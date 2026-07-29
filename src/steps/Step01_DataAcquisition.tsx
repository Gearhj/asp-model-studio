import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Check, Loader2, ShieldCheck } from "lucide-react";
import StepShell from "../components/StepShell";
import BureauReviewPanel from "../components/BureauReviewPanel";
import { AtlasStatusStrip, type AtlasStatusItem, type AtlasWorkflowMetric } from "../components/ui/AtlasWorkflow";
import { logDecision } from "../lib/decisionJournal";
import {
  BROWSER_PARSE_EXTENSIONS,
  DEFAULT_BROWSER_MAX_COLUMNS,
  DEFAULT_BROWSER_MAX_ROWS,
  backendImportFailureMessage,
  buildSelectedDatasetView,
  dataAcquisitionDisabledReason,
  getUploadDecision,
  guessTargetFromHeaders,
  normalizeBackendImportResponse,
  type NormalizedBackendImport,
} from "../lib/dataAcquisitionUpload";
import {
  buildDataAccessMetadata,
  fetchFullDataQualityProfile,
  inferDataQuality,
  loadDataAccessMetadata,
  loadDatasetVersions,
  queryTemplates,
  recordDatasetVersion,
  saveDataAccessMetadata,
  validateSql,
  type DataAccessMetadata,
  type DataQualitySummary,
  type DataSourceType,
  type SamplingMethod,
} from "../lib/enterpriseDataAccess";
import { loadLocalDataset, saveLocalDataset, type LocalDataset } from "../lib/localDataset";
import {
  activateDatasetVersion,
  findSimilarDatasets,
  getDatasetPreview,
  linkDatasetToProject,
  listDatasets,
  registerWorkspaceDataset,
  type DatasetSummary,
} from "../lib/datasetLibrary";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { fetchFullFeatureProfile, predictorEligibility, profileFeaturesInBrowser, type FeatureProfileResponse } from "../lib/featureProfiling";
import {
  formatEventRatePrecise,
  ivCellText,
  formatIvExact,
  planWeakSignalExclusion,
  IV_STATUS_LABELS,
  WEAK_SIGNAL_IV_THRESHOLD,
  type PredictorProfile,
  signalStrength,
  leakageScreen,
  LEAKAGE_SCREEN_LABELS,
  predictorEvaluationCounts,
  HIGH_IV_EXPLANATION,
} from "../lib/governedProfile";
import { useTargetProfile } from "../lib/useTargetProfile";
import {
  deriveDataAcquisitionStatus,
  projectLinkLabel,
  registrationLabel,
  type DataAcquisitionStatus,
} from "../lib/dataAcquisitionStatus";
import {
  DATASET_SOURCE_LABELS,
  EVENT_RATE_SCOPE_LABELS,
  DATASET_LOAD_STAGES,
  IDLE_LOAD_PROGRESS,
  READINESS_LABELS,
  READINESS_TONES,
  buildTargetDistribution,
  computeClassDistributionFromRows,
  computeReadinessStatus,
  formatEventRate,
  isAlreadyLinked,
  resolveAuthoritativeEventRate,
  resolveDatasetSourceKind,
  resolvePersistenceMode,
  resolveRegistrationActionLabel,
  type DatasetLibraryLink,
  type DatasetLoadProgress,
  type DatasetSourceKind,
  type PersistenceMode,
  type ReadinessStatus,
} from "../lib/dataAcquisitionLifecycle";
import DatasetLoadProgressPanel from "../components/dataAcquisition/DatasetLoadProgressPanel";
import TargetDistributionPanel from "../components/dataAcquisition/TargetDistributionPanel";
import { useTargetDistribution } from "../lib/useTargetDistribution";

const BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

const sourceCards: { id: DataSourceType; title: string; body: string }[] = [
  { id: "upload", title: "Upload File", body: "CSV and JSON parse locally. Excel, Parquet, Feather, SAS, and ZIP are staged for backend import." },
  { id: "existing", title: "Existing Dataset", body: "Reuse a registered Dataset Library asset and preserve its governed version history." },
  { id: "sql", title: "SQL Database", body: "Author governed SQL, validate queries, capture lineage, and generate Python extraction code." },
  { id: "python", title: "Python Loader", body: "Advanced users can document Python or Spark loading logic that assigns the final dataframe to df." },
  { id: "cloud", title: "Cloud Storage", body: "Document S3, Azure Blob, GCS, SharePoint, or OneDrive paths for governed ingestion." },
];

const WEAK_IV_THRESHOLD = 0.01;
const WEAK_CORRELATION_THRESHOLD = 0.05;

const databaseProviders = ["Oracle", "SQL Server", "PostgreSQL", "MySQL", "Snowflake", "BigQuery", "Databricks SQL", "Teradata", "SQLite", "DuckDB"];
const cloudProviders = ["AWS S3", "Azure Blob Storage", "Google Cloud Storage", "SharePoint", "OneDrive"];

function parseDelimitedLine(line: string) {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"') inQuotes = !inQuotes;
    else if (c === "," && !inQuotes) {
      out.push(cur);
      cur = "";
    } else {
      cur += c;
    }
  }
  out.push(cur);
  return out.map((value) => value.replace(/^"(.*)"$/s, "$1").trim());
}

function coerce(value: string) {
  if (value === "") return "";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : value;
}

export function parseCSV(text: string) {
  const lines = text.replace(/\r/g, "").split("\n").filter((line) => line.trim().length);
  if (!lines.length) return { headers: [] as string[], rows: [] as Record<string, unknown>[] };
  const headers = parseDelimitedLine(lines[0]);
  const rows = lines.slice(1).map((line) => {
    const values = parseDelimitedLine(line);
    const row: Record<string, unknown> = {};
    headers.forEach((header, index) => {
      row[header] = coerce(values[index] ?? "");
    });
    return row;
  });
  return { headers, rows };
}

export function parseJSON(text: string) {
  const parsed = JSON.parse(text);
  const rows = Array.isArray(parsed) ? parsed : Array.isArray(parsed?.data) ? parsed.data : [];
  if (!Array.isArray(rows) || !rows.length) return { headers: [] as string[], rows: [] as Record<string, unknown>[] };
  const headers = Array.from(new Set(rows.flatMap((row) => Object.keys(row ?? {}))));
  return { headers, rows: rows as Record<string, unknown>[] };
}

function isNumericVector(vals: unknown[]) {
  const nonMissing = vals.filter((value) => value !== null && value !== undefined && String(value).trim() !== "");
  if (!nonMissing.length) return false;
  return nonMissing.filter((value) => Number.isFinite(Number(value))).length / nonMissing.length >= 0.6;
}

function targetMeta(rows: Record<string, unknown>[], target: string) {
  if (!target) return { kind: "none" as const, eventRate: null as number | null };
  const vals = rows.map((row) => row[target]);
  if (!isNumericVector(vals)) {
    const counts = new Map<string, number>();
    vals.forEach((value) => counts.set(String(value), (counts.get(String(value)) ?? 0) + 1));
    const sorted = Array.from(counts.values()).sort((a, b) => b - a);
    const total = sorted.reduce((sum, count) => sum + count, 0);
    const event = total - (sorted[0] ?? 0);
    return { kind: "binary" as const, eventRate: total ? event / total : null };
  }
  const ones = vals.filter((value) => Number(value) === 1).length;
  const zeros = vals.filter((value) => Number(value) === 0).length;
  if (ones + zeros >= vals.length * 0.8) return { kind: "binary" as const, eventRate: vals.length ? ones / vals.length : null };
  return { kind: "continuous" as const, eventRate: null };
}

function inferProblemType(rows: Record<string, unknown>[], target: string) {
  return targetMeta(rows, target).kind === "continuous" ? "regression" : "classification";
}

function summarizeColumn(rows: Record<string, unknown>[], column: string, target: string) {
  const values = rows.map((row) => row[column]);
  const missing = values.filter((value) => value === null || value === undefined || String(value).trim() === "").length;
  const numeric = isNumericVector(values);
  const distinct = new Set(values.map(String)).size;
  if (!numeric) return { type: "Categorical", missingPct: rows.length ? missing / rows.length : 0, distinct, mean: null, min: null, max: null };
  const nums = values.map(Number).filter(Number.isFinite);
  const mean = nums.length ? nums.reduce((sum, value) => sum + value, 0) / nums.length : null;
  return {
    type: column === target ? "Target" : "Numeric",
    missingPct: rows.length ? missing / rows.length : 0,
    distinct,
    mean,
    min: nums.length ? Math.min(...nums) : null,
    max: nums.length ? Math.max(...nums) : null,
  };
}

function numericValues(rows: Record<string, unknown>[], column: string) {
  return rows.map((row) => Number(row[column])).filter(Number.isFinite);
}

function targetSummary(rows: Record<string, unknown>[], target: string) {
  const nums = numericValues(rows, target).sort((a, b) => a - b);
  if (!nums.length) return null;
  const mean = nums.reduce((sum, value) => sum + value, 0) / nums.length;
  const variance = nums.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(1, nums.length - 1);
  return {
    mean,
    median: nums[Math.floor(nums.length / 2)],
    std: Math.sqrt(variance),
    min: nums[0],
    max: nums[nums.length - 1],
  };
}

function getBinaryTargetProfile(rows: Record<string, unknown>[], target: string) {
  if (!target) return null;
  const values = rows
    .map((row) => row[target])
    .filter((value) => value !== null && value !== undefined && String(value).trim() !== "");
  if (!values.length) return null;

  const numericCount = values.filter((value) => Number.isFinite(Number(value))).length;
  if (numericCount / values.length >= 0.8) {
    const ones = values.filter((value) => Number(value) === 1).length;
    const zeros = values.filter((value) => Number(value) === 0).length;
    if (ones + zeros >= values.length * 0.8) {
      return { isEvent: (value: unknown) => Number(value) === 1 };
    }
  }

  const counts = new Map<string, number>();
  values.forEach((value) => counts.set(String(value), (counts.get(String(value)) ?? 0) + 1));
  if (counts.size < 2 || counts.size > 20) return null;
  const majority = Array.from(counts.entries()).sort((a, b) => b[1] - a[1])[0]?.[0];
  if (majority === undefined) return null;
  return { isEvent: (value: unknown) => String(value) !== majority };
}

function preferredTarget(headers: string[], fallbackTarget = "") {
  return (fallbackTarget && headers.includes(fallbackTarget) ? fallbackTarget : "") || guessTargetFromHeaders(headers);
}

function quantileBreaks(nums: number[], bins = 10) {
  const sorted = [...nums].sort((a, b) => a - b);
  const breaks: number[] = [];
  for (let i = 1; i < bins; i++) {
    const index = Math.floor((i / bins) * (sorted.length - 1));
    const value = sorted[index];
    if (Number.isFinite(value) && !breaks.includes(value)) breaks.push(value);
  }
  return breaks;
}

function informationValue(rows: Record<string, unknown>[], column: string, target: string) {
  if (!target || column === target || !rows.length) return null;
  const targetProfile = getBinaryTargetProfile(rows, target);
  if (!targetProfile) return null;

  const featureValues = rows.map((row) => row[column]);
  const numeric = isNumericVector(featureValues);
  const numericValues = featureValues.map(Number).filter(Number.isFinite);
  const breaks = numeric && new Set(numericValues).size > 10 ? quantileBreaks(numericValues, 10) : [];
  const rawCategoryCounts = new Map<string, number>();
  if (!numeric) {
    featureValues.forEach((value) => {
      const key = value === null || value === undefined || String(value).trim() === "" ? "__MISSING__" : String(value);
      rawCategoryCounts.set(key, (rawCategoryCounts.get(key) ?? 0) + 1);
    });
  }
  const topCategories = new Set(
    Array.from(rawCategoryCounts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20)
      .map(([key]) => key)
  );

  const bucketFor = (value: unknown) => {
    if (value === null || value === undefined || String(value).trim() === "") return "__MISSING__";
    if (!numeric) {
      const key = String(value);
      return topCategories.has(key) ? key : "__OTHER__";
    }
    const num = Number(value);
    if (!Number.isFinite(num)) return "__MISSING__";
    const upper = breaks.find((breakValue) => num <= breakValue);
    return upper === undefined ? `>${breaks.length ? breaks[breaks.length - 1] : "all"}` : `<=${upper}`;
  };

  const buckets = new Map<string, { event: number; nonEvent: number }>();
  let totalEvents = 0;
  let totalNonEvents = 0;
  rows.forEach((row) => {
    const targetValue = row[target];
    if (targetValue === null || targetValue === undefined || String(targetValue).trim() === "") return;
    const key = bucketFor(row[column]);
    const bucket = buckets.get(key) ?? { event: 0, nonEvent: 0 };
    if (targetProfile.isEvent(targetValue)) {
      bucket.event += 1;
      totalEvents += 1;
    } else {
      bucket.nonEvent += 1;
      totalNonEvents += 1;
    }
    buckets.set(key, bucket);
  });

  if (!totalEvents || !totalNonEvents || !buckets.size) return null;
  const epsilon = 0.000001;
  let iv = 0;
  buckets.forEach((bucket) => {
    const eventDist = Math.max(bucket.event / totalEvents, epsilon);
    const nonEventDist = Math.max(bucket.nonEvent / totalNonEvents, epsilon);
    iv += (eventDist - nonEventDist) * Math.log(eventDist / nonEventDist);
  });
  return Number.isFinite(iv) ? Math.max(0, iv) : null;
}

function correlationWithTarget(rows: Record<string, unknown>[], column: string, target: string) {
  if (!target || column === target || !rows.length) return null;
  const pairs = rows
    .map((row) => ({ x: Number(row[column]), y: Number(row[target]) }))
    .filter((row) => Number.isFinite(row.x) && Number.isFinite(row.y));
  if (pairs.length < 3) return null;
  const meanX = pairs.reduce((sum, row) => sum + row.x, 0) / pairs.length;
  const meanY = pairs.reduce((sum, row) => sum + row.y, 0) / pairs.length;
  const numerator = pairs.reduce((sum, row) => sum + (row.x - meanX) * (row.y - meanY), 0);
  const denomX = Math.sqrt(pairs.reduce((sum, row) => sum + (row.x - meanX) ** 2, 0));
  const denomY = Math.sqrt(pairs.reduce((sum, row) => sum + (row.y - meanY) ** 2, 0));
  const corr = numerator / ((denomX || 0) * (denomY || 0));
  return Number.isFinite(corr) ? corr : null;
}

function formatNumber(value: unknown, digits = 4) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : "-";
}

function formatPercent(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${(numeric * 100).toFixed(2)}%` : "-";
}

function ivStatusClass(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "bg-slate-50 text-slate-400";
  if (numeric >= 0.02) return "bg-emerald-100 font-semibold text-emerald-900";
  return "bg-red-100 font-semibold text-red-900";
}

function signalStatusClass(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "bg-slate-50 text-slate-400";
  if (Math.abs(numeric) >= 0.1) return "bg-emerald-100 font-semibold text-emerald-900";
  return "bg-red-100 font-semibold text-red-900";
}

function seededRandom(seed: number) {
  let value = Math.max(1, Math.floor(seed)) % 2147483647;
  return () => {
    value = (value * 16807) % 2147483647;
    return (value - 1) / 2147483646;
  };
}

function applyPreviewSampling(input: {
  rows: Record<string, unknown>[];
  method: SamplingMethod;
  rowLimit: number;
  seed: number;
  stratificationColumn?: string;
  timeColumn?: string;
}) {
  const rowLimit = Math.max(1, Math.min(input.rows.length, input.rowLimit));
  if (input.method === "full") return input.rows;
  if (input.method === "random") {
    const random = seededRandom(input.seed);
    return input.rows.map((row) => ({ row, order: random() })).sort((a, b) => a.order - b.order).slice(0, rowLimit).map((item) => item.row);
  }
  if (input.method === "stratified" && input.stratificationColumn) {
    const groups = new Map<string, Record<string, unknown>[]>();
    input.rows.forEach((row) => {
      const key = String(row[input.stratificationColumn as string] ?? "__MISSING__");
      groups.set(key, [...(groups.get(key) ?? []), row]);
    });
    const output: Record<string, unknown>[] = [];
    groups.forEach((group) => {
      const take = Math.max(1, Math.round((group.length / input.rows.length) * rowLimit));
      output.push(...group.slice(0, take));
    });
    return output.slice(0, rowLimit);
  }
  if (input.method === "time_based" && input.timeColumn) {
    return [...input.rows].sort((a, b) => String(a[input.timeColumn as string] ?? "").localeCompare(String(b[input.timeColumn as string] ?? ""))).slice(0, rowLimit);
  }
  return input.rows.slice(0, rowLimit);
}

export default function Step01DataAcquisition() {
  const [sourceType, setSourceType] = useState<DataSourceType>("upload");
  const [headers, setHeaders] = useState<string[]>([]);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [fileName, setFileName] = useState("");
  const [message, setMessage] = useState("");
  const [target, setTarget] = useState("");
  const [kept, setKept] = useState<Record<string, boolean>>({});
  const [autoExcludeWeakSignals, setAutoExcludeWeakSignals] = useState(false);
  const [previewSamplingMethod, setPreviewSamplingMethod] = useState<SamplingMethod>("top_n");
  const [previewRowLimit, setPreviewRowLimit] = useState(100);
  const [profileRowLimit, setProfileRowLimit] = useState(5000);
  const [previewRandomSeed, setPreviewRandomSeed] = useState(42);
  const [previewStratificationColumn, setPreviewStratificationColumn] = useState("");
  const [previewTimeColumn, setPreviewTimeColumn] = useState("");
  const [browserDataComplete, setBrowserDataComplete] = useState(false);
  const [eventValue, setEventValue] = useState<unknown>(1);
  const [nonEventValue, setNonEventValue] = useState<unknown>(0);
  const [connectionName, setConnectionName] = useState("Development connection");
  const [provider, setProvider] = useState("Oracle");
  const [database, setDatabase] = useState("");
  const [schema, setSchema] = useState("");
  const [sql, setSql] = useState(queryTemplates()[0].sql);
  const [savedQueries, setSavedQueries] = useState<string[]>([]);
  const [favoriteQueries, setFavoriteQueries] = useState<string[]>([]);
  const [cloudProvider, setCloudProvider] = useState("AWS S3");
  const [cloudPath, setCloudPath] = useState("");
  const [pythonCode, setPythonCode] = useState("import pandas as pd\n\n# Assign final dataframe to df\n# df = pd.read_sql(...)\n");
  const [metadata, setMetadata] = useState<DataAccessMetadata | null>(() => loadDataAccessMetadata());
  const [quality, setQuality] = useState<DataQualitySummary | null>(null);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [featureProfile, setFeatureProfile] = useState<FeatureProfileResponse | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [backendImportSynced, setBackendImportSynced] = useState(false);
  const [backendRowCount, setBackendRowCount] = useState<number | null>(null);
  const [libraryDatasets, setLibraryDatasets] = useState<DatasetSummary[]>([]);
  const [selectedLibraryDatasetId, setSelectedLibraryDatasetId] = useState("");
  const [selectedLibraryVersionId, setSelectedLibraryVersionId] = useState("");
  const [libraryLoading, setLibraryLoading] = useState(false);
  // Part A/H1: which dataset+version was actually loaded, plus the real load
  // milestones. Identity is tracked by datasetId/versionId (never by display
  // name or filename) so changing either selector honestly resets the action.
  const [loadedLibraryIdentity, setLoadedLibraryIdentity] = useState<{ datasetId: string; versionId: string } | null>(null);
  // Governed target-dependent profiling. The analytical identity includes the
  // dataset version AND the event mapping, so changing either invalidates every
  // target-dependent result rather than leaving stale IV on screen.
  const [weakSignalUndo, setWeakSignalUndo] = useState<Record<string, boolean> | null>(null);
  const [weakSignalNotice, setWeakSignalNotice] = useState("");
  const [loadProgress, setLoadProgress] = useState<DatasetLoadProgress>(IDLE_LOAD_PROGRESS);
  const datasetVersions = loadDatasetVersions();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);

  // Dataset Persistence (dataset lifecycle audit): explicit workspace-only vs
  // register-to-Library choice, defaulting to workspace-only per the ADR.
  const [persistenceChoice, setPersistenceChoice] = useState<"workspace" | "register">("workspace");
  const [registerName, setRegisterName] = useState("");
  const [registerDescription, setRegisterDescription] = useState("");
  const [registerTags, setRegisterTags] = useState("");
  const [registering, setRegistering] = useState(false);
  const [registrationResult, setRegistrationResult] = useState<DatasetSummary | null>(null);
  const [registrationError, setRegistrationError] = useState("");
  const [duplicateCandidates, setDuplicateCandidates] = useState<DatasetSummary[]>([]);
  const [checkingDuplicates, setCheckingDuplicates] = useState(false);

  useEffect(() => {
    const saved = loadLocalDataset();
    if (!saved?.headers.length) return;

    const savedTarget = saved.target ?? "";
    const selectedSet = new Set(saved.selected_columns ?? []);
    setHeaders(saved.headers);
    setRows(saved.rows ?? []);
    setTarget(savedTarget);
    setEventValue(saved.event_value ?? 1);
    setNonEventValue(saved.non_event_value ?? 0);
    setBrowserDataComplete(saved.browser_data_complete === true);
    setKept(
      Object.fromEntries(
        saved.headers.map((header) => [header, header !== savedTarget && selectedSet.has(header)])
      )
    );
    setImportError(null);
    setBackendImportSynced(false);
    setBackendRowCount(saved.registered_row_count ?? null);
    setMessage((current) => current || "Restored the cached modeling dataset and selected features for this browser session.");
    setQuality(
      saved.data_quality ??
        inferDataQuality({ headers: saved.headers, rows: saved.rows ?? [], target: savedTarget || null })
    );
    if (saved.data_access) setMetadata(saved.data_access);
  }, []);

  useEffect(() => {
    if (sourceType !== "existing") return;
    let alive = true;
    setLibraryLoading(true);
    listDatasets()
      .then((payload) => {
        if (!alive) return;
        setLibraryDatasets(payload.datasets);
        const first = payload.datasets[0];
        if (first && !selectedLibraryDatasetId) {
          setSelectedLibraryDatasetId(first.datasetId);
          setSelectedLibraryVersionId(first.latestVersion?.versionId ?? "");
        }
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "ATLAS could not load Dataset Library records."))
      .finally(() => alive && setLibraryLoading(false));
    return () => {
      alive = false;
    };
  }, [sourceType, selectedLibraryDatasetId]);

  const fullSourceRows = rows;
  const registeredRowCount = backendRowCount ?? fullSourceRows.length;
  const completeBrowserDataset = browserDataComplete && fullSourceRows.length === registeredRowCount;
  const previewRows = useMemo(() => applyPreviewSampling({
    rows: fullSourceRows,
    method: previewSamplingMethod,
    rowLimit: previewRowLimit,
    seed: previewRandomSeed,
    stratificationColumn: previewStratificationColumn,
    timeColumn: previewTimeColumn,
  }), [fullSourceRows, previewSamplingMethod, previewRowLimit, previewRandomSeed, previewStratificationColumn, previewTimeColumn]);
  const profilingRows = useMemo(
    () => fullSourceRows.slice(0, Math.max(1, profileRowLimit)),
    [fullSourceRows, profileRowLimit]
  );
  const targetAnalysisRows = completeBrowserDataset ? fullSourceRows : profilingRows;
  const targetInfo = useMemo(() => targetMeta(targetAnalysisRows, target), [targetAnalysisRows, target]);

  // UX-DATAACQ-004 / Part C: the active source's governed identity decides which
  // persistence UI applies. `datasetLibraryLink` is the authoritative signal --
  // it is only ever written with a real datasetId/versionId pair.
  const datasetLibraryLink = useMemo(() => loadLocalDataset()?.dataset_library ?? null, [headers, fileName, backendImportSynced, loadedLibraryIdentity]);
  const datasetSourceKind: DatasetSourceKind = useMemo(
    () =>
      resolveDatasetSourceKind({
        sourceType,
        libraryLink: datasetLibraryLink,
        registeredDatasetId: registrationResult?.datasetId ?? null,
      }),
    [sourceType, datasetLibraryLink, registrationResult]
  );
  const persistenceMode = resolvePersistenceMode(datasetSourceKind);

  // Part F: the Target Profile must not report a rare-event rate computed from a
  // ~100-row browser preview. Backend full-population profiling wins when present.
  const governedProfileRequest = useMemo(
    () =>
      target
        ? {
            projectId,
            datasetId: loadedLibraryIdentity?.datasetId ?? null,
            versionId: loadedLibraryIdentity?.versionId ?? null,
            target,
            eventValue,
            nonEventValue,
            problemType: (targetInfo.kind === "continuous" ? "regression" : "classification") as
              | "regression"
              | "classification",
          }
        : null,
    [projectId, loadedLibraryIdentity, target, eventValue, nonEventValue, targetInfo.kind]
  );
  const governedProfile = useTargetProfile(governedProfileRequest);
  const governedPredictors = useMemo(() => {
    const map = new Map<string, PredictorProfile>();
    for (const row of governedProfile.profile?.predictors ?? []) map.set(row.predictor, row);
    return map;
  }, [governedProfile.profile]);

  const authoritativeEventRate = useMemo(
    () => {
      // Part I: the governed profile is the source of truth for the event rate.
      // Only when no authoritative profile exists does the previous resolver run.
      const governed = governedProfile.quality ?? governedProfile.profile;
      if (governed && governed.quality.eventRate !== null) {
        return {
          rate: governed.quality.eventRate,
          scope: "full_population" as const,
          isAuthoritative: governed.analysisScope.mode !== "preview_only",
        };
      }
      return resolveAuthoritativeEventRate({ quality, previewEventRate: targetInfo.eventRate, completeBrowserDataset });
    },
    [governedProfile.quality, governedProfile.profile, quality, targetInfo.eventRate, completeBrowserDataset]
  );

  // Target Distribution performance: for a registered Dataset Library version the
  // counts come from a dedicated bounded server aggregate that loads independently
  // of quality profiling. Reading them out of the full quality profile cost ~4s of
  // server compute on the 170,884-row CLASS_TRAIN asset just to obtain two rows.
  const targetDistributionRequest = useMemo(() => {
    if (!target || targetInfo.kind === "continuous") return null;
    if (!datasetLibraryLink?.datasetId || !datasetLibraryLink?.versionId) return null;
    return {
      projectId,
      datasetId: datasetLibraryLink.datasetId,
      versionId: datasetLibraryLink.versionId,
      target,
      eventValue,
      nonEventValue,
    };
  }, [target, targetInfo.kind, datasetLibraryLink?.datasetId, datasetLibraryLink?.versionId, projectId, eventValue, nonEventValue]);

  const serverDistribution = useTargetDistribution(targetDistributionRequest);

  // A workspace dataset the browser already holds in full needs no server round
  // trip -- those counts are already exact and instant.
  const localDistribution = useMemo(
    () =>
      targetDistributionRequest
        ? null
        : buildTargetDistribution({
            target,
            classDistribution: quality?.classDistribution,
            eventValue: quality?.targetEventValue ?? eventValue,
            nonEventValue,
          }),
    [targetDistributionRequest, target, quality?.classDistribution, quality?.targetEventValue, eventValue, nonEventValue]
  );

  const targetDistribution = useMemo(() => {
    if (!targetDistributionRequest) return localDistribution;
    if (!serverDistribution.result?.supported) return null;
    return buildTargetDistribution({
      target,
      classDistribution: serverDistribution.result.classDistribution,
      eventValue,
      nonEventValue,
    });
  }, [targetDistributionRequest, localDistribution, serverDistribution.result, target, eventValue, nonEventValue]);

  const targetDistributionState = useMemo(() => {
    if (!target) return "empty" as const;
    if (targetInfo.kind === "continuous") return "unsupported" as const;
    if (targetDistributionRequest) {
      if (serverDistribution.phase === "queued" || serverDistribution.phase === "running") return "loading" as const;
      if (serverDistribution.phase === "failed") return "error" as const;
      if (serverDistribution.phase === "unsupported") return "unsupported" as const;
      return targetDistribution ? ("ready" as const) : ("empty" as const);
    }
    if (qualityLoading || !quality) return "loading" as const;
    return targetDistribution ? ("ready" as const) : ("empty" as const);
  }, [target, targetInfo.kind, targetDistributionRequest, serverDistribution.phase, qualityLoading, quality, targetDistribution]);
  const continuousTargetSummary = useMemo(() => targetSummary(targetAnalysisRows, target), [targetAnalysisRows, target]);
  const selectable = headers.filter((header) => header !== target);
  const selected = selectable.filter((header) => kept[header]);
  // Part D: a single readiness status derived only from findings ATLAS already computes.

  // Part B: ONE derivation feeds every Data Acquisition status. Previously the
  // hero used `nextDisabledReason`, the strip used `readiness.status`, and the
  // checkpoint used READINESS_LABELS -- three answers to one question.
  const [dataAcquisitionReviewed, setDataAcquisitionReviewed] = useState(false);
  const acquisitionStatus = useMemo(
    () =>
      deriveDataAcquisitionStatus({
        hasSelectedVersion: Boolean(loadedLibraryIdentity?.versionId || selectedLibraryVersionId || headers.length),
        isRegisteredAsset: Boolean(loadedLibraryIdentity?.datasetId || selectedLibraryDatasetId || datasetLibraryLink?.datasetId),
        isLinkedToProject: Boolean(datasetLibraryLink?.datasetId || loadedLibraryIdentity?.datasetId),
        isLoaded: Boolean(headers.length && backendImportSynced),
        isLoading: isImporting,
        loadError: importError,
        target,
        eventValue,
        nonEventValue,
        selectedPredictorCount: selected.length,
        profilePhase: governedProfile.phase,
        profileError: governedProfile.error,
        authoritativeEventCount: governedProfile.profile?.quality.eventCount ?? governedProfile.quality?.quality.eventCount ?? null,
        authoritativeNonEventCount: governedProfile.profile?.quality.nonEventCount ?? governedProfile.quality?.quality.nonEventCount ?? null,
        duplicateRows: governedProfile.quality?.quality.duplicateRows ?? governedProfile.profile?.quality.duplicateRows ?? null,
        columnsWithMissingValues:
          governedProfile.quality?.quality.columnsWithMissingValues ?? governedProfile.profile?.quality.columnsWithMissingValues ?? null,
        unusuallyStrongPredictorCount: (governedProfile.profile?.predictors ?? []).filter(
          (row) => row.ivStatus === "available" && (row.iv ?? 0) >= 0.5
        ).length,
        isRareEvent: Boolean(
          (governedProfile.quality?.quality.eventRate ?? governedProfile.profile?.quality.eventRate ?? 0) > 0 &&
            (governedProfile.quality?.quality.eventRate ?? governedProfile.profile?.quality.eventRate ?? 1) < 0.01
        ),
        reviewCompleted: dataAcquisitionReviewed,
      }),
    [
      loadedLibraryIdentity, selectedLibraryVersionId, selectedLibraryDatasetId, datasetLibraryLink,
      headers.length, backendImportSynced, isImporting, importError, target, eventValue, nonEventValue,
      selected.length, governedProfile.phase, governedProfile.error, governedProfile.profile,
      governedProfile.quality, dataAcquisitionReviewed,
    ]
  );

  const readiness = useMemo(
    () =>
      computeReadinessStatus({
        quality,
        target,
        registeredRowCount,
        selectedPredictorCount: selected.length,
        profileScopeMode: governedProfile.profile?.analysisScope.mode ?? governedProfile.quality?.analysisScope.mode ?? null,
        authoritativeEventCount: governedProfile.quality?.quality.eventCount ?? governedProfile.profile?.quality.eventCount ?? null,
      }),
    [quality, target, registeredRowCount, selected.length, governedProfile.profile, governedProfile.quality]
  );
  const sqlWarnings = useMemo(() => validateSql(sql), [sql]);
  const generatedMetadata = useMemo(() => {
    if (!headers.length) return null;
    return buildDataAccessMetadata({
      dataset: { headers, rows: completeBrowserDataset ? fullSourceRows : profilingRows, target },
      sourceType,
      sourceLabel:
        sourceType === "sql"
          ? `${provider} SQL`
          : sourceType === "cloud"
            ? cloudProvider
            : sourceType === "python"
              ? "Python loader"
              : sourceType === "existing"
                ? `Dataset Library: ${libraryDatasets.find((dataset) => dataset.datasetId === selectedLibraryDatasetId)?.name ?? (fileName || "Existing dataset")}`
                : fileName || "Uploaded file",
      fileName,
      fileType: fileName.split(".").pop(),
      connectionName,
      provider,
      database,
      schema,
      sqlQuery: sourceType === "sql" ? sql : undefined,
      cloudProvider: sourceType === "cloud" ? cloudProvider : undefined,
      cloudPath: sourceType === "cloud" ? cloudPath : undefined,
      pythonCode: sourceType === "python" ? pythonCode : undefined,
      samplingMethod: "full",
      samplingDetail: "Registered modeling dataset",
      rowCountOverride: registeredRowCount,
    });
  }, [headers, fullSourceRows, profilingRows, completeBrowserDataset, target, sourceType, provider, cloudProvider, fileName, connectionName, database, schema, sql, cloudPath, pythonCode, registeredRowCount, libraryDatasets, selectedLibraryDatasetId]);


  /** IV for one predictor from the authoritative profile. While the profile is
   *  still running every eligible predictor reports `pending` ("Calculating"),
   *  never a zero placeholder. */
  function governedIv(column: string): Pick<PredictorProfile, "iv" | "ivStatus"> {
    const row = governedPredictors.get(column);
    if (row) return { iv: row.iv, ivStatus: row.ivStatus };
    if (governedProfile.phase === "artifact_missing") return { iv: null, ivStatus: "unavailable_not_eligible" };
    if (governedProfile.phase === "failed") return { iv: null, ivStatus: "failed" };
    return { iv: null, ivStatus: "pending" };
  }

  // Part F: counts by analytical role. The target is never counted as an
  // unavailable predictor.
  const predictorCounts = useMemo(
    () => predictorEvaluationCounts(governedProfile.profile, target),
    [governedProfile.profile, target]
  );

  const variableSummary = useMemo(
    () => (featureProfile?.features ?? []).map((row) => ({
      column: row.predictor,
      type: row.datatype,
      missingPct: row.missingPercent,
      distinct: row.distinctCount,
      mean: row.mean,
      min: row.minimum,
      max: row.maximum,
      // Root causes 1-3: IV now comes from the authoritative server profile and
      // carries an explicit status. `null` stays `null` -- it is never coerced
      // to a number, and therefore never rendered as a misleading 0.0000.
      iv: row.iv,
      corr: row.correlationWithTarget,
      role: row.role,
      exclusionReason: row.exclusionReason,
    })),
    [featureProfile]
  );

  useEffect(() => {
    if (!headers.length || !target || !profilingRows.length) {
      setFeatureProfile(null);
      return;
    }
    let alive = true;
    const profileDataset: LocalDataset = {
      headers,
      rows: profilingRows,
      target,
      selected_columns: selected,
      problem_type: targetInfo.kind === "continuous" ? "regression" : "classification",
      registered_row_count: registeredRowCount,
      browser_data_complete: completeBrowserDataset,
      event_value: eventValue,
      non_event_value: nonEventValue,
    };
    const browserProfile = () => profileFeaturesInBrowser(
      profileDataset,
      completeBrowserDataset ? fullSourceRows : profilingRows,
      completeBrowserDataset ? "complete_browser_dataset" : "preview_profile",
    );
    if (backendImportSynced) {
      // Root cause 2: this used to `.catch(() => setFeatureProfile(browserProfile()))`,
      // silently replacing a failed governed profile with a 100-row preview
      // computation that still reported itself as full_dataset. A failure is now
      // a failure: the authoritative profile hook surfaces it, and the browser
      // profile is never substituted for target-dependent statistics.
      fetchFullFeatureProfile(profileDataset, projectId)
        .then((payload) => alive && setFeatureProfile(payload))
        .catch(() => alive && setFeatureProfile(null));
    } else {
      // No backend population at all: the browser profile is retained ONLY for
      // its non-target-dependent inspection columns. Its scope says preview, and
      // IV comes from the authoritative profile (or reports why it cannot).
      setFeatureProfile(browserProfile());
    }
    return () => {
      alive = false;
    };
  }, [headers, target, profilingRows, fullSourceRows, selected.join("|"), targetInfo.kind, registeredRowCount, completeBrowserDataset, backendImportSynced, eventValue, nonEventValue]);

  useEffect(() => {
    if (!headers.length || !profilingRows.length) {
      setQuality(null);
      return;
    }
    let alive = true;
    const browserQuality = () => {
      const base = inferDataQuality({ headers, rows: completeBrowserDataset ? fullSourceRows : profilingRows, target: target || null });
      return {
        ...base,
        // Part H3/2: class counts are only supplied when the browser genuinely holds
        // the complete registered dataset. For a bounded preview they are omitted, so
        // the distribution chart shows an honest empty state rather than preview-derived
        // proportions that would misrepresent a rare-event population.
        classDistribution: completeBrowserDataset
          ? computeClassDistributionFromRows(fullSourceRows, target) ?? undefined
          : undefined,
        targetEventValue: completeBrowserDataset ? eventValue : undefined,
        profileScope: completeBrowserDataset ? "complete_browser_dataset" as const : "preview_profile" as const,
        profiledRowCount: completeBrowserDataset ? fullSourceRows.length : profilingRows.length,
        registeredRowCount,
        rowCount: registeredRowCount,
        warnings: completeBrowserDataset ? base.warnings : ["This report is based on configured profiling rows, not the full registered dataset."],
        readinessStatus: "needs_review" as const,
      };
    };
    if (backendImportSynced) {
      // Part H3/10: reject stale asynchronous results. `alive` is flipped by this
      // effect's own cleanup, so a response that arrives after the project,
      // dataset/version, or target changed is discarded instead of overwriting
      // the newer selection's profile.
      setQualityLoading(true);
      fetchFullDataQualityProfile({ projectId, target, eventValue, nonEventValue, selectedColumns: selected })
        .then((payload) => {
          if (!alive) return;
          setQuality(payload);
        })
        .catch((error) => {
          if (!alive) return;
          // No silent downgrade. The page shows that governed quality profiling
          // failed rather than presenting preview statistics as registered-
          // population findings.
          setQuality(null);
          setMessage(
            error instanceof Error
              ? `Full-population data quality profiling failed: ${error.message}`
              : "Full-population data quality profiling failed."
          );
        })
        .finally(() => alive && setQualityLoading(false));
    } else {
      setQualityLoading(false);
      setQuality(browserQuality());
    }
    return () => {
      alive = false;
    };
  }, [headers, target, profilingRows, fullSourceRows, completeBrowserDataset, registeredRowCount, backendImportSynced, eventValue, nonEventValue, selected.join("|"), projectId, loadedLibraryIdentity]);

  function saveKeptSelection(nextKept: Record<string, boolean>) {
    setKept(nextKept);
    const currentDataset = loadLocalDataset();
    const localView = buildSelectedDatasetView({
      headers,
      rows: profilingRows,
      selectedColumns: headers.filter((header) => header !== target && predictorEligibility(header, {
        headers,
        rows: profilingRows,
        target,
        selected_columns: [],
      }).role === "eligible" && nextKept[header] !== false),
      target: target || null,
    });
    saveLocalDataset({
      headers: localView.headers,
      rows: localView.rows,
      target: target || null,
      selected_columns: localView.selectedColumns,
      problem_type: target ? inferProblemType(localView.rows, target) : undefined,
      registered_row_count: registeredRowCount,
      browser_data_complete: completeBrowserDataset,
      event_value: eventValue,
      non_event_value: nonEventValue,
      dataset_library: currentDataset?.dataset_library,
    });
    window.dispatchEvent(new CustomEvent("atlas-dataset-updated"));
  }

  // Part H: automatic weak-signal exclusion, hardened.
  //
  // The previous implementation did `Number(row.iv) < threshold`. With
  // `row.iv === null` that is `0 < 0.01`, so every predictor whose IV was merely
  // UNAVAILABLE was silently deselected. The plan below never treats null,
  // pending, preview-only, or failed as zero, and it is computed before the user
  // confirms so the affected count can be shown up front.
  const weakSignalPlan = useMemo(
    () =>
      planWeakSignalExclusion({
        profile: governedProfile.profile,
        loading: governedProfile.phase === "quality" || governedProfile.phase === "iv",
        error: governedProfile.phase === "failed" || governedProfile.phase === "artifact_missing" ? governedProfile.error : null,
        problemType: targetInfo.kind === "continuous" ? "regression" : "classification",
        selected: headers.filter((header) => kept[header] !== false && header !== target),
      }),
    [governedProfile.profile, governedProfile.phase, governedProfile.error, targetInfo.kind, headers, kept, target]
  );

  function applyWeakSignalFilter() {
    if (!weakSignalPlan.eligible) {
      setWeakSignalNotice(weakSignalPlan.blockedReason ?? "Automatic weak-signal exclusion is unavailable.");
      return;
    }
    const previous = { ...kept };
    const nextKept = { ...kept };
    // Only predictors with a genuinely computed, genuinely weak IV are removed.
    weakSignalPlan.affected.forEach((column) => {
      nextKept[column] = false;
    });
    saveKeptSelection(nextKept);
    setWeakSignalUndo(previous);
    setWeakSignalNotice(
      `${weakSignalPlan.affected.length} predictor(s) deselected. ${weakSignalPlan.protectedFromRemoval.length} predictor(s) with unavailable Information Value were kept.`
    );
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "feature_inclusion_changed",
      subject: "Automatic weak-signal exclusion",
      previousValue: Object.keys(previous).filter((key) => previous[key] !== false),
      newValue: Object.keys(nextKept).filter((key) => nextKept[key] !== false),
      systemRecommendation: `Configured ATLAS weak-signal threshold ${weakSignalPlan.threshold}`,
      userReason: JSON.stringify({
        scopeMode: governedProfile.profile?.analysisScope.mode,
        datasetId: governedProfile.profile?.datasetId,
        datasetVersionId: governedProfile.profile?.datasetVersionId,
        target,
        eventValue,
        nonEventValue,
        calculationVersion: governedProfile.profile?.calculationVersion,
        affected: weakSignalPlan.affected,
        keptBecauseUnavailable: weakSignalPlan.protectedFromRemoval,
      }),
    });
  }

  function undoWeakSignalFilter() {
    if (!weakSignalUndo) return;
    saveKeptSelection(weakSignalUndo);
    setWeakSignalUndo(null);
    setWeakSignalNotice("Automatic weak-signal exclusion was undone.");
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "feature_inclusion_changed",
      subject: "Automatic weak-signal exclusion undone",
      previousValue: "applied",
      newValue: "reverted",
    });
  }

  function applyLoadedDataset(normalized: NormalizedBackendImport, options: {
    sourceLabel: string;
    backendSynced: boolean;
    browserComplete?: boolean;
    datasetLibrary?: LocalDataset["dataset_library"];
  }) {
    const guessedTarget = preferredTarget(normalized.headers, normalized.target);
    const keep: Record<string, boolean> = {};
    normalized.headers.forEach((header) => {
      keep[header] = header !== guessedTarget;
    });
    setHeaders(normalized.headers);
    setRows(normalized.previewRows);
    setKept(keep);
    setTarget(guessedTarget);
    setImportError(null);
    setBackendImportSynced(options.backendSynced);
    setBackendRowCount(options.backendSynced ? normalized.rowCount : null);
    setBrowserDataComplete(options.browserComplete ?? (!options.backendSynced && normalized.previewRows.length === normalized.rowCount));
    setPreviewSamplingMethod("top_n");
    const selectedColumns = normalized.selectedColumns.length ? normalized.selectedColumns : normalized.headers.filter((header) => header !== guessedTarget);
    const localView = buildSelectedDatasetView({
      headers: normalized.headers,
      rows: normalized.previewRows.slice(0, 5000),
      selectedColumns,
      target: guessedTarget || null,
    });
    saveLocalDataset({
      headers: localView.headers,
      rows: localView.rows,
      target: guessedTarget || null,
      selected_columns: localView.selectedColumns,
      problem_type: guessedTarget ? inferProblemType(localView.rows, guessedTarget) : undefined,
      registered_row_count: normalized.rowCount,
      browser_data_complete: options.browserComplete ?? (!options.backendSynced && normalized.previewRows.length === normalized.rowCount),
      event_value: eventValue,
      non_event_value: nonEventValue,
      dataset_library: options.datasetLibrary,
    });
    window.dispatchEvent(new CustomEvent("atlas-dataset-updated"));
    // The profiling effect recomputes quality (with correct scope and aggregates) as
    // soon as the new headers/rows land, so no interim profile is written here.
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "workflow_setting_changed",
      subject: "Data source",
      previousValue: metadata?.sourceLabel,
      newValue: options.sourceLabel,
      systemRecommendation: "Capture data source, version, sampling method, and data quality immediately after import.",
      followStatus: "followed",
    });
  }

  async function importCsvThroughBackend(file: File) {
    setIsImporting(true);
    setImportError(null);
    setMessage(`Importing ${file.name} through the ATLAS backend. The browser will show a governed preview sample when loading is complete.`);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("project_id", projectId);
      const response = await fetch(`${BASE}/data/upload_csv`, {
        method: "POST",
        credentials: "include",
        body: formData,
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok || !payload?.ok) {
        const errorMessage = payload?.detail ?? payload?.error ?? `HTTP ${response.status}`;
        throw new Error(backendImportFailureMessage(errorMessage, payload?.max_upload_mb));
      }
      const normalized = normalizeBackendImportResponse(payload);
      if (!normalized.headers.length || !normalized.previewRows.length || !normalized.rowCount) {
        throw new Error("Backend import completed but did not return usable columns and preview rows.");
      }
      applyLoadedDataset(normalized, { sourceLabel: `Backend CSV import: ${file.name}`, backendSynced: true });
      setMessage(`Loaded ${normalized.rowCount.toLocaleString()} rows and ${normalized.columnCount.toLocaleString()} columns through backend import. The browser preview shows ${normalized.previewRows.length.toLocaleString()} rows.`);
    } catch (err: any) {
      const errorText = err?.message ?? "ATLAS could not import this file through the backend.";
      setImportError(errorText);
      setBackendImportSynced(false);
      setBackendRowCount(null);
      setMessage(errorText);
    } finally {
      setIsImporting(false);
    }
  }

  async function onFile(file: File) {
    setMessage("");
    setImportError(null);
    setFileName(file.name);
    setBackendImportSynced(false);
    setBackendRowCount(null);
    setBrowserDataComplete(false);
    const decision = getUploadDecision({ fileName: file.name, fileSize: file.size });
    if (decision.mode === "invalid" || decision.mode === "recognized_unsupported") {
      setImportError(decision.message);
      setMessage(decision.message);
      return;
    }
    if (decision.mode === "backend") {
      await importCsvThroughBackend(file);
      return;
    }
    const extension = decision.extension;
    if (!BROWSER_PARSE_EXTENSIONS.has(extension)) {
      setMessage(`${extension.toUpperCase()} files are recognized but require backend parser support before they can be loaded into the browser preview.`);
      return;
    }
    try {
      const text = await file.text();
      const parsed = extension === "json" ? parseJSON(text) : parseCSV(text);
      if (parsed.headers.length > DEFAULT_BROWSER_MAX_COLUMNS) {
        setMessage(`This dataset has ${parsed.headers.length.toLocaleString()} columns. Browser preview is limited to ${DEFAULT_BROWSER_MAX_COLUMNS.toLocaleString()} columns.`);
        return;
      }
      if (parsed.rows.length > DEFAULT_BROWSER_MAX_ROWS) {
        setMessage(`This dataset has ${parsed.rows.length.toLocaleString()} rows. Browser preview is limited to ${DEFAULT_BROWSER_MAX_ROWS.toLocaleString()} rows; use sampling or backend import for larger files.`);
        return;
      }
      const normalized = {
        headers: parsed.headers,
        previewRows: parsed.rows,
        rowCount: parsed.rows.length,
        columnCount: parsed.headers.length,
        target: preferredTarget(parsed.headers),
        selectedColumns: parsed.headers.filter((header) => header !== preferredTarget(parsed.headers)),
        filename: file.name,
      };
      applyLoadedDataset(normalized, { sourceLabel: `Uploaded ${file.name}`, backendSynced: false, browserComplete: true });
      setMessage(`Loaded the complete browser dataset with ${parsed.rows.length.toLocaleString()} rows and ${parsed.headers.length.toLocaleString()} columns.`);
    } catch (err: any) {
      const errorText = err?.message ?? "Unable to parse file.";
      setImportError(errorText);
      setMessage(errorText);
    }
  }

  function saveQueryMetadata() {
    const stubHeaders = ["customer_id", "observation_date", "target", "feature_1", "feature_2"];
    const stubRows: Record<string, unknown>[] = [];
    setHeaders(stubHeaders);
    setRows(stubRows);
    const keep: Record<string, boolean> = {};
    stubHeaders.forEach((header) => {
      keep[header] = header !== "target";
    });
    setKept(keep);
    setTarget("target");
    setImportError(null);
    setBackendImportSynced(false);
    setBackendRowCount(null);
    setBrowserDataComplete(false);
    setMessage("SQL metadata saved. Real query execution requires a backend connector; upload query output or connect the backend to populate rows.");
  }

  async function persistDataset() {
    if (!headers.length) throw new Error("No dataset or query metadata is available.");
    const selectedColumns = selected;
    const localView = buildSelectedDatasetView({
      headers,
      rows: profilingRows,
      selectedColumns,
      target: target || null,
    });
    const backendView = buildSelectedDatasetView({
      headers,
      rows: fullSourceRows,
      selectedColumns,
      target: target || null,
    });
    const meta = generatedMetadata;
    const dq = quality ?? inferDataQuality({ headers, rows: completeBrowserDataset ? fullSourceRows : profilingRows, target: target || null });
    const problemType = targetInfo.kind === "continuous" ? "regression" : "classification";
    const localPayload: LocalDataset = {
      headers: localView.headers,
      rows: localView.rows,
      target: target || null,
      selected_columns: localView.selectedColumns,
      problem_type: problemType,
      registered_row_count: registeredRowCount,
      browser_data_complete: completeBrowserDataset,
      dataset_version: meta?.version,
      event_value: eventValue,
      non_event_value: nonEventValue,
      dataset_library:
        sourceType === "existing" && selectedLibraryDatasetId && selectedLibraryVersionId
          ? {
              datasetId: selectedLibraryDatasetId,
              versionId: selectedLibraryVersionId,
              datasetName: libraryDatasets.find((dataset) => dataset.datasetId === selectedLibraryDatasetId)?.name ?? "Dataset Library asset",
              datasetRole: "modeling",
              sourceType: "dataset-library",
              rowCount: registeredRowCount,
              columnCount: headers.length,
              linkedAt: new Date().toISOString(),
            }
          : undefined,
      data_access: meta ?? undefined,
      data_quality: dq,
    };
    const backendPayload: LocalDataset = {
      ...localPayload,
      headers: backendView.headers,
      rows: backendView.rows,
      selected_columns: backendView.selectedColumns,
    };
    const localSaveStatus = saveLocalDataset(localPayload);
    if (localSaveStatus === "failed") {
      setMessage("Dataset preview loaded, but browser session storage could not cache the sample. Continue is allowed; reload the source file if the browser session is refreshed.");
    }
    if (meta) {
      try {
        saveDataAccessMetadata(meta);
        recordDatasetVersion(localPayload, meta);
      } catch (error) {
        console.warn("ATLAS could not update data access metadata history", error);
        setMessage("Dataset is loaded and usable, but ATLAS could not update browser metadata history because local storage is full. Navigation is still allowed.");
      }
      setMetadata(meta);
    }
    setQuality(dq);
    useWorkflowStore.setState((state: any) => ({
      ...state,
      hasDataset: rows.length > 0 || headers.length > 0,
      trainSpec: {
        ...(state?.trainSpec ?? {}),
        data: {
          ...(state?.trainSpec?.data ?? {}),
          source: sourceType,
          n_samples: registeredRowCount,
          task: problemType === "regression" ? "regression" : "binary",
          target,
          selected_columns: localView.selectedColumns,
          dataset_version: meta?.version,
        },
      },
    }));

    let backendSynced = backendImportSynced;
    try {
      if (!backendImportSynced && !completeBrowserDataset) {
        throw new Error("The full registered dataset artifact is not active. Reload the source instead of sending preview rows as modeling data.");
      }
      const backendRes = await fetch(`${BASE}${backendImportSynced ? "/data/set_target" : "/data/set_sample"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(backendImportSynced
          ? { project_id: projectId, target, selected_columns: localView.selectedColumns, dataset_version: meta?.version }
          : { ...backendPayload, project_id: projectId, dataset_version: meta?.version }),
      });
      const backendJson = await backendRes.json().catch(() => null);
      if (!backendRes.ok || !backendJson?.ok) {
        throw new Error(backendJson?.detail ?? backendJson?.error ?? "Backend did not accept the modeling dataset.");
      }
      backendSynced = true;
    } catch (err: any) {
      setMessage(`Dataset preview is saved locally. Backend sync did not complete: ${err?.message ?? "Unable to send the modeling dataset to the backend."}`);
    }

    if (backendSynced && localSaveStatus === "sample") {
      setMessage(`Cached ${profilingRows.length.toLocaleString()} profiling rows in the browser and sent ${registeredRowCount.toLocaleString()} rows to the backend for modeling.`);
    } else if (backendSynced && localSaveStatus !== "failed") {
      setMessage(`Cached ${profilingRows.length.toLocaleString()} profiling rows in the browser and preserved ${registeredRowCount.toLocaleString()} registered modeling rows.`);
    }
    if (sourceType === "existing" && selectedLibraryDatasetId && selectedLibraryVersionId) {
      try {
        await linkDatasetToProject(projectId, selectedLibraryDatasetId, selectedLibraryVersionId, "modeling");
      } catch (error) {
        setMessage("Dataset is usable in this workflow, but ATLAS could not update the project-dataset link registry.");
      }
    }
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "workflow_setting_changed",
      subject: "Dataset version",
      previousValue: metadata?.version,
      newValue: meta?.version,
      systemRecommendation: "Use dataset version, hash, source, query, and sampling metadata in model governance documentation.",
      followStatus: "followed",
    });
  }

  // `dataAcquisitionDisabledReason` no longer gates this page: progression is
  // decided by `acquisitionStatus.canContinue`, which considers the governed
  // profile as well as the import state. The helper remains exported for other
  // callers and its own tests.
  // Part D: a successful load is GREEN. The previous default painted the
  // "Loaded CLASS_TRAIN..." confirmation amber, so success read as a warning.
  const messageClass =
    importError && !headers.length
      ? "border-red-200 bg-red-50 text-red-900"
      : isImporting
        ? "border-blue-200 bg-blue-50 text-blue-900"
        : /^(Loaded|Registered|Cached|Linked|Saved)/i.test(message)
          ? "border-emerald-200 bg-emerald-50 text-emerald-900"
          : "border-amber-200 bg-amber-50 text-amber-900";
  const updateTarget = (next: string) => {
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "target_variable_selected",
      subject: "Target variable",
      previousValue: target,
      newValue: next,
    });
    setTarget(next);
    const currentDataset = loadLocalDataset();
    if (headers.length) setImportError(null);
    const localView = buildSelectedDatasetView({
      headers,
      rows: profilingRows,
      selectedColumns: headers.filter((header) => header !== next && kept[header] !== false),
      target: next || null,
    });
    saveLocalDataset({
      headers: localView.headers,
      rows: localView.rows,
      target: next || null,
      selected_columns: localView.selectedColumns,
      problem_type: next ? inferProblemType(localView.rows, next) : undefined,
      registered_row_count: registeredRowCount,
      browser_data_complete: completeBrowserDataset,
      event_value: eventValue,
      non_event_value: nonEventValue,
      dataset_library: currentDataset?.dataset_library,
    });
    window.dispatchEvent(new CustomEvent("atlas-dataset-updated"));
    // Quality is recomputed by the profiling effect, which is the single source of
    // truth for profile scope, registered row counts, and class aggregates. Writing a
    // bare inferDataQuality() result here raced that effect and could leave a preview
    // profile mislabelled as a complete-dataset profile with no class distribution.
  };

  // Debounced on registerName changes (NOT on the name field's onBlur): blurring that
  // field is also the first event a click on "Register Development Dataset" fires, so
  // triggering an async state update from onBlur raced the click itself -- the
  // duplicate-check's re-render could land between the button's mousedown and mouseup
  // and silently swallow the click. Typing-driven debounce has no such coupling.
  useEffect(() => {
    if (persistenceChoice !== "register" || !registerName.trim()) {
      setDuplicateCandidates([]);
      return;
    }
    const timer = setTimeout(() => void checkForSimilarDatasets(registerName), 500);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [registerName, persistenceChoice]);

  async function checkForSimilarDatasets(name: string) {
    if (!name.trim()) {
      setDuplicateCandidates([]);
      return;
    }
    setCheckingDuplicates(true);
    try {
      const candidates = await findSimilarDatasets({
        name,
        target: target || undefined,
        rowCount: registeredRowCount || undefined,
        columnCount: headers.length || undefined,
      });
      setDuplicateCandidates(candidates);
    } catch {
      setDuplicateCandidates([]);
    } finally {
      setCheckingDuplicates(false);
    }
  }

  async function handleRegisterDevelopmentDataset() {
    if (!registerName.trim()) {
      setRegistrationError("Enter a Dataset Library name before registering.");
      return;
    }
    setRegistering(true);
    setRegistrationError("");
    try {
      // The backend DATASTORE for this project is only synced when the user advances
      // past this step (persistDataset, normally StepShell's onNext) -- registration can
      // happen before that, so ensure the sync has actually happened first, without
      // navigating away from this page.
      await persistDataset();
      const dataset = await registerWorkspaceDataset({
        projectId,
        name: registerName.trim(),
        description: registerDescription.trim(),
        tags: registerTags.split(",").map((tag) => tag.trim()).filter(Boolean),
      });
      setRegistrationResult(dataset);
      // Record the governed link locally.
      //
      // Without this, registering an UPLOADED workspace dataset left
      // `dataset_library` unset (it was only written when picking an already
      // registered asset), so downstream steps had no immutable
      // (datasetId, versionId) to analyze against and EDA stayed a Workspace
      // Draft Analysis forever -- the draft-to-governed transition could never
      // complete for the most common flow.
      const registeredVersion = dataset.latestVersion ?? null;
      const existing = loadLocalDataset();
      if (existing && dataset.datasetId && registeredVersion?.versionId) {
        saveLocalDataset({
          ...existing,
          dataset_library: {
            datasetId: dataset.datasetId,
            versionId: registeredVersion.versionId,
            datasetName: dataset.name ?? registerName.trim(),
            datasetRole: "modeling",
            sourceType: "dataset-library",
            rowCount: registeredVersion.rowCount ?? existing.registered_row_count,
            columnCount: registeredVersion.columnCount ?? existing.headers.length,
            linkedAt: new Date().toISOString(),
          },
        });
        window.dispatchEvent(new CustomEvent("atlas-dataset-updated"));
      }
      logDecision({
        workflowStep: "Data Acquisition",
        actionType: "workflow_setting_changed",
        subject: "Dataset Library registration",
        newValue: dataset.datasetId,
        systemRecommendation: "Registered datasets are governed, versioned, and reusable across authorized projects.",
        followStatus: "followed",
      });
    } catch (error) {
      setRegistrationError(error instanceof Error ? error.message : "ATLAS could not register this dataset to the Dataset Library.");
    } finally {
      setRegistering(false);
    }
  }

  const existingDatasetPicker = (
    <ExistingDatasetPanel
      versions={datasetVersions}
      libraryDatasets={libraryDatasets}
      selectedDatasetId={selectedLibraryDatasetId}
      selectedVersionId={selectedLibraryVersionId}
      loading={libraryLoading}
      loadProgress={loadProgress}
      isLoaded={isAlreadyLinked(loadedLibraryIdentity, { datasetId: selectedLibraryDatasetId, versionId: selectedLibraryVersionId })}
      onDatasetChange={(datasetId) => {
        const dataset = libraryDatasets.find((item) => item.datasetId === datasetId);
        setSelectedLibraryDatasetId(datasetId);
        setSelectedLibraryVersionId(dataset?.latestVersion?.versionId ?? "");
        // Part A/5 + H1/8: a different selection is not the loaded version.
        setLoadProgress(IDLE_LOAD_PROGRESS);
      }}
      onVersionChange={(versionId) => {
        setSelectedLibraryVersionId(versionId);
        setLoadProgress(IDLE_LOAD_PROGRESS);
      }}
      onRefresh={async () => {
        setLibraryLoading(true);
        try {
          const payload = await listDatasets();
          setLibraryDatasets(payload.datasets);
        } finally {
          setLibraryLoading(false);
        }
      }}
      onLoad={async () => {
        if (!selectedLibraryDatasetId || !selectedLibraryVersionId) {
          setMessage("Select a dataset and version before loading from the Dataset Library.");
          return;
        }
        const dataset = libraryDatasets.find((item) => item.datasetId === selectedLibraryDatasetId);
        setIsImporting(true);
        // Part H1: stages advance only at real observable boundaries. The two
        // backend calls run sequentially (rather than in parallel) precisely so
        // each milestone corresponds to work that actually completed.
        const advance = (activeStageIndex: number) =>
          setLoadProgress({ phase: "loading", activeStageIndex, failedStageIndex: null, error: null });
        let stageIndex = 0;
        try {
          advance(0); // Authorizing dataset access
          const activation = await activateDatasetVersion(selectedLibraryDatasetId, selectedLibraryVersionId, projectId);
          // Loading a governed version INTO this project's modeling workspace is
          // the act of using it here, so the project-dataset link is established
          // now rather than only when the page is finally saved. Governed
          // profiling requires the link (server-side `_require_linked`), so
          // deferring it left the authoritative profile unavailable after load.
          await linkDatasetToProject(projectId, selectedLibraryDatasetId, selectedLibraryVersionId, "modeling").catch(() => undefined);

          stageIndex = 1;
          advance(1); // Resolving dataset version
          const resolvedRowCount = activation.row_count ?? dataset?.latestVersion?.rowCount ?? 0;

          stageIndex = 2;
          advance(2); // Reading governed schema
          const preview = await getDatasetPreview(selectedLibraryDatasetId, selectedLibraryVersionId);

          stageIndex = 3;
          advance(3); // Profiling target and predictors
          const guessedTarget = preferredTarget(preview.columns);
          const normalized = {
            headers: preview.columns,
            previewRows: preview.rows,
            rowCount: resolvedRowCount || preview.rows.length,
            columnCount: preview.columns.length,
            target: guessedTarget,
            selectedColumns: preview.columns.filter((header) => header !== guessedTarget),
            filename: dataset?.name ?? selectedLibraryDatasetId,
          };

          stageIndex = 4;
          advance(4); // Evaluating data quality (the quality effect refetches on the new dataset)

          stageIndex = 5;
          advance(5); // Preparing browser preview
          applyLoadedDataset(normalized, {
            sourceLabel: `Dataset Library: ${dataset?.name ?? selectedLibraryDatasetId} (${selectedLibraryVersionId})`,
            backendSynced: true,
            browserComplete: false,
            datasetLibrary: {
              datasetId: selectedLibraryDatasetId,
              versionId: selectedLibraryVersionId,
              datasetName: dataset?.name ?? "Dataset Library asset",
              datasetRole: "modeling",
              sourceType: "dataset-library",
              rowCount: normalized.rowCount,
              columnCount: normalized.columnCount,
              linkedAt: new Date().toISOString(),
            },
          });
          setFileName(dataset?.name ?? "Dataset Library asset");
          setLoadedLibraryIdentity({ datasetId: selectedLibraryDatasetId, versionId: selectedLibraryVersionId });
          setLoadProgress({ phase: "loaded", activeStageIndex: DATASET_LOAD_STAGES.length - 1, failedStageIndex: null, error: null });
          // Part A/6: identity, not display name, is what the analyst is told was loaded.
          setMessage(`Loaded ${dataset?.name ?? "Dataset Library asset"}, version ${selectedLibraryVersionId}, into this project.`);
        } catch (error) {
          const detail = error instanceof Error ? error.message : "ATLAS could not load the selected dataset version.";
          // Part H1/7: completed milestones survive, the failed stage is named, no green completion.
          setLoadProgress({ phase: "failed", activeStageIndex: stageIndex, failedStageIndex: stageIndex, error: detail });
          setLoadedLibraryIdentity(null);
          setMessage(detail);
        } finally {
          setIsImporting(false);
        }
      }}
    />
  );

  return (
    <StepShell
      title="Step 1: Data Acquisition"
      subtitle="Connect to governed sources, register the modeling population, confirm the target, assess data quality, approve predictors, and establish reproducible lineage."
      variant="data"
      heroMetrics={[
        { label: "Source Type", value: sourceCards.find((card) => card.id === sourceType)?.title ?? "Not selected" },
        // Part C: registration is a fact about the Library asset, not about
        // whether an upload filename exists.
        { label: "Dataset", value: datasetLibraryLink?.datasetName || fileName || "Not selected", tone: "neutral" },
        { label: "Registration", value: registrationLabel(acquisitionStatus.registrationState), tone: acquisitionStatus.registrationState === "registered" ? "success" : "neutral" },
        { label: "Project link", value: projectLinkLabel(acquisitionStatus.linkState), tone: acquisitionStatus.linkState === "linked" ? "success" : "neutral" },
        { label: "Load state", value: acquisitionStatus.loadLabel, tone: acquisitionStatus.loadTone },
        { label: "Registered Rows", value: registeredRowCount ? registeredRowCount.toLocaleString() : "Not available" },
        { label: "Columns", value: headers.length ? headers.length.toLocaleString() : "Not available" },
        { label: "Target", value: target || "Not confirmed", tone: target ? "neutral" : "warning" },
        // Part B: the same derivation the strip and checkpoint use.
        { label: "Modeling Readiness", value: acquisitionStatus.readinessLabel, tone: acquisitionStatus.readinessTone },
        { label: "Quality Review", value: acquisitionStatus.reviewLabel, tone: acquisitionStatus.reviewTone },
      ] satisfies AtlasWorkflowMetric[]}
      nextDisabled={!acquisitionStatus.canContinue}
      nextDisabledReason={acquisitionStatus.blockingReasons[0] ?? ""}
      nextLabel={acquisitionStatus.continueLabel}
      nextPath="/step02"
      onNext={async () => {
        await persistDataset();
      }}
    >
      <div className="space-y-5">
        {message && (
          <div
            className={`rounded-lg border px-4 py-3 text-sm ${messageClass}`}
            role="status"
            aria-live="polite"
            data-testid="data-acquisition-message"
            data-tone={
              importError && !headers.length
                ? "danger"
                : isImporting
                  ? "info"
                  : /^(Loaded|Registered|Cached|Linked|Saved)/i.test(message)
                    ? "success"
                    : "warning"
            }
          >
            {message}
          </div>
        )}

        {/* Part H2: every state below is derived from real workflow state. Amber
            marks a warning the analyst can proceed past; red is reserved for a
            genuine blocker. Each item carries a text detail so the track is
            understandable without color. */}
        <AtlasStatusStrip
          items={[
            { label: "Source selected", state: fileName || generatedMetadata ? "complete" : "current", detail: fileName || "Choose or configure a source" },
            { label: "Import completed", state: headers.length ? "complete" : "pending", detail: headers.length ? `${headers.length.toLocaleString()} columns available` : "Awaiting source import" },
            {
              label: "Dataset registered or linked",
              state: datasetLibraryLink?.datasetId ? "complete" : registeredRowCount && backendImportSynced ? "complete" : registeredRowCount ? "warning" : "pending",
              detail: datasetLibraryLink?.datasetId
                ? `Linked to ${datasetLibraryLink.datasetName ?? datasetLibraryLink.datasetId}`
                : registeredRowCount
                  ? `${registeredRowCount.toLocaleString()} modeling rows`
                  : "No registered population",
            },
            { label: "Target confirmed", state: target ? "complete" : "pending", detail: target || "Select the governed outcome" },
            {
              label: "Quality reviewed",
              // Review is a user action: "review required" is amber, never the
              // red "blocked" that previously appeared beside a green "Ready".
              state:
                acquisitionStatus.readiness === "blocked"
                  ? "blocked"
                  : acquisitionStatus.reviewState === "completed"
                    ? "complete"
                    : acquisitionStatus.readiness === "unavailable"
                      ? "pending"
                      : "warning",
              detail:
                acquisitionStatus.readiness === "blocked"
                  ? acquisitionStatus.blockingReasons[0] ?? "Blocked"
                  : `${acquisitionStatus.readinessLabel} - ${acquisitionStatus.reviewLabel}`,
            },
            { label: "Predictors approved", state: selected.length ? "complete" : "pending", detail: selected.length ? `${selected.length.toLocaleString()} selected` : "Approve eligible inputs" },
          ] satisfies AtlasStatusItem[]}
        />

        {/* Part H6: the source-and-load command section carries a strong slate
            identity so the page reads as a sequence of sections rather than a
            uniform white sheet. */}
        <section className="rounded-xl border-2 border-slate-400 bg-slate-100 p-5 shadow-sm" data-testid="source-command-section">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate-600">Source and load</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Source Selection, File Upload, and Target Setup</h2>
            <p className="mt-1 text-sm text-slate-700">Start here: load the source file and confirm the target column before reviewing summaries or downstream settings.</p>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-5">
            {sourceCards.map((card) => (
              <button
                key={card.id}
                type="button"
                className={`rounded-xl border p-4 text-left shadow-sm transition ${sourceType === card.id ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white/80 text-slate-900 hover:bg-white"}`}
                onClick={() => setSourceType(card.id)}
                aria-pressed={sourceType === card.id}
                data-testid={`source-card-${card.id}`}
              >
                <div className={`text-sm font-semibold ${sourceType === card.id ? "text-white" : "text-slate-950"}`}>{card.title}</div>
                <p className={`mt-2 text-xs leading-5 ${sourceType === card.id ? "text-slate-200" : "text-slate-500"}`}>{card.body}</p>
              </button>
            ))}
          </div>
          <div className="mt-4">
            {sourceType === "upload" && (
              <UploadPanel fileName={fileName} onFile={onFile} />
            )}
            {sourceType === "existing" && existingDatasetPicker}
            <div className="mt-5">
              <TargetSetup
                headers={headers}
                target={target}
                setTarget={updateTarget}
                eventValue={eventValue}
                setEventValue={setEventValue}
                nonEventValue={nonEventValue}
                setNonEventValue={setNonEventValue}
                problemType={targetInfo.kind === "continuous" ? "regression" : "classification"}
              />
            </div>
            {/* Part H3: appears once a classification target is confirmed. */}
            {!!target && targetInfo.kind !== "continuous" && (
              <div className="mt-5">
                <TargetDistributionPanel
                  distribution={targetDistribution}
                  state={targetDistributionState}
                  scopeLabel={
                    targetDistributionRequest
                      ? "full registered population"
                      : quality?.profileScope === "full_dataset"
                        ? "full registered population"
                        : quality?.profileScope === "complete_browser_dataset"
                          ? "complete browser dataset"
                          : "registered population"
                  }
                  query={
                    targetDistributionRequest
                      ? {
                          phase: serverDistribution.phase,
                          elapsedMs: serverDistribution.elapsedMs,
                          error: serverDistribution.error,
                          sampling: serverDistribution.result?.sampling,
                          retry: serverDistribution.retry,
                          calculateExact: serverDistribution.calculateExact,
                        }
                      : undefined
                  }
                />
              </div>
            )}
            {headers.length > 0 && target && (
              <DatasetPersistenceCard
                projectName={projectName}
                target={target}
                rowCount={registeredRowCount}
                columnCount={headers.length}
                choice={persistenceChoice}
                onChoice={setPersistenceChoice}
                registerName={registerName}
                onRegisterNameChange={(value) => {
                  setRegisterName(value);
                  setRegistrationResult(null);
                }}
                registerDescription={registerDescription}
                onRegisterDescriptionChange={setRegisterDescription}
                registerTags={registerTags}
                onRegisterTagsChange={setRegisterTags}
                registering={registering}
                registrationResult={registrationResult}
                registrationError={registrationError}
                duplicateCandidates={duplicateCandidates}
                checkingDuplicates={checkingDuplicates}
                onRegister={() => void handleRegisterDevelopmentDataset()}
                persistenceMode={persistenceMode}
                sourceKindLabel={DATASET_SOURCE_LABELS[datasetSourceKind]}
                registrationActionLabel={resolveRegistrationActionLabel(datasetSourceKind, Boolean(datasetLibraryLink?.datasetId))}
                libraryLink={datasetLibraryLink}
                assetOwner={libraryDatasets.find((item) => item.datasetId === datasetLibraryLink?.datasetId)?.ownerDisplayName}
              />
            )}
            {(sourceType === "sql" || sourceType === "cloud" || sourceType === "python") && (
              <details className="rounded-xl border border-slate-200 bg-slate-50 p-3" open>
                <summary className="cursor-pointer text-sm font-semibold text-slate-900">Configure {sourceCards.find((card) => card.id === sourceType)?.title}</summary>
                <div className="mt-4">
                {sourceType === "sql" && (
                  <SqlPanel
                    provider={provider}
                    setProvider={setProvider}
                    connectionName={connectionName}
                    setConnectionName={setConnectionName}
                    database={database}
                    setDatabase={setDatabase}
                    schema={schema}
                    setSchema={setSchema}
                    sql={sql}
                    setSql={setSql}
                    warnings={sqlWarnings}
                    savedQueries={savedQueries}
                    favoriteQueries={favoriteQueries}
                    onTemplate={(template) => setSql(template)}
                    onSave={() => setSavedQueries((current) => [sql, ...current].slice(0, 8))}
                    onFavorite={() => setFavoriteQueries((current) => [sql, ...current.filter((item) => item !== sql)].slice(0, 5))}
                    onSaveMetadata={saveQueryMetadata}
                  />
                )}
                {sourceType === "cloud" && (
                  <CloudPanel cloudProvider={cloudProvider} setCloudProvider={setCloudProvider} cloudPath={cloudPath} setCloudPath={setCloudPath} />
                )}
                {sourceType === "python" && (
                  <PythonPanel pythonCode={pythonCode} setPythonCode={setPythonCode} />
                )}
                </div>
              </details>
            )}
          </div>
        </section>

        <CurrentDatasetSummary
          fileName={fileName}
          sourceType={sourceType}
          target={target}
          registeredRowCount={registeredRowCount}
          previewRowCount={previewRows.length}
          columnCount={headers.length}
          selectedCount={selected.length}
          browserDataComplete={completeBrowserDataset}
          datasetVersion={selectedLibraryVersionId || generatedMetadata?.version || metadata?.version}
          sourceKindLabel={DATASET_SOURCE_LABELS[datasetSourceKind]}
        />

        <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)] xl:items-start">
          <DataPreview
            headers={headers}
            rows={previewRows}
            target={target}
            targetInfo={targetInfo}
            targetSummary={continuousTargetSummary}
            effectiveModelingRowCount={registeredRowCount}
            previewRowCount={previewRows.length}
            backendImportSynced={backendImportSynced}
            eventRate={authoritativeEventRate.rate}
            eventRateScopeLabel={EVENT_RATE_SCOPE_LABELS[authoritativeEventRate.scope]}
            eventRateIsAuthoritative={authoritativeEventRate.isAuthoritative}
          />
        </section>

        {/* UX-DATAACQ-003 / Part D: this is a readiness checkpoint, not a grey
            appendix. Light-teal identity, stronger border, explicit readiness
            status, and white internal metric cards. */}
        <section
          className="rounded-xl border-2 border-teal-300 bg-teal-50 p-5 shadow-sm"
          data-testid="data-quality-readiness"
          id="data-quality-readiness"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-[11px] font-bold uppercase tracking-wide text-teal-700">Readiness checkpoint</div>
              <h2 className="mt-1 text-base font-semibold text-teal-950">Data Quality & Modeling Readiness</h2>
              <p className="mt-1 text-sm text-slate-700">Quality findings identify their actual profiling scope and registered row count.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <ReadinessBadge status={acquisitionStatus} />
              <ProfileScopeBadge quality={quality} />
            </div>
          </div>
          <ReadinessSummary
            quality={quality}
            readiness={readiness}
            acquisitionStatus={acquisitionStatus}
            registeredRowCount={registeredRowCount}
            eventRateDisplay={formatEventRatePrecise(authoritativeEventRate.rate)}
            eventRateScopeLabel={EVENT_RATE_SCOPE_LABELS[authoritativeEventRate.scope]}
          />
          <div className="mt-4 rounded-xl border border-teal-200 bg-white p-4">
            <DataQualityPanel quality={quality} metadata={generatedMetadata ?? metadata} />
          </div>
        </section>

        <BureauReviewPanel target={target} eventValue={eventValue} enabled={!!headers.length && !!registeredRowCount} />

        {!!headers.length && (
          <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-slate-950">Variable Summary / Feature Selection</h2>
                <p className="mt-1 text-sm text-slate-500">Review data types, missingness, distinct counts, and selected model inputs.</p>
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <label className="flex max-w-md items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950">
                  <input
                    className="mt-1"
                    type="checkbox"
                    checked={autoExcludeWeakSignals}
                    disabled={!weakSignalPlan.eligible}
                    onChange={(event) => setAutoExcludeWeakSignals(event.target.checked)}
                    data-testid="weak-signal-toggle" 
                  />
                  <span>
                    Uncheck weak-signal features automatically. Classification uses the configured ATLAS weak-signal
                    threshold IV &lt; {WEAK_SIGNAL_IV_THRESHOLD}; regression uses absolute correlation &lt;{" "}
                    {WEAK_CORRELATION_THRESHOLD.toFixed(2)}. Predictors whose Information Value is unavailable are never
                    removed.
                  </span>
                </label>
                {autoExcludeWeakSignals && weakSignalPlan.eligible ? (
                  <button
                    type="button"
                    className="rounded-lg border border-amber-400 bg-white px-3 py-2 text-sm font-semibold text-amber-900"
                    data-testid="weak-signal-apply"
                    onClick={applyWeakSignalFilter}
                  >
                    Apply to {weakSignalPlan.affected.length} predictor(s)
                  </button>
                ) : null}
                {weakSignalUndo ? (
                  <button
                    type="button"
                    className="rounded-lg border px-3 py-2 text-sm"
                    data-testid="weak-signal-undo"
                    onClick={undoWeakSignalFilter}
                  >
                    Undo
                  </button>
                ) : null}
                <button
                  className="rounded-lg border px-3 py-2 text-sm"
                  onClick={() => {
                    const nextKept = Object.fromEntries(variableSummary.map((row) => [row.column, row.role === "eligible"]));
                    saveKeptSelection(nextKept);
                  }}
                >
                  Select all
                </button>
                <button
                  className="rounded-lg border px-3 py-2 text-sm"
                  onClick={() => {
                    const nextKept = Object.fromEntries(headers.map((header) => [header, false]));
                    saveKeptSelection(nextKept);
                  }}
                >
                  None
                </button>
              </div>
            </div>
            {!weakSignalPlan.eligible && weakSignalPlan.blockedReason ? (
              <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950" data-testid="weak-signal-blocked-reason">
                {weakSignalPlan.blockedReason}
              </p>
            ) : null}
            {weakSignalNotice ? (
              <p className="mt-2 text-xs font-semibold text-slate-700" role="status" aria-live="polite" data-testid="weak-signal-notice">
                {weakSignalNotice}
              </p>
            ) : null}
            <p className="mt-3 text-xs text-slate-600" data-testid="variable-summary-scope">
              {governedProfile.profile
                ? `Scope: ${governedProfile.profile.analysisScope.label} - ${governedProfile.profile.quality.populationRows.toLocaleString()} rows - calculated ${new Date(governedProfile.profile.generatedAt).toLocaleString()}.`
                : governedProfile.phase === "artifact_missing"
                  ? "Legacy Dataset Version: Full Artifact Unavailable. Information Value cannot be calculated for this version."
                  : governedProfile.phase === "failed"
                    ? `Authoritative predictor profiling failed: ${governedProfile.error}`
                    : "Calculating the authoritative predictor profile..."}
            </p>
            {governedProfile.profile ? (
              <div
                className="mt-2 grid gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs sm:grid-cols-2 xl:grid-cols-4"
                data-testid="predictor-evaluation-summary"
              >
                <div>
                  <span className="font-semibold text-slate-900" data-testid="predictors-evaluated">
                    {predictorCounts.evaluated} predictors evaluated
                  </span>
                  <div className="text-slate-600" data-testid="target-exclusion-note">
                    Target excluded from predictor IV{predictorCounts.targetExcluded ? ` (${predictorCounts.targetExcluded})` : ""}
                  </div>
                </div>
                <div>
                  <span className="font-semibold text-amber-900" data-testid="unusually-strong-count">
                    {predictorCounts.unusuallyStrong} unusually strong
                  </span>
                  <div className="text-slate-600">Require human review</div>
                </div>
                <div>
                  <span className="font-semibold text-slate-900" data-testid="leakage-review-count">
                    {predictorCounts.leakageReview} automated leakage signals
                  </span>
                  <div className="text-slate-600">Review recommended, not confirmed</div>
                </div>
                <div>
                  <span className="font-semibold text-slate-900" data-testid="unavailable-predictor-count">
                    {predictorCounts.unavailable.length} predictors unavailable
                  </span>
                  {predictorCounts.unavailable.length ? (
                    <details className="text-slate-600">
                      <summary className="cursor-pointer">Show details</summary>
                      <ul className="mt-1 list-disc pl-4" data-testid="unavailable-predictor-list">
                        {predictorCounts.unavailable.slice(0, 10).map((item) => (
                          <li key={item.predictor}>
                            {item.predictor}: {item.reason}
                          </li>
                        ))}
                      </ul>
                      {predictorCounts.unavailable.length > 10 ? (
                        <p className="mt-1">{predictorCounts.unavailable.length - 10} more not listed.</p>
                      ) : null}
                    </details>
                  ) : (
                    <div className="text-slate-600">All selected predictors evaluated</div>
                  )}
                </div>
              </div>
            ) : null}
            {predictorCounts.unusuallyStrong ? (
              <p
                className="mt-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950"
                data-testid="high-iv-explanation"
              >
                <strong>Why unusually high Information Value matters:</strong> {HIGH_IV_EXPLANATION} These predictors are
                not deselected automatically and do not block Data Acquisition.
              </p>
            ) : null}
            {governedProfile.phase === "artifact_missing" && governedProfile.artifactMissing ? (
              <div className="mt-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950" data-testid="legacy-artifact-missing">
                <p className="font-semibold">Legacy Dataset Version: Full Artifact Unavailable</p>
                <p className="mt-1">{governedProfile.artifactMissing.disclosure}</p>
                <ul className="mt-1 list-disc pl-5">
                  {governedProfile.artifactMissing.recovery.map((item) => (<li key={item}>{item}</li>))}
                </ul>
              </div>
            ) : null}
            {governedProfile.phase === "failed" ? (
              <button type="button" className="mt-2 rounded-lg border px-3 py-1.5 text-xs" data-testid="profile-retry" onClick={governedProfile.retry}>
                Retry profiling
              </button>
            ) : null}
            <div className="mt-4 max-h-[560px] overflow-auto rounded-lg border border-slate-200">
              <table className="min-w-full text-sm">
                <thead className="sticky top-0 bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-center">Keep</th>
                    <th className="px-3 py-2 text-left">Column</th>
                    <th className="px-3 py-2 text-left">Role</th>
                    <th className="px-3 py-2 text-left">Type</th>
                    <th className="px-3 py-2 text-right">{targetInfo.kind === "continuous" ? "Corr(Target)" : "IV"}</th>
                    <th className="px-3 py-2 text-left">Signal strength</th>
                    <th className="px-3 py-2 text-left">Calculation status</th>
                    <th className="px-3 py-2 text-right">Missing %</th>
                    <th className="px-3 py-2 text-right">Distinct</th>
                    <th className="px-3 py-2 text-right">Mean</th>
                    <th className="px-3 py-2 text-right">Min</th>
                    <th className="px-3 py-2 text-right">Max</th>
                    <th className="px-3 py-2 text-left">Leakage status</th>
                    <th className="px-3 py-2 text-left">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {variableSummary.map((row) => {
                    const leakageRole = row.role === "eligible" ? "" : row.role;
                    const role = leakageRole || "Candidate Predictor";
                    return (
                      <tr key={row.column} className="border-t">
                        <td className="px-3 py-2 text-center">
                          {leakageRole ? (
                            <input type="checkbox" disabled checked={false} aria-label={`${row.column} disabled excluded predictor`} />
                          ) : (
                            <input
                              type="checkbox"
                              checked={!!kept[row.column]}
                              onChange={(event) => {
                                const nextKept = { ...kept, [row.column]: event.target.checked };
                                saveKeptSelection(nextKept);
                                logDecision({
                                  workflowStep: "Data Acquisition",
                                  actionType: "feature_inclusion_changed",
                                  subject: row.column,
                                  previousValue: kept[row.column] ? "included" : "excluded",
                                  newValue: event.target.checked ? "included" : "excluded",
                                });
                              }}
                            />
                          )}
                        </td>
                        <td className="px-3 py-2 font-medium">{row.column}</td>
                        <td className="px-3 py-2 text-xs font-semibold text-slate-700">{role}</td>
                        <td className="px-3 py-2">{row.type}</td>
                        {targetInfo.kind === "continuous" ? (
                          <td className={`px-3 py-2 text-right ${signalStatusClass(row.corr)}`}>{formatNumber(row.corr)}</td>
                        ) : (
                          <td className="px-3 py-2 text-right" data-testid="iv-cell" data-iv-status={governedIv(row.column).ivStatus}>
                            <span
                              className={governedIv(row.column).ivStatus === "available" ? ivStatusClass(governedIv(row.column).iv) : "text-slate-500"}
                              title={
                                governedIv(row.column).ivStatus === "available"
                                  ? `Exact Information Value: ${formatIvExact(governedIv(row.column).iv)}`
                                  : IV_STATUS_LABELS[governedIv(row.column).ivStatus]
                              }
                            >
                              {ivCellText(governedIv(row.column))}
                            </span>
                          </td>
                        )}
                        <td className="px-3 py-2 text-xs" data-testid="signal-strength-cell">
                          {(() => {
                            const strength = signalStrength(governedIv(row.column));
                            if (!strength) return <span className="text-slate-400">Not available</span>;
                            return (
                              <span
                                data-signal-strength={strength.key}
                                className={
                                  strength.tone === "warning"
                                    ? "rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 font-semibold text-amber-900"
                                    : "text-slate-700"
                                }
                                title={strength.reviewRecommended ? HIGH_IV_EXPLANATION : undefined}
                              >
                                {strength.label}
                                {strength.reviewRecommended ? " - review recommended" : ""}
                              </span>
                            );
                          })()}
                        </td>
                        <td className="px-3 py-2 text-xs text-slate-600" data-testid="iv-status-cell">
                          {targetInfo.kind === "continuous" ? "Correlation" : IV_STATUS_LABELS[governedIv(row.column).ivStatus]}
                        </td>
                        <td className="px-3 py-2 text-right">{formatPercent(row.missingPct)}</td>
                        <td className="px-3 py-2 text-right">{row.distinct.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right">{formatNumber(row.mean)}</td>
                        <td className="px-3 py-2 text-right">{formatNumber(row.min)}</td>
                        <td className="px-3 py-2 text-right">{formatNumber(row.max)}</td>
                        <td className="px-3 py-2 text-xs font-semibold" data-testid="leakage-screen-cell">
                          {(() => {
                            const state = leakageScreen({
                              iv: governedIv(row.column).iv,
                              ivStatus: governedIv(row.column).ivStatus,
                              role: row.role,
                              eligible: !leakageRole,
                            });
                            const label = leakageRole ? "Excluded" : LEAKAGE_SCREEN_LABELS[state];
                            return (
                              <span
                                data-leakage-state={leakageRole ? "excluded" : state}
                                className={
                                  leakageRole
                                    ? "text-rose-700"
                                    : state === "review_recommended"
                                      ? "text-amber-800"
                                      : "text-slate-700"
                                }
                              >
                                {label}
                              </span>
                            );
                          })()}
                        </td>
                        <td className="px-3 py-2 text-xs text-slate-600">{row.exclusionReason || "Eligible predictor."}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {!!headers.length && (
          <section className="space-y-4">
            <h2 className="text-base font-semibold text-slate-950">Data Lineage</h2>
            <div className="mt-4 grid gap-4">
              <LineagePanel metadata={generatedMetadata ?? metadata} />
            </div>
          </section>
        )}
      </div>
    </StepShell>
  );
}

function UploadPanel({ fileName, onFile }: { fileName: string; onFile: (file: File) => void }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-slate-950">Upload File</h2>
      <p className="mt-1 text-sm text-slate-500">Supported source types: CSV, Excel, Parquet, Feather, JSON, SAS datasets, and ZIP. CSV and JSON parse locally today.</p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label className="cursor-pointer rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white">
          Choose File
          <input className="hidden" type="file" accept=".csv,.txt,.json,.xlsx,.xls,.parquet,.feather,.sas7bdat,.zip" onChange={(event) => event.target.files?.[0] && onFile(event.target.files[0])} />
        </label>
        <span className="text-sm text-slate-600">{fileName || "No file selected"}</span>
      </div>
    </div>
  );
}

function CurrentDatasetSummary(props: {
  fileName: string;
  sourceType: DataSourceType;
  target: string;
  registeredRowCount: number;
  previewRowCount: number;
  columnCount: number;
  selectedCount: number;
  browserDataComplete: boolean;
  datasetVersion?: string;
  sourceKindLabel: string;
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">Current Dataset Summary</h2>
      <p className="mt-1 text-sm text-slate-500">Registered modeling data and governed selection state.</p>
      {/* Part E: modeling rows, browser preview rows, and source type are named
          explicitly so the preview limit is never mistaken for the modeling
          population. */}
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Dataset" value={props.fileName || "Source metadata only"} />
        <Stat label="Source Type" value={props.sourceKindLabel} />
        <Stat label="Modeling Rows" value={props.registeredRowCount} />
        <Stat label="Browser Preview Rows" value={props.previewRowCount} />
        <Stat label="Dataset Columns" value={props.columnCount} />
        <Stat label="Target" value={props.target || "Not selected"} />
        <Stat label="Selected Predictors" value={props.selectedCount} />
        {/* Part C: an absent version id means none is SELECTED. It never means
            the Library asset is unregistered. */}
        <Stat label="Dataset Version" value={props.datasetVersion || "Not selected"} />
      </div>
      <p className="mt-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900" data-testid="modeling-vs-preview-note">
        {props.registeredRowCount.toLocaleString()} rows are available for backend modeling.{" "}
        {props.browserDataComplete
          ? "The browser holds the complete dataset."
          : `Only ${props.previewRowCount.toLocaleString()} rows are loaded for the browser preview; the preview limit does not reduce the modeling population.`}
      </p>
    </section>
  );
}

function DatasetPersistenceCard(props: {
  projectName: string;
  target: string;
  rowCount: number;
  columnCount: number;
  choice: "workspace" | "register";
  onChoice: (choice: "workspace" | "register") => void;
  registerName: string;
  onRegisterNameChange: (value: string) => void;
  registerDescription: string;
  onRegisterDescriptionChange: (value: string) => void;
  registerTags: string;
  onRegisterTagsChange: (value: string) => void;
  registering: boolean;
  registrationResult: DatasetSummary | null;
  registrationError: string;
  duplicateCandidates: DatasetSummary[];
  checkingDuplicates: boolean;
  onRegister: () => void;
  /** Part C: which persistence UI applies for the current source state. */
  persistenceMode: PersistenceMode;
  sourceKindLabel: string;
  registrationActionLabel: string;
  libraryLink: DatasetLibraryLink | null;
  assetOwner?: string;
}) {
  // UX-DATAACQ-004 / Part C1: data that is already a registered governed asset gets
  // a read-only status panel. Offering "Project Workspace Only" vs "Register in
  // Dataset Library" here implied a duplicate-registration or overwrite risk that
  // does not exist, and invited the analyst to re-register their own source.
  if (props.persistenceMode === "registered-status") {
    return (
      <section className="mt-5 rounded-xl border-2 border-emerald-300 bg-emerald-50 p-5 shadow-sm" data-testid="dataset-persistence-card" data-persistence-mode="registered-status">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wide text-emerald-700">Dataset persistence</div>
            <h2 className="mt-1 flex items-center gap-2 text-base font-semibold text-emerald-950">
              <ShieldCheck size={16} aria-hidden="true" />
              Registered Dataset Library Asset
            </h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-700">
              This project is linked to {props.libraryLink?.datasetName ?? "this dataset"}, version{" "}
              <span className="font-mono">{props.libraryLink?.versionId ?? "unknown"}</span>. The source asset remains in the
              Dataset Library if this project is deleted.
            </p>
          </div>
          <span className="rounded-full border border-emerald-300 bg-white px-3 py-1 text-xs font-semibold text-emerald-800" data-testid="already-linked-badge">
            Already linked
          </span>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <Stat label="Dataset ID" value={props.libraryLink?.datasetId ?? "-"} />
          <Stat label="Version ID" value={props.libraryLink?.versionId ?? "-"} />
          <Stat label="Owner" value={props.assetOwner || "-"} />
          <Stat label="Linked project status" value="Linked to this project" />
          <Stat label="Source type" value={props.sourceKindLabel} />
          <Stat label="Registration status" value="Registered in Dataset Library" />
        </div>
        <p className="mt-3 text-xs leading-5 text-slate-600">
          Registration is not offered for a source asset that is already registered, so the same asset cannot be duplicated
          or its immutable version overwritten from this page.
        </p>
        {props.libraryLink?.datasetId && (
          <Link
            className="mt-3 inline-block rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-semibold text-emerald-900"
            to={`/datasets/${props.libraryLink.datasetId}`}
          >
            Open in Dataset Library
          </Link>
        )}
      </section>
    );
  }

  const isDerived = props.persistenceMode === "derived-choice";
  return (
    <section className="mt-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm" data-testid="dataset-persistence-card" data-persistence-mode={props.persistenceMode}>
      <h2 className="text-base font-semibold text-slate-950">Dataset Persistence</h2>
      <p className="mt-1 text-sm text-slate-500">
        Choose how ATLAS should store this dataset. Status: <span className="font-semibold text-slate-800" data-testid="persistence-source-label">{props.sourceKindLabel}</span>
      </p>
      {isDerived && (
        <p className="mt-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900" data-testid="derived-dataset-notice">
          This is a {props.sourceKindLabel.toLowerCase()}. Registering it creates a new governed record; it never modifies or
          overwrites the immutable source version it was derived from.
        </p>
      )}
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <button
          type="button"
          onClick={() => props.onChoice("workspace")}
          aria-pressed={props.choice === "workspace"}
          className={`rounded-xl border p-4 text-left shadow-sm transition ${props.choice === "workspace" ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white hover:bg-slate-50"}`}
        >
          <div className={`text-sm font-semibold ${props.choice === "workspace" ? "text-white" : "text-slate-950"}`}>Project Workspace Only</div>
          <p className={`mt-2 text-xs leading-5 ${props.choice === "workspace" ? "text-slate-200" : "text-slate-500"}`}>
            Use this dataset only in the current project. It will not appear in the Dataset Library unless you register it later. Deleting this project deletes this workspace copy.
          </p>
        </button>
        <button
          type="button"
          onClick={() => props.onChoice("register")}
          aria-pressed={props.choice === "register"}
          className={`rounded-xl border p-4 text-left shadow-sm transition ${props.choice === "register" ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white hover:bg-slate-50"}`}
        >
          <div className={`text-sm font-semibold ${props.choice === "register" ? "text-white" : "text-slate-950"}`}>Register in Dataset Library</div>
          <p className={`mt-2 text-xs leading-5 ${props.choice === "register" ? "text-slate-200" : "text-slate-500"}`}>
            Create a governed, versioned data asset that authorized projects can reuse. If this project is later deleted, the registered asset and its Library link to other projects remain.
          </p>
        </button>
      </div>

      {props.choice === "register" && !props.registrationResult && (
        <div className="mt-5 space-y-3 rounded-lg border border-blue-100 bg-blue-50/60 p-4">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-1 text-xs font-semibold text-slate-700">
              Dataset Library name
              <input
                className="atlas-input"
                value={props.registerName}
                placeholder={`${props.projectName || "ATLAS Project"} - Development Dataset`}
                onChange={(event) => props.onRegisterNameChange(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold text-slate-700">
              Tags (comma-separated)
              <input className="atlas-input" value={props.registerTags} onChange={(event) => props.onRegisterTagsChange(event.target.value)} placeholder="development, governed" />
            </label>
          </div>
          <label className="grid gap-1 text-xs font-semibold text-slate-700">
            Description / business purpose
            <textarea className="atlas-input" rows={2} value={props.registerDescription} onChange={(event) => props.onRegisterDescriptionChange(event.target.value)} placeholder="What this dataset is and how it should be used." />
          </label>
          <div className="text-xs text-slate-500">Target <strong>{props.target}</strong>, {props.rowCount.toLocaleString()} rows, {props.columnCount} columns, and the current project owner will be recorded automatically.</div>

          {props.checkingDuplicates && <div className="text-xs text-slate-500">Checking for similar existing assets...</div>}
          {!props.checkingDuplicates && props.duplicateCandidates.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950" data-testid="duplicate-suggestions">
              <div className="font-semibold">Possibly similar assets already exist. Review before registering a new one:</div>
              <ul className="mt-2 space-y-1">
                {props.duplicateCandidates.map((candidate) => (
                  <li key={candidate.datasetId}>
                    <Link className="underline" to={`/datasets/${candidate.datasetId}`} target="_blank" rel="noreferrer">
                      {candidate.name}
                    </Link>{" "}
                    ({candidate.latestVersion?.rowCount?.toLocaleString() ?? "-"} rows, owner {candidate.ownerDisplayName ?? candidate.ownerUserId})
                  </li>
                ))}
              </ul>
              <div className="mt-2">This is a suggestion only -- registering below always creates your own new asset.</div>
            </div>
          )}

          {props.registrationError && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-900">{props.registrationError}</div>}

          <button type="button" onClick={props.onRegister} disabled={props.registering} data-testid="register-dataset-action" className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-800 disabled:opacity-60">
            {props.registering ? "Registering..." : props.registrationActionLabel}
          </button>
        </div>
      )}

      {props.registrationResult && (
        <div className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950" data-testid="registration-success">
          <div className="font-semibold">Registered to the Dataset Library</div>
          <div className="mt-2 grid gap-1 text-xs">
            <div>Asset ID: <span className="font-mono">{props.registrationResult.datasetId}</span></div>
            <div>Version ID: <span className="font-mono">{props.registrationResult.latestVersion?.versionId ?? "-"}</span></div>
            <div>This project is now linked to this asset.</div>
          </div>
          <Link className="mt-3 inline-block rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-semibold text-emerald-900" to={`/datasets/${props.registrationResult.datasetId}`}>
            Open in Dataset Library
          </Link>
        </div>
      )}
    </section>
  );
}

function TargetSetup(props: {
  headers: string[];
  target: string;
  setTarget: (value: string) => void;
  eventValue: unknown;
  setEventValue: (value: unknown) => void;
  nonEventValue: unknown;
  setNonEventValue: (value: unknown) => void;
  problemType: "classification" | "regression";
}) {
  const targetConfirmed = Boolean(props.target);
  return (
    <section
      id="data-acquisition-target-setup"
      className="overflow-hidden rounded-xl border-2 border-blue-500 bg-gradient-to-br from-blue-50 via-white to-cyan-50 shadow-[0_14px_34px_rgba(37,99,235,0.16)]"
      data-testid="data-acquisition-target-setup"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 bg-gradient-to-r from-blue-700 to-cyan-700 px-5 py-3 text-white">
        <div className="flex items-center gap-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white text-sm font-black text-blue-700">
            2
          </span>
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-blue-100">
              Required modeling decision
            </div>
            <h2 className="text-base font-semibold">Identify the Target Variable</h2>
          </div>
        </div>
        <span
          className={`rounded-full border px-3 py-1 text-xs font-bold ${
            targetConfirmed
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-amber-200 bg-amber-50 text-amber-900"
          }`}
        >
          {targetConfirmed ? `Target confirmed: ${props.target}` : "Target required"}
        </span>
      </div>
      <div className="p-5">
      <p className="text-sm leading-6 text-slate-700">
        Select the outcome ATLAS must predict. This choice becomes the
        authoritative target for EDA, predictor exclusion, feature engineering,
        validation, and modeling.
      </p>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <Select label="Target Column" value={props.target} onChange={props.setTarget} options={props.headers} />
        {props.problemType === "classification" ? (
          <>
            <Input label="Event / Positive Value" value={String(props.eventValue ?? "")} onChange={props.setEventValue} />
            <Input label="Non-event / Negative Value" value={String(props.nonEventValue ?? "")} onChange={props.setNonEventValue} />
          </>
        ) : (
          <ReadOnlyField label="Target behavior" value="Continuous regression target" />
        )}
      </div>
      <p className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-950">
        ATLAS will exclude <strong>{props.target || "the selected target"}</strong>{" "}
        and any deterministic target-source fields from the predictor set.
      </p>
      </div>
    </section>
  );
}

function PreviewProfilingSettings(props: {
  headers: string[];
  method: SamplingMethod;
  setMethod: (value: SamplingMethod) => void;
  previewRowLimit: number;
  setPreviewRowLimit: (value: number) => void;
  profileRowLimit: number;
  setProfileRowLimit: (value: number) => void;
  randomSeed: number;
  setRandomSeed: (value: number) => void;
  stratificationColumn: string;
  setStratificationColumn: (value: string) => void;
  timeColumn: string;
  setTimeColumn: (value: string) => void;
  registeredRowCount: number;
  previewRowCount: number;
  profileRowCount: number;
  browserDataComplete: boolean;
}) {
  const stratifiedDisabled = !props.browserDataComplete || !props.headers.length;
  const timeDisabled = !props.browserDataComplete || !props.headers.some((header) => /date|time|timestamp/i.test(header));
  return (
    <details className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <summary className="cursor-pointer text-base font-semibold text-slate-950">Preview & Profiling Settings</summary>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <label className="grid gap-1 text-xs font-semibold text-slate-700">
          Preview method
          <select className="atlas-input" value={props.method} onChange={(event) => props.setMethod(event.target.value as SamplingMethod)}>
            <option value="top_n">First rows</option>
            <option value="random">Random sample</option>
            <option value="stratified" disabled={stratifiedDisabled}>Stratified preview</option>
            <option value="time_based" disabled={timeDisabled}>Time-ordered preview</option>
            <option value="full" disabled={!props.browserDataComplete}>Use all available browser rows</option>
          </select>
        </label>
        <NumberInput label="Preview row limit" value={props.previewRowLimit} onChange={props.setPreviewRowLimit} />
        <NumberInput label="Profile row limit" value={props.profileRowLimit} onChange={props.setProfileRowLimit} />
        {props.method === "random" && <NumberInput label="Random seed" value={props.randomSeed} onChange={props.setRandomSeed} />}
        {props.method === "stratified" && <Select label="Stratification variable" value={props.stratificationColumn} onChange={props.setStratificationColumn} options={props.headers} />}
        {props.method === "time_based" && <Select label="Time field" value={props.timeColumn} onChange={props.setTimeColumn} options={props.headers.filter((header) => /date|time|timestamp/i.test(header))} />}
      </div>
      {(stratifiedDisabled || timeDisabled) && (
        <p className="mt-3 text-xs text-amber-800">Stratified and time-ordered previews are enabled only when the complete browser dataset and the required fields are available.</p>
      )}
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <ReadOnlyField label="Current modeling row count" value={props.registeredRowCount.toLocaleString()} />
        <ReadOnlyField label="Current preview row count" value={props.previewRowCount.toLocaleString()} />
        <ReadOnlyField label="Current profile row count" value={props.profileRowCount.toLocaleString()} />
      </div>
      <p className="mt-3 text-sm font-semibold text-emerald-800">Preview and profiling settings do not change the registered modeling dataset.</p>
    </details>
  );
}

function NumberInput({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <label className="grid gap-1 text-xs font-semibold text-slate-700">
      {label}
      <input className="atlas-input" type="number" min={1} value={value} onChange={(event) => onChange(Math.max(1, Number(event.target.value) || 1))} />
    </label>
  );
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function SqlPanel(props: {
  provider: string;
  setProvider: (value: string) => void;
  connectionName: string;
  setConnectionName: (value: string) => void;
  database: string;
  setDatabase: (value: string) => void;
  schema: string;
  setSchema: (value: string) => void;
  sql: string;
  setSql: (value: string) => void;
  warnings: string[];
  savedQueries: string[];
  favoriteQueries: string[];
  onTemplate: (sql: string) => void;
  onSave: () => void;
  onFavorite: () => void;
  onSaveMetadata: () => void;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="rounded-lg border border-slate-200 bg-slate-50 p-3">
        <h2 className="text-sm font-semibold text-slate-950">Database Explorer</h2>
        <div className="mt-3 space-y-2 text-sm text-slate-700">
          <div className="font-medium">{props.provider}</div>
          <div className="pl-3">Connection: {props.connectionName}</div>
          <div className="pl-3">Schemas</div>
          <div className="pl-6">CUSTOMER_BASE</div>
          <div className="pl-8 text-xs text-slate-500">customer_id PK, open_date, status</div>
          <div className="pl-6">TRANSACTION_HISTORY</div>
          <div className="pl-8 text-xs text-slate-500">customer_id FK, amount, txn_date</div>
          <div className="pl-6">BUREAU_ATTRIBUTES</div>
          <div className="pl-8 text-xs text-slate-500">fico_score, trades, inquiries</div>
        </div>
      </aside>
      <div>
        <div className="grid gap-3 md:grid-cols-4">
          <Select label="Provider" value={props.provider} onChange={props.setProvider} options={databaseProviders} />
          <Input label="Connection Name" value={props.connectionName} onChange={props.setConnectionName} />
          <Input label="Database" value={props.database} onChange={props.setDatabase} />
          <Input label="Schema" value={props.schema} onChange={props.setSchema} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {queryTemplates().map((template) => (
            <button key={template.name} className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-medium" onClick={() => props.onTemplate(template.sql)}>
              {template.name}
            </button>
          ))}
        </div>
        <textarea
          className="mt-4 min-h-[260px] w-full rounded-lg border border-slate-300 bg-slate-950 p-4 font-mono text-sm text-emerald-100"
          value={props.sql}
          onChange={(event) => props.setSql(event.target.value)}
          spellCheck={false}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="rounded-lg border px-3 py-2 text-sm" onClick={props.onSave}>Save Query</button>
          <button className="rounded-lg border px-3 py-2 text-sm" onClick={props.onFavorite}>Favorite</button>
          <button className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white" onClick={props.onSaveMetadata}>Validate & Save Query Metadata</button>
        </div>
        {!!props.warnings.length && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <div className="font-semibold">Query validation</div>
            <ul className="mt-1 list-disc pl-5">{props.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          </div>
        )}
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <QueryList title="Saved Queries" queries={props.savedQueries} />
          <QueryList title="Favorites" queries={props.favoriteQueries} />
        </div>
      </div>
    </div>
  );
}

function CloudPanel({ cloudProvider, setCloudProvider, cloudPath, setCloudPath }: { cloudProvider: string; setCloudProvider: (value: string) => void; cloudPath: string; setCloudPath: (value: string) => void }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-slate-950">Cloud Storage</h2>
      <p className="mt-1 text-sm text-slate-500">Capture cloud data source metadata now. Actual object reads should be handled by backend connectors with governed credentials.</p>
      <div className="mt-4 grid gap-3 md:grid-cols-[240px_minmax(0,1fr)]">
        <Select label="Cloud Provider" value={cloudProvider} onChange={setCloudProvider} options={cloudProviders} />
        <Input label="Path / URL" value={cloudPath} onChange={setCloudPath} placeholder="s3://bucket/path/train.parquet" />
      </div>
    </div>
  );
}

function ExistingDatasetPanel({
  versions,
  libraryDatasets,
  selectedDatasetId,
  selectedVersionId,
  loading,
  loadProgress,
  isLoaded,
  onDatasetChange,
  onVersionChange,
  onRefresh,
  onLoad,
}: {
  versions: ReturnType<typeof loadDatasetVersions>;
  libraryDatasets: DatasetSummary[];
  selectedDatasetId: string;
  selectedVersionId: string;
  loading: boolean;
  loadProgress: DatasetLoadProgress;
  isLoaded: boolean;
  onDatasetChange: (datasetId: string) => void;
  onVersionChange: (versionId: string) => void;
  onRefresh: () => void;
  onLoad: () => void;
}) {
  const selectedDataset = libraryDatasets.find((dataset) => dataset.datasetId === selectedDatasetId);
  const selectedVersions = selectedDataset?.latestVersion ? [selectedDataset.latestVersion] : [];
  const isLoading = loadProgress.phase === "loading";
  const failed = loadProgress.phase === "failed";
  // Part A/5: a successful load only counts for the selection that produced it.
  const showLoaded = isLoaded && loadProgress.phase === "loaded";
  const canLoad = Boolean(selectedDatasetId && selectedVersionId) && !isLoading;

  const buttonLabel = isLoading
    ? "Loading Selected Version..."
    : showLoaded
      ? "Version Loaded"
      : failed
        ? "Retry Load"
        : "Load Selected Version";
  const buttonClass = isLoading
    ? "border-blue-300 bg-blue-100 text-blue-800"
    : showLoaded
      ? "border-emerald-600 bg-emerald-600 text-white hover:bg-emerald-700"
      : "border-blue-700 bg-blue-700 text-white hover:bg-blue-800";

  return (
    <div>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-950">Existing Dataset Library Asset</h2>
          <p className="mt-1 text-sm text-slate-500">
            Load a governed dataset version from the backend Dataset Library and link it to this ATLAS project.
          </p>
        </div>
        <button type="button" onClick={onRefresh} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">
          {loading ? "Refreshing..." : "Refresh Library"}
        </button>
      </div>

      {/* UX-DATAACQ-001: the load action is a primary command directly beneath its
          own selectors, not a weak control at the far-right edge of the row. */}
      <div className="mt-4 rounded-xl border-2 border-blue-300 bg-blue-50 p-4" data-testid="dataset-load-command">
        <div className="grid gap-3 md:grid-cols-2">
          <Select
            label="Dataset"
            value={selectedDatasetId}
            onChange={onDatasetChange}
            options={libraryDatasets.map((dataset) => dataset.datasetId)}
            optionLabels={Object.fromEntries(libraryDatasets.map((dataset) => [dataset.datasetId, `${dataset.name} (${dataset.latestVersion?.rowCount?.toLocaleString() ?? 0} rows)`]))}
          />
          <Select
            label="Version"
            value={selectedVersionId}
            onChange={onVersionChange}
            options={selectedVersions.map((version) => version.versionId)}
          />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={onLoad}
            disabled={!canLoad}
            aria-busy={isLoading}
            data-testid="load-selected-version"
            data-load-state={isLoading ? "loading" : showLoaded ? "loaded" : failed ? "failed" : "unloaded"}
            className={`inline-flex items-center gap-2 rounded-lg border-2 px-5 py-2.5 text-sm font-semibold shadow-sm transition disabled:cursor-not-allowed disabled:opacity-60 ${buttonClass}`}
          >
            {isLoading && <Loader2 size={16} className="motion-safe:animate-spin" aria-hidden="true" />}
            {showLoaded && <Check size={16} aria-hidden="true" />}
            {buttonLabel}
          </button>
          {showLoaded && (
            <span className="text-xs font-semibold text-emerald-800" data-testid="dataset-loaded-identity">
              {selectedDataset?.name ?? selectedDatasetId}, version <span className="font-mono">{selectedVersionId}</span>, loaded into this project.
            </span>
          )}
        </div>
        <DatasetLoadProgressPanel progress={loadProgress} />
      </div>

      {selectedDataset && (
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <Stat label="Library Dataset" value={selectedDataset.name} />
          <Stat label="Rows" value={selectedDataset.latestVersion?.rowCount ?? "-"} />
          <Stat label="Columns" value={selectedDataset.latestVersion?.columnCount ?? "-"} />
          <Stat label="Owner" value={selectedDataset.ownerDisplayName || selectedDataset.ownerUserId || "-"} />
        </div>
      )}
      {!libraryDatasets.length && (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          No reusable datasets are registered yet. Open Dataset Library to upload or register governed datasets.
        </div>
      )}

      {/* UX-DATAACQ-002: browser-session import records are lineage diagnostics, not
          analyst workflow input. They stay available (and keep flowing into project
          snapshots) but are collapsed, and never render an empty placeholder table. */}
      {versions.length > 0 && (
        <details className="mt-5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2" data-testid="advanced-session-details">
          <summary className="cursor-pointer text-xs font-semibold text-slate-700">
            Advanced session details ({versions.length} browser import record{versions.length === 1 ? "" : "s"})
          </summary>
          <div className="mt-2 overflow-auto rounded-lg border border-slate-200 bg-white">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr><th className="px-3 py-2 text-left">Version</th><th className="px-3 py-2 text-left">Source</th><th className="px-3 py-2 text-right">Rows</th><th className="px-3 py-2 text-right">Columns</th><th className="px-3 py-2 text-left">Imported</th></tr>
              </thead>
              <tbody>{versions.map((row) => <tr key={row.version} className="border-t"><td className="px-3 py-2 font-mono text-xs">{row.version}</td><td className="px-3 py-2">{row.sourceLabel}</td><td className="px-3 py-2 text-right">{row.rows}</td><td className="px-3 py-2 text-right">{row.columns}</td><td className="px-3 py-2">{new Date(row.importedAt).toLocaleString()}</td></tr>)}</tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

function PythonPanel({ pythonCode, setPythonCode }: { pythonCode: string; setPythonCode: (value: string) => void }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-slate-950">Python Loader</h2>
      <p className="mt-1 text-sm text-slate-500">Document advanced loading code. Backend execution can later synchronize the resulting dataframe back into the app.</p>
      <textarea className="mt-4 min-h-[260px] w-full rounded-lg border border-slate-300 bg-slate-950 p-4 font-mono text-sm text-emerald-100" value={pythonCode} onChange={(event) => setPythonCode(event.target.value)} spellCheck={false} />
    </div>
  );
}

function DataPreview(props: {
  headers: string[];
  rows: Record<string, unknown>[];
  target: string;
  targetInfo: { kind: "none" | "binary" | "continuous"; eventRate: number | null };
  targetSummary: { mean: number; median: number; std: number; min: number; max: number } | null;
  effectiveModelingRowCount: number;
  previewRowCount: number;
  backendImportSynced: boolean;
  /** Part F: authoritative event rate plus the population it describes. */
  eventRate: number | null;
  eventRateScopeLabel: string;
  eventRateIsAuthoritative: boolean;
}) {
  return (
    <section className="min-w-0 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div>
        <div>
          <h2 className="text-base font-semibold text-slate-950">Data Preview</h2>
          <p className="mt-1 text-sm text-slate-500">Configured browser preview rows. Preview settings do not alter the registered modeling population.</p>
        </div>
      </div>
      {!!props.headers.length && (
        <div className={`mt-5 rounded-xl border px-4 py-4 text-sm shadow-sm ${props.target ? "border-blue-200 bg-blue-50 text-blue-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
          <div className="text-sm font-semibold">Target profile</div>
          <p className="mt-2 text-xs leading-5">
            {props.target
              ? `Selected ${props.target}. Detected target type: ${props.targetInfo.kind}.`
              : "Select the dependent variable in Target Setup before continuing to EDA and model training."}
          </p>
          {props.targetInfo.kind === "binary" && props.eventRate !== null && props.eventRate > 0 && props.eventRate < 0.01 && (
            <div className="mt-3 rounded-lg border border-amber-300 bg-amber-100 px-3 py-2 text-xs leading-5 text-amber-950">
              <span className="font-semibold">Rare-event target detected:</span> event rate is {formatEventRate(props.eventRate)}.
              Use PR-AUC, recall, lift, KS, and calibration in addition to ROC-AUC; accuracy will be misleading.
            </div>
          )}
          {props.targetInfo.kind === "binary" && !props.eventRateIsAuthoritative && (
            <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950" data-testid="preview-only-event-rate-warning">
              The event rate below is derived from the browser preview only and can under-report rare events. Full-population
              profiling supplies the authoritative rate once the backend profile is available.
            </p>
          )}
        </div>
      )}
      <div className="mt-5 grid gap-3 md:grid-cols-4">
        <Stat label="Modeling Rows" value={props.effectiveModelingRowCount} />
        <Stat label="Browser Preview Rows" value={props.previewRowCount} />
        <Stat label="Columns" value={props.headers.length} />
        <Stat label="Target Type" value={props.targetInfo.kind} />
        {props.targetInfo.kind === "continuous" ? (
          <>
            <Stat label="Target Mean" value={formatNumber(props.targetSummary?.mean)} />
            <Stat label="Target Median" value={formatNumber(props.targetSummary?.median)} />
            <Stat label="Target Std Dev" value={formatNumber(props.targetSummary?.std)} />
            <Stat label="Target Min / Max" value={`${formatNumber(props.targetSummary?.min)} / ${formatNumber(props.targetSummary?.max)}`} />
          </>
        ) : (
          // Part F: the authoritative full-population rate, explicitly scoped. The
          // previous implementation computed this from the ~100-row browser preview,
          // which reported 0.00% for a genuinely 0.21% rare-event target.
          <Stat
            label={`Event Rate (${props.eventRateScopeLabel})`}
            value={formatEventRate(props.eventRate)}
            testId="target-profile-event-rate"
          />
        )}
      </div>
      {props.backendImportSynced && (
        <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs leading-5 text-emerald-900">
          Backend import is active. ATLAS cached {props.previewRowCount.toLocaleString()} rows for the browser preview while preserving {props.effectiveModelingRowCount.toLocaleString()} rows for backend modeling.
        </div>
      )}
      <div className="mt-4 max-h-[360px] overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-xs">
          <thead className="sticky top-0 bg-slate-50 text-slate-500">
            <tr>{props.headers.map((header) => <th key={header} className="whitespace-nowrap px-3 py-2 text-left">{header}</th>)}</tr>
          </thead>
          <tbody>{props.rows.map((row, index) => <tr key={index} className="border-t">{props.headers.map((header) => <td key={header} className="whitespace-nowrap px-3 py-2">{String(row[header] ?? "")}</td>)}</tr>)}</tbody>
        </table>
        {!props.headers.length && <div className="p-8 text-center text-sm text-slate-500">Load data or save SQL metadata to begin.</div>}
      </div>
    </section>
  );
}

function DataQualityPanel({ quality, metadata }: { quality: DataQualitySummary | null; metadata: DataAccessMetadata | null }) {
  if (!quality) return <div className="atlas-empty-state text-sm text-slate-600">Quality profiling has not been generated.</div>;
  const actualOr = (values: string[], empty = "None detected") => values.length ? values.join(", ") : empty;
  return (
    <div className="space-y-4">
      {!!quality.warnings?.length && (
        <div className="atlas-warning-panel">
          <div className="text-sm font-semibold">Priority findings</div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">{quality.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </div>
      )}
      <div>
        <h3 className="atlas-section-title">Dataset identity and scope</h3>
        <div className="mt-3 grid gap-3 md:grid-cols-4">
          <Stat label="Registered rows" value={quality.registeredRowCount ?? quality.rowCount} />
          <Stat label="Profiled rows" value={quality.profiledRowCount ?? quality.rowCount} />
          <Stat label="Columns" value={quality.columnCount} />
          <Stat label="Memory estimate" value={`${quality.memoryEstimateMb.toFixed(2)} MB`} />
          {metadata?.version && <Stat label="Dataset version" value={quality.datasetVersion ?? metadata.version} />}
          {(quality.datasetHash || metadata?.hash) && <Stat label="Dataset hash" value={quality.datasetHash ?? metadata?.hash ?? ""} />}
        </div>
      </div>
      {/* Part D: the five findings groups are visually separated and semantically
          toned -- green when a check is clean, amber when it needs attention. Grey
          is reserved for genuinely neutral information. */}
      <div className="grid gap-4 lg:grid-cols-2">
        <QualityGroup title="Row and column health" tone={quality.duplicateRows || quality.constantColumns.length || quality.nearZeroVarianceColumns.length ? "warning" : "success"}>
          <QualityLine label="Duplicate rows" value={quality.duplicateRows.toLocaleString()} />
          <QualityLine label="Duplicate ID candidates" value={actualOr(quality.duplicateIdCandidates)} />
          <QualityLine label="Constant columns" value={actualOr(quality.constantColumns)} />
          <QualityLine label="Near-zero variance" value={actualOr(quality.nearZeroVarianceColumns)} />
        </QualityGroup>
        <QualityGroup title="Missingness and duplicates" tone={quality.missing.some((row) => row.percent > 0) || quality.unexpectedDatatypeColumns.length ? "warning" : "success"}>
          <QualityLine label="Highest missing fields" value={quality.missing.slice(0, 5).map((row) => `${row.column} ${formatPercent(row.percent)}`).join(", ") || "None detected"} />
          <QualityLine label="High-cardinality categoricals" value={actualOr(quality.highCardinalityCategoricals)} />
          <QualityLine label="Unexpected datatypes" value={actualOr(quality.unexpectedDatatypeColumns)} />
        </QualityGroup>
        <QualityGroup title="Predictor readiness" tone={quality.outlierPrevalence.length ? "warning" : "success"}>
          <QualityLine label="Outlier prevalence" value={quality.outlierPrevalence.length ? quality.outlierPrevalence.slice(0, 5).map((row) => `${row.column} ${formatPercent(row.percent)}`).join(", ") : "None detected"} />
          <QualityLine label="Legitimate date ranges" value={quality.dateRanges.length ? quality.dateRanges.map((row) => `${row.column}: ${row.min} to ${row.max}`).join(", ") : "None detected"} />
        </QualityGroup>
        <QualityGroup title="Leakage and target health" tone={quality.potentialLeakageColumns.length ? "warning" : "success"}>
          <QualityLine label="Potential leakage candidates" value={actualOr(quality.potentialLeakageColumns)} />
          {/* Rare-event-safe precision: formatEventRate keeps two significant digits
              below 1%, so a genuine 0.21% rate never renders as 0.00%. */}
          <QualityLine label="Event rate" value={formatEventRate(quality.classBalance?.eventRate)} />
          <QualityLine label="Majority class" value={formatEventRate(quality.classBalance?.majorityClassPercent)} />
        </QualityGroup>
      </div>
    </div>
  );
}

function QualityGroup({
  title,
  tone,
  children,
}: {
  title: string;
  tone: "success" | "warning";
  children: React.ReactNode;
}) {
  const toneClass = tone === "warning" ? "border-amber-300 bg-amber-50" : "border-emerald-200 bg-emerald-50";
  const headingClass = tone === "warning" ? "text-amber-900" : "text-emerald-900";
  return (
    <div className={`rounded-xl border p-4 ${toneClass}`} data-quality-group={title} data-quality-tone={tone}>
      <div className="flex items-center justify-between gap-2">
        <h3 className={`text-xs font-bold uppercase tracking-wide ${headingClass}`}>{title}</h3>
        {/* Text status, so the group is readable without relying on color. */}
        <span className={`text-[10px] font-semibold uppercase tracking-wide ${headingClass}`}>
          {tone === "warning" ? "Review" : "Clear"}
        </span>
      </div>
      <div className="mt-3 grid gap-2 rounded-lg bg-white p-3 text-sm">{children}</div>
    </div>
  );
}

const readinessBadgeClass: Record<ReadinessStatus, string> = {
  ready: "border-emerald-300 bg-emerald-100 text-emerald-900",
  ready_with_warnings: "border-amber-300 bg-amber-100 text-amber-900",
  review_required: "border-amber-400 bg-amber-100 text-amber-950",
  blocked: "border-red-300 bg-red-100 text-red-900",
};

/**
 * Lifecycle badge for the readiness checkpoint.
 *
 * Part A closure: this used to take `readiness.status` from
 * `computeReadinessStatus` -- a SECOND lifecycle derivation that could report
 * "Blocked" while the hero reported "Ready with warnings". It now renders the
 * one shared `acquisitionStatus`, so the checkpoint cannot disagree with the
 * rest of the page.
 */
function ReadinessBadge({ status }: { status: DataAcquisitionStatus }) {
  const toneClass: Record<string, string> = {
    success: "border-emerald-300 bg-emerald-50 text-emerald-900",
    warning: "border-amber-300 bg-amber-50 text-amber-900",
    danger: "border-red-300 bg-red-50 text-red-900",
    info: "border-blue-200 bg-blue-50 text-blue-900",
    neutral: "border-slate-200 bg-slate-50 text-slate-700",
  };
  return (
    <span
      className={`rounded-full border px-3 py-1 text-xs font-bold ${toneClass[status.readinessTone]}`}
      data-testid="readiness-status-badge"
      data-readiness-status={status.readiness}
      data-review-state={status.reviewState}
    >
      {status.readinessLabel}
    </span>
  );
}

/**
 * Part H4: concise readiness reveal shown above the detailed findings. Every
 * value is read straight from the current authoritative profiling result -- there
 * are no placeholder or animated-from-zero numbers, so the summary is correct
 * the first time it paints and stays readable with motion disabled.
 */
function ReadinessSummary({
  quality,
  readiness,
  acquisitionStatus,
  registeredRowCount,
  eventRateDisplay,
  eventRateScopeLabel,
}: {
  quality: DataQualitySummary | null;
  /** FINDINGS ONLY. Its `.status` is never rendered as a lifecycle state. */
  readiness: { status: ReadinessStatus; reasons: string[] };
  acquisitionStatus: DataAcquisitionStatus;
  registeredRowCount: number;
  eventRateDisplay: string;
  eventRateScopeLabel: string;
}) {
  if (!quality) {
    return (
      <p className="mt-4 rounded-lg border border-teal-200 bg-white px-3 py-2 text-sm text-slate-600" data-testid="readiness-summary">
        Load a dataset and confirm a target to generate the readiness profile.
      </p>
    );
  }
  const columnsWithMissing = quality.missing.filter((row) => row.percent > 0).length;
  const facts: { label: string; value: string; tone: "info" | "warning" | "success" }[] = [
    { label: "Modeling rows", value: registeredRowCount.toLocaleString(), tone: "info" },
    { label: "Columns", value: quality.columnCount.toLocaleString(), tone: "info" },
    { label: "Duplicate rows", value: quality.duplicateRows.toLocaleString(), tone: quality.duplicateRows ? "warning" : "success" },
    { label: "Columns with missing values", value: columnsWithMissing.toLocaleString(), tone: columnsWithMissing ? "warning" : "success" },
    { label: "Leakage candidates", value: quality.potentialLeakageColumns.length.toLocaleString(), tone: quality.potentialLeakageColumns.length ? "warning" : "success" },
    { label: `Event rate (${eventRateScopeLabel})`, value: eventRateDisplay, tone: "info" },
  ];
  const toneClass = {
    info: "border-blue-200 text-blue-900",
    warning: "border-amber-300 text-amber-900",
    success: "border-emerald-200 text-emerald-900",
  } as const;

  return (
    <div className="mt-4" data-testid="readiness-summary">
      {/* Part A closure: the lifecycle sentence comes from the shared model.
          `readiness` below contributes FINDINGS ONLY. */}
      <div className="text-sm font-semibold text-teal-950" data-testid="readiness-summary-status">
        Analytical readiness: {acquisitionStatus.readinessLabel} - User review: {acquisitionStatus.reviewLabel}
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {facts.map((fact) => (
          <div key={fact.label} className={`rounded-lg border bg-white px-3 py-2 ${toneClass[fact.tone]}`}>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{fact.label}</div>
            <div className="mt-0.5 text-sm font-semibold">{fact.value}</div>
          </div>
        ))}
      </div>
      {readiness.reasons.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs leading-5 text-slate-700" data-testid="readiness-reasons">
          {readiness.reasons.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
      )}
    </div>
  );
}

function ProfileScopeBadge({ quality }: { quality: DataQualitySummary | null }) {
  const label = !quality
    ? "Not Generated"
    : quality.profileScope === "full_dataset"
      ? "Full Dataset"
      : quality.profileScope === "complete_browser_dataset"
        ? "Complete Browser Dataset"
        : quality.profileScope === "preview_profile"
          ? `Preview Profile: ${(quality.profiledRowCount ?? quality.rowCount).toLocaleString()} Rows`
          : "Not Generated";
  return <span className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-800">{label}</span>;
}

function LineagePanel({ metadata }: { metadata: DataAccessMetadata | null }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">Data Lineage</h2>
      <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
        {(metadata?.lineage ?? ["Source not captured"]).map((item, index, arr) => (
          <span key={`${item}-${index}`} className="flex items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1">{item}</span>
            {index < arr.length - 1 && <span className="text-slate-400">to</span>}
          </span>
        ))}
      </div>
    </section>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
  optionLabels,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
  optionLabels?: Record<string, string>;
}) {
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
      {label}
      <select className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case text-slate-900" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option} value={option}>{optionLabels?.[option] ?? (option || "Select")}</option>)}
      </select>
    </label>
  );
}

function Input({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
      {label}
      <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function Stat({ label, value, testId }: { label: string; value: unknown; testId?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2" data-testid={testId}>
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950" title={String(value)}>{String(value)}</div>
    </div>
  );
}

function QualityLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-2">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-slate-800">{value}</div>
    </div>
  );
}

function QueryList({ title, queries }: { title: string; queries: string[] }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{title}</div>
      <div className="mt-2 space-y-2">{queries.length ? queries.map((query, index) => <div key={index} className="truncate text-xs text-slate-600">{query}</div>) : <div className="text-xs text-slate-400">None</div>}</div>
    </div>
  );
}

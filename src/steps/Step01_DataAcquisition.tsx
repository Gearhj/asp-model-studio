import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
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
  const [featureProfile, setFeatureProfile] = useState<FeatureProfileResponse | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [backendImportSynced, setBackendImportSynced] = useState(false);
  const [backendRowCount, setBackendRowCount] = useState<number | null>(null);
  const [libraryDatasets, setLibraryDatasets] = useState<DatasetSummary[]>([]);
  const [selectedLibraryDatasetId, setSelectedLibraryDatasetId] = useState("");
  const [selectedLibraryVersionId, setSelectedLibraryVersionId] = useState("");
  const [libraryLoading, setLibraryLoading] = useState(false);
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
  const continuousTargetSummary = useMemo(() => targetSummary(targetAnalysisRows, target), [targetAnalysisRows, target]);
  const selectable = headers.filter((header) => header !== target);
  const selected = selectable.filter((header) => kept[header]);
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

  const variableSummary = useMemo(
    () => (featureProfile?.features ?? []).map((row) => ({
      column: row.predictor,
      type: row.datatype,
      missingPct: row.missingPercent,
      distinct: row.distinctCount,
      mean: row.mean,
      min: row.minimum,
      max: row.maximum,
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
      fetchFullFeatureProfile(profileDataset, projectId)
        .then((payload) => alive && setFeatureProfile(payload))
        .catch(() => alive && setFeatureProfile(browserProfile()));
    } else {
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
        profileScope: completeBrowserDataset ? "complete_browser_dataset" as const : "preview_profile" as const,
        profiledRowCount: completeBrowserDataset ? fullSourceRows.length : profilingRows.length,
        registeredRowCount,
        rowCount: registeredRowCount,
        warnings: completeBrowserDataset ? base.warnings : ["This report is based on configured profiling rows, not the full registered dataset."],
        readinessStatus: "needs_review" as const,
      };
    };
    if (backendImportSynced) {
      fetchFullDataQualityProfile({ projectId, target, eventValue, nonEventValue, selectedColumns: selected })
        .then((payload) => alive && setQuality(payload))
        .catch(() => alive && setQuality(browserQuality()));
    } else {
      setQuality(browserQuality());
    }
    return () => {
      alive = false;
    };
  }, [headers, target, profilingRows, fullSourceRows, completeBrowserDataset, registeredRowCount, backendImportSynced, eventValue, nonEventValue, selected.join("|")]);

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

  function applyWeakSignalFilter() {
    const nextKept = { ...kept };
    variableSummary.forEach((row) => {
      const leakageRole = row.role === "eligible" ? "" : row.role;
      if (leakageRole) {
        nextKept[row.column] = false;
        return;
      }
      const metric = targetInfo.kind === "continuous" ? Math.abs(Number(row.corr)) : Number(row.iv);
      const threshold = targetInfo.kind === "continuous" ? WEAK_CORRELATION_THRESHOLD : WEAK_IV_THRESHOLD;
      if (Number.isFinite(metric) && metric < threshold) nextKept[row.column] = false;
    });
    saveKeptSelection(nextKept);
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "feature_inclusion_changed",
      subject: "Weak signal global filter",
      previousValue: kept,
      newValue: nextKept,
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
    const dq = inferDataQuality({ headers: normalized.headers, rows: normalized.previewRows.slice(0, 5000), target: guessedTarget || null });
    setQuality({
      ...dq,
      rowCount: normalized.rowCount,
      memoryEstimateMb: normalized.rowCount * Math.max(1, normalized.headers.length) * 16 / 1024 / 1024,
    });
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

  const nextDisabledReason = dataAcquisitionDisabledReason({
    isImporting,
    hasHeaders: headers.length > 0,
    hasTarget: !!target,
    importError,
  }) || (!selected.length ? "Select at least one eligible predictor before continuing." : "");
  const messageClass =
    importError && !headers.length
      ? "border-red-200 bg-red-50 text-red-900"
      : isImporting
        ? "border-blue-200 bg-blue-50 text-blue-900"
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
    if (rows.length) setQuality(inferDataQuality({ headers, rows: rows.slice(0, 5000), target: next || null }));
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
      onDatasetChange={(datasetId) => {
        const dataset = libraryDatasets.find((item) => item.datasetId === datasetId);
        setSelectedLibraryDatasetId(datasetId);
        setSelectedLibraryVersionId(dataset?.latestVersion?.versionId ?? "");
      }}
      onVersionChange={setSelectedLibraryVersionId}
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
        try {
          const [preview, activation] = await Promise.all([
            getDatasetPreview(selectedLibraryDatasetId, selectedLibraryVersionId),
            activateDatasetVersion(selectedLibraryDatasetId, selectedLibraryVersionId, projectId),
          ]);
          const normalized = {
            headers: preview.columns,
            previewRows: preview.rows,
            rowCount: activation.row_count ?? dataset?.latestVersion?.rowCount ?? preview.rows.length,
            columnCount: preview.columns.length,
            target: preferredTarget(preview.columns),
            selectedColumns: preview.columns.filter((header) => header !== preferredTarget(preview.columns)),
            filename: dataset?.name ?? selectedLibraryDatasetId,
          };
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
          setMessage(`Loaded ${dataset?.name ?? "Dataset Library asset"} version ${selectedLibraryVersionId} into Data Acquisition.`);
        } catch (error) {
          setMessage(error instanceof Error ? error.message : "ATLAS could not load the selected dataset version.");
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
        { label: "Dataset", value: fileName || "Not registered", tone: fileName ? "neutral" : "warning" },
        { label: "Registered Rows", value: registeredRowCount ? registeredRowCount.toLocaleString() : "Not available" },
        { label: "Columns", value: headers.length ? headers.length.toLocaleString() : "Not available" },
        { label: "Target", value: target || "Not confirmed", tone: target ? "neutral" : "warning" },
        { label: "Modeling Readiness", value: nextDisabledReason ? "Needs review" : "Ready", tone: nextDisabledReason ? "warning" : "success" },
      ] satisfies AtlasWorkflowMetric[]}
      nextDisabled={!!nextDisabledReason}
      nextDisabledReason={nextDisabledReason}
      nextPath="/step02"
      onNext={async () => {
        await persistDataset();
      }}
    >
      <div className="space-y-5">
        {message && (
          <div className={`rounded-lg border px-4 py-3 text-sm ${messageClass}`}>
            {message}
          </div>
        )}

        <AtlasStatusStrip
          items={[
            { label: "Source selected", state: fileName || generatedMetadata ? "complete" : "current", detail: fileName || "Choose or configure a source" },
            { label: "Import completed", state: headers.length ? "complete" : "pending", detail: headers.length ? `${headers.length.toLocaleString()} columns available` : "Awaiting source import" },
            { label: "Dataset registered", state: registeredRowCount && backendImportSynced ? "complete" : registeredRowCount ? "warning" : "pending", detail: registeredRowCount ? `${registeredRowCount.toLocaleString()} modeling rows` : "No registered population" },
            { label: "Target confirmed", state: target ? "complete" : "pending", detail: target || "Select the governed outcome" },
            { label: "Quality reviewed", state: quality ? "complete" : "pending", detail: quality ? `${quality.profileScope?.replace(/_/g, " ") ?? "Profile available"}` : "Run data quality review" },
            { label: "Predictors approved", state: selected.length ? "complete" : "pending", detail: selected.length ? `${selected.length.toLocaleString()} selected` : "Approve eligible inputs" },
          ] satisfies AtlasStatusItem[]}
        />

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div>
            <h2 className="text-base font-semibold text-slate-950">Source Selection, File Upload, and Target Setup</h2>
            <p className="mt-1 text-sm text-slate-500">Start here: load the source file and confirm the target column before reviewing summaries or downstream settings.</p>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-5">
            {sourceCards.map((card) => (
              <button
                key={card.id}
                type="button"
                className={`rounded-xl border p-4 text-left shadow-sm transition ${sourceType === card.id ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white/80 text-slate-900 hover:bg-white"}`}
                onClick={() => setSourceType(card.id)}
                aria-pressed={sourceType === card.id}
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
            <div className="mt-5 rounded-xl border border-blue-100 bg-blue-50/60 p-4">
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
          columnCount={headers.length}
          selectedCount={selected.length}
          browserDataComplete={completeBrowserDataset}
          datasetVersion={selectedLibraryVersionId || generatedMetadata?.version || metadata?.version}
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
          />
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-slate-950">Data Quality & Modeling Readiness</h2>
              <p className="mt-1 text-sm text-slate-500">Quality findings identify their actual profiling scope and registered row count.</p>
            </div>
            <ProfileScopeBadge quality={quality} />
          </div>
          <div className="mt-4">
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
                    onChange={(event) => {
                      setAutoExcludeWeakSignals(event.target.checked);
                      if (event.target.checked) applyWeakSignalFilter();
                    }}
                  />
                  <span>
                    Uncheck weak-signal features automatically. Classification uses IV &lt; {WEAK_IV_THRESHOLD.toFixed(2)}; regression uses absolute correlation &lt; {WEAK_CORRELATION_THRESHOLD.toFixed(2)}.
                  </span>
                </label>
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
            <div className="mt-4 max-h-[560px] overflow-auto rounded-lg border border-slate-200">
              <table className="min-w-full text-sm">
                <thead className="sticky top-0 bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-center">Keep</th>
                    <th className="px-3 py-2 text-left">Column</th>
                    <th className="px-3 py-2 text-left">Role</th>
                    <th className="px-3 py-2 text-left">Type</th>
                    <th className="px-3 py-2 text-right">{targetInfo.kind === "continuous" ? "Corr(Target)" : "IV"}</th>
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
                        <td className={`px-3 py-2 text-right ${targetInfo.kind === "continuous" ? signalStatusClass(row.corr) : ivStatusClass(row.iv)}`}>
                          {formatNumber(targetInfo.kind === "continuous" ? row.corr : row.iv)}
                        </td>
                        <td className="px-3 py-2 text-right">{formatPercent(row.missingPct)}</td>
                        <td className="px-3 py-2 text-right">{row.distinct.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right">{formatNumber(row.mean)}</td>
                        <td className="px-3 py-2 text-right">{formatNumber(row.min)}</td>
                        <td className="px-3 py-2 text-right">{formatNumber(row.max)}</td>
                        <td className={`px-3 py-2 text-xs font-semibold ${leakageRole ? "text-rose-700" : "text-emerald-700"}`}>{leakageRole ? "Excluded" : "Eligible"}</td>
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
  columnCount: number;
  selectedCount: number;
  browserDataComplete: boolean;
  datasetVersion?: string;
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">Current Dataset Summary</h2>
      <p className="mt-1 text-sm text-slate-500">Registered modeling data and governed selection state.</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Dataset" value={props.fileName || "Source metadata only"} />
        <Stat label="Source" value={sourceCards.find((card) => card.id === props.sourceType)?.title ?? props.sourceType} />
        <Stat label="Registered rows" value={props.registeredRowCount} />
        <Stat label="Columns" value={props.columnCount} />
        <Stat label="Target" value={props.target || "Not selected"} />
        <Stat label="Selected predictors" value={props.selectedCount} />
        <Stat label="Browser data" value={props.browserDataComplete ? "Complete dataset" : "Preview only"} />
        <Stat label="Dataset version" value={props.datasetVersion || "Not registered"} />
      </div>
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
}) {
  return (
    <section className="mt-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm" data-testid="dataset-persistence-card">
      <h2 className="text-base font-semibold text-slate-950">Dataset Persistence</h2>
      <p className="mt-1 text-sm text-slate-500">
        Choose how ATLAS should store this dataset. Status: <span className="font-semibold text-slate-800">{props.registrationResult ? "Registered Asset" : "Workspace Upload"}</span>
      </p>
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

          <button type="button" onClick={props.onRegister} disabled={props.registering} className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 disabled:opacity-60">
            {props.registering ? "Registering..." : "Register Development Dataset"}
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
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">Target Setup</h2>
      <p className="mt-1 text-sm text-slate-500">Choose the outcome field. Binary classification also requires an explicit event and non-event definition.</p>
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
  onDatasetChange: (datasetId: string) => void;
  onVersionChange: (versionId: string) => void;
  onRefresh: () => void;
  onLoad: () => void;
}) {
  const selectedDataset = libraryDatasets.find((dataset) => dataset.datasetId === selectedDatasetId);
  const selectedVersions = selectedDataset?.latestVersion ? [selectedDataset.latestVersion] : [];
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
      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(240px,360px)_auto] lg:items-end">
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
        <button type="button" onClick={onLoad} className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
          Load Selected Version
        </button>
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
      <div className="mt-5">
        <h3 className="text-sm font-semibold text-slate-950">Browser Session Dataset History</h3>
        <div className="mt-2 overflow-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr><th className="px-3 py-2 text-left">Version</th><th className="px-3 py-2 text-left">Source</th><th className="px-3 py-2 text-right">Rows</th><th className="px-3 py-2 text-right">Columns</th><th className="px-3 py-2 text-left">Imported</th></tr>
            </thead>
            <tbody>{versions.map((row) => <tr key={row.version} className="border-t"><td className="px-3 py-2 font-mono text-xs">{row.version}</td><td className="px-3 py-2">{row.sourceLabel}</td><td className="px-3 py-2 text-right">{row.rows}</td><td className="px-3 py-2 text-right">{row.columns}</td><td className="px-3 py-2">{new Date(row.importedAt).toLocaleString()}</td></tr>)}</tbody>
          </table>
          {!versions.length && <div className="p-6 text-center text-sm text-slate-500">No browser-session dataset versions captured yet.</div>}
        </div>
      </div>
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
          {props.targetInfo.kind === "binary" && props.targetInfo.eventRate !== null && props.targetInfo.eventRate < 0.01 && (
            <div className="mt-3 rounded-lg border border-amber-300 bg-amber-100 px-3 py-2 text-xs leading-5 text-amber-950">
              <span className="font-semibold">Rare-event target detected:</span> event rate is {formatPercent(props.targetInfo.eventRate)}.
              Use PR-AUC, recall, lift, KS, and calibration in addition to ROC-AUC; accuracy will be misleading.
            </div>
          )}
        </div>
      )}
      <div className="mt-5 grid gap-3 md:grid-cols-4">
        <Stat label="Rows for Modeling" value={props.effectiveModelingRowCount} />
        <Stat label="Rows Cached for UI" value={props.previewRowCount} />
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
          <Stat label="Event Rate" value={props.targetInfo.eventRate === null ? "-" : formatPercent(props.targetInfo.eventRate)} />
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
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="atlas-inset-section">
          <h3 className="atlas-section-title">Row and column health</h3>
          <div className="mt-3 grid gap-3 text-sm">
            <QualityLine label="Duplicate rows" value={quality.duplicateRows.toLocaleString()} />
            <QualityLine label="Duplicate ID candidates" value={actualOr(quality.duplicateIdCandidates)} />
            <QualityLine label="Constant columns" value={actualOr(quality.constantColumns)} />
            <QualityLine label="Near-zero variance" value={actualOr(quality.nearZeroVarianceColumns)} />
          </div>
        </div>
        <div className="atlas-inset-section">
          <h3 className="atlas-section-title">Missingness and duplicates</h3>
          <div className="mt-3 grid gap-3 text-sm">
            <QualityLine label="Highest missing fields" value={quality.missing.slice(0, 5).map((row) => `${row.column} ${formatPercent(row.percent)}`).join(", ") || "None detected"} />
            <QualityLine label="High-cardinality categoricals" value={actualOr(quality.highCardinalityCategoricals)} />
            <QualityLine label="Unexpected datatypes" value={actualOr(quality.unexpectedDatatypeColumns)} />
          </div>
        </div>
        <div className="atlas-inset-section">
          <h3 className="atlas-section-title">Predictor readiness</h3>
          <div className="mt-3 grid gap-3 text-sm">
            <QualityLine label="Outlier prevalence" value={quality.outlierPrevalence.length ? quality.outlierPrevalence.slice(0, 5).map((row) => `${row.column} ${formatPercent(row.percent)}`).join(", ") : "None detected"} />
            <QualityLine label="Legitimate date ranges" value={quality.dateRanges.length ? quality.dateRanges.map((row) => `${row.column}: ${row.min} to ${row.max}`).join(", ") : "None detected"} />
          </div>
        </div>
        <div className="atlas-inset-section">
          <h3 className="atlas-section-title">Leakage and target health</h3>
          <div className="mt-3 grid gap-3 text-sm">
            <QualityLine label="Potential leakage candidates" value={actualOr(quality.potentialLeakageColumns)} />
            <QualityLine label="Event rate" value={quality.classBalance?.eventRate === null || quality.classBalance?.eventRate === undefined ? "Not evaluated" : formatPercent(quality.classBalance.eventRate)} />
            <QualityLine label="Majority class" value={quality.classBalance?.majorityClassPercent === null || quality.classBalance?.majorityClassPercent === undefined ? "Not evaluated" : formatPercent(quality.classBalance.majorityClassPercent)} />
          </div>
        </div>
      </div>
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

function Stat({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950">{String(value)}</div>
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

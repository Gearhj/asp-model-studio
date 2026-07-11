import { useEffect, useMemo, useState } from "react";
import StepShell from "../components/StepShell";
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
  getDatasetPreview,
  linkDatasetToProject,
  listDatasets,
  type DatasetSummary,
} from "../lib/datasetLibrary";
import { useWorkflowStore } from "../state/useWorkflowStore";

const BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

const sourceCards: { id: DataSourceType; title: string; body: string }[] = [
  { id: "upload", title: "Upload File", body: "CSV and JSON parse locally. Excel, Parquet, Feather, SAS, and ZIP are staged for backend import." },
  { id: "sql", title: "SQL Database", body: "Author governed SQL, validate queries, capture lineage, and generate Python extraction code." },
  { id: "cloud", title: "Cloud Storage", body: "Document S3, Azure Blob, GCS, SharePoint, or OneDrive paths for governed ingestion." },
  { id: "existing", title: "Existing Dataset", body: "Reuse previously imported project datasets and preserve dataset version history." },
  { id: "python", title: "Python Loader", body: "Advanced users can document Python or Spark loading logic that assigns the final dataframe to df." },
];

const HELOC_DATA_ACQUISITION_SUMMARY = {
  project: "HELOC Risk Model TEST",
  trainingDataset: "HELOC_TRAIN",
  validationDataset: "HELOC_TEST",
  ootDataset: "HELOC_OOT",
  target: "bad_flag = 1",
  eventValue: "1",
  nonEventValue: "0",
  modelPurpose: "Application Underwriting",
  productType: "Credit Card",
  ootType: "Synthetic holdout",
  sourceType: "Uploaded CSV datasets registered in Dataset Library",
  datasetPurpose: "Credit-risk scorecard test run",
  originalTargetLabel: "RiskPerformance",
  splitColumn: "atlas_split",
};
const WEAK_IV_THRESHOLD = 0.01;
const WEAK_CORRELATION_THRESHOLD = 0.05;

const databaseProviders = ["Oracle", "SQL Server", "PostgreSQL", "MySQL", "Snowflake", "BigQuery", "Databricks SQL", "Teradata", "SQLite", "DuckDB"];
const cloudProviders = ["AWS S3", "Azure Blob Storage", "Google Cloud Storage", "SharePoint", "OneDrive"];
const selectGuidance: Record<string, Record<string, string>> = {
  Sampling: {
    full: "Definition: use all loaded records. Use when the file is small enough for browser and backend processing.",
    sample: "Definition: take the first bounded sample. Use for quick previews when full data is large.",
    random: "Definition: randomly sample records. Use when the preview should represent the full population.",
    stratified: "Definition: preserve target or segment mix while sampling. Use when class balance or business segments matter.",
    time_based: "Definition: preserve temporal order. Use when future performance or out-of-time validation matters.",
    top_n: "Definition: keep the first N rows. Use only for deterministic debugging or fixed extracts.",
  },
  Target: {
    "": "Definition: no target selected. Select the dependent variable before modeling so ATLAS can infer classification versus regression.",
  },
  Provider: Object.fromEntries(databaseProviders.map((providerName) => [providerName, `Definition: ${providerName} governed SQL source. Use when lineage, query review, and repeatable extraction are required.`])),
  "Cloud Provider": Object.fromEntries(cloudProviders.map((providerName) => [providerName, `Definition: ${providerName} object/file source. Use when data is staged in managed cloud or document storage.`])),
};

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

function preferredCreditRiskTarget(headers: string[], fallbackTarget = "") {
  const badFlag = headers.find((header) => /^bad_flag$/i.test(header));
  return badFlag ?? fallbackTarget ?? guessTargetFromHeaders(headers);
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

function applySampling(rows: Record<string, unknown>[], method: SamplingMethod, detail: string) {
  const n = Number(detail) || 1000;
  if (method === "top_n") return rows.slice(0, Math.max(1, n));
  if (method === "sample") return rows.slice(0, Math.min(rows.length, Math.max(1, n)));
  if (method === "random") return [...rows].sort(() => Math.random() - 0.5).slice(0, Math.min(rows.length, Math.max(1, n)));
  return rows;
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
  const [samplingMethod, setSamplingMethod] = useState<SamplingMethod>("full");
  const [samplingDetail, setSamplingDetail] = useState("1000");
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

  useEffect(() => {
    const saved = loadLocalDataset();
    if (!saved?.headers.length) return;

    const savedTarget = saved.target ?? "";
    const selectedSet = new Set(saved.selected_columns ?? []);
    setHeaders(saved.headers);
    setRows(saved.rows ?? []);
    setTarget(savedTarget);
    setKept(
      Object.fromEntries(
        saved.headers.map((header) => [header, header !== savedTarget && selectedSet.has(header)])
      )
    );
    setImportError(null);
    setBackendImportSynced(false);
    setBackendRowCount(null);
    setMessage((current) => current || "Restored the cached modeling dataset and selected features for this browser session.");
    setQuality(
      saved.data_quality ??
        inferDataQuality({ headers: saved.headers, rows: (saved.rows ?? []).slice(0, 5000), target: savedTarget || null })
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

  const modelingRows = useMemo(() => applySampling(rows, samplingMethod, samplingDetail), [rows, samplingMethod, samplingDetail]);
  const sampleRows = useMemo(() => modelingRows.slice(0, 5000), [modelingRows]);
  const effectiveModelingRowCount = backendRowCount ?? modelingRows.length;
  const previewRows = sampleRows.slice(0, 100);
  const targetInfo = useMemo(() => targetMeta(modelingRows, target), [modelingRows, target]);
  const continuousTargetSummary = useMemo(() => targetSummary(modelingRows, target), [modelingRows, target]);
  const selectable = headers.filter((header) => header !== target);
  const selected = selectable.filter((header) => kept[header]);
  const sqlWarnings = useMemo(() => validateSql(sql), [sql]);
  const generatedMetadata = useMemo(() => {
    if (!headers.length) return null;
    return buildDataAccessMetadata({
      dataset: { headers, rows: modelingRows, target },
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
      samplingMethod,
      samplingDetail,
      rowCountOverride: effectiveModelingRowCount,
    });
  }, [headers, modelingRows, target, sourceType, provider, cloudProvider, fileName, connectionName, database, schema, sql, cloudPath, pythonCode, samplingMethod, samplingDetail, effectiveModelingRowCount, libraryDatasets, selectedLibraryDatasetId]);

  const variableSummary = useMemo(
    () =>
      headers.map((column) => ({
        column,
        ...summarizeColumn(sampleRows, column, target),
        iv: informationValue(sampleRows, column, target),
        corr: correlationWithTarget(sampleRows, column, target),
      })),
    [headers, sampleRows, target]
  );

  function saveKeptSelection(nextKept: Record<string, boolean>) {
    setKept(nextKept);
    const localView = buildSelectedDatasetView({
      headers,
      rows: sampleRows,
      selectedColumns: headers.filter((header) => header !== target && !creditRiskLeakageRole(header) && nextKept[header] !== false),
      target: target || null,
    });
    saveLocalDataset({
      headers: localView.headers,
      rows: localView.rows,
      target: target || null,
      selected_columns: localView.selectedColumns,
      problem_type: target ? inferProblemType(localView.rows, target) : undefined,
    });
    window.dispatchEvent(new CustomEvent("atlas-dataset-updated"));
  }

  function applyWeakSignalFilter() {
    const nextKept = { ...kept };
    variableSummary.forEach((row) => {
      const leakageRole = row.column === target ? "Target / Excluded" : creditRiskLeakageRole(row.column);
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

  function applyLoadedDataset(normalized: NormalizedBackendImport, options: { sourceLabel: string; backendSynced: boolean }) {
    const guessedTarget = preferredCreditRiskTarget(normalized.headers, normalized.target);
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
    setSamplingMethod("full");
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
      const response = await fetch(`${BASE}/data/upload_csv`, {
        method: "POST",
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
        target: preferredCreditRiskTarget(parsed.headers),
        selectedColumns: parsed.headers.filter((header) => header !== preferredCreditRiskTarget(parsed.headers)),
        filename: file.name,
      };
      applyLoadedDataset(normalized, { sourceLabel: `Uploaded ${file.name}`, backendSynced: false });
      setMessage(`Loaded ${parsed.rows.length.toLocaleString()} rows and ${parsed.headers.length.toLocaleString()} columns in the browser preview.`);
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
    setMessage("SQL metadata saved. Real query execution requires a backend connector; upload query output or connect the backend to populate rows.");
  }

  async function persistDataset() {
    if (!headers.length) throw new Error("No dataset or query metadata is available.");
    const selectedColumns = selected.length ? selected : selectable;
    const localView = buildSelectedDatasetView({
      headers,
      rows: sampleRows,
      selectedColumns,
      target: target || null,
    });
    const backendView = buildSelectedDatasetView({
      headers,
      rows: modelingRows,
      selectedColumns,
      target: target || null,
    });
    const meta = generatedMetadata;
    const dq = quality ?? inferDataQuality({ headers, rows: sampleRows, target: target || null });
    const problemType = targetInfo.kind === "continuous" ? "regression" : "classification";
    const localPayload: LocalDataset = {
      headers: localView.headers,
      rows: localView.rows,
      target: target || null,
      selected_columns: localView.selectedColumns,
      problem_type: problemType,
      dataset_library:
        sourceType === "existing" && selectedLibraryDatasetId && selectedLibraryVersionId
          ? {
              datasetId: selectedLibraryDatasetId,
              versionId: selectedLibraryVersionId,
              datasetName: libraryDatasets.find((dataset) => dataset.datasetId === selectedLibraryDatasetId)?.name ?? "Dataset Library asset",
              datasetRole: "modeling",
              sourceType: "dataset-library",
              rowCount: effectiveModelingRowCount,
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
          n_samples: effectiveModelingRowCount,
          task: problemType === "regression" ? "regression" : "binary",
          target,
          selected_columns: localView.selectedColumns,
          dataset_version: meta?.version,
        },
      },
    }));

    let backendSynced = backendImportSynced;
    try {
      const backendRes = await fetch(`${BASE}${backendImportSynced ? "/data/set_target" : "/data/set_sample"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(backendImportSynced ? { target, selected_columns: localView.selectedColumns } : backendPayload),
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
      setMessage(`Cached ${sampleRows.length.toLocaleString()} preview rows in the browser and sent ${effectiveModelingRowCount.toLocaleString()} rows to the backend for modeling.`);
    } else if (backendSynced && localSaveStatus !== "failed") {
      setMessage(`Cached ${sampleRows.length.toLocaleString()} preview rows in the browser and synced ${effectiveModelingRowCount.toLocaleString()} rows to the backend for modeling.`);
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
  });
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
    if (headers.length) setImportError(null);
    const localView = buildSelectedDatasetView({
      headers,
      rows: sampleRows,
      selectedColumns: headers.filter((header) => header !== next && kept[header] !== false),
      target: next || null,
    });
    saveLocalDataset({
      headers: localView.headers,
      rows: localView.rows,
      target: next || null,
      selected_columns: localView.selectedColumns,
      problem_type: next ? inferProblemType(localView.rows, next) : undefined,
    });
    window.dispatchEvent(new CustomEvent("atlas-dataset-updated"));
    if (rows.length) setQuality(inferDataQuality({ headers, rows: rows.slice(0, 5000), target: next || null }));
  };

  return (
    <StepShell
      title="Step 1: Data Access & Data Acquisition"
      subtitle="Connect to enterprise data sources, validate extraction logic, preview data, capture lineage, and persist the governed modeling dataset."
      nextDisabled={!!nextDisabledReason}
      nextDisabledReason={nextDisabledReason}
      nextPath="/step01b"
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
            <div className="mt-5 rounded-xl border border-blue-100 bg-blue-50/60 p-4">
              <TargetSetup headers={headers} target={target} setTarget={updateTarget} />
            </div>
            <details className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <summary className="cursor-pointer text-sm font-semibold text-slate-900">Advanced source options</summary>
              <div className="mt-4">
                {sourceType === "upload" && (
                  <p className="text-sm leading-6 text-slate-600">Select SQL Database, Cloud Storage, Existing Dataset, or Python Loader above to configure a non-upload source.</p>
                )}
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
                {sourceType === "existing" && (
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
                        const preview = await getDatasetPreview(selectedLibraryDatasetId, selectedLibraryVersionId);
                        const normalized = {
                          headers: preview.columns,
                          previewRows: preview.rows,
                          rowCount: dataset?.latestVersion?.rowCount ?? preview.rows.length,
                          columnCount: preview.columns.length,
                          target: preferredCreditRiskTarget(preview.columns),
                          selectedColumns: preview.columns.filter((header) => header !== preferredCreditRiskTarget(preview.columns)),
                          filename: dataset?.name ?? selectedLibraryDatasetId,
                        };
                        applyLoadedDataset(normalized, {
                          sourceLabel: `Dataset Library: ${dataset?.name ?? selectedLibraryDatasetId} (${selectedLibraryVersionId})`,
                          backendSynced: false,
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
                )}
                {sourceType === "python" && (
                  <PythonPanel pythonCode={pythonCode} setPythonCode={setPythonCode} />
                )}
              </div>
            </details>
          </div>
        </section>

        <CurrentProjectSummary target={target || "bad_flag"} />

        <DatasetRoleAssignment />
        <SamplingProfilingControls samplingMethod={samplingMethod} setSamplingMethod={setSamplingMethod} samplingDetail={samplingDetail} setSamplingDetail={setSamplingDetail} />
        <details className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <summary className="cursor-pointer text-base font-semibold text-slate-950">Full Data Quality Report</summary>
          <div className="mt-4">
            <DataQualityPanel quality={quality} metadata={generatedMetadata ?? metadata} />
          </div>
        </details>

        <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)] xl:items-start">
          <DataPreview
            headers={headers}
            rows={previewRows}
            target={target}
            targetInfo={targetInfo}
            targetSummary={continuousTargetSummary}
            effectiveModelingRowCount={effectiveModelingRowCount}
            previewRowCount={sampleRows.length}
            backendImportSynced={backendImportSynced}
          />
        </section>

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
                    const nextKept = Object.fromEntries(headers.map((header) => [header, header !== target && !creditRiskLeakageRole(header)]));
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
                    const leakageRole = row.column === target ? "Target / Excluded" : creditRiskLeakageRole(row.column);
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
                        <td className="px-3 py-2 text-xs text-slate-600">{leakageReason(row.column, target)}</td>
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
            <h2 className="text-base font-semibold text-slate-950">Data Lineage and Python Sync</h2>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <LineagePanel metadata={generatedMetadata ?? metadata} />
              <details className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <summary className="cursor-pointer text-base font-semibold text-slate-950">Python Synchronization</summary>
                <div className="mt-4">
                  <PythonSyncPanel metadata={generatedMetadata ?? metadata} />
                </div>
              </details>
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

function CurrentProjectSummary({ target }: { target: string }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">Current Project Summary</h2>
      <p className="mt-1 text-sm text-slate-500">Informational summary for this Credit Risk Studio data acquisition step.</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Project" value={HELOC_DATA_ACQUISITION_SUMMARY.project} />
        <Stat label="Training dataset" value={HELOC_DATA_ACQUISITION_SUMMARY.trainingDataset} />
        <Stat label="Validation dataset" value={HELOC_DATA_ACQUISITION_SUMMARY.validationDataset} />
        <Stat label="OOT dataset" value={HELOC_DATA_ACQUISITION_SUMMARY.ootDataset} />
        <Stat label="Target" value={target === "bad_flag" ? HELOC_DATA_ACQUISITION_SUMMARY.target : `${target || "bad_flag"} = ${HELOC_DATA_ACQUISITION_SUMMARY.eventValue}`} />
        <Stat label="Event / bad value" value={HELOC_DATA_ACQUISITION_SUMMARY.eventValue} />
        <Stat label="Model purpose" value={HELOC_DATA_ACQUISITION_SUMMARY.modelPurpose} />
        <Stat label="Product type" value={HELOC_DATA_ACQUISITION_SUMMARY.productType} />
      </div>
    </section>
  );
}

function DatasetRoleAssignment() {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">Dataset Role Assignment</h2>
      <p className="mt-1 text-sm text-slate-500">One canonical role assignment for the HELOC scorecard test run.</p>
      <div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <ReadOnlyField label="Training Dataset" value={HELOC_DATA_ACQUISITION_SUMMARY.trainingDataset} />
        <ReadOnlyField label="Validation Dataset" value={HELOC_DATA_ACQUISITION_SUMMARY.validationDataset} />
        <ReadOnlyField label="OOT Dataset" value={HELOC_DATA_ACQUISITION_SUMMARY.ootDataset} />
        <ReadOnlyField label="OOT Type" value={HELOC_DATA_ACQUISITION_SUMMARY.ootType} />
        <ReadOnlyField label="Dataset Source Type" value={HELOC_DATA_ACQUISITION_SUMMARY.sourceType} />
        <ReadOnlyField label="Dataset Purpose" value={HELOC_DATA_ACQUISITION_SUMMARY.datasetPurpose} />
      </div>
    </section>
  );
}

function TargetSetup({ headers, target, setTarget }: { headers: string[]; target: string; setTarget: (value: string) => void }) {
  const targetOptions = headers.length ? headers : ["bad_flag", "RiskPerformance", "atlas_split"];
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">Target Setup</h2>
      <p className="mt-1 text-sm text-slate-500">One canonical target definition for the underwriting model.</p>
      <div className="mt-4 grid gap-3 md:grid-cols-5">
        <Select label="Target Column" value={target || "bad_flag"} onChange={setTarget} options={targetOptions} />
        <ReadOnlyField label="Event / Bad Value" value={HELOC_DATA_ACQUISITION_SUMMARY.eventValue} />
        <ReadOnlyField label="Non-event / Good Value" value={HELOC_DATA_ACQUISITION_SUMMARY.nonEventValue} />
        <ReadOnlyField label="Original Target Label Column" value={HELOC_DATA_ACQUISITION_SUMMARY.originalTargetLabel} />
        <ReadOnlyField label="Split Column" value={HELOC_DATA_ACQUISITION_SUMMARY.splitColumn} />
      </div>
      <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-950">
        <div>RiskPerformance is the original target label and must be excluded from predictors.</div>
        <div>bad_flag is the numeric target and must be excluded from predictors.</div>
        <div>atlas_split is split metadata and must be excluded from predictors.</div>
      </div>
    </section>
  );
}

function SamplingProfilingControls({
  samplingMethod,
  setSamplingMethod,
  samplingDetail,
  setSamplingDetail,
}: {
  samplingMethod: SamplingMethod;
  setSamplingMethod: (value: SamplingMethod) => void;
  samplingDetail: string;
  setSamplingDetail: (value: string) => void;
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">Sampling and Profiling Controls</h2>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <Select label="Sampling Method" value={samplingMethod} onChange={(value) => setSamplingMethod(value as SamplingMethod)} options={["full", "sample", "random", "stratified", "time_based", "top_n"]} />
        <Input label="Sample Detail" value={samplingDetail} onChange={setSamplingDetail} />
        <Input label="Profile Rows" value="5000" onChange={() => undefined} />
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-600">
        Sampling controls affect browser preview and profiling ergonomics. Backend modeling should use the full registered dataset unless preview mode is explicitly selected.
      </p>
    </section>
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

function creditRiskLeakageRole(column: string) {
  if (/^riskperformance$/i.test(column)) return "Original Target Label / Excluded";
  if (/^bad_flag$/i.test(column)) return "Target / Excluded";
  if (/^atlas_split$/i.test(column)) return "Split Indicator / Excluded";
  return "";
}

function leakageReason(column: string, target: string) {
  if (column === target || /^bad_flag$/i.test(column)) return "Numeric target; excluded from predictors.";
  if (/^riskperformance$/i.test(column)) return "Original target label; excluded from predictors.";
  if (/^atlas_split$/i.test(column)) return "Split metadata; excluded from predictors.";
  return "Eligible bureau feature; can be selected or deselected.";
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
          <p className="mt-1 text-sm text-slate-500">First 100 rows and schema profile. Target and sampling controls are managed in the setup panels above.</p>
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
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">Data Quality Report</h2>
      <p className="mt-1 text-sm text-slate-500">Automatically generated after import and included in governance documentation.</p>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <Stat label="Dataset Version" value={metadata?.version ?? "-"} />
        <Stat label="Dataset Hash" value={metadata?.hash ?? "-"} />
        <Stat label="Duplicate Rows" value={quality?.duplicateRows ?? "-"} />
        <Stat label="Memory Estimate" value={quality ? `${quality.memoryEstimateMb.toFixed(2)} MB` : "-"} />
      </div>
      <div className="mt-4 grid gap-3 text-sm md:grid-cols-2">
        <QualityLine label="Highest Missing Fields" value={quality?.missing.slice(0, 5).map((row) => `${row.column} ${formatPercent(row.percent)}`).join(", ") || "-"} />
        <QualityLine label="Potential Leakage" value={quality?.potentialLeakageColumns.join(", ") || "RiskPerformance"} />
        <QualityLine label="Constant Columns" value={quality?.constantColumns.join(", ") || "atlas_split"} />
        <QualityLine label="Near-Zero Variance" value={quality?.nearZeroVarianceColumns.join(", ") || "RiskPerformance, bad_flag, atlas_split"} />
        <QualityLine label="High-Cardinality Categoricals" value={quality?.highCardinalityCategoricals.join(", ") || "-"} />
        <QualityLine label="Date Ranges" value={quality?.dateRanges.map((row) => `${row.column}: ${row.min} to ${row.max}`).join(", ") || "-"} />
      </div>
    </section>
  );
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

function PythonSyncPanel({ metadata }: { metadata: DataAccessMetadata | null }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">Python Synchronization</h2>
      <pre className="mt-4 max-h-[260px] overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-emerald-100">{metadata?.generatedPython ?? "Generated loader code appears after data source metadata is captured."}</pre>
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
  const guidance = selectGuidance[label]?.[value] ?? (label === "Target" && value ? `Definition: ${value} is the selected dependent variable. Use it only if it represents the outcome the model should predict.` : "");
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
      {label}
      <select className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case text-slate-900" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option} value={option}>{optionLabels?.[option] ?? (option || "Select")}</option>)}
      </select>
      {guidance && <span className="text-[11px] font-normal normal-case leading-4 text-slate-500">{guidance}</span>}
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

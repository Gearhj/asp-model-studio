import type { LocalDataset } from "./localDataset";
import {
  assertExactDatasetIdentity,
  type CanonicalDatasetIdentity,
} from "./datasetIdentity";

export const DATA_ACCESS_METADATA_KEY = "modeling-tool-data-access-metadata";
export const DATASET_VERSIONS_KEY = "modeling-tool-dataset-versions";

export type DataSourceType = "upload" | "sql" | "cloud" | "existing" | "python";
export type SamplingMethod = "full" | "sample" | "random" | "stratified" | "time_based" | "top_n";

export type DataAccessMetadata = {
  /** Browser-generated identity for this access/import metadata snapshot. */
  accessMetadataId: string;
  /** Browser-generated identity for the source represented by this snapshot. */
  accessSourceId: string;
  hash: string;
  sourceType: DataSourceType;
  sourceLabel: string;
  fileName?: string;
  fileType?: string;
  connectionName?: string;
  provider?: string;
  database?: string;
  schema?: string;
  sqlQuery?: string;
  cloudProvider?: string;
  cloudPath?: string;
  pythonCode?: string;
  tablesReferenced: string[];
  importedAt: string;
  importedBy: string;
  returnedRowCount: number;
  returnedColumns: string[];
  samplingMethod: SamplingMethod;
  samplingDetail: string;
  lineage: string[];
  validationWarnings: string[];
  generatedPython: string;
};

export type DataQualitySummary = {
  projectId?: string;
  datasetId?: string;
  datasetVersionId?: string;
  profileScope?: "full_dataset" | "complete_browser_dataset" | "preview_profile" | "not_generated";
  profiledRowCount?: number;
  registeredRowCount?: number;
  generatedAt?: string;
  datasetVersion?: string;
  datasetHash?: string;
  warnings?: string[];
  readinessStatus?: "ready" | "needs_review" | "not_generated";
  rowCount: number;
  columnCount: number;
  duplicateRows: number;
  duplicateIdCandidates: string[];
  constantColumns: string[];
  nearZeroVarianceColumns: string[];
  highCardinalityCategoricals: string[];
  unexpectedDatatypeColumns: string[];
  potentialLeakageColumns: string[];
  outlierPrevalence: { column: string; percent: number }[];
  classBalance?: { eventRate: number | null; majorityClassPercent: number | null };
  /** Authoritative full-population class counts, when backend profiling produced them.
   *  The Target Distribution chart aggregates from these rather than the browser preview. */
  classDistribution?: { value: unknown; count: number; percent: number }[];
  targetEventValue?: unknown;
  dateRanges: { column: string; min: string; max: string }[];
  missing: { column: string; percent: number }[];
  memoryEstimateMb: number;
};

export type DataAccessHistoryRecord = {
  accessMetadataId: string;
  accessSourceId: string;
  hash: string;
  sourceType: DataSourceType;
  sourceLabel: string;
  target: string | null;
  rows: number;
  columns: number;
  importedAt: string;
  samplingMethod: SamplingMethod;
};

/** @deprecated Use DataAccessHistoryRecord. This history is not Dataset Library version history. */
export type DatasetVersionRecord = DataAccessHistoryRecord;

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return (JSON.parse(raw) as T) ?? fallback;
  } catch {
    return fallback;
  }
}

export function hashText(text: string) {
  let hash = 2166136261;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

export function hashDataset(headers: string[], rows: Record<string, unknown>[]) {
  return hashText(JSON.stringify({ headers, rows: rows.slice(0, 1000), rowCount: rows.length }));
}

export function hashDatasetPreview(headers: string[], rows: Record<string, unknown>[], rowCount: number) {
  return hashText(JSON.stringify({ headers, rows: rows.slice(0, 1000), rowCount }));
}

export function compactTimestamp(date = new Date()) {
  return date.toISOString().replace(/\D/g, "").slice(0, 14);
}

function asNonEmptyString(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const normalized = value.trim();
  return normalized || undefined;
}

/**
 * Reads current access metadata and safely reclassifies legacy browser-only
 * datasetId/version fields as subordinate access identifiers. They are never
 * promoted to canonical Dataset Library identity.
 */
function normalizeDataAccessMetadata(value: unknown): DataAccessMetadata | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const accessMetadataId = asNonEmptyString(raw.accessMetadataId) ?? asNonEmptyString(raw.version);
  const accessSourceId = asNonEmptyString(raw.accessSourceId) ?? asNonEmptyString(raw.datasetId);
  if (!accessMetadataId || !accessSourceId) return null;

  const metadata = { ...raw };
  delete metadata.datasetId;
  delete metadata.version;
  delete metadata.dataset_id;
  delete metadata.dataset_version;
  delete metadata.dataset_version_id;
  return {
    ...metadata,
    accessMetadataId,
    accessSourceId,
  } as DataAccessMetadata;
}

export function loadDataAccessMetadata(): DataAccessMetadata | null {
  return normalizeDataAccessMetadata(readJson<unknown>(DATA_ACCESS_METADATA_KEY, null));
}

export function saveDataAccessMetadata(metadata: DataAccessMetadata) {
  localStorage.setItem(DATA_ACCESS_METADATA_KEY, JSON.stringify(metadata));
  window.dispatchEvent(new CustomEvent("data-access-metadata-updated"));
}

function normalizeDataAccessHistoryRecord(value: unknown): DataAccessHistoryRecord | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const accessMetadataId = asNonEmptyString(raw.accessMetadataId) ?? asNonEmptyString(raw.version);
  const accessSourceId = asNonEmptyString(raw.accessSourceId) ?? asNonEmptyString(raw.datasetId);
  if (!accessMetadataId || !accessSourceId) return null;
  const record = { ...raw };
  delete record.datasetId;
  delete record.version;
  delete record.dataset_id;
  delete record.dataset_version;
  delete record.dataset_version_id;
  return {
    ...record,
    accessMetadataId,
    accessSourceId,
  } as DataAccessHistoryRecord;
}

export function loadDataAccessHistory(): DataAccessHistoryRecord[] {
  const stored = readJson<unknown[]>(DATASET_VERSIONS_KEY, []);
  return stored
    .map(normalizeDataAccessHistoryRecord)
    .filter((record): record is DataAccessHistoryRecord => record !== null);
}

/** @deprecated Use loadDataAccessHistory. */
export function loadDatasetVersions(): DataAccessHistoryRecord[] {
  return loadDataAccessHistory();
}

export function recordDataAccessHistory(dataset: LocalDataset, metadata: DataAccessMetadata) {
  const existing = loadDataAccessHistory();
  const record: DataAccessHistoryRecord = {
    accessMetadataId: metadata.accessMetadataId,
    accessSourceId: metadata.accessSourceId,
    hash: metadata.hash,
    sourceType: metadata.sourceType,
    sourceLabel: metadata.sourceLabel,
    target: dataset.target,
    rows: metadata.returnedRowCount || dataset.rows.length,
    columns: dataset.headers.length,
    importedAt: metadata.importedAt,
    samplingMethod: metadata.samplingMethod,
  };
  const next = [record, ...existing.filter((row) => row.accessMetadataId !== record.accessMetadataId)].slice(0, 50);
  localStorage.setItem(DATASET_VERSIONS_KEY, JSON.stringify(next));
  return next;
}

/** @deprecated Use recordDataAccessHistory. */
export function recordDatasetVersion(dataset: LocalDataset, metadata: DataAccessMetadata) {
  return recordDataAccessHistory(dataset, metadata);
}

export function extractSqlTables(sql: string) {
  const matches = sql.matchAll(/\b(?:from|join)\s+([a-zA-Z0-9_.\[\]"]+)/gi);
  return Array.from(matches).map((match) => match[1].replace(/[\[\]"]/g, ""));
}

export function validateSql(sql: string) {
  const warnings: string[] = [];
  const normalized = sql.replace(/\s+/g, " ").trim().toLowerCase();
  if (!normalized) return ["No SQL query has been entered."];
  if (/select\s+\*/i.test(sql)) warnings.push("SELECT * detected. Select explicit columns for governance and reproducibility.");
  if (/\bfrom\b/i.test(sql) && !/\bwhere\b/i.test(sql)) warnings.push("No WHERE clause detected. Confirm this is not a large unrestricted scan.");
  if (/\bjoin\b/i.test(sql) && !/\bon\b/i.test(sql)) warnings.push("JOIN without ON detected. This may create a Cartesian join.");
  if (/\bcross\s+join\b/i.test(sql)) warnings.push("CROSS JOIN detected. Validate row-count expansion before import.");
  if (/(^|[^a-z])(date|user|group|order|select)([^a-z]|$)/i.test(sql)) warnings.push("Potential reserved words detected. Quote identifiers if required by the database.");
  if (/target|outcome|fraud|default|chargeoff|performance|label|future|post_/i.test(sql)) {
    warnings.push("Potential leakage column names detected. Review target timing and feature availability.");
  }
  return warnings;
}

function isMissing(value: unknown) {
  return value === null || value === undefined || String(value).trim() === "";
}

function toNumber(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function isDateLike(value: unknown) {
  if (isMissing(value)) return false;
  if (typeof value === "number" || /^-?\d+(?:\.\d+)?$/.test(String(value).trim())) return false;
  const text = String(value).trim();
  if (!/^(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})(?:[ T].*)?$/.test(text)) return false;
  const parsed = Date.parse(text);
  return Number.isFinite(parsed);
}

export function inferDataQuality(dataset: Pick<LocalDataset, "headers" | "rows" | "target">): DataQualitySummary {
  const { headers, rows, target } = dataset;
  const missing = headers.map((column) => {
    const count = rows.filter((row) => isMissing(row[column])).length;
    return { column, percent: rows.length ? count / rows.length : 0 };
  });
  const duplicateRows = rows.length - new Set(rows.map((row) => JSON.stringify(row))).size;
  const duplicateIdCandidates = headers.filter((column) => {
    if (!/id|key|number|acct|account|customer/i.test(column)) return false;
    const values = rows.map((row) => row[column]).filter((value) => !isMissing(value)).map(String);
    return values.length > new Set(values).size;
  });
  const constantColumns: string[] = [];
  const nearZeroVarianceColumns: string[] = [];
  const highCardinalityCategoricals: string[] = [];
  const unexpectedDatatypeColumns: string[] = [];
  const outlierPrevalence: { column: string; percent: number }[] = [];
  const dateRanges: { column: string; min: string; max: string }[] = [];

  for (const column of headers) {
    const values = rows.map((row) => row[column]).filter((value) => !isMissing(value));
    const unique = new Set(values.map(String));
    if (unique.size <= 1 && values.length) constantColumns.push(column);
    if (values.length && unique.size / values.length <= 0.01 && unique.size <= 5) nearZeroVarianceColumns.push(column);

    const numericValues = values.map(toNumber).filter((value): value is number => value !== null);
    const numericRate = values.length ? numericValues.length / values.length : 0;
    if (values.length && numericRate > 0.1 && numericRate < 0.8) unexpectedDatatypeColumns.push(column);
    if (values.length && numericRate < 0.8 && unique.size > Math.min(100, values.length * 0.5)) {
      highCardinalityCategoricals.push(column);
    }
    if (numericValues.length >= 10) {
      const sorted = [...numericValues].sort((a, b) => a - b);
      const q = (p: number) => sorted[Math.max(0, Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * p)))];
      const q1 = q(0.25);
      const q3 = q(0.75);
      const iqr = q3 - q1;
      const lower = q1 - 1.5 * iqr;
      const upper = q3 + 1.5 * iqr;
      const outliers = numericValues.filter((value) => value < lower || value > upper).length;
      const percent = outliers / numericValues.length;
      if (percent >= 0.01) outlierPrevalence.push({ column, percent });
    }
    const hasDateName = /(^|_)(date|datetime|timestamp|time|dt)($|_)/i.test(column);
    const dateValues = hasDateName ? values.filter(isDateLike).map((value) => new Date(String(value)).toISOString().slice(0, 10)) : [];
    if (dateValues.length >= Math.max(5, values.length * 0.8)) {
      dateRanges.push({ column, min: dateValues.sort()[0], max: dateValues.sort()[dateValues.length - 1] });
    }
  }

  const potentialLeakageColumns = headers.filter(
    (column) => column !== target && /target|outcome|future|post_|chargeoff|default|fraud|label|performance/i.test(column)
  );
  let classBalance: DataQualitySummary["classBalance"];
  if (target) {
    const targetValues = rows.map((row) => row[target]).filter((value) => !isMissing(value));
    const counts = new Map(targetValues.map(String).map((value) => [value, 0]));
    targetValues.forEach((value) => counts.set(String(value), (counts.get(String(value)) ?? 0) + 1));
    const total = targetValues.length;
    const ones = targetValues.filter((value) => Number(value) === 1).length;
    const majority = Math.max(...Array.from(counts.values()), 0);
    classBalance = {
      eventRate: total ? ones / total : null,
      majorityClassPercent: total ? majority / total : null,
    };
  }

  return {
    profileScope: "complete_browser_dataset",
    profiledRowCount: rows.length,
    registeredRowCount: rows.length,
    generatedAt: new Date().toISOString(),
    warnings: [],
    readinessStatus: "ready",
    rowCount: rows.length,
    columnCount: headers.length,
    duplicateRows,
    duplicateIdCandidates,
    constantColumns,
    nearZeroVarianceColumns,
    highCardinalityCategoricals,
    unexpectedDatatypeColumns,
    potentialLeakageColumns,
    outlierPrevalence: outlierPrevalence.sort((a, b) => b.percent - a.percent).slice(0, 20),
    classBalance,
    dateRanges,
    missing: missing.sort((a, b) => b.percent - a.percent),
    memoryEstimateMb: rows.length * Math.max(1, headers.length) * 16 / 1024 / 1024,
  };
}

export async function fetchFullDataQualityProfile(input: {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  target?: string | null;
  eventValue?: unknown;
  nonEventValue?: unknown;
  selectedColumns?: string[];
}): Promise<DataQualitySummary> {
  if (input.datasetIdentity.project_id !== input.projectId) {
    throw new Error("Quality-profile project identity does not match the active workflow.");
  }
  const apiBase =
    (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
    "http://127.0.0.1:8001/api";
  const response = await fetch(`${apiBase}/data/quality-profile`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: input.projectId,
      expected_dataset_id: input.datasetIdentity.dataset_id,
      expected_dataset_version_id: input.datasetIdentity.dataset_version_id,
      dataset_version: input.datasetIdentity.dataset_version_id,
      target: input.target,
      event_value: input.eventValue,
      non_event_value: input.nonEventValue,
      selected_columns: input.selectedColumns ?? [],
    }),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) throw new Error(payload?.detail ?? "Full-dataset quality profiling is unavailable.");
  const canonical = assertExactDatasetIdentity(
    input.datasetIdentity,
    payload,
    "Full-dataset quality profile response",
  );
  return {
    projectId: canonical.project_id,
    datasetId: canonical.dataset_id,
    datasetVersionId: canonical.dataset_version_id,
    profileScope: payload.profileScope,
    profiledRowCount: payload.profiledRowCount,
    registeredRowCount: payload.registeredRowCount,
    generatedAt: payload.generatedAt,
    datasetVersion: canonical.dataset_version_id,
    datasetHash: payload.datasetHash,
    rowCount: payload.registeredRowCount,
    columnCount: payload.columnCount,
    duplicateRows: payload.duplicateRows,
    duplicateIdCandidates: payload.duplicateIdCandidates ?? [],
    constantColumns: payload.constantColumns ?? [],
    nearZeroVarianceColumns: payload.nearZeroVarianceColumns ?? [],
    highCardinalityCategoricals: payload.highCardinalityCategoricalColumns ?? [],
    unexpectedDatatypeColumns: payload.unexpectedDatatypeColumns ?? [],
    potentialLeakageColumns: payload.potentialLeakageCandidates ?? [],
    outlierPrevalence: payload.outlierPrevalence ?? [],
    classBalance: payload.targetHealth?.kind === "classification" ? {
      eventRate: payload.targetHealth.eventRate ?? null,
      majorityClassPercent: Array.isArray(payload.targetHealth.classDistribution)
        ? Math.max(...payload.targetHealth.classDistribution.map((row: { percent?: number }) => Number(row.percent) || 0), 0)
        : null,
    } : undefined,
    classDistribution: Array.isArray(payload.targetHealth?.classDistribution) ? payload.targetHealth.classDistribution : undefined,
    targetEventValue: payload.targetHealth?.eventValue,
    dateRanges: payload.dateRanges ?? [],
    missing: (payload.missingness ?? []).map((row: { column: string; percent: number }) => ({ column: row.column, percent: row.percent })),
    memoryEstimateMb: payload.memoryEstimateMb ?? 0,
    warnings: payload.warnings ?? [],
    readinessStatus: payload.readinessStatus ?? "needs_review",
  };
}

export function buildDataAccessMetadata(input: {
  dataset: Pick<LocalDataset, "headers" | "rows" | "target">;
  sourceType: DataSourceType;
  sourceLabel: string;
  fileName?: string;
  fileType?: string;
  connectionName?: string;
  provider?: string;
  database?: string;
  schema?: string;
  sqlQuery?: string;
  cloudProvider?: string;
  cloudPath?: string;
  pythonCode?: string;
  samplingMethod: SamplingMethod;
  samplingDetail: string;
  rowCountOverride?: number;
}) {
  const returnedRowCount = input.rowCountOverride ?? input.dataset.rows.length;
  const hash = hashDatasetPreview(input.dataset.headers, input.dataset.rows, returnedRowCount);
  const accessSourceId = `${input.sourceType}-${hash.slice(0, 8)}`;
  const accessMetadataId = `${compactTimestamp()}-${hash.slice(0, 8)}`;
  const tablesReferenced = input.sqlQuery ? extractSqlTables(input.sqlQuery) : [];
  const validationWarnings = input.sqlQuery ? validateSql(input.sqlQuery) : [];
  const lineage = [
    input.sourceLabel,
    ...(input.database ? [`Database: ${input.database}`] : []),
    ...(input.schema ? [`Schema: ${input.schema}`] : []),
    ...(tablesReferenced.length ? [`Tables: ${tablesReferenced.join(", ")}`] : []),
    ...(input.samplingMethod !== "full" ? [`Sampled: ${input.samplingMethod} ${input.samplingDetail}`] : ["Full dataset"]),
    "Imported into modeling project",
  ];
  const metadata: DataAccessMetadata = {
    accessMetadataId,
    accessSourceId,
    hash,
    sourceType: input.sourceType,
    sourceLabel: input.sourceLabel,
    fileName: input.fileName,
    fileType: input.fileType,
    connectionName: input.connectionName,
    provider: input.provider,
    database: input.database,
    schema: input.schema,
    sqlQuery: input.sqlQuery,
    cloudProvider: input.cloudProvider,
    cloudPath: input.cloudPath,
    pythonCode: input.pythonCode,
    tablesReferenced,
    importedAt: new Date().toISOString(),
    importedBy: "Local user",
    returnedRowCount,
    returnedColumns: input.dataset.headers,
    samplingMethod: input.samplingMethod,
    samplingDetail: input.samplingDetail,
    lineage,
    validationWarnings,
    generatedPython: generateDataAccessPython({
      sourceType: input.sourceType,
      sourceLabel: input.sourceLabel,
      fileName: input.fileName,
      provider: input.provider,
      connectionName: input.connectionName,
      sqlQuery: input.sqlQuery,
      cloudProvider: input.cloudProvider,
      cloudPath: input.cloudPath,
      pythonCode: input.pythonCode,
    }),
  };
  return metadata;
}

export function generateDataAccessPython(input: {
  sourceType: DataSourceType;
  sourceLabel?: string;
  fileName?: string;
  provider?: string;
  connectionName?: string;
  sqlQuery?: string;
  cloudProvider?: string;
  cloudPath?: string;
  pythonCode?: string;
}) {
  if (input.sourceType === "sql") {
    return `import pandas as pd
from sqlalchemy import create_engine

# Credentials should come from environment variables or a secrets manager.
engine = create_engine("DATABASE_URL_FOR_${(input.provider || "provider").replace(/\W+/g, "_").toUpperCase()}")

sql = r"""
${input.sqlQuery || "-- paste governed SQL query here"}
"""

df = pd.read_sql(sql, engine)`;
  }
  if (input.sourceType === "cloud") {
    return `import pandas as pd

# Configure ${input.cloudProvider || "cloud"} credentials outside the notebook.
path = "${input.cloudPath || "cloud://path/to/data"}"
df = pd.read_csv(path)`;
  }
  if (input.sourceType === "python") {
    return input.pythonCode || "import pandas as pd\n\n# User-provided loader must assign the final dataframe to df.";
  }
  return `import pandas as pd
from pathlib import Path

path = Path("${input.fileName || "TRAIN.csv"}")
df = pd.read_csv(path)`;
}

export function queryTemplates() {
  return [
    { name: "Training dataset", sql: "SELECT customer_id, observation_date, target, feature_1, feature_2\nFROM schema.training_population\nWHERE observation_date BETWEEN DATE '2024-01-01' AND DATE '2024-12-31';" },
    { name: "OOT sample", sql: "SELECT *\nFROM schema.scoring_population\nWHERE observation_date BETWEEN DATE '2025-01-01' AND DATE '2025-03-31';" },
    { name: "Random sample", sql: "SELECT *\nFROM schema.population\nWHERE random() < 0.10;" },
    { name: "Monthly snapshot", sql: "SELECT date_trunc('month', observation_date) AS month, COUNT(*) AS records\nFROM schema.population\nGROUP BY 1\nORDER BY 1;" },
    { name: "Population counts", sql: "SELECT COUNT(*) AS records, COUNT(DISTINCT customer_id) AS customers\nFROM schema.population;" },
    { name: "Target event rate", sql: "SELECT target, COUNT(*) AS records, COUNT(*) * 1.0 / SUM(COUNT(*)) OVER () AS pct\nFROM schema.population\nGROUP BY target;" },
    { name: "Missing value report", sql: "SELECT COUNT(*) AS records,\nSUM(CASE WHEN feature_1 IS NULL THEN 1 ELSE 0 END) AS feature_1_missing\nFROM schema.population;" },
    { name: "Duplicate detection", sql: "SELECT customer_id, observation_date, COUNT(*) AS records\nFROM schema.population\nGROUP BY customer_id, observation_date\nHAVING COUNT(*) > 1;" },
  ];
}

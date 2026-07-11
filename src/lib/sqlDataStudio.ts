import { DATASET_API_BASE, type DatasetSummary } from "./datasetLibrary";

export type SqlDatasetRef = {
  datasetId: string;
  versionId: string;
  alias: string;
};

export type SqlResultColumn = {
  name: string;
  type: string;
};

export type SqlSchemaProfile = {
  name: string;
  type: string;
  missingCount: number;
  distinctCount: number;
  min?: number;
  max?: number;
  mean?: number;
  sampleValues?: string[];
};

export type SqlPreviewResult = {
  ok: boolean;
  status: "success" | "blocked" | "error" | string;
  rowCount: number;
  returnedRows: number;
  columns: SqlResultColumn[];
  rows: Record<string, unknown>[];
  runtimeMs: number;
  warnings: string[];
  error?: string;
  schemaProfile?: SqlSchemaProfile[];
};

export type SavedSqlQuery = {
  queryId: string;
  name: string;
  description?: string;
  sql: string;
  sourceType: string;
  datasetRefs: SqlDatasetRef[];
  createdAt: string;
  updatedAt: string;
  createdBy: string;
  linkedProjectId?: string;
  tags?: string[];
};

async function sqlFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers ?? {}),
    },
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json().catch(() => null) : null;
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.detail ?? payload?.error ?? `SQL Data Studio request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

export async function validateSql(input: { sql: string; sourceType?: string; datasetRefs: SqlDatasetRef[]; limit?: number }) {
  return sqlFetch<{ ok: boolean; status: string; warnings: string[]; error?: string }>("/sql-studio/validate", {
    method: "POST",
    body: JSON.stringify({ sourceType: "dataset_library_preview", limit: 100, ...input }),
  });
}

export async function runSqlPreview(input: { sql: string; sourceType?: string; datasetRefs: SqlDatasetRef[]; limit?: number }) {
  return sqlFetch<SqlPreviewResult>("/sql-studio/run-preview", {
    method: "POST",
    body: JSON.stringify({ sourceType: "dataset_library_preview", limit: 100, ...input }),
  });
}

export async function listSavedSqlQueries() {
  return sqlFetch<{ ok: true; queries: SavedSqlQuery[] }>("/sql-studio/queries");
}

export async function saveSqlQuery(input: {
  name: string;
  description?: string;
  sql: string;
  sourceType?: string;
  datasetRefs: SqlDatasetRef[];
  linkedProjectId?: string;
  tags?: string[];
}) {
  return sqlFetch<{ ok: true; query: SavedSqlQuery }>("/sql-studio/queries", {
    method: "POST",
    body: JSON.stringify({ sourceType: "dataset_library_preview", ...input }),
  });
}

export async function deleteSqlQuery(queryId: string) {
  return sqlFetch<{ ok: true; deleted: boolean }>(`/sql-studio/queries/${encodeURIComponent(queryId)}`, { method: "DELETE" });
}

export async function registerSqlResult(input: {
  queryName: string;
  sql: string;
  sourceType?: string;
  datasetRefs: SqlDatasetRef[];
  resultRows: Record<string, unknown>[];
  resultColumns: SqlResultColumn[];
  description?: string;
  linkedProjectId?: string;
  tags?: string[];
}) {
  return sqlFetch<{ ok: true; dataset: DatasetSummary; lineage: Record<string, unknown> }>("/sql-studio/register-result", {
    method: "POST",
    body: JSON.stringify({ sourceType: "dataset_library_preview", ...input }),
  });
}

export async function exportSqlResultExcel(input: {
  queryName: string;
  sql: string;
  rows: Record<string, unknown>[];
  columns: SqlResultColumn[];
  schemaProfile: SqlSchemaProfile[];
  datasetRefs: SqlDatasetRef[];
  warnings: string[];
  lineage?: Record<string, unknown>;
}) {
  const response = await fetch(`${DATASET_API_BASE}/sql-studio/export/excel`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? payload?.error ?? `SQL Data Studio export failed with HTTP ${response.status}.`);
  }
  return response.blob();
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function safeSqlAlias(dataset: DatasetSummary) {
  const name = `${dataset.name || dataset.datasetId}`.toUpperCase();
  if (/REG.*TRAIN|TRAIN.*REG/.test(name)) return "REG_TRAIN";
  if (/REG.*TEST|TEST.*REG/.test(name)) return "REG_TEST";
  if (/REG.*OOT|OOT.*REG/.test(name)) return "REG_OOT";
  if (/CLASS.*TRAIN|TRAIN.*CLASS|FRAUD.*TRAIN/.test(name)) return "CLASS_TRAIN";
  if (/CLASS.*TEST|TEST.*CLASS|FRAUD.*TEST/.test(name)) return "CLASS_TEST";
  if (/CLASS.*OOT|OOT.*CLASS|FRAUD.*OOT/.test(name)) return "CLASS_OOT";
  const safe = `${dataset.name || dataset.datasetId}`
    .replace(/[^a-zA-Z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
  return /^[0-9]/.test(safe) ? `t_${safe}` : safe || "atlas_dataset";
}


import { DATASET_API_BASE } from "./datasetLibrary";

async function analyticsFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS analytics request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

export type AtlasAnalyticsInsight = {
  insightId: string;
  title: string;
  summary: string;
  datasetId: string;
  versionId: string;
  projectId?: string | null;
  businessQuestion?: string;
  analysisType: string;
  createdByUserId: string;
  createdAt: string;
  evidence: {
    metrics?: Record<string, unknown>;
    chartType?: string;
    columnsUsed?: string[];
    filters?: Record<string, unknown>;
  };
};

export type AnalyticsSqlRunResult = {
  ok?: boolean;
  status: "success" | "error";
  columns: string[];
  rows: Array<Record<string, unknown>>;
  rowCount: number;
  runtimeMs: number;
  error?: string;
};

export type AnalyticsExportFormat = "excel" | "word" | "powerpoint";

export type AnalyticsExportPayload = {
  exportTitle?: string;
  datasetName?: string;
  datasetId?: string;
  versionId?: string;
  businessQuestion?: string;
  cleanedQuestion?: string;
  analysisPlan?: string[];
  targetVariable?: string;
  previewRowCount?: number;
  pivotConfig?: Record<string, unknown>;
  pivotRows?: Array<Record<string, unknown>>;
  pivotReadout?: string;
  sqlResult?: Record<string, unknown> | null;
  sasResult?: Record<string, unknown> | null;
  pythonResult?: Record<string, unknown> | null;
  rResult?: Record<string, unknown> | null;
  generatedPython?: string;
  generatedSql?: string;
  generatedR?: string;
  generatedSas?: string;
  userEditedPython?: string;
  userEditedSql?: string;
  userEditedR?: string;
  userEditedSas?: string;
  savedInsight?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  linkedProjectId?: string;
  createdAt?: string;
  createdBy?: string;
  limitations?: string;
};

export type AnalyticsResultExportPayload = {
  resultType:
    | "column_explorer"
    | "target_relationship"
    | "group_comparison"
    | "data_quality"
    | "pivot"
    | "sql_result"
    | "sas_compatible_result"
    | "r_result"
    | "python_result";
  exportTitle: string;
  datasetName: string;
  versionId: string;
  businessQuestion?: string;
  resultPayload: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  createdAt?: string;
};

export async function listAnalyticsInsights(filters: { datasetId?: string; projectId?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.datasetId) params.set("datasetId", filters.datasetId);
  if (filters.projectId) params.set("projectId", filters.projectId);
  const query = params.toString();
  return analyticsFetch<{ ok: true; insights: AtlasAnalyticsInsight[] }>(`/analytics/insights${query ? `?${query}` : ""}`);
}

export async function saveAnalyticsInsight(input: {
  title: string;
  summary: string;
  datasetId: string;
  versionId: string;
  projectId?: string;
  businessQuestion?: string;
  analysisType: string;
  evidence?: AtlasAnalyticsInsight["evidence"];
}) {
  const payload = await analyticsFetch<{ ok: true; insight: AtlasAnalyticsInsight }>("/analytics/insights", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.insight;
}

export async function deleteAnalyticsInsight(insightId: string) {
  return analyticsFetch<{ ok: true; deleted: string }>(`/analytics/insights/${insightId}`, { method: "DELETE" });
}

export async function auditAnalyticsRun(input: { datasetId?: string; versionId?: string; analysisType: string }) {
  return analyticsFetch<{ ok: true }>("/analytics/audit-run", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function runAnalyticsPreviewSql(input: {
  sql: string;
  datasetName: string;
  versionId: string;
  previewRows: Array<Record<string, unknown>>;
  secondaryDatasetName?: string;
  secondaryPreviewRows?: Array<Record<string, unknown>>;
}) {
  const response = await fetch(`${DATASET_API_BASE}/analytics/sql/run`, {
    credentials: "include",
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload) {
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS SQL preview failed with HTTP ${response.status}.`);
  }
  return payload as AnalyticsSqlRunResult;
}

export async function exportAnalyticsPackage(format: AnalyticsExportFormat, payload: AnalyticsExportPayload) {
  const response = await fetch(`${DATASET_API_BASE}/analytics/export/${format}`, {
    credentials: "include",
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorPayload = await response.json().catch(() => null);
    throw new Error(errorPayload?.detail ?? errorPayload?.error ?? `ATLAS ${format} export failed with HTTP ${response.status}.`);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  return {
    blob,
    filename: filenameFromDisposition(disposition) ?? fallbackExportFilename(format, payload.datasetName || payload.datasetId || "atlas-analytics"),
  };
}

export async function exportAnalyticsResultExcel(payload: AnalyticsResultExportPayload) {
  const response = await fetch(`${DATASET_API_BASE}/analytics/export/result/excel`, {
    credentials: "include",
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorPayload = await response.json().catch(() => null);
    throw new Error(errorPayload?.detail ?? errorPayload?.error ?? `ATLAS result Excel export failed with HTTP ${response.status}.`);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  return {
    blob,
    filename: filenameFromDisposition(disposition) ?? fallbackExportFilename("excel", payload.exportTitle || payload.datasetName || "atlas-result"),
  };
}

function filenameFromDisposition(disposition: string) {
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  return match?.[1];
}

function fallbackExportFilename(format: AnalyticsExportFormat, datasetName: string) {
  const extension = format === "excel" ? "xlsx" : format === "word" ? "docx" : "pptx";
  const safe = datasetName.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "atlas-analytics";
  return `${safe}-analytics-export.${extension}`;
}

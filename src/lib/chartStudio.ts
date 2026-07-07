import { DATASET_API_BASE } from "./datasetLibrary";
import type { AtlasAnalyticsInsight } from "./analyticsWorkbench";

async function chartFetch<T>(path: string, init?: RequestInit): Promise<T> {
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
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS chart request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

export type ChartStudioRoleAssignments = Record<string, string | number | boolean | string[] | null | undefined>;

export type ChartStudioExportPayload = {
  chartTitle: string;
  chartType: string;
  datasetName: string;
  datasetId: string;
  versionId: string;
  businessQuestion?: string;
  roles: ChartStudioRoleAssignments;
  chartData: Array<Record<string, unknown>>;
  interpretation: string;
  generatedPython: string;
  generatedSql: string;
  generatedR: string;
  generatedSas: string;
  metadata?: Record<string, unknown>;
};

export type ChartStudioInsightInput = {
  title: string;
  summary: string;
  datasetId: string;
  datasetName: string;
  versionId: string;
  projectId?: string;
  businessQuestion?: string;
  chartType: string;
  roles: ChartStudioRoleAssignments;
  chartData: Array<Record<string, unknown>>;
  interpretation: string;
  generatedPython: string;
  generatedSql: string;
  generatedR: string;
  generatedSas: string;
  linkedProjectId?: string;
  metadata?: Record<string, unknown>;
};

export async function listChartInsights(filters: { datasetId?: string; projectId?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.datasetId) params.set("datasetId", filters.datasetId);
  if (filters.projectId) params.set("projectId", filters.projectId);
  const query = params.toString();
  return chartFetch<{ ok: true; insights: AtlasAnalyticsInsight[] }>(`/charts/insights${query ? `?${query}` : ""}`);
}

export async function saveChartInsight(input: ChartStudioInsightInput) {
  const payload = await chartFetch<{ ok: true; insight: AtlasAnalyticsInsight }>("/charts/insights", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.insight;
}

export async function exportChartDataExcel(payload: ChartStudioExportPayload) {
  const response = await fetch(`${DATASET_API_BASE}/charts/export/excel`, {
    credentials: "include",
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorPayload = await response.json().catch(() => null);
    throw new Error(errorPayload?.detail ?? errorPayload?.error ?? `ATLAS chart Excel export failed with HTTP ${response.status}.`);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  return {
    blob,
    filename: filenameFromDisposition(disposition) ?? `${safeFilename(payload.chartTitle || "atlas-chart")}-chart-data.xlsx`,
  };
}

function filenameFromDisposition(disposition: string) {
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  return match?.[1];
}

function safeFilename(value: string) {
  return value.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "atlas-chart";
}

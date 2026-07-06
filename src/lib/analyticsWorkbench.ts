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

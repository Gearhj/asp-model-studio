// ATLAS Persistent Scoring Runs -- browser client for /api/scoring-runs.
//
// This is the ONLY place frontend code should read/write durable scoring-run
// state. Every call is authorized server-side (authorize_modeling_scope on
// every scoring_run_service entry point); this layer adds no authorization
// of its own.
export type ScoringPartition = "train" | "test" | "oot";
export type ScoringRunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type ScoringRunSummary = {
  scoringRunId: string;
  projectId: string | null;
  userId: string | null;
  datasetId: string | null;
  datasetVersionId: string | null;
  datasetIdentity: string | null;
  partition: ScoringPartition;
  modelId: string | null;
  modelVersion: string | null;
  problemType: "classification" | "regression" | null;
  target: string | null;
  status: ScoringRunStatus;
  createdAt: string;
  completedAt: string | null;
  rowCount: number | null;
  predictionColumn: string | null;
  probabilityColumn: string | null;
  residualColumn: string | null;
  checksum: string | null;
  archivedAt: string | null;
  errorMessage?: string | null;
  metrics?: { metrics?: Record<string, number | null>; scoreSummary?: Record<string, number | null>; adjustedScoreSummary?: Record<string, number | null>; lift?: unknown };
  registrationStatus?: "not_registered" | "registered";
  outputDatasetId?: string | null;
  outputDatasetVersionId?: string | null;
  /** Durable Model Registry, Phase F: the real registry identity, when this run
   *  was scored against a model saved through the registry. null for runs that
   *  predate the registry or scored a non-final named artifact. */
  modelVersionId?: string | null;
};

const API_BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : `Scoring run request failed (${response.status}): ${path}`);
  }
  return payload as T;
}

async function postJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method: "POST", credentials: "include" });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : `Scoring run request failed (${response.status}): ${path}`);
  }
  return payload as T;
}

export type ListScoringRunsFilters = {
  datasetId?: string;
  datasetVersionId?: string;
  modelId?: string;
  modelVersionId?: string;
  target?: string;
  partition?: ScoringPartition;
  status?: ScoringRunStatus;
  problemType?: "classification" | "regression";
  createdAfter?: string;
  createdBefore?: string;
  includeArchived?: boolean;
  limit?: number;
};

export async function listScoringRuns(projectId: string, filters: ListScoringRunsFilters = {}): Promise<ScoringRunSummary[]> {
  const params = new URLSearchParams({ projectId });
  if (filters.datasetId) params.set("datasetId", filters.datasetId);
  if (filters.datasetVersionId) params.set("datasetVersionId", filters.datasetVersionId);
  if (filters.modelId) params.set("modelId", filters.modelId);
  if (filters.modelVersionId) params.set("modelVersionId", filters.modelVersionId);
  if (filters.target) params.set("target", filters.target);
  if (filters.partition) params.set("partition", filters.partition);
  if (filters.status) params.set("status", filters.status);
  if (filters.problemType) params.set("problemType", filters.problemType);
  if (filters.createdAfter) params.set("createdAfter", filters.createdAfter);
  if (filters.createdBefore) params.set("createdBefore", filters.createdBefore);
  if (filters.includeArchived) params.set("includeArchived", "true");
  if (filters.limit) params.set("limit", String(filters.limit));
  const payload = await getJson<{ scoringRuns: ScoringRunSummary[] }>(`/scoring-runs?${params.toString()}`);
  return payload.scoringRuns;
}

export async function getScoringRun(scoringRunId: string): Promise<ScoringRunSummary> {
  const payload = await getJson<{ scoringRun: ScoringRunSummary }>(`/scoring-runs/${encodeURIComponent(scoringRunId)}`);
  return payload.scoringRun;
}

export async function getScoringRunMetrics(scoringRunId: string): Promise<{ metrics: Record<string, unknown> }> {
  return getJson(`/scoring-runs/${encodeURIComponent(scoringRunId)}/metrics`);
}

export async function getScoringRunDiagnostics(
  scoringRunId: string
): Promise<{ scoringDiagnostics: Record<string, unknown>; psi: Record<string, unknown>; vsi: Record<string, unknown> }> {
  return getJson(`/scoring-runs/${encodeURIComponent(scoringRunId)}/diagnostics`);
}

export async function getScoringRunLineage(scoringRunId: string): Promise<Record<string, unknown>> {
  return getJson(`/scoring-runs/${encodeURIComponent(scoringRunId)}/lineage`);
}

export async function getScoringRunRows(
  scoringRunId: string,
  limit = 100
): Promise<{ columns: string[]; rows: Record<string, unknown>[]; totalRowCount: number; truncated: boolean }> {
  return getJson(`/scoring-runs/${encodeURIComponent(scoringRunId)}/rows?limit=${limit}`);
}

export async function cancelScoringRun(scoringRunId: string): Promise<ScoringRunSummary> {
  const payload = await postJson<{ scoringRun: ScoringRunSummary }>(`/scoring-runs/${encodeURIComponent(scoringRunId)}/cancel`);
  return payload.scoringRun;
}

export async function archiveScoringRun(scoringRunId: string): Promise<ScoringRunSummary> {
  const payload = await postJson<{ scoringRun: ScoringRunSummary }>(`/scoring-runs/${encodeURIComponent(scoringRunId)}/archive`);
  return payload.scoringRun;
}

export async function compareScoringRuns(scoringRunIds: string[]): Promise<{ runs: Record<string, unknown>[] }> {
  return getJson(`/scoring-runs/compare?ids=${scoringRunIds.map(encodeURIComponent).join(",")}`);
}

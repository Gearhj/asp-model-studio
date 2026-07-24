// ATLAS Enterprise Analytical Data Plane -- browser client for the server-side
// query plane (POST /api/analytics/queries and friends). This is now the
// PREFERRED path for any Visual Intelligence aggregate/summary/diagnostic
// request -- see dataAccessLayer.ts's updated priority order (Phase N):
// server aggregate > server sample > cached result > bounded browser
// calculation > DuckDB-Wasm (local extracts only) > honest unsupported state.
import type { VisualDatasetReference } from "./types";

const API_BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

export type AnalyticalOperation =
  | "schema" | "row_count" | "column_profile" | "histogram" | "quantiles"
  | "grouped_summary" | "category_frequency" | "scatter_sample" | "hexbin"
  | "threshold_curve" | "confusion_matrix_at_threshold" | "regression_diagnostics"
  | "residual_distribution" | "qq_points" | "error_by_target_band"
  | "prediction_distribution" | "psi" | "vsi" | "top_outliers" | "bounded_rows";

export type AnalyticalQueryInput = {
  projectId: string;
  datasetId?: string;
  versionId?: string;
  sourceType?: "workspace" | "registered" | "scoring-session" | "evaluation-result" | "interpretation-result" | "derived" | "server-aggregate";
  partition?: "train" | "test" | "oot";
  modelId?: string;
  scoringRunId?: string;
  operation: AnalyticalOperation;
  selectedColumns?: string[];
  filters?: Array<{ column: string; op: string; value?: unknown }>;
  groupBy?: string[];
  aggregations?: Record<string, unknown>;
  binning?: number;
  quantiles?: number[];
  limit?: number;
  /** Wide-table schema browsing only (operation="schema") -- server-side pagination/
   *  search/type-filter, never an eagerly-fetched full column list. */
  offset?: number;
  search?: string;
  dtypeFilter?: string;
  approximationPolicy?: "exact_required" | "approximate_preferred" | "approximate_allowed";
  timeoutSeconds?: number;
};

export type AnalyticalQueryResponse = {
  queryId: string;
  status: "queued" | "planning" | "running" | "completed" | "failed" | "cancelled" | "timed_out" | "rejected";
  exact: boolean;
  approximate: boolean;
  sampled: boolean;
  sampleMethod: string;
  sourceRowCount: number | null;
  rowsScanned: number | null;
  resultRowCount: number | null;
  executionEngine: string | null;
  pushdownApplied: boolean;
  cacheStatus: "hit" | "miss" | "not_cacheable";
  durationMs: number | null;
  warnings: string[];
  result: unknown;
  error?: string | null;
};

/** ClientQueryState -- the states a UI must be able to distinguish (Phase N
 *  requirement): "no data" vs "engine loading" vs "query running" vs "query
 *  failed" vs "unsupported operation" are all different situations, not one
 *  generic loading spinner. */
export type ClientQueryState =
  | "idle" | "requesting-metadata" | "planning" | "queued" | "running"
  | "preparing-local-analytics" | "loading-duckdb-engine" | "calculating"
  | "completed" | "sampled" | "approximate" | "cancelled" | "timed-out"
  | "unavailable" | "failed";

export function deriveClientState(response: AnalyticalQueryResponse | null, error: string | null): ClientQueryState {
  if (error) return "failed";
  if (!response) return "idle";
  if (response.status === "queued" || response.status === "planning") return "planning";
  if (response.status === "running") return "running";
  if (response.status === "cancelled") return "cancelled";
  if (response.status === "timed_out") return "timed-out";
  if (response.status === "rejected" || response.status === "failed") return "failed";
  if (response.sampled) return "sampled";
  if (response.approximate) return "approximate";
  return "completed";
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : `Analytical query failed (${response.status}).`);
  }
  return payload as T;
}

/** Submit an analytical query to the server-side data plane. Fast operations
 *  return status="completed" inline; heavy operations return status="queued"
 *  with a queryId the caller can poll via pollQueryResult(). */
export async function submitAnalyticalQuery(input: AnalyticalQueryInput): Promise<AnalyticalQueryResponse> {
  return postJson<AnalyticalQueryResponse>("/analytics/queries", input);
}

export async function cancelAnalyticalQuery(queryId: string): Promise<void> {
  await fetch(`${API_BASE}/analytics/queries/${encodeURIComponent(queryId)}/cancel`, { method: "POST", credentials: "include" });
}

export async function pollQueryResult(queryId: string, { intervalMs = 500, timeoutMs = 30_000 }: { intervalMs?: number; timeoutMs?: number } = {}): Promise<AnalyticalQueryResponse> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const response = await fetch(`${API_BASE}/analytics/queries/${encodeURIComponent(queryId)}/result`, { credentials: "include" });
    const payload = await response.json();
    if (payload.status && !["queued", "planning", "running"].includes(payload.status)) {
      return payload as AnalyticalQueryResponse;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("Polling for analytical query result timed out client-side.");
}

/** Convenience: submit and, if queued, transparently poll to completion. */
export async function runAnalyticalQuery(input: AnalyticalQueryInput): Promise<AnalyticalQueryResponse> {
  const initial = await submitAnalyticalQuery(input);
  if (initial.status === "queued") {
    return pollQueryResult(initial.queryId);
  }
  return initial;
}

export function toDatasetReferenceFields(reference: VisualDatasetReference): Pick<AnalyticalQueryInput, "projectId" | "datasetId" | "versionId" | "sourceType" | "partition" | "modelId" | "scoringRunId"> {
  return {
    projectId: reference.projectId,
    datasetId: reference.datasetId,
    versionId: reference.versionId,
    sourceType: reference.sourceType,
    partition: reference.partition,
    modelId: reference.modelId,
    scoringRunId: reference.scoringRunId,
  };
}

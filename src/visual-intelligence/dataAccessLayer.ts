// ATLAS Visual Intelligence Foundation -- browser-side Data Access Layer.
//
// This is the ONLY place Visual Intelligence components are allowed to decide
// "where does this chart's data come from." Components must never call
// duckdbService.ts or a raw fetch() directly for chart data -- they call one
// of the functions below, which:
//   1. resolves a strategy (existing browser data / backend aggregate /
//      scoring payload / registered-asset preview / server aggregation /
//      DuckDB-Wasm / sampling / honest refusal),
//   2. always goes through backend-authorized endpoints (authorize_modeling_scope
//      on the server; this layer adds no authorization of its own and cannot
//      bypass it -- every fetch below includes credentials so the existing
//      session-cookie authorization always applies),
//   3. attaches VisualDataSourceMeta so the UI can render an honest
//      sampling/freshness/durability notice.
import type { VisualDataResult, VisualDatasetReference, VisualDataSourceMeta } from "./types";
import { chooseRenderStrategy, reservoirSample } from "./largeDataPolicy";
import { registerTable, runQuery, clearProjectTables } from "./duckdb/duckdbService";
import { submitAnalyticalQuery, toDatasetReferenceFields } from "./analyticalQueryClient";
import { getScoringRunRows } from "../scoring-runs/scoringRunClient";
import { requestScopedTrainingHistory } from "../lib/scopedTrainingHistory";

const API_BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  if (!response.ok) throw new Error(`Visual Intelligence data request failed (${response.status}): ${path}`);
  return response.json() as Promise<T>;
}

/**
 * Source 1/5: workspace dataset rows, bounded server-side (GET /api/data/get_sample
 * already caps at max_rows and is authorized by authorize_modeling_scope). Used by
 * the Interactive Distribution Explorer.
 */
export async function fetchWorkspaceRows(
  reference: VisualDatasetReference,
  options: { maxRows?: number } = {}
): Promise<VisualDataResult<Record<string, unknown>>> {
  const start = performance.now();
  const maxRows = options.maxRows ?? 5000;
  if (!reference.datasetId || !reference.versionId) {
    throw new Error("Visual Intelligence workspace rows require an exact registered dataset version.");
  }
  const query = new URLSearchParams({
    project_id: reference.projectId,
    expected_dataset_id: reference.datasetId,
    expected_dataset_version_id: reference.versionId,
    max_rows: String(Math.min(Math.max(Math.trunc(maxRows), 1), 5000)),
  });
  const payload = await getJson<{
    ok: boolean;
    project_id: string;
    dataset_id: string;
    dataset_version_id: string;
    headers: string[];
    rows: Record<string, unknown>[];
    target: string | null;
    registered_row_count?: number;
    target_values_included: boolean;
    source_checksum?: string;
    scope?: Record<string, unknown>;
  }>(
    `/data/get_sample?${query.toString()}`
  );
  const target = payload.target ?? reference.target;
  const scope = payload.scope ?? {};
  const exact = payload.project_id === reference.projectId
    && payload.dataset_id === reference.datasetId
    && payload.dataset_version_id === reference.versionId;
  const rows = payload.rows.map((row) => {
    const safe = { ...row };
    if (target) delete safe[target];
    return safe;
  });
  if (!exact || payload.target_values_included !== false || scope.target_values_included !== false) {
    throw new Error("Visual Intelligence refused a workspace sample without exact target-free scope metadata.");
  }
  if (target && payload.rows.some((row) => Object.prototype.hasOwnProperty.call(row, target))) {
    throw new Error("Visual Intelligence refused a workspace sample containing target values.");
  }
  const totalSourceRows = Number(payload.registered_row_count ?? scope.population_count ?? rows.length);
  const meta: VisualDataSourceMeta = {
    source: "workspace",
    rowsAvailable: rows.length,
    totalSourceRows: Number.isFinite(totalSourceRows) ? totalSourceRows : rows.length,
    sampled: Number.isFinite(totalSourceRows)
      ? rows.length < totalSourceRows
      : rows.length >= maxRows,
    freshAsOf: new Date().toISOString(),
    ephemeral: true, // workspace data is DATASTORE-resident, not a registered durable asset
    aggregationMethod: "none",
    queryDurationMs: performance.now() - start,
    analyticalScope:
      scope.analytical_scope === "development_population_predictors_only"
      || scope.analytical_scope === "full_governed_population_predictors_only"
        ? scope.analytical_scope
        : undefined,
    populationId: typeof scope.population_id === "string" ? scope.population_id : undefined,
    partitionId: typeof scope.partition_id === "string" ? scope.partition_id : undefined,
    partitionRevision: Number.isSafeInteger(Number(scope.partition_revision))
      ? Number(scope.partition_revision)
      : undefined,
    holdoutExcluded: typeof scope.holdout_excluded === "boolean" ? scope.holdout_excluded : undefined,
    targetValuesIncluded: false,
    sourceChecksum: typeof payload.source_checksum === "string" ? payload.source_checksum : undefined,
  };
  return { reference: { ...reference, sourceType: "workspace", target }, meta, rows };
}

/**
 * Source 2/3: the most recent training run's raw actual/prediction arrays
 * (GET /api/train/last). This is the durable-enough-for-a-session evaluation
 * result used by the Classification Decision Explorer and Regression
 * Diagnostic Explorer for the TRAIN partition -- it survives page navigation
 * within the project (backend-held), unlike Step10_Scoring's TEST/OOT state,
 * which is genuine ephemeral React component state with no backend counterpart
 * (Known Constraint #1/#2 -- see docs/visual-intelligence/ARCHITECTURE_DECISION_RECORD.md).
 */
export async function fetchTrainingEvaluationResult(
  reference: VisualDatasetReference,
  modelKey: string
): Promise<VisualDataResult<{ actual: number; prediction: number }> & { problemType: "classification" | "regression" | null; modelName: string | null }> {
  const start = performance.now();
  if (!reference.datasetId || !reference.versionId) {
    throw new Error("Visual Intelligence training results require an exact registered dataset version.");
  }
  const history = await requestScopedTrainingHistory<{
    problem_type?: string;
    target?: string;
    raw?: Record<string, { name?: string; task?: string; y_true: number[]; y_score: number[] }>;
  }>({
    project_id: reference.projectId,
    dataset_id: reference.datasetId,
    dataset_version_id: reference.versionId,
  });
  if (history.status !== "success") {
    throw new Error(`Visual Intelligence training results are unavailable (${history.status}).`);
  }
  const summary = history.summary;

  const raw = summary.raw?.[modelKey];
  const yTrue = raw?.y_true ?? [];
  const yScore = raw?.y_score ?? [];
  const rows = yTrue.map((actual, i) => ({ actual, prediction: yScore[i] }));
  const reportedProblemType = summary.problem_type;
  const problemType = reportedProblemType === "regression" || reportedProblemType === "classification" ? reportedProblemType : null;

  const meta: VisualDataSourceMeta = {
    source: "evaluation-result",
    rowsAvailable: rows.length,
    totalSourceRows: rows.length,
    sampled: false,
    partition: "train",
    freshAsOf: new Date().toISOString(),
    ephemeral: false, // backend-held for the life of the process, unlike Scoring's TEST/OOT React state
    aggregationMethod: "none",
    queryDurationMs: performance.now() - start,
  };
  return {
    reference: { ...reference, sourceType: "evaluation-result", partition: "train", modelId: modelKey, problemType: problemType ?? reference.problemType, target: summary.target ?? reference.target },
    meta,
    rows,
    problemType,
    modelName: raw?.name ?? null,
  };
}

/**
 * Persistent Scoring Runs, Phase G: rows from a durable ScoringRun's governed
 * Parquet artifact (GET /api/scoring-runs/{id}/rows), used in place of
 * fetchWorkspaceRows whenever `reference.sourceType === "scoring-session"`.
 * Unlike workspace data, this is NOT ephemeral -- the same scoringRunId always
 * returns the same rows, including after a refresh, because the id lives in
 * the URL (see VisualIntelligenceContext.tsx) rather than in React state.
 */
export async function fetchScoringRunRows(
  reference: VisualDatasetReference,
  options: { maxRows?: number } = {}
): Promise<VisualDataResult<Record<string, unknown>>> {
  const start = performance.now();
  if (!reference.scoringRunId) throw new Error("A scoringRunId is required to load a scoring run's rows.");
  const maxRows = options.maxRows ?? 5000;
  const payload = await getScoringRunRows(reference.scoringRunId, maxRows);
  const meta: VisualDataSourceMeta = {
    source: "scoring-session",
    rowsAvailable: payload.rows.length,
    totalSourceRows: payload.totalRowCount,
    sampled: payload.truncated,
    partition: reference.partition,
    freshAsOf: new Date().toISOString(),
    ephemeral: false, // a durable ScoringRun artifact, unlike Step10_Scoring's plain React state
    aggregationMethod: "none",
    queryDurationMs: performance.now() - start,
  };
  return { reference: { ...reference, sourceType: "scoring-session" }, meta, rows: payload.rows };
}

/**
 * Same durable ScoringRun source, shaped as {actual, prediction} pairs for the
 * Classification Decision Explorer and Regression Diagnostic Explorer -- the
 * scoring-session counterpart to fetchTrainingEvaluationResult's TRAIN-only,
 * ephemeral-process-memory evaluation result.
 */
export async function fetchScoringRunEvaluationRows(
  reference: VisualDatasetReference,
  task: "classification" | "regression"
): Promise<VisualDataResult<{ actual: number; prediction: number }> & { modelName: string | null }> {
  const result = await fetchScoringRunRows(reference, { maxRows: 5000 });
  const predictionKey = task === "regression" ? "predicted_value" : "adjusted_score";
  const rows = result.rows
    .map((row) => ({ actual: Number(row.actual), prediction: Number(row[predictionKey] ?? row.prediction ?? row.score) }))
    .filter((row) => Number.isFinite(row.actual) && Number.isFinite(row.prediction));
  return { ...result, rows, modelName: reference.modelId ?? null };
}

export type SegmentAggregateResult = {
  rowCount: number;
  mean: number | null;
  median: number | null;
  std: number | null;
  min: number | null;
  max: number | null;
  targetRate: number | null; // classification: share of rows where target column == positive value
  aggregationMethod: "server" | "duckdb-wasm" | "client-sample";
  queryDurationMs: number;
};

async function tryServerSegmentAggregate(
  reference: VisualDatasetReference,
  field: string,
  range: { min?: number; max?: number },
  positiveValue?: unknown
): Promise<SegmentAggregateResult | null> {
  void positiveValue;
  try {
    const filters = [];
    if (range.min !== undefined) filters.push({ column: field, op: "gte", value: range.min });
    if (range.max !== undefined) filters.push({ column: field, op: "lte", value: range.max });
    const response = await submitAnalyticalQuery({
      ...toDatasetReferenceFields(reference),
      operation: "column_profile",
      selectedColumns: [field],
      filters,
      // This prototype route has no verified Analysis Partition membership.
      // Request structural aggregates only; target-rate evidence must come
      // from a dedicated development-scoped backend artifact.
      aggregations: {},
    });
    if (response.status !== "completed" || !response.result) return null;
    const result = response.result as { totalCount?: number; mean?: number; median?: number; std?: number; minimum?: number; maximum?: number };
    return {
      rowCount: result.totalCount ?? 0, mean: result.mean ?? null, median: result.median ?? null, std: result.std ?? null,
      min: result.minimum ?? null, max: result.maximum ?? null, targetRate: null,
      aggregationMethod: "server",
      queryDurationMs: response.durationMs ?? 0,
    };
  } catch {
    return null; // honest fallback -- server unavailable or unauthorized for this source; caller proceeds to the local strategies
  }
}

/**
 * Selected-segment aggregation for the Distribution Explorer.
 *
 * Enterprise Analytical Data Plane priority (Phase N -- supersedes the earlier
 * Visual Intelligence Phase 1 policy of "DuckDB-Wasm above 2,000 rows"):
 *   1. Server-side aggregate (POST /api/analytics/queries, operation=histogram/
 *      grouped_summary-shaped) -- authoritative, works regardless of how many
 *      rows the *source* has, since the server never materializes the full
 *      source for an aggregate.
 *   2. DuckDB-Wasm -- only as a fallback when the server request fails AND the
 *      rows are already resident in the browser (already fetched, already
 *      bounded by fetchWorkspaceRows' server-side cap) AND large enough that a
 *      client streaming pass would be the slower option.
 *   3. Client streaming pass -- small already-local data, or final fallback.
 * DuckDB-Wasm is never chosen merely because rows.length crosses a fixed
 * threshold; the threshold that matters now is "did the server aggregate
 * fail," not "how many rows are already in the browser."
 */
export async function computeSegmentAggregate(
  reference: VisualDatasetReference,
  rows: Record<string, unknown>[],
  field: string,
  range: { min?: number; max?: number },
  positiveValue?: unknown
): Promise<SegmentAggregateResult> {
  void positiveValue;
  const serverResult = await tryServerSegmentAggregate(reference, field, range, positiveValue);
  if (serverResult) return serverResult;

  const strategy = chooseRenderStrategy(rows.length);
  const whereClauseParts: string[] = [];
  if (range.min !== undefined) whereClauseParts.push(`"${field}" >= ${Number(range.min)}`);
  if (range.max !== undefined) whereClauseParts.push(`"${field}" <= ${Number(range.max)}`);
  const whereClause = whereClauseParts.length ? `WHERE ${whereClauseParts.join(" AND ")}` : "";

  if (strategy === "direct-svg") {
    const start = performance.now();
    const filtered = rows.filter((row) => {
      const value = Number(row[field]);
      if (!Number.isFinite(value)) return false;
      if (range.min !== undefined && value < range.min) return false;
      if (range.max !== undefined && value > range.max) return false;
      return true;
    });
    const values = filtered.map((row) => Number(row[field])).filter(Number.isFinite);
    const { streamingMeanStd, streamingMedian, safeMinMax } = await import("./largeDataPolicy");
    const { mean, std } = streamingMeanStd(values);
    const minMax = safeMinMax(values);
    return {
      rowCount: filtered.length, mean: values.length ? mean : null, median: streamingMedian(values), std: values.length ? std : null,
      min: minMax?.min ?? null, max: minMax?.max ?? null, targetRate: null, aggregationMethod: "client-sample", queryDurationMs: performance.now() - start,
    };
  }

  const table = await registerTable(reference.projectId, "distribution_source", rows);
  const sql = `SELECT COUNT(*) AS row_count, AVG("${field}") AS mean, STDDEV_SAMP("${field}") AS std, MIN("${field}") AS min_value, MAX("${field}") AS max_value, MEDIAN("${field}") AS median, NULL AS target_rate FROM ${table} ${whereClause}`;
  const result = await runQuery(sql);
  const row = result.rows[0] ?? {};
  return {
    rowCount: Number(row.row_count ?? 0),
    mean: row.mean === null || row.mean === undefined ? null : Number(row.mean),
    median: row.median === null || row.median === undefined ? null : Number(row.median),
    std: row.std === null || row.std === undefined ? null : Number(row.std),
    min: row.min_value === null || row.min_value === undefined ? null : Number(row.min_value),
    max: row.max_value === null || row.max_value === undefined ? null : Number(row.max_value),
    targetRate: row.target_rate === null || row.target_rate === undefined ? null : Number(row.target_rate),
    aggregationMethod: "duckdb-wasm",
    queryDurationMs: result.queryDurationMs,
  };
}

/** Reject a query result whose context no longer matches the currently active
 *  project/dataset/model -- the guard against stale async results updating a
 *  newer selection (project switch, dataset-version change, model change while
 *  a query was in flight). Callers pass the reference captured when the query
 *  STARTED and the reference that is CURRENT when it resolves. */
export function isStaleResult(startedFor: VisualDatasetReference, currentContext: VisualDatasetReference): boolean {
  return (
    startedFor.projectId !== currentContext.projectId ||
    startedFor.datasetId !== currentContext.datasetId ||
    startedFor.versionId !== currentContext.versionId ||
    startedFor.modelId !== currentContext.modelId
  );
}

/** Sample-with-disclosure helper for callers that must render something even
 *  above the aggregate threshold (e.g. a scatter plot that cannot be reduced to
 *  a single aggregate). Always returns sampled=true metadata -- never silent. */
export function sampleForDirectRender<T>(rows: T[], sampleSize = 2000): { rows: T[]; sampled: boolean } {
  if (rows.length <= sampleSize) return { rows, sampled: false };
  return { rows: reservoirSample(rows, sampleSize), sampled: true };
}

/** Project-switch / sign-out / dataset-version-change cleanup entry point --
 *  called from the VI context provider's effect (visualIntelligenceContext.tsx). */
export async function clearVisualDataForProject(projectId: string): Promise<void> {
  await clearProjectTables(projectId);
}

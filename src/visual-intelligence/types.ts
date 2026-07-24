// ATLAS Visual Intelligence Foundation -- shared typed identities.
//
// Every visualization in this module resolves its data through a
// VisualDatasetReference, never through a dataset/model NAME. Names are
// display-only; identity is always the explicit id tuple below. This mirrors
// the same lesson already applied to the Dataset Library
// (docs/architecture/DATASET_LIBRARY_ADR.md) and to browser dataset state
// (Predictive Modeling Repair Stage 6.2): name-based lookup is how two
// different projects' data silently collided in earlier stages.

export type ProblemType = "classification" | "regression";

/** Distinguishes WHERE a visualization's underlying rows actually live and
 *  whether they are durable. This directly drives the Data Access Layer's
 *  source-selection decision (see dataAccessLayer.ts) and is always shown to
 *  the user via VisualDataSourceMeta.ephemeral. */
export type VisualSourceType =
  | "workspace" // the current project's in-memory DATASTORE / browser dataset cache -- session-scoped, not durable
  | "registered" // a Dataset Library asset, pinned by datasetId + versionId -- durable
  | "scoring-session" // a TRAIN/TEST/OOT scoring result held only in the current Scoring page's React state -- ephemeral unless registered
  | "evaluation-result" // /train/last or /eval/* payloads -- backend-held, but only for the most recent run
  | "interpretation-result" // /interpretation/* payloads (SHAP, PDP, RFE, importance) -- backend-held, most recent run only
  | "derived" // computed client-side from one or more of the above (e.g. a DuckDB-Wasm aggregation)
  | "server-aggregate"; // computed server-side and returned as a small summary, never raw rows

export type ScoringPartition = "train" | "test" | "oot";

/**
 * The identity every visualization is pinned to. Two references are "the
 * same data" only when every field that applies to their sourceType matches.
 * Fields that don't apply to a given sourceType are left undefined rather
 * than defaulted -- an undefined field must never be treated as "matches
 * anything" by adapter mismatch-rejection logic (see adapters/queryResultAdapter.ts).
 */
export type VisualDatasetReference = {
  authenticatedUserId: string;
  projectId: string;
  datasetId?: string;
  versionId?: string;
  sourceType: VisualSourceType;
  partition?: ScoringPartition;
  modelId?: string;
  /** Identifies one specific scoring run (a single TRAIN/TEST/OOT score action),
   *  so a stale async result from a superseded run can never be attributed to a
   *  newer one. Only meaningful when sourceType is "scoring-session". */
  scoringRunId?: string;
  target?: string;
  problemType?: ProblemType;
  /** A cheap structural fingerprint (sorted column names + dtypes) used to
   *  reject a query result whose shape no longer matches what a chart expects
   *  -- e.g. after Feature Engineering changes the materialized columns. */
  schemaFingerprint?: string;
  featureManifestVersion?: string;
};

export function referencesMatch(a: VisualDatasetReference, b: VisualDatasetReference): boolean {
  const fields: Array<keyof VisualDatasetReference> = [
    "authenticatedUserId", "projectId", "datasetId", "versionId", "sourceType",
    "partition", "modelId", "scoringRunId", "target", "problemType", "schemaFingerprint",
  ];
  return fields.every((field) => {
    const av = a[field];
    const bv = b[field];
    if (av === undefined || bv === undefined) return true; // absent on either side = "not asserted", not a mismatch
    return av === bv;
  });
}

/** Metadata the Data Access Layer must attach to every result so the UI can
 *  render an honest sampling/freshness/durability notice (Phase C/D requirement:
 *  "Do not silently treat a sample as the full population"). */
export type VisualDataSourceMeta = {
  source: VisualSourceType;
  rowsAvailable: number;
  totalSourceRows: number;
  sampled: boolean;
  partition?: ScoringPartition;
  datasetVersion?: string;
  /** ISO timestamp of when this data was produced/fetched, not when it was rendered. */
  freshAsOf: string;
  /** True when this data could disappear on refresh (e.g. an unregistered scoring result). */
  ephemeral: boolean;
  aggregationMethod?: "none" | "server-aggregate" | "duckdb-wasm" | "client-sample";
  queryDurationMs?: number;
};

export type VisualDataResult<T> = {
  reference: VisualDatasetReference;
  meta: VisualDataSourceMeta;
  rows: T[];
};

/** Returned instead of VisualDataResult when no strategy could safely produce
 *  data -- an explicit refusal, never a silently-empty chart pretending to be
 *  a real "zero rows" answer. */
export type VisualDataRefusal = {
  ok: false;
  reason: string;
};

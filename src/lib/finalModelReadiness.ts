// Resolves the Scoring page's final-model readiness view from a /model/final/status
// response plus the locally-known modeling context (project id from the workflow store,
// dataset version and target derived from the sessionStorage-backed local dataset).
//
// The context comparison must mirror the backend's _artifact_context_mismatch semantics
// (server/evaluation/eval_service.py): a field is only compared when BOTH sides are known.
// sessionStorage is per-tab, so a user can legitimately arrive at Scoring with no local
// dataset snapshot (new tab, cleared session, API-driven setup) -- an absent local
// expectation means "cannot verify", not "belongs to a different project/dataset/target".
// The saved artifact's identity was already validated against the trained model's own
// recorded metadata at save time, so trusting the backend's ready flag in that case does
// not weaken genuine-mismatch detection: whenever a local expectation IS present and
// disagrees with the saved metadata, the mismatch error still fires.

export type FinalModelContextFields = {
  project_id?: string;
  dataset_version?: string;
  target?: string;
};

export type ExpectedModelingContext = {
  projectId: string;
  datasetVersion: string;
  target: string;
};

export type FinalModelReadinessView<M extends FinalModelContextFields> = {
  ready: boolean;
  metadata: M;
  error: string;
};

export const FINAL_MODEL_CONTEXT_MISMATCH_MESSAGE =
  "The saved final model belongs to a different project, dataset version, or target. Return to Interpretation and save the current final model.";

function contextFieldMatches(expected: string | undefined, actual: string | undefined): boolean {
  if (!expected || !actual) return true;
  return expected === actual;
}

export function resolveFinalModelReadiness<M extends FinalModelContextFields>(
  data: { ready?: boolean; metadata?: M | null } | null | undefined,
  expected: ExpectedModelingContext
): FinalModelReadinessView<M> {
  const metadata = (data?.metadata ?? {}) as M;
  const contextMatches =
    contextFieldMatches(expected.projectId, metadata.project_id) &&
    contextFieldMatches(expected.datasetVersion, metadata.dataset_version) &&
    contextFieldMatches(expected.target, metadata.target);
  const backendReady = Boolean(data?.ready);
  return {
    ready: backendReady && contextMatches,
    metadata: contextMatches ? metadata : ({} as M),
    error: backendReady && !contextMatches ? FINAL_MODEL_CONTEXT_MISMATCH_MESSAGE : "",
  };
}

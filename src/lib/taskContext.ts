// Shared task-context resolver (problem type + target), used by any component that
// needs to know "is this project classification or regression" without repeating its
// own browser-cache-only fallback logic.
//
// Root cause this fixes: Step08_Evaluation.tsx and CopilotCard.tsx independently derived
// problem type from inferLocalProblemType(loadLocalDataset()) ?? "classification" -- the
// browser dataset cache (src/lib/localDataset.ts) is a per-tab session convenience cache
// (Predictive Modeling Repair Stage 6.2) and is legitimately empty on any fresh session
// (new tab, reopened project, browser restart). Defaulting to "classification" in that
// case silently mis-rendered a fully-trained regression project as classification
// (confirmed defect, Regression Stage B audit). Evaluation was fixed directly; this
// module generalizes that fix into one resolver so CopilotCard (and any future Visual
// Intelligence component) uses the same backend-truth-first priority instead of a third
// independent copy of the same fallback.
//
// Priority order:
//   1. Backend training truth (/train/last's own problem_type) -- authoritative once a
//      training run exists for this project, regardless of what the current browser tab
//      has cached.
//   2. Local dataset cache (inferLocalProblemType(loadLocalDataset())) -- the only signal
//      available before any model has been trained (e.g. during Data Acquisition/EDA).
//   3. null -- honestly unknown, not defaulted to either problem type.
import { inferLocalProblemType, loadLocalDataset } from "./localDataset";
import type { CanonicalDatasetIdentity } from "./datasetIdentity";
import { requestScopedTrainingHistory } from "./scopedTrainingHistory";

export type ProblemType = "classification" | "regression";

export type TaskContext = {
  problemType: ProblemType | null;
  target: string | null;
  /** Where problemType/target came from -- surfaced so callers/tests can distinguish an
   *  authoritative backend answer from a best-effort local guess. */
  source: "backend-training" | "local-cache" | "unknown";
};

const UNKNOWN_CONTEXT: TaskContext = { problemType: null, target: null, source: "unknown" };

// Small in-memory, per-projectId cache so repeated resolveTaskContext() calls within the
// same page (e.g. CopilotCard re-rendering on every route change) don't refire the same
// /train/last request. Not persisted -- a fresh page load always asks the backend again.
const cache = new Map<string, Promise<TaskContext>>();

function localFallback(): TaskContext {
  const dataset = loadLocalDataset();
  const problemType = inferLocalProblemType(dataset);
  if (!problemType) return UNKNOWN_CONTEXT;
  return { problemType, target: dataset?.target ?? null, source: "local-cache" };
}

/** Pure priority logic, reusable by any caller that already holds a fetched training
 *  summary (e.g. CopilotCard, which fetches /train/last for its own purposes and would
 *  otherwise waste a second network round trip calling resolveTaskContext()). Backend
 *  truth always wins over the local dataset cache when both are present. */
export function deriveTaskContext(
  trainingSummary: { problem_type?: string; target?: string } | null | undefined,
  dataset = loadLocalDataset()
): TaskContext {
  const reported = trainingSummary?.problem_type;
  if (reported === "regression" || reported === "classification") {
    const target = typeof trainingSummary?.target === "string" ? trainingSummary.target : dataset?.target ?? null;
    return { problemType: reported, target, source: "backend-training" };
  }
  const problemType = inferLocalProblemType(dataset);
  if (!problemType) return UNKNOWN_CONTEXT;
  return { problemType, target: dataset?.target ?? null, source: "local-cache" };
}

async function fetchBackendTaskContext(
  identity: CanonicalDatasetIdentity,
  signal?: AbortSignal,
): Promise<TaskContext> {
  const result = await requestScopedTrainingHistory<{ problem_type?: string; target?: string }>(
    identity,
    signal,
  );
  return result.status === "success"
    ? deriveTaskContext(result.summary)
    : localFallback();
}

/** Resolve the current project's task context, preferring backend training truth over the
 *  browser's local dataset cache. Cached per projectId for the lifetime of the page. */
export function resolveTaskContext(
  identity: CanonicalDatasetIdentity | null,
  signal?: AbortSignal,
): Promise<TaskContext> {
  if (!identity) return Promise.resolve(localFallback());
  const cacheKey = `${identity.project_id}:${identity.dataset_id}:${identity.dataset_version_id}`;
  const cached = cache.get(cacheKey);
  if (cached) return cached;
  const promise = fetchBackendTaskContext(identity, signal);
  cache.set(cacheKey, promise);
  return promise;
}

/** Drop the cached resolution for a project -- call when a new training run completes so
 *  the next resolveTaskContext() call re-asks the backend instead of serving a stale answer. */
export function invalidateTaskContext(projectId: string): void {
  for (const key of cache.keys()) {
    if (key.startsWith(`${projectId}:`)) cache.delete(key);
  }
}

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

const API_BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

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

async function fetchBackendTaskContext(projectId: string): Promise<TaskContext> {
  try {
    const response = await fetch(`${API_BASE}/train/last?project_id=${encodeURIComponent(projectId)}`, { credentials: "include" });
    if (!response.ok) return localFallback();
    const payload = await response.json();
    return deriveTaskContext(payload?.summary ?? null);
  } catch {
    return localFallback();
  }
}

/** Resolve the current project's task context, preferring backend training truth over the
 *  browser's local dataset cache. Cached per projectId for the lifetime of the page. */
export function resolveTaskContext(projectId: string): Promise<TaskContext> {
  if (!projectId) return Promise.resolve(localFallback());
  const cached = cache.get(projectId);
  if (cached) return cached;
  const promise = fetchBackendTaskContext(projectId);
  cache.set(projectId, promise);
  return promise;
}

/** Drop the cached resolution for a project -- call when a new training run completes so
 *  the next resolveTaskContext() call re-asks the backend instead of serving a stale answer. */
export function invalidateTaskContext(projectId: string): void {
  cache.delete(projectId);
}

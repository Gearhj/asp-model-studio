import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Loader2, RefreshCw, ShieldAlert } from "lucide-react";
import {
  DatasetIdentityError,
  requireCanonicalDatasetIdentity,
  requireLocalDatasetCanonicalIdentity,
  type CanonicalDatasetIdentity,
} from "../lib/datasetIdentity";
import {
  classifyPredictiveIdentity,
  type ActiveIdentityProbe,
  type LocalIdentityProbe,
  type PredictiveIdentityReadiness,
} from "../lib/predictiveIdentityReadiness";
import {
  inferLocalProblemType,
  loadLocalDataset,
  saveLocalDataset,
  type LocalDataset,
} from "../lib/localDataset";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { getProjectWorkflowStateFromDatabase } from "../lib/serverPersistence";

const API_BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type PredictiveIdentityContextValue = {
  readiness: PredictiveIdentityReadiness;
  retry: () => void;
};

const IDLE: PredictiveIdentityReadiness = {
  status: "idle",
  projectId: "",
  identity: null,
  message: "Select a Predictive Modeling project to resolve dataset identity.",
};

const PredictiveIdentityContext = createContext<PredictiveIdentityContextValue>({
  readiness: IDLE,
  retry: () => undefined,
});

function probeLocalIdentity(projectId: string): LocalIdentityProbe {
  const dataset = loadLocalDataset();
  if (!dataset) return { kind: "missing" };
  try {
    return {
      kind: "exact",
      identity: requireLocalDatasetCanonicalIdentity(
        projectId,
        dataset,
        "Restored browser dataset identity",
      ),
    };
  } catch (error) {
    if (
      error instanceof DatasetIdentityError
      && error.code === "missing_canonical_identity"
      && Boolean(dataset.dataset_version)
    ) {
      return { kind: "legacy_unresolved" };
    }
    return { kind: "contradictory" };
  }
}

async function activeIdentityProbe(projectId: string, signal: AbortSignal): Promise<ActiveIdentityProbe> {
  try {
    const response = await fetch(
      `${API_BASE}/data/active-identity?project_id=${encodeURIComponent(projectId)}`,
      { credentials: "include", signal },
    );
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) {
      return {
        kind: "http_error",
        status: response.status,
        detail: typeof payload?.detail === "string" ? payload.detail : undefined,
      };
    }
    return { kind: "ready", identity: payload };
  } catch (error) {
    if (signal.aborted) throw error;
    return {
      kind: "network_error",
      detail: error instanceof Error ? error.message : undefined,
    };
  }
}

async function restoreBrowserDataset(
  identity: CanonicalDatasetIdentity,
  signal: AbortSignal,
) {
  const response = await fetch(
    `${API_BASE}/data/get_sample?project_id=${encodeURIComponent(identity.project_id)}&max_rows=5000`,
    { credentials: "include", signal },
  );
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok || !Array.isArray(payload.headers) || !Array.isArray(payload.rows)) {
    return {
      ok: false as const,
      status: response.status,
      detail: typeof payload?.detail === "string"
        ? payload.detail
        : "The active dataset sample could not be restored.",
    };
  }

  const target = typeof payload.target === "string" && payload.headers.includes(payload.target)
    ? payload.target
    : null;
  const selectedColumns = Array.isArray(payload.selected_columns)
    ? payload.selected_columns.map(String).filter((column: string) => payload.headers.includes(column) && column !== target)
    : payload.headers.filter((column: string) => column !== target);
  const dataset: LocalDataset = {
    headers: payload.headers.map(String),
    rows: payload.rows,
    target,
    selected_columns: selectedColumns,
    registered_row_count: payload.rows.length,
    browser_data_complete: false,
    dataset_id: identity.dataset_id,
    dataset_version_id: identity.dataset_version_id,
    dataset_version: identity.dataset_version_id,
    dataset_library: {
      datasetId: identity.dataset_id,
      versionId: identity.dataset_version_id,
      datasetName: identity.dataset_version_label || "Registered Dataset Library asset",
      datasetRole: "modeling",
      sourceType: identity.dataset_source_type || "dataset-library",
      rowCount: payload.rows.length,
      columnCount: payload.headers.length,
    },
  };
  dataset.problem_type = inferLocalProblemType(dataset) ?? undefined;
  const saved = saveLocalDataset(dataset);
  if (saved === "failed") {
    return {
      ok: false as const,
      status: 507,
      detail: "The browser could not cache the verified dataset sample.",
    };
  }
  window.dispatchEvent(new CustomEvent("atlas-dataset-updated"));
  return { ok: true as const };
}

export function PredictiveIdentityProvider({ children }: { children: ReactNode }) {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectType = useWorkflowStore((state) => state.projectType);
  const hasDataset = useWorkflowStore((state) => state.hasDataset);
  const persistedIdentity = useWorkflowStore((state) => state.datasetIdentity);
  const setDatasetIdentity = useWorkflowStore((state) => state.setDatasetIdentity);
  const applyAuthoritativeWorkflowState = useWorkflowStore((state) => state.applyAuthoritativeWorkflowState);
  const invalidateEffectiveWorkflow = useWorkflowStore((state) => state.invalidateEffectiveWorkflow);
  const [revision, setRevision] = useState(0);
  const [readiness, setReadiness] = useState<PredictiveIdentityReadiness>(IDLE);
  const requestGeneration = useRef(0);
  const retry = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    const refresh = () => retry();
    window.addEventListener("atlas-dataset-identity-updated", refresh);
    return () => window.removeEventListener("atlas-dataset-identity-updated", refresh);
  }, [retry]);

  useEffect(() => {
    const generation = ++requestGeneration.current;
    const controller = new AbortController();

    if (projectType !== "predictive-modeling" || !projectId) {
      setReadiness(IDLE);
      return () => controller.abort();
    }

    setReadiness({
      status: "loading",
      projectId,
      identity: null,
      message: "Verifying the exact registered Dataset Library version...",
    });

    void (async () => {
      let activeProbe: ActiveIdentityProbe;
      try {
        activeProbe = await activeIdentityProbe(projectId, controller.signal);
      } catch {
        return;
      }
      if (controller.signal.aborted || generation !== requestGeneration.current) return;

      const localProbe = probeLocalIdentity(projectId);
      let next = classifyPredictiveIdentity({
        projectId,
        hasDataset,
        persistedIdentity,
        activeProbe,
        localProbe,
      });

      if (next.status === "ready" && next.identity && localProbe.kind === "missing") {
        const restored = await restoreBrowserDataset(next.identity, controller.signal).catch(() => null);
        if (controller.signal.aborted || generation !== requestGeneration.current) return;
        if (!restored?.ok) {
          const status = restored?.status;
          next = {
            status: status === 401 || status === 403 ? "unauthorized" : "error",
            projectId,
            identity: null,
            message: status === 401 || status === 403
              ? "ATLAS could not authorize restoration of the governed dataset sample."
              : restored?.detail || "ATLAS could not restore the governed dataset sample.",
            ...(status == null ? {} : { httpStatus: status }),
          };
        }
      }

      if (next.status === "ready") {
        // Preserve the backend's durable activation revision in the workflow
        // store before applying effective state. A stale workflow response from
        // an earlier activation revision must therefore fail closed.
        if (
          next.identity
          && (
            persistedIdentity?.project_id !== next.identity.project_id
            || persistedIdentity?.dataset_id !== next.identity.dataset_id
            || persistedIdentity?.dataset_version_id !== next.identity.dataset_version_id
            || persistedIdentity?.activation_revision !== next.identity.activation_revision
          )
        ) {
          setDatasetIdentity(next.identity);
        }
        const workflowState = await getProjectWorkflowStateFromDatabase(
          projectId,
          controller.signal,
        ).catch(() => null);
        if (controller.signal.aborted || generation !== requestGeneration.current) return;
        // A missing/legacy workflow-state response remains fail closed. Only
        // backend effectiveCompletedSteps/effectiveSteps may grant progress.
        applyAuthoritativeWorkflowState(workflowState);
      } else {
        invalidateEffectiveWorkflow(next.status);
      }

      if (!controller.signal.aborted && generation === requestGeneration.current) {
        setReadiness(next);
      }
    })();

    return () => controller.abort();
  }, [
    applyAuthoritativeWorkflowState,
    hasDataset,
    invalidateEffectiveWorkflow,
    persistedIdentity,
    projectId,
    projectType,
    revision,
    setDatasetIdentity,
  ]);

  const value = useMemo(() => ({ readiness, retry }), [readiness, retry]);
  return (
    <PredictiveIdentityContext.Provider value={value}>
      {children}
    </PredictiveIdentityContext.Provider>
  );
}

export function usePredictiveIdentity() {
  return useContext(PredictiveIdentityContext);
}

export function PredictiveIdentityGate({ children }: { children: ReactNode }) {
  const { readiness, retry } = usePredictiveIdentity();
  if (readiness.status === "ready") return <>{children}</>;

  const loading = readiness.status === "idle" || readiness.status === "loading";
  const unauthorized = readiness.status === "unauthorized";
  const recoverable = ["missing", "stale", "legacy_unresolved", "contradictory"].includes(readiness.status);

  return (
    <section
      className={`rounded-xl border p-6 shadow-sm ${
        loading
          ? "border-blue-200 bg-blue-50 text-blue-950"
          : unauthorized
            ? "border-red-200 bg-red-50 text-red-950"
            : "border-amber-200 bg-amber-50 text-amber-950"
      }`}
      data-testid="predictive-identity-gate"
      data-identity-status={readiness.status}
      role={loading ? "status" : "alert"}
    >
      <div className="flex items-start gap-3">
        {loading ? (
          <Loader2 className="mt-0.5 animate-spin" size={20} />
        ) : unauthorized ? (
          <ShieldAlert className="mt-0.5" size={20} />
        ) : (
          <AlertTriangle className="mt-0.5" size={20} />
        )}
        <div className="min-w-0 flex-1">
          <h1 className="text-base font-semibold">
            {loading
              ? "Verifying governed dataset identity"
              : readiness.status === "missing"
                ? "Dataset selection required"
                : readiness.status === "legacy_unresolved"
                  ? "Canonical dataset recovery required"
                  : readiness.status === "contradictory"
                    ? "Conflicting dataset identities"
                    : unauthorized
                      ? "Dataset access is not authorized"
                      : "Dataset identity is unavailable"}
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6">{readiness.message}</p>
          <p className="mt-2 text-xs font-medium">Project scope: {readiness.projectId || "not resolved"}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {recoverable ? (
              <Link to="/step01" className="atlas-primary-button" data-testid="identity-recovery-data-acquisition">
                Open Data Acquisition
              </Link>
            ) : null}
            <button type="button" className="atlas-secondary-button" onClick={retry}>
              <RefreshCw size={15} /> Retry verification
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

export function verifiedPredictiveIdentity(value: PredictiveIdentityReadiness) {
  return value.status === "ready"
    ? requireCanonicalDatasetIdentity(value.identity, "Verified predictive route identity")
    : null;
}

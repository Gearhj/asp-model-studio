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
import { Link, useLocation } from "react-router-dom";
import { AlertTriangle, Loader2, RefreshCw, ShieldAlert } from "lucide-react";
import {
  requireCanonicalDatasetIdentity,
  type CanonicalDatasetIdentity,
} from "../lib/datasetIdentity";
import type {
  PredictiveIdentityReadiness,
} from "../lib/predictiveIdentityReadiness";
import {
  clearProjectDataset,
  saveProjectDataset,
  type LocalDataset,
} from "../lib/localDataset";
import {
  failedAuthoritativeProjectContext,
  IDLE_AUTHORITATIVE_PROJECT_CONTEXT,
  projectIdFromScopedPathname,
  resolvingAuthoritativeProjectContext,
  resolveAuthoritativeProjectContext,
  scopedWorkflowPath,
  type AuthoritativeProjectContextReadiness,
} from "../lib/authoritativeProjectContext";
import {
  applyProjectMetadataUpdate,
  projectContextUpdatedEventDetail,
  registerProjectMetadataEvent,
  type ProjectMetadataRefreshStatus,
  type ProjectMetadataUpdate,
  type ProjectMetadataUpdateDisposition,
} from "../lib/projectContextMetadata";
import { saveProjectContext, type ProjectContext } from "../lib/projectContext";
import { migrateStoredContext } from "../lib/projectContextPersistence";
import { useWorkflowStore } from "../state/useWorkflowStore";
import {
  getActiveDatasetIdentityFromDatabase,
  getProjectFromDatabase,
  getProjectWorkflowStateFromDatabase,
  PersistenceHttpError,
} from "../lib/serverPersistence";

const API_BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type PredictiveIdentityContextValue = {
  readiness: PredictiveIdentityReadiness;
  retry: () => void;
};

type AuthoritativeProjectContextValue = {
  readiness: AuthoritativeProjectContextReadiness;
  retry: () => void;
  metadataRefreshStatus: ProjectMetadataRefreshStatus;
  setMetadataRefreshStatus: (status: ProjectMetadataRefreshStatus) => void;
  publishSavedProjectMetadata: (
    update: ProjectMetadataUpdate,
  ) => ProjectMetadataUpdateDisposition;
  authenticatedUserId: string;
};

const IDLE: PredictiveIdentityReadiness = {
  status: "idle",
  projectId: "",
  identity: null,
  message: "Open a project-scoped Predictive Modeling route to resolve dataset identity.",
};

const PredictiveIdentityContext = createContext<PredictiveIdentityContextValue>({
  readiness: IDLE,
  retry: () => undefined,
});

const AuthoritativeProjectContext = createContext<AuthoritativeProjectContextValue>({
  readiness: IDLE_AUTHORITATIVE_PROJECT_CONTEXT,
  retry: () => undefined,
  metadataRefreshStatus: "idle",
  setMetadataRefreshStatus: () => undefined,
  publishSavedProjectMetadata: () => "identity_not_ready",
  authenticatedUserId: "",
});

function updateScopedProjectContextCompatibilityCopy(input: {
  projectId: string;
  projectName: string;
  modelId: string;
  userId: string;
  projectContext: Partial<ProjectContext> | null;
}) {
  if (!input.projectId || !input.userId || !input.projectContext) return;
  const materialized = migrateStoredContext(input.projectContext);
  if (!materialized) return;
  try {
    // MDD/report readers still use this content-only compatibility view. The
    // provider never reads it as identity authority and emits no event here.
    saveProjectContext({
      ...materialized,
      projectName: input.projectName,
      modelId: input.modelId,
    }, input.projectId, input.userId);
  } catch {
    // Browser storage availability cannot invalidate authoritative hydration.
  }
}

async function capture<T>(promise: Promise<T>) {
  try {
    return { ok: true as const, value: await promise };
  } catch (error) {
    return { ok: false as const, error };
  }
}

async function restoreBrowserDataset(
  identity: CanonicalDatasetIdentity,
  userId: string,
  signal: AbortSignal,
) {
  // Never leave a previous exact-ID cache in place while its current scope is
  // being revalidated.  Partition revision/scope is authority too, not just
  // the canonical dataset triple.
  clearProjectDataset(userId, identity.project_id);
  const query = new URLSearchParams({
    project_id: identity.project_id,
    expected_dataset_id: identity.dataset_id,
    expected_dataset_version_id: identity.dataset_version_id,
    max_rows: "5000",
  });
  const response = await fetch(
    `${API_BASE}/data/get_sample?${query.toString()}`,
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

  const target = typeof payload.target === "string" && payload.target.trim()
    ? payload.target.trim()
    : null;
  const scope = payload.scope && typeof payload.scope === "object"
    ? payload.scope as Record<string, unknown>
    : null;
  const exactResponse = payload.project_id === identity.project_id
    && payload.dataset_id === identity.dataset_id
    && payload.dataset_version_id === identity.dataset_version_id;
  const targetSafe = payload.target_values_included === false
    && (!target || payload.rows.every(
      (row: Record<string, unknown>) => !Object.prototype.hasOwnProperty.call(row, target),
    ));
  const scopeSafe = scope
    && (
      scope.analytical_scope === "development_population_predictors_only"
      || scope.analytical_scope === "full_governed_population_predictors_only"
    )
    && scope.target_values_included === false;
  const checksumSafe = !identity.dataset_content_hash
    || payload.source_checksum === identity.dataset_content_hash;
  if (!exactResponse || !targetSafe || !scopeSafe || !checksumSafe) {
    return {
      ok: false as const,
      status: 409,
      detail: "The backend sample did not satisfy the exact target-free analytical-scope contract.",
    };
  }
  const selectedColumns = Array.isArray(payload.selected_columns)
    ? payload.selected_columns.map(String).filter((column: string) => payload.headers.includes(column) && column !== target)
    : payload.headers.filter((column: string) => column !== target);
  const registeredRowCount = Number(
    payload.registered_row_count ?? payload.row_count ?? payload.rows.length,
  );
  const dataset: LocalDataset = {
    headers: payload.headers.map(String),
    rows: payload.rows,
    target,
    selected_columns: selectedColumns,
    registered_row_count: Number.isFinite(registeredRowCount)
      ? registeredRowCount
      : payload.rows.length,
    browser_data_complete: false,
    dataset_id: identity.dataset_id,
    dataset_version_id: identity.dataset_version_id,
    dataset_version: identity.dataset_version_id,
    activation_revision: Number.isSafeInteger(Number(payload.activation_revision))
      ? Number(payload.activation_revision)
      : identity.activation_revision,
    source_checksum: String(payload.source_checksum || "") || undefined,
    target_contract_id: typeof payload.target_contract_id === "string"
      ? payload.target_contract_id
      : undefined,
    problem_type:
      payload.problem_type === "classification" || payload.problem_type === "regression"
        ? payload.problem_type
        : undefined,
    target_values_included: false,
    cache_schema_version: 2,
    analytical_scope: scope.analytical_scope as LocalDataset["analytical_scope"],
    population_id: typeof scope.population_id === "string" ? scope.population_id : undefined,
    population_count: Number.isFinite(Number(scope.population_count))
      ? Number(scope.population_count)
      : undefined,
    analysis_partition_id:
      typeof scope.partition_id === "string" && scope.partition_id
        ? scope.partition_id
        : typeof scope.analysis_partition_id === "string"
          ? scope.analysis_partition_id
          : undefined,
    analysis_partition_revision: Number.isSafeInteger(Number(scope.partition_revision))
      && Number(scope.partition_revision) > 0
      ? Number(scope.partition_revision)
      : undefined,
    holdout_excluded: typeof scope.holdout_excluded === "boolean"
      ? scope.holdout_excluded
      : undefined,
    dataset_library: {
      datasetId: identity.dataset_id,
      versionId: identity.dataset_version_id,
      datasetName: identity.dataset_version_label || "Registered Dataset Library asset",
      datasetRole: "modeling",
      sourceType: identity.dataset_source_type || "dataset-library",
      rowCount: Number.isFinite(registeredRowCount)
        ? registeredRowCount
        : payload.rows.length,
      columnCount: payload.headers.length,
    },
  };
  const saved = saveProjectDataset(userId, identity.project_id, dataset);
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

function projectFailure(
  routeProjectId: string,
  error: unknown,
  resource: "project" | "workflow" | "identity",
) {
  const status = error instanceof PersistenceHttpError ? error.status : undefined;
  if (status === 401 || status === 403) {
    return failedAuthoritativeProjectContext({
      status: "unauthorized",
      routeProjectId,
      httpStatus: status,
      message: status === 401
        ? "Your ATLAS session is not authorized to resolve this project. Sign in again."
        : "You do not have permission to open this project and its governed workflow.",
    });
  }
  if (resource === "project" && status === 404) {
    return failedAuthoritativeProjectContext({
      status: "not_found",
      routeProjectId,
      httpStatus: status,
      message: "The requested project is unavailable or no longer exists.",
    });
  }
  return failedAuthoritativeProjectContext({
    status: "error",
    routeProjectId,
    ...(status == null ? {} : { httpStatus: status }),
    message: resource === "project"
      ? "ATLAS could not load the exact authorized project record."
      : resource === "workflow"
        ? "ATLAS could not load workflow state for the exact authorized project."
        : "ATLAS could not verify the project's exact active dataset identity.",
  });
}

function identityReadinessFromProjectContext(
  projectContext: AuthoritativeProjectContextReadiness,
): PredictiveIdentityReadiness {
  const projectId = projectContext.routeProjectId;
  if (projectContext.status === "ready") {
    return projectContext.activeDatasetIdentity
      ? {
          status: "ready",
          projectId,
          identity: projectContext.activeDatasetIdentity,
          message: "The exact registered Dataset Library version is verified for this project.",
        }
      : {
          status: "missing",
          projectId,
          identity: null,
          message: "Dataset selection is required before downstream Predictive Modeling routes can open.",
        };
  }
  if (projectContext.status === "idle") return IDLE;
  if (projectContext.status === "resolving") {
    return {
      status: "loading",
      projectId,
      identity: null,
      message: "Verifying the exact registered Dataset Library version...",
    };
  }
  if (projectContext.status === "unauthorized") {
    return {
      status: "unauthorized",
      projectId,
      identity: null,
      message: projectContext.message,
      ...(projectContext.httpStatus == null ? {} : { httpStatus: projectContext.httpStatus }),
    };
  }
  return {
    status: projectContext.status === "contradictory" ? "contradictory" : "error",
    projectId,
    identity: null,
    message: projectContext.message,
    ...(projectContext.httpStatus == null ? {} : { httpStatus: projectContext.httpStatus }),
  };
}

export function PredictiveIdentityProvider({
  children,
  authenticatedUserId,
}: {
  children: ReactNode;
  authenticatedUserId: string;
}) {
  const location = useLocation();
  const routeProjectId = projectIdFromScopedPathname(location.pathname);
  const applyAuthoritativeProjectContext = useWorkflowStore(
    (state) => state.applyAuthoritativeProjectContext,
  );
  const applyAuthoritativeProjectMetadata = useWorkflowStore(
    (state) => state.applyAuthoritativeProjectMetadata,
  );
  const [revision, setRevision] = useState(0);
  const [readiness, setReadiness] = useState<PredictiveIdentityReadiness>(IDLE);
  const [projectReadiness, setProjectReadiness] =
    useState<AuthoritativeProjectContextReadiness>(IDLE_AUTHORITATIVE_PROJECT_CONTEXT);
  const [metadataRefreshStatus, setMetadataRefreshStatus] =
    useState<ProjectMetadataRefreshStatus>("idle");
  const requestGeneration = useRef(0);
  const metadataRequestSequence = useRef(0);
  const emittedMetadataEvents = useRef(new Set<string>());
  const projectReadinessRef = useRef(projectReadiness);
  projectReadinessRef.current = projectReadiness;
  const routeProjectIdRef = useRef(routeProjectId);
  routeProjectIdRef.current = routeProjectId;
  const authenticatedUserIdRef = useRef(authenticatedUserId);
  authenticatedUserIdRef.current = authenticatedUserId;
  const retry = useCallback(() => setRevision((value) => value + 1), []);

  const publishSavedProjectMetadata = useCallback((update: ProjectMetadataUpdate) => {
    if (update.projectId !== routeProjectIdRef.current) return "wrong_project";
    if (update.actorUserId !== authenticatedUserIdRef.current) return "wrong_user";
    const result = applyProjectMetadataUpdate({
      readiness: projectReadinessRef.current,
      update,
      currentUserId: authenticatedUserIdRef.current,
      lastRequestSequence: metadataRequestSequence.current,
    });
    metadataRequestSequence.current = Math.max(
      metadataRequestSequence.current,
      result.requestSequence,
    );
    if (result.disposition === "applied" && result.readiness.status === "ready") {
      projectReadinessRef.current = result.readiness;
      setProjectReadiness(result.readiness);
      applyAuthoritativeProjectMetadata({
        projectId: result.readiness.project.projectId,
        projectName: result.readiness.project.projectName,
        modelId: result.readiness.project.modelId,
      });
    }
    if (result.disposition === "applied" || result.disposition === "duplicate") {
      updateScopedProjectContextCompatibilityCopy({
        projectId: update.projectId,
        projectName: update.projectName,
        modelId: update.modelId,
        userId: authenticatedUserIdRef.current,
        projectContext: update.projectContext,
      });
      setMetadataRefreshStatus("saved");
    }
    if (result.disposition === "applied" && update.source === "user_save") {
      if (!registerProjectMetadataEvent(emittedMetadataEvents.current, update)) {
        return result.disposition;
      }
      const detail = projectContextUpdatedEventDetail(update);
      if (!detail) return result.disposition;
      window.dispatchEvent(new CustomEvent("atlas-project-context-updated", {
        detail,
      }));
    }
    return result.disposition;
  }, [applyAuthoritativeProjectMetadata]);

  useEffect(() => {
    metadataRequestSequence.current = 0;
    emittedMetadataEvents.current.clear();
    setMetadataRefreshStatus("idle");
  }, [authenticatedUserId, routeProjectId]);

  useEffect(() => {
    const refresh = () => retry();
    window.addEventListener("atlas-dataset-identity-updated", refresh);
    return () => {
      window.removeEventListener("atlas-dataset-identity-updated", refresh);
    };
  }, [retry]);

  useEffect(() => {
    const generation = ++requestGeneration.current;
    const controller = new AbortController();

    if (!routeProjectId) {
      setProjectReadiness(IDLE_AUTHORITATIVE_PROJECT_CONTEXT);
      setReadiness(IDLE);
      return () => controller.abort();
    }

    const resolving = resolvingAuthoritativeProjectContext(routeProjectId);
    setProjectReadiness(resolving);
    setReadiness(identityReadinessFromProjectContext(resolving));

    void (async () => {
      let projectPayload: Record<string, any>;
      try {
        projectPayload = await getProjectFromDatabase(routeProjectId, controller.signal);
      } catch (error) {
        if (controller.signal.aborted || generation !== requestGeneration.current) return;
        const failed = projectFailure(routeProjectId, error, "project");
        setProjectReadiness(failed);
        setReadiness(identityReadinessFromProjectContext(failed));
        return;
      }
      if (controller.signal.aborted || generation !== requestGeneration.current) return;

      const [workflowResult, identityResult] = await Promise.all([
        capture(getProjectWorkflowStateFromDatabase(routeProjectId, controller.signal)),
        capture(
          getActiveDatasetIdentityFromDatabase(routeProjectId, controller.signal).catch((error) => {
            if (error instanceof PersistenceHttpError && [404, 409].includes(error.status)) {
              return null;
            }
            throw error;
          }),
        ),
      ]);
      if (controller.signal.aborted || generation !== requestGeneration.current) return;
      if (!workflowResult.ok) {
        const failed = projectFailure(routeProjectId, workflowResult.error, "workflow");
        setProjectReadiness(failed);
        setReadiness(identityReadinessFromProjectContext(failed));
        return;
      }
      if (!identityResult.ok) {
        const failed = projectFailure(routeProjectId, identityResult.error, "identity");
        setProjectReadiness(failed);
        setReadiness(identityReadinessFromProjectContext(failed));
        return;
      }
      const workflowState = workflowResult.value;
      const activeIdentityPayload = identityResult.value;

      let next = resolveAuthoritativeProjectContext({
        routeProjectId,
        projectPayload,
        workflowState,
        activeIdentityPayload,
        requireWorkflow: true,
        // Missing identity is represented in PredictiveIdentityReadiness and
        // blocked by PredictiveIdentityGate on downstream routes. It is not a
        // reason to remount Project Context when navigating within one project.
        requireActiveIdentity: false,
      });

      if (next.status === "ready" && next.activeDatasetIdentity) {
        const identity = next.activeDatasetIdentity;
        const userId = authenticatedUserId;
        if (!userId) {
          const failed = failedAuthoritativeProjectContext({
            status: "unauthorized",
            routeProjectId,
            httpStatus: 401,
            message: "The authenticated browser identity is unavailable. Sign in again before restoring governed project data.",
          });
          if (controller.signal.aborted || generation !== requestGeneration.current) return;
          setProjectReadiness(failed);
          setReadiness(identityReadinessFromProjectContext(failed));
          return;
        }
        // Revalidate the exact sample scope on every project workflow route
        // transition. Dataset identity alone cannot prove that a cached sample
        // matches the current Analysis Partition revision.
        const restored = await restoreBrowserDataset(
          identity,
          userId,
          controller.signal,
        ).catch((error) => {
          if (controller.signal.aborted) throw error;
          return null;
        });
        if (controller.signal.aborted || generation !== requestGeneration.current) return;
        if (!restored?.ok && (restored?.status === 401 || restored?.status === 403)) {
          next = failedAuthoritativeProjectContext({
            status: "unauthorized",
            routeProjectId,
            httpStatus: restored.status,
            message: "ATLAS could not authorize restoration of the governed dataset sample.",
          });
        }
      }

      if (controller.signal.aborted || generation !== requestGeneration.current) return;
      if (next.status === "ready") {
        // One verified backend project/workflow/identity tuple replaces the
        // compatibility view in one store update. No browser snapshot is read
        // as authority and no browser-to-backend write is performed here.
        applyAuthoritativeProjectContext(next);
        updateScopedProjectContextCompatibilityCopy({
          projectId: next.project.projectId,
          projectName: next.project.projectName,
          modelId: next.project.modelId,
          userId: authenticatedUserId,
          projectContext: next.project.projectContext,
        });
      }
      setProjectReadiness(next);
      setReadiness(identityReadinessFromProjectContext(next));
    })();

    return () => controller.abort();
  }, [
    applyAuthoritativeProjectContext,
    authenticatedUserId,
    location.pathname,
    revision,
    routeProjectId,
  ]);

  // Effects run after render. Derive a synchronous route-keyed resolving view
  // so a navigation from Project A to Project B can never expose Project A's
  // prior ready context for even one render while the new request starts.
  const exposedProjectReadiness = routeProjectId
    ? projectReadiness.routeProjectId === routeProjectId
      ? projectReadiness
      : resolvingAuthoritativeProjectContext(routeProjectId)
    : IDLE_AUTHORITATIVE_PROJECT_CONTEXT;
  const exposedIdentityReadiness = routeProjectId
    ? readiness.projectId === routeProjectId
      ? readiness
      : identityReadinessFromProjectContext(
          resolvingAuthoritativeProjectContext(routeProjectId),
        )
    : IDLE;
  const identityValue = useMemo(
    () => ({ readiness: exposedIdentityReadiness, retry }),
    [exposedIdentityReadiness, retry],
  );
  const projectValue = useMemo(
    () => ({
      readiness: exposedProjectReadiness,
      retry,
      metadataRefreshStatus,
      setMetadataRefreshStatus,
      publishSavedProjectMetadata,
      authenticatedUserId,
    }),
    [
      exposedProjectReadiness,
      metadataRefreshStatus,
      publishSavedProjectMetadata,
      retry,
      authenticatedUserId,
    ],
  );
  return (
    <AuthoritativeProjectContext.Provider value={projectValue}>
      <PredictiveIdentityContext.Provider value={identityValue}>
        {children}
      </PredictiveIdentityContext.Provider>
    </AuthoritativeProjectContext.Provider>
  );
}

export function useAuthoritativeProjectContext() {
  return useContext(AuthoritativeProjectContext);
}

export function usePredictiveIdentity() {
  return useContext(PredictiveIdentityContext);
}

export function ProjectContextGate({ children }: { children: ReactNode }) {
  const { readiness, retry } = useAuthoritativeProjectContext();
  if (readiness.status === "ready") return <>{children}</>;

  const resolving = readiness.status === "idle" || readiness.status === "resolving";
  const unauthorized = readiness.status === "unauthorized";
  const title = resolving
    ? "Loading project context..."
    : readiness.status === "not_found"
      ? "Project unavailable"
      : unauthorized
        ? "Project unauthorized"
        : readiness.status === "workflow_unavailable"
          ? "Workflow state unavailable"
          : readiness.status === "identity_unavailable"
            ? "Active dataset unavailable"
            : readiness.status === "contradictory"
              ? "Project context contradictory"
              : "Project context unavailable";
  const recoveryPath = readiness.status === "identity_unavailable" && readiness.routeProjectId
    ? scopedWorkflowPath(readiness.routeProjectId, "step01")
    : "/projects/open";
  const recoveryLabel = readiness.status === "identity_unavailable"
    ? "Open Data Acquisition"
    : "Open Project";

  return (
    <section
      className={`rounded-xl border p-6 shadow-sm ${
        resolving
          ? "border-blue-200 bg-blue-50 text-blue-950"
          : unauthorized
            ? "border-red-200 bg-red-50 text-red-950"
            : "border-amber-200 bg-amber-50 text-amber-950"
      }`}
      data-testid="project-context-gate"
      data-project-context-status={readiness.status}
      data-route-project-id={readiness.routeProjectId}
      role={resolving ? "status" : "alert"}
    >
      <div className="flex items-start gap-3">
        {resolving ? (
          <Loader2 className="mt-0.5 animate-spin" size={20} />
        ) : unauthorized ? (
          <ShieldAlert className="mt-0.5" size={20} />
        ) : (
          <AlertTriangle className="mt-0.5" size={20} />
        )}
        <div className="min-w-0 flex-1">
          <h1 className="text-base font-semibold">{title}</h1>
          {!resolving ? (
            <p className="mt-2 max-w-3xl text-sm leading-6">{readiness.message}</p>
          ) : null}
          <p className="mt-2 text-xs font-medium">
            Project scope: {readiness.routeProjectId || "not resolved"}
          </p>
          {!resolving ? (
            <div className="mt-4 flex flex-wrap gap-2">
              <Link to={recoveryPath} className="atlas-primary-button">
                {recoveryLabel}
              </Link>
              <button type="button" className="atlas-secondary-button" onClick={retry}>
                <RefreshCw size={15} /> Retry project context
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

export function PredictiveIdentityGate({ children }: { children: ReactNode }) {
  const { readiness, retry } = usePredictiveIdentity();
  if (readiness.status === "ready") return <>{children}</>;

  const loading = readiness.status === "idle" || readiness.status === "loading";
  const unauthorized = readiness.status === "unauthorized";
  const recoverable = ["missing", "stale", "legacy_unresolved", "contradictory"].includes(readiness.status);
  const recoveryPath = readiness.projectId
    ? scopedWorkflowPath(readiness.projectId, "step01")
    : "/projects/open";

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
              <Link to={recoveryPath} className="atlas-primary-button" data-testid="identity-recovery-data-acquisition">
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

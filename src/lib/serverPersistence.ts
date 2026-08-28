import { BASE } from "./api";
import { emitProjectSaveStatus } from "./projectPersistence";
import type { WorkflowProjectSnapshot } from "../state/useWorkflowStore";
import { readStoredOptimizationTemplateId } from "../config/optimizationTemplates";

type JsonRecord = Record<string, unknown>;
const rawEnv = (import.meta as any)?.env ?? {};
const devUserId = rawEnv.DEV ? String(rawEnv.VITE_ATLAS_DEV_USER_ID || "local-dev-user") : "";

export type PersistedRecord = Record<string, any>;

type WorkflowStateSaveResponse = {
  ok?: boolean;
  workflowState?: {
    workflowStatus?: {
      effectiveCompletedSteps?: unknown;
      effectiveSteps?: Record<string, {
        effectiveStatus?: unknown;
        lineageStatus?: unknown;
      }>;
    };
  };
};

export const DURABLE_WORKFLOW_COMPLETION_ERROR =
  "ATLAS could not durably record this workflow step's completion. Retry to continue; this page remains open.";

export type ProjectPersistenceBundle = {
  project: PersistedRecord | null;
  workflowState: PersistedRecord | null;
  evidence: PersistedRecord[];
  runs: PersistedRecord[];
  documentation: PersistedRecord[];
  exports: PersistedRecord[];
  decisions: PersistedRecord[];
};

export class PersistenceHttpError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "PersistenceHttpError";
    this.status = status;
  }
}

export class PersistenceResponseValidationError extends Error {
  readonly code = "invalid_response";

  constructor(message: string) {
    super(message);
    this.name = "PersistenceResponseValidationError";
  }
}

export async function persistenceRequest<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Accept": "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(devUserId ? { "X-ATLAS-USER-ID": devUserId } : {}),
      ...(init.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    throw new PersistenceHttpError(
      response.status,
      payload?.detail ?? payload?.error ?? `ASP Model Studio persistence request failed with HTTP ${response.status}.`
    );
  }
  return payload as T;
}

function emitDatabaseFailure(error: unknown, projectId?: string) {
  const unavailable =
    error instanceof TypeError ||
    (error instanceof PersistenceHttpError && [502, 503, 504].includes(error.status));
  emitProjectSaveStatus({
    status: unavailable ? "backend_unavailable" : "database_save_failed",
    projectId,
    message: unavailable
      ? "The ASP Model Studio database is unavailable. The project remains saved in local browser persistence."
      : error instanceof Error
        ? error.message
            .replace(/\bATLAS project\b/gi, "ASP Model Studio project")
            .replace(/\bATLAS persistence\b/gi, "ASP Model Studio persistence")
            .replace(/\bATLAS database\b/gi, "ASP Model Studio database")
        : "ASP Model Studio could not save this record to the database. Local persistence remains available.",
  });
}

async function mirrorToDatabase(projectId: string | undefined, operation: () => Promise<unknown>) {
  if (!projectId) return false;
  try {
    await operation();
    emitProjectSaveStatus({
      status: "database_saved",
      projectId,
      savedAt: new Date().toISOString(),
      message: "Project state is saved to the local ASP Model Studio database and browser compatibility store.",
    });
    return true;
  } catch (error) {
    emitDatabaseFailure(error, projectId);
    return false;
  }
}

function workflowStatePayload(snapshot: WorkflowProjectSnapshot) {
  const completedSteps = snapshot.workflowSteps
    .filter((step) => step.status === "complete" || step.status === "skipped")
    .map((step) => step.id);
  return {
    currentStepId: snapshot.currentStepId,
    // Browser state may append historical audit completion only. Effective
    // completion is calculated server-side from the durable active selection
    // and exact governed artifacts and is never accepted from this payload.
    historicalCompletedSteps: completedSteps,
    completedSteps,
    workflowStatus: {
      workflowId: snapshot.workflowId,
      projectType: snapshot.projectType,
      steps: Object.fromEntries(snapshot.workflowSteps.map((step) => [step.id, step.status ?? "pending"])),
      hasDataset: Boolean(snapshot.hasDataset),
      datasetIdentity: snapshot.datasetIdentity ?? null,
    },
    stepEvidenceStatus: {},
    updatedAt: new Date().toISOString(),
  };
}

/** Build the exact historical-completion snapshot that must be accepted by
 * the backend before a predictive workflow route is allowed to advance. */
export function workflowCompletionSnapshot(
  snapshot: WorkflowProjectSnapshot,
  completedStepId: string,
  nextStepId?: string,
): WorkflowProjectSnapshot {
  return {
    ...snapshot,
    currentStepId: nextStepId || snapshot.currentStepId,
    workflowSteps: snapshot.workflowSteps.map((step) =>
      step.id === completedStepId
        ? { ...step, status: "complete" as const }
        : step,
    ),
  };
}

/** Persist an exact workflow snapshot and report whether the authoritative
 * project record accepted it. Callers that gate navigation can await this
 * instead of relying on the normal debounced compatibility mirror. */
function responseEffectivelyCompletesStep(
  response: WorkflowStateSaveResponse | null,
  stepId: string,
) {
  const workflowStatus = response?.workflowState?.workflowStatus;
  const completed = Array.isArray(workflowStatus?.effectiveCompletedSteps)
    ? workflowStatus.effectiveCompletedSteps.map((value) => String(value))
    : [];
  const step = workflowStatus?.effectiveSteps?.[stepId];
  return completed.includes(stepId)
    && step?.effectiveStatus === "complete"
    && step?.lineageStatus === "current";
}

export async function saveWorkflowStateToDatabase(
  snapshot: WorkflowProjectSnapshot,
  requiredEffectiveStepId?: string,
) {
  let response: WorkflowStateSaveResponse | null = null;
  const persisted = await mirrorToDatabase(snapshot.projectId, async () => {
    response = await persistenceRequest<WorkflowStateSaveResponse>(
      `/projects/${encodeURIComponent(snapshot.projectId)}/workflow-state`,
      {
        method: "PUT",
        body: JSON.stringify(workflowStatePayload(snapshot)),
      },
    );
  });
  if (!persisted) return false;
  if (
    requiredEffectiveStepId
    && !responseEffectivelyCompletesStep(response, requiredEffectiveStepId)
  ) {
    emitDatabaseFailure(
      new PersistenceResponseValidationError(
        `ATLAS recorded ${requiredEffectiveStepId} as historical activity, but the backend did not verify its current canonical completion evidence.`,
      ),
      snapshot.projectId,
    );
    return false;
  }
  return true;
}

function readOptimizationState(projectId: string) {
  if (typeof localStorage === "undefined") return null;
  try {
    const parsed = JSON.parse(localStorage.getItem(`atlas-optimization-transportation:${projectId}`) || "null");
    return parsed && typeof parsed === "object" ? parsed as JsonRecord : null;
  } catch {
    return null;
  }
}

function optimizationTemplateId(snapshot: WorkflowProjectSnapshot) {
  if (snapshot.projectType !== "optimization") return undefined;
  return snapshot.templateId || readStoredOptimizationTemplateId(snapshot.projectId);
}

export async function saveProjectToDatabase(snapshot: WorkflowProjectSnapshot, additionalMetadata: JsonRecord = {}) {
  return mirrorToDatabase(snapshot.projectId, async () => {
    const updatedAt = new Date().toISOString();
    const templateId = optimizationTemplateId(snapshot);
    const optimizationState = templateId === "transportation_logistics" ? readOptimizationState(snapshot.projectId) : null;
    await persistenceRequest(`/projects/${encodeURIComponent(snapshot.projectId)}`, {
      method: "PUT",
      body: JSON.stringify({
        projectName: snapshot.projectName,
        projectType: snapshot.projectType,
        workflowType: snapshot.workflowId,
        templateId,
        status: "active",
        updatedAt,
        metadata: {
          modelId: snapshot.modelId,
          hasDataset: Boolean(snapshot.hasDataset),
          projectTools: snapshot.projectTools ?? {},
          compatibilityStore: "browser_local_persistence",
          ...additionalMetadata,
          ...(optimizationState ? { optimizationState } : {}),
        },
      }),
    });
    await persistenceRequest(`/projects/${encodeURIComponent(snapshot.projectId)}/workflow-state`, {
      method: "PUT",
      body: JSON.stringify(workflowStatePayload(snapshot)),
    });
  });
}

const optimizationStateTimers = new Map<string, ReturnType<typeof setTimeout>>();

export function queueOptimizationStateDatabaseSave(
  projectId: string,
  state: JsonRecord,
  options: { projectName?: string; delayMs?: number } = {},
) {
  const existing = optimizationStateTimers.get(projectId);
  if (existing) clearTimeout(existing);
  optimizationStateTimers.set(projectId, setTimeout(() => {
    optimizationStateTimers.delete(projectId);
    void mirrorToDatabase(projectId, () => persistenceRequest(`/projects/${encodeURIComponent(projectId)}`, {
      method: "PUT",
      body: JSON.stringify({
        projectName: options.projectName,
        projectType: "optimization",
        workflowType: "optimization",
        templateId: "transportation_logistics",
        metadata: {
          optimizationState: state,
          optimizationStateSavedAt: new Date().toISOString(),
        },
      }),
    }));
  }, options.delayMs ?? 500));
}

export async function saveProjectTemplateToDatabase(projectId: string, templateId: string) {
  return mirrorToDatabase(projectId, () => persistenceRequest(`/projects/${encodeURIComponent(projectId)}`, {
    method: "PUT",
    body: JSON.stringify({
      projectType: "optimization",
      workflowType: "optimization",
      templateId,
      metadata: {
        optimizationTemplateId: templateId,
        optimizationState: null,
        optimizationStateInvalidatedAt: new Date().toISOString(),
      },
    }),
  }));
}

/** Persist the compact, structured Project Context separately from governed dataset artifacts. */
export async function savePredictiveProjectContextToDatabase(
  projectId: string,
  input: { projectName: string; modelId: string; projectContext: JsonRecord; validationStatus: string },
) {
  return mirrorToDatabase(projectId, () => persistenceRequest(`/projects/${encodeURIComponent(projectId)}`, {
    method: "PUT",
    body: JSON.stringify({
      projectName: input.projectName || "Untitled ATLAS Project",
      projectType: "predictive-modeling",
      workflowType: "predictive-modeling",
      metadata: {
        modelId: input.modelId,
        projectContext: input.projectContext,
        projectContextValidationStatus: input.validationStatus,
        projectContextSavedAt: new Date().toISOString(),
      },
    }),
  }));
}

const projectSaveTimers = new Map<string, ReturnType<typeof setTimeout>>();
const queuedSnapshots = new Map<string, WorkflowProjectSnapshot>();

export function queueProjectDatabaseSave(snapshot: WorkflowProjectSnapshot, delayMs = 220) {
  queuedSnapshots.set(snapshot.projectId, snapshot);
  const existing = projectSaveTimers.get(snapshot.projectId);
  if (existing) clearTimeout(existing);
  projectSaveTimers.set(
    snapshot.projectId,
    setTimeout(() => {
      projectSaveTimers.delete(snapshot.projectId);
      const queued = queuedSnapshots.get(snapshot.projectId);
      queuedSnapshots.delete(snapshot.projectId);
      if (queued) void saveProjectToDatabase(queued);
    }, delayMs)
  );
}

/**
 * Persist one exact project snapshot before a route starts reading project-scoped
 * backend authority. This drains the normal debounce for the same canonical ID,
 * so creation/reopen cannot race its own deferred mirror.
 */
export async function flushProjectDatabaseSave(snapshot: WorkflowProjectSnapshot, additionalMetadata: JsonRecord = {}) {
  const existing = projectSaveTimers.get(snapshot.projectId);
  if (existing) clearTimeout(existing);
  projectSaveTimers.delete(snapshot.projectId);
  queuedSnapshots.delete(snapshot.projectId);
  return saveProjectToDatabase(snapshot, additionalMetadata);
}

export async function saveEvidenceToDatabase(projectId: string | undefined, evidence: JsonRecord) {
  return mirrorToDatabase(projectId, () =>
    persistenceRequest(`/projects/${encodeURIComponent(projectId ?? "")}/evidence`, {
      method: "POST",
      body: JSON.stringify(evidence),
    })
  );
}

export async function saveRunToDatabase(projectId: string | undefined, run: JsonRecord) {
  return mirrorToDatabase(projectId, () =>
    persistenceRequest(`/projects/${encodeURIComponent(projectId ?? "")}/runs`, {
      method: "POST",
      body: JSON.stringify(run),
    })
  );
}

export async function updateEvidenceInDatabase(projectId: string | undefined, evidenceId: string, evidence: JsonRecord) {
  return mirrorToDatabase(projectId, () =>
    persistenceRequest(
      `/projects/${encodeURIComponent(projectId ?? "")}/evidence/${encodeURIComponent(evidenceId)}`,
      { method: "PUT", body: JSON.stringify(evidence) }
    )
  );
}

export async function saveDocumentationToDatabase(projectId: string | undefined, document: JsonRecord) {
  const sections = Array.isArray(document.sections) ? document.sections as JsonRecord[] : [];
  const completed = sections.filter((section) => ["complete", "ready_for_review"].includes(String(section.status))).length;
  const quality = (document.quality ?? {}) as JsonRecord;
  return mirrorToDatabase(projectId, () =>
    persistenceRequest(`/projects/${encodeURIComponent(projectId ?? "")}/documentation`, {
      method: "POST",
      body: JSON.stringify({
        packageId: document.documentId,
        packageType: document.templateType,
        status: quality.exportReady ? "ready" : "draft",
        readinessScore: quality.completionPct,
        sectionCount: sections.length,
        completedSectionCount: completed,
        createdAt: document.createdAt,
        updatedAt: document.updatedAt,
        payload: document,
      }),
    })
  );
}

export async function saveDocumentationPackageToDatabase(
  projectId: string | undefined,
  document: {
    packageId: string;
    packageType: string;
    status: "draft" | "ready" | "complete";
    readinessScore: number;
    sectionCount: number;
    completedSectionCount: number;
    payload: JsonRecord;
    createdAt?: string;
    updatedAt?: string;
  },
) {
  return mirrorToDatabase(projectId, () =>
    persistenceRequest(`/projects/${encodeURIComponent(projectId ?? "")}/documentation`, {
      method: "POST",
      body: JSON.stringify(document),
    })
  );
}

export async function saveExportToDatabase(
  projectId: string | undefined,
  input: { exportId?: string; exportType: string; fileName: string; filePath?: string; artifactHash?: string; metadata?: JsonRecord }
) {
  return mirrorToDatabase(projectId, () =>
    persistenceRequest(`/projects/${encodeURIComponent(projectId ?? "")}/exports`, {
      method: "POST",
      body: JSON.stringify({
        ...input,
        createdAt: new Date().toISOString(),
      }),
    })
  );
}

export async function saveDecisionToDatabase(projectId: string | undefined, decision: JsonRecord) {
  return mirrorToDatabase(projectId, () =>
    persistenceRequest(`/projects/${encodeURIComponent(projectId ?? "")}/decisions`, {
      method: "POST",
      body: JSON.stringify(decision),
    })
  );
}

export async function saveDemoFeedbackToDatabase(feedback: JsonRecord) {
  return persistenceRequest<{ ok: boolean; feedback: PersistedRecord }>("/demo-feedback", {
    method: "POST",
    body: JSON.stringify(feedback),
  });
}

export async function getPersistenceHealth() {
  try {
    return await persistenceRequest<{ ok: boolean; status: string; databasePath: string }>("/persistence/health", { method: "GET" });
  } catch {
    return null;
  }
}

export async function getProjectFromDatabase(projectId: string, signal?: AbortSignal) {
  const payload = await persistenceRequest<{ ok: boolean; project: PersistedRecord }>(
    `/projects/${encodeURIComponent(projectId)}`,
    { method: "GET", signal },
  );
  return payload.project;
}

export async function listProjectsFromDatabase(signal?: AbortSignal) {
  const payload = await persistenceRequest<{ ok: boolean; projects: PersistedRecord[] }>("/projects", { method: "GET", signal });
  if (!payload || !Array.isArray(payload.projects)) {
    throw new PersistenceResponseValidationError(
      "The project registry returned an invalid response: expected a projects array.",
    );
  }
  return payload.projects;
}

export async function getProjectWorkflowStateFromDatabase(projectId: string, signal?: AbortSignal) {
  try {
    const payload = await persistenceRequest<{ ok: boolean; workflowState: PersistedRecord | null }>(
      `/projects/${encodeURIComponent(projectId)}/workflow-state`,
      { method: "GET", signal },
    );
    return payload.workflowState ?? null;
  } catch (error) {
    if (error instanceof PersistenceHttpError && error.status === 404) return null;
    throw error;
  }
}

/**
 * Read the exact durable project-scoped Dataset Library activation. This is a
 * GET-only authority lookup; callers must never turn a missing response into a
 * first/latest-version selection or an implicit activation.
 */
export async function getActiveDatasetIdentityFromDatabase(projectId: string, signal?: AbortSignal) {
  return persistenceRequest<PersistedRecord>(
    `/data/active-identity?project_id=${encodeURIComponent(projectId)}`,
    { method: "GET", signal },
  );
}

export async function deleteProjectFromDatabase(projectId: string) {
  return persistenceRequest<{ ok: boolean; projectId: string; deleted: boolean }>(
    `/projects/${encodeURIComponent(projectId)}`,
    { method: "DELETE" },
  );
}

export async function getProjectPersistenceBundle(projectId: string): Promise<ProjectPersistenceBundle> {
  const encoded = encodeURIComponent(projectId);
  async function safe<T>(path: string, key: string, fallback: T): Promise<T> {
    try {
      const payload = await persistenceRequest<Record<string, any>>(path, { method: "GET" });
      return (payload[key] ?? fallback) as T;
    } catch (error) {
      if (error instanceof PersistenceHttpError && error.status === 404) return fallback;
      throw error;
    }
  }
  const [project, workflowState, evidence, runs, documentation, exports, decisions] = await Promise.all([
    safe<PersistedRecord | null>(`/projects/${encoded}`, "project", null),
    safe<PersistedRecord | null>(`/projects/${encoded}/workflow-state`, "workflowState", null),
    safe<PersistedRecord[]>(`/projects/${encoded}/evidence`, "evidence", []),
    safe<PersistedRecord[]>(`/projects/${encoded}/runs`, "runs", []),
    safe<PersistedRecord[]>(`/projects/${encoded}/documentation`, "documentation", []),
    safe<PersistedRecord[]>(`/projects/${encoded}/exports`, "exports", []),
    safe<PersistedRecord[]>(`/projects/${encoded}/decisions`, "decisions", []),
  ]);
  return { project, workflowState, evidence, runs, documentation, exports, decisions };
}

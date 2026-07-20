import { BASE } from "./api";
import { emitProjectSaveStatus } from "./projectPersistence";
import type { WorkflowProjectSnapshot } from "../state/useWorkflowStore";
import { readStoredOptimizationTemplateId } from "../config/optimizationTemplates";

type JsonRecord = Record<string, unknown>;
const rawEnv = (import.meta as any)?.env ?? {};
const devUserId = rawEnv.DEV ? String(rawEnv.VITE_ATLAS_DEV_USER_ID || "local-dev-user") : "";

export type PersistedRecord = Record<string, any>;

export type ProjectPersistenceBundle = {
  project: PersistedRecord | null;
  workflowState: PersistedRecord | null;
  evidence: PersistedRecord[];
  runs: PersistedRecord[];
  documentation: PersistedRecord[];
  exports: PersistedRecord[];
  decisions: PersistedRecord[];
};

class PersistenceHttpError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
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
      payload?.detail ?? payload?.error ?? `ATLAS persistence request failed with HTTP ${response.status}.`
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
      ? "ATLAS database is unavailable. The project remains saved in local browser persistence."
      : error instanceof Error
        ? error.message
        : "ATLAS could not save this record to the database. Local persistence remains available.",
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
      message: "Project state is saved to the ATLAS SQLite database and the local compatibility store.",
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
    completedSteps,
    workflowStatus: {
      workflowId: snapshot.workflowId,
      projectType: snapshot.projectType,
      steps: Object.fromEntries(snapshot.workflowSteps.map((step) => [step.id, step.status ?? "pending"])),
      hasDataset: Boolean(snapshot.hasDataset),
    },
    stepEvidenceStatus: {},
    updatedAt: new Date().toISOString(),
  };
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

export async function saveProjectToDatabase(snapshot: WorkflowProjectSnapshot) {
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

export async function getProjectFromDatabase(projectId: string) {
  const payload = await persistenceRequest<{ ok: boolean; project: PersistedRecord }>(
    `/projects/${encodeURIComponent(projectId)}`,
    { method: "GET" },
  );
  return payload.project;
}

export async function listProjectsFromDatabase() {
  const payload = await persistenceRequest<{ ok: boolean; projects: PersistedRecord[] }>("/projects", { method: "GET" });
  return payload.projects;
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

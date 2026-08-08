import { getWorkflowDefinition, getWorkflowForProjectType, type ProjectType, type WorkflowStep } from "../config/workflows";
import type { WorkflowProjectSnapshot } from "../state/useWorkflowStore";
import {
  attachPersistedProjectState,
  compactProjectForStorage,
  emitProjectSaveStatus,
  estimateBytes,
  projectPersistenceDebug,
  restoreProjectSnapshotArtifacts,
  thinProjectForStorage,
} from "./projectPersistence";
import { validateProjectImport } from "./projectImportValidation";
import { queueProjectDatabaseSave } from "./serverPersistence";
import { clearProjectDatasetEverywhere } from "./localDataset";
import { normalizeWorkflowRoute } from "./projectScopedRoutes";

export const LOCAL_PROJECTS_KEY = "atlas-local-projects";
export const PROJECT_SNAPSHOT_KEY_PREFIX = "atlas-project-snapshot:";
const PROJECT_SCOPED_STORAGE_PREFIXES = ["atlas-workflow-node-state:"];
const RECENT_PROJECTS_REGISTRY_BUDGET_BYTES = 100 * 1024;
const PROJECT_REGISTRY_ENTRY_BUDGET_BYTES = 5 * 1024;
const COMPACT_PROJECT_SNAPSHOT_TARGET_BYTES = 150 * 1024;
const THIN_PROJECT_SNAPSHOT_BUDGET_BYTES = 50 * 1024;
const SAFE_COMPACTION_KEY_PATTERNS = [
  /^atlas-local-projects-corrupt-backup-/,
  /^atlas-project-snapshot:/,
  /^atlas-workflow-node-state:[^:]+:/,
  /^modeling-tool-decision-journal$/,
  /^modeling-tool-mlflow-lite-experiments$/,
];

let volatileProjectRegistry: LocalProjectRegistryRecord[] = [];
let lastRegistryWriteError = "";

export function clearVolatileProjectRegistryForTests() {
  volatileProjectRegistry = [];
  lastRegistryWriteError = "";
}

export type LocalProjectRecord = {
  projectId: string;
  modelId?: string;
  projectName: string;
  projectType: ProjectType;
  workflowId: string;
  createdAt: string;
  lastModified: string;
  source?: "browser" | "imported" | "database";
  backendMetadata?: Record<string, unknown>;
  snapshotStorageKey?: string;
  restoreStatus?: string;
  snapshot: WorkflowProjectSnapshot;
};

type LocalProjectRegistryRecord = Omit<LocalProjectRecord, "snapshot"> & {
  snapshot?: WorkflowProjectSnapshot;
  completedSteps?: string[];
  currentStep?: string;
};

type CurrentWorkflowState = WorkflowProjectSnapshot & {
  projectTools?: WorkflowProjectSnapshot["projectTools"];
};

export type LocalProjectsRegistryStatus = {
  ok: boolean;
  corrupted: boolean;
  message: string;
  projectCount: number;
  validProjects: LocalProjectRecord[];
  volatileFallback?: boolean;
  lastWriteError?: string;
};

export type SafeStorageWriteResult = {
  ok: boolean;
  key: string;
  bytes: number;
  errorName?: string;
  errorMessage?: string;
  quotaExceeded?: boolean;
};

function nowIso() {
  return new Date().toISOString();
}

function newProjectId() {
  return `atlas-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function safeJsonParse(raw: string | null) {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function safeSetLocalStorage(key: string, value: string, options: { replaceExisting?: boolean } = {}): SafeStorageWriteResult {
  const bytes = estimateBytes(value);
  try {
    if (typeof localStorage === "undefined") {
      return { ok: false, key, bytes, errorName: "StorageUnavailable", errorMessage: "Browser localStorage is unavailable." };
    }
    if (options.replaceExisting) localStorage.removeItem(key);
    localStorage.setItem(key, value);
    return { ok: true, key, bytes };
  } catch (error) {
    const name = error instanceof Error ? error.name : "StorageError";
    const message = error instanceof Error ? error.message : "Browser storage write failed.";
    return {
      ok: false,
      key,
      bytes,
      errorName: name,
      errorMessage: message,
      quotaExceeded: /quota|exceeded|storage/i.test(`${name} ${message}`),
    };
  }
}

function projectSnapshotKey(projectId: string) {
  return `${PROJECT_SNAPSHOT_KEY_PREFIX}${projectId}`;
}

function workflowStepSummary(steps: WorkflowStep[]) {
  return steps
    .filter((step) => step.status === "complete" || step.status === "skipped")
    .map((step) => step.id);
}

function minimalSnapshot(snapshot: WorkflowProjectSnapshot): WorkflowProjectSnapshot {
  const workflow = workflowFromProjectType(snapshot.projectType, snapshot.workflowId);
  const persistedById = new Map((snapshot.workflowSteps ?? []).map((step) => [step.id, step]));
  return {
    projectId: snapshot.projectId,
    modelId: snapshot.modelId ?? "",
    projectName: snapshot.projectName?.trim() || "Untitled ATLAS Project",
    projectType: snapshot.projectType,
    workflowId: snapshot.workflowId || workflow.id,
    workflowSteps: workflow.steps.map((step) => ({
      ...step,
      status: persistedById.get(step.id)?.status ?? step.status ?? "pending",
    })),
    currentStepId: snapshot.currentStepId || workflow.steps[0]?.id || "step00",
    hasDataset: Boolean(snapshot.hasDataset),
    datasetIdentity: snapshot.datasetIdentity ?? null,
    projectTools: snapshot.projectTools,
    restoreWarnings: snapshot.restoreWarnings,
  };
}

function snapshotForProjectStorage(snapshot: WorkflowProjectSnapshot) {
  const compacted = compactProjectForStorage({ snapshot }).snapshot;
  if (estimateBytes(compacted) <= COMPACT_PROJECT_SNAPSHOT_TARGET_BYTES) return compacted;
  const thin = thinProjectForStorage({ snapshot: compacted }).snapshot;
  if (estimateBytes(thin) <= THIN_PROJECT_SNAPSHOT_BUDGET_BYTES) return thin;
  return minimalSnapshot(snapshot);
}

function trySetStorageItem(key: string, value: string, replaceExisting = false) {
  return safeSetLocalStorage(key, value, { replaceExisting }).ok;
}

function writeProjectSnapshot(snapshot: WorkflowProjectSnapshot) {
  const key = projectSnapshotKey(snapshot.projectId);
  const snapshotToStore = snapshotForProjectStorage(snapshot);
  if (trySetStorageItem(key, JSON.stringify(snapshotToStore))) {
    return { key, snapshot: snapshotToStore, thinned: snapshotToStore !== snapshot, persisted: true };
  }

  const fallback = minimalSnapshot(snapshot);
  if (trySetStorageItem(key, JSON.stringify(fallback), true)) {
    return { key, snapshot: fallback, thinned: true, persisted: true };
  }

  localStorage.removeItem(key);
  return { key: "", snapshot: fallback, thinned: true, persisted: false };
}

function readProjectSnapshot(projectId: string, fallback?: WorkflowProjectSnapshot) {
  if (typeof localStorage === "undefined") return fallback;
  const stored = safeJsonParse(localStorage.getItem(projectSnapshotKey(projectId))) as WorkflowProjectSnapshot | null;
  return stored?.projectId ? stored : fallback;
}

function registryRecordFromProject(project: LocalProjectRecord): LocalProjectRegistryRecord {
  const completedSteps = workflowStepSummary(project.snapshot.workflowSteps ?? []);
  const record: LocalProjectRegistryRecord = {
    projectId: project.projectId,
    modelId: project.modelId,
    projectName: project.projectName,
    projectType: project.projectType,
    workflowId: project.workflowId,
    createdAt: project.createdAt,
    lastModified: project.lastModified,
    source: project.source,
    snapshotStorageKey: project.snapshotStorageKey,
    completedSteps,
    currentStep: project.snapshot.currentStepId,
    restoreStatus: project.restoreStatus ?? (project.snapshot.persistedLocalState ? "compact_snapshot_available" : "workflow_progress_only"),
  };
  if (estimateBytes(record) <= PROJECT_REGISTRY_ENTRY_BUDGET_BYTES) return record;
  return {
    ...record,
    completedSteps: completedSteps.slice(-12),
  };
}

function hydrateRegistryRecord(project: LocalProjectRegistryRecord): LocalProjectRecord | null {
  if (!project?.projectId || !project?.projectName) return null;
  const snapshot = readProjectSnapshot(project.projectId, project.snapshot);
  if (!snapshot?.projectId) return null;
  return {
    projectId: project.projectId,
    modelId: project.modelId ?? snapshot.modelId,
    projectName: project.projectName,
    projectType: project.projectType ?? snapshot.projectType,
    workflowId: project.workflowId ?? snapshot.workflowId,
    createdAt: project.createdAt,
    lastModified: project.lastModified,
    source: project.source,
    snapshotStorageKey: project.snapshotStorageKey ?? projectSnapshotKey(project.projectId),
    restoreStatus: project.restoreStatus,
    snapshot,
  };
}

function parseProjects(raw: string | null): LocalProjectRecord[] {
  return parseProjectsDetailed(raw).projects;
}

function parseProjectsDetailed(raw: string | null): { projects: LocalProjectRecord[]; corrupted: boolean; message: string } {
  if (!raw) {
    return {
      projects: [],
      corrupted: false,
      message: "No Recent Projects registry exists yet.",
    };
  }
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return {
        projects: [],
        corrupted: true,
        message: "Recent Projects registry is not a valid project list.",
      };
    }
    const projects = parsed
      .map((project: LocalProjectRegistryRecord) => hydrateRegistryRecord(project))
      .filter((project): project is LocalProjectRecord => Boolean(project));
    return {
      projects,
      corrupted: projects.length !== parsed.length,
      message:
        projects.length !== parsed.length
          ? "Recent Projects registry contains invalid records. Valid projects can be repaired."
          : "Recent Projects registry is valid.",
    };
  } catch {
    return {
      projects: [],
      corrupted: true,
      message: "Recent Projects registry contains invalid JSON. Use Repair Recent Projects to rebuild the index.",
    };
  }
}

function projectScopedPrefix(prefix: string, projectId: string) {
  return `${prefix}${projectId}:`;
}

function copyProjectScopedStorage(sourceProjectId: string, targetProjectId: string) {
  if (typeof localStorage === "undefined") return;
  for (const prefix of PROJECT_SCOPED_STORAGE_PREFIXES) {
    const sourcePrefix = projectScopedPrefix(prefix, sourceProjectId);
    const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).filter(
      (key): key is string => Boolean(key?.startsWith(sourcePrefix))
    );
    for (const key of keys) {
      const value = localStorage.getItem(key);
      if (value == null) continue;
      localStorage.setItem(`${projectScopedPrefix(prefix, targetProjectId)}${key.slice(sourcePrefix.length)}`, value);
    }
  }
}

function deleteProjectScopedStorage(projectId: string) {
  // Dataset browser cache lives in sessionStorage under a separate (user,
  // project)-scoped key format (src/lib/localDataset.ts) -- swept here too,
  // for every user, so a deleted project's cached rows/headers/target can
  // never resurface (Predictive Modeling Repair Stage 6.2).
  clearProjectDatasetEverywhere(projectId);
  if (typeof localStorage === "undefined") return;
  for (const prefix of PROJECT_SCOPED_STORAGE_PREFIXES) {
    const scopedPrefix = projectScopedPrefix(prefix, projectId);
    const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).filter(
      (key): key is string => Boolean(key?.startsWith(scopedPrefix))
    );
    keys.forEach((key) => localStorage.removeItem(key));
  }
  localStorage.removeItem(projectSnapshotKey(projectId));
}

function inferProjectType(value: unknown): ProjectType {
  const text = JSON.stringify(value ?? {}).toLowerCase();
  if (text.includes("experimental-design") || text.includes("experimental design") || text.includes("anova") || text.includes("monte carlo")) return "experimental-design";
  return "predictive-modeling";
}

function workflowFromProjectType(projectType: ProjectType, workflowId?: string) {
  try {
    return getWorkflowDefinition(workflowId || getWorkflowForProjectType(projectType).id);
  } catch {
    return getWorkflowForProjectType(projectType);
  }
}

function projectIdsFromWorkflowEvidence() {
  if (typeof localStorage === "undefined") return [];
  const ids = new Set<string>();
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index) ?? "";
    const match = key.match(/^atlas-workflow-node-state:([^:]+):/);
    if (match?.[1]) ids.add(match[1]);
  }
  return Array.from(ids);
}

function evidenceForProject(projectId: string) {
  if (typeof localStorage === "undefined") return [];
  const evidence: Array<{ stepId: string; state: Record<string, unknown> }> = [];
  const prefix = `atlas-workflow-node-state:${projectId}:`;
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index) ?? "";
    if (!key.startsWith(prefix)) continue;
    const state = safeJsonParse(localStorage.getItem(key));
    if (state && typeof state === "object") evidence.push({ stepId: key.slice(prefix.length), state });
  }
  return evidence;
}

function hasSubstantiveEvidence(evidence: Array<{ state: Record<string, unknown> }>) {
  return evidence.some(({ state }) =>
    ["objective", "method", "decision", "rationale", "notes", "metrics"].some((field) => {
      const value = state[field];
      if (Array.isArray(value)) return value.length > 0;
      return typeof value === "string" ? Boolean(value.trim()) : Boolean(value);
    })
  );
}

function snapshotFromLegacyPersisted(candidate: any): WorkflowProjectSnapshot | null {
  const state = candidate?.state ?? candidate;
  if (!state || typeof state !== "object") return null;
  const projectType = inferProjectType(state);
  const workflow = workflowFromProjectType(projectType, state.workflowId);
  const snapshot: WorkflowProjectSnapshot = {
    projectId: state.projectId || newProjectId(),
    modelId: state.modelId ?? "",
    projectName: state.projectName || (projectType === "experimental-design" ? "Recovered Experimental Design Project" : "Recovered ATLAS Project"),
    projectType,
    workflowId: state.workflowId || workflow.id,
    workflowSteps: Array.isArray(state.workflowSteps) && state.workflowSteps.length ? state.workflowSteps : workflow.steps,
    currentStepId: state.currentStepId || workflow.steps[0]?.id || "step00",
    hasDataset: Boolean(state.hasDataset),
    datasetIdentity: state.datasetIdentity ?? null,
    projectTools: state.projectTools,
  };
  return isMeaningfulProjectSnapshot(snapshot) ? snapshot : null;
}

function snapshotFromEvidence(projectId: string): WorkflowProjectSnapshot | null {
  const evidence = evidenceForProject(projectId);
  if (!hasSubstantiveEvidence(evidence)) return null;
  const projectType = inferProjectType(evidence);
  const workflow = workflowFromProjectType(projectType);
  const completedIds = new Set(evidence.map((row) => row.stepId));
  return {
    projectId,
    modelId: "",
    projectName: projectType === "experimental-design" ? "Recovered Experimental Design Project" : "Recovered ATLAS Project",
    projectType,
    workflowId: workflow.id,
    workflowSteps: workflow.steps.map((step) => ({ ...step, status: completedIds.has(step.id) ? "complete" : step.status ?? "pending" })),
    currentStepId: workflow.steps.find((step) => !completedIds.has(step.id))?.id || workflow.steps[0]?.id || "step00",
    hasDataset: false,
  };
}

export function migrateLegacyLocalProjects() {
  if (typeof localStorage === "undefined") return { migrated: 0, recoveredExperimentalDesign: false };
  const existing = loadLocalProjects();
  const existingIds = new Set(existing.map((project) => project.projectId));
  const snapshots: WorkflowProjectSnapshot[] = [];

  const legacyStore = safeJsonParse(localStorage.getItem("ds-workflow-store"));
  const currentSnapshot = snapshotFromLegacyPersisted(legacyStore);
  if (currentSnapshot && !existingIds.has(currentSnapshot.projectId)) snapshots.push(currentSnapshot);

  for (const projectId of projectIdsFromWorkflowEvidence()) {
    if (existingIds.has(projectId) || snapshots.some((snapshot) => snapshot.projectId === projectId)) continue;
    const evidenceSnapshot = snapshotFromEvidence(projectId);
    if (evidenceSnapshot) snapshots.push(evidenceSnapshot);
  }

  snapshots.forEach((snapshot) => upsertProjectSnapshot(snapshot, "browser"));
  return {
    migrated: snapshots.length,
    recoveredExperimentalDesign: snapshots.some((snapshot) => snapshot.projectType === "experimental-design"),
  };
}

export function loadLocalProjects(): LocalProjectRecord[] {
  if (typeof localStorage === "undefined") return [];
  const persisted = parseProjects(localStorage.getItem(LOCAL_PROJECTS_KEY));
  const volatile = volatileProjectRegistry
    .map((project) => hydrateRegistryRecord(project))
    .filter((project): project is LocalProjectRecord => Boolean(project));
  const byId = new Map<string, LocalProjectRecord>();
  [...persisted, ...volatile].forEach((project) => byId.set(project.projectId, project));
  return Array.from(byId.values()).sort((a, b) => b.lastModified.localeCompare(a.lastModified));
}

export function getLocalProjectsRegistryStatus(): LocalProjectsRegistryStatus {
  if (typeof localStorage === "undefined") {
    return {
      ok: true,
      corrupted: false,
      message: "Browser storage is unavailable in this environment.",
      projectCount: 0,
      validProjects: [],
    };
  }
  const parsed = parseProjectsDetailed(localStorage.getItem(LOCAL_PROJECTS_KEY));
  const validProjects = parsed.projects.sort((a, b) => b.lastModified.localeCompare(a.lastModified));
  const fallbackProjects = volatileProjectRegistry
    .map((project) => hydrateRegistryRecord(project))
    .filter((project): project is LocalProjectRecord => Boolean(project));
  const merged = validProjects.length ? validProjects : fallbackProjects;
  return {
    ok: !parsed.corrupted && !lastRegistryWriteError,
    corrupted: parsed.corrupted,
    message: lastRegistryWriteError
      ? `Recent Projects is using an in-session recovery index because browser storage rejected the registry write: ${lastRegistryWriteError}`
      : parsed.message,
    projectCount: merged.length,
    validProjects: merged,
    volatileFallback: Boolean(lastRegistryWriteError && fallbackProjects.length),
    lastWriteError: lastRegistryWriteError,
  };
}

export function repairLocalProjectsRegistry() {
  if (typeof localStorage === "undefined") {
    return { projects: [] as LocalProjectRecord[], repaired: false, message: "Browser storage is unavailable." };
  }
  const raw = localStorage.getItem(LOCAL_PROJECTS_KEY);
  const parsed = parseProjectsDetailed(raw);
  if (parsed.corrupted && raw) {
    localStorage.setItem(`${LOCAL_PROJECTS_KEY}-corrupt-backup-${Date.now()}`, raw);
  }
  saveLocalProjects(parsed.projects);
  const migration = migrateLegacyLocalProjects();
  const projects = loadLocalProjects();
  return {
    projects,
    repaired: parsed.corrupted || migration.migrated > 0,
    message: parsed.corrupted
      ? `Recent Projects index repaired. ${projects.length} valid project${projects.length === 1 ? "" : "s"} available.`
      : `Recent Projects index checked. ${migration.migrated} legacy project${migration.migrated === 1 ? "" : "s"} recovered.`,
  };
}

export function saveLocalProjects(projects: LocalProjectRecord[]) {
  if (typeof localStorage === "undefined") return;
  const registry = projects.map((project) => {
    const snapshotResult = writeProjectSnapshot(project.snapshot);
    const record = registryRecordFromProject({
      ...project,
      snapshot: snapshotResult.snapshot,
      snapshotStorageKey: snapshotResult.persisted ? snapshotResult.key : undefined,
      restoreStatus: snapshotResult.persisted
        ? snapshotResult.thinned
          ? "thin_snapshot_available"
          : project.restoreStatus
        : "inline_minimal_snapshot",
    });
    if (!snapshotResult.persisted) {
      return {
        ...record,
        snapshot: snapshotResult.snapshot,
        snapshotStorageKey: undefined,
        restoreStatus: "inline_minimal_snapshot",
      };
    }
    return record;
  });
  const registryToPersist =
    estimateBytes(registry) <= RECENT_PROJECTS_REGISTRY_BUDGET_BYTES
      ? registry
      : registry.map((record) => ({
          projectId: record.projectId,
          modelId: record.modelId,
          projectName: record.projectName,
          projectType: record.projectType,
          workflowId: record.workflowId,
          createdAt: record.createdAt,
          lastModified: record.lastModified,
          source: record.source,
          snapshotStorageKey: record.snapshotStorageKey,
          snapshot: record.snapshotStorageKey ? undefined : record.snapshot,
          currentStep: record.currentStep,
          completedSteps: record.completedSteps?.slice(-12),
          restoreStatus: record.restoreStatus ?? "snapshot_reference_only",
        }));
  try {
    const registryJson = JSON.stringify(registryToPersist);
    if (!trySetStorageItem(LOCAL_PROJECTS_KEY, registryJson) && !trySetStorageItem(LOCAL_PROJECTS_KEY, registryJson, true)) {
      throw new Error("Browser storage quota exceeded while saving the Recent Projects index.");
    }
    volatileProjectRegistry = [];
    lastRegistryWriteError = "";
  } catch (error) {
    const compacted = registryToPersist.map((record) => ({
      projectId: record.projectId,
      modelId: record.modelId,
      projectName: record.projectName,
      projectType: record.projectType,
      workflowId: record.workflowId,
      createdAt: record.createdAt,
      lastModified: record.lastModified,
      source: record.source,
      snapshotStorageKey: record.snapshotStorageKey,
      snapshot: record.snapshotStorageKey ? undefined : record.snapshot,
      currentStep: record.currentStep,
      completedSteps: [],
      restoreStatus: "snapshot_reference_only",
    }));
    try {
      const compactedJson = JSON.stringify(compacted);
      if (!trySetStorageItem(LOCAL_PROJECTS_KEY, compactedJson) && !trySetStorageItem(LOCAL_PROJECTS_KEY, compactedJson, true)) {
        throw new Error("Browser storage quota exceeded while saving the compact Recent Projects index.");
      }
    } catch (compactError) {
      const thin = compacted.slice(0, 30);
      try {
        const thinJson = JSON.stringify(thin);
        if (!trySetStorageItem(LOCAL_PROJECTS_KEY, thinJson) && !trySetStorageItem(LOCAL_PROJECTS_KEY, thinJson, true)) {
          throw new Error("Browser storage quota exceeded while saving the thin Recent Projects index.");
        }
        volatileProjectRegistry = [];
        lastRegistryWriteError = "";
      } catch {
        volatileProjectRegistry = thin;
        lastRegistryWriteError = `Browser storage quota exceeded while saving the Recent Projects index. Registry size was ${Math.round(estimateBytes(registryToPersist) / 1024).toLocaleString()} KB; compacted size was ${Math.round(estimateBytes(compacted) / 1024).toLocaleString()} KB.`;
        console.warn("ATLAS is using an in-session Recent Projects recovery index", lastRegistryWriteError);
        return;
      }
      if (compactError instanceof Error) {
        console.warn("ATLAS saved thin project registry after compact snapshot exceeded storage quota", compactError.message);
      }
    }
    if (error instanceof Error) {
      console.warn("ATLAS compacted project registry after storage warning", error.message);
    }
  }
}

export function workflowLabel(projectType: ProjectType, workflowId?: string) {
  try {
    return getWorkflowDefinition(workflowId || getWorkflowForProjectType(projectType).id).label;
  } catch {
    return getWorkflowForProjectType(projectType).label;
  }
}

export function createSnapshotFromState(state: CurrentWorkflowState): WorkflowProjectSnapshot {
  const workflow = getWorkflowDefinition(state.workflowId || getWorkflowForProjectType(state.projectType).id);
  const currentStepId = resolveCurrentBrowserStepId(state, workflow.steps);
  return {
    projectId: state.projectId,
    modelId: state.modelId ?? "",
    projectName: state.projectName?.trim() || "Untitled ATLAS Project",
    projectType: state.projectType,
    workflowId: workflow.id,
    workflowSteps: state.workflowSteps?.length ? state.workflowSteps : workflow.steps,
    currentStepId,
    hasDataset: Boolean(state.hasDataset),
    datasetIdentity: state.datasetIdentity ?? null,
    projectTools: state.projectTools,
  };
}

function normalizePath(value?: string) {
  if (!value) return "";
  const path = value.startsWith("/") ? value : `/${value}`;
  return path.length > 1 ? path.replace(/\/+$/, "") : path;
}

function resolveCurrentBrowserStepId(state: CurrentWorkflowState, fallbackSteps: WorkflowStep[]) {
  const steps = state.workflowSteps?.length ? state.workflowSteps : fallbackSteps;
  if (typeof window === "undefined") return state.currentStepId || steps[0]?.id || "step00";
  const pathname = normalizePath(normalizeWorkflowRoute(window.location?.pathname));
  if (!pathname || pathname === "/projects/open") return state.currentStepId || steps[0]?.id || "step00";
  const routeMatch = steps.find((step) => normalizePath(step.route) === pathname);
  if (routeMatch) return routeMatch.id;
  const predictiveMatch = steps.find((step) => normalizePath(`/${step.id}`) === pathname);
  return predictiveMatch?.id || state.currentStepId || steps[0]?.id || "step00";
}

export function isMeaningfulProjectSnapshot(snapshot: WorkflowProjectSnapshot) {
  const hasNamedProject = snapshot.projectName.trim() && snapshot.projectName.trim() !== "Untitled ATLAS Project";
  const hasModelId = Boolean(snapshot.modelId.trim());
  const hasProgress = snapshot.workflowSteps.some((step) => step.status === "complete" || step.status === "skipped");
  return hasNamedProject || hasModelId || hasProgress || Boolean(snapshot.hasDataset);
}

export function upsertProjectSnapshot(snapshot: WorkflowProjectSnapshot, source: LocalProjectRecord["source"] = "browser") {
  if (!isMeaningfulProjectSnapshot(snapshot)) return null;
  emitProjectSaveStatus({
    status: "saving",
    projectId: snapshot.projectId,
    message: "Saving ATLAS project snapshot...",
  });
  const snapshotToPersist = attachPersistedProjectState(snapshot);
  const existing = loadLocalProjects();
  const current = existing.find((project) => project.projectId === snapshotToPersist.projectId);
  const record: LocalProjectRecord = {
    projectId: snapshotToPersist.projectId,
    modelId: snapshotToPersist.modelId,
    projectName: snapshotToPersist.projectName,
    projectType: snapshotToPersist.projectType,
    workflowId: snapshotToPersist.workflowId,
    createdAt: current?.createdAt ?? nowIso(),
    lastModified: nowIso(),
    source: current?.source ?? source,
    snapshot: snapshotToPersist,
    snapshotStorageKey: projectSnapshotKey(snapshotToPersist.projectId),
  };
  try {
    saveLocalProjects([record, ...existing.filter((project) => project.projectId !== record.projectId)]);
    const registryWarning = lastRegistryWriteError;
    emitProjectSaveStatus({
      status: registryWarning ? "registry_warning" : "local_only",
      projectId: record.projectId,
      savedAt: record.lastModified,
      snapshotBytes: estimateBytes(record.snapshot),
      message: registryWarning
        ? `Project snapshot preserved for this session, but the Recent Projects index could not be written: ${registryWarning}`
        : "Project saved to the local compatibility store. ATLAS database sync is pending.",
    });
    queueProjectDatabaseSave(record.snapshot);
    return record;
  } catch (error) {
    emitProjectSaveStatus({
      status: "save_failed",
      projectId: record.projectId,
      message: error instanceof Error ? error.message : "ATLAS could not save this project snapshot.",
    });
    throw error;
  }
}

export function upsertProjectFromState(state: CurrentWorkflowState) {
  return upsertProjectSnapshot(createSnapshotFromState(state), "browser");
}

export function saveActiveProjectBeforeNavigation(
  state: CurrentWorkflowState,
  snapshotOverride?: WorkflowProjectSnapshot,
) {
  const snapshot = snapshotOverride ?? createSnapshotFromState(state);
  try {
    upsertProjectSnapshot(snapshot, "browser");
    return {
      ok: true,
      message: lastRegistryWriteError || "Project saved before navigation.",
      registryWarning: lastRegistryWriteError || undefined,
    };
  } catch (error) {
    try {
      const fallbackSnapshot = minimalSnapshot(snapshot);
      const existing = loadLocalProjects();
      const current = existing.find((project) => project.projectId === fallbackSnapshot.projectId);
      const record: LocalProjectRecord = {
        projectId: fallbackSnapshot.projectId,
        modelId: fallbackSnapshot.modelId,
        projectName: fallbackSnapshot.projectName,
        projectType: fallbackSnapshot.projectType,
        workflowId: fallbackSnapshot.workflowId,
        createdAt: current?.createdAt ?? nowIso(),
        lastModified: nowIso(),
        source: current?.source ?? "browser",
        snapshot: fallbackSnapshot,
        snapshotStorageKey: projectSnapshotKey(fallbackSnapshot.projectId),
        restoreStatus: "thin_snapshot_available",
      };
      saveLocalProjects([record, ...existing.filter((project) => project.projectId !== record.projectId)]);
      const registryWarning = lastRegistryWriteError;
      emitProjectSaveStatus({
        status: registryWarning ? "registry_warning" : "local_only",
        projectId: record.projectId,
        savedAt: record.lastModified,
        snapshotBytes: estimateBytes(fallbackSnapshot),
        message: registryWarning
          ? `Thin project snapshot preserved for this session, but the Recent Projects index could not be written: ${registryWarning}`
          : "ATLAS saved a thin project snapshot before navigation.",
      });
      queueProjectDatabaseSave(record.snapshot);
      return { ok: true, message: registryWarning || "Project saved as a thin snapshot before navigation.", registryWarning };
    } catch (fallbackError) {
      emitProjectSaveStatus({
        status: "save_failed",
        projectId: state.projectId,
        message:
          fallbackError instanceof Error
            ? fallbackError.message
            : error instanceof Error
              ? error.message
              : "ATLAS could not save the current project before navigation.",
      });
    }
    return {
      ok: false,
      message: error instanceof Error ? error.message : "ATLAS could not save the current project before navigation.",
    };
  }
}

export function renameLocalProject(projectId: string, projectName: string) {
  const name = projectName.trim();
  if (!name) return loadLocalProjects();
  const projects = loadLocalProjects().map((project) =>
    project.projectId === projectId
      ? {
          ...project,
          projectName: name,
          lastModified: nowIso(),
          snapshot: { ...project.snapshot, projectName: name },
        }
      : project
  );
  saveLocalProjects(projects);
  const renamed = projects.find((project) => project.projectId === projectId);
  if (renamed) queueProjectDatabaseSave(renamed.snapshot);
  return projects;
}

export function deleteLocalProject(projectId: string) {
  const projects = loadLocalProjects().filter((project) => project.projectId !== projectId);
  saveLocalProjects(projects);
  deleteProjectScopedStorage(projectId);
  return projects;
}

export function duplicateLocalProject(projectId: string) {
  const projects = loadLocalProjects();
  const source = projects.find((project) => project.projectId === projectId);
  if (!source) return { projects, duplicate: null as LocalProjectRecord | null };
  const duplicatedId = newProjectId();
  const duplicate: LocalProjectRecord = {
    ...source,
    projectId: duplicatedId,
    projectName: `${source.projectName} Copy`,
    createdAt: nowIso(),
    lastModified: nowIso(),
    source: "browser",
    snapshot: {
      ...source.snapshot,
      projectId: duplicatedId,
      projectName: `${source.projectName} Copy`,
    },
    snapshotStorageKey: projectSnapshotKey(duplicatedId),
  };
  const next = [duplicate, ...projects];
  saveLocalProjects(next);
  copyProjectScopedStorage(source.projectId, duplicatedId);
  queueProjectDatabaseSave(duplicate.snapshot);
  return { projects: next, duplicate };
}

export function importLocalProject(candidate: unknown) {
  const validation = validateProjectImport(candidate);
  if (!validation.ok) return null;
  const { snapshot, sourceRecord } = validation;
  const projectId = snapshot.projectId || newProjectId();
  const record: LocalProjectRecord = {
    projectId,
    modelId: snapshot.modelId,
    projectName: snapshot.projectName,
    projectType: snapshot.projectType,
    workflowId: snapshot.workflowId,
    createdAt: sourceRecord?.createdAt ?? nowIso(),
    lastModified: nowIso(),
    source: "imported",
    snapshot: { ...snapshot, projectId },
    snapshotStorageKey: projectSnapshotKey(projectId),
  };
  saveLocalProjects([record, ...loadLocalProjects().filter((item) => item.projectId !== projectId)]);
  queueProjectDatabaseSave(record.snapshot);
  return record;
}

export function restoreLocalProjectArtifacts(snapshot: WorkflowProjectSnapshot) {
  return restoreProjectSnapshotArtifacts(snapshot);
}

export function getProjectPersistenceDebug(projectId: string, workflowSteps: WorkflowStep[]) {
  return projectPersistenceDebug(projectId, workflowSteps);
}

export function saveProjectSnapshotFromState(state: CurrentWorkflowState) {
  return upsertProjectFromState(state);
}

export function recoverCurrentProjectToRegistry(state: CurrentWorkflowState) {
  const snapshot = createSnapshotFromState(state);
  const record = upsertProjectSnapshot(snapshot, "browser");
  return {
    record,
    projects: loadLocalProjects(),
    message: record
      ? lastRegistryWriteError
        ? `Recovered "${record.projectName}" into an in-session Recent Projects index. Export a backup or compact browser storage before closing the browser.`
        : `Recovered "${record.projectName}" into Recent Projects.`
      : "The active project does not contain enough information to recover yet.",
    registryWarning: lastRegistryWriteError,
  };
}

export function compactBrowserProjectStorage(currentProjectId?: string) {
  if (typeof localStorage === "undefined") {
    return { removed: 0, reclaimedBytes: 0, message: "Browser storage is unavailable." };
  }
  let removed = 0;
  let reclaimedBytes = 0;
  const protectedKeys = new Set([LOCAL_PROJECTS_KEY, currentProjectId ? projectSnapshotKey(currentProjectId) : ""]);
  const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).filter(
    (key): key is string => Boolean(key)
  );
  for (const key of keys) {
    if (protectedKeys.has(key)) continue;
    if (currentProjectId && key.startsWith(`atlas-workflow-node-state:${currentProjectId}:`)) continue;
    const shouldCompact = SAFE_COMPACTION_KEY_PATTERNS.some((pattern) => pattern.test(key));
    if (!shouldCompact) continue;
    const value = localStorage.getItem(key);
    const bytes = estimateBytes(value ?? "");
    if (bytes < 75 * 1024 && !key.includes("corrupt-backup")) continue;
    localStorage.removeItem(key);
    removed += 1;
    reclaimedBytes += bytes;
  }
  if (currentProjectId) {
    const projects = loadLocalProjects();
    if (projects.length) saveLocalProjects(projects);
  }
  return {
    removed,
    reclaimedBytes,
    message: removed
      ? `Compacted ${removed} large browser artifact${removed === 1 ? "" : "s"} and reclaimed about ${Math.round(reclaimedBytes / 1024).toLocaleString()} KB.`
      : "No large compactable browser artifacts were found.",
  };
}

export function getProjectStorageDiagnostics(projectId: string, workflowSteps: WorkflowStep[]) {
  const debug = projectPersistenceDebug(projectId, workflowSteps);
  const status = getLocalProjectsRegistryStatus();
  const largestKeys =
    typeof localStorage === "undefined"
      ? []
      : debug.localStorageKeys
          .map((key) => ({ key, bytes: estimateBytes(localStorage.getItem(key) ?? "") }))
          .sort((a, b) => b.bytes - a.bytes)
          .slice(0, 8);
  return {
    ...debug,
    registryStatus: status.message,
    registryOk: status.ok,
    volatileFallback: Boolean(status.volatileFallback),
    lastRegistryWriteError: status.lastWriteError ?? "",
    largestKeys,
  };
}

export function projectProgress(steps: WorkflowStep[]) {
  const total = Math.max(1, steps.length);
  const complete = steps.filter((step) => step.status === "complete" || step.status === "skipped").length;
  return {
    complete,
    total,
    percent: Math.round((complete / total) * 100),
  };
}

export function currentWorkflowStage(steps: WorkflowStep[], currentStepId?: string) {
  return steps.find((step) => step.id === currentStepId) ?? steps.find((step) => step.status !== "complete" && step.status !== "skipped") ?? steps[0];
}

export function formatProjectDate(value: string) {
  if (!value) return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not available";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

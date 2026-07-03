import { getWorkflowDefinition, getWorkflowForProjectType, type ProjectType, type WorkflowStep } from "../config/workflows";
import type { WorkflowProjectSnapshot } from "../state/useWorkflowStore";
import {
  attachPersistedProjectState,
  compactProjectForStorage,
  emitProjectSaveStatus,
  estimateBytes,
  projectPersistenceDebug,
  restoreProjectSnapshotArtifacts,
} from "./projectPersistence";
import { validateProjectImport } from "./projectImportValidation";

export const LOCAL_PROJECTS_KEY = "atlas-local-projects";
const PROJECT_SCOPED_STORAGE_PREFIXES = ["atlas-workflow-node-state:"];

export type LocalProjectRecord = {
  projectId: string;
  modelId?: string;
  projectName: string;
  projectType: ProjectType;
  workflowId: string;
  createdAt: string;
  lastModified: string;
  source?: "browser" | "imported";
  snapshot: WorkflowProjectSnapshot;
};

type CurrentWorkflowState = WorkflowProjectSnapshot & {
  projectTools?: WorkflowProjectSnapshot["projectTools"];
};

function nowIso() {
  return new Date().toISOString();
}

function newProjectId() {
  return `atlas-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function parseProjects(raw: string | null): LocalProjectRecord[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((project): project is LocalProjectRecord => Boolean(project?.projectId && project?.projectName && project?.snapshot));
  } catch {
    return [];
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
  if (typeof localStorage === "undefined") return;
  for (const prefix of PROJECT_SCOPED_STORAGE_PREFIXES) {
    const scopedPrefix = projectScopedPrefix(prefix, projectId);
    const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).filter(
      (key): key is string => Boolean(key?.startsWith(scopedPrefix))
    );
    keys.forEach((key) => localStorage.removeItem(key));
  }
}

function safeJsonParse(raw: string | null) {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
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
  return parseProjects(localStorage.getItem(LOCAL_PROJECTS_KEY)).sort((a, b) => b.lastModified.localeCompare(a.lastModified));
}

export function saveLocalProjects(projects: LocalProjectRecord[]) {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(LOCAL_PROJECTS_KEY, JSON.stringify(projects));
  } catch (error) {
    const compacted = projects.map(compactProjectForStorage);
    try {
      localStorage.setItem(LOCAL_PROJECTS_KEY, JSON.stringify(compacted));
    } catch {
      throw new Error(
        `Browser storage quota exceeded while saving Recent Projects. Snapshot size was ${Math.round(estimateBytes(projects) / 1024).toLocaleString()} KB.`
      );
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
  return {
    projectId: state.projectId,
    modelId: state.modelId ?? "",
    projectName: state.projectName?.trim() || "Untitled ATLAS Project",
    projectType: state.projectType,
    workflowId: workflow.id,
    workflowSteps: state.workflowSteps?.length ? state.workflowSteps : workflow.steps,
    currentStepId: state.currentStepId || workflow.steps[0]?.id || "step00",
    hasDataset: Boolean(state.hasDataset),
    projectTools: state.projectTools,
  };
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
  };
  try {
    saveLocalProjects([record, ...existing.filter((project) => project.projectId !== record.projectId)]);
    emitProjectSaveStatus({
      status: "saved",
      projectId: record.projectId,
      savedAt: record.lastModified,
      snapshotBytes: estimateBytes(record.snapshot),
      message: "ATLAS project saved.",
    });
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
  };
  const next = [duplicate, ...projects];
  saveLocalProjects(next);
  copyProjectScopedStorage(source.projectId, duplicatedId);
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
  };
  saveLocalProjects([record, ...loadLocalProjects().filter((item) => item.projectId !== projectId)]);
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

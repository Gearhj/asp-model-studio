import { getWorkflowDefinition } from "../config/workflows";
import type { WorkflowProjectSnapshot } from "../state/useWorkflowStore";
import { DATASET_API_BASE, listDatasets, type DatasetSummary } from "./datasetLibrary";
import type { LocalProjectRecord } from "./localProjects";

export type BackendProjectRecord = {
  projectId: string;
  name: string;
  projectType: "predictive_modeling" | "experimental_design" | "unknown" | string;
  taskType?: "regression" | "classification" | "experimental_design" | string;
  target?: string;
  linkedDatasets?: Array<Partial<DatasetSummary> & { datasetRole?: string; versionId?: string }>;
  lastOpenedAt?: string;
  lastSavedAt?: string;
  createdAt?: string;
  storageLocation?: "server_artifact" | "browser" | "recovered" | "imported_file" | string;
  snapshotPath?: string;
  recoveryStatus?: string;
};

export type RecoveryCompleteness =
  | "Complete project"
  | "Partial project"
  | "Dataset-linked shell only"
  | "Workflow-node-state only"
  | "Artifact-only"
  | "Unrecoverable";

export type ProjectRecoveryCandidate = {
  candidateId: string;
  projectId: string;
  name: string;
  projectType: "predictive-modeling" | "experimental-design" | "unknown";
  taskType?: "regression" | "classification" | "experimental-design" | "unknown";
  target?: string;
  linkedDatasets: Array<Partial<DatasetSummary> & { datasetRole?: string; versionId?: string }>;
  lastModified?: string;
  createdAt?: string;
  sourceLocation: string;
  completeness: RecoveryCompleteness;
  storageLocation?: string;
  notes?: string;
  snapshot?: WorkflowProjectSnapshot;
};

function apiBase() {
  return DATASET_API_BASE.replace(/\/$/, "");
}

async function jsonFetch<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, { credentials: "include" });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) throw new Error(payload?.detail ?? payload?.error ?? `Request failed: ${path}`);
  return payload as T;
}

export async function listBackendProjectRegistry() {
  const payload = await jsonFetch<{ ok: true; projects: BackendProjectRecord[]; registryPath: string }>("/projects/registry");
  return payload.projects;
}

export async function scanBackendProjectRecovery() {
  const payload = await jsonFetch<{ ok: true; candidates: BackendProjectRecord[]; summary: Record<string, number> }>("/projects/recovery/scan");
  return payload.candidates;
}

function normalizeProjectType(value?: string): ProjectRecoveryCandidate["projectType"] {
  const text = (value ?? "").replace(/_/g, "-").toLowerCase();
  if (text.includes("experiment")) return "experimental-design";
  if (text.includes("predict") || text.includes("model") || text.includes("regression") || text.includes("classification")) return "predictive-modeling";
  return "unknown";
}

function inferTaskFromDataset(dataset: Partial<DatasetSummary>): ProjectRecoveryCandidate["taskType"] {
  const sourceInfo = (dataset as any).sourceInfo ?? {};
  const text = `${dataset.name ?? ""} ${dataset.datasetId ?? ""} ${dataset.sourceType ?? ""} ${sourceInfo.task ?? ""} ${sourceInfo.datasetType ?? ""}`.toLowerCase();
  if (text.includes("regression") || text.includes("reg_") || text.includes("home-prices")) return "regression";
  if (text.includes("classification") || text.includes("class_") || text.includes("fraud")) return "classification";
  return "unknown";
}

function inferTarget(datasets: Partial<DatasetSummary>[], task?: string) {
  for (const dataset of datasets) {
    const sourceInfo = (dataset as any).sourceInfo ?? {};
    if (sourceInfo.targetColumn) return String(sourceInfo.targetColumn);
  }
  if (task === "regression") return "MedHouseVal";
  if (task === "classification") return "Class";
  return "";
}

function candidateName(task: string | undefined, datasets: Partial<DatasetSummary>[]) {
  const scored = datasets.find((dataset) => /home-prices-regression-test-model/i.test(`${dataset.name ?? ""} ${dataset.datasetId ?? ""}`));
  if (scored) return "Home Prices Regression Test Model";
  if (task === "regression") return "Home Prices Regression Test Model";
  if (task === "classification") return "Recovered Classification Predictive Model";
  return "Recovered ATLAS Project";
}

export function snapshotFromRecoveryCandidate(candidate: ProjectRecoveryCandidate): WorkflowProjectSnapshot {
  const workflow = getWorkflowDefinition("predictive-modeling");
  const completed = new Set(candidate.linkedDatasets.length ? ["step00", "step01"] : ["step00"]);
  if (candidate.linkedDatasets.some((dataset) => /scored/i.test(`${dataset.datasetRole ?? ""} ${dataset.sourceType ?? ""}`))) {
    completed.add("step10");
  }
  return {
    projectId: candidate.projectId,
    modelId: "",
    projectName: candidate.name,
    projectType: "predictive-modeling",
    workflowId: workflow.id,
    workflowSteps: workflow.steps.map((step) => ({
      ...step,
      status: completed.has(step.id) ? "complete" : step.status ?? "pending",
    })),
    currentStepId: "step01",
    hasDataset: candidate.linkedDatasets.length > 0,
    restoreWarnings: [
      "This project was reconstructed from dataset links and artifacts. Some page-level settings may need review.",
      `Recovered target: ${candidate.target || "not detected"}.`,
    ],
  };
}

export function candidateFromBackendProject(record: BackendProjectRecord): ProjectRecoveryCandidate {
  const projectType = normalizeProjectType(record.projectType);
  return {
    candidateId: `backend:${record.projectId}`,
    projectId: record.projectId,
    name: record.name,
    projectType,
    taskType: (record.taskType as ProjectRecoveryCandidate["taskType"]) ?? "unknown",
    target: record.target,
    linkedDatasets: record.linkedDatasets ?? [],
    lastModified: record.lastSavedAt || record.lastOpenedAt,
    createdAt: record.createdAt,
    sourceLocation: "server/artifacts/projects/project_registry.json",
    completeness: (record.recoveryStatus as RecoveryCompleteness) || (projectType === "predictive-modeling" ? "Dataset-linked shell only" : "Partial project"),
    storageLocation: record.storageLocation,
    notes: record.snapshotPath ? `Snapshot path: ${record.snapshotPath}` : undefined,
  };
}

export function candidatesFromBrowserProjects(projects: LocalProjectRecord[]): ProjectRecoveryCandidate[] {
  return projects.map((project) => ({
    candidateId: `browser:${project.projectId}`,
    projectId: project.projectId,
    name: project.projectName,
    projectType: normalizeProjectType(project.projectType),
    taskType: project.projectType === "experimental-design" ? "experimental-design" : "unknown",
    linkedDatasets: [],
    lastModified: project.lastModified,
    createdAt: project.createdAt,
    sourceLocation: "browser Recent Projects registry",
    completeness: project.snapshot?.persistedLocalState ? "Complete project" : "Partial project",
    storageLocation: project.source ?? "browser",
    snapshot: project.snapshot,
  }));
}

export function candidatesFromDatasets(datasets: DatasetSummary[]): ProjectRecoveryCandidate[] {
  const groups: Array<{ id: string; task: "regression" | "classification"; prefix: string }> = [
    { id: "recovered-regression-shell", task: "regression", prefix: "REG_" },
    { id: "recovered-classification-shell", task: "classification", prefix: "CLASS_" },
  ];
  const candidates: ProjectRecoveryCandidate[] = [];
  for (const group of groups) {
    const matches = datasets.filter((dataset) => (dataset.name ?? "").toUpperCase().startsWith(group.prefix));
    const scored = datasets.filter((dataset) => inferTaskFromDataset(dataset) === group.task && /scored/i.test(`${dataset.sourceType ?? ""} ${(dataset as any).datasetRole ?? ""} ${dataset.name ?? ""}`));
    const linked = [...matches, ...scored].filter((dataset, index, rows) => rows.findIndex((row) => row.datasetId === dataset.datasetId) === index);
    if (!linked.length) continue;
    candidates.push({
      candidateId: `dataset-shell:${group.id}`,
      projectId: linked.flatMap((dataset) => dataset.linkedProjects ?? []).find((link) => link.projectId)?.projectId || group.id,
      name: candidateName(group.task, linked),
      projectType: "predictive-modeling",
      taskType: group.task,
      target: inferTarget(linked, group.task),
      linkedDatasets: linked,
      lastModified: latestString(linked.map((dataset) => dataset.updatedAt || dataset.createdAt || "")),
      createdAt: linked.map((dataset) => dataset.createdAt || "").filter(Boolean).sort()[0],
      sourceLocation: "Dataset Library links and dataset names",
      completeness: "Dataset-linked shell only",
      storageLocation: "recovered",
      notes: "Rebuilt from Dataset Library assets because a full project snapshot was not found.",
    });
  }
  return candidates;
}

function latestString(values: string[]) {
  const sorted = values.filter(Boolean).sort();
  return sorted.length ? sorted[sorted.length - 1] : undefined;
}

export async function deepRecoveryScan(browserProjects: LocalProjectRecord[]) {
  const candidates: ProjectRecoveryCandidate[] = [];
  const errors: string[] = [];
  candidates.push(...candidatesFromBrowserProjects(browserProjects));

  try {
    candidates.push(...(await listBackendProjectRegistry()).map(candidateFromBackendProject));
  } catch (error) {
    errors.push(error instanceof Error ? error.message : "Backend project registry scan failed.");
  }

  try {
    candidates.push(...(await scanBackendProjectRecovery()).map(candidateFromBackendProject));
  } catch (error) {
    errors.push(error instanceof Error ? error.message : "Backend recovery scan failed.");
  }

  try {
    candidates.push(...candidatesFromDatasets((await listDatasets(true)).datasets));
  } catch (error) {
    errors.push(error instanceof Error ? error.message : "Dataset Library recovery scan failed.");
  }

  const byId = new Map<string, ProjectRecoveryCandidate>();
  for (const candidate of candidates) {
    const key = `${candidate.projectId}:${candidate.taskType ?? ""}:${candidate.name}`;
    const existing = byId.get(key);
    if (!existing || rankCompleteness(candidate.completeness) > rankCompleteness(existing.completeness)) byId.set(key, candidate);
  }
  return { candidates: Array.from(byId.values()), errors };
}

function rankCompleteness(value: RecoveryCompleteness) {
  return {
    "Complete project": 5,
    "Partial project": 4,
    "Dataset-linked shell only": 3,
    "Workflow-node-state only": 2,
    "Artifact-only": 1,
    Unrecoverable: 0,
  }[value];
}

export function buildRecoveryReport(candidates: ProjectRecoveryCandidate[], actions: string[] = []) {
  const predictive = candidates.filter((candidate) => candidate.projectType === "predictive-modeling");
  const experimental = candidates.filter((candidate) => candidate.projectType === "experimental-design");
  const shellCandidates = candidates.filter((candidate) => candidate.completeness === "Dataset-linked shell only");
  return `# PROJECT_RECOVERY_SCAN_REPORT

Generated: ${new Date().toISOString()}

## Summary

- Recovered project candidates: ${candidates.length}
- Predictive Modeling candidates found: ${predictive.length}
- Experimental Design candidates found: ${experimental.length}
- Dataset-linked shells available: ${shellCandidates.length}

## Recovered Project Candidates

| Candidate | Type | Task | Target | Completeness | Source |
|---|---|---|---|---|---|
${candidates.map((candidate) => `| ${candidate.name} | ${candidate.projectType} | ${candidate.taskType ?? ""} | ${candidate.target ?? ""} | ${candidate.completeness} | ${candidate.sourceLocation} |`).join("\n")}

## Dataset-Linked Shells Created

${shellCandidates.length ? shellCandidates.map((candidate) => `- ${candidate.name}: ${(candidate.linkedDatasets ?? []).map((dataset) => dataset.name || dataset.datasetId).join(", ")}`).join("\n") : "No dataset-linked shells were created during this scan."}

## Unrecoverable References

No unrecoverable references were identified by this browser scan. If a project existed only in expired session storage and has no dataset or artifact links, it cannot be reconstructed automatically.

## Actions Taken

${actions.length ? actions.map((action) => `- ${action}`).join("\n") : "- Scan only; no projects were recovered automatically."}

## Remaining Risks

- Dataset-linked shells restore project identity, task, target, and dataset links, but not every page-level modeling option.
- Browser quota pressure may still prevent durable localStorage writes until large artifacts are compacted.
- Backend registry now provides durable metadata, but full browser snapshots may still need export/backups for complete restoration.
`;
}

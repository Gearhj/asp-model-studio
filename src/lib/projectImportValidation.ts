import { getWorkflowDefinition, getWorkflowForProjectType, type ProjectType } from "../config/workflows";
import type { LocalProjectRecord } from "./localProjects";
import type { WorkflowProjectSnapshot } from "../state/useWorkflowStore";

export type ProjectImportValidationResult =
  | { ok: true; snapshot: WorkflowProjectSnapshot; sourceRecord?: Partial<LocalProjectRecord>; warnings: string[] }
  | { ok: false; errors: string[]; warnings: string[] };

const supportedProjectTypes: ProjectType[] = [
  "predictive-modeling",
  "experimental-design",
  "ab-testing",
  "optimization",
  "forecasting",
  "segmentation",
  "reinforcement-learning",
  "time-series",
  "nlp",
  "computer-vision",
  "graph-analytics",
  "custom-workflow",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function asString(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function isProjectType(value: unknown): value is ProjectType {
  return supportedProjectTypes.includes(value as ProjectType);
}

function newProjectId() {
  return `atlas-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function normalizeCandidate(candidate: unknown) {
  const imported = Array.isArray(candidate) ? candidate[0] : candidate;
  if (!isRecord(imported)) return null;
  const snapshotCandidate = isRecord(imported.snapshot) ? imported.snapshot : imported;
  return { imported, snapshotCandidate };
}

export function validateProjectImport(candidate: unknown): ProjectImportValidationResult {
  const normalized = normalizeCandidate(candidate);
  if (!normalized) {
    return { ok: false, errors: ["Project import must be a JSON object or an exported ATLAS project array."], warnings: [] };
  }

  const { imported, snapshotCandidate } = normalized;
  const errors: string[] = [];
  const warnings: string[] = [];
  const projectName = asString(snapshotCandidate.projectName);
  const projectType = snapshotCandidate.projectType;
  const workflowId = asString(snapshotCandidate.workflowId);

  if (!projectName) errors.push("Project name is required.");
  if (!isProjectType(projectType)) errors.push("Project type is missing or unsupported.");

  if (asString(imported.schemaVersion) && !/^1|2$/.test(asString(imported.schemaVersion))) {
    warnings.push("Import schema version is newer than this ATLAS build; unsupported fields will be ignored.");
  }

  if (errors.length || !isProjectType(projectType)) {
    return { ok: false, errors, warnings };
  }

  let workflow = getWorkflowForProjectType(projectType);
  try {
    workflow = getWorkflowDefinition(workflowId || workflow.id);
  } catch {
    warnings.push(`Workflow ${workflowId || "(blank)"} was not recognized; ATLAS selected ${workflow.id}.`);
  }

  const projectId = asString(snapshotCandidate.projectId) || newProjectId();
  const steps = Array.isArray(snapshotCandidate.workflowSteps) && snapshotCandidate.workflowSteps.length
    ? snapshotCandidate.workflowSteps
    : workflow.steps;
  const stepIds = new Set(steps.map((step: any) => step?.id).filter(Boolean));
  const requestedCurrentStep = asString(snapshotCandidate.currentStepId);
  const currentStepId = requestedCurrentStep && stepIds.has(requestedCurrentStep)
    ? requestedCurrentStep
    : workflow.steps[0]?.id || "step00";
  if (requestedCurrentStep && currentStepId !== requestedCurrentStep) {
    warnings.push("Imported current step did not exist in the workflow and was reset to the first step.");
  }

  const snapshot: WorkflowProjectSnapshot = {
    projectId,
    modelId: asString(snapshotCandidate.modelId),
    projectName,
    projectType,
    workflowId: workflow.id,
    workflowSteps: steps as WorkflowProjectSnapshot["workflowSteps"],
    currentStepId,
    hasDataset: Boolean(snapshotCandidate.hasDataset),
    projectTools: isRecord(snapshotCandidate.projectTools) ? (snapshotCandidate.projectTools as WorkflowProjectSnapshot["projectTools"]) : undefined,
    persistedLocalState: snapshotCandidate.persistedLocalState,
    restoreWarnings: Array.isArray(snapshotCandidate.restoreWarnings) ? snapshotCandidate.restoreWarnings.map(String) : undefined,
  };

  return { ok: true, snapshot, sourceRecord: imported as Partial<LocalProjectRecord>, warnings };
}

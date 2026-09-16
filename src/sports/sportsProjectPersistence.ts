import {
  getProjectFromDatabase,
  getProjectWorkflowStateFromDatabase,
  type PersistedRecord,
} from "../lib/serverPersistence";
import type { WorkflowProjectSnapshot } from "../state/useWorkflowStore";
import {
  isSportsWorkflow,
  sportsWorkflowForId,
  type SportsProjectMetadata,
} from "./sportsConfig";

function object(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, any>
    : {};
}

function text(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

export function sportsMetadataFromPersistedProject(
  project: PersistedRecord,
): SportsProjectMetadata | null {
  const metadata = object(project.metadata ?? project.metadata_json);
  const candidate = object(metadata.sportsProject);
  const projectId = text(project.projectId ?? project.project_id);
  return candidate.projectId === projectId ? candidate as SportsProjectMetadata : null;
}

export function persistedSportsProjectSnapshot(
  project: PersistedRecord,
  workflowState: PersistedRecord | null = null,
): WorkflowProjectSnapshot {
  const projectId = text(project.projectId ?? project.project_id);
  const workflowId = text(
    project.workflowType ?? project.workflow_type ?? project.workflowId ?? project.workflow_id,
  );
  if (!projectId || !isSportsWorkflow(workflowId)) {
    throw new Error("The backend record is not a registered ASP Model Studio sports project.");
  }
  const workflow = sportsWorkflowForId(workflowId);
  const state = object(workflowState);
  const workflowStatus = object(state.workflowStatus ?? state.workflow_status);
  const stepStatuses = object(workflowStatus.steps);
  const completed = new Set(
    (Array.isArray(state.historicalCompletedSteps)
      ? state.historicalCompletedSteps
      : Array.isArray(state.completedSteps)
        ? state.completedSteps
        : []
    ).map(String),
  );
  const workflowSteps = workflow.steps.map((item) => {
    const rawStatus = text(stepStatuses[item.id]).toLowerCase();
    const status = rawStatus === "complete" || completed.has(item.id)
      ? "complete" as const
      : rawStatus === "skipped"
        ? "skipped" as const
        : rawStatus === "in_progress"
          ? "in_progress" as const
          : "pending" as const;
    return {
      id: item.id,
      label: item.title,
      shortLabel: item.title.split(" ").slice(0, 2).join(" "),
      route: `/workflows/${workflow.key}#${item.id}`,
      description: item.purpose,
      required: true,
      status,
    };
  });
  const metadata = object(project.metadata ?? project.metadata_json);
  const rawProjectTools = object(metadata.projectTools ?? metadata.project_tools);
  const requestedStep = text(
    state.currentStepId
      ?? state.current_step_id
      ?? workflowStatus.currentStepId
      ?? workflowStatus.current_step_id,
  );
  return {
    projectId,
    modelId: text(metadata.modelId ?? metadata.model_id),
    projectName: text(project.projectName ?? project.project_name) || "Untitled Sports Project",
    projectType: "custom-workflow",
    workflowId: workflow.id,
    workflowSteps,
    currentStepId: workflowSteps.some((step) => step.id === requestedStep)
      ? requestedStep
      : workflowSteps.find((step) => step.status !== "complete" && step.status !== "skipped")?.id
        ?? workflowSteps[0]?.id
        ?? "mlb-01",
    hasDataset: false,
    datasetIdentity: null,
    projectTools: {
      experimentsEnabled: rawProjectTools.experimentsEnabled === true,
      decisionJournalEnabled: rawProjectTools.decisionJournalEnabled === true,
      governanceEnabled: rawProjectTools.governanceEnabled === true,
      notebookExportEnabled: rawProjectTools.notebookExportEnabled === true,
    },
  };
}

export async function loadPersistedSportsProject(
  projectId: string,
  signal?: AbortSignal,
) {
  const [project, workflowState] = await Promise.all([
    getProjectFromDatabase(projectId, signal),
    getProjectWorkflowStateFromDatabase(projectId, signal),
  ]);
  return {
    project,
    workflowState,
    snapshot: persistedSportsProjectSnapshot(project, workflowState),
    sportsMetadata: sportsMetadataFromPersistedProject(project),
  };
}

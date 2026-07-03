import type { WorkflowProjectSnapshot } from "../state/useWorkflowStore";

export type ArtifactRestoreStatus =
  | "fully_restored"
  | "dataset_reload_required"
  | "model_rerun_required"
  | "simulation_summary_only"
  | "artifact_missing";

export type ArtifactStorageTier = "localStorage" | "sessionStorage" | "indexedDB" | "backendFilesystem";

export type ArtifactStoragePolicy = {
  artifact: string;
  tier: ArtifactStorageTier;
  persistFullPayload: boolean;
  restoreStatus: ArtifactRestoreStatus;
  rationale: string;
};

export type ArtifactRestoreSummary = {
  status: ArtifactRestoreStatus;
  label: string;
  message: string;
  warnings: string[];
};

export const artifactStoragePolicy: ArtifactStoragePolicy[] = [
  {
    artifact: "Project metadata, workflow progress, selected options, and final decisions",
    tier: "localStorage",
    persistFullPayload: true,
    restoreStatus: "fully_restored",
    rationale: "Small governed state must survive browser refresh and project reopen.",
  },
  {
    artifact: "Raw uploaded datasets and large row-level scoring files",
    tier: "sessionStorage",
    persistFullPayload: false,
    restoreStatus: "dataset_reload_required",
    rationale: "Raw data can exceed browser quota and should be reloaded or moved to governed backend storage.",
  },
  {
    artifact: "Fitted model binaries, SHAP arrays, RFE paths, and full scoring outputs",
    tier: "backendFilesystem",
    persistFullPayload: false,
    restoreStatus: "model_rerun_required",
    rationale: "Model artifacts are large and should be recreated or stored by a backend artifact service.",
  },
  {
    artifact: "Monte Carlo simulations and long iteration-level arrays",
    tier: "localStorage",
    persistFullPayload: false,
    restoreStatus: "simulation_summary_only",
    rationale: "ATLAS persists seed, assumptions, summary metrics, and chart aggregates, not full iteration traces.",
  },
  {
    artifact: "Missing or corrupted imported project references",
    tier: "indexedDB",
    persistFullPayload: false,
    restoreStatus: "artifact_missing",
    rationale: "Future IndexedDB/backend references can be validated without crashing the project launcher.",
  },
];

export function describeArtifactRestoreStatus(status: ArtifactRestoreStatus) {
  switch (status) {
    case "fully_restored":
      return "Fully restored";
    case "dataset_reload_required":
      return "Restored with dataset reload required";
    case "model_rerun_required":
      return "Restored with model rerun required";
    case "simulation_summary_only":
      return "Restored with simulation summary only";
    case "artifact_missing":
      return "Artifact missing";
    default:
      return "Unknown restore status";
  }
}

export function summarizeArtifactRestore(snapshot: WorkflowProjectSnapshot): ArtifactRestoreSummary {
  const persisted = snapshot.persistedLocalState as
    | { missingArtifacts?: string[]; sessionStorage?: Record<string, unknown>; workflowNodeStates?: Record<string, unknown> }
    | undefined;
  const warnings = Array.isArray(persisted?.missingArtifacts) ? persisted.missingArtifacts.map(String) : [];
  const hasDatasetPreview = Boolean(persisted?.sessionStorage?.["modeling-tool-dataset"]);
  const hasSimulationSummary = Object.values(persisted?.workflowNodeStates ?? {}).some((state) => {
    if (!state || typeof state !== "object") return false;
    const maybe = state as { simulationResults?: unknown };
    return Boolean(maybe.simulationResults);
  });

  let status: ArtifactRestoreStatus = "fully_restored";
  if (warnings.some((warning) => /missing|corrupt|not found/i.test(warning))) status = "artifact_missing";
  else if (warnings.some((warning) => /model|train|rerun/i.test(warning))) status = "model_rerun_required";
  else if (hasSimulationSummary || warnings.some((warning) => /simulation|monte carlo/i.test(warning))) status = "simulation_summary_only";
  else if (snapshot.hasDataset && !hasDatasetPreview) status = "dataset_reload_required";

  return {
    status,
    label: describeArtifactRestoreStatus(status),
    message:
      status === "fully_restored"
        ? "Workflow state and compact artifacts can be restored from browser storage."
        : "Workflow state was restored, but one or more large artifacts require reload, rerun, or backend retrieval.",
    warnings,
  };
}

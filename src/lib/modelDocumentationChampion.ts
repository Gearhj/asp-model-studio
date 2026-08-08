import type { CanonicalDatasetIdentity } from "./datasetIdentity";
import type { ExperimentRecord } from "./experimentTracking";
import type { ExactPromotedModelIdentity } from "./implementationMonitoringIdentity";

export type ModelDocumentationChampionResolution = {
  ready: boolean;
  identity: ExactPromotedModelIdentity | null;
  supplementaryExperiment: ExperimentRecord | null;
  error: string;
};

const text = (value: unknown) => typeof value === "string" ? value.trim() : "";

function normalizedModelName(value: unknown) {
  return text(value).toLowerCase().replace(/[^a-z0-9]+/g, "");
}

/**
 * Binds Model Development Documentation to the exact durable Model Registry
 * identity. Browser experiment rows may contribute supplementary diagnostics
 * only when both their canonical dataset scope and training/model identity
 * match. A browser `champion` flag is never promotion authority.
 */
export function resolveModelDocumentationChampion(input: {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity | null;
  target: string;
  promotedModelIdentity: ExactPromotedModelIdentity | null;
  experiments: ExperimentRecord[];
}): ModelDocumentationChampionResolution {
  const projectId = text(input.projectId);
  const datasetId = text(input.datasetIdentity?.dataset_id);
  const datasetVersionId = text(input.datasetIdentity?.dataset_version_id);
  const target = text(input.target);
  const promoted = input.promotedModelIdentity;

  if (!projectId || !datasetId || !datasetVersionId || !target || !promoted) {
    return {
      ready: false,
      identity: null,
      supplementaryExperiment: null,
      error: "Model Development Documentation requires an exact backend-verified champion, registered dataset version, and target.",
    };
  }

  const exactFieldsPresent = Boolean(
    text(promoted.modelId)
      && text(promoted.modelVersionId)
      && text(promoted.modelName)
      && text(promoted.candidateId)
      && text(promoted.trainingRunId)
      && text(promoted.featureManifestVersion)
      && text(promoted.validationDesignId)
      && text(promoted.splitId)
      && text(promoted.artifactChecksum)
      && /^(verified|ready|complete)$/i.test(text(promoted.artifactVerificationStatus)),
  );
  if (!exactFieldsPresent) {
    return {
      ready: false,
      identity: null,
      supplementaryExperiment: null,
      error: "The promoted champion is missing its durable model version, candidate lineage, or verified artifact checksum.",
    };
  }

  const contextMatches = promoted.projectId === projectId
    && promoted.datasetId === datasetId
    && promoted.datasetVersionId === datasetVersionId
    && promoted.target === target;
  if (!contextMatches) {
    return {
      ready: false,
      identity: null,
      supplementaryExperiment: null,
      error: "The promoted champion contradicts the exact project, registered dataset version, or target required by this documentation checkpoint.",
    };
  }

  const promotedModelName = normalizedModelName(promoted.modelName);
  const supplementaryMatches = input.experiments.filter((experiment) => {
    const modelMatches = normalizedModelName(experiment.modelType) === promotedModelName
      || normalizedModelName(experiment.modelKey) === promotedModelName;
    return experiment.project_id === projectId
      && experiment.dataset_id === datasetId
      && experiment.dataset_version_id === datasetVersionId
      && experiment.trainingJobId === promoted.trainingRunId
      && modelMatches;
  });

  return {
    ready: true,
    identity: promoted,
    // Duplicate or ambiguous browser diagnostics are ignored. They are never
    // allowed to contradict or replace the durable Model Registry champion.
    supplementaryExperiment: supplementaryMatches.length === 1
      ? supplementaryMatches[0]
      : null,
    error: "",
  };
}

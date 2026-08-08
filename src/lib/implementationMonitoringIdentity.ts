import {
  resolveFinalModelReadiness,
  type ExpectedModelingContext,
  type FinalModelContextFields,
} from "./finalModelReadiness";
import type { ProjectContext } from "./projectContext";

export type PromotedModelStatusMetadata = FinalModelContextFields & {
  model_id?: string;
  modelId?: string;
  name?: string;
  model_name?: string;
  modelName?: string;
};

export type ExactPromotedModelIdentity = {
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  target: string;
  modelId: string;
  modelVersionId: string;
  modelName: string;
  candidateId: string;
  trainingRunId: string;
  featureManifestVersion: string;
  validationDesignId: string;
  splitId: string;
  artifactChecksum: string;
  artifactVerificationStatus: string;
};

export type ExactPromotedModelResolution = {
  ready: boolean;
  identity: ExactPromotedModelIdentity | null;
  error: string;
};

const text = (value: unknown) => typeof value === "string" ? value.trim() : "";

function firstText(...values: unknown[]) {
  for (const value of values) {
    const resolved = text(value);
    if (resolved) return resolved;
  }
  return "";
}

/**
 * Resolves the one durable Model Registry identity that Implementation and
 * Monitoring are allowed to display. Browser context is never accepted as
 * model identity authority.
 */
export function resolveExactPromotedModelIdentity(
  response: { ready?: boolean; metadata?: PromotedModelStatusMetadata | null } | null | undefined,
  expected: ExpectedModelingContext,
): ExactPromotedModelResolution {
  const readiness = resolveFinalModelReadiness(response, expected);
  if (!readiness.ready || !readiness.durableIdentity) {
    return {
      ready: false,
      identity: null,
      error: readiness.error || "No exact verified promoted model is available for this project and dataset version.",
    };
  }

  const metadata = readiness.metadata;
  const modelId = firstText(metadata.model_id, metadata.modelId);
  if (!modelId) {
    return {
      ready: false,
      identity: null,
      error: "The promoted model status did not return a durable model_id.",
    };
  }

  return {
    ready: true,
    identity: {
      projectId: text(metadata.project_id),
      datasetId: firstText(metadata.training_dataset_id, metadata.dataset_id),
      datasetVersionId: firstText(
        metadata.training_dataset_version_id,
        metadata.dataset_version_id,
      ),
      target: firstText(metadata.target_name, metadata.target),
      modelId,
      modelVersionId: readiness.durableIdentity.modelVersionId,
      modelName: firstText(metadata.model_name, metadata.modelName, metadata.name, modelId),
      candidateId: text(metadata.candidate_id),
      trainingRunId: text(metadata.training_run_id),
      featureManifestVersion: text(metadata.feature_manifest_version),
      validationDesignId: text(metadata.validation_design_id),
      splitId: text(metadata.split_id),
      artifactChecksum: firstText(metadata.artifact_checksum, metadata.checksum),
      artifactVerificationStatus: readiness.durableIdentity.artifactVerificationStatus,
    },
    error: "",
  };
}

export function bindPromotedModelIdentity(
  context: ProjectContext,
  identity: ExactPromotedModelIdentity,
): ProjectContext {
  return {
    ...context,
    promotedModelId: identity.modelId,
    promotedModelVersionId: identity.modelVersionId,
    promotedCandidateId: identity.candidateId,
    promotedTrainingRunId: identity.trainingRunId,
    promotedDatasetId: identity.datasetId,
    promotedDatasetVersionId: identity.datasetVersionId,
    promotedTarget: identity.target,
  };
}

export function projectContextMatchesPromotedModel(
  context: ProjectContext,
  identity: ExactPromotedModelIdentity,
) {
  return context.promotedModelId === identity.modelId
    && context.promotedModelVersionId === identity.modelVersionId
    && context.promotedCandidateId === identity.candidateId
    && context.promotedTrainingRunId === identity.trainingRunId
    && context.promotedDatasetId === identity.datasetId
    && context.promotedDatasetVersionId === identity.datasetVersionId
    && context.promotedTarget === identity.target;
}

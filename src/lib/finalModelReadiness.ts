/**
 * Pure fail-closed resolver for a durable final-model status response.
 *
 * Browser state is never proof that promotion succeeded. Readiness requires an
 * exact backend ModelVersion identity, verified serialized artifact, checksum,
 * and the immutable candidate lineage needed to recover that same version
 * after a process restart.
 */

export type FinalModelContextFields = {
  project_id?: string;
  dataset_id?: string;
  training_dataset_id?: string;
  dataset_version_id?: string;
  training_dataset_version_id?: string;
  target?: string;
  target_name?: string;
  candidate_id?: string;
  training_run_id?: string;
  feature_manifest_version?: string;
  validation_design_id?: string;
  split_id?: string;
  model_version_id?: string;
  modelVersionId?: string;
  artifact_verified?: boolean;
  artifactVerified?: boolean;
  artifact_verification_status?: string;
  artifactVerificationStatus?: string;
  artifact_checksum?: string;
  checksum?: string;
  promotion_status?: string;
  publicationStatus?: string;
  lineage_status?: string;
  lineageStatus?: string;
  champion_status?: string;
  designation?: string;
  candidate_decision_id?: string;
  candidateDecisionId?: string;
  evaluation_package_id?: string;
  evaluationPackageId?: string;
  holdout_exposure_id?: string;
  holdoutExposureId?: string;
  selection_integrity_status?: string;
  selectionIntegrityStatus?: string;
  holdout_isolation_status?: string;
  holdoutIsolationStatus?: string;
  evaluation_package_integrity_status?: string;
  evaluationPackageIntegrityStatus?: string;
  promotion_readiness_status?: string;
  promotionReadinessStatus?: string;
  final_holdout_status?: string;
  finalHoldoutStatus?: string;
};

export type ExpectedModelingContext = {
  projectId: string;
  datasetId?: string;
  datasetVersion: string;
  target: string;
};

export type DurableFinalModelIdentity = {
  modelVersionId: string;
  artifactVerificationStatus: string;
  trainingDatasetVersionId: string;
  promotionStatus: string;
  designation: string;
};

export type FinalModelReadinessView<M extends FinalModelContextFields> = {
  ready: boolean;
  metadata: M;
  durableIdentity: DurableFinalModelIdentity | null;
  error: string;
};

export const FINAL_MODEL_CONTEXT_MISMATCH_MESSAGE =
  "The saved final model does not match the exact project, registered dataset version, or target. Return to Interpretation and promote the current candidate.";

export const FINAL_MODEL_DURABILITY_MESSAGE =
  "Final-model promotion is not durable yet. A verified model version and complete candidate lineage are required.";

const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const resolved = text(value);
    if (resolved) return resolved;
  }
  return "";
}

function verificationStatus(metadata: FinalModelContextFields): string {
  if (metadata.artifact_verified === true || metadata.artifactVerified === true) return "verified";
  return firstText(metadata.artifact_verification_status, metadata.artifactVerificationStatus);
}

function isVerified(status: string): boolean {
  return /^(verified|ready|complete)$/i.test(status);
}

export function resolveFinalModelReadiness<M extends FinalModelContextFields>(
  data: { ready?: boolean; metadata?: M | null } | null | undefined,
  expected: ExpectedModelingContext,
): FinalModelReadinessView<M> {
  const metadata = (data?.metadata ?? {}) as M;
  const projectId = text(metadata.project_id);
  const datasetId = firstText(metadata.training_dataset_id, metadata.dataset_id);
  const datasetVersionId = firstText(
    metadata.training_dataset_version_id,
    metadata.dataset_version_id,
  );
  const target = firstText(metadata.target_name, metadata.target);
  const modelVersionId = firstText(metadata.model_version_id, metadata.modelVersionId);
  const artifactVerificationStatus = verificationStatus(metadata);
  const checksum = firstText(metadata.artifact_checksum, metadata.checksum);
  const promotionStatus = firstText(metadata.promotion_status, metadata.publicationStatus);
  const designation = firstText(metadata.champion_status, metadata.designation);
  const lineageStatus = firstText(metadata.lineage_status, metadata.lineageStatus);
  const candidateDecisionId = firstText(metadata.candidate_decision_id, metadata.candidateDecisionId);
  const evaluationPackageId = firstText(metadata.evaluation_package_id, metadata.evaluationPackageId);
  const holdoutExposureId = firstText(metadata.holdout_exposure_id, metadata.holdoutExposureId);
  const selectionIntegrityStatus = firstText(metadata.selection_integrity_status, metadata.selectionIntegrityStatus);
  const holdoutIsolationStatus = firstText(metadata.holdout_isolation_status, metadata.holdoutIsolationStatus);
  const evaluationPackageIntegrityStatus = firstText(metadata.evaluation_package_integrity_status, metadata.evaluationPackageIntegrityStatus);
  const promotionReadinessStatus = firstText(metadata.promotion_readiness_status, metadata.promotionReadinessStatus);
  const finalHoldoutStatus = firstText(metadata.final_holdout_status, metadata.finalHoldoutStatus);

  const contextMatches =
    Boolean(projectId && datasetVersionId && target) &&
    projectId === expected.projectId &&
    (!expected.datasetId || datasetId === expected.datasetId) &&
    datasetVersionId === expected.datasetVersion &&
    target === expected.target;
  const lineageComplete = Boolean(
    datasetId &&
      metadata.candidate_id &&
      metadata.training_run_id &&
      metadata.feature_manifest_version &&
      metadata.validation_design_id &&
      metadata.split_id &&
      candidateDecisionId &&
      evaluationPackageId &&
      holdoutExposureId &&
      selectionIntegrityStatus === "verified" &&
      holdoutIsolationStatus === "verified" &&
      evaluationPackageIntegrityStatus === "verified" &&
      promotionReadinessStatus === "verified" &&
      finalHoldoutStatus === "evaluated",
  );
  const durabilityComplete = Boolean(
    modelVersionId &&
      checksum &&
      isVerified(artifactVerificationStatus) &&
      lineageStatus === "verified" &&
      promotionStatus &&
      designation &&
      lineageComplete,
  );
  const backendReady = Boolean(data?.ready);
  const ready = backendReady && contextMatches && durabilityComplete;

  let error = "";
  if (backendReady && !contextMatches) error = FINAL_MODEL_CONTEXT_MISMATCH_MESSAGE;
  else if (backendReady && !durabilityComplete) error = FINAL_MODEL_DURABILITY_MESSAGE;

  return {
    ready,
    metadata: ready ? metadata : ({} as M),
    durableIdentity: ready
      ? {
          modelVersionId,
          artifactVerificationStatus,
          trainingDatasetVersionId: datasetVersionId,
          promotionStatus,
          designation,
        }
      : null,
    error,
  };
}

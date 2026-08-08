import type { CanonicalDatasetIdentity } from "../lib/datasetIdentity";
import type { InterpretationCandidate } from "../lib/interpretationCandidates";
import {
  resolvePromotionReadiness,
  type GovernedEvaluationPackage,
  type SelectionCandidateEvidence,
} from "../lib/selectionProvenance";

export type ExactPromotionGovernance = {
  candidateEvidence: SelectionCandidateEvidence;
  candidateDecision: unknown;
  evaluationPackage: GovernedEvaluationPackage;
};

export type DurablePromotion = {
  modelId: string;
  modelVersionId: string;
  promotionStatus: "finalized";
  designation: "champion" | "challenger";
  artifactVerified: true;
  artifactVerificationStatus: "verified";
  checksum: string;
  lineageStatus: "verified";
  trainingDatasetVersionId: string;
  idempotentReplay: boolean;
  championGeneration: number;
  candidateDecisionId: string;
  evaluationPackageId: string;
  selectionIntegrityStatus: "verified";
  holdoutIsolationStatus: "verified";
  evaluationPackageIntegrityStatus: "verified";
  promotionReadinessStatus: "verified";
  finalHoldoutStatus: "evaluated";
  holdoutExposureId: string;
};

export type ExactRecovery = {
  status: "ready";
  projectId: string;
  modelId: string;
  modelVersionId: string;
  publicationStatus: "finalized";
  lineageStatus: "verified";
  artifactVerified: true;
  checksum: string;
  artifactFormat: string;
};

export type ExactFinalModelHandoff = {
  candidateId?: string;
  trainingRunId?: string;
  candidateDecisionId?: string;
  evaluationPackageId?: string;
};

type PromotionResponse = {
  ok?: boolean;
  error?: string;
  detail?: string;
  metadata?: Record<string, unknown>;
  model?: Record<string, unknown>;
  modelVersion?: Record<string, unknown>;
  promotion?: Record<string, unknown>;
};

const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");

async function responseJson(response: Response): Promise<any> {
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    const detail = text(payload?.detail) || text(payload?.error);
    const correlationId = text(payload?.correlation_id) || text(payload?.correlationId);
    throw new Error(`${detail || `Request failed (${response.status})`}${correlationId ? ` Reference: ${correlationId}.` : ""}`);
  }
  return payload;
}

function assertEqual(actual: unknown, expected: string, label: string) {
  if (text(actual) !== expected) throw new Error(`Promotion returned a different ${label}; no final model was recorded.`);
}

function lineageValue(lineage: Record<string, unknown>, camel: string, snake: string) {
  return lineage[camel] ?? lineage[snake];
}

function normalizedExactHandoff(handoff: ExactFinalModelHandoff | undefined) {
  const normalized = {
    candidateId: text(handoff?.candidateId),
    trainingRunId: text(handoff?.trainingRunId),
    candidateDecisionId: text(handoff?.candidateDecisionId),
    evaluationPackageId: text(handoff?.evaluationPackageId),
  };
  const hasExplicitHandoff = Object.values(normalized).some(Boolean);
  if (hasExplicitHandoff && Object.values(normalized).some((value) => !value)) {
    throw new Error(
      "Exact final-model recovery requires candidate_id, training_run_id, candidate_decision_id, and evaluation_package_id from the same Evaluation handoff. No current-model fallback was used.",
    );
  }
  return hasExplicitHandoff ? normalized : null;
}

function exactVersionIdentity(
  version: Record<string, unknown>,
  metadata: Record<string, unknown>,
) {
  const lineage = (
    version.lineage && typeof version.lineage === "object"
      ? version.lineage
      : metadata.lineage && typeof metadata.lineage === "object"
        ? metadata.lineage
        : {}
  ) as Record<string, unknown>;
  return {
    candidateId: text(
      version.candidateId ?? version.candidate_id ?? metadata.candidate_id ??
      metadata.candidateId ?? lineageValue(lineage, "candidateId", "candidate_id"),
    ),
    trainingRunId: text(
      version.trainingRunId ?? version.training_run_id ?? metadata.training_run_id ??
      metadata.trainingRunId ?? lineageValue(lineage, "trainingRunId", "training_run_id"),
    ),
    candidateDecisionId: text(
      version.candidateDecisionId ?? version.candidate_decision_id ?? metadata.candidate_decision_id ??
      metadata.candidateDecisionId ?? lineageValue(lineage, "candidateDecisionId", "candidate_decision_id"),
    ),
    evaluationPackageId: text(
      version.evaluationPackageId ?? version.evaluation_package_id ?? metadata.evaluation_package_id ??
      metadata.evaluationPackageId ?? lineageValue(lineage, "evaluationPackageId", "evaluation_package_id"),
    ),
  };
}

function validatePromotion(
  payload: PromotionResponse,
  candidate: InterpretationCandidate,
  evaluationPackageId: string,
  candidateDecisionId: string,
): DurablePromotion {
  const model = payload.model ?? {};
  const version = payload.modelVersion ?? {};
  const promotion = payload.promotion ?? {};
  const lineage = (version.lineage && typeof version.lineage === "object" ? version.lineage : {}) as Record<string, unknown>;
  const modelId = text(version.modelId) || text(payload.metadata?.modelId);
  const modelVersionId = text(version.modelVersionId) || text(payload.metadata?.modelVersionId);
  const checksum = text(promotion.checksum) || text(version.checksum);
  const designation = text(promotion.designation);
  const selectionIntegrityStatus = text(version.selectionIntegrityStatus);
  const holdoutIsolationStatus = text(version.holdoutIsolationStatus);
  const evaluationPackageIntegrityStatus = text(version.evaluationPackageIntegrityStatus);
  const promotionReadinessStatus = text(version.promotionReadinessStatus);
  const finalHoldoutStatus = text(version.finalHoldoutStatus);
  const holdoutExposureId = text(version.holdoutExposureId);

  if (!modelId || !modelVersionId) throw new Error("Promotion did not return a durable model_version_id.");
  if (promotion.status !== "finalized") throw new Error("Model promotion did not finalize.");
  if (promotion.artifactVerified !== true || promotion.lineageStatus !== "verified" || !checksum) {
    throw new Error("The promoted model artifact or its lineage was not verified.");
  }
  if (designation !== "champion" && designation !== "challenger") {
    throw new Error("Promotion did not return a champion or challenger designation.");
  }
  if (designation === "champion" && text(model.currentVersionId) !== modelVersionId) {
    throw new Error("The champion pointer was not atomically updated to the promoted model version.");
  }
  assertEqual(version.projectId, candidate.project_id, "project_id");
  assertEqual(version.datasetId, candidate.dataset_id, "training_dataset_id");
  assertEqual(version.datasetVersionId, candidate.dataset_version_id, "training_dataset_version_id");
  assertEqual(version.trainingRunId, candidate.training_run_id, "training_run_id");
  assertEqual(version.featureManifestVersion, candidate.feature_manifest_version, "feature_manifest_version");
  assertEqual(version.evaluationPackageId, evaluationPackageId, "evaluation_package_id");
  assertEqual(version.candidateDecisionId, candidateDecisionId, "candidate_decision_id");
  assertEqual(lineageValue(lineage, "candidateId", "candidate_id"), candidate.candidate_id, "candidate_id");
  assertEqual(lineageValue(lineage, "trainingJobId", "training_job_id"), candidate.training_job_id, "training_job_id");
  assertEqual(lineageValue(lineage, "trainingRunId", "training_run_id"), candidate.training_run_id, "training_run_id");
  assertEqual(lineageValue(lineage, "splitId", "split_id"), candidate.split_id, "split_id");
  assertEqual(lineageValue(lineage, "validationDesignId", "validation_design_id"), candidate.validation_design_id, "validation_design_id");
  assertEqual(lineageValue(lineage, "validationDesignVersion", "validation_design_version"), candidate.validation_design_version, "validation_design_version");
  assertEqual(lineageValue(lineage, "featureManifestVersion", "feature_manifest_version"), candidate.feature_manifest_version, "feature_manifest_version");
  assertEqual(lineageValue(lineage, "target", "target_name"), candidate.target, "target");
  assertEqual(lineageValue(lineage, "candidateDecisionId", "candidate_decision_id"), candidateDecisionId, "candidate_decision_id lineage");
  if (
    selectionIntegrityStatus !== "verified" ||
    holdoutIsolationStatus !== "verified" ||
    evaluationPackageIntegrityStatus !== "verified" ||
    promotionReadinessStatus !== "verified" ||
    finalHoldoutStatus !== "evaluated" ||
    !holdoutExposureId
  ) {
    throw new Error("The durable model version does not preserve verified selection, Evaluation-package, and final-holdout isolation evidence.");
  }

  return {
    modelId,
    modelVersionId,
    promotionStatus: "finalized",
    designation,
    artifactVerified: true,
    artifactVerificationStatus: "verified",
    checksum,
    lineageStatus: "verified",
    trainingDatasetVersionId: candidate.dataset_version_id,
    idempotentReplay: promotion.idempotentReplay === true,
    championGeneration: Number(promotion.championGeneration) || 0,
    candidateDecisionId,
    evaluationPackageId,
    selectionIntegrityStatus: "verified",
    holdoutIsolationStatus: "verified",
    evaluationPackageIntegrityStatus: "verified",
    promotionReadinessStatus: "verified",
    finalHoldoutStatus: "evaluated",
    holdoutExposureId,
  };
}

export async function promoteExactCandidate(
  apiBase: string,
  candidate: InterpretationCandidate,
  evaluationPackageId: string,
  governance: ExactPromotionGovernance,
): Promise<DurablePromotion> {
  if (!text(evaluationPackageId)) {
    throw new Error("A completed exact evaluation_package_id is required before promotion.");
  }
  const readiness = resolvePromotionReadiness(
    governance.candidateEvidence,
    governance.candidateDecision,
    governance.evaluationPackage,
  );
  if (!readiness.ready || readiness.evaluationPackageId !== text(evaluationPackageId)) {
    throw new Error(readiness.reason || "Promotion requires verified selection and final-holdout isolation evidence.");
  }
  if (
    text(governance.candidateEvidence.candidate_id) !== candidate.candidate_id ||
    text(governance.candidateEvidence.training_run_id) !== candidate.training_run_id
  ) {
    throw new Error("Promotion governance does not match the exact candidate and training run.");
  }
  const response = await fetch(`${apiBase}/model/save_final`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      candidate_id: candidate.candidate_id,
      training_job_id: candidate.training_job_id,
      training_run_id: candidate.training_run_id,
      project_id: candidate.project_id,
      dataset_id: candidate.dataset_id,
      dataset_version_id: candidate.dataset_version_id,
      target: candidate.target,
      feature_manifest_version: candidate.feature_manifest_version,
      validation_design_id: candidate.validation_design_id,
      validation_design_version: candidate.validation_design_version,
      split_id: candidate.split_id,
      problem_type: candidate.task,
      evaluation_package_id: evaluationPackageId,
      candidate_decision_id: readiness.candidateDecisionId,
    }),
  });
  return validatePromotion(
    await responseJson(response),
    candidate,
    evaluationPackageId,
    readiness.candidateDecisionId,
  );
}

export async function verifyExactModelRecovery(
  apiBase: string,
  modelVersionId: string,
  projectId: string,
): Promise<ExactRecovery> {
  if (!modelVersionId) throw new Error("Exact model_version_id is required for restart recovery.");
  const response = await fetch(
    `${apiBase}/model-versions/${encodeURIComponent(modelVersionId)}/recovery-status?projectId=${encodeURIComponent(projectId)}`,
    { credentials: "include" },
  );
  const payload = await responseJson(response);
  const recovery = payload?.recovery ?? {};
  if (
    recovery.status !== "ready" ||
    recovery.publicationStatus !== "finalized" ||
    recovery.lineageStatus !== "verified" ||
    recovery.artifactVerified !== true ||
    !text(recovery.checksum) ||
    !text(recovery.artifactFormat)
  ) {
    throw new Error("The exact registered model version is not ready for restart recovery.");
  }
  assertEqual(recovery.projectId, projectId, "project_id");
  assertEqual(recovery.modelVersionId, modelVersionId, "model_version_id");
  return recovery as ExactRecovery;
}

export async function restoreExactFinalModel(
  apiBase: string,
  identity: CanonicalDatasetIdentity,
  target: string,
  expectedHandoff?: ExactFinalModelHandoff,
): Promise<{ promotion: DurablePromotion; recovery: ExactRecovery; metadata: Record<string, unknown> } | null> {
  const exactHandoff = normalizedExactHandoff(expectedHandoff);
  const params = new URLSearchParams({
    project_id: identity.project_id,
    dataset_id: identity.dataset_id,
    dataset_version_id: identity.dataset_version_id,
    target,
  });
  if (exactHandoff) {
    params.set("candidate_id", exactHandoff.candidateId);
    params.set("training_run_id", exactHandoff.trainingRunId);
    params.set("candidate_decision_id", exactHandoff.candidateDecisionId);
    params.set("evaluation_package_id", exactHandoff.evaluationPackageId);
  }
  const statusResponse = await fetch(`${apiBase}/model/final/status?${params.toString()}`, { credentials: "include" });
  const status = await responseJson(statusResponse);
  if (!status?.ready) return null;
  const metadata = (status.metadata ?? {}) as Record<string, unknown>;
  const version = (
    status.modelVersion && typeof status.modelVersion === "object"
      ? status.modelVersion
      : status.recovery?.modelVersion && typeof status.recovery.modelVersion === "object"
        ? status.recovery.modelVersion
        : metadata
  ) as Record<string, unknown>;
  const modelVersionId = text(metadata.model_version_id) || text(metadata.modelVersionId);
  if (!modelVersionId) throw new Error("Final-model status did not identify an exact registered model version.");
  assertEqual(metadata.project_id ?? metadata.projectId, identity.project_id, "project_id");
  assertEqual(metadata.training_dataset_id ?? metadata.dataset_id ?? metadata.datasetId, identity.dataset_id, "training_dataset_id");
  assertEqual(
    metadata.training_dataset_version_id ?? metadata.dataset_version_id ?? metadata.datasetVersionId,
    identity.dataset_version_id,
    "training_dataset_version_id",
  );
  assertEqual(metadata.target_name ?? metadata.target, target, "target");
  const restoredIdentity = exactVersionIdentity(version, metadata);
  if (exactHandoff) {
    try {
      assertEqual(restoredIdentity.candidateId, exactHandoff.candidateId, "candidate_id");
      assertEqual(restoredIdentity.trainingRunId, exactHandoff.trainingRunId, "training_run_id");
      assertEqual(restoredIdentity.candidateDecisionId, exactHandoff.candidateDecisionId, "candidate_decision_id");
      assertEqual(restoredIdentity.evaluationPackageId, exactHandoff.evaluationPackageId, "evaluation_package_id");
    } catch {
      throw new Error(
        "The registered final model does not match the exact Evaluation handoff. Promote this candidate explicitly before continuing; no current-model fallback was used.",
      );
    }
  }
  const recovery = await verifyExactModelRecovery(apiBase, modelVersionId, identity.project_id);
  const designation = text(metadata.designation ?? metadata.champion_status);
  if (designation !== "champion" && designation !== "challenger") {
    throw new Error("Final-model status is missing its champion or challenger designation.");
  }
  const candidateDecisionId = text(version.candidateDecisionId ?? metadata.candidate_decision_id);
  const evaluationPackageId = text(version.evaluationPackageId ?? metadata.evaluation_package_id);
  const holdoutExposureId = text(version.holdoutExposureId ?? metadata.holdout_exposure_id);
  if (
    !candidateDecisionId ||
    !evaluationPackageId ||
    !holdoutExposureId ||
    text(version.selectionIntegrityStatus ?? metadata.selection_integrity_status) !== "verified" ||
    text(version.holdoutIsolationStatus ?? metadata.holdout_isolation_status) !== "verified" ||
    text(version.evaluationPackageIntegrityStatus ?? metadata.evaluation_package_integrity_status) !== "verified" ||
    text(version.promotionReadinessStatus ?? metadata.promotion_readiness_status) !== "verified" ||
    text(version.finalHoldoutStatus ?? metadata.final_holdout_status) !== "evaluated"
  ) {
    throw new Error("The registered model version does not preserve verified candidate-decision and final-holdout isolation evidence.");
  }
  const promotion: DurablePromotion = {
    modelId: recovery.modelId,
    modelVersionId,
    promotionStatus: "finalized",
    designation,
    artifactVerified: true,
    artifactVerificationStatus: "verified",
    checksum: recovery.checksum,
    lineageStatus: "verified",
    trainingDatasetVersionId: identity.dataset_version_id,
    idempotentReplay: false,
    championGeneration: Number(metadata.champion_generation ?? metadata.championGeneration) || 0,
    candidateDecisionId,
    evaluationPackageId,
    selectionIntegrityStatus: "verified",
    holdoutIsolationStatus: "verified",
    evaluationPackageIntegrityStatus: "verified",
    promotionReadinessStatus: "verified",
    finalHoldoutStatus: "evaluated",
    holdoutExposureId,
  };
  return { promotion, recovery, metadata };
}

import {
  buildCanonicalEvidenceEnvelope,
  requireCanonicalDatasetIdentity,
  type CanonicalDatasetIdentityInput,
} from "./datasetIdentity";
import {
  createEvidence,
  type EvidenceItem,
  type EvidenceType,
} from "./evidenceGraph";

export type PredictiveWorkflowCompletionStep = "step10" | "step11" | "step12" | "step13";

export type PredictiveWorkflowModelIdentity = {
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
  target: string;
};

export type PredictiveWorkflowCompletionEvidenceInput = {
  datasetIdentity: CanonicalDatasetIdentityInput;
  projectName: string;
  stepId: PredictiveWorkflowCompletionStep;
  evidenceType: EvidenceType;
  artifactType?: string;
  artifactId?: string;
  title: string;
  summary: string;
  supportsSections: string[];
  tags: string[];
  documentIds?: string[];
  model: PredictiveWorkflowModelIdentity;
  payload?: Record<string, unknown>;
};

function safeEvidenceToken(value: string) {
  return value.replace(/[^A-Za-z0-9_.-]/g, "_");
}

export function buildPredictiveWorkflowCompletionEvidence(
  input: PredictiveWorkflowCompletionEvidenceInput,
): Partial<EvidenceItem> {
  const identity = requireCanonicalDatasetIdentity(
    input.datasetIdentity,
    `${input.stepId} completion evidence`,
  );
  const exactModel = {
    modelId: input.model.modelId.trim(),
    modelVersionId: input.model.modelVersionId.trim(),
    modelName: input.model.modelName.trim(),
    candidateId: input.model.candidateId.trim(),
    trainingRunId: input.model.trainingRunId.trim(),
    featureManifestVersion: input.model.featureManifestVersion.trim(),
    validationDesignId: input.model.validationDesignId.trim(),
    splitId: input.model.splitId.trim(),
    artifactChecksum: input.model.artifactChecksum.trim(),
    artifactVerificationStatus: input.model.artifactVerificationStatus.trim().toLowerCase(),
    target: input.model.target.trim(),
  };
  if (
    Object.values(exactModel).some((value) => !value)
    || exactModel.artifactVerificationStatus !== "verified"
  ) {
    throw new Error(
      `${input.stepId} completion requires the full checksum-verified promoted-model lineage.`,
    );
  }
  const evidenceId = [
    "ev",
    "predictive-workflow-completion",
    input.stepId,
    identity.project_id,
    exactModel.modelVersionId,
  ].map(safeEvidenceToken).join("-");
  const modelIds = [exactModel.modelId, exactModel.modelVersionId]
    .map((value) => String(value ?? "").trim())
    .filter((value, index, values) => Boolean(value) && values.indexOf(value) === index);

  return {
    evidenceId,
    ...buildCanonicalEvidenceEnvelope(identity, {
      workflowStep: input.stepId,
      ...exactModel,
    }),
    projectName: input.projectName,
    evidenceType: input.evidenceType,
    artifactType: input.artifactType ?? input.evidenceType,
    artifactId: input.artifactId ?? exactModel.modelVersionId,
    title: input.title,
    summary: input.summary,
    sourcePage: input.title,
    sourceRoute: `/${input.stepId}`,
    workflowStep: input.stepId,
    datasetIds: [identity.dataset_id],
    modelIds,
    documentIds: input.documentIds ?? [],
    notebookIds: [],
    supportsSections: input.supportsSections,
    tags: [
      "predictive_modeling",
      "workflow_completion",
      input.stepId,
      ...input.tags,
    ],
    status: "ready",
    importance: "high",
    payload: {
      workflowCompletionContract: "predictive_workflow_completion_v1",
      stepId: input.stepId,
      ...exactModel,
      ...input.payload,
    },
    governance: {
      completionAuthority: "durable_canonical_evidence",
      browserFallbackUsed: false,
      exactDatasetVersionRequired: true,
      exactPromotedModelVersionRequired: true,
    },
  };
}

export async function persistPredictiveWorkflowCompletionEvidence(
  input: PredictiveWorkflowCompletionEvidenceInput,
) {
  return createEvidence(
    buildPredictiveWorkflowCompletionEvidence(input),
    { requireDatabaseMirror: true },
  );
}

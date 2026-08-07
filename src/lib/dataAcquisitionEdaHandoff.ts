import {
  fetchSpecialValueReview,
  type SpecialValueReviewContract,
  type SpecialValueReviewLineage,
} from "./bureauDetection";
import {
  fetchDataAcquisitionReproducibilityContext,
  requireCurrentDataAcquisitionReproducibilityContext,
  type CurrentDataAcquisitionReproducibilityContext,
  type DataAcquisitionReproducibilityContext,
} from "./dataAcquisitionReproducibility";
import {
  assertExactDatasetIdentity,
  requireCanonicalDatasetIdentity,
  type CanonicalDatasetIdentity,
} from "./datasetIdentity";
import {
  fetchBureauSemanticAnnotations,
  type BureauSemanticAnnotationContract,
} from "./bureauSemanticAnnotations";

export type DataAcquisitionEdaPrerequisiteCode =
  | "dataset_identity_required"
  | "target_contract_required"
  | "analysis_partition_required"
  | "special_value_review_incomplete"
  | "data_acquisition_handoff_mismatch";

export class DataAcquisitionEdaHandoffError extends Error {
  readonly code: DataAcquisitionEdaPrerequisiteCode;
  readonly recovery: string;

  constructor(
    code: DataAcquisitionEdaPrerequisiteCode,
    message: string,
    recovery: string,
  ) {
    super(message);
    this.name = "DataAcquisitionEdaHandoffError";
    this.code = code;
    this.recovery = recovery;
  }
}

export type CanonicalDataAcquisitionEdaHandoff = {
  context: CurrentDataAcquisitionReproducibilityContext;
  datasetIdentity: CanonicalDatasetIdentity;
  specialValueReview: SpecialValueReviewContract;
  bureauSemanticAnnotations: BureauSemanticAnnotationContract;
};

function prerequisiteError(
  context: DataAcquisitionReproducibilityContext,
): DataAcquisitionEdaHandoffError {
  if (context.state === "identity_pending") {
    return new DataAcquisitionEdaHandoffError(
      "dataset_identity_required",
      "An exact registered Dataset Library version must be activated before EDA can open.",
      "Return to Data Acquisition and activate the intended dataset version.",
    );
  }
  if (context.state === "target_pending") {
    return new DataAcquisitionEdaHandoffError(
      "target_contract_required",
      "The target mapping and predictor authorization must be confirmed before EDA can open.",
      "Return to Data Acquisition and confirm the target, class mapping, and eligible predictors.",
    );
  }
  return new DataAcquisitionEdaHandoffError(
    "analysis_partition_required",
    "A current sealed Analysis Partition must be confirmed before EDA can open.",
    "Return to Data Acquisition and create or verify the governed development/final-holdout partition.",
  );
}

export function datasetIdentityFromReproducibilityContext(
  context: CurrentDataAcquisitionReproducibilityContext,
): CanonicalDatasetIdentity {
  return requireCanonicalDatasetIdentity(
    {
      project_id: context.project_id,
      dataset_id: context.identity.dataset_id,
      dataset_version_id: context.identity.dataset_version_id,
      activation_revision: context.identity.activation_revision,
      dataset_version_label: context.identity.dataset_version_label,
      dataset_source_type: context.identity.source_type,
    },
    "Data Acquisition to EDA handoff identity",
  );
}

export function requireCanonicalDataAcquisitionContext(
  context: DataAcquisitionReproducibilityContext,
  expectedProjectId: string,
  expectedIdentity?: CanonicalDatasetIdentity | null,
): CurrentDataAcquisitionReproducibilityContext {
  if (context.project_id !== expectedProjectId) {
    throw new DataAcquisitionEdaHandoffError(
      "data_acquisition_handoff_mismatch",
      "The Data Acquisition handoff belongs to a different project.",
      "Reload the current project before continuing to EDA.",
    );
  }
  if (context.state !== "current") throw prerequisiteError(context);
  const current = requireCurrentDataAcquisitionReproducibilityContext(context);
  const identity = datasetIdentityFromReproducibilityContext(current);
  if (expectedIdentity) {
    try {
      assertExactDatasetIdentity(
        expectedIdentity,
        identity,
        "Data Acquisition to EDA handoff",
      );
      if (
        expectedIdentity.activation_revision != null &&
        expectedIdentity.activation_revision !== identity.activation_revision
      ) {
        throw new Error("activation revision mismatch");
      }
    } catch {
      throw new DataAcquisitionEdaHandoffError(
        "data_acquisition_handoff_mismatch",
        "The backend Data Acquisition handoff no longer matches the active dataset activation.",
        "Reload Data Acquisition and verify the exact registered dataset version before continuing.",
      );
    }
  }
  return current;
}

export function specialValueReviewLineageFromContext(
  context: CurrentDataAcquisitionReproducibilityContext,
): SpecialValueReviewLineage {
  return {
    projectId: context.project_id,
    datasetIdentity: datasetIdentityFromReproducibilityContext(context),
    activationRevision: context.identity.activation_revision,
    predictorAuthorizationId:
      context.predictor_authorization.predictor_authorization_id,
    targetContractId: context.target_contract.target_contract_id,
    analysisPartitionId:
      context.analysis_partition.analysis_partition_id,
    analysisPartitionRevision: context.analysis_partition.revision,
  };
}

export function requireCompletedSpecialValueReview(
  review: SpecialValueReviewContract,
): SpecialValueReviewContract {
  const complete =
    (review.status === "confirmed" || review.status === "not_required") &&
    review.open_count === 0 &&
    review.blocks_continuation === false;
  if (!complete) {
    throw new DataAcquisitionEdaHandoffError(
      "special_value_review_incomplete",
      "Special-Value Treatment Review is incomplete.",
      review.open_count > 0
        ? `Return to Data Acquisition and resolve ${review.open_count.toLocaleString()} remaining special-value treatment item${review.open_count === 1 ? "" : "s"}.`
        : "Return to Data Acquisition and confirm the Special-Value Treatment Review.",
    );
  }
  return review;
}

export async function fetchCanonicalDataAcquisitionEdaHandoff(input: {
  projectId: string;
  expectedIdentity?: CanonicalDatasetIdentity | null;
  context?: DataAcquisitionReproducibilityContext | null;
  signal?: AbortSignal;
}): Promise<CanonicalDataAcquisitionEdaHandoff> {
  const context =
    input.context ??
    (await fetchDataAcquisitionReproducibilityContext(
      input.projectId,
      input.signal,
    ));
  const current = requireCanonicalDataAcquisitionContext(
    context,
    input.projectId,
    input.expectedIdentity,
  );
  const datasetIdentity = datasetIdentityFromReproducibilityContext(current);
  const [specialValueReviewResponse, bureauSemanticAnnotations] =
    await Promise.all([
      fetchSpecialValueReview({
      lineage: specialValueReviewLineageFromContext(current),
      signal: input.signal,
      }),
      fetchBureauSemanticAnnotations({
        projectId: input.projectId,
        datasetIdentity,
        signal: input.signal,
      }),
    ]);
  const specialValueReview = requireCompletedSpecialValueReview(
    specialValueReviewResponse,
  );
  return {
    context: current,
    datasetIdentity,
    specialValueReview,
    bureauSemanticAnnotations,
  };
}

export function buildCanonicalEdaRequestContract(
  handoff: CanonicalDataAcquisitionEdaHandoff,
) {
  const { context, specialValueReview, bureauSemanticAnnotations } = handoff;
  const annotationSet =
    bureauSemanticAnnotations.state === "available"
      ? bureauSemanticAnnotations.annotationSet
      : null;
  return {
    project_id: context.project_id,
    dataset_id: context.identity.dataset_id,
    dataset_version_id: context.identity.dataset_version_id,
    activation_revision: context.identity.activation_revision,
    target_contract_id: context.target_contract.target_contract_id,
    target: context.target_contract.target,
    positive_value: context.target_contract.event_value,
    negative_value: context.target_contract.non_event_value,
    event_value: context.target_contract.event_value,
    non_event_value: context.target_contract.non_event_value,
    predictor_authorization_id:
      context.predictor_authorization.predictor_authorization_id,
    analysis_partition_id:
      context.analysis_partition.analysis_partition_id,
    analysis_partition_revision: context.analysis_partition.revision,
    special_value_review_id: specialValueReview.special_value_review_id,
    special_value_review_revision: specialValueReview.revision,
    bureau_semantic_annotation_state: bureauSemanticAnnotations.state,
    bureau_semantic_annotation_set_id: annotationSet?.annotationSetId ?? null,
    bureau_semantic_annotation_set_checksum:
      annotationSet?.annotationSetChecksum ?? null,
    bureau_metadata_schema_checksum: annotationSet?.schemaChecksum ?? null,
    bureau_metadata_binding_id: annotationSet?.bindingId ?? null,
    bureau_metadata_binding_revision: annotationSet?.bindingRevision ?? null,
    bureau_metadata_binding_revision_checksum:
      annotationSet?.bindingRevisionChecksum ?? null,
    bureau_metadata_crosswalk_id: annotationSet?.crosswalkId ?? null,
    bureau_metadata_crosswalk_revision:
      annotationSet?.crosswalkRevision ?? null,
    bureau_metadata_crosswalk_revision_checksum:
      annotationSet?.crosswalkRevisionChecksum ?? null,
    bureau_metadata_catalog_version_id:
      annotationSet?.catalogVersionId ?? null,
    bureau_metadata_catalog_checksum: annotationSet?.catalogChecksum ?? null,
    // Transitional equality assertions retained for older analytical routes.
    expected_dataset_id: context.identity.dataset_id,
    expected_dataset_version_id: context.identity.dataset_version_id,
    dataset_version: context.identity.dataset_version_id,
  } as const;
}

export function assertExactEdaResponseLineage(
  handoff: CanonicalDataAcquisitionEdaHandoff,
  value: unknown,
) {
  const payload = value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
  assertExactDatasetIdentity(
    handoff.datasetIdentity,
    payload,
    "EDA analytical response",
  );
  const expected = buildCanonicalEdaRequestContract(handoff);
  const comparisons: Array<[string, unknown, unknown]> = [
    ["activation_revision", expected.activation_revision, payload.activation_revision],
    ["target_contract_id", expected.target_contract_id, payload.target_contract_id],
    ["target", expected.target, payload.target],
    ["positive_value", expected.positive_value, payload.positive_value ?? payload.event_value],
    ["negative_value", expected.negative_value, payload.negative_value ?? payload.non_event_value],
    ["predictor_authorization_id", expected.predictor_authorization_id, payload.predictor_authorization_id ?? (payload.predictor_authorization as Record<string, unknown> | undefined)?.predictor_authorization_id ?? (payload.predictor_authorization as Record<string, unknown> | undefined)?.manifest_version],
    ["analysis_partition_id", expected.analysis_partition_id, payload.analysis_partition_id ?? (payload.analysis_scope as Record<string, unknown> | undefined)?.partition_id],
    ["analysis_partition_revision", expected.analysis_partition_revision, payload.analysis_partition_revision ?? (payload.analysis_scope as Record<string, unknown> | undefined)?.partition_revision],
    ["special_value_review_id", expected.special_value_review_id, payload.special_value_review_id],
    ["special_value_review_revision", expected.special_value_review_revision, payload.special_value_review_revision],
  ];
  const mismatch = comparisons.find(([, expectedValue, actualValue]) =>
    String(expectedValue ?? "") !== String(actualValue ?? ""),
  );
  if (mismatch) {
    throw new DataAcquisitionEdaHandoffError(
      "data_acquisition_handoff_mismatch",
      `The EDA response does not match the exact ${mismatch[0]} from Data Acquisition.`,
      "Discard the stale response and reload the current project-scoped EDA route.",
    );
  }
  const nestedSemanticLineage =
    payload.bureau_semantic_annotations &&
    typeof payload.bureau_semantic_annotations === "object"
      ? (payload.bureau_semantic_annotations as Record<string, unknown>)
      : {};
  const nestedAnnotationSet =
    nestedSemanticLineage.annotation_set &&
    typeof nestedSemanticLineage.annotation_set === "object"
      ? (nestedSemanticLineage.annotation_set as Record<string, unknown>)
      : nestedSemanticLineage;
  const responseSemanticLineage = {
    ...nestedSemanticLineage,
    ...payload,
    bureau_semantic_annotation_state:
      payload.bureau_semantic_annotation_state ??
      nestedSemanticLineage.bureau_semantic_annotation_state ??
      nestedSemanticLineage.state ??
      (Object.keys(nestedAnnotationSet).length ? "available" : undefined),
    bureau_semantic_annotation_set_id:
      payload.bureau_semantic_annotation_set_id ??
      nestedAnnotationSet.annotation_set_id,
    bureau_semantic_annotation_set_checksum:
      payload.bureau_semantic_annotation_set_checksum ??
      nestedAnnotationSet.annotation_set_checksum,
    bureau_metadata_schema_checksum:
      payload.bureau_metadata_schema_checksum ?? nestedAnnotationSet.schema_checksum,
    bureau_metadata_binding_id:
      payload.bureau_metadata_binding_id ?? nestedAnnotationSet.binding_id,
    bureau_metadata_binding_revision:
      payload.bureau_metadata_binding_revision ?? nestedAnnotationSet.binding_revision,
    bureau_metadata_binding_revision_checksum:
      payload.bureau_metadata_binding_revision_checksum ??
      nestedAnnotationSet.binding_revision_checksum,
    bureau_metadata_crosswalk_id:
      payload.bureau_metadata_crosswalk_id ?? nestedAnnotationSet.crosswalk_id,
    bureau_metadata_crosswalk_revision:
      payload.bureau_metadata_crosswalk_revision ??
      nestedAnnotationSet.crosswalk_revision,
    bureau_metadata_crosswalk_revision_checksum:
      payload.bureau_metadata_crosswalk_revision_checksum ??
      nestedAnnotationSet.crosswalk_revision_checksum,
    bureau_metadata_catalog_version_id:
      payload.bureau_metadata_catalog_version_id ??
      nestedAnnotationSet.catalog_version_id,
    bureau_metadata_catalog_checksum:
      payload.bureau_metadata_catalog_checksum ?? nestedAnnotationSet.catalog_checksum,
  };
  const semanticLineageKeys = [
    "bureau_semantic_annotation_state",
    "bureau_semantic_annotation_set_id",
    "bureau_semantic_annotation_set_checksum",
    "bureau_metadata_schema_checksum",
    "bureau_metadata_binding_id",
    "bureau_metadata_binding_revision",
    "bureau_metadata_binding_revision_checksum",
    "bureau_metadata_crosswalk_id",
    "bureau_metadata_crosswalk_revision",
    "bureau_metadata_crosswalk_revision_checksum",
    "bureau_metadata_catalog_version_id",
    "bureau_metadata_catalog_checksum",
  ] as const;
  if (
    Object.keys(nestedSemanticLineage).length > 0 ||
    semanticLineageKeys.some((key) => responseSemanticLineage[key] !== undefined)
  ) {
    const semanticMismatch = semanticLineageKeys.find(
      (key) =>
        String(expected[key] ?? "") !==
        String(responseSemanticLineage[key] ?? ""),
    );
    if (semanticMismatch) {
      throw new DataAcquisitionEdaHandoffError(
        "data_acquisition_handoff_mismatch",
        `The EDA response does not match the exact ${semanticMismatch} from the current bureau metadata annotation set.`,
        "Discard the stale metadata response and reload the current project-scoped EDA route.",
      );
    }
  }
  const analysisScope = payload.analysis_scope && typeof payload.analysis_scope === "object"
    ? payload.analysis_scope as Record<string, unknown>
    : {};
  const governedScope = payload.governed_analysis_scope && typeof payload.governed_analysis_scope === "object"
    ? payload.governed_analysis_scope as Record<string, unknown>
    : {};
  const exclusionReasons = Array.isArray(analysisScope.exclusionReasons)
    ? analysisScope.exclusionReasons.map(String)
    : [];
  const finalHoldoutAccessed =
    payload.final_holdout_accessed ??
    governedScope.final_holdout_accessed ??
    analysisScope.finalHoldoutAccessed;
  if (
    payload.scope !== "development_population" ||
    finalHoldoutAccessed !== false ||
    !exclusionReasons.includes("sealed_final_holdout_excluded")
  ) {
    throw new DataAcquisitionEdaHandoffError(
      "data_acquisition_handoff_mismatch",
      "The EDA response did not prove development-only target-directed scope and final-holdout exclusion.",
      "Stop analysis and revalidate the current Analysis Partition authority.",
    );
  }
  return payload;
}

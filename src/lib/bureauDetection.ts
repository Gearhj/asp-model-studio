import {
  BUREAU_METADATA_KEY,
  BUREAU_TREATMENT_KEY,
  loadBureauTreatmentDecisions,
} from "./creditBureau";
import type { CanonicalDatasetIdentity } from "./datasetIdentity";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

export const BUREAU_REVIEW_KEY = "atlas-predictive-bureau-review-v2";

export type BureauDeclaration = "auto" | "contains" | "does_not_contain" | "manual_review";
export type BureauHandling =
  | "preserve_informative"
  | "convert_to_missing"
  | "convert_to_category"
  | "documented_domain_mapping"
  | "exclude_variable"
  | "leave_unchanged"
  | "custom";

export type BureauReviewDecision = {
  variable: string;
  value: number;
  handling: BureauHandling;
  rationale: string;
  replacementValue?: string;
  updatedAt: string;
  override: true;
};

export type BureauVariableDefault = {
  variable: string;
  handling: BureauHandling;
  rationale: string;
  replacementValue?: string;
  updatedAt: string;
};

export type BureauDetectionVariable = {
  variable: string;
  confidence: number;
  reasons: string[];
  datatype: string;
  special_value_count: number;
  special_value_frequency: number;
  ordinary_value_count: number;
  null_count: number;
  parse_failure_count: number;
  likely_bureau: boolean;
  special_values: Array<{
    value: number;
    definition: string;
    count: number;
    frequency: number;
    event_count: number | null;
    event_rate: number | null;
    regular_event_rate: number | null;
    event_rate_delta: number | null;
    recommended_handling: string;
  }>;
};

export type BureauDetectionResponse = {
  ok: boolean;
  scope: "full_dataset";
  analysis_scope: "mixed_governed_scopes";
  structural_scope: "full_governed_population_predictors_only";
  row_count: number;
  full_governed_population_rows: number;
  target: string | null;
  event_value: unknown;
  detected: boolean;
  confidence: number;
  manual_declaration: BureauDeclaration;
  reasons: string[];
  likely_variable_count: number;
  variables_with_special_values: number;
  rows_with_special_values: number;
  variables: BureauDetectionVariable[];
  metadata_source: string;
  reviewed_at: string;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  activation_revision: number;
  predictor_authorization_id: string;
  target_contract_id: string;
  correlation_id: string;
  target_analysis_scope: "development_population" | "not_available";
  analysis_partition_id: string | null;
  analysis_partition_revision: number | null;
  development_partition_id: string | null;
  analysis_partition_assignment_hash: string | null;
  analysis_partition_artifact_hash: string | null;
  development_target_checksum: string | null;
  scope_contract: {
    structural_evidence: "full_governed_population_predictors_only";
    target_evidence: "development_population" | "not_available";
    single_scope_inference_allowed: false;
  };
  structural_evidence: {
    scope: "full_governed_population_predictors_only";
    population_count: number;
    target_accessed: false;
    measures: string[];
  };
  target_evidence: {
    available: boolean;
    status: "available" | "unavailable";
    scope: "development_population" | "not_available";
    population_id: string | null;
    population_count: number;
    analysis_partition_id: string | null;
    analysis_partition_revision: number | null;
    assignment_hash: string | null;
    artifact_hash: string | null;
    source_checksum: string | null;
    development_target_checksum: string | null;
    holdout_excluded: true;
    final_holdout_accessed: false;
    measures: string[];
  };
  final_holdout_accessed: false;
  special_value_review: SpecialValueReviewContract;
};

export type SpecialValueReviewStatus =
  | "not_required"
  | "not_started"
  | "in_review"
  | "ready_for_confirmation"
  | "confirmed";

export type SpecialValueReviewVariableDecision = {
  variable: string;
  policy: BureauHandling;
  rationale: string;
  replacement_value?: unknown;
  overrides: Array<{
    value: unknown;
    policy: BureauHandling;
    rationale: string;
    replacement_value?: unknown;
  }>;
};

/**
 * Durable, exact-version authority returned by FastAPI. Browser state is never
 * accepted as a substitute for this contract.
 */
export type SpecialValueReviewContract = {
  special_value_review_id: string;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  activation_revision: number;
  predictor_authorization_id: string;
  target_contract_id: string;
  analysis_partition_id: string | null;
  analysis_partition_revision: number | null;
  development_partition_id: string | null;
  analysis_partition_assignment_hash: string | null;
  analysis_partition_artifact_hash: string | null;
  development_target_checksum: string | null;
  source_checksum: string | null;
  structural_scope: "full_governed_population_predictors_only";
  target_analysis_scope: "development_population" | "not_available";
  target_evidence_available: boolean;
  target_evidence_status: "available" | "unavailable";
  target_evidence_unavailable_reason: string;
  full_governed_population_rows: number;
  development_rows: number;
  detection_fingerprint: string;
  status: SpecialValueReviewStatus;
  detected_count: number;
  reviewed_count: number;
  open_count: number;
  open_items: string[];
  blocks_confirmation: boolean;
  blocks_continuation: boolean;
  confirmation_allowed: boolean;
  revision: number;
  variable_decisions: SpecialValueReviewVariableDecision[];
  reviewer_rationale: string;
  confirmed_at: string | null;
  updated_at: string | null;
  authority: "backend_durable_exact_version";
  browser_cache_authority: false;
};

export type SpecialValueReviewLineage = {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  activationRevision: number;
  predictorAuthorizationId: string;
  targetContractId: string;
  analysisPartitionId?: string | null;
  analysisPartitionRevision?: number | null;
};

export type BureauReviewDraftAuthority = {
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  activation_revision: number;
  predictor_authorization_id: string;
  target_contract_id: string;
  analysis_partition_id: string | null;
  analysis_partition_revision: number | null;
  detection_fingerprint: string;
  special_value_review_id: string;
  special_value_review_revision: number;
};

export type BureauReviewState = {
  declaration: BureauDeclaration;
  rationale: string;
  decisions: BureauReviewDecision[];
  variableDefaults: BureauVariableDefault[];
  status: "draft" | "confirmed";
  evidenceStatus: "not_recorded" | "draft" | "ready" | "stale";
  evidenceId?: string;
  evidenceReviewRevision?: number;
  confirmedAt?: string;
  savedAt?: string;
  /** Exact scope for this non-authoritative browser draft cache. */
  draftAuthority?: BureauReviewDraftAuthority;
};

function positiveInteger(value: unknown) {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function nonnegativeInteger(value: unknown) {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function requiredText(value: unknown) {
  return typeof value === "string" && value.trim().length > 0;
}

export type SpecialValueReviewContractErrorKind =
  | "missing"
  | "identity_mismatch"
  | "incomplete"
  | "contradictory";

export class SpecialValueReviewContractError extends Error {
  readonly kind: SpecialValueReviewContractErrorKind;

  constructor(kind: SpecialValueReviewContractErrorKind, message: string) {
    super(message);
    this.name = "SpecialValueReviewContractError";
    this.kind = kind;
  }
}

/**
 * A same-identity review written before the current durable contract may be
 * refreshed by running exact automatic detection again. Identity or lineage
 * contradictions remain fail-closed and are never treated as legacy state.
 */
export function isRefreshableLegacySpecialValueReviewError(error: unknown) {
  if (
    error instanceof SpecialValueReviewContractError &&
    error.kind === "incomplete"
  ) {
    return true;
  }
  // The backend reports a durable review written before the current contract
  // schema as `special_value_review_stale` with the offending fields named.
  // Re-running exact detection regenerates it; identity contradictions never
  // reach here because the backend raises those with a different code.
  return (
    error instanceof SpecialValueReviewApiError &&
    error.code === "special_value_review_stale" &&
    error.supersededContractFields.length > 0
  );
}

export function assertSpecialValueReviewContract(
  value: unknown,
  lineage: SpecialValueReviewLineage,
): SpecialValueReviewContract {
  const contract = value as Partial<SpecialValueReviewContract> | null;
  if (!contract || typeof contract !== "object") {
    throw new SpecialValueReviewContractError(
      "missing",
      "The backend did not return a durable special-value review contract.",
    );
  }
  const identity = lineage.datasetIdentity;
  const exactIdentity =
    contract.project_id === lineage.projectId &&
    contract.project_id === identity.project_id &&
    contract.dataset_id === identity.dataset_id &&
    contract.dataset_version_id === identity.dataset_version_id;
  const exactLineage =
    contract.activation_revision === lineage.activationRevision &&
    contract.predictor_authorization_id === lineage.predictorAuthorizationId &&
    contract.target_contract_id === lineage.targetContractId;
  const expectedPartitionId = lineage.analysisPartitionId ?? null;
  const expectedPartitionRevision = lineage.analysisPartitionRevision ?? null;
  const completePartitionExpectation =
    Boolean(expectedPartitionId) === (expectedPartitionRevision != null);
  const exactPartitionLineage =
    !expectedPartitionId ||
    (contract.analysis_partition_id === expectedPartitionId &&
      contract.analysis_partition_revision === expectedPartitionRevision);
  const identityRevision = identity.activation_revision;
  if (
    !exactIdentity ||
    !exactLineage ||
    !completePartitionExpectation ||
    !exactPartitionLineage ||
    (identityRevision != null && contract.activation_revision !== identityRevision)
  ) {
    throw new SpecialValueReviewContractError(
      "identity_mismatch",
      "The durable special-value review does not match the exact project, dataset version, activation, predictor authorization, target contract, and development-partition lineage.",
    );
  }
  if (
    contract.authority !== "backend_durable_exact_version" ||
    contract.browser_cache_authority !== false ||
    !positiveInteger(contract.activation_revision) ||
    !positiveInteger(contract.revision) ||
    !requiredText(contract.special_value_review_id) ||
    !requiredText(contract.detection_fingerprint) ||
    !requiredText(contract.predictor_authorization_id) ||
    !requiredText(contract.target_contract_id) ||
    contract.structural_scope !==
      "full_governed_population_predictors_only" ||
    !requiredText(contract.source_checksum) ||
    !positiveInteger(contract.full_governed_population_rows) ||
    typeof contract.target_evidence_available !== "boolean" ||
    !["available", "unavailable"].includes(
      String(contract.target_evidence_status),
    ) ||
    !["development_population", "not_available"].includes(
      String(contract.target_analysis_scope),
    ) ||
    !Array.isArray(contract.variable_decisions) ||
    !Array.isArray(contract.open_items) ||
    ![
      "not_required",
      "not_started",
      "in_review",
      "ready_for_confirmation",
      "confirmed",
    ].includes(String(contract.status)) ||
    typeof contract.blocks_confirmation !== "boolean" ||
    typeof contract.blocks_continuation !== "boolean" ||
    typeof contract.confirmation_allowed !== "boolean" ||
    !nonnegativeInteger(contract.detected_count) ||
    !nonnegativeInteger(contract.reviewed_count) ||
    !nonnegativeInteger(contract.open_count)
  ) {
    throw new SpecialValueReviewContractError(
      "incomplete",
      "The backend special-value review authority is incomplete or invalid.",
    );
  }
  const detectedCount = contract.detected_count as number;
  const reviewedCount = contract.reviewed_count as number;
  const openCount = contract.open_count as number;
  const targetEvidenceCoherent = contract.target_evidence_available
    ? contract.target_evidence_status === "available" &&
      contract.target_analysis_scope === "development_population" &&
      requiredText(contract.analysis_partition_id) &&
      positiveInteger(contract.analysis_partition_revision) &&
      requiredText(contract.development_partition_id) &&
      requiredText(contract.analysis_partition_assignment_hash) &&
      requiredText(contract.analysis_partition_artifact_hash) &&
      requiredText(contract.development_target_checksum) &&
      requiredText(contract.source_checksum) &&
      positiveInteger(contract.development_rows)
    : contract.target_evidence_status === "unavailable" &&
      contract.target_analysis_scope === "not_available" &&
      contract.analysis_partition_id == null &&
      contract.analysis_partition_revision == null &&
      contract.development_partition_id == null &&
      contract.analysis_partition_assignment_hash == null &&
      contract.analysis_partition_artifact_hash == null &&
      contract.development_target_checksum == null &&
      contract.development_rows === 0;
  if (
    !targetEvidenceCoherent ||
    reviewedCount > detectedCount ||
    openCount !== detectedCount - reviewedCount ||
    contract.open_items.length !== openCount ||
    contract.blocks_confirmation !== (openCount > 0) ||
    contract.confirmation_allowed !== (openCount === 0) ||
    (contract.status === "confirmed" &&
      (openCount !== 0 || contract.blocks_continuation)) ||
    (contract.status === "not_required" &&
      (detectedCount !== 0 || contract.blocks_continuation))
  ) {
    throw new SpecialValueReviewContractError(
      "contradictory",
      "The backend special-value review counts and status are contradictory.",
    );
  }
  return contract as SpecialValueReviewContract;
}

export function specialValueDraftAuthority(
  contract: SpecialValueReviewContract,
): BureauReviewDraftAuthority {
  return {
    project_id: contract.project_id,
    dataset_id: contract.dataset_id,
    dataset_version_id: contract.dataset_version_id,
    activation_revision: contract.activation_revision,
    predictor_authorization_id: contract.predictor_authorization_id,
    target_contract_id: contract.target_contract_id,
    analysis_partition_id: contract.analysis_partition_id,
    analysis_partition_revision: contract.analysis_partition_revision,
    detection_fingerprint: contract.detection_fingerprint,
    special_value_review_id: contract.special_value_review_id,
    special_value_review_revision: contract.revision,
  };
}

export function bureauDraftMatchesContract(
  state: BureauReviewState,
  contract: SpecialValueReviewContract,
) {
  const authority = state.draftAuthority;
  return Boolean(
    authority &&
      Object.entries(specialValueDraftAuthority(contract)).every(
        ([key, expected]) =>
          authority[key as keyof BureauReviewDraftAuthority] === expected,
      ),
  );
}

function mapLegacyHandling(treatment: string): BureauHandling {
  if (treatment === "convert_to_missing") return "convert_to_missing";
  if (treatment === "exclude_variable") return "exclude_variable";
  if (treatment === "group_special_values") return "convert_to_category";
  if (treatment === "impute_bureau_equivalent") return "documented_domain_mapping";
  if (treatment === "keep_as_is") return "leave_unchanged";
  return "preserve_informative";
}

function emptyBureauReviewState(): BureauReviewState {
  return {
    declaration: "auto",
    rationale: "",
    decisions: [],
    variableDefaults: [],
    status: "draft",
    evidenceStatus: "not_recorded",
  };
}

export function bureauReviewDraftKey(projectId: string) {
  const scope = projectId.trim();
  if (!scope) {
    throw new Error("A project_id is required for the special-value draft cache.");
  }
  return `${BUREAU_REVIEW_KEY}:${encodeURIComponent(scope)}`;
}

export function loadBureauReviewState(projectId?: string): BureauReviewState {
  const storageKey = projectId?.trim()
    ? bureauReviewDraftKey(projectId)
    : BUREAU_REVIEW_KEY;
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey) || "null");
    if (parsed && Array.isArray(parsed.decisions)) {
      return {
        declaration: parsed.declaration ?? "auto",
        rationale: parsed.rationale ?? "",
        decisions: parsed.decisions.map((row: BureauReviewDecision) => ({
          ...row,
          override: true as const,
        })),
        variableDefaults: Array.isArray(parsed.variableDefaults)
          ? parsed.variableDefaults
          : [],
        // A browser record is a convenience draft only. Durable confirmation
        // is loaded from /api/data/special-value-review.
        status: "draft",
        // A cached "ready" marker is downgraded until the component reads the
        // exact evidence back from durable storage for the current review.
        evidenceStatus:
          parsed.evidenceStatus === "ready" ||
          parsed.evidenceStatus === "stale"
            ? "stale"
            : parsed.evidenceStatus === "draft"
              ? "draft"
              : "not_recorded",
        confirmedAt: undefined,
        savedAt:
          typeof parsed.savedAt === "string" ? parsed.savedAt : undefined,
        evidenceId:
          typeof parsed.evidenceId === "string" ? parsed.evidenceId : undefined,
        evidenceReviewRevision:
          positiveInteger(parsed.evidenceReviewRevision)
            ? parsed.evidenceReviewRevision
            : undefined,
        draftAuthority:
          parsed.draftAuthority && typeof parsed.draftAuthority === "object"
            ? parsed.draftAuthority
            : undefined,
      };
    }
  } catch {
    // Fall through to compatibility migration.
  }
  // Project-scoped callers must never inherit another project's legacy draft.
  if (projectId?.trim()) return emptyBureauReviewState();
  const legacy = loadBureauTreatmentDecisions();
  return {
    declaration: "auto",
    rationale: "",
    decisions: legacy.map((row) => ({
      variable: row.variableName,
      value: row.value,
      handling: mapLegacyHandling(row.treatment),
      rationale: row.rationale,
      updatedAt: row.updatedAt,
      override: true,
    })),
    variableDefaults: [],
    status: "draft",
    evidenceStatus: "not_recorded",
  };
}

export function saveBureauReviewState(
  state: BureauReviewState,
  projectId?: string,
) {
  const storageKey = projectId?.trim()
    ? bureauReviewDraftKey(projectId)
    : BUREAU_REVIEW_KEY;
  localStorage.setItem(
    storageKey,
    JSON.stringify({
      ...state,
      status: "draft",
      confirmedAt: undefined,
      browserCacheAuthority: false,
    }),
  );
  window.dispatchEvent(
    new CustomEvent("bureau-review-updated", {
      detail: { projectId: projectId?.trim() || null },
    }),
  );
}

export async function fetchBureauDetection(input: {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  target?: string;
  eventValue?: unknown;
  state: BureauReviewState;
  signal?: AbortSignal;
}) {
  const response = await fetch(`${API_BASE}/data/bureau-detection`, {
    method: "POST",
    credentials: "include",
    signal: input.signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: input.projectId,
      expected_dataset_id: input.datasetIdentity.dataset_id,
      expected_dataset_version_id: input.datasetIdentity.dataset_version_id,
      target: input.target || undefined,
      event_value: input.eventValue,
      manual_declaration: input.state.declaration,
      treatment_selections: input.state.decisions,
      reviewer_rationale: input.state.rationale,
    }),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) {
    const detail =
      payload?.detail && typeof payload.detail === "object"
        ? payload.detail
        : payload;
    const message =
      (typeof payload?.detail === "string" ? payload.detail : "") ||
      detail?.message ||
      detail?.error ||
      "Credit bureau detection is unavailable.";
    const correctiveAction = detail?.corrective_action;
    const reference = detail?.correlation_id;
    throw new Error(
      [
        message,
        correctiveAction,
        reference ? `Reference: ${reference}.` : "",
      ]
        .filter(Boolean)
        .join(" "),
    );
  }
  return payload as BureauDetectionResponse;
}

export class SpecialValueReviewApiError extends Error {
  readonly status: number;
  readonly currentReview?: unknown;
  /** Governed error code, e.g. "special_value_review_stale". */
  readonly code: string;
  /** Contract fields the persisted review predates, when the server reports them. */
  readonly supersededContractFields: string[];

  constructor(
    message: string,
    status: number,
    currentReview?: unknown,
    code = "",
    supersededContractFields: string[] = [],
  ) {
    super(message);
    this.name = "SpecialValueReviewApiError";
    this.status = status;
    this.currentReview = currentReview;
    this.code = code;
    this.supersededContractFields = supersededContractFields;
  }
}

async function readSpecialValueReviewResponse(response: Response) {
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) {
    const detail =
      payload?.detail && typeof payload.detail === "object"
        ? payload.detail
        : payload;
    const message =
      (typeof payload?.detail === "string" ? payload.detail : "") ||
      detail?.message ||
      detail?.error ||
      "The durable special-value review is unavailable.";
    const correctiveAction = detail?.corrective_action;
    const reference = detail?.correlation_id;
    throw new SpecialValueReviewApiError(
      [
        message,
        correctiveAction,
        reference ? `Reference: ${reference}.` : "",
      ]
        .filter(Boolean)
        .join(" "),
      response.status,
      detail?.special_value_review ??
        detail?.context?.special_value_review,
      typeof detail?.code === "string" ? detail.code : "",
      Array.isArray(detail?.superseded_contract_fields)
        ? (detail.superseded_contract_fields as string[])
        : Array.isArray(detail?.context?.superseded_contract_fields)
          ? (detail.context.superseded_contract_fields as string[])
          : [],
    );
  }
  return payload.special_value_review as unknown;
}

export async function fetchSpecialValueReview(input: {
  lineage: SpecialValueReviewLineage;
  signal?: AbortSignal;
}) {
  const query = new URLSearchParams({
    project_id: input.lineage.projectId,
    expected_dataset_id: input.lineage.datasetIdentity.dataset_id,
    expected_dataset_version_id:
      input.lineage.datasetIdentity.dataset_version_id,
  });
  if (
    input.lineage.analysisPartitionId &&
    input.lineage.analysisPartitionRevision != null
  ) {
    query.set(
      "expected_analysis_partition_id",
      input.lineage.analysisPartitionId,
    );
    query.set(
      "expected_analysis_partition_revision",
      String(input.lineage.analysisPartitionRevision),
    );
  }
  const response = await fetch(
    `${API_BASE}/data/special-value-review?${query.toString()}`,
    { credentials: "include", signal: input.signal },
  );
  return assertSpecialValueReviewContract(
    await readSpecialValueReviewResponse(response),
    input.lineage,
  );
}

/**
 * Loads the backend's exact active review before detection. The backend derives
 * predictor and target lineage from the exact project/version; the returned
 * identifiers are then validated as the authoritative lineage tuple.
 */
export async function fetchSpecialValueReviewForIdentity(input: {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  signal?: AbortSignal;
}) {
  const query = new URLSearchParams({
    project_id: input.projectId,
    expected_dataset_id: input.datasetIdentity.dataset_id,
    expected_dataset_version_id: input.datasetIdentity.dataset_version_id,
  });
  const response = await fetch(
    `${API_BASE}/data/special-value-review?${query.toString()}`,
    { credentials: "include", signal: input.signal },
  );
  const raw = (await readSpecialValueReviewResponse(
    response,
  )) as Partial<SpecialValueReviewContract>;
  return assertSpecialValueReviewContract(raw, {
    projectId: input.projectId,
    datasetIdentity: input.datasetIdentity,
    activationRevision: Number(raw.activation_revision),
    predictorAuthorizationId: String(raw.predictor_authorization_id ?? ""),
    targetContractId: String(raw.target_contract_id ?? ""),
    analysisPartitionId: raw.analysis_partition_id ?? null,
    analysisPartitionRevision: raw.analysis_partition_revision ?? null,
  });
}

export async function updateSpecialValueReview(input: {
  lineage: SpecialValueReviewLineage;
  current: SpecialValueReviewContract;
  intent: "draft" | "confirm";
  variableDecisions: SpecialValueReviewVariableDecision[];
  reviewerRationale: string;
  signal?: AbortSignal;
}) {
  assertSpecialValueReviewContract(input.current, input.lineage);
  const response = await fetch(`${API_BASE}/data/special-value-review`, {
    method: "PUT",
    credentials: "include",
    signal: input.signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: input.lineage.projectId,
      expected_dataset_id: input.lineage.datasetIdentity.dataset_id,
      expected_dataset_version_id:
        input.lineage.datasetIdentity.dataset_version_id,
      expected_analysis_partition_id:
        input.lineage.analysisPartitionId || undefined,
      expected_analysis_partition_revision:
        input.lineage.analysisPartitionRevision ?? undefined,
      expected_revision: input.current.revision,
      detection_fingerprint: input.current.detection_fingerprint,
      intent: input.intent,
      variable_decisions: input.variableDecisions,
      reviewer_rationale: input.reviewerRationale,
    }),
  });
  return assertSpecialValueReviewContract(
    await readSpecialValueReviewResponse(response),
    input.lineage,
  );
}

export const bureauCompatibilityKeys = [BUREAU_METADATA_KEY, BUREAU_TREATMENT_KEY, BUREAU_REVIEW_KEY];

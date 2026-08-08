/**
 * Versioned, transport-neutral audit contracts for future Audit & Assurance
 * consumers.  This module does not persist, authorize, approve, or render
 * anything.  Runtime authorities remain on the backend.
 */

export const AUDIT_ASSURANCE_CONTRACT_VERSION = "1.0" as const;

export type AuditAssuranceContractVersion =
  typeof AUDIT_ASSURANCE_CONTRACT_VERSION;

export type AuditWorkflowStage =
  | "project_context"
  | "data_acquisition"
  | "eda"
  | "outliers"
  | "missing_values"
  | "feature_engineering"
  | "validation_design"
  | "model_training"
  | "evaluation"
  | "interpretation"
  | "scoring"
  | "implementation"
  | "monitoring";

export type AuditSubjectIdentity = {
  tenant_id: string;
  project_id: string;
  model_id?: string;
  model_version_id?: string;
  dataset_id?: string;
  dataset_version_id?: string;
  activation_revision?: number;
  target_contract_id?: string;
  target_column?: string;
  positive_value?: string | number | boolean;
  negative_value?: string | number | boolean;
  predictor_authorization_id?: string;
  analysis_partition_id?: string;
  analysis_partition_revision?: number;
  feature_manifest_id?: string;
  feature_manifest_revision?: number;
  feature_manifest_checksum?: string;
  materialization_id?: string;
  validation_design_id?: string;
  validation_design_revision?: number;
  training_preflight_id?: string;
  training_job_id?: string;
  training_run_id?: string;
  candidate_id?: string;
  candidate_decision_id?: string;
  evaluation_package_id?: string;
  interpretation_package_id?: string;
  scoring_run_id?: string;
  deployment_id?: string;
  monitoring_run_id?: string;
};

export type AuditActorRole =
  | "developer"
  | "analyst"
  | "model_owner"
  | "independent_validation"
  | "governance"
  | "internal_audit"
  | "administrator"
  | "service";

export type AuditActor = {
  actor_id: string;
  actor_display_name?: string;
  authenticated_principal: string;
  actor_role: AuditActorRole;
  acting_capacity: string;
  delegated_identity_id?: string;
  service_identity_id?: string;
  authorization_decision: "allowed" | "denied";
  server_timestamp: string;
};

export type AuditDecisionKind =
  | "system_observation"
  | "developer_attestation"
  | "model_owner_approval"
  | "validation_conclusion"
  | "governance_approval"
  | "internal_audit_conclusion";

export type AuditSourceAuthority =
  | "artifact_registry"
  | "automated_control"
  | "backend_service"
  | "dataset_library"
  | "decision_registry"
  | "durable_database"
  | "evidence_graph"
  | "model_registry";

export type AuditEvent = {
  audit_event_id: string;
  contract_version: AuditAssuranceContractVersion;
  event_type: string;
  action: string;
  resource_type: string;
  resource_id: string;
  subject: AuditSubjectIdentity;
  actor: AuditActor;
  decision_kind: AuditDecisionKind;
  rationale?: string;
  prior_revision?: number;
  new_revision?: number;
  before_checksum?: string;
  after_checksum?: string;
  request_correlation_id: string;
  originating_workflow_stage: AuditWorkflowStage;
  source_authority: AuditSourceAuthority;
  authorization_result: "allowed" | "denied";
  server_timestamp: string;
  supersedes_audit_event_id?: string;
  invalidates_audit_event_id?: string;
  exception_reference?: string;
  human_readable_summary: string;
};

export type EvidenceSensitivity =
  | "public"
  | "internal"
  | "confidential"
  | "restricted";

export type EvidenceReference = {
  evidence_id: string;
  evidence_type: string;
  artifact_id: string;
  artifact_revision: number;
  artifact_checksum: string;
  subject: AuditSubjectIdentity;
  producing_workflow_stage: AuditWorkflowStage;
  bounded_retrieval_reference: string;
  sensitivity_classification: EvidenceSensitivity;
  entitlement_requirement: string;
  retention_classification: string;
  created_by: string;
  created_at: string;
  supersedes_evidence_id?: string;
  invalidates_evidence_id?: string;
  current_state: "current" | "stale" | "invalidated" | "superseded";
  mdd_references: string[];
  control_references: string[];
};

export type ControlAssessment = {
  control_id: string;
  audit_profile_id: string;
  audit_profile_version: string;
  subject: AuditSubjectIdentity;
  assessment_status:
    | "not_assessed"
    | "observation_only"
    | "effective"
    | "ineffective"
    | "exception"
    | "deferred";
  evidence_references: EvidenceReference[];
  exception_reference?: string;
  control_owner_id: string;
  reviewer_id?: string;
  assessment_timestamp: string;
  conclusion_basis: "automated_check" | "human_review";
  conclusion_role?: Exclude<AuditActorRole, "service">;
  rationale: string;
  current_state: "current" | "stale";
};

export type AuditPackageManifest = {
  audit_package_id: string;
  package_revision: number;
  contract_version: AuditAssuranceContractVersion;
  audit_profile_id: string;
  audit_profile_version: string;
  subject: AuditSubjectIdentity;
  as_of_timestamp: string;
  evidence_manifest_checksum: string;
  included_evidence_references: EvidenceReference[];
  excluded_or_redacted_evidence_summary: string;
  generated_by: string;
  review_status: "draft" | "in_review" | "reviewed";
  package_status: "current" | "stale" | "superseded";
  superseded_package_reference?: string;
};

export type GovernedCompletionAuditChecklist = {
  subject: AuditSubjectIdentity;
  actor: AuditActor;
  action: string;
  rationale?: string;
  prior_revision?: number;
  new_revision?: number;
  before_checksum?: string;
  after_checksum?: string;
  evidence_ids: string[];
  mdd_section_references: string[];
  authorization_result: "allowed" | "denied";
  downstream_invalidations: string[];
  exception_references: string[];
  access_classification: {
    restricted_data_accessed: boolean;
    sealed_holdout_accessed: boolean;
    sensitive_data_accessed: boolean;
  };
  mutation_scope: "data" | "metadata" | "recommendations" | "documentation_only";
  idempotency_key: string;
  retry_behavior: "idempotent" | "optimistic_concurrency" | "not_retryable";
  request_correlation_id: string;
  human_readable_summary: string;
};

const UNSAFE_SELECTOR_VALUES = new Set(["first", "latest"]);
const UNSAFE_AUTHORITY_VALUES = new Set([
  "browser",
  "browser_storage",
  "client_state",
  "local_storage",
  "session_storage",
]);
const PROHIBITED_EMBEDDED_KEYS = new Set([
  "raw_rows",
  "dataset_rows",
  "customer_records",
  "sealed_holdout_membership",
  "holdout_positions",
  "restricted_catalog_content",
  "provider_catalog_rows",
]);

function nonEmptyIdentifier(value: unknown, field: string): string {
  const normalized = typeof value === "string" ? value.trim() : "";
  if (!normalized) throw new Error(`${field} is required.`);
  if (UNSAFE_SELECTOR_VALUES.has(normalized.toLowerCase())) {
    throw new Error(`${field} cannot use first/latest fallback selection.`);
  }
  return normalized;
}

/** Fail closed when an applicable lifecycle stage lacks exact canonical IDs. */
export function requireAuditSubjectIdentity(
  input: AuditSubjectIdentity,
  requiredFields: Array<keyof AuditSubjectIdentity> = ["tenant_id", "project_id"],
): AuditSubjectIdentity {
  const record = input as AuditSubjectIdentity & Record<string, unknown>;
  if (!record.project_id && record.project_name) {
    throw new Error("A project display name cannot substitute for project_id.");
  }
  if (!record.dataset_id && record.dataset_name) {
    throw new Error("A dataset display name cannot substitute for dataset_id.");
  }
  for (const field of requiredFields) {
    const value = record[field];
    if (typeof value === "number") {
      if (!Number.isInteger(value) || value < 0) {
        throw new Error(`${String(field)} must be a non-negative integer.`);
      }
    } else {
      nonEmptyIdentifier(value, String(field));
    }
  }
  Object.entries(record).forEach(([field, value]) => {
    if (field.endsWith("_id") && value != null) {
      nonEmptyIdentifier(value, field);
    }
  });
  return { ...input };
}

export function assertServerAuthority(sourceAuthority: string): string {
  const normalized = nonEmptyIdentifier(sourceAuthority, "source_authority");
  if (UNSAFE_AUTHORITY_VALUES.has(normalized.toLowerCase())) {
    throw new Error("Browser or client state cannot be an audit authority.");
  }
  return normalized;
}

export function assertAuditRoleSeparation(
  actor: AuditActor,
  decisionKind: AuditDecisionKind,
): void {
  const requiredRole: Partial<Record<AuditDecisionKind, AuditActorRole>> = {
    developer_attestation: "developer",
    model_owner_approval: "model_owner",
    validation_conclusion: "independent_validation",
    governance_approval: "governance",
    internal_audit_conclusion: "internal_audit",
  };
  if (decisionKind === "system_observation" && actor.actor_role !== "service") {
    throw new Error("System observations must be attributed to a service identity.");
  }
  const expected = requiredRole[decisionKind];
  if (expected && actor.actor_role !== expected) {
    throw new Error(`${decisionKind} requires the ${expected} role.`);
  }
}

export function assertControlAssessmentSeparation(
  assessment: ControlAssessment,
): void {
  if (
    assessment.conclusion_basis === "automated_check" &&
    assessment.assessment_status !== "observation_only"
  ) {
    throw new Error(
      "An automated check is an observation, not an independent audit conclusion.",
    );
  }
  if (
    assessment.conclusion_basis === "human_review" &&
    !assessment.reviewer_id
  ) {
    throw new Error("Human conclusions require an identified reviewer.");
  }
}

export function assertBoundedAuditProjection(value: unknown): void {
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    value.forEach(assertBoundedAuditProjection);
    return;
  }
  for (const [key, child] of Object.entries(value)) {
    if (PROHIBITED_EMBEDDED_KEYS.has(key.toLowerCase())) {
      throw new Error(`${key} cannot be embedded in an audit contract.`);
    }
    assertBoundedAuditProjection(child);
  }
}

function canonicalValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, child]) => child !== undefined)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, canonicalValue(child)]),
    );
  }
  return value;
}

export function deterministicAuditJson(value: unknown): string {
  assertBoundedAuditProjection(value);
  return JSON.stringify(canonicalValue(value));
}

export async function auditManifestSha256(
  manifest: Omit<AuditPackageManifest, "evidence_manifest_checksum">,
): Promise<string> {
  const references = [...manifest.included_evidence_references].sort((left, right) =>
    left.evidence_id.localeCompare(right.evidence_id),
  );
  const bytes = new TextEncoder().encode(
    deterministicAuditJson({ ...manifest, included_evidence_references: references }),
  );
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

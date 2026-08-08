"""Canonical ATLAS Audit & Assurance wire contracts.

These frozen Pydantic models intentionally mirror ``src/lib/auditAssurance.ts``
field-for-field.  They are transport-neutral and side-effect free: this module
does not resolve runtime authority, persist evidence, expose routes, or claim
that a human or independent review occurred.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import math
import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .canonical import canonical_json_bytes, canonical_sha256


AUDIT_ASSURANCE_CONTRACT_VERSION = "1.0"
SHA256_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
FORBIDDEN_AUTHORITY_TOKENS = {
    "active",
    "anonymous",
    "browser",
    "checkpoint",
    "client",
    "current",
    "default",
    "first",
    "latest",
    "localstorage",
    "results",
    "selected",
    "sessionstorage",
}


def server_timestamp() -> datetime:
    return datetime.now(timezone.utc)


def _authority_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^A-Za-z0-9]+", value.casefold())
        if token
    }


def _exact_identifier(value: Any, *, label: str, prefix: str | None = None) -> str:
    text = str(value or "").strip()
    if not text or not ID_PATTERN.fullmatch(text):
        raise ValueError(f"{label} must be one exact durable identifier.")
    if _authority_tokens(text) & FORBIDDEN_AUTHORITY_TOKENS:
        raise ValueError(
            f"{label} cannot use first/latest/browser/checkpoint authority aliases."
        )
    if prefix and not text.startswith(prefix):
        raise ValueError(f"{label} must use the canonical {prefix!r} identifier prefix.")
    return text


def _checksum(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_PATTERN.fullmatch(text):
        raise ValueError(f"{label} must be one complete SHA-256 checksum.")
    return text.removeprefix("sha256:")


def _bounded_text(value: Any, *, label: str, maximum: int = 4000) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} cannot be blank.")
    if len(text) > maximum:
        raise ValueError(f"{label} exceeds its bounded contract length.")
    return text


def _scalar(value: Any, *, label: str) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{label} must be finite for deterministic serialization.")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str) and len(value) <= 512:
        return value
    raise ValueError(f"{label} must be a bounded scalar value, never row data.")


class FrozenContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        protected_namespaces=(),
    )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self)

    def canonical_checksum(self) -> str:
        return canonical_sha256(self)


class AuditWorkflowStage(str, Enum):
    PROJECT_CONTEXT = "project_context"
    DATA_ACQUISITION = "data_acquisition"
    EDA = "eda"
    OUTLIERS = "outliers"
    MISSING_VALUES = "missing_values"
    FEATURE_ENGINEERING = "feature_engineering"
    VALIDATION_DESIGN = "validation_design"
    MODEL_TRAINING = "model_training"
    EVALUATION = "evaluation"
    INTERPRETATION = "interpretation"
    SCORING = "scoring"
    IMPLEMENTATION = "implementation"
    MONITORING = "monitoring"


# Backward-compatible Python import name; its serialized values are the exact
# frontend AuditWorkflowStage union.
WorkflowStage = AuditWorkflowStage


class AuditSubjectIdentity(FrozenContract):
    """Exact lifecycle identity; labels and mutable selectors are rejected."""

    tenant_id: str
    project_id: str
    model_id: str | None = None
    model_version_id: str | None = None
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    activation_revision: int | None = Field(default=None, ge=1)
    target_contract_id: str | None = None
    target_column: str | None = None
    positive_value: Any = None
    negative_value: Any = None
    predictor_authorization_id: str | None = None
    analysis_partition_id: str | None = None
    analysis_partition_revision: int | None = Field(default=None, ge=1)
    feature_manifest_id: str | None = None
    feature_manifest_revision: int | None = Field(default=None, ge=1)
    feature_manifest_checksum: str | None = None
    materialization_id: str | None = None
    validation_design_id: str | None = None
    validation_design_revision: int | None = Field(default=None, ge=1)
    training_preflight_id: str | None = None
    training_job_id: str | None = None
    training_run_id: str | None = None
    candidate_id: str | None = None
    candidate_decision_id: str | None = None
    evaluation_package_id: str | None = None
    interpretation_package_id: str | None = None
    scoring_run_id: str | None = None
    deployment_id: str | None = None
    monitoring_run_id: str | None = None

    _GENERAL_IDS: ClassVar[tuple[str, ...]] = (
        "tenant_id",
        "model_id",
        "model_version_id",
        "target_contract_id",
        "predictor_authorization_id",
        "analysis_partition_id",
        "feature_manifest_id",
        "materialization_id",
        "validation_design_id",
        "training_preflight_id",
        "training_job_id",
        "training_run_id",
        "candidate_id",
        "candidate_decision_id",
        "evaluation_package_id",
        "interpretation_package_id",
        "scoring_run_id",
        "deployment_id",
        "monitoring_run_id",
    )

    @field_validator("project_id", mode="before")
    @classmethod
    def validate_project_id(cls, value: Any) -> str:
        text = _exact_identifier(value, label="project_id")
        if not (text.startswith("atlas-") or text.startswith("project-")):
            raise ValueError("project_id cannot be replaced by a project display name.")
        return text

    @field_validator("dataset_id", mode="before")
    @classmethod
    def validate_dataset_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _exact_identifier(value, label="dataset_id", prefix="ds_")

    @field_validator("dataset_version_id", mode="before")
    @classmethod
    def validate_dataset_version_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _exact_identifier(value, label="dataset_version_id", prefix="v_")

    @field_validator(*_GENERAL_IDS, mode="before")
    @classmethod
    def validate_general_ids(cls, value: Any, info) -> str | None:
        if value is None:
            return None
        return _exact_identifier(value, label=info.field_name)

    @field_validator("target_column", mode="before")
    @classmethod
    def validate_target_column(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _bounded_text(value, label="target_column", maximum=512)

    @field_validator("positive_value", "negative_value", mode="before")
    @classmethod
    def validate_target_values(cls, value: Any, info) -> Any:
        return _scalar(value, label=info.field_name)

    @field_validator("feature_manifest_checksum", mode="before")
    @classmethod
    def validate_feature_checksum(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _checksum(value, label="feature_manifest_checksum")

    @model_validator(mode="after")
    def validate_relational_identity(self):
        if self.model_version_id and not self.model_id:
            raise ValueError("model_version_id requires the exact model_id.")
        if self.feature_manifest_id and not (
            self.feature_manifest_revision or self.feature_manifest_checksum
        ):
            raise ValueError(
                "feature_manifest_id requires an exact revision or checksum."
            )
        if (
            self.positive_value is not None
            and self.negative_value is not None
            and self.positive_value == self.negative_value
        ):
            raise ValueError("Positive and negative target values must differ.")
        return self

    def require_for_stage(self, stage: AuditWorkflowStage) -> None:
        project = {"tenant_id", "project_id"}
        base = project | {
            "dataset_id",
            "dataset_version_id",
            "activation_revision",
            "target_contract_id",
            "target_column",
            "positive_value",
            "negative_value",
            "predictor_authorization_id",
        }
        partition = base | {
            "analysis_partition_id",
            "analysis_partition_revision",
        }
        feature = partition | {"feature_manifest_id", "materialization_id"}
        validation = feature | {
            "validation_design_id",
            "validation_design_revision",
        }
        training = validation | {
            "training_preflight_id",
            "training_job_id",
            "training_run_id",
        }
        requirements: dict[AuditWorkflowStage, set[str]] = {
            AuditWorkflowStage.PROJECT_CONTEXT: project,
            AuditWorkflowStage.DATA_ACQUISITION: base,
            AuditWorkflowStage.EDA: partition,
            AuditWorkflowStage.OUTLIERS: partition,
            AuditWorkflowStage.MISSING_VALUES: partition,
            AuditWorkflowStage.FEATURE_ENGINEERING: feature,
            AuditWorkflowStage.VALIDATION_DESIGN: validation,
            AuditWorkflowStage.MODEL_TRAINING: training,
            AuditWorkflowStage.EVALUATION: training
            | {"candidate_id", "candidate_decision_id", "evaluation_package_id"},
            AuditWorkflowStage.INTERPRETATION: training
            | {
                "candidate_id",
                "candidate_decision_id",
                "evaluation_package_id",
                "interpretation_package_id",
            },
            AuditWorkflowStage.SCORING: {
                "tenant_id",
                "project_id",
                "model_id",
                "model_version_id",
                "dataset_id",
                "dataset_version_id",
                "scoring_run_id",
            },
            AuditWorkflowStage.IMPLEMENTATION: {
                "tenant_id",
                "project_id",
                "model_id",
                "model_version_id",
                "deployment_id",
            },
            AuditWorkflowStage.MONITORING: {
                "tenant_id",
                "project_id",
                "model_id",
                "model_version_id",
                "deployment_id",
                "monitoring_run_id",
            },
        }
        missing = [
            name for name in sorted(requirements[stage]) if getattr(self, name) is None
        ]
        if self.feature_manifest_id and not (
            self.feature_manifest_revision or self.feature_manifest_checksum
        ):
            missing.append("feature_manifest_revision_or_checksum")
        if missing:
            raise ValueError(
                f"Audit identity fails closed for {stage.value}; missing exact "
                f"authority: {', '.join(missing)}."
            )


AuditActorRole = Literal[
    "developer",
    "analyst",
    "model_owner",
    "independent_validation",
    "governance",
    "internal_audit",
    "administrator",
    "service",
]

AuditConclusionRole = Literal[
    "developer",
    "analyst",
    "model_owner",
    "independent_validation",
    "governance",
    "internal_audit",
    "administrator",
]


class AuditActor(FrozenContract):
    actor_id: str
    actor_display_name: str | None = Field(default=None, max_length=256)
    authenticated_principal: str
    actor_role: AuditActorRole
    acting_capacity: str = Field(min_length=1, max_length=128)
    delegated_identity_id: str | None = None
    service_identity_id: str | None = None
    authorization_decision: Literal["allowed", "denied"]
    server_timestamp: datetime = Field(default_factory=server_timestamp)

    @field_validator(
        "actor_id",
        "authenticated_principal",
        "delegated_identity_id",
        "service_identity_id",
        mode="before",
    )
    @classmethod
    def validate_actor_ids(cls, value: Any, info) -> str | None:
        if value is None:
            return None
        return _exact_identifier(value, label=info.field_name)

    @field_validator("acting_capacity", mode="before")
    @classmethod
    def validate_acting_capacity(cls, value: Any) -> str:
        return _bounded_text(value, label="acting_capacity", maximum=128)

    @field_validator("server_timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("server_timestamp must be timezone-aware.")
        return value.astimezone(timezone.utc)


class ResourceIdentity(FrozenContract):
    """Helper for constructing the flat AuditEvent resource wire fields."""

    resource_type: str = Field(min_length=1, max_length=128)
    resource_id: str

    @field_validator("resource_id", mode="before")
    @classmethod
    def validate_resource_id(cls, value: Any) -> str:
        return _exact_identifier(value, label="resource_id")


AuditDecisionKind = Literal[
    "system_observation",
    "developer_attestation",
    "model_owner_approval",
    "validation_conclusion",
    "governance_approval",
    "internal_audit_conclusion",
]


class AuditEvent(FrozenContract):
    audit_event_id: str
    contract_version: Literal["1.0"] = "1.0"
    event_type: str
    action: str
    resource_type: str = Field(min_length=1, max_length=128)
    resource_id: str
    subject: AuditSubjectIdentity
    actor: AuditActor
    decision_kind: AuditDecisionKind
    rationale: str | None = Field(default=None, max_length=4000)
    prior_revision: int | None = Field(default=None, ge=1)
    new_revision: int | None = Field(default=None, ge=1)
    before_checksum: str | None = None
    after_checksum: str | None = None
    request_correlation_id: str
    originating_workflow_stage: AuditWorkflowStage
    source_authority: Literal[
        "artifact_registry",
        "automated_control",
        "backend_service",
        "dataset_library",
        "decision_registry",
        "durable_database",
        "evidence_graph",
        "model_registry",
    ]
    authorization_result: Literal["allowed", "denied"]
    server_timestamp: datetime = Field(default_factory=server_timestamp)
    supersedes_audit_event_id: str | None = None
    invalidates_audit_event_id: str | None = None
    exception_reference: str | None = None
    human_readable_summary: str = Field(min_length=1, max_length=4000)

    @field_validator(
        "audit_event_id",
        "resource_id",
        "request_correlation_id",
        "supersedes_audit_event_id",
        "invalidates_audit_event_id",
        "exception_reference",
        mode="before",
    )
    @classmethod
    def validate_event_ids(cls, value: Any, info) -> str | None:
        if value is None:
            return None
        return _exact_identifier(value, label=info.field_name)

    @field_validator("event_type", "action", mode="before")
    @classmethod
    def validate_event_text(cls, value: Any, info) -> str:
        return _bounded_text(value, label=info.field_name, maximum=256)

    @field_validator("before_checksum", "after_checksum", mode="before")
    @classmethod
    def validate_event_checksums(cls, value: Any, info) -> str | None:
        if value is None:
            return None
        return _checksum(value, label=info.field_name)

    @field_validator("server_timestamp")
    @classmethod
    def event_timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("server_timestamp must be timezone-aware.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_event_contract(self):
        self.subject.require_for_stage(self.originating_workflow_stage)
        if (self.prior_revision is None) != (self.new_revision is None):
            raise ValueError("prior_revision and new_revision must be recorded together.")
        if (self.before_checksum is None) != (self.after_checksum is None):
            raise ValueError("before_checksum and after_checksum must be recorded together.")
        if self.authorization_result != self.actor.authorization_decision:
            raise ValueError("Event and actor authorization decisions contradict.")
        required_roles: dict[str, str] = {
            "system_observation": "service",
            "developer_attestation": "developer",
            "model_owner_approval": "model_owner",
            "validation_conclusion": "independent_validation",
            "governance_approval": "governance",
            "internal_audit_conclusion": "internal_audit",
        }
        if self.actor.actor_role != required_roles[self.decision_kind]:
            raise ValueError(
                f"{self.decision_kind} requires actor_role "
                f"{required_roles[self.decision_kind]}."
            )
        return self


class EvidenceReference(FrozenContract):
    evidence_id: str
    evidence_type: str = Field(min_length=1, max_length=128)
    artifact_id: str
    artifact_revision: int = Field(ge=1)
    artifact_checksum: str
    subject: AuditSubjectIdentity
    producing_workflow_stage: AuditWorkflowStage
    bounded_retrieval_reference: str
    sensitivity_classification: Literal[
        "public", "internal", "confidential", "restricted"
    ]
    entitlement_requirement: str
    retention_classification: str
    created_by: str
    created_at: datetime
    supersedes_evidence_id: str | None = None
    invalidates_evidence_id: str | None = None
    current_state: Literal["current", "stale", "invalidated", "superseded"]
    mdd_references: tuple[str, ...] = ()
    control_references: tuple[str, ...] = ()

    @field_validator(
        "evidence_id",
        "artifact_id",
        "entitlement_requirement",
        "retention_classification",
        "created_by",
        "supersedes_evidence_id",
        "invalidates_evidence_id",
        mode="before",
    )
    @classmethod
    def validate_reference_ids(cls, value: Any, info) -> str | None:
        if value is None:
            return None
        return _exact_identifier(value, label=info.field_name)

    @field_validator("artifact_checksum", mode="before")
    @classmethod
    def validate_artifact_checksum(cls, value: Any) -> str:
        return _checksum(value, label="artifact_checksum")

    @field_validator("bounded_retrieval_reference", mode="before")
    @classmethod
    def validate_bounded_reference(cls, value: Any) -> str:
        text = _bounded_text(
            value,
            label="bounded_retrieval_reference",
            maximum=1024,
        )
        allowed = (
            "artifact://",
            "atlas://",
            "database://",
            "evidence://",
            "object://",
            "registry://",
        )
        if not text.startswith(allowed) or ".." in text or "\\" in text:
            raise ValueError(
                "bounded_retrieval_reference must be governed, never a filesystem path."
            )
        return text

    @field_validator("mdd_references", "control_references", mode="before")
    @classmethod
    def normalize_reference_links(cls, value: Any, info) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    _exact_identifier(item, label=info.field_name)
                    for item in tuple(value or ())
                }
            )
        )

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_evidence_stage(self):
        self.subject.require_for_stage(self.producing_workflow_stage)
        return self


class ControlAssessment(FrozenContract):
    """Future control shape separating automated checks from human conclusions."""

    control_id: str
    audit_profile_id: str
    audit_profile_version: str
    subject: AuditSubjectIdentity
    assessment_status: Literal[
        "not_assessed",
        "observation_only",
        "effective",
        "ineffective",
        "exception",
        "deferred",
    ]
    evidence_references: tuple[EvidenceReference, ...] = ()
    exception_reference: str | None = None
    control_owner_id: str
    reviewer_id: str | None = None
    assessment_timestamp: datetime = Field(default_factory=server_timestamp)
    conclusion_basis: Literal["automated_check", "human_review"]
    conclusion_role: AuditConclusionRole | None = None
    rationale: str = Field(min_length=1, max_length=4000)
    current_state: Literal["current", "stale"]

    @field_validator(
        "control_id",
        "audit_profile_id",
        "audit_profile_version",
        "exception_reference",
        "control_owner_id",
        "reviewer_id",
        mode="before",
    )
    @classmethod
    def validate_control_ids(cls, value: Any, info) -> str | None:
        if value is None:
            return None
        return _exact_identifier(value, label=info.field_name)

    @field_validator("assessment_timestamp")
    @classmethod
    def assessment_timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("assessment_timestamp must be timezone-aware.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def enforce_assessment_separation(self):
        if self.conclusion_basis == "automated_check":
            if self.assessment_status != "observation_only":
                raise ValueError(
                    "A system observation cannot be represented as human approval."
                )
            if self.reviewer_id or self.conclusion_role:
                raise ValueError(
                    "Automated observations cannot identify a human conclusion."
                )
        else:
            if not self.reviewer_id or not self.conclusion_role:
                raise ValueError(
                    "Human conclusions require an identified reviewer and conclusion role."
                )
            if self.assessment_status in {"not_assessed", "observation_only"}:
                raise ValueError("A human conclusion requires a conclusion status.")
            if (
                self.conclusion_role == "independent_validation"
                and self.reviewer_id == self.control_owner_id
            ):
                raise ValueError(
                    "Independent validation cannot be performed by the control owner."
                )
        return self


class AuditPackageManifest(FrozenContract):
    """Future-only deterministic package contract; no package is written here."""

    audit_package_id: str
    package_revision: int = Field(ge=1)
    contract_version: Literal["1.0"] = "1.0"
    audit_profile_id: str
    audit_profile_version: str
    subject: AuditSubjectIdentity
    as_of_timestamp: datetime
    evidence_manifest_checksum: str
    included_evidence_references: tuple[EvidenceReference, ...] = Field(min_length=1)
    excluded_or_redacted_evidence_summary: str = Field(
        min_length=1,
        max_length=4000,
    )
    generated_by: str
    review_status: Literal["draft", "in_review", "reviewed"]
    package_status: Literal["current", "stale", "superseded"]
    superseded_package_reference: str | None = None

    @field_validator(
        "audit_package_id",
        "audit_profile_id",
        "audit_profile_version",
        "generated_by",
        "superseded_package_reference",
        mode="before",
    )
    @classmethod
    def validate_manifest_ids(cls, value: Any, info) -> str | None:
        if value is None:
            return None
        return _exact_identifier(value, label=info.field_name)

    @field_validator("included_evidence_references", mode="before")
    @classmethod
    def normalize_evidence_references(cls, value: Any) -> tuple[Any, ...]:
        references = tuple(value or ())
        return tuple(
            sorted(
                references,
                key=lambda item: str(
                    item.evidence_id
                    if isinstance(item, EvidenceReference)
                    else item.get("evidence_id", "")
                ),
            )
        )

    @field_validator("evidence_manifest_checksum", mode="before")
    @classmethod
    def validate_package_checksum(cls, value: Any) -> str:
        return _checksum(value, label="evidence_manifest_checksum")

    @field_validator("as_of_timestamp")
    @classmethod
    def as_of_timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of_timestamp must be timezone-aware.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def verify_manifest(self):
        subject_checksum = self.subject.canonical_checksum()
        for reference in self.included_evidence_references:
            if reference.subject.canonical_checksum() != subject_checksum:
                raise ValueError(
                    "Every included evidence reference must match the package subject."
                )
        expected = canonical_sha256(
            self.model_dump(
                mode="python",
                exclude={"evidence_manifest_checksum"},
                exclude_none=True,
            )
        )
        if self.evidence_manifest_checksum != expected:
            raise ValueError(
                "evidence_manifest_checksum does not match canonical manifest content."
            )
        return self

    @classmethod
    def build(
        cls,
        *,
        audit_package_id: str,
        package_revision: int,
        audit_profile_id: str,
        audit_profile_version: str,
        subject: AuditSubjectIdentity,
        as_of_timestamp: datetime,
        included_evidence_references: (
            tuple[EvidenceReference, ...] | list[EvidenceReference]
        ),
        excluded_or_redacted_evidence_summary: str,
        generated_by: str,
        review_status: Literal["draft", "in_review", "reviewed"] = "draft",
        package_status: Literal["current", "stale", "superseded"] = "current",
        superseded_package_reference: str | None = None,
    ) -> "AuditPackageManifest":
        ordered = tuple(
            sorted(
                included_evidence_references,
                key=lambda item: item.evidence_id,
            )
        )
        payload = {
            "audit_package_id": audit_package_id,
            "package_revision": package_revision,
            "contract_version": AUDIT_ASSURANCE_CONTRACT_VERSION,
            "audit_profile_id": audit_profile_id,
            "audit_profile_version": audit_profile_version,
            "subject": subject,
            "as_of_timestamp": as_of_timestamp,
            "included_evidence_references": ordered,
            "excluded_or_redacted_evidence_summary": (
                excluded_or_redacted_evidence_summary
            ),
            "generated_by": generated_by,
            "review_status": review_status,
            "package_status": package_status,
        }
        if superseded_package_reference is not None:
            payload["superseded_package_reference"] = superseded_package_reference
        return cls(
            **payload,
            evidence_manifest_checksum=canonical_sha256(payload),
        )


__all__ = [
    "AUDIT_ASSURANCE_CONTRACT_VERSION",
    "AuditActor",
    "AuditActorRole",
    "AuditConclusionRole",
    "AuditDecisionKind",
    "AuditEvent",
    "AuditPackageManifest",
    "AuditSubjectIdentity",
    "AuditWorkflowStage",
    "ControlAssessment",
    "EvidenceReference",
    "ResourceIdentity",
    "WorkflowStage",
    "server_timestamp",
]

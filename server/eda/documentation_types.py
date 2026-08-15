"""Typed contract for governed EDA-to-MDD documentation.

The browser may submit documentation content and assertions about the active
analysis scope, but it may not submit the confirmation actor or timestamp.
Those fields are always derived from the authenticated server-side user and
the server clock by :mod:`server.eda.documentation_service`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EDAEvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=200)
    title: Optional[str] = Field(default=None, max_length=500)
    uri: Optional[str] = Field(default=None, max_length=2000)
    checksum: Optional[str] = Field(default=None, max_length=256)
    evidence_type: Optional[str] = Field(default=None, max_length=120)

    @field_validator("evidence_id")
    @classmethod
    def normalize_evidence_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("evidence_id cannot be blank.")
        return cleaned


class EDADecisionReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=120)
    decision: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(default="", max_length=5000)
    status: str = Field(default="documented", max_length=80)
    finding_id: Optional[str] = Field(default=None, max_length=200)
    parent_id: Optional[str] = Field(default=None, max_length=200)
    child_ids: List[str] = Field(default_factory=list, max_length=500)
    finding_family: Optional[str] = Field(default=None, max_length=200)
    downstream_destination: Optional[str] = Field(default=None, max_length=120)
    suggested_transformation: Optional[str] = Field(default=None, max_length=200)
    carry_forward_mode: Optional[
        Literal["draft_recommendation", "none"]
    ] = None
    mutation_applied: Literal[False] = False
    evidence_references: List[str] = Field(default_factory=list, max_length=100)

    @field_validator("evidence_references", "child_ids")
    @classmethod
    def normalize_decision_evidence(cls, values: List[str]) -> List[str]:
        return [
            str(value).strip()
            for value in values
            if str(value).strip()
        ]


class EDAReviewerRecordInput(BaseModel):
    """Editable expert record; authenticated identity/time remain server-owned."""

    model_config = ConfigDict(extra="forbid")

    overall_conclusion: str = Field(default="", max_length=20_000)
    reviewer_commentary: str = Field(default="", max_length=20_000)
    overall_review_status: Literal[
        "draft",
        "under_review",
        "accepted",
        "accepted_with_conditions",
        "rejected",
        "reviewed",
    ] = "draft"
    required_conditions: List[str] = Field(default_factory=list, max_length=100)
    open_nonblocking_items: List[str] = Field(default_factory=list, max_length=100)
    evidence_references: List[str] = Field(default_factory=list, max_length=500)
    mdd_reference: Optional[str] = Field(default=None, max_length=500)
    generated_draft_used: bool = False
    generated_draft_non_approving: Optional[Literal[True]] = None

    @field_validator(
        "required_conditions",
        "open_nonblocking_items",
        "evidence_references",
    )
    @classmethod
    def normalize_reviewer_lists(cls, values: List[str]) -> List[str]:
        return [str(value).strip() for value in values if str(value).strip()]

    @model_validator(mode="after")
    def validate_generated_draft_and_conditions(self):
        if self.generated_draft_used and self.generated_draft_non_approving is not True:
            raise ValueError("A generated reviewer draft must remain explicitly non-approving.")
        if (
            self.overall_review_status == "accepted_with_conditions"
            and not self.required_conditions
        ):
            raise ValueError(
                "Accepted with Conditions requires at least one documented condition."
            )
        return self


class EDABulkDispositionActionInput(BaseModel):
    """Controlled bulk decision. Actor and timestamp are injected by the server."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1, max_length=300)
    family: str = Field(min_length=1, max_length=200)
    parent_ids: List[str] = Field(min_length=1, max_length=500)
    child_ids: List[str] = Field(default_factory=list, max_length=2000)
    prior_statuses: Dict[str, str] = Field(default_factory=dict)
    new_status: Literal[
        "accepted",
        "rejected",
        "deferred",
        "documented",
        "no_action_required",
        "not_applicable",
    ]
    rationale: str = Field(min_length=1, max_length=5000)
    destination: Optional[str] = Field(default=None, max_length=200)
    mutation_applied: Literal[False] = False

    @field_validator("parent_ids", "child_ids")
    @classmethod
    def normalize_bulk_ids(cls, values: List[str]) -> List[str]:
        return sorted({str(value).strip() for value in values if str(value).strip()})

    @field_validator("rationale")
    @classmethod
    def normalize_bulk_rationale(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Bulk disposition requires a rationale.")
        return cleaned


class EDADocumentationSections(BaseModel):
    """Documentation-ready content for every EDA product area.

    Section values remain structured dictionaries because each analytical
    surface owns its detailed metrics and narratives. The fixed section names
    are the canonical boundary; confirmation rejects a missing/empty section.
    """

    model_config = ConfigDict(extra="forbid")

    overview: Dict[str, Any] = Field(default_factory=dict)
    target: Dict[str, Any] = Field(default_factory=dict)
    predictors: Dict[str, Any] = Field(default_factory=dict)
    relationships: Dict[str, Any] = Field(default_factory=dict)
    stability_and_segments: Dict[str, Any] = Field(default_factory=dict)
    findings: Dict[str, Any] = Field(default_factory=dict)


class EDADocumentationPayload(BaseModel):
    """Canonical draft and confirmation payload.

    All scope fields are assertions checked against the active, server-governed
    EDA context. ``confirmed_by`` and ``confirmed_at`` intentionally do not
    exist in this client-settable type.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=200)
    dataset_id: str = Field(min_length=1, max_length=300)
    dataset_version_id: str = Field(min_length=1, max_length=300)
    # Transitional compare-only alias. The service derives the persisted alias
    # from dataset_version_id after validating that both values agree.
    dataset_version: Optional[str] = Field(default=None, min_length=1, max_length=300)
    target: str = Field(min_length=1, max_length=300)
    predictor_manifest_id: str = Field(min_length=1, max_length=300)
    eda_analysis_version: str = Field(min_length=1, max_length=120)
    sections: EDADocumentationSections
    evidence_references: List[EDAEvidenceReference] = Field(
        default_factory=list,
        max_length=500,
    )
    decisions: List[EDADecisionReference] = Field(
        default_factory=list,
        max_length=500,
    )
    governance_contract_version: Optional[Literal["eda-governance-v2"]] = None
    reviewer_record: Optional[EDAReviewerRecordInput] = None
    bulk_disposition_actions: List[EDABulkDispositionActionInput] = Field(
        default_factory=list,
        max_length=500,
    )
    performance_metadata: Dict[str, Any] = Field(default_factory=dict)
    completion_contract: Dict[str, Any] = Field(default_factory=dict)
    duplicate_decision: Optional[str] = Field(default=None, max_length=1000)
    target_source_exclusions: List[str] = Field(default_factory=list)
    unresolved_blocking_findings: List[str] = Field(
        default_factory=list,
        max_length=500,
    )
    reviewer_status: str = Field(default="pending", max_length=80)

    @field_validator(
        "project_id",
        "dataset_id",
        "dataset_version_id",
        "target",
        "predictor_manifest_id",
        "eda_analysis_version",
    )
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Documentation scope identity values cannot be blank.")
        return cleaned

    @field_validator("target_source_exclusions")
    @classmethod
    def normalize_target_source_exclusions(cls, values: List[str]) -> List[str]:
        return sorted({str(value).strip() for value in values if str(value).strip()})

    @field_validator("unresolved_blocking_findings")
    @classmethod
    def normalize_blockers(cls, values: List[str]) -> List[str]:
        return [str(value).strip() for value in values if str(value).strip()]


class EDACompletionRequest(BaseModel):
    """Typed idempotent request for the governed EDA completion sequence."""

    model_config = ConfigDict(extra="forbid")

    payload: EDADocumentationPayload
    expected_analysis_version: Optional[str] = Field(default=None, max_length=200)
    idempotency_key: Optional[str] = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_analysis_version(self):
        if (
            self.expected_analysis_version
            and self.expected_analysis_version != self.payload.eda_analysis_version
        ):
            raise ValueError(
                "expected_analysis_version must match payload.eda_analysis_version."
            )
        return self


class EDAInvalidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    upstream_revision: Optional[str] = Field(default=None, max_length=300)
    expected_dataset_id: Optional[str] = Field(default=None, max_length=300)
    expected_dataset_version_id: Optional[str] = Field(default=None, max_length=300)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("An invalidation reason is required.")
        return cleaned

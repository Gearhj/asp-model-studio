"""Typed contract for governed EDA-to-MDD documentation.

The browser may submit documentation content and assertions about the active
analysis scope, but it may not submit the confirmation actor or timestamp.
Those fields are always derived from the authenticated server-side user and
the server clock by :mod:`server.eda.documentation_service`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    downstream_destination: Optional[str] = Field(default=None, max_length=120)
    suggested_transformation: Optional[str] = Field(default=None, max_length=200)
    carry_forward_mode: Optional[
        Literal["draft_recommendation", "none"]
    ] = None
    mutation_applied: Literal[False] = False
    evidence_references: List[str] = Field(default_factory=list, max_length=100)

    @field_validator("evidence_references")
    @classmethod
    def normalize_decision_evidence(cls, values: List[str]) -> List[str]:
        return [
            str(value).strip()
            for value in values
            if str(value).strip()
        ]


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
    performance_metadata: Dict[str, Any] = Field(default_factory=dict)
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

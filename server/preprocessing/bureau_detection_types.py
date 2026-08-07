from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BureauMetadataInput(BaseModel):
    variableName: str
    bureauSource: Optional[str] = None
    attributeDescription: Optional[str] = None
    specialValueDefinitions: Optional[str] = None
    variableFamily: Optional[str] = None
    regulatorySensitivity: Optional[str] = None


class BureauDetectionRequest(BaseModel):
    project_id: str
    expected_dataset_id: Optional[str] = None
    expected_dataset_version_id: Optional[str] = None
    target: Optional[str] = None
    event_value: Optional[Any] = None
    manual_declaration: Literal["auto", "contains", "does_not_contain", "manual_review"] = "auto"
    metadata: List[BureauMetadataInput] = Field(default_factory=list)
    treatment_selections: List[Dict[str, Any]] = Field(default_factory=list)
    reviewer_rationale: str = ""


SpecialValuePolicy = Literal[
    "preserve_informative",
    "convert_to_missing",
    "convert_to_category",
    "documented_domain_mapping",
    "exclude_variable",
    "leave_unchanged",
    "custom",
]


class SpecialValueOverrideInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any
    policy: SpecialValuePolicy
    replacement_value: Optional[Any] = None
    rationale: str = ""

    @field_validator("rationale", mode="before")
    @classmethod
    def strip_override_rationale(cls, value: Any) -> str:
        return str(value or "").strip()


class SpecialValueVariableDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variable: str = Field(min_length=1)
    policy: SpecialValuePolicy
    replacement_value: Optional[Any] = None
    rationale: str = ""
    overrides: List[SpecialValueOverrideInput] = Field(default_factory=list)

    @field_validator("variable", "rationale", mode="before")
    @classmethod
    def strip_decision_text(cls, value: Any) -> str:
        return str(value or "").strip()


class SpecialValueReviewUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    expected_dataset_id: str = Field(min_length=1)
    expected_dataset_version_id: str = Field(min_length=1)
    expected_analysis_partition_id: Optional[str] = None
    expected_analysis_partition_revision: Optional[int] = Field(
        default=None,
        ge=1,
    )
    expected_revision: int = Field(ge=1)
    detection_fingerprint: str = Field(min_length=1)
    intent: Literal["draft", "confirm"] = "draft"
    variable_decisions: List[SpecialValueVariableDecisionInput] = Field(
        default_factory=list
    )
    reviewer_rationale: str = ""

    @field_validator(
        "project_id",
        "expected_dataset_id",
        "expected_dataset_version_id",
        "expected_analysis_partition_id",
        "detection_fingerprint",
        "reviewer_rationale",
        mode="before",
    )
    @classmethod
    def strip_review_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def require_complete_partition_expectation(self):
        has_partition_id = bool(self.expected_analysis_partition_id)
        has_partition_revision = self.expected_analysis_partition_revision is not None
        if has_partition_id != has_partition_revision:
            raise ValueError(
                "expected_analysis_partition_id and "
                "expected_analysis_partition_revision must be supplied together"
            )
        return self

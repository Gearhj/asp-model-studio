from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


FeatureOrigin = Literal[
    "original",
    "interaction",
    "polynomial",
    "numeric_bin",
    "categorical_rule",
    "arithmetic",
    "date-derived",
    "encoding-output",
    "other",
]


class FeatureDefinitionInput(BaseModel):
    feature_id: Optional[str] = None
    feature_name: str
    display_name: Optional[str] = None
    origin: FeatureOrigin
    source_features: List[str] = Field(default_factory=list)
    transformation_type: str
    formula_or_rule: str = ""
    output_datatype: str = "numeric"
    config: Dict[str, Any] = Field(default_factory=dict)
    selected: bool = True
    exclusion_reason: str = ""
    user_rationale: str = ""


class PipelineStepInput(BaseModel):
    step_id: Optional[str] = None
    transformation_type: str
    selected_features: List[str] = Field(default_factory=list)
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class FeatureManifestUpdateRequest(BaseModel):
    project_id: str
    features: List[FeatureDefinitionInput] = Field(default_factory=list)
    pipeline_steps: List[PipelineStepInput] = Field(default_factory=list)
    dataset_id: str = ""
    dataset_version_id: str = ""
    # Backward-compatible expectation only. The active Dataset Library
    # identity remains authoritative and this value must never be persisted as
    # identity without an exact comparison.
    dataset_version: str = ""


class FeaturePreviewRequest(BaseModel):
    project_id: str
    features: List[FeatureDefinitionInput] = Field(default_factory=list)
    preview_limit: int = Field(default=20, ge=1, le=100)
    manifest_version: str = ""
    dataset_id: str = ""
    dataset_version_id: str = ""
    # Transitional comparison-only mirror. It can never establish identity.
    dataset_version: str = ""


class FeatureMaterializeRequest(BaseModel):
    project_id: str
    manifest_version: str = ""
    preview_hash: str = ""
    dataset_id: str = ""
    dataset_version_id: str = ""
    # Transitional comparison-only mirror. It can never establish identity.
    dataset_version: str = ""


class FeatureConfirmRequest(BaseModel):
    project_id: str
    manifest_version: str = ""
    materialization_hash: str = ""
    dataset_id: str = ""
    dataset_version_id: str = ""
    # Transitional comparison-only mirror. It can never establish identity.
    dataset_version: str = ""

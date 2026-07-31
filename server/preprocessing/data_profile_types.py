from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DataProfileRequest(BaseModel):
    project_id: str
    # Compare-only expectations for the exact immutable Dataset Library
    # version already active in this project.
    expected_dataset_id: str = ""
    expected_dataset_version_id: str = ""
    # Transitional mirror only. It must equal dataset_version_id when supplied.
    dataset_version: str = ""
    target: Optional[str] = None
    event_value: Optional[Any] = None
    non_event_value: Optional[Any] = None
    selected_columns: List[str] = Field(default_factory=list)


class FeatureProfileRequest(DataProfileRequest):
    problem_type: Optional[str] = None


JsonRow = Dict[str, Any]

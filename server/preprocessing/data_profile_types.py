from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DataProfileRequest(BaseModel):
    target: Optional[str] = None
    event_value: Optional[Any] = None
    non_event_value: Optional[Any] = None
    selected_columns: List[str] = Field(default_factory=list)


class FeatureProfileRequest(DataProfileRequest):
    problem_type: Optional[str] = None


JsonRow = Dict[str, Any]


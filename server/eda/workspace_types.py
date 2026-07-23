from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class EDAWorkspaceRequest(BaseModel):
    project_id: str
    target: Optional[str] = None
    event_value: Optional[Any] = None
    problem_type: Optional[str] = None
    selected_features: List[str] = Field(default_factory=list)
    pairwise_features: List[str] = Field(default_factory=list)
    segment_field: Optional[str] = None
    date_field: Optional[str] = None
    histogram_bins: int = Field(default=20, ge=5, le=60)
    rendered_sample_limit: int = Field(default=5000, ge=100, le=10000)

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


class TargetByPredictorRequest(BaseModel):
    """On-demand Target-by-Predictor over the full in-memory backend population.

    Used when the project has no registered Dataset Library version, so the
    DuckDB-over-artifact path in
    server/analytics/target_intelligence_service.py has no immutable
    (dataset, version) to scan. The result shape is identical, and the summary
    is produced by the same shared function, so the two paths cannot disagree.
    """

    project_id: str
    target: Optional[str] = None
    event_value: Optional[Any] = None
    problem_type: Optional[str] = None
    predictor: str
    analysis_type: str = "numeric_quantile"
    bands: int = Field(default=10, ge=2, le=20)
    top_categories: int = Field(default=12, ge=2, le=30)
    include_missing: bool = True

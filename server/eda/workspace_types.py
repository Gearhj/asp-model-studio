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
    predictor_visual_shape_limit: int = Field(default=8, ge=6, le=10)
    rendered_sample_limit: int = Field(default=5000, ge=100, le=10000)
    feature: Optional[str] = None
    selection_min: Optional[float] = None
    selection_max: Optional[float] = None


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


class EDAVifSimulationRequest(BaseModel):
    """Non-mutating VIF reduction scenario for one authorized predictor."""

    project_id: str
    excluded_feature: str
    target: Optional[str] = None
    event_value: Optional[Any] = None
    problem_type: Optional[str] = None


class EDARelationshipSampleRequest(BaseModel):
    """Bounded, server-authorized data for the relationship explorer.

    Every requested field is an assertion against the server-authored
    predictor manifest. The browser can narrow the authorized set, but it
    cannot add the target, a target source, split metadata, or another excluded
    field back into analytical plot data.
    """

    project_id: str
    target: Optional[str] = None
    event_value: Optional[Any] = None
    problem_type: Optional[str] = None
    dataset_version: Optional[str] = None
    predictor_manifest_id: Optional[str] = None
    x_feature: str
    y_feature: str
    z_feature: Optional[str] = None
    point_size_feature: Optional[str] = None
    segment_feature: Optional[str] = None
    selection_feature: Optional[str] = None
    sample_limit: int = Field(default=2500, ge=100, le=5000)

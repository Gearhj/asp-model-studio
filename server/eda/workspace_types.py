from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class EDADatasetIdentityExpectation(BaseModel):
    """Compare-only identity supplied by an EDA client.

    These values can constrain a read, but they can never activate a dataset or
    replace the canonical identity held by the server.
    """

    expected_dataset_id: Optional[str] = None
    expected_dataset_version_id: Optional[str] = None
    # Transitional compatibility assertion. It must mirror
    # expected_dataset_version_id and is never authoritative.
    dataset_version: Optional[str] = None


class EDAWorkspaceRequest(EDADatasetIdentityExpectation):
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


class TargetByPredictorRequest(EDADatasetIdentityExpectation):
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


class EDAVifSimulationRequest(EDADatasetIdentityExpectation):
    """Non-mutating VIF reduction scenario for one authorized predictor."""

    project_id: str
    excluded_feature: str
    target: Optional[str] = None
    event_value: Optional[Any] = None
    problem_type: Optional[str] = None


class EDAVifPreferenceWeights(BaseModel):
    """Reviewer-controlled policy weights for a non-mutating VIF plan."""

    signal: float = Field(default=1.0, ge=0.0, le=5.0)
    interpretability: float = Field(default=1.0, ge=0.0, le=5.0)
    data_quality: float = Field(default=1.0, ge=0.0, le=5.0)
    special_value_burden: float = Field(default=1.0, ge=0.0, le=5.0)
    production_availability: float = Field(default=1.0, ge=0.0, le=5.0)


class EDAVifResolutionPlanRequest(EDADatasetIdentityExpectation):
    """Generate recommendations without changing the governed feature set."""

    project_id: str
    target: Optional[str] = None
    event_value: Optional[Any] = None
    problem_type: Optional[str] = None
    intended_model_family: Literal[
        "linear_scorecard",
        "generalized_linear",
        "tree_ensemble",
        "neural_network",
        "mixed_bench",
    ] = "linear_scorecard"
    target_vif_threshold: float = Field(default=10.0, ge=1.0, le=100.0)
    resolution_objective: Literal[
        "balanced",
        "minimize_exclusions",
        "reduce_max_vif",
        "preserve_signal",
        "maximize_interpretability",
    ] = "balanced"
    protected_predictors: List[str] = Field(default_factory=list)
    allowed_actions: List[
        Literal["retain", "exclude", "combine", "defer"]
    ] = Field(default_factory=lambda: ["retain", "exclude", "combine", "defer"])
    correlation_threshold: float = Field(default=0.85, ge=0.5, le=0.999)
    preference_weights: EDAVifPreferenceWeights = Field(
        default_factory=EDAVifPreferenceWeights
    )
    maximum_removals: int = Field(default=2, ge=1, le=3)


class EDAVifResolutionDecisionRequest(EDADatasetIdentityExpectation):
    """Record a governed disposition for a generated VIF plan."""

    project_id: str
    plan_id: str
    action: Literal[
        "accept_complete",
        "accept_selected",
        "modify",
        "reject",
        "defer",
        "send_to_feature_engineering",
    ]
    selected_cluster_ids: List[str] = Field(default_factory=list)
    rationale: str = ""
    modifications: Dict[str, Any] = Field(default_factory=dict)


class EDARelationshipSampleRequest(EDADatasetIdentityExpectation):
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
    predictor_manifest_id: Optional[str] = None
    x_feature: str
    y_feature: str
    z_feature: Optional[str] = None
    point_size_feature: Optional[str] = None
    segment_feature: Optional[str] = None
    selection_feature: Optional[str] = None
    sample_limit: int = Field(default=2500, ge=100, le=5000)

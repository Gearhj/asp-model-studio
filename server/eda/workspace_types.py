from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


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

    # Canonical Data Acquisition -> EDA handoff.  These fields are optional at
    # schema-validation time so the service can resolve and report the real
    # missing durable prerequisite before it reports an incomplete or stale
    # browser assertion.  Project-scoped HTTP workspace reads require every
    # applicable field after those durable prerequisites have been resolved.
    dataset_id: Optional[str] = None
    dataset_version_id: Optional[str] = None
    activation_revision: Optional[int] = None
    target_contract_id: Optional[str] = None
    positive_value: Optional[Any] = None
    negative_value: Optional[Any] = None
    # Compatibility alias used by older Data Acquisition clients.  It is
    # compare-only and may never replace ``negative_value`` as authority.
    non_event_value: Optional[Any] = None
    predictor_authorization_id: Optional[str] = None
    analysis_partition_id: Optional[str] = None
    analysis_partition_revision: Optional[int] = None
    special_value_review_id: Optional[str] = None
    special_value_review_revision: Optional[int] = None

    # Optional, compare-only Bureau Metadata Catalog handoff.  Data
    # Acquisition resolves this bounded identity from the exact current
    # dataset-version binding and crosswalk; the browser can never make a
    # catalog mapping authoritative by supplying these fields.  Ordinary
    # datasets may omit the entire contract.  An explicit ``unavailable``
    # assertion is accepted only after the HTTP boundary verifies that no
    # exact entitled annotation set exists.
    bureau_semantic_annotation_state: Optional[
        Literal["available", "unavailable"]
    ] = None
    bureau_semantic_annotation_set_id: Optional[str] = None
    bureau_semantic_annotation_set_checksum: Optional[str] = None
    bureau_metadata_schema_checksum: Optional[str] = None
    bureau_metadata_binding_id: Optional[str] = None
    bureau_metadata_binding_revision: Optional[int] = None
    bureau_metadata_binding_revision_checksum: Optional[str] = None
    bureau_metadata_crosswalk_id: Optional[str] = None
    bureau_metadata_crosswalk_revision: Optional[int] = None
    bureau_metadata_crosswalk_revision_checksum: Optional[str] = None
    bureau_metadata_catalog_version_id: Optional[str] = None
    bureau_metadata_catalog_checksum: Optional[str] = None

    @model_validator(mode="after")
    def validate_bureau_semantic_identity_shape(
        self,
    ) -> "EDADatasetIdentityExpectation":
        identity_fields = (
            "bureau_semantic_annotation_set_id",
            "bureau_semantic_annotation_set_checksum",
            "bureau_metadata_schema_checksum",
            "bureau_metadata_binding_id",
            "bureau_metadata_binding_revision",
            "bureau_metadata_binding_revision_checksum",
            "bureau_metadata_crosswalk_id",
            "bureau_metadata_crosswalk_revision",
            "bureau_metadata_crosswalk_revision_checksum",
            "bureau_metadata_catalog_version_id",
            "bureau_metadata_catalog_checksum",
        )
        present = [
            field for field in identity_fields if getattr(self, field) is not None
        ]
        if self.bureau_semantic_annotation_state is None:
            if present:
                raise ValueError(
                    "Bureau semantic identity fields require an explicit "
                    "available state."
                )
            return self
        if self.bureau_semantic_annotation_state == "unavailable":
            if present:
                raise ValueError(
                    "An unavailable Bureau semantic assertion cannot carry "
                    "annotation, binding, crosswalk, schema, or catalog identity."
                )
            return self
        missing = [
            field for field in identity_fields if getattr(self, field) is None
        ]
        if missing:
            raise ValueError(
                "An available Bureau semantic assertion requires the complete "
                "exact identity: " + ", ".join(missing) + "."
            )
        revisions = (
            self.bureau_metadata_binding_revision,
            self.bureau_metadata_crosswalk_revision,
        )
        if any(
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
            for revision in revisions
        ):
            raise ValueError(
                "Bureau semantic binding and crosswalk revisions must be "
                "positive integers."
            )
        return self


class EDAWorkspaceRequest(EDADatasetIdentityExpectation):
    project_id: str
    # The public EDA workspace is canonical by default. Feature Engineering's
    # pre-existing selected-features-only VIF request is recognized only at
    # the router's exact target-free compatibility boundary; this optional
    # marker makes that intent explicit for newer clients.
    analysis_mode: Literal[
        "canonical_eda",
        "predictor_only_diagnostic",
    ] = "canonical_eda"
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
    """On-demand Target-by-Predictor over the exact development population.

    The inherited identity fields carry the complete canonical Data
    Acquisition handoff.  They remain optional at schema-validation time so
    the service can report a more precise missing durable prerequisite before
    it reports a missing browser assertion, but every HTTP EDA call is validated
    fail-closed against the full handoff before calculation.
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
    target: Optional[str] = None
    event_value: Optional[Any] = None
    problem_type: Optional[str] = None
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

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TrainingJobRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    models: List[str] = Field(default_factory=list)
    k_folds: int = Field(default=5, ge=2, le=10)
    max_parallel: int = Field(default=1, ge=1, le=8)
    calibrate: bool = False
    use_pca: bool = False
    grid_search: bool = False
    grid_search_level: str = "quick"
    model_params: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    project_id: str
    dataset_id: str = ""
    dataset_version_id: str = ""
    # Backward-compatible expectation only. The active Dataset Library
    # identity is authoritative.
    dataset_version: str = ""
    target: str = ""
    problem_type: str = ""
    event_value: Any | None = None
    non_event_value: Any | None = None
    feature_manifest_version: str = ""
    split_id: str = ""
    validation_design_id: str = ""
    validation_design_version: str = ""
    selected_original_features: List[str] = Field(default_factory=list)
    selected_engineered_features: List[str] = Field(default_factory=list)
    preprocessing_pipeline: List[Dict[str, Any]] = Field(default_factory=list)
    random_seed: int = 42
    primary_metric: str = ""
    candidate_strategy: str = "custom_portfolio"
    large_job_confirmed: bool = False
    retry_parent_job_id: str = ""
    user: str = ""
    requested_at: str = ""
    # A successful preflight can be carried into the primary start action.
    # The backend always revalidates the current state, but rejects the start
    # when either expectation no longer identifies that same state.
    expected_preflight_id: str = ""
    expected_preflight_state_hash: str = ""
    # Clients should reuse this value for retries of one user action. When it
    # is omitted, the service still coalesces identical concurrently-active
    # submissions by their governed submission hash.
    idempotency_key: str = Field(default="", max_length=200)
    # Optional runtime-version expectations captured from preflight.
    selected_algorithm_versions: Dict[str, str] = Field(default_factory=dict)


class TrainingPortfolioRequest(BaseModel):
    """Dataset-bound, backend-authoritative model portfolio selection."""

    model_config = ConfigDict(protected_namespaces=())
    project_id: str
    dataset_id: str
    dataset_version_id: str
    selected_algorithm_ids: List[str] = Field(default_factory=list)
    candidate_strategy: str = "custom_portfolio"
    problem_type: str = ""
    max_parallel: int = Field(default=1, ge=1, le=8)
    calibrate: bool = False
    grid_search: bool = False
    grid_search_level: str = "quick"
    primary_metric: str = ""
    # Optimistic concurrency is optional. A zero value means "save against
    # the current authoritative revision" and is useful for first load.
    expected_selection_revision: int = Field(default=0, ge=0)
    client_portfolio_revision: int = Field(default=0, ge=0)
    portfolio_revision: int = Field(default=0, ge=0)


class TrainingJobCancelResponse(BaseModel):
    ok: bool
    job_id: str
    overall_status: str
    cancellation_requested: bool
    message: Optional[str] = None

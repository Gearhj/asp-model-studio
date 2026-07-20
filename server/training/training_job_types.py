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
    project_id: str = ""
    dataset_id: str = ""
    dataset_version: str = ""
    target: str = ""
    problem_type: str = ""
    event_value: Any | None = None
    non_event_value: Any | None = None
    feature_manifest_version: str = ""
    split_id: str = ""
    selected_original_features: List[str] = Field(default_factory=list)
    selected_engineered_features: List[str] = Field(default_factory=list)
    preprocessing_pipeline: List[Dict[str, Any]] = Field(default_factory=list)
    random_seed: int = 42
    primary_metric: str = ""
    user: str = ""
    requested_at: str = ""


class TrainingJobCancelResponse(BaseModel):
    ok: bool
    job_id: str
    overall_status: str
    cancellation_requested: bool
    message: Optional[str] = None

from __future__ import annotations

from typing import Any, Literal, TypedDict


AssetType = Literal[
    "predictive_model",
    "credit_risk_model",
    "optimization_study",
    "experiment",
    "ab_test",
    "decision_strategy",
    "custom_workflow",
]

LifecycleStatus = Literal[
    "Draft",
    "Development",
    "Ready for Review",
    "Validation",
    "Recommended",
    "Approved",
    "Approved with Conditions",
    "Implementation Planned",
    "Implemented",
    "Monitoring",
    "Returned",
    "Rejected",
    "Retired",
]

ASSET_TYPES: tuple[str, ...] = (
    "predictive_model",
    "credit_risk_model",
    "optimization_study",
    "experiment",
    "ab_test",
    "decision_strategy",
    "custom_workflow",
)

LIFECYCLE_STATUSES: tuple[str, ...] = (
    "Draft",
    "Development",
    "Ready for Review",
    "Validation",
    "Recommended",
    "Approved",
    "Approved with Conditions",
    "Implementation Planned",
    "Implemented",
    "Monitoring",
    "Returned",
    "Rejected",
    "Retired",
)

TRANSPORTATION_REQUIRED_EVIDENCE: tuple[str, ...] = (
    "optimization_decision_charter",
    "optimization_input_bundle",
    "optimization_route_normalization",
    "optimization_formulation_readiness",
    "optimization_objective",
    "optimization_decision_variables",
    "optimization_constraints",
    "optimization_solver_configuration",
    "optimization_scenarios",
    "optimization_solution",
    "optimization_sensitivity",
    "optimization_validation",
    "optimization_recommendation",
    "optimization_implementation_plan",
    "optimization_monitoring_plan",
    "optimization_documentation_package",
    "optimization_reproducibility_code",
)


class RegistryAction(TypedDict):
    action_id: str
    project_id: str
    project_name: str
    severity: str
    action_type: str
    title: str
    description: str
    owner: str
    recommended_next_step: str
    created_at: str | None
    source: str


class RegistryAsset(TypedDict, total=False):
    registry_id: str
    project_id: str
    name: str
    asset_type: AssetType
    workflow_type: str
    template_id: str | None
    owner_user_id: str | None
    owner_display_name: str
    lifecycle_status: LifecycleStatus
    risk_tier: str
    business_purpose: str
    intended_use: str
    current_step_id: str | None
    workflow_completion_percent: int
    evidence_readiness_percent: int
    evidence_status: str
    documentation_readiness_percent: int
    documentation_status: str
    validation_status: str
    validation_score: float | None
    recommendation_status: str
    implementation_status: str
    monitoring_status: str
    monitoring_open_alert_count: int
    last_monitoring_run_at: str | None
    next_monitoring_due_at: str | None
    latest_run_status: str
    latest_run_type: str | None
    latest_run_at: str | None
    latest_export_at: str | None
    last_activity_at: str | None
    created_at: str | None
    updated_at: str | None
    next_review_date: str | None
    open_action_count: int
    open_finding_count: int
    tags: list[str]
    summary_json: dict[str, Any]

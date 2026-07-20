from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


PLAN_STATUSES = {"draft": "Draft", "active": "Active", "paused": "Paused", "retired": "Retired"}
RUN_STATUSES = {"draft": "Draft", "running": "Running", "completed": "Completed", "failed": "Failed", "cancelled": "Cancelled"}
OBSERVATION_STATUSES = {"pass": "Pass", "warning": "Warning", "breach": "Breach", "not_available": "Not Available"}
ALERT_STATUSES = {"open": "Open", "acknowledged": "Acknowledged", "in_remediation": "In Remediation", "resolved": "Resolved", "accepted_risk": "Accepted Risk", "closed": "Closed"}
SEVERITIES = {"low": "Low", "medium": "Medium", "high": "High", "critical": "Critical"}


def label_for(group: Dict[str, str], value: str | None) -> str:
    return group.get(str(value or "").lower(), str(value or "Not Available").replace("_", " ").title())


def status_color(kind: str, value: str | None) -> str:
    key = str(value or "").lower()
    if key in {"active", "completed", "pass", "resolved", "closed"}:
        return "emerald"
    if key in {"warning", "acknowledged", "in_remediation", "medium", "paused"}:
        return "amber"
    if key in {"breach", "failed", "high", "critical", "open"}:
        return "red"
    if key in {"draft", "running", "low"}:
        return "blue"
    return "slate"


class MonitoringPlanPayload(BaseModel):
    project_id: str
    asset_type: str | None = None
    workflow_type: str | None = None
    template_id: str | None = None
    plan_name: str | None = None
    plan_status: str | None = None
    monitoring_owner_user_id: str | None = None
    monitoring_owner_name: str | None = None
    business_owner_user_id: str | None = None
    business_owner_name: str | None = None
    monitoring_cadence: str | None = None
    first_monitoring_date: str | None = None
    next_monitoring_date: str | None = None
    production_start_date: str | None = None
    monitoring_scope: str | None = None
    data_source_ref: str | None = None
    notes: str | None = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class MonitoringPlanUpdate(BaseModel):
    plan_name: str | None = None
    plan_status: str | None = None
    monitoring_owner_user_id: str | None = None
    monitoring_owner_name: str | None = None
    business_owner_user_id: str | None = None
    business_owner_name: str | None = None
    monitoring_cadence: str | None = None
    first_monitoring_date: str | None = None
    next_monitoring_date: str | None = None
    production_start_date: str | None = None
    monitoring_scope: str | None = None
    data_source_ref: str | None = None
    notes: str | None = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class MonitoringMetricPayload(BaseModel):
    metric_name: str
    metric_category: str = "performance"
    metric_definition: str | None = None
    metric_direction: str | None = "higher_is_worse"
    warning_threshold: float | None = None
    breach_threshold: float | None = None
    lower_warning_threshold: float | None = None
    lower_breach_threshold: float | None = None
    unit: str | None = None
    cadence: str | None = None
    owner_user_id: str | None = None
    status: str | None = "active"
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class MonitoringRunPayload(BaseModel):
    run_name: str | None = None
    run_period_start: str | None = None
    run_period_end: str | None = None
    data_version_ref: str | None = None
    summary: str | None = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class MonitoringObservationPayload(BaseModel):
    monitoring_metric_id: str
    observed_value: float | None = None
    baseline_value: float | None = None
    comparison_value: float | None = None
    threshold_used: str | None = None
    interpretation: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class MonitoringRunCompletePayload(BaseModel):
    observations: List[MonitoringObservationPayload] = Field(default_factory=list)
    summary: str | None = None
    overall_status: str | None = None


class MonitoringAlertPayload(BaseModel):
    project_id: str
    monitoring_run_id: str | None = None
    monitoring_plan_id: str | None = None
    alert_type: str = "threshold"
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    status: str = "open"
    title: str
    description: str | None = None
    metric_name: str | None = None
    observed_value: float | None = None
    threshold_value: float | None = None
    owner_user_id: str | None = None
    owner_name: str | None = None
    due_date: str | None = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class MonitoringAlertUpdate(BaseModel):
    status: str | None = None
    severity: str | None = None
    title: str | None = None
    description: str | None = None
    owner_user_id: str | None = None
    owner_name: str | None = None
    due_date: str | None = None
    resolution_notes: str | None = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class MonitoringActionPayload(BaseModel):
    project_id: str
    alert_id: str | None = None
    monitoring_plan_id: str | None = None
    action_type: str = "review"
    title: str
    description: str | None = None
    owner_user_id: str | None = None
    status: str = "open"
    due_date: str | None = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class MonitoringActionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    owner_user_id: str | None = None
    status: str | None = None
    due_date: str | None = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class MonitoringBaselinePayload(BaseModel):
    project_id: str
    baseline_name: str
    baseline_type: str = "production"
    baseline_period_start: str | None = None
    baseline_period_end: str | None = None
    data_version_ref: str | None = None
    metric_summary_json: Dict[str, Any] = Field(default_factory=dict)
    metadata_json: Dict[str, Any] = Field(default_factory=dict)

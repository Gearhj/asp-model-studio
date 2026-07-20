from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from ..security.security_store import require_user
from .monitoring_service import get_monitoring_service
from .schemas import (
    MonitoringActionPayload,
    MonitoringActionUpdate,
    MonitoringAlertPayload,
    MonitoringAlertUpdate,
    MonitoringBaselinePayload,
    MonitoringMetricPayload,
    MonitoringObservationPayload,
    MonitoringPlanPayload,
    MonitoringPlanUpdate,
    MonitoringRunCompletePayload,
    MonitoringRunPayload,
)


router = APIRouter(prefix="/api", tags=["monitoring"])


def _service():
    return get_monitoring_service()


@router.get("/monitoring/summary")
def monitoring_summary(_user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "summary": _service().summary()}


@router.get("/monitoring/plans")
def list_plans(project_id: str | None = None, status: str | None = None, workflow_type: str | None = None, owner_user_id: str | None = None, search: str | None = None, limit: int = 250, _user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().list_plans({"project_id": project_id, "status": status, "workflow_type": workflow_type, "owner_user_id": owner_user_id, "search": search, "limit": limit})}


@router.post("/monitoring/plans")
def create_plan(payload: MonitoringPlanPayload, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().create_plan(payload.dict(), user)}


@router.get("/monitoring/plans/{monitoring_plan_id}")
def get_plan(monitoring_plan_id: str, _user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().plan_detail(monitoring_plan_id)}


@router.put("/monitoring/plans/{monitoring_plan_id}")
def update_plan(monitoring_plan_id: str, payload: MonitoringPlanUpdate, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().update_plan(monitoring_plan_id, payload.dict(), user)}


@router.post("/monitoring/projects/{project_id}/create-plan")
def create_project_plan(project_id: str, payload: MonitoringPlanUpdate | None = None, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    data = (payload.dict() if payload else {})
    return {"ok": True, **_service().create_plan({"project_id": project_id, **data}, user)}


@router.get("/monitoring/projects/{project_id}/plan")
def get_project_plan(project_id: str, _user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().get_plan_by_project(project_id)}


@router.post("/monitoring/plans/{monitoring_plan_id}/activate")
def activate_plan(monitoring_plan_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().set_plan_status(monitoring_plan_id, "active", user)}


@router.post("/monitoring/plans/{monitoring_plan_id}/pause")
def pause_plan(monitoring_plan_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().set_plan_status(monitoring_plan_id, "paused", user)}


@router.post("/monitoring/plans/{monitoring_plan_id}/retire")
def retire_plan(monitoring_plan_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().set_plan_status(monitoring_plan_id, "retired", user)}


@router.get("/monitoring/plans/{monitoring_plan_id}/metrics")
def list_metrics(monitoring_plan_id: str, _user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "metrics": _service().monitoring.list_metrics(monitoring_plan_id)}


@router.post("/monitoring/plans/{monitoring_plan_id}/metrics")
def add_metric(monitoring_plan_id: str, payload: MonitoringMetricPayload, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "metric": _service().add_metric(monitoring_plan_id, payload.dict(), user)}


@router.post("/monitoring/plans/{monitoring_plan_id}/metrics/seed-from-template")
def seed_metrics(monitoring_plan_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().seed_metrics_from_template(monitoring_plan_id, user)}


@router.put("/monitoring/metrics/{monitoring_metric_id}")
def update_metric(monitoring_metric_id: str, payload: MonitoringMetricPayload, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "metric": _service().update_metric(monitoring_metric_id, payload.dict(), user)}


@router.delete("/monitoring/metrics/{monitoring_metric_id}")
def remove_metric(monitoring_metric_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().remove_metric(monitoring_metric_id, user)}


@router.get("/monitoring/plans/{monitoring_plan_id}/runs")
def list_runs(monitoring_plan_id: str, _user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "runs": _service().monitoring.list_runs(monitoring_plan_id)}


@router.post("/monitoring/plans/{monitoring_plan_id}/runs")
def create_run(monitoring_plan_id: str, payload: MonitoringRunPayload, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "run": _service().create_run(monitoring_plan_id, payload.dict(), user)}


@router.get("/monitoring/runs/{monitoring_run_id}")
def get_run(monitoring_run_id: str, _user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().run_detail(monitoring_run_id)}


@router.post("/monitoring/runs/{monitoring_run_id}/start")
def start_run(monitoring_run_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "run": _service().start_run(monitoring_run_id, user)}


@router.post("/monitoring/runs/{monitoring_run_id}/complete")
def complete_run(monitoring_run_id: str, payload: MonitoringRunCompletePayload, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().complete_run(monitoring_run_id, payload.dict(), user)}


@router.post("/monitoring/runs/{monitoring_run_id}/fail")
def fail_run(monitoring_run_id: str, payload: MonitoringRunPayload, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "run": _service().fail_run(monitoring_run_id, payload.dict(), user)}


@router.get("/monitoring/runs/{monitoring_run_id}/observations")
def list_observations(monitoring_run_id: str, _user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "observations": _service().monitoring.list_observations(monitoring_run_id)}


@router.post("/monitoring/runs/{monitoring_run_id}/observations")
def record_observation(monitoring_run_id: str, payload: MonitoringObservationPayload, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "observation": _service().record_observation(monitoring_run_id, payload.dict(), user)}


@router.get("/monitoring/alerts")
def list_alerts(project_id: str | None = None, status: str | None = None, severity: str | None = None, owner_user_id: str | None = None, limit: int = 250, _user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "alerts": _service().monitoring.list_alerts(project_id=project_id, status=status, severity=severity, owner_user_id=owner_user_id, limit=limit)}


@router.get("/monitoring/projects/{project_id}/alerts")
def list_project_alerts(project_id: str, _user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "alerts": _service().monitoring.list_alerts(project_id=project_id)}


@router.post("/monitoring/alerts")
def create_alert(payload: MonitoringAlertPayload, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "alert": _service().create_alert(payload.dict(), user)}


@router.put("/monitoring/alerts/{alert_id}")
def update_alert(alert_id: str, payload: MonitoringAlertUpdate, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "alert": _service().update_alert(alert_id, payload.dict(), user)}


@router.post("/monitoring/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "alert": _service().set_alert_status(alert_id, "acknowledged", user)}


@router.post("/monitoring/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str, payload: MonitoringAlertUpdate | None = None, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "alert": _service().set_alert_status(alert_id, "resolved", user, (payload.resolution_notes if payload else None))}


@router.post("/monitoring/alerts/{alert_id}/accept-risk")
def accept_risk(alert_id: str, payload: MonitoringAlertUpdate | None = None, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "alert": _service().set_alert_status(alert_id, "accepted_risk", user, (payload.resolution_notes if payload else None))}


@router.post("/monitoring/alerts/{alert_id}/close")
def close_alert(alert_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "alert": _service().set_alert_status(alert_id, "closed", user)}


@router.post("/monitoring/alerts/{alert_id}/create-validation-finding")
def create_validation_finding(alert_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().create_validation_finding(alert_id, user)}


@router.get("/monitoring/actions")
def list_actions(project_id: str | None = None, monitoring_plan_id: str | None = None, status: str | None = None, _user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "actions": _service().monitoring.list_actions(project_id=project_id, monitoring_plan_id=monitoring_plan_id, status=status)}


@router.post("/monitoring/actions")
def create_action(payload: MonitoringActionPayload, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "action": _service().create_action(payload.dict(), user)}


@router.put("/monitoring/actions/{action_id}")
def update_action(action_id: str, payload: MonitoringActionUpdate, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "action": _service().update_action(action_id, payload.dict(), user)}


@router.post("/monitoring/actions/{action_id}/complete")
def complete_action(action_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "action": _service().complete_action(action_id, user)}


@router.post("/monitoring/baselines")
def create_baseline(payload: MonitoringBaselinePayload, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "baseline": _service().create_baseline(payload.dict(), user)}


@router.get("/monitoring/templates")
def monitoring_templates(_user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().list_templates()}


@router.get("/monitoring/templates/{workflow_type}")
def monitoring_template(workflow_type: str, _user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "template": _service().get_template(workflow_type)}


@router.get("/monitoring/projects/{project_id}/events")
def project_events(project_id: str, _user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "events": _service().monitoring.list_events(project_id=project_id)}

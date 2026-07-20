from __future__ import annotations

import uuid
from collections import Counter
from typing import Any, Dict, Mapping

from fastapi import HTTPException

from ..persistence.db import json_loads, now_iso
from ..persistence.service import get_persistence_service
from .monitoring_templates import list_templates, template_for_workflow


OWNER_ROLES = {"admin", "data_scientist", "model_owner", "model_manager", "manager", "validator"}
VALIDATION_ROLES = {"admin", "validator", "model_manager", "manager"}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _user_id(user: Mapping[str, Any]) -> str | None:
    return user.get("userId") or user.get("user_id")


def _user_name(user: Mapping[str, Any]) -> str:
    return str(user.get("displayName") or user.get("display_name") or user.get("email") or _user_id(user) or "ATLAS user")


def _role(user: Mapping[str, Any]) -> str:
    return str(user.get("role") or "")


def _require_role(user: Mapping[str, Any], roles: set[str], action: str) -> None:
    if _role(user) not in roles:
        raise HTTPException(status_code=403, detail=f"{action} requires one of these roles: {', '.join(sorted(roles))}.")


def _metadata(record: Mapping[str, Any] | None) -> Dict[str, Any]:
    return json_loads((record or {}).get("metadata_json"), {})


class MonitoringService:
    def __init__(self, persistence: Any | None = None) -> None:
        self.persistence = persistence or get_persistence_service()
        self.monitoring = self.persistence.monitoring

    def _project(self, project_id: str) -> Dict[str, Any]:
        project = self.persistence.projects.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project was not found in the ATLAS persistence database.")
        return project

    def _plan(self, monitoring_plan_id: str) -> Dict[str, Any]:
        plan = self.monitoring.get_plan(monitoring_plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Monitoring plan was not found.")
        return plan

    def _run(self, monitoring_run_id: str) -> Dict[str, Any]:
        run = self.monitoring.get_run(monitoring_run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Monitoring run was not found.")
        return run

    def _alert(self, alert_id: str) -> Dict[str, Any]:
        alert = self.monitoring.get_alert(alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="Monitoring alert was not found.")
        return alert

    def _audit(self, project_id: str, user: Mapping[str, Any], action_type: str, entity_type: str, entity_id: str | None, title: str, summary: str | None = None, metadata: Mapping[str, Any] | None = None) -> None:
        self.persistence.audit.create(
            {
                "audit_id": _id("audit"),
                "project_id": project_id,
                "user_id": _user_id(user),
                "action_type": action_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "title": title,
                "summary": summary,
                "created_at": now_iso(),
                "metadata_json": dict(metadata or {}),
            }
        )

    def _event(self, project_id: str | None, user: Mapping[str, Any], event_type: str, title: str, summary: str | None = None, *, plan_id: str | None = None, run_id: str | None = None, metadata: Mapping[str, Any] | None = None) -> None:
        self.monitoring.create_event(
            {
                "event_id": _id("mev"),
                "monitoring_plan_id": plan_id,
                "monitoring_run_id": run_id,
                "project_id": project_id,
                "user_id": _user_id(user),
                "event_type": event_type,
                "title": title,
                "summary": summary,
                "created_at": now_iso(),
                "metadata_json": dict(metadata or {}),
            }
        )

    def _notify(self, recipient_user_id: str | None, actor: Mapping[str, Any], project_id: str | None, resource_type: str, resource_id: str | None, title: str, message: str, priority: str = "normal") -> None:
        if not recipient_user_id:
            return
        self.persistence.notifications.create(
            {
                "notification_id": _id("ntf"),
                "recipient_user_id": recipient_user_id,
                "actor_user_id": _user_id(actor),
                "notification_type": "monitoring",
                "title": title,
                "message": message,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "project_id": project_id,
                "priority": priority,
                "created_at": now_iso(),
                "metadata_json": {"source": "monitoring_center"},
            }
        )

    def _evidence(self, project_id: str, user: Mapping[str, Any], artifact_type: str, title: str, summary: str, payload: Mapping[str, Any]) -> str:
        evidence_id = _id("ev")
        self.persistence.evidence.upsert(
            {
                "evidence_id": evidence_id,
                "project_id": project_id,
                "workflow_type": "monitoring",
                "step_id": "monitoring",
                "artifact_type": artifact_type,
                "status": "captured",
                "title": title,
                "summary": summary,
                "source_ref": "monitoring_center",
                "created_by": _user_id(user),
                "created_at": now_iso(),
                "captured_at": now_iso(),
                "payload_json": dict(payload),
            }
        )
        return evidence_id

    def evaluate_thresholds(self, metric: Mapping[str, Any], observed_value: float | None) -> Dict[str, Any]:
        if observed_value is None:
            return {"status": "not_available", "threshold_used": None, "interpretation": "Metric value was not available."}
        direction = str(metric.get("metric_direction") or "higher_is_worse")
        breach = metric.get("breach_threshold")
        warning = metric.get("warning_threshold")
        lower_breach = metric.get("lower_breach_threshold")
        lower_warning = metric.get("lower_warning_threshold")
        status = "pass"
        used = ""
        if direction in {"higher_is_worse", "two_sided"}:
            if breach is not None and observed_value >= float(breach):
                status, used = "breach", f">= {breach}"
            elif warning is not None and observed_value >= float(warning):
                status, used = "warning", f">= {warning}"
        if status == "pass" and direction in {"lower_is_worse", "two_sided"}:
            if lower_breach is not None and observed_value <= float(lower_breach):
                status, used = "breach", f"<= {lower_breach}"
            elif lower_warning is not None and observed_value <= float(lower_warning):
                status, used = "warning", f"<= {lower_warning}"
            elif breach is not None and direction == "lower_is_worse" and observed_value <= float(breach):
                status, used = "breach", f"<= {breach}"
            elif warning is not None and direction == "lower_is_worse" and observed_value <= float(warning):
                status, used = "warning", f"<= {warning}"
        return {
            "status": status,
            "threshold_used": used or None,
            "interpretation": "Within threshold." if status == "pass" else f"{metric.get('metric_name')} triggered {status}.",
        }

    def list_templates(self) -> Dict[str, Any]:
        return {"templates": list_templates()}

    def get_template(self, workflow_type: str) -> Dict[str, Any]:
        return template_for_workflow(workflow_type)

    def create_plan(self, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        _require_role(user, OWNER_ROLES, "Creating monitoring plan")
        project = self._project(str(payload["project_id"]))
        template = template_for_workflow(payload.get("workflow_type") or project.get("workflow_type") or project.get("project_type"))
        timestamp = now_iso()
        plan = self.monitoring.upsert_plan(
            {
                "monitoring_plan_id": _id("monplan"),
                "project_id": project["project_id"],
                "asset_type": payload.get("asset_type") or project.get("project_type"),
                "workflow_type": payload.get("workflow_type") or project.get("workflow_type") or project.get("project_type"),
                "template_id": payload.get("template_id") or template["template_id"],
                "plan_name": payload.get("plan_name") or f"{project.get('project_name') or project['project_id']} Monitoring Plan",
                "plan_status": payload.get("plan_status") or "draft",
                "monitoring_owner_user_id": payload.get("monitoring_owner_user_id") or project.get("owner_user_id") or _user_id(user),
                "monitoring_owner_name": payload.get("monitoring_owner_name") or _user_name(user),
                "business_owner_user_id": payload.get("business_owner_user_id"),
                "business_owner_name": payload.get("business_owner_name"),
                "monitoring_cadence": payload.get("monitoring_cadence") or "monthly",
                "first_monitoring_date": payload.get("first_monitoring_date"),
                "next_monitoring_date": payload.get("next_monitoring_date"),
                "production_start_date": payload.get("production_start_date"),
                "monitoring_scope": payload.get("monitoring_scope") or "Production performance, drift, stability, alerts, and revalidation triggers.",
                "data_source_ref": payload.get("data_source_ref"),
                "notes": payload.get("notes"),
                "created_by_user_id": _user_id(user),
                "created_at": timestamp,
                "updated_at": timestamp,
                "metadata_json": {**dict(payload.get("metadata_json") or {}), "template_label": template["label"]},
            }
        )
        self._audit(plan["project_id"], user, "monitoring_plan_created", "monitoring_plan", plan["monitoring_plan_id"], "Monitoring plan created")
        self._event(plan["project_id"], user, "monitoring.plan_created", "Monitoring plan created", plan["plan_name"], plan_id=plan["monitoring_plan_id"])
        self._evidence(plan["project_id"], user, "monitoring_plan", "Monitoring plan captured", "Monitoring plan definition was persisted.", {"plan": plan})
        self._notify(plan.get("monitoring_owner_user_id"), user, plan["project_id"], "monitoring_plan", plan["monitoring_plan_id"], "Monitoring plan assigned", plan["plan_name"], "normal")
        return self.seed_metrics_from_template(plan["monitoring_plan_id"], user)

    def get_plan_by_project(self, project_id: str) -> Dict[str, Any]:
        plan = self.monitoring.get_plan_by_project(project_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Monitoring plan has not been defined for this project.")
        return self.plan_detail(plan["monitoring_plan_id"])

    def list_plans(self, filters: Mapping[str, Any]) -> Dict[str, Any]:
        plans = self.monitoring.list_plans(**{k: v for k, v in filters.items() if k in {"project_id", "status", "workflow_type", "owner_user_id", "search", "limit"}})
        items = [self._enrich_plan(plan) for plan in plans]
        return {"items": items, "total": len(items)}

    def _enrich_plan(self, plan: Mapping[str, Any]) -> Dict[str, Any]:
        project = self.persistence.projects.get(plan["project_id"]) or {}
        runs = self.monitoring.list_runs(plan["monitoring_plan_id"], limit=1)
        alerts = self.monitoring.list_alerts(monitoring_plan_id=plan["monitoring_plan_id"], limit=500)
        open_alerts = [a for a in alerts if a.get("status") not in {"resolved", "closed", "accepted_risk"}]
        latest = runs[0] if runs else None
        return {
            **dict(plan),
            "project_name": project.get("project_name") or plan["project_id"],
            "last_run_at": (latest or {}).get("completed_at") or (latest or {}).get("executed_at"),
            "latest_run_status": (latest or {}).get("run_status"),
            "overall_status": (latest or {}).get("overall_status") or ("Breach" if any(a.get("severity") in {"high", "critical"} for a in open_alerts) else "Current"),
            "open_alert_count": len(open_alerts),
            "high_critical_alert_count": len([a for a in open_alerts if a.get("severity") in {"high", "critical"}]),
        }

    def update_plan(self, monitoring_plan_id: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        plan = self._plan(monitoring_plan_id)
        updated = self.monitoring.upsert_plan({**plan, **{k: v for k, v in payload.items() if v is not None}, "metadata_json": {**_metadata(plan), **dict(payload.get("metadata_json") or {})}, "updated_at": now_iso()})
        self._audit(updated["project_id"], user, "monitoring_plan_updated", "monitoring_plan", monitoring_plan_id, "Monitoring plan updated")
        self._event(updated["project_id"], user, "monitoring.plan_updated", "Monitoring plan updated", plan_id=monitoring_plan_id)
        return self.plan_detail(monitoring_plan_id)

    def set_plan_status(self, monitoring_plan_id: str, status: str, user: Mapping[str, Any]) -> Dict[str, Any]:
        plan = self._plan(monitoring_plan_id)
        updated = self.monitoring.upsert_plan({**plan, "plan_status": status, "updated_at": now_iso()})
        action = {"active": "monitoring_plan_activated", "paused": "monitoring_plan_paused", "retired": "monitoring_plan_retired"}.get(status, f"monitoring_plan_{status}")
        self._audit(updated["project_id"], user, action, "monitoring_plan", monitoring_plan_id, f"Monitoring plan {status}")
        self._event(updated["project_id"], user, f"monitoring.plan_{status}", f"Monitoring plan {status}", plan_id=monitoring_plan_id)
        return self.plan_detail(monitoring_plan_id)

    def seed_metrics_from_template(self, monitoring_plan_id: str, user: Mapping[str, Any]) -> Dict[str, Any]:
        plan = self._plan(monitoring_plan_id)
        template = template_for_workflow(plan.get("template_id") or plan.get("workflow_type"))
        existing = {m["metric_name"].lower(): m for m in self.monitoring.list_metrics(monitoring_plan_id)}
        for item in template["metrics"]:
            if item["metric_name"].lower() in existing:
                continue
            self.monitoring.upsert_metric({**item, "monitoring_metric_id": _id("monmet"), "monitoring_plan_id": monitoring_plan_id, "project_id": plan["project_id"], "created_at": now_iso(), "updated_at": now_iso(), "metadata_json": {"seeded_from_template": template["template_id"]}})
        self._audit(plan["project_id"], user, "monitoring_metric_added", "monitoring_plan", monitoring_plan_id, "Monitoring metrics seeded", template["label"])
        self._event(plan["project_id"], user, "monitoring.metrics_seeded", "Monitoring metrics seeded", template["label"], plan_id=monitoring_plan_id)
        self._evidence(plan["project_id"], user, "monitoring_metric_thresholds", "Monitoring metric thresholds captured", "Template monitoring metric thresholds were persisted.", {"template": template["template_id"], "metrics": self.monitoring.list_metrics(monitoring_plan_id)})
        return self.plan_detail(monitoring_plan_id)

    def add_metric(self, monitoring_plan_id: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        plan = self._plan(monitoring_plan_id)
        metric = self.monitoring.upsert_metric({**dict(payload), "monitoring_metric_id": _id("monmet"), "monitoring_plan_id": monitoring_plan_id, "project_id": plan["project_id"], "created_at": now_iso(), "updated_at": now_iso()})
        self._audit(plan["project_id"], user, "monitoring_metric_added", "monitoring_metric", metric["monitoring_metric_id"], "Monitoring metric added", metric["metric_name"])
        self._event(plan["project_id"], user, "monitoring.metric_added", "Monitoring metric added", metric["metric_name"], plan_id=monitoring_plan_id)
        return metric

    def update_metric(self, monitoring_metric_id: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        metric = self.monitoring.get_metric(monitoring_metric_id)
        if not metric:
            raise HTTPException(status_code=404, detail="Monitoring metric was not found.")
        updated = self.monitoring.upsert_metric({**metric, **{k: v for k, v in payload.items() if v is not None}, "metadata_json": {**_metadata(metric), **dict(payload.get("metadata_json") or {})}, "updated_at": now_iso()})
        self._audit(updated["project_id"], user, "monitoring_metric_updated", "monitoring_metric", monitoring_metric_id, "Monitoring metric updated", updated["metric_name"])
        return updated

    def remove_metric(self, monitoring_metric_id: str, user: Mapping[str, Any]) -> Dict[str, Any]:
        metric = self.monitoring.get_metric(monitoring_metric_id)
        if not metric:
            raise HTTPException(status_code=404, detail="Monitoring metric was not found.")
        self.monitoring.remove_metric(monitoring_metric_id)
        self._audit(metric["project_id"], user, "monitoring_metric_removed", "monitoring_metric", monitoring_metric_id, "Monitoring metric removed", metric["metric_name"])
        return {"removed": True, "monitoring_metric_id": monitoring_metric_id}

    def create_run(self, monitoring_plan_id: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        plan = self._plan(monitoring_plan_id)
        run = self.monitoring.upsert_run({**dict(payload), "monitoring_run_id": _id("monrun"), "monitoring_plan_id": monitoring_plan_id, "project_id": plan["project_id"], "run_status": "draft", "created_at": now_iso(), "updated_at": now_iso()})
        self._audit(plan["project_id"], user, "monitoring_run_created", "monitoring_run", run["monitoring_run_id"], "Monitoring run created")
        self._event(plan["project_id"], user, "monitoring.run_created", "Monitoring run created", run.get("run_name"), plan_id=monitoring_plan_id, run_id=run["monitoring_run_id"])
        return run

    def start_run(self, monitoring_run_id: str, user: Mapping[str, Any]) -> Dict[str, Any]:
        run = self._run(monitoring_run_id)
        updated = self.monitoring.upsert_run({**run, "run_status": "running", "executed_by_user_id": _user_id(user), "executed_at": now_iso(), "updated_at": now_iso()})
        self._audit(updated["project_id"], user, "monitoring_run_started", "monitoring_run", monitoring_run_id, "Monitoring run started")
        self._event(updated["project_id"], user, "monitoring.run_started", "Monitoring run started", run_id=monitoring_run_id, plan_id=updated["monitoring_plan_id"])
        return updated

    def record_observation(self, monitoring_run_id: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        run = self._run(monitoring_run_id)
        metric = self.monitoring.get_metric(str(payload["monitoring_metric_id"]))
        if not metric:
            raise HTTPException(status_code=404, detail="Monitoring metric was not found.")
        evaluation = self.evaluate_thresholds(metric, payload.get("observed_value"))
        observation = self.monitoring.create_observation({**dict(payload), **evaluation, "observation_id": _id("monobs"), "monitoring_run_id": monitoring_run_id, "project_id": run["project_id"], "metric_name": metric["metric_name"], "created_at": now_iso()})
        if observation["status"] in {"warning", "breach"}:
            severity = "critical" if observation["status"] == "breach" else "medium"
            self.create_alert(
                {
                    "project_id": run["project_id"],
                    "monitoring_plan_id": run["monitoring_plan_id"],
                    "monitoring_run_id": monitoring_run_id,
                    "alert_type": "threshold",
                    "severity": severity,
                    "title": f"{metric['metric_name']} {observation['status']}",
                    "description": observation.get("interpretation"),
                    "metric_name": metric["metric_name"],
                    "observed_value": observation.get("observed_value"),
                    "owner_user_id": metric.get("owner_user_id") or self._plan(run["monitoring_plan_id"]).get("monitoring_owner_user_id"),
                },
                user,
            )
        return observation

    def complete_run(self, monitoring_run_id: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        run = self._run(monitoring_run_id)
        for observation in payload.get("observations") or []:
            self.record_observation(monitoring_run_id, observation, user)
        observations = self.monitoring.list_observations(monitoring_run_id)
        counts = Counter(o.get("status") for o in observations)
        overall = payload.get("overall_status") or ("breach" if counts["breach"] else "warning" if counts["warning"] else "pass")
        evidence_id = self._evidence(run["project_id"], user, "monitoring_run", "Monitoring run captured", "Monitoring run and observations were persisted.", {"run": run, "observations": observations, "overall_status": overall})
        updated = self.monitoring.upsert_run({**run, "run_status": "completed", "completed_at": now_iso(), "summary": payload.get("summary") or run.get("summary"), "overall_status": overall, "breach_count": counts["breach"], "warning_count": counts["warning"], "evidence_ref": evidence_id, "updated_at": now_iso()})
        self._audit(updated["project_id"], user, "monitoring_run_completed", "monitoring_run", monitoring_run_id, "Monitoring run completed", f"{counts['breach']} breaches and {counts['warning']} warnings.")
        self._event(updated["project_id"], user, "monitoring.run_completed", "Monitoring run completed", f"{overall} overall status.", plan_id=updated["monitoring_plan_id"], run_id=monitoring_run_id)
        if counts["breach"]:
            plan = self._plan(updated["monitoring_plan_id"])
            self._notify(plan.get("monitoring_owner_user_id"), user, updated["project_id"], "monitoring_run", monitoring_run_id, "Monitoring run completed with breach", f"{counts['breach']} breach(es) require review.", "high")
        return self.run_detail(monitoring_run_id)

    def fail_run(self, monitoring_run_id: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        run = self._run(monitoring_run_id)
        updated = self.monitoring.upsert_run({**run, "run_status": "failed", "summary": payload.get("summary") or run.get("summary"), "updated_at": now_iso()})
        self._audit(updated["project_id"], user, "monitoring_run_failed", "monitoring_run", monitoring_run_id, "Monitoring run failed")
        return updated

    def create_alert(self, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        alert = self.monitoring.upsert_alert({**dict(payload), "alert_id": _id("monalert"), "created_at": now_iso(), "updated_at": now_iso()})
        self._audit(alert["project_id"], user, "monitoring_alert_created", "monitoring_alert", alert["alert_id"], "Monitoring alert created", alert["title"])
        self._event(alert["project_id"], user, "monitoring.alert_created", "Monitoring alert created", alert["title"], plan_id=alert.get("monitoring_plan_id"), run_id=alert.get("monitoring_run_id"), metadata={"severity": alert.get("severity")})
        if alert.get("owner_user_id") or alert.get("severity") in {"high", "critical"}:
            self._notify(alert.get("owner_user_id") or _user_id(user), user, alert["project_id"], "monitoring_alert", alert["alert_id"], alert["title"], alert.get("description") or "Monitoring alert requires review.", alert.get("severity") or "normal")
        self._evidence(alert["project_id"], user, "monitoring_alert", "Monitoring alert captured", alert["title"], {"alert": alert})
        return alert

    def update_alert(self, alert_id: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        alert = self._alert(alert_id)
        updated = self.monitoring.upsert_alert({**alert, **{k: v for k, v in payload.items() if v is not None}, "metadata_json": {**_metadata(alert), **dict(payload.get("metadata_json") or {})}, "updated_at": now_iso()})
        self._audit(updated["project_id"], user, "monitoring_alert_updated", "monitoring_alert", alert_id, "Monitoring alert updated")
        return updated

    def set_alert_status(self, alert_id: str, status: str, user: Mapping[str, Any], notes: str | None = None) -> Dict[str, Any]:
        alert = self._alert(alert_id)
        updated = self.monitoring.upsert_alert({**alert, "status": status, "resolved_at": now_iso() if status in {"resolved", "accepted_risk", "closed"} else alert.get("resolved_at"), "resolution_notes": notes or alert.get("resolution_notes"), "updated_at": now_iso()})
        action_map = {"acknowledged": "monitoring_alert_acknowledged", "resolved": "monitoring_alert_resolved", "accepted_risk": "monitoring_alert_accepted_risk", "closed": "monitoring_alert_closed"}
        self._audit(updated["project_id"], user, action_map.get(status, "monitoring_alert_updated"), "monitoring_alert", alert_id, f"Monitoring alert {status}")
        self._event(updated["project_id"], user, f"monitoring.alert_{status}", f"Monitoring alert {status}", updated["title"], plan_id=updated.get("monitoring_plan_id"), run_id=updated.get("monitoring_run_id"))
        if status in {"resolved", "accepted_risk", "closed"}:
            self._evidence(updated["project_id"], user, "monitoring_resolution", "Monitoring alert resolution captured", updated["title"], {"alert": updated})
        return updated

    def create_action(self, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        action = self.monitoring.upsert_action({**dict(payload), "action_id": _id("monact"), "created_at": now_iso(), "updated_at": now_iso()})
        self._audit(action["project_id"], user, "monitoring_action_created", "monitoring_action", action["action_id"], "Monitoring action created", action["title"])
        self._event(action["project_id"], user, "monitoring.action_created", "Monitoring action created", action["title"], plan_id=action.get("monitoring_plan_id"))
        return action

    def update_action(self, action_id: str, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        action = self.monitoring.get_action(action_id)
        if not action:
            raise HTTPException(status_code=404, detail="Monitoring action was not found.")
        updated = self.monitoring.upsert_action({**action, **{k: v for k, v in payload.items() if v is not None}, "metadata_json": {**_metadata(action), **dict(payload.get("metadata_json") or {})}, "updated_at": now_iso()})
        self._audit(updated["project_id"], user, "monitoring_action_updated", "monitoring_action", action_id, "Monitoring action updated")
        return updated

    def complete_action(self, action_id: str, user: Mapping[str, Any]) -> Dict[str, Any]:
        return self.update_action(action_id, {"status": "complete", "completed_at": now_iso()}, user)

    def create_baseline(self, payload: Mapping[str, Any], user: Mapping[str, Any]) -> Dict[str, Any]:
        baseline = self.monitoring.create_baseline({**dict(payload), "baseline_id": _id("monbase"), "created_by_user_id": _user_id(user), "created_at": now_iso()})
        self._audit(baseline["project_id"], user, "monitoring_baseline_created", "monitoring_baseline", baseline["baseline_id"], "Monitoring baseline created")
        return baseline

    def create_validation_finding(self, alert_id: str, user: Mapping[str, Any]) -> Dict[str, Any]:
        _require_role(user, VALIDATION_ROLES, "Creating revalidation review")
        alert = self._alert(alert_id)
        action = self.create_action(
            {
                "project_id": alert["project_id"],
                "alert_id": alert_id,
                "monitoring_plan_id": alert.get("monitoring_plan_id"),
                "action_type": "revalidation_review",
                "title": "Review for revalidation",
                "description": f"Monitoring alert requires validation review: {alert.get('title')}",
                "owner_user_id": alert.get("owner_user_id"),
                "metadata_json": {"alert_id": alert_id, "validation_link_pending": True},
            },
            user,
        )
        self.persistence.decisions.upsert(
            {
                "decision_id": f"monitoring:{alert_id}:revalidation_review",
                "project_id": alert["project_id"],
                "decision_type": "monitoring_revalidation_review",
                "title": "Monitoring revalidation review triggered",
                "summary": alert.get("title"),
                "status": "recorded",
                "owner": alert.get("owner_name"),
                "created_by": _user_id(user),
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "payload_json": {"alert_id": alert_id, "monitoring_plan_id": alert.get("monitoring_plan_id")},
            }
        )
        self._audit(alert["project_id"], user, "revalidation_review_triggered", "monitoring_alert", alert_id, "Revalidation review triggered")
        self._notify(alert.get("owner_user_id"), user, alert["project_id"], "monitoring_alert", alert_id, "Revalidation review needed", alert.get("title") or "Monitoring alert needs validation review.", "high")
        return {"action": action, "validation_finding_created": False, "limitation": "A monitoring revalidation action was created. Direct validation-case linking is available when a validation case exists."}

    def run_detail(self, monitoring_run_id: str) -> Dict[str, Any]:
        run = self._run(monitoring_run_id)
        return {"run": run, "observations": self.monitoring.list_observations(monitoring_run_id)}

    def plan_detail(self, monitoring_plan_id: str) -> Dict[str, Any]:
        plan = self._plan(monitoring_plan_id)
        return {
            "plan": self._enrich_plan(plan),
            "metrics": self.monitoring.list_metrics(monitoring_plan_id),
            "runs": self.monitoring.list_runs(monitoring_plan_id, limit=50),
            "observations": self.monitoring.list_observations_for_plan(monitoring_plan_id, limit=500),
            "alerts": self.monitoring.list_alerts(monitoring_plan_id=monitoring_plan_id, limit=250),
            "actions": self.monitoring.list_actions(monitoring_plan_id=monitoring_plan_id, limit=250),
            "events": self.monitoring.list_events(monitoring_plan_id=monitoring_plan_id, limit=100),
            "baselines": self.monitoring.list_baselines(plan["project_id"]),
        }

    def summary(self) -> Dict[str, Any]:
        plans = self.monitoring.list_plans(limit=1000)
        alerts = self.monitoring.list_alerts(limit=1000)
        actions = self.monitoring.list_actions(limit=1000)
        runs = []
        for plan in plans:
            runs.extend(self.monitoring.list_runs(plan["monitoring_plan_id"], limit=20))
        open_alerts = [a for a in alerts if a.get("status") not in {"resolved", "closed", "accepted_risk"}]
        return {
            "active_plans": len([p for p in plans if p.get("plan_status") == "active"]),
            "total_plans": len(plans),
            "runs_this_period": len(runs),
            "open_alerts": len(open_alerts),
            "high_critical_alerts": len([a for a in open_alerts if a.get("severity") in {"high", "critical"}]),
            "breaches": sum(int(r.get("breach_count") or 0) for r in runs),
            "warnings": sum(int(r.get("warning_count") or 0) for r in runs),
            "next_reviews_due": len([p for p in plans if p.get("next_monitoring_date")]),
            "actions_open": len([a for a in actions if a.get("status") not in {"complete", "closed"}]),
            "plans_by_status": dict(Counter(p.get("plan_status") or "draft" for p in plans)),
            "alerts_by_severity": dict(Counter(a.get("severity") or "medium" for a in open_alerts)),
            "breaches_by_workflow_type": dict(Counter(p.get("workflow_type") or "generic" for p in plans if any(a.get("monitoring_plan_id") == p.get("monitoring_plan_id") and a.get("status") not in {"resolved", "closed", "accepted_risk"} for a in alerts))),
            "recent_events": self.monitoring.list_events(limit=30),
            "latest_alerts": alerts[:30],
        }


_service: MonitoringService | None = None


def get_monitoring_service() -> MonitoringService:
    global _service
    if _service is None:
        _service = MonitoringService()
    return _service

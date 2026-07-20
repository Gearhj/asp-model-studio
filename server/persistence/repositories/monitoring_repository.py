from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class MonitoringRepository(BaseRepository):
    def upsert_plan(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO monitoring_plans (
              monitoring_plan_id, project_id, asset_type, workflow_type, template_id,
              plan_name, plan_status, monitoring_owner_user_id, monitoring_owner_name,
              business_owner_user_id, business_owner_name, monitoring_cadence,
              first_monitoring_date, next_monitoring_date, production_start_date,
              monitoring_scope, data_source_ref, notes, created_by_user_id,
              created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(monitoring_plan_id) DO UPDATE SET
              asset_type = excluded.asset_type,
              workflow_type = excluded.workflow_type,
              template_id = excluded.template_id,
              plan_name = excluded.plan_name,
              plan_status = excluded.plan_status,
              monitoring_owner_user_id = excluded.monitoring_owner_user_id,
              monitoring_owner_name = excluded.monitoring_owner_name,
              business_owner_user_id = excluded.business_owner_user_id,
              business_owner_name = excluded.business_owner_name,
              monitoring_cadence = excluded.monitoring_cadence,
              first_monitoring_date = excluded.first_monitoring_date,
              next_monitoring_date = excluded.next_monitoring_date,
              production_start_date = excluded.production_start_date,
              monitoring_scope = excluded.monitoring_scope,
              data_source_ref = excluded.data_source_ref,
              notes = excluded.notes,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            (
                record["monitoring_plan_id"], record["project_id"], record.get("asset_type"), record.get("workflow_type"),
                record.get("template_id"), record.get("plan_name") or "Monitoring Plan", record.get("plan_status") or "draft",
                record.get("monitoring_owner_user_id"), record.get("monitoring_owner_name"), record.get("business_owner_user_id"),
                record.get("business_owner_name"), record.get("monitoring_cadence"), record.get("first_monitoring_date"),
                record.get("next_monitoring_date"), record.get("production_start_date"), record.get("monitoring_scope"),
                record.get("data_source_ref"), record.get("notes"), record.get("created_by_user_id"),
                record.get("created_at") or timestamp, timestamp, json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get_plan(record["monitoring_plan_id"]) or {}

    def get_plan(self, monitoring_plan_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM monitoring_plans WHERE monitoring_plan_id = ?", (monitoring_plan_id,))

    def get_plan_by_project(self, project_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM monitoring_plans WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1", (project_id,))

    def list_plans(self, *, project_id: str | None = None, status: str | None = None, workflow_type: str | None = None, owner_user_id: str | None = None, search: str | None = None, limit: int = 250) -> List[Dict[str, Any]]:
        query = "SELECT * FROM monitoring_plans WHERE 1=1"
        params: list[Any] = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if status:
            query += " AND plan_status = ?"
            params.append(status)
        if workflow_type:
            query += " AND workflow_type = ?"
            params.append(workflow_type)
        if owner_user_id:
            query += " AND monitoring_owner_user_id = ?"
            params.append(owner_user_id)
        if search:
            query += " AND (plan_name LIKE ? OR project_id LIKE ? OR monitoring_owner_name LIKE ?)"
            like = f"%{search}%"
            params.extend([like, like, like])
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        return self._many(query, params)

    def upsert_metric(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO monitoring_metrics (
              monitoring_metric_id, monitoring_plan_id, project_id, metric_name,
              metric_category, metric_definition, metric_direction, warning_threshold,
              breach_threshold, lower_warning_threshold, lower_breach_threshold, unit,
              cadence, owner_user_id, status, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(monitoring_metric_id) DO UPDATE SET
              metric_name = excluded.metric_name,
              metric_category = excluded.metric_category,
              metric_definition = excluded.metric_definition,
              metric_direction = excluded.metric_direction,
              warning_threshold = excluded.warning_threshold,
              breach_threshold = excluded.breach_threshold,
              lower_warning_threshold = excluded.lower_warning_threshold,
              lower_breach_threshold = excluded.lower_breach_threshold,
              unit = excluded.unit,
              cadence = excluded.cadence,
              owner_user_id = excluded.owner_user_id,
              status = excluded.status,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            (
                record["monitoring_metric_id"], record["monitoring_plan_id"], record["project_id"], record["metric_name"],
                record.get("metric_category") or "performance", record.get("metric_definition"), record.get("metric_direction"),
                record.get("warning_threshold"), record.get("breach_threshold"), record.get("lower_warning_threshold"),
                record.get("lower_breach_threshold"), record.get("unit"), record.get("cadence"), record.get("owner_user_id"),
                record.get("status") or "active", record.get("created_at") or timestamp, timestamp, json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get_metric(record["monitoring_metric_id"]) or {}

    def get_metric(self, monitoring_metric_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM monitoring_metrics WHERE monitoring_metric_id = ?", (monitoring_metric_id,))

    def list_metrics(self, monitoring_plan_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM monitoring_metrics WHERE monitoring_plan_id = ? ORDER BY metric_category, metric_name", (monitoring_plan_id,))

    def remove_metric(self, monitoring_metric_id: str) -> None:
        self._write("DELETE FROM monitoring_metrics WHERE monitoring_metric_id = ?", (monitoring_metric_id,))

    def upsert_run(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO monitoring_runs (
              monitoring_run_id, monitoring_plan_id, project_id, run_name, run_status,
              run_period_start, run_period_end, data_version_ref, executed_by_user_id,
              executed_at, completed_at, summary, overall_status, breach_count,
              warning_count, evidence_ref, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(monitoring_run_id) DO UPDATE SET
              run_name = excluded.run_name,
              run_status = excluded.run_status,
              run_period_start = excluded.run_period_start,
              run_period_end = excluded.run_period_end,
              data_version_ref = excluded.data_version_ref,
              executed_by_user_id = excluded.executed_by_user_id,
              executed_at = excluded.executed_at,
              completed_at = excluded.completed_at,
              summary = excluded.summary,
              overall_status = excluded.overall_status,
              breach_count = excluded.breach_count,
              warning_count = excluded.warning_count,
              evidence_ref = excluded.evidence_ref,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            (
                record["monitoring_run_id"], record["monitoring_plan_id"], record["project_id"], record.get("run_name"),
                record.get("run_status") or "draft", record.get("run_period_start"), record.get("run_period_end"),
                record.get("data_version_ref"), record.get("executed_by_user_id"), record.get("executed_at"),
                record.get("completed_at"), record.get("summary"), record.get("overall_status"),
                int(record.get("breach_count") or 0), int(record.get("warning_count") or 0), record.get("evidence_ref"),
                record.get("created_at") or timestamp, timestamp, json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get_run(record["monitoring_run_id"]) or {}

    def get_run(self, monitoring_run_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM monitoring_runs WHERE monitoring_run_id = ?", (monitoring_run_id,))

    def list_runs(self, monitoring_plan_id: str | None = None, *, project_id: str | None = None, limit: int = 100) -> List[Dict[str, Any]]:
        query = "SELECT * FROM monitoring_runs WHERE 1=1"
        params: list[Any] = []
        if monitoring_plan_id:
            query += " AND monitoring_plan_id = ?"
            params.append(monitoring_plan_id)
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " ORDER BY COALESCE(completed_at, executed_at, updated_at) DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        return self._many(query, params)

    def create_observation(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            INSERT INTO monitoring_observations (
              observation_id, monitoring_run_id, monitoring_metric_id, project_id,
              metric_name, observed_value, baseline_value, comparison_value, status,
              threshold_used, interpretation, period_start, period_end, created_at,
              metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["observation_id"], record["monitoring_run_id"], record["monitoring_metric_id"], record["project_id"],
                record["metric_name"], record.get("observed_value"), record.get("baseline_value"), record.get("comparison_value"),
                record.get("status") or "not_available", record.get("threshold_used"), record.get("interpretation"),
                record.get("period_start"), record.get("period_end"), record.get("created_at") or now_iso(),
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one("SELECT * FROM monitoring_observations WHERE observation_id = ?", (record["observation_id"],)) or {}

    def list_observations(self, monitoring_run_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM monitoring_observations WHERE monitoring_run_id = ? ORDER BY metric_name", (monitoring_run_id,))

    def list_observations_for_plan(self, monitoring_plan_id: str, *, limit: int = 500) -> List[Dict[str, Any]]:
        return self._many(
            """
            SELECT o.* FROM monitoring_observations o
            JOIN monitoring_runs r ON r.monitoring_run_id = o.monitoring_run_id
            WHERE r.monitoring_plan_id = ?
            ORDER BY o.created_at DESC LIMIT ?
            """,
            (monitoring_plan_id, max(1, min(int(limit), 2000))),
        )

    def upsert_alert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO monitoring_alerts (
              alert_id, monitoring_run_id, monitoring_plan_id, project_id, alert_type,
              severity, status, title, description, metric_name, observed_value,
              threshold_value, owner_user_id, owner_name, due_date, created_at,
              updated_at, resolved_at, resolution_notes, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alert_id) DO UPDATE SET
              monitoring_run_id = excluded.monitoring_run_id,
              monitoring_plan_id = excluded.monitoring_plan_id,
              alert_type = excluded.alert_type,
              severity = excluded.severity,
              status = excluded.status,
              title = excluded.title,
              description = excluded.description,
              metric_name = excluded.metric_name,
              observed_value = excluded.observed_value,
              threshold_value = excluded.threshold_value,
              owner_user_id = excluded.owner_user_id,
              owner_name = excluded.owner_name,
              due_date = excluded.due_date,
              updated_at = excluded.updated_at,
              resolved_at = excluded.resolved_at,
              resolution_notes = excluded.resolution_notes,
              metadata_json = excluded.metadata_json
            """,
            (
                record["alert_id"], record.get("monitoring_run_id"), record.get("monitoring_plan_id"), record["project_id"],
                record.get("alert_type") or "threshold", record.get("severity") or "medium", record.get("status") or "open",
                record.get("title") or "Monitoring alert", record.get("description"), record.get("metric_name"),
                record.get("observed_value"), record.get("threshold_value"), record.get("owner_user_id"), record.get("owner_name"),
                record.get("due_date"), record.get("created_at") or timestamp, timestamp, record.get("resolved_at"),
                record.get("resolution_notes"), json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get_alert(record["alert_id"]) or {}

    def get_alert(self, alert_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM monitoring_alerts WHERE alert_id = ?", (alert_id,))

    def list_alerts(self, *, project_id: str | None = None, monitoring_plan_id: str | None = None, status: str | None = None, severity: str | None = None, owner_user_id: str | None = None, limit: int = 250) -> List[Dict[str, Any]]:
        query = "SELECT * FROM monitoring_alerts WHERE 1=1"
        params: list[Any] = []
        for field, value in (("project_id", project_id), ("monitoring_plan_id", monitoring_plan_id), ("status", status), ("severity", severity), ("owner_user_id", owner_user_id)):
            if value:
                query += f" AND {field} = ?"
                params.append(value)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        return self._many(query, params)

    def upsert_action(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO monitoring_actions (
              action_id, alert_id, monitoring_plan_id, project_id, action_type, title,
              description, owner_user_id, status, due_date, completed_at, created_at,
              updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(action_id) DO UPDATE SET
              alert_id = excluded.alert_id,
              monitoring_plan_id = excluded.monitoring_plan_id,
              action_type = excluded.action_type,
              title = excluded.title,
              description = excluded.description,
              owner_user_id = excluded.owner_user_id,
              status = excluded.status,
              due_date = excluded.due_date,
              completed_at = excluded.completed_at,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            (
                record["action_id"], record.get("alert_id"), record.get("monitoring_plan_id"), record["project_id"],
                record.get("action_type") or "review", record.get("title") or "Monitoring action", record.get("description"),
                record.get("owner_user_id"), record.get("status") or "open", record.get("due_date"), record.get("completed_at"),
                record.get("created_at") or timestamp, timestamp, json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get_action(record["action_id"]) or {}

    def get_action(self, action_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM monitoring_actions WHERE action_id = ?", (action_id,))

    def list_actions(self, *, project_id: str | None = None, monitoring_plan_id: str | None = None, alert_id: str | None = None, status: str | None = None, limit: int = 250) -> List[Dict[str, Any]]:
        query = "SELECT * FROM monitoring_actions WHERE 1=1"
        params: list[Any] = []
        for field, value in (("project_id", project_id), ("monitoring_plan_id", monitoring_plan_id), ("alert_id", alert_id), ("status", status)):
            if value:
                query += f" AND {field} = ?"
                params.append(value)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        return self._many(query, params)

    def create_baseline(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            INSERT INTO monitoring_baselines (
              baseline_id, project_id, baseline_name, baseline_type,
              baseline_period_start, baseline_period_end, data_version_ref,
              metric_summary_json, created_by_user_id, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["baseline_id"], record["project_id"], record.get("baseline_name") or "Monitoring baseline",
                record.get("baseline_type") or "production", record.get("baseline_period_start"), record.get("baseline_period_end"),
                record.get("data_version_ref"), json_dumps(record.get("metric_summary_json"), {}), record.get("created_by_user_id"),
                record.get("created_at") or now_iso(), json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get_baseline(record["baseline_id"]) or {}

    def get_baseline(self, baseline_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM monitoring_baselines WHERE baseline_id = ?", (baseline_id,))

    def list_baselines(self, project_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM monitoring_baselines WHERE project_id = ? ORDER BY created_at DESC", (project_id,))

    def create_event(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            INSERT INTO monitoring_events (
              event_id, monitoring_plan_id, monitoring_run_id, project_id, user_id,
              event_type, title, summary, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["event_id"], record.get("monitoring_plan_id"), record.get("monitoring_run_id"), record.get("project_id"),
                record.get("user_id"), record["event_type"], record.get("title") or record["event_type"], record.get("summary"),
                record.get("created_at") or now_iso(), json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one("SELECT * FROM monitoring_events WHERE event_id = ?", (record["event_id"],)) or {}

    def list_events(self, *, project_id: str | None = None, monitoring_plan_id: str | None = None, limit: int = 100) -> List[Dict[str, Any]]:
        query = "SELECT * FROM monitoring_events WHERE 1=1"
        params: list[Any] = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if monitoring_plan_id:
            query += " AND monitoring_plan_id = ?"
            params.append(monitoring_plan_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        return self._many(query, params)

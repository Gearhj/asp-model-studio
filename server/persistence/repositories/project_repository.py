from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class ProjectRepository(BaseRepository):
    def list(self) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM projects ORDER BY updated_at DESC, project_name")

    def get(self, project_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM projects WHERE project_id = ?", (project_id,))

    def delete(self, project_id: str) -> bool:
        """Delete a project and its project-scoped records through database cascades."""
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
            return cursor.rowcount > 0

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        created_at = record.get("created_at") or timestamp
        self._write(
            """
            INSERT INTO projects (
              project_id, project_name, project_type, workflow_type, template_id,
              status, owner_user_id, created_at, updated_at, metadata_json, created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
              project_name = excluded.project_name,
              project_type = excluded.project_type,
              workflow_type = excluded.workflow_type,
              template_id = excluded.template_id,
              status = excluded.status,
              owner_user_id = COALESCE(excluded.owner_user_id, projects.owner_user_id),
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json,
              created_by = COALESCE(projects.created_by, excluded.created_by),
              updated_by = excluded.updated_by
            """,
            (
                record["project_id"],
                record.get("project_name") or "Untitled ATLAS Project",
                record.get("project_type") or "predictive-modeling",
                record.get("workflow_type") or record.get("project_type") or "predictive-modeling",
                record.get("template_id"),
                record.get("status") or "active",
                record.get("owner_user_id"),
                created_at,
                timestamp,
                json_dumps(record.get("metadata_json"), {}),
                record.get("created_by") or record.get("owner_user_id"),
                record.get("updated_by") or record.get("owner_user_id"),
            ),
        )
        return self.get(record["project_id"]) or {}

    def ensure(self, project_id: str, defaults: Dict[str, Any] | None = None) -> Dict[str, Any]:
        existing = self.get(project_id)
        if existing:
            return existing
        values = defaults or {}
        return self.upsert(
            {
                "project_id": project_id,
                "project_name": values.get("project_name") or "Recovered ATLAS Project",
                "project_type": values.get("project_type") or "predictive-modeling",
                "workflow_type": values.get("workflow_type") or values.get("project_type") or "predictive-modeling",
                "status": values.get("status") or "active",
                "owner_user_id": values.get("owner_user_id"),
                "created_by": values.get("created_by") or values.get("owner_user_id"),
                "updated_by": values.get("updated_by") or values.get("owner_user_id"),
                "metadata_json": {"recoveredFromCompatibilityStore": True, **(values.get("metadata_json") or {})},
            }
        )

    def get_workflow_state(self, project_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM workflow_state WHERE project_id = ?", (project_id,))

    def upsert_workflow_state(self, project_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
        self.ensure(project_id)
        self._write(
            """
            INSERT INTO workflow_state (
              project_id, current_step_id, completed_steps_json, workflow_status_json,
              step_evidence_status_json, updated_at, completed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
              current_step_id = excluded.current_step_id,
              completed_steps_json = excluded.completed_steps_json,
              workflow_status_json = excluded.workflow_status_json,
              step_evidence_status_json = excluded.step_evidence_status_json,
              updated_at = excluded.updated_at,
              completed_by = excluded.completed_by
            """,
            (
                project_id,
                record.get("current_step_id"),
                json_dumps(record.get("completed_steps_json"), []),
                json_dumps(record.get("workflow_status_json"), {}),
                json_dumps(record.get("step_evidence_status_json"), {}),
                record.get("updated_at") or now_iso(),
                record.get("completed_by"),
            ),
        )
        return self.get_workflow_state(project_id) or {}

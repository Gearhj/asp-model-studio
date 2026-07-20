from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class DemoFeedbackRepository(BaseRepository):
    def list(self, *, project_id: str | None = None, limit: int = 250) -> List[Dict[str, Any]]:
        if project_id:
            return self._many(
                "SELECT * FROM demo_feedback WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                (project_id, max(1, min(int(limit), 1000))),
            )
        return self._many(
            "SELECT * FROM demo_feedback ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        )

    def get(self, feedback_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM demo_feedback WHERE feedback_id = ?", (feedback_id,))

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            INSERT INTO demo_feedback (
              feedback_id, project_id, user_id, route, workflow_type, step_id,
              issue_type, severity, expected_behavior, actual_behavior, notes,
              created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(feedback_id) DO UPDATE SET
              project_id = excluded.project_id,
              user_id = excluded.user_id,
              route = excluded.route,
              workflow_type = excluded.workflow_type,
              step_id = excluded.step_id,
              issue_type = excluded.issue_type,
              severity = excluded.severity,
              expected_behavior = excluded.expected_behavior,
              actual_behavior = excluded.actual_behavior,
              notes = excluded.notes,
              metadata_json = excluded.metadata_json
            """,
            (
                record["feedback_id"],
                record.get("project_id"),
                record.get("user_id"),
                record.get("route") or "/",
                record.get("workflow_type"),
                record.get("step_id"),
                record.get("issue_type") or "usability",
                record.get("severity") or "medium",
                record.get("expected_behavior"),
                record.get("actual_behavior"),
                record.get("notes"),
                record.get("created_at") or now_iso(),
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get(record["feedback_id"]) or {}

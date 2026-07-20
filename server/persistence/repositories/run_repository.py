from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class RunRepository(BaseRepository):
    def list_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM run_records WHERE project_id = ? ORDER BY COALESCE(started_at, completed_at) DESC", (project_id,))

    def get(self, run_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM run_records WHERE run_id = ?", (run_id,))

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            INSERT INTO run_records (
              run_id, project_id, run_type, workflow_type, status, started_at,
              completed_at, parameters_json, metrics_json, artifacts_json, error_json, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
              run_type = excluded.run_type,
              workflow_type = excluded.workflow_type,
              status = excluded.status,
              started_at = excluded.started_at,
              completed_at = excluded.completed_at,
              parameters_json = excluded.parameters_json,
              metrics_json = excluded.metrics_json,
              artifacts_json = excluded.artifacts_json,
              error_json = excluded.error_json,
              created_by = COALESCE(run_records.created_by, excluded.created_by)
            """,
            (
                record["run_id"],
                record["project_id"],
                record.get("run_type") or "workflow",
                record.get("workflow_type"),
                record.get("status") or "created",
                record.get("started_at") or now_iso(),
                record.get("completed_at"),
                json_dumps(record.get("parameters_json"), {}),
                json_dumps(record.get("metrics_json"), {}),
                json_dumps(record.get("artifacts_json"), {}),
                json_dumps(record.get("error_json"), {}),
                record.get("created_by"),
            ),
        )
        return self.get(record["run_id"]) or {}

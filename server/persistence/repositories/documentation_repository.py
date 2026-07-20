from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class DocumentationRepository(BaseRepository):
    def list_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM documentation_packages WHERE project_id = ? ORDER BY updated_at DESC", (project_id,))

    def get(self, package_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM documentation_packages WHERE package_id = ?", (package_id,))

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO documentation_packages (
              package_id, project_id, package_type, status, readiness_score,
              section_count, completed_section_count, created_at, updated_at, payload_json, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(package_id) DO UPDATE SET
              package_type = excluded.package_type,
              status = excluded.status,
              readiness_score = excluded.readiness_score,
              section_count = excluded.section_count,
              completed_section_count = excluded.completed_section_count,
              updated_at = excluded.updated_at,
              payload_json = excluded.payload_json,
              created_by = COALESCE(documentation_packages.created_by, excluded.created_by)
            """,
            (
                record["package_id"],
                record["project_id"],
                record.get("package_type") or "model_development_document",
                record.get("status") or "draft",
                record.get("readiness_score"),
                record.get("section_count"),
                record.get("completed_section_count"),
                record.get("created_at") or timestamp,
                timestamp,
                json_dumps(record.get("payload_json"), {}),
                record.get("created_by"),
            ),
        )
        return self.get(record["package_id"]) or {}

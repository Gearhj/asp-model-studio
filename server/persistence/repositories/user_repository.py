from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class UserRepository(BaseRepository):
    def list(self) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM users ORDER BY display_name")

    def get(self, user_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM users WHERE user_id = ?", (user_id,))

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        last_active_at = record.get("last_active_at") or timestamp
        self._write(
            """
            INSERT INTO users (user_id, display_name, email, role, status, created_at, updated_at, metadata_json, last_active_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              display_name = excluded.display_name,
              email = excluded.email,
              role = excluded.role,
              status = excluded.status,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json,
              last_active_at = excluded.last_active_at
            """,
            (
                record["user_id"],
                record.get("display_name") or record.get("email") or "ATLAS User",
                record.get("email"),
                record.get("role") or "data_scientist",
                record.get("status") or "active",
                record.get("created_at") or timestamp,
                timestamp,
                json_dumps(record.get("metadata_json"), {}),
                last_active_at,
            ),
        )
        return self.get(record["user_id"]) or {}

    def activity_summary(self, user_id: str) -> Dict[str, int]:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM projects WHERE owner_user_id = ? OR created_by = ?) AS project_count,
                  (SELECT COUNT(*) FROM evidence_artifacts WHERE created_by = ?) AS evidence_count,
                  (SELECT COUNT(*) FROM run_records WHERE created_by = ? AND LOWER(run_type) LIKE '%validation%') AS validation_count,
                  (SELECT COUNT(*) FROM export_artifacts WHERE created_by = ?) AS export_count
                """,
                (user_id, user_id, user_id, user_id, user_id),
            ).fetchone()
        return {
            "projectCount": int(row["project_count"] or 0),
            "evidenceCount": int(row["evidence_count"] or 0),
            "validationCount": int(row["validation_count"] or 0),
            "exportCount": int(row["export_count"] or 0),
        }

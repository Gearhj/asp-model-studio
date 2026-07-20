from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class AuditRepository(BaseRepository):
    def list(
        self,
        *,
        project_id: str | None = None,
        user_id: str | None = None,
        action_type: str | None = None,
        limit: int = 250,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM audit_log WHERE 1=1"
        params: list[Any] = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if action_type:
            query += " AND action_type = ?"
            params.append(action_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        return self._many(query, params)

    def get(self, audit_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM audit_log WHERE audit_id = ?", (audit_id,))

    def search(
        self,
        *,
        user_id: str | None = None,
        action_type: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        project_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        text: str | None = None,
        sharing_only: bool = False,
        admin_only: bool = False,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM audit_log WHERE 1=1"
        params: list[Any] = []
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if action_type:
            query += " AND action_type = ?"
            params.append(action_type)
        if entity_type:
            query += " AND entity_type = ?"
            params.append(entity_type)
        if entity_id:
            query += " AND entity_id = ?"
            params.append(entity_id)
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if date_from:
            query += " AND created_at >= ?"
            params.append(date_from)
        if date_to:
            query += " AND created_at <= ?"
            params.append(date_to)
        if text:
            like = f"%{text}%"
            query += " AND (title LIKE ? OR summary LIKE ? OR entity_id LIKE ? OR metadata_json LIKE ?)"
            params.extend([like, like, like, like])
        if sharing_only:
            query += " AND (action_type LIKE '%share%' OR action_type LIKE '%permission%' OR action_type LIKE '%access%')"
        if admin_only:
            query += " AND (action_type LIKE 'user_%' OR action_type LIKE 'group_%' OR action_type LIKE '%permission%' OR action_type LIKE '%ownership%' OR action_type LIKE '%review%')"
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 5000)))
        return self._many(query, params)

    def create(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            INSERT INTO audit_log (
              audit_id, project_id, user_id, action_type, entity_type, entity_id,
              title, summary, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["audit_id"],
                record.get("project_id"),
                record.get("user_id"),
                record["action_type"],
                record.get("entity_type"),
                record.get("entity_id"),
                record.get("title") or record["action_type"].replace(".", " ").title(),
                record.get("summary"),
                record.get("created_at") or now_iso(),
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get(record["audit_id"]) or {}

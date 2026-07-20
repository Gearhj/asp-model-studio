from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class DecisionJournalRepository(BaseRepository):
    def list_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM decision_journal WHERE project_id = ? ORDER BY updated_at DESC", (project_id,))

    def get(self, decision_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM decision_journal WHERE decision_id = ?", (decision_id,))

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO decision_journal (
              decision_id, project_id, decision_type, title, summary, status, owner,
              created_by, created_at, updated_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(decision_id) DO UPDATE SET
              decision_type = excluded.decision_type,
              title = excluded.title,
              summary = excluded.summary,
              status = excluded.status,
              owner = excluded.owner,
              updated_at = excluded.updated_at,
              payload_json = excluded.payload_json
            """,
            (
                record["decision_id"],
                record["project_id"],
                record.get("decision_type") or "workflow_decision",
                record.get("title") or "ATLAS Decision",
                record.get("summary"),
                record.get("status") or "draft",
                record.get("owner"),
                record.get("created_by"),
                record.get("created_at") or timestamp,
                timestamp,
                json_dumps(record.get("payload_json"), {}),
            ),
        )
        return self.get(record["decision_id"]) or {}

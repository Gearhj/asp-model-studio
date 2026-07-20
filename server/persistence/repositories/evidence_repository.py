from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class EvidenceRepository(BaseRepository):
    def list_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM evidence_artifacts WHERE project_id = ? ORDER BY created_at DESC", (project_id,))

    def get(self, evidence_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM evidence_artifacts WHERE evidence_id = ?", (evidence_id,))

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("created_at") or now_iso()
        self._write(
            """
            INSERT INTO evidence_artifacts (
              evidence_id, project_id, workflow_type, step_id, artifact_type, status,
              title, summary, source_ref, artifact_hash, created_by, created_at,
              captured_at, approved_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(evidence_id) DO UPDATE SET
              workflow_type = excluded.workflow_type,
              step_id = excluded.step_id,
              artifact_type = excluded.artifact_type,
              status = excluded.status,
              title = excluded.title,
              summary = excluded.summary,
              source_ref = excluded.source_ref,
              artifact_hash = excluded.artifact_hash,
              captured_at = excluded.captured_at,
              approved_at = excluded.approved_at,
              payload_json = excluded.payload_json
            """,
            (
                record["evidence_id"],
                record["project_id"],
                record.get("workflow_type"),
                record.get("step_id"),
                record.get("artifact_type") or "evidence",
                record.get("status") or "draft",
                record.get("title") or "ATLAS Evidence",
                record.get("summary"),
                record.get("source_ref"),
                record.get("artifact_hash"),
                record.get("created_by"),
                timestamp,
                record.get("captured_at") or timestamp,
                record.get("approved_at"),
                json_dumps(record.get("payload_json"), {}),
            ),
        )
        return self.get(record["evidence_id"]) or {}

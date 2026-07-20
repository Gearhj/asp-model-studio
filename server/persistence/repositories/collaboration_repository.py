from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class CollaborationRepository(BaseRepository):
    def create_ownership_transfer(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("created_at") or now_iso()
        self._write(
            """
            INSERT INTO ownership_transfers (
              transfer_id, resource_type, resource_id, from_user_id, to_user_id,
              requested_by_user_id, approved_by_user_id, status, reason, created_at,
              approved_at, completed_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["transfer_id"],
                record["resource_type"],
                record["resource_id"],
                record.get("from_user_id"),
                record["to_user_id"],
                record["requested_by_user_id"],
                record.get("approved_by_user_id"),
                record.get("status") or "pending",
                record.get("reason"),
                timestamp,
                record.get("approved_at"),
                record.get("completed_at"),
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get_ownership_transfer(record["transfer_id"]) or {}

    def get_ownership_transfer(self, transfer_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM ownership_transfers WHERE transfer_id = ?", (transfer_id,))

    def list_ownership_transfers(self, *, status: str | None = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM ownership_transfers WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        return self._many(query, params)

    def update_ownership_transfer(self, transfer_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        allowed = ["status", "approved_by_user_id", "approved_at", "completed_at", "metadata_json"]
        assignments = []
        params: list[Any] = []
        for key in allowed:
            if key in updates:
                assignments.append(f"{key} = ?")
                params.append(json_dumps(updates[key], {}) if key == "metadata_json" else updates[key])
        if not assignments:
            return self.get_ownership_transfer(transfer_id) or {}
        params.append(transfer_id)
        self._write(f"UPDATE ownership_transfers SET {', '.join(assignments)} WHERE transfer_id = ?", params)
        return self.get_ownership_transfer(transfer_id) or {}

    def create_access_review(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("created_at") or now_iso()
        self._write(
            """
            INSERT INTO access_reviews (
              review_id, review_name, resource_type, resource_id, scope, owner_user_id,
              status, due_date, created_by_user_id, created_at, completed_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["review_id"],
                record["review_name"],
                record.get("resource_type"),
                record.get("resource_id"),
                record["scope"],
                record.get("owner_user_id"),
                record.get("status") or "draft",
                record.get("due_date"),
                record.get("created_by_user_id"),
                timestamp,
                record.get("completed_at"),
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get_access_review(record["review_id"]) or {}

    def get_access_review(self, review_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM access_reviews WHERE review_id = ?", (review_id,))

    def list_access_reviews(self, *, status: str | None = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM access_reviews WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        return self._many(query, params)

    def update_access_review(self, review_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        allowed = ["status", "completed_at", "metadata_json"]
        assignments = []
        params: list[Any] = []
        for key in allowed:
            if key in updates:
                assignments.append(f"{key} = ?")
                params.append(json_dumps(updates[key], {}) if key == "metadata_json" else updates[key])
        if not assignments:
            return self.get_access_review(review_id) or {}
        params.append(review_id)
        self._write(f"UPDATE access_reviews SET {', '.join(assignments)} WHERE review_id = ?", params)
        return self.get_access_review(review_id) or {}

    def create_access_review_item(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            INSERT INTO access_review_items (
              review_item_id, review_id, resource_type, resource_id, principal_type,
              principal_id, permission_level, decision, reviewer_user_id,
              reviewer_notes, decided_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["review_item_id"],
                record["review_id"],
                record["resource_type"],
                record["resource_id"],
                record["principal_type"],
                record["principal_id"],
                record["permission_level"],
                record.get("decision") or "pending",
                record.get("reviewer_user_id"),
                record.get("reviewer_notes"),
                record.get("decided_at"),
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get_access_review_item(record["review_item_id"]) or {}

    def get_access_review_item(self, review_item_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM access_review_items WHERE review_item_id = ?", (review_item_id,))

    def list_access_review_items(self, review_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM access_review_items WHERE review_id = ? ORDER BY resource_type, resource_id", (review_id,))

    def decide_access_review_item(self, review_item_id: str, decision: str, reviewer_user_id: str, notes: str | None = None) -> Dict[str, Any]:
        self._write(
            """
            UPDATE access_review_items
            SET decision = ?, reviewer_user_id = ?, reviewer_notes = ?, decided_at = ?
            WHERE review_item_id = ?
            """,
            (decision, reviewer_user_id, notes, now_iso(), review_item_id),
        )
        return self.get_access_review_item(review_item_id) or {}

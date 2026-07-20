from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class SharingRepository(BaseRepository):
    def create_event(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            INSERT INTO sharing_events (
              sharing_event_id, resource_type, resource_id, shared_by_user_id,
              principal_type, principal_id, permission_level, message, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["sharing_event_id"],
                record["resource_type"],
                record["resource_id"],
                record["shared_by_user_id"],
                record["principal_type"],
                record["principal_id"],
                record["permission_level"],
                record.get("message"),
                record.get("created_at") or now_iso(),
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one("SELECT * FROM sharing_events WHERE sharing_event_id = ?", (record["sharing_event_id"],)) or {}

    def list_events_for_resource(self, resource_type: str, resource_id: str) -> List[Dict[str, Any]]:
        return self._many(
            "SELECT * FROM sharing_events WHERE resource_type = ? AND resource_id = ? ORDER BY created_at DESC",
            (resource_type, resource_id),
        )

    def list_events_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM sharing_events WHERE shared_by_user_id = ? ORDER BY created_at DESC", (user_id,))

    def create_share_link(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            INSERT INTO share_links (
              share_link_id, resource_type, resource_id, token_hash, permission_level,
              created_by_user_id, created_at, expires_at, revoked_at, status, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["share_link_id"],
                record["resource_type"],
                record["resource_id"],
                record["token_hash"],
                record.get("permission_level") or "view",
                record["created_by_user_id"],
                record.get("created_at") or now_iso(),
                record.get("expires_at"),
                record.get("revoked_at"),
                record.get("status") or "active",
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one("SELECT * FROM share_links WHERE share_link_id = ?", (record["share_link_id"],)) or {}

    def revoke_share_link(self, share_link_id: str, revoked_at: str | None = None) -> Dict[str, Any] | None:
        self._write(
            "UPDATE share_links SET status = 'revoked', revoked_at = ? WHERE share_link_id = ?",
            (revoked_at or now_iso(), share_link_id),
        )
        return self._one("SELECT * FROM share_links WHERE share_link_id = ?", (share_link_id,))

    def list_share_links_for_resource(self, resource_type: str, resource_id: str) -> List[Dict[str, Any]]:
        return self._many(
            "SELECT * FROM share_links WHERE resource_type = ? AND resource_id = ? ORDER BY created_at DESC",
            (resource_type, resource_id),
        )

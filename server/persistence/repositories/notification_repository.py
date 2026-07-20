from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class NotificationRepository(BaseRepository):
    def create(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("created_at") or now_iso()
        self._write(
            """
            INSERT INTO notifications (
              notification_id, recipient_user_id, actor_user_id, notification_type,
              title, message, resource_type, resource_id, project_id, status,
              priority, created_at, read_at, dismissed_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["notification_id"],
                record["recipient_user_id"],
                record.get("actor_user_id"),
                record["notification_type"],
                record["title"],
                record.get("message"),
                record.get("resource_type"),
                record.get("resource_id"),
                record.get("project_id"),
                record.get("status") or "unread",
                record.get("priority") or "normal",
                timestamp,
                record.get("read_at"),
                record.get("dismissed_at"),
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get(record["notification_id"]) or {}

    def get(self, notification_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM notifications WHERE notification_id = ?", (notification_id,))

    def list_for_user(self, user_id: str, *, include_dismissed: bool = False, limit: int = 100) -> List[Dict[str, Any]]:
        query = "SELECT * FROM notifications WHERE recipient_user_id = ?"
        params: list[Any] = [user_id]
        if not include_dismissed:
            query += " AND dismissed_at IS NULL"
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        return self._many(query, params)

    def unread_count(self, user_id: str) -> int:
        row = self._one(
            "SELECT COUNT(*) AS count FROM notifications WHERE recipient_user_id = ? AND status = 'unread' AND dismissed_at IS NULL",
            (user_id,),
        )
        return int((row or {}).get("count") or 0)

    def mark_read(self, notification_id: str, user_id: str) -> Dict[str, Any]:
        self._write(
            """
            UPDATE notifications
            SET status = 'read', read_at = COALESCE(read_at, ?)
            WHERE notification_id = ? AND recipient_user_id = ?
            """,
            (now_iso(), notification_id, user_id),
        )
        return self.get(notification_id) or {}

    def dismiss(self, notification_id: str, user_id: str) -> Dict[str, Any]:
        self._write(
            """
            UPDATE notifications
            SET status = 'dismissed', dismissed_at = COALESCE(dismissed_at, ?)
            WHERE notification_id = ? AND recipient_user_id = ?
            """,
            (now_iso(), notification_id, user_id),
        )
        return self.get(notification_id) or {}

    def mark_all_read(self, user_id: str) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE notifications
                SET status = 'read', read_at = COALESCE(read_at, ?)
                WHERE recipient_user_id = ? AND status = 'unread' AND dismissed_at IS NULL
                """,
                (now_iso(), user_id),
            )
            return int(cursor.rowcount or 0)

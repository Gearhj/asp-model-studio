from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List

from ..persistence.db import now_iso
from ..persistence.service import PersistenceService, get_persistence_service
from ..security.security_store import get_user
from ..sharing.sharing_service import _audit, _user_id


class NotificationService:
    def __init__(self, persistence: PersistenceService | None = None) -> None:
        self.persistence = persistence or get_persistence_service()

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        recipient_id = payload["recipientUserId"]
        recipient = get_user(recipient_id)
        if recipient and recipient.get("status") != "active":
            return {}
        record = self.persistence.notifications.create(
            {
                "notification_id": f"notif_{uuid.uuid4().hex}",
                "recipient_user_id": recipient_id,
                "actor_user_id": payload.get("actorUserId"),
                "notification_type": payload["notificationType"],
                "title": payload["title"],
                "message": payload.get("message"),
                "resource_type": payload.get("resourceType"),
                "resource_id": payload.get("resourceId"),
                "project_id": payload.get("projectId"),
                "priority": payload.get("priority") or "normal",
                "metadata_json": payload.get("metadata") or {},
            }
        )
        _audit(
            self.persistence,
            payload.get("actorUserId") or "system",
            "notification_created",
            payload.get("resourceType") or "notification",
            payload.get("resourceId") or record.get("notification_id"),
            f"Created notification for {recipient_id}.",
            {"notification_type": payload["notificationType"], "recipient_user_id": recipient_id},
        )
        return record

    def notify_many(self, recipients: Iterable[str], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        seen: set[str] = set()
        results: list[Dict[str, Any]] = []
        for recipient_id in recipients:
            if not recipient_id or recipient_id in seen:
                continue
            seen.add(recipient_id)
            results.append(self.create({**payload, "recipientUserId": recipient_id}))
        return [row for row in results if row]

    def list_for_user(self, user: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.persistence.notifications.list_for_user(_user_id(user))

    def unread_count(self, user: Dict[str, Any]) -> int:
        return self.persistence.notifications.unread_count(_user_id(user))

    def mark_read(self, user: Dict[str, Any], notification_id: str) -> Dict[str, Any]:
        return self.persistence.notifications.mark_read(notification_id, _user_id(user))

    def dismiss(self, user: Dict[str, Any], notification_id: str) -> Dict[str, Any]:
        return self.persistence.notifications.dismiss(notification_id, _user_id(user))

    def mark_all_read(self, user: Dict[str, Any]) -> Dict[str, Any]:
        count = self.persistence.notifications.mark_all_read(_user_id(user))
        return {"updated": count, "read_at": now_iso()}

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from ..security.security_store import require_user
from .notification_service import NotificationService
from .schemas import NotificationCreate

router = APIRouter()


def _service() -> NotificationService:
    return NotificationService()


@router.get("/notifications")
def list_notifications(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "notifications": _service().list_for_user(user)}


@router.get("/notifications/unread-count")
def unread_count(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "count": _service().unread_count(user)}


@router.post("/notifications")
def create_notification(payload: NotificationCreate, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    data = payload.dict()
    data.setdefault("actorUserId", user.get("userId"))
    return {"ok": True, "notification": _service().create(data)}


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "notification": _service().mark_read(user, notification_id)}


@router.post("/notifications/{notification_id}/dismiss")
def dismiss_notification(notification_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "notification": _service().dismiss(user, notification_id)}


@router.post("/notifications/mark-all-read")
def mark_all_read(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().mark_all_read(user)}

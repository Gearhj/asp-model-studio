from __future__ import annotations

from pydantic import BaseModel


class NotificationCreate(BaseModel):
    recipientUserId: str
    actorUserId: str | None = None
    notificationType: str
    title: str
    message: str | None = None
    resourceType: str | None = None
    resourceId: str | None = None
    projectId: str | None = None
    priority: str = "normal"
    metadata: dict = {}

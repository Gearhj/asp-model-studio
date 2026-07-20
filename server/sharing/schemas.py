from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel


class ShareResourceRequest(BaseModel):
    principalType: str
    principalId: str
    permissionLevel: str = "view"
    message: Optional[str] = None
    expiresAt: Optional[str] = None
    metadata: Dict[str, Any] = {}


class RevokeShareRequest(BaseModel):
    principalType: str
    principalId: str


class AccessRequestCreate(BaseModel):
    requestedPermission: str = "view"
    reason: Optional[str] = None


class ShareLinkCreate(BaseModel):
    permissionLevel: str = "view"
    expiresAt: Optional[str] = None

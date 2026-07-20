from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from ..security.security_store import require_user
from .schemas import AccessRequestCreate, RevokeShareRequest, ShareLinkCreate, ShareResourceRequest
from .sharing_service import SharingService

router = APIRouter()


def _service() -> SharingService:
    return SharingService()


@router.get("/sharing/resources/{resource_type}/{resource_id}")
def sharing_status(resource_type: str, resource_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "sharing": _service().sharing_status(user, resource_type, resource_id)}


@router.post("/sharing/resources/{resource_type}/{resource_id}/share")
def share_resource(resource_type: str, resource_id: str, payload: ShareResourceRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().share_resource(user, resource_type, resource_id, payload.dict())}


@router.post("/sharing/resources/{resource_type}/{resource_id}/revoke")
def revoke_share(resource_type: str, resource_id: str, payload: RevokeShareRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().revoke_share(user, resource_type, resource_id, payload.principalType, payload.principalId)}


@router.get("/sharing/shared-with-me")
def shared_with_me(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "resources": _service().shared_with_me(user)}


@router.get("/sharing/shared-by-me")
def shared_by_me(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "resources": _service().shared_by_me(user)}


@router.post("/sharing/resources/{resource_type}/{resource_id}/request-access")
def request_access(resource_type: str, resource_id: str, payload: AccessRequestCreate, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "request": _service().request_access(user, resource_type, resource_id, payload.requestedPermission, payload.reason)}


@router.get("/sharing/access-check/{resource_type}/{resource_id}")
def access_check(resource_type: str, resource_id: str, permission: str = "view", user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "access": _service().check_permission(user, resource_type, resource_id, permission)}


@router.post("/sharing/resources/{resource_type}/{resource_id}/share-link")
def create_share_link(resource_type: str, resource_id: str, payload: ShareLinkCreate, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "shareLink": _service().create_share_link(user, resource_type, resource_id, payload.permissionLevel, payload.expiresAt)}


@router.post("/sharing/share-links/{share_link_id}/revoke")
def revoke_share_link(share_link_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "shareLink": _service().revoke_share_link(user, share_link_id)}

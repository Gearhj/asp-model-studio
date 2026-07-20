from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ..security.security_store import require_user
from .admin_service import AdminService, PERMISSION_LEVELS, PLATFORM_ROLES, RESOURCE_TYPES, ROLE_DEFINITIONS
from .schemas import (
    AccessRequestResolution,
    AccessReviewCreate,
    AccessReviewItemDecision,
    AdminUserCreate,
    AdminUserUpdate,
    AuditSearchQuery,
    BulkPermissionApplyRequest,
    BulkPermissionPreviewRequest,
    GroupCreate,
    GroupMemberRequest,
    GroupUpdate,
    OwnershipTransferRequest,
    OwnershipTransferResolution,
    PermissionGrantRequest,
    PermissionRevokeRequest,
    RoleUpdate,
    StatusUpdate,
)

router = APIRouter()


def _service() -> AdminService:
    return AdminService()


@router.get("/admin/users")
def list_admin_users(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "users": _service().list_users(user)}


@router.get("/admin/users/{user_id}")
def get_admin_user(user_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "user": _service().get_user(user, user_id)}


@router.post("/admin/users")
def create_admin_user(payload: AdminUserCreate, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "user": _service().create_user(user, payload.dict())}


@router.put("/admin/users/{user_id}")
def put_admin_user(user_id: str, payload: AdminUserUpdate, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "user": _service().update_user(user, user_id, payload.dict())}


@router.put("/admin/users/{user_id}/role")
def put_admin_user_role(user_id: str, payload: RoleUpdate, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "user": _service().update_role(user, user_id, payload.role)}


@router.put("/admin/users/{user_id}/status")
def put_admin_user_status(user_id: str, payload: StatusUpdate, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "user": _service().update_status(user, user_id, payload.status)}


@router.get("/admin/groups")
def list_groups(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "groups": _service().list_groups(user)}


@router.post("/admin/groups")
def create_group(payload: GroupCreate, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "group": _service().create_group(user, payload.dict())}


@router.get("/admin/groups/{group_id}")
def get_group(group_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "group": _service().get_group(user, group_id)}


@router.put("/admin/groups/{group_id}")
def update_group(group_id: str, payload: GroupUpdate, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "group": _service().update_group(user, group_id, payload.dict())}


@router.post("/admin/groups/{group_id}/members")
def add_group_member(group_id: str, payload: GroupMemberRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "member": _service().add_group_member(user, group_id, payload.userId, payload.roleInGroup)}


@router.delete("/admin/groups/{group_id}/members/{user_id}")
def remove_group_member(group_id: str, user_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().remove_group_member(user, group_id, user_id)}


@router.get("/admin/permissions/users/{user_id}")
def permissions_for_user(user_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    service = _service()
    service.get_user(user, user_id)
    return {"ok": True, "permissions": service.persistence.access.list_permissions_for_user(user_id)}


@router.get("/admin/permissions/resources/{resource_type}/{resource_id}")
def permissions_for_resource(resource_type: str, resource_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    service = _service()
    service.sharing.assert_can_manage(user, resource_type, resource_id)
    return {"ok": True, "permissions": service.persistence.access.list_permissions_for_resource(resource_type, resource_id)}


@router.post("/admin/permissions/grant")
def grant_permission(payload: PermissionGrantRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "permission": _service().grant_permission(user, payload.dict())}


@router.post("/admin/permissions/revoke")
def revoke_permission(payload: PermissionRevokeRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_service().revoke_permission(user, payload.dict())}


@router.get("/admin/access-requests")
def access_requests(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    service = _service()
    service.summary(user)
    return {"ok": True, "requests": service.persistence.access.list_access_requests()}


@router.post("/admin/access-requests/{request_id}/approve")
def approve_access_request(request_id: str, payload: AccessRequestResolution, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "request": _service().sharing.resolve_access_request(user, request_id, True, payload.reviewNotes)}


@router.post("/admin/access-requests/{request_id}/deny")
def deny_access_request(request_id: str, payload: AccessRequestResolution, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "request": _service().sharing.resolve_access_request(user, request_id, False, payload.reviewNotes)}


@router.get("/admin/summary")
def admin_summary(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "summary": _service().summary(user)}


@router.get("/admin/access-policies")
def admin_access_policies(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    service = _service()
    service.summary(user)
    return {
        "ok": True,
        "roles": PLATFORM_ROLES,
        "roleDefinitions": ROLE_DEFINITIONS,
        "permissionLevels": PERMISSION_LEVELS,
        "resourceTypes": RESOURCE_TYPES,
    }


@router.get("/admin/audit-log")
def admin_audit_log(
    userId: str | None = None,
    actionType: str | None = None,
    resourceType: str | None = None,
    resourceId: str | None = None,
    projectId: str | None = None,
    dateFrom: str | None = None,
    dateTo: str | None = None,
    text: str | None = None,
    sharingOnly: bool = False,
    adminOnly: bool = False,
    limit: int = 1000,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    filters = AuditSearchQuery(userId=userId, actionType=actionType, resourceType=resourceType, resourceId=resourceId, projectId=projectId, dateFrom=dateFrom, dateTo=dateTo, text=text, sharingOnly=sharingOnly, adminOnly=adminOnly, limit=limit)
    return {"ok": True, "events": _service().audit_log(user, filters.dict())}


@router.get("/admin/audit-log/export.csv")
def admin_audit_log_csv(
    userId: str | None = None,
    actionType: str | None = None,
    resourceType: str | None = None,
    resourceId: str | None = None,
    projectId: str | None = None,
    dateFrom: str | None = None,
    dateTo: str | None = None,
    text: str | None = None,
    sharingOnly: bool = False,
    adminOnly: bool = False,
    limit: int = 1000,
    user: Dict[str, Any] = Depends(require_user),
) -> Response:
    filters = AuditSearchQuery(userId=userId, actionType=actionType, resourceType=resourceType, resourceId=resourceId, projectId=projectId, dateFrom=dateFrom, dateTo=dateTo, text=text, sharingOnly=sharingOnly, adminOnly=adminOnly, limit=limit)
    return Response(_service().audit_csv(user, filters.dict()), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=atlas-audit-log.csv"})


@router.get("/admin/audit-log/export.json")
def admin_audit_log_json(
    userId: str | None = None,
    actionType: str | None = None,
    resourceType: str | None = None,
    resourceId: str | None = None,
    projectId: str | None = None,
    dateFrom: str | None = None,
    dateTo: str | None = None,
    text: str | None = None,
    sharingOnly: bool = False,
    adminOnly: bool = False,
    limit: int = 5000,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    filters = AuditSearchQuery(userId=userId, actionType=actionType, resourceType=resourceType, resourceId=resourceId, projectId=projectId, dateFrom=dateFrom, dateTo=dateTo, text=text, sharingOnly=sharingOnly, adminOnly=adminOnly, limit=limit)
    return {"ok": True, "events": _service().audit_log(user, filters.dict())}


@router.get("/admin/ownership-transfers")
def list_ownership_transfers(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "transfers": _service().list_ownership_transfers(user)}


@router.post("/admin/ownership-transfers")
def create_ownership_transfer(payload: OwnershipTransferRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "transfer": _service().request_ownership_transfer(user, payload.dict())}


@router.post("/admin/ownership-transfers/{transfer_id}/complete")
def complete_ownership_transfer(transfer_id: str, _payload: OwnershipTransferResolution, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "transfer": _service().complete_ownership_transfer(user, transfer_id)}


@router.post("/admin/ownership-transfers/{transfer_id}/reject")
def reject_ownership_transfer(transfer_id: str, payload: OwnershipTransferResolution, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "transfer": _service().reject_ownership_transfer(user, transfer_id, payload.notes)}


@router.get("/admin/access-reviews")
def list_access_reviews(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "reviews": _service().list_access_reviews(user)}


@router.post("/admin/access-reviews")
def create_access_review(payload: AccessReviewCreate, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "review": _service().create_access_review(user, payload.dict())}


@router.post("/admin/access-reviews/{review_id}/complete")
def complete_access_review(review_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "review": _service().complete_access_review(user, review_id)}


@router.post("/admin/access-review-items/{review_item_id}/decision")
def decide_access_review_item(review_item_id: str, payload: AccessReviewItemDecision, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "item": _service().decide_access_review_item(user, review_item_id, payload.decision, payload.reviewerNotes)}


@router.post("/admin/bulk-access/preview")
def bulk_access_preview(payload: BulkPermissionPreviewRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "preview": _service().bulk_permission_preview(user, payload.dict())}


@router.post("/admin/bulk-access/apply")
def bulk_access_apply(payload: BulkPermissionApplyRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "result": _service().bulk_permission_apply(user, payload.dict())}

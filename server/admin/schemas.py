from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel


class AdminUserCreate(BaseModel):
    displayName: str
    email: str
    role: str = "data_scientist"
    status: str = "active"
    password: Optional[str] = None


class AdminUserUpdate(BaseModel):
    displayName: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None


class RoleUpdate(BaseModel):
    role: str


class StatusUpdate(BaseModel):
    status: str


class GroupCreate(BaseModel):
    groupName: str
    description: Optional[str] = None
    status: str = "active"
    metadata: Dict[str, Any] = {}


class GroupUpdate(BaseModel):
    groupName: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    metadata: Dict[str, Any] = {}


class GroupMemberRequest(BaseModel):
    userId: str
    roleInGroup: Optional[str] = None


class PermissionGrantRequest(BaseModel):
    resourceType: str
    resourceId: str
    principalType: str
    principalId: str
    permissionLevel: str
    expiresAt: Optional[str] = None
    metadata: Dict[str, Any] = {}


class PermissionRevokeRequest(BaseModel):
    resourceType: str
    resourceId: str
    principalType: str
    principalId: str


class AccessRequestResolution(BaseModel):
    reviewNotes: Optional[str] = None


class AuditSearchQuery(BaseModel):
    userId: Optional[str] = None
    actionType: Optional[str] = None
    resourceType: Optional[str] = None
    resourceId: Optional[str] = None
    projectId: Optional[str] = None
    dateFrom: Optional[str] = None
    dateTo: Optional[str] = None
    text: Optional[str] = None
    sharingOnly: bool = False
    adminOnly: bool = False
    limit: int = 1000


class OwnershipTransferRequest(BaseModel):
    resourceType: str
    resourceId: str
    toUserId: str
    reason: Optional[str] = None


class OwnershipTransferResolution(BaseModel):
    notes: Optional[str] = None


class AccessReviewCreate(BaseModel):
    reviewName: str
    scope: str = "resource"
    resourceType: Optional[str] = None
    resourceId: Optional[str] = None
    ownerUserId: Optional[str] = None
    dueDate: Optional[str] = None


class AccessReviewItemDecision(BaseModel):
    decision: str
    reviewerNotes: Optional[str] = None


class BulkPermissionPreviewRequest(BaseModel):
    groupId: str
    resourceType: str
    resourceFilter: str = "all"
    workflowType: Optional[str] = None
    ownerUserId: Optional[str] = None
    lifecycleStatus: Optional[str] = None
    permissionLevel: str = "view"
    expiresAt: Optional[str] = None


class BulkPermissionApplyRequest(BulkPermissionPreviewRequest):
    resourceIds: list[str] = []

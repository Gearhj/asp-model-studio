from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .security_store import (
    AUDIT_ROLES,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    audit_events_for_resource,
    authenticate,
    change_password,
    create_user,
    get_user,
    grant_project_access,
    list_audit_events,
    list_project_access,
    list_users,
    public_user,
    public_registration_enabled,
    require_role,
    require_user,
    revoke_project_access,
    revoke_session,
    security_diagnostics,
    secure_cookie_enabled,
    set_user_role,
    set_user_status,
    unlock_user,
    update_user,
)


router = APIRouter()


class RegisterRequest(BaseModel):
    email: str
    displayName: str
    password: str
    # Deprecated compatibility input. It is deliberately ignored and can
    # never influence the effective role.
    role: Any = None


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str


class CreateUserRequest(BaseModel):
    email: str
    displayName: str
    password: str
    role: str = "data_scientist"


class UpdateUserRequest(BaseModel):
    displayName: Optional[str] = None
    status: Optional[str] = None

    class Config:
        extra = "forbid"


class RoleRequest(BaseModel):
    role: str


class ProjectGrantRequest(BaseModel):
    userId: str
    permission: str = "viewer"


def set_session_cookie(response: Response, session_id: str, expires_at: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_id,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=secure_cookie_enabled(),
        samesite="lax",
    )


@router.post("/auth/register")
def register(payload: RegisterRequest, response: Response, request: Request) -> Dict[str, Any]:
    if not public_registration_enabled():
        raise HTTPException(status_code=403, detail="Public registration is not enabled.")
    user = create_user(
        email=payload.email,
        display_name=payload.displayName,
        password=payload.password,
        role="data_scientist",
    )
    login = authenticate(payload.email, payload.password, request)
    set_session_cookie(response, login["sessionId"], login["expiresAt"])
    return {"ok": True, "user": user, "sessionExpiresAt": login["expiresAt"]}


@router.post("/auth/login")
def login(payload: LoginRequest, response: Response, request: Request) -> Dict[str, Any]:
    result = authenticate(payload.email, payload.password, request)
    set_session_cookie(response, result["sessionId"], result["expiresAt"])
    return {"ok": True, "user": result["user"], "sessionExpiresAt": result["expiresAt"]}


@router.post("/auth/logout")
def logout(response: Response, request: Request, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    revoke_session(request.cookies.get(SESSION_COOKIE_NAME), user.get("userId"))
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@router.get("/auth/me")
def me(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "user": user}


@router.post("/auth/change-password")
def post_change_password(payload: ChangePasswordRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    change_password(user["userId"], payload.currentPassword, payload.newPassword)
    return {"ok": True}


@router.post("/auth/request-password-reset")
def request_password_reset() -> Dict[str, Any]:
    return {"ok": True, "message": "Password reset is a local stub in this ATLAS build."}


@router.post("/auth/reset-password")
def reset_password() -> Dict[str, Any]:
    return {"ok": True, "message": "Password reset is a local stub in this ATLAS build."}


@router.get("/admin/users")
def admin_users(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    require_role(user, {"admin"})
    users = list_users()
    try:
        from ..persistence.service import get_persistence_service

        service = get_persistence_service()
        enriched = []
        for item in users:
            persisted = service.sync_user(item) or {}
            enriched.append(
                {
                    **item,
                    "lastActiveAt": persisted.get("last_active_at") or item.get("lastLoginAt"),
                    **service.users.activity_summary(item["userId"]),
                }
            )
        users = enriched
    except Exception:
        pass
    return {"ok": True, "users": users}


@router.get("/admin/users/{user_id}")
def admin_user(user_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    require_role(user, {"admin"})
    found = get_user(user_id)
    if not found:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"ok": True, "user": public_user(found)}


@router.post("/admin/users")
def admin_create_user(payload: CreateUserRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    require_role(user, {"admin"})
    created = create_user(
        email=payload.email,
        display_name=payload.displayName,
        password=payload.password,
        role=payload.role,
        actor_user_id=user["userId"],
    )
    return {"ok": True, "user": created}


@router.patch("/admin/users/{user_id}")
def admin_update_user(user_id: str, payload: UpdateUserRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    require_role(user, {"admin"})
    return {
        "ok": True,
        "user": update_user(
            user_id,
            {key: value for key, value in payload.dict().items() if value is not None},
            actor_user_id=user["userId"],
        ),
    }


@router.post("/admin/users/{user_id}/disable")
def admin_disable_user(user_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    require_role(user, {"admin"})
    result = set_user_status(user_id, "inactive", actor_user_id=user["userId"])
    return {"ok": True, "user": {key: value for key, value in result.items() if key != "auditAction"}}


@router.post("/admin/users/{user_id}/enable")
def admin_enable_user(user_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    require_role(user, {"admin"})
    result = set_user_status(user_id, "active", actor_user_id=user["userId"])
    return {"ok": True, "user": {key: value for key, value in result.items() if key != "auditAction"}}


@router.post("/admin/users/{user_id}/unlock")
def admin_unlock_user(user_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    require_role(user, {"admin"})
    return {"ok": True, "user": unlock_user(user_id)}


@router.post("/admin/users/{user_id}/role")
def admin_role_user(user_id: str, payload: RoleRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    if user.get("role") != "admin":
        from .security_store import audit_event

        audit_event(
            "user.role.changed",
            "user",
            user_id,
            "denied",
            reason="Administrator role required",
            metadata={"requestedRole": payload.role},
            user_id=user.get("userId"),
        )
        raise HTTPException(status_code=403, detail="Insufficient permissions.")
    try:
        changed = set_user_role(user_id, payload.role, actor_user_id=user["userId"])
    except HTTPException as exc:
        from .security_store import audit_event

        audit_event(
            "user.role.changed",
            "user",
            user_id,
            "denied",
            reason="Role change rejected",
            metadata={"requestedRole": payload.role},
            user_id=user["userId"],
        )
        raise exc
    return {
        "ok": True,
        "user": changed,
        "audit": {
            "actorUserId": user["userId"],
            "selectedRole": payload.role,
            "impact": "The user's effective permissions change immediately; existing sessions are revoked.",
            "recorded": True,
        },
    }


@router.get("/projects/{project_id}/access")
def get_project_access(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "access": list_project_access(project_id, user)}


@router.post("/projects/{project_id}/access/grant")
def grant_project(project_id: str, payload: ProjectGrantRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    # The authenticated actor and canonical owner-of-record check are enforced
    # inside the service; request-body identity names only the target grantee.
    return {"ok": True, "grant": grant_project_access(project_id, payload.userId, payload.permission, user)}


@router.post("/projects/{project_id}/access/revoke")
def revoke_project(project_id: str, payload: ProjectGrantRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return revoke_project_access(project_id, payload.userId, user)


@router.get("/audit/events")
def audit_events(
    userId: Optional[str] = None,
    resourceType: Optional[str] = None,
    outcome: Optional[str] = None,
    action: Optional[str] = None,
    projectId: Optional[str] = None,
    limit: int = 250,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    require_role(user, AUDIT_ROLES)
    return {"ok": True, "events": list_audit_events(limit=limit, user_id=userId, resource_type=resourceType, outcome=outcome, action=action, project_id=projectId)}


@router.get("/audit/events/resource/{resource_type}/{resource_id}")
def audit_resource(resource_type: str, resource_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    require_role(user, AUDIT_ROLES)
    return {"ok": True, "events": audit_events_for_resource(resource_type, resource_id)}


@router.get("/security/diagnostics")
def get_security_diagnostics(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    require_role(user, {"admin", "auditor", "model_manager"})
    return security_diagnostics()

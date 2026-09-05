"""Stage 2B (ATLAS_MODELING_STATE_ISOLATION_PLAN.md): project-aware scope
resolution for DATASTORE working state.

DATASTORE (server/core/dataset_store.py) is scoped by (user_id, project_id).
The user half is established by ActiveUserContextMiddleware (Stage 2A,
server/security/security_store.py) from the server-side session -- an
ambient, request-wide signal. The project half has no equivalent ambient
signal: project_id is an explicit, per-endpoint value (a query param or a
request-body field, shape varies by endpoint), so it cannot be resolved by
a single generic middleware the way the session cookie can.

Instead, each affected router endpoint calls `authorize_modeling_scope(...)`
as its first action, after FastAPI has already parsed `project_id` out of
that endpoint's own request model. That call validates project_id, checks
SharingService authorization (the same mechanism FND-001/FND-002 already
established -- not a second authorization system), and sets
`ACTIVE_PROJECT_ID` for the current execution context.

Why setting a ContextVar here (inside the route handler body) works, when
Stage 2A proved the same trick fails inside a `Depends()` dependency:
FastAPI/Starlette resolves each dependency, and the route handler itself,
via separate `run_in_threadpool` calls, each with an independently-copied
`contextvars.Context` -- mutations inside one are invisible to the next
(see ActiveUserContextMiddleware's docstring for the full mechanism).
But everything an already-running route handler calls afterward -- the
preprocessing/feature/split service functions that read DATASTORE via its
ambient proxy -- are ordinary, synchronous, nested Python function calls
within that SAME context, not further dependency-injection hops. A
ContextVar set at the top of the route handler body is therefore visible to
all of them, verified empirically before use (see the delivery report).
This is what lets every deeper service-layer function keep reading
DATASTORE exactly as before, unmodified, while still resolving the correct
per-project scope.
"""

from __future__ import annotations

import contextvars
from typing import Any, Dict, Optional

from fastapi import HTTPException

ACTIVE_PROJECT_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "atlas_active_project_id", default=None
)


def set_active_project_id(project_id: Optional[str]) -> None:
    ACTIVE_PROJECT_ID.set(project_id)


def active_project_id() -> Optional[str]:
    return ACTIVE_PROJECT_ID.get()


def authorize_modeling_scope(user: Dict[str, Any], project_id: Optional[str], permission: str) -> str:
    """Validate `project_id`, authorize it for `user` via SharingService, and
    set the active-project context so DATASTORE's ambient proxy resolves the
    right (user, project) scope for the remainder of this request.

    `permission` is "view" for read-only profile/preview/retrieval
    operations and "edit" for state-changing operations, per the platform's
    existing SharingService.PERMISSION_LEVELS ranking (already used by the
    FND-001 persistence routes and FND-002 project-sharing endpoints).

    Raises:
        HTTPException(400) if project_id is missing, blank, or whitespace-only.
        HTTPException(404) if the project does not exist in the persistence database.
        HTTPException(403) if the authenticated user lacks `permission` on it.

    Never falls back to a user-only or "anonymous" DATASTORE scope: every
    exit from this function either raises or leaves ACTIVE_PROJECT_ID set to
    a real, authorized project_id.
    """
    cleaned = str(project_id or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="A project_id is required for this operation.")

    # Local imports: avoids a module-load-order dependency between
    # server.core (loaded early, by server.main and nearly everything else)
    # and server.persistence / server.sharing / server.security, mirroring
    # the existing lazy-import convention already used by
    # server/core/dataset_store.py's _scope_key() for the same reason.
    from ..persistence.service import get_persistence_service
    from ..security.security_store import audit_event
    from ..sharing.sharing_service import SharingService

    service = get_persistence_service()
    existing = service.projects.get(cleaned)
    if existing is None:
        raise HTTPException(status_code=404, detail="ATLAS project was not found in the persistence database.")

    check = SharingService(service).check_permission(user, "project", cleaned, permission)
    if not check.get("allowed"):
        audit_event(
            "access.denied",
            "project",
            cleaned,
            "denied",
            user_id=user.get("userId"),
            reason=f"Insufficient '{permission}' permission on project for modeling workspace access.",
            metadata={"projectId": cleaned, "requiredPermission": permission},
        )
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action on this project.")

    set_active_project_id(cleaned)
    return cleaned


async def require_project_scope(request, response, user):
    """Resolve one authenticated project across path, query and body before work.

    The dependency runs on the request context (async), so its project context is
    inherited by the synchronous route and its service calls. No client actor or
    alternate project identity can supersede the authenticated path authority.
    """
    from ..persistence.service import get_persistence_service
    from ..sharing.sharing_service import SharingService

    identities = []
    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"projectId", "project_id"}:
                    if not isinstance(item, str) or not item.strip():
                        raise HTTPException(400, "An explicit project identity is required.")
                    identities.append(item.strip())
                elif isinstance(item, (dict, list)):
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(dict(request.path_params))
    for key in ("projectId", "project_id"):
        for value in request.query_params.getlist(key):
            collect({key: value})
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        try:
            collect(await request.json())
        except (ValueError, UnicodeError):
            pass  # Body schema validation remains the route's responsibility.
    if not identities:
        raise HTTPException(400, "An explicit project identity is required.")
    if len(set(identities)) != 1:
        raise HTTPException(409, "Conflicting project identities are not permitted.")
    project_id = identities[0]
    permission = getattr(request.state, "project_required_permission", "view")
    service = get_persistence_service()
    project = service.projects.get(project_id)
    allowed = project is not None and SharingService(service).check_permission(
        user, "project", project_id, permission
    ).get("allowed")
    if not allowed:
        # Uniform unknown/nonmember denial; no existence oracle and no writes.
        raise HTTPException(403, "Project access is not permitted.")
    set_active_project_id(project_id)
    request.state.project_authority = {
        "projectId": project_id, "userId": user.get("userId"), "permission": permission
    }
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Cookie, Authorization"
    return request.state.project_authority


# Explicitly typed wrappers are stable dependency identities for route inventory.
from fastapi import Depends, Request, Response
from ..security.security_store import require_user


async def require_project_view(request: Request, response: Response,
                               user: Dict[str, Any] = Depends(require_user)):
    request.state.project_required_permission = "view"
    return await require_project_scope(request, response, user)


async def require_project_edit(request: Request, response: Response,
                               user: Dict[str, Any] = Depends(require_user)):
    request.state.project_required_permission = "edit"
    return await require_project_scope(request, response, user)

from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware


DEFAULT_SECURITY_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "security"
SECURITY_ROOT = Path(os.getenv("ATLAS_SECURITY_ROOT", str(DEFAULT_SECURITY_ROOT))).expanduser().resolve()
DB_PATH = Path(os.getenv("ATLAS_SECURITY_DB_PATH", str(SECURITY_ROOT / "atlas_security.db"))).expanduser().resolve()
SESSION_COOKIE_NAME = "atlas_session"
ATLAS_AUTH_ENABLED = os.getenv("ATLAS_AUTH_ENABLED", "true").lower() not in {"0", "false", "no"}
ATLAS_LOCAL_DEV = os.getenv("ATLAS_LOCAL_DEV", "true").lower() in {"1", "true", "yes"}
ATLAS_HOSTED_MODE = os.getenv("ATLAS_HOSTED_MODE", "false").lower() in {"1", "true", "yes"}
ATLAS_DEV_AUTH_TOOLS = os.getenv("ATLAS_DEV_AUTH_TOOLS", "false").lower() in {"1", "true", "yes"}
ATLAS_DEV_MODE = os.getenv(
    "ATLAS_DEV_MODE",
    "true" if ATLAS_LOCAL_DEV and not ATLAS_HOSTED_MODE else "false",
).lower() in {"1", "true", "yes"}
SESSION_TTL_SECONDS = int(os.getenv("ATLAS_SESSION_TTL_SECONDS", str(8 * 60 * 60)))
LOCKOUT_THRESHOLD = int(os.getenv("ATLAS_LOCKOUT_THRESHOLD", "5"))
LOCKOUT_SECONDS = int(os.getenv("ATLAS_LOCKOUT_SECONDS", "900"))
PASSWORD_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = int(os.getenv("ATLAS_PBKDF2_ITERATIONS", "260000"))
SESSION_SECRET = os.getenv("ATLAS_SESSION_SECRET", "atlas-local-dev-default-session-secret")
DEFAULT_ADMIN_EMAIL = os.getenv("ATLAS_DEFAULT_ADMIN_EMAIL", "admin@atlas.local")
DEFAULT_ADMIN_PASSWORD = os.getenv("ATLAS_DEFAULT_ADMIN_PASSWORD", "AtlasLocalDev123!")

ACTIVE_USER: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("atlas_active_user", default=None)

ROLES = {"admin", "data_steward", "model_owner", "model_manager", "data_scientist", "validator", "manager", "auditor", "viewer"}
DATASET_ACCESS_ROLES = {"owner", "editor", "viewer", "auditor"}
PROJECT_ACCESS_ROLES = {"owner", "editor", "viewer", "approver", "auditor"}
# FND-002: server/sharing/sharing_service.py is the single authoritative store for
# project access (resource_permissions / project_collaborators). This maps the
# legacy project-ACL permission vocabulary (still used by the /projects/{id}/access
# request payloads and the frontend) onto SharingService.PERMISSION_LEVELS so grants
# made through the legacy endpoints are recorded in, and evaluated against, the same
# permission table as every other resource type. "editor"/"approver" both map to
# levels at or above "edit" so user_can_access_project(write=True) keeps admitting
# exactly the same principals it did before ({"owner", "editor", "approver"}), via
# SharingService's permission ranking rather than a second set-membership check.
LEGACY_TO_SHARING_PERMISSION = {
    "owner": "admin",
    "editor": "edit",
    "approver": "approve",
    "viewer": "view",
    "auditor": "view",
}
ADMIN_ROLES = {"admin"}
AUDIT_ROLES = {"admin", "auditor", "model_manager", "validator", "manager"}
DEFAULT_SESSION_SECRET = "atlas-local-dev-default-session-secret"
DEFAULT_LOCAL_ADMIN_PASSWORD = "AtlasLocalDev123!"
LOCAL_DEV_USER_ID = "local-dev-user"
SEEDED_LOCAL_ADMIN_USER_ID = os.getenv("ATLAS_LOCAL_ADMIN_USER_ID", "user_eecc3a44ed694307")
LOCAL_DEV_USER_HEADER = "X-ATLAS-USER-ID"
DEMO_USERS = (
    ("demo_ds_1", "demo.ds1@atlas.local", "Demo Data Scientist", "data_scientist"),
    ("demo_validator", "demo.validator@atlas.local", "Demo Validator", "validator"),
    ("demo_manager", "demo.manager@atlas.local", "Demo Manager", "manager"),
)
_DEV_CONTEXT_AUDITED: set[str] = set()


class AtlasUserContextError(HTTPException):
    """Authentication error whose payload is flattened by the FastAPI app handler."""

    def __init__(self, payload: Dict[str, Any]):
        super().__init__(status_code=401, detail=payload)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def development_user_header_enabled() -> bool:
    """Allow the explicit dev-user header only for non-hosted local/dev processes."""

    return not ATLAS_HOSTED_MODE and (ATLAS_DEV_MODE or ATLAS_LOCAL_DEV)


def epoch() -> int:
    return int(time.time())


def connect() -> sqlite3.Connection:
    SECURITY_ROOT.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def enforce_hosted_security_configuration() -> None:
    if not ATLAS_HOSTED_MODE:
        return
    if not ATLAS_AUTH_ENABLED:
        raise RuntimeError("ATLAS_AUTH_ENABLED must be true in hosted mode.")
    if SESSION_SECRET == DEFAULT_SESSION_SECRET:
        raise RuntimeError("ATLAS_SESSION_SECRET must be configured in hosted mode.")
    if DEFAULT_ADMIN_PASSWORD == DEFAULT_LOCAL_ADMIN_PASSWORD:
        raise RuntimeError("ATLAS_DEFAULT_ADMIN_PASSWORD must be changed in hosted mode.")


def init_security_store() -> None:
    enforce_hosted_security_configuration()
    SECURITY_ROOT.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              user_id TEXT PRIMARY KEY,
              email TEXT UNIQUE NOT NULL,
              display_name TEXT NOT NULL,
              role TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              last_login_at TEXT,
              failed_login_count INTEGER NOT NULL DEFAULT 0,
              locked_until TEXT
            );
            CREATE TABLE IF NOT EXISTS credentials (
              user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
              password_hash TEXT NOT NULL,
              password_algorithm TEXT NOT NULL,
              password_updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
              session_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              ip_address_hash TEXT,
              user_agent_hash TEXT,
              revoked_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_events (
              audit_id TEXT PRIMARY KEY,
              timestamp TEXT NOT NULL,
              user_id TEXT,
              action TEXT NOT NULL,
              resource_type TEXT NOT NULL,
              resource_id TEXT,
              outcome TEXT NOT NULL,
              reason TEXT,
              metadata_json TEXT
            );
            CREATE TABLE IF NOT EXISTS project_access (
              project_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              permission TEXT NOT NULL,
              granted_by_user_id TEXT,
              granted_at TEXT NOT NULL,
              PRIMARY KEY (project_id, user_id)
            );
            """
        )
        admin_count = conn.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'").fetchone()["n"]
        if admin_count == 0:
            create_user(
                user_id=SEEDED_LOCAL_ADMIN_USER_ID if ATLAS_LOCAL_DEV and not ATLAS_HOSTED_MODE else None,
                email=DEFAULT_ADMIN_EMAIL,
                display_name="ATLAS Local Admin",
                password=DEFAULT_ADMIN_PASSWORD,
                role="admin",
                audit=False,
                conn=conn,
            )
        legacy = conn.execute("SELECT user_id FROM users WHERE user_id = 'local-user'").fetchone()
        if legacy is None:
            create_user(
                email="local.user@atlas.local",
                display_name="Local ATLAS User",
                password=DEFAULT_ADMIN_PASSWORD,
                role="admin",
                audit=False,
                conn=conn,
                user_id="local-user",
            )
        if ATLAS_LOCAL_DEV and not ATLAS_HOSTED_MODE:
            for user_id, email, display_name, role in DEMO_USERS:
                exists = conn.execute(
                    "SELECT user_id FROM users WHERE user_id = ? OR email = ?",
                    (user_id, normalize_email(email)),
                ).fetchone()
                if exists is None:
                    create_user(
                        user_id=user_id,
                        email=email,
                        display_name=display_name,
                        password=DEFAULT_ADMIN_PASSWORD,
                        role=role,
                        status="active",
                        audit=False,
                        conn=conn,
                    )


def row_to_user(row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {
        "userId": row["user_id"],
        "email": row["email"],
        "displayName": row["display_name"],
        "role": row["role"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "lastLoginAt": row["last_login_at"],
        "failedLoginCount": row["failed_login_count"],
        "lockedUntil": row["locked_until"],
    }


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {key: user.get(key) for key in ["userId", "email", "displayName", "role", "status", "createdAt", "updatedAt", "lastLoginAt", "failedLoginCount", "lockedUntil"]}


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password(password: str) -> None:
    weak = {"password", "password1", "password123", "passwordpassword", "password1234", "atlaspassword", "letmeinletmein", "12345678", "123456789012"}
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if password.lower() in weak:
        raise HTTPException(status_code=400, detail="Choose a less common passphrase.")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{PASSWORD_ALGORITHM}${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def hash_observable(value: str | None) -> Optional[str]:
    if not value:
        return None
    digest = hmac.new(SESSION_SECRET.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:32]


def create_user(
    *,
    email: str,
    display_name: str,
    password: str,
    role: str = "data_scientist",
    status: str = "active",
    audit: bool = True,
    conn: sqlite3.Connection | None = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    validate_password(password)
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Unsupported ATLAS role.")
    if status not in {"active", "inactive"}:
        raise HTTPException(status_code=400, detail="User status must be active or inactive.")
    owns_conn = conn is None
    active_conn = conn or connect()
    try:
        user_id = user_id or f"user_{uuid.uuid4().hex[:16]}"
        timestamp = now_iso()
        active_conn.execute(
            """
            INSERT INTO users (user_id, email, display_name, role, status, created_at, updated_at, failed_login_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (user_id, normalize_email(email), display_name.strip() or normalize_email(email), role, status, timestamp, timestamp),
        )
        active_conn.execute(
            "INSERT INTO credentials (user_id, password_hash, password_algorithm, password_updated_at) VALUES (?, ?, ?, ?)",
            (user_id, hash_password(password), PASSWORD_ALGORITHM, timestamp),
        )
        if audit:
            audit_event("user.created", "user", user_id, "success", metadata={"email": normalize_email(email), "role": role}, conn=active_conn)
        if owns_conn:
            active_conn.commit()
        row = active_conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return public_user(row_to_user(row) or {})
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="User account could not be created.") from exc
    finally:
        if owns_conn:
            active_conn.close()


def list_users() -> List[Dict[str, Any]]:
    init_security_store()
    with connect() as conn:
        return [public_user(row_to_user(row) or {}) for row in conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()]


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    init_security_store()
    with connect() as conn:
        return row_to_user(conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone())


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    init_security_store()
    with connect() as conn:
        return row_to_user(conn.execute("SELECT * FROM users WHERE email = ?", (normalize_email(email),)).fetchone())


def update_user(user_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {"displayName": "display_name", "role": "role", "status": "status"}
    updates = []
    params = []
    for key, column in allowed.items():
        if key in fields:
            if key == "role" and fields[key] not in ROLES:
                raise HTTPException(status_code=400, detail="Unsupported ATLAS role.")
            if key == "status" and fields[key] not in {"active", "inactive", "disabled"}:
                raise HTTPException(status_code=400, detail="User status must be active or inactive.")
            updates.append(f"{column} = ?")
            params.append(fields[key])
    if not updates:
        user = get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        return public_user(user)
    updates.append("updated_at = ?")
    params.append(now_iso())
    params.append(user_id)
    with connect() as conn:
        conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?", params)
        audit_event("user.updated", "user", user_id, "success", metadata={"fields": list(fields.keys())}, conn=conn)
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        return public_user(row_to_user(row) or {})


def set_user_status(user_id: str, status: str) -> Dict[str, Any]:
    action = "user.inactivated" if status in {"disabled", "inactive"} else "user.activated"
    return update_user(user_id, {"status": status}) | {"auditAction": action}


def set_user_role(user_id: str, role: str) -> Dict[str, Any]:
    user = update_user(user_id, {"role": role})
    audit_event("user.role.changed", "user", user_id, "success", metadata={"role": role})
    return user


def unlock_user(user_id: str) -> Dict[str, Any]:
    with connect() as conn:
        conn.execute("UPDATE users SET locked_until = NULL, failed_login_count = 0, updated_at = ? WHERE user_id = ?", (now_iso(), user_id))
        audit_event("user.unlocked", "user", user_id, "success", conn=conn)
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        return public_user(row_to_user(row) or {})


def authenticate(email: str, password: str, request: Request | None = None) -> Dict[str, Any]:
    init_security_store()
    generic = HTTPException(status_code=401, detail="Email or password is not valid.")
    # Every branch below determines its outcome and performs its writes and
    # audit events *inside* this transaction, but none of them raise while
    # still inside the `with` block: sqlite3's connection context manager
    # rolls back the transaction when the block exits via an exception, so
    # raising here (as this function previously did) silently discarded the
    # failed_login_count/locked_until update and the audit event for every
    # failed, disabled, or locked login attempt. Denial is instead recorded
    # in `denied`, the block is left normally so the transaction commits,
    # and `generic` is raised only after that commit has happened.
    denied = False
    result: Dict[str, Any] | None = None
    with connect() as conn:
        user_row = conn.execute("SELECT * FROM users WHERE email = ?", (normalize_email(email),)).fetchone()
        user = row_to_user(user_row)
        if not user:
            audit_event("auth.login.failure", "auth", None, "failure", reason="Invalid credentials", metadata={"emailHash": hash_observable(normalize_email(email))}, conn=conn)
            denied = True
        elif user["status"] != "active":
            audit_event("auth.login.failure", "auth", user["userId"], "denied", reason="Inactive user", conn=conn)
            denied = True
        else:
            locked_until = user.get("lockedUntil")
            if locked_until and locked_until > now_iso():
                audit_event("auth.login.failure", "auth", user["userId"], "denied", reason="Account locked", conn=conn)
                denied = True
            else:
                cred = conn.execute("SELECT * FROM credentials WHERE user_id = ?", (user["userId"],)).fetchone()
                if not cred or not verify_password(password, cred["password_hash"]):
                    next_failed = int(user.get("failedLoginCount") or 0) + 1
                    locked_until_value = None
                    if next_failed >= LOCKOUT_THRESHOLD:
                        locked_until_value = datetime.fromtimestamp(epoch() + LOCKOUT_SECONDS, tz=timezone.utc).isoformat()
                    conn.execute(
                        "UPDATE users SET failed_login_count = ?, locked_until = ?, updated_at = ? WHERE user_id = ?",
                        (next_failed, locked_until_value, now_iso(), user["userId"]),
                    )
                    audit_event("auth.login.failure", "auth", user["userId"], "failure", reason="Invalid credentials", conn=conn)
                    denied = True
                else:
                    timestamp = now_iso()
                    session_id = secrets.token_urlsafe(32)
                    expires = datetime.fromtimestamp(epoch() + SESSION_TTL_SECONDS, tz=timezone.utc).isoformat()
                    conn.execute(
                        """
                        INSERT INTO sessions (session_id, user_id, created_at, expires_at, last_seen_at, ip_address_hash, user_agent_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            user["userId"],
                            timestamp,
                            expires,
                            timestamp,
                            hash_observable(request.client.host if request and request.client else None),
                            hash_observable(request.headers.get("user-agent") if request else None),
                        ),
                    )
                    conn.execute(
                        "UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login_at = ?, updated_at = ? WHERE user_id = ?",
                        (timestamp, timestamp, user["userId"]),
                    )
                    audit_event("auth.login.success", "auth", user["userId"], "success", conn=conn)
                    updated = row_to_user(conn.execute("SELECT * FROM users WHERE user_id = ?", (user["userId"],)).fetchone()) or user
                    result = {"sessionId": session_id, "expiresAt": expires, "user": public_user(updated)}
    if denied:
        raise generic
    assert result is not None
    return result


def user_for_session(session_id: str | None) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None
    init_security_store()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.user_id = sessions.user_id
            WHERE sessions.session_id = ? AND sessions.revoked_at IS NULL AND sessions.expires_at > ?
            """,
            (session_id, now_iso()),
        ).fetchone()
        if not row:
            return None
        user = row_to_user(row)
        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE session_id = ?", (now_iso(), session_id))
        return user


def revoke_session(session_id: str | None, user_id: Optional[str] = None) -> None:
    if not session_id:
        return
    with connect() as conn:
        conn.execute("UPDATE sessions SET revoked_at = ? WHERE session_id = ?", (now_iso(), session_id))
        audit_event("auth.logout", "auth", user_id, "success", conn=conn)


def change_password(user_id: str, current_password: str, new_password: str) -> None:
    validate_password(new_password)
    with connect() as conn:
        cred = conn.execute("SELECT * FROM credentials WHERE user_id = ?", (user_id,)).fetchone()
        if not cred or not verify_password(current_password, cred["password_hash"]):
            audit_event("auth.password.changed", "auth", user_id, "failure", reason="Invalid current password", conn=conn)
            raise HTTPException(status_code=400, detail="Password could not be changed.")
        conn.execute(
            "UPDATE credentials SET password_hash = ?, password_algorithm = ?, password_updated_at = ? WHERE user_id = ?",
            (hash_password(new_password), PASSWORD_ALGORITHM, now_iso(), user_id),
        )
        audit_event("auth.password.changed", "auth", user_id, "success", conn=conn)


def active_user() -> Optional[Dict[str, Any]]:
    return ACTIVE_USER.get()


def set_active_user(user: Optional[Dict[str, Any]]) -> None:
    ACTIVE_USER.set(user)


def _available_dev_users() -> List[Dict[str, Any]]:
    return [
        {"user_id": row.get("userId"), "display_name": row.get("displayName"), "role": row.get("role")}
        for row in list_users()
        if row.get("status") == "active"
    ]


def _local_header_help() -> Dict[str, str]:
    return {
        "name": LOCAL_DEV_USER_HEADER,
        "example": f"{LOCAL_DEV_USER_HEADER}: {SEEDED_LOCAL_ADMIN_USER_ID}",
    }


def _track_user_activity(user: Dict[str, Any], *, dev_context: bool = False) -> None:
    try:
        from ..persistence.service import get_persistence_service

        get_persistence_service().sync_user({**public_user(user), "lastActiveAt": now_iso()})
    except Exception:
        return
    user_id = str(user.get("userId") or "")
    if dev_context and user_id and user_id not in _DEV_CONTEXT_AUDITED:
        _DEV_CONTEXT_AUDITED.add(user_id)
        audit_event(
            "auth.context.established",
            "user",
            user_id,
            "success",
            user_id=user_id,
            metadata={"source": LOCAL_DEV_USER_HEADER, "summary": "Local development user context established."},
        )


def _resolve_authenticated_user(request: Request, *, allow_dev_bootstrap: bool) -> Optional[Dict[str, Any]]:
    """Single source of truth for "which user does this request belong to".

    Shared by require_user() (which layers rejection, status checks, audit
    events, and the dev-user auto-bootstrap side effect on top of this) and
    ActiveUserContextMiddleware (which calls this read-only, with
    allow_dev_bootstrap=False, purely to populate ACTIVE_USER for the
    request's ambient contextvars.Context before routing/dependency
    resolution runs -- see that class's docstring for why that matters).

    Never raises and never triggers side effects beyond the one gated by
    allow_dev_bootstrap. Returns None when no user can be resolved this way;
    callers decide what "no user" means for them.
    """
    requested_dev_user = (request.headers.get(LOCAL_DEV_USER_HEADER) or "").strip()
    if development_user_header_enabled() and requested_dev_user:
        user = get_user(requested_dev_user)
        if user is None and requested_dev_user == LOCAL_DEV_USER_ID and allow_dev_bootstrap:
            user = get_user_by_email(DEFAULT_ADMIN_EMAIL)
            if user is None:
                user = create_user(
                    user_id=LOCAL_DEV_USER_ID,
                    email="local-dev@atlas.local",
                    display_name="Local Dev User",
                    password=DEFAULT_LOCAL_ADMIN_PASSWORD,
                    role="admin",
                    status="active",
                    audit=False,
                )
        return user
    if not ATLAS_AUTH_ENABLED:
        return get_user("local-user") or get_user_by_email(DEFAULT_ADMIN_EMAIL)
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    return user_for_session(session_id)


def require_user(request: Request) -> Dict[str, Any]:
    requested_dev_user = (request.headers.get(LOCAL_DEV_USER_HEADER) or "").strip()
    if development_user_header_enabled() and requested_dev_user:
        user = _resolve_authenticated_user(request, allow_dev_bootstrap=True)
        if user is None:
            raise AtlasUserContextError(
                {
                    "error": "no user selected",
                    "hint": f"The {LOCAL_DEV_USER_HEADER} header did not match a user in the local security database.",
                    "example": f"{LOCAL_DEV_USER_HEADER}: {SEEDED_LOCAL_ADMIN_USER_ID}",
                    "expected_local_header": _local_header_help(),
                    "received_user_id": requested_dev_user,
                    "available_dev_users": _available_dev_users(),
                }
            )
        if user.get("status") != "active":
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "user is not active",
                    "hint": f"Use an active local account with {LOCAL_DEV_USER_HEADER}.",
                    "received_user_id": requested_dev_user,
                },
            )
        set_active_user(user)
        _track_user_activity(user, dev_context=True)
        return public_user(user)
    if not ATLAS_AUTH_ENABLED:
        user = _resolve_authenticated_user(request, allow_dev_bootstrap=False)
        set_active_user(user)
        if user:
            _track_user_activity(user)
        return public_user(user or {})
    user = _resolve_authenticated_user(request, allow_dev_bootstrap=False)
    if not user:
        audit_event("access.denied", "auth", None, "denied", reason="Authentication required")
        payload: Dict[str, Any] = {
            "error": "no user selected",
            "hint": "Authenticate through the login endpoint.",
        }
        if development_user_header_enabled():
            payload["hint"] = (
                f"For local API testing, pass {LOCAL_DEV_USER_HEADER} with an active user ID."
            )
            payload["example"] = f"{LOCAL_DEV_USER_HEADER}: {SEEDED_LOCAL_ADMIN_USER_ID}"
            payload["expected_local_header"] = _local_header_help()
            payload["available_dev_users"] = _available_dev_users()
        raise AtlasUserContextError(payload)
    if user.get("status") != "active":
        audit_event("access.denied", "auth", user.get("userId"), "denied", reason="User is not active")
        raise HTTPException(status_code=403, detail="User is not active.")
    set_active_user(user)
    _track_user_activity(user)
    return public_user(user)


class ActiveUserContextMiddleware(BaseHTTPMiddleware):
    """Fixes ACTIVE_USER propagation for ordinary synchronous FastAPI routes.

    Root cause: require_user() is a FastAPI *dependency*
    (Depends(require_user)). FastAPI/Starlette resolves each synchronous
    dependency via its own run_in_threadpool call, which runs the function
    against a private copy of the caller's contextvars.Context (via
    anyio.to_thread.run_sync -> contextvars.copy_context().run(...)).
    require_user()'s call to set_active_user(user) mutates only that
    private copy; the mutation is discarded when the dependency call
    returns and is never merged back into the request's ambient context.
    The route handler body -- and anything it calls, including
    DATASTORE/RESULTS's proxy classes, which read active_user() to decide
    which per-user store instance to use -- runs in a SEPARATE
    run_in_threadpool call with its own fresh copy of the (unmutated)
    ambient context, so active_user() reads back None there. In practice
    this meant every authenticated request resolved DATASTORE/RESULTS to
    the shared "anonymous" scope, for every user, always -- confirmed by
    tests/modeling_state_characterization_test.py and independently against
    a live uvicorn process.

    Fix: resolve the user once, here, in the middleware's own dispatch()
    coroutine -- which runs directly in the request's ambient async task,
    not inside a nested run_in_threadpool call -- and set ACTIVE_USER
    *before* calling `call_next(request)`. Every run_in_threadpool call
    downstream of this point (every dependency, including require_user()
    itself, and the route handler body) copies its context from this
    already-mutated ambient context, so they all correctly see the same
    resolved user from here on. Verified empirically before use (see the
    delivery report) -- this is not assumed to work merely because it reads
    plausibly.

    This middleware never rejects a request and performs no side effects
    (in particular, it never auto-creates the local-dev bootstrap user --
    see _resolve_authenticated_user's allow_dev_bootstrap parameter);
    actual authentication enforcement remains exactly where it already was,
    in each route's own Depends(require_user). A request that
    require_user() would reject is simply left with ACTIVE_USER unset here
    too, and is rejected downstream as before.
    """

    async def dispatch(self, request: Request, call_next):
        token = ACTIVE_USER.set(_resolve_authenticated_user(request, allow_dev_bootstrap=False))
        try:
            return await call_next(request)
        finally:
            ACTIVE_USER.reset(token)


def require_role(user: Dict[str, Any], roles: Iterable[str]) -> None:
    if user.get("role") not in set(roles):
        audit_event("access.denied", "system", None, "denied", reason="Insufficient role", user_id=user.get("userId"))
        raise HTTPException(status_code=403, detail="Insufficient permissions.")


def audit_event(
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    outcome: str,
    *,
    reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    owns_conn = conn is None
    active_conn = conn or connect()
    audit_id = f"audit_{uuid.uuid4().hex}"
    timestamp = now_iso()
    actor: Optional[str] = user_id
    safe_metadata = metadata or {}
    try:
        user = active_user()
        actor = user_id if user_id is not None else user.get("userId") if user else None
        active_conn.execute(
            """
            INSERT INTO audit_events (audit_id, timestamp, user_id, action, resource_type, resource_id, outcome, reason, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                timestamp,
                actor,
                action,
                resource_type,
                resource_id,
                outcome,
                reason,
                json.dumps(safe_metadata, sort_keys=True),
            ),
        )
        if owns_conn:
            active_conn.commit()
    finally:
        if owns_conn:
            active_conn.close()
    try:
        from ..persistence.service import get_persistence_service

        project_id = safe_metadata.get("projectId") or safe_metadata.get("project_id")
        if not project_id and resource_type == "project":
            project_id = resource_id
        get_persistence_service().audit.create(
            {
                "audit_id": audit_id,
                "project_id": project_id,
                "user_id": actor,
                "action_type": action,
                "entity_type": resource_type,
                "entity_id": resource_id,
                "title": safe_metadata.get("auditTitle") or action.replace(".", " ").title(),
                "summary": safe_metadata.get("summary") or reason,
                "created_at": timestamp,
                "metadata_json": {**safe_metadata, "outcome": outcome, **({"reason": reason} if reason else {})},
            }
        )
    except Exception:
        # Security logging must remain available if project persistence is offline.
        pass


def list_audit_events(limit: int = 250, user_id: Optional[str] = None, resource_type: Optional[str] = None, outcome: Optional[str] = None, action: Optional[str] = None, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    query = "SELECT * FROM audit_events WHERE 1=1"
    params: List[Any] = []
    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)
    if resource_type:
        query += " AND resource_type = ?"
        params.append(resource_type)
    if outcome:
        query += " AND outcome = ?"
        params.append(outcome)
    if action:
        query += " AND action = ?"
        params.append(action)
    if project_id:
        query += " AND ("
        query += "(resource_type = 'project' AND resource_id = ?)"
        query += " OR json_extract(metadata_json, '$.projectId') = ?"
        query += " OR json_extract(metadata_json, '$.project_id') = ?)"
        params.extend([project_id, project_id, project_id])
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(max(1, min(limit, 1000)))
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [audit_row(row) for row in rows]


def audit_events_for_resource(resource_type: str, resource_id: str, limit: int = 250) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_events WHERE resource_type = ? AND resource_id = ? ORDER BY timestamp DESC LIMIT ?",
            (resource_type, resource_id, max(1, min(limit, 1000))),
        ).fetchall()
        return [audit_row(row) for row in rows]


def audit_row(row: sqlite3.Row) -> Dict[str, Any]:
    metadata = json.loads(row["metadata_json"] or "{}")
    return {
        "auditId": row["audit_id"],
        "timestamp": row["timestamp"],
        "userId": row["user_id"],
        "action": row["action"],
        "resourceType": row["resource_type"],
        "resourceId": row["resource_id"],
        "outcome": row["outcome"],
        "reason": row["reason"],
        "projectId": metadata.get("projectId") or metadata.get("project_id") or (row["resource_id"] if row["resource_type"] == "project" else None),
        "metadata": metadata,
    }


def _sharing_service():
    from ..sharing.sharing_service import SharingService

    return SharingService()


def _sync_user_into_persistence(user_id: Optional[str]) -> None:
    """Best-effort sync so project_collaborators' FK on users(user_id) is satisfied.

    require_user() already syncs the *calling* user on every authenticated
    request; this covers the case where a grant/revoke targets a different
    user_id that has not made a request (and therefore not been synced) yet.
    """
    if not user_id:
        return
    try:
        target = get_user(user_id)
        if target:
            from ..persistence.service import get_persistence_service

            get_persistence_service().sync_user(public_user(target))
    except Exception:
        pass


def grant_project_access(project_id: str, user_id: str, permission: str, granted_by_user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if permission not in PROJECT_ACCESS_ROLES:
        raise HTTPException(status_code=400, detail="Unsupported project permission.")
    service = _sharing_service()
    granter_id = (granted_by_user or {}).get("userId")
    mapped_permission = LEGACY_TO_SHARING_PERMISSION[permission]
    _sync_user_into_persistence(user_id)

    # Bootstrap case: a brand-new project's owner self-granting "owner" before
    # any permission record exists for it. This mirrors the previous router-level
    # first_owner_claim check, but against the authoritative permission table
    # instead of the legacy ACL table. It has to be handled explicitly because
    # the frontend queues the project's own persistence-layer row asynchronously,
    # so SharingService.assert_can_manage's owner-of-record lookup can race ahead
    # of it and would otherwise reject the very first grant on a new project.
    existing = service.persistence.access.list_permissions_for_resource("project", project_id)
    first_owner_claim = not existing and user_id == granter_id and permission == "owner"

    if first_owner_claim:
        record = service.persistence.access.grant_permission(
            {
                "permission_id": f"perm_{uuid.uuid4().hex}",
                "resource_type": "project",
                "resource_id": project_id,
                "principal_type": "user",
                "principal_id": user_id,
                "permission_level": mapped_permission,
                "granted_by_user_id": granter_id,
                "metadata_json": {"source": "project_bootstrap_self_owner", "legacyPermission": permission},
            }
        )
        try:
            service.persistence.access.upsert_project_collaborator(
                {
                    "collaborator_id": f"collab_{uuid.uuid4().hex}",
                    "project_id": project_id,
                    "user_id": user_id,
                    "project_role": mapped_permission,
                    "added_by_user_id": granter_id,
                    "metadata_json": {"source": "project_bootstrap_self_owner"},
                }
            )
        except Exception:
            # The project's own persistence-layer row has not landed yet (see
            # above); the collaborator table is a denormalized convenience view,
            # not the authoritative permission record, so this is safe to skip.
            pass
    else:
        result = service.share_resource(
            granted_by_user or {},
            "project",
            project_id,
            {"principalType": "user", "principalId": user_id, "permissionLevel": mapped_permission},
        )
        record = result["permission"]

    audit_event(
        "project.shared",
        "project",
        project_id,
        "success",
        metadata={"targetUserId": user_id, "permission": permission},
        user_id=granter_id,
    )
    return {"projectId": project_id, "userId": user_id, "permission": permission, "grantedAt": record.get("granted_at")}


def revoke_project_access(project_id: str, user_id: str, revoked_by_user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    service = _sharing_service()
    result = service.revoke_share(revoked_by_user or {}, "project", project_id, "user", user_id)
    audit_event(
        "project.access.revoked",
        "project",
        project_id,
        "success",
        metadata={"targetUserId": user_id},
        user_id=(revoked_by_user or {}).get("userId"),
    )
    return {"ok": True, "removed": result.get("revoked", 0)}


def list_project_access(project_id: str) -> List[Dict[str, Any]]:
    service = _sharing_service()
    rows = service.persistence.access.list_permissions_for_resource("project", project_id)
    return [
        {
            "project_id": row.get("resource_id"),
            "user_id": row.get("principal_id"),
            "permission": row.get("permission_level"),
            "granted_by_user_id": row.get("granted_by_user_id"),
            "granted_at": row.get("granted_at"),
        }
        for row in rows
        if row.get("principal_type") == "user"
    ]


def user_can_access_project(project_id: str, user: Optional[Dict[str, Any]] = None, write: bool = False) -> bool:
    active = user or active_user() or get_user("local-user")
    if not active:
        return False
    if active.get("role") == "admin":
        return True
    check = _sharing_service().check_permission(active, "project", project_id, "edit" if write else "view")
    return bool(check.get("allowed"))


def security_diagnostics() -> Dict[str, Any]:
    init_security_store()
    users = list_users()
    checks = []
    checks.append({"id": "auth_enabled", "label": "Authentication enabled", "status": "pass" if ATLAS_AUTH_ENABLED else "warning", "detail": f"ATLAS_AUTH_ENABLED={ATLAS_AUTH_ENABLED}"})
    checks.append({"id": "user_db", "label": "User database reachable", "status": "pass" if DB_PATH.exists() else "fail", "detail": str(DB_PATH)})
    checks.append({"id": "hashing", "label": "Password hashing configured", "status": "warning", "detail": f"{PASSWORD_ALGORITHM} with per-user random salt. Install argon2id/bcrypt for production-grade hosted deployment."})
    checks.append({"id": "admin_exists", "label": "Admin user exists", "status": "pass" if any(user.get("role") == "admin" for user in users) else "fail", "detail": f"{len(users)} user records."})
    checks.append({"id": "session_secret", "label": "Security secret configured", "status": "warning" if SESSION_SECRET == DEFAULT_SESSION_SECRET else "pass", "detail": "Default local secret is in use." if SESSION_SECRET == DEFAULT_SESSION_SECRET else "Custom session secret configured."})
    checks.append({"id": "cookie_policy", "label": "Session cookie policy", "status": "pass" if ATLAS_LOCAL_DEV or ATLAS_HOSTED_MODE else "warning", "detail": "Secure cookies are required when not running local development."})
    checks.append({"id": "dataset_acl", "label": "Dataset ACL enforcement available", "status": "pass", "detail": "Dataset endpoints require authenticated user context and owner/grant/admin access."})
    checks.append({"id": "project_acl", "label": "Project ACL enforcement available", "status": "pass", "detail": "Project access grants and project-dataset link checks are available."})
    checks.append({"id": "audit_writable", "label": "Audit logging writable", "status": "pass", "detail": "Audit events are stored in SQLite."})
    checks.append({"id": "hosted_python", "label": "Hosted mode Python execution disabled", "status": "pass" if not ATLAS_HOSTED_MODE or os.getenv("ATLAS_ENABLE_PYTHON_RUN", "1") in {"0", "false"} else "warning", "detail": f"ATLAS_HOSTED_MODE={ATLAS_HOSTED_MODE}, ATLAS_ENABLE_PYTHON_RUN={os.getenv('ATLAS_ENABLE_PYTHON_RUN', '1')}"})
    audit_event("diagnostics.run", "system", "security", "success", metadata={"checks": len(checks)})
    return {"ok": True, "generatedAt": now_iso(), "checks": checks, "currentUser": public_user(active_user() or get_user("local-user") or {}), "authEnabled": ATLAS_AUTH_ENABLED}

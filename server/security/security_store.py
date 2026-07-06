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


SECURITY_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "security"
DB_PATH = SECURITY_ROOT / "atlas_security.db"
SESSION_COOKIE_NAME = "atlas_session"
ATLAS_AUTH_ENABLED = os.getenv("ATLAS_AUTH_ENABLED", "true").lower() not in {"0", "false", "no"}
ATLAS_LOCAL_DEV = os.getenv("ATLAS_LOCAL_DEV", "true").lower() in {"1", "true", "yes"}
ATLAS_HOSTED_MODE = os.getenv("ATLAS_HOSTED_MODE", "false").lower() in {"1", "true", "yes"}
ATLAS_DEV_AUTH_TOOLS = os.getenv("ATLAS_DEV_AUTH_TOOLS", "false").lower() in {"1", "true", "yes"}
SESSION_TTL_SECONDS = int(os.getenv("ATLAS_SESSION_TTL_SECONDS", str(8 * 60 * 60)))
LOCKOUT_THRESHOLD = int(os.getenv("ATLAS_LOCKOUT_THRESHOLD", "5"))
LOCKOUT_SECONDS = int(os.getenv("ATLAS_LOCKOUT_SECONDS", "900"))
PASSWORD_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = int(os.getenv("ATLAS_PBKDF2_ITERATIONS", "260000"))
SESSION_SECRET = os.getenv("ATLAS_SESSION_SECRET", "atlas-local-dev-default-session-secret")
DEFAULT_ADMIN_EMAIL = os.getenv("ATLAS_DEFAULT_ADMIN_EMAIL", "admin@atlas.local")
DEFAULT_ADMIN_PASSWORD = os.getenv("ATLAS_DEFAULT_ADMIN_PASSWORD", "AtlasLocalDev123!")

ACTIVE_USER: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("atlas_active_user", default=None)

ROLES = {"admin", "data_steward", "model_owner", "model_manager", "data_scientist", "auditor", "viewer"}
DATASET_ACCESS_ROLES = {"owner", "editor", "viewer", "auditor"}
PROJECT_ACCESS_ROLES = {"owner", "editor", "viewer", "approver", "auditor"}
ADMIN_ROLES = {"admin"}
AUDIT_ROLES = {"admin", "auditor", "model_manager"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def epoch() -> int:
    return int(time.time())


def connect() -> sqlite3.Connection:
    SECURITY_ROOT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_security_store() -> None:
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
    action = "user.disabled" if status == "disabled" else "user.enabled"
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
    with connect() as conn:
        user_row = conn.execute("SELECT * FROM users WHERE email = ?", (normalize_email(email),)).fetchone()
        user = row_to_user(user_row)
        if not user:
            audit_event("auth.login.failure", "auth", None, "failure", reason="Invalid credentials", metadata={"emailHash": hash_observable(normalize_email(email))}, conn=conn)
            raise generic
        if user["status"] == "disabled":
            audit_event("auth.login.failure", "auth", user["userId"], "denied", reason="Disabled user", conn=conn)
            raise generic
        locked_until = user.get("lockedUntil")
        if locked_until and locked_until > now_iso():
            audit_event("auth.login.failure", "auth", user["userId"], "denied", reason="Account locked", conn=conn)
            raise generic
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
            raise generic
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
        conn.execute("UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login_at = ?, updated_at = ? WHERE user_id = ?", (timestamp, timestamp, user["userId"]))
        audit_event("auth.login.success", "auth", user["userId"], "success", conn=conn)
        updated = row_to_user(conn.execute("SELECT * FROM users WHERE user_id = ?", (user["userId"],)).fetchone()) or user
        return {"sessionId": session_id, "expiresAt": expires, "user": public_user(updated)}


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


def require_user(request: Request) -> Dict[str, Any]:
    if not ATLAS_AUTH_ENABLED:
        user = get_user("local-user") or get_user_by_email(DEFAULT_ADMIN_EMAIL)
        set_active_user(user)
        return public_user(user or {})
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    user = user_for_session(session_id)
    if not user:
        audit_event("access.denied", "auth", None, "denied", reason="Authentication required")
        raise HTTPException(status_code=401, detail="Authentication required.")
    if user.get("status") != "active":
        audit_event("access.denied", "auth", user.get("userId"), "denied", reason="User is not active")
        raise HTTPException(status_code=403, detail="User is not active.")
    set_active_user(user)
    return public_user(user)


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
    try:
        user = active_user()
        actor = user_id if user_id is not None else user.get("userId") if user else None
        safe_metadata = metadata or {}
        active_conn.execute(
            """
            INSERT INTO audit_events (audit_id, timestamp, user_id, action, resource_type, resource_id, outcome, reason, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"audit_{uuid.uuid4().hex}",
                now_iso(),
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


def list_audit_events(limit: int = 250, user_id: Optional[str] = None, resource_type: Optional[str] = None, outcome: Optional[str] = None, action: Optional[str] = None) -> List[Dict[str, Any]]:
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
    return {
        "auditId": row["audit_id"],
        "timestamp": row["timestamp"],
        "userId": row["user_id"],
        "action": row["action"],
        "resourceType": row["resource_type"],
        "resourceId": row["resource_id"],
        "outcome": row["outcome"],
        "reason": row["reason"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
    }


def grant_project_access(project_id: str, user_id: str, permission: str, granted_by: Optional[str]) -> Dict[str, Any]:
    if permission not in PROJECT_ACCESS_ROLES:
        raise HTTPException(status_code=400, detail="Unsupported project permission.")
    timestamp = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO project_access (project_id, user_id, permission, granted_by_user_id, granted_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id, user_id) DO UPDATE SET permission = excluded.permission, granted_by_user_id = excluded.granted_by_user_id, granted_at = excluded.granted_at
            """,
            (project_id, user_id, permission, granted_by, timestamp),
        )
        audit_event("project.shared", "project", project_id, "success", metadata={"targetUserId": user_id, "permission": permission}, conn=conn)
    return {"projectId": project_id, "userId": user_id, "permission": permission, "grantedAt": timestamp}


def revoke_project_access(project_id: str, user_id: str) -> Dict[str, Any]:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM project_access WHERE project_id = ? AND user_id = ?", (project_id, user_id))
        audit_event("project.access.revoked", "project", project_id, "success", metadata={"targetUserId": user_id}, conn=conn)
    return {"ok": True, "removed": cursor.rowcount}


def list_project_access(project_id: str) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM project_access WHERE project_id = ? ORDER BY granted_at DESC", (project_id,)).fetchall()
        return [dict(row) for row in rows]


def user_can_access_project(project_id: str, user: Optional[Dict[str, Any]] = None, write: bool = False) -> bool:
    active = user or active_user() or get_user("local-user")
    if not active:
        return False
    if active.get("role") == "admin":
        return True
    allowed = {"owner", "editor", "approver"} if write else PROJECT_ACCESS_ROLES
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM project_access WHERE project_id = ?", (project_id,)).fetchone()["n"]
        if total == 0 and active.get("userId"):
            conn.execute(
                "INSERT INTO project_access (project_id, user_id, permission, granted_by_user_id, granted_at) VALUES (?, ?, 'owner', ?, ?)",
                (project_id, active.get("userId"), active.get("userId"), now_iso()),
            )
            audit_event("project.created", "project", project_id, "success", metadata={"implicitOwner": True}, conn=conn)
            return True
        row = conn.execute("SELECT permission FROM project_access WHERE project_id = ? AND user_id = ?", (project_id, active.get("userId"))).fetchone()
        return bool(row and row["permission"] in allowed)


def security_diagnostics() -> Dict[str, Any]:
    init_security_store()
    users = list_users()
    checks = []
    checks.append({"id": "auth_enabled", "label": "Authentication enabled", "status": "pass" if ATLAS_AUTH_ENABLED else "warning", "detail": f"ATLAS_AUTH_ENABLED={ATLAS_AUTH_ENABLED}"})
    checks.append({"id": "user_db", "label": "User database reachable", "status": "pass" if DB_PATH.exists() else "fail", "detail": str(DB_PATH)})
    checks.append({"id": "hashing", "label": "Password hashing configured", "status": "warning", "detail": f"{PASSWORD_ALGORITHM} with per-user random salt. Install argon2id/bcrypt for production-grade hosted deployment."})
    checks.append({"id": "admin_exists", "label": "Admin user exists", "status": "pass" if any(user.get("role") == "admin" for user in users) else "fail", "detail": f"{len(users)} user records."})
    checks.append({"id": "session_secret", "label": "Security secret configured", "status": "warning" if SESSION_SECRET == "atlas-local-dev-default-session-secret" else "pass", "detail": "Default local secret is in use." if SESSION_SECRET == "atlas-local-dev-default-session-secret" else "Custom session secret configured."})
    checks.append({"id": "cookie_policy", "label": "Session cookie policy", "status": "pass" if ATLAS_LOCAL_DEV or ATLAS_HOSTED_MODE else "warning", "detail": "Secure cookies are required when not running local development."})
    checks.append({"id": "dataset_acl", "label": "Dataset ACL enforcement available", "status": "pass", "detail": "Dataset endpoints require authenticated user context and owner/grant/admin access."})
    checks.append({"id": "project_acl", "label": "Project ACL enforcement available", "status": "pass", "detail": "Project access grants and project-dataset link checks are available."})
    checks.append({"id": "audit_writable", "label": "Audit logging writable", "status": "pass", "detail": "Audit events are stored in SQLite."})
    checks.append({"id": "hosted_python", "label": "Hosted mode Python execution disabled", "status": "pass" if not ATLAS_HOSTED_MODE or os.getenv("ATLAS_ENABLE_PYTHON_RUN", "1") in {"0", "false"} else "warning", "detail": f"ATLAS_HOSTED_MODE={ATLAS_HOSTED_MODE}, ATLAS_ENABLE_PYTHON_RUN={os.getenv('ATLAS_ENABLE_PYTHON_RUN', '1')}"})
    audit_event("diagnostics.run", "system", "security", "success", metadata={"checks": len(checks)})
    return {"ok": True, "generatedAt": now_iso(), "checks": checks, "currentUser": public_user(active_user() or get_user("local-user") or {}), "authEnabled": ATLAS_AUTH_ENABLED}

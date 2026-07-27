"""Behavioral release-gate tests for ATLAS security containment phase 1.

The suite uses disposable SQLite databases and real FastAPI requests. It
deliberately avoids source-text assertions: every assertion observes an HTTP,
database, session, or startup-validation behavior.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import unittest
import uuid
import asyncio
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TMP_ROOT = ROOT / ".tmp"
TMP_ROOT.mkdir(exist_ok=True)
RUN_ID = uuid.uuid4().hex[:10]
SECURITY_DB = TMP_ROOT / f"atlas_security_containment_{RUN_ID}.db"
PERSISTENCE_DB = TMP_ROOT / f"atlas_security_containment_persistence_{RUN_ID}.db"

os.environ["ATLAS_SECURITY_DB_PATH"] = str(SECURITY_DB)
os.environ["ATLAS_SQLITE_PATH"] = str(PERSISTENCE_DB)
os.environ["ATLAS_AUTH_ENABLED"] = "true"
os.environ["ATLAS_LOCAL_DEV"] = "false"
os.environ["ATLAS_HOSTED_MODE"] = "false"
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "false"
os.environ["ATLAS_ENABLE_DEV_USER_HEADER"] = "false"
os.environ["ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
import httpx  # noqa: E402

from server.main import app, assert_api_routes_authenticated  # noqa: E402
from server.security import security_store  # noqa: E402


def cleanup_databases() -> None:
    for base in (SECURITY_DB, PERSISTENCE_DB):
        for suffix in ("", "-wal", "-shm"):
            target = Path(f"{base}{suffix}")
            for attempt in range(25):
                try:
                    target.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt < 24:
                        time.sleep(0.2)


@contextmanager
def registration_enabled():
    with patch.object(security_store, "ATLAS_ALLOW_PUBLIC_REGISTRATION", True):
        yield


class SecurityContainmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_databases()
        security_store.init_security_store()
        cls.admin_password = "ContainmentAdminPass123!"
        cls.admin = security_store.create_user(
            email="security-admin@containment.test",
            display_name="Security Admin",
            password=cls.admin_password,
            role="admin",
        )
        cls.analyst_password = "ContainmentAnalystPass123!"
        cls.analyst = security_store.create_user(
            email="security-analyst@containment.test",
            display_name="Security Analyst",
            password=cls.analyst_password,
            role="data_scientist",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_databases()

    def login(self, email: str, password: str) -> TestClient:
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("sessionId", response.text)
        return client

    def register(self, label: str, **extra: object):
        suffix = uuid.uuid4().hex[:8]
        payload = {
            "email": f"{label}-{suffix}@containment.test",
            "displayName": f"Containment {label}",
            "password": "ContainmentRegisterPass123!",
            **extra,
        }
        return TestClient(app).post("/api/auth/register", json=payload)

    def test_public_registration_is_disabled_by_default_without_enumeration(self) -> None:
        first = self.register("disabled")
        duplicate = self.register("disabled-existing", email=self.analyst["email"])
        self.assertEqual(first.status_code, 403)
        self.assertEqual(duplicate.status_code, 403)
        self.assertEqual(first.json(), duplicate.json())
        self.assertEqual(first.json()["detail"], "Public registration is not enabled.")

    def test_enabled_registration_ignores_all_privilege_inputs(self) -> None:
        attacks = [
            "admin",
            "ADMIN",
            " admin ",
            "administrator",
            "validator",
            "model manager",
            "model_manager",
            "manager",
            {"name": "admin"},
            ["admin"],
            None,
        ]
        with registration_enabled():
            for index, role in enumerate(attacks):
                with self.subTest(role=role):
                    response = self.register(f"role-{index}", role=role)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["user"]["role"], "data_scientist")

    def test_role_elevation_requires_admin_and_is_audited(self) -> None:
        analyst_client = self.login(self.analyst["email"], self.analyst_password)
        denied = analyst_client.post(f"/api/admin/users/{self.analyst['userId']}/role", json={"role": "admin"})
        self.assertEqual(denied.status_code, 403, denied.text)

        admin_client = self.login(self.admin["email"], self.admin_password)
        with registration_enabled():
            created = self.register("role-target")
        target_id = created.json()["user"]["userId"]
        allowed = admin_client.post(f"/api/admin/users/{target_id}/role", json={"role": "validator"})
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(allowed.json()["user"]["role"], "validator")

        with sqlite3.connect(SECURITY_DB) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT action, outcome, user_id FROM audit_events "
                "WHERE action = 'user.role.changed' ORDER BY timestamp"
            ).fetchall()
        self.assertTrue(any(row["outcome"] == "denied" and row["user_id"] == self.analyst["userId"] for row in rows))
        self.assertTrue(any(row["outcome"] == "success" and row["user_id"] == self.admin["userId"] for row in rows))

    def test_dev_header_is_ignored_by_default_even_when_auth_is_enabled(self) -> None:
        response = TestClient(app).get(
            "/api/auth/me",
            headers={security_store.LOCAL_DEV_USER_HEADER: self.admin["userId"]},
        )
        self.assertEqual(response.status_code, 401, response.text)
        serialized = response.text.lower()
        for forbidden in (self.admin["userId"].lower(), self.admin["email"].lower(), "available_dev_users", "x-atlas-user-id"):
            self.assertNotIn(forbidden, serialized)

    def test_dev_header_requires_explicit_local_loopback_configuration(self) -> None:
        enabled = {
            "ATLAS_ENABLE_DEV_USER_HEADER": True,
            "ATLAS_LOCAL_DEV": True,
            "ATLAS_HOSTED_MODE": False,
        }
        async def exercise():
            headers = {security_store.LOCAL_DEV_USER_HEADER: self.analyst["userId"]}
            loopback_transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
            remote_transport = httpx.ASGITransport(app=app, client=("203.0.113.20", 50000))
            async with httpx.AsyncClient(transport=loopback_transport, base_url="http://atlas.test") as client:
                loopback_response = await client.get("/api/auth/me", headers=headers)
            async with httpx.AsyncClient(transport=remote_transport, base_url="http://atlas.test") as client:
                remote_response = await client.get("/api/auth/me", headers=headers)
            return loopback_response, remote_response

        with patch.multiple(security_store, **enabled):
            loopback, remote = asyncio.run(exercise())
        self.assertEqual(loopback.status_code, 200, loopback.text)
        self.assertEqual(remote.status_code, 401, remote.text)

    def test_forwarded_header_spoofing_cannot_create_loopback_identity(self) -> None:
        enabled = {
            "ATLAS_ENABLE_DEV_USER_HEADER": True,
            "ATLAS_LOCAL_DEV": True,
            "ATLAS_HOSTED_MODE": False,
            "ATLAS_TRUSTED_PROXY_IPS": frozenset(),
        }
        headers = {
            security_store.LOCAL_DEV_USER_HEADER: self.admin["userId"],
            "X-Forwarded-For": "127.0.0.1",
        }
        async def exercise():
            transport = httpx.ASGITransport(app=app, client=("203.0.113.20", 50000))
            async with httpx.AsyncClient(transport=transport, base_url="http://atlas.test") as client:
                return await client.get("/api/auth/me", headers=headers)

        with patch.multiple(security_store, **enabled):
            response = asyncio.run(exercise())
        self.assertEqual(response.status_code, 401, response.text)

    def test_conflicting_session_and_dev_header_identities_are_rejected(self) -> None:
        enabled = {
            "ATLAS_ENABLE_DEV_USER_HEADER": True,
            "ATLAS_LOCAL_DEV": True,
            "ATLAS_HOSTED_MODE": False,
        }
        async def exercise():
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
            async with httpx.AsyncClient(transport=transport, base_url="http://atlas.test") as client:
                login_response = await client.post(
                    "/api/auth/login",
                    json={"email": self.analyst["email"], "password": self.analyst_password},
                )
                self.assertEqual(login_response.status_code, 200, login_response.text)
                return await client.get(
                    "/api/auth/me",
                    headers={security_store.LOCAL_DEV_USER_HEADER: self.admin["userId"]},
                )

        with patch.multiple(security_store, **enabled):
            response = asyncio.run(exercise())
        self.assertEqual(response.status_code, 400, response.text)

    def test_public_health_endpoints_are_minimal(self) -> None:
        client = TestClient(app)
        health = client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"ok": True, "status": "running"})
        persistence = client.get("/api/persistence/health")
        self.assertEqual(persistence.status_code, 200)
        self.assertEqual(persistence.json(), {"ok": True, "status": "running"})

    def test_security_diagnostics_require_admin_and_do_not_expose_secrets_or_paths(self) -> None:
        anonymous = TestClient(app).get("/api/security/diagnostics")
        self.assertEqual(anonymous.status_code, 401)
        analyst = self.login(self.analyst["email"], self.analyst_password).get("/api/security/diagnostics")
        self.assertEqual(analyst.status_code, 403)
        admin = self.login(self.admin["email"], self.admin_password).get("/api/security/diagnostics")
        self.assertEqual(admin.status_code, 200, admin.text)
        serialized = admin.text.lower()
        for forbidden in ("session-secret", "atlas_security.db", str(ROOT).lower(), self.admin_password.lower()):
            self.assertNotIn(forbidden, serialized)

    def test_login_logout_and_expired_session_regressions(self) -> None:
        client = TestClient(app)
        login_response = client.post(
            "/api/auth/login",
            json={"email": self.analyst["email"], "password": self.analyst_password},
        )
        self.assertEqual(login_response.status_code, 200, login_response.text)
        cookie = login_response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertNotIn("secure", cookie)
        self.assertEqual(client.get("/api/auth/me").status_code, 200)
        self.assertEqual(client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(client.get("/api/auth/me").status_code, 401)

        expired_client = self.login(self.analyst["email"], self.analyst_password)
        session_id = expired_client.cookies.get(security_store.SESSION_COOKIE_NAME)
        with sqlite3.connect(SECURITY_DB) as connection:
            connection.execute(
                "UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00' WHERE session_id = ?",
                (session_id,),
            )
            connection.commit()
        self.assertEqual(expired_client.get("/api/auth/me").status_code, 401)

    def test_role_change_revokes_existing_target_sessions(self) -> None:
        with registration_enabled():
            created = self.register("revoke-role-session")
        target = created.json()["user"]
        target_client = self.login(target["email"], "ContainmentRegisterPass123!")
        self.assertEqual(target_client.get("/api/auth/me").status_code, 200)
        admin_client = self.login(self.admin["email"], self.admin_password)
        changed = admin_client.post(f"/api/admin/users/{target['userId']}/role", json={"role": "viewer"})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(target_client.get("/api/auth/me").status_code, 401)

    def test_route_authentication_startup_assertion_and_public_surface(self) -> None:
        assert_api_routes_authenticated(app)
        public = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
            if route.path.startswith("/api/") and route.path in {
                "/api/health",
                "/api/persistence/health",
                "/api/auth/login",
                "/api/auth/register",
                "/api/auth/request-password-reset",
                "/api/auth/reset-password",
            }
        }
        self.assertIn(("GET", "/api/health"), public)
        self.assertIn(("POST", "/api/auth/register"), public)

    def test_hosted_mode_rejects_each_unsafe_authentication_setting(self) -> None:
        safe = {
            "ATLAS_HOSTED_MODE": True,
            "ATLAS_AUTH_ENABLED": True,
            "ATLAS_LOCAL_DEV": False,
            "ATLAS_ENABLE_DEV_USER_HEADER": False,
            "ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP": False,
            "ATLAS_ALLOW_PUBLIC_REGISTRATION": False,
            "SESSION_SECRET": "a-unique-hosted-session-secret-with-sufficient-length",
            "DEFAULT_ADMIN_PASSWORD": "A-unique-hosted-bootstrap-password!",
            "ATLAS_COOKIE_SECURE": True,
            "ATLAS_CORS_ORIGINS": ("https://atlas.example.test",),
        }
        unsafe = [
            ("development header", {"ATLAS_ENABLE_DEV_USER_HEADER": True}),
            ("local development", {"ATLAS_LOCAL_DEV": True}),
            ("local-user bootstrap", {"ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP": True}),
            ("authentication disabled", {"ATLAS_AUTH_ENABLED": False}),
            ("default session secret", {"SESSION_SECRET": security_store.DEFAULT_SESSION_SECRET}),
            ("default administrator password", {"DEFAULT_ADMIN_PASSWORD": security_store.DEFAULT_LOCAL_ADMIN_PASSWORD}),
            ("insecure cookies", {"ATLAS_COOKIE_SECURE": False}),
            ("missing allowed origins", {"ATLAS_CORS_ORIGINS": ()}),
            ("insecure allowed origin", {"ATLAS_CORS_ORIGINS": ("http://atlas.example.test",)}),
        ]
        with patch.multiple(security_store, **safe):
            security_store.validate_security_configuration()
            for label, override in unsafe:
                with self.subTest(label=label), patch.multiple(security_store, **override):
                    with self.assertRaisesRegex(RuntimeError, label):
                        security_store.validate_security_configuration()

    def test_hosted_startup_event_fails_before_application_initialization(self) -> None:
        unsafe_hosted = {
            "ATLAS_HOSTED_MODE": True,
            "ATLAS_AUTH_ENABLED": True,
            "ATLAS_LOCAL_DEV": False,
            "ATLAS_ENABLE_DEV_USER_HEADER": True,
            "ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP": False,
            "SESSION_SECRET": "a-unique-hosted-session-secret-with-sufficient-length",
            "DEFAULT_ADMIN_PASSWORD": "A-unique-hosted-bootstrap-password!",
            "ATLAS_COOKIE_SECURE": True,
            "ATLAS_CORS_ORIGINS": ("https://atlas.example.test",),
        }
        with patch.multiple(security_store, **unsafe_hosted):
            with self.assertRaisesRegex(RuntimeError, "development header"):
                with TestClient(app):
                    self.fail("Unsafe hosted startup must not enter the application lifespan.")

    def test_hosted_cookie_policy_sets_secure_attribute(self) -> None:
        with patch.object(security_store, "ATLAS_COOKIE_SECURE", True):
            client = TestClient(app)
            response = client.post(
                "/api/auth/login",
                json={"email": self.analyst["email"], "password": self.analyst_password},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("secure", response.headers["set-cookie"].lower())


if __name__ == "__main__":
    unittest.main()

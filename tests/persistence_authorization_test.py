"""Router-level API integration tests for FND-001.

FND-001: server/persistence/persistence_router.py required authentication
(the caller must be *some* logged-in user) but performed no resource-level
authorization (the caller must be *the right* logged-in user) before
reading, changing, creating nested resources under, or deleting a project.

These tests drive the real FastAPI app through fastapi.testclient -- real
HTTP requests, real routing, real Depends(require_user) dependency
injection -- rather than calling SharingService directly. That distinction
matters: the pre-existing tests/admin_sharing_backend_test.py already prove
SharingService.check_permission() is correct in isolation; this file proves
the HTTP layer actually calls it.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# server.security.security_store resolves its DB_PATH as a module-level
# constant at import time, so these environment variables must be set
# BEFORE server.main (or anything importing server.security.security_store)
# is imported for the first time in this process. This mirrors the pattern
# already used by tests/sqlite_persistence_backend_test.py.
_TEST_DATA_ROOT = ROOT / ".tmp"
_TEST_DATA_ROOT.mkdir(parents=True, exist_ok=True)
_RUN_ID = uuid.uuid4().hex[:10]
_SECURITY_DB_PATH = _TEST_DATA_ROOT / f"atlas_persistence_authorization_security_{_RUN_ID}.db"
_PERSISTENCE_DB_PATH = _TEST_DATA_ROOT / f"atlas_persistence_authorization_persistence_{_RUN_ID}.db"
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH)
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402


def _cleanup_db_files() -> None:
    # SQLite connections opened during the test run can briefly hold a
    # Windows file lock past the last request; retry rather than fail
    # cleanup, matching the pattern in tests/sqlite_persistence_backend_test.py.
    for base in (_SECURITY_DB_PATH, _PERSISTENCE_DB_PATH):
        for suffix in ("", "-wal", "-shm"):
            target = Path(f"{base}{suffix}")
            for attempt in range(25):
                try:
                    target.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt < 24:
                        time.sleep(0.2)


class PersistenceAuthorizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        # Initialize both stores explicitly rather than relying on FastAPI's
        # startup event firing through TestClient, matching the explicit
        # initialization pattern already used in tests/admin_sharing_backend_test.py.
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    # ---- helpers -----------------------------------------------------

    def _register(self, label: str) -> tuple[TestClient, str]:
        client = TestClient(app)
        suffix = uuid.uuid4().hex[:10]
        response = client.post(
            "/api/auth/register",
            json={
                "email": f"{label}-{suffix}@atlas-fnd001-test.local",
                "displayName": f"FND-001 Test {label} {suffix}",
                "password": "AuthFnd001TestPass!",
                "role": "data_scientist",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return client, response.json()["user"]["userId"]

    def _create_project(self, client: TestClient, name: str) -> str:
        response = client.post("/api/projects", json={"projectName": name, "projectType": "predictive-modeling"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["project"]["projectId"]

    def _create_evidence(self, client: TestClient, project_id: str, title: str) -> str:
        response = client.post(f"/api/projects/{project_id}/evidence", json={"title": title})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["evidence"]["evidenceId"]

    def _share(self, owner_client: TestClient, project_id: str, principal_id: str, permission: str) -> None:
        response = owner_client.post(
            f"/api/sharing/resources/project/{project_id}/share",
            json={"principalType": "user", "principalId": principal_id, "permissionLevel": permission},
        )
        self.assertEqual(response.status_code, 200, response.text)

    # ---- tests ---------------------------------------------------------

    def test_full_cross_user_authorization_sequence(self) -> None:
        # 1-2. Register User A (owner) and User B (unrelated), each an
        # independent authenticated session with its own cookie jar.
        client_a, user_a_id = self._register("owner")
        client_b, user_b_id = self._register("stranger")

        # 3-4. User A creates a project and evidence under it.
        project_id = self._create_project(client_a, "FND-001 Owner Project")
        self._create_evidence(client_a, project_id, "Confidential Evidence A")

        # 5. User A (the owner) can view, edit, and read evidence.
        get_response = client_a.get(f"/api/projects/{project_id}")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["project"]["projectName"], "FND-001 Owner Project")

        update_response = client_a.put(f"/api/projects/{project_id}", json={"projectName": "FND-001 Owner Project Updated"})
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["project"]["projectName"], "FND-001 Owner Project Updated")

        evidence_list_response = client_a.get(f"/api/projects/{project_id}/evidence")
        self.assertEqual(evidence_list_response.status_code, 200)
        self.assertEqual(evidence_list_response.json()["count"], 1)
        evidence_id = evidence_list_response.json()["evidence"][0]["evidenceId"]

        # 6. User B (authenticated, unrelated) must be denied on every
        # project-scoped read, write, create, and delete operation, and the
        # 403 body must not leak protected content.
        denied_requests = [
            ("GET", f"/api/projects/{project_id}", None),
            ("PUT", f"/api/projects/{project_id}", {"projectName": "Hijacked by B"}),
            ("DELETE", f"/api/projects/{project_id}", None),
            ("GET", f"/api/projects/{project_id}/evidence", None),
            ("POST", f"/api/projects/{project_id}/evidence", {"title": "Planted by B"}),
            ("PUT", f"/api/projects/{project_id}/evidence/{evidence_id}", {"title": "Tampered by B"}),
            ("GET", f"/api/projects/{project_id}/workflow-state", None),
            ("PUT", f"/api/projects/{project_id}/workflow-state", {"currentStepId": "step02"}),
            ("GET", f"/api/projects/{project_id}/runs", None),
            ("POST", f"/api/projects/{project_id}/runs", {"runType": "workflow"}),
            ("GET", f"/api/projects/{project_id}/decisions", None),
            ("POST", f"/api/projects/{project_id}/decisions", {"title": "Planted decision"}),
            ("GET", f"/api/projects/{project_id}/documentation", None),
            ("POST", f"/api/projects/{project_id}/documentation", {"packageType": "model_development_document"}),
            ("GET", f"/api/projects/{project_id}/exports", None),
            ("POST", f"/api/projects/{project_id}/exports", {"exportType": "download"}),
        ]
        for method, path, body in denied_requests:
            with self.subTest(method=method, path=path):
                response = client_b.request(method, path, json=body)
                self.assertEqual(response.status_code, 403, f"{method} {path} -> {response.status_code}: {response.text}")
                self.assertNotIn("Confidential Evidence A", response.text)
                self.assertNotIn("FND-001 Owner Project", response.text)

        # 7. User A's project and evidence remain unchanged after every one
        # of User B's denied attempts above.
        unchanged_project = client_a.get(f"/api/projects/{project_id}")
        self.assertEqual(unchanged_project.json()["project"]["projectName"], "FND-001 Owner Project Updated")
        unchanged_evidence = client_a.get(f"/api/projects/{project_id}/evidence")
        self.assertEqual(unchanged_evidence.json()["count"], 1)
        self.assertEqual(unchanged_evidence.json()["evidence"][0]["title"], "Confidential Evidence A")

        # Listing requirement: User B's own project list must not include a
        # project they cannot access.
        list_as_b_before_share = client_b.get("/api/projects")
        self.assertEqual(list_as_b_before_share.status_code, 200)
        self.assertNotIn(project_id, [item["projectId"] for item in list_as_b_before_share.json()["projects"]])

        # 8. Grant User B "view" permission via the existing sharing system.
        self._share(client_a, project_id, user_b_id, "view")

        # 9. User B can now view, but still cannot edit or delete.
        viewer_get = client_b.get(f"/api/projects/{project_id}")
        self.assertEqual(viewer_get.status_code, 200)
        self.assertEqual(viewer_get.json()["project"]["projectName"], "FND-001 Owner Project Updated")

        self.assertEqual(client_b.get(f"/api/projects/{project_id}/evidence").status_code, 200)
        self.assertEqual(client_b.put(f"/api/projects/{project_id}", json={"projectName": "Still hijacked?"}).status_code, 403)
        self.assertEqual(client_b.delete(f"/api/projects/{project_id}").status_code, 403)
        self.assertEqual(client_b.post(f"/api/projects/{project_id}/evidence", json={"title": "Still planted?"}).status_code, 403)

        list_as_b_after_view_share = client_b.get("/api/projects")
        self.assertIn(project_id, [item["projectId"] for item in list_as_b_after_view_share.json()["projects"]])

        # 10. Grant "edit" permission: User B can now edit and create nested
        # records, but still cannot delete (delete requires admin).
        self._share(client_a, project_id, user_b_id, "edit")
        editor_update = client_b.put(f"/api/projects/{project_id}", json={"projectName": "Edited by B with permission"})
        self.assertEqual(editor_update.status_code, 200)
        self.assertEqual(editor_update.json()["project"]["projectName"], "Edited by B with permission")
        self.assertEqual(client_b.post(f"/api/projects/{project_id}/evidence", json={"title": "Legitimately added by B"}).status_code, 200)
        self.assertEqual(client_b.delete(f"/api/projects/{project_id}").status_code, 403)

        # Granting "admin" permission allows the destructive operation.
        self._share(client_a, project_id, user_b_id, "admin")
        admin_delete = client_b.delete(f"/api/projects/{project_id}")
        self.assertEqual(admin_delete.status_code, 200)
        self.assertTrue(admin_delete.json()["deleted"])

        # 11. An unauthenticated caller receives 401 (not 403/404).
        anonymous_client = TestClient(app)
        for method, path in [("GET", "/api/projects"), ("GET", f"/api/projects/{project_id}"), ("PUT", f"/api/projects/{project_id}")]:
            with self.subTest(method=method, path=path):
                response = anonymous_client.request(method, path, json={} if method == "PUT" else None)
                self.assertEqual(response.status_code, 401, f"{method} {path} -> {response.status_code}: {response.text}")

    def test_denied_access_is_recorded_in_the_audit_log(self) -> None:
        client_a, _user_a_id = self._register("audit-owner")
        client_b, user_b_id = self._register("audit-stranger")
        project_id = self._create_project(client_a, "FND-001 Audit Project")

        denied = client_b.get(f"/api/projects/{project_id}")
        self.assertEqual(denied.status_code, 403)

        with sqlite3.connect(_SECURITY_DB_PATH) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE action = 'access.denied' AND resource_id = ?",
                (project_id,),
            ).fetchall()
        self.assertTrue(rows, "Expected an access.denied audit event for the unauthorized project access attempt.")
        self.assertEqual(rows[0]["user_id"], user_b_id)
        self.assertEqual(rows[0]["outcome"], "denied")

    def test_creating_nested_resources_under_an_inaccessible_project_is_denied(self) -> None:
        client_a, _user_a_id = self._register("nested-owner")
        client_b, _user_b_id = self._register("nested-stranger")
        project_id = self._create_project(client_a, "FND-001 Nested Resource Project")

        creation_attempts = [
            ("evidence", f"/api/projects/{project_id}/evidence", {"title": "x"}),
            ("run", f"/api/projects/{project_id}/runs", {"runType": "workflow"}),
            ("decision", f"/api/projects/{project_id}/decisions", {"title": "x"}),
            ("documentation", f"/api/projects/{project_id}/documentation", {"packageType": "model_development_document"}),
            ("export", f"/api/projects/{project_id}/exports", {"exportType": "download"}),
        ]
        for label, path, body in creation_attempts:
            with self.subTest(resource=label):
                response = client_b.post(path, json=body)
                self.assertEqual(response.status_code, 403, f"{path} -> {response.status_code}: {response.text}")

        # None of User B's denied attempts actually created anything.
        self.assertEqual(client_a.get(f"/api/projects/{project_id}/evidence").json()["count"], 0)
        self.assertEqual(client_a.get(f"/api/projects/{project_id}/runs").json()["count"], 0)
        self.assertEqual(client_a.get(f"/api/projects/{project_id}/decisions").json()["count"], 0)
        self.assertEqual(client_a.get(f"/api/projects/{project_id}/documentation").json()["count"], 0)
        self.assertEqual(client_a.get(f"/api/projects/{project_id}/exports").json()["count"], 0)

    def test_evidence_cannot_be_hijacked_into_a_different_project_via_update(self) -> None:
        client_a, _user_a_id = self._register("hijack-owner-a")
        client_c, _user_c_id = self._register("hijack-owner-c")
        project_a = self._create_project(client_a, "FND-001 Project A")
        project_c = self._create_project(client_c, "FND-001 Project C")
        evidence_id = self._create_evidence(client_a, project_a, "Owned by A")

        # User C has edit rights on their OWN project C, but tries to reach
        # A's evidence_id by addressing it through C's own project URL.
        response = client_c.put(
            f"/api/projects/{project_c}/evidence/{evidence_id}",
            json={"title": "Reparented into C"},
        )
        self.assertEqual(response.status_code, 404, response.text)

        still_under_a = client_a.get(f"/api/projects/{project_a}/evidence")
        self.assertEqual(still_under_a.json()["count"], 1)
        self.assertEqual(still_under_a.json()["evidence"][0]["title"], "Owned by A")
        under_c = client_c.get(f"/api/projects/{project_c}/evidence")
        self.assertEqual(under_c.json()["count"], 0)

    def test_unauthenticated_caller_receives_401_not_403(self) -> None:
        client_a, _user_a_id = self._register("anon-check-owner")
        project_id = self._create_project(client_a, "FND-001 Anonymous Check Project")

        anonymous_client = TestClient(app)
        response = anonymous_client.get(f"/api/projects/{project_id}")
        self.assertEqual(response.status_code, 401, response.text)


if __name__ == "__main__":
    unittest.main()

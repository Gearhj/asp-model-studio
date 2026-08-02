"""Router-level API integration tests for FND-002.

FND-002: server/security/security_store.py had its own independent project
ACL implementation (grant_project_access/revoke_project_access/list_project_access/
user_can_access_project, backed by a project_access table in the security
database) that was completely disconnected from server/sharing/sharing_service.py
(backed by resource_permissions/project_collaborators in the persistence
database) -- the system server/persistence/persistence_router.py's FND-001
authorization fix actually checks. A grant made through one system was
invisible to the other.

These tests drive the real FastAPI app through fastapi.testclient, exercising
BOTH the legacy /api/projects/{id}/access/* endpoints and the modern
/api/sharing/... endpoints, to prove they now write to and read from the same
underlying store and are both immediately recognized by the FND-001-protected
persistence routes.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# security_store.DB_PATH and persistence/db.py's database path are resolved
# from these environment variables; the security path is a module-level
# constant read at import time, so both must be set BEFORE server.main (or
# anything importing server.security.security_store) is imported for the
# first time in this process. Mirrors tests/persistence_authorization_test.py.
_TEST_DATA_ROOT = ROOT / ".tmp"
_TEST_DATA_ROOT.mkdir(parents=True, exist_ok=True)
_RUN_ID = uuid.uuid4().hex[:10]
_SECURITY_DB_PATH = _TEST_DATA_ROOT / f"atlas_project_access_security_{_RUN_ID}.db"
_PERSISTENCE_DB_PATH = _TEST_DATA_ROOT / f"atlas_project_access_persistence_{_RUN_ID}.db"
_DATASET_LIBRARY_ROOT = _TEST_DATA_ROOT / f"atlas_project_access_datasets_{_RUN_ID}"
_DATASET_BACKUP_ROOT = Path(tempfile.gettempdir()) / f"atlas_project_access_backups_{_RUN_ID}"
_CHECKPOINT_PATH = _TEST_DATA_ROOT / f"atlas_project_access_checkpoint_{_RUN_ID}.json"
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(_CHECKPOINT_PATH)
os.environ["ATLAS_TEST_MODE"] = "1"
os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(_DATASET_LIBRARY_ROOT)
os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(_DATASET_BACKUP_ROOT)
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402
from server.core import session_checkpoint as session_checkpoint_module  # noqa: E402
from server.datasets import dataset_registry as dataset_registry_module  # noqa: E402
from server.security import security_store as security_store_module  # noqa: E402


def _bind_isolated_runtime_paths() -> None:
    os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
    os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH)
    os.environ["ATLAS_CHECKPOINT_PATH"] = str(_CHECKPOINT_PATH)
    os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(_DATASET_LIBRARY_ROOT)
    os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(_DATASET_BACKUP_ROOT)
    security_store_module.SECURITY_ROOT = _SECURITY_DB_PATH.parent.resolve()
    security_store_module.DB_PATH = _SECURITY_DB_PATH.resolve()
    security_store_module.ATLAS_AUTH_ENABLED = True
    security_store_module.ATLAS_ALLOW_PUBLIC_REGISTRATION = True
    session_checkpoint_module.CHECKPOINT_PATH = _CHECKPOINT_PATH.resolve()
    dataset_registry_module.ARTIFACT_ROOT = _DATASET_LIBRARY_ROOT.resolve()
    dataset_registry_module.REGISTRY_PATH = (
        _DATASET_LIBRARY_ROOT / "registry.json"
    ).resolve()
    dataset_registry_module.USERS_PATH = (
        _DATASET_LIBRARY_ROOT / "users.json"
    ).resolve()
    dataset_registry_module.PROJECT_LINKS_PATH = (
        _DATASET_LIBRARY_ROOT / "project_links.json"
    ).resolve()
    assert security_store_module.DB_PATH == _SECURITY_DB_PATH.resolve()
    assert session_checkpoint_module.CHECKPOINT_PATH == _CHECKPOINT_PATH.resolve()
    assert dataset_registry_module.ARTIFACT_ROOT == _DATASET_LIBRARY_ROOT.resolve()


_bind_isolated_runtime_paths()

SERVER_ROOT = ROOT / "server"


def _cleanup_db_files() -> None:
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
    shutil.rmtree(_DATASET_LIBRARY_ROOT, ignore_errors=True)
    shutil.rmtree(_DATASET_BACKUP_ROOT, ignore_errors=True)
    _CHECKPOINT_PATH.unlink(missing_ok=True)


class ProjectAccessConsolidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _bind_isolated_runtime_paths()
        _cleanup_db_files()
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
                "email": f"{label}-{suffix}@atlas-fnd002-test.local",
                "displayName": f"FND-002 Test {label} {suffix}",
                "password": "AuthFnd002TestPass!",
                "role": "data_scientist",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return client, response.json()["user"]["userId"]

    def _create_project(self, client: TestClient, name: str) -> str:
        response = client.post("/api/projects", json={"projectName": name, "projectType": "predictive-modeling"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["project"]["projectId"]

    def _grant_legacy(self, client: TestClient, project_id: str, user_id: str, permission: str) -> None:
        response = client.post(
            f"/api/projects/{project_id}/access/grant",
            json={"userId": user_id, "permission": permission},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _revoke_legacy(self, client: TestClient, project_id: str, user_id: str) -> None:
        response = client.post(
            f"/api/projects/{project_id}/access/revoke",
            json={"userId": user_id, "permission": "viewer"},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _share_modern(self, client: TestClient, project_id: str, user_id: str, permission_level: str) -> None:
        response = client.post(
            f"/api/sharing/resources/project/{project_id}/share",
            json={"principalType": "user", "principalId": user_id, "permissionLevel": permission_level},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _legacy_table_row_count(self, project_id: str) -> int:
        with sqlite3.connect(_SECURITY_DB_PATH) as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM project_access WHERE project_id = ?", (project_id,)
            ).fetchone()[0]

    # ---- tests ---------------------------------------------------------

    def test_grant_via_legacy_endpoint_is_recognized_by_fnd001_persistence_routes(self) -> None:
        owner, _owner_id = self._register("owner-a")
        stranger, stranger_id = self._register("stranger-b")
        project_id = self._create_project(owner, "FND-002 Legacy Grant Project")

        # User B is denied before any grant exists.
        self.assertEqual(stranger.get(f"/api/projects/{project_id}").status_code, 403)

        # Access granted through the legacy endpoint (still exposed for
        # compatibility) must be visible to the FND-001-protected persistence
        # routes immediately -- proving both now consult the same store.
        self._grant_legacy(owner, project_id, stranger_id, "viewer")
        view_response = stranger.get(f"/api/projects/{project_id}")
        self.assertEqual(view_response.status_code, 200, view_response.text)

        # View permission does not allow editing or deleting.
        self.assertEqual(stranger.put(f"/api/projects/{project_id}", json={"projectName": "hijack"}).status_code, 403)
        self.assertEqual(stranger.delete(f"/api/projects/{project_id}").status_code, 403)

        # Edit permission allows editing but not administrative deletion.
        self._grant_legacy(owner, project_id, stranger_id, "editor")
        edit_response = stranger.put(f"/api/projects/{project_id}", json={"projectName": "Edited by B"})
        self.assertEqual(edit_response.status_code, 200, edit_response.text)
        self.assertEqual(edit_response.json()["project"]["projectName"], "Edited by B")
        self.assertEqual(stranger.delete(f"/api/projects/{project_id}").status_code, 403)

        # Admin-equivalent permission ("owner" in the legacy vocabulary) allows
        # the intended administrative action (delete).
        self._grant_legacy(owner, project_id, stranger_id, "owner")
        delete_response = stranger.delete(f"/api/projects/{project_id}")
        self.assertEqual(delete_response.status_code, 200, delete_response.text)
        self.assertTrue(delete_response.json()["deleted"])

    def test_no_separate_legacy_acl_entry_is_required_for_access_to_work(self) -> None:
        owner, _owner_id = self._register("owner-c")
        stranger, stranger_id = self._register("stranger-d")
        project_id = self._create_project(owner, "FND-002 No Duplicate Record Project")

        self._grant_legacy(owner, project_id, stranger_id, "viewer")

        # The grant works...
        self.assertEqual(stranger.get(f"/api/projects/{project_id}").status_code, 200)
        # ...without writing anything into the legacy ACL table. The legacy
        # endpoint now delegates entirely to SharingService's own store.
        self.assertEqual(self._legacy_table_row_count(project_id), 0)

    def test_revocation_immediately_returns_403(self) -> None:
        owner, _owner_id = self._register("owner-e")
        stranger, stranger_id = self._register("stranger-f")
        project_id = self._create_project(owner, "FND-002 Revocation Project")

        self._grant_legacy(owner, project_id, stranger_id, "editor")
        self.assertEqual(stranger.get(f"/api/projects/{project_id}").status_code, 200)

        self._revoke_legacy(owner, project_id, stranger_id)
        self.assertEqual(stranger.get(f"/api/projects/{project_id}").status_code, 403)
        self.assertEqual(stranger.put(f"/api/projects/{project_id}", json={"projectName": "x"}).status_code, 403)

    def test_project_list_reflects_grants_and_revocations(self) -> None:
        owner, _owner_id = self._register("owner-g")
        stranger, stranger_id = self._register("stranger-h")
        project_id = self._create_project(owner, "FND-002 List Visibility Project")

        before_grant = stranger.get("/api/projects")
        self.assertEqual(before_grant.status_code, 200)
        self.assertNotIn(project_id, [item["projectId"] for item in before_grant.json()["projects"]])

        self._grant_legacy(owner, project_id, stranger_id, "viewer")
        after_grant = stranger.get("/api/projects")
        self.assertIn(project_id, [item["projectId"] for item in after_grant.json()["projects"]])

        self._revoke_legacy(owner, project_id, stranger_id)
        after_revoke = stranger.get("/api/projects")
        self.assertNotIn(project_id, [item["projectId"] for item in after_revoke.json()["projects"]])

    def test_legacy_and_modern_grant_endpoints_are_cross_recognized(self) -> None:
        # A grant made through the modern SharingService endpoint must be
        # visible through the legacy listing endpoint, and vice versa --
        # both now read/write the exact same permission table.
        owner, _owner_id = self._register("owner-i")
        stranger, stranger_id = self._register("stranger-j")
        project_id = self._create_project(owner, "FND-002 Cross-Recognition Project")

        # A pre-existing, out-of-scope-for-FND-002 SharingService quirk (not
        # introduced by this fix, and not touched by it -- see FND-002 report):
        # share_resource()'s project_collaborators sync has a hard FK on
        # users(user_id), so the target principal must have made at least one
        # authenticated request (which syncs their persistence user row) before
        # they can be the target of a project share. Registration alone does
        # not trigger that sync. This mirrors realistic sequencing.
        self.assertEqual(stranger.get("/api/auth/me").status_code, 200)

        self._share_modern(owner, project_id, stranger_id, "edit")
        self.assertEqual(stranger.put(f"/api/projects/{project_id}", json={"projectName": "via modern grant"}).status_code, 200)

        legacy_listing = owner.get(f"/api/projects/{project_id}/access")
        self.assertEqual(legacy_listing.status_code, 200)
        entries = legacy_listing.json()["access"]
        self.assertTrue(any(entry["user_id"] == stranger_id and entry["permission"] == "edit" for entry in entries))

        # Revoking through the legacy endpoint removes access granted through
        # the modern endpoint.
        self._revoke_legacy(owner, project_id, stranger_id)
        self.assertEqual(stranger.get(f"/api/projects/{project_id}").status_code, 403)

    def test_first_owner_self_grant_bootstrap_still_works(self) -> None:
        # Mirrors the live NewProject.tsx flow: the creator immediately
        # self-grants "owner" on their own brand-new project before any
        # permission record exists for it.
        owner, owner_id = self._register("owner-k")
        project_id = self._create_project(owner, "FND-002 Bootstrap Project")
        self._grant_legacy(owner, project_id, owner_id, "owner")

        get_response = owner.get(f"/api/projects/{project_id}")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(self._legacy_table_row_count(project_id), 0)

    def test_existing_fnd001_authorization_tests_still_pass(self) -> None:
        # A lightweight smoke check duplicated here (the full suite is run
        # separately in validation): an unrelated stranger must still be
        # denied and an unauthenticated caller must still get 401, not 403.
        owner, _owner_id = self._register("owner-l")
        stranger, _stranger_id = self._register("stranger-m")
        project_id = self._create_project(owner, "FND-002 FND-001 Smoke Project")

        self.assertEqual(stranger.get(f"/api/projects/{project_id}").status_code, 403)
        anonymous_client = TestClient(app)
        self.assertEqual(anonymous_client.get(f"/api/projects/{project_id}").status_code, 401)

    def test_no_production_code_path_independently_calls_the_legacy_acl_table(self) -> None:
        # Static-code assertion: outside of the CREATE TABLE statement that
        # intentionally keeps the legacy table in place for historical data,
        # no production module under server/ still reads or writes rows in
        # the legacy project_access table. scripts/migrate_legacy_project_access.py
        # is excluded -- it is the one-off, explicitly-authorized migration,
        # not a live authorization path.
        pattern = re.compile(r"(?:FROM|INTO|UPDATE)\s+project_access\b")
        offending: list[str] = []
        for path in SERVER_ROOT.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                offending.append(f"{path.relative_to(ROOT)}: {match.group(0)}")
        self.assertEqual(offending, [], f"Found live code still reading/writing the legacy ACL table: {offending}")


if __name__ == "__main__":
    unittest.main()

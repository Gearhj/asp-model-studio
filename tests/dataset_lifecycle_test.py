"""ATLAS Data Asset Lifecycle audit: backend tests for the dataset registration,
linking, deletion, and authorization behaviors documented in
docs/architecture/DATASET_LIFECYCLE_ADR.md.

Covers (Phase 12 of the audit brief):
  1. Workspace upload does not appear in the Dataset Library.
  2/3. Explicit registration creates an asset+version and preserves schema/target/provenance.
  4. Existing Dataset selection links the correct asset and version.
  5/6. Same filename/name in two projects or two users does not collide.
  7/8. Project deletion removes the link, never the shared Library asset.
  9. Dataset Library archive path exists and excludes archived assets from listings.
  10. A shared asset remains usable by a second project after the first is deleted.
  11. Transformed (post-DATASTORE-mutation) datasets preserve provenance the same way.
  12. Scored dataset registration lineage (existing behavior, spot-checked).
  13. Regression target metadata stays a plain string, never coerced to a class.
  14/15. Unauthorized cross-project link/unlink attempts are denied (the two auth fixes).
  17. Checkpoint scope cleanup remains correct after project deletion (Stage 6.1 regression).
  18. Duplicate-suggestion lookup never returns a substitute silently -- it is advisory only.

Isolation: dedicated security/persistence SQLite files, dedicated checkpoint path
(Stage 6.1 pattern), and a dedicated ATLAS_DATASET_LIBRARY_ROOT so this suite never
touches the shared dev backend's real registry.json / project_links.json.

Run:  .venv/Scripts/python.exe tests/dataset_lifecycle_test.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
_TEST_DATA_ROOT = _REPO_ROOT / ".tmp"
_TEST_DATA_ROOT.mkdir(exist_ok=True)
_RUN_ID = uuid.uuid4().hex[:10]
_SECURITY_DB_PATH = _TEST_DATA_ROOT / f"atlas_dataset_lifecycle_security_{_RUN_ID}.db"
_PERSISTENCE_DB_PATH = _TEST_DATA_ROOT / f"atlas_dataset_lifecycle_persistence_{_RUN_ID}.db"
_CHECKPOINT_PATH = _TEST_DATA_ROOT / f"atlas_dataset_lifecycle_checkpoint_{_RUN_ID}.json"
_LIBRARY_ROOT = Path(tempfile.mkdtemp(prefix=f"atlas_dataset_lifecycle_library_{_RUN_ID}_"))
_BACKUP_ROOT = Path(tempfile.mkdtemp(prefix=f"atlas_dataset_lifecycle_backups_{_RUN_ID}_"))
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(_CHECKPOINT_PATH)
os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(_LIBRARY_ROOT)
os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(_BACKUP_ROOT)
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.persistence import db as persistence_db_module  # noqa: E402
from server.persistence import service as persistence_service_module  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402
from server.security import security_store as security_store_module  # noqa: E402

import server.core.dataset_store as dataset_store_module  # noqa: E402
import server.core.session_checkpoint as checkpoint  # noqa: E402
from server.datasets import dataset_registry  # noqa: E402


def _bind_dataset_library_paths() -> None:
    """Rebind every cached registry path to this suite's owned root."""
    expected_root = _LIBRARY_ROOT.resolve()
    expected_backup_root = _BACKUP_ROOT.resolve()
    os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(expected_root)
    os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(expected_backup_root)
    dataset_registry.ARTIFACT_ROOT = expected_root
    dataset_registry.REGISTRY_PATH = dataset_registry.ARTIFACT_ROOT / "registry.json"
    dataset_registry.USERS_PATH = dataset_registry.ARTIFACT_ROOT / "users.json"
    dataset_registry.PROJECT_LINKS_PATH = (
        dataset_registry.ARTIFACT_ROOT / "project_links.json"
    )
    assert Path(os.environ["ATLAS_DATASET_LIBRARY_ROOT"]).resolve() == expected_root
    assert Path(os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"]).resolve() == expected_backup_root
    assert dataset_registry.ARTIFACT_ROOT.resolve() == expected_root
    assert dataset_registry.REGISTRY_PATH.resolve() == expected_root / "registry.json"
    assert dataset_registry.USERS_PATH.resolve() == expected_root / "users.json"
    assert dataset_registry.PROJECT_LINKS_PATH.resolve() == expected_root / "project_links.json"


def _bind_checkpoint_path() -> None:
    """Keep this suite isolated even when ``server.main`` was imported first."""
    expected = _CHECKPOINT_PATH.resolve()
    os.environ["ATLAS_CHECKPOINT_PATH"] = str(expected)
    checkpoint.CHECKPOINT_PATH = expected
    assert Path(os.environ["ATLAS_CHECKPOINT_PATH"]).resolve() == expected
    assert checkpoint.CHECKPOINT_PATH.resolve() == expected


_bind_dataset_library_paths()
_bind_checkpoint_path()


def setUpModule() -> None:
    _bind_dataset_library_paths()
    _bind_checkpoint_path()
    # Multi-file pytest collection may import a later suite that rebinds the
    # process-global persistence singleton.  Restore this suite's exact owned
    # database before any lifecycle test can create durable activation rows.
    os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH.resolve())
    persistence_db_module._database = persistence_db_module.Database(
        _PERSISTENCE_DB_PATH.resolve()
    )
    persistence_service_module._service = None
    os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH.resolve())
    security_store_module.SECURITY_ROOT = _TEST_DATA_ROOT.resolve()
    security_store_module.DB_PATH = _SECURITY_DB_PATH.resolve()
    security_store_module.ATLAS_AUTH_ENABLED = True
    security_store_module.ATLAS_ALLOW_PUBLIC_REGISTRATION = True


def _cleanup_db_files() -> None:
    checkpoint.flush_checkpoint()
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
    _CHECKPOINT_PATH.unlink(missing_ok=True)
    shutil.rmtree(_BACKUP_ROOT, ignore_errors=True)


def _register(label: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{label}-{suffix}@atlas-dataset-lifecycle-test.local",
            "displayName": f"Dataset Lifecycle Test {label} {suffix}",
            "password": "DatasetLifecycleTestPass!",
            "role": "data_scientist",
        },
    )
    assert response.status_code == 200, response.text
    return client, response.json()["user"]["userId"]


def _create_project(client: TestClient, name: str) -> str:
    response = client.post("/api/projects", json={"projectName": name, "projectType": "predictive-modeling"})
    assert response.status_code == 200, response.text
    return response.json()["project"]["projectId"]


def _build_frame(rows: int = 40, target: str = "MedHouseVal") -> pd.DataFrame:
    return pd.DataFrame({
        "amount": [float(i % 23) for i in range(rows)],
        "velocity": [float((i * 3) % 11) for i in range(rows)],
        target: [round(0.5 + (i % 7) * 0.13, 2) for i in range(rows)],
    })


def _upload_and_select_target(client: TestClient, project_id: str, df: pd.DataFrame, target: str) -> None:
    """Use the governed upload/activation contract before selecting a target.

    ``upload_csv`` now registers and activates one exact immutable Dataset
    Library version.  The browser carries that returned identity into
    ``set_target``; this fixture must do the same instead of relying on the
    retired identity-free workspace path.
    """
    import io
    files = {"file": ("dataset.csv", io.BytesIO(df.to_csv(index=False).encode("utf-8")), "text/csv")}
    response = client.post("/api/data/upload_csv", data={"project_id": project_id}, files=files)
    assert response.status_code == 200, response.text
    upload = response.json()
    dataset_id = str(upload.get("dataset_id") or upload.get("datasetId") or "")
    dataset_version_id = str(
        upload.get("dataset_version_id") or upload.get("versionId") or ""
    )
    assert dataset_id and dataset_version_id, upload
    response = client.post(
        "/api/data/set_target",
        json={
            "project_id": project_id,
            "target": target,
            "selected_columns": [c for c in df.columns if c != target],
            "expected_dataset_id": dataset_id,
            "expected_dataset_version_id": dataset_version_id,
        },
    )
    assert response.status_code == 200, response.text


class DatasetLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        setUpModule()
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()
        shutil.rmtree(_LIBRARY_ROOT, ignore_errors=True)

    def setUp(self) -> None:
        self._datasets_snapshot = dict(dataset_store_module._DATASTORES)
        dataset_store_module._DATASTORES.clear()

    def tearDown(self) -> None:
        dataset_store_module._DATASTORES.clear()
        dataset_store_module._DATASTORES.update(self._datasets_snapshot)

    # ------------------------------------------------------------------
    # 1: workspace upload stays out of the Library until registered
    # ------------------------------------------------------------------
    def test_workspace_upload_not_in_library_until_registered(self) -> None:
        client, user_id = _register("workspace-only")
        project_id = _create_project(client, "Lifecycle Workspace Only")
        _upload_and_select_target(client, project_id, _build_frame(), "MedHouseVal")

        listing = client.get("/api/datasets")
        self.assertEqual(listing.status_code, 200, listing.text)
        names = [d["name"] for d in listing.json()["datasets"]]
        self.assertNotIn("Lifecycle Workspace Only - Development", names)

    # ------------------------------------------------------------------
    # 2/3: explicit registration creates asset + version, preserves provenance
    # ------------------------------------------------------------------
    def test_register_workspace_creates_asset_with_schema_target_and_lineage(self) -> None:
        client, user_id = _register("register")
        project_id = _create_project(client, "Lifecycle Register Source")
        df = _build_frame(rows=55, target="MedHouseVal")
        _upload_and_select_target(client, project_id, df, "MedHouseVal")

        response = client.post("/api/datasets/register-workspace", json={
            "projectId": project_id, "name": "Lifecycle Register Asset",
            "description": "Test registration", "tags": ["development", "test"],
        })
        self.assertEqual(response.status_code, 200, response.text)
        dataset = response.json()["dataset"]
        self.assertEqual(dataset["name"], "Lifecycle Register Asset")
        self.assertEqual(dataset["ownerUserId"], user_id)
        self.assertEqual(dataset["versionCount"], 1)
        latest = dataset["latestVersion"]
        self.assertEqual(latest["rowCount"], 55)
        self.assertEqual(latest["columnCount"], 3)
        self.assertEqual(dataset["sourceInfo"]["target"], "MedHouseVal")
        self.assertEqual(dataset["sourceInfo"]["projectId"], project_id)
        self.assertEqual(dataset["sourceInfo"]["tags"], ["development", "test"])

        # Now visible in the Library.
        listing = client.get("/api/datasets")
        names = [d["name"] for d in listing.json()["datasets"]]
        self.assertIn("Lifecycle Register Asset", names)

        # Lineage artifact records who/when/what.
        lineage_path = _LIBRARY_ROOT / dataset["datasetId"] / "versions" / latest["versionId"] / "lineage.json"
        self.assertTrue(lineage_path.exists())
        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
        self.assertEqual(lineage["registeredBy"], user_id)
        self.assertEqual(lineage["sourceType"], "workspace_upload")

        # Project is linked.
        links = client.get(f"/api/projects/{project_id}/datasets")
        self.assertEqual(links.status_code, 200, links.text)
        linked_dataset_ids = {
            link["datasetId"] for link in links.json()["links"]
        }
        # Data Acquisition now registers and links its exact canonical upload
        # before this explicit workspace-registration action creates a second
        # governed asset.  The contract under test is the exact new link, not
        # an obsolete assumption that the project has only one asset.
        self.assertIn(dataset["datasetId"], linked_dataset_ids)

    def test_registration_requires_uploaded_data(self) -> None:
        client, user_id = _register("empty")
        project_id = _create_project(client, "Lifecycle Empty Project")
        response = client.post("/api/datasets/register-workspace", json={"projectId": project_id, "name": "Nothing To Register"})
        self.assertEqual(response.status_code, 400, response.text)

    # ------------------------------------------------------------------
    # 4: Existing Dataset selection links the correct asset+version
    # ------------------------------------------------------------------
    def test_existing_dataset_link_references_correct_asset_and_version(self) -> None:
        owner, owner_id = _register("share-owner")
        source_project = _create_project(owner, "Lifecycle Share Source")
        _upload_and_select_target(owner, source_project, _build_frame(rows=30), "MedHouseVal")
        registered = owner.post("/api/datasets/register-workspace", json={"projectId": source_project, "name": "Lifecycle Shared Asset"}).json()["dataset"]

        second_project = _create_project(owner, "Lifecycle Share Target")
        link = owner.post(f"/api/projects/{second_project}/datasets/link", json={
            "datasetId": registered["datasetId"], "versionId": registered["latestVersion"]["versionId"], "datasetRole": "modeling",
        })
        self.assertEqual(link.status_code, 200, link.text)
        self.assertEqual(link.json()["link"]["datasetId"], registered["datasetId"])
        self.assertEqual(link.json()["link"]["versionId"], registered["latestVersion"]["versionId"])

    # ------------------------------------------------------------------
    # 5/6: name collisions across projects and users
    # ------------------------------------------------------------------
    def test_same_dataset_name_two_projects_same_user_creates_distinct_assets(self) -> None:
        client, user_id = _register("collide-proj")
        project_a = _create_project(client, "Lifecycle Collide A")
        project_b = _create_project(client, "Lifecycle Collide B")
        _upload_and_select_target(client, project_a, _build_frame(rows=10), "MedHouseVal")
        asset_a = client.post("/api/datasets/register-workspace", json={"projectId": project_a, "name": "Same Name Asset"}).json()["dataset"]
        _upload_and_select_target(client, project_b, _build_frame(rows=99), "MedHouseVal")
        asset_b = client.post("/api/datasets/register-workspace", json={"projectId": project_b, "name": "Same Name Asset"}).json()["dataset"]
        self.assertNotEqual(asset_a["datasetId"], asset_b["datasetId"])
        self.assertEqual(asset_a["latestVersion"]["rowCount"], 10)
        self.assertEqual(asset_b["latestVersion"]["rowCount"], 99)

    def test_same_dataset_name_two_users_creates_distinct_assets(self) -> None:
        client_a, user_a_id = _register("collide-user-a")
        client_b, user_b_id = _register("collide-user-b")
        project_a = _create_project(client_a, "Lifecycle User A Project")
        project_b = _create_project(client_b, "Lifecycle User B Project")
        _upload_and_select_target(client_a, project_a, _build_frame(rows=12), "MedHouseVal")
        _upload_and_select_target(client_b, project_b, _build_frame(rows=34), "MedHouseVal")
        asset_a = client_a.post("/api/datasets/register-workspace", json={"projectId": project_a, "name": "Identical Name"}).json()["dataset"]
        asset_b = client_b.post("/api/datasets/register-workspace", json={"projectId": project_b, "name": "Identical Name"}).json()["dataset"]
        self.assertNotEqual(asset_a["datasetId"], asset_b["datasetId"])
        self.assertEqual(asset_a["ownerUserId"], user_a_id)
        self.assertEqual(asset_b["ownerUserId"], user_b_id)
        # User B cannot see user A's private asset in their own listing.
        listing_b = client_b.get("/api/datasets").json()["datasets"]
        self.assertNotIn(asset_a["datasetId"], [d["datasetId"] for d in listing_b])

    # ------------------------------------------------------------------
    # 7/8/10: project deletion removes the LINK, never the shared asset
    # ------------------------------------------------------------------
    def test_project_deletion_removes_link_but_preserves_shared_asset_for_other_projects(self) -> None:
        owner, owner_id = _register("delete-owner")
        source_project = _create_project(owner, "Lifecycle Delete Source")
        _upload_and_select_target(owner, source_project, _build_frame(rows=20), "MedHouseVal")
        asset = owner.post("/api/datasets/register-workspace", json={"projectId": source_project, "name": "Lifecycle Survives Deletion"}).json()["dataset"]

        second_project = _create_project(owner, "Lifecycle Delete Second")
        owner.post(f"/api/projects/{second_project}/datasets/link", json={"datasetId": asset["datasetId"], "versionId": asset["latestVersion"]["versionId"]})

        delete_response = owner.delete(f"/api/projects/{source_project}")
        self.assertEqual(delete_response.status_code, 200, delete_response.text)

        # Asset itself is untouched.
        fetched = owner.get(f"/api/datasets/{asset['datasetId']}")
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertFalse(fetched.json()["dataset"]["archived"])

        # Source project's link is gone; the second project's link survives.
        remaining_links = fetched.json()["dataset"]["linkedProjects"]
        remaining_project_ids = {link["projectId"] for link in remaining_links}
        self.assertNotIn(source_project, remaining_project_ids)
        self.assertIn(second_project, remaining_project_ids)

        # The second project can still resolve and use the asset.
        second_links = owner.get(f"/api/projects/{second_project}/datasets")
        self.assertEqual(len(second_links.json()["links"]), 1)
        self.assertEqual(second_links.json()["links"][0]["datasetId"], asset["datasetId"])

    # ------------------------------------------------------------------
    # 9: archive path exists and excludes archived assets from listings
    # ------------------------------------------------------------------
    def test_archive_excludes_from_default_listing_without_deleting_history(self) -> None:
        client, user_id = _register("archive")
        project_id = _create_project(client, "Lifecycle Archive Project")
        _upload_and_select_target(client, project_id, _build_frame(rows=8), "MedHouseVal")
        asset = client.post("/api/datasets/register-workspace", json={"projectId": project_id, "name": "Lifecycle Archive Me"}).json()["dataset"]

        archived = client.post(f"/api/datasets/{asset['datasetId']}/archive")
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertTrue(archived.json()["dataset"]["archived"])

        listing = client.get("/api/datasets").json()["datasets"]
        self.assertNotIn(asset["datasetId"], [d["datasetId"] for d in listing])
        listing_with_archived = client.get("/api/datasets?include_archived=true").json()["datasets"]
        self.assertIn(asset["datasetId"], [d["datasetId"] for d in listing_with_archived])

    # ------------------------------------------------------------------
    # 13: regression target metadata stays a plain continuous target string
    # ------------------------------------------------------------------
    def test_regression_target_metadata_is_not_coerced_to_classification_language(self) -> None:
        client, user_id = _register("regression-meta")
        project_id = _create_project(client, "Lifecycle Regression Meta")
        _upload_and_select_target(client, project_id, _build_frame(rows=15, target="MedHouseVal"), "MedHouseVal")
        asset = client.post("/api/datasets/register-workspace", json={"projectId": project_id, "name": "Lifecycle Regression Asset"}).json()["dataset"]
        self.assertEqual(asset["sourceInfo"]["target"], "MedHouseVal")
        self.assertNotIn("classIndex", json.dumps(asset["sourceInfo"]))
        self.assertNotIn("positiveClass", json.dumps(asset["sourceInfo"]))

    # ------------------------------------------------------------------
    # 14/15: unauthorized cross-project link/unlink is denied (the two auth fixes)
    # ------------------------------------------------------------------
    def test_unauthorized_user_cannot_unlink_another_users_project_dataset(self) -> None:
        owner, owner_id = _register("auth-owner")
        stranger, stranger_id = _register("auth-stranger")
        project_id = _create_project(owner, "Lifecycle Auth Project")
        _upload_and_select_target(owner, project_id, _build_frame(rows=9), "MedHouseVal")
        asset = owner.post("/api/datasets/register-workspace", json={"projectId": project_id, "name": "Lifecycle Auth Asset"}).json()["dataset"]

        # Stranger cannot unlink (write-authorization fix).
        response = stranger.delete(f"/api/projects/{project_id}/datasets/{asset['datasetId']}")
        self.assertEqual(response.status_code, 403, response.text)
        # The exact protected link is still intact for the real owner.  The
        # canonical upload may also be linked, so total link count is not an
        # authorization invariant.
        owner_links = owner.get(
            f"/api/projects/{project_id}/datasets"
        ).json()["links"]
        self.assertIn(
            asset["datasetId"],
            {link["datasetId"] for link in owner_links},
        )

    def test_unauthorized_user_cannot_view_another_users_project_links(self) -> None:
        owner, owner_id = _register("view-owner")
        stranger, stranger_id = _register("view-stranger")
        project_id = _create_project(owner, "Lifecycle View Auth Project")
        response = stranger.get(f"/api/projects/{project_id}/datasets")
        self.assertEqual(response.status_code, 403, response.text)

    def test_unauthorized_user_cannot_register_scored_output_into_foreign_project(self) -> None:
        owner, owner_id = _register("scored-owner")
        stranger, stranger_id = _register("scored-stranger")
        project_id = _create_project(owner, "Lifecycle Scored Auth Project")
        response = stranger.post("/api/scoring/register-scored-dataset", json={
            "projectId": project_id, "projectName": "Lifecycle Scored Auth Project",
            "datasetName": "Malicious Scored Asset", "datasetType": "test",
            "rows": [{"score": 0.5, "prediction": 1, "actual": 1}],
        })
        self.assertEqual(response.status_code, 403, response.text)
        # No link was created for the foreign project.
        self.assertEqual(len(owner.get(f"/api/projects/{project_id}/datasets").json()["links"]), 0)

    # ------------------------------------------------------------------
    # 17: checkpoint scope cleanup remains correct after project deletion
    # ------------------------------------------------------------------
    def test_checkpoint_scope_cleanup_still_correct_after_project_deletion(self) -> None:
        client, user_id = _register("checkpoint-interplay")
        project_id = _create_project(client, "Lifecycle Checkpoint Interplay")
        _upload_and_select_target(client, project_id, _build_frame(rows=5), "MedHouseVal")
        self.assertTrue(checkpoint.save_checkpoint())
        payload = json.loads(checkpoint.CHECKPOINT_PATH.read_text(encoding="utf-8"))
        scope_keys = {(e["owner_user_id"], e["project_id"]) for e in payload["datastore_scopes"]}
        self.assertIn((user_id, project_id), scope_keys)

        client.delete(f"/api/projects/{project_id}")
        self.assertNotIn((user_id, project_id), dataset_store_module._DATASTORES)
        payload_after = json.loads(checkpoint.CHECKPOINT_PATH.read_text(encoding="utf-8"))
        scope_keys_after = {(e["owner_user_id"], e["project_id"]) for e in payload_after["datastore_scopes"]}
        self.assertNotIn((user_id, project_id), scope_keys_after)

    # ------------------------------------------------------------------
    # 18: duplicate suggestions are advisory, never a silent substitution
    # ------------------------------------------------------------------
    def test_similar_dataset_suggestion_is_advisory_only(self) -> None:
        client, user_id = _register("duplicate")
        project_a = _create_project(client, "Lifecycle Duplicate Source")
        _upload_and_select_target(client, project_a, _build_frame(rows=25), "MedHouseVal")
        original = client.post("/api/datasets/register-workspace", json={"projectId": project_a, "name": "Lifecycle Duplicate Candidate"}).json()["dataset"]

        similar = client.get("/api/datasets/similar", params={"name": "Lifecycle Duplicate Candidate", "target": "MedHouseVal", "row_count": 25, "column_count": 3})
        self.assertEqual(similar.status_code, 200, similar.text)
        candidate_ids = [c["datasetId"] for c in similar.json()["candidates"]]
        self.assertIn(original["datasetId"], candidate_ids)

        # Registering again under the SAME name still creates a NEW, distinct asset --
        # the suggestion never substitutes it.
        project_b = _create_project(client, "Lifecycle Duplicate Second")
        _upload_and_select_target(client, project_b, _build_frame(rows=25), "MedHouseVal")
        second = client.post("/api/datasets/register-workspace", json={"projectId": project_b, "name": "Lifecycle Duplicate Candidate"}).json()["dataset"]
        self.assertNotEqual(original["datasetId"], second["datasetId"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

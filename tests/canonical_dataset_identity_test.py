"""Phase 2A regression coverage for canonical Dataset Library identity.

This suite is intentionally isolated from every checked-in/runtime ATLAS store.
It owns temporary security/persistence databases, a temporary workflow checkpoint,
and a temporary Dataset Library artifact root.

Run:
    .venv/Scripts/python.exe tests/canonical_dataset_identity_test.py
"""
from __future__ import annotations

import atexit
import io
import os
import shutil
import sys
import time
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict


_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
_TEST_DATA_PARENT = _REPO_ROOT / ".tmp"
_TEST_DATA_PARENT.mkdir(exist_ok=True)
_TEST_DATA_ROOT = (
    _TEST_DATA_PARENT / f"atlas_canonical_identity_{uuid.uuid4().hex}"
)
_TEST_DATA_ROOT.mkdir(parents=True, exist_ok=False)
_SECURITY_DB_PATH = _TEST_DATA_ROOT / "security.db"
_PERSISTENCE_DB_PATH = _TEST_DATA_ROOT / "persistence.db"
_CHECKPOINT_PATH = _TEST_DATA_ROOT / "workflow_checkpoint.json"
_LIBRARY_ROOT = _TEST_DATA_ROOT / "dataset_library"
_LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)

_ENVIRONMENT_OVERRIDES = {
    "ATLAS_SECURITY_DB_PATH": str(_SECURITY_DB_PATH),
    "ATLAS_SQLITE_PATH": str(_PERSISTENCE_DB_PATH),
    "ATLAS_CHECKPOINT_PATH": str(_CHECKPOINT_PATH),
    "ATLAS_DATASET_LIBRARY_ROOT": str(_LIBRARY_ROOT),
    "ATLAS_AUTH_ENABLED": os.environ.get("ATLAS_AUTH_ENABLED", "true"),
    "ATLAS_ALLOW_PUBLIC_REGISTRATION": "true",
}
_ORIGINAL_ENVIRONMENT = {
    key: os.environ.get(key) for key in _ENVIRONMENT_OVERRIDES
}
os.environ.update(_ENVIRONMENT_OVERRIDES)

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402
import server.core.dataset_store as dataset_store_module  # noqa: E402
import server.core.result_store as result_store_module  # noqa: E402
import server.core.session_checkpoint as checkpoint  # noqa: E402
from server.core.dataset_store import get_scoped_dataset_store  # noqa: E402
from server.datasets import dataset_registry  # noqa: E402


ACCESS_METADATA_ID = "20260729212115-f471e706"
_CLIENTS: list[TestClient] = []


def _cleanup() -> None:
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


def _cleanup_process_state() -> None:
    for client in list(_CLIENTS):
        client.close()
    _CLIENTS.clear()
    _cleanup()
    shutil.rmtree(_TEST_DATA_ROOT, ignore_errors=True)
    for key, value in _ORIGINAL_ENVIRONMENT.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


atexit.register(_cleanup_process_state)


def _register_client(label: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    _CLIENTS.append(client)
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{label}-{suffix}@atlas-canonical-identity-test.local",
            "displayName": f"Canonical Identity Test {label} {suffix}",
            "password": "CanonicalIdentityTestPass!1",
            "role": "data_scientist",
        },
    )
    assert response.status_code == 200, response.text
    return client, response.json()["user"]["userId"]


def _create_project(client: TestClient, name: str) -> str:
    response = client.post(
        "/api/projects",
        json={"projectName": name, "projectType": "predictive-modeling"},
    )
    assert response.status_code == 200, response.text
    return response.json()["project"]["projectId"]


def _csv_bytes() -> bytes:
    rows = list(range(40))
    frame = pd.DataFrame(
        {
            # Repeated predictor levels map to both outcomes, so the governed
            # target-source detector correctly keeps them as predictors.
            "predictor_a": [float(value % 10) for value in rows],
            "predictor_b": [float((value * 3) % 7) for value in rows],
            "bad_flag": [(value // 10) % 2 for value in rows],
        }
    )
    return frame.to_csv(index=False).encode("utf-8")


def _register_link_activate(
    client: TestClient,
    project_id: str,
    *,
    name: str = "Canonical Identity Asset",
) -> tuple[str, str]:
    upload = client.post(
        "/api/datasets/upload",
        files={"file": (f"{name}.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        data={"name": name, "description": "Phase 2A regression asset"},
    )
    assert upload.status_code == 200, upload.text
    dataset = upload.json()["dataset"]
    dataset_id = dataset["datasetId"]
    version_id = dataset["created_dataset_version_id"]
    link = client.post(
        f"/api/projects/{project_id}/datasets/link",
        json={
            "datasetId": dataset_id,
            "versionId": version_id,
            "datasetRole": "modeling",
        },
    )
    assert link.status_code == 200, link.text
    activation = client.post(
        f"/api/datasets/{dataset_id}/versions/{version_id}/activate",
        params={"project_id": project_id},
    )
    assert activation.status_code == 200, activation.text
    return dataset_id, version_id


def _configure_target(
    client: TestClient,
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    **extra: object,
) -> Dict[str, Any]:
    response = client.post(
        "/api/data/set_target",
        json={
            "project_id": project_id,
            "target": "bad_flag",
            "selected_columns": ["predictor_a", "predictor_b"],
            "expected_dataset_id": dataset_id,
            "expected_dataset_version_id": dataset_version_id,
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


class CanonicalDatasetIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _cleanup()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_process_state()

    def setUp(self) -> None:
        self._datasets_snapshot = dict(dataset_store_module._DATASTORES)
        self._results_snapshot = dict(result_store_module._RESULT_STORES)
        dataset_store_module._DATASTORES.clear()
        result_store_module._RESULT_STORES.clear()

    def tearDown(self) -> None:
        checkpoint.flush_checkpoint()
        dataset_store_module._DATASTORES.clear()
        dataset_store_module._DATASTORES.update(self._datasets_snapshot)
        result_store_module._RESULT_STORES.clear()
        result_store_module._RESULT_STORES.update(self._results_snapshot)

    def test_registered_version_survives_target_configuration(self) -> None:
        client, user_id = _register_client("survives-target")
        project_id = _create_project(client, "Canonical Identity Target Project")
        dataset_id, registered_version_id = _register_link_activate(client, project_id)

        target = _configure_target(
            client,
            project_id,
            dataset_id,
            registered_version_id,
            access_metadata_id=ACCESS_METADATA_ID,
        )
        self.assertEqual(target["dataset_version_id"], registered_version_id)

        store = get_scoped_dataset_store((user_id, project_id))
        self.assertEqual(store.meta.get("dataset_id"), dataset_id)
        self.assertEqual(
            store.meta.get("dataset_version_id"),
            registered_version_id,
            "Target persistence must not replace the activated immutable version.",
        )
        self.assertNotEqual(store.meta.get("dataset_version_id"), ACCESS_METADATA_ID)

    def test_access_and_profile_metadata_cannot_overwrite_version(self) -> None:
        client, user_id = _register_client("metadata-separated")
        project_id = _create_project(client, "Canonical Metadata Separation")
        dataset_id, version_id = _register_link_activate(client, project_id)

        _configure_target(
            client,
            project_id,
            dataset_id,
            version_id,
            access_metadata_id=ACCESS_METADATA_ID,
            profile_snapshot_id="profile-snapshot-001",
        )
        store = get_scoped_dataset_store((user_id, project_id))
        self.assertEqual(store.meta["dataset_version_id"], version_id)
        self.assertEqual(store.meta["access_metadata_id"], ACCESS_METADATA_ID)
        self.assertEqual(store.meta["profile_snapshot_id"], "profile-snapshot-001")

        contradictory = client.post(
            "/api/data/set_target",
            json={
                "project_id": project_id,
                "target": "bad_flag",
                "selected_columns": ["predictor_a", "predictor_b"],
                "expected_dataset_id": dataset_id,
                "expected_dataset_version_id": version_id,
                "dataset_version": ACCESS_METADATA_ID,
            },
        )
        self.assertEqual(contradictory.status_code, 409, contradictory.text)
        self.assertEqual(store.meta["dataset_version_id"], version_id)

    def test_dataset_version_mismatch_fails_closed(self) -> None:
        client, user_id = _register_client("mismatch")
        project_id = _create_project(client, "Canonical Mismatch Project")
        dataset_id, version_id = _register_link_activate(client, project_id)

        response = client.post(
            "/api/data/set_target",
            json={
                "project_id": project_id,
                "target": "bad_flag",
                "selected_columns": ["predictor_a"],
                "expected_dataset_id": dataset_id,
                "expected_dataset_version_id": "v_registered_wrong",
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        store = get_scoped_dataset_store((user_id, project_id))
        self.assertEqual(store.meta["dataset_version_id"], version_id)
        self.assertIsNone(store.target)

    def test_unknown_version_fails_closed(self) -> None:
        client, _user_id = _register_client("unknown-version")
        project_id = _create_project(client, "Canonical Unknown Version Project")
        dataset_id, _version_id = _register_link_activate(client, project_id)

        response = client.post(
            f"/api/datasets/{dataset_id}/versions/v_missing_001/activate",
            params={"project_id": project_id},
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_version_belonging_to_another_dataset_fails_closed(self) -> None:
        client, _user_id = _register_client("cross-dataset-version")
        project_id = _create_project(client, "Canonical Cross Dataset Project")
        first_dataset_id, _first_version_id = _register_link_activate(
            client,
            project_id,
            name="Canonical First Asset",
        )
        second_project_id = _create_project(client, "Canonical Second Asset Project")
        _second_dataset_id, second_version_id = _register_link_activate(
            client,
            second_project_id,
            name="Canonical Second Asset",
        )

        response = client.post(
            f"/api/projects/{project_id}/datasets/link",
            json={
                "datasetId": first_dataset_id,
                "versionId": second_version_id,
                "datasetRole": "modeling",
            },
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_unauthorized_project_version_combination_fails_closed(self) -> None:
        owner_client, _owner_id = _register_client("dataset-owner")
        owner_project_id = _create_project(owner_client, "Canonical Owner Project")
        dataset_id, version_id = _register_link_activate(
            owner_client,
            owner_project_id,
            name="Owner Private Asset",
        )
        other_client, _other_id = _register_client("unauthorized-user")
        other_project_id = _create_project(other_client, "Unauthorized Project")

        link = other_client.post(
            f"/api/projects/{other_project_id}/datasets/link",
            json={
                "datasetId": dataset_id,
                "versionId": version_id,
                "datasetRole": "modeling",
            },
        )
        self.assertEqual(link.status_code, 403, link.text)
        activation = other_client.post(
            f"/api/datasets/{dataset_id}/versions/{version_id}/activate",
            params={"project_id": other_project_id},
        )
        self.assertIn(activation.status_code, {403, 409}, activation.text)

    def test_checkpoint_save_and_restore_preserve_exact_version(self) -> None:
        client, user_id = _register_client("checkpoint-exact")
        project_id = _create_project(client, "Canonical Checkpoint Project")
        dataset_id, version_id = _register_link_activate(client, project_id)
        _configure_target(client, project_id, dataset_id, version_id)

        self.assertTrue(checkpoint.flush_checkpoint())
        dataset_store_module._DATASTORES.clear()
        result_store_module._RESULT_STORES.clear()
        self.assertTrue(checkpoint.load_checkpoint())

        restored = get_scoped_dataset_store((user_id, project_id))
        self.assertEqual(restored.meta["project_id"], project_id)
        self.assertEqual(restored.meta["dataset_id"], dataset_id)
        self.assertEqual(restored.meta["dataset_version_id"], version_id)
        self.assertEqual(restored.meta["dataset_identity_status"], "current")
        self.assertEqual(len(restored.raw_df), 40)

    def test_checkpoint_restore_never_falls_back_to_another_version(self) -> None:
        client, user_id = _register_client("checkpoint-no-fallback")
        project_id = _create_project(client, "Canonical No Fallback Project")
        dataset_id, activated_version_id = _register_link_activate(
            client,
            project_id,
            name="Canonical Versioned Asset",
        )
        second = client.post(
            f"/api/datasets/{dataset_id}/versions",
            files={
                "file": (
                    "Canonical Versioned Asset v2.csv",
                    io.BytesIO(_csv_bytes()),
                    "text/csv",
                )
            },
        )
        self.assertEqual(second.status_code, 200, second.text)
        second_version_id = second.json()["version"]["versionId"]
        self.assertNotEqual(second_version_id, activated_version_id)
        _configure_target(
            client,
            project_id,
            dataset_id,
            activated_version_id,
        )
        self.assertTrue(checkpoint.flush_checkpoint())

        registry = dataset_registry.load_registry()
        for dataset in registry["datasets"]:
            if dataset.get("datasetId") == dataset_id:
                dataset["versions"] = [
                    version
                    for version in dataset.get("versions", [])
                    if version.get("versionId") != activated_version_id
                ]
        dataset_registry.save_registry(registry)

        dataset_store_module._DATASTORES.clear()
        result_store_module._RESULT_STORES.clear()
        self.assertTrue(checkpoint.load_checkpoint())
        restored = get_scoped_dataset_store((user_id, project_id))
        self.assertEqual(restored.meta["dataset_version_id"], activated_version_id)
        self.assertNotEqual(restored.meta["dataset_version_id"], second_version_id)
        self.assertEqual(restored.meta["dataset_identity_status"], "invalid")
        self.assertIsNone(restored.raw_df)

    def test_new_upload_is_registered_linked_and_activated_first(self) -> None:
        client, user_id = _register_client("registered-upload")
        project_id = _create_project(client, "Canonical Registered Upload Project")
        response = client.post(
            "/api/data/upload_csv",
            files={
                "file": (
                    "Canonical Upload.csv",
                    io.BytesIO(_csv_bytes()),
                    "text/csv",
                )
            },
            data={"project_id": project_id},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        dataset_id = payload["dataset_id"]
        version_id = payload["dataset_version_id"]
        self.assertTrue(dataset_id)
        self.assertTrue(version_id)

        registered = next(
            dataset
            for dataset in dataset_registry.load_registry()["datasets"]
            if dataset["datasetId"] == dataset_id
        )
        self.assertIn(
            version_id,
            [version["versionId"] for version in registered["versions"]],
        )
        self.assertTrue(
            any(
                link.get("projectId") == project_id
                and link.get("datasetId") == dataset_id
                and link.get("versionId") == version_id
                for link in dataset_registry.load_links()["links"]
            )
        )
        store = get_scoped_dataset_store((user_id, project_id))
        self.assertEqual(store.meta["dataset_version_id"], version_id)
        self.assertEqual(store.meta["dataset_identity_status"], "current")

    def test_pretraining_records_retain_the_same_canonical_version(self) -> None:
        client, user_id = _register_client("pretraining")
        project_id = _create_project(client, "Canonical Pretraining Project")
        dataset_id, version_id = _register_link_activate(client, project_id)
        _configure_target(client, project_id, dataset_id, version_id)
        expected = {
            "expected_dataset_id": dataset_id,
            "expected_dataset_version_id": version_id,
        }

        outlier_summary = client.post(
            "/api/outliers/summary",
            json={
                "project_id": project_id,
                "target": "bad_flag",
                "problem_type": "classification",
                **expected,
            },
        )
        self.assertEqual(outlier_summary.status_code, 200, outlier_summary.text)
        self.assertEqual(outlier_summary.json()["dataset_version_id"], version_id)
        outlier_apply = client.post(
            "/api/outliers/apply",
            json={
                "project_id": project_id,
                "target": "bad_flag",
                "problem_type": "classification",
                "global_method": "IQR_1_5",
                "config": {
                    "predictor_a": "USE_GLOBAL",
                    "predictor_b": "USE_GLOBAL",
                },
                "acknowledged_high_impact": True,
                **expected,
            },
        )
        self.assertEqual(outlier_apply.status_code, 200, outlier_apply.text)
        self.assertEqual(
            outlier_apply.json()["application"]["dataset_version_id"],
            version_id,
        )

        missing_validate = client.post(
            "/api/missing/validate",
            json={
                "project_id": project_id,
                "problem_type": "classification",
                **expected,
            },
        )
        self.assertEqual(missing_validate.status_code, 200, missing_validate.text)
        self.assertEqual(
            missing_validate.json()["validation"]["dataset_version_id"],
            version_id,
        )

        manifest_response = client.post(
            "/api/features/manifest",
            json={
                "project_id": project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": version_id,
                "features": [],
                "pipeline_steps": [],
            },
        )
        self.assertEqual(manifest_response.status_code, 200, manifest_response.text)
        manifest = manifest_response.json()
        self.assertEqual(manifest["dataset_version_id"], version_id)

        split_response = client.post(
            "/api/balancing_split/config",
            json={
                "project_id": project_id,
                "split_strategy": "holdout",
                "test_size": 0.2,
                "random_seed": 42,
                "stratify": True,
                "balance_method": "none",
                "problem_type": "classification",
                "event_value": 1,
                "selected_features": ["predictor_a", "predictor_b"],
                "feature_manifest_version": manifest["manifest_version"],
                "dataset_id": dataset_id,
                "dataset_version_id": version_id,
                "development_dataset_id": dataset_id,
                "development_dataset_version_id": version_id,
                "holdout_protection_confirmed": True,
            },
        )
        self.assertEqual(split_response.status_code, 200, split_response.text)
        split = split_response.json()
        self.assertEqual(split["dataset_version_id"], version_id)
        self.assertEqual(
            split["validation_design"]["dataset_version_id"],
            version_id,
        )

        store = get_scoped_dataset_store((user_id, project_id))
        for key in (
            "outlier_application",
            "missing_validation",
            "feature_manifest",
            "split_record",
            "validation_design",
        ):
            record = store.meta[key]
            self.assertEqual(record["project_id"], project_id, key)
            self.assertEqual(record["dataset_id"], dataset_id, key)
            self.assertEqual(record["dataset_version_id"], version_id, key)


if __name__ == "__main__":
    unittest.main(verbosity=2)

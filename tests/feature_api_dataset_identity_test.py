"""Focused Phase 2A coverage for feature/profile dataset identity seams."""
from __future__ import annotations

import io
import os
import shutil
import sys
import time
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
TEST_ROOT = REPO_ROOT / ".tmp"
TEST_ROOT.mkdir(exist_ok=True)
RUN_ID = uuid.uuid4().hex[:10]
SECURITY_DB = TEST_ROOT / f"feature_api_identity_security_{RUN_ID}.db"
PERSISTENCE_DB = TEST_ROOT / f"feature_api_identity_persistence_{RUN_ID}.db"
CHECKPOINT = TEST_ROOT / f"feature_api_identity_checkpoint_{RUN_ID}.json"
LIBRARY_ROOT = TEST_ROOT / f"feature_api_identity_library_{RUN_ID}"
LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)

os.environ["ATLAS_SECURITY_DB_PATH"] = str(SECURITY_DB)
os.environ["ATLAS_SQLITE_PATH"] = str(PERSISTENCE_DB)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(CHECKPOINT)
os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(LIBRARY_ROOT)
os.environ["ATLAS_AUTH_ENABLED"] = "true"
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402


def cleanup() -> None:
    for base in (SECURITY_DB, PERSISTENCE_DB):
        for suffix in ("", "-wal", "-shm"):
            target = Path(f"{base}{suffix}")
            for attempt in range(20):
                try:
                    target.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt < 19:
                        time.sleep(0.1)
    CHECKPOINT.unlink(missing_ok=True)
    shutil.rmtree(LIBRARY_ROOT, ignore_errors=True)


class FeatureApiDatasetIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup()
        LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
        init_security_store()
        initialize_persistence()
        cls.client = TestClient(app)
        suffix = uuid.uuid4().hex[:8]
        registration = cls.client.post(
            "/api/auth/register",
            json={
                "email": f"feature-api-{suffix}@atlas-phase2a-test.local",
                "displayName": f"Feature API Phase 2A {suffix}",
                "password": "FeatureApiPhase2ATest!1",
                "role": "data_scientist",
            },
        )
        assert registration.status_code == 200, registration.text
        project = cls.client.post(
            "/api/projects",
            json={
                "projectName": f"Feature API Identity {suffix}",
                "projectType": "predictive-modeling",
            },
        )
        assert project.status_code == 200, project.text
        cls.project_id = project.json()["project"]["projectId"]

        frame = pd.DataFrame(
            {
                "predictor_a": [float(value % 6) for value in range(36)],
                "predictor_b": [float((value * 2) % 5) for value in range(36)],
                "bad_flag": [(value // 9) % 2 for value in range(36)],
            }
        )
        upload = cls.client.post(
            "/api/datasets/upload",
            files={
                "file": (
                    "feature-api-identity.csv",
                    io.BytesIO(frame.to_csv(index=False).encode("utf-8")),
                    "text/csv",
                )
            },
            data={"name": f"Feature API Identity {suffix}"},
        )
        assert upload.status_code == 200, upload.text
        dataset = upload.json()["dataset"]
        cls.dataset_id = dataset["datasetId"]
        cls.version_id = dataset["latestVersion"]["versionId"]
        link = cls.client.post(
            f"/api/projects/{cls.project_id}/datasets/link",
            json={
                "datasetId": cls.dataset_id,
                "versionId": cls.version_id,
                "datasetRole": "modeling",
            },
        )
        assert link.status_code == 200, link.text
        activation = cls.client.post(
            f"/api/datasets/{cls.dataset_id}/versions/{cls.version_id}/activate",
            params={"project_id": cls.project_id},
        )
        assert activation.status_code == 200, activation.text
        target = cls.client.post(
            "/api/data/set_target",
            json={
                "project_id": cls.project_id,
                "target": "bad_flag",
                "selected_columns": ["predictor_a", "predictor_b"],
                "expected_dataset_id": cls.dataset_id,
                "expected_dataset_version_id": cls.version_id,
            },
        )
        assert target.status_code == 200, target.text

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cleanup()

    def identity_body(self) -> dict[str, str]:
        return {
            "project_id": self.project_id,
            "expected_dataset_id": self.dataset_id,
            "expected_dataset_version_id": self.version_id,
            "dataset_version": self.version_id,
        }

    def test_quality_and_feature_profiles_return_exact_canonical_identity(self) -> None:
        for path in ("/api/data/quality-profile", "/api/data/feature-profile"):
            response = self.client.post(
                path,
                json={
                    **self.identity_body(),
                    "target": "bad_flag",
                    "event_value": 1,
                    "problem_type": "classification",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertEqual(payload["project_id"], self.project_id)
            self.assertEqual(payload["dataset_id"], self.dataset_id)
            self.assertEqual(payload["dataset_version_id"], self.version_id)
            self.assertEqual(payload["dataset_version"], self.version_id)

    def test_profiles_reject_contradictory_version_before_reading_data(self) -> None:
        for path in ("/api/data/quality-profile", "/api/data/feature-profile"):
            response = self.client.post(
                path,
                json={
                    **self.identity_body(),
                    "expected_dataset_version_id": "v_wrong_profile_version",
                    "target": "bad_flag",
                    "event_value": 1,
                    "problem_type": "classification",
                },
            )
            self.assertEqual(response.status_code, 409, response.text)

    def test_manifest_read_and_mutations_reject_stale_identity(self) -> None:
        manifest = self.client.get(
            "/api/features/manifest",
            params={
                "project_id": self.project_id,
                "expected_dataset_id": self.dataset_id,
                "expected_dataset_version_id": self.version_id,
            },
        )
        self.assertEqual(manifest.status_code, 200, manifest.text)
        payload = manifest.json()
        self.assertEqual(payload["dataset_version_id"], self.version_id)

        stale_query = {
            "project_id": self.project_id,
            "expected_dataset_id": self.dataset_id,
            "expected_dataset_version_id": "v_wrong_manifest_version",
        }
        stale_read = self.client.get("/api/features/manifest", params=stale_query)
        self.assertEqual(stale_read.status_code, 409, stale_read.text)

        stale_body = {
            "project_id": self.project_id,
            "dataset_id": self.dataset_id,
            "dataset_version_id": "v_wrong_manifest_version",
            "dataset_version": "v_wrong_manifest_version",
        }
        requests = (
            ("/api/features/preview", {**stale_body, "features": []}),
            (
                "/api/features/materialize",
                {**stale_body, "manifest_version": payload["manifest_hash"]},
            ),
            (
                "/api/features/confirm",
                {**stale_body, "manifest_version": payload["manifest_hash"]},
            ),
        )
        for path, body in requests:
            response = self.client.post(path, json=body)
            self.assertEqual(response.status_code, 409, response.text)

        stale_delete = self.client.delete(
            "/api/features/does-not-matter",
            params=stale_query,
        )
        self.assertEqual(stale_delete.status_code, 409, stale_delete.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

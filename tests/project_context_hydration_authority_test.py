"""Focused backend authority-chain coverage for project-context hydration.

This suite proves that the frontend hydration endpoints share one exact,
authorized durable project context:

    GET /api/projects/{project_id}
    GET /api/projects/{project_id}/workflow-state
    GET /api/data/active-identity?project_id={project_id}

The test process owns isolated security, persistence, checkpoint, and Dataset
Library roots.  It never reads or writes the developer's live ATLAS stores.

Run:
    .venv/Scripts/python.exe -m pytest -q \
        tests/project_context_hydration_authority_test.py
"""

from __future__ import annotations

import atexit
import io
import os
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_RUN_ID = uuid.uuid4().hex
_TEST_PARENT = _REPO_ROOT / ".tmp"
_TEST_PARENT.mkdir(parents=True, exist_ok=True)
_TEST_ROOT = _TEST_PARENT / f"atlas_project_context_authority_{_RUN_ID}"
_TEST_ROOT.mkdir(parents=True, exist_ok=False)
_SECURITY_DB_PATH = _TEST_ROOT / "security.db"
_PERSISTENCE_DB_PATH = _TEST_ROOT / "persistence.db"
_CHECKPOINT_PATH = _TEST_ROOT / "workflow_checkpoint.json"
_DATASET_LIBRARY_ROOT = _TEST_ROOT / "dataset_library"
_DATASET_LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
_DATASET_BACKUP_ROOT = (
    Path(tempfile.gettempdir()).resolve()
    / f"atlas_project_context_authority_backups_{_RUN_ID}_{uuid.uuid4().hex}"
)
# ``tempfile.mkdtemp`` requests a Windows owner-only ACL that a restricted
# hermetic child token can create but then cannot traverse.  This fixture is
# already rooted in the launcher's unique external TEMP authority, so create
# the collision-resistant directory with the ordinary inherited test ACL.
_DATASET_BACKUP_ROOT.mkdir(parents=False, exist_ok=False)

_ENVIRONMENT_OVERRIDES = {
    "ATLAS_SECURITY_ROOT": str(_TEST_ROOT),
    "ATLAS_SECURITY_DB_PATH": str(_SECURITY_DB_PATH),
    "ATLAS_SQLITE_PATH": str(_PERSISTENCE_DB_PATH),
    "ATLAS_CHECKPOINT_PATH": str(_CHECKPOINT_PATH),
    "ATLAS_DATASET_LIBRARY_ROOT": str(_DATASET_LIBRARY_ROOT),
    "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": str(_DATASET_BACKUP_ROOT),
    "ATLAS_AUTH_ENABLED": "true",
    "ATLAS_ALLOW_PUBLIC_REGISTRATION": "true",
    "ATLAS_TEST_MODE": "1",
}
_ORIGINAL_ENVIRONMENT = {
    key: os.environ.get(key) for key in _ENVIRONMENT_OVERRIDES
}
os.environ.update(_ENVIRONMENT_OVERRIDES)

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.core import dataset_store as dataset_store_module  # noqa: E402
from server.core import result_store as result_store_module  # noqa: E402
from server.core import session_checkpoint as checkpoint_module  # noqa: E402
from server.core.dataset_store import get_scoped_dataset_store  # noqa: E402
from server.core.result_store import get_scoped_result_store  # noqa: E402
from server.datasets import dataset_registry as dataset_registry_module  # noqa: E402
from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.persistence import db as persistence_db_module  # noqa: E402
from server.persistence import service as persistence_service_module  # noqa: E402
from server.persistence.service import get_persistence_service  # noqa: E402
from server.security import security_store as security_store_module  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402


_CLIENTS: list[TestClient] = []


def _bind_isolated_runtime_paths() -> None:
    """Rebind module-cached paths when another test imported ATLAS first."""

    os.environ.update(_ENVIRONMENT_OVERRIDES)
    security_store_module.SECURITY_ROOT = _TEST_ROOT.resolve()
    security_store_module.DB_PATH = _SECURITY_DB_PATH.resolve()
    security_store_module.ATLAS_AUTH_ENABLED = True
    security_store_module.ATLAS_ALLOW_PUBLIC_REGISTRATION = True
    checkpoint_module.CHECKPOINT_PATH = _CHECKPOINT_PATH.resolve()
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
    # A grouped backend run may have imported persistence under another
    # suite's environment first.  Rebind both cached singletons to this
    # suite-owned database so Dataset Library recovery checks cannot observe
    # another fixture's durable catalog authority.
    persistence_db_module._database = persistence_db_module.Database(
        _PERSISTENCE_DB_PATH.resolve()
    )
    persistence_service_module._service = None

    assert security_store_module.DB_PATH == _SECURITY_DB_PATH.resolve()
    assert checkpoint_module.CHECKPOINT_PATH == _CHECKPOINT_PATH.resolve()
    assert dataset_registry_module.ARTIFACT_ROOT == _DATASET_LIBRARY_ROOT.resolve()
    assert persistence_db_module.get_database().path == _PERSISTENCE_DB_PATH.resolve()


def _remove_sqlite_files(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        target = Path(f"{path}{suffix}")
        for attempt in range(25):
            try:
                target.unlink(missing_ok=True)
                break
            except PermissionError:
                if attempt < 24:
                    time.sleep(0.2)


def _cleanup_process_state() -> None:
    # A pending checkpoint timer must remain pointed at this suite's owned
    # path while it is flushed.  No live/runtime ATLAS checkpoint is touched.
    _bind_isolated_runtime_paths()
    for client in list(_CLIENTS):
        client.close()
    _CLIENTS.clear()
    try:
        checkpoint_module.flush_checkpoint()
    except Exception:
        pass
    dataset_store_module._DATASTORES.clear()
    result_store_module._RESULT_STORES.clear()
    _remove_sqlite_files(_SECURITY_DB_PATH)
    _remove_sqlite_files(_PERSISTENCE_DB_PATH)
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)
    shutil.rmtree(_DATASET_BACKUP_ROOT, ignore_errors=True)
    for key, value in _ORIGINAL_ENVIRONMENT.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


_bind_isolated_runtime_paths()
atexit.register(_cleanup_process_state)


def _csv_bytes(offset: int = 0) -> bytes:
    rows = list(range(40))
    frame = pd.DataFrame(
        {
            "predictor_a": [float((value + offset) % 10) for value in rows],
            "predictor_b": [float(((value + offset) * 3) % 7) for value in rows],
            "bad_flag": [(value // 10) % 2 for value in rows],
        }
    )
    return frame.to_csv(index=False).encode("utf-8")


class ProjectContextHydrationAuthorityTest(unittest.TestCase):
    """HTTP integration tests for one fail-closed project hydration chain."""

    @classmethod
    def setUpClass(cls) -> None:
        # Pytest imports every file in a multi-file group before running any
        # class.  Later imports can legitimately create compatibility files
        # under the environment that was active during collection.  Select a
        # fresh suite-owned catalog root only after collection is complete so
        # the recovery guard sees this fixture's real empty starting state.
        global _DATASET_LIBRARY_ROOT
        _DATASET_LIBRARY_ROOT = (
            _TEST_ROOT / f"dataset_library_runtime_{uuid.uuid4().hex}"
        )
        _DATASET_LIBRARY_ROOT.mkdir(parents=True, exist_ok=False)
        _ENVIRONMENT_OVERRIDES["ATLAS_DATASET_LIBRARY_ROOT"] = str(
            _DATASET_LIBRARY_ROOT
        )
        _bind_isolated_runtime_paths()
        init_security_store()
        initialize_persistence()
        # Establish the empty Dataset Library contract before user
        # registration can create a sibling users.json projection.  In a
        # grouped process, relying on import order here makes the recovery
        # guard correctly reject an apparently partial catalog.
        dataset_registry_module.ensure_store()

        cls.owner_client, cls.owner_user_id = cls._register("owner")
        cls.intruder_client, cls.intruder_user_id = cls._register("intruder")

        # Create another project and dataset first.  If any endpoint used a
        # first-project or first-dataset fallback, it would return this identity.
        cls.other_project_id = cls._create_project(
            cls.owner_client, "Authority Chain Other Project"
        )
        (
            cls.other_dataset_id,
            cls.other_dataset_version_id,
        ) = cls._register_link_activate(
            cls.owner_client,
            cls.other_project_id,
            name="Authority Chain Other Dataset",
            offset=100,
        )

        cls.project_id = cls._create_project(
            cls.owner_client, "Authority Chain Exact Project"
        )
        cls.dataset_id, cls.dataset_version_id = cls._register_link_activate(
            cls.owner_client,
            cls.project_id,
            name="Authority Chain Exact Dataset",
            offset=0,
        )

        # Add a later version without activating it.  Exact project hydration
        # must keep returning the older durable selection, never latest-version.
        later = cls.owner_client.post(
            f"/api/datasets/{cls.dataset_id}/versions",
            files={
                "file": (
                    "Authority Chain Exact Dataset v2.csv",
                    io.BytesIO(_csv_bytes(offset=1)),
                    "text/csv",
                )
            },
        )
        assert later.status_code == 200, later.text
        cls.latest_unactivated_version_id = later.json()["version"]["versionId"]
        assert cls.latest_unactivated_version_id != cls.dataset_version_id

        cls.service = get_persistence_service()
        active = cls.service.project_dataset_activations.get_active_selection(
            cls.project_id
        )
        assert active is not None
        cls.activation_revision = int(active["activation_revision"])
        assert cls.activation_revision > 0

        # Seed a real immutable Analysis Partition so the read-only assertion
        # proves an existing authority row and its event are unchanged, not
        # merely that an empty table stays empty.
        cls.partition = cls.service.analysis_partitions.create_or_reuse(
            {
                "project_id": cls.project_id,
                "dataset_id": cls.dataset_id,
                "dataset_version_id": cls.dataset_version_id,
                "target_contract_id": "target-contract-authority-chain",
                "target_column": "bad_flag",
                "positive_value_json": 1,
                "negative_value_json": 0,
                "problem_type": "classification",
                "partition_method": "deterministic_random",
                "selection_rationale": "",
                "preview_fingerprint": "preview-authority-chain",
                "sufficiency_json": {
                    "status": "sufficient",
                    "population_count": 40,
                },
                "predictor_authorization_id": "predictor-auth-authority-chain",
                "development_share": 0.8,
                "holdout_share": 0.2,
                "random_seed": 42,
                "stratification_policy": "target",
                "stratification_field": "bad_flag",
                "population_count": 40,
                "development_count": 32,
                "holdout_count": 8,
                "event_counts_json": {
                    "population": {"0": 20, "1": 20},
                    "development": {"0": 16, "1": 16},
                    "holdout": {"0": 4, "1": 4},
                },
                "row_assignments_json": {
                    "development": list(range(32)),
                    "holdout": list(range(32, 40)),
                },
                "assignment_hash": "assignment-hash-authority-chain",
                "population_fingerprint": "population-fingerprint-authority-chain",
                "artifact_hash": (
                    "a4c7f099166827f0a3e59fe0e919a8aa"
                    "9ac91f3a960d87f58facb06b89c7e121"
                ),
            },
            actor_user_id=cls.owner_user_id,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_process_state()

    @classmethod
    def _register(cls, label: str) -> tuple[TestClient, str]:
        client = TestClient(app)
        _CLIENTS.append(client)
        suffix = uuid.uuid4().hex[:10]
        response = client.post(
            "/api/auth/register",
            json={
                "email": f"{label}-{suffix}@atlas-project-context-test.local",
                "displayName": f"Project Context Test {label} {suffix}",
                "password": "ProjectContextAuthorityTest!1",
                "role": "data_scientist",
            },
        )
        assert response.status_code == 200, response.text
        return client, response.json()["user"]["userId"]

    @classmethod
    def _create_project(cls, client: TestClient, name: str) -> str:
        response = client.post(
            "/api/projects",
            json={"projectName": name, "projectType": "predictive-modeling"},
        )
        assert response.status_code == 200, response.text
        return response.json()["project"]["projectId"]

    @classmethod
    def _register_link_activate(
        cls,
        client: TestClient,
        project_id: str,
        *,
        name: str,
        offset: int,
    ) -> tuple[str, str]:
        upload = client.post(
            "/api/datasets/upload",
            files={
                "file": (
                    f"{name}.csv",
                    io.BytesIO(_csv_bytes(offset=offset)),
                    "text/csv",
                )
            },
            data={"name": name, "description": "Project hydration authority test"},
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

    @classmethod
    def _durable_authority_snapshot(cls) -> dict[str, list[tuple[Any, ...]]]:
        """Capture only state that the hydration GET chain must not mutate."""

        queries = {
            "links": (
                "SELECT * FROM project_dataset_links WHERE project_id = ? "
                "ORDER BY dataset_id"
            ),
            "active_selection": (
                "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?"
            ),
            "activation_events": (
                "SELECT * FROM project_dataset_activation_events WHERE project_id = ? "
                "ORDER BY created_at, activation_event_id"
            ),
            "analysis_partitions": (
                "SELECT * FROM analysis_partitions WHERE project_id = ? "
                "ORDER BY revision, analysis_partition_id"
            ),
            "analysis_partition_events": (
                "SELECT * FROM analysis_partition_events WHERE project_id = ? "
                "ORDER BY created_at, analysis_partition_event_id"
            ),
        }
        with cls.service.database.connection() as connection:
            return {
                name: [tuple(row) for row in connection.execute(query, (cls.project_id,))]
                for name, query in queries.items()
            }

    def test_authorized_chain_uses_one_exact_durable_project_identity(self) -> None:
        # Deliberately contradict only the runtime/browser-like cache and a
        # result-store metadata fallback.  The later registry version exists,
        # but durable selection still authorizes the exact older version.
        scoped_store = get_scoped_dataset_store(
            (self.owner_user_id, self.project_id)
        )
        scoped_store.meta.update(
            {
                "project_id": self.project_id,
                "dataset_id": self.dataset_id,
                "dataset_version_id": self.latest_unactivated_version_id,
                "dataset_version": self.latest_unactivated_version_id,
                "activation_revision": 999,
                "dataset_identity_status": "current",
                "browser_project_id": self.other_project_id,
                "browser_dataset_version_id": self.latest_unactivated_version_id,
            }
        )
        scoped_results = get_scoped_result_store(
            (self.owner_user_id, self.project_id)
        )
        scoped_results.final_model_metadata = {
            "project_id": self.other_project_id,
            "dataset_id": self.other_dataset_id,
            "dataset_version_id": self.other_dataset_version_id,
        }

        before = self._durable_authority_snapshot()

        project_response = self.owner_client.get(
            f"/api/projects/{self.project_id}",
            headers={
                "X-Atlas-Project-Id": self.other_project_id,
                "X-Atlas-Dataset-Version-Id": self.latest_unactivated_version_id,
            },
        )
        self.assertEqual(project_response.status_code, 200, project_response.text)
        project = project_response.json()["project"]
        self.assertEqual(project["projectId"], self.project_id)
        self.assertEqual(len(project["links"]), 1)
        self.assertEqual(project["links"][0]["projectId"], self.project_id)
        self.assertEqual(project["links"][0]["datasetId"], self.dataset_id)
        self.assertEqual(project["activeSelection"]["projectId"], self.project_id)
        self.assertEqual(project["activeSelection"]["datasetId"], self.dataset_id)
        self.assertEqual(
            project["activeSelection"]["datasetVersionId"],
            self.dataset_version_id,
        )
        self.assertEqual(
            project["activeSelection"]["activationRevision"],
            self.activation_revision,
        )

        workflow_response = self.owner_client.get(
            f"/api/projects/{self.project_id}/workflow-state"
        )
        self.assertEqual(workflow_response.status_code, 200, workflow_response.text)
        workflow = workflow_response.json()["workflowState"]
        self.assertEqual(workflow["projectId"], self.project_id)
        workflow_status = workflow["workflowStatus"]
        self.assertEqual(
            workflow_status["datasetIdentity"],
            {
                "project_id": self.project_id,
                "dataset_id": self.dataset_id,
                "dataset_version_id": self.dataset_version_id,
            },
        )
        self.assertEqual(
            workflow_status["identityValidity"]["activationRevision"],
            self.activation_revision,
        )

        identity_response = self.owner_client.get(
            "/api/data/active-identity",
            params={"project_id": self.project_id},
            headers={
                "X-Atlas-Project-Id": self.other_project_id,
                "X-Atlas-Dataset-Version-Id": self.latest_unactivated_version_id,
            },
        )
        self.assertEqual(identity_response.status_code, 200, identity_response.text)
        identity = identity_response.json()
        self.assertEqual(identity["project_id"], self.project_id)
        self.assertEqual(identity["dataset_id"], self.dataset_id)
        self.assertEqual(identity["dataset_version_id"], self.dataset_version_id)
        self.assertEqual(identity["activation_revision"], self.activation_revision)
        self.assertEqual(identity["link"]["project_id"], self.project_id)
        self.assertEqual(identity["link"]["dataset_id"], self.dataset_id)
        self.assertEqual(
            identity["active_selection"]["dataset_version_id"],
            self.dataset_version_id,
        )

        # Explicitly reject every available fallback candidate.
        self.assertNotEqual(identity["project_id"], self.other_project_id)
        self.assertNotEqual(identity["dataset_id"], self.other_dataset_id)
        self.assertNotEqual(
            identity["dataset_version_id"], self.latest_unactivated_version_id
        )
        self.assertNotEqual(
            identity["dataset_version_id"], self.other_dataset_version_id
        )

        after = self._durable_authority_snapshot()
        self.assertEqual(after, before)
        self.assertEqual(len(after["analysis_partitions"]), 1)
        self.assertEqual(len(after["analysis_partition_events"]), 1)

    def test_missing_project_returns_precise_404_across_the_chain(self) -> None:
        missing_project_id = f"missing-project-{uuid.uuid4().hex}"
        requests = (
            self.owner_client.get(f"/api/projects/{missing_project_id}"),
            self.owner_client.get(
                f"/api/projects/{missing_project_id}/workflow-state"
            ),
            self.owner_client.get(
                "/api/data/active-identity",
                params={"project_id": missing_project_id},
            ),
        )
        for response in requests:
            with self.subTest(path=response.request.url.path):
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(
                    response.json()["detail"],
                    "ATLAS project was not found in the persistence database.",
                )

    def test_unrelated_user_gets_precise_nonleaking_403_across_the_chain(self) -> None:
        requests = (
            self.intruder_client.get(f"/api/projects/{self.project_id}"),
            self.intruder_client.get(
                f"/api/projects/{self.project_id}/workflow-state"
            ),
            self.intruder_client.get(
                "/api/data/active-identity",
                params={"project_id": self.project_id},
            ),
        )
        protected_values = (
            self.dataset_id,
            self.dataset_version_id,
            self.latest_unactivated_version_id,
            "Authority Chain Exact Project",
        )
        for response in requests:
            with self.subTest(path=response.request.url.path):
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(
                    response.json()["detail"],
                    "You do not have permission to perform this action on this project.",
                )
                for protected in protected_values:
                    self.assertNotIn(protected, response.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

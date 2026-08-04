"""Focused Phase 2A tests for created-version and external-split identity.

The suite owns an isolated Dataset Library root and calls router functions
directly with scoped in-memory stores. It never reads or writes the developer
runtime registry, project links, checkpoint, or security database.

Run:
    .venv/Scripts/python.exe tests/phase2a_registration_external_identity_test.py
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid


_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
_TEMP_PARENT = _REPO_ROOT / ".tmp"
_TEMP_PARENT.mkdir(parents=True, exist_ok=True)
_RUN_ID = uuid.uuid4().hex
_TEST_ROOT = (
    _TEMP_PARENT / f"atlas_phase2a_registration_external_{_RUN_ID}"
).resolve()
_SECURITY_ROOT = _TEST_ROOT / "security"
_SECURITY_DB = _SECURITY_ROOT / "atlas_security.db"
_PERSISTENCE_DB = _TEST_ROOT / "persistence" / "atlas_local.db"
_CHECKPOINT_PATH = _TEST_ROOT / "checkpoint" / "workflow_checkpoint.json"
_LIBRARY_ROOT = _TEST_ROOT / "dataset-library"
_SYSTEM_TEMP_ROOT = Path(tempfile.gettempdir()).resolve()
_LIBRARY_BACKUP_ROOT = (
    _SYSTEM_TEMP_ROOT / f"atlas_phase2a_dataset_backups_{_RUN_ID}"
).resolve()
_EVIDENCE_ROOT = _TEST_ROOT / "evidence"
_MODEL_ARTIFACT_ROOT = _TEST_ROOT / "model-registry"
_SCORING_ARTIFACT_ROOT = _TEST_ROOT / "scoring-runs"
_ISOLATED_ENVIRONMENT = {
    "ATLAS_TEST_MODE": "1",
    "ATLAS_SECURITY_ROOT": str(_SECURITY_ROOT),
    "ATLAS_SECURITY_DB_PATH": str(_SECURITY_DB),
    "ATLAS_SQLITE_PATH": str(_PERSISTENCE_DB),
    "ATLAS_CHECKPOINT_PATH": str(_CHECKPOINT_PATH),
    "ATLAS_DATASET_LIBRARY_ROOT": str(_LIBRARY_ROOT),
    "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": str(_LIBRARY_BACKUP_ROOT),
    "ATLAS_EVIDENCE_ROOT": str(_EVIDENCE_ROOT),
    "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT": str(_MODEL_ARTIFACT_ROOT),
    "ATLAS_SCORING_RUN_ARTIFACT_ROOT": str(_SCORING_ARTIFACT_ROOT),
}
os.environ.update(_ISOLATED_ENVIRONMENT)

import pandas as pd  # noqa: E402
from fastapi import HTTPException, UploadFile  # noqa: E402

from server.core import session_checkpoint  # noqa: E402
from server.core.dataset_store import DatasetStore  # noqa: E402
from server.datasets import dataset_registry, dataset_router  # noqa: E402
from server.evidence import evidence_store  # noqa: E402
import server.main as main_module  # noqa: E402
from server.model_registry import model_artifacts  # noqa: E402
from server.persistence import db as persistence_db  # noqa: E402
from server.persistence import service as persistence_service  # noqa: E402
from server.scoring_runs import scoring_run_artifacts  # noqa: E402
from server.security import security_store  # noqa: E402
from server.splitting import split_router  # noqa: E402
from tests.analysis_partition_fixture import GovernedAnalysisFixture  # noqa: E402


_CHECKED_IN_MUTABLE_ROOTS = tuple(
    path.resolve()
    for path in (
        _REPO_ROOT / ".runtime",
        _REPO_ROOT / "server" / "data",
        _REPO_ROOT / "server" / "artifacts" / "datasets",
        _REPO_ROOT / "server" / "artifacts" / "security",
        _REPO_ROOT / "server" / "artifacts" / "evidence",
        _REPO_ROOT / "server" / "artifacts" / "model_registry",
        _REPO_ROOT / "server" / "artifacts" / "scoring_runs",
    )
)


def _assert_isolated_path(path: Path, label: str) -> None:
    resolved = Path(path).expanduser().resolve()
    allowed_roots = (_TEST_ROOT, _LIBRARY_BACKUP_ROOT)
    if not any(
        resolved == root or root in resolved.parents
        for root in allowed_roots
    ):
        raise AssertionError(f"{label} escaped the suite-owned temporary root: {resolved}")
    for forbidden in _CHECKED_IN_MUTABLE_ROOTS:
        if resolved == forbidden or forbidden in resolved.parents:
            raise AssertionError(f"{label} targets checked-in runtime state: {resolved}")


def _rebind_isolated_runtime() -> None:
    """Defeat Python module-cache/import-order leakage in combined test runs."""
    os.environ.update(_ISOLATED_ENVIRONMENT)

    dataset_registry.ARTIFACT_ROOT = _LIBRARY_ROOT
    dataset_registry.REGISTRY_PATH = _LIBRARY_ROOT / "registry.json"
    dataset_registry.USERS_PATH = _LIBRARY_ROOT / "users.json"
    dataset_registry.PROJECT_LINKS_PATH = _LIBRARY_ROOT / "project_links.json"
    session_checkpoint.CHECKPOINT_PATH = _CHECKPOINT_PATH
    evidence_store.EVIDENCE_ROOT = _EVIDENCE_ROOT
    evidence_store.ITEMS_ROOT = _EVIDENCE_ROOT / "items"
    evidence_store.REGISTRY_PATH = _EVIDENCE_ROOT / "evidence_registry.json"
    model_artifacts.ARTIFACT_ROOT = _MODEL_ARTIFACT_ROOT
    scoring_run_artifacts.ARTIFACT_ROOT = _SCORING_ARTIFACT_ROOT
    security_store.SECURITY_ROOT = _SECURITY_ROOT
    security_store.DB_PATH = _SECURITY_DB
    persistence_db._database = persistence_db.Database(_PERSISTENCE_DB)
    persistence_service._service = None

    for label, path in (
        ("security root", security_store.SECURITY_ROOT),
        ("security database", security_store.DB_PATH),
        ("persistence database", persistence_db.get_database().path),
        ("checkpoint", session_checkpoint.CHECKPOINT_PATH),
        ("dataset library", dataset_registry.ARTIFACT_ROOT),
        ("dataset library backups", _LIBRARY_BACKUP_ROOT),
        ("evidence root", evidence_store.EVIDENCE_ROOT),
        ("model artifact root", model_artifacts.ARTIFACT_ROOT),
        ("scoring artifact root", scoring_run_artifacts.ARTIFACT_ROOT),
    ):
        _assert_isolated_path(path, label)


OWNER = {
    "userId": "owner-user",
    "displayName": "Owner User",
    "email": "owner@example.test",
    "role": "data_scientist",
}
OUTSIDER = {
    "userId": "outsider-user",
    "displayName": "Outsider User",
    "email": "outsider@example.test",
    "role": "data_scientist",
}
PROJECT_ID = "project-phase2a"
DEVELOPMENT_DATASET_ID = "dataset-development"
DEVELOPMENT_VERSION_ID = "v-development-exact"
TEST_DATASET_ID = "dataset-test"
TEST_VERSION_ID = "v-test-exact"
OOT_DATASET_ID = "dataset-oot"
OOT_VERSION_ID = "v-oot-exact"


class _ScopedProxy:
    def __init__(self, value: object) -> None:
        self.value = value

    def current(self) -> object:
        return self.value


def _frame(rows: int = 120) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "predictor_a": [float(index % 12) for index in range(rows)],
            "bad_flag": [index % 2 for index in range(rows)],
        }
    )


def _created_dataset_payload() -> dict[str, object]:
    created = {
        "versionId": "v-created-exact",
        "rowCount": 120,
        "columnCount": 2,
        "hash": "created-content-hash",
    }
    return {
        "datasetId": "dataset-created",
        "name": "Created Dataset",
        "created_dataset_version_id": created["versionId"],
        "createdDatasetVersionId": created["versionId"],
        "created_version": created,
        # Deliberately contradictory: activation must never use this
        # descriptive projection as authority.
        "latestVersion": {
            "versionId": "v-unrelated-latest",
            "rowCount": 999,
            "columnCount": 999,
        },
    }


def _durable_activation_payload() -> dict[str, object]:
    return {
        "link": {
            "project_id": PROJECT_ID,
            "dataset_id": "dataset-created",
            "link_status": "linked",
            "metadata_json": {
                "datasetRole": "development",
                "requestedDatasetVersionId": "v-created-exact",
            },
        },
        "active_selection": {
            "project_id": PROJECT_ID,
            "dataset_id": "dataset-created",
            "dataset_version_id": "v-created-exact",
            "activation_revision": 1,
            "activation_status": "active",
        },
    }


class Phase2ARegistrationAndExternalIdentityTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(_TEST_ROOT, ignore_errors=True)
        if _LIBRARY_BACKUP_ROOT.parent == _SYSTEM_TEMP_ROOT:
            shutil.rmtree(_LIBRARY_BACKUP_ROOT, ignore_errors=True)

    def setUp(self) -> None:
        _rebind_isolated_runtime()
        # Exercise the normal persistence bootstrap so every repository used
        # by the split contract, including Analysis Partition authority, is
        # present in this suite-owned database.  Hand-creating only the legacy
        # tables would bypass the governed migration path being tested.
        persistence_db.get_database().initialize()
        persistence_service._service = None
        shutil.rmtree(_LIBRARY_ROOT, ignore_errors=True)
        dataset_registry.ensure_store()
        dataset_registry.save_registry({"datasets": []})
        dataset_registry.save_links({"links": []})

    def test_mutable_runtime_bindings_never_target_checked_in_roots(self) -> None:
        for label, path in (
            ("security database", security_store.DB_PATH),
            ("persistence database", persistence_db.get_database().path),
            ("checkpoint", session_checkpoint.CHECKPOINT_PATH),
            ("dataset registry", dataset_registry.REGISTRY_PATH),
            ("project links", dataset_registry.PROJECT_LINKS_PATH),
            ("evidence registry", evidence_store.REGISTRY_PATH),
            ("model artifact root", model_artifacts.ARTIFACT_ROOT),
            ("scoring artifact root", scoring_run_artifacts.ARTIFACT_ROOT),
        ):
            _assert_isolated_path(path, label)

    def _seed_registered_dataset(
        self,
        *,
        dataset_id: str,
        version_id: str,
        owner_user_id: str,
        frame: pd.DataFrame | None = None,
        grants: list[dict[str, str]] | None = None,
    ) -> dict[str, object]:
        data = frame.copy() if frame is not None else _frame()
        relative = Path(dataset_id) / version_id / "data_full.csv"
        artifact = dataset_registry.ARTIFACT_ROOT / relative
        artifact.parent.mkdir(parents=True, exist_ok=True)
        data.to_csv(artifact, index=False)
        return {
            "datasetId": dataset_id,
            "name": dataset_id,
            "ownerUserId": owner_user_id,
            "archived": False,
            "access": grants or [],
            "versions": [
                {
                    "versionId": version_id,
                    "fullDataPath": relative.as_posix(),
                    "rowCount": int(len(data)),
                    "columnCount": int(len(data.columns)),
                    "hash": f"hash-{version_id}",
                }
            ],
            "linkedProjects": [],
        }

    def _seed_external_registry(self) -> None:
        datasets = [
            self._seed_registered_dataset(
                dataset_id=TEST_DATASET_ID,
                version_id=TEST_VERSION_ID,
                owner_user_id=OWNER["userId"],
            ),
            self._seed_registered_dataset(
                dataset_id=OOT_DATASET_ID,
                version_id=OOT_VERSION_ID,
                owner_user_id=OWNER["userId"],
            ),
            self._seed_registered_dataset(
                dataset_id="dataset-private",
                version_id="v-private-exact",
                owner_user_id="private-owner",
            ),
        ]
        dataset_registry.save_registry({"datasets": datasets})

    def _configured_store(self) -> DatasetStore:
        store = DatasetStore()
        store.set_raw(_frame())
        store.set_target("bad_flag")
        store.meta.update(
            {
                "project_id": PROJECT_ID,
                "dataset_id": DEVELOPMENT_DATASET_ID,
                "dataset_version_id": DEVELOPMENT_VERSION_ID,
                "dataset_version": DEVELOPMENT_VERSION_ID,
                "selected_columns": ["predictor_a"],
                "feature_manifest": {
                    "project_id": PROJECT_ID,
                    "dataset_id": DEVELOPMENT_DATASET_ID,
                    "dataset_version_id": DEVELOPMENT_VERSION_ID,
                    "dataset_version": DEVELOPMENT_VERSION_ID,
                    "manifest_hash": "manifest-exact",
                    "manifest_version": "manifest-exact",
                    "features": [
                        {
                            "feature_name": "predictor_a",
                            "selected": True,
                            "eligibility_status": "eligible",
                            "origin": "original",
                        }
                    ],
                },
            }
        )
        return store

    @staticmethod
    def _assert_active_identity(
        project_id: str,
        *,
        expected_dataset_id: str = "",
        expected_dataset_version_id: str = "",
        legacy_dataset_version: str = "",
        **_: object,
    ) -> dict[str, str]:
        expected = {
            "project_id": PROJECT_ID,
            "dataset_id": DEVELOPMENT_DATASET_ID,
            "dataset_version_id": DEVELOPMENT_VERSION_ID,
        }
        if (
            project_id != expected["project_id"]
            or (
                expected_dataset_id
                and expected_dataset_id != expected["dataset_id"]
            )
            or (
                expected_dataset_version_id
                and expected_dataset_version_id
                != expected["dataset_version_id"]
            )
            or (
                legacy_dataset_version
                and legacy_dataset_version
                != expected["dataset_version_id"]
            )
        ):
            raise HTTPException(
                status_code=409,
                detail="The requested dataset identity does not match.",
            )
        return expected

    @contextmanager
    def _patched_split(self, store: DatasetStore):
        with (
            patch.object(split_router, "DATASTORE", store),
            patch.object(
                split_router,
                "assert_expected_active_identity",
                side_effect=self._assert_active_identity,
            ),
            patch.object(split_router, "authorize_modeling_scope"),
            patch.object(split_router, "schedule_checkpoint_save"),
            patch.object(split_router, "audit_event"),
            patch("server.datasets.dataset_identity.audit_event"),
        ):
            yield

    def _split_payload(self, **overrides: object) -> split_router.SplitConfigPayload:
        payload: dict[str, object] = {
            "project_id": PROJECT_ID,
            "split_strategy": "hybrid",
            "test_size": 0.2,
            "random_seed": 42,
            "stratify": True,
            "balance_method": "none",
            "problem_type": "classification",
            "event_value": 1,
            "selected_features": ["predictor_a"],
            "feature_manifest_version": "manifest-exact",
            "dataset_id": DEVELOPMENT_DATASET_ID,
            "dataset_version_id": DEVELOPMENT_VERSION_ID,
            "dataset_version": DEVELOPMENT_VERSION_ID,
            "development_dataset_id": DEVELOPMENT_DATASET_ID,
            "development_dataset_version_id": DEVELOPMENT_VERSION_ID,
            "external_validation_mode": "test_oot",
            "test_dataset_id": TEST_DATASET_ID,
            "test_dataset_version_id": TEST_VERSION_ID,
            "test_target_field": "bad_flag",
            "oot_dataset_id": OOT_DATASET_ID,
            "oot_dataset_version_id": OOT_VERSION_ID,
            "oot_target_field": "bad_flag",
            "fold_method": "stratified_k_fold",
            "fold_count": 3,
            "holdout_protection_confirmed": True,
            "cv_design_approved": True,
            "schema_compatibility_confirmed": True,
            "target_mapping_verified": True,
            "approval_note": "Focused Phase 2A identity test.",
        }
        payload.update(overrides)
        return split_router.SplitConfigPayload(**payload)

    def test_creation_returns_the_exact_created_version_explicitly(self) -> None:
        with (
            patch.object(dataset_registry, "current_user", return_value=OWNER),
            patch.object(dataset_registry, "audit_event"),
        ):
            dataset = dataset_registry.create_dataset_from_dataframe(
                _frame(12),
                name="Explicit Created Version",
                source_type="phase2a_test",
                dataset_role="development",
            )

        created_version_id = dataset["created_dataset_version_id"]
        self.assertTrue(created_version_id)
        self.assertEqual(dataset["createdDatasetVersionId"], created_version_id)
        self.assertEqual(
            dataset["created_version"]["versionId"],
            created_version_id,
        )

    def test_workspace_registration_links_and_activates_created_not_latest(
        self,
    ) -> None:
        dataset = _created_dataset_payload()
        link = Mock()
        with (
            patch.object(
                dataset_registry,
                "create_dataset_from_dataframe",
                return_value=dataset,
            ),
            patch.object(dataset_registry, "link_project", link),
        ):
            returned = dataset_registry.register_workspace_dataset(
                _frame(12),
                name="Workspace Dataset",
                project_id=PROJECT_ID,
            )
        self.assertIs(returned, dataset)
        link.assert_called_once_with(
            PROJECT_ID,
            "dataset-created",
            "v-created-exact",
            "development",
        )

        store = self._configured_store()
        resolve = Mock(
            return_value={
                "project_id": PROJECT_ID,
                "dataset_id": "dataset-created",
                "dataset_version_id": "v-created-exact",
            }
        )
        activation_repository = Mock()
        activation_repository.activate_exact.return_value = (
            _durable_activation_payload()
        )
        persistence = Mock(project_dataset_activations=activation_repository)
        with (
            patch.object(
                dataset_router,
                "DATASTORE",
                _ScopedProxy(store),
            ),
            patch.object(
                dataset_router,
                "RESULTS",
                _ScopedProxy(object()),
            ),
            patch.object(dataset_router, "authorize_modeling_scope"),
            patch.object(
                dataset_router,
                "register_workspace_dataset",
                return_value=dataset,
            ),
            patch.object(
                dataset_router,
                "resolve_registered_version",
                resolve,
            ),
            patch.object(
                dataset_router,
                "get_persistence_service",
                return_value=persistence,
            ),
            patch.object(
                dataset_router,
                "invalidate_downstream_training_state",
            ),
            patch.object(dataset_router, "schedule_checkpoint_save"),
        ):
            response = dataset_router.register_workspace(
                dataset_router.RegisterWorkspaceDatasetRequest(
                    projectId=PROJECT_ID,
                    name="Workspace Dataset",
                ),
                user=OWNER,
            )

        resolve.assert_called_once_with(
            "dataset-created",
            "v-created-exact",
            user=OWNER,
        )
        activation_repository.activate_exact.assert_called_once_with(
            project_id=PROJECT_ID,
            dataset_id="dataset-created",
            dataset_version_id="v-created-exact",
            actor_user_id=OWNER["userId"],
            metadata={
                "datasetRole": "development",
                "requestedDatasetVersionId": "v-created-exact",
                "source": "workspace_registration",
            },
        )
        self.assertEqual(
            response["created_dataset_version_id"],
            "v-created-exact",
        )
        self.assertEqual(
            response["created_version"]["versionId"],
            "v-created-exact",
        )
        self.assertEqual(response["dataset_version_id"], "v-created-exact")
        self.assertNotEqual(
            response["dataset_version_id"],
            dataset["latestVersion"]["versionId"],
        )

    def test_workspace_registration_rejects_latest_only_response(self) -> None:
        store = self._configured_store()
        latest_only = {
            "datasetId": "dataset-created",
            "latestVersion": {"versionId": "v-latest-only"},
        }
        with (
            patch.object(
                dataset_router,
                "DATASTORE",
                _ScopedProxy(store),
            ),
            patch.object(
                dataset_router,
                "RESULTS",
                _ScopedProxy(object()),
            ),
            patch.object(dataset_router, "authorize_modeling_scope"),
            patch.object(
                dataset_router,
                "register_workspace_dataset",
                return_value=latest_only,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                dataset_router.register_workspace(
                    dataset_router.RegisterWorkspaceDatasetRequest(
                        projectId=PROJECT_ID,
                        name="Workspace Dataset",
                    ),
                    user=OWNER,
                )
        self.assertEqual(raised.exception.status_code, 500)

    def test_data_acquisition_upload_links_the_explicit_created_version(
        self,
    ) -> None:
        dataset = _created_dataset_payload()
        store = DatasetStore()
        link = Mock()
        resolve = Mock(
            return_value={
                "project_id": PROJECT_ID,
                "dataset_id": "dataset-created",
                "dataset_version_id": "v-created-exact",
            }
        )
        activation_repository = Mock()
        activation_repository.activate_exact.return_value = (
            _durable_activation_payload()
        )
        persistence = Mock(project_dataset_activations=activation_repository)
        endpoint = next(
            route.endpoint
            for route in main_module.app.routes
            if getattr(route, "path", "") == "/api/data/upload_csv"
        )
        upload = UploadFile(
            file=io.BytesIO(_frame(12).to_csv(index=False).encode("utf-8")),
            filename="phase2a.csv",
        )
        with (
            patch.object(main_module, "DATASTORE", _ScopedProxy(store)),
            patch.object(main_module, "RESULTS", _ScopedProxy(object())),
            patch.object(main_module, "authorize_modeling_scope"),
            patch.object(
                main_module,
                "create_dataset_from_dataframe",
                return_value=dataset,
            ),
            patch.object(main_module, "link_project", link),
            patch.object(
                main_module,
                "resolve_registered_version",
                resolve,
            ),
            patch.object(
                main_module,
                "get_persistence_service",
                return_value=persistence,
            ),
            patch.object(
                main_module,
                "invalidate_downstream_training_state",
            ),
            patch.object(main_module, "schedule_checkpoint_save"),
        ):
            response = asyncio.run(
                endpoint(file=upload, project_id=PROJECT_ID, user=OWNER)
            )

        link.assert_called_once_with(
            PROJECT_ID,
            "dataset-created",
            "v-created-exact",
            "development",
        )
        resolve.assert_called_once_with(
            "dataset-created",
            "v-created-exact",
            user=OWNER,
        )
        activation_repository.activate_exact.assert_called_once_with(
            project_id=PROJECT_ID,
            dataset_id="dataset-created",
            dataset_version_id="v-created-exact",
            actor_user_id=OWNER["userId"],
            metadata={
                "datasetRole": "development",
                "requestedDatasetVersionId": "v-created-exact",
                "source": "data_acquisition_upload",
            },
        )
        self.assertEqual(
            response["created_dataset_version_id"],
            "v-created-exact",
        )
        self.assertEqual(
            response["created_version"]["versionId"],
            "v-created-exact",
        )
        self.assertEqual(response["dataset_version_id"], "v-created-exact")
        self.assertNotEqual(
            response["dataset_version_id"],
            dataset["latestVersion"]["versionId"],
        )

    def test_external_version_resolution_is_exact_and_acl_checked(self) -> None:
        self._seed_external_registry()
        with patch("server.datasets.dataset_identity.audit_event"):
            frame, reference = split_router._load_external_frame(
                TEST_DATASET_ID,
                TEST_VERSION_ID,
                "TEST",
                user=OWNER,
            )
            self.assertFalse(frame.empty)
            self.assertEqual(
                reference["dataset_version_id"],
                TEST_VERSION_ID,
            )

            with self.assertRaises(HTTPException) as wrong_membership:
                split_router._load_external_frame(
                    TEST_DATASET_ID,
                    OOT_VERSION_ID,
                    "TEST",
                    user=OWNER,
                )
            self.assertEqual(wrong_membership.exception.status_code, 409)

            with self.assertRaises(HTTPException) as unknown_version:
                split_router._load_external_frame(
                    TEST_DATASET_ID,
                    "v-unknown",
                    "TEST",
                    user=OWNER,
                )
            self.assertEqual(unknown_version.exception.status_code, 404)

            with self.assertRaises(HTTPException) as unauthorized:
                split_router._load_external_frame(
                    "dataset-private",
                    "v-private-exact",
                    "TEST",
                    user=OUTSIDER,
                )
            self.assertEqual(unauthorized.exception.status_code, 403)

    def test_external_validation_persists_all_exact_version_references(
        self,
    ) -> None:
        self._seed_external_registry()
        store = self._configured_store()
        # The external-validation contract is downstream of the exact,
        # documented Analysis Partition.  Install that authority through the
        # same preview/confirm/evidence/MDD path used by production instead of
        # bypassing the pre-EDA gate with a legacy split-only fixture.
        partition = GovernedAnalysisFixture(
            project_id=PROJECT_ID,
            owner=OWNER["userId"],
        )
        try:
            partition.install(
                store,
                dataset_id=DEVELOPMENT_DATASET_ID,
                dataset_version_id=DEVELOPMENT_VERSION_ID,
                target="bad_flag",
                authorized_predictors=["predictor_a"],
            )
            with self._patched_split(store):
                response = split_router.balancing_split_config(
                    self._split_payload(),
                    user=OWNER,
                )
        finally:
            partition.close()

        self.assertTrue(response["ready"])
        record = store.meta["split_record"]
        config = record["config"]
        design = record["validation_design"]
        self.assertEqual(
            config["development_dataset_version_id"],
            DEVELOPMENT_VERSION_ID,
        )
        self.assertEqual(config["test_dataset_version_id"], TEST_VERSION_ID)
        self.assertEqual(config["oot_dataset_version_id"], OOT_VERSION_ID)
        self.assertEqual(
            design["development_dataset"]["dataset_version_id"],
            DEVELOPMENT_VERSION_ID,
        )
        self.assertEqual(
            design["test_reference"]["dataset_version_id"],
            TEST_VERSION_ID,
        )
        self.assertEqual(
            design["oot_reference"]["dataset_version_id"],
            OOT_VERSION_ID,
        )
        self.assertEqual(
            record["test_reference"]["dataset_version_id"],
            TEST_VERSION_ID,
        )
        self.assertEqual(
            record["oot_reference"]["dataset_version_id"],
            OOT_VERSION_ID,
        )

    def test_external_legacy_only_and_conflicting_versions_fail_closed(
        self,
    ) -> None:
        self._seed_external_registry()
        store = self._configured_store()
        with self._patched_split(store):
            with self.assertRaises(HTTPException) as legacy_only:
                split_router.balancing_split_config(
                    self._split_payload(
                        test_dataset_version_id="",
                        test_dataset_version=TEST_VERSION_ID,
                    ),
                    user=OWNER,
                )
            self.assertEqual(legacy_only.exception.status_code, 409)

            with self.assertRaises(HTTPException) as conflicting_alias:
                split_router.balancing_split_config(
                    self._split_payload(
                        test_dataset_version="v-browser-profile-id",
                    ),
                    user=OWNER,
                )
            self.assertEqual(conflicting_alias.exception.status_code, 409)

            with self.assertRaises(HTTPException) as wrong_development:
                split_router.balancing_split_config(
                    self._split_payload(
                        development_dataset_version_id="v-other-development",
                    ),
                    user=OWNER,
                )
            self.assertEqual(wrong_development.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main(verbosity=2)

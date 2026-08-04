from __future__ import annotations

import json
import os
import shutil
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch

import pandas as pd

from server.core.dataset_store import DatasetStore, DatasetStoreProxy
from server.core.result_store import ResultStore, ResultStoreProxy
from server.datasets import dataset_identity, dataset_registry, dataset_router
from server.datasets.dataset_identity import (
    active_dataset_identity,
    assert_expected_active_identity,
)
from server.persistence.db import Database
from server.persistence.repositories.project_dataset_activation_repository import (
    ProjectDatasetActivationConflictError,
)
from server.persistence.service import PersistenceService


class ActivationRuntimeRevisionConsistencyTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary_root = Path(__file__).resolve().parents[1] / ".tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        self.database_path = temporary_root / f"activation_runtime_{token}.db"
        self.dataset_root = temporary_root / f"activation_runtime_library_{token}"
        self.dataset_root.mkdir(parents=True, exist_ok=True)
        self.database = Database(self.database_path)
        self.database.initialize()
        self.service = PersistenceService(self.database)
        self.user = {
            "userId": "activation-runtime-owner",
            "displayName": "Activation Runtime Owner",
            "email": "activation-runtime-owner@example.test",
            "role": "data_scientist",
        }
        self.service.sync_user(self.user)
        self.service.projects.upsert(
            {
                "project_id": "project-activation-runtime",
                "project_name": "Activation Runtime Test",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "owner_user_id": self.user["userId"],
                "metadata_json": {},
            }
        )
        self._write_dataset_library()
        self.store = DatasetStore()
        self.results = ResultStore()

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)
        expected_parent = Path(__file__).resolve().parents[1] / ".tmp"
        if self.dataset_root.parent == expected_parent:
            shutil.rmtree(self.dataset_root, ignore_errors=True)

    def _write_dataset_library(self) -> None:
        versions = [
            {
                "versionId": "dataset-version-1",
                "label": "v1",
                "fullDataPath": "dataset-1/versions/dataset-version-1/full_data.csv",
                "hash": "hash-v1",
                "schemaHash": "schema-v1",
            },
            {
                "versionId": "dataset-version-2",
                "label": "v2",
                "fullDataPath": "dataset-1/versions/dataset-version-2/full_data.csv",
                "hash": "hash-v2",
                "schemaHash": "schema-v2",
            },
        ]
        frames = {
            "dataset-version-1": "feature,target\n1,0\n2,1\n",
            "dataset-version-2": "feature,target\n101,0\n202,1\n",
        }
        for version in versions:
            artifact = self.dataset_root / str(version["fullDataPath"])
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(frames[str(version["versionId"])], encoding="utf-8")
        (self.dataset_root / "registry.json").write_text(
            json.dumps(
                {
                    "datasets": [
                        {
                            "datasetId": "dataset-1",
                            "name": "Dataset One",
                            "sourceType": "registered",
                            "ownerUserId": self.user["userId"],
                            "archived": False,
                            "access": [],
                            "target": "target",
                            "versions": versions,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (self.dataset_root / "project_links.json").write_text(
            json.dumps({"links": []}), encoding="utf-8"
        )
        (self.dataset_root / "users.json").write_text(
            json.dumps({"users": []}), encoding="utf-8"
        )

    @contextmanager
    def _environment(self):
        with (
            patch.dict(
                os.environ,
                {"ATLAS_DATASET_LIBRARY_ROOT": str(self.dataset_root)},
            ),
            patch.object(dataset_registry, "ARTIFACT_ROOT", self.dataset_root),
            patch.object(
                dataset_registry,
                "REGISTRY_PATH",
                self.dataset_root / "registry.json",
            ),
            patch.object(
                dataset_registry,
                "PROJECT_LINKS_PATH",
                self.dataset_root / "project_links.json",
            ),
            patch.object(
                dataset_registry,
                "USERS_PATH",
                self.dataset_root / "users.json",
            ),
            patch(
                "server.persistence.service.get_persistence_service",
                return_value=self.service,
            ),
            patch.object(
                dataset_router,
                "get_persistence_service",
                return_value=self.service,
            ),
            patch.object(dataset_router, "_mirror_legacy_link"),
            patch.object(dataset_router, "schedule_checkpoint_save"),
            patch.object(DatasetStoreProxy, "current", return_value=self.store),
            patch.object(ResultStoreProxy, "current", return_value=self.results),
            patch("server.datasets.dataset_identity.audit_event"),
            patch("server.security.security_store.audit_event"),
        ):
            yield

    def _activate(self, version_id: str, expected_revision: int | None = None) -> dict:
        return dataset_router.activate_dataset_version(
            "dataset-1",
            version_id,
            project_id="project-activation-runtime",
            expected_activation_revision=expected_revision,
            user=self.user,
        )

    def test_same_triple_new_revision_invalidates_unrevalidated_runtime_state(self) -> None:
        with self._environment():
            first = self._activate("dataset-version-1")
            self.assertEqual(first["activation_revision"], 1)
            self.store.set_processed(
                pd.DataFrame({"feature": [9, 10], "target": [0, 1]})
            )
            self.store.meta.update(
                {
                    "outlier_application": {"status": "applied"},
                    "missing_application": {"status": "applied"},
                    "feature_manifest": {"feature_manifest_id": "stale-manifest"},
                    "split_record": {"split_id": "stale-split"},
                    "validation_design": {
                        "validation_design_id": "stale-validation"
                    },
                    "training_execution": {"training_run_id": "stale-run"},
                }
            )
            self.store.X_train = pd.DataFrame({"feature": [9]})
            self.store.y_train = pd.Series([0])
            self.results.set_last_summary({"candidate_id": "stale-candidate"})
            self.results.set_model_artifacts({"stale-candidate": object()})
            self.results.set_final_model(object(), {"candidate_id": "stale-candidate"})

            self.service.project_dataset_activations.record_contradiction(
                project_id="project-activation-runtime",
                actor_user_id=self.user["userId"],
                reason="Focused test requires explicit same-version revalidation.",
            )
            repaired = self._activate("dataset-version-1", expected_revision=1)

        self.assertEqual(repaired["activation_revision"], 2)
        self.assertEqual(self.store.meta["activation_revision"], 2)
        self.assertIsNone(self.store.processed_df)
        self.assertIsNone(self.store.X_train)
        for key in (
            "outlier_application",
            "missing_application",
            "feature_manifest",
            "split_record",
            "validation_design",
            "training_execution",
        ):
            self.assertNotIn(key, self.store.meta)
        self.assertIsNone(self.results.get_last_summary())
        self.assertEqual(self.results.get_model_artifacts(), {})
        self.assertIsNone(self.results.get_final_model())

    def test_same_dataset_version_switch_refreshes_non_authoritative_link_projection(self) -> None:
        with self._environment():
            self._activate("dataset-version-1")
            switched = self._activate("dataset-version-2", expected_revision=1)
            state = self.service.project_dataset_activations.get_project_state(
                "project-activation-runtime"
            )
            listing = dataset_router.get_project_links(
                "project-activation-runtime",
                user=self.user,
            )

        link = state["links"][0]
        self.assertNotIn("requestedDatasetVersionId", link["metadata_json"])
        self.assertEqual(
            link["metadata_json"]["lastValidatedVersionId"],
            "dataset-version-2",
        )
        self.assertNotIn("dataset_version_id", link)
        self.assertEqual(switched["link"]["versionId"], "dataset-version-2")
        self.assertFalse(switched["link"]["versionSelectionAuthoritative"])
        self.assertEqual(
            switched["active_selection"]["datasetVersionId"],
            "dataset-version-2",
        )
        self.assertEqual(listing["links"][0]["versionId"], "dataset-version-2")

    def test_stale_optimistic_diagnostic_cannot_poison_new_activation(self) -> None:
        with self._environment():
            self._activate("dataset-version-1")
            self._activate("dataset-version-2", expected_revision=1)
            with self.assertRaises(ProjectDatasetActivationConflictError):
                self.service.project_dataset_activations.record_contradiction_if_current(
                    project_id="project-activation-runtime",
                    actor_user_id=self.user["userId"],
                    reason="A stale reader observed a revision-one contradiction.",
                    expected_dataset_id="dataset-1",
                    expected_dataset_version_id="dataset-version-1",
                    expected_activation_revision=1,
                )
            durable = self.service.project_dataset_activations.get_active_selection(
                "project-activation-runtime"
            ) or {}

        self.assertEqual(durable["activation_status"], "active")
        self.assertEqual(durable["dataset_version_id"], "dataset-version-2")
        self.assertEqual(int(durable["activation_revision"]), 2)

    def test_concurrent_read_and_different_activation_never_leave_stale_cache(self) -> None:
        read_started = Event()
        allow_read = Event()
        original_read_csv = pd.read_csv

        def controlled_read_csv(path, *args, **kwargs):
            if "dataset-version-1" in str(path):
                read_started.set()
                if not allow_read.wait(timeout=5):
                    raise TimeoutError("Timed out waiting to release exact v1 hydration.")
            return original_read_csv(path, *args, **kwargs)

        with self._environment():
            self._activate("dataset-version-1")
            self.store.raw_df = None
            with patch.object(dataset_identity.pd, "read_csv", side_effect=controlled_read_csv):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    read_future = executor.submit(
                        active_dataset_identity,
                        "project-activation-runtime",
                        user=self.user,
                        store=self.store,
                        result_store=self.results,
                    )
                    self.assertTrue(read_started.wait(timeout=5))
                    activation_future = executor.submit(
                        self._activate,
                        "dataset-version-2",
                        1,
                    )
                    allow_read.set()
                    read_identity = read_future.result(timeout=10)
                    activation = activation_future.result(timeout=10)

            durable = self.service.project_dataset_activations.get_active_selection(
                "project-activation-runtime"
            )

        self.assertEqual(read_identity["dataset_version_id"], "dataset-version-2")
        self.assertEqual(activation["dataset_version_id"], "dataset-version-2")
        self.assertEqual(durable["dataset_version_id"], "dataset-version-2")
        self.assertEqual(self.store.meta["dataset_version_id"], "dataset-version-2")
        self.assertEqual(self.store.meta["activation_revision"], 2)
        self.assertEqual(self.store.raw_df["feature"].tolist(), [101, 202])

    def test_store_held_reader_cannot_deadlock_with_committed_activation(self) -> None:
        """Force the former store->project / project->store inversion.

        The reader owns the runtime lock before activation starts.  Activation
        then commits revision 2 and waits to publish through that same runtime
        lock.  Identity resolution must observe/publish revision 2 without
        waiting for activation's project lock, release the store, and allow the
        activation request to finish.
        """

        store_held = Event()
        activation_committed = Event()
        reader_results: list[dict] = []
        activation_results: list[dict] = []
        errors: list[BaseException] = []

        def read_while_holding_store() -> None:
            try:
                with self.store.state_lock:
                    store_held.set()
                    if not activation_committed.wait(timeout=5):
                        raise TimeoutError(
                            "Activation did not commit while the runtime lock was held."
                        )
                    reader_results.append(
                        assert_expected_active_identity(
                            "project-activation-runtime",
                            expected_dataset_id="dataset-1",
                            expected_dataset_version_id="dataset-version-2",
                            require_expected=True,
                            user=self.user,
                            store=self.store,
                        )
                    )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        def activate_new_revision() -> None:
            try:
                activation_results.append(
                    self._activate("dataset-version-2", expected_revision=1)
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        with self._environment():
            self._activate("dataset-version-1")
            reader_thread = Thread(target=read_while_holding_store, daemon=True)
            reader_thread.start()
            self.assertTrue(store_held.wait(timeout=5))

            activation_thread = Thread(target=activate_new_revision, daemon=True)
            activation_thread.start()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                durable = self.service.project_dataset_activations.get_active_selection(
                    "project-activation-runtime"
                ) or {}
                if (
                    durable.get("dataset_version_id") == "dataset-version-2"
                    and int(durable.get("activation_revision") or 0) == 2
                ):
                    activation_committed.set()
                    break
                time.sleep(0.01)

            self.assertTrue(
                activation_committed.is_set(),
                "The competing activation never reached its durable commit.",
            )
            # Registry integrity validation may perform protected-root physical
            # checks on Windows before the optimistic reader can release the
            # runtime lock. Keep this a bounded deadlock assertion without
            # conflating slow filesystem checks with a lock inversion.
            reader_thread.join(timeout=15)
            self.assertFalse(
                reader_thread.is_alive(),
                "Identity resolution deadlocked while the caller held the runtime lock.",
            )
            activation_thread.join(timeout=15)
            self.assertFalse(
                activation_thread.is_alive(),
                "Activation did not finish after the reader released the runtime lock.",
            )
            durable = self.service.project_dataset_activations.get_active_selection(
                "project-activation-runtime"
            ) or {}

        self.assertEqual(errors, [])
        self.assertEqual(len(reader_results), 1)
        self.assertEqual(len(activation_results), 1)
        self.assertEqual(reader_results[0]["dataset_version_id"], "dataset-version-2")
        self.assertEqual(reader_results[0]["activation_revision"], 2)
        self.assertEqual(activation_results[0]["activation_revision"], 2)
        self.assertEqual(durable["dataset_version_id"], "dataset-version-2")
        self.assertEqual(int(durable["activation_revision"]), 2)
        self.assertEqual(self.store.meta["dataset_version_id"], "dataset-version-2")
        self.assertEqual(int(self.store.meta["activation_revision"]), 2)
        self.assertEqual(self.store.raw_df["feature"].tolist(), [101, 202])


if __name__ == "__main__":
    unittest.main()

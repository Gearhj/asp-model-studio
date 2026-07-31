"""Focused regressions for source replacement and fail-closed restore state."""
from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

import pandas as pd
from fastapi import HTTPException


_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import server.core.dataset_store as dataset_store_module  # noqa: E402
import server.core.result_store as result_store_module  # noqa: E402
import server.core.session_checkpoint as checkpoint  # noqa: E402
from server.core.dataset_state_keys import PRETRAINING_STATE_KEYS  # noqa: E402
from server.core.dataset_store import DatasetStore, get_scoped_dataset_store  # noqa: E402
from server.core.result_store import get_scoped_result_store  # noqa: E402
from server.datasets import dataset_identity  # noqa: E402


class DatasetIdentityClearTests(unittest.TestCase):
    def test_source_replacement_clears_all_shared_pretraining_state(self) -> None:
        store = DatasetStore()
        store.raw_df = pd.DataFrame({"old": [1, 2]})
        store.processed_df = pd.DataFrame({"old": [10, 20]})
        store.X_train = pd.DataFrame({"old": [10]})
        store.X_test = pd.DataFrame({"old": [20]})
        store.y_train = pd.Series([0])
        store.y_test = pd.Series([1])
        store.meta.update(
            {
                "project_id": "project-old",
                "dataset_id": "dataset-old",
                "dataset_version_id": "version-old",
                "dataset_version": "version-old",
                "source": {"dataset_id": "dataset-old"},
                "access_metadata_id": "access-old",
                "profile_snapshot_id": "profile-old",
                **{key: {"stale": key} for key in PRETRAINING_STATE_KEYS},
            }
        )

        store.set_raw(pd.DataFrame({"new": [3, 4]}))

        self.assertEqual(list(store.raw_df.columns), ["new"])
        self.assertIsNone(store.processed_df)
        self.assertEqual(store.get_splits(), (None, None, None, None))
        for key in PRETRAINING_STATE_KEYS:
            self.assertNotIn(key, store.meta, key)
        for key in (
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "dataset_version",
            "source",
            "access_metadata_id",
            "profile_snapshot_id",
        ):
            self.assertNotIn(key, store.meta, key)
        self.assertIs(
            dataset_identity.PRETRAINING_STATE_KEYS,
            PRETRAINING_STATE_KEYS,
        )

    def test_invalid_status_cannot_be_read_as_an_active_identity(self) -> None:
        store = DatasetStore()
        store.meta.update(
            {
                "project_id": "project-1",
                "dataset_id": "dataset-1",
                "dataset_version_id": "version-1",
                "dataset_identity_status": "invalid",
                "dataset_identity_error": (
                    "The exact immutable artifact is unavailable."
                ),
            }
        )

        with self.assertRaises(HTTPException) as raised:
            dataset_identity.active_dataset_identity(
                "project-1",
                store=store,
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("artifact is unavailable", str(raised.exception.detail))


class InvalidCheckpointResultsSuppressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._datasets_snapshot = dict(dataset_store_module._DATASTORES)
        self._results_snapshot = dict(result_store_module._RESULT_STORES)
        dataset_store_module._DATASTORES.clear()
        result_store_module._RESULT_STORES.clear()
        self._original_checkpoint_path = checkpoint.CHECKPOINT_PATH
        test_temp_root = _REPO_ROOT / ".tmp"
        test_temp_root.mkdir(exist_ok=True)
        self._temp_dir = (
            test_temp_root
            / f"atlas_invalid_checkpoint_{uuid.uuid4().hex}"
        )
        self._temp_dir.mkdir(parents=True)
        checkpoint.CHECKPOINT_PATH = self._temp_dir / "workflow_checkpoint.json"

    def tearDown(self) -> None:
        checkpoint.CHECKPOINT_PATH = self._original_checkpoint_path
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        dataset_store_module._DATASTORES.clear()
        dataset_store_module._DATASTORES.update(self._datasets_snapshot)
        result_store_module._RESULT_STORES.clear()
        result_store_module._RESULT_STORES.update(self._results_snapshot)

    def test_invalid_legacy_dataset_scope_drops_paired_results(self) -> None:
        scope = ("checkpoint-owner", "checkpoint-project")
        stale_results = get_scoped_result_store(scope)
        stale_results.set_last_summary({"source": "stale-memory"})
        stale_results.set_model_availability({"xgboost": True})
        stale_results.set_model_artifacts({"xgboost": {"source": "stale-memory"}})

        checkpoint.CHECKPOINT_PATH.write_text(
            json.dumps(
                {
                    "schema_version": checkpoint.CHECKPOINT_SCHEMA_VERSION,
                    "datastore_scopes": [
                        {
                            "owner_user_id": scope[0],
                            "project_id": scope[1],
                            "dataset": {
                                "raw_df": checkpoint._encode(
                                    pd.DataFrame(
                                        {
                                            "predictor": [1.0, 2.0],
                                            "target": [0, 1],
                                        }
                                    )
                                ),
                                "processed_df": None,
                                "target": "target",
                                "X_train": None,
                                "X_test": None,
                                "y_train": None,
                                "y_test": None,
                                "meta": {
                                    "dataset_version": "legacy-version-only",
                                    "training_execution": {"status": "complete"},
                                },
                            },
                        }
                    ],
                    "results_scopes": [
                        {
                            "owner_user_id": scope[0],
                            "project_id": scope[1],
                            "results": {
                                "last_training_summary": {
                                    "source": "checkpoint"
                                },
                                "training_timestamp": "2026-07-30T12:00:00Z",
                                "model_availability": {"xgboost": True},
                                "model_artifacts": {
                                    "xgboost": {"source": "checkpoint"}
                                },
                                "final_model_metadata": {
                                    "model": "xgboost"
                                },
                                "scoring_reference": {
                                    "dataset_version_id": "legacy-version-only"
                                },
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with (
            mock.patch.object(
                checkpoint,
                "_live_identity_sets",
                return_value=(None, None),
            ),
            mock.patch.object(
                dataset_identity,
                "get_user",
                return_value={"userId": scope[0]},
            ),
        ):
            self.assertTrue(checkpoint.load_checkpoint())

        restored_dataset = get_scoped_dataset_store(scope)
        self.assertEqual(
            restored_dataset.meta.get("dataset_identity_status"),
            "invalid",
        )
        self.assertIsNone(restored_dataset.raw_df)
        self.assertNotIn("training_execution", restored_dataset.meta)

        restored_results = get_scoped_result_store(scope)
        self.assertIsNone(restored_results.last_training_summary)
        self.assertIsNone(restored_results.training_timestamp)
        self.assertEqual(restored_results.model_availability, {})
        self.assertEqual(restored_results.model_artifacts, {})
        self.assertIsNone(restored_results.final_model_metadata)
        self.assertIsNone(restored_results.scoring_reference)

    def test_results_without_paired_dataset_scope_are_not_restored(self) -> None:
        scope = ("checkpoint-owner", "results-only-project")
        checkpoint.CHECKPOINT_PATH.write_text(
            json.dumps(
                {
                    "schema_version": checkpoint.CHECKPOINT_SCHEMA_VERSION,
                    "datastore_scopes": [],
                    "results_scopes": [
                        {
                            "owner_user_id": scope[0],
                            "project_id": scope[1],
                            "results": {
                                "last_training_summary": {
                                    "source": "orphaned-checkpoint"
                                },
                                "training_timestamp": "2026-07-30T12:00:00Z",
                                "model_availability": {"xgboost": True},
                                "model_artifacts": {
                                    "xgboost": {"source": "orphaned-checkpoint"}
                                },
                                "final_model_metadata": {
                                    "model": "xgboost"
                                },
                                "scoring_reference": {
                                    "dataset_version_id": "version-without-scope"
                                },
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with mock.patch.object(
            checkpoint,
            "_live_identity_sets",
            return_value=(None, None),
        ):
            self.assertTrue(checkpoint.load_checkpoint())

        restored_results = get_scoped_result_store(scope)
        self.assertIsNone(restored_results.last_training_summary)
        self.assertIsNone(restored_results.training_timestamp)
        self.assertEqual(restored_results.model_availability, {})
        self.assertEqual(restored_results.model_artifacts, {})
        self.assertIsNone(restored_results.final_model_metadata)
        self.assertIsNone(restored_results.scoring_reference)

    def test_checkpoint_encodes_paired_dataset_and_results_atomically(self) -> None:
        scope = ("checkpoint-owner", "atomic-project")
        dataset = get_scoped_dataset_store(scope)
        results = get_scoped_result_store(scope)
        dataset.data_revision = 7
        dataset.meta["snapshot_marker"] = "before"
        results.set_last_summary({"snapshot_marker": "before"})

        mutation_started = threading.Event()
        mutation_finished = threading.Event()
        original_encode_dataset = checkpoint._encode_dataset
        mutator: list[threading.Thread] = []

        def mutate_after_lock_is_requested() -> None:
            mutation_started.set()
            with dataset.state_lock:
                dataset.meta["snapshot_marker"] = "after"
                results.set_last_summary({"snapshot_marker": "after"})
            mutation_finished.set()

        def encode_while_mutation_waits(store: object) -> dict:
            thread = threading.Thread(
                target=mutate_after_lock_is_requested,
                daemon=True,
            )
            mutator.append(thread)
            thread.start()
            self.assertTrue(mutation_started.wait(timeout=1))
            time.sleep(0.05)
            self.assertFalse(
                mutation_finished.is_set(),
                "the paired scope lock must block mutation during encoding",
            )
            return original_encode_dataset(store)

        with (
            mock.patch.object(
                checkpoint,
                "_live_identity_sets",
                return_value=(None, None),
            ),
            mock.patch.object(
                checkpoint,
                "_encode_dataset",
                side_effect=encode_while_mutation_waits,
            ),
        ):
            self.assertTrue(checkpoint.save_checkpoint())

        for thread in mutator:
            thread.join(timeout=1)
        self.assertTrue(mutation_finished.is_set())
        payload = json.loads(
            checkpoint.CHECKPOINT_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(
            payload["datastore_scopes"][0]["dataset"]["meta"][
                "snapshot_marker"
            ],
            "before",
        )
        self.assertEqual(
            payload["datastore_scopes"][0]["dataset"]["data_revision"],
            7,
        )
        self.assertEqual(
            payload["results_scopes"][0]["results"][
                "last_training_summary"
            ]["snapshot_marker"],
            "before",
        )


if __name__ == "__main__":
    unittest.main()

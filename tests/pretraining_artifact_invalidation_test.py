from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import Mock, patch
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.core.dataset_store import DATASTORE, DatasetStore
from server.core.metadata_router import SetTargetPayload, set_target
from server.core.pretraining_invalidation import (
    invalidate_downstream_training_state,
)
from server.core.result_store import RESULTS, ResultStore
from server.datasets.dataset_router import activate_dataset_version
from server.persistence.db import Database
from server.persistence.service import PersistenceService
from server.training.candidate_contract import (
    build_candidate_contract,
    canonical_contract_hash,
    complete_training_contract,
)
from server.training.training_job_service import TrainingJobService
from server.training.training_job_types import TrainingJobRequest


IDENTITY = {
    "project_id": "project-invalidation",
    "dataset_id": "dataset-old",
    "dataset_version_id": "version-old",
}


def _target_semantics_authority() -> dict[str, object]:
    """Return the same sealed target-authority shape emitted by preflight."""

    authority: dict[str, object] = {
        "target": "target",
        "source_target_contract_id": "target-contract-old",
        "problem_type": "classification",
        "event_value": 1,
        "non_event_value": 0,
        "authority_source": (
            "approved_validation_design_bound_to_sealed_analysis_partition"
        ),
        "analysis_partition_id": "analysis-partition-old",
        "analysis_partition_revision": 1,
        "validation_design_id": "design-old",
        "validation_design_version": "design-version-old",
    }
    authority["target_authority_hash"] = canonical_contract_hash(authority)
    return authority


def _seed_downstream(store: DatasetStore, results: ResultStore) -> None:
    store.set_splits(
        pd.DataFrame({"x": [1.0]}),
        pd.DataFrame({"x": [2.0]}),
        pd.Series([0], name="target"),
        pd.Series([1], name="target"),
    )
    store.meta.update(
        {
            "split_record": {"split_id": "split-old"},
            "split_config": {"test_size": 0.2},
            "validation_design": {"validation_design_id": "design-old"},
            "target_prevalence": {"event_rate": 0.5},
            "training_execution": {"training_job_id": "job-old"},
            "model_selection_decision": {"champion_model": "logreg"},
            "active_training_job_id": "job-old",
            "split_status": "current",
            "feature_manifest": {"split_status": "current"},
        }
    )
    results.set_model_artifacts({"logreg": object()})
    results.set_last_summary({"training_job_id": "job-old"})
    results.set_model_availability({"logreg": True})
    results.set_final_model(object(), {"training_job_id": "job-old"})
    results.set_scoring_reference({"training_job_id": "job-old"})


class PretrainingArtifactInvalidationTests(unittest.TestCase):
    def setUp(self) -> None:
        DATASTORE.reset_all()
        RESULTS.clear_model_artifacts()

    def tearDown(self) -> None:
        DATASTORE.reset_all()
        RESULTS.clear_model_artifacts()

    def test_shared_invalidation_clears_split_design_decision_execution_and_results(
        self,
    ) -> None:
        store = DatasetStore()
        results = ResultStore()
        _seed_downstream(store, results)
        revision = store.data_revision

        report = invalidate_downstream_training_state(
            "feature contract changed",
            store=store,
            result_store=results,
        )

        self.assertEqual(store.data_revision, revision + 1)
        self.assertEqual(report["split_status"], "stale")
        self.assertTrue(
            {
                "split_record",
                "split_config",
                "validation_design",
                "target_prevalence",
                "training_execution",
                "model_selection_decision",
                "active_training_job_id",
            }.issubset(set(report["invalidated_keys"]))
        )
        self.assertEqual(store.get_splits(), (None, None, None, None))
        self.assertEqual(store.meta["feature_manifest"]["split_status"], "stale")
        self.assertIsNone(results.get_last_summary())
        self.assertEqual(results.get_model_artifacts(), {})
        self.assertEqual(results.get_model_availability(), {})
        self.assertIsNone(results.get_final_model())
        self.assertIsNone(results.get_scoring_reference())

    def test_shared_invalidation_durably_invalidates_exact_holdout_first(
        self,
    ) -> None:
        store = DatasetStore()
        results = ResultStore()
        _seed_downstream(store, results)
        store.meta.update(IDENTITY)
        store.meta["split_record"].update(
            {
                **IDENTITY,
                "split_id": "split-old",
                "final_holdout_partition_id": "holdout-old",
                "validation_design": {
                    **IDENTITY,
                    "validation_design_id": "design-old",
                    "design_version": "design-version-old",
                },
            }
        )

        class GovernanceRepository:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def invalidate_holdout_exposure_for_partition(self, **kwargs):
                self.calls.append(kwargs)
                self.assert_store_still_current()
                return {
                    "holdout_exposure_id": "exposure-old",
                    "final_holdout_status": "invalidated",
                }

            def assert_store_still_current(self) -> None:
                self_test.assertIn("split_record", store.meta)
                self_test.assertIsNotNone(store.X_train)

        self_test = self
        repository = GovernanceRepository()
        report = invalidate_downstream_training_state(
            "feature contract changed",
            store=store,
            result_store=results,
            governance_repository=repository,
            invalidated_by="system:test",
        )
        self.assertEqual(len(repository.calls), 1)
        self.assertEqual(
            repository.calls[0]["final_holdout_partition_id"],
            "holdout-old",
        )
        self.assertEqual(repository.calls[0]["invalidated_by"], "system:test")
        self.assertEqual(
            report["durably_invalidated_holdout_exposures"][0][
                "final_holdout_status"
            ],
            "invalidated",
        )
        self.assertNotIn("split_record", store.meta)
        self.assertIsNone(store.X_train)

    def test_material_target_change_invalidates_but_identical_contract_does_not(
        self,
    ) -> None:
        store = DATASTORE.current()
        results = RESULTS.current()
        store.set_raw(
            pd.DataFrame(
                {
                    "x": [1.0, 2.0, 3.0, 4.0],
                    "target": [0, 1, 0, 1],
                }
            )
        )
        store.set_target("target")
        store.meta.update(
            {
                **IDENTITY,
                "dataset_version": IDENTITY["dataset_version_id"],
                "dataset_identity_status": "current",
                "selected_columns": ["x"],
            }
        )
        _seed_downstream(store, results)
        payload = SetTargetPayload(
            project_id=IDENTITY["project_id"],
            target="target",
            selected_columns=[],
            dataset_id=IDENTITY["dataset_id"],
            dataset_version_id=IDENTITY["dataset_version_id"],
            event_value=1,
            non_event_value=0,
        )
        # Direct unit invocation bypasses FastAPI startup, so provide the same
        # fully migrated durable authority that production startup guarantees.
        # This keeps the test isolated from both the live database and legacy
        # minimal test databases without adding a non-durable runtime fallback.
        with TemporaryDirectory(prefix="atlas-pretraining-invalidation-") as root:
            database = Database(Path(root) / "atlas.db")
            database.initialize()
            persistence = PersistenceService(database)
            with (
                patch(
                    "server.core.metadata_router.authorize_modeling_scope",
                    return_value=None,
                ),
                patch(
                    "server.core.metadata_router.assert_expected_active_identity",
                    return_value=IDENTITY,
                ),
                patch(
                    "server.core.metadata_router.schedule_checkpoint_save",
                    return_value=None,
                ),
                patch(
                    "server.core.metadata_router.get_persistence_service",
                    return_value=persistence,
                ),
                patch(
                    "server.analysis_partition.service.get_persistence_service",
                    return_value=persistence,
                ),
            ):
                changed = set_target(payload, user={})

                self.assertTrue(changed["ok"])
                self.assertNotIn("split_record", store.meta)
                self.assertNotIn("validation_design", store.meta)
                self.assertNotIn("training_execution", store.meta)
                self.assertNotIn("model_selection_decision", store.meta)
                self.assertIsNone(results.get_last_summary())

                _seed_downstream(store, results)
                unchanged_payload = payload.model_copy(
                    update={"selected_columns": []}
                )
                unchanged = set_target(unchanged_payload, user={})

                self.assertTrue(unchanged["ok"])
                self.assertEqual(
                    results.get_last_summary(),
                    {"training_job_id": "job-old"},
                )
                self.assertIn("training_execution", store.meta)

    def test_activation_injected_at_final_persistence_leaves_no_old_training_result(
        self,
    ) -> None:
        store = DATASTORE.current()
        results = RESULTS.current()
        store.set_raw(
            pd.DataFrame(
                {
                    "x": [1.0, 2.0],
                    "target": [0, 1],
                }
            )
        )
        store.set_target("target")
        store.meta.update(
            {
                **IDENTITY,
                "dataset_version": IDENTITY["dataset_version_id"],
                "dataset_identity_status": "current",
                "selected_columns": ["x"],
                "split_status": "current",
            }
        )
        service = TrainingJobService()
        job_id = "job-race"
        request = TrainingJobRequest(
            models=["logreg"],
            project_id=IDENTITY["project_id"],
            dataset_id=IDENTITY["dataset_id"],
            dataset_version_id=IDENTITY["dataset_version_id"],
            target="target",
            problem_type="classification",
        )
        target_authority = _target_semantics_authority()
        training_contract = complete_training_contract(
            {
                "project_id": IDENTITY["project_id"],
                "dataset_id": IDENTITY["dataset_id"],
                "dataset_version_id": IDENTITY["dataset_version_id"],
                "target": "target",
                "problem_type": "classification",
                "event_value": 1,
                "non_event_value": 0,
                "target_semantics_authority": target_authority,
                "target_authority_hash": target_authority[
                    "target_authority_hash"
                ],
                "source_target_contract_id": target_authority[
                    "source_target_contract_id"
                ],
                "analysis_partition_id": target_authority[
                    "analysis_partition_id"
                ],
                "analysis_partition_revision": target_authority[
                    "analysis_partition_revision"
                ],
                "feature_manifest_version": "manifest-old",
                "selected_original_features": ["x"],
                "selected_engineered_features": [],
                "preprocessing_pipeline": [],
                "split_id": "split-old",
                "validation_design_id": "design-old",
                "validation_design_version": "design-version-old",
                "training_population_id": "training-population-old",
                "selection_partition_id": "training-population-old",
                "holdout_population_id": "holdout-population-old",
                "final_holdout_partition_id": "holdout-population-old",
                "fold_definition_id": "fold-definition-old",
                "final_holdout_status": "sealed",
                "holdout_isolation_status": "verified",
                "selection_resampling_status": "not_applied",
                "random_seed": 42,
            },
            feature_manifest={
                "manifest_id": "manifest-old",
                "manifest_hash": "manifest-old",
            },
            store_meta={},
            training_job_id=job_id,
            training_run_id="training-run-race",
            created_by="owner",
            created_at="2026-07-30T00:00:00+00:00",
            primary_metric="roc_auc",
        )
        candidate_contract = build_candidate_contract(
            training_contract,
            algorithm_id="logreg",
            candidate_metrics={
                "champion_eligible": True,
                "locked_threshold": 0.5,
                "selection_metric": {
                    "selection_metric_name": "roc_auc",
                    "selection_metric_value": 0.73,
                    "selection_metric_source": "out_of_fold",
                    "selection_partition_id": "training-population-old",
                    "fold_definition_id": "fold-definition-old",
                    "fold_count": 2,
                    "fold_values": [0.72, 0.74],
                    "mean": 0.73,
                    "standard_deviation": 0.01,
                    "out_of_fold_prediction_artifact_id": "oof-race",
                    "threshold_source": "platform_governed_default_0_5",
                    "calibration_source": "not_applied",
                    "created_at": "2026-07-30T00:00:01+00:00",
                },
                "selection_integrity_status": "verified",
                "holdout_isolation_status": "verified",
                "class_encoding": {
                    "encoding": "binary_training_partition",
                    "class_labels": ["0", "1"],
                    "positive_class_label": "1",
                    "positive_class_index": 1,
                    "fit_partition": "training_only",
                },
            },
            artifact=object(),
            created_at="2026-07-30T00:00:02+00:00",
        )
        service._jobs[job_id] = {
            "job_id": job_id,
            "overall_status": "running",
            "project_id": IDENTITY["project_id"],
            "owner_user_id": "owner",
            "dataset_id": IDENTITY["dataset_id"],
            "dataset_version_id": IDENTITY["dataset_version_id"],
            "dataset_version": IDENTITY["dataset_version_id"],
            "data_revision": store.data_revision,
            "target": "target",
            "event_value": 1,
            "non_event_value": 0,
            "target_semantics_authority": target_authority,
            "target_authority_hash": target_authority[
                "target_authority_hash"
            ],
            "source_target_contract_id": target_authority[
                "source_target_contract_id"
            ],
            "analysis_partition_id": target_authority[
                "analysis_partition_id"
            ],
            "analysis_partition_revision": target_authority[
                "analysis_partition_revision"
            ],
            "partial_ranked_results": [
                {
                    "key": "logreg",
                    "name": "Logistic Regression",
                    "task": "classification",
                    "auc": 0.8,
                    "champion_eligible": True,
                    "candidate_id": candidate_contract["candidate_id"],
                    "candidate_contract": candidate_contract,
                }
            ],
            "_raw_results": {},
            "_artifacts": {"logreg": object()},
            "failed_models": [],
            "requested_models": ["logreg"],
            "completed_models": ["logreg"],
            "total_count": 1,
            "finished_count": 1,
            "created_at": "2026-07-30T00:00:00+00:00",
            "started_at": "2026-07-30T00:00:01+00:00",
            "completed_at": "2026-07-30T00:00:02+00:00",
            "runtime_ms": 1,
            "input_feature_names": ["x"],
            "trained_feature_names": ["x"],
            "engineered_feature_names": [],
            "transformed_feature_names": [],
            "feature_count": 1,
            "feature_manifest_version": "manifest-old",
            "feature_manifest_id": training_contract["feature_manifest_id"],
            "feature_manifest_hash": training_contract["feature_manifest_hash"],
            "predictor_manifest_id": training_contract["predictor_manifest_id"],
            "predictor_manifest_hash": training_contract["predictor_manifest_hash"],
            "treatment_manifest_id": training_contract["treatment_manifest_id"],
            "treatment_manifest_hash": training_contract["treatment_manifest_hash"],
            "target_contract_id": training_contract["target_contract_id"],
            "split_id": "split-old",
            "training_population_id": "training-population-old",
            "selection_partition_id": "training-population-old",
            "holdout_population_id": "holdout-population-old",
            "final_holdout_partition_id": "holdout-population-old",
            "fold_definition_id": "fold-definition-old",
            "final_holdout_status": "sealed",
            "holdout_isolation_status": "verified",
            "selection_resampling_status": "not_applied",
            "validation_design_id": "design-old",
            "validation_design_version": "design-version-old",
            "_excluded_target_features": [],
            "preflight": {
                "cross_validation_compatibility": {"effective_folds": 2}
            },
            "max_parallel_honored": 1,
            "training_run_id": training_contract["training_run_id"],
            "contract": training_contract,
            "_result_store": results,
            "_dataset_store": store,
            "_governance_repository": Mock(
                get_holdout_exposure_for_partition=Mock(return_value=None)
            ),
            "summary": None,
            "partial_results": [],
        }
        service._cancel_events[job_id] = Event()

        final_guard_reached = Event()
        activation_attempted = Event()
        calls = {"count": 0}

        def guarded_interrupt(_job_id: str) -> bool:
            calls["count"] += 1
            if calls["count"] == 2:
                final_guard_reached.set()
                self.assertTrue(activation_attempted.wait(timeout=5))
            return False

        activated_frame = pd.DataFrame(
            {
                "z": [10.0, 11.0],
                "new_target": [0, 1],
            }
        )
        new_identity = {
            "project_id": IDENTITY["project_id"],
            "dataset_id": "dataset-new",
            "dataset_version_id": "version-new",
            "dataset": {"name": "new-version"},
            "version": {"originalFilename": "new-version.csv"},
            "artifact_path": Path("unused-in-test.csv"),
        }
        persistence_service = Mock()
        persistence_service.project_dataset_activations.activate_exact.return_value = {
            "link": {
                "project_id": IDENTITY["project_id"],
                "dataset_id": new_identity["dataset_id"],
                "link_status": "active",
            },
            "active_selection": {
                "project_id": IDENTITY["project_id"],
                "dataset_id": new_identity["dataset_id"],
                "dataset_version_id": new_identity["dataset_version_id"],
                "activation_revision": 2,
                "activation_status": "active",
            },
            "workflow_effective_state": {},
            "changed": True,
        }

        activation_error: list[BaseException] = []

        def activate() -> None:
            try:
                self.assertTrue(final_guard_reached.wait(timeout=5))
                activation_attempted.set()
                activate_dataset_version(
                    new_identity["dataset_id"],
                    new_identity["dataset_version_id"],
                    project_id=IDENTITY["project_id"],
                    user={"userId": "owner"},
                )
            except BaseException as exc:  # pragma: no cover - surfaced below
                activation_error.append(exc)

        with (
            patch.object(
                service,
                "_interrupt_if_scope_changed",
                side_effect=guarded_interrupt,
            ),
            patch(
                "server.datasets.dataset_router.authorize_modeling_scope",
                return_value=None,
            ),
            patch(
                "server.datasets.dataset_router.resolve_registered_version",
                return_value=new_identity,
            ),
            patch(
                "server.datasets.dataset_router.get_persistence_service",
                return_value=persistence_service,
            ),
            patch(
                "server.datasets.dataset_router.pd.read_csv",
                return_value=activated_frame.copy(),
            ),
            patch(
                "server.datasets.dataset_router.schedule_checkpoint_save",
                return_value=None,
            ),
            patch(
                "server.datasets.dataset_router._mirror_legacy_link",
                return_value=None,
            ),
            patch(
                "server.datasets.dataset_router.DATASTORE",
                Mock(current=Mock(return_value=store)),
            ),
            patch(
                "server.datasets.dataset_router.RESULTS",
                Mock(current=Mock(return_value=results)),
            ),
        ):
            activation_thread = Thread(target=activate, daemon=True)
            activation_thread.start()
            finalized = service._finalize(
                job_id,
                request,
                pd.DataFrame({"x": [1.0]}),
                pd.Series([0], name="target"),
                final_status="complete",
            )
            activation_thread.join(timeout=5)

        self.assertTrue(finalized)
        self.assertFalse(activation_thread.is_alive())
        self.assertEqual(activation_error, [])
        self.assertEqual(store.meta["dataset_id"], "dataset-new")
        self.assertEqual(store.meta["dataset_version_id"], "version-new")
        self.assertNotIn("training_execution", store.meta)
        self.assertIsNone(results.get_last_summary())
        self.assertEqual(results.get_model_artifacts(), {})

    def test_create_rejects_activation_before_active_job_assignment(self) -> None:
        store = DATASTORE.current()
        store.set_raw(
            pd.DataFrame(
                {
                    "x": [1.0, 2.0, 3.0, 4.0],
                    "target": [0, 1, 0, 1],
                }
            )
        )
        store.set_target("target")
        store.meta.update(
            {
                **IDENTITY,
                "dataset_version": IDENTITY["dataset_version_id"],
                "dataset_identity_status": "current",
                "selected_columns": ["x"],
                "feature_manifest": {
                    **IDENTITY,
                    "manifest_hash": "manifest-old",
                },
                "split_record": {
                    **IDENTITY,
                    "split_id": "split-old",
                    "validation_design": {
                        **IDENTITY,
                        "validation_design_id": "design-old",
                        "design_version": "design-version-old",
                    },
                },
                "split_status": "current",
            }
        )
        copied_training_partition = (
            pd.DataFrame({"x": [1.0, 2.0]}),
            pd.Series([0, 1], name="target"),
            [],
        )
        preflight = {
            "ready": True,
            "blocking_errors": [],
            "recommended_parallelism": 1,
            "cross_validation_compatibility": {"effective_folds": 2},
            "calibration_compatibility": {},
            "dataset_id": IDENTITY["dataset_id"],
            "dataset_version_id": IDENTITY["dataset_version_id"],
            "feature_manifest_version": "manifest-old",
            "split_id": "split-old",
            "training_population_id": "training-population-old",
            "selection_partition_id": "training-population-old",
            "holdout_population_id": "holdout-population-old",
            "final_holdout_partition_id": "holdout-population-old",
            "fold_definition_id": "fold-definition-old",
            "final_holdout_status": "sealed",
            "holdout_isolation_status": "verified",
            "selection_resampling_status": "not_applied",
            "validation_design_id": "design-old",
            "validation_design_version": "design-version-old",
            "problem_type": "classification",
            "target": "target",
            "event_value": 1,
            "non_event_value": 0,
            "target_semantics_authority": _target_semantics_authority(),
            "selected_original_features": ["x"],
            "engineered_features": [],
        }
        request = TrainingJobRequest(
            models=["logreg"],
            project_id=IDENTITY["project_id"],
            dataset_id=IDENTITY["dataset_id"],
            dataset_version_id=IDENTITY["dataset_version_id"],
            target="target",
            problem_type="classification",
        )
        service = TrainingJobService()

        def preflight_then_activate(_request: TrainingJobRequest) -> dict:
            with store.state_lock:
                store.set_raw(
                    pd.DataFrame(
                        {
                            "z": [5.0, 6.0],
                            "new_target": [0, 1],
                        }
                    )
                )
                store.meta.update(
                    {
                        "project_id": IDENTITY["project_id"],
                        "dataset_id": "dataset-new",
                        "dataset_version_id": "version-new",
                        "dataset_version": "version-new",
                        "dataset_identity_status": "current",
                        "selected_columns": ["z"],
                    }
                )
            return preflight

        with (
            patch.object(
                service,
                "preflight",
                side_effect=preflight_then_activate,
            ),
            patch(
                "server.training.training_job_service.TRAINER._get_training_partition",
                return_value=copied_training_partition,
            ),
            patch(
                "server.training.training_job_service.validate_checkpoint_identity",
                return_value=(
                    True,
                    "",
                    {
                        "project_id": IDENTITY["project_id"],
                        "dataset_id": "dataset-new",
                        "dataset_version_id": "version-new",
                    },
                ),
            ),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "Training inputs changed during job creation",
            ):
                service.create(request, owner_user_id="owner")

        self.assertEqual(service._jobs, {})
        self.assertNotIn("active_training_job_id", store.meta)


if __name__ == "__main__":
    unittest.main()

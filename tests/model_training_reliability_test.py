from __future__ import annotations

from copy import deepcopy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException
from sklearn.base import is_classifier, is_regressor
from sklearn.datasets import make_classification
from sklearn.model_selection import StratifiedKFold

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.training.trainer import (  # noqa: E402
    AtlasXGBClassifier,
    MODEL_CATALOG,
    train_models,
)
from server.core.dataset_store import DATASTORE  # noqa: E402
from server.training import trainer_router  # noqa: E402
from server.training.candidate_contract import (  # noqa: E402
    build_candidate_contract,
    canonical_contract_hash,
    complete_training_contract,
)


class _HoldoutRepository:
    def __init__(self):
        self.records = {}

    def insert_selection_decision_if_absent(self, record):
        existing = self.records.get(record["candidate_decision_id"])
        if existing is None:
            existing = deepcopy(record)
            self.records[record["candidate_decision_id"]] = existing
        return deepcopy(existing)

    def insert_selection_decision_if_unexposed(
        self,
        record,
        *,
        final_holdout_partition_id,
    ):
        if final_holdout_partition_id != record.get(
            "final_holdout_partition_id"
        ):
            raise AssertionError("The atomic decision lock lost holdout identity.")
        return self.insert_selection_decision_if_absent(record)

    def get_selection_decision_exact(self, **identity):
        record = self.records.get(identity["candidate_decision_id"])
        if not record:
            return None
        mapped = {
            "project_id": "project_id",
            "dataset_id": "dataset_id",
            "dataset_version_id": "dataset_version_id",
            "validation_design_id": "validation_design_id",
            "validation_design_version_id": "validation_design_version_id",
            "split_id": "split_id",
            "training_run_id": "training_run_id",
            "candidate_id": "candidate_id",
        }
        if any(str(record.get(field) or "") != str(identity.get(key) or "") for key, field in mapped.items()):
            return None
        return deepcopy(record)


class _Persistence:
    def __init__(self):
        self.holdout_governance = _HoldoutRepository()


class ModelTrainingReliabilityTests(unittest.TestCase):
    IDENTITY = {
        "project_id": "project-1",
        "dataset_id": "dataset-1",
        "dataset_version_id": "version-1",
    }
    _META_KEYS = ("validation_design", "model_selection_decision")

    def setUp(self):
        self.persistence = _Persistence()
        self._persistence_patch = patch.object(
            trainer_router,
            "get_persistence_service",
            return_value=self.persistence,
        )
        self._persistence_patch.start()
        self._previous_meta = {
            key: deepcopy(DATASTORE.meta[key])
            for key in self._META_KEYS
            if key in DATASTORE.meta
        }
        DATASTORE.meta["validation_design"] = {
            **self.IDENTITY,
            "validation_design_id": "validation-design-1",
            "design_version": "validation-design-v1",
        }
        DATASTORE.meta.pop("model_selection_decision", None)

    def tearDown(self):
        self._persistence_patch.stop()
        for key in self._META_KEYS:
            DATASTORE.meta.pop(key, None)
        DATASTORE.meta.update(self._previous_meta)

    def assert_exact_identity(
        self,
        project_id,
        *,
        expected_dataset_id="",
        expected_dataset_version_id="",
        legacy_dataset_version="",
        user=None,
        **_kwargs,
    ):
        del user
        if (
            project_id != self.IDENTITY["project_id"]
            or (
                expected_dataset_id
                and expected_dataset_id != self.IDENTITY["dataset_id"]
            )
            or (
                expected_dataset_version_id
                and expected_dataset_version_id
                != self.IDENTITY["dataset_version_id"]
            )
            or (
                legacy_dataset_version
                and legacy_dataset_version
                != self.IDENTITY["dataset_version_id"]
            )
        ):
            raise HTTPException(
                status_code=409,
                detail="The requested dataset identity is stale.",
            )
        return dict(self.IDENTITY)

    def decision_request(self, **overrides):
        values = {
            **self.IDENTITY,
            "dataset_version": self.IDENTITY["dataset_version_id"],
            "training_job_id": "train-job-persisted",
            "validation_design_id": "validation-design-1",
            "validation_design_version": "validation-design-v1",
            "champion_model": "logreg",
            "challenger_models": [],
            "status": "proposed",
            "primary_metric": "auc",
            "rationale": (
                "Logistic Regression is the provisional metric leader."
            ),
        }
        values.update(overrides)
        return trainer_router.ModelSelectionDecisionRequest(**values)

    def completed_summary(self, **overrides):
        training_job_id = str(
            overrides.get("training_job_id") or "train-job-persisted"
        )
        values = {
            **self.IDENTITY,
            "training_job_id": training_job_id,
            "training_run_id": "train-run-persisted",
            "status": "complete",
            "overall_status": "complete",
            "requested_models": ["logreg"],
            "completed_models": ["logreg"],
            "failed": [],
            "total_count": 1,
            "finished_count": 1,
            "queued_models": [],
            "current_models": [],
            "ranked": [self.candidate_row(training_job_id=training_job_id)],
            "feature_manifest_version": "manifest-1",
            "split_id": "split-1",
            "validation_design_id": "validation-design-1",
            "validation_design_version": "validation-design-v1",
            "target": "target",
            "problem_type": "classification",
        }
        values.update(overrides)
        return values

    def candidate_row(self, training_job_id: str = "train-job-persisted"):
        training_contract = complete_training_contract(
            {
                **self.IDENTITY,
                "target": "target",
                "problem_type": "classification",
                "event_value": 1,
                "non_event_value": 0,
                "feature_manifest_version": "manifest-1",
                "selected_original_features": ["feature_1"],
                "selected_engineered_features": [],
                "preprocessing_pipeline": [],
                "split_id": "split-1",
                "validation_design_id": "validation-design-1",
                "validation_design_version": "validation-design-v1",
                "training_population_id": "training-population-1",
                "selection_partition_id": "training-population-1",
                "holdout_population_id": "holdout-population-1",
                "final_holdout_partition_id": "holdout-population-1",
                "fold_definition_id": "fold-definition-1",
                "final_holdout_status": "sealed",
                "holdout_isolation_status": "verified",
                "selection_resampling_status": "not_applied",
                "random_seed": 42,
                "runtime_environment": {
                    "requested_workers": 1,
                    "honored_workers": 1,
                },
            },
            feature_manifest={
                "manifest_id": "manifest-1",
                "manifest_hash": "manifest-1",
            },
            store_meta={},
            training_job_id=training_job_id,
            training_run_id="train-run-persisted",
            created_by="user-1",
            created_at="2026-07-31T12:00:00+00:00",
            primary_metric="roc_auc",
        )
        selection_metric = {
            "selection_metric_name": "roc_auc",
            "selection_metric_value": 0.78,
            "selection_metric_source": "out_of_fold",
            "selection_partition_id": "training-population-1",
            "fold_definition_id": "fold-definition-1",
            "fold_count": 3,
            "fold_values": [0.76, 0.78, 0.80],
            "mean": 0.78,
            "standard_deviation": 0.016329931618554536,
            "out_of_fold_prediction_artifact_id": "oof-logreg-1",
            "threshold_source": "platform_governed_default_0_5",
            "calibration_source": "not_applied",
            "created_at": "2026-07-31T12:01:00+00:00",
        }
        contract = build_candidate_contract(
            training_contract,
            algorithm_id="logreg",
            candidate_metrics={
                "champion_eligible": True,
                "locked_threshold": 0.5,
                "selection_metric": selection_metric,
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
            created_at="2026-07-31T12:02:00+00:00",
        )
        return {
            "key": "logreg",
            "name": "Logistic Regression",
            "champion_eligible": True,
            "auc": 0.78,
            "selection_metric": selection_metric,
            "selection_integrity_status": "verified",
            "holdout_isolation_status": "verified",
            "candidate_id": contract["candidate_id"],
            "training_job_id": contract["training_job_id"],
            "training_run_id": contract["training_run_id"],
            "candidate_contract": contract,
        }

    @staticmethod
    def classification_data(rows: int = 360):
        features, target = make_classification(
            n_samples=rows,
            n_features=10,
            n_informative=6,
            n_redundant=1,
            random_state=42,
        )
        frame = pd.DataFrame(
            features,
            columns=[f"feature_{index}" for index in range(features.shape[1])],
        )
        series = pd.Series(target, name="target")
        split = int(rows * 0.75)
        return frame.iloc[:split], frame.iloc[split:], series.iloc[:split], series.iloc[split:]

    @unittest.skipIf(
        AtlasXGBClassifier is None,
        "The optional XGBoost dependency is not installed.",
    )
    def test_xgboost_adapters_restore_sklearn_estimator_tags(self):
        self.assertTrue(is_classifier(MODEL_CATALOG["xgb"]["factory"]()))
        self.assertTrue(is_regressor(MODEL_CATALOG["xgb_reg"]["factory"]()))

    @unittest.skipIf(
        AtlasXGBClassifier is None,
        "The optional XGBoost dependency is not installed.",
    )
    def test_xgboost_grid_search_completes_with_roc_auc(self):
        X_train, X_test, y_train, y_test = self.classification_data()
        del X_test, y_test
        folds = [
            (train.tolist(), validation.tolist())
            for train, validation in StratifiedKFold(
                n_splits=3, shuffle=True, random_state=42
            ).split(X_train, y_train)
        ]
        original = MODEL_CATALOG["xgb"]
        MODEL_CATALOG["xgb"] = {
            **original,
            "factory": lambda: AtlasXGBClassifier(
                n_estimators=12,
                max_depth=3,
                learning_rate=0.1,
                n_jobs=1,
                random_state=42,
            ),
            "param_grid": {
                "model__n_estimators": [8, 12],
                "model__max_depth": [2, 3],
            },
        }
        try:
            result = train_models(
                X_train,
                y_train,
                requested_models=["xgb"],
                grid_search=True,
                grid_search_level="quick",
                cv_folds=3,
                cv_splits=folds,
                selection_partition_id="training-population-1",
                fold_definition_id="fold-definition-1",
            )
        finally:
            MODEL_CATALOG["xgb"] = original

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["failed"], [])
        row = result["summary"]["ranked"][0]
        self.assertEqual(row["key"], "xgb")
        self.assertIsNotNone(row["auc"])
        self.assertIsNotNone(row["best_score"])

    def test_small_dataset_neural_fit_uses_bounded_adaptive_profile(self):
        X_train, X_test, y_train, y_test = self.classification_data(rows=320)
        del X_test, y_test
        folds = [
            (train.tolist(), validation.tolist())
            for train, validation in StratifiedKFold(
                n_splits=3, shuffle=True, random_state=42
            ).split(X_train, y_train)
        ]
        result = train_models(
            X_train,
            y_train,
            requested_models=["mlp"],
            grid_search=False,
            cv_folds=3,
            cv_splits=folds,
            selection_partition_id="training-population-1",
            fold_definition_id="fold-definition-1",
        )

        self.assertTrue(result["ok"])
        row = result["summary"]["ranked"][0]
        profile = row["runtime_profile"]
        self.assertEqual(profile["name"], "small_data_fast")
        self.assertLessEqual(profile["max_iter"], 120)
        self.assertEqual(tuple(profile["hidden_layer_sizes"]), (32, 16))
        self.assertTrue(profile["early_stopping"])

    def test_provisional_decision_can_bind_to_persisted_completed_job(self):
        request = self.decision_request()
        summary = self.completed_summary()
        result_store = trainer_router.RESULTS.current()
        with (
            patch.object(
                trainer_router,
                "authorize_modeling_scope",
                return_value=None,
            ),
            patch.object(
                trainer_router,
                "assert_expected_active_identity",
                side_effect=self.assert_exact_identity,
            ),
            patch.object(
                trainer_router.TRAINING_JOBS,
                "get",
                return_value=None,
            ),
            patch.object(
                result_store,
                "get_last_summary",
                return_value=summary,
            ),
            patch.object(trainer_router, "audit_event"),
            patch.object(trainer_router, "schedule_checkpoint_save"),
        ):
            response = trainer_router.save_model_selection_decision(
                request,
                user={
                    "userId": "user-1",
                    "displayName": "Reliability Test",
                },
            )

        self.assertTrue(response["ok"])
        self.assertEqual(
            response["decision"]["training_job_id"],
            "train-job-persisted",
        )
        self.assertEqual(response["decision"]["champion_model"], "logreg")
        self.assertEqual(
            response["decision"]["dataset_id"],
            self.IDENTITY["dataset_id"],
        )
        self.assertEqual(
            response["decision"]["dataset_version_id"],
            self.IDENTITY["dataset_version_id"],
        )
        self.assertEqual(
            response["decision"]["dataset_version"],
            self.IDENTITY["dataset_version_id"],
        )
        self.assertEqual(
            len(self.persistence.holdout_governance.records), 1
        )
        durable_record = next(
            iter(self.persistence.holdout_governance.records.values())
        )
        self.assertEqual(
            durable_record["ranking_snapshot_hash"],
            canonical_contract_hash(
                durable_record["ranking_snapshot_json"]
            ),
        )
        selected_snapshot = next(
            row
            for row in durable_record["ranking_snapshot_json"]
            if row["candidate_id"] == durable_record["candidate_id"]
        )
        self.assertEqual(
            selected_snapshot["candidate_contract_hash"],
            durable_record["selected_candidate_contract_hash"],
        )
        with (
            patch.object(
                trainer_router,
                "authorize_modeling_scope",
                return_value=None,
            ),
            patch.object(
                trainer_router,
                "assert_expected_active_identity",
                side_effect=self.assert_exact_identity,
            ),
        ):
            recovered = trainer_router.get_model_selection_decision(
                project_id=self.IDENTITY["project_id"],
                expected_dataset_id=self.IDENTITY["dataset_id"],
                expected_dataset_version_id=self.IDENTITY[
                    "dataset_version_id"
                ],
                user={"userId": "user-1"},
            )
        self.assertEqual(
            recovered["decision_recovery_status"], "exact_durable_record"
        )
        self.assertFalse(recovered["fallback_used"])
        self.assertEqual(
            recovered["decision"]["candidate_id"],
            response["decision"]["candidate_id"],
        )

    def test_model_selection_decision_get_rejects_stale_identity(self):
        with (
            patch.object(
                trainer_router,
                "authorize_modeling_scope",
                return_value=None,
            ),
            patch.object(
                trainer_router,
                "assert_expected_active_identity",
                side_effect=self.assert_exact_identity,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                trainer_router.get_model_selection_decision(
                    project_id=self.IDENTITY["project_id"],
                    expected_dataset_id=self.IDENTITY["dataset_id"],
                    expected_dataset_version_id="version-stale",
                    user={"userId": "user-1"},
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertNotIn("model_selection_decision", DATASTORE.meta)

    def test_model_selection_decision_get_never_trusts_browser_cache_alone(self):
        stored = {
            **self.IDENTITY,
            "dataset_version": self.IDENTITY["dataset_version_id"],
            "decision_id": "model-decision-current",
        }
        DATASTORE.meta["model_selection_decision"] = stored
        with (
            patch.object(
                trainer_router,
                "authorize_modeling_scope",
                return_value=None,
            ),
            patch.object(
                trainer_router,
                "assert_expected_active_identity",
                side_effect=self.assert_exact_identity,
            ),
        ):
            response = trainer_router.get_model_selection_decision(
                project_id=self.IDENTITY["project_id"],
                expected_dataset_id=self.IDENTITY["dataset_id"],
                expected_dataset_version_id=self.IDENTITY[
                    "dataset_version_id"
                ],
                user={"userId": "user-1"},
            )

        self.assertEqual(
            {
                key: response[key]
                for key in (
                    "project_id",
                    "dataset_id",
                    "dataset_version_id",
                )
            },
            self.IDENTITY,
        )
        self.assertEqual(
            response["dataset_version"],
            self.IDENTITY["dataset_version_id"],
        )
        self.assertIsNone(response["decision"])
        self.assertEqual(
            response["decision_recovery_status"], "exact_identity_required"
        )
        self.assertFalse(response["fallback_used"])

    def test_model_selection_decision_get_rejects_stale_saved_decision(self):
        DATASTORE.meta["model_selection_decision"] = {
            **self.IDENTITY,
            "dataset_version_id": "version-stale",
            "decision_id": "model-decision-stale",
        }
        with (
            patch.object(
                trainer_router,
                "authorize_modeling_scope",
                return_value=None,
            ),
            patch.object(
                trainer_router,
                "assert_expected_active_identity",
                side_effect=self.assert_exact_identity,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                trainer_router.get_model_selection_decision(
                    project_id=self.IDENTITY["project_id"],
                    expected_dataset_id=self.IDENTITY["dataset_id"],
                    expected_dataset_version_id=self.IDENTITY[
                        "dataset_version_id"
                    ],
                    user={"userId": "user-1"},
                )

        self.assertEqual(raised.exception.status_code, 409)

    def test_model_selection_decision_post_rejects_stale_identity_before_write(
        self,
    ):
        request = self.decision_request(dataset_version_id="version-stale")
        with (
            patch.object(
                trainer_router,
                "authorize_modeling_scope",
                return_value=None,
            ),
            patch.object(
                trainer_router,
                "assert_expected_active_identity",
                side_effect=self.assert_exact_identity,
            ),
            patch.object(trainer_router.TRAINING_JOBS, "get") as get_job,
        ):
            with self.assertRaises(HTTPException) as raised:
                trainer_router.save_model_selection_decision(
                    request,
                    user={"userId": "user-1"},
                )

        self.assertEqual(raised.exception.status_code, 409)
        get_job.assert_not_called()
        self.assertNotIn("model_selection_decision", DATASTORE.meta)

    def test_model_selection_decision_post_stamps_active_identity(self):
        request = self.decision_request(training_job_id="train-job-live")
        live_summary = self.completed_summary(training_job_id="train-job-live")
        live_job = {
            **live_summary,
            "partial_ranked_results": live_summary["ranked"],
        }
        with (
            patch.object(
                trainer_router,
                "authorize_modeling_scope",
                return_value=None,
            ),
            patch.object(
                trainer_router,
                "assert_expected_active_identity",
                side_effect=self.assert_exact_identity,
            ),
            patch.object(
                trainer_router.TRAINING_JOBS,
                "get",
                return_value=live_job,
            ),
            patch.object(trainer_router, "audit_event"),
            patch.object(trainer_router, "schedule_checkpoint_save"),
        ):
            response = trainer_router.save_model_selection_decision(
                request,
                user={"userId": "user-1", "displayName": "Reliability Test"},
            )

        decision = response["decision"]
        self.assertEqual(
            {
                key: decision[key]
                for key in (
                    "project_id",
                    "dataset_id",
                    "dataset_version_id",
                )
            },
            self.IDENTITY,
        )
        self.assertEqual(
            DATASTORE.meta["model_selection_decision"][
                "dataset_version_id"
            ],
            self.IDENTITY["dataset_version_id"],
        )

    def test_model_selection_decision_rejects_partial_leaderboard(self):
        request = self.decision_request(training_job_id="train-job-live")
        live_summary = self.completed_summary(training_job_id="train-job-live")
        live_job = {
            **live_summary,
            "overall_status": "running",
            "requested_models": ["logreg", "rf"],
            "completed_models": ["logreg"],
            "total_count": 2,
            "finished_count": 1,
            "queued_models": ["rf"],
            "current_models": [],
            "partial_ranked_results": live_summary["ranked"],
        }
        with (
            patch.object(
                trainer_router,
                "authorize_modeling_scope",
                return_value=None,
            ),
            patch.object(
                trainer_router,
                "assert_expected_active_identity",
                side_effect=self.assert_exact_identity,
            ),
            patch.object(
                trainer_router.TRAINING_JOBS,
                "get",
                return_value=live_job,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                trainer_router.save_model_selection_decision(
                    request,
                    user={"userId": "user-1"},
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("partial leaderboard", str(raised.exception.detail))
        self.assertEqual(self.persistence.holdout_governance.records, {})

    def test_persisted_summary_restart_fallback_rejects_stale_version(self):
        request = self.decision_request()
        result_store = trainer_router.RESULTS.current()
        stale_summary = self.completed_summary(
            dataset_version_id="version-stale",
        )
        with (
            patch.object(
                trainer_router,
                "authorize_modeling_scope",
                return_value=None,
            ),
            patch.object(
                trainer_router,
                "assert_expected_active_identity",
                side_effect=self.assert_exact_identity,
            ),
            patch.object(
                trainer_router.TRAINING_JOBS,
                "get",
                return_value=None,
            ),
            patch.object(
                result_store,
                "get_last_summary",
                return_value=stale_summary,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                trainer_router.save_model_selection_decision(
                    request,
                    user={"userId": "user-1"},
                )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertNotIn("model_selection_decision", DATASTORE.meta)

    def test_last_train_rejects_stale_request_identity(self):
        result_store = trainer_router.RESULTS.current()
        with (
            patch.object(
                trainer_router,
                "authorize_modeling_scope",
                return_value=None,
            ),
            patch.object(
                trainer_router,
                "assert_expected_active_identity",
                side_effect=self.assert_exact_identity,
            ),
            patch.object(
                result_store,
                "get_last_summary",
                return_value=self.completed_summary(),
            ) as get_last,
        ):
            with self.assertRaises(HTTPException) as raised:
                trainer_router.get_last_train(
                    project_id=self.IDENTITY["project_id"],
                    dataset_id=self.IDENTITY["dataset_id"],
                    dataset_version_id="version-stale",
                    dataset_version="",
                    target="target",
                    problem_type="classification",
                    user={"userId": "user-1"},
                )

        self.assertEqual(raised.exception.status_code, 409)
        get_last.assert_not_called()

    def test_last_train_returns_only_exactly_scoped_summary(self):
        DATASTORE.reset_all()
        self.addCleanup(DATASTORE.reset_all)
        frame = pd.DataFrame({"feature": [0.0, 1.0, 2.0, 3.0], "target": [0, 1, 0, 1]})
        DATASTORE.set_raw(frame)
        DATASTORE.set_target("target")
        DATASTORE.set_splits(
            frame[["feature"]].iloc[:2].copy(),
            frame[["feature"]].iloc[2:].copy(),
            frame["target"].iloc[:2].copy(),
            frame["target"].iloc[2:].copy(),
        )
        validation_design = {
            **self.IDENTITY,
            "validation_design_id": "validation-design-1",
            "design_version": "validation-design-v1",
            "feature_manifest_hash": "manifest-1",
            "development_dataset": {
                "dataset_id": self.IDENTITY["dataset_id"],
                "dataset_version_id": self.IDENTITY["dataset_version_id"],
            },
        }
        DATASTORE.meta.update(
            {
                **self.IDENTITY,
                "dataset_version": self.IDENTITY["dataset_version_id"],
                "dataset_identity_status": "current",
                "split_status": "current",
                "feature_manifest": {
                    **self.IDENTITY,
                    "manifest_hash": "manifest-1",
                    "manifest_version": "manifest-1",
                },
                "validation_design": validation_design,
                "split_record": {
                    **self.IDENTITY,
                    "split_id": "split-1",
                    "feature_manifest_version": "manifest-1",
                    "validation_design": validation_design,
                },
            }
        )
        result_store = trainer_router.RESULTS.current()
        exact_summary = self.completed_summary(data_revision=DATASTORE.data_revision)
        with (
            patch.object(
                trainer_router,
                "authorize_modeling_scope",
                return_value=None,
            ),
            patch.object(
                trainer_router,
                "assert_expected_active_identity",
                side_effect=self.assert_exact_identity,
            ),
            patch.object(
                result_store,
                "get_last_summary",
                return_value=exact_summary,
            ),
        ):
            exact = trainer_router.get_last_train(
                project_id=self.IDENTITY["project_id"],
                dataset_id=self.IDENTITY["dataset_id"],
                dataset_version_id=self.IDENTITY["dataset_version_id"],
                dataset_version=self.IDENTITY["dataset_version_id"],
                target="target",
                problem_type="classification",
                user={"userId": "user-1"},
            )

        self.assertTrue(exact["ok"])
        self.assertEqual(exact["summary"], exact_summary)
        self.assertEqual(
            exact["summary"]["dataset_version_id"],
            self.IDENTITY["dataset_version_id"],
        )

        stale_summary = self.completed_summary(
            dataset_version_id="version-stale",
            data_revision=DATASTORE.data_revision,
        )
        with (
            patch.object(
                trainer_router,
                "authorize_modeling_scope",
                return_value=None,
            ),
            patch.object(
                trainer_router,
                "assert_expected_active_identity",
                side_effect=self.assert_exact_identity,
            ),
            patch.object(
                result_store,
                "get_last_summary",
                return_value=stale_summary,
            ),
        ):
            stale = trainer_router.get_last_train(
                project_id=self.IDENTITY["project_id"],
                dataset_id=self.IDENTITY["dataset_id"],
                dataset_version_id=self.IDENTITY["dataset_version_id"],
                dataset_version="",
                target="target",
                problem_type="classification",
                user={"userId": "user-1"},
            )

        self.assertTrue(stale["ok"])
        self.assertIsNone(stale["summary"])
        self.assertIn("does not match the active dataset", stale["context_error"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import random
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault(
    "ATLAS_CHECKPOINT_PATH",
    str(
        Path(tempfile.gettempdir())
        / f"atlas_validation_design_{uuid.uuid4().hex[:10]}.json"
    ),
)

from server.core.dataset_store import DATASTORE  # noqa: E402
from server.features.feature_service import (  # noqa: E402
    confirm_manifest,
    delete_feature,
    materialize_manifest,
    preview_features,
    update_manifest,
)
from server.features.feature_types import (  # noqa: E402
    FeatureDefinitionInput,
    FeatureManifestUpdateRequest,
)
from server.preprocessing.preparation_documentation_router import (  # noqa: E402
    _feature_documentation,
    _training_documentation,
    _validation_documentation,
)
from server.splitting.split_service import split_service  # noqa: E402
from server.training.training_job_types import TrainingJobRequest  # noqa: E402
from server.training.training_preflight_service import training_preflight  # noqa: E402
from server.training.trainer import train_models  # noqa: E402


def development_frame(rows: int = 240, imbalanced: bool = False) -> pd.DataFrame:
    rng = random.Random(20260728 + rows + (1 if imbalanced else 0))
    return pd.DataFrame(
        {
            "bureau_score": [500.0 + (index % 120) for index in range(rows)],
            "trade_count": [5.0 + (index % 18) for index in range(rows)],
            "account_group": [f"group-{index // 2}" for index in range(rows)],
            "observation_date": pd.date_range("2023-01-01", periods=rows, freq="D"),
            "bad_flag": [
                1 if rng.random() < (0.2 if imbalanced else 0.5) else 0
                for _ in range(rows)
            ],
        }
    )


def split_config(
    strategy: str,
    *,
    fold_method: str = "none",
    balance_method: str = "none",
) -> dict:
    return {
        "split_strategy": strategy,
        "test_size": 0.2,
        "random_seed": 42,
        "stratify": True,
        "problem_type": "classification",
        "event_value": 1,
        "balance_method": balance_method,
        "minority_share": 0.5,
        "fold_method": fold_method,
        "fold_count": 5,
        "repeats": 2,
        "shuffle": fold_method != "time_series",
        "group_field": "account_group"
        if fold_method in {"group_k_fold", "stratified_group_k_fold"}
        else "",
        "time_field": "observation_date" if fold_method == "time_series" else "",
        "inner_fold_count": 3,
    }


class FeatureExecutionContractTests(unittest.TestCase):
    def tearDown(self):
        DATASTORE.reset_all()

    def test_preview_materialize_confirm_and_stale_hash_contract(self):
        frame = development_frame()
        DATASTORE.reset_all()
        DATASTORE.set_raw(frame)
        DATASTORE.set_target("bad_flag")
        DATASTORE.meta["dataset_version"] = "heloc-contract-v1"
        DATASTORE.meta["selected_columns"] = ["bureau_score", "trade_count"]
        engineered = FeatureDefinitionInput(
            feature_id="feature-bureau-trades",
            feature_name="bureau_score_x_trade_count",
            origin="interaction",
            source_features=["bureau_score", "trade_count"],
            transformation_type="interaction",
            formula_or_rule="bureau_score * trade_count",
            output_datatype="numeric",
            config={"preserve_bureau_special_values": True},
        )
        manifest = update_manifest(
            FeatureManifestUpdateRequest(
                project_id="validation-contract-test",
                dataset_version="heloc-contract-v1",
                features=[engineered],
            )
        )
        self.assertEqual(manifest["validation_status"], "passed")
        with self.assertRaisesRegex(ValueError, "Preview"):
            materialize_manifest(manifest["manifest_hash"], "")

        preview = preview_features([engineered], 20, manifest["manifest_hash"])
        materialized = materialize_manifest(
            manifest["manifest_hash"],
            preview["preview_hash"],
        )
        self.assertEqual(
            materialized["manifest_hash"],
            materialized["materialized_manifest_hash"],
        )
        confirmed = confirm_manifest(
            manifest["manifest_hash"],
            materialized["materialization_hash"],
        )
        self.assertEqual(confirmed["confirmation_status"], "confirmed")
        self.assertEqual(
            confirmed["confirmed_manifest_hash"],
            confirmed["manifest_hash"],
        )

        changed = engineered.model_copy(
            update={
                "origin": "arithmetic",
                "transformation_type": "arithmetic",
                "formula_or_rule": "bureau_score + trade_count",
                "config": {"operation": "add"},
            }
        )
        stale = update_manifest(
            FeatureManifestUpdateRequest(
                project_id="validation-contract-test",
                dataset_version="heloc-contract-v1",
                features=[changed],
            )
        )
        self.assertNotEqual(stale["manifest_hash"], manifest["manifest_hash"])
        self.assertEqual(stale["materialization_status"], "stale")
        self.assertEqual(stale["confirmation_status"], "required")
        removed = delete_feature(
            "feature-bureau-trades",
            "validation-contract-test",
        )
        self.assertFalse(
            any(
                row.get("feature_id") == "feature-bureau-trades"
                for row in removed["features"]
            )
        )


class ValidationStrategyTests(unittest.TestCase):
    features = ["bureau_score", "trade_count"]

    def test_holdout_separate_test_test_oot_cv_and_hybrid(self):
        frame = development_frame()
        external = development_frame(80)

        holdout = split_service.make_validation_split(
            frame,
            "bad_flag",
            self.features,
            split_config("holdout_current"),
        )
        self.assertEqual(holdout.evaluation_population_role, "untouched_holdout")
        self.assertEqual(len(holdout.y_test), 48)

        for strategy in ("separate_test", "separate_test_oot"):
            result = split_service.make_validation_split(
                frame,
                "bad_flag",
                self.features,
                split_config(strategy),
                external_test_frame=external,
                external_test_target="bad_flag",
            )
            self.assertEqual(result.evaluation_population_role, "separate_test")
            self.assertEqual(len(result.y_test), len(external))

        cv_only = split_service.make_validation_split(
            frame,
            "bad_flag",
            self.features,
            split_config("cross_validation", fold_method="stratified_k_fold"),
        )
        self.assertEqual(cv_only.evaluation_population_role, "cv_reference_fold")
        self.assertEqual(len(cv_only.fold_architecture["folds"]), 5)

        hybrid = split_service.make_validation_split(
            frame,
            "bad_flag",
            self.features,
            split_config("hybrid", fold_method="stratified_k_fold"),
        )
        self.assertEqual(hybrid.evaluation_population_role, "untouched_holdout")
        self.assertEqual(hybrid.fold_architecture["fold_count"], 5)
        self.assertTrue(hybrid.fold_architecture["fold_size_consistent"])
        for fold in hybrid.fold_architecture["folds"]:
            self.assertGreater(fold["validation_distribution"]["events"], 0)
            self.assertGreater(
                fold["validation_distribution"]["non_events"],
                0,
            )

    def test_group_time_repeated_and_nested_fold_architectures(self):
        frame = development_frame()
        for method in (
            "group_k_fold",
            "stratified_group_k_fold",
            "time_series",
            "repeated_stratified_k_fold",
            "nested_cv",
        ):
            result = split_service.make_validation_split(
                frame,
                "bad_flag",
                self.features,
                split_config("hybrid", fold_method=method),
            )
            architecture = result.fold_architecture
            self.assertTrue(architecture["enabled"])
            self.assertEqual(architecture["method"], method)
            if method == "repeated_stratified_k_fold":
                self.assertEqual(len(architecture["folds"]), 10)
            if method == "nested_cv":
                self.assertTrue(architecture["nested"])
                self.assertEqual(architecture["inner_folds"], 3)

    def test_balancing_changes_training_only_and_never_holdout(self):
        frame = development_frame(300, imbalanced=True)
        baseline = split_service.make_validation_split(
            frame,
            "bad_flag",
            self.features,
            split_config("holdout_current"),
        )
        oversampled = split_service.make_validation_split(
            frame,
            "bad_flag",
            self.features,
            split_config("holdout_current", balance_method="oversample"),
        )
        self.assertEqual(
            baseline.test_distribution,
            oversampled.test_distribution,
        )
        self.assertEqual(
            baseline.validation_index,
            oversampled.validation_index,
        )
        self.assertGreater(oversampled.synthetic_rows_added, 0)
        self.assertEqual(oversampled.rows_removed, 0)


class TrainingAndDocumentationContractTests(unittest.TestCase):
    def tearDown(self):
        DATASTORE.reset_all()

    def _configure_approved_design(self):
        frame = development_frame()
        result = split_service.make_validation_split(
            frame,
            "bad_flag",
            ["bureau_score", "trade_count"],
            split_config("hybrid", fold_method="stratified_k_fold"),
        )
        DATASTORE.reset_all()
        DATASTORE.set_raw(frame)
        DATASTORE.set_target("bad_flag")
        DATASTORE.set_splits(
            result.X_train,
            result.X_test,
            result.y_train,
            result.y_test,
        )
        DATASTORE.meta["dataset_version"] = "heloc-validation-v1"
        DATASTORE.meta["source"] = {"datasetId": "heloc-train"}
        DATASTORE.meta["split_status"] = "current"
        DATASTORE.meta["feature_manifest"] = {
            "manifest_version": "fm-heloc-v1",
            "manifest_hash": "fm-heloc-v1",
            "dataset_version": "heloc-validation-v1",
            "validation_status": "passed",
            "materialization_status": "current",
            "materialized_manifest_hash": "fm-heloc-v1",
            "materialization_hash": "mat-heloc-v1",
            "confirmation_status": "confirmed",
            "confirmed_manifest_hash": "fm-heloc-v1",
            "features": [
                {
                    "feature_name": feature,
                    "origin": "original",
                    "selected": True,
                    "eligibility_status": "eligible",
                    "materialization_status": "materialized",
                }
                for feature in ["bureau_score", "trade_count"]
            ],
            "pipeline_steps": [],
        }
        validation_design = {
            "validation_design_id": "validation-design-heloc",
            "design_version": "validation-design-v1",
            "development_dataset_version": "heloc-validation-v1",
            "strategy": "hybrid",
            "status": "approved",
        }
        gates = {
            "strategy_selected": True,
            "dataset_versions_pinned": True,
            "schema_compatibility_verified": True,
            "target_mapping_verified": True,
            "feature_manifest_current": True,
            "target_source_excluded": True,
            "populations_created": True,
            "event_coverage_sufficient": True,
            "holdout_protection_confirmed": True,
            "cv_design_approved": True,
            "balancing_policy_recorded": True,
        }
        DATASTORE.meta["validation_design"] = validation_design
        DATASTORE.meta["split_record"] = {
            "split_id": "split-heloc-v1",
            "dataset_version": "heloc-validation-v1",
            "feature_manifest_version": "fm-heloc-v1",
            "selected_features": ["bureau_score", "trade_count"],
            "validation_design": validation_design,
            "cv_design": {
                "method": "stratified_k_fold",
                "fold_count": 5,
                "repeats": 1,
                "shuffle": True,
            },
            "fold_architecture": result.fold_architecture,
            "cv_execution_splits": result.fold_architecture[
                "execution_splits"
            ],
            "completion_gates": gates,
            "balancing_policy": {
                "method": "none",
                "scope": "training_population_only",
            },
            "evaluation_population_role": "untouched_holdout",
            "training_population_id": "train-pop-heloc-v1",
            "holdout_population_id": "holdout-pop-heloc-v1",
        }
        return validation_design

    def _request(self, folds: int) -> TrainingJobRequest:
        return TrainingJobRequest(
            project_id="validation-contract-test",
            dataset_id="heloc-train",
            dataset_version="heloc-validation-v1",
            target="bad_flag",
            event_value=1,
            non_event_value=0,
            problem_type="classification",
            feature_manifest_version="fm-heloc-v1",
            split_id="split-heloc-v1",
            validation_design_id="validation-design-heloc",
            validation_design_version="validation-design-v1",
            models=["logreg"],
            k_folds=folds,
            candidate_strategy="transparent_baseline",
        )

    def test_training_folds_are_locked_to_validation_design(self):
        self._configure_approved_design()
        wrong = training_preflight(self._request(3))
        self.assertFalse(wrong["ready"])
        self.assertTrue(
            any(
                "locked by Validation Design at 5 folds" in message
                for message in wrong["blocking_errors"]
            )
        )
        current = training_preflight(self._request(5))
        self.assertTrue(current["ready"], current["blocking_errors"])
        self.assertTrue(
            current["cross_validation_compatibility"][
                "owned_by_validation_design"
            ]
        )
        self.assertTrue(
            current["cross_validation_compatibility"]["read_only"]
        )
        self.assertEqual(
            current["cross_validation_compatibility"]["effective_folds"],
            5,
        )
        self.assertTrue(
            current["cross_validation_compatibility"]["exact_fold_bindings"]
        )
        self.assertEqual(
            current["cross_validation_compatibility"]["execution_fold_count"],
            5,
        )

    def test_grid_search_executes_exact_approved_fold_positions(self):
        frame = development_frame()
        split = split_service.make_validation_split(
            frame,
            "bad_flag",
            ["bureau_score", "trade_count"],
            split_config("hybrid", fold_method="stratified_k_fold"),
        )
        exact_splits = [
            (
                fold["train_positions"],
                fold["validation_positions"],
            )
            for fold in split.fold_architecture["execution_splits"]
        ]
        result = train_models(
            X_train=split.X_train,
            X_test=split.X_test,
            y_train=split.y_train,
            y_test=split.y_test,
            requested_models=["logreg"],
            grid_search=True,
            grid_search_level="quick",
            cv_folds=5,
            cv_splits=exact_splits,
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["summary"]["ranked"][0]["key"], "logreg")
        self.assertIsNotNone(
            result["summary"]["ranked"][0].get("best_score")
        )

    def test_mdd_stale_state_follows_design_training_and_decision_bindings(self):
        design = self._configure_approved_design()
        manifest_doc = _feature_documentation(
            DATASTORE.meta["feature_manifest"],
            "heloc-validation-v1",
        )
        validation_doc = _validation_documentation(
            design,
            DATASTORE.meta["split_record"],
            manifest_doc,
            "heloc-validation-v1",
        )
        self.assertEqual(manifest_doc["status"], "confirmed")
        self.assertEqual(validation_doc["status"], "confirmed")
        execution = {
            "training_job_id": "train-job-heloc-v1",
            "status": "complete",
            "candidate_strategy": "transparent_baseline",
            "requested_models": ["logreg"],
            "completed_models": ["logreg"],
            "failed_models": [],
            "ranked_candidates": [{"key": "logreg", "auc": 0.74}],
            "dataset_version": "heloc-validation-v1",
            "feature_manifest_version": "fm-heloc-v1",
            "split_id": "split-heloc-v1",
            "validation_design_id": "validation-design-heloc",
            "validation_design_version": "validation-design-v1",
            "contract": {
                "tuning_configuration": {"grid_search": False, "folds": 5},
                "cv_design": {"method": "stratified_k_fold", "fold_count": 5},
                "calibration_configuration": {"requested": False},
                "runtime_environment": {"execution_mode": "local_background_workers"},
            },
        }
        decision = {
            "training_job_id": "train-job-heloc-v1",
            "validation_design_version": "validation-design-v1",
            "feature_manifest_version": "fm-heloc-v1",
            "champion_model": "logreg",
            "challenger_models": [],
            "status": "proposed",
        }
        training_doc = _training_documentation(
            execution,
            decision,
            manifest_doc,
            validation_doc,
        )
        self.assertEqual(training_doc["status"], "confirmed")
        self.assertEqual(training_doc["tuning_policy"]["folds"], 5)
        stale_decision = {**decision, "training_job_id": "older-job"}
        stale_doc = _training_documentation(
            execution,
            stale_decision,
            manifest_doc,
            validation_doc,
        )
        self.assertEqual(stale_doc["status"], "stale")
        self.assertTrue(
            any(
                "champion/challenger proposal is stale" in reason
                for reason in stale_doc["stale_reasons"]
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

from __future__ import annotations

from copy import deepcopy
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.training.candidate_contract import (  # noqa: E402
    CandidateContractError,
    assert_candidate_contract_intact,
    assert_training_contract_intact,
    build_candidate_contract,
    canonical_contract_hash,
    complete_training_contract,
)


class _Estimator:
    pass


class Phase2B1CandidateContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = {
            "project_id": "project-1",
            "dataset_id": "dataset-1",
            "dataset_version_id": "version-1",
            "data_revision": 7,
            "target": "bad_flag",
            "problem_type": "classification",
            "event_value": 1,
            "non_event_value": 0,
            "feature_manifest_version": "feature-hash-1",
            "selected_original_features": ["income", "age"],
            "selected_engineered_features": ["income_to_age"],
            "preprocessing_pipeline": [{"type": "median"}],
            "split_id": "split-1",
            "validation_design_id": "design-1",
            "validation_design_version": "design-version-1",
            "training_population_id": "training-population-1",
            "selection_partition_id": "training-population-1",
            "holdout_population_id": "holdout-population-1",
            "final_holdout_partition_id": "holdout-population-1",
            "fold_definition_id": "fold-definition-1",
            "final_holdout_status": "sealed",
            "holdout_isolation_status": "verified",
            "selection_resampling_status": "not_applied",
            "random_seed": 42,
            "calibration_configuration": {"requested": True},
            "runtime_environment": {
                "requested_workers": 2,
                "honored_workers": 2,
            },
        }
        self.feature_manifest = {
            "manifest_version": "feature-manifest-1",
            "manifest_hash": "feature-hash-1",
        }
        self.store_meta = {
            "outlier_application": {"method": "iqr", "threshold": 1.5},
            "missing_application": {"method": "median"},
            "missing_validation": {"status": "confirmed"},
        }

    def training_contract(self):
        return complete_training_contract(
            self.base,
            feature_manifest=self.feature_manifest,
            store_meta=self.store_meta,
            training_job_id="train-job-1",
            training_run_id="train-run-1",
            created_by="user-1",
            created_at="2026-07-31T12:00:00+00:00",
            primary_metric="roc_auc",
        )

    def candidate_metrics(self, **overrides):
        payload = {
            "champion_eligible": True,
            "locked_threshold": 0.5,
            "selection_metric": {
                "selection_metric_name": "roc_auc",
                "selection_metric_value": 0.73,
                "selection_metric_source": "out_of_fold",
                "selection_partition_id": "training-population-1",
                "fold_definition_id": "fold-definition-1",
                "fold_count": 3,
                "fold_values": [0.70, 0.73, 0.76],
                "mean": 0.73,
                "standard_deviation": 0.024494897427831803,
                "out_of_fold_prediction_artifact_id": "oof-1",
                "threshold_source": "platform_governed_default_0_5",
                "calibration_source": "not_applied",
                "created_at": "2026-07-31T12:04:00+00:00",
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
        }
        payload.update(overrides)
        return payload

    def test_training_contract_contains_exact_governed_lineage(self):
        contract = self.training_contract()

        assert_training_contract_intact(contract)
        self.assertEqual(contract["project_id"], "project-1")
        self.assertEqual(contract["dataset_id"], "dataset-1")
        self.assertEqual(contract["dataset_version_id"], "version-1")
        self.assertEqual(contract["training_dataset_id"], "dataset-1")
        self.assertEqual(contract["training_dataset_version_id"], "version-1")
        self.assertEqual(contract["target_name"], "bad_flag")
        self.assertEqual(contract["positive_class"], 1)
        self.assertEqual(contract["feature_manifest_id"], "feature-manifest-1")
        self.assertEqual(contract["feature_manifest_hash"], "feature-hash-1")
        self.assertTrue(contract["predictor_manifest_id"].startswith("pm-"))
        self.assertTrue(contract["treatment_manifest_id"].startswith("tm-"))
        self.assertEqual(contract["training_job_id"], "train-job-1")
        self.assertEqual(contract["training_run_id"], "train-run-1")
        self.assertEqual(contract["ranking_metric"], "roc_auc")
        self.assertEqual(contract["created_by"], "user-1")
        self.assertIn("python_version", contract["runtime_environment"])
        self.assertIn("package_versions", contract["runtime_environment"])
        self.assertEqual(contract["worker_configuration"]["requested_workers"], 2)
        self.assertEqual(contract["worker_configuration"]["honored_workers"], 2)

    def test_training_contract_tampering_is_rejected(self):
        contract = self.training_contract()
        contract["dataset_version_id"] = "version-2"

        with self.assertRaisesRegex(
            CandidateContractError, "modified"
        ):
            assert_training_contract_intact(contract)

    def test_candidate_contract_is_frozen_and_complete(self):
        contract = build_candidate_contract(
            self.training_contract(),
            algorithm_id="logreg",
            candidate_metrics=self.candidate_metrics(
                best_params={"C": 0.5}
            ),
            artifact=_Estimator(),
            created_at="2026-07-31T12:05:00+00:00",
        )

        assert_candidate_contract_intact(contract)
        self.assertTrue(contract["candidate_id"].startswith("candidate-"))
        self.assertEqual(contract["training_run_id"], "train-run-1")
        self.assertEqual(contract["algorithm_id"], "logreg")
        self.assertEqual(contract["target_name"], "bad_flag")
        self.assertEqual(contract["problem_type"], "classification")
        self.assertEqual(contract["feature_manifest_version"], "feature-hash-1")
        self.assertEqual(contract["validation_design_version"], "design-version-1")
        self.assertEqual(contract["hyperparameter_manifest"], {"C": 0.5})
        self.assertEqual(contract["candidate_state"], "complete")
        self.assertTrue(contract["champion_eligible"])
        self.assertEqual(
            contract["threshold_configuration"]["locked_threshold"],
            0.5,
        )
        self.assertEqual(
            contract["threshold_configuration"]["threshold_source"],
            "platform_governed_default_0_5",
        )
        self.assertEqual(
            contract["threshold_configuration"]["threshold_locked_at"],
            "2026-07-31T12:05:00+00:00",
        )
        self.assertLess(
            contract["selection_metric"]["created_at"],
            contract["threshold_configuration"]["threshold_locked_at"],
        )
        self.assertEqual(
            contract["threshold_configuration"]["threshold_policy_hash"],
            canonical_contract_hash(
                {
                    "locked_threshold": 0.5,
                    "threshold_source": "platform_governed_default_0_5",
                    "threshold_locked_at": "2026-07-31T12:05:00+00:00",
                    "selection_threshold_tuned": False,
                }
            ),
        )

    def test_candidate_lineage_cannot_change_after_completion(self):
        contract = build_candidate_contract(
            self.training_contract(),
            algorithm_id="logreg",
            candidate_metrics=self.candidate_metrics(),
            artifact=_Estimator(),
            created_at="2026-07-31T12:05:00+00:00",
        )
        mutated = deepcopy(contract)
        mutated["split_id"] = "split-2"

        with self.assertRaisesRegex(
            CandidateContractError, "modified"
        ):
            assert_candidate_contract_intact(mutated)

    def test_deleted_required_fields_remain_rejected_after_rehash(self):
        contract = build_candidate_contract(
            self.training_contract(),
            algorithm_id="logreg",
            candidate_metrics=self.candidate_metrics(),
            artifact=_Estimator(),
            created_at="2026-07-31T12:05:00+00:00",
        )
        for field in (
            "predictor_manifest_id",
            "treatment_manifest_id",
            "feature_manifest_id",
            "algorithm_version",
            "target_definition",
            "runtime_environment",
            "worker_configuration",
        ):
            mutated = deepcopy(contract)
            mutated.pop(field)
            mutated.pop("contract_hash", None)
            mutated["contract_hash"] = canonical_contract_hash(mutated)
            with self.subTest(field=field), self.assertRaises(CandidateContractError):
                assert_candidate_contract_intact(mutated)

    def test_candidate_id_is_exact_run_and_algorithm_identity(self):
        training = self.training_contract()
        first = build_candidate_contract(
            training,
            algorithm_id="logreg",
            candidate_metrics=self.candidate_metrics(),
            artifact=_Estimator(),
            created_at="2026-07-31T12:05:00+00:00",
        )
        replay = build_candidate_contract(
            training,
            algorithm_id="logreg",
            candidate_metrics=self.candidate_metrics(),
            artifact=_Estimator(),
            created_at="2026-07-31T12:06:00+00:00",
        )
        challenger = build_candidate_contract(
            training,
            algorithm_id="random_forest",
            candidate_metrics=self.candidate_metrics(),
            artifact=_Estimator(),
            created_at="2026-07-31T12:06:00+00:00",
        )

        self.assertEqual(first["candidate_id"], replay["candidate_id"])
        self.assertNotEqual(first["candidate_id"], challenger["candidate_id"])

    def test_unsupervised_candidate_remains_champion_ineligible(self):
        contract = build_candidate_contract(
            self.training_contract(),
            algorithm_id="isolation_forest",
            candidate_metrics=self.candidate_metrics(champion_eligible=False),
            artifact=_Estimator(),
            created_at="2026-07-31T12:05:00+00:00",
        )

        assert_candidate_contract_intact(contract)
        self.assertFalse(contract["champion_eligible"])

    def test_treatment_manifest_hash_changes_with_policy(self):
        first = self.training_contract()
        changed_meta = deepcopy(self.store_meta)
        changed_meta["missing_application"]["method"] = "mean"
        second = complete_training_contract(
            self.base,
            feature_manifest=self.feature_manifest,
            store_meta=changed_meta,
            training_job_id="train-job-1",
            training_run_id="train-run-1",
            created_by="user-1",
            created_at="2026-07-31T12:00:00+00:00",
            primary_metric="roc_auc",
        )

        self.assertNotEqual(
            first["treatment_manifest_hash"],
            second["treatment_manifest_hash"],
        )


if __name__ == "__main__":
    unittest.main()

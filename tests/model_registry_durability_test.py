"""Focused Phase 2B1 durable Model Registry tests.

All persistence and artifact writes are isolated under the repository's
ignored .tmp directory; the checked-in runtime database/artifact root is never
opened.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from pathlib import Path
import shutil
import sys
import unittest
import uuid
from unittest import mock

from fastapi import HTTPException


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from server.model_registry import model_artifacts  # noqa: E402
from server.model_registry import model_registry_service as registry  # noqa: E402
from server.persistence.db import (  # noqa: E402
    Database,
    MIGRATIONS_PATH,
    SCHEMA_PATH,
    json_dumps,
    now_iso,
)
from server.persistence.service import PersistenceService  # noqa: E402
from server.training.candidate_contract import canonical_contract_hash  # noqa: E402


class ModelRegistryDurabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = REPO_ROOT / ".tmp" / f"registry-durability-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.database_path = self.root / "atlas.db"
        self.database = Database(self.database_path)
        self.assertTrue(self.database.initialize()["ok"])
        self.service = PersistenceService(self.database)
        self.user = {
            "userId": "registry-owner",
            "displayName": "Registry Owner",
            "email": "registry-owner@example.invalid",
            "role": "data_scientist",
        }
        self.service.sync_user(self.user)
        for project_id in ("project-one", "project-two"):
            self.service.projects.ensure(
                project_id,
                {
                    "owner_user_id": self.user["userId"],
                    "created_by": self.user["userId"],
                },
            )
        self.artifact_root = (self.root / "artifacts").resolve()
        self.artifact_root.mkdir()
        self.previous_artifact_root = model_artifacts.ARTIFACT_ROOT
        model_artifacts.ARTIFACT_ROOT = self.artifact_root
        self.persistence_patch = mock.patch.object(
            registry,
            "get_persistence_service",
            return_value=self.service,
        )
        self.authorization_patch = mock.patch.object(
            registry,
            "authorize_modeling_scope",
            side_effect=lambda user, project_id, permission: project_id,
        )
        self.persistence_mock = self.persistence_patch.start()
        self.authorization_mock = self.authorization_patch.start()

    def tearDown(self) -> None:
        self.authorization_patch.stop()
        self.persistence_patch.stop()
        model_artifacts.ARTIFACT_ROOT = self.previous_artifact_root
        shutil.rmtree(self.root, ignore_errors=True)

    def _candidate_contract(
        self,
        *,
        suffix: str = "one",
        project_id: str = "project-one",
        algorithm: str = "logreg",
        problem_type: str = "classification",
    ) -> dict:
        is_regression = problem_type == "regression"
        target_name = "MedHouseVal" if is_regression else "bad_flag"
        metric_name = "rmse" if is_regression else "roc_auc"
        metric_value = 1.2 if is_regression else 0.78
        fold_values = [1.1, 1.2, 1.3] if is_regression else [0.76, 0.78, 0.80]
        threshold_source = (
            "not_applicable" if is_regression else "training_oof"
        )
        threshold_policy = {
            "locked_threshold": None if is_regression else 0.5,
            "threshold_source": threshold_source,
            "threshold_locked_at": "2026-07-31T12:00:00+00:00",
            "selection_threshold_tuned": False,
        }
        threshold_policy["threshold_policy_hash"] = canonical_contract_hash(
            threshold_policy
        )
        contract = {
            "project_id": project_id,
            "dataset_id": "dataset-heloc",
            "dataset_version_id": "dv-registered-001",
            "target_name": target_name,
            "target_definition": {
                "target_name": target_name,
                "problem_type": problem_type,
                "positive_class": None if is_regression else 1,
                "negative_class": None if is_regression else 0,
            },
            "target_contract_id": "target-contract-001",
            "positive_class": None if is_regression else 1,
            "predictor_manifest_id": "predictors-001",
            "predictor_manifest_hash": "predictors-hash-001",
            "treatment_manifest_id": "treatments-001",
            "treatment_manifest_hash": "treatments-hash-001",
            "feature_manifest_id": "features-001",
            "feature_manifest_hash": "features-hash-001",
            "materialization_id": f"materialization-{suffix}",
            "validation_design_id": "validation-001",
            "validation_design_version": "validation-version-001",
            "split_id": "split-001",
            "training_job_id": f"job-{suffix}",
            "training_run_id": f"run-{suffix}",
            "candidate_id": f"candidate-{suffix}",
            "algorithm_id": algorithm,
            "algorithm_class": (
                "sklearn.linear_model.LinearRegression"
                if is_regression
                else "sklearn.linear_model.LogisticRegression"
            ),
            "algorithm_version": "1.7.0",
            "hyperparameter_manifest": {} if is_regression else {"C": 1.0},
            "calibration_configuration": {"requested": False},
            "ranking_metric": metric_name,
            "selection_metric": {
                "name": metric_name,
                "value": metric_value,
                "source": "out_of_fold",
                "partition_id": f"training-oof-{suffix}",
                "fold_definition_id": f"fold-definition-{suffix}",
                "fold_count": 3,
                "fold_values": fold_values,
                "mean": metric_value,
                "standard_deviation": 0.02,
                "out_of_fold_prediction_artifact_id": f"oof-{suffix}",
                "threshold_source": threshold_source,
                "calibration_source": threshold_source,
                "created_at": "2026-07-31T12:00:00+00:00",
            },
            "selection_integrity_status": "verified",
            "holdout_isolation_status": "verified",
            "final_holdout_status": "sealed",
            "selection_resampling_status": "not_applied",
            "threshold_configuration": threshold_policy,
            "class_encoding": (
                {}
                if is_regression
                else {
                    "class_labels": [0, 1],
                    "positive_class_label": 1,
                    "positive_class_index": 1,
                    "fit_partition": "training_only",
                }
            ),
            "training_population_id": f"training-population-{suffix}",
            "final_holdout_partition_id": f"split-001:test:{suffix}",
            "fold_definition_id": f"fold-definition-{suffix}",
            "created_by": self.user["userId"],
            "created_at": "2026-07-31T12:00:00+00:00",
            "runtime_environment": {
                "python_version": "3.12",
                "package_versions": {"scikit-learn": "1.7.0"},
                "worker_configuration": {"max_parallel": 1},
            },
            "random_seed": 42,
            "candidate_state": "complete",
            "champion_eligible": True,
        }
        contract["contract_hash"] = canonical_contract_hash(contract)
        return contract

    def _seed_governance(
        self,
        contract: dict,
        *,
        suffix: str,
        evaluation_package_id: str,
    ) -> str:
        decision_id = f"decision-{suffix}"
        exposure_id = f"exposure-{suffix}"
        source_metric = contract["selection_metric"]
        metric = {
            "name": source_metric.get("name")
            or source_metric.get("selection_metric_name"),
            "value": source_metric.get("value")
            if source_metric.get("value") is not None
            else source_metric.get("selection_metric_value"),
            "source": source_metric.get("source")
            or source_metric.get("selection_metric_source"),
            "partition_id": source_metric.get("partition_id")
            or source_metric.get("selection_partition_id"),
            "fold_definition_id": source_metric["fold_definition_id"],
            "fold_count": source_metric["fold_count"],
            "fold_values": source_metric["fold_values"],
            "mean": source_metric.get("mean")
            if source_metric.get("mean") is not None
            else source_metric.get("selection_metric_mean"),
            "standard_deviation": source_metric.get("standard_deviation")
            if source_metric.get("standard_deviation") is not None
            else source_metric.get("selection_metric_std"),
            "out_of_fold_prediction_artifact_id": source_metric[
                "out_of_fold_prediction_artifact_id"
            ],
            "threshold_source": source_metric["threshold_source"],
            "calibration_source": source_metric["calibration_source"],
            "created_at": source_metric["created_at"],
        }
        lock_time = "2026-07-31T12:01:00+00:00"
        threshold_policy = contract["threshold_configuration"]
        threshold_time = threshold_policy["threshold_locked_at"]
        opened_time = "2026-07-31T12:02:00+00:00"
        governance = self.service.holdout_governance
        ranking_snapshot = [
            {
                "candidate_id": contract["candidate_id"],
                "selection_metric": metric["value"],
                "candidate_contract_hash": contract["contract_hash"],
            }
        ]
        decision_record = {
                "candidate_decision_id": decision_id,
                "decision_status": "locked",
                "project_id": contract["project_id"],
                "dataset_id": contract["dataset_id"],
                "dataset_version_id": contract["dataset_version_id"],
                "feature_manifest_id": contract["feature_manifest_id"],
                "feature_manifest_hash": contract["feature_manifest_hash"],
                "treatment_manifest_id": contract["treatment_manifest_id"],
                "treatment_manifest_hash": contract["treatment_manifest_hash"],
                "materialization_id": contract["materialization_id"],
                "validation_design_id": contract["validation_design_id"],
                "validation_design_version_id": contract[
                    "validation_design_version"
                ],
                "split_id": contract["split_id"],
                "final_holdout_partition_id": contract[
                    "final_holdout_partition_id"
                ],
                "training_job_id": contract["training_job_id"],
                "training_run_id": contract["training_run_id"],
                "candidate_id": contract["candidate_id"],
                "selected_candidate_contract_hash": contract[
                    "contract_hash"
                ],
                "selection_metric_name": metric["name"],
                "selection_metric_value": metric["value"],
                "selection_metric_source": metric["source"],
                "selection_metric_created_at": metric["created_at"],
                "selection_partition_id": metric["partition_id"],
                "fold_definition_id": metric["fold_definition_id"],
                "fold_count": metric["fold_count"],
                "fold_values_json": metric["fold_values"],
                "selection_metric_mean": metric["mean"],
                "selection_metric_std": metric["standard_deviation"],
                "out_of_fold_prediction_artifact_id": metric[
                    "out_of_fold_prediction_artifact_id"
                ],
                "threshold_source": metric["threshold_source"],
                "locked_threshold": threshold_policy["locked_threshold"],
                "threshold_locked_at": threshold_time,
                "threshold_policy_hash": threshold_policy[
                    "threshold_policy_hash"
                ],
                "calibration_source": metric["calibration_source"],
                "ranking_snapshot_json": ranking_snapshot,
                "ranking_snapshot_hash": canonical_contract_hash(
                    ranking_snapshot
                ),
                "selection_rationale": "Highest governed OOF ROC-AUC.",
                "selection_locked_at": lock_time,
                "actor": self.user["userId"],
                "selection_integrity_status": "verified",
                "selection_integrity_reason": "Training-only OOF evidence verified.",
                "holdout_isolation_status": "verified",
                "holdout_isolation_reason": "Final holdout remained sealed.",
                "integrity_classified_at": lock_time,
                "integrity_classified_by": self.user["userId"],
                "decision_contract_hash": f"decision-contract-{suffix}",
                "created_at": lock_time,
            }
        governance.insert_selection_decision_if_absent(
            decision_record
        )
        governance.seal_holdout_exposure_if_absent(
            {
                "holdout_exposure_id": exposure_id,
                "project_id": contract["project_id"],
                "dataset_id": contract["dataset_id"],
                "dataset_version_id": contract["dataset_version_id"],
                "validation_design_id": contract["validation_design_id"],
                "validation_design_version_id": contract[
                    "validation_design_version"
                ],
                "split_id": contract["split_id"],
                "final_holdout_partition_id": contract[
                    "final_holdout_partition_id"
                ],
                "candidate_decision_id": decision_id,
                "candidate_id": contract["candidate_id"],
                "feature_manifest_id": contract["feature_manifest_id"],
                "feature_manifest_hash": contract["feature_manifest_hash"],
                "treatment_manifest_id": contract["treatment_manifest_id"],
                "treatment_manifest_hash": contract[
                    "treatment_manifest_hash"
                ],
                "materialization_id": contract["materialization_id"],
                "selection_locked_at": lock_time,
                "exposure_contract_hash": f"exposure-contract-{suffix}",
                "created_at": lock_time,
            }
        )
        governance.mark_holdout_opened(
            exposure_id,
            opened_by=self.user["userId"],
            opened_at=opened_time,
        )
        canonical_lineage = {
            "project_id": contract["project_id"],
            "dataset_id": contract["dataset_id"],
            "dataset_version_id": contract["dataset_version_id"],
            "training_job_id": contract["training_job_id"],
            "training_run_id": contract["training_run_id"],
            "candidate_id": contract["candidate_id"],
            "candidate_decision_id": decision_id,
            "validation_design_id": contract["validation_design_id"],
            "validation_design_version_id": contract[
                "validation_design_version"
            ],
            "split_id": contract["split_id"],
            "feature_manifest_id": contract["feature_manifest_id"],
            "feature_manifest_hash": contract["feature_manifest_hash"],
            "treatment_manifest_id": contract["treatment_manifest_id"],
            "treatment_manifest_hash": contract["treatment_manifest_hash"],
            "materialization_id": f"materialization-{suffix}",
            "evaluation_package_id": evaluation_package_id,
            "holdout_exposure_id": exposure_id,
            "final_holdout_partition_id": contract[
                "final_holdout_partition_id"
            ],
        }
        package_payload = {
            "evaluation_package_id": evaluation_package_id,
            "candidate_decision_id": decision_id,
            "holdout_exposure_id": exposure_id,
            "final_holdout_partition_id": contract[
                "final_holdout_partition_id"
            ],
            "project_id": contract["project_id"],
            "dataset_id": contract["dataset_id"],
            "dataset_version_id": contract["dataset_version_id"],
            "training_run_id": contract["training_run_id"],
            "candidate_id": contract["candidate_id"],
            "completion_content_hash": canonical_contract_hash(
                {"status": "complete", "suffix": suffix}
            ),
            "holdout_prediction_digest": f"holdout-predictions-{suffix}",
        }
        package_content_hash = canonical_contract_hash(package_payload)
        package_contract_hash = canonical_contract_hash(
            {
                "evaluation_package_id": evaluation_package_id,
                "completion_content_hash": package_payload[
                    "completion_content_hash"
                ],
                "holdout_prediction_digest": package_payload[
                    "holdout_prediction_digest"
                ],
                "candidate_decision_id": decision_id,
                "holdout_exposure_id": exposure_id,
                "content_hash": package_content_hash,
            }
        )
        governance.insert_evaluation_package_if_absent(
            {
                "evaluation_package_id": evaluation_package_id,
                "package_status": "complete",
                "project_id": contract["project_id"],
                "dataset_id": contract["dataset_id"],
                "dataset_version_id": contract["dataset_version_id"],
                "feature_manifest_id": contract["feature_manifest_id"],
                "feature_manifest_hash": contract["feature_manifest_hash"],
                "treatment_manifest_id": contract["treatment_manifest_id"],
                "treatment_manifest_hash": contract["treatment_manifest_hash"],
                "materialization_id": contract["materialization_id"],
                "validation_design_id": contract["validation_design_id"],
                "validation_design_version_id": contract[
                    "validation_design_version"
                ],
                "split_id": contract["split_id"],
                "training_job_id": contract["training_job_id"],
                "training_run_id": contract["training_run_id"],
                "candidate_id": contract["candidate_id"],
                "selected_candidate_contract_hash": contract[
                    "contract_hash"
                ],
                "candidate_decision_id": decision_id,
                "holdout_exposure_id": exposure_id,
                "final_holdout_partition_id": contract[
                    "final_holdout_partition_id"
                ],
                "selection_metric_name": metric["name"],
                "selection_metric_value": metric["value"],
                "selection_metric_source": metric["source"],
                "selection_metric_created_at": metric["created_at"],
                "out_of_fold_prediction_artifact_id": metric[
                    "out_of_fold_prediction_artifact_id"
                ],
                "locked_threshold": threshold_policy["locked_threshold"],
                "threshold_source": threshold_policy["threshold_source"],
                "threshold_policy_hash": threshold_policy[
                    "threshold_policy_hash"
                ],
                "selection_integrity_status": "verified",
                "selection_evidence_json": {
                    "selection_metric": metric,
                    "selection_metric_created_at": metric["created_at"],
                    "out_of_fold_prediction_artifact_id": metric[
                        "out_of_fold_prediction_artifact_id"
                    ],
                },
                "final_holdout_evidence_json": {
                    "partition_id": contract["final_holdout_partition_id"]
                },
                "metric_definitions_json": {"roc_auc": "final holdout"},
                "threshold_policy_json": threshold_policy,
                "isolation_evidence_json": {"status": "verified"},
                "canonical_lineage_json": canonical_lineage,
                "holdout_isolation_status": "verified",
                "final_holdout_status": "evaluated",
                "threshold_locked_at": threshold_time,
                "holdout_exposed_at": opened_time,
                "recommendations_derived_from_final_holdout": False,
                "package_integrity_status": "verified",
                "evaluation_package_contract_hash": package_contract_hash,
                "content_hash": package_content_hash,
                "package_payload_json": package_payload,
                "created_by": self.user["userId"],
                "created_at": opened_time,
            }
        )
        governance.mark_holdout_evaluated(
            exposure_id,
            evaluation_package_id=evaluation_package_id,
            evaluated_at="2026-07-31T12:03:00+00:00",
        )
        return decision_id

    def _publish(
        self,
        *,
        suffix: str = "one",
        project_id: str = "project-one",
        model_name: str = "HELOC champion",
        fitted_object: object | None = None,
        idempotency_key: str | None = None,
        contract: dict | None = None,
        lineage_validation_design_version: str | None = None,
        caller_evaluation_summary: dict | None = None,
        before_promotion=None,
    ) -> dict:
        contract = deepcopy(
            contract
            or self._candidate_contract(
                suffix=suffix,
                project_id=project_id,
            )
        )
        evaluation_package_id = f"evalpkg-{suffix}"
        candidate_decision_id = self._seed_governance(
            contract,
            suffix=suffix,
            evaluation_package_id=evaluation_package_id,
        )
        if before_promotion is not None:
            before_promotion(
                candidate_decision_id,
                evaluation_package_id,
                f"exposure-{suffix}",
            )
        problem_type = contract["target_definition"]["problem_type"]
        metric_name = contract["selection_metric"].get(
            "name",
            contract["selection_metric"].get("selection_metric_name"),
        )
        metric_value = contract["selection_metric"].get(
            "value",
            contract["selection_metric"].get("selection_metric_value"),
        )
        return registry.create_model_version(
            self.user,
            project_id,
            model_name=model_name,
            problem_type=problem_type,
            algorithm=contract["algorithm_id"],
            algorithm_version=contract.get("algorithm_version"),
            fitted_object=(
                fitted_object
                if fitted_object is not None
                else {"coefficient": 1.25, "candidate": contract["candidate_id"]}
            ),
            hyperparameters=contract["hyperparameter_manifest"],
            training_parameters={"random_seed": 42},
            metrics_summary={metric_name: metric_value},
            evaluation_summary=(
                caller_evaluation_summary
                if caller_evaluation_summary is not None
                else {"evaluationPackageId": evaluation_package_id}
            ),
            interpretation_summary={"status": "complete"},
            training_run_id=contract["training_run_id"],
            dataset_id=contract["dataset_id"],
            dataset_version_id=contract["dataset_version_id"],
            feature_manifest_version=contract["feature_manifest_hash"],
            training_timestamp=contract["created_at"],
            lineage={
                "project_id": contract["project_id"],
                "dataset_id": contract["dataset_id"],
                "dataset_version_id": contract["dataset_version_id"],
                "candidate_id": contract["candidate_id"],
                "training_job_id": contract["training_job_id"],
                "training_run_id": contract["training_run_id"],
                "feature_manifest_version": contract["feature_manifest_hash"],
                "validation_design_id": contract["validation_design_id"],
                "validation_design_version": (
                    lineage_validation_design_version
                    or contract["validation_design_version"]
                ),
                "split_id": contract["split_id"],
                "target": contract["target_name"],
                "problem_type": problem_type,
                "evaluation_package_id": evaluation_package_id,
                "candidate_decision_id": candidate_decision_id,
            },
            candidate_contract=contract,
            evaluation_package_id=evaluation_package_id,
            idempotency_key=idempotency_key,
        )

    def _artifact_path(self, result: dict) -> Path:
        row = self.service.model_versions.get(
            result["modelVersion"]["modelVersionId"]
        )
        self.assertIsNotNone(row)
        return model_artifacts.resolve_model_artifact_path(
            row["artifact_reference"]
        )

    def test_atomic_publication_persists_verified_contract_and_champion(self) -> None:
        result = self._publish(idempotency_key="promotion-one")
        version = result["modelVersion"]
        model = result["model"]
        promotion = result["promotion"]

        self.assertEqual(promotion["status"], "finalized")
        self.assertTrue(promotion["artifactVerified"])
        self.assertEqual(promotion["designation"], "champion")
        self.assertEqual(promotion["championStatus"], "champion")
        self.assertEqual(model["currentVersionId"], version["modelVersionId"])
        self.assertEqual(model["currentVersionGeneration"], 1)
        self.assertEqual(version["publicationStatus"], "finalized")
        self.assertEqual(version["lineageStatus"], "verified")
        self.assertEqual(version["candidateDecisionId"], "decision-one")
        self.assertEqual(version["candidateDecisionStatus"], "locked")
        self.assertEqual(
            version["candidateDecisionContractHash"],
            "decision-contract-one",
        )
        self.assertEqual(version["selectionMetricName"], "roc_auc")
        self.assertEqual(version["selectionMetricValue"], 0.78)
        self.assertEqual(version["selectionMetricSource"], "out_of_fold")
        self.assertEqual(
            version["selectionMetricCreatedAt"],
            "2026-07-31T12:00:00+00:00",
        )
        self.assertEqual(version["outOfFoldPredictionArtifactId"], "oof-one")
        self.assertEqual(
            version["selectedCandidateContractHash"],
            version["candidateContractHash"],
        )
        self.assertEqual(version["selectionIntegrityStatus"], "verified")
        self.assertEqual(version["holdoutExposureId"], "exposure-one")
        self.assertEqual(
            version["finalHoldoutPartitionId"],
            "split-001:test:one",
        )
        self.assertEqual(version["finalHoldoutStatus"], "evaluated")
        self.assertEqual(version["holdoutIsolationStatus"], "verified")
        package = self.service.holdout_governance.get_evaluation_package(
            "evalpkg-one"
        )
        self.assertEqual(
            version["evaluationPackageContractHash"],
            package["evaluation_package_contract_hash"],
        )
        self.assertEqual(
            version["evaluationPackageContentHash"],
            package["content_hash"],
        )
        self.assertEqual(version["lockedThreshold"], 0.5)
        self.assertEqual(version["thresholdSource"], "training_oof")
        self.assertEqual(
            version["thresholdPolicyHash"],
            package["threshold_policy_hash"],
        )
        self.assertEqual(
            version["evaluationPackageIntegrityStatus"],
            "verified",
        )
        self.assertEqual(version["promotionReadinessStatus"], "verified")
        self.assertEqual(version["lineage"]["datasetVersionId"], "dv-registered-001")
        self.assertEqual(version["lineage"]["candidateId"], "candidate-one")
        self.assertEqual(
            version["lineage"]["validationDesignVersion"],
            version["lineage"]["candidateContract"][
                "validation_design_version"
            ],
        )
        self.assertEqual(
            version["modelContract"]["artifactChecksum"], version["checksum"]
        )
        self.assertTrue(self._artifact_path(result).is_file())

    def test_snake_case_candidate_selection_metric_matches_durable_columns(self) -> None:
        contract = self._candidate_contract(suffix="snake")
        metric = dict(contract["selection_metric"])
        metric["selection_metric_name"] = metric.pop("name")
        metric["selection_metric_value"] = metric.pop("value")
        metric["selection_metric_source"] = metric.pop("source")
        metric["selection_partition_id"] = metric.pop("partition_id")
        contract["selection_metric"] = metric
        contract["contract_hash"] = canonical_contract_hash(
            {key: value for key, value in contract.items() if key != "contract_hash"}
        )
        result = self._publish(
            suffix="snake",
            contract=contract,
            idempotency_key="snake-selection-metric",
        )
        version = result["modelVersion"]
        self.assertEqual(version["selectionMetricName"], "roc_auc")
        self.assertEqual(version["selectionMetricValue"], 0.78)
        self.assertEqual(version["selectionMetricSource"], "out_of_fold")

    def test_identical_retry_returns_same_version_without_duplicate_artifact(self) -> None:
        first = self._publish(idempotency_key="stable-key")
        second = self._publish(idempotency_key="stable-key")
        self.assertEqual(
            first["modelVersion"]["modelVersionId"],
            second["modelVersion"]["modelVersionId"],
        )
        self.assertTrue(second["promotion"]["idempotentReplay"])
        self.assertEqual(len(self.service.model_versions.list(include_archived=True)), 1)
        artifact_dirs = [
            path
            for path in self.artifact_root.iterdir()
            if path.is_dir() and path.name.startswith("mv-")
        ]
        self.assertEqual(len(artifact_dirs), 1)

    def test_regression_retry_preserves_nullable_threshold_identity(self) -> None:
        contract = self._candidate_contract(
            suffix="regression-retry",
            algorithm="linreg",
            problem_type="regression",
        )
        first = self._publish(
            suffix="regression-retry",
            contract=contract,
            idempotency_key="regression-stable-key",
        )
        second = self._publish(
            suffix="regression-retry",
            contract=contract,
            idempotency_key="regression-stable-key",
        )

        first_version = first["modelVersion"]
        second_version = second["modelVersion"]
        self.assertEqual(
            first_version["modelVersionId"],
            second_version["modelVersionId"],
        )
        self.assertIsNone(second_version["lockedThreshold"])
        self.assertEqual(second_version["thresholdSource"], "not_applicable")
        self.assertTrue(second["promotion"]["idempotentReplay"])
        self.assertEqual(
            len(self.service.model_versions.list(include_archived=True)),
            1,
        )

    def test_browser_package_claims_are_replaced_by_exact_durable_package(self) -> None:
        result = self._publish(
            idempotency_key="durable-package-authority",
            caller_evaluation_summary={
                "evaluationPackageId": "evalpkg-one",
                "status": "complete",
                "selectionIntegrityStatus": "browser-claimed",
                "holdoutIsolationStatus": "browser-claimed",
                "finalHoldoutEvidence": {"metric": 999.0},
            },
        )
        summary = result["modelVersion"]["evaluationSummary"]
        self.assertEqual(summary["selectionIntegrityStatus"], "verified")
        self.assertEqual(summary["holdoutIsolationStatus"], "verified")
        self.assertEqual(
            summary["finalHoldoutEvidence"],
            {"partition_id": "split-001:test:one"},
        )
        self.assertNotIn("metric", summary["finalHoldoutEvidence"])

    def test_promotion_rejects_tampered_threshold_candidate_and_oof_provenance(self) -> None:
        mutations = (
            ("threshold", "locked_threshold", 0.61),
            ("candidate-hash", "selected_candidate_contract_hash", "tampered-contract"),
            ("metric-time", "selection_metric_created_at", "2026-07-31T12:00:30+00:00"),
            ("oof-artifact", "out_of_fold_prediction_artifact_id", "oof-substituted"),
        )
        for suffix, field, value in mutations:
            with self.subTest(field=field):
                exact = self.service.holdout_governance.get_selection_decision_exact

                def tampered_decision(**kwargs):
                    record = dict(exact(**kwargs))
                    record[field] = value
                    return record

                with mock.patch.object(
                    self.service.holdout_governance,
                    "get_selection_decision_exact",
                    side_effect=tampered_decision,
                ), mock.patch.object(
                    model_artifacts, "stage_model_artifact"
                ) as stage, self.assertRaises(HTTPException) as raised:
                    self._publish(
                        suffix=suffix,
                        idempotency_key=f"reject-{suffix}",
                    )
                self.assertEqual(raised.exception.status_code, 409)
                stage.assert_not_called()

    def test_promotion_rejects_tampered_package_payload_and_invalidated_exposure(self) -> None:
        exact_package = self.service.holdout_governance.get_evaluation_package_exact

        def tampered_package(**kwargs):
            package = dict(exact_package(**kwargs))
            payload = dict(package["package_payload_json"])
            payload["holdout_prediction_digest"] = "tampered"
            package["package_payload_json"] = payload
            return package

        with mock.patch.object(
            self.service.holdout_governance,
            "get_evaluation_package_exact",
            side_effect=tampered_package,
        ), mock.patch.object(
            model_artifacts, "stage_model_artifact"
        ) as stage, self.assertRaises(HTTPException) as raised:
            self._publish(
                suffix="tampered-payload",
                idempotency_key="reject-tampered-package",
            )
        self.assertEqual(raised.exception.status_code, 409)
        stage.assert_not_called()

        def invalidate(_decision_id, _package_id, exposure_id):
            self.service.holdout_governance.invalidate_holdout_exposure(
                exposure_id,
                reason="Candidate changed after holdout exposure.",
                invalidated_by=self.user["userId"],
            )

        with mock.patch.object(model_artifacts, "stage_model_artifact") as stage:
            with self.assertRaises(HTTPException) as raised:
                self._publish(
                    suffix="invalidated-exposure",
                    idempotency_key="reject-invalidated-exposure",
                    before_promotion=invalidate,
                )
        self.assertEqual(raised.exception.status_code, 409)
        stage.assert_not_called()

    def test_atomic_publication_rechecks_package_hash_under_write_lock(self) -> None:
        original = self.service.model_versions.publish_finalized
        with self.database.transaction() as connection:
            connection.execute(
                "DROP TRIGGER trg_evaluation_packages_immutable"
            )

        def race(model_record, version_record):
            package_id = version_record["evaluation_package_id"]
            package = self.service.holdout_governance.get_evaluation_package(
                package_id
            )
            payload = dict(package["package_payload_json"])
            payload["holdout_prediction_digest"] = "changed-after-precheck"
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE evaluation_packages SET package_payload_json = ? WHERE evaluation_package_id = ?",
                    (json_dumps(payload, {}), package_id),
                )
            return original(model_record, version_record)

        with mock.patch.object(
            self.service.model_versions,
            "publish_finalized",
            side_effect=race,
        ):
            with self.assertRaises(HTTPException) as raised:
                self._publish(
                    suffix="package-race",
                    idempotency_key="package-race",
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            self.service.model_versions.list(include_archived=True), []
        )
        self.assertFalse(
            any(
                path.name.startswith("mv-")
                for path in self.artifact_root.iterdir()
            )
        )
        staging = self.artifact_root / ".staging"
        self.assertFalse(staging.exists() and any(staging.iterdir()))

    def test_recovery_quarantines_when_exact_durable_package_is_unavailable(self) -> None:
        result = self._publish(idempotency_key="missing-governance-recovery")
        version_id = result["modelVersion"]["modelVersionId"]
        with mock.patch.object(
            self.service.holdout_governance,
            "get_evaluation_package",
            return_value=None,
        ):
            with self.assertRaises(HTTPException) as error:
                registry.get_recovery_status(
                    self.user,
                    "project-one",
                    version_id,
                )
        self.assertEqual(error.exception.status_code, 409)
        quarantined = self.service.model_versions.get(version_id)
        self.assertEqual(quarantined["publication_status"], "quarantined")
        self.assertIsNone(
            self.service.models.get(quarantined["model_id"])[
                "current_version_id"
            ]
        )

    def test_recovery_quarantines_tampered_package_or_invalidated_exposure(self) -> None:
        first = self._publish(
            suffix="recovery-payload",
            idempotency_key="recovery-payload",
        )
        first_id = first["modelVersion"]["modelVersionId"]
        package = self.service.holdout_governance.get_evaluation_package(
            "evalpkg-recovery-payload"
        )
        exact_package = self.service.holdout_governance.get_evaluation_package_exact

        def tampered_package(**kwargs):
            durable = dict(exact_package(**kwargs))
            payload = dict(durable["package_payload_json"])
            payload["holdout_prediction_digest"] = "tampered-after-promotion"
            durable["package_payload_json"] = payload
            return durable

        with mock.patch.object(
            self.service.holdout_governance,
            "get_evaluation_package_exact",
            side_effect=tampered_package,
        ), self.assertRaises(HTTPException) as raised:
            registry.get_recovery_status(self.user, "project-one", first_id)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            self.service.model_versions.get(first_id)["publication_status"],
            "quarantined",
        )

        second = self._publish(
            suffix="recovery-exposure",
            idempotency_key="recovery-exposure",
        )
        second_id = second["modelVersion"]["modelVersionId"]
        self.service.holdout_governance.invalidate_holdout_exposure(
            "exposure-recovery-exposure",
            reason="Candidate changed after publication.",
            invalidated_by=self.user["userId"],
        )
        with self.assertRaises(HTTPException) as raised:
            registry.get_recovery_status(self.user, "project-one", second_id)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            self.service.model_versions.get(second_id)["publication_status"],
            "quarantined",
        )

    def test_conflicting_retry_fails_without_second_version_or_artifact(self) -> None:
        self._publish(idempotency_key="conflict-key")
        with self.assertRaises(HTTPException) as raised:
            self._publish(
                fitted_object={"coefficient": 999.0},
                idempotency_key="conflict-key",
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(len(self.service.model_versions.list(include_archived=True)), 1)
        self.assertEqual(
            len(
                [
                    path
                    for path in self.artifact_root.iterdir()
                    if path.is_dir() and path.name.startswith("mv-")
                ]
            ),
            1,
        )

    def test_serialization_failure_creates_no_row_or_artifact(self) -> None:
        with mock.patch.object(
            model_artifacts,
            "stage_model_artifact",
            side_effect=ValueError("serialization failed"),
        ):
            with self.assertRaises(HTTPException) as raised:
                self._publish(idempotency_key="serialize-failure")
        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(self.service.model_versions.list(include_archived=True), [])

    def test_final_verification_failure_compensates_finalized_artifact(self) -> None:
        with mock.patch.object(
            model_artifacts,
            "verify_model_artifact",
            side_effect=ValueError("verification failed"),
        ):
            with self.assertRaises(HTTPException) as raised:
                self._publish(idempotency_key="verify-failure")
        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(self.service.model_versions.list(include_archived=True), [])
        self.assertFalse(
            any(path.name.startswith("mv-") for path in self.artifact_root.iterdir())
        )

    def test_database_failure_compensates_finalized_artifact(self) -> None:
        with mock.patch.object(
            self.service.model_versions,
            "publish_finalized",
            side_effect=RuntimeError("database failed"),
        ):
            with self.assertRaises(HTTPException) as raised:
                self._publish(idempotency_key="database-failure")
        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(self.service.model_versions.list(include_archived=True), [])
        self.assertFalse(
            any(path.name.startswith("mv-") for path in self.artifact_root.iterdir())
        )

    def test_exact_artifact_recovers_after_persistence_service_restart(self) -> None:
        result = self._publish(idempotency_key="restart-key")
        version_id = result["modelVersion"]["modelVersionId"]
        restarted_service = PersistenceService(Database(self.database_path))
        self.persistence_mock.return_value = restarted_service
        loaded = registry.load_version_artifact(
            self.user,
            version_id,
            expected_project_id="project-one",
        )
        self.assertEqual(loaded["candidate"], "candidate-one")
        status = registry.get_recovery_status(
            self.user,
            "project-one",
            version_id,
        )
        self.assertEqual(status["modelVersionId"], version_id)
        self.assertTrue(status["artifactVerified"])

    def test_exact_context_resolver_returns_only_verified_current_version(self) -> None:
        result = self._publish(idempotency_key="resolver-key")
        resolved = registry.resolve_current_version_by_exact_context(
            self.user,
            project_id="project-one",
            dataset_id="dataset-heloc",
            dataset_version_id="dv-registered-001",
            target_name="bad_flag",
        )
        self.assertEqual(resolved["status"], "ready")
        self.assertEqual(
            resolved["modelVersionId"],
            result["modelVersion"]["modelVersionId"],
        )
        self.assertTrue(resolved["artifactVerified"])
        not_ready = registry.resolve_current_version_by_exact_context(
            self.user,
            project_id="project-one",
            dataset_id="dataset-heloc",
            dataset_version_id="dv-another-exact-version",
            target_name="bad_flag",
        )
        self.assertEqual(not_ready["status"], "not_ready")
        self.assertIsNone(not_ready["modelVersion"])

    def test_exact_context_resolver_rejects_ambiguous_current_champions(self) -> None:
        self._publish(
            suffix="one",
            model_name="HELOC model A",
            idempotency_key="ambiguous-one",
        )
        self._publish(
            suffix="two",
            model_name="HELOC model B",
            idempotency_key="ambiguous-two",
        )
        with self.assertRaises(HTTPException) as raised:
            registry.resolve_current_version_by_exact_context(
                self.user,
                project_id="project-one",
                dataset_id="dataset-heloc",
                dataset_version_id="dv-registered-001",
                target_name="bad_flag",
            )
        self.assertEqual(raised.exception.status_code, 409)

    def test_corrupt_artifact_fails_closed_quarantines_and_clears_champion(self) -> None:
        result = self._publish(idempotency_key="tamper-key")
        version_id = result["modelVersion"]["modelVersionId"]
        with open(self._artifact_path(result), "ab") as handle:
            handle.write(b"tamper")
        with self.assertRaises(HTTPException) as raised:
            registry.get_recovery_status(self.user, "project-one", version_id)
        self.assertEqual(raised.exception.status_code, 409)
        row = self.service.model_versions.get(version_id)
        model = self.service.models.get(result["model"]["modelId"])
        self.assertEqual(row["publication_status"], "quarantined")
        self.assertIsNotNone(row["quarantined_at"])
        self.assertIsNone(model["current_version_id"])
        self.assertEqual(model["current_version_generation"], 2)

    def test_missing_exact_artifact_never_falls_back_to_newer_champion(self) -> None:
        first = self._publish(suffix="one", idempotency_key="missing-one")
        second = self._publish(suffix="two", idempotency_key="missing-two")
        first_id = first["modelVersion"]["modelVersionId"]
        second_id = second["modelVersion"]["modelVersionId"]
        self._artifact_path(first).unlink()
        with self.assertRaises(HTTPException) as raised:
            registry.load_version_artifact(
                self.user,
                first_id,
                expected_project_id="project-one",
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            self.service.model_versions.get(first_id)["publication_status"],
            "quarantined",
        )
        current_model = self.service.models.get(second["model"]["modelId"])
        self.assertEqual(current_model["current_version_id"], second_id)
        recovered_second = registry.load_version_artifact(
            self.user,
            second_id,
            expected_project_id="project-one",
        )
        self.assertEqual(recovered_second["candidate"], "candidate-two")

    def test_authorization_and_exact_project_checks_precede_artifact_access(self) -> None:
        result = self._publish(idempotency_key="acl-key")
        version_id = result["modelVersion"]["modelVersionId"]
        with mock.patch.object(
            model_artifacts,
            "verify_model_artifact",
        ) as verify:
            with mock.patch.object(
                registry,
                "authorize_modeling_scope",
                side_effect=HTTPException(status_code=403, detail="Forbidden"),
            ):
                with self.assertRaises(HTTPException) as raised:
                    registry.load_version_artifact(
                        {"userId": "stranger"},
                        version_id,
                        expected_project_id="project-one",
                    )
            self.assertEqual(raised.exception.status_code, 403)
            verify.assert_not_called()
        with mock.patch.object(
            model_artifacts,
            "verify_model_artifact",
        ) as verify:
            with self.assertRaises(HTTPException) as mismatch:
                registry.load_version_artifact(
                    self.user,
                    version_id,
                    expected_project_id="project-two",
                )
            self.assertEqual(mismatch.exception.status_code, 409)
            verify.assert_not_called()

    def test_legacy_unresolved_version_is_quarantined_and_never_recovered(self) -> None:
        timestamp = now_iso()
        model = self.service.models.upsert(
            {
                "model_id": "model-legacy",
                "project_id": "project-one",
                "name": "Legacy model",
                "problem_type": "classification",
                "status": "active",
                "owner_user_id": self.user["userId"],
                "created_at": timestamp,
                "updated_at": timestamp,
                "current_version_id": None,
                "archived": False,
                "tags_json": [],
            }
        )
        legacy = self.service.model_versions.insert(
            {
                "model_version_id": "mv-legacy",
                "model_id": model["model_id"],
                "version_number": 1,
                "project_id": "project-one",
                "algorithm": "logreg",
                "artifact_reference": None,
                "lineage_json": {"projectId": "project-one"},
                "created_by": self.user["userId"],
                "created_at": timestamp,
            }
        )
        model["current_version_id"] = legacy["model_version_id"]
        self.service.models.upsert(model)
        with self.assertRaises(HTTPException) as raised:
            registry.get_recovery_status(
                self.user,
                "project-one",
                legacy["model_version_id"],
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            self.service.model_versions.get("mv-legacy")["publication_status"],
            "quarantined",
        )
        self.assertIsNone(
            self.service.models.get("model-legacy")["current_version_id"]
        )

    def test_forward_migration_retains_legacy_row_and_clears_legacy_champion(self) -> None:
        legacy_database = Database(self.root / "legacy-before-0017.db")
        with legacy_database.transaction() as connection:
            connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            for migration in sorted(MIGRATIONS_PATH.glob("*.sql")):
                if migration.name >= "0017_model_registry_durability.sql":
                    continue
                connection.executescript(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (migration.name, now_iso()),
                )
            timestamp = now_iso()
            connection.execute(
                """
                INSERT INTO models (
                  model_id, project_id, name, problem_type, status,
                  created_at, updated_at, current_version_id, archived, tags_json
                ) VALUES (?, NULL, ?, ?, 'active', ?, ?, ?, 0, '[]')
                """,
                (
                    "model-pre-0017",
                    "Pre-migration model",
                    "classification",
                    timestamp,
                    timestamp,
                    "mv-pre-0017",
                ),
            )
            connection.execute(
                """
                INSERT INTO model_versions (
                  model_version_id, model_id, version_number, project_id,
                  dataset_version_id, algorithm, artifact_reference,
                  artifact_format, checksum, lineage_json, created_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, '{}', ?)
                """,
                (
                    "mv-pre-0017",
                    "model-pre-0017",
                    "project-retired",
                    "timestamp-pseudo-version",
                    "logreg",
                    "legacy/model.joblib",
                    "joblib",
                    "unverified",
                    timestamp,
                ),
            )
        self.assertTrue(legacy_database.initialize()["ok"])
        legacy_service = PersistenceService(legacy_database)
        version = legacy_service.model_versions.get("mv-pre-0017")
        model = legacy_service.models.get("model-pre-0017")
        self.assertIsNotNone(version)
        self.assertEqual(version["publication_status"], "legacy_unresolved")
        self.assertEqual(version["lineage_status"], "legacy_unresolved")
        self.assertIn("Legacy model version", version["quarantine_reason"])
        self.assertIsNone(model["current_version_id"])
        self.assertEqual(model["current_version_generation"], 1)

    def test_champion_compare_and_set_rejects_stale_generation(self) -> None:
        first = self._publish(suffix="one", idempotency_key="cas-one")
        second = self._publish(suffix="two", idempotency_key="cas-two")
        model_id = second["model"]["modelId"]
        first_version_id = first["modelVersion"]["modelVersionId"]
        with self.assertRaises(HTTPException) as stale:
            registry.promote_champion(
                self.user,
                model_id,
                first_version_id,
                expected_generation=1,
            )
        self.assertEqual(stale.exception.status_code, 409)
        promoted = registry.promote_champion(
            self.user,
            model_id,
            first_version_id,
            expected_generation=2,
        )
        self.assertEqual(promoted["currentVersionId"], first_version_id)
        self.assertEqual(promoted["currentVersionGeneration"], 3)

    def test_version_archive_atomically_clears_the_champion_pointer(self) -> None:
        result = self._publish(idempotency_key="archive-key")
        version_id = result["modelVersion"]["modelVersionId"]
        archived = registry.archive_version(self.user, version_id)
        model = self.service.models.get(result["model"]["modelId"])
        self.assertIsNotNone(archived["archivedAt"])
        self.assertIsNone(model["current_version_id"])
        self.assertEqual(model["current_version_generation"], 2)

    def test_concurrent_identical_promotions_create_one_version(self) -> None:
        def publish() -> dict:
            return self._publish(idempotency_key="concurrent-key")

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: publish(), range(2)))
        version_ids = {
            result["modelVersion"]["modelVersionId"] for result in results
        }
        self.assertEqual(len(version_ids), 1)
        self.assertEqual(len(self.service.model_versions.list(include_archived=True)), 1)
        self.assertEqual(
            sum(bool(result["promotion"]["idempotentReplay"]) for result in results),
            1,
        )

    def test_concurrent_distinct_champion_promotions_leave_one_consistent_pointer(self) -> None:
        suffixes = ("concurrent-a", "concurrent-b")

        def publish(suffix: str) -> dict:
            return self._publish(
                suffix=suffix,
                idempotency_key=f"promotion-{suffix}",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(publish, suffixes))

        model_ids = {result["model"]["modelId"] for result in results}
        version_ids = {
            result["modelVersion"]["modelVersionId"] for result in results
        }
        self.assertEqual(len(model_ids), 1)
        self.assertEqual(len(version_ids), 2)
        self.assertTrue(
            all(
                result["promotion"]["status"] == "finalized"
                and result["promotion"]["artifactVerified"] is True
                for result in results
            )
        )

        model = self.service.models.get(next(iter(model_ids)))
        self.assertIsNotNone(model)
        self.assertIn(model["current_version_id"], version_ids)
        self.assertEqual(model["current_version_generation"], 2)
        persisted_versions = self.service.model_versions.list(
            model_id=next(iter(model_ids)),
            include_archived=True,
        )
        self.assertEqual(
            {row["model_version_id"] for row in persisted_versions},
            version_ids,
        )

    def test_crash_window_orphan_reconciliation_removes_only_unknown_version(self) -> None:
        durable = self._publish(idempotency_key="durable-key")
        durable_path = self._artifact_path(durable)
        orphan = model_artifacts.write_model_artifact(
            "mv-orphan",
            {"orphan": True},
        )
        orphan_path = model_artifacts.resolve_model_artifact_path(orphan["path"])
        os.utime(orphan_path.parent, (0, 0))
        outcome = registry.reconcile_orphan_artifacts(minimum_age_seconds=0)
        self.assertEqual(outcome["orphanArtifactsRemoved"], 1)
        self.assertFalse(orphan_path.exists())
        self.assertTrue(durable_path.exists())

    def test_modified_candidate_contract_fails_before_artifact_staging(self) -> None:
        contract = self._candidate_contract()
        contract["dataset_version_id"] = "dv-conflicting"
        with mock.patch.object(
            model_artifacts,
            "stage_model_artifact",
        ) as stage:
            with self.assertRaises(HTTPException) as raised:
                self._publish(contract=contract, idempotency_key="bad-contract")
            self.assertEqual(raised.exception.status_code, 409)
            stage.assert_not_called()

    def test_validation_design_version_mismatch_fails_before_artifact_staging(self) -> None:
        with mock.patch.object(
            model_artifacts,
            "stage_model_artifact",
        ) as stage:
            with self.assertRaises(HTTPException) as raised:
                self._publish(
                    idempotency_key="wrong-validation-version",
                    lineage_validation_design_version="validation-version-other",
                )
            self.assertEqual(raised.exception.status_code, 409)
            self.assertIn("validation-design version", raised.exception.detail)
            stage.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)

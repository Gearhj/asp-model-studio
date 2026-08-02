from __future__ import annotations

import sqlite3
import os
import unittest
from pathlib import Path
from threading import Event, Thread, current_thread
from unittest.mock import patch

from server.persistence.db import Database, MIGRATIONS_PATH, SCHEMA_PATH, now_iso
from server.persistence.repositories import (
    HoldoutGovernanceConflictError,
    HoldoutGovernanceStateError,
)
from server.persistence.service import PersistenceService
from server.training.candidate_contract import canonical_contract_hash


FIXED_TIME = "2026-07-31T12:00:00+00:00"


class HoldoutGovernancePersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary_root = Path(__file__).resolve().parents[1] / ".tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.database_path = temporary_root / (
            f"atlas_holdout_governance_{os.getpid()}_{self._testMethodName}.db"
        )
        self.legacy_database_path = self.database_path.with_name(f"{self.database_path.stem}_legacy.db")
        self._remove_database_files(self.database_path)
        self._remove_database_files(self.legacy_database_path)
        self.database = Database(self.database_path)
        self.health = self.database.initialize()
        self.service = PersistenceService(self.database)
        self.repository = self.service.holdout_governance

    def tearDown(self) -> None:
        self._remove_database_files(self.database_path)
        self._remove_database_files(self.legacy_database_path)

    @staticmethod
    def _remove_database_files(path: Path) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)

    @staticmethod
    def _decision(**overrides: object) -> dict:
        record = {
            "candidate_decision_id": "decision-1",
            "decision_status": "locked",
            "project_id": "project-1",
            "dataset_id": "dataset-1",
            "dataset_version_id": "dataset-version-1",
            "feature_manifest_id": "feature-manifest-1",
            "feature_manifest_hash": "feature-manifest-hash-1",
            "treatment_manifest_id": "treatment-manifest-1",
            "treatment_manifest_hash": "treatment-manifest-hash-1",
            "materialization_id": "materialization-1",
            "validation_design_id": "validation-design-1",
            "validation_design_version_id": "validation-design-version-1",
            "split_id": "split-1",
            "final_holdout_partition_id": "final-holdout-partition-1",
            "training_job_id": "training-job-1",
            "training_run_id": "training-run-1",
            "candidate_id": "candidate-1",
            "selected_candidate_contract_hash": "candidate-contract-hash-1",
            "selection_metric_name": "pr_auc",
            "selection_metric_value": 0.71,
            "selection_metric_source": "cross_validation_mean",
            "selection_metric_created_at": "2026-07-31T11:58:00+00:00",
            "selection_partition_id": "training-partition-1",
            "fold_definition_id": "fold-definition-1",
            "fold_count": 3,
            "fold_values_json": [0.69, 0.71, 0.73],
            "selection_metric_mean": 0.71,
            "selection_metric_std": 0.0163,
            "out_of_fold_prediction_artifact_id": "oof-artifact-1",
            "threshold_source": "training_oof_fixed",
            "locked_threshold": 0.5,
            "threshold_locked_at": "2026-07-31T11:59:59.123456+00:00",
            "calibration_source": "cross_validation",
            "selection_rationale": "Highest governed cross-validation PR-AUC.",
            "selection_locked_at": FIXED_TIME,
            "actor": "tester-1",
            "selection_integrity_status": "verified",
            "selection_integrity_reason": "Selection uses governed cross-validation folds only.",
            "holdout_isolation_status": "verified",
            "holdout_isolation_reason": "Final holdout remained sealed until the decision lock.",
            "integrity_classified_at": FIXED_TIME,
            "integrity_classified_by": "tester-1",
            "decision_contract_hash": "decision-contract-hash-1",
            "created_at": FIXED_TIME,
        }
        record.update(overrides)
        if "selected_candidate_contract_hash" not in overrides:
            record["selected_candidate_contract_hash"] = (
                f"{record['candidate_id']}-contract-hash"
            )
        if "ranking_snapshot_json" not in overrides:
            record["ranking_snapshot_json"] = [
                {
                    "candidate_id": record["candidate_id"],
                    "candidate_contract_hash": record[
                        "selected_candidate_contract_hash"
                    ],
                    "rank": 1,
                    "selection_metric_value": record[
                        "selection_metric_value"
                    ],
                },
                {
                    "candidate_id": "candidate-2",
                    "candidate_contract_hash": "candidate-2-contract-hash",
                    "rank": 2,
                    "selection_metric_value": 0.68,
                },
            ]
        if "ranking_snapshot_hash" not in overrides:
            record["ranking_snapshot_hash"] = canonical_contract_hash(
                record["ranking_snapshot_json"]
            )
        if "threshold_policy_hash" not in overrides:
            record["threshold_policy_hash"] = canonical_contract_hash(
                {
                    "locked_threshold": record["locked_threshold"],
                    "threshold_source": record["threshold_source"],
                    "threshold_locked_at": record["threshold_locked_at"],
                    "selection_threshold_tuned": False,
                }
            )
        return record

    @staticmethod
    def _exposure(**overrides: object) -> dict:
        record = {
            "holdout_exposure_id": "holdout-exposure-1",
            "project_id": "project-1",
            "dataset_id": "dataset-1",
            "dataset_version_id": "dataset-version-1",
            "validation_design_id": "validation-design-1",
            "validation_design_version_id": "validation-design-version-1",
            "split_id": "split-1",
            "final_holdout_partition_id": "final-holdout-partition-1",
            "candidate_decision_id": "decision-1",
            "candidate_id": "candidate-1",
            "feature_manifest_id": "feature-manifest-1",
            "feature_manifest_hash": "feature-manifest-hash-1",
            "treatment_manifest_id": "treatment-manifest-1",
            "treatment_manifest_hash": "treatment-manifest-hash-1",
            "materialization_id": "materialization-1",
            "final_holdout_status": "sealed",
            "selection_locked_at": FIXED_TIME,
            "sealed_at": "2026-07-31T11:00:00+00:00",
            "exposure_contract_hash": "exposure-contract-hash-1",
            "created_at": FIXED_TIME,
            "updated_at": FIXED_TIME,
        }
        record.update(overrides)
        return record

    @staticmethod
    def _package(**overrides: object) -> dict:
        record = {
            "evaluation_package_id": "evaluation-package-1",
            "package_status": "complete",
            "project_id": "project-1",
            "dataset_id": "dataset-1",
            "dataset_version_id": "dataset-version-1",
            "feature_manifest_id": "feature-manifest-1",
            "feature_manifest_hash": "feature-manifest-hash-1",
            "treatment_manifest_id": "treatment-manifest-1",
            "treatment_manifest_hash": "treatment-manifest-hash-1",
            "materialization_id": "materialization-1",
            "validation_design_id": "validation-design-1",
            "validation_design_version_id": "validation-design-version-1",
            "split_id": "split-1",
            "training_job_id": "training-job-1",
            "training_run_id": "training-run-1",
            "candidate_id": "candidate-1",
            "selected_candidate_contract_hash": "candidate-1-contract-hash",
            "candidate_decision_id": "decision-1",
            "holdout_exposure_id": "holdout-exposure-1",
            "final_holdout_partition_id": "final-holdout-partition-1",
            "selection_metric_name": "pr_auc",
            "selection_metric_value": 0.71,
            "selection_metric_source": "cross_validation_mean",
            "selection_metric_created_at": "2026-07-31T11:58:00+00:00",
            "out_of_fold_prediction_artifact_id": "oof-artifact-1",
            "locked_threshold": 0.5,
            "threshold_source": "training_oof_fixed",
            "selection_integrity_status": "verified",
            "selection_evidence_json": {
                "metric_name": "pr_auc",
                "metric_value": 0.71,
                "metric_source": "cross_validation_mean",
                "selection_metric_created_at": "2026-07-31T11:58:00+00:00",
                "out_of_fold_prediction_artifact_id": "oof-artifact-1",
            },
            "final_holdout_evidence_json": {
                "metric_name": "pr_auc",
                "metric_value": 0.67,
                "metric_source": "final_holdout",
            },
            "metric_definitions_json": {"pr_auc": "Area under the precision-recall curve"},
            "isolation_evidence_json": {
                "sealed_until_selection_lock": True,
                "ranking_consumed_final_holdout": False,
            },
            "canonical_lineage_json": {"dataset_version_id": "dataset-version-1", "split_id": "split-1"},
            "holdout_isolation_status": "verified",
            "final_holdout_status": "evaluated",
            "threshold_locked_at": "2026-07-31T11:59:59.123456+00:00",
            "holdout_exposed_at": "2026-07-31T12:05:00+00:00",
            "recommendations_derived_from_final_holdout": False,
            "package_integrity_status": "verified",
            "package_payload_json": {
                "completion_content_hash": "completion-content-hash-1",
                "holdout_prediction_digest": "holdout-prediction-digest-1",
                "metrics": {"pr_auc": 0.67},
            },
            "created_by": "tester-1",
            "created_at": "2026-07-31T12:06:00+00:00",
        }
        record.update(overrides)
        if "threshold_policy_hash" not in overrides:
            record["threshold_policy_hash"] = canonical_contract_hash(
                {
                    "locked_threshold": record["locked_threshold"],
                    "threshold_source": record["threshold_source"],
                    "threshold_locked_at": record["threshold_locked_at"],
                    "selection_threshold_tuned": False,
                }
            )
        if "threshold_policy_json" not in overrides:
            record["threshold_policy_json"] = {
                "locked_threshold": record["locked_threshold"],
                "threshold_source": record["threshold_source"],
                "threshold_locked_at": record["threshold_locked_at"],
                "selection_threshold_tuned": False,
                "threshold_policy_hash": record["threshold_policy_hash"],
            }
        if "content_hash" not in overrides:
            record["content_hash"] = canonical_contract_hash(
                record["package_payload_json"]
            )
        if "evaluation_package_contract_hash" not in overrides:
            record["evaluation_package_contract_hash"] = canonical_contract_hash(
                {
                    "evaluation_package_id": record["evaluation_package_id"],
                    "completion_content_hash": record[
                        "package_payload_json"
                    ].get("completion_content_hash"),
                    "holdout_prediction_digest": record[
                        "package_payload_json"
                    ].get("holdout_prediction_digest"),
                    "candidate_decision_id": record["candidate_decision_id"],
                    "holdout_exposure_id": record["holdout_exposure_id"],
                    "content_hash": record["content_hash"],
                }
            )
        return record

    def test_migration_creates_governance_tables_and_service_repository(self) -> None:
        self.assertTrue(self.health["ok"])
        self.assertTrue(
            {"candidate_selection_decisions", "holdout_exposures", "evaluation_packages"}.issubset(
                set(self.health["tables"])
            )
        )
        self.assertIs(self.repository.database, self.database)
        with self.database.connection() as connection:
            migration = connection.execute(
                "SELECT version FROM schema_migrations WHERE version = ?",
                ("0018_holdout_selection_governance.sql",),
            ).fetchone()
            model_version_columns = {
                row["name"]: row for row in connection.execute("PRAGMA table_info(model_versions)").fetchall()
            }
        self.assertIsNotNone(migration)
        for column in (
            "candidate_decision_id",
            "candidate_decision_status",
            "candidate_decision_contract_hash",
            "selection_metric_source",
            "selection_integrity_status",
            "selection_locked_at",
            "holdout_exposure_id",
            "final_holdout_partition_id",
            "final_holdout_status",
            "holdout_isolation_status",
            "threshold_locked_at",
            "locked_threshold",
            "threshold_source",
            "threshold_policy_hash",
            "selected_candidate_contract_hash",
            "selection_metric_created_at",
            "out_of_fold_prediction_artifact_id",
            "evaluation_package_contract_hash",
            "evaluation_package_content_hash",
            "evaluation_package_integrity_status",
            "promotion_readiness_status",
        ):
            self.assertIn(column, model_version_columns)
        self.assertEqual(model_version_columns["selection_integrity_status"]["dflt_value"], "'legacy_unresolved'")
        self.assertEqual(model_version_columns["selection_metric_source"]["dflt_value"], "'legacy_unresolved'")
        self.assertEqual(model_version_columns["promotion_readiness_status"]["dflt_value"], "'legacy_unresolved'")

    def test_selection_lock_is_insert_only_exact_and_json_safe(self) -> None:
        inserted = self.repository.insert_selection_decision_if_absent(self._decision())
        self.assertEqual(inserted["candidate_decision_id"], "decision-1")
        self.assertEqual(inserted["fold_values_json"], [0.69, 0.71, 0.73])
        self.assertEqual(inserted["ranking_snapshot_json"][0]["candidate_id"], "candidate-1")

        exact = self.repository.get_selection_decision_exact(
            candidate_decision_id="decision-1",
            project_id="project-1",
            dataset_id="dataset-1",
            dataset_version_id="dataset-version-1",
            validation_design_id="validation-design-1",
            validation_design_version_id="validation-design-version-1",
            split_id="split-1",
            training_run_id="training-run-1",
            candidate_id="candidate-1",
        )
        self.assertIsNotNone(exact)
        self.assertIsNone(
            self.repository.get_selection_decision_exact(
                candidate_decision_id="decision-1",
                project_id="project-other",
                dataset_id="dataset-1",
                dataset_version_id="dataset-version-1",
                validation_design_id="validation-design-1",
                validation_design_version_id="validation-design-version-1",
                split_id="split-1",
                training_run_id="training-run-1",
                candidate_id="candidate-1",
            )
        )
        replay = self.repository.insert_selection_decision_if_absent(self._decision())
        self.assertEqual(replay["decision_contract_hash"], "decision-contract-hash-1")
        with self.assertRaises(HoldoutGovernanceConflictError):
            self.repository.insert_selection_decision_if_absent(
                self._decision(decision_contract_hash="different-contract-hash", candidate_id="candidate-other")
            )
        with self.assertRaises(sqlite3.IntegrityError), self.database.transaction() as connection:
            connection.execute(
                "UPDATE candidate_selection_decisions SET candidate_id = ? WHERE candidate_decision_id = ?",
                ("mutated-candidate", "decision-1"),
            )
        with self.assertRaises(sqlite3.IntegrityError), self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM candidate_selection_decisions WHERE candidate_decision_id = ?",
                ("decision-1",),
            )

        with self.assertRaises(ValueError):
            self.repository.insert_selection_decision_if_absent(
                self._decision(
                    candidate_decision_id="decision-json-safe",
                    training_run_id="training-run-json-safe",
                    candidate_id="candidate-json-safe",
                    decision_contract_hash="decision-contract-hash-json-safe",
                    fold_values_json="not-an-array",
                    ranking_snapshot_json={"not": "an array"},
                )
            )

    def test_selection_lock_rejects_ranking_and_candidate_hash_tampering(self) -> None:
        with self.assertRaises(ValueError):
            self.repository.insert_selection_decision_if_absent(
                self._decision(ranking_snapshot_hash="tampered-ranking-hash")
            )

        with self.assertRaises(ValueError):
            self.repository.insert_selection_decision_if_absent(
                self._decision(
                    selected_candidate_contract_hash="substituted-contract-hash",
                    ranking_snapshot_json=[
                        {
                            "candidate_id": "candidate-1",
                            "candidate_contract_hash": "candidate-1-contract-hash",
                            "rank": 1,
                            "selection_metric_value": 0.71,
                        }
                    ],
                )
            )

    def test_integrity_classification_is_explicit_one_way_and_idempotent(self) -> None:
        unresolved = self._decision(
            candidate_decision_id="decision-unresolved",
            training_run_id="training-run-unresolved",
            candidate_id="candidate-unresolved",
            decision_contract_hash="decision-contract-hash-unresolved",
            selection_integrity_status="legacy_unresolved",
            selection_integrity_reason=None,
            holdout_isolation_status="legacy_unresolved",
            holdout_isolation_reason=None,
            integrity_classified_at=None,
            integrity_classified_by=None,
        )
        self.repository.insert_selection_decision_if_absent(unresolved)
        classified = self.repository.classify_selection_integrity(
            "decision-unresolved",
            selection_integrity_status="invalid_final_holdout_ranking",
            holdout_isolation_status="invalid",
            reason="Historical candidate ranking consumed final-holdout metrics.",
            classified_by="governance-reviewer",
            classified_at="2026-07-31T13:00:00+00:00",
        )
        self.assertEqual(classified["selection_integrity_status"], "invalid_final_holdout_ranking")
        self.assertEqual(classified["holdout_isolation_status"], "invalid")
        replay = self.repository.classify_selection_integrity(
            "decision-unresolved",
            selection_integrity_status="invalid_final_holdout_ranking",
            holdout_isolation_status="invalid",
            reason="Retry does not replace the original classification.",
            classified_by="governance-reviewer",
        )
        self.assertEqual(replay["integrity_classified_at"], "2026-07-31T13:00:00+00:00")
        with self.assertRaises(HoldoutGovernanceConflictError):
            self.repository.classify_selection_integrity(
                "decision-unresolved",
                selection_integrity_status="verified",
                holdout_isolation_status="verified",
                reason="Conflicting reclassification must fail.",
                classified_by="governance-reviewer",
            )

        with self.assertRaises(ValueError):
            self.repository.insert_selection_decision_if_absent(
                self._decision(
                    candidate_decision_id="decision-unclassified-holdout",
                    training_run_id="training-run-unclassified-holdout",
                    candidate_id="candidate-unclassified-holdout",
                    decision_contract_hash="decision-contract-hash-unclassified-holdout",
                    selection_metric_source="final_holdout",
                    selection_integrity_status="legacy_unresolved",
                    holdout_isolation_status="legacy_unresolved",
                )
            )

    def test_holdout_lifecycle_and_evaluation_package_are_durable_and_immutable(self) -> None:
        self.repository.insert_selection_decision_if_absent(self._decision())
        sealed = self.repository.seal_holdout_exposure_if_absent(self._exposure())
        self.assertEqual(sealed["final_holdout_status"], "sealed")
        self.assertEqual(
            self.repository.seal_holdout_exposure_if_absent(self._exposure())["holdout_exposure_id"],
            "holdout-exposure-1",
        )
        opened = self.repository.mark_holdout_opened(
            "holdout-exposure-1",
            opened_by="evaluator-1",
            opened_at="2026-07-31T12:05:00+00:00",
        )
        self.assertEqual(opened["final_holdout_status"], "opened")
        self.assertEqual(opened["opened_by"], "evaluator-1")

        package = self.repository.complete_evaluation_package(
            self._package(),
            exposure_id="holdout-exposure-1",
            evaluated_at="2026-07-31T12:07:00+00:00",
        )
        self.assertEqual(package["selection_evidence_json"]["metric_value"], 0.71)
        self.assertEqual(package["final_holdout_evidence_json"]["metric_value"], 0.67)
        self.assertFalse(package["recommendations_derived_from_final_holdout"])
        self.assertEqual(
            self.repository.complete_evaluation_package(
                self._package(),
                exposure_id="holdout-exposure-1",
                evaluated_at="2026-07-31T12:07:00+00:00",
            )["evaluation_package_id"],
            "evaluation-package-1",
        )
        exact_package = self.repository.get_evaluation_package_exact(
            evaluation_package_id="evaluation-package-1",
            project_id="project-1",
            dataset_id="dataset-1",
            dataset_version_id="dataset-version-1",
            training_run_id="training-run-1",
            candidate_id="candidate-1",
            candidate_decision_id="decision-1",
            holdout_exposure_id="holdout-exposure-1",
        )
        self.assertIsNotNone(exact_package)
        with self.assertRaises(HoldoutGovernanceConflictError):
            self.repository.insert_evaluation_package_if_absent(
                self._package(content_hash="different-content-hash")
            )
        with self.assertRaises(sqlite3.IntegrityError), self.database.transaction() as connection:
            connection.execute(
                "UPDATE evaluation_packages SET content_hash = ? WHERE evaluation_package_id = ?",
                ("mutated", "evaluation-package-1"),
            )

        evaluated = self.repository.get_holdout_exposure("holdout-exposure-1")
        self.assertEqual(evaluated["final_holdout_status"], "evaluated")
        self.assertEqual(evaluated["evaluation_package_id"], "evaluation-package-1")
        invalidated = self.repository.invalidate_holdout_exposure(
            "holdout-exposure-1",
            reason="The feature contract changed after holdout exposure.",
            invalidated_by="tester-1",
            invalidated_at="2026-07-31T12:10:00+00:00",
        )
        self.assertEqual(invalidated["final_holdout_status"], "invalidated")
        with self.assertRaises(HoldoutGovernanceStateError):
            self.repository.mark_holdout_opened("holdout-exposure-1", opened_by="evaluator-2")

    def test_evaluation_completion_rolls_back_package_when_validation_fails(self) -> None:
        self.repository.insert_selection_decision_if_absent(self._decision())
        self.repository.seal_holdout_exposure_if_absent(self._exposure())
        self.repository.mark_holdout_opened(
            "holdout-exposure-1",
            opened_by="evaluator-1",
            opened_at="2026-07-31T12:05:00+00:00",
        )

        with self.assertRaises(HoldoutGovernanceConflictError):
            self.repository.complete_evaluation_package(
                self._package(content_hash="tampered-content-hash"),
                exposure_id="holdout-exposure-1",
            )

        self.assertIsNone(
            self.repository.get_evaluation_package("evaluation-package-1")
        )
        exposure = self.repository.get_holdout_exposure("holdout-exposure-1")
        self.assertEqual(exposure["final_holdout_status"], "opened")
        self.assertIsNone(exposure["evaluation_package_id"])

    def test_atomic_selection_lock_rejects_new_decision_after_exposure(self) -> None:
        self.repository.insert_selection_decision_if_absent(self._decision())
        self.repository.seal_holdout_exposure_if_absent(self._exposure())

        replacement = self._decision(
            candidate_decision_id="decision-2",
            training_job_id="training-job-2",
            training_run_id="training-run-2",
            candidate_id="candidate-replacement",
            decision_contract_hash="decision-contract-hash-2",
        )
        with self.assertRaises(HoldoutGovernanceStateError):
            self.repository.insert_selection_decision_if_unexposed(
                replacement,
                final_holdout_partition_id="final-holdout-partition-1",
            )
        self.assertIsNone(self.repository.get_selection_decision("decision-2"))

    def test_concurrent_exposure_wins_before_replacement_decision_lock(self) -> None:
        self.repository.insert_selection_decision_if_absent(self._decision())
        replacement = self._decision(
            candidate_decision_id="decision-racing",
            training_job_id="training-job-racing",
            training_run_id="training-run-racing",
            candidate_id="candidate-racing",
            decision_contract_hash="decision-contract-hash-racing",
        )
        exposure_locked = Event()
        decision_waiting = Event()
        original_connect = self.database.connect

        class CoordinatedConnection:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql, parameters=()):
                statement = str(sql).strip().upper()
                name = current_thread().name
                if statement == "BEGIN IMMEDIATE" and name == "exposure-writer":
                    result = self.connection.execute(sql, parameters)
                    exposure_locked.set()
                    if not decision_waiting.wait(timeout=5):
                        raise AssertionError(
                            "The replacement decision did not reach the serialized boundary."
                        )
                    return result
                if statement == "BEGIN IMMEDIATE" and name == "decision-writer":
                    decision_waiting.set()
                return self.connection.execute(sql, parameters)

            def __getattr__(self, name):
                return getattr(self.connection, name)

        def coordinated_connect():
            return CoordinatedConnection(original_connect())

        results: dict[str, object] = {}

        def seal_exposure() -> None:
            try:
                results["exposure"] = (
                    self.repository.seal_holdout_exposure_if_absent(
                        self._exposure()
                    )
                )
            except BaseException as exc:  # pragma: no cover - assertion aid
                results["exposure_error"] = exc

        def lock_replacement() -> None:
            try:
                results["decision"] = (
                    self.repository.insert_selection_decision_if_unexposed(
                        replacement,
                        final_holdout_partition_id=(
                            "final-holdout-partition-1"
                        ),
                    )
                )
            except BaseException as exc:
                results["decision_error"] = exc

        with patch.object(
            self.database,
            "connect",
            side_effect=coordinated_connect,
        ):
            exposure_thread = Thread(
                target=seal_exposure,
                name="exposure-writer",
            )
            exposure_thread.start()
            self.assertTrue(exposure_locked.wait(timeout=5))
            decision_thread = Thread(
                target=lock_replacement,
                name="decision-writer",
            )
            decision_thread.start()
            exposure_thread.join(timeout=10)
            decision_thread.join(timeout=10)

        self.assertFalse(exposure_thread.is_alive())
        self.assertFalse(decision_thread.is_alive())
        self.assertNotIn("exposure_error", results)
        self.assertEqual(
            results["exposure"]["holdout_exposure_id"],
            "holdout-exposure-1",
        )
        self.assertIsInstance(
            results.get("decision_error"),
            HoldoutGovernanceStateError,
        )
        self.assertNotIn("decision", results)
        self.assertIsNone(
            self.repository.get_selection_decision("decision-racing")
        )

    def test_threshold_time_comparison_preserves_offset_and_subsecond_precision(self) -> None:
        threshold_locked_at = "2026-07-31T08:00:00.123456-04:00"
        opened_at = "2026-07-31T12:00:00.123457Z"
        self.repository.insert_selection_decision_if_absent(
            self._decision(threshold_locked_at=threshold_locked_at)
        )
        self.repository.seal_holdout_exposure_if_absent(self._exposure())
        self.repository.mark_holdout_opened(
            "holdout-exposure-1",
            opened_by="evaluator-1",
            opened_at=opened_at,
        )
        package = self.repository.complete_evaluation_package(
            self._package(
                threshold_locked_at=threshold_locked_at,
                holdout_exposed_at=opened_at,
            ),
            exposure_id="holdout-exposure-1",
        )
        self.assertEqual(package["package_status"], "complete")

    def test_threshold_lock_at_same_instant_as_exposure_is_rejected(self) -> None:
        threshold_locked_at = "2026-07-31T08:00:00.123457-04:00"
        opened_at = "2026-07-31T12:00:00.123457Z"
        self.repository.insert_selection_decision_if_absent(
            self._decision(threshold_locked_at=threshold_locked_at)
        )
        self.repository.seal_holdout_exposure_if_absent(self._exposure())
        self.repository.mark_holdout_opened(
            "holdout-exposure-1",
            opened_by="evaluator-1",
            opened_at=opened_at,
        )
        with self.assertRaises(HoldoutGovernanceStateError):
            self.repository.complete_evaluation_package(
                self._package(
                    threshold_locked_at=threshold_locked_at,
                    holdout_exposed_at=opened_at,
                ),
                exposure_id="holdout-exposure-1",
            )
        self.assertIsNone(
            self.repository.get_evaluation_package("evaluation-package-1")
        )

    def test_exact_partition_invalidation_survives_repository_restart(self) -> None:
        self.repository.insert_selection_decision_if_absent(self._decision())
        self.repository.seal_holdout_exposure_if_absent(self._exposure())
        exact_identity = {
            "project_id": "project-1",
            "dataset_id": "dataset-1",
            "dataset_version_id": "dataset-version-1",
            "validation_design_id": "validation-design-1",
            "validation_design_version_id": "validation-design-version-1",
            "split_id": "split-1",
            "final_holdout_partition_id": "final-holdout-partition-1",
        }
        self.assertEqual(
            self.repository.get_holdout_exposure_for_partition(
                **exact_identity
            )["final_holdout_status"],
            "sealed",
        )
        invalidated = self.repository.invalidate_holdout_exposure_for_partition(
            **exact_identity,
            reason="The upstream preparation contract changed.",
            invalidated_by="system:test",
            invalidated_at="2026-07-31T12:15:00+00:00",
        )
        self.assertEqual(invalidated["final_holdout_status"], "invalidated")

        restarted_database = Database(self.database_path)
        self.assertTrue(restarted_database.initialize()["ok"])
        restarted_repository = PersistenceService(
            restarted_database
        ).holdout_governance
        recovered = restarted_repository.get_holdout_exposure_for_partition(
            **exact_identity
        )
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["holdout_exposure_id"], "holdout-exposure-1")
        self.assertEqual(recovered["final_holdout_status"], "invalidated")
        self.assertEqual(recovered["invalidated_by"], "system:test")
        self.assertEqual(
            recovered["invalidation_reason"],
            "The upstream preparation contract changed.",
        )

    def test_forward_migration_preserves_legacy_model_version_as_unresolved(self) -> None:
        legacy_database = Database(self.legacy_database_path)
        with legacy_database.transaction() as connection:
            connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            for migration in sorted(MIGRATIONS_PATH.glob("*.sql")):
                if migration.name >= "0018_holdout_selection_governance.sql":
                    continue
                connection.executescript(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (migration.name, now_iso()),
                )
            connection.execute(
                """
                INSERT INTO models (
                  model_id, name, status, created_at, updated_at, archived, tags_json
                ) VALUES (?, ?, 'active', ?, ?, 0, '[]')
                """,
                ("legacy-model", "Legacy model", FIXED_TIME, FIXED_TIME),
            )
            connection.execute(
                """
                INSERT INTO model_versions (
                  model_version_id, model_id, version_number, training_run_id,
                  dataset_version_id, algorithm, lineage_json, created_at
                ) VALUES (?, ?, 1, ?, ?, ?, '{}', ?)
                """,
                (
                    "legacy-model-version",
                    "legacy-model",
                    "legacy-training-run",
                    "legacy-dataset-version",
                    "logreg",
                    FIXED_TIME,
                ),
            )

        self.assertTrue(legacy_database.initialize()["ok"])
        legacy_version = PersistenceService(legacy_database).model_versions.get("legacy-model-version")
        self.assertIsNotNone(legacy_version)
        self.assertIsNone(legacy_version["candidate_decision_id"])
        self.assertEqual(legacy_version["candidate_decision_status"], "legacy_unresolved")
        self.assertIsNone(legacy_version["holdout_exposure_id"])
        self.assertEqual(legacy_version["selection_metric_source"], "legacy_unresolved")
        self.assertEqual(legacy_version["selection_integrity_status"], "legacy_unresolved")
        self.assertEqual(legacy_version["holdout_isolation_status"], "legacy_unresolved")
        self.assertEqual(legacy_version["final_holdout_status"], "legacy_unresolved")
        self.assertEqual(legacy_version["evaluation_package_integrity_status"], "legacy_unresolved")
        self.assertEqual(legacy_version["promotion_readiness_status"], "legacy_unresolved")


if __name__ == "__main__":
    unittest.main()

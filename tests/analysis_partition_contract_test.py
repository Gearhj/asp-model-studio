from __future__ import annotations

import importlib
import sqlite3
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
from fastapi import HTTPException

from server.analysis_partition.service import AnalysisPartitionService
from server.analysis_partition.types import (
    ANALYSIS_PARTITION_CONTRADICTORY,
    ANALYSIS_PARTITION_INTEGRITY_FAILED,
    ANALYSIS_PARTITION_RESET_INVALIDATION_FAILED,
    ANALYSIS_PARTITION_STALE,
    DATASET_IDENTITY_UNAVAILABLE,
    AnalysisPartitionConfirmRequest,
    AnalysisPartitionError,
)
from server.core.dataset_store import DatasetStore
from server.persistence.db import Database
from server.persistence.service import PersistenceService


analysis_partition_router = importlib.import_module(
    "server.analysis_partition.router"
)


class AnalysisPartitionContractTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary_root = Path(__file__).resolve().parents[1] / ".tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.database_path = temporary_root / f"analysis_partition_{uuid.uuid4().hex}.db"
        self.database = Database(self.database_path)
        self.database.initialize()
        self.persistence = PersistenceService(self.database)
        self.persistence.projects.upsert(
            {
                "project_id": "project-analysis-partition",
                "project_name": "Analysis Partition Test",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "owner_user_id": "partition-owner",
                "created_by": "partition-owner",
                "updated_by": "partition-owner",
            }
        )
        self.service = AnalysisPartitionService(self.persistence.analysis_partitions)
        self.store = DatasetStore()
        self.store.raw_df = pd.DataFrame(
            {
                "feature_a": list(range(100)),
                "feature_b": [value * 3 for value in range(100)],
                "bad_flag": [value % 2 for value in range(100)],
            },
            index=[f"row-{value:03d}" for value in range(100)],
        )
        self.store.target = "bad_flag"
        self.store.meta.update(
            {
                "project_id": "project-analysis-partition",
                "dataset_id": "dataset-heloc",
                "dataset_version_id": "version-heloc-1",
                "target_contract_id": "target-contract-1",
                "selected_columns": ["feature_a", "feature_b"],
                "predictor_authorization": {
                    "predictor_authorization_id": "predictor-auth-1",
                    "target_contract_id": "target-contract-1",
                    "authorized_predictors": ["feature_a", "feature_b"],
                },
            }
        )
        self.user = {"userId": "partition-owner"}

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def _request(self, **changes) -> AnalysisPartitionConfirmRequest:
        payload = {
            "project_id": "project-analysis-partition",
            "dataset_id": "dataset-heloc",
            "dataset_version_id": "version-heloc-1",
            "target_contract_id": "target-contract-1",
            "target": "bad_flag",
            "positive_value": 1,
            "negative_value": 0,
            "predictor_authorization_id": "predictor-auth-1",
            "development_share": 0.8,
            "holdout_share": 0.2,
            "random_seed": 42,
            "stratification_policy": "target",
            "stratification_field": "bad_flag",
            "confirmation_acknowledged": True,
        }
        payload.update(changes)
        if payload.get("reset_existing"):
            current = self.persistence.analysis_partitions.get_current(
                "project-analysis-partition"
            )
            if current is not None:
                payload.setdefault(
                    "expected_current_partition_id",
                    current["analysis_partition_id"],
                )
                payload.setdefault(
                    "expected_current_revision",
                    int(current["revision"]),
                )
        return AnalysisPartitionConfirmRequest(**payload)

    def _confirm(self, **changes):
        return self.service.confirm(self.store, self._request(**changes), self.user)

    def test_confirmation_persists_exact_sealed_membership_and_safe_metadata(self) -> None:
        response = self._confirm()
        safe = response["analysis_partition"]

        self.assertEqual("analysis_partition_confirmed", response["code"])
        self.assertEqual(80, safe["development_count"])
        self.assertEqual(20, safe["holdout_count"])
        self.assertEqual(100, safe["population_count"])
        self.assertEqual("sealed", safe["holdout_status"])
        self.assertEqual("verified", safe["holdout_isolation_status"])
        self.assertEqual(1, safe["revision"])
        self.assertGreater(len(safe["artifact_hash"]), 40)
        self.assertNotIn("row_assignments_json", safe)
        self.assertNotIn("development_positions", str(self.store.meta["analysis_partition"]))
        self.assertEqual(40, safe["event_counts"]["development"]["event"])
        self.assertNotIn("holdout", safe["event_counts"])
        self.assertNotIn("full", safe["event_counts"])
        self.assertNotIn("checks", safe["sufficiency"])

        current = self.service.current(
            "project-analysis-partition",
            "dataset-heloc",
            "version-heloc-1",
            target="bad_flag",
            target_contract_id="target-contract-1",
            predictor_authorization_id="predictor-auth-1",
        )
        self.assertEqual(safe["analysis_partition_id"], current["analysis_partition_id"])
        self.assertEqual("sealed", current["holdout_status"])

    def test_selected_nondefault_ratio_is_materialized_exactly(self) -> None:
        response = self._confirm(development_share=0.7, holdout_share=0.3)
        safe = response["analysis_partition"]

        self.assertEqual(0.7, safe["development_share"])
        self.assertEqual(0.3, safe["holdout_share"])
        self.assertEqual(70, safe["development_count"])
        self.assertEqual(30, safe["holdout_count"])
        self.assertEqual("sealed", safe["holdout_status"])
        self.assertEqual("verified", safe["holdout_isolation_status"])

    def test_development_materialization_does_not_read_or_validate_holdout_values(self) -> None:
        response = self._confirm()
        record = self.service.current(
            "project-analysis-partition",
            "dataset-heloc",
            "version-heloc-1",
        )
        holdout_positions = record["row_assignments_json"]["holdout_positions"]
        development_positions = record["row_assignments_json"][
            "development_positions"
        ]

        original_development_targets = self.store.raw_df.iloc[
            development_positions
        ]["bad_flag"].copy()
        self.store.raw_df.iloc[
            holdout_positions,
            self.store.raw_df.columns.get_loc("bad_flag"),
        ] = 99
        self.store.raw_df.iloc[
            holdout_positions,
            self.store.raw_df.columns.get_loc("feature_a"),
        ] = -99999

        X_dev, y_dev = self.service.materialize_development(
            self.store,
            record,
            ["feature_a", "feature_b"],
        )
        self.assertEqual(80, len(X_dev))
        self.assertEqual(original_development_targets.tolist(), y_dev.tolist())
        self.assertNotIn(-99999, X_dev["feature_a"].tolist())
        self.assertEqual(
            response["analysis_partition"]["analysis_partition_id"],
            record["analysis_partition_id"],
        )

        with self.assertRaises(AnalysisPartitionError) as captured:
            self.service.materialize_validation(
                self.store,
                record,
                ["feature_a", "feature_b"],
            )
        self.assertEqual(ANALYSIS_PARTITION_INTEGRITY_FAILED, captured.exception.code)
        self.assertIn("holdout", str(captured.exception).lower())

    def test_idempotent_confirmation_and_predictor_change_preserve_membership(self) -> None:
        first = self._confirm()["analysis_partition"]
        second_response = self._confirm()
        second = second_response["analysis_partition"]
        self.assertTrue(second_response["reused"])
        self.assertEqual(first["analysis_partition_id"], second["analysis_partition_id"])
        self.assertEqual(first["revision"], second["revision"])
        self.assertEqual(first["assignment_hash"], second["assignment_hash"])

        self.store.meta["predictor_authorization"] = {
            "predictor_authorization_id": "predictor-auth-2",
            "target_contract_id": "target-contract-1",
            "authorized_predictors": ["feature_a"],
        }
        changed = self._confirm(predictor_authorization_id="predictor-auth-2")
        self.assertTrue(changed["reused"])
        self.assertEqual(
            first["analysis_partition_id"],
            changed["analysis_partition"]["analysis_partition_id"],
        )
        self.assertEqual(first["revision"], changed["analysis_partition"]["revision"])
        self.assertEqual(
            "changed_partition_preserved",
            changed["analysis_partition"]["predictor_authorization_lineage_status"],
        )
        current = self.service.current(
            "project-analysis-partition",
            "dataset-heloc",
            "version-heloc-1",
            predictor_authorization_id="predictor-auth-2",
        )
        self.assertEqual(first["analysis_partition_id"], current["analysis_partition_id"])
        self.assertEqual("changed_partition_preserved", current["predictor_authorization_lineage_status"])

    def test_contradiction_requires_explicit_reset_and_increments_revision(self) -> None:
        first = self._confirm()["analysis_partition"]
        with self.assertRaises(AnalysisPartitionError) as captured:
            self._confirm(random_seed=17)
        self.assertEqual(ANALYSIS_PARTITION_CONTRADICTORY, captured.exception.code)
        self.assertGreaterEqual(len(captured.exception.impacts), 5)
        self.assertEqual(
            first["analysis_partition_id"],
            self.persistence.analysis_partitions.get_current(
                "project-analysis-partition"
            )["analysis_partition_id"],
        )

        reset = self._confirm(
            random_seed=17,
            reset_existing=True,
            reset_reason="Approved target-partition redesign.",
            acknowledge_invalidation=True,
        )["analysis_partition"]
        self.assertEqual(2, reset["revision"])
        self.assertNotEqual(first["analysis_partition_id"], reset["analysis_partition_id"])
        history = self.persistence.analysis_partitions.history(
            "project-analysis-partition"
        )
        self.assertEqual(["superseded", "current"], [row["status"] for row in history])
        self.assertEqual(
            reset["analysis_partition_id"],
            history[0]["superseded_by_partition_id"],
        )

    def test_explicit_same_policy_reset_always_creates_new_ids_and_revision(self) -> None:
        first = self._confirm()["analysis_partition"]
        invalidation_observations: list[tuple[str, int]] = []

        def invalidate_derivatives_before_replacement() -> None:
            current = self.persistence.analysis_partitions.get_current(
                "project-analysis-partition"
            )
            invalidation_observations.append(
                (
                    current["analysis_partition_id"],
                    len(
                        self.persistence.analysis_partitions.history(
                            "project-analysis-partition"
                        )
                    ),
                )
            )

        response = self.service.confirm(
            self.store,
            self._request(
                reset_existing=True,
                reset_reason="Explicitly approved same-policy reset.",
                acknowledge_invalidation=True,
            ),
            self.user,
            before_reset_persist=invalidate_derivatives_before_replacement,
        )
        replacement = response["analysis_partition"]

        self.assertFalse(response["reused"])
        self.assertEqual("analysis_partition_confirmed", response["code"])
        self.assertEqual(
            [(first["analysis_partition_id"], 1)],
            invalidation_observations,
        )
        self.assertEqual(2, replacement["revision"])
        self.assertNotEqual(
            first["analysis_partition_id"],
            replacement["analysis_partition_id"],
        )
        self.assertNotEqual(
            first["development_partition_id"],
            replacement["development_partition_id"],
        )
        self.assertNotEqual(
            first["sealed_holdout_partition_id"],
            replacement["sealed_holdout_partition_id"],
        )
        self.assertEqual(first["artifact_hash"], replacement["artifact_hash"])
        self.assertEqual(first["assignment_hash"], replacement["assignment_hash"])
        history = self.persistence.analysis_partitions.history(
            "project-analysis-partition"
        )
        self.assertEqual(
            ["superseded", "current"],
            [row["status"] for row in history],
        )

    def test_derivative_invalidation_failure_never_persists_replacement(self) -> None:
        first = self._confirm()["analysis_partition"]
        reset_preview_payload = self._request().model_dump()
        reset_preview_payload.update(
            {
                "expected_current_partition_id": first["analysis_partition_id"],
                "expected_current_revision": first["revision"],
            }
        )
        reset_preview = self.service.reset_preview(
            self.store,
            reset_preview_payload,
        )["preview"]
        reset_request = self._request(
            preview_fingerprint=reset_preview["preview_fingerprint"],
            selection_rationale="The governed default ratio remains appropriate for this reset.",
            reset_existing=True,
            reset_reason="Reset whose downstream invalidation fails.",
            acknowledge_invalidation=True,
        )

        with (
            patch.object(
                analysis_partition_router.analysis_partition_service,
                "_repository",
                self.persistence.analysis_partitions,
            ),
            patch.object(
                analysis_partition_router,
                "DATASTORE",
                Mock(current=Mock(return_value=self.store)),
            ),
            patch.object(
                analysis_partition_router,
                "authorize_modeling_scope",
                return_value=None,
            ),
            patch.object(
                analysis_partition_router,
                "_authoritative_partition_request",
                return_value=(
                    self.store,
                    reset_request.model_dump(),
                    {
                        "project_id": "project-analysis-partition",
                        "dataset_id": "dataset-analysis",
                        "dataset_version_id": "version-analysis-1",
                        "activation_revision": 1,
                    },
                ),
            ),
            patch.object(
                analysis_partition_router,
                "_invalidate_partition_derivatives",
                side_effect=RuntimeError("injected derivative invalidation failure"),
            ),
        ):
            with self.assertRaises(HTTPException) as captured:
                analysis_partition_router.confirm_analysis_partition(
                    reset_request,
                    self.user,
                )

        self.assertEqual(409, captured.exception.status_code)
        self.assertEqual(
            ANALYSIS_PARTITION_RESET_INVALIDATION_FAILED,
            captured.exception.detail["code"],
        )
        current = self.persistence.analysis_partitions.get_current(
            "project-analysis-partition"
        )
        self.assertEqual(
            first["analysis_partition_id"],
            current["analysis_partition_id"],
        )
        self.assertEqual(1, current["revision"])
        history = self.persistence.analysis_partitions.history(
            "project-analysis-partition"
        )
        self.assertEqual(1, len(history))
        self.assertEqual("current", history[0]["status"])
        events = self.persistence.analysis_partitions.events(
            first["analysis_partition_id"]
        )
        self.assertEqual(["confirmed"], [event["event_type"] for event in events])

    def test_invalidation_is_durable_precise_and_allows_system_actor(self) -> None:
        safe = self._confirm()["analysis_partition"]
        result = self.service.invalidate(
            "project-analysis-partition",
            "Target mapping changed.",
            expected_dataset_id="dataset-heloc",
            expected_dataset_version_id="version-heloc-1",
            target="bad_flag",
            store=self.store,
        )
        self.assertEqual("analysis_partition_invalidated", result["code"])
        self.assertEqual("stale", result["analysis_partition"]["status"])
        self.assertEqual("stale", self.store.meta["analysis_partition"]["status"])
        self.assertIsNone(
            self.persistence.analysis_partitions.get_current(
                "project-analysis-partition"
            )
        )
        history = self.persistence.analysis_partitions.history(
            "project-analysis-partition"
        )
        self.assertEqual(safe["analysis_partition_id"], history[0]["analysis_partition_id"])
        self.assertEqual("stale", history[0]["status"])
        events = self.persistence.analysis_partitions.events(
            safe["analysis_partition_id"]
        )
        self.assertEqual("atlas-system", events[-1]["actor_user_id"])
        with self.assertRaises(AnalysisPartitionError) as captured:
            self.service.current(
                "project-analysis-partition",
                "dataset-heloc",
                "version-heloc-1",
            )
        self.assertEqual(ANALYSIS_PARTITION_STALE, captured.exception.code)
        self.assertIn("no partition is current", str(captured.exception).lower())

    def test_exact_identity_only_and_no_other_project_fallback(self) -> None:
        self._confirm()
        with self.assertRaises(AnalysisPartitionError) as wrong_version:
            self.service.current(
                "project-analysis-partition",
                "dataset-heloc",
                "version-other",
            )
        self.assertEqual(ANALYSIS_PARTITION_STALE, wrong_version.exception.code)

        self.persistence.projects.upsert(
            {
                "project_id": "project-other",
                "project_name": "Other Project",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
            }
        )
        with self.assertRaises(AnalysisPartitionError) as other_project:
            self.service.current(
                "project-other",
                "dataset-heloc",
                "version-heloc-1",
            )
        self.assertNotEqual(DATASET_IDENTITY_UNAVAILABLE, other_project.exception.code)
        self.assertEqual("analysis_partition_required", other_project.exception.code)

    def test_checksum_tampering_is_rejected_and_database_rows_are_not_deletable(self) -> None:
        safe = self._confirm()["analysis_partition"]
        record = self.persistence.analysis_partitions.get(
            safe["analysis_partition_id"]
        )
        tampered = dict(record)
        tampered["row_assignments_json"] = dict(record["row_assignments_json"])
        tampered["row_assignments_json"]["development_positions"] = list(
            reversed(tampered["row_assignments_json"]["development_positions"])
        )
        with self.assertRaises(AnalysisPartitionError) as captured:
            self.service.materialize_development(
                self.store,
                tampered,
                ["feature_a", "feature_b"],
            )
        self.assertEqual(ANALYSIS_PARTITION_INTEGRITY_FAILED, captured.exception.code)

        with self.assertRaises(sqlite3.IntegrityError):
            with self.database.transaction() as connection:
                connection.execute(
                    "DELETE FROM analysis_partitions WHERE analysis_partition_id = ?",
                    (safe["analysis_partition_id"],),
                )

    def test_project_deletion_cascades_governed_state_but_preserves_event_evidence(self) -> None:
        authorization = self.persistence.predictor_authorizations.set_current(
            {
                "predictor_authorization_id": "predictor-auth-1",
                "project_id": "project-analysis-partition",
                "dataset_id": "dataset-heloc",
                "dataset_version_id": "version-heloc-1",
                "target_contract_id": "target-contract-1",
                "target": "bad_flag",
                "authorized_predictors": ["feature_a", "feature_b"],
                "excluded_predictors": {},
                "artifact_hash": "predictor-auth-cascade-proof",
                "created_by": "partition-owner",
            }
        )
        safe = self._confirm()["analysis_partition"]
        events_before = self.persistence.analysis_partitions.events(
            safe["analysis_partition_id"]
        )

        # A second project's governed state proves the cascade is scoped to
        # the exact deleted project and never behaves as a table-wide bypass.
        self.persistence.projects.upsert(
            {
                "project_id": "project-analysis-partition-other",
                "project_name": "Other Analysis Partition Project",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
            }
        )
        other_authorization = self.persistence.predictor_authorizations.set_current(
            {
                "predictor_authorization_id": "predictor-auth-other",
                "project_id": "project-analysis-partition-other",
                "dataset_id": "dataset-other",
                "dataset_version_id": "version-other-1",
                "target_contract_id": "target-contract-other",
                "target": "bad_flag",
                "authorized_predictors": ["feature_a"],
                "excluded_predictors": {},
                "artifact_hash": "predictor-auth-other-proof",
                "created_by": "partition-owner",
            }
        )

        self.assertTrue(
            self.persistence.projects.delete("project-analysis-partition")
        )
        self.assertIsNone(
            self.persistence.projects.get("project-analysis-partition")
        )
        self.assertEqual(
            [],
            self.persistence.analysis_partitions.history(
                "project-analysis-partition"
            ),
        )
        self.assertIsNone(
            self.persistence.predictor_authorizations.get(
                authorization["predictor_authorization_id"]
            )
        )
        self.assertEqual(
            events_before,
            self.persistence.analysis_partitions.events(
                safe["analysis_partition_id"]
            ),
        )
        self.assertIsNotNone(
            self.persistence.predictor_authorizations.get(
                other_authorization["predictor_authorization_id"]
            )
        )
        with self.database.connection() as connection:
            self.assertEqual(1, connection.execute("PRAGMA foreign_keys").fetchone()[0])
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))

    def test_failed_project_cascade_rolls_back_parent_and_governed_children(self) -> None:
        authorization = self.persistence.predictor_authorizations.set_current(
            {
                "predictor_authorization_id": "predictor-auth-1",
                "project_id": "project-analysis-partition",
                "dataset_id": "dataset-heloc",
                "dataset_version_id": "version-heloc-1",
                "target_contract_id": "target-contract-1",
                "target": "bad_flag",
                "authorized_predictors": ["feature_a", "feature_b"],
                "excluded_predictors": {},
                "artifact_hash": "predictor-auth-rollback-proof",
                "created_by": "partition-owner",
            }
        )
        safe = self._confirm()["analysis_partition"]
        self.persistence.projects.upsert_workflow_state(
            "project-analysis-partition",
            {"current_step_id": "step01"},
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                CREATE TRIGGER injected_project_cascade_failure
                BEFORE DELETE ON workflow_state
                BEGIN
                  SELECT RAISE(ABORT, 'injected project cascade failure');
                END
                """
            )

        with self.assertRaisesRegex(sqlite3.IntegrityError, "injected project cascade failure"):
            self.persistence.projects.delete("project-analysis-partition")

        self.assertIsNotNone(
            self.persistence.projects.get("project-analysis-partition")
        )
        self.assertIsNotNone(
            self.persistence.analysis_partitions.get(
                safe["analysis_partition_id"]
            )
        )
        self.assertIsNotNone(
            self.persistence.predictor_authorizations.get(
                authorization["predictor_authorization_id"]
            )
        )

    def test_restart_reloads_exact_durable_partition(self) -> None:
        safe = self._confirm()["analysis_partition"]
        reloaded_persistence = PersistenceService(Database(self.database_path))
        reloaded_service = AnalysisPartitionService(
            reloaded_persistence.analysis_partitions
        )
        reloaded = reloaded_service.current(
            "project-analysis-partition",
            "dataset-heloc",
            "version-heloc-1",
            target="bad_flag",
        )
        self.assertEqual(safe["analysis_partition_id"], reloaded["analysis_partition_id"])
        self.assertEqual(safe["artifact_hash"], reloaded["artifact_hash"])
        self.assertEqual(safe["assignment_hash"], reloaded["assignment_hash"])


if __name__ == "__main__":
    unittest.main()

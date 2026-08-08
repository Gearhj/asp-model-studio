from __future__ import annotations

import importlib
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from server.analysis_partition.service import analysis_partition_service
from server.analysis_partition.types import (
    ANALYSIS_PARTITION_REQUIRED,
    ANALYSIS_PARTITION_STALE,
    DATASET_IDENTITY_UNAVAILABLE,
    PREDICTOR_AUTHORIZATION_REQUIRED,
    TARGET_CONTRACT_STALE,
    AnalysisPartitionError,
)
from server.core.dataset_store import DATASTORE, DatasetStore
from server.core.modeling_scope import set_active_project_id
from server.preprocessing import missing_router, outlier_router
from server.preprocessing.development_scope import (
    resolve_development_analysis_scope,
)
from server.preprocessing.outlier_service import outlier_service

from tests.analysis_partition_fixture import GovernedAnalysisFixture


partition_service_module = importlib.import_module(
    "server.analysis_partition.service"
)


PROJECT_ID = "project-development-scope"
DATASET_ID = "dataset-development-scope"
VERSION_ID = "version-development-scope-v1"
TARGET = "event"
PREDICTORS = ["signal", "missing_signal", "noise"]
IDENTITY = {
    "project_id": PROJECT_ID,
    "dataset_id": DATASET_ID,
    "dataset_version_id": VERSION_ID,
}


def _synthetic_frame(*, duplicate_index: bool = False) -> pd.DataFrame:
    rng = np.random.default_rng(20260804)
    rows = 103
    target = np.array([1] * 31 + [0] * (rows - 31), dtype=int)
    rng.shuffle(target)
    signal = target * 4.0 + rng.normal(0.0, 0.75, rows)
    missing_signal = target * 2.0 + rng.normal(0.0, 1.0, rows)
    missing_signal[np.arange(rows) % 9 == 0] = np.nan
    frame = pd.DataFrame(
        {
            "signal": signal,
            "missing_signal": missing_signal,
            "noise": rng.normal(0.0, 1.0, rows),
            TARGET: target,
        }
    )
    if duplicate_index:
        frame.index = pd.Index([index // 2 for index in range(rows)])
    return frame


class DevelopmentOnlyPreprocessingContractTest(unittest.TestCase):
    def setUp(self) -> None:
        set_active_project_id(PROJECT_ID)
        self.store = DATASTORE.current()
        self.store.reset_all()
        self.frame = _synthetic_frame()
        self.store.set_raw(self.frame)
        self.store.set_target(TARGET)
        self.store.meta.update(
            {
                **IDENTITY,
                "dataset_version": VERSION_ID,
                "selected_columns": list(PREDICTORS),
            }
        )
        self.fixture = GovernedAnalysisFixture(project_id=PROJECT_ID)
        self.installation = self.fixture.install(
            self.store,
            dataset_id=DATASET_ID,
            dataset_version_id=VERSION_ID,
            target=TARGET,
            authorized_predictors=PREDICTORS,
            positive_value=1,
            negative_value=0,
            development_share=0.8,
            random_seed=73,
        )

    def tearDown(self) -> None:
        self.fixture.close()
        self.store.reset_all()
        set_active_project_id(None)

    def _scope(self, **kwargs):
        return resolve_development_analysis_scope(
            self.store,
            IDENTITY,
            **kwargs,
        )

    def _missing_summary(self) -> dict:
        with (
            patch.object(
                missing_router,
                "authorize_modeling_scope",
                return_value=PROJECT_ID,
            ),
            patch.object(
                missing_router,
                "assert_expected_active_identity",
                return_value=dict(IDENTITY),
            ),
        ):
            return missing_router.missing_summary(
                project_id=PROJECT_ID,
                target=None,
                event_value=None,
                problem_type=None,
                expected_dataset_id=DATASET_ID,
                expected_dataset_version_id=VERSION_ID,
                dataset_id=None,
                dataset_version_id=None,
                dataset_version=None,
                analysis_partition_id=None,
                analysis_partition_revision=None,
                user={"userId": "governed-analysis-test"},
            )

    def test_target_metrics_use_development_rate_not_full_population_rate(self):
        scope = self._scope()
        full_rate = float(self.store.raw_df[TARGET].mean())
        development_rate = float(scope.development_target.mean())
        self.assertNotAlmostEqual(full_rate, development_rate)

        payload = outlier_service.summary(
            self.store.raw_df.drop(columns=[TARGET]),
            target=scope.target,
            event_value=scope.event_value,
            problem_type=scope.problem_type,
            predictor_authorization=scope.predictor_authorization,
            target_analysis_features=scope.development_features,
            target_analysis_target=scope.development_target,
        )
        self.assertAlmostEqual(payload["event_rate"], development_rate)
        self.assertNotAlmostEqual(payload["event_rate"], full_rate)
        self.assertEqual(payload["scope"], "development_population")
        self.assertEqual(
            payload["structural_scope"],
            "full_governed_population_predictors_only",
        )

        missing_payload = self._missing_summary()
        self.assertAlmostEqual(missing_payload["event_rate"], development_rate)
        self.assertNotAlmostEqual(missing_payload["event_rate"], full_rate)
        self.assertEqual(
            missing_payload["target_directed_scope"],
            "development_population",
        )
        self.assertFalse(missing_payload["final_holdout_accessed"])

    def test_full_dataset_application_scope_preserves_development_analysis_lineage(self):
        user = {"userId": "governed-analysis-test"}
        expected_scope = {
            "scope": "full_dataset",
            "application_scope": "full_dataset",
            "materialization_scope": "full_dataset",
            "application_source_population": "full_governed_population",
            "analysis_scope": "development_population",
            "analytical_scope": "development_population",
            "target_directed_scope": "development_population",
            "structural_scope": "full_governed_population_predictors_only",
            "holdout_excluded": True,
            "final_holdout_accessed": False,
            "final_holdout_used_for_selection": False,
        }

        def assert_application_contract(payload: dict) -> None:
            for key, expected in expected_scope.items():
                self.assertEqual(payload[key], expected, key)
                self.assertEqual(payload["application"][key], expected, key)
            self.assertEqual(payload["full_governed_population_rows"], len(self.frame))
            self.assertEqual(
                payload["application"]["full_governed_population_rows"],
                len(self.frame),
            )
            self.assertEqual(
                payload["development_rows"],
                self.installation["record"]["development_count"],
            )

        with (
            patch.object(
                outlier_router,
                "authorize_modeling_scope",
                return_value=PROJECT_ID,
            ),
            patch.object(
                outlier_router,
                "assert_expected_active_identity",
                return_value=dict(IDENTITY),
            ),
            patch.object(outlier_router, "save_checkpoint", return_value=True),
            patch.object(
                missing_router,
                "authorize_modeling_scope",
                return_value=PROJECT_ID,
            ),
            patch.object(
                missing_router,
                "assert_expected_active_identity",
                return_value=dict(IDENTITY),
            ),
            patch.object(missing_router, "save_checkpoint", return_value=True),
        ):
            outlier_request = outlier_router.OutlierApplyRequest(
                project_id=PROJECT_ID,
                expected_dataset_id=DATASET_ID,
                expected_dataset_version_id=VERSION_ID,
                global_method="NONE",
                config={feature: "USE_GLOBAL" for feature in PREDICTORS},
            )
            first_outlier = outlier_router.apply_outlier_treatments(
                outlier_request,
                user=user,
            )
            assert_application_contract(first_outlier)
            self.assertNotIn("idempotent", first_outlier)

            # A pre-repair durable record used the analytical population as
            # its generic scope. Idempotent replay must not leak that stale
            # label back through either response layer.
            self.store.meta["outlier_application"]["scope"] = (
                "development_population"
            )
            self.store.meta["outlier_application"].pop(
                "application_scope", None
            )
            self.store.meta["outlier_application"].pop(
                "materialization_scope", None
            )

            second_outlier = outlier_router.apply_outlier_treatments(
                outlier_request,
                user=user,
            )
            assert_application_contract(second_outlier)
            self.assertTrue(second_outlier["idempotent"])

            missing_request = missing_router.MissingApplyRequest(
                project_id=PROJECT_ID,
                expected_dataset_id=DATASET_ID,
                expected_dataset_version_id=VERSION_ID,
                config={
                    "missing_signal": missing_router.MissingRule(
                        strategy="Median"
                    )
                },
            )
            first_missing = missing_router.apply_missing_values(
                missing_request,
                user=user,
            )
            assert_application_contract(first_missing)
            self.assertNotIn("idempotent", first_missing)
            self.assertEqual(first_missing["application"]["missing_after"], 0)

            self.store.meta["missing_application"]["scope"] = (
                "development_population"
            )
            self.store.meta["missing_application"].pop(
                "application_scope", None
            )
            self.store.meta["missing_application"].pop(
                "materialization_scope", None
            )

            second_missing = missing_router.apply_missing_values(
                missing_request,
                user=user,
            )
            assert_application_contract(second_missing)
            self.assertTrue(second_missing["idempotent"])

    def test_holdout_target_changes_cannot_change_preprocessing_evidence(self):
        scope = self._scope()
        structural = self.store.raw_df.drop(columns=[TARGET])
        before_outlier = outlier_service.summary(
            structural,
            target=scope.target,
            event_value=scope.event_value,
            problem_type=scope.problem_type,
            predictor_authorization=scope.predictor_authorization,
            target_analysis_features=scope.development_features,
            target_analysis_target=scope.development_target,
        )
        before_missing = self._missing_summary()

        holdout_positions = self.installation["record"][
            "row_assignments_json"
        ]["holdout_positions"]
        target_position = self.store.raw_df.columns.get_loc(TARGET)
        current = self.store.raw_df.iloc[holdout_positions, target_position]
        self.store.raw_df.iloc[holdout_positions, target_position] = (
            1 - current.to_numpy()
        )

        after_scope = self._scope()
        after_outlier = outlier_service.summary(
            self.store.raw_df.drop(columns=[TARGET]),
            target=after_scope.target,
            event_value=after_scope.event_value,
            problem_type=after_scope.problem_type,
            predictor_authorization=after_scope.predictor_authorization,
            target_analysis_features=after_scope.development_features,
            target_analysis_target=after_scope.development_target,
        )
        after_missing = self._missing_summary()

        self.assertEqual(before_outlier["event_rate"], after_outlier["event_rate"])
        self.assertEqual(
            [row["signal_metric"] for row in before_outlier["features"]],
            [row["signal_metric"] for row in after_outlier["features"]],
        )
        for feature in PREDICTORS:
            self.assertEqual(
                before_missing["stats"][feature]["information_value"],
                after_missing["stats"][feature]["information_value"],
            )
            self.assertEqual(
                before_missing["stats"][feature]["difference"],
                after_missing["stats"][feature]["difference"],
            )

    def test_resolution_reads_development_membership_only(self):
        development_positions = tuple(
            self.installation["record"]["row_assignments_json"][
                "development_positions"
            ]
        )
        observed_positions: list[tuple[int, ...]] = []
        original_fingerprint = (
            partition_service_module._target_membership_fingerprint
        )

        def fingerprint_spy(frame, target, positions):
            observed_positions.append(tuple(int(value) for value in positions))
            return original_fingerprint(frame, target, positions)

        with (
            patch.object(
                partition_service_module,
                "_target_membership_fingerprint",
                side_effect=fingerprint_spy,
            ),
            patch.object(
                analysis_partition_service,
                "materialize_validation",
                side_effect=AssertionError(
                    "Target-aware preprocessing opened final holdout data."
                ),
            ),
        ):
            scope = self._scope()
            outlier_service.summary(
                self.store.raw_df.drop(columns=[TARGET]),
                target=scope.target,
                event_value=scope.event_value,
                problem_type=scope.problem_type,
                predictor_authorization=scope.predictor_authorization,
                target_analysis_features=scope.development_features,
                target_analysis_target=scope.development_target,
            )
            self._missing_summary()

        self.assertGreaterEqual(len(observed_positions), 2)
        self.assertTrue(
            all(positions == development_positions for positions in observed_positions)
        )

    def test_missing_stale_and_cross_identity_requests_fail_closed(self):
        record = self.installation["record"]
        with self.assertRaises(AnalysisPartitionError) as stale_id:
            self._scope(
                expected_analysis_partition_id="analysis-partition-stale",
                expected_analysis_partition_revision=int(record["revision"]),
            )
        self.assertEqual(stale_id.exception.code, ANALYSIS_PARTITION_STALE)

        with self.assertRaises(AnalysisPartitionError) as stale_revision:
            self._scope(
                expected_analysis_partition_id=record[
                    "analysis_partition_id"
                ],
                expected_analysis_partition_revision=int(record["revision"]) + 1,
            )
        self.assertEqual(stale_revision.exception.code, ANALYSIS_PARTITION_STALE)

        with self.assertRaises(AnalysisPartitionError) as wrong_target:
            self._scope(requested_target="different_target")
        self.assertEqual(wrong_target.exception.code, TARGET_CONTRACT_STALE)

        for identity in (
            {**IDENTITY, "project_id": "other-project"},
            {**IDENTITY, "dataset_version_id": "other-version"},
        ):
            with self.assertRaises(AnalysisPartitionError) as crossed:
                resolve_development_analysis_scope(self.store, identity)
            self.assertEqual(
                crossed.exception.code, PREDICTOR_AUTHORIZATION_REQUIRED
            )

        with self.assertRaises(AnalysisPartitionError) as missing_identity:
            resolve_development_analysis_scope(self.store, {})
        self.assertEqual(
            missing_identity.exception.code, DATASET_IDENTITY_UNAVAILABLE
        )

        with patch.object(
            analysis_partition_service,
            "current",
            side_effect=AnalysisPartitionError(
                ANALYSIS_PARTITION_REQUIRED,
                "Synthetic missing Analysis Partition.",
            ),
        ):
            with self.assertRaises(AnalysisPartitionError) as missing_partition:
                self._scope()
        self.assertEqual(
            missing_partition.exception.code, ANALYSIS_PARTITION_REQUIRED
        )

    def test_duplicate_index_materialization_is_positional(self):
        self.fixture.close()
        self.store.reset_all()
        self.frame = _synthetic_frame(duplicate_index=True)
        self.store.set_raw(self.frame)
        self.store.set_target(TARGET)
        self.store.meta.update(
            {
                **IDENTITY,
                "dataset_version": VERSION_ID,
                "selected_columns": list(PREDICTORS),
            }
        )
        self.fixture = GovernedAnalysisFixture(project_id=PROJECT_ID)
        self.installation = self.fixture.install(
            self.store,
            dataset_id=DATASET_ID,
            dataset_version_id=VERSION_ID,
            target=TARGET,
            authorized_predictors=PREDICTORS,
            positive_value=1,
            negative_value=0,
            random_seed=91,
        )
        scope = self._scope()
        positions = self.installation["record"]["row_assignments_json"][
            "development_positions"
        ]
        expected = self.store.raw_df.iloc[positions]
        self.assertTrue(scope.development_features.index.has_duplicates)
        self.assertEqual(
            scope.development_features.index.tolist(), expected.index.tolist()
        )
        self.assertEqual(
            scope.development_target.tolist(), expected[TARGET].tolist()
        )
        aligned = scope.materialize_aligned_features(
            self.store.raw_df.drop(columns=[TARGET])
        )
        self.assertEqual(aligned.index.tolist(), expected.index.tolist())
        self.assertEqual(aligned["signal"].tolist(), expected["signal"].tolist())

    def test_exact_partition_restores_from_durable_state_after_runtime_restart(self):
        before = self._scope()
        restarted = DatasetStore()
        restarted.set_raw(self.store.raw_df.copy())
        restarted.set_target(TARGET)
        restarted.meta.update(
            {
                **IDENTITY,
                "dataset_version": VERSION_ID,
                "selected_columns": list(PREDICTORS),
                "dataset_content_hash": self.store.meta["dataset_content_hash"],
            }
        )

        restored = resolve_development_analysis_scope(restarted, IDENTITY)
        self.assertEqual(
            restored.partition["analysis_partition_id"],
            before.partition["analysis_partition_id"],
        )
        self.assertEqual(restored.partition["revision"], before.partition["revision"])
        self.assertTrue(
            restored.development_features.equals(before.development_features)
        )
        self.assertTrue(restored.development_target.equals(before.development_target))
        self.assertEqual(restored.metadata()["scope_resolution"], "durable_current_exact")
        self.assertFalse(restored.metadata()["final_holdout_accessed"])

    def test_scope_emits_canonical_audit_metadata_and_requires_checksum(self):
        scope = resolve_development_analysis_scope(
            self.store,
            {**IDENTITY, "dataset_content_hash": self.store.meta["dataset_content_hash"]},
            actor="synthetic-auditor",
            timestamp="2026-08-04T12:00:00+00:00",
        )
        metadata = scope.metadata()
        self.assertEqual(metadata["analytical_scope"], "development_population")
        self.assertEqual(
            metadata["population_id"],
            scope.partition["development_partition_id"],
        )
        self.assertEqual(metadata["population_count"], len(scope.development_target))
        self.assertEqual(metadata["partition_id"], scope.partition["analysis_partition_id"])
        self.assertEqual(metadata["partition_revision"], scope.partition["revision"])
        self.assertTrue(metadata["holdout_excluded"])
        self.assertEqual(metadata["source_checksum"], self.store.meta["dataset_content_hash"])
        self.assertEqual(metadata["actor"], "synthetic-auditor")
        self.assertEqual(metadata["actor_source"], "authenticated_request")
        self.assertEqual(metadata["timestamp"], "2026-08-04T12:00:00+00:00")

        with self.assertRaises(AnalysisPartitionError) as checksum_mismatch:
            resolve_development_analysis_scope(
                self.store,
                {**IDENTITY, "dataset_content_hash": "different-version-checksum"},
                actor="synthetic-auditor",
            )
        self.assertEqual(
            checksum_mismatch.exception.code,
            DATASET_IDENTITY_UNAVAILABLE,
        )

        prior_checksum = self.store.meta.pop("dataset_content_hash")
        try:
            with self.assertRaises(AnalysisPartitionError) as missing_checksum:
                resolve_development_analysis_scope(self.store, IDENTITY)
            self.assertEqual(
                missing_checksum.exception.code,
                DATASET_IDENTITY_UNAVAILABLE,
            )
        finally:
            self.store.meta["dataset_content_hash"] = prior_checksum


if __name__ == "__main__":
    unittest.main(verbosity=2)

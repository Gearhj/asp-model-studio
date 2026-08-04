"""Batched, governed Predictor visual payload contract tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd
from pydantic import ValidationError

from server.core.dataset_store import DATASTORE
from server.eda.workspace_service import eda_workspace_service
from server.eda.workspace_types import EDAWorkspaceRequest
from tests.analysis_partition_fixture import GovernedAnalysisFixture


PROJECT_ID = "eda-predictor-visual-project"
TARGET = "bad_flag"
SAFE_FEATURES = {
    "ExternalRiskEstimate",
    "NumTrades60Ever2DerogPubRec",
    "segment",
}


def _frame(rows: int = 360) -> pd.DataFrame:
    target = [index % 2 for index in range(rows)]
    external_risk: list[float | None] = []
    for index in range(rows):
        if index % 53 == 0:
            external_risk.append(None)
        elif index % 37 == 0:
            external_risk.append(-7.0)
        elif index % 41 == 0:
            external_risk.append(-8.0)
        elif index % 43 == 0:
            external_risk.append(-9.0)
        else:
            external_risk.append(float(35 + (index % 57)))
    return pd.DataFrame(
        {
            "RiskPerformance": [
                "Bad" if value == 1 else "Good"
                for value in target
            ],
            "outcome_code": [
                900.0 if value == 1 else 100.0
                for value in target
            ],
            "ExternalRiskEstimate": external_risk,
            "NumTrades60Ever2DerogPubRec": [
                None if index % 71 == 0 else float(index % 13)
                for index in range(rows)
            ],
            "segment": [
                None if index % 67 == 0 else f"segment-{index % 15:02d}"
                for index in range(rows)
            ],
            TARGET: target,
        }
    )


class EDAPredictorVisualContractTests(unittest.TestCase):
    def setUp(self) -> None:
        DATASTORE.reset_all()
        DATASTORE.set_raw(_frame())
        DATASTORE.set_target(TARGET)
        DATASTORE.meta.update(
            {
                "project_id": PROJECT_ID,
                "dataset_id": "dataset-heloc-predictor",
                "dataset_version_id": "heloc-predictor-v1",
            }
        )
        DATASTORE.meta["selected_columns"] = [
            "RiskPerformance",
            "outcome_code",
            *sorted(SAFE_FEATURES),
        ]
        DATASTORE.meta["dataset_version"] = "heloc-predictor-v1"
        DATASTORE.meta["source"] = {
            "kind": "dataset_library",
            "datasetId": "dataset-heloc-predictor",
            "version": "heloc-predictor-v1",
            "filename": "HELOC_TRAIN.csv",
        }
        DATASTORE.meta["feature_manifest"] = {
            "manifest_version": "pm-heloc-predictor-v1",
            "dataset_version": "heloc-predictor-v1",
            "features": [
                {
                    "feature_name": feature,
                    "selected": True,
                    "eligibility_status": "eligible",
                    "origin": "original",
                }
                for feature in sorted(SAFE_FEATURES)
            ]
            + [
                {
                    "feature_name": feature,
                    "selected": False,
                    "eligibility_status": "excluded",
                    "exclusion_reason": "Deterministic source of modeling target",
                    "origin": "original",
                }
                for feature in ("RiskPerformance", "outcome_code")
            ],
        }
        self.governed_fixture = GovernedAnalysisFixture(project_id=PROJECT_ID)
        self.partition_fixture = self.governed_fixture.install(
            DATASTORE.current(),
            dataset_id="dataset-heloc-predictor",
            dataset_version_id="heloc-predictor-v1",
            target=TARGET,
            authorized_predictors=sorted(SAFE_FEATURES),
            target_sources=("RiskPerformance", "outcome_code"),
            development_share=0.8,
        )
        DATASTORE.meta["selected_columns"] = [
            "RiskPerformance",
            "outcome_code",
            *sorted(SAFE_FEATURES),
        ]
        self.identity_patch = patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value={
                "project_id": PROJECT_ID,
                "dataset_id": "dataset-heloc-predictor",
                "dataset_version_id": "heloc-predictor-v1",
            },
        )
        self.identity_patch.start()
        eda_workspace_service._cache.clear()
        eda_workspace_service._contract_cache.clear()

    def tearDown(self) -> None:
        self.identity_patch.stop()
        eda_workspace_service._cache.clear()
        eda_workspace_service._contract_cache.clear()
        DATASTORE.reset_all()
        self.governed_fixture.close()

    def _request(self, shape_limit: int = 8) -> EDAWorkspaceRequest:
        return EDAWorkspaceRequest(
            project_id=PROJECT_ID,
            target=TARGET,
            event_value=1,
            problem_type="classification",
            selected_features=[
                TARGET,
                "RiskPerformance",
                "outcome_code",
                *sorted(SAFE_FEATURES),
            ],
            predictor_visual_shape_limit=shape_limit,
        )

    def test_single_batched_payload_is_authorized_and_chart_ready(self) -> None:
        # Initial Predictor entry must not pay for the relationship/VIF engine.
        with (
            patch.object(
                eda_workspace_service,
                "_prepare_vif_frame",
                side_effect=AssertionError("Predictors must not compute VIF."),
            ),
            patch.object(
                eda_workspace_service,
                "_vif",
                side_effect=AssertionError("Predictors must not compute VIF."),
            ),
        ):
            payload = eda_workspace_service.section(
                "predictors",
                self._request(),
            )

        self.assertEqual(payload["scope"], "development_population")
        self.assertEqual(payload["analysis_scope"]["mode"], "governed_version")
        self.assertEqual(payload["analysis_scope"]["populationRows"], 288)
        self.assertEqual(payload["row_count"], 360)
        self.assertEqual(payload["profiled_features"], len(SAFE_FEATURES))
        self.assertEqual(
            {
                row["feature"]
                for row in payload["predictor_visual_profiles"]
            },
            SAFE_FEATURES,
        )
        self.assertTrue(
            {"RiskPerformance", "outcome_code"}.issubset(
                set(payload["target_source_excluded"])
            )
        )
        contract = payload["predictor_visual_contract"]
        self.assertEqual(contract["version"], "eda-predictor-visual-v1")
        self.assertEqual(
            contract["request_mode"],
            "single_batched_workspace_request",
        )
        self.assertFalse(contract["additional_vif_computation"])
        self.assertTrue(contract["server_authorized_predictors_only"])
        self.assertTrue(contract["target_excluded"])
        self.assertTrue(
            contract[
                "target_source_exclusions_disclosed_at_response_root"
            ]
        )
        self.assertEqual(contract["event_rate_shape_limit"], 8)
        self.assertEqual(
            contract["non_overlapping_quality_buckets"],
            [
                "null_missing",
                "bureau_special_value",
                "ordinary_outlier",
            ],
        )

        self.assertGreaterEqual(contract["profile_duration_ms"], 0)
        self.assertEqual(payload["cache_status"], "miss")
        self.assertGreaterEqual(payload["duration_ms"], 0)
        self.assertLessEqual(
            contract["profile_duration_ms"],
            payload["duration_ms"],
        )

        by_feature = {
            row["feature"]: row
            for row in payload["predictor_visual_profiles"]
        }
        numeric = by_feature["ExternalRiskEstimate"]
        self.assertEqual(numeric["kind"], "numeric")
        self.assertEqual(numeric["population_rows"], 360)
        self.assertLessEqual(
            len(numeric["event_rate_shape"]["groups"]),
            8,
        )
        self.assertFalse(
            numeric["event_rate_shape"]["raw_observations_included"]
        )
        self.assertEqual(numeric["missing"]["semantics"], "null_only")
        self.assertGreater(numeric["missing"]["count"], 0)
        self.assertGreater(numeric["bureau_special"]["count"], 0)
        self.assertFalse(
            numeric["bureau_special"]["missing_values_included"]
        )
        self.assertTrue(
            numeric["ordinary_outlier"]["excludes_nulls"]
        )
        self.assertTrue(
            numeric["ordinary_outlier"][
                "excludes_bureau_special_values"
            ]
        )
        self.assertEqual(
            numeric["missing"]["count"]
            + numeric["bureau_special"]["count"]
            + numeric["ordinary_outlier"]["denominator"],
            numeric["population_rows"],
        )
        self.assertLessEqual(
            numeric["ordinary_outlier"]["count"],
            numeric["ordinary_outlier"]["denominator"],
        )
        self.assertEqual(
            {
                row["value"]
                for row in numeric["bureau_special"]["values"]
            },
            {-7, -8, -9},
        )
        self.assertEqual(
            numeric["metrics"]["special_prevalence"],
            numeric["bureau_special"]["prevalence"],
        )
        for metric in (
            "iv",
            "missing_rate",
            "outlier_rate",
            "distinct_count",
            "skewness",
            "monotonicity",
            "vif",
            "special_prevalence",
        ):
            self.assertIn(metric, numeric["metrics"])
        self.assertIsNotNone(numeric["metrics"]["vif"])
        self.assertIn(
            numeric["metrics"]["vif_status"],
            {"acceptable", "review", "high"},
        )
        legacy_numeric = next(
            row
            for row in payload["numeric"]
            if row["feature"] == "ExternalRiskEstimate"
        )
        self.assertEqual(
            legacy_numeric["outlier_rate_semantics"],
            "legacy_raw_numeric_rate_may_include_bureau_special_values",
        )

        categorical = by_feature["segment"]
        self.assertEqual(categorical["kind"], "categorical")
        self.assertLessEqual(
            len(categorical["event_rate_shape"]["groups"]),
            8,
        )
        self.assertNotIn(
            "__MISSING__",
            {
                row["label"]
                for row in categorical["event_rate_shape"]["groups"]
            },
        )
        self.assertEqual(
            categorical["metrics"]["vif_status"],
            "not_applicable_categorical",
        )

    def test_target_entry_includes_one_bounded_authorized_predictor_preview(self) -> None:
        payload = eda_workspace_service.section("target", self._request())
        preview = payload["predictor_preview"]

        self.assertEqual(preview["scope"], "development_population")
        self.assertEqual(preview["population_rows"], 288)
        self.assertEqual(
            preview["request_mode"],
            "governed_shared_analytical_contract",
        )
        self.assertTrue(preview["server_authorized_predictors_only"])
        self.assertTrue(preview["target_excluded"])
        self.assertFalse(preview["raw_observations_included"])
        self.assertLessEqual(preview["returned_predictors"], 5)

        features = {row["feature"] for row in preview["predictors"]}
        self.assertTrue(features.issubset(SAFE_FEATURES))
        self.assertNotIn(TARGET, features)
        self.assertNotIn("RiskPerformance", features)
        self.assertNotIn("outcome_code", features)
        self.assertTrue(
            {"RiskPerformance", "outcome_code"}.issubset(
                set(payload["target_source_excluded"])
            )
        )

        for row in preview["predictors"]:
            self.assertIn(row["kind"], {"numeric", "categorical"})
            self.assertIsInstance(row["iv"], float)
            self.assertIn("monotonicity", row)
            self.assertIn("event_rate_spread", row)
            self.assertGreater(len(row["groups"]), 0)
            self.assertLessEqual(len(row["groups"]), preview["shape_limit"])
            for group in row["groups"]:
                self.assertTrue(
                    {"label", "count", "event_count", "event_rate"}.issubset(group)
                )
                self.assertNotIn("rows", group)

    def test_shape_limit_is_governed_and_part_of_cache_identity(self) -> None:
        six = eda_workspace_service.section(
            "predictors",
            self._request(shape_limit=6),
        )
        six_hit = eda_workspace_service.section(
            "predictors",
            self._request(shape_limit=6),
        )
        ten = eda_workspace_service.section(
            "predictors",
            self._request(shape_limit=10),
        )
        self.assertEqual(six["cache_status"], "miss")
        self.assertEqual(six_hit["cache_status"], "hit")
        self.assertEqual(ten["cache_status"], "miss")
        self.assertEqual(
            six["predictor_visual_contract"]["event_rate_shape_limit"],
            6,
        )
        self.assertEqual(
            ten["predictor_visual_contract"]["event_rate_shape_limit"],
            10,
        )
        self.assertLessEqual(
            max(
                len(row["event_rate_shape"]["groups"])
                for row in six["predictor_visual_profiles"]
            ),
            6,
        )
        with self.assertRaises(ValidationError):
            self._request(shape_limit=5)
        with self.assertRaises(ValidationError):
            self._request(shape_limit=11)


if __name__ == "__main__":
    unittest.main()

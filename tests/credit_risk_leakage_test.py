import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.credit_risk.leakage_guard import default_predictors, validate_predictors  # noqa: E402
from server.credit_risk.ml_engine import train_ml_model  # noqa: E402
from server.credit_risk import ml_engine  # noqa: E402


class CreditRiskLeakageTests(unittest.TestCase):
    def test_default_predictors_exclude_reserved_credit_risk_columns(self) -> None:
        columns = ["RiskPerformance", "bad_flag", "atlas_split", "ExternalRiskEstimate", "score", "account_id"]
        predictors = default_predictors(target="bad_flag", dataset_meta={}, columns=columns)
        self.assertEqual(predictors, ["ExternalRiskEstimate"])

    def test_explicit_reserved_predictor_returns_422(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            validate_predictors(
                ["RiskPerformance", "ExternalRiskEstimate"],
                target="bad_flag",
                dataset_meta={},
                columns=["RiskPerformance", "ExternalRiskEstimate", "bad_flag"],
                explicit=True,
            )
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("RiskPerformance", raised.exception.detail["columns"])

    def test_ml_training_uses_only_authorized_development_scope(self) -> None:
        df = pd.DataFrame(
            {
                "bad_flag": [1, 0, 1, 0, 1, 0, 1, 0],
                "ExternalRiskEstimate": [10, 90, 20, 80, 30, 70, 40, 60],
            }
        )
        scope = SimpleNamespace(
            identity={
                "project_id": "p",
                "dataset_id": "d",
                "dataset_version_id": "v1",
                "dataset": {"datasetId": "d", "name": "Fixture"},
            },
            target="bad_flag",
            problem_type="classification",
            event_value=1,
            non_event_value=0,
            development_features=df[["ExternalRiskEstimate"]].copy(),
            development_target=df["bad_flag"].copy(),
            authorized_predictors=["ExternalRiskEstimate"],
            metadata=lambda: {
                "scope": "development_population",
                "analysis_scope": "development_population",
                "analytical_scope": "development_population",
                "target_directed_scope": "development_population",
                "scope_resolution": "durable_current_exact",
                "row_selection_method": "verified_positional_assignment",
                "project_id": "p",
                "dataset_id": "d",
                "dataset_version_id": "v1",
                "target_contract_id": "target-contract-1",
                "analysis_partition_id": "ap-1",
                "analysis_partition_revision": 1,
                "development_partition_id": "dev-1",
                "population_id": "dev-1",
                "population_count": 8,
                "partition_id": "ap-1",
                "partition_revision": 1,
                "holdout_excluded": True,
                "final_holdout_accessed": False,
                "final_holdout_used_for_selection": False,
                "raw_dataset_target_fallback_used": False,
                "browser_target_semantics_used": False,
                "source_checksum": "sha256:fixture",
                "actor": "user-1",
                "actor_source": "authenticated_request",
                "timestamp": "2026-08-04T00:00:00+00:00",
            },
        )
        original_save = ml_engine.save_ml_model
        ml_engine.save_ml_model = lambda model: model
        try:
            result = train_ml_model(
                {
                    "projectId": "p",
                    "datasetId": "d",
                    "datasetVersionId": "v1",
                    "targetColumn": "bad_flag",
                    "eventValue": 1,
                    "selectedVariables": [],
                    "modelType": "Logistic Regression Baseline",
                },
                scope,
            )
        finally:
            ml_engine.save_ml_model = original_save

        self.assertEqual(result["splitSource"], "governed_development_stratified_fold")
        self.assertEqual(result["selectedVariables"], ["ExternalRiskEstimate"])
        self.assertEqual(result["analysis_scope"], "development_population")
        self.assertTrue(result["holdout_excluded"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

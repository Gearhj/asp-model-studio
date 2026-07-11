import sys
import unittest
from pathlib import Path

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

    def test_ml_training_uses_atlas_split_and_excludes_it_from_features(self) -> None:
        df = pd.DataFrame(
            {
                "bad_flag": [1, 0, 1, 0, 1, 0, 1, 0],
                "RiskPerformance": ["Bad", "Good", "Bad", "Good", "Bad", "Good", "Bad", "Good"],
                "atlas_split": ["train", "train", "train", "train", "test", "test", "test", "test"],
                "ExternalRiskEstimate": [10, 90, 20, 80, 30, 70, 40, 60],
                "score": [1, 2, 3, 4, 5, 6, 7, 8],
            }
        )

        original_loader = ml_engine.load_dataset_frame
        original_save = ml_engine.save_ml_model
        ml_engine.load_dataset_frame = lambda dataset_id, version_id: ({"datasetId": dataset_id, "name": "Fixture"}, "v1", df)
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
                }
            )
        finally:
            ml_engine.load_dataset_frame = original_loader
            ml_engine.save_ml_model = original_save

        self.assertEqual(result["splitSource"], "atlas_split")
        self.assertEqual(result["selectedVariables"], ["ExternalRiskEstimate"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

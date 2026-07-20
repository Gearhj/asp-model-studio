from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.analytics_engine.modules.classification import compute_classification_diagnostics
from server.analytics_engine.modules.descriptive import compute_dataset_profile
from server.analytics_engine.modules.forecasting import compute_forecast_diagnostics
from server.analytics_engine.modules.regression import compute_regression_diagnostics
from server.analytics_engine.modules.time_series import compute_time_series_profile
from server.analytics_engine.service import AnalyticsEngineService
from server.persistence.db import Database
from server.persistence.service import PersistenceService


class AnalyticsEngineBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp.close()
        self.database = Database(self.temp.name)
        self.database.initialize()
        self.service = PersistenceService(self.database)

    def tearDown(self) -> None:
        os.unlink(self.temp.name)

    def test_descriptive_profile_returns_real_numeric_summary_and_chart_data(self) -> None:
        frame = pd.DataFrame({"value": [1, 2, 3, 4, 5, None], "category": ["a", "a", "b", "b", "b", "c"]})
        output = compute_dataset_profile(frame, {}, {"column": "value", "bins": 5})
        self.assertEqual(output["statistics"]["row_count"], 6)
        self.assertEqual(output["tables"][0]["rows"][0]["mean"], 3.0)
        self.assertEqual(len(output["charts"][0]["data"]), 5)

    def test_classification_metrics_and_threshold_data(self) -> None:
        frame = pd.DataFrame({"y": [0, 0, 0, 1, 1, 1], "score": [.1, .2, .35, .6, .8, .9]})
        output = compute_classification_diagnostics(frame, {}, {"target_column": "y", "score_column": "score"})
        self.assertGreater(output["statistics"]["roc_auc"], .9)
        self.assertTrue(any(item["table_id"] == "threshold_performance" for item in output["tables"]))

    def test_regression_and_forecast_metrics_are_calculated(self) -> None:
        frame = pd.DataFrame({"actual": [1, 2, 3, 4, 5, 6], "prediction": [1.1, 2.1, 2.9, 4.2, 4.8, 5.9]})
        regression = compute_regression_diagnostics(frame, {}, {"target_column": "actual", "prediction_column": "prediction"})
        forecast = compute_forecast_diagnostics(frame, {}, {"actual_column": "actual", "forecast_column": "prediction"})
        self.assertLess(regression["statistics"]["rmse"], .3)
        self.assertLess(forecast["statistics"]["wape"], 10)

    def test_time_series_profile_has_real_acf_and_anomaly_data(self) -> None:
        frame = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=40, freq="D"), "target": list(range(39)) + [120]})
        output = compute_time_series_profile(frame, {}, {"timestamp_column": "date", "target_column": "target", "rolling_window": 7, "anomaly_threshold": 2})
        self.assertEqual(output["statistics"]["observation_count"], 40)
        self.assertTrue(output["charts"][1]["data"])
        self.assertGreaterEqual(output["statistics"]["anomaly_count"], 1)

    def test_persisted_result_contract(self) -> None:
        result = compute_dataset_profile(pd.DataFrame({"value": [1, 2, 3]}), {"project_id": "project_analytics"}, {"column": "value"})
        self.service.projects.ensure("project_analytics", {})
        run = self.service.analytics.upsert_run({"analytical_run_id": "arun_test", "project_id": "project_analytics", "analysis_type": "descriptive_profile", "analysis_version": "1.0.0", "status": "completed"})
        self.service.analytics.replace_outputs(run["analytical_run_id"], result)
        stored = self.service.analytics.full_result(run["analytical_run_id"])
        self.assertEqual(stored["analysis_type"], "descriptive_profile")
        self.assertTrue(stored["charts"])


if __name__ == "__main__":
    unittest.main()

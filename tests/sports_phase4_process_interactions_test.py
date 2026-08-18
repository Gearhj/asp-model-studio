"""Hermetic tests for E2 batter x pitcher process interactions (no model training)."""

import math
import unittest

import numpy as np
import pandas as pd

from server.sports_phase4 import process_interactions_run as e2


def _e1_row(**over):
    base = {c: 0.0 for c in e2.required_e1_columns()}
    base.update({"batter_id": "b", "pitcher_id": "p", "season": 2024, "_ord": 100})
    base.update(over)
    return base


def _e1_frame(rows):
    return pd.DataFrame([_e1_row(**r) for r in rows])


class RowAlignmentTest(unittest.TestCase):
    def test_output_row_count_equals_input(self):
        df = _e1_frame([{}, {}, {}])
        out = e2.build_interactions(df)
        self.assertEqual(len(out), len(df))

    def test_feature_count_within_hard_bound(self):
        self.assertLessEqual(len(e2.FEATURE_NAMES), e2.FEATURE_HARD_MAX)
        self.assertGreaterEqual(len(e2.FEATURE_NAMES), 15)

    def test_missing_parent_column_raises(self):
        df = _e1_frame([{}])
        with self.assertRaises(e2.ProcessInteractionError):
            e2.build_interactions(df.drop(columns=["batter_cum_ball_rate"]))


class FormulaTest(unittest.TestCase):
    def test_product_formula(self):
        df = _e1_frame([{"batter_cum_swinging_strike_rate": 0.2, "pitcher_cum_swinging_strike_rate": 0.3}])
        out = e2.build_interactions(df)
        self.assertAlmostEqual(float(out["bp_swinging_strike_product"].iloc[0]), 0.06, places=9)

    def test_absdiff_formula(self):
        df = _e1_frame([{"batter_cum_ball_rate": 0.40, "pitcher_cum_ball_rate": 0.32}])
        out = e2.build_interactions(df)
        self.assertAlmostEqual(float(out["bp_ball_rate_absdiff"].iloc[0]), 0.08, places=9)

    def test_cross_patience_command(self):
        df = _e1_frame([{"batter_cum_called_strike_rate": 0.18, "pitcher_cum_ball_rate": 0.35}])
        out = e2.build_interactions(df)
        self.assertAlmostEqual(float(out["batter_patience_x_pitcher_command"].iloc[0]), 0.063, places=9)

    def test_log_sample_product(self):
        df = _e1_frame([{"batter_cum_prior_pas": 99, "pitcher_cum_prior_pas": 999}])
        out = e2.build_interactions(df)
        expected = math.log1p(99) * math.log1p(999)
        self.assertAlmostEqual(float(out["bp_log_sample_product"].iloc[0]), expected, places=6)


class NullAndIndicatorTest(unittest.TestCase):
    def test_null_propagates_not_imputed(self):
        df = _e1_frame([{"batter_cum_swinging_strike_rate": np.nan, "pitcher_cum_swinging_strike_rate": 0.3}])
        out = e2.build_interactions(df)
        self.assertTrue(pd.isna(out["bp_swinging_strike_product"].iloc[0]))

    def test_both_missing_and_present_indicators(self):
        df = _e1_frame([
            {"batter_cum_missing_history": 1, "pitcher_cum_missing_history": 1},
            {"batter_cum_missing_history": 0, "pitcher_cum_missing_history": 0},
            {"batter_cum_missing_history": 1, "pitcher_cum_missing_history": 0},
        ])
        out = e2.build_interactions(df)
        self.assertEqual(list(out["both_process_missing"]), [1, 0, 0])
        self.assertEqual(list(out["both_process_history_present"]), [0, 1, 0])
        self.assertEqual(list(out["batter_process_missing"]), [1, 0, 1])

    def test_both_low_sample(self):
        df = _e1_frame([{"batter_cum_low_sample": 1, "pitcher_cum_low_sample": 1}])
        out = e2.build_interactions(df)
        self.assertEqual(int(out["both_process_low_sample"].iloc[0]), 1)


class AuditTest(unittest.TestCase):
    def _frame(self):
        rng = np.random.default_rng(1)
        rows = []
        for i in range(200):
            rows.append({
                "season": 2023 + (i % 3),
                "batter_cum_swinging_strike_rate": float(rng.uniform(0.05, 0.2)),
                "pitcher_cum_swinging_strike_rate": float(rng.uniform(0.05, 0.2)),
                "batter_cum_ball_rate": float(rng.uniform(0.3, 0.42)),
                "pitcher_cum_ball_rate": float(rng.uniform(0.3, 0.42)),
                "batter_cum_prior_pas": int(rng.integers(0, 400)),
                "pitcher_cum_prior_pas": int(rng.integers(0, 2000)),
            })
        return e2.build_interactions(_e1_frame(rows))

    def test_distribution_and_redundancy_shape(self):
        out = self._frame()
        dist = e2.feature_distribution_audit(out)
        self.assertIn("2024", dist)
        self.assertEqual(len(dist["2024"]["features"]), len(e2.FEATURE_NAMES))
        red = e2.redundancy_audit(out)
        self.assertIn("highCorrelationPairs", red)
        self.assertIsInstance(red["exactDuplicateGroups"], list)

    def test_payload_no_model_metrics_and_row_preserved(self):
        out = self._frame()
        payload = e2.compute_readiness_payload(
            out, e2.feature_distribution_audit(out), e2.redundancy_audit(out),
            dataset_authority={"registrationId": "r", "manifestSha": "m"},
            identity_bridge_authority={}, parent_e1={"materializationId": "e1"},
            rows_read=len(out),
        )
        self.assertIn(payload["terminalStatus"], ("PROCESS_INTERACTIONS_READY", "PROCESS_INTERACTIONS_PARTIALLY_READY"))
        text = repr(payload).lower()
        for forbidden in ("logloss", "brier", "accuracy", "auc", "champion", "challenger_metric", "target_encoding"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()

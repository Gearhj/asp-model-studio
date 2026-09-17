from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "nfl_cfb_nba_feature_readiness_v1.py"
SPEC = importlib.util.spec_from_file_location("feature_readiness", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class FeatureReadinessTests(unittest.TestCase):
    def test_feature_contracts_exclude_targets_and_identity(self):
        common = {"home_score", "away_score", "game_id", "game_date", "home_team", "away_team"}
        for sport, features in MODULE.FEATURES.items():
            forbidden = common | ({"home_margin", "total_points"} if sport == "CFB" else set())
            self.assertFalse(forbidden.intersection(features), sport)

    def test_nba_cold_start_is_support_bounded_and_target_free(self):
        frame = pd.DataFrame({
            "home_season_games_played": [0, 10], "away_season_games_played": [2, 20],
            "home_points_for": [120.0, 115.0], "away_points_for": [105.0, 110.0],
            "home_prior_points_for": [100.0, 100.0], "away_prior_points_for": [98.0, 98.0],
            "home_points_allowed": [99.0, 101.0], "away_points_allowed": [102.0, 103.0],
            "home_prior_points_allowed": [97.0, 97.0], "away_prior_points_allowed": [99.0, 99.0],
            "home_rolling_points_for": [120.0, 115.0], "away_rolling_points_for": [105.0, 110.0],
            "home_rolling_points_allowed": [99.0, 101.0], "away_rolling_points_allowed": [102.0, 103.0],
            "home_score": [999, 999], "away_score": [0, 0],
        })
        a, _, cols = MODULE.cold_start_features("NBA", frame, frame)
        self.assertEqual(a.loc[0, "audit_shrunk__home_points_for"], 100.0)
        self.assertAlmostEqual(a.loc[1, "audit_shrunk__home_points_for"], (10/15)*115 + (5/15)*100)
        self.assertNotIn("home_score", cols)
        self.assertEqual(list(a.audit_low_support), [1.0, 0.0])

    def test_context_features_preserve_participant_orientation(self):
        frame = pd.DataFrame({
            "home_pass_epa_per_play_season_to_date": [.2], "away_defensive_pass_epa_per_play_season_to_date": [-.1],
            "away_pass_epa_per_play_season_to_date": [.05], "home_defensive_pass_epa_per_play_season_to_date": [.03],
            "home_rush_epa_per_play_season_to_date": [.1], "away_defensive_rush_epa_per_play_season_to_date": [.02],
            "away_rush_epa_per_play_season_to_date": [-.04], "home_defensive_rush_epa_per_play_season_to_date": [.01],
        })
        # Add the other declared windows with the same values.
        for w in ("last_4", "last_8", "last_16"):
            for c in list(frame.columns):
                frame[c.replace("season_to_date", w)] = frame[c]
        a, _, cols = MODULE.context_features("NFL", frame, frame)
        self.assertAlmostEqual(a.loc[0, "audit_matchup_home_pass_season_to_date"], .3)
        self.assertAlmostEqual(a.loc[0, "audit_matchup_away_pass_season_to_date"], .02)
        self.assertEqual(len(cols), 16)
        c, _, _ = MODULE.context_features("NFL", frame, frame)
        pd.testing.assert_frame_equal(a, c)

    def test_chronological_role_map_is_explicit(self):
        design = {"roles": {"Development": {"NFL": [2022]}, "ReusedLaterDiagnostic": {"NFL": [2023, 2024]}}}
        self.assertEqual(MODULE.role_for("NFL", 2022, design), "Development")
        self.assertEqual(MODULE.role_for("NFL", 2024, design), "ReusedLaterDiagnostic")
        self.assertEqual(MODULE.role_for("NFL", 2021, design), "EarlierTrainingHistory")

    def test_missingness_indicator_is_explicit_not_zero_imputation(self):
        train = pd.DataFrame({"x": [1.0, np.nan], "y": [0.0, 0.0]})
        test = pd.DataFrame({"x": [np.nan], "y": [1.0]})
        a, b, cols = MODULE.missing_indicators(train, test, ["x", "y"])
        self.assertEqual(cols, ["audit_missing__x"])
        self.assertTrue(pd.isna(a.loc[1, "x"]))
        self.assertEqual(b.loc[0, "audit_missing__x"], 1.0)

    def test_block_bootstrap_is_deterministic_and_week_grouped(self):
        delta = np.array([1.0, -1.0, .5, -.5])
        dates = pd.Series(["2024-09-01", "2024-09-02", "2024-09-10", "2024-09-11"])
        self.assertEqual(MODULE.bootstrap(delta, dates), MODULE.bootstrap(delta, dates))

    def test_probability_metrics_exclude_real_ties_explicitly(self):
        actual = np.array([[20, 20], [21, 17], [10, 14]], dtype=float)
        out = MODULE.probability_metrics(actual, np.array([.5, .7, .2]))
        self.assertEqual(out["n"], 2)
        self.assertEqual(out["excludedTies"], 1)


if __name__ == "__main__":
    unittest.main()

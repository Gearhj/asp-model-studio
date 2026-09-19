"""Synthetic checks only: no retained forecasts, outcomes or providers."""
import math
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mlb_v18_six_game_statistics as stats


class SixGameStatisticsTests(unittest.TestCase):
    def test_block_aggregation_matches_explicit_frame_resampling(self):
        frame = pd.DataFrame({"game_date": ["d1", "d1", "d2", "d3"],
                              "delta": [1., 5., -4., 2.]})
        actual = stats.paired_interval(frame.game_date.to_numpy(), frame.delta.to_numpy())
        expected = stats.interval_by_date(frame, lambda f: f.delta.mean())
        for key in ["estimate", "lower95", "upper95"]:
            self.assertAlmostEqual(actual[key], expected[key])
        self.assertEqual(actual["date_blocks"], 3)
        self.assertEqual(actual["valid_resamples"], 2000)

    def test_empty_group_bootstraps_are_excluded_not_filled(self):
        frame = pd.DataFrame({"game_date": ["d1", "d2"],
                              "group": ["UNUSUAL", "ORDINARY"],
                              "value": [8., 3.]})
        result = stats.group_difference(frame, "value", "group")
        self.assertEqual(result["estimate"], 5.)
        self.assertEqual(result["lower95"], 5.)
        self.assertEqual(result["upper95"], 5.)
        self.assertGreater(result["valid_resamples"], 0)
        self.assertLess(result["valid_resamples"], 2000)

    def test_one_date_has_no_fabricated_interval(self):
        result = stats.paired_interval(np.array(["d1", "d1"]), np.array([1., 3.]))
        self.assertEqual(result["estimate"], 2.)
        self.assertIsNone(result["lower95"])
        self.assertIsNone(result["upper95"])
        self.assertEqual(result["valid_resamples"], 0)

    def test_comparisons_share_reference_cohort_and_pool_team_squared_errors(self):
        f = pd.DataFrame({
            "game_date": ["d1", "d2", "d2"],
            "actual_home": [2., 4., 7.], "actual_away": [1., 3., 5.],
            "v18_home": [4., 5., 9.], "v18_away": [1., 1., 1.],
            "team6_home": [2., 4., np.nan], "team6_away": [1., 3., np.nan],
            "h2h6_home": [2., np.nan, np.nan], "h2h6_away": [1., np.nan, np.nan],
            "selected": [True, False, True], "p_home_win": [.6, .7, .8],
            "team6_complete_six": [True, False, False],
            "h2h6_complete_six": [True, False, False],
        })
        for ref in ["team6", "h2h6"]:
            for side in ["home", "away"]:
                f[ref+"_blend_"+side] = .5 * (f["v18_"+side]+f[ref+"_"+side])
        scored = stats.add_losses(f)
        compared = stats.comparisons(scored)
        pop = compared[(compared.reference == "team6") &
                       (compared.support_population == "AVAILABLE_SUPPORT") &
                       (compared.selection == "ALL")].set_index("arm")
        self.assertEqual(pop.games.tolist(), [2, 2, 2])
        self.assertAlmostEqual(pop.loc["v18", "team_rmse"], math.sqrt((4.+0.+1.+4.)/4))
        self.assertAlmostEqual(pop.loc["team6", "team_mae_delta_vs_v18"], -1.25)
        self.assertAlmostEqual(pop.loc["team6_blend", "team_mae_delta_vs_v18"], -.625)
        common = compared[(compared.support_population == "BOTH_REFERENCES_COMPLETE_SIX") &
                          (compared.selection == "ALL")]
        self.assertEqual(set(common.games), {1})


if __name__ == "__main__":
    unittest.main()

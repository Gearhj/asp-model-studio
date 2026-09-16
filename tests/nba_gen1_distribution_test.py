"""UNIT_ONLY synthetic numerical fixtures; no NBA modeling or performance evidence."""
import unittest

import numpy as np

from server.sports_nba_gen1.distribution import (
    DistributionUnsupported, empirical_crps, game_seed, joint_energy_score,
    score_forecast, simulate, summarize,
)


class NbaGen1DistributionTests(unittest.TestCase):
    def test_oriented_complete_pairs_are_preserved(self):
        residuals = np.array([[4, 8], [-4, -8]])
        result = simulate(100, 90, residuals, seed=25, draws=1000, overtime_evidence=[[9, 7]])
        chosen = residuals[result["residual_indices"]]
        np.testing.assert_array_equal(result["home_runs"], 100 + chosen[:, 0])
        np.testing.assert_array_equal(result["away_runs"], 90 + chosen[:, 1])
        self.assertEqual(result["diagnostics"]["rawTieCount"], 0)
        self.assertEqual(set(zip(result["home_runs"], result["away_runs"])), {(104, 98), (96, 82)})

    def test_empirical_overtime_preserves_count_and_reports_changes(self):
        result = simulate(100, 100, [[0, 0], [0, 0]], seed=27, draws=1000,
                          overtime_evidence=[[9, 7]])
        np.testing.assert_array_equal(result["home_runs"], np.full(1000, 109))
        np.testing.assert_array_equal(result["away_runs"], np.full(1000, 107))
        np.testing.assert_array_equal(result["overtime_period_counts"], np.ones(1000))
        diagnostics = result["diagnostics"]
        self.assertEqual(diagnostics["rawTieFraction"], 1)
        self.assertEqual(diagnostics["overtimeMeanChangeHomeAway"], [9, 7])
        self.assertEqual(diagnostics["overtimeHomeWinProbabilityChange"], 1)
        self.assertEqual(diagnostics["finalTieCount"], 0)

    def test_missing_or_nonresolving_overtime_is_explicit(self):
        for evidence in (None, [], [[0, 0]], [[4, 4]], [[-1, 2]], [[2.5, 4]]):
            with self.subTest(evidence=evidence), self.assertRaises(DistributionUnsupported):
                simulate(110, 108, [[0, 0], [0, 0]], seed=1, overtime_evidence=evidence)

    def test_safeguard_fails_entire_call_without_discarding_ties(self):
        with self.assertRaisesRegex(DistributionUnsupported, "entire forecast unsupported"):
            simulate(100, 100, [[0, 0], [0, 0]], seed=3, draws=1000,
                     overtime_evidence=[[4, 4], [5, 4]], max_overtime_periods=1)
        result = simulate(100, 100, [[0, 0], [0, 0]], seed=3, draws=1000,
                          overtime_evidence=[[4, 4], [5, 4]])
        self.assertFalse(np.any(result["home_runs"] == result["away_runs"]))
        self.assertGreater(result["diagnostics"]["maximumOvertimePeriodsAppended"], 1)
        self.assertEqual(result["diagnostics"]["drawCount"], 1000)

    def test_seed_reproduction_and_pooled_centering(self):
        seed = game_seed("NBA:GAME_A", "CONFIG:A", 873)
        self.assertEqual(seed, game_seed("NBA:GAME_A", "CONFIG:A", 873))
        self.assertNotEqual(seed, game_seed("NBA:GAME_B", "CONFIG:A", 873))
        kwargs = dict(predicted_home=106.2, predicted_away=102.9,
                      residuals=[[3, 5], [-1, -3], [4, -1]], seed=seed,
                      draws=1000, overtime_evidence=[[7, 5], [4, 9]])
        first, second = simulate(**kwargs), simulate(**kwargs)
        for key in ("home_runs", "away_runs", "residual_indices", "overtime_period_counts"):
            np.testing.assert_array_equal(first[key], second[key])
        np.testing.assert_allclose(first["diagnostics"]["residualPooledColumnMeans"], [2, 1 / 3])
        self.assertTrue(np.issubdtype(first["home_runs"].dtype, np.integer))

    def test_probability_and_full_population_accounting(self):
        result = simulate(111, 109, [[-8, 6], [8, -6]], seed=221,
                          draws=1000, overtime_evidence=[[5, 7], [8, 6]])
        summary = summarize(result["home_runs"], result["away_runs"])
        self.assertEqual(summary["drawCount"], 1000)
        self.assertEqual(summary["homeWinProbability"] + summary["awayWinProbability"], 1)
        self.assertEqual(summary["tieProbability"], 0)
        for name, rows in summary["distributions"].items():
            self.assertEqual(sum(row["count"] for row in rows), 1000)
            self.assertAlmostEqual(sum(row["probability"] for row in rows), 1)
            self.assertAlmostEqual(sum(row["value"] * row["count"] for row in rows) / 1000,
                                   summary["marginals"][name]["mean"])
        self.assertAlmostEqual(summary["expectedTotal"], summary["expectedHomeScore"] + summary["expectedAwayScore"])

    def test_proper_scores_match_explicit_small_population(self):
        home, away = np.array([100, 110, 110, 90]), np.array([99, 108, 108, 101])
        observed = np.array([103, 101])
        pairs = np.column_stack((home, away))
        brute_energy = np.linalg.norm(pairs - observed, axis=1).mean() - 0.5 * np.linalg.norm(
            pairs[:, None] - pairs[None], axis=2).mean()
        brute_crps = np.abs(home - observed[0]).mean() - 0.5 * np.abs(home[:, None] - home[None]).mean()
        self.assertAlmostEqual(joint_energy_score(home, away, observed), brute_energy)
        self.assertAlmostEqual(empirical_crps(home, observed[0]), brute_crps)
        score = score_forecast(home, away, 103, 101)
        self.assertAlmostEqual(score["binaryBrier"], (0.75 - 1)**2)
        self.assertAlmostEqual(score["winnerLogLoss"], -np.log(0.75))
        self.assertEqual(set(score["marginals"]["home"]["centralPredictionIntervals"]), {"0.5", "0.8", "0.9"})

    def test_final_ties_bad_alignment_and_tied_truth_are_rejected(self):
        with self.assertRaises(DistributionUnsupported):
            summarize([100, 101], [100, 99])
        with self.assertRaises(DistributionUnsupported):
            summarize([100, 101], [99, 99, 99])
        with self.assertRaises(DistributionUnsupported):
            score_forecast([100, 101], [99, 99], 100, 100)


if __name__ == "__main__":
    unittest.main()

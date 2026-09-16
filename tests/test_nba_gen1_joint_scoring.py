"""UNIT_ONLY numerical parity checks; no real sports outcomes or model fitting."""
import unittest
from unittest.mock import patch

import numpy as np

from server.sports_nba_gen1.distribution import DistributionUnsupported, joint_energy_score
from server.sports_nba_gen1 import joint_residual_scoring as scoring


class NbaGen1JointScoringTests(unittest.TestCase):
    def assert_reference(self, home, away, observed):
        expected = joint_energy_score(home, away, observed)
        found = scoring.energy_score(home, away, observed[0], observed[1])
        self.assertAlmostEqual(found, expected, delta=1e-11 * max(1, abs(expected)))
        return found

    def test_repeated_scores_retain_original_v_statistic_denominator(self):
        home = np.array([100, 100, 100, 104, 104, 107, 109, 109])
        away = np.array([99, 99, 99, 108, 108, 101, 115, 115])
        expected = self.assert_reference(home, away, [105, 102])
        pairs = np.column_stack((home, away))
        brute = (np.linalg.norm(pairs - [105, 102], axis=1).mean()
                 - np.linalg.norm(pairs[:, None] - pairs[None, :], axis=2).mean() / 2)
        self.assertAlmostEqual(expected, brute, places=12)

    def test_negative_margins_and_home_away_orientation(self):
        home, away = np.array([80, 92, 101, 107, 120]), np.array([115, 108, 98, 123, 121])
        first = self.assert_reference(home, away, [95, 110])
        flipped = self.assert_reference(away, home, [110, 95])
        self.assertAlmostEqual(first, flipped, places=12)

    def test_full_10000_draw_population_parity_and_no_mutation(self):
        rng = np.random.default_rng(91201)
        raw = rng.multivariate_normal([110, 108], [[144, 45], [45, 121]], 10_000)
        home, away = np.rint(raw).astype(np.int64).T
        away = away + (home == away)
        before_home, before_away = home.copy(), away.copy()
        with patch.object(scoring, "_reference_energy", wraps=joint_energy_score) as fallback:
            first = self.assert_reference(home, away, [112, 105])
            self.assertEqual(fallback.call_count, 0)
            self.assertEqual(first, scoring.energy_score(home, away, 112, 105))
        np.testing.assert_array_equal(home, before_home)
        np.testing.assert_array_equal(away, before_away)

    def test_degenerate_single_joint_point(self):
        self.assertEqual(self.assert_reference([110] * 10, [100] * 10, [110, 100]), 0)
        self.assert_reference([110] * 10, [100] * 10, [102, 104])

    def test_oversized_sparse_tail_uses_full_reference_population(self):
        home = np.array([10, 12, 1_000_000, 1_000_000])
        away = np.array([20, 18, 120, 120])
        with patch.object(scoring, "_reference_energy", wraps=joint_energy_score) as fallback:
            with patch.object(scoring, "_fftconvolve", side_effect=AssertionError("Oversized grid must not be allocated")):
                self.assert_reference(home, away, [15, 19])
            fallback.assert_called_once()
            np.testing.assert_array_equal(fallback.call_args.args[0], home)
            np.testing.assert_array_equal(fallback.call_args.args[1], away)

    def test_failed_fft_integrity_uses_established_exact_scorer(self):
        home, away = np.array([10, 11, 12, 13]), np.array([20, 22, 21, 24])
        original_fft = scoring._fftconvolve

        def corrupted(amount):
            def call(*args, **kwargs):
                result = original_fft(*args, **kwargs)
                result[0, 0] += amount
                return result
            return call

        for amount in (0.25, 1.0):
            with self.subTest(amount=amount), patch.object(scoring, "_reference_energy", wraps=joint_energy_score) as fallback:
                with patch.object(scoring, "_fftconvolve", side_effect=corrupted(amount)):
                    self.assert_reference(home, away, [15, 19])
                fallback.assert_called_once()

    def test_invalid_final_populations_and_observations_fail(self):
        cases = [([1], [2], 3, 4), ([1, 2], [2], 3, 4), ([1, 2], [2, 2], 3, 4),
                 ([-1, 2], [2, 3], 3, 4), ([1.5, 2], [2, 3], 3, 4),
                 ([1, np.nan], [2, 3], 3, 4), ([1, 2], [2, 3], 4, 4),
                 ([1, 2], [2, 3], -1, 4), ([1, 2], [2, 3], 1.5, 4)]
        for home, away, oh, oa in cases:
            with self.subTest(home=home, away=away, observation=(oh, oa)), self.assertRaises(DistributionUnsupported):
                scoring.energy_score(home, away, oh, oa)


if __name__ == "__main__":
    unittest.main()

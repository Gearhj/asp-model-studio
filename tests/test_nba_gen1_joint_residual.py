"""Synthetic checks for the additive NBA final-score residual configuration.

These checks read no basketball records, models, forecasts or source payloads.
"""
from __future__ import annotations

from itertools import product
import unittest

import numpy as np
import pandas as pd

from server.sports_nba_gen1 import joint_residual as subject


def synthetic_bank_frame(count=200):
    dates = pd.date_range("2020-01-01", periods=count, freq="D")
    return pd.DataFrame({
        "game_id": [f"synthetic-{i:03d}" for i in range(count)],
        "game_date": dates,
        "training_last_date": dates - pd.Timedelta(days=1),
    })


class FinalScoreProjectionTests(unittest.TestCase):
    def test_projection_minimizes_distance_over_valid_lattice(self):
        # Enumerate the support independently, including zero-floor cases,
        # half-integer boundaries and latent ties. This is not the projection
        # implementation's four-neighbor construction.
        values = (-2.3, -0.2, 0.0, 0.2, 0.5, 1.1, 1.5, 2.4, 3.5, 4.7)
        latent = np.array(list(product(values, repeat=2)))
        original = latent.copy()
        lattice = np.array([(h, a) for h, a in product(range(7), repeat=2) if h != a])
        final, stages = subject.project_final_scores(latent, np.random.default_rng(19))
        minimum = ((latent[:, None, :] - lattice[None, :, :]) ** 2).sum(axis=2).min(axis=1)
        chosen = ((latent - final) ** 2).sum(axis=1)
        np.testing.assert_allclose(chosen, minimum, rtol=0, atol=1e-12)
        np.testing.assert_array_equal(latent, original)
        self.assertEqual(len(final), len(latent))
        self.assertTrue(np.issubdtype(final.dtype, np.integer))
        self.assertTrue((final >= 0).all())
        self.assertTrue((final[:, 0] != final[:, 1]).all())
        np.testing.assert_array_equal(stages["latent"], original)

    def test_unique_projection_is_team_symmetric_and_keeps_upper_tail(self):
        latent = np.array([
            [100.4, 100.2], [100.2, 100.4], [100.4, 99.7],
            [0.1, -0.3], [-2.4, -0.1], [0.2, 1.3], [347.2, 281.4],
        ])
        final, _ = subject.project_final_scores(latent, np.random.default_rng(1))
        swapped, _ = subject.project_final_scores(latent[:, ::-1], np.random.default_rng(8))
        np.testing.assert_array_equal(final, swapped[:, ::-1])
        np.testing.assert_array_equal(final[-1], [347, 281])
        self.assertTrue(((latent[:, 0] - latent[:, 1]) * (final[:, 0] - final[:, 1]) > 0).all())

    def test_equal_cost_choices_are_reproducible_and_do_not_discard_ties(self):
        latent = np.tile([100.0, 100.0], (subject.DRAW_COUNT, 1))
        first, _ = subject.project_final_scores(latent, np.random.default_rng(34))
        second, _ = subject.project_final_scores(latent, np.random.default_rng(34))
        np.testing.assert_array_equal(first, second)
        self.assertEqual(len(first), subject.DRAW_COUNT)
        self.assertEqual(set(map(tuple, first)), {(101, 100), (99, 100), (100, 101), (100, 99)})
        self.assertTrue((np.abs(first[:, 0] - first[:, 1]) == 1).all())

    def test_nonfinite_or_nonpaired_projection_input_is_rejected(self):
        for invalid in (np.array([1, 2]), np.array([[1, 2, 3]]), np.array([[np.nan, 1]]), np.array([[1, np.inf]])):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "Finite HOME/AWAY"):
                subject.project_final_scores(invalid, np.random.default_rng(1))


class DonorEligibilityTests(unittest.TestCase):
    def test_only_earlier_dates_enter_bank_and_input_is_unchanged(self):
        valid = synthetic_bank_frame()
        extra = pd.DataFrame({
            "game_id": ["target", "same-day-other", "future"],
            "game_date": pd.to_datetime(["2021-01-01", "2021-01-01", "2021-01-02"]),
            # These rows must be excluded before donor chronology validation.
            "training_last_date": pd.to_datetime(["2022-01-01"] * 3),
        })
        all_rows = pd.concat([extra, valid.iloc[::-1]], ignore_index=True)
        original = all_rows.copy(deep=True)
        bank = subject.eligible_bank(all_rows, pd.Timestamp("2021-01-01"), "target")
        self.assertEqual(len(bank), subject.MIN_DONORS)
        self.assertEqual(bank.game_id.tolist(), valid.game_id.tolist())
        pd.testing.assert_frame_equal(all_rows, original)

    def test_target_cannot_be_hidden_as_an_earlier_donor(self):
        rows = synthetic_bank_frame()
        rows.loc[0, "game_id"] = "target"
        with self.assertRaisesRegex(ValueError, "Target appeared"):
            subject.eligible_bank(rows, pd.Timestamp("2021-01-01"), "target")

    def test_at_least_200_earlier_donors_are_required(self):
        with self.assertRaisesRegex(ValueError, "199 earlier OOF donors; require 200"):
            subject.eligible_bank(synthetic_bank_frame(199), pd.Timestamp("2021-01-01"), "target")
        with self.assertRaisesRegex(ValueError, "Supported finite paired OOF bank"):
            subject.simulate_pair([110, 108], np.zeros((199, 2)), "synthetic-target")

    def test_donor_training_must_precede_its_game_and_ids_must_be_unique(self):
        for offset in (0, 1):
            rows = synthetic_bank_frame()
            rows.loc[0, "training_last_date"] = rows.loc[0, "game_date"] + pd.Timedelta(days=offset)
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, "out of fold chronologically"):
                subject.eligible_bank(rows, pd.Timestamp("2021-01-01"), "target")
        rows = synthetic_bank_frame()
        rows.loc[1, "game_id"] = rows.loc[0, "game_id"]
        with self.assertRaisesRegex(ValueError, "Duplicate whole-game"):
            subject.eligible_bank(rows, pd.Timestamp("2021-01-01"), "target")


class JointPopulationTests(unittest.TestCase):
    def test_paired_and_benchmark_are_deterministic_with_exact_latent_marginals(self):
        home = np.linspace(-20, 20, subject.MIN_DONORS)
        bank = np.column_stack([home + 3, 0.8 * home + np.sin(home) - 2])
        bank_before = bank.copy()
        expected = np.array([110.25, 108.75])
        expected_before = expected.copy()
        first, offset = subject.simulate_pair(expected, bank, "synthetic-game")
        second, offset2 = subject.simulate_pair(expected, bank, "synthetic-game")
        np.testing.assert_array_equal(offset, bank.mean(axis=0))
        np.testing.assert_array_equal(offset, offset2)
        np.testing.assert_array_equal(bank, bank_before)
        np.testing.assert_array_equal(expected, expected_before)
        for arm in ("paired", "benchmark"):
            np.testing.assert_array_equal(first[arm]["draws"], second[arm]["draws"])
            for stage in ("latent", "floored", "rounded", "final"):
                np.testing.assert_array_equal(first[arm]["stages"][stage], second[arm]["stages"][stage])
            draws = first[arm]["draws"]
            self.assertEqual(draws.shape, (10_000, 2))
            self.assertTrue((draws >= 0).all())
            self.assertTrue((draws[:, 0] != draws[:, 1]).all())
            pairs, counts = subject.joint_counts(draws)
            self.assertEqual(int(counts.sum()), 10_000)
            self.assertEqual(len(pairs), len(counts))
        paired = first["paired"]["stages"]["latent"]
        benchmark = first["benchmark"]["stages"]["latent"]
        np.testing.assert_array_equal(paired[:, 0], benchmark[:, 0])
        np.testing.assert_array_equal(np.sort(paired[:, 1]), np.sort(benchmark[:, 1]))
        self.assertFalse(np.array_equal(paired[:, 1], benchmark[:, 1]))
        # Every paired latent row retains one complete empirical donor pair.
        supported = expected + bank - offset
        distances = np.abs(paired[:, None, :] - supported[None, :, :]).max(axis=2).min(axis=1)
        np.testing.assert_allclose(distances, 0, rtol=0, atol=1e-12)

    def test_integer_and_half_lines_use_complete_population_and_pushes(self):
        # Totals are 3, 4, 4, 5, 6; identical totals need not have identical pairs.
        draws = np.array([[2, 1], [3, 1], [1, 3], [3, 2], [4, 2]])
        integer = subject.totals_query(draws, 4)
        half = subject.totals_query(draws, 4.5)
        self.assertEqual(integer["drawCount"], 5)
        self.assertEqual(integer["probabilityUnits"], "FRACTIONS_0_TO_1")
        self.assertEqual(integer["over"], {"win": 0.4, "push": 0.4, "loss": 0.2})
        self.assertEqual(integer["under"], {"win": 0.2, "push": 0.4, "loss": 0.4})
        self.assertEqual(half["over"], {"win": 0.4, "push": 0.0, "loss": 0.6})
        self.assertEqual(half["under"], {"win": 0.6, "push": 0.0, "loss": 0.4})
        for query in (integer, half):
            for side in ("over", "under"):
                self.assertAlmostEqual(sum(query[side].values()), 1)
                self.assertTrue(all(0 <= p <= 1 for p in query[side].values()))
            self.assertEqual(query["under"]["win"], query["over"]["loss"])
        pairs, counts = subject.joint_counts(np.vstack([draws, draws[0]]))
        self.assertEqual(dict(zip(map(tuple, pairs), counts))[(2, 1)], 2)
        self.assertEqual(int(counts.sum()), 6)

    def test_unsupported_lines_or_populations_fail_closed(self):
        draws = np.array([[2, 1]])
        for line in (-1, 4.25, np.nan, np.inf):
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, "integer or half-point"):
                subject.totals_query(draws, line)
        for invalid in (np.empty((0, 2)), np.array([[2.1, 1]]), np.array([[np.nan, 1]]), np.array([2, 1])):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "Complete integer joint"):
                subject.totals_query(invalid, 4)


if __name__ == "__main__":
    unittest.main()

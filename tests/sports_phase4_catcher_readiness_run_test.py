"""Hermetic tests for the catcher readiness RUN pipeline (vectorized over frames).

No dataset access, no model fitting. Validates the pandas reconstruction and the
strict prior-history counting, and that the vectorized banding agrees with the pure
``prior_pair_sample_distribution`` engine.
"""

import unittest

import numpy as np
import pandas as pd

from server.sports_phase4 import catcher_readiness as cr
from server.sports_phase4 import catcher_readiness_run as run


def _fielding(rows):
    cols = ["game_id", "team_id", "player_id", "season", "game_date",
            "fielding_position", "stat_d_gs", "appearance_sequence", "stat_d_ifouts",
            "canonical_identity_resolved"]
    return pd.DataFrame(rows, columns=cols)


def _pa(rows):
    cols = ["game_id", "pitching_team_id", "batter_id", "pitcher_id", "season",
            "game_date", "half_play_number", "canonical_identity_resolved"]
    return pd.DataFrame(rows, columns=cols)


class VectorizedPriorCountTest(unittest.TestCase):
    def test_matches_pure_bisect_engine(self):
        # Same battery across three ascending dates + a same-date tie.
        frame = pd.DataFrame({
            "pair": ["b", "b", "b", "b"],
            "_ord": [10, 20, 20, 30],
        })
        prior = run._vectorized_prior_counts(frame, "pair", "_ord")
        # ord10 -> 0 prior; the two ord20 -> 1 each (only ord10 is strictly before,
        # same-date tie excluded); ord30 -> 3 prior.
        self.assertEqual(list(prior), [0, 1, 1, 3])
        # Cross-check the band aggregation against the pure engine.
        events = [("b", 10), ("b", 20), ("b", 20), ("b", 30)]
        pure = cr.prior_pair_sample_distribution(events)
        vec = run._band_series(prior)
        self.assertEqual(vec["bands"]["0"]["count"], pure["bands"]["0"]["count"])
        self.assertEqual(vec["maxPriorSamples"], pure["maxPriorSamples"])


class ReconstructionTest(unittest.TestCase):
    def test_single_multi_and_missing_team_games(self):
        fielding = _fielding([
            ["g1", "t1", "cat_a", 2023, "2023-04-01", 2, 1, 1, 27, True],
            ["g1", "t1", "ss_x", 2023, "2023-04-01", 6, 1, 1, 6, True],   # non-catcher
            ["g3", "t2", "cat_b", 2023, "2023-04-15", 2, 1, 1, 15, True],
            ["g3", "t2", "cat_c", 2023, "2023-04-15", 2, 0, 2, 12, True],  # sub catcher
        ])
        tg = run.reconstruct_team_game_catchers(fielding)
        by = {(r.game_id, r.team_id): r.status for r in tg.itertuples(index=False)}
        self.assertEqual(by[("g1", "t1")], "DETERMINISTIC")
        self.assertEqual(by[("g3", "t2")], "MULTI_CATCHER")


class ComputeAuditTest(unittest.TestCase):
    def _frames(self):
        fielding = _fielding([
            ["g1", "t1", "cat_a", 2023, "2023-04-01", 2, 1, 1, 27, True],
            ["g2", "t1", "cat_a", 2023, "2023-04-08", 2, 1, 1, 27, True],
            ["g3", "t2", "cat_b", 2023, "2023-04-15", 2, 1, 1, 15, True],
            ["g3", "t2", "cat_c", 2023, "2023-04-15", 2, 0, 2, 12, True],
        ])
        pa = _pa([
            # g1 defense t1: two PAs of battery (p1, cat_a)
            ["g1", "t1", "bat1", "p1", 2023, "2023-04-01", 1, True],
            ["g1", "t1", "bat2", "p1", 2023, "2023-04-01", 2, True],
            # g2 defense t1: one PA of battery (p1, cat_a) -> sees 2 prior
            ["g2", "t1", "bat1", "p1", 2023, "2023-04-08", 1, True],
            # g3 defense t2: multi-catcher -> ambiguous
            ["g3", "t2", "bat3", "p2", 2023, "2023-04-15", 1, True],
        ])
        role_map = {("g1", "p1"): "STARTER", ("g2", "p1"): "STARTER", ("g3", "p2"): "RELIEVER"}
        return fielding, pa, role_map

    def test_coverage_and_no_self_inclusion(self):
        fielding, pa, role_map = self._frames()
        audit, decision = run.compute_catcher_readiness(
            fielding, pa, role_map,
            dataset_authority={"registrationId": "r"},
            identity_bridge_authority={"registrationId": "b"},
            available_field_names={"player_game_fielding": set(fielding.columns)},
        )
        payload = audit.to_registry_payload(run_id="run_x", contract_sha="0" * 64)
        cov = payload["paCatcherAssignmentCoverage"]["2023"]
        self.assertEqual(cov["plateAppearances"], 4)
        self.assertEqual(cov["deterministicCatcherAssignment"], 3)  # g1(2)+g2(1)
        self.assertEqual(cov["ambiguous"], 1)                        # g3
        battery_2023 = payload["batterySampleDistribution"]["bySeason"]["2023"]
        # 3 deterministic battery PAs. g1's two PAs share a date (0 prior each);
        # g2's PA sees 2 prior -> band "1-9".
        self.assertEqual(battery_2023["bands"]["0"]["count"], 2)
        self.assertEqual(battery_2023["bands"]["1-9"]["count"], 1)
        self.assertEqual(battery_2023["maxPriorSamples"], 2)
        self.assertIn(payload["terminalStatus"], cr.TERMINAL_STATUSES)
        self.assertEqual(payload["batterySampleDistribution"]["roleSegmentation"]["starterPlateAppearances"], 3)

    def test_no_fabricated_metrics_in_payload(self):
        fielding, pa, role_map = self._frames()
        audit, _ = run.compute_catcher_readiness(
            fielding, pa, role_map,
            dataset_authority={}, identity_bridge_authority={},
            available_field_names={"player_game_fielding": set(fielding.columns)},
        )
        text = repr(audit.to_registry_payload(run_id="r", contract_sha="0" * 64)).lower()
        for forbidden in ("logloss", "brier", "accuracy", "auc", " ece", "f1_"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()

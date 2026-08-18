from __future__ import annotations

import unittest

import numpy as np
import pyarrow as pa

from server.sports_phase4.participation_contract import (
    BULLPEN_FEATURES,
    LINEUP_FEATURES,
    STARTER_FEATURES,
)
from server.sports_phase4.participation_metrics import (
    ParticipationMetricsError,
    bullpen_metrics,
)
from tests.sports_phase4_participation_fixture import build_fixture_views


class ParticipationFeaturesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.views = build_fixture_views()

    def test_exact_feature_columns_and_id_exclusion(self) -> None:
        for table, features in (
            (self.views.lineup, LINEUP_FEATURES),
            (self.views.starter, STARTER_FEATURES),
            (self.views.bullpen, BULLPEN_FEATURES),
        ):
            self.assertTrue(set(features).issubset(table.column_names))
            self.assertFalse(any(name in features for name in table.column_names if "id" in name))
        dynamic_log_odds = [name for name in STARTER_FEATURES if "log_odds" in name]
        self.assertEqual(len(dynamic_log_odds), 7)
        self.assertEqual(
            [name for name in BULLPEN_FEATURES if "log_odds" in name],
            dynamic_log_odds,
        )
        self.assertFalse(any("log_odds" in name for name in LINEUP_FEATURES))
        self.assertIn("prior_bfp_1d", BULLPEN_FEATURES)
        self.assertIn("prior_outs_1d", BULLPEN_FEATURES)

    def test_current_target_participant_is_not_injected(self) -> None:
        views = build_fixture_views(target_only_batter=True)
        evidence = views.coverage["lineup"][0]
        self.assertGreater(evidence["uncoveredPositiveRows"], 0)
        first = views.lineup.filter(
            pa.array(
                np.asarray(views.lineup["game_date"].to_pylist(), dtype=object)
                == "2023-04-01"
            )
        )
        self.assertFalse(
            any("target-only" in value for value in first["canonical_player_uuid"].to_pylist())
        )

    def test_complete_lineup_eligibility_excludes_both_teams_and_is_measured(self) -> None:
        views = build_fixture_views(incomplete_lineup_game=True)
        evidence = next(item for item in views.coverage["lineup"] if item["season"] == 2024)
        self.assertEqual(evidence["completeLineupEligibleGames"], 3)
        self.assertEqual(evidence["completeLineupExcludedGames"], 1)
        self.assertEqual(evidence["eligibleTargetTeamGames"], 6)
        self.assertEqual(evidence["excludedTargetTeamGames"], 2)
        season_rows = sum(1 for value in views.lineup["season"].to_pylist() if value == 2024)
        self.assertEqual(season_rows, 72)

    def test_bullpen_zero_reliever_and_empty_pool_denominators_reconcile(self) -> None:
        mask = np.asarray(self.views.bullpen["season"].to_pylist()) == 2025
        table = self.views.bullpen.filter(pa.array(mask))
        coverage = dict(next(item for item in self.views.coverage["bullpen"] if item["season"] == 2025))
        coverage["targetTeamGames"] += 1
        coverage["zeroRelieverTeamGames"] += 1
        coverage["emptyCandidatePools"] += 1
        coverage["emptyPoolZeroRelieverTeamGames"] += 1
        probabilities = np.full(table.num_rows, 0.2)
        durations = np.full(table.num_rows, 4.0)
        metrics = bullpen_metrics(
            table,
            probabilities,
            durations,
            durations,
            coverage_evidence=coverage,
        )
        self.assertEqual(metrics["teamGameCount"], 9)
        self.assertEqual(metrics["totalActualPositiveCount"], 14)
        self.assertIsNotNone(metrics["zeroRelieverAccuracy"])
        contradiction = dict(coverage)
        contradiction["emptyPoolZeroRelieverTeamGames"] = 0
        with self.assertRaises(ParticipationMetricsError):
            bullpen_metrics(
                table,
                probabilities,
                durations,
                durations,
                coverage_evidence=contradiction,
            )


if __name__ == "__main__":
    unittest.main()

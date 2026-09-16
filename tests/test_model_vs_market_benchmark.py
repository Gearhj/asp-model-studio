from copy import deepcopy
import unittest

from server.sports_shared.model_vs_market_benchmark import (
    BINARY_BRIER,
    fit_development_blend,
    no_vig_home_probability,
    score_benchmark,
    validate_observation,
)


def observation(*, event="mlb:1", sport="MLB", home=0.60, away=0.40, tie=0.0, final=(5, 3), start="2026-09-10T23:00:00Z"):
    return {
        "schemaVersion": "MODEL_VS_MARKET_OBSERVATION_V1",
        "observationId": f"{event}:DECISION_TIME",
        "sport": sport,
        "season": 2026,
        "eventId": event,
        "eventStartUtc": start,
        "supportCohort": "PROSPECTIVE_CAPTURE_V1",
        "decisionStatus": "NO_BET",
        "evidenceRole": "PROSPECTIVE_ACCUMULATION",
        "forecast": {
            "forecastId": f"forecast:{event}",
            "engineId": "ENGINE",
            "availableAtUtc": "2026-09-10T22:20:00Z",
            "homeWinProbability": home,
            "awayWinProbability": away,
            "tieProbability": tie,
            "expectedHomeScore": 4.5 if sport == "MLB" else 24.0,
            "expectedAwayScore": 3.8 if sport == "MLB" else 21.0,
        },
        "market": {
            "horizon": "DECISION_TIME",
            "asOfUtc": "2026-09-10T22:45:00Z",
            "noVigMethod": "PROPORTIONAL_IMPLIED_PROBABILITY_V1",
            "homeMarginLine": 1.5,
            "totalLine": 8.5,
            "quotes": [{
                "provider": "persisted-fixture",
                "sportsbook": "Book A",
                "marketType": "FULL_GAME_MONEYLINE",
                "period": "FULL_GAME",
                "home": {"snapshotId": "h", "decimalOdds": 1.8, "observedAtUtc": "2026-09-10T22:40:00Z", "availableAsOfUtc": "2026-09-10T22:41:00Z"},
                "away": {"snapshotId": "a", "decimalOdds": 2.1, "observedAtUtc": "2026-09-10T22:39:00Z", "availableAsOfUtc": "2026-09-10T22:41:00Z"},
            }],
        },
        "final": {
            "identity": f"final:{event}:r1", "revision": 1, "status": "FINAL",
            "availableAtUtc": "2026-09-11T03:00:00Z", "homeScore": final[0], "awayScore": final[1],
        },
    }


class ModelVsMarketBenchmarkTests(unittest.TestCase):
    def test_proportional_devig_and_leg_freshness(self):
        self.assertAlmostEqual(no_vig_home_probability(1.8, 2.1), (1 / 1.8) / (1 / 1.8 + 1 / 2.1))
        row = validate_observation(observation())
        self.assertEqual(row["market"]["quotes"][0]["olderLegFreshnessSeconds"], 360.0)

    def test_chronology_and_incomplete_market_fail_closed(self):
        row = observation()
        row["market"]["quotes"] = []
        with self.assertRaises(ValueError):
            validate_observation(row)
        row = observation()
        row["forecast"]["availableAtUtc"] = "2026-09-10T22:50:00Z"
        with self.assertRaises(ValueError):
            validate_observation(row)

    def test_distinct_games_are_scored_once_with_explicit_binary_brier(self):
        rows = [
            observation(event="mlb:1", final=(5, 3)),
            observation(event="mlb:2", home=0.45, away=0.55, final=(2, 4)),
        ]
        report = score_benchmark(rows, scored_at_utc="2026-09-12T00:00:00Z")
        self.assertEqual(report["sports"]["MLB"]["games"], 2)
        self.assertEqual(report["sports"]["MLB"]["model"]["brierDefinition"], BINARY_BRIER)
        self.assertEqual(report["coverage"]["eligibleMatchedFinals"], 2)
        with self.assertRaises(ValueError):
            score_benchmark(rows + [deepcopy(rows[0])], scored_at_utc="2026-09-12T00:00:00Z")

    def test_nfl_tie_is_preserved_and_excluded_from_two_way_comparison(self):
        row = observation(event="nfl:1", sport="NFL", home=0.50, away=0.46, tie=0.04, final=(20, 20))
        report = score_benchmark([row], scored_at_utc="2026-09-12T00:00:00Z")
        self.assertEqual(report["coverage"]["realizedTiePushesExcludedFromBinaryComparison"], 1)
        self.assertEqual(report["sports"]["NFL"]["games"], 0)

    def test_blend_cannot_fit_without_authorized_development(self):
        self.assertEqual(fit_development_blend([observation()])["status"], "NOT_FIT_INSUFFICIENT_AUTHORIZED_DEVELOPMENT")


if __name__ == "__main__":
    unittest.main()

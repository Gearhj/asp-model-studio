from datetime import UTC, datetime

import pytest

from server.sports_nfl_m1 import production_handoff as subject


def _forecast():
    return {
        "eventId": "2026_02_NYG_LA",
        "sourceEventId": "nflverse:2026_02_NYG_LA",
        "awayTeam": {"abbreviation": "NYG"},
        "homeTeam": {"abbreviation": "LAR"},
        "simulator": {"simulationCount": 10000, "completedSimulations": 10000},
        "jointScoreDistribution": [
            {"awayScore": 10, "homeScore": 20, "probability": 0.45},
            {"awayScore": 20, "homeScore": 10, "probability": 0.40},
            {"awayScore": 17, "homeScore": 17, "probability": 0.15},
        ],
        "scoreMarginDistribution": [
            {"homeMinusAway": -10, "probability": 0.40},
            {"homeMinusAway": 0, "probability": 0.15},
            {"homeMinusAway": 10, "probability": 0.45},
        ],
        "totalScoreDistribution": [
            {"totalScore": 30, "probability": 0.85},
            {"totalScore": 34, "probability": 0.15},
        ],
        "homeWinProbability": 0.45,
        "awayWinProbability": 0.40,
        "tieProbability": 0.15,
        "expectedHomeScore": 15.55,
        "expectedAwayScore": 15.05,
    }


def test_population_reconciles_joint_outcomes_and_score_derivatives():
    forecast = _forecast()
    subject._orientation(forecast)
    result = subject._population(forecast)
    assert result["drawCount"] == 10000
    assert result["homeWinProbability"] == 0.45
    assert result["awayWinProbability"] == 0.40
    assert result["tieProbability"] == 0.15
    assert len(result["populationSha256"]) == 64


def test_population_rejects_probability_or_derivative_drift():
    forecast = _forecast()
    forecast["homeWinProbability"] = 0.46
    with pytest.raises(subject.NflProductionHandoffError, match="homeWinProbability"):
        subject._population(forecast)
    forecast = _forecast()
    forecast["scoreMarginDistribution"][0]["probability"] = 0.39
    with pytest.raises(subject.NflProductionHandoffError, match="margin distribution"):
        subject._population(forecast)


def test_orientation_rejects_home_away_swap_but_accepts_lar_alias():
    forecast = _forecast()
    subject._orientation(forecast)
    forecast["homeTeam"]["abbreviation"] = "NYG"
    with pytest.raises(subject.NflProductionHandoffError, match="orientation"):
        subject._orientation(forecast)


def test_handoff_keeps_three_way_ties_and_disallows_play_level_substitution():
    discovery = {
        "effectiveFromUtc": "2026-09-20T17:00:00.000000Z",
        "model": {"featureContractSha256": "a" * 64},
        "forecasts": [{
            "eventId": "2026_02_NYG_LA", "forecastId": "forecast:1",
            "sourceBundleSha256": "b" * 64, "populationSha256": "c" * 64,
            "drawCount": 10000,
        }],
    }
    handoff = subject.build_handoff(
        discovery,
        discovery_path="nfl-m1-production-v1/discovery/sha256/" + "d" * 64 + "/discovery-index.json",
        discovery_sha256="d" * 64,
        issued_at_utc=datetime(2026, 9, 17, 20, 0, tzinfo=UTC),
        issuer_revision="e" * 40,
    )
    assert handoff["tiePolicy"]["outcomes"] == ["HOME", "TIE", "AWAY"]
    assert handoff["tiePolicy"]["probabilityMass"] == "RETAINED_NOT_REDISTRIBUTED"
    assert handoff["playLevelSubstitutionAllowed"] is False
    assert handoff["forecastPopulations"] == {}
    assert handoff["seedForecastPopulationEvidence"][0]["populationSha256"] == "c" * 64

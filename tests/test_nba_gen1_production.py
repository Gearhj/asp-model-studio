import copy

import numpy as np
import pytest

from server.sports_nba_gen1.joint_residual import DRAW_COUNT, ENGINE
from server.sports_nba_gen1.production import (
    CONFIGURATION, assemble_forecast, digest, summarize_population, verify_forecast,
)


def population():
    home = 100 + np.arange(DRAW_COUNT) % 23
    away = 99 + np.arange(DRAW_COUNT) % 19
    tied = home == away
    home[tied] += 1
    return np.column_stack((home, away)).astype(np.int64)


def point():
    return {"configurationIdentity": CONFIGURATION,
            "sourceCutoffUtc": "2026-09-14T13:04:43+00:00",
            "game": {"game_id": "nba-espn:game:2", "status": "SCHEDULED",
                     "home_team_id": "home", "away_team_id": "away"},
            "pointExpectations": {"home": 111.0, "away": 109.0, "total": 220.0,
                                  "homeMargin": 2.0, "units": "points including overtime"},
            "winnerProbabilities": {"home": .55, "away": .45, "tie": 0.0}}


def test_population_accounting_orientation_and_assembly():
    draws = population()
    summary = summarize_population(draws)
    assert summary["drawCount"] == DRAW_COUNT
    assert all(sum(cell["count"] for cell in summary["pmfs"][key]) == DRAW_COUNT
               for key in ("home", "away", "total", "margin"))
    assert summary["expectedScores"]["total"] == pytest.approx(
        summary["expectedScores"]["home"] + summary["expectedScores"]["away"])
    forecast = assemble_forecast(point_forecast=point(), draws=draws,
        created_at_utc="2026-09-18T01:00:00+00:00",
        effective_at_utc="2026-09-18T00:59:00+00:00",
        handoff={"sha256": "a" * 64}, bindings={"x": 1},
        population={"drawCount": DRAW_COUNT, "logicalSha256": digest(draws.astype("<i8").tobytes())})
    assert forecast["distributionConfigurationIdentity"] == ENGINE
    assert forecast["eloWinnerProbabilities"]["home"] == .55
    assert forecast["closeScoreChallenger"]["enabled"] is False
    verify_forecast(forecast, draws)


def test_ties_or_tampering_fail_closed():
    draws = population()
    draws[0] = [100, 100]
    with pytest.raises(ValueError):
        summarize_population(draws)
    draws = population()
    forecast = assemble_forecast(point_forecast=point(), draws=draws,
        created_at_utc="2026-09-18T01:00:00+00:00",
        effective_at_utc="2026-09-18T00:59:00+00:00",
        handoff={"sha256": "a" * 64}, bindings={},
        population={"drawCount": DRAW_COUNT, "logicalSha256": "b" * 64})
    bad = copy.deepcopy(forecast)
    bad["jointSimulation"]["expectedScores"]["home"] += 1
    with pytest.raises(ValueError):
        verify_forecast(bad, draws)

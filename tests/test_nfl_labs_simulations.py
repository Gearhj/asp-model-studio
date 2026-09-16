"""Narrow invariants for exact-distribution export and drive score/clock logic."""
from datetime import datetime, timezone

import numpy as np
import pytest

from pathlib import Path
from server.sports_nfl_m1.labs_simulation import empirical_scores, market_query, score_supplement, summarize_scores, pregame_clock, PregameClosed
from server.sports_nfl_m1.labs_simulation_drives import overtime_finished, verify_drive_accounting, starting_kickoff_evidence


def test_exact_empirical_population_and_market_push_contract():
    source = {"simulator": {"simulationCount": 10}, "jointScoreDistribution": [
        {"homeScore": 21, "awayScore": 17, "probability": .4},
        {"homeScore": 17, "awayScore": 21, "probability": .3},
        {"homeScore": 20, "awayScore": 20, "probability": .3}]}
    home, away = empirical_scores(source)
    assert summarize_scores(home, away)["tieProbability"] == .3
    assert market_query(home, away, home_spread=-4, total_line=38) == {
        "homeCoverProbability": 0.0, "awayCoverProbability": .6, "spreadPushProbability": .4,
        "overProbability": .3, "underProbability": 0.0, "totalPushProbability": .7}
    source["jointScoreDistribution"][0]["probability"] = .35
    with pytest.raises(ValueError, match="population|integer"):
        empirical_scores(source)


def test_overtime_historical_and_current_possession_rules():
    args = dict(first_drive_defensive_score=False, first_drive_td=True)
    assert overtime_finished(6, 0, 1, season=2024, postseason=False, **args)
    assert not overtime_finished(7, 0, 1, season=2026, postseason=False, **args)
    assert not overtime_finished(7, 0, 1, season=2024, postseason=True, **args)
    assert overtime_finished(7, 3, 2, season=2026, postseason=False, **args)
    assert not overtime_finished(7, 7, 2, season=2026, postseason=False, **args)
    assert overtime_finished(0, 2, 1, first_drive_defensive_score=True,
                             first_drive_td=False, season=2026, postseason=False)


def test_drive_replay_score_and_clock_fail_closed():
    game = {"homeScore": 7, "awayScore": 0, "drives": [
        {"period": "REGULATION_HALF_1", "durationSeconds": 200,
         "periodSecondsBefore": 1800, "periodSecondsAfter": 1600,
         "homePointsAdded": 7, "awayPointsAdded": 0,
         "homeScoreAfter": 7, "awayScoreAfter": 0}]}
    verify_drive_accounting(game)
    game["drives"][0]["periodSecondsAfter"] = 1601
    with pytest.raises(ValueError, match="clock"):
        verify_drive_accounting(game)


def test_no_retroactive_pregame_supplement():
    forecast = {"sourceCutoffUtc": "2026-09-08T00:00:00Z", "forecastCutoffUtc": "2026-09-09T00:00:00Z",
                "availableAsOfUtc": "2026-09-09T00:00:00Z", "scheduledStartUtc": "2026-09-10T00:00:00Z"}
    with pytest.raises(ValueError, match="precede kickoff"):
        score_supplement(forecast, bundle_path=Path("unused-no-read"), published_at=datetime(2026, 9, 10, tzinfo=timezone.utc))


def test_starting_kickoff_touchback_and_fresh_publication_clock_regression():
    import pandas as pd
    group = pd.DataFrame([
        {"play_id": 1, "play_type": "kickoff", "touchback": 0, "posteam": "NE"},
        {"play_id": 2, "play_type": "run", "touchback": 0, "posteam": "NE"},
        {"play_id": 3, "play_type": "punt", "touchback": 1, "posteam": "NE"},
        {"play_id": 4, "play_type": "kickoff", "touchback": 1, "posteam": "SEA"}])
    assert starting_kickoff_evidence(group,group.iloc[1]) == (True,0.0,"OBSERVED_STARTING_KICKOFF_PLAY")
    unknown = starting_kickoff_evidence(group.iloc[1:],group.iloc[1])
    assert unknown[0] is False and np.isnan(unknown[1]) and unknown[2] == "STARTING_KICKOFF_ABSENT"
    moments = iter([datetime(2026,9,10,0,0,0,tzinfo=timezone.utc),datetime(2026,9,10,0,0,2,tzinfo=timezone.utc)])
    kickoff = "2026-09-10T00:00:01Z"
    assert pregame_clock(kickoff,clock=lambda:next(moments),stage="EVENT_INFERENCE").second == 0
    with pytest.raises(PregameClosed,match="BEFORE_PUBLICATION"):
        pregame_clock(kickoff,clock=lambda:next(moments),stage="PUBLICATION")

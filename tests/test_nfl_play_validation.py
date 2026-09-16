"""Only the new population selection and historical pregame isolation contracts."""
from server.sports_nfl_m1.play_validation import distribution_summary, historical_game_validation, representative_indices


def test_population_representatives_are_distinct_actual_games_and_pmf_reconciles():
    finals = [{"simulationIndex": index, "homeScore": home, "awayScore": away, "reachedOvertime": home == away}
              for index, (home, away) in enumerate([(24, 20), (21, 20), (28, 14), (14, 28), (42, 35), (6, 3), (20, 20), (10, 7)])]
    selected = representative_indices(finals)
    assert set(selected) == {"Typical", "Close", "Home win", "Away win", "High scoring", "Low scoring"}
    assert len(set(selected.values())) == 6
    assert finals[selected["Home win"]]["homeScore"] > finals[selected["Home win"]]["awayScore"]
    assert finals[selected["Away win"]]["homeScore"] < finals[selected["Away win"]]["awayScore"]
    result = distribution_summary(finals)
    assert result["drawCount"] == 8
    assert sum(p["probability"] for p in result["jointScoreDistribution"]) == 1
    assert result["scoreSummary"]["tieProbability"] == 1 / 8


def test_historical_outcomes_do_not_enter_simulator_and_2025_is_never_selected():
    calls = []
    def simulate(model, **kwargs):
        calls.append(kwargs)
        return {"homeScore": 0, "awayScore": 0, "reachedOvertime": True, "plays": []}
    games = [{"season": 2024, "seasonType": "REG", "gameId": f"2024_fixture_{index:02}", "date": "2024-09-05",
              "homeTeam": "SEA", "awayTeam": "NE", "homeScore": 999, "awayScore": 17, "observedDriveCount": 20}
             for index in range(32)]
    games.append({**games[0], "season": 2025, "gameId": "SEALED_NOT_SELECTED"})
    report = historical_game_validation(object(), games, simulate=simulate, draws=1)
    assert report["games"] == 32 and len(calls) == 32
    assert all(set(call) == {"home_team", "away_team", "season", "seed", "scenario", "postseason", "include_geometry"} for call in calls)
    assert all(call["season"] == 2024 for call in calls)
    assert all(row["gameId"] != "SEALED_NOT_SELECTED" for row in report["perGame"])
    assert report["populationAccounting"]["impossibleStateCount"] == 0
    assert report["zeroDrawObservedClassGames"] == 32


def test_validation_reuse_accepts_renderer_only_successor_but_rejects_numerical_changes():
    import copy
    import pytest
    from scripts.publish_nfl_play_level import _assert_validation_compatibility

    previous = {"implementation": {f"server/sports_nfl_m1/{name}": {"sha256": name}
                                    for name in ("play_evidence.py", "play_model.py", "play_engine.py", "play_validation.py", "play_geometry.py")},
                **{key: {"unchanged": key} for key in ("modelConfiguration", "scenarioDefinitions", "historicalFixture", "sourcePartitions",
                                                       "trainingSeasons", "validationSeason", "validationModelCutoffExclusive", "finalTrainingSeasons")}}
    current = copy.deepcopy(previous)
    current["implementation"]["server/sports_nfl_m1/play_geometry.py"]["sha256"] = "renderer-repair"
    current["contractImplementation"] = {"sha256": "geometry-contract-successor"}
    _assert_validation_compatibility(previous, current)
    current["implementation"]["server/sports_nfl_m1/play_engine.py"]["sha256"] = "changed-numerical-engine"
    with pytest.raises(ValueError, match="play_engine.py"):
        _assert_validation_compatibility(previous, current)
    current = copy.deepcopy(previous)
    current["modelConfiguration"] = {"changed": "prior"}
    with pytest.raises(ValueError, match="modelConfiguration"):
        _assert_validation_compatibility(previous, current)

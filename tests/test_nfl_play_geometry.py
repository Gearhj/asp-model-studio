"""Focused modeled-geometry facts, state continuity and local contract checks."""
import copy
import json

import pytest

from server.sports_nfl_m1.play_geometry import (
    ARTIFACT_VERSION, AUTHORITY, CONTRACT_VERSION, PlayGeometryError,
    geometry_for_play, load_contract, validate_contract_schema,
    validate_play_level_artifact, validate_play_sequence,
)


def state(**updates):
    base = {"possession": "HOME", "quarter": 1, "clockSeconds": 900., "gameSecondsRemaining": 3600.,
            "down": 1, "distance": 10., "yardline100": 60., "homeScore": 0, "awayScore": 0, "phase": "SCRIMMAGE"}
    return {**base, **updates}


def event(kind="PASS_COMPLETE", **outcome):
    return {"playNumber": 1, "driveNumber": 1, "playType": kind, "description": "Anonymous modeled play fixture",
            "stateBefore": state(), "stateAfter": state(clockSeconds=870., gameSecondsRemaining=3570., yardline100=40.),
            "outcome": {"endYardline100": 40., "seconds": 30., "homePointsAdded": 0, "awayPointsAdded": 0,
                        "scoringType": None, **outcome}}


def test_paths_distinguish_modeled_pass_ground_sneak_and_backward_sack_without_physics():
    complete = geometry_for_play(event())
    ground = geometry_for_play(event("RUSH"))
    sneak = geometry_for_play(event("QB_SNEAK", endYardline100=59.))
    sack = geometry_for_play(event("SACK", endYardline100=67.))
    assert complete["segments"][0]["interpolation"] == "CUBIC_BEZIER"
    assert ground["segments"][0]["interpolation"] == "POLYLINE"
    assert sneak["segments"][0]["kind"] == "QB_SNEAK_GROUND"
    assert sack["segments"][0]["end"]["x"] > sack["segments"][0]["start"]["x"]
    assert all(p["measuredTracking"] is False and p["playerIdentities"] is None for p in (complete, ground, sneak, sack))
    assert complete["segments"][0]["lateralBasis"] == "SCHEMATIC_LAYOUT_NOT_FITTED_ROUTE"
    assert geometry_for_play(event()) == complete
    split = geometry_for_play(event(targetYardline100=30., endYardline100=40.))
    assert [segment["kind"] for segment in split["segments"]] == ["PASS_MODELED_AIR_CURVE", "MODELED_YAC_GROUND"]
    air, yac = split["segments"]
    assert air["end"] == yac["start"] == {"x": 30., "y": .5}
    assert yac["end"]["x"] == 40.  # Negative YAC preserved, not forced to increase gain.
    assert all(segment["longitudinalBasis"] == "MODELED_AIR_YARDS_AND_NET_YARDS" for segment in split["segments"])
    with pytest.raises(PlayGeometryError, match="sack endpoint"):
        geometry_for_play(event("SACK", endYardline100=55.))


def test_turnover_return_uses_explicit_pre_play_frame_and_never_post_flip_reset_spot():
    play = event("INTERCEPTION", endYardline100=30., turnover=True, turnoverYardline100=30., returnEndYardline100=80.)
    play["stateAfter"].update(possession="AWAY", yardline100=20.)
    geometry = geometry_for_play(play)
    air, returned = geometry["segments"]
    assert air["end"]["x"] == returned["start"]["x"] == 30.
    assert returned["end"]["x"] == 80.  # NOT the new possession's20-yard frame.
    assert returned["possession"] == "AWAY" and returned["possessionDirection"] == "RIGHT"
    assert geometry["turnoverLocation"]["x"] == 30.
    missing = event("INTERCEPTION", endYardline100=None, turnover=True)
    assert geometry_for_play(missing)["segments"] == []
    with pytest.raises(PlayGeometryError, match="requires explicit"):
        geometry_for_play(event("INTERCEPTION", returnEndYardline100=80.))
    lost_sack = event("SACK", yardsGained=-5., endYardline100=55., turnover=True, fumble=True,
                      fumbleLost=True, turnoverYardline100=55., returnEndYardline100=75.)
    lost_sack["stateAfter"].update(possession="AWAY", yardline100=25.)
    split = geometry_for_play(lost_sack)
    assert [segment["kind"] for segment in split["segments"]] == ["SACK_NET_BACKWARD", "RETURN_GROUND"]
    assert split["segments"][0]["end"]["x"] == 65.  # Net loss, not forward recovery55.
    assert split["segments"][1]["start"]["x"] == 55.  # No invented bridge65→55.
    assert split["segments"][1]["end"]["x"] == 75.
    lost_sack["outcome"]["yardsGained"] = 0.
    zero = geometry_for_play(lost_sack)
    assert [segment["kind"] for segment in zero["segments"]] == ["RETURN_GROUND"]
    assert any(marker["kind"] == "SACK_NET_ZERO" for marker in zero["markers"])


def test_scoring_marker_does_not_rewrite_endpoint_and_safety_goal_is_correct():
    td = event("RUSH", endYardline100=12., scoringType="TD", homePointsAdded=6)
    td["stateAfter"].update(homeScore=6, phase="TRY", down=0, yardline100=15.)
    rendered = geometry_for_play(td)
    assert rendered["segments"][0]["end"]["x"] == 12.
    assert rendered["scoringEndpoint"]["point"]["x"] == 0.
    assert rendered["scoringEndpoint"]["basis"] == "SCORING_RULE_MARKER_NOT_TRACKED_ENDPOINT"
    safety = event("SACK", endYardline100=100., scoringType="SAFETY", awayPointsAdded=2)
    safety["stateAfter"].update(awayScore=2, phase="KICKOFF", down=0, yardline100=80.)
    assert geometry_for_play(safety)["scoringEndpoint"]["point"]["x"] == 100.
    downs = geometry_for_play(event("RUSH", turnoverDowns=True))
    assert any(marker["kind"] == "TURNOVER_ON_DOWNS" for marker in downs["markers"])


def test_incomplete_target_kick_arc_and_no_play_paths_never_add_missing_evidence():
    incomplete = geometry_for_play(event("PASS_INCOMPLETE", endYardline100=60.))
    assert incomplete["ballPathType"] == "INCOMPLETE_PASS_UNLOCATED" and incomplete["segments"] == []
    supplied = geometry_for_play(event("PASS_INCOMPLETE", endYardline100=60., targetYardline100=42.))
    assert supplied["segments"][0]["end"]["x"] == 42.
    punt = geometry_for_play(event("PUNT", endYardline100=10., turnoverYardline100=10., returnEndYardline100=25.))
    assert [segment["kind"] for segment in punt["segments"]] == ["PUNT_ARC", "RETURN_GROUND"]
    assert geometry_for_play(event("PENALTY", noPlay=True))["segments"] == []
    assert geometry_for_play(event("PERIOD_END"))["segments"] == []


class FixedFixtureModel:
    """Artificial transition fixture only, not a fitted or published NFL model."""
    def sample(self, state, rng, scenario):
        if state["phase"] == "KICKOFF":
            return {"type": "KICKOFF", "seconds": 0., "kick_distance": 65., "touchback": True}
        if state["phase"] == "TRY":
            return {"type": "EXTRA_POINT", "seconds": 0., "kick_success": True}
        return {"type": "RUSH", "seconds": 30., "yards": 5.}


def complete_fixture():
    from server.sports_nfl_m1.play_engine import simulate_play_game
    return simulate_play_game(FixedFixtureModel(), home_team="SEA", away_team="NE", season=2026, seed=41)


def test_complete_engine_fixture_geometry_reloads_and_rejects_hidden_state_or_path_changes():
    game = complete_fixture()
    restored = json.loads(json.dumps(game))
    report = validate_play_sequence(restored["plays"])
    assert report["scoreReconciliationExact"] and report["geometryReproductionExact"]
    assert report["stateDiscontinuities"] == 0
    damaged = copy.deepcopy(restored["plays"])
    damaged[1]["stateBefore"]["yardline100"] -= 1
    with pytest.raises(PlayGeometryError, match="continuity"):
        validate_play_sequence(damaged)
    damaged = copy.deepcopy(restored["plays"])
    damaged[0]["geometry"]["segments"][0]["end"]["x"] += 1
    with pytest.raises(PlayGeometryError, match="stored geometry"):
        validate_play_sequence(damaged)


def test_new_contract_envelope_schema_representatives_and_research_authority():
    game = complete_fixture()
    reps = [{**copy.deepcopy(game), "simulationIndex": index, "seed": 41, "label": f"Artificial fixture {index}"} for index in range(6)]
    artifact = {"schemaVersion": ARTIFACT_VERSION, "sport": "NFL", **AUTHORITY, "forecastId": "fixture", "eventId": "fixture-event",
        "homeTeam": {"abbreviation": "SEA"}, "awayTeam": {"abbreviation": "NE"}, "model": {"engineId": "ARTIFICIAL_FIXTURE_ONLY"},
        "scheduledStartUtc": "2026-09-10T00:00:00Z", "forecastCreatedUtc": "2026-09-09T00:00:00Z", "sourceCutoffUtc": None,
        "publishedAtUtc": "2026-09-09T00:00:00Z", "drawCount": 6, "seed": 41, "scenario": {"scenarioId": "BASE"},
        "simulatedGames": reps, "populationFinals": [{key: rep[key] for key in ("simulationIndex", "seed", "homeScore", "awayScore")} for rep in reps],
        "jointScoreDistribution": [{"homeScore": game["homeScore"], "awayScore": game["awayScore"], "probability": 1.}],
        "scoreMarginDistribution": [{"homeMinusAway": game["homeScore"]-game["awayScore"], "probability": 1.}],
        "totalScoreDistribution": [{"totalScore": game["homeScore"]+game["awayScore"], "probability": 1.}],
        "scoreSummary": {}, "limitations": ["Artificial transition fixture, not empirical performance evidence"]}
    assert load_contract()["schemaVersion"] == CONTRACT_VERSION
    report = validate_play_level_artifact(json.loads(json.dumps(artifact)))
    assert report["representatives"] == 6 and report["allRepresentativeStatesContinuous"]
    artifact["wageringAuthority"] = True
    with pytest.raises(PlayGeometryError, match="constant|authority"):
        validate_contract_schema(artifact)
    artifact["wageringAuthority"] = False
    artifact["simulatedGames"][0]["geometry"] = {"ignoredUnrelatedField": True}
    artifact["simulatedGames"][0]["plays"][0]["geometry"]["segments"][0]["start"]["y"] = 2.
    with pytest.raises(PlayGeometryError, match="bound"):
        validate_contract_schema(artifact)

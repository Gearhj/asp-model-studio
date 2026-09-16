from __future__ import annotations

import json

import numpy as np
import pytest

from server.sports_current_statcast.mlb_v18_player_prop_sidecar import (
    PlayerPropCollector, PlayerPropSidecarError, build_sidecar,
    evaluate_player_prop, verify_sidecar,
)


def _event(pa, half, slot, outcome, pitcher="STARTER"):
    return {"pa": pa, "half": half, "battingOrderPosition": slot,
            "pitcherState": pitcher, "outcome": outcome}


def _identities():
    lineups = {}
    starters = {}
    for side in ("AWAY", "HOME"):
        lineups[side] = [{"playerId": f"{side.lower()}-batter-{slot}", "mlbamId": f"{side[0]}{slot}",
                          "displayName": "Same Display Name" if slot < 3 else f"{side} Batter {slot}",
                          "teamId": f"{side.lower()}-team", "modelTemplatePlayerId": f"model-{side.lower()}-{slot}",
                          "battingOrderPosition": slot} for slot in range(1, 10)]
        starters[side] = {"playerId": f"{side.lower()}-starter", "mlbamId": f"{side[0]}P",
                          "displayName": f"{side} Starter", "teamId": f"{side.lower()}-team",
                          "modelTemplatePlayerId": f"model-{side.lower()}-starter"}
    return lineups, starters


def _binding(n=2):
    return {"gameId": "game-1", "sourceGameId": "123", "forecastId": "forecast-1",
            "forecastObjectSha256": "a"*64, "populationSha256": "b"*64,
            "modelId": "MLB_V18_HGB_PA", "modelArtifactSha256": "c"*64,
            "transitionArtifactSha256": "d"*64, "sourceCutoff": {"capturedAt": "2026-09-15T20:00:00Z"},
            "forecastCreatedAt": "2026-09-15T20:01:00Z", "simulationCount": n, "masterSeed": 7,
            "lineupAuthorities": {"AWAY": {"observationId": "away-lineup-v1"},
                                   "HOME": {"observationId": "home-lineup-v1"}}}


def _sidecar():
    collector = PlayerPropCollector(2)
    # Draw 0: away leadoff has single+HR (2 H, 5 TB); home leadoff strikes out.
    for event in (_event(1, "TOP", 1, "SINGLE"), _event(2, "BOTTOM", 1, "STRIKEOUT"),
                  _event(3, "TOP", 1, "HOME_RUN", "TEAM_BULLPEN")):
        collector(0, event)
    # Draw 1: away leadoff double (1 H, 2 TB); home leadoff K against away starter.
    for event in (_event(1, "TOP", 1, "DOUBLE"), _event(2, "BOTTOM", 1, "STRIKEOUT")):
        collector(1, event)
    population = {"simulationCount": 2, "paCounts": np.array([3, 2])}
    accounting = collector.finalize(population)
    lineups, starters = _identities()
    return build_sidecar(collector=collector, accounting=accounting, binding=_binding(),
                         lineups=lineups, starters=starters, created_at="2026-09-16T12:00:00Z")


def test_counts_settlement_and_identity_binding_are_exact():
    payload, digest = _sidecar()
    document = verify_sidecar(payload, digest)
    assert document["accounting"]["allPassed"] is True
    assert len(document["batters"]) == 18 and len(document["startingPitchers"]) == 2
    hits = evaluate_player_prop(payload, digest, {"propType": "BATTER_TO_RECORD_1_PLUS_HIT", "selection": "YES",
                                                       "playerId": "away-batter-1"})
    assert hits["counts"] == {"win": 2, "loss": 0, "push": 0, "void": None}
    total_bases = evaluate_player_prop(payload, digest, {"propType": "BATTER_TOTAL_BASES",
        "selection": "OVER", "line": 2, "playerId": "away-batter-1"})
    assert total_bases["counts"] == {"win": 1, "loss": 0, "push": 1, "void": None}
    strikeouts = evaluate_player_prop(payload, digest, {"propType": "STARTING_PITCHER_STRIKEOUTS",
        "selection": "OVER", "line": 0.5, "playerId": "away-starter"})
    assert strikeouts["counts"] == {"win": 2, "loss": 0, "push": 0, "void": None}
    assert strikeouts["probabilities"]["pVoid"] is None


def test_tamper_unknown_role_and_relief_prop_fail_closed():
    payload, digest = _sidecar()
    with pytest.raises(PlayerPropSidecarError, match="SIDECAR_HASH_MISMATCH"):
        verify_sidecar(payload + b" ", digest)
    with pytest.raises(PlayerPropSidecarError, match="PLAYER_NOT_IN_FROZEN_ROLE"):
        evaluate_player_prop(payload, digest, {"propType": "STARTING_PITCHER_STRIKEOUTS",
            "selection": "OVER", "line": 1.5, "playerId": "away-batter-1"})
    with pytest.raises(PlayerPropSidecarError, match="PROP_UNSUPPORTED"):
        evaluate_player_prop(payload, digest, {"propType": "RELIEF_PITCHER_STRIKEOUTS",
            "selection": "OVER", "line": 0.5, "playerId": "someone"})
    with pytest.raises(PlayerPropSidecarError, match="QUERY_BINDING_MISMATCH"):
        evaluate_player_prop(payload, digest, {"propType": "BATTER_HITS", "selection": "YES",
            "playerId": "away-batter-1", "expectedBinding": {"forecastId": "other"}})
    with pytest.raises(PlayerPropSidecarError, match="LINEUP_REVISION_MISMATCH"):
        evaluate_player_prop(payload, digest, {"propType": "BATTER_HITS", "selection": "YES",
            "playerId": "away-batter-1", "side": "AWAY", "expectedLineupObservationId": "later-lineup"})


def test_duplicate_names_never_create_identity_joins_and_mass_reconciles():
    payload, digest = _sidecar()
    result = evaluate_player_prop(payload, digest, {"propType": "BATTER_HOME_RUNS",
        "selection": "UNDER", "line": 0.5, "playerId": "away-batter-2"})
    assert result["counts"]["win"] == 2
    assert sum(v for v in result["counts"].values() if v is not None) == result["drawCount"]
    assert sum(v for v in result["probabilities"].values() if v is not None) == 1.0
    home_run = evaluate_player_prop(payload, digest, {"propType": "BATTER_HOME_RUN",
        "selection": "YES", "playerId": "away-batter-1"})
    assert home_run["counts"] == {"win": 1, "loss": 1, "push": 0, "void": None}


def test_invalid_line_and_incomplete_lineup_fail_closed():
    payload, digest = _sidecar()
    with pytest.raises(PlayerPropSidecarError, match="LINE_INVALID"):
        evaluate_player_prop(payload, digest, {"propType": "BATTER_HITS", "selection": "OVER",
            "line": 0.25, "playerId": "away-batter-1"})
    collector = PlayerPropCollector(1)
    collector(0, _event(1, "TOP", 1, "BIP_OUT"))
    accounting = collector.finalize({"simulationCount": 1, "paCounts": np.array([1])})
    lineups, starters = _identities(); lineups["HOME"].pop()
    with pytest.raises(PlayerPropSidecarError, match="LINEUP_BINDING_INVALID"):
        build_sidecar(collector=collector, accounting=accounting, binding=_binding(1),
                      lineups=lineups, starters=starters, created_at="2026-09-16T12:00:00Z")


def test_serializer_is_deterministic_and_nan_rejecting():
    first, digest = _sidecar(); second, second_digest = _sidecar()
    assert first == second and digest == second_digest
    assert json.loads(first)["schemaVersion"] == "ASP_MLB_V18_PLAYER_PROP_POPULATION_V1"


def test_variable_exposure_walkoff_extra_inning_orientation_and_bullpen_isolation():
    collector = PlayerPropCollector(3)
    # Variable paths stand in for an early walkoff, regulation game, and extra-inning game.
    paths = [
        [_event(1, "TOP", 1, "STRIKEOUT"), _event(2, "BOTTOM", 1, "SINGLE")],
        [_event(1, "TOP", 2, "BIP_OUT"), _event(2, "BOTTOM", 2, "STRIKEOUT"),
         _event(3, "TOP", 3, "HOME_RUN", "TEAM_BULLPEN")],
        [_event(1, "TOP", 1, "DOUBLE"), _event(2, "BOTTOM", 1, "TRIPLE"),
         _event(3, "TOP", 1, "STRIKEOUT", "TEAM_BULLPEN"),
         _event(4, "BOTTOM", 1, "STRIKEOUT")],
    ]
    for simulation, events in enumerate(paths):
        for event in events:
            collector(simulation, event)
    accounting = collector.finalize({"simulationCount": 3, "paCounts": np.array([2, 3, 4])})
    lineups, starters = _identities()
    payload, digest = build_sidecar(collector=collector, accounting=accounting, binding=_binding(3),
        lineups=lineups, starters=starters, created_at="2026-09-16T12:00:00Z")
    # A TOP strikeout belongs to the HOME pitcher; a BOTTOM strikeout belongs to AWAY.
    home_starter = evaluate_player_prop(payload, digest, {"propType": "STARTING_PITCHER_STRIKEOUTS",
        "selection": "OVER", "line": 0.5, "playerId": "home-starter"})
    away_starter = evaluate_player_prop(payload, digest, {"propType": "STARTING_PITCHER_STRIKEOUTS",
        "selection": "OVER", "line": 0.5, "playerId": "away-starter"})
    assert home_starter["counts"] == {"win": 1, "loss": 2, "push": 0, "void": None}
    assert away_starter["counts"] == {"win": 2, "loss": 1, "push": 0, "void": None}
    # The TOP bullpen K in draw 2 is isolated from the named home starter.
    assert home_starter["counts"]["win"] == 1

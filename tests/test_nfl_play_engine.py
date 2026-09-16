"""Focused football transitions; no database, provider or historical data access."""
import copy

import pytest

from server.sports_nfl_m1.play_engine import apply_play, simulate_play_game, verify_game, IllegalPlayState
from server.sports_nfl_m1.play_geometry import validate_play_sequence


def state(**overrides):
    return {"possession": "HOME", "quarter": 1, "clockSeconds": 900., "gameSecondsRemaining": 3600.,
            "down": 1, "distance": 10., "yardline100": 65., "homeScore": 0, "awayScore": 0,
            "phase": "SCRIMMAGE", **overrides}


def draw(kind="RUSH", **kwargs):
    return {"type": kind, "yards": 5., "seconds": 25., "fumble": False, "fumble_lost": False, **kwargs}


def test_series_sack_and_turnover_on_downs():
    after, out = apply_play(state(), draw(yards=12.), season=2026)
    assert (after["down"], after["distance"], after["yardline100"], out["firstDown"]) == (1, 10., 53., True)
    after, out = apply_play(state(down=3), draw("SACK", yards=-8.), season=2026)
    assert (after["down"], after["distance"], after["yardline100"]) == (4, 18., 73.)
    after, out = apply_play(state(down=4, distance=3.), draw(yards=2.), season=2026)
    assert out["turnoverDowns"] and after["possession"] == "AWAY" and after["yardline100"] == 37.


def test_touchdown_try_kickoff_and_missed_field_goal():
    after, out = apply_play(state(yardline100=4., distance=4.), draw(yards=9.), season=2026)
    assert after["homeScore"] == 6 and after["phase"] == "TRY" and out["endYardline100"] == 0.
    after, out = apply_play(after, draw("EXTRA_POINT", kick_success=True), season=2026)
    assert after["homeScore"] == 7 and out["seconds"] == 0 and after["phase"] == "KICKOFF"
    after, out = apply_play(after, draw("KICKOFF", kick_distance=70., touchback=True), season=2026)
    assert after["possession"] == "AWAY" and after["yardline100"] == 65.
    after, out = apply_play(state(yardline100=40.), draw("FIELD_GOAL", kick_success=False), season=2026)
    assert after["yardline100"] == 53. and out["seconds"] == 5 and after["homeScore"] == 0
    after, out = apply_play(state(phase="KICKOFF", down=0, distance=0.),
                            draw("KICKOFF", kick_distance=70., touchback=False, return_yards=15.), season=2026)
    assert out["returnEndYardline100"] == 10. and after["yardline100"] == 90.
    with pytest.raises(IllegalPlayState, match="did not reach"):
        apply_play(state(down=4), draw("PUNT", kick_distance=30., touchback=True), season=2026)


def test_interception_return_and_fumble_recovery_frames():
    after, out = apply_play(state(), draw("INTERCEPTION", air_yards=20., return_yards=15.), season=2026)
    assert out["turnoverYardline100"] == 45. and out["returnEndYardline100"] == 60.
    assert after["possession"] == "AWAY" and after["yardline100"] == 40.
    after, out = apply_play(state(), draw(fumble=True, fumble_lost=False, yards=4.), season=2026)
    assert after["possession"] == "HOME" and not out["turnover"] and after["down"] == 2
    after, out = apply_play(state(), draw(fumble=True, fumble_lost=True, yards=4., return_yards=8., turnover_yardline_100=61.), season=2026)
    assert out["turnover"] and out["returnEndYardline100"] == 69. and after["yardline100"] == 31.


def test_safety_and_presnap_penalty_half_distance():
    after, out = apply_play(state(yardline100=97.), draw("SACK", yards=-7.), season=2026)
    assert out["scoringType"] == "SAFETY" and after["awayScore"] == 2
    assert after["phase"] == "KICKOFF" and after["possession"] == "HOME" and after["yardline100"] == 80.
    after, out = apply_play(state(yardline100=98.), draw("PENALTY", penalty={"yards": 5., "no_play": True, "offense": True}), season=2026)
    assert after["yardline100"] == 99. and after["down"] == 1 and out["seconds"] == 0


class TouchdownFixture:
    def sample(self, s, rng, scenario):
        if s["phase"] == "KICKOFF": return draw("KICKOFF", seconds=0., kick_distance=70., touchback=True)
        if s["phase"] == "TRY": return draw("EXTRA_POINT", seconds=0., kick_success=True)
        return draw(yards=100., seconds=60. if s["quarter"] == 5 else 900.)


def test_deterministic_full_game_and_both_overtime_possessions():
    model = TouchdownFixture()
    first = simulate_play_game(model, home_team="H", away_team="A", season=2026, seed=42)
    assert first == simulate_play_game(model, home_team="H", away_team="A", season=2026, seed=42)
    assert first["reachedOvertime"] and sorted([first["homeScore"], first["awayScore"]]) == [21, 27]
    ot_scrimmage = [p for p in first["plays"] if p["stateBefore"]["quarter"] == 5 and p["playType"] == "RUSH"]
    assert len(ot_scrimmage) == 3 and len({p["stateBefore"]["possession"] for p in ot_scrimmage}) == 2
    assert first["plays"][-1]["stateAfter"]["clockSeconds"] > 0
    assert verify_game(first)["impossibleStateCount"] == 0
    validate_play_sequence(first["plays"])
    old = simulate_play_game(model, home_team="H", away_team="A", season=2024, seed=42)
    assert sorted([old["homeScore"], old["awayScore"]]) == [14, 20]


def test_reconciliation_rejects_corrupt_state_and_sealed_target():
    model = TouchdownFixture()
    game = simulate_play_game(model, home_team="H", away_team="A", season=2026, seed=4, include_geometry=False)
    corrupt = copy.deepcopy(game)
    corrupt["plays"][1]["stateAfter"]["homeScore"] += 1
    with pytest.raises(IllegalPlayState): verify_game(corrupt)
    with pytest.raises(ValueError, match="sealed"):
        simulate_play_game(model, home_team="H", away_team="A", season=2025, seed=4)

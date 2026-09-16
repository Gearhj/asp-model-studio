"""Small synthetic mechanics checks, without any estimator or transition fits."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from server.sports_phase5 import base_out_transition as bt
from server.sports_current_statcast.mlb_starter_survival_models import PREGAME_FIELDS
from server.sports_current_statcast.mlb_v18_whole_game_challenger import simulate_prospective_game
from server.sports_current_statcast.mlb_starter_duration_paired_simulation import (
    CHALLENGER, REFERENCE, POPULATION_ARRAYS, PairedSimulationError,
    _duration_lookup, simulate_paired_game, simulate_research_arm,
)


class FixedProvider:
    def probabilities(self, **state):
        p = np.zeros((len(state["top"]), 8))
        p[:, 2] = np.where(state["bullpen"], 0.12, 0.06)
        p[:, 0] = 0.22
        p[:, 6] = 1-p[:, 2]-p[:, 0]
        return p


class FixedHazard:
    model_id = "HGB_PREGAME"
    feature_order = PREGAME_FIELDS
    temperature = 1.0
    calls = 0

    def predict_proba(self, frame, calibrated=True):
        self.calls += 1
        assert calibrated and frame.bf.min() == 1
        assert tuple(frame.columns) == PREGAME_FIELDS
        # Removal conditional on not GAME_END is exactly 1/3, not .30.
        return np.tile([0.6, 0.3, 0.1], (len(frame), 1))


def transition_fixture():
    cells = {f"{outcome}|{outs}|{base}": {(1, base if outs < 2 else 0, 0): 1}
             for outcome in bt.PA_CLASSES for outs in range(3) for base in range(8)}
    return bt.TransitionModel(alpha=0.0, min_cell=1, cells=cells,
        by_outcome_outs={}, by_outcome={}, seasons=())


def inputs(home):
    return {"homePitcher": home, "calendarMonth": 9, "priorStartCount": 3,
        "priorStartBfMean": 22.0, "daysRest": 5, "historyMissing": 0}


def common():
    return dict(game_id="SYNTHETIC_PAIRED_MECHANICS_ONLY", provider=FixedProvider(),
        transition_model=transition_fixture(), n_sims=64, master_seed=20260911, regulation=9, trace_count=2)


def test_reference_is_exact_frozen_loop_and_outs_bf_accounting():
    args = common()
    expected = simulate_prospective_game(**args)
    actual = simulate_research_arm(**args, arm=REFERENCE)
    for name in ("homeRuns", "awayRuns", "innings", "paCounts"):
        np.testing.assert_array_equal(actual[name], expected[name])
    assert actual["traces"] == expected["traces"]
    assert actual["homeWinProbability"] == expected["homeWinProbability"]
    for side in ("home", "away"):
        assert (actual[side+"StarterBf"] >= 1).all()
        assert (actual[side+"StarterOuts"] >= 0).all()
        assert (actual[side+"RelieverBf"] >= 0).all()
    np.testing.assert_array_equal(actual["homeStarterBf"]+actual["awayStarterBf"]+
        actual["homeRelieverBf"]+actual["awayRelieverBf"], actual["paCounts"])


def test_paired_repeatability_conditional_hazard_no_bf_zero_hook_or_reentry():
    model = FixedHazard()
    lookup, evidence = _duration_lookup(model, inputs(1), inputs(0))
    assert model.calls == 1 and evidence["rowsScored"] == 400
    np.testing.assert_array_equal(lookup[:, 0], [0, 0])
    np.testing.assert_allclose(lookup[:, 1:], 1/3, atol=1e-15)
    args = {**common(), "duration_model": model, "home_duration_inputs": inputs(1), "away_duration_inputs": inputs(0)}
    first, second = simulate_paired_game(**args), simulate_paired_game(**args)
    for arm in ("reference", "challenger"):
        for name in POPULATION_ARRAYS:
            np.testing.assert_array_equal(first[arm][name], second[arm][name])
        assert first[arm]["traces"] == second[arm]["traces"]
        assert first[arm]["homeWinProbability"]+first[arm]["awayWinProbability"] == 1
        assert sum(row["count"] for row in first[arm]["jointScores"]) == 64
        assert first[arm]["bfZeroHookCount"] == 0
        for trace in first[arm]["traces"]:
            for half in ("TOP", "BOTTOM"):
                states = [e for e in trace if e["half"] == half]
                assert sum(e["pitchingChange"] for e in states) <= 1
                bullpen_started = False
                for event in states:
                    if event["pitcherState"] == "TEAM_BULLPEN":
                        bullpen_started = True
                    if bullpen_started:
                        assert event["pitcherState"] == "TEAM_BULLPEN"


def test_expired_deadline_and_orientation_fail_before_rollout():
    model = FixedHazard()
    with pytest.raises(PairedSimulationError, match="DEADLINE_EXPIRED"):
        simulate_paired_game(**common(), duration_model=model,
            home_duration_inputs=inputs(1), away_duration_inputs=inputs(0),
            deadline_utc=datetime.now(timezone.utc)-timedelta(seconds=1))
    assert model.calls == 0
    with pytest.raises(PairedSimulationError, match="ORIENTATION"):
        _duration_lookup(model, inputs(0), inputs(1))

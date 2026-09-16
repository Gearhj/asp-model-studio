"""Hermetic Phase 7B6 coverage for the whole-game probability-provider seam.

No governed data, fitted PA model, market logic, or study orchestration is used here.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from server.sports_phase5 import base_out_transition as bt
from server.sports_phase5 import whole_game_monte_carlo as mc
from server.sports_phase5.game_initialization import RngLineage


FIXED = np.array([0.225, 0.085, 0.033, 0.140, 0.045, 0.005, 0.440, 0.027])
FIXED = FIXED / FIXED.sum()


def _tiny_sampler() -> mc.FastTransitionSampler:
    records = [
        {
            "pa_outcome": outcome,
            "outs_before": 0,
            "base_mask_before": 0,
            "outs_after": 1,
            "base_mask_after": 0,
            "runs_scored": 0,
            "season": 2021,
        }
        for outcome in bt.PA_CLASSES
    ]
    return mc.FastTransitionSampler(
        bt.fit(records, alpha=0.5, min_cell=1, seasons=(2021,))
    )


def _zero_contribs() -> mc.GameContribs:
    zeros = np.zeros((mc.MAX_TEAM_PA, 8), dtype=np.float64)
    return mc.GameContribs(
        away_batter=zeros.copy(),
        away_pitcher=zeros.copy(),
        home_batter=zeros.copy(),
        home_pitcher=zeros.copy(),
        regulation=9,
    )


def _simulate(*, seed: int = 7, n_sims: int = 96, **mode):
    return mc.simulate_game(
        game_id="g",
        contribs=_zero_contribs(),
        transition_sampler=_tiny_sampler(),
        rng_lineage=RngLineage(seed, "g"),
        n_sims=n_sims,
        **mode,
    )


def _legacy_result_sha(result: mc.GameSimResult) -> str:
    digest = hashlib.sha256()
    for values in (
        result.away_runs,
        result.home_runs,
        result.innings,
        result.pa_counts,
        result.home_win,
    ):
        digest.update(np.ascontiguousarray(values).tobytes())
    return digest.hexdigest()


class _ZeroFold:
    def context_base_logits(self, inning, top_bottom, outs, base, score_diff):
        return np.zeros((len(inning), 8), dtype=np.float64)


def test_legacy_fixed_and_fold_rng_outputs_are_byte_identical():
    fixed = _simulate(
        seed=7,
        n_sims=300,
        fold=None,
        fixed_probs=FIXED,
    )
    folded = _simulate(seed=7, n_sims=300, fold=_ZeroFold())

    assert _legacy_result_sha(fixed) == (
        "d25d8cbe34f7ff151986f78c05c0799e18255362bbc4abe89376532feedc594d"
    )
    assert _legacy_result_sha(folded) == (
        "c624497e842b92f4d3af7fbd15db086ae0f561981f87356c1e1e9dcc2cb81094"
    )


def test_provider_matches_fixed_mode_and_receives_simulated_state():
    calls: list[mc.SimulatedPAStateBatch] = []

    def provider(state: mc.SimulatedPAStateBatch) -> np.ndarray:
        calls.append(state)
        return np.repeat(FIXED[None, :], len(state.inning), axis=0)

    fixed = _simulate(fold=None, fixed_probs=FIXED)
    supplied = _simulate(fold=None, probability_provider=provider)

    for field_name in (
        "away_runs",
        "home_runs",
        "innings",
        "pa_counts",
        "home_win",
        "first_five_away_runs",
        "first_five_home_runs",
    ):
        assert np.array_equal(getattr(supplied, field_name), getattr(fixed, field_name))

    assert calls
    assert np.all(calls[0].inning == 1)
    assert np.all(calls[0].is_top)
    assert np.all(calls[0].batting_team_pa_ordinal == 0)
    assert any(np.any(~state.is_top) for state in calls)
    assert any(np.max(state.batting_team_pa_ordinal) > 0 for state in calls)
    for state in calls:
        for values in (
            state.inning,
            state.is_top,
            state.outs_before,
            state.base_mask_before,
            state.away_score_before,
            state.home_score_before,
            state.batting_score_diff_before,
            state.batting_team_pa_ordinal,
            state.active,
        ):
            assert values.shape == (supplied.n_sims,)
            assert not values.flags.writeable


@pytest.mark.parametrize(
    ("provider", "message"),
    [
        (
            lambda state: np.full((len(state.inning), 7), 1.0 / 7.0),
            "returned shape",
        ),
        (
            lambda state: np.full((len(state.inning), 8), np.nan),
            "non-finite",
        ),
        (
            lambda state: np.tile(
                np.array([-0.1, 1.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
                (len(state.inning), 1),
            ),
            "negative",
        ),
        (
            lambda state: np.full((len(state.inning), 8), 0.1),
            "sum to one",
        ),
    ],
)
def test_provider_probability_matrices_fail_closed(provider, message):
    with pytest.raises(mc.MonteCarloError, match=message):
        _simulate(n_sims=8, fold=None, probability_provider=provider)


def test_probability_mode_is_exactly_one():
    provider = lambda state: np.repeat(FIXED[None, :], len(state.inning), axis=0)
    common = {
        "game_id": "phase7b6-mode",
        "contribs": _zero_contribs(),
        "transition_sampler": _tiny_sampler(),
        "rng_lineage": RngLineage(3, "phase7b6-mode"),
        "n_sims": 8,
    }

    with pytest.raises(mc.MonteCarloError, match="exactly one"):
        mc.simulate_game(fold=None, **common)
    with pytest.raises(mc.MonteCarloError, match="exactly one"):
        mc.simulate_game(
            fold=None,
            fixed_probs=FIXED,
            probability_provider=provider,
            **common,
        )
    with pytest.raises(mc.MonteCarloError, match="exactly one"):
        mc.simulate_game(fold=_ZeroFold(), fixed_probs=FIXED, **common)
    with pytest.raises(mc.MonteCarloError, match="exactly one"):
        mc.simulate_game(
            fold=_ZeroFold(), probability_provider=provider, **common
        )


def test_first_five_snapshots_and_summary_are_complete():
    result = _simulate(seed=11, n_sims=128, fold=None, fixed_probs=FIXED)

    assert result.first_five_away_runs.shape == (128,)
    assert result.first_five_home_runs.shape == (128,)
    assert np.all(result.first_five_complete)
    assert np.all(result.first_five_away_runs <= result.away_runs)
    assert np.all(result.first_five_home_runs <= result.home_runs)

    summary = result.summary()
    assert summary["firstFiveCompletedSimulations"] == 128
    assert summary["firstFiveCompletionRate"] == 1.0
    assert (
        summary["firstFiveHomeWinProb"]
        + summary["firstFiveAwayWinProb"]
        + summary["firstFiveTieProb"]
        == pytest.approx(1.0)
    )
    assert set(summary["firstFiveTotalQuantiles"]) == {
        "p5",
        "p10",
        "p25",
        "p50",
        "p75",
        "p90",
        "p95",
    }


def test_legacy_game_result_constructor_remains_valid_without_f5_arrays():
    result = mc.GameSimResult(
        game_id="legacy",
        n_sims=2,
        away_runs=np.array([1, 2]),
        home_runs=np.array([2, 1]),
        innings=np.array([9, 9]),
        pa_counts=np.array([70, 71]),
        home_win=np.array([True, False]),
        nonterminated=0,
        illegal_states=0,
    )

    summary = result.summary()
    assert summary["firstFiveCompletedSimulations"] == 0
    assert summary["firstFiveCompletionRate"] == 0.0
    assert summary["firstFiveHomeWinProb"] is None

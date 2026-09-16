"""Focused synthetic checks; no historical or assessment payloads are opened."""
from copy import deepcopy

import numpy as np
import pytest

from server.sports_nfl_m1.distributions import (
    CommonRandomNumbers, PairedResidualAuthority, ScoreDistributionError,
    make_common_random_numbers, simulate_joint_scores,
)
from server.sports_nfl_m1.qb_context_residual_sampler import (
    authority_from_config, context_weights, fit_conditioning, game_seed, simulate_comparison,
)


def _bank(count=200):
    index = np.arange(count)
    return PairedResidualAuthority.fit(
        actual_home=10+index % 31, actual_away=8+(index*7) % 29,
        predicted_home=np.full(count, 20), predicted_away=np.full(count, 18),
        row_ids=[f"donor-{value}" for value in index],
        row_dates=["2022-12-01"]*count, training_end="2022-12-01")


def _config():
    authority = _bank()
    contexts = ["STABLE|STABLE"]*80+["MIXED|STABLE"]*80+["UNKNOWN|STABLE"]*40
    config = fit_conditioning(residual_authority=authority, donor_contexts=contexts,
                              declaration_sha256="a"*64)
    return authority, config


def _compare(authority, config, contexts=None, ids=None):
    contexts = contexts or ["STABLE|STABLE", "UNKNOWN|STABLE", "MIXED|MIXED"]
    ids = ids or [f"target-{index}" for index in range(len(contexts))]
    return simulate_comparison(predicted_home_mean=[3.2]*len(contexts),
        predicted_away_mean=[4.7]*len(contexts), target_contexts=contexts,
        target_game_ids=ids, target_game_dates=["2023-09-10"]*len(contexts),
        residual_authority=authority, fitted_config=config, draws=1000, seed=731001)


def test_shrinkage_support_missing_and_effective_support_are_declared():
    _, config = _config()
    weights, meta = context_weights(config["donorContexts"], "STABLE|STABLE")
    alpha = 80/180
    expected = np.full(200, (1-alpha)/200)
    expected[:80] += alpha/80
    assert weights == pytest.approx(expected)
    assert weights.sum() == pytest.approx(1)
    assert meta["effectiveSampleSize"] == pytest.approx(1/(expected@expected))
    assert meta["supportedConditioning"]
    for context, reason in (("UNKNOWN|STABLE", "UNKNOWN_CONTEXT"),
                            ("MIXED|MIXED", "INSUFFICIENT_LOCAL_DONORS")):
        fallback, status = context_weights(config["donorContexts"], context)
        assert np.array_equal(fallback, np.full(200, 1/200))
        assert status["status"].endswith(reason)
    _, low_ess = context_weights(["STABLE|STABLE"]*40+["MIXED|STABLE"]*10, "STABLE|STABLE")
    assert low_ess["status"] == "POOLED_FALLBACK_INSUFFICIENT_EFFECTIVE_SUPPORT"


def test_complete_oriented_donors_reuse_existing_transform_rounding_and_ties():
    authority, config = _config()
    before = authority.home.copy(), authority.away.copy()
    compared = _compare(authority, config)
    for index, context in enumerate(("STABLE|STABLE", "UNKNOWN|STABLE", "MIXED|MIXED")):
        randoms = make_common_random_numbers(n_games=1, draws=1000,
                                            seed=game_seed(f"target-{index}"))
        original_u = randoms.residual_uniform.copy()
        direct = simulate_joint_scores(predicted_home_mean=[3.2], predicted_away_mean=[4.7],
            residual_authority=authority, draws=1000, common_random_numbers=randoms)
        assert np.array_equal(direct.home[0], compared.baseline.home[index])
        assert np.array_equal(direct.away[0], compared.baseline.away[index])
        if index == 0:
            weights, _ = context_weights(config["donorContexts"], context)
            cdf = np.cumsum(weights); cdf[-1] = 1
            donor = np.searchsorted(cdf, randoms.residual_uniform, side="right")
            h = np.maximum(0, 3.2+authority.home[donor])
            a = np.maximum(0, 4.7+authority.away[donor])
            expected_h = np.floor(h)+(randoms.home_round_uniform < h-np.floor(h))
            expected_a = np.floor(a)+(randoms.away_round_uniform < a-np.floor(a))
            assert np.array_equal(expected_h[0], compared.candidate.home[index])
            assert np.array_equal(expected_a[0], compared.candidate.away[index])
        else:
            assert np.array_equal(direct.home[0], compared.candidate.home[index])
            assert np.array_equal(direct.away[0], compared.candidate.away[index])
            assert compared.diagnostics[index]["exactPooledNumericalFallback"]
        assert np.array_equal(original_u, randoms.residual_uniform)
    assert np.array_equal(before[0], authority.home)
    assert np.array_equal(before[1], authority.away)
    for arm in (compared.baseline, compared.candidate):
        assert (arm.home >= 0).all() and (arm.away >= 0).all()
        assert (arm.home == arm.away).any()
    assert compared.diagnostics[0]["candidate"]["tieProbability"] > 0


def test_game_identity_stream_and_complete_config_roundtrip():
    authority, config = _config()
    reloaded = authority_from_config(config)
    assert np.array_equal(authority.home, reloaded.home)
    assert np.array_equal(authority.away, reloaded.away)
    assert reloaded.row_ids == authority.row_ids
    first = _compare(authority, config)
    reordered = _compare(reloaded, config, ["MIXED|MIXED", "STABLE|STABLE", "UNKNOWN|STABLE"],
                         ["target-2", "target-0", "target-1"])
    assert np.array_equal(first.baseline.home[[2, 0, 1]], reordered.baseline.home)
    assert np.array_equal(first.candidate.home[[2, 0, 1]], reordered.candidate.home)
    assert np.array_equal(first.candidate.away[[2, 0, 1]], reordered.candidate.away)
    corrupted = deepcopy(config); corrupted["pairedResidualAuthority"]["home"][0] += 1
    with pytest.raises(ScoreDistributionError, match="identity differs"):
        authority_from_config(corrupted)


def test_conditional_selection_is_not_recentred_and_reports_mc_precision():
    authority, config = _config()
    compared = _compare(authority, config)
    first = compared.diagnostics[0]
    w, _ = context_weights(config["donorContexts"], "STABLE|STABLE")
    assert first["weightedResidualMeanHome"] == pytest.approx(w@authority.home)
    assert abs(first["weightedResidualMeanHome"]) > 0.01
    delta = compared.candidate.home[0].astype(float)-compared.baseline.home[0]
    reported = first["pairedSimulationDifference"]["homeMean"]
    assert reported["candidateMinusControl"] == pytest.approx(delta.mean())
    assert reported["monteCarloStandardError"] == pytest.approx(delta.std(ddof=1)/np.sqrt(1000))
    for side in ("baseline", "candidate"):
        summary = first[side]
        assert sum(summary[name] for name in ("homeWinProbability", "awayWinProbability", "tieProbability")) == pytest.approx(1)


def test_misalignment_chronology_and_donor_overlap_fail_closed():
    authority, config = _config()
    with pytest.raises(ScoreDistributionError, match="aligned declared"):
        context_weights(["STABLE|STABLE"], "HOME_UNKNOWN")
    with pytest.raises(ScoreDistributionError, match="separate from donors"):
        _compare(authority, config, ["STABLE|STABLE"], ["donor-1"])
    with pytest.raises(ScoreDistributionError, match="strictly after"):
        simulate_comparison(predicted_home_mean=[20], predicted_away_mean=[20],
            target_contexts=["STABLE|STABLE"], target_game_ids=["new"],
            target_game_dates=["2022-12-01"], residual_authority=authority,
            fitted_config=config, draws=100)
    with pytest.raises(ScoreDistributionError, match="aligned declared"):
        fit_conditioning(residual_authority=authority, donor_contexts=["STABLE|STABLE"],
                         declaration_sha256="a"*64)

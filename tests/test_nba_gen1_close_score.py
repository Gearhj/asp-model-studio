"""Focused support/count checks, separate from observed-game evidence."""
import copy

import numpy as np
import pytest

from server.sports_nba_gen1.close_score import (
    _apply_with_uniforms, canonical_population, fit_kernel, transform,
)


def kernel():
    return fit_kernel(
        [240000, 160000, 160000, 160000, 160000, 160000, 160000, 160000],
        [30, 25, 40, 35, 40, 45, 50, 35], 400,
    )


def population():
    draws = [[100 + magnitude, 100] for magnitude in range(1, 13)]
    draws += [[100, 100 + magnitude] for magnitude in range(1, 13)]
    return canonical_population(np.repeat(draws, 25, axis=0))


def test_conditional_cdf_transport_has_exact_probability_mass():
    fitted = kernel()
    matrix = np.asarray(fitted["transitionProbabilities"])
    assert fitted["ready"] and fitted["pseudocounts"] == 0
    np.testing.assert_allclose(matrix.sum(axis=1), 1, atol=1e-14)
    for group in fitted["parities"].values():
        indices = np.asarray(group["absoluteMargins"]) - 1
        p, q = group["sourceConditionalProbabilities"], group["targetConditionalProbabilities"]
        np.testing.assert_allclose(np.asarray(p) @ matrix[np.ix_(indices, indices)], q, atol=1e-14)
    assert not matrix[0::2, 1::2].any() and not matrix[1::2, 0::2].any()


def test_full_population_winners_totals_outer_margins_and_input_preserved():
    original = population()
    before = original.copy()
    result, summary = transform(original, "synthetic-game", kernel())
    np.testing.assert_array_equal(original, before)
    np.testing.assert_array_equal(result.sum(axis=1), original.sum(axis=1))
    np.testing.assert_array_equal(result[:, 0] > result[:, 1], original[:, 0] > original[:, 1])
    outer = np.abs(original[:, 0] - original[:, 1]) > 8
    np.testing.assert_array_equal(result[outer], original[outer])
    assert len(result) == len(original) and (result >= 0).all()
    assert (result[:, 0] != result[:, 1]).all() and summary["changedDrawCount"] > 0
    assert summary["maximumAbsoluteTeamScoreChange"] <= 3


def test_determinism_and_canonical_multiset_preservation():
    original = population()
    shuffled = original[::-1]
    np.testing.assert_array_equal(canonical_population(shuffled), original)
    first, summary = transform(original, "stable-game", kernel())
    second, again = transform(original, "stable-game", kernel())
    np.testing.assert_array_equal(first, second)
    assert summary == again and summary["originalDrawOrderClaimed"] is False
    with pytest.raises(ValueError, match="canonical"):
        transform(shuffled, "stable-game", kernel())


def test_whole_population_fallback_requires_both_prerequisites():
    original = population()
    for fitted in (
        fit_kernel([100] * 8, [10] * 8, 199),
        fit_kernel([100] * 8, [10, 1, 10, 1, 10, 1, 10, 1], 200),
    ):
        assert not fitted["ready"]
        result, summary = transform(original, "fallback", fitted)
        np.testing.assert_array_equal(result, original)
        assert summary["uniformsGenerated"] == 0 and summary["exactWholePopulationFallback"]


def test_low_total_proposal_falls_back_per_draw_without_negative_scores():
    original = np.array([[1, 0], [0, 1], [101, 100]])
    result, summary = _apply_with_uniforms(original, kernel(), np.full(3, 0.99))
    np.testing.assert_array_equal(result[:2], original[:2])
    assert summary["nonnegativeSupportFallbackDrawCount"] == 2
    assert result[2, 0] > original[2, 0] and result[2].sum() == original[2].sum()


def test_team_swap_is_symmetric_with_matched_uniforms():
    original = population()
    uniforms = np.linspace(0, 0.999, len(original))
    direct, _ = _apply_with_uniforms(original, kernel(), uniforms)
    mirrored, _ = _apply_with_uniforms(original[:, ::-1], kernel(), uniforms)
    np.testing.assert_array_equal(direct[:, ::-1], mirrored)


def test_missing_source_bin_identity_and_kernel_binding():
    fitted = fit_kernel([0, 100, 100, 100, 100, 100, 100, 100], [20] * 8, 200)
    original = np.array([[101, 100]])
    result, summary = transform(original, "unseen-source", fitted)
    np.testing.assert_array_equal(result, original)
    assert summary["unseenSourceBinIdentityDrawCount"] == 1
    corrupted = copy.deepcopy(fitted)
    corrupted["transitionProbabilities"][0][0] = 0.5
    with pytest.raises(ValueError, match="identity"):
        transform(original, "unseen-source", corrupted)


def test_invalid_inputs_fail_before_transformation():
    with pytest.raises(ValueError, match="integer counts"):
        fit_kernel([1.5] * 8, [1] * 8, 200)
    with pytest.raises(ValueError, match="exceed"):
        fit_kernel([100] * 8, [100] * 8, 200)
    with pytest.raises(ValueError, match="untied"):
        canonical_population([[100, 100]])
    with pytest.raises(ValueError, match="integer scores"):
        canonical_population([[100.0, 101.0]])

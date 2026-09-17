import numpy as np
import pytest

from server.sports_current_statcast.mlb_v19_structural_defense import (
    BIP_INDICES, DefenseConfig, UNCHANGED_INDICES, apply_defense_shift,
    defense_log_odds_shift, fit_state,
)


def probabilities():
    return np.array([
        [.20, .08, .04, .18, .06, .01, .41, .02],
        [.25, .09, .05, .15, .05, .01, .38, .02],
    ], dtype=np.float64)


def test_shift_preserves_mass_and_every_non_bip_probability():
    baseline = probabilities()
    changed = apply_defense_shift(baseline, [.2, -.2])
    assert np.array_equal(changed[:, UNCHANGED_INDICES], baseline[:, UNCHANGED_INDICES])
    assert np.allclose(changed[:, BIP_INDICES].sum(axis=1), baseline[:, BIP_INDICES].sum(axis=1), atol=1e-12, rtol=0)
    assert np.allclose(changed.sum(axis=1), 1.0, atol=1e-12, rtol=0)
    assert changed[0, 6] < baseline[0, 6]
    assert changed[1, 6] > baseline[1, 6]


def test_zero_shift_is_exact_and_deterministic():
    baseline = probabilities()
    first = apply_defense_shift(baseline, [0.0, 0.0])
    second = apply_defense_shift(baseline, [0.0, 0.0])
    assert np.array_equal(first, baseline)
    assert np.array_equal(first, second)


def test_shrinkage_and_cap_fail_closed():
    state = fit_state([("A", 3)] * 8 + [("A", 6)] * 2 + [("B", 3)] * 2 + [("B", 6)] * 8)
    loose = defense_log_odds_shift(state, "A", DefenseConfig(1.0, .15))
    shrunk = defense_log_odds_shift(state, "A", DefenseConfig(1000.0, .15))
    unknown = defense_log_odds_shift(state, "UNKNOWN", DefenseConfig(100.0, .15))
    assert loose == pytest.approx(.15)
    assert 0 < shrunk < loose
    assert unknown == pytest.approx(0.0)
    with pytest.raises(ValueError):
        DefenseConfig(0)


def test_invalid_probability_contract_is_rejected():
    with pytest.raises(ValueError):
        apply_defense_shift(np.ones((2, 7)) / 7, [0, 0])
    bad = probabilities()
    bad[0, 0] += .01
    with pytest.raises(ValueError):
        apply_defense_shift(bad, [0, 0])

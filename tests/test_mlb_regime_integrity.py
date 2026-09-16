"""Focused seal and game-identity protections for the bounded MLB study."""
import numpy as np
import pytest


def test_simulation_rejects_sealed_dates_before_execution():
    import pandas as pd
    from server.sports_current_statcast.mlb_regime_simulation import compare_paired_game_mechanics, RegimeSimulationError
    frame = pd.DataFrame({'canonicalPaId': ['a', 'b'], 'canonicalGameId': ['g', 'g'],
                          'game_date': ['2026-08-14'] * 2, 'context_top_bottom': [0, 1]})
    probabilities = np.full((2, 8), .125)
    with pytest.raises(RegimeSimulationError, match='sealed'):
        compare_paired_game_mechanics(frame, probabilities, probabilities, transition_model=None,
                                     transition_training_end='2025-07-27', transition_model_sha256='a' * 64)


def test_unsupported_corrections_preserve_global_and_deployed_gradient():
    from server.sports_current_statcast.mlb_regime_models import (
        OffsetCorrection, SoftGate, simplex_correction, bounded_log_loss_gradient,
    )
    rng = np.random.default_rng(18)
    base = rng.dirichlet(np.ones(8) * 4, size=6)
    empty_basis = np.zeros((6, 2))
    offset = OffsetCorrection(rng.normal(size=(2, 8)), {})
    assert np.array_equal(offset.predict(empty_basis, base), base)
    gate = SoftGate(np.zeros((3, 1)), {})
    branches = np.broadcast_to(base[:, None, :], (6, 1, 8)).copy()
    assert np.array_equal(gate.predict(empty_basis, np.zeros((6, 1)), branches, base), base)
    delta = rng.normal(scale=.1, size=base.shape)
    predicted = simplex_correction(base, delta)
    assert (predicted >= 0).all()
    assert np.allclose(predicted.sum(axis=1), 1., atol=1e-14)
    assert np.max(np.abs(predicted-base)) <= .03 + 1e-14
    y = np.arange(6)
    value, gradient = bounded_log_loss_gradient(base, delta, y)
    assert value == pytest.approx(-np.log(predicted[np.arange(6), y]).mean(), abs=1e-14)
    epsilon = 1e-7
    for row, column in [(0, 0), (2, 5), (5, 7)]:
        step = np.zeros_like(delta)
        step[row, column] = epsilon
        upper = bounded_log_loss_gradient(base, delta+step, y)[0]
        lower = bounded_log_loss_gradient(base, delta-step, y)[0]
        assert (upper-lower)/(2*epsilon) == pytest.approx(gradient[row, column]/len(y), abs=1e-7)

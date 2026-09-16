"""Pure prospective hook boundary for a future *research* simulator comparison.

This is not wired into frozen V18 or its publisher. The game's existing terminal
process owns game end. Conditional on an actual next pitching opportunity, only
the continuation/removal probabilities are renormalized; no second game-end draw
is sampled. Existing bullpen limitations are not solved by this adapter.
"""
import numpy as np

from .mlb_starter_survival_models import PREGAME_FIELDS


def removal_probability(model, features, *, game_active, starter_active):
    if set(model.feature_order) - set(PREGAME_FIELDS):
        raise ValueError("Only the predeclared deployable pregame subset may enter this research adapter")
    game_active, starter_active = np.asarray(game_active, bool), np.asarray(starter_active, bool)
    if len(game_active) != len(features) or len(starter_active) != len(features):
        raise ValueError("Game/starter state shape mismatch")
    # The source study only supports announced starters after >=1 recorded BF.
    eligible = game_active & starter_active & features.bf.to_numpy().astype(float).__ge__(1)
    probability = np.zeros(len(features))
    if eligible.any():
        p = model.predict_proba(features.loc[eligible], calibrated=True)
        denominator = p[:, 0] + p[:, 1]
        if not np.isfinite(p).all() or (denominator <= 0).any():
            raise ValueError("No supported next-opportunity probability")
        probability[eligible] = p[:, 1] / denominator
    return probability


def apply_removal_draws(starter_active, game_active, probabilities, uniform_draws):
    active, games = np.asarray(starter_active, bool), np.asarray(game_active, bool)
    probabilities, draws = np.asarray(probabilities, float), np.asarray(uniform_draws, float)
    if not (active.shape == games.shape == probabilities.shape == draws.shape):
        raise ValueError("Draw/state shape mismatch")
    if not np.isfinite(probabilities).all() or not np.isfinite(draws).all() or (probabilities < 0).any() or (probabilities > 1).any() or (draws < 0).any() or (draws >= 1).any():
        raise ValueError("Illegal probability/draw")
    removed = active & games & (draws < probabilities)
    return active & ~removed

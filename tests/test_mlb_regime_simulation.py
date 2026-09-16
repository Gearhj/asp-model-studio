from pathlib import Path

import numpy as np
import pandas as pd

from server.sports_current_statcast.mlb_regime_simulation import (
    EVIDENCE_TRACK,
    compare_paired_game_mechanics,
    load_accepted_transition,
)


def _fixture():
    observations = pd.DataFrame({
        "canonicalPaId": ["fixture-away", "fixture-home"],
        "canonicalGameId": ["fixture-game", "fixture-game"],
        "game_date": ["2026-05-02", "2026-05-02"],
        "context_top_bottom": [0, 1],
    })
    transition, authority = load_accepted_transition(Path(__file__).resolve().parents[1])
    return observations, transition, authority


def test_observed_top_zero_is_away_and_bottom_one_is_home():
    observations, transition, authority = _fixture()
    away = np.array([1.0, 0, 0, 0, 0, 0, 0, 0])
    home = np.array([0.7, 0, 0.3, 0, 0, 0, 0, 0])
    probabilities = np.vstack([away, home])
    result = compare_paired_game_mechanics(
        observations, probabilities, probabilities,
        transition_model=transition, transition_training_end=authority["trainingEnd"],
        transition_model_sha256=authority["sha256"], n_sims=20,
    )
    game = result["games"][0]["baseline"]
    np.testing.assert_array_equal(game["observedSideMeanPaProbabilities"], probabilities)
    assert game["means"]["away"] == 0
    assert game["means"]["home"] > 0
    assert game["probabilityHomeWin"] == 1


def test_identical_probability_branches_reproduce_coherent_population():
    observations, transition, authority = _fixture()
    probabilities = np.tile([0.22, 0.10, 0.035, 0.145, 0.045, 0.005, 0.44, 0.01], (2, 1))
    result = compare_paired_game_mechanics(
        observations, probabilities, probabilities,
        transition_model=transition, transition_training_end=authority["trainingEnd"],
        transition_model_sha256=authority["sha256"], n_sims=20,
    )
    game = result["games"][0]
    assert game["baseline"]["simulationArraySha256"] == game["challenger"]["simulationArraySha256"]
    assert game["baseline"]["coherent"] and game["challenger"]["coherent"]
    assert game["challengerMinusBaseline"]["probabilityHomeWin"] == 0
    assert set(game["challengerMinusBaseline"]["means"].values()) == {0}
    assert result["evidenceTrack"] == EVIDENCE_TRACK
    assert result["pregameForecastsProduced"] == 0

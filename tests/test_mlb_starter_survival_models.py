"""Small mathematical fixtures, no learned estimator, source data or publication."""
import numpy as np
import pandas as pd
import pytest

from server.sports_current_statcast.mlb_starter_survival_models import (
    PREGAME_FIELDS, LearnedHazard, target_codes, pregame_bf_distribution, duration_metrics, losses,
)


class ConstantHazard:
    feature_order = PREGAME_FIELDS

    def predict_proba(self, frame, *, calibrated=True):
        return np.tile([0.5, 0.3, 0.2], (len(frame), 1))


def test_competing_endpoints_conserve_mass_and_tail_is_not_hook():
    starts = pd.DataFrame({"homePitcher": [0, 1], "realizedBf": [2, 4]})
    law = pregame_bf_distribution(ConstantHazard(), starts, maximum_bf=100)
    assert np.allclose(law["pmf"].sum(1) + law["tail"], 1)
    assert np.allclose(law["causeMass"][:, :, 0].sum(1), 0.6)
    assert np.allclose(law["causeMass"][:, :, 1].sum(1), 0.4)
    assert np.all(law["tail"] > 0)
    metrics = duration_metrics(law, starts.realizedBf)
    assert np.allclose(metrics["expectedBfCapped101"], 2)
    assert np.allclose(metrics["earlyExitProbability"], 1 - 0.5 ** 9)
    assert np.allclose(metrics["longStartProbability"], 0.5 ** 26)


def test_observed_future_state_cannot_enter_pregame_model_or_distribution():
    model = LearnedHazard("LOGISTIC_PREGAME", ("bf", "runsAllowedSoFar"))
    with pytest.raises(ValueError, match="future"):
        model.fit(pd.DataFrame(), [])
    with pytest.raises(ValueError, match="Conditional observed state"):
        pregame_bf_distribution(model, pd.DataFrame({"startId": ["synthetic"]}))
    starts = pd.DataFrame({"futureFinalScore": [2, 9]})
    first = pregame_bf_distribution(ConstantHazard(), starts)
    starts["futureFinalScore"] = [999, -999]
    second = pregame_bf_distribution(ConstantHazard(), starts)
    assert np.array_equal(first["pmf"], second["pmf"])


def test_unknown_censoring_is_not_removal_and_probability_scores_coherent():
    assert target_codes(["CONTINUE", "REMOVAL", "GAME_END"]).tolist() == [0, 1, 2]
    with pytest.raises(ValueError, match="Unknown/censored"):
        target_codes(["UNKNOWN"])
    p = np.array([[0.5, 0.3, 0.2]])
    nll, brier = losses(p, np.array([2]))
    assert nll[0] == pytest.approx(-np.log(0.2))
    assert brier[0] == pytest.approx(0.5 ** 2 + 0.3 ** 2 + 0.8 ** 2)
    with pytest.raises(ValueError, match="Incoherent"):
        losses(p * 2, np.array([2]))

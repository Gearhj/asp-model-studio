import numpy as np
import pandas as pd

from server.sports_nfl_m1.current_state_study import crps, mixture, ensemble_weight, calibration


def test_joint_mixture_never_breaks_paired_scores_and_crps_is_exact():
    first = {"home_draws": np.zeros((2,100), int), "away_draws": np.ones((2,100), int)}
    second = {"home_draws": np.full((2,100),20), "away_draws": np.full((2,100),30)}
    mixed = mixture(first, second, .5, 17)
    assert set(zip(mixed["home_draws"].ravel(),mixed["away_draws"].ravel())) == {(0,1),(20,30)}
    assert np.array_equal(mixed["home_draws"],mixture(first,second,.5,17)["home_draws"])
    assert crps(np.array([[0,2]]),np.array([1])).item() == .5


def test_ensemble_requires_two_completed_oof_seasons():
    frame = pd.DataFrame({"canonical_game_id":["a","b"], "season":[2020,2020]})
    weight, evidence = ensemble_weight(frame,frame)
    assert weight == 0
    assert "WARMUP" in evidence["status"]


def test_calibration_bins_include_decimal_boundaries_once():
    frame = pd.DataFrame({f"raw_{side}_probability":np.linspace(0,1,11) for side in ("away","tie","home")})
    frame["outcome_class"] = np.arange(11) % 3
    for value in calibration(frame).values():
        assert sum(band["count"] for band in value["reliability"]) == 11

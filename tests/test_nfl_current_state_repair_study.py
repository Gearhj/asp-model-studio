import numpy as np
import pandas as pd

from server.sports_nfl_m1 import current_state_repair_study as study


def test_balanced_mixture_preserves_fixed_conditional_means_when_dispersion_changes():
    means_h = np.array([[21.1, 18.2], [25.3, 23.4]])
    means_r = means_h + np.array([[1., -1.], [-2., 2.]])
    raw = np.arange(400).reshape(2, 200).astype(float) - 100
    def component(means, scale):
        return {"scoreMeans": means, "homeDraws": raw*scale, "awayDraws": raw[:, ::-1]*scale}
    first = study.balanced_mixture(component(means_h, 1), component(means_r, .5), .4, 77)
    second = study.balanced_mixture(component(means_h, 5), component(means_r, 3), .4, 77)
    for name, side in (("home_draws", 0), ("away_draws", 1)):
        target = np.rint(((1-.4)*means_h[:, side]+.4*means_r[:, side])*200)
        np.testing.assert_array_equal(first[name].sum(1), target)
        np.testing.assert_array_equal(second[name].sum(1), target)
        assert np.all(second[name] >= 0)


def test_chronological_calibration_uses_only_earlier_oof_and_keeps_score_predictions(tmp_path):
    frame = pd.DataFrame({"canonical_game_id": [f"g{i}" for i in range(18)],
        "season": [2020]*9+[2021]*9, "outcome_class": [0, 1, 2]*6,
        "raw_away_probability": [.4, .2, .3]*6, "raw_tie_probability": [.1, .2, .1]*6,
        "raw_home_probability": [.5, .6, .6]*6,
        "predicted_home_points": np.arange(18)+10., "predicted_away_points": np.arange(18)+8.})
    events = []
    result = study.chronological_calibration(frame, tmp_path / "calibration", events.append)
    assert len([row for row in events if row["event"] == "EVALUATION_CALIBRATOR_FIT_COMPLETE"]) == 1
    completed = events[-1]
    assert completed["trainingSeasons"] == [2020] and completed["trainingGames"] == 9
    assert completed["trainingObservationIds"] == frame.canonical_game_id.iloc[:9].tolist()
    assert completed["reloadMismatch"] == 0
    np.testing.assert_array_equal(result.loc[:8, [f"calibrated_{side}_probability" for side in ("away", "tie", "home")]],
                                  frame.loc[:8, study.PROBABILITIES])
    np.testing.assert_array_equal(result[["predicted_home_points", "predicted_away_points"]], frame[["predicted_home_points", "predicted_away_points"]])

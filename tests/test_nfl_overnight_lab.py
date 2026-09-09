from __future__ import annotations

import numpy as np
import pandas as pd

from server.sports_nfl_m1.overnight_lab import (
    _chronological_calibration,
    _folds,
    _loss_vector,
    _plain_json,
    _select_tuning_candidates,
)


def _games() -> pd.DataFrame:
    rows = []
    for season in range(2019, 2025):
        for game in range(3):
            rows.append({
                "canonical_game_id": f"{season}-{game}", "season": season,
                "game_date": pd.Timestamp(f"{season}-09-{game + 1:02d}"),
            })
    return pd.DataFrame(rows)


def test_expanding_folds_end_at_2024_without_2025() -> None:
    folds = _folds(_games())
    assert [fold["validationSeason"] for fold in folds] == [2020, 2021, 2022, 2023, 2024]
    assert all(fold["trainEnd"] < fold["validationStart"] for fold in folds)


def test_tuning_selects_two_distinct_families() -> None:
    results = [
        {"pipelineId": "A", "family": "RIDGE", "status": "COMPLETED", "metrics": {"multiclassLogLoss": 0.9}},
        {"pipelineId": "B", "family": "RIDGE", "status": "COMPLETED", "metrics": {"multiclassLogLoss": 0.91}},
        {"pipelineId": "C", "family": "XGBOOST", "status": "COMPLETED", "metrics": {"multiclassLogLoss": 0.92}},
        {"pipelineId": "D", "family": "MLP", "status": "FAILED"},
    ]
    assert _select_tuning_candidates(results) == ["A", "C"]


def test_chronological_calibration_never_uses_same_season() -> None:
    rows = []
    for season in (2020, 2021, 2022):
        for outcome in (0, 1, 2):
            rows.append({
                "season": season, "actual_home_points": 20.0, "actual_away_points": 17.0,
                "predicted_home_points": 21.0, "predicted_away_points": 18.0,
                "outcome_class": outcome, "raw_away_probability": 0.30,
                "raw_tie_probability": 0.05, "raw_home_probability": 0.65,
            })
    calibrated, receipt = _chronological_calibration(pd.DataFrame(rows))
    assert receipt["folds"][0]["status"] == "RAW_INSUFFICIENT_EARLIER_OOF"
    assert receipt["folds"][1]["trainingSeasons"] == [2020]
    assert receipt["folds"][2]["trainingSeasons"] == [2020, 2021]
    assert np.isfinite(calibrated.filter(like="calibrated_").to_numpy()).all()
    assert np.isfinite(_loss_vector(np.array([[0.2, 0.1, 0.7]]), np.array([2]))).all()


def test_canonical_receipt_accepts_numpy_dataframe_scalars() -> None:
    assert _plain_json({"games": np.int32(269), "loss": np.float64(0.67)}) == {
        "games": 269,
        "loss": 0.67,
    }

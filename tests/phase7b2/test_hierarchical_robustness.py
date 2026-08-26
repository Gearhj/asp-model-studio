from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from server.sports_gold import hierarchical_robustness as H
from server.sports_gold.binary_hierarchical import binary_labels
from server.sports_gold.contracts import GOLD_FEATURES
from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix


def _fixture_frame(rows_per_year: int = 24) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for season in (2021, 2022, 2023, 2024):
        for index in range(rows_per_year):
            row: dict[str, object] = {
                "season": season,
                "outcome": PA_CLASS_ORDER[index % len(PA_CLASS_ORDER)],
            }
            for feature_index, feature in enumerate(GOLD_FEATURES):
                row[feature] = float(((index + 1) * (feature_index + 3) + season) % 17)
            row["context_top_bottom"] = int(index % 2)
            row["context_outs_before"] = int(index % 3)
            row["context_base_mask_before"] = int(index % 8)
            rows.append(row)
    return pd.DataFrame(rows)


def test_chronological_oof_folds_are_exact_and_never_use_2024() -> None:
    seasons = np.repeat(np.asarray([2021, 2022, 2023, 2024]), 3)
    folds = H.chronological_fold_masks(seasons)
    assert len(folds) == 2
    first, second = folds
    assert first[0].training_seasons == (2021,)
    assert first[0].validation_season == 2022
    assert set(seasons[first[1]]) == {2021}
    assert set(seasons[first[2]]) == {2022}
    assert second[0].training_seasons == (2021, 2022)
    assert second[0].validation_season == 2023
    assert set(seasons[second[1]]) == {2021, 2022}
    assert set(seasons[second[2]]) == {2023}
    assert not any(mask[seasons == 2024].any() for _, *masks in folds for mask in masks)


def test_fixed_candidate_inventory_is_exact_and_bounded() -> None:
    specs = H.candidate_specs()
    assert len(specs) == 13
    assert sum(item.family == "gold_binary_logistic" for item in specs) == 4
    assert sum(item.family == "gold_binary_extra_trees" for item in specs) == 4
    assert sum(item.family == "gold_binary_hgb" for item in specs) == 4
    assert sum(item.family == "collapsed_direct_gold_logistic" for item in specs) == 1
    assert {item.config["C"] for item in specs if item.family == "gold_binary_logistic"} == {
        0.01, 0.05, 0.20, 1.00
    }


def test_generate_oof_predictions_cover_only_2022_and_2023() -> None:
    frame = _fixture_frame()
    labels = binary_labels(frame["outcome"].to_numpy())
    leaderboard, predictions, positions, folds = H.generate_chronological_oof(frame, labels)
    assert len(leaderboard) == 13
    assert len(predictions) == 13
    assert set(frame.iloc[positions]["season"]) == {2022, 2023}
    assert all(row["status"] == "SUCCESS" for row in leaderboard)
    assert all(np.isfinite(values).all() and values.shape == positions.shape for values in predictions.values())
    assert [row["uses2024"] for row in folds] == [False, False]


def test_all_calibrators_are_probability_safe_and_selection_is_primary_metric_first() -> None:
    raw = np.linspace(0.05, 0.95, 80)
    labels = (np.arange(80) % 3 == 0).astype(np.int8)
    for method in ("raw", "platt", "isotonic"):
        calibrator = H.fit_probability_calibrator(method, labels, raw)
        first = calibrator.transform(raw)
        second = calibrator.transform(raw)
        assert np.array_equal(first, second)
        assert np.isfinite(first).all()
        assert np.all((first >= 0.0) & (first <= 1.0))

    records = [
        {
            "family": "b", "calibrationMethod": "raw", "status": "SUCCESS",
            "metrics": {"binaryLogLoss": 0.50, "brierScore": 0.20, "ece": 0.01,
                        "calibrationIntercept": 0.0, "calibrationSlope": 1.0},
        },
        {
            "family": "a", "calibrationMethod": "platt", "status": "SUCCESS",
            "metrics": {"binaryLogLoss": 0.49, "brierScore": 0.30, "ece": 0.20,
                        "calibrationIntercept": 0.5, "calibrationSlope": 0.5},
        },
    ]
    assert H.select_calibrated_candidate(records)["family"] == "a"


def test_game_bootstrap_samples_whole_games_and_is_deterministic() -> None:
    labels = np.asarray(list(PA_CLASS_ORDER) * 2, dtype=object)
    direct = np.full((16, 8), 1.0 / 8.0, dtype=np.float64)
    selected = direct.copy()
    encoded = np.tile(np.arange(8), 2)
    selected[np.arange(16), encoded] += 0.01
    selected -= 0.01 / 7.0 * (1.0 - np.eye(8)[encoded])
    direct = validate_probability_matrix(direct)
    selected = validate_probability_matrix(selected)
    games = np.asarray([f"game-{index // 2}" for index in range(16)], dtype=object)
    first, first_values = H.compact_game_bootstrap(
        labels=labels, selected=selected, direct=direct, game_ids=games,
        n_resamples=50, seed=7,
    )
    second, second_values = H.compact_game_bootstrap(
        labels=labels, selected=selected, direct=direct, game_ids=games,
        n_resamples=50, seed=7,
    )
    assert first["resamplingUnit"] == "game_id"
    assert first["rowsSampledIndependently"] is False
    assert first["clusterCount"] == 8
    assert np.array_equal(first_values, second_values)
    assert first == second


def test_stability_slice_inventory_is_bounded_and_keeps_empty_postseason() -> None:
    validation = pd.DataFrame({
        "outcome": list(PA_CLASS_ORDER),
        "game_date": [f"2024-0{3 + index // 4}-01" for index in range(8)],
        "canonicalGameId": [f"g{index // 2}" for index in range(8)],
        "batterCanonicalPlayerId": ["seen-b", "new-b"] * 4,
        "pitcherCanonicalPlayerId": ["seen-p"] * 6 + ["new-p"] * 2,
        "batter_last100_pa_count": [99.0, 100.0] * 4,
        "pitcher_last250_bf_count": [249.0, 250.0] * 4,
    })
    development = pd.DataFrame({
        "batterCanonicalPlayerId": ["seen-b"],
        "pitcherCanonicalPlayerId": ["seen-p"],
    })
    direct = validate_probability_matrix(np.full((8, 8), 1.0 / 8.0))
    selected = direct.copy()
    rows = H.stability_slices(
        validation=validation,
        development=development,
        direct=direct,
        selected=selected,
        game_types={f"g{index}": "R" for index in range(4)},
    )
    assert len(rows) == 12  # two months plus five requested binary partitions
    postseason = next(row for row in rows if row["slice"] == "POSTSEASON")
    assert postseason["status"] == "EMPTY_NOT_ESTIMABLE"
    assert postseason["rows"] == 0

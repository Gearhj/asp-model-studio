from __future__ import annotations

from dataclasses import FrozenInstanceError
from itertools import combinations
import json

import numpy as np
import pandas as pd
import pytest

from server.sports_gold import walk_forward_ensemble as WalkForward
from server.sports_gold import walk_forward_charts as WalkForwardCharts
from server.sports_gold import walk_forward_state as State
from server.sports_gold import recent_data_walk_forward as Study
from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix
from scripts import phase7b_research as ResearchCLI


def _rows_for_dates(
    dates: list[pd.Timestamp], *, rows_per_date: int = 8, prefix: str
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for date_index, day in enumerate(dates):
        game_id = f"{prefix}-game-{date_index}"
        for row_index in range(rows_per_date):
            rows.append(
                {
                    "game_date": day,
                    "canonicalGameId": game_id,
                    "outcome": PA_CLASS_ORDER[row_index % len(PA_CLASS_ORDER)],
                    "plate_appearance_id": f"{prefix}-pa-{date_index}-{row_index}",
                }
            )
    return rows


def _fold_frame() -> pd.DataFrame:
    prior_dates = [pd.Timestamp("2021-09-01")]
    validation_dates = [
        *[pd.Timestamp(2022, month, 1) for month in range(4, 13)],
        *[pd.Timestamp(2023, month, 1) for month in range(4, 12)],
        pd.Timestamp("2024-04-01"),
        pd.Timestamp("2024-05-01"),
        pd.Timestamp("2024-06-01"),
        pd.Timestamp("2024-07-01"),
        pd.Timestamp("2024-08-01"),
        pd.Timestamp("2024-09-01"),
        pd.Timestamp("2024-09-10"),
        pd.Timestamp("2024-09-16"),
    ]
    assert len(validation_dates) == 25
    holdout_dates = list(pd.date_range("2024-09-17", "2024-09-30", freq="D"))
    rows = [
        *_rows_for_dates(prior_dates, prefix="prior"),
        *_rows_for_dates(validation_dates, prefix="validation"),
        *_rows_for_dates(holdout_dates, prefix="holdout"),
    ]
    return pd.DataFrame(rows)


def _daily_state_frame() -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    rows: list[dict[str, object]] = []
    for repetition in range(12):
        day = pd.Timestamp("2022-01-01") + pd.Timedelta(days=repetition)
        for player_index in range(12):
            rows.append(
                {
                    "game_date": day,
                    "outcome": PA_CLASS_ORDER[
                        (player_index + repetition % ((player_index % 4) + 1))
                        % len(PA_CLASS_ORDER)
                    ],
                    "batterCanonicalPlayerId": f"b{player_index}",
                    "pitcherCanonicalPlayerId": f"p{(player_index * 5) % 12}",
                    "plate_appearance_id": f"history-{repetition}-{player_index}",
                    "canonicalGameId": f"history-game-{repetition}",
                }
            )
    for index, (day, outcome) in enumerate(
        (
            (pd.Timestamp("2022-02-01"), "STRIKEOUT"),
            (pd.Timestamp("2022-02-01"), "BIP_OUT"),
            (pd.Timestamp("2022-02-02"), "SINGLE"),
        )
    ):
        rows.append(
            {
                "game_date": day,
                "outcome": outcome,
                "batterCanonicalPlayerId": "b0",
                "pitcherCanonicalPlayerId": "p0",
                "plate_appearance_id": f"score-{index}",
                "canonicalGameId": f"score-game-{day:%Y%m%d}",
            }
        )
    frame = pd.DataFrame(rows)
    score_mask = frame["plate_appearance_id"].str.startswith("score-").to_numpy()
    probabilities = validate_probability_matrix(
        np.full((len(frame), len(PA_CLASS_ORDER)), 1.0 / len(PA_CLASS_ORDER))
    )
    return frame, score_mask, probabilities


def _ensemble_fixture(
    rows: int = 80,
) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, dict[str, np.ndarray]]]:
    encoded = np.arange(rows, dtype=np.int64) % len(PA_CLASS_ORDER)
    labels = np.asarray(PA_CLASS_ORDER, dtype=object)[encoded]
    probabilities: dict[str, np.ndarray] = {}
    reliability: dict[str, dict[str, np.ndarray]] = {}
    positions = np.arange(rows, dtype=np.int64)
    for component_index, component in enumerate(
        WalkForward.WALK_FORWARD_COMPONENT_ORDER
    ):
        matrix = np.full((rows, len(PA_CLASS_ORDER)), 0.03, dtype=np.float64)
        matrix[np.arange(rows), encoded] += 0.44 - 0.02 * component_index
        distractor = (encoded + component_index + 1) % len(PA_CLASS_ORDER)
        matrix[np.arange(rows), distractor] += 0.01 * (component_index + 1)
        probabilities[component] = validate_probability_matrix(
            matrix / matrix.sum(axis=1, keepdims=True)
        )
        if component != WalkForward.DIRECT_GOLD:
            count = ((positions + 2 * component_index) % 23 + 1).astype(np.float64)
            missing = (positions + component_index) % 19 == 0
            reliability[component] = {
                "observationCount": count,
                "effectiveSampleSize": count * 0.75,
                "missingHistoryFlag": missing,
                "daysSincePriorAppearance": np.where(
                    missing, np.nan, 1.0 + positions % 29
                ),
                "entropy": np.full(rows, 1.3 + component_index / 100.0),
                "deviationFromLongTerm": (
                    positions % 9 / 20.0 + component_index / 500.0
                ),
            }
    return labels, probabilities, reliability


def _chronological_ledger(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    *,
    availability: np.ndarray | None = None,
) -> State.ChronologicalDirectLedger:
    cutoffs = (pd.to_datetime(frame["game_date"]) - pd.Timedelta(days=1)).dt.strftime(
        "%Y-%m-%d"
    )
    return State.ChronologicalDirectLedger.aligned(
        frame,
        probabilities,
        cutoffs,
        availability=availability,
    )


def _chart_result() -> dict[str, object]:
    selected = "E10"
    candidates = ["CLASS_FREQUENCY_NULL", "MATCHED_BASE", "DIRECT_GOLD", selected]
    daily = [
        {
            "scoreDate": day,
            "candidateId": candidate,
            "logLoss": 1.5 - 0.01 * candidate_index + 0.002 * day_index,
        }
        for day_index, day in enumerate(("2024-09-16", "2024-09-17"))
        for candidate_index, candidate in enumerate(candidates)
    ]
    coverage = [
        {
            "scoreDate": day,
            "componentId": component,
            "coverage": 0.75 + 0.01 * component_index,
            "effectiveSampleSizeMean": 10.0 + component_index + day_index,
        }
        for day_index, day in enumerate(("2024-09-16", "2024-09-17"))
        for component_index, component in enumerate(
            WalkForward.WALK_FORWARD_EMPIRICAL_COMPONENTS
        )
    ]
    return {
        "selectedOofEnsemble": selected,
        "request": {"components": list(WalkForward.WALK_FORWARD_COMPONENT_ORDER)},
        "tables": {
            "candidate-performance": [
                {
                    "candidateId": candidate,
                    "logLossImprovementVsDirect": 0.01 * index,
                }
                for index, candidate in enumerate(candidates)
            ],
            "daily-performance": daily,
            "coverage-by-date": coverage,
            "ensemble-weights-gating": [
                {
                    "componentId": component,
                    "e9Weight": 0.1,
                    "e10CoefficientImportance": 0.1,
                }
                for component in WalkForward.WALK_FORWARD_COMPONENT_ORDER
            ],
        },
    }


def test_final_holdout_is_the_frozen_last_fourteen_calendar_days() -> None:
    frame = _fold_frame()
    holdout, mask = WalkForward.freeze_final_holdout(frame)
    assert holdout.start_date == "2024-09-17"
    assert holdout.end_date == "2024-09-30"
    assert len(holdout.active_dates) == 14
    assert holdout.row_count == 14 * 8
    assert holdout.game_count == 14
    assert int(mask.sum()) == holdout.row_count
    dates = pd.to_datetime(frame["game_date"])
    assert dates[mask].min() == pd.Timestamp("2024-09-17")
    assert dates[mask].max() == pd.Timestamp("2024-09-30")
    assert np.array_equal(mask, (dates >= "2024-09-17").to_numpy())
    first_record = holdout.record()
    second, second_mask = WalkForward.freeze_final_holdout(frame.copy())
    assert second.record() == first_record
    assert np.array_equal(second_mask, mask)
    with pytest.raises(FrozenInstanceError):
        holdout.row_count = 0  # type: ignore[misc]

    prohibited = pd.concat(
        [
            frame,
            pd.DataFrame(
                {
                    "game_date": [pd.Timestamp("2025-01-01")],
                    "canonicalGameId": ["prohibited-2025"],
                }
            ),
        ],
        ignore_index=True,
    )
    with pytest.raises(
        WalkForward.WalkForwardEnsembleError, match="2021--2024|2025|2026"
    ):
        WalkForward.freeze_final_holdout(prohibited)


def test_five_walk_forward_folds_are_contiguous_date_atomic_and_equal_pa() -> None:
    frame = _fold_frame()
    holdout, holdout_mask = WalkForward.freeze_final_holdout(frame)
    folds = WalkForward.five_equal_pa_walk_forward_folds(frame, holdout)
    assert len(folds) == 5
    dates = pd.to_datetime(frame["game_date"])
    expected_validation = (
        (dates >= pd.Timestamp("2022-01-01"))
        & (dates < pd.Timestamp(holdout.start_date))
    ).to_numpy()
    validation_union = np.zeros(len(frame), dtype=bool)
    prior_validation = np.zeros(len(frame), dtype=bool)
    previous_end: pd.Timestamp | None = None
    for fold_index, (fold, training, validation) in enumerate(folds, start=1):
        assert fold.fold_id == f"FOLD_{fold_index}"
        assert training.dtype == validation.dtype == np.bool_
        assert not (training & validation).any()
        assert not (validation & holdout_mask).any()
        assert dates[training].max() < dates[validation].min()
        assert not validation_union[validation].any()
        assert np.all(training[prior_validation])
        validation_days = pd.DatetimeIndex(dates[validation].unique()).sort_values()
        assert len(validation_days) == 5
        assert int(validation.sum()) == 40
        if previous_end is not None:
            remaining_days = pd.DatetimeIndex(
                dates[expected_validation & ~validation_union].unique()
            ).sort_values()
            assert validation_days[0] == remaining_days[0]
            assert previous_end < validation_days[0]
        previous_end = validation_days[-1]
        for day in validation_days:
            same_day = (dates == day).to_numpy()
            assert np.array_equal(
                validation[same_day], np.ones(same_day.sum(), dtype=bool)
            )
        validation_union |= validation
        prior_validation |= validation
    assert np.array_equal(validation_union, expected_validation)


def test_uneven_date_atomic_folds_are_globally_nearest_to_equal_pa() -> None:
    validation_dates = list(pd.date_range("2022-01-01", periods=9, freq="MS"))
    date_counts = np.asarray([1, 9, 2, 7, 4, 8, 3, 6, 5], dtype=np.int64)
    rows = _rows_for_dates([pd.Timestamp("2021-09-01")], prefix="prior")
    for index, (day, count) in enumerate(
        zip(validation_dates, date_counts, strict=True)
    ):
        rows.extend(
            _rows_for_dates([day], rows_per_date=int(count), prefix=f"uneven-{index}")
        )
    rows.extend(
        _rows_for_dates(
            list(pd.date_range("2024-09-17", "2024-09-30", freq="D")),
            rows_per_date=2,
            prefix="holdout",
        )
    )
    frame = pd.DataFrame(rows)
    holdout, _ = WalkForward.freeze_final_holdout(frame)
    folds = WalkForward.five_equal_pa_walk_forward_folds(frame, holdout)
    observed_counts = tuple(int(validation.sum()) for _, _, validation in folds)
    observed_boundaries = tuple(
        sum(len(prior_fold[0].validation_active_dates) for prior_fold in folds[:index])
        for index in range(1, len(folds))
    )

    target = float(date_counts.sum()) / 5.0
    candidates: list[tuple[tuple[float, float, tuple[int, ...]], tuple[int, ...]]] = []
    for boundaries in combinations(range(1, len(date_counts)), 4):
        block_counts = np.asarray(
            [part.sum() for part in np.split(date_counts, boundaries)], dtype=float
        )
        objective = (
            float(np.max(np.abs(block_counts - target))),
            float(np.sum(np.square(block_counts - target))),
            boundaries,
        )
        candidates.append((objective, boundaries))
    expected_boundaries = min(candidates, key=lambda item: item[0])[1]
    assert observed_boundaries == expected_boundaries
    assert sum(observed_counts) == int(date_counts.sum())
    assert max(abs(count - target) for count in observed_counts) <= int(
        date_counts.max()
    )


def test_daily_masks_use_only_earlier_dates_and_update_between_score_days() -> None:
    frame, score_mask, _ = _daily_state_frame()
    daily = WalkForward.daily_walk_forward_masks(
        frame["game_date"],
        score_mask,
        history_eligible_mask=np.ones(len(frame), dtype=bool),
    )
    assert len(daily) == 2
    scored_once = np.zeros(len(frame), dtype=np.int8)
    dates = pd.to_datetime(frame["game_date"])
    for day, history, score_day in daily:
        scored_once += score_day.astype(np.int8)
        target_date = dates[score_day].unique()
        assert len(target_date) == 1
        assert str(pd.Timestamp(target_date[0]).date()) == day.score_date
        assert np.all(dates[history] < pd.Timestamp(target_date[0]))
        assert not history[score_day].any()
    assert np.array_equal(scored_once, score_mask.astype(np.int8))
    assert np.all(daily[1][1][daily[0][2]])
    assert int(daily[1][1].sum()) == int(daily[0][1].sum() + daily[0][2].sum())

    prohibited_dates = pd.Series(
        [pd.Timestamp("2024-09-01"), pd.Timestamp("2026-01-01")]
    )
    with pytest.raises(
        WalkForward.WalkForwardEnsembleError, match="2021--2024|2025|2026"
    ):
        WalkForward.daily_walk_forward_masks(
            prohibited_dates,
            np.ones(2, dtype=bool),
            history_eligible_mask=np.ones(2, dtype=bool),
        )


def test_state_engine_is_date_atomic_and_residuals_require_chronological_ledger() -> (
    None
):
    frame, score_mask, direct = _daily_state_frame()
    training_mask = ~score_mask
    availability = np.ones(len(frame), dtype=bool)
    availability[0] = False
    ledger = _chronological_ledger(frame, direct, availability=availability)

    with pytest.raises(TypeError, match="ChronologicalDirectLedger"):
        State.fit_walk_forward_state(
            frame, direct, training_mask=training_mask  # type: ignore[arg-type]
        )
    engine = State.fit_walk_forward_state(frame, ledger, training_mask=training_mask)
    target_positions = np.flatnonzero(score_mask)
    day_one = frame.iloc[target_positions[:2]].copy()
    day_two = frame.iloc[target_positions[2:]].copy()

    with pytest.raises(TypeError, match="ChronologicalDirectLedger"):
        engine.score_day(day_one, direct[target_positions[:2]])  # type: ignore[arg-type]
    bad_day_one_ledger = State.ChronologicalDirectLedger.aligned(
        day_one,
        direct[target_positions[:2]],
        ["2022-02-01", "2022-02-01"],
    )
    with pytest.raises(State.WalkForwardStateError, match="strictly earlier"):
        engine.score_day(day_one, bad_day_one_ledger)

    day_one_ledger = ledger.subset(day_one["plate_appearance_id"].tolist())
    first = engine.score_day(day_one, day_one_ledger)
    repeated = engine.score_day(day_one, day_one_ledger)
    assert repeated is first
    assert tuple(first.probability_matrices) == WalkForward.WALK_FORWARD_COMPONENT_ORDER
    assert tuple(first.components) == State.WALK_FORWARD_COMPONENT_ORDER
    assert first.history_end_day_before_score == "2022-01-12"
    assert first.residual_expectation_source == State.RESIDUAL_EXPECTATION_SOURCE
    assert first.components[
        WalkForward.SHRUNK_EXACT_BVP
    ].observation_count.tolist() == [
        12.0,
        12.0,
    ]
    residual = first.components[WalkForward.RECENT_RESIDUAL_FORM]
    assert residual.role_diagnostics["batter_residual_observation_count"].tolist() == [
        11.0,
        11.0,
    ]
    assert residual.role_diagnostics["pitcher_residual_observation_count"].tolist() == [
        11.0,
        11.0,
    ]
    assert np.all(residual.role_diagnostics["chronological_oof_expectation_verified"])
    for matrix in first.probability_matrices.values():
        validate_probability_matrix(matrix, class_order=PA_CLASS_ORDER)

    engine.advance_day(day_one)
    assert engine.history_end_day == "2022-02-01"
    assert engine.history_rows == int(training_mask.sum()) + 2
    second = engine.score_day(
        day_two, ledger.subset(day_two["plate_appearance_id"].tolist())
    )
    assert second.components[
        WalkForward.SHRUNK_EXACT_BVP
    ].observation_count.tolist() == [14.0]
    second_residual = second.components[WalkForward.RECENT_RESIDUAL_FORM]
    assert second_residual.role_diagnostics[
        "batter_residual_observation_count"
    ].tolist() == [13.0]
    assert second_residual.role_diagnostics[
        "pitcher_residual_observation_count"
    ].tolist() == [13.0]
    engine.advance_day(day_two)

    future = day_two.copy()
    future["game_date"] = pd.Timestamp("2025-01-01")
    future["plate_appearance_id"] = "prohibited-future-row"
    future_ledger = State.ChronologicalDirectLedger.aligned(
        future, direct[target_positions[2:]], "2024-12-31"
    )
    with pytest.raises(State.WalkForwardStateError, match="2025-or-later"):
        engine.score_day(future, future_ledger)


def test_state_block_scores_advances_and_restores_every_input_row() -> None:
    frame, score_mask, direct = _daily_state_frame()
    training_mask = ~score_mask
    ledger = _chronological_ledger(frame, direct)
    engine = State.fit_walk_forward_state(frame, ledger, training_mask=training_mask)
    target_positions = np.flatnonzero(score_mask)
    shuffled_positions = target_positions[[2, 0, 1]]
    target = frame.iloc[shuffled_positions].reset_index(drop=True)
    target_ledger = ledger.subset(target["plate_appearance_id"].tolist())
    block = State.score_walk_forward_block(engine, target, target_ledger)

    expected_ids = tuple(target["plate_appearance_id"].tolist())
    assert block.row_ids == expected_ids
    assert tuple(block.probability_matrices) == WalkForward.WALK_FORWARD_COMPONENT_ORDER
    assert block.input_rows == block.scored_rows == block.advanced_rows == 3
    assert block.reconciliation == {
        "inputRows": 3,
        "scoredRows": 3,
        "advancedRows": 3,
        "scoreDates": 2,
        "rowIdsUnique": True,
        "noRowsDropped": True,
    }
    assert [len(bundle.row_ids) for bundle in block.daily_bundles] == [2, 1]
    assert block.initial_history_end_day == "2022-01-12"
    assert block.final_history_end_day == block.score_end_day == "2022-02-02"
    assert block.components[
        WalkForward.SHRUNK_EXACT_BVP
    ].observation_count.tolist() == [14.0, 12.0, 12.0]
    assert block.residual_expectation_source == State.RESIDUAL_EXPECTATION_SOURCE
    for matrix in block.probability_matrices.values():
        assert matrix.shape == (3, len(PA_CLASS_ORDER))
        validate_probability_matrix(matrix, class_order=PA_CLASS_ORDER)


def test_walk_forward_candidate_inventory_is_exact_and_bounded() -> None:
    assert WalkForward.WALK_FORWARD_COMPONENT_ORDER == (
        "DIRECT_GOLD",
        "RECENT_14_DAY_STATE",
        "RECENT_42_DAY_STATE",
        "ROLLING_365_DAY_STATE",
        "ROLLING_730_DAY_STATE",
        "DECAY_180_DAY_STATE",
        "DECAY_365_DAY_STATE",
        "CLUSTER_MATCHUP",
        "SHRUNK_EXACT_BVP",
        "RECENT_RESIDUAL_FORM",
    )
    assert WalkForward.FIXED_WALK_FORWARD_ENSEMBLES == {
        "E1": ("DIRECT_GOLD", "RECENT_14_DAY_STATE"),
        "E2": ("DIRECT_GOLD", "RECENT_14_DAY_STATE", "RECENT_42_DAY_STATE"),
        "E3": ("DIRECT_GOLD", "ROLLING_365_DAY_STATE", "ROLLING_730_DAY_STATE"),
        "E4": ("DIRECT_GOLD", "DECAY_180_DAY_STATE", "DECAY_365_DAY_STATE"),
        "E5": ("DIRECT_GOLD", "CLUSTER_MATCHUP"),
    }
    assert WalkForward.WALK_FORWARD_ENSEMBLE_IDS == (
        "E1",
        "E2",
        "E3",
        "E4",
        "E5",
        "E9",
        "E10",
    )
    assert WalkForward.COMPARISON_CANDIDATE_IDS == (
        "CLASS_FREQUENCY_NULL",
        "MATCHED_BASE",
        "DIRECT_GOLD",
        "E1",
        "E2",
        "E3",
        "E4",
        "E5",
        "E9",
        "E10",
    )

    _, components, _ = _ensemble_fixture(rows=16)
    fixed = WalkForward.build_fixed_walk_forward_ensembles(components)
    assert tuple(fixed) == ("E1", "E2", "E3", "E4", "E5")
    for ensemble_id, members in WalkForward.FIXED_WALK_FORWARD_ENSEMBLES.items():
        expected = np.mean(
            np.stack([components[member] for member in members], axis=0), axis=0
        )
        assert np.allclose(fixed[ensemble_id], expected, rtol=0.0, atol=1e-15)


def test_e9_and_e10_coefficients_are_frozen_before_holdout_scoring() -> None:
    labels, probabilities, reliability = _ensemble_fixture()
    holdout, _ = WalkForward.freeze_final_holdout(_fold_frame())
    oof_dates = pd.date_range("2023-04-01", periods=len(labels), freq="D")
    e9 = WalkForward.fit_walk_forward_convex_blend(
        labels, probabilities, oof_dates, holdout
    )
    e10 = WalkForward.fit_walk_forward_stacker(
        labels, probabilities, reliability, oof_dates, holdout
    )
    e9_weights = np.asarray(e9.weights).copy()
    e10_coefficients = e10.estimator.coef_.copy()
    e10_intercepts = e10.estimator.intercept_.copy()
    scaler_mean = e10.scaler.mean_.copy()
    scaler_scale = e10.scaler.scale_.copy()

    e9_holdout = e9.predict_proba(probabilities)
    e10_holdout = e10.predict_proba(probabilities, reliability)
    validate_probability_matrix(e9_holdout, class_order=PA_CLASS_ORDER)
    validate_probability_matrix(e10_holdout, class_order=PA_CLASS_ORDER)
    assert np.array_equal(np.asarray(e9.weights), e9_weights)
    assert np.array_equal(e10.estimator.coef_, e10_coefficients)
    assert np.array_equal(e10.estimator.intercept_, e10_intercepts)
    assert np.array_equal(e10.scaler.mean_, scaler_mean)
    assert np.array_equal(e10.scaler.scale_, scaler_scale)
    assert e9.record()["weightsFrozenBeforeHoldout"] is True
    assert e9.record()["usesHoldoutForFit"] is False
    assert e10.record()["coefficientsFrozenBeforeHoldout"] is True
    assert e10.record()["usesHoldoutForFit"] is False

    contaminated_dates = oof_dates.to_numpy(copy=True)
    contaminated_dates[-1] = np.datetime64(holdout.start_date)
    with pytest.raises(WalkForward.WalkForwardEnsembleError, match="frozen-holdout"):
        WalkForward.fit_walk_forward_convex_blend(
            labels, probabilities, contaminated_dates, holdout
        )


def test_candidate_evaluation_and_daily_predictions_reconcile_exactly() -> None:
    labels, probabilities, _ = _ensemble_fixture(rows=8)
    direct = probabilities[WalkForward.DIRECT_GOLD]
    candidate_probabilities = {
        candidate_id: direct.copy()
        for candidate_id in WalkForward.COMPARISON_CANDIDATE_IDS
    }
    leaderboard = WalkForward.evaluate_walk_forward_candidates(
        labels, candidate_probabilities
    )
    assert len(leaderboard) == len(WalkForward.COMPARISON_CANDIDATE_IDS) == 10
    assert {row["candidateId"] for row in leaderboard} == set(
        WalkForward.COMPARISON_CANDIDATE_IDS
    )
    assert all(row["metrics"]["rowCount"] == 8 for row in leaderboard)

    accumulator = WalkForward.DailyPredictionAccumulator(
        row_count=8, candidate_ids=("DIRECT_GOLD", "E1")
    )
    accumulator.add_day(
        "2024-09-17",
        np.asarray([0, 1, 2]),
        {"DIRECT_GOLD": direct[:3], "E1": direct[:3]},
    )
    accumulator.add_day(
        "2024-09-18",
        np.asarray([3, 4, 5, 6, 7]),
        {"DIRECT_GOLD": direct[3:], "E1": direct[3:]},
    )
    finalized, reconciliation = accumulator.finalize(np.ones(8, dtype=bool))
    assert tuple(finalized) == ("DIRECT_GOLD", "E1")
    assert all(
        matrix.shape == (8, len(PA_CLASS_ORDER)) for matrix in finalized.values()
    )
    for matrix in finalized.values():
        validated = validate_probability_matrix(matrix, class_order=PA_CLASS_ORDER)
        assert np.array_equal(validated, matrix)
        assert np.isfinite(validated).all()
        assert np.allclose(validated.sum(axis=1), 1.0, rtol=0.0, atol=1e-12)
        assert matrix.flags.writeable is False
    assert reconciliation["eligibleRows"] == reconciliation["scoredRows"] == 8
    assert reconciliation["complete"] is True
    assert sum(row["rowCount"] for row in reconciliation["dailyRecords"]) == 8

    dates = np.asarray(["2024-09-17"] * 3 + ["2024-09-18"] * 5)
    daily = WalkForward.daily_metric_records(labels, dates, finalized)
    assert len(daily) == 2 * len(finalized)
    for candidate_id in finalized:
        candidate_rows = [row for row in daily if row["candidateId"] == candidate_id]
        assert sum(row["metrics"]["rowCount"] for row in candidate_rows) == 8
    assert all(
        row["logLossDifferenceVsDirect"] == 0.0
        for row in daily
        if row["candidateId"] == "DIRECT_GOLD"
    )

    incomplete = WalkForward.DailyPredictionAccumulator(
        row_count=3, candidate_ids=("DIRECT_GOLD",)
    )
    incomplete.add_day("2024-09-17", [0, 1], {"DIRECT_GOLD": direct[:2]})
    with pytest.raises(WalkForward.WalkForwardEnsembleError, match="missing=1"):
        incomplete.finalize(np.ones(3, dtype=bool))

    duplicate = WalkForward.DailyPredictionAccumulator(
        row_count=3, candidate_ids=("DIRECT_GOLD",)
    )
    duplicate.add_day("2024-09-17", [0, 1], {"DIRECT_GOLD": direct[:2]})
    with pytest.raises(WalkForward.WalkForwardEnsembleError, match="more than once"):
        duplicate.add_day("2024-09-18", [1, 2], {"DIRECT_GOLD": direct[1:3]})


def test_combined_method_table_normalizes_component_identity_exactly() -> None:
    candidates = [
        {"candidateId": candidate, "logLoss": float(index + 1)}
        for index, candidate in enumerate(WalkForward.COMPARISON_CANDIDATE_IDS)
    ]
    components = [
        {"componentId": component, "logLoss": float(index + 20)}
        for index, component in enumerate(WalkForward.WALK_FORWARD_COMPONENT_ORDER)
    ]

    combined = Study._all_method_table(candidates, components)

    expected = {
        "CLASS_FREQUENCY_NULL",
        "MATCHED_BASE",
        *WalkForward.WALK_FORWARD_COMPONENT_ORDER,
        *WalkForward.WALK_FORWARD_ENSEMBLE_IDS,
    }
    assert len(combined) == len(expected)
    assert {row["candidateId"] for row in combined} == expected
    component_rows = [row for row in combined if "componentId" in row]
    assert all(row["candidateId"] == row["componentId"] for row in component_rows)


@pytest.mark.parametrize(
    ("selected", "expected"),
    (
        ("E1", "B. ADD_14_DAY_STATE"),
        ("E2", "C. ADD_14_AND_42_DAY_STATE"),
        ("E3", "D. USE_LONGER_ROLLING_STATE"),
        ("E4", "D. USE_LONGER_ROLLING_STATE"),
        ("E5", "E. USE_STATIC_ENSEMBLE"),
        ("E9", "E. USE_STATIC_ENSEMBLE"),
        ("E10", "F. USE_RELIABILITY_GATED_ENSEMBLE"),
    ),
)
def test_pipeline_recommendation_mapping_is_exact_and_holdout_cannot_reselect(
    selected: str, expected: str
) -> None:
    oof = [
        {"candidateId": "DIRECT_GOLD", "logLoss": 1.0},
        {"candidateId": selected, "logLoss": 0.9},
    ]
    holdout = [
        {"candidateId": "DIRECT_GOLD", "logLoss": 1.0},
        {"candidateId": selected, "logLoss": 0.95},
    ]
    decision = Study._recommendation(
        selected=selected, oof_table=oof, holdout_table=holdout
    )
    assert decision["recommendation"] == expected
    assert decision["selectedOofEnsemble"] == selected
    assert decision["holdoutUsedForWeightsOrSelection"] is False
    assert decision["promotionRequested"] is False

    failed_holdout = [
        {"candidateId": "DIRECT_GOLD", "logLoss": 1.0},
        {"candidateId": selected, "logLoss": 1.01},
    ]
    kept = Study._recommendation(
        selected=selected, oof_table=oof, holdout_table=failed_holdout
    )
    assert kept["recommendation"] == "A. KEEP_DIRECT_GOLD"
    assert kept["selectedOofEnsemble"] == selected
    assert kept["holdoutUsedForWeightsOrSelection"] is False


def test_phase7b5_cli_routes_only_the_requested_external_roots(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    observed: dict[str, object] = {}

    def fake_study(*, gold_root, silver_root, progress):
        observed["goldRoot"] = gold_root
        observed["silverRoot"] = silver_root
        progress("synthetic complete")
        return {"status": "SYNTHETIC_COMPLETE", "promotionRequested": False}

    monkeypatch.setattr(Study, "run_recent_data_walk_forward_study", fake_study)
    gold_root = tmp_path / "external-gold"
    silver_root = tmp_path / "external-silver"
    exit_code = ResearchCLI.main(
        [
            "--recent-data-walk-forward",
            "--gold-root",
            str(gold_root),
            "--silver-root",
            str(silver_root),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert observed == {"goldRoot": gold_root, "silverRoot": silver_root}
    assert payload["entryPoint"] == "PHASE_7B5_RECENT_DATA_WALK_FORWARD_RESEARCH_V1"
    assert payload["recentDataWalkForward"] == {
        "status": "SYNTHETIC_COMPLETE",
        "promotionRequested": False,
    }
    assert captured.err.strip() == "[recent-data-walk-forward] synthetic complete"


def test_walk_forward_charts_are_complete_and_byte_deterministic(tmp_path) -> None:
    result = _chart_result()
    first = WalkForwardCharts.generate_walk_forward_charts(result, tmp_path / "first")
    second = WalkForwardCharts.generate_walk_forward_charts(result, tmp_path / "second")
    assert len(first) == len(second) == 4
    assert [row["chartId"] for row in first] == [
        "sorted-improvement-vs-direct",
        "daily-holdout-performance",
        "component-coverage-by-date",
        "ensemble-weight-gating-summary",
    ]
    for first_chart, second_chart in zip(first, second, strict=True):
        assert [item["format"] for item in first_chart["files"]] == ["PNG", "SVG"]
        assert [item["sha256"] for item in first_chart["files"]] == [
            item["sha256"] for item in second_chart["files"]
        ]
        assert all(item["bytes"] > 0 for item in first_chart["files"])

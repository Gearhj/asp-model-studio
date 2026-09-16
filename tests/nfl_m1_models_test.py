from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
import pytest

from server.sports_nfl_m1 import (
    SCORE_MODEL_GRID,
    EloTeamStrengthBaseline,
    FoldLocalPreprocessor,
    IndependentHomeAwayScoreModel,
    LeagueHomePrior,
    NflM1IntegrityError,
    RecencyStrategy,
    RegularizedHomeWinModel,
    RollingScoringMarginBaseline,
    XGBOOST_SCORE_CONFIG,
    assert_no_market_predictors,
    assert_valid_model_predictors,
    recency_weights,
    require_research_only,
    xgboost_capability,
)


def _training_games() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "canonical_game_id": ["g1", "g2", "g3", "g4"],
            "game_date": ["2019-09-01", "2019-09-08", "2019-09-15", "2019-09-22"],
            "canonical_home_team_id": ["A", "B", "A", "C"],
            "canonical_away_team_id": ["B", "C", "C", "A"],
            "home_points": [24, 17, 31, 20],
            "away_points": [17, 21, 14, 27],
        }
    )


def _model_frame(row_count: int = 120) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7301)
    strength = rng.normal(size=row_count)
    rest = rng.integers(3, 12, size=row_count).astype(float)
    rest[::17] = np.nan
    roof = np.where(np.arange(row_count) % 3 == 0, "dome", "outdoors")
    home = np.maximum(np.rint(23.0 + 4.0 * strength + rng.normal(0, 3, row_count)), 0.0)
    away = np.maximum(np.rint(21.0 - 3.0 * strength + rng.normal(0, 3, row_count)), 0.0)
    frame = pd.DataFrame(
        {
            "strength_delta": strength,
            "rest_days": rest,
            "division_game": (np.arange(row_count) % 2).astype(float),
            "roof": roof,
        }
    )
    return frame, home, away


def test_recency_strategies_use_only_pre_validation_rows_and_declared_decay() -> None:
    seasons = np.arange(2014, 2025, dtype=np.int64)
    recent = recency_weights(seasons, 2024, RecencyStrategy.MOST_RECENT_3_SEASONS)
    assert seasons[recent.eligible_mask].tolist() == [2021, 2022, 2023]
    assert np.all(recent.sample_weights[~recent.eligible_mask] == 0.0)

    decay = recency_weights(
        seasons,
        2024,
        RecencyStrategy.EXPONENTIAL_SEASON_DECAY_HALF_LIFE_1,
    )
    included = decay.sample_weights[decay.eligible_mask]
    assert included.mean() == pytest.approx(1.0)
    assert decay.sample_weights[seasons == 2023][0] == pytest.approx(
        2.0 * decay.sample_weights[seasons == 2022][0]
    )
    assert decay.sample_weights[seasons == 2024][0] == 0.0


def test_market_predictors_and_promotion_are_fail_closed() -> None:
    assert assert_no_market_predictors(["rest_days", "historical_total_points"]) == (
        "rest_days",
        "historical_total_points",
    )
    with pytest.raises(NflM1IntegrityError, match="market"):
        assert_no_market_predictors(["rest_days", "home_moneyline"])
    with pytest.raises(NflM1IntegrityError, match="target-game"):
        assert_valid_model_predictors(["rest_days", "home_points"])
    with pytest.raises(NflM1IntegrityError, match="disposition"):
        require_research_only(
            {
                "candidateId": "illegal",
                "status": "PROMOTED",
                "promotionState": "PROMOTED",
                "deploymentEligible": True,
                "marketPredictorsUsed": False,
            }
        )


def test_preprocessing_statistics_are_fitted_on_training_fold_only() -> None:
    training = pd.DataFrame(
        {
            "numeric": [1.0, np.nan, 3.0],
            "source_era_value": [np.nan, np.nan, np.nan],
            "roof": ["dome", None, "outdoors"],
        }
    )
    fitted = FoldLocalPreprocessor.fit(
        training,
        ("numeric", "source_era_value", "roof"),
        categorical_features=("roof",),
        training_row_ids=("a", "b", "c"),
    )
    state = fitted.state()
    assert state["numericImputationStatistics"] == [2.0, 0.0]
    assert state["fitScope"] == "TRAINING_ROWS_OF_THIS_FOLD_ONLY"
    assert state["trainingRowIdSha256"] is not None
    validation = pd.DataFrame(
        {
            "numeric": [100_000.0, np.nan],
            "source_era_value": [np.nan, np.nan],
            "roof": ["retractable", None],
        }
    )
    matrix = fitted.transform(validation)
    assert matrix.shape[0] == 2
    assert np.isfinite(matrix).all()
    assert fitted.state()["numericImputationStatistics"] == [2.0, 0.0]


def test_league_prior_is_smoothed_and_finite() -> None:
    model = LeagueHomePrior().fit([21, 17, 24], [14, 17, 28])
    predictions = model.predict(4)
    assert predictions.row_count == 4
    assert np.all((predictions.home_win_probability > 0) & (predictions.home_win_probability < 1))
    require_research_only(model.state())


@pytest.mark.parametrize("baseline", [RollingScoringMarginBaseline(window_games=3), EloTeamStrengthBaseline()])
def test_chronological_baselines_are_date_atomic_and_ignore_same_day_truth(baseline: object) -> None:
    baseline.fit(_training_games())
    validation = pd.DataFrame(
        {
            "game_date": ["2020-09-01", "2020-09-01"],
            "canonical_home_team_id": ["A", "A"],
            "canonical_away_team_id": ["B", "C"],
            "home_points": [3, 70],
            "away_points": [42, 0],
        }
    )
    changed_truth = validation.assign(home_points=[70, 0], away_points=[0, 70])
    first = baseline.predict(validation, update_with_truth=True)
    second = baseline.predict(changed_truth, update_with_truth=True)
    np.testing.assert_allclose(first.expected_home_points, second.expected_home_points)
    np.testing.assert_allclose(first.expected_away_points, second.expected_away_points)
    np.testing.assert_allclose(first.home_win_probability, second.home_win_probability)
    require_research_only(baseline.state())


def test_regularized_win_model_is_deterministic_and_fold_local() -> None:
    frame, home, away = _model_frame()
    labels = (home > away).astype(np.int64)
    first = RegularizedHomeWinModel(
        tuple(frame.columns), c_value=1.0
    ).fit(frame, labels, training_row_ids=np.arange(len(frame)))
    second = RegularizedHomeWinModel(
        tuple(frame.columns), c_value=1.0
    ).fit(frame, labels, training_row_ids=np.arange(len(frame)))
    np.testing.assert_allclose(first.predict_home_win_proba(frame), second.predict_home_win_proba(frame))
    assert first.state()["marketPredictorsUsed"] is False
    require_research_only(first.state())


@pytest.mark.parametrize("config", [SCORE_MODEL_GRID[0], SCORE_MODEL_GRID[2], SCORE_MODEL_GRID[4]])
def test_score_models_retain_paired_residuals_and_reconcile(config: object) -> None:
    frame, home, away = _model_frame()
    weights = np.linspace(0.5, 1.5, len(frame))
    model = IndependentHomeAwayScoreModel(
        config,
        tuple(frame.columns),
        categorical_features=("roof",),
    ).fit(frame, home, away, sample_weight=weights)
    predictions = model.predict(frame.iloc[:12])
    assert predictions.row_count == 12
    assert model.paired_training_residuals is not None
    assert model.paired_training_residuals.shape == (len(frame), 2)
    assert model.residual_correlation is not None
    assert -1.0 <= model.residual_correlation <= 1.0
    require_research_only(model.state())


def test_score_model_artifact_reloads_without_prediction_drift(tmp_path) -> None:
    frame, home, away = _model_frame(80)
    model = IndependentHomeAwayScoreModel(
        SCORE_MODEL_GRID[0], tuple(frame.columns), categorical_features=("roof",)
    ).fit(frame, home, away)
    expected = model.predict(frame.iloc[:8])
    path = tmp_path / "research-shadow.joblib"
    joblib.dump(model, path)
    reloaded = joblib.load(path)
    observed = reloaded.predict(frame.iloc[:8])
    np.testing.assert_allclose(expected.expected_home_points, observed.expected_home_points)
    np.testing.assert_allclose(expected.expected_away_points, observed.expected_away_points)
    np.testing.assert_allclose(expected.home_win_probability, observed.home_win_probability)
    require_research_only(reloaded.state())


def test_xgboost_probe_is_detection_only() -> None:
    capability = xgboost_capability()
    assert capability["detectionOnly"] is True
    assert capability["instantiated"] is False
    assert isinstance(capability["available"], bool)


def test_fixed_xgboost_score_challenger_uses_the_common_research_contract() -> None:
    capability = xgboost_capability()
    if not capability["available"]:
        pytest.skip("optional XGBoost dependency is unavailable")
    frame, home, away = _model_frame(80)
    first = IndependentHomeAwayScoreModel(
        XGBOOST_SCORE_CONFIG,
        tuple(frame.columns),
        categorical_features=("roof",),
    ).fit(frame, home, away)
    second = IndependentHomeAwayScoreModel(
        XGBOOST_SCORE_CONFIG,
        tuple(frame.columns),
        categorical_features=("roof",),
    ).fit(frame, home, away)
    first_prediction = first.predict(frame.iloc[:10])
    second_prediction = second.predict(frame.iloc[:10])
    np.testing.assert_allclose(
        first_prediction.expected_home_points,
        second_prediction.expected_home_points,
    )
    np.testing.assert_allclose(
        first_prediction.expected_away_points,
        second_prediction.expected_away_points,
    )
    assert first.state()["estimatorFamily"] == "XGBOOST"
    require_research_only(first.state())

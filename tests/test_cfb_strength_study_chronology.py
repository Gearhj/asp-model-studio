"""Synthetic study-boundary tests; no retained or protected outcomes are opened."""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from server.sports_cfb_gen1 import pipeline
from server.sports_cfb_gen1 import strength_study as study


def history_row(game_id, when, **changes):
    row = {"game_id": game_id, "season": 2022, "scheduled_at": pd.Timestamp(when),
           "is_final": True, "home_score": 31.0, "away_score": 20.0, "primary": True}
    row.update(changes)
    return row


def prediction_rows(count=500, season=2021):
    n = np.arange(count)
    home = 21 + n % 21
    away = 14 + n % 17
    return pd.DataFrame({
        "game_id": n + 1, "season": season,
        "scheduled_at": pd.Timestamp(f"{season}-09-01T12:00:00Z") + pd.to_timedelta(n, unit="m"),
        "home_score": home, "away_score": away, "home_win": (home > away).astype(float),
        "pred_home": np.full(count, 28.0), "pred_away": np.full(count, 24.0),
        "pred_margin": np.full(count, 4.0), "pred_total": np.full(count, 52.0),
    })


def scoring_target(season=2022):
    return pd.DataFrame([{
        "game_id": 9999, "season": season, "week": 3,
        "scheduled_at": pd.Timestamp(f"{season}-09-17T18:00:00Z"),
        "neutral_site": False, "conference_competition": False,
        "home_id": 1, "away_id": 2, "home_score": 35.0, "away_score": 21.0,
        "home_margin": 14.0, "total_points": 56.0, "home_win": 1.0,
        "pred_home": 30.0, "pred_away": 24.0, "pred_margin": 6.0, "pred_total": 54.0,
        "arm": "A", "lambda_prior": 12.0, "low_support": True, "opener": False,
        "zero_prior_support": False, "home_current_support": 1, "away_current_support": 1,
        "calibratedHomeWinProbability": 0.6,
    }])


def complete_game(game_id, when, home=1, away=2, **changes):
    row = history_row(game_id, when, home_id=home, away_id=away)
    row.update({
        "week": 1, "home_team": str(home), "away_team": str(away),
        "neutral_site": False, "conference_competition": False, "context_eligible": True,
        "role": "development", "season_type": 2, "home_is_fbs": True,
        "away_is_fbs": True, "both_fbs": True, "postseason": False,
        "late_regular_unclassified": False, "overtime": False, "score_supported": True,
        "home_margin": 11.0, "total_points": 51.0, "home_win": 1.0,
        "home_total_yards": 400.0, "away_total_yards": 300.0,
        "home_turnovers": 1.0, "away_turnovers": 2.0,
    })
    row.update(changes)
    return row


def test_history_gate_is_final_scored_and_atomic_at_utc_date():
    frame = pd.DataFrame([
        history_row(1, "2022-09-08T00:00:00Z"),  # exact 48-hour boundary
        history_row(2, "2022-09-08T00:00:01Z"),
        history_row(3, "2022-09-07T12:00:00Z", is_final=False),
        history_row(4, "2022-09-07T12:00:00Z", away_score=np.nan),
        history_row(5, "2022-09-07T12:00:00Z", primary=False),
        history_row(6, "2022-09-07T12:00:00Z", season=2023),
        history_row(7, "2022-09-10T01:00:00Z"),
    ])
    early = study.eligible_history(frame, "2022-09-10T00:01:00Z", 2022)
    late = study.eligible_history(frame, "2022-09-10T23:59:00Z", 2022)
    assert early.game_id.tolist() == [1]
    pd.testing.assert_frame_equal(early, late)
    context = study.eligible_history(frame, "2022-09-10T23:59:00Z", 2022, primary_only=False)
    assert context.game_id.tolist() == [5, 1]
    assert "completed_at" not in early and "available_at" not in early


def test_history_origin_requires_timezone_and_normalizes_to_utc():
    frame = pd.DataFrame([history_row(1, "2022-09-08T00:00:00Z")])
    with pytest.raises(ValueError, match="UTC-aware"):
        study.eligible_history(frame, "2022-09-10T12:00:00", 2022)
    assert study.eligible_history(frame, "2022-09-09T20:00:00-04:00", 2022).game_id.tolist() == [1]


def test_2026_input_rejected_before_history_or_oof_selection():
    frame = pd.DataFrame([history_row(1, "2026-09-01T00:00:00Z", season=2026)])
    with pytest.raises(ValueError, match="2026"):
        study.eligible_history(frame, "2022-09-10T00:00:00Z", 2022)
    with pytest.raises(ValueError, match="2026"):
        study.prior_oof(frame, 2022)
    with pytest.raises(ValueError, match="2026"):
        study.checked_baseline_features(frame)


def test_prior_oof_excludes_same_and_later_seasons_without_rewriting_predictions():
    previous = pd.concat([prediction_rows(3, 2020), prediction_rows(3, 2021), prediction_rows(3, 2022)])
    earlier = study.prior_oof(previous, 2021)
    pd.testing.assert_frame_equal(earlier, previous.loc[previous.season.eq(2020)])


def grid_scores():
    return pd.DataFrame([
        {"season": season, "arm": arm, "lambda_prior": penalty, "jointEnergyScore": value}
        for season in (2017, 2018)
        for arm in ("A", "B")
        for penalty, value in ((4.0, 10.0), (12.0, 10.1))
    ])


def test_nested_lambda_defaults_until_two_earlier_scored_seasons_and_ignores_future():
    scores = grid_scores()
    assert study.choose_lambda(scores.iloc[:0], 2017) == 12.0
    assert study.choose_lambda(scores, 2018) == 12.0
    assert study.choose_lambda(scores, 2019) == 4.0
    future = pd.DataFrame([
        {"season": s, "arm": arm, "lambda_prior": p, "jointEnergyScore": v}
        for s in (2019, 2020, 2023, 2024, 2025)
        for arm in ("A", "B") for p, v in ((4.0, 10000.0), (12.0, -10000.0))
    ])
    assert study.choose_lambda(pd.concat([scores, future]), 2019) == 4.0
    assert study.choose_lambda(pd.concat([scores, future.loc[future.season.ge(2023)]]), 2026) == 4.0


def test_nested_lambda_tie_prefers_stronger_pooling_and_incomplete_grid_fails():
    scores = grid_scores()
    scores.loc[scores.lambda_prior.eq(12), "jointEnergyScore"] = 10.004
    assert study.choose_lambda(scores, 2019) == 12.0
    with pytest.raises(ValueError, match="incomplete"):
        study.choose_lambda(scores.loc[scores.lambda_prior.eq(4)], 2019)


def test_checked_baseline_keeps_permitted_nonprimary_context_and_excludes_target_outcome():
    games = pd.DataFrame([
        complete_game(1, "2022-09-01T12:00:00Z", away=99, primary=False, away_is_fbs=False, both_fbs=False),
        complete_game(2, "2022-09-08T12:00:00Z"),
    ])
    features = study.checked_baseline_features(games)
    assert features.iloc[1].home_current_season_games == 1
    assert features.iloc[1].home_points_for_season == 31.0
    changed = games.copy()
    changed.loc[1, ["home_score", "away_score", "home_margin", "total_points", "home_total_yards"]] = 9999.0
    updated = study.checked_baseline_features(changed)
    pd.testing.assert_frame_equal(features[pipeline.FEATURE_COLUMNS], updated[pipeline.FEATURE_COLUMNS])


def test_baseline_source_inside_embargo_fails_instead_of_silently_relabelling_it():
    games = pd.DataFrame([
        complete_game(1, "2022-09-07T12:00:00Z"),
        complete_game(2, "2022-09-08T12:00:00Z"),
    ])
    with pytest.raises(ValueError, match="48-hour"):
        study.checked_baseline_features(games)
    games.loc[0, "is_final"] = False
    with pytest.raises(ValueError, match="source-declared final"):
        study.checked_baseline_features(games)


def test_residual_population_is_prior_season_and_identical_arm_inputs_share_draws():
    donors = prediction_rows()
    target = scoring_target()
    first = study.score_predictions(target, donors, draw_count=128)
    contaminant = prediction_rows(5, 2022)
    contaminant[["home_score", "away_score"]] = 999999
    contaminated = study.score_predictions(target, pd.concat([donors, contaminant]), draw_count=128)
    pd.testing.assert_frame_equal(first, contaminated)
    other_arm = target.copy()
    other_arm["arm"] = "B"
    second = study.score_predictions(other_arm, donors, draw_count=128)
    pd.testing.assert_frame_equal(first.drop(columns="arm"), second.drop(columns="arm"))
    assert first.iloc[0].donorCount == 500
    assert first.iloc[0].donorMaximumSeason == 2021
    assert study.score_predictions(target, donors.iloc[:499], draw_count=128).empty


def test_residual_donors_reject_duplicate_identity_and_bad_timestamp():
    donors = prediction_rows()
    target = scoring_target()
    with pytest.raises(ValueError):
        study.score_predictions(target, pd.concat([donors, donors.iloc[:1]]), draw_count=128)
    donors.loc[0, "scheduled_at"] = target.iloc[0].scheduled_at
    with pytest.raises(ValueError):
        study.score_predictions(target, donors, draw_count=128)


def test_score_target_rejects_2026_and_duplicate_targets():
    donors = prediction_rows()
    with pytest.raises(ValueError):
        study.score_predictions(scoring_target(2026), donors, draw_count=128)
    with pytest.raises(ValueError):
        study.score_predictions(pd.concat([scoring_target(), scoring_target()]), donors, draw_count=128)


def training_features():
    rng = np.random.default_rng(28)
    frame = pd.DataFrame(rng.normal(size=(36, len(pipeline.FEATURE_COLUMNS))), columns=pipeline.FEATURE_COLUMNS)
    frame["game_id"] = np.arange(36) + 10000
    frame["season"] = np.repeat([2020, 2021, 2022], 12)
    frame["scheduled_at"] = pd.to_datetime(frame.season.astype(str) + "-09-01", utc=True)
    frame["primary"], frame["is_final"] = True, True
    frame["home_margin"] = np.tile([-14.0, 7.0, 3.0, -10.0], 9)
    frame["total_points"] = 56.0 + np.tile([0.0, 4.0, -4.0], 12)
    frame["home_win"] = frame.home_margin.gt(0).astype(float)
    return frame


def test_fit_preprocessing_and_calibration_are_origin_local(tmp_path):
    features = training_features()
    previous = prediction_rows(10, 2021)
    previous["home_win"] = np.arange(10) % 2
    previous["pred_margin"] = np.arange(10) - 4
    first = study.fit_predict(features, None, 2022, "baseline", previous, tmp_path / "first")
    artifact = joblib.load(tmp_path / "first/models/fold-2022-baseline.joblib")
    assert artifact["trainingThroughSeason"] == 2021
    assert artifact["calibrationGameIds"] == previous.game_id.tolist()
    expected_medians = features.loc[features.season.lt(2022), pipeline.FEATURE_COLUMNS].median().to_numpy()
    np.testing.assert_allclose(artifact["models"]["margin"].named_steps["imputer"].statistics_, expected_medians)
    future_previous = prediction_rows(10, 2022)
    future_previous["home_win"] = 1
    future_previous["pred_margin"] = 1000000
    changed = features.copy()
    changed.loc[changed.season.eq(2022), ["home_margin", "total_points", "home_win"]] = 999999
    second = study.fit_predict(changed, None, 2022, "baseline", pd.concat([previous, future_previous]), tmp_path / "second")
    pd.testing.assert_frame_equal(first[["pred_margin", "pred_total", "calibratedHomeWinProbability"]],
                                  second[["pred_margin", "pred_total", "calibratedHomeWinProbability"]])


def test_fit_rejects_2026_and_misdated_calibration_donors(tmp_path):
    features = training_features()
    previous = prediction_rows(10, 2021)
    previous["home_win"] = np.arange(10) % 2
    previous.loc[0, "scheduled_at"] = pd.Timestamp("2023-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        study.fit_predict(features, None, 2022, "baseline", previous, tmp_path / "misdated")
    features.loc[0, "season"] = 2026
    with pytest.raises(ValueError, match="2026"):
        study.fit_predict(features, None, 2022, "baseline", previous.iloc[:0], tmp_path / "future")

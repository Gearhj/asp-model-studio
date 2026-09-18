"""Synthetic tests for the isolated research estimator; no retained data access."""

import json

import numpy as np
import pandas as pd
import pytest

from server.sports_cfb_gen1.opponent_strength import (
    DEFAULT_MU, DEFAULT_VENUE, HISTORY_COLUMNS, clear_strength_cache, fit_strength, predict_strength,
)


def games(rows):
    return pd.DataFrame(rows, columns=HISTORY_COLUMNS)


def target(home="A", away="B", neutral=True, season=2024):
    return pd.DataFrame([{"season": season, "home_id": home, "away_id": away, "neutral_site": neutral}])


def test_empty_history_and_unseen_teams_use_explicit_cold_start():
    artifact = fit_strength(games([]), 2024, 4, True)
    prediction = predict_strength(artifact, target(neutral=False)).iloc[0]
    assert prediction.strength_pred_home == DEFAULT_MU + DEFAULT_VENUE
    assert prediction.strength_pred_away == DEFAULT_MU - DEFAULT_VENUE
    assert prediction.home_current_support == prediction.home_prior_support == 0
    assert prediction.home_prior_weight == 1
    assert artifact["teams"] == {} and artifact["train_season_max"] is None
    json.dumps(artifact, allow_nan=False)


def test_reversed_neutral_orientation_reverses_margin_preserves_total():
    history = games([(2024, "A", "B", 38, 18, True)] * 8)
    artifact = fit_strength(history, 2024, 4, False)
    ab = predict_strength(artifact, target()).iloc[0]
    ba = predict_strength(artifact, target("B", "A")).iloc[0]
    assert ab.strength_pred_margin == pytest.approx(-ba.strength_pred_margin)
    assert ab.strength_pred_total == pytest.approx(ba.strength_pred_total)
    home = predict_strength(artifact, target(neutral=False)).iloc[0]
    assert home.strength_pred_margin - ab.strength_pred_margin == pytest.approx(2 * artifact["venue"])
    assert home.strength_pred_total == pytest.approx(ab.strength_pred_total)


def test_target_scores_never_change_predictions_or_fitted_team_universe():
    history = games([(2023, "A", "B", 35, 21, False)])
    artifact = fit_strength(history, 2024, 12, True)
    before = json.dumps(artifact, sort_keys=True)
    targets = pd.concat([target(), target("X", "Y")], ignore_index=True)
    expected = predict_strength(artifact, targets)
    targets["home_score"], targets["away_score"] = [9999, -9999], [np.nan, np.inf]
    pd.testing.assert_frame_equal(expected, predict_strength(artifact, targets))
    assert json.dumps(artifact, sort_keys=True) == before
    assert "X" not in artifact["teams"]


def test_prior_uses_exact_previous_year_without_double_support_shrink():
    history = games([(2023, "A", "B", 40, 20, True)] * 4)
    previous = fit_strength(history, 2023, 4, False)
    current = fit_strength(history, 2024, 4, False)
    a = current["teams"]["A"]
    assert a["prior_offense_mean"] == pytest.approx(2 / 3 * previous["teams"]["A"]["offense"])
    assert a["offense"] == a["prior_offense_mean"]
    assert a["prior_support"] == 4 and a["current_support"] == 0
    after_gap = fit_strength(history, 2025, 4, False)
    assert "A" not in after_gap["teams"]
    assert predict_strength(after_gap, target(season=2025)).iloc[0].home_prior_support == 0


def test_team_missing_previous_year_resets_prior_when_it_returns():
    history = games([(2022, "A", "B", 50, 0, True), (2023, "C", "D", 25, 25, True), (2024, "A", "C", 30, 20, True)])
    artifact = fit_strength(history, 2024, 4, False)
    assert artifact["teams"]["A"]["prior_support"] == 0
    assert artifact["teams"]["A"]["prior_offense_mean"] == 0
    assert artifact["teams"]["C"]["prior_support"] == 1


def test_dynamic_support_earns_precision_reduction_and_more_current_response():
    history = games([(2024, "A", "B", 44, 12, True)] * 8)
    fixed = fit_strength(history, 2024, 12, False)
    dynamic = fit_strength(history, 2024, 12, True)
    fa, da = fixed["teams"]["A"], dynamic["teams"]["A"]
    assert da["effective_prior_precision"] == pytest.approx(12 / 3)
    assert fa["effective_prior_precision"] == 12
    assert da["prior_weight"] < fa["prior_weight"]
    assert predict_strength(dynamic, target()).iloc[0].strength_pred_margin > predict_strength(fixed, target()).iloc[0].strength_pred_margin


def test_globals_only_use_earlier_seasons_and_match_across_ablation():
    history = games([(2023, "A", "B", 35, 21, False), (2024, "A", "B", 70, 0, False)])
    adjusted = fit_strength(history, 2024, 4, True)
    naive = fit_strength(history, 2024, 4, True, False)
    assert adjusted["mu"] == naive["mu"] == 28
    assert adjusted["venue"] == naive["venue"] == pytest.approx((14 + 40 * 1.5) / 42)
    changed = history.copy()
    changed.loc[1, "home_score"] = 1000
    updated = fit_strength(changed, 2024, 4, True)
    assert updated["mu"] == adjusted["mu"] and updated["venue"] == adjusted["venue"]


def test_joint_adjustment_recovers_strength_under_imbalanced_opponents():
    # A and B have identical true offense but A chiefly meets a weak defense.
    offense = {"A": 5, "B": 5, "C": -5, "D": -5}
    defense = {"A": 0, "B": 0, "C": 10, "D": -10}
    rows = []
    for h, a, n in [("A", "C", 30), ("B", "D", 30), ("A", "D", 5), ("B", "C", 5), ("C", "D", 10), ("A", "B", 10)]:
        rows.extend([(2024, h, a, 28 + offense[h] + defense[a], 28 + offense[a] + defense[h], True)] * n)
    history = games(rows)
    adjusted = fit_strength(history, 2024, 4, False)
    naive = fit_strength(history, 2024, 4, False, False)
    adjusted_gap = abs(adjusted["teams"]["A"]["offense"] - adjusted["teams"]["B"]["offense"])
    naive_gap = abs(naive["teams"]["A"]["offense"] - naive["teams"]["B"]["offense"])
    assert adjusted_gap < 0.2 * naive_gap
    unseen_pair = target("A", "B")
    actual_margin = 0
    assert abs(predict_strength(adjusted, unseen_pair).iloc[0].strength_pred_margin - actual_margin) < abs(predict_strength(naive, unseen_pair).iloc[0].strength_pred_margin - actual_margin)


def test_json_roundtrip_and_input_order_are_deterministic():
    history = games([(2023, 1, 2, 40, 21, False), (2024, 2, 3, 24, 28, True), (2024, 1, 3, 35, 31, False)])
    fitted = fit_strength(history, 2024, 4, True)
    assert fitted == fit_strength(history.sample(frac=1, random_state=5), 2024, 4, True)
    restored = json.loads(json.dumps(fitted, allow_nan=False))
    pd.testing.assert_frame_equal(predict_strength(fitted, target(1, 2)), predict_strength(restored, target(1.0, 2.0)))


def test_cached_priors_match_fresh_and_invalidate_on_changed_history_or_config():
    history = games([(2022, "A", "B", 40, 14, False), (2023, "A", "B", 35, 21, False), (2024, "B", "C", 24, 28, True)])
    cached = fit_strength(history, 2024, 4, True)
    clear_strength_cache()
    assert fit_strength(history, 2024, 4, True) == cached
    modified = history.copy()
    modified.loc[0, "home_score"] = 70
    for frame, shrinkage, dynamic, adjusted in [(modified, 4, True, True), (history, 12, True, True), (history, 4, False, True), (history, 4, True, False)]:
        result = fit_strength(frame, 2024, shrinkage, dynamic, adjusted)
        assert result != cached
        clear_strength_cache()
        assert fit_strength(frame, 2024, shrinkage, dynamic, adjusted) == result


@pytest.mark.parametrize("change", ["future", "missing_score", "negative_score", "self_game", "ambiguous_venue"])
def test_invalid_history_fails_closed(change):
    history = games([(2024, "A", "B", 28, 21, False)])
    if change == "future": history.loc[0, "season"] = 2025
    elif change == "missing_score": history.loc[0, "home_score"] = np.nan
    elif change == "negative_score": history.loc[0, "away_score"] = -1
    elif change == "self_game": history.loc[0, "away_id"] = "A"
    else: history["neutral_site"] = "False"
    with pytest.raises(ValueError):
        fit_strength(history, 2024, 4, False)


def test_future_targets_are_not_silently_assigned_old_effects():
    artifact = fit_strength(games([]), 2024, 4, False)
    with pytest.raises(ValueError, match="seasons"):
        predict_strength(artifact, target(season=2025))

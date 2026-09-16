"""Synthetic feature-accounting checks; not basketball assessment evidence."""
from copy import deepcopy

import numpy as np
import pandas as pd

from server.sports_nba_gen1.historical_features import (
    FEATURE_COLUMNS as HISTORICAL_COLUMNS, build_historical_features,
)
from server.sports_nba_gen1.recent_features import (
    FEATURE_COLUMNS, build_recent_features, recent_feature_contract,
)


def game(gid, day, *, home="A", away="B", hs=110, aws=100, season_end=2024, neutral=False):
    return dict(game_id=gid, game_date=day, season_end=season_end, home_team_id=home, away_team_id=away,
                home_team_code=home, away_team_code=away, home_score=hs, away_score=aws,
                neutral_site=neutral,
                orientation="PUBLISHER_FOCAL_AXIS_NO_HOME_CLAIM" if neutral else "SOURCE_HOME_AWAY")


def test_existing_features_unchanged_and_no_target_same_day_or_future_leakage():
    records = [game("old", "2023-10-01"), game("target", "2023-10-03"),
               game("same", "2023-10-03", home="A", away="C"), game("later", "2023-10-05")]
    base, _ = build_historical_features(pd.DataFrame(records))
    rows, audit = build_recent_features(pd.DataFrame(records))
    pd.testing.assert_frame_equal(base, rows.loc[:, base.columns])
    changed = deepcopy(records)
    for row in changed[1:]:
        row["home_score"], row["away_score"] = 10, 200
    other, _ = build_recent_features(pd.DataFrame(changed))
    mask = rows.game_id.isin(["target", "same"])
    pd.testing.assert_frame_equal(rows.loc[mask, FEATURE_COLUMNS], other.loc[mask, FEATURE_COLUMNS])
    assert audit["sameDayTeamAmbiguities"] == [{"gameDate": "2023-10-03", "teams": ["A"]}]
    assert not audit["prospectiveEligible"] and not audit["certifiedHistoricalAvailability"]
    assert len(FEATURE_COLUMNS) == 78 and len(set(FEATURE_COLUMNS)) == 78
    assert set(HISTORICAL_COLUMNS).issubset(FEATURE_COLUMNS)


def test_raw_population_moments_and_first_observation_availability():
    rows, _ = build_recent_features(pd.DataFrame([
        game("one", "2023-10-01", hs=100, aws=90),
        game("two", "2023-10-02", hs=120, aws=100),
        game("three", "2023-10-03"),
    ]))
    one, two, three = rows.iloc[0], rows.iloc[1], rows.iloc[2]
    assert np.isnan(one.home_margin_std) and one.home_prior_fallback_available == 0
    assert np.isnan(two.home_rolling_margin_std) and two.home_variability_supported == 0
    assert three.home_rolling_points_for_std == 10
    assert three.home_rolling_points_allowed_std == 5
    assert three.home_rolling_margin_std == 5
    assert three.home_rolling_total_std == 15
    assert three.home_rolling_margin == 15 and three.home_rolling_total == 205
    assert three.away_rolling_margin == -15 and three.away_rolling_total == 205
    assert three.home_variability_supported == 1
    # Earlier league team margin moments: [10,-10,20,-20], mean0, E[x²]=250.
    expected_mean = 2 * 15 / 12
    expected_second = (2 * 250 + 10 * 250) / 12
    np.testing.assert_allclose(three.home_margin_std, np.sqrt(expected_second - expected_mean**2))


def test_prior_season_shrinkage_gap_and_neutral_history_policy():
    rows, audit = build_recent_features(pd.DataFrame([
        game("old", "2022-04-01", season_end=2022, neutral=True),
        game("new", "2023-10-01"), game("next", "2023-10-02"),
    ]))
    assert not rows.iloc[0].target_eligible and rows.iloc[0].home_court == 0
    assert rows.iloc[1].home_prior_season_games == 0
    assert rows.iloc[1].home_margin == 0  # No immediately prior team season; earlier league fallback.
    assert rows.iloc[1].home_total == 210
    assert rows.iloc[1].home_prior_fallback_available == 1
    assert rows.iloc[1].home_variability_supported == 0
    assert audit["missingSeasonEndYearsWithinRange"] == [2023]
    assert audit["neutralHistoryGames"] == 1
    assert audit["featureContract"]["parentFeatureContract"]["schema"] == "nba-gen1-historical-reduced-features-v1"


def test_last_twenty_window_and_prior_pseudo_game_moment_formula():
    records = [game("prior1", "2023-04-01", season_end=2023, hs=100, aws=90),
               game("prior2", "2023-04-02", season_end=2023, hs=120, aws=100)]
    records += [game(f"current{i}", f"2023-10-{i + 1:02}", hs=101 + i, aws=80) for i in range(22)]
    rows, _ = build_recent_features(pd.DataFrame(records))
    target = rows.iloc[-1]
    values = np.arange(102, 122) - 80  # Twenty predecessors after oldest current game leaves window.
    assert target.home_rolling_games == 20
    np.testing.assert_allclose(target.home_rolling_margin_std, values.std(ddof=0))
    prior_margin = (2 * 15 + 10 * 0) / 12
    expected_margin = (20 * values.mean() + 10 * prior_margin) / 30
    np.testing.assert_allclose(target.home_margin, expected_margin)


def test_contract_is_fixed_and_input_order_is_not_a_time_source():
    source = pd.DataFrame([game("one", "2023-10-01"), game("two", "2023-10-03"), game("three", "2023-10-04")])
    rows, audit = build_recent_features(source)
    reverse, reverse_audit = build_recent_features(source.iloc[::-1])
    pd.testing.assert_frame_equal(rows, reverse)
    assert audit == reverse_audit
    contract = recent_feature_contract()
    assert contract["rollingWindowGames"] == 20 and contract["priorPseudoGames"] == 10
    assert len(contract["sha256"]) == 64 and "possessions" in contract["unavailable"]


def test_cup_dates_change_only_rest_density_and_never_elo_or_score_moments():
    source = pd.DataFrame([game("one", "2023-12-01"), game("two", "2023-12-10")])
    baseline, _ = build_recent_features(source)
    context = [{"game_id": "cup", "game_date": "2023-12-09", "season_end": 2024,
                "team_ids": ["A", "C"], "classification": "NBA_CUP_FINAL_DATE_ONLY"}]
    changed, audit = build_recent_features(source, context_events=context)
    target = changed.iloc[1]
    assert target.home_rest_days == 0 and target.home_back_to_back == 1
    assert target.home_games_last_3_days == 1 and target.home_games_last_7_days == 1
    assert target.home_games_last_14_days == 2 and target.away_games_last_14_days == 1
    assert target.difference_rest_days == -8 and target.difference_games_last_7_days == 1
    calendar_names = {f"{side}_{field}" for side in ("home", "away") for field in
                      ("rest_days", "rest_known", "back_to_back", "games_last_3_days", "games_last_7_days", "games_last_14_days")}
    calendar_names.update(("difference_rest_days", "difference_games_last_7_days"))
    unchanged = [column for column in FEATURE_COLUMNS if column not in calendar_names]
    pd.testing.assert_frame_equal(baseline.loc[:, unchanged], changed.loc[:, unchanged])
    pd.testing.assert_series_equal(baseline.iloc[0], changed.iloc[0])
    assert audit["dateOnlyCalendarContext"]["changedTargetGameIds"] == ["two"]
    assert not audit["dateOnlyCalendarContext"]["outcomesConsumed"]

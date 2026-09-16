"""Synthetic mechanics checks only, never NBA training or assessment evidence."""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from server.sports_nba_gen1.historical_features import (
    EVIDENCE_CLASS, FEATURE_COLUMNS, build_historical_features, historical_feature_contract,
)


def game(gid, day, *, home="A", away="B", hs=110, aws=100, season_end=2024):
    return dict(game_id=gid, game_date=day, season_end=season_end, home_team_id=home, away_team_id=away,
                home_team_code=home, away_team_code=away, home_score=hs, away_score=aws)


def test_target_later_and_same_day_outcomes_do_not_enter_features():
    records = [game("old", "2023-10-01"), game("target", "2023-10-03"),
               game("same", "2023-10-03", home="C", away="D"), game("later", "2023-10-05")]
    first, audit = build_historical_features(pd.DataFrame(records))
    changed = deepcopy(records)
    for row in changed[1:]:
        row["home_score"], row["away_score"] = 10, 200
    second, _ = build_historical_features(pd.DataFrame(changed))
    target_first = first.loc[first.game_id == "target", list(FEATURE_COLUMNS)].reset_index(drop=True)
    target_second = second.loc[second.game_id == "target", list(FEATURE_COLUMNS)].reset_index(drop=True)
    pd.testing.assert_frame_equal(target_first, target_second)
    target = first.set_index("game_id").loc["target"]
    assert target.league_history_games == 1
    assert target.history_latest_game_date == "2023-10-01"
    assert not audit["certifiedHistoricalAvailability"]
    assert not audit["prospectiveEligible"]
    assert EVIDENCE_CLASS in first.evidence_class.unique()


def test_rebuilds_elo_and_preserves_orientation_without_source_forecast():
    records = [game("g1", "2023-10-01"), game("g2", "2023-10-03", home="B", away="A")]
    records[0].update(elo_i=9999, elo_n=-9999, forecast=1.0)
    rows, _ = build_historical_features(pd.DataFrame(records))
    prior_probability = 1 / (1 + 10 ** (-65 / 400))
    update = 20 * (1 - prior_probability)
    np.testing.assert_allclose(rows.home_elo, [1500, 1500 - update])
    np.testing.assert_allclose(rows.away_elo, [1500, 1500 + update])
    assert rows.iloc[1].home_rolling_points_for == 100
    assert rows.iloc[1].away_rolling_points_for == 110
    assert rows.iloc[0].home_score == 110
    assert "forecast" not in rows and "elo_i" not in rows


def test_dates_rest_density_and_permutation_invariance():
    source = pd.DataFrame([game("g1", "2023-10-01"), game("g2", "2023-10-03"), game("g3", "2023-10-04"), game("g4", "2023-10-05")])
    rows, audit = build_historical_features(source)
    reverse, reverse_audit = build_historical_features(source.iloc[::-1])
    pd.testing.assert_frame_equal(rows, reverse)
    assert audit == reverse_audit
    assert rows.iloc[3].home_rest_days == 0
    assert rows.iloc[3].home_back_to_back == 1
    assert rows.iloc[3].home_games_last_3_days == 2
    assert rows.iloc[3].home_games_last_7_days == 3
    assert rows.iloc[0].home_rest_known == 0
    assert np.isnan(rows.iloc[0].home_points_for)
    assert "pace" not in FEATURE_COLUMNS


def test_season_cold_start_support_regression_and_shrinkage():
    records = [game(f"old{i}", f"2023-04-{i+1:02}", season_end=2023) for i in range(5)]
    old, _ = build_historical_features(pd.DataFrame(records + [game("after", "2023-04-08", season_end=2023)]))
    rows, audit = build_historical_features(pd.DataFrame(records + [game("new", "2023-10-01")]))
    target = rows.iloc[-1]
    assert target.home_prior_season_games == 5 and target.home_season_games_played == 0
    assert target.home_history_supported == 1 and target.home_current_season_weight == 0
    assert target.home_points_for == (5 * 110 + 10 * 105) / 15
    np.testing.assert_allclose(target.home_elo, 1500 + (old.iloc[-1].home_elo - 1500) * 2 / 3)
    assert target.season == 2023
    assert audit["unsupportedTargetGames"] == 5
    contract = historical_feature_contract()
    assert len(contract["sha256"]) == 64
    assert "possessions" in contract["unavailable"]


def test_same_day_repeated_team_has_no_invented_order():
    source = pd.DataFrame([game("one", "2023-10-01"), game("two", "2023-10-01", home="A", away="C"), game("next", "2023-10-02")])
    rows, audit = build_historical_features(source)
    assert rows.iloc[:2].home_elo.tolist() == [1500, 1500]
    assert rows.iloc[:2].home_season_games_played.tolist() == [0, 0]
    assert rows.iloc[2].home_season_games_played == 2
    assert audit["sameDayTeamAmbiguities"] == [{"gameDate": "2023-10-01", "teams": ["A"]}]


def test_neutral_axes_remain_history_without_claiming_home_orientation():
    neutral = game("neutral", "2023-10-01")
    neutral.update(neutral_site=True, orientation="PUBLISHER_FOCAL_AXIS_NO_HOME_CLAIM")
    normal = game("after", "2023-10-02")
    normal.update(neutral_site=False, orientation="SOURCE_HOME_AWAY")
    rows, audit = build_historical_features(pd.DataFrame([neutral, normal]))
    assert not rows.iloc[0].target_eligible and rows.iloc[0].home_court == 0
    assert rows.iloc[0].elo_home_win_probability == 0.5
    assert rows.iloc[1].home_elo == 1510 and rows.iloc[1].away_elo == 1490
    assert rows.iloc[1].home_season_games_played == 1
    assert rows.iloc[1].home_back_to_back == 1
    assert rows.iloc[1].home_rolling_points_for == 110
    assert np.isnan(rows.iloc[1].league_mean_home_score)
    assert rows.iloc[1].league_history_games == 1
    assert audit["neutralHistoryGames"] == 1


@pytest.mark.parametrize("change, message", [
    ({"away_team_id": "A"}, "identities must differ"),
    ({"away_score": 110}, "cannot be tied"),
    ({"game_date": "2023-10-01T00:00:00Z"}, "exact YYYY-MM-DD"),
    ({"home_score": 2.5}, "integer counts"),
])
def test_invalid_history_is_not_silently_repaired(change, message):
    row = game("one", "2023-10-01")
    row.update(change)
    with pytest.raises(ValueError, match=message):
        build_historical_features(pd.DataFrame([row]))
    with pytest.raises(ValueError, match="Duplicate game identity"):
        build_historical_features(pd.DataFrame([game("same", "2023-10-01"), game("same", "2023-10-02")]))

"""Synthetic calculation checks only; these fixtures are never a model population."""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from server.sports_nba_gen1.features import FEATURE_COLUMNS, build_features, feature_contract


def game(gid, day, *, home="A", away="B", season=2023, available=None, revision=1, ot=0):
    tipoff = pd.Timestamp(day + "T23:00:00Z")
    row = dict(game_id=gid, season=season, season_type="REGULAR", status="FINAL",
               scheduled_tipoff_utc=tipoff.isoformat(),
               source_available_at_utc=available or (tipoff + pd.Timedelta(hours=3)).isoformat(),
               source_revision=revision, home_team_id=home, away_team_id=away,
               home_score=110, away_score=100, overtime_periods=ot)
    for side, fgm in (("home", 40), ("away", 35)):
        row.update({f"{side}_fgm": fgm, f"{side}_fga": 90, f"{side}_fg3m": 10,
                    f"{side}_ftm": 20, f"{side}_fta": 25, f"{side}_oreb": 10,
                    f"{side}_dreb": 30, f"{side}_tov": 12, f"{side}_minutes": 240+25*ot})
    return row


def target(gid, day, *, home="A", away="B", season=2023):
    return dict(game_id=gid, season=season, season_type="REGULAR", status="SCHEDULED",
                scheduled_tipoff_utc=day+"T23:00:00Z", home_team_id=home, away_team_id=away)


def test_target_and_future_results_are_excluded_and_target_labels_not_read():
    history = [game("g1", "2023-10-01"), game("target", "2023-10-03"), game("future", "2023-10-05")]
    future_target = target("target", "2023-10-03")
    future_target.update(home_score="DO NOT READ", away_fga="DO NOT READ")
    result, audit = build_features(pd.DataFrame(history), pd.DataFrame([future_target]))
    assert result.iloc[0].home_season_games_played == 1
    assert result.iloc[0].league_history_games == 1
    assert audit["targetRows"][0]["eligibleHistoryGames"] == 1
    expected = hashlib.sha256(json.dumps([("g1", 1)], separators=(",", ":")).encode()).hexdigest()
    assert audit["targetRows"][0]["eligibleHistoryIdentitySha256"] == expected
    # One team game is shrunk with ten league-prior pseudo-games (league 105).
    np.testing.assert_allclose(result["home_off_efficiency"], [(110+10*105)/(11*103)*100])


def test_strict_availability_and_late_revision_do_not_rewrite_earlier_features():
    old = game("g1", "2023-10-01")
    revised = game("g1", "2023-10-01", available="2023-10-04T23:00:00Z", revision=2)
    revised.update(home_score=120, home_fgm=45)
    history = pd.DataFrame([old, revised])
    targets = pd.DataFrame([target("before", "2023-10-03"), target("equal", "2023-10-04"), target("after", "2023-10-05")])
    result, audit = build_features(history, targets)
    assert result.home_off_efficiency.iloc[0] == result.home_off_efficiency.iloc[1]
    assert result.home_off_efficiency.iloc[2] > result.home_off_efficiency.iloc[1]
    assert result.home_season_games_played.tolist() == [1, 1, 1]
    assert audit["chronologicalFullReplays"] == 2
    first_only, _ = build_features(pd.DataFrame([old]), targets.iloc[:1])
    pd.testing.assert_frame_equal(result.iloc[:1].reset_index(drop=True), first_only)


def test_orientation_and_overtime_pace_normalization():
    history = pd.DataFrame([game("g1", "2023-10-01", ot=1)])
    rows, _ = build_features(history, pd.DataFrame([target("one", "2023-10-03"), target("two", "2023-10-03", home="B", away="A")]))
    np.testing.assert_allclose(rows.home_pace, [103*48/53]*2)
    assert rows.iloc[0].home_off_efficiency == rows.iloc[1].away_off_efficiency
    assert rows.iloc[0].away_elo == rows.iloc[1].home_elo
    assert rows.iloc[0].home_elo > rows.iloc[0].away_elo
    assert rows.iloc[0].difference_off_efficiency == -rows.iloc[1].difference_off_efficiency


def test_cold_start_is_explicit_and_prior_season_support_is_used():
    history = pd.DataFrame([game(f"old{i}", f"2023-04-{i+1:02}", season=2022) for i in range(5)])
    targets = pd.DataFrame([target("first", "2022-10-01", season=2022), target("next", "2023-10-01")])
    rows, _ = build_features(history, targets)
    assert rows.iloc[0].home_history_supported == 0
    assert np.isnan(rows.iloc[0].home_off_efficiency)
    assert rows.iloc[0].home_rest_known == 0
    assert rows.iloc[1].home_prior_season_games == 5
    assert rows.iloc[1].home_season_games_played == 0
    assert rows.iloc[1].home_current_season_weight == 0
    assert rows.iloc[1].home_history_supported == 1
    assert np.isfinite(rows.iloc[1].home_off_efficiency)


def test_rest_schedule_density_and_order_independent_reproduction():
    history = pd.DataFrame([game("g1", "2023-10-01"), game("g2", "2023-10-03"), game("g3", "2023-10-04")])
    targets = pd.DataFrame([target("later", "2023-10-05"), target("earlier", "2023-10-03")])
    rows, audit = build_features(history, targets)
    shuffled, audit2 = build_features(history.iloc[::-1], targets.iloc[::-1])
    pd.testing.assert_frame_equal(rows, shuffled)
    assert audit == audit2
    assert rows.iloc[1].home_rest_days == 0
    assert rows.iloc[1].home_back_to_back == 1
    assert rows.iloc[1].home_games_last_3_days == 2
    assert rows.iloc[1].home_games_last_7_days == 3
    assert rows.iloc[0].home_season_games_played == 1
    assert set(FEATURE_COLUMNS).issubset(rows.columns)


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(home_team_id="B"),
    lambda r: r.update(home_score=100),
    lambda r: r.update(home_minutes=265),
    lambda r: r.update(source_available_at_utc="2023-10-01T23:00:00Z"),
    lambda r: r.update(source_available_at_utc="2023-10-02 02:00:00"),
    lambda r: r.update(season_type="PLAYOFF"),
])
def test_reject_identity_clock_box_and_scope_errors(mutate):
    record = game("g1", "2023-10-01")
    mutate(record)
    with pytest.raises(ValueError):
        build_features(pd.DataFrame([record]), pd.DataFrame([target("t", "2023-10-03")]))


def test_duplicate_games_and_orientation_aliases_are_not_silently_counted():
    record = game("g1", "2023-10-01")
    with pytest.raises(ValueError, match="Duplicate"):
        build_features(pd.DataFrame([record, record]))
    revised = game("g1", "2023-10-01", revision=2, home="B", away="A")
    with pytest.raises(ValueError, match="orientation"):
        build_features(pd.DataFrame([record, revised]))


def test_contract_identity_and_incremental_update_equal_independent_snapshots():
    contract = feature_contract()
    digest = contract.pop("sha256")
    assert hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest() == digest
    history = pd.DataFrame([game("g1", "2023-10-01"), game("g2", "2023-10-03"), game("g3", "2023-10-04")])
    targets = pd.DataFrame([target("t1", "2023-10-03"), target("t2", "2023-10-05")])
    together, audit = build_features(history, targets)
    assert audit["incrementalUpdates"] == 1
    for index in range(2):
        independent, _ = build_features(history, targets.iloc[index:index+1])
        pd.testing.assert_frame_equal(together.iloc[index:index+1].reset_index(drop=True), independent)


def test_delayed_earlier_game_triggers_same_replay_as_independent_snapshot():
    delayed = game("early", "2023-10-01", available="2023-10-04T23:01:00Z")
    prompt = game("later", "2023-10-03")
    history = pd.DataFrame([delayed, prompt])
    targets = pd.DataFrame([target("t1", "2023-10-04"), target("t2", "2023-10-05")])
    rows, audit = build_features(history, targets)
    independent, _ = build_features(history, targets.iloc[1:])
    assert audit["chronologicalFullReplays"] == 2
    assert rows.home_season_games_played.tolist() == [1, 2]
    pd.testing.assert_frame_equal(rows.iloc[1:].reset_index(drop=True), independent)

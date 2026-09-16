"""Synthetic timing, attribution and identity checks; no data acquisition."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from server.sports_nfl_m1.qb_usage_context import (
    PBP_COLUMNS, aggregate_usage_partition, build_lagged_contexts,
    load_development_usage,
)


def _pbp():
    base = dict(season=2024, season_type="REG", week=1, game_id="g1", game_date="2024-09-01",
                home_team="LA", away_team="SEA", posteam="LA", play_type="pass", qb_dropback=1,
                qb_scramble=0, two_point_attempt=0, passer_player_id="q1", rusher_player_id=None)
    rows = [{**base, "play_id": i} for i in range(23)]
    rows[20].update(passer_player_id=None, rusher_player_id="q1", play_type="run", qb_scramble=1)
    rows[21].update(passer_player_id=None)
    rows[22].update(two_point_attempt=1)
    return pd.DataFrame(rows, columns=PBP_COLUMNS)


def _history(game, day, leader="q1", n=25, second=0):
    counts = {leader: n - second}
    if second:
        counts["backup"] = second
    return dict(canonical_game_id=game, game_date=day, season=2024, team_id="LAR",
                available_utc=pd.Timestamp(day, tz="UTC") + pd.Timedelta(days=3),
                dropbacks=n, attributed_dropbacks=n, attribution_fraction=1.0,
                leader_id=leader, actor_counts_json=json.dumps(counts))


def _target(game="target", date="2024-09-22", week=4, cutoff=None):
    row = dict(canonical_game_id=game, game_date=date, season=2024, week=week,
               canonical_home_team_id="LAR", canonical_away_team_id="SEA")
    if cutoff:
        row["forecast_cutoff_utc"] = cutoff
    return row


def test_scramble_and_unknown_actor_accounting():
    frame = aggregate_usage_partition(_pbp(), expected_season=2024)
    own = frame.loc[frame.team_id.eq("LAR")].iloc[0]
    assert own.dropbacks == 22
    assert own.attributed_dropbacks == 21
    assert own.unattributed_dropbacks == 1
    assert json.loads(own.actor_counts_json) == {"q1": 21}
    assert frame.loc[frame.team_id.eq("SEA"), "dropbacks"].iloc[0] == 0


def test_stable_mixed_and_unknown_are_prior_only():
    history = pd.DataFrame([_history("p1", "2024-09-01"), _history("p2", "2024-09-08"),
                            _history("target", "2024-09-22", "future")])
    first = build_lagged_contexts(pd.DataFrame([_target()]), history).iloc[0]
    assert first.home_context == "STABLE" and first.away_context == "UNKNOWN"
    assert json.loads(first.home_details_json)["priorGameIds"] == ["p1", "p2"]
    history.loc[history.canonical_game_id.eq("p2"), ["leader_id", "actor_counts_json"]] = ["q2", '{"q2":25}']
    assert build_lagged_contexts(pd.DataFrame([_target()]), history).iloc[0].home_context == "MIXED"
    history.loc[history.canonical_game_id.eq("p2"), "attribution_fraction"] = .5
    assert build_lagged_contexts(pd.DataFrame([_target()]), history).iloc[0].home_context == "UNKNOWN"


def test_strict_cutoff_and_slate_atomicity():
    history = pd.DataFrame([_history("p1", "2024-09-01"), _history("p2", "2024-09-08")])
    history.loc[history.canonical_game_id.eq("p2"), "available_utc"] = pd.Timestamp("2024-09-19T04:00Z")
    targets = pd.DataFrame([_target("early", "2024-09-19", 4), _target("late", "2024-09-22", 4)])
    result = build_lagged_contexts(targets, history)
    assert result.home_context.tolist() == ["UNKNOWN", "UNKNOWN"]
    assert all(json.loads(value)["priorGameIds"] == ["p1"] for value in result.home_details_json)


def test_same_season_and_two_game_minimum():
    history = pd.DataFrame([_history("old", "2024-01-01"), _history("p1", "2024-09-01")])
    history.loc[history.canonical_game_id.eq("old"), "season"] = 2023
    result = build_lagged_contexts(pd.DataFrame([_target()]), history).iloc[0]
    assert result.home_context == "UNKNOWN"
    assert json.loads(result.home_details_json)["priorGameIds"] == ["p1"]


def test_protected_source_rejected_before_open(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("no source may be opened for a rejected season")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    with pytest.raises(ValueError, match="Development"):
        load_development_usage(Path("irrelevant"), seasons=[2025])


def test_duplicate_play_and_partition_identity_rejected():
    frame = _pbp()
    with pytest.raises(ValueError, match="duplicate"):
        aggregate_usage_partition(pd.concat([frame, frame.iloc[:1]]), expected_season=2024)
    with pytest.raises(ValueError, match="different season"):
        aggregate_usage_partition(frame, expected_season=2023)

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd

from server.sports_nfl_m1 import prospective_shadow as P


def test_rolling_selector_is_bounded_and_never_selects_postkickoff() -> None:
    cutoff = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)
    targets = [
        {"id": "started", "game_date": "2026-09-08", "scheduled_start_utc": cutoff - timedelta(seconds=1)},
        {"id": "inside", "game_date": "2026-09-09", "scheduled_start_utc": cutoff + timedelta(hours=1)},
        {"id": "boundary", "game_date": "2026-09-16", "scheduled_start_utc": cutoff + timedelta(days=7)},
        {"id": "outside", "game_date": "2026-09-16", "scheduled_start_utc": cutoff + timedelta(days=7, seconds=1)},
    ]
    selected = P._select_slate_targets(
        targets,
        slate_date=None,
        next_slate_only=False,
        rolling_window_days=7,
        as_of=cutoff,
    )
    assert [item["id"] for item in selected] == ["inside", "boundary"]


def test_completed_history_cutoff_excludes_unfinished_target_and_future_games() -> None:
    rows = pd.DataFrame(
        [
            {"canonical_game_id": "prior", "season": 2026, "game_date": date(2026, 9, 3), "team_id": "SEA", "completed": True},
            {"canonical_game_id": "unfinished", "season": 2026, "game_date": date(2026, 9, 4), "team_id": "SEA", "completed": False},
            {"canonical_game_id": "target", "season": 2026, "game_date": date(2026, 9, 10), "team_id": "SEA", "completed": True},
            {"canonical_game_id": "future", "season": 2026, "game_date": date(2026, 9, 17), "team_id": "SEA", "completed": True},
        ]
    )
    for metric in P.ROLLING_METRICS:
        rows[metric] = 1.0
    history = P._team_daily(rows, "SEA", pd.Timestamp("2026-09-10"))
    assert history["games_on_date"].sum() == 1
    assert history["game_date"].dt.date.tolist() == [date(2026, 9, 3)]

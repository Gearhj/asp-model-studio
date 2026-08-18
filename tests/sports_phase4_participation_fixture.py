from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pyarrow as pa

from server.sports_phase4.participation_features import (
    BuiltParticipationFeatureViews,
    build_participation_views_from_tables,
)


_SEASON_DATES: dict[int, tuple[str, ...]] = {
    2022: ("2022-09-01",),
    2023: ("2023-04-01", "2023-04-10", "2023-05-01", "2023-06-01"),
    2024: ("2024-04-01", "2024-04-10", "2024-05-01", "2024-06-01"),
    2025: ("2025-04-01", "2025-04-10", "2025-05-01", "2025-06-01"),
}


def _governance() -> dict[str, bool]:
    return {
        "historical_reconstruction": True,
        "available_only_after_game_final": True,
        "future_evidence_allowed": False,
        "strict_same_game_pregame_eligible": False,
        "strict_prior_eligible_after_game_final": True,
        "enhanced_research_eligible": True,
    }


def _batting_rows(
    *,
    incomplete_lineup_game: bool,
    target_only_batter: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for season, dates in _SEASON_DATES.items():
        for date_index, game_date in enumerate(dates):
            game_id = f"fixture-game-{season}-{date_index + 1}"
            for team_index, team_id in enumerate(("TEAM_A", "TEAM_B")):
                rotation = (date_index + team_index + season) % 12
                starters = [(rotation + offset) % 12 for offset in range(9)]
                order_by_player = {
                    player_index: order
                    for order, player_index in enumerate(starters, start=1)
                }
                for player_index in range(12):
                    started = player_index in order_by_player
                    batting_order = order_by_player.get(player_index)
                    if (
                        incomplete_lineup_game
                        and season == 2024
                        and date_index == 0
                        and team_id == "TEAM_A"
                        and batting_order == 9
                    ):
                        batting_order = None
                    rows.append(
                        {
                            "game_id": game_id,
                            "game_date": game_date,
                            "season": season,
                            "team_id": team_id,
                            "player_id": (
                                f"raw-batter-target-only-{team_id}"
                                if target_only_batter
                                and season >= 2023
                                and player_index == 11
                                else f"raw-batter-{team_id}-{player_index}"
                            ),
                            "final_available_date": game_date,
                            **_governance(),
                            "actual_starting_lineup": started,
                            "actual_batting_order": batting_order,
                            "stat_b_pa": 4 if started else 1,
                        }
                    )
    return rows


def _pitching_row(
    *,
    usage_id: str,
    game_id: str,
    game_date: str,
    season: int,
    team_id: str,
    player_id: str,
    starter: bool,
    bfp: int,
    outs: int,
) -> dict[str, Any]:
    return {
        "usage_id": usage_id,
        "game_id": game_id,
        "game_date": game_date,
        "season": season,
        "team_id": team_id,
        "player_id": player_id,
        "final_available_date": game_date,
        **_governance(),
        "announcement_time_known": False,
        "actual_appearance_target": True,
        "actual_starter_target": starter,
        "stat_p_bfp": bfp,
        "stat_p_ipouts": outs,
    }


def _starter_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for season, dates in _SEASON_DATES.items():
        for date_index, game_date in enumerate(dates):
            game_id = f"fixture-game-{season}-{date_index + 1}"
            for team_index, team_id in enumerate(("TEAM_A", "TEAM_B")):
                pitcher_index = (date_index + team_index) % 2
                rows.append(
                    _pitching_row(
                        usage_id=f"fixture-starter-{season}-{date_index}-{team_id}",
                        game_id=game_id,
                        game_date=game_date,
                        season=season,
                        team_id=team_id,
                        player_id=f"raw-starter-{team_id}-{pitcher_index}",
                        starter=True,
                        bfp=18 + ((date_index + team_index + season) % 10),
                        outs=12 + ((2 * date_index + team_index + season) % 10),
                    )
                )
    return rows


def _bullpen_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for season, dates in _SEASON_DATES.items():
        for date_index, game_date in enumerate(dates):
            game_id = f"fixture-game-{season}-{date_index + 1}"
            for team_index, team_id in enumerate(("TEAM_A", "TEAM_B")):
                # One explicit zero-reliever team-game is retained in the target
                # denominator even though it has no positive source row.
                if season == 2025 and date_index == 3 and team_id == "TEAM_B":
                    continue
                relievers = {
                    (date_index + team_index) % 4,
                    (date_index + team_index + 1) % 4,
                }
                for pitcher_index in sorted(relievers):
                    rows.append(
                        _pitching_row(
                            usage_id=(
                                f"fixture-reliever-{season}-{date_index}-{team_id}-{pitcher_index}"
                            ),
                            game_id=game_id,
                            game_date=game_date,
                            season=season,
                            team_id=team_id,
                            player_id=f"raw-reliever-{team_id}-{pitcher_index}",
                            starter=False,
                            bfp=3 + ((pitcher_index + date_index) % 6),
                            outs=2 + ((pitcher_index + date_index) % 5),
                        )
                    )
    return rows


def _identities(rows: Iterable[dict[str, Any]]) -> tuple[dict[str, str], frozenset[str]]:
    raw_ids = sorted({str(row["player_id"]) for row in rows})
    aliases = {raw_id: f"canonical::{raw_id}" for raw_id in raw_ids}
    return aliases, frozenset(aliases.values())


def build_fixture_views(
    *,
    incomplete_lineup_game: bool = False,
    target_only_batter: bool = False,
) -> BuiltParticipationFeatureViews:
    batting_rows = _batting_rows(
        incomplete_lineup_game=incomplete_lineup_game,
        target_only_batter=target_only_batter,
    )
    starter_rows = _starter_rows()
    bullpen_rows = _bullpen_rows()
    aliases, dimensions = _identities([*batting_rows, *starter_rows, *bullpen_rows])
    return build_participation_views_from_tables(
        pa.Table.from_pylist(batting_rows),
        pa.Table.from_pylist(starter_rows),
        pa.Table.from_pylist(bullpen_rows),
        retrosheet_aliases=aliases,
        dimension_uuids=dimensions,
        dynamic_state=None,
        fixture_mode=True,
        source_partition_ids=(
            "fixture:bullpen-usage",
            "fixture:player-game-batting",
            "fixture:starter-usage",
        ),
    )


__all__ = ["build_fixture_views"]

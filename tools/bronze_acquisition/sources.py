"""Per-source partition planners and URL builders for Bronze acquisition. NO ASP imports. Every planner is
year-bounded (2019-2024); the safety layer independently refuses any 2025/2026 date."""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from dataclasses import dataclass, field

from . import MAX_YEAR, MIN_YEAR
from .safety import assert_year_allowed, assert_date_allowed

# The Baseball Savant CSV search endpoint SILENTLY TRUNCATES at this row cap. Any chunk must stay under it;
# per-day queries (~9k pitches max) are safe, and the acquirer flags any chunk that reaches the cap.
STATCAST_ROW_CAP = 25000


@dataclass
class Partition:
    partition_id: str
    source: str
    scope: str                 # e.g. "regular" / "postseason" / "release" / "register"
    url: str
    rel_dir: str               # directory under the staging root
    filename: str
    natural_keys: list[str] = field(default_factory=list)
    date_col: str | None = None
    year: int | None = None
    query: dict = field(default_factory=dict)
    is_archive: bool = False


# --------------------------------------------------------------------------- Statcast (Baseball Savant)
_SAVANT = "https://baseballsavant.mlb.com/statcast_search/csv"
# Baseball Savant game-type codes: R = regular season; PO = postseason.
_GAMETYPE = {"regular": "R", "postseason": "PO"}
# In-season months only (skip the off-season; those months have no games and need no request).
_SEASON_MONTHS = (3, 4, 5, 6, 7, 8, 9, 10, 11)


def statcast_url(gametype_code: str, start_date: str, end_date: str) -> str:
    assert_date_allowed(start_date)
    assert_date_allowed(end_date)
    return (f"{_SAVANT}?all=true&type=details&hfGT={gametype_code}%7C"
            f"&game_date_gt={start_date}&game_date_lt={end_date}"
            f"&min_pitches=0&min_results=0&sort_col=pitches&player_event_sort=api_p_release_speed"
            f"&sort_order=desc&min_pas=0")


def statcast_partitions(start_year: int = MIN_YEAR, end_year: int = MAX_YEAR) -> list[Partition]:
    """Per-DAY partitions (the Savant CSV endpoint truncates at STATCAST_ROW_CAP, so a day — ~9k pitches
    max — is the safe unit). Off-days simply return 0 rows and are recorded as empty."""
    parts: list[Partition] = []
    for year in range(assert_year_allowed(start_year), assert_year_allowed(end_year) + 1):
        for scope, code in _GAMETYPE.items():
            months = _SEASON_MONTHS if scope == "regular" else (9, 10, 11)  # postseason is Oct-ish
            for month in months:
                for day in range(1, calendar.monthrange(year, month)[1] + 1):
                    d = f"{year}-{month:02d}-{day:02d}"
                    parts.append(Partition(
                        partition_id=f"statcast/{scope}/year={year}/{d}", source="statcast", scope=scope,
                        url=statcast_url(code, d, d),
                        rel_dir=f"statcast/{scope}/year={year}/month={month:02d}",
                        filename=f"statcast_{scope}_{d}.csv",
                        natural_keys=["game_pk", "at_bat_number", "pitch_number"], date_col="game_date",
                        year=year, query={"gameType": code, "date": d}))
    return parts


# --------------------------------------------------------------------------- Retrosheet
_RETRO = "https://www.retrosheet.org"


def retrosheet_partitions(start_year: int = MIN_YEAR, end_year: int = MAX_YEAR) -> list[Partition]:
    parts: list[Partition] = []
    for year in range(assert_year_allowed(start_year), assert_year_allowed(end_year) + 1):
        parts.append(Partition(partition_id=f"retrosheet/game-logs/gl{year}", source="retrosheet", scope="game-logs",
                               url=f"{_RETRO}/gamelogs/gl{year}.zip", rel_dir="retrosheet/game-logs",
                               filename=f"gl{year}.zip", year=year, is_archive=True))
        parts.append(Partition(partition_id=f"retrosheet/events/{year}eve", source="retrosheet", scope="events",
                               url=f"{_RETRO}/events/{year}eve.zip", rel_dir="retrosheet/events",
                               filename=f"{year}eve.zip", year=year, is_archive=True))
    return parts


# --------------------------------------------------------------------------- Chadwick register (sharded people-*.csv)
_CHADWICK_RAW = "https://raw.githubusercontent.com/chadwickbureau/register/master/data"
_SHARDS = list("0123456789abcdef")


def chadwick_partitions() -> list[Partition]:
    return [Partition(partition_id=f"chadwick/register/people-{s}", source="chadwick", scope="register",
                      url=f"{_CHADWICK_RAW}/people-{s}.csv", rel_dir="chadwick/register",
                      filename=f"people-{s}.csv",
                      natural_keys=["key_uuid"], date_col=None) for s in _SHARDS]


# --------------------------------------------------------------------------- Lahman (baseballdatabank, coverage <= 2024)
_LAHMAN_RAW = "https://raw.githubusercontent.com/chadwickbureau/baseballdatabank/master"
# Source-native core tables. People/Parks are undated; the season tables carry a yearID we bound at Silver.
_LAHMAN_TABLES = {
    "People": ("core", None), "Teams": ("core", "yearID"), "Batting": ("core", "yearID"),
    "Pitching": ("core", "yearID"), "Fielding": ("core", "yearID"), "Appearances": ("core", "yearID"),
    "Managers": ("core", "yearID"), "Parks": ("core", None), "HomeGames": ("core", "yearID"),
    "SeriesPost": ("contrib", "yearID"), "BattingPost": ("contrib", "yearID"), "PitchingPost": ("contrib", "yearID"),
    "FieldingPost": ("contrib", "yearID"),
}


def lahman_partitions() -> list[Partition]:
    parts: list[Partition] = []
    for table, (subdir, date_col) in _LAHMAN_TABLES.items():
        parts.append(Partition(partition_id=f"lahman/release/{table}", source="lahman", scope="release",
                               url=f"{_LAHMAN_RAW}/{subdir}/{table}.csv", rel_dir="lahman/release",
                               filename=f"{table}.csv", date_col=date_col))
    return parts


PLANNERS = {
    "statcast": statcast_partitions,
    "retrosheet": retrosheet_partitions,
    "chadwick": lambda start_year=MIN_YEAR, end_year=MAX_YEAR: chadwick_partitions(),
    "lahman": lambda start_year=MIN_YEAR, end_year=MAX_YEAR: lahman_partitions(),
}

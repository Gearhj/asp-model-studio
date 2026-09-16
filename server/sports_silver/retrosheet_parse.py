"""Deterministic Retrosheet parsers (Phase 7B1, Sections 5 & 6) over the governed 2019-2024 Bronze corpus.

Parses the ACTUAL landed files (verified by inventory): game-logs ``gl{year}.txt`` (161-field GL format) and the
per-team event files ``{team}{year}.EVA/.EVN`` (id / version / info / start / sub / play / com / data records), plus
``{team}{year}.ROS`` rosters and the ``TEAM{year}`` code file. Malformed rows are reported as structured parse errors
(never silently field-shifted); absent values are never fabricated. Read-only: never mutates Bronze.
"""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field
from typing import Any, Iterator

from . import bronze_authority as BA

# Retrosheet game-log (GL) canonical field indices (0-based) for the fields we consume.
GL_DATE, GL_GAMENUM, GL_DOW = 0, 1, 2
GL_VISTEAM, GL_VISLG = 3, 4
GL_HOMETEAM, GL_HOMELG = 6, 7
GL_VISSCORE, GL_HOMESCORE = 9, 10
GL_DAYNIGHT, GL_PARKID = 12, 16
GL_VIS_MANAGER_ID, GL_VIS_MANAGER_NAME = 77, 78
GL_HOME_MANAGER_ID, GL_HOME_MANAGER_NAME = 79, 80
GL_FIELD_COUNT = 161


class RetrosheetParseError(RuntimeError):
    pass


def _decode(raw: bytes) -> list[str]:
    return raw.decode("latin-1").splitlines()


def _csv_split(line: str) -> list[str]:
    # Retrosheet uses simple comma separation with optional double quotes; values contain no embedded commas here.
    return [c.strip().strip('"') for c in line.split(",")]


def _event_partition(manifest, year: int):
    for p in BA.partitions(manifest, source="retrosheet"):
        if p.relative_path == f"retrosheet/events/{year}eve.zip":
            return p
    raise RetrosheetParseError(f"no event archive for {year}")


def _gamelog_partition(manifest, year: int):
    for p in BA.partitions(manifest, source="retrosheet"):
        if p.relative_path == f"retrosheet/game-logs/gl{year}.zip":
            return p
    raise RetrosheetParseError(f"no game-log archive for {year}")


# --------------------------------------------------------------------------- game-logs
@dataclass
class GameLogResult:
    team_games: list[dict[str, Any]]
    rejects: list[dict[str, Any]]
    parsed_games: int = 0


def parse_game_logs(manifest, root, year: int) -> GameLogResult:
    p = _gamelog_partition(manifest, year)
    z = zipfile.ZipFile(p.absolute_path(root))
    member = f"gl{year}.txt"
    text = z.read(member).decode("latin-1")
    # GL is proper CSV with quoted fields that may contain commas -> use a real CSV reader (never naive split).
    rows = list(csv.reader(io.StringIO(text)))
    team_games: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    for i, f in enumerate(rows):
        if not f or (len(f) == 1 and not f[0].strip()):
            continue
        f = [c.strip() for c in f]
        if len(f) != GL_FIELD_COUNT:
            rejects.append({"stage": "gamelog", "member": member, "line": i, "reasonCode": "MALFORMED_SOURCE_ROW",
                            "detail": f"expected {GL_FIELD_COUNT} fields got {len(f)}"})
            continue
        date, gnum = f[GL_DATE], f[GL_GAMENUM]
        home, away = f[GL_HOMETEAM], f[GL_VISTEAM]
        retro_game_id = f"{home}{date}{gnum}"
        # two team-game rows per game (home + away), historical outcome facts
        for is_home, team, opp, score, oppscore, mgr_id, mgr_name in (
            (True, home, away, f[GL_HOMESCORE], f[GL_VISSCORE], f[GL_HOME_MANAGER_ID], f[GL_HOME_MANAGER_NAME]),
            (False, away, home, f[GL_VISSCORE], f[GL_HOMESCORE], f[GL_VIS_MANAGER_ID], f[GL_VIS_MANAGER_NAME])):
            team_games.append({
                "retroGameId": retro_game_id, "gameDate": date, "gameNumber": gnum, "season": date[:4],
                "retroTeamCode": team, "retroOpponentCode": opp, "homeAway": "home" if is_home else "away",
                "runsScored": score, "runsAllowed": oppscore, "parkId": f[GL_PARKID],
                "retroManagerId": mgr_id or None, "retroManagerName": mgr_name or None,
                "sourceArchive": p.partition_id, "sourceMember": member, "sourceLine": str(i)})
    return GameLogResult(team_games=team_games, rejects=rejects, parsed_games=len({tg["retroGameId"] for tg in team_games}))


# --------------------------------------------------------------------------- event files
@dataclass
class EventResult:
    games: list[dict[str, Any]]                 # game identity + info (site/umps/etc.)
    events: list[dict[str, Any]]                # play records
    lineup: list[dict[str, Any]]                # start + sub records
    umpires: list[dict[str, Any]]              # one per (game, umpire position)
    rejects: list[dict[str, Any]]
    stats: dict[str, Any] = field(default_factory=dict)


_UMP_KEYS = {"umphome": "HP", "ump1b": "1B", "ump2b": "2B", "ump3b": "3B", "umplf": "LF", "umprf": "RF"}


def iter_event_members(manifest, root, year: int) -> Iterator[tuple[str, list[str]]]:
    p = _event_partition(manifest, year)
    z = zipfile.ZipFile(p.absolute_path(root))
    for name in sorted(z.namelist()):
        if name.upper().endswith((".EVA", ".EVN")):
            yield name, _decode(z.read(name))


def parse_events(manifest, root, year: int) -> EventResult:
    games: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    lineup: list[dict[str, Any]] = []
    umpires: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    archive = _event_partition(manifest, year).partition_id
    n_play = n_start = n_sub = 0
    for member, lines in iter_event_members(manifest, root, year):
        cur_id: str | None = None
        info: dict[str, str] = {}
        event_seq = 0

        def flush_game():
            if cur_id is None:
                return
            games.append({"retroGameId": cur_id, "gameDate": info.get("date", "").replace("/", ""),
                          "gameNumber": info.get("number"), "retroHomeTeam": info.get("hometeam"),
                          "retroVisTeam": info.get("visteam"), "site": info.get("site"),
                          "startTime": info.get("starttime"), "dayNight": info.get("daynight"),
                          "usedh": info.get("usedh"), "season": (info.get("date", "")[:4] or None),
                          "sourceArchive": archive, "sourceMember": member})
            for key, pos in _UMP_KEYS.items():
                if info.get(key):
                    umpires.append({"retroGameId": cur_id, "umpirePosition": pos, "retroUmpireId": info[key],
                                    "season": info.get("date", "")[:4], "sourceArchive": archive, "sourceMember": member})

        for i, line in enumerate(lines):
            if not line.strip():
                continue
            f = _csv_split(line)
            rt = f[0]
            if rt == "id":
                flush_game()
                cur_id = f[1] if len(f) > 1 else None
                info = {}
                event_seq = 0
            elif rt == "info" and len(f) >= 3:
                info[f[1]] = f[2]
            elif rt == "start" or rt == "sub":
                if cur_id and len(f) >= 6:
                    lineup.append({"retroGameId": cur_id, "recordType": rt, "retroPlayerId": f[1],
                                   "playerName": f[2], "homeAway": "home" if f[3] == "1" else "away",
                                   "battingOrder": f[4], "fieldPosition": f[5], "season": info.get("date", "")[:4],
                                   "sourceArchive": archive, "sourceMember": member, "sourceLine": str(i)})
                    if rt == "start":
                        n_start += 1
                    else:
                        n_sub += 1
                else:
                    rejects.append({"stage": "event", "member": member, "line": i,
                                    "reasonCode": "MALFORMED_SOURCE_ROW", "detail": f"{rt} record malformed"})
            elif rt == "play":
                if cur_id and len(f) >= 7:
                    event_seq += 1
                    events.append({"retroGameId": cur_id, "eventSequence": str(event_seq), "inning": f[1],
                                   "half": f[2], "retroBatterId": f[3], "count": f[4], "pitches": f[5],
                                   "eventText": f[6], "season": info.get("date", "")[:4],
                                   "sourceArchive": archive, "sourceMember": member, "sourceLine": str(i)})
                    n_play += 1
                else:
                    rejects.append({"stage": "event", "member": member, "line": i,
                                    "reasonCode": "MALFORMED_SOURCE_ROW", "detail": "play record malformed"})
            # version/com/data/badj/padj/ladj: retained implicitly via provenance; not separate facts here
        flush_game()
    stats = {"games": len(games), "events": n_play, "lineupRecords": len(lineup), "starts": n_start, "subs": n_sub,
             "umpireRecords": len(umpires), "rejects": len(rejects)}
    return EventResult(games=games, events=events, lineup=lineup, umpires=umpires, rejects=rejects, stats=stats)


# --------------------------------------------------------------------------- team file
def parse_team_file(manifest, root, year: int) -> list[dict[str, str]]:
    p = _event_partition(manifest, year)
    z = zipfile.ZipFile(p.absolute_path(root))
    member = f"TEAM{year}"
    if member not in z.namelist():
        return []
    teams = []
    for line in _decode(z.read(member)):
        if not line.strip():
            continue
        f = _csv_split(line)
        if len(f) >= 4:
            teams.append({"retroTeamCode": f[0], "league": f[1], "city": f[2], "nickname": f[3], "season": str(year)})
    return teams


# --------------------------------------------------------------------------- rosters
def parse_rosters(manifest, root, year: int) -> list[dict[str, str]]:
    p = _event_partition(manifest, year)
    z = zipfile.ZipFile(p.absolute_path(root))
    out = []
    for name in sorted(z.namelist()):
        if not name.upper().endswith(".ROS"):
            continue
        for line in _decode(z.read(name)):
            if not line.strip():
                continue
            f = _csv_split(line)
            if len(f) >= 7:
                out.append({"retroPlayerId": f[0], "nameLast": f[1], "nameFirst": f[2], "bats": f[3],
                            "throws": f[4], "retroTeamCode": f[5], "position": f[6], "season": str(year),
                            "sourceMember": name})
    return out

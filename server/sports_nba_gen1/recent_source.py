"""Identity-gated normalization of Neil Paine's mirrored NBA Elo CSV records.

This reader consumes finalized scores only after a separately frozen population
declaration admits the source identity. Publisher Elo values and probabilities
are ignored. Reconstructed historical inputs remain Category A, not certified
contemporaneous records or future forecasts.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import date, datetime
import hashlib
import io
import json
import re

import pandas as pd

from .historical_source import EVIDENCE_CLASS


_METADATA_FIELDS = {"date", "season", "neutral", "playoff", "team1", "team2", "is_home"}
_OUTCOME_FIELDS = {"score1", "score2"}
_IGNORED_DERIVED_FIELDS = ["elo1_pre", "elo2_pre", "elo_prob1", "elo_prob2", "elo1_post", "elo2_post", "haswon"]


class RecentSourceError(ValueError):
    """An admitted source identity or mirrored final cannot be reconciled."""


def _integer(value: str, field: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.0+)?", value):
        raise RecentSourceError(f"{field} must be a nonnegative integer count")
    return int(value.split(".")[0])


def _date_only(value: str) -> str:
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
            return date.fromisoformat(value).isoformat()
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", value or ""):
            return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
    except ValueError as exc:
        raise RecentSourceError("Invalid recorded calendar date") from exc
    raise RecentSourceError("Source date must be a calendar date without invented tipoff time")


def _team(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{2,4}", value):
        raise RecentSourceError("Team identity must be an unchanged uppercase source code")
    return value


def source_game_key(season_end: int, game_date: str, team1: str, team2: str) -> str:
    """Metadata-only key, never an asserted NBA official game identifier."""
    first, second = sorted((_team(team1), _team(team2)))
    if first == second:
        raise RecentSourceError("A game cannot oppose a team to itself")
    return f"nba-neil:{season_end}:{_date_only(game_date)}:{first}:{second}"


def _declaration(scope: dict, allowed: tuple[int, ...]) -> tuple[dict, dict, dict, dict]:
    if not isinstance(scope, dict):
        raise RecentSourceError("A frozen metadata-only scope declaration is required")
    end_dates = scope.get("regularSeasonEndDates")
    admitted = scope.get("admittedSourceKeysBySeason")
    context_admitted = scope.get("contextOnlySourceKeysBySeason")
    cups = scope.get("cupFinals")
    if (not isinstance(end_dates, dict) or not isinstance(admitted, dict)
            or not isinstance(context_admitted, dict) or not isinstance(cups, list)):
        raise RecentSourceError("Declaration requires regularSeasonEndDates, admittedSourceKeysBySeason, contextOnlySourceKeysBySeason and cupFinals")
    cutoffs, expected, cup_keys, context_expected = {}, {}, {}, {}
    for season in allowed:
        raw_date = end_dates.get(str(season), end_dates.get(season))
        cutoffs[season] = _date_only(raw_date)
        if int(cutoffs[season][:4]) != season:
            raise RecentSourceError("Regular-season cutoff must belong to its season end year")
        keys = admitted.get(str(season), admitted.get(season))
        if (not isinstance(keys, list) or not keys or len(keys) != len(set(keys))
                or any(not isinstance(key, str) or not key.startswith(f"nba-neil:{season}:") for key in keys)):
            raise RecentSourceError("Each allowed season requires unique explicit admitted source keys")
        expected[season] = set(keys)
        keys = context_admitted.get(str(season), context_admitted.get(season))
        if (not isinstance(keys, list) or len(keys) != len(set(keys))
                or any(not isinstance(key, str) or not key.startswith(f"nba-neil:{season}:") for key in keys)):
            raise RecentSourceError("Each allowed season requires explicit context-only source keys, possibly empty")
        context_expected[season] = set(keys)
        if expected[season].intersection(context_expected[season]):
            raise RecentSourceError("Context-only identities must never also enter score history")
    for item in cups:
        if not isinstance(item, dict) or set(("seasonEnd", "date", "teams")).difference(item):
            raise RecentSourceError("Each cup-final declaration requires seasonEnd, date and teams")
        season = item["seasonEnd"]
        teams = item["teams"]
        if isinstance(season, bool) or not isinstance(season, int) or not isinstance(teams, list) or len(teams) != 2:
            raise RecentSourceError("Cup-final metadata must contain an integer season and two source teams")
        key = source_game_key(season, item["date"], *teams)
        if key in cup_keys:
            raise RecentSourceError("Duplicate cup-final declaration")
        cup_keys[key] = item
        if season in expected and key not in context_expected[season]:
            raise RecentSourceError("Declared cup-final dates must appear in context-only source keys")
    expected_cups = {key for key, item in cup_keys.items() if item["seasonEnd"] in allowed}
    if set().union(*context_expected.values()) != expected_cups:
        raise RecentSourceError("Context-only identities must exactly match declared cup-final dates")
    return cutoffs, expected, cup_keys, context_expected


def normalize_recent_source(rawbytes: bytes, allowed_season_ends, scope_declaration: dict) -> tuple[pd.DataFrame, dict]:
    """Reconcile regular-season outcomes and separate cup-final date metadata.

    Extra columns are ignored. Every allowed outcome must bind to a declared
    metadata key. Cup finals supply only dates for rest/density; their scores
    never enter conversion, Elo, score histories, fitting or assessment.
    """
    if not isinstance(rawbytes, bytes):
        raise RecentSourceError("Source must be exact delivered bytes")
    allowed = tuple(sorted(set(allowed_season_ends)))
    if not allowed or any(isinstance(year, bool) or not isinstance(year, int) or year < 1947 for year in allowed):
        raise RecentSourceError("Explicit integer season-end allowlist is required")
    cutoffs, expected, cup_keys, context_expected = _declaration(scope_declaration, allowed)
    try:
        decoded = rawbytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RecentSourceError("Source CSV must be valid UTF-8") from exc
    reader = csv.DictReader(io.StringIO(decoded, newline=""))
    fields = reader.fieldnames or []
    if len(fields) != len(set(fields)) or (_METADATA_FIELDS | _OUTCOME_FIELDS).difference(fields):
        raise RecentSourceError("Source CSV requires unique metadata and score headers")
    grouped, context_grouped, exclusions, source_rows = defaultdict(list), defaultdict(list), Counter(), 0
    for line, raw in enumerate(reader, start=2):
        source_rows += 1
        if None in raw:
            raise RecentSourceError("CSV record has more fields than the declared header")
        season = _integer(raw["season"], "season")
        if season not in allowed:
            exclusions["OUTSIDE_ALLOWED_SEASONS"] += 1
            continue
        day = _date_only(raw["date"])
        if int(day[:4]) not in (season - 1, season):
            raise RecentSourceError("Source date falls outside its season years")
        team1, team2 = _team(raw["team1"]), _team(raw["team2"])
        key = source_game_key(season, day, team1, team2)
        is_cup = key in cup_keys
        if is_cup:
            # Cup outcomes remain uninterpreted, even if their strings are invalid.
            neutral, is_home = _integer(raw["neutral"], "neutral"), _integer(raw["is_home"], "is_home")
            if neutral != 1 or is_home != 0:
                raise RecentSourceError("Cup-final date context requires neutral=1 and is_home=0")
            context_grouped[key].append(dict(game_id=key, game_date=day, season_end=season,
                                             team1=team1, team2=team2, source_line=line))
            continue
        if raw["playoff"] != "":
            exclusions["NON_REGULAR_PLAYOFF_FLAG"] += 1
            continue
        if day > cutoffs[season]:
            exclusions["AFTER_DECLARED_REGULAR_SEASON_END"] += 1
            continue
        if key not in expected[season]:
            raise RecentSourceError(f"Eligible source identity {key} is absent from frozen declaration")
        neutral, is_home = _integer(raw["neutral"], "neutral"), _integer(raw["is_home"], "is_home")
        if neutral not in (0, 1) or is_home not in (0, 1):
            raise RecentSourceError("neutral and is_home metadata must be 0 or 1")
        # First interpretation of final-score fields follows all metadata gates.
        score, opponent = _integer(raw["score1"], "score1"), _integer(raw["score2"], "score2")
        if score == opponent:
            raise RecentSourceError("Final NBA games cannot tie")
        grouped[key].append(dict(game_id=key, season_end=season, game_date=day, team1=team1, team2=team2,
                                 neutral=bool(neutral), is_home=is_home, score=score, opponent=opponent,
                                 source_line=line))
    normalized, aliases, neutral_ids = [], defaultdict(dict), []
    for key, pair in sorted(grouped.items()):
        if len(pair) != 2:
            raise RecentSourceError(f"Game {key} requires exactly two mirrored source rows")
        first, second = pair
        if first["team1"] != second["team2"] or first["team2"] != second["team1"]:
            raise RecentSourceError(f"Game {key} mirrored team identities differ")
        if (first["score"] != second["opponent"] or first["opponent"] != second["score"]):
            raise RecentSourceError(f"Game {key} mirrored scores differ")
        if first["neutral"] != second["neutral"]:
            raise RecentSourceError(f"Game {key} mirrored neutral metadata differs")
        neutral = first["neutral"]
        if neutral:
            if any(row["is_home"] != 0 for row in pair):
                raise RecentSourceError(f"Neutral game {key} must have is_home=0 on both rows")
            focal = min(pair, key=lambda row: row["team1"])
            neutral_ids.append(key)
        else:
            if {row["is_home"] for row in pair} != {0, 1}:
                raise RecentSourceError(f"Game {key} requires one explicit home and one away row")
            focal = next(row for row in pair if row["is_home"] == 1)
        for row in pair:
            aliases[row["season_end"]][row["team1"]] = f"nba-neil:franchise:{row['team1']}"
        normalized.append({
            "game_id": key, "source_game_id": key, "season_end": focal["season_end"], "game_date": focal["game_date"],
            "home_team_id": f"nba-neil:franchise:{focal['team1']}", "away_team_id": f"nba-neil:franchise:{focal['team2']}",
            "home_team_code": focal["team1"], "away_team_code": focal["team2"],
            "home_score": focal["score"], "away_score": focal["opponent"], "neutral_site": neutral,
            "orientation": "PUBLISHER_FOCAL_AXIS_NO_HOME_CLAIM" if neutral else "SOURCE_HOME_AWAY",
            "target_eligible": not neutral, "competition": "NBA_REGULAR_SEASON",
            "source_row_numbers": ",".join(str(row["source_line"]) for row in sorted(pair, key=lambda row: row["team1"])),
            "record_classification": "FINALIZED_SCORE_RECORD_INCLUDING_OVERTIME_NO_STATUS_CLOCK",
            "evidence_class": EVIDENCE_CLASS,
        })
    actual = {row["game_id"] for row in normalized}
    required = set().union(*expected.values())
    if actual != required:
        raise RecentSourceError(f"Frozen admitted identities failed reconciliation: missing={sorted(required - actual)}, unexpected={sorted(actual - required)}")
    context_events = []
    for key, pair in sorted(context_grouped.items()):
        if len(pair) != 2 or pair[0]["team1"] != pair[1]["team2"] or pair[0]["team2"] != pair[1]["team1"]:
            raise RecentSourceError(f"Cup date {key} requires exactly two reciprocal metadata rows")
        row = pair[0]
        context_events.append({"game_id": key, "game_date": row["game_date"], "season_end": row["season_end"],
                               "team_ids": sorted([f"nba-neil:franchise:{row['team1']}", f"nba-neil:franchise:{row['team2']}"]),
                               "classification": "NBA_CUP_FINAL_DATE_ONLY",
                               "source_row_numbers": ",".join(str(item["source_line"]) for item in sorted(pair, key=lambda item: item["team1"]))})
    if set(context_grouped) != set().union(*context_expected.values()):
        raise RecentSourceError("Declared context-only dates failed exact identity reconciliation")
    normalized.sort(key=lambda row: (row["game_date"], row["game_id"]))
    identity_fields = ("game_id", "season_end", "game_date", "home_team_id", "away_team_id", "neutral_site", "orientation", "competition")
    identity_bytes = json.dumps([{field: row[field] for field in identity_fields} for row in normalized],
                                sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    by_season = []
    for season in allowed:
        selected = [row for row in normalized if row["season_end"] == season]
        by_season.append({"seasonEnd": season, "games": len(selected),
                          "orientedTargetGames": sum(row["target_eligible"] for row in selected),
                          "neutralHistoryOnlyGames": sum(row["neutral_site"] for row in selected),
                          "cupFinalDateOnlyEvents": sum(row["season_end"] == season for row in context_events),
                          "firstGameDate": min((row["game_date"] for row in selected), default=None),
                          "lastGameDate": max((row["game_date"] for row in selected), default=None)})
    return pd.DataFrame(normalized), {
        "schema": "nba-gen1-neil-recent-source-reconciliation-v1", "evidenceClass": EVIDENCE_CLASS,
        "sourcePhysicalSha256": hashlib.sha256(rawbytes).hexdigest(), "sourcePhysicalBytes": len(rawbytes),
        "sourceRows": source_rows, "admittedSourceRows": len(normalized) * 2, "admittedGames": len(normalized),
        "metadataExcludedRows": dict(sorted(exclusions.items())), "allowedSeasonEnds": list(allowed),
        "gamesBySeason": by_season, "regularSeasonEndDates": {str(year): value for year, value in cutoffs.items()},
        "aliasToFranchiseBySeason": {str(year): dict(sorted(mapping.items())) for year, mapping in sorted(aliases.items())},
        "neutralHistoryOnlyGameIds": sorted(neutral_ids), "contextOnlyEvents": context_events,
        "contextOnlySourceRows": len(context_events) * 2,
        "cupFinalPolicy": "Dates/team identities only for rest and schedule density; cup-final scores are not converted and cannot enter Elo, score moments, fitting or assessment.",
        "populationIdentitySha256": hashlib.sha256(identity_bytes).hexdigest(),
        "scopeDeclarationSha256": hashlib.sha256(json.dumps(scope_declaration, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
        "gameIdentityDefinition": "nba-neil:<season end>:<calendar date>:<alphabetically first source team>:<second source team>. Constructed stable source identity, not an NBA official identifier.",
        "franchiseIdentityDefinition": "nba-neil:franchise:<unchanged source code>; caller verifies stable alias coverage before admission.",
        "neutralOrientation": "Alphabetically first source team defines internal SIDE1 in home_* fields solely for symmetric history; no actual home-team claim or target assessment.",
        "outcomeAccessOrder": "Allowed season, calendar date, removal of cup-final outcomes, blank playoff flag, declared regular-season cutoff and exact frozen source-key checks all precede score conversion.",
        "ignoredPublisherDerivedFields": _IGNORED_DERIVED_FIELDS,
        "hardFailurePolicy": "Malformed admitted identity, mirror count, orientation, score mismatch or tied final raises RecentSourceError; no silent repair, completeness relaxation or omission.",
        "certifiedHistoricalAvailability": False, "prospectiveEligible": False,
        "timestampPolicy": "Caller retains physical source capture time. Recorded calendar dates are not source publication, revision availability or scheduled tipoff clocks.",
        "missingHistoricalEvidence": ["scheduled_tipoff", "original_schedule_revision", "source_publication_time", "final_status_time", "historical_revision_vintages"],
    }

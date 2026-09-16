"""Identity-first normalization of FiveThirtyEight's historical NBA Elo CSV.

The caller establishes source-use rights and freezes season roles before this
function is called. It preserves original source identity and acquisition-byte
identity, but does not infer historical publication or scheduled tipoff clocks.
Publisher Elo values, forecasts and other fitted outputs are never consumed.
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


EVIDENCE_CLASS = "A_HISTORICAL_FINALIZED_RECORD_RECONSTRUCTION"
_METADATA_FIELDS = {
    "game_id", "lg_id", "_iscopy", "year_id", "date_game", "is_playoffs", "team_id", "fran_id",
    "opp_id", "opp_fran", "game_location",
}
_OUTCOME_FIELDS = {"pts", "opp_pts", "game_result"}
_IGNORED_DERIVED_FIELDS = ["elo_i", "elo_n", "win_equiv", "opp_elo_i", "opp_elo_n", "forecast"]


class HistoricalSourceError(ValueError):
    """Source identities or mirrored finalized outcomes cannot be reconciled."""


def _integer(value: str, field: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise HistoricalSourceError(f"{field} must be an unsigned source integer")
    return int(value)


def _required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise HistoricalSourceError(f"Missing or unnormalized source {field}")
    return value


def _date_only(value: str) -> str:
    try:
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", value or ""):
            return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
            return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HistoricalSourceError("Invalid recorded calendar date") from exc
    raise HistoricalSourceError("date_game must be a source calendar date, without an invented time")


def normalize_source(raw_csv_bytes: bytes, allowed_season_ends) -> tuple[pd.DataFrame, dict]:
    """Normalize admitted NBA regular seasons, reconciling two source rows/game.

    Outcome strings are converted and checked only after each row passes NBA,
    regular-season and allowlisted-season metadata checks. Neutral games retain
    publisher focal axes for history and are explicitly ineligible home/away
    model targets. Population role enforcement remains the caller's obligation.
    """
    if not isinstance(raw_csv_bytes, bytes):
        raise HistoricalSourceError("Source must be exact delivered bytes")
    allowed = tuple(sorted(set(allowed_season_ends)))
    if not allowed or any(isinstance(year, bool) or not isinstance(year, int) or year < 1947 for year in allowed):
        raise HistoricalSourceError("Explicit integer NBA season-end allowlist is required")
    try:
        decoded = raw_csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HistoricalSourceError("Source CSV must be valid UTF-8") from exc
    reader = csv.DictReader(io.StringIO(decoded, newline=""))
    fields = reader.fieldnames or []
    if len(fields) != len(set(fields)):
        raise HistoricalSourceError("CSV headers must be unique")
    missing = (_METADATA_FIELDS | _OUTCOME_FIELDS).difference(fields)
    if missing:
        raise HistoricalSourceError(f"Missing required source columns: {sorted(missing)}")
    grouped, exclusions = defaultdict(list), Counter()
    source_rows = 0
    for source_line, raw in enumerate(reader, start=2):
        source_rows += 1
        if None in raw:
            raise HistoricalSourceError("CSV record has more fields than the declared header")
        # Do not parse score/result fields before the row passes metadata gates.
        if raw["lg_id"] != "NBA":
            exclusions["NON_NBA"] += 1
            continue
        if raw["is_playoffs"] == "1":
            exclusions["PLAYOFFS"] += 1
            continue
        if raw["is_playoffs"] != "0":
            raise HistoricalSourceError("NBA is_playoffs metadata must be 0 or 1")
        season_end = _integer(raw["year_id"], "year_id")
        if season_end not in allowed:
            exclusions["OUTSIDE_ALLOWED_SEASONS"] += 1
            continue
        meta = {field: _required_text(raw[field], field) for field in _METADATA_FIELDS}
        meta.update(season_end=season_end, source_line=source_line, game_date=_date_only(raw["date_game"]))
        if int(meta["game_date"][:4]) not in (season_end - 1, season_end):
            raise HistoricalSourceError("Source date falls outside source season years")
        meta["copy"] = _integer(raw["_iscopy"], "_iscopy")
        if meta["copy"] not in (0, 1):
            raise HistoricalSourceError("_iscopy must be 0 or 1")
        if meta["team_id"] == meta["opp_id"] or meta["fran_id"] == meta["opp_fran"]:
            raise HistoricalSourceError("A source game cannot oppose a team/franchise to itself")
        if meta["game_location"] not in ("H", "A", "N"):
            raise HistoricalSourceError("Source game_location must be H, A or N")
        # This is the first interpretation of actual outcome fields.
        meta["score"] = _integer(raw["pts"], "pts")
        meta["opponent_score"] = _integer(raw["opp_pts"], "opp_pts")
        meta["result"] = raw["game_result"]
        if meta["score"] == meta["opponent_score"]:
            raise HistoricalSourceError("Final NBA game scores cannot tie")
        if meta["result"] != ("W" if meta["score"] > meta["opponent_score"] else "L"):
            raise HistoricalSourceError("Source W/L outcome disagrees with final scores")
        grouped[meta["game_id"]].append(meta)

    normalized, aliases, neutral_ids = [], defaultdict(dict), []
    for source_id, pair in sorted(grouped.items()):
        if len(pair) != 2 or {row["copy"] for row in pair} != {0, 1}:
            raise HistoricalSourceError(f"Game {source_id} must have exactly two rows with _iscopy 0 and 1")
        first, second = pair
        for field in ("season_end", "game_date", "lg_id", "is_playoffs"):
            if first[field] != second[field]:
                raise HistoricalSourceError(f"Game {source_id} mirrored {field} metadata differs")
        if (first["team_id"] != second["opp_id"] or first["opp_id"] != second["team_id"]
                or first["fran_id"] != second["opp_fran"] or first["opp_fran"] != second["fran_id"]):
            raise HistoricalSourceError(f"Game {source_id} mirrored team/franchise identities differ")
        if (first["score"] != second["opponent_score"] or first["opponent_score"] != second["score"]):
            raise HistoricalSourceError(f"Game {source_id} mirrored scores differ")
        locations = [row["game_location"] for row in pair]
        neutral = locations == ["N", "N"]
        if neutral:
            focal = next(row for row in pair if row["copy"] == 0)
        elif set(locations) == {"H", "A"}:
            focal = next(row for row in pair if row["game_location"] == "H")
        else:
            raise HistoricalSourceError(f"Game {source_id} must have mirrored H/A or N/N locations")
        game_id = f"fte:{source_id}"
        if neutral:
            neutral_ids.append(game_id)
        for row in pair:
            alias_map = aliases[row["season_end"]]
            identity = f"fte:franchise:{row['fran_id']}"
            if row["team_id"] in alias_map and alias_map[row["team_id"]] != identity:
                raise HistoricalSourceError("Source alias maps to multiple franchises within one season")
            alias_map[row["team_id"]] = identity
        normalized.append({
            "game_id": game_id, "source_game_id": source_id,
            "season_end": focal["season_end"], "game_date": focal["game_date"],
            "home_team_id": f"fte:franchise:{focal['fran_id']}",
            "away_team_id": f"fte:franchise:{focal['opp_fran']}",
            "home_team_code": focal["team_id"], "away_team_code": focal["opp_id"],
            "home_score": focal["score"], "away_score": focal["opponent_score"],
            "neutral_site": neutral,
            "orientation": "PUBLISHER_FOCAL_AXIS_NO_HOME_CLAIM" if neutral else "SOURCE_HOME_AWAY",
            "target_eligible": not neutral,
            "source_row_numbers": ",".join(str(row["source_line"]) for row in sorted(pair, key=lambda row: row["copy"])),
            "record_classification": "FINALIZED_SCORE_RECORD_INCLUDING_OVERTIME_NO_STATUS_CLOCK",
            "evidence_class": EVIDENCE_CLASS,
        })
    normalized.sort(key=lambda row: (row["game_date"], row["game_id"]))
    by_season = []
    for season in allowed:
        selected = [row for row in normalized if row["season_end"] == season]
        by_season.append({"seasonEnd": season, "games": len(selected),
                          "orientedTargetGames": sum(row["target_eligible"] for row in selected),
                          "neutralHistoryOnlyGames": sum(row["neutral_site"] for row in selected),
                          "firstGameDate": min((row["game_date"] for row in selected), default=None),
                          "lastGameDate": max((row["game_date"] for row in selected), default=None)})
    identity_records = [{key: row[key] for key in ("game_id", "season_end", "game_date", "home_team_id", "away_team_id", "neutral_site", "orientation")} for row in normalized]
    identity_bytes = json.dumps(identity_records, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    reconciliation = {
        "schema": "nba-gen1-fte-historical-source-reconciliation-v1",
        "evidenceClass": EVIDENCE_CLASS,
        "sourcePhysicalSha256": hashlib.sha256(raw_csv_bytes).hexdigest(), "sourcePhysicalBytes": len(raw_csv_bytes),
        "sourceRows": source_rows, "admittedSourceRows": len(normalized) * 2, "admittedGames": len(normalized),
        "metadataExcludedRows": dict(sorted(exclusions.items())), "allowedSeasonEnds": list(allowed),
        "gamesBySeason": by_season,
        "aliasToFranchiseBySeason": {str(season): dict(sorted(mapping.items())) for season, mapping in sorted(aliases.items())},
        "neutralHistoryOnlyGameIds": sorted(neutral_ids), "populationIdentitySha256": hashlib.sha256(identity_bytes).hexdigest(),
        "gameIdentityDefinition": "fte: followed by unchanged publisher game_id. This is a stable source identity, not an asserted NBA.com or NBAAM game key.",
        "franchiseIdentityDefinition": "fte:franchise: followed by exact publisher fran_id; source team_id aliases retained separately by season.",
        "neutralOrientation": "N/N games use _iscopy=0 as SIDE1 in home_* fields solely for symmetric history; no actual home-team claim or home/away target assessment.",
        "outcomeAccessOrder": "NBA/regular/allowed-season metadata gate precedes score/result conversion. Only allowlisted outcomes are interpreted.",
        "ignoredPublisherDerivedFields": _IGNORED_DERIVED_FIELDS,
        "rejectedHardFailures": 0,
        "hardFailurePolicy": "Malformed admitted identities, mismatched mirrors, ambiguous location, conflicting aliases, score mismatch or ties raise HistoricalSourceError; no silent repair or omission.",
        "missingHistoricalEvidence": ["scheduled_tipoff", "original_schedule_revision", "source_publication_time", "final_status_time", "historical_revision_vintages"],
        "timestampPolicy": "Original bytes are acquired at the caller's recorded actual capture time. Source game_date is not a publication or availability clock.",
        "certifiedHistoricalAvailability": False, "prospectiveEligible": False,
    }
    return pd.DataFrame(normalized), reconciliation

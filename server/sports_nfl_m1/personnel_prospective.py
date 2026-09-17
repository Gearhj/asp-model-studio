"""Bounded prospective NFL personnel capture orchestration.

This module never scores a model, loads game outcomes, publishes a forecast, or
writes to AISP/the exchange.  It turns exact provider bytes into an append-only,
outcome-free evidence projection observed at the actual capture time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from .personnel_capture import MAX_REQUESTS_PER_UTC_DAY
from .personnel_evidence import canonical_json_bytes, sha256_json


CONTRACT = "NFL_PERSONNEL_PROSPECTIVE_OWNER_V1"
TASK_NAME = "ASP NFL Personnel Evidence Capture"
OWNER_MARKER = "ASP_NFL_PERSONNEL_EVIDENCE_OWNER_V1"
DEFAULT_RUNTIME_ROOT = Path(r"C:\Users\james\asp-model-studio\.runtime\nfl-personnel-capture")
DEFAULT_DATA_ROOT = Path(r"C:\Users\james\asp-data-staging\nfl\personnel-captures-v1")
DEFAULT_FOUNDATION_ROOT = Path(r"C:\Users\james\asp-data-staging\nfl\foundation-v1")
ET = ZoneInfo("America/New_York")

# The task ticks every fifteen minutes.  Only these local slots can spend the
# network budget.  Monday/Tuesday use one capture; Wednesday through Sunday use
# three, matching the observed once-daily-to-intraday release cadence while
# leaving room under the 28-call hard ceiling.
SLOTS_BY_WEEKDAY = {
    0: ("15:15",), 1: ("15:15",),
    2: ("07:15", "11:15", "15:15"),
    3: ("07:15", "11:15", "15:15"),
    4: ("07:15", "11:15", "15:15"),
    5: ("07:15", "11:15", "15:15"),
    6: ("07:15", "11:15", "15:15"),
}

SAFE_SCHEDULE_COLUMNS = ("game_id", "season", "game_type", "week", "gameday", "gametime", "away_team", "home_team")
PROHIBITED_SCHEDULE_COLUMNS = frozenset({
    "away_score", "home_score", "result", "total", "overtime", "away_moneyline", "home_moneyline",
    "spread_line", "away_spread_odds", "home_spread_odds", "total_line", "under_odds", "over_odds",
    "away_qb_id", "home_qb_id", "away_qb_name", "home_qb_name", "temp", "wind",
})
ALLOWED_FIELDS = {
    "injuries": ("season", "week", "game_type", "team", "gsis_id", "position", "full_name", "report_status", "practice_status", "date_modified"),
    "weekly_rosters": ("season", "week", "game_type", "team", "position", "depth_chart_position", "status", "status_description_abbr", "gsis_id", "espn_id", "full_name", "entry_year", "rookie_year", "draft_club", "draft_number"),
    "depth_charts": ("dt", "team", "gsis_id", "espn_id", "player_name", "pos_grp", "pos_name", "pos_abb", "pos_slot", "pos_rank"),
    "snap_counts": ("game_id", "pfr_game_id", "season", "week", "game_type", "team", "player", "pfr_player_id", "position", "offense_snaps", "defense_snaps", "st_snaps"),
    "players": ("gsis_id", "display_name", "common_first_name", "first_name", "last_name", "short_name", "football_name", "position_group", "position", "ngs_position", "espn_id", "pfr_id"),
    "draft_picks": ("season", "round", "pick", "team", "gsis_id", "pfr_player_id", "cfb_player_id", "pfr_player_name", "position", "college"),
}


def utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def due_slot(now_utc: datetime, completed_slots: Iterable[str], *, grace_minutes: int = 45) -> str | None:
    local = now_utc.astimezone(ET)
    completed = set(completed_slots)
    for hhmm in reversed(SLOTS_BY_WEEKDAY[local.weekday()]):
        hour, minute = map(int, hhmm.split(":"))
        start = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        key = f"{local.date().isoformat()}T{hhmm}:00[{local.tzname()}]"
        if start <= local < start + timedelta(minutes=grace_minutes) and key not in completed:
            return key
    return None


def requests_used_on_utc_day(data_root: Path, day: str) -> int:
    total = 0
    receipts = data_root / "receipts" / "sha256"
    for path in receipts.glob("*/receipt.json") if receipts.exists() else ():
        value = json.loads(path.read_bytes())
        if str(value.get("capturedAtUtc", ""))[:10] == day:
            total += int(value.get("requestCount", 0))
    return total


def load_outcome_free_schedule(foundation_root: Path = DEFAULT_FOUNDATION_ROOT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read only schedule identity/time columns from the registered local object."""
    import pyarrow.parquet as pq

    current_path = foundation_root / "CURRENT.json"
    current_bytes = current_path.read_bytes()
    current = json.loads(current_bytes)
    manifest_path = foundation_root / str(current["relativeManifestPath"])
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    matches = [row for row in manifest["objects"] if row.get("tableName") == "snapshot_nfl_schedule"]
    if len(matches) != 1:
        raise RuntimeError("registered Foundation schedule object is missing or ambiguous")
    entry = matches[0]
    object_dir = foundation_root / "objects" / "sha256" / str(entry["manifestSha256"])
    object_path = object_dir / "object.parquet"
    schema = pq.read_schema(object_path)
    if not set(SAFE_SCHEDULE_COLUMNS).issubset(schema.names):
        raise RuntimeError("registered schedule lacks required identity/time fields")
    table = pq.read_table(object_path, columns=list(SAFE_SCHEDULE_COLUMNS))
    rows = [row for row in table.to_pylist() if int(row.get("season") or 0) == 2026 and row.get("game_type") == "REG"]
    result = []
    for row in rows:
        date = str(row["gameday"])
        clock = str(row.get("gametime") or "00:00")
        kickoff = datetime.fromisoformat(f"{date}T{clock}:00").replace(tzinfo=ET).astimezone(timezone.utc)
        result.append({"eventId": str(row["game_id"]), "season": 2026, "week": int(row["week"]),
                       "awayTeamId": str(row["away_team"]), "homeTeamId": str(row["home_team"]),
                       "kickoffUtc": kickoff.isoformat().replace("+00:00", "Z")})
    result.sort(key=lambda row: (row["kickoffUtc"], row["eventId"]))
    lineage = {"currentPath": str(current_path), "currentSha256": hashlib.sha256(current_bytes).hexdigest(),
               "manifestPath": str(manifest_path), "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
               "objectPath": str(object_path), "objectSha256": hashlib.sha256(object_path.read_bytes()).hexdigest(),
               "readColumns": list(SAFE_SCHEDULE_COLUMNS), "excludedOutcomeAndMarketColumns": sorted(PROHIBITED_SCHEDULE_COLUMNS)}
    return result, lineage


def _read_projected(path: Path, family: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import pyarrow.parquet as pq

    schema = pq.read_schema(path)
    selected = [field for field in ALLOWED_FIELDS[family] if field in schema.names]
    if not selected:
        raise RuntimeError(f"{family} has no admitted fields")
    table = pq.read_table(path, columns=selected)
    rows = table.to_pylist()
    return rows, {"familyId": family, "schemaFields": schema.names, "projectedFields": selected,
                  "schemaFingerprint": sha256_json([{"name": f.name, "type": str(f.type)} for f in schema]),
                  "rowCount": len(rows), "physicalSha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _put(root: Path, kind: str, filename: str, value: Mapping[str, Any]) -> dict[str, Any]:
    raw = canonical_json_bytes(value)
    digest = hashlib.sha256(raw).hexdigest()
    target = root / kind / "sha256" / digest / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != raw:
        raise RuntimeError("content-address collision")
    if not target.exists():
        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_bytes(raw)
        if hashlib.sha256(temp.read_bytes()).hexdigest() != digest:
            raise RuntimeError("staged evidence failed physical verification")
        temp.replace(target)
    return {"path": str(target), "sha256": digest, "byteCount": len(raw)}


def project_capture(*, capture_receipt: Mapping[str, Any], data_root: Path,
                    foundation_root: Path = DEFAULT_FOUNDATION_ROOT) -> dict[str, Any]:
    captured = utc(str(capture_receipt["capturedAtUtc"]))
    schedule, schedule_lineage = load_outcome_free_schedule(foundation_root)
    future = [row for row in schedule if utc(row["kickoffUtc"]) > captured]
    if future:
        next_week = min(int(row["week"]) for row in future)
        games = [row for row in future if int(row["week"]) == next_week]
    else:
        next_week, games = None, []

    projected: dict[str, list[dict[str, Any]]] = {}
    source_summaries = []
    unavailable = []
    for source in capture_receipt["objects"]:
        family = str(source["familyId"])
        if source["disposition"] == "SOURCE_NOT_PUBLISHED":
            unavailable.append(family)
            continue
        rows, summary = _read_projected(Path(str(source["objectPath"])), family)
        projected[family] = rows
        source_summaries.append({**summary, "retrievedAtUtc": source["retrievedAtUtc"],
                                 "sourceObjectSha256": source["physicalSha256"], "disposition": source["disposition"]})

    rosters = projected.get("weekly_rosters", [])
    if next_week is not None:
        rosters = [row for row in rosters if int(row.get("season") or 0) == 2026 and int(row.get("week") or 0) == next_week]
    depth = projected.get("depth_charts", [])
    qbs_by_team: dict[str, list[dict[str, Any]]] = {}
    for row in depth:
        if str(row.get("pos_abb") or row.get("pos_grp") or "").upper() != "QB":
            continue
        qbs_by_team.setdefault(str(row.get("team") or ""), []).append(row)
    roster_ids = {(str(row.get("team") or ""), str(row.get("gsis_id") or "")): row for row in rosters
                  if str(row.get("position") or "").upper() == "QB"}
    game_rows = []
    for game in games:
        teams = []
        for team in (game["awayTeamId"], game["homeTeamId"]):
            candidates = sorted(qbs_by_team.get(team, []), key=lambda row: (int(row.get("pos_rank") or 999), str(row.get("gsis_id") or "")))
            top_rank = int(candidates[0].get("pos_rank") or 999) if candidates else None
            top = [row for row in candidates if int(row.get("pos_rank") or 999) == top_rank]
            if len(top) == 1 and top_rank == 1:
                player_id = str(top[0].get("gsis_id") or "")
                roster = roster_ids.get((team, player_id))
                disposition = "PROBABLE_FROM_CURRENT_DEPTH_CHART" if player_id and roster else "AMBIGUOUS_EXPECTED_QUARTERBACK"
            elif candidates:
                player_id, disposition = None, "AMBIGUOUS_EXPECTED_QUARTERBACK"
            else:
                player_id, disposition = None, "UNAVAILABLE_EXPECTED_QUARTERBACK"
            teams.append({"teamId": team, "expectedQuarterbackDisposition": disposition,
                          "canonicalPlayerId": player_id,
                          "candidatePlayerIds": [str(row.get("gsis_id") or "") for row in candidates[:4]],
                          "confirmedPregame": False})
        kickoff = utc(game["kickoffUtc"])
        availability = []
        for horizon, delta in (("EARLY", timedelta(hours=48)), ("CURRENT", timedelta(hours=6)), ("FINAL_PREGAME", timedelta(minutes=15))):
            cutoff = kickoff - delta
            availability.append({"horizon": horizon, "featureCutoffUtc": cutoff.isoformat().replace("+00:00", "Z"),
                                 "captureEligible": captured <= cutoff,
                                 "disposition": "CAPTURE_AVAILABLE_BY_CUTOFF" if captured <= cutoff else "NO_PROSPECTIVE_EVIDENCE_BEFORE_CUTOFF"})
        game_rows.append({**game, "teams": teams, "availabilityBindings": availability})

    prior_current = data_root / "evidence" / "CURRENT.json"
    predecessor = json.loads(prior_current.read_bytes()).get("evidenceSha256") if prior_current.exists() else None
    evidence = {
        "schemaVersion": "NFL_PERSONNEL_PROSPECTIVE_EVIDENCE_V1", "status": "RESEARCH_EVIDENCE_ONLY",
        "capturedAtUtc": captured.isoformat().replace("+00:00", "Z"), "season": 2026, "week": next_week,
        "weekRole": "DEVELOPMENT" if next_week is not None else None,
        "captureReceiptSha256": hashlib.sha256(canonical_json_bytes(capture_receipt)).hexdigest(),
        "scheduleLineage": schedule_lineage, "sources": source_summaries,
        "unavailableFamilies": sorted(unavailable), "games": game_rows,
        "appendOnlyPredecessorEvidenceSha256": predecessor,
        "authority": {"modelFit": False, "forecastPublication": False, "AISPWrite": False,
                      "exchangeWrite": False, "wagering": False, "outcomeAccess": False},
        "limitations": ["Depth rank is a probable-role signal, not a confirmed starter.",
                        "No target-game participation or schedule outcome fields enter this projection.",
                        "A complete captured week is Development evidence; no Validation/OOT role is assigned."],
    }
    ref = _put(data_root, "evidence", "evidence.json", evidence)
    pointer = canonical_json_bytes({"evidenceSha256": ref["sha256"], "evidencePath": ref["path"]})
    prior_current.parent.mkdir(parents=True, exist_ok=True)
    temp = prior_current.with_suffix(".tmp")
    temp.write_bytes(pointer); temp.replace(prior_current)
    return {"evidence": ref, "week": next_week, "gameCount": len(game_rows),
            "expectedQuarterbackDispositions": {state: sum(team["expectedQuarterbackDisposition"] == state
                for game in game_rows for team in game["teams"])
                for state in ("CONFIRMED_PREGAME", "PROBABLE_FROM_CURRENT_DEPTH_CHART", "AMBIGUOUS_EXPECTED_QUARTERBACK", "UNAVAILABLE_EXPECTED_QUARTERBACK")}}


__all__ = ["CONTRACT", "TASK_NAME", "OWNER_MARKER", "DEFAULT_RUNTIME_ROOT", "DEFAULT_DATA_ROOT",
           "DEFAULT_FOUNDATION_ROOT", "SLOTS_BY_WEEKDAY", "due_slot", "requests_used_on_utc_day",
           "load_outcome_free_schedule", "project_capture"]

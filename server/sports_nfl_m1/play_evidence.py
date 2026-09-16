"""Auditable, physically separated Development play evidence (never Final OOT).

Only pre-play situation columns become model inputs. The descriptions are used
solely to identify an explicit sneak, supported penalty, or recovery location;
neither descriptions nor individual identities survive normalization.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

DEVELOPMENT_SEASONS = tuple(range(2018, 2025))
PLAY_TYPES = ("RUSH", "QB_SNEAK", "QB_SCRAMBLE", "PASS_COMPLETE", "PASS_INCOMPLETE",
              "SACK", "INTERCEPTION", "PUNT", "FIELD_GOAL", "EXTRA_POINT", "TWO_POINT",
              "KICKOFF", "KNEEL", "SPIKE", "PENALTY")
PENALTIES = {"false start", "offside", "defensive offside", "encroachment",
             "neutral zone infraction", "delay of game", "offensive offside"}
SOURCE_COLUMNS = (
    "season game_id game_date week home_team away_team season_type play_id fixed_drive "
    "posteam defteam yardline_100 qtr quarter_seconds_remaining half_seconds_remaining "
    "down ydstogo score_differential play_type desc yards_gained air_yards return_yards "
    "kick_distance touchback interception fumble fumble_lost fumbled_2_team "
    "fumble_recovery_1_yards fumble_recovery_1_team touchdown safety first_down "
    "complete_pass incomplete_pass sack qb_scramble qb_kneel qb_spike rush_attempt "
    "pass_attempt punt_attempt field_goal_attempt extra_point_attempt two_point_attempt "
    "kickoff_attempt field_goal_result extra_point_result two_point_conv_result "
    "penalty penalty_team penalty_yards penalty_type first_down_penalty play_deleted "
    "lateral_reception lateral_rush lateral_return lateral_recovery punt_blocked "
    "own_kickoff_recovery defensive_two_point_attempt defensive_extra_point_attempt "
    "home_score away_score"
).split()


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _flag(row: dict[str, Any], key: str) -> bool:
    return _number(row.get(key)) == 1


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _record(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(payload).hexdigest(), "byteCount": len(payload)}


def classify_play(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return one supported primary category or an explicit exclusion reason."""
    description = _text(row.get("desc"))
    if _flag(row, "play_deleted"):
        return None, "DELETED_PLAY"
    if any(_flag(row, key) for key in ("lateral_reception", "lateral_rush", "lateral_return", "lateral_recovery")):
        return None, "LATERAL_SEQUENCE_UNSUPPORTED"
    if _text(row.get("fumbled_2_team")):
        return None, "MULTIPLE_FUMBLE_UNSUPPORTED"
    if any(_flag(row, key) for key in ("defensive_two_point_attempt", "defensive_extra_point_attempt")):
        return None, "DEFENSIVE_TRY_UNSUPPORTED"
    if _flag(row, "penalty") or row.get("play_type") == "no_play":
        penalty_type = _text(row.get("penalty_type")).lower()
        if (row.get("play_type") == "no_play" and penalty_type in PENALTIES
                and row.get("penalty_team") in (row.get("posteam"), row.get("defteam"))
                and row.get("penalty_team") is not None
                and (_number(row.get("penalty_yards")) or 0) > 0
                and not re.search(r"offset|declined|another penalty|end of (?:half|game)|untimed", description, re.I)
                and not _flag(row, "first_down_penalty")):
            return "PENALTY", None
        return None, "LIVE_OR_AMBIGUOUS_OR_UNSUPPORTED_PENALTY"
    special = row.get("play_type") in ("kickoff", "punt", "field_goal", "extra_point")
    if special and (_flag(row, "fumble") or _flag(row, "punt_blocked")
                    or _flag(row, "own_kickoff_recovery")
                    or re.search(r"onside|muff|blocked|free kick", description, re.I)):
        return None, "ONSIDE_MUFF_BLOCKED_OR_FREE_KICK_UNSUPPORTED"
    if ((_flag(row, "fumble") or _flag(row, "fumble_lost"))
            and any(_flag(row, key) for key in ("interception", "incomplete_pass", "qb_spike"))):
        # An intercepted return can fumble back to the original offense; an
        # aborted/recovered snap can precede an incomplete pass. Neither is one
        # supported ball path or single-possession transition. Completed-pass
        # fumbles remain supported by the explicit recovery-location treatment.
        return None, "COMPOUND_FUMBLE_PASS_SEQUENCE_UNSUPPORTED"
    for flag, kind in (("extra_point_attempt", "EXTRA_POINT"), ("two_point_attempt", "TWO_POINT"),
                       ("kickoff_attempt", "KICKOFF"), ("punt_attempt", "PUNT"),
                       ("field_goal_attempt", "FIELD_GOAL"), ("qb_kneel", "KNEEL"),
                       ("qb_spike", "SPIKE"), ("sack", "SACK"), ("interception", "INTERCEPTION"),
                       ("qb_scramble", "QB_SCRAMBLE")):
        if _flag(row, flag):
            return kind, None
    if _flag(row, "rush_attempt") or row.get("play_type") == "run":
        return ("QB_SNEAK" if re.search(r"\bsneak\b", description, re.I) else "RUSH"), None
    if _flag(row, "complete_pass"):
        return "PASS_COMPLETE", None
    if _flag(row, "incomplete_pass"):
        return "PASS_INCOMPLETE", None
    return None, "ADMINISTRATIVE_OR_UNSUPPORTED_PLAY"


def normalize_partition(frame: pd.DataFrame, *, expected_season: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Normalize one already authorized physical partition, retaining joint labels.

    Clock is elapsed game clock between consecutive live plays in the same
    quarter AND half. We do not cross a period boundary, use drive duration, or
    substitute a fixed median. Zero-clock tries/touchbacks are valid evidence.
    """
    if expected_season not in DEVELOPMENT_SEASONS or not frame["season"].eq(expected_season).all():
        raise ValueError("only a separated Development season is permitted")
    frame = frame.sort_values(["game_id", "play_id"], kind="stable").copy()
    live = frame.loc[frame["play_type"].isin(["run", "pass", "punt", "field_goal", "extra_point", "kickoff", "qb_kneel", "qb_spike"])
                     & ~frame.get("play_deleted", pd.Series(0, index=frame.index)).eq(1)].copy()
    # Penalty rows can occur before the next live snap; find the next physical
    # play rather than pretending an administrative clock marker is a snap.
    next_by_game: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
    for game, group in live.groupby("game_id", sort=False):
        next_by_game[str(game)] = (group["play_id"].to_numpy(float), group["qtr"].to_numpy(float),
                                   group["quarter_seconds_remaining"].to_numpy(float),
                                   group["half_seconds_remaining"].to_numpy(float))
    exclusions: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    evaluation_games = []
    for game, group in frame.groupby("game_id", sort=False):
        first = group.iloc[0]
        evaluation_games.append({"gameId": str(game), "date": str(first["game_date"]),
                                 "season": expected_season, "seasonType": str(first["season_type"]),
                                 "homeTeam": str(first["home_team"]), "awayTeam": str(first["away_team"]),
                                 "homeScore": int(group["home_score"].max()), "awayScore": int(group["away_score"].max()),
                                 "observedDriveCount": int(group.loc[group["posteam"].notna(), "fixed_drive"].nunique()),
                                 "observedPlayCount": int(group["play_type"].isin(["run", "pass", "punt", "field_goal", "extra_point", "kickoff", "qb_kneel", "qb_spike"]).sum())})
    for row in frame.to_dict("records"):
        kind, reason = classify_play(row)
        if kind is None:
            exclusions[str(reason)] += 1
            continue
        if not (_text(row.get("posteam")) and _text(row.get("defteam"))):
            exclusions["MISSING_TEAMS"] += 1
            continue
        quarter = _number(row.get("qtr"))
        yard = _number(row.get("yardline_100"))
        qsec = _number(row.get("quarter_seconds_remaining"))
        hsec = _number(row.get("half_seconds_remaining"))
        if quarter not in (1, 2, 3, 4) or yard is None or not 0 <= yard <= 100 or qsec is None or hsec is None:
            exclusions["OVERTIME_OR_MISSING_PREPLAY_STATE"] += 1
            continue
        if kind not in ("KICKOFF", "EXTRA_POINT", "TWO_POINT") and (_number(row.get("down")) not in (1, 2, 3, 4) or _number(row.get("ydstogo")) is None):
            exclusions["MISSING_DOWN_DISTANCE"] += 1
            continue
        clock = next_by_game.get(str(row["game_id"]))
        following = np.searchsorted(clock[0], float(row["play_id"]), side="right") if clock is not None else 0
        if clock is None or following == len(clock[0]) or clock[1][following] != quarter:
            exclusions["NO_CONSECUTIVE_SAME_PERIOD_CLOCK"] += 1
            continue
        seconds = qsec - clock[2][following]
        if not np.isfinite(seconds) or not 0 <= seconds <= 120 or abs((hsec - clock[3][following]) - seconds) > .001:
            exclusions["INVALID_CONSECUTIVE_LIVE_CLOCK"] += 1
            continue
        yards = _number(row.get("yards_gained"))
        if yards is None:
            exclusions["MISSING_JOINT_YARDAGE"] += 1
            continue
        off, defense = row["posteam"], row["defteam"]
        score_difference = _number(row.get("score_differential"))
        phase = "TRY" if kind in ("EXTRA_POINT", "TWO_POINT") else ("KICKOFF" if kind == "KICKOFF" else "SCRIMMAGE")
        if phase == "KICKOFF":
            off, defense = defense, off
            yard = 100 - yard  # nflverse posteam on kickoffs is the RECEIVING team.
            score_difference = -score_difference if score_difference is not None else None
        if score_difference is None:
            exclusions["MISSING_PREPLAY_SCORE"] += 1
            continue
        air, returns, distance = (_number(row.get(key)) for key in ("air_yards", "return_yards", "kick_distance"))
        fumble, lost = _flag(row, "fumble"), _flag(row, "fumble_lost")
        turnover = kind == "INTERCEPTION" or lost
        turnover_spot = None
        location_status = "NOT_APPLICABLE"
        if kind == "INTERCEPTION":
            turnover_spot = yard - air if air is not None else None
            location_status = "OBSERVED_AIR_YARDS_OFFSET" if air is not None else "UNAVAILABLE"
        elif lost:
            # The recovery spot and return yardage are explicit source evidence;
            # yards_gained alone does not identify the initial fumble location.
            match = re.search(r"RECOVERED by .*? at ([A-Z]{2,3}) (-?\d+)\b", _text(row.get("desc")))
            if match and match[1] in (off, defense):
                turnover_spot = 100 - float(match[2]) if match[1] == off else float(match[2])
                location_status = "EXPLICIT_RECOVERY_SPOT_NOT_INITIAL_FUMBLE_POINT"
            else:
                location_status = "UNAVAILABLE"
            returns = _number(row.get("fumble_recovery_1_yards"))
        if turnover and (turnover_spot is None or returns is None):
            exclusions["TURNOVER_LOCATION_OR_RETURN_UNAVAILABLE"] += 1
            continue
        if kind == "SACK" and yards > 0:
            exclusions["POSITIVE_NET_SACK_FUMBLE_SEQUENCE_UNSUPPORTED"] += 1
            continue
        touchback = _flag(row, "touchback")
        if kind in ("PUNT", "KICKOFF") and distance is None:
            exclusions["MISSING_KICK_DISTANCE"] += 1
            continue
        if kind in ("PUNT", "KICKOFF") and returns is None and not touchback:
            exclusions["MISSING_KICK_RETURN_YARDS"] += 1
            continue
        result_field = {"FIELD_GOAL": "field_goal_result", "EXTRA_POINT": "extra_point_result", "TWO_POINT": "two_point_conv_result"}.get(kind)
        result = _text(row.get(result_field)) if result_field else ""
        if result_field and result not in ("made", "good", "missed", "failed", "failure", "success"):
            exclusions["UNKNOWN_OR_BLOCKED_KICK_TRY_RESULT"] += 1
            continue
        ball_end = turnover_spot if kind == "INTERCEPTION" else yard - yards
        if kind in ("KICKOFF", "PUNT"):
            ball_end = yard - distance
        return_end = turnover_spot + returns if turnover_spot is not None and returns is not None else None
        if kind in ("KICKOFF", "PUNT") and returns is not None:
            return_end = ball_end + returns
        receiving_start = 100 - return_end if kind == "KICKOFF" and not touchback and return_end is not None else None
        records.append({"season": expected_season, "game_id": str(row["game_id"]), "date": str(row["game_date"]),
                        "week": int(row["week"]), "home_team": row["home_team"], "away_team": row["away_team"],
                        "season_type": row["season_type"], "play_id": float(row["play_id"]), "drive_id": _number(row.get("fixed_drive")),
                        "offense_team": off, "defense_team": defense, "phase": phase, "quarter": int(quarter),
                        "quarter_seconds": qsec, "half_seconds": hsec, "down": _number(row.get("down")),
                        "yards_to_go": _number(row.get("ydstogo")), "yardline_100": yard, "score_differential": score_difference,
                        "type": kind, "yards": yards, "seconds": float(seconds), "air_yards": air, "return_yards": returns,
                        "kick_distance": distance, "touchback": touchback, "fumble": fumble, "fumble_lost": lost,
                        "turnover": turnover, "touchdown": _flag(row, "touchdown"), "safety": _flag(row, "safety"),
                        "first_down": _flag(row, "first_down"), "kick_success": result in ("made", "good", "success") if result_field else None,
                        "ball_end_yardline_100": ball_end, "turnover_yardline_100": turnover_spot,
                        "return_end_yardline_100": return_end, "receiving_start_yardline_100": receiving_start,
                        "location_evidence_status": location_status, "penalty_accepted": kind == "PENALTY",
                        "penalty_yards": _number(row.get("penalty_yards")) if kind == "PENALTY" else None,
                        "penalty_offense": row.get("penalty_team") == off if kind == "PENALTY" else None,
                        "penalty_no_play": kind == "PENALTY", "penalty_automatic_first_down": False})
    normalized = pd.DataFrame(records)
    return normalized, {"rawRows": len(frame), "normalizedRows": len(records), "exclusions": dict(exclusions),
                        "evaluationGames": evaluation_games}


def load_development_plays(bronze_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    bronze_root = Path(bronze_root).resolve()
    pointer = json.loads((bronze_root / "current.json").read_bytes())
    manifest_path = (bronze_root / pointer["manifestRelativePath"]).resolve()
    if not manifest_path.is_relative_to(bronze_root):
        raise ValueError("manifest escapes bronze root")
    manifest_ref = _record(manifest_path)
    if manifest_ref["sha256"] != pointer["manifestSha256"]:
        raise ValueError("registered manifest checksum differs")
    manifest = json.loads(manifest_path.read_bytes())
    partitions = [p for p in manifest["partitions"] if p["familyId"] == "play_by_play" and p.get("season") in DEVELOPMENT_SEASONS]
    if len(partitions) != 7 or {p["season"] for p in partitions} != set(DEVELOPMENT_SEASONS):
        raise ValueError("expected exactly seven physically separated Development PBP partitions")
    frames, sources, evaluation_games = [], [], []
    exclusions: Counter[str] = Counter()
    raw_count = 0
    for partition in sorted(partitions, key=lambda p: p["season"]):
        path = (bronze_root / partition["relativePath"]).resolve()
        if not path.is_relative_to(bronze_root) or f"season={partition['season']}" not in path.parts:
            raise ValueError("Development source is not physically separated")
        source = _record(path)
        if source["sha256"] != partition["fileSha256"]:
            raise ValueError("Development source checksum differs")
        source.update({"season": partition["season"], "license": partition["license"]})
        sources.append(source)
        parquet = pq.ParquetFile(path)  # read this file, never a mixed hive dataset
        available = set(parquet.schema_arrow.names)
        columns = [column for column in SOURCE_COLUMNS if column in available]
        frame = parquet.read(columns=columns).to_pandas()
        normalized, audit = normalize_partition(frame, expected_season=partition["season"])
        frames.append(normalized)
        raw_count += audit["rawRows"]
        exclusions.update(audit["exclusions"])
        evaluation_games.extend(audit["evaluationGames"])
    plays = pd.concat(frames, ignore_index=True).sort_values(["date", "game_id", "play_id"], kind="stable").reset_index(drop=True)
    counts = plays["type"].value_counts()
    return plays, {"schemaVersion": "NFL_DEVELOPMENT_PLAY_EVIDENCE_V1", "sources": sources,
                   "registeredManifest": manifest_ref, "seasonsRead": list(DEVELOPMENT_SEASONS), "sealedOotRead": False,
                   "rawRows": raw_count, "playCount": len(plays), "gameCount": int(plays["game_id"].nunique()),
                   "categoryCounts": {kind: int(counts.get(kind, 0)) for kind in PLAY_TYPES}, "exclusions": dict(exclusions),
                   "locationEvidence": plays["location_evidence_status"].value_counts().to_dict(),
                   "evaluationGames": evaluation_games,
                   "evaluationOnlyFields": ["homeScore", "awayScore", "observedDriveCount", "observedPlayCount"],
                   "clockDefinition": "Observed elapsed clock to next live play within the same quarter and half; missing/negative/over120-second intervals excluded; zero is retained.",
                   "limitations": ["No tracking data or individual identities; explicit sneak text only.",
                       "No onside, muff, blocked/free kick, lateral, multiple-fumble, defensive-try or full penalty-code model.",
                       "Clock-qualified regulation donor selection excludes last live plays of a period and may alter rare-play frequencies.",
                       "Interception locations derive from observed air yards; fumble geometry uses an explicit recovery location, not an invented initial fumble point.",
                       "Historical archive retrieval is not proof of archival point-in-time release availability."]}

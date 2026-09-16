"""Narrow, research-only all-prior-start intake; never repairs PA model history.

Retrosheet projection delegates to the frozen risk parser. StatsAPI projection
uses observed starter/substitution/PA facts and independently reconciles BF and
outs. Missing evidence is UNRESOLVED, not an eligible zero-history start.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow.parquet as pq

from server.sports_current_statcast.mlb_starter_survival_data import (
    align_raw_fd1, innings_notation_to_outs, parse_event_member, start_risks,
)
from server.sports_datasets.consumer import canonical_json_bytes, semantic_manifest_sha
from server.sports_phase5.game_replay import event_from_row, replay_game

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "outputs/mlb-starter-duration-paired-research-v1"
SCHEMA = "MLB_STARTER_DURATION_LOCAL_HISTORY_RECONCILIATION_V1"
FD1_SHA = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
FD1 = Path("C:/Users/james/asp-model-exchange/datasets/mlb-fd1") / ("sha256-" + FD1_SHA)
RAW_ROOT = Path("C:/Users/james/ai-sports-predictor/data/raw")
CERTIFIED_SHA = "9d12bb87e31b77c4f088705dd15a713c0b29795fcd9e7e2d32aac4b41420fbc4"
CERTIFIED = ROOT / "outputs/mlb-starter-survival-hierarchical-pa-v1/duration-data/sha256" / CERTIFIED_SHA
HOLD_SHA = "04547a356104206a904f38dfa2049f9c67ee2d1822ef39d67cae9d585d6fb985"
HOLD = ROOT / ".runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256" / (HOLD_SHA + ".json")
CONTEXT_ROOT = Path("C:/Users/james/asp-data-staging/mlb-current-statcast-context-gold-v2")
CONTEXT_SHA = "4c228116951a3505d6a5d955f00cd2b92b35b1ccb85c7c69d11d77828485320e"
CURRENT_IDENTITIES = {
    "664285": "retrosheet:player:valdf001",
    # No Retrosheet identifier exists in the verified dim_player registration.
    "690279": "mlbam:player:690279",
}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _read(path, expected=None, size=None):
    data = Path(path).read_bytes()
    if (expected is not None and _sha(data) != expected) or (size is not None and len(data) != size):
        raise ValueError("Source checksum/bytes mismatch: " + str(path))
    return data


def _ref(path):
    data = _read(path)
    return {"path": str(Path(path).resolve()), "sha256": _sha(data), "bytes": len(data)}


def _write(path, data):
    path = Path(path)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Immutable history conflict")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def _clock(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timezone-required source clock")
    return parsed.astimezone(timezone.utc)


def _retained_archive(directory, expected):
    latest = json.loads((directory / "latest.json").read_text())
    if latest["sha256"] != expected:
        raise ValueError("Retained source revision changed")
    path = RAW_ROOT / latest["content_logical_uri"]
    data = _read(path, expected, latest["content_length"])
    acquisition = RAW_ROOT / latest["manifest_logical_uri"]
    proof = json.loads(acquisition.read_text())
    if proof["sha256"] != expected or proof["http_status"] != 200:
        raise ValueError("Retained acquisition identity mismatch")
    return data, [_ref(path), _ref(acquisition)], latest["completed_at"]


def _held_2025_source_ids():
    hold = json.loads(_read(HOLD, HOLD_SHA))
    if hold["heldRows"] != 56 or len(hold["heldObservations"]) != 56:
        raise ValueError("Frozen hold identity changed")
    wanted = {r["canonicalPaId"]: r for r in hold["heldObservations"] if r["gameDate"].startswith("2025-")}
    manifest_path = CONTEXT_ROOT / "publications/sha256" / CONTEXT_SHA / "manifest.json"
    manifest = json.loads(_read(manifest_path, CONTEXT_SHA))
    bridge, refs = [], [_ref(HOLD), _ref(manifest_path)]
    for part in manifest["partitions"]:
        if part["season"] != 2025:
            continue
        if not "2025-01-01" <= part["minimumDate"] <= part["maximumDate"] <= "2025-12-31":
            raise ValueError("Unsafe identity bridge partition")
        path = CONTEXT_ROOT / part["relativePath"]
        _read(path, part["sha256"], part["byteCount"])
        refs.append(_ref(path))
        table = pq.ParquetFile(path).read(columns=["canonicalPaId", "canonicalGameId", "plate_appearance_id", "game_date"])
        for row in table.to_pylist():
            if row["canonicalPaId"] in wanted:
                w = wanted[row["canonicalPaId"]]
                if (row["canonicalGameId"], row["game_date"]) != (w["canonicalGameId"], w["gameDate"]):
                    raise ValueError("Frozen hold bridge differs")
                bridge.append(row)
    if len(bridge) != len(wanted) or {r["canonicalPaId"] for r in bridge} != set(wanted):
        raise ValueError("Frozen hold bridge incomplete")
    return {r["plate_appearance_id"] for r in bridge}, bridge, refs


def reconcile_retained_2025(*, pitcher_ids=("664285", "690279"), player_identity_map=None):
    """No source requests. Reuse the exact frozen parser and its game checks."""
    from scripts.build_mlb_starter_survival_risk import COLUMNS

    pitcher_ids = tuple(str(p) for p in pitcher_ids)
    identity_map = dict(CURRENT_IDENTITIES if player_identity_map is None else player_identity_map)
    if player_identity_map is not None:
        import re
        if (not pitcher_ids or len(set(pitcher_ids)) != len(pitcher_ids)
                or set(identity_map) != set(pitcher_ids)
                or len(set(identity_map.values())) != len(identity_map)):
            raise ValueError("Explicit player identity map must match the exact unique pitcher scope")
        for pid, canonical in identity_map.items():
            if (not isinstance(pid, str) or not re.fullmatch(r"[1-9][0-9]*", pid)
                    or not isinstance(canonical, str)
                    or not (re.fullmatch(r"retrosheet:player:[a-z][a-z0-9]{7}", canonical)
                            or canonical == "mlbam:player:" + pid)):
                raise ValueError("Explicit player identity map contains an invalid canonical identity")
    if set(pitcher_ids) - set(identity_map):
        raise ValueError("Only the declared initial matchup identity scope is registered")
    raw_bytes, sources, captured = _retained_archive(
        RAW_ROOT / "open-data/retrosheet-event-archives/retrosheet-2025-regular-events",
        "5ece2be6c8ec5b47b9d8d90f2ca533ceca7eee915c7e0997f9bd6d64b879303c")
    log_bytes, log_refs, log_clock = _retained_archive(
        RAW_ROOT / "open-data/retrosheet-auxiliary-downloads/retrosheet-gamelogs-2020-2025",
        "23f4bb079696ce7c931fdc31cff704eb1f669d624fc51259801bea51f830e12c")
    sources += log_refs
    sources += [_ref(Path(__file__)), _ref(ROOT / "server/sports_current_statcast/mlb_starter_survival_data.py")]
    raw, logs = {}, {}
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
        for member in sorted(archive.namelist()):
            if member.upper().endswith((".EVA", ".EVN")):
                games = parse_event_member(archive.read(member).decode("latin1"), member)
                if set(games) & set(raw):
                    raise ValueError("Duplicate raw games")
                raw.update(games)
    with zipfile.ZipFile(io.BytesIO(log_bytes)) as archive:
        member = next(n for n in archive.namelist() if n.lower().endswith("gl2025.txt"))
        for row in csv.reader(io.StringIO(archive.read(member).decode("latin1"))):
            if len(row) != 161:
                raise ValueError("Game log schema differs")
            logs[row[6] + row[0] + row[1]] = {
                "completion": row[13], "homeScore": int(row[10]), "awayScore": int(row[9]),
                "totalOuts": int(row[11]), "starters": {0: "retrosheet:player:" + row[101], 1: "retrosheet:player:" + row[103]}}
    if set(raw) != set(logs):
        raise ValueError("Raw archive/gamelog coverage mismatch")
    selected = {gid: g for gid, g in raw.items() if set(g["starters"].values()) & set(identity_map[p] for p in pitcher_ids)}
    for gid in selected:
        if raw[gid]["starters"] != logs[gid]["starters"]:
            raise ValueError("Declared starter/gamelog identity differs")
    held, hold_bridge, hold_refs = _held_2025_source_ids()
    sources += hold_refs
    manifest_path = FD1 / "sports-dataset-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if semantic_manifest_sha(manifest) != FD1_SHA:
        raise ValueError("FD1 identity differs")
    sources.append(_ref(manifest_path))
    sources += [_ref(FD1 / "source-rights.json"), _ref(FD1 / "attribution.md")]
    groups, usage = {}, []
    for part in manifest["partitions"]:
        if part["season"] != 2025 or part["family"] not in ("play_transition", "starter_usage"):
            continue
        if not "2025-01-01" <= part["minimum_date"] <= part["maximum_date"] <= "2025-12-31":
            raise ValueError("Unsafe source partition")
        path = FD1 / part["package_relative_uri"]
        _read(path, part["file_sha256"], part["byte_count"])
        sources.append(_ref(path))
        columns = COLUMNS if part["family"] == "play_transition" else ["player_id", "retrosheet_game_id", "actual_starter_target", "stat_p_bfp", "stat_p_ipouts", "row_checksum"]
        for row in pq.ParquetFile(path).read(columns=columns).to_pylist():
            if row["retrosheet_game_id"] not in selected:
                continue
            if part["family"] == "play_transition":
                groups.setdefault(row["retrosheet_game_id"], []).append(row)
            elif row["actual_starter_target"] and row["player_id"] in identity_map.values():
                usage.append(row)
    usage_by_id = {(r["retrosheet_game_id"], r["player_id"]): r for r in usage}
    expected = {(gid, pid) for gid, g in selected.items() for pid in g["starters"].values() if pid in identity_map.values()}
    if set(usage_by_id) != expected:
        raise ValueError("FD1/raw candidate starter enumeration differs")
    starts = []
    for gid, game in sorted(selected.items()):
        rows = sorted(groups.get(gid, []), key=lambda r: int(r["play_number"]))
        log, reason, aligned = logs[gid], None, None
        if not rows:
            reason = "FD1_EVENT_LEDGER_MISSING"
        elif game["info"].get("gametype") != "regular" or any(r["game_type"] != "regular" for r in rows):
            reason = "NOT_REGULAR_SEASON"
        elif log["completion"] or any(r["game_suspended"] or r["resumed_segment"] for r in rows):
            reason = "SUSPENDED_RESUMED_WHOLE_GAME_HELD"
        else:
            try:
                aligned = align_raw_fd1(game, rows)
                replay = replay_game([event_from_row(r) for r in rows])
                if replay.classification != "EXACT_REPLAY":
                    reason = "FD1_" + replay.classification
                elif (rows[-1]["home_score_after"], rows[-1]["visiting_score_after"]) != (log["homeScore"], log["awayScore"]):
                    reason = "FINAL_SCORE_GAMELOG_MISMATCH"
                elif sum(int(r["outs_after"]) - int(r["outs_before"]) for r in rows) != log["totalOuts"]:
                    reason = "PITCHING_OUTS_GAMELOG_MISMATCH"
            except ValueError as error:
                reason = str(error)
        for side, pid in game["starters"].items():
            if pid not in (identity_map[p] for p in pitcher_ids):
                continue
            risks = []
            if reason is None:
                risks, summary = start_risks(game, aligned, side, complete=True)
                if any(r["plateAppearanceId"] in held for r in risks):
                    summary.update(eligible=False, endpoint="UNKNOWN", exclusionReason="FROZEN_V18_ELIGIBILITY_HOLD_INTERSECTING_START")
            else:
                summary = {"startId": "retrosheet:game:" + gid + ":" + str(side), "gameId": "retrosheet:game:" + gid,
                           "pitcherId": pid, "gameDate": game["info"]["date"].replace("/", "-"), "homePitcher": side,
                           "eligible": False, "exclusionReason": reason, "endpoint": "UNKNOWN", "totalBf": None, "totalOuts": None}
            u = usage_by_id[(gid, pid)]
            if summary["eligible"] and (summary["totalBf"], summary["totalOuts"]) != (u["stat_p_bfp"], u["stat_p_ipouts"]):
                # Preserve frozen parsed disposition; a differing independent box
                # does not permit numerical repair or a fabricated exclusion.
                summary.update(eligible=False, disposition="UNRESOLVED", unresolvedReasons=["PARSED_STINT_BOX_RECONCILIATION_MISMATCH"])
            summary.setdefault("disposition", "ELIGIBLE" if summary["eligible"] else "EXCLUDED")
            summary.update(completionDate=summary["gameDate"], availableAsOf=max(captured, log_clock),
                           observedAt=max(captured, log_clock), ingestedAt=max(captured, log_clock),
                           sourceHistoryVintage="RETROSPECTIVELY_RETRIEVED_SOURCE_NOT_HISTORICAL_PREGAME", sourceUsageRowChecksum=u["row_checksum"],
                           frozenHoldPaIntersections=[r["plateAppearanceId"] for r in risks if r["plateAppearanceId"] in held])
            starts.append(summary)
    counts = {pid: dict(Counter(s["disposition"] for s in starts if s["pitcherId"] == identity_map[pid])) for pid in pitcher_ids}
    return {"schemaVersion": SCHEMA, "season": 2025, "starts": starts, "sources": sources,
            "enumeration": {"rawGames": len(raw), "gamelogGames": len(logs), "matchingGameIdentities": True,
                            "candidateStarts": len(starts), "fd1StarterUsageCandidates": len(usage), "countsByMlbam": counts},
            "identityUnknownPlayers": [p for p in pitcher_ids if identity_map[p].startswith("mlbam:")],
            "holdIdentityBridge": hold_bridge, "newProviderRequests": 0, "newDownloadedBytes": 0, "costUsd": 0,
            "protectedStartPayloadCount": 0, "limitations": ["Retrosheet-unmapped player absence is not independently certified zero history."]}


def save_reconciliation(result):
    data = canonical_json_bytes(result)
    digest = _sha(data)
    path = RESEARCH / "starter-history/reconciliations/sha256" / digest / "reconciliation.json"
    _write(path, data)
    return {"path": str(path.resolve()), "sha256": digest, "bytes": len(data)}


TERMINAL_EVENTS = frozenset({
    "single", "double", "triple", "home_run", "field_out", "force_out", "fielders_choice",
    "fielders_choice_out", "field_error", "strikeout", "strikeout_double_play", "walk",
    "intent_walk", "hit_by_pitch", "catcher_interf", "sac_bunt", "sac_fly", "sac_fly_double_play",
    "sac_bunt_double_play", "grounded_into_double_play", "double_play", "triple_play", "batter_interference",
    "other_out", "runner_double_play",
})
NON_PA_EVENTS = frozenset({
    "pickoff_1b", "pickoff_2b", "pickoff_3b", "caught_stealing_2b", "caught_stealing_3b",
    "caught_stealing_home", "pickoff_caught_stealing_2b", "pickoff_caught_stealing_3b",
    "pickoff_caught_stealing_home", "stolen_base_2b", "stolen_base_3b", "stolen_base_home",
    "wild_pitch", "passed_ball", "balk", "defensive_indiff", "runner_out", "other_advance",
})


def parse_statsapi_start(feed, *, pitcher_mlbam_id, completion_metadata, source_reference=None):
    """Project one actual start only when equivalent frozen facts are supported.

    This adapter uses source record order, not action wall clocks (which may be
    corrected out of order). A boxscore-only record is deliberately insufficient.
    """
    pid = int(pitcher_mlbam_id)
    metadata = completion_metadata
    # Metadata authorization precedes every access to feed statistics/events.
    day = str(metadata.get("gameDate", ""))
    if "2026-08-14" <= day <= "2026-08-27":
        from server.sports_current_statcast.mlb_starter_duration_quarantine import assert_prospective_source_allowed
        assert_prospective_source_allowed(pid, int(metadata.get("gamePk", 0)), day)
    gid = int(metadata.get("gamePk", 0))
    result = {"startId": f"mlbam:game:{gid}:starter:{pid}", "gameId": f"mlbam:game:{gid}",
              "gamePk": gid, "pitcherMlbamId": str(pid), "pitcherId": CURRENT_IDENTITIES.get(str(pid), f"mlbam:player:{pid}"),
              "gameDate": day, "completionDate": metadata.get("completionDate"),
              "eligible": False, "disposition": "UNRESOLVED", "endpoint": "UNKNOWN",
              "totalBf": None, "totalOuts": None, "exclusionReason": None, "unresolvedReasons": [],
              "sourceReference": source_reference, "sourceMode": "CURRENT_RETRIEVAL_OF_COMPLETED_GAME_NOT_HISTORICAL_PREGAME_VINTAGE"}

    def unresolved(reason):
        result["unresolvedReasons"].append(reason)
        return result

    def exclude(reason):
        result.update(disposition="EXCLUDED", exclusionReason=reason)
        return result

    if metadata.get("suspendedOrResumed") is True:
        return exclude("SUSPENDED_RESUMED_WHOLE_GAME_HELD")
    if (metadata.get("statusFinal") is not True or metadata.get("suspendedOrResumed") is not False
            or metadata.get("completionDate") != day or not metadata.get("evidenceSource")):
        return unresolved("COMPLETE_UNSUSPENDED_GAME_PROOF_MISSING")
    data = feed.get("payload", feed)
    game = data.get("gameData", {})
    if int(data.get("gamePk", 0)) != gid or game.get("datetime", {}).get("officialDate") != day:
        return unresolved("EVENT_DATE_IDENTITY_MISMATCH")
    if game.get("game", {}).get("type") != "R":
        return exclude("NOT_REGULAR_SEASON")
    if any(t.get("sport", {}).get("id") not in (None, 1) for t in game.get("teams", {}).values()):
        return exclude("NOT_MLB_POPULATION")
    if game.get("status", {}).get("abstractGameState") != "Final":
        return unresolved("CENSORED_UNKNOWN_GAME_COMPLETION")
    dt = game.get("datetime", {})
    if any(dt.get(k) for k in ("resumeDate", "resumeDateTime", "resumedFromDate", "rescheduledFromDate")):
        return exclude("SUSPENDED_RESUMED_WHOLE_GAME_HELD")
    live = data.get("liveData", {})
    teams = live.get("boxscore", {}).get("teams", {})
    sides = []
    for side in ("home", "away"):
        player = teams.get(side, {}).get("players", {}).get("ID" + str(pid))
        if player:
            sides.append((side, player))
    if len(sides) != 1:
        return unresolved("PLAYER_TEAM_IDENTITY_MISSING_OR_DUPLICATED")
    side, player = sides[0]
    pitching = player.get("stats", {}).get("pitching", {})
    if pitching.get("gamesStarted") != 1:
        if pitching.get("gamesStarted") == 0:
            return exclude("NOT_A_DECLARED_STARTER")
        return unresolved("DECLARED_STARTER_UNAVAILABLE")
    pitchers = teams[side].get("pitchers", [])
    if not pitchers or pitchers[0] != pid:
        return unresolved("DECLARED_STARTER_FIRST_PITCHER_MISMATCH")
    result["homePitcher"] = int(side == "home")
    plays = live.get("plays", {}).get("allPlays", [])
    if not plays or [p.get("about", {}).get("atBatIndex") for p in plays] != list(range(len(plays))):
        return unresolved("COMPLETE_CONTIGUOUS_EVENT_SEQUENCE_UNAVAILABLE")
    defensive = [p for p in plays if p.get("about", {}).get("isTopInning") == (side == "home")]
    if not defensive or defensive[0].get("matchup", {}).get("pitcher", {}).get("id") != pid:
        return unresolved("DECLARED_STARTER_FIRST_PITCHER_MISMATCH")
    bf, outs, previous_inning, prior_outs = 0, 0, None, 0
    active, replacement, last_kind, changed = pid, False, None, False
    attribution = []
    for play in defensive:
        about, events = play.get("about", {}), play.get("playEvents", [])
        inning = about.get("inning")
        if inning != previous_inning:
            if previous_inning is not None and prior_outs != 3:
                return unresolved("INNING_OUT_SEQUENCE_INCOMPLETE")
            previous_inning, prior_outs = inning, 0
        if [e.get("index") for e in events] != list(range(len(events))):
            return unresolved("PLAY_EVENT_SEQUENCE_INCOMPLETE")
        for i, event in enumerate(events):
            if event.get("details", {}).get("eventType") != "pitching_substitution":
                continue
            incoming = event.get("player", {}).get("id")
            if incoming is None:
                return unresolved("SUBSTITUTION_IDENTITY_MISSING")
            if incoming == pid and active != pid:
                return exclude("STARTER_REENTRY_UNSUPPORTED")
            if active == pid and incoming != pid:
                # Any pitcher delivery or nonzero batter count before replacement
                # marks a within-PA change, even if the official BF is charged back.
                count = event.get("count", {})
                if count.get("balls", 0) or count.get("strikes", 0) or any(e.get("isPitch") for e in events[:i]):
                    return exclude("MID_PA_STARTER_CHANGE")
                if any(e.get("details", {}).get("isOut") for e in events[:i]):
                    return exclude("NON_PA_TERMINAL_STINT_BOUNDARY_UNSUPPORTED")
                if last_kind != "PA":
                    return exclude("NON_PA_TERMINAL_STINT_BOUNDARY_UNSUPPORTED")
                replacement, changed = True, True
            active = incoming
        matchup = play.get("matchup", {}).get("pitcher", {}).get("id")
        if matchup != active:
            return unresolved("UNOBSERVED_PITCHER_REPLACEMENT_OR_ATTRIBUTION")
        event_type = play.get("result", {}).get("eventType")
        complete = about.get("isComplete") is True
        terminal = complete and event_type in TERMINAL_EVENTS
        known_non_pa = event_type in NON_PA_EVENTS
        if event_type in ("other_out", "runner_double_play"):
            # StatsAPI labels both batter outs and runner-only inning-ending
            # plays as type=atBat. Observed participant/base origin disambiguates
            # without borrowing the box BF merely to force agreement.
            batter = play.get("matchup", {}).get("batter", {}).get("id")
            movements = play.get("runners", [])
            batter_terminal = any(r.get("details", {}).get("runner", {}).get("id") == batter
                                  and r.get("movement", {}).get("start") is None
                                  and r.get("movement", {}).get("originBase") is None for r in movements)
            runner_only = bool(movements) and all(r.get("details", {}).get("runner", {}).get("id") != batter
                                                and r.get("movement", {}).get("start") is not None for r in movements)
            if not batter_terminal and not runner_only:
                return unresolved("AMBIGUOUS_OTHER_OUT_BATTER_VS_RUNNER")
            terminal, known_non_pa = complete and batter_terminal, runner_only
        if not terminal and not known_non_pa:
            return unresolved("UNSUPPORTED_PA_TERMINAL_SEMANTICS:" + str(event_type))
        after = play.get("count", {}).get("outs")
        if not isinstance(after, int) or not prior_outs <= after <= 3:
            return unresolved("OUT_SEQUENCE_INCONSISTENT")
        if active == pid:
            if replacement:
                return exclude("STARTER_REENTRY_UNSUPPORTED")
            outs += after - prior_outs
            bf += int(terminal)
            last_kind = "PA" if terminal else "NON_PA"
            attribution.append({"atBatIndex": about["atBatIndex"], "terminalPa": terminal, "outsAdded": after-prior_outs})
        prior_outs = after
    if not bf or last_kind != "PA":
        return exclude("NON_PA_TERMINAL_STINT_BOUNDARY_UNSUPPORTED")
    try:
        box_bf, box_outs = int(pitching["battersFaced"]), int(pitching["outs"])
        if innings_notation_to_outs(pitching["inningsPitched"]) != box_outs:
            return unresolved("BOXSCORE_IP_OUTS_MISMATCH")
    except (KeyError, TypeError, ValueError):
        return unresolved("ATTRIBUTED_STARTER_BF_OUTS_UNAVAILABLE")
    if (bf, outs) != (box_bf, box_outs):
        return unresolved("PARSED_STINT_BOX_RECONCILIATION_MISMATCH")
    final = plays[-1].get("result", {})
    lines = live.get("linescore", {}).get("teams", {})
    for s in ("home", "away"):
        score = final.get(s + "Score")
        if score is None or lines.get(s, {}).get("runs") != score or teams[s].get("teamStats", {}).get("batting", {}).get("runs") != score:
            return unresolved("FINAL_SCORE_RECONCILIATION_MISMATCH")
    result.update(eligible=True, disposition="ELIGIBLE", endpoint="REMOVAL" if changed else "GAME_END",
                  totalBf=bf, totalOuts=outs, attribution=attribution, allCauseRemoval=changed,
                  sourceFinalPlayAt=plays[-1].get("about", {}).get("endTime"),
                  sourceTimestampRaw=data.get("metaData", {}).get("timeStamp"))
    return result


def completion_from_observed_clocks(game, feed):
    """Same-local-date event occurrence plus final schedule, not absent-key proof."""
    day = game["gameDate"]
    if "2026-08-14" <= day <= "2026-08-27":
        from server.sports_current_statcast.mlb_starter_duration_quarantine import assert_prospective_source_allowed
        if not game.get("pitcherMlbamIds"):
            raise ValueError("PROTECTED_START_SCOPED_PITCHER_IDENTITY_REQUIRED")
        for pid in game["pitcherMlbamIds"]:
            assert_prospective_source_allowed(pid, game["gamePk"], day)
    schedule, source = game.get("scheduleMetadata", {}), feed.get("gameData", {})
    dt = source.get("datetime", {})
    proof = {"gamePk": game["gamePk"], "gameDate": day, "completionDate": None,
             "suspendedOrResumed": None, "statusFinal": False, "evidenceSource": None}
    if (schedule.get("gamePk") != game["gamePk"] or schedule.get("officialDate") != day
            or dt.get("officialDate") != day or dt.get("originalDate") != day):
        return proof
    resumed_keys = ("resumeDate", "resumeDateTime", "resumeGameDate", "resumedFrom", "resumedFromDate")
    if any(s.get(k) for s in (schedule, dt) for k in resumed_keys):
        proof["suspendedOrResumed"] = True
        return proof
    final = (schedule.get("status", {}).get("abstractGameState") == "Final"
             and source.get("status", {}).get("abstractGameState") == "Final")
    try:
        zone = ZoneInfo(source["venue"]["timeZone"]["id"])
        plays = feed["liveData"]["plays"]["allPlays"]
        starts = [_clock(p["about"]["startTime"]) for p in plays]
        ends = [_clock(p["about"]["endTime"]) for p in plays]
        if not plays or starts != sorted(starts) or ends != sorted(ends):
            return proof
        days = {t.astimezone(zone).date().isoformat() for t in starts + ends}
        if days != {day}:
            # This can be an ordinary late finish or a resumed game. The adapter
            # does not invent a disposition when date-only evidence is ambiguous.
            proof["observedLocalEventDates"] = sorted(days)
            return proof
    except (KeyError, TypeError, ValueError):
        return proof
    proof.update(statusFinal=final, suspendedOrResumed=False, completionDate=day,
                 evidenceSource="FINAL_SCHEDULE_PLUS_ORIGINAL_DATE_AND_ALL_PA_CLOCKS_SAME_VENUE_LOCAL_DATE",
                 observedFirstPaAt=starts[0].isoformat(), observedLastPaAt=ends[-1].isoformat(),
                 venueTimezone=zone.key,
                 invertedWithinPaClockIndices=[i for i, (s, e) in enumerate(zip(starts, ends)) if s > e],
                 clockCaveat="Within-PA clock inversions are retained, not corrected; native PA order and same-day occurrence proof do not require elapsed durations")
    return proof


def _intake_source(ref, *, protected_game=None):
    path = Path(ref["path"]).resolve()
    if protected_game is not None:
        from server.sports_current_statcast.mlb_starter_duration_quarantine import assert_prospective_source_allowed
        if not protected_game.get("pitcherMlbamIds") or protected_game.get("sourceUse") != "PROSPECTIVE_STARTER_HISTORY_ONLY":
            raise ValueError("PROTECTED_DERIVATIVE_SOURCE_USE_MISMATCH")
        for pid in protected_game["pitcherMlbamIds"]:
            authority = assert_prospective_source_allowed(pid, protected_game["gamePk"], protected_game["gameDate"])
            if protected_game.get("protectedDerivativeAuthority") != authority["authorityRef"]:
                raise ValueError("PROTECTED_DERIVATIVE_AUTHORITY_REFERENCE_MISMATCH")
        root = (RESEARCH / "intake/prospective-only-source-quarantine/objects/sha256").resolve()
    else:
        root = (RESEARCH / "intake/objects/sha256").resolve()
    if not path.is_relative_to(root) or path.name != ref["sha256"] + ".source.json":
        raise ValueError("History source outside restricted content-addressed intake")
    return json.loads(_read(path, ref["sha256"], ref["bytes"]))


def _publish_partial_pointer(manifest_ref):
    """A data pointer is not coverage certification; the consumer checks both."""
    path = RESEARCH / "starter-history/current.json"
    if path.exists():
        old = json.loads(path.read_text())
        old_path = Path(old["path"]).resolve()
        root = (RESEARCH / "starter-history/objects/sha256").resolve()
        if not old_path.is_relative_to(root):
            raise ValueError("Existing history pointer outside research namespace")
        old_manifest = json.loads(_read(old_path, old["sha256"], old["bytes"]))
        if old == manifest_ref:
            return True
        new_manifest = json.loads(_read(manifest_ref["path"], manifest_ref["sha256"], manifest_ref["bytes"]))
        for pid, prior in old_manifest.get("coverageByPlayer", {}).items():
            current = new_manifest.get("coverageByPlayer", {}).get(pid, {})
            if prior.get("allScheduledStartsAccountedFor") is True and (
                    current.get("allScheduledStartsAccountedFor") is not True
                    or current.get("completeThrough", "") < prior.get("completeThrough", "")):
                return False  # Never replace supported evidence with partial/older coverage.
        _write(RESEARCH / "starter-history/pointer-history" / (old["sha256"] + ".json"), canonical_json_bytes(old))
    temp = path.with_name(".current-" + uuid.uuid4().hex + ".tmp")
    _write(temp, canonical_json_bytes(manifest_ref))
    os.replace(temp, path)
    return True


def build_compatible_projection(intake_manifest_path, *, as_of_utc):
    """Produce immutable partial accounting; never certify omitted protected starts."""
    as_of = _clock(as_of_utc)
    path = Path(intake_manifest_path).resolve()
    intake_root = (RESEARCH / "intake/objects/sha256").resolve()
    if not path.is_relative_to(intake_root) or not path.name.endswith(".intake-manifest.json"):
        raise ValueError("Unregistered intake manifest path")
    intake = json.loads(_read(path, path.name.split(".")[0]))
    if _clock(intake["completedAt"]) > as_of:
        raise ValueError("Intake unavailable at requested cutoff")
    ids = sorted(str(e["pitcherMlbamId"]) for e in intake["enumeration"])
    if ids != sorted(CURRENT_IDENTITIES):
        raise ValueError("Unregistered starter-history scope")
    protected_games = [g for g in intake.get("games", []) if "2026-08-14" <= g["gameDate"] <= "2026-08-27"]
    exception = None
    protected_descriptors = []
    if protected_games:
        from server.sports_current_statcast.mlb_starter_duration_quarantine import assert_prospective_source_allowed, load_exception_authority
        exception = load_exception_authority()
        for game in protected_games:
            if not game.get("pitcherMlbamIds") or game.get("sourceUse") != "PROSPECTIVE_STARTER_HISTORY_ONLY":
                raise ValueError("PROTECTED_DERIVATIVE_SOURCE_USE_MISMATCH")
            if game.get("protectedDerivativeAuthority") != exception["authorityRef"]:
                raise ValueError("PROTECTED_DERIVATIVE_AUTHORITY_REFERENCE_MISMATCH")
            for pid in game["pitcherMlbamIds"]:
                assert_prospective_source_allowed(pid, game["gamePk"], game["gameDate"])
                protected_descriptors.append({"pitcherMlbamId": str(pid), "gamePk": int(game["gamePk"]), "gameDate": game["gameDate"]})
    identity_sha = "869e2848322c405476c0820ce7d02449ed7e297cb6fa03a3546dfe0becb59f38"
    identity_path = intake_root / (identity_sha + ".first-pitcher-identity.json")
    code_ref = archive_parser_code()
    cache_key = _sha(canonical_json_bytes({"intake": _ref(path)["sha256"], "parser": code_ref["sha256"],
                                         "identity": identity_sha if identity_path.exists() else None,
                                         "certifiedBase": CERTIFIED_SHA, "hold": HOLD_SHA,
                                         "protectedException": exception["authorityRef"] if exception else None,
                                         "wholeGameQuarantine": exception["quarantineRef"] if exception else None,
                                         "retained2025Predecessor": "ecc375b80c9d7552b4e228bd2a1dc371e6865d4788eac1fde5400fe9a8ef5dcb"}))
    cache_path = RESEARCH / "starter-history/projection-cache" / (cache_key + ".json")
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        cm = json.loads(_read(cached["manifestRef"]["path"], cached["manifestRef"]["sha256"], cached["manifestRef"]["bytes"]))
        if _clock(cm["createdAt"]) > as_of:
            raise ValueError("Existing projection unavailable at cutoff")
        descriptor = cm["startsArtifact"]
        _read(Path(cached["manifestRef"]["path"]).with_name("starts.parquet"), descriptor["sha256"], descriptor["bytes"])
        cached["currentPointerActivated"] = _publish_partial_pointer(cached["manifestRef"])
        return cached
    # Cached immutable exact2025 replay; no source reacquisition or recomputation
    # during every dispatcher tick.
    rsha = "ecc375b80c9d7552b4e228bd2a1dc371e6865d4788eac1fde5400fe9a8ef5dcb"
    rpath = RESEARCH / "starter-history/reconciliations/sha256" / rsha / "reconciliation.json"
    if not rpath.exists():
        rref = save_reconciliation(reconcile_retained_2025())
        rpath = Path(rref["path"])
        rsha = rref["sha256"]
    retained = json.loads(_read(rpath, rsha))
    # The first immutable receipt named live working code. Preserve its exact
    # bytes when recoverable, then reference a successor with archived code.
    original = next(r for r in retained["sources"] if Path(r["path"]).name == Path(__file__).name)
    original_code = RESEARCH / "starter-history/code/sha256" / (original["sha256"] + ".py")
    _read(original_code, original["sha256"], original["bytes"])
    successor = dict(retained)
    successor["predecessor"] = _ref(rpath)
    successor["predecessorCodeReference"] = {**original, "status": "EXACT_ORIGINAL_BYTES_RECOVERED_AND_ARCHIVED"}
    successor["sources"] = [_ref(original_code) if Path(r["path"]).name == Path(__file__).name else r for r in retained["sources"]]
    successor["codeLineageCorrection"] = "Only source-reference location updated to immutable snapshot; parsed2025 starts and counts unchanged. Original receipt preserved."
    successor["startsSemanticSha256"] = _sha(canonical_json_bytes(retained["starts"]))
    successor_ref = save_reconciliation(successor)
    rpath = Path(successor_ref["path"])
    rsha = successor_ref["sha256"]
    base_manifest = json.loads(_read(CERTIFIED / "manifest.json", CERTIFIED_SHA))
    base_ref = base_manifest["artifacts"]["starts.parquet"]
    _read(CERTIFIED / "starts.parquet", base_ref["sha256"], base_ref["bytes"])
    base = pd.read_parquet(CERTIFIED / "starts.parquet")
    base = base[base.pitcherId.isin(CURRENT_IDENTITIES.values())]
    records = []
    for row in base.to_dict("records"):
        records.append({k: row.get(k) for k in ("startId", "gameId", "pitcherId", "gameDate", "eligible", "totalBf", "totalOuts", "endpoint", "exclusionReason")})
        records[-1].update(disposition="ELIGIBLE" if row["eligible"] else "EXCLUDED", completionDate=row["gameDate"])
    records.extend(retained["starts"])
    expected = {(str(e["pitcherMlbamId"]), int(g["gamePk"])): g for e in intake["enumeration"] for g in e["appearanceIdentities"]}
    if len(expected) != sum(len(e["appearanceIdentities"]) for e in intake["enumeration"]):
        raise ValueError("Duplicate enumerated appearance")
    held = json.loads(_read(HOLD, HOLD_SHA))
    held_2026 = [{k: h[k] for k in ("canonicalPaId", "canonicalGameId", "gameDate")} for h in held["heldObservations"] if h["gameDate"].startswith("2026-")]
    held_dates = {h["gameDate"] for h in held_2026}
    parsed, seen = [], set()
    for game in intake.get("games", []):
        if "2026-08-14" <= game["gameDate"] <= "2026-08-27":
            # All exact tuples and immutable authority/quarantine references have
            # already passed before any protected source bytes are opened.
            if not exception:
                raise ValueError("PROTECTED_START_PAYLOAD_NOT_AUTHORIZED")
        feed = _intake_source(game["raw"], protected_game=game if "2026-08-14" <= game["gameDate"] <= "2026-08-27" else None)
        completion = completion_from_observed_clocks(game, feed)
        for pid in game["pitcherMlbamIds"]:
            key = (str(pid), int(game["gamePk"]))
            if key not in expected or key in seen or expected[key]["gameDate"] != game["gameDate"]:
                raise ValueError("Appearance/feed identity mismatch")
            seen.add(key)
            row = parse_statsapi_start(feed, pitcher_mlbam_id=pid, completion_metadata=completion, source_reference=game["raw"])
            if row["gameDate"] in held_dates:
                row.update(eligible=False, disposition="UNRESOLVED", unresolvedReasons=["FROZEN_HOLD_GAME_PA_IDENTITY_INTERSECTION_REQUIRES_PROOF"])
            row.update({k: game[k] for k in ("availableAsOf", "observedAt", "ingestedAt")})
            if any(_clock(row[k]) > as_of for k in ("availableAsOf", "observedAt", "ingestedAt")):
                raise ValueError("Source unavailable at cutoff")
            row["completionEvidence"] = completion
            if "2026-08-14" <= row["gameDate"] <= "2026-08-27":
                row.update(protectedHistoryDerivative=True, protectedDerivativeAuthority=exception["authorityRef"],
                           wholeGameQuarantine=exception["quarantineRef"])
            parsed.append(row)
    unknown = []
    for key, g in expected.items():
        if key in seen:
            continue
        reason = "PROTECTED_START_HISTORY_PROSPECTIVE_USE_NOT_AUTHORIZED" if "2026-08-14" <= g["gameDate"] <= "2026-08-27" else "ENUMERATED_APPEARANCE_FEED_NOT_ACQUIRED"
        unknown.append({**g, "pitcherMlbamId": key[0], "disposition": "UNRESOLVED", "reason": reason, "payloadRead": False})
    identity = json.loads(_read(identity_path, identity_sha)) if identity_path.exists() else None
    debut = {}
    if identity:
        people = _intake_source(identity["receipt"]["raw"])["people"]
        if _clock(identity["receipt"]["availableAsOf"]) > as_of:
            raise ValueError("Identity source unavailable at cutoff")
        debut = {str(p["id"]): p["mlbDebutDate"] for p in people}
    records.extend(parsed)
    # Fresh projection time is actual present availability, never a claim of
    # newly refreshed historical evidence. Retained original clocks remain in
    # the linked reconciliation and raw acquisition receipts.
    created = datetime.now(timezone.utc).isoformat()
    for row in records:
        row.setdefault("observedAt", created)
        row["availableAsOf"] = created
        row.setdefault("ingestedAt", created)
    counts = {}
    for pid in ids:
        current = [r for r in parsed if r["pitcherMlbamId"] == pid]
        missing = [r for r in unknown if r["pitcherMlbamId"] == pid]
        counts[pid] = {"enumerated2026Appearances": sum(k[0] == pid for k in expected),
                       "eligible2026Starts": sum(r["eligible"] for r in current),
                       "justified2026Exclusions": sum(r["disposition"] == "EXCLUDED" for r in current),
                       "unresolved2026": sum(r["disposition"] == "UNRESOLVED" for r in current) + len(missing),
                       "pre2026NoMlbHistoryProvenByDebut": debut.get(pid, "") > "2025-12-31",
                       "sourceMlbDebutDate": debut.get(pid)}
        c = counts[pid]
        if c["enumerated2026Appearances"] != c["eligible2026Starts"] + c["justified2026Exclusions"] + c["unresolved2026"]:
            raise ValueError("Appearance coverage does not reconcile")
    complete = {p: counts[p]["unresolved2026"] == 0 and (CURRENT_IDENTITIES[p].startswith("retrosheet:")
                or counts[p]["pre2026NoMlbHistoryProvenByDebut"]) for p in ids}
    status = "COMPLETE_COMPATIBLE_CURRENT_STARTER_HISTORY" if all(complete.values()) else "PARTIAL_COVERAGE_NOT_USABLE_FOR_FORECAST"
    slim = [{k: r.get(k) for k in ("startId", "gameId", "gamePk", "pitcherMlbamId", "pitcherId", "gameDate", "completionDate", "eligible", "totalBf", "totalOuts", "disposition", "endpoint", "exclusionReason", "availableAsOf", "observedAt", "ingestedAt", "protectedHistoryDerivative")} for r in records]
    buffer = io.BytesIO()
    pd.DataFrame(slim).to_parquet(buffer, index=False, compression="zstd")
    payload = buffer.getvalue()
    report = {"schemaVersion": "MLB_STARTER_DURATION_COMPLETED_HISTORY_V1", "sourcePurpose": "CURRENT_PREGAME_INPUTS_ONLY",
              "payloadRole": "CURRENT_STARTER_DURATION_HISTORY_PROJECTION", "eligibilityDefinition": "MLB_STARTER_SURVIVAL_RISK_V1",
              "frozenEligibilityHoldPreserved": True, "sealedEvaluationPayloadsRead": 0, "protectedStartPayloadCount": len(protected_descriptors),
              "protectedStartDescriptors": protected_descriptors, "protectedExceptionAuthority": exception["authorityRef"] if exception else None,
              "wholeGameQuarantine": exception["quarantineRef"] if exception else None,
              "createdAt": created, "sourceEligibilityCutoff": as_of.isoformat(), "status": status, "playerIdentityMap": CURRENT_IDENTITIES,
              "counts": counts, "unresolvedMetadataOnly": unknown, "parsed2026Dispositions": parsed,
              "frozenHold2026": {"heldObservations": held_2026, "candidateDateIntersections": sorted(held_dates & {g["gameDate"] for g in expected.values()}),
                                 "proof": "No enumerated candidate occurs on any held2026 game date; no mixed2026 payload opened"},
              "coverageByPlayer": {CURRENT_IDENTITIES[p]: {"completeFrom": "2023-01-01", "completeThrough": intake["through"] if complete[p] else "2025-12-31",
                                    "attemptedThrough": intake.get("through"), "allScheduledStartsAccountedFor": complete[p], "eligibleStartDefinitionVerified": True,
                                    "unresolvedProtectedAppearances": [g for g in unknown if g["pitcherMlbamId"] == p and "PROTECTED" in g["reason"]],
                                    "unresolvedNonsealedStarts": [g for g in parsed if g["pitcherMlbamId"] == p and g["disposition"] == "UNRESOLVED"],
                                    "observedAt": created, "availableAsOf": created, "ingestedAt": created} for p in ids},
              "sourceReferences": [_ref(path), _ref(rpath), _ref(CERTIFIED / "manifest.json"), _ref(CERTIFIED / "starts.parquet"), _ref(HOLD), code_ref] + ([_ref(identity_path)] if identity else []) + ([exception["authorityRef"], exception["quarantineRef"]] if exception else []),
              "startsArtifact": {"relativePath": "starts.parquet", "sha256": _sha(payload), "bytes": len(payload), "rows": len(slim)},
              "publicationAuthority": {"researchOnly": True, "wageringAuthority": False},
              "notes": ["Current pointer is source evidence; only per-player complete coverage permits future-pregame input use.",
                        "2026 counts reconcile enumerated pitching appearances, not an assumption that every appearance was a start.",
                        "Protected derivatives require the exact three-game future-input exception and permanent whole-game evaluation quarantine; original sealed files remain unread.",
                        "This current retrieval cannot certify a historical pregame backtest."]}
    manifest_data = canonical_json_bytes(report)
    digest = _sha(manifest_data)
    out = RESEARCH / "starter-history/objects/sha256" / digest
    _write(out / "starts.parquet", payload)
    _write(out / "manifest.json", manifest_data)
    result = {"status": report["status"], "manifestRef": _ref(out / "manifest.json"), "counts": counts,
              "currentPointerActivated": _publish_partial_pointer(_ref(out / "manifest.json")),
              "missingReasons": unknown + [r for r in parsed if r["disposition"] == "UNRESOLVED"]}
    _write(cache_path, canonical_json_bytes(result))
    return result


def archive_parser_code():
    source = Path(__file__).read_bytes()
    path = RESEARCH / "starter-history/code/sha256" / (_sha(source) + ".py")
    _write(path, source)
    return _ref(path)

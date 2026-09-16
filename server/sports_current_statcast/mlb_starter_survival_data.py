"""Research-only supported PA-boundary starter risk sets; no model fitting.

The source is retrospective Retrosheet/FD1 observation, not a pregame vintage.
Scores below are the state immediately after the completed PA. In particular an
inning break never borrows the score when the pitcher's next inning begins.
"""
from __future__ import annotations

import csv
import io
from datetime import date

import pandas as pd

SCHEMA = "MLB_STARTER_SURVIVAL_RISK_V1"
PITCH_CODES = frozenset("BCFHIKLMOPQRSTXY")
NONPITCH_CODES = frozenset("AVN123+*.> ")
ENDPOINTS = ("CONTINUE", "REMOVAL", "GAME_END")


def innings_notation_to_outs(value: str) -> int:
    """Baseball notation, deliberately not floating-point arithmetic."""
    parts = str(value).split(".")
    if len(parts) > 2 or not parts[0].isdigit() or (len(parts) == 2 and parts[1] not in ("0", "1", "2")):
        raise ValueError("Invalid baseball innings notation")
    return 3 * int(parts[0]) + (int(parts[1]) if len(parts) == 2 else 0)


def parse_event_member(text: str, member: str) -> dict[str, dict]:
    games, game, active, last_play = {}, None, {}, None
    for line_no, row in enumerate(csv.reader(io.StringIO(text)), 1):
        if not row:
            continue
        if row[0] == "id":
            game = {"id": row[1], "member": member, "info": {}, "starters": {}, "plays": [], "subs": [], "comments": []}
            if row[1] in games:
                raise ValueError("Duplicate raw game")
            games[row[1]], active, last_play = game, {}, None
        elif game is None:
            continue
        elif row[0] == "info":
            game["info"][row[1]] = row[2] if len(row) > 2 else ""
        elif row[0] in ("start", "sub") and len(row) >= 6 and row[5] == "1":
            side, pid = int(row[3]), "retrosheet:player:" + row[1]
            if row[0] == "start":
                if side in game["starters"] and game["starters"][side] != pid:
                    raise ValueError("Multiple declared starting pitchers")
                game["starters"][side] = pid
            else:
                previous = active.get(side)
                if previous != pid:
                    same_half = last_play is not None and last_play["side"] == 1 - side
                    # NP is the supported substitution marker. Nonzero count or
                    # actual pitch evidence means a batter-facing opportunity began.
                    begun = same_half and (last_play["count"] not in ("00", "??", "") or
                                            any(c in PITCH_CODES or c == "U" for c in last_play["pitches"]))
                    game["subs"].append({"line": line_no, "side": side, "outgoing": previous,
                                         "incoming": pid, "midPaEvidence": bool(begun),
                                         "npMarker": bool(last_play and last_play["event"] == "NP")})
            active[side] = pid
        elif row[0] == "play":
            last_play = {"line": line_no, "inning": int(row[1]), "side": int(row[2]),
                         "batter": "retrosheet:player:" + row[3], "count": row[4],
                         "pitches": row[5], "event": row[6], "pitcher": active.get(1-int(row[2]))}
            game["plays"].append(last_play)
        elif row[0] == "com":
            game["comments"].append({"line": line_no, "text": ",".join(row[1:])})
    return games


def align_raw_fd1(raw: dict, rows: list[dict]) -> list[dict]:
    raw_plays = [r for r in raw["plays"] if r["event"] != "NP"]
    actual = [dict(r) for r in rows if r["event_text"] != "NP"]
    if len(raw_plays) != len(actual):
        raise ValueError("RAW_FD1_NON_NP_COUNT_MISMATCH")
    for source, row in zip(raw_plays, actual):
        if (source["inning"], source["side"], source["batter"], source["event"]) != (
                int(row["inning"]), int(row["top_bottom"]), row["batter_id"], row["event_text"]):
            raise ValueError("RAW_FD1_EVENT_IDENTITY_MISMATCH")
        if source["pitcher"] != row["pitcher_id"]:
            raise ValueError("RAW_FD1_PITCHER_ATTRIBUTION_MISMATCH")
        row["raw"] = source
    return actual


def _terminal(row: dict) -> bool:
    return bool(row.get("pa_terminal_token"))


def start_risks(raw: dict, rows: list[dict], home_pitcher: int, *, complete: bool) -> tuple[list[dict], dict]:
    """Return supported starter rows and a disposition even when unsupported.

    Endpoint is observed from later source ordering; predictors are not. A
    non-PA terminal stint and a mid-PA change have no supported completed-PA
    endpoint and are excluded whole-stint, not converted to managerial hooks.
    """
    pid = raw["starters"].get(home_pitcher)
    gid = "retrosheet:game:" + raw["id"]
    game_date = raw["info"].get("date", "").replace("/", "-")
    common = {"startId": gid + ":" + str(home_pitcher), "gameId": gid, "pitcherId": pid,
              "gameDate": game_date, "homePitcher": home_pitcher, "calendarMonth": int(game_date[5:7]),
              "sourceMember": raw["member"], "sourceGameId": raw["id"]}
    summary = {**common, "eligible": False, "endpoint": "UNKNOWN", "exclusionReason": None,
               "totalBf": None, "totalOuts": None, "observedPitches": None, "midPaChange": False,
               "realizedShortStartBfLe9": None, "roleAtStart": "UNKNOWN_NOT_INFERRED_FROM_REALIZED_DURATION"}
    if not pid:
        summary["exclusionReason"] = "DECLARED_STARTER_UNAVAILABLE"
        return [], summary
    defensive = [r for r in rows if int(r["top_bottom"]) == 1-home_pitcher]
    if not defensive or defensive[0]["pitcher_id"] != pid:
        summary["exclusionReason"] = "DECLARED_STARTER_FIRST_PITCHER_MISMATCH"
        return [], summary
    seen_replacement = False
    stint = []
    for row in defensive:
        if row["pitcher_id"] == pid:
            if seen_replacement:
                summary["exclusionReason"] = "STARTER_REENTRY_UNSUPPORTED"
                return [], summary
            stint.append(row)
        else:
            seen_replacement = True
    substitutions = [r for r in raw["subs"] if r["side"] == home_pitcher and r["outgoing"] == pid]
    summary["midPaChange"] = any(r["midPaEvidence"] for r in substitutions)
    summary["totalBf"] = sum(_terminal(r) for r in stint)
    summary["totalOuts"] = sum(int(r["outs_after"])-int(r["outs_before"]) for r in stint)
    summary["realizedShortStartBfLe9"] = summary["totalBf"] <= 9
    if summary["midPaChange"]:
        summary["exclusionReason"] = "MID_PA_STARTER_CHANGE"
        return [], summary
    if not complete:
        summary["exclusionReason"] = "CENSORED_UNKNOWN_GAME_COMPLETION"
        return [], summary
    if not stint or not _terminal(stint[-1]):
        summary["exclusionReason"] = "NON_PA_TERMINAL_STINT_BOUNDARY_UNSUPPORTED"
        return [], summary
    if substitutions and any(not r["npMarker"] for r in substitutions):
        summary["exclusionReason"] = "UNSUPPORTED_SUBSTITUTION_ORDER"
        return [], summary
    removal = bool(substitutions or seen_replacement)
    if removal and substitutions and substitutions[0]["line"] <= stint[-1]["raw"]["line"]:
        summary["exclusionReason"] = "SUBSTITUTION_STINT_ORDER_MISMATCH"
        return [], summary
    bf = outs = runs = pitches = 0
    pitches_known, previous_pitch_string, previous_pa_key = True, "", None
    risks = []
    for row in stint:
        outs += int(row["outs_after"]) - int(row["outs_before"])
        runs += int(row["runs_scored"])
        pitch_string = row["raw"]["pitches"]
        pa_key = (int(row["inning"]), int(row["top_bottom"]), row["batter_id"])
        if pa_key != previous_pa_key:
            previous_pitch_string = ""
        if not pitch_string.startswith(previous_pitch_string):
            pitches_known = False
            delta = ""
        else:
            delta = pitch_string[len(previous_pitch_string):]
        if any(c not in PITCH_CODES | NONPITCH_CODES for c in delta):
            pitches_known = False
        if not pitch_string and row["event_text"] not in ("IW", "W"):
            pitches_known = False
        pitches += sum(c in PITCH_CODES for c in delta)
        previous_pitch_string, previous_pa_key = pitch_string, pa_key
        if not _terminal(row):
            continue
        bf += 1
        score_margin = int(row["home_score_after"])-int(row["visiting_score_after"])
        final = row is stint[-1]
        endpoint = ("REMOVAL" if removal else "GAME_END") if final else "CONTINUE"
        risks.append({**common, "riskId": common["startId"]+":bf:"+str(bf), "bf": bf,
                      "endpoint": endpoint, "removalTarget": int(endpoint == "REMOVAL") if endpoint != "GAME_END" else None,
                      "inning": int(row["inning"]), "outsInInning": int(row["outs_after"]),
                      "nextPitchInning": int(row["inning"])+(int(row["outs_after"]) == 3),
                      "inningBreak": int(row["outs_after"]) == 3,
                      "pitchingOuts": outs, "runsAllowedSoFar": runs,
                      "pitchingTeamScoreMargin": score_margin if home_pitcher else -score_margin,
                      "baseState": int(row["base_mask_after"]),
                      "observedPitches": pitches if pitches_known else None, "elapsedWallClockSeconds": None,
                      "plateAppearanceId": row["plate_appearance_id"], "playNumber": int(row["play_number"]),
                      "sourceLine": row["raw"]["line"], "sourceRowChecksum": row.get("row_checksum"),
                      "substitutionSourceLine": substitutions[0]["line"] if final and substitutions else None})
        previous_pa_key, previous_pitch_string = None, ""
    summary.update(eligible=True, endpoint=risks[-1]["endpoint"], observedPitches=pitches if pitches_known else None)
    return risks, summary


def add_pregame_history(starts: pd.DataFrame, risks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Strictly prior calendar-date eligible games only; same-day games held back."""
    out = starts.copy()
    history = {}
    for day, group in out.sort_values(["gameDate", "startId"]).groupby("gameDate", sort=True):
        current_date = date.fromisoformat(day)
        for idx, row in group.iterrows():
            prior = history.get(row.pitcherId, [])
            out.loc[idx, "priorStartCount"] = len(prior)
            out.loc[idx, "priorStartBfMean"] = sum(p[1] for p in prior)/len(prior) if prior else float("nan")
            out.loc[idx, "daysRest"] = (current_date-prior[-1][0]).days-1 if prior else float("nan")
            out.loc[idx, "historyMissing"] = not prior
            out.loc[idx, "latestHistoryCompletionDate"] = prior[-1][0].isoformat() if prior else None
        for _, row in group.iterrows():
            if bool(row.eligible):
                history.setdefault(row.pitcherId, []).append((current_date, int(row.totalBf)))
    fields = ["startId", "priorStartCount", "priorStartBfMean", "daysRest", "historyMissing", "latestHistoryCompletionDate"]
    risk_out = risks.merge(out[fields], on="startId", how="left", validate="many_to_one")
    known = risk_out.latestHistoryCompletionDate.notna()
    if not risk_out.loc[known, "latestHistoryCompletionDate"].lt(risk_out.loc[known, "gameDate"]).all():
        raise ValueError("History does not strictly precede game date")
    return out, risk_out

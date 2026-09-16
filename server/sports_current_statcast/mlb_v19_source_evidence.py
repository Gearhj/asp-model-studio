"""Read-only, source-backed V19 research supplements, never V18 publication.

The input boundary accepts immutable single-day captures only, checks their
clocks before opening their payloads, and rejects the sealed calendar interval.
Retrospective derivation does not create a historical publication vintage.
No fitted model, provider, database, operational cache, or scheduler is imported.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Mapping, Sequence


VERSION = "MLB_V19_SOURCE_EVIDENCE_V1"
WINDOWS = (1, 3, 7)
SEALED = (date(2026, 8, 14), date(2026, 8, 27))
RIGHTS = {
    "allowedUse": "LOCAL_PRIVATE_MODEL_DEVELOPMENT",
    "statcastStatus": "GOVERNED_LOCAL_RESEARCH_ONLY",
    "attributionRequired": True, "commercialRightsReviewRequired": True,
    "publicRawRedistributionAllowed": False,
}


def utc(value) -> datetime:
    value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Source clocks must include timezone")
    return value.astimezone(timezone.utc)


def canonical_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def descriptor(path: Path) -> dict:
    blob = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def verified_bytes(ref: Mapping, allowed_root: Path) -> bytes:
    path = Path(ref["path"]).resolve()
    if not path.is_relative_to(allowed_root.resolve()):
        raise ValueError("Source reference escaped the immutable capture root")
    blob = path.read_bytes()
    if hashlib.sha256(blob).hexdigest() != ref["sha256"] or len(blob) != ref["bytes"]:
        raise ValueError("Source checksum or byte count mismatch")
    return blob


def checked_clocks(record: Mapping, cutoff) -> dict:
    cutoff = utc(cutoff)
    result = {key: record[key] for key in ("observedAt", "availableAsOf", "ingestedAt")}
    if utc(result["observedAt"]) > utc(result["availableAsOf"]):
        raise ValueError("Observation follows availability")
    if any(utc(value) > cutoff for value in result.values()):
        raise ValueError("Evidence was not captured before the requested cutoff")
    # Preserve, do not repair, legacy ingestion clocks that precede observation.
    result["providerPublishedAt"] = record.get("providerPublishedAt")
    return result


def load_daily_capture(schedule: Mapping, statcast: Mapping, *, cutoff, source_root: Path) -> dict:
    """Derive observed pitch-bearing appearances, not invented official workload.

    Automatic balls/strikes are not physical pitch events. Unclassified pitches
    otherwise remain included. A complete game-ID match is required for known
    zero recorded-pitch exposure; it does not prove the absence of every possible
    pitchless appearance, warmup pitch, bullpen session, or untracked pitch.
    """
    day = date.fromisoformat(str(statcast["day"]))
    if SEALED[0] <= day <= SEALED[1]:
        raise ValueError("FINAL_OOT_CALENDAR_EXCLUDED_BEFORE_PAYLOAD_READ")
    if day >= utc(cutoff).date() or schedule["day"] != statcast["day"]:
        raise ValueError("History must be one prior completed calendar date")
    if schedule["family"] != "SCHEDULE" or statcast["family"] != "STATCAST":
        raise ValueError("Expected existing schedule/Statcast capture pair")
    clocks = [checked_clocks(record, cutoff) for record in (schedule, statcast)]
    for record in (schedule, statcast):
        if record.get("rights") != RIGHTS:
            raise ValueError("Source rights differ: explicit restrictive-rights review required")
    schedule_payload = json.loads(verified_bytes(schedule["raw"], source_root))
    expected, unresolved, games = set(), [], {}
    for group in schedule_payload.get("dates", []):
        if group["date"] != day.isoformat():
            raise ValueError("Schedule response contains an unrequested date")
        for game in group.get("games", []):
            if game.get("gameType") != "R" or game.get("officialDate") != day.isoformat():
                continue
            pk = str(game["gamePk"])
            status = game.get("status", {}).get("detailedState")
            if status in {"Final", "Completed Early"}:
                expected.add(pk)
                games[pk] = {"gamePk": pk, "gameDate": day.isoformat(),
                    "scheduledStartUtc": game["gameDate"], "venueId": game.get("venue", {}).get("id"),
                    "homeTeamId": str(game["teams"]["home"]["team"]["id"]),
                    "awayTeamId": str(game["teams"]["away"]["team"]["id"]), "status": "FINAL"}
            elif status not in {"Postponed", "Cancelled", "Canceled"}:
                unresolved.append(pk)
    blob = verified_bytes(statcast["raw"], source_root)
    records = list(csv.DictReader(io.StringIO(blob.decode("utf-8-sig"))))
    if len(records) >= 25000:
        raise ValueError("Daily source row cap reached; completeness unproven")
    seen, pitches, automatic, duplicate = {}, [], 0, 0
    represented = set()
    for record in records:
        if record["game_date"] != day.isoformat():
            raise ValueError("Statcast response contains an unrequested date")
        pk = str(int(record["game_pk"]))
        represented.add(pk)
        key = (pk, int(record["at_bat_number"]), int(record["pitch_number"]))
        # Conflicting corrections cannot be silently collapsed by row order.
        fingerprint = canonical_bytes(record)
        if key in seen:
            if seen[key] != fingerprint:
                raise ValueError("Conflicting source pitch identities require correction authority")
            duplicate += 1
            continue
        seen[key] = fingerprint
        if record["description"] in {"automatic_ball", "automatic_strike"}:
            automatic += 1
            continue
        if pk not in expected:
            continue
        top = record["inning_topbot"]
        if top not in {"Top", "Bot"}:
            raise ValueError("Unknown home/away pitching orientation")
        pitches.append({"gamePk": pk, "gameDate": day.isoformat(),
            "pitcherId": str(int(record["pitcher"])), "inning": int(record["inning"]),
            "atBatNumber": key[1], "pitchNumber": key[2],
            "teamId": games[pk]["homeTeamId" if top == "Top" else "awayTeamId"],
            "teamAbbreviation": record["home_team" if top == "Top" else "away_team"],
            "pitchClassified": bool(record["pitch_type"]), "description": record["description"]})
    pitches.sort(key=lambda row: (row["gamePk"], row["atBatNumber"], row["pitchNumber"]))
    opening, appearances = {}, {}
    for pitch in pitches:
        opening.setdefault((pitch["gamePk"], pitch["teamId"]), pitch["pitcherId"])
        key = (pitch["gamePk"], pitch["teamId"], pitch["pitcherId"])
        row = appearances.setdefault(key, {k: pitch[k] for k in
            ("gamePk", "gameDate", "pitcherId", "teamId", "teamAbbreviation")})
        row["recordedPitchEvents"] = row.get("recordedPitchEvents", 0) + 1
        row["unclassifiedPitchEvents"] = row.get("unclassifiedPitchEvents", 0) + int(not pitch["pitchClassified"])
        row["openedRecordedPitchSequence"] = opening[(pitch["gamePk"], pitch["teamId"])] == pitch["pitcherId"]
    return {"day": day.isoformat(), "complete": represented == expected and not unresolved,
        "expectedGamePks": sorted(expected), "representedGamePks": sorted(represented),
        "unresolvedGamePks": sorted(unresolved), "missingGamePks": sorted(expected - represented),
        "unexpectedGamePks": sorted(represented - expected), "rawRows": len(records),
        "duplicateRowsRemoved": duplicate, "automaticEventsExcluded": automatic,
        "recordedPitchEvents": len(pitches), "appearances": sorted(appearances.values(), key=lambda row:
            (row["gamePk"], row["teamId"], row["pitcherId"])), "games": list(games.values()),
        "sourceClocks": clocks, "sourceReceipts": [schedule["_receipt"], statcast["_receipt"]],
        "rawSources": [schedule["raw"], statcast["raw"]], "rights": RIGHTS,
        "historicalPregameVintageEstablished": False,
        "availabilityBasis": "ORIGINAL_RETRIEVAL_OF_COMPLETED_GAMES_NOT_GAME_TIME"}


def pitcher_workload(player_id: str, captures: Sequence[Mapping], *, target_day: str) -> dict:
    day = date.fromisoformat(target_day)
    by_day = {date.fromisoformat(capture["day"]): capture for capture in captures}
    if len(by_day) != len(captures):
        raise ValueError("Duplicate daily capture: choose a correction vintage explicitly")
    if any(value >= day or SEALED[0] <= value <= SEALED[1] for value in by_day):
        raise ValueError("Future/target-day or sealed historical evidence is forbidden")
    result = {"playerMlbamId": str(player_id), "windows": {}}
    for window in WINDOWS:
        days = [day - timedelta(days=i) for i in range(1, window + 1)]
        missing = [d.isoformat() for d in days if d not in by_day or not by_day[d]["complete"]]
        rows = [row for d in days if d in by_day for row in by_day[d]["appearances"]
                if row["pitcherId"] == str(player_id)]
        result["windows"][str(window)] = {"recordedPitchEvents": None if missing else sum(r["recordedPitchEvents"] for r in rows),
            "pitchBearingAppearances": None if missing else len(rows),
            "calendarDaysWithRecordedPitches": None if missing else len({r["gameDate"] for r in rows}),
            "semanticState": "SOURCE_GAP" if missing else "OBSERVED_EXPOSURE" if rows else "KNOWN_ZERO_RECORDED_PITCH_EXPOSURE",
            "missingCoverageDates": missing}
    rows = sorted((r for c in captures for r in c["appearances"] if r["pitcherId"] == str(player_id)),
                  key=lambda row: (row["gameDate"], row["gamePk"]))
    complete_seven = not result["windows"]["7"]["missingCoverageDates"]
    latest = rows[-1] if rows and complete_seven else None
    same_day = [r for r in rows if latest and r["gameDate"] == latest["gameDate"]]
    result.update(latestObservedAppearance=latest,
        calendarDaysSinceLatestRecordedPitch=(day - date.fromisoformat(latest["gameDate"])).days if latest else None,
        latestDayAppearanceOrderKnown=len(same_day) <= 1,
        noRecordedAppearanceWithinSevenDays=not rows if complete_seven else None,
        actualRecoveryHours=None, actualAvailability=None, officialPitchCountVerified=False,
        restLimitation="Calendar-date spacing, not actual end-to-start recovery; no appearance outside observed window inferred")
    return result


def roster_membership(rows: Sequence[Mapping], *, cutoff) -> dict:
    """Latest observed source batch per side; retain superseded identities.

    These are V18's selected staff candidates, not a complete 26-man roster.
    A superseded row is unknown current membership, never an inferred release.
    """
    grouped = defaultdict(list)
    for row in rows:
        checked_clocks(row["source"], cutoff)
        grouped[(row["side"], row["source"]["sourceIdentity"])].append(row)
    retained, superseded = [], []
    for values in grouped.values():
        latest = max(utc(row["source"]["observedAt"]) for row in values)
        for row in values:
            target = retained if utc(row["source"]["observedAt"]) == latest else superseded
            target.append({**row, "membershipState": "LATEST_OBSERVED_SELECTED_POOL" if target is retained
                           else "SUPERSEDED_OBSERVATION_CURRENT_MEMBERSHIP_UNKNOWN"})
    return {"currentSelectedPool": retained, "supersededObservations": superseded,
            "fullRosterCompletenessEstablished": False, "transactionsEstablished": False,
            "actualBullpenAvailabilityEstablished": False}


def supplement(game: Mapping, captures: Sequence[Mapping], *, predecessor_sha256=None) -> dict:
    """Construct a post-event research supplement tied to an original forecast.

    This API cannot publish forecasts; calculation time never overwrites the
    original forecast-created/evidence clocks. Nothing changes V18's 246 fields.
    """
    cutoff, start = utc(game["evidenceCutoff"]), utc(game["scheduledFirstPitch"])
    if cutoff >= start:
        raise ValueError("Original evidence cutoff must precede scheduled first pitch")
    for capture in captures:
        for clocks in capture["sourceClocks"]:
            checked_clocks(clocks, cutoff)
    # MLB's official/local event date is explicit; UTC midnight is not a season
    # boundary and must not accidentally include target-day history.
    target_day = game["targetGameDate"]
    membership = roster_membership(game["originalSourceEvidence"]["roster"], cutoff=cutoff)
    pitchers, sides = [], []
    for side in game["participants"]:
        starter, lineup = side["starter"], side["lineupAuthority"]
        starter_clocks, lineup_clocks = checked_clocks(starter, cutoff), checked_clocks(lineup, cutoff)
        pitchers.append({"side": side["side"], "role": "PROBABLE_STARTER",
            "canonicalPlayerId": starter["canonicalPlayerId"], "membershipState": "PROBABLE_NOT_CONFIRMED",
            **pitcher_workload(starter["mlbamId"], captures, target_day=target_day)})
        current = [r for r in membership["currentSelectedPool"] if r["side"] == side["side"]]
        for player in current:
            pitchers.append({"side": side["side"], "role": "SELECTED_NONSTARTER_CANDIDATE",
                "canonicalPlayerId": player["canonicalPlayerId"], "membershipState": player["membershipState"],
                **pitcher_workload(player["mlbamId"], captures, target_day=target_day)})
        sides.append({"side": side["side"], "team": side["team"],
            "starterConfirmationState": starter["confirmationState"], "starterClocks": starter_clocks,
            "lineupConfirmationState": lineup["status"], "lineupClocks": lineup_clocks,
            "starterObservationAgeMinutesAtCutoff": (cutoff - utc(starter["observedAt"])).total_seconds() / 60,
            "lineupObservationAgeMinutesAtCutoff": (cutoff - utc(lineup["observedAt"])).total_seconds() / 60,
            "currentSelectedPoolCount": len(current), "teamWorkload": team_workload(side["team"]["abbreviation"], captures,
                target_day=target_day), "scheduleContext": schedule_context(side["team"]["abbreviation"], captures,
                target_day=target_day, start=start, venue_id=game.get("sourceVenueId"), venues=game.get("venueAuthorities", [])),
            "actualBullpenAvailability": None,
            "transactionState": "UNSUPPORTED_NO_TRANSACTION_AUTHORITY", "weather": "UNSUPPORTED_NO_PREGAME_VINTAGE",
            "roof": "UNSUPPORTED_NO_PREGAME_VINTAGE", "actualRecoveryHours": None})
    return {"schemaVersion": VERSION, "gameId": game["gameId"], "sourceGameId": game["sourceGameId"],
        "originalForecastObjectSha256": game["forecastObject"]["objectSha256"],
        "originalForecastCreatedAt": game["forecastCreatedAt"], "originalEvidenceCutoff": game["evidenceCutoff"],
        "scheduledFirstPitch": game["scheduledFirstPitch"], "targetGameDate": target_day,
        "historySourceEvidenceAsOf": max(
            (utc(c["availableAsOf"]) for capture in captures for c in capture["sourceClocks"]), default=cutoff).isoformat(),
        "sourceEvidenceAsOf": max([utc(c["availableAsOf"]) for capture in captures for c in capture["sourceClocks"]]
            + [utc(side[family]["availableAsOf"]) for side in game["participants"] for family in ("starter", "lineupAuthority")]
            + [utc(row["source"]["availableAsOf"]) for row in game["originalSourceEvidence"]["roster"]]).isoformat(),
        "artifactPurpose": "RETROSPECTIVE_DERIVATION_FROM_ORIGINAL_PREGAME_CAPTURE_FOR_FORWARD_ARCHIVE_DESIGN",
        "historicalDevelopmentTrainingAllowed": False, "historicalPregameVintageClaimed": False,
        "newPregameForecastClaimed": False, "consumedByFrozenV18": False, "consumedByFittedV19": False,
        "sourceProviderCalls": 0, "sourceCostUsd": 0, "sealedPayloadReads": 0,
        "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED", "wageringAuthority": False,
        "executionAllowedInAISP": False, "rights": RIGHTS, "predecessorSha256": predecessor_sha256,
        "scheduleVenueAuthority": game.get("scheduleVenueAuthority"),
        "sourceCaptureIdentities": [c["sourceReceipts"] for c in captures], "rosterEvidence": membership,
        "pitchers": pitchers, "sides": sides,
        "limitations": ["Recorded Statcast pitch events are not independently verified official pitch counts.",
            "Opening recorded pitcher is not a claim about a prior announced starter or future role.",
            "Calendar rest is not actual recovery time. Warmups, bullpen sessions and pitchless appearances are unsupported.",
            "Selected staff pool is not complete roster or actual bullpen availability; stale membership remains unknown.",
            "No injury/transaction/weather/roof/umpire authority was invented. No performance improvement asserted."]}


def team_workload(abbreviation: str, captures: Sequence[Mapping], *, target_day: str) -> dict:
    day = date.fromisoformat(target_day)
    by_day = {c["day"]: c for c in captures}
    output = {}
    for window in WINDOWS:
        days = [(day - timedelta(days=i)).isoformat() for i in range(1, window + 1)]
        complete = all(d in by_day and by_day[d]["complete"] for d in days)
        rows = [r for d in days if d in by_day for r in by_day[d]["appearances"]
                if r["teamAbbreviation"] == abbreviation]
        output[str(window)] = {"recordedPitchEvents": sum(r["recordedPitchEvents"] for r in rows) if complete else None,
            "nonopeningPitcherRecordedPitchEvents": sum(r["recordedPitchEvents"] for r in rows
                if not r["openedRecordedPitchSequence"]) if complete else None,
            "nonopeningPitchBearingAppearances": sum(not r["openedRecordedPitchSequence"] for r in rows) if complete else None,
            "semanticState": "OBSERVED_TEAM_HISTORY" if complete else "SOURCE_GAP"}
    return output


def schedule_context(abbreviation: str, captures: Sequence[Mapping], *, target_day: str,
                     start, venue_id, venues: Sequence[Mapping]) -> dict:
    """Schedule spacing and reviewed-venue centroid distance, not actual travel."""
    team_ids = {r["teamId"] for c in captures for r in c["appearances"] if r["teamAbbreviation"] == abbreviation}
    if len(team_ids) != 1:
        return {"semanticState": "TEAM_IDENTITY_UNRESOLVED", "actualRecoveryHours": None}
    team_id = next(iter(team_ids))
    games = sorted((game for capture in captures for game in capture["games"]
                    if team_id in (game["homeTeamId"], game["awayTeamId"])
                    and game["gameDate"] < target_day), key=lambda game: (utc(game["scheduledStartUtc"]), game["gamePk"]))
    prior = games[-1] if games else None
    lookback = {capture["day"]: capture["complete"] for capture in captures}
    if not prior or any(not lookback.get((date.fromisoformat(target_day) - timedelta(days=i)).isoformat(), False)
                        for i in range(1, (date.fromisoformat(target_day) - date.fromisoformat(prior["gameDate"])).days + 1)):
        return {"semanticState": "PREVIOUS_COMPLETED_GAME_UNRESOLVED", "actualRecoveryHours": None}
    indexed = {str(mlbam): venue for venue in venues for mlbam in venue["mlbVenueIds"]}
    origin, destination = indexed.get(str(prior["venueId"])), indexed.get(str(venue_id))
    distance = None
    if origin and destination and all(v.get(k) is not None for v in (origin, destination) for k in ("latitude", "longitude")):
        lat1, lat2 = map(math.radians, (origin["latitude"], destination["latitude"]))
        delta_lat = lat2 - lat1
        delta_lon = math.radians(destination["longitude"] - origin["longitude"])
        a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
        distance = 2 * 3958.7613 * math.asin(min(1.0, math.sqrt(a)))
    return {"semanticState": "OBSERVED_PRIOR_GAME_REVIEWED_VENUE_PROXY", "canonicalSourceTeamId": team_id,
        "priorGamePk": prior["gamePk"], "priorGameDate": prior["gameDate"],
        "priorScheduledStartUtc": prior["scheduledStartUtc"],
        "scheduledStartToStartHours": (utc(start) - utc(prior["scheduledStartUtc"])).total_seconds() / 3600,
        "calendarDateGap": (date.fromisoformat(target_day) - date.fromisoformat(prior["gameDate"])).days,
        "reviewedVenueCentroidMiles": distance, "actualTravelObserved": False, "actualRecoveryHours": None,
        "actualPreviousGameEndUtc": None, "newToFrozenV18": False,
        "historicalDevelopmentVintageEstablished": False}


def store_supplement(value: Mapping, output_root: Path, *, name="source-supplement.json") -> dict:
    """Content-addressed cache. Unchanged sources/derivation yield the same file."""
    blob = canonical_bytes(value)
    digest = hashlib.sha256(blob).hexdigest()
    path = output_root / "sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != blob:
            raise ValueError("Immutable supplement collision")
    else:
        with path.open("xb") as handle:
            handle.write(blob)
    return {"path": str(path.resolve()), "sha256": digest, "bytes": len(blob)}

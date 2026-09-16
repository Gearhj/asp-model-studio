"""Pure current-event input composition; no loading, fitting or inference.

Callers supply the verified frozen source order and authenticated source records.
Historical player snapshots are never borrowed from another player. Missing
current evidence stays missing, even when the frozen estimator accepts NaNs.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .contextual_features import (
    CONTEXT_FEATURE_VERSION, GameContextInput, VenueAuthority,
    build_team_game_context,
)


CALENDAR_FIELDS = frozenset({
    "game_day_of_week", "game_month", "season_phase", "local_start_hour",
    "is_day_game", "is_night_game", "is_friday", "is_saturday", "is_sunday",
    "is_weekend", "month_sin", "month_cos", "day_of_week_sin", "day_of_week_cos",
    "local_start_hour_sin", "local_start_hour_cos",
})
CURRENT_ONLY_CONTEXT = frozenset({
    "current_start_missing", "current_venue_coordinates_missing",
    "current_venue_timezone_missing", "current_venue_altitude_missing",
    "team_home_timezone_missing", "team_alignment_missing",
    "start_hour_in_team_home_time_zone", "local_body_clock_offset_hours",
    "circadian_body_clock_component", "same_league_game", "interleague_game",
    "division_game", "same_division", "pregame_temperature_missing",
    "recent_bullpen_workload_missing", "home_x_friday_night", "home_x_weekend",
})
INITIAL_STATE = {
    "context_inning": 1, "context_outs_before": 0,
    "context_base_mask_before": 0, "context_batting_score_diff_before": 0,
}


def _utc(value: Any) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Source and event timestamps must be timezone-aware")
    return result.astimezone(timezone.utc)


def _source_reason(record: Mapping[str, Any] | None, event_id: str, as_of: datetime) -> str | None:
    if not record or not record.get("sourceIdentity"):
        return "MISSING_SOURCE_EVIDENCE"
    if str(record.get("eventId", "")) != event_id:
        return "SOURCE_EVENT_IDENTITY_MISMATCH"
    try:
        observed, available = _utc(record["observedAt"]), _utc(record["availableAsOf"])
    except (KeyError, TypeError, ValueError):
        return "MISSING_OR_INVALID_SOURCE_TIMESTAMPS"
    if observed > available or available > as_of:
        return "SOURCE_NOT_AVAILABLE_AT_FORECAST_CUTOFF"
    return None


def _provenance(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in (
        "sourceIdentity", "eventId", "observedAt", "availableAsOf", "sha256",
        "stateAsOf", "historyCompleteThrough", "missingState", "playerId", "identityKind",
    ) if key in record}


def compose_current_input(
    *, source_order: Sequence[str], event: Mapping[str, Any], batting_side: str,
    as_of_utc: str | datetime, field_evidence: Mapping[str, Mapping[str, Any]],
    treated_order: Sequence[str] = (), prior_output_schema: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return one truthful 246-field current row and field-level support evidence.

    ``event`` requires canonicalGameId, gameDate, startsAtUtc, venueTimezone,
    homeTeamId, awayTeamId, venueId, and a source record. Optional source-backed
    seasonStartDate/seriesGameNumber/gamesInSeries/isHomeOpener add calendar
    coverage. Each field record contains value/sourceIdentity/eventId/observedAt/
    availableAsOf. Player fields also bind playerId. Rolling and history-dependent
    team fields require historyCompleteThrough covering the prior completed date;
    an old last-observation date alone cannot prove completeness.

    canonicalPaId must explicitly identify a hypothetical PA, not an observed PA.
    Supply batterBats (L/R/S) and pitcherThrows (L/R) to derive matchup flags.
    This seam does not execute or bypass the existing Development-only transforms.
    """
    order = list(source_order)
    if len(order) != 246 or len(set(order)) != 246:
        raise ValueError("The verified V18 source order must contain exactly 246 unique fields")
    if batting_side not in {"AWAY", "HOME"}:
        raise ValueError("batting_side must be AWAY or HOME")
    as_of = _utc(as_of_utc)
    kickoff = _utc(event["startsAtUtc"])
    day = date.fromisoformat(str(event["gameDate"]))
    event_id = str(event["canonicalGameId"])
    if as_of >= kickoff or date(2026, 8, 14) <= day <= date(2026, 8, 27):
        raise ValueError("Only genuinely pregame events outside sealed Final OOT may be composed")
    event_source = event.get("source") or {}
    reason = _source_reason(event_source, event_id, as_of)
    if reason:
        raise ValueError("Event authority: " + reason)
    local = kickoff.astimezone(ZoneInfo(str(event["venueTimezone"])))
    if local.date() != day:
        raise ValueError("Event gameDate differs from kickoff date in its verified venue timezone")
    prior_day = day - timedelta(days=1)
    values: dict[str, Any] = {name: None for name in order}
    fields = {name: {"field": name, "supported": False, "status": "MISSING_SOURCE_EVIDENCE", "provenance": []}
              for name in order}

    def assign(name: str, value: Any, status: str, sources: list[dict]) -> None:
        if name in fields:
            values[name] = value
            fields[name].update(supported=True, status=status, provenance=sources)

    for name in order:
        if name.startswith("matchup_"):
            fields[name]["status"] = "VERIFIED_PARTICIPANT_HANDEDNESS_REQUIRED"
            continue
        record = field_evidence.get(name)
        issue = _source_reason(record, event_id, as_of)
        if issue:
            fields[name]["status"] = issue
            continue
        assert record is not None
        source = _provenance(record)
        if "value" not in record or record["value"] is None:
            fields[name].update(status="SOURCE_VALUE_MISSING", provenance=[source])
            continue
        if name.startswith(("batter_", "pitcher_")):
            identity_name = "batterCanonicalPlayerId" if name.startswith("batter_") else "pitcherCanonicalPlayerId"
            identity = field_evidence.get(identity_name)
            if (_source_reason(identity, event_id, as_of) is not None or not identity.get("value")
                    or record.get("playerId") != identity["value"]):
                fields[name].update(status="PLAYER_SOURCE_IDENTITY_MISMATCH", provenance=[source])
                continue
        suffix = name.split("_", 1)[1] if name.startswith(("batting_", "fielding_")) else None
        needs_history = name.startswith(("batter_last100_", "pitcher_last250_")) or (
            suffix is not None and suffix not in CURRENT_ONLY_CONTEXT)
        if needs_history:
            try:
                complete = date.fromisoformat(str(record["historyCompleteThrough"]))
            except (KeyError, TypeError, ValueError):
                fields[name].update(status="HISTORY_WINDOW_COMPLETENESS_NOT_PROVEN", provenance=[source])
                continue
            if complete < prior_day:
                fields[name].update(status="STALE_HISTORY_WINDOW", provenance=[source])
                continue
            if complete >= day:
                fields[name].update(status="SAME_DATE_OR_FUTURE_HISTORY_NOT_AUTHORIZED", provenance=[source])
                continue
        if name == "canonicalPaId" and record.get("identityKind") != "HYPOTHETICAL_PA":
            fields[name].update(status="HYPOTHETICAL_PA_IDENTITY_REQUIRED", provenance=[source])
            continue
        assign(name, record["value"], "SOURCE_BACKED_CURRENT" if needs_history else "SOURCE_BACKED",
               [source])

    event_provenance = [_provenance(event_source)]
    for name, value in {"game_date": day.isoformat(), "canonicalGameId": event_id, "season": day.year}.items():
        assign(name, value, "CURRENT_EVENT_IDENTITY", event_provenance)
    for name, value in {**INITIAL_STATE, "context_top_bottom": int(batting_side == "HOME")}.items():
        assign(name, value, "DEFINED_INITIAL_SIMULATION_STATE_NOT_OBSERVED_EVENT", event_provenance)
    # The existing builder owns calendar semantics. Its history-dependent outputs
    # are deliberately discarded: empty supplied history is not no-history proof.
    team_keys = ("homeTeamId", "awayTeamId", "venueId")
    if all(event.get(key) for key in team_keys):
        game = GameContextInput(
            canonical_game_id=event_id, game_date=day,
            home_team_id=str(event["homeTeamId"]), away_team_id=str(event["awayTeamId"]),
            venue_id=str(event["venueId"]), scheduled_start_utc=kickoff,
            season_start_date=date.fromisoformat(str(event["seasonStartDate"])) if event.get("seasonStartDate") else None,
            series_game_number=event.get("seriesGameNumber"), games_in_series=event.get("gamesInSeries"),
            is_home_opener=bool(event.get("isHomeOpener", False)),
        )
        venue = VenueAuthority(str(event["venueId"]), None, None, str(event["venueTimezone"]))
        calendar = build_team_game_context(game, game.home_team_id, history=(), venues={game.venue_id: venue})
        supported_calendar = set(CALENDAR_FIELDS)
        if event.get("seasonStartDate"):
            supported_calendar.add("game_day_of_season")
        if event.get("seriesGameNumber") is not None:
            supported_calendar.update(("series_game_number", "is_series_opener"))
        if event.get("seriesGameNumber") is not None and event.get("gamesInSeries") is not None:
            supported_calendar.update(("is_series_finale", "is_getaway_day"))
        if "isHomeOpener" in event:
            supported_calendar.add("is_home_opener")
        for name in supported_calendar:
            if calendar.get(name) is not None:
                assign(name, calendar[name], "DERIVED_REGISTERED_CALENDAR", event_provenance)

    hand_sources = {name: field_evidence.get(name) for name in ("batterBats", "pitcherThrows")}
    hand_values = {}
    for name, identity_name, allowed in (("batterBats", "batterCanonicalPlayerId", {"L", "R", "S"}),
                                         ("pitcherThrows", "pitcherCanonicalPlayerId", {"L", "R"})):
        record = hand_sources[name]
        identity = field_evidence.get(identity_name)
        if (record and _source_reason(record, event_id, as_of) is None
                and identity and _source_reason(identity, event_id, as_of) is None
                and record.get("playerId") == identity.get("value")
                and record.get("value") in allowed):
            hand_values[name] = record["value"]
    if len(hand_values) == 2:
        bats, throws = hand_values["batterBats"], hand_values["pitcherThrows"]
        matchup = {"matchup_batter_bats_left": int(bats == "L"), "matchup_batter_bats_switch": int(bats == "S"),
                   "matchup_pitcher_throws_left": int(throws == "L"), "matchup_batter_hand_missing": 0,
                   "matchup_pitcher_hand_missing": 0, "matchup_platoon_advantage": int(bats == "S" or bats != throws)}
        for name, value in matchup.items():
            assign(name, value, "DERIVED_VERIFIED_HANDEDNESS", [_provenance(record) for record in hand_sources.values()])

    schema = prior_output_schema or {}
    additions = {item["name"]: item["sourceFeature"] for item in schema.get("additions", [])}
    bindings = schema.get("bindings", {})
    treated_support = []
    for name in treated_order:
        feature = additions.get(name, name)
        dependencies = {feature}
        if name in additions or feature in schema.get("wave2Features", []):
            binding = bindings.get(feature, {})
            dependencies.update(binding.get("missingIndicatorFeatures", []))
            dependencies.update(binding.get("numeratorComponents", []))
            dependencies.update(binding.get("compositionComponents", []))
            dependencies.update(binding.get("componentFields", {}).get("numerators", []))
            dependencies.update(key for key in (binding.get("playerIdentityFeature"), binding.get("exposureFeature"), "game_date") if key)
        missing = sorted(key for key in dependencies if key not in fields or not fields[key]["supported"])
        treated_support.append({"field": name, "sourceInputsSupported": not missing, "missingDependencies": missing,
                                "treatmentExecuted": False})
    missing_fields = [name for name in order if not fields[name]["supported"]]
    output = pd.DataFrame([{name: values[name] for name in order}], columns=order)
    coverage = {
        "schemaVersion": "MLB_V18_CURRENT_INPUT_COMPOSITION_COVERAGE_V1", "canonicalGameId": event_id,
        "gameDate": day.isoformat(), "asOfUtc": as_of.isoformat(), "scheduledStartUtc": kickoff.isoformat(),
        "battingSide": batting_side, "rawInputCount": len(order), "rawSupportedCount": len(order) - len(missing_fields),
        "rawMissingCount": len(missing_fields), "missingRawFields": missing_fields,
        "missingReasonCounts": dict(Counter(fields[name]["status"] for name in missing_fields)),
        "fields": [fields[name] for name in order], "treatedInputCount": len(treated_order),
        "treatedSourceSupportedCount": sum(row["sourceInputsSupported"] for row in treated_support),
        "treatedSourceMissingCount": sum(not row["sourceInputsSupported"] for row in treated_support),
        "treatedInputSupport": treated_support, "registeredContextImplementation": CONTEXT_FEATURE_VERSION,
        "status": "CURRENT_SOURCE_INPUTS_INCOMPLETE" if missing_fields else "CURRENT_SOURCE_INPUTS_COMPOSED_NOT_INFERRED",
        "upstreamBlockers": sorted({fields[name]["status"] for name in missing_fields}),
        "nextCodeIntegration": "EXPLICIT_PROSPECTIVE_TRANSFORM_SEAM_REQUIRED_WITH_FROZEN_PARAMETERS_AND_UNCHANGED_TREATMENT",
        "historicalTemplatesBorrowed": False, "coldStartInferredFromMissingEvidence": False,
        "parametersFitted": False, "inferenceExecuted": False, "dateGuardBypassed": False,
    }
    return output, coverage

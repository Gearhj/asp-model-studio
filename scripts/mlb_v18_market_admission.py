"""Pure admission checks for the frozen private V18/fresh-market pilot.

This module opens no files, calls no providers, and reads no outcomes. The caller
verifies the genuine completed SEALED ledger and supplies its hash-bound context.
``verify_ref`` verifies physical bytes (including any locator) and returns the
decoded referenced value. A forecast audit is computed only from the packet's
exact retained producer object; it cannot substitute another forecast or model.
Unknown quote conventions or per-leg clocks preserve a legitimate UNPRICED game.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import math
import re


MODEL_KEYS = ("engine", "paSha256", "transitionSha256", "parentBundleSha256",
              "treatmentManifestSha256", "calibration")
PACKET_KEYS = {"protocolSha256", "episodeKey", "sealedAtUtc", "attemptLedgerRef",
               "game", "anchor", "forecast", "selection", "market", "eligibility", "sourceRefs"}
SHA = re.compile(r"^[0-9a-f]{64}$")
UNKNOWN = ("UNKNOWN", "NOT_RETAINED", "UNPROVED", "UNPROVEN", "MISSING", "NOT_MEASURABLE")


def _utc(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timezone required")
    return result.astimezone(timezone.utc)


def _same_ref(left, right):
    return isinstance(left, dict) and isinstance(right, dict) and all(
        left.get(k) == right.get(k) for k in ("path", "sha256", "bytes", "locator"))


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _known(value):
    return bool(value) and not any(word in str(value).upper() for word in UNKNOWN)


def _identity_values(value):
    """Aliases can be arrays/maps; their shape cannot hide a quarantined game."""
    if isinstance(value, dict):
        for child in value.values():
            yield from _identity_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _identity_values(child)
    elif value is not None:
        yield str(value)


class _Checks:
    def __init__(self, verify_ref):
        self.verify_ref = verify_ref
        self.groups = {k: [] for k in ("packet", "forecast", "selection", "market")}
        self.warnings = []
        self.documents = []

    def fail(self, group, reason):
        if reason not in self.groups[group]:
            self.groups[group].append(reason)

    def require(self, condition, group, reason):
        if not condition:
            self.fail(group, reason)
        return bool(condition)

    def clock(self, value, group, reason):
        try:
            return _utc(value)
        except (TypeError, ValueError, OverflowError):
            self.fail(group, reason)
            return None

    def ref(self, value, group, label):
        if not (isinstance(value, dict) and isinstance(value.get("path"), str)
                and value["path"] and SHA.fullmatch(str(value.get("sha256", "")))
                and type(value.get("bytes")) is int and value["bytes"] >= 0):
            self.fail(group, label + "_REFERENCE_MISSING_OR_INVALID")
            return None
        try:
            result = self.verify_ref(value)
            if result is False or result is None:
                raise ValueError("No verified reference result")
            if isinstance(result, dict):
                self.documents.append(result)
            return result
        except Exception:
            self.fail(group, label + "_REFERENCE_VERIFICATION_FAILED")
            return None


def _rows(documents, table):
    selected = {}
    for document in documents:
        rows = document.get("rows", {}).get(table, {})
        if isinstance(rows, dict):
            selected.update(rows)
        elif isinstance(rows, list):
            selected.update({str(row.get("id")): row for row in rows if isinstance(row, dict)})
    return list(selected.values())


def _check_phase(check, game, phase, lock):
    if not check.require(game.get("phase") == "R", "packet", "PHASE_NOT_CERTIFIED_R"):
        return
    if not isinstance(phase, dict):
        check.fail("packet", "PHASE_SOURCE_EVIDENCE_UNAVAILABLE")
        return
    source_id = str((game.get("sourceGameIds") or {}).get("MLB_STATS_API") or
                    (game.get("sourceGameIds") or {}).get("mlbamGamePk") or "")
    # The reference may be a caller's identity-only projection, or the original
    # capture. Only schedule identity fields are inspected here.
    candidates = [phase.get("fields", phase)]
    schedule = (phase.get("payload") or {}).get("schedule") or {}
    for day in schedule.get("dates", []):
        candidates.extend(day.get("games", []))
    matches = [row for row in candidates if str(row.get("gamePk", row.get("sourceGameId", ""))) == source_id]
    check.require(bool(source_id) and len(matches) == 1 and matches[0].get("gameType") == "R",
                  "packet", "PHASE_SOURCE_GAME_BINDING_UNPROVEN")
    observed = (phase.get("archivedAtUtc") or phase.get("observedAtUtc") or
                (phase.get("metadata") or {}).get("ingestion_timestamp"))
    when = check.clock(observed, "packet", "PHASE_AVAILABILITY_CLOCK_MISSING")
    check.require(when is not None and lock is not None and when <= lock,
                  "packet", "PHASE_EVIDENCE_AFTER_LOCK")
    if len(matches) == 1:
        row = matches[0]
        for side in ("home", "away"):
            expected = (game.get(side + "SourceIds") or {}).get("MLB_STATS_API")
            observed_id = row.get(side + "TeamId") or (((row.get("teams") or {}).get(side) or {}).get("team") or {}).get("id")
            if expected is not None:
                check.require(str(expected) == str(observed_id), "packet", "PHASE_TEAM_ORIENTATION_MISMATCH")


def _check_quarantine(check, game, protocol, context):
    ref = context.get("quarantineRef") or protocol.get("quarantineLedgerAtFreeze")
    ledger = check.ref(ref, "packet", "QUARANTINE")
    gate = game.get("quarantineIdentityGate") or {}
    check.require(isinstance(ref, dict) and gate.get("ledgerSha256") == ref.get("sha256"),
                  "packet", "QUARANTINE_LEDGER_BINDING_MISMATCH")
    if not isinstance(ledger, dict) or not ledger.get("games"):
        check.fail("packet", "QUARANTINE_IDENTITY_EVIDENCE_UNAVAILABLE")
        return
    denied = set()
    for row in ledger["games"]:
        denied.update(str(row.get(key)) for key in ("canonicalGameId", "mlbamGamePk") if row.get(key) is not None)
        if row.get("mlbamGamePk") is not None:
            denied.add("mlbam:game:" + str(row["mlbamGamePk"]))
    aliases = {str(game.get("canonicalGameId", ""))}
    aliases.update(_identity_values(game.get("sourceGameIds") or {}))
    aliases.update(_identity_values(game.get("aliases") or []))
    check.require(not aliases.intersection(denied), "packet", "PERMANENT_WHOLE_GAME_QUARANTINE")
    check.require(ledger.get("permanent") is True, "packet", "QUARANTINE_LEDGER_NOT_PERMANENT")


def _check_anchor_and_selection(check, packet, lock, sealed, context):
    anchor, selection = packet.get("anchor") or {}, packet.get("selection") or {}
    note = check.ref(anchor.get("candidateDecisionsRef"), "forecast", "CANDIDATE_DECISIONS")
    export = check.ref(selection.get("consumerExportRef"), "selection", "SELECTION_EXPORT")
    at = check.clock(anchor.get("atUtc"), "forecast", "ANCHOR_CLOCK_INVALID")
    recorded = check.clock(selection.get("recordedAtUtc"), "selection", "SELECTION_RECORDING_CLOCK_INVALID")
    check.require(recorded is not None and sealed is not None and recorded <= sealed,
                  "selection", "SELECTION_RECORDED_AFTER_SEAL")
    evidence = context.get("evidenceDoc")
    if isinstance(evidence, dict):
        check.documents.append(evidence)
    decisions = _rows(check.documents, "shadow_experiment_decisions")
    positions = _rows(check.documents, "official_asp_positions")
    forecasts = _rows(check.documents, "shadow_forecasts")
    if isinstance(note, dict) and isinstance(note.get("decisions"), list):
        decisions = note["decisions"]
        positions = note.get("positions", [])
    candidates, valid_positions = [], []
    for row in decisions:
        try:
            when = _utc(row["recommended_at"])
        except (KeyError, TypeError, ValueError):
            check.fail("forecast", "DECISION_CLOCK_UNPROVEN")
            continue
        if row.get("game_id") != packet.get("game", {}).get("canonicalGameId") or row.get("phase") != "FINAL_PREGAME":
            continue
        if lock is not None and when <= lock:
            candidates.append((when, str(row.get("id", "")), row))
    for row in positions:
        try:
            when = _utc(row["placed_at"])
        except (KeyError, TypeError, ValueError):
            check.fail("selection", "POSITION_AS_OF_LOCK_UNPROVEN")
            continue
        if lock is not None and when <= lock:
            valid_positions.append(row)
    backed_ids = {str(row.get("shadow_decision_id")) for row in valid_positions}
    backed = [item for item in candidates if item[1] in backed_ids]
    for position in valid_positions:
        bound = next((item[2] for item in backed if item[1] == str(position.get("shadow_decision_id"))), None)
        check.require(bound is not None and bool(position.get("shadow_forecast_id")) and
                      str(position.get("shadow_forecast_id")) == str(bound.get("shadow_forecast_id")),
                      "forecast", "POSITION_DECISION_FORECAST_BINDING_UNPROVEN")
    chosen = None
    if len({(item[1], str(item[2].get("shadow_forecast_id"))) for item in backed}) > 1:
        check.fail("forecast", "ANCHOR_AMBIGUOUS_MULTIPLE_POSITION_DECISIONS")
    elif backed:
        chosen = backed[0]
        if lock - chosen[0] > timedelta(minutes=15):
            check.warnings.append("POSITION_DECISION_OUTSIDE_USUAL_T30_T15_WINDOW")
    else:
        usual = [item for item in candidates if lock is not None and lock - timedelta(minutes=15) <= item[0]]
        if usual:
            chosen = sorted(usual, key=lambda item: (-item[0].timestamp(), item[1]))[0]
    if isinstance(note, dict):
        declared_ids = set(map(str, note.get("allFinalPregameDecisionIds", [row.get("id") for row in decisions])))
        check.require(declared_ids.issubset({str(row.get("id")) for row in decisions}),
                      "forecast", "CANDIDATE_DECISION_ROWS_INCOMPLETE")
    usable = chosen is not None and chosen[2].get("shadow_forecast_id")
    if usable:
        check.require(anchor.get("kind") == "ACTUAL_DECISION" and anchor.get("decisionId") == chosen[1]
                      and at == chosen[0], "forecast", "ACTUAL_DECISION_ANCHOR_MISMATCH")
        identity = chosen[2].get("forecast_id")
        for row in forecasts:
            if str(row.get("id")) == str(chosen[2].get("shadow_forecast_id")):
                identity = row.get("forecast_id") or identity
        check.require(bool(identity) and identity == (packet.get("forecast") or {}).get("forecastIdentity"),
                      "forecast", "DECISION_FORECAST_IDENTITY_MISMATCH")
    else:
        check.require(anchor.get("kind") == "RESEARCH_T_MINUS_15" and at == lock and anchor.get("decisionId") is None,
                      "forecast", "RESEARCH_ANCHOR_MISMATCH")
        # Producer candidates are checked by the caller against exact physically
        # retained handoff availability, not consumer-created_at aliases.
        check.require(context.get("researchForecastSelectionVerified") is True,
                      "forecast", "LATEST_RESEARCH_FORECAST_SELECTION_UNPROVEN")
    complete = (isinstance(export, dict) and export.get("completeAsOfExport") is True
                and selection.get("completeAsOfExport") is True and not export.get("freezeRunsInFlightAtBuild")
                and bool(export.get("experiment") or export.get("experimentId")))
    status = selection.get("statusAtResearchLock")
    if status == "UNRESOLVED":
        check.fail("selection", "SELECTION_UNRESOLVED")
    else:
        check.require(complete, "selection", "SELECTION_COMPLETE_AS_OF_EXPORT_UNPROVEN")
        actual = "NO_FINAL_DECISION" if chosen is None else None
        if valid_positions and backed:
            actual = "SELECTED"
        elif chosen:
            rec = str(chosen[2].get("recommendation", "")).upper()
            if rec == "QUALIFIED_BET":
                actual = "SELECTED"
            elif rec in {"NO_BET", "PASS", "SKIP", "WAIT", "REJECTED", "NOT_QUALIFIED", "AVOID", "NO_ACTION", "BLOCKED"}:
                actual = "EVALUATED_NOT_SELECTED"
        check.require(actual is not None and status == actual, "selection", "SELECTION_AS_OF_STATUS_UNPROVEN")
    return at


def _check_forecast(check, packet, protocol, audit, anchor):
    forecast = packet.get("forecast")
    if not isinstance(forecast, dict):
        check.fail("forecast", "FORECAST_MISSING")
        return
    for key in ("objectRef", "inputSnapshotRef", "publicationReceiptRef", "scorePopulationRef"):
        check.ref(forecast.get(key), "forecast", key.upper())
    if packet.get("anchor", {}).get("kind") == "ACTUAL_DECISION":
        check.ref(forecast.get("importReceiptRef"), "forecast", "IMPORT_RECEIPT")
    if not isinstance(audit, dict):
        check.fail("forecast", "EXACT_PRODUCER_AUDIT_UNAVAILABLE")
        return
    for key in ("objectRef", "inputSnapshotRef"):
        check.require(_same_ref(audit.get(key), forecast.get(key)), "forecast", "AUDIT_" + key.upper() + "_BINDING_MISMATCH")
    physical = audit.get("physicalProducerRefs", [])
    check.require(bool(physical), "forecast", "PHYSICAL_PRODUCER_REFERENCES_REQUIRED")
    for ref in physical:
        check.ref(ref, "forecast", "PHYSICAL_PRODUCER")
    check.require(audit.get("forecastIdentity") == forecast.get("forecastIdentity"), "forecast", "AUDIT_FORECAST_IDENTITY_MISMATCH")
    for key in MODEL_KEYS:
        expected = protocol.get("model", {}).get(key)
        actual = audit.get("modelIdentity", {}).get(key)
        retained = forecast.get("modelIdentity", {}).get(key)
        check.require(expected is not None and actual == expected and retained in (None, expected),
                      "forecast", "FROZEN_MODEL_" + key.upper() + "_MISMATCH")
    check.require(audit.get("modelIdentity", {}).get("calibration") == "RETAIN_RAW_V18",
                  "forecast", "RAW_V18_CALIBRATION_REQUIRED")
    check.require(audit.get("rawInputCount") == 246 and audit.get("treatedInputCount") == 273,
                  "forecast", "FROZEN_FEATURE_CONTRACT_MISMATCH")
    check.require(audit.get("sourceEligibilityVerified") is True, "forecast", "SOURCE_ELIGIBILITY_UNPROVEN")
    check.require(audit.get("illegalStateCount") == 0 and audit.get("nonterminationCount") == 0,
                  "forecast", "ILLEGAL_OR_INCOMPLETE_SIMULATION")
    check.require(audit.get("seed") == forecast.get("seed") and forecast.get("seed") is not None,
                  "forecast", "ORIGINAL_SEED_MISMATCH")
    clocks = {}
    for key in ("createdAtUtc", "sourceCutoffUtc"):
        clocks[key] = check.clock(forecast.get(key), "forecast", key.upper() + "_INVALID")
        audited = check.clock(audit.get(key), "forecast", "AUDIT_" + key.upper() + "_INVALID")
        check.require(clocks[key] == audited, "forecast", "AUDIT_" + key.upper() + "_MISMATCH")
    created, cutoff = clocks.get("createdAtUtc"), clocks.get("sourceCutoffUtc")
    published = check.clock(audit.get("publicationCompletedAtUtc"), "forecast", "ACTUAL_PUBLICATION_BOUND_UNPROVEN")
    generated = check.clock(forecast.get("publicationCompletedAtUtc"), "forecast", "RETAINED_PUBLICATION_CLOCK_INVALID")
    check.require(all(value is not None for value in (created, cutoff, published, anchor, generated)) and
                  cutoff <= created <= published <= anchor and generated <= published,
                  "forecast", "FORECAST_NOT_AVAILABLE_BY_ANCHOR")
    if packet.get("anchor", {}).get("kind") == "ACTUAL_DECISION":
        imported = check.clock(audit.get("importReceiptCompletedAtUtc", forecast.get("importReceiptCompletedAtUtc")),
                               "forecast", "COMPLETED_IMPORT_BOUND_UNPROVEN")
        check.require(imported is not None and published is not None and anchor is not None and published <= imported <= anchor,
                      "forecast", "IMPORT_NOT_COMPLETED_BY_DECISION")
    source_clocks = forecast.get("sourceClockEvidence", [])
    for item in source_clocks:
        observed = check.clock(item.get("atUtc"), "forecast", "SOURCE_OBSERVATION_CLOCK_MISSING")
        check.require(observed is not None and cutoff is not None and observed <= cutoff,
                      "forecast", "SOURCE_OBSERVATION_AFTER_CUTOFF")
    pairs = audit.get("scorePairs")
    check.require(forecast.get("simulationCount") == 5000 and isinstance(pairs, list) and len(pairs) == 5000,
                  "forecast", "ORIGINAL_PAIRED_POPULATION_5000_REQUIRED")
    if isinstance(pairs, list) and len(pairs) == 5000:
        valid = all(isinstance(row, (list, tuple)) and len(row) == 2 and all(
            type(value) is int and value >= 0 for value in row) and row[0] != row[1] for row in pairs)
        check.require(valid, "forecast", "PAIRED_POPULATION_ILLEGAL_SCORE_OR_TIE")
        if valid:
            p = sum(home > away for home, away in pairs) / 5000
            home, away = forecast.get("pHome"), forecast.get("pAway")
            check.require(_finite(home) and _finite(away) and 0 <= home <= 1 and 0 <= away <= 1
                          and abs(home - p) <= 1e-12 and abs(home + away - 1) <= 1e-12,
                          "forecast", "RAW_PROBABILITY_POPULATION_MISMATCH")
            saved_se = (forecast.get("samplingError") or {}).get("value")
            if saved_se is None:
                saved_se = audit.get("samplingError")
            check.require(_finite(saved_se) and abs(saved_se - math.sqrt(p * (1 - p) / 5000)) <= 1e-10,
                          "forecast", "RECORDED_SAMPLING_ERROR_MISSING_OR_MISMATCH")
    if not forecast.get("deploymentAttestation"):
        check.warnings.append("NO_PER_FORECAST_DEPLOYMENT_ATTESTATION_RETAINED")


def _pair(check, pair, game, anchor):
    reasons = []
    def require(condition, reason):
        if not condition and reason not in reasons:
            reasons.append(reason)
    if not isinstance(pair, dict):
        return None, ["MALFORMED_BOOK_PAIR"]
    book, provider = pair.get("bookKey"), pair.get("providerKey")
    require(isinstance(book, str) and bool(book.strip()) and book == book.strip(), "CANONICAL_BOOK_KEY_MISSING")
    require(isinstance(provider, str) and bool(provider.strip()) and provider == provider.strip(), "CANONICAL_PROVIDER_KEY_MISSING")
    require(not any(word in str(provider).upper() for word in ("POLYMARKET", "KALSHI", "EXCHANGE", "PREDICTION_MARKET")),
            "NON_BOOKMAKER_PRICE_EXCLUDED")
    require(pair.get("period") == "full_game" and bool(pair.get("marketId")), "FULL_GAME_MONEYLINE_REQUIRED")
    conventions = pair.get("conventions") or {}
    require(_known(conventions.get("extraInnings")) and
            (conventions.get("extraInnings") is True or "INCLUDED" in str(conventions.get("extraInnings")).upper()),
            "EXTRA_INNINGS_CONVENTION_UNPROVEN")
    require(conventions.get("settlementRule") in {"TWO_WAY_NO_TIE", "TWO_WAY_DECISIVE_RESULT"}, "SETTLEMENT_CONVENTION_UNPROVEN")
    require(_known(conventions.get("pitcherActionRule")), "PITCHER_ACTION_CONVENTION_UNPROVEN")
    before = len(check.groups["market"])
    response = check.ref(pair.get("sourceResponseRef"), "market", "SOURCE_RESPONSE")
    require(response is not None, "SOURCE_RESPONSE_UNVERIFIED")
    # Claimed parser conventions require retained source/rule evidence, not a
    # plain eligible flag or an unreferenced exporter assertion.
    convention_ref = conventions.get("evidenceRef") or pair.get("conventionsEvidenceRef")
    convention_source = check.ref(convention_ref, "market", "CONVENTIONS")
    require(isinstance(convention_source, dict) and all(convention_source.get(key) == conventions.get(key)
            for key in ("extraInnings", "settlementRule", "pitcherActionRule")), "CONVENTIONS_SOURCE_EVIDENCE_UNPROVEN")
    require("MONEYLINE" in str(conventions.get("market", "")).upper() or conventions.get("market") == "h2h",
            "MONEYLINE_MARKET_CONVENTION_UNPROVEN")
    snapshot = str(pair.get("snapshotId") or (response or {}).get("snapshotId") or "") if isinstance(response, dict) else ""
    response_sha = (response or {}).get("rawResponseSha256") if isinstance(response, dict) else None
    require(bool(snapshot) and isinstance(response, dict) and
            (SHA.fullmatch(str(response_sha or "")) is not None or response.get("responseIdentityVerified") is True),
            "SAME_PROVIDER_RESPONSE_IDENTITY_UNPROVEN")
    if isinstance(response, dict):
        require(response.get("provider", response.get("providerKey", provider)) == provider, "RESPONSE_PROVIDER_MISMATCH")
        source_ids = set(str(value) for value in (game.get("sourceGameIds") or {}).values())
        response_game = response.get("canonicalGameId")
        source_event = response.get("sourceEventId", pair.get("sourceEventId"))
        require(response_game == game.get("canonicalGameId") or str(source_event) in source_ids, "RESPONSE_GAME_BINDING_UNPROVEN")
    clocks, availability, decimals = [], [], []
    for side in ("home", "away"):
        leg = pair.get(side)
        if not isinstance(leg, dict):
            require(False, side.upper() + "_LEG_MISSING")
            continue
        require(leg.get("teamId") == game.get(side + "Id"), side.upper() + "_ORIENTATION_MISMATCH")
        require(str(leg.get("status", "")).upper() == "OPEN", side.upper() + "_MARKET_NOT_OPEN")
        meaning = str(leg.get("clockMeaning", "")).upper()
        require(bool(meaning) and "PER-SIDE STAMPS NOT RETAINED" not in meaning and
                "OLDER PROVIDER SIDE UPDATE APPLIED TO BOTH" not in meaning and
                "NOT A RECEIPT" not in meaning and "NO COMPLETED RECEIPT" not in meaning,
                side.upper() + "_INDIVIDUAL_QUOTE_CLOCK_UNPROVEN")
        require(leg.get("perLegQuoteClockVerified") is True or
                ("BOOKMAKER" in meaning and "UPDATE" in meaning and "PER_LEG" in meaning),
                side.upper() + "_INDIVIDUAL_QUOTE_CLOCK_UNPROVEN")
        leg_source = check.ref(leg.get("rowRef"), "market", side.upper() + "_QUOTE_ROW")
        require(isinstance(leg_source, dict) and leg_source.get("quoteClockSource") == "BOOKMAKER_PER_LEG_UPDATE"
                and leg_source.get("quoteUpdatedAtUtc") == leg.get("quoteUpdatedAtUtc")
                and leg_source.get("teamId") == leg.get("teamId"), side.upper() + "_SOURCE_LEG_CLOCK_BINDING_UNPROVEN")
        require(isinstance(leg_source, dict) and leg_source.get("american") == leg.get("american")
                and all(leg_source.get(key) == expected for key, expected in (("bookKey", book),
                    ("providerKey", provider), ("marketId", pair.get("marketId")), ("snapshotId", snapshot))),
                side.upper() + "_SOURCE_PRICE_IDENTITY_UNPROVEN")
        try:
            observed, available = _utc(leg.get("quoteUpdatedAtUtc")), _utc(leg.get("availableByUtc"))
            require(anchor is not None and 0 <= (anchor - observed).total_seconds() <= 900,
                    side.upper() + "_QUOTE_STALE_FUTURE_OR_NO_ANCHOR")
            require(anchor is not None and observed <= available <= anchor, side.upper() + "_NOT_AVAILABLE_BY_ANCHOR")
            clocks.append(observed)
            availability.append(available)
        except (TypeError, ValueError, OverflowError):
            require(False, side.upper() + "_QUOTE_CLOCK_MISSING")
            observed, available = None, None
        receipt = check.ref(leg.get("availabilityReceiptRef"), "market", side.upper() + "_AVAILABILITY")
        require(leg.get("availableByIsReceipt") is not False and isinstance(receipt, dict), side.upper() + "_RECEIPT_BOUND_UNPROVEN")
        if isinstance(receipt, dict):
            completion = receipt.get("completedAtUtc", receipt.get("completed_at"))
            try:
                bound = _utc(completion)
                require(available is not None and bound <= available and
                        str(receipt.get("status", "")).upper() in {"COMPLETED", "SUCCESS", "SUCCEEDED"},
                        side.upper() + "_RECEIPT_BOUND_UNPROVEN")
            except (TypeError, ValueError, OverflowError):
                require(False, side.upper() + "_RECEIPT_BOUND_UNPROVEN")
        for key, expected in (("bookKey", book), ("providerKey", provider), ("marketId", pair.get("marketId")),
                              ("snapshotId", snapshot), ("period", "full_game")):
            require(leg.get(key) == expected, side.upper() + "_" + key.upper() + "_BINDING_UNPROVEN")
        require(leg.get("conventions") == conventions, side.upper() + "_CONVENTIONS_MISMATCH")
        try:
            american = leg.get("american")
            if type(american) is not int or -100 < american < 100:
                raise ValueError("Invalid American odds")
            exact = Decimal(1) + (Decimal(american) / 100 if american > 0 else Decimal(100) / -american)
            decimal = Decimal(str(leg.get("decimal")))
            require(decimal.is_finite() and decimal > 1 and abs(decimal - exact) <= Decimal("0.000000001"),
                    side.upper() + "_AMERICAN_DECIMAL_DISAGREEMENT")
            decimals.append(float(exact))
        except (ValueError, TypeError, InvalidOperation, ArithmeticError):
            require(False, side.upper() + "_INVALID_PRICE")
    # Candidate-local reference failures do not invalidate another valid book.
    reasons.extend(check.groups["market"][before:])
    del check.groups["market"][before:]
    if reasons or len(clocks) != 2 or len(decimals) != 2:
        return None, list(dict.fromkeys(reasons))
    rh, ra = 1 / decimals[0], 1 / decimals[1]
    return {**deepcopy(pair), "eligible": True, "reasonCodes": [], "qHome": rh / (rh + ra),
            "overround": rh + ra - 1, "olderLegObservedAtUtc": min(clocks).isoformat(),
            "pairAvailableByUtc": max(availability).isoformat(),
            "legSkewSeconds": abs((clocks[0] - clocks[1]).total_seconds()), "snapshotId": snapshot}, []


def _validate_packet(packet, protocol, verify_ref, now, *, forecast_audit=None):
    """Validate sealed evidence without changing its bytes or consulting outcomes.

    ``protocol['_admissionContext']`` supplies verified completion-ledger metadata,
    readiness/authority clocks, optional exact sealed evidence, and the current
    quarantine reference. Later validation is allowed; the seal itself must be
    prospective. Caller-derived ``forecast_audit`` is described in the tests.
    """
    check = _Checks(verify_ref)
    candidates = []
    selected = None
    context = protocol.get("_admissionContext") or {}
    if not isinstance(packet, dict):
        packet = {}
    check.require(set(packet) == PACKET_KEYS, "packet", "PACKET_TOP_LEVEL_SCHEMA_MISMATCH")
    check.require(packet.get("protocolSha256") == protocol.get("protocolSha256") and
                  SHA.fullmatch(str(packet.get("protocolSha256", ""))) is not None,
                  "packet", "FROZEN_PROTOCOL_IDENTITY_MISMATCH")
    current = check.clock(now, "packet", "VALIDATION_CLOCK_INVALID")
    build = check.clock(packet.get("sealedAtUtc"), "packet", "PACKET_BUILD_CLOCK_INVALID")
    completed = check.clock(context.get("sealCompletedAtUtc"), "packet", "GENUINE_SEAL_COMPLETION_UNPROVEN")
    ledger = check.ref(context.get("sealLedgerRef"), "packet", "COMPLETED_SEAL_LEDGER")
    if isinstance(ledger, dict):
        check.require(ledger.get("kind") == "SEALED" and ledger.get("episodeKey") == packet.get("episodeKey"),
                      "packet", "COMPLETED_SEAL_LEDGER_BINDING_MISMATCH")
        written = check.clock(ledger.get("writtenAtUtc"), "packet", "LEDGER_COMPLETION_CLOCK_INVALID")
        check.require(written == completed, "packet", "SEAL_COMPLETION_CLOCK_MISMATCH")
        check.require(SHA.fullmatch(str(context.get("packetSha256", ""))) is not None and
                      ledger.get("packetSha256") == context.get("packetSha256"), "packet", "SEALED_PACKET_HASH_MISMATCH")
    game, anchor = packet.get("game") or {}, packet.get("anchor") or {}
    start = check.clock(game.get("scheduledStartUtc"), "packet", "SCHEDULE_START_INVALID")
    lock = check.clock(anchor.get("researchLockUtc"), "packet", "RESEARCH_LOCK_INVALID")
    deadline = check.clock(anchor.get("sealDeadlineUtc"), "packet", "SEAL_DEADLINE_INVALID")
    first_seen = check.clock(game.get("firstSeenAtUtc"), "packet", "FIRST_SEEN_CLOCK_INVALID")
    opening = check.clock(protocol.get("window", {}).get("openingUtc"), "packet", "OPENING_CLOCK_INVALID")
    close = check.clock(protocol.get("window", {}).get("closeUtc"), "packet", "CLOSING_CLOCK_INVALID")
    frozen = check.clock(protocol.get("frozenAtUtc"), "packet", "FREEZE_CLOCK_INVALID")
    ready = check.clock(context.get("readinessAtUtc"), "packet", "CONSUMER_READINESS_UNPROVEN")
    expiry = check.clock(context.get("authorityExpiresAtUtc"), "packet", "SOURCE_AUTHORITY_EXPIRY_UNPROVEN")
    check.require(bool(game.get("canonicalGameId")) and bool(game.get("sourceGameIds")) and
                  bool(game.get("homeId")) and bool(game.get("awayId")) and game.get("homeId") != game.get("awayId")
                  and bool(game.get("scheduleRevision")) and bool(packet.get("episodeKey")),
                  "packet", "GAME_SCHEDULE_IDENTITY_INCOMPLETE")
    if all(v is not None for v in (start, lock, deadline)):
        check.require(lock <= start - timedelta(minutes=15) and deadline == start - timedelta(minutes=5),
                      "packet", "LOCK_OR_SEAL_DEADLINE_WIDENED")
        if context.get("earliestResearchLockUtc"):
            check.require(lock == _utc(context["earliestResearchLockUtc"]), "packet", "EARLIEST_SCHEDULE_LOCK_MISMATCH")
    if all(v is not None for v in (build, completed, deadline, start, current, lock)):
        check.require(lock <= build <= completed <= deadline and completed < start and completed <= current,
                      "packet", "LATE_OR_BACKDATED_PACKET_SEAL")
    if all(v is not None for v in (opening, close, frozen, ready, expiry, lock, build, completed)):
        check.require(max(opening, frozen, ready) <= lock < min(close, expiry) and completed <= expiry,
                      "packet", "ENROLLMENT_WINDOW_OR_AUTHORITY_VIOLATION")
    check.require(first_seen is not None and lock is not None and first_seen <= lock, "packet", "LATE_DISCOVERED_GAME")
    if context.get("knownActualStartUtc"):
        actual = check.clock(context["knownActualStartUtc"], "packet", "ACTUAL_START_CLOCK_INVALID")
        check.require(actual is not None and completed is not None and completed < actual, "packet", "SEALED_AFTER_KNOWN_ACTUAL_START")
    check.ref(packet.get("attemptLedgerRef"), "packet", "ATTEMPT_LEDGER")
    for ref in packet.get("sourceRefs") or []:
        check.ref(ref, "packet", "SOURCE")
    check.require(bool(packet.get("sourceRefs")), "packet", "SOURCE_REFERENCES_REQUIRED")
    phase = check.ref(game.get("phaseEvidenceRef"), "packet", "PHASE")
    _check_phase(check, game, phase, lock)
    _check_quarantine(check, game, protocol, context)
    at = _check_anchor_and_selection(check, packet, lock, completed, context)
    _check_forecast(check, packet, protocol, forecast_audit, at)
    eligible_pairs = []
    for candidate in (packet.get("market") or {}).get("candidates", []):
        result, reasons = _pair(check, candidate, game, at)
        candidates.append({"bookKey": candidate.get("bookKey") if isinstance(candidate, dict) else None,
            "providerKey": candidate.get("providerKey") if isinstance(candidate, dict) else None,
            "snapshotId": candidate.get("snapshotId") if isinstance(candidate, dict) else None,
            "eligible": result is not None, "reasonCodes": reasons})
        if result is not None:
            eligible_pairs.append(result)
    if eligible_pairs:
        # An asserted stable snapshot cannot name two different prices. Refuse
        # the ambiguity instead of depending on input list order.
        ambiguous = set()
        snapshot_values = {}
        for pair in eligible_pairs:
            identity = pair["bookKey"], pair["providerKey"], pair["snapshotId"]
            value = (pair["home"]["american"], pair["away"]["american"],
                     pair["olderLegObservedAtUtc"], pair["pairAvailableByUtc"],
                     pair["sourceResponseRef"]["sha256"])
            if identity in snapshot_values and snapshot_values[identity] != value:
                ambiguous.add(identity)
            snapshot_values[identity] = value
        if ambiguous:
            eligible_pairs = [pair for pair in eligible_pairs if
                (pair["bookKey"], pair["providerKey"], pair["snapshotId"]) not in ambiguous]
            check.warnings.append("CONFLICTING_STABLE_SNAPSHOT_ID_EXCLUDED")
        if not eligible_pairs:
            check.fail("market", "UNPRICED_CONFLICTING_STABLE_SNAPSHOT_ID")
        by_book = {}
        for pair in eligible_pairs:
            key = pair["bookKey"], pair["providerKey"]
            sort_key = (-_utc(pair["olderLegObservedAtUtc"]).timestamp(),
                        -_utc(pair["pairAvailableByUtc"]).timestamp(), pair["snapshotId"])
            if key not in by_book or sort_key < by_book[key][0]:
                by_book[key] = sort_key, pair
        if by_book:
            selected = by_book[min(by_book)][1]
    else:
        check.fail("market", "UNPRICED_NO_ELIGIBLE_BOOK")
        for candidate in candidates:
            for reason in candidate["reasonCodes"]:
                check.fail("market", reason)
    forecast_ok = not check.groups["packet"] and not check.groups["forecast"]
    price_ok = not check.groups["packet"] and selected is not None
    selection_ok = not check.groups["packet"] and not check.groups["selection"]
    reasons = list(dict.fromkeys(reason for group in check.groups.values() for reason in group))
    return {"forecastEligible": forecast_ok, "priceEvaluable": price_ok,
            "selectionAscertained": selection_ok, "enrollmentEligible": forecast_ok,
            "pairedMetricEligible": forecast_ok and price_ok, "reasons": reasons,
            "reasonCodes": reasons, "firstFailure": reasons[0] if reasons else None,
            "selectedPair": selected, "qHome": selected["qHome"] if price_ok else None,
            "marketStatus": "FRESH_PAIRED" if price_ok else "UNPRICED",
            "warnings": list(dict.fromkeys(check.warnings)), "candidateDiagnostics": candidates,
            "reasonGroups": check.groups, "validatedAtUtc": current.isoformat() if current else None}


def validate_packet(packet, protocol, verify_ref, now, *, forecast_audit=None):
    """Return fail-closed flags for a private packet; perform no external I/O.

    The caller's reference verifier must verify physical bytes and then resolve
    any locator. The trusted context and producer-audit interface are documented
    in this module and exercised with complete synthetic evidence in its tests.
    ``now`` is the real validation time, and may follow a genuine pregame seal.
    """
    try:
        return _validate_packet(packet, protocol, verify_ref, now, forecast_audit=forecast_audit)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, OverflowError):
        # A malformed record cannot abort processing of other sealed attempts or
        # accidentally become eligible through omitted/type-coerced fields.
        reason = "MALFORMED_PACKET_OR_CONTEXT"
        return {"forecastEligible": False, "priceEvaluable": False, "selectionAscertained": False,
                "enrollmentEligible": False, "pairedMetricEligible": False,
                "reasons": [reason], "reasonCodes": [reason], "firstFailure": reason,
                "selectedPair": None, "qHome": None, "marketStatus": "UNPRICED",
                "warnings": [], "candidateDiagnostics": [], "reasonGroups": {"packet": [reason]},
                "validatedAtUtc": None}

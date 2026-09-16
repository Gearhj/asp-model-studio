"""Prospective descriptive market ledger; no market fetch, model fit or decision."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from server.audit_assurance.canonical import canonical_json_bytes
from .labs_simulation import AUTHORITY, file_record, immutable_json
from .research_benchmarks import conditional_home, no_vig_home, timestamp_matched_quotes

OUTPUTS_ROOT = Path(__file__).resolve().parents[2] / "outputs"
MARKETS = ("MONEYLINE", "SPREAD", "TOTAL")
OBSERVED = "OBSERVED_AS_OF"
RECONSTRUCTED = "RETROSPECTIVE_RECONSTRUCTED_AS_OF"
EXPORT_CONTRACT = {
    "schemaVersion": "NFL_AISP_TIMED_QUOTE_EXPORT_CONTRACT_V1",
    "evidenceClass": OBSERVED,
    "evidenceMeaning": "Observed configuration record only; this contract is not an empirical quote, source vintage or validation result.",
    "requiredEnvelope": {"schemaVersion": "NFL_AISP_TIMED_QUOTE_SNAPSHOTS_V1", "exportId": "immutable export identity",
        "exportedAtUtc": "timezone-aware export creation time; never used as original quote time",
        "sourceUseAuthority": "nonempty applicable source identities, permissions, attribution and restrictions", "snapshots": "array of original quote records"},
    "requiredPerSnapshot": {"quoteId": "unique immutable quote identity", "sourceSnapshotId": "original capture/snapshot identity",
        "eventId": "canonical nflverse event ID, e.g.2026_01_SF_LA", "homeTeamId": "canonical home ID, e.g.LAR", "awayTeamId": "canonical away ID",
        "bookmaker": "original book/source identity", "marketType": "MONEYLINE, SPREAD or TOTAL",
        "observedAtUtc": "original timezone-aware local observation time of this price, not provider update or export time",
        "firstAvailableAtUtc": "original timezone-aware time this quote became available to AISP; never inferred from a later export",
        "settlementContract": "explicit full-game/OT/tie/push convention"},
    "perMarketFields": {"MONEYLINE": ["homeMoneyline", "awayMoneyline"],
        "SPREAD": ["spreadLineHomeHandicap", "homeSpreadOdds", "awaySpreadOdds"],
        "TOTAL": ["totalLine", "overOdds", "underOdds"]},
    "priceRepresentation": "American odds for all odds fields, not decimal odds; retain original values. Lines are points; spreadLineHomeHandicap is the signed handicap added to home minus away.",
    "optionalOriginalMetadata": ["sourcePublishedAtUtc", "providerUpdatedAtUtc", "sourceUrl", "sourceUseAuthority", "marketId"],
    "joinRules": ["Same event and canonical home/away identities; each model forecast remains distinct.",
        "Quote observedAt and firstAvailableAt must both be <= frozen forecastCutoffUtc < scheduledStartUtc.",
        "Latest eligible two-way moneyline per bookmaker; FULL_GAME_INCLUDING_OT_TIE_VOID only.",
        "Spread/total snapshots may be retained, but automated line comparison remains unsupported in this bounded exporter.",
        "No outcomes, positions or stakes are required. No model uses the supplied market values."],
    "missingDataRule": "Missing or untimed sportsbook evidence remains pending; no price, time, settlement convention or wagering edge is inferred.",
}


def _utc(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _load(ref):
    path = Path(ref["path"]).resolve()
    if not path.is_relative_to(OUTPUTS_ROOT.resolve()):
        raise ValueError("comparison reads only dedicated Model Studio output artifacts")
    actual = file_record(path)
    if actual["sha256"] != ref["sha256"] or actual["byteCount"] != ref["byteCount"]:
        raise ValueError("comparison artifact checksum or byte count differs")
    return json.loads(path.read_bytes())


def _put(root, name, body):
    digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    return {**immutable_json(Path(root) / "sha256" / digest / name, body), "evidenceClass": OBSERVED}


def horizon_bin(seconds):
    if seconds <= 0:
        raise ValueError("a retrospective or started-event forecast is not prospective")
    return "<1h" if seconds < 3600 else "1-6h" if seconds < 21600 else "6-24h" if seconds < 86400 else ">=24h"


def prepare_market_comparison(handoff_ref, output, quotes=None):
    """Prepare pending rows or join an explicitly supplied immutable export.

    `quotes` is an already available export object, never a URL/database handle.
    Only moneyline comparison is implemented by the existing timed-quote helper.
    """
    output = Path(output).resolve()
    if not output.is_relative_to(OUTPUTS_ROOT.resolve()) or output == OUTPUTS_ROOT.resolve():
        raise ValueError("comparison needs a dedicated Model Studio outputs subdirectory")
    handoff = _load(handoff_ref)
    if (handoff.get("schemaVersion") != "NFL_CURRENT_STATE_JOINT_DISTRIBUTION_HANDOFF_V2"
            or handoff.get("status") != "RESEARCH_SHADOW" or handoff.get("wageringAuthority") is not False
            or handoff.get("executionAllowedInAISP") is not False):
        raise ValueError("expected nonexecuting current-state V2 research handoff")
    supplied = [] if quotes is None else quotes["snapshots"]
    if quotes is not None:
        if (quotes.get("schemaVersion") != "NFL_AISP_TIMED_QUOTE_SNAPSHOTS_V1"
                or not quotes.get("exportId") or not quotes.get("sourceUseAuthority")):
            raise ValueError("timed-quote source identity and use authority are required")
        _utc(quotes["exportedAtUtc"])
        if not isinstance(supplied, list):
            raise ValueError("snapshots must be an explicit list")
        required = set(EXPORT_CONTRACT["requiredPerSnapshot"])
        for quote in supplied:
            if not required <= quote.keys() or any(quote[key] is None for key in required):
                raise ValueError("original quote identity, availability and settlement fields are required")
            if quote.get("evidenceClass", OBSERVED) != OBSERVED:
                raise ValueError("current quote snapshots must be classified OBSERVED_AS_OF")
        ids = [quote["quoteId"] for quote in supplied]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate immutable quote identity")
    identity = hashlib.sha256(canonical_json_bytes({"handoff": handoff_ref, "quotes": quotes,
        "implementation": file_record(Path(__file__)), "exportContract": EXPORT_CONTRACT})).hexdigest()
    identity_path = output / "identities" / identity / "receipt.json"
    if identity_path.is_file():
        previous = json.loads(identity_path.read_bytes())
        _load(previous["comparison"]); _load(previous["contract"])
        return {**previous, "reused": True}
    rows, decisions, model_rows = [], [], []
    seen_forecasts = set()
    event_ids = set()
    for ref in handoff.get("forecasts", []):
        forecast = _load(ref)
        identity_key = forecast["forecastId"]
        if identity_key in seen_forecasts:
            raise ValueError("duplicate forecast identity in immutable handoff")
        seen_forecasts.add(identity_key); event_ids.add(forecast["eventId"])
        cutoff, kickoff, created = (_utc(forecast[key]) for key in ("forecastCutoffUtc", "scheduledStartUtc", "forecastCreatedUtc"))
        if cutoff > created or created >= kickoff:
            raise ValueError("forecast snapshot or creation time is not pre-kickoff")
        probabilities = [float(forecast[key]) for key in ("awayWinProbability", "tieProbability", "homeWinProbability")]
        conditional = float(conditional_home(np.array([probabilities[0]]), np.array([probabilities[1]]), np.array([probabilities[2]]))[0])
        model = {"forecastId": identity_key, "eventId": forecast["eventId"], "modelId": forecast["model"]["engineId"],
            "evidenceClass": OBSERVED, "trainingEvidenceClass": RECONSTRUCTED,
            "modelVersion": forecast["model"]["modelVersion"], "forecastArtifact": ref,
            "homeTeamId": forecast["homeTeam"]["teamId"], "awayTeamId": forecast["awayTeam"]["teamId"],
            **{key: forecast[key] for key in ("forecastCreatedUtc", "forecastCutoffUtc", "scheduledStartUtc", "sourceCutoffUtc",
                                              "homeWinProbability", "awayWinProbability", "tieProbability", "expectedHomeScore", "expectedAwayScore")},
            "forecastHorizonSeconds": (kickoff-cutoff).total_seconds(), "forecastHorizonBin": horizon_bin((kickoff-cutoff).total_seconds()),
            "conditionalHomeProbabilityTieVoid": conditional, "marketInputsUsed": False, "modelArtifactModified": False}
        model_rows.append(model)
        eligible = []
        for quote in supplied:
            if quote["eventId"] != model["eventId"]:
                continue
            reason = None
            if (quote["homeTeamId"], quote["awayTeamId"]) != (model["homeTeamId"], model["awayTeamId"]):
                reason = "TEAM_IDENTITY_MISMATCH"
            try:
                observed, available = _utc(quote["observedAtUtc"]), _utc(quote["firstAvailableAtUtc"])
                if reason is None and (observed > cutoff or available > cutoff):
                    reason = "QUOTE_OR_FIRST_AVAILABILITY_AFTER_FORECAST_CUTOFF"
                if reason is None and available < observed:
                    reason = "QUOTE_AVAILABILITY_PRECEDES_OBSERVATION"
            except (ValueError, TypeError):
                reason = reason or "QUOTE_TIME_UNAVAILABLE_OR_NOT_TIMEZONE_AWARE"
            if reason is None and quote["marketType"] != "MONEYLINE":
                reason = "MARKET_AXIS_NOT_IMPLEMENTED_RETAINED_WITHOUT_COMPARISON"
            if reason is None:
                selected, counts = timestamp_matched_quotes(pd.DataFrame([quote]), pd.DataFrame([model]))
                if not len(selected):
                    reason = next(iter(counts))
                else:
                    eligible.append(quote)
            decisions.append({"forecastId": identity_key, "quoteId": quote["quoteId"], "eventId": quote["eventId"],
                              "evidenceClass": OBSERVED, "disposition": reason or "ELIGIBLE_PENDING_LATEST_SELECTION",
                              "snapshot": {**quote, "evidenceClass": OBSERVED}})
        selected_ids = set()
        if eligible:
            selected, _ = timestamp_matched_quotes(pd.DataFrame(eligible), pd.DataFrame([model]))
            for _, quote in selected.iterrows():
                selected_ids.add(quote.quoteId)
                market_home = float(no_vig_home(np.array([float(quote.homeMoneyline)]), np.array([float(quote.awayMoneyline)]))[0])
                rows.append({"forecastId": identity_key, "eventId": model["eventId"], "marketType": "MONEYLINE",
                             "evidenceClass": OBSERVED, "trainingEvidenceClass": RECONSTRUCTED,
                             "status": "DESCRIPTIVE_TIMESTAMP_MATCHED_NO_OUTCOME_EVALUATION", "bookmaker": quote.bookmaker,
                             "quoteId": quote.quoteId, "quoteAgeSeconds": float(quote.quoteAgeSeconds),
                             "forecastHorizonBin": model["forecastHorizonBin"], "conditionalModelHomeProbability": conditional,
                             "proportionalNoVigMarketHomeProbability": market_home,
                             "modelMinusMarketProbability": conditional-market_home, "wageringEdgeClaim": False})
        for decision in decisions:
            if decision["forecastId"] == identity_key and decision["disposition"] == "ELIGIBLE_PENDING_LATEST_SELECTION":
                decision["disposition"] = "INCLUDED" if decision["quoteId"] in selected_ids else "NOT_LATEST_ELIGIBLE_PER_BOOKMAKER"
        for market in MARKETS:
            if market != "MONEYLINE" or not selected_ids:
                rows.append({"forecastId": identity_key, "eventId": model["eventId"], "marketType": market,
                             "evidenceClass": OBSERVED, "trainingEvidenceClass": RECONSTRUCTED,
                             "forecastHorizonBin": model["forecastHorizonBin"], "status": "PENDING_COMPARISON",
                             "reason": "NO_AUTHORIZED_TIMESTAMPED_SPORTSBOOK_SNAPSHOT" if not supplied else
                                "NO_ELIGIBLE_TIMESTAMP_MATCHED_MONEYLINE" if market == "MONEYLINE" else "MARKET_AXIS_NOT_IMPLEMENTED",
                             "quoteId": None, "wageringEdgeClaim": False})
    if len(model_rows) != handoff["forecastCount"]:
        raise ValueError("forecast count differs from handoff")
    for quote in supplied:
        if quote["eventId"] not in event_ids:
            decisions.append({"forecastId": None, "quoteId": quote["quoteId"], "eventId": quote["eventId"],
                              "evidenceClass": OBSERVED, "disposition": "EVENT_NOT_IN_HANDOFF", "snapshot": {**quote, "evidenceClass": OBSERVED}})
    contract = _put(output / "contracts", "aisp-timed-quote-export-contract.json", EXPORT_CONTRACT)
    snapshot_ref = _put(output / "quote-exports", "supplied-quotes.json", {
        "schemaVersion": "NFL_SUPPLIED_TIMED_QUOTE_EXPORT_RECEIPT_V1", "evidenceClass": OBSERVED,
        "evidenceMeaning": "Preserved supplied observations with original availability timestamps; no source retrieval occurred here.",
        "originalExport": quotes, "snapshots": [{**quote, "evidenceClass": OBSERVED} for quote in supplied]}) if quotes is not None else None
    body = {"schemaVersion": "NFL_CURRENT_STATE_PROSPECTIVE_MARKET_COMPARISON_V1", **AUTHORITY,
        "evidenceClass": OBSERVED, "trainingEvidenceClass": RECONSTRUCTED,
        "createdAtUtc": datetime.now(timezone.utc).isoformat(), "handoff": handoff_ref, "exportContract": contract,
        "status": "PENDING_TIMESTAMPED_MARKET_EVIDENCE" if not supplied else "DESCRIPTIVE_ONLY",
        "modelLifecycle": "RESEARCH_SHADOW", "comparisonIdentity": identity, "forecastCount": len(model_rows), "eventCount": len(event_ids),
        "suppliedQuoteCount": len(supplied), "quoteExport": snapshot_ref, "modelOnlyForecasts": model_rows,
        "comparisons": rows, "quoteDecisions": decisions, "providerCalls": 0, "modelFits": 0, "aispReads": 0, "aispWrites": 0,
        "modelInputsChanged": False, "outcomesRead": False, "selectionOrThresholdOptimization": False,
        "limitations": ["Probability differences are descriptive, not wagering edge or executable prices.",
            "Conditional two-way tie-void moneyline comparison does not replace original home/away/tie probabilities.",
            "Spread/total comparison is not implemented; unavailable snapshots and unsupported axes remain explicit.",
            "Forecast horizon and quote age are reported without selecting an optimized freshness threshold."]}
    ref = _put(output / "comparisons", "comparison.json", body)
    receipt = {"comparison": ref, "contract": contract, "forecastCount": len(model_rows), "eventCount": len(event_ids),
               "evidenceClass": OBSERVED,
               "suppliedQuoteCount": len(supplied), "status": body["status"], "reused": False}
    immutable_json(identity_path, receipt)
    return receipt

"""Descriptive, non-optimizing cohort builder for existing AISP Gen 1 evidence."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from server.sports_datasets.consumer import canonical_json_bytes


EXPORT_SCHEMA_VERSION = "AISP_GEN1_BET_READINESS_READ_ONLY_EXPORT_V1"
COHORT_SCHEMA_VERSION = "MLB_GEN1_EXPLORATORY_BET_READINESS_COHORT_V1"
PRICE_FRESHNESS_MINUTES = 15.0

EXPORT_CONTRACT: dict[str, Any] = {
    "schemaVersion": EXPORT_SCHEMA_VERSION,
    "purpose": "DESCRIPTIVE_EXPLORATORY_READINESS_ONLY",
    "requiredTopLevel": ["schemaVersion", "extractedAt", "source", "decisions"],
    "sourceAssertions": {"readOnlyTransaction": True, "aispRowsModified": 0, "providerCalls": 0},
    "decisionFields": [
        "experimentId", "experimentVersion", "experimentName", "decisionPolicy",
        "recommendationPolicyVersion", "stakingPolicyVersion", "decisionId", "eventId",
        "eventStart", "eventStatus", "phase", "market", "period", "selection", "line",
        "sportsbook", "americanOdds", "decimalOdds", "quoteObservedAt", "forecastId",
        "forecastGeneratedAt", "forecastCutoff", "forecastVersion", "modelVersionId",
        "modelName", "modelVersion", "modelIdentityChecksum", "recommendedAt",
        "modelProbability", "noVigProbability", "edge", "expectedValue", "readiness",
        "uncertainty", "recommendation", "recommendationReason", "qualificationReasons",
        "evidence", "outcome", "position",
    ],
    "analysisSeparation": {
        "A": "EXPLORATORY_DESCRIPTION_ALLOWED_NOW",
        "B": "POLICY_SELECTION_NOT_AUTHORIZED",
        "C": "INDEPENDENT_POLICY_EVALUATION_NOT_STARTED",
        "D": "VIRTUAL_POSITION_AUTHORITY_NOT_GRANTED_BY_THIS_COHORT",
    },
    "counterfactualRule": "A rejected decision is outcome-describable only with a legitimate contemporaneous price, pregame timestamps, and a final outcome; no profitability is inferred otherwise.",
}


class CohortError(ValueError):
    pass


def export_contract_sha256() -> str:
    return hashlib.sha256(canonical_json_bytes(EXPORT_CONTRACT)).hexdigest()


def _time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _minutes(later: datetime | None, earlier: datetime | None) -> float | None:
    return None if later is None or earlier is None else (later-earlier).total_seconds()/60.0


def _quantiles(values: Sequence[float]) -> dict[str, float | int | None]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"count": 0, "minimum": None, "p25": None, "median": None, "p75": None, "maximum": None}
    def pick(fraction: float) -> float:
        return ordered[round((len(ordered)-1)*fraction)]
    return {"count": len(ordered), "minimum": ordered[0], "p25": pick(.25),
            "median": median(ordered), "p75": pick(.75), "maximum": ordered[-1]}


def validate_export(payload: Mapping[str, Any]) -> None:
    if payload.get("schemaVersion") != EXPORT_SCHEMA_VERSION:
        raise CohortError("wrong export schemaVersion")
    if not isinstance(payload.get("decisions"), list):
        raise CohortError("decisions must be a list")
    source = payload.get("source")
    if not isinstance(source, Mapping) or source.get("readOnlyTransaction") is not True:
        raise CohortError("source must attest a read-only transaction")
    if source.get("aispRowsModified") != 0 or source.get("providerCalls") != 0:
        raise CohortError("export must modify zero AISP rows and call zero providers")
    missing = set(EXPORT_CONTRACT["decisionFields"])
    seen: set[str] = set()
    for row in payload["decisions"]:
        if not isinstance(row, Mapping) or missing-set(row):
            raise CohortError("decision row does not satisfy the exact export contract")
        identity = str(row.get("decisionId") or "")
        if not identity or identity in seen:
            raise CohortError("decision identities must be nonempty and unique")
        seen.add(identity)


def _derived(row: Mapping[str, Any]) -> dict[str, Any]:
    start, decision = _time(row.get("eventStart")), _time(row.get("recommendedAt"))
    quote, forecast = _time(row.get("quoteObservedAt")), _time(row.get("forecastGeneratedAt"))
    quote_age = _minutes(decision, quote)
    forecast_age = _minutes(decision, forecast)
    decision_lead = _minutes(start, decision)
    forecast_lead = _minutes(start, forecast)
    has_price = row.get("decimalOdds") is not None and row.get("americanOdds") is not None and quote is not None
    if not has_price:
        price_state = "MISSING"
    elif quote_age is None or quote_age < 0:
        price_state = "INVALID_FUTURE_OR_UNORDERED"
    elif quote_age > PRICE_FRESHNESS_MINUTES:
        price_state = "STALE"
    else:
        price_state = "FRESH"
    event_status = str(row.get("eventStatus") or "").lower()
    excluded_status = event_status in {"postponed", "canceled", "void", "voided"}
    pregame = decision_lead is not None and decision_lead > 0
    forecast_legitimate = forecast is not None and decision is not None and start is not None and forecast <= decision < start
    outcome = row.get("outcome") if isinstance(row.get("outcome"), Mapping) else {}
    outcome_available = outcome.get("status") == "FINAL" and outcome.get("homeScore") is not None and outcome.get("awayScore") is not None
    readiness_reasons = []
    if excluded_status:
        readiness_reasons.append("EVENT_STATUS_NOT_ELIGIBLE")
    if not pregame:
        readiness_reasons.append("DECISION_NOT_PREGAME")
    if not forecast_legitimate:
        readiness_reasons.append("FORECAST_LINEAGE_OR_TIMING_UNAVAILABLE")
    if price_state == "MISSING":
        readiness_reasons.append("CONTEMPORANEOUS_PRICE_MISSING")
    elif price_state == "STALE":
        readiness_reasons.append("CONTEMPORANEOUS_PRICE_STALE")
    elif price_state != "FRESH":
        readiness_reasons.append("CONTEMPORANEOUS_PRICE_INVALID")
    if not outcome_available:
        readiness_reasons.append("FINAL_OUTCOME_UNAVAILABLE")
    evidence = row.get("evidence") if isinstance(row.get("evidence"), Mapping) else {}
    evidence_text = json.dumps(evidence, sort_keys=True).lower()
    lineup_recorded = "lineup" in evidence_text
    starter_recorded = "starter" in evidence_text
    rejected = row.get("recommendation") != "QUALIFIED_BET"
    retained_fields = (
        "experimentId", "experimentVersion", "experimentName", "decisionPolicy",
        "recommendationPolicyVersion", "stakingPolicyVersion", "decisionId", "eventId",
        "eventStart", "eventStatus", "phase", "market", "period", "selection", "line",
        "sportsbook", "americanOdds", "decimalOdds", "quoteObservedAt", "forecastId",
        "forecastGeneratedAt", "forecastCutoff", "forecastVersion", "modelVersionId",
        "modelName", "modelVersion", "modelIdentityChecksum", "recommendedAt",
        "modelProbability", "noVigProbability", "edge", "expectedValue", "readiness",
        "uncertainty", "recommendation", "recommendationReason", "qualificationReasons",
        "outcome", "position",
    )
    evidence_summary = {key: value for key, value in evidence.items() if key != "feature_decomposition"}
    return {
        **{name: row.get(name) for name in retained_fields},
        "evidenceSummary": evidence_summary or None,
        "derived": {
            "quoteAgeMinutes": quote_age, "forecastAgeMinutes": forecast_age,
            "decisionLeadMinutes": decision_lead, "forecastLeadMinutes": forecast_lead,
            "priceCoverageState": price_state, "decisionPregame": pregame,
            "forecastLegitimatePregame": forecast_legitimate, "outcomeAvailable": outcome_available,
            "lineupReadinessRecorded": lineup_recorded, "starterReadinessRecorded": starter_recorded,
            "readinessExclusionReasons": sorted(readiness_reasons),
            "completeDescriptiveDecisionEvidence": not readiness_reasons,
            "rejectedCounterfactualOutcomeDescribable": bool(rejected and not readiness_reasons),
            "counterfactualProfitabilityComputed": False,
        },
    }


def _reason_category(value: Any) -> str:
    text = str(value or "").lower()
    routes = (
        (("no complete", "quote"), "MISSING_COMPLETE_TWO_SIDED_MARKET"),
        (("quote is stale",), "STALE_MARKET_QUOTE"),
        (("forecast unavailable",), "FORECAST_UNAVAILABLE"),
        (("no valid current forecast",), "FORECAST_UNAVAILABLE"),
        (("lineup missing",), "LINEUP_MISSING"),
        (("starter evidence",), "STARTER_EVIDENCE_INADEQUATE"),
        (("critical inputs incomplete",), "CRITICAL_INPUTS_INCOMPLETE"),
        (("readiness below",), "READINESS_BELOW_POLICY_THRESHOLD"),
        (("adjusted expected value is not positive",), "ADJUSTED_EXPECTED_VALUE_NOT_POSITIVE"),
        (("adjusted edge", "below"), "ADJUSTED_EDGE_BELOW_POLICY_THRESHOLD"),
        (("extreme model-market disagreement",), "EXTREME_MODEL_MARKET_DISAGREEMENT"),
        (("awaiting first forecast and quote",), "AWAITING_FORECAST_AND_QUOTE"),
        (("starting pitcher probable",), "STARTER_NOT_CONFIRMED"),
    )
    for needles, category in routes:
        if all(needle in text for needle in needles):
            return category
    return "OTHER_RECORDED_REASON"


def _reason_counts(records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    categories: Counter[str] = Counter()
    exact: Counter[str] = Counter()
    for row in records:
        if row.get("recommendation") == "QUALIFIED_BET":
            continue
        recommendation_reason = str(row.get("recommendationReason") or "UNSPECIFIED")
        exact[recommendation_reason] += 1
        categories[_reason_category(recommendation_reason)] += 1
        reasons = row.get("qualificationReasons") or []
        if isinstance(reasons, list):
            for reason in reasons:
                key = reason.get("code") if isinstance(reason, Mapping) else reason
                categories[_reason_category(key)] += 1
    ordered_categories = dict(sorted(categories.items(), key=lambda item: (-item[1], item[0])))
    top_exact = dict(sorted(exact.items(), key=lambda item: (-item[1], item[0]))[:20])
    return ordered_categories, top_exact


def _funnel(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    qualified = [row for row in records if row.get("recommendation") == "QUALIFIED_BET"]
    positions = [row for row in records if isinstance(row.get("position"), Mapping) and row["position"].get("positionId")]
    settled = [row for row in positions if (row["position"].get("settlement") or {}).get("result")]
    selection_key = lambda row: (row["eventId"], row["market"], row["period"], row["selection"], row.get("line"))
    return {
        "decisionEvaluations": len(records),
        "distinctEvents": len({row["eventId"] for row in records}),
        "qualifiedEvaluations": len(qualified),
        "rejectedEvaluations": len(records)-len(qualified),
        "distinctQualifiedSelections": len({selection_key(row) for row in qualified}),
        "virtualPositions": len(positions),
        "settledVirtualPositions": len(settled),
        "oneEventMayHaveMultiplePolicyDecisions": True,
    }


def _coverage(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    criteria = [
        ("ELIGIBLE_EVENT_STATUS", lambda row: str(row.get("eventStatus") or "").lower() not in {"postponed", "canceled", "void", "voided"}),
        ("DECISION_PREGAME", lambda row: row["derived"]["decisionPregame"]),
        ("LEGITIMATE_PREGAME_FORECAST", lambda row: row["derived"]["forecastLegitimatePregame"]),
        ("PRICE_PRESENT", lambda row: row["derived"]["priceCoverageState"] != "MISSING"),
        ("PRICE_FRESH_AT_DECISION", lambda row: row["derived"]["priceCoverageState"] == "FRESH"),
        ("FINAL_OUTCOME_AVAILABLE", lambda row: row["derived"]["outcomeAvailable"]),
    ]
    remaining = list(records)
    cascade = []
    independent = {}
    for name, predicate in criteria:
        independent[name] = sum(bool(predicate(row)) for row in records)
        before = len(remaining)
        remaining = [row for row in remaining if predicate(row)]
        cascade.append({"requirement": name, "before": before, "lost": before-len(remaining), "remaining": len(remaining)})
    price = Counter(row["derived"]["priceCoverageState"] for row in records)
    return {"independentPassingCounts": independent, "sequentialAttrition": cascade,
            "fullyDescribableDecisions": len(remaining), "priceCoverage": dict(sorted(price.items()))}


def build_cohort(payload: Mapping[str, Any]) -> dict[str, Any]:
    validate_export(payload)
    records = [_derived(row) for row in payload["decisions"]]
    records.sort(key=lambda row: (str(row["recommendedAt"]), str(row["decisionId"])))
    by_experiment: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in records:
        by_experiment[f"v{row['experimentVersion']}::{row['decisionPolicy']}"].append(row)
    price_ages = [row["derived"]["quoteAgeMinutes"] for row in records if row["derived"]["quoteAgeMinutes"] is not None]
    forecast_ages = [row["derived"]["forecastAgeMinutes"] for row in records if row["derived"]["forecastAgeMinutes"] is not None]
    decision_leads = [row["derived"]["decisionLeadMinutes"] for row in records if row["derived"]["decisionLeadMinutes"] is not None]
    outcome_count = sum(row["derived"]["outcomeAvailable"] for row in records)
    fresh_outcome_rejected = sum(row["derived"]["rejectedCounterfactualOutcomeDescribable"] for row in records)
    reason_categories, top_exact_reasons = _reason_counts(records)
    result = {
        "schemaVersion": COHORT_SCHEMA_VERSION,
        "exportContractSha256": export_contract_sha256(),
        "sourceExportSha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
        "source": payload["source"], "extractedAt": payload["extractedAt"],
        "purpose": "DESCRIPTIVE_EXPLORATORY_READINESS_ONLY_NO_POLICY_OPTIMIZATION",
        "authority": {"policySelection": False, "independentPolicyEvaluation": False,
                      "affectVirtualPositions": False, "wageringEdgeClaim": False},
        "funnel": _funnel(records),
        "funnelByExperiment": {key: _funnel(rows) for key, rows in sorted(by_experiment.items())},
        "rejectionReasons": reason_categories,
        "topExactRejectionReasons": top_exact_reasons,
        "coverage": _coverage(records),
        "timingMinutes": {"quoteAge": _quantiles(price_ages), "forecastAge": _quantiles(forecast_ages),
                          "decisionLead": _quantiles(decision_leads)},
        "outcomes": {"availableDecisions": outcome_count, "missingDecisions": len(records)-outcome_count,
                     "coverage": outcome_count/len(records) if records else 0.0},
        "readinessMetadata": {
            "lineupRecorded": sum(row["derived"]["lineupReadinessRecorded"] for row in records),
            "starterRecorded": sum(row["derived"]["starterReadinessRecorded"] for row in records),
        },
        "versionInventory": {
            "decisionPolicies": dict(sorted(Counter(str(row.get("decisionPolicy") or "MISSING") for row in records).items())),
            "recommendationPolicies": dict(sorted(Counter(str(row.get("recommendationPolicyVersion") or "MISSING") for row in records).items())),
            "stakingPolicies": dict(sorted(Counter(str(row.get("stakingPolicyVersion") or "MISSING") for row in records).items())),
            "modelVersions": dict(sorted(Counter(
                f"{row.get('modelName') or 'MISSING'}::{row.get('modelVersion') or row.get('forecastVersion') or 'MISSING'}"
                for row in records
            ).items())),
            "decisionPhases": dict(sorted(Counter(str(row.get("phase") or "MISSING") for row in records).items())),
        },
        "missingDataRequirements": {
            "finalOutcomeByEventId": len(records)-outcome_count,
            "contemporaneousDecisionPrice": sum(row["derived"]["priceCoverageState"] == "MISSING" for row in records),
            "freshDecisionPriceWithin15Minutes": sum(row["derived"]["priceCoverageState"] == "STALE" for row in records),
            "legitimateForecastIdentityAndTiming": sum(not row["derived"]["forecastLegitimatePregame"] for row in records),
            "lineupReadinessMetadata": sum(not row["derived"]["lineupReadinessRecorded"] for row in records),
            "starterReadinessMetadata": sum(not row["derived"]["starterReadinessRecorded"] for row in records),
            "exactKeys": [
                "eventId + final immutable outcome/status/time",
                "decisionId + sportsbook + two-sided price + quoteObservedAt",
                "forecastId + model identity/version + generatedAt + cutoff",
                "decisionId + pregame lineup/starter readiness as observed at the cutoff",
            ],
        },
        "policyQuestions": {
            "answerableNow": ["opportunity funnel", "recorded rejection reasons", "timestamp and price coverage",
                              "forecast and decision lead times", "outcome coverage", "actual virtual-position inventory"],
            "conditionallyDescribable": {
                "rejectedDecisionOutcomesWithFreshPriceAndOutcome": fresh_outcome_rejected,
                "warning": "This count permits description only; it does not establish counterfactual profit or policy superiority.",
            },
            "notAuthorizedOrNotAnswerable": ["threshold optimization", "recommendation to loosen readiness rules",
                                             "wagering-edge claim", "causal policy comparison", "real wagering authority"],
        },
        "records": records,
        "lineage": {"aispRowsModified": 0, "providerCalls": 0, "modelFits": 0, "finalOotAccessed": False},
    }
    return result


def human_report(result: Mapping[str, Any]) -> str:
    f, c, o = result["funnel"], result["coverage"], result["outcomes"]
    lines = [
        "# Gen 1 exploratory bet-readiness cohort", "",
        "Descriptive research only. No policy was selected, optimized, or authorized.", "",
        f"- Decision evaluations: {f['decisionEvaluations']}",
        f"- Distinct events: {f['distinctEvents']}",
        f"- Qualified evaluations: {f['qualifiedEvaluations']}",
        f"- Distinct qualified selections: {f['distinctQualifiedSelections']}",
        f"- Virtual positions / settled: {f['virtualPositions']} / {f['settledVirtualPositions']}",
        f"- Fully describable decisions: {c['fullyDescribableDecisions']}",
        f"- Outcome coverage: {o['availableDecisions']} / {f['decisionEvaluations']}",
        f"- Price coverage states: {json.dumps(c['priceCoverage'], sort_keys=True)}", "",
        "Missing sportsbook evidence remains a limitation. Rejected decisions are never assigned inferred profit.",
        "AISP rows modified: 0. Provider calls: 0. Final OOT accessed: false.",
    ]
    return "\n".join(lines) + "\n"


def write_cohort(payload: Mapping[str, Any], output_root: Path) -> Path:
    result = build_cohort(payload)
    records = result.pop("records")
    records_bytes = b"".join(canonical_json_bytes(row)+b"\n" for row in records)
    source_bytes = canonical_json_bytes(payload)
    compressed_artifacts = {
        "records.jsonl.gz": gzip.compress(records_bytes, compresslevel=9, mtime=0),
        "source-export.json.gz": gzip.compress(source_bytes, compresslevel=9, mtime=0),
    }
    result["artifacts"] = {
        "records.jsonl.gz": {"uncompressedBytes": len(records_bytes), "uncompressedSha256": hashlib.sha256(records_bytes).hexdigest(),
                             "compressedBytes": len(compressed_artifacts["records.jsonl.gz"]),
                             "compressedSha256": hashlib.sha256(compressed_artifacts["records.jsonl.gz"]).hexdigest()},
        "source-export.json.gz": {"uncompressedBytes": len(source_bytes), "uncompressedSha256": hashlib.sha256(source_bytes).hexdigest(),
                                  "compressedBytes": len(compressed_artifacts["source-export.json.gz"]),
                                  "compressedSha256": hashlib.sha256(compressed_artifacts["source-export.json.gz"]).hexdigest()},
    }
    result["cohortSha256"] = hashlib.sha256(canonical_json_bytes(result)).hexdigest()
    target = output_root / "sha256" / result["cohortSha256"]
    target.mkdir(parents=True, exist_ok=True)
    (target / "cohort.json").write_bytes(canonical_json_bytes(result))
    (target / "report.md").write_text(human_report(result), encoding="utf-8")
    for name, compressed in compressed_artifacts.items():
        (target / name).write_bytes(compressed)
    return target

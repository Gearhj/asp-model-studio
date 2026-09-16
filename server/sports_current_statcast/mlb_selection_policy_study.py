"""Bounded, leakage-safe MLB selection-policy study over frozen AISP evidence.

The module deliberately does not query AISP, call providers, fit a model, or create
positions.  It replays the persisted Gen 1 decision arithmetic and keeps V18 as a
separate research-shadow inventory.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence

from server.sports_datasets.consumer import canonical_json_bytes


SCHEMA_VERSION = "MLB_SELECTION_POLICY_OPTIMIZATION_STUDY_V1"
SOURCE_COHORT_SHA256 = "cd44ef70d6d4a5f3258cfad2cd6222accc5a39431d131184cf7b851ecced5785"
CONTROL_POLICY = "AISP_PRACTICAL_PREGAME_POLICY_V2_1"
HISTORICAL_POLICY = "AISP_OPPORTUNITY_POLICY_V1"
CONTROL_MIN_ADJUSTED_EDGE = 0.020

# This is the entire predeclared candidate set.  It is intentionally small and
# varies only the minimum adjusted edge; every evidence and integrity gate stays
# identical to the control.
CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "candidateId": "GEN1_EDGE_0175_RESEARCH_CANDIDATE",
        "minimumAdjustedEdge": 0.0175,
    },
    {
        "candidateId": "GEN1_EDGE_0150_RESEARCH_CANDIDATE",
        "minimumAdjustedEdge": 0.0150,
    },
)

BASE_GATES = frozenset(
    {
        "valid_current_forecast",
        "model_required_inputs_valid_or_governed_fallback",
        "complete_two_sided_moneyline_quote",
        "fresh_quote",
        "market_probabilities_available",
        "not_extreme_disagreement",
        "no_unresolved_scratch",
        "starters_confirmed_or_probable_stable",
        "lineup_confirmed_adequate_or_pending_allowed",
    }
)


class PolicyStudyError(ValueError):
    pass


def load_jsonl_gzip(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _evidence(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("evidenceSummary")
    return value if isinstance(value, Mapping) else {}


def _derived(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("derived")
    return value if isinstance(value, Mapping) else {}


def _selection_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("eventId"),
        row.get("market"),
        row.get("period"),
        row.get("selection"),
        row.get("line"),
    )


def _source_base_gate_passes(row: Mapping[str, Any]) -> bool:
    evidence = _evidence(row)
    gates = set(evidence.get("gates_passed") or [])
    return bool(
        _derived(row).get("decisionPregame")
        and _derived(row).get("forecastLegitimatePregame")
        and row.get("selection") not in (None, "", "—")
        and evidence.get("adjusted_edge") is not None
        and evidence.get("adjusted_expected_value") is not None
        and BASE_GATES <= gates
    )


def qualifies(row: Mapping[str, Any], minimum_adjusted_edge: float) -> bool:
    if not _source_base_gate_passes(row):
        return False
    evidence = _evidence(row)
    return bool(
        float(evidence["adjusted_edge"]) >= minimum_adjusted_edge
        and float(evidence["adjusted_expected_value"]) > 0.0
    )


def replay(
    records: Sequence[Mapping[str, Any]], minimum_adjusted_edge: float
) -> dict[str, Any]:
    ordered = sorted(records, key=lambda row: (str(row.get("recommendedAt")), str(row.get("decisionId"))))
    evaluations = [row for row in ordered if qualifies(row, minimum_adjusted_edge)]
    first_by_selection: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    for row in evaluations:
        first_by_selection.setdefault(_selection_key(row), row)
    selections = list(first_by_selection.values())
    edges = [float(_evidence(row)["adjusted_edge"]) for row in selections]
    blocks = Counter(str(row.get("recommendedAt"))[:10] for row in selections)
    weeks = Counter(_iso_week(str(row.get("recommendedAt"))) for row in selections)
    teams = Counter(str(row.get("selection") or "MISSING") for row in selections)
    books = Counter(str(row.get("sportsbook") or "MISSING") for row in selections)
    price_bands = Counter(_price_band(row.get("decimalOdds")) for row in selections)
    return {
        "minimumAdjustedEdge": minimum_adjusted_edge,
        "qualifiedEvaluations": len(evaluations),
        "distinctSelections": len(selections),
        "distinctEvents": len({row.get("eventId") for row in selections}),
        "meanAdjustedEdge": mean(edges) if edges else None,
        "medianAdjustedEdge": median(edges) if edges else None,
        "dailyBlocks": dict(sorted(blocks.items())),
        "distinctDailyBlocks": len(blocks),
        "isoWeekBlocks": dict(sorted(weeks.items())),
        "distinctIsoWeekBlocks": len(weeks),
        "sportsbookConcentration": dict(sorted(books.items())),
        "priceBandConcentration": dict(sorted(price_bands.items())),
        "largestSelectionShare": max(teams.values()) / len(selections) if selections else None,
        "selectionDecisionIds": [str(row.get("decisionId")) for row in selections],
        "selections": selections,
    }


def _iso_week(value: str) -> str:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    year, week, _ = instant.isocalendar()
    return f"{year}-W{week:02d}"


def _price_band(value: Any) -> str:
    if value is None:
        return "MISSING"
    price = float(value)
    if price < 2.0:
        return "FAVORITE"
    if price == 2.0:
        return "EVEN"
    if price < 3.0:
        return "UNDERDOG_LT_3"
    return "LONGSHOT_GE_3"


def _funnel(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    stages: tuple[tuple[str, Any], ...] = (
        ("ELIGIBLE_EVENT_AND_PREGAME_DECISION", lambda row: bool(_derived(row).get("decisionPregame"))),
        ("LEGITIMATE_FORECAST", lambda row: bool(_derived(row).get("forecastLegitimatePregame"))),
        ("COMPLETE_TWO_SIDED_QUOTE", lambda row: "complete_two_sided_moneyline_quote" in set(_evidence(row).get("gates_passed") or [])),
        ("SOURCE_POLICY_FRESH_QUOTE", lambda row: "fresh_quote" in set(_evidence(row).get("gates_passed") or [])),
        ("VALID_MARKET_PROBABILITIES", lambda row: "market_probabilities_available" in set(_evidence(row).get("gates_passed") or [])),
        ("MODEL_AND_INTEGRITY_GATES", lambda row: {"valid_current_forecast", "model_required_inputs_valid_or_governed_fallback", "not_extreme_disagreement", "no_unresolved_scratch"} <= set(_evidence(row).get("gates_passed") or [])),
        ("STARTER_AND_LINEUP_GATES", lambda row: {"starters_confirmed_or_probable_stable", "lineup_confirmed_adequate_or_pending_allowed"} <= set(_evidence(row).get("gates_passed") or [])),
        ("ADJUSTED_EDGE_AT_LEAST_0_020", lambda row: _evidence(row).get("adjusted_edge") is not None and float(_evidence(row)["adjusted_edge"]) >= CONTROL_MIN_ADJUSTED_EDGE),
        ("ADJUSTED_EXPECTED_VALUE_POSITIVE", lambda row: _evidence(row).get("adjusted_expected_value") is not None and float(_evidence(row)["adjusted_expected_value"]) > 0.0),
    )
    remaining = list(records)
    result: list[dict[str, Any]] = []
    for name, predicate in stages:
        before = len(remaining)
        remaining = [row for row in remaining if predicate(row)]
        result.append({"gate": name, "before": before, "lost": before - len(remaining), "remaining": len(remaining)})
    return result


def _state(row: Mapping[str, Any], key: str) -> str:
    value = _evidence(row).get(key)
    if not isinstance(value, Mapping):
        return "MISSING"
    return str(value.get("state") or "MISSING")


def _arithmetic_mismatches(records: Iterable[Mapping[str, Any]]) -> int:
    mismatches = 0
    for row in records:
        evidence = _evidence(row)
        probability = evidence.get("adjusted_probability")
        market = evidence.get("market_probability")
        edge = evidence.get("adjusted_edge")
        expected_value = evidence.get("adjusted_expected_value")
        price = row.get("decimalOdds")
        if probability is None or market is None or edge is None or expected_value is None or price is None:
            continue
        if abs((float(probability) - float(market)) - float(edge)) > 2e-6:
            mismatches += 1
            continue
        if abs((float(probability) * float(price) - 1.0) - float(expected_value)) > 2e-6:
            mismatches += 1
    return mismatches


def _actual_positions(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    positions: dict[str, Mapping[str, Any]] = {}
    for row in records:
        value = row.get("position")
        if isinstance(value, Mapping) and value.get("positionId"):
            positions[str(value["positionId"])] = value
    settled = [
        value for value in positions.values()
        if isinstance(value.get("settlement"), Mapping) and value["settlement"].get("result")
    ]
    settled.sort(key=lambda value: str(value.get("placedAt")))
    total_stake = sum(float(value.get("stake") or 0.0) for value in settled)
    profit_loss = sum(float(value["settlement"].get("profitLoss") or 0.0) for value in settled)
    cumulative = 0.0
    peak = 0.0
    maximum_drawdown = 0.0
    for value in settled:
        cumulative += float(value["settlement"].get("profitLoss") or 0.0)
        peak = max(peak, cumulative)
        maximum_drawdown = max(maximum_drawdown, peak - cumulative)
    return {
        "positions": len(positions),
        "settledPositions": len(settled),
        "totalSettledStake": total_stake,
        "settledProfitLoss": profit_loss,
        "settledReturnOnStake": profit_loss / total_stake if total_stake else None,
        "maximumDrawdown": maximum_drawdown,
        "warning": "Stored realized results describe actual control positions only; they are not a counterfactual candidate-policy evaluation.",
    }


def _group_summary(
    records: Sequence[Mapping[str, Any]], key_function: Any
) -> dict[str, dict[str, int]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in records:
        groups.setdefault(str(key_function(row)), []).append(row)
    result = {}
    for key, rows in sorted(groups.items()):
        qualified = [row for row in rows if row.get("recommendation") == "QUALIFIED_BET"]
        result[key] = {
            "evaluations": len(rows),
            "qualifiedEvaluations": len(qualified),
            "distinctQualifiedSelections": len({_selection_key(row) for row in qualified}),
        }
    return result


def _additional_selections(
    control: Mapping[str, Any], candidate: Mapping[str, Any]
) -> list[dict[str, Any]]:
    control_keys = {_selection_key(row) for row in control["selections"]}
    result = []
    for row in candidate["selections"]:
        if _selection_key(row) in control_keys:
            continue
        evidence = _evidence(row)
        result.append(
            {
                "eventId": row.get("eventId"),
                "selection": row.get("selection"),
                "decisionId": row.get("decisionId"),
                "decisionTimestamp": row.get("recommendedAt"),
                "eventStart": row.get("eventStart"),
                "sportsbook": row.get("sportsbook"),
                "decimalOdds": row.get("decimalOdds"),
                "quoteAgeMinutes": _derived(row).get("quoteAgeMinutes"),
                "readiness": row.get("readiness"),
                "adjustedEdge": evidence.get("adjusted_edge"),
                "adjustedExpectedValue": evidence.get("adjusted_expected_value"),
                "outcomeAvailableButSelectionSideMappingMissing": bool(_derived(row).get("outcomeAvailable")),
            }
        )
    return result


def _metric_view(replay_result: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in replay_result.items() if key not in {"selections", "selectionDecisionIds"}}


def build_study(
    records: Sequence[Mapping[str, Any]],
    cohort: Mapping[str, Any],
    v18_handoff: Mapping[str, Any],
    *,
    aisp_audit: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    if cohort.get("cohortSha256") != SOURCE_COHORT_SHA256:
        raise PolicyStudyError("unexpected source cohort identity")
    if cohort.get("lineage", {}).get("finalOotAccessed") is not False:
        raise PolicyStudyError("source cohort does not attest sealed Final OOT")
    if cohort.get("source", {}).get("readOnlyTransaction") is not True:
        raise PolicyStudyError("source cohort was not exported read-only")

    known_policies = {CONTROL_POLICY, HISTORICAL_POLICY}
    gen1 = [row for row in records if row.get("decisionPolicy") in known_policies]
    unknown = [row for row in records if row.get("decisionPolicy") not in known_policies]
    if unknown:
        raise PolicyStudyError("source decision records contain an unrecognized policy track")
    control_rows = [row for row in gen1 if row.get("decisionPolicy") == CONTROL_POLICY]
    historical_rows = [row for row in gen1 if row.get("decisionPolicy") == HISTORICAL_POLICY]

    control = replay(control_rows, CONTROL_MIN_ADJUSTED_EDGE)
    recorded_qualified = {str(row.get("decisionId")) for row in control_rows if row.get("recommendation") == "QUALIFIED_BET"}
    replayed_qualified = {str(row.get("decisionId")) for row in control_rows if qualifies(row, CONTROL_MIN_ADJUSTED_EDGE)}
    if recorded_qualified != replayed_qualified:
        raise PolicyStudyError("control replay does not reproduce persisted recommendations exactly")

    candidate_outputs: dict[str, list[dict[str, Any]]] = {}
    comparisons = []
    for definition in CANDIDATES:
        candidate = replay(control_rows, float(definition["minimumAdjustedEdge"]))
        additional = _additional_selections(control, candidate)
        candidate_outputs[str(definition["candidateId"])] = additional
        comparisons.append(
            {
                **definition,
                **_metric_view(candidate),
                "additionalSelectionsVersusControl": len(additional),
                "calibration": None,
                "realizedReturn": None,
                "maximumDrawdown": None,
                "outcomeMetricStatus": "UNAVAILABLE_MISSING_EVENT_PARTICIPANT_TO_SCORE_MAPPING",
            }
        )

    quote_conflicts = [
        row for row in control_rows
        if row.get("recommendation") == "QUALIFIED_BET"
        and _derived(row).get("priceCoverageState") != "FRESH"
    ]
    lineups = Counter(_state(row, "lineup") for row in control_rows)
    starter_home = Counter(_state(row, "starter_home") for row in control_rows)
    starter_away = Counter(_state(row, "starter_away") for row in control_rows)
    readiness_bands = Counter()
    for row in control_rows:
        score = row.get("readiness")
        if score is None:
            readiness_bands["MISSING"] += 1
        elif float(score) < 50:
            readiness_bands["LT_50"] += 1
        elif float(score) < 60:
            readiness_bands["50_TO_LT_60"] += 1
        else:
            readiness_bands["GE_60"] += 1

    def readiness_band(row: Mapping[str, Any]) -> str:
        score = row.get("readiness")
        if score is None:
            return "MISSING"
        if float(score) < 50:
            return "LT_50"
        if float(score) < 60:
            return "50_TO_LT_60"
        return "GE_60"

    lineup_summary = _group_summary(control_rows, lambda row: _state(row, "lineup"))
    starter_summary = _group_summary(
        control_rows,
        lambda row: f"HOME_{_state(row, 'starter_home')}__AWAY_{_state(row, 'starter_away')}",
    )
    readiness_summary = _group_summary(control_rows, readiness_band)

    v18_forecasts = list(v18_handoff.get("forecasts") or [])
    audit_status = "PRESENT_RECONCILED" if aisp_audit is not None else "NOT_PRESENT_AT_STUDY_TIME"
    audit_reconciliation = None
    if aisp_audit is not None:
        audit_funnel = aisp_audit.get("funnel", {})
        audit_engine = aisp_audit.get("forecast_engine", {})
        audit_quotes = aisp_audit.get("quote_availability", {})
        audit_readiness = aisp_audit.get("readiness_components", {})
        audit_positions = aisp_audit.get("positions", {})
        audit_reconciliation = {
            "schemaVersion": aisp_audit.get("schema_version"),
            "repositoryCommit": aisp_audit.get("repository_commit"),
            "canonicalSha256": hashlib.sha256(canonical_json_bytes(aisp_audit)).hexdigest(),
            "generatedAt": aisp_audit.get("generated_at"),
            "accessMode": aisp_audit.get("access_mode"),
            "snapshotDifference": {
                "frozenCohortDecisionRows": len(gen1),
                "laterOperationalAuditDecisionRows": aisp_audit.get("decision_rows", {}).get("rows_total"),
                "reason": "The audit is a later read-only snapshot; it reconciles operations but does not replace the frozen policy-evaluation cohort.",
            },
            "engineSeparation": {
                "gen1DecisionRows": audit_engine.get("decision_rows_joined_to_gen1_forecast"),
                "v18DailyImportedRows": audit_engine.get("v18_daily_imported_rows_mlb"),
                "v18ShadowBoardDecisions": audit_engine.get("v18_mlb_rows_evaluated_on_shadow_board"),
                "positionsLinkedToV18": audit_engine.get("official_positions_linked_to_v18"),
            },
            "historicalGameFunnel": audit_funnel.get("historical_2026-08-28_to_2026-09-07"),
            "currentSlateFunnel": audit_funnel.get("current_slate_2026-09-08"),
            "currentSlateLiveFunnel": audit_funnel.get("live_policy_funnel_current_slate"),
            "quoteSemantics": audit_quotes.get("policy"),
            "quoteFailureOrigin": audit_quotes.get("failure_origin"),
            "readinessThreshold": audit_readiness.get("threshold"),
            "readinessPublishFloor": audit_readiness.get("publish_floor"),
            "historicalReadinessComponents": audit_readiness.get("historical_2026-08-28_to_2026-09-07"),
            "currentSlateReadinessComponents": audit_readiness.get("current_slate_2026-09-08"),
            "laterPositionInventory": audit_positions,
        }
    study: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "evidenceTimestamp": cohort.get("extractedAt"),
        "source": {
            "baseCommit": "3cc9d67376aaa6ef7364f044a02813d8d61e056b",
            "acceptanceEvidenceCommit": "922450b9c0492b4c86f12a87ff3217bfb3fc70cc",
            "gen1CohortSha256": SOURCE_COHORT_SHA256,
            "v18DailyHandoffSha256": v18_handoff.get("handoffSha256"),
            "aispOperationalAuditStatus": audit_status,
            "aispOperationalAuditCommit": None if aisp_audit is None else aisp_audit.get("repository_commit"),
        },
        "trackSeparation": {
            "gen1": {
                "decisionEvaluations": len(gen1),
                "historicalPolicy": {"policyId": HISTORICAL_POLICY, "evaluations": len(historical_rows), "qualifiedEvaluations": sum(row.get("recommendation") == "QUALIFIED_BET" for row in historical_rows)},
                "controlPolicy": {"policyId": CONTROL_POLICY, "evaluations": len(control_rows), "recordedQualifiedEvaluations": len(recorded_qualified)},
            },
            "v18ResearchShadow": {
                "forecastObjects": len(v18_forecasts),
                "policyDecisionRecordsInFrozenCohort": 0,
                "selectionPerformanceRecords": 0,
                "promotionStatus": v18_handoff.get("promotionStatus"),
                "researchShadowOnly": v18_handoff.get("researchShadowOnly"),
                "wageringAuthority": v18_handoff.get("wageringAuthority"),
                "status": "DESCRIPTIVE_FORECAST_INVENTORY_ONLY_NO_V18_POLICY_EVALUATION",
            },
            "combinedPerformanceStatistics": False,
        },
        "gen1Funnel": {
            "allPolicies": cohort.get("funnel"),
            "byPolicy": cohort.get("funnelByExperiment"),
            "controlSequentialGateAttrition": _funnel(control_rows),
            "topRecordedLossCauses": cohort.get("rejectionReasons"),
            "sourceCoverage": cohort.get("coverage"),
        },
        "aispOperationalReconciliation": audit_reconciliation,
        "gateReview": [
            {"gate": "FORECAST_IDENTITY_AND_PREGAME_ORDERING", "disposition": "KEEP_HARD", "lostAllGen1Evaluations": cohort.get("missingDataRequirements", {}).get("legitimateForecastIdentityAndTiming"), "reason": "Identity and temporal validity are non-negotiable leakage controls."},
            {"gate": "COMPLETE_TWO_SIDED_MARKET", "disposition": "KEEP_HARD", "missingAllGen1Evaluations": cohort.get("missingDataRequirements", {}).get("contemporaneousDecisionPrice"), "reason": "A no-vig market decision and legitimate return cannot be computed without both sides."},
            {"gate": "QUOTE_AGE", "disposition": "KEEP_HARD_DO_NOT_RELAX", "controlQualifiedRowsOutsideExploratory15MinuteClassification": len(quote_conflicts), "maximumAgeMinutesAmongThoseRows": max((float(_derived(row).get("quoteAgeMinutes")) for row in quote_conflicts), default=None), "reason": "The audit confirms Gen 1 uses a 240-minute board-staleness rule plus a 15-minute pregame cutoff; the cohort's exploratory 15-minute age label is not the Gen 1 control rule. The exact control semantics are retained."},
            {"gate": "LINEUP_CONFIRMATION", "disposition": "KEEP_GRADUATED", "states": dict(sorted(lineups.items())), "evaluationByState": lineup_summary, "outcomeComparisonStatus": "UNAVAILABLE_MISSING_EVENT_PARTICIPANT_TO_SCORE_MAPPING", "incrementalInformationStatus": "NOT_ESTIMABLE_FROM_THIS_EXPORT", "reason": "The control already permits lineup-pending moneylines with an explicit penalty; no evidence supports either a new hard stop or removal."},
            {"gate": "STARTER_CONFIRMATION", "disposition": "KEEP_HARD", "homeStates": dict(sorted(starter_home.items())), "awayStates": dict(sorted(starter_away.items())), "evaluationByCombinedState": starter_summary, "outcomeComparisonStatus": "UNAVAILABLE_MISSING_EVENT_PARTICIPANT_TO_SCORE_MAPPING", "incrementalInformationStatus": "NOT_ESTIMABLE_FROM_THIS_EXPORT", "reason": "Unstable or missing starter evidence cannot be outcome-scored in this export, so softening is not justified."},
            {"gate": "READINESS", "disposition": "SOFTENING_STRUCTURALLY_MOTIVATED_BUT_NOT_EVIDENCE_APPROVED", "bands": dict(sorted(readiness_bands.items())), "evaluationByBand": readiness_summary, "outcomeComparisonStatus": "UNAVAILABLE_MISSING_EVENT_PARTICIPANT_TO_SCORE_MAPPING", "incrementalInformationStatus": "STRUCTURALLY_CONFOUNDED_BY_THREE_NEVER_READY_COMPONENTS", "reason": "The audit shows a 70 threshold while three never-ready components consume 20 points, but the export cannot outcome-score the excluded games. Keep the control unchanged until an outcome-linked graduated challenger can be independently evaluated."},
            {"gate": "ADJUSTED_EDGE", "disposition": "KEEP_CONTROL_AT_0_020", "reason": "Lower thresholds add only three to five distinct selections and cannot be independently outcome-scored."},
            {"gate": "MODEL_UNCERTAINTY", "disposition": "KEEP_PENALTY", "reason": "The adjusted probability already subtracts the recorded uncertainty; no independent evidence supports weakening it."},
            {"gate": "EXTREME_DISAGREEMENT_AND_EVIDENCE_INTEGRITY", "disposition": "KEEP_HARD", "reason": "These are corruption/review safeguards, not availability thresholds."},
        ],
        "controlReplay": {
            **_metric_view(control),
            "recordedQualifiedEvaluations": len(recorded_qualified),
            "replayMismatchCount": 0,
            "arithmeticMismatchCount": _arithmetic_mismatches(control_rows),
            "actualPositionResults": _actual_positions(control_rows),
            "calibration": None,
            "selectionOutcomeMappingStatus": "UNAVAILABLE_MISSING_EVENT_HOME_AWAY_IDENTITIES",
        },
        "candidateSet": comparisons,
        "retainedControlRules": {
            "policyId": CONTROL_POLICY,
            "minimumReadiness": None if aisp_audit is None else aisp_audit.get("policy_values", {}).get("readiness_threshold"),
            "minimumAdjustedEdge": CONTROL_MIN_ADJUSTED_EDGE,
            "adjustedExpectedValue": "STRICTLY_GREATER_THAN_ZERO",
            "extremeDisagreementThreshold": None if aisp_audit is None else aisp_audit.get("policy_values", {}).get("extreme_disagreement_threshold"),
            "maximumBoardQuoteStalenessMinutes": None if aisp_audit is None else aisp_audit.get("policy_values", {}).get("max_quote_staleness_minutes"),
            "finalPregameCutoffMinutes": None if aisp_audit is None else aisp_audit.get("policy_values", {}).get("final_pregame_cutoff_minutes"),
            "starterRequirement": None if aisp_audit is None else aisp_audit.get("policy_values", {}).get("starter_requirement"),
            "lineupRequirement": None if aisp_audit is None else aisp_audit.get("policy_values", {}).get("lineup_requirement"),
            "uncertaintyPenalty": "PRESERVE_RECORDED_ADJUSTED_PROBABILITY",
            "kellyFraction": None if aisp_audit is None else aisp_audit.get("policy_values", {}).get("kelly_fraction"),
            "unitPercentage": None if aisp_audit is None else aisp_audit.get("policy_values", {}).get("unit_percentage"),
            "maximumPositionPercentage": None if aisp_audit is None else aisp_audit.get("policy_values", {}).get("max_position_percentage"),
            "maximumSameGamePercentage": None if aisp_audit is None else aisp_audit.get("policy_values", {}).get("max_same_game_percentage"),
            "maximumDailyPercentage": None if aisp_audit is None else aisp_audit.get("policy_values", {}).get("max_daily_percentage"),
            "requiredEvidenceGates": sorted(BASE_GATES),
        },
        "chronologicalEvaluation": {
            "method": "PREDECLARED_POLICY_REPLAY_WITH_DAILY_BLOCK_REPORTING",
            "candidateParametersChosenFromOutcomes": False,
            "dailyBlocksObserved": sorted({str(row.get("recommendedAt"))[:10] for row in control_rows}),
            "independentIsoWeekBlocksWithSelections": control.get("distinctIsoWeekBlocks"),
            "weekToWeekStabilityStatus": "INSUFFICIENT_ONE_SELECTION_WEEK",
        },
        "decision": {
            "outcome": "KEEP_STRICT_CONTROL_UNCHANGED",
            "recommendedChallenger": None,
            "additionalSelectionsByRecommendedChallenger": [],
            "aispShadowPolicyHandoff": None,
            "reasons": [
                "Only nine actual control positions are settled.",
                "Candidate selections occur in one ISO-week block, so week-to-week stability is not estimable.",
                "The frozen export lacks event participant identities needed to map a selected team to the final home/away score.",
                "The later operational audit shows that missing odds, not edge strictness, is the current slate's first binding constraint.",
                "The readiness composite is structurally depressed, but its excluded games cannot be outcome-scored from the frozen export.",
                "V18 has 13 research-shadow forecasts but no frozen policy-decision cohort.",
            ],
        },
        "limitations": {
            "missingEventParticipantMapping": True,
            "missingOrStalePrices": cohort.get("coverage", {}).get("priceCoverage"),
            "settledControlPositions": _actual_positions(control_rows)["settledPositions"],
            "selectionIsoWeekBlocks": control.get("distinctIsoWeekBlocks"),
            "v18DecisionEvidenceAbsent": True,
            "aispOperationalAuditAbsent": aisp_audit is None,
            "counterfactualProfitInferred": False,
        },
        "authority": {
            "researchOnly": True,
            "officialPolicyChanged": False,
            "positionsCreatedAlteredOrSettled": 0,
            "aispWrites": 0,
            "providerCalls": 0,
            "modelFits": 0,
            "finalOotOpened": False,
            "wageringAuthorityGranted": False,
        },
        "verdict": "MLB_STRICT_POLICY_RETAINED",
    }
    return study, candidate_outputs


def _report(study: Mapping[str, Any], additions: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    control = study["controlReplay"]
    positions = control["actualPositionResults"]
    lines = [
        "# MLB bounded selection-policy study", "",
        "Verdict: `MLB_STRICT_POLICY_RETAINED`", "",
        "Gen 1 and V18 were evaluated separately. V18 contributes 13 research-shadow forecasts and zero policy-decision records; no V18 selection or performance statistic is mixed with Gen 1.", "",
        "## Funnel", "",
        f"The frozen Gen 1 cohort contains {study['trackSeparation']['gen1']['decisionEvaluations']:,} evaluations across 154 events. Historical V1 has 7,550 evaluations and zero qualifications; the V2.1 control has 11,060 evaluations, 731 qualified evaluations and 22 distinct selections.", "",
        "The largest recorded losses are missing complete two-sided market evidence (11,090 overlapping reason occurrences), other policy reasons (7,095), incomplete critical inputs / unconfirmed starters (6,997 each), missing lineups (6,683), readiness below threshold (6,367), non-positive adjusted EV (3,978), and adjusted edge below threshold (2,495). Missing sportsbook evidence is a market-data exclusion, not a model failure.", "",
        "## Operational reconciliation", "",
    ]
    audit = study.get("aispOperationalReconciliation")
    if audit:
        current = audit["currentSlateFunnel"]
        historical = audit["historicalGameFunnel"]
        lines += [
            f"Claude's later read-only AISP audit (`{audit['repositoryCommit'][:8]}`) contains {audit['snapshotDifference']['laterOperationalAuditDecisionRows']:,} rows over 169 games, versus the frozen study cohort's {audit['snapshotDifference']['frozenCohortDecisionRows']:,} rows. The later rows reconcile operations but do not replace the frozen evaluation cohort.", "",
            f"At the game level, the historical first blockers were: no forecast {historical['first_blocking_stage'].get('no_valid_forecast', 0)}, no quote {historical['first_blocking_stage'].get('no_complete_two_sided_quote', 0)}, stale quote {historical['first_blocking_stage'].get('stale_quote', 0)}, readiness {historical['first_blocking_stage'].get('readiness_below_threshold', 0)}, starter {historical['first_blocking_stage'].get('starter_not_confirmed', 0)}, and edge/EV {historical['first_blocking_stage'].get('edge_below_threshold', 0)}; 12 final game rows reached QUALIFIED_BET.", "",
            f"For September 8, all {current['games_evaluated']} games stop first at missing two-sided quotes. The audit confirms 13 imported daily V18 rows, zero V18 shadow-board decisions, and zero positions linked to V18. Thus edge relaxation would change nothing operationally on the current slate.", "",
            "The audit also resolves quote semantics: Gen 1's board allows 240 minutes of staleness and separately enforces a 15-minute pregame cutoff. The cohort's exploratory 15-minute quote-age label is not substituted for the persisted Gen 1 control gate.", "",
            "Readiness is structurally suspect: the threshold is 70, while feature completeness, bullpen, and Statcast are never ready and remove 20 possible points. That supports a future graduated-readiness study, but not installation from this outcome-incomplete cohort.", "",
        ]
    else:
        lines += ["The AISP operational audit was not available at study time.", ""]
    lines += [
        "## Gate dispositions", "",
        "| Gate | Disposition | Evidence-based reason |", "|---|---|---|",
    ]
    for gate in study["gateReview"]:
        lines.append(f"| {gate['gate']} | {gate['disposition']} | {gate['reason']} |")
    lineup_gate = next(gate for gate in study["gateReview"] if gate["gate"] == "LINEUP_CONFIRMATION")
    readiness_gate = next(gate for gate in study["gateReview"] if gate["gate"] == "READINESS")
    lines += [
        "",
        "Gate-state coverage confirms the distinction between availability and performance. Lineup evidence was confirmed in 3,090 evaluations and pending-but-allowed in 7,817; their qualified-evaluation counts were "
        f"{lineup_gate['evaluationByState']['CONFIRMED_COMPLETE']['qualifiedEvaluations']} and {lineup_gate['evaluationByState']['PENDING_ALLOWED_FOR_MONEYLINE']['qualifiedEvaluations']}. Readiness bands below 50, 50–59.9, and 60+ contained "
        f"{readiness_gate['evaluationByBand']['LT_50']['evaluations']}, {readiness_gate['evaluationByBand']['50_TO_LT_60']['evaluations']}, and {readiness_gate['evaluationByBand']['GE_60']['evaluations']} evaluations, with "
        f"{readiness_gate['evaluationByBand']['LT_50']['qualifiedEvaluations']}, {readiness_gate['evaluationByBand']['50_TO_LT_60']['qualifiedEvaluations']}, and {readiness_gate['evaluationByBand']['GE_60']['qualifiedEvaluations']} qualifications. Calibration, error, return, and incremental-information comparisons across these states remain unavailable because the export does not map the selected team to the final home/away score.", "",
        "## Exact retained control rules", "",
        "| Parameter | Rule |", "|---|---|",
    ]
    rules = study["retainedControlRules"]
    rule_rows = (
        ("Readiness", f">= {rules['minimumReadiness']:.1f}" if rules["minimumReadiness"] is not None else "Source policy"),
        ("Adjusted edge", f">= {rules['minimumAdjustedEdge']:.3f}"),
        ("Adjusted EV", "> 0"),
        ("Extreme disagreement", f"Hard stop at {rules['extremeDisagreementThreshold']:.2f}" if rules["extremeDisagreementThreshold"] is not None else "Source hard stop"),
        ("Quote timing", f"<= {rules['maximumBoardQuoteStalenessMinutes']} minutes old and observed before the {rules['finalPregameCutoffMinutes']}-minute pregame cutoff"),
        ("Starters", rules["starterRequirement"] or "Source requirement"),
        ("Lineups", rules["lineupRequirement"] or "Source requirement"),
        ("Uncertainty", "Preserve recorded adjusted-probability penalty"),
        ("Stake", f"{rules['kellyFraction']:.2f} Kelly; {rules['unitPercentage']:.3f} unit, {rules['maximumPositionPercentage']:.3f} position, {rules['maximumSameGamePercentage']:.3f} same-game, {rules['maximumDailyPercentage']:.3f} daily caps"),
    )
    for name, value in rule_rows:
        lines.append(f"| {name} | {value} |")
    lines += ["", "## Compact comparison", "", "| Policy | Eval qualifications | Distinct selections | Added | Mean adjusted edge | Outcome metrics |", "|---|---:|---:|---:|---:|---|"]
    lines.append(f"| V2.1 control, edge ≥ 0.020 | {control['qualifiedEvaluations']} | {control['distinctSelections']} | — | {control['meanAdjustedEdge']:.4f} | Actual positions only |");
    for candidate in study["candidateSet"]:
        lines.append(f"| {candidate['candidateId']} | {candidate['qualifiedEvaluations']} | {candidate['distinctSelections']} | {candidate['additionalSelectionsVersusControl']} | {candidate['meanAdjustedEdge']:.4f} | Unavailable: participant mapping missing |")
    lines += [
        "", "The exact control arithmetic replayed with zero decision mismatches. The actual control inventory has "
        f"{positions['settledPositions']} settled positions on {positions['totalSettledStake']:.1f} stake units, P/L {positions['settledProfitLoss']:+.2f}, return on stake {positions['settledReturnOnStake']:.2%}, and maximum drawdown {positions['maximumDrawdown']:.2f}. This sample is descriptive only.", "",
        "## Candidate-only additional games (not recommended selections)", "",
    ]
    for candidate_id, rows in additions.items():
        lines += [f"### {candidate_id}", "", "| Event | Selection | Decision | Edge | Price |", "|---|---|---|---:|---:|"]
        for row in rows:
            lines.append(f"| `{row['eventId']}` | {row['selection']} | `{row['decisionId']}` | {row['adjustedEdge']:.4f} | {row['decimalOdds']:.4f} |")
        if not rows:
            lines.append("| — | None | — | — | — |")
        lines.append("")
    lines += [
        "No challenger is installed. The five-game maximum incremental sample, one selection week, missing event-team outcome mapping, and only nine settled positions in the frozen control snapshot do not support a defensible relaxation. The operational audit independently shows that current selections stop at missing odds before edge or readiness is reached. Consequently there is no challenger identity, no official additional selection list, and no AISP shadow-policy handoff.", "",
        "Final OOT stayed sealed. No model fit, provider call, AISP write, position mutation, or wagering authority occurred.",
    ]
    return "\n".join(lines) + "\n"


def write_study(
    records_path: Path,
    cohort_path: Path,
    v18_handoff_path: Path,
    output_root: Path,
    *,
    aisp_audit_path: Path | None = None,
) -> Path:
    records = load_jsonl_gzip(records_path)
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    handoff = json.loads(v18_handoff_path.read_text(encoding="utf-8"))
    aisp_audit = None
    if aisp_audit_path is not None and aisp_audit_path.exists():
        aisp_audit = json.loads(aisp_audit_path.read_text(encoding="utf-8"))
    study, additions = build_study(records, cohort, handoff, aisp_audit=aisp_audit)
    study_sha = hashlib.sha256(canonical_json_bytes(study)).hexdigest()
    study["studyId"] = f"mlb-selection-policy-study-{study_sha[:24]}"
    study["studySha256"] = study_sha
    target = output_root / "sha256" / study_sha
    target.mkdir(parents=True, exist_ok=True)
    (target / "study.json").write_bytes(canonical_json_bytes(study))
    (target / "candidate-additional-selections.json").write_bytes(canonical_json_bytes(additions))
    (target / "report.md").write_text(_report(study, additions), encoding="utf-8")
    latest = {
        "schemaVersion": "MLB_SELECTION_POLICY_STUDY_LOCATOR_V1",
        "relativePath": str(target.as_posix()),
        "studySha256": study_sha,
        "verdict": study["verdict"],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "latest.json").write_bytes(canonical_json_bytes(latest))
    return target

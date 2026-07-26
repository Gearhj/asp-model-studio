"""Target Intelligence -- bounded analytical aggregates for the EDA Target tab.

Why this exists
---------------
The Target tab previously restated the Overview page: the same class counts, the
same rare-event sentence, and two group tables. Nothing on it answered the
questions a reviewer actually has to answer -- is the observed prevalence stable,
how uncertain is it, does any predictor move it, and is the target measurable at
all.

This module supplies the three analytical pieces that were missing, and it does
so WITHOUT introducing a second source of truth for the class counts:

  * `assess_class_balance` and `wilson_score_interval` are pure functions over
    counts. `compute_target_assessment` obtains those counts by calling
    `target_distribution_service.compute_target_distribution` -- the same exact,
    cached, DuckDB-backed aggregate the Data Acquisition panel already uses. A
    warm Target tab therefore costs one cache read, not a second scan.

  * `compute_target_by_predictor` is the one genuinely new scan. It is on-demand
    (never issued on page load), it projects exactly two columns out of the
    governed artifact, and it returns bounded grouped rows -- never predictor or
    target values themselves.

Nothing here profiles every column, and nothing here transfers a population
column to the browser.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from . import result_cache
from .analysis_scope import governed_scope, scope_identity
from .target_distribution_service import (
    _duckdb,
    _quote_identifier,
    _resolve_version_artifact,
    _scan_expression,
    compute_target_distribution,
)

ENGINE_VERSION = "target-intelligence/1"

# ---------------------------------------------------------------------------
# Bounds. Every one of these caps a payload, not a source population.
# ---------------------------------------------------------------------------

MIN_BANDS = 2
MAX_BANDS = 20
DEFAULT_BANDS = 10

# Categories beyond this are collapsed into a disclosed "Other" row, so a
# 50,000-level categorical never produces a 50,000-row payload.
MIN_TOP_CATEGORIES = 2
MAX_TOP_CATEGORIES = 30
DEFAULT_TOP_CATEGORIES = 12

# A predictor with more distinct values than this is treated as an identifier
# rather than a categorical predictor, and is refused with an explanation.
MAX_CATEGORICAL_CARDINALITY = 10_000

# Groups smaller than this cannot support a stable rate estimate; the group is
# still returned, but flagged, and it is excluded from the "highest/lowest
# event rate" summary so one 3-row band never reads as a finding.
SMALL_GROUP_MIN_ROWS = 30
SMALL_GROUP_MIN_EVENTS = 5

_QUERY_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Part E / Part F: event prevalence and class imbalance are DIFFERENT questions
# ---------------------------------------------------------------------------
#
# The first implementation tiered the minority-class share and called the result
# a rare-event tier. That is right for CLASS_TRAIN, where the configured fraud
# event happens to be the minority class, and wrong in general: if a project
# configures the majority class as its positive value, minority share says
# "extreme" while the configured event occurs in 99.8% of rows. Calling that a
# rare event is simply false.
#
# So two independent assessments are produced from the same counts:
#
#   Event prevalence  -- tiered on the EVENT RATE (the configured positive
#                        value). Answers "is the thing we are modeling rare?"
#   Class imbalance   -- tiered on the MINORITY SHARE. Answers "how uneven are
#                        the two classes?", independent of which one is labelled
#                        the event.
#
# Both ratios are reported with explicit orientation, because "imbalance ratio"
# alone is ambiguous.

# Tiers on the observed EVENT RATE. Each tier is [lower, upper).
PREVALENCE_RULES: List[Dict[str, Any]] = [
    {"label": "Common event", "minEventRate": 0.40, "severity": "none", "rare": False},
    {"label": "Moderately common event", "minEventRate": 0.20, "severity": "none", "rare": False},
    {"label": "Uncommon event", "minEventRate": 0.05, "severity": "low", "rare": False},
    {"label": "Rare event", "minEventRate": 0.01, "severity": "high", "rare": True},
    {"label": "Extreme rare event", "minEventRate": 0.0, "severity": "critical", "rare": True},
]

# Tiers on the MINORITY class share. The thresholds are unchanged from the first
# implementation; only the bottom tier's LABEL changed, from "Extreme rare event"
# to "Extreme imbalance", because that tier describes imbalance and not
# prevalence. CLASS_TRAIN still reports "Extreme rare event" -- from the
# prevalence assessment, where it belongs.
IMBALANCE_RULES: List[Dict[str, Any]] = [
    {"label": "Balanced", "minMinorityShare": 0.40, "severity": "none"},
    {"label": "Mild imbalance", "minMinorityShare": 0.20, "severity": "low"},
    {"label": "Moderate imbalance", "minMinorityShare": 0.05, "severity": "medium"},
    {"label": "Severe imbalance", "minMinorityShare": 0.01, "severity": "high"},
    {"label": "Extreme imbalance", "minMinorityShare": 0.0, "severity": "critical"},
]

# Analytical guidance only. This module never selects a treatment: it does not
# enable SMOTE, set class weights, undersample, or choose a threshold.
RARE_EVENT_IMPLICATIONS: List[str] = [
    "Accuracy will be misleading -- a model that predicts every row as a non-event scores near-perfect accuracy.",
    "Use stratified splitting so the training, validation, and test partitions preserve the observed prevalence.",
    "Confirm that events appear in every cross-validation fold before trusting a fold-averaged metric.",
    "Prioritize PR-AUC, recall, precision, F1, KS, lift, gains, and calibration over accuracy and raw ROC-AUC.",
    "Class weighting or resampling may be appropriate later; evaluate it on the Balancing and Split step.",
    "Compare treatment alternatives against an untreated baseline rather than adopting one automatically.",
]

# When the configured event is the MAJORITY class the binding constraint moves
# to the non-event class, so the guidance has to move with it.
MAJORITY_EVENT_IMPLICATIONS: List[str] = [
    "The configured event is the majority class, so the NON-EVENT class is the minority class here.",
    "Accuracy remains misleading, but for the opposite reason: predicting the event for every row scores well.",
    "Use stratified splitting so both partitions preserve the observed prevalence.",
    "Confirm that non-events appear in every cross-validation fold before trusting a fold-averaged metric.",
    "Report precision, recall, and PR-AUC for the minority (non-event) class as well as the configured event, "
    "or re-express the target so the class of interest is the positive value.",
    "Class weighting or resampling may be appropriate later; evaluate it on the Balancing and Split step.",
    "Compare treatment alternatives against an untreated baseline rather than adopting one automatically.",
]

BALANCED_IMPLICATIONS: List[str] = [
    "Standard classification metrics are usable, though calibration should still be reviewed.",
    "Stratified splitting remains good practice even when the classes are close to balanced.",
]

SINGLE_CLASS_IMPLICATIONS: List[str] = [
    "Only one class is present, so no classification model can be trained or evaluated on this target as defined.",
    "Confirm the target definition, the configured positive value, and the observation and performance windows.",
    "Check whether the event simply has not matured yet within the performance window.",
]


def assess_event_prevalence(event_count: int, non_event_count: int) -> Dict[str, Any]:
    """How common is the CONFIGURED event? Tiered on the event rate.

    Note the deliberate asymmetry with `assess_class_imbalance`: this function
    is orientation-sensitive. Reversing which class is configured as positive
    changes this result, and it should.
    """
    events = max(0, int(event_count))
    non_events = max(0, int(non_event_count))
    total = events + non_events
    if total <= 0:
        return {
            "label": "Not evaluated", "severity": "unknown", "eventRate": None, "nonEventRate": None,
            "eventIsRare": None, "eventIsMajority": None, "singleClass": None,
            "rule": "No non-missing target rows were available to assess.",
            "thresholds": PREVALENCE_RULES,
        }

    event_rate = events / total
    if events == 0 or non_events == 0:
        # A degenerate target has no meaningful prevalence tier. Saying "Extreme
        # rare event" for a column with zero events would imply a modelable but
        # difficult problem, which is not what a single-class column is.
        return {
            "label": "No events observed" if events == 0 else "No non-events observed",
            "severity": "critical",
            "eventRate": event_rate,
            "nonEventRate": 1.0 - event_rate,
            "eventIsRare": events == 0,
            "eventIsMajority": events > 0,
            "singleClass": True,
            "rule": (
                "Only one class is present in the non-missing target, so an event-prevalence tier is not "
                "applicable and no rare-event tier is claimed."
            ),
            "thresholds": PREVALENCE_RULES,
        }

    rule = next(item for item in PREVALENCE_RULES if event_rate >= item["minEventRate"])
    return {
        "label": rule["label"],
        "severity": rule["severity"],
        "eventRate": event_rate,
        "nonEventRate": non_events / total,
        "eventIsRare": bool(rule["rare"]),
        "eventIsMajority": events > non_events,
        "singleClass": False,
        "rule": (
            f"Observed event rate {event_rate:.6%} falls in the "
            f"[{rule['minEventRate']:.0%}, upper) tier for '{rule['label']}'."
        ),
        "thresholds": PREVALENCE_RULES,
    }


def assess_class_imbalance(event_count: int, non_event_count: int) -> Dict[str, Any]:
    """How uneven are the two classes? Tiered on the minority share.

    Orientation-INDEPENDENT: swapping which class is configured as positive does
    not change this result.
    """
    events = max(0, int(event_count))
    non_events = max(0, int(non_event_count))
    total = events + non_events
    if total <= 0:
        return {
            "label": "Not evaluated", "severity": "unknown", "minorityShare": None, "minorityClass": None,
            "minorityCount": None, "majorityCount": None, "majorityToMinorityRatio": None,
            "rule": "No non-missing target rows were available to assess.",
            "thresholds": IMBALANCE_RULES,
        }
    if events == 0 or non_events == 0:
        return {
            "label": "Single class present", "severity": "critical",
            "minorityShare": 0.0, "minorityClass": "event" if events == 0 else "non_event",
            "minorityCount": 0, "majorityCount": total, "majorityToMinorityRatio": None,
            "rule": "Only one class is present, so a two-class imbalance tier is not applicable.",
            "thresholds": IMBALANCE_RULES,
        }

    minority_count = min(events, non_events)
    majority_count = max(events, non_events)
    minority_share = minority_count / total
    rule = next(item for item in IMBALANCE_RULES if minority_share >= item["minMinorityShare"])
    return {
        "label": rule["label"],
        "severity": rule["severity"],
        "minorityShare": minority_share,
        "minorityClass": "event" if events <= non_events else "non_event",
        "minorityCount": minority_count,
        "majorityCount": majority_count,
        # Explicitly oriented and named -- never a bare "imbalance ratio".
        "majorityToMinorityRatio": majority_count / minority_count,
        "rule": (
            f"Minority class share {minority_share:.6%} falls in the "
            f"[{rule['minMinorityShare']:.0%}, upper) tier for '{rule['label']}'."
        ),
        "thresholds": IMBALANCE_RULES,
    }


def assess_class_balance(event_count: int, non_event_count: int) -> Dict[str, Any]:
    """Combined assessment: event prevalence AND class imbalance, plus the
    guidance that follows from whichever condition actually holds.

    The headline `label` describes the CONFIGURED EVENT, because that is what the
    Rare-Event Assessment section is about. `classImbalance.label` is reported
    alongside it, so a majority-class event reads as
    "Common event / Extreme imbalance" rather than as a rare event.
    """
    events = max(0, int(event_count))
    non_events = max(0, int(non_event_count))
    total = events + non_events

    prevalence = assess_event_prevalence(events, non_events)
    imbalance = assess_class_imbalance(events, non_events)

    if total <= 0:
        implications: List[str] = []
    elif prevalence.get("singleClass"):
        implications = SINGLE_CLASS_IMPLICATIONS
    elif prevalence.get("eventIsMajority") and imbalance["label"] != "Balanced":
        implications = MAJORITY_EVENT_IMPLICATIONS
    elif imbalance["label"] == "Balanced":
        implications = BALANCED_IMPLICATIONS
    else:
        implications = RARE_EVENT_IMPLICATIONS

    return {
        # Headline = prevalence of the configured event.
        "label": prevalence["label"],
        "severity": prevalence["severity"] if total > 0 else "unknown",
        "eventPrevalence": prevalence,
        "classImbalance": imbalance,
        # Both ratios, each explicitly oriented. `imbalanceRatio` is retained as
        # an alias of nonEventsPerEvent for existing callers, and every surface
        # that renders it now states the orientation.
        "nonEventsPerEvent": (non_events / events) if events else None,
        "eventsPerNonEvent": (events / non_events) if non_events else None,
        "majorityToMinorityRatio": imbalance.get("majorityToMinorityRatio"),
        "imbalanceRatio": (non_events / events) if events else None,
        "ratioOrientation": "non-events per event",
        "eventToNonEventRatio": (events / non_events) if non_events else None,
        "minorityShare": imbalance.get("minorityShare"),
        "minorityClass": imbalance.get("minorityClass"),
        "minorityCount": imbalance.get("minorityCount"),
        "eventIsRare": prevalence.get("eventIsRare"),
        "eventIsMajority": prevalence.get("eventIsMajority"),
        "singleClass": prevalence.get("singleClass"),
        "rule": f"{prevalence['rule']} {imbalance['rule']}",
        "implications": implications,
        "thresholds": IMBALANCE_RULES,
        "prevalenceThresholds": PREVALENCE_RULES,
    }


# ---------------------------------------------------------------------------
# Part F: event-rate uncertainty
# ---------------------------------------------------------------------------

# Two-sided normal critical values. Kept as a table so the interval never depends
# on SciPy being installed in a deployment's interpreter.
_Z_SCORES: Dict[str, float] = {
    "0.80": 1.2815515655446004,
    "0.90": 1.6448536269514722,
    "0.95": 1.959963984540054,
    "0.98": 2.3263478740408408,
    "0.99": 2.5758293035489004,
}

WILSON_METHOD = "Wilson score interval"

CONFIDENCE_INTERVAL_EXPLANATION = (
    "The interval describes uncertainty in the observed event prevalence. "
    "It does not measure model-performance uncertainty."
)


def wilson_score_interval(events: int, total: int, confidence: float = 0.95) -> Dict[str, Any]:
    """Wilson score interval for a binomial proportion.

    Wilson rather than the normal (Wald) approximation because Wald is invalid
    exactly where this product needs an interval: at a 0.21% event rate with a
    handful of events, Wald produces bounds that can fall below zero and whose
    coverage collapses. Wilson stays inside [0, 1] and keeps nominal coverage at
    small p.

        center = (p + z^2/2n) / (1 + z^2/n)
        half   = z/(1 + z^2/n) * sqrt( p(1-p)/n + z^2/(4n^2) )
    """
    key = f"{float(confidence):.2f}"
    z = _Z_SCORES.get(key)
    if z is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported confidence level {confidence}. Supported levels: {', '.join(sorted(_Z_SCORES))}.",
        )

    n = int(total)
    k = int(events)
    if n <= 0 or k < 0 or k > n:
        return {
            "method": WILSON_METHOD,
            "confidenceLevel": float(key),
            "z": z,
            "eventCount": max(0, k),
            "totalCount": max(0, n),
            "pointEstimate": None,
            "lowerBound": None,
            "upperBound": None,
            "explanation": CONFIDENCE_INTERVAL_EXPLANATION,
        }

    p = k / n
    z_squared_over_n = (z * z) / n
    denominator = 1.0 + z_squared_over_n
    center = (p + (z * z) / (2 * n)) / denominator
    half_width = (z / denominator) * math.sqrt((p * (1.0 - p)) / n + (z * z) / (4.0 * n * n))
    return {
        "method": WILSON_METHOD,
        "confidenceLevel": float(key),
        "z": z,
        "eventCount": k,
        "totalCount": n,
        "pointEstimate": p,
        "lowerBound": max(0.0, center - half_width),
        "upperBound": min(1.0, center + half_width),
        "halfWidth": half_width,
        "explanation": CONFIDENCE_INTERVAL_EXPLANATION,
    }


# ---------------------------------------------------------------------------
# Monotonicity. Single implementation, shared with the EDA workspace service so
# the Target tab and the Predictor tab can never disagree about the same table.
# ---------------------------------------------------------------------------


def classify_monotonicity(rates: List[Optional[float]]) -> str:
    values = [rate for rate in rates if rate is not None]
    if len(values) < 3:
        return "Insufficient bins"
    increasing = all(left <= right for left, right in zip(values, values[1:]))
    decreasing = all(left >= right for left, right in zip(values, values[1:]))
    if increasing and decreasing:
        return "Flat"
    return "Increasing" if increasing else "Decreasing" if decreasing else "Non-monotonic"


# ---------------------------------------------------------------------------
# Part D + E + F: one assessment over the already-cached exact aggregate
# ---------------------------------------------------------------------------


def _fold_binary(
    distribution: List[Dict[str, Any]],
    event_value: Any,
    non_event_value: Any,
) -> Dict[str, Any]:
    """Folds a governed class distribution into event vs non-event.

    Any class that is not the event value is aggregated into non-event, so a
    multi-valued encoding still yields an honest binary view rather than
    silently dropping classes. Mirrors the frontend's `buildTargetDistribution`
    so the two can never disagree.
    """
    total = sum(int(row.get("count") or 0) for row in distribution)
    if total <= 0 or len(distribution) < 2:
        single = distribution[0] if distribution else {}
        requested_single = None if event_value is None else str(event_value)
        # A single-class target still has a real event count: it is the whole
        # population when that class IS the configured event, and zero otherwise.
        matches = bool(requested_single is not None and str(single.get("value")) == requested_single)
        return {
            "eventValue": requested_single if requested_single is not None else (None if not single else str(single.get("value"))),
            "nonEventValue": None,
            "eventCount": total if (matches or requested_single is None) and total else 0,
            "nonEventCount": 0 if (matches or requested_single is None) else total,
            "totalRowCount": total,
            "eventValueResolution": "single_class",
            "requestedEventValue": requested_single,
        }

    values = [str(row.get("value")) for row in distribution]
    requested = None if event_value is None else str(event_value)
    if requested is not None and requested in values:
        resolved_event = requested
        resolution = "configured"
    else:
        # Without an explicit event value the minority class is the event -- the
        # rare class is what a classification project is modeling. When a value
        # WAS requested but is absent from the target, that is recorded, because
        # silently analyzing a different class than the one configured is exactly
        # the kind of substitution a reviewer has to be told about.
        resolved_event = min(distribution, key=lambda row: int(row.get("count") or 0))
        resolved_event = str(resolved_event.get("value"))
        resolution = "requested_value_absent" if requested is not None else "minority_fallback"

    event_count = sum(int(row.get("count") or 0) for row in distribution if str(row.get("value")) == resolved_event)
    non_event_count = total - event_count

    requested_non_event = None if non_event_value is None else str(non_event_value)
    if requested_non_event is not None and requested_non_event in values:
        resolved_non_event = requested_non_event
    else:
        others = [str(row.get("value")) for row in distribution if str(row.get("value")) != resolved_event]
        resolved_non_event = others[0] if len(others) == 1 else "All other values"

    return {
        "eventValue": resolved_event,
        "nonEventValue": resolved_non_event,
        "eventCount": event_count,
        "nonEventCount": non_event_count,
        "totalRowCount": total,
        "eventValueResolution": resolution,
        "requestedEventValue": requested,
    }


def compute_target_assessment(
    *,
    user_scope: str,
    project_id: str,
    dataset_id: str,
    version_id: Optional[str],
    target: str,
    event_value: Any = None,
    non_event_value: Any = None,
    confidence_level: float = 0.95,
    force_exact: bool = False,
) -> Dict[str, Any]:
    """Class balance + imbalance assessment + event-rate confidence interval.

    Deliberately delegates the counts to `compute_target_distribution`: that
    aggregate is already exact, already authorized, and already cached, so this
    endpoint costs a cache read on a warm tab.
    """
    distribution = compute_target_distribution(
        user_scope=user_scope,
        project_id=project_id,
        dataset_id=dataset_id,
        version_id=version_id,
        target=target,
        event_value=event_value,
        non_event_value=non_event_value,
        force_exact=force_exact,
    )

    # Scope is derived from the identity the distribution aggregate ALREADY
    # resolved and cached. Re-resolving the artifact here would cost a second
    # registry read and a second dataset ACL check on every warm request --
    # measured at ~2.4 s of pure overhead on a large dev registry. The fallback
    # covers a cache entry written before those fields existed.
    if distribution.get("artifactChecksum") or distribution.get("datasetName"):
        dataset_name = str(distribution.get("datasetName") or dataset_id)
        checksum = distribution.get("artifactChecksum")
        resolved_version_id = str(distribution.get("versionId") or "")
    else:  # pragma: no cover - only reachable for a pre-upgrade cache entry
        artifact = _resolve_version_artifact(dataset_id, version_id)
        dataset_name = str(artifact.get("datasetName") or dataset_id)
        checksum = artifact.get("checksum")
        resolved_version_id = str(artifact.get("versionId") or "")

    scope = governed_scope(
        project_id=project_id,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        version_id=resolved_version_id,
        artifact_checksum=checksum,
        target=target,
        population_rows=int(distribution.get("totalRowCount") or 0),
        exact=distribution.get("resolution") == "exact",
        analysis_source="analytics.target_assessment",
    )

    if not distribution.get("supported"):
        return {
            "ok": True,
            "supported": False,
            "reason": distribution.get("reason") or "The target is not a supported binary or low-cardinality classification target.",
            "distribution": distribution,
            "analysisScope": scope,
            "scopeIdentity": scope_identity(scope),
            "classBalance": None,
            "imbalance": None,
            "confidenceInterval": None,
        }

    rows = distribution.get("classDistribution") or []
    folded = _fold_binary(rows, distribution.get("eventValue") or event_value, distribution.get("nonEventValue") or non_event_value)
    total = folded["totalRowCount"]
    events = folded["eventCount"]
    non_events = folded["nonEventCount"]

    class_balance = {
        "target": target,
        "eventValue": folded["eventValue"],
        "nonEventValue": folded["nonEventValue"],
        "eventCount": events,
        "nonEventCount": non_events,
        "eventRate": (events / total) if total else None,
        "nonEventRate": (non_events / total) if total else None,
        "eventToNonEventRatio": (events / non_events) if non_events else None,
        "imbalanceRatio": (non_events / events) if events else None,
        # The aggregate groups on the stored value, so NULL targets appear as a
        # null-valued class rather than being silently dropped.
        "missingTargetCount": sum(int(row.get("count") or 0) for row in rows if row.get("value") is None),
        "totalModelingPopulation": total,
        "classCount": len(rows),
        "resolution": distribution.get("resolution"),
        "eventValueResolution": folded.get("eventValueResolution"),
        "requestedEventValue": folded.get("requestedEventValue"),
    }

    return {
        "ok": True,
        "supported": True,
        "datasetId": distribution.get("datasetId"),
        "versionId": distribution.get("versionId"),
        "target": target,
        "distribution": distribution,
        "analysisScope": scope,
        "scopeIdentity": scope_identity(scope),
        "classBalance": class_balance,
        "imbalance": assess_class_balance(events, non_events),
        "confidenceInterval": wilson_score_interval(events, total, confidence_level),
        "cached": bool(distribution.get("cached")),
        "engineVersion": ENGINE_VERSION,
    }


# ---------------------------------------------------------------------------
# Part G: target by predictor
# ---------------------------------------------------------------------------


def _event_predicate(target: str, event_value: Any) -> str:
    column = _quote_identifier(target)
    literal = str(event_value).replace("'", "''")
    return f"CASE WHEN CAST({column} AS VARCHAR) = '{literal}' THEN 1 ELSE 0 END"


def _numeric_bands(scan: str, predictor: str, target: str, event_value: Any, bands: int) -> Dict[str, Any]:
    predictor_column = _quote_identifier(predictor)
    target_column = _quote_identifier(target)
    event_expression = _event_predicate(target, event_value)

    # Only the two columns are projected out of the artifact. NTILE assigns
    # equal-population quantile bands; ties are resolved by NTILE itself, so the
    # bands stay balanced even for a heavily repeated value.
    sql = f"""
    WITH source AS (
      SELECT TRY_CAST({predictor_column} AS DOUBLE) AS predictor_value,
             {event_expression} AS is_event
      FROM {scan}
      WHERE {target_column} IS NOT NULL
    ),
    present AS (
      SELECT predictor_value, is_event,
             NTILE({bands}) OVER (ORDER BY predictor_value) AS band
      FROM source WHERE predictor_value IS NOT NULL
    ),
    banded AS (
      SELECT band, COUNT(*) AS population, SUM(is_event) AS events,
             MIN(predictor_value) AS lower_bound, MAX(predictor_value) AS upper_bound,
             AVG(predictor_value) AS mean_value
      FROM present GROUP BY band
    ),
    absent AS (
      SELECT 0 AS band, COUNT(*) AS population, SUM(is_event) AS events,
             NULL AS lower_bound, NULL AS upper_bound, NULL AS mean_value
      FROM source WHERE predictor_value IS NULL
    )
    SELECT * FROM banded UNION ALL SELECT * FROM absent WHERE population > 0 ORDER BY band
    """
    with _QUERY_LOCK:
        connection = _duckdb().connect()
        try:
            rows = connection.execute(sql).fetchall()
        finally:
            connection.close()

    present_rows: List[Dict[str, Any]] = []
    missing_row: Optional[Dict[str, Any]] = None
    for band, population, events, lower, upper, mean in rows:
        population = int(population or 0)
        events = int(events or 0)
        entry = {
            "band": int(band),
            "label": "Missing" if int(band) == 0 else f"Q{int(band)}",
            "population": population,
            "eventCount": events,
            "eventRate": (events / population) if population else None,
            "lowerBound": None if lower is None else float(lower),
            "upperBound": None if upper is None else float(upper),
            "meanValue": None if mean is None else float(mean),
            "isMissingGroup": int(band) == 0,
            "smallGroup": population < SMALL_GROUP_MIN_ROWS or events < SMALL_GROUP_MIN_EVENTS,
        }
        if entry["isMissingGroup"]:
            missing_row = entry
        else:
            present_rows.append(entry)

    return {"bands": present_rows, "missingGroup": missing_row}


def _categorical_groups(
    scan: str, predictor: str, target: str, event_value: Any, top_n: int
) -> Dict[str, Any]:
    predictor_column = _quote_identifier(predictor)
    target_column = _quote_identifier(target)
    event_expression = _event_predicate(target, event_value)

    # The missing group is ranked separately (rank 0) so it can never be folded
    # into "Other" -- informative missingness must stay visible.
    sql = f"""
    WITH source AS (
      SELECT CAST({predictor_column} AS VARCHAR) AS predictor_value,
             {event_expression} AS is_event
      FROM {scan}
      WHERE {target_column} IS NOT NULL
    ),
    grouped AS (
      SELECT COALESCE(predictor_value, '__MISSING__') AS category,
             COUNT(*) AS population, SUM(is_event) AS events
      FROM source GROUP BY 1
    ),
    ranked AS (
      SELECT category, population, events,
             CASE WHEN category = '__MISSING__' THEN 0
                  ELSE ROW_NUMBER() OVER (PARTITION BY (category = '__MISSING__') ORDER BY population DESC, category)
             END AS rank
      FROM grouped
    )
    SELECT CASE WHEN rank = 0 THEN '__MISSING__' WHEN rank <= {top_n} THEN category ELSE '__OTHER__' END AS category,
           SUM(population) AS population, SUM(events) AS events, COUNT(*) AS collapsed_categories
    FROM ranked GROUP BY 1 ORDER BY population DESC
    """
    count_sql = f"""
    SELECT COUNT(DISTINCT CAST({predictor_column} AS VARCHAR)) FROM {scan} WHERE {predictor_column} IS NOT NULL
    """

    with _QUERY_LOCK:
        connection = _duckdb().connect()
        try:
            distinct_count = int(connection.execute(count_sql).fetchone()[0] or 0)
            if distinct_count > MAX_CATEGORICAL_CARDINALITY:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"'{predictor}' has {distinct_count:,} distinct values and is treated as an identifier "
                        f"rather than a categorical predictor (limit {MAX_CATEGORICAL_CARDINALITY:,})."
                    ),
                )
            rows = connection.execute(sql).fetchall()
        finally:
            connection.close()

    categories: List[Dict[str, Any]] = []
    missing_row: Optional[Dict[str, Any]] = None
    other_row: Optional[Dict[str, Any]] = None
    for category, population, events, collapsed in rows:
        population = int(population or 0)
        events = int(events or 0)
        is_missing = category == "__MISSING__"
        is_other = category == "__OTHER__"
        entry = {
            "category": "Missing" if is_missing else "Other" if is_other else str(category),
            "population": population,
            "eventCount": events,
            "eventRate": (events / population) if population else None,
            "isMissingGroup": is_missing,
            "isOtherGroup": is_other,
            "collapsedCategoryCount": int(collapsed or 0) if is_other else 0,
            "smallGroup": population < SMALL_GROUP_MIN_ROWS or events < SMALL_GROUP_MIN_EVENTS,
        }
        if is_missing:
            missing_row = entry
        elif is_other:
            other_row = entry
        else:
            categories.append(entry)

    return {
        "categories": categories,
        "missingGroup": missing_row,
        "otherGroup": other_row,
        "distinctCategoryCount": distinct_count,
    }


def summarize_target_by_predictor(
    rows: List[Dict[str, Any]],
    *,
    label_key: str,
    missing_group: Optional[Dict[str, Any]],
    other_group: Optional[Dict[str, Any]],
    population_event_rate: Optional[float],
    analysis_type: str,
) -> Dict[str, Any]:
    """Conservative analytical summary of one bounded result table.

    Small groups are excluded from the highest/lowest ranking on purpose: a band
    holding 4 rows and 1 event has a 25% rate that means nothing, and letting it
    win "highest event rate" is precisely how a variable gets called predictive
    on the strength of one band.
    """
    rated = [row for row in rows if row.get("eventRate") is not None]
    stable = [row for row in rated if not row.get("smallGroup")] or rated

    limitations: List[str] = []
    if not rated:
        limitations.append("No group produced an event rate; the analysis has no usable bands.")
        return {
            "highest": None, "lowest": None, "eventRateSpread": None, "monotonicity": "Insufficient bins",
            "eventConcentration": None, "missingEffect": None, "limitations": limitations,
            "smallGroupCount": 0, "interpretation": "This predictor cannot be assessed against the target from the returned groups.",
        }

    if len(stable) < len(rated):
        limitations.append(
            f"{len(rated) - len(stable)} group(s) hold fewer than {SMALL_GROUP_MIN_ROWS} rows or "
            f"{SMALL_GROUP_MIN_EVENTS} events and are excluded from the highest/lowest ranking."
        )

    highest = max(stable, key=lambda row: row["eventRate"])
    lowest = min(stable, key=lambda row: row["eventRate"])
    spread = highest["eventRate"] - lowest["eventRate"]

    total_events = sum(int(row.get("eventCount") or 0) for row in rows)
    if missing_group:
        total_events += int(missing_group.get("eventCount") or 0)
    if other_group:
        total_events += int(other_group.get("eventCount") or 0)
    concentration = (int(highest.get("eventCount") or 0) / total_events) if total_events else None

    monotonicity = (
        classify_monotonicity([row.get("eventRate") for row in rows])
        if analysis_type == "numeric_quantile"
        # Category order is arbitrary, so monotonicity is not a meaningful claim.
        else "Not applicable to categorical groups"
    )

    missing_effect: Optional[Dict[str, Any]] = None
    if missing_group and missing_group.get("population"):
        present_population = sum(int(row.get("population") or 0) for row in rows)
        present_events = sum(int(row.get("eventCount") or 0) for row in rows)
        present_rate = (present_events / present_population) if present_population else None
        missing_rate = missing_group.get("eventRate")
        difference = (
            (missing_rate - present_rate)
            if missing_rate is not None and present_rate is not None
            else None
        )
        missing_effect = {
            "missingPopulation": missing_group.get("population"),
            "missingEventCount": missing_group.get("eventCount"),
            "missingEventRate": missing_rate,
            "presentEventRate": present_rate,
            "difference": difference,
            # A conservative flag, not a conclusion: it says the gap is large
            # enough to look at, not that missingness is informative.
            "materialDifference": bool(
                difference is not None
                and present_rate is not None
                and present_rate > 0
                and abs(difference) >= max(0.5 * present_rate, 0.005)
            ),
        }

    if other_group:
        limitations.append(
            f"{other_group.get('collapsedCategoryCount', 0)} lower-population categories are aggregated into "
            "'Other'; their individual event rates are not shown."
        )
    if population_event_rate is not None and population_event_rate < 0.01:
        limitations.append(
            "The population event rate is below 1%, so per-group rates carry wide uncertainty even at large group sizes."
        )

    interpretation = (
        f"Event rate ranges from {lowest['eventRate']:.4%} in {lowest.get(label_key)} to "
        f"{highest['eventRate']:.4%} in {highest.get(label_key)} (spread {spread:.4%}). "
        "A spread alone does not establish predictive value; confirm it survives out-of-sample and is not a leakage artifact."
    )

    return {
        "highest": {"label": highest.get(label_key), "eventRate": highest["eventRate"], "eventCount": highest.get("eventCount"), "population": highest.get("population")},
        "lowest": {"label": lowest.get(label_key), "eventRate": lowest["eventRate"], "eventCount": lowest.get("eventCount"), "population": lowest.get("population")},
        "eventRateSpread": spread,
        "eventRateRatio": (highest["eventRate"] / lowest["eventRate"]) if lowest["eventRate"] else None,
        "monotonicity": monotonicity,
        "eventConcentration": concentration,
        "missingEffect": missing_effect,
        "smallGroupCount": sum(1 for row in rows if row.get("smallGroup")),
        "limitations": limitations,
        "interpretation": interpretation,
    }


def compute_target_by_predictor(
    *,
    user_scope: str,
    project_id: str,
    dataset_id: str,
    version_id: Optional[str],
    target: str,
    predictor: str,
    analysis_type: str,
    event_value: Any = None,
    bands: int = DEFAULT_BANDS,
    top_categories: int = DEFAULT_TOP_CATEGORIES,
    include_missing: bool = True,
) -> Dict[str, Any]:
    """On-demand grouped event rate for ONE predictor against the target.

    Never called on page load: the caller must explicitly run the analysis. Two
    columns are projected out of the artifact and bounded grouped rows come back
    -- the predictor column and the target column never leave the server.
    """
    if not target:
        raise HTTPException(status_code=400, detail="A target column is required.")
    if not predictor:
        raise HTTPException(status_code=400, detail="A predictor column is required.")
    if predictor == target:
        raise HTTPException(status_code=400, detail="The target cannot be analyzed against itself.")
    if analysis_type not in {"numeric_quantile", "categorical"}:
        raise HTTPException(
            status_code=400,
            detail="Unsupported analysis type. Use 'numeric_quantile' or 'categorical'.",
        )

    bands = max(MIN_BANDS, min(int(bands or DEFAULT_BANDS), MAX_BANDS))
    top_categories = max(MIN_TOP_CATEGORIES, min(int(top_categories or DEFAULT_TOP_CATEGORIES), MAX_TOP_CATEGORIES))

    artifact = _resolve_version_artifact(dataset_id, version_id)
    resolved_version = artifact["versionId"]
    scope = governed_scope(
        project_id=project_id,
        dataset_id=dataset_id,
        dataset_name=str(artifact.get("datasetName") or dataset_id),
        version_id=str(resolved_version or ""),
        artifact_checksum=artifact.get("checksum"),
        target=target,
        population_rows=int(artifact.get("rowCount") or 0),
        exact=True,
        analysis_source="analytics.target_by_predictor",
    )

    cache_key = result_cache.RESULT_CACHE.build_key(
        user_scope=user_scope, project_id=project_id, dataset_id=dataset_id, version_id=resolved_version,
        partition=None, model_id=None, scoring_run_id=None, operation="target_by_predictor",
        selected_columns=[target, predictor], filters=[],
        # Scope identity participates in the cache key, so a governed entry can
        # never be served for a differently-scoped request.
        aggregations={
            "event": str(event_value), "analysis": analysis_type,
            "includeMissing": bool(include_missing), "scope": scope_identity(scope),
        },
        binning=bands if analysis_type == "numeric_quantile" else top_categories,
        sampling_method=None, exact=True, engine_version=ENGINE_VERSION,
    )
    cached = result_cache.RESULT_CACHE.get(cache_key, user_scope=user_scope, project_id=project_id)
    if cached is not None:
        return {**cached, "cached": True, "durationMs": 0}

    started = time.perf_counter()
    scan = _scan_expression(artifact)

    # Without an explicit event value there is nothing to count as an event; the
    # exact class aggregate resolves it (minority class) rather than this query
    # guessing independently.
    resolved_event = event_value
    if resolved_event is None:
        distribution = compute_target_distribution(
            user_scope=user_scope, project_id=project_id, dataset_id=dataset_id,
            version_id=resolved_version, target=target,
        )
        folded = _fold_binary(distribution.get("classDistribution") or [], None, None)
        resolved_event = folded.get("eventValue")
    if resolved_event is None:
        raise HTTPException(
            status_code=422,
            detail="No event value could be resolved for this target, so an event rate cannot be computed.",
        )

    try:
        if analysis_type == "numeric_quantile":
            computed = _numeric_bands(scan, predictor, target, resolved_event, bands)
            rows = computed["bands"]
            missing_group = computed["missingGroup"]
            other_group = None
            label_key = "label"
            extras: Dict[str, Any] = {"requestedBands": bands, "returnedBands": len(rows)}
        else:
            computed = _categorical_groups(scan, predictor, target, resolved_event, top_categories)
            rows = computed["categories"]
            missing_group = computed["missingGroup"]
            other_group = computed["otherGroup"]
            label_key = "category"
            extras = {
                "requestedTopCategories": top_categories,
                "returnedCategories": len(rows),
                "distinctCategoryCount": computed["distinctCategoryCount"],
                "topNApplied": bool(other_group),
                "rareCategoryWarning": bool(
                    computed["distinctCategoryCount"] > top_categories
                    or any(row["smallGroup"] for row in rows)
                ),
            }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Target-by-predictor aggregation failed: {exc}") from exc

    if not include_missing:
        missing_group = None

    total_population = sum(int(row.get("population") or 0) for row in rows)
    total_events = sum(int(row.get("eventCount") or 0) for row in rows)
    for extra in (missing_group, other_group):
        if extra:
            total_population += int(extra.get("population") or 0)
            total_events += int(extra.get("eventCount") or 0)
    population_event_rate = (total_events / total_population) if total_population else None

    payload: Dict[str, Any] = {
        "ok": True,
        "supported": bool(rows),
        "datasetId": dataset_id,
        "versionId": resolved_version,
        "target": target,
        "predictor": predictor,
        "analysisType": analysis_type,
        "analysisScope": scope,
        "scopeIdentity": scope_identity(scope),
        "eventValue": str(resolved_event),
        "includeMissing": bool(include_missing),
        "rows": rows,
        "missingGroup": missing_group,
        "otherGroup": other_group,
        "populationEventRate": population_event_rate,
        "analyzedRowCount": total_population,
        "analyzedEventCount": total_events,
        "summary": summarize_target_by_predictor(
            rows,
            label_key=label_key,
            missing_group=missing_group,
            other_group=other_group,
            population_event_rate=population_event_rate,
            analysis_type=analysis_type,
        ),
        "artifactFormat": artifact["format"],
        "engine": "duckdb",
        "engineVersion": ENGINE_VERSION,
        "resolution": "exact",
        "cached": False,
        "durationMs": int((time.perf_counter() - started) * 1000),
        **extras,
    }

    result_cache.RESULT_CACHE.set(cache_key, payload, user_scope=user_scope, project_id=project_id)
    return payload

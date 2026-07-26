"""Governed full-population profiling -- data quality and WOE/IV.

Why this exists
---------------
`feature_profile_service.profile_features` and `quality_profile_service.
profile_active_dataset` both profile whatever happens to be in the in-memory
DATASTORE and then hardcode `"profileScope": "full_dataset"`. When the workspace
frame was a 100-row browser preview, the response ASSERTED it was the full
registered population -- which is how a preview containing no fraud events
produced a "the target has no events in the registered population" blocker and a
wall of IV values for every predictor.

This module replaces that for target-dependent profiling. It:

  * resolves ONE authorized, immutable artifact per request (never per feature);
  * refuses, with a stable `full_artifact_missing` reason, to profile a legacy
    version whose full artifact was never stored -- it does NOT fall back to
    that version's 5,000-row `data_sample.csv`;
  * computes quality and IV over the governed population with DuckDB;
  * returns bounded aggregates only -- no population rows, no filesystem paths;
  * reports an explicit per-predictor IV STATUS, so "not estimable" is never
    encoded as the number zero.
"""
from __future__ import annotations

import math
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from ..analytics.analysis_scope import (
    FULL_ARTIFACT_MISSING,
    GOVERNED_VERSION,
    LEGACY_ARTIFACT_DISCLOSURE,
    governed_scope,
    scope_identity,
)
from ..analytics import result_cache
from ..datasets.dataset_registry import ARTIFACT_ROOT, require_dataset

CALCULATION_VERSION = "governed-profile/1"

# ---------------------------------------------------------------------------
# Documented analytical conventions. These are reported in every response so a
# reviewer never has to guess which convention produced a number.
# ---------------------------------------------------------------------------

# Additive (Laplace) smoothing. Matches the 0.5 convention already used by
# feature_profile_service.information_value, so Data Acquisition, Balance and
# Split, Outliers, and Credit Risk Studio cannot disagree about the same IV.
SMOOTHING_METHOD = "additive_laplace"
SMOOTHING_CONSTANT = 0.5

MAX_NUMERIC_BINS = 10
# A numeric predictor with at most this many distinct values is binned by value
# rather than by quantile -- quantile bins over 3 distinct values are noise.
LOW_CARDINALITY_NUMERIC = 10

MAX_CATEGORY_BINS = 20
# Beyond this the field is an identifier, not a predictor; it is still bounded
# and disclosed rather than refused, so the table stays complete.
HIGH_CARDINALITY_DISCLOSURE_LIMIT = 1_000

MIN_POPULATION_FOR_IV = 50

# Part D: documented IV strength interpretation. `unusually_strong` is a REVIEW
# prompt, never a leakage verdict.
IV_STRENGTH_BANDS: List[Dict[str, Any]] = [
    {"label": "Not predictive", "minIv": 0.0, "key": "not_predictive"},
    {"label": "Weak", "minIv": 0.02, "key": "weak"},
    {"label": "Medium", "minIv": 0.10, "key": "medium"},
    {"label": "Strong", "minIv": 0.30, "key": "strong"},
    {"label": "Unusually strong -- review for leakage or instability", "minIv": 0.50, "key": "unusually_strong"},
]

# Explicit IV states. Numeric zero is NEVER an error or unavailable state.
IV_STATUS = (
    "pending",
    "available",
    "unavailable_no_events",
    "unavailable_no_non_events",
    "unavailable_nonbinary_target",
    "unavailable_invalid_event_mapping",
    "unavailable_insufficient_population",
    "unavailable_not_eligible",
    "failed",
    "preview_only",
)

_SYSTEM_FIELD = re.compile(r"(^|_)(atlas|system|row)(_id|_key|_split|_metadata)?($|_)", re.IGNORECASE)
_SPLIT_FIELD = re.compile(r"(^|_)(split|fold|partition|sample_role)($|_)", re.IGNORECASE)
_LEAKAGE_FIELD = re.compile(r"target|outcome|future|post[_ ]|label|response", re.IGNORECASE)
_DATE_NAME = re.compile(r"(^|_)(date|datetime|timestamp|time|dt)($|_)", re.IGNORECASE)

_QUERY_LOCK = threading.Lock()


def _duckdb():
    try:
        import duckdb  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - deployment dependent
        raise HTTPException(
            status_code=503,
            detail="The DuckDB analytical engine is not installed, so governed profiling is unavailable.",
        ) from exc
    return duckdb


def _q(name: str) -> str:
    """Identifier quoting. Column names come from user data and are NEVER
    interpolated unquoted; values are compared as bound literals only."""
    return '"' + str(name).replace('"', '""') + '"'


def _lit(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def iv_strength(iv: Optional[float]) -> Optional[Dict[str, str]]:
    if iv is None or not math.isfinite(iv):
        return None
    band = IV_STRENGTH_BANDS[0]
    for candidate in IV_STRENGTH_BANDS:
        if iv >= candidate["minIv"]:
            band = candidate
    return {"key": band["key"], "label": band["label"]}


# ---------------------------------------------------------------------------
# Part B: one authorized artifact resolution per request
# ---------------------------------------------------------------------------


def resolve_governed_artifact(dataset_id: str, version_id: Optional[str]) -> Dict[str, Any]:
    """Authorizes and resolves ONE immutable artifact.

    `require_dataset` performs the dataset ACL check. A version registered before
    ATLAS stored full artifacts is refused with a stable machine-readable reason
    -- its `data_sample.csv` is deliberately NOT offered as a substitute, because
    a 5,000-row sample cannot answer a full-population question and presenting it
    as one is the exact defect this phase exists to remove.
    """
    dataset = require_dataset(dataset_id)
    versions = dataset.get("versions") or []
    version = next((item for item in versions if item.get("versionId") == version_id), versions[-1] if versions else None)
    if not version:
        raise HTTPException(status_code=404, detail="Dataset version not found.")

    relative = version.get("analyticalParquetPath") or version.get("fullDataPath")
    if not relative:
        raise HTTPException(
            status_code=409,
            detail={
                "ok": False,
                "reason": FULL_ARTIFACT_MISSING,
                "message": (
                    f"Dataset version {version.get('versionId')} does not contain a complete data artifact, so it "
                    "cannot support governed full-population profiling."
                ),
                "disclosure": LEGACY_ARTIFACT_DISCLOSURE,
                "datasetId": dataset_id,
                "datasetName": dataset.get("name"),
                "versionId": version.get("versionId"),
                "declaredRowCount": version.get("rowCount"),
                "recovery": [
                    "Select a Dataset Version that has a complete governed artifact.",
                    "Or re-register the original source file as a new immutable version.",
                ],
                "sampleSubstituted": False,
            },
        )

    candidate = (ARTIFACT_ROOT / str(relative)).resolve()
    root = ARTIFACT_ROOT.resolve()
    if not (root in candidate.parents or candidate == root) or not candidate.exists():
        raise HTTPException(
            status_code=409,
            detail={
                "ok": False,
                "reason": FULL_ARTIFACT_MISSING,
                "message": "The registered artifact for this dataset version is not present on disk.",
                "disclosure": LEGACY_ARTIFACT_DISCLOSURE,
                "datasetId": dataset_id,
                "versionId": version.get("versionId"),
                "sampleSubstituted": False,
            },
        )

    return {
        "path": candidate,
        "format": "parquet" if version.get("analyticalParquetPath") else "csv",
        "versionId": version.get("versionId"),
        "rowCount": version.get("rowCount"),
        "columnCount": version.get("columnCount"),
        "checksum": version.get("hash"),
        "datasetName": dataset.get("name") or dataset_id,
    }


def _scan(artifact: Dict[str, Any]) -> str:
    path = artifact["path"].as_posix().replace("'", "''")
    if artifact["format"] == "parquet":
        return f"read_parquet('{path}')"
    return f"read_csv('{path}', all_varchar=true, header=true)"


class _Session:
    """One artifact, read into DuckDB once.

    Profiling 30 predictors used to mean 30 independent reads of an 86 MB CSV.
    Materializing a single temp table makes every subsequent per-column
    aggregate cheap, and satisfies "no duplicate artifact resolution and no
    unnecessary rescan within one profile request".
    """

    def __init__(self, artifact: Dict[str, Any]) -> None:
        self.artifact = artifact
        self.connection = _duckdb().connect()
        self.scans = 0
        self.connection.execute(f"CREATE TEMP TABLE src AS SELECT * FROM {_scan(artifact)}")
        self.scans += 1
        self.columns: List[str] = [row[0] for row in self.connection.execute("DESCRIBE src").fetchall()]

    def close(self) -> None:
        try:
            self.connection.close()
        except Exception:  # noqa: BLE001
            pass

    def one(self, sql: str) -> Tuple:
        return self.connection.execute(sql).fetchone()

    def all(self, sql: str) -> List[Tuple]:
        return self.connection.execute(sql).fetchall()


# ---------------------------------------------------------------------------
# Part E: target and event mapping, resolved once and safely
# ---------------------------------------------------------------------------


def resolve_target_mapping(
    session: _Session, target: str, event_value: Any, non_event_value: Any
) -> Dict[str, Any]:
    """Resolves the event / non-event mapping against the governed population.

    String and numeric equivalents are compared as trimmed strings, so 1 and "1"
    are the same class. An event value that is absent from the population is
    reported as such rather than silently producing valid-looking IV.
    """
    if target not in session.columns:
        raise HTTPException(status_code=422, detail=f"Target '{target}' does not exist in this dataset version.")

    event_text = None if event_value is None else str(event_value).strip()
    non_event_text = None if non_event_value is None else str(non_event_value).strip()
    if event_text is not None and non_event_text is not None and event_text == non_event_text:
        raise HTTPException(
            status_code=422,
            detail="The event value and the non-event value cannot be identical.",
        )

    column = _q(target)
    rows = session.all(
        f"SELECT TRIM(CAST({column} AS VARCHAR)) AS v, COUNT(*) AS n FROM src "
        f"WHERE {column} IS NOT NULL AND TRIM(CAST({column} AS VARCHAR)) <> '' "
        f"GROUP BY 1 ORDER BY n DESC LIMIT 64"
    )
    distribution = [{"value": row[0], "count": int(row[1])} for row in rows]
    missing = int(
        session.one(
            f"SELECT COUNT(*) FROM src WHERE {column} IS NULL OR TRIM(CAST({column} AS VARCHAR)) = ''"
        )[0]
    )
    valid_total = sum(item["count"] for item in distribution)
    present = {item["value"] for item in distribution}

    resolution = "configured"
    resolved_event = event_text
    if resolved_event is None:
        resolved_event = "1" if "1" in present else None
        resolution = "defaulted_to_one" if resolved_event else "unresolved"
    elif resolved_event not in present:
        resolution = "event_value_absent"

    resolved_non_event = non_event_text
    if resolved_non_event is None:
        others = [item["value"] for item in distribution if item["value"] != resolved_event]
        resolved_non_event = others[0] if len(others) == 1 else None

    event_count = next((item["count"] for item in distribution if item["value"] == resolved_event), 0)
    non_event_count = valid_total - event_count if resolved_event is not None else 0

    return {
        "target": target,
        "eventValue": resolved_event,
        "nonEventValue": resolved_non_event if resolved_non_event is not None else "All other values",
        "eventValueResolution": resolution,
        "requestedEventValue": event_text,
        "requestedNonEventValue": non_event_text,
        "distinctCount": len(distribution),
        "isBinary": len(distribution) == 2,
        "classDistribution": distribution[:MAX_CATEGORY_BINS],
        "missingTargetCount": missing,
        "validTargetCount": valid_total,
        "eventCount": int(event_count),
        "nonEventCount": int(non_event_count),
        "eventRate": (event_count / valid_total) if valid_total else None,
    }


def _event_expression(target: str, event_value: Optional[str]) -> str:
    if event_value is None:
        return "0"
    return f"CASE WHEN TRIM(CAST({_q(target)} AS VARCHAR)) = {_lit(event_value)} THEN 1 ELSE 0 END"


def _valid_target_predicate(target: str) -> str:
    column = _q(target)
    return f"{column} IS NOT NULL AND TRIM(CAST({column} AS VARCHAR)) <> ''"


# ---------------------------------------------------------------------------
# Part C: full-population data quality
# ---------------------------------------------------------------------------


def compute_quality(session: _Session, mapping: Dict[str, Any], target: str) -> Dict[str, Any]:
    """Governed data quality over the complete artifact.

    Duplicate counting matches `pandas.DataFrame.duplicated().sum()` -- the count
    of rows that repeat a previous row, not the number of duplicate groups. Both
    were verified against the CLASS_TRAIN artifact (52).
    """
    row_count = int(session.one("SELECT COUNT(*) FROM src")[0])
    columns = session.columns
    quoted = ", ".join(_q(column) for column in columns)
    duplicate_rows = int(
        session.one(
            f"SELECT COALESCE(SUM(n - 1), 0) FROM (SELECT COUNT(*) AS n FROM src GROUP BY {quoted} HAVING COUNT(*) > 1) t"
        )[0]
    )

    # One pass for every column's missing count, distinct count, and blank count.
    missing_parts = []
    for column in columns:
        c = _q(column)
        missing_parts.append(
            f"SUM(CASE WHEN {c} IS NULL OR TRIM(CAST({c} AS VARCHAR)) = '' THEN 1 ELSE 0 END)"
        )
        missing_parts.append(f"COUNT(DISTINCT CAST({c} AS VARCHAR))")
    aggregate = session.one(f"SELECT {', '.join(missing_parts)} FROM src")

    missingness: List[Dict[str, Any]] = []
    constant_columns: List[str] = []
    high_cardinality: List[str] = []
    for index, column in enumerate(columns):
        missing = int(aggregate[index * 2] or 0)
        distinct = int(aggregate[index * 2 + 1] or 0)
        missingness.append({
            "column": str(column),
            "count": missing,
            "percent": (missing / row_count) if row_count else 0.0,
            "distinctCount": distinct,
        })
        # Part H: the TARGET is not a predictor. In a rare-event model the
        # target's low prevalence is a target characteristic, not a predictor
        # near-zero-variance or constant-column defect. Reporting `Class` as a
        # near-zero-variance predictor is what made the acceptance walkthrough
        # look like the fraud flag was a broken feature.
        if distinct <= 1 and str(column) != target:
            constant_columns.append(str(column))
        if distinct > max(50, int(row_count * 0.5)) and str(column) != target:
            high_cardinality.append(str(column))

    # Near-zero variance: one class covers 99% or more of the non-missing values.
    near_zero: List[str] = []
    for column in columns:
        if str(column) in constant_columns or str(column) == target:
            continue
        c = _q(column)
        top = session.one(
            f"SELECT COUNT(*) FROM src WHERE {c} IS NOT NULL GROUP BY CAST({c} AS VARCHAR) ORDER BY COUNT(*) DESC LIMIT 1"
        )
        if top and row_count and (int(top[0]) / row_count) >= 0.99:
            near_zero.append(str(column))

    leakage = [str(column) for column in columns if str(column) != target and _LEAKAGE_FIELD.search(str(column))]
    date_fields = [str(column) for column in columns if _DATE_NAME.search(str(column))]

    columns_with_missing = sum(1 for row in missingness if row["count"] > 0)
    return {
        "populationRows": row_count,
        "columnCount": len(columns),
        "duplicateRows": duplicate_rows,
        "columnsWithMissingValues": columns_with_missing,
        "missingness": sorted(missingness, key=lambda row: row["percent"], reverse=True),
        "targetExcludedFromPredictorFindings": str(target),
        "constantColumns": constant_columns,
        "nearZeroVarianceColumns": near_zero,
        "highCardinalityColumns": high_cardinality[:50],
        "potentialLeakageColumns": leakage[:50],
        "dateFields": date_fields[:50],
        "targetMissingCount": mapping["missingTargetCount"],
        "targetDistinctCount": mapping["distinctCount"],
        "eventCount": mapping["eventCount"],
        "nonEventCount": mapping["nonEventCount"],
        "eventRate": mapping["eventRate"],
    }


# ---------------------------------------------------------------------------
# Part D: WOE and IV
# ---------------------------------------------------------------------------


def _iv_from_bins(bins: List[Dict[str, Any]], total_events: int, total_non_events: int) -> Tuple[float, List[Dict[str, Any]]]:
    """Smoothed WOE/IV over the supplied bins.

    Smoothing is applied to BOTH class distributions with the same constant, and
    the denominators include the constant times the bin count, so the two
    distributions each remain a proper probability distribution.
    """
    count = len(bins)
    event_denominator = total_events + SMOOTHING_CONSTANT * count
    non_event_denominator = total_non_events + SMOOTHING_CONSTANT * count
    iv = 0.0
    detail: List[Dict[str, Any]] = []
    for entry in bins:
        events = int(entry["eventCount"])
        non_events = int(entry["nonEventCount"])
        event_distribution = (events + SMOOTHING_CONSTANT) / event_denominator
        non_event_distribution = (non_events + SMOOTHING_CONSTANT) / non_event_denominator
        woe = math.log(event_distribution / non_event_distribution)
        contribution = (event_distribution - non_event_distribution) * woe
        iv += contribution
        population = events + non_events
        detail.append({
            **entry,
            "population": population,
            "eventRate": (events / population) if population else None,
            "eventDistribution": event_distribution,
            "nonEventDistribution": non_event_distribution,
            "woe": woe,
            "ivContribution": contribution,
        })
    return iv, detail


def _numeric_bins(session: _Session, predictor: str, target: str, event_expression: str) -> Optional[List[Dict[str, Any]]]:
    column = _q(predictor)
    valid = _valid_target_predicate(target)
    distinct = int(
        session.one(f"SELECT COUNT(DISTINCT TRY_CAST({column} AS DOUBLE)) FROM src WHERE {valid}")[0] or 0
    )
    if distinct == 0:
        return None

    if distinct <= LOW_CARDINALITY_NUMERIC:
        rows = session.all(
            f"SELECT CAST(TRY_CAST({column} AS DOUBLE) AS VARCHAR) AS label, "
            f"COUNT(*) AS n, SUM({event_expression}) AS ev, "
            f"MIN(TRY_CAST({column} AS DOUBLE)) AS lo, MAX(TRY_CAST({column} AS DOUBLE)) AS hi "
            f"FROM src WHERE {valid} AND TRY_CAST({column} AS DOUBLE) IS NOT NULL GROUP BY 1 ORDER BY lo"
        )
        bins = [
            {
                "bin": index + 1,
                "label": f"= {row[3]:g}" if row[3] is not None else str(row[0]),
                "lowerBound": None if row[3] is None else float(row[3]),
                "upperBound": None if row[4] is None else float(row[4]),
                "eventCount": int(row[2] or 0),
                "nonEventCount": int(row[1] or 0) - int(row[2] or 0),
                "isMissingBin": False,
            }
            for index, row in enumerate(rows)
        ]
        method = "distinct_value"
    else:
        # Quantile cut points, then DEDUPED. A heavily repeated value would
        # otherwise produce several bins sharing an identical boundary; collapsing
        # them is the honest treatment and is reported via effectiveBinCount.
        quantiles = ", ".join(f"{index / MAX_NUMERIC_BINS:.4f}" for index in range(1, MAX_NUMERIC_BINS))
        raw = session.one(
            f"SELECT quantile_cont(TRY_CAST({column} AS DOUBLE), [{quantiles}]) FROM src "
            f"WHERE {valid} AND TRY_CAST({column} AS DOUBLE) IS NOT NULL"
        )[0]
        cuts = sorted({float(value) for value in (raw or []) if value is not None})
        if not cuts:
            return None
        case_parts = [f"WHEN v <= {cut!r} THEN {index}" for index, cut in enumerate(cuts)]
        case_sql = "CASE " + " ".join(case_parts) + f" ELSE {len(cuts)} END"
        rows = session.all(
            f"WITH base AS (SELECT TRY_CAST({column} AS DOUBLE) AS v, {event_expression} AS e FROM src WHERE {valid}) "
            f"SELECT {case_sql} AS b, COUNT(*) AS n, SUM(e) AS ev, MIN(v) AS lo, MAX(v) AS hi "
            f"FROM base WHERE v IS NOT NULL GROUP BY 1 ORDER BY 1"
        )
        bins = [
            {
                "bin": int(row[0]) + 1,
                "label": f"({row[3]:g} .. {row[4]:g}]" if row[3] is not None else "bin",
                "lowerBound": None if row[3] is None else float(row[3]),
                "upperBound": None if row[4] is None else float(row[4]),
                "eventCount": int(row[2] or 0),
                "nonEventCount": int(row[1] or 0) - int(row[2] or 0),
                "isMissingBin": False,
            }
            for row in rows
        ]
        method = "quantile"

    # Missing predictor values are always their own bin -- informative
    # missingness must never be silently folded into a value bin.
    missing = session.one(
        f"SELECT COUNT(*) AS n, SUM({event_expression}) AS ev FROM src "
        f"WHERE {valid} AND TRY_CAST({column} AS DOUBLE) IS NULL"
    )
    missing_count = int(missing[0] or 0)
    if missing_count:
        bins.append({
            "bin": 0,
            "label": "Missing",
            "lowerBound": None,
            "upperBound": None,
            "eventCount": int(missing[1] or 0),
            "nonEventCount": missing_count - int(missing[1] or 0),
            "isMissingBin": True,
        })

    for entry in bins:
        entry["binningMethod"] = method
    return bins


def _categorical_bins(session: _Session, predictor: str, target: str, event_expression: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    column = _q(predictor)
    valid = _valid_target_predicate(target)
    rows = session.all(
        f"SELECT COALESCE(NULLIF(TRIM(CAST({column} AS VARCHAR)), ''), '__MISSING__') AS g, "
        f"COUNT(*) AS n, SUM({event_expression}) AS ev FROM src WHERE {valid} GROUP BY 1 ORDER BY n DESC"
    )
    distinct_total = len([row for row in rows if row[0] != "__MISSING__"])

    missing_row = next((row for row in rows if row[0] == "__MISSING__"), None)
    present = [row for row in rows if row[0] != "__MISSING__"]
    kept = present[:MAX_CATEGORY_BINS]
    collapsed = present[MAX_CATEGORY_BINS:]

    bins: List[Dict[str, Any]] = [
        {
            "bin": index + 1,
            "label": str(row[0]),
            "eventCount": int(row[2] or 0),
            "nonEventCount": int(row[1] or 0) - int(row[2] or 0),
            "isMissingBin": False,
            "isOtherBin": False,
        }
        for index, row in enumerate(kept)
    ]
    if collapsed:
        # "Other" never absorbs Missing -- they answer different questions.
        bins.append({
            "bin": len(bins) + 1,
            "label": "Other",
            "eventCount": sum(int(row[2] or 0) for row in collapsed),
            "nonEventCount": sum(int(row[1] or 0) - int(row[2] or 0) for row in collapsed),
            "isMissingBin": False,
            "isOtherBin": True,
            "collapsedCategoryCount": len(collapsed),
        })
    if missing_row:
        bins.append({
            "bin": 0,
            "label": "Missing",
            "eventCount": int(missing_row[2] or 0),
            "nonEventCount": int(missing_row[1] or 0) - int(missing_row[2] or 0),
            "isMissingBin": True,
            "isOtherBin": False,
        })

    grouping = {
        "distinctCategoryCount": distinct_total,
        "retainedCategoryCount": len(kept),
        "collapsedCategoryCount": len(collapsed),
        "groupingApplied": bool(collapsed),
        "highCardinality": distinct_total > HIGH_CARDINALITY_DISCLOSURE_LIMIT,
        "rule": (
            f"The {MAX_CATEGORY_BINS} highest-population categories are retained; the remainder are aggregated "
            "into a disclosed 'Other' bin. Missing is always a separate bin and is never merged into 'Other'. "
            "The reported IV is the IV of this grouping."
        ),
    }
    for entry in bins:
        entry["binningMethod"] = "category"
    return bins, grouping


def compute_predictor_iv(
    session: _Session,
    predictor: str,
    target: str,
    mapping: Dict[str, Any],
    problem_type: str,
) -> Dict[str, Any]:
    """IV for one predictor, or an explicit reason it is not estimable.

    Returns `iv: None` with a status whenever the value cannot be computed. Zero
    is only ever a genuine, computed IV.
    """
    base = {
        "predictor": predictor,
        "iv": None,
        "ivStatus": "pending",
        "ivStrength": None,
        "bins": [],
        "binningMethod": None,
        "effectiveBinCount": 0,
        "grouping": None,
        "totalEvents": mapping["eventCount"],
        "totalNonEvents": mapping["nonEventCount"],
        "smoothingMethod": SMOOTHING_METHOD,
        "smoothingConstant": SMOOTHING_CONSTANT,
    }

    if problem_type != "classification":
        return {**base, "ivStatus": "unavailable_nonbinary_target"}
    # A single-class target is reported as "no events" / "no non-events" rather
    # than "nonbinary": both are true, but the class-count answer tells the
    # reviewer what is actually wrong with the target.
    if mapping["distinctCount"] <= 1:
        return {
            **base,
            "ivStatus": "unavailable_no_events" if mapping["eventCount"] == 0 else "unavailable_no_non_events",
        }
    if not mapping["isBinary"]:
        return {**base, "ivStatus": "unavailable_nonbinary_target"}
    if mapping["eventValueResolution"] in {"unresolved", "event_value_absent"}:
        return {**base, "ivStatus": "unavailable_invalid_event_mapping"}
    if mapping["eventCount"] == 0:
        return {**base, "ivStatus": "unavailable_no_events"}
    if mapping["nonEventCount"] == 0:
        return {**base, "ivStatus": "unavailable_no_non_events"}
    if mapping["validTargetCount"] < MIN_POPULATION_FOR_IV:
        return {**base, "ivStatus": "unavailable_insufficient_population"}

    event_expression = _event_expression(target, mapping["eventValue"])
    try:
        column = _q(predictor)
        numeric_rate = session.one(
            f"SELECT COALESCE(AVG(CASE WHEN TRY_CAST({column} AS DOUBLE) IS NOT NULL THEN 1.0 ELSE 0.0 END), 0) "
            f"FROM src WHERE {column} IS NOT NULL"
        )[0]
        is_numeric = float(numeric_rate or 0) >= 0.8

        grouping = None
        if is_numeric:
            bins = _numeric_bins(session, predictor, target, event_expression)
        else:
            bins, grouping = _categorical_bins(session, predictor, target, event_expression)

        if not bins:
            return {**base, "ivStatus": "unavailable_insufficient_population"}

        iv, detail = _iv_from_bins(bins, mapping["eventCount"], mapping["nonEventCount"])
        binned_events = sum(entry["eventCount"] for entry in bins)
        binned_non_events = sum(entry["nonEventCount"] for entry in bins)
        return {
            **base,
            "iv": float(iv),
            "ivStatus": "available",
            "ivStrength": iv_strength(iv),
            "bins": detail,
            "binningMethod": bins[0].get("binningMethod"),
            "effectiveBinCount": len(bins),
            "grouping": grouping,
            # Reconciliation: the bins must account for the whole
            # target-dependent population, or the IV is not trustworthy.
            "binnedEventCount": binned_events,
            "binnedNonEventCount": binned_non_events,
            "reconciled": binned_events == mapping["eventCount"] and binned_non_events == mapping["nonEventCount"],
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        return {**base, "ivStatus": "failed", "failureReason": str(exc)[:300]}


def _role_for(column: str, target: str) -> Tuple[str, str]:
    if column == target:
        return "target", "Target column"
    if _SPLIT_FIELD.search(column):
        return "split_indicator", "Split or fold indicator"
    if _SYSTEM_FIELD.search(column):
        return "system_metadata", "System metadata field"
    if _LEAKAGE_FIELD.search(column):
        return "potential_leakage", "Potential post-outcome or target-derived field"
    return "eligible", ""


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def governed_target_profile(
    *,
    user_scope: str,
    project_id: str,
    dataset_id: str,
    version_id: Optional[str],
    target: str,
    event_value: Any = None,
    non_event_value: Any = None,
    problem_type: str = "classification",
    include_iv: bool = True,
    selected_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Governed quality + WOE/IV over ONE immutable artifact.

    The artifact is resolved once and read once; every predictor is then profiled
    against the materialized table.
    """
    started = time.perf_counter()
    artifact = resolve_governed_artifact(dataset_id, version_id)

    cache_key = result_cache.RESULT_CACHE.build_key(
        user_scope=user_scope, project_id=project_id, dataset_id=dataset_id,
        version_id=str(artifact["versionId"]), partition=None, model_id=None, scoring_run_id=None,
        operation="governed_target_profile",
        selected_columns=[target], filters=[],
        # Target AND event mapping participate in cache identity: changing either
        # must invalidate every target-dependent result.
        aggregations={
            "event": str(event_value), "nonEvent": str(non_event_value),
            "problem": problem_type, "iv": bool(include_iv),
            "checksum": str(artifact.get("checksum")),
        },
        binning=MAX_NUMERIC_BINS, sampling_method=None, exact=True, engine_version=CALCULATION_VERSION,
    )
    cached = result_cache.RESULT_CACHE.get(cache_key, user_scope=user_scope, project_id=project_id)
    if cached is not None:
        return {**cached, "cached": True, "durationMs": 0}

    with _QUERY_LOCK:
        session = _Session(artifact)
        try:
            mapping = resolve_target_mapping(session, target, event_value, non_event_value)
            quality = compute_quality(session, mapping, target)

            scope = governed_scope(
                project_id=project_id, dataset_id=dataset_id,
                dataset_name=str(artifact["datasetName"]), version_id=str(artifact["versionId"]),
                artifact_checksum=artifact.get("checksum"), target=target,
                population_rows=quality["populationRows"], exact=True,
                analysis_source="preprocessing.governed_target_profile",
            )
            scope["profiledRows"] = quality["populationRows"]
            scope["decisionReady"] = True

            predictors: List[Dict[str, Any]] = []
            if include_iv:
                allowed = set(selected_columns or []) or None
                for column in session.columns:
                    role, reason = _role_for(str(column), target)
                    entry: Dict[str, Any] = {
                        "predictor": str(column),
                        "role": role,
                        "exclusionReason": reason,
                        "eligible": role == "eligible",
                    }
                    if role != "eligible":
                        entry.update({
                            "iv": None, "ivStatus": "unavailable_not_eligible", "ivStrength": None,
                            "bins": [], "effectiveBinCount": 0,
                        })
                    elif allowed is not None and str(column) not in allowed:
                        entry.update({
                            "iv": None, "ivStatus": "unavailable_not_eligible", "ivStrength": None,
                            "bins": [], "effectiveBinCount": 0,
                            "exclusionReason": "Not in the approved predictor selection",
                        })
                    else:
                        entry.update(compute_predictor_iv(session, str(column), target, mapping, problem_type))
                    # Bin detail is bounded; the browser gets summaries, not curves.
                    entry["bins"] = entry.get("bins", [])[:MAX_CATEGORY_BINS + 2]
                    predictors.append(entry)
            scans = session.scans
        finally:
            session.close()

    available = [item for item in predictors if item.get("ivStatus") == "available"]
    payload: Dict[str, Any] = {
        "ok": True,
        "analysisScope": scope,
        "scopeIdentity": scope_identity(scope),
        "profileScope": GOVERNED_VERSION,
        "calculationVersion": CALCULATION_VERSION,
        "generatedAt": scope["resolvedAt"],
        "datasetId": dataset_id,
        "datasetVersionId": artifact["versionId"],
        "datasetName": artifact["datasetName"],
        "artifactChecksum": artifact.get("checksum"),
        "target": target,
        "targetMapping": mapping,
        "quality": quality,
        "problemType": problem_type,
        "predictors": predictors,
        "predictorSummary": {
            "total": len(predictors),
            "evaluated": len(available),
            "unavailable": len([item for item in predictors if str(item.get("ivStatus", "")).startswith("unavailable")]),
            "failed": len([item for item in predictors if item.get("ivStatus") == "failed"]),
            "leakageReview": len([item for item in predictors if item.get("role") == "potential_leakage"]),
        },
        "methodology": {
            "sourcePopulation": f"Registered dataset version {artifact['versionId']} ({quality['populationRows']:,} rows)",
            "targetMapping": f"event = {mapping['eventValue']}, non-event = {mapping['nonEventValue']}",
            "numericBinning": f"Up to {MAX_NUMERIC_BINS} quantile bins with duplicate cut points collapsed; predictors with at most {LOW_CARDINALITY_NUMERIC} distinct values are binned by value.",
            "categoricalGrouping": f"Top {MAX_CATEGORY_BINS} categories retained, remainder aggregated into a disclosed 'Other' bin; Missing is always separate.",
            "missingTreatment": "Missing predictor values form their own bin and are never merged into a value bin or into 'Other'.",
            "smoothing": f"{SMOOTHING_METHOD} with constant {SMOOTHING_CONSTANT}",
            "strengthBands": IV_STRENGTH_BANDS,
            "exact": True,
            "sampled": False,
        },
        "artifactResolutions": 1,
        "datasetScans": scans,
        "cached": False,
        "durationMs": int((time.perf_counter() - started) * 1000),
    }
    result_cache.RESULT_CACHE.set(cache_key, payload, user_scope=user_scope, project_id=project_id)
    return payload


class _FrameSession(_Session):
    """A `_Session` backed by the in-memory workspace frame instead of an artifact.

    Registering the frame with DuckDB means the workspace path runs the SAME SQL
    and therefore the SAME binning, smoothing, and reconciliation as the governed
    path -- the two can differ in SCOPE but never in method.
    """

    def __init__(self, frame: Any) -> None:  # noqa: D107 - see class docstring
        self.artifact = {"format": "workspace", "versionId": None}
        self.connection = _duckdb().connect()
        self.connection.register("workspace_frame", frame)
        self.connection.execute("CREATE TEMP TABLE src AS SELECT * FROM workspace_frame")
        self.scans = 1
        self.columns = [row[0] for row in self.connection.execute("DESCRIBE src").fetchall()]


def workspace_target_profile(
    *,
    user_scope: str,
    project_id: str,
    target: str,
    event_value: Any = None,
    non_event_value: Any = None,
    problem_type: str = "classification",
    include_iv: bool = True,
    selected_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Profiles the in-memory backend population, declaring its scope honestly.

    `workspace_draft` when the backend holds what the source says is the whole
    population; `preview_only` when it demonstrably holds less. A preview_only
    result never carries IV, because a bounded preview cannot answer a
    population question -- that refusal is the point of this phase.
    """
    from ..analytics.analysis_scope import preview_scope, workspace_fingerprint, workspace_scope  # noqa: PLC0415
    from ..core.dataset_store import DATASTORE  # noqa: PLC0415

    started = time.perf_counter()
    frame = DATASTORE.get_base_df()
    if frame is None or frame.empty:
        raise HTTPException(status_code=409, detail="No backend dataset is loaded for this project.")

    source = DATASTORE.meta.get("source") if isinstance(DATASTORE.meta.get("source"), dict) else {}
    declared_rows = int(source.get("rows") or 0)
    loaded_rows = int(len(frame))
    # The backend holds fewer rows than the source declares => what is loaded is
    # a bounded preview, not the population.
    is_preview = bool(declared_rows and loaded_rows < declared_rows)
    fingerprint = workspace_fingerprint(frame, target, source)

    with _QUERY_LOCK:
        session = _FrameSession(frame)
        try:
            mapping = resolve_target_mapping(session, target, event_value, non_event_value)
            quality = compute_quality(session, mapping, target)
            predictors: List[Dict[str, Any]] = []
            # preview_only never produces IV.
            if include_iv and not is_preview:
                allowed = set(selected_columns or []) or None
                for column in session.columns:
                    role, reason = _role_for(str(column), target)
                    entry: Dict[str, Any] = {
                        "predictor": str(column), "role": role,
                        "exclusionReason": reason, "eligible": role == "eligible",
                    }
                    if role != "eligible" or (allowed is not None and str(column) not in allowed):
                        entry.update({"iv": None, "ivStatus": "unavailable_not_eligible", "ivStrength": None, "bins": [], "effectiveBinCount": 0})
                    else:
                        entry.update(compute_predictor_iv(session, str(column), target, mapping, problem_type))
                    entry["bins"] = entry.get("bins", [])[:MAX_CATEGORY_BINS + 2]
                    predictors.append(entry)
            elif include_iv and is_preview:
                for column in session.columns:
                    role, reason = _role_for(str(column), target)
                    predictors.append({
                        "predictor": str(column), "role": role, "exclusionReason": reason,
                        "eligible": role == "eligible", "iv": None,
                        "ivStatus": "preview_only", "ivStrength": None, "bins": [], "effectiveBinCount": 0,
                    })
        finally:
            session.close()

    if is_preview:
        scope = preview_scope(
            project_id=project_id, target=target, profiled_rows=loaded_rows,
            population_rows=declared_rows or loaded_rows, fingerprint=fingerprint,
            dataset_name=str(source.get("filename") or "Browser preview"),
            analysis_source="preprocessing.workspace_target_profile",
        )
    else:
        scope = workspace_scope(
            project_id=project_id, target=target, population_rows=loaded_rows,
            fingerprint=fingerprint, dataset_name=str(source.get("filename") or "Workspace dataset"),
            analysis_source="preprocessing.workspace_target_profile", exact=True,
            linked_dataset_id=source.get("datasetId") if source.get("kind") == "dataset_library" else None,
            linked_version_id=source.get("version") if source.get("kind") == "dataset_library" else None,
        )
        scope["profiledRows"] = loaded_rows
        scope["decisionReady"] = False

    available = [item for item in predictors if item.get("ivStatus") == "available"]
    return {
        "ok": True,
        "analysisScope": scope,
        "scopeIdentity": scope_identity(scope),
        "profileScope": scope["mode"],
        "calculationVersion": CALCULATION_VERSION,
        "generatedAt": scope["resolvedAt"],
        "datasetId": None,
        "datasetVersionId": None,
        "datasetName": scope["datasetName"],
        "artifactChecksum": None,
        "target": target,
        "targetMapping": mapping,
        "quality": quality,
        "problemType": problem_type,
        "predictors": predictors,
        "predictorSummary": {
            "total": len(predictors),
            "evaluated": len(available),
            "unavailable": len([item for item in predictors if str(item.get("ivStatus", "")).startswith("unavailable")]),
            "previewOnly": len([item for item in predictors if item.get("ivStatus") == "preview_only"]),
            "failed": len([item for item in predictors if item.get("ivStatus") == "failed"]),
            "leakageReview": len([item for item in predictors if item.get("role") == "potential_leakage"]),
        },
        "methodology": {
            "sourcePopulation": (
                f"Browser preview ({loaded_rows:,} of {declared_rows:,} declared rows)"
                if is_preview
                else f"Full backend workspace population ({loaded_rows:,} rows)"
            ),
            "targetMapping": f"event = {mapping['eventValue']}, non-event = {mapping['nonEventValue']}",
            "numericBinning": f"Up to {MAX_NUMERIC_BINS} quantile bins with duplicate cut points collapsed.",
            "categoricalGrouping": f"Top {MAX_CATEGORY_BINS} categories retained; Missing always separate.",
            "missingTreatment": "Missing predictor values form their own bin.",
            "smoothing": f"{SMOOTHING_METHOD} with constant {SMOOTHING_CONSTANT}",
            "strengthBands": IV_STRENGTH_BANDS,
            "exact": not is_preview,
            "sampled": is_preview,
        },
        "artifactResolutions": 0,
        "datasetScans": 1,
        "cached": False,
        "durationMs": int((time.perf_counter() - started) * 1000),
    }

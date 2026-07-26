from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time
from typing import Any, Callable

import numpy as np
import pandas as pd

from ..analytics.analysis_scope import scope_identity, workspace_fingerprint, workspace_scope
from ..analytics.target_intelligence_service import (
    assess_class_balance,
    classify_monotonicity,
    wilson_score_interval,
)
from ..core.dataset_store import DATASTORE
from ..preprocessing.feature_profile_service import information_value
from ..preprocessing.quality_profile_service import governed_time_field
from ..analytics.target_intelligence_service import (
    MAX_TOP_CATEGORIES,
    SMALL_GROUP_MIN_EVENTS,
    SMALL_GROUP_MIN_ROWS,
    summarize_target_by_predictor,
)
from .workspace_types import EDAWorkspaceRequest, TargetByPredictorRequest


_DATE_NAME = re.compile(r"(^|_)(date|month|year|period|timestamp|time)($|_)", re.IGNORECASE)
_ID_NAME = re.compile(r"(^|_)(id|key|uuid|account|customer|application|transaction)(_?id)?($|_)", re.IGNORECASE)
_LEAKAGE_NAME = re.compile(r"target|outcome|response|label|post[_ ]|future|approved|declined", re.IGNORECASE)
_SPLIT_NAME = re.compile(r"(^|_)(split|fold|partition|sample_role)($|_)", re.IGNORECASE)

# Part I: two conservative name families, kept separate because they mean
# different things to a reviewer. A target-derived name suggests the column was
# computed FROM the outcome; a post-outcome name suggests it was recorded AFTER
# the outcome was known. Neither is evidence of leakage on its own -- both only
# ever produce a "Review recommended" state.
_TARGET_DERIVED_NAME = re.compile(r"target|label|outcome|response|_y$|^y_|class(_|$)|score|probability|pred", re.IGNORECASE)
_POST_OUTCOME_NAME = re.compile(r"post[_ ]|future|after[_ ]|_final$|closed|settle|resolution|charge.?off|recover|writeoff|write.?off", re.IGNORECASE)

# Leakage assessment states, ordered by strength of claim. `confirmed_leakage`
# is never produced by a rule -- it exists so a reviewer's explicit confirmation
# has somewhere to live.
LEAKAGE_STATES = ("no_signal", "review_recommended", "likely_leakage", "confirmed_leakage")

# A perfect-separation check is only meaningful on a low-cardinality column: a
# near-unique identifier trivially separates every row and would otherwise be
# reported as leakage in every dataset.
MAX_SEPARATION_CARDINALITY = 50
MIN_SEPARATION_ROWS = 100
# Correlation this close to +/-1 with a numeric target is not a predictor.
PERFECT_CORRELATION_THRESHOLD = 0.999


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return _finite(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _problem_type(target: pd.Series, requested: str | None) -> str:
    if requested in {"classification", "regression"}:
        return requested
    unique = int(target.dropna().nunique())
    return "classification" if 1 < unique <= 20 else "regression"


def _event_value(target: pd.Series, requested: Any) -> Any:
    values = list(pd.unique(target.dropna()))
    if requested is not None and any(str(value) == str(requested) for value in values):
        return next(value for value in values if str(value) == str(requested))
    for candidate in values:
        if str(candidate).strip().lower() in {"1", "true", "yes", "event", "bad", "fraud"}:
            return candidate
    if len(values) == 2:
        counts = target.value_counts(dropna=True)
        return counts.index[-1]
    return None


def _numeric_series(series: pd.Series) -> tuple[pd.Series, bool]:
    numeric = pd.to_numeric(series, errors="coerce")
    nonmissing = int(series.notna().sum())
    numeric_rate = float(numeric.notna().sum()) / max(nonmissing, 1)
    return numeric, bool(pd.api.types.is_numeric_dtype(series) or numeric_rate >= 0.8)


def _series_quantiles(series: pd.Series) -> dict[str, float | None]:
    clean = series.dropna()
    if clean.empty:
        return {"q1": None, "median": None, "q3": None}
    values = clean.quantile([0.25, 0.5, 0.75])
    return {
        "q1": _finite(values.loc[0.25]),
        "median": _finite(values.loc[0.5]),
        "q3": _finite(values.loc[0.75]),
    }


def _event_rate(values: pd.Series, event: Any) -> float | None:
    valid = values.dropna()
    if valid.empty or event is None:
        return None
    return float((valid.astype(str) == str(event)).mean())


def _quantile_event_table(feature: pd.Series, target: pd.Series, event: Any, bins: int = 10) -> list[dict[str, Any]]:
    numeric = pd.to_numeric(feature, errors="coerce")
    frame = pd.DataFrame({"value": numeric, "target": target}).dropna(subset=["value", "target"])
    if frame.empty:
        return []
    try:
        frame["bucket"] = pd.qcut(frame["value"].rank(method="first"), q=min(bins, len(frame)), duplicates="drop")
    except ValueError:
        frame["bucket"] = frame["value"].astype(str)
    frame["event"] = frame["target"].astype(str) == str(event)
    grouped = frame.groupby("bucket", observed=True, dropna=False).agg(
        count=("event", "size"),
        events=("event", "sum"),
        minimum=("value", "min"),
        maximum=("value", "max"),
    )
    return [
        {
            "bucket": str(index),
            "count": int(row["count"]),
            "events": int(row["events"]),
            "event_rate": float(row["events"] / row["count"]) if row["count"] else None,
            "minimum": _finite(row["minimum"]),
            "maximum": _finite(row["maximum"]),
        }
        for index, row in grouped.iterrows()
    ]


def _histogram_bins(series: pd.Series, bins: int = 20) -> list[dict[str, Any]]:
    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if numeric.empty:
        return []
    requested_bins = min(max(5, int(bins)), 60)
    counts, edges = np.histogram(numeric.to_numpy(dtype=float), bins=requested_bins)
    return [
        {
            "bin": index + 1,
            "lower": _finite(edges[index]),
            "upper": _finite(edges[index + 1]),
            "count": int(count),
        }
        for index, count in enumerate(counts)
    ]


def _monotonicity(rows: list[dict[str, Any]]) -> str:
    """Delegates to the single shared implementation so the Predictor tab and the
    Target tab can never label the same band table differently."""
    return classify_monotonicity([row.get("event_rate") for row in rows])


class EDAWorkspaceService:
    def __init__(self, max_cache_entries: int = 36) -> None:
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_cache_entries = max_cache_entries

    def _dataset(self, request: EDAWorkspaceRequest) -> tuple[pd.DataFrame, str, pd.Series, str, Any]:
        df = DATASTORE.get_active_df()
        if df is None or df.empty:
            raise ValueError("No full backend dataset is loaded.")
        target = request.target if request.target in df.columns else DATASTORE.target
        if not target or target not in df.columns:
            raise ValueError("Select a valid target before running EDA.")
        y = df[target]
        problem = _problem_type(y, request.problem_type)
        event = _event_value(y, request.event_value) if problem == "classification" else None
        return df, str(target), y, problem, event

    def _workspace_scope(self, df: pd.DataFrame, target: str, project_id: str, analysis_source: str) -> dict[str, Any]:
        """Draft scope for the in-memory population.

        Always `workspace_draft`, even when the frame was loaded FROM a Library
        version: the in-memory frame can have been mutated since it was loaded,
        so it is not the immutable artifact. The originating version is carried
        as a suggestion only, so the UI can offer a one-click governed rerun.
        """
        source = DATASTORE.meta.get("source") if isinstance(DATASTORE.meta.get("source"), dict) else {}
        return workspace_scope(
            project_id=project_id,
            target=target,
            population_rows=int(len(df)),
            fingerprint=self._fingerprint(df, target, source),
            dataset_name=str(source.get("filename") or "Workspace dataset"),
            analysis_source=analysis_source,
            exact=True,
            linked_dataset_id=source.get("datasetId") if source.get("kind") == "dataset_library" else None,
            linked_version_id=source.get("version") if source.get("kind") == "dataset_library" else None,
        )

    def _fingerprint(self, df: pd.DataFrame, target: str, source: dict[str, Any]) -> str:
        """Memoized per (shape, target, source) so a section render never
        re-hashes the frame it just hashed."""
        cache_key = (int(df.shape[0]), int(df.shape[1]), str(target), str(source.get("filename") or ""))
        if getattr(self, "_fingerprint_key", None) == cache_key and getattr(self, "_fingerprint_value", None):
            return str(self._fingerprint_value)
        value = workspace_fingerprint(df, target, source)
        self._fingerprint_key = cache_key
        self._fingerprint_value = value
        return value

    def _key(self, section: str, request: EDAWorkspaceRequest, df: pd.DataFrame, target: str) -> str:
        source = DATASTORE.meta.get("source") if isinstance(DATASTORE.meta.get("source"), dict) else {}
        payload = {
            "section": section,
            # Content identity, so a replacement upload with the same shape can
            # never be served the previous dataset's cached section.
            "workspace_fingerprint": self._fingerprint(df, target, source),
            "dataset_version": DATASTORE.meta.get("dataset_version") or DATASTORE.meta.get("version_id") or "in-memory",
            "shape": list(df.shape),
            "target": target,
            "event_value": request.event_value,
            "problem_type": request.problem_type,
            "selected_features": sorted(request.selected_features),
            "pairwise_features": request.pairwise_features,
            "segment_field": request.segment_field,
            "date_field": request.date_field,
            "histogram_bins": request.histogram_bins,
            "manifest_version": (DATASTORE.meta.get("feature_manifest") or {}).get("manifest_version") if isinstance(DATASTORE.meta.get("feature_manifest"), dict) else None,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def _cached(self, section: str, request: EDAWorkspaceRequest, factory: Callable[..., dict[str, Any]]) -> dict[str, Any]:
        df, target, y, problem, event = self._dataset(request)
        key = self._key(section, request, df, target)
        if key in self._cache:
            cached = self._cache.pop(key)
            self._cache[key] = cached
            return {**cached, "cache_status": "hit"}
        started = time.perf_counter()
        result = factory(df, target, y, problem, event, request)
        scope = self._workspace_scope(df, target, request.project_id, f"eda.workspace.{section}")
        result.update({
            "ok": True,
            "section": section,
            "scope": "full_dataset",
            # Governance scope. `scope` above is the long-standing DATA scope
            # label ("full_dataset" vs a preview); `analysis_scope` is the new
            # GOVERNANCE contract, and the two answer different questions.
            "analysis_scope": scope,
            "scope_identity": scope_identity(scope),
            "row_count": int(len(df)),
            "column_count": int(df.shape[1]),
            "target": target,
            "problem_type": problem,
            "event_value": _json_value(event),
            "dataset_version": str(DATASTORE.meta.get("dataset_version") or DATASTORE.meta.get("version_id") or "in-memory"),
            "generated_at": _now(),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "cache_status": "miss",
            "requested_histogram_bins": int(request.histogram_bins),
        })
        self._cache[key] = result
        while len(self._cache) > self._max_cache_entries:
            self._cache.popitem(last=False)
        return result

    def section(self, section: str, request: EDAWorkspaceRequest) -> dict[str, Any]:
        factories: dict[str, Callable[..., dict[str, Any]]] = {
            "overview": self._overview,
            "target": self._target,
            "predictors": self._predictors,
            "relationships": self._relationships,
            "stability": self._stability,
            "findings": self._findings,
        }
        if section not in factories:
            raise ValueError(f"Unsupported EDA section '{section}'.")
        return self._cached(section, request, factories[section])

    def _overview(self, df, target, y, problem, event, request) -> dict[str, Any]:
        duplicate_rows = int(df.duplicated().sum())
        feature_columns = [column for column in df.columns if column != target]
        numeric_columns: list[str] = []
        categorical_columns: list[str] = []
        constants: list[str] = []
        identifier_candidates: list[dict[str, Any]] = []
        leakage_candidates: list[dict[str, Any]] = []
        invalid_numeric: list[dict[str, Any]] = []
        for column in feature_columns:
            series = df[column]
            numeric, is_numeric = _numeric_series(series)
            (numeric_columns if is_numeric else categorical_columns).append(str(column))
            distinct = int(series.nunique(dropna=True))
            if distinct <= 1:
                constants.append(str(column))
            uniqueness = distinct / max(int(series.notna().sum()), 1)
            if _ID_NAME.search(str(column)) or (uniqueness >= 0.98 and distinct > 20):
                identifier_candidates.append({"feature": str(column), "distinct_count": distinct, "uniqueness": uniqueness})
            if _LEAKAGE_NAME.search(str(column)) or _SPLIT_NAME.search(str(column)):
                leakage_candidates.append({"feature": str(column), "reason": "Name indicates a target, post-outcome, or split relationship."})
            if not is_numeric and numeric.notna().any():
                failures = int(series.notna().sum() - numeric.notna().sum())
                if failures:
                    invalid_numeric.append({"feature": str(column), "unparsed_count": failures})
        missing_cells = int(df.isna().sum().sum())
        target_payload = self._classification_target(y, event) if problem == "classification" else self._regression_target(y, request.histogram_bins)
        return {
            "headline": {
                "rows": int(len(df)),
                "predictors": len(feature_columns),
                "numeric_predictors": len(numeric_columns),
                "categorical_predictors": len(categorical_columns),
                "missing_cells": missing_cells,
                "missing_cell_rate": missing_cells / max(int(df.shape[0] * df.shape[1]), 1),
                "duplicate_rows": duplicate_rows,
            },
            "target_profile": target_payload,
            "data_integrity": {
                "duplicate_rows": duplicate_rows,
                "constant_columns": constants,
                "identifier_candidates": identifier_candidates[:50],
                "leakage_candidates": leakage_candidates[:50],
                "invalid_numeric_parsing": invalid_numeric[:50],
                "unsupported_types": [str(column) for column in df.columns if str(df[column].dtype) in {"complex64", "complex128"}],
            },
            "available_fields": {
                "numeric": numeric_columns,
                "categorical": categorical_columns,
                "date_candidates": [str(column) for column in df.columns if _DATE_NAME.search(str(column))],
                "segment_candidates": [str(column) for column in categorical_columns if 1 < df[column].nunique(dropna=True) <= 100],
            },
        }

    def _classification_target(self, y: pd.Series, event: Any) -> dict[str, Any]:
        valid = y.dropna()
        counts = valid.astype(str).value_counts()
        event_count = int((valid.astype(str) == str(event)).sum()) if event is not None else 0
        non_event_count = int(len(valid) - event_count)
        event_rate = event_count / len(valid) if len(valid) else None
        unexpected = [str(value) for value in pd.unique(valid) if event is not None and len(counts) <= 2 and str(value) not in {str(event), str(next((item for item in pd.unique(valid) if str(item) != str(event)), ""))}]
        min_events_for_five_fold = event_count >= 10 and non_event_count >= 10
        metrics = ["PR-AUC", "Recall", "Lift", "KS", "Calibration"] if event_rate is not None and event_rate < 0.05 else ["ROC-AUC", "PR-AUC", "F1", "Calibration"]
        return {
            "valid_count": int(len(valid)),
            "missing_count": int(y.isna().sum()),
            "class_count": int(valid.nunique()),
            "class_distribution": [{"value": str(index), "count": int(value), "rate": float(value / len(valid))} for index, value in counts.items()],
            "positive_class": _json_value(event),
            "negative_class": _json_value(next((value for value in pd.unique(valid) if str(value) != str(event)), None)),
            "event_count": event_count,
            "non_event_count": non_event_count,
            "event_rate": event_rate,
            "non_event_rate": 1 - event_rate if event_rate is not None else None,
            "event_to_non_event_ratio": event_count / non_event_count if non_event_count else None,
            "unexpected_values": unexpected,
            "rare_event": bool(event_rate is not None and event_rate < 0.01),
            "split_sufficiency": event_count >= 2 and non_event_count >= 2,
            "five_fold_sufficiency": min_events_for_five_fold,
            "recommended_metrics": metrics,
        }

    def _regression_target(self, y: pd.Series, histogram_bins: int = 20) -> dict[str, Any]:
        numeric = pd.to_numeric(y, errors="coerce")
        clean = numeric.dropna()
        quantiles = _series_quantiles(clean)
        q1, q3 = quantiles["q1"], quantiles["q3"]
        iqr = (q3 - q1) if q1 is not None and q3 is not None else None
        outlier_rate = float(((clean < q1 - 1.5 * iqr) | (clean > q3 + 1.5 * iqr)).mean()) if iqr is not None else None
        return {
            "valid_count": int(len(clean)),
            "missing_count": int(y.isna().sum() + (y.notna() & numeric.isna()).sum()),
            "mean": _finite(clean.mean()),
            "standard_deviation": _finite(clean.std()),
            "minimum": _finite(clean.min()),
            **quantiles,
            "maximum": _finite(clean.max()),
            "skewness": _finite(clean.skew()),
            "kurtosis": _finite(clean.kurt()),
            "zero_proportion": float((clean == 0).mean()) if len(clean) else None,
            "negative_proportion": float((clean < 0).mean()) if len(clean) else None,
            "extreme_value_prevalence": outlier_rate,
            "histogram": _histogram_bins(clean, bins=histogram_bins),
        }

    def _target(self, df, target, y, problem, event, request) -> dict[str, Any]:
        profile = self._classification_target(y, event) if problem == "classification" else self._regression_target(y, request.histogram_bins)

        # Part H: a time field is only offered when it is genuinely a time field.
        # `request.date_field` being present in the frame is not sufficient --
        # the governed rule must also accept it, so a numeric "Time" column
        # holding elapsed seconds can never be charted as a calendar axis.
        governed_time_fields = self._governed_time_fields(df)
        governed_time_names = {item["field"] for item in governed_time_fields}
        requested_date = request.date_field if request.date_field in df.columns else None
        date_field = requested_date if requested_date in governed_time_names else None
        rejected_date_field = (
            {"field": requested_date, "reason": "This field is not a governed time field. ATLAS does not infer dates from numeric or non-date-formatted values."}
            if requested_date and requested_date not in governed_time_names
            else None
        )

        segment_field = request.segment_field if request.segment_field in df.columns else None
        segment_rows = self._group_target(df, target, event, segment_field, False) if segment_field else []
        if segment_rows:
            population_rate = profile.get("event_rate") if problem == "classification" else None
            for row in segment_rows:
                row["population_event_rate"] = population_rate
                row["difference_from_population"] = (
                    row["event_rate"] - population_rate if population_rate is not None else None
                )
                row["small_segment"] = row["count"] < 30 or row["events"] < 5
            missing_row = next((row for row in segment_rows if row["group"] == "__MISSING__"), None)
            segment_missing_count = missing_row["count"] if missing_row else 0
        else:
            segment_missing_count = 0

        time_rows = (
            self._group_target(df, target, event, date_field, True)
            if problem == "classification" and date_field
            else []
        )
        return {
            "profile": profile,
            "identity": self._target_identity(df, target, y, problem, event, profile),
            "full_population_assessment": self._full_population_assessment(target, problem, profile),
            "target_quality": self._target_quality(df, target, y, problem, event, profile),
            "governed_time_fields": governed_time_fields,
            "rejected_time_field": rejected_date_field,
            "event_rate_by_time": time_rows,
            "time_stability": self._time_stability(time_rows, df, date_field),
            "target_by_segment": segment_rows,
            "segment_missing_count": segment_missing_count,
            "date_field": date_field,
            "segment_field": segment_field,
        }

    def target_by_predictor(self, request: TargetByPredictorRequest) -> dict[str, Any]:
        """On-demand grouped event rate over the full in-memory population.

        The pandas twin of `compute_target_by_predictor`: same request shape,
        same bounded response shape, same summary function. It exists so the
        Target tab's Run Analysis control is usable for a project whose dataset
        is loaded in the backend but not registered as an immutable Dataset
        Library version -- rather than being a permanently disabled button.

        Only grouped counts are returned. The predictor column and the target
        column never leave the server.
        """
        started = time.perf_counter()
        base = EDAWorkspaceRequest(
            project_id=request.project_id, target=request.target,
            event_value=request.event_value, problem_type=request.problem_type,
        )
        df, target, y, problem, event = self._dataset(base)

        predictor = request.predictor
        if predictor not in df.columns:
            raise ValueError(f"'{predictor}' is not a column in the loaded dataset.")
        if predictor == target:
            raise ValueError("The target cannot be analyzed against itself.")
        if problem != "classification" or event is None:
            raise ValueError("Target-by-predictor event rates apply to classification targets with a resolved event value.")
        if request.analysis_type not in {"numeric_quantile", "categorical"}:
            raise ValueError("Unsupported analysis type. Use 'numeric_quantile' or 'categorical'.")

        frame = pd.DataFrame({"value": df[predictor], "event": (y.astype(str) == str(event)).astype(int)})
        frame = frame[y.notna()]
        analyzed_rows = int(len(frame))

        rows: list[dict[str, Any]] = []
        missing_group: dict[str, Any] | None = None
        other_group: dict[str, Any] | None = None
        extras: dict[str, Any] = {}

        def _entry(label_key: str, label: str, subset: pd.DataFrame, **fields: Any) -> dict[str, Any]:
            population = int(len(subset))
            events = int(subset["event"].sum())
            return {
                label_key: label,
                "population": population,
                "eventCount": events,
                "eventRate": (events / population) if population else None,
                "smallGroup": population < SMALL_GROUP_MIN_ROWS or events < SMALL_GROUP_MIN_EVENTS,
                **fields,
            }

        if request.analysis_type == "numeric_quantile":
            numeric = pd.to_numeric(frame["value"], errors="coerce")
            present = frame[numeric.notna()].assign(numeric=numeric[numeric.notna()])
            absent = frame[numeric.isna()]
            if present.empty:
                raise ValueError(f"'{predictor}' has no numeric values to band.")
            bands = max(2, min(int(request.bands), 20))
            # Rank-then-qcut mirrors the NTILE the DuckDB path uses: equal-population
            # bands even when a value is heavily repeated.
            buckets = pd.qcut(present["numeric"].rank(method="first"), q=min(bands, len(present)), labels=False, duplicates="drop")
            for index in sorted(pd.unique(buckets.dropna())):
                subset = present[buckets == index]
                rows.append(_entry(
                    "label", f"Q{int(index) + 1}", subset,
                    band=int(index) + 1,
                    lowerBound=_finite(subset["numeric"].min()),
                    upperBound=_finite(subset["numeric"].max()),
                    meanValue=_finite(subset["numeric"].mean()),
                    isMissingGroup=False,
                ))
            if len(absent):
                missing_group = _entry("label", "Missing", absent, band=0, lowerBound=None, upperBound=None, meanValue=None, isMissingGroup=True)
            label_key = "label"
            extras = {"requestedBands": bands, "returnedBands": len(rows)}
        else:
            values = frame["value"].astype("object")
            is_missing = values.isna()
            distinct = int(values[~is_missing].astype(str).nunique())
            top_n = max(2, min(int(request.top_categories), MAX_TOP_CATEGORIES))
            present = frame[~is_missing].assign(category=values[~is_missing].astype(str))
            ordered = present["category"].value_counts()
            keep = list(ordered.head(top_n).index)
            for category in keep:
                rows.append(_entry("category", str(category), present[present["category"] == category], isMissingGroup=False, isOtherGroup=False))
            collapsed = present[~present["category"].isin(keep)]
            if len(collapsed):
                other_group = _entry(
                    "category", "Other", collapsed,
                    isMissingGroup=False, isOtherGroup=True,
                    collapsedCategoryCount=int(collapsed["category"].nunique()),
                )
            if int(is_missing.sum()):
                missing_group = _entry("category", "Missing", frame[is_missing], isMissingGroup=True, isOtherGroup=False)
            label_key = "category"
            extras = {
                "requestedTopCategories": top_n,
                "returnedCategories": len(rows),
                "distinctCategoryCount": distinct,
                "topNApplied": bool(other_group),
                "rareCategoryWarning": bool(distinct > top_n or any(row["smallGroup"] for row in rows)),
            }

        if not request.include_missing:
            missing_group = None

        total_population = sum(row["population"] for row in rows) + sum(
            int(extra["population"]) for extra in (missing_group, other_group) if extra
        )
        total_events = sum(row["eventCount"] for row in rows) + sum(
            int(extra["eventCount"]) for extra in (missing_group, other_group) if extra
        )
        population_event_rate = (total_events / total_population) if total_population else None

        scope = self._workspace_scope(df, str(target), request.project_id, "eda.target_by_predictor")
        return {
            "ok": True,
            "supported": bool(rows),
            "source": "eda_full_population",
            "analysisScope": scope,
            "scopeIdentity": scope_identity(scope),
            # Never invented. A draft analysis has no governed dataset identity,
            # so these stay null rather than echoing an in-memory label that
            # would read like a registered version.
            "datasetId": None,
            "versionId": None,
            "target": str(target),
            "predictor": str(predictor),
            "analysisType": request.analysis_type,
            "eventValue": str(event),
            "includeMissing": bool(request.include_missing),
            "rows": rows,
            "missingGroup": missing_group,
            "otherGroup": other_group,
            "populationEventRate": population_event_rate,
            "analyzedRowCount": total_population,
            "analyzedEventCount": total_events,
            "summary": summarize_target_by_predictor(
                rows, label_key=label_key, missing_group=missing_group, other_group=other_group,
                population_event_rate=population_event_rate, analysis_type=request.analysis_type,
            ),
            "engine": "pandas",
            "resolution": "exact",
            "scope": "full_dataset",
            "sourceRowCount": analyzed_rows,
            "cached": False,
            "durationMs": int((time.perf_counter() - started) * 1000),
            **extras,
        }

    def _full_population_assessment(self, target, problem, profile) -> dict[str, Any] | None:
        """Class balance, imbalance tier, and event-rate interval over the full
        backend population.

        This exists for the case where the project has no registered Dataset
        Library version, so `/api/analytics/target-assessment` has no immutable
        (dataset, version) to aggregate. The backend still holds the complete
        population here, so the Target tab must show exact figures rather than
        "Not available" -- and it must show the SAME figures, which is why this
        calls the shared `assess_class_balance` / `wilson_score_interval`
        functions instead of recomputing anything locally.
        """
        if problem != "classification":
            return None
        events = int(profile.get("event_count") or 0)
        non_events = int(profile.get("non_event_count") or 0)
        total = events + non_events
        if total <= 0:
            return None
        return {
            "supported": True,
            "source": "eda_full_population",
            "classBalance": {
                "target": str(target),
                "eventValue": None if profile.get("positive_class") is None else str(profile.get("positive_class")),
                "nonEventValue": None if profile.get("negative_class") is None else str(profile.get("negative_class")),
                "eventCount": events,
                "nonEventCount": non_events,
                "eventRate": events / total,
                "nonEventRate": non_events / total,
                "eventToNonEventRatio": (events / non_events) if non_events else None,
                "imbalanceRatio": (non_events / events) if events else None,
                "missingTargetCount": int(profile.get("missing_count") or 0),
                "totalModelingPopulation": total,
                "classCount": int(profile.get("class_count") or 0),
                "resolution": "exact",
            },
            "imbalance": assess_class_balance(events, non_events),
            "confidenceInterval": wilson_score_interval(events, total, 0.95),
        }

    def _governed_time_fields(self, df) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        for column in df.columns:
            accepted = governed_time_field(str(column), df[column])
            if accepted:
                fields.append({
                    "field": str(column),
                    "minimum": accepted.get("min"),
                    "maximum": accepted.get("max"),
                    "basis": "datetime dtype" if pd.api.types.is_datetime64_any_dtype(df[column]) else "date-named text parsed at 80 percent or higher",
                })
        return fields

    def _time_stability(self, rows: list[dict[str, Any]], df, date_field: str | None) -> dict[str, Any] | None:
        """Material prevalence movement across observed periods.

        'Material' is defined conservatively: the widest period rate must be at
        least twice the narrowest AND differ by at least half a percentage point
        of the pooled rate, so ordinary rare-event noise across small monthly
        cells is not reported as a shift.
        """
        if not rows or not date_field:
            return None
        rates = [row["event_rate"] for row in rows if row.get("event_rate") is not None]
        if len(rates) < 2:
            return None
        pooled_events = sum(row["events"] for row in rows)
        pooled_count = sum(row["count"] for row in rows)
        pooled_rate = pooled_events / pooled_count if pooled_count else None
        lowest, highest = min(rates), max(rates)
        material = bool(
            pooled_rate
            and lowest > 0
            and (highest / lowest) >= 2.0
            and (highest - lowest) >= max(0.5 * pooled_rate, 0.0005)
        )
        return {
            "period_count": len(rows),
            "pooled_event_rate": pooled_rate,
            "lowest_period_event_rate": lowest,
            "highest_period_event_rate": highest,
            "material_shift": material,
            "missing_time_values": int(df[date_field].isna().sum()) if date_field in df.columns else 0,
            "rule": "A material shift requires the highest period rate to be at least twice the lowest and to differ by at least half the pooled rate.",
        }

    def _target_identity(self, df, target, y, problem, event, profile) -> dict[str, Any]:
        return {
            "target": str(target),
            "data_type": str(y.dtype),
            "problem_type": problem,
            "positive_value": _json_value(event) if problem == "classification" else None,
            "negative_value": profile.get("negative_class") if problem == "classification" else None,
            "missing_target_count": int(y.isna().sum()),
            "population_row_count": int(len(df)),
            "modeling_population_row_count": int(y.notna().sum()),
            "distinct_value_count": int(y.dropna().nunique()),
        }

    def _target_quality(self, df, target, y, problem, event, profile) -> dict[str, Any]:
        """Part I: focused target measurability review.

        Reuses the same conservative name families and the same duplicate
        detection as the rest of ATLAS; it does not introduce a second leakage
        engine. Every automated conclusion stops at 'Review recommended' --
        'Likely leakage' requires a structural rule (perfect separation or a
        near-perfect correlation), and 'Confirmed leakage' is only ever set by a
        reviewer.
        """
        valid = y.dropna()
        missing_count = int(y.isna().sum())

        invalid_values: list[dict[str, Any]] = []
        unexpected_values: list[str] = []
        if problem == "classification":
            governed = {str(event), str(profile.get("negative_class"))} if event is not None else set()
            counts = valid.astype(str).value_counts()
            if governed and len(counts) > 2:
                unexpected_values = [str(index) for index in counts.index if str(index) not in governed][:20]
            # A blank-but-not-null target value is neither a class nor a missing
            # value; it is an invalid record that would silently join a class.
            blanks = int((valid.astype(str).str.strip() == "").sum())
            if blanks:
                invalid_values.append({"reason": "Blank (whitespace-only) target value", "count": blanks})
        else:
            numeric = pd.to_numeric(valid, errors="coerce")
            unparsed = int(numeric.isna().sum())
            if unparsed:
                invalid_values.append({"reason": "Target value could not be parsed as a number", "count": unparsed})
            non_finite = int(np.isinf(numeric.dropna().to_numpy(dtype=float)).sum()) if len(numeric.dropna()) else 0
            if non_finite:
                invalid_values.append({"reason": "Non-finite target value", "count": non_finite})

        duplicate_rows = int(df.duplicated().sum())
        # Duplicate records that carry a target are the ones that actually bias a
        # rate: a duplicated row with a missing target contributes to neither
        # numerator nor denominator.
        duplicate_mask = df.duplicated(keep=False) & y.notna()
        duplicate_target_rows = int(df[duplicate_mask].duplicated().sum())

        candidates = self._leakage_candidates(df, target, y, problem, event)

        return {
            "missing_target_count": missing_count,
            "missing_target_rate": missing_count / max(len(y), 1),
            "invalid_target_values": invalid_values,
            "unexpected_target_values": unexpected_values,
            "target_cardinality": int(valid.nunique()),
            "duplicate_rows": duplicate_rows,
            "duplicate_target_bearing_rows": duplicate_target_rows,
            "target_derived_candidates": [item for item in candidates if item["family"] == "target_derived"],
            "post_outcome_candidates": [item for item in candidates if item["family"] == "post_outcome"],
            "perfect_relationship_candidates": [item for item in candidates if item["family"] == "perfect_relationship"],
            "leakage_states": list(LEAKAGE_STATES),
            "assessment_rule": (
                "Name-based matches are reported as 'Review recommended' only. 'Likely leakage' requires a structural "
                "rule: a low-cardinality field that perfectly separates the target, or a numeric field correlated with "
                "the target at 0.999 or above. High IV, high correlation, and differing event rates alone are never "
                "sufficient. 'Confirmed leakage' is set by a reviewer, never by ATLAS."
            ),
        }

    def _leakage_candidates(self, df, target, y, problem, event) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        numeric_target = pd.to_numeric(y, errors="coerce") if problem == "regression" else (y.astype(str) == str(event)).astype(float)
        row_count = int(len(df))

        for column in df.columns:
            if str(column) == str(target):
                continue
            name = str(column)
            series = df[column]

            if _TARGET_DERIVED_NAME.search(name):
                candidates.append({
                    "feature": name, "family": "target_derived", "state": "review_recommended",
                    "reason": "The field name suggests it may be derived from the target or from a model output.",
                })
            if _POST_OUTCOME_NAME.search(name):
                candidates.append({
                    "feature": name, "family": "post_outcome", "state": "review_recommended",
                    "reason": "The field name suggests information recorded after the outcome was known.",
                })

            if row_count < MIN_SEPARATION_ROWS:
                continue
            distinct = int(series.nunique(dropna=True))
            if 2 <= distinct <= MAX_SEPARATION_CARDINALITY and problem == "classification":
                frame = pd.DataFrame({"value": series.astype(str), "target": y.astype(str)}).dropna()
                if not frame.empty and int(frame.groupby("value")["target"].nunique().max()) == 1:
                    candidates.append({
                        "feature": name, "family": "perfect_relationship", "state": "likely_leakage",
                        "reason": f"Every one of the {distinct} distinct values maps to exactly one target class. A predictor cannot separate an outcome perfectly unless it encodes it.",
                    })
                    continue
            numeric, is_numeric = _numeric_series(series)
            if is_numeric:
                pairs = pd.DataFrame({"x": numeric, "y": numeric_target}).dropna()
                if len(pairs) >= 3:
                    correlation = _finite(pairs["x"].corr(pairs["y"]))
                    if correlation is not None and abs(correlation) >= PERFECT_CORRELATION_THRESHOLD:
                        candidates.append({
                            "feature": name, "family": "perfect_relationship", "state": "likely_leakage",
                            "reason": f"Correlation with the target is {correlation:.4f}, which is not attainable for a legitimate predictor.",
                        })
        return candidates[:100]

    def _group_target(self, df, target, event, field, as_date: bool) -> list[dict[str, Any]]:
        if not field:
            return []
        frame = df[[field, target]].copy()
        if as_date:
            parsed = pd.to_datetime(frame[field], errors="coerce")
            if parsed.notna().mean() < 0.8:
                return []
            frame["group"] = parsed.dt.to_period("M").astype(str)
        else:
            frame["group"] = frame[field].astype("object").where(frame[field].notna(), "__MISSING__").astype(str)
            keep = set(frame["group"].value_counts().head(50).index)
            frame["group"] = frame["group"].where(frame["group"].isin(keep), "__OTHER__")
        frame = frame.dropna(subset=[target])
        frame["event"] = frame[target].astype(str) == str(event)
        grouped = frame.groupby("group", dropna=False)["event"].agg(["size", "sum"])
        return [{"group": str(index), "count": int(row["size"]), "events": int(row["sum"]), "event_rate": float(row["sum"] / row["size"])} for index, row in grouped.iterrows()]

    def _predictors(self, df, target, y, problem, event, request) -> dict[str, Any]:
        requested = [column for column in request.selected_features if column in df.columns and column != target]
        columns = requested or [str(column) for column in df.columns if column != target]
        numeric_profiles: list[dict[str, Any]] = []
        categorical_profiles: list[dict[str, Any]] = []
        missing_profiles: list[dict[str, Any]] = []
        for column in columns:
            series = df[column]
            numeric, is_numeric = _numeric_series(series)
            missing_count = int(series.isna().sum())
            missing_rate = missing_count / max(len(series), 1)
            present_event_rate = _event_rate(y[series.notna()], event) if problem == "classification" else None
            missing_event_rate = _event_rate(y[series.isna()], event) if problem == "classification" else None
            missing_profiles.append({
                "feature": column,
                "missing_count": missing_count,
                "missing_rate": missing_rate,
                "present_event_rate": present_event_rate,
                "missing_event_rate": missing_event_rate,
                "informative_missingness": bool(present_event_rate is not None and missing_event_rate is not None and abs(present_event_rate - missing_event_rate) >= 0.02),
            })
            if is_numeric:
                clean = numeric.dropna()
                histogram = _histogram_bins(numeric, bins=request.histogram_bins)
                quantiles = _series_quantiles(clean)
                q1, q3 = quantiles["q1"], quantiles["q3"]
                iqr = (q3 - q1) if q1 is not None and q3 is not None else None
                outlier_rate = float(((clean < q1 - 1.5 * iqr) | (clean > q3 + 1.5 * iqr)).mean()) if iqr is not None and len(clean) else None
                association = None
                iv = None
                if problem == "classification":
                    try:
                        iv, _ = information_value(series, y, event)
                    except ValueError:
                        iv = None
                else:
                    pairs = pd.DataFrame({"x": numeric, "y": pd.to_numeric(y, errors="coerce")}).dropna()
                    association = _finite(pairs["x"].corr(pairs["y"])) if len(pairs) >= 3 else None
                event_bins = _quantile_event_table(series, y, event) if problem == "classification" else []
                numeric_profiles.append({
                    "feature": column,
                    "count": int(len(clean)),
                    "missing_count": missing_count,
                    "missing_rate": missing_rate,
                    "mean": _finite(clean.mean()),
                    "standard_deviation": _finite(clean.std()),
                    "minimum": _finite(clean.min()),
                    **quantiles,
                    "maximum": _finite(clean.max()),
                    "skewness": _finite(clean.skew()),
                    "kurtosis": _finite(clean.kurt()),
                    "distinct_count": int(series.nunique(dropna=True)),
                    "zero_rate": float((clean == 0).mean()) if len(clean) else None,
                    "negative_rate": float((clean < 0).mean()) if len(clean) else None,
                    "outlier_rate": outlier_rate,
                    "correlation_with_target": association,
                    "iv": iv,
                    "event_rate_by_quantile": event_bins,
                    "histogram": histogram,
                    "histogram_bin_count": len(histogram),
                    "monotonicity": _monotonicity(event_bins) if event_bins else None,
                    "present_event_rate": present_event_rate,
                    "missing_event_rate": missing_event_rate,
                })
            else:
                values = series.astype("object").where(series.notna(), "__MISSING__").astype(str)
                counts = values.value_counts()
                top_levels = []
                for level, count in counts.head(20).items():
                    mask = values == level
                    top_levels.append({
                        "level": str(level),
                        "count": int(count),
                        "rate": float(count / len(values)),
                        "event_rate": _event_rate(y[mask], event) if problem == "classification" else None,
                    })
                iv = None
                if problem == "classification":
                    try:
                        iv, _ = information_value(series, y, event)
                    except ValueError:
                        iv = None
                cardinality = int(series.nunique(dropna=True))
                rare_levels = int((counts < max(5, int(len(values) * 0.001))).sum())
                stripped_unique = int(series.dropna().astype(str).str.strip().str.lower().nunique())
                categorical_profiles.append({
                    "feature": column,
                    "count": int(series.notna().sum()),
                    "missing_count": missing_count,
                    "missing_rate": missing_rate,
                    "cardinality": cardinality,
                    "rare_level_count": rare_levels,
                    "top_levels": top_levels,
                    "iv": iv,
                    "high_cardinality": bool(cardinality > 50 or cardinality / max(len(values), 1) > 0.2),
                    "sparse_levels": bool(rare_levels > 0),
                    "inconsistent_labels": bool(stripped_unique < cardinality),
                    "suggested_grouping": "Review rare levels for grouping" if rare_levels else "No grouping indicated",
                    "present_event_rate": present_event_rate,
                    "missing_event_rate": missing_event_rate,
                })
        numeric_profiles.sort(key=lambda row: abs(float(row.get("iv") or row.get("correlation_with_target") or 0)), reverse=True)
        categorical_profiles.sort(key=lambda row: abs(float(row.get("iv") or 0)), reverse=True)
        missing_profiles.sort(key=lambda row: row["missing_rate"], reverse=True)
        return {
            "numeric": numeric_profiles,
            "categorical": categorical_profiles,
            "missingness": missing_profiles,
            "profiled_features": len(columns),
        }

    def _relationships(self, df, target, y, problem, event, request) -> dict[str, Any]:
        candidate_columns = request.selected_features or [str(column) for column in df.columns if column != target]
        numeric_data: dict[str, pd.Series] = {}
        for column in candidate_columns:
            if column not in df.columns or column == target:
                continue
            numeric, is_numeric = _numeric_series(df[column])
            if is_numeric and numeric.notna().sum() >= 3:
                numeric_data[column] = numeric
        numeric_df = pd.DataFrame(numeric_data)
        correlation = numeric_df.corr() if numeric_df.shape[1] >= 2 else pd.DataFrame()
        strong_pairs: list[dict[str, Any]] = []
        if not correlation.empty:
            for left_index, left in enumerate(correlation.columns):
                for right in correlation.columns[left_index + 1:]:
                    value = _finite(correlation.loc[left, right])
                    if value is not None and abs(value) >= 0.7:
                        strong_pairs.append({"feature_a": str(left), "feature_b": str(right), "correlation": value})
            strong_pairs.sort(key=lambda row: abs(row["correlation"]), reverse=True)
        vif_rows = self._vif(numeric_df)
        pairwise = [column for column in request.pairwise_features if column in numeric_df.columns][:6]
        rendered = pd.DataFrame()
        if pairwise:
            sample_frame = pd.concat([numeric_df[pairwise], y.rename("__target__")], axis=1).dropna(subset=pairwise)
            if problem == "classification" and event is not None and "__target__" in sample_frame.columns:
                events = sample_frame[sample_frame["__target__"].astype(str) == str(event)]
                non_events = sample_frame[sample_frame["__target__"].astype(str) != str(event)]
                event_limit = min(len(events), max(25, request.rendered_sample_limit // 3))
                non_event_limit = max(0, request.rendered_sample_limit - event_limit)
                rendered = pd.concat([events.head(event_limit), non_events.head(non_event_limit)], axis=0).head(request.rendered_sample_limit)
            else:
                rendered = sample_frame.head(request.rendered_sample_limit)
            rendered["__event__"] = rendered["__target__"].astype(str) == str(event) if problem == "classification" and event is not None else False
        return {
            "correlation_columns": [str(column) for column in correlation.columns],
            "correlation_matrix": [[_finite(value) for value in row] for row in correlation.to_numpy()] if not correlation.empty else [],
            "strong_pairs": strong_pairs[:100],
            "vif": vif_rows,
            "pairwise_features": pairwise,
            "pairwise_sample": [{str(key): _json_value(value) for key, value in row.items()} for row in rendered.to_dict(orient="records")],
            "pairwise_scope": "rendered_sample" if pairwise else "unavailable",
            "pairwise_rows": int(len(rendered)),
            "pairwise_event_rows": int(rendered["__event__"].sum()) if "__event__" in rendered.columns else 0,
            "pairwise_limit": 6,
        }

    def _vif(self, numeric_df: pd.DataFrame) -> list[dict[str, Any]]:
        if numeric_df.shape[1] < 2:
            return []
        work = numeric_df.replace([np.inf, -np.inf], np.nan).dropna()
        if len(work) > 20000:
            work = work.sample(20000, random_state=42)
        variances = work.var().replace(0, np.nan).dropna().sort_values(ascending=False)
        work = work[[column for column in variances.index[:25] if column in work.columns]]
        if work.shape[1] < 2 or len(work) < 5:
            return []
        values = (work - work.mean()) / work.std(ddof=0).replace(0, 1)
        rows: list[dict[str, Any]] = []
        for column in values.columns:
            y = values[column].to_numpy()
            X = values.drop(columns=[column]).to_numpy()
            X = np.column_stack([np.ones(len(X)), X])
            try:
                fitted = X @ np.linalg.lstsq(X, y, rcond=None)[0]
                denominator = float(((y - y.mean()) ** 2).sum())
                r_squared = 1 - float(((y - fitted) ** 2).sum()) / denominator if denominator > 0 else 1
                vif = 1 / max(1 - r_squared, 1e-9)
            except np.linalg.LinAlgError:
                vif = float("inf")
            rows.append({"feature": str(column), "vif": _finite(vif), "status": "high" if vif >= 10 else "review" if vif >= 5 else "acceptable"})
        return sorted(rows, key=lambda row: float(row["vif"] or 1e12), reverse=True)

    def _stability(self, df, target, y, problem, event, request) -> dict[str, Any]:
        date_field = request.date_field if request.date_field in df.columns else None
        segment_field = request.segment_field if request.segment_field in df.columns else None
        time_rows = self._group_target(df, target, event, date_field, True) if problem == "classification" and date_field else []
        segment_rows = self._group_target(df, target, event, segment_field, False) if problem == "classification" and segment_field else []
        if segment_field and segment_rows:
            total = sum(row["count"] for row in segment_rows)
            for row in segment_rows:
                row["population_rate"] = row["count"] / max(total, 1)
                row["small_sample"] = row["count"] < 30 or row["events"] < 5
        return {
            "date_field": date_field,
            "segment_field": segment_field,
            "time_profile": time_rows,
            "segment_profile": segment_rows,
            "time_scope": "full_dataset" if time_rows else "unavailable",
            "segment_scope": "full_dataset" if segment_rows else "unavailable",
            "out_of_time_suggestion": self._oot_suggestion(time_rows),
        }

    def _oot_suggestion(self, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if len(rows) < 6:
            return None
        cutoff = max(1, int(len(rows) * 0.8))
        return {
            "reference_periods": [row["group"] for row in rows[:cutoff]],
            "comparison_periods": [row["group"] for row in rows[cutoff:]],
            "rationale": "The latest 20 percent of observed periods can be reserved as an out-of-time comparison after reviewer confirmation.",
        }

    def _findings(self, df, target, y, problem, event, request) -> dict[str, Any]:
        overview = self._overview(df, target, y, problem, event, request)
        target_profile = overview["target_profile"]
        findings: list[dict[str, Any]] = []
        if problem == "classification" and target_profile.get("rare_event"):
            findings.append({"category": "Rare event", "severity": "warning", "finding": "The observed event rate is below 1 percent.", "recommended_action": "Use stratified validation and ranking, lift, calibration, and threshold metrics instead of accuracy alone."})
        if overview["data_integrity"]["duplicate_rows"]:
            findings.append({"category": "Data integrity", "severity": "warning", "finding": f"{overview['data_integrity']['duplicate_rows']:,} duplicate rows were detected.", "recommended_action": "Confirm whether duplicate records represent repeated observations or ingestion duplication."})
        if overview["data_integrity"]["leakage_candidates"]:
            findings.append({"category": "Leakage", "severity": "warning", "finding": f"{len(overview['data_integrity']['leakage_candidates'])} fields have names associated with targets, outcomes, or split metadata.", "recommended_action": "Review the evidence before excluding any field from the governed predictor set."})
        if overview["headline"]["missing_cells"]:
            findings.append({"category": "Missingness", "severity": "review", "finding": f"{overview['headline']['missing_cells']:,} missing cells are present.", "recommended_action": "Review informative missingness and select treatment on the Missing Values step."})
        if not findings:
            findings.append({"category": "Readiness", "severity": "info", "finding": "No headline target, duplicate, leakage-name, or missingness condition requires immediate escalation.", "recommended_action": "Review predictor, relationship, and stability tabs before completing EDA."})
        return {
            "findings": findings,
            "carry_forward": {
                "outliers": [item for item in findings if item["category"] in {"Data integrity"}],
                "missing_values": [item for item in findings if item["category"] == "Missingness"],
                "feature_engineering": [item for item in findings if item["category"] == "Leakage"],
                "balance_split": [item for item in findings if item["category"] == "Rare event"],
            },
        }


eda_workspace_service = EDAWorkspaceService()

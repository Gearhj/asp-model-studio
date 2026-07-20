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

from ..core.dataset_store import DATASTORE
from ..preprocessing.feature_profile_service import information_value
from .workspace_types import EDAWorkspaceRequest


_DATE_NAME = re.compile(r"(^|_)(date|month|year|period|timestamp|time)($|_)", re.IGNORECASE)
_ID_NAME = re.compile(r"(^|_)(id|key|uuid|account|customer|application|transaction)(_?id)?($|_)", re.IGNORECASE)
_LEAKAGE_NAME = re.compile(r"target|outcome|response|label|post[_ ]|future|approved|declined", re.IGNORECASE)
_SPLIT_NAME = re.compile(r"(^|_)(split|fold|partition|sample_role)($|_)", re.IGNORECASE)


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
    rates = [row["event_rate"] for row in rows if row.get("event_rate") is not None]
    if len(rates) < 3:
        return "Insufficient bins"
    increasing = all(left <= right for left, right in zip(rates, rates[1:]))
    decreasing = all(left >= right for left, right in zip(rates, rates[1:]))
    return "Increasing" if increasing else "Decreasing" if decreasing else "Non-monotonic"


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

    def _key(self, section: str, request: EDAWorkspaceRequest, df: pd.DataFrame, target: str) -> str:
        payload = {
            "section": section,
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
        result.update({
            "ok": True,
            "section": section,
            "scope": "full_dataset",
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
        date_field = request.date_field if request.date_field in df.columns else None
        segment_field = request.segment_field if request.segment_field in df.columns else None
        return {
            "profile": profile,
            "event_rate_by_time": self._group_target(df, target, event, date_field, True) if problem == "classification" and date_field else [],
            "target_by_segment": self._group_target(df, target, event, segment_field, False) if segment_field else [],
            "date_field": date_field,
            "segment_field": segment_field,
        }

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

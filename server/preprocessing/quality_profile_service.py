from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any

import numpy as np
import pandas as pd

from ..core.dataset_store import DATASTORE


_DATE_NAME = re.compile(r"(^|_)(date|datetime|timestamp|time|dt)($|_)", re.IGNORECASE)
_DATE_TEXT = re.compile(
    r"^(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})(?:[ T].*)?$"
)
_LEAKAGE_NAME = re.compile(
    r"target|outcome|future|post[_ ]|label|response|charge.?off|default.?date|fraud.?confirmed",
    re.IGNORECASE,
)


def _json_value(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _dataset_hash(df: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update("|".join(map(str, df.columns)).encode("utf-8"))
    digest.update(str(df.shape).encode("utf-8"))
    if not df.empty:
        hashed = pd.util.hash_pandas_object(df, index=True).values
        digest.update(hashed.tobytes())
    return digest.hexdigest()


def _legitimate_date_range(name: str, series: pd.Series) -> dict[str, str] | None:
    values = series.dropna()
    if values.empty:
        return None
    if pd.api.types.is_datetime64_any_dtype(values):
        parsed = pd.to_datetime(values, errors="coerce")
    else:
        # Numeric values are never passed through date parsing. Text fields
        # require both a date-like name and a high supported-format match rate.
        if pd.api.types.is_numeric_dtype(values) or not _DATE_NAME.search(str(name)):
            return None
        text = values.astype(str).str.strip()
        matches = text.str.match(_DATE_TEXT)
        if float(matches.mean()) < 0.8:
            return None
        parsed = pd.to_datetime(text.where(matches), errors="coerce", utc=True)
    parsed = parsed.dropna()
    if parsed.empty:
        return None
    return {
        "column": str(name),
        "min": parsed.min().date().isoformat(),
        "max": parsed.max().date().isoformat(),
    }


def profile_active_dataset(target: str | None = None, event_value: Any = None) -> dict[str, Any]:
    df = DATASTORE.get_base_df()
    if df is None or df.empty:
        raise ValueError("No full backend dataset is loaded.")

    target = target if target in df.columns else DATASTORE.target if DATASTORE.target in df.columns else None
    row_count = int(df.shape[0])
    column_count = int(df.shape[1])
    missingness: list[dict[str, Any]] = []
    constant_columns: list[str] = []
    near_zero_variance: list[str] = []
    high_cardinality: list[str] = []
    unexpected_types: list[str] = []
    outlier_prevalence: list[dict[str, Any]] = []
    date_ranges: list[dict[str, str]] = []

    for column in df.columns:
        series = df[column]
        nonmissing = series.dropna()
        missingness.append({
            "column": str(column),
            "count": int(series.isna().sum()),
            "percent": float(series.isna().mean()) if row_count else 0.0,
        })
        distinct = int(nonmissing.nunique(dropna=True))
        if len(nonmissing) and distinct <= 1:
            constant_columns.append(str(column))
        if len(nonmissing) and distinct <= 5:
            top_share = float(nonmissing.value_counts(normalize=True, dropna=True).iloc[0])
            if top_share >= 0.99:
                near_zero_variance.append(str(column))
        if not pd.api.types.is_numeric_dtype(series) and len(nonmissing):
            if distinct > min(100, max(20, int(len(nonmissing) * 0.5))):
                high_cardinality.append(str(column))
            numeric_rate = float(pd.to_numeric(nonmissing, errors="coerce").notna().mean())
            if 0.1 < numeric_rate < 0.8:
                unexpected_types.append(str(column))
        numeric = pd.to_numeric(series, errors="coerce").dropna()
        if len(numeric) >= 10 and str(column) != target:
            q1, q3 = numeric.quantile([0.25, 0.75])
            iqr = float(q3 - q1)
            if np.isfinite(iqr) and iqr > 0:
                prevalence = float(((numeric < q1 - 1.5 * iqr) | (numeric > q3 + 1.5 * iqr)).mean())
                if prevalence >= 0.01:
                    outlier_prevalence.append({"column": str(column), "percent": prevalence})
        date_range = _legitimate_date_range(str(column), series)
        if date_range:
            date_ranges.append(date_range)

    duplicate_rows = int(df.duplicated().sum())
    duplicate_ids: list[str] = []
    for column in df.columns:
        if re.search(r"(^|_)(id|key|account|customer|number)($|_)", str(column), re.IGNORECASE):
            values = df[column].dropna()
            if len(values) and values.duplicated().any():
                duplicate_ids.append(str(column))

    potential_leakage = [
        str(column)
        for column in df.columns
        if str(column) != target and _LEAKAGE_NAME.search(str(column))
    ]

    target_health: dict[str, Any] = {"target": target, "status": "not_evaluated"}
    if target:
        target_values = df[target].dropna()
        counts = target_values.value_counts(dropna=False)
        target_health = {
            "target": target,
            "status": "evaluated",
            "nonmissingCount": int(len(target_values)),
            "missingCount": int(df[target].isna().sum()),
            "distinctCount": int(target_values.nunique()),
        }
        if 1 < len(counts) <= 20:
            governed_event = event_value
            if governed_event is None and any(str(value) == "1" for value in counts.index):
                governed_event = next(value for value in counts.index if str(value) == "1")
            target_health.update({
                "kind": "classification",
                "classDistribution": [
                    {"value": _json_value(index), "count": int(count), "percent": float(count / max(len(target_values), 1))}
                    for index, count in counts.items()
                ],
                "eventValue": _json_value(governed_event),
                "eventRate": float((target_values.astype(str) == str(governed_event)).mean()) if governed_event is not None else None,
            })
        else:
            numeric_target = pd.to_numeric(target_values, errors="coerce").dropna()
            target_health.update({
                "kind": "regression",
                "mean": float(numeric_target.mean()) if len(numeric_target) else None,
                "standardDeviation": float(numeric_target.std()) if len(numeric_target) > 1 else None,
                "minimum": float(numeric_target.min()) if len(numeric_target) else None,
                "maximum": float(numeric_target.max()) if len(numeric_target) else None,
            })

    warnings: list[str] = []
    if potential_leakage:
        warnings.append(f"Review {len(potential_leakage)} potential leakage candidate(s) before modeling.")
    if duplicate_rows:
        warnings.append(f"The full dataset contains {duplicate_rows:,} duplicate row(s).")
    columns_with_missing = sum(1 for row in missingness if row["count"])
    if columns_with_missing:
        warnings.append(f"{columns_with_missing} column(s) contain missing values.")
    readiness = "needs_review" if warnings else "ready"
    source = DATASTORE.meta.get("source") if isinstance(DATASTORE.meta, dict) else {}
    version = DATASTORE.meta.get("dataset_version") or (source.get("version") if isinstance(source, dict) else None)

    return {
        "ok": True,
        "profileScope": "full_dataset",
        "profiledRowCount": row_count,
        "registeredRowCount": row_count,
        "columnCount": column_count,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "datasetVersion": version,
        "datasetHash": _dataset_hash(df),
        "duplicateRows": duplicate_rows,
        "duplicateIdCandidates": duplicate_ids,
        "missingness": sorted(missingness, key=lambda item: item["percent"], reverse=True),
        "constantColumns": constant_columns,
        "nearZeroVarianceColumns": near_zero_variance,
        "highCardinalityCategoricalColumns": high_cardinality,
        "unexpectedDatatypeColumns": unexpected_types,
        "potentialLeakageCandidates": potential_leakage,
        "outlierPrevalence": sorted(outlier_prevalence, key=lambda item: item["percent"], reverse=True),
        "classDistribution": target_health.get("classDistribution"),
        "continuousTargetSummary": target_health if target_health.get("kind") == "regression" else None,
        "targetHealth": target_health,
        "dateRanges": date_ranges,
        "memoryEstimateMb": float(df.memory_usage(index=True, deep=True).sum() / 1024 / 1024),
        "warnings": warnings,
        "readinessStatus": readiness,
    }


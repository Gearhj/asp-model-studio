from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from ..core.dataset_store import DATASTORE
from ..core.modeling_scope import active_project_id
from ..datasets.dataset_identity import assert_expected_active_identity


_SYSTEM_FIELD = re.compile(r"(^|_)(atlas|system|row)(_id|_key|_split|_metadata)?($|_)", re.IGNORECASE)
_SPLIT_FIELD = re.compile(r"(^|_)(split|fold|partition|sample_role)($|_)", re.IGNORECASE)
_LEAKAGE_FIELD = re.compile(r"target|outcome|future|post[_ ]|label|response", re.IGNORECASE)


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _quantile_bucket(series: pd.Series, bins: int = 10) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    nonmissing = numeric.dropna()
    if nonmissing.nunique() <= bins:
        return numeric.astype("object").where(numeric.notna(), "__MISSING__").astype(str)
    ranked = nonmissing.rank(method="first")
    bucketed = pd.qcut(ranked, q=min(bins, len(nonmissing)), duplicates="drop")
    result = pd.Series("__MISSING__", index=series.index, dtype="object")
    result.loc[nonmissing.index] = bucketed.astype(str)
    return result


def _categorical_bucket(series: pd.Series) -> pd.Series:
    values = series.astype("object").where(series.notna(), "__MISSING__").astype(str)
    top = set(values.value_counts().head(50).index)
    return values.where(values.isin(top), "__OTHER__")


def _event_mask(target: pd.Series, event_value: Any = None) -> tuple[pd.Series, Any]:
    nonmissing = target.dropna()
    if nonmissing.empty or nonmissing.nunique() != 2:
        raise ValueError("Information Value requires a binary target with two nonmissing classes.")
    governed_event = event_value
    if governed_event is None:
        for value in nonmissing.unique():
            if str(value) == "1":
                governed_event = value
                break
    if governed_event is None:
        raise ValueError("Set the governed event value before calculating Information Value.")
    return target.astype(str) == str(governed_event), governed_event


def information_value(feature: pd.Series, target: pd.Series, event_value: Any = None) -> tuple[float, Any]:
    event, governed_event = _event_mask(target, event_value)
    valid_target = target.notna()
    buckets = _quantile_bucket(feature) if pd.api.types.is_numeric_dtype(feature) else _categorical_bucket(feature)
    frame = pd.DataFrame({"bucket": buckets, "event": event, "valid": valid_target})
    frame = frame[frame["valid"]]
    grouped = frame.groupby("bucket", dropna=False)["event"].agg(["sum", "count"])
    grouped["non_event"] = grouped["count"] - grouped["sum"]
    smoothing = 0.5
    event_dist = (grouped["sum"] + smoothing) / (grouped["sum"].sum() + smoothing * len(grouped))
    non_event_dist = (grouped["non_event"] + smoothing) / (grouped["non_event"].sum() + smoothing * len(grouped))
    iv = ((event_dist - non_event_dist) * np.log(event_dist / non_event_dist)).sum()
    return float(max(0.0, iv)), governed_event


def _strength(value: float | None, problem_type: str) -> str:
    if value is None or not np.isfinite(value):
        return "Not Evaluated"
    magnitude = abs(float(value))
    if problem_type == "regression":
        if magnitude < 0.05:
            return "Very Weak"
        if magnitude < 0.15:
            return "Weak"
        if magnitude < 0.30:
            return "Moderate"
        return "Strong"
    if magnitude < 0.02:
        return "Not Predictive"
    if magnitude < 0.10:
        return "Weak"
    if magnitude < 0.30:
        return "Medium"
    if magnitude < 0.50:
        return "Strong"
    return "Very Strong"


def _locked_reason(column: str, target: str, source_meta: dict[str, Any]) -> tuple[str, str]:
    if column == target:
        return "target", "Target column"
    normalized = _normalize(column)
    source_target_names = {
        _normalize(source_meta.get(key))
        for key in ("originalTargetLabelColumn", "originalTargetLabel", "labelColumn")
        if source_meta.get(key)
    }
    if normalized in source_target_names:
        return "original_target_label", "Original target-label field"
    if _SPLIT_FIELD.search(column):
        return "split_indicator", "Split or fold indicator"
    if _SYSTEM_FIELD.search(column):
        return "system_metadata", "System metadata field"
    prohibited = {_normalize(value) for value in source_meta.get("prohibitedVariables", []) if value}
    if normalized in prohibited:
        return "prohibited", "Explicitly prohibited variable"
    if _LEAKAGE_FIELD.search(column):
        return "potential_leakage", "Potential post-outcome or target-derived field"
    return "eligible", ""


def profile_features(
    target: str | None = None,
    event_value: Any = None,
    problem_type: str | None = None,
    *,
    project_id: str = "",
    expected_dataset_id: str = "",
    expected_dataset_version_id: str = "",
    legacy_dataset_version: str = "",
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_project_id = str(
        project_id
        or active_project_id()
        or DATASTORE.meta.get("project_id")
        or ""
    ).strip()
    identity = assert_expected_active_identity(
        resolved_project_id,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version_id=expected_dataset_version_id,
        legacy_dataset_version=legacy_dataset_version,
        user=user,
    )
    df = DATASTORE.get_base_df()
    if df is None or df.empty:
        raise ValueError("No full backend dataset is loaded.")
    target = target if target in df.columns else DATASTORE.target if DATASTORE.target in df.columns else None
    if not target:
        raise ValueError("Select a valid target before profiling predictors.")
    y = df[target]
    inferred_problem = problem_type
    if inferred_problem not in {"classification", "regression"}:
        inferred_problem = "classification" if 1 < y.dropna().nunique() <= 20 else "regression"
    selected = set(DATASTORE.get_selected_columns())
    manifest = DATASTORE.meta.get("feature_manifest") if isinstance(DATASTORE.meta.get("feature_manifest"), dict) else {}
    manifest_by_name = {
        str(row.get("feature_name")): row
        for row in manifest.get("features", [])
        if isinstance(row, dict) and row.get("feature_name")
    }
    source_meta = DATASTORE.meta.get("source") if isinstance(DATASTORE.meta.get("source"), dict) else {}
    rows: list[dict[str, Any]] = []
    governed_event = event_value

    for column in df.columns:
        series = df[column]
        manifest_row = manifest_by_name.get(str(column), {})
        role, exclusion_reason = _locked_reason(str(column), str(target), source_meta)
        numeric = pd.to_numeric(series, errors="coerce")
        numeric_rate = float(numeric.notna().mean()) if len(series) else 0.0
        is_numeric = pd.api.types.is_numeric_dtype(series) or numeric_rate >= 0.8
        metric: float | None = None
        association_status = "evaluated"
        if role == "eligible":
            if inferred_problem == "classification":
                try:
                    metric, governed_event = information_value(series, y, governed_event)
                except ValueError:
                    association_status = "not_evaluated"
            elif is_numeric:
                pairs = pd.DataFrame({"x": numeric, "y": pd.to_numeric(y, errors="coerce")}).dropna()
                metric = float(pairs["x"].corr(pairs["y"])) if len(pairs) >= 3 else None
                if metric is None or not np.isfinite(metric):
                    metric = None
                    association_status = "not_evaluated"
            else:
                association_status = "not_evaluated"

        values = numeric.dropna() if is_numeric else pd.Series(dtype="float64")
        quantiles = values.quantile([0.25, 0.5, 0.75]) if len(values) else None
        rows.append({
            "selected": role == "eligible" and (not selected or str(column) in selected),
            "predictor": str(column),
            "role": role,
            "datatype": str(series.dtype),
            "iv": metric if inferred_problem == "classification" else None,
            "ivStrength": _strength(metric, "classification") if inferred_problem == "classification" else None,
            "correlationWithTarget": metric if inferred_problem == "regression" else None,
            "correlationStrength": _strength(metric, "regression") if inferred_problem == "regression" else None,
            "associationStatus": association_status,
            "missingCount": int(series.isna().sum()),
            "missingPercent": float(series.isna().mean()) if len(series) else 0.0,
            "distinctCount": int(series.nunique(dropna=True)),
            "mean": float(values.mean()) if len(values) else None,
            "standardDeviation": float(values.std()) if len(values) > 1 else None,
            "minimum": float(values.min()) if len(values) else None,
            "firstQuartile": float(quantiles.loc[0.25]) if quantiles is not None else None,
            "median": float(quantiles.loc[0.5]) if quantiles is not None else None,
            "thirdQuartile": float(quantiles.loc[0.75]) if quantiles is not None else None,
            "maximum": float(values.max()) if len(values) else None,
            "leakageStatus": "eligible" if role == "eligible" else "locked",
            "eligibilityStatus": "eligible" if role == "eligible" else "excluded",
            "exclusionReason": exclusion_reason,
            "origin": manifest_row.get("origin", "original"),
            "sourceFeatures": manifest_row.get("source_features", [str(column)]),
            "transformationType": manifest_row.get("transformation_type", "source_column"),
            "formulaOrRule": manifest_row.get("formula_or_rule", str(column)),
            "materializationStatus": manifest_row.get("materialization_status", "source"),
            "featureId": manifest_row.get("feature_id"),
            "featureManifestVersion": manifest.get("manifest_version"),
        })

    identity = assert_expected_active_identity(
        resolved_project_id,
        expected_dataset_id=identity["dataset_id"],
        expected_dataset_version_id=identity["dataset_version_id"],
        user=user,
    )
    return {
        "ok": True,
        "project_id": identity["project_id"],
        "dataset_id": identity["dataset_id"],
        "dataset_version_id": identity["dataset_version_id"],
        # Transitional response compatibility only.
        "dataset_version": identity["dataset_version_id"],
        "profileScope": "full_dataset",
        "profiledRowCount": int(df.shape[0]),
        "registeredRowCount": int(df.shape[0]),
        "problemType": inferred_problem,
        "target": target,
        "eventValue": governed_event,
        "selectedColumns": [column for column in DATASTORE.get_selected_columns() if column in df.columns],
        "featureManifestVersion": manifest.get("manifest_version"),
        "features": rows,
    }

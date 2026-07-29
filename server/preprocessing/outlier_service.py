from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .feature_profile_service import information_value
from .predictor_authorization import (
    bureau_special_mask,
    bureau_special_summary,
    governed_predictor_authorization,
)


OUTLIER_METHODS = (
    "NONE",
    "IQR_1_5",
    "IQR_3_0",
    "ZSCORE_3",
    "ZSCORE_4",
    "PCT_01_99",
    "PCT_05_95",
)


def _numeric(series: pd.Series) -> pd.Series | None:
    values = pd.to_numeric(series, errors="coerce")
    nonmissing = int(series.notna().sum())
    if pd.api.types.is_numeric_dtype(series) or (nonmissing and int(values.notna().sum()) / nonmissing >= 0.8):
        return values
    return None


def _thresholds(values: pd.Series, method: str) -> tuple[float, float]:
    clean = values.dropna().astype(float)
    if clean.empty:
        return 0.0, 0.0
    if method == "NONE":
        return float(clean.min()), float(clean.max())
    if method == "ZSCORE_3" or method == "ZSCORE_4":
        width = 3.0 if method == "ZSCORE_3" else 4.0
        mean = float(clean.mean())
        standard_deviation = float(clean.std(ddof=0))
        return mean - width * standard_deviation, mean + width * standard_deviation
    if method == "PCT_01_99":
        return float(clean.quantile(0.005)), float(clean.quantile(0.995))
    if method == "PCT_05_95":
        return float(clean.quantile(0.05)), float(clean.quantile(0.95))
    first_quartile = float(clean.quantile(0.25))
    third_quartile = float(clean.quantile(0.75))
    multiplier = 3.0 if method == "IQR_3_0" else 1.5
    spread = third_quartile - first_quartile
    return first_quartile - multiplier * spread, third_quartile + multiplier * spread


def _method_result(values: pd.Series, method: str) -> dict[str, Any]:
    low, high = _thresholds(values, method)
    clean = values.dropna().astype(float)
    count = 0 if method == "NONE" else int(((clean < low) | (clean > high)).sum())
    return {
        "method": method,
        "lower_threshold": low,
        "upper_threshold": high,
        "outlier_count": count,
        "outlier_rate": count / max(int(len(clean)), 1),
    }


def _rendered_sample(values: pd.Series, limit: int = 600) -> list[float]:
    clean = values.dropna().astype(float)
    if len(clean) <= limit:
        return [float(value) for value in clean.tolist()]
    indexes = np.linspace(0, len(clean) - 1, limit, dtype=int)
    return [float(value) for value in clean.iloc[indexes].tolist()]


def _problem_type(target: pd.Series | None, requested: str | None) -> str:
    if requested in {"classification", "regression"}:
        return str(requested)
    if target is None:
        return "classification"
    distinct = int(target.dropna().nunique())
    return "classification" if 1 < distinct <= 20 else "regression"


def _event_value(target: pd.Series, requested: Any) -> Any:
    if requested is not None and str(requested) != "":
        return requested
    for value in target.dropna().unique():
        if str(value) == "1":
            return value
    return None


class OutlierService:
    def summary(
        self,
        df: pd.DataFrame,
        target: str | None = None,
        event_value: Any = None,
        problem_type: str | None = None,
        selected_columns: list[str] | None = None,
    ) -> dict[str, Any]:
        if df is None or df.empty:
            raise ValueError("No full backend dataset is loaded.")

        y = df[target] if target and target in df.columns else None
        resolved_problem = _problem_type(y, problem_type)
        resolved_event = _event_value(y, event_value) if y is not None and resolved_problem == "classification" else None
        event_rate = None
        if y is not None and resolved_event is not None:
            valid = y.notna()
            event_rate = float((y[valid].astype(str) == str(resolved_event)).mean()) if int(valid.sum()) else None

        authorization = governed_predictor_authorization(
            df,
            target=target,
            selected_columns=selected_columns,
        )
        rows: list[dict[str, Any]] = []
        for name in authorization["authorized_predictors"]:
            column = name
            numeric = _numeric(df[column])
            if numeric is None:
                continue
            special_summary = bureau_special_summary(numeric)
            special_mask = bureau_special_mask(numeric)
            ordinary = numeric.mask(special_mask)

            signal = None
            association_status = "not_evaluated"
            if y is not None:
                if resolved_problem == "classification":
                    try:
                        signal, resolved_event = information_value(df[column], y, resolved_event)
                        association_status = "evaluated"
                    except ValueError:
                        association_status = "target_definition_required"
                else:
                    pairs = pd.DataFrame({"feature": ordinary, "target": pd.to_numeric(y, errors="coerce")}).dropna()
                    if len(pairs) >= 3:
                        correlation = pairs["feature"].corr(pairs["target"])
                        if pd.notna(correlation):
                            signal = float(correlation)
                            association_status = "evaluated"

            clean = ordinary.dropna().astype(float)
            quantiles = clean.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]) if len(clean) else None
            rows.append({
                "feature": name,
                "datatype": str(df[column].dtype),
                "nonmissing_count": int(numeric.notna().sum()),
                "ordinary_nonmissing_count": int(len(clean)),
                "missing_count": int(numeric.isna().sum()),
                "signal_metric": signal,
                "association_status": association_status,
                "methods": {method: _method_result(ordinary, method) for method in OUTLIER_METHODS},
                "rendered_sample": _rendered_sample(ordinary),
                "rendered_sample_count": min(int(len(clean)), 600),
                "distinct_count": int(clean.nunique()),
                "mean": float(clean.mean()) if len(clean) else None,
                "standard_deviation": (
                    float(clean.std(ddof=0)) if len(clean) else None
                ),
                "minimum": float(clean.min()) if len(clean) else None,
                "maximum": float(clean.max()) if len(clean) else None,
                "skewness": float(clean.skew()) if len(clean) >= 3 and pd.notna(clean.skew()) else None,
                **special_summary,
                "quantiles": {
                    "p01": float(quantiles.loc[0.01]) if quantiles is not None else None,
                    "p05": float(quantiles.loc[0.05]) if quantiles is not None else None,
                    "p25": float(quantiles.loc[0.25]) if quantiles is not None else None,
                    "median": float(quantiles.loc[0.5]) if quantiles is not None else None,
                    "p75": float(quantiles.loc[0.75]) if quantiles is not None else None,
                    "p95": float(quantiles.loc[0.95]) if quantiles is not None else None,
                    "p99": float(quantiles.loc[0.99]) if quantiles is not None else None,
                },
            })

        rows.sort(key=lambda row: abs(float(row["signal_metric"] or 0)), reverse=True)
        return {
            "ok": True,
            "scope": "full_dataset",
            "row_count": int(len(df)),
            "target": target,
            "problem_type": resolved_problem,
            "event_value": resolved_event,
            "event_rate": event_rate,
            "rare_event": bool(event_rate is not None and event_rate < 0.05),
            "predictor_authorization": authorization,
            "features": rows,
        }

    def apply(
        self,
        df: pd.DataFrame,
        config: dict[str, Any],
        global_method: str = "IQR_1_5",
        target: str | None = None,
        selected_columns: list[str] | None = None,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        if df is None or df.empty:
            raise ValueError("No full backend dataset is loaded.")
        if global_method not in OUTLIER_METHODS:
            raise ValueError(f"Unsupported global outlier method: {global_method}.")

        work = df.copy()
        authorization = governed_predictor_authorization(
            work,
            target=target,
            selected_columns=selected_columns,
        )
        authorized = set(authorization["authorized_predictors"])
        applied: list[dict[str, Any]] = []
        for column, configured_value in config.items():
            if column not in work.columns or column not in authorized or (target and column == target):
                continue
            configured = str(configured_value or "USE_GLOBAL")
            method = global_method if configured == "USE_GLOBAL" else configured
            if method not in OUTLIER_METHODS:
                raise ValueError(f"Unsupported outlier method '{method}' for {column}.")
            numeric = _numeric(work[column])
            if numeric is None:
                continue
            special_mask = bureau_special_mask(numeric)
            ordinary = numeric.mask(special_mask)
            special_summary = bureau_special_summary(numeric)
            result = _method_result(ordinary, method)
            if method != "NONE":
                treated = numeric.clip(result["lower_threshold"], result["upper_threshold"])
                work[column] = treated.where(~special_mask, numeric)
            applied.append({
                "feature": column,
                "configured_method": configured,
                "applied_method": method,
                "changed_values": result["outlier_count"],
                "lower_threshold": result["lower_threshold"],
                "upper_threshold": result["upper_threshold"],
                "special_values_preserved": special_summary["special_value_count"],
            })
        return work, applied


outlier_service = OutlierService()

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from .feature_profile_service import information_value
from .predictor_authorization import (
    bureau_special_mask,
    bureau_special_summary,
)
from .preprocessing_contract import (
    OUTLIER_METHODS,
    analytical_type,
    apply_outlier_recipe,
    fit_metadata,
    fit_outlier_recipe,
    special_mask,
    special_values_for_feature,
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
        return float(clean.quantile(0.01)), float(clean.quantile(0.99))
    if method == "PCT_05_95":
        return float(clean.quantile(0.05)), float(clean.quantile(0.95))
    first_quartile = float(clean.quantile(0.25))
    third_quartile = float(clean.quantile(0.75))
    multiplier = 3.0 if method == "IQR_3_0" else 1.5
    spread = third_quartile - first_quartile
    return first_quartile - multiplier * spread, third_quartile + multiplier * spread


def _method_result(
    fit_values: pd.Series,
    projected_values: pd.Series,
    method: str,
) -> dict[str, Any]:
    """Fit and preview burden on Development ordinary values only."""

    low, high = _thresholds(fit_values, method)
    clean = projected_values.dropna().astype(float)
    count = 0 if method == "NONE" else int(((clean < low) | (clean > high)).sum())
    return {
        "method": method,
        "lower_threshold": low,
        "upper_threshold": high,
        "outlier_count": count,
        "outlier_rate": count / max(int(len(clean)), 1),
        "fit_ordinary_count": int(fit_values.notna().sum()),
        "projected_ordinary_count": int(len(clean)),
        "fit_scope": "development_preview",
    }


def _rendered_sample(values: pd.Series, limit: int = 600) -> list[float]:
    clean = values.dropna().astype(float)
    if len(clean) <= limit:
        return [float(value) for value in clean.tolist()]
    indexes = np.linspace(0, len(clean) - 1, limit, dtype=int)
    return [float(value) for value in clean.iloc[indexes].tolist()]


class OutlierService:
    def summary(
        self,
        df: pd.DataFrame,
        target: str | None = None,
        event_value: Any = None,
        problem_type: str | None = None,
        selected_columns: list[str] | None = None,
        *,
        predictor_authorization: Mapping[str, Any] | None = None,
        target_analysis_features: pd.DataFrame | None = None,
        target_analysis_target: pd.Series | None = None,
        special_value_contract: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if df is None or df.empty:
            raise ValueError("No full governed predictor population is loaded.")
        if not isinstance(predictor_authorization, Mapping):
            raise ValueError(
                "Exact durable predictor authorization is required for outlier analysis."
            )
        if target_analysis_features is None or target_analysis_target is None:
            raise ValueError(
                "The exact development population is required for target-directed outlier analysis."
            )

        y = target_analysis_target
        resolved_problem = str(problem_type or "").strip().lower()
        if resolved_problem not in {"classification", "regression"}:
            raise ValueError(
                "The exact governed problem type is required for outlier analysis."
            )
        resolved_event = event_value if resolved_problem == "classification" else None
        if resolved_problem == "classification" and resolved_event in (None, ""):
            raise ValueError(
                "The exact governed event value is required for classification outlier analysis."
            )
        event_rate = None
        if y is not None and resolved_event is not None:
            valid = y.notna()
            event_rate = float((y[valid].astype(str) == str(resolved_event)).mean()) if int(valid.sum()) else None

        authorization = dict(predictor_authorization)
        rows: list[dict[str, Any]] = []
        for name in authorization["authorized_predictors"]:
            column = name
            if column not in df.columns or column not in target_analysis_features.columns:
                continue
            numeric = _numeric(df[column])
            if numeric is None:
                continue
            governed_special_mask = (
                special_mask(
                    df[column], str(column), special_value_contract
                )
                if special_value_contract is not None
                else bureau_special_mask(numeric)
            )
            registered_ordinary = numeric.mask(governed_special_mask)
            if special_value_contract is not None:
                special_values = special_values_for_feature(
                    str(column), special_value_contract
                )
                special_counts = {
                    str(value): int(
                        special_mask(
                            df[column], str(column), {
                                "features": {
                                    str(column): {"values": [value]}
                                }
                            }
                        ).sum()
                    )
                    for value in special_values
                }
                special_count = int(governed_special_mask.sum())
                registered_special_summary = {
                    "special_value_count": special_count,
                    "special_value_rate": special_count
                    / max(int(numeric.notna().sum()), 1),
                    "special_values": special_counts,
                }
            else:
                registered_special_summary = bureau_special_summary(numeric)

            signal = None
            association_status = "not_evaluated"
            development_series = target_analysis_features[column]
            development_numeric = _numeric(development_series)
            if development_numeric is None:
                continue
            development_special_mask = (
                special_mask(
                    development_series, str(column), special_value_contract
                )
                if special_value_contract is not None
                else bureau_special_mask(development_numeric)
            )
            development_ordinary = development_numeric.mask(
                development_special_mask
            )
            if special_value_contract is not None:
                development_special_count = int(
                    development_special_mask.sum()
                )
                special_summary = {
                    "special_value_count": development_special_count,
                    "special_value_rate": development_special_count
                    / max(int(development_numeric.notna().sum()), 1),
                    "special_values": {
                        str(value): int(
                            special_mask(
                                development_series,
                                str(column),
                                {
                                    "features": {
                                        str(column): {"values": [value]}
                                    }
                                },
                            ).sum()
                        )
                        for value in special_values_for_feature(
                            str(column), special_value_contract
                        )
                    },
                }
            else:
                special_summary = bureau_special_summary(
                    development_numeric
                )
            if resolved_problem == "classification":
                try:
                    signal, resolved_event = information_value(
                        development_series,
                        y,
                        resolved_event,
                    )
                    association_status = "evaluated"
                except ValueError:
                    association_status = "target_definition_required"
            else:
                pairs = pd.DataFrame(
                    {
                        "feature": pd.to_numeric(
                            development_series, errors="coerce"
                        ),
                        "target": pd.to_numeric(y, errors="coerce"),
                    }
                ).dropna()
                if len(pairs) >= 3:
                    correlation = pairs["feature"].corr(pairs["target"])
                    if pd.notna(correlation):
                        signal = float(correlation)
                        association_status = "evaluated"

            clean = development_ordinary.dropna().astype(float)
            registered_clean = registered_ordinary.dropna().astype(float)
            profile = analytical_type(development_series)
            quantiles = clean.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]) if len(clean) else None
            rows.append({
                "feature": name,
                "datatype": str(development_series.dtype),
                "nonmissing_count": int(development_numeric.notna().sum()),
                "ordinary_nonmissing_count": int(len(clean)),
                "missing_count": int(development_numeric.isna().sum()),
                "signal_metric": signal,
                "association_status": association_status,
                "analytical_type": profile["analytical_type"],
                "outlier_eligible": profile["outlier_eligible"],
                "safe_default_method": profile["safe_default_method"],
                "eligibility_reason": profile["eligibility_reason"],
                "methods": {
                    method: _method_result(
                        development_ordinary,
                        development_ordinary,
                        method,
                    )
                    for method in OUTLIER_METHODS
                },
                "rendered_sample": _rendered_sample(development_ordinary),
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
                "registered_structural": {
                    "scope": "registered_structural_population",
                    "row_count": int(len(df)),
                    "nonmissing_count": int(numeric.notna().sum()),
                    "ordinary_nonmissing_count": int(len(registered_clean)),
                    "missing_or_parse_failure_count": int(numeric.isna().sum()),
                    **registered_special_summary,
                    "rendered_sample": _rendered_sample(registered_ordinary),
                    "rendered_sample_count": min(
                        int(len(registered_clean)), 600
                    ),
                },
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
            "scope": "development_population",
            "analysis_scope": "development_population",
            "target_directed_scope": "development_population",
            "structural_scope": "full_governed_population_predictors_only",
            "fit_scope": "development_preview",
            "row_count": int(len(y)),
            "rows": int(len(y)),
            "registered_population_rows": int(len(df)),
            "registered_structural_row_count": int(len(df)),
            "development_row_count": int(len(y)),
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
        *,
        predictor_authorization: Mapping[str, Any] | None = None,
        fitted_recipe: Mapping[str, Any] | None = None,
        fit_frame: pd.DataFrame | None = None,
        fit_population_id: str = "compatibility-fit",
        special_value_contract: Mapping[str, Any] | None = None,
        rationales: Mapping[str, str] | None = None,
        analytical_types: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        if df is None or df.empty:
            raise ValueError("No full backend dataset is loaded.")
        if global_method not in OUTLIER_METHODS:
            raise ValueError(f"Unsupported global outlier method: {global_method}.")

        if not isinstance(predictor_authorization, Mapping):
            raise ValueError(
                "Exact durable predictor authorization is required for outlier treatment."
            )
        authorization = dict(predictor_authorization)
        policy = {
            "global_method": global_method,
            "config": {
                feature: value
                for feature, value in config.items()
                if feature in set(authorization["authorized_predictors"])
            },
            "rationales": dict(rationales or {}),
            "analytical_types": dict(analytical_types or {}),
        }
        recipe = dict(fitted_recipe or {})
        if not recipe:
            # Compatibility for non-route callers. Governed HTTP mutations
            # always pass an exact Development-fitted recipe.
            fitted = fit_frame if fit_frame is not None else df
            recipe = fit_outlier_recipe(
                fitted,
                policy=policy,
                fit=fit_metadata(
                    fit_scope="development_preview",
                    population_id=fit_population_id,
                    population_count=len(fitted),
                    actor="compatibility-service-call",
                    application_scope="caller_supplied_frame",
                    application_population_id="compatibility-application",
                    application_population_rows=len(df),
                ),
                special_value_contract=special_value_contract,
            )
        work, report = apply_outlier_recipe(
            df,
            recipe=recipe,
            target=target,
            special_value_contract=special_value_contract,
        )
        applied = [
            {
                **row,
                "changed_values": int(row.get("flagged_cell_count") or 0),
                "special_values_preserved": len(
                    row.get("special_values_preserved") or []
                ),
            }
            for row in report["treatments"]
        ]
        return work, applied


outlier_service = OutlierService()

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd
from scipy import stats

from ..interpretation import distribution_findings
from ..result_builder import chart, result, table


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)


def compute_numeric_summary(frame: pd.DataFrame, column: str) -> Dict[str, Any]:
    values = _numeric(frame[column])
    valid = values.dropna()
    if valid.empty:
        return {"column": column, "count": 0, "missing_count": int(len(values)), "missing_percent": 100.0}
    q1, median, q3 = [float(valid.quantile(q)) for q in (0.25, 0.5, 0.75)]
    return {"column": column, "count": int(valid.size), "missing_count": int(values.isna().sum()), "missing_percent": float(values.isna().mean() * 100),
        "mean": float(valid.mean()), "median": median, "standard_deviation": float(valid.std(ddof=1)) if valid.size > 1 else 0.0,
        "variance": float(valid.var(ddof=1)) if valid.size > 1 else 0.0, "minimum": float(valid.min()), "maximum": float(valid.max()),
        "q1": q1, "q3": q3, "interquartile_range": q3 - q1, "skewness": float(valid.skew()) if valid.size > 2 else None,
        "kurtosis": float(valid.kurt()) if valid.size > 3 else None, "unique_count": int(valid.nunique()), "zero_count": int((valid == 0).sum())}


def compute_categorical_summary(frame: pd.DataFrame, column: str, max_categories: int = 20) -> Dict[str, Any]:
    series = frame[column]
    valid = series.dropna().astype(str)
    counts = valid.value_counts(dropna=True)
    mode = counts.index[0] if not counts.empty else None
    return {"column": column, "count": int(valid.size), "missing_count": int(series.isna().sum()), "missing_percent": float(series.isna().mean() * 100),
        "unique_count": int(valid.nunique()), "mode": mode, "mode_frequency": int(counts.iloc[0]) if not counts.empty else 0,
        "top_categories": [{"category": str(index), "count": int(value), "percent": float(value / max(len(valid), 1) * 100)} for index, value in counts.head(max_categories).items()],
        "rare_category_rate": float(counts[counts / max(len(valid), 1) < 0.01].sum() / max(len(valid), 1)),
        "cardinality_warning": valid.nunique() > max(100, len(valid) * 0.5)}


def compute_distribution_diagnostics(frame: pd.DataFrame, column: str, bins: int = 30) -> Dict[str, Any]:
    summary = compute_numeric_summary(frame, column)
    values = _numeric(frame[column]).dropna()
    if values.empty:
        return {"statistics": summary, "histogram": [], "boxplot": {}, "warnings": ["No numeric observations are available for distribution diagnostics."]}
    bins = max(5, min(int(bins), 100))
    counts, edges = np.histogram(values, bins=bins)
    iqr = summary["interquartile_range"]
    lower, upper = summary["q1"] - 1.5 * iqr, summary["q3"] + 1.5 * iqr
    outlier_count = int(((values < lower) | (values > upper)).sum())
    histogram = [{"bin_start": float(edges[i]), "bin_end": float(edges[i + 1]), "count": int(counts[i])} for i in range(len(counts))]
    return {"statistics": summary, "histogram": histogram, "boxplot": {"q1": summary["q1"], "median": summary["median"], "q3": summary["q3"], "lower_whisker": max(float(values.min()), lower), "upper_whisker": min(float(values.max()), upper), "outlier_count": outlier_count}, "warnings": []}


def compute_correlation_matrix(frame: pd.DataFrame, method: str = "pearson") -> Dict[str, Any]:
    numeric = frame.select_dtypes(include=[np.number])
    if numeric.shape[1] < 2:
        return {"columns": [], "matrix": [], "pair_counts": []}
    matrix = numeric.corr(method="spearman" if method == "spearman" else "pearson")
    pair_counts = numeric.notna().astype(int).T.dot(numeric.notna().astype(int))
    return {"columns": [str(c) for c in matrix.columns], "matrix": matrix.round(8).values.tolist(), "pair_counts": pair_counts.values.tolist(), "method": method}


def compute_target_relationships(frame: pd.DataFrame, target_column: str) -> list[Dict[str, Any]]:
    target = _numeric(frame[target_column])
    rows = []
    for column in frame.columns:
        if column == target_column: continue
        candidate = _numeric(frame[column])
        paired = pd.DataFrame({"x": candidate, "y": target}).dropna()
        if len(paired) < 3: continue
        rows.append({"feature": str(column), "pearson": float(paired.x.corr(paired.y, method="pearson")), "spearman": float(paired.x.corr(paired.y, method="spearman")), "pair_count": int(len(paired))})
    return sorted(rows, key=lambda row: abs(row["pearson"]), reverse=True)


def compute_dataset_profile(frame: pd.DataFrame, context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    numeric_rows, categorical_rows = [], []
    for column in frame.columns:
        numeric = _numeric(frame[column])
        if numeric.notna().sum() >= max(2, len(frame) * 0.5): numeric_rows.append(compute_numeric_summary(frame, str(column)))
        else: categorical_rows.append(compute_categorical_summary(frame, str(column)))
    target = parameters.get("target_column")
    distribution_column = parameters.get("column") or (numeric_rows[0]["column"] if numeric_rows else None)
    distribution = compute_distribution_diagnostics(frame, distribution_column, parameters.get("bins", 30)) if distribution_column else None
    warnings = (distribution or {}).get("warnings", [])
    interpretations = distribution_findings((distribution or {}).get("statistics", {}))
    tables = [table("numeric_summary", "Numeric summary", numeric_rows), table("categorical_summary", "Categorical summary", categorical_rows)]
    if target and target in frame.columns: tables.append(table("target_relationships", "Target relationships", compute_target_relationships(frame, target)))
    charts = []
    if distribution:
        charts.append(chart("distribution", "histogram", f"Distribution of {distribution_column}", distribution["histogram"], x_field="bin_start", x_label=distribution_column, y_fields=[{"field": "count", "label": "Count"}], interpretation="Histogram bins are calculated from the selected dataset."))
    return result("descriptive_profile", context, parameters, statistics={"row_count": int(len(frame)), "column_count": int(len(frame.columns)), "numeric_column_count": len(numeric_rows), "categorical_column_count": len(categorical_rows)}, tables=tables, charts=charts, warnings=warnings, interpretations=interpretations)

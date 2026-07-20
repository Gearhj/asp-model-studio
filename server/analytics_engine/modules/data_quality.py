from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from ..result_builder import result, table


def compute_missingness_profile(frame: pd.DataFrame) -> list[Dict[str, Any]]:
    return [{"column": str(column), "missing_count": int(frame[column].isna().sum()), "missing_percent": float(frame[column].isna().mean() * 100)} for column in frame.columns]


def compute_outlier_profile(frame: pd.DataFrame) -> list[Dict[str, Any]]:
    rows = []
    for column in frame.select_dtypes(include="number").columns:
        values = frame[column].dropna()
        if values.empty: continue
        q1, q3 = values.quantile(.25), values.quantile(.75); iqr = q3 - q1
        rows.append({"column": str(column), "lower_threshold": float(q1 - 1.5 * iqr), "upper_threshold": float(q3 + 1.5 * iqr), "outlier_count": int(((values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)).sum())})
    return rows


def compute_data_quality_scorecard(frame: pd.DataFrame, context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    missing = compute_missingness_profile(frame)
    duplicate_count = int(frame.duplicated().sum())
    constants = [str(c) for c in frame.columns if frame[c].nunique(dropna=False) <= 1]
    high_cardinality = [str(c) for c in frame.columns if frame[c].nunique(dropna=True) > min(100, len(frame) * .5)]
    completeness = 100 - float(frame.isna().mean().mean() * 100)
    uniqueness = 100 - duplicate_count / max(len(frame), 1) * 100
    score = round(max(0, min(100, .65 * completeness + .35 * uniqueness)), 2)
    warnings = []
    if duplicate_count: warnings.append(f"{duplicate_count:,} duplicate rows were detected in the selected dataset.")
    if constants: warnings.append(f"{len(constants)} constant variable(s) require review.")
    return result("data_quality_profile", context, parameters, statistics={"quality_score": score, "completeness": completeness, "uniqueness": uniqueness, "duplicate_count": duplicate_count, "constant_variables": constants, "high_cardinality_variables": high_cardinality}, tables=[table("missingness", "Missingness profile", missing), table("outliers", "Numeric outlier profile", compute_outlier_profile(frame))], warnings=warnings)

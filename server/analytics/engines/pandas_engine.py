"""Enterprise Analytical Data Plane -- bounded pandas fallback / row-level shaping.

This module NEVER receives the full enterprise-scale source. Every function
here operates on a frame that was already bounded upstream -- either by
duckdb_engine.bounded_sql_sample()/bounded_rows() (a SQL-level LIMIT/SAMPLE
against a file-backed source), or by an already-small in-memory frame
(workspace uploads are capped at ATLAS_MAX_UPLOAD_ROWS; evaluation-result
frames are one model's training-run arrays). The query planner is responsible
for enforcing that nothing larger than resource_governance.LIMITS.pandas_fallback_max_rows
ever reaches this module -- see query_planner.py's `_reject_unsafe_pandas`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .. import sampling
from ..resource_governance import LIMITS


def regression_diagnostics(frame: pd.DataFrame, actual_col: str, prediction_col: str) -> Dict[str, Any]:
    actual = frame[actual_col].astype(float)
    prediction = frame[prediction_col].astype(float)
    residual = actual - prediction
    n = len(frame)
    mae = float(residual.abs().mean()) if n else None
    mse = float((residual ** 2).mean()) if n else None
    rmse = float(np.sqrt(mse)) if mse is not None else None
    mean_actual = float(actual.mean()) if n else None
    ss_tot = float(((actual - mean_actual) ** 2).sum()) if mean_actual is not None else 0.0
    ss_res = float((residual ** 2).sum())
    r2 = (1 - ss_res / ss_tot) if ss_tot > 0 else None
    return {
        "rowCount": n, "mae": mae, "mse": mse, "rmse": rmse, "r2": r2 if n >= 10 else None,
        "meanResidual": float(residual.mean()) if n else None,
        "medianResidual": float(residual.median()) if n else None,
        "medianAbsoluteError": float(residual.abs().median()) if n else None,
        "minPrediction": float(prediction.min()) if n else None, "maxPrediction": float(prediction.max()) if n else None,
        "minActual": float(actual.min()) if n else None, "maxActual": float(actual.max()) if n else None,
    }


def residual_distribution(frame: pd.DataFrame, actual_col: str, prediction_col: str, bins: int = 20) -> Dict[str, Any]:
    bins = min(bins, LIMITS.max_histogram_bins)
    residual = (frame[actual_col].astype(float) - frame[prediction_col].astype(float)).dropna()
    if residual.empty:
        return {"bins": [], "meanResidual": None, "medianResidual": None}
    counts, edges = np.histogram(residual, bins=bins)
    return {
        "bins": [{"x0": float(edges[i]), "x1": float(edges[i + 1]), "count": int(counts[i])} for i in range(len(counts))],
        "meanResidual": float(residual.mean()), "medianResidual": float(residual.median()),
    }


def qq_points(frame: pd.DataFrame, actual_col: str, prediction_col: str) -> List[Dict[str, float]]:
    residual = (frame[actual_col].astype(float) - frame[prediction_col].astype(float)).dropna()
    n = len(residual)
    if n < 8:
        return []
    sorted_residual = np.sort(residual.to_numpy())
    from scipy import stats
    theoretical = stats.norm.ppf((np.arange(1, n + 1) - 0.5) / n)
    return [{"theoretical": float(t), "sample": float(s)} for t, s in zip(theoretical, sorted_residual)]


def error_by_target_band(frame: pd.DataFrame, actual_col: str, prediction_col: str, bands: int = 8) -> Dict[str, Any]:
    actual = frame[actual_col].astype(float)
    prediction = frame[prediction_col].astype(float)
    residual = actual - prediction
    try:
        band_labels, band_edges = pd.qcut(actual, q=min(bands, actual.nunique()), duplicates="drop", retbins=True)
    except (ValueError, IndexError):
        return {"bands": []}
    result = []
    grouped = residual.groupby(band_labels, observed=True)
    for interval, group in grouped:
        abs_errors = group.abs()
        result.append({
            "x0": float(interval.left), "x1": float(interval.right), "count": int(len(group)),
            "mae": float(abs_errors.mean()) if len(group) else None,
            "rmse": float(np.sqrt((group ** 2).mean())) if len(group) else None,
            "medianAbsoluteError": float(abs_errors.median()) if len(group) else None,
            "sampleSizeWarning": len(group) < 5,
        })
    return {"bands": result}


def threshold_curve(frame: pd.DataFrame, actual_col: str, score_col: str, num_points: int = 50, positive_value: Any = 1) -> Dict[str, Any]:
    num_points = min(num_points, LIMITS.max_histogram_bins)
    actual = (frame[actual_col] == positive_value).astype(int)
    score = frame[score_col].astype(float)
    thresholds = np.linspace(0, 1, num_points)
    points = []
    for t in thresholds:
        predicted_positive = score >= t
        tp = int(((predicted_positive) & (actual == 1)).sum())
        fp = int(((predicted_positive) & (actual == 0)).sum())
        tn = int(((~predicted_positive) & (actual == 0)).sum())
        fn = int(((~predicted_positive) & (actual == 1)).sum())
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        specificity = tn / (tn + fp) if (tn + fp) else None
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall and (precision + recall) else None
        points.append({
            "threshold": float(t), "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": precision, "recall": recall, "specificity": specificity, "f1": f1,
            "alertRate": (tp + fp) / len(frame) if len(frame) else None,
        })
    return {"points": points, "positiveValue": positive_value}


def confusion_matrix_at_threshold(frame: pd.DataFrame, actual_col: str, score_col: str, threshold: float, positive_value: Any = 1) -> Dict[str, Any]:
    actual = (frame[actual_col] == positive_value).astype(int)
    predicted_positive = frame[score_col].astype(float) >= threshold
    tp = int(((predicted_positive) & (actual == 1)).sum())
    fp = int(((predicted_positive) & (actual == 0)).sum())
    tn = int(((~predicted_positive) & (actual == 0)).sum())
    fn = int(((~predicted_positive) & (actual == 1)).sum())
    return {"threshold": threshold, "tp": tp, "fp": fp, "tn": tn, "fn": fn}


def roc_auc(frame: pd.DataFrame, actual_col: str, score_col: str, positive_value: Any = 1) -> Optional[float]:
    actual = (frame[actual_col] == positive_value).astype(int)
    positives = frame.loc[actual == 1, score_col].astype(float)
    negatives = frame.loc[actual == 0, score_col].astype(float)
    if positives.empty or negatives.empty:
        return None
    # Rank-based Mann-Whitney U -- O(n log n), safe well beyond this module's bounded input size.
    combined = pd.concat([positives, negatives])
    ranks = combined.rank()
    pos_rank_sum = ranks.iloc[: len(positives)].sum()
    n_pos, n_neg = len(positives), len(negatives)
    auc = (pos_rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(auc)


def prediction_distribution(frame: pd.DataFrame, prediction_col: str, bins: int = 20) -> Dict[str, Any]:
    values = frame[prediction_col].astype(float).dropna()
    if values.empty:
        return {"bins": []}
    counts, edges = np.histogram(values, bins=min(bins, LIMITS.max_histogram_bins))
    total = len(values)
    return {"bins": [{"x0": float(edges[i]), "x1": float(edges[i + 1]), "count": int(counts[i]), "share": float(counts[i]) / total} for i in range(len(counts))]}


def psi(baseline: pd.Series, comparison: pd.Series, bins: int = 10) -> Dict[str, Any]:
    """Population Stability Index between a baseline (TRAIN) and comparison
    (TEST/OOT) numeric distribution -- bin edges from the baseline, epsilon
    substitution for zero-count bins so a single empty bin cannot produce inf."""
    baseline = baseline.astype(float).dropna()
    comparison = comparison.astype(float).dropna()
    if baseline.empty or comparison.empty:
        return {"psi": None, "bins": []}
    edges = np.histogram_bin_edges(baseline, bins=bins)
    baseline_counts, _ = np.histogram(baseline, bins=edges)
    comparison_counts, _ = np.histogram(comparison, bins=edges)
    eps = 1e-4
    baseline_pct = np.maximum(baseline_counts / max(1, baseline_counts.sum()), eps)
    comparison_pct = np.maximum(comparison_counts / max(1, comparison_counts.sum()), eps)
    contributions = (comparison_pct - baseline_pct) * np.log(comparison_pct / baseline_pct)
    total_psi = float(contributions.sum())
    return {
        "psi": total_psi,
        "bins": [{"x0": float(edges[i]), "x1": float(edges[i + 1]), "baselineShare": float(baseline_pct[i]), "comparisonShare": float(comparison_pct[i]), "contribution": float(contributions[i])} for i in range(len(contributions))],
    }


def top_outliers(frame: pd.DataFrame, metric_col: str, n: int = 20) -> pd.DataFrame:
    n = min(n, LIMITS.max_result_rows)
    return sampling.top_n_by_metric(frame, metric_col, n)


def vsi(baseline: pd.DataFrame, comparison: pd.DataFrame, columns: List[str], bins: int = 10) -> Dict[str, Any]:
    """Variable Stability Index across multiple feature columns -- reuses the same
    binned-PSI-style formula per column, ranked by severity."""
    results = []
    for column in columns:
        if column not in baseline.columns or column not in comparison.columns:
            continue
        if not pd.api.types.is_numeric_dtype(baseline[column]):
            continue
        column_result = psi(baseline[column], comparison[column], bins=bins)
        value = column_result.get("psi")
        status = "fail" if (value is not None and value >= 0.25) else "warning" if (value is not None and value >= 0.10) else "pass"
        results.append({"column": column, "vsi": value, "status": status})
    results.sort(key=lambda r: (r["vsi"] is None, -(r["vsi"] or 0)))
    return {"variables": results, "thresholds": {"warning": 0.10, "fail": 0.25}}

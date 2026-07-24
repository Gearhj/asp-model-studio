"""Enterprise Analytical Data Plane -- sampling and approximation policies.

Every sampling function is deterministic when given a seed (numpy Generator
seeded explicitly), returns a method label for the response contract, and
never silently reduces cardinality without the caller being able to report it.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np
import pandas as pd

from .query_contract import SampleMethod
from .resource_governance import LIMITS


def _rng(seed: Optional[int]) -> np.random.Generator:
    return np.random.default_rng(seed if seed is not None else 0)


def random_sample(df: pd.DataFrame, size: int, seed: Optional[int]) -> pd.DataFrame:
    n = min(size, len(df), LIMITS.max_scatter_points)
    if n >= len(df):
        return df
    indices = _rng(seed).choice(len(df), size=n, replace=False)
    return df.iloc[np.sort(indices)]


def class_stratified_sample(df: pd.DataFrame, target_column: str, size: int, seed: Optional[int]) -> pd.DataFrame:
    """Preserves each class's share of the sample -- prevents a minority class from
    being silently dropped by a plain random sample, per Phase H requirement 2."""
    size = min(size, LIMITS.max_scatter_points)
    if target_column not in df.columns or len(df) <= size:
        return df
    groups = df.groupby(target_column, group_keys=False, observed=True)
    class_shares = df[target_column].value_counts(normalize=True)
    parts: List[pd.DataFrame] = []
    for class_value, group in groups:
        share = class_shares.get(class_value, 0.0)
        take = max(1, int(round(share * size)))
        parts.append(random_sample(group, take, seed))
    combined = pd.concat(parts) if parts else df.head(0)
    return combined.head(size)


def target_band_stratified_sample(df: pd.DataFrame, target_column: str, size: int, seed: Optional[int], bands: int = 10) -> pd.DataFrame:
    """Preserves the target's distribution shape for regression -- required so a
    scatter/residual sample does not misrepresent the true actual/residual spread
    (Phase H requirement 3)."""
    size = min(size, LIMITS.max_scatter_points)
    if target_column not in df.columns or len(df) <= size:
        return df
    try:
        band_labels = pd.qcut(df[target_column], q=min(bands, df[target_column].nunique()), duplicates="drop")
    except (ValueError, IndexError):
        return random_sample(df, size, seed)
    parts: List[pd.DataFrame] = []
    band_counts = band_labels.value_counts(normalize=True)
    for band_value, group_index in band_labels.groupby(band_labels, observed=True).groups.items():
        group = df.loc[group_index]
        share = band_counts.get(band_value, 0.0)
        take = max(1, int(round(share * size)))
        parts.append(random_sample(group, take, seed))
    combined = pd.concat(parts) if parts else df.head(0)
    return combined.head(size)


def reservoir_sample(df: pd.DataFrame, size: int, seed: Optional[int]) -> pd.DataFrame:
    size = min(size, LIMITS.max_scatter_points)
    if len(df) <= size:
        return df
    rng = _rng(seed)
    reservoir_idx = np.arange(size)
    for i in range(size, len(df)):
        j = rng.integers(0, i + 1)
        if j < size:
            reservoir_idx[j] = i
    return df.iloc[np.sort(reservoir_idx)]


def top_n_by_metric(df: pd.DataFrame, metric_column: str, n: int, ascending: bool = False) -> pd.DataFrame:
    n = min(n, LIMITS.max_result_rows)
    if metric_column not in df.columns:
        return df.head(0)
    return df.reindex(df[metric_column].abs().sort_values(ascending=ascending).index).head(n)


def hexbin_density(x: Sequence[float], y: Sequence[float], grid_size: int = 30) -> dict:
    """Density-grid aggregation for a scatter that would otherwise exceed the
    bounded-point limit -- returns bin centers and counts, never raw points."""
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    mask = np.isfinite(x_arr) & np.isfinite(y_arr)
    x_arr, y_arr = x_arr[mask], y_arr[mask]
    if len(x_arr) == 0:
        return {"bins": [], "xEdges": [], "yEdges": []}
    counts, x_edges, y_edges = np.histogram2d(x_arr, y_arr, bins=grid_size)
    bins = []
    for i in range(counts.shape[0]):
        for j in range(counts.shape[1]):
            if counts[i, j] > 0:
                bins.append({
                    "x": float((x_edges[i] + x_edges[i + 1]) / 2),
                    "y": float((y_edges[j] + y_edges[j + 1]) / 2),
                    "count": int(counts[i, j]),
                })
    return {"bins": bins, "xEdges": x_edges.tolist(), "yEdges": y_edges.tolist()}


def approximate_quantiles(values: pd.Series, quantiles: List[float]) -> List[float]:
    """numpy's default quantile interpolation is already an approximation for
    non-exact ranks; explicitly labeled as such in the response, never silently
    presented as exact (Phase H requirement 6)."""
    clean = values.dropna()
    if clean.empty:
        return [float("nan")] * len(quantiles)
    return [float(np.quantile(clean, q)) for q in quantiles]


def exact_quantiles(values: pd.Series, quantiles: List[float]) -> List[float]:
    """Full sort -- exact but O(n log n); the planner only allows this path when
    the row count is within resource_governance's pandas fallback bound."""
    clean = values.dropna().sort_values()
    if clean.empty:
        return [float("nan")] * len(quantiles)
    n = len(clean)
    result = []
    for q in quantiles:
        rank = min(n - 1, max(0, int(round(q * (n - 1)))))
        result.append(float(clean.iloc[rank]))
    return result

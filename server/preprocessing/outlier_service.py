# server/preprocessing/outlier_service.py
# =============================================================================
# Outlier Service for DS Workflow (Modular Backend)
# =============================================================================
# Contains all logic for outlier detection and summary statistics used by
# Step03 Outliers. Mirrors the behavior of the original monolithic backend:
#
#   POST /api/outliers/summary
#
# using:
#   • IQR-based outlier detection
#   • Z-score-based outlier detection
# =============================================================================

from __future__ import annotations
from typing import Dict, Any, List

import numpy as np
import pandas as pd


def is_numeric_series(s: pd.Series) -> bool:
    """Return True if the pandas Series is numeric."""
    return pd.api.types.is_numeric_dtype(s)


def outlier_iqr_mask(s: pd.Series, k: float = 1.5) -> pd.Series:
    """Return boolean mask of IQR-based outliers."""
    q1 = s.quantile(0.25)
    q3 = s.quantile(0.75)
    iqr = q3 - q1
    lo = q1 - k * iqr
    hi = q3 + k * iqr
    return (s < lo) | (s > hi)


def outlier_zscore_mask(s: pd.Series, thresh: float = 3.0) -> pd.Series:
    """Return boolean mask of z-score-based outliers."""
    mu = s.mean()
    sd = s.std(ddof=0)
    if sd == 0 or np.isnan(sd):
        return pd.Series(False, index=s.index)
    return (np.abs((s - mu) / sd) > thresh)


class OutlierService:
    """
    Service class wrapping outlier logic for better testability and reuse.
    """

    def summary(self, df: pd.DataFrame, method: str = "iqr", z_thresh: float = 3.0) -> Dict[str, Any]:
        """
        Compute per-column outlier counts and percentages.

        Parameters
        ----------
        df : DataFrame
            Input dataset.
        method : str
            'iqr' or 'zscore'
        z_thresh : float
            Z-score threshold when method == 'zscore'

        Returns
        -------
        dict:
            {
              "ok": True,
              "rows": [
                 {"column": col, "method": method, "count": int, "pct": float},
                 ...
              ]
            }
        """
        rows: List[Dict[str, Any]] = []

        for c in df.columns:
            s = df[c]
            if not is_numeric_series(s):
                continue

            try:
                if method == "iqr":
                    m = outlier_iqr_mask(s.astype(float))
                else:
                    m = outlier_zscore_mask(s.astype(float), thresh=float(z_thresh))
            except Exception:
                # Fail gracefully on weird columns
                m = pd.Series(False, index=s.index)

            count = int(m.sum())
            pct = float(count * 100.0 / len(s)) if len(s) else 0.0
            rows.append(
                {
                    "column": c,
                    "method": method,
                    "count": count,
                    "pct": pct,
                }
            )

        rows.sort(key=lambda r: (-r["count"], r["column"]))

        return {
            "ok": True,
            "rows": rows,
        }


# Singleton service instance
outlier_service = OutlierService()

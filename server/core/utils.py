# server/core/utils.py
# =============================================================================
# Shared Utility Functions for DS Workflow Backend (Modular Architecture)
# =============================================================================
# Includes:
#   • Large-dataset DataFrame serialization helpers
#   • KS statistic calculation
#   • Gini coefficient
#   • Safe logging / soft error handler
#   • Future hooks for scorecard export, MRM docs, etc.
# =============================================================================

from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Any, Dict


# -----------------------------------------------------------------------------
# Large Dataset JSON Serialization
# -----------------------------------------------------------------------------
def df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Convert a DataFrame to a list-of-dicts with safety for large datasets.

    FastAPI/Pydantic does not like numpy types or weird objects, so everything
    is converted to a JSON-safe Python type here.
    """
    if df is None:
        return []

    df_clean = df.copy()
    for col in df_clean.columns:
        df_clean[col] = df_clean[col].apply(_safe_json_value)

    return df_clean.to_dict(orient="records")


def _safe_json_value(v: Any) -> Any:
    """
    Convert numpy/scalar values into JSON-safe types.
    """
    if isinstance(v, (np.int64, np.int32, np.integer)):
        return int(v)
    if isinstance(v, (np.float64, np.float32, np.floating)):
        return float(v)
    if pd.isna(v):
        return None
    return v


# -----------------------------------------------------------------------------
# KS Statistic
# -----------------------------------------------------------------------------
def ks_statistic(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Compute the Kolmogorov-Smirnov statistic for binary classification.
    """
    if len(y_true) == 0:
        return 0.0

    df = pd.DataFrame({"y": y_true, "p": y_pred})
    df0 = df[df["y"] == 0]["p"]
    df1 = df[df["y"] == 1]["p"]

    if len(df0) == 0 or len(df1) == 0:
        return 0.0

    cdf0 = np.sort(df0)
    cdf1 = np.sort(df1)

    # Empirical CDFs
    ecdf0 = np.arange(1, len(cdf0) + 1) / len(cdf0)
    ecdf1 = np.arange(1, len(cdf1) + 1) / len(cdf1)

    # Align lengths by interpolation
    x = np.linspace(0, 1, max(len(ecdf0), len(ecdf1)))
    ecdf0_interp = np.interp(x, np.linspace(0, 1, len(ecdf0)), ecdf0)
    ecdf1_interp = np.interp(x, np.linspace(0, 1, len(ecdf1)), ecdf1)

    return float(np.max(np.abs(ecdf1_interp - ecdf0_interp)))


# -----------------------------------------------------------------------------
# Gini Coefficient (2*AUC - 1)
# -----------------------------------------------------------------------------
def gini_from_auc(auc: float | None) -> float | None:
    if auc is None:
        return None
    return 2 * auc - 1


# -----------------------------------------------------------------------------
# Safe Logger (silent fail)
# -----------------------------------------------------------------------------
def safe_log(message: str):
    """
    A tiny safe logger for debugging without breaking endpoints.
    Can be expanded later into a full FinServ audit log.
    """
    try:
        print(f"[DS WORKFLOW] {message}")
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Future Hooks
# -----------------------------------------------------------------------------
def not_implemented(msg: str):
    """
    Placeholder hook for features planned in later phases:
      • Model cards
      • MRM documentation
      • Fairness & stability testing
      • Sensitivity analysis
      • Scorecard / SHAP summaries
    """
    raise NotImplementedError(f"Feature not implemented yet: {msg}")

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..core.dataset_store import DATASTORE
from ..core.session_checkpoint import save_checkpoint

router = APIRouter()

MISSING_STRINGS = {"", "na", "n/a", "null", "none", "nan", "missing"}


class MissingRule(BaseModel):
    strategy: str = "None"
    constantValue: Optional[Any] = None


class MissingApplyRequest(BaseModel):
    config: Dict[str, MissingRule] = Field(default_factory=dict)


def _current_df() -> Optional[pd.DataFrame]:
    return DATASTORE.get_active_df()


def _normalize_missing(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    for col in work.columns:
        if pd.api.types.is_object_dtype(work[col]) or pd.api.types.is_string_dtype(work[col]):
            text = work[col].astype("string")
            missing_mask = text.str.strip().str.lower().isin(MISSING_STRINGS)
            work.loc[missing_mask, col] = np.nan
    return work


def _feature_columns(df: pd.DataFrame) -> List[str]:
    target = DATASTORE.target
    return [str(col) for col in df.columns if not target or str(col) != str(target)]


def _is_numeric_like(series: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(series):
        return True
    non_missing = series.dropna()
    if non_missing.empty:
        return False
    numeric = pd.to_numeric(non_missing, errors="coerce")
    return float(numeric.notna().mean()) >= 0.8


def _display_dtype(series: pd.Series) -> str:
    return "float64" if _is_numeric_like(series) else str(series.dtype)


@router.get("/summary")
def missing_summary() -> Dict[str, Any]:
    df = _current_df()
    if df is None or df.empty:
        return {"ok": True, "rows": 0, "columns": [], "stats": {}}

    work = _normalize_missing(df)
    features = _feature_columns(work)
    stats: Dict[str, Any] = {}
    columns: List[Dict[str, Any]] = []
    total = int(len(work))
    for col in features:
        missing = int(work[col].isna().sum())
        stats[col] = {
            "missing": missing,
            "missingPct": float((missing / total) * 100) if total else 0.0,
            "total": total,
        }
        columns.append(
            {
                "name": col,
                "dtype": _display_dtype(work[col]),
                "role": "feature",
            }
        )
    return {"ok": True, "rows": total, "columns": columns, "stats": stats, "target": DATASTORE.target}


@router.post("/apply")
def apply_missing_values(request: MissingApplyRequest) -> Dict[str, Any]:
    df = _current_df()
    if df is None or df.empty:
        return {"ok": False, "error": "No dataset is loaded."}

    work = _normalize_missing(df)
    before = int(work.isna().sum().sum())
    features = set(_feature_columns(work))
    dropped_rows = 0
    applied: List[Dict[str, Any]] = []

    for col, rule in request.config.items():
        if col not in work.columns or col not in features:
            continue
        strategy = str(rule.strategy or "None").strip().lower()
        if strategy == "none":
            continue

        missing_before = int(work[col].isna().sum())
        if missing_before == 0:
            continue

        if strategy == "drop row":
            row_count = int(len(work))
            work = work.loc[~work[col].isna()].copy()
            dropped_rows += row_count - int(len(work))
            applied.append({"feature": col, "strategy": rule.strategy, "filled": 0, "dropped_rows": row_count - int(len(work))})
            continue

        fill_value: Any = None
        series = work[col]
        numeric = _is_numeric_like(series)
        if numeric:
            series = pd.to_numeric(series, errors="coerce")
            work[col] = series
        if strategy == "mean" and numeric:
            fill_value = pd.to_numeric(series, errors="coerce").mean()
        elif strategy == "median" and numeric:
            fill_value = pd.to_numeric(series, errors="coerce").median()
        elif strategy in {"mode", "mean", "median"}:
            mode = series.dropna().mode()
            fill_value = mode.iloc[0] if len(mode) else ""
        elif strategy == "constant":
            fill_value = rule.constantValue if rule.constantValue is not None else ""
            if numeric:
                fill_value = pd.to_numeric(pd.Series([fill_value]), errors="coerce").iloc[0]
        else:
            continue

        if pd.isna(fill_value):
            fill_value = 0 if numeric else ""
        work[col] = series.fillna(fill_value)
        applied.append({"feature": col, "strategy": rule.strategy, "filled": missing_before, "value": str(fill_value)})

    DATASTORE.set_processed(work)
    DATASTORE.meta["missing_config"] = {
        key: value.dict() for key, value in request.config.items()
    }
    save_checkpoint()

    after = int(work.isna().sum().sum())
    return {
        "ok": True,
        "rows": int(len(work)),
        "missing_before": before,
        "missing_after": after,
        "dropped_rows": int(dropped_rows),
        "applied": applied,
    }

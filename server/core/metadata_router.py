# server/core/metadata_router.py
# =============================================================================
# Metadata + Data router – compatibility endpoints for legacy frontend calls:
#
#   GET  /api/columns
#   GET  /api/data/get_sample
#   POST /api/data/set_sample
#
# These are used by:
#   • Step01_DataAcquisition.tsx
#   • Step02_EDA.tsx
#   • Step03/04/05 pages that need columns or samples
#
# They operate on the in-memory DATASTORE and only mutate it to:
#   • set raw_df
#   • optionally set target
# =============================================================================

from __future__ import annotations

from typing import Dict, Any, List, Optional
import re

import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .dataset_store import DATASTORE
from .session_checkpoint import save_checkpoint

router = APIRouter()


def _current_df() -> Optional[pd.DataFrame]:
    """
    Prefer processed_df if available, otherwise raw_df.
    """
    if DATASTORE.processed_df is not None:
        return DATASTORE.processed_df
    if DATASTORE.raw_df is not None:
        return DATASTORE.raw_df
    return None


def _infer_target(df: pd.DataFrame) -> Optional[str]:
    """
    Very light heuristic to guess a target column if not already set:

      • Exact case-insensitive match on: fraud, target, label
    """
    # If already set and valid, keep it
    if DATASTORE.target is not None and DATASTORE.target in df.columns:
        return DATASTORE.target

    pattern = re.compile(
        r"^(fraud|target|label|class|y|bad|default|outcome|response|event)$",
        flags=re.IGNORECASE,
    )
    for col in df.columns:
        if pattern.search(str(col)):
            DATASTORE.set_target(str(col))
            return str(col)

    for col in reversed(list(df.columns)):
        s = df[col].dropna()
        if s.empty:
            continue
        unique = pd.unique(s)
        if 1 < len(unique) <= 2:
            DATASTORE.set_target(str(col))
            return str(col)

    return None


# -----------------------------------------------------------------------------
# Pydantic model for /data/set_sample
# -----------------------------------------------------------------------------
class SetSamplePayload(BaseModel):
    headers: List[str] = Field(default_factory=list)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    target: Optional[str] = None
    selected_columns: Optional[List[str]] = None


# -----------------------------------------------------------------------------
# POST /api/data/set_sample
# -----------------------------------------------------------------------------
@router.post("/data/set_sample")
def set_sample(payload: SetSamplePayload) -> Dict[str, Any]:
    """
    Legacy-compatible endpoint used by Step01_DataAcquisition.tsx.

    Payload shape:

        {
          "headers": [...],
          "rows": [ {col: val, ...}, ... ],
          "target": "TARGET" | null,
          "selected_columns": [...]
        }

    We:
      • Build a DataFrame from rows
      • Store it into DATASTORE.raw_df
      • Optionally set DATASTORE.target
    """
    if not payload.rows:
        return {"ok": False, "error": "No rows provided."}

    try:
        df = pd.DataFrame(payload.rows)
    except Exception as exc:
        return {"ok": False, "error": f"Failed to build DataFrame: {exc}"}

    if df.empty:
        return {"ok": False, "error": "Constructed DataFrame is empty."}

    # Persist into DATASTORE
    DATASTORE.set_raw(df)

    if payload.target:
        if payload.target in df.columns:
            DATASTORE.set_target(payload.target)
        else:
            # keep silent; frontend may let user pick it later
            pass
    else:
        _infer_target(df)

    save_checkpoint()

    return {
        "ok": True,
        "n_rows": int(df.shape[0]),
        "n_cols": int(df.shape[1]),
        "columns": [str(c) for c in df.columns],
        "target": DATASTORE.target,
    }


# -----------------------------------------------------------------------------
# GET /api/columns
# -----------------------------------------------------------------------------
@router.get("/columns")
def get_columns() -> Dict[str, Any]:
    """
    Column metadata used by several steps.

    Response shape matches frontend expectations:

        {
          "ok": true,
          "columns": [
            {"name": "AGE", "dtype": "float64", "role": "feature"},
            {"name": "TARGET", "dtype": "int64", "role": "target"}
          ],
          "target": "TARGET"
        }
    """
    df = _current_df()
    if df is None or df.empty:
        return {"ok": True, "columns": [], "target": None}

    target = _infer_target(df)

    columns: List[Dict[str, Any]] = []
    for name in df.columns:
        s = df[name]
        columns.append(
            {
                "name": str(name),
                "dtype": str(s.dtype),
                "role": "target" if target is not None and str(name) == target else "feature",
            }
        )

    return {
        "ok": True,
        "columns": columns,
        "target": target,
    }


# -----------------------------------------------------------------------------
# GET /api/data/get_sample
# -----------------------------------------------------------------------------
@router.get("/data/get_sample")
def get_sample(max_rows: int = 5000) -> Dict[str, Any]:
    """
    Sample of the current dataset.

    Shape aligns with what Step04_Outliers.tsx expects:

        {
          "ok": true,
          "headers": [...],
          "rows": [{"col": "value", ...}, ...],
          "target": "TARGET",
          "selected_columns": null
        }
    """
    df = _current_df()
    if df is None or df.empty:
        return {
            "ok": True,
            "headers": [],
            "rows": [],
            "target": DATASTORE.target,
            "selected_columns": None,
        }

    sample_df = df.head(max_rows)
    headers = [str(c) for c in sample_df.columns]
    rows = sample_df.to_dict(orient="records")

    return {
        "ok": True,
        "headers": headers,
        "rows": rows,
        "target": DATASTORE.target,
        "selected_columns": None,
    }

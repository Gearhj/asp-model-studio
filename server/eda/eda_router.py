# server/eda/eda_router.py
# =============================================================================
# EDA Router – tabular summaries + D3 endpoints
# =============================================================================

from __future__ import annotations

from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Query, Body

from ..core.dataset_store import DATASTORE
from .eda_service import eda_service

router = APIRouter()


def _require_df():
    df = DATASTORE.get_active_df()
    if df is not None:
        return df
    raise HTTPException(status_code=400, detail="No dataset loaded.")


# ---------------------------------------------------------------------------
# Tabular endpoints (may be used by other steps)
# ---------------------------------------------------------------------------
@router.get("/overview")
def eda_overview():
    df = _require_df()
    return eda_service.dataset_overview(df)


@router.get("/numeric_summary")
def numeric_summary():
    df = _require_df()
    return eda_service.numeric_summary(df)


@router.get("/missing")
def missing_summary():
    df = _require_df()
    return eda_service.missing_summary(df)


@router.get("/histogram/{column}")
def histogram(column: str, bins: int = 40):
    df = _require_df()
    return eda_service.histogram(df, column, bins=bins)


@router.get("/boxplot/{column}")
def boxplot(column: str):
    df = _require_df()
    return eda_service.boxplot_stats(df, column)


@router.get("/correlation")
def correlation():
    df = _require_df()
    return eda_service.correlation_matrix(df)


@router.get("/sample")
def sample(max_rows: int = 10000):
    df = _require_df()
    return eda_service.sample_records(df, max_rows=max_rows)


# ---------------------------------------------------------------------------
# D3 Histogram – POST /api/eda/d3_histogram
# ---------------------------------------------------------------------------
@router.post("/d3_histogram")
def d3_histogram(payload: Dict[str, Any] = Body(...)):
    df = _require_df()
    feature = payload.get("feature") or ""
    bins = int(payload.get("bins") or 20)
    sample_pct = int(payload.get("sample_pct") or 10)

    if not feature:
        raise HTTPException(status_code=400, detail="Feature is required.")

    res = eda_service.d3_histogram(
        df,
        feature=feature,
        target=DATASTORE.target,
        bins=bins,
        sample_pct=sample_pct,
    )
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "Histogram failed."))
    return res


# ---------------------------------------------------------------------------
# Boxplot image – GET /api/eda/boxplot?feature=...&sample_pct=10
# ---------------------------------------------------------------------------
@router.get("/boxplot")
def boxplot_image(
    feature: str = Query(..., description="Numeric feature to visualize"),
    sample_pct: int = Query(10, ge=1, le=100),
):
    df = _require_df()
    res = eda_service.boxplot_image(df, feature=feature, sample_pct=sample_pct)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "Boxplot failed."))
    return res


# ---------------------------------------------------------------------------
# Correlation heatmap – GET /api/eda/corr?sample_pct=10
# ---------------------------------------------------------------------------
@router.get("/corr")
def corr_heatmap(
    sample_pct: int = Query(10, ge=1, le=100),
    limit: int = Query(20, ge=2, le=20),
):
    df = _require_df()
    res = eda_service.corr_heatmap_image(df, sample_pct=sample_pct, limit=limit)
    if not res.get("ok"):
        # frontend treats missing image as "Not enough numeric columns"
        return {"ok": False, "error": res.get("error", "Heatmap failed.")}
    return res


# ---------------------------------------------------------------------------
# Pairplot – GET /api/eda/pairplot?sample_pct=10
# ---------------------------------------------------------------------------
@router.get("/pairplot")
def pairplot(sample_pct: int = Query(10, ge=1, le=100)):
    df = _require_df()
    res = eda_service.pairplot_image(df, sample_pct=sample_pct)
    if not res.get("ok"):
        # frontend treats missing image as generic failure
        return {"ok": False, "error": res.get("error", "Pairplot failed.")}
    return res

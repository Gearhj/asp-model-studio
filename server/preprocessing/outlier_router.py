# server/preprocessing/outlier_router.py
# =============================================================================
# Outlier Router for DS Workflow (Modular Backend)
# =============================================================================
# Exposes REST endpoint(s) for Step03 Outliers.
#
#   POST /api/outliers/summary
#
# Uses the global DATASTORE singleton to fetch the current dataset, then
# delegates to OutlierService for the actual logic.
# =============================================================================

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.dataset_store import DATASTORE
from .outlier_service import outlier_service


router = APIRouter()


class OutlierRequest(BaseModel):
    method: str = Field("iqr", description="iqr|zscore")
    z_thresh: float = 3.0


def _require_df():
    """
    Helper to get a DataFrame from DATASTORE.
    For now, we prefer the processed_df if present, otherwise raw_df.
    """
    if DATASTORE.processed_df is not None:
        return DATASTORE.processed_df
    if DATASTORE.raw_df is not None:
        return DATASTORE.raw_df
    raise HTTPException(status_code=400, detail="No dataset loaded.")


@router.post("/summary")
def outliers_summary(req: OutlierRequest):
    """
    Summarize numeric outliers for each column using IQR or z-score method.

    Response structure is compatible with the original monolithic backend:
    {
      "ok": True,
      "rows": [
        {"column": "AGE", "method": "iqr", "count": 123, "pct": 0.045},
        ...
      ]
    }
    """
    df = _require_df()
    return outlier_service.summary(df, method=req.method, z_thresh=req.z_thresh)

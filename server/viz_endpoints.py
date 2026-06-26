# server/viz_endpoints.py
from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Any, Dict
from .plots import roc_png, pr_png, decile_lift

router = APIRouter()

@router.post("/api/plots/roc")
def api_plot_roc(payload: Dict[str, Any] = Body(...)):
    img = roc_png(
        y=payload.get("y"),
        yhat=payload.get("yhat"),
        roc_x=payload.get("roc", {}).get("x"),
        roc_y=payload.get("roc", {}).get("y"),
        f1_fpr=payload.get("markers", {}).get("f1_fpr"),
        maxp_fpr=payload.get("markers", {}).get("maxp_fpr"),
        maxr_fpr=payload.get("markers", {}).get("maxr_fpr"),
        auc=payload.get("auc"),
    )
    return StreamingResponse(iter([img]), media_type="image/png")

@router.post("/api/plots/pr")
def api_plot_pr(payload: Dict[str, Any] = Body(...)):
    img = pr_png(
        y=payload.get("y"),
        yhat=payload.get("yhat"),
        pr_x=payload.get("pr", {}).get("x"),
        pr_y=payload.get("pr", {}).get("y"),
        f1_rec=payload.get("markers", {}).get("f1_rec"),
        maxp_rec=payload.get("markers", {}).get("maxp_rec"),
        maxr_rec=payload.get("markers", {}).get("maxr_rec"),
    )
    return StreamingResponse(iter([img]), media_type="image/png")

@router.post("/api/metrics/deciles")
def api_deciles(payload: Dict[str, Any] = Body(...)):
    y = payload.get("y")
    yhat = payload.get("yhat")
    if not y or not yhat or len(y) != len(yhat):
        return JSONResponse({"error": "y and yhat required and must be equal length"}, status_code=422)
    return JSONResponse(decile_lift(y, yhat))

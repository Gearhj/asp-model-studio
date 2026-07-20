from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core.session_checkpoint import save_checkpoint
from .bureau_detection_service import detect_bureau_data
from .bureau_detection_types import BureauDetectionRequest


router = APIRouter()


@router.post("/data/bureau-detection")
def bureau_detection(request: BureauDetectionRequest):
    try:
        result = detect_bureau_data(request)
        save_checkpoint()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


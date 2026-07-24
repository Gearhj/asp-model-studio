from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from ..core.modeling_scope import authorize_modeling_scope
from ..core.session_checkpoint import schedule_checkpoint_save
from ..security.security_store import require_user
from .bureau_detection_service import detect_bureau_data
from .bureau_detection_types import BureauDetectionRequest


router = APIRouter()


@router.post("/data/bureau-detection")
def bureau_detection(request: BureauDetectionRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "edit")
    try:
        result = detect_bureau_data(request)
        schedule_checkpoint_save()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


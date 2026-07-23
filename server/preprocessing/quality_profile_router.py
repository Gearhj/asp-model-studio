from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from ..core.modeling_scope import authorize_modeling_scope
from ..security.security_store import require_user
from .data_profile_types import DataProfileRequest
from .quality_profile_service import profile_active_dataset


router = APIRouter()


@router.post("/data/quality-profile")
def quality_profile(request: DataProfileRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "view")
    try:
        return profile_active_dataset(request.target, request.event_value)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


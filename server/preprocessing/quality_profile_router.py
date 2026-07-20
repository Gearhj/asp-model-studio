from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .data_profile_types import DataProfileRequest
from .quality_profile_service import profile_active_dataset


router = APIRouter()


@router.post("/data/quality-profile")
def quality_profile(request: DataProfileRequest):
    try:
        return profile_active_dataset(request.target, request.event_value)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


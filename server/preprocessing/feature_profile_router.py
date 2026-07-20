from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .data_profile_types import FeatureProfileRequest
from .feature_profile_service import profile_features


router = APIRouter()


@router.post("/data/feature-profile")
def feature_profile(request: FeatureProfileRequest):
    try:
        return profile_features(request.target, request.event_value, request.problem_type)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


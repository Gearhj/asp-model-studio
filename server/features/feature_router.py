from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .feature_service import delete_feature, get_manifest, materialize_manifest, preview_features, update_manifest
from .feature_types import FeatureManifestUpdateRequest, FeatureMaterializeRequest, FeaturePreviewRequest


router = APIRouter()


@router.get("/features/manifest")
def feature_manifest():
    try:
        return get_manifest()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/features/manifest")
def save_feature_manifest(request: FeatureManifestUpdateRequest):
    try:
        return update_manifest(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/features/preview")
def feature_preview(request: FeaturePreviewRequest):
    try:
        return preview_features(request.features, request.preview_limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/features/materialize")
def feature_materialize(request: FeatureMaterializeRequest):
    try:
        return materialize_manifest(request.manifest_version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/features/{feature_id}")
def remove_feature(feature_id: str):
    try:
        return delete_feature(feature_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


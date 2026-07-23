from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.modeling_scope import authorize_modeling_scope
from ..security.security_store import require_user
from .feature_service import delete_feature, get_manifest, materialize_manifest, preview_features, update_manifest
from .feature_types import FeatureManifestUpdateRequest, FeatureMaterializeRequest, FeaturePreviewRequest


router = APIRouter()


@router.get("/features/manifest")
def feature_manifest(project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    try:
        return get_manifest()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/features/manifest")
def save_feature_manifest(request: FeatureManifestUpdateRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "edit")
    try:
        return update_manifest(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/features/preview")
def feature_preview(request: FeaturePreviewRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "view")
    try:
        return preview_features(request.features, request.preview_limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/features/materialize")
def feature_materialize(request: FeatureMaterializeRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "edit")
    try:
        return materialize_manifest(request.manifest_version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/features/{feature_id}")
def remove_feature(feature_id: str, project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "edit")
    try:
        return delete_feature(feature_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


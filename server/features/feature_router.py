from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.modeling_scope import authorize_modeling_scope
from ..security.security_store import audit_event, require_user
from .feature_service import (
    confirm_manifest,
    delete_feature,
    get_manifest,
    materialize_manifest,
    preview_features,
    update_manifest,
)
from .feature_types import (
    FeatureConfirmRequest,
    FeatureManifestUpdateRequest,
    FeatureMaterializeRequest,
    FeaturePreviewRequest,
)


router = APIRouter()


@router.get("/features/manifest")
def feature_manifest(
    project_id: str = Query(...),
    expected_dataset_id: str = Query(""),
    expected_dataset_version_id: str = Query(""),
    dataset_version: str = Query(""),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    try:
        return get_manifest(
            project_id,
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_dataset_version_id,
            legacy_dataset_version=dataset_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/features/manifest")
def save_feature_manifest(request: FeatureManifestUpdateRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "edit")
    try:
        result = update_manifest(request)
        audit_event(
            "modeling.feature_manifest.saved",
            "project",
            request.project_id,
            "success",
            metadata={
                "projectId": request.project_id,
                "manifestHash": result.get("manifest_hash"),
                "featureCount": len(result.get("features") or []),
                "validationStatus": result.get("validation_status"),
            },
            user_id=user.get("userId"),
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/features/preview")
def feature_preview(request: FeaturePreviewRequest, user: Dict[str, Any] = Depends(require_user)):
    # Preview persists a governed preview hash and refreshed manifest, so it
    # is a mutation even though it does not materialize the feature frame.
    authorize_modeling_scope(user, request.project_id, "edit")
    try:
        result = preview_features(
            request.features,
            request.preview_limit,
            request.manifest_version,
            project_id=request.project_id,
            expected_dataset_id=request.dataset_id,
            expected_dataset_version_id=request.dataset_version_id,
            legacy_dataset_version=request.dataset_version,
        )
        audit_event(
            "modeling.feature_manifest.previewed",
            "project",
            request.project_id,
            "success",
            metadata={
                "projectId": request.project_id,
                "manifestHash": result.get("manifest_hash"),
                "previewHash": result.get("preview_hash"),
                "previewRows": result.get("rows"),
            },
            user_id=user.get("userId"),
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/features/materialize")
def feature_materialize(request: FeatureMaterializeRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "edit")
    try:
        result = materialize_manifest(
            request.manifest_version,
            request.preview_hash,
            project_id=request.project_id,
            expected_dataset_id=request.dataset_id,
            expected_dataset_version_id=request.dataset_version_id,
            legacy_dataset_version=request.dataset_version,
        )
        audit_event(
            "modeling.feature_manifest.materialized",
            "project",
            request.project_id,
            "success",
            metadata={
                "projectId": request.project_id,
                "manifestHash": result.get("manifest_hash"),
                "materializationHash": result.get("materialization_hash"),
                "materializedRows": result.get("rows"),
            },
            user_id=user.get("userId"),
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/features/confirm")
def feature_confirm(request: FeatureConfirmRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "edit")
    try:
        result = confirm_manifest(
            request.manifest_version,
            request.materialization_hash,
            project_id=request.project_id,
            expected_dataset_id=request.dataset_id,
            expected_dataset_version_id=request.dataset_version_id,
            legacy_dataset_version=request.dataset_version,
        )
        audit_event(
            "modeling.feature_manifest.confirmed",
            "project",
            request.project_id,
            "success",
            metadata={
                "projectId": request.project_id,
                "manifestHash": result.get("manifest_hash"),
                "materializationHash": result.get("materialization_hash"),
                "confirmationStatus": result.get("confirmation_status"),
            },
            user_id=user.get("userId"),
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/features/{feature_id}")
def remove_feature(
    feature_id: str,
    project_id: str = Query(...),
    expected_dataset_id: str = Query(""),
    expected_dataset_version_id: str = Query(""),
    dataset_version: str = Query(""),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "edit")
    try:
        result = delete_feature(
            feature_id,
            project_id,
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_dataset_version_id,
            legacy_dataset_version=dataset_version,
        )
        audit_event(
            "modeling.feature_manifest.feature_removed",
            "project",
            project_id,
            "success",
            metadata={
                "projectId": project_id,
                "featureId": feature_id,
                "manifestHash": result.get("manifest_hash"),
            },
            user_id=user.get("userId"),
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

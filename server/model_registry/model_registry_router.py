"""ATLAS Durable Model Registry -- HTTP routes (Phase D)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..security.security_store import require_user
from . import model_registry_service as REGISTRY

router = APIRouter(dependencies=[Depends(require_user)])


@router.get("/models")
def list_models(
    project_id: str = Query(..., alias="projectId"),
    problem_type: Optional[str] = Query(None, alias="problemType"),
    status: Optional[str] = Query(None),
    owner_user_id: Optional[str] = Query(None, alias="ownerUserId"),
    include_archived: bool = Query(False, alias="includeArchived"),
    limit: int = Query(200),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    models = REGISTRY.list_models(
        user, project_id, problem_type=problem_type, status=status, owner_user_id=owner_user_id,
        include_archived=include_archived, limit=limit,
    )
    return {"ok": True, "models": models, "count": len(models)}


@router.get("/model-versions/compare")
def compare_model_versions(ids: str = Query(..., description="Comma-separated modelVersionIds"), user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    model_version_ids: List[str] = [value.strip() for value in ids.split(",") if value.strip()]
    return {"ok": True, **REGISTRY.compare_versions(user, model_version_ids)}


@router.get("/model-versions/resolve-current")
def resolve_current_version(
    project_id: str = Query(..., alias="projectId"),
    dataset_id: str = Query(..., alias="datasetId"),
    dataset_version_id: str = Query(..., alias="datasetVersionId"),
    target_name: str = Query(..., alias="targetName"),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    return {
        "ok": True,
        "resolution": REGISTRY.resolve_current_version_by_exact_context(
            user,
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
            target_name=target_name,
        ),
    }


@router.get("/models/{model_id}")
def get_model(model_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "model": REGISTRY.get_model(user, model_id)}


@router.get("/models/{model_id}/versions")
def list_versions(
    model_id: str,
    algorithm: Optional[str] = Query(None),
    approval_status: Optional[str] = Query(None, alias="approvalStatus"),
    validation_status: Optional[str] = Query(None, alias="validationStatus"),
    include_archived: bool = Query(False, alias="includeArchived"),
    limit: int = Query(200),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    versions = REGISTRY.list_versions(
        user, model_id, algorithm=algorithm, approval_status=approval_status,
        validation_status=validation_status, include_archived=include_archived, limit=limit,
    )
    return {"ok": True, "modelVersions": versions, "count": len(versions)}


@router.post("/models/{model_id}/archive")
def archive_model(model_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "model": REGISTRY.archive_model(user, model_id)}


@router.post("/models/{model_id}/champion")
def promote_champion(
    model_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    model_version_id = str(payload.get("modelVersionId") or "").strip()
    if not model_version_id:
        raise HTTPException(status_code=422, detail="modelVersionId is required.")
    return {
        "ok": True,
        "model": REGISTRY.promote_champion(
            user,
            model_id,
            model_version_id,
            expected_generation=payload.get("expectedGeneration"),
        ),
    }


@router.get("/model-versions/{model_version_id}")
def get_version(model_version_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "modelVersion": REGISTRY.get_version(user, model_version_id)}


@router.get("/model-versions/{model_version_id}/recovery-status")
def recovery_status(
    model_version_id: str,
    project_id: str = Query(..., alias="projectId"),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    return {
        "ok": True,
        "recovery": REGISTRY.get_recovery_status(
            user,
            project_id,
            model_version_id,
        ),
    }


@router.post("/model-versions/{model_version_id}/archive")
def archive_version(model_version_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "modelVersion": REGISTRY.archive_version(user, model_version_id)}


@router.post("/model-versions/{model_version_id}/governance-status")
def set_governance_status(model_version_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "modelVersion": REGISTRY.set_governance_status(
        user, model_version_id,
        approval_status=payload.get("approvalStatus"), validation_status=payload.get("validationStatus"),
        documentation_status=payload.get("documentationStatus"),
    )}


@router.get("/model-versions/{model_version_id}/documentation-bundle")
def documentation_bundle(model_version_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Phase I: Documentation Studio integration point. Read-only aggregation
    -- never writes into the documentation subsystem, never redesigns it.
    Returns everything a documentation package needs to cite: model metadata,
    hyperparameters, metrics, feature manifest reference, evaluation/
    interpretation summaries (captured at Save-Final-Model time), plus the
    Scoring Runs and Evidence items that reference this exact version."""
    from ..persistence.service import get_persistence_service

    version = REGISTRY.get_version(user, model_version_id)
    model = REGISTRY.get_model(user, version["modelId"])
    service = get_persistence_service()
    # Filter in Python, not via the repository's model_id kwarg -- scoring_runs.model_id
    # holds the display-friendly algorithm key (e.g. "logreg"), not this registry's
    # modelId format; model_version_id is the real FK added in this phase.
    project_scoring_runs = service.scoring_runs.list(project_id=version.get("projectId"), include_archived=True, limit=200)
    scoring_runs = [row for row in project_scoring_runs if row.get("model_version_id") == model_version_id]
    evidence_items = []
    if version.get("projectId"):
        evidence_items = [
            item for item in service.evidence.list_for_project(version["projectId"])
            if (item.get("payload_json") or {}).get("modelVersionId") == model_version_id
        ]
    return {
        "ok": True,
        "model": model,
        "modelVersion": version,
        "scoringRuns": [
            {
                "scoringRunId": row["scoring_run_id"], "partition": row.get("partition"), "status": row.get("status"),
                "rowCount": row.get("row_count"), "createdAt": row.get("created_at"),
            }
            for row in scoring_runs
        ],
        "evidence": [
            {"evidenceId": item.get("evidence_id"), "title": item.get("title"), "status": item.get("status"), "createdAt": item.get("created_at")}
            for item in evidence_items
        ],
    }

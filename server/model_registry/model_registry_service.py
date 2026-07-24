"""ATLAS Durable Model Registry -- domain service.

This is the ONLY place a Model or ModelVersion row is created, read, listed,
compared, or archived. Every entry point re-authorizes via
authorize_modeling_scope, exactly like scoring_run_service.py and every other
ATLAS modeling endpoint -- a model's projectId is never trusted as its own
authorization signal.

A ModelVersion is immutable once created (Phase B requirement): create_model_
version() is the only path that INSERTs a model_versions row, and
ModelVersionRepository has no update-content method -- only
set_governance_status() (approval/validation/documentation stage transitions,
not content) and archive() exist as post-creation mutations.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from ..core.modeling_scope import authorize_modeling_scope
from ..persistence.db import now_iso
from ..persistence.service import get_persistence_service
from . import model_artifacts

TERMINAL_APPROVAL_STATUSES = {"approved", "rejected"}


def new_model_id() -> str:
    return f"model-{uuid.uuid4().hex[:16]}"


def new_model_version_id() -> str:
    return f"mv-{uuid.uuid4().hex[:16]}"


def _camel(key: str) -> str:
    import re

    return re.sub(r"_([a-z0-9])", lambda match: match.group(1).upper(), key)


def _to_api(record: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in record.items():
        output_key = key[:-5] if key.endswith("_json") else key
        result[_camel(output_key)] = value
    return result


def _get_or_create_model(
    service, user: Dict[str, Any], project_id: str, name: str, problem_type: Optional[str],
) -> Dict[str, Any]:
    existing = service.models.find_by_name(project_id, name)
    if existing:
        return existing
    timestamp = now_iso()
    record = {
        "model_id": new_model_id(),
        "project_id": project_id,
        "name": name,
        "problem_type": problem_type,
        "status": "active",
        "owner_user_id": str(user.get("userId") or ""),
        "created_at": timestamp,
        "updated_at": timestamp,
        "current_version_id": None,
        "archived": False,
        "archived_at": None,
        "tags_json": [],
        "description": None,
    }
    return service.models.upsert(record)


def create_model_version(
    user: Dict[str, Any],
    project_id: str,
    *,
    model_name: str,
    problem_type: Optional[str],
    algorithm: str,
    algorithm_version: Optional[str],
    fitted_object: Any,
    hyperparameters: Optional[Dict[str, Any]] = None,
    training_parameters: Optional[Dict[str, Any]] = None,
    metrics_summary: Optional[Dict[str, Any]] = None,
    evaluation_summary: Optional[Dict[str, Any]] = None,
    interpretation_summary: Optional[Dict[str, Any]] = None,
    training_run_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    dataset_version_id: Optional[str] = None,
    feature_manifest_version: Optional[str] = None,
    training_timestamp: Optional[str] = None,
    lineage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The Phase E entry point: called from eval_service.py's "Save Final
    Model" actions (save_selected_model_as_final / save_rfe_model). Creates
    (or reuses) the parent Model, serializes the fitted object to a governed,
    immutable artifact, INSERTs one new immutable ModelVersion row, and points
    the parent Model's currentVersionId at it. Returns the durable
    {modelId, modelVersionId} pair callers (Scoring, Evidence, Visual
    Intelligence) reference from now on -- never a timestamp string."""
    authorize_modeling_scope(user, project_id, "edit")
    service = get_persistence_service()
    model = _get_or_create_model(service, user, project_id, model_name, problem_type)
    model_version_id = new_model_version_id()
    artifact = model_artifacts.write_model_artifact(model_version_id, fitted_object)
    version_number = service.model_versions.next_version_number(model["model_id"])
    timestamp = now_iso()
    record = {
        "model_version_id": model_version_id,
        "model_id": model["model_id"],
        "version_number": version_number,
        "training_run_id": training_run_id,
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "feature_manifest_version": feature_manifest_version,
        "algorithm": algorithm,
        "algorithm_version": algorithm_version,
        "hyperparameters_json": hyperparameters or {},
        "training_parameters_json": training_parameters or {},
        "metrics_summary_json": metrics_summary or {},
        "evaluation_summary_json": evaluation_summary or {},
        "interpretation_summary_json": interpretation_summary or {},
        "artifact_reference": artifact["path"],
        "artifact_format": artifact["format"],
        "training_timestamp": training_timestamp or timestamp,
        "checksum": artifact["checksum"],
        "approval_status": "unreviewed",
        "validation_status": "not_validated",
        "documentation_status": "not_documented",
        "lineage_json": {
            "projectId": project_id,
            "datasetId": dataset_id,
            "datasetVersionId": dataset_version_id,
            "trainingRunId": training_run_id,
            "featureManifestVersion": feature_manifest_version,
            **(lineage or {}),
        },
        "created_by": str(user.get("userId") or ""),
        "created_at": timestamp,
    }
    saved_version = service.model_versions.insert(record)
    model["current_version_id"] = model_version_id
    model["updated_at"] = timestamp
    saved_model = service.models.upsert(model)
    return {"model": _to_api(saved_model), "modelVersion": _to_api(saved_version)}


def list_models(user: Dict[str, Any], project_id: str, **filters: Any) -> List[Dict[str, Any]]:
    authorize_modeling_scope(user, project_id, "view")
    service = get_persistence_service()
    rows = service.models.list(project_id=project_id, **filters)
    return [_to_api(row) for row in rows]


def _get_model_authorized(user: Dict[str, Any], model_id: str) -> Dict[str, Any]:
    service = get_persistence_service()
    row = service.models.get(model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    if row.get("project_id"):
        authorize_modeling_scope(user, row["project_id"], "view")
    return row


def get_model(user: Dict[str, Any], model_id: str) -> Dict[str, Any]:
    return _to_api(_get_model_authorized(user, model_id))


def list_versions(user: Dict[str, Any], model_id: str, **filters: Any) -> List[Dict[str, Any]]:
    _get_model_authorized(user, model_id)
    service = get_persistence_service()
    rows = service.model_versions.list(model_id=model_id, **filters)
    return [_to_api(row) for row in rows]


def _get_version_authorized(user: Dict[str, Any], model_version_id: str) -> Dict[str, Any]:
    service = get_persistence_service()
    row = service.model_versions.get(model_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model version not found.")
    if row.get("project_id"):
        authorize_modeling_scope(user, row["project_id"], "view")
    return row


def get_version(user: Dict[str, Any], model_version_id: str) -> Dict[str, Any]:
    return _to_api(_get_version_authorized(user, model_version_id))


def load_version_artifact(user: Dict[str, Any], model_version_id: str) -> Any:
    """Loads the actual fitted object back into memory -- used by the scoring
    fallback path when RESULTS.final_model is unavailable (e.g. after a
    process restart) but a durable ModelVersion + artifact exist."""
    row = _get_version_authorized(user, model_version_id)
    if not row.get("artifact_reference"):
        raise HTTPException(status_code=409, detail="This model version has no stored artifact.")
    return model_artifacts.load_model_artifact(row["artifact_reference"])


def archive_model(user: Dict[str, Any], model_id: str) -> Dict[str, Any]:
    row = _get_model_authorized(user, model_id)
    service = get_persistence_service()
    timestamp = now_iso()
    row["archived"] = True
    row["archived_at"] = timestamp
    row["updated_at"] = timestamp
    saved = service.models.upsert(row)
    return _to_api(saved)


def archive_version(user: Dict[str, Any], model_version_id: str) -> Dict[str, Any]:
    """Archiving a version preserves lineage (Phase L) -- the row and its
    artifact are never deleted, only marked archived_at. If this was the
    parent Model's current version, the Model's currentVersionId is honestly
    cleared rather than left silently pointing at an archived version."""
    row = _get_version_authorized(user, model_version_id)
    service = get_persistence_service()
    archived = service.model_versions.archive(model_version_id)
    model = service.models.get(row["model_id"])
    if model and model.get("current_version_id") == model_version_id:
        model["current_version_id"] = None
        model["updated_at"] = now_iso()
        service.models.upsert(model)
    return _to_api(archived or row)


def compare_versions(user: Dict[str, Any], model_version_ids: List[str]) -> Dict[str, Any]:
    if len(model_version_ids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least two modelVersionIds to compare.")
    if len(model_version_ids) > 10:
        raise HTTPException(status_code=400, detail="Cannot compare more than 10 model versions at once.")
    rows = [_get_version_authorized(user, version_id) for version_id in model_version_ids]
    return {
        "versions": [
            {
                "modelVersionId": row["model_version_id"],
                "modelId": row["model_id"],
                "versionNumber": row["version_number"],
                "algorithm": row.get("algorithm"),
                "algorithmVersion": row.get("algorithm_version"),
                "hyperparameters": row.get("hyperparameters_json"),
                "metricsSummary": row.get("metrics_summary_json"),
                "datasetId": row.get("dataset_id"),
                "datasetVersionId": row.get("dataset_version_id"),
                "featureManifestVersion": row.get("feature_manifest_version"),
                "trainingTimestamp": row.get("training_timestamp"),
                "lineage": row.get("lineage_json"),
                "approvalStatus": row.get("approval_status"),
                "validationStatus": row.get("validation_status"),
            }
            for row in rows
        ]
    }


def set_governance_status(
    user: Dict[str, Any], model_version_id: str, *,
    approval_status: Optional[str] = None, validation_status: Optional[str] = None, documentation_status: Optional[str] = None,
) -> Dict[str, Any]:
    _get_version_authorized(user, model_version_id)
    service = get_persistence_service()
    updated = service.model_versions.set_governance_status(
        model_version_id, approval_status=approval_status, validation_status=validation_status, documentation_status=documentation_status,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Model version not found.")
    return _to_api(updated)


def archive_registry_for_project(project_id: str) -> Dict[str, int]:
    """Project-deletion lifecycle hook (Phase L, mirroring Phase I from the
    Persistent Scoring Runs phase) -- archives (never deletes) every Model and
    ModelVersion belonging to the project. Scoring Runs, Evidence, and
    Dataset Versions referencing an archived model/version are untouched."""
    service = get_persistence_service()
    versions_archived = service.model_versions.archive_for_project(project_id)
    models_archived = service.models.archive_for_project(project_id)
    return {"modelsArchived": models_archived, "versionsArchived": versions_archived}

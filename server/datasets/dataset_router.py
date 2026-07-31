from __future__ import annotations

from typing import Any, Dict, Optional
import pandas as pd

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi import Depends
from pydantic import BaseModel

from .dataset_registry import (
    add_dataset_version,
    archive_dataset,
    create_dataset_from_upload,
    create_metadata_only_dataset,
    current_user,
    dataset_access,
    diagnostics,
    find_similar_datasets,
    latest_version_id,
    link_project,
    list_accessible_datasets,
    list_users,
    list_versions,
    project_dataset_links,
    read_version_artifact,
    register_workspace_dataset,
    require_dataset,
    grant_dataset_access,
    revoke_dataset_access,
    share_dataset,
    switch_user,
    unlink_project_dataset,
    ARTIFACT_ROOT,
)
from .dataset_identity import (
    resolve_project_dataset_identity,
    stamp_active_dataset_identity,
)
from ..core.dataset_store import DATASTORE
from ..core.modeling_scope import authorize_modeling_scope
from ..core.pretraining_invalidation import invalidate_downstream_training_state
from ..core.result_store import RESULTS
from ..core.session_checkpoint import schedule_checkpoint_save
from ..security.security_store import require_user, user_can_access_project, audit_event


router = APIRouter(dependencies=[Depends(require_user)])


class RegisterDatasetRequest(BaseModel):
    name: str
    description: str = ""
    domain: str = "General"
    sourceType: str = "registered"
    sourceInfo: Dict[str, Any] = {}


class ShareDatasetRequest(BaseModel):
    grants: list[Dict[str, str]] = []


class DatasetGrantRequest(BaseModel):
    userId: str
    role: str = "viewer"


class LinkDatasetRequest(BaseModel):
    datasetId: str
    versionId: str
    datasetRole: str = "modeling"


class SwitchUserRequest(BaseModel):
    userId: str


class RegisterWorkspaceDatasetRequest(BaseModel):
    projectId: str
    name: str
    description: str = ""
    domain: str = "General"
    tags: list[str] = []


@router.get("/users/current")
def get_current_user() -> Dict[str, Any]:
    return {"ok": True, "user": current_user()}


@router.get("/users")
def get_users() -> Dict[str, Any]:
    return {"ok": True, "users": list_users(), "currentUser": current_user()}


@router.post("/users/switch-dev-user")
def post_switch_user(payload: SwitchUserRequest) -> Dict[str, Any]:
    return {"ok": False, "error": "Development user switching was replaced by sign-in/sign-out authentication."}


@router.get("/datasets")
def get_datasets(include_archived: bool = False) -> Dict[str, Any]:
    return {"ok": True, "datasets": list_accessible_datasets(include_archived=include_archived), "currentUser": current_user()}


@router.get("/datasets/similar")
def get_similar_datasets(
    name: str = Query(""),
    target: Optional[str] = Query(None),
    row_count: Optional[int] = Query(None),
    column_count: Optional[int] = Query(None),
) -> Dict[str, Any]:
    """Reviewable duplicate suggestions for the Data Acquisition registration flow --
    never used to auto-substitute a different asset (dataset lifecycle audit, Phase 4 item 9).
    MUST be registered before /datasets/{dataset_id} -- FastAPI/Starlette route matching is
    registration-order-based, not specificity-based, so a literal "similar" segment placed
    after the {dataset_id} path-param route would be swallowed by it as dataset_id="similar"."""
    return {"ok": True, "candidates": find_similar_datasets(name, target, row_count, column_count)}


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str) -> Dict[str, Any]:
    dataset = require_dataset(dataset_id)
    return {"ok": True, "dataset": dataset}


@router.post("/datasets/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    description: str = Form(""),
    domain: str = Form("General"),
    sourceType: str = Form("upload"),
) -> Dict[str, Any]:
    dataset = await create_dataset_from_upload(file=file, name=name, description=description, domain=domain, source_type=sourceType)
    return {"ok": True, "dataset": dataset}


@router.post("/datasets/register")
def register_dataset(payload: RegisterDatasetRequest) -> Dict[str, Any]:
    dataset = create_metadata_only_dataset(payload.dict())
    return {"ok": True, "dataset": dataset}


@router.post("/datasets/register-workspace")
def register_workspace(payload: RegisterWorkspaceDatasetRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Register the CURRENT project's already-uploaded workspace dataset (DATASTORE
    state, transformed or not) as a durable, versioned Dataset Library asset linked
    to this project. Previously missing path -- see docs/architecture/DATASET_LIFECYCLE_ADR.md."""
    authorize_modeling_scope(user, payload.projectId, "edit")
    scoped_store = DATASTORE.current()
    scoped_results = RESULTS.current()
    with scoped_store.state_lock:
        active = scoped_store.get_active_df()
        if active is None or active.empty:
            raise HTTPException(status_code=400, detail="Upload a dataset in this project before registering it to the Dataset Library.")
        df = active.copy()
        source = (
            dict(scoped_store.meta.get("source"))
            if isinstance(scoped_store.meta.get("source"), dict)
            else {}
        )
        target = scoped_store.target
        starting_revision = int(scoped_store.data_revision)
    dataset = register_workspace_dataset(
        df,
        name=payload.name,
        project_id=payload.projectId,
        description=payload.description,
        domain=payload.domain,
        tags=payload.tags,
        target=target,
        source_meta=source,
    )
    dataset_id = str(dataset.get("datasetId") or "")
    dataset_version_id = str(
        dataset.get("created_dataset_version_id")
        or dataset.get("createdDatasetVersionId")
        or ""
    )
    if not dataset_id or not dataset_version_id:
        raise HTTPException(
            status_code=500,
            detail=(
                "Dataset registration did not return the exact immutable "
                "version created by this operation."
            ),
        )
    identity = resolve_project_dataset_identity(
        payload.projectId,
        dataset_id,
        dataset_version_id,
        user=user,
    )
    with scoped_store.state_lock:
        if int(scoped_store.data_revision) != starting_revision:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The workspace dataset changed while registration was in "
                    "progress. Register the current dataset again."
                ),
            )
        canonical = stamp_active_dataset_identity(identity, store=scoped_store)
        scoped_store.meta["source"] = {
            "kind": "dataset_library",
            "dataset_id": canonical["dataset_id"],
            "dataset_version_id": canonical["dataset_version_id"],
            "created_dataset_version_id": dataset_version_id,
            "created_version": dataset.get("created_version"),
            "datasetId": canonical["dataset_id"],
            "versionId": canonical["dataset_version_id"],
            "filename": dataset.get("name"),
            "rows": int(df.shape[0]),
            "columns": int(df.shape[1]),
        }
        invalidate_downstream_training_state(
            "An exact Dataset Library version was activated for the workspace.",
            store=scoped_store,
            result_store=scoped_results,
            split_status="not_created",
        )
    schedule_checkpoint_save()
    return {
        "ok": True,
        "dataset": dataset,
        "project_id": canonical["project_id"],
        "dataset_id": canonical["dataset_id"],
        "dataset_version_id": canonical["dataset_version_id"],
        "created_dataset_version_id": dataset_version_id,
        "created_version": dataset.get("created_version"),
        "datasetId": canonical["dataset_id"],
        "versionId": canonical["dataset_version_id"],
    }


@router.get("/datasets/{dataset_id}/versions")
def get_versions(dataset_id: str) -> Dict[str, Any]:
    return {"ok": True, "versions": list_versions(dataset_id)}


@router.post("/datasets/{dataset_id}/versions")
async def post_version(dataset_id: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    version = await add_dataset_version(dataset_id, file)
    return {"ok": True, "version": version}


@router.get("/datasets/{dataset_id}/versions/{version_id}")
def get_version(dataset_id: str, version_id: str) -> Dict[str, Any]:
    dataset = require_dataset(dataset_id)
    version = next((item for item in dataset.get("versions", []) if item.get("versionId") == version_id), None)
    if not version:
        return {"ok": False, "error": "Version not found."}
    return {"ok": True, "dataset": dataset, "version": version}


@router.get("/datasets/{dataset_id}/profile")
def get_latest_profile(dataset_id: str) -> Dict[str, Any]:
    dataset = require_dataset(dataset_id)
    version_id = latest_version_id(dataset)
    if not version_id:
        return {"ok": True, "profile": None, "dataset": dataset}
    return {"ok": True, "profile": read_version_artifact(dataset_id, version_id, "profile.json", {}), "dataset": dataset, "versionId": version_id}


@router.get("/datasets/{dataset_id}/versions/{version_id}/profile")
def get_profile(dataset_id: str, version_id: str) -> Dict[str, Any]:
    return {"ok": True, "profile": read_version_artifact(dataset_id, version_id, "profile.json", {})}


@router.get("/datasets/{dataset_id}/versions/{version_id}/preview")
def get_preview(dataset_id: str, version_id: str) -> Dict[str, Any]:
    return {"ok": True, "preview": read_version_artifact(dataset_id, version_id, "preview.json", {"rows": [], "columns": []})}


@router.post("/datasets/{dataset_id}/versions/{version_id}/activate")
def activate_dataset_version(dataset_id: str, version_id: str, project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "edit")
    identity = resolve_project_dataset_identity(
        project_id,
        dataset_id,
        version_id,
        user=user,
    )
    dataset = identity["dataset"]
    version = identity["version"]
    path = identity["artifact_path"]
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to load registered dataset version: {exc}") from exc
    scoped_store = DATASTORE.current()
    scoped_results = RESULTS.current()
    with scoped_store.state_lock:
        scoped_store.set_raw(df)
        scoped_store.set_target(None)
        scoped_store.meta["selected_columns"] = [
            str(column) for column in df.columns
        ]
        canonical = stamp_active_dataset_identity(identity, store=scoped_store)
        scoped_store.meta["source"] = {
            "kind": "dataset_library",
            "dataset_id": canonical["dataset_id"],
            "dataset_version_id": canonical["dataset_version_id"],
            "datasetId": canonical["dataset_id"],
            "versionId": canonical["dataset_version_id"],
            "filename": version.get("originalFilename") or dataset.get("name"),
            "rows": int(df.shape[0]),
            "columns": int(df.shape[1]),
        }
        invalidate_downstream_training_state(
            "A different exact Dataset Library version was activated.",
            store=scoped_store,
            result_store=scoped_results,
            split_status="not_created",
            # set_raw already advanced the guarded revision.
            bump_revision=False,
        )
    schedule_checkpoint_save()
    return {
        "ok": True,
        "project_id": canonical["project_id"],
        "dataset_id": canonical["dataset_id"],
        "dataset_version_id": canonical["dataset_version_id"],
        "datasetId": canonical["dataset_id"],
        "versionId": canonical["dataset_version_id"],
        "dataset_version_label": identity.get("dataset_version_label"),
        "dataset_content_hash": identity.get("dataset_content_hash"),
        "dataset_schema_hash": identity.get("dataset_schema_hash"),
        "dataset_source_type": identity.get("dataset_source_type"),
        "datasetVersionLabel": identity.get("dataset_version_label"),
        "datasetContentHash": identity.get("dataset_content_hash"),
        "datasetSchemaHash": identity.get("dataset_schema_hash"),
        "datasetSourceType": identity.get("dataset_source_type"),
        "row_count": int(df.shape[0]),
        "column_count": int(df.shape[1]),
        "headers": [str(column) for column in df.columns],
        "selected_columns": [str(column) for column in df.columns],
    }


@router.post("/datasets/{dataset_id}/share")
def post_share(dataset_id: str, payload: ShareDatasetRequest) -> Dict[str, Any]:
    return {"ok": True, "dataset": share_dataset(dataset_id, payload.grants)}


@router.get("/datasets/{dataset_id}/access")
def get_dataset_access(dataset_id: str) -> Dict[str, Any]:
    return {"ok": True, "access": dataset_access(dataset_id)}


@router.post("/datasets/{dataset_id}/access/grant")
def post_dataset_grant(dataset_id: str, payload: DatasetGrantRequest) -> Dict[str, Any]:
    return {"ok": True, "dataset": grant_dataset_access(dataset_id, payload.userId, payload.role)}


@router.post("/datasets/{dataset_id}/access/revoke")
def post_dataset_revoke(dataset_id: str, payload: DatasetGrantRequest) -> Dict[str, Any]:
    return {"ok": True, "dataset": revoke_dataset_access(dataset_id, payload.userId)}


@router.post("/datasets/{dataset_id}/archive")
def post_archive(dataset_id: str) -> Dict[str, Any]:
    return {"ok": True, "dataset": archive_dataset(dataset_id)}


@router.post("/projects/{project_id}/datasets/link")
def post_project_link(project_id: str, payload: LinkDatasetRequest) -> Dict[str, Any]:
    if not user_can_access_project(project_id, write=True):
        audit_event("access.denied", "project", project_id, "denied", reason="Project ACL denied for dataset link")
        raise HTTPException(status_code=403, detail="You do not have access to link datasets to this project.")
    return {
        "ok": True,
        "link": link_project(project_id, payload.datasetId, payload.versionId, payload.datasetRole),
    }


@router.get("/projects/{project_id}/datasets")
def get_project_links(project_id: str) -> Dict[str, Any]:
    # Dataset lifecycle audit fix: this endpoint had no project-authorization check at
    # all -- any authenticated user could enumerate any project's link count/roles (the
    # linked datasets' own content was already protected by project_dataset_links's
    # internal user_can_access() filter, but the mere existence/count of links was not).
    if not user_can_access_project(project_id):
        audit_event("access.denied", "project", project_id, "denied", reason="Project ACL denied for dataset link listing")
        raise HTTPException(status_code=403, detail="You do not have access to view this project's linked datasets.")
    return {"ok": True, "links": project_dataset_links(project_id)}


@router.delete("/projects/{project_id}/datasets/{dataset_id}")
def delete_project_link(project_id: str, dataset_id: str) -> Dict[str, Any]:
    # Dataset lifecycle audit fix: this endpoint had NO authorization check -- any
    # authenticated user could sever another user's project-dataset link by ID.
    if not user_can_access_project(project_id, write=True):
        audit_event("access.denied", "project", project_id, "denied", reason="Project ACL denied for dataset unlink")
        raise HTTPException(status_code=403, detail="You do not have access to unlink datasets from this project.")
    return unlink_project_dataset(project_id, dataset_id)


@router.get("/system/diagnostics")
def get_system_diagnostics() -> Dict[str, Any]:
    return diagnostics()

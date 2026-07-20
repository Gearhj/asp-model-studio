from __future__ import annotations

from typing import Any, Dict, Optional
import pandas as pd

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
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
    latest_version_id,
    link_project,
    list_accessible_datasets,
    list_users,
    list_versions,
    project_dataset_links,
    read_version_artifact,
    require_dataset,
    grant_dataset_access,
    revoke_dataset_access,
    share_dataset,
    switch_user,
    unlink_project_dataset,
    ARTIFACT_ROOT,
)
from ..core.dataset_store import DATASTORE
from ..core.result_store import RESULTS
from ..core.session_checkpoint import save_checkpoint
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
    versionId: Optional[str] = None
    datasetRole: str = "modeling"


class SwitchUserRequest(BaseModel):
    userId: str


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
def activate_dataset_version(dataset_id: str, version_id: str) -> Dict[str, Any]:
    dataset = require_dataset(dataset_id)
    version = next((item for item in dataset.get("versions", []) if item.get("versionId") == version_id), None)
    if not version:
        raise HTTPException(status_code=404, detail="Dataset version not found.")
    relative_path = version.get("fullDataPath")
    if not relative_path:
        raise HTTPException(status_code=409, detail="This dataset version does not contain a full registered artifact.")
    path = (ARTIFACT_ROOT / str(relative_path)).resolve()
    root = ARTIFACT_ROOT.resolve()
    if root not in path.parents or not path.exists():
        raise HTTPException(status_code=409, detail="The full registered dataset artifact is unavailable.")
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to load registered dataset version: {exc}") from exc
    DATASTORE.set_raw(df)
    DATASTORE.set_target(None)
    DATASTORE.meta["selected_columns"] = [str(column) for column in df.columns]
    DATASTORE.meta["dataset_version"] = version_id
    DATASTORE.meta["source"] = {
        "kind": "dataset_library",
        "datasetId": dataset_id,
        "version": version_id,
        "filename": version.get("originalFilename") or dataset.get("name"),
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
    }
    RESULTS.clear_model_artifacts()
    save_checkpoint()
    return {
        "ok": True,
        "datasetId": dataset_id,
        "versionId": version_id,
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
    return {"ok": True, "links": project_dataset_links(project_id)}


@router.delete("/projects/{project_id}/datasets/{dataset_id}")
def delete_project_link(project_id: str, dataset_id: str) -> Dict[str, Any]:
    return unlink_project_dataset(project_id, dataset_id)


@router.get("/system/diagnostics")
def get_system_diagnostics() -> Dict[str, Any]:
    return diagnostics()

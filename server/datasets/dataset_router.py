from __future__ import annotations

import logging
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
    load_registry,
    read_version_artifact,
    register_workspace_dataset,
    require_dataset,
    grant_dataset_access,
    revoke_dataset_access,
    share_dataset,
    switch_user,
    summarize_dataset,
    unlink_project_dataset,
    user_can_access,
)
from .dataset_identity import (
    invalidate_dataset_identity,
    resolve_registered_version,
    stamp_active_dataset_identity,
)
from ..core.dataset_store import DATASTORE
from ..core.modeling_scope import authorize_modeling_scope
from ..core.pretraining_invalidation import invalidate_downstream_training_state
from ..core.result_store import RESULTS
from ..core.session_checkpoint import schedule_checkpoint_save
from ..persistence.repositories import (
    ProjectDatasetActivationConflictError,
    ProjectDatasetActivationStateError,
)
from ..persistence.repositories.project_dataset_activation_repository import (
    project_dataset_activation_lock,
)
from ..persistence.service import get_persistence_service
from ..security.security_store import audit_event, require_user


router = APIRouter(dependencies=[Depends(require_user)])
LOGGER = logging.getLogger("atlas.dataset_activation")


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


def _authenticated_actor(user: Dict[str, Any]) -> str:
    actor_user_id = str((user or {}).get("userId") or "").strip()
    if not actor_user_id:
        raise HTTPException(
            status_code=401,
            detail="An authenticated user is required for dataset activation.",
        )
    return actor_user_id


def _authorize_dataset_acl_for_link_removal(
    dataset_id: str,
    user: Dict[str, Any],
) -> None:
    """Require Dataset Library visibility before mutating a project link.

    Project edit permission and Dataset Library access are independent grants.
    Return the same not-found response for an absent or inaccessible asset so a
    project collaborator cannot use unlink requests to probe guessed IDs.
    """

    dataset = next(
        (
            item
            for item in (load_registry().get("datasets") or [])
            if isinstance(item, dict)
            and str(item.get("datasetId") or "") == str(dataset_id or "")
        ),
        None,
    )
    if dataset is None or not user_can_access(dataset, user=user):
        audit_event(
            "access.denied",
            "dataset",
            str(dataset_id or ""),
            "denied",
            user_id=(user or {}).get("userId"),
            reason="Dataset ACL denied for project-link removal.",
            metadata={"operation": "project_dataset_unlink"},
        )
        raise HTTPException(
            status_code=404,
            detail="Project dataset link was not found.",
        )


def _link_response(
    link: Dict[str, Any] | None,
    *,
    dataset_version_id: Optional[str] = None,
) -> Dict[str, Any]:
    durable = dict(link or {})
    metadata = (
        durable.get("metadata_json")
        if isinstance(durable.get("metadata_json"), dict)
        else {}
    )
    requested_version = str(
        dataset_version_id
        or metadata.get("lastValidatedVersionId")
        or ""
    )
    role = str(metadata.get("datasetRole") or "modeling")
    return {
        **durable,
        "projectId": durable.get("project_id"),
        "datasetId": durable.get("dataset_id"),
        "versionId": requested_version or None,
        # Compatibility display only. The link authorizes the dataset asset;
        # active_selection is the sole exact-version authority.
        "versionIdRole": "last_validated_compatibility_projection",
        "versionSelectionAuthoritative": False,
        "datasetRole": role,
        "linkStatus": durable.get("link_status"),
        "linkedBy": durable.get("linked_by"),
        "linkedAt": durable.get("linked_at"),
        "updatedAt": durable.get("updated_at"),
    }


def _active_selection_response(selection: Dict[str, Any] | None) -> Dict[str, Any]:
    durable = dict(selection or {})
    return {
        **durable,
        "projectId": durable.get("project_id"),
        "datasetId": durable.get("dataset_id"),
        "datasetVersionId": durable.get("dataset_version_id"),
        "activationRevision": durable.get("activation_revision"),
        "activationStatus": durable.get("activation_status"),
        "activatedBy": durable.get("activated_by"),
        "activatedAt": durable.get("activated_at"),
        "updatedAt": durable.get("updated_at"),
    }


def _mirror_legacy_link(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    dataset_role: str,
) -> None:
    """Maintain the legacy JSON projection without making it authoritative."""
    try:
        link_project(project_id, dataset_id, dataset_version_id, dataset_role)
    except Exception as exc:  # pragma: no cover - projection is best effort
        LOGGER.warning(
            "Durable dataset activation succeeded but legacy link projection failed "
            "for project=%s dataset=%s version=%s: %s",
            project_id,
            dataset_id,
            dataset_version_id,
            exc,
        )


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
    resolved = resolve_registered_version(
        dataset_id,
        dataset_version_id,
        user=user,
    )
    actor_user_id = _authenticated_actor(user)
    activation: Dict[str, Any]
    activation_guard = project_dataset_activation_lock(payload.projectId)
    activation_guard.acquire()
    with scoped_store.state_lock:
        if int(scoped_store.data_revision) != starting_revision:
            activation_guard.release()
            raise HTTPException(
                status_code=409,
                detail=(
                    "The workspace dataset changed while registration was in "
                    "progress. Register the current dataset again."
                ),
            )
        try:
            activation = get_persistence_service().project_dataset_activations.activate_exact(
                project_id=payload.projectId,
                dataset_id=dataset_id,
                dataset_version_id=dataset_version_id,
                actor_user_id=actor_user_id,
                metadata={
                    "datasetRole": "development",
                    "requestedDatasetVersionId": dataset_version_id,
                    "source": "workspace_registration",
                },
            )
        except BaseException:
            activation_guard.release()
            raise
        identity = {
            **resolved,
            "project_id": payload.projectId,
            "project_link": activation.get("link") or {},
            "active_selection": activation.get("active_selection") or {},
            "activation_revision": int(
                (activation.get("active_selection") or {}).get("activation_revision")
                or 0
            ),
        }
        try:
            canonical = stamp_active_dataset_identity(identity, store=scoped_store)
            scoped_store.meta["activation_revision"] = identity["activation_revision"]
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
        except Exception as exc:
            try:
                get_persistence_service().project_dataset_activations.record_contradiction(
                    project_id=payload.projectId,
                    actor_user_id=actor_user_id,
                    reason="Runtime workspace hydration failed after durable activation.",
                    metadata={"operation": "register_workspace"},
                )
            except Exception as contradiction_exc:  # pragma: no cover - diagnostic best effort
                LOGGER.error(
                    "Unable to persist dataset activation contradiction for project=%s: %s",
                    payload.projectId,
                    contradiction_exc,
                )
            invalidate_dataset_identity(
                "The durable dataset selection could not be hydrated into the workspace.",
                store=scoped_store,
                clear_frames=True,
            )
            activation_guard.release()
            raise HTTPException(
                status_code=500,
                detail="The registered dataset version was not activated because workspace hydration failed.",
            ) from exc
    activation_guard.release()
    _mirror_legacy_link(
        payload.projectId,
        dataset_id,
        dataset_version_id,
        "development",
    )
    schedule_checkpoint_save()
    active_selection = activation.get("active_selection") or {}
    link = _link_response(
        activation.get("link") or {},
        dataset_version_id=dataset_version_id,
    )
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
        "activation_revision": int(active_selection.get("activation_revision") or 0),
        "link": link,
        "active_selection": _active_selection_response(active_selection),
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
def activate_dataset_version(
    dataset_id: str,
    version_id: str,
    project_id: str = Query(...),
    expected_activation_revision: Optional[int] = Query(None, ge=0),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "edit")
    resolved = resolve_registered_version(
        dataset_id,
        version_id,
        user=user,
    )
    dataset = resolved["dataset"]
    version = resolved["version"]
    path = resolved["artifact_path"]
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to load registered dataset version: {exc}") from exc
    actor_user_id = _authenticated_actor(user)
    scoped_store = DATASTORE.current()
    scoped_results = RESULTS.current()
    activation_guard = project_dataset_activation_lock(project_id)
    activation_guard.acquire()
    try:
        activation = get_persistence_service().project_dataset_activations.activate_exact(
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=version_id,
            actor_user_id=actor_user_id,
            expected_activation_revision=expected_activation_revision,
            metadata={
                "datasetRole": "modeling",
                "requestedDatasetVersionId": version_id,
                "source": "dataset_library_activation",
            },
        )
    except ProjectDatasetActivationConflictError as exc:
        activation_guard.release()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProjectDatasetActivationStateError as exc:
        activation_guard.release()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BaseException:
        activation_guard.release()
        raise

    active_selection = activation.get("active_selection") or {}
    identity = {
        **resolved,
        "project_id": project_id,
        "project_link": activation.get("link") or {},
        "active_selection": active_selection,
        "activation_revision": int(active_selection.get("activation_revision") or 0),
    }
    with scoped_store.state_lock:
        try:
            cached_activation_revision = int(
                scoped_store.meta.get("activation_revision") or 0
            )
        except (TypeError, ValueError):
            cached_activation_revision = 0
        prior_same_identity = (
            str(scoped_store.meta.get("project_id") or "") == project_id
            and str(scoped_store.meta.get("dataset_id") or "") == dataset_id
            and str(scoped_store.meta.get("dataset_version_id") or "") == version_id
            and cached_activation_revision == identity["activation_revision"]
            and str(scoped_store.meta.get("dataset_identity_status") or "").casefold()
            == "current"
            and scoped_store.raw_df is not None
            and not scoped_store.raw_df.empty
        )
        try:
            if not prior_same_identity:
                scoped_store.set_raw(df)
                scoped_store.set_target(None)
                scoped_store.meta["selected_columns"] = [
                    str(column) for column in df.columns
                ]
            canonical = stamp_active_dataset_identity(identity, store=scoped_store)
            scoped_store.meta["activation_revision"] = identity["activation_revision"]
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
            if not prior_same_identity:
                invalidate_downstream_training_state(
                    "A different exact Dataset Library version or activation "
                    "revision was activated.",
                    store=scoped_store,
                    result_store=scoped_results,
                    split_status="not_created",
                    # set_raw already advanced the guarded revision.
                    bump_revision=False,
                )
        except Exception as exc:
            try:
                get_persistence_service().project_dataset_activations.record_contradiction(
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    reason="Runtime workspace hydration failed after durable activation.",
                    metadata={"operation": "activate_dataset_version"},
                )
            except Exception as contradiction_exc:  # pragma: no cover - diagnostic best effort
                LOGGER.error(
                    "Unable to persist dataset activation contradiction for project=%s: %s",
                    project_id,
                    contradiction_exc,
                )
            invalidate_dataset_identity(
                "The durable dataset selection could not be hydrated into the workspace.",
                store=scoped_store,
                clear_frames=True,
            )
            activation_guard.release()
            raise HTTPException(
                status_code=500,
                detail="The exact dataset selection was not activated because workspace hydration failed.",
            ) from exc

    activation_guard.release()

    _mirror_legacy_link(project_id, dataset_id, version_id, "modeling")
    schedule_checkpoint_save()
    link = _link_response(
        activation.get("link") or {},
        dataset_version_id=version_id,
    )
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
        "activation_revision": int(active_selection.get("activation_revision") or 0),
        "link": link,
        "active_selection": _active_selection_response(active_selection),
        "workflow_effective_state": activation.get("workflow_effective_state"),
        "activation_changed": bool(activation.get("changed")),
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
def post_project_link(
    project_id: str,
    payload: LinkDatasetRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "edit")
    # A link authorizes one registered asset.  The supplied version is
    # validated exactly for compatibility, but version selection remains the
    # separate transactional activation contract.
    resolved = resolve_registered_version(
        payload.datasetId,
        payload.versionId,
        user=user,
    )
    actor_user_id = _authenticated_actor(user)
    result = get_persistence_service().project_dataset_activations.authorize_link(
        project_id=project_id,
        dataset_id=resolved["dataset_id"],
        actor_user_id=actor_user_id,
        metadata={
            "datasetRole": payload.datasetRole,
            "requestedDatasetVersionId": resolved["dataset_version_id"],
            "source": "compatibility_link_endpoint",
        },
    )
    _mirror_legacy_link(
        project_id,
        resolved["dataset_id"],
        resolved["dataset_version_id"],
        payload.datasetRole,
    )
    return {
        "ok": True,
        "link": _link_response(
            result.get("link") or {},
            dataset_version_id=resolved["dataset_version_id"],
        ),
        "changed": bool(result.get("changed")),
    }


@router.get("/projects/{project_id}/datasets")
def get_project_links(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "view")
    repository = get_persistence_service().project_dataset_activations
    durable_links = repository.list_links(project_id)
    registry = load_registry()
    datasets = {
        str(item.get("datasetId") or ""): item
        for item in (registry.get("datasets") or [])
        if isinstance(item, dict)
    }
    links = []
    accessible_dataset_ids = set()
    for durable_link in durable_links:
        dataset = datasets.get(str(durable_link.get("dataset_id") or ""))
        if not dataset or not user_can_access(dataset, user=user):
            continue
        accessible_dataset_ids.add(str(dataset.get("datasetId") or ""))
        response_link = _link_response(durable_link)
        response_link["dataset"] = summarize_dataset(dataset)
        links.append(response_link)
    active_selection = repository.get_active_selection(project_id)
    if (
        not isinstance(active_selection, dict)
        or str(active_selection.get("dataset_id") or "")
        not in accessible_dataset_ids
    ):
        active_selection = None
    return {
        "ok": True,
        "links": links,
        "active_selection": (
            _active_selection_response(active_selection)
            if active_selection is not None
            else None
        ),
    }


@router.delete("/projects/{project_id}/datasets/{dataset_id}")
def delete_project_link(
    project_id: str,
    dataset_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "edit")
    _authorize_dataset_acl_for_link_removal(dataset_id, user)
    actor_user_id = _authenticated_actor(user)
    result = get_persistence_service().project_dataset_activations.unlink_dataset(
        project_id=project_id,
        dataset_id=dataset_id,
        actor_user_id=actor_user_id,
    )
    try:
        unlink_project_dataset(project_id, dataset_id)
    except Exception as exc:  # pragma: no cover - projection is best effort
        LOGGER.warning(
            "Durable project-dataset unlink succeeded but legacy projection failed "
            "for project=%s dataset=%s: %s",
            project_id,
            dataset_id,
            exc,
        )

    active_selection = result.get("active_selection") or {}
    if (
        str(active_selection.get("dataset_id") or "") == dataset_id
        and str(active_selection.get("activation_status") or "").casefold()
        != "active"
    ):
        scoped_store = DATASTORE.current()
        scoped_results = RESULTS.current()
        with scoped_store.state_lock:
            try:
                invalidate_downstream_training_state(
                    "The active project-dataset authorization was removed.",
                    store=scoped_store,
                    result_store=scoped_results,
                    split_status="stale",
                )
            except Exception as exc:  # pragma: no cover - cache cleanup is best effort
                LOGGER.warning(
                    "Durable unlink succeeded but downstream cache invalidation reported: %s",
                    exc,
                )
            scoped_store.reset_all()
            scoped_results.clear_model_artifacts()
            scoped_results.set_model_availability({})
        schedule_checkpoint_save()
    return {
        "ok": True,
        "removed": int(result.get("removed") or 0),
        "active_selection": _active_selection_response(active_selection),
    }


@router.get("/system/diagnostics")
def get_system_diagnostics() -> Dict[str, Any]:
    return diagnostics()

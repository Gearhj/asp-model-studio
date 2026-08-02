from __future__ import annotations

import logging
import re
import sqlite3
import uuid
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from ..security.security_store import (
    AUDIT_ROLES,
    audit_event,
    require_role,
    require_user,
)
from ..core.session_checkpoint import discard_modeling_scopes, flush_checkpoint
from ..datasets.dataset_registry import (
    load_registry,
    unlink_all_project_datasets,
    user_can_access,
)
from ..evidence.evidence_identity import (
    assert_evidence_lineage_immutable,
    authorize_and_normalize_evidence,
)
from ..analytics.result_cache import RESULT_CACHE
from ..analytics.resource_governance import CONCURRENCY
from ..scoring_runs.scoring_run_service import archive_scoring_runs_for_project
from ..model_registry.model_registry_service import archive_registry_for_project
from ..sharing.sharing_service import SharingService
from .db import PersistenceUnavailableError, now_iso
from .service import PersistenceService, get_persistence_service


router = APIRouter()
LOGGER = logging.getLogger("atlas.persistence_router")


def _pick(payload: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _camel(key: str) -> str:
    return re.sub(r"_([a-z])", lambda match: match.group(1).upper(), key)


def _api_record(record: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if record is None:
        return None
    result: Dict[str, Any] = {}
    for key, value in record.items():
        output_key = key[:-5] if key.endswith("_json") else key
        result[_camel(output_key)] = value
    return result


def _execute(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except PersistenceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=f"ATLAS persistence rejected the record: {exc}") from exc
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=f"ATLAS persistence is temporarily unavailable: {exc}") from exc


def _service() -> PersistenceService:
    return get_persistence_service()


def _accessible_dataset_ids(user: Dict[str, Any]) -> set[str]:
    """Return only Dataset Library assets visible to this authenticated caller."""

    authenticated_user_id = str((user or {}).get("userId") or "").strip()
    if not authenticated_user_id:
        return set()
    return {
        str(dataset.get("datasetId") or "")
        for dataset in (load_registry().get("datasets") or [])
        if isinstance(dataset, dict) and user_can_access(dataset, user=user)
    }


def _project_with_durable_dataset_state(
    record: Dict[str, Any],
    user: Dict[str, Any],
) -> Dict[str, Any]:
    project = _api_record(record) or {}
    state = _service().project_dataset_activations.get_project_state(
        str(record.get("project_id") or "")
    )
    # Project access and Dataset Library access are independent grants.  A
    # collaborator may be allowed to open a project without being allowed to
    # discover the identifiers of a dataset linked to it.  Resolve the
    # authenticated caller's Dataset Library ACL explicitly and fail closed
    # when the registry record is absent; durable link state never grants
    # dataset access by itself.
    accessible_dataset_ids = _accessible_dataset_ids(user)
    visible_links = [
        link
        for link in (state.get("links") or [])
        if str(link.get("dataset_id") or "") in accessible_dataset_ids
    ]
    active_selection = state.get("active_selection")
    if (
        not isinstance(active_selection, dict)
        or str(active_selection.get("dataset_id") or "")
        not in accessible_dataset_ids
    ):
        active_selection = None
    project["links"] = [_api_record(link) or {} for link in visible_links]
    project["activeSelection"] = _api_record(active_selection)
    return project


def _workflow_state_for_dataset_acl(
    record: Dict[str, Any],
    user: Dict[str, Any],
) -> Dict[str, Any]:
    """Fail closed without leaking an inaccessible active dataset identity.

    Project permission and Dataset Library permission are independent.  The
    workflow endpoint therefore cannot return the exact dataset/version,
    activation revision, or lineage artifact identifiers merely because a
    caller may view the surrounding project.  Historical workflow progress is
    retained, while the effective view is redacted and blocked until the
    caller also has Dataset Library access.
    """

    result = dict(record)
    workflow_status = dict(record.get("workflow_status_json") or {})
    durable_state = _service().project_dataset_activations.get_project_state(
        str(record.get("project_id") or "")
    )
    active_selection = durable_state.get("active_selection")
    active_dataset_id = (
        str(active_selection.get("dataset_id") or "").strip()
        if isinstance(active_selection, dict)
        else ""
    )
    workflow_identity = workflow_status.get("datasetIdentity")
    workflow_dataset_id = (
        str(
            workflow_identity.get("dataset_id")
            or workflow_identity.get("datasetId")
            or ""
        ).strip()
        if isinstance(workflow_identity, dict)
        else ""
    )
    referenced_dataset_ids = {
        dataset_id
        for dataset_id in (active_dataset_id, workflow_dataset_id)
        if dataset_id
    }
    if not referenced_dataset_ids:
        return result
    if referenced_dataset_ids.issubset(_accessible_dataset_ids(user)):
        return result

    historical = [
        str(step)
        for step in (record.get("completed_steps_json") or [])
        if str(step)
    ]
    identity_independent = [step for step in historical if step == "step00"]
    redacted_status = {
        key: workflow_status[key]
        for key in ("projectType", "workflowId")
        if key in workflow_status
    }
    redacted_status.update(
        {
            "datasetIdentity": None,
            "hasDataset": False,
            "historicalCompletedSteps": historical,
            "effectiveCompletedSteps": identity_independent,
            "effectiveCurrentStepId": "step01",
            "effectiveSteps": {
                step: {
                    "effectiveStatus": (
                        "complete" if step in identity_independent else "pending"
                    ),
                    "lineageStatus": (
                        "current" if step in identity_independent else "unauthorized"
                    ),
                    "reason": (
                        "Identity-independent project context remains current."
                        if step in identity_independent
                        else "Dataset Library access is required to resolve this workflow step."
                    ),
                    "artifactIds": [],
                }
                for step in historical
            },
            "steps": {step: "complete" for step in historical},
            "identityValidity": {
                "status": "unauthorized",
                "reason": (
                    "Dataset Library access is required to resolve the active "
                    "modeling identity."
                ),
                "historicalCompletionPreserved": True,
            },
        }
    )
    result["workflow_status_json"] = redacted_status
    result["step_evidence_status_json"] = {}
    return result


def _sharing_service() -> SharingService:
    return SharingService(_service())


def _authorize_project(
    project_id: str,
    user: Dict[str, Any],
    permission: str,
    *,
    allow_missing: bool = False,
) -> Optional[Dict[str, Any]]:
    """Enforce resource-level authorization on a project before a persistence
    operation (on the project itself or a project-scoped nested resource)
    proceeds.

    Returns the existing project record, or ``None`` when the project does
    not yet exist and ``allow_missing`` permits the caller to implicitly
    create it (the existing ``ensure_project``/upsert-as-create behavior of
    several endpoints is preserved unchanged; a not-yet-existing project has
    no owner to violate, so there is nothing to authorize against).
    """
    existing = _service().projects.get(project_id)
    if existing is None:
        if allow_missing:
            return None
        raise HTTPException(status_code=404, detail="ATLAS project was not found in the persistence database.")
    check = _sharing_service().check_permission(user, "project", project_id, permission)
    if not check.get("allowed"):
        audit_event(
            "access.denied",
            "project",
            project_id,
            "denied",
            user_id=user.get("userId"),
            reason=f"Insufficient '{permission}' permission on project.",
            metadata={"projectId": project_id, "requiredPermission": permission},
        )
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action on this project.")
    return existing


def _id(prefix: str, payload: Dict[str, Any], *keys: str) -> str:
    return str(_pick(payload, *keys, default=f"{prefix}_{uuid.uuid4().hex}"))


def _project_record(project_id: str, payload: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    metadata = _pick(payload, "metadata", "metadataJson", "metadata_json", default={}) or {}
    snapshot = payload.get("snapshot")
    if snapshot is not None:
        metadata = {**metadata, "snapshot": snapshot}
    return {
        "project_id": project_id,
        "project_name": _pick(payload, "projectName", "project_name", default="Untitled ATLAS Project"),
        "project_type": _pick(payload, "projectType", "project_type", default="predictive-modeling"),
        "workflow_type": _pick(payload, "workflowType", "workflow_type", "workflowId", "workflow_id", default="predictive-modeling"),
        "template_id": _pick(payload, "templateId", "template_id"),
        "status": _pick(payload, "status", default="active"),
        "owner_user_id": _pick(payload, "ownerUserId", "owner_user_id", default=user.get("userId")),
        "created_at": _pick(payload, "createdAt", "created_at"),
        "updated_at": _pick(payload, "updatedAt", "updated_at", default=now_iso()),
        "created_by": _pick(payload, "createdBy", "created_by", default=user.get("userId")),
        "updated_by": _pick(payload, "updatedBy", "updated_by", default=user.get("userId")),
        "metadata_json": metadata,
    }


@router.get("/persistence/health")
def persistence_health() -> Dict[str, Any]:
    try:
        _service().database.health()
    except (PersistenceUnavailableError, sqlite3.Error, OSError) as exc:
        raise HTTPException(status_code=503, detail="Service unavailable.") from exc
    return {"ok": True, "status": "running"}


@router.get("/projects")
def list_projects(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    items = _execute(lambda: _service().projects.list())
    sharing = _sharing_service()
    visible = [item for item in items if sharing.check_permission(user, "project", item["project_id"], "view").get("allowed")]
    projects = _execute(
        lambda: [_project_with_durable_dataset_state(item, user) for item in visible]
    )
    return {"ok": True, "projects": projects, "count": len(visible)}


@router.post("/projects")
def create_project(payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    project_id = _id("project", payload, "projectId", "project_id")

    def operation() -> Dict[str, Any]:
        service = _service()
        service.sync_user(user)
        return service.projects.upsert(_project_record(project_id, payload, user))

    record = _execute(operation)
    audit_event(
        "project.created",
        "project",
        project_id,
        "success",
        metadata={"projectId": project_id, "summary": f"Created project {record.get('project_name')}."},
    )
    if record.get("template_id"):
        audit_event(
            "template.selected",
            "project",
            project_id,
            "success",
            metadata={"projectId": project_id, "templateId": record.get("template_id"), "summary": f"Selected template {record.get('template_id')}."},
        )
    project = _execute(lambda: _project_with_durable_dataset_state(record, user))
    return {"ok": True, "project": project}


@router.get("/projects/{project_id}")
def get_project(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    record = _authorize_project(project_id, user, "view")
    audit_event(
        "project.opened",
        "project",
        project_id,
        "success",
        user_id=user.get("userId"),
        metadata={"projectId": project_id, "summary": f"Opened project {record.get('project_name')}."},
    )
    project = _execute(lambda: _project_with_durable_dataset_state(record, user))
    return {"ok": True, "project": project}


@router.put("/projects/{project_id}")
def update_project(project_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    # A PUT to a project_id that doesn't exist yet implicitly creates it, owned
    # by the caller (existing behavior, relied on by sqlite_persistence_backend_test.py).
    # A PUT to an existing project the caller doesn't have edit access to is denied.
    _authorize_project(project_id, user, "edit", allow_missing=True)

    def operation() -> Dict[str, Any]:
        service = _service()
        service.sync_user(user)
        existing = service.projects.get(project_id) or {}
        existing_metadata = existing.get("metadata_json") or {}
        incoming_metadata = _pick(payload, "metadata", "metadataJson", "metadata_json", default={}) or {}
        merged = {
            "projectName": existing.get("project_name"),
            "projectType": existing.get("project_type"),
            "workflowType": existing.get("workflow_type"),
            "templateId": existing.get("template_id"),
            "status": existing.get("status"),
            "ownerUserId": existing.get("owner_user_id"),
            "createdAt": existing.get("created_at"),
            "metadata": {**existing_metadata, **incoming_metadata},
            **payload,
        }
        merged["metadata"] = {**existing_metadata, **incoming_metadata}
        return service.projects.upsert(_project_record(project_id, merged, user))

    record = _execute(operation)
    audit_event(
        "project.saved",
        "project",
        project_id,
        "success",
        metadata={"projectId": project_id, "summary": f"Saved project {record.get('project_name')}."},
    )
    project = _execute(lambda: _project_with_durable_dataset_state(record, user))
    return {"ok": True, "project": project}


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "admin")
    actor_user_id = str(user.get("userId") or "").strip()
    if not actor_user_id:
        raise HTTPException(
            status_code=401,
            detail="An authenticated user is required to delete a project.",
        )

    # Persistent Scoring Runs, Phase I: archive this project's scoring runs
    # BEFORE the project row is deleted -- scoring_runs.project_id uses
    # ON DELETE SET NULL, so archiving must happen while project_id is still
    # a valid foreign key value, exactly like the Dataset Library's
    # unlink-before-delete ordering below.
    _execute(lambda: archive_scoring_runs_for_project(project_id))
    # Durable Model Registry, Phase L: same archive-before-delete ordering as
    # scoring runs -- model_versions.project_id also uses ON DELETE SET NULL.
    _execute(lambda: archive_registry_for_project(project_id))

    # Preserve an immutable exact-dataset deactivation event while the project
    # and its FK-backed link/selection records still exist.  Deleting the
    # project then cascades only those current authorization/selection rows;
    # activation events intentionally survive as audit evidence.
    _execute(
        lambda: _service().project_dataset_activations.deactivate_project(
            project_id=project_id,
            actor_user_id=actor_user_id,
            reason="The project was deleted.",
        )
    )

    def operation() -> bool:
        service = _service()
        service.sync_user(user)
        return service.projects.delete(project_id)

    deleted = _execute(operation)
    if not deleted:
        raise HTTPException(status_code=404, detail="ATLAS project was not found in the persistence database.")
    # Dataset lifecycle audit fix: project deletion never removed this project's
    # Dataset Library links, leaving project_links.json entries (and each asset's
    # linkedProjects list) pointing at a project_id that no longer exists forever.
    # The Library asset itself is NEVER deleted here -- only this project's link to
    # it -- see docs/architecture/DATASET_LIFECYCLE_ADR.md's deletion rules table.
    try:
        unlink_all_project_datasets(project_id)
    except Exception as exc:  # pragma: no cover - compatibility projection only
        LOGGER.warning(
            "Project %s was durably deleted but legacy dataset-link projection "
            "cleanup failed: %s",
            project_id,
            exc,
        )
    # Stage 6.1 lifecycle repair: drop every resident in-memory modeling scope
    # for this project (all owners, including collaborator-private scopes) and
    # rewrite the checkpoint immediately, so the deleted project can neither
    # keep inflating future saves nor be resurrected at the next restart.
    discard_modeling_scopes(project_id=project_id)
    flush_checkpoint()
    # Enterprise Analytical Data Plane: drop any cached analytical results and
    # release concurrency counters scoped to this project (Phase J requirement 10 /
    # Phase L requirement 12) so a deleted project's cached aggregates can never be
    # served again and its query slots don't leak.
    RESULT_CACHE.invalidate_project(project_id)
    CONCURRENCY.release(str(user.get("userId") or ""), project_id)
    audit_event(
        "project.deleted",
        "project",
        project_id,
        "success",
        user_id=user.get("userId"),
        metadata={
            "projectId": project_id,
            "summary": "Deleted the project workspace and project-scoped persisted records. Dataset Library assets were retained.",
        },
    )
    return {"ok": True, "projectId": project_id, "deleted": True}


@router.get("/projects/{project_id}/workflow-state")
def get_workflow_state(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "view")
    record = _execute(lambda: _service().projects.get_workflow_state(project_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Workflow state has not been saved for this project.")
    visible_record = _execute(lambda: _workflow_state_for_dataset_acl(record, user))
    return {"ok": True, "workflowState": _api_record(visible_record)}


@router.put("/projects/{project_id}/workflow-state")
def save_workflow_state(project_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "edit", allow_missing=True)
    previous_completed = set()

    def operation() -> Dict[str, Any]:
        service = _service()
        service.ensure_project(project_id, user)
        previous = service.projects.get_workflow_state(project_id) or {}
        previous_completed.update(previous.get("completed_steps_json") or [])
        return service.projects.upsert_workflow_history(
            project_id,
            {
                "current_step_id": _pick(payload, "currentStepId", "current_step_id"),
                "completed_steps_json": _pick(
                    payload,
                    "historicalCompletedSteps",
                    "historical_completed_steps",
                    "completedSteps",
                    "completed_steps_json",
                    default=[],
                ),
                "workflow_status_json": _pick(payload, "workflowStatus", "workflow_status_json", default={}),
                "step_evidence_status_json": _pick(payload, "stepEvidenceStatus", "step_evidence_status_json", default={}),
                "updated_at": _pick(payload, "updatedAt", "updated_at", default=now_iso()),
                "completed_by": user.get("userId"),
            },
        )

    record = _execute(operation)
    new_completed = [step for step in (record.get("completed_steps_json") or []) if step not in previous_completed]
    if new_completed:
        audit_event(
            "workflow.step.completed",
            "workflow_state",
            project_id,
            "success",
            metadata={"projectId": project_id, "completedSteps": new_completed, "summary": f"Completed workflow step(s): {', '.join(new_completed)}."},
        )
    # Browser workflow PUT records historical observations only.  It must
    # never emit the project-completed audit event: that event belongs to the
    # backend path that proves effective completion from canonical artifacts.
    return {"ok": True, "workflowState": _api_record(record)}


@router.get("/projects/{project_id}/evidence")
def list_evidence(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "view")
    items = _execute(lambda: _service().evidence.list_for_project(project_id))
    return {"ok": True, "evidence": [_api_record(item) for item in items], "count": len(items)}


def _evidence_record(project_id: str, evidence_id: str, payload: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    requested_status = str(_pick(payload, "status", default="generated") or "generated").lower()
    status = {
        "draft": "generated",
        "needs_review": "generated",
        "accepted": "approved",
        "deprecated": "stale",
    }.get(requested_status, requested_status)
    if status not in {"generated", "captured", "ready", "approved", "stale", "rejected"}:
        status = "generated"
    payload_json = (
        payload
        if payload.get("lineage_contract") == "canonical_dataset_version"
        else _pick(
            payload,
            "payload",
            "payloadJson",
            "payload_json",
            default=payload,
        )
    )
    return {
        "evidence_id": evidence_id,
        "project_id": project_id,
        "workflow_type": _pick(payload, "workflowType", "workflow_type"),
        "step_id": _pick(payload, "stepId", "step_id", "workflowStep"),
        "artifact_type": _pick(payload, "artifactType", "artifact_type", "evidenceType", default="evidence"),
        "status": status,
        "title": _pick(payload, "title", default="ATLAS Evidence"),
        "summary": _pick(payload, "summary"),
        "source_ref": _pick(payload, "sourceRef", "source_ref", "sourceRoute", "sourcePage"),
        "artifact_hash": _pick(payload, "artifactHash", "artifact_hash"),
        "created_by": _pick(payload, "createdBy", "created_by", default=user.get("userId")),
        "created_at": _pick(payload, "createdAt", "created_at"),
        "captured_at": _pick(payload, "capturedAt", "captured_at"),
        "approved_at": _pick(payload, "approvedAt", "approved_at"),
        "payload_json": payload_json,
    }


@router.post("/projects/{project_id}/evidence")
def create_evidence(project_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    normalized = authorize_and_normalize_evidence(
        payload,
        user,
        path_project_id=project_id,
    )
    evidence_id = _id("evidence", normalized, "evidenceId", "evidence_id")

    def operation() -> Dict[str, Any]:
        service = _service()
        existing = service.evidence.get(evidence_id)
        if existing and existing.get("project_id") != project_id:
            raise HTTPException(
                status_code=404,
                detail="ATLAS evidence record was not found under this project.",
            )
        effective = normalized
        if existing:
            effective = authorize_and_normalize_evidence(
                {
                    **(existing.get("payload_json") or {}),
                    **payload,
                },
                user,
                path_project_id=project_id,
            )
            assert_evidence_lineage_immutable(
                existing.get("payload_json") or {},
                effective,
            )
        return service.evidence.upsert(
            _evidence_record(project_id, evidence_id, effective, user)
        )

    record = _execute(operation)
    action = "evidence.artifact.captured" if record.get("status") in {"captured", "ready", "approved"} else "evidence.artifact.generated"
    audit_event(action, "evidence", evidence_id, "success", metadata={"projectId": project_id, "status": record.get("status"), "summary": f"{record.get('title')} is {record.get('status')}."})
    return {"ok": True, "evidence": _api_record(record)}


@router.put("/projects/{project_id}/evidence/{evidence_id}")
def update_evidence(project_id: str, evidence_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    def operation() -> Dict[str, Any]:
        service = _service()
        existing = service.evidence.get(evidence_id) or {}
        # An evidence_id that exists but belongs to a different project must not be
        # readable, mergeable, or re-parented via an update scoped to this project_id.
        if existing and existing.get("project_id") != project_id:
            raise HTTPException(status_code=404, detail="ATLAS evidence record was not found under this project.")
        merged = {**(existing.get("payload_json") or {}), **payload}
        normalized = authorize_and_normalize_evidence(
            merged,
            user,
            path_project_id=project_id,
        )
        if existing:
            assert_evidence_lineage_immutable(
                existing.get("payload_json") or {},
                normalized,
            )
        return service.evidence.upsert(
            _evidence_record(project_id, evidence_id, normalized, user)
        )

    record = _execute(operation)
    action = "evidence.artifact.captured" if record.get("status") in {"captured", "ready", "approved"} else "evidence.artifact.generated"
    audit_event(action, "evidence", evidence_id, "success", metadata={"projectId": project_id, "status": record.get("status"), "summary": f"Updated {record.get('title')} to {record.get('status')}."})
    return {"ok": True, "evidence": _api_record(record)}


def _child_list(project_id: str, repository_name: str) -> Dict[str, Any]:
    repository = getattr(_service(), repository_name)
    items = _execute(lambda: repository.list_for_project(project_id))
    return {"ok": True, "items": [_api_record(item) for item in items], "count": len(items)}


@router.get("/projects/{project_id}/runs")
def list_runs(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "view")
    payload = _child_list(project_id, "runs")
    items = payload.pop("items")
    return {**payload, "runs": items}


@router.post("/projects/{project_id}/runs")
def create_run(project_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "edit", allow_missing=True)
    run_id = _id("run", payload, "runId", "run_id")

    def operation() -> Dict[str, Any]:
        service = _service()
        service.ensure_project(project_id, user)
        return service.runs.upsert(
            {
                "run_id": run_id,
                "project_id": project_id,
                "run_type": _pick(payload, "runType", "run_type", default="workflow"),
                "workflow_type": _pick(payload, "workflowType", "workflow_type"),
                "status": _pick(payload, "status", default="created"),
                "started_at": _pick(payload, "startedAt", "started_at"),
                "completed_at": _pick(payload, "completedAt", "completed_at"),
                "parameters_json": _pick(payload, "parameters", "parametersJson", "parameters_json", default={}),
                "metrics_json": _pick(payload, "metrics", "metricsJson", "metrics_json", default={}),
                "artifacts_json": _pick(payload, "artifacts", "artifactsJson", "artifacts_json", default={}),
                "error_json": _pick(payload, "error", "errorJson", "error_json", default={}),
                "created_by": _pick(payload, "createdBy", "created_by", default=user.get("userId")),
            }
        )

    record = _execute(operation)
    run_type = str(record.get("run_type") or "workflow")
    status = str(record.get("status") or "created").lower()
    if status in {"complete", "completed", "success", "succeeded"}:
        if "validation" in run_type:
            action = "validation.completed"
        elif "scenario" in run_type:
            action = "scenario.run.completed"
        elif "sensitivity" in run_type:
            action = "sensitivity.run.completed"
        else:
            action = "solver.run.completed"
    else:
        action = "solver.run.started"
    audit_event(action, "run", run_id, "success", metadata={"projectId": project_id, "runType": run_type, "status": status, "summary": f"{run_type} is {status}."})
    return {"ok": True, "run": _api_record(record)}


@router.get("/projects/{project_id}/decisions")
def list_decisions(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "view")
    payload = _child_list(project_id, "decisions")
    items = payload.pop("items")
    return {**payload, "decisions": items}


@router.post("/projects/{project_id}/decisions")
def create_decision(project_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "edit", allow_missing=True)
    decision_id = _id("decision", payload, "decisionId", "decision_id")

    def operation() -> Dict[str, Any]:
        service = _service()
        service.ensure_project(project_id, user)
        timestamp = now_iso()
        return service.decisions.upsert(
            {
                "decision_id": decision_id,
                "project_id": project_id,
                "decision_type": _pick(payload, "decisionType", "decision_type", default="workflow_decision"),
                "title": _pick(payload, "title", default="ATLAS Decision"),
                "summary": _pick(payload, "summary"),
                "status": _pick(payload, "status", default="draft"),
                "owner": _pick(payload, "owner"),
                "created_by": _pick(payload, "createdBy", "created_by", default=user.get("userId")),
                "created_at": _pick(payload, "createdAt", "created_at", default=timestamp),
                "updated_at": _pick(payload, "updatedAt", "updated_at", default=timestamp),
                "payload_json": _pick(payload, "payload", "payloadJson", "payload_json", default=payload),
            }
        )

    record = _execute(operation)
    audit_event("recommendation.status.changed", "decision", decision_id, "success", metadata={"projectId": project_id, "status": record.get("status"), "summary": f"{record.get('title')} is {record.get('status')}."})
    if "implementation" in str(record.get("decision_type") or "").lower() and record.get("status") in {"complete", "approved"}:
        audit_event("implementation.plan.completed", "decision", decision_id, "success", metadata={"projectId": project_id, "summary": record.get("summary") or "Implementation plan completed."})
    return {"ok": True, "decision": _api_record(record)}


@router.get("/projects/{project_id}/documentation")
def list_documentation(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "view")
    payload = _child_list(project_id, "documentation")
    items = payload.pop("items")
    return {**payload, "documentation": items}


@router.post("/projects/{project_id}/documentation")
def create_documentation(project_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "edit", allow_missing=True)
    package_id = _id("package", payload, "packageId", "package_id", "documentId")

    def operation() -> Dict[str, Any]:
        service = _service()
        service.ensure_project(project_id, user)
        timestamp = now_iso()
        return service.documentation.upsert(
            {
                "package_id": package_id,
                "project_id": project_id,
                "package_type": _pick(payload, "packageType", "package_type", "templateType", default="model_development_document"),
                "status": _pick(payload, "status", default="draft"),
                "readiness_score": _pick(payload, "readinessScore", "readiness_score"),
                "section_count": _pick(payload, "sectionCount", "section_count"),
                "completed_section_count": _pick(payload, "completedSectionCount", "completed_section_count"),
                "created_at": _pick(payload, "createdAt", "created_at", default=timestamp),
                "updated_at": _pick(payload, "updatedAt", "updated_at", default=timestamp),
                "payload_json": _pick(payload, "payload", "payloadJson", "payload_json", default=payload),
                "created_by": _pick(payload, "createdBy", "created_by", default=user.get("userId")),
            }
        )

    record = _execute(operation)
    audit_event("documentation.package.generated", "documentation", package_id, "success", metadata={"projectId": project_id, "status": record.get("status"), "summary": f"Generated {record.get('package_type')} documentation package."})
    return {"ok": True, "documentationPackage": _api_record(record)}


@router.get("/projects/{project_id}/exports")
def list_exports(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "view")
    payload = _child_list(project_id, "exports")
    items = payload.pop("items")
    return {**payload, "exports": items}


@router.post("/projects/{project_id}/exports")
def create_export(project_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "edit", allow_missing=True)
    export_id = _id("export", payload, "exportId", "export_id")

    def operation() -> Dict[str, Any]:
        service = _service()
        service.ensure_project(project_id, user)
        return service.exports.upsert(
            {
                "export_id": export_id,
                "project_id": project_id,
                "export_type": _pick(payload, "exportType", "export_type", default="download"),
                "file_name": _pick(payload, "fileName", "file_name", default="atlas-export"),
                "file_path": _pick(payload, "filePath", "file_path"),
                "storage_mode": _pick(payload, "storageMode", "storage_mode", default="client_generated"),
                "created_by": _pick(payload, "createdBy", "created_by", default=user.get("userId")),
                "created_at": _pick(payload, "createdAt", "created_at", default=now_iso()),
                "artifact_hash": _pick(payload, "artifactHash", "artifact_hash"),
                "metadata_json": _pick(payload, "metadata", "metadataJson", "metadata_json", default=payload),
            }
        )

    record = _execute(operation)
    audit_event("export.generated", "export", export_id, "success", metadata={"projectId": project_id, "exportType": record.get("export_type"), "storageMode": record.get("storage_mode"), "summary": f"Generated export {record.get('file_name')}."})
    return {"ok": True, "export": _api_record(record)}


@router.get("/audit-log")
def list_persisted_audit(
    projectId: Optional[str] = None,
    userId: Optional[str] = None,
    actionType: Optional[str] = None,
    limit: int = 250,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    require_role(user, AUDIT_ROLES)
    items = _execute(lambda: _service().audit.list(project_id=projectId, user_id=userId, action_type=actionType, limit=limit))
    return {"ok": True, "events": [_api_record(item) for item in items], "count": len(items)}


@router.get("/demo-feedback")
def list_demo_feedback(
    projectId: Optional[str] = None,
    limit: int = 250,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    require_role(user, {"admin", "manager", "validator"})
    items = _execute(lambda: _service().feedback.list(project_id=projectId, limit=limit))
    return {"ok": True, "feedback": [_api_record(item) for item in items], "count": len(items)}


@router.post("/demo-feedback")
def create_demo_feedback(payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    feedback_id = _id("feedback", payload, "feedbackId", "feedback_id")
    record = _execute(
        lambda: _service().feedback.upsert(
            {
                "feedback_id": feedback_id,
                "project_id": _pick(payload, "projectId", "project_id"),
                "user_id": user.get("userId"),
                "route": _pick(payload, "route", default="/"),
                "workflow_type": _pick(payload, "workflowType", "workflow_type"),
                "step_id": _pick(payload, "stepId", "step_id"),
                "issue_type": _pick(payload, "issueType", "issue_type", default="usability"),
                "severity": _pick(payload, "severity", default="medium"),
                "expected_behavior": _pick(payload, "expectedBehavior", "expected_behavior"),
                "actual_behavior": _pick(payload, "actualBehavior", "actual_behavior"),
                "notes": _pick(payload, "notes"),
                "created_at": _pick(payload, "createdAt", "created_at", default=now_iso()),
                "metadata_json": _pick(payload, "metadata", "metadataJson", "metadata_json", default={}),
            }
        )
    )
    audit_event("demo.feedback.submitted", "demo_feedback", feedback_id, "success", metadata={"projectId": record.get("project_id"), "severity": record.get("severity"), "summary": "Private demo feedback submitted."})
    return {"ok": True, "feedback": _api_record(record)}

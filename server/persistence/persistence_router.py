from __future__ import annotations

import logging
import re
import sqlite3
import uuid
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from ..security.security_store import (
    AUDIT_ROLES,
    audit_event,
    require_role,
    require_user,
)
from ..core.modeling_scope import require_project_view, require_project_edit
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
from .sports_forecast_contract import (
    FORECAST_CONTRACT_METADATA_KEY,
    SportsForecastContractError,
    SportsForecastContractStore,
)
from ..sports_current_statcast.stage2_review import (
    CurrentGoldStage2ReviewError,
    current_gold_stage2_review,
)
from ..sports_current_statcast.stage3_eda import (
    Stage3EdaError,
    stage3_eda_metadata,
    stage3_eda_query,
)
from ..sports_current_statcast.stage3_treatments import (
    Stage3TreatmentError,
    adopt_treatment_policy,
    missing_detail,
    missing_preview,
    missing_summary,
    missing_table,
    outlier_detail,
    outlier_preview,
    outlier_summary,
    outlier_table,
    predicted_imputation_preview,
    save_treatment_policy_draft,
    treatment_policy,
)
from ..sports_current_statcast.stage3_feature_treatment_spec import (
    Stage3FeatureTreatmentSpecError,
    adopt_treatment_specification,
    save_treatment_specification_draft,
    treatment_specification,
)
from ..sports_current_statcast.stage3_feature_engineering import (
    Stage3FeatureEngineeringError,
    feature_detail,
    feature_inventory,
    feature_set_state,
    feature_studio_summary,
    register_feature_set,
    retire_feature_set,
    save_feature_set_draft,
)
from ..sports_current_statcast.stage3_split_balance import (
    Stage3SplitBalanceError,
    generate_automatic_split,
    register_split_contract,
    save_split_draft,
    split_balance_summary,
    split_contract_state,
    validate_manual_split,
)
from ..sports_current_statcast.stage3_model_laboratory import (
    Stage3ModelLaboratoryError,
    list_model_laboratory_runs,
    model_laboratory_summary,
    run_model_laboratory,
)
from ..sports_current_statcast.stage3_model_jobs import (
    cancel_unstarted_model_development_work,
    enqueue_model_development_job,
    get_model_development_job,
    list_model_development_jobs,
    plan_model_development_queue,
)
from ..sports_current_statcast.stage3_candidate_evaluation import (
    execute_model_refinement,
    plan_model_refinement,
    project_candidate_evaluation,
    project_stage3_downstream,
    register_project_research_handoff,
    request_candidate_analysis,
    save_finalist_selection,
    save_project_calibration_decision,
    save_project_challenger_decision,
    save_project_game_evaluation_decision,
)
from ..sports_current_statcast.stage3_executable_artifact import (
    cancel_unstarted_executable_artifact_work,
    enqueue_executable_artifact_job,
    executable_artifact_summary,
    get_executable_artifact_job,
    list_executable_artifact_jobs,
    plan_executable_artifact,
    recover_failed_executable_artifact_publication,
)
from ..sports_current_statcast.stage3_game_scoring import (
    Stage3GameScoringError,
    enqueue_game_scoring_job,
    game_scoring_summary,
    get_game_scoring_job,
)


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


def _forecast_contracts() -> SportsForecastContractStore:
    return SportsForecastContractStore(_service().database)


def _raise_forecast_contract_error(exc: SportsForecastContractError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc


def _raise_sports_backend_unavailable(exc: BaseException) -> None:
    raise HTTPException(
        status_code=503,
        detail={
            "code": "BACKEND_UNAVAILABLE",
            "message": "The ASP Model Studio persistence backend is temporarily unavailable.",
        },
    ) from exc


def _run_sports_operation(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except SportsForecastContractError as exc:
        _raise_forecast_contract_error(exc)
    except (PersistenceUnavailableError, sqlite3.Error, OSError) as exc:
        _raise_sports_backend_unavailable(exc)


def _forecast_contract_response(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": True,
        "contract": state.get("current"),
        "history": state.get("history") or [],
        "coverage": state.get("sourceCoverage"),
    }


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


def _authorize_sports_project(
    project_id: str,
    user: Dict[str, Any],
    permission: str,
) -> Dict[str, Any]:
    """Project authorization with sports-domain error classification.

    A reachable backend returning a missing project is not an availability
    failure, and sports surfaces must never expose the legacy ATLAS label.
    """

    try:
        existing = _authorize_project(project_id, user, permission)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PROJECT_NOT_REGISTERED",
                "message": (
                    "The ASP Model Studio sports project is not registered in "
                    "the local persistence database. Reopen or reconcile the project."
                ),
                "projectId": project_id,
            },
        ) from exc
    except (PersistenceUnavailableError, sqlite3.Error, OSError) as exc:
        _raise_sports_backend_unavailable(exc)
    assert existing is not None
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
        "owner_user_id": user.get("userId"),
        "created_at": _pick(payload, "createdAt", "created_at"),
        "updated_at": _pick(payload, "updatedAt", "updated_at", default=now_iso()),
        "created_by": user.get("userId"),
        "updated_by": user.get("userId"),
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


def _audit_project_write(
    service: PersistenceService,
    user: Dict[str, Any],
    record: Dict[str, Any],
    action: str,
    summary: str,
    **metadata: Any,
) -> None:
    # Project mutation events have one durable authority: the same transaction
    # as the project row. The security audit APIs project these canonical rows,
    # so a separate best-effort security-database write cannot leave a false
    # success event or split the commit across two WAL databases.
    service.audit.create({
        "audit_id": f"audit_{uuid.uuid4().hex}",
        "project_id": record["project_id"],
        "user_id": user.get("userId"),
        "action_type": action,
        "entity_type": "project",
        "entity_id": record["project_id"],
        "title": action.replace(".", " ").title(),
        "summary": summary,
        "created_at": now_iso(),
        "metadata_json": {
            **metadata, "projectId": record["project_id"],
            "summary": summary, "outcome": "success",
        },
    })


@router.post("/projects")
def create_project(payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    project_id = _id("project", payload, "projectId", "project_id")

    def operation() -> Dict[str, Any]:
        # Reuse the transaction-bound project/ACL service. BEGIN IMMEDIATE
        # precedes every existence/permission read, and nested repository and
        # creator membership writes all use this one connection.
        with _sharing_service()._project_acl_transaction() as sharing:
            service = sharing.persistence
            if service.projects.get(project_id) is not None:
                if not sharing.check_permission(user, "project", project_id, "edit").get("allowed"):
                    raise HTTPException(status_code=403, detail="Project creation requires a new project identity.")
                # Preserve the existing retry contract: conflict, no mutation,
                # no second creator membership or success audit event.
                raise HTTPException(status_code=409, detail="Project creation requires a new project identity.")
            service.sync_user(user)
            record = service.projects.create(_project_record(project_id, payload, user))
            sharing._bootstrap_project_owner(user, project_id)
            _audit_project_write(service, user, record, "project.created", f"Created project {record.get('project_name')}.")
            if record.get("template_id"):
                _audit_project_write(service, user, record, "template.selected", f"Selected template {record.get('template_id')}.", templateId=record["template_id"])
            return record

    record = _execute(operation)
    project = _execute(lambda: _project_with_durable_dataset_state(record, user))
    return {"ok": True, "project": project}


@router.get("/projects/{project_id}", dependencies=[Depends(require_project_view)])
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
    def operation() -> Dict[str, Any]:
        # Missing-ID PUT retains its creation contract, but it never becomes
        # an upsert. Authorization is evaluated against the actual locked row
        # and live permissions, not a snapshot taken before this transaction.
        with _sharing_service()._project_acl_transaction() as sharing:
            service = sharing.persistence
            existing = service.projects.get(project_id)
            if existing:
                if not sharing.check_permission(user, "project", project_id, "edit").get("allowed"):
                    raise HTTPException(status_code=403, detail="You do not have permission to perform this action on this project.")
                for key in ("ownerUserId", "owner_user_id"):
                    if key in payload and payload[key] != existing.get("owner_user_id"):
                        raise HTTPException(status_code=403, detail="Project ownership cannot be changed through project saves.")
                for key in ("createdBy", "created_by"):
                    if key in payload and payload[key] != existing.get("created_by"):
                        raise HTTPException(status_code=403, detail="Project provenance cannot be changed through project saves.")
            # Denials and duplicate requests reach no domain write or audit.
            service.sync_user(user)
            current = existing or {}
            existing_metadata = current.get("metadata_json") or {}
            incoming_metadata = _pick(payload, "metadata", "metadataJson", "metadata_json", default={}) or {}
            incoming_metadata = dict(incoming_metadata) if isinstance(incoming_metadata, dict) else {}
            # The forecast contract is server authority. Its current value was
            # read under this write lock and cannot change before our UPDATE.
            incoming_metadata.pop(FORECAST_CONTRACT_METADATA_KEY, None)
            merged = {
                "projectName": current.get("project_name"),
                "projectType": current.get("project_type"),
                "workflowType": current.get("workflow_type"),
                "templateId": current.get("template_id"),
                "status": current.get("status"),
                "createdAt": current.get("created_at"),
                **payload,
            }
            merged["metadata"] = {**existing_metadata, **incoming_metadata}
            record = _project_record(project_id, merged, user)
            if existing:
                record["owner_user_id"] = existing.get("owner_user_id")
                record["created_by"] = existing.get("created_by")
                with service.database.connection() as connection:
                    record = service.projects.update_locked(record, connection=connection)
            else:
                record = service.projects.create(record)
                sharing._bootstrap_project_owner(user, project_id)
            _audit_project_write(service, user, record, "project.saved", f"Saved project {record.get('project_name')}.")
            return record

    record = _execute(operation)
    project = _execute(lambda: _project_with_durable_dataset_state(record, user))
    return {"ok": True, "project": project}


@router.get("/projects/{project_id}/sports/forecast-contract", dependencies=[Depends(require_project_view)])
def get_sports_forecast_contract(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "view")
    contract = _run_sports_operation(lambda: _forecast_contracts().get(project_id))
    return _forecast_contract_response(contract)


@router.get("/projects/{project_id}/sports/evidence-dataset", dependencies=[Depends(require_project_view)])
def get_sports_evidence_dataset(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "view")
    linkage = _run_sports_operation(
        lambda: _forecast_contracts().get_evidence_dataset(project_id)
    )
    return {"ok": True, "linkage": linkage}


@router.get("/projects/{project_id}/sports/stage2-data-review", dependencies=[Depends(require_project_view)])
def get_sports_stage2_data_review(
    project_id: str,
    season: int | None = None,
    limit: int = Query(default=25, ge=1, le=50),
    sample: str = Query(default="head", pattern="^(head|random)$"),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Read the exact current-Gold matrix authorized by this project's link."""

    _authorize_sports_project(project_id, user, "view")
    try:
        review = current_gold_stage2_review(
            _service().database,
            project_id,
            season=season,
            limit=limit,
            sample=sample,
        )
    except SportsForecastContractError as exc:
        _raise_forecast_contract_error(exc)
    except CurrentGoldStage2ReviewError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc
    except (PersistenceUnavailableError, sqlite3.Error, OSError) as exc:
        _raise_sports_backend_unavailable(exc)
    return {"ok": True, "review": review}


@router.get("/projects/{project_id}/sports/stage3-eda/metadata", dependencies=[Depends(require_project_view)])
def get_sports_stage3_eda_metadata(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Return the redacted, development-only Stage 3 analytical authority."""

    _authorize_sports_project(project_id, user, "view")
    try:
        return stage3_eda_metadata(_service().database, project_id)
    except SportsForecastContractError as exc:
        _raise_forecast_contract_error(exc)
    except Stage3EdaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc
    except (PersistenceUnavailableError, sqlite3.Error, OSError) as exc:
        _raise_sports_backend_unavailable(exc)


@router.post("/projects/{project_id}/sports/stage3-eda/query", dependencies=[Depends(require_project_view)])
def post_sports_stage3_eda_query(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Run one bounded aggregate query over project-bound development rows."""

    _authorize_sports_project(project_id, user, "view")
    try:
        return stage3_eda_query(_service().database, project_id, payload)
    except SportsForecastContractError as exc:
        _raise_forecast_contract_error(exc)
    except Stage3EdaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc
    except (PersistenceUnavailableError, sqlite3.Error, OSError) as exc:
        _raise_sports_backend_unavailable(exc)


def _run_stage3_treatment(operation: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    try:
        return operation()
    except SportsForecastContractError as exc:
        _raise_forecast_contract_error(exc)
    except Stage3TreatmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc
    except Stage3FeatureTreatmentSpecError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc
    except Stage3EdaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc
    except (PersistenceUnavailableError, sqlite3.Error, OSError) as exc:
        _raise_sports_backend_unavailable(exc)


@router.get("/projects/{project_id}/sports/stage3-treatment/{kind}/summary", dependencies=[Depends(require_project_view)])
def get_sports_stage3_treatment_summary(
    project_id: str,
    kind: str,
    authority_key: str = Header(default="", alias="X-Stage3-Authority-Key"),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Return evaluated project-bound development-only treatment counts."""

    _authorize_sports_project(project_id, user, "view")
    normalized = kind.lower()
    if normalized not in {"outliers", "missing"}:
        raise HTTPException(status_code=404, detail="Unknown Stage 3 treatment studio.")
    operation = outlier_summary if normalized == "outliers" else missing_summary
    return _run_stage3_treatment(
        lambda: operation(
            _service().database,
            project_id,
            authority_key=authority_key,
        )
    )


@router.get("/projects/{project_id}/sports/stage3-treatment/{kind}/policy", dependencies=[Depends(require_project_view)])
def get_sports_stage3_treatment_policy(
    project_id: str,
    kind: str,
    authority_key: str = Header(default="", alias="X-Stage3-Authority-Key"),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Return immutable draft/adopted versions for the exact current authority."""

    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_treatment(
        lambda: treatment_policy(
            _service().database,
            project_id,
            kind,
            authority_key=authority_key,
        )
    )


@router.post("/projects/{project_id}/sports/stage3-treatment/missing/predicted-preview", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_predicted_imputation_preview(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Run one explicit bounded cross-fitted preprocessing preview."""

    _authorize_sports_project(project_id, user, "edit")
    actor = str(user.get("userId") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="Authenticated user identity is required.")
    return _run_stage3_treatment(
        lambda: predicted_imputation_preview(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.post("/projects/{project_id}/sports/stage3-treatment/{kind}/policy/draft", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_treatment_policy_draft(
    project_id: str,
    kind: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Append one immutable preprocessing-policy draft version."""

    _authorize_sports_project(project_id, user, "edit")
    actor = str(user.get("userId") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="Authenticated user identity is required.")
    return _run_stage3_treatment(
        lambda: save_treatment_policy_draft(
            _service().database,
            project_id,
            kind,
            payload,
            actor_user_id=actor,
        )
    )


@router.post("/projects/{project_id}/sports/stage3-treatment/{kind}/policy/adopt", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_treatment_policy_adopt(
    project_id: str,
    kind: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Append an adopted version copied from one exact immutable draft."""

    _authorize_sports_project(project_id, user, "edit")
    actor = str(user.get("userId") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="Authenticated user identity is required.")
    return _run_stage3_treatment(
        lambda: adopt_treatment_policy(
            _service().database,
            project_id,
            kind,
            payload,
            actor_user_id=actor,
        )
    )


@router.get("/projects/{project_id}/sports/stage3-treatment/specification", dependencies=[Depends(require_project_view)])
def get_sports_stage3_treatment_specification(
    project_id: str,
    authority_key: str = Header(default="", alias="X-Stage3-Authority-Key"),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Resolve the canonical workbook authority against the live feature catalog."""

    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_treatment(
        lambda: treatment_specification(
            _service().database,
            project_id,
            authority_key=authority_key,
        )
    )


@router.post("/projects/{project_id}/sports/stage3-treatment/specification/draft", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_treatment_specification_draft(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Atomically append linked Outlier/Missing drafts and one binding receipt."""

    _authorize_sports_project(project_id, user, "edit")
    actor = str(user.get("userId") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="Authenticated user identity is required.")
    return _run_stage3_treatment(
        lambda: save_treatment_specification_draft(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.post("/projects/{project_id}/sports/stage3-treatment/specification/adopt", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_treatment_specification_adopt(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Fail closed until every combined-spec semantic/executable blocker is resolved."""

    _authorize_sports_project(project_id, user, "edit")
    actor = str(user.get("userId") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="Authenticated user identity is required.")
    return _run_stage3_treatment(
        lambda: adopt_treatment_specification(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.post("/projects/{project_id}/sports/stage3-treatment/{kind}/{action}", dependencies=[Depends(require_project_view)])
def post_sports_stage3_treatment_query(
    project_id: str,
    kind: str,
    action: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Run one bounded aggregate table, detail, or treatment preview."""

    _authorize_sports_project(project_id, user, "view")
    handlers: Dict[tuple[str, str], Callable[[Any, str, Any], Dict[str, Any]]] = {
        ("outliers", "table"): outlier_table,
        ("outliers", "detail"): outlier_detail,
        ("outliers", "preview"): outlier_preview,
        ("missing", "table"): missing_table,
        ("missing", "detail"): missing_detail,
        ("missing", "preview"): missing_preview,
    }
    handler = handlers.get((kind.lower(), action.lower()))
    if handler is None:
        raise HTTPException(status_code=404, detail="Unknown Stage 3 treatment operation.")
    return _run_stage3_treatment(
        lambda: handler(_service().database, project_id, payload)
    )


def _run_stage3_prepare(operation: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """Translate bounded Feature/Split authority errors without hiding blockers."""

    try:
        return operation()
    except SportsForecastContractError as exc:
        _raise_forecast_contract_error(exc)
    except (
        Stage3FeatureEngineeringError,
        Stage3SplitBalanceError,
        Stage3ModelLaboratoryError,
        Stage3GameScoringError,
    ) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc
    except Stage3TreatmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc
    except Stage3EdaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc
    except (PersistenceUnavailableError, sqlite3.Error, OSError) as exc:
        _raise_sports_backend_unavailable(exc)


@router.get("/projects/{project_id}/sports/stage3-feature-engineering/summary", dependencies=[Depends(require_project_view)])
def get_sports_stage3_feature_engineering_summary(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: feature_studio_summary(project_id, _service().database)
    )


@router.post("/projects/{project_id}/sports/stage3-feature-engineering/inventory", dependencies=[Depends(require_project_view)])
def post_sports_stage3_feature_inventory(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: feature_inventory(project_id, _service().database, payload)
    )


@router.get("/projects/{project_id}/sports/stage3-feature-engineering/feature/{feature_name}", dependencies=[Depends(require_project_view)])
def get_sports_stage3_feature_detail(
    project_id: str,
    feature_name: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: feature_detail(project_id, _service().database, feature_name)
    )


@router.get("/projects/{project_id}/sports/stage3-feature-engineering/feature-sets", dependencies=[Depends(require_project_view)])
def get_sports_stage3_feature_sets(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: feature_set_state(project_id, _service().database)
    )


def _stage3_actor(user: Dict[str, Any]) -> str:
    actor = str(user.get("userId") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="Authenticated user identity is required.")
    return actor


@router.post("/projects/{project_id}/sports/stage3-feature-engineering/feature-sets/draft", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_feature_set_draft(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: save_feature_set_draft(
            project_id, _service().database, payload, actor_user_id=actor
        )
    )


@router.post("/projects/{project_id}/sports/stage3-feature-engineering/feature-sets/register", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_feature_set_register(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: register_feature_set(
            project_id, _service().database, payload, actor_user_id=actor
        )
    )


@router.post("/projects/{project_id}/sports/stage3-feature-engineering/feature-sets/retire", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_feature_set_retire(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: retire_feature_set(
            project_id, _service().database, payload, actor_user_id=actor
        )
    )


@router.get("/projects/{project_id}/sports/stage3-split-balance/summary", dependencies=[Depends(require_project_view)])
def get_sports_stage3_split_balance_summary(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: split_balance_summary(project_id, _service().database)
    )


@router.post("/projects/{project_id}/sports/stage3-split-balance/automatic", dependencies=[Depends(require_project_view)])
def post_sports_stage3_automatic_split(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: generate_automatic_split(project_id, _service().database, payload)
    )


@router.post("/projects/{project_id}/sports/stage3-split-balance/manual/validate", dependencies=[Depends(require_project_view)])
def post_sports_stage3_manual_split_validation(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: validate_manual_split(project_id, _service().database, payload)
    )


@router.get("/projects/{project_id}/sports/stage3-split-balance/contracts", dependencies=[Depends(require_project_view)])
def get_sports_stage3_split_contracts(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: split_contract_state(project_id, _service().database)
    )


@router.post("/projects/{project_id}/sports/stage3-split-balance/contracts/draft", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_split_contract_draft(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: save_split_draft(
            project_id, _service().database, payload, actor_user_id=actor
        )
    )


@router.post("/projects/{project_id}/sports/stage3-split-balance/contracts/register", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_split_contract_register(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: register_split_contract(
            project_id, _service().database, payload, actor_user_id=actor
        )
    )


@router.get("/projects/{project_id}/sports/stage3-model-laboratory/summary", dependencies=[Depends(require_project_view)])
def get_sports_stage3_model_laboratory_summary(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Resolve the exact project/Gold/feature/split/treatment run authority."""

    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: model_laboratory_summary(_service().database, project_id)
    )


@router.get("/projects/{project_id}/sports/stage3-model-laboratory/runs", dependencies=[Depends(require_project_view)])
def get_sports_stage3_model_laboratory_runs(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """List verified immutable development-only comparison receipts."""

    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: list_model_laboratory_runs(_service().database, project_id)
    )


@router.post("/projects/{project_id}/sports/stage3-model-laboratory/plan", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_model_laboratory_plan(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Validate and count a development queue without fitting anything."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: {
            "ok": True,
            "plan": plan_model_development_queue(
                _service().database, project_id, payload, actor_user_id=actor
            ),
        }
    )


@router.get("/projects/{project_id}/sports/stage3-model-laboratory/jobs", dependencies=[Depends(require_project_view)])
def get_sports_stage3_model_laboratory_jobs(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """List project-scoped model-development jobs and persisted progress."""

    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: list_model_development_jobs(_service().database, project_id)
    )


@router.get("/projects/{project_id}/sports/stage3-model-laboratory/jobs/{job_id}", dependencies=[Depends(require_project_view)])
def get_sports_stage3_model_laboratory_job(
    project_id: str,
    job_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Read one persisted job without touching providers or scientific data."""

    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: get_model_development_job(
            _service().database, project_id, job_id
        )
    )


@router.post(
    "/projects/{project_id}/sports/stage3-model-laboratory/jobs",
    status_code=202,
 dependencies=[Depends(require_project_edit)])
def post_sports_stage3_model_laboratory_job(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Explicitly enqueue one safely bounded multi-candidate batch plan."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: enqueue_model_development_job(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.post(
    "/projects/{project_id}/sports/stage3-model-laboratory/jobs/{job_id}/cancel-unstarted"
, dependencies=[Depends(require_project_edit)])
def post_sports_stage3_model_laboratory_cancel_unstarted(
    project_id: str,
    job_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Cancel only queued/unstarted configurations; preserve active evidence."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: cancel_unstarted_model_development_work(
            _service().database,
            project_id,
            job_id,
            actor_user_id=actor,
        )
    )


@router.get("/projects/{project_id}/sports/stage3-executable-artifact", dependencies=[Depends(require_project_view)])
def get_sports_stage3_executable_artifact(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Read exact challenger/artifact readiness without fitting or opening OOT."""

    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: executable_artifact_summary(_service().database, project_id)
    )


@router.post("/projects/{project_id}/sports/stage3-executable-artifact/plan", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_executable_artifact_plan(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Review one immutable six-fit artifact plan before any work is queued."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: plan_executable_artifact(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.get("/projects/{project_id}/sports/stage3-executable-artifact/jobs", dependencies=[Depends(require_project_view)])
def get_sports_stage3_executable_artifact_jobs(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """List persisted artifact jobs without touching scientific data."""

    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: list_executable_artifact_jobs(_service().database, project_id)
    )


@router.post(
    "/projects/{project_id}/sports/stage3-executable-artifact/jobs",
    status_code=202,
 dependencies=[Depends(require_project_edit)])
def post_sports_stage3_executable_artifact_job(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Queue the exact reviewed OOF-reproduction and final-fit plan."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: enqueue_executable_artifact_job(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.get(
    "/projects/{project_id}/sports/stage3-executable-artifact/jobs/{job_id}"
, dependencies=[Depends(require_project_view)])
def get_sports_stage3_executable_artifact_job(
    project_id: str,
    job_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Read genuine persisted artifact progress and terminal verification."""

    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: get_executable_artifact_job(
            _service().database,
            project_id,
            job_id,
        )
    )


@router.post(
    "/projects/{project_id}/sports/stage3-executable-artifact/jobs/{job_id}/cancel-unstarted"
, dependencies=[Depends(require_project_edit)])
def post_sports_stage3_executable_artifact_cancel_unstarted(
    project_id: str,
    job_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Cancel only unstarted work while retaining verified fold checkpoints."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: cancel_unstarted_executable_artifact_work(
            _service().database,
            project_id,
            job_id,
            actor_user_id=actor,
        )
    )


@router.post(
    "/projects/{project_id}/sports/stage3-executable-artifact/jobs/{job_id}/recover-publication"
, dependencies=[Depends(require_project_edit)])
def post_sports_stage3_executable_artifact_recover_publication(
    project_id: str,
    job_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Recover a fully verified private bundle without repeating any fit."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: recover_failed_executable_artifact_publication(
            _service().database,
            project_id,
            job_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.get("/projects/{project_id}/sports/stage3-game-scoring", dependencies=[Depends(require_project_view)])
def get_sports_stage3_game_scoring(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Read provider-free governed-game readiness and verified results."""

    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: game_scoring_summary(_service().database, project_id)
    )


@router.post(
    "/projects/{project_id}/sports/stage3-game-scoring/jobs",
    status_code=202,
 dependencies=[Depends(require_project_edit)])
def post_sports_stage3_game_scoring_job(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Queue only games with complete governed point-in-time evidence."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: enqueue_game_scoring_job(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.get("/projects/{project_id}/sports/stage3-game-scoring/jobs/{job_id}", dependencies=[Depends(require_project_view)])
def get_sports_stage3_game_scoring_job(
    project_id: str,
    job_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Read one persisted governed-game scoring job."""

    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: get_game_scoring_job(_service().database, project_id, job_id)
    )


@router.get("/projects/{project_id}/sports/stage3-candidate-evaluation", dependencies=[Depends(require_project_view)])
def get_sports_stage3_candidate_evaluation(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Read verified project-bound candidate evidence without fitting."""

    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: project_candidate_evaluation(_service().database, project_id)
    )


@router.post("/projects/{project_id}/sports/stage3-candidate-evaluation/finalists", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_candidate_finalists(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: save_finalist_selection(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.post("/projects/{project_id}/sports/stage3-candidate-evaluation/analysis", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_candidate_analysis(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: request_candidate_analysis(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.post("/projects/{project_id}/sports/stage3-model-refinement/plan", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_model_refinement_plan(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: plan_model_refinement(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.post("/projects/{project_id}/sports/stage3-model-refinement/execute", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_model_refinement_execute(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Explicitly queue a supported reduced challenger from one finalist."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: execute_model_refinement(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.get("/projects/{project_id}/sports/stage3-downstream", dependencies=[Depends(require_project_view)])
def get_sports_stage3_downstream(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Read the project-bound Steps 12-15 development decision state."""

    _authorize_sports_project(project_id, user, "view")
    return _run_stage3_prepare(
        lambda: project_stage3_downstream(_service().database, project_id)
    )


@router.post("/projects/{project_id}/sports/stage3-downstream/calibration", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_downstream_calibration(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Persist an explicit raw/deferred calibration decision without fitting."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: save_project_calibration_decision(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.post("/projects/{project_id}/sports/stage3-downstream/game-evaluation", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_downstream_game_evaluation(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Record the exact game-evaluation limitation for a current finalist."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: save_project_game_evaluation_decision(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.post("/projects/{project_id}/sports/stage3-downstream/selection", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_downstream_selection(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Select a research challenger without declaring a champion or promotion."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: save_project_challenger_decision(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.post("/projects/{project_id}/sports/stage3-downstream/registry", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_downstream_registry(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Record a metadata-only research handoff; never export or deploy it."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: register_project_research_handoff(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.post("/projects/{project_id}/sports/stage3-model-laboratory/run", dependencies=[Depends(require_project_edit)])
def post_sports_stage3_model_laboratory_run(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Explicitly run only requested first-pass candidates over five folds."""

    _authorize_sports_project(project_id, user, "edit")
    actor = _stage3_actor(user)
    return _run_stage3_prepare(
        lambda: run_model_laboratory(
            _service().database,
            project_id,
            payload,
            actor_user_id=actor,
        )
    )


@router.put("/projects/{project_id}/sports/evidence-dataset", dependencies=[Depends(require_project_edit)])
def select_sports_evidence_dataset(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "edit")
    linkage = _run_sports_operation(
        lambda: _forecast_contracts().link_evidence_dataset(
            project_id,
            str(_pick(payload, "registrationId", "registration_id", default="") or ""),
            user_id=str(user.get("userId") or ""),
        )
    )
    audit_event(
        "sports.evidence_dataset.selected",
        "sports_dataset_registration",
        str(linkage.get("registrationId") or ""),
        "success",
        user_id=user.get("userId"),
        metadata={
            "projectId": project_id,
            "datasetId": linkage.get("datasetId"),
            "datasetVersionId": linkage.get("datasetVersionId"),
            "activationRevision": linkage.get("activationRevision"),
            "summary": "Selected the project's exact sports evidence dataset.",
        },
    )
    return {"ok": True, "linkage": linkage}


@router.put("/projects/{project_id}/sports/forecast-contract", dependencies=[Depends(require_project_edit)])
def save_sports_forecast_contract(
    project_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    _authorize_sports_project(project_id, user, "edit")
    contract = _run_sports_operation(
        lambda: _forecast_contracts().save(
            project_id,
            payload,
            user_id=str(user.get("userId") or ""),
        )
    )
    current = contract.get("current") or {}
    audit_event(
        "sports.forecast_contract.registered",
        "sports_forecast_contract",
        str(current.get("contractId") or project_id),
        "success",
        user_id=user.get("userId"),
        metadata={
            "projectId": project_id,
            "version": contract.get("currentVersion"),
            "temporalDesignMode": current.get("temporalDesignMode"),
            "saveDisposition": contract.get("saveDisposition"),
            "summary": "Registered the MLB Stage 1 forecast contract.",
        },
    )
    return _forecast_contract_response(contract)


@router.delete("/projects/{project_id}", dependencies=[Depends(require_project_edit)])
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


@router.get("/projects/{project_id}/workflow-state", dependencies=[Depends(require_project_view)])
def get_workflow_state(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "view")
    record = _execute(lambda: _service().projects.get_workflow_state(project_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Workflow state has not been saved for this project.")
    visible_record = _execute(lambda: _workflow_state_for_dataset_acl(record, user))
    return {"ok": True, "workflowState": _api_record(visible_record)}


@router.put("/projects/{project_id}/workflow-state", dependencies=[Depends(require_project_edit)])
def save_workflow_state(project_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "edit", allow_missing=True)
    previous_completed = set()

    def operation() -> Dict[str, Any]:
        service = _service()
        service.ensure_project(project_id, user)
        previous = service.projects.get_workflow_state(project_id) or {}
        previous_completed.update(previous.get("completed_steps_json") or [])
        service.projects.upsert_workflow_history(
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
        # Historical completion is append-only, but the effective resume point
        # must be recalculated after every save from the exact durable active
        # dataset identity and current canonical evidence.  This never trusts
        # browser status fields or selects a first/latest dataset version.
        return service.project_dataset_activations.reconcile_workflow_after_history_update(
            project_id=project_id,
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


@router.get("/projects/{project_id}/evidence", dependencies=[Depends(require_project_view)])
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


@router.post("/projects/{project_id}/evidence", dependencies=[Depends(require_project_edit)])
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


@router.put("/projects/{project_id}/evidence/{evidence_id}", dependencies=[Depends(require_project_edit)])
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


@router.get("/projects/{project_id}/runs", dependencies=[Depends(require_project_view)])
def list_runs(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "view")
    payload = _child_list(project_id, "runs")
    items = payload.pop("items")
    return {**payload, "runs": items}


@router.post("/projects/{project_id}/runs", dependencies=[Depends(require_project_edit)])
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


@router.get("/projects/{project_id}/decisions", dependencies=[Depends(require_project_view)])
def list_decisions(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "view")
    payload = _child_list(project_id, "decisions")
    items = payload.pop("items")
    return {**payload, "decisions": items}


@router.post("/projects/{project_id}/decisions", dependencies=[Depends(require_project_edit)])
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


@router.get("/projects/{project_id}/documentation", dependencies=[Depends(require_project_view)])
def list_documentation(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "view")
    payload = _child_list(project_id, "documentation")
    items = payload.pop("items")
    return {**payload, "documentation": items}


@router.post("/projects/{project_id}/documentation", dependencies=[Depends(require_project_edit)])
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


@router.get("/projects/{project_id}/exports", dependencies=[Depends(require_project_view)])
def list_exports(project_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    _authorize_project(project_id, user, "view")
    payload = _child_list(project_id, "exports")
    items = payload.pop("items")
    return {**payload, "exports": items}


@router.post("/projects/{project_id}/exports", dependencies=[Depends(require_project_edit)])
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

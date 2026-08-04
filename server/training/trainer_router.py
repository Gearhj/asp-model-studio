# server/training/trainer_router.py

from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .trainer_service import TRAINER
from .training_job_service import TRAINING_JOBS
from .training_job_types import TrainingJobRequest, TrainingPortfolioRequest
from .training_preflight_service import TrainingTargetSemanticsError
from .candidate_contract import (
    CandidateContractError,
    assert_candidate_contract_intact,
    canonical_contract_hash,
    classify_selection_integrity,
)
from ..core.json_safety import json_safe
from ..core.dataset_store import DATASTORE
from ..core.modeling_scope import authorize_modeling_scope
from ..core.result_store import RESULTS
from ..core.session_checkpoint import schedule_checkpoint_save
from ..datasets.dataset_identity import assert_expected_active_identity
from ..persistence.service import get_persistence_service
from ..persistence.repositories.holdout_governance_repository import (
    HoldoutGovernanceConflictError,
    HoldoutGovernanceStateError,
)
from ..security.security_store import audit_event, require_user


router = APIRouter()


class ModelSelectionDecisionRequest(BaseModel):
    project_id: str
    dataset_id: str = ""
    dataset_version_id: str = ""
    # Compatibility expectation only; canonical identity remains the exact
    # Dataset Library version resolved by the backend.
    dataset_version: str = ""
    training_job_id: str
    validation_design_id: str = ""
    validation_design_version: str = ""
    champion_model: str
    challenger_models: list[str] = Field(default_factory=list)
    status: Literal["proposed", "approved", "rejected"] = "proposed"
    primary_metric: str = ""
    rationale: str = Field(min_length=10, max_length=4000)
    metric_justification: str = Field(default="", max_length=4000)
    interpretability_justification: str = Field(default="", max_length=4000)
    calibration_considerations: str = Field(default="", max_length=4000)
    fairness_validation_prerequisites: str = Field(default="", max_length=4000)
    deployment_constraints: str = Field(default="", max_length=4000)
    reviewer_notes: str = Field(default="", max_length=4000)


def _current_store(proxy: Any) -> Any:
    current = getattr(proxy, "current", None)
    return current() if callable(current) else proxy


def _record_matches_identity(
    record: dict[str, Any],
    identity: dict[str, Any],
) -> bool:
    if not record:
        return False
    if any(
        not str(record.get(key) or "").strip()
        or str(record.get(key) or "") != str(identity.get(key) or "")
        for key in ("project_id", "dataset_id", "dataset_version_id")
    ):
        return False
    compatibility_version = str(record.get("dataset_version") or "").strip()
    return (
        not compatibility_version
        or compatibility_version == str(identity["dataset_version_id"])
    )


def _ui_decision_from_durable(record: dict[str, Any]) -> dict[str, Any]:
    snapshot = (
        record.get("ranking_snapshot_json")
        if isinstance(record.get("ranking_snapshot_json"), list)
        else []
    )
    if canonical_contract_hash(snapshot) != str(
        record.get("ranking_snapshot_hash") or ""
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The durable candidate ranking snapshot failed canonical hash verification."
            ),
        )
    champion = next(
        (
            row
            for row in snapshot
            if isinstance(row, dict)
            and str(row.get("candidate_id") or "")
            == str(record.get("candidate_id") or "")
        ),
        {},
    )
    if (
        str(champion.get("candidate_contract_hash") or "")
        != str(record.get("selected_candidate_contract_hash") or "")
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The durable selected candidate contract hash does not match "
                "the immutable ranking snapshot."
            ),
        )
    challenger_models = [
        str(row.get("key") or row.get("algorithm_id") or "")
        for row in snapshot
        if isinstance(row, dict)
        and str(row.get("candidate_id") or "")
        != str(record.get("candidate_id") or "")
        and str(row.get("key") or row.get("algorithm_id") or "")
    ]
    return {
        "decision_id": record.get("candidate_decision_id"),
        "candidate_decision_id": record.get("candidate_decision_id"),
        "decision_status": record.get("decision_status"),
        "status": record.get("decision_status") or "locked",
        "project_id": record.get("project_id"),
        "dataset_id": record.get("dataset_id"),
        "dataset_version_id": record.get("dataset_version_id"),
        "dataset_version": record.get("dataset_version_id"),
        "feature_manifest_id": record.get("feature_manifest_id"),
        "feature_manifest_hash": record.get("feature_manifest_hash"),
        "treatment_manifest_id": record.get("treatment_manifest_id"),
        "treatment_manifest_hash": record.get("treatment_manifest_hash"),
        "materialization_id": record.get("materialization_id"),
        "final_holdout_partition_id": record.get(
            "final_holdout_partition_id"
        ),
        "validation_design_id": record.get("validation_design_id"),
        "validation_design_version": record.get(
            "validation_design_version_id"
        ),
        "split_id": record.get("split_id"),
        "training_job_id": record.get("training_job_id"),
        "training_run_id": record.get("training_run_id"),
        "candidate_id": record.get("candidate_id"),
        "selected_candidate_id": record.get("candidate_id"),
        "selected_candidate_contract_hash": record.get(
            "selected_candidate_contract_hash"
        ),
        "champion_model": champion.get("key")
        or champion.get("algorithm_id"),
        "challenger_models": challenger_models,
        "challenger_candidate_ids": [
            str(row.get("candidate_id") or "")
            for row in snapshot
            if isinstance(row, dict)
            and str(row.get("candidate_id") or "")
            != str(record.get("candidate_id") or "")
            and str(row.get("candidate_id") or "")
        ],
        "primary_metric": record.get("selection_metric_name"),
        "locked_threshold": record.get("locked_threshold"),
        "threshold_source": record.get("threshold_source"),
        "threshold_locked_at": record.get("threshold_locked_at"),
        "threshold_policy_hash": record.get("threshold_policy_hash"),
        "rationale": record.get("selection_rationale"),
        "selection_metric": {
            "selection_metric_name": record.get("selection_metric_name"),
            "selection_metric_value": record.get("selection_metric_value"),
            "selection_metric_source": record.get("selection_metric_source"),
            "selection_partition_id": record.get("selection_partition_id"),
            "fold_definition_id": record.get("fold_definition_id"),
            "fold_count": record.get("fold_count"),
            "fold_values": record.get("fold_values_json") or [],
            "mean": record.get("selection_metric_mean"),
            "standard_deviation": record.get("selection_metric_std"),
            "out_of_fold_prediction_artifact_id": record.get(
                "out_of_fold_prediction_artifact_id"
            ),
            "threshold_source": record.get("threshold_source"),
            "calibration_source": record.get("calibration_source"),
            "created_at": record.get("selection_metric_created_at"),
        },
        "candidate_metrics": {
            str(row.get("key") or row.get("algorithm_id") or ""): row
            for row in snapshot
            if isinstance(row, dict)
        },
        "selection_integrity_status": record.get(
            "selection_integrity_status"
        ),
        "holdout_isolation_status": record.get(
            "holdout_isolation_status"
        ),
        "actor": {"user_id": record.get("actor")},
        "selection_ranking_snapshot_hash": record.get(
            "ranking_snapshot_hash"
        ),
        "selection_locked_at": record.get("selection_locked_at"),
        "decided_at": record.get("selection_locked_at"),
        "decision_contract_hash": record.get("decision_contract_hash"),
        "durable": True,
    }


def _last_summary_context_error(
    summary: dict[str, Any],
    identity: dict[str, Any],
    store: Any,
) -> str:
    """Fail closed unless the summary matches the full active training input."""
    manifest = (
        store.meta.get("feature_manifest")
        if isinstance(store.meta.get("feature_manifest"), dict)
        else {}
    )
    split_record = (
        store.meta.get("split_record")
        if isinstance(store.meta.get("split_record"), dict)
        else {}
    )
    validation_design = (
        split_record.get("validation_design")
        if isinstance(split_record.get("validation_design"), dict)
        else {}
    )
    top_level_design = (
        store.meta.get("validation_design")
        if isinstance(store.meta.get("validation_design"), dict)
        else {}
    )
    if not _record_matches_identity(manifest, identity):
        return (
            "The last training run cannot be used because the active feature "
            "manifest is missing or belongs to another dataset version."
        )
    if not _record_matches_identity(split_record, identity):
        return (
            "The last training run cannot be used because the active split is "
            "missing or belongs to another dataset version."
        )
    if not _record_matches_identity(validation_design, identity):
        return (
            "The last training run cannot be used because the active "
            "Validation Design is missing or belongs to another dataset version."
        )
    if top_level_design and (
        not _record_matches_identity(top_level_design, identity)
        or str(top_level_design.get("validation_design_id") or "")
        != str(validation_design.get("validation_design_id") or "")
        or str(top_level_design.get("design_version") or "")
        != str(validation_design.get("design_version") or "")
    ):
        return (
            "The last training run cannot be used because the active "
            "Validation Design records are inconsistent."
        )
    if str(store.meta.get("split_status") or "") != "current" or any(
        part is None for part in store.get_splits()
    ):
        return (
            "The last training run cannot be used because the governed "
            "validation split is no longer current."
        )

    manifest_version = str(
        manifest.get("manifest_hash") or manifest.get("manifest_version") or ""
    )
    split_id = str(split_record.get("split_id") or "")
    validation_design_id = str(
        validation_design.get("validation_design_id") or ""
    )
    validation_design_version = str(
        validation_design.get("design_version") or ""
    )
    if (
        not manifest_version
        or not split_id
        or not validation_design_id
        or not validation_design_version
        or str(split_record.get("feature_manifest_version") or "")
        != manifest_version
        or str(validation_design.get("feature_manifest_hash") or "")
        != manifest_version
    ):
        return (
            "The last training run cannot be used because the active feature, "
            "split, and Validation Design contract is incomplete or inconsistent."
        )

    expected = {
        "project_id": str(identity["project_id"]),
        "dataset_id": str(identity["dataset_id"]),
        "dataset_version_id": str(identity["dataset_version_id"]),
        "feature_manifest_version": manifest_version,
        "split_id": split_id,
        "validation_design_id": validation_design_id,
        "validation_design_version": validation_design_version,
    }
    if any(
        not str(summary.get(key) or "").strip()
        or str(summary.get(key) or "") != value
        for key, value in expected.items()
    ):
        return (
            "The last training run does not match the active dataset, feature "
            "manifest, split, or Validation Design. Train models again."
        )
    compatibility_version = str(summary.get("dataset_version") or "").strip()
    if (
        compatibility_version
        and compatibility_version != str(identity["dataset_version_id"])
    ):
        return (
            "The last training run contains conflicting dataset version "
            "identifiers. Train models again."
        )
    try:
        summary_revision = int(summary.get("data_revision"))
    except (TypeError, ValueError):
        summary_revision = -1
    if summary_revision != int(store.data_revision):
        return (
            "The last training run belongs to an older governed data revision. "
            "Train models again."
        )
    for record, label in (
        (split_record, "split"),
        (validation_design, "Validation Design"),
    ):
        if record.get("data_revision") not in (None, ""):
            try:
                record_revision = int(record.get("data_revision"))
            except (TypeError, ValueError):
                record_revision = -1
            if record_revision != int(store.data_revision):
                return (
                    f"The active {label} belongs to an older governed data "
                    "revision. Rebuild Balance & Split."
                )
    return ""


# Stage 4 (ATLAS_MODELING_STATE_ISOLATION_PLAN.md): TRAINING_JOBS project
# isolation and authorization. This RETIRES the Stage 2B/3 temporary
# `_connect_datastore_scope`/raw `set_active_project_id(...)` workaround
# that used to live here -- every endpoint below now calls the real
# `authorize_modeling_scope(user, project_id, permission)` directly, which
# both authorizes AND sets the same ContextVar the old workaround set as a
# side effect, so DATASTORE connectivity (the original reason the
# workaround existed) is preserved with no separate mechanism left behind.
# See training_job_service.py's module-level comment for how job ownership/
# scope is threaded through job creation and background execution.


@router.get("/model/train/selection")
def get_training_model_selection(
    project_id: str = Query(...),
    dataset_id: str = Query(...),
    dataset_version_id: str = Query(...),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "view")
    try:
        portfolio = TRAINING_JOBS.get_portfolio(
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
        )
        return json_safe({"ok": True, **portfolio})
    except HTTPException:
        raise
    except TrainingTargetSemanticsError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="ATLAS could not read the governed model portfolio.",
        ) from exc


@router.post("/model/train/selection")
def save_training_model_selection(
    request: TrainingPortfolioRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, request.project_id, "edit")
    try:
        portfolio = TRAINING_JOBS.save_portfolio(
            request,
            persisted_by=str(user.get("userId") or ""),
        )
        return json_safe({"ok": True, **portfolio})
    except HTTPException:
        raise
    except TrainingTargetSemanticsError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="ATLAS could not persist the governed model portfolio.",
        ) from exc


@router.get("/model/train/preflight")
def get_latest_training_preflight(
    project_id: str = Query(...),
    dataset_id: str = Query(...),
    dataset_version_id: str = Query(...),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "view")
    try:
        result = TRAINING_JOBS.latest_preflight(
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
        )
        return json_safe({"ok": True, "preflight": result})
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="ATLAS could not read the authoritative training preflight.",
        ) from exc


@router.post("/model/train/jobs")
def create_training_job(request: TrainingJobRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    authorize_modeling_scope(user, request.project_id, "edit")
    try:
        result = TRAINING_JOBS.create(
            request,
            owner_user_id=str(user.get("userId") or ""),
        )
        audit_event(
            "modeling.training_job.created",
            "project",
            request.project_id,
            "success",
            metadata={
                "projectId": request.project_id,
                "trainingJobId": result.get("job_id"),
                "models": request.models,
                "validationDesignId": request.validation_design_id,
                "validationDesignVersion": request.validation_design_version,
                "candidateStrategy": request.candidate_strategy,
            },
            user_id=user.get("userId"),
        )
        return json_safe({"ok": True, **result})
    except HTTPException:
        raise
    except TrainingTargetSemanticsError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="ATLAS could not create the governed training job.",
        ) from exc


@router.post("/model/train/preflight")
def run_training_preflight(request: TrainingJobRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    authorize_modeling_scope(user, request.project_id, "view")
    try:
        return json_safe(TRAINING_JOBS.preflight(request))
    except HTTPException:
        raise
    except TrainingTargetSemanticsError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="ATLAS could not validate the governed training request.",
        ) from exc


@router.get("/model/train/jobs/active")
def get_active_training_jobs(project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "view")
    owner_user_id = str(user.get("userId") or "")
    jobs = TRAINING_JOBS.active(
        owner_user_id=owner_user_id,
        project_id=project_id,
    )
    latest_job = TRAINING_JOBS.latest(
        owner_user_id=owner_user_id,
        project_id=project_id,
    )
    return json_safe(
        {
            "ok": True,
            "jobs": jobs,
            "active_job": jobs[0] if jobs else None,
            "latest_job": latest_job,
        }
    )


@router.get("/model/train/jobs/{job_id}")
def get_training_job(job_id: str, project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "view")
    job = TRAINING_JOBS.get(job_id, owner_user_id=str(user.get("userId") or ""), project_id=project_id)
    if not job:
        raise HTTPException(status_code=404, detail="Training job was not found or is no longer available.")
    return json_safe({"ok": True, **job})


@router.post("/model/train/jobs/{job_id}/cancel")
def cancel_training_job(job_id: str, project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "edit")
    job = TRAINING_JOBS.cancel(job_id, owner_user_id=str(user.get("userId") or ""), project_id=project_id)
    if not job:
        raise HTTPException(status_code=404, detail="Training job was not found or is no longer available.")
    audit_event(
        "modeling.training_job.cancelled",
        "project",
        project_id,
        "success",
        metadata={"projectId": project_id, "trainingJobId": job_id},
        user_id=user.get("userId"),
    )
    return json_safe({"ok": True, **job})


@router.post("/model/train/jobs/{job_id}/cancel-queued")
def cancel_queued_training_models(
    job_id: str,
    project_id: str = Query(...),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "edit")
    job = TRAINING_JOBS.cancel_queued(
        job_id,
        owner_user_id=str(user.get("userId") or ""),
        project_id=project_id,
    )
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Training job was not found or is no longer available.",
        )
    audit_event(
        "modeling.training_job.queued_models_cancelled",
        "project",
        project_id,
        "success",
        metadata={
            "projectId": project_id,
            "trainingJobId": job_id,
            "cancelledModels": job.get("cancelled_models") or [],
        },
        user_id=user.get("userId"),
    )
    return json_safe({"ok": True, **job})


@router.get("/model/train/decision")
def get_model_selection_decision(
    project_id: str = Query(...),
    expected_dataset_id: str = Query(""),
    expected_dataset_version_id: str = Query(""),
    candidate_decision_id: str = Query(""),
    validation_design_id: str = Query(""),
    validation_design_version: str = Query(""),
    split_id: str = Query(""),
    training_run_id: str = Query(""),
    candidate_id: str = Query(""),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    candidate_decision_id = (
        candidate_decision_id if isinstance(candidate_decision_id, str) else ""
    )
    validation_design_id = (
        validation_design_id if isinstance(validation_design_id, str) else ""
    )
    validation_design_version = (
        validation_design_version
        if isinstance(validation_design_version, str)
        else ""
    )
    split_id = split_id if isinstance(split_id, str) else ""
    training_run_id = (
        training_run_id if isinstance(training_run_id, str) else ""
    )
    candidate_id = candidate_id if isinstance(candidate_id, str) else ""
    authorize_modeling_scope(user, project_id, "view")
    identity = assert_expected_active_identity(
        project_id,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version_id=expected_dataset_version_id,
        require_expected=True,
        user=user,
    )
    cached = DATASTORE.meta.get("model_selection_decision")
    if isinstance(cached, dict):
        if any(
            str(cached.get(key) or "") != str(identity.get(key) or "")
            for key in ("project_id", "dataset_id", "dataset_version_id")
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "The saved model-selection decision does not belong to "
                    "the exact active Dataset Library version."
                ),
            )
    else:
        cached = {}
    exact = {
        "candidate_decision_id": candidate_decision_id
        or str(cached.get("candidate_decision_id") or cached.get("decision_id") or ""),
        "validation_design_id": validation_design_id
        or str(cached.get("validation_design_id") or ""),
        "validation_design_version_id": validation_design_version
        or str(cached.get("validation_design_version") or ""),
        "split_id": split_id or str(cached.get("split_id") or ""),
        "training_run_id": training_run_id
        or str(cached.get("training_run_id") or ""),
        "candidate_id": candidate_id or str(cached.get("candidate_id") or ""),
    }
    decision = None
    recovery_status = "exact_identity_required"
    if all(str(value or "").strip() for value in exact.values()):
        durable = get_persistence_service().holdout_governance.get_selection_decision_exact(
            project_id=str(identity["project_id"]),
            dataset_id=str(identity["dataset_id"]),
            dataset_version_id=str(identity["dataset_version_id"]),
            **exact,
        )
        if durable is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "The exact immutable model-selection decision was not found. "
                    "ATLAS did not substitute a latest, algorithm, or browser-only decision."
                ),
            )
        decision = _ui_decision_from_durable(durable)
        recovery_status = "exact_durable_record"
    return json_safe(
        {
            "ok": True,
            "project_id": identity["project_id"],
            "dataset_id": identity["dataset_id"],
            "dataset_version_id": identity["dataset_version_id"],
            "dataset_version": identity["dataset_version_id"],
            "decision": decision,
            "decision_recovery_status": recovery_status,
            "fallback_used": False,
        }
    )


@router.post("/model/train/decision")
def save_model_selection_decision(
    request: ModelSelectionDecisionRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, request.project_id, "edit")
    scoped_store = _current_store(DATASTORE)
    scoped_results = _current_store(RESULTS)
    with scoped_store.state_lock:
        active_identity = assert_expected_active_identity(
            request.project_id,
            expected_dataset_id=request.dataset_id,
            expected_dataset_version_id=request.dataset_version_id,
            legacy_dataset_version=request.dataset_version,
            require_expected=True,
            user=user,
            store=scoped_store,
        )
        input_revision = int(scoped_store.data_revision)
        validation_design = deepcopy(
            scoped_store.meta.get("validation_design")
            if isinstance(scoped_store.meta.get("validation_design"), dict)
            else {}
        )
    if request.status == "approved":
        raise HTTPException(
            status_code=409,
            detail=(
                "Model Training may propose candidates but cannot approve a "
                "champion. Final approval remains in downstream Evaluation / "
                "Validation."
            ),
        )
    job = TRAINING_JOBS.get(
        request.training_job_id,
        owner_user_id=str(user.get("userId") or ""),
        project_id=request.project_id,
    )
    if not job:
        # Completed training summaries are persisted beyond the in-memory job
        # worker.  After a backend restart the user must still be able to bind
        # a provisional selection to that exact governed run.
        last_summary = scoped_results.get_last_summary()
        if (
            isinstance(last_summary, dict)
            and str(last_summary.get("training_job_id") or "")
            == request.training_job_id
            and str(last_summary.get("project_id") or "")
            == request.project_id
            and str(last_summary.get("dataset_id") or "")
            == active_identity["dataset_id"]
            and str(last_summary.get("dataset_version_id") or "")
            == active_identity["dataset_version_id"]
            and str(last_summary.get("status") or "") == "complete"
        ):
            job = {
                "partial_ranked_results": last_summary.get("ranked") or [],
                "dataset_id": last_summary.get("dataset_id"),
                "dataset_version_id": last_summary.get(
                    "dataset_version_id"
                ),
                "feature_manifest_version": last_summary.get(
                    "feature_manifest_version"
                ),
                "split_id": last_summary.get("split_id"),
                "validation_design_id": last_summary.get(
                    "validation_design_id"
                ),
                "validation_design_version": last_summary.get(
                    "validation_design_version"
                ),
                "overall_status": last_summary.get("status"),
                "requested_models": last_summary.get("requested_models") or [],
                "completed_models": last_summary.get("completed_models") or [],
                "failed_models": last_summary.get("failed") or [],
                "finished_count": len(last_summary.get("completed_models") or [])
                + len(last_summary.get("failed") or []),
                "total_count": len(last_summary.get("requested_models") or []),
                "queued_models": [],
                "current_models": [],
            }
    if not job:
        raise HTTPException(
            status_code=404,
            detail=(
                "The governed training job was not found in this project. "
                "Run Model Training again before recording a proposal."
            ),
        )
    total_count = int(job.get("total_count") or 0)
    finished_count = int(job.get("finished_count") or 0)
    if (
        str(job.get("overall_status") or "") != "complete"
        or total_count < 1
        or finished_count != total_count
        or bool(job.get("queued_models"))
        or bool(job.get("current_models"))
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The training portfolio is not terminal and complete. ATLAS "
                "will not lock a candidate from a partial leaderboard."
            ),
        )
    if any(
        str(job.get(key) or "") != str(active_identity.get(key) or "")
        for key in ("dataset_id", "dataset_version_id")
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The governed training job does not belong to the exact "
                "active Dataset Library version."
            ),
        )
    candidate_rows: dict[str, dict[str, Any]] = {}
    invalid_candidate_reasons: dict[str, str] = {}
    for row in job.get("partial_ranked_results") or []:
        if not isinstance(row, dict) or not row.get("champion_eligible", True):
            continue
        key = str(row.get("key") or "")
        contract = row.get("candidate_contract")
        integrity = classify_selection_integrity(
            contract if isinstance(contract, dict) else row
        )
        if integrity != "verified":
            invalid_candidate_reasons[key] = integrity
            continue
        try:
            assert_candidate_contract_intact(contract)
        except (CandidateContractError, TypeError) as exc:
            invalid_candidate_reasons[key] = str(exc)
            continue
        if any(
            str(contract.get(field) or "") != str(expected or "")
            for field, expected in (
                ("project_id", active_identity["project_id"]),
                ("dataset_id", active_identity["dataset_id"]),
                (
                    "dataset_version_id",
                    active_identity["dataset_version_id"],
                ),
                ("training_job_id", request.training_job_id),
                ("split_id", job.get("split_id")),
                (
                    "validation_design_id",
                    job.get("validation_design_id"),
                ),
                (
                    "validation_design_version",
                    job.get("validation_design_version"),
                ),
            )
        ):
            invalid_candidate_reasons[key] = (
                "candidate contract does not match the exact requested training lineage"
            )
            continue
        candidate_rows[key] = row
    if request.champion_model not in candidate_rows:
        reason = invalid_candidate_reasons.get(request.champion_model)
        raise HTTPException(
            status_code=409 if reason else 400,
            detail=(
                "The proposed champion is non-promotable because its governed "
                f"selection integrity is not verified: {reason}"
                if reason
                else "The proposed champion is not an eligible completed candidate."
            ),
        )
    invalid_challengers = [
        model
        for model in request.challenger_models
        if model not in candidate_rows or model == request.champion_model
    ]
    if invalid_challengers:
        raise HTTPException(
            status_code=400,
            detail="Invalid challenger candidates: " + ", ".join(invalid_challengers),
        )
    if any(
        str(validation_design.get(key) or "")
        != str(active_identity.get(key) or "")
        for key in ("project_id", "dataset_id", "dataset_version_id")
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The active Validation Design does not belong to the exact "
                "active Dataset Library version."
            ),
        )
    if (
        str(job.get("validation_design_id") or "")
        != str(validation_design.get("validation_design_id") or "")
        or str(job.get("validation_design_version") or "")
        != str(validation_design.get("design_version") or "")
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The governed training job no longer matches the active "
                "Validation Design."
            ),
        )
    if (
        request.validation_design_id
        and request.validation_design_id
        != validation_design.get("validation_design_id")
    ):
        raise HTTPException(
            status_code=409,
            detail="The Validation Design changed. Refresh the training decision.",
        )
    if (
        request.validation_design_version
        and request.validation_design_version
        != validation_design.get("design_version")
    ):
        raise HTTPException(
            status_code=409,
            detail="The Validation Design version changed. Refresh the training decision.",
        )
    selected_row = candidate_rows[request.champion_model]
    selected_contract = selected_row["candidate_contract"]
    selection_metric = selected_contract["selection_metric"]
    threshold_configuration = selected_contract["threshold_configuration"]
    decision_identity = {
        "project_id": request.project_id,
        "dataset_id": active_identity["dataset_id"],
        "dataset_version_id": active_identity["dataset_version_id"],
        "validation_design_id": validation_design.get(
            "validation_design_id"
        ),
        "validation_design_version_id": validation_design.get(
            "design_version"
        ),
        "split_id": job.get("split_id"),
        "training_job_id": request.training_job_id,
        "training_run_id": selected_contract.get("training_run_id"),
        "candidate_id": selected_contract.get("candidate_id"),
        "final_holdout_partition_id": selected_contract.get(
            "final_holdout_partition_id"
        ),
    }
    candidate_decision_id = (
        "model-decision-"
        + canonical_contract_hash(decision_identity)[:20]
    )
    selected_keys = {
        request.champion_model,
        *request.challenger_models,
    }
    ranking_snapshot = [
        {
            "rank": rank,
            "key": str(row.get("key") or ""),
            "algorithm_id": str(
                (row.get("candidate_contract") or {}).get("algorithm_id")
                or row.get("key")
                or ""
            ),
            "name": str(row.get("name") or row.get("key") or ""),
            "candidate_id": str(row.get("candidate_id") or ""),
            "training_run_id": str(row.get("training_run_id") or ""),
            "selection_metric": deepcopy(row.get("selection_metric") or {}),
            "selection_integrity_status": row.get(
                "selection_integrity_status"
            ),
            "holdout_isolation_status": row.get(
                "holdout_isolation_status"
            ),
            "candidate_contract_hash": (
                row.get("candidate_contract") or {}
            ).get("contract_hash"),
        }
        for rank, row in enumerate(
            job.get("partial_ranked_results") or [], start=1
        )
        if isinstance(row, dict) and str(row.get("key") or "") in selected_keys
    ]
    ranking_snapshot_hash = canonical_contract_hash(ranking_snapshot)
    decided_at = datetime.now(timezone.utc).isoformat()
    actor_id = str(user.get("userId") or "")
    durable_record = {
        "candidate_decision_id": candidate_decision_id,
        "decision_status": "locked",
        **decision_identity,
        "feature_manifest_id": selected_contract.get(
            "feature_manifest_id"
        ),
        "feature_manifest_hash": selected_contract.get(
            "feature_manifest_hash"
        ),
        "treatment_manifest_id": selected_contract.get(
            "treatment_manifest_id"
        ),
        "treatment_manifest_hash": selected_contract.get(
            "treatment_manifest_hash"
        ),
        "materialization_id": selected_contract.get("materialization_id"),
        "selected_candidate_contract_hash": selected_contract.get(
            "contract_hash"
        ),
        "selection_metric_name": selection_metric[
            "selection_metric_name"
        ],
        "selection_metric_value": selection_metric[
            "selection_metric_value"
        ],
        "selection_metric_source": selection_metric[
            "selection_metric_source"
        ],
        "selection_metric_created_at": selection_metric["created_at"],
        "selection_partition_id": selection_metric[
            "selection_partition_id"
        ],
        "fold_definition_id": selection_metric["fold_definition_id"],
        "fold_count": selection_metric["fold_count"],
        "fold_values_json": selection_metric["fold_values"],
        "selection_metric_mean": selection_metric["mean"],
        "selection_metric_std": selection_metric[
            "standard_deviation"
        ],
        "out_of_fold_prediction_artifact_id": selection_metric[
            "out_of_fold_prediction_artifact_id"
        ],
        "threshold_source": selection_metric["threshold_source"],
        "locked_threshold": threshold_configuration.get(
            "locked_threshold"
        ),
        "threshold_locked_at": threshold_configuration.get(
            "threshold_locked_at"
        ),
        "threshold_policy_hash": threshold_configuration.get(
            "threshold_policy_hash"
        ),
        "calibration_source": selection_metric["calibration_source"],
        "ranking_snapshot_json": ranking_snapshot,
        "ranking_snapshot_hash": ranking_snapshot_hash,
        "selection_rationale": request.rationale,
        "selection_locked_at": decided_at,
        "actor": actor_id,
        "selection_integrity_status": "verified",
        "selection_integrity_reason": (
            "Candidate ranking uses exact governed out-of-fold training evidence only."
        ),
        "holdout_isolation_status": "verified",
        "holdout_isolation_reason": (
            "The final holdout remained sealed through candidate selection and threshold policy lock."
        ),
        "integrity_classified_at": decided_at,
        "integrity_classified_by": actor_id,
        "created_at": decided_at,
    }
    durable_record["decision_contract_hash"] = canonical_contract_hash(
        durable_record
    )
    durable_decision: dict[str, Any]
    with scoped_store.state_lock:
        assert_expected_active_identity(
            request.project_id,
            expected_dataset_id=active_identity["dataset_id"],
            expected_dataset_version_id=active_identity[
                "dataset_version_id"
            ],
            require_expected=True,
            user=user,
            store=scoped_store,
        )
        current_validation_design = (
            scoped_store.meta.get("validation_design")
            if isinstance(
                scoped_store.meta.get("validation_design"),
                dict,
            )
            else {}
        )
        if (
            int(scoped_store.data_revision) != input_revision
            or str(
                current_validation_design.get("validation_design_id") or ""
            )
            != str(validation_design.get("validation_design_id") or "")
            or str(current_validation_design.get("design_version") or "")
            != str(validation_design.get("design_version") or "")
            or any(
                str(current_validation_design.get(key) or "")
                != str(active_identity.get(key) or "")
                for key in (
                    "project_id",
                    "dataset_id",
                    "dataset_version_id",
                )
            )
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "The governed dataset or Validation Design changed while "
                    "the model-selection proposal was being recorded. Reload "
                    "Model Training and try again."
                ),
            )
        repository = get_persistence_service().holdout_governance
        try:
            durable_decision = repository.insert_selection_decision_if_unexposed(
                durable_record,
                final_holdout_partition_id=str(
                    selected_contract.get("final_holdout_partition_id") or ""
                ),
            )
        except (
            HoldoutGovernanceConflictError,
            HoldoutGovernanceStateError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        decision = _ui_decision_from_durable(durable_decision)
        decision.update(
            {
                "decision_id": candidate_decision_id,
                "candidate_decision_id": candidate_decision_id,
                "candidate_id": selected_contract.get("candidate_id"),
                "selected_candidate_id": selected_contract.get(
                    "candidate_id"
                ),
                "selected_candidate_contract_hash": selected_contract.get(
                    "contract_hash"
                ),
                "training_run_id": selected_contract.get("training_run_id"),
                "project_id": active_identity["project_id"],
                "dataset_id": active_identity["dataset_id"],
                "dataset_version_id": active_identity[
                    "dataset_version_id"
                ],
                "dataset_version": active_identity[
                    "dataset_version_id"
                ],
                "validation_design_id": validation_design.get(
                    "validation_design_id"
                ),
                "validation_design_version": validation_design.get(
                    "design_version"
                ),
                "feature_manifest_version": job.get(
                    "feature_manifest_version"
                ),
                "feature_manifest_id": selected_contract.get(
                    "feature_manifest_id"
                ),
                "feature_manifest_hash": selected_contract.get(
                    "feature_manifest_hash"
                ),
                "treatment_manifest_id": selected_contract.get(
                    "treatment_manifest_id"
                ),
                "treatment_manifest_hash": selected_contract.get(
                    "treatment_manifest_hash"
                ),
                "materialization_id": selected_contract.get(
                    "materialization_id"
                ),
                "split_id": job.get("split_id"),
                "actor": {
                    "user_id": user.get("userId"),
                    "display_name": user.get("displayName")
                    or user.get("email")
                    or "Current ATLAS user",
                },
                "decided_at": durable_decision.get(
                    "selection_locked_at"
                ),
                "durable": True,
                "fallback_used": False,
            }
        )
        # The durable insert/read is authoritative. This browser-session copy
        # is only a checkpointable cache for exact-key recovery.
        scoped_store.meta["model_selection_decision"] = decision
    audit_event(
        "modeling.model_selection.decision",
        "project",
        request.project_id,
        "success",
        metadata={
            "decisionId": decision["decision_id"],
            "trainingJobId": request.training_job_id,
            "championModel": request.champion_model,
            "status": request.status,
        },
        user_id=user.get("userId"),
    )
    schedule_checkpoint_save()
    return json_safe({"ok": True, "decision": decision})


@router.get("/models/availability")
def get_model_availability(
    project_id: str = Query(...),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """
    Front-end (Step06_Train.tsx) calls this to determine:

      • Which algorithms are available (`availability`)
      • Human-readable model labels (`labels`)

    Expected response shape on the frontend:

      {
        ok: boolean,
        availability: { [key: string]: boolean },
        labels: { [key: string]: string }
      }

    The reported availability is environment-wide (which ML libraries are
    installed), not project-specific data -- but TRAINER.get_availability()
    writes its result into RESULTS.model_availability internally (see
    trainer_service.py), so this still requires project_id/authorization
    like every other endpoint that touches RESULTS (Stage 3).
    """
    authorize_modeling_scope(user, project_id, "view")
    try:
        data = TRAINER.get_availability()
        return {
            "ok": True,
            "availability": data.get("availability", {}),
            "labels": data.get("labels", {}),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/model/train")
def train_models(request: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """
    Retired synchronous training endpoint retained only to fail closed.

    Request body (from Step06_Train.tsx):

      {
        models: string[],        // e.g. ["logreg", "xgb"]
        k_folds: number,         // 2–5, chosen in the UI
        max_parallel: number,    // future use
        calibrate: boolean,      // future use
        use_pca: boolean,        // future use
        grid_search: boolean,    // optional hyperparameter search
        grid_search_level: string // quick | balanced | thorough
      }

    Response shape consumed by the frontend:

      {
        ok: boolean,
        summary: {
          ranked: [
            { key, name, auc, pr_auc, accuracy, f1 },
            ...
          ],
          n_train: number,
          n_test: number,
          k_folds: number,
          status: string
        },
        rows: number,    // convenience echo (n_train)
        status: string   // mirrors summary.status
      }
    """
    project_id = str(request.get("project_id") or "")
    authorize_modeling_scope(user, project_id, "edit")
    raise HTTPException(
        status_code=410,
        detail=(
            "Synchronous model training has been retired because it cannot "
            "provide the governed atomic commit contract. Use "
            "POST /api/model/train/jobs."
        ),
    )


@router.get("/train/last")
def get_last_train(
    project_id: str = Query(...),
    dataset_id: str = "",
    dataset_version_id: str = "",
    dataset_version: str = "",
    target: str = "",
    problem_type: str = "",
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """
    Used by:
      • Step06_Train.tsx (to render the summary table after training)
      • Step08_Evaluation.tsx (leaderboard + default model selection)

    Returns whatever the last successful /model/train call stored in RESULTStore.

    project_id is now required and authorized (Stage 3): RESULTS is scoped
    by (user_id, project_id), so a caller can only ever read their own
    project's own last summary in the first place. The dataset_version/
    target/problem_type soft-mismatch check below remains meaningful (it
    detects a stale summary from an earlier feature/split configuration
    within the SAME project); the project_id entry in that same check is now
    redundant with the scope isolation itself but is left in place as a
    harmless, defense-in-depth no-op -- it can never trigger under correct
    scope resolution, since `last` (if present) can only ever be this
    project's own summary.
    """
    authorize_modeling_scope(user, project_id, "view")
    scoped_store = _current_store(DATASTORE)
    scoped_results = _current_store(RESULTS)
    with scoped_store.state_lock:
        identity = assert_expected_active_identity(
            project_id,
            expected_dataset_id=dataset_id,
            expected_dataset_version_id=dataset_version_id,
            legacy_dataset_version=dataset_version,
            require_expected=True,
            user=user,
            store=scoped_store,
        )
        last = scoped_results.get_last_summary()
        if last:
            context_error = _last_summary_context_error(
                last,
                identity,
                scoped_store,
            )
            if not context_error:
                for key, label, requested_value in (
                    ("target", "target", target),
                    ("problem_type", "problem type", problem_type),
                ):
                    requested = str(requested_value or "").strip()
                    actual = str(last.get(key) or "").strip()
                    if requested and requested != actual:
                        context_error = (
                            "The last training run does not match the current "
                            f"{label}. Train models for this project before "
                            "continuing."
                        )
                        break
            if context_error:
                return json_safe(
                    {
                        "ok": True,
                        "summary": None,
                        "context_error": (
                            "The last training run does not match the current "
                            f"project context. {context_error}"
                        ),
                    }
                )
    return json_safe({"ok": True, "summary": last})

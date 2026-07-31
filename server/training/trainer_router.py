# server/training/trainer_router.py

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Dict, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .trainer_service import TRAINER
from .training_job_service import TRAINING_JOBS
from .training_job_types import TrainingJobRequest
from ..core.json_safety import json_safe
from ..core.dataset_store import DATASTORE
from ..core.modeling_scope import authorize_modeling_scope
from ..core.result_store import RESULTS
from ..core.session_checkpoint import schedule_checkpoint_save
from ..datasets.dataset_identity import assert_expected_active_identity
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
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/model/train/preflight")
def run_training_preflight(request: TrainingJobRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    authorize_modeling_scope(user, request.project_id, "view")
    try:
        return json_safe(TRAINING_JOBS.preflight(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/model/train/jobs/active")
def get_active_training_jobs(project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "view")
    return json_safe({"ok": True, "jobs": TRAINING_JOBS.active(owner_user_id=str(user.get("userId") or ""), project_id=project_id)})


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
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "view")
    identity = assert_expected_active_identity(
        project_id,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version_id=expected_dataset_version_id,
        require_expected=True,
        user=user,
    )
    decision = DATASTORE.meta.get("model_selection_decision")
    if isinstance(decision, dict):
        if any(
            str(decision.get(key) or "") != str(identity.get(key) or "")
            for key in ("project_id", "dataset_id", "dataset_version_id")
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "The saved model-selection decision does not belong to "
                    "the exact active Dataset Library version."
                ),
            )
    return json_safe(
        {
            "ok": True,
            "project_id": identity["project_id"],
            "dataset_id": identity["dataset_id"],
            "dataset_version_id": identity["dataset_version_id"],
            "dataset_version": identity["dataset_version_id"],
            "decision": decision if isinstance(decision, dict) else None,
        }
    )


@router.post("/model/train/decision")
def save_model_selection_decision(
    request: ModelSelectionDecisionRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, request.project_id, "edit")
    scoped_store = _current_store(DATASTORE)
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
        raise HTTPException(
            status_code=404,
            detail="The governed training job was not found in this project.",
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
    candidates = {
        str(row.get("key"))
        for row in job.get("partial_ranked_results") or []
        if isinstance(row, dict) and row.get("champion_eligible", True)
    }
    if request.champion_model not in candidates:
        raise HTTPException(
            status_code=400,
            detail="The proposed champion is not an eligible completed candidate.",
        )
    invalid_challengers = [
        model
        for model in request.challenger_models
        if model not in candidates or model == request.champion_model
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
    decided_at = datetime.now(timezone.utc).isoformat()
    identity = {
        "project_id": request.project_id,
        "dataset_id": active_identity["dataset_id"],
        "dataset_version_id": active_identity["dataset_version_id"],
        "training_job_id": request.training_job_id,
        "champion_model": request.champion_model,
        "challenger_models": request.challenger_models,
        "status": request.status,
        "validation_design_version": validation_design.get("design_version"),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    decision = {
        "decision_id": f"model-decision-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:16]}",
        **request.model_dump(),
        "project_id": active_identity["project_id"],
        "dataset_id": active_identity["dataset_id"],
        "dataset_version_id": active_identity["dataset_version_id"],
        "dataset_version": active_identity["dataset_version_id"],
        "validation_design_id": validation_design.get("validation_design_id"),
        "validation_design_version": validation_design.get("design_version"),
        "feature_manifest_version": job.get("feature_manifest_version"),
        "split_id": job.get("split_id"),
        "actor": {
            "user_id": user.get("userId"),
            "display_name": user.get("displayName")
            or user.get("email")
            or "Current ATLAS user",
        },
        "decided_at": decided_at,
        "candidate_metrics": {
            str(row.get("key")): row
            for row in job.get("partial_ranked_results") or []
            if isinstance(row, dict)
            and str(row.get("key"))
            in {request.champion_model, *request.challenger_models}
        },
    }
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
    Core training endpoint used by the Step06 Training page.

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
    try:
        models = request.get("models") or []
        if not isinstance(models, list) or not models:
            raise ValueError("No models selected for training.")

        k_folds = int(request.get("k_folds", 5))
        max_parallel = int(request.get("max_parallel", 1))
        calibrate = bool(request.get("calibrate", False))
        use_pca = bool(request.get("use_pca", False))
        grid_search = bool(request.get("grid_search", False))
        grid_search_level = str(request.get("grid_search_level", "quick"))
        model_params = request.get("model_params") or {}
        if not isinstance(model_params, dict):
            model_params = {}
        project_id = str(request.get("project_id") or "")
        dataset_version = str(request.get("dataset_version") or "")
        target = str(request.get("target") or "")
        problem_type = str(request.get("problem_type") or "")
        authorize_modeling_scope(user, project_id, "edit")

        typed_request = TrainingJobRequest(
            models=models,
            k_folds=k_folds,
            max_parallel=max_parallel,
            calibrate=calibrate,
            use_pca=use_pca,
            grid_search=grid_search,
            grid_search_level=grid_search_level,
            model_params=model_params,
            project_id=project_id,
            dataset_version=dataset_version,
            target=target,
            problem_type=problem_type,
            event_value=request.get("event_value"),
            feature_manifest_version=str(request.get("feature_manifest_version") or ""),
            split_id=str(request.get("split_id") or ""),
        )
        preflight = TRAINING_JOBS.preflight(typed_request)
        if not preflight["ready"]:
            raise ValueError("Training preflight blocked execution: " + " | ".join(preflight["blocking_errors"]))

        summary = TRAINER.train(
            models=models,
            k_folds=k_folds,
            max_parallel=max_parallel,
            calibrate=calibrate,
            use_pca=use_pca,
            grid_search=grid_search,
            grid_search_level=grid_search_level,
            model_params=model_params,
            project_id=project_id,
            dataset_version=dataset_version,
            target=target,
            problem_type=problem_type,
        )

        rows = summary.get("n_train")
        status = summary.get("status", "ok")
        schedule_checkpoint_save()

        return json_safe({
            "ok": True,
            "summary": summary,
            "rows": rows,
            "status": status,
        })

    except HTTPException:
        # Let authorize_modeling_scope's 400/403/404 propagate with their
        # real status codes instead of being flattened to 500 below.
        raise
    except Exception as e:
        # Frontend will show a "training failed" banner if this bubbles up
        raise HTTPException(status_code=500, detail=str(e))


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

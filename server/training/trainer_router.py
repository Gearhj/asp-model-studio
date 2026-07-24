# server/training/trainer_router.py

from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from .trainer_service import TRAINER
from .training_job_service import TRAINING_JOBS
from .training_job_types import TrainingJobRequest
from ..core.json_safety import json_safe
from ..core.modeling_scope import authorize_modeling_scope
from ..core.result_store import RESULTS
from ..core.session_checkpoint import schedule_checkpoint_save
from ..security.security_store import require_user


router = APIRouter()


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
        return json_safe({"ok": True, **TRAINING_JOBS.create(request, owner_user_id=str(user.get("userId") or ""))})
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
    return json_safe({"ok": True, **job})


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
    last = RESULTS.get_last_summary()
    if last:
        expected = {
            "project_id": project_id,
            "dataset_version": dataset_version,
            "target": target,
            "problem_type": problem_type,
        }
        labels = {
            "project_id": "project",
            "dataset_version": "dataset version",
            "target": "target",
            "problem_type": "problem type",
        }
        for key, label in labels.items():
            expected_value = str(expected.get(key) or "").strip()
            actual_value = str(last.get(key) or "").strip()
            if expected_value and expected_value != actual_value:
                return json_safe({
                    "ok": True,
                    "summary": None,
                    "context_error": f"The last training run does not match the current {label}. Train models for this project before continuing.",
                })
    return json_safe({"ok": True, "summary": last})

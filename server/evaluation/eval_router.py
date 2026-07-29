# server/evaluation/eval_router.py

import io
import hashlib
from typing import Any, Dict

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from ..core.modeling_scope import authorize_modeling_scope
from ..core.result_store import RESULTS
from ..core.session_checkpoint import schedule_checkpoint_save
from ..security.security_store import require_user
from ..scoring_runs.scoring_run_service import create_failed_scoring_run, create_scoring_run
from ..model_registry.model_registry_service import create_model_version
from .eval_service import EVAL


router = APIRouter()


def _context(
    project_id: str = "",
    dataset_version: str = "",
    target: str = "",
    problem_type: str = "",
) -> dict:
    return {
        "project_id": project_id,
        "dataset_version": dataset_version,
        "target": target,
        "problem_type": problem_type,
    }


@router.get("/eval/curves")
def get_curves(model: str, project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)):
    """Return curves computed from the persisted governed holdout predictions."""
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.get_curves(model)


@router.get("/eval/deciles")
def get_deciles(model: str, project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)):
    """Return deciles computed from the persisted governed holdout predictions."""
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.get_deciles(model)


@router.get("/eval/command_center")
def get_evaluation_command_center(
    model: str,
    project_id: str = Query(...),
    threshold: float = 0.5,
    review_capacity: float = 0.1,
    user: Dict[str, Any] = Depends(require_user),
):
    """Return real threshold, lift, gain, capture, and calibration diagnostics."""
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.get_evaluation_command_center(
        model,
        threshold=threshold,
        review_capacity=review_capacity,
    )


@router.get("/eval/tree")
def get_decision_tree(
    model: str,
    project_id: str = Query(...),
    max_depth: int = 4,
    dataset_version: str = "",
    target: str = "",
    problem_type: str = "",
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.decision_tree(model, max_depth=max_depth, context=_context(project_id, dataset_version, target, problem_type))


@router.get("/eval/knn_clusters")
def get_knn_clusters(model: str, project_id: str = Query(...), max_points: int = 900, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.knn_clusters(model, max_points=max_points)


@router.get("/interpretation/importance")
def get_feature_importance(
    model: str,
    project_id: str = Query(...),
    dataset_version: str = "",
    target: str = "",
    problem_type: str = "",
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.feature_importance(model, _context(project_id, dataset_version, target, problem_type))


@router.get("/interpretation/details")
def get_model_details(
    model: str,
    project_id: str = Query(...),
    dataset_version: str = "",
    target: str = "",
    problem_type: str = "",
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.model_details(model, _context(project_id, dataset_version, target, problem_type))


@router.get("/interpretation/debug")
def get_model_debug(
    model: str,
    project_id: str = Query(...),
    dataset_version: str = "",
    target: str = "",
    problem_type: str = "",
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.model_details(model, _context(project_id, dataset_version, target, problem_type))


@router.get("/interpretation/hyperparameters")
def get_hyperparameters(
    model: str,
    project_id: str = Query(...),
    dataset_version: str = "",
    target: str = "",
    problem_type: str = "",
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.hyperparameters(model, _context(project_id, dataset_version, target, problem_type))


@router.get("/interpretation/pdp")
def get_pdp(
    model: str,
    feature: str,
    project_id: str = Query(...),
    dataset_version: str = "",
    target: str = "",
    problem_type: str = "",
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.pdp(model, feature, _context(project_id, dataset_version, target, problem_type))


@router.get("/interpretation/sensitivity")
def get_sensitivity(
    model: str,
    feature: str,
    project_id: str = Query(...),
    dataset_version: str = "",
    target: str = "",
    problem_type: str = "",
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.sensitivity(model, feature, _context(project_id, dataset_version, target, problem_type))


@router.get("/interpretation/sensitivity_summary")
def get_sensitivity_summary(model: str, project_id: str = Query(...), top_n: int = 12, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.sensitivity_summary(model, top_n=top_n)


@router.get("/interpretation/vsi")
def get_vsi_summary(model: str, project_id: str = Query(...), top_n: int = 40, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.vsi_summary(model, top_n=top_n)


@router.get("/interpretation/vif")
def get_vif_summary(project_id: str = Query(...), model: str = "final", user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.vif_summary(model)


@router.get("/interpretation/shap")
def get_shap_summary(
    model: str,
    project_id: str = Query(...),
    dataset_version: str = "",
    target: str = "",
    problem_type: str = "",
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.shap_summary(model, _context(project_id, dataset_version, target, problem_type))


@router.get("/interpretation/decision_boundary")
def get_decision_boundary(
    model: str,
    project_id: str = Query(...),
    x_feature: str = "",
    y_feature: str = "",
    dataset_version: str = "",
    target: str = "",
    problem_type: str = "",
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.decision_boundary(
        model_name=model,
        x_feature=x_feature,
        y_feature=y_feature,
        context=_context(project_id, dataset_version, target, problem_type),
    )


@router.get("/interpretation/rfe")
def get_rfe(
    project_id: str = Query(...),
    model: str = "",
    keep: int = 10,
    dataset_version: str = "",
    target: str = "",
    problem_type: str = "",
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.rfe(model_name=model, keep=keep, context=_context(project_id, dataset_version, target, problem_type))


def _register_model_version(user: Dict[str, Any], project_id: str, metadata: Dict[str, Any]) -> Dict[str, Any] | None:
    """Durable Model Registry, Phase E: called after EVAL.save_selected_model_
    as_final / EVAL.save_rfe_model succeed. Reads the just-set RESULTS.final_model
    (the fitted object) plus the last training summary for hyperparameters/
    dataset/feature-manifest context, and creates one immutable ModelVersion.
    Returns None (never raises) on any failure -- durability is additive, never
    fatal to the "Save Final Model" action that already worked before this
    phase (Do-Not: "do not remove current scoring functionality")."""
    try:
        fitted_object = RESULTS.get_final_model()
        if fitted_object is None:
            return None
        summary = RESULTS.get_last_summary() or {}
        source_key = str(metadata.get("source_model") or metadata.get("model_key") or "")
        ranked_row = next((row for row in (summary.get("ranked") or []) if row.get("key") == source_key), {})
        is_rfe = str(metadata.get("model_key") or "").startswith("final_rfe")
        interpretation_summary = (
            {"selectedFeatures": metadata.get("features"), "featureCount": metadata.get("feature_count"), "method": "RFE"}
            if is_rfe else {}
        )
        saved = create_model_version(
            user, project_id,
            model_name=str(metadata.get("name") or metadata.get("model_key") or "Final Model"),
            problem_type=metadata.get("problem_type"),
            algorithm=source_key or str(metadata.get("model_key") or ""),
            algorithm_version=str(metadata.get("final_estimator_class") or metadata.get("source_estimator_class") or fitted_object.__class__.__name__),
            fitted_object=fitted_object,
            hyperparameters=ranked_row.get("best_params") or {},
            training_parameters={
                "kFolds": summary.get("k_folds"), "calibrate": summary.get("calibrate"),
                "gridSearch": summary.get("grid_search"), "gridSearchLevel": summary.get("grid_search_level"),
            },
            metrics_summary=metadata.get("metrics") or {
                key: metadata.get(key) for key in ("holdout_auc", "holdout_rmse", "holdout_r2", "holdout_adjusted_r2") if metadata.get(key) is not None
            },
            evaluation_summary={key: ranked_row.get(key) for key in ("auc", "pr_auc", "accuracy", "f1", "mae", "mse", "rmse", "r2", "adjusted_r2") if ranked_row.get(key) is not None},
            interpretation_summary=interpretation_summary,
            training_run_id=summary.get("training_job_id"),
            dataset_id=summary.get("dataset_id"),
            dataset_version_id=metadata.get("dataset_version") or summary.get("dataset_version"),
            feature_manifest_version=summary.get("feature_manifest_version") or metadata.get("feature_manifest_version"),
            training_timestamp=RESULTS.training_timestamp,
            lineage={
                "datasetVersionLabel": metadata.get("dataset_version") or summary.get("dataset_version"),
                "splitId": metadata.get("split_id") or summary.get("split_id"),
                "validationDesignId": metadata.get("validation_design_id") or summary.get("validation_design_id"),
                "validationDesignVersion": metadata.get("validation_design_version") or summary.get("validation_design_version"),
                "trainingJobId": metadata.get("training_job_id") or summary.get("training_job_id"),
                "featureManifestVersion": metadata.get("feature_manifest_version") or summary.get("feature_manifest_version"),
                "target": metadata.get("target") or summary.get("target"),
            },
        )
        return saved
    except Exception:  # noqa: BLE001
        return None


@router.post("/interpretation/rfe/save_final")
def save_rfe_final_model(request: dict, user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, str(request.get("project_id") or ""), "edit")
    result = EVAL.save_rfe_model(
        model_name=str(request.get("model") or ""),
        keep=int(request.get("keep") or 10),
        context=_context(
            project_id,
            str(request.get("dataset_version") or ""),
            str(request.get("target") or ""),
            str(request.get("problem_type") or ""),
        ),
    )
    if result.get("ok"):
        registered = _register_model_version(user, project_id, result["metadata"])
        if registered:
            result["metadata"]["modelId"] = registered["model"]["modelId"]
            result["metadata"]["modelVersionId"] = registered["modelVersion"]["modelVersionId"]
            RESULTS.final_model_metadata = result["metadata"]
        schedule_checkpoint_save()
    return result


@router.post("/model/save_final")
def save_selected_final_model(request: dict, user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, str(request.get("project_id") or ""), "edit")
    result = EVAL.save_selected_model_as_final(
        model_name=str(request.get("model") or ""),
        context=_context(
            project_id,
            str(request.get("dataset_version") or ""),
            str(request.get("target") or ""),
            str(request.get("problem_type") or ""),
        ),
    )
    if result.get("ok"):
        registered = _register_model_version(user, project_id, result["metadata"])
        if registered:
            result["metadata"]["modelId"] = registered["model"]["modelId"]
            result["metadata"]["modelVersionId"] = registered["modelVersion"]["modelVersionId"]
            RESULTS.final_model_metadata = result["metadata"]
        schedule_checkpoint_save()
    return result


@router.get("/model/final/status")
def get_final_model_status(project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    return EVAL.final_model_status(context={"project_id": project_id})


@router.get("/model/export")
def export_model(project_id: str = Query(...), model: str = "final", format: str = "json", user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    if format.lower() not in {"json", "manifest"}:
        return {
            "ok": False,
            "error": "Only JSON model manifests are exported. Executable model objects must be deployed through a signed model registry or approved ONNX/skops pipeline.",
        }
    try:
        content, filename = EVAL.export_model_bundle(model_name=model)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/score/upload")
async def score_upload(
    file: UploadFile = File(...),
    project_id: str = Query(...),
    dataset_type: str = "test",
    model: str = "final",
    correction_method: str = "none",
    original_prior: float | None = None,
    model_prior: float | None = None,
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "edit")
    content = await file.read()
    df = pd.read_csv(io.BytesIO(content))
    result = EVAL.score_dataset(
        df=df,
        dataset_type=dataset_type,
        model_name=model,
        correction_method=correction_method,
        original_prior=original_prior,
        model_prior=model_prior,
    )
    if result.get("ok"):
        result["dataset_identity"] = file.filename or f"{dataset_type.upper()} upload"
        result["dataset_version"] = f"sha256:{hashlib.sha256(content).hexdigest()[:16]}"
        date_candidates = [
            column for column in df.columns
            if any(token in str(column).strip().lower() for token in ("date", "time", "timestamp", "as_of", "asof"))
        ]
        for column in date_candidates:
            parsed = pd.to_datetime(df[column], errors="coerce")
            if parsed.notna().mean() >= 0.8:
                result["period"] = {
                    "column": str(column),
                    "start": parsed.min().isoformat(),
                    "end": parsed.max().isoformat(),
                }
                break
        scoring_run = create_scoring_run(
            user, project_id, dataset_type, result,
            dataset_context={"datasetIdentity": result.get("dataset_identity"), "source": "csv_upload"},
        )
        if scoring_run:
            result["scoringRunId"] = scoring_run["scoringRunId"]
        schedule_checkpoint_save()
    else:
        failed_run = create_failed_scoring_run(
            user, project_id, dataset_type, str(result.get("error") or "Scoring failed."),
            dataset_context={"datasetIdentity": file.filename or f"{dataset_type.upper()} upload", "source": "csv_upload"},
        )
        if failed_run:
            result["scoringRunId"] = failed_run["scoringRunId"]
    return result


@router.post("/score/development-split")
def score_development_split(
    project_id: str = Query(...),
    dataset_type: str = "train",
    model: str = "final",
    correction_method: str = "none",
    original_prior: float | None = None,
    model_prior: float | None = None,
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "edit")
    result = EVAL.score_development_split(
        dataset_type=dataset_type,
        model_name=model,
        correction_method=correction_method,
        original_prior=original_prior,
        model_prior=model_prior,
    )
    if result.get("ok"):
        scoring_run = create_scoring_run(
            user, project_id, result.get("dataset_type", dataset_type), result,
            dataset_context={"datasetIdentity": result.get("dataset_identity"), "source": "development_split"},
        )
        if scoring_run:
            result["scoringRunId"] = scoring_run["scoringRunId"]
        schedule_checkpoint_save()
    else:
        failed_run = create_failed_scoring_run(
            user, project_id, dataset_type, str(result.get("error") or "Scoring failed."),
            dataset_context={"source": "development_split"},
        )
        if failed_run:
            result["scoringRunId"] = failed_run["scoringRunId"]
    return result

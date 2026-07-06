# server/evaluation/eval_router.py

import io

import pandas as pd
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response
from ..core.session_checkpoint import save_checkpoint
from .eval_service import EVAL


router = APIRouter()


@router.get("/eval/curves")
def get_curves(model: str):
    """
    Returns dummy curve data so the Evaluation page loads.
    """
    return EVAL.get_curves(model)


@router.get("/eval/deciles")
def get_deciles(model: str):
    """
    Returns placeholder decile results.
    """
    return EVAL.get_deciles(model)


@router.get("/eval/tree")
def get_decision_tree(model: str, max_depth: int = 4):
    return EVAL.decision_tree(model, max_depth=max_depth)


@router.get("/eval/knn_clusters")
def get_knn_clusters(model: str, max_points: int = 900):
    return EVAL.knn_clusters(model, max_points=max_points)


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


@router.get("/interpretation/importance")
def get_feature_importance(model: str, project_id: str = "", dataset_version: str = "", target: str = "", problem_type: str = ""):
    return EVAL.feature_importance(model, _context(project_id, dataset_version, target, problem_type))


@router.get("/interpretation/details")
def get_model_details(model: str, project_id: str = "", dataset_version: str = "", target: str = "", problem_type: str = ""):
    return EVAL.model_details(model, _context(project_id, dataset_version, target, problem_type))


@router.get("/interpretation/debug")
def get_model_debug(model: str, project_id: str = "", dataset_version: str = "", target: str = "", problem_type: str = ""):
    return EVAL.model_details(model, _context(project_id, dataset_version, target, problem_type))


@router.get("/interpretation/hyperparameters")
def get_hyperparameters(model: str, project_id: str = "", dataset_version: str = "", target: str = "", problem_type: str = ""):
    return EVAL.hyperparameters(model, _context(project_id, dataset_version, target, problem_type))


@router.get("/interpretation/pdp")
def get_pdp(model: str, feature: str):
    return EVAL.pdp(model, feature)


@router.get("/interpretation/sensitivity")
def get_sensitivity(model: str, feature: str):
    return EVAL.sensitivity(model, feature)


@router.get("/interpretation/sensitivity_summary")
def get_sensitivity_summary(model: str, top_n: int = 12):
    return EVAL.sensitivity_summary(model, top_n=top_n)


@router.get("/interpretation/vsi")
def get_vsi_summary(model: str, top_n: int = 40):
    return EVAL.vsi_summary(model, top_n=top_n)


@router.get("/interpretation/vif")
def get_vif_summary(model: str = "final"):
    return EVAL.vif_summary(model)


@router.get("/interpretation/shap")
def get_shap_summary(model: str):
    return EVAL.shap_summary(model)


@router.get("/interpretation/decision_boundary")
def get_decision_boundary(model: str, x_feature: str = "", y_feature: str = ""):
    return EVAL.decision_boundary(model_name=model, x_feature=x_feature, y_feature=y_feature)


@router.get("/interpretation/rfe")
def get_rfe(model: str = "", keep: int = 10):
    return EVAL.rfe(model_name=model, keep=keep)


@router.post("/interpretation/rfe/save_final")
def save_rfe_final_model(request: dict):
    result = EVAL.save_rfe_model(
        model_name=str(request.get("model") or ""),
        keep=int(request.get("keep") or 10),
    )
    if result.get("ok"):
        save_checkpoint()
    return result


@router.post("/model/save_final")
def save_selected_final_model(request: dict):
    result = EVAL.save_selected_model_as_final(
        model_name=str(request.get("model") or ""),
    )
    if result.get("ok"):
        save_checkpoint()
    return result


@router.get("/model/export")
def export_model(model: str = "final", format: str = "pkl"):
    if format.lower() != "pkl":
        return {
            "ok": False,
            "error": "Only pkl export is currently supported. Use ONNX, PMML, or a Java scoring wrapper for JVM production deployment.",
        }
    content, filename = EVAL.export_model_bundle(model_name=model)
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/score/upload")
async def score_upload(
    file: UploadFile = File(...),
    dataset_type: str = "test",
    model: str = "final",
    correction_method: str = "none",
    original_prior: float | None = None,
    model_prior: float | None = None,
):
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
        save_checkpoint()
    return result

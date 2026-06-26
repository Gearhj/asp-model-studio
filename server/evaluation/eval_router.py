# server/evaluation/eval_router.py

from fastapi import APIRouter
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


@router.get("/interpretation/importance")
def get_feature_importance(model: str):
    return EVAL.feature_importance(model)


@router.get("/interpretation/details")
def get_model_details(model: str):
    return EVAL.model_details(model)


@router.get("/interpretation/hyperparameters")
def get_hyperparameters(model: str):
    return EVAL.hyperparameters(model)


@router.get("/interpretation/pdp")
def get_pdp(model: str, feature: str):
    return EVAL.pdp(model, feature)


@router.get("/interpretation/sensitivity")
def get_sensitivity(model: str, feature: str):
    return EVAL.sensitivity(model, feature)


@router.get("/interpretation/shap")
def get_shap_summary(model: str):
    return EVAL.shap_summary(model)


@router.get("/interpretation/decision_boundary")
def get_decision_boundary(model: str, x_feature: str = "", y_feature: str = ""):
    return EVAL.decision_boundary(model_name=model, x_feature=x_feature, y_feature=y_feature)


@router.get("/interpretation/rfe")
def get_rfe(model: str = "", keep: int = 10):
    return EVAL.rfe(model_name=model, keep=keep)

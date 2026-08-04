from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from ..preprocessing.development_scope import DevelopmentAnalysisScope
from .governed_scope import canonical_scope_fields
from .scorecard_engine import (
    build_ks_table,
    build_lift_table,
    build_score_distribution,
    raw_design_matrix,
    safe_auc,
    safe_log_loss,
)
from .leakage_guard import default_predictors, validate_predictors


ML_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "credit_risk" / "ml_models"
REGISTRY_PATH = ML_ROOT / "ml_model_registry.json"
MODELS_DIR = ML_ROOT / "models"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dirs() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    if not REGISTRY_PATH.exists():
        REGISTRY_PATH.write_text("[]", encoding="utf-8")


def _load_registry() -> List[Dict[str, Any]]:
    _ensure_dirs()
    try:
        payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def _save_registry(rows: List[Dict[str, Any]]) -> None:
    _ensure_dirs()
    REGISTRY_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def save_ml_model(model: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_dirs()
    model["updatedAt"] = _utc_now()
    model.setdefault("generatedAt", model["updatedAt"])
    model_id = str(model.get("modelId"))
    (MODELS_DIR / f"{model_id}.json").write_text(json.dumps(model, indent=2, default=str), encoding="utf-8")
    registry = [row for row in _load_registry() if row.get("modelId") != model_id]
    registry.insert(0, {
        "modelId": model_id,
        "projectId": model.get("projectId"),
        "datasetId": model.get("datasetId"),
        "datasetVersionId": model.get("datasetVersionId"),
        "modelType": model.get("modelType"),
        "auc": (model.get("metrics") or {}).get("auc"),
        "ks": (model.get("metrics") or {}).get("ks"),
        "gini": (model.get("metrics") or {}).get("gini"),
        "updatedAt": model.get("updatedAt"),
        "analysis_scope": model.get("analysis_scope"),
        "analysis_partition_id": model.get("analysis_partition_id"),
        "analysis_partition_revision": model.get("analysis_partition_revision"),
        "development_partition_id": model.get("development_partition_id"),
        "source_checksum": model.get("source_checksum"),
        "holdout_excluded": model.get("holdout_excluded"),
    })
    _save_registry(registry[:100])
    return model


def get_ml_model(model_id: str) -> Optional[Dict[str, Any]]:
    _ensure_dirs()
    path = MODELS_DIR / f"{model_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_project_ml_model(project_id: str) -> Optional[Dict[str, Any]]:
    raise HTTPException(
        status_code=409,
        detail="Project-latest AI/ML lookup is disabled. Resolve the exact active dataset version and Analysis Partition.",
    )


def get_project_ml_model_exact(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    analysis_partition_id: str,
    analysis_partition_revision: int,
) -> Optional[Dict[str, Any]]:
    matches = [
            row
            for row in _load_registry()
            if row.get("projectId") == project_id
            and row.get("datasetId") == dataset_id
            and row.get("datasetVersionId") == dataset_version_id
            and row.get("analysis_partition_id") == analysis_partition_id
            and int(row.get("analysis_partition_revision") or 0)
            == int(analysis_partition_revision)
            and row.get("analysis_scope") == "development_population"
            and row.get("holdout_excluded") is True
    ]
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail="Multiple current AI/ML models exist. Select one by exact modelId; first/latest fallback is prohibited.",
        )
    return get_ml_model(str(matches[0].get("modelId"))) if matches else None


def train_ml_model(
    payload: Dict[str, Any],
    scope: DevelopmentAnalysisScope,
) -> Dict[str, Any]:
    try:
        import numpy as np
        from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import average_precision_score, log_loss, roc_auc_score
        from sklearn.model_selection import StratifiedKFold
    except Exception as exc:
        raise HTTPException(status_code=501, detail=f"AI/ML underwriting training requires sklearn in the local backend environment. {exc}")

    dataset = scope.identity.get("dataset") or {}
    resolved_version = str(scope.identity.get("dataset_version_id") or "")
    df = scope.development_features.copy()
    target = scope.target
    event_value = scope.event_value
    y = scope.development_target.astype(str).str.strip().eq(str(event_value)).astype(int)
    if y.nunique() < 2:
        raise HTTPException(status_code=400, detail="Target has one class only. AI/ML underwriting training requires both good and bad outcomes.")

    requested_selected = [str(item) for item in payload.get("selectedVariables") or []]
    unauthorized = [name for name in requested_selected if name not in scope.authorized_predictors]
    if unauthorized:
        raise HTTPException(
            status_code=409,
            detail=(
                "AI/ML variables contradict the exact current predictor "
                f"authorization: {', '.join(unauthorized[:10])}."
            ),
        )
    selected = requested_selected or list(scope.authorized_predictors[:25])
    X = raw_design_matrix(df, selected)
    if X.empty:
        raise HTTPException(status_code=400, detail="No usable AI/ML underwriting variables were selected.")

    model_type = str(payload.get("modelType") or "Random Forest")
    model_key = model_type.lower()
    if "xgboost" in model_key or "lightgbm" in model_key or "catboost" in model_key or "monotonic" in model_key:
        raise HTTPException(status_code=501, detail=f"{model_type} is not available in this local environment. Use Random Forest, Logistic Regression Baseline, or install the required backend library.")
    if "logistic" in model_key:
        estimator = LogisticRegression(max_iter=1000, solver="liblinear", class_weight="balanced" if payload.get("classWeight") == "balanced" else None)
    elif "gradient" in model_key or "calibrated" in model_key:
        estimator = GradientBoostingClassifier(random_state=42)
    else:
        estimator = RandomForestClassifier(n_estimators=160, min_samples_leaf=20, random_state=42, class_weight="balanced_subsample" if payload.get("classWeight") == "balanced" else None)

    folds = min(5, int(y.value_counts().min()))
    if folds < 2:
        raise HTTPException(
            status_code=409,
            detail="The governed development population cannot support stratified validation.",
        )
    train_positions, validation_positions = next(
        StratifiedKFold(n_splits=folds, shuffle=False).split(X, y)
    )
    X_train = X.iloc[train_positions].reset_index(drop=True)
    X_val = X.iloc[validation_positions].reset_index(drop=True)
    y_train = y.iloc[train_positions].reset_index(drop=True)
    y_val = y.iloc[validation_positions].reset_index(drop=True)
    split_source = "governed_development_stratified_fold"
    estimator.fit(X_train, y_train)
    if hasattr(estimator, "predict_proba"):
        val_pd = estimator.predict_proba(X_val)[:, 1]
    else:
        val_pd = estimator.decision_function(X_val)
    score = 1000 - (val_pd * 1000)
    auc = safe_auc(y_val, val_pd, roc_auc_score)
    ks_table = build_ks_table(score, y_val, val_pd)
    lift_table = build_lift_table(score, y_val, val_pd)
    feature_importance = _feature_importance(estimator, list(X.columns), np)
    scope_fields = canonical_scope_fields(scope)
    model_id = "ml-credit-" + hashlib.sha256(json.dumps({
        "projectId": scope.identity.get("project_id"),
        "datasetId": scope.identity.get("dataset_id"),
        "version": resolved_version,
        "target": target,
        "variables": selected,
        "modelType": model_type,
        "partitionId": scope_fields["partition_id"],
        "partitionRevision": scope_fields["partition_revision"],
        "sourceChecksum": scope_fields["source_checksum"],
    }, sort_keys=True).encode("utf-8")).hexdigest()[:14]
    model = {
        "modelId": model_id,
        "projectId": scope.identity.get("project_id"),
        "datasetId": scope.identity.get("dataset_id"),
        "datasetName": dataset.get("name"),
        "datasetVersionId": resolved_version,
        "targetColumn": target,
        "eventValue": event_value,
        "modelType": model_type,
        "selectedVariables": list(X.columns),
        "splitSource": split_source,
        "rowCount": int(len(X)),
        "eventRate": round(float(y.mean()), 6),
        "metrics": {
            "auc": auc,
            "ks": max((row["ks"] for row in ks_table), default=0),
            "gini": round((2 * auc - 1), 6) if auc is not None else None,
            "logLoss": safe_log_loss(y_val, val_pd, log_loss),
            "prAuc": _safe_pr_auc(y_val, val_pd, average_precision_score),
        },
        "featureImportance": feature_importance,
        "scoreDistribution": build_score_distribution(score, y_val, val_pd),
        "decileLift": lift_table,
        "calibrationTable": lift_table,
        "warnings": _ml_warnings(model_type, payload),
        **scope_fields,
    }
    return save_ml_model(model)


def _feature_importance(estimator: Any, columns: List[str], np: Any) -> List[Dict[str, Any]]:
    values = getattr(estimator, "feature_importances_", None)
    if values is None and hasattr(estimator, "coef_"):
        values = np.abs(estimator.coef_[0])
    if values is None:
        values = np.ones(len(columns))
    total = float(np.sum(np.abs(values))) or 1.0
    rows = [
        {"feature": col, "importance": round(float(abs(value)) / total, 6), "direction": "Review"}
        for col, value in zip(columns, values)
    ]
    return sorted(rows, key=lambda row: row["importance"], reverse=True)[:30]


def _safe_pr_auc(y: Any, pred: Any, fn: Any) -> Optional[float]:
    try:
        return round(float(fn(y, pred)), 6)
    except Exception:
        return None


def _ml_warnings(model_type: str, payload: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    if "monotonic" not in model_type.lower() and payload.get("monotonicConstraints"):
        warnings.append("The selected model does not support native monotonic constraints. ATLAS preserved the constraint evidence for review, but did not enforce it during training.")
    warnings.append("SHAP values are not computed by this local lightweight trainer. Use feature importance, PDP placeholders, or connect SHAP for full explainability.")
    return warnings


def create_ml_evidence(model_id: str, technique: str = "ml_underwriting", label: str = "AI/ML Underwriting Evidence") -> Dict[str, Any]:
    from ..evidence.evidence_store import upsert_evidence

    model = get_ml_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="AI/ML underwriting model not found.")
    metrics = model.get("metrics") or {}
    evidence = {
        "evidenceId": f"credit-risk-ml-{model_id}-{technique}",
        "title": label,
        "evidenceType": "credit_risk",
        "summary": f"AI/ML underwriting evidence for {model.get('modelType')} with AUC {metrics.get('auc')} and KS {metrics.get('ks')}.",
        "source": "Credit Risk Studio",
        "sourceRoute": "/credit-risk-studio",
        "artifactType": "credit_risk_ml_model",
        "financialDomain": "credit_risk",
        "productType": model.get("productType"),
        "modelPurpose": model.get("modelPurpose"),
        "targetEvent": model.get("targetColumn"),
        "modelingApproach": "ml",
        "modelType": model.get("modelType"),
        "technique": technique,
        "tags": ["credit_risk", "ml_underwriting", technique, "champion_challenger"],
        "metrics": metrics,
        "scopeMetadata": {
            key: model.get(key)
            for key in (
                "project_id",
                "dataset_id",
                "dataset_version_id",
                "analysis_scope",
                "analysis_partition_id",
                "analysis_partition_revision",
                "development_partition_id",
                "population_id",
                "population_count",
                "holdout_excluded",
                "source_checksum",
                "actor",
                "timestamp",
            )
        },
        "createdAt": _utc_now(),
    }
    return upsert_evidence(evidence)


def run_champion_comparison(payload: Dict[str, Any]) -> Dict[str, Any]:
    profile = payload.get("profile") or {}
    scorecard = payload.get("scorecardModel") or {}
    ml = payload.get("mlModel") or {}
    rows = []
    if scorecard:
        rows.append(_comparison_row(scorecard, "Traditional Scorecard Baseline", "scorecard"))
    if ml:
        rows.append(_comparison_row(ml, "AI/ML Challenger", "ml"))
    if not rows:
        rows = [
            {"model": "Traditional Scorecard Baseline", "modelType": "Scorecard", "recommendedRole": "Needs Review"},
            {"model": "AI/ML Challenger", "modelType": "AI/ML", "recommendedRole": "Needs Review"},
        ]
    recommended = rows[0]
    if len(rows) > 1:
        # Do not select by AUC alone; require explainability readiness for AI/ML champion.
        ml_row = next((row for row in rows if row.get("modelType") == "ml"), None)
        score_row = next((row for row in rows if row.get("modelType") == "scorecard"), None)
        if ml_row and score_row and float(ml_row.get("auc") or 0) >= float(score_row.get("auc") or 0) + 0.03:
            ml_row["recommendedRole"] = "Challenger"
            recommended = ml_row
        elif score_row:
            score_row["recommendedRole"] = "Champion"
            recommended = score_row
    return {
        "projectId": profile.get("projectId"),
        "rows": rows,
        "recommendedChampion": recommended,
        "reason": "ATLAS weighs performance with explainability, calibration, adverse-action readiness, stability, and governance complexity. AI/ML is not automatically championed solely because of higher AUC.",
        "generatedAt": _utc_now(),
        **(payload.get("scopeMetadata") or {}),
    }


def _comparison_row(model: Dict[str, Any], label: str, model_type: str) -> Dict[str, Any]:
    metrics = model.get("metrics") or {}
    return {
        "model": label,
        "modelId": model.get("modelId"),
        "modelType": model_type,
        "auc": metrics.get("auc"),
        "ks": metrics.get("ks"),
        "gini": metrics.get("gini"),
        "logLoss": metrics.get("logLoss"),
        "approvalRate": None,
        "badRate": metrics.get("eventRate") or model.get("eventRate"),
        "liftTopDecile": (model.get("liftTable") or model.get("decileLift") or [{}])[0].get("lift") if (model.get("liftTable") or model.get("decileLift")) else None,
        "calibrationQuality": "Review",
        "explainabilityStrength": "High" if model_type == "scorecard" else "Medium",
        "adverseActionReadiness": "High" if model_type == "scorecard" else "Needs SHAP / surrogate review",
        "fairLendingReadiness": "Needs Review",
        "monitoringReadiness": "Needs Review",
        "modelRiskComplexity": "Low" if model_type == "scorecard" else "Medium / High",
        "recommendedRole": "Benchmark" if model_type == "scorecard" else "Challenger",
    }

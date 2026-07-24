from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.modeling_scope import authorize_modeling_scope
from ..datasets.dataset_registry import create_dataset_from_dataframe, link_project, require_dataset
from ..persistence.service import get_persistence_service
from ..security.security_store import require_user


router = APIRouter()


class RegisterScoredDatasetRequest(BaseModel):
    projectId: Optional[str] = None
    projectName: Optional[str] = None
    datasetName: Optional[str] = None
    datasetType: str = "scored"
    task: Optional[str] = None
    modelName: Optional[str] = None
    targetColumn: Optional[str] = None
    scoreColumn: Optional[str] = None
    predictionColumn: Optional[str] = None
    actualColumn: Optional[str] = None
    residualColumn: Optional[str] = None
    absResidualColumn: Optional[str] = None
    squaredResidualColumn: Optional[str] = None
    decileColumn: Optional[str] = None
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Visual Intelligence Production Integration, Phase K: the durable ScoringRun
    # this registration originates from, if any -- optional so the pre-existing
    # unattributed-registration path keeps working unchanged.
    scoringRunId: Optional[str] = None


@router.post("/scoring/register-scored-dataset")
def register_scored_dataset(payload: RegisterScoredDatasetRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    # Dataset lifecycle audit fix: this endpoint called link_project() directly with a
    # client-supplied projectId and no check that the caller can edit that project --
    # any authenticated user could link fabricated scored content into a project they
    # do not own. Registration without a project link is still permitted (unattributed
    # Library asset); only the LINK step requires edit access to that specific project.
    if payload.projectId:
        authorize_modeling_scope(user, payload.projectId, "edit")

    scoring_run = None
    if payload.scoringRunId:
        service = get_persistence_service()
        scoring_run = service.scoring_runs.get(payload.scoringRunId)
        if scoring_run is None:
            raise HTTPException(status_code=404, detail="Scoring run not found.")
        if scoring_run.get("project_id") and payload.projectId and scoring_run["project_id"] != payload.projectId:
            raise HTTPException(status_code=403, detail="This scoring run does not belong to the requested project.")
        # Idempotency (Phase K requirement 3/4): a run already registered reports/returns
        # its existing asset rather than creating a duplicate Dataset Library entry.
        if scoring_run.get("registration_status") == "registered" and scoring_run.get("output_dataset_id"):
            try:
                existing = require_dataset(scoring_run["output_dataset_id"])
                return {"ok": True, "dataset": existing, "columnRoles": {}, "alreadyRegistered": True}
            except HTTPException:
                pass  # underlying asset vanished (e.g. archived+purged) -- fall through and re-register

    if not payload.rows:
        raise HTTPException(status_code=400, detail="No scored rows were provided. Score a dataset before registration.")
    df = pd.DataFrame(payload.rows)
    if df.empty:
        raise HTTPException(status_code=400, detail="No scored rows were provided. Score a dataset before registration.")
    columns = detect_scored_columns(df, payload)
    df = enrich_scored_frame(df, columns)
    dataset_name = payload.datasetName or default_scored_name(payload)
    source_info = {
        "datasetRole": "scored_output",
        "datasetType": payload.datasetType,
        "task": payload.task,
        "modelName": payload.modelName,
        "projectId": payload.projectId,
        "projectName": payload.projectName,
        "columnRoles": columns,
        "rowScope": (payload.metadata or {}).get("rowScope") or "full_scored_output",
        "limitation": (payload.metadata or {}).get("limitation") or "Registered from full scored rows returned by the ATLAS scoring response. Original feature columns, target values when present, predictions, residuals, and split metadata are preserved.",
        **(payload.metadata or {}),
    }
    if scoring_run:
        # Phase K: bidirectional lineage -- the Dataset Library side of the cross-link.
        source_info.update({
            "sourceScoringRunId": scoring_run["scoring_run_id"],
            "sourceModelId": scoring_run.get("model_id"),
            "sourceDatasetId": scoring_run.get("dataset_id"),
            "sourceDatasetVersionId": scoring_run.get("dataset_version_id"),
            "sourcePartition": scoring_run.get("partition"),
            "scoringTimestamp": scoring_run.get("completed_at"),
            "predictionColumn": scoring_run.get("prediction_column"),
            "probabilityColumn": scoring_run.get("probability_column"),
            "residualColumn": scoring_run.get("residual_column"),
        })
    dataset = create_dataset_from_dataframe(
        df,
        name=dataset_name,
        description=f"ATLAS scored output for {payload.datasetType.upper()} scoring. Contains predictions, scores, and diagnostics-ready columns.",
        domain="Model Outputs",
        source_type="scored_output",
        source_info=source_info,
        dataset_role="scored_output",
    )
    version_id = dataset.get("latestVersion", {}).get("versionId")
    if payload.projectId and version_id:
        link_project(payload.projectId, dataset["datasetId"], version_id, "scored_output")
    if scoring_run and version_id:
        # Phase K: the ScoringRun side of the cross-link.
        get_persistence_service().scoring_runs.mark_registered(
            scoring_run["scoring_run_id"], dataset_id=dataset["datasetId"], version_id=version_id,
            registered_by=str(user.get("userId") or ""),
        )
    return {"ok": True, "dataset": dataset, "columnRoles": columns}


def default_scored_name(payload: RegisterScoredDatasetRequest) -> str:
    label = payload.datasetType.upper() if payload.datasetType else "Scored"
    model = payload.modelName or "Final Model"
    project = payload.projectName or "ATLAS Project"
    return f"{project} - {model} - {label} Scored Output"


def detect_scored_columns(df: pd.DataFrame, payload: RegisterScoredDatasetRequest) -> Dict[str, Optional[str]]:
    names = [str(column) for column in df.columns]
    lower = {name.lower(): name for name in names}
    metadata = payload.metadata if isinstance(payload.metadata, dict) else {}
    metadata_target = metadata.get("targetColumn") or metadata.get("target")
    metadata_roles = metadata.get("columnRoles") if isinstance(metadata.get("columnRoles"), dict) else {}

    def first(candidates: List[str]) -> Optional[str]:
        for candidate in candidates:
            if candidate.lower() in lower:
                return lower[candidate.lower()]
        for name in names:
            clean = name.lower().replace("_", " ")
            if any(candidate.lower().replace("_", " ") in clean for candidate in candidates):
                return name
        return None

    blocked_actual = {"predicted_value", "prediction", "predicted", "score", "probability", "prediction_score", "predicted_probability", "adjusted_score", "pd", "p_default", "y_pred"}

    def valid_actual(value: Any) -> Optional[str]:
        if not value or value not in names:
            return None
        text = str(value)
        return None if text.lower() in blocked_actual else text

    actual = (
        valid_actual(payload.actualColumn)
        or valid_actual(payload.targetColumn)
        or valid_actual(str(metadata_roles.get("actual")) if metadata_roles.get("actual") in names else None)
        or valid_actual(str(metadata_target) if metadata_target in names else None)
        or first(["actual", "target", "class", "observed", "y_true"])
    )
    if actual and actual.lower() in blocked_actual:
        actual = None
    score = payload.scoreColumn if payload.scoreColumn in names else first(["score", "probability", "prediction_score", "predicted_probability", "pd", "p_default"])
    prediction = payload.predictionColumn if payload.predictionColumn in names else first(["prediction", "predicted", "y_pred", "predicted_value"])
    residual = payload.residualColumn if payload.residualColumn in names else first(["atlas_residual", "residual", "error"])
    abs_residual = payload.absResidualColumn if payload.absResidualColumn in names else first(["atlas_abs_residual", "abs_residual", "absolute_residual"])
    squared_residual = payload.squaredResidualColumn if payload.squaredResidualColumn in names else first(["atlas_squared_residual", "squared_residual"])
    decile = payload.decileColumn if payload.decileColumn in names else first(["decile", "score_decile", "risk_decile"])
    target = payload.targetColumn if payload.targetColumn in names else str(metadata_target) if metadata_target in names else actual
    return {
        "target": target,
        "actual": actual,
        "score": score,
        "prediction": prediction,
        "residual": residual,
        "absResidual": abs_residual,
        "squaredResidual": squared_residual,
        "decile": decile,
    }


def enrich_scored_frame(df: pd.DataFrame, columns: Dict[str, Optional[str]]) -> pd.DataFrame:
    enriched = df.copy()
    score_col = columns.get("score")
    prediction_col = columns.get("prediction")
    actual_col = columns.get("actual")
    residual_col = columns.get("residual")
    abs_residual_col = columns.get("absResidual")
    squared_residual_col = columns.get("squaredResidual")
    decile_col = columns.get("decile")
    if actual_col and prediction_col:
        actual = pd.to_numeric(enriched[actual_col], errors="coerce")
        prediction = pd.to_numeric(enriched[prediction_col], errors="coerce")
        if actual.notna().any() and prediction.notna().any():
            residual = actual - prediction
            if not residual_col:
                enriched["atlas_residual"] = residual
                columns["residual"] = "atlas_residual"
                residual_col = "atlas_residual"
            if not abs_residual_col:
                enriched["atlas_abs_residual"] = residual.abs()
                columns["absResidual"] = "atlas_abs_residual"
            if not squared_residual_col:
                enriched["atlas_squared_residual"] = residual * residual
                columns["squaredResidual"] = "atlas_squared_residual"
            if "atlas_percent_error" not in enriched.columns:
                enriched["atlas_percent_error"] = residual.where(actual != 0) / actual.where(actual != 0)
                columns["percentError"] = "atlas_percent_error"
    if score_col and not decile_col:
        score = pd.to_numeric(enriched[score_col], errors="coerce")
        if score.notna().sum() >= 10:
            ranked = score.rank(method="first", ascending=False)
            enriched["atlas_score_decile"] = pd.qcut(ranked, q=10, labels=False, duplicates="drop")
            enriched["atlas_score_decile"] = pd.to_numeric(enriched["atlas_score_decile"], errors="coerce").fillna(0).astype(int) + 1
            columns["decile"] = "atlas_score_decile"
    return enriched

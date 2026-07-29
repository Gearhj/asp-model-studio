from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from ..core.modeling_scope import authorize_modeling_scope
from ..core.session_checkpoint import save_checkpoint
from ..security.security_store import require_user
from .outlier_service import outlier_service
from .predictor_authorization import bureau_special_mask, governed_predictor_authorization


router = APIRouter()


class OutlierSummaryRequest(BaseModel):
    project_id: str
    target: str | None = None
    event_value: Any = None
    problem_type: str | None = None
    method: str | None = None
    z_thresh: float = 3.0


class OutlierApplyRequest(BaseModel):
    project_id: str
    config: dict[str, str] = Field(default_factory=dict)
    global_method: str = "IQR_1_5"
    target: str | None = None
    event_value: Any = None
    problem_type: str | None = None
    rationales: dict[str, str] = Field(default_factory=dict)
    acknowledged_high_impact: bool = False


def _source_df():
    df = DATASTORE.get_raw_active_df()
    if df is None or df.empty:
        raise HTTPException(status_code=400, detail="No full registered dataset is loaded.")
    return df


def _merge_full_source_exclusions(authorization: dict[str, Any]) -> dict[str, Any]:
    raw = DATASTORE.raw_df
    if raw is None or raw.empty:
        return authorization
    full = governed_predictor_authorization(
        raw,
        target=DATASTORE.target,
        selected_columns=DATASTORE.get_selected_columns(),
    )
    merged = dict(authorization)
    merged["target_source_excluded"] = sorted(
        set(authorization.get("target_source_excluded", []))
        | set(full.get("target_source_excluded", []))
    )
    merged["excluded_predictors"] = {
        **full.get("excluded_predictors", {}),
        **authorization.get("excluded_predictors", {}),
    }
    return merged


@router.post("/summary")
def outliers_summary(request: OutlierSummaryRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "view")
    try:
        result = outlier_service.summary(
            _source_df(),
            target=request.target or DATASTORE.target,
            event_value=request.event_value,
            problem_type=request.problem_type,
            selected_columns=DATASTORE.get_selected_columns(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["predictor_authorization"] = _merge_full_source_exclusions(
        result.get("predictor_authorization") or {}
    )
    result["dataset_version"] = DATASTORE.meta.get("dataset_version") or "unversioned"
    result["application"] = DATASTORE.meta.get("outlier_application")
    return json_safe(result)


@router.post("/apply")
def apply_outlier_treatments(request: OutlierApplyRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "edit")
    target = request.target or DATASTORE.target
    source = _source_df()
    authorization = governed_predictor_authorization(
        source,
        target=target,
        selected_columns=DATASTORE.get_selected_columns(),
    )
    authorization = _merge_full_source_exclusions(authorization)
    authorized = set(authorization["authorized_predictors"])
    normalized_config = {
        feature: request.config.get(feature, "USE_GLOBAL")
        for feature in authorization["authorized_predictors"]
    }
    normalized_rationales = {
        feature: str(request.rationales.get(feature) or "").strip()
        for feature in authorization["authorized_predictors"]
        if str(request.rationales.get(feature) or "").strip()
    }
    dataset_version = DATASTORE.meta.get("dataset_version") or "unversioned"
    prior = DATASTORE.meta.get("outlier_application")
    if (
        isinstance(prior, dict)
        and prior.get("dataset_version") == dataset_version
        and prior.get("global_method") == request.global_method
        and prior.get("config") == normalized_config
        and (prior.get("rationales") or {}) == normalized_rationales
    ):
        return json_safe({
            "ok": True,
            "scope": "full_dataset",
            "application": prior,
            "idempotent": True,
        })
    try:
        work, applied = outlier_service.apply(
            source,
            config=normalized_config,
            global_method=request.global_method,
            target=target,
            selected_columns=DATASTORE.get_selected_columns(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    high_impact: list[dict[str, Any]] = []
    for treatment in applied:
        feature = str(treatment.get("feature") or "")
        if feature not in authorized:
            continue
        numeric = pd.to_numeric(source[feature], errors="coerce")
        ordinary_count = int((numeric.notna() & ~bureau_special_mask(numeric)).sum())
        rate = int(treatment.get("changed_values") or 0) / max(ordinary_count, 1)
        if rate >= 0.10 and int(treatment.get("changed_values") or 0) > 0:
            high_impact.append({
                "feature": feature,
                "changed_values": int(treatment.get("changed_values") or 0),
                "changed_rate": rate,
            })
    if high_impact and not request.acknowledged_high_impact:
        names = ", ".join(row["feature"] for row in high_impact[:5])
        raise HTTPException(
            status_code=409,
            detail=(
                "High-impact confirmation is required before applying this treatment "
                f"configuration. At least 10% of ordinary values change for: {names}."
            ),
        )

    applied_at = datetime.now(timezone.utc).isoformat()
    application = {
        "applied_at": applied_at,
        "dataset_version": dataset_version,
        "row_count": int(len(work)),
        "global_method": request.global_method,
        "config": normalized_config,
        "rationales": normalized_rationales,
        "treatments": applied,
        "changed_values": int(sum(int(row.get("changed_values") or 0) for row in applied)),
        "high_impact_features": high_impact,
        "high_impact_acknowledged": bool(high_impact and request.acknowledged_high_impact),
        "row_removal_applied": False,
        "state": "applied",
        "predictor_authorization": authorization,
    }
    DATASTORE.set_processed(work)
    DATASTORE.meta["processed_stage"] = "outliers"
    DATASTORE.meta["outlier_application"] = application
    DATASTORE.meta.pop("missing_application", None)
    DATASTORE.meta.pop("missing_config", None)
    DATASTORE.meta.pop("missing_validation", None)
    DATASTORE.meta["split_status"] = "stale"
    manifest = DATASTORE.meta.get("feature_manifest")
    if isinstance(manifest, dict):
        manifest["split_status"] = "stale"

    if not save_checkpoint():
        raise HTTPException(status_code=500, detail="Outlier treatments were calculated, but ATLAS could not persist the workflow checkpoint.")
    return json_safe({"ok": True, "scope": "full_dataset", "application": application})

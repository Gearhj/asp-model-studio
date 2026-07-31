from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from ..core.modeling_scope import authorize_modeling_scope
from ..core.pretraining_invalidation import invalidate_downstream_training_state
from ..core.session_checkpoint import save_checkpoint
from ..datasets.dataset_identity import (
    assert_expected_active_identity,
    coalesce_identity_expectations,
)
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
    expected_dataset_id: str | None = None
    expected_dataset_version_id: str | None = None
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    dataset_version: str | None = None


class OutlierApplyRequest(BaseModel):
    project_id: str
    config: dict[str, str] = Field(default_factory=dict)
    global_method: str = "IQR_1_5"
    target: str | None = None
    event_value: Any = None
    problem_type: str | None = None
    rationales: dict[str, str] = Field(default_factory=dict)
    acknowledged_high_impact: bool = False
    expected_dataset_id: str | None = None
    expected_dataset_version_id: str | None = None
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    dataset_version: str | None = None


def _active_identity(request: Any, user: Dict[str, Any]) -> Dict[str, Any]:
    dataset_id, dataset_version_id, legacy_version = (
        coalesce_identity_expectations(
            expected_dataset_id=request.expected_dataset_id,
            expected_dataset_version_id=request.expected_dataset_version_id,
            dataset_id=request.dataset_id,
            dataset_version_id=request.dataset_version_id,
            legacy_dataset_version=request.dataset_version,
        )
    )
    return assert_expected_active_identity(
        request.project_id,
        expected_dataset_id=dataset_id,
        expected_dataset_version_id=dataset_version_id,
        legacy_dataset_version=legacy_version,
        require_expected=True,
        user=user,
    )


def _identity_fields(identity: Dict[str, Any]) -> Dict[str, str]:
    dataset_version_id = str(identity["dataset_version_id"])
    return {
        "project_id": str(identity["project_id"]),
        "dataset_id": str(identity["dataset_id"]),
        "dataset_version_id": dataset_version_id,
        # Compatibility alias only; canonical identity remains dataset_version_id.
        "dataset_version": dataset_version_id,
    }


def _record_matches_identity(
    record: Any,
    identity: Dict[str, Any],
) -> bool:
    legacy = str(record.get("dataset_version") or "") if isinstance(record, dict) else ""
    return (
        isinstance(record, dict)
        and record.get("project_id") == identity["project_id"]
        and record.get("dataset_id") == identity["dataset_id"]
        and record.get("dataset_version_id") == identity["dataset_version_id"]
        and (not legacy or legacy == identity["dataset_version_id"])
    )


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
    scoped_store = DATASTORE.current()
    # Hold the activation/mutation lock for the read so the response cannot
    # combine A's identity with B's frame or preparation metadata.
    with scoped_store.state_lock:
        identity = _active_identity(request, user)
        try:
            result = outlier_service.summary(
                _source_df(),
                target=request.target or scoped_store.target,
                event_value=request.event_value,
                problem_type=request.problem_type,
                selected_columns=scoped_store.get_selected_columns(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result["predictor_authorization"] = (
            _merge_full_source_exclusions(
                result.get("predictor_authorization") or {}
            )
        )
        result.update(_identity_fields(identity))
        prior = scoped_store.meta.get("outlier_application")
        result["application"] = (
            deepcopy(prior)
            if _record_matches_identity(prior, identity)
            else None
        )
        return json_safe(result)


@router.post("/apply")
def apply_outlier_treatments(request: OutlierApplyRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "edit")
    scoped_store = DATASTORE.current()
    with scoped_store.state_lock:
        identity = _active_identity(request, user)
        input_revision = int(scoped_store.data_revision)
        target = request.target or scoped_store.target
        selected_columns = scoped_store.get_selected_columns()
        source = _source_df().copy()
        prior = deepcopy(scoped_store.meta.get("outlier_application"))
    authorization = governed_predictor_authorization(
        source,
        target=target,
        selected_columns=selected_columns,
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
    if (
        _record_matches_identity(prior, identity)
        and prior.get("global_method") == request.global_method
        and prior.get("config") == normalized_config
        and (prior.get("rationales") or {}) == normalized_rationales
    ):
        with scoped_store.state_lock:
            if int(scoped_store.data_revision) != input_revision:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "The governed dataset or preparation state changed "
                        "while the outlier plan was being evaluated. Reload "
                        "the current plan before continuing."
                    ),
                )
        return json_safe({
            "ok": True,
            "scope": "full_dataset",
            **_identity_fields(identity),
            "application": prior,
            "idempotent": True,
        })
    try:
        work, applied = outlier_service.apply(
            source,
            config=normalized_config,
            global_method=request.global_method,
            target=target,
            selected_columns=selected_columns,
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
        **_identity_fields(identity),
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
    with scoped_store.state_lock:
        # Revalidate under the same lock used by activation and training
        # persistence so a calculation for an old version can never commit.
        assert_expected_active_identity(
            request.project_id,
            expected_dataset_id=identity["dataset_id"],
            expected_dataset_version_id=identity["dataset_version_id"],
            user=user,
            store=scoped_store,
        )
        if int(scoped_store.data_revision) != input_revision:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The governed dataset or preparation state changed while "
                    "outlier treatments were being calculated. Reload and "
                    "apply the plan again."
                ),
            )
        scoped_store.set_processed(work)
        scoped_store.meta["processed_stage"] = "outliers"
        scoped_store.meta["outlier_application"] = application
        scoped_store.meta.pop("missing_application", None)
        scoped_store.meta.pop("missing_config", None)
        scoped_store.meta.pop("missing_validation", None)
        invalidate_downstream_training_state(
            "The governed outlier treatment changed.",
            store=scoped_store,
            split_status="stale",
        )

    if not save_checkpoint():
        raise HTTPException(status_code=500, detail="Outlier treatments were calculated, but ATLAS could not persist the workflow checkpoint.")
    return json_safe({
        "ok": True,
        "scope": "full_dataset",
        **_identity_fields(identity),
        "application": application,
    })

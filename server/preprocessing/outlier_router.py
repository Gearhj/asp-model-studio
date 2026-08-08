from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..analysis_partition.types import AnalysisPartitionError
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
from .development_scope import (
    DevelopmentAnalysisScope,
    resolve_development_analysis_scope,
    scope_http_exception,
)
from .outlier_service import outlier_service
from .predictor_authorization import bureau_special_mask


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
    analysis_partition_id: str | None = None
    analysis_partition_revision: int | None = None


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
    analysis_partition_id: str | None = None
    analysis_partition_revision: int | None = None


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


def _full_structural_source():
    df = DATASTORE.get_raw_active_df()
    if df is None or df.empty:
        raise HTTPException(status_code=400, detail="No full registered dataset is loaded.")
    return df


def _development_scope(
    request: Any,
    identity: Dict[str, Any],
    scoped_store: Any,
    *,
    actor: Any = None,
) -> DevelopmentAnalysisScope:
    try:
        return resolve_development_analysis_scope(
            scoped_store,
            identity,
            requested_target=getattr(request, "target", None),
            requested_event_value=getattr(request, "event_value", None),
            requested_problem_type=getattr(request, "problem_type", None),
            expected_analysis_partition_id=getattr(
                request, "analysis_partition_id", None
            ),
            expected_analysis_partition_revision=getattr(
                request, "analysis_partition_revision", None
            ),
            actor=actor,
        )
    except AnalysisPartitionError as exc:
        raise scope_http_exception(exc) from exc


def _record_matches_scope(
    record: Any,
    identity: Dict[str, Any],
    scope: DevelopmentAnalysisScope,
) -> bool:
    return bool(
        _record_matches_identity(record, identity)
        and record.get("analysis_partition_id")
        == scope.partition.get("analysis_partition_id")
        and int(record.get("analysis_partition_revision") or 0)
        == int(scope.partition.get("revision") or 0)
    )


def _full_dataset_application_metadata(
    scope: DevelopmentAnalysisScope,
) -> Dict[str, Any]:
    """Describe a full-population transform without widening analysis scope.

    Outlier cutoffs and every target-directed comparison are resolved from the
    sealed development population, but the accepted treatment is materialized
    over the exact full governed dataset.  Keep both facts explicit so callers
    cannot mistake the analysis population for the application population.
    """

    return {
        **scope.metadata(),
        "scope": "full_dataset",
        "application_scope": "full_dataset",
        "materialization_scope": "full_dataset",
        "application_source_population": "full_governed_population",
    }


def _public_application(record: Any) -> Any:
    """Normalize an older stored application at the response boundary."""

    if not isinstance(record, dict):
        return record
    return {
        **record,
        "scope": "full_dataset",
        "application_scope": "full_dataset",
        "materialization_scope": "full_dataset",
        "application_source_population": "full_governed_population",
    }


@router.post("/summary")
def outliers_summary(request: OutlierSummaryRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "view")
    scoped_store = DATASTORE.current()
    # Hold the activation/mutation lock for the read so the response cannot
    # combine A's identity with B's frame or preparation metadata.
    with scoped_store.state_lock:
        identity = _active_identity(request, user)
        scope = _development_scope(
            request, identity, scoped_store, actor=user.get("userId")
        )
        source = _full_structural_source()
        structural = source.drop(columns=[scope.target], errors="ignore")
        try:
            result = outlier_service.summary(
                structural,
                target=scope.target,
                event_value=scope.event_value,
                problem_type=scope.problem_type,
                predictor_authorization=scope.predictor_authorization,
                target_analysis_features=scope.development_features,
                target_analysis_target=scope.development_target,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result["predictor_authorization"] = dict(
            scope.predictor_authorization
        )
        result.update(_identity_fields(identity))
        result.update(scope.metadata())
        prior = scoped_store.meta.get("outlier_application")
        result["application"] = (
            _public_application(deepcopy(prior))
            if _record_matches_scope(prior, identity, scope)
            else None
        )
        return json_safe(result)


@router.post("/apply")
def apply_outlier_treatments(request: OutlierApplyRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "edit")
    scoped_store = DATASTORE.current()
    with scoped_store.state_lock:
        identity = _active_identity(request, user)
        scope = _development_scope(
            request, identity, scoped_store, actor=user.get("userId")
        )
        input_revision = int(scoped_store.data_revision)
        target = scope.target
        selected_columns = scoped_store.get_selected_columns()
        source = _full_structural_source().copy()
        prior = deepcopy(scoped_store.meta.get("outlier_application"))
    authorization = dict(scope.predictor_authorization)
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
        _record_matches_scope(prior, identity, scope)
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
            **_identity_fields(identity),
            **_full_dataset_application_metadata(scope),
            "application": _public_application(prior),
            "idempotent": True,
        })
    try:
        work, applied = outlier_service.apply(
            source,
            config=normalized_config,
            global_method=request.global_method,
            target=target,
            selected_columns=selected_columns,
            predictor_authorization=authorization,
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
        **_full_dataset_application_metadata(scope),
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
        **_identity_fields(identity),
        **_full_dataset_application_metadata(scope),
        "application": application,
    })

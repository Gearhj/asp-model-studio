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
from ..core.result_store import RESULTS
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
from .preprocessing_contract import (
    PREPROCESSING_CONTRACT_VERSION,
    FIT_SCOPE_DEVELOPMENT_PREVIEW,
    apply_outlier_recipe,
    assert_mutation_expectations,
    build_preprocessing_policy_record,
    canonical_hash,
    capture_preprocessing_mutation_state,
    classify_preprocessing_record,
    fit_metadata,
    fit_outlier_recipe,
    quarantine_preprocessing_state,
    resolve_special_value_contract,
    restore_preprocessing_mutation_state,
    scope_lineage,
)


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
    preprocessing_contract_version: int | None = None
    expected_predictor_authorization_id: str | None = None
    expected_special_value_review_id: str | None = None
    expected_special_value_review_revision: int | None = None
    analytical_types: dict[str, dict[str, Any]] = Field(default_factory=dict)


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
    df = DATASTORE.get_raw_active_df(include_target=False)
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
    special_contract = resolve_special_value_contract(
        identity=identity,
        scope=scope,
        store=DATASTORE.current(),
    )
    status, _ = classify_preprocessing_record(
        record,
        lineage=scope_lineage(scope, special_contract),
    )
    return status == "current"


def _full_dataset_application_metadata(
    scope: DevelopmentAnalysisScope,
) -> Dict[str, Any]:
    """Describe Development preview approval without holdout application."""

    return {
        **scope.metadata(),
        "scope": "development_population",
        "fit_scope": "development_preview",
        "application_scope": "none_prelock",
        "materialization_scope": "none",
        "application_source_population": None,
        "backend_materialization": False,
        "processed_frame_materialized": False,
        "sealed_holdout_transformed": False,
    }


def _public_application(record: Any) -> Any:
    """Return only the artifact as persisted; never relabel legacy state."""

    return deepcopy(record) if isinstance(record, dict) else record


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
        special_contract = resolve_special_value_contract(
            identity=identity,
            scope=scope,
            store=scoped_store,
        )
        lineage = scope_lineage(scope, special_contract)
        prior = scoped_store.meta.get("outlier_application")
        prior_status, prior_reasons = classify_preprocessing_record(
            prior,
            lineage=lineage,
        )
        try:
            result = outlier_service.summary(
                structural,
                target=scope.target,
                event_value=scope.event_value,
                problem_type=scope.problem_type,
                predictor_authorization=scope.predictor_authorization,
                target_analysis_features=scope.development_features,
                target_analysis_target=scope.development_target,
                special_value_contract=special_contract,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result["predictor_authorization"] = dict(
            scope.predictor_authorization
        )
        result.update(_identity_fields(identity))
        result.update(scope.metadata())
        result["final_holdout_predictors_in_structural_profile"] = True
        result["final_holdout_predictors_included_in_structural_profile"] = True
        result["application"] = (
            _public_application(deepcopy(prior))
            if prior_status == "current"
            else None
        )
        result["preprocessing_contract_version"] = PREPROCESSING_CONTRACT_VERSION
        result["preprocessing_lineage"] = lineage
        result["special_value_contract"] = special_contract
        result["legacy_artifact_status"] = (
            prior_status if prior_status.startswith("stale") else None
        )
        result["legacy_artifact_reasons"] = prior_reasons
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
        registered_row_count = int(len(_full_structural_source()))
        prior = deepcopy(scoped_store.meta.get("outlier_application"))
        special_contract = resolve_special_value_contract(
            identity=identity,
            scope=scope,
            store=scoped_store,
        )
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
    lineage = scope_lineage(scope, special_contract)
    try:
        assert_mutation_expectations(request, lineage=lineage)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    approved_policy = {
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "artifact_kind": "approved_outlier_policy",
        "status": "approved",
        "global_method": request.global_method,
        "config": normalized_config,
        "rationales": normalized_rationales,
        "analytical_types": dict(request.analytical_types or {}),
    }
    approved_policy["outlier_policy_id"] = (
        f"op-{canonical_hash(approved_policy)[:20]}"
    )
    prior_policy = (
        prior.get("approved_policy")
        if isinstance(prior, dict)
        and isinstance(prior.get("approved_policy"), dict)
        else {}
    )
    approved_policy["outlier_policy_revision"] = (
        int(prior_policy.get("outlier_policy_revision") or 1)
        if prior_policy.get("outlier_policy_id")
        == approved_policy["outlier_policy_id"]
        else int(prior_policy.get("outlier_policy_revision") or 0) + 1
    )
    prior_status, prior_reasons = classify_preprocessing_record(
        prior,
        lineage=lineage,
    )
    if prior_status.startswith("stale"):
        with scoped_store.state_lock:
            quarantine_preprocessing_state(
                scoped_store,
                keys=(
                    "outlier_application",
                    "outlier_policy",
                    "missing_application",
                    "missing_policy",
                    "missing_config",
                    "missing_validation",
                    "preprocessing_policy",
                    "feature_manifest",
                    "feature_preview",
                    "materialized_feature_names",
                ),
                reason="; ".join(prior_reasons),
            )
            input_revision = int(scoped_store.data_revision)
        prior = None
    if (
        prior_status == "current"
        and prior.get("approved_policy") == approved_policy
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
        preview_fit = fit_outlier_recipe(
            scope.development_features,
            policy=approved_policy,
            fit=fit_metadata(
                fit_scope=FIT_SCOPE_DEVELOPMENT_PREVIEW,
                population_id=str(scope.partition.get("development_partition_id")),
                population_count=len(scope.development_features),
                lineage=lineage,
                actor=str(user.get("userId") or "atlas-user"),
                application_scope="development_population_preview",
                application_population_id=str(
                    scope.partition.get("development_partition_id")
                ),
                application_population_rows=len(scope.development_features),
                evidence_references=[],
            ),
            special_value_contract=special_contract,
        )
        _, projection = apply_outlier_recipe(
            scope.development_features,
            recipe=preview_fit,
            target=None,
            special_value_contract=special_contract,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    high_impact: list[dict[str, Any]] = []
    for treatment in projection["treatments"]:
        feature = str(treatment.get("feature") or "")
        if feature not in authorized:
            continue
        rate = float(treatment.get("flagged_cell_rate") or 0)
        changed = int(treatment.get("flagged_cell_count") or 0)
        if rate >= 0.10 and changed > 0:
            high_impact.append({
                "feature": feature,
                "changed_values": changed,
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
        **lineage,
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "artifact_kind": "outlier_policy_approval",
        "row_count": int(len(scope.development_features)),
        "registered_population_row_count": registered_row_count,
        "global_method": request.global_method,
        "config": normalized_config,
        "rationales": normalized_rationales,
        "approved_policy": approved_policy,
        "development_preview_fit": preview_fit,
        "development_preview": projection,
        "counts": projection["counts"],
        "changed_values": int(projection["counts"]["flagged_cell_count"]),
        "high_impact_features": high_impact,
        "high_impact_acknowledged": bool(high_impact and request.acknowledged_high_impact),
        "row_removal_applied": False,
        "state": "approved",
        "predictor_authorization": authorization,
        "special_value_contract": special_contract,
        "fold_fitted_artifact_status": "required_during_training",
        "final_fitted_artifact_status": "required_during_training",
        "backend_materialization": False,
        "processed_frame_materialized": False,
        "sealed_holdout_transformed": False,
    }
    combined_policy = build_preprocessing_policy_record(
        lineage=lineage,
        special_value_contract=special_contract,
        actor=str(user.get("userId") or "atlas-user"),
        outlier_policy=approved_policy,
        missing_policy=None,
        outlier_development_preview_fit=preview_fit,
        missing_development_preview_fit=None,
        previous=scoped_store.meta.get("preprocessing_policy"),
        approved_at=applied_at,
    )
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
        result_store = RESULTS.current()
        rollback_snapshot = capture_preprocessing_mutation_state(
            scoped_store, result_store
        )
        quarantine_preprocessing_state(
            scoped_store,
            keys=(
                "missing_application",
                "missing_policy",
                "missing_config",
                "missing_validation",
                "preprocessing_policy",
                "feature_manifest",
                "feature_preview",
                "materialized_feature_names",
                "processed_stage",
            ),
            reason="A new governed outlier policy superseded dependent state.",
        )
        scoped_store.processed_df = None
        scoped_store.meta.pop("processed_stage", None)
        scoped_store.meta["outlier_policy"] = approved_policy
        scoped_store.meta["outlier_application"] = application
        scoped_store.meta["preprocessing_policy"] = combined_policy
        scoped_store.meta.pop("missing_application", None)
        scoped_store.meta.pop("missing_policy", None)
        scoped_store.meta.pop("missing_config", None)
        scoped_store.meta.pop("missing_validation", None)
        scoped_store.meta.pop("feature_manifest", None)
        scoped_store.meta.pop("feature_preview", None)
        scoped_store.meta.pop("materialized_feature_names", None)
        invalidate_downstream_training_state(
            "The governed outlier treatment changed.",
            store=scoped_store,
            split_status="stale",
        )
        if not save_checkpoint():
            restore_preprocessing_mutation_state(
                scoped_store, result_store, rollback_snapshot
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "Outlier policy approval could not be persisted; the "
                    "in-memory workflow state was rolled back."
                ),
            )
    return json_safe({
        "ok": True,
        **_identity_fields(identity),
        **_full_dataset_application_metadata(scope),
        "application": application,
    })

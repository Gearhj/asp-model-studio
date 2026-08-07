# server/eda/eda_router.py
# =============================================================================
# EDA Router – tabular summaries + D3 endpoints
# =============================================================================

from __future__ import annotations

import logging
import os
import uuid
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from ..core.modeling_scope import authorize_modeling_scope
from ..security.security_store import require_user
from .documentation_service import (
    EDADocumentationValidationError,
    eda_documentation_service,
)
from .documentation_types import (
    EDACompletionRequest,
    EDADocumentationPayload,
    EDAInvalidationRequest,
)
from .eda_service import eda_service
from .workspace_service import (
    RelationshipSampleValidationError,
    eda_workspace_service,
)
from .analytical_contract import EDAAnalyticalContractError
from .bureau_semantic_contract import validate_bureau_semantic_handoff
from .workspace_types import (
    EDARelationshipSampleRequest,
    EDAVifResolutionDecisionRequest,
    EDAVifResolutionPlanRequest,
    EDAVifSimulationRequest,
    EDAWorkspaceRequest,
    TargetByPredictorRequest,
)

router = APIRouter()
logger = logging.getLogger("atlas.eda")
DEV_LOGGING = os.getenv("ATLAS_ENV", "development").lower() in {"dev", "development", "local"}


def _raise_documentation_validation(
    exc: EDADocumentationValidationError,
) -> None:
    status_code = (
        409
        if exc.code
        in {
            "eda_documentation_context_mismatch",
            "eda_evidence_context_mismatch",
            "eda_governed_context_incomplete",
            "eda_project_scope_mismatch",
        }
        else 422
    )
    raise HTTPException(
        status_code=status_code,
        detail={
            "ok": False,
            "code": exc.code,
            "message": str(exc),
            "blockers": exc.blockers,
        },
    ) from exc


def _raise_analytical_readiness(exc: EDAAnalyticalContractError) -> None:
    raise HTTPException(
        status_code=409,
        detail={
            "ok": False,
            "code": getattr(exc, "code", "analysis_partition_stale"),
            "message": str(exc),
            "recovery": getattr(
                exc,
                "recovery",
                "Return to Data Acquisition and confirm the Analysis Partition.",
            ),
            "stale_artifacts": getattr(exc, "stale_artifacts", []),
        },
    ) from exc


@router.get("/documentation/{project_id}")
def get_eda_documentation(
    project_id: str,
    expected_dataset_id: str = Query(...),
    expected_dataset_version_id: str = Query(...),
    user: Dict[str, Any] = Depends(require_user),
):
    """Read the canonical EDA documentation state consumed by MDD."""

    authorize_modeling_scope(user, project_id, "view")
    try:
        return eda_documentation_service.get_state(
            project_id,
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_dataset_version_id,
        )
    except EDADocumentationValidationError as exc:
        _raise_documentation_validation(exc)
    except EDAAnalyticalContractError as exc:
        _raise_analytical_readiness(exc)


@router.post("/documentation/draft")
def save_eda_documentation_draft(
    request: EDADocumentationPayload,
    user: Dict[str, Any] = Depends(require_user),
):
    """Upsert one current draft without modifying an approved snapshot."""

    authorize_modeling_scope(user, request.project_id, "edit")
    try:
        return eda_documentation_service.upsert_draft(request, user)
    except EDADocumentationValidationError as exc:
        _raise_documentation_validation(exc)
    except EDAAnalyticalContractError as exc:
        _raise_analytical_readiness(exc)


@router.post("/confirmation")
def confirm_eda_documentation(
    request: EDADocumentationPayload,
    user: Dict[str, Any] = Depends(require_user),
):
    """Validate and freeze an immutable EDA documentation snapshot."""

    authorize_modeling_scope(user, request.project_id, "edit")
    try:
        return eda_documentation_service.confirm(request, user)
    except EDADocumentationValidationError as exc:
        _raise_documentation_validation(exc)
    except EDAAnalyticalContractError as exc:
        _raise_analytical_readiness(exc)


@router.post("/completion")
def complete_eda_governance(
    request: EDACompletionRequest,
    user: Dict[str, Any] = Depends(require_user),
):
    """Run the idempotent all-or-nothing EDA governance sequence."""

    authorize_modeling_scope(user, request.payload.project_id, "edit")
    try:
        return eda_documentation_service.complete(request, user)
    except EDADocumentationValidationError as exc:
        _raise_documentation_validation(exc)
    except EDAAnalyticalContractError as exc:
        _raise_analytical_readiness(exc)


@router.post("/documentation/{project_id}/invalidate")
def invalidate_eda_documentation(
    project_id: str,
    request: EDAInvalidationRequest,
    user: Dict[str, Any] = Depends(require_user),
):
    """Explicitly mark the current approval stale after an upstream change."""

    authorize_modeling_scope(user, project_id, "edit")
    try:
        return eda_documentation_service.invalidate(
            project_id,
            request.reason,
            user,
            upstream_revision=request.upstream_revision,
            expected_dataset_id=request.expected_dataset_id,
            expected_dataset_version_id=request.expected_dataset_version_id,
        )
    except EDADocumentationValidationError as exc:
        _raise_documentation_validation(exc)
    except EDAAnalyticalContractError as exc:
        _raise_analytical_readiness(exc)


@router.post("/workspace/{section}")
def eda_workspace_section(section: str, request: EDAWorkspaceRequest, user: Dict[str, Any] = Depends(require_user)):
    correlation_id = f"eda-{uuid.uuid4().hex}"
    correlation_headers = {"X-Request-Correlation-ID": correlation_id}
    try:
        authorize_modeling_scope(user, request.project_id, "view")
        # Feature Engineering retains its existing selected-features-only VIF
        # request. It is routed to a separate target-free implementation, not
        # to the governed EDA Relationships factory. Every request containing
        # target or canonical Data Acquisition lineage remains strict.
        predictor_only_shape = (
            section == "relationships"
            and request.target is None
            and request.problem_type is None
            and request.event_value is None
            and request.positive_value is None
            and request.negative_value is None
            and request.non_event_value is None
            and request.target_contract_id is None
            and request.predictor_authorization_id is None
            and request.analysis_partition_id is None
            and request.analysis_partition_revision is None
            and request.special_value_review_id is None
            and request.special_value_review_revision is None
            and request.bureau_semantic_annotation_state is None
            and len(request.selected_features) >= 2
            and not request.pairwise_features
            and request.feature is None
            and request.segment_field is None
            and request.date_field is None
        )
        predictor_only_requested = (
            request.analysis_mode == "predictor_only_diagnostic"
            or predictor_only_shape
        )
        if predictor_only_requested:
            if not predictor_only_shape:
                raise ValueError(
                    "Predictor-only Relationships accepts only an exact dataset identity and selected predictor fields."
                )
            result = eda_workspace_service.predictor_only_relationships(
                request
            )
        else:
            # Resolve the optional Bureau metadata identity with this exact
            # authenticated principal before EDA can materialize a development
            # target or consult an analytical cache.
            validate_bureau_semantic_handoff(request, user)
            result = eda_workspace_service.section(
                section,
                request,
                canonical_lineage_required=True,
            )
        if DEV_LOGGING:
            logger.info(
                "EDA request received section=%s dataset=%s found=true rows=%s cols=%s target=%s status=200",
                section,
                result.get("dataset_version"),
                result.get("row_count"),
                result.get("column_count"),
                result.get("target"),
            )
        # JSONResponse performs the final serialization here, inside the
        # guarded boundary.  `json_safe` removes NumPy scalar/array values and
        # `jsonable_encoder` verifies the remainder before control returns to
        # FastAPI's outer response machinery.
        payload = jsonable_encoder(json_safe(result))
        return JSONResponse(
            status_code=200,
            content=payload,
            headers=correlation_headers,
        )
    except HTTPException as exc:
        # Identity and authorization helpers raise HTTPException directly.
        # Normalize those expected failures here so they carry the same safe
        # correlation contract as analytical-readiness failures.
        status_code = int(exc.status_code)
        if status_code in {401, 403}:
            code = "eda_authorization_required"
            message = "The current session is not authorized for this project-scoped EDA request."
            recovery = "Sign in again or ask a project administrator to confirm access."
        elif status_code == 422:
            code = "dataset_identity_required"
            message = "EDA requires the exact active dataset and dataset-version identifiers."
            recovery = "Reload the project from Data Acquisition and retry."
        elif status_code == 409:
            code = "dataset_identity_mismatch"
            message = "The requested dataset identity is not the exact active Dataset Library version."
            recovery = "Reload Data Acquisition and retry against its active version."
        else:
            code = "eda_request_invalid"
            message = "The governed EDA request could not be accepted."
            recovery = "Review the project and dataset context, then retry."
        logger.info(
            "EDA governed request rejected correlation_id=%s section=%s project_id=%s code=%s status=%s",
            correlation_id,
            section,
            request.project_id,
            code,
            status_code,
        )
        raise HTTPException(
            status_code=status_code,
            detail={
                "ok": False,
                "code": code,
                "message": message,
                "recovery": recovery,
                "correlation_id": correlation_id,
            },
            headers=correlation_headers,
        ) from exc
    except EDAAnalyticalContractError as exc:
        if DEV_LOGGING:
            logger.info(
                "EDA governed prerequisite unavailable correlation_id=%s section=%s project_id=%s code=%s status=409",
                correlation_id,
                section,
                request.project_id,
                getattr(exc, "code", "eda_contract_unavailable"),
            )
        raise HTTPException(
            status_code=409,
            detail={
                "ok": False,
                "code": getattr(exc, "code", "eda_contract_unavailable"),
                "message": str(exc),
                "recovery": getattr(
                    exc,
                    "recovery",
                    "Return to Data Acquisition and confirm the governed EDA prerequisites.",
                ),
                "stale_artifacts": getattr(exc, "stale_artifacts", []),
                "correlation_id": correlation_id,
            },
            headers=correlation_headers,
        ) from exc
    except (RelationshipSampleValidationError, ValueError) as exc:
        if DEV_LOGGING:
            logger.info(
                "EDA request validation failed correlation_id=%s section=%s project_id=%s status=422",
                correlation_id,
                section,
                request.project_id,
            )
        raise HTTPException(
            status_code=422,
            detail={
                "ok": False,
                "code": "eda_request_invalid",
                "message": str(exc),
                "recovery": "Review the requested EDA section and governed field selections.",
                "correlation_id": correlation_id,
            },
            headers=correlation_headers,
        ) from exc
    except Exception as exc:
        logger.exception(
            "Unexpected EDA execution failure correlation_id=%s section=%s project_id=%s",
            correlation_id,
            section,
            request.project_id,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "ok": False,
                "code": "internal_eda_execution_error",
                "message": "EDA could not complete the governed analytical request.",
                "recovery": (
                    "Retry the request once. If it continues to fail, provide "
                    "the correlation ID to an administrator."
                ),
                "correlation_id": correlation_id,
            },
            headers=correlation_headers,
        ) from exc


@router.post("/target-by-predictor")
def eda_target_by_predictor(request: TargetByPredictorRequest, user: Dict[str, Any] = Depends(require_user)):
    """On-demand Target-by-Predictor over the governed development population."""
    authorize_modeling_scope(user, request.project_id, "view")
    try:
        validate_bureau_semantic_handoff(request, user)
        return eda_workspace_service.target_by_predictor(request)
    except EDAAnalyticalContractError as exc:
        _raise_analytical_readiness(exc)
    except ValueError as exc:
        detail = str(exc)
        status = 409 if "no full backend dataset" in detail.lower() else 400
        raise HTTPException(
            status_code=status,
            detail={
                "ok": False,
                "code": (
                    "backend_dataset_missing"
                    if status == 409
                    else "eda_request_invalid"
                ),
                "message": detail,
                "recovery": "Confirm a target and a valid predictor in Data Acquisition.",
                "stale_artifacts": [],
            },
        ) from exc


@router.post("/vif-simulation")
def eda_vif_simulation(request: EDAVifSimulationRequest, user: Dict[str, Any] = Depends(require_user)):
    """Run a temporary, non-mutating VIF exclusion scenario."""

    authorize_modeling_scope(user, request.project_id, "view")
    try:
        validate_bureau_semantic_handoff(request, user)
        return eda_workspace_service.vif_simulation(request)
    except EDAAnalyticalContractError as exc:
        _raise_analytical_readiness(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/vif-resolution-plan")
def eda_vif_resolution_plan(
    request: EDAVifResolutionPlanRequest,
    user: Dict[str, Any] = Depends(require_user),
):
    """Generate a governed recommendation plan without changing predictors."""

    authorize_modeling_scope(user, request.project_id, "view")
    try:
        validate_bureau_semantic_handoff(request, user)
        return eda_workspace_service.vif_resolution_plan(request)
    except EDAAnalyticalContractError as exc:
        _raise_analytical_readiness(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "ok": False,
                "code": "vif_resolution_plan_invalid",
                "message": str(exc),
            },
        ) from exc


@router.post("/vif-resolution-plan/decision")
def eda_vif_resolution_decision(
    request: EDAVifResolutionDecisionRequest,
    user: Dict[str, Any] = Depends(require_user),
):
    """Record a disposition and draft Feature Engineering recommendations."""

    authorize_modeling_scope(user, request.project_id, "edit")
    try:
        validate_bureau_semantic_handoff(request, user)
        return eda_workspace_service.vif_resolution_decision(
            request,
            actor_id=str(user.get("userId") or user.get("id") or "ATLAS"),
        )
    except EDAAnalyticalContractError as exc:
        _raise_analytical_readiness(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "ok": False,
                "code": "vif_resolution_decision_invalid",
                "message": str(exc),
            },
        ) from exc


@router.get("/vif-resolution-recommendations")
def eda_vif_resolution_recommendations(
    project_id: str = Query(...),
    expected_dataset_id: str = Query(...),
    expected_dataset_version_id: str = Query(...),
    user: Dict[str, Any] = Depends(require_user),
):
    """Return exact-version draft VIF recommendations for Feature Engineering."""

    authorize_modeling_scope(user, project_id, "view")
    return eda_workspace_service.vif_feature_recommendations(
        project_id=project_id,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version_id=expected_dataset_version_id,
    )


@router.post("/relationship-sample")
def eda_relationship_sample(
    request: EDARelationshipSampleRequest,
    user: Dict[str, Any] = Depends(require_user),
):
    """Serve one governed sample reused by the 2D, density, and 3D views."""

    authorize_modeling_scope(user, request.project_id, "view")
    try:
        validate_bureau_semantic_handoff(request, user)
        return eda_workspace_service.relationship_sample(request)
    except EDAAnalyticalContractError as exc:
        _raise_analytical_readiness(exc)
    except RelationshipSampleValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "ok": False,
                "code": "relationship_fields_not_authorized",
                "message": str(exc),
                "rejected_fields": exc.rejected_fields,
            },
        ) from exc
    except ValueError as exc:
        detail = str(exc)
        status = (
            409
            if "dataset" in detail.lower() or "manifest" in detail.lower()
            else 422
        )
        raise HTTPException(
            status_code=status,
            detail={
                "ok": False,
                "code": (
                    "relationship_context_mismatch"
                    if status == 409
                    else "relationship_request_invalid"
                ),
                "message": detail,
            },
        ) from exc


@router.post("/profile")
def eda_profile(request: EDAWorkspaceRequest, user: Dict[str, Any] = Depends(require_user)):
    """Compatibility route for frontend builds that expect a single profile endpoint."""
    return eda_workspace_section("overview", request, user)


@router.post("/analyze")
def eda_analyze(request: EDAWorkspaceRequest, user: Dict[str, Any] = Depends(require_user)):
    """Compatibility route for prior EDA endpoint naming."""
    return eda_workspace_section("overview", request, user)


def _require_df():
    df = DATASTORE.get_active_df()
    if df is not None:
        return df
    raise HTTPException(status_code=400, detail="No dataset loaded.")

def _authorized_df(project_id: str, *, include_target: bool = True):
    """Resolve the fail-closed predictor frame for legacy EDA read routes."""

    try:
        df, target, _y, _problem, _event, authorization = (
            eda_workspace_service.authorized_dataset(
                EDAWorkspaceRequest(
                    project_id=project_id,
                    target=DATASTORE.target,
                )
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not include_target:
        df = df.drop(columns=[target], errors="ignore")
    return df, target, authorization


# ---------------------------------------------------------------------------
# Tabular endpoints (may be used by other steps)
# ---------------------------------------------------------------------------
@router.get("/overview")
def eda_overview(project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    df, _target, _authorization = _authorized_df(project_id, include_target=False)
    return eda_service.dataset_overview(df)


@router.get("/numeric_summary")
def numeric_summary(project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    df, _target, _authorization = _authorized_df(project_id, include_target=False)
    return eda_service.numeric_summary(df)


@router.get("/missing")
def missing_summary(project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    df, _target, _authorization = _authorized_df(project_id, include_target=False)
    return eda_service.missing_summary(df)


@router.get("/histogram/{column}")
def histogram(column: str, project_id: str = Query(...), bins: int = Query(default=40, ge=5, le=60), user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    try:
        payload = eda_workspace_service.section(
            "distribution",
            EDAWorkspaceRequest(
                project_id=project_id,
                target=DATASTORE.target,
                feature=column,
                histogram_bins=bins,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rows = payload.get("bins") or []
    edges = [rows[0]["lower"], *[row["upper"] for row in rows]] if rows else []
    return {
        "ok": True,
        "edges": edges,
        "counts": [row["count"] for row in rows],
        "column": column,
        "requested_bins": bins,
        "returned_bins": len(rows),
        "row_count": int((payload.get("statistics") or {}).get("count") or 0),
        "missing_count": int((payload.get("missing_bucket") or {}).get("count") or 0),
        "predictor_authorization": payload.get("predictor_authorization"),
    }


@router.get("/boxplot/{column}")
def boxplot(column: str, project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    df, _target, authorization = _authorized_df(project_id, include_target=False)
    if column not in authorization["authorized_predictors"] or column not in df.columns:
        raise HTTPException(
            status_code=422,
            detail=f"Predictor '{column}' is not authorized for EDA boxplot analysis.",
        )
    return eda_service.boxplot_stats(df, column)


@router.get("/correlation")
def correlation(project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    try:
        payload = eda_workspace_service.section(
            "relationships",
            EDAWorkspaceRequest(project_id=project_id, target=DATASTORE.target),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": True,
        "matrix": payload.get("correlation_matrix") or [],
        "columns": payload.get("correlation_columns") or [],
        "predictor_authorization": payload.get("predictor_authorization"),
    }


@router.get("/sample")
def sample(project_id: str = Query(...), max_rows: int = 10000, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    try:
        df, _target, _y, _problem, _event, authorization, scope = (
            eda_workspace_service.authorized_development_dataset(
                EDAWorkspaceRequest(
                    project_id=project_id,
                    target=DATASTORE.target,
                ),
                include_target=False,
            )
        )
    except EDAAnalyticalContractError as exc:
        _raise_analytical_readiness(exc)
    result = eda_service.sample_records(df, max_rows=max_rows)
    result.update(
        {
            "scope": "development_population",
            "analysis_partition_id": scope["analysis_partition_id"],
            "analysis_partition_revision": scope[
                "analysis_partition_revision"
            ],
            "predictor_authorization": authorization,
            "target_excluded": True,
            "final_holdout_accessed": False,
        }
    )
    return result


# ---------------------------------------------------------------------------
# D3 Histogram – POST /api/eda/d3_histogram
# ---------------------------------------------------------------------------
@router.post("/d3_histogram")
def d3_histogram(payload: Dict[str, Any] = Body(...), user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, payload.get("project_id"), "view")
    try:
        df, target, _y, _problem, _event, authorization, scope = (
            eda_workspace_service.authorized_development_dataset(
                EDAWorkspaceRequest(
                    project_id=project_id,
                    target=DATASTORE.target,
                )
            )
        )
    except EDAAnalyticalContractError as exc:
        _raise_analytical_readiness(exc)
    feature = payload.get("feature") or ""
    bins = int(payload.get("bins") or 20)
    sample_pct = int(payload.get("sample_pct") or 10)

    if not feature:
        raise HTTPException(status_code=400, detail="Feature is required.")
    if feature not in authorization["authorized_predictors"]:
        raise HTTPException(
            status_code=422,
            detail=f"Predictor '{feature}' is not authorized for EDA histogram analysis.",
        )

    res = eda_service.d3_histogram(
        df,
        feature=feature,
        target=target,
        bins=bins,
        sample_pct=sample_pct,
    )
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "Histogram failed."))
    res.update(
        {
            "scope": "development_population",
            "analysis_partition_id": scope["analysis_partition_id"],
            "analysis_partition_revision": scope[
                "analysis_partition_revision"
            ],
            "final_holdout_accessed": False,
            "final_holdout_used_for_selection": False,
        }
    )
    return res


# ---------------------------------------------------------------------------
# Boxplot image – GET /api/eda/boxplot?feature=...&sample_pct=10
# ---------------------------------------------------------------------------
@router.get("/boxplot")
def boxplot_image(
    project_id: str = Query(...),
    feature: str = Query(..., description="Numeric feature to visualize"),
    sample_pct: int = Query(10, ge=1, le=100),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    df, _target, authorization = _authorized_df(project_id, include_target=False)
    if feature not in authorization["authorized_predictors"] or feature not in df.columns:
        raise HTTPException(
            status_code=422,
            detail=f"Predictor '{feature}' is not authorized for EDA boxplot analysis.",
        )
    res = eda_service.boxplot_image(df, feature=feature, sample_pct=sample_pct)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "Boxplot failed."))
    return res


# ---------------------------------------------------------------------------
# Correlation heatmap – GET /api/eda/corr?sample_pct=10
# ---------------------------------------------------------------------------
@router.get("/corr")
def corr_heatmap(
    project_id: str = Query(...),
    sample_pct: int = Query(10, ge=1, le=100),
    limit: int = Query(20, ge=2, le=20),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    df, _target, _authorization = _authorized_df(project_id, include_target=False)
    res = eda_service.corr_heatmap_image(df, sample_pct=sample_pct, limit=limit)
    if not res.get("ok"):
        # frontend treats missing image as "Not enough numeric columns"
        return {"ok": False, "error": res.get("error", "Heatmap failed.")}
    return res


# ---------------------------------------------------------------------------
# Pairplot – GET /api/eda/pairplot?sample_pct=10
# ---------------------------------------------------------------------------
@router.get("/pairplot")
def pairplot(project_id: str = Query(...), sample_pct: int = Query(10, ge=1, le=100), user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, project_id, "view")
    df, _target, _authorization = _authorized_df(project_id, include_target=False)
    res = eda_service.pairplot_image(df, sample_pct=sample_pct)
    if not res.get("ok"):
        # frontend treats missing image as generic failure
        return {"ok": False, "error": res.get("error", "Pairplot failed.")}
    return res

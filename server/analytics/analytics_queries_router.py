"""Enterprise Analytical Data Plane -- HTTP routes.

Named `analytics_queries_router` (distinct from the existing `analytics_router.py`,
which serves the unrelated AnalyticsWorkbench SQL/insights/export feature) to avoid
any naming collision while still following this repository's existing router-per-
feature convention and mounting under the same `/analytics` prefix family.
"""
from __future__ import annotations

import threading
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..security.security_store import audit_event, require_user, user_can_access_project
from .target_distribution_service import compute_target_distribution
from .distributed_engine_interface import list_configured_engines
from .parquet_service import materialize_parquet_for_version
from .query_contract import AnalyticalQueryRequest, AnalyticalQueryResponse, QueryStatus
from .query_planner import PlanningRejection, decision_matrix_summary
from .query_service import JOBS, execute_query, is_heavy, run_async
from .resource_governance import CONCURRENCY, LIMITS, ResourceRejection
from . import result_cache


router = APIRouter(dependencies=[Depends(require_user)])


def _check_project_access(user: Dict[str, Any], project_id: str) -> None:
    if not user_can_access_project(project_id):
        audit_event("access.denied", "project", project_id, "denied", reason="Analytical query denied for project ACL")
        raise HTTPException(status_code=403, detail="You do not have access to run analytical queries against this project.")


@router.post("/analytics/queries", response_model=AnalyticalQueryResponse)
def submit_query(payload: AnalyticalQueryRequest, user: Dict[str, Any] = Depends(require_user)) -> AnalyticalQueryResponse:
    _check_project_access(user, payload.projectId)
    user_id = str(user.get("userId") or "anonymous")

    try:
        CONCURRENCY.try_acquire(user_id, payload.projectId)
    except ResourceRejection as exc:
        audit_event("analytics.query.rejected", "project", payload.projectId, "denied", user_id=user_id, reason=exc.reason)
        raise HTTPException(status_code=429, detail=exc.reason) from exc

    try:
        if is_heavy(payload):
            JOBS.create(payload.queryId, user_id, payload.projectId)
            thread = threading.Thread(target=lambda: _run_and_release(user, payload, user_id), daemon=True)
            thread.start()
            return AnalyticalQueryResponse(queryId=payload.queryId, status=QueryStatus.QUEUED, projectId=payload.projectId)

        response = execute_query(user, payload)
        return response
    except PlanningRejection as exc:
        raise HTTPException(status_code=422, detail=exc.reason) from exc
    except ResourceRejection as exc:
        raise HTTPException(status_code=429, detail=exc.reason) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Analytical query failed: {exc}") from exc
    finally:
        if not is_heavy(payload):
            CONCURRENCY.release(user_id, payload.projectId)


def _run_and_release(user: Dict[str, Any], payload: AnalyticalQueryRequest, user_id: str) -> None:
    try:
        run_async(user, payload)
    finally:
        CONCURRENCY.release(user_id, payload.projectId)


class TargetDistributionRequest(BaseModel):
    projectId: str
    datasetId: str
    versionId: str | None = None
    target: str
    eventValue: Any = None
    nonEventValue: Any = None
    # Set by the "Calculate Exact Distribution" action to override a sampled estimate.
    forceExact: bool = False


@router.post("/analytics/target-distribution")
def target_distribution(payload: TargetDistributionRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Bounded grouped count for one immutable (dataset, version, target).

    Deliberately separate from `/api/data/quality-profile`: the chart must not
    wait on full-column profiling, predictor profiling, missingness analysis, or
    browser preview preparation to render class counts.
    """
    _check_project_access(user, payload.projectId)
    return compute_target_distribution(
        user_scope=str(user.get("userId") or "anonymous"),
        project_id=payload.projectId,
        dataset_id=payload.datasetId,
        version_id=payload.versionId,
        target=payload.target,
        event_value=payload.eventValue,
        non_event_value=payload.nonEventValue,
        force_exact=payload.forceExact,
    )


@router.get("/analytics/queries/{query_id}")
def get_query_status(query_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    job = JOBS.get(query_id)
    if not job or job.get("userId") != str(user.get("userId")):
        raise HTTPException(status_code=404, detail="Query not found.")
    return {"queryId": query_id, "status": job.get("status"), "error": job.get("error")}


@router.post("/analytics/queries/{query_id}/cancel")
def cancel_query(query_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    ok = JOBS.cancel(query_id, str(user.get("userId")))
    if not ok:
        raise HTTPException(status_code=404, detail="Query not found or not owned by the current user.")
    return {"ok": True, "queryId": query_id, "status": "cancelled"}


@router.get("/analytics/queries/{query_id}/result")
def get_query_result(query_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    job = JOBS.get(query_id)
    if not job or job.get("userId") != str(user.get("userId")):
        raise HTTPException(status_code=404, detail="Query not found.")
    if job.get("status") != QueryStatus.COMPLETED:
        return {"queryId": query_id, "status": job.get("status"), "error": job.get("error")}
    return job.get("response") or {"queryId": query_id, "status": job.get("status")}


@router.post("/analytics/datasets/{dataset_id}/versions/{version_id}/materialize-parquet")
def materialize_parquet(dataset_id: str, version_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Explicit, on-demand Parquet materialization for one Dataset Library version
    (Phase F). Never automatic -- a caller (UI action or governed job) must invoke
    this explicitly; registering/uploading a dataset does not trigger it."""
    try:
        result = materialize_parquet_for_version(dataset_id, version_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_event("analytics.dataset.parquet_materialized", "dataset", dataset_id, "success", user_id=str(user.get("userId")), metadata=result)
    return {"ok": True, **result}


@router.get("/analytics/diagnostics/planner")
def planner_diagnostics(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Development query-inspection endpoint (Phase M) -- surfaces the decision
    matrix, current resource limits, configured distributed engines, and live
    concurrency counters. Consistent with the existing /api/system/diagnostics
    pattern already used elsewhere in ATLAS."""
    return {
        "ok": True,
        "decisionMatrix": decision_matrix_summary(),
        "resourceLimits": {
            "maxResultRows": LIMITS.max_result_rows, "maxResultBytes": LIMITS.max_result_bytes,
            "maxSelectedColumns": LIMITS.max_selected_columns, "maxHistogramBins": LIMITS.max_histogram_bins,
            "maxGroupCardinality": LIMITS.max_group_cardinality, "maxScatterPoints": LIMITS.max_scatter_points,
            "maxConcurrentPerUser": LIMITS.max_concurrent_queries_per_user, "maxConcurrentPerProject": LIMITS.max_concurrent_queries_per_project,
            "maxQueryDurationSeconds": LIMITS.max_query_duration_seconds, "pandasFallbackMaxRows": LIMITS.pandas_fallback_max_rows,
        },
        "configuredDistributedEngines": list_configured_engines(),
        "concurrency": CONCURRENCY.snapshot(),
        "cache": result_cache.RESULT_CACHE.stats(),
    }

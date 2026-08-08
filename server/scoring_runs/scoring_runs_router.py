"""ATLAS Persistent Scoring Runs -- HTTP routes (Phase E: Scoring History API).

Mounted at /api/scoring-runs (distinct path family from the pre-existing
/api/scoring/register-scored-dataset in server/scoring/scoring_router.py,
which registers an already-scored dataset into the Dataset Library and is
untouched by this phase)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from ..security.security_store import require_user
from . import scoring_run_service as SCORING_RUNS

router = APIRouter(dependencies=[Depends(require_user)])


@router.get("/scoring-runs")
def list_scoring_runs(
    project_id: str = Query(..., alias="projectId"),
    dataset_id: Optional[str] = Query(None, alias="datasetId"),
    dataset_version_id: Optional[str] = Query(None, alias="datasetVersionId"),
    model_id: Optional[str] = Query(None, alias="modelId"),
    model_version_id: Optional[str] = Query(None, alias="modelVersionId"),
    target: Optional[str] = Query(None),
    partition: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    problem_type: Optional[str] = Query(None, alias="problemType"),
    created_after: Optional[str] = Query(None, alias="createdAfter"),
    created_before: Optional[str] = Query(None, alias="createdBefore"),
    include_archived: bool = Query(False, alias="includeArchived"),
    limit: int = Query(200),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    runs = SCORING_RUNS.list_scoring_runs(
        user, project_id,
        dataset_id=dataset_id, dataset_version_id=dataset_version_id,
        model_id=model_id, model_version_id=model_version_id, target=target,
        partition=partition, status=status,
        problem_type=problem_type, created_after=created_after, created_before=created_before,
        include_archived=include_archived, limit=limit,
    )
    return {"ok": True, "scoringRuns": runs, "count": len(runs)}


@router.get("/scoring-runs/compare")
def compare_scoring_runs(
    ids: str = Query(..., description="Comma-separated scoringRunIds"),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    scoring_run_ids: List[str] = [value.strip() for value in ids.split(",") if value.strip()]
    return {"ok": True, **SCORING_RUNS.compare_scoring_runs(user, scoring_run_ids)}


@router.get("/scoring-runs/{scoring_run_id}")
def get_scoring_run(scoring_run_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "scoringRun": SCORING_RUNS.get_scoring_run(user, scoring_run_id)}


@router.get("/scoring-runs/{scoring_run_id}/metrics")
def get_scoring_run_metrics(scoring_run_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **SCORING_RUNS.get_scoring_run_metrics(user, scoring_run_id)}


@router.get("/scoring-runs/{scoring_run_id}/diagnostics")
def get_scoring_run_diagnostics(scoring_run_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **SCORING_RUNS.get_scoring_run_diagnostics(user, scoring_run_id)}


@router.get("/scoring-runs/{scoring_run_id}/summary")
def get_scoring_run_summary(scoring_run_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "scoringRun": SCORING_RUNS.get_scoring_run_summary(user, scoring_run_id)}


@router.get("/scoring-runs/{scoring_run_id}/lineage")
def get_scoring_run_lineage(scoring_run_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **SCORING_RUNS.get_scoring_run_lineage(user, scoring_run_id)}


@router.get("/scoring-runs/{scoring_run_id}/rows")
def get_scoring_run_rows(
    scoring_run_id: str,
    limit: int = Query(100),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    return {"ok": True, **SCORING_RUNS.get_scoring_run_rows(user, scoring_run_id, limit=limit)}


@router.post("/scoring-runs/{scoring_run_id}/cancel")
def cancel_scoring_run(scoring_run_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "scoringRun": SCORING_RUNS.cancel_scoring_run(user, scoring_run_id)}


@router.post("/scoring-runs/{scoring_run_id}/archive")
def archive_scoring_run(scoring_run_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, "scoringRun": SCORING_RUNS.archive_scoring_run(user, scoring_run_id)}

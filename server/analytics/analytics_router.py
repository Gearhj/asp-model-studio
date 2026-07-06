from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field

from ..security.security_store import audit_event, require_user
from .analytics_store import create_insight, delete_insight, diagnostics, get_insight, list_insights


router = APIRouter(dependencies=[Depends(require_user)])


class InsightRequest(BaseModel):
    title: str
    summary: str = ""
    datasetId: str
    versionId: str = ""
    projectId: Optional[str] = None
    businessQuestion: str = ""
    analysisType: str = "dataset_overview"
    evidence: Dict[str, Any] = Field(default_factory=dict)


@router.get("/analytics/insights")
def get_insights(datasetId: Optional[str] = None, projectId: Optional[str] = None) -> Dict[str, Any]:
    return {"ok": True, "insights": list_insights(dataset_id=datasetId, project_id=projectId)}


@router.post("/analytics/insights")
def post_insight(payload: InsightRequest) -> Dict[str, Any]:
    return {"ok": True, "insight": create_insight(payload.model_dump())}


@router.get("/analytics/insights/{insight_id}")
def get_one_insight(insight_id: str) -> Dict[str, Any]:
    return {"ok": True, "insight": get_insight(insight_id)}


@router.delete("/analytics/insights/{insight_id}")
def delete_one_insight(insight_id: str) -> Dict[str, Any]:
    return delete_insight(insight_id)


@router.post("/analytics/audit-run")
def post_analysis_run(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    audit_event(
        "analytics.analysis.run",
        "dataset",
        str(payload.get("datasetId") or ""),
        "success",
        metadata={"analysisType": payload.get("analysisType"), "versionId": payload.get("versionId")},
    )
    return {"ok": True}


@router.get("/analytics/diagnostics")
def get_analytics_diagnostics() -> Dict[str, Any]:
    return diagnostics()

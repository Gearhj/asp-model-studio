from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .ab_service import analyze_registered_ab_dataset


class AbMapping(BaseModel):
    unitIdColumn: str
    treatmentColumn: str
    treatmentValue: str
    controlValue: str
    outcomeColumn: str
    successEvent: str = "True"
    exposureColumn: str = ""
    segmentColumns: list[str] = Field(default_factory=list)


class AbAnalysisRequest(BaseModel):
    datasetId: str
    versionId: str | None = None
    mapping: AbMapping


router = APIRouter()


@router.post("/experimentation/ab/analyze")
def post_ab_analysis(payload: AbAnalysisRequest) -> dict[str, Any]:
    return {"ok": True, "analysis": analyze_registered_ab_dataset(payload.dict())}

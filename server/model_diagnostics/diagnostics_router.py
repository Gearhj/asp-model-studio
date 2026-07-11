from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .diagnostics_store import (
    compute_model_diagnostics,
    diagnostics_system_status,
    export_diagnostics_excel,
    export_diagnostics_powerpoint,
    export_diagnostics_word,
    save_diagnostic_insight,
)

import io
import re


router = APIRouter()


class DiagnosticInsightRequest(BaseModel):
    title: str = "Model Diagnostics Review"
    summary: str = ""
    datasetId: str
    versionId: str
    projectId: Optional[str] = None
    businessQuestion: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)


@router.get("/model-diagnostics/run")
def run_model_diagnostics(
    datasetId: str,
    versionId: Optional[str] = None,
    target: Optional[str] = None,
    actual: Optional[str] = None,
    score: Optional[str] = None,
    prediction: Optional[str] = None,
    residual: Optional[str] = None,
    segment: Optional[str] = None,
    positiveClass: Optional[str] = None,
) -> Dict[str, Any]:
    return compute_model_diagnostics(
        datasetId,
        versionId,
        {
            "target": target,
            "actual": actual,
            "score": score,
            "prediction": prediction,
            "residual": residual,
            "segment": segment,
            "positiveClass": positiveClass,
        },
    )


@router.post("/model-diagnostics/insights")
def post_diagnostic_insight(payload: DiagnosticInsightRequest) -> Dict[str, Any]:
    return {"ok": True, "insight": save_diagnostic_insight(payload.model_dump())}


@router.get("/model-diagnostics/system/diagnostics")
def get_diagnostics_status() -> Dict[str, Any]:
    return diagnostics_system_status()


@router.get("/model-diagnostics/export/{export_format}")
def export_model_diagnostics(
    export_format: str,
    datasetId: str,
    versionId: Optional[str] = None,
    target: Optional[str] = None,
    actual: Optional[str] = None,
    score: Optional[str] = None,
    prediction: Optional[str] = None,
    residual: Optional[str] = None,
    segment: Optional[str] = None,
    positiveClass: Optional[str] = None,
) -> StreamingResponse:
    diagnostics = compute_model_diagnostics(
        datasetId,
        versionId,
        {
            "target": target,
            "actual": actual,
            "score": score,
            "prediction": prediction,
            "residual": residual,
            "segment": segment,
            "positiveClass": positiveClass,
        },
    )
    label = safe_filename(diagnostics.get("dataset", {}).get("name") or "atlas-model-diagnostics")
    if export_format == "excel":
        content = export_diagnostics_excel(diagnostics)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"{label}-model-diagnostics.xlsx"
    elif export_format == "word":
        content = export_diagnostics_word(diagnostics)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        filename = f"{label}-model-diagnostics.docx"
    elif export_format == "powerpoint":
        content = export_diagnostics_powerpoint(diagnostics)
        media = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        filename = f"{label}-model-diagnostics.pptx"
    else:
        raise HTTPException(status_code=400, detail="Unsupported diagnostics export format.")
    return StreamingResponse(io.BytesIO(content), media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return safe[:80] or "atlas-model-diagnostics"

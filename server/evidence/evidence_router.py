from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from .evidence_store import auto_capture, coverage, delete_evidence, export_excel, get_evidence, graph, list_evidence, upsert_evidence

router = APIRouter()


@router.get("/evidence")
def evidence_index(
    projectId: Optional[str] = None,
    datasetId: Optional[str] = None,
    evidenceType: Optional[str] = None,
    sourcePage: Optional[str] = None,
    status: Optional[str] = None,
    importance: Optional[str] = None,
    tag: Optional[str] = None,
    financialDomain: Optional[str] = None,
    financialTechnique: Optional[str] = None,
    productType: Optional[str] = None,
    modelPurpose: Optional[str] = None,
    regulatoryRelevance: Optional[str] = None,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    items = list_evidence(
        {
            "projectId": projectId,
            "datasetId": datasetId,
            "evidenceType": evidenceType,
            "sourcePage": sourcePage,
            "status": status,
            "importance": importance,
            "tag": tag,
            "financialDomain": financialDomain,
            "financialTechnique": financialTechnique,
            "productType": productType,
            "modelPurpose": modelPurpose,
            "regulatoryRelevance": regulatoryRelevance,
            "search": search,
        }
    )
    return {"ok": True, "items": items, "count": len(items)}


@router.post("/evidence")
def create_evidence(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "evidence": upsert_evidence(payload)}


@router.get("/evidence/graph")
def evidence_graph(projectId: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    return {"ok": True, "graph": graph(projectId)}


@router.get("/evidence/coverage/{project_id}")
def evidence_coverage(project_id: str) -> Dict[str, Any]:
    return {"ok": True, "coverage": coverage(project_id)}


@router.get("/evidence/project/{project_id}")
def project_evidence(project_id: str) -> Dict[str, Any]:
    items = list_evidence({"projectId": project_id})
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/evidence/dataset/{dataset_id}")
def dataset_evidence(dataset_id: str) -> Dict[str, Any]:
    items = list_evidence({"datasetId": dataset_id})
    return {"ok": True, "items": items, "count": len(items)}


@router.post("/evidence/auto-capture")
def auto_capture_evidence(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = payload or {}
    items = auto_capture(payload.get("projectId"), payload.get("projectName"))
    return {"ok": True, "items": items, "count": len(items)}


@router.post("/evidence/export/excel")
def export_evidence_excel(payload: Dict[str, Any] | None = None) -> StreamingResponse:
    payload = payload or {}
    data = export_excel(payload.get("projectId"))
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="atlas-evidence-pack.xlsx"'},
    )


@router.get("/evidence/{evidence_id}")
def read_evidence(evidence_id: str) -> Dict[str, Any]:
    item = get_evidence(evidence_id)
    if not item:
        raise HTTPException(status_code=404, detail="Evidence item not found.")
    return {"ok": True, "evidence": item}


@router.put("/evidence/{evidence_id}")
def update_evidence(evidence_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not get_evidence(evidence_id):
        raise HTTPException(status_code=404, detail="Evidence item not found.")
    return {"ok": True, "evidence": upsert_evidence({**payload, "evidenceId": evidence_id})}


@router.delete("/evidence/{evidence_id}")
def remove_evidence(evidence_id: str) -> Dict[str, Any]:
    return {"ok": True, "deleted": delete_evidence(evidence_id)}

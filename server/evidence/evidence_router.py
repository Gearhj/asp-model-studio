from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..core.modeling_scope import authorize_modeling_scope
from ..security.security_store import require_user
from .evidence_identity import (
    assert_evidence_lineage_immutable,
    authorize_and_normalize_evidence,
    has_complete_canonical_dataset_lineage,
    is_dataset_catalog_evidence,
)
from .evidence_store import auto_capture, coverage, delete_evidence, export_excel, get_evidence, graph, list_evidence, upsert_evidence

router = APIRouter()


def _dataset_version_filter(
    dataset_version_id: Optional[str],
    datasetVersionId: Optional[str],
) -> Optional[str]:
    """Resolve canonical and compatibility query aliases without guessing."""
    canonical = str(dataset_version_id or "").strip()
    compatibility = str(datasetVersionId or "").strip()
    if canonical and compatibility and canonical != compatibility:
        raise HTTPException(
            status_code=409,
            detail=(
                "dataset_version_id contradicts datasetVersionId. Reload the "
                "exact Dataset Library version before reading evidence."
            ),
        )
    return canonical or compatibility or None


def _owning_project_id(item: Dict[str, Any]) -> Optional[str]:
    """Return one unambiguous owning project, or quarantine the item.

    ``project_id`` is authoritative for canonical evidence and ``projectId``
    remains the compatibility field for older, non-modeling evidence. Records
    with no owner, or contradictory owner aliases, must not be exposed by any
    collection or item endpoint.
    """
    canonical = str(item.get("project_id") or "").strip()
    compatibility = str(item.get("projectId") or "").strip()
    if canonical and compatibility and canonical != compatibility:
        return None
    if (
        is_dataset_catalog_evidence(item)
        and not has_complete_canonical_dataset_lineage(item)
    ):
        return None
    return canonical or compatibility or None


def _safe_authorize_item(
    item: Optional[Dict[str, Any]],
    user: Dict[str, Any],
    permission: str,
) -> str:
    """Authorize an evidence item without disclosing whether it exists."""
    if not item:
        raise HTTPException(status_code=404, detail="Evidence item not found.")
    project_id = _owning_project_id(item)
    if not project_id:
        raise HTTPException(status_code=404, detail="Evidence item not found.")
    try:
        authorize_modeling_scope(user, project_id, permission)
    except HTTPException as exc:
        raise HTTPException(
            status_code=404,
            detail="Evidence item not found.",
        ) from exc
    return project_id


def _visible_items(
    items: Iterable[Dict[str, Any]],
    user: Dict[str, Any],
    *,
    authorized_project_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter a collection to unambiguous projects the caller can view."""
    visible: List[Dict[str, Any]] = []
    for item in items:
        project_id = _owning_project_id(item)
        if not project_id:
            continue
        if authorized_project_id:
            if project_id == authorized_project_id:
                visible.append(item)
            continue
        try:
            authorize_modeling_scope(user, project_id, "view")
        except HTTPException:
            continue
        visible.append(item)
    return visible


@router.get("/evidence")
def evidence_index(
    projectId: Optional[str] = None,
    datasetId: Optional[str] = None,
    dataset_version_id: Optional[str] = None,
    datasetVersionId: Optional[str] = None,
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
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    resolved_dataset_version_id = _dataset_version_filter(
        dataset_version_id,
        datasetVersionId,
    )
    authorized_project_id: Optional[str] = None
    if projectId:
        authorized_project_id = authorize_modeling_scope(
            user,
            projectId,
            "view",
        )
    items = list_evidence(
        {
            "projectId": projectId,
            "datasetId": datasetId,
            "dataset_version_id": resolved_dataset_version_id,
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
    items = _visible_items(
        items,
        user,
        authorized_project_id=authorized_project_id,
    )
    return {"ok": True, "items": items, "count": len(items)}


@router.post("/evidence")
def create_evidence(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    normalized = authorize_and_normalize_evidence(payload, user)
    proposed_id = normalized.get("evidenceId")
    existing = get_evidence(str(proposed_id)) if proposed_id else None
    if existing:
        _safe_authorize_item(existing, user, "edit")
    if existing and existing.get("projectId") != normalized.get("projectId"):
        raise HTTPException(
            status_code=404,
            detail="ATLAS evidence record was not found under this project.",
        )
    if existing:
        normalized = authorize_and_normalize_evidence(
            {**existing, **payload},
            user,
        )
        assert_evidence_lineage_immutable(existing, normalized)
    return {"ok": True, "evidence": upsert_evidence(normalized)}


@router.get("/evidence/graph")
def evidence_graph(
    projectId: Optional[str] = Query(default=None),
    dataset_version_id: Optional[str] = Query(default=None),
    datasetVersionId: Optional[str] = Query(default=None),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    resolved_dataset_version_id = _dataset_version_filter(
        dataset_version_id,
        datasetVersionId,
    )
    authorized_project_id: Optional[str] = None
    if projectId:
        authorized_project_id = authorize_modeling_scope(
            user,
            projectId,
            "view",
        )
    items = _visible_items(
        list_evidence(
            {
                "projectId": projectId,
                "dataset_version_id": resolved_dataset_version_id,
            }
        ),
        user,
        authorized_project_id=authorized_project_id,
    )
    return {
        "ok": True,
        "graph": graph(projectId, evidence_rows=items),
    }


@router.get("/evidence/coverage/{project_id}")
def evidence_coverage(
    project_id: str,
    dataset_version_id: Optional[str] = Query(default=None),
    datasetVersionId: Optional[str] = Query(default=None),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    resolved_dataset_version_id = _dataset_version_filter(
        dataset_version_id,
        datasetVersionId,
    )
    authorized_project_id = authorize_modeling_scope(
        user,
        project_id,
        "view",
    )
    items = _visible_items(
        list_evidence(
            {
                "projectId": project_id,
                "dataset_version_id": resolved_dataset_version_id,
            }
        ),
        user,
        authorized_project_id=authorized_project_id,
    )
    return {
        "ok": True,
        "coverage": coverage(project_id, evidence_rows=items),
    }


@router.get("/evidence/project/{project_id}")
def project_evidence(
    project_id: str,
    dataset_version_id: Optional[str] = Query(default=None),
    datasetVersionId: Optional[str] = Query(default=None),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    resolved_dataset_version_id = _dataset_version_filter(
        dataset_version_id,
        datasetVersionId,
    )
    authorized_project_id = authorize_modeling_scope(
        user,
        project_id,
        "view",
    )
    items = _visible_items(
        list_evidence(
            {
                "projectId": project_id,
                "dataset_version_id": resolved_dataset_version_id,
            }
        ),
        user,
        authorized_project_id=authorized_project_id,
    )
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/evidence/dataset/{dataset_id}")
def dataset_evidence(
    dataset_id: str,
    dataset_version_id: Optional[str] = Query(default=None),
    datasetVersionId: Optional[str] = Query(default=None),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    resolved_dataset_version_id = _dataset_version_filter(
        dataset_version_id,
        datasetVersionId,
    )
    items = _visible_items(
        list_evidence(
            {
                "datasetId": dataset_id,
                "dataset_version_id": resolved_dataset_version_id,
            }
        ),
        user,
    )
    return {"ok": True, "items": items, "count": len(items)}


@router.post("/evidence/auto-capture")
def auto_capture_evidence(
    payload: Dict[str, Any] | None = None,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    payload = payload or {}
    project_id = authorize_modeling_scope(
        user,
        payload.get("projectId"),
        "edit",
    )
    items = auto_capture(project_id, payload.get("projectName"))
    return {"ok": True, "items": items, "count": len(items)}


@router.post("/evidence/export/excel")
def export_evidence_excel(
    payload: Dict[str, Any] | None = None,
    user: Dict[str, Any] = Depends(require_user),
) -> StreamingResponse:
    payload = payload or {}
    project_id = str(payload.get("projectId") or "").strip() or None
    dataset_version_id = _dataset_version_filter(
        payload.get("dataset_version_id"),
        payload.get("datasetVersionId"),
    )
    authorized_project_id: Optional[str] = None
    if project_id:
        authorized_project_id = authorize_modeling_scope(
            user,
            project_id,
            "view",
        )
    items = _visible_items(
        list_evidence(
            {
                "projectId": project_id,
                "dataset_version_id": dataset_version_id,
            }
        ),
        user,
        authorized_project_id=authorized_project_id,
    )
    data = export_excel(project_id, evidence_rows=items)
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="atlas-evidence-pack.xlsx"'},
    )


@router.get("/evidence/{evidence_id}")
def read_evidence(
    evidence_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    item = get_evidence(evidence_id)
    _safe_authorize_item(item, user, "view")
    return {"ok": True, "evidence": item}


@router.put("/evidence/{evidence_id}")
def update_evidence(
    evidence_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    existing = get_evidence(evidence_id)
    _safe_authorize_item(existing, user, "edit")
    assert existing is not None
    merged = {**existing, **payload, "evidenceId": evidence_id}
    normalized = authorize_and_normalize_evidence(merged, user)
    assert_evidence_lineage_immutable(existing, normalized)
    if existing.get("projectId") != normalized.get("projectId"):
        raise HTTPException(
            status_code=404,
            detail="ATLAS evidence record was not found under this project.",
        )
    return {"ok": True, "evidence": upsert_evidence(normalized)}


@router.delete("/evidence/{evidence_id}")
def remove_evidence(
    evidence_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    item = get_evidence(evidence_id)
    _safe_authorize_item(item, user, "edit")
    return {"ok": True, "deleted": delete_evidence(evidence_id)}

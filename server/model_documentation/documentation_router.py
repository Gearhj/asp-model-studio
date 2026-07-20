from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..security.security_store import audit_event, require_user
from .documentation_store import (
    attach_evidence,
    build_project_context,
    create_document,
    evidence_library,
    export_evidence_excel,
    export_powerpoint,
    export_word,
    list_documents,
    list_templates,
    load_document,
    quality_check,
    safe_filename,
    save_document,
    save_section,
)


router = APIRouter(dependencies=[Depends(require_user)])


class CreateDocumentationRequest(BaseModel):
    projectId: str
    templateType: str = "model_development_document"
    createdBy: str = "ATLAS local user"


class SaveSectionRequest(BaseModel):
    sectionId: str
    userNarrative: str = ""
    status: str = "draft"
    attachedEvidence: list[Dict[str, Any]] = Field(default_factory=list)
    includeInExport: bool = True
    notApplicableRationale: str = ""


class AttachEvidenceRequest(BaseModel):
    sectionId: str
    evidence: Dict[str, Any]


@router.get("/model-documentation/templates")
def get_templates() -> Dict[str, Any]:
    return {"ok": True, "templates": list_templates()}


@router.get("/model-documentation/project-context/{project_id}")
def get_project_context(project_id: str) -> Dict[str, Any]:
    return {"ok": True, "context": build_project_context(project_id), "documents": list_documents(project_id)}


@router.post("/model-documentation/create")
def post_create_document(payload: CreateDocumentationRequest) -> Dict[str, Any]:
    document = create_document(payload.projectId, payload.templateType, payload.createdBy)
    audit_event(
        "model_documentation.document.created",
        "project",
        payload.projectId,
        "success",
        metadata={"documentId": document.get("documentId"), "templateType": payload.templateType},
    )
    return {"ok": True, "document": document}


@router.get("/model-documentation/{document_id}")
def get_document(document_id: str) -> Dict[str, Any]:
    try:
        return {"ok": True, "document": load_document(document_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model documentation record not found.") from exc


@router.post("/model-documentation/{document_id}/save-section")
def post_save_section(document_id: str, payload: SaveSectionRequest) -> Dict[str, Any]:
    try:
        document = save_section(document_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model documentation record not found.") from exc
    audit_event(
        "model_documentation.section.saved",
        "document",
        document_id,
        "success",
        metadata={"sectionId": payload.sectionId, "status": payload.status},
    )
    return {"ok": True, "document": document}


@router.post("/model-documentation/{document_id}/generate-version-control-summary")
def generate_version_control_summary(document_id: str) -> Dict[str, Any]:
    document = load_document(document_id)
    changes = document.get("sectionChangeRecords") or []
    sections = [{"sectionId": item.get("section_id"), "sectionNumber": item.get("section_number"), "sectionTitle": item.get("section_title")} for item in changes]
    document.setdefault("versionControlEntries", []).append({"version": document.get("documentVersion", "0.1"), "summary": f"Draft summary generated from {len(sections)} section-level change record(s).", "sections": sections, "status": "working_draft", "createdAt": document.get("updatedAt")})
    return {"ok": True, "document": save_document(document), "undisclosedChanges": []}


@router.post("/model-documentation/{document_id}/request-management-approval")
def request_management_approval(document_id: str) -> Dict[str, Any]:
    document = load_document(document_id)
    changed = {item.get("section_id") for item in document.get("sectionChangeRecords") or []}
    disclosed = {item.get("sectionId") for entry in document.get("versionControlEntries") or [] for item in entry.get("sections") or []}
    missing = sorted(changed - disclosed)
    if missing:
        raise HTTPException(status_code=422, detail="Document changes exist that are not included in the version-control summary.")
    document["documentStatus"] = "management_review"
    return {"ok": True, "document": save_document(document)}


@router.post("/model-documentation/{document_id}/attach-evidence")
def post_attach_evidence(document_id: str, payload: AttachEvidenceRequest) -> Dict[str, Any]:
    try:
        document = attach_evidence(document_id, payload.sectionId, payload.evidence)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model documentation record not found.") from exc
    audit_event(
        "model_documentation.evidence.attached",
        "document",
        document_id,
        "success",
        metadata={"sectionId": payload.sectionId, "source": payload.evidence.get("source"), "type": payload.evidence.get("type")},
    )
    return {"ok": True, "document": document}


@router.post("/model-documentation/{document_id}/quality-check")
def post_quality_check(document_id: str) -> Dict[str, Any]:
    try:
        document = load_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model documentation record not found.") from exc
    document["quality"] = quality_check(document, document.get("contextSummary"))
    return {"ok": True, "document": save_document(document), "quality": document["quality"]}


@router.get("/model-documentation/{document_id}/evidence-library")
def get_evidence_library(document_id: str, projectId: Optional[str] = None) -> Dict[str, Any]:
    try:
        document = load_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model documentation record not found.") from exc
    return {"ok": True, "items": evidence_library(projectId or str(document.get("projectId") or ""))}


@router.post("/model-documentation/{document_id}/export/word")
def export_document_word(document_id: str) -> StreamingResponse:
    return stream_document_export(document_id, "word", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", export_word)


@router.post("/model-documentation/{document_id}/export/powerpoint")
def export_document_powerpoint(document_id: str) -> StreamingResponse:
    return stream_document_export(document_id, "powerpoint", "pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", export_powerpoint)


@router.post("/model-documentation/{document_id}/export/evidence-excel")
def export_document_evidence_excel(document_id: str) -> StreamingResponse:
    return stream_document_export(document_id, "evidence_excel", "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", export_evidence_excel)


def stream_document_export(document_id: str, label: str, extension: str, media_type: str, builder) -> StreamingResponse:
    try:
        document = load_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model documentation record not found.") from exc
    try:
        content = builder(document)
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"{label} export requires the corresponding Office export dependency.") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ATLAS could not create the {label} export: {exc}") from exc
    document.setdefault("exports", []).append({"format": label, "createdAt": document.get("updatedAt"), "filename": safe_filename(document.get("projectName") or "atlas-model-document", extension)})
    save_document(document)
    audit_event(
        "model_documentation.export.created",
        "document",
        document_id,
        "success",
        metadata={"format": label, "projectId": document.get("projectId")},
    )
    filename = safe_filename(document.get("projectName") or "atlas-model-document", extension)
    return StreamingResponse(
        BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

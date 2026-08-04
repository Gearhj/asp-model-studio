from __future__ import annotations

import json
import time
from io import BytesIO
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..datasets.dataset_registry import read_version_artifact, require_dataset
from ..core.modeling_scope import authorize_modeling_scope
from ..python_execution import (
    CodeRunRequest,
    PythonRunRequest,
    project_requires_development_binding,
    run_python,
    run_python_request,
    run_r,
    run_sas_compatible_endpoint,
)
from ..security.security_store import audit_event, require_user
from ..sql_studio.sql_engine import run_preview_sql
from .notebook_export import build_html, build_ipynb
from .notebook_store import add_notebook_evidence, delete_notebook, list_notebooks, load_notebook, save_notebook, update_cell_output


router = APIRouter(dependencies=[Depends(require_user)])


class NotebookPayload(BaseModel):
    notebookId: Optional[str] = None
    name: str = "Untitled ATLAS Notebook"
    description: str = ""
    projectId: str = ""
    projectName: str = ""
    primaryDatasetId: str = ""
    primaryVersionId: str = ""
    secondaryDatasetId: str = ""
    secondaryVersionId: str = ""
    target: str = ""
    eventValue: Any = None
    nonEventValue: Any = None
    targetContractId: str = ""
    analysisPartitionId: str = ""
    analysisPartitionRevision: int = 0
    createdBy: str = "ATLAS local user"
    tags: List[str] = Field(default_factory=list)
    defaultCodeLanguage: str = "python"
    cells: List[Dict[str, Any]] = Field(default_factory=list)


class RunCellRequest(BaseModel):
    cellId: str
    cellType: str
    source: str = ""
    projectId: str = ""
    primaryDatasetId: str = ""
    primaryVersionId: str = ""
    secondaryDatasetId: str = ""
    secondaryVersionId: str = ""
    target: str = ""
    eventValue: Any = None
    nonEventValue: Any = None
    targetContractId: str = ""
    analysisPartitionId: str = ""
    analysisPartitionRevision: int = 0


class AttachNotebookRequest(BaseModel):
    projectId: str = ""
    documentId: str = ""
    sectionId: str = "appendices"
    cellIds: List[str] = Field(default_factory=list)
    summary: str = ""


@router.get("/notebooks")
def get_notebooks() -> Dict[str, Any]:
    return {"ok": True, "notebooks": list_notebooks()}


@router.post("/notebooks")
def post_notebook(payload: NotebookPayload) -> Dict[str, Any]:
    notebook = save_notebook(payload.model_dump())
    audit_event("notebook.saved", "notebook", notebook.get("notebookId"), "success", metadata={"projectId": notebook.get("projectId"), "cells": len(notebook.get("cells") or [])})
    return {"ok": True, "notebook": notebook}


@router.get("/notebooks/{notebook_id}")
def get_notebook(notebook_id: str) -> Dict[str, Any]:
    try:
        return {"ok": True, "notebook": load_notebook(notebook_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Notebook artifact not found.") from exc


@router.put("/notebooks/{notebook_id}")
def put_notebook(notebook_id: str, payload: NotebookPayload) -> Dict[str, Any]:
    body = payload.model_dump()
    body["notebookId"] = notebook_id
    notebook = save_notebook(body)
    audit_event("notebook.saved", "notebook", notebook_id, "success", metadata={"projectId": notebook.get("projectId"), "cells": len(notebook.get("cells") or [])})
    return {"ok": True, "notebook": notebook}


@router.delete("/notebooks/{notebook_id}")
def delete_one_notebook(notebook_id: str) -> Dict[str, Any]:
    audit_event("notebook.deleted", "notebook", notebook_id, "success")
    return delete_notebook(notebook_id)


@router.post("/notebooks/{notebook_id}/run-cell")
def post_run_cell(
    notebook_id: str,
    payload: RunCellRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    try:
        load_notebook(notebook_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Notebook artifact not found.") from exc
    result = run_cell(payload, user=user)
    update_cell_output(notebook_id, payload.cellId, result["output"])
    audit_event("notebook.cell.run", "notebook", notebook_id, "success" if result.get("ok") else "error", metadata={"cellType": payload.cellType, "cellId": payload.cellId})
    return result


@router.post("/notebooks/{notebook_id}/run-all")
def post_run_all(
    notebook_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    notebook = load_notebook(notebook_id)
    results = []
    for cell in notebook.get("cells") or []:
        if cell.get("cellType") == "markdown":
            output = {"status": "success", "stdout": "Markdown preview rendered.", "stderr": "", "runtimeMs": 0, "returnCode": 0}
            update_cell_output(notebook_id, cell.get("cellId"), output)
            results.append({"cellId": cell.get("cellId"), "ok": True, "status": "success", "output": output, "runtimeMs": 0, "warnings": []})
            continue
        request = RunCellRequest(
            cellId=cell.get("cellId"),
            cellType=cell.get("cellType"),
            source=cell.get("source") or "",
            projectId=notebook.get("projectId") or "",
            primaryDatasetId=notebook.get("primaryDatasetId") or "",
            primaryVersionId=notebook.get("primaryVersionId") or "",
            secondaryDatasetId=notebook.get("secondaryDatasetId") or "",
            secondaryVersionId=notebook.get("secondaryVersionId") or "",
            target=notebook.get("target") or "",
            eventValue=notebook.get("eventValue"),
            nonEventValue=notebook.get("nonEventValue"),
            targetContractId=notebook.get("targetContractId") or "",
            analysisPartitionId=notebook.get("analysisPartitionId") or "",
            analysisPartitionRevision=int(notebook.get("analysisPartitionRevision") or 0),
        )
        result = run_cell(request, user=user)
        update_cell_output(notebook_id, cell.get("cellId"), result["output"])
        results.append({"cellId": cell.get("cellId"), **result})
    return {"ok": True, "results": results, "notebook": load_notebook(notebook_id)}


@router.post("/notebooks/{notebook_id}/export/ipynb")
def export_notebook_ipynb(notebook_id: str) -> StreamingResponse:
    try:
        notebook = load_notebook(notebook_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Notebook artifact not found.") from exc
    content = json.dumps(build_ipynb(notebook), indent=2).encode("utf-8")
    filename = safe_filename(notebook.get("name") or "atlas-notebook", "ipynb")
    return StreamingResponse(BytesIO(content), media_type="application/x-ipynb+json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/notebooks/{notebook_id}/export/html")
def export_notebook_html(notebook_id: str) -> HTMLResponse:
    try:
        notebook = load_notebook(notebook_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Notebook artifact not found.") from exc
    return HTMLResponse(content=build_html(notebook))


@router.post("/notebooks/{notebook_id}/attach-to-documentation")
def attach_notebook_to_documentation(notebook_id: str, payload: AttachNotebookRequest) -> Dict[str, Any]:
    notebook = load_notebook(notebook_id)
    evidence = add_notebook_evidence(notebook, payload.cellIds, payload.summary)
    if payload.documentId:
        try:
            from ..model_documentation.documentation_store import attach_evidence

            attach_evidence(payload.documentId, payload.sectionId or "appendices", evidence)
        except Exception:
            pass
    audit_event("notebook.evidence.attached", "notebook", notebook_id, "success", metadata={"projectId": payload.projectId or notebook.get("projectId"), "cells": len(payload.cellIds)})
    return {"ok": True, "evidence": evidence}


def dataset_context(payload: RunCellRequest) -> Dict[str, Any]:
    primary_rows: List[Dict[str, Any]] = []
    secondary_rows: List[Dict[str, Any]] = []
    if payload.primaryDatasetId and payload.primaryVersionId:
        require_dataset(payload.primaryDatasetId)
        primary_rows = (read_version_artifact(payload.primaryDatasetId, payload.primaryVersionId, "preview.json", {"rows": []}) or {}).get("rows") or []
    if payload.secondaryDatasetId and payload.secondaryVersionId:
        require_dataset(payload.secondaryDatasetId)
        secondary_rows = (read_version_artifact(payload.secondaryDatasetId, payload.secondaryVersionId, "preview.json", {"rows": []}) or {}).get("rows") or []
    return {
        "preview_rows": primary_rows,
        "primary_preview_rows": primary_rows,
        "secondary_preview_rows": secondary_rows,
        "previewRows": primary_rows,
        "dataset_name": payload.primaryDatasetId,
        "version_id": payload.primaryVersionId,
    }


def run_cell(payload: RunCellRequest, *, user: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    cell_type = payload.cellType
    predictive_project = False
    if payload.projectId:
        authorize_modeling_scope(user, payload.projectId, "view")
        predictive_project = project_requires_development_binding(payload.projectId)
    warnings = governance_warnings(payload, predictive_project=predictive_project)
    if predictive_project:
        context = {
            "previewRows": [],
            "datasetId": payload.primaryDatasetId,
            "versionId": payload.primaryVersionId,
            "target": payload.target,
            "eventValue": payload.eventValue,
            "nonEventValue": payload.nonEventValue,
            "targetContractId": payload.targetContractId,
            "analysisPartitionId": payload.analysisPartitionId,
            "analysisPartitionRevision": payload.analysisPartitionRevision,
        }
    else:
        context = dataset_context(payload)
    if cell_type == "markdown":
        output = {"status": "success", "stdout": "Markdown preview rendered.", "stderr": "", "runtimeMs": 0, "returnCode": 0}
    elif cell_type == "python":
        request = PythonRunRequest(
            page="Notebook Studio",
            userCode=payload.source,
            projectId=payload.projectId,
            workflowStep="notebook",
            context=context,
            captureImages=True,
        )
        output = run_python(request, user) if predictive_project else run_python_request(request)
    elif cell_type == "sql":
        if predictive_project:
            raise HTTPException(
                status_code=409,
                detail="Predictive Notebook SQL is blocked until it can use the exact development-population binding.",
            )
        refs = []
        if payload.primaryDatasetId and payload.primaryVersionId:
            refs.append({"datasetId": payload.primaryDatasetId, "versionId": payload.primaryVersionId, "alias": "REG_TRAIN"})
        if payload.secondaryDatasetId and payload.secondaryVersionId:
            refs.append({"datasetId": payload.secondaryDatasetId, "versionId": payload.secondaryVersionId, "alias": "SECONDARY"})
        sql_result = run_preview_sql(payload.source, refs, 100)
        output = {
            "ok": sql_result.get("ok"),
            "status": sql_result.get("status"),
            "stdout": f"{sql_result.get('returnedRows', 0)} row(s) returned.",
            "stderr": sql_result.get("error") or "",
            "runtimeMs": sql_result.get("runtimeMs", 0),
            "returnCode": 0 if sql_result.get("ok") else 1,
            "rows": sql_result.get("rows") or [],
            "columns": sql_result.get("columns") or [],
            "messages": sql_result.get("warnings") or [],
        }
    elif cell_type == "r":
        if predictive_project:
            raise HTTPException(
                status_code=409,
                detail="Predictive Notebook R is blocked until it can use the exact development-population binding.",
            )
        output = run_r(CodeRunRequest(code=payload.source, context=context))
    elif cell_type == "sas_compatible":
        if predictive_project:
            raise HTTPException(
                status_code=409,
                detail="Predictive Notebook SAS-compatible execution is blocked until it can use the exact development-population binding.",
            )
        output = run_sas_compatible_endpoint(CodeRunRequest(code=payload.source, context=context))
    else:
        output = {"ok": False, "status": "blocked", "stdout": "", "stderr": f"Unsupported notebook cell type: {cell_type}", "runtimeMs": 0, "returnCode": 1}
    status = str(output.get("status") or ("success" if output.get("ok") else "error"))
    response_output = {**output, "status": status, "runtimeMs": int(output.get("runtimeMs") or ((time.perf_counter() - started) * 1000))}
    return {
        "ok": bool(output.get("ok", status == "success")),
        "status": status,
        "output": response_output,
        "runtimeMs": response_output["runtimeMs"],
        "warnings": warnings + list(output.get("warnings") or output.get("messages") or []),
        "error": output.get("stderr") or output.get("error") or "",
    }


def governance_warnings(
    payload: RunCellRequest,
    *,
    predictive_project: bool = False,
) -> List[str]:
    warnings = ["Local-development-only execution."]
    warnings.append(
        "Predictive Notebook execution uses the exact sealed development population; final holdout rows are excluded."
        if predictive_project
        else "Notebook dataset context uses registered preview/sample rows."
    )
    if payload.cellType == "sql":
        warnings.append("SQL notebook cells are read-only SELECT/WITH only.")
    if payload.cellType == "sas_compatible":
        warnings.append("No SAS license required for ATLAS SAS-compatible mode.")
    return warnings


def safe_filename(name: str, extension: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in name.lower()).strip("-") or "atlas-notebook"
    return f"{safe}.{extension}"

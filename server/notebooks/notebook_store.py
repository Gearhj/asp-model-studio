from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..datasets.dataset_registry import write_json


NOTEBOOK_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "notebooks"
NOTEBOOK_INDEX_PATH = NOTEBOOK_ROOT / "notebook_index.json"
EVIDENCE_PATH = NOTEBOOK_ROOT / "notebook_evidence.json"
MAX_OUTPUT_ROWS = 100
MAX_OUTPUT_CHARS = 20000
MAX_OUTPUT_IMAGES = 5
MAX_IMAGE_BASE64_CHARS = 1500000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_store() -> None:
    NOTEBOOK_ROOT.mkdir(parents=True, exist_ok=True)
    if not NOTEBOOK_INDEX_PATH.exists():
        write_json(NOTEBOOK_INDEX_PATH, {"notebooks": []})
    if not EVIDENCE_PATH.exists():
        write_json(EVIDENCE_PATH, {"items": []})


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-") or "notebook"


def notebook_path(notebook_id: str) -> Path:
    return NOTEBOOK_ROOT / f"{safe_id(notebook_id)}.json"


def compact_text(value: Any, limit: int = MAX_OUTPUT_CHARS) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[ATLAS truncated large notebook output for compact persistence.]"


def compact_rows(rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    compacted: List[Dict[str, Any]] = []
    for row in rows[:MAX_OUTPUT_ROWS]:
        if isinstance(row, dict):
            compacted.append({str(key): value for key, value in list(row.items())[:40]})
    return compacted


def compact_images(images: Any) -> List[Dict[str, Any]]:
    if not isinstance(images, list):
        return []
    compacted: List[Dict[str, Any]] = []
    for image in images[:MAX_OUTPUT_IMAGES]:
        if not isinstance(image, dict):
            continue
        data = str(image.get("data") or "")
        if not data or len(data) > MAX_IMAGE_BASE64_CHARS:
            continue
        compacted.append(
            {
                "mimeType": str(image.get("mimeType") or "image/png"),
                "data": data,
                "alt": compact_text(image.get("alt") or "ATLAS notebook chart", 200),
            }
        )
    return compacted


def compact_output(output: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(output, dict):
        return {}
    compacted = dict(output)
    for key in ["stdout", "stderr", "error", "log", "listing", "translatedPython"]:
        if key in compacted:
            compacted[key] = compact_text(compacted.get(key))
    if "rows" in compacted:
        compacted["rows"] = compact_rows(compacted.get("rows"))
        if isinstance(output.get("rows"), list) and len(output.get("rows") or []) > MAX_OUTPUT_ROWS:
            compacted["truncated"] = True
    if "tables" in compacted and isinstance(compacted["tables"], list):
        compacted["tables"] = [
            {
                **{k: v for k, v in table.items() if k != "rows"},
                "rows": compact_rows(table.get("rows")),
            }
            for table in compacted["tables"][:8]
            if isinstance(table, dict)
        ]
    if "images" in compacted:
        compacted["images"] = compact_images(compacted.get("images"))
        if isinstance(output.get("images"), list) and len(output.get("images") or []) > MAX_OUTPUT_IMAGES:
            compacted["truncated"] = True
    if "html" in compacted:
        compacted["html"] = compact_text(compacted.get("html"), 8000)
    compacted.setdefault("warnings", [])
    return compacted


def default_cells() -> List[Dict[str, Any]]:
    timestamp = now_iso()
    return [
        {
            "cellId": f"cell_{uuid.uuid4().hex[:12]}",
            "cellType": "markdown",
            "source": "# ATLAS Notebook\n\nUse this governed notebook to document analysis, code, outputs, and review notes.",
            "output": {"status": "idle"},
            "createdAt": timestamp,
            "updatedAt": timestamp,
        },
        {
            "cellId": f"cell_{uuid.uuid4().hex[:12]}",
            "cellType": "python",
            "source": "import pandas as pd\n\n# ATLAS injects preview_rows for the selected Dataset Library asset.\ndf = pd.DataFrame(preview_rows)\nprint(df.shape)\nprint(df.head())",
            "output": {"status": "idle"},
            "createdAt": timestamp,
            "updatedAt": timestamp,
        },
    ]


def normalize_notebook(payload: Dict[str, Any], existing: Dict[str, Any] | None = None) -> Dict[str, Any]:
    timestamp = now_iso()
    existing = existing or {}
    notebook_id = str(payload.get("notebookId") or existing.get("notebookId") or f"nb_{uuid.uuid4().hex[:16]}")
    if not notebook_id.startswith("nb_"):
        notebook_id = f"nb_{safe_id(notebook_id)}"
    cells = payload.get("cells")
    if not isinstance(cells, list) or not cells:
        cells = existing.get("cells") if existing else default_cells()
    normalized_cells = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        normalized_cells.append(
            {
                "cellId": str(cell.get("cellId") or f"cell_{uuid.uuid4().hex[:12]}"),
                "cellType": str(cell.get("cellType") or "markdown"),
                "source": str(cell.get("source") or ""),
                "output": compact_output(cell.get("output") or {}),
                "createdAt": cell.get("createdAt") or timestamp,
                "updatedAt": timestamp,
                "lastRunAt": cell.get("lastRunAt") or "",
            }
        )
    datasets = []
    for dataset_id, version_id, role in [
        (payload.get("primaryDatasetId"), payload.get("primaryVersionId"), "primary"),
        (payload.get("secondaryDatasetId"), payload.get("secondaryVersionId"), "secondary"),
    ]:
        if dataset_id and version_id:
            datasets.append({"datasetId": dataset_id, "versionId": version_id, "role": role})
    return {
        "notebookId": notebook_id,
        "name": str(payload.get("name") or existing.get("name") or "Untitled ATLAS Notebook"),
        "description": str(payload.get("description") or existing.get("description") or ""),
        "projectId": str(payload.get("projectId") or existing.get("projectId") or ""),
        "projectName": str(payload.get("projectName") or existing.get("projectName") or ""),
        "primaryDatasetId": str(payload.get("primaryDatasetId") or existing.get("primaryDatasetId") or ""),
        "primaryVersionId": str(payload.get("primaryVersionId") or existing.get("primaryVersionId") or ""),
        "secondaryDatasetId": str(payload.get("secondaryDatasetId") or existing.get("secondaryDatasetId") or ""),
        "secondaryVersionId": str(payload.get("secondaryVersionId") or existing.get("secondaryVersionId") or ""),
        "target": str(payload.get("target") or existing.get("target") or ""),
        "eventValue": payload.get("eventValue") if payload.get("eventValue") is not None else existing.get("eventValue"),
        "nonEventValue": (
            payload.get("nonEventValue")
            if payload.get("nonEventValue") is not None
            else existing.get("nonEventValue")
        ),
        "targetContractId": str(payload.get("targetContractId") or existing.get("targetContractId") or ""),
        "analysisPartitionId": str(payload.get("analysisPartitionId") or existing.get("analysisPartitionId") or ""),
        "analysisPartitionRevision": int(
            payload.get("analysisPartitionRevision")
            or existing.get("analysisPartitionRevision")
            or 0
        ),
        "createdAt": existing.get("createdAt") or timestamp,
        "updatedAt": timestamp,
        "createdBy": str(payload.get("createdBy") or existing.get("createdBy") or "ATLAS local user"),
        "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else existing.get("tags", []),
        "cells": normalized_cells,
        "lineage": {"datasets": datasets, "sourcePages": ["Notebook Studio"]},
        "governance": {
            "localExecutionOnly": True,
            "previewRowsOnly": True,
            "warnings": [
                "Local development execution only.",
                "Predictive Modeling execution requires the exact sealed development-population binding; final holdout rows are excluded.",
                "Other workflow types retain their registered preview/sample-row behavior.",
                "Attach notebook outputs to documentation before final model approval.",
            ],
        },
    }


def summarize_notebook(notebook: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "notebookId": notebook.get("notebookId"),
        "name": notebook.get("name"),
        "projectId": notebook.get("projectId"),
        "projectName": notebook.get("projectName"),
        "primaryDatasetId": notebook.get("primaryDatasetId"),
        "primaryVersionId": notebook.get("primaryVersionId"),
        "createdAt": notebook.get("createdAt"),
        "updatedAt": notebook.get("updatedAt"),
        "cellCount": len(notebook.get("cells") or []),
        "lastRunStatus": last_run_status(notebook),
    }


def last_run_status(notebook: Dict[str, Any]) -> str:
    statuses = [str((cell.get("output") or {}).get("status") or "idle") for cell in notebook.get("cells") or []]
    if "error" in statuses:
        return "error"
    if "running" in statuses:
        return "running"
    if "success" in statuses:
        return "success"
    return "idle"


def list_notebooks() -> List[Dict[str, Any]]:
    ensure_store()
    return read_json(NOTEBOOK_INDEX_PATH, {"notebooks": []}).get("notebooks", [])


def load_notebook(notebook_id: str) -> Dict[str, Any]:
    ensure_store()
    notebook = read_json(notebook_path(notebook_id), {})
    if not notebook:
        raise KeyError(notebook_id)
    return notebook


def save_notebook(payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_store()
    existing = {}
    if payload.get("notebookId") and notebook_path(str(payload["notebookId"])).exists():
        existing = read_json(notebook_path(str(payload["notebookId"])), {})
    notebook = normalize_notebook(payload, existing or None)
    write_json(notebook_path(notebook["notebookId"]), notebook)
    index = read_json(NOTEBOOK_INDEX_PATH, {"notebooks": []})
    records = [item for item in index.get("notebooks", []) if item.get("notebookId") != notebook["notebookId"]]
    records.insert(0, summarize_notebook(notebook))
    write_json(NOTEBOOK_INDEX_PATH, {"notebooks": records[:250]})
    return notebook


def delete_notebook(notebook_id: str) -> Dict[str, Any]:
    ensure_store()
    path = notebook_path(notebook_id)
    if path.exists():
        path.unlink()
    index = read_json(NOTEBOOK_INDEX_PATH, {"notebooks": []})
    records = [item for item in index.get("notebooks", []) if item.get("notebookId") != notebook_id]
    write_json(NOTEBOOK_INDEX_PATH, {"notebooks": records})
    return {"ok": True, "deleted": True}


def update_cell_output(notebook_id: str, cell_id: str, output: Dict[str, Any]) -> Dict[str, Any]:
    notebook = load_notebook(notebook_id)
    timestamp = now_iso()
    for cell in notebook.get("cells") or []:
        if cell.get("cellId") == cell_id:
            cell["output"] = compact_output(output)
            cell["lastRunAt"] = timestamp
            cell["updatedAt"] = timestamp
            break
    return save_notebook(notebook)


def add_notebook_evidence(notebook: Dict[str, Any], cell_ids: List[str], summary: str = "") -> Dict[str, Any]:
    ensure_store()
    evidence = read_json(EVIDENCE_PATH, {"items": []})
    selected = [cell for cell in notebook.get("cells") or [] if not cell_ids or cell.get("cellId") in cell_ids]
    has_images = any((cell.get("output") or {}).get("images") for cell in selected)
    has_tables = any((cell.get("output") or {}).get("rows") or (cell.get("output") or {}).get("tables") for cell in selected)
    has_markdown = any(cell.get("cellType") == "markdown" for cell in selected)
    evidence_type = "notebook_chart" if has_images else "notebook_table" if has_tables else "notebook_markdown" if has_markdown else "notebook_code"
    item = {
        "type": "Notebook Output",
        "evidenceType": evidence_type,
        "title": f"Notebook Output - {notebook.get('name')}",
        "source": "Notebook Studio",
        "notebookId": notebook.get("notebookId"),
        "projectId": notebook.get("projectId"),
        "datasetId": notebook.get("primaryDatasetId"),
        "cellIds": [cell.get("cellId") for cell in selected],
        "summary": summary or f"{len(selected)} notebook cell output(s) attached from ATLAS Notebook Studio.",
        "createdAt": now_iso(),
        "preview": {
            "notebook": notebook.get("name"),
            "cells": [
                {
                    "cellType": cell.get("cellType"),
                    "source": compact_text(cell.get("source"), 1000),
                    "status": (cell.get("output") or {}).get("status"),
                    "stdout": compact_text((cell.get("output") or {}).get("stdout"), 1000),
                    "rows": compact_rows((cell.get("output") or {}).get("rows")),
                    "images": compact_images((cell.get("output") or {}).get("images")),
                }
                for cell in selected[:12]
            ],
        },
    }
    records = [entry for entry in evidence.get("items", []) if not (entry.get("notebookId") == item["notebookId"] and entry.get("cellIds") == item["cellIds"])]
    records.insert(0, item)
    write_json(EVIDENCE_PATH, {"items": records[:500]})
    return item


def list_notebook_evidence(project_id: str = "") -> List[Dict[str, Any]]:
    ensure_store()
    items = read_json(EVIDENCE_PATH, {"items": []}).get("items", [])
    if project_id:
        items = [item for item in items if str(item.get("projectId") or "") in {"", project_id}]
    return items

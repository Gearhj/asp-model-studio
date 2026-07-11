from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..datasets.dataset_registry import load_links, load_registry, write_json


PROJECT_ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "projects"
PROJECT_REGISTRY_PATH = PROJECT_ARTIFACT_ROOT / "project_registry.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_project_registry() -> None:
    PROJECT_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    if not PROJECT_REGISTRY_PATH.exists():
        write_json(PROJECT_REGISTRY_PATH, {"projects": []})


def read_project_registry() -> Dict[str, Any]:
    ensure_project_registry()
    try:
        return json.loads(PROJECT_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"projects": []}


def save_project_registry(registry: Dict[str, Any]) -> None:
    ensure_project_registry()
    write_json(PROJECT_REGISTRY_PATH, registry)


def normalize_project_type(value: str) -> str:
    text = (value or "").replace("-", "_").lower()
    if "experiment" in text:
        return "experimental_design"
    if "predict" in text or "model" in text or "regression" in text or "classification" in text:
        return "predictive_modeling"
    return "unknown"


def infer_task_from_dataset(dataset: Dict[str, Any]) -> Optional[str]:
    source = dataset.get("sourceInfo") or {}
    task = str(source.get("task") or source.get("problemType") or "").lower()
    name = str(dataset.get("name") or dataset.get("datasetId") or "").lower()
    if "regression" in task or name.startswith("reg_") or "home-prices" in name:
        return "regression"
    if "classification" in task or name.startswith("class_") or "fraud" in name:
        return "classification"
    return None


def infer_target_from_dataset(dataset: Dict[str, Any], task: Optional[str]) -> str:
    source = dataset.get("sourceInfo") or {}
    if source.get("targetColumn"):
        return str(source.get("targetColumn"))
    name = str(dataset.get("name") or "").upper()
    if task == "regression" or name.startswith("REG_"):
        return "MedHouseVal"
    if task == "classification" or name.startswith("CLASS_"):
        return "Class"
    return ""


def project_name_from_dataset(dataset: Dict[str, Any], task: Optional[str]) -> str:
    source = dataset.get("sourceInfo") or {}
    if source.get("projectName"):
        return str(source.get("projectName"))
    name = str(dataset.get("name") or dataset.get("datasetId") or "")
    cleaned = re.sub(r"\s+", " ", re.sub(r"[_-]+", " ", name)).strip()
    if "home prices regression test model" in cleaned.lower():
        return "Home Prices Regression Test Model"
    if task == "regression":
        return "Home Prices Regression Test Model"
    if task == "classification":
        return "Recovered Classification Predictive Model"
    return cleaned.title() or "Recovered ATLAS Project"


def _summarize_dataset(dataset: Dict[str, Any]) -> Dict[str, Any]:
    versions = dataset.get("versions") or []
    latest = versions[-1] if versions else {}
    return {
        "datasetId": dataset.get("datasetId"),
        "name": dataset.get("name"),
        "datasetRole": dataset.get("datasetRole") or (dataset.get("sourceInfo") or {}).get("datasetRole"),
        "sourceType": dataset.get("sourceType"),
        "rowCount": latest.get("rowCount"),
        "columnCount": latest.get("columnCount"),
        "versionId": latest.get("versionId"),
        "createdAt": dataset.get("createdAt"),
        "updatedAt": dataset.get("updatedAt"),
    }


def scan_dataset_linked_project_candidates() -> List[Dict[str, Any]]:
    datasets = load_registry().get("datasets", [])
    links = load_links().get("links", [])
    by_project: Dict[str, Dict[str, Any]] = {}
    by_id = {item.get("datasetId"): item for item in datasets}

    for link in links:
        dataset = by_id.get(link.get("datasetId"))
        if not dataset:
            continue
        project_id = str(link.get("projectId") or "")
        if not project_id:
            continue
        task = infer_task_from_dataset(dataset)
        target = infer_target_from_dataset(dataset, task)
        current = by_project.setdefault(
            project_id,
            {
                "projectId": project_id,
                "name": project_name_from_dataset(dataset, task),
                "projectType": "predictive_modeling" if task in {"regression", "classification"} else "unknown",
                "taskType": task or "unknown",
                "target": target,
                "linkedDatasets": [],
                "lastOpenedAt": "",
                "lastSavedAt": dataset.get("updatedAt") or dataset.get("createdAt") or now_iso(),
                "createdAt": dataset.get("createdAt") or now_iso(),
                "storageLocation": "recovered",
                "snapshotPath": "",
                "recoveryStatus": "Dataset-linked shell only",
            },
        )
        if task and current.get("taskType") == "unknown":
            current["taskType"] = task
            current["projectType"] = "predictive_modeling"
        if target and not current.get("target"):
            current["target"] = target
        current["linkedDatasets"].append(_summarize_dataset(dataset))
        if dataset.get("updatedAt") and str(dataset.get("updatedAt")) > str(current.get("lastSavedAt") or ""):
            current["lastSavedAt"] = dataset.get("updatedAt")

    grouped: Dict[str, Dict[str, Any]] = {}
    for prefix, task, target, name in [
        ("REG_", "regression", "MedHouseVal", "Home Prices Regression Test Model"),
        ("CLASS_", "classification", "Class", "Recovered Classification Predictive Model"),
    ]:
        matches = [item for item in datasets if str(item.get("name") or "").upper().startswith(prefix)]
        if not matches:
            continue
        project_id = "recovered-regression-shell" if task == "regression" else "recovered-classification-shell"
        grouped[project_id] = {
            "projectId": project_id,
            "name": name,
            "projectType": "predictive_modeling",
            "taskType": task,
            "target": target,
            "linkedDatasets": [_summarize_dataset(item) for item in matches],
            "lastOpenedAt": "",
            "lastSavedAt": max(str(item.get("updatedAt") or item.get("createdAt") or "") for item in matches),
            "createdAt": min(str(item.get("createdAt") or now_iso()) for item in matches),
            "storageLocation": "recovered",
            "snapshotPath": "",
            "recoveryStatus": "Dataset-linked shell only",
        }

    merged = {**grouped, **by_project}
    return sorted(merged.values(), key=lambda item: str(item.get("lastSavedAt") or ""), reverse=True)


def list_backend_projects(include_recovery_candidates: bool = True) -> List[Dict[str, Any]]:
    registry = read_project_registry()
    projects = registry.get("projects") if isinstance(registry.get("projects"), list) else []
    by_id = {str(project.get("projectId")): project for project in projects if project.get("projectId")}
    if include_recovery_candidates:
        for candidate in scan_dataset_linked_project_candidates():
            by_id.setdefault(str(candidate.get("projectId")), candidate)
    return sorted(by_id.values(), key=lambda item: str(item.get("lastSavedAt") or item.get("createdAt") or ""), reverse=True)


def upsert_project_record(record: Dict[str, Any]) -> Dict[str, Any]:
    registry = read_project_registry()
    projects = [item for item in registry.get("projects", []) if item.get("projectId") != record.get("projectId")]
    now = now_iso()
    normalized = {
        "projectId": record.get("projectId"),
        "name": record.get("name") or record.get("projectName") or "Recovered ATLAS Project",
        "projectType": normalize_project_type(str(record.get("projectType") or "unknown")),
        "taskType": record.get("taskType"),
        "target": record.get("target") or "",
        "linkedDatasets": record.get("linkedDatasets") or [],
        "lastOpenedAt": record.get("lastOpenedAt") or "",
        "lastSavedAt": record.get("lastSavedAt") or now,
        "createdAt": record.get("createdAt") or now,
        "storageLocation": record.get("storageLocation") or "recovered",
        "snapshotPath": record.get("snapshotPath") or "",
        "recoveryStatus": record.get("recoveryStatus") or "Recovered shell",
    }
    projects.insert(0, normalized)
    save_project_registry({"projects": projects})
    return normalized


from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..security.security_store import require_user
from .project_registry import (
    PROJECT_REGISTRY_PATH,
    list_backend_projects,
    scan_dataset_linked_project_candidates,
    upsert_project_record,
)


router = APIRouter(dependencies=[Depends(require_user)])


class ProjectRegistryRecord(BaseModel):
    projectId: str
    name: str
    projectType: str = "unknown"
    taskType: str | None = None
    target: str = ""
    linkedDatasets: list[Dict[str, Any]] = []
    lastOpenedAt: str = ""
    lastSavedAt: str = ""
    createdAt: str = ""
    storageLocation: str = "recovered"
    snapshotPath: str = ""
    recoveryStatus: str = "Recovered shell"


@router.get("/projects/registry")
def get_project_registry() -> Dict[str, Any]:
    return {
        "ok": True,
        "projects": list_backend_projects(include_recovery_candidates=True),
        "registryPath": str(PROJECT_REGISTRY_PATH),
    }


@router.post("/projects/registry")
def post_project_registry_record(payload: ProjectRegistryRecord) -> Dict[str, Any]:
    return {"ok": True, "project": upsert_project_record(payload.dict())}


@router.get("/projects/recovery/scan")
def get_project_recovery_scan() -> Dict[str, Any]:
    candidates = scan_dataset_linked_project_candidates()
    return {
        "ok": True,
        "candidates": candidates,
        "summary": {
            "total": len(candidates),
            "predictiveModeling": len([item for item in candidates if item.get("projectType") == "predictive_modeling"]),
            "regression": len([item for item in candidates if item.get("taskType") == "regression"]),
            "classification": len([item for item in candidates if item.get("taskType") == "classification"]),
        },
    }


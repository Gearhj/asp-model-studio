from __future__ import annotations

import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from ..persistence.db import PersistenceUnavailableError
from .registry_service import get_registry_service


router = APIRouter(prefix="/registry")


def _execute(operation):
    try:
        return operation()
    except PersistenceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=f"ATLAS registry is temporarily unavailable: {exc}") from exc


@router.get("/assets")
def list_registry_assets(
    asset_type: str | None = None,
    workflow_type: str | None = None,
    lifecycle_status: str | None = None,
    owner_user_id: str | None = None,
    evidence_status: str | None = None,
    documentation_status: str | None = None,
    validation_status: str | None = None,
    search: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    payload = _execute(lambda: get_registry_service().list_assets(
        asset_type=asset_type,
        workflow_type=workflow_type,
        lifecycle_status=lifecycle_status,
        owner_user_id=owner_user_id,
        evidence_status=evidence_status,
        documentation_status=documentation_status,
        validation_status=validation_status,
        search=search,
        limit=limit,
        offset=offset,
    ))
    return {"ok": True, "assets": payload["items"], "total": payload["total"], "limit": payload["limit"], "offset": payload["offset"]}


@router.get("/assets/{project_id}")
def get_registry_asset(project_id: str) -> Dict[str, Any]:
    detail = _execute(lambda: get_registry_service().get_asset(project_id))
    if detail is None:
        raise HTTPException(status_code=404, detail="Registry asset was not found in the ATLAS persistence database.")
    return {"ok": True, **detail}


@router.get("/summary")
def get_registry_summary() -> Dict[str, Any]:
    return {"ok": True, "summary": _execute(lambda: get_registry_service().summary())}


@router.get("/actions")
def get_registry_actions(
    severity: str | None = None,
    project_id: str | None = None,
    limit: int = Query(250, ge=1, le=500),
) -> Dict[str, Any]:
    payload = _execute(lambda: get_registry_service().list_actions(severity=severity, project_id=project_id, limit=limit))
    return {"ok": True, "actions": payload["items"], "total": payload["total"]}


@router.get("/activity")
def get_registry_activity(
    project_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    payload = _execute(lambda: get_registry_service().list_activity(project_id=project_id, limit=limit))
    return {"ok": True, "activity": payload["items"], "total": payload["total"]}


@router.get("/owners")
def get_registry_owners() -> Dict[str, Any]:
    payload = _execute(lambda: get_registry_service().owner_summaries())
    return {"ok": True, "owners": payload["items"], "total": payload["total"]}

"""Authenticated read-only discovery endpoints for the multi-sport shell."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from .contracts import SportContractError, contract_payload
from .registry import (
    WORKFLOW_MANIFESTS,
    get_workflow_manifest,
    list_workflow_manifests,
    registry_payload,
    workflow_capability,
)


router = APIRouter()


@router.get("/sports/registry")
def read_sport_registry():
    return registry_payload()


@router.get("/sports/manifests")
def read_sport_manifests(
    sportCode: Optional[str] = Query(default=None),
    leagueCode: Optional[str] = Query(default=None),
    selectableOnly: bool = Query(default=False),
):
    try:
        manifests = list_workflow_manifests(
            sport_code=sportCode,
            league_code=leagueCode,
            selectable_only=selectableOnly,
        )
    except SportContractError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_SPORT_WORKFLOW_FILTER", "message": str(exc)}) from exc
    return {
        "schemaVersion": "SPORT_WORKFLOW_MANIFEST_COLLECTION_V1",
        "manifests": [contract_payload(manifest) for manifest in manifests],
    }


@router.get("/sports/manifests/{workflow_code}")
def read_sport_manifest(workflow_code: str):
    try:
        return contract_payload(get_workflow_manifest(workflow_code))
    except SportContractError as exc:
        raise HTTPException(status_code=404, detail={"code": "SPORT_WORKFLOW_MANIFEST_NOT_FOUND", "message": str(exc)}) from exc


@router.get("/sports/capabilities")
def read_sport_capabilities():
    return {
        "schemaVersion": "SPORT_WORKFLOW_CAPABILITIES_V1",
        "capabilities": [workflow_capability(manifest) for manifest in WORKFLOW_MANIFESTS],
        "activity": {
            "databaseReads": 0,
            "databaseWrites": 0,
            "sourceReads": 0,
            "providerCalls": 0,
            "modelFits": 0,
            "modelScores": 0,
            "finalOotReads": 0,
        },
    }


__all__ = ["router"]

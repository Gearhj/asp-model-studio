"""Authenticated, read-only views of published MLB regime-study evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..security.security_store import require_user
from ..sharing.sharing_service import SharingService
from . import mlb_regime_study_registration as registration

router = APIRouter()
ROOT = registration.STUDY_ROOT
SUPPORTED_SUFFIXES = {".json", ".jsonl", ".md", ".png", ".csv", ".xlsx", ".joblib", ".parquet", ".npz"}
ARRAY_FIELDS = ("clusterProfiles", "stability", "failureRegimes", "specialistEligibility", "leaderboard", "influence", "calibration",
                "foldMetrics", "regimeMetrics", "monthlyEvaluation", "removalSensitivity")


def _permission(user: dict[str, Any], permission: str = "view"):
    if not SharingService().check_permission(user, "project", registration.PROJECT_ID, permission)["allowed"]:
        raise HTTPException(status_code=403, detail="MLB study project access is required.")


def study_catalog() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The publisher owns latest.json; viewing never creates or runs evidence."""
    base = {"schemaVersion": "MLB_REGIME_STUDY_UI_V1", "projectId": registration.PROJECT_ID,
            "status": "NOT_AVAILABLE", "artifacts": [], "warnings": []}
    allowed = {}
    pointer = ROOT / "latest.json"
    if not pointer.is_file():
        base["warnings"] = ["No completed MLB regime-study publication is available."]
        return base, allowed
    try:
        result_ref = json.loads(pointer.read_text(encoding="utf-8"))["result"]
        result = registration.read_result(result_ref)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        base["warnings"] = [f"Study publication unavailable: {exc}"]
        return base, allowed
    base.update({key: result.get(key) for key in ("studyId", "completedAtUtc", "status", "verdict", "authority", "cohort", "baselineParity", "gameSimulation", "limitations",
                                               "selectedArchitecture", "diagnosticChallenger", "selection", "coldStart", "currentShadow", "uncertaintyIntervals")})
    for field in ARRAY_FIELDS:
        base[field] = result.get(field) if isinstance(result.get(field), list) else []
    for ref in [{**result_ref, "label": "Complete study result", "category": "Study"}, *result.get("artifacts", [])]:
        try:
            # Large tabular/model artifacts are hashed incrementally, never deserialized.
            path = registration.checked_artifact(ref)
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                raise ValueError("Artifact format is not supported for download.")
            identifier = hashlib.sha256((str(path) + ref["sha256"]).encode()).hexdigest()[:32]
            if identifier in allowed:
                continue
            allowed[identifier] = dict(ref)
            base["artifacts"].append({"id": identifier, "label": ref.get("label", path.name),
                                      "category": ref.get("category", "Research evidence"),
                                      "filename": path.name, "sha256": ref["sha256"], "bytes": ref["byteCount"],
                                      "href": f"/sports/mlb/regime-study/artifacts/{identifier}"})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            base["warnings"].append(f"Artifact unavailable: {exc}")
    return base, allowed


@router.get("/sports/mlb/regime-study")
def read_study(user: dict[str, Any] = Depends(require_user)):
    _permission(user)
    catalog, _ = study_catalog()
    return catalog


@router.get("/sports/mlb/regime-study/artifacts/{artifact_id}")
def read_artifact(artifact_id: str, user: dict[str, Any] = Depends(require_user)):
    _permission(user, "export")
    _, allowed = study_catalog()
    if artifact_id not in allowed:
        raise HTTPException(status_code=404, detail="Artifact is not in the completed MLB study publication.")
    ref = allowed[artifact_id]
    try:
        path = registration.checked_artifact(ref)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name,
                        content_disposition_type="inline" if path.suffix in {".json", ".md", ".png"} else "attachment",
                        headers={"X-Artifact-SHA256": ref["sha256"], "Cache-Control": "private, no-store"})

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, Depends, HTTPException

from ..persistence import get_database
from ..security.security_store import require_role, require_user
from ..sports_datasets.access import approved_package_root
from ..sports_datasets.consumer import ManifestValidationError, SportsDatasetManifestConsumer, raw_absolute_path
from .consumer import IdentityBridgeValidationError, SportsIdentityBridgeV1Consumer, approved_bridge_root
from .mlb_adapter import MLBFD1IdentityAdapter
from .registry import IdentityBridgeRegistrationError, SportsIdentityBridgeRegistry


LOGGER = logging.getLogger("asp.sports_identity_bridges")
router = APIRouter()
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"


def _exchange_root() -> Path:
    configured = os.getenv("ASP_MODEL_EXCHANGE_ROOT", "").strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "EXCHANGE_ROOT_NOT_CONFIGURED",
                "message": "The administrator-controlled exchange root is not configured.",
            },
        )
    return raw_absolute_path(Path(configured))


def _runtime_root() -> Path:
    configured = os.getenv("ASP_MODEL_STUDIO_SPORTS_MODELING_ROOT", "").strip()
    return Path(configured).expanduser().resolve(strict=False) if configured else DEFAULT_RUNTIME_ROOT.resolve(strict=False)


def _code_revision() -> str:
    configured = os.getenv("ASP_MODEL_STUDIO_CODE_REVISION", "").strip()
    if configured:
        return configured
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        revision = completed.stdout.strip()
        if len(revision) == 40 and all(character in "0123456789abcdef" for character in revision):
            return f"git:{revision}+worktree"
    except (OSError, subprocess.SubprocessError):
        pass
    return "worktree:revision-unavailable"


def _progress_log(progress: Mapping[str, Any]) -> None:
    eta = progress.get("etaSeconds")
    LOGGER.info(
        "%s | stage=%s | elapsed=%ss | files=%s/%s | partitions=%s/%s | rows_or_refs=%s/%s | errors=%s | eta=%s",
        progress.get("title", "ASP MODEL STUDIO — MLB IDENTITY BRIDGE"),
        progress.get("stage", "UNKNOWN"),
        progress.get("elapsedSeconds", 0),
        progress.get("filesProcessed", 0),
        progress.get("filesTotal", 0),
        progress.get("partitionsProcessed", 0),
        progress.get("partitionsTotal", 0),
        progress.get("rowsProcessed", progress.get("referencesProcessed", 0)),
        progress.get("rowsTotal", progress.get("referencesTotal", 0)),
        progress.get("errors", 0),
        "unavailable" if eta is None else eta,
    )


@router.post("/sports/identity-bridges/register-approved")
def register_approved_identity_bridge(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_role(user, {"admin"})
    registry = SportsIdentityBridgeRegistry(get_database())
    try:
        registry.require_parent_binding()
        exchange_root = _exchange_root()
        runtime_root = _runtime_root()
        parent = SportsDatasetManifestConsumer(
            approved_package_root(exchange_root),
            cache_path=runtime_root / "dataset-validation" / "validation-cache.json",
            progress=_progress_log,
        ).validate()
        bridge = SportsIdentityBridgeV1Consumer(
            approved_bridge_root(exchange_root),
            progress=_progress_log,
        ).validate()
        audit = MLBFD1IdentityAdapter(bridge, parent, progress=_progress_log).build_join_audit()
        registration = registry.register(
            bridge,
            audit,
            runtime_root=runtime_root,
            user_id=str(user["userId"]),
            code_revision=_code_revision(),
        )
        return {
            "ok": True,
            "identityBridge": registration,
            "registrationDisposition": registration["registrationDisposition"],
            "parentValidationCacheFullyReused": parent.cache_misses == 0,
        }
    except IdentityBridgeValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.public_detail()) from exc
    except ManifestValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.public_detail()) from exc
    except IdentityBridgeRegistrationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "IDENTITY_BRIDGE_REGISTRATION_REJECTED", "message": str(exc)},
        ) from exc


__all__ = ["router"]

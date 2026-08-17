from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..persistence import get_database
from ..security.security_store import require_role, require_user
from .access import SportsDataAccessError, SportsDatasetAccessService, approved_package_root
from .consumer import ManifestValidationError, SportsDatasetManifestConsumer, raw_absolute_path
from .registry import SportsDatasetRegistry


LOGGER = logging.getLogger("asp.sports_datasets")
router = APIRouter()
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio"


def _exchange_root() -> Path:
    configured = os.getenv("ASP_MODEL_EXCHANGE_ROOT", "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail={"code": "EXCHANGE_ROOT_NOT_CONFIGURED", "message": "The administrator-controlled exchange root is not configured."})
    return raw_absolute_path(Path(configured))


def _runtime_root() -> Path:
    configured = os.getenv("ASP_MODEL_STUDIO_SPORTS_MODELING_ROOT", "").strip()
    default = DEFAULT_RUNTIME_ROOT / "sports-modeling"
    return Path(configured).expanduser().resolve(strict=False) if configured else default.resolve(strict=False)


def _registry() -> SportsDatasetRegistry:
    return SportsDatasetRegistry(get_database())


def _access() -> SportsDatasetAccessService:
    return SportsDatasetAccessService(
        _registry(),
        exchange_root=_exchange_root(),
        validation_cache_path=_runtime_root() / "dataset-validation" / "validation-cache.json",
    )


def _raise_access(exc: SportsDataAccessError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc


def _progress_log(progress: dict[str, Any]) -> None:
    eta = "ETA unavailable" if progress["etaSeconds"] is None else f"ETA seconds={progress['etaSeconds']}"
    LOGGER.info(
        "%s | Stage=%s | Elapsed=%ss | Partitions=%s/%s | Rows=%s/%s | Errors=%s | %s",
        progress["title"],
        progress["stage"],
        progress["elapsedSeconds"],
        progress["partitionsProcessed"],
        progress["partitionsTotal"],
        progress["rowsProcessed"],
        progress["rowsTotal"],
        progress["errors"],
        eta,
    )


@router.get("/sports/datasets/active")
def active_dataset(_user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    registry = _registry()
    registration = registry.get_active()
    return {"ok": True, "dataset": registry.public_dataset(registration) if registration else None}


@router.post("/sports/datasets/register-approved")
def register_approved_dataset(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_role(user, {"admin"})
    exchange_root = _exchange_root()
    package_root = approved_package_root(exchange_root)
    cache_path = _runtime_root() / "dataset-validation" / "validation-cache.json"
    try:
        validated = SportsDatasetManifestConsumer(package_root, cache_path=cache_path, progress=_progress_log).validate()
        registry = _registry()
        registration = registry.register(validated, user_id=str(user["userId"]))
        return {
            "ok": True,
            "dataset": registry.public_dataset(registration),
            "registrationDisposition": registration.get("registration_disposition"),
            "validationCacheFullyReused": validated.cache_hits == len(validated.manifest["partitions"]),
        }
    except ManifestValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.public_detail()) from exc


@router.get("/sports/datasets/{registration_id}/aggregates/family-season")
def family_season_counts(
    registration_id: str,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        return {"ok": True, **_access().family_season_counts(registration_id, user_id=str(user["userId"]))}
    except SportsDataAccessError as exc:
        _raise_access(exc)


@router.get("/sports/datasets/{registration_id}/families/{family}/schema")
def family_schema(
    registration_id: str,
    family: str,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        return {"ok": True, **_access().schema_preview(registration_id, family, user_id=str(user["userId"]))}
    except SportsDataAccessError as exc:
        _raise_access(exc)


@router.get("/sports/datasets/{registration_id}/families/{family}/preview")
def family_preview(
    registration_id: str,
    family: str,
    seasons: list[int] = Query(default=[]),
    fields: str | None = None,
    limit: int = Query(default=25, ge=1, le=200),
    queryId: str | None = None,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    selected_fields = [item.strip() for item in fields.split(",") if item.strip()] if fields else None
    try:
        result = _access().preview(
            registration_id,
            family,
            user_id=str(user["userId"]),
            seasons=seasons,
            fields=selected_fields,
            limit=limit,
            query_id=queryId,
        )
        return {"ok": True, **result}
    except SportsDataAccessError as exc:
        _raise_access(exc)


@router.get("/sports/datasets/{registration_id}/families/{family}/class-distribution")
def family_class_distribution(
    registration_id: str,
    family: str,
    field: str,
    seasons: list[int] = Query(default=[]),
    queryId: str | None = None,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            **_access().class_distribution(
                registration_id,
                family,
                field,
                user_id=str(user["userId"]),
                seasons=seasons,
                query_id=queryId,
            ),
        }
    except SportsDataAccessError as exc:
        _raise_access(exc)


@router.get("/sports/datasets/{registration_id}/families/{family}/missingness")
def family_missingness(
    registration_id: str,
    family: str,
    fields: str,
    seasons: list[int] = Query(default=[]),
    queryId: str | None = None,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    selected_fields = [item.strip() for item in fields.split(",") if item.strip()]
    try:
        return {
            "ok": True,
            **_access().missingness(
                registration_id,
                family,
                selected_fields,
                user_id=str(user["userId"]),
                seasons=seasons,
                query_id=queryId,
            ),
        }
    except SportsDataAccessError as exc:
        _raise_access(exc)


@router.get("/sports/datasets/{registration_id}/families/{family}/feature-eligibility")
def family_feature_eligibility(
    registration_id: str,
    family: str,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        return {"ok": True, **_access().feature_eligibility(registration_id, family, user_id=str(user["userId"]))}
    except SportsDataAccessError as exc:
        _raise_access(exc)


@router.get("/sports/datasets/{registration_id}/folds/{fold_id}/scan-plan")
def fold_scan_plan(
    registration_id: str,
    fold_id: str,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    try:
        return {"ok": True, **_access().fold_scan_plan(registration_id, fold_id, user_id=str(user["userId"]))}
    except SportsDataAccessError as exc:
        _raise_access(exc)


@router.post("/sports/datasets/queries/{query_id}/cancel")
def cancel_query(query_id: str, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    try:
        requested = _access().cancel(
            query_id,
            user_id=str(user["userId"]),
            is_admin=user.get("role") == "admin",
        )
        return {"ok": True, "queryId": query_id, "cancellationRequested": requested}
    except SportsDataAccessError as exc:
        _raise_access(exc)

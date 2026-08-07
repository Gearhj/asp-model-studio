"""Hermetic process host for the Bureau Catalog admin acceptance.

This module is imported only by the isolated acceptance subprocess.  It uses
the production catalog router, registry, loader, and operational service, but
replaces live ATLAS authentication with an explicitly bounded synthetic
fixture.  Every mutable authority is supplied as an isolated process setting;
no live security, audit, catalog, or workflow authority is opened by a request.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Mapping
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from server.bureau_metadata import catalog_registry, catalog_router, operational_service
from server.bureau_metadata.operational_service import OperationalCatalogService
from server.security.security_store import require_user


_ROOT_ENV = "ATLAS_ISOLATED_BUREAU_ACCEPTANCE_ROOT"
_REGISTRY_ROOT_ENV = "ATLAS_BUREAU_CATALOG_REGISTRY_ROOT"
_AUDIT_ROOT_ENV = "ATLAS_ISOLATED_BUREAU_AUDIT_ROOT"
_FRONTEND_ORIGIN_ENV = "ATLAS_ISOLATED_BUREAU_FRONTEND_ORIGIN"
_AUDIT_LOCK = threading.RLock()
_AUTH_AUDIT_FILE = "synthetic_authentication_audit.jsonl"
_AUTHORITY_BASE_ENV = "ATLAS_ISOLATED_AUTHORITY_BASE_ROOT"
_PROJECT_FIXTURES: Mapping[str, Mapping[str, Any]] = {
    "synthetic-project-alpha-001": {
        "principal": "synthetic-project-user-alpha",
        "identity": {
            "project_id": "synthetic-project-alpha-001",
            "dataset_id": "synthetic-dataset-alpha-001",
            "dataset_version_id": "synthetic-version-alpha-001",
            "binding_revision": 1,
            "classification": "synthetic_isolated_project_identity",
        },
    },
    "synthetic-project-beta-002": {
        "principal": "synthetic-project-user-beta",
        "identity": {
            "project_id": "synthetic-project-beta-002",
            "dataset_id": "synthetic-dataset-beta-002",
            "dataset_version_id": "synthetic-version-beta-002",
            "binding_revision": 1,
            "classification": "synthetic_isolated_project_identity",
        },
    },
}
_PIN_ENVIRONMENTS = (
    "ATLAS_SQLITE_PATH",
    "ATLAS_SECURITY_ROOT",
    "ATLAS_SECURITY_DB_PATH",
    _AUDIT_ROOT_ENV,
    _REGISTRY_ROOT_ENV,
    _ROOT_ENV,
    "ATLAS_RESTRICTED_METADATA_ROOT",
    "ATLAS_ISOLATED_CATALOG_INSTALL_JOURNAL_ROOT",
    "ATLAS_ISOLATED_PROJECT_REGISTRY_ROOT",
    "ATLAS_ISOLATED_DATASET_REGISTRY_ROOT",
    "ATLAS_ISOLATED_PROJECT_LINKS_ROOT",
    "ATLAS_DATASET_LIBRARY_ROOT",
    "ATLAS_DATASET_LIBRARY_BACKUP_ROOT",
    "ATLAS_CHECKPOINT_PATH",
    "ATLAS_EVIDENCE_ROOT",
    "ATLAS_ISOLATED_DOCUMENTATION_REGISTRY_ROOT",
    "ATLAS_FEATURE_MANIFEST_ROOT",
    "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT",
    "ATLAS_SCORING_RUN_ARTIFACT_ROOT",
    "ATLAS_VIF_PLAN_ROOT",
    "ATLAS_BROWSER_STORAGE_ROOT",
    "ATLAS_PLAYWRIGHT_OUTPUT_ROOT",
    "ATLAS_ISOLATED_LOG_ROOT",
    "ATLAS_ISOLATED_FRONTEND_BUILD_ROOT",
    "ATLAS_PYTHON_RUNTIME_DIR",
    "ATLAS_SAS_CONFIG_DIR",
    "LOCALAPPDATA",
    "TEMP",
    "TMP",
    "PYTHONPYCACHEPREFIX",
)


def _validate_isolated_authority_pins() -> None:
    """Fail startup unless every mutable authority resolves under one isolated base."""

    raw_base = str(os.environ.get(_AUTHORITY_BASE_ENV) or "").strip()
    if not raw_base:
        # Retain compatibility with the older single-root synthetic harness.
        return
    base = Path(raw_base).resolve(strict=True)
    if not base.is_dir():
        raise RuntimeError("The isolated authority base is unavailable.")
    resolved: dict[str, Path] = {}
    for name in _PIN_ENVIRONMENTS:
        raw = str(os.environ.get(name) or "").strip()
        if not raw:
            raise RuntimeError("An isolated mutable-authority pin is missing.")
        candidate = Path(raw).resolve(strict=False)
        if candidate != base and base not in candidate.parents:
            raise RuntimeError("An isolated mutable-authority pin escaped its base.")
        resolved[name] = candidate
    if resolved["ATLAS_SQLITE_PATH"] == resolved["ATLAS_SECURITY_DB_PATH"]:
        raise RuntimeError("Isolated persistence and security database pins overlap.")


_validate_isolated_authority_pins()


def _configured_root(name: str) -> Path:
    configured = Path(os.environ[name]).resolve(strict=True)
    if not configured.is_dir():
        raise RuntimeError("An isolated authority root is unavailable.")
    repository = Path(__file__).resolve().parents[1]
    if configured == repository or repository in configured.parents or configured in repository.parents:
        raise RuntimeError("An isolated authority root overlaps the repository.")
    return configured


def _isolated_root(
    root: str | Path | None,
    *,
    repository_root: str | Path | None = None,
    **_kwargs: Any,
) -> Path:
    """Allow only the exact explicit test root supplied to this subprocess."""

    candidate = Path(str(root or "")).resolve(strict=True)
    permitted = {
        _configured_root(_ROOT_ENV),
        _configured_root(_REGISTRY_ROOT_ENV),
    }
    if candidate not in permitted:
        raise RuntimeError("The isolated catalog service received an unexpected root.")
    if repository_root is not None:
        repository = Path(repository_root).resolve(strict=True)
        if candidate == repository or repository in candidate.parents or candidate in repository.parents:
            raise RuntimeError("The isolated catalog root overlaps the repository.")
    return candidate


def _bounded_audit_text(value: object, fallback: str) -> str:
    cleaned = " ".join(str(value or "").split())
    cleaned = "".join(character for character in cleaned if 31 < ord(character) < 127)
    return (cleaned[:160] or fallback)


def _append_isolated_audit(request: Request, status_code: int, *, action: str) -> None:
    """Append one bounded authorization fact to the isolated audit authority."""

    audit_root = _configured_root(_AUDIT_ROOT_ENV)
    audit_path = audit_root / _AUTH_AUDIT_FILE
    row = {
        "schema_version": "1.0",
        "event_id": "synthetic-auth-event-" + uuid.uuid4().hex,
        "correlation_id": "synthetic-auth-corr-" + uuid.uuid4().hex,
        "actor": _bounded_audit_text(
            request.headers.get("x-synthetic-principal"),
            "unauthenticated",
        ),
        "action": _bounded_audit_text(action, "synthetic_authorization"),
        "result_status": "success" if status_code == 200 else "denied",
        "server_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    if len(encoded.encode("utf-8")) > 1_024:
        raise RuntimeError("The isolated authentication audit row exceeded its bound.")
    with _AUDIT_LOCK, audit_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _append_auth_audit(request: Request, status_code: int) -> None:
    _append_isolated_audit(
        request,
        status_code,
        action="synthetic_authentication",
    )


# Patch the aliases imported by the production constructors.  This relaxation
# exists only in this short-lived synthetic subprocess because production
# correctly rejects Windows Temp as a durable restricted-catalog location.
catalog_registry.validate_restricted_metadata_root = _isolated_root
operational_service.validate_restricted_metadata_root = _isolated_root


def _synthetic_user(request: Request) -> Mapping[str, Any]:
    role = (request.headers.get("x-synthetic-role") or "").strip().lower()
    principal = (request.headers.get("x-synthetic-principal") or "").strip()
    tenant = (request.headers.get("x-synthetic-tenant") or "synthetic-tenant").strip()
    if role not in {"admin", "user"} or not principal:
        raise HTTPException(status_code=401, detail="Synthetic authentication is required.")
    return {
        "userId": principal,
        "displayName": "Synthetic acceptance principal",
        "role": role,
        "status": "active",
        "tenantId": tenant,
    }


def _synthetic_require_role(user: Mapping[str, Any], roles: set[str]) -> None:
    """Role check with no live security audit side effect."""

    if user.get("role") not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions.")


catalog_router.require_role = _synthetic_require_role

service = OperationalCatalogService(
    Path(os.environ[_ROOT_ENV]),
    repository_root=Path(__file__).resolve().parents[1],
    registry_root=Path(os.environ[_REGISTRY_ROOT_ENV]),
)

app = FastAPI(title="ATLAS isolated bureau catalog acceptance")
origin = os.environ.get(_FRONTEND_ORIGIN_ENV, "").strip()
if origin:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "X-Synthetic-Principal",
            "X-Synthetic-Role",
            "X-Synthetic-Tenant",
            "X-Synthetic-Auth-Delay-Ms",
            "X-Synthetic-Run-Id",
        ],
    )
app.dependency_overrides[require_user] = _synthetic_user
app.dependency_overrides[catalog_router.get_operational_catalog_service] = lambda: service
app.include_router(catalog_router.router, prefix="/api")


@app.get("/api/auth/me")
def synthetic_me(
    request: Request,
    user: Mapping[str, Any] = Depends(_synthetic_user),
) -> Mapping[str, Any]:
    try:
        delay_ms = max(
            0,
            min(2_000, int(request.headers.get("x-synthetic-auth-delay-ms") or "0")),
        )
    except ValueError:
        delay_ms = 0
    if delay_ms:
        time.sleep(delay_ms / 1_000)
    return {"ok": True, "user": dict(user)}


@app.get("/api/isolated/project-identities/{project_id}")
def synthetic_project_identity(
    project_id: str,
    request: Request,
    user: Mapping[str, Any] = Depends(_synthetic_user),
) -> Mapping[str, Any]:
    """Return one bounded synthetic project identity to its exact bound user only."""

    fixture = _PROJECT_FIXTURES.get(project_id)
    if fixture is None or user.get("userId") != fixture.get("principal"):
        _append_isolated_audit(
            request,
            403,
            action="synthetic_project_identity_authorization",
        )
        raise HTTPException(status_code=403, detail="Project access denied.")
    _append_isolated_audit(
        request,
        200,
        action="synthetic_project_identity_authorization",
    )
    return {"ok": True, "identity": dict(fixture["identity"])}


@app.get("/health")
def health() -> Mapping[str, Any]:
    return {"ok": True, "service": "isolated-bureau-catalog"}


@app.middleware("http")
async def isolated_auth_audit(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/api/auth/me":
        _append_auth_audit(request, response.status_code)
    return response

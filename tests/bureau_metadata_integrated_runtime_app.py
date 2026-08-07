"""Guarded isolated FastAPI host for the integrated catalog closeout soak.

The regular synthetic runtime remains reusable by focused acceptance tests.  This
wrapper adds two release-only controls:

* every request must prove the exact synthetic run identity (preflights must
  declare its header), so a browser outside the orchestrated profile is detected
  and denied; and
* one bounded endpoint proves exact catalog, entitlement, and governed-crosswalk
  recovery after each real listener restart.

All roots and expected identities are mandatory process pins.  The module has no
fallback to a live authority, a first/latest catalog, or an inferred crosswalk.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from server.bureau_metadata.crosswalk_governance import calculate_revision_checksum
from server.bureau_metadata.crosswalk_governance_repository import (
    SQLiteGovernedCrosswalkRepository,
)
from tests.bureau_metadata_isolated_runtime_app import (
    _synthetic_user,
    app,
    service,
)


_RUN_ID_ENV = "ATLAS_ISOLATED_ACCEPTANCE_RUN_ID"
_CROSSWALK_ID_ENV = "ATLAS_ISOLATED_CROSSWALK_GOVERNANCE_ID"
_CROSSWALK_REVISION_ENV = "ATLAS_ISOLATED_CROSSWALK_REVISION"
_CROSSWALK_CHECKSUM_ENV = "ATLAS_ISOLATED_CROSSWALK_CHECKSUM"
_CATALOG_VERSION_ENV = "ATLAS_ISOLATED_RECOVERY_CATALOG_VERSION_ID"
_CATALOG_CHECKSUM_ENV = "ATLAS_ISOLATED_RECOVERY_CATALOG_CHECKSUM"
_LOG_ROOT_ENV = "ATLAS_ISOLATED_LOG_ROOT"
_RESTRICTED_ROOT_ENV = "ATLAS_ISOLATED_BUREAU_ACCEPTANCE_ROOT"
_VIOLATION_FILE = "integrated-network-isolation-violation.jsonl"
_VIOLATION_LOCK = RLock()


def _required_text(name: str, *, maximum: int = 256) -> str:
    value = str(os.environ.get(name) or "").strip()
    if (
        not value
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise RuntimeError("An integrated isolated-runtime identity pin is invalid.")
    return value


_RUN_ID = _required_text(_RUN_ID_ENV, maximum=128)
_EXPECTED_GOVERNANCE_ID = _required_text(_CROSSWALK_ID_ENV)
_EXPECTED_CROSSWALK_REVISION = int(_required_text(_CROSSWALK_REVISION_ENV, maximum=16))
_EXPECTED_CROSSWALK_CHECKSUM = _required_text(_CROSSWALK_CHECKSUM_ENV, maximum=64)
_EXPECTED_CATALOG_VERSION_ID = _required_text(_CATALOG_VERSION_ENV)
_EXPECTED_CATALOG_CHECKSUM = _required_text(_CATALOG_CHECKSUM_ENV, maximum=64)
if _EXPECTED_CROSSWALK_REVISION < 1:
    raise RuntimeError("The integrated crosswalk revision pin is invalid.")
if any(
    len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
    for value in (_EXPECTED_CROSSWALK_CHECKSUM, _EXPECTED_CATALOG_CHECKSUM)
):
    raise RuntimeError("An integrated checksum pin is invalid.")

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CROSSWALK_REPOSITORY = SQLiteGovernedCrosswalkRepository(
    Path(os.environ[_RESTRICTED_ROOT_ENV]),
    repository_root=_REPOSITORY_ROOT,
)
_VIOLATION_PATH = Path(os.environ[_LOG_ROOT_ENV]).resolve(strict=True) / _VIOLATION_FILE


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _record_isolation_violation(request: Request) -> None:
    row = {
        "schema_version": "1.0",
        "classification": "isolated_runtime_network_violation",
        "occurred_at": _utc_now(),
        "method": request.method[:16],
        "path_digest": hashlib.sha256(request.url.path.encode("utf-8")).hexdigest(),
    }
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    with _VIOLATION_LOCK, _VIOLATION_PATH.open(
        "a", encoding="utf-8", newline="\n"
    ) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


@app.middleware("http")
async def require_integrated_run_identity(request: Request, call_next):
    """Deny and record every request outside this exact orchestrated run."""

    if request.method == "OPTIONS":
        requested_headers = {
            header.strip().lower()
            for header in request.headers.get(
                "access-control-request-headers", ""
            ).split(",")
            if header.strip()
        }
        authorized = "x-synthetic-run-id" in requested_headers
    else:
        authorized = request.headers.get("x-synthetic-run-id") == _RUN_ID
    if not authorized:
        _record_isolation_violation(request)
        return JSONResponse(
            status_code=421,
            content={"detail": "The isolated runtime request is not authorized."},
        )
    return await call_next(request)


@app.get(
    "/api/isolated/integrated-recovery/{catalog_version_id}/{governance_id}/{revision}"
)
def integrated_restart_recovery(
    catalog_version_id: str,
    governance_id: str,
    revision: int,
    user: Mapping[str, Any] = Depends(_synthetic_user),
) -> Mapping[str, Any]:
    """Recover only the exact pre-pinned durable catalog and crosswalk identity."""

    if (
        catalog_version_id != _EXPECTED_CATALOG_VERSION_ID
        or governance_id != _EXPECTED_GOVERNANCE_ID
        or revision != _EXPECTED_CROSSWALK_REVISION
    ):
        raise HTTPException(status_code=404, detail="Exact recovery identity was not found.")
    principal_id = str(user.get("userId") or "")
    tenant_id = str(user.get("tenantId") or "") or None
    try:
        health = service.catalog_health(
            principal_id=principal_id,
            tenant_id=tenant_id,
            catalog_version_id=catalog_version_id,
        )
        service.registry.entitlement_for(
            principal_id=principal_id,
            tenant_id=tenant_id,
            catalog_version_id=catalog_version_id,
            operation="crosswalk_candidate",
        )
        crosswalk = _CROSSWALK_REPOSITORY.get_revision(governance_id, revision)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail="Exact isolated recovery verification failed.",
        ) from exc
    catalog_checksum = str(health.get("normalized_catalog_checksum") or "")
    checksum_verified = calculate_revision_checksum(crosswalk) == crosswalk.revision_checksum
    if (
        catalog_checksum != _EXPECTED_CATALOG_CHECKSUM
        or crosswalk.revision_checksum != _EXPECTED_CROSSWALK_CHECKSUM
        or checksum_verified is not True
    ):
        raise HTTPException(
            status_code=409,
            detail="Exact isolated recovery verification failed.",
        )
    return {
        "ok": True,
        "classification": "synthetic_exact_restart_recovery",
        "run_id": _RUN_ID,
        "catalog": {
            "catalog_version_id": catalog_version_id,
            "catalog_checksum": catalog_checksum,
            "integrity_status": health.get("integrity_status"),
            "exact_identity_verified": True,
        },
        "entitlement": {
            "catalog_health_verified": True,
            "crosswalk_candidate_verified": True,
        },
        "crosswalk": {
            "governance_id": crosswalk.governance_id,
            "revision": crosswalk.revision,
            "revision_checksum": crosswalk.revision_checksum,
            "checksum_verified": True,
        },
        "no_first_or_latest_fallback": True,
    }

"""Authenticated, bounded HTTP surface for restricted bureau catalogs.

The router deliberately exposes no filesystem locations, catalog-wide export,
or unbounded enumeration.  Every handler resolves the authenticated principal
itself; project-scoped preview additionally requires the exact durable
project/dataset link before the catalog entitlement check is evaluated.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Dict, Literal, Mapping, TypeVar
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..datasets.dataset_identity import resolve_project_dataset_identity
from ..security.security_store import require_role, require_user
from .catalog_registry import (
    ALLOWED_ENTITLEMENT_OPERATIONS,
    CatalogRegistryConflictError,
    CatalogRegistryError,
    CatalogRegistryNotFoundError,
)
from .catalog_service import (
    BureauCatalogAccessDeniedError,
    BureauCatalogLookupError,
)
from .catalog_store import (
    BureauCatalogIntegrityError,
    BureauCatalogNotFoundError,
    BureauCatalogStoreError,
)
from .normalizer import canonical_json_bytes
from .operational_service import (
    CatalogOperationalError,
    CatalogSearchTimeoutError,
    MAX_ATTRIBUTE_PAGE_SIZE,
    MAX_SEARCH_OFFSET,
    MAX_SEARCH_QUERY_LENGTH,
    MAX_SPECIAL_PAGE_SIZE,
    OperationalCatalogService,
    get_operational_catalog_service,
)
from .restricted_storage import RestrictedStorageError
from .types import BureauCatalogAccessContext, BureauCatalogKey


router = APIRouter()

_T = TypeVar("_T")
_MAX_VERSION_PAGE = 50
_MAX_CROSSWALK_FIELDS = 250
_MAX_CROSSWALK_RESULTS = 2_000
_MAX_TARGET_SOURCE_FIELDS = 100
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EmptyAdminRequest(_StrictRequest):
    """An explicit empty body prevents silently ignored administrative input."""


class RetireCatalogRequest(_StrictRequest):
    expected_revision: int | None = Field(default=None, ge=1)


CatalogEntitlementOperation = Literal[
    "catalog_health",
    "manifest_read",
    "attribute_lookup",
    "special_value_lookup",
    "value_classification",
    "crosswalk_candidate",
]


class GrantCatalogEntitlementRequest(_StrictRequest):
    principal_id: str = Field(min_length=1, max_length=200)
    tenant_id: str | None = Field(default=None, min_length=1, max_length=200)
    operations: frozenset[CatalogEntitlementOperation] = Field(min_length=1)
    expires_at: str | None = Field(default=None, max_length=64)

    @field_validator("principal_id", "tenant_id")
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Catalog entitlement identifiers contain unsupported characters.")
        return value


class RevokeCatalogEntitlementRequest(_StrictRequest):
    """Reserved for a bounded reason field without accepting arbitrary metadata."""

    reason: str | None = Field(default=None, max_length=160)


class CrosswalkFieldRequest(_StrictRequest):
    field_name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=320)
    units: str | None = Field(default=None, max_length=80)
    observed_min: str | None = Field(default=None, max_length=80)
    observed_max: str | None = Field(default=None, max_length=80)
    observed_special_values: tuple[str, ...] = Field(default=(), max_length=25)
    non_catalog_field: bool = False
    catalog_eligible: bool = True

    @field_validator(
        "field_name",
        "description",
        "units",
        "observed_min",
        "observed_max",
    )
    @classmethod
    def bounded_plain_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(
            (ord(character) < 32 and character not in {"\n", "\t"})
            or ord(character) == 127
            for character in value
        ):
            raise ValueError("Crosswalk schema metadata contains unsupported characters.")
        return value

    @field_validator("observed_special_values")
    @classmethod
    def bounded_special_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            cleaned = str(value).strip()
            if not cleaned or len(cleaned) > 80:
                raise ValueError("Observed special-value codes must contain 1 to 80 characters.")
            if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
                raise ValueError("Observed special-value codes contain unsupported characters.")
            normalized.append(cleaned)
        return tuple(sorted(set(normalized)))


class CrosswalkPreviewRequest(_StrictRequest):
    dataset_id: str = Field(min_length=1, max_length=200)
    dataset_version_id: str = Field(min_length=1, max_length=200)
    schema_checksum: str = Field(pattern=_SHA256_PATTERN)
    fields: tuple[CrosswalkFieldRequest, ...] = Field(
        min_length=1,
        max_length=_MAX_CROSSWALK_FIELDS,
    )
    target_field: str | None = Field(default=None, min_length=1, max_length=160)
    target_source_fields: tuple[str, ...] = Field(
        default=(),
        max_length=_MAX_TARGET_SOURCE_FIELDS,
    )
    semantic_threshold: float = Field(default=0.55, ge=0.5, le=1.0)
    semantic_tie_delta: float = Field(default=0.03, ge=0.0, le=0.10)

    @field_validator("dataset_id", "dataset_version_id", "target_field")
    @classmethod
    def bounded_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Crosswalk identifiers contain unsupported characters.")
        return value

    @field_validator("target_source_fields")
    @classmethod
    def normalize_target_sources(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(sorted({str(value).strip() for value in values if str(value).strip()}))
        if any(len(value) > 160 for value in cleaned):
            raise ValueError("Target-source field names exceed their length limit.")
        return cleaned

    @model_validator(mode="after")
    def require_unique_fields(self) -> "CrosswalkPreviewRequest":
        names = [field.field_name.casefold() for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("Crosswalk schema fields must be unique ignoring case.")
        if self.target_field and self.target_field.casefold() not in set(names):
            raise ValueError("The target field must be present in the bounded schema fields.")
        return self


def _principal(user: Mapping[str, Any]) -> str:
    principal = str(user.get("userId") or "").strip()
    if not principal:
        raise HTTPException(status_code=401, detail="Authentication is required.")
    return principal


def _tenant(user: Mapping[str, Any]) -> str | None:
    tenant = str(user.get("tenantId") or user.get("tenant_id") or "").strip()
    return tenant or None


def _correlation_id() -> str:
    return "bureau-catalog-http-" + uuid.uuid4().hex


def _require_catalog_administrator(
    user: Mapping[str, Any],
    service: OperationalCatalogService,
    catalog_version_id: str,
) -> None:
    """Require both the existing ATLAS admin role and exact catalog grant."""

    require_role(user, {"admin"})
    actor = _principal(user)
    try:
        service.registry.entitlement_for(
            principal_id=actor,
            tenant_id=_tenant(user),
            catalog_version_id=catalog_version_id,
            operation="catalog_health",
        )
    except (BureauCatalogAccessDeniedError, CatalogRegistryNotFoundError) as exc:
        _audit(
            service,
            actor=actor,
            action="catalog_admin_authorization",
            result_status="denied_or_failed",
            catalog_version_id=catalog_version_id,
        )
        raise _safe_http_error(exc) from None


def _audit(
    service: OperationalCatalogService,
    *,
    actor: str,
    action: str,
    result_status: str,
    catalog_version_id: str | None = None,
    attribute_code: str | None = None,
    project_id: str | None = None,
    safe_detail: str | None = None,
) -> None:
    """Best-effort bounded audit; it never replaces the primary HTTP result."""

    try:
        service.registry.record_access_audit(
            actor=actor,
            action=action,
            result_status=result_status,
            correlation_id=_correlation_id(),
            catalog_version_id=catalog_version_id,
            attribute_code=attribute_code,
            project_id=project_id,
            safe_detail=safe_detail,
        )
    except Exception:
        # Registry/storage availability will already be represented by the
        # primary request failure.  Never emit raw catalog/error content from
        # this secondary path.
        pass


def _safe_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, BureauCatalogAccessDeniedError):
        return HTTPException(
            status_code=403,
            detail={
                "code": "bureau_catalog_access_denied",
                "message": "Bureau catalog access is not authorized.",
            },
        )
    if isinstance(exc, (CatalogRegistryNotFoundError, BureauCatalogLookupError, BureauCatalogNotFoundError)):
        return HTTPException(
            status_code=404,
            detail={
                "code": "bureau_catalog_exact_resource_unavailable",
                "message": "The exact catalog version or attribute is unavailable.",
            },
        )
    if isinstance(exc, (CatalogRegistryConflictError, BureauCatalogIntegrityError)):
        return HTTPException(
            status_code=409,
            detail={
                "code": "bureau_catalog_state_conflict",
                "message": "The exact catalog state is contradictory or changed.",
            },
        )
    if isinstance(exc, CatalogSearchTimeoutError):
        return HTTPException(
            status_code=504,
            detail={
                "code": "bureau_catalog_search_timeout",
                "message": "The bounded catalog search exceeded its deadline.",
            },
        )
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=400,
            detail={
                "code": "bureau_catalog_request_invalid",
                "message": "The catalog request is invalid or exceeds a bounded limit.",
            },
        )
    if isinstance(
        exc,
        (
            CatalogOperationalError,
            CatalogRegistryError,
            BureauCatalogStoreError,
            RestrictedStorageError,
        ),
    ):
        return HTTPException(
            status_code=503,
            detail={
                "code": "bureau_catalog_service_unavailable",
                "message": "The restricted catalog service is unavailable.",
            },
        )
    return HTTPException(
        status_code=503,
        detail={
            "code": "bureau_catalog_service_unavailable",
            "message": "The restricted catalog service is unavailable.",
        },
    )


def _execute(
    service: OperationalCatalogService,
    user: Mapping[str, Any],
    action: str,
    function: Callable[[], _T],
    *,
    catalog_version_id: str | None = None,
    attribute_code: str | None = None,
    project_id: str | None = None,
    success_detail: str | None = None,
) -> _T:
    actor = _principal(user)
    try:
        result = function()
    except HTTPException:
        _audit(
            service,
            actor=actor,
            action=action,
            result_status="denied_or_failed",
            catalog_version_id=catalog_version_id,
            attribute_code=attribute_code,
            project_id=project_id,
        )
        raise
    except Exception as exc:
        _audit(
            service,
            actor=actor,
            action=action,
            result_status="denied_or_failed",
            catalog_version_id=catalog_version_id,
            attribute_code=attribute_code,
            project_id=project_id,
        )
        raise _safe_http_error(exc) from exc
    _audit(
        service,
        actor=actor,
        action=action,
        result_status="success",
        catalog_version_id=catalog_version_id,
        attribute_code=attribute_code,
        project_id=project_id,
        safe_detail=success_detail,
    )
    return result


@router.get("/bureau-catalogs")
def list_entitled_catalogs(
    offset: int = Query(default=0, ge=0, le=MAX_SEARCH_OFFSET),
    limit: int = Query(default=25, ge=1, le=_MAX_VERSION_PAGE),
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    actor = _principal(user)
    result = _execute(
        service,
        user,
        "catalog_version_list",
        lambda: service.list_entitled_versions(
            principal_id=actor,
            tenant_id=_tenant(user),
            offset=offset,
            limit=limit,
        ),
        success_detail=f"returned_page offset={offset} limit={limit}",
    )
    return {"ok": True, **dict(result)}


@router.get("/bureau-catalogs/{catalog_version_id}/health")
def catalog_health(
    catalog_version_id: str,
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    result = _execute(
        service,
        user,
        "catalog_health",
        lambda: service.catalog_health(
            principal_id=_principal(user),
            tenant_id=_tenant(user),
            catalog_version_id=catalog_version_id,
        ),
        catalog_version_id=catalog_version_id,
    )
    return {"ok": True, "catalog": dict(result)}


@router.get("/bureau-catalogs/{catalog_version_id}/attributes")
def search_catalog_attributes(
    catalog_version_id: str,
    q: str = Query(min_length=1, max_length=MAX_SEARCH_QUERY_LENGTH),
    offset: int = Query(default=0, ge=0, le=MAX_SEARCH_OFFSET),
    limit: int = Query(default=25, ge=1, le=MAX_ATTRIBUTE_PAGE_SIZE),
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    page = _execute(
        service,
        user,
        "attribute_search",
        lambda: service.search_attributes(
            principal_id=_principal(user),
            tenant_id=_tenant(user),
            catalog_version_id=catalog_version_id,
            query=q,
            offset=offset,
            limit=limit,
        ),
        catalog_version_id=catalog_version_id,
        success_detail=f"returned_page offset={offset} limit={limit}",
    )
    return {"ok": True, **page.public_payload()}


@router.get("/bureau-catalogs/{catalog_version_id}/attributes/{attribute_code}")
def exact_catalog_attribute(
    catalog_version_id: str,
    attribute_code: str,
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    result = _execute(
        service,
        user,
        "attribute_lookup",
        lambda: service.get_attribute(
            principal_id=_principal(user),
            tenant_id=_tenant(user),
            catalog_version_id=catalog_version_id,
            attribute_code=attribute_code,
        ),
        catalog_version_id=catalog_version_id,
        attribute_code=attribute_code,
    )
    return {"ok": True, "attribute": dict(result)}


@router.get("/bureau-catalogs/{catalog_version_id}/attributes/{attribute_code}/special-values")
def catalog_attribute_special_values(
    catalog_version_id: str,
    attribute_code: str,
    offset: int = Query(default=0, ge=0, le=MAX_SEARCH_OFFSET),
    limit: int = Query(default=25, ge=1, le=MAX_SPECIAL_PAGE_SIZE),
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    result = _execute(
        service,
        user,
        "special_value_lookup",
        lambda: service.list_special_values(
            principal_id=_principal(user),
            tenant_id=_tenant(user),
            catalog_version_id=catalog_version_id,
            attribute_code=attribute_code,
            offset=offset,
            limit=limit,
        ),
        catalog_version_id=catalog_version_id,
        attribute_code=attribute_code,
        success_detail=f"returned_page offset={offset} limit={limit}",
    )
    return {"ok": True, **dict(result)}


@router.get("/bureau-catalogs/{catalog_version_id}/attributes/{attribute_code}/availability")
def catalog_attribute_availability(
    catalog_version_id: str,
    attribute_code: str,
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    result = _execute(
        service,
        user,
        "attribute_availability",
        lambda: service.attribute_availability(
            principal_id=_principal(user),
            tenant_id=_tenant(user),
            catalog_version_id=catalog_version_id,
            attribute_code=attribute_code,
        ),
        catalog_version_id=catalog_version_id,
        attribute_code=attribute_code,
    )
    return {"ok": True, "availability": dict(result)}


@router.post("/projects/{project_id}/bureau-catalogs/{catalog_version_id}/crosswalk-preview")
def project_catalog_crosswalk_preview(
    project_id: str,
    catalog_version_id: str,
    payload: CrosswalkPreviewRequest,
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    actor = _principal(user)

    # This exact resolver first authorizes the project, then verifies the
    # requested registered version and durable project-to-dataset link.  It
    # never selects first/latest/checkpoint/browser state.
    identity = _execute(
        service,
        user,
        "crosswalk_identity_resolve",
        lambda: resolve_project_dataset_identity(
            project_id,
            payload.dataset_id,
            payload.dataset_version_id,
            user=user,
            require_artifact=False,
        ),
        catalog_version_id=catalog_version_id,
        project_id=project_id,
    )
    registered_schema_checksum = str(identity.get("dataset_schema_hash") or "").strip().lower()
    if registered_schema_checksum and registered_schema_checksum != payload.schema_checksum:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "bureau_crosswalk_schema_identity_conflict",
                "message": "The supplied schema does not match the exact registered dataset version.",
            },
        )

    def build_preview() -> Mapping[str, Any]:
        record = service.registry.get_version(catalog_version_id)
        result = service.catalogs.build_dataset_crosswalk_candidates_exact(
            BureauCatalogAccessContext(
                principal_id=actor,
                tenant_id=_tenant(user),
                project_id=project_id,
            ),
            BureauCatalogKey(
                provider=record.provider_name,
                product=record.product_name,
                edition=record.edition,
                dictionary_version=record.source_release_version,
            ),
            record.normalized_catalog_checksum,
            [field.model_dump(mode="json") for field in payload.fields],
            target_field=payload.target_field,
            target_source_fields=payload.target_source_fields,
            semantic_threshold=payload.semantic_threshold,
            semantic_tie_delta=payload.semantic_tie_delta,
        )
        mappings = result.get("mappings")
        if not isinstance(mappings, list) or len(mappings) > _MAX_CROSSWALK_RESULTS:
            raise ValueError(
                "Crosswalk candidate ambiguity exceeds the bounded response limit."
            )
        return result

    preview = _execute(
        service,
        user,
        "crosswalk_preview",
        build_preview,
        catalog_version_id=catalog_version_id,
        project_id=project_id,
        success_detail=f"schema_fields={len(payload.fields)} candidate_only=true",
    )
    preview_checksum = hashlib.sha256(
        canonical_json_bytes(
            {
                "project_id": project_id,
                "dataset_id": payload.dataset_id,
                "dataset_version_id": payload.dataset_version_id,
                "schema_checksum": payload.schema_checksum,
                "catalog_version_id": catalog_version_id,
                "candidate_crosswalk_checksum": preview.get("crosswalk_checksum"),
            }
        )
    ).hexdigest()
    return {
        "ok": True,
        "identity": {
            "project_id": project_id,
            "dataset_id": payload.dataset_id,
            "dataset_version_id": payload.dataset_version_id,
            "schema_checksum": payload.schema_checksum,
            "catalog_version_id": catalog_version_id,
        },
        "preview_status": "candidate_only",
        "preview_checksum": preview_checksum,
        "persisted": False,
        "dataset_mutated": False,
        "governed_feature_set_changed": False,
        "crosswalk": dict(preview),
    }


@router.get("/admin/bureau-catalogs")
def admin_list_catalogs(
    offset: int = Query(default=0, ge=0, le=MAX_SEARCH_OFFSET),
    limit: int = Query(default=25, ge=1, le=_MAX_VERSION_PAGE),
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    require_role(user, {"admin"})
    page = _execute(
        service,
        user,
        "catalog_admin_list",
        lambda: service.list_entitled_versions(
            principal_id=_principal(user),
            tenant_id=_tenant(user),
            offset=offset,
            limit=limit,
        ),
        success_detail=f"returned_page offset={offset} limit={limit}",
    )
    return {
        "ok": True,
        **dict(page),
        "catalogs": list(page["versions"]),
    }


@router.post("/admin/bureau-catalogs/{catalog_version_id}/validate")
def admin_validate_catalog(
    catalog_version_id: str,
    _payload: EmptyAdminRequest,
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    _require_catalog_administrator(user, service, catalog_version_id)
    verification = _execute(
        service,
        user,
        "catalog_admin_validate",
        lambda: service.validate_integrity_as_administrator(
            actor=_principal(user),
            catalog_version_id=catalog_version_id,
        ),
        catalog_version_id=catalog_version_id,
    )
    record = service.registry.get_version(catalog_version_id)
    return {"ok": True, "catalog": record.public_payload(), "verification": dict(verification)}


@router.post("/admin/bureau-catalogs/{catalog_version_id}/retire")
def admin_retire_catalog(
    catalog_version_id: str,
    payload: RetireCatalogRequest,
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    _require_catalog_administrator(user, service, catalog_version_id)

    def retire():
        current = service.registry.get_version(catalog_version_id)
        expected_revision = payload.expected_revision or current.registry_revision
        return service.registry.retire_version(
            catalog_version_id,
            actor=_principal(user),
            expected_revision=expected_revision,
        )

    record = _execute(
        service,
        user,
        "catalog_admin_retire",
        retire,
        catalog_version_id=catalog_version_id,
    )
    service.loader.clear()
    return {"ok": True, "catalog": record.public_payload()}


@router.post("/admin/bureau-catalogs/{catalog_version_id}/entitlements")
def admin_grant_catalog_entitlement(
    catalog_version_id: str,
    payload: GrantCatalogEntitlementRequest,
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    _require_catalog_administrator(user, service, catalog_version_id)
    if not set(payload.operations).issubset(ALLOWED_ENTITLEMENT_OPERATIONS):
        raise HTTPException(status_code=400, detail="Unsupported catalog entitlement operation.")
    entitlement = _execute(
        service,
        user,
        "catalog_entitlement_grant",
        lambda: service.registry.grant_entitlement(
            principal_id=payload.principal_id,
            tenant_id=payload.tenant_id,
            catalog_version_id=catalog_version_id,
            operations=payload.operations,
            granted_by=_principal(user),
            expires_at=payload.expires_at,
        ),
        catalog_version_id=catalog_version_id,
        success_detail="entitlement_granted",
    )
    return {"ok": True, "entitlement": entitlement.public_payload()}


@router.post("/admin/bureau-catalog-entitlements/{entitlement_id}/revoke")
def admin_revoke_catalog_entitlement(
    entitlement_id: str,
    _payload: RevokeCatalogEntitlementRequest,
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    require_role(user, {"admin"})
    existing = service.registry.get_entitlement(entitlement_id)
    _require_catalog_administrator(user, service, existing.catalog_version_id)
    entitlement = _execute(
        service,
        user,
        "catalog_entitlement_revoke",
        lambda: service.registry.revoke_entitlement(
            entitlement_id,
            revoked_by=_principal(user),
        ),
        success_detail="entitlement_revoked",
    )
    return {"ok": True, "entitlement": entitlement.public_payload()}


# Administration uses the same independently entitled definition endpoints;
# these aliases support the minimal admin surface without broadening access.
@router.get("/admin/bureau-catalogs/{catalog_version_id}/attributes")
def admin_search_catalog_attributes(
    catalog_version_id: str,
    q: str = Query(min_length=1, max_length=MAX_SEARCH_QUERY_LENGTH),
    offset: int = Query(default=0, ge=0, le=MAX_SEARCH_OFFSET),
    limit: int = Query(default=25, ge=1, le=MAX_ATTRIBUTE_PAGE_SIZE),
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    require_role(user, {"admin"})
    return search_catalog_attributes(
        catalog_version_id=catalog_version_id,
        q=q,
        offset=offset,
        limit=limit,
        user=user,
        service=service,
    )


@router.get("/admin/bureau-catalogs/{catalog_version_id}/attributes/{attribute_code}")
def admin_exact_catalog_attribute(
    catalog_version_id: str,
    attribute_code: str,
    user: Dict[str, Any] = Depends(require_user),
    service: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    require_role(user, {"admin"})
    return exact_catalog_attribute(
        catalog_version_id=catalog_version_id,
        attribute_code=attribute_code,
        user=user,
        service=service,
    )


__all__ = [
    "CrosswalkFieldRequest",
    "CrosswalkPreviewRequest",
    "GrantCatalogEntitlementRequest",
    "RetireCatalogRequest",
    "router",
]

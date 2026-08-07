"""Bounded operational service for durable bureau metadata catalogs."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import threading
import time
import uuid
from typing import Any, Iterable, Mapping

from .catalog_registry import (
    CatalogRegistry,
    CatalogRegistryNotFoundError,
    CatalogVersionRecord,
    RegistryEntitlementProvider,
)
from .catalog_service import (
    BureauCatalogLookupError,
    BureauCatalogService,
)
from .catalog_store import BureauCatalogIntegrityError, BureauCatalogLoader, BureauCatalogStore
from .normalizer import normalize_attribute_code
from .restricted_storage import RESTRICTED_ROOT_ENV, validate_restricted_metadata_root
from .types import BureauCatalogAccessContext, BureauCatalogKey


MAX_ATTRIBUTE_PAGE_SIZE = 50
MAX_SPECIAL_PAGE_SIZE = 100
MAX_SEARCH_QUERY_LENGTH = 128
MAX_SEARCH_OFFSET = 100_000
MAX_MAPPED_ATTRIBUTE_BATCH_SIZE = 250
MAX_MAPPED_SPECIAL_DEFINITIONS_PER_ATTRIBUTE = 64
MAX_MAPPED_SPECIAL_DEFINITIONS_TOTAL = 1_024
DEFAULT_SEARCH_TIMEOUT_SECONDS = 2.0
CATALOG_REGISTRY_ROOT_ENV = "ATLAS_BUREAU_CATALOG_REGISTRY_ROOT"


class CatalogOperationalError(RuntimeError):
    """Base class for safe operational failures."""


class CatalogSearchTimeoutError(CatalogOperationalError):
    """A bounded search exceeded its server-side deadline."""


@dataclass(frozen=True, slots=True)
class CatalogSearchPage:
    catalog_version_id: str
    query: str
    offset: int
    limit: int
    returned: int
    has_more: bool
    results: tuple[Mapping[str, Any], ...]

    def public_payload(self) -> dict[str, Any]:
        return {
            "catalog_version_id": self.catalog_version_id,
            "query": self.query,
            "offset": self.offset,
            "limit": self.limit,
            "returned": self.returned,
            "has_more": self.has_more,
            "results": [dict(item) for item in self.results],
        }


def _key(record: CatalogVersionRecord) -> BureauCatalogKey:
    return BureauCatalogKey(
        provider=record.provider_name,
        product=record.product_name,
        edition=record.edition,
        dictionary_version=record.source_release_version,
    )


def _context(principal_id: str, tenant_id: str | None, project_id: str | None = None) -> BureauCatalogAccessContext:
    return BureauCatalogAccessContext(
        principal_id=principal_id,
        tenant_id=tenant_id,
        project_id=project_id,
    )


def _correlation_id() -> str:
    return "bureau-catalog-corr-" + uuid.uuid4().hex


class OperationalCatalogService:
    """Provider-neutral exact service; all catalog access is entitlement checked."""

    def __init__(
        self,
        restricted_root: str | Path,
        *,
        repository_root: str | Path | None = None,
        max_cache_entries: int = 4,
        registry_root: str | Path | None = None,
    ) -> None:
        self.root = validate_restricted_metadata_root(
            restricted_root,
            repository_root=repository_root,
        )
        self.registry = CatalogRegistry(
            self.root,
            repository_root=repository_root,
            registry_root=registry_root,
        )
        self.store = BureauCatalogStore(self.root, repository_root=repository_root)
        self.loader = BureauCatalogLoader(self.store, max_entries=max_cache_entries)
        self.catalogs = BureauCatalogService(
            self.loader,
            RegistryEntitlementProvider(self.registry),
        )

    def list_entitled_versions(
        self,
        *,
        principal_id: str,
        tenant_id: str | None,
        offset: int = 0,
        limit: int = 25,
    ) -> Mapping[str, Any]:
        records = self.registry.list_entitled_versions(
            principal_id=principal_id,
            tenant_id=tenant_id,
            operation="catalog_health",
            offset=offset,
            limit=limit,
        )
        return {
            "offset": max(0, int(offset)),
            "limit": int(limit),
            "returned": len(records),
            "versions": [record.public_payload() for record in records],
        }

    def catalog_health(
        self,
        *,
        principal_id: str,
        tenant_id: str | None,
        catalog_version_id: str,
    ) -> Mapping[str, Any]:
        correlation = _correlation_id()
        record = self.registry.get_version(catalog_version_id)
        try:
            health = self.catalogs.catalog_health_exact(
                _context(principal_id, tenant_id),
                _key(record),
                record.normalized_catalog_checksum,
            )
            result = {
                **record.public_payload(),
                "catalog_health": dict(health),
                "cache_entries": self.loader.cache_size(),
            }
            self.registry.record_access_audit(
                actor=principal_id,
                catalog_version_id=record.catalog_version_id,
                action="catalog_health",
                result_status="success",
                correlation_id=correlation,
            )
            return result
        except Exception:
            self.registry.record_access_audit(
                actor=principal_id,
                catalog_version_id=record.catalog_version_id,
                action="catalog_health",
                result_status="denied_or_failed",
                correlation_id=correlation,
            )
            raise

    def verify_integrity(
        self,
        *,
        principal_id: str,
        tenant_id: str | None,
        catalog_version_id: str,
    ) -> Mapping[str, Any]:
        """Evict the cache and perform a complete exact checksum validation."""

        record = self.registry.get_version(catalog_version_id)
        # Verify the entitlement independently of the version's current
        # integrity status.  This permits a previously failed version to be
        # revalidated after an administrator repairs the external bytes,
        # without allowing ordinary catalog reads while it remains failed.
        self.registry.entitlement_for(
            principal_id=principal_id,
            tenant_id=tenant_id,
            catalog_version_id=record.catalog_version_id,
            operation="catalog_health",
        )
        return self._verify_integrity_bytes(record, actor=principal_id)

    def validate_integrity_as_administrator(
        self,
        *,
        actor: str,
        catalog_version_id: str,
    ) -> Mapping[str, Any]:
        """Validate exact bytes after the HTTP layer has enforced admin role."""

        record = self.registry.get_version(catalog_version_id)
        return self._verify_integrity_bytes(record, actor=actor)

    def _verify_integrity_bytes(
        self,
        record: CatalogVersionRecord,
        *,
        actor: str,
    ) -> Mapping[str, Any]:
        correlation = _correlation_id()
        self.loader.clear()
        try:
            catalog = self.store.load_exact(
                _key(record), record.normalized_catalog_checksum
            )
            health = {
                "attribute_count": catalog.manifest.attribute_count,
                "special_value_count": catalog.manifest.special_value_count,
                "catalog_checksum": catalog.manifest.catalog_checksum,
            }
            if (
                int(health["attribute_count"]) != record.record_count
                or int(health["special_value_count"]) != record.special_value_definition_count
                or str(health["catalog_checksum"]) != record.normalized_catalog_checksum
            ):
                raise BureauCatalogIntegrityError(
                    "Catalog registry and installed content are contradictory."
                )
            updated = self.registry.set_integrity_status(
                record.catalog_version_id, status="verified"
            )
            self.registry.record_access_audit(
                actor=actor,
                catalog_version_id=record.catalog_version_id,
                action="catalog_integrity_validate",
                result_status="success",
                correlation_id=correlation,
            )
            return {
                "catalog_version_id": updated.catalog_version_id,
                "integrity_status": updated.integrity_status,
                "catalog_checksum": updated.normalized_catalog_checksum,
                "record_count": updated.record_count,
                "special_value_definition_count": updated.special_value_definition_count,
            }
        except Exception:
            self.loader.clear()
            self.registry.set_integrity_status(record.catalog_version_id, status="failed")
            self.registry.record_access_audit(
                actor=actor,
                catalog_version_id=record.catalog_version_id,
                action="catalog_integrity_validate",
                result_status="failed",
                correlation_id=correlation,
            )
            raise

    def search_attributes(
        self,
        *,
        principal_id: str,
        tenant_id: str | None,
        catalog_version_id: str,
        query: str,
        offset: int = 0,
        limit: int = 25,
        timeout_seconds: float = DEFAULT_SEARCH_TIMEOUT_SECONDS,
    ) -> CatalogSearchPage:
        normalized_query = " ".join(str(query or "").split())
        if not normalized_query or len(normalized_query) > MAX_SEARCH_QUERY_LENGTH:
            raise ValueError(
                f"Catalog search query must contain 1 to {MAX_SEARCH_QUERY_LENGTH} characters."
            )
        bounded_offset = int(offset)
        bounded_limit = int(limit)
        if bounded_offset < 0 or bounded_offset > MAX_SEARCH_OFFSET:
            raise ValueError("Catalog search offset is outside its bounded range.")
        if bounded_limit <= 0 or bounded_limit > MAX_ATTRIBUTE_PAGE_SIZE:
            raise ValueError(
                f"Catalog search page size must be between 1 and {MAX_ATTRIBUTE_PAGE_SIZE}."
            )
        record = self.registry.get_version(catalog_version_id)
        context = _context(principal_id, tenant_id)
        catalog = self.catalogs._load_authorized(
            context,
            _key(record),
            record.normalized_catalog_checksum,
            "attribute_lookup",
        )
        needle = normalized_query.casefold()
        deadline = time.monotonic() + max(0.05, min(float(timeout_seconds), 5.0))
        matches: list[Mapping[str, Any]] = []
        seen = 0
        has_more = False
        for code in sorted(catalog.attributes_by_code):
            if time.monotonic() > deadline:
                raise CatalogSearchTimeoutError("Catalog search exceeded its bounded deadline.")
            attribute = catalog.attributes_by_code[code]
            if needle not in code.casefold() and needle not in attribute.description.casefold():
                continue
            if seen < bounded_offset:
                seen += 1
                continue
            if len(matches) >= bounded_limit:
                has_more = True
                break
            matches.append(
                {
                    "attribute_code": attribute.attribute_code,
                    "description": attribute.description[:320],
                    "numeric_type": attribute.numeric_type,
                    "units": attribute.units,
                    "valid_range_expression": attribute.valid_range_expression,
                    "review_status": attribute.review_status,
                    "record_checksum": attribute.record_checksum,
                }
            )
        self.registry.record_access_audit(
            actor=principal_id,
            catalog_version_id=record.catalog_version_id,
            action="attribute_search",
            result_status="success",
            correlation_id=_correlation_id(),
            safe_detail=f"returned={len(matches)} offset={bounded_offset} limit={bounded_limit}",
        )
        return CatalogSearchPage(
            catalog_version_id=record.catalog_version_id,
            query=normalized_query,
            offset=bounded_offset,
            limit=bounded_limit,
            returned=len(matches),
            has_more=has_more,
            results=tuple(matches),
        )

    def get_attribute(
        self,
        *,
        principal_id: str,
        tenant_id: str | None,
        catalog_version_id: str,
        attribute_code: str,
    ) -> Mapping[str, Any]:
        record = self.registry.get_version(catalog_version_id)
        attribute = self.catalogs.get_attribute_exact(
            _context(principal_id, tenant_id),
            _key(record),
            record.normalized_catalog_checksum,
            attribute_code,
        )
        self.registry.record_access_audit(
            actor=principal_id,
            catalog_version_id=record.catalog_version_id,
            attribute_code=attribute.attribute_code,
            action="attribute_lookup",
            result_status="success",
            correlation_id=_correlation_id(),
        )
        payload = attribute.model_dump(mode="json")
        payload.pop("catalog_key", None)
        payload["catalog_version_id"] = record.catalog_version_id
        return payload

    def get_mapped_attribute_batch(
        self,
        *,
        principal_id: str,
        tenant_id: str | None,
        catalog_version_id: str,
        attribute_codes: Iterable[str],
    ) -> Mapping[str, Any]:
        """Return bounded provider semantics for an exact mapped-field set.

        The exact entitled catalog is loaded once. This avoids one attribute
        request and one special-value request per Data Acquisition table row,
        while preserving the same backend entitlement boundary.
        """

        codes = tuple(
            sorted(
                {
                    normalize_attribute_code(value)
                    for value in attribute_codes
                    if str(value or "").strip()
                }
            )
        )
        if not codes or len(codes) > MAX_MAPPED_ATTRIBUTE_BATCH_SIZE:
            raise ValueError(
                "Mapped attribute batches must contain between 1 and "
                f"{MAX_MAPPED_ATTRIBUTE_BATCH_SIZE} exact codes."
            )
        record = self.registry.get_version(catalog_version_id)
        context = _context(principal_id, tenant_id)
        catalog = self.catalogs._load_authorized(
            context,
            _key(record),
            record.normalized_catalog_checksum,
            "attribute_lookup",
        )
        missing = [code for code in codes if code not in catalog.attributes_by_code]
        if missing:
            raise BureauCatalogLookupError(
                "An exact mapped catalog attribute is unavailable."
            )
        remaining_specials = MAX_MAPPED_SPECIAL_DEFINITIONS_TOTAL
        rows: list[dict[str, Any]] = []
        for code in codes:
            attribute = catalog.attributes_by_code[code]
            available_specials = [
                special
                for (attribute_code, _value), special in sorted(
                    catalog.special_values_by_key.items()
                )
                if attribute_code == code
            ]
            special_limit = min(
                MAX_MAPPED_SPECIAL_DEFINITIONS_PER_ATTRIBUTE,
                remaining_specials,
            )
            selected_specials = available_specials[:special_limit]
            remaining_specials -= len(selected_specials)
            valid_values = tuple(getattr(attribute, "valid_values", ()) or ())
            applicable_versions = tuple(
                getattr(attribute, "applicable_versions", ()) or ()
            )
            cross_bureau_availability = tuple(
                getattr(attribute, "cross_bureau_availability", ()) or ()
            )
            rows.append(
                {
                    "attribute_code": attribute.attribute_code,
                    "description": attribute.description[:320],
                    "numeric_type": attribute.numeric_type,
                    "units": attribute.units,
                    "field_length": attribute.field_length,
                    "valid_range_expression": attribute.valid_range_expression,
                    "ordinary_min": attribute.ordinary_min,
                    "ordinary_max": attribute.ordinary_max,
                    # Bounded restriction metadata is needed to reconcile an
                    # accepted mapping with the exact Dataset Library schema.
                    # It remains within the existing entitled mapped-field
                    # batch and never exposes the complete catalog.
                    "valid_values": list(valid_values[:64]),
                    "valid_values_truncated": len(valid_values) > 64,
                    "applicable_versions": list(applicable_versions[:32]),
                    "applicable_versions_truncated": len(applicable_versions)
                    > 32,
                    "cross_bureau_availability": list(
                        cross_bureau_availability[:16]
                    ),
                    "leveling_indicator": getattr(
                        attribute, "leveling_indicator", None
                    ),
                    "archive_indicator": getattr(attribute, "archive_indicator", None),
                    "reconciliation_status": getattr(
                        attribute, "reconciliation_status", "unreviewed"
                    ),
                    "review_status": getattr(
                        attribute, "review_status", "unreviewed"
                    ),
                    "record_checksum": attribute.record_checksum,
                    "special_values": [
                        {
                            "value_code": item.value_code,
                            "meaning": item.meaning[:512],
                            "semantic_family": item.semantic_family,
                            "definition_id": item.definition_id,
                            "definition_checksum": item.definition_checksum,
                        }
                        for item in selected_specials
                    ],
                    # The exact total is safe, bounded metadata for an already
                    # entitled mapped attribute.  Returning it avoids treating
                    # a response-size cap as though the catalog contained no
                    # additional definitions.
                    "special_values_total": len(available_specials),
                    "special_values_truncated": len(selected_specials)
                    < len(available_specials),
                }
            )
        self.registry.record_access_audit(
            actor=principal_id,
            catalog_version_id=record.catalog_version_id,
            action="mapped_attribute_batch",
            result_status="success",
            correlation_id=_correlation_id(),
            safe_detail=(
                f"returned={len(rows)} specials="
                f"{sum(len(row['special_values']) for row in rows)}"
            ),
        )
        return {
            "catalog_version_id": record.catalog_version_id,
            "catalog_checksum": record.normalized_catalog_checksum,
            "requested": len(codes),
            "returned": len(rows),
            "attributes": rows,
            "bounded": True,
        }

    def list_special_values(
        self,
        *,
        principal_id: str,
        tenant_id: str | None,
        catalog_version_id: str,
        attribute_code: str,
        offset: int = 0,
        limit: int = 25,
    ) -> Mapping[str, Any]:
        bounded_offset = max(0, int(offset))
        bounded_limit = int(limit)
        if bounded_limit <= 0 or bounded_limit > MAX_SPECIAL_PAGE_SIZE:
            raise ValueError(
                f"Special-value page size must be between 1 and {MAX_SPECIAL_PAGE_SIZE}."
            )
        record = self.registry.get_version(catalog_version_id)
        context = _context(principal_id, tenant_id)
        catalog = self.catalogs._load_authorized(
            context,
            _key(record),
            record.normalized_catalog_checksum,
            "special_value_lookup",
        )
        code = normalize_attribute_code(attribute_code)
        if code not in catalog.attributes_by_code:
            raise BureauCatalogLookupError("The exact catalog attribute is unavailable.")
        values = [
            special
            for (attribute, _value), special in sorted(catalog.special_values_by_key.items())
            if attribute == code
        ]
        selected = values[bounded_offset : bounded_offset + bounded_limit]
        self.registry.record_access_audit(
            actor=principal_id,
            catalog_version_id=record.catalog_version_id,
            attribute_code=code,
            action="special_value_lookup",
            result_status="success",
            correlation_id=_correlation_id(),
            safe_detail=f"returned={len(selected)} offset={bounded_offset} limit={bounded_limit}",
        )
        return {
            "catalog_version_id": record.catalog_version_id,
            "attribute_code": code,
            "offset": bounded_offset,
            "limit": bounded_limit,
            "returned": len(selected),
            "has_more": bounded_offset + len(selected) < len(values),
            "special_values": [
                {
                    "value_code": item.value_code,
                    "meaning": item.meaning,
                    "semantic_family": item.semantic_family,
                    "review_status": item.review_status,
                    "definition_id": item.definition_id,
                    "definition_checksum": item.definition_checksum,
                }
                for item in selected
            ],
        }

    def attribute_availability(
        self,
        *,
        principal_id: str,
        tenant_id: str | None,
        catalog_version_id: str,
        attribute_code: str,
    ) -> Mapping[str, Any]:
        attribute = self.get_attribute(
            principal_id=principal_id,
            tenant_id=tenant_id,
            catalog_version_id=catalog_version_id,
            attribute_code=attribute_code,
        )
        return {
            "catalog_version_id": catalog_version_id,
            "attribute_code": attribute["attribute_code"],
            "valid_range_expression": attribute.get("valid_range_expression"),
            "ordinary_min": attribute.get("ordinary_min"),
            "ordinary_max": attribute.get("ordinary_max"),
            "valid_values": attribute.get("valid_values", []),
            "applicable_versions": attribute.get("applicable_versions", []),
            "cross_bureau_availability": attribute.get("cross_bureau_availability", []),
            "leveling_indicator": attribute.get("leveling_indicator"),
            "archive_indicator": attribute.get("archive_indicator"),
        }


_SERVICE_LOCK = threading.RLock()
_SERVICE_CACHE: dict[str, OperationalCatalogService] = {}


def get_operational_catalog_service() -> OperationalCatalogService:
    configured = str(os.getenv(RESTRICTED_ROOT_ENV) or "").strip()
    root = validate_restricted_metadata_root(configured)
    configured_registry = str(os.getenv(CATALOG_REGISTRY_ROOT_ENV) or "").strip()
    registry_root = (
        validate_restricted_metadata_root(configured_registry)
        if configured_registry
        else None
    )
    key = "::".join(
        (
            str(root).casefold(),
            str(registry_root or root).casefold(),
        )
    )
    with _SERVICE_LOCK:
        service = _SERVICE_CACHE.get(key)
        if service is None:
            service = OperationalCatalogService(root, registry_root=registry_root)
            _SERVICE_CACHE.clear()
            _SERVICE_CACHE[key] = service
        return service


def clear_operational_catalog_service_cache() -> None:
    with _SERVICE_LOCK:
        for service in _SERVICE_CACHE.values():
            service.loader.clear()
        _SERVICE_CACHE.clear()


__all__ = [
    "CATALOG_REGISTRY_ROOT_ENV",
    "CatalogOperationalError",
    "CatalogSearchPage",
    "CatalogSearchTimeoutError",
    "DEFAULT_SEARCH_TIMEOUT_SECONDS",
    "MAX_ATTRIBUTE_PAGE_SIZE",
    "MAX_MAPPED_ATTRIBUTE_BATCH_SIZE",
    "MAX_MAPPED_SPECIAL_DEFINITIONS_PER_ATTRIBUTE",
    "MAX_MAPPED_SPECIAL_DEFINITIONS_TOTAL",
    "MAX_SEARCH_OFFSET",
    "MAX_SEARCH_QUERY_LENGTH",
    "MAX_SPECIAL_PAGE_SIZE",
    "OperationalCatalogService",
    "clear_operational_catalog_service_cache",
    "get_operational_catalog_service",
]

"""Durable, provider-neutral registration and entitlement authority.

The registry stores only safe catalog metadata, opaque storage references, and
bounded audit facts.  Restricted definitions remain in the exact catalog
snapshot and are never copied into this SQLite authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import uuid
from typing import Any, Iterable, Mapping, Sequence

from .catalog_service import (
    BureauCatalogAccessDeniedError,
    BureauCatalogEntitlementProvider,
)
from .normalizer import canonical_json_bytes, validate_sha256
from .restricted_storage import validate_restricted_metadata_root
from .types import (
    BureauCatalogAccessContext,
    BureauCatalogAccessGrant,
    BureauCatalogKey,
    BureauCatalogManifest,
    CatalogOperation,
)


REGISTRY_SCHEMA_VERSION = "1.0"
REGISTRY_DATABASE_RELATIVE = Path("registry") / "catalog_registry.sqlite3"
MAX_PAGE_SIZE = 100
MAX_AUDIT_TEXT = 160
MAX_REGISTRY_METADATA_BYTES = 32 * 1024
MAX_REGISTRY_METADATA_ITEMS = 256
ALLOWED_ENTITLEMENT_OPERATIONS: frozenset[str] = frozenset(
    {
        "catalog_health",
        "manifest_read",
        "attribute_lookup",
        "special_value_lookup",
        "value_classification",
        "crosswalk_candidate",
    }
)


class CatalogRegistryError(RuntimeError):
    """Base class for safe durable registry failures."""


class CatalogRegistryConflictError(CatalogRegistryError):
    """An immutable version or optimistic revision contradicted authority."""


class CatalogRegistryNotFoundError(CatalogRegistryError):
    """The exact requested registry identity does not exist."""


@dataclass(frozen=True, slots=True)
class CatalogVersionRecord:
    catalog_id: str
    catalog_version_id: str
    provider_id: str
    provider_name: str
    product_id: str
    product_name: str
    edition: str
    country_or_region: str
    source_release_version: str
    source_checksum: str
    normalized_catalog_checksum: str
    record_count: int
    special_value_definition_count: int
    supported_bureau_versions: tuple[str, ...]
    provider_availability_metadata: Mapping[str, Any]
    leveling_metadata: Mapping[str, Any]
    archive_availability_metadata: Mapping[str, Any]
    parser_build_version: str
    schema_version: str
    source_provenance_reference: str
    restricted_storage_reference: str
    installation_status: str
    integrity_status: str
    entitlement_classification: str
    created_by: str
    created_at: str
    updated_at: str
    supersession_status: str
    retired_status: str
    registry_revision: int

    def public_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("restricted_storage_reference", None)
        payload["checksum_prefix"] = self.normalized_catalog_checksum[:12]
        return payload


@dataclass(frozen=True, slots=True)
class CatalogEntitlementRecord:
    entitlement_id: str
    principal_id: str
    tenant_id: str | None
    catalog_version_id: str
    catalog_checksum: str
    operations: tuple[str, ...]
    status: str
    expires_at: str | None
    granted_by: str
    granted_at: str
    revoked_by: str | None
    revoked_at: str | None

    def public_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["catalog_checksum"] = self.catalog_checksum[:12]
        return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_identifier(value: object, *, label: str, maximum: int = 200) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or len(cleaned) > maximum:
        raise ValueError(f"{label} is missing or exceeds its length limit.")
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise ValueError(f"{label} contains unsupported characters.")
    return cleaned


def _bounded_text(value: object | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned[:MAX_AUDIT_TEXT] or None


def _stable_identifier(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}{digest[:28]}"


def _json_dump(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _safe_metadata(value: Mapping[str, Any] | None, *, label: str) -> dict[str, Any]:
    """Validate bounded, definition-free registry metadata.

    Registry metadata is intended for small provider/version capability facts,
    never attribute descriptions or catalog payloads.  The conservative shape
    and byte limits prevent a registration call from turning the registry into
    a second unrestricted catalog store.
    """

    def normalize(item: Any, *, depth: int) -> Any:
        if depth > 4:
            raise ValueError(f"{label} exceeds its nesting limit.")
        if item is None or isinstance(item, (bool, int, float)):
            return item
        if isinstance(item, str):
            cleaned = " ".join(item.split())
            if len(cleaned) > 500:
                raise ValueError(f"{label} contains an oversized text value.")
            return cleaned
        if isinstance(item, Mapping):
            if len(item) > MAX_REGISTRY_METADATA_ITEMS:
                raise ValueError(f"{label} contains too many entries.")
            normalized: dict[str, Any] = {}
            for raw_key, raw_value in item.items():
                key = _clean_identifier(raw_key, label=f"{label} key", maximum=100)
                normalized[key] = normalize(raw_value, depth=depth + 1)
            return normalized
        if isinstance(item, (list, tuple)):
            if len(item) > MAX_REGISTRY_METADATA_ITEMS:
                raise ValueError(f"{label} contains too many entries.")
            return [normalize(child, depth=depth + 1) for child in item]
        raise ValueError(f"{label} contains an unsupported value type.")

    normalized = normalize(dict(value or {}), depth=0)
    if len(canonical_json_bytes(normalized)) > MAX_REGISTRY_METADATA_BYTES:
        raise ValueError(f"{label} exceeds its byte limit.")
    return normalized


def _json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    decoded = json.loads(value)
    return decoded


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp requires a timezone.")
    return parsed.astimezone(timezone.utc)


class CatalogRegistry:
    """SQLite-backed exact version, entitlement, and bounded audit registry."""

    def __init__(
        self,
        restricted_root: str | Path,
        *,
        repository_root: str | Path | None = None,
        database_path: str | Path | None = None,
        registry_root: str | Path | None = None,
    ) -> None:
        self.root = validate_restricted_metadata_root(
            restricted_root,
            repository_root=repository_root,
        )
        if database_path is not None and registry_root is not None:
            raise CatalogRegistryError(
                "Catalog registry database_path and registry_root are mutually exclusive."
            )
        if registry_root is None:
            self.registry_root = self.root
        else:
            self.registry_root = validate_restricted_metadata_root(
                registry_root,
                repository_root=repository_root,
            )
            if (
                self.registry_root == self.root
                or self.registry_root in self.root.parents
                or self.root in self.registry_root.parents
            ):
                raise CatalogRegistryError(
                    "Catalog registry and restricted catalog roots must be disjoint."
                )
        self.database_path = (
            Path(database_path)
            if database_path is not None
            else self.registry_root / REGISTRY_DATABASE_RELATIVE
        )
        if not self.database_path.is_absolute():
            raise CatalogRegistryError("Catalog registry database path must be absolute.")
        database_parent = self.database_path.parent.resolve(strict=False)
        if database_parent != self.registry_root and self.registry_root not in database_parent.parents:
            raise CatalogRegistryError("Catalog registry database must remain under its registry root.")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS catalog_registry_metadata (
              schema_version TEXT PRIMARY KEY,
              created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS bureau_catalog_versions (
              catalog_version_id TEXT PRIMARY KEY,
              catalog_id TEXT NOT NULL,
              provider_id TEXT NOT NULL,
              provider_name TEXT NOT NULL,
              product_id TEXT NOT NULL,
              product_name TEXT NOT NULL,
              edition TEXT NOT NULL,
              country_or_region TEXT NOT NULL,
              source_release_version TEXT NOT NULL,
              source_checksum TEXT NOT NULL,
              normalized_catalog_checksum TEXT NOT NULL,
              record_count INTEGER NOT NULL,
              special_value_definition_count INTEGER NOT NULL,
              supported_bureau_versions_json TEXT NOT NULL,
              provider_availability_metadata_json TEXT NOT NULL,
              leveling_metadata_json TEXT NOT NULL,
              archive_availability_metadata_json TEXT NOT NULL,
              parser_build_version TEXT NOT NULL,
              schema_version TEXT NOT NULL,
              source_provenance_reference TEXT NOT NULL,
              restricted_storage_reference TEXT NOT NULL,
              installation_status TEXT NOT NULL,
              integrity_status TEXT NOT NULL,
              entitlement_classification TEXT NOT NULL,
              created_by TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              supersession_status TEXT NOT NULL,
              retired_status TEXT NOT NULL,
              registry_revision INTEGER NOT NULL,
              UNIQUE(provider_id, product_id, edition, source_release_version),
              UNIQUE(normalized_catalog_checksum)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS bureau_catalog_entitlements (
              entitlement_id TEXT PRIMARY KEY,
              principal_id TEXT NOT NULL,
              tenant_id TEXT,
              catalog_version_id TEXT NOT NULL,
              catalog_checksum TEXT NOT NULL,
              operations_json TEXT NOT NULL,
              status TEXT NOT NULL,
              expires_at TEXT,
              granted_by TEXT NOT NULL,
              granted_at TEXT NOT NULL,
              revoked_by TEXT,
              revoked_at TEXT,
              UNIQUE(principal_id, tenant_id, catalog_version_id),
              FOREIGN KEY(catalog_version_id) REFERENCES bureau_catalog_versions(catalog_version_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS bureau_catalog_access_audit (
              audit_id TEXT PRIMARY KEY,
              actor TEXT NOT NULL,
              catalog_version_id TEXT,
              attribute_code TEXT,
              project_id TEXT,
              action TEXT NOT NULL,
              result_status TEXT NOT NULL,
              correlation_id TEXT NOT NULL,
              safe_detail TEXT,
              server_timestamp TEXT NOT NULL
            )
            """,
            """
            CREATE TRIGGER IF NOT EXISTS bureau_catalog_access_audit_no_update
            BEFORE UPDATE ON bureau_catalog_access_audit
            BEGIN SELECT RAISE(ABORT, 'catalog audit is append only'); END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS bureau_catalog_access_audit_no_delete
            BEFORE DELETE ON bureau_catalog_access_audit
            BEGIN SELECT RAISE(ABORT, 'catalog audit is append only'); END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS bureau_catalog_version_identity_immutable
            BEFORE UPDATE ON bureau_catalog_versions
            WHEN NEW.catalog_id <> OLD.catalog_id
              OR NEW.provider_id <> OLD.provider_id
              OR NEW.product_id <> OLD.product_id
              OR NEW.edition <> OLD.edition
              OR NEW.source_release_version <> OLD.source_release_version
              OR NEW.normalized_catalog_checksum <> OLD.normalized_catalog_checksum
              OR NEW.restricted_storage_reference <> OLD.restricted_storage_reference
            BEGIN SELECT RAISE(ABORT, 'catalog version identity is immutable'); END
            """,
        )
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT OR IGNORE INTO catalog_registry_metadata(schema_version, created_at) VALUES (?, ?)",
                    (REGISTRY_SCHEMA_VERSION, _utc_now()),
                )
                versions = connection.execute(
                    "SELECT schema_version FROM catalog_registry_metadata"
                ).fetchall()
                if [row["schema_version"] for row in versions] != [REGISTRY_SCHEMA_VERSION]:
                    raise CatalogRegistryError("Catalog registry schema version is unsupported.")
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _version_record(row: sqlite3.Row) -> CatalogVersionRecord:
        return CatalogVersionRecord(
            catalog_id=row["catalog_id"],
            catalog_version_id=row["catalog_version_id"],
            provider_id=row["provider_id"],
            provider_name=row["provider_name"],
            product_id=row["product_id"],
            product_name=row["product_name"],
            edition=row["edition"],
            country_or_region=row["country_or_region"],
            source_release_version=row["source_release_version"],
            source_checksum=row["source_checksum"],
            normalized_catalog_checksum=row["normalized_catalog_checksum"],
            record_count=int(row["record_count"]),
            special_value_definition_count=int(row["special_value_definition_count"]),
            supported_bureau_versions=tuple(_json_load(row["supported_bureau_versions_json"], [])),
            provider_availability_metadata=_json_load(row["provider_availability_metadata_json"], {}),
            leveling_metadata=_json_load(row["leveling_metadata_json"], {}),
            archive_availability_metadata=_json_load(row["archive_availability_metadata_json"], {}),
            parser_build_version=row["parser_build_version"],
            schema_version=row["schema_version"],
            source_provenance_reference=row["source_provenance_reference"],
            restricted_storage_reference=row["restricted_storage_reference"],
            installation_status=row["installation_status"],
            integrity_status=row["integrity_status"],
            entitlement_classification=row["entitlement_classification"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            supersession_status=row["supersession_status"],
            retired_status=row["retired_status"],
            registry_revision=int(row["registry_revision"]),
        )

    @staticmethod
    def _entitlement_record(row: sqlite3.Row) -> CatalogEntitlementRecord:
        return CatalogEntitlementRecord(
            entitlement_id=row["entitlement_id"],
            principal_id=row["principal_id"],
            tenant_id=row["tenant_id"],
            catalog_version_id=row["catalog_version_id"],
            catalog_checksum=row["catalog_checksum"],
            operations=tuple(_json_load(row["operations_json"], [])),
            status=row["status"],
            expires_at=row["expires_at"],
            granted_by=row["granted_by"],
            granted_at=row["granted_at"],
            revoked_by=row["revoked_by"],
            revoked_at=row["revoked_at"],
        )

    def register_manifest(
        self,
        manifest: BureauCatalogManifest,
        *,
        storage_reference: str,
        actor: str,
        country_or_region: str = "global",
        supported_bureau_versions: Iterable[str] = (),
        provider_availability_metadata: Mapping[str, Any] | None = None,
        leveling_metadata: Mapping[str, Any] | None = None,
        archive_availability_metadata: Mapping[str, Any] | None = None,
    ) -> CatalogVersionRecord:
        checksum = validate_sha256(manifest.catalog_checksum, field_name="catalog_checksum")
        actor_id = _clean_identifier(actor, label="actor")
        storage_token = _clean_identifier(storage_reference, label="storage_reference")
        if not storage_token.startswith("restricted-catalog:"):
            raise CatalogRegistryError("Catalog storage reference must be opaque and restricted.")
        provider_id = _stable_identifier("provider_", manifest.catalog_key.provider.casefold())
        product_id = _stable_identifier(
            "product_", provider_id, manifest.catalog_key.product.casefold()
        )
        version_id = _stable_identifier(
            "bcv_", manifest.catalog_id, manifest.catalog_key.dictionary_version, checksum
        )
        canonical_sources = tuple(
            item for item in manifest.source_files if item.role == "canonical_pdf"
        )
        if len(canonical_sources) != 1:
            raise CatalogRegistryError(
                "Catalog source provenance requires exactly one canonical_pdf descriptor."
            )
        (source_descriptor,) = canonical_sources
        now = _utc_now()
        values = (
            version_id,
            manifest.catalog_id,
            provider_id,
            manifest.catalog_key.provider,
            product_id,
            manifest.catalog_key.product,
            manifest.catalog_key.edition,
            _clean_identifier(country_or_region, label="country_or_region"),
            manifest.catalog_key.dictionary_version,
            source_descriptor.sha256,
            checksum,
            manifest.attribute_count,
            manifest.special_value_count,
            _json_dump(sorted({_clean_identifier(item, label="supported bureau version") for item in supported_bureau_versions})),
            _json_dump(_safe_metadata(provider_availability_metadata, label="provider availability metadata")),
            _json_dump(_safe_metadata(leveling_metadata, label="leveling metadata")),
            _json_dump(_safe_metadata(archive_availability_metadata, label="archive availability metadata")),
            f"{manifest.builder_name}/{manifest.builder_version}",
            manifest.schema_version,
            "source-sha256:" + source_descriptor.sha256,
            storage_token,
            "installed",
            "verified",
            manifest.license.classification,
            actor_id,
            now,
            now,
            "current",
            "active",
            1,
        )
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    """
                    SELECT * FROM bureau_catalog_versions
                    WHERE provider_id=? AND product_id=? AND edition=? AND source_release_version=?
                    """,
                    (provider_id, product_id, manifest.catalog_key.edition, manifest.catalog_key.dictionary_version),
                ).fetchone()
                if existing is not None:
                    record = self._version_record(existing)
                    if (
                        record.catalog_version_id != version_id
                        or record.normalized_catalog_checksum != checksum
                        or record.record_count != manifest.attribute_count
                        or record.special_value_definition_count != manifest.special_value_count
                        or record.restricted_storage_reference != storage_token
                    ):
                        raise CatalogRegistryConflictError(
                            "The same logical catalog version is registered with different immutable content."
                        )
                    connection.commit()
                    return record
                connection.execute(
                    """
                    INSERT INTO bureau_catalog_versions (
                      catalog_version_id, catalog_id, provider_id, provider_name,
                      product_id, product_name, edition, country_or_region,
                      source_release_version, source_checksum,
                      normalized_catalog_checksum, record_count,
                      special_value_definition_count, supported_bureau_versions_json,
                      provider_availability_metadata_json, leveling_metadata_json,
                      archive_availability_metadata_json, parser_build_version,
                      schema_version, source_provenance_reference,
                      restricted_storage_reference, installation_status,
                      integrity_status, entitlement_classification, created_by,
                      created_at, updated_at, supersession_status, retired_status,
                      registry_revision
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    values,
                )
                row = connection.execute(
                    "SELECT * FROM bureau_catalog_versions WHERE catalog_version_id=?",
                    (version_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise CatalogRegistryError("Catalog registration did not persist.")
                return self._version_record(row)
            except Exception:
                connection.rollback()
                raise

    def get_version(self, catalog_version_id: str) -> CatalogVersionRecord:
        version_id = _clean_identifier(catalog_version_id, label="catalog_version_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM bureau_catalog_versions WHERE catalog_version_id=?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise CatalogRegistryNotFoundError("Exact catalog version is unavailable.")
        return self._version_record(row)

    def get_version_for_exact_catalog(
        self,
        key: BureauCatalogKey,
        checksum: str,
    ) -> CatalogVersionRecord:
        exact_checksum = validate_sha256(checksum, field_name="catalog_checksum")
        provider_id = _stable_identifier("provider_", key.provider.casefold())
        product_id = _stable_identifier("product_", provider_id, key.product.casefold())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM bureau_catalog_versions
                WHERE provider_id=? AND product_id=? AND edition=?
                  AND source_release_version=? AND normalized_catalog_checksum=?
                """,
                (provider_id, product_id, key.edition, key.dictionary_version, exact_checksum),
            ).fetchone()
        if row is None:
            raise CatalogRegistryNotFoundError("Exact catalog version is unavailable.")
        return self._version_record(row)

    def list_versions(self, *, offset: int = 0, limit: int = 25) -> tuple[CatalogVersionRecord, ...]:
        bounded_offset = max(0, int(offset))
        bounded_limit = int(limit)
        if bounded_limit <= 0 or bounded_limit > MAX_PAGE_SIZE:
            raise ValueError(f"Catalog version page size must be between 1 and {MAX_PAGE_SIZE}.")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM bureau_catalog_versions
                ORDER BY provider_name COLLATE NOCASE, product_name COLLATE NOCASE,
                         edition COLLATE NOCASE, source_release_version COLLATE NOCASE,
                         catalog_version_id
                LIMIT ? OFFSET ?
                """,
                (bounded_limit, bounded_offset),
            ).fetchall()
        return tuple(self._version_record(row) for row in rows)

    def grant_entitlement(
        self,
        *,
        principal_id: str,
        tenant_id: str | None,
        catalog_version_id: str,
        operations: Iterable[str],
        granted_by: str,
        expires_at: str | None = None,
    ) -> CatalogEntitlementRecord:
        principal = _clean_identifier(principal_id, label="principal_id")
        tenant = _clean_identifier(tenant_id, label="tenant_id") if tenant_id else None
        version = self.get_version(catalog_version_id)
        normalized_operations = tuple(sorted({_clean_identifier(item, label="operation") for item in operations}))
        if not normalized_operations or not set(normalized_operations).issubset(ALLOWED_ENTITLEMENT_OPERATIONS):
            raise ValueError("Catalog entitlement operations are empty or unsupported.")
        if expires_at is not None and _parse_timestamp(expires_at) <= datetime.now(timezone.utc):
            raise ValueError("Catalog entitlement expiry must be in the future.")
        grantor = _clean_identifier(granted_by, label="granted_by")
        entitlement_id = _stable_identifier(
            "bce_", principal, tenant or "", version.catalog_version_id
        )
        now = _utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO bureau_catalog_entitlements (
                      entitlement_id, principal_id, tenant_id, catalog_version_id,
                      catalog_checksum, operations_json, status, expires_at,
                      granted_by, granted_at, revoked_by, revoked_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL)
                    ON CONFLICT(entitlement_id) DO UPDATE SET
                      operations_json=excluded.operations_json,
                      catalog_checksum=excluded.catalog_checksum,
                      status='active', expires_at=excluded.expires_at,
                      granted_by=excluded.granted_by, granted_at=excluded.granted_at,
                      revoked_by=NULL, revoked_at=NULL
                    """,
                    (
                        entitlement_id,
                        principal,
                        tenant,
                        version.catalog_version_id,
                        version.normalized_catalog_checksum,
                        _json_dump(normalized_operations),
                        "active",
                        expires_at,
                        grantor,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM bureau_catalog_entitlements WHERE entitlement_id=?",
                    (entitlement_id,),
                ).fetchone()
                connection.commit()
                if row is None:
                    raise CatalogRegistryError("Catalog entitlement did not persist.")
                return self._entitlement_record(row)
            except Exception:
                connection.rollback()
                raise

    def revoke_entitlement(
        self,
        entitlement_id: str,
        *,
        revoked_by: str,
    ) -> CatalogEntitlementRecord:
        exact_id = _clean_identifier(entitlement_id, label="entitlement_id")
        actor = _clean_identifier(revoked_by, label="revoked_by")
        now = _utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                changed = connection.execute(
                    """
                    UPDATE bureau_catalog_entitlements
                    SET status='revoked', revoked_by=?, revoked_at=?
                    WHERE entitlement_id=? AND status='active'
                    """,
                    (actor, now, exact_id),
                ).rowcount
                row = connection.execute(
                    "SELECT * FROM bureau_catalog_entitlements WHERE entitlement_id=?",
                    (exact_id,),
                ).fetchone()
                if changed != 1 or row is None:
                    raise CatalogRegistryNotFoundError("Active catalog entitlement is unavailable.")
                connection.commit()
                return self._entitlement_record(row)
            except Exception:
                connection.rollback()
                raise

    def get_entitlement(self, entitlement_id: str) -> CatalogEntitlementRecord:
        exact_id = _clean_identifier(entitlement_id, label="entitlement_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM bureau_catalog_entitlements WHERE entitlement_id=?",
                (exact_id,),
            ).fetchone()
        if row is None:
            raise CatalogRegistryNotFoundError(
                "Exact catalog entitlement is unavailable."
            )
        return self._entitlement_record(row)

    def entitlement_for(
        self,
        *,
        principal_id: str,
        tenant_id: str | None,
        catalog_version_id: str,
        operation: str,
    ) -> CatalogEntitlementRecord:
        principal = _clean_identifier(principal_id, label="principal_id")
        version_id = _clean_identifier(catalog_version_id, label="catalog_version_id")
        exact_operation = _clean_identifier(operation, label="operation")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM bureau_catalog_entitlements
                WHERE principal_id=?
                  AND ((tenant_id IS NULL AND ? IS NULL) OR tenant_id=?)
                  AND catalog_version_id=? AND status='active'
                """,
                (principal, tenant_id, tenant_id, version_id),
            ).fetchone()
        if row is None:
            raise BureauCatalogAccessDeniedError("Bureau catalog access is not authorized.")
        entitlement = self._entitlement_record(row)
        if exact_operation not in entitlement.operations:
            raise BureauCatalogAccessDeniedError("Bureau catalog access is not authorized.")
        if entitlement.expires_at and _parse_timestamp(entitlement.expires_at) <= datetime.now(timezone.utc):
            raise BureauCatalogAccessDeniedError("Bureau catalog entitlement has expired.")
        return entitlement

    def list_entitlements(
        self,
        *,
        catalog_version_id: str | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[CatalogEntitlementRecord, ...]:
        """Return a bounded administrative entitlement inventory."""

        bounded_offset = max(0, int(offset))
        bounded_limit = int(limit)
        if bounded_limit <= 0 or bounded_limit > MAX_PAGE_SIZE:
            raise ValueError(
                f"Catalog entitlement page size must be between 1 and {MAX_PAGE_SIZE}."
            )
        parameters: tuple[object, ...]
        if catalog_version_id is None:
            where = ""
            parameters = (bounded_limit, bounded_offset)
        else:
            exact_id = _clean_identifier(
                catalog_version_id, label="catalog_version_id"
            )
            where = "WHERE catalog_version_id=?"
            parameters = (exact_id, bounded_limit, bounded_offset)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM bureau_catalog_entitlements
                {where}
                ORDER BY catalog_version_id, principal_id COLLATE NOCASE,
                         COALESCE(tenant_id, ''), entitlement_id
                LIMIT ? OFFSET ?
                """,
                parameters,
            ).fetchall()
        return tuple(self._entitlement_record(row) for row in rows)

    def list_entitled_versions(
        self,
        *,
        principal_id: str,
        tenant_id: str | None,
        operation: str = "catalog_health",
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[CatalogVersionRecord, ...]:
        bounded_limit = int(limit)
        bounded_offset = max(0, int(offset))
        if bounded_limit <= 0 or bounded_limit > MAX_PAGE_SIZE:
            raise ValueError(f"Catalog version page size must be between 1 and {MAX_PAGE_SIZE}.")
        principal = _clean_identifier(principal_id, label="principal_id")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT v.*, e.operations_json, e.expires_at
                FROM bureau_catalog_versions v
                JOIN bureau_catalog_entitlements e ON e.catalog_version_id=v.catalog_version_id
                WHERE e.principal_id=?
                  AND ((e.tenant_id IS NULL AND ? IS NULL) OR e.tenant_id=?)
                  AND e.status='active' AND v.retired_status='active'
                ORDER BY v.provider_name COLLATE NOCASE, v.product_name COLLATE NOCASE,
                         v.edition COLLATE NOCASE, v.source_release_version COLLATE NOCASE,
                         v.catalog_version_id
                """,
                (principal, tenant_id, tenant_id),
            ).fetchall()
        now = datetime.now(timezone.utc)
        authorized = []
        for row in rows:
            operations = tuple(_json_load(row["operations_json"], []))
            expiry = row["expires_at"]
            if operation not in operations or (expiry and _parse_timestamp(expiry) <= now):
                continue
            authorized.append(self._version_record(row))
        return tuple(authorized[bounded_offset : bounded_offset + bounded_limit])

    def retire_version(
        self,
        catalog_version_id: str,
        *,
        actor: str,
        expected_revision: int,
    ) -> CatalogVersionRecord:
        version_id = _clean_identifier(catalog_version_id, label="catalog_version_id")
        _clean_identifier(actor, label="actor")
        now = _utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                changed = connection.execute(
                    """
                    UPDATE bureau_catalog_versions
                    SET retired_status='retired', supersession_status='retired',
                        updated_at=?, registry_revision=registry_revision+1
                    WHERE catalog_version_id=? AND registry_revision=? AND retired_status='active'
                    """,
                    (now, version_id, int(expected_revision)),
                ).rowcount
                if changed != 1:
                    raise CatalogRegistryConflictError(
                        "Catalog version changed or is already retired."
                    )
                row = connection.execute(
                    "SELECT * FROM bureau_catalog_versions WHERE catalog_version_id=?",
                    (version_id,),
                ).fetchone()
                connection.commit()
                return self._version_record(row)
            except Exception:
                connection.rollback()
                raise

    def set_integrity_status(
        self,
        catalog_version_id: str,
        *,
        status: str,
    ) -> CatalogVersionRecord:
        exact_status = _clean_identifier(status, label="integrity_status")
        if exact_status not in {"verified", "failed", "unknown"}:
            raise ValueError("Catalog integrity status is unsupported.")
        version_id = _clean_identifier(catalog_version_id, label="catalog_version_id")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                changed = connection.execute(
                    """
                    UPDATE bureau_catalog_versions
                    SET integrity_status=?, updated_at=?, registry_revision=registry_revision+1
                    WHERE catalog_version_id=?
                    """,
                    (exact_status, _utc_now(), version_id),
                ).rowcount
                if changed != 1:
                    raise CatalogRegistryNotFoundError("Exact catalog version is unavailable.")
                row = connection.execute(
                    "SELECT * FROM bureau_catalog_versions WHERE catalog_version_id=?",
                    (version_id,),
                ).fetchone()
                connection.commit()
                return self._version_record(row)
            except Exception:
                connection.rollback()
                raise

    def record_access_audit(
        self,
        *,
        actor: str,
        action: str,
        result_status: str,
        correlation_id: str,
        catalog_version_id: str | None = None,
        attribute_code: str | None = None,
        project_id: str | None = None,
        safe_detail: str | None = None,
    ) -> None:
        record = (
            "bca_" + uuid.uuid4().hex,
            _clean_identifier(actor, label="actor"),
            _bounded_text(catalog_version_id),
            _bounded_text(attribute_code),
            _bounded_text(project_id),
            _clean_identifier(action, label="action"),
            _clean_identifier(result_status, label="result_status"),
            _clean_identifier(correlation_id, label="correlation_id"),
            _bounded_text(safe_detail),
            _utc_now(),
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO bureau_catalog_access_audit (
                  audit_id, actor, catalog_version_id, attribute_code, project_id,
                  action, result_status, correlation_id, safe_detail, server_timestamp
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                record,
            )


class RegistryEntitlementProvider(BureauCatalogEntitlementProvider):
    """Exact entitlement adapter used by :class:`BureauCatalogService`."""

    def __init__(self, registry: CatalogRegistry) -> None:
        self.registry = registry

    def authorize(
        self,
        context: BureauCatalogAccessContext,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
        operation: CatalogOperation,
    ) -> BureauCatalogAccessGrant:
        version = self.registry.get_version_for_exact_catalog(
            catalog_key, catalog_checksum
        )
        if version.retired_status != "active" or version.integrity_status != "verified":
            raise BureauCatalogAccessDeniedError("Bureau catalog access is not authorized.")
        entitlement = self.registry.entitlement_for(
            principal_id=context.principal_id,
            tenant_id=context.tenant_id,
            catalog_version_id=version.catalog_version_id,
            operation=operation,
        )
        return BureauCatalogAccessGrant(
            grant_id=entitlement.entitlement_id,
            principal_id=context.principal_id,
            tenant_id=context.tenant_id,
            catalog_key=catalog_key,
            catalog_checksum=version.normalized_catalog_checksum,
            operation=operation,
            expires_at=entitlement.expires_at,
        )


__all__ = [
    "ALLOWED_ENTITLEMENT_OPERATIONS",
    "CatalogEntitlementRecord",
    "CatalogRegistry",
    "CatalogRegistryConflictError",
    "CatalogRegistryError",
    "CatalogRegistryNotFoundError",
    "CatalogVersionRecord",
    "MAX_PAGE_SIZE",
    "MAX_REGISTRY_METADATA_BYTES",
    "REGISTRY_DATABASE_RELATIVE",
    "REGISTRY_SCHEMA_VERSION",
    "RegistryEntitlementProvider",
]

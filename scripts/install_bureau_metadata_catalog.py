"""Install and register one exact restricted bureau metadata catalog.

This local administration command never enumerates catalogs, prints vendor
content, or returns a physical path on stdout.  The explicit path is retained
only in a restricted acceptance record beneath the selected durable root.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

from pydantic import ValidationError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.bureau_metadata.catalog_registry import (  # noqa: E402
    ALLOWED_ENTITLEMENT_OPERATIONS,
    CatalogRegistry,
)
from server.bureau_metadata.catalog_store import (  # noqa: E402
    BureauCatalogStore,
    CATALOG_MANIFEST_FILE,
)
from server.bureau_metadata.restricted_storage import (  # noqa: E402
    RestrictedCatalogInstaller,
    RestrictedStorageError,
    validate_restricted_metadata_root,
)
from server.bureau_metadata.types import BureauCatalogManifest  # noqa: E402


MAX_MANIFEST_BYTES = 2 * 1024 * 1024
CATALOG_ADMINISTRATOR_ROLE = "catalog-administrator"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_source_manifest(source: Path) -> BureauCatalogManifest:
    path = source / CATALOG_MANIFEST_FILE
    try:
        payload = path.read_bytes()
        if len(payload) > MAX_MANIFEST_BYTES:
            raise ValueError("manifest exceeds read limit")
        return BureauCatalogManifest.model_validate_json(payload)
    except (OSError, ValueError, ValidationError) as exc:
        raise RestrictedStorageError("Exact source manifest is invalid.") from exc


def _create_explicit_root(candidate: Path) -> Path:
    checked = validate_restricted_metadata_root(
        candidate,
        repository_root=REPOSITORY_ROOT,
        require_exists=False,
    )
    checked.mkdir(parents=False, exist_ok=False)
    return validate_restricted_metadata_root(
        checked,
        repository_root=REPOSITORY_ROOT,
    )


def _acceptance_record(
    *,
    root: Path,
    source: Path,
    version_id: str,
    catalog_id: str,
    checksum: str,
    attribute_count: int,
    special_value_count: int,
    actor: str,
    acl_status: str,
) -> Path:
    acceptance_root = root / "acceptance"
    acceptance_root.mkdir(parents=True, exist_ok=True)
    path = acceptance_root / (
        "catalog-installation-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + ".json"
    )
    payload = {
        "schema_version": "1.0",
        "record_type": "restricted_local_catalog_installation",
        "catalog_id": catalog_id,
        "catalog_version_id": version_id,
        "catalog_checksum": checksum,
        "attribute_count": attribute_count,
        "special_value_definition_count": special_value_count,
        "restricted_storage_location": str(root),
        "source_preserved_at": str(source),
        "source_deleted_or_moved": False,
        "actor": actor,
        "actor_role": CATALOG_ADMINISTRATOR_ROLE,
        "acl_inspection_status": acl_status,
        "installed_at": _utc_now(),
        "physical_path_publicly_exposed": False,
        "vendor_content_logged": False,
    }
    encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    staging = path.with_name("." + path.name + ".staging-" + uuid.uuid4().hex)
    with staging.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staging, path)
    return path


def install_and_register(args: argparse.Namespace) -> dict[str, object]:
    if args.actor_role != CATALOG_ADMINISTRATOR_ROLE:
        raise PermissionError("Catalog installation requires the catalog administrator role.")
    source = Path(args.source_exact_directory).expanduser().resolve(strict=True)
    requested_root = Path(args.restricted_root).expanduser()
    if not requested_root.is_absolute():
        raise RestrictedStorageError("Restricted root must be an explicit absolute path.")
    if requested_root.exists():
        root = validate_restricted_metadata_root(
            requested_root, repository_root=REPOSITORY_ROOT
        )
    elif args.create_root:
        root = _create_explicit_root(requested_root)
    else:
        raise RestrictedStorageError(
            "Restricted root does not exist; use --create-root for an explicit new directory."
        )

    manifest = _read_source_manifest(source)
    installer = RestrictedCatalogInstaller(root, repository_root=REPOSITORY_ROOT)
    installed = installer.install(
        source,
        expected_catalog_checksum=args.expected_catalog_checksum,
        expected_attribute_count=args.expected_attribute_count,
        expected_special_value_count=args.expected_special_value_count,
        actor=args.actor,
    )
    loaded = BureauCatalogStore(root, repository_root=REPOSITORY_ROOT).load_exact(
        manifest.catalog_key, manifest.catalog_checksum
    )
    supported_versions = sorted(
        {
            version
            for attribute in loaded.attributes_by_code.values()
            for version in attribute.applicable_versions
        }
    )
    provider_availability = {
        "attributes_with_cross_bureau_availability": sum(
            bool(attribute.cross_bureau_availability)
            for attribute in loaded.attributes_by_code.values()
        )
    }
    leveling = {
        "attributes_with_leveling_indicator": sum(
            bool(attribute.leveling_indicator)
            for attribute in loaded.attributes_by_code.values()
        )
    }
    archive = {
        "attributes_with_archive_indicator": sum(
            bool(attribute.archive_indicator)
            for attribute in loaded.attributes_by_code.values()
        )
    }
    registry = CatalogRegistry(root, repository_root=REPOSITORY_ROOT)
    version = registry.register_manifest(
        manifest,
        storage_reference=installed.storage_reference,
        actor=args.actor,
        country_or_region=args.country_or_region,
        supported_bureau_versions=supported_versions,
        provider_availability_metadata=provider_availability,
        leveling_metadata=leveling,
        archive_availability_metadata=archive,
    )
    registry.grant_entitlement(
        principal_id=args.actor,
        tenant_id=args.tenant_id,
        catalog_version_id=version.catalog_version_id,
        operations=ALLOWED_ENTITLEMENT_OPERATIONS,
        granted_by=args.actor,
    )
    _acceptance_record(
        root=root,
        source=source,
        version_id=version.catalog_version_id,
        catalog_id=version.catalog_id,
        checksum=version.normalized_catalog_checksum,
        attribute_count=version.record_count,
        special_value_count=version.special_value_definition_count,
        actor=args.actor,
        acl_status=installer.acl_assessment.status,
    )
    return {
        "ok": True,
        "catalog_id": version.catalog_id,
        "catalog_version_id": version.catalog_version_id,
        "catalog_checksum": version.normalized_catalog_checksum,
        "attribute_count": version.record_count,
        "special_value_definition_count": version.special_value_definition_count,
        "installation_status": version.installation_status,
        "integrity_status": version.integrity_status,
        "idempotent": installed.idempotent,
        "acl_inspection_status": installer.acl_assessment.status,
        "source_deleted_or_moved": False,
        "physical_path_publicly_exposed": False,
        "vendor_content_logged": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-exact-directory", type=Path, required=True)
    parser.add_argument("--restricted-root", type=Path, required=True)
    parser.add_argument("--expected-catalog-checksum", required=True)
    parser.add_argument("--expected-attribute-count", type=int, required=True)
    parser.add_argument("--expected-special-value-count", type=int, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--actor-role", choices=(CATALOG_ADMINISTRATOR_ROLE,), required=True)
    parser.add_argument("--tenant-id")
    parser.add_argument("--country-or-region", default="global")
    parser.add_argument("--create-root", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = install_and_register(args)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": "catalog installation failed; inspect restricted local diagnostics",
                    "physical_path_publicly_exposed": False,
                    "vendor_content_logged": False,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

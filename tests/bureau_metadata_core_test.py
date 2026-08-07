from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any
import uuid

import pytest
from pydantic import ValidationError

from server.bureau_metadata.catalog_service import (
    BureauCatalogAccessDeniedError,
    BureauCatalogService,
)
from server.bureau_metadata.catalog_store import (
    BureauCatalogIntegrityError,
    BureauCatalogLoader,
    BureauCatalogNotFoundError,
    BureauCatalogRootError,
    BureauCatalogStore,
)
from server.bureau_metadata.normalizer import (
    canonical_json_bytes,
    catalog_relative_directory,
)
from server.bureau_metadata.types import (
    BureauAttributeDefinition,
    BureauCatalogAccessContext,
    BureauCatalogAccessGrant,
    BureauCatalogFileDescriptor,
    BureauCatalogKey,
    BureauCatalogLicenseMetadata,
    BureauCatalogManifest,
    BureauSourceReference,
    BureauSpecialValueDefinition,
)
from server.bureau_metadata.validation import (
    attribute_record_checksum,
    catalog_governance_payload,
    calculate_catalog_checksum,
    special_definition_checksum,
    special_definition_id,
)


def _jsonl(records: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(record) + b"\n" for record in records)


def _descriptor(path: Path, count: int) -> BureauCatalogFileDescriptor:
    payload = path.read_bytes()
    return BureauCatalogFileDescriptor(
        relative_path=path.name,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        record_count=count,
    )


def _publish_synthetic_catalog(
    root: Path,
    *,
    allowed_operations: frozenset[str] | None = None,
) -> tuple[BureauCatalogKey, str, Path]:
    key = BureauCatalogKey(
        provider="Synthetic Bureau",
        product="Synthetic Attributes",
        edition="Test",
        dictionary_version="1.0",
    )
    source = BureauSourceReference(
        source_document_sha256="a" * 64,
        source_locator="synthetic:1",
        extraction_method="manual_review",
    )
    attributes: list[dict[str, Any]] = [
        {
            "catalog_key": key.model_dump(mode="json"),
            "sequence": 1,
            "attribute_code": "ATTR_A",
            "description": "Attribute-specific special semantics",
            "numeric_type": "integer",
            "ordinary_min": "0",
            "ordinary_max": "100",
            "source_references": [source.model_dump(mode="json")],
            "created_at": "2026-08-04T00:00:00Z",
        },
        {
            "catalog_key": key.model_dump(mode="json"),
            "sequence": 2,
            "attribute_code": "ATTR_B",
            "description": "The same observed number is ordinary here",
            "numeric_type": "integer",
            "ordinary_min": "0",
            "ordinary_max": "200",
            "source_references": [source.model_dump(mode="json")],
            "created_at": "2026-08-04T00:00:00Z",
        },
    ]
    special_identity = {
        "catalog_key": key.model_dump(mode="json"),
        "attribute_code": "ATTR_A",
        "value_code": "98",
    }
    specials: list[dict[str, Any]] = [
        {
            **special_identity,
            "meaning": "Synthetic attribute-specific exception",
            "definition_id": special_definition_id(special_identity),
            "source_references": [source.model_dump(mode="json")],
        }
    ]
    resolved_allowed_operations = allowed_operations
    if resolved_allowed_operations is None:
        resolved_allowed_operations = frozenset(
            {
                "catalog_health",
                "manifest_read",
                "attribute_lookup",
                "special_value_lookup",
                "value_classification",
            }
        )
    license_metadata = BureauCatalogLicenseMetadata(
        policy_id="synthetic-policy",
        policy_version="1",
        allowed_operations=resolved_allowed_operations,
    )
    checksum = calculate_catalog_checksum(
        schema_version="1.0",
        catalog_key=key,
        attributes=attributes,
        special_values=specials,
        reconciliation_findings=[],
        governance=catalog_governance_payload(
            license_metadata=license_metadata,
            restricted_export=True,
            full_catalog_path=".",
        ),
    )
    for record in attributes:
        record["catalog_checksum"] = checksum
        record["record_checksum"] = attribute_record_checksum(record)
    for record in specials:
        record["catalog_checksum"] = checksum
        record["definition_checksum"] = special_definition_checksum(record)
    typed_attributes = [
        BureauAttributeDefinition.model_validate(record).model_dump(mode="json")
        for record in attributes
    ]
    typed_specials = [
        BureauSpecialValueDefinition.model_validate(record).model_dump(mode="json")
        for record in specials
    ]

    relative = catalog_relative_directory(key, checksum)
    directory = root.joinpath(*relative.parts)
    directory.mkdir(parents=True)
    attribute_path = directory / "attribute_definitions.jsonl"
    special_path = directory / "special_value_definitions.jsonl"
    attribute_path.write_bytes(_jsonl(typed_attributes))
    special_path.write_bytes(_jsonl(typed_specials))
    manifest = BureauCatalogManifest(
        catalog_id="bureau-catalog-key-synthetic",
        catalog_key=key,
        catalog_checksum=checksum,
        attribute_file=_descriptor(attribute_path, len(typed_attributes)),
        special_value_file=_descriptor(special_path, len(typed_specials)),
        attribute_count=len(typed_attributes),
        special_value_count=len(typed_specials),
        validation_status="passed",
        license=license_metadata,
        builder_name="synthetic-test-builder",
        builder_version="1",
        built_at="2026-08-04T00:00:00Z",
        built_by="test-actor",
        source_control_commit="synthetic",
    )
    (directory / "catalog_manifest.json").write_bytes(
        canonical_json_bytes(manifest.model_dump(mode="json"))
    )
    return key, checksum, directory


def _synthetic_store(root: Path) -> BureauCatalogStore:
    # Tests may be forced under the repository's ignored .tmp directory by a
    # constrained runner. Production construction has no override and rejects
    # that location; the injected marker isolates only this synthetic fixture.
    synthetic_repository = root.parent / f"{root.name}-repository-marker"
    synthetic_repository.mkdir(exist_ok=True)
    return BureauCatalogStore(root, repository_root=synthetic_repository)


@pytest.fixture
def catalog_test_root() -> Path:
    base = Path(__file__).resolve().parents[1] / ".tmp"
    base.mkdir(exist_ok=True)
    root = base / f"bureau-metadata-core-{uuid.uuid4().hex}"
    marker = root.parent / f"{root.name}-repository-marker"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(marker, ignore_errors=True)


class _ExactGrantProvider:
    def authorize(self, context, catalog_key, catalog_checksum, operation):
        return BureauCatalogAccessGrant(
            grant_id="synthetic-grant",
            principal_id=context.principal_id,
            tenant_id=context.tenant_id,
            catalog_key=catalog_key,
            catalog_checksum=catalog_checksum,
            operation=operation,
            expires_at="2099-01-01T00:00:00Z",
        )


def test_catalog_codes_are_strings_and_contracts_are_frozen() -> None:
    key = BureauCatalogKey(
        provider="P", product="X", edition="E", dictionary_version="1"
    )
    with pytest.raises(ValidationError):
        BureauSpecialValueDefinition(
            catalog_key=key,
            catalog_checksum="a" * 64,
            attribute_code="A",
            value_code=98,
            meaning="Invalid numeric input",
            definition_id="d",
            definition_checksum="b" * 64,
        )
    with pytest.raises(ValidationError):
        key.provider = "Changed"


def test_catalog_governance_payload_orders_allowed_operations_deterministically() -> None:
    license_metadata = BureauCatalogLicenseMetadata(
        policy_id="synthetic-policy",
        policy_version="1",
        allowed_operations=frozenset(
            {"value_classification", "catalog_health", "attribute_lookup"}
        ),
    )

    governance = catalog_governance_payload(
        license_metadata=license_metadata,
        restricted_export=True,
        full_catalog_path=".",
    )

    assert governance["license"]["allowed_operations"] == [
        "attribute_lookup",
        "catalog_health",
        "value_classification",
    ]


def test_exact_classification_is_attribute_specific_and_mutually_exclusive(
    catalog_test_root: Path,
) -> None:
    key, checksum, _ = _publish_synthetic_catalog(catalog_test_root)
    loader = BureauCatalogLoader(_synthetic_store(catalog_test_root))
    service = BureauCatalogService(loader, _ExactGrantProvider())
    context = BureauCatalogAccessContext(principal_id="test-user")

    special = service.classify_value_exact(context, key, checksum, "ATTR_A", 98)
    ordinary = service.classify_value_exact(
        context,
        key,
        checksum,
        "ATTR_B",
        98,
        ordinary_outlier_upper="90",
    )
    assert special.classification == "bureau_special"
    assert special.ordinary_outlier is False
    assert ordinary.classification == "ordinary_valid"
    assert ordinary.ordinary_outlier is True
    assert service.classify_value_exact(
        context, key, checksum, "ATTR_B", None
    ).classification == "true_null"
    assert service.classify_value_exact(
        context, key, checksum, "ATTR_B", "not-a-number"
    ).classification == "parse_failure"
    assert service.classify_value_exact(
        context, key, checksum, "ATTR_B", 300
    ).classification == "unexpected_invalid"
    definition = service.get_special_value_exact(
        context, key, checksum, "ATTR_A", "98"
    )
    assert definition.is_bureau_special is True
    assert definition.is_true_null is False
    assert definition.is_parse_failure is False
    assert definition.is_ordinary_outlier is False
    assert definition.analyst_review_required is True

    unresolved = service.resolve_attribute_exact(
        context, key, checksum, "UNKNOWN_ATTRIBUTE"
    )
    assert unresolved.status == "unresolved"
    assert unresolved.reason == "unknown_attribute_code"
    assert unresolved.attribute is None


def test_access_fails_closed_before_cache_or_catalog_use(catalog_test_root: Path) -> None:
    key, checksum, _ = _publish_synthetic_catalog(catalog_test_root)
    service = BureauCatalogService(
        BureauCatalogLoader(_synthetic_store(catalog_test_root))
    )
    with pytest.raises(BureauCatalogAccessDeniedError):
        service.get_attribute_exact(
            BureauCatalogAccessContext(principal_id="test-user"),
            key,
            checksum,
            "ATTR_A",
        )


def test_loader_has_no_latest_fallback_and_rejects_corruption(
    catalog_test_root: Path,
) -> None:
    key, checksum, directory = _publish_synthetic_catalog(catalog_test_root)
    store = _synthetic_store(catalog_test_root)
    with pytest.raises(BureauCatalogNotFoundError):
        store.load_exact(key, "f" * 64)

    attribute_path = directory / "attribute_definitions.jsonl"
    attribute_path.write_bytes(attribute_path.read_bytes() + b" ")
    with pytest.raises(BureauCatalogIntegrityError):
        BureauCatalogLoader(store).load_exact(key, checksum)


@pytest.mark.parametrize(
    ("license_field", "replacement"),
    (("policy_version", "tampered"), ("public_demo_allowed", True)),
)
def test_license_governance_is_checksum_bound_and_restrictive(
    catalog_test_root: Path,
    license_field: str,
    replacement: object,
) -> None:
    key, checksum, directory = _publish_synthetic_catalog(catalog_test_root)
    manifest_path = directory / "catalog_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["license"][license_field] = replacement
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(BureauCatalogIntegrityError):
        BureauCatalogLoader(_synthetic_store(catalog_test_root)).load_exact(
            key,
            checksum,
        )


def test_external_root_and_cache_are_bounded_and_safe(
    catalog_test_root: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    with pytest.raises(BureauCatalogRootError):
        BureauCatalogStore(repository_root)

    key, checksum, _ = _publish_synthetic_catalog(catalog_test_root)
    loader = BureauCatalogLoader(_synthetic_store(catalog_test_root), max_entries=1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        loaded = list(pool.map(lambda _: loader.load_exact(key, checksum), range(8)))
    assert all(item is loaded[0] for item in loaded)
    assert loader.cache_size() == 1
    assert not hasattr(loader, "load_latest")
    assert not hasattr(loader, "list_catalogs")
    assert not hasattr(BureauCatalogService, "export_catalog")

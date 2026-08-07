from __future__ import annotations

from pathlib import Path

import pytest

from server.bureau_metadata import catalog_registry, operational_service
from server.bureau_metadata.catalog_registry import (
    CatalogRegistry,
    CatalogRegistryError,
    REGISTRY_DATABASE_RELATIVE,
)
from server.bureau_metadata.operational_service import (
    CATALOG_REGISTRY_ROOT_ENV,
    OperationalCatalogService,
    clear_operational_catalog_service_cache,
    get_operational_catalog_service,
)
from server.bureau_metadata.restricted_storage import RESTRICTED_ROOT_ENV
from server.bureau_metadata.types import (
    BureauCatalogFileDescriptor,
    BureauCatalogKey,
    BureauCatalogLicenseMetadata,
    BureauCatalogManifest,
    BureauCatalogSourceDescriptor,
)
from tests.hermetic_test_roots import temporary_test_root


@pytest.fixture
def writable_tmp_path() -> Path:
    with temporary_test_root(
        "bureau-registry-root-",
        scope="bureau-registry-root-fixtures",
    ) as root:
        yield root


def _allow_exact_roots(monkeypatch: pytest.MonkeyPatch, *roots: Path) -> None:
    allowed = {root.resolve(strict=True) for root in roots}

    def validate(root: str | Path | None, **_kwargs) -> Path:
        candidate = Path(str(root or "")).resolve(strict=True)
        if candidate not in allowed:
            raise RuntimeError("unexpected isolated test root")
        return candidate

    monkeypatch.setattr(catalog_registry, "validate_restricted_metadata_root", validate)
    monkeypatch.setattr(operational_service, "validate_restricted_metadata_root", validate)


def _source_descriptor(
    role: str,
    *,
    checksum: str,
) -> BureauCatalogSourceDescriptor:
    suffix = ".pdf" if role == "canonical_pdf" else ".csv"
    return BureauCatalogSourceDescriptor(
        role=role,
        filename=f"synthetic-source{suffix}",
        suffix=suffix,
        sha256=checksum,
        size_bytes=1,
    )


def _manifest(
    *source_files: BureauCatalogSourceDescriptor,
) -> BureauCatalogManifest:
    return BureauCatalogManifest(
        catalog_id="synthetic-catalog",
        catalog_key=BureauCatalogKey(
            provider="Synthetic Bureau",
            product="Synthetic Product",
            edition="Test",
            dictionary_version="1.0",
        ),
        catalog_checksum="c" * 64,
        attribute_file=BureauCatalogFileDescriptor(
            relative_path="attribute_definitions.jsonl",
            sha256="d" * 64,
            size_bytes=1,
            record_count=1,
        ),
        special_value_file=BureauCatalogFileDescriptor(
            relative_path="special_value_definitions.jsonl",
            sha256="e" * 64,
            size_bytes=1,
            record_count=0,
        ),
        source_files=source_files,
        attribute_count=1,
        special_value_count=0,
        validation_status="passed",
        license=BureauCatalogLicenseMetadata(
            policy_id="synthetic-policy",
            policy_version="1",
        ),
        builder_name="synthetic-builder",
        builder_version="1",
        built_at="2026-08-06T00:00:00Z",
        built_by="synthetic-actor",
        source_control_commit="synthetic",
    )


def test_registry_root_defaults_to_the_restricted_catalog_root(
    writable_tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restricted_root = writable_tmp_path / "restricted-catalog"
    restricted_root.mkdir()
    _allow_exact_roots(monkeypatch, restricted_root)

    registry = CatalogRegistry(restricted_root)

    assert registry.registry_root == restricted_root
    assert registry.database_path == restricted_root / REGISTRY_DATABASE_RELATIVE
    assert registry.database_path.is_file()


def test_registration_uses_the_exact_canonical_pdf_provenance_descriptor(
    writable_tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restricted_root = writable_tmp_path / "restricted-catalog"
    restricted_root.mkdir()
    _allow_exact_roots(monkeypatch, restricted_root)
    registry = CatalogRegistry(restricted_root)
    canonical_checksum = "a" * 64
    manifest = _manifest(
        _source_descriptor("csv_staging", checksum="b" * 64),
        _source_descriptor("canonical_pdf", checksum=canonical_checksum),
    )

    record = registry.register_manifest(
        manifest,
        storage_reference="restricted-catalog:" + "f" * 32,
        actor="synthetic-administrator",
    )

    assert record.source_checksum == canonical_checksum
    assert record.source_provenance_reference == f"source-sha256:{canonical_checksum}"


def test_registration_rejects_missing_canonical_pdf_provenance_descriptor(
    writable_tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restricted_root = writable_tmp_path / "restricted-catalog"
    restricted_root.mkdir()
    _allow_exact_roots(monkeypatch, restricted_root)
    registry = CatalogRegistry(restricted_root)
    manifest = _manifest(
        _source_descriptor("csv_staging", checksum="b" * 64),
    )

    with pytest.raises(CatalogRegistryError, match="exactly one canonical_pdf"):
        registry.register_manifest(
            manifest,
            storage_reference="restricted-catalog:" + "f" * 32,
            actor="synthetic-administrator",
        )

    assert registry.list_versions() == ()


def test_registry_root_can_be_a_disjoint_durable_authority(
    writable_tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restricted_root = writable_tmp_path / "restricted-catalog"
    registry_root = writable_tmp_path / "catalog-registry"
    restricted_root.mkdir()
    registry_root.mkdir()
    _allow_exact_roots(monkeypatch, restricted_root, registry_root)

    service = OperationalCatalogService(
        restricted_root,
        registry_root=registry_root,
    )

    assert service.root == restricted_root
    assert service.registry.registry_root == registry_root
    assert service.registry.database_path == registry_root / REGISTRY_DATABASE_RELATIVE
    assert service.registry.database_path.is_file()
    assert not (restricted_root / REGISTRY_DATABASE_RELATIVE).exists()


def test_explicit_registry_root_rejects_overlap_and_database_path_conflict(
    writable_tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restricted_root = writable_tmp_path / "restricted-catalog"
    nested_root = restricted_root / "registry-authority"
    restricted_root.mkdir()
    nested_root.mkdir()
    _allow_exact_roots(monkeypatch, restricted_root, nested_root)

    with pytest.raises(CatalogRegistryError, match="must be disjoint"):
        CatalogRegistry(restricted_root, registry_root=nested_root)

    with pytest.raises(CatalogRegistryError, match="mutually exclusive"):
        CatalogRegistry(
            restricted_root,
            registry_root=nested_root,
            database_path=restricted_root / "explicit.sqlite3",
        )


def test_operational_service_cache_keys_both_authorities(
    writable_tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restricted_root = writable_tmp_path / "restricted-catalog"
    first_registry_root = writable_tmp_path / "catalog-registry-one"
    second_registry_root = writable_tmp_path / "catalog-registry-two"
    for root in (restricted_root, first_registry_root, second_registry_root):
        root.mkdir()
    _allow_exact_roots(
        monkeypatch,
        restricted_root,
        first_registry_root,
        second_registry_root,
    )
    monkeypatch.setenv(RESTRICTED_ROOT_ENV, str(restricted_root))
    monkeypatch.setenv(CATALOG_REGISTRY_ROOT_ENV, str(first_registry_root))
    clear_operational_catalog_service_cache()
    try:
        first = get_operational_catalog_service()
        assert first.registry.registry_root == first_registry_root

        monkeypatch.setenv(CATALOG_REGISTRY_ROOT_ENV, str(second_registry_root))
        second = get_operational_catalog_service()
        assert second is not first
        assert second.registry.registry_root == second_registry_root
    finally:
        clear_operational_catalog_service_cache()

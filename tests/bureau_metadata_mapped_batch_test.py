from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.bureau_metadata.catalog_service import BureauCatalogLookupError
from server.bureau_metadata.operational_service import OperationalCatalogService


def _service() -> tuple[OperationalCatalogService, SimpleNamespace, SimpleNamespace]:
    record = SimpleNamespace(
        catalog_version_id="catalog-version-synthetic",
        normalized_catalog_checksum="a" * 64,
        provider_name="Synthetic Bureau",
        product_name="Synthetic Product",
        edition="Synthetic Edition",
        source_release_version="2026.1",
    )
    attribute = SimpleNamespace(
        attribute_code="ATTR_A",
        description="Synthetic bounded provider definition",
        numeric_type="integer",
        units="months",
        field_length=3,
        valid_range_expression="0 through 120",
        ordinary_min="0",
        ordinary_max="120",
        record_checksum="b" * 64,
    )
    special = SimpleNamespace(
        value_code="-9",
        meaning="Synthetic unavailable value",
        semantic_family="unavailable",
        definition_id="synthetic-special-definition",
        definition_checksum="c" * 64,
    )
    catalog = SimpleNamespace(
        attributes_by_code={"ATTR_A": attribute},
        special_values_by_key={("ATTR_A", "-9"): special},
    )
    registry = SimpleNamespace(
        get_version=lambda _version_id: record,
        record_access_audit=lambda **_kwargs: None,
    )
    catalogs = SimpleNamespace(
        _load_authorized=lambda *_args, **_kwargs: catalog,
    )
    service = object.__new__(OperationalCatalogService)
    service.registry = registry
    service.catalogs = catalogs
    return service, registry, catalogs


def test_mapped_attribute_batch_is_single_load_bounded_and_exact() -> None:
    service, registry, catalogs = _service()
    load_calls: list[tuple[object, ...]] = []
    audit_calls: list[dict[str, object]] = []
    original_load = catalogs._load_authorized
    catalogs._load_authorized = lambda *args, **kwargs: (
        load_calls.append(args) or original_load(*args, **kwargs)
    )
    registry.record_access_audit = lambda **kwargs: audit_calls.append(kwargs)

    result = service.get_mapped_attribute_batch(
        principal_id="synthetic-analyst",
        tenant_id="synthetic-tenant",
        catalog_version_id="catalog-version-synthetic",
        attribute_codes=("ATTR_A", "ATTR_A"),
    )

    assert len(load_calls) == 1
    assert result["bounded"] is True
    assert result["requested"] == 1
    assert result["returned"] == 1
    row = result["attributes"][0]
    assert row["attribute_code"] == "ATTR_A"
    assert row["description"] == "Synthetic bounded provider definition"
    assert row["ordinary_min"] == "0"
    assert row["ordinary_max"] == "120"
    assert len(row["special_values"]) == 1
    assert row["special_values_total"] == 1
    assert row["special_values_truncated"] is False
    assert audit_calls[0]["action"] == "mapped_attribute_batch"


def test_mapped_attribute_batch_rejects_unbounded_or_missing_codes() -> None:
    service, _registry, _catalogs = _service()
    with pytest.raises(ValueError, match="between 1 and 250"):
        service.get_mapped_attribute_batch(
            principal_id="synthetic-analyst",
            tenant_id="synthetic-tenant",
            catalog_version_id="catalog-version-synthetic",
            attribute_codes=(),
        )
    with pytest.raises(BureauCatalogLookupError):
        service.get_mapped_attribute_batch(
            principal_id="synthetic-analyst",
            tenant_id="synthetic-tenant",
            catalog_version_id="catalog-version-synthetic",
            attribute_codes=("ATTR_MISSING",),
        )

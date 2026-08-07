"""Fail-closed validation for normalized bureau catalog artifacts."""

from __future__ import annotations

from decimal import Decimal
import hashlib
from typing import Any, Mapping, Sequence

from pydantic import BaseModel

from .normalizer import (
    BureauMetadataNormalizationError,
    canonical_json_bytes,
    normalize_attribute_code,
    normalize_value_code,
    parse_decimal_lexeme,
    validate_relative_artifact_path,
    validate_sha256,
)
from .types import (
    BureauAttributeDefinition,
    BureauCatalogKey,
    BureauCatalogLicenseMetadata,
    BureauCatalogManifest,
    BureauCatalogValidationFinding,
    BureauSpecialValueDefinition,
)


_VOLATILE_HASH_KEYS = frozenset(
    {
        "built_at",
        "created_at",
        "catalog_artifact_checksum",
        "catalog_checksum",
        "record_checksum",
        "definition_checksum",
    }
)


class BureauCatalogValidationError(ValueError):
    """Raised when an exact catalog cannot be proven internally consistent."""


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _strip_volatile(value: Any) -> Any:
    value = _json_value(value)
    if isinstance(value, Mapping):
        return {
            str(key): _strip_volatile(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            if str(key) not in _VOLATILE_HASH_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_strip_volatile(item) for item in value]
    return value


def deterministic_normalized_hash(value: Any) -> str:
    """Match the builder's normalized, newline-terminated SHA-256 contract."""

    payload = canonical_json_bytes(_strip_volatile(value)) + b"\n"
    return hashlib.sha256(payload).hexdigest()


def _normalized_attribute_payload(
    attribute: BureauAttributeDefinition | Mapping[str, Any],
) -> Mapping[str, Any]:
    """Materialize aliases and defaults before hashing an attribute record.

    The builder computes checksums while lineage checksum fields are still being
    assembled, whereas the loader verifies fully materialized Pydantic records.
    Supplying inert placeholders lets both paths use the same immutable contract;
    the placeholders themselves are excluded by ``_strip_volatile``.
    """

    if isinstance(attribute, BureauAttributeDefinition):
        return attribute.model_dump(mode="json")
    payload = dict(attribute)
    payload.setdefault("catalog_checksum", "0" * 64)
    payload.setdefault("record_checksum", "0" * 64)
    return BureauAttributeDefinition.model_validate(payload).model_dump(mode="json")


def _normalized_special_payload(
    special: BureauSpecialValueDefinition | Mapping[str, Any],
) -> Mapping[str, Any]:
    """Materialize aliases and defaults before hashing a special definition."""

    if isinstance(special, BureauSpecialValueDefinition):
        return special.model_dump(mode="json")
    payload = dict(special)
    payload.setdefault("catalog_checksum", "0" * 64)
    payload.setdefault("definition_checksum", "0" * 64)
    return BureauSpecialValueDefinition.model_validate(payload).model_dump(mode="json")


def attribute_record_checksum(attribute: BureauAttributeDefinition | Mapping[str, Any]) -> str:
    return deterministic_normalized_hash(_normalized_attribute_payload(attribute))


def special_definition_id(
    special: BureauSpecialValueDefinition | Mapping[str, Any],
) -> str:
    payload = _json_value(special)
    return "bsv-" + deterministic_normalized_hash(
        {
            "catalog_key": payload["catalog_key"],
            "attribute_code": payload["attribute_code"],
            "value_code": payload["value_code"],
        }
    )[:24]


def special_definition_checksum(
    special: BureauSpecialValueDefinition | Mapping[str, Any],
) -> str:
    return deterministic_normalized_hash(_normalized_special_payload(special))


def calculate_catalog_checksum(
    *,
    schema_version: str,
    catalog_key: BureauCatalogKey | Mapping[str, Any],
    attributes: Sequence[BureauAttributeDefinition | Mapping[str, Any]],
    special_values: Sequence[BureauSpecialValueDefinition | Mapping[str, Any]],
    reconciliation_findings: Sequence[
        BureauCatalogValidationFinding | Mapping[str, Any]
    ],
    governance: Mapping[str, Any],
) -> str:
    key_payload = (
        catalog_key.model_dump(mode="json")
        if isinstance(catalog_key, BureauCatalogKey)
        else dict(catalog_key)
    )
    return deterministic_normalized_hash(
        {
            "schema_version": schema_version,
            "catalog_key": key_payload,
            "attributes": [
                _normalized_attribute_payload(value) for value in attributes
            ],
            "special_values": [
                _normalized_special_payload(value) for value in special_values
            ],
            "reconciliation": [_json_value(value) for value in reconciliation_findings],
            "governance": _json_value(governance),
        }
    )


def catalog_governance_payload(
    *,
    license_metadata: BureauCatalogLicenseMetadata | Mapping[str, Any],
    restricted_export: bool,
    full_catalog_path: str,
) -> Mapping[str, Any]:
    """Return the restrictive envelope that is bound to catalog identity."""

    license_contract = (
        license_metadata
        if isinstance(license_metadata, BureauCatalogLicenseMetadata)
        else BureauCatalogLicenseMetadata.model_validate(license_metadata)
    )
    license_payload = license_contract.model_dump(mode="json")
    # Pydantic's JSON conversion of frozenset values has changed ordering
    # across supported releases.  Catalog identity must not depend on the
    # interpreter's set iteration order, so materialize the operation set in
    # the one canonical order before hashing it.
    license_payload["allowed_operations"] = sorted(
        license_contract.allowed_operations
    )
    return {
        "license": license_payload,
        "restricted_export": bool(restricted_export),
        "full_catalog_path": str(full_catalog_path),
    }


def validate_restricted_catalog_governance(
    manifest: BureauCatalogManifest,
) -> None:
    """Fail closed if a lookup-capable snapshot relaxes its safety envelope."""

    license_metadata = manifest.license
    if not manifest.restricted_export or manifest.full_catalog_path != ".":
        raise BureauCatalogValidationError(
            "Catalog restriction metadata is contradictory."
        )
    if (
        license_metadata.source_export_allowed
        or license_metadata.full_catalog_api_allowed
        or license_metadata.tenant_sharing_allowed
        or license_metadata.public_demo_allowed
        or not license_metadata.legal_review_required
        or license_metadata.redistribution_status == "permitted"
    ):
        raise BureauCatalogValidationError(
            "Catalog license metadata relaxes required restricted-access controls."
        )


def _validate_descriptor_paths(manifest: BureauCatalogManifest) -> None:
    descriptors = [
        manifest.attribute_file,
        manifest.special_value_file,
        manifest.validation_file,
        manifest.lookup_index_file,
        manifest.reconciliation_file,
        manifest.build_log_file,
    ]
    paths: list[str] = []
    for descriptor in descriptors:
        if descriptor is None:
            continue
        try:
            paths.append(validate_relative_artifact_path(descriptor.relative_path))
        except BureauMetadataNormalizationError as exc:
            raise BureauCatalogValidationError(
                "Catalog manifest contains an unsafe artifact path."
            ) from exc
    if len(paths) != len(set(paths)):
        raise BureauCatalogValidationError(
            "Catalog manifest assigns the same path to multiple artifacts."
        )


def _decimal_bound(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return parse_decimal_lexeme(value)
    except BureauMetadataNormalizationError as exc:
        raise BureauCatalogValidationError(
            "Catalog attribute contains an invalid numeric domain bound."
        ) from exc


def validate_catalog(
    *,
    manifest: BureauCatalogManifest,
    expected_key: BureauCatalogKey,
    expected_checksum: str,
    attributes: Sequence[BureauAttributeDefinition],
    special_values: Sequence[BureauSpecialValueDefinition],
    reconciliation_findings: Sequence[
        BureauCatalogValidationFinding | Mapping[str, Any]
    ] = (),
) -> None:
    """Validate one exact artifact set or raise without partial acceptance."""

    checksum = validate_sha256(expected_checksum, field_name="expected catalog checksum")
    if manifest.catalog_key != expected_key or manifest.catalog_checksum != checksum:
        raise BureauCatalogValidationError(
            "Catalog manifest does not match the exact requested identity."
        )
    if manifest.validation_status == "failed":
        raise BureauCatalogValidationError(
            "Catalog build is marked failed and cannot be loaded."
        )
    validate_restricted_catalog_governance(manifest)
    if manifest.attribute_count != len(attributes):
        raise BureauCatalogValidationError("Catalog attribute count does not match its manifest.")
    if manifest.special_value_count != len(special_values):
        raise BureauCatalogValidationError(
            "Catalog special-value count does not match its manifest."
        )
    if manifest.validation_finding_count != len(reconciliation_findings):
        raise BureauCatalogValidationError(
            "Catalog validation-finding count does not match its manifest."
        )
    if manifest.attribute_file.record_count != len(attributes):
        raise BureauCatalogValidationError(
            "Attribute descriptor count does not match the loaded artifact."
        )
    if manifest.special_value_file.record_count != len(special_values):
        raise BureauCatalogValidationError(
            "Special-value descriptor count does not match the loaded artifact."
        )
    _validate_descriptor_paths(manifest)

    by_code: dict[str, BureauAttributeDefinition] = {}
    casefolded_codes: set[str] = set()
    for attribute in attributes:
        if (
            attribute.catalog_key != expected_key
            or attribute.catalog_checksum != checksum
        ):
            raise BureauCatalogValidationError(
                "An attribute definition has contradictory catalog lineage."
            )
        code = normalize_attribute_code(attribute.attribute_code)
        if code.casefold() in casefolded_codes:
            raise BureauCatalogValidationError(
                "Attribute codes are not unique within the exact catalog."
            )
        casefolded_codes.add(code.casefold())
        by_code[code] = attribute
        if attribute.record_checksum != attribute_record_checksum(attribute):
            raise BureauCatalogValidationError(
                "An attribute definition checksum could not be verified."
            )
        if attribute.numeric_type in {"integer", "decimal"}:
            lower = _decimal_bound(attribute.ordinary_min)
            upper = _decimal_bound(attribute.ordinary_max)
            if lower is not None and upper is not None and lower > upper:
                raise BureauCatalogValidationError(
                    "An attribute definition has a contradictory ordinary range."
                )

    seen_specials: set[tuple[str, str]] = set()
    for special in special_values:
        if special.catalog_key != expected_key or special.catalog_checksum != checksum:
            raise BureauCatalogValidationError(
                "A special-value definition has contradictory catalog lineage."
            )
        attribute = by_code.get(special.attribute_code)
        if attribute is None:
            raise BureauCatalogValidationError(
                "A special-value definition references an unknown attribute."
            )
        try:
            normalized_code = normalize_value_code(
                special.value_code,
                attribute.numeric_type,
            )
        except BureauMetadataNormalizationError as exc:
            raise BureauCatalogValidationError(
                "A special-value definition has an invalid value code."
            ) from exc
        exact_key = (special.attribute_code, normalized_code)
        if exact_key in seen_specials:
            raise BureauCatalogValidationError(
                "Special-value definitions are not unique for one attribute."
            )
        seen_specials.add(exact_key)
        if special.definition_id != special_definition_id(special):
            raise BureauCatalogValidationError(
                "A special-value definition ID could not be verified."
            )
        if special.definition_checksum != special_definition_checksum(special):
            raise BureauCatalogValidationError(
                "A special-value definition checksum could not be verified."
            )

    actual_catalog_checksum = calculate_catalog_checksum(
        schema_version=manifest.schema_version,
        catalog_key=manifest.catalog_key,
        attributes=attributes,
        special_values=special_values,
        reconciliation_findings=reconciliation_findings,
        governance=catalog_governance_payload(
            license_metadata=manifest.license,
            restricted_export=manifest.restricted_export,
            full_catalog_path=manifest.full_catalog_path,
        ),
    )
    if actual_catalog_checksum != checksum:
        raise BureauCatalogValidationError(
            "Normalized catalog content does not match its exact checksum."
        )


__all__ = [
    "BureauCatalogValidationError",
    "attribute_record_checksum",
    "catalog_governance_payload",
    "calculate_catalog_checksum",
    "deterministic_normalized_hash",
    "special_definition_checksum",
    "special_definition_id",
    "validate_restricted_catalog_governance",
    "validate_catalog",
]

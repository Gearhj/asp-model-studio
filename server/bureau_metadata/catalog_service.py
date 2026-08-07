"""Authorized, bounded operations over exact bureau metadata catalogs."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from .catalog_store import BureauCatalogLoader, LoadedBureauCatalog
from .normalizer import (
    BureauMetadataNormalizationError,
    canonicalize_observed_value,
    normalize_attribute_code,
    normalize_value_code,
    parse_decimal_lexeme,
    validate_sha256,
)
from .types import (
    BureauAttributeDefinition,
    BureauAttributeResolution,
    BureauCatalogAccessContext,
    BureauCatalogAccessGrant,
    BureauCatalogKey,
    BureauCatalogManifest,
    BureauSpecialValueDefinition,
    BureauValueClassification,
    CatalogOperation,
)
from .validation import (
    BureauCatalogValidationError,
    validate_restricted_catalog_governance,
)


class BureauCatalogAccessDeniedError(PermissionError):
    """Raised without disclosing whether restricted catalog content exists."""


class BureauCatalogLookupError(LookupError):
    """Raised when an authorized exact lookup has no single result."""


@runtime_checkable
class BureauCatalogEntitlementProvider(Protocol):
    """Independent licensing authority; project/admin roles are insufficient."""

    def authorize(
        self,
        context: BureauCatalogAccessContext,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
        operation: CatalogOperation,
    ) -> BureauCatalogAccessGrant:
        """Return one exact unexpired grant or raise access denied."""


class DenyAllBureauCatalogEntitlementProvider:
    """Safe default until an explicit external entitlement source is configured."""

    def authorize(
        self,
        context: BureauCatalogAccessContext,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
        operation: CatalogOperation,
    ) -> BureauCatalogAccessGrant:
        del context, catalog_key, catalog_checksum, operation
        raise BureauCatalogAccessDeniedError(
            "Bureau catalog access is not authorized."
        )


def _parse_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BureauCatalogAccessDeniedError(
            "Bureau catalog entitlement is invalid."
        ) from exc
    if parsed.tzinfo is None:
        raise BureauCatalogAccessDeniedError(
            "Bureau catalog entitlement expiry must include a timezone."
        )
    return parsed.astimezone(timezone.utc)


class BureauCatalogService:
    """No enumeration or export API: every method is an exact bounded lookup."""

    def __init__(
        self,
        loader: BureauCatalogLoader,
        entitlement_provider: BureauCatalogEntitlementProvider | None = None,
    ) -> None:
        self.loader = loader
        self.entitlement_provider = (
            entitlement_provider or DenyAllBureauCatalogEntitlementProvider()
        )

    def _authorize(
        self,
        context: BureauCatalogAccessContext,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
        operation: CatalogOperation,
    ) -> str:
        try:
            checksum = validate_sha256(
                catalog_checksum,
                field_name="catalog_checksum",
            )
            grant = self.entitlement_provider.authorize(
                context,
                catalog_key,
                checksum,
                operation,
            )
        except BureauCatalogAccessDeniedError:
            raise
        except Exception as exc:
            raise BureauCatalogAccessDeniedError(
                "Bureau catalog access could not be authorized."
            ) from exc
        if (
            grant.principal_id != context.principal_id
            or grant.catalog_key != catalog_key
            or grant.catalog_checksum != checksum
            or grant.operation != operation
        ):
            raise BureauCatalogAccessDeniedError(
                "Bureau catalog access grant does not match the exact request."
            )
        if grant.tenant_id != context.tenant_id:
            raise BureauCatalogAccessDeniedError(
                "Bureau catalog tenant entitlement could not be verified."
            )
        if grant.expires_at is not None and _parse_expiry(grant.expires_at) <= datetime.now(
            timezone.utc
        ):
            raise BureauCatalogAccessDeniedError(
                "Bureau catalog entitlement has expired."
            )
        return checksum

    @staticmethod
    def _license_gate(
        catalog: LoadedBureauCatalog,
        operation: CatalogOperation,
    ) -> None:
        try:
            validate_restricted_catalog_governance(catalog.manifest)
        except BureauCatalogValidationError as exc:
            raise BureauCatalogAccessDeniedError(
                "Catalog restriction metadata is contradictory."
            ) from exc
        license_metadata = catalog.manifest.license
        if operation not in license_metadata.allowed_operations:
            raise BureauCatalogAccessDeniedError(
                "The catalog license does not allow this operation."
            )

    def _load_authorized(
        self,
        context: BureauCatalogAccessContext,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
        operation: CatalogOperation,
    ) -> LoadedBureauCatalog:
        # Authorization deliberately occurs before loader/cache access. An LRU
        # entry never becomes an entitlement and revocation is checked per call.
        checksum = self._authorize(
            context,
            catalog_key,
            catalog_checksum,
            operation,
        )
        catalog = self.loader.load_exact(catalog_key, checksum)
        self._license_gate(catalog, operation)
        return catalog

    def catalog_health_exact(
        self,
        context: BureauCatalogAccessContext,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
    ) -> Mapping[str, Any]:
        catalog = self._load_authorized(
            context,
            catalog_key,
            catalog_checksum,
            "catalog_health",
        )
        return {
            "catalog_id": catalog.manifest.catalog_id,
            "catalog_key": catalog.manifest.catalog_key.model_dump(mode="json"),
            "catalog_checksum": catalog.manifest.catalog_checksum,
            "validation_status": catalog.manifest.validation_status,
            "attribute_count": catalog.manifest.attribute_count,
            "special_value_count": catalog.manifest.special_value_count,
        }

    def get_manifest_exact(
        self,
        context: BureauCatalogAccessContext,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
    ) -> BureauCatalogManifest:
        return self._load_authorized(
            context,
            catalog_key,
            catalog_checksum,
            "manifest_read",
        ).manifest

    def build_dataset_crosswalk_candidates_exact(
        self,
        context: BureauCatalogAccessContext,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
        fields: Iterable[object],
        *,
        target_field: str | None = None,
        target_source_fields: Iterable[str] = (),
        semantic_threshold: float = 0.55,
        semantic_tie_delta: float = 0.03,
    ) -> Mapping[str, Any]:
        """Return candidate mappings without exposing catalog enumeration.

        Entitlement and catalog-license checks occur before definitions are
        loaded.  Attribute definitions remain inside the service boundary;
        callers receive only the bounded candidate-only crosswalk artifact.
        Institutional aliases are deliberately unavailable through this
        foundation method because alias approval requires a separate governed
        authority that is not part of the catalog license grant.
        """

        catalog = self._load_authorized(
            context,
            catalog_key,
            catalog_checksum,
            "crosswalk_candidate",
        )
        field_records = tuple(fields)
        if len(field_records) > 10_000:
            raise ValueError("Crosswalk candidate input exceeds its field limit.")
        from .crosswalk import build_dataset_crosswalk

        return build_dataset_crosswalk(
            field_records,
            tuple(
                catalog.attributes_by_code[code]
                for code in sorted(catalog.attributes_by_code)
            ),
            catalog_key=catalog_key,
            catalog_checksum=catalog.manifest.catalog_checksum,
            aliases=(),
            target_field=target_field,
            target_source_fields=tuple(target_source_fields),
            semantic_threshold=semantic_threshold,
            semantic_tie_delta=semantic_tie_delta,
        )

    def get_attribute_exact(
        self,
        context: BureauCatalogAccessContext,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
        attribute_code: str,
    ) -> BureauAttributeDefinition:
        catalog = self._load_authorized(
            context,
            catalog_key,
            catalog_checksum,
            "attribute_lookup",
        )
        code = normalize_attribute_code(attribute_code)
        attribute = catalog.attributes_by_code.get(code)
        if attribute is None:
            raise BureauCatalogLookupError(
                "The exact catalog attribute is unavailable."
            )
        return attribute

    def resolve_attribute_exact(
        self,
        context: BureauCatalogAccessContext,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
        attribute_code: str,
    ) -> BureauAttributeResolution:
        """Resolve one code without turning an unknown code into an exception."""

        catalog = self._load_authorized(
            context,
            catalog_key,
            catalog_checksum,
            "attribute_lookup",
        )
        try:
            code = normalize_attribute_code(attribute_code)
        except BureauMetadataNormalizationError:
            requested = str(attribute_code).strip() or "<invalid>"
            return BureauAttributeResolution(
                catalog_key=catalog_key,
                catalog_checksum=catalog.manifest.catalog_checksum,
                requested_attribute_code=requested,
                status="unresolved",
                reason="invalid_attribute_code",
            )
        attribute = catalog.attributes_by_code.get(code)
        return BureauAttributeResolution(
            catalog_key=catalog_key,
            catalog_checksum=catalog.manifest.catalog_checksum,
            requested_attribute_code=code,
            status="resolved" if attribute is not None else "unresolved",
            attribute=attribute,
            reason="exact_match" if attribute is not None else "unknown_attribute_code",
        )

    def get_special_value_exact(
        self,
        context: BureauCatalogAccessContext,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
        attribute_code: str,
        value_code: str,
    ) -> BureauSpecialValueDefinition:
        catalog = self._load_authorized(
            context,
            catalog_key,
            catalog_checksum,
            "special_value_lookup",
        )
        code = normalize_attribute_code(attribute_code)
        attribute = catalog.attributes_by_code.get(code)
        if attribute is None:
            raise BureauCatalogLookupError(
                "The exact catalog attribute is unavailable."
            )
        try:
            normalized_value = normalize_value_code(value_code, attribute.numeric_type)
        except BureauMetadataNormalizationError as exc:
            raise BureauCatalogLookupError(
                "The exact special-value code is invalid for this attribute."
            ) from exc
        special = catalog.special_values_by_key.get((code, normalized_value))
        if special is None:
            raise BureauCatalogLookupError(
                "The exact catalog special-value definition is unavailable."
            )
        return special

    def classify_value_exact(
        self,
        context: BureauCatalogAccessContext,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
        attribute_code: str,
        observed_value: object,
        *,
        ordinary_outlier_lower: str | None = None,
        ordinary_outlier_upper: str | None = None,
    ) -> BureauValueClassification:
        catalog = self._load_authorized(
            context,
            catalog_key,
            catalog_checksum,
            "value_classification",
        )
        code = normalize_attribute_code(attribute_code)
        attribute = catalog.attributes_by_code.get(code)
        if attribute is None:
            raise BureauCatalogLookupError(
                "The exact catalog attribute is unavailable."
            )
        normalized = canonicalize_observed_value(
            observed_value,
            attribute.numeric_type,
        )
        common = {
            "catalog_key": catalog_key,
            "catalog_checksum": catalog.manifest.catalog_checksum,
            "attribute_code": code,
            "observed_value_code": normalized.canonical_code,
        }
        if normalized.is_null:
            return BureauValueClassification(
                **common,
                classification="true_null",
                reason="The observed value is a true null.",
            )
        if not normalized.parsed:
            classification = (
                "unexpected_invalid"
                if normalized.reason
                in {"fractional_value_for_integer_attribute", "non_finite_numeric_value"}
                else "parse_failure"
            )
            return BureauValueClassification(
                **common,
                classification=classification,
                reason=normalized.reason,
            )

        special = catalog.special_values_by_key.get(
            (code, normalized.canonical_code or "")
        )
        if special is not None:
            return BureauValueClassification(
                **common,
                classification="bureau_special",
                definition_id=special.definition_id,
                definition_checksum=special.definition_checksum,
                reason="The exact attribute-specific catalog defines this value as special.",
            )

        unexpected_reason = self._unexpected_invalid_reason(attribute, normalized)
        if unexpected_reason is not None:
            return BureauValueClassification(
                **common,
                classification="unexpected_invalid",
                reason=unexpected_reason,
            )

        ordinary_outlier = self._ordinary_outlier(
            normalized.numeric_value,
            ordinary_outlier_lower,
            ordinary_outlier_upper,
        )
        return BureauValueClassification(
            **common,
            classification="ordinary_valid",
            ordinary_outlier=ordinary_outlier,
            reason=(
                "The ordinary valid value is outside the supplied outlier bounds."
                if ordinary_outlier
                else "The value is ordinary and valid for the exact attribute."
            ),
        )

    @staticmethod
    def _unexpected_invalid_reason(
        attribute: BureauAttributeDefinition,
        normalized: Any,
    ) -> str | None:
        if normalized.reason == "fractional_value_for_integer_attribute":
            return normalized.reason
        numeric = normalized.numeric_value
        if numeric is not None:
            if attribute.ordinary_min is not None and numeric < parse_decimal_lexeme(
                attribute.ordinary_min
            ):
                return "value_below_attribute_domain"
            if attribute.ordinary_max is not None and numeric > parse_decimal_lexeme(
                attribute.ordinary_max
            ):
                return "value_above_attribute_domain"
        if attribute.valid_values:
            valid = {
                normalize_value_code(value, attribute.numeric_type)
                for value in attribute.valid_values
            }
            if normalized.canonical_code not in valid:
                return "value_outside_attribute_domain"
        return None

    @staticmethod
    def _ordinary_outlier(
        numeric_value: Decimal | None,
        lower: str | None,
        upper: str | None,
    ) -> bool:
        if numeric_value is None:
            return False
        lower_value = parse_decimal_lexeme(lower) if lower is not None else None
        upper_value = parse_decimal_lexeme(upper) if upper is not None else None
        if lower_value is not None and upper_value is not None and lower_value > upper_value:
            raise ValueError("Ordinary outlier bounds are contradictory.")
        return bool(
            (lower_value is not None and numeric_value < lower_value)
            or (upper_value is not None and numeric_value > upper_value)
        )


__all__ = [
    "BureauCatalogAccessDeniedError",
    "BureauCatalogEntitlementProvider",
    "BureauCatalogLookupError",
    "BureauCatalogService",
    "DenyAllBureauCatalogEntitlementProvider",
]

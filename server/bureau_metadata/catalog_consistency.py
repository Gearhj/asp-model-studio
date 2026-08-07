"""Bounded reconciliation of governed mappings with observed dataset metadata.

This module is deliberately pure: it accepts one analyst-governed mapping,
one exact provider definition, and one backend-authoritative field summary. It
never opens dataset rows, previews, partitions, or holdout artifacts and has no
mutation path.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .crosswalk_governance import GovernedMappingDecision
from .normalizer import canonical_json_bytes


CatalogConsistencyState = Literal[
    "consistent",
    "consistent_with_observed_unused_codes",
    "review_required",
    "contradictory",
    "metadata_unavailable",
    "mapping_unresolved",
]

CatalogConsistencyCheckState = Literal[
    "consistent",
    "review_required",
    "contradictory",
    "metadata_unavailable",
    "not_applicable",
]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CatalogConsistencyCheck(_FrozenContract):
    state: CatalogConsistencyCheckState
    code: str = Field(min_length=1, max_length=96)
    detail: str = Field(min_length=1, max_length=320)

    @field_validator("code", "detail")
    @classmethod
    def bounded_plain_text(cls, value: str) -> str:
        cleaned = " ".join(str(value).split())
        if not cleaned or any(
            ord(character) < 32 or ord(character) == 127 for character in cleaned
        ):
            raise ValueError("Consistency check text is invalid.")
        return cleaned


class CatalogFieldConsistency(_FrozenContract):
    dataset_field: str = Field(min_length=1, max_length=256)
    candidate_attribute_code: str | None = Field(default=None, max_length=256)
    mapping_state: str = Field(min_length=1, max_length=96)
    provider_authoritative: bool
    consistency_state: CatalogConsistencyState
    recommendations_blocked: bool
    recommendation_block_reason: str | None = Field(default=None, max_length=160)
    checks: Mapping[str, CatalogConsistencyCheck]
    observed_unused_special_codes: tuple[str, ...] = Field(default=(), max_length=64)
    observed_undefined_special_codes: tuple[str, ...] = Field(default=(), max_length=64)
    source_summary_checksum: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    raw_rows_accessed: Literal[False] = False
    browser_preview_used: Literal[False] = False
    final_holdout_accessed: Literal[False] = False
    dataset_mutated: Literal[False] = False
    predictor_authorization_mutated: Literal[False] = False
    analysis_partition_mutated: Literal[False] = False
    feature_manifest_mutated: Literal[False] = False


def _decimal(value: object) -> Decimal | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _canonical_code(value: object) -> str:
    text = "" if value is None else str(value).strip()
    numeric = _decimal(text)
    if numeric is None:
        return text.casefold()
    normalized = numeric.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f").rstrip("0").rstrip(".")


def _check(
    state: CatalogConsistencyCheckState, code: str, detail: str
) -> CatalogConsistencyCheck:
    return CatalogConsistencyCheck(state=state, code=code, detail=detail)


def _type_family(value: object) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return "unknown"
    if any(token in text for token in ("datetime", "timestamp", "date")):
        return "date"
    if any(token in text for token in ("string", "text", "object", "category", "char")):
        return "text"
    if any(token in text for token in ("int", "integer")):
        return "integer"
    if any(token in text for token in ("float", "double", "decimal", "real")):
        return "decimal"
    if "numeric" in text or "number" in text:
        return "numeric"
    return "unknown"


def _type_check(provider: object, observed: object) -> CatalogConsistencyCheck:
    expected = _type_family(provider)
    actual = _type_family(observed)
    if expected == "unknown" or actual == "unknown":
        return _check(
            "review_required",
            "datatype_not_comparable",
            "Provider and observed datatypes are not both specific enough to compare.",
        )
    if expected == actual:
        return _check("consistent", "datatype_compatible", "Datatypes are compatible.")
    if expected in {"integer", "decimal"} and actual in {
        "integer",
        "decimal",
        "numeric",
    }:
        if expected == "integer" and actual == "decimal":
            return _check(
                "review_required",
                "integer_decimal_review",
                "The provider expects an integer while the observed storage type permits decimals.",
            )
        return _check("consistent", "numeric_datatype_compatible", "Numeric datatypes are compatible.")
    return _check(
        "contradictory",
        "datatype_contradiction",
        "The provider and observed datatype families conflict.",
    )


def _length_check(provider: object, observed: object) -> CatalogConsistencyCheck:
    try:
        expected = int(provider) if provider not in (None, "") else None
        actual = int(observed) if observed not in (None, "") else None
    except (TypeError, ValueError):
        return _check(
            "review_required",
            "field_length_invalid",
            "A field-length value is present but cannot be compared.",
        )
    if expected is None or actual is None:
        return _check(
            "not_applicable",
            "field_length_not_available",
            "Comparable provider and observed field lengths are not both available.",
        )
    if actual > expected:
        return _check(
            "contradictory",
            "field_length_exceeds_provider",
            "The observed field length exceeds the provider definition.",
        )
    return _check("consistent", "field_length_compatible", "Field lengths are compatible.")


def _range_and_special_checks(
    provider: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> tuple[
    CatalogConsistencyCheck,
    CatalogConsistencyCheck,
    tuple[str, ...],
    tuple[str, ...],
]:
    lower = _decimal(provider.get("ordinary_min"))
    upper = _decimal(provider.get("ordinary_max"))
    observed_min = _decimal(observed.get("observed_min"))
    observed_max = _decimal(observed.get("observed_max"))
    special_rows = tuple(provider.get("special_values") or ())
    defined_codes = {
        _canonical_code(row.get("value_code"))
        for row in special_rows
        if isinstance(row, Mapping) and str(row.get("value_code") or "").strip()
    }
    observed_codes = {
        _canonical_code(value)
        for value in tuple(observed.get("observed_special_values") or ())
        if str(value or "").strip()
    }
    # Exact profile bounds are also authoritative observed values. If a bound
    # is outside the ordinary domain but exactly matches a provider-defined
    # special, it must not be misreported as an unused code merely because an
    # older structural summary omitted that code from its special-value list.
    for bound in (observed_min, observed_max):
        if bound is None:
            continue
        code = _canonical_code(bound)
        if code in defined_codes and (
            (lower is not None and bound < lower)
            or (upper is not None and bound > upper)
        ):
            observed_codes.add(code)
    undefined = tuple(sorted(observed_codes.difference(defined_codes)))
    unused = tuple(sorted(defined_codes.difference(observed_codes)))

    if provider.get("special_values_truncated") is True:
        special_check = _check(
            "review_required",
            "provider_special_definitions_truncated",
            "The bounded provider response did not include every special-value definition.",
        )
    elif observed.get("special_summary_available") is not True:
        special_check = _check(
            "metadata_unavailable",
            "observed_special_summary_unavailable",
            "The exact backend special-value summary is unavailable.",
        )
    elif undefined:
        special_check = _check(
            "contradictory",
            "observed_special_code_undefined",
            "At least one observed special code is not defined by the provider metadata.",
        )
    elif unused:
        special_check = _check(
            "consistent",
            "provider_special_codes_unused",
            "Provider-defined special codes are valid but were not observed in this dataset version.",
        )
    else:
        special_check = _check(
            "consistent",
            "special_codes_reconciled",
            "Observed and provider-defined special codes are reconciled.",
        )

    if lower is None or upper is None or observed_min is None or observed_max is None:
        range_check = _check(
            "review_required",
            "ordinary_range_not_comparable",
            "Provider and observed ordinary bounds are not all available.",
        )
    elif lower > upper or observed_min > observed_max:
        range_check = _check(
            "contradictory",
            "range_bounds_contradictory",
            "Provider or observed range bounds are internally contradictory.",
        )
    else:
        outside: list[str] = []
        if observed_min < lower and _canonical_code(observed_min) not in defined_codes:
            outside.append("minimum")
        if observed_max > upper and _canonical_code(observed_max) not in defined_codes:
            outside.append("maximum")
        for code in undefined:
            numeric = _decimal(code)
            if numeric is not None and (numeric < lower or numeric > upper):
                outside.append("undefined_special")
        if outside:
            range_check = _check(
                "contradictory",
                "value_outside_ordinary_and_special_domains",
                "An observed bound or code falls outside both the ordinary range and provider special definitions.",
            )
        else:
            range_check = _check(
                "consistent",
                "ordinary_range_compatible",
                "Observed bounds are within the provider ordinary or special-value domains.",
            )
    return range_check, special_check, unused, undefined


def _restriction_check(
    provider: Mapping[str, Any], observed: Mapping[str, Any]
) -> CatalogConsistencyCheck:
    reconciliation = str(provider.get("reconciliation_status") or "").casefold()
    review = str(provider.get("review_status") or "").casefold()
    if reconciliation == "conflict" or review == "rejected":
        return _check(
            "contradictory",
            "provider_definition_restricted",
            "The exact provider definition is conflicted or rejected.",
        )
    valid_values = {
        _canonical_code(value)
        for value in tuple(provider.get("valid_values") or ())
        if str(value or "").strip()
    }
    observed_values = {
        _canonical_code(value)
        for value in tuple(observed.get("observed_values") or ())
        if str(value or "").strip()
    }
    if valid_values and observed_values.difference(valid_values):
        return _check(
            "contradictory",
            "valid_value_restriction_contradiction",
            "An observed summarized value is outside the provider valid-value restriction.",
        )
    if provider.get("valid_values_truncated") is True:
        return _check(
            "review_required",
            "provider_valid_values_truncated",
            "The bounded provider response did not include every valid-value restriction.",
        )
    applicable_versions = {
        str(value).strip().casefold()
        for value in tuple(provider.get("applicable_versions") or ())
        if str(value or "").strip()
    }
    source_version = str(observed.get("source_version") or "").strip().casefold()
    if applicable_versions and source_version and source_version not in applicable_versions:
        return _check(
            "contradictory",
            "applicable_version_contradiction",
            "The observed source version is outside the provider applicability restriction.",
        )
    if provider.get("applicable_versions_truncated") is True:
        return _check(
            "review_required",
            "provider_applicable_versions_truncated",
            "The bounded provider response did not include every applicability restriction.",
        )
    if applicable_versions and not source_version:
        return _check(
            "review_required",
            "observed_source_version_unavailable",
            "Provider applicability restrictions exist but the observed source version is unavailable.",
        )
    archive = str(provider.get("archive_indicator") or "").strip().casefold()
    if archive and archive not in {"0", "n", "no", "false", "active", "current"}:
        return _check(
            "review_required",
            "provider_archive_restriction_review",
            "The provider archive restriction requires analyst review.",
        )
    if reconciliation in {"unreviewed", "pdf_only", "csv_only"} or review == "unreviewed":
        return _check(
            "review_required",
            "provider_definition_review_required",
            "The provider definition has not completed reconciliation review.",
        )
    return _check(
        "consistent",
        "provider_restrictions_compatible",
        "Available provider restrictions do not conflict with the observed summary.",
    )


def reconcile_catalog_consistency(
    *,
    decision: GovernedMappingDecision,
    provider_attribute: Mapping[str, Any] | None,
    observed_summary: Mapping[str, Any] | None,
) -> CatalogFieldConsistency:
    """Return one deterministic, non-mutating field consistency result."""

    authoritative = bool(
        decision.analyst_confirmed
        and decision.mapping_state in {"exact_verified", "approved_alias"}
        and decision.candidate_attribute_code
    )
    if not authoritative:
        return CatalogFieldConsistency(
            dataset_field=decision.dataset_field,
            candidate_attribute_code=decision.candidate_attribute_code,
            mapping_state=decision.mapping_state,
            provider_authoritative=False,
            consistency_state="mapping_unresolved",
            recommendations_blocked=True,
            recommendation_block_reason="mapping_not_authoritative",
            checks={
                "mapping": _check(
                    "metadata_unavailable",
                    "mapping_unresolved",
                    "Only analyst-confirmed exact or approved-alias mappings are eligible.",
                )
            },
        )
    if provider_attribute is None or observed_summary is None:
        return CatalogFieldConsistency(
            dataset_field=decision.dataset_field,
            candidate_attribute_code=decision.candidate_attribute_code,
            mapping_state=decision.mapping_state,
            provider_authoritative=True,
            consistency_state="metadata_unavailable",
            recommendations_blocked=True,
            recommendation_block_reason="exact_metadata_unavailable",
            checks={
                "metadata": _check(
                    "metadata_unavailable",
                    "exact_metadata_unavailable",
                    "Exact provider or backend-authoritative observed metadata is unavailable.",
                )
            },
        )
    if str(provider_attribute.get("attribute_code") or "") != str(
        decision.candidate_attribute_code
    ):
        raise ValueError("The provider definition contradicts the governed mapping.")

    type_check = _type_check(
        provider_attribute.get("numeric_type"), observed_summary.get("data_type")
    )
    length_check = _length_check(
        provider_attribute.get("field_length"), observed_summary.get("field_length")
    )
    range_check, special_check, unused, undefined = _range_and_special_checks(
        provider_attribute, observed_summary
    )
    restriction_check = _restriction_check(provider_attribute, observed_summary)
    checks = {
        "datatype": type_check,
        "field_length": length_check,
        "ordinary_range": range_check,
        "special_values": special_check,
        "restrictions": restriction_check,
    }
    states = {check.state for check in checks.values()}
    if "contradictory" in states:
        consistency_state: CatalogConsistencyState = "contradictory"
    elif "metadata_unavailable" in states:
        consistency_state = "metadata_unavailable"
    elif "review_required" in states:
        consistency_state = "review_required"
    elif unused:
        consistency_state = "consistent_with_observed_unused_codes"
    else:
        consistency_state = "consistent"
    blocked = consistency_state not in {
        "consistent",
        "consistent_with_observed_unused_codes",
    }
    summary_checksum = str(observed_summary.get("summary_checksum") or "") or None
    if summary_checksum is None:
        summary_checksum = hashlib.sha256(
            canonical_json_bytes(dict(observed_summary))
        ).hexdigest()
    return CatalogFieldConsistency(
        dataset_field=decision.dataset_field,
        candidate_attribute_code=decision.candidate_attribute_code,
        mapping_state=decision.mapping_state,
        provider_authoritative=True,
        consistency_state=consistency_state,
        recommendations_blocked=blocked,
        recommendation_block_reason=(
            f"catalog_consistency_{consistency_state}" if blocked else None
        ),
        checks=checks,
        observed_unused_special_codes=unused,
        observed_undefined_special_codes=undefined,
        source_summary_checksum=summary_checksum,
    )


__all__ = [
    "CatalogConsistencyCheck",
    "CatalogConsistencyState",
    "CatalogFieldConsistency",
    "reconcile_catalog_consistency",
]

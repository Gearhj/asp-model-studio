"""Bounded bureau semantic annotations for controlled workflow display.

Annotations expose only the minimum provider semantics needed by a workflow.
They are descriptive evidence, never instructions to alter data, treatments,
predictor authorization, or analysis partitions.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from .catalog_binding import DatasetCatalogBindingRevision
from .crosswalk_governance import GovernedMappingDecision, MappingGovernanceState
from .normalizer import canonical_json_bytes
from .types import BureauCatalogKey


BureauSemanticAuthorityState = Literal[
    "provider_exact",
    "provider_definition_via_approved_alias",
    "non_authoritative_derived",
    "non_authoritative_review_required",
    "non_authoritative_unresolved",
    "non_authoritative_stale",
    "non_authoritative_unentitled",
    "non_authoritative_mapping",
]

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


def _clean_text(value: Any, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} cannot contain control characters.")
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError(f"{field_name} cannot be blank.")
    if len(cleaned) > maximum:
        raise ValueError(f"{field_name} exceeds the {maximum}-character limit.")
    return cleaned


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BureauOrdinaryRangeReference(_FrozenContract):
    """Bounded reference to an ordinary-value range in the exact catalog."""

    attribute_code: str
    definition_id: str
    definition_checksum: str = Field(pattern=_SHA256_PATTERN)
    ordinary_min: str | None = None
    ordinary_max: str | None = None
    range_expression: str | None = None

    @field_validator("attribute_code", "definition_id", mode="before")
    @classmethod
    def validate_identifier(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name, maximum=160)

    @field_validator("ordinary_min", "ordinary_max", mode="before")
    @classmethod
    def validate_optional_bound(
        cls, value: Any, info: ValidationInfo
    ) -> str | None:
        if value is None:
            return None
        return _clean_text(value, info.field_name, maximum=128)

    @field_validator("range_expression", mode="before")
    @classmethod
    def validate_optional_expression(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _clean_text(value, "range_expression", maximum=512)

    @model_validator(mode="after")
    def require_bounded_range(self) -> "BureauOrdinaryRangeReference":
        if not (self.range_expression or self.ordinary_min or self.ordinary_max):
            raise ValueError("An ordinary range requires a bound or expression.")
        return self


class BureauSpecialDefinitionReference(_FrozenContract):
    """Bounded special-value definition; source content remains restricted."""

    attribute_code: str
    definition_id: str
    definition_checksum: str = Field(pattern=_SHA256_PATTERN)
    value_code: str
    semantic_family: str
    meaning: str

    @field_validator(
        "attribute_code",
        "definition_id",
        "value_code",
        "semantic_family",
        mode="before",
    )
    @classmethod
    def validate_identifier(cls, value: Any, info: ValidationInfo) -> str:
        maximum = 64 if info.field_name == "semantic_family" else 160
        return _clean_text(value, info.field_name, maximum=maximum)

    @field_validator("meaning", mode="before")
    @classmethod
    def validate_meaning(cls, value: Any) -> str:
        return _clean_text(value, "meaning", maximum=512)


class BureauSemanticAnnotation(_FrozenContract):
    annotation_id: str
    dataset_field: str
    mapping_state: MappingGovernanceState
    mapping_accepted: bool
    candidate_attribute_code: str | None = None
    authority_state: BureauSemanticAuthorityState
    provider_authoritative: bool
    non_authoritative_reasons: tuple[str, ...] = ()
    binding_id: str
    binding_revision: int = Field(ge=1)
    binding_revision_checksum: str = Field(pattern=_SHA256_PATTERN)
    binding_status: Literal["active", "stale"]
    binding_current: bool
    entitlement_verified: bool
    crosswalk_id: str | None = None
    crosswalk_revision: int | None = Field(default=None, ge=1)
    catalog_version_id: str
    catalog_key: BureauCatalogKey
    catalog_checksum: str = Field(pattern=_SHA256_PATTERN)
    description: str | None = None
    data_type: str | None = None
    units: str | None = None
    attribute_definition_checksum: str | None = Field(
        default=None, pattern=_SHA256_PATTERN
    )
    ordinary_range: BureauOrdinaryRangeReference | None = None
    special_definitions: tuple[BureauSpecialDefinitionReference, ...] = ()
    dataset_mutated: Literal[False] = False
    target_contract_mutated: Literal[False] = False
    treatment_mutated: Literal[False] = False
    predictor_authorization_mutated: Literal[False] = False
    analysis_partition_mutated: Literal[False] = False
    feature_manifest_mutated: Literal[False] = False

    @field_validator(
        "annotation_id",
        "dataset_field",
        "binding_id",
        "catalog_version_id",
        mode="before",
    )
    @classmethod
    def validate_identifier(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name, maximum=256)

    @field_validator("candidate_attribute_code", "crosswalk_id", mode="before")
    @classmethod
    def validate_optional_identifier(
        cls, value: Any, info: ValidationInfo
    ) -> str | None:
        if value is None:
            return None
        return _clean_text(value, info.field_name, maximum=256)

    @field_validator("description", mode="before")
    @classmethod
    def validate_optional_description(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _clean_text(value, "description", maximum=1_024)

    @field_validator("data_type", "units", mode="before")
    @classmethod
    def validate_optional_attribute_text(
        cls, value: Any, info: ValidationInfo
    ) -> str | None:
        if value is None:
            return None
        return _clean_text(value, info.field_name, maximum=128)

    @field_validator("non_authoritative_reasons", mode="before")
    @classmethod
    def normalize_reasons(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, (tuple, list, set, frozenset)):
            raise ValueError("non_authoritative_reasons must be a bounded sequence.")
        reasons = tuple(
            sorted(
                {
                    _clean_text(item, "non_authoritative_reason", maximum=160)
                    for item in value
                }
            )
        )
        if len(reasons) > 8:
            raise ValueError("At most eight non-authoritative reasons may be recorded.")
        return reasons

    @model_validator(mode="after")
    def validate_authority_contract(self) -> "BureauSemanticAnnotation":
        eligible_mapping = self.mapping_state in {
            "exact_verified",
            "approved_alias",
        }
        eligible = (
            eligible_mapping
            and self.mapping_accepted
            and self.candidate_attribute_code is not None
            and self.binding_status == "active"
            and self.binding_current
            and self.entitlement_verified
        )
        if self.provider_authoritative != eligible:
            raise ValueError(
                "Provider authority must derive only from an accepted exact or "
                "approved-alias mapping under a current entitled binding."
            )
        expected_authorities = {
            "exact_verified": "provider_exact",
            "approved_alias": "provider_definition_via_approved_alias",
        }
        if eligible and self.authority_state != expected_authorities[self.mapping_state]:
            raise ValueError("The provider authority basis contradicts mapping state.")
        if eligible and self.non_authoritative_reasons:
            raise ValueError("An authoritative annotation cannot carry denial reasons.")
        if not eligible:
            if not self.authority_state.startswith("non_authoritative_"):
                raise ValueError("A non-authoritative annotation must say so explicitly.")
            if not self.non_authoritative_reasons:
                raise ValueError("A non-authoritative annotation requires a reason.")
        if (self.crosswalk_id is None) != (self.crosswalk_revision is None):
            raise ValueError("Crosswalk identity and revision must be recorded together.")
        if len(self.special_definitions) > 64:
            raise ValueError("At most 64 bounded special definitions may be exposed.")
        definition_ids = [item.definition_id for item in self.special_definitions]
        if len(definition_ids) != len(set(definition_ids)):
            raise ValueError("Special definition references must be unique.")
        if self.candidate_attribute_code is None and (
            self.description
            or self.data_type
            or self.units
            or self.attribute_definition_checksum
            or self.ordinary_range
            or self.special_definitions
        ):
            raise ValueError("An unresolved annotation cannot expose attribute semantics.")
        if self.candidate_attribute_code is not None:
            if (
                self.ordinary_range
                and self.ordinary_range.attribute_code
                != self.candidate_attribute_code
            ):
                raise ValueError("Ordinary range must match the candidate attribute.")
            if any(
                item.attribute_code != self.candidate_attribute_code
                for item in self.special_definitions
            ):
                raise ValueError("Special definitions must match the candidate attribute.")
        return self


def _authority_result(
    *,
    binding: DatasetCatalogBindingRevision,
    decision: GovernedMappingDecision,
    binding_current: bool,
    entitlement_verified: bool,
) -> tuple[BureauSemanticAuthorityState, bool, tuple[str, ...]]:
    if binding.status != "active" or not binding_current:
        return "non_authoritative_stale", False, ("binding_not_current",)
    if not entitlement_verified:
        return "non_authoritative_unentitled", False, ("entitlement_not_verified",)
    if decision.mapping_state == "exact_verified" and decision.analyst_confirmed:
        return "provider_exact", True, ()
    if decision.mapping_state == "approved_alias" and decision.analyst_confirmed:
        return "provider_definition_via_approved_alias", True, ()
    if decision.mapping_state == "transformed_or_derived":
        return "non_authoritative_derived", False, ("derived_mapping",)
    if decision.mapping_state in {
        "probable_review_required",
        "ambiguous_review_required",
        "recoding_evidence_required",
    }:
        return "non_authoritative_review_required", False, ("review_required",)
    if decision.mapping_state == "unresolved":
        return "non_authoritative_unresolved", False, ("mapping_unresolved",)
    return "non_authoritative_mapping", False, (
        f"mapping_{decision.mapping_state}",
    )


def build_bureau_semantic_annotation(
    *,
    binding: DatasetCatalogBindingRevision,
    decision: GovernedMappingDecision,
    binding_current: bool,
    entitlement_verified: bool,
    description: str | None = None,
    data_type: str | None = None,
    units: str | None = None,
    attribute_definition_checksum: str | None = None,
    ordinary_range: BureauOrdinaryRangeReference | None = None,
    special_definitions: tuple[BureauSpecialDefinitionReference, ...] = (),
) -> BureauSemanticAnnotation:
    authority_state, authoritative, reasons = _authority_result(
        binding=binding,
        decision=decision,
        binding_current=binding_current,
        entitlement_verified=entitlement_verified,
    )
    annotation_identity = {
        "binding_id": binding.binding_id,
        "binding_revision": binding.revision,
        "binding_revision_checksum": binding.revision_checksum,
        "dataset_field": decision.dataset_field,
        "mapping_state": decision.mapping_state,
        "candidate_attribute_code": decision.candidate_attribute_code,
    }
    annotation_id = "bsa_" + hashlib.sha256(
        canonical_json_bytes(annotation_identity)
    ).hexdigest()[:32]
    identity = binding.identity
    return BureauSemanticAnnotation(
        annotation_id=annotation_id,
        dataset_field=decision.dataset_field,
        mapping_state=decision.mapping_state,
        mapping_accepted=decision.analyst_confirmed,
        candidate_attribute_code=decision.candidate_attribute_code,
        authority_state=authority_state,
        provider_authoritative=authoritative,
        non_authoritative_reasons=reasons,
        binding_id=binding.binding_id,
        binding_revision=binding.revision,
        binding_revision_checksum=binding.revision_checksum,
        binding_status=binding.status,
        binding_current=binding_current,
        entitlement_verified=entitlement_verified,
        crosswalk_id=binding.crosswalk_id,
        crosswalk_revision=binding.crosswalk_revision,
        catalog_version_id=identity.catalog_version_id,
        catalog_key=identity.catalog_key,
        catalog_checksum=identity.catalog_checksum,
        description=description,
        data_type=data_type,
        units=units,
        attribute_definition_checksum=attribute_definition_checksum,
        ordinary_range=ordinary_range,
        special_definitions=tuple(
            sorted(special_definitions, key=lambda item: item.definition_id)
        ),
        dataset_mutated=False,
        target_contract_mutated=False,
        treatment_mutated=False,
        predictor_authorization_mutated=False,
        analysis_partition_mutated=False,
        feature_manifest_mutated=False,
    )


__all__ = [
    "BureauOrdinaryRangeReference",
    "BureauSemanticAnnotation",
    "BureauSemanticAuthorityState",
    "BureauSpecialDefinitionReference",
    "build_bureau_semantic_annotation",
]

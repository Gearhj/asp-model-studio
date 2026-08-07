"""Immutable, provider-neutral contracts for restricted bureau metadata.

The contracts in this module contain no storage, HTTP, project, or workflow
behavior.  Catalog identity is always the complete provider/product/edition/
dictionary-version tuple and content is additionally pinned by SHA-256.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


Sha256 = str
CatalogOperation = Literal[
    "catalog_health",
    "manifest_read",
    "attribute_lookup",
    "special_value_lookup",
    "value_classification",
    "crosswalk_candidate",
]
NumericType = Literal["integer", "decimal", "text", "date", "unknown"]
ValueClass = Literal[
    "ordinary_valid",
    "bureau_special",
    "true_null",
    "parse_failure",
    "unexpected_invalid",
]

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


def _clean_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be blank.")
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise ValueError(f"{field_name} cannot contain control characters.")
    return cleaned


def _clean_multiline_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    cleaned = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be blank.")
    if any(
        (ord(character) < 32 and character not in {"\n", "\t"})
        or ord(character) == 127
        for character in cleaned
    ):
        raise ValueError(f"{field_name} contains an unsupported control character.")
    return cleaned


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BureauCatalogKey(_FrozenContract):
    provider: str
    product: str
    edition: str
    dictionary_version: str = Field(
        validation_alias=AliasChoices("dictionary_version", "version")
    )

    @field_validator("provider", "product", "edition", "dictionary_version", mode="before")
    @classmethod
    def validate_key_part(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name)

    @property
    def version(self) -> str:
        """Compatibility accessor; serialization remains ``dictionary_version``."""

        return self.dictionary_version


class BureauCatalogFileDescriptor(_FrozenContract):
    relative_path: str
    sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=0)
    record_count: int = Field(ge=0)
    media_type: Literal[
        "application/x-ndjson",
        "application/json",
        "text/plain",
    ] = (
        "application/x-ndjson"
    )

    @field_validator("relative_path", mode="before")
    @classmethod
    def validate_relative_path_text(cls, value: Any) -> str:
        return _clean_text(value, "relative_path")


class BureauCatalogSourceDescriptor(_FrozenContract):
    """Sanitized source inventory entry; never carries a filesystem path."""

    role: Literal["canonical_pdf", "csv_staging"]
    filename: str
    suffix: str
    sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=0)

    @field_validator("filename", "suffix", mode="before")
    @classmethod
    def validate_source_text(cls, value: Any, info: ValidationInfo) -> str:
        cleaned = _clean_text(value, info.field_name)
        if info.field_name == "filename" and ("/" in cleaned or "\\" in cleaned):
            raise ValueError("filename must be a basename, not a path.")
        if info.field_name == "suffix" and not cleaned.startswith("."):
            raise ValueError("suffix must include its leading dot.")
        return cleaned


class BureauCatalogLicenseMetadata(_FrozenContract):
    classification: Literal[
        "restricted_vendor_metadata",
        "internal_reference",
    ] = "restricted_vendor_metadata"
    policy_id: str
    policy_version: str
    allowed_operations: frozenset[CatalogOperation] = Field(default_factory=frozenset)
    redistribution_status: Literal["prohibited", "unresolved", "permitted"] = (
        "prohibited"
    )
    source_export_allowed: bool = False
    full_catalog_api_allowed: bool = False
    tenant_sharing_allowed: bool = False
    public_demo_allowed: bool = False
    legal_review_required: bool = True

    @field_validator("policy_id", "policy_version", mode="before")
    @classmethod
    def validate_policy_text(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name)


class BureauSourceReference(_FrozenContract):
    source_document_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    source_locator: str
    extraction_method: Literal[
        "pdf_text",
        "pdfplumber_table",
        "pdf_ocr",
        "csv",
        "manual_review",
        "derived_reconciliation",
    ]
    confidence: Literal["high", "medium", "low", "unreviewed"] = "unreviewed"

    @field_validator("source_locator", mode="before")
    @classmethod
    def validate_locator(cls, value: Any) -> str:
        return _clean_text(value, "source_locator")


class BureauAttributeDefinition(_FrozenContract):
    catalog_key: BureauCatalogKey
    catalog_checksum: Sha256 = Field(pattern=_SHA256_PATTERN)
    sequence: int = Field(ge=1)
    attribute_code: str
    description: str
    numeric_type: NumericType = Field(
        default="unknown",
        validation_alias=AliasChoices("numeric_type", "data_type"),
    )
    units: str | None = None
    field_length: int | None = Field(default=None, ge=1)
    valid_range_expression: str | None = None
    ordinary_min: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ordinary_min", "ordinary_valid_min", "valid_min"),
    )
    ordinary_max: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ordinary_max", "ordinary_valid_max", "valid_max"),
    )
    valid_values: tuple[str, ...] = ()
    applicable_versions: tuple[str, ...] = ()
    cross_bureau_availability: tuple[str, ...] = ()
    leveling_indicator: str | None = None
    archive_indicator: str | None = None
    parser_notes: tuple[str, ...] = ()
    source_row: int | None = Field(default=None, ge=1)
    source_references: tuple[BureauSourceReference, ...] = ()
    reconciliation_status: Literal[
        "matched",
        "pdf_only",
        "csv_only",
        "conflict",
        "unreviewed",
    ] = "unreviewed"
    review_status: Literal["unreviewed", "reviewed", "approved", "rejected"] = (
        "unreviewed"
    )
    created_at: str
    record_checksum: Sha256 = Field(pattern=_SHA256_PATTERN)

    @field_validator("attribute_code", "created_at", mode="before")
    @classmethod
    def validate_required_text(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name)

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, value: Any) -> str:
        return _clean_multiline_text(value, "description")

    @field_validator(
        "units",
        "valid_range_expression",
        "ordinary_min",
        "ordinary_max",
        "leveling_indicator",
        "archive_indicator",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(
        cls,
        value: Any,
        info: ValidationInfo,
    ) -> str | None:
        if value is None:
            return None
        if info.field_name in {
            "units",
            "valid_range_expression",
            "leveling_indicator",
            "archive_indicator",
        }:
            return _clean_multiline_text(value, info.field_name)
        return _clean_text(value, info.field_name)

    @property
    def data_type(self) -> NumericType:
        return self.numeric_type


class BureauSpecialValueDefinition(_FrozenContract):
    catalog_key: BureauCatalogKey
    catalog_checksum: Sha256 = Field(pattern=_SHA256_PATTERN)
    attribute_code: str
    value_code: str
    meaning: str
    semantic_family: Literal[
        "no_hit",
        "not_applicable",
        "insufficient_history",
        "suppressed",
        "frozen",
        "unavailable",
        "unknown",
        "exception",
        "other",
    ] = "other"
    semantic_confidence: Literal["high", "medium", "low", "unreviewed"] = (
        "unreviewed"
    )
    source_page: int | None = Field(default=None, ge=1)
    source_sequence: int | None = Field(default=None, ge=1)
    source_references: tuple[BureauSourceReference, ...] = ()
    is_bureau_special: Literal[True] = True
    is_true_null: Literal[False] = False
    is_parse_failure: Literal[False] = False
    is_ordinary_outlier: Literal[False] = False
    analyst_review_required: bool = True
    review_status: Literal["unreviewed", "reviewed", "approved", "rejected"] = (
        "unreviewed"
    )
    treatment_recommendation_status: Literal[
        "unreviewed",
        "candidate",
        "reviewed",
    ] = "unreviewed"
    treatment_policy_reference: str | None = None
    created_at: str | None = None
    definition_id: str
    definition_checksum: Sha256 = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "attribute_code",
        "value_code",
        "definition_id",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name)

    @field_validator("meaning", mode="before")
    @classmethod
    def validate_meaning(cls, value: Any) -> str:
        return _clean_multiline_text(value, "meaning")

    @field_validator("treatment_policy_reference", mode="before")
    @classmethod
    def normalize_policy_reference(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _clean_text(value, "treatment_policy_reference")

    @field_validator("created_at", mode="before")
    @classmethod
    def normalize_created_at(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _clean_text(value, "created_at")

    @property
    def exact_source_meaning(self) -> str:
        return self.meaning


class BureauCatalogValidationFinding(_FrozenContract):
    finding_id: str
    catalog_key: BureauCatalogKey
    finding_type: Literal[
        "source_conflict",
        "duplicate_attribute",
        "duplicate_special_value",
        "missing_required_field",
        "invalid_range",
        "orphan_special_value",
        "checksum_mismatch",
        "parser_warning",
        "other",
    ]
    severity: Literal["info", "warning", "error", "critical"]
    status: Literal["open", "resolved", "accepted", "rejected"] = "open"
    attribute_code: str | None = None
    value_code: str | None = None
    message: str
    source_references: tuple[BureauSourceReference, ...] = ()
    selected_value: str | None = None
    selection_basis: str | None = None
    reviewer: str | None = None
    created_at: str
    resolved_at: str | None = None

    @field_validator("finding_id", "message", "created_at", mode="before")
    @classmethod
    def validate_required_text(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name)


class BureauTokenMatchEvidence(_FrozenContract):
    overlap_tokens: tuple[str, ...] = ()
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class BureauCompatibilityEvidence(_FrozenContract):
    comparable: bool = False
    compatible: bool | None = None


class BureauValidRangeEvidence(BureauCompatibilityEvidence):
    observed_range_present: bool = False
    catalog_range_present: bool = False


class BureauSpecialValueMatchEvidence(_FrozenContract):
    observed_values: tuple[str, ...] = ()
    negative_recodes_present: bool = False
    durable_recode_evidence_present: bool = False
    source_meaning_assignment: Literal[
        "withheld_pending_durable_recode_evidence",
        "not_assigned_by_crosswalk",
    ] = "not_assigned_by_crosswalk"


class BureauAttributeMatchCandidate(_FrozenContract):
    dataset_field: str
    catalog_key: BureauCatalogKey
    catalog_checksum: Sha256 = Field(pattern=_SHA256_PATTERN)
    candidate_attribute_code: str | None = None
    match_status: Literal[
        "exact_dictionary_code_match",
        "approved_institutional_alias",
        "probable_semantic_match",
        "multiple_possible_matches",
        "no_supported_match",
        "unresolved_recoding",
        "non_catalog_field",
        "target",
        "deterministic_target_source",
    ]
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    name_evidence: BureauTokenMatchEvidence = Field(
        default_factory=BureauTokenMatchEvidence
    )
    description_evidence: BureauTokenMatchEvidence = Field(
        default_factory=BureauTokenMatchEvidence
    )
    units_evidence: BureauCompatibilityEvidence = Field(
        default_factory=BureauCompatibilityEvidence
    )
    valid_range_evidence: BureauValidRangeEvidence = Field(
        default_factory=BureauValidRangeEvidence
    )
    special_value_evidence: BureauSpecialValueMatchEvidence = Field(
        default_factory=BureauSpecialValueMatchEvidence
    )
    ambiguity: tuple[str, ...] = ()
    required_analyst_confirmation: bool = True
    transformation_or_recoding_concerns: tuple[str, ...] = ()
    institutional_alias_reference: str | None = None
    analyst_confirmed: Literal[False] = False
    candidate_only: Literal[True] = True
    approved_mapping: Literal[False] = False

    @model_validator(mode="before")
    @classmethod
    def accept_flat_catalog_key(cls, value: Any) -> Any:
        if not isinstance(value, Mapping) or "catalog_key" in value:
            return value
        flattened = dict(value)
        key_names = ("provider", "product", "edition", "dictionary_version")
        if all(name in flattened for name in key_names):
            flattened["catalog_key"] = {
                name: flattened.pop(name) for name in key_names
            }
        return flattened

    @field_validator("dataset_field", mode="before")
    @classmethod
    def validate_dataset_field(cls, value: Any) -> str:
        return _clean_text(value, "dataset_field")


class BureauDatasetCrosswalk(_FrozenContract):
    crosswalk_id: str
    revision: int = Field(default=1, ge=1)
    project_id: str | None = None
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    schema_checksum: Sha256 | None = Field(default=None, pattern=_SHA256_PATTERN)
    target_contract_id: str | None = None
    predictor_authorization_id: str | None = None
    catalog_key: BureauCatalogKey
    catalog_checksum: Sha256 = Field(pattern=_SHA256_PATTERN)
    mappings: tuple[BureauAttributeMatchCandidate, ...] = ()
    crosswalk_status: Literal[
        "candidate_only",
        "partially_confirmed",
        "confirmed",
        "rejected",
    ] = "candidate_only"
    candidate_only: Literal[True] = True
    approved_mappings: tuple[str, ...] = ()
    governed_feature_set_changed: Literal[False] = False
    dataset_mutated: Literal[False] = False
    created_by: str
    created_at: str
    crosswalk_checksum: Sha256 = Field(pattern=_SHA256_PATTERN)

    @field_validator("crosswalk_id", "created_by", "created_at", mode="before")
    @classmethod
    def validate_required_text(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name)


class BureauCatalogManifest(_FrozenContract):
    schema_version: str = "1.0"
    catalog_id: str
    catalog_key: BureauCatalogKey = Field(
        validation_alias=AliasChoices("catalog_key", "key")
    )
    catalog_checksum: Sha256 = Field(pattern=_SHA256_PATTERN)
    attribute_file: BureauCatalogFileDescriptor
    special_value_file: BureauCatalogFileDescriptor
    validation_file: BureauCatalogFileDescriptor | None = None
    lookup_index_file: BureauCatalogFileDescriptor | None = None
    reconciliation_file: BureauCatalogFileDescriptor | None = None
    build_log_file: BureauCatalogFileDescriptor | None = None
    source_files: tuple[BureauCatalogSourceDescriptor, ...] = ()
    attribute_count: int = Field(ge=0)
    special_value_count: int = Field(ge=0)
    validation_finding_count: int = Field(default=0, ge=0)
    parse_warning_count: int = Field(default=0, ge=0)
    reconciliation_conflict_count: int = Field(default=0, ge=0)
    unresolved_count: int = Field(default=0, ge=0)
    validation_status: Literal["passed", "passed_with_warnings", "failed"]
    license: BureauCatalogLicenseMetadata
    restricted_export: Literal[True] = True
    full_catalog_path: Literal["."] = "."
    builder_name: str
    builder_version: str
    built_at: str
    built_by: str
    source_control_commit: str

    @field_validator(
        "schema_version",
        "catalog_id",
        "builder_name",
        "builder_version",
        "built_at",
        "built_by",
        "source_control_commit",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name)

    @property
    def key(self) -> BureauCatalogKey:
        return self.catalog_key


class BureauCatalogAccessContext(_FrozenContract):
    principal_id: str
    tenant_id: str | None = None
    project_id: str | None = None

    @field_validator("principal_id", mode="before")
    @classmethod
    def validate_principal(cls, value: Any) -> str:
        return _clean_text(value, "principal_id")


class BureauCatalogAccessGrant(_FrozenContract):
    grant_id: str
    principal_id: str
    tenant_id: str | None = None
    catalog_key: BureauCatalogKey
    catalog_checksum: Sha256 = Field(pattern=_SHA256_PATTERN)
    operation: CatalogOperation
    expires_at: str | None = None

    @field_validator("grant_id", "principal_id", mode="before")
    @classmethod
    def validate_grant_text(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name)


class BureauAttributeResolution(_FrozenContract):
    catalog_key: BureauCatalogKey
    catalog_checksum: Sha256 = Field(pattern=_SHA256_PATTERN)
    requested_attribute_code: str
    status: Literal["resolved", "unresolved"]
    attribute: BureauAttributeDefinition | None = None
    reason: Literal["exact_match", "unknown_attribute_code", "invalid_attribute_code"]

    @field_validator("requested_attribute_code", mode="before")
    @classmethod
    def validate_requested_code(cls, value: Any) -> str:
        return _clean_text(value, "requested_attribute_code")

    @model_validator(mode="after")
    def validate_resolution(self) -> "BureauAttributeResolution":
        if self.status == "resolved":
            if self.attribute is None or self.reason != "exact_match":
                raise ValueError("A resolved attribute requires one exact match.")
        elif self.attribute is not None or self.reason == "exact_match":
            raise ValueError("An unresolved attribute cannot contain a match.")
        return self


class BureauValueClassification(_FrozenContract):
    catalog_key: BureauCatalogKey
    catalog_checksum: Sha256 = Field(pattern=_SHA256_PATTERN)
    attribute_code: str
    observed_value_code: str | None
    classification: ValueClass
    ordinary_outlier: bool = False
    definition_id: str | None = None
    definition_checksum: Sha256 | None = Field(default=None, pattern=_SHA256_PATTERN)
    reason: str

    @model_validator(mode="after")
    def validate_classification_invariants(self) -> "BureauValueClassification":
        if self.ordinary_outlier and self.classification != "ordinary_valid":
            raise ValueError(
                "ordinary_outlier can be true only for an ordinary valid value."
            )
        has_definition = bool(self.definition_id or self.definition_checksum)
        if self.classification == "bureau_special":
            if not self.definition_id or not self.definition_checksum:
                raise ValueError(
                    "Bureau-special classification requires an exact definition reference."
                )
        elif has_definition:
            raise ValueError(
                "Only bureau-special classifications may reference a special definition."
            )
        return self


__all__ = [
    "BureauAttributeDefinition",
    "BureauAttributeResolution",
    "BureauAttributeMatchCandidate",
    "BureauCatalogAccessContext",
    "BureauCatalogAccessGrant",
    "BureauCatalogFileDescriptor",
    "BureauCatalogKey",
    "BureauCatalogLicenseMetadata",
    "BureauCatalogManifest",
    "BureauCatalogSourceDescriptor",
    "BureauCatalogValidationFinding",
    "BureauCompatibilityEvidence",
    "BureauDatasetCrosswalk",
    "BureauSourceReference",
    "BureauSpecialValueDefinition",
    "BureauSpecialValueMatchEvidence",
    "BureauTokenMatchEvidence",
    "BureauValidRangeEvidence",
    "BureauValueClassification",
    "CatalogOperation",
    "NumericType",
    "Sha256",
    "ValueClass",
]

"""Provider-neutral governance contracts for dataset-to-bureau crosswalks.

This module intentionally contains no dataset writer, predictor-authority writer,
catalog loader, HTTP route, or persistence implementation.  It records bounded
references to externally retained evidence and pins every decision to one exact
project, dataset version, authorization contract, and catalog checksum.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from .normalizer import canonical_json_bytes
from .types import BureauCatalogKey


MappingGovernanceState = Literal[
    "exact_verified",
    "approved_alias",
    "transformed_or_derived",
    "probable_review_required",
    "ambiguous_review_required",
    "recoding_evidence_required",
    "unresolved",
    "out_of_catalog",
    "rejected",
]
CrosswalkLifecycleState = Literal["draft", "review_required", "confirmed"]
CrosswalkEvidenceKind = Literal[
    "catalog_definition",
    "exact_match",
    "institutional_alias",
    "transformation_lineage",
    "semantic_analysis",
    "ambiguity_analysis",
    "recoding_observation",
    "unresolved_assessment",
    "out_of_catalog_assessment",
    "analyst_review",
]

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SENSITIVE_AUDIT_FRAGMENTS = (
    "authorization",
    "connection_string",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
)
_CONFIRMABLE_STATES = frozenset(
    {
        "exact_verified",
        "approved_alias",
        "transformed_or_derived",
        "out_of_catalog",
        "rejected",
    }
)


def _clean_text(value: Any, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be blank.")
    if len(cleaned) > maximum:
        raise ValueError(f"{field_name} exceeds the {maximum}-character limit.")
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise ValueError(f"{field_name} cannot contain control characters.")
    return cleaned


def _validate_timestamp(value: Any, field_name: str) -> str:
    cleaned = _clean_text(value, field_name, maximum=64)
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CrosswalkAuditLabel(_FrozenContract):
    """A deliberately small, flat audit label; arbitrary payloads are prohibited."""

    key: str
    value: str

    @field_validator("key", mode="before")
    @classmethod
    def validate_key(cls, value: Any) -> str:
        cleaned = _clean_text(value, "key", maximum=64).lower()
        normalized = cleaned.replace("-", "_").replace(" ", "_")
        if any(fragment in normalized for fragment in _SENSITIVE_AUDIT_FRAGMENTS):
            raise ValueError("Sensitive audit label keys are prohibited.")
        return normalized

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: Any) -> str:
        return _clean_text(value, "value", maximum=256)


class CrosswalkAuditMetadata(_FrozenContract):
    actor_id: str
    request_id: str
    occurred_at: str
    reason: str
    labels: tuple[CrosswalkAuditLabel, ...] = ()

    @field_validator("actor_id", "request_id", mode="before")
    @classmethod
    def validate_identifier(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name, maximum=128)

    @field_validator("reason", mode="before")
    @classmethod
    def validate_reason(cls, value: Any) -> str:
        return _clean_text(value, "reason", maximum=1024)

    @field_validator("occurred_at", mode="before")
    @classmethod
    def validate_occurred_at(cls, value: Any) -> str:
        return _validate_timestamp(value, "occurred_at")

    @model_validator(mode="after")
    def validate_labels(self) -> "CrosswalkAuditMetadata":
        if len(self.labels) > 16:
            raise ValueError("Audit metadata is limited to 16 labels.")
        keys = [label.key for label in self.labels]
        if len(keys) != len(set(keys)):
            raise ValueError("Audit label keys must be unique.")
        if keys != sorted(keys):
            raise ValueError("Audit labels must be sorted by key.")
        return self


class CrosswalkEvidenceReference(_FrozenContract):
    """Bounded evidence identity; evidence content remains in its authority system."""

    evidence_id: str
    evidence_kind: CrosswalkEvidenceKind
    authority_id: str
    checksum: str = Field(pattern=_SHA256_PATTERN)
    created_by: str
    created_at: str

    @field_validator("evidence_id", "authority_id", "created_by", mode="before")
    @classmethod
    def validate_identifier(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name, maximum=160)

    @field_validator("created_at", mode="before")
    @classmethod
    def validate_created_at(cls, value: Any) -> str:
        return _validate_timestamp(value, "created_at")


class GovernedMappingDecision(_FrozenContract):
    dataset_field: str
    mapping_state: MappingGovernanceState
    candidate_attribute_code: str | None = None
    alternative_attribute_codes: tuple[str, ...] = ()
    source_attribute_codes: tuple[str, ...] = ()
    evidence: tuple[CrosswalkEvidenceReference, ...]
    analyst_confirmed: bool = False
    rationale: str | None = None
    alias_authority_id: str | None = None
    institutional_alias_reference: str | None = None
    transformation_reference_id: str | None = None
    transformation_rule: str | None = None
    transformation_or_recoding_concerns: tuple[str, ...] = ()
    data_type: str | None = None
    units: str | None = None
    source_system: str | None = None
    timing: str | None = None
    special_value_handling: str | None = None
    value_range_reconciliation: str | None = None
    special_value_reconciliation: str | None = None
    reviewer_id: str | None = None

    @field_validator("dataset_field", mode="before")
    @classmethod
    def validate_dataset_field(cls, value: Any) -> str:
        return _clean_text(value, "dataset_field", maximum=256)

    @field_validator(
        "candidate_attribute_code",
        "alias_authority_id",
        "institutional_alias_reference",
        "transformation_reference_id",
        "data_type",
        "units",
        "source_system",
        "reviewer_id",
        mode="before",
    )
    @classmethod
    def validate_optional_identifier(
        cls, value: Any, info: ValidationInfo
    ) -> str | None:
        if value is None:
            return None
        maximum = 128 if info.field_name in {"data_type", "units", "reviewer_id"} else 256
        return _clean_text(value, info.field_name, maximum=maximum)

    @field_validator(
        "transformation_rule",
        "timing",
        "special_value_handling",
        "value_range_reconciliation",
        "special_value_reconciliation",
        mode="before",
    )
    @classmethod
    def validate_optional_operational_text(
        cls, value: Any, info: ValidationInfo
    ) -> str | None:
        if value is None:
            return None
        maximum = 2048 if info.field_name == "transformation_rule" else 1024
        return _clean_text(value, info.field_name, maximum=maximum)

    @field_validator("rationale", mode="before")
    @classmethod
    def validate_optional_rationale(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _clean_text(value, "rationale", maximum=2048)

    @field_validator("alternative_attribute_codes", mode="before")
    @classmethod
    def normalize_alternatives(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, (tuple, list, set, frozenset)):
            raise ValueError("alternative_attribute_codes must be a bounded sequence.")
        cleaned = tuple(
            sorted(
                {
                    _clean_text(item, "alternative_attribute_codes", maximum=256)
                    for item in value
                }
            )
        )
        if len(cleaned) > 32:
            raise ValueError("At most 32 alternative attribute codes may be recorded.")
        return cleaned

    @field_validator("source_attribute_codes", mode="before")
    @classmethod
    def normalize_source_codes(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, (tuple, list, set, frozenset)):
            raise ValueError("source_attribute_codes must be a bounded sequence.")
        cleaned = tuple(
            sorted(
                {
                    _clean_text(item, "source_attribute_codes", maximum=256)
                    for item in value
                }
            )
        )
        if len(cleaned) > 32:
            raise ValueError("At most 32 source attribute codes may be recorded.")
        return cleaned

    @field_validator("transformation_or_recoding_concerns", mode="before")
    @classmethod
    def normalize_transformation_concerns(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, (tuple, list, set, frozenset)):
            raise ValueError(
                "transformation_or_recoding_concerns must be a bounded sequence."
            )
        cleaned = tuple(
            sorted(
                {
                    _clean_text(
                        item,
                        "transformation_or_recoding_concerns",
                        maximum=512,
                    )
                    for item in value
                }
            )
        )
        if len(cleaned) > 16:
            raise ValueError(
                "At most 16 transformation or recoding concerns may be recorded."
            )
        return cleaned

    @model_validator(mode="after")
    def validate_state_evidence(self) -> "GovernedMappingDecision":
        if not self.evidence:
            raise ValueError("Every governed mapping decision requires evidence.")
        if len(self.evidence) > 32:
            raise ValueError("A mapping decision is limited to 32 evidence references.")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Evidence references must be unique.")

        kinds = {item.evidence_kind for item in self.evidence}
        required: dict[str, frozenset[str]] = {
            "exact_verified": frozenset(
                {"catalog_definition", "exact_match", "analyst_review"}
            ),
            "approved_alias": frozenset({"institutional_alias", "analyst_review"}),
            "transformed_or_derived": frozenset(
                {"transformation_lineage", "analyst_review"}
            ),
            "probable_review_required": frozenset({"semantic_analysis"}),
            "ambiguous_review_required": frozenset({"ambiguity_analysis"}),
            "recoding_evidence_required": frozenset({"recoding_observation"}),
            "unresolved": frozenset({"unresolved_assessment"}),
            "out_of_catalog": frozenset(
                {"out_of_catalog_assessment", "analyst_review"}
            ),
            "rejected": frozenset({"analyst_review"}),
        }
        missing = required[self.mapping_state] - kinds
        if missing:
            raise ValueError(
                f"{self.mapping_state} is missing required evidence: "
                + ", ".join(sorted(missing))
                + "."
            )

        requires_candidate = self.mapping_state in {
            "exact_verified",
            "approved_alias",
            "transformed_or_derived",
            "probable_review_required",
            "recoding_evidence_required",
        }
        if requires_candidate and self.candidate_attribute_code is None:
            raise ValueError(f"{self.mapping_state} requires one candidate attribute code.")
        if self.mapping_state == "out_of_catalog" and self.candidate_attribute_code:
            raise ValueError("out_of_catalog cannot name a catalog candidate.")
        if self.mapping_state == "ambiguous_review_required":
            possibilities = set(self.alternative_attribute_codes)
            if self.candidate_attribute_code:
                possibilities.add(self.candidate_attribute_code)
            if len(possibilities) < 2:
                raise ValueError(
                    "ambiguous_review_required requires at least two alternatives."
                )
        elif self.alternative_attribute_codes:
            raise ValueError(
                "Alternative attribute codes are reserved for ambiguous review."
            )

        evidence_by_kind: dict[str, tuple[CrosswalkEvidenceReference, ...]] = {
            kind: tuple(item for item in self.evidence if item.evidence_kind == kind)
            for kind in kinds
        }
        if self.mapping_state == "approved_alias":
            if not self.alias_authority_id:
                raise ValueError("approved_alias requires an alias authority reference.")
            if not self.institutional_alias_reference:
                raise ValueError(
                    "approved_alias requires the exact institutional alias reference."
                )
            alias_evidence = evidence_by_kind.get("institutional_alias", ())
            if not any(
                item.evidence_id == self.institutional_alias_reference
                and item.authority_id == self.alias_authority_id
                for item in alias_evidence
            ):
                raise ValueError(
                    "approved_alias must pin matching institutional alias evidence."
                )
        elif self.institutional_alias_reference or self.alias_authority_id:
            raise ValueError(
                "Institutional alias references are reserved for approved_alias."
            )

        if self.mapping_state == "transformed_or_derived":
            if not self.source_attribute_codes:
                raise ValueError(
                    "transformed_or_derived requires at least one source attribute code."
                )
            if not (self.transformation_reference_id or self.transformation_rule):
                raise ValueError(
                    "transformed_or_derived requires a documented transformation rule or reference."
                )
            transformation_evidence = evidence_by_kind.get(
                "transformation_lineage", ()
            )
            if self.transformation_reference_id and not any(
                item.evidence_id == self.transformation_reference_id
                for item in transformation_evidence
            ):
                raise ValueError(
                    "transformation_reference_id must match transformation lineage evidence."
                )
            operational_fields = {
                "data_type": self.data_type,
                "units": self.units,
                "source_system": self.source_system,
                "timing": self.timing,
                "special_value_handling": self.special_value_handling,
                "value_range_reconciliation": self.value_range_reconciliation,
                "special_value_reconciliation": self.special_value_reconciliation,
            }
            missing_operational = sorted(
                field_name
                for field_name, field_value in operational_fields.items()
                if not field_value
            )
            if missing_operational:
                raise ValueError(
                    "transformed_or_derived is missing operational fields: "
                    + ", ".join(missing_operational)
                    + "."
                )
            if not self.transformation_or_recoding_concerns:
                raise ValueError(
                    "transformed_or_derived requires bounded transformation or recoding concerns."
                )
        if (
            self.mapping_state == "recoding_evidence_required"
            and not self.transformation_or_recoding_concerns
        ):
            raise ValueError(
                "recoding_evidence_required requires bounded recoding concerns."
            )

        should_be_confirmed = self.mapping_state in _CONFIRMABLE_STATES
        if self.analyst_confirmed != should_be_confirmed:
            expected = "true" if should_be_confirmed else "false"
            raise ValueError(
                f"analyst_confirmed must be {expected} for {self.mapping_state}."
            )
        if self.mapping_state == "rejected" and not self.rationale:
            raise ValueError("rejected requires a bounded analyst rationale.")
        if should_be_confirmed:
            if not self.reviewer_id:
                raise ValueError(
                    f"{self.mapping_state} requires an explicit reviewer_id."
                )
            if not self.rationale:
                raise ValueError(
                    f"{self.mapping_state} requires a bounded analyst rationale."
                )
            review_evidence = evidence_by_kind.get("analyst_review", ())
            if not any(
                item.created_by == self.reviewer_id for item in review_evidence
            ):
                raise ValueError(
                    "reviewer_id must match the analyst-review evidence creator."
                )
        return self


class CrosswalkLineage(_FrozenContract):
    project_id: str
    dataset_id: str
    dataset_version_id: str
    activation_revision: int = Field(ge=1)
    target_contract_id: str
    predictor_authorization_id: str
    schema_checksum: str = Field(pattern=_SHA256_PATTERN)
    catalog_key: BureauCatalogKey
    catalog_checksum: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "project_id",
        "dataset_id",
        "dataset_version_id",
        "target_contract_id",
        "predictor_authorization_id",
        mode="before",
    )
    @classmethod
    def validate_identifier(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name, maximum=256)


class GovernedCrosswalkRevision(_FrozenContract):
    governance_id: str
    revision: int = Field(ge=1)
    lifecycle_state: CrosswalkLifecycleState
    lineage: CrosswalkLineage
    source_crosswalk_id: str
    source_crosswalk_checksum: str = Field(pattern=_SHA256_PATTERN)
    decisions: tuple[GovernedMappingDecision, ...]
    audit: CrosswalkAuditMetadata
    previous_revision_checksum: str | None = Field(
        default=None, pattern=_SHA256_PATTERN
    )
    revision_checksum: str = Field(pattern=_SHA256_PATTERN)
    source_candidate_only: Literal[True] = True
    dataset_mutated: Literal[False] = False
    target_contract_mutated: Literal[False] = False
    predictor_authorization_mutated: Literal[False] = False
    analysis_partition_mutated: Literal[False] = False
    feature_manifest_mutated: Literal[False] = False
    treatment_mutated: Literal[False] = False

    @field_validator("governance_id", "source_crosswalk_id", mode="before")
    @classmethod
    def validate_identifier(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name, maximum=256)

    @model_validator(mode="after")
    def validate_decisions_and_lifecycle(self) -> "GovernedCrosswalkRevision":
        if not self.decisions:
            raise ValueError("A governed crosswalk requires at least one mapping decision.")
        if len(self.decisions) > 10_000:
            raise ValueError("A governed crosswalk is limited to 10,000 decisions.")
        fields = [decision.dataset_field for decision in self.decisions]
        if len(fields) != len(set(fields)):
            raise ValueError("A governed crosswalk may contain one decision per field.")
        if fields != sorted(fields):
            raise ValueError("Governed mapping decisions must be sorted by dataset field.")
        all_confirmable = all(
            decision.mapping_state in _CONFIRMABLE_STATES
            for decision in self.decisions
        )
        if self.lifecycle_state == "confirmed" and not all_confirmable:
            raise ValueError(
                "A crosswalk cannot be confirmed while review-required decisions remain."
            )
        if self.revision == 1 and self.previous_revision_checksum is not None:
            raise ValueError("The first revision cannot reference a previous revision.")
        if self.revision > 1 and self.previous_revision_checksum is None:
            raise ValueError("Later revisions must reference the exact previous checksum.")
        return self


def is_confirmable(decisions: tuple[GovernedMappingDecision, ...]) -> bool:
    return bool(decisions) and all(
        decision.mapping_state in _CONFIRMABLE_STATES for decision in decisions
    )


def governance_identity(
    lineage: CrosswalkLineage,
    source_crosswalk_id: str,
) -> str:
    payload = {
        "project_id": lineage.project_id,
        "dataset_id": lineage.dataset_id,
        "dataset_version_id": lineage.dataset_version_id,
        "activation_revision": lineage.activation_revision,
        "target_contract_id": lineage.target_contract_id,
        "predictor_authorization_id": lineage.predictor_authorization_id,
        "schema_checksum": lineage.schema_checksum,
        "catalog_key": lineage.catalog_key.model_dump(mode="json"),
        "catalog_checksum": lineage.catalog_checksum,
        "source_crosswalk_id": _clean_text(
            source_crosswalk_id, "source_crosswalk_id", maximum=256
        ),
    }
    return "gcw_" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()[:32]


def revision_checksum_payload(value: GovernedCrosswalkRevision | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, GovernedCrosswalkRevision):
        payload = value.model_dump(mode="json")
    else:
        payload = dict(value)
    payload.pop("revision_checksum", None)
    return payload


def calculate_revision_checksum(
    value: GovernedCrosswalkRevision | Mapping[str, Any],
) -> str:
    return hashlib.sha256(canonical_json_bytes(revision_checksum_payload(value))).hexdigest()


def build_governed_revision(
    *,
    governance_id: str,
    revision: int,
    lifecycle_state: CrosswalkLifecycleState,
    lineage: CrosswalkLineage,
    source_crosswalk_id: str,
    source_crosswalk_checksum: str,
    decisions: tuple[GovernedMappingDecision, ...],
    audit: CrosswalkAuditMetadata,
    previous_revision_checksum: str | None = None,
) -> GovernedCrosswalkRevision:
    ordered = tuple(sorted(decisions, key=lambda item: item.dataset_field))
    payload: dict[str, Any] = {
        "governance_id": governance_id,
        "revision": revision,
        "lifecycle_state": lifecycle_state,
        "lineage": lineage,
        "source_crosswalk_id": source_crosswalk_id,
        "source_crosswalk_checksum": source_crosswalk_checksum,
        "decisions": ordered,
        "audit": audit,
        "previous_revision_checksum": previous_revision_checksum,
        "source_candidate_only": True,
        "dataset_mutated": False,
        "target_contract_mutated": False,
        "predictor_authorization_mutated": False,
        "analysis_partition_mutated": False,
        "feature_manifest_mutated": False,
        "treatment_mutated": False,
    }
    payload["revision_checksum"] = calculate_revision_checksum(payload)
    return GovernedCrosswalkRevision.model_validate(payload)


__all__ = [
    "CrosswalkAuditLabel",
    "CrosswalkAuditMetadata",
    "CrosswalkEvidenceKind",
    "CrosswalkEvidenceReference",
    "CrosswalkLifecycleState",
    "CrosswalkLineage",
    "GovernedCrosswalkRevision",
    "GovernedMappingDecision",
    "MappingGovernanceState",
    "build_governed_revision",
    "calculate_revision_checksum",
    "governance_identity",
    "is_confirmable",
]

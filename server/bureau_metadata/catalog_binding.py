"""Exact, append-only dataset-version to bureau-catalog binding contracts.

The contracts in this module are provider neutral and deliberately contain no
dataset content.  A binding pins one exact project dataset version and its
current authorization contracts to one exact verified catalog snapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from .normalizer import canonical_json_bytes
from .types import BureauCatalogKey


CatalogBindingStatus = Literal["active", "stale"]
CatalogBindingEvidenceKind = Literal[
    "dataset_lineage",
    "catalog_registry",
    "catalog_entitlement",
    "crosswalk_governance",
    "analyst_review",
]

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_REQUIRED_ACTIVE_EVIDENCE = frozenset(
    {"dataset_lineage", "catalog_registry", "catalog_entitlement"}
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


def _utc_timestamp(value: Any, field_name: str) -> str:
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


class DatasetCatalogBindingScope(_FrozenContract):
    """Exact dataset authority scope with one governed current binding head."""

    tenant_id: str | None = None
    project_id: str
    dataset_id: str
    dataset_version_id: str

    @field_validator(
        "project_id",
        "dataset_id",
        "dataset_version_id",
        mode="before",
    )
    @classmethod
    def validate_identifier(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name, maximum=256)

    @field_validator("tenant_id", mode="before")
    @classmethod
    def validate_optional_tenant(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _clean_text(value, "tenant_id", maximum=256)


class DatasetVersionCatalogIdentity(DatasetCatalogBindingScope):
    """One exact catalog selection recorded within the dataset binding scope."""

    activation_revision: int = Field(ge=1)
    schema_checksum: str = Field(pattern=_SHA256_PATTERN)
    target_contract_id: str
    predictor_authorization_id: str
    catalog_version_id: str
    catalog_key: BureauCatalogKey
    catalog_checksum: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "target_contract_id",
        "predictor_authorization_id",
        "catalog_version_id",
        mode="before",
    )
    @classmethod
    def validate_identifier(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name, maximum=256)


class CatalogBindingEvidenceReference(_FrozenContract):
    """Bounded identity for evidence retained by another authority."""

    evidence_id: str
    evidence_kind: CatalogBindingEvidenceKind
    authority_id: str
    checksum: str = Field(pattern=_SHA256_PATTERN)
    recorded_at: str

    @field_validator("evidence_id", "authority_id", mode="before")
    @classmethod
    def validate_identifier(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name, maximum=160)

    @field_validator("recorded_at", mode="before")
    @classmethod
    def validate_recorded_at(cls, value: Any) -> str:
        return _utc_timestamp(value, "recorded_at")


class DatasetCatalogBindingRevision(_FrozenContract):
    """One immutable revision in a dataset-version catalog-binding history."""

    binding_id: str
    revision: int = Field(ge=1)
    status: CatalogBindingStatus
    identity: DatasetVersionCatalogIdentity
    actor_id: str
    server_recorded_at: str
    evidence: tuple[CatalogBindingEvidenceReference, ...]
    crosswalk_id: str | None = None
    crosswalk_revision: int | None = Field(default=None, ge=1)
    stale_reason: str | None = None
    previous_revision_checksum: str | None = Field(
        default=None, pattern=_SHA256_PATTERN
    )
    revision_checksum: str = Field(pattern=_SHA256_PATTERN)
    dataset_mutated: Literal[False] = False
    target_contract_mutated: Literal[False] = False
    treatment_mutated: Literal[False] = False
    predictor_authorization_mutated: Literal[False] = False
    analysis_partition_mutated: Literal[False] = False
    feature_manifest_mutated: Literal[False] = False

    @field_validator("binding_id", "actor_id", mode="before")
    @classmethod
    def validate_identifier(cls, value: Any, info: ValidationInfo) -> str:
        return _clean_text(value, info.field_name, maximum=256)

    @field_validator("crosswalk_id", mode="before")
    @classmethod
    def validate_optional_crosswalk_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _clean_text(value, "crosswalk_id", maximum=256)

    @field_validator("stale_reason", mode="before")
    @classmethod
    def validate_optional_stale_reason(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _clean_text(value, "stale_reason", maximum=1024)

    @field_validator("server_recorded_at", mode="before")
    @classmethod
    def validate_server_recorded_at(cls, value: Any) -> str:
        return _utc_timestamp(value, "server_recorded_at")

    @model_validator(mode="after")
    def validate_revision_contract(self) -> "DatasetCatalogBindingRevision":
        if not self.evidence or len(self.evidence) > 32:
            raise ValueError("A binding revision requires 1 to 32 evidence references.")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Binding evidence references must be unique.")
        kinds = {item.evidence_kind for item in self.evidence}
        if not _REQUIRED_ACTIVE_EVIDENCE.issubset(kinds):
            raise ValueError(
                "Binding evidence must pin dataset lineage, catalog registry, "
                "and catalog entitlement authorities."
            )
        if (self.crosswalk_id is None) != (self.crosswalk_revision is None):
            raise ValueError("Crosswalk identity and revision must be recorded together.")
        if self.status == "active" and self.stale_reason is not None:
            raise ValueError("An active binding cannot carry a stale reason.")
        if self.status == "stale" and self.stale_reason is None:
            raise ValueError("A stale binding requires a bounded stale reason.")
        if self.revision == 1 and self.previous_revision_checksum is not None:
            raise ValueError("The first binding revision cannot reference a predecessor.")
        if self.revision > 1 and self.previous_revision_checksum is None:
            raise ValueError("Later binding revisions require the exact previous checksum.")
        return self


def dataset_catalog_binding_scope(
    identity: DatasetVersionCatalogIdentity,
) -> DatasetCatalogBindingScope:
    return DatasetCatalogBindingScope.model_validate(
        identity.model_dump(
            mode="json",
            include={"tenant_id", "project_id", "dataset_id", "dataset_version_id"},
        )
    )


def catalog_binding_scope_identity(scope: DatasetCatalogBindingScope) -> str:
    return "bcb_" + hashlib.sha256(
        canonical_json_bytes(scope.model_dump(mode="json"))
    ).hexdigest()[:32]


def catalog_binding_identity(identity: DatasetVersionCatalogIdentity) -> str:
    """Compatibility helper returning the authoritative dataset-scope ID."""

    return catalog_binding_scope_identity(dataset_catalog_binding_scope(identity))


def binding_revision_checksum_payload(
    value: DatasetCatalogBindingRevision | Mapping[str, Any],
) -> dict[str, Any]:
    payload = (
        value.model_dump(mode="json")
        if isinstance(value, DatasetCatalogBindingRevision)
        else dict(value)
    )
    payload.pop("revision_checksum", None)
    return payload


def calculate_binding_revision_checksum(
    value: DatasetCatalogBindingRevision | Mapping[str, Any],
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(binding_revision_checksum_payload(value))
    ).hexdigest()


def build_catalog_binding_revision(
    *,
    identity: DatasetVersionCatalogIdentity,
    revision: int,
    status: CatalogBindingStatus,
    actor_id: str,
    server_recorded_at: str,
    evidence: tuple[CatalogBindingEvidenceReference, ...],
    crosswalk_id: str | None = None,
    crosswalk_revision: int | None = None,
    stale_reason: str | None = None,
    previous_revision_checksum: str | None = None,
) -> DatasetCatalogBindingRevision:
    payload: dict[str, Any] = {
        "binding_id": catalog_binding_identity(identity),
        "revision": revision,
        "status": status,
        "identity": identity,
        "actor_id": actor_id,
        "server_recorded_at": server_recorded_at,
        "evidence": tuple(sorted(evidence, key=lambda item: item.evidence_id)),
        "crosswalk_id": crosswalk_id,
        "crosswalk_revision": crosswalk_revision,
        "stale_reason": stale_reason,
        "previous_revision_checksum": previous_revision_checksum,
        "dataset_mutated": False,
        "target_contract_mutated": False,
        "treatment_mutated": False,
        "predictor_authorization_mutated": False,
        "analysis_partition_mutated": False,
        "feature_manifest_mutated": False,
    }
    payload["revision_checksum"] = calculate_binding_revision_checksum(payload)
    return DatasetCatalogBindingRevision.model_validate(payload)


__all__ = [
    "CatalogBindingEvidenceKind",
    "CatalogBindingEvidenceReference",
    "CatalogBindingStatus",
    "DatasetCatalogBindingScope",
    "DatasetCatalogBindingRevision",
    "DatasetVersionCatalogIdentity",
    "binding_revision_checksum_payload",
    "build_catalog_binding_revision",
    "calculate_binding_revision_checksum",
    "catalog_binding_identity",
    "catalog_binding_scope_identity",
    "dataset_catalog_binding_scope",
]

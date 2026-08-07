"""Exact HTTP adapter for controlled Dataset Acquisition catalog binding.

The router never selects a catalog or dataset by display name, first record,
latest record, checkpoint state, or browser state.  Preview is deterministic
and nonpersistent; confirmation revalidates the exact authorities before one
append-only binding revision is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, Mapping
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.modeling_scope import authorize_modeling_scope
from ..datasets.dataset_identity import durable_active_dataset_identity
from ..persistence.service import get_persistence_service
from ..preprocessing.predictor_authorization import (
    PredictorAuthorizationIntegrityError,
    verify_durable_predictor_authorization,
)
from ..security.security_store import require_user
from .catalog_binding import (
    CatalogBindingEvidenceReference,
    DatasetCatalogBindingRevision,
    DatasetCatalogBindingScope,
    DatasetVersionCatalogIdentity,
    catalog_binding_scope_identity,
)
from .catalog_binding_repository import (
    CatalogBindingConflictError,
    CatalogBindingNotFoundError,
    CatalogBindingRepositoryError,
    CatalogBindingRepositoryStateError,
    SQLiteCatalogBindingRepository,
)
from .catalog_binding_service import (
    CatalogBindingAccessDeniedError,
    CatalogBindingCatalogError,
    CatalogBindingCurrentResolution,
    CatalogBindingLineageError,
    CatalogBindingService,
    CatalogBindingStateError,
    ExactCatalogRegistryRecord,
    ExactDatasetLineage,
)
from .catalog_documentation import record_binding_evidence_and_documentation
from .crosswalk_governance_repository import (
    CrosswalkGovernanceNotFoundError,
    CrosswalkGovernanceRepositoryError,
    CrosswalkGovernanceStateError,
    SQLiteGovernedCrosswalkRepository,
)
from .catalog_registry import (
    CatalogRegistryError,
    CatalogRegistryNotFoundError,
    RegistryEntitlementProvider,
)
from .catalog_service import BureauCatalogAccessDeniedError
from .normalizer import canonical_json_bytes
from .operational_service import (
    CatalogOperationalError,
    OperationalCatalogService,
    get_operational_catalog_service,
)
from .restricted_storage import RestrictedStorageError
from .types import (
    BureauCatalogAccessContext,
    BureauCatalogAccessGrant,
    BureauCatalogKey,
)


router = APIRouter()

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_PREVIEW_CONTRACT_VERSION = "bureau-metadata-binding-preview-v1"
_MAX_HISTORY_LIMIT = 100


class CatalogBindingPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog_version_id: str = Field(min_length=1, max_length=256)
    catalog_checksum: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("catalog_version_id")
    @classmethod
    def validate_catalog_version_id(cls, value: str) -> str:
        cleaned = value.strip()
        if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
            raise ValueError("Catalog version identity contains unsupported characters.")
        return cleaned


class CatalogBindingConfirmRequest(CatalogBindingPreviewRequest):
    expected_revision: int = Field(ge=0)
    preview_checksum: str = Field(pattern=_SHA256_PATTERN)
    analyst_rationale: str = Field(min_length=8, max_length=1000)

    @field_validator("analyst_rationale")
    @classmethod
    def validate_rationale(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Analyst rationale contains unsupported characters.")
        cleaned = " ".join(value.split())
        if len(cleaned) < 8:
            raise ValueError("Analyst rationale must contain at least eight characters.")
        return cleaned


def _principal(user: Mapping[str, Any]) -> str:
    value = str(user.get("userId") or "").strip()
    if not value:
        raise HTTPException(status_code=401, detail="Authentication is required.")
    return value


def _tenant(user: Mapping[str, Any]) -> str | None:
    value = str(user.get("tenantId") or user.get("tenant_id") or "").strip()
    return value or None


def _bounded_path_id(value: object, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or len(cleaned) > 256 or any(
        ord(character) < 32 or ord(character) == 127 for character in cleaned
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "bureau_metadata_binding_identity_invalid",
                "message": f"The exact {label} identity is invalid.",
            },
        )
    return cleaned


def _sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ProductionBindingProjectAuthorization:
    def __init__(self, user: Mapping[str, Any]) -> None:
        self._user = dict(user)

    def authorize_project(
        self,
        context: BureauCatalogAccessContext,
        project_id: str,
        permission: str,
    ) -> bool:
        if context.principal_id != _principal(self._user):
            return False
        if context.tenant_id != _tenant(self._user):
            return False
        return authorize_modeling_scope(
            self._user, project_id, permission
        ) == project_id


class ProductionExactDatasetLineageAuthority:
    """Exact active-version and predictor-authorization adapter."""

    def __init__(self, user: Mapping[str, Any]) -> None:
        self._user = dict(user)

    def get_exact_lineage(
        self,
        context: BureauCatalogAccessContext,
        *,
        tenant_id: str | None,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
    ) -> ExactDatasetLineage:
        if (
            context.principal_id != _principal(self._user)
            or context.tenant_id != tenant_id
            or tenant_id != _tenant(self._user)
            or context.project_id != project_id
        ):
            raise CatalogBindingAccessDeniedError(
                "Catalog binding access is not authorized."
            )
        try:
            active = durable_active_dataset_identity(
                project_id,
                user=dict(self._user),
                require_artifact=True,
            )
        except Exception as exc:
            raise CatalogBindingLineageError(
                "exact_dataset_lineage_unavailable"
            ) from exc
        active_project = str(active.get("project_id") or "").strip()
        active_dataset = str(active.get("dataset_id") or "").strip()
        active_version = str(active.get("dataset_version_id") or "").strip()
        if (active_project, active_dataset, active_version) != (
            project_id,
            dataset_id,
            dataset_version_id,
        ):
            raise CatalogBindingLineageError("exact_dataset_version_not_active")
        try:
            activation_revision = int(active.get("activation_revision") or 0)
        except (TypeError, ValueError) as exc:
            raise CatalogBindingLineageError(
                "activation_revision_invalid"
            ) from exc
        schema_checksum = str(active.get("dataset_schema_hash") or "").strip().lower()
        if activation_revision < 1 or not _is_sha256(schema_checksum):
            raise CatalogBindingLineageError("active_dataset_identity_incomplete")

        try:
            record = (
                get_persistence_service()
                .predictor_authorizations.get_current_exact(
                    project_id,
                    dataset_id,
                    dataset_version_id,
                )
            )
            authorization = verify_durable_predictor_authorization(
                record,
                project_id=project_id,
                dataset_id=dataset_id,
                dataset_version_id=dataset_version_id,
            )
        except PredictorAuthorizationIntegrityError as exc:
            raise CatalogBindingLineageError(
                "predictor_authorization_unavailable"
            ) from exc
        target_contract_id = str(
            authorization.get("target_contract_id") or ""
        ).strip()
        predictor_authorization_id = str(
            authorization.get("predictor_authorization_id") or ""
        ).strip()
        if not target_contract_id or not predictor_authorization_id:
            raise CatalogBindingLineageError(
                "predictor_authorization_incomplete"
            )
        return ExactDatasetLineage(
            tenant_id=tenant_id,
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
            activation_revision=activation_revision,
            schema_checksum=schema_checksum,
            target_contract_id=target_contract_id,
            predictor_authorization_id=predictor_authorization_id,
        )


class ProductionExactCatalogRegistryAuthority:
    def __init__(self, operational: OperationalCatalogService) -> None:
        self._operational = operational

    def get_exact_catalog(
        self,
        *,
        catalog_version_id: str,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
    ) -> ExactCatalogRegistryRecord:
        record = self._operational.registry.get_version(catalog_version_id)
        exact_key = _catalog_key(record)
        if (
            exact_key != catalog_key
            or str(record.normalized_catalog_checksum) != catalog_checksum
        ):
            raise CatalogBindingCatalogError("exact_catalog_contradictory")
        return ExactCatalogRegistryRecord(
            catalog_version_id=str(record.catalog_version_id),
            catalog_key=exact_key,
            catalog_checksum=str(record.normalized_catalog_checksum),
            installation_status=str(record.installation_status),
            integrity_status=str(record.integrity_status),
            retired_status=str(record.retired_status),
            registry_revision=int(record.registry_revision),
        )


def _catalog_key(record: Any) -> BureauCatalogKey:
    return BureauCatalogKey(
        provider=str(record.provider_name),
        product=str(record.product_name),
        edition=str(record.edition),
        dictionary_version=str(record.source_release_version),
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True, slots=True)
class CatalogBindingRuntime:
    """Shared production composition for binding and future crosswalk routes."""

    user: Mapping[str, Any]
    context: BureauCatalogAccessContext
    operational: OperationalCatalogService
    repository: SQLiteCatalogBindingRepository
    project_authorization: ProductionBindingProjectAuthorization
    lineage: ProductionExactDatasetLineageAuthority
    catalog_registry: ProductionExactCatalogRegistryAuthority
    catalog_entitlements: RegistryEntitlementProvider
    service: CatalogBindingService

    def resolve_scope(
        self,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
    ) -> tuple[DatasetCatalogBindingScope, ExactDatasetLineage]:
        exact_project = _bounded_path_id(project_id, "project")
        exact_dataset = _bounded_path_id(dataset_id, "dataset")
        exact_version = _bounded_path_id(dataset_version_id, "dataset version")
        try:
            allowed = self.project_authorization.authorize_project(
                self.context, exact_project, "view"
            )
        except Exception as exc:
            raise CatalogBindingAccessDeniedError(
                "Catalog binding access is not authorized."
            ) from exc
        if allowed is not True:
            raise CatalogBindingAccessDeniedError(
                "Catalog binding access is not authorized."
            )
        current = self.lineage.get_exact_lineage(
            self.context,
            tenant_id=self.context.tenant_id,
            project_id=exact_project,
            dataset_id=exact_dataset,
            dataset_version_id=exact_version,
        )
        scope = DatasetCatalogBindingScope(
            tenant_id=self.context.tenant_id,
            project_id=exact_project,
            dataset_id=exact_dataset,
            dataset_version_id=exact_version,
        )
        return scope, current

    def current_binding(
        self, scope: DatasetCatalogBindingScope
    ) -> DatasetCatalogBindingRevision | None:
        try:
            return self.repository.get_current(
                catalog_binding_scope_identity(scope)
            )
        except CatalogBindingNotFoundError:
            return None

    def candidate_identity(
        self,
        *,
        scope: DatasetCatalogBindingScope,
        lineage: ExactDatasetLineage,
        catalog_version_id: str,
        catalog_checksum: str,
    ) -> tuple[
        DatasetVersionCatalogIdentity,
        ExactCatalogRegistryRecord,
        BureauCatalogAccessGrant,
    ]:
        record = self.operational.registry.get_version(catalog_version_id)
        key = _catalog_key(record)
        registry_record = self.catalog_registry.get_exact_catalog(
            catalog_version_id=catalog_version_id,
            catalog_key=key,
            catalog_checksum=catalog_checksum,
        )
        if (
            registry_record.installation_status != "installed"
            or registry_record.integrity_status != "verified"
            or registry_record.retired_status != "active"
        ):
            raise CatalogBindingCatalogError("exact_catalog_not_eligible")
        grant = self.catalog_entitlements.authorize(
            self.context,
            key,
            catalog_checksum,
            "crosswalk_candidate",
        )
        if (
            grant.principal_id != self.context.principal_id
            or grant.tenant_id != self.context.tenant_id
            or grant.catalog_key != key
            or grant.catalog_checksum != catalog_checksum
            or grant.operation != "crosswalk_candidate"
        ):
            raise CatalogBindingAccessDeniedError(
                "Catalog binding access is not authorized."
            )
        identity = DatasetVersionCatalogIdentity(
            tenant_id=scope.tenant_id,
            project_id=scope.project_id,
            dataset_id=scope.dataset_id,
            dataset_version_id=scope.dataset_version_id,
            activation_revision=lineage.activation_revision,
            schema_checksum=lineage.schema_checksum,
            target_contract_id=lineage.target_contract_id,
            predictor_authorization_id=lineage.predictor_authorization_id,
            catalog_version_id=registry_record.catalog_version_id,
            catalog_key=registry_record.catalog_key,
            catalog_checksum=registry_record.catalog_checksum,
        )
        return identity, registry_record, grant


def build_catalog_binding_runtime(
    user: Mapping[str, Any],
    *,
    project_id: str,
    operational_service: OperationalCatalogService | None = None,
) -> CatalogBindingRuntime:
    """Build the reusable exact production authority composition.

    Construction performs no binding database write.  Missing binding reads
    remain lazy through :class:`SQLiteCatalogBindingRepository`.
    """

    exact_project = _bounded_path_id(project_id, "project")
    operational = operational_service or get_operational_catalog_service()
    context = BureauCatalogAccessContext(
        principal_id=_principal(user),
        tenant_id=_tenant(user),
        project_id=exact_project,
    )
    repository = SQLiteCatalogBindingRepository(operational.root)
    project_authorization = ProductionBindingProjectAuthorization(user)
    lineage = ProductionExactDatasetLineageAuthority(user)
    catalog_registry = ProductionExactCatalogRegistryAuthority(operational)
    catalog_entitlements = RegistryEntitlementProvider(operational.registry)
    service = CatalogBindingService(
        repository=repository,
        project_authorization=project_authorization,
        lineage_authority=lineage,
        catalog_registry=catalog_registry,
        catalog_entitlements=catalog_entitlements,
    )
    return CatalogBindingRuntime(
        user=dict(user),
        context=context,
        operational=operational,
        repository=repository,
        project_authorization=project_authorization,
        lineage=lineage,
        catalog_registry=catalog_registry,
        catalog_entitlements=catalog_entitlements,
        service=service,
    )


@dataclass(frozen=True, slots=True)
class _PreparedPreview:
    scope: DatasetCatalogBindingScope
    lineage: ExactDatasetLineage
    identity: DatasetVersionCatalogIdentity
    registry_record: ExactCatalogRegistryRecord
    grant: BureauCatalogAccessGrant
    current_binding: DatasetCatalogBindingRevision | None
    expected_revision: int
    preview_checksum: str
    mapping_counts: Mapping[str, int]

    def payload(self) -> dict[str, Any]:
        current_exact = bool(
            self.current_binding
            and self.current_binding.identity == self.identity
            and self.current_binding.status == "active"
        )
        stale = bool(self.current_binding and not current_exact)
        return {
            "identity": self.identity.model_dump(mode="json"),
            "preview_checksum": self.preview_checksum,
            "expected_revision": self.expected_revision,
            "entitlement_state": "authorized",
            "integrity_state": self.registry_record.integrity_status,
            "mapping_counts": dict(self.mapping_counts),
            "evidence_count": 3,
            "current": current_exact,
            "stale": stale,
            "impact": _nonmutation_payload(),
        }


def _nonmutation_payload() -> dict[str, bool]:
    return {
        "dataset_mutated": False,
        "target_contract_mutated": False,
        "treatment_mutated": False,
        "predictor_authorization_mutated": False,
        "analysis_partition_mutated": False,
        "feature_manifest_mutated": False,
    }


def _prepare_preview(
    runtime: CatalogBindingRuntime,
    *,
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    catalog_version_id: str,
    catalog_checksum: str,
    expected_revision: int | None = None,
) -> _PreparedPreview:
    scope, lineage = runtime.resolve_scope(
        project_id, dataset_id, dataset_version_id
    )
    identity, registry_record, grant = runtime.candidate_identity(
        scope=scope,
        lineage=lineage,
        catalog_version_id=catalog_version_id,
        catalog_checksum=catalog_checksum,
    )
    current = runtime.current_binding(scope)
    resolved_revision = (
        int(expected_revision)
        if expected_revision is not None
        else (current.revision if current else 0)
    )
    mapping_counts = {
        "authoritative": 0,
        "review_required": 0,
        "unresolved": 0,
        "special_definitions": 0,
    }
    checksum_payload = {
        "contract_version": _PREVIEW_CONTRACT_VERSION,
        "identity": identity.model_dump(mode="json"),
        "expected_revision": resolved_revision,
        "registry_revision": registry_record.registry_revision,
        "grant": {
            "grant_id": grant.grant_id,
            "principal_id": grant.principal_id,
            "tenant_id": grant.tenant_id,
            "operation": grant.operation,
            "expires_at": grant.expires_at,
        },
        "mapping_counts": mapping_counts,
        "impact": _nonmutation_payload(),
    }
    return _PreparedPreview(
        scope=scope,
        lineage=lineage,
        identity=identity,
        registry_record=registry_record,
        grant=grant,
        current_binding=current,
        expected_revision=resolved_revision,
        preview_checksum=_sha256(checksum_payload),
        mapping_counts=mapping_counts,
    )


def _evidence_reference(
    *,
    kind: str,
    authority_id: str,
    payload: Mapping[str, Any],
    recorded_at: str,
) -> CatalogBindingEvidenceReference:
    checksum = _sha256(payload)
    return CatalogBindingEvidenceReference(
        evidence_id=f"binding-{kind}-{checksum[:24]}",
        evidence_kind=kind,
        authority_id=authority_id,
        checksum=checksum,
        recorded_at=recorded_at,
    )


def _confirmation_evidence(
    prepared: _PreparedPreview,
    *,
    actor: str,
    rationale: str,
) -> tuple[tuple[CatalogBindingEvidenceReference, ...], str]:
    recorded_at = _utc_now()
    lineage_payload = prepared.lineage.model_dump(mode="json")
    registry_payload = prepared.registry_record.model_dump(mode="json")
    entitlement_payload = {
        "grant_id": prepared.grant.grant_id,
        "principal_id": prepared.grant.principal_id,
        "tenant_id": prepared.grant.tenant_id,
        "catalog_checksum": prepared.grant.catalog_checksum,
        "operation": prepared.grant.operation,
        "expires_at": prepared.grant.expires_at,
    }
    review_payload = {
        "preview_checksum": prepared.preview_checksum,
        "analyst_rationale": rationale,
        "actor": actor,
    }
    review_checksum = _sha256(review_payload)
    evidence = (
        _evidence_reference(
            kind="dataset_lineage",
            authority_id="atlas-active-dataset-lineage",
            payload=lineage_payload,
            recorded_at=recorded_at,
        ),
        _evidence_reference(
            kind="catalog_registry",
            authority_id="atlas-bureau-catalog-registry",
            payload=registry_payload,
            recorded_at=recorded_at,
        ),
        _evidence_reference(
            kind="catalog_entitlement",
            authority_id=prepared.grant.grant_id,
            payload=entitlement_payload,
            recorded_at=recorded_at,
        ),
        CatalogBindingEvidenceReference(
            evidence_id=f"binding-analyst-review-{review_checksum[:24]}",
            evidence_kind="analyst_review",
            authority_id="atlas-bureau-binding-review",
            checksum=review_checksum,
            recorded_at=recorded_at,
        ),
    )
    return evidence, review_checksum


def _is_identical_retry(
    current: DatasetCatalogBindingRevision | None,
    prepared: _PreparedPreview,
    *,
    expected_revision: int,
    review_checksum: str,
) -> bool:
    return bool(
        current
        and current.revision == expected_revision + 1
        and current.identity == prepared.identity
        and current.status == "active"
        and any(
            evidence.evidence_kind == "analyst_review"
            and evidence.checksum == review_checksum
            for evidence in current.evidence
        )
    )


def _binding_envelope(
    runtime: CatalogBindingRuntime,
    resolution: CatalogBindingCurrentResolution,
) -> dict[str, Any]:
    record = resolution.binding
    binding = record.model_dump(mode="json")
    binding["stored_status"] = record.status
    binding["status"] = resolution.effective_status
    binding["stale_reason"] = resolution.stale_reason
    version = runtime.operational.registry.get_version(
        record.identity.catalog_version_id
    )
    mapping_counts = _binding_mapping_counts(runtime, record)
    return {
        "ok": True,
        "binding": binding,
        "summary": {
            "identity": record.identity.model_dump(mode="json"),
            "current": resolution.effective_status == "active",
            "stale": resolution.effective_status == "stale",
            "stale_reason": resolution.stale_reason,
            "entitlement_state": "authorized",
            "integrity_state": str(getattr(version, "integrity_status", "verified")),
            "mapping_counts": mapping_counts,
            "evidence_count": len(record.evidence),
            "evidence_kinds": sorted(
                {item.evidence_kind for item in record.evidence}
            ),
            **_nonmutation_payload(),
        },
    }


def _binding_mapping_counts(
    runtime: CatalogBindingRuntime,
    record: DatasetCatalogBindingRevision,
) -> dict[str, int]:
    """Project the exact linked crosswalk into a compact authorized summary.

    A missing link is a legitimate zero-state.  Once a binding pins a
    crosswalk revision, however, missing or contradictory governance must fail
    closed instead of quietly displaying zero mappings.
    """

    empty = {
        "authoritative": 0,
        "review_required": 0,
        "unresolved": 0,
        "special_definitions": 0,
    }
    if record.crosswalk_id is None or record.crosswalk_revision is None:
        return empty

    repository = SQLiteGovernedCrosswalkRepository(runtime.operational.root)
    try:
        governance = repository.get_revision(
            record.crosswalk_id, record.crosswalk_revision
        )
    except (CrosswalkGovernanceNotFoundError, CrosswalkGovernanceStateError) as exc:
        raise CatalogBindingStateError(
            "linked_crosswalk_revision_unavailable_or_contradictory"
        ) from exc

    identity = record.identity
    lineage = governance.lineage
    if (
        governance.governance_id != record.crosswalk_id
        or governance.revision != record.crosswalk_revision
        or lineage.project_id != identity.project_id
        or lineage.dataset_id != identity.dataset_id
        or lineage.dataset_version_id != identity.dataset_version_id
        or lineage.activation_revision != identity.activation_revision
        or lineage.target_contract_id != identity.target_contract_id
        or lineage.predictor_authorization_id != identity.predictor_authorization_id
        or lineage.schema_checksum != identity.schema_checksum
        or lineage.catalog_key != identity.catalog_key
        or lineage.catalog_checksum != identity.catalog_checksum
    ):
        raise CatalogBindingStateError("linked_crosswalk_lineage_contradictory")

    authoritative_states = {"exact_verified", "approved_alias"}
    review_states = {
        "probable_review_required",
        "ambiguous_review_required",
        "recoding_evidence_required",
    }
    unresolved_states = {"unresolved", "out_of_catalog"}
    authoritative = tuple(
        decision
        for decision in governance.decisions
        if decision.analyst_confirmed
        and decision.mapping_state in authoritative_states
        and decision.candidate_attribute_code
    )
    special_definition_count = 0
    if authoritative:
        codes = tuple(
            sorted(
                {str(decision.candidate_attribute_code) for decision in authoritative},
                key=str.casefold,
            )
        )
        batch = runtime.operational.get_mapped_attribute_batch(
            principal_id=runtime.context.principal_id,
            tenant_id=runtime.context.tenant_id,
            catalog_version_id=identity.catalog_version_id,
            attribute_codes=codes,
        )
        rows = tuple(batch.get("attributes") or ())
        returned_codes = {
            str(row.get("attribute_code") or "")
            for row in rows
            if isinstance(row, Mapping)
        }
        if (
            batch.get("bounded") is not True
            or str(batch.get("catalog_version_id") or "")
            != identity.catalog_version_id
            or str(batch.get("catalog_checksum") or "")
            != identity.catalog_checksum
            or int(batch.get("requested") or 0) != len(codes)
            or int(batch.get("returned") or 0) != len(codes)
            or returned_codes != set(codes)
        ):
            raise CatalogBindingStateError(
                "linked_crosswalk_definition_batch_contradictory"
            )
        for row in rows:
            if not isinstance(row, Mapping):
                raise CatalogBindingStateError(
                    "linked_crosswalk_definition_batch_contradictory"
                )
            total = row.get("special_values_total")
            if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                raise CatalogBindingStateError(
                    "linked_crosswalk_definition_count_contradictory"
                )
            special_definition_count += total

    return {
        "authoritative": len(authoritative),
        "review_required": sum(
            decision.mapping_state in review_states
            for decision in governance.decisions
        ),
        "unresolved": sum(
            decision.mapping_state in unresolved_states
            for decision in governance.decisions
        ),
        "special_definitions": special_definition_count,
    }


def _safe_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(
        exc,
        (
            CatalogBindingAccessDeniedError,
            BureauCatalogAccessDeniedError,
        ),
    ):
        return HTTPException(
            status_code=403,
            detail={
                "code": "bureau_metadata_binding_access_denied",
                "message": "Bureau metadata binding is not authorized.",
            },
        )
    if isinstance(exc, (CatalogBindingNotFoundError, CatalogRegistryNotFoundError)):
        return HTTPException(
            status_code=404,
            detail={
                "code": "bureau_metadata_binding_exact_resource_unavailable",
                "message": "The exact bureau metadata binding is unavailable.",
            },
        )
    if isinstance(
        exc,
        (
            CatalogBindingConflictError,
            CatalogBindingLineageError,
            CatalogBindingCatalogError,
            CatalogBindingStateError,
            CatalogBindingRepositoryStateError,
        ),
    ):
        return HTTPException(
            status_code=409,
            detail={
                "code": "bureau_metadata_binding_state_conflict",
                "message": "The exact binding authority changed or is contradictory.",
            },
        )
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=400,
            detail={
                "code": "bureau_metadata_binding_request_invalid",
                "message": "The bureau metadata binding request is invalid.",
            },
        )
    if isinstance(
        exc,
        (
            CatalogBindingRepositoryError,
            CrosswalkGovernanceRepositoryError,
            CatalogRegistryError,
            CatalogOperationalError,
            RestrictedStorageError,
        ),
    ):
        return HTTPException(
            status_code=503,
            detail={
                "code": "bureau_metadata_binding_service_unavailable",
                "message": "The bureau metadata binding service is unavailable.",
            },
        )
    return HTTPException(
        status_code=503,
        detail={
            "code": "bureau_metadata_binding_service_unavailable",
            "message": "The bureau metadata binding service is unavailable.",
        },
    )


def _audit(
    runtime: CatalogBindingRuntime,
    *,
    action: str,
    result: str,
    catalog_version_id: str | None = None,
) -> None:
    try:
        runtime.operational.registry.record_access_audit(
            actor=runtime.context.principal_id,
            catalog_version_id=catalog_version_id,
            project_id=runtime.context.project_id,
            action=action,
            result_status=result,
            correlation_id="bureau-binding-http-" + uuid.uuid4().hex,
        )
    except Exception:
        pass


@router.get(
    "/projects/{project_id}/datasets/{dataset_id}/versions/{dataset_version_id}"
    "/bureau-metadata/binding"
)
def get_catalog_binding(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    user: Dict[str, Any] = Depends(require_user),
    operational: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    runtime = build_catalog_binding_runtime(
        user, project_id=project_id, operational_service=operational
    )
    try:
        scope, _lineage = runtime.resolve_scope(
            project_id, dataset_id, dataset_version_id
        )
        resolution = runtime.service.resolve_current(
            context=runtime.context, scope=scope
        )
        response = _binding_envelope(runtime, resolution)
    except Exception as exc:
        _audit(runtime, action="catalog_binding_get", result="denied_or_failed")
        raise _safe_http_error(exc) from exc
    _audit(
        runtime,
        action="catalog_binding_get",
        result="success",
        catalog_version_id=resolution.binding.identity.catalog_version_id,
    )
    return response


@router.post(
    "/projects/{project_id}/datasets/{dataset_id}/versions/{dataset_version_id}"
    "/bureau-metadata/binding/preview"
)
def preview_catalog_binding(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    payload: CatalogBindingPreviewRequest,
    user: Dict[str, Any] = Depends(require_user),
    operational: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    runtime = build_catalog_binding_runtime(
        user, project_id=project_id, operational_service=operational
    )
    try:
        prepared = _prepare_preview(
            runtime,
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
            catalog_version_id=payload.catalog_version_id,
            catalog_checksum=payload.catalog_checksum,
        )
    except Exception as exc:
        _audit(
            runtime,
            action="catalog_binding_preview",
            result="denied_or_failed",
            catalog_version_id=payload.catalog_version_id,
        )
        raise _safe_http_error(exc) from exc
    _audit(
        runtime,
        action="catalog_binding_preview",
        result="success",
        catalog_version_id=payload.catalog_version_id,
    )
    preview = prepared.payload()
    return {
        "ok": True,
        "preview": preview,
        "summary": {
            "persisted": False,
            "mapping_counts": dict(prepared.mapping_counts),
            "evidence_count": 3,
            **_nonmutation_payload(),
        },
    }


@router.post(
    "/projects/{project_id}/datasets/{dataset_id}/versions/{dataset_version_id}"
    "/bureau-metadata/binding/confirm"
)
def confirm_catalog_binding(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    payload: CatalogBindingConfirmRequest,
    user: Dict[str, Any] = Depends(require_user),
    operational: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    runtime = build_catalog_binding_runtime(
        user, project_id=project_id, operational_service=operational
    )
    try:
        prepared = _prepare_preview(
            runtime,
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
            catalog_version_id=payload.catalog_version_id,
            catalog_checksum=payload.catalog_checksum,
            expected_revision=payload.expected_revision,
        )
        if prepared.preview_checksum != payload.preview_checksum:
            raise HTTPException(
                status_code=412,
                detail={
                    "code": "bureau_metadata_binding_preview_stale",
                    "message": "The exact binding preview no longer verifies.",
                },
            )
        evidence, review_checksum = _confirmation_evidence(
            prepared,
            actor=runtime.context.principal_id,
            rationale=payload.analyst_rationale,
        )
        current = runtime.current_binding(prepared.scope)
        current_revision = current.revision if current else 0
        if current_revision != payload.expected_revision:
            if not _is_identical_retry(
                current,
                prepared,
                expected_revision=payload.expected_revision,
                review_checksum=review_checksum,
            ):
                raise CatalogBindingConflictError(
                    expected_revision=payload.expected_revision,
                    current_revision=current_revision,
                )
            assert current is not None
            persisted = current
        elif current is None:
            persisted = runtime.service.bind(
                context=runtime.context,
                identity=prepared.identity,
                actor_id=runtime.context.principal_id,
                evidence=evidence,
            )
        else:
            persisted = runtime.service.revise(
                context=runtime.context,
                identity=prepared.identity,
                expected_revision=payload.expected_revision,
                status="active",
                actor_id=runtime.context.principal_id,
                evidence=evidence,
            )
        resolution = runtime.service.resolve_current(
            context=runtime.context, scope=prepared.scope
        )
        if resolution.binding.binding_id != persisted.binding_id:
            raise CatalogBindingLineageError("confirmed_binding_contradictory")
        response = _binding_envelope(runtime, resolution)
        documentation = record_binding_evidence_and_documentation(
            binding=resolution.binding,
            actor_id=runtime.context.principal_id,
            mapping_counts=response["summary"]["mapping_counts"],
            entitlement_verified=True,
        )
        response["documentation"] = {
            **documentation,
            "bounded_project_references_only": True,
            "provider_catalog_embedded": False,
        }
    except Exception as exc:
        _audit(
            runtime,
            action="catalog_binding_confirm",
            result="denied_or_failed",
            catalog_version_id=payload.catalog_version_id,
        )
        raise _safe_http_error(exc) from exc
    _audit(
        runtime,
        action="catalog_binding_confirm",
        result="success",
        catalog_version_id=payload.catalog_version_id,
    )
    return response


@router.get(
    "/projects/{project_id}/datasets/{dataset_id}/versions/{dataset_version_id}"
    "/bureau-metadata/binding/history"
)
def get_catalog_binding_history(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    limit: int = Query(default=25, ge=1, le=_MAX_HISTORY_LIMIT),
    user: Dict[str, Any] = Depends(require_user),
    operational: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> Mapping[str, Any]:
    runtime = build_catalog_binding_runtime(
        user, project_id=project_id, operational_service=operational
    )
    try:
        scope, _lineage = runtime.resolve_scope(
            project_id, dataset_id, dataset_version_id
        )
        history = runtime.service.history_for_scope(
            context=runtime.context, scope=scope
        )
        selected = history[-limit:]
    except Exception as exc:
        _audit(runtime, action="catalog_binding_history", result="denied_or_failed")
        raise _safe_http_error(exc) from exc
    _audit(runtime, action="catalog_binding_history", result="success")
    return {
        "ok": True,
        "scope": scope.model_dump(mode="json"),
        "returned": len(selected),
        "total_revisions": len(history),
        "revisions": [record.model_dump(mode="json") for record in selected],
    }


__all__ = [
    "CatalogBindingConfirmRequest",
    "CatalogBindingPreviewRequest",
    "CatalogBindingRuntime",
    "ProductionBindingProjectAuthorization",
    "ProductionExactCatalogRegistryAuthority",
    "ProductionExactDatasetLineageAuthority",
    "build_catalog_binding_runtime",
    "router",
]

"""Fail-closed service for exact dataset-version bureau-catalog bindings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Literal, Protocol, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .catalog_binding import (
    CatalogBindingEvidenceReference,
    CatalogBindingStatus,
    DatasetCatalogBindingScope,
    DatasetCatalogBindingRevision,
    DatasetVersionCatalogIdentity,
    build_catalog_binding_revision,
    catalog_binding_identity,
    catalog_binding_scope_identity,
    dataset_catalog_binding_scope,
)
from .catalog_binding_repository import CatalogBindingRepository
from .catalog_service import (
    BureauCatalogAccessDeniedError,
    BureauCatalogEntitlementProvider,
)
from .types import (
    BureauCatalogAccessContext,
    BureauCatalogAccessGrant,
    BureauCatalogKey,
)


CatalogBindingProjectPermission = Literal["view", "edit"]


class CatalogBindingAccessDeniedError(PermissionError):
    """Generic denial that does not reveal project or catalog existence."""


class CatalogBindingLineageError(RuntimeError):
    """The exact project/dataset lineage is absent or contradictory."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"Catalog binding lineage is not current ({reason_code}).")


class CatalogBindingCatalogError(RuntimeError):
    """The exact catalog registry record is absent or contradictory."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"Catalog registry identity is not valid ({reason_code}).")


class CatalogBindingStateError(RuntimeError):
    """The requested binding operation violates the exact authority contract."""


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _clean_identifier(value: object, field_name: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or len(cleaned) > 256 or any(
        ord(character) < 32 or ord(character) == 127 for character in cleaned
    ):
        raise ValueError(f"{field_name} is missing or invalid.")
    return cleaned


class ExactDatasetLineage(_FrozenContract):
    tenant_id: str | None = None
    project_id: str
    dataset_id: str
    dataset_version_id: str
    activation_revision: int = Field(ge=1)
    schema_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_contract_id: str
    predictor_authorization_id: str

    @field_validator(
        "project_id",
        "dataset_id",
        "dataset_version_id",
        "target_contract_id",
        "predictor_authorization_id",
        mode="before",
    )
    @classmethod
    def validate_identifier(cls, value: object, info: ValidationInfo) -> str:
        return _clean_identifier(value, info.field_name)

    @field_validator("tenant_id", mode="before")
    @classmethod
    def validate_optional_tenant(cls, value: object) -> str | None:
        if value is None:
            return None
        return _clean_identifier(value, "tenant_id")


class ExactCatalogRegistryRecord(_FrozenContract):
    catalog_version_id: str
    catalog_key: BureauCatalogKey
    catalog_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    installation_status: str
    integrity_status: str
    retired_status: str
    registry_revision: int = Field(ge=1)

    @field_validator(
        "catalog_version_id",
        "installation_status",
        "integrity_status",
        "retired_status",
        mode="before",
    )
    @classmethod
    def validate_identifier(cls, value: object, info: ValidationInfo) -> str:
        return _clean_identifier(value, info.field_name)


class CatalogBindingCurrentResolution(_FrozenContract):
    """Current stored head plus its effective status against live authority."""

    scope: DatasetCatalogBindingScope
    binding: DatasetCatalogBindingRevision
    effective_status: CatalogBindingStatus
    lineage_current: bool
    stale_reason: str | None = None

    @field_validator("stale_reason", mode="before")
    @classmethod
    def validate_stale_reason(cls, value: object) -> str | None:
        if value is None:
            return None
        return _clean_identifier(value, "stale_reason")

    @model_validator(mode="after")
    def validate_resolution(self) -> "CatalogBindingCurrentResolution":
        if dataset_catalog_binding_scope(self.binding.identity) != self.scope:
            raise ValueError("Binding resolution scope contradicts the stored binding.")
        if self.effective_status == "active":
            if (
                self.binding.status != "active"
                or not self.lineage_current
                or self.stale_reason is not None
            ):
                raise ValueError("An active binding resolution must be exactly current.")
        elif self.stale_reason is None:
            raise ValueError("A stale binding resolution requires a bounded reason.")
        return self


@runtime_checkable
class CatalogBindingProjectAuthorization(Protocol):
    def authorize_project(
        self,
        context: BureauCatalogAccessContext,
        project_id: str,
        permission: CatalogBindingProjectPermission,
    ) -> bool: ...


@runtime_checkable
class ExactDatasetLineageAuthority(Protocol):
    def get_exact_lineage(
        self,
        context: BureauCatalogAccessContext,
        *,
        tenant_id: str | None,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
    ) -> ExactDatasetLineage:
        """Return only the requested identity; never latest, first, or display-name."""


@runtime_checkable
class ExactCatalogRegistryAuthority(Protocol):
    def get_exact_catalog(
        self,
        *,
        catalog_version_id: str,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
    ) -> ExactCatalogRegistryRecord:
        """Return only the exact registry record or fail closed."""


def _parse_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CatalogBindingAccessDeniedError(
            "Catalog binding access is not authorized."
        ) from exc
    if parsed.tzinfo is None:
        raise CatalogBindingAccessDeniedError(
            "Catalog binding access is not authorized."
        )
    return parsed.astimezone(timezone.utc)


def _system_clock() -> datetime:
    return datetime.now(timezone.utc)


class CatalogBindingService:
    """Coordinates exact binding persistence without changing workflow state."""

    _ENTITLEMENT_OPERATION = "crosswalk_candidate"

    def __init__(
        self,
        *,
        repository: CatalogBindingRepository,
        project_authorization: CatalogBindingProjectAuthorization,
        lineage_authority: ExactDatasetLineageAuthority,
        catalog_registry: ExactCatalogRegistryAuthority,
        catalog_entitlements: BureauCatalogEntitlementProvider,
        clock: Callable[[], datetime] = _system_clock,
    ) -> None:
        self._repository = repository
        self._project_authorization = project_authorization
        self._lineage_authority = lineage_authority
        self._catalog_registry = catalog_registry
        self._catalog_entitlements = catalog_entitlements
        self._clock = clock

    def _authorize_project(
        self,
        context: BureauCatalogAccessContext,
        scope: DatasetCatalogBindingScope,
        permission: CatalogBindingProjectPermission,
    ) -> None:
        if (
            context.project_id != scope.project_id
            or context.tenant_id != scope.tenant_id
        ):
            raise CatalogBindingAccessDeniedError(
                "Catalog binding access is not authorized."
            )
        try:
            allowed = self._project_authorization.authorize_project(
                context, scope.project_id, permission
            )
        except Exception as exc:
            raise CatalogBindingAccessDeniedError(
                "Catalog binding access is not authorized."
            ) from exc
        if allowed is not True:
            raise CatalogBindingAccessDeniedError(
                "Catalog binding access is not authorized."
            )

    def _get_exact_lineage(
        self,
        context: BureauCatalogAccessContext,
        scope: DatasetCatalogBindingScope,
    ) -> ExactDatasetLineage:
        try:
            current = self._lineage_authority.get_exact_lineage(
                context,
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                dataset_id=scope.dataset_id,
                dataset_version_id=scope.dataset_version_id,
            )
        except Exception as exc:
            raise CatalogBindingLineageError("exact_lineage_unavailable") from exc
        if (
            current.tenant_id,
            current.project_id,
            current.dataset_id,
            current.dataset_version_id,
        ) != (
            scope.tenant_id,
            scope.project_id,
            scope.dataset_id,
            scope.dataset_version_id,
        ):
            raise CatalogBindingLineageError("exact_dataset_scope_contradictory")
        return current

    def _require_exact_lineage(
        self,
        context: BureauCatalogAccessContext,
        identity: DatasetVersionCatalogIdentity,
    ) -> None:
        current = self._get_exact_lineage(
            context, dataset_catalog_binding_scope(identity)
        )
        supplied = ExactDatasetLineage(
            tenant_id=identity.tenant_id,
            project_id=identity.project_id,
            dataset_id=identity.dataset_id,
            dataset_version_id=identity.dataset_version_id,
            activation_revision=identity.activation_revision,
            schema_checksum=identity.schema_checksum,
            target_contract_id=identity.target_contract_id,
            predictor_authorization_id=identity.predictor_authorization_id,
        )
        if current != supplied:
            raise CatalogBindingLineageError("exact_lineage_contradictory")

    def _require_exact_catalog(
        self, identity: DatasetVersionCatalogIdentity
    ) -> None:
        try:
            current = self._catalog_registry.get_exact_catalog(
                catalog_version_id=identity.catalog_version_id,
                catalog_key=identity.catalog_key,
                catalog_checksum=identity.catalog_checksum,
            )
        except Exception as exc:
            raise CatalogBindingCatalogError("exact_catalog_unavailable") from exc
        if (
            current.catalog_version_id != identity.catalog_version_id
            or current.catalog_key != identity.catalog_key
            or current.catalog_checksum != identity.catalog_checksum
        ):
            raise CatalogBindingCatalogError("exact_catalog_contradictory")
        if (
            current.installation_status != "installed"
            or current.integrity_status != "verified"
            or current.retired_status != "active"
        ):
            raise CatalogBindingCatalogError("exact_catalog_not_eligible")

    def _authorize_entitlement(
        self,
        context: BureauCatalogAccessContext,
        identity: DatasetVersionCatalogIdentity,
    ) -> BureauCatalogAccessGrant:
        try:
            grant = self._catalog_entitlements.authorize(
                context,
                identity.catalog_key,
                identity.catalog_checksum,
                self._ENTITLEMENT_OPERATION,
            )
        except BureauCatalogAccessDeniedError as exc:
            raise CatalogBindingAccessDeniedError(
                "Catalog binding access is not authorized."
            ) from exc
        except Exception as exc:
            raise CatalogBindingAccessDeniedError(
                "Catalog binding access is not authorized."
            ) from exc
        if (
            grant.principal_id != context.principal_id
            or grant.tenant_id != context.tenant_id
            or grant.catalog_key != identity.catalog_key
            or grant.catalog_checksum != identity.catalog_checksum
            or grant.operation != self._ENTITLEMENT_OPERATION
        ):
            raise CatalogBindingAccessDeniedError(
                "Catalog binding access is not authorized."
            )
        if grant.expires_at and _parse_expiry(grant.expires_at) <= self._now():
            raise CatalogBindingAccessDeniedError(
                "Catalog binding access is not authorized."
            )
        return grant

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise CatalogBindingStateError("Server clock must be timezone aware.")
        return value.astimezone(timezone.utc)

    def _authorize_exact(
        self,
        context: BureauCatalogAccessContext,
        identity: DatasetVersionCatalogIdentity,
        permission: CatalogBindingProjectPermission,
    ) -> None:
        self._authorize_project(
            context, dataset_catalog_binding_scope(identity), permission
        )
        self._require_exact_lineage(context, identity)
        self._require_exact_catalog(identity)
        self._authorize_entitlement(context, identity)

    @staticmethod
    def _require_actor(
        context: BureauCatalogAccessContext, actor_id: str
    ) -> None:
        if actor_id != context.principal_id:
            raise CatalogBindingStateError(
                "Binding actor must match the authenticated principal."
            )

    def bind(
        self,
        *,
        context: BureauCatalogAccessContext,
        identity: DatasetVersionCatalogIdentity,
        actor_id: str,
        evidence: tuple[CatalogBindingEvidenceReference, ...],
        crosswalk_id: str | None = None,
        crosswalk_revision: int | None = None,
    ) -> DatasetCatalogBindingRevision:
        self._authorize_exact(context, identity, "edit")
        self._require_actor(context, actor_id)
        record = build_catalog_binding_revision(
            identity=identity,
            revision=1,
            status="active",
            actor_id=actor_id,
            server_recorded_at=self._now().isoformat().replace("+00:00", "Z"),
            evidence=evidence,
            crosswalk_id=crosswalk_id,
            crosswalk_revision=crosswalk_revision,
        )
        return self._repository.append(record, expected_revision=0)

    def revise(
        self,
        *,
        context: BureauCatalogAccessContext,
        identity: DatasetVersionCatalogIdentity,
        expected_revision: int,
        status: CatalogBindingStatus,
        actor_id: str,
        evidence: tuple[CatalogBindingEvidenceReference, ...],
        crosswalk_id: str | None = None,
        crosswalk_revision: int | None = None,
        stale_reason: str | None = None,
    ) -> DatasetCatalogBindingRevision:
        self._authorize_exact(context, identity, "edit")
        self._require_actor(context, actor_id)
        binding_id = catalog_binding_identity(identity)
        current = self._repository.get_current(binding_id)
        if dataset_catalog_binding_scope(current.identity) != dataset_catalog_binding_scope(
            identity
        ):
            raise CatalogBindingLineageError("stored_binding_scope_contradictory")
        record = build_catalog_binding_revision(
            identity=identity,
            revision=expected_revision + 1,
            status=status,
            actor_id=actor_id,
            server_recorded_at=self._now().isoformat().replace("+00:00", "Z"),
            evidence=evidence,
            crosswalk_id=crosswalk_id,
            crosswalk_revision=crosswalk_revision,
            stale_reason=stale_reason,
            previous_revision_checksum=current.revision_checksum,
        )
        return self._repository.append(
            record, expected_revision=expected_revision
        )

    def get_current(
        self,
        *,
        context: BureauCatalogAccessContext,
        identity: DatasetVersionCatalogIdentity,
    ) -> DatasetCatalogBindingRevision:
        resolution = self.resolve_current(
            context=context, scope=dataset_catalog_binding_scope(identity)
        )
        record = resolution.binding
        if record.identity != identity or not resolution.lineage_current:
            raise CatalogBindingLineageError("stored_binding_contradictory")
        return record

    def resolve_current(
        self,
        *,
        context: BureauCatalogAccessContext,
        scope: DatasetCatalogBindingScope,
    ) -> CatalogBindingCurrentResolution:
        """Resolve the sole exact dataset-scope head without a catalog hint."""

        self._authorize_project(context, scope, "view")
        current_lineage = self._get_exact_lineage(context, scope)
        record = self._repository.get_current(
            catalog_binding_scope_identity(scope)
        )
        if dataset_catalog_binding_scope(record.identity) != scope:
            raise CatalogBindingLineageError("stored_binding_scope_contradictory")
        self._require_exact_catalog(record.identity)
        self._authorize_entitlement(context, record.identity)
        recorded_lineage = ExactDatasetLineage(
            tenant_id=record.identity.tenant_id,
            project_id=record.identity.project_id,
            dataset_id=record.identity.dataset_id,
            dataset_version_id=record.identity.dataset_version_id,
            activation_revision=record.identity.activation_revision,
            schema_checksum=record.identity.schema_checksum,
            target_contract_id=record.identity.target_contract_id,
            predictor_authorization_id=record.identity.predictor_authorization_id,
        )
        lineage_current = recorded_lineage == current_lineage
        effective_status: CatalogBindingStatus = (
            "active" if record.status == "active" and lineage_current else "stale"
        )
        stale_reason = None
        if effective_status == "stale":
            stale_reason = record.stale_reason or "upstream_authority_changed"
        return CatalogBindingCurrentResolution(
            scope=scope,
            binding=record,
            effective_status=effective_status,
            lineage_current=lineage_current,
            stale_reason=stale_reason,
        )

    def get_revision(
        self,
        *,
        context: BureauCatalogAccessContext,
        identity: DatasetVersionCatalogIdentity,
        revision: int,
    ) -> DatasetCatalogBindingRevision:
        self._authorize_exact(context, identity, "view")
        record = self._repository.get_revision(
            catalog_binding_identity(identity), revision
        )
        if record.identity != identity:
            raise CatalogBindingLineageError("stored_binding_contradictory")
        return record

    def history(
        self,
        *,
        context: BureauCatalogAccessContext,
        identity: DatasetVersionCatalogIdentity,
    ) -> tuple[DatasetCatalogBindingRevision, ...]:
        history = self.history_for_scope(
            context=context, scope=dataset_catalog_binding_scope(identity)
        )
        if history[-1].identity != identity:
            raise CatalogBindingLineageError("stored_binding_contradictory")
        return history

    def history_for_scope(
        self,
        *,
        context: BureauCatalogAccessContext,
        scope: DatasetCatalogBindingScope,
    ) -> tuple[DatasetCatalogBindingRevision, ...]:
        """Return one exact scope history, authorizing every catalog revision."""

        self._authorize_project(context, scope, "view")
        self._get_exact_lineage(context, scope)
        history = self._repository.history(catalog_binding_scope_identity(scope))
        if any(dataset_catalog_binding_scope(record.identity) != scope for record in history):
            raise CatalogBindingLineageError("stored_binding_scope_contradictory")
        for record in history:
            self._require_exact_catalog(record.identity)
            self._authorize_entitlement(context, record.identity)
        return history


__all__ = [
    "CatalogBindingAccessDeniedError",
    "CatalogBindingCatalogError",
    "CatalogBindingCurrentResolution",
    "CatalogBindingLineageError",
    "CatalogBindingProjectAuthorization",
    "CatalogBindingProjectPermission",
    "CatalogBindingService",
    "CatalogBindingStateError",
    "ExactCatalogRegistryAuthority",
    "ExactCatalogRegistryRecord",
    "ExactDatasetLineage",
    "ExactDatasetLineageAuthority",
]

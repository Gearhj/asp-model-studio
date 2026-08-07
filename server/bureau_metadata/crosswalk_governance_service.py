"""Authorization- and entitlement-gated bureau crosswalk governance service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Protocol, runtime_checkable

from .catalog_service import (
    BureauCatalogAccessDeniedError,
    BureauCatalogEntitlementProvider,
)
from .crosswalk_governance import (
    CrosswalkAuditMetadata,
    CrosswalkLineage,
    GovernedCrosswalkRevision,
    GovernedMappingDecision,
    build_governed_revision,
    governance_identity,
    is_confirmable,
)
from .crosswalk_governance_repository import GovernedCrosswalkRepository
from .types import (
    BureauCatalogAccessContext,
    BureauCatalogAccessGrant,
    BureauDatasetCrosswalk,
)


CrosswalkProjectPermission = Literal["view", "edit"]


class CrosswalkGovernanceAccessDeniedError(PermissionError):
    """Generic denial that does not disclose project or catalog existence."""


class CrosswalkGovernanceLineageError(RuntimeError):
    """Fail-closed exact-lineage error with a bounded machine-readable reason."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"Crosswalk lineage is not current ({reason_code}).")


class CrosswalkGovernanceStateError(RuntimeError):
    """A requested governance transition violates the governed contract."""


@runtime_checkable
class CrosswalkProjectAuthorizationProvider(Protocol):
    def authorize_project(
        self,
        context: BureauCatalogAccessContext,
        project_id: str,
        permission: CrosswalkProjectPermission,
    ) -> bool:
        """Return true only for the exact project and requested permission."""


@runtime_checkable
class CrosswalkLineageAuthority(Protocol):
    def current_lineage(
        self,
        context: BureauCatalogAccessContext,
        project_id: str,
    ) -> CrosswalkLineage:
        """Return the exact current dataset/authorization/catalog identity."""


def _parse_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CrosswalkGovernanceAccessDeniedError(
            "Crosswalk catalog entitlement is invalid."
        ) from exc
    if parsed.tzinfo is None:
        raise CrosswalkGovernanceAccessDeniedError(
            "Crosswalk catalog entitlement is invalid."
        )
    return parsed.astimezone(timezone.utc)


class GovernedCrosswalkService:
    """Coordinates governance state without mutating data or predictor authority."""

    _CATALOG_OPERATION = "crosswalk_candidate"

    def __init__(
        self,
        *,
        repository: GovernedCrosswalkRepository,
        project_authorization: CrosswalkProjectAuthorizationProvider,
        catalog_entitlements: BureauCatalogEntitlementProvider,
        lineage_authority: CrosswalkLineageAuthority,
    ) -> None:
        self._repository = repository
        self._project_authorization = project_authorization
        self._catalog_entitlements = catalog_entitlements
        self._lineage_authority = lineage_authority

    def _authorize_project(
        self,
        context: BureauCatalogAccessContext,
        project_id: str,
        permission: CrosswalkProjectPermission,
    ) -> None:
        if context.project_id != project_id:
            raise CrosswalkGovernanceAccessDeniedError(
                "Crosswalk governance access is not authorized."
            )
        try:
            allowed = self._project_authorization.authorize_project(
                context,
                project_id,
                permission,
            )
        except Exception as exc:
            raise CrosswalkGovernanceAccessDeniedError(
                "Crosswalk governance access is not authorized."
            ) from exc
        if allowed is not True:
            raise CrosswalkGovernanceAccessDeniedError(
                "Crosswalk governance access is not authorized."
            )

    def _authorize_catalog(
        self,
        context: BureauCatalogAccessContext,
        lineage: CrosswalkLineage,
    ) -> BureauCatalogAccessGrant:
        try:
            grant = self._catalog_entitlements.authorize(
                context,
                lineage.catalog_key,
                lineage.catalog_checksum,
                self._CATALOG_OPERATION,
            )
        except BureauCatalogAccessDeniedError as exc:
            raise CrosswalkGovernanceAccessDeniedError(
                "Crosswalk governance access is not authorized."
            ) from exc
        except Exception as exc:
            raise CrosswalkGovernanceAccessDeniedError(
                "Crosswalk governance access is not authorized."
            ) from exc
        if (
            grant.principal_id != context.principal_id
            or grant.tenant_id != context.tenant_id
            or grant.catalog_key != lineage.catalog_key
            or grant.catalog_checksum != lineage.catalog_checksum
            or grant.operation != self._CATALOG_OPERATION
        ):
            raise CrosswalkGovernanceAccessDeniedError(
                "Crosswalk governance access is not authorized."
            )
        if grant.expires_at is not None and _parse_expiry(grant.expires_at) <= datetime.now(
            timezone.utc
        ):
            raise CrosswalkGovernanceAccessDeniedError(
                "Crosswalk governance access is not authorized."
            )
        return grant

    def _require_current_lineage(
        self,
        context: BureauCatalogAccessContext,
        supplied: CrosswalkLineage,
    ) -> None:
        try:
            current = self._lineage_authority.current_lineage(
                context,
                supplied.project_id,
            )
        except Exception as exc:
            raise CrosswalkGovernanceLineageError(
                "lineage_authority_unavailable"
            ) from exc

        if current.project_id != supplied.project_id:
            raise CrosswalkGovernanceLineageError("project_lineage_stale")
        catalog_identity = (current.catalog_key, current.catalog_checksum)
        supplied_catalog_identity = (supplied.catalog_key, supplied.catalog_checksum)
        if catalog_identity != supplied_catalog_identity:
            raise CrosswalkGovernanceLineageError("catalog_lineage_stale")
        dataset_identity = (
            current.dataset_id,
            current.dataset_version_id,
            current.activation_revision,
            current.target_contract_id,
            current.predictor_authorization_id,
            current.schema_checksum,
        )
        supplied_dataset_identity = (
            supplied.dataset_id,
            supplied.dataset_version_id,
            supplied.activation_revision,
            supplied.target_contract_id,
            supplied.predictor_authorization_id,
            supplied.schema_checksum,
        )
        if dataset_identity != supplied_dataset_identity:
            raise CrosswalkGovernanceLineageError("dataset_lineage_stale")

    @staticmethod
    def _require_actor(
        context: BureauCatalogAccessContext,
        audit: CrosswalkAuditMetadata,
    ) -> None:
        if audit.actor_id != context.principal_id:
            raise CrosswalkGovernanceStateError(
                "Audit actor must match the authenticated principal."
            )

    @staticmethod
    def _validate_source_identity(
        source: BureauDatasetCrosswalk,
        lineage: CrosswalkLineage,
        decisions: tuple[GovernedMappingDecision, ...],
    ) -> None:
        if (
            source.project_id != lineage.project_id
            or source.dataset_id != lineage.dataset_id
            or source.dataset_version_id != lineage.dataset_version_id
            or source.schema_checksum != lineage.schema_checksum
            or source.target_contract_id != lineage.target_contract_id
            or source.predictor_authorization_id != lineage.predictor_authorization_id
            or source.catalog_key != lineage.catalog_key
            or source.catalog_checksum != lineage.catalog_checksum
        ):
            raise CrosswalkGovernanceLineageError("source_lineage_mismatch")
        if (
            source.crosswalk_status != "candidate_only"
            or source.candidate_only is not True
            or source.approved_mappings
            or source.governed_feature_set_changed is not False
            or source.dataset_mutated is not False
        ):
            raise CrosswalkGovernanceStateError(
                "Only an unapproved, nonmutating candidate crosswalk may enter governance."
            )
        if any(
            mapping.candidate_only is not True
            or mapping.approved_mapping is not False
            or mapping.catalog_key != lineage.catalog_key
            or mapping.catalog_checksum != lineage.catalog_checksum
            for mapping in source.mappings
        ):
            raise CrosswalkGovernanceStateError(
                "Source mappings must remain exact-catalog, candidate-only evidence."
            )

        source_fields = {mapping.dataset_field for mapping in source.mappings}
        decision_fields = {decision.dataset_field for decision in decisions}
        if not source_fields or decision_fields != source_fields:
            raise CrosswalkGovernanceStateError(
                "Governance decisions must cover exactly the candidate crosswalk fields."
            )

        supported_codes: dict[str, set[str]] = {}
        source_statuses: dict[str, set[str]] = {}
        alias_references: dict[str, set[str]] = {}
        for mapping in source.mappings:
            supported_codes.setdefault(mapping.dataset_field, set())
            source_statuses.setdefault(mapping.dataset_field, set()).add(
                mapping.match_status
            )
            alias_references.setdefault(mapping.dataset_field, set())
            if mapping.candidate_attribute_code:
                supported_codes[mapping.dataset_field].add(
                    mapping.candidate_attribute_code
                )
            supported_codes[mapping.dataset_field].update(mapping.ambiguity)
            if mapping.institutional_alias_reference:
                alias_references[mapping.dataset_field].add(
                    mapping.institutional_alias_reference
                )

        all_supported_codes = set().union(*supported_codes.values())

        for decision in decisions:
            supported = supported_codes[decision.dataset_field]
            if decision.candidate_attribute_code and decision.mapping_state not in {
                "transformed_or_derived",
                "rejected",
            }:
                if decision.candidate_attribute_code not in supported:
                    raise CrosswalkGovernanceStateError(
                        "A mapping decision names a candidate absent from source evidence."
                    )
            if not set(decision.alternative_attribute_codes).issubset(supported):
                raise CrosswalkGovernanceStateError(
                    "Ambiguous alternatives must be present in source evidence."
                )
            if not set(decision.source_attribute_codes).issubset(
                all_supported_codes
            ):
                raise CrosswalkGovernanceStateError(
                    "Transformation source attributes must be present in source evidence."
                )
            if decision.mapping_state == "exact_verified" and not any(
                status == "exact_dictionary_code_match"
                for status in source_statuses[decision.dataset_field]
            ):
                raise CrosswalkGovernanceStateError(
                    "Exact verification requires an exact-code source candidate."
                )
            if decision.mapping_state == "approved_alias" and not any(
                status == "approved_institutional_alias"
                for status in source_statuses[decision.dataset_field]
            ):
                raise CrosswalkGovernanceStateError(
                    "Approved alias governance requires versioned alias source evidence."
                )
            if (
                decision.mapping_state == "approved_alias"
                and decision.institutional_alias_reference
                not in alias_references[decision.dataset_field]
            ):
                raise CrosswalkGovernanceStateError(
                    "Approved alias governance must pin the exact source alias reference."
                )
            if decision.mapping_state == "out_of_catalog" and not any(
                status in {"non_catalog_field", "no_supported_match"}
                for status in source_statuses[decision.dataset_field]
            ):
                raise CrosswalkGovernanceStateError(
                    "Out-of-catalog governance requires source evidence with no supported match."
                )

    def _authorize_current(
        self,
        context: BureauCatalogAccessContext,
        lineage: CrosswalkLineage,
        permission: CrosswalkProjectPermission,
    ) -> None:
        self._authorize_project(context, lineage.project_id, permission)
        self._authorize_catalog(context, lineage)
        self._require_current_lineage(context, lineage)

    def register_candidate(
        self,
        *,
        context: BureauCatalogAccessContext,
        source: BureauDatasetCrosswalk,
        lineage: CrosswalkLineage,
        decisions: tuple[GovernedMappingDecision, ...],
        audit: CrosswalkAuditMetadata,
    ) -> GovernedCrosswalkRevision:
        """Register a draft only; candidate analysis can never auto-confirm mappings."""

        self._authorize_current(context, lineage, "edit")
        self._require_actor(context, audit)
        self._validate_source_identity(source, lineage, decisions)
        governance_id = governance_identity(lineage, source.crosswalk_id)
        record = build_governed_revision(
            governance_id=governance_id,
            revision=1,
            lifecycle_state="draft",
            lineage=lineage,
            source_crosswalk_id=source.crosswalk_id,
            source_crosswalk_checksum=source.crosswalk_checksum,
            decisions=decisions,
            audit=audit,
        )
        return self._repository.append(record, expected_revision=0)

    def revise(
        self,
        *,
        context: BureauCatalogAccessContext,
        lineage: CrosswalkLineage,
        governance_id: str,
        expected_revision: int,
        decisions: tuple[GovernedMappingDecision, ...],
        audit: CrosswalkAuditMetadata,
        confirm: bool = False,
    ) -> GovernedCrosswalkRevision:
        self._authorize_current(context, lineage, "edit")
        self._require_actor(context, audit)
        current = self._repository.get_current(governance_id)
        if current.lineage != lineage:
            raise CrosswalkGovernanceLineageError("governance_lineage_mismatch")
        current_fields = {decision.dataset_field for decision in current.decisions}
        revised_fields = {decision.dataset_field for decision in decisions}
        if revised_fields != current_fields:
            raise CrosswalkGovernanceStateError(
                "A revision must preserve the exact governed field inventory."
            )
        if confirm and not is_confirmable(decisions):
            raise CrosswalkGovernanceStateError(
                "Crosswalk confirmation requires evidence-complete terminal decisions."
            )
        record = build_governed_revision(
            governance_id=current.governance_id,
            revision=expected_revision + 1,
            lifecycle_state="confirmed" if confirm else "review_required",
            lineage=current.lineage,
            source_crosswalk_id=current.source_crosswalk_id,
            source_crosswalk_checksum=current.source_crosswalk_checksum,
            decisions=decisions,
            audit=audit,
            previous_revision_checksum=current.revision_checksum,
        )
        return self._repository.append(
            record,
            expected_revision=expected_revision,
        )

    def get_current(
        self,
        *,
        context: BureauCatalogAccessContext,
        lineage: CrosswalkLineage,
        governance_id: str,
    ) -> GovernedCrosswalkRevision:
        self._authorize_current(context, lineage, "view")
        record = self._repository.get_current(governance_id)
        if record.lineage != lineage:
            raise CrosswalkGovernanceLineageError("governance_lineage_mismatch")
        return record

    def get_revision(
        self,
        *,
        context: BureauCatalogAccessContext,
        lineage: CrosswalkLineage,
        governance_id: str,
        revision: int,
    ) -> GovernedCrosswalkRevision:
        self._authorize_current(context, lineage, "view")
        record = self._repository.get_revision(governance_id, revision)
        if record.lineage != lineage:
            raise CrosswalkGovernanceLineageError("governance_lineage_mismatch")
        return record

    def history(
        self,
        *,
        context: BureauCatalogAccessContext,
        lineage: CrosswalkLineage,
        governance_id: str,
    ) -> tuple[GovernedCrosswalkRevision, ...]:
        """Return exact historical evidence, including rejected mapping states.

        Historical audit is authorized and catalog-entitled but deliberately does
        not require that the old lineage still be active.  It never substitutes a
        latest or first lineage: every returned record must match the supplied one.
        """

        self._authorize_project(context, lineage.project_id, "view")
        self._authorize_catalog(context, lineage)
        history = self._repository.history(governance_id)
        if any(record.lineage != lineage for record in history):
            raise CrosswalkGovernanceLineageError("governance_lineage_mismatch")
        return history


__all__ = [
    "CrosswalkGovernanceAccessDeniedError",
    "CrosswalkGovernanceLineageError",
    "CrosswalkGovernanceStateError",
    "CrosswalkLineageAuthority",
    "CrosswalkProjectAuthorizationProvider",
    "CrosswalkProjectPermission",
    "GovernedCrosswalkService",
]

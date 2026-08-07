"""Governed HTTP adapter for exact dataset-version bureau crosswalks.

Candidate analysis is rebuilt by the server from the current predictor
authorization and exact active catalog binding.  Browser-supplied schemas,
catalog enumeration, dataset rows, and holdout data are intentionally absent.
Only an explicit analyst decision can create a governance revision.  That
action then appends a catalog-binding revision which pins the exact governed
crosswalk revision; a failure of the second append is reported as a partial
metadata state and never treated as an atomic success.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any, Callable, Dict, Literal, Mapping
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..persistence.service import get_persistence_service
from ..preprocessing.predictor_authorization import (
    PredictorAuthorizationIntegrityError,
    verify_durable_predictor_authorization,
)
from ..security.security_store import require_user
from .catalog_binding import (
    CatalogBindingEvidenceReference,
    DatasetCatalogBindingScope,
)
from .catalog_binding_repository import (
    CatalogBindingConflictError,
    CatalogBindingNotFoundError,
    CatalogBindingRepositoryError,
    CatalogBindingRepositoryStateError,
)
from .catalog_binding_service import (
    CatalogBindingAccessDeniedError,
    CatalogBindingCatalogError,
    CatalogBindingCurrentResolution,
    CatalogBindingLineageError,
    CatalogBindingStateError,
)
from .catalog_consistency import reconcile_catalog_consistency
from .catalog_documentation import record_binding_evidence_and_documentation
from .catalog_registry import CatalogRegistryError, CatalogRegistryNotFoundError
from .catalog_service import (
    BureauCatalogAccessDeniedError,
    BureauCatalogLookupError,
)
from .crosswalk_governance import (
    CrosswalkAuditMetadata,
    CrosswalkEvidenceReference,
    CrosswalkLineage,
    GovernedCrosswalkRevision,
    GovernedMappingDecision,
    MappingGovernanceState,
    governance_identity,
)
from .crosswalk_governance_repository import (
    CrosswalkGovernanceConflictError,
    CrosswalkGovernanceNotFoundError,
    CrosswalkGovernanceRepositoryError,
    CrosswalkGovernanceStateError as CrosswalkGovernanceRepositoryStateError,
    SQLiteGovernedCrosswalkRepository,
)
from .crosswalk_governance_service import (
    CrosswalkGovernanceAccessDeniedError,
    CrosswalkGovernanceLineageError,
    CrosswalkGovernanceStateError,
    GovernedCrosswalkService,
)
from .normalizer import canonical_json_bytes
from .operational_service import (
    CatalogOperationalError,
    OperationalCatalogService,
    get_operational_catalog_service,
)
from .restricted_storage import RestrictedStorageError
from .semantic_annotation import (
    BureauOrdinaryRangeReference,
    BureauSpecialDefinitionReference,
    build_bureau_semantic_annotation,
)
from .types import BureauCatalogAccessContext, BureauDatasetCrosswalk


router = APIRouter()

_MAX_FIELDS = 250
_MAX_CANDIDATES = 1_000
_MAX_HISTORY_LIMIT = 100
_SOURCE_CONTRACT_VERSION = "bureau-crosswalk-authoritative-schema-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def _safe_identifier(value: object, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or len(cleaned) > 256 or any(
        ord(character) < 32 or ord(character) == 127 for character in cleaned
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "bureau_crosswalk_identity_invalid",
                "message": f"The exact {label} identity is invalid.",
            },
        )
    return cleaned


def _nonmutation_payload() -> dict[str, bool]:
    return {
        "dataset_mutated": False,
        "target_contract_mutated": False,
        "treatment_mutated": False,
        "predictor_authorization_mutated": False,
        "analysis_partition_mutated": False,
        "feature_manifest_mutated": False,
    }


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MappingDecisionRequest(_StrictRequest):
    dataset_field: str = Field(min_length=1, max_length=256)
    mapping_state: MappingGovernanceState
    candidate_attribute_code: str | None = Field(default=None, max_length=256)
    alternative_attribute_codes: tuple[str, ...] = Field(default=(), max_length=32)
    source_attribute_codes: tuple[str, ...] = Field(default=(), max_length=32)
    rationale: str | None = Field(default=None, max_length=2_048)
    alias_authority_id: str | None = Field(default=None, max_length=160)
    institutional_alias_reference: str | None = Field(default=None, max_length=160)
    transformation_reference_id: str | None = Field(default=None, max_length=160)
    transformation_rule: str | None = Field(default=None, max_length=2_048)
    transformation_or_recoding_concerns: tuple[str, ...] = Field(
        default=(), max_length=16
    )
    data_type: str | None = Field(default=None, max_length=128)
    units: str | None = Field(default=None, max_length=128)
    source_system: str | None = Field(default=None, max_length=256)
    timing: str | None = Field(default=None, max_length=1_024)
    special_value_handling: str | None = Field(default=None, max_length=1_024)
    value_range_reconciliation: str | None = Field(default=None, max_length=1_024)
    special_value_reconciliation: str | None = Field(default=None, max_length=1_024)

    @field_validator(
        "dataset_field",
        "candidate_attribute_code",
        "rationale",
        "alias_authority_id",
        "institutional_alias_reference",
        "transformation_reference_id",
        "transformation_rule",
        "data_type",
        "units",
        "source_system",
        "timing",
        "special_value_handling",
        "value_range_reconciliation",
        "special_value_reconciliation",
    )
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Crosswalk decision text contains unsupported characters.")
        return value

    @field_validator(
        "alternative_attribute_codes",
        "source_attribute_codes",
        "transformation_or_recoding_concerns",
    )
    @classmethod
    def normalize_bounded_sequences(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(sorted({str(value).strip() for value in values if str(value).strip()}))
        if any(
            len(value) > 512
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            for value in cleaned
        ):
            raise ValueError("Crosswalk decision sequences contain invalid values.")
        return cleaned


class CrosswalkDecisionRevisionRequest(_StrictRequest):
    expected_crosswalk_revision: int = Field(ge=0)
    expected_binding_revision: int = Field(ge=1)
    decisions: tuple[MappingDecisionRequest, ...] = Field(
        min_length=1, max_length=_MAX_FIELDS
    )
    analyst_reason: str = Field(min_length=8, max_length=1_024)
    confirm_crosswalk: bool = False

    @field_validator("analyst_reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Analyst reason contains unsupported characters.")
        return " ".join(value.split())

    @model_validator(mode="after")
    def unique_fields(self) -> "CrosswalkDecisionRevisionRequest":
        fields = [decision.dataset_field.casefold() for decision in self.decisions]
        if len(fields) != len(set(fields)):
            raise ValueError("Each field may appear only once in a decision batch.")
        return self


class CrosswalkBindingLinkRequest(_StrictRequest):
    crosswalk_revision: int = Field(ge=1)
    expected_binding_revision: int = Field(ge=1)
    analyst_reason: str = Field(min_length=8, max_length=1_024)

    @field_validator("analyst_reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Analyst reason contains unsupported characters.")
        return " ".join(value.split())


class _ExactCrosswalkLineageAuthority:
    def __init__(self, lineage: CrosswalkLineage) -> None:
        self._lineage = lineage

    def current_lineage(
        self, context: BureauCatalogAccessContext, project_id: str
    ) -> CrosswalkLineage:
        if context.project_id != project_id or self._lineage.project_id != project_id:
            raise CrosswalkGovernanceAccessDeniedError(
                "Crosswalk governance access is not authorized."
            )
        return self._lineage


@dataclass(frozen=True, slots=True)
class CrosswalkRouterRuntime:
    binding_runtime: Any
    scope: DatasetCatalogBindingScope
    binding_resolution: CatalogBindingCurrentResolution
    predictor_manifest: Mapping[str, Any]
    lineage: CrosswalkLineage
    repository: SQLiteGovernedCrosswalkRepository
    service: GovernedCrosswalkService
    documentation_recorder: Callable[..., Mapping[str, str]] = (
        record_binding_evidence_and_documentation
    )
    observed_summary_provider: Callable[
        ["CrosswalkRouterRuntime"], Mapping[str, Mapping[str, Any]]
    ] | None = None

    @property
    def context(self) -> BureauCatalogAccessContext:
        return self.binding_runtime.context


def _build_runtime(
    *,
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    user: Mapping[str, Any],
    operational: OperationalCatalogService,
) -> CrosswalkRouterRuntime:
    # Imported lazily so the binding router can remain independently testable.
    from .catalog_binding_router import (
        ProductionBindingProjectAuthorization,
        build_catalog_binding_runtime,
    )

    binding_runtime = build_catalog_binding_runtime(
        user,
        project_id=project_id,
        operational_service=operational,
    )
    scope, _exact_lineage = binding_runtime.resolve_scope(
        _safe_identifier(project_id, "project"),
        _safe_identifier(dataset_id, "dataset"),
        _safe_identifier(dataset_version_id, "dataset version"),
    )
    resolution = binding_runtime.service.resolve_current(
        context=binding_runtime.context,
        scope=scope,
    )
    if resolution.effective_status != "active" or not resolution.lineage_current:
        raise CrosswalkGovernanceLineageError("catalog_binding_not_current")
    identity = resolution.binding.identity
    record = (
        get_persistence_service()
        .predictor_authorizations.get_current_exact(
            scope.project_id,
            scope.dataset_id,
            scope.dataset_version_id,
            identity.target_contract_id,
        )
    )
    try:
        manifest = verify_durable_predictor_authorization(
            record,
            project_id=scope.project_id,
            dataset_id=scope.dataset_id,
            dataset_version_id=scope.dataset_version_id,
        )
    except PredictorAuthorizationIntegrityError as exc:
        raise CrosswalkGovernanceLineageError(
            "predictor_authorization_unavailable"
        ) from exc
    if (
        str(manifest.get("target_contract_id") or "") != identity.target_contract_id
        or str(manifest.get("predictor_authorization_id") or "")
        != identity.predictor_authorization_id
    ):
        raise CrosswalkGovernanceLineageError(
            "predictor_authorization_contradictory"
        )
    lineage = CrosswalkLineage(
        project_id=identity.project_id,
        dataset_id=identity.dataset_id,
        dataset_version_id=identity.dataset_version_id,
        activation_revision=identity.activation_revision,
        target_contract_id=identity.target_contract_id,
        predictor_authorization_id=identity.predictor_authorization_id,
        schema_checksum=identity.schema_checksum,
        catalog_key=identity.catalog_key,
        catalog_checksum=identity.catalog_checksum,
    )
    repository = SQLiteGovernedCrosswalkRepository(operational.root)
    service = GovernedCrosswalkService(
        repository=repository,
        project_authorization=ProductionBindingProjectAuthorization(user),
        catalog_entitlements=binding_runtime.catalog_entitlements,
        lineage_authority=_ExactCrosswalkLineageAuthority(lineage),
    )
    return CrosswalkRouterRuntime(
        binding_runtime=binding_runtime,
        scope=scope,
        binding_resolution=resolution,
        predictor_manifest=manifest,
        lineage=lineage,
        repository=repository,
        service=service,
    )


def get_crosswalk_router_runtime(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    user: Dict[str, Any] = Depends(require_user),
    operational: OperationalCatalogService = Depends(get_operational_catalog_service),
) -> CrosswalkRouterRuntime:
    try:
        return _build_runtime(
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
            user=user,
            operational=operational,
        )
    except Exception as exc:
        raise _safe_http_error(exc) from exc


def _authorized_schema(runtime: CrosswalkRouterRuntime) -> tuple[tuple[dict[str, str], ...], str, tuple[str, ...]]:
    manifest = runtime.predictor_manifest
    target = str(manifest.get("target") or "").strip()
    excluded = {
        str(value).strip()
        for value in manifest.get("target_source_excluded", [])
        if str(value).strip()
    }
    excluded.update(
        str(value).strip()
        for value in dict(manifest.get("excluded_predictors") or {})
        if str(value).strip()
    )
    predictors = tuple(
        sorted(
            {
                str(value).strip()
                for value in manifest.get("authorized_predictors", [])
                if str(value).strip()
            },
            key=str.casefold,
        )
    )
    if not predictors or len(predictors) > _MAX_FIELDS:
        raise CrosswalkGovernanceStateError(
            "The exact authorized predictor inventory is unavailable or exceeds its bound."
        )
    forbidden = {value.casefold() for value in excluded}
    if target:
        forbidden.add(target.casefold())
    if any(predictor.casefold() in forbidden for predictor in predictors):
        raise CrosswalkGovernanceLineageError(
            "predictor_authorization_contains_target_or_exclusion"
        )
    return tuple({"field_name": predictor} for predictor in predictors), target, tuple(sorted(excluded, key=str.casefold))


def _rebuild_source(runtime: CrosswalkRouterRuntime) -> BureauDatasetCrosswalk:
    fields, target, target_sources = _authorized_schema(runtime)
    identity = runtime.binding_resolution.binding.identity
    candidate = runtime.binding_runtime.operational.catalogs.build_dataset_crosswalk_candidates_exact(
        runtime.context,
        identity.catalog_key,
        identity.catalog_checksum,
        fields,
        target_field=target or None,
        target_source_fields=target_sources,
    )
    mappings = tuple(candidate.get("mappings") or ())
    if not mappings or len(mappings) > _MAX_CANDIDATES:
        raise CrosswalkGovernanceStateError(
            "The bounded candidate crosswalk is unavailable."
        )
    candidate_checksum = str(candidate.get("crosswalk_checksum") or "")
    identity_payload = {
        "contract_version": _SOURCE_CONTRACT_VERSION,
        "lineage": runtime.lineage.model_dump(mode="json"),
        "candidate_checksum": candidate_checksum,
        "authorized_fields": [field["field_name"] for field in fields],
    }
    source_checksum = _sha256(identity_payload)
    source_id = "bcw_" + source_checksum[:32]
    return BureauDatasetCrosswalk.model_validate(
        {
            "crosswalk_id": source_id,
            "revision": 1,
            "project_id": runtime.lineage.project_id,
            "dataset_id": runtime.lineage.dataset_id,
            "dataset_version_id": runtime.lineage.dataset_version_id,
            "schema_checksum": runtime.lineage.schema_checksum,
            "target_contract_id": runtime.lineage.target_contract_id,
            "predictor_authorization_id": runtime.lineage.predictor_authorization_id,
            "catalog_key": runtime.lineage.catalog_key,
            "catalog_checksum": runtime.lineage.catalog_checksum,
            "mappings": mappings,
            "crosswalk_status": "candidate_only",
            "candidate_only": True,
            "approved_mappings": (),
            "governed_feature_set_changed": False,
            "dataset_mutated": False,
            "created_by": "bureau-crosswalk-candidate-service",
            "created_at": _utc_now(),
            "crosswalk_checksum": source_checksum,
        }
    )


def _evidence(
    *,
    kind: str,
    field: str,
    authority_id: str,
    source_checksum: str,
    actor: str,
    created_at: str,
    evidence_id: str | None = None,
) -> CrosswalkEvidenceReference:
    checksum = _sha256(
        {
            "kind": kind,
            "field": field,
            "authority_id": authority_id,
            "source_checksum": source_checksum,
            "actor": actor,
        }
    )
    return CrosswalkEvidenceReference(
        evidence_id=evidence_id or f"cwe-{kind[:24]}-{checksum[:24]}",
        evidence_kind=kind,
        authority_id=authority_id,
        checksum=checksum,
        created_by=actor,
        created_at=created_at,
    )


def _default_decisions(
    source: BureauDatasetCrosswalk,
) -> tuple[GovernedMappingDecision, ...]:
    grouped: dict[str, list[Any]] = {}
    for mapping in source.mappings:
        grouped.setdefault(mapping.dataset_field, []).append(mapping)
    created_at = _utc_now()
    actor = "bureau-crosswalk-candidate-service"
    decisions: list[GovernedMappingDecision] = []
    for field in sorted(grouped, key=str.casefold):
        candidates = grouped[field]
        codes = tuple(
            sorted(
                {
                    code
                    for candidate in candidates
                    for code in (
                        *((candidate.candidate_attribute_code,) if candidate.candidate_attribute_code else ()),
                        *candidate.ambiguity,
                    )
                }
            )
        )
        statuses = {candidate.match_status for candidate in candidates}
        primary = codes[0] if codes else None
        concerns = tuple(
            sorted(
                {
                    concern
                    for candidate in candidates
                    for concern in candidate.transformation_or_recoding_concerns
                }
            )
        )
        if "unresolved_recoding" in statuses and primary:
            state: MappingGovernanceState = "recoding_evidence_required"
            kind = "recoding_observation"
            kwargs: dict[str, Any] = {
                "candidate_attribute_code": primary,
                "transformation_or_recoding_concerns": concerns
                or ("Durable recoding evidence remains required.",),
            }
        elif len(codes) > 1 or "multiple_possible_matches" in statuses:
            state = "ambiguous_review_required"
            kind = "ambiguity_analysis"
            kwargs = {
                "candidate_attribute_code": primary,
                "alternative_attribute_codes": codes,
            }
        elif primary:
            # Even an exact-code candidate remains review-required until an
            # explicit analyst decision supplies terminal evidence.
            state = "probable_review_required"
            kind = "semantic_analysis"
            kwargs = {"candidate_attribute_code": primary}
        else:
            state = "unresolved"
            kind = "unresolved_assessment"
            kwargs = {}
        evidence = (
            _evidence(
                kind=kind,
                field=field,
                authority_id=source.crosswalk_id,
                source_checksum=source.crosswalk_checksum,
                actor=actor,
                created_at=created_at,
            ),
        )
        decisions.append(
            GovernedMappingDecision(
                dataset_field=field,
                mapping_state=state,
                evidence=evidence,
                analyst_confirmed=False,
                **kwargs,
            )
        )
    return tuple(decisions)


def _decision_from_request(
    request: MappingDecisionRequest,
    *,
    source: BureauDatasetCrosswalk,
    actor: str,
    created_at: str,
) -> GovernedMappingDecision:
    state = request.mapping_state
    terminal = state in {
        "exact_verified",
        "approved_alias",
        "transformed_or_derived",
        "out_of_catalog",
        "rejected",
    }
    evidence_kinds: dict[str, tuple[str, ...]] = {
        "exact_verified": ("catalog_definition", "exact_match", "analyst_review"),
        "approved_alias": ("institutional_alias", "analyst_review"),
        "transformed_or_derived": ("transformation_lineage", "analyst_review"),
        "probable_review_required": ("semantic_analysis",),
        "ambiguous_review_required": ("ambiguity_analysis",),
        "recoding_evidence_required": ("recoding_observation",),
        "unresolved": ("unresolved_assessment",),
        "out_of_catalog": ("out_of_catalog_assessment", "analyst_review"),
        "rejected": ("analyst_review",),
    }
    evidence: list[CrosswalkEvidenceReference] = []
    for kind in evidence_kinds[state]:
        authority = source.crosswalk_id
        evidence_id = None
        if kind == "catalog_definition":
            authority = source.catalog_checksum
        elif kind == "institutional_alias":
            authority = request.alias_authority_id or "missing-alias-authority"
            evidence_id = request.institutional_alias_reference
        elif kind == "transformation_lineage":
            authority = "feature-transformation-authority"
            evidence_id = request.transformation_reference_id
        elif kind == "analyst_review":
            authority = "bureau-crosswalk-review"
        evidence.append(
            _evidence(
                kind=kind,
                field=request.dataset_field,
                authority_id=authority,
                source_checksum=source.crosswalk_checksum,
                actor=actor,
                created_at=created_at,
                evidence_id=evidence_id,
            )
        )
    return GovernedMappingDecision(
        **request.model_dump(mode="python"),
        evidence=tuple(evidence),
        analyst_confirmed=terminal,
        reviewer_id=actor if terminal else None,
    )


def _governance_id(runtime: CrosswalkRouterRuntime, source: BureauDatasetCrosswalk) -> str:
    return governance_identity(runtime.lineage, source.crosswalk_id)


def _merge_decisions(
    runtime: CrosswalkRouterRuntime,
    source: BureauDatasetCrosswalk,
    governance_id_value: str,
    payload: CrosswalkDecisionRevisionRequest,
) -> tuple[GovernedMappingDecision, ...]:
    if payload.expected_crosswalk_revision == 0:
        base = _default_decisions(source)
    else:
        current = runtime.service.get_current(
            context=runtime.context,
            lineage=runtime.lineage,
            governance_id=governance_id_value,
        )
        if current.revision != payload.expected_crosswalk_revision:
            raise CrosswalkGovernanceConflictError(
                expected_revision=payload.expected_crosswalk_revision,
                current_revision=current.revision,
            )
        if (
            current.source_crosswalk_id != source.crosswalk_id
            or current.source_crosswalk_checksum != source.crosswalk_checksum
        ):
            raise CrosswalkGovernanceLineageError("candidate_source_changed")
        base = current.decisions
    merged = {decision.dataset_field: decision for decision in base}
    requested = {decision.dataset_field for decision in payload.decisions}
    if not requested.issubset(merged):
        raise CrosswalkGovernanceStateError(
            "Decision fields must belong to the exact authorized predictor inventory."
        )
    created_at = _utc_now()
    for decision in payload.decisions:
        merged[decision.dataset_field] = _decision_from_request(
            decision,
            source=source,
            actor=runtime.context.principal_id,
            created_at=created_at,
        )
    return tuple(merged[field] for field in sorted(merged, key=str.casefold))


def _audit(runtime: CrosswalkRouterRuntime, reason: str) -> CrosswalkAuditMetadata:
    return CrosswalkAuditMetadata(
        actor_id=runtime.context.principal_id,
        request_id="bureau-crosswalk-http-" + uuid.uuid4().hex,
        occurred_at=_utc_now(),
        reason=reason,
    )


def _binding_crosswalk_evidence(
    governance: GovernedCrosswalkRevision,
) -> CatalogBindingEvidenceReference:
    return CatalogBindingEvidenceReference(
        evidence_id=f"binding-crosswalk-{governance.revision_checksum[:24]}",
        evidence_kind="crosswalk_governance",
        authority_id=governance.governance_id,
        checksum=governance.revision_checksum,
        recorded_at=governance.audit.occurred_at,
    )


def _link_exact_governance(
    runtime: CrosswalkRouterRuntime,
    governance: GovernedCrosswalkRevision,
    *,
    expected_binding_revision: int,
) -> tuple[Any, bool]:
    resolution = runtime.binding_runtime.service.resolve_current(
        context=runtime.context,
        scope=runtime.scope,
    )
    current = resolution.binding
    if resolution.effective_status != "active" or not resolution.lineage_current:
        raise CrosswalkGovernanceLineageError("catalog_binding_not_current")
    if (
        current.crosswalk_id == governance.governance_id
        and current.crosswalk_revision == governance.revision
    ):
        return current, True
    if current.revision != expected_binding_revision:
        raise CatalogBindingConflictError(
            expected_revision=expected_binding_revision,
            current_revision=current.revision,
        )
    preserved = tuple(
        item for item in current.evidence if item.evidence_kind != "crosswalk_governance"
    )
    evidence = preserved + (_binding_crosswalk_evidence(governance),)
    linked = runtime.binding_runtime.service.revise(
        context=runtime.context,
        identity=current.identity,
        expected_revision=expected_binding_revision,
        status="active",
        actor_id=runtime.context.principal_id,
        evidence=evidence,
        crosswalk_id=governance.governance_id,
        crosswalk_revision=governance.revision,
    )
    if (
        linked.crosswalk_id != governance.governance_id
        or linked.crosswalk_revision != governance.revision
    ):
        raise CatalogBindingLineageError("crosswalk_link_contradictory")
    return linked, False


def _governance_envelope(
    governance: GovernedCrosswalkRevision,
    *,
    binding: Any | None = None,
    binding_linked: bool,
    idempotent_link: bool = False,
) -> dict[str, Any]:
    return {
        "governance": governance.model_dump(mode="json"),
        "binding": binding.model_dump(mode="json") if binding is not None else None,
        "binding_linked": binding_linked,
        "idempotent_binding_link": idempotent_link,
        **_nonmutation_payload(),
    }


def _bounded_governance_counts(
    governance: GovernedCrosswalkRevision,
) -> dict[str, int]:
    """Project only bounded decision counts into evidence/MDD records."""

    authoritative = {"exact_verified", "approved_alias"}
    review_required = {
        "probable_review_required",
        "ambiguous_review_required",
        "recoding_evidence_required",
    }
    unresolved = {"unresolved", "out_of_catalog"}
    return {
        "authoritative": sum(
            decision.analyst_confirmed and decision.mapping_state in authoritative
            for decision in governance.decisions
        ),
        "review_required": sum(
            decision.mapping_state in review_required
            for decision in governance.decisions
        ),
        "unresolved": sum(
            decision.mapping_state in unresolved
            for decision in governance.decisions
        ),
        "rejected": sum(
            decision.mapping_state == "rejected"
            for decision in governance.decisions
        ),
        # Crosswalk confirmation references provider semantics but does not
        # materialize or apply any special-value definition.
        "special_definitions_used": 0,
        "contradictions": 0,
    }


def _record_exact_documentation(
    runtime: CrosswalkRouterRuntime,
    *,
    binding: Any,
    governance: GovernedCrosswalkRevision,
) -> Mapping[str, str]:
    return runtime.documentation_recorder(
        binding=binding,
        actor_id=runtime.context.principal_id,
        mapping_counts=_bounded_governance_counts(governance),
        entitlement_verified=True,
    )


def _bounded_provider_semantics(
    runtime: CrosswalkRouterRuntime,
    *,
    binding: Any,
    accepted: tuple[GovernedMappingDecision, ...],
) -> Mapping[str, tuple[Any, ...]]:
    """Load exact accepted exact/alias definitions once; never enumerate them."""

    eligible = tuple(
        decision
        for decision in accepted
        if decision.mapping_state in {"exact_verified", "approved_alias"}
        and decision.candidate_attribute_code
    )
    if not eligible:
        return {}
    codes = tuple(
        sorted(
            {str(decision.candidate_attribute_code) for decision in eligible},
            key=str.casefold,
        )
    )
    if len(codes) > _MAX_FIELDS:
        raise CrosswalkGovernanceStateError(
            "The accepted semantic annotation inventory exceeds its bound."
        )
    batch = runtime.binding_runtime.operational.get_mapped_attribute_batch(
        principal_id=runtime.context.principal_id,
        tenant_id=runtime.context.tenant_id,
        catalog_version_id=binding.identity.catalog_version_id,
        attribute_codes=codes,
    )
    if (
        str(batch.get("catalog_version_id") or "")
        != binding.identity.catalog_version_id
        or str(batch.get("catalog_checksum") or "")
        != binding.identity.catalog_checksum
        or int(batch.get("requested") or 0) != len(codes)
        or int(batch.get("returned") or 0) != len(codes)
        or batch.get("bounded") is not True
    ):
        raise CrosswalkGovernanceLineageError(
            "accepted_mapping_definition_batch_contradictory"
        )
    result: dict[str, tuple[Any, ...]] = {}
    rows = tuple(batch.get("attributes") or ())
    by_code = {
        str(row.get("attribute_code") or ""): row
        for row in rows
        if isinstance(row, Mapping)
    }
    if set(by_code) != set(codes):
        raise CrosswalkGovernanceLineageError(
            "accepted_mapping_definition_batch_contradictory"
        )
    for code in codes:
        attribute = by_code.get(code)
        if not attribute:
            raise CrosswalkGovernanceLineageError(
                "accepted_mapping_definition_unavailable"
            )
        special_rows = tuple(attribute.get("special_values") or ())
        ordinary_range = None
        if (
            attribute.get("valid_range_expression")
            or attribute.get("ordinary_min")
            or attribute.get("ordinary_max")
        ):
            ordinary_range = BureauOrdinaryRangeReference(
                attribute_code=code,
                definition_id=f"attribute-{str(attribute['record_checksum'])[:24]}",
                definition_checksum=str(attribute["record_checksum"]),
                ordinary_min=attribute.get("ordinary_min"),
                ordinary_max=attribute.get("ordinary_max"),
                range_expression=attribute.get("valid_range_expression"),
            )
        special_definitions = tuple(
            BureauSpecialDefinitionReference(
                attribute_code=code,
                definition_id=str(special.get("definition_id") or ""),
                definition_checksum=str(special.get("definition_checksum") or ""),
                value_code=str(special.get("value_code") or ""),
                semantic_family=str(special.get("semantic_family") or ""),
                meaning=str(special.get("meaning") or ""),
            )
            for special in special_rows
            if isinstance(special, Mapping)
        )
        result[code] = (
            attribute,
            ordinary_range,
            special_definitions,
        )
    return result


def _bounded_sequence(value: object, *, maximum: int = 64) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        sorted(
            {
                str(item).strip()
                for item in value[:maximum]
                if str(item or "").strip()
            },
            key=str.casefold,
        )
    )


def _unique_field_rows(
    rows: object,
    *,
    name_keys: tuple[str, ...],
) -> Mapping[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    folded: set[str] = set()
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, Mapping):
            raise CrosswalkGovernanceLineageError(
                "dataset_schema_summary_contradictory"
            )
        name = next(
            (
                str(row.get(key) or "").strip()
                for key in name_keys
                if str(row.get(key) or "").strip()
            ),
            "",
        )
        if not name or name.casefold() in folded:
            raise CrosswalkGovernanceLineageError(
                "dataset_schema_summary_contradictory"
            )
        folded.add(name.casefold())
        result[name] = row
    return result


def _backend_authoritative_observed_summaries(
    runtime: CrosswalkRouterRuntime,
) -> Mapping[str, Mapping[str, Any]]:
    """Read exact persisted schema/detection summaries without dataset rows.

    Dataset Library ``schema_json`` / ``profile_json`` and the exact durable
    special-value detection record are backend authorities already bound to
    this dataset version.  Browser previews, sample CSVs, full data, partition
    assignments, and holdout artifacts are intentionally not referenced.
    """

    persistence = get_persistence_service()
    version = persistence.datasets.get_version(runtime.lineage.dataset_version_id)
    if not version:
        return {}
    if str(version.get("dataset_id") or "") != runtime.lineage.dataset_id:
        raise CrosswalkGovernanceLineageError(
            "dataset_schema_summary_identity_contradictory"
        )
    schema_payload = version.get("schema_json")
    profile_payload = version.get("profile_json")
    schema_payload = schema_payload if isinstance(schema_payload, Mapping) else {}
    profile_payload = profile_payload if isinstance(profile_payload, Mapping) else {}
    schema_rows = _unique_field_rows(
        schema_payload.get("columns"), name_keys=("name", "field_name", "column")
    )
    profile_rows = _unique_field_rows(
        profile_payload.get("schema"), name_keys=("name", "field_name", "column")
    )
    if schema_rows and profile_rows and set(schema_rows) != set(profile_rows):
        raise CrosswalkGovernanceLineageError(
            "dataset_schema_profile_contradictory"
        )
    observed_rows = profile_rows or schema_rows

    special_by_field: Mapping[str, Mapping[str, Any]] = {}
    special_review = persistence.special_value_reviews.get_exact(
        runtime.lineage.project_id,
        runtime.lineage.dataset_id,
        runtime.lineage.dataset_version_id,
    )
    if special_review:
        if (
            int(special_review.get("activation_revision") or 0)
            != runtime.lineage.activation_revision
            or str(special_review.get("predictor_authorization_id") or "")
            != runtime.lineage.predictor_authorization_id
            or str(special_review.get("target_contract_id") or "")
            != runtime.lineage.target_contract_id
        ):
            raise CrosswalkGovernanceLineageError(
                "special_value_summary_lineage_contradictory"
            )
        detection = special_review.get("detection_json")
        detection = detection if isinstance(detection, Mapping) else {}
        if (
            detection.get("final_holdout_accessed") is not False
            or str(detection.get("structural_scope") or "")
            != "full_governed_population_predictors_only"
        ):
            raise CrosswalkGovernanceLineageError(
                "special_value_summary_scope_contradictory"
            )
        special_by_field = _unique_field_rows(
            detection.get("variables"), name_keys=("variable",)
        )

    authorized = {
        str(value).strip()
        for value in runtime.predictor_manifest.get("authorized_predictors", ())
        if str(value or "").strip()
    }
    summaries: dict[str, Mapping[str, Any]] = {}
    for field in sorted(authorized, key=str.casefold):
        row = observed_rows.get(field)
        if row is None:
            continue
        special = special_by_field.get(field)
        special_values = tuple(
            str(item.get("value")).strip()
            for item in ((special or {}).get("special_values") or ())
            if isinstance(item, Mapping) and item.get("value") is not None
        )
        observed_values = _bounded_sequence(
            row.get("observedValues")
            or row.get("observed_values")
            or row.get("validValuesSample")
            or row.get("valid_values_sample")
        )
        payload: dict[str, Any] = {
            "dataset_field": field,
            "data_type": str(
                (special or {}).get("datatype")
                or row.get("dtype")
                or row.get("data_type")
                or ""
            ).strip(),
            "field_length": (
                row.get("fieldLength")
                or row.get("field_length")
                or row.get("maxLength")
                or row.get("max_length")
            ),
            "observed_min": row.get("min", row.get("observed_min")),
            "observed_max": row.get("max", row.get("observed_max")),
            "observed_values": observed_values,
            "source_version": str(
                row.get("sourceVersion")
                or row.get("source_version")
                or row.get("applicableVersion")
                or row.get("applicable_version")
                or ""
            ).strip(),
            "observed_special_values": tuple(sorted(set(special_values))),
            "special_summary_available": special is not None,
            "source": "exact_persisted_dataset_schema_and_special_value_summary",
            "schema_checksum": runtime.lineage.schema_checksum,
            "raw_rows_accessed": False,
            "browser_preview_used": False,
            "final_holdout_accessed": False,
        }
        payload["summary_checksum"] = _sha256(payload)
        summaries[field] = payload
    return summaries


def _resolve_exact_bound_governance(
    runtime: CrosswalkRouterRuntime,
) -> tuple[BureauDatasetCrosswalk, Any, GovernedCrosswalkRevision]:
    source = _rebuild_source(runtime)
    expected_governance_id = _governance_id(runtime, source)
    resolution = runtime.binding_runtime.service.resolve_current(
        context=runtime.context,
        scope=runtime.scope,
    )
    binding = resolution.binding
    if (
        resolution.effective_status != "active"
        or not resolution.lineage_current
        or not binding.crosswalk_id
        or not binding.crosswalk_revision
        or binding.crosswalk_id != expected_governance_id
    ):
        raise CrosswalkGovernanceLineageError(
            "exact_crosswalk_binding_unavailable"
        )
    governance = runtime.service.get_current(
        context=runtime.context,
        lineage=runtime.lineage,
        governance_id=expected_governance_id,
    )
    if governance.revision != binding.crosswalk_revision:
        raise CrosswalkGovernanceLineageError(
            "crosswalk_binding_revision_stale"
        )
    return source, binding, governance


def _safe_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if (
        isinstance(exc, CrosswalkGovernanceLineageError)
        and exc.reason_code == "exact_crosswalk_binding_unavailable"
    ):
        # Optional bureau metadata must remain non-blocking when no exact
        # binding/crosswalk has ever been linked. Stale or contradictory
        # lineage continues to fail closed as a 409 below.
        return HTTPException(
            status_code=404,
            detail={
                "code": "bureau_crosswalk_exact_resource_unavailable",
                "message": "No exact governed bureau metadata annotation set is available.",
            },
        )
    if isinstance(
        exc,
        (
            CrosswalkGovernanceAccessDeniedError,
            CatalogBindingAccessDeniedError,
            BureauCatalogAccessDeniedError,
        ),
    ):
        return HTTPException(
            status_code=403,
            detail={
                "code": "bureau_crosswalk_access_denied",
                "message": "Bureau crosswalk access is not authorized.",
            },
        )
    if isinstance(
        exc,
        (
            CrosswalkGovernanceNotFoundError,
            CatalogBindingNotFoundError,
            CatalogRegistryNotFoundError,
            BureauCatalogLookupError,
        ),
    ):
        return HTTPException(
            status_code=404,
            detail={
                "code": "bureau_crosswalk_exact_resource_unavailable",
                "message": "The exact governed bureau crosswalk is unavailable.",
            },
        )
    if isinstance(
        exc,
        (
            CrosswalkGovernanceConflictError,
            CrosswalkGovernanceLineageError,
            CrosswalkGovernanceStateError,
            CrosswalkGovernanceRepositoryStateError,
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
                "code": "bureau_crosswalk_state_conflict",
                "message": "The exact crosswalk authority changed or is contradictory.",
            },
        )
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=400,
            detail={
                "code": "bureau_crosswalk_request_invalid",
                "message": "The governed crosswalk request is invalid.",
            },
        )
    if isinstance(
        exc,
        (
            CrosswalkGovernanceRepositoryError,
            CatalogBindingRepositoryError,
            CatalogRegistryError,
            CatalogOperationalError,
            RestrictedStorageError,
        ),
    ):
        return HTTPException(
            status_code=503,
            detail={
                "code": "bureau_crosswalk_service_unavailable",
                "message": "The governed bureau crosswalk service is unavailable.",
            },
        )
    return HTTPException(
        status_code=503,
        detail={
            "code": "bureau_crosswalk_service_unavailable",
            "message": "The governed bureau crosswalk service is unavailable.",
        },
    )


_BASE = (
    "/projects/{project_id}/datasets/{dataset_id}/versions/{dataset_version_id}"
    "/bureau-metadata/crosswalk"
)


@router.get(_BASE + "/preview")
def preview_crosswalk(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    _user: Dict[str, Any] = Depends(require_user),
    runtime: CrosswalkRouterRuntime = Depends(get_crosswalk_router_runtime),
) -> Mapping[str, Any]:
    try:
        source = _rebuild_source(runtime)
        defaults = _default_decisions(source)
    except Exception as exc:
        raise _safe_http_error(exc) from exc
    return {
        "ok": True,
        "persisted": False,
        "source": source.model_dump(mode="json"),
        "initial_decisions": [item.model_dump(mode="json") for item in defaults],
        "summary": {
            "authorized_predictor_count": len(defaults),
            "candidate_count": len(source.mappings),
            "authoritative_mapping_count": 0,
            "all_initial_mappings_review_required_or_unresolved": True,
            **_nonmutation_payload(),
        },
    }


@router.get(_BASE + "/current")
def get_current_crosswalk(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    _user: Dict[str, Any] = Depends(require_user),
    runtime: CrosswalkRouterRuntime = Depends(get_crosswalk_router_runtime),
) -> Mapping[str, Any]:
    try:
        source = _rebuild_source(runtime)
        record = runtime.service.get_current(
            context=runtime.context,
            lineage=runtime.lineage,
            governance_id=_governance_id(runtime, source),
        )
    except Exception as exc:
        raise _safe_http_error(exc) from exc
    return {"ok": True, **_governance_envelope(record, binding_linked=False)}


@router.get(_BASE + "/history")
def get_crosswalk_history(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    limit: int = Query(default=25, ge=1, le=_MAX_HISTORY_LIMIT),
    _user: Dict[str, Any] = Depends(require_user),
    runtime: CrosswalkRouterRuntime = Depends(get_crosswalk_router_runtime),
) -> Mapping[str, Any]:
    try:
        source = _rebuild_source(runtime)
        history = runtime.service.history(
            context=runtime.context,
            lineage=runtime.lineage,
            governance_id=_governance_id(runtime, source),
        )
    except Exception as exc:
        raise _safe_http_error(exc) from exc
    selected = history[-limit:]
    return {
        "ok": True,
        "lineage": runtime.lineage.model_dump(mode="json"),
        "returned": len(selected),
        "total_revisions": len(history),
        "revisions": [record.model_dump(mode="json") for record in selected],
    }


@router.post(_BASE + "/decisions")
def revise_crosswalk_decisions(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    payload: CrosswalkDecisionRevisionRequest,
    _user: Dict[str, Any] = Depends(require_user),
    runtime: CrosswalkRouterRuntime = Depends(get_crosswalk_router_runtime),
) -> Any:
    try:
        source = _rebuild_source(runtime)
        governance_id_value = _governance_id(runtime, source)
        decisions = _merge_decisions(
            runtime, source, governance_id_value, payload
        )
        # The service's registration path validates candidate support.  Reuse
        # that validation for revisions too, because revise intentionally
        # validates lifecycle rather than reloading candidate evidence.
        runtime.service._validate_source_identity(source, runtime.lineage, decisions)
        audit = _audit(runtime, payload.analyst_reason)
        if payload.expected_crosswalk_revision == 0:
            persisted = runtime.service.register_candidate(
                context=runtime.context,
                source=source,
                lineage=runtime.lineage,
                decisions=decisions,
                audit=audit,
            )
        else:
            persisted = runtime.service.revise(
                context=runtime.context,
                lineage=runtime.lineage,
                governance_id=governance_id_value,
                expected_revision=payload.expected_crosswalk_revision,
                decisions=decisions,
                audit=audit,
                confirm=payload.confirm_crosswalk,
            )
    except Exception as exc:
        raise _safe_http_error(exc) from exc

    try:
        linked, idempotent = _link_exact_governance(
            runtime,
            persisted,
            expected_binding_revision=payload.expected_binding_revision,
        )
    except Exception as exc:
        safe = _safe_http_error(exc)
        return JSONResponse(
            status_code=safe.status_code,
            content={
                "ok": False,
                "partial_metadata_state": True,
                "governance_persisted": True,
                "binding_linked": False,
                "governance_id": persisted.governance_id,
                "crosswalk_revision": persisted.revision,
                "crosswalk_revision_checksum": persisted.revision_checksum,
                "error": safe.detail,
                **_nonmutation_payload(),
            },
        )
    try:
        documentation = _record_exact_documentation(
            runtime, binding=linked, governance=persisted
        )
    except Exception as exc:
        safe = _safe_http_error(exc)
        return JSONResponse(
            status_code=safe.status_code,
            content={
                "ok": False,
                "partial_metadata_state": True,
                "governance_persisted": True,
                "binding_linked": True,
                "documentation_persisted": False,
                "governance_id": persisted.governance_id,
                "crosswalk_revision": persisted.revision,
                "crosswalk_revision_checksum": persisted.revision_checksum,
                "binding_id": linked.binding_id,
                "binding_revision": linked.revision,
                "error": safe.detail,
                **_nonmutation_payload(),
            },
        )
    return {
        "ok": True,
        "partial_metadata_state": False,
        "documentation_persisted": True,
        "documentation": dict(documentation),
        **_governance_envelope(
            persisted,
            binding=linked,
            binding_linked=True,
            idempotent_link=idempotent,
        ),
    }


@router.post(_BASE + "/binding-link")
def retry_crosswalk_binding_link(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    payload: CrosswalkBindingLinkRequest,
    _user: Dict[str, Any] = Depends(require_user),
    runtime: CrosswalkRouterRuntime = Depends(get_crosswalk_router_runtime),
) -> Mapping[str, Any]:
    try:
        source = _rebuild_source(runtime)
        governance_id_value = _governance_id(runtime, source)
        governance = runtime.service.get_current(
            context=runtime.context,
            lineage=runtime.lineage,
            governance_id=governance_id_value,
        )
        if governance.revision != payload.crosswalk_revision:
            raise CrosswalkGovernanceConflictError(
                expected_revision=payload.crosswalk_revision,
                current_revision=governance.revision,
            )
        linked, idempotent = _link_exact_governance(
            runtime,
            governance,
            expected_binding_revision=payload.expected_binding_revision,
        )
        documentation = _record_exact_documentation(
            runtime, binding=linked, governance=governance
        )
    except Exception as exc:
        safe = _safe_http_error(exc)
        # If the exact binding already points at this governance revision,
        # evidence/MDD persistence is the only incomplete metadata operation.
        if "linked" in locals():
            return JSONResponse(
                status_code=safe.status_code,
                content={
                    "ok": False,
                    "partial_metadata_state": True,
                    "governance_persisted": True,
                    "binding_linked": True,
                    "documentation_persisted": False,
                    "governance_id": governance.governance_id,
                    "crosswalk_revision": governance.revision,
                    "binding_id": linked.binding_id,
                    "binding_revision": linked.revision,
                    "error": safe.detail,
                    **_nonmutation_payload(),
                },
            )
        raise safe from exc
    return {
        "ok": True,
        "partial_metadata_state": False,
        "documentation_persisted": True,
        "documentation": dict(documentation),
        **_governance_envelope(
            governance,
            binding=linked,
            binding_linked=True,
            idempotent_link=idempotent,
        ),
    }


@router.get(_BASE + "/semantic-annotations")
@router.get(
    "/projects/{project_id}/datasets/{dataset_id}/versions/{dataset_version_id}"
    "/bureau-metadata/annotations"
)
def get_semantic_annotations(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    _user: Dict[str, Any] = Depends(require_user),
    runtime: CrosswalkRouterRuntime = Depends(get_crosswalk_router_runtime),
) -> Mapping[str, Any]:
    try:
        return build_exact_semantic_handoff(runtime)
    except Exception as exc:
        raise _safe_http_error(exc) from exc


def build_exact_semantic_handoff(
    runtime: CrosswalkRouterRuntime,
) -> Mapping[str, Any]:
    """Build the reusable exact annotation envelope for EDA and DA consumers."""

    _source, binding, governance = _resolve_exact_bound_governance(runtime)
    accepted = tuple(
        decision for decision in governance.decisions if decision.analyst_confirmed
    )
    provider_semantics = _bounded_provider_semantics(
        runtime,
        binding=binding,
        accepted=accepted,
    )
    annotations = []
    for decision in accepted:
        semantics = provider_semantics.get(str(decision.candidate_attribute_code or ""))
        attribute = semantics[0] if semantics else None
        annotations.append(
            build_bureau_semantic_annotation(
                binding=binding,
                decision=decision,
                binding_current=True,
                entitlement_verified=True,
                description=(
                    str(attribute.get("description") or "")[:1_024]
                    if attribute
                    else None
                ),
                data_type=(
                    str(attribute.get("numeric_type") or "") if attribute else None
                ),
                units=(attribute.get("units") if attribute else None),
                attribute_definition_checksum=(
                    str(attribute.get("record_checksum") or "") if attribute else None
                ),
                ordinary_range=(semantics[1] if semantics else None),
                special_definitions=(semantics[2] if semantics else ()),
            )
        )
    annotations_tuple = tuple(annotations)
    set_payload = {
        "project_id": runtime.lineage.project_id,
        "dataset_id": runtime.lineage.dataset_id,
        "dataset_version_id": runtime.lineage.dataset_version_id,
        "schema_checksum": runtime.lineage.schema_checksum,
        "catalog_version_id": binding.identity.catalog_version_id,
        "catalog_key": binding.identity.catalog_key.model_dump(mode="json"),
        "catalog_checksum": binding.identity.catalog_checksum,
        "binding_id": binding.binding_id,
        "binding_revision": binding.revision,
        "binding_revision_checksum": binding.revision_checksum,
        "crosswalk_id": governance.governance_id,
        "crosswalk_revision": governance.revision,
        "crosswalk_revision_checksum": governance.revision_checksum,
        "accepted_annotation_count": len(annotations_tuple),
        "annotation_checksums": [
            annotation.annotation_id for annotation in annotations_tuple
        ],
        "source": "exact_current_binding_and_accepted_crosswalk_decisions",
        **_nonmutation_payload(),
    }
    set_checksum = _sha256(set_payload)
    annotation_set = {
        key: value for key, value in set_payload.items() if key != "annotation_checksums"
    }
    annotation_set["annotation_set_id"] = "bsas_" + set_checksum[:32]
    annotation_set["annotation_set_checksum"] = set_checksum
    return {
        "ok": True,
        "annotation_set": annotation_set,
        "annotations": [
            annotation.model_dump(mode="json") for annotation in annotations_tuple
        ],
    }


@router.get(_BASE + "/consistency")
def get_catalog_consistency(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    _user: Dict[str, Any] = Depends(require_user),
    runtime: CrosswalkRouterRuntime = Depends(get_crosswalk_router_runtime),
) -> Mapping[str, Any]:
    """Reconcile exact accepted mappings with authoritative structural summaries."""

    try:
        _source, binding, governance = _resolve_exact_bound_governance(runtime)
        eligible = tuple(
            decision
            for decision in governance.decisions
            if decision.analyst_confirmed
            and decision.mapping_state in {"exact_verified", "approved_alias"}
        )
        provider_semantics = _bounded_provider_semantics(
            runtime,
            binding=binding,
            accepted=eligible,
        )
        observed = (
            runtime.observed_summary_provider(runtime)
            if runtime.observed_summary_provider is not None
            else _backend_authoritative_observed_summaries(runtime)
        )
        results = []
        for decision in governance.decisions:
            semantics = provider_semantics.get(
                str(decision.candidate_attribute_code or "")
            )
            provider_attribute = semantics[0] if semantics else None
            result = reconcile_catalog_consistency(
                decision=decision,
                provider_attribute=provider_attribute,
                observed_summary=observed.get(decision.dataset_field),
            )
            results.append(result)
        priority = {
            "contradictory": 6,
            "metadata_unavailable": 5,
            "review_required": 4,
            "mapping_unresolved": 3,
            "consistent_with_observed_unused_codes": 2,
            "consistent": 1,
        }
        overall = max(
            (result.consistency_state for result in results),
            key=lambda state: priority[state],
            default="mapping_unresolved",
        )
        counts = {
            state: sum(result.consistency_state == state for result in results)
            for state in priority
        }
        identity_payload = {
            "project_id": runtime.lineage.project_id,
            "dataset_id": runtime.lineage.dataset_id,
            "dataset_version_id": runtime.lineage.dataset_version_id,
            "schema_checksum": runtime.lineage.schema_checksum,
            "catalog_version_id": binding.identity.catalog_version_id,
            "catalog_checksum": binding.identity.catalog_checksum,
            "binding_id": binding.binding_id,
            "binding_revision": binding.revision,
            "crosswalk_id": governance.governance_id,
            "crosswalk_revision": governance.revision,
            "result_checksums": [
                _sha256(result.model_dump(mode="json")) for result in results
            ],
        }
        reconciliation_checksum = _sha256(identity_payload)
    except Exception as exc:
        raise _safe_http_error(exc) from exc
    return {
        "ok": True,
        "identity": {
            "project_id": runtime.lineage.project_id,
            "dataset_id": runtime.lineage.dataset_id,
            "dataset_version_id": runtime.lineage.dataset_version_id,
            "activation_revision": runtime.lineage.activation_revision,
            "schema_checksum": runtime.lineage.schema_checksum,
            "catalog_version_id": binding.identity.catalog_version_id,
            "catalog_key": binding.identity.catalog_key.model_dump(mode="json"),
            "catalog_checksum": binding.identity.catalog_checksum,
            "binding_id": binding.binding_id,
            "binding_revision": binding.revision,
            "binding_revision_checksum": binding.revision_checksum,
            "crosswalk_id": governance.governance_id,
            "crosswalk_revision": governance.revision,
            "crosswalk_revision_checksum": governance.revision_checksum,
        },
        "overall_consistency_state": overall,
        "summary": {
            "field_count": len(results),
            "counts": counts,
            "recommendations_blocked": any(
                result.recommendations_blocked for result in results
            ),
            "contradictory_recommendations_blocked": counts["contradictory"] > 0,
            "source": "backend_authoritative_schema_and_value_summaries",
            "raw_rows_accessed": False,
            "browser_preview_used": False,
            "final_holdout_accessed": False,
            **_nonmutation_payload(),
        },
        "reconciliation_id": "bcr_" + reconciliation_checksum[:32],
        "reconciliation_checksum": reconciliation_checksum,
        "results": [result.model_dump(mode="json") for result in results],
    }


def resolve_exact_semantic_handoff_for_user(
    *,
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    user: Mapping[str, Any],
    operational: OperationalCatalogService | None = None,
) -> Mapping[str, Any]:
    """Public server-side resolver for EDA and other trusted consumers.

    Domain failures are intentionally converted to the same safe 403/404/409/
    503 HTTP contract as the canonical annotation route.
    """

    try:
        runtime = _build_runtime(
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
            user=user,
            operational=operational or get_operational_catalog_service(),
        )
        return build_exact_semantic_handoff(runtime)
    except Exception as exc:
        raise _safe_http_error(exc) from exc


__all__ = [
    "CrosswalkBindingLinkRequest",
    "CrosswalkDecisionRevisionRequest",
    "CrosswalkRouterRuntime",
    "MappingDecisionRequest",
    "build_exact_semantic_handoff",
    "get_crosswalk_router_runtime",
    "resolve_exact_semantic_handoff_for_user",
    "router",
]

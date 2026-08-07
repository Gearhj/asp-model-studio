from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
from typing import get_args

import pytest
from pydantic import ValidationError

from server.bureau_metadata.catalog_service import BureauCatalogAccessDeniedError
from server.bureau_metadata.crosswalk_governance import (
    CrosswalkAuditLabel,
    CrosswalkAuditMetadata,
    CrosswalkEvidenceReference,
    CrosswalkLineage,
    GovernedMappingDecision,
    MappingGovernanceState,
)
from server.bureau_metadata.crosswalk_governance_repository import (
    CrosswalkGovernanceConflictError,
    CrosswalkGovernanceNotFoundError,
    InMemoryGovernedCrosswalkRepository,
)
from server.bureau_metadata.crosswalk_governance_service import (
    CrosswalkGovernanceAccessDeniedError,
    CrosswalkGovernanceLineageError,
    CrosswalkGovernanceStateError,
    GovernedCrosswalkService,
)
from server.bureau_metadata.types import (
    BureauAttributeMatchCandidate,
    BureauCatalogAccessContext,
    BureauCatalogAccessGrant,
    BureauCatalogKey,
    BureauDatasetCrosswalk,
)


CATALOG_CHECKSUM = "a" * 64
SCHEMA_CHECKSUM = "b" * 64
SOURCE_CHECKSUM = "c" * 64
EVIDENCE_CHECKSUM = "d" * 64
NOW = "2026-08-05T12:00:00Z"


def catalog_key() -> BureauCatalogKey:
    return BureauCatalogKey(
        provider="Synthetic Bureau",
        product="Synthetic Product",
        edition="Test",
        dictionary_version="1.0",
    )


def lineage(**updates: object) -> CrosswalkLineage:
    payload: dict[str, object] = {
        "project_id": "project-synthetic-1",
        "dataset_id": "dataset-synthetic-1",
        "dataset_version_id": "version-synthetic-1",
        "activation_revision": 7,
        "target_contract_id": "target-contract-1",
        "predictor_authorization_id": "predictor-authorization-1",
        "schema_checksum": SCHEMA_CHECKSUM,
        "catalog_key": catalog_key(),
        "catalog_checksum": CATALOG_CHECKSUM,
    }
    payload.update(updates)
    return CrosswalkLineage.model_validate(payload)


def context(*, project_id: str = "project-synthetic-1") -> BureauCatalogAccessContext:
    return BureauCatalogAccessContext(
        principal_id="analyst-synthetic-1",
        tenant_id="tenant-synthetic-1",
        project_id=project_id,
    )


def evidence(kind: str, suffix: str | None = None) -> CrosswalkEvidenceReference:
    resolved_suffix = suffix or kind
    return CrosswalkEvidenceReference(
        evidence_id=f"evidence-{resolved_suffix}",
        evidence_kind=kind,
        authority_id=f"authority-{resolved_suffix}",
        checksum=EVIDENCE_CHECKSUM,
        created_by="analyst-synthetic-1",
        created_at=NOW,
    )


def exact_decision() -> GovernedMappingDecision:
    return GovernedMappingDecision(
        dataset_field="bureau_score",
        mapping_state="exact_verified",
        candidate_attribute_code="ATTR_001",
        evidence=(
            evidence("catalog_definition"),
            evidence("exact_match"),
            evidence("analyst_review"),
        ),
        analyst_confirmed=True,
        rationale="Exact code and definition were independently reviewed.",
        reviewer_id="analyst-synthetic-1",
    )


def rejected_decision() -> GovernedMappingDecision:
    return GovernedMappingDecision(
        dataset_field="bureau_score",
        mapping_state="rejected",
        candidate_attribute_code="ATTR_001",
        evidence=(evidence("analyst_review", "rejection-review"),),
        analyst_confirmed=True,
        rationale="The local field is known to be semantically incompatible.",
        reviewer_id="analyst-synthetic-1",
    )


def pending_decision() -> GovernedMappingDecision:
    return GovernedMappingDecision(
        dataset_field="bureau_score",
        mapping_state="probable_review_required",
        candidate_attribute_code="ATTR_001",
        evidence=(evidence("semantic_analysis"),),
        analyst_confirmed=False,
    )


def transformed_decision() -> GovernedMappingDecision:
    return GovernedMappingDecision(
        dataset_field="bureau_score",
        mapping_state="transformed_or_derived",
        candidate_attribute_code="ATTR_DERIVED",
        source_attribute_codes=("ATTR_001",),
        evidence=(
            evidence("transformation_lineage"),
            evidence("analyst_review"),
        ),
        analyst_confirmed=True,
        transformation_reference_id="evidence-transformation_lineage",
        transformation_rule="Apply the documented synthetic normalization rule.",
        transformation_or_recoding_concerns=(
            "Confirm synthetic denominator behavior before use.",
        ),
        data_type="decimal",
        units="unitless",
        source_system="synthetic_source",
        timing="Measured during the synthetic observation window.",
        special_value_handling="Preserve documented synthetic sentinels.",
        value_range_reconciliation="Synthetic input and output ranges reconciled.",
        special_value_reconciliation="Synthetic special values reconciled.",
        reviewer_id="analyst-synthetic-1",
        rationale="The documented synthetic derivation was independently reviewed.",
    )


def approved_alias_decision() -> GovernedMappingDecision:
    return GovernedMappingDecision(
        dataset_field="bureau_score",
        mapping_state="approved_alias",
        candidate_attribute_code="ATTR_001",
        evidence=(
            evidence("institutional_alias", "alias-policy-1"),
            evidence("analyst_review"),
        ),
        analyst_confirmed=True,
        alias_authority_id="authority-alias-policy-1",
        institutional_alias_reference="evidence-alias-policy-1",
        reviewer_id="analyst-synthetic-1",
        rationale="The exact synthetic institutional alias was reviewed.",
    )


def audit(reason: str = "Synthetic governance review") -> CrosswalkAuditMetadata:
    return CrosswalkAuditMetadata(
        actor_id="analyst-synthetic-1",
        request_id="request-synthetic-1",
        occurred_at=NOW,
        reason=reason,
        labels=(CrosswalkAuditLabel(key="channel", value="isolated-test"),),
    )


def source_crosswalk(**updates: object) -> BureauDatasetCrosswalk:
    candidate = BureauAttributeMatchCandidate(
        dataset_field="bureau_score",
        catalog_key=catalog_key(),
        catalog_checksum=CATALOG_CHECKSUM,
        candidate_attribute_code="ATTR_001",
        match_status="exact_dictionary_code_match",
        confidence=1.0,
    )
    payload: dict[str, object] = {
        "crosswalk_id": "candidate-crosswalk-1",
        "revision": 1,
        "project_id": "project-synthetic-1",
        "dataset_id": "dataset-synthetic-1",
        "dataset_version_id": "version-synthetic-1",
        "schema_checksum": SCHEMA_CHECKSUM,
        "target_contract_id": "target-contract-1",
        "predictor_authorization_id": "predictor-authorization-1",
        "catalog_key": catalog_key(),
        "catalog_checksum": CATALOG_CHECKSUM,
        "mappings": (candidate,),
        "crosswalk_status": "candidate_only",
        "created_by": "candidate-engine",
        "created_at": NOW,
        "crosswalk_checksum": SOURCE_CHECKSUM,
    }
    payload.update(updates)
    return BureauDatasetCrosswalk.model_validate(payload)


def alias_source_crosswalk(
    *, alias_reference: str = "evidence-alias-policy-1"
) -> BureauDatasetCrosswalk:
    candidate = BureauAttributeMatchCandidate(
        dataset_field="bureau_score",
        catalog_key=catalog_key(),
        catalog_checksum=CATALOG_CHECKSUM,
        candidate_attribute_code="ATTR_001",
        match_status="approved_institutional_alias",
        confidence=1.0,
        institutional_alias_reference=alias_reference,
    )
    return source_crosswalk(mappings=(candidate,))


class ProjectAuthorization:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[tuple[str, str]] = []

    def authorize_project(
        self,
        access_context: BureauCatalogAccessContext,
        project_id: str,
        permission: str,
    ) -> bool:
        del access_context
        self.calls.append((project_id, permission))
        return self.allowed


class Entitlements:
    def __init__(self, *, allowed: bool = True, wrong_checksum: bool = False) -> None:
        self.allowed = allowed
        self.wrong_checksum = wrong_checksum
        self.calls = 0

    def authorize(
        self,
        access_context: BureauCatalogAccessContext,
        requested_key: BureauCatalogKey,
        requested_checksum: str,
        operation: str,
    ) -> BureauCatalogAccessGrant:
        self.calls += 1
        if not self.allowed:
            raise BureauCatalogAccessDeniedError("Synthetic denial")
        return BureauCatalogAccessGrant(
            grant_id="grant-synthetic-1",
            principal_id=access_context.principal_id,
            tenant_id=access_context.tenant_id,
            catalog_key=requested_key,
            catalog_checksum=("f" * 64 if self.wrong_checksum else requested_checksum),
            operation=operation,
            expires_at="2099-01-01T00:00:00Z",
        )


class LineageAuthority:
    def __init__(self, current: CrosswalkLineage) -> None:
        self.current = current
        self.calls = 0

    def current_lineage(
        self,
        access_context: BureauCatalogAccessContext,
        project_id: str,
    ) -> CrosswalkLineage:
        del access_context, project_id
        self.calls += 1
        return self.current


class CountingRepository(InMemoryGovernedCrosswalkRepository):
    def __init__(self) -> None:
        super().__init__()
        self.append_calls = 0
        self.read_calls = 0

    def append(self, record, *, expected_revision):  # type: ignore[no-untyped-def]
        self.append_calls += 1
        return super().append(record, expected_revision=expected_revision)

    def get_current(self, governance_id):  # type: ignore[no-untyped-def]
        self.read_calls += 1
        return super().get_current(governance_id)


def service(
    *,
    repository: InMemoryGovernedCrosswalkRepository | None = None,
    project_authorization: ProjectAuthorization | None = None,
    entitlements: Entitlements | None = None,
    current_lineage: CrosswalkLineage | None = None,
) -> GovernedCrosswalkService:
    return GovernedCrosswalkService(
        repository=repository or InMemoryGovernedCrosswalkRepository(),
        project_authorization=project_authorization or ProjectAuthorization(),
        catalog_entitlements=entitlements or Entitlements(),
        lineage_authority=LineageAuthority(current_lineage or lineage()),
    )


def register(
    governed_service: GovernedCrosswalkService,
    *,
    supplied_lineage: CrosswalkLineage | None = None,
):
    return governed_service.register_candidate(
        context=context(),
        source=source_crosswalk(),
        lineage=supplied_lineage or lineage(),
        decisions=(exact_decision(),),
        audit=audit(),
    )


def test_mapping_state_contract_is_exact_and_has_no_generic_approved_state() -> None:
    assert set(get_args(MappingGovernanceState)) == {
        "exact_verified",
        "approved_alias",
        "transformed_or_derived",
        "probable_review_required",
        "ambiguous_review_required",
        "recoding_evidence_required",
        "unresolved",
        "out_of_catalog",
        "rejected",
    }
    assert "approved" not in get_args(MappingGovernanceState)


@pytest.mark.parametrize(
    ("state", "decision_payload", "message"),
    [
        (
            "exact_verified",
            {
                "candidate_attribute_code": "ATTR_001",
                "evidence": (evidence("analyst_review"),),
                "analyst_confirmed": True,
            },
            "missing required evidence",
        ),
        (
            "approved_alias",
            {
                "candidate_attribute_code": "ATTR_001",
                "evidence": (
                    evidence("institutional_alias"),
                    evidence("analyst_review"),
                ),
                "analyst_confirmed": True,
                "institutional_alias_reference": "evidence-institutional_alias",
                "reviewer_id": "analyst-synthetic-1",
                "rationale": "Synthetic alias review.",
            },
            "alias authority",
        ),
        (
            "transformed_or_derived",
            {
                "candidate_attribute_code": "ATTR_DERIVED",
                "evidence": (
                    evidence("transformation_lineage"),
                    evidence("analyst_review"),
                ),
                "analyst_confirmed": True,
                "source_attribute_codes": ("ATTR_001",),
                "transformation_or_recoding_concerns": (
                    "Synthetic transformation review required.",
                ),
                "data_type": "decimal",
                "units": "unitless",
                "source_system": "synthetic_source",
                "timing": "Synthetic observation window.",
                "special_value_handling": "Preserve documented synthetic sentinels.",
                "value_range_reconciliation": "Synthetic ranges reconciled.",
                "special_value_reconciliation": "Synthetic special values reconciled.",
                "reviewer_id": "analyst-synthetic-1",
                "rationale": "Synthetic derived mapping review.",
            },
            "documented transformation rule or reference",
        ),
    ],
)
def test_evidence_complete_states_fail_closed(
    state: str,
    decision_payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        GovernedMappingDecision.model_validate(
            {
                "dataset_field": "bureau_score",
                "mapping_state": state,
                **decision_payload,
            }
        )


def test_review_states_cannot_claim_analyst_confirmation() -> None:
    with pytest.raises(ValidationError, match="analyst_confirmed must be false"):
        GovernedMappingDecision(
            dataset_field="bureau_score",
            mapping_state="probable_review_required",
            candidate_attribute_code="ATTR_001",
            evidence=(evidence("semantic_analysis"),),
            analyst_confirmed=True,
        )


def test_transformed_decision_carries_complete_bounded_operational_contract() -> None:
    decision = transformed_decision()
    record = service().register_candidate(
        context=context(),
        source=source_crosswalk(),
        lineage=lineage(),
        decisions=(decision,),
        audit=audit("Register synthetic governed transformation"),
    )

    assert decision.source_attribute_codes == ("ATTR_001",)
    assert decision.units == "unitless"
    assert decision.transformation_reference_id == "evidence-transformation_lineage"
    assert decision.reviewer_id == "analyst-synthetic-1"
    assert decision.value_range_reconciliation
    assert decision.special_value_reconciliation
    assert record.decisions == (decision,)


@pytest.mark.parametrize(
    "missing_field",
    [
        "data_type",
        "units",
        "source_system",
        "timing",
        "special_value_handling",
        "value_range_reconciliation",
        "special_value_reconciliation",
    ],
)
def test_transformed_decision_fails_closed_when_operational_field_is_missing(
    missing_field: str,
) -> None:
    payload = transformed_decision().model_dump(mode="json")
    payload[missing_field] = None

    with pytest.raises(ValidationError, match=missing_field):
        GovernedMappingDecision.model_validate(payload)


def test_transformed_decision_requires_sources_rule_concerns_and_reviewer() -> None:
    payload = transformed_decision().model_dump(mode="json")
    payload["source_attribute_codes"] = ()
    with pytest.raises(ValidationError, match="source attribute code"):
        GovernedMappingDecision.model_validate(payload)

    payload = transformed_decision().model_dump(mode="json")
    payload["transformation_reference_id"] = None
    payload["transformation_rule"] = None
    with pytest.raises(ValidationError, match="rule or reference"):
        GovernedMappingDecision.model_validate(payload)

    payload = transformed_decision().model_dump(mode="json")
    payload["transformation_or_recoding_concerns"] = ()
    with pytest.raises(ValidationError, match="transformation or recoding concerns"):
        GovernedMappingDecision.model_validate(payload)

    payload = transformed_decision().model_dump(mode="json")
    payload["reviewer_id"] = None
    with pytest.raises(ValidationError, match="reviewer_id"):
        GovernedMappingDecision.model_validate(payload)


def test_transformation_reference_must_match_exact_evidence() -> None:
    payload = transformed_decision().model_dump(mode="json")
    payload["transformation_reference_id"] = "different-transformation-evidence"

    with pytest.raises(ValidationError, match="must match transformation lineage"):
        GovernedMappingDecision.model_validate(payload)


def test_transformation_sources_must_exist_in_candidate_crosswalk() -> None:
    payload = transformed_decision().model_dump(mode="json")
    payload["source_attribute_codes"] = ("ATTR_NOT_IN_SOURCE",)
    unsupported = GovernedMappingDecision.model_validate(payload)

    with pytest.raises(CrosswalkGovernanceStateError, match="source evidence"):
        service().register_candidate(
            context=context(),
            source=source_crosswalk(),
            lineage=lineage(),
            decisions=(unsupported,),
            audit=audit("Reject unsupported synthetic transform source"),
        )


def test_recoding_evidence_required_preserves_bounded_concern() -> None:
    with pytest.raises(ValidationError, match="recoding concerns"):
        GovernedMappingDecision(
            dataset_field="bureau_score",
            mapping_state="recoding_evidence_required",
            candidate_attribute_code="ATTR_001",
            evidence=(evidence("recoding_observation"),),
            analyst_confirmed=False,
        )

    decision = GovernedMappingDecision(
        dataset_field="bureau_score",
        mapping_state="recoding_evidence_required",
        candidate_attribute_code="ATTR_001",
        evidence=(evidence("recoding_observation"),),
        analyst_confirmed=False,
        transformation_or_recoding_concerns=(
            "Synthetic negative code lacks a durable source-to-model crosswalk.",
        ),
    )
    assert decision.transformation_or_recoding_concerns


def test_confirmable_decisions_require_reviewer_rationale_and_review_evidence() -> None:
    payload = exact_decision().model_dump(mode="json")
    payload["reviewer_id"] = None
    with pytest.raises(ValidationError, match="reviewer_id"):
        GovernedMappingDecision.model_validate(payload)

    payload = exact_decision().model_dump(mode="json")
    payload["rationale"] = None
    with pytest.raises(ValidationError, match="analyst rationale"):
        GovernedMappingDecision.model_validate(payload)

    payload = exact_decision().model_dump(mode="json")
    payload["reviewer_id"] = "different-reviewer"
    with pytest.raises(ValidationError, match="reviewer_id must match"):
        GovernedMappingDecision.model_validate(payload)


def test_approved_alias_pins_evidence_and_exact_source_alias_reference() -> None:
    decision = approved_alias_decision()
    governed_service = service()
    record = governed_service.register_candidate(
        context=context(),
        source=alias_source_crosswalk(),
        lineage=lineage(),
        decisions=(decision,),
        audit=audit("Approve exact synthetic alias"),
    )
    assert record.decisions[0].institutional_alias_reference == (
        "evidence-alias-policy-1"
    )

    with pytest.raises(CrosswalkGovernanceStateError, match="exact source alias"):
        service().register_candidate(
            context=context(),
            source=alias_source_crosswalk(
                alias_reference="different-source-alias-policy"
            ),
            lineage=lineage(),
            decisions=(decision,),
            audit=audit("Reject mismatched synthetic alias"),
        )

    payload = decision.model_dump(mode="json")
    payload["institutional_alias_reference"] = "different-alias-evidence"
    with pytest.raises(ValidationError, match="matching institutional alias evidence"):
        GovernedMappingDecision.model_validate(payload)


def test_operational_decision_fields_are_bounded() -> None:
    payload = transformed_decision().model_dump(mode="json")
    payload["source_attribute_codes"] = tuple(
        f"ATTR_{index:03d}" for index in range(33)
    )
    with pytest.raises(ValidationError, match="At most 32 source"):
        GovernedMappingDecision.model_validate(payload)

    payload = transformed_decision().model_dump(mode="json")
    payload["transformation_or_recoding_concerns"] = ("x" * 513,)
    with pytest.raises(ValidationError, match="512-character"):
        GovernedMappingDecision.model_validate(payload)

    payload = transformed_decision().model_dump(mode="json")
    payload["special_value_handling"] = "x" * 1025
    with pytest.raises(ValidationError, match="1024-character"):
        GovernedMappingDecision.model_validate(payload)


def test_registration_is_draft_candidate_only_and_nonmutating() -> None:
    original_dataset = {"bureau_score": [1, 2, 3]}
    original_predictor_authority = {"authorized": ["bureau_score"]}
    dataset_before = copy.deepcopy(original_dataset)
    predictor_before = copy.deepcopy(original_predictor_authority)

    record = register(service())

    assert record.lifecycle_state == "draft"
    assert record.revision == 1
    assert record.source_candidate_only is True
    assert record.dataset_mutated is False
    assert record.predictor_authorization_mutated is False
    assert original_dataset == dataset_before
    assert original_predictor_authority == predictor_before


def test_optimistic_concurrency_is_atomic_under_competing_writers() -> None:
    repository = InMemoryGovernedCrosswalkRepository()
    governed_service = service(repository=repository)
    first = register(governed_service)

    def revise(reason: str):
        return governed_service.revise(
            context=context(),
            lineage=lineage(),
            governance_id=first.governance_id,
            expected_revision=1,
            decisions=(rejected_decision(),),
            audit=audit(reason),
            confirm=True,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(revise, f"Synthetic concurrent review {index}") for index in range(2)]
    results: list[object] = []
    errors: list[BaseException] = []
    for future in futures:
        try:
            results.append(future.result())
        except BaseException as exc:  # noqa: BLE001 - asserted below
            errors.append(exc)

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], CrosswalkGovernanceConflictError)
    assert repository.get_current(first.governance_id).revision == 2
    assert len(repository.history(first.governance_id)) == 2


def test_rejected_state_remains_in_append_only_history_after_later_revision() -> None:
    repository = InMemoryGovernedCrosswalkRepository()
    governed_service = service(repository=repository)
    first = register(governed_service)
    rejected = governed_service.revise(
        context=context(),
        lineage=lineage(),
        governance_id=first.governance_id,
        expected_revision=1,
        decisions=(rejected_decision(),),
        audit=audit("Reject synthetic candidate"),
        confirm=True,
    )
    governed_service.revise(
        context=context(),
        lineage=lineage(),
        governance_id=first.governance_id,
        expected_revision=2,
        decisions=(exact_decision(),),
        audit=audit("Reconsider with independent evidence"),
        confirm=True,
    )

    history = governed_service.history(
        context=context(),
        lineage=lineage(),
        governance_id=first.governance_id,
    )
    assert [record.revision for record in history] == [1, 2, 3]
    assert history[1] == rejected
    assert history[1].decisions[0].mapping_state == "rejected"
    assert history[1].revision_checksum != history[2].revision_checksum


@pytest.mark.parametrize(
    "authority_lineage",
    [
        lineage(dataset_version_id="version-synthetic-2"),
        lineage(activation_revision=8),
        lineage(predictor_authorization_id="predictor-authorization-2"),
        lineage(schema_checksum="e" * 64),
    ],
)
def test_stale_dataset_lineage_rejected_before_repository_write(
    authority_lineage: CrosswalkLineage,
) -> None:
    repository = CountingRepository()
    governed_service = service(
        repository=repository,
        current_lineage=authority_lineage,
    )

    with pytest.raises(CrosswalkGovernanceLineageError) as caught:
        register(governed_service)

    assert caught.value.reason_code == "dataset_lineage_stale"
    assert repository.append_calls == 0


@pytest.mark.parametrize(
    "authority_lineage",
    [
        lineage(catalog_checksum="e" * 64),
        lineage(
            catalog_key=BureauCatalogKey(
                provider="Synthetic Bureau",
                product="Synthetic Product",
                edition="Test",
                dictionary_version="2.0",
            )
        ),
    ],
)
def test_stale_catalog_lineage_rejected_before_repository_write(
    authority_lineage: CrosswalkLineage,
) -> None:
    repository = CountingRepository()
    governed_service = service(
        repository=repository,
        current_lineage=authority_lineage,
    )

    with pytest.raises(CrosswalkGovernanceLineageError) as caught:
        register(governed_service)

    assert caught.value.reason_code == "catalog_lineage_stale"
    assert repository.append_calls == 0


def test_project_authorization_denial_precedes_entitlement_and_repository_access() -> None:
    repository = CountingRepository()
    denied_project = ProjectAuthorization(allowed=False)
    entitlements = Entitlements()
    governed_service = service(
        repository=repository,
        project_authorization=denied_project,
        entitlements=entitlements,
    )

    with pytest.raises(CrosswalkGovernanceAccessDeniedError):
        register(governed_service)

    assert entitlements.calls == 0
    assert repository.append_calls == 0
    assert repository.read_calls == 0


@pytest.mark.parametrize(
    "entitlements",
    [Entitlements(allowed=False), Entitlements(wrong_checksum=True)],
)
def test_exact_catalog_entitlement_is_required_before_repository_access(
    entitlements: Entitlements,
) -> None:
    repository = CountingRepository()
    governed_service = service(repository=repository, entitlements=entitlements)

    with pytest.raises(CrosswalkGovernanceAccessDeniedError):
        register(governed_service)

    assert repository.append_calls == 0
    assert repository.read_calls == 0


def test_audit_metadata_is_bounded_flat_and_secret_safe() -> None:
    with pytest.raises(ValidationError, match="Sensitive audit label keys"):
        CrosswalkAuditLabel(key="access_token", value="redacted")
    with pytest.raises(ValidationError, match="256-character"):
        CrosswalkAuditLabel(key="detail", value="x" * 257)
    with pytest.raises(ValidationError, match="limited to 16"):
        CrosswalkAuditMetadata(
            actor_id="analyst-synthetic-1",
            request_id="request-synthetic-1",
            occurred_at=NOW,
            reason="Bounded test",
            labels=tuple(
                CrosswalkAuditLabel(key=f"label_{index:02d}", value="safe")
                for index in range(17)
            ),
        )


def test_confirmation_with_review_required_state_fails_closed_without_append() -> None:
    repository = CountingRepository()
    governed_service = service(repository=repository)
    first = register(governed_service)
    append_count = repository.append_calls

    with pytest.raises(CrosswalkGovernanceStateError, match="terminal decisions"):
        governed_service.revise(
            context=context(),
            lineage=lineage(),
            governance_id=first.governance_id,
            expected_revision=1,
            decisions=(pending_decision(),),
            audit=audit("Pending semantic review"),
            confirm=True,
        )

    assert repository.append_calls == append_count
    assert repository.get_current(first.governance_id).revision == 1


def test_revision_cannot_silently_add_or_remove_governed_fields() -> None:
    repository = CountingRepository()
    governed_service = service(repository=repository)
    first = register(governed_service)
    added_field = exact_decision().model_copy(update={"dataset_field": "other_score"})
    append_count = repository.append_calls

    with pytest.raises(CrosswalkGovernanceStateError, match="field inventory"):
        governed_service.revise(
            context=context(),
            lineage=lineage(),
            governance_id=first.governance_id,
            expected_revision=1,
            decisions=(exact_decision(), added_field),
            audit=audit("Attempt field inventory expansion"),
        )

    assert repository.append_calls == append_count


def test_source_and_current_lineage_must_match_exactly() -> None:
    governed_service = service()
    mismatched_source = source_crosswalk(dataset_version_id="version-synthetic-2")

    with pytest.raises(CrosswalkGovernanceLineageError) as caught:
        governed_service.register_candidate(
            context=context(),
            source=mismatched_source,
            lineage=lineage(),
            decisions=(exact_decision(),),
            audit=audit(),
        )

    assert caught.value.reason_code == "source_lineage_mismatch"


def test_repository_exact_revision_lookup_has_no_latest_or_first_fallback() -> None:
    repository = InMemoryGovernedCrosswalkRepository()
    record = register(service(repository=repository))

    with pytest.raises(CrosswalkGovernanceNotFoundError):
        repository.get_revision(record.governance_id, 2)
    with pytest.raises(CrosswalkGovernanceNotFoundError):
        repository.get_revision("missing-governance-id", 1)


def test_historical_read_remains_authorization_and_entitlement_gated() -> None:
    repository = InMemoryGovernedCrosswalkRepository()
    allowed_service = service(repository=repository)
    record = register(allowed_service)

    denied_service = service(
        repository=repository,
        project_authorization=ProjectAuthorization(allowed=False),
    )
    with pytest.raises(CrosswalkGovernanceAccessDeniedError):
        denied_service.history(
            context=context(),
            lineage=lineage(),
            governance_id=record.governance_id,
        )


def test_audit_actor_cannot_be_spoofed() -> None:
    spoofed = audit().model_copy(update={"actor_id": "different-analyst"})
    with pytest.raises(CrosswalkGovernanceStateError, match="authenticated principal"):
        service().register_candidate(
            context=context(),
            source=source_crosswalk(),
            lineage=lineage(),
            decisions=(exact_decision(),),
            audit=spoofed,
        )

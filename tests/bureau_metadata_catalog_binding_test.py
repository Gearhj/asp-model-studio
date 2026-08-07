from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Barrier
import tempfile

import pytest
from pydantic import ValidationError

import server.bureau_metadata.catalog_binding_repository as repository_module
from server.bureau_metadata.catalog_binding import (
    CatalogBindingEvidenceReference,
    DatasetCatalogBindingRevision,
    DatasetVersionCatalogIdentity,
    build_catalog_binding_revision,
    catalog_binding_scope_identity,
    dataset_catalog_binding_scope,
)
from server.bureau_metadata.catalog_binding_repository import (
    CatalogBindingConflictError,
    CatalogBindingNotFoundError,
    CatalogBindingRepositoryStateError,
    SQLiteCatalogBindingRepository,
)
from server.bureau_metadata.catalog_binding_service import (
    CatalogBindingAccessDeniedError,
    CatalogBindingCatalogError,
    CatalogBindingLineageError,
    CatalogBindingService,
    ExactCatalogRegistryRecord,
    ExactDatasetLineage,
)
from server.bureau_metadata.catalog_service import BureauCatalogAccessDeniedError
from server.bureau_metadata.crosswalk_governance import (
    CrosswalkEvidenceReference,
    GovernedMappingDecision,
)
from server.bureau_metadata.crosswalk_governance_repository import (
    CROSSWALK_DATABASE_RELATIVE,
)
from server.bureau_metadata.semantic_annotation import (
    BureauOrdinaryRangeReference,
    BureauSpecialDefinitionReference,
    build_bureau_semantic_annotation,
)
from server.bureau_metadata.types import (
    BureauCatalogAccessContext,
    BureauCatalogAccessGrant,
    BureauCatalogKey,
)


NOW = "2026-08-05T16:00:00Z"
CATALOG_CHECKSUM_1 = "a" * 64
CATALOG_CHECKSUM_2 = "b" * 64
SCHEMA_CHECKSUM_1 = "c" * 64
SCHEMA_CHECKSUM_2 = "d" * 64
EVIDENCE_CHECKSUM = "e" * 64
DEFINITION_CHECKSUM = "f" * 64


def _catalog_key(version: str = "1.0") -> BureauCatalogKey:
    return BureauCatalogKey(
        provider="Synthetic Bureau",
        product="Synthetic Credit Dictionary",
        edition="Test",
        dictionary_version=version,
    )


def _identity(**updates: object) -> DatasetVersionCatalogIdentity:
    payload: dict[str, object] = {
        "tenant_id": "tenant-synthetic",
        "project_id": "project-synthetic",
        "dataset_id": "dataset-synthetic",
        "dataset_version_id": "version-synthetic-1",
        "activation_revision": 4,
        "schema_checksum": SCHEMA_CHECKSUM_1,
        "target_contract_id": "target-contract-synthetic",
        "predictor_authorization_id": "predictor-auth-synthetic",
        "catalog_version_id": "catalog-version-synthetic-1",
        "catalog_key": _catalog_key(),
        "catalog_checksum": CATALOG_CHECKSUM_1,
    }
    payload.update(updates)
    return DatasetVersionCatalogIdentity.model_validate(payload)


def _lineage(identity: DatasetVersionCatalogIdentity) -> ExactDatasetLineage:
    return ExactDatasetLineage(
        tenant_id=identity.tenant_id,
        project_id=identity.project_id,
        dataset_id=identity.dataset_id,
        dataset_version_id=identity.dataset_version_id,
        activation_revision=identity.activation_revision,
        schema_checksum=identity.schema_checksum,
        target_contract_id=identity.target_contract_id,
        predictor_authorization_id=identity.predictor_authorization_id,
    )


def _registry_record(
    identity: DatasetVersionCatalogIdentity,
) -> ExactCatalogRegistryRecord:
    return ExactCatalogRegistryRecord(
        catalog_version_id=identity.catalog_version_id,
        catalog_key=identity.catalog_key,
        catalog_checksum=identity.catalog_checksum,
        installation_status="installed",
        integrity_status="verified",
        retired_status="active",
        registry_revision=1,
    )


def _context(tenant_id: str | None = "tenant-synthetic") -> BureauCatalogAccessContext:
    return BureauCatalogAccessContext(
        principal_id="analyst-synthetic",
        tenant_id=tenant_id,
        project_id="project-synthetic",
    )


def _binding_evidence(suffix: str = "1") -> tuple[CatalogBindingEvidenceReference, ...]:
    return tuple(
        CatalogBindingEvidenceReference(
            evidence_id=f"evidence-{kind}-{suffix}",
            evidence_kind=kind,
            authority_id=f"authority-{kind}",
            checksum=EVIDENCE_CHECKSUM,
            recorded_at=NOW,
        )
        for kind in (
            "dataset_lineage",
            "catalog_registry",
            "catalog_entitlement",
        )
    )


class ProjectAuthorization:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    def authorize_project(self, context, project_id, permission):  # type: ignore[no-untyped-def]
        del context, project_id, permission
        return self.allowed


class LineageAuthority:
    def __init__(self, current: ExactDatasetLineage) -> None:
        self.current = current
        self.calls: list[tuple[str, str, str, str]] = []

    def get_exact_lineage(
        self,
        context,
        *,
        tenant_id,
        project_id,
        dataset_id,
        dataset_version_id,
    ):  # type: ignore[no-untyped-def]
        del context
        self.calls.append((tenant_id, project_id, dataset_id, dataset_version_id))
        return self.current


class RegistryAuthority:
    def __init__(self, *records: ExactCatalogRegistryRecord) -> None:
        self.records = {record.catalog_version_id: record for record in records}
        self.contradict_checksum = False

    def get_exact_catalog(
        self, *, catalog_version_id, catalog_key, catalog_checksum
    ):  # type: ignore[no-untyped-def]
        del catalog_key, catalog_checksum
        record = self.records[catalog_version_id]
        if self.contradict_checksum:
            return record.model_copy(update={"catalog_checksum": "0" * 64})
        return record


class Entitlements:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[tuple[str, str]] = []

    def authorize(
        self, context, requested_key, requested_checksum, operation
    ):  # type: ignore[no-untyped-def]
        self.calls.append((requested_checksum, operation))
        if not self.allowed:
            raise BureauCatalogAccessDeniedError("synthetic denial")
        return BureauCatalogAccessGrant(
            grant_id="grant-synthetic",
            principal_id=context.principal_id,
            tenant_id=context.tenant_id,
            catalog_key=requested_key,
            catalog_checksum=requested_checksum,
            operation=operation,
        )


@pytest.fixture
def restricted_root(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    hermetic_root = os.environ.get("ATLAS_HERMETIC_ROOT")
    if hermetic_root:
        root = (
            Path(hermetic_root)
            / "authorities"
            / "catalog-binding-tests"
            / request.node.name
        )
        root.mkdir(parents=True, exist_ok=False)
    else:
        root = Path(tempfile.mkdtemp(prefix="atlas-binding-test-")) / "restricted"
        root.mkdir()

    def validate_exact_test_root(value, **_kwargs):  # type: ignore[no-untyped-def]
        candidate = Path(value).resolve(strict=True)
        if candidate != root.resolve(strict=True):
            raise AssertionError("Only the exact synthetic restricted root is permitted.")
        return candidate

    monkeypatch.setattr(
        repository_module,
        "validate_restricted_metadata_root",
        validate_exact_test_root,
    )
    return root


def _service_parts(
    restricted_root: Path,
    identity: DatasetVersionCatalogIdentity | None = None,
):
    selected = identity or _identity()
    repository = SQLiteCatalogBindingRepository(restricted_root)
    lineage = LineageAuthority(_lineage(selected))
    registry = RegistryAuthority(_registry_record(selected))
    entitlements = Entitlements()
    service = CatalogBindingService(
        repository=repository,
        project_authorization=ProjectAuthorization(),
        lineage_authority=lineage,
        catalog_registry=registry,
        catalog_entitlements=entitlements,
        clock=lambda: datetime(2026, 8, 5, 16, 0, tzinfo=timezone.utc),
    )
    return service, repository, lineage, registry, entitlements


def test_lazy_missing_binding_read_does_not_create_authority(
    restricted_root: Path,
) -> None:
    repository = SQLiteCatalogBindingRepository(restricted_root)
    expected_database = restricted_root / CROSSWALK_DATABASE_RELATIVE

    assert not expected_database.exists()
    with pytest.raises(CatalogBindingNotFoundError):
        repository.get_current("bcb_missing_synthetic")
    assert not expected_database.exists()
    assert not expected_database.parent.exists()


def test_exact_binding_pins_all_authorities_and_never_mutates_workflow(
    restricted_root: Path,
) -> None:
    identity = _identity()
    service, repository, lineage, _registry, entitlements = _service_parts(
        restricted_root, identity
    )

    record = service.bind(
        context=_context(),
        identity=identity,
        actor_id="analyst-synthetic",
        evidence=_binding_evidence(),
        crosswalk_id="crosswalk-synthetic",
        crosswalk_revision=3,
    )

    assert repository.database_path == restricted_root / CROSSWALK_DATABASE_RELATIVE
    assert record.identity == identity
    assert record.revision == 1
    assert record.status == "active"
    assert record.server_recorded_at == NOW
    assert record.crosswalk_id == "crosswalk-synthetic"
    assert record.crosswalk_revision == 3
    assert record.dataset_mutated is False
    assert record.treatment_mutated is False
    assert record.predictor_authorization_mutated is False
    assert record.analysis_partition_mutated is False
    assert lineage.calls == [
        (
            identity.tenant_id,
            identity.project_id,
            identity.dataset_id,
            identity.dataset_version_id,
        )
    ]
    assert entitlements.calls == [(CATALOG_CHECKSUM_1, "crosswalk_candidate")]

    resolution = service.resolve_current(
        context=_context(), scope=dataset_catalog_binding_scope(identity)
    )
    assert resolution.binding == record
    assert resolution.effective_status == "active"
    assert resolution.lineage_current is True


def test_tenantless_authority_is_preserved_as_exact_none(
    restricted_root: Path,
) -> None:
    identity = _identity(tenant_id=None)
    service, _repository, _lineage, _registry, _entitlements = _service_parts(
        restricted_root, identity
    )

    record = service.bind(
        context=_context(None),
        identity=identity,
        actor_id="analyst-synthetic",
        evidence=_binding_evidence("tenantless"),
    )

    assert record.identity.tenant_id is None
    assert dataset_catalog_binding_scope(record.identity).tenant_id is None
    assert service.resolve_current(
        context=_context(None), scope=dataset_catalog_binding_scope(identity)
    ).binding == record


def test_binding_fails_closed_on_lineage_catalog_or_entitlement_contradiction(
    restricted_root: Path,
) -> None:
    identity = _identity()
    service, repository, lineage, registry, entitlements = _service_parts(
        restricted_root, identity
    )
    lineage.current = _lineage(identity).model_copy(
        update={"activation_revision": identity.activation_revision + 1}
    )
    with pytest.raises(CatalogBindingLineageError) as lineage_error:
        service.bind(
            context=_context(),
            identity=identity,
            actor_id="analyst-synthetic",
            evidence=_binding_evidence(),
        )
    assert lineage_error.value.reason_code == "exact_lineage_contradictory"

    lineage.current = _lineage(identity)
    registry.contradict_checksum = True
    with pytest.raises(CatalogBindingCatalogError) as catalog_error:
        service.bind(
            context=_context(),
            identity=identity,
            actor_id="analyst-synthetic",
            evidence=_binding_evidence(),
        )
    assert catalog_error.value.reason_code == "exact_catalog_contradictory"

    registry.contradict_checksum = False
    entitlements.allowed = False
    with pytest.raises(CatalogBindingAccessDeniedError):
        service.bind(
            context=_context(),
            identity=identity,
            actor_id="analyst-synthetic",
            evidence=_binding_evidence(),
        )
    with pytest.raises(CatalogBindingNotFoundError):
        repository.get_current(catalog_binding_scope_identity(dataset_catalog_binding_scope(identity)))


def test_repository_rejects_invalid_checksum_without_partial_binding(
    restricted_root: Path,
) -> None:
    identity = _identity()
    repository = SQLiteCatalogBindingRepository(restricted_root)
    valid = build_catalog_binding_revision(
        identity=identity,
        revision=1,
        status="active",
        actor_id="analyst-synthetic",
        server_recorded_at=NOW,
        evidence=_binding_evidence(),
    )
    invalid = valid.model_copy(update={"revision_checksum": "0" * 64})

    with pytest.raises(
        CatalogBindingRepositoryStateError, match="checksum verification"
    ):
        repository.append(invalid, expected_revision=0)
    with pytest.raises(CatalogBindingNotFoundError):
        repository.get_current(valid.binding_id)


def test_binding_restart_recovers_exact_current_revision(
    restricted_root: Path,
) -> None:
    identity = _identity()
    service, repository, _lineage, _registry, _entitlements = _service_parts(
        restricted_root, identity
    )
    first = service.bind(
        context=_context(),
        identity=identity,
        actor_id="analyst-synthetic",
        evidence=_binding_evidence(),
    )

    reopened = SQLiteCatalogBindingRepository(restricted_root)

    assert reopened.get_current(first.binding_id) == first
    assert reopened.get_revision(first.binding_id, 1) == first
    assert reopened.history(first.binding_id) == (first,)


def test_competing_binding_revisions_allow_one_writer_and_preserve_history(
    restricted_root: Path,
) -> None:
    identity = _identity()
    first_repository = SQLiteCatalogBindingRepository(restricted_root)
    second_repository = SQLiteCatalogBindingRepository(restricted_root)
    first = build_catalog_binding_revision(
        identity=identity,
        revision=1,
        status="active",
        actor_id="analyst-synthetic",
        server_recorded_at=NOW,
        evidence=_binding_evidence("first"),
    )
    first_repository.append(first, expected_revision=0)
    barrier = Barrier(2)

    def compete(repository: SQLiteCatalogBindingRepository, suffix: str):
        candidate = build_catalog_binding_revision(
            identity=identity,
            revision=2,
            status="active",
            actor_id="analyst-synthetic",
            server_recorded_at=NOW,
            evidence=_binding_evidence(suffix),
            crosswalk_id=f"crosswalk-{suffix}",
            crosswalk_revision=2,
            previous_revision_checksum=first.revision_checksum,
        )
        barrier.wait(timeout=5)
        return repository.append(candidate, expected_revision=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (
            pool.submit(compete, first_repository, "one"),
            pool.submit(compete, second_repository, "two"),
        )
    successes = []
    failures = []
    for future in futures:
        try:
            successes.append(future.result())
        except BaseException as exc:  # noqa: BLE001 - exact type asserted
            failures.append(exc)

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], CatalogBindingConflictError)
    assert first_repository.history(first.binding_id) == (first, successes[0])


def test_change_catalog_binding_uses_one_dataset_scope_head(
    restricted_root: Path,
) -> None:
    first_identity = _identity()
    second_identity = _identity(
        catalog_version_id="catalog-version-synthetic-2",
        catalog_key=_catalog_key("2.0"),
        catalog_checksum=CATALOG_CHECKSUM_2,
    )
    service, repository, _lineage, registry, _entitlements = _service_parts(
        restricted_root, first_identity
    )
    registry.records[second_identity.catalog_version_id] = _registry_record(
        second_identity
    )
    first = service.bind(
        context=_context(),
        identity=first_identity,
        actor_id="analyst-synthetic",
        evidence=_binding_evidence("first"),
    )
    second = service.revise(
        context=_context(),
        identity=second_identity,
        expected_revision=1,
        status="active",
        actor_id="analyst-synthetic",
        evidence=_binding_evidence("second"),
    )

    assert first.binding_id == second.binding_id
    assert repository.get_current(first.binding_id) == second
    assert repository.history(first.binding_id) == (first, second)
    resolution = service.resolve_current(
        context=_context(), scope=dataset_catalog_binding_scope(first_identity)
    )
    assert resolution.binding.identity.catalog_version_id == (
        second_identity.catalog_version_id
    )


def test_upstream_change_marks_resolution_stale_then_reconfirms_same_history(
    restricted_root: Path,
) -> None:
    first_identity = _identity()
    service, repository, lineage, _registry, _entitlements = _service_parts(
        restricted_root, first_identity
    )
    first = service.bind(
        context=_context(),
        identity=first_identity,
        actor_id="analyst-synthetic",
        evidence=_binding_evidence("first"),
    )
    revised_identity = _identity(
        activation_revision=5,
        schema_checksum=SCHEMA_CHECKSUM_2,
        target_contract_id="target-contract-synthetic-2",
        predictor_authorization_id="predictor-auth-synthetic-2",
    )
    lineage.current = _lineage(revised_identity)

    stale = service.resolve_current(
        context=_context(), scope=dataset_catalog_binding_scope(first_identity)
    )
    assert stale.effective_status == "stale"
    assert stale.lineage_current is False
    assert stale.stale_reason == "upstream_authority_changed"

    second = service.revise(
        context=_context(),
        identity=revised_identity,
        expected_revision=1,
        status="active",
        actor_id="analyst-synthetic",
        evidence=_binding_evidence("reconfirmed"),
    )
    assert second.binding_id == first.binding_id
    assert [record.revision for record in repository.history(first.binding_id)] == [
        1,
        2,
    ]
    assert service.resolve_current(
        context=_context(), scope=dataset_catalog_binding_scope(revised_identity)
    ).effective_status == "active"


def _mapping_evidence(kind: str, suffix: str | None = None) -> CrosswalkEvidenceReference:
    resolved = suffix or kind
    return CrosswalkEvidenceReference(
        evidence_id=f"mapping-evidence-{resolved}",
        evidence_kind=kind,
        authority_id=f"mapping-authority-{resolved}",
        checksum=EVIDENCE_CHECKSUM,
        created_by="analyst-synthetic",
        created_at=NOW,
    )


def _mapping_decision(state: str) -> GovernedMappingDecision:
    if state == "exact_verified":
        return GovernedMappingDecision(
            dataset_field="ExternalRiskEstimate",
            mapping_state=state,
            candidate_attribute_code="ATTR_001",
            evidence=(
                _mapping_evidence("catalog_definition"),
                _mapping_evidence("exact_match"),
                _mapping_evidence("analyst_review"),
            ),
            analyst_confirmed=True,
            reviewer_id="analyst-synthetic",
            rationale="Synthetic exact provider definition was reviewed.",
        )
    if state == "approved_alias":
        return GovernedMappingDecision(
            dataset_field="ExternalRiskEstimate",
            mapping_state=state,
            candidate_attribute_code="ATTR_001",
            evidence=(
                _mapping_evidence("institutional_alias", "alias-reference"),
                _mapping_evidence("analyst_review"),
            ),
            analyst_confirmed=True,
            alias_authority_id="mapping-authority-alias-reference",
            institutional_alias_reference="mapping-evidence-alias-reference",
            reviewer_id="analyst-synthetic",
            rationale="Synthetic institutional alias was reviewed.",
        )
    if state == "transformed_or_derived":
        return GovernedMappingDecision(
            dataset_field="ExternalRiskEstimate",
            mapping_state=state,
            candidate_attribute_code="ATTR_DERIVED",
            source_attribute_codes=("ATTR_001",),
            evidence=(
                _mapping_evidence("transformation_lineage"),
                _mapping_evidence("analyst_review"),
            ),
            analyst_confirmed=True,
            transformation_reference_id="mapping-evidence-transformation_lineage",
            transformation_rule="Apply a synthetic governed derivation.",
            transformation_or_recoding_concerns=("Confirm synthetic scaling.",),
            data_type="decimal",
            units="unitless",
            source_system="synthetic",
            timing="Synthetic observation window.",
            special_value_handling="Preserve synthetic special values.",
            value_range_reconciliation="Synthetic range reconciled.",
            special_value_reconciliation="Synthetic special values reconciled.",
            reviewer_id="analyst-synthetic",
            rationale="Synthetic derivation was reviewed but is not provider authority.",
        )
    if state == "probable_review_required":
        return GovernedMappingDecision(
            dataset_field="ExternalRiskEstimate",
            mapping_state=state,
            candidate_attribute_code="ATTR_001",
            evidence=(_mapping_evidence("semantic_analysis"),),
        )
    if state == "ambiguous_review_required":
        return GovernedMappingDecision(
            dataset_field="ExternalRiskEstimate",
            mapping_state=state,
            candidate_attribute_code="ATTR_001",
            alternative_attribute_codes=("ATTR_002",),
            evidence=(_mapping_evidence("ambiguity_analysis"),),
        )
    if state == "unresolved":
        return GovernedMappingDecision(
            dataset_field="ExternalRiskEstimate",
            mapping_state=state,
            evidence=(_mapping_evidence("unresolved_assessment"),),
        )
    raise AssertionError(f"Unsupported synthetic mapping state: {state}")


def _binding_record() -> DatasetCatalogBindingRevision:
    return build_catalog_binding_revision(
        identity=_identity(),
        revision=1,
        status="active",
        actor_id="analyst-synthetic",
        server_recorded_at=NOW,
        evidence=_binding_evidence(),
        crosswalk_id="crosswalk-synthetic",
        crosswalk_revision=1,
    )


@pytest.mark.parametrize(
    ("mapping_state", "authoritative"),
    (
        ("exact_verified", True),
        ("approved_alias", True),
        ("transformed_or_derived", False),
        ("probable_review_required", False),
        ("ambiguous_review_required", False),
        ("unresolved", False),
    ),
)
def test_semantic_authority_is_limited_to_accepted_exact_or_alias_mapping(
    mapping_state: str,
    authoritative: bool,
) -> None:
    annotation = build_bureau_semantic_annotation(
        binding=_binding_record(),
        decision=_mapping_decision(mapping_state),
        binding_current=True,
        entitlement_verified=True,
    )

    assert annotation.provider_authoritative is authoritative
    assert annotation.dataset_mutated is False
    assert annotation.treatment_mutated is False
    assert annotation.predictor_authorization_mutated is False
    assert annotation.analysis_partition_mutated is False
    if not authoritative:
        assert annotation.authority_state.startswith("non_authoritative_")
        assert annotation.non_authoritative_reasons


def test_generic_heloc_field_remains_unresolved_and_stale_or_unentitled_is_denied() -> None:
    binding = _binding_record()
    unresolved = build_bureau_semantic_annotation(
        binding=binding,
        decision=_mapping_decision("unresolved"),
        binding_current=True,
        entitlement_verified=True,
    )
    stale = build_bureau_semantic_annotation(
        binding=binding,
        decision=_mapping_decision("exact_verified"),
        binding_current=False,
        entitlement_verified=True,
    )
    unentitled = build_bureau_semantic_annotation(
        binding=binding,
        decision=_mapping_decision("exact_verified"),
        binding_current=True,
        entitlement_verified=False,
    )

    assert unresolved.dataset_field == "ExternalRiskEstimate"
    assert unresolved.candidate_attribute_code is None
    assert unresolved.authority_state == "non_authoritative_unresolved"
    assert stale.authority_state == "non_authoritative_stale"
    assert unentitled.authority_state == "non_authoritative_unentitled"
    assert not any(
        item.provider_authoritative for item in (unresolved, stale, unentitled)
    )


def test_semantic_annotation_exposes_only_bounded_range_and_special_references() -> None:
    ordinary_range = BureauOrdinaryRangeReference(
        attribute_code="ATTR_001",
        definition_id="range-definition-1",
        definition_checksum=DEFINITION_CHECKSUM,
        ordinary_min="0",
        ordinary_max="999",
        range_expression="0 through 999",
    )
    special = BureauSpecialDefinitionReference(
        attribute_code="ATTR_001",
        definition_id="special-definition-1",
        definition_checksum=DEFINITION_CHECKSUM,
        value_code="-9",
        semantic_family="no_hit",
        meaning="No qualifying bureau record was available.",
    )
    annotation = build_bureau_semantic_annotation(
        binding=_binding_record(),
        decision=_mapping_decision("exact_verified"),
        binding_current=True,
        entitlement_verified=True,
        ordinary_range=ordinary_range,
        special_definitions=(special,),
    )

    assert annotation.provider_authoritative is True
    assert annotation.ordinary_range == ordinary_range
    assert annotation.special_definitions == (special,)
    assert "restricted_storage_reference" not in annotation.model_dump(mode="json")

    oversized = tuple(
        special.model_copy(update={"definition_id": f"special-{index}"})
        for index in range(65)
    )
    with pytest.raises(ValidationError, match="At most 64"):
        build_bureau_semantic_annotation(
            binding=_binding_record(),
            decision=_mapping_decision("exact_verified"),
            binding_current=True,
            entitlement_verified=True,
            special_definitions=oversized,
        )

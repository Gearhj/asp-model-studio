from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.bureau_metadata.catalog_binding import (
    CatalogBindingEvidenceReference,
    DatasetCatalogBindingScope,
    DatasetVersionCatalogIdentity,
    build_catalog_binding_revision,
)
from server.bureau_metadata.catalog_binding_repository import CatalogBindingConflictError
from server.bureau_metadata.catalog_binding_service import CatalogBindingCurrentResolution
from server.bureau_metadata.catalog_service import BureauCatalogAccessDeniedError
from server.bureau_metadata.crosswalk_governance import CrosswalkLineage
from server.bureau_metadata.crosswalk_governance_repository import (
    InMemoryGovernedCrosswalkRepository,
)
from server.bureau_metadata.crosswalk_governance_service import GovernedCrosswalkService
from server.bureau_metadata.crosswalk_router import (
    CrosswalkRouterRuntime,
    get_crosswalk_router_runtime,
    router,
)
from server.security.security_store import require_user
from server.bureau_metadata.types import (
    BureauAttributeMatchCandidate,
    BureauCatalogAccessContext,
    BureauCatalogAccessGrant,
    BureauCatalogKey,
)


NOW = "2026-08-05T12:00:00Z"
CATALOG_CHECKSUM = "a" * 64
SCHEMA_CHECKSUM = "b" * 64
PROJECT_ID = "project-router-synthetic"
DATASET_ID = "dataset-router-synthetic"
VERSION_ID = "version-router-synthetic"
ACTOR = "analyst-router-synthetic"


def _key() -> BureauCatalogKey:
    return BureauCatalogKey(
        provider="Synthetic Bureau",
        product="Synthetic Product",
        edition="Test",
        dictionary_version="1.0",
    )


class _Authorization:
    def authorize_project(self, context, project_id, permission):  # type: ignore[no-untyped-def]
        return context.project_id == project_id and permission in {"view", "edit"}


class _Entitlements:
    def authorize(self, context, key, checksum, operation):  # type: ignore[no-untyped-def]
        return BureauCatalogAccessGrant(
            grant_id="grant-router-synthetic",
            principal_id=context.principal_id,
            tenant_id=context.tenant_id,
            catalog_key=key,
            catalog_checksum=checksum,
            operation=operation,
            expires_at="2099-01-01T00:00:00Z",
        )


class _LineageAuthority:
    def __init__(self, lineage: CrosswalkLineage) -> None:
        self.lineage = lineage

    def current_lineage(self, context, project_id):  # type: ignore[no-untyped-def]
        assert context.project_id == project_id
        return self.lineage


class _CatalogCandidates:
    def __init__(self, *, alias: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.alias = alias

    def build_dataset_crosswalk_candidates_exact(
        self,
        context,
        catalog_key,
        catalog_checksum,
        fields,
        *,
        target_field=None,
        target_source_fields=(),
    ):  # type: ignore[no-untyped-def]
        names = tuple(field["field_name"] for field in fields)
        self.calls.append(
            {
                "context": context,
                "fields": names,
                "target": target_field,
                "target_sources": tuple(target_source_fields),
            }
        )
        mappings = []
        for name in names:
            exact = name == "ATTR_001"
            mappings.append(
                BureauAttributeMatchCandidate(
                    dataset_field=name,
                    catalog_key=catalog_key,
                    catalog_checksum=catalog_checksum,
                    candidate_attribute_code="ATTR_001" if exact else None,
                    match_status=(
                        "approved_institutional_alias"
                        if exact and self.alias
                        else "exact_dictionary_code_match"
                        if exact
                        else "no_supported_match"
                    ),
                    confidence=1.0 if exact else 0.0,
                    institutional_alias_reference=(
                        "alias-policy-router" if exact and self.alias else None
                    ),
                ).model_dump(mode="json")
            )
        return {
            "mappings": mappings,
            "candidate_only": True,
            "crosswalk_checksum": "c" * 64,
        }


class _Operational:
    def __init__(self, candidates: _CatalogCandidates) -> None:
        self.catalogs = candidates
        self.batch_calls: list[tuple[str, ...]] = []
        self.deny_batch = False

    def get_mapped_attribute_batch(
        self,
        *,
        principal_id,
        tenant_id,
        catalog_version_id,
        attribute_codes,
    ):  # type: ignore[no-untyped-def]
        del principal_id, tenant_id
        if self.deny_batch:
            raise BureauCatalogAccessDeniedError("Synthetic batch denial")
        codes = tuple(sorted(attribute_codes))
        self.batch_calls.append(codes)
        assert codes == ("ATTR_001",)
        return {
            "catalog_version_id": catalog_version_id,
            "catalog_checksum": CATALOG_CHECKSUM,
            "requested": 1,
            "returned": 1,
            "bounded": True,
            "attributes": [
                {
                    "attribute_code": "ATTR_001",
                    "description": "Synthetic exact provider definition.",
                    "numeric_type": "integer",
                    "units": "points",
                    "valid_range_expression": "0 through 999",
                    "ordinary_min": "0",
                    "ordinary_max": "999",
                    "record_checksum": "d" * 64,
                    "special_values": [
                        {
                            "value_code": "-9",
                            "meaning": "Synthetic unavailable value.",
                            "semantic_family": "unavailable",
                            "definition_id": "special-router-9",
                            "definition_checksum": "e" * 64,
                        }
                    ],
                    "special_values_truncated": False,
                }
            ],
        }


class _BindingService:
    def __init__(self, record, scope: DatasetCatalogBindingScope) -> None:  # type: ignore[no-untyped-def]
        self.record = record
        self.scope = scope
        self._project_authorization = _Authorization()
        self.fail_revision: int | None = None

    def resolve_current(self, *, context, scope):  # type: ignore[no-untyped-def]
        assert context.project_id == scope.project_id
        assert scope == self.scope
        return CatalogBindingCurrentResolution(
            scope=scope,
            binding=self.record,
            effective_status="active",
            lineage_current=True,
        )

    def revise(
        self,
        *,
        context,
        identity,
        expected_revision,
        status,
        actor_id,
        evidence,
        crosswalk_id=None,
        crosswalk_revision=None,
        stale_reason=None,
    ):  # type: ignore[no-untyped-def]
        del context
        if self.fail_revision is not None or expected_revision != self.record.revision:
            raise CatalogBindingConflictError(
                expected_revision=expected_revision,
                current_revision=self.record.revision,
            )
        self.record = build_catalog_binding_revision(
            identity=identity,
            revision=expected_revision + 1,
            status=status,
            actor_id=actor_id,
            server_recorded_at=NOW,
            evidence=evidence,
            crosswalk_id=crosswalk_id,
            crosswalk_revision=crosswalk_revision,
            stale_reason=stale_reason,
            previous_revision_checksum=self.record.revision_checksum,
        )
        return self.record


def _binding_evidence() -> tuple[CatalogBindingEvidenceReference, ...]:
    return tuple(
        CatalogBindingEvidenceReference(
            evidence_id=f"binding-{kind}",
            evidence_kind=kind,
            authority_id=f"authority-{kind}",
            checksum=(str(index + 1) * 64)[:64],
            recorded_at=NOW,
        )
        for index, kind in enumerate(
            ("dataset_lineage", "catalog_registry", "catalog_entitlement")
        )
    )


def _runtime(
    *,
    alias: bool = False,
    documentation_recorder=None,
    observed_summary_provider=None,
) -> tuple[CrosswalkRouterRuntime, _CatalogCandidates, _BindingService]:
    context = BureauCatalogAccessContext(
        principal_id=ACTOR,
        tenant_id="tenant-router-synthetic",
        project_id=PROJECT_ID,
    )
    identity = DatasetVersionCatalogIdentity(
        tenant_id=context.tenant_id,
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID,
        dataset_version_id=VERSION_ID,
        activation_revision=3,
        schema_checksum=SCHEMA_CHECKSUM,
        target_contract_id="target-contract-router",
        predictor_authorization_id="predictor-auth-router",
        catalog_version_id="catalog-version-router",
        catalog_key=_key(),
        catalog_checksum=CATALOG_CHECKSUM,
    )
    scope = DatasetCatalogBindingScope(
        tenant_id=context.tenant_id,
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID,
        dataset_version_id=VERSION_ID,
    )
    binding = build_catalog_binding_revision(
        identity=identity,
        revision=1,
        status="active",
        actor_id=ACTOR,
        server_recorded_at=NOW,
        evidence=_binding_evidence(),
    )
    binding_service = _BindingService(binding, scope)
    candidates = _CatalogCandidates(alias=alias)
    operational = _Operational(candidates)
    binding_runtime = SimpleNamespace(
        context=context,
        operational=operational,
        service=binding_service,
    )
    lineage = CrosswalkLineage(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID,
        dataset_version_id=VERSION_ID,
        activation_revision=3,
        target_contract_id="target-contract-router",
        predictor_authorization_id="predictor-auth-router",
        schema_checksum=SCHEMA_CHECKSUM,
        catalog_key=_key(),
        catalog_checksum=CATALOG_CHECKSUM,
    )
    repository = InMemoryGovernedCrosswalkRepository()
    governed_service = GovernedCrosswalkService(
        repository=repository,
        project_authorization=_Authorization(),
        catalog_entitlements=_Entitlements(),
        lineage_authority=_LineageAuthority(lineage),
    )
    runtime = CrosswalkRouterRuntime(
        binding_runtime=binding_runtime,
        scope=scope,
        binding_resolution=binding_service.resolve_current(
            context=context, scope=scope
        ),
        predictor_manifest={
            "target": "outcome",
            "target_source_excluded": ["outcome_proxy"],
            "excluded_predictors": {"system_split": "system field"},
            "authorized_predictors": ["ATTR_001", "LOCAL_ONLY"],
        },
        lineage=lineage,
        repository=repository,  # type: ignore[arg-type]
        service=governed_service,
        documentation_recorder=documentation_recorder or (lambda **kwargs: {
            "evidence_id": (
                f"evidence-{kwargs['binding'].binding_id}-"
                f"r{kwargs['binding'].revision}"
            ),
            "documentation_package_id": (
                f"documentation-{kwargs['binding'].binding_id}-"
                f"r{kwargs['binding'].revision}"
            ),
        }),
        observed_summary_provider=observed_summary_provider,
    )
    return runtime, candidates, binding_service


def _client(runtime: CrosswalkRouterRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_crosswalk_router_runtime] = lambda: runtime
    app.dependency_overrides[require_user] = lambda: {
        "userId": ACTOR,
        "tenantId": "tenant-router-synthetic",
    }
    return TestClient(app)


def _base() -> str:
    return (
        f"/projects/{PROJECT_ID}/datasets/{DATASET_ID}/versions/{VERSION_ID}"
        "/bureau-metadata/crosswalk"
    )


def _exact_request(*, expected_crosswalk: int = 0, expected_binding: int = 1):
    return {
        "expected_crosswalk_revision": expected_crosswalk,
        "expected_binding_revision": expected_binding,
        "analyst_reason": "The exact provider code was independently reviewed.",
        "decisions": [
            {
                "dataset_field": "ATTR_001",
                "mapping_state": "exact_verified",
                "candidate_attribute_code": "ATTR_001",
                "rationale": "The exact provider code and definition were reviewed.",
            }
        ],
    }


def _alias_request():
    return {
        "expected_crosswalk_revision": 0,
        "expected_binding_revision": 1,
        "analyst_reason": "The governed institutional alias was independently reviewed.",
        "decisions": [
            {
                "dataset_field": "ATTR_001",
                "mapping_state": "approved_alias",
                "candidate_attribute_code": "ATTR_001",
                "alias_authority_id": "alias-authority-router",
                "institutional_alias_reference": "alias-policy-router",
                "rationale": "The exact governed alias and definition were reviewed.",
            }
        ],
    }


def test_preview_uses_only_authorized_schema_and_never_auto_approves() -> None:
    runtime, candidates, binding_service = _runtime()
    response = _client(runtime).get(_base() + "/preview")
    assert response.status_code == 200
    body = response.json()
    assert body["persisted"] is False
    assert body["summary"]["authoritative_mapping_count"] == 0
    assert {
        decision["mapping_state"] for decision in body["initial_decisions"]
    } == {"probable_review_required", "unresolved"}
    assert all(not decision["analyst_confirmed"] for decision in body["initial_decisions"])
    assert candidates.calls[0]["fields"] == ("ATTR_001", "LOCAL_ONLY")
    assert candidates.calls[0]["target"] == "outcome"
    assert candidates.calls[0]["target_sources"] == (
        "outcome_proxy",
        "system_split",
    )
    assert binding_service.record.revision == 1


def test_explicit_decision_persists_and_pins_exact_binding_revision() -> None:
    runtime, _candidates, binding_service = _runtime()
    client = _client(runtime)
    response = client.post(_base() + "/decisions", json=_exact_request())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["governance"]["revision"] == 1
    assert body["governance"]["decisions"][0]["mapping_state"] == "exact_verified"
    assert body["binding_linked"] is True
    assert body["binding"]["revision"] == 2
    assert body["binding"]["crosswalk_id"] == body["governance"]["governance_id"]
    assert body["binding"]["crosswalk_revision"] == 1
    assert body["documentation_persisted"] is True
    assert body["documentation"]["evidence_id"].startswith("evidence-")
    assert binding_service.record.revision == 2
    assert all(body[field] is False for field in (
        "dataset_mutated",
        "target_contract_mutated",
        "treatment_mutated",
        "predictor_authorization_mutated",
        "analysis_partition_mutated",
        "feature_manifest_mutated",
    ))


def test_partial_state_is_explicit_and_semantics_fail_closed_until_retry() -> None:
    runtime, _candidates, binding_service = _runtime()
    binding_service.fail_revision = 1
    client = _client(runtime)
    response = client.post(_base() + "/decisions", json=_exact_request())
    assert response.status_code == 409
    partial = response.json()
    assert partial["partial_metadata_state"] is True
    assert partial["governance_persisted"] is True
    assert partial["binding_linked"] is False
    assert binding_service.record.crosswalk_id is None
    semantic = client.get(_base() + "/semantic-annotations")
    assert semantic.status_code == 404
    assert (
        semantic.json()["detail"]["code"]
        == "bureau_crosswalk_exact_resource_unavailable"
    )

    binding_service.fail_revision = None
    retry = client.post(
        _base() + "/binding-link",
        json={
            "crosswalk_revision": partial["crosswalk_revision"],
            "expected_binding_revision": 1,
            "analyst_reason": "Retry the exact durable crosswalk binding link.",
        },
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["binding_linked"] is True
    assert binding_service.record.crosswalk_revision == 1


def test_documentation_failure_is_partial_and_idempotent_retry_closes_it() -> None:
    calls: list[dict[str, Any]] = []

    def recorder(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("synthetic documentation outage")
        return {
            "evidence_id": "evidence-crosswalk-retry",
            "documentation_package_id": "mdd-crosswalk-retry",
        }

    runtime, _candidates, binding_service = _runtime(
        documentation_recorder=recorder
    )
    client = _client(runtime)
    first = client.post(_base() + "/decisions", json=_exact_request())
    assert first.status_code == 503
    partial = first.json()
    assert partial["partial_metadata_state"] is True
    assert partial["governance_persisted"] is True
    assert partial["binding_linked"] is True
    assert partial["documentation_persisted"] is False
    assert binding_service.record.revision == 2

    retry = client.post(
        _base() + "/binding-link",
        json={
            "crosswalk_revision": 1,
            "expected_binding_revision": 2,
            "analyst_reason": "Retry bounded evidence and documentation persistence.",
        },
    )
    assert retry.status_code == 200, retry.text
    body = retry.json()
    assert body["idempotent_binding_link"] is True
    assert body["documentation_persisted"] is True
    assert body["documentation"]["documentation_package_id"] == "mdd-crosswalk-retry"
    assert calls[-1]["mapping_counts"] == {
        "authoritative": 1,
        "review_required": 0,
        "unresolved": 1,
        "rejected": 0,
        "special_definitions_used": 0,
        "contradictions": 0,
    }


def test_semantic_annotations_are_accepted_only_bounded_and_canonical() -> None:
    runtime, _candidates, _binding_service = _runtime()
    client = _client(runtime)
    assert client.post(_base() + "/decisions", json=_exact_request()).status_code == 200
    response = client.get(_base() + "/semantic-annotations")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"ok", "annotation_set", "annotations"}
    assert body["annotation_set"]["accepted_annotation_count"] == 1
    assert body["annotation_set"]["crosswalk_revision"] == 1
    assert len(body["annotation_set"]["annotation_set_checksum"]) == 64
    assert body["annotations"][0]["provider_authoritative"] is True
    assert body["annotations"][0]["description"] == "Synthetic exact provider definition."
    assert body["annotations"][0]["data_type"] == "integer"
    assert body["annotations"][0]["units"] == "points"
    assert body["annotations"][0]["ordinary_range"]["ordinary_max"] == "999"
    assert body["annotations"][0]["special_definitions"][0]["value_code"] == "-9"
    assert runtime.binding_runtime.operational.batch_calls == [("ATTR_001",)]
    serialized = response.text.casefold()
    assert "catalog.attributes" not in serialized
    assert "source_file" not in serialized

    alias = client.get(
        f"/projects/{PROJECT_ID}/datasets/{DATASET_ID}/versions/{VERSION_ID}"
        "/bureau-metadata/annotations"
    )
    assert alias.status_code == 200
    assert alias.json() == body


def test_accepted_alias_uses_same_bounded_batch_and_unentitled_batch_is_denied() -> None:
    runtime, _candidates, _binding_service = _runtime(alias=True)
    client = _client(runtime)
    accepted = client.post(_base() + "/decisions", json=_alias_request())
    assert accepted.status_code == 200, accepted.text
    annotation = client.get(_base() + "/semantic-annotations")
    assert annotation.status_code == 200, annotation.text
    assert annotation.json()["annotations"][0]["mapping_state"] == "approved_alias"
    assert annotation.json()["annotations"][0]["description"].startswith("Synthetic")
    assert runtime.binding_runtime.operational.batch_calls == [("ATTR_001",)]

    runtime.binding_runtime.operational.deny_batch = True
    denied = client.get(_base() + "/semantic-annotations")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "bureau_crosswalk_access_denied"


def _observed_summary(
    *,
    data_type: str = "int64",
    observed_min: object = 0,
    observed_max: object = 900,
    observed_special_values: tuple[object, ...] = (),
):
    def resolve(runtime):  # type: ignore[no-untyped-def]
        assert runtime.lineage.dataset_version_id == VERSION_ID
        return {
            "ATTR_001": {
                "dataset_field": "ATTR_001",
                "data_type": data_type,
                "field_length": None,
                "observed_min": observed_min,
                "observed_max": observed_max,
                "observed_values": (),
                "observed_special_values": observed_special_values,
                "special_summary_available": True,
                "source": "synthetic_backend_authoritative_summary",
                "summary_checksum": "f" * 64,
                "raw_rows_accessed": False,
                "browser_preview_used": False,
                "final_holdout_accessed": False,
            }
        }

    return resolve


def test_consistency_reports_unused_defined_codes_and_unmapped_fields() -> None:
    runtime, _candidates, _binding_service = _runtime(
        observed_summary_provider=_observed_summary()
    )
    client = _client(runtime)
    assert client.post(_base() + "/decisions", json=_exact_request()).status_code == 200
    response = client.get(_base() + "/consistency")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["identity"]["project_id"] == PROJECT_ID
    assert body["identity"]["dataset_id"] == DATASET_ID
    assert body["identity"]["dataset_version_id"] == VERSION_ID
    by_field = {item["dataset_field"]: item for item in body["results"]}
    assert (
        by_field["ATTR_001"]["consistency_state"]
        == "consistent_with_observed_unused_codes"
    ), by_field["ATTR_001"]
    assert by_field["ATTR_001"]["observed_unused_special_codes"] == ["-9"]
    assert by_field["LOCAL_ONLY"]["consistency_state"] == "mapping_unresolved"
    assert body["summary"]["raw_rows_accessed"] is False
    assert body["summary"]["browser_preview_used"] is False
    assert body["summary"]["final_holdout_accessed"] is False
    assert body["summary"]["dataset_mutated"] is False
    assert body["summary"]["predictor_authorization_mutated"] is False
    assert body["summary"]["analysis_partition_mutated"] is False
    assert body["summary"]["feature_manifest_mutated"] is False


def test_consistency_blocks_recommendations_on_range_and_type_contradiction() -> None:
    runtime, _candidates, _binding_service = _runtime(
        observed_summary_provider=_observed_summary(
            data_type="string",
            observed_min=-20,
            observed_max=1_200,
            observed_special_values=(-20,),
        )
    )
    client = _client(runtime)
    assert client.post(_base() + "/decisions", json=_exact_request()).status_code == 200
    response = client.get(_base() + "/consistency")
    assert response.status_code == 200, response.text
    body = response.json()
    result = next(
        item for item in body["results"] if item["dataset_field"] == "ATTR_001"
    )
    assert result["consistency_state"] == "contradictory"
    assert result["recommendations_blocked"] is True
    assert result["checks"]["datatype"]["state"] == "contradictory"
    assert result["checks"]["ordinary_range"]["state"] == "contradictory"
    assert result["checks"]["special_values"]["state"] == "contradictory"
    assert result["observed_undefined_special_codes"] == ["-20"]
    assert body["summary"]["contradictory_recommendations_blocked"] is True
    assert runtime.binding_runtime.operational.batch_calls == [("ATTR_001",)]


def test_provider_special_at_observed_bound_is_not_reported_unused() -> None:
    runtime, _candidates, _binding_service = _runtime(
        observed_summary_provider=_observed_summary(observed_min=-9)
    )
    client = _client(runtime)
    assert client.post(_base() + "/decisions", json=_exact_request()).status_code == 200
    response = client.get(_base() + "/consistency")
    assert response.status_code == 200, response.text
    result = next(
        item for item in response.json()["results"] if item["dataset_field"] == "ATTR_001"
    )
    assert result["consistency_state"] == "consistent"
    assert result["observed_unused_special_codes"] == []


def test_consistency_uses_only_exact_persisted_summaries(monkeypatch) -> None:
    runtime, _candidates, _binding_service = _runtime()
    schema = [
        {"name": "ATTR_001", "dtype": "numeric", "min": 0, "max": 900},
        {"name": "LOCAL_ONLY", "dtype": "numeric", "min": 0, "max": 1},
    ]
    calls: list[tuple[object, ...]] = []

    class ExactDatasets:
        def get_version(self, version_id):  # type: ignore[no-untyped-def]
            calls.append(("version", version_id))
            return {
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
                "schema_json": {"columns": schema},
                "profile_json": {"schema": schema},
            }

    class ExactSpecialReviews:
        def get_exact(self, project_id, dataset_id, version_id):  # type: ignore[no-untyped-def]
            calls.append(("special", project_id, dataset_id, version_id))
            return {
                "activation_revision": 3,
                "predictor_authorization_id": "predictor-auth-router",
                "target_contract_id": "target-contract-router",
                "detection_json": {
                    "structural_scope": "full_governed_population_predictors_only",
                    "final_holdout_accessed": False,
                    "variables": [
                        {
                            "variable": "ATTR_001",
                            "datatype": "int64",
                            "special_values": [],
                        },
                        {
                            "variable": "LOCAL_ONLY",
                            "datatype": "int64",
                            "special_values": [],
                        },
                    ],
                },
            }

    fake_persistence = SimpleNamespace(
        datasets=ExactDatasets(), special_value_reviews=ExactSpecialReviews()
    )
    monkeypatch.setattr(
        "server.bureau_metadata.crosswalk_router.get_persistence_service",
        lambda: fake_persistence,
    )
    client = _client(runtime)
    assert client.post(_base() + "/decisions", json=_exact_request()).status_code == 200
    response = client.get(_base() + "/consistency")
    assert response.status_code == 200, response.text
    exact = next(
        item for item in response.json()["results"] if item["dataset_field"] == "ATTR_001"
    )
    assert exact["consistency_state"] == "consistent_with_observed_unused_codes"
    assert exact["raw_rows_accessed"] is False
    assert exact["browser_preview_used"] is False
    assert exact["final_holdout_accessed"] is False
    assert calls == [
        ("version", VERSION_ID),
        ("special", PROJECT_ID, DATASET_ID, VERSION_ID),
    ]


def test_consistency_fails_closed_on_special_summary_lineage_conflict(monkeypatch) -> None:
    runtime, _candidates, _binding_service = _runtime()
    schema = [{"name": "ATTR_001", "dtype": "numeric", "min": 0, "max": 900}]
    fake_persistence = SimpleNamespace(
        datasets=SimpleNamespace(
            get_version=lambda _version_id: {
                "dataset_id": DATASET_ID,
                "schema_json": {"columns": schema},
                "profile_json": {"schema": schema},
            }
        ),
        special_value_reviews=SimpleNamespace(
            get_exact=lambda *_args: {
                "activation_revision": 999,
                "predictor_authorization_id": "predictor-auth-router",
                "target_contract_id": "target-contract-router",
                "detection_json": {},
            }
        ),
    )
    monkeypatch.setattr(
        "server.bureau_metadata.crosswalk_router.get_persistence_service",
        lambda: fake_persistence,
    )
    client = _client(runtime)
    assert client.post(_base() + "/decisions", json=_exact_request()).status_code == 200
    response = client.get(_base() + "/consistency")
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "bureau_crosswalk_state_conflict",
        "message": "The exact crosswalk authority changed or is contradictory.",
    }


def test_current_history_and_optimistic_revision_are_exact() -> None:
    runtime, _candidates, _binding_service = _runtime()
    client = _client(runtime)
    first = client.post(_base() + "/decisions", json=_exact_request())
    assert first.status_code == 200
    current = client.get(_base() + "/current")
    history = client.get(_base() + "/history")
    assert current.status_code == 200
    assert current.json()["governance"]["revision"] == 1
    assert history.status_code == 200
    assert history.json()["total_revisions"] == 1

    stale = client.post(_base() + "/decisions", json=_exact_request())
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "bureau_crosswalk_state_conflict"

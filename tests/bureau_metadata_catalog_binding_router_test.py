from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import tempfile

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from server.bureau_metadata import catalog_binding_repository as repository_module
from server.bureau_metadata import catalog_binding_router
from server.bureau_metadata.catalog_registry import CatalogRegistryNotFoundError
from server.bureau_metadata.catalog_service import BureauCatalogAccessDeniedError
from server.bureau_metadata.crosswalk_governance_repository import (
    CROSSWALK_DATABASE_RELATIVE,
)
from server.bureau_metadata.operational_service import get_operational_catalog_service
from server.bureau_metadata.types import BureauCatalogKey
from server.security.security_store import require_user


PROJECT_ID = "project-binding-router"
DATASET_ID = "dataset-binding-router"
DATASET_VERSION_ID = "dataset-version-binding-router"
ACTIVATION_REVISION = 7
SCHEMA_CHECKSUM = "a" * 64
CATALOG_CHECKSUM_1 = "b" * 64
CATALOG_CHECKSUM_2 = "c" * 64
CATALOG_VERSION_1 = "catalog-binding-router-v1"
CATALOG_VERSION_2 = "catalog-binding-router-v2"
TARGET_CONTRACT_ID = "target-contract-binding-router"
PREDICTOR_AUTHORIZATION_ID = "predictor-auth-binding-router"
ANALYST_RATIONALE = "The exact synthetic catalog applies to this dataset version."


@dataclass(frozen=True)
class FakeVersion:
    catalog_version_id: str
    normalized_catalog_checksum: str
    source_release_version: str
    registry_revision: int
    provider_name: str = "Synthetic Bureau"
    product_name: str = "Synthetic Credit Dictionary"
    edition: str = "Test"
    installation_status: str = "installed"
    integrity_status: str = "verified"
    retired_status: str = "active"
    special_value_definition_count: int = 5

    @property
    def key(self) -> BureauCatalogKey:
        return BureauCatalogKey(
            provider=self.provider_name,
            product=self.product_name,
            edition=self.edition,
            dictionary_version=self.source_release_version,
        )


@dataclass(frozen=True)
class FakeEntitlement:
    entitlement_id: str
    expires_at: str | None = None


class FakeRegistry:
    def __init__(self) -> None:
        self.versions = {
            CATALOG_VERSION_1: FakeVersion(
                catalog_version_id=CATALOG_VERSION_1,
                normalized_catalog_checksum=CATALOG_CHECKSUM_1,
                source_release_version="1.0",
                registry_revision=3,
            ),
            CATALOG_VERSION_2: FakeVersion(
                catalog_version_id=CATALOG_VERSION_2,
                normalized_catalog_checksum=CATALOG_CHECKSUM_2,
                source_release_version="2.0",
                registry_revision=4,
                special_value_definition_count=8,
            ),
        }
        self.deny_entitlement = False
        self.get_version_calls: list[str] = []
        self.audits: list[dict[str, Any]] = []

    def get_version(self, catalog_version_id: str) -> FakeVersion:
        self.get_version_calls.append(catalog_version_id)
        try:
            return self.versions[catalog_version_id]
        except KeyError as exc:
            raise CatalogRegistryNotFoundError(
                "Synthetic exact catalog is unavailable."
            ) from exc

    def get_version_for_exact_catalog(
        self,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
    ) -> FakeVersion:
        for version in self.versions.values():
            if (
                version.key == catalog_key
                and version.normalized_catalog_checksum == catalog_checksum
            ):
                return version
        raise CatalogRegistryNotFoundError(
            "Synthetic exact catalog is unavailable."
        )

    def entitlement_for(self, **kwargs: Any) -> FakeEntitlement:
        if self.deny_entitlement:
            raise BureauCatalogAccessDeniedError("Synthetic entitlement denial.")
        assert kwargs["operation"] == "crosswalk_candidate"
        version_id = str(kwargs["catalog_version_id"])
        assert version_id in self.versions
        tenant = str(kwargs.get("tenant_id") or "none")
        return FakeEntitlement(
            entitlement_id=f"entitlement-{version_id}-{tenant}"
        )

    def record_access_audit(self, **kwargs: Any) -> None:
        self.audits.append(dict(kwargs))


@dataclass(frozen=True)
class FakeOperationalService:
    root: Path
    registry: FakeRegistry


class FakePredictorAuthorizations:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def get_current_exact(
        self,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
    ) -> dict[str, Any]:
        self.calls.append((project_id, dataset_id, dataset_version_id))
        return {"synthetic": "predictor-authorization"}


@dataclass
class RouterEnvironment:
    client: TestClient
    root: Path
    registry: FakeRegistry
    active_identity: dict[str, Any]
    project_access: dict[str, bool]
    predictor_authorizations: FakePredictorAuthorizations
    documentation_calls: list[dict[str, Any]]

    @property
    def base_url(self) -> str:
        return (
            f"/api/projects/{PROJECT_ID}/datasets/{DATASET_ID}/versions/"
            f"{DATASET_VERSION_ID}/bureau-metadata/binding"
        )

    @property
    def database_path(self) -> Path:
        return self.root / CROSSWALK_DATABASE_RELATIVE


def test_linked_crosswalk_summary_projects_exact_counts_and_special_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_key = BureauCatalogKey(
        provider="Synthetic Bureau",
        product="Synthetic Credit Dictionary",
        edition="Test",
        dictionary_version="1.0",
    )
    identity = SimpleNamespace(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        activation_revision=ACTIVATION_REVISION,
        target_contract_id=TARGET_CONTRACT_ID,
        predictor_authorization_id=PREDICTOR_AUTHORIZATION_ID,
        schema_checksum=SCHEMA_CHECKSUM,
        catalog_key=catalog_key,
        catalog_checksum=CATALOG_CHECKSUM_1,
        catalog_version_id=CATALOG_VERSION_1,
    )
    lineage = SimpleNamespace(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        activation_revision=ACTIVATION_REVISION,
        target_contract_id=TARGET_CONTRACT_ID,
        predictor_authorization_id=PREDICTOR_AUTHORIZATION_ID,
        schema_checksum=SCHEMA_CHECKSUM,
        catalog_key=catalog_key,
        catalog_checksum=CATALOG_CHECKSUM_1,
    )
    decisions = (
        SimpleNamespace(
            mapping_state="exact_verified",
            analyst_confirmed=True,
            candidate_attribute_code="ATTR_A",
        ),
        SimpleNamespace(
            mapping_state="probable_review_required",
            analyst_confirmed=False,
            candidate_attribute_code="ATTR_B",
        ),
        SimpleNamespace(
            mapping_state="unresolved",
            analyst_confirmed=False,
            candidate_attribute_code=None,
        ),
    )
    governance = SimpleNamespace(
        governance_id="crosswalk-synthetic",
        revision=2,
        lineage=lineage,
        decisions=decisions,
    )

    class FakeCrosswalkRepository:
        def __init__(self, _root: Path) -> None:
            pass

        def get_revision(self, governance_id: str, revision: int) -> Any:
            assert (governance_id, revision) == ("crosswalk-synthetic", 2)
            return governance

    batch_calls: list[dict[str, Any]] = []

    def mapped_batch(**kwargs: Any) -> dict[str, Any]:
        batch_calls.append(kwargs)
        return {
            "catalog_version_id": CATALOG_VERSION_1,
            "catalog_checksum": CATALOG_CHECKSUM_1,
            "requested": 1,
            "returned": 1,
            "bounded": True,
            "attributes": [
                {
                    "attribute_code": "ATTR_A",
                    "special_values_total": 5,
                    "special_values": [{"value_code": "-9"}],
                    "special_values_truncated": True,
                }
            ],
        }

    monkeypatch.setattr(
        catalog_binding_router,
        "SQLiteGovernedCrosswalkRepository",
        FakeCrosswalkRepository,
    )
    runtime = SimpleNamespace(
        operational=SimpleNamespace(
            root=Path("synthetic-restricted-root"),
            get_mapped_attribute_batch=mapped_batch,
        ),
        context=SimpleNamespace(
            principal_id="synthetic-analyst",
            tenant_id="synthetic-tenant",
        ),
    )
    record = SimpleNamespace(
        crosswalk_id="crosswalk-synthetic",
        crosswalk_revision=2,
        identity=identity,
    )

    result = catalog_binding_router._binding_mapping_counts(runtime, record)

    assert result == {
        "authoritative": 1,
        "review_required": 1,
        "unresolved": 1,
        "special_definitions": 5,
    }
    assert batch_calls[0]["attribute_codes"] == ("ATTR_A",)


def test_linked_crosswalk_summary_fails_closed_when_revision_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingCrosswalkRepository:
        def __init__(self, _root: Path) -> None:
            pass

        def get_revision(self, _governance_id: str, _revision: int) -> Any:
            raise catalog_binding_router.CrosswalkGovernanceNotFoundError(
                "synthetic missing crosswalk"
            )

    monkeypatch.setattr(
        catalog_binding_router,
        "SQLiteGovernedCrosswalkRepository",
        MissingCrosswalkRepository,
    )
    runtime = SimpleNamespace(
        operational=SimpleNamespace(root=Path("synthetic-restricted-root"))
    )
    record = SimpleNamespace(
        crosswalk_id="crosswalk-missing",
        crosswalk_revision=1,
        identity=SimpleNamespace(),
    )

    with pytest.raises(catalog_binding_router.CatalogBindingStateError):
        catalog_binding_router._binding_mapping_counts(runtime, record)


@pytest.fixture
def make_environment(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
):
    environments: list[RouterEnvironment] = []
    hermetic_root = os.environ.get("ATLAS_HERMETIC_ROOT")
    if hermetic_root:
        fixture_root = (
            Path(hermetic_root)
            / "authorities"
            / "catalog-binding-router-tests"
            / request.node.name
        )
        fixture_root.mkdir(parents=True, exist_ok=False)
    else:
        fixture_root = Path(
            tempfile.mkdtemp(prefix="atlas-binding-router-test-")
        )

    def factory(*, tenant_id: str | None = "tenant-binding-router") -> RouterEnvironment:
        root = fixture_root / f"restricted-{len(environments)}"
        root.mkdir()

        def validate_exact_test_root(value: object, **_kwargs: Any) -> Path:
            candidate = Path(str(value)).resolve(strict=True)
            if candidate != root.resolve(strict=True):
                raise AssertionError(
                    "Only the exact synthetic restricted root is permitted."
                )
            return candidate

        monkeypatch.setattr(
            repository_module,
            "validate_restricted_metadata_root",
            validate_exact_test_root,
        )

        registry = FakeRegistry()
        operational = FakeOperationalService(root=root, registry=registry)
        active_identity: dict[str, Any] = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": DATASET_VERSION_ID,
            "activation_revision": ACTIVATION_REVISION,
            "dataset_schema_hash": SCHEMA_CHECKSUM,
        }
        project_access = {PROJECT_ID: True}
        predictor_authorizations = FakePredictorAuthorizations()
        documentation_calls: list[dict[str, Any]] = []

        def authorize_project(
            _user: dict[str, Any], project_id: str, _permission: str
        ) -> str:
            if project_access.get(project_id) is not True:
                raise PermissionError("Synthetic project denial.")
            return project_id

        def active_dataset(
            project_id: str,
            *,
            user: dict[str, Any],
            require_artifact: bool,
        ) -> dict[str, Any]:
            del user
            assert project_id == PROJECT_ID
            assert require_artifact is True
            return dict(active_identity)

        def verify_authorization(
            record: dict[str, Any] | None,
            *,
            project_id: str,
            dataset_id: str,
            dataset_version_id: str,
        ) -> dict[str, Any]:
            assert record == {"synthetic": "predictor-authorization"}
            assert (project_id, dataset_id, dataset_version_id) == (
                PROJECT_ID,
                DATASET_ID,
                DATASET_VERSION_ID,
            )
            return {
                "target_contract_id": TARGET_CONTRACT_ID,
                "predictor_authorization_id": PREDICTOR_AUTHORIZATION_ID,
            }

        monkeypatch.setattr(
            catalog_binding_router, "authorize_modeling_scope", authorize_project
        )
        monkeypatch.setattr(
            catalog_binding_router,
            "durable_active_dataset_identity",
            active_dataset,
        )
        monkeypatch.setattr(
            catalog_binding_router,
            "get_persistence_service",
            lambda: SimpleNamespace(
                predictor_authorizations=predictor_authorizations
            ),
        )
        monkeypatch.setattr(
            catalog_binding_router,
            "verify_durable_predictor_authorization",
            verify_authorization,
        )
        def record_documentation(**kwargs: Any) -> dict[str, str]:
            documentation_calls.append(dict(kwargs))
            binding = kwargs["binding"]
            return {
                "evidence_id": f"evidence-{binding.binding_id}-r{binding.revision}",
                "documentation_package_id": (
                    f"documentation-{binding.binding_id}-r{binding.revision}"
                ),
            }

        monkeypatch.setattr(
            catalog_binding_router,
            "record_binding_evidence_and_documentation",
            record_documentation,
        )

        user: dict[str, Any] = {"userId": "analyst-binding-router"}
        if tenant_id is not None:
            user["tenantId"] = tenant_id
        app = FastAPI()
        app.include_router(catalog_binding_router.router, prefix="/api")
        app.dependency_overrides[require_user] = lambda: dict(user)
        app.dependency_overrides[get_operational_catalog_service] = lambda: operational
        environment = RouterEnvironment(
            client=TestClient(app),
            root=root,
            registry=registry,
            active_identity=active_identity,
            project_access=project_access,
            predictor_authorizations=predictor_authorizations,
            documentation_calls=documentation_calls,
        )
        environments.append(environment)
        return environment

    yield factory

    for environment in environments:
        environment.client.close()


def _catalog_payload(version: int = 1) -> dict[str, Any]:
    if version == 1:
        return {
            "catalog_version_id": CATALOG_VERSION_1,
            "catalog_checksum": CATALOG_CHECKSUM_1,
        }
    return {
        "catalog_version_id": CATALOG_VERSION_2,
        "catalog_checksum": CATALOG_CHECKSUM_2,
    }


def _preview(environment: RouterEnvironment, version: int = 1) -> dict[str, Any]:
    response = environment.client.post(
        environment.base_url + "/preview", json=_catalog_payload(version)
    )
    assert response.status_code == 200, response.text
    return response.json()["preview"]


def _confirm(
    environment: RouterEnvironment,
    preview: dict[str, Any],
    *,
    version: int = 1,
    rationale: str = ANALYST_RATIONALE,
):
    return environment.client.post(
        environment.base_url + "/confirm",
        json={
            **_catalog_payload(version),
            "expected_revision": preview["expected_revision"],
            "preview_checksum": preview["preview_checksum"],
            "analyst_rationale": rationale,
        },
    )


def test_missing_get_and_preview_do_not_create_binding_authority(
    make_environment,
) -> None:
    environment = make_environment()

    missing = environment.client.get(environment.base_url)
    assert missing.status_code == 404
    assert not environment.database_path.exists()

    preview = _preview(environment)
    assert preview["expected_revision"] == 0
    assert preview["current"] is False
    assert preview["stale"] is False
    assert len(preview["preview_checksum"]) == 64
    assert preview["identity"]["activation_revision"] == ACTIVATION_REVISION
    assert preview["identity"]["schema_checksum"] == SCHEMA_CHECKSUM
    assert preview["identity"]["target_contract_id"] == TARGET_CONTRACT_ID
    assert (
        preview["identity"]["predictor_authorization_id"]
        == PREDICTOR_AUTHORIZATION_ID
    )
    assert preview["impact"] == {
        "dataset_mutated": False,
        "target_contract_mutated": False,
        "treatment_mutated": False,
        "predictor_authorization_mutated": False,
        "analysis_partition_mutated": False,
        "feature_manifest_mutated": False,
    }
    assert not environment.database_path.exists()


def test_confirm_persists_exact_revision_and_get_recovers_frontend_envelope(
    make_environment,
) -> None:
    environment = make_environment()
    preview = _preview(environment)

    confirmed = _confirm(environment, preview)
    assert confirmed.status_code == 200, confirmed.text
    payload = confirmed.json()
    assert payload["ok"] is True
    assert payload["binding"]["revision"] == 1
    assert payload["binding"]["status"] == "active"
    assert payload["binding"]["identity"] == preview["identity"]
    assert payload["summary"]["current"] is True
    assert payload["summary"]["stale"] is False
    assert payload["summary"]["integrity_state"] == "verified"
    assert payload["summary"]["evidence_count"] == 4
    assert payload["documentation"]["bounded_project_references_only"] is True
    assert payload["documentation"]["provider_catalog_embedded"] is False
    assert len(environment.documentation_calls) == 1
    assert environment.documentation_calls[0]["actor_id"] == "analyst-binding-router"
    assert environment.documentation_calls[0]["mapping_counts"] == {
        "authoritative": 0,
        "review_required": 0,
        "unresolved": 0,
        "special_definitions": 0,
    }
    assert environment.database_path.is_file()

    recovered = environment.client.get(environment.base_url)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["binding"] == payload["binding"]


def test_bad_preview_checksum_fails_without_persisting(
    make_environment,
) -> None:
    environment = make_environment()
    preview = _preview(environment)
    preview["preview_checksum"] = "0" * 64

    response = _confirm(environment, preview)
    assert response.status_code == 412
    assert not environment.database_path.exists()


def test_confirmation_withholds_success_until_bounded_documentation_persists(
    make_environment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = make_environment()
    preview = _preview(environment)

    def fail_documentation(**_kwargs: Any) -> dict[str, str]:
        raise RuntimeError("synthetic documentation persistence failure")

    monkeypatch.setattr(
        catalog_binding_router,
        "record_binding_evidence_and_documentation",
        fail_documentation,
    )
    failed = _confirm(environment, preview)
    assert failed.status_code == 503
    # The immutable binding revision is durable, but the endpoint has not
    # reported confirmation success.
    current = environment.client.get(environment.base_url)
    assert current.status_code == 200
    assert current.json()["binding"]["revision"] == 1

    monkeypatch.setattr(
        catalog_binding_router,
        "record_binding_evidence_and_documentation",
        lambda **kwargs: {
            "evidence_id": f"evidence-{kwargs['binding'].binding_id}-r1",
            "documentation_package_id": (
                f"documentation-{kwargs['binding'].binding_id}-r1"
            ),
        },
    )
    recovered = _confirm(environment, preview)
    assert recovered.status_code == 200
    assert recovered.json()["binding"]["revision"] == 1
    assert recovered.json()["documentation"]["bounded_project_references_only"] is True


def test_confirm_recomputes_preview_against_current_exact_lineage(
    make_environment,
) -> None:
    environment = make_environment()
    preview = _preview(environment)
    environment.active_identity["dataset_schema_hash"] = "d" * 64

    response = _confirm(environment, preview)
    assert response.status_code == 412
    assert response.json()["detail"]["code"] == "bureau_metadata_binding_preview_stale"
    assert not environment.database_path.exists()


def test_dataset_authority_failure_does_not_leak_resource_detail(
    make_environment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = make_environment()

    def unavailable(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise HTTPException(
            status_code=404,
            detail="private synthetic dataset authority detail",
        )

    monkeypatch.setattr(
        catalog_binding_router, "durable_active_dataset_identity", unavailable
    )
    response = environment.client.post(
        environment.base_url + "/preview", json=_catalog_payload()
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "bureau_metadata_binding_state_conflict"
    assert "private synthetic" not in response.text
    assert environment.registry.get_version_calls == []
    assert not environment.database_path.exists()


def test_project_denial_precedes_dataset_and_catalog_reads(make_environment) -> None:
    environment = make_environment()
    environment.project_access[PROJECT_ID] = False

    response = environment.client.post(
        environment.base_url + "/preview", json=_catalog_payload()
    )
    assert response.status_code == 403
    assert environment.registry.get_version_calls == []
    assert environment.predictor_authorizations.calls == []
    assert not environment.database_path.exists()


def test_exact_active_dataset_contradiction_fails_before_catalog_read(
    make_environment,
) -> None:
    environment = make_environment()
    environment.active_identity["dataset_version_id"] = "different-version"

    response = environment.client.post(
        environment.base_url + "/preview", json=_catalog_payload()
    )
    assert response.status_code == 409
    assert environment.registry.get_version_calls == []
    assert not environment.database_path.exists()


def test_entitlement_denial_is_generic_and_nonpersistent(make_environment) -> None:
    environment = make_environment()
    environment.registry.deny_entitlement = True

    response = environment.client.post(
        environment.base_url + "/preview", json=_catalog_payload()
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "bureau_metadata_binding_access_denied"
    assert CATALOG_VERSION_1 not in detail["message"]
    assert not environment.database_path.exists()


def test_identical_confirm_retry_is_idempotent_but_changed_review_conflicts(
    make_environment,
) -> None:
    environment = make_environment()
    preview = _preview(environment)

    first = _confirm(environment, preview)
    retry = _confirm(environment, preview)
    assert first.status_code == retry.status_code == 200
    assert retry.json()["binding"]["revision"] == 1
    assert (
        retry.json()["binding"]["revision_checksum"]
        == first.json()["binding"]["revision_checksum"]
    )

    changed = _confirm(
        environment,
        preview,
        rationale="A materially different synthetic analyst rationale.",
    )
    assert changed.status_code == 409
    recovered = environment.client.get(environment.base_url)
    assert recovered.json()["binding"]["revision"] == 1


def test_catalog_change_appends_one_scope_history_revision(make_environment) -> None:
    environment = make_environment()
    first_preview = _preview(environment)
    first = _confirm(environment, first_preview)
    assert first.status_code == 200

    second_preview = _preview(environment, version=2)
    assert second_preview["expected_revision"] == 1
    assert second_preview["stale"] is True
    second = _confirm(environment, second_preview, version=2)
    assert second.status_code == 200, second.text
    assert second.json()["binding"]["revision"] == 2
    assert (
        second.json()["binding"]["binding_id"]
        == first.json()["binding"]["binding_id"]
    )
    assert (
        second.json()["binding"]["identity"]["catalog_version_id"]
        == CATALOG_VERSION_2
    )

    history = environment.client.get(environment.base_url + "/history")
    assert history.status_code == 200, history.text
    assert history.json()["total_revisions"] == 2
    assert [item["revision"] for item in history.json()["revisions"]] == [1, 2]


def test_optional_tenant_scope_remains_exact_and_restart_recoverable(
    make_environment,
) -> None:
    environment = make_environment(tenant_id=None)
    preview = _preview(environment)
    assert preview["identity"]["tenant_id"] is None

    confirmed = _confirm(environment, preview)
    assert confirmed.status_code == 200, confirmed.text
    recovered = environment.client.get(environment.base_url)
    assert recovered.status_code == 200
    assert recovered.json()["binding"]["identity"]["tenant_id"] is None


def test_responses_do_not_expose_restricted_storage_paths(make_environment) -> None:
    environment = make_environment()
    preview_response = environment.client.post(
        environment.base_url + "/preview", json=_catalog_payload()
    )
    assert preview_response.status_code == 200
    confirmed = _confirm(environment, preview_response.json()["preview"])
    assert confirmed.status_code == 200

    serialized = preview_response.text + confirmed.text
    assert str(environment.root) not in serialized
    assert "crosswalk_governance.sqlite3" not in serialized

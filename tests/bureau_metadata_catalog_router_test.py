from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any
import uuid


_TEST_RUN_ID = uuid.uuid4().hex
_TEST_AUTHORITY_ROOT = Path(tempfile.gettempdir()) / (
    f"atlas-bureau-catalog-router-{_TEST_RUN_ID}"
)
_TEST_AUTHORITY_ROOT.mkdir(parents=True, exist_ok=False)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(
    _TEST_AUTHORITY_ROOT / "checkpoint" / "workflow.json"
)

from server.core import session_checkpoint

session_checkpoint.CHECKPOINT_PATH = Path(
    os.environ["ATLAS_CHECKPOINT_PATH"]
).resolve()
assert session_checkpoint.CHECKPOINT_PATH == Path(
    os.environ["ATLAS_CHECKPOINT_PATH"]
).resolve()

from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest

from server.bureau_metadata import catalog_router
from server.bureau_metadata.catalog_service import BureauCatalogAccessDeniedError
from server.bureau_metadata.operational_service import CatalogSearchPage
from server.security.security_store import require_user


VERSION_ID = "bcv_synthetic_exact_version"
CATALOG_CHECKSUM = "a" * 64
SCHEMA_CHECKSUM = "b" * 64


@dataclass(frozen=True)
class FakeVersion:
    catalog_version_id: str = VERSION_ID
    catalog_id: str = "catalog-synthetic"
    provider_name: str = "Synthetic Bureau"
    product_name: str = "Synthetic Product"
    edition: str = "Synthetic Edition"
    source_release_version: str = "1.0"
    normalized_catalog_checksum: str = CATALOG_CHECKSUM
    registry_revision: int = 3
    retired_status: str = "active"
    integrity_status: str = "verified"

    def public_payload(self) -> dict[str, Any]:
        return {
            "catalog_version_id": self.catalog_version_id,
            "catalog_id": self.catalog_id,
            "provider_name": self.provider_name,
            "product_name": self.product_name,
            "edition": self.edition,
            "source_release_version": self.source_release_version,
            "normalized_catalog_checksum": self.normalized_catalog_checksum,
            "registry_revision": self.registry_revision,
            "retired_status": self.retired_status,
            "integrity_status": self.integrity_status,
            "record_count": 2,
            "special_value_definition_count": 1,
        }


@dataclass(frozen=True)
class FakeEntitlement:
    entitlement_id: str = "bce_synthetic"
    principal_id: str = "reader-synthetic"
    tenant_id: str | None = None
    catalog_version_id: str = VERSION_ID
    catalog_checksum: str = CATALOG_CHECKSUM
    operations: tuple[str, ...] = ("catalog_health",)
    status: str = "active"

    def public_payload(self) -> dict[str, Any]:
        return {
            "entitlement_id": self.entitlement_id,
            "principal_id": self.principal_id,
            "tenant_id": self.tenant_id,
            "catalog_version_id": self.catalog_version_id,
            "catalog_checksum": self.catalog_checksum[:12],
            "operations": list(self.operations),
            "status": self.status,
        }


class FakeRegistry:
    def __init__(self) -> None:
        self.record = FakeVersion()
        self.audits: list[dict[str, Any]] = []
        self.grants: list[dict[str, Any]] = []
        self.revocations: list[str] = []
        self.deny_entitlement = False

    def record_access_audit(self, **kwargs: Any) -> None:
        self.audits.append(dict(kwargs))

    def list_versions(self, *, offset: int, limit: int):
        return (self.record,)[offset : offset + limit]

    def get_version(self, catalog_version_id: str) -> FakeVersion:
        if catalog_version_id != VERSION_ID:
            from server.bureau_metadata.catalog_registry import CatalogRegistryNotFoundError

            raise CatalogRegistryNotFoundError("synthetic unavailable")
        return self.record

    def entitlement_for(self, **kwargs: Any) -> FakeEntitlement:
        if self.deny_entitlement:
            raise BureauCatalogAccessDeniedError("synthetic denied")
        assert kwargs["catalog_version_id"] == VERSION_ID
        assert kwargs["operation"] == "catalog_health"
        return FakeEntitlement(
            principal_id=kwargs["principal_id"],
            tenant_id=kwargs["tenant_id"],
        )

    def get_entitlement(self, entitlement_id: str) -> FakeEntitlement:
        return replace(FakeEntitlement(), entitlement_id=entitlement_id)

    def retire_version(self, catalog_version_id: str, *, actor: str, expected_revision: int):
        assert catalog_version_id == VERSION_ID
        assert expected_revision == self.record.registry_revision
        self.record = replace(
            self.record,
            registry_revision=self.record.registry_revision + 1,
            retired_status="retired",
        )
        return self.record

    def grant_entitlement(self, **kwargs: Any) -> FakeEntitlement:
        self.grants.append(dict(kwargs))
        return FakeEntitlement(
            principal_id=kwargs["principal_id"],
            tenant_id=kwargs["tenant_id"],
            operations=tuple(sorted(kwargs["operations"])),
        )

    def revoke_entitlement(self, entitlement_id: str, *, revoked_by: str) -> FakeEntitlement:
        self.revocations.append(entitlement_id)
        return replace(FakeEntitlement(), entitlement_id=entitlement_id, status="revoked")


class FakeCatalogFoundation:
    def __init__(self) -> None:
        self.crosswalk_calls: list[dict[str, Any]] = []
        self.deny_crosswalk = False

    def build_dataset_crosswalk_candidates_exact(
        self,
        context,
        key,
        checksum,
        fields,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.crosswalk_calls.append(
            {
                "context": context,
                "key": key,
                "checksum": checksum,
                "fields": fields,
                **kwargs,
            }
        )
        if self.deny_crosswalk:
            raise BureauCatalogAccessDeniedError("synthetic denial")
        mappings = [
            {
                "dataset_field": item["field_name"],
                "candidate_attribute_code": "ATTR_A"
                if item["field_name"].casefold() == "attr_a"
                else None,
                "match_status": "exact_dictionary_code_match"
                if item["field_name"].casefold() == "attr_a"
                else "no_supported_match",
                "candidate_only": True,
                "approved_mapping": False,
            }
            for item in fields
        ]
        return {
            "catalog_checksum": checksum,
            "crosswalk_status": "candidate_only",
            "candidate_only": True,
            "approved_mappings": [],
            "governed_feature_set_changed": False,
            "dataset_mutated": False,
            "mappings": mappings,
            "summary": {"synthetic": len(mappings)},
            "crosswalk_checksum": "c" * 64,
        }


class FakeOperationalService:
    def __init__(self) -> None:
        self.registry = FakeRegistry()
        self.catalogs = FakeCatalogFoundation()
        self.loader = SimpleNamespace(clear=lambda: None)
        self.denied_actions: set[str] = set()

    def _allow(self, action: str) -> None:
        if action in self.denied_actions:
            raise BureauCatalogAccessDeniedError("synthetic denial")

    def list_entitled_versions(self, **kwargs: Any) -> dict[str, Any]:
        self._allow("list")
        return {
            "offset": kwargs["offset"],
            "limit": kwargs["limit"],
            "returned": 1,
            "versions": [self.registry.record.public_payload()],
        }

    def catalog_health(self, **kwargs: Any) -> dict[str, Any]:
        self._allow("health")
        return {
            **self.registry.record.public_payload(),
            "catalog_health": {"validation_status": "passed"},
        }

    def search_attributes(self, **kwargs: Any) -> CatalogSearchPage:
        self._allow("search")
        return CatalogSearchPage(
            catalog_version_id=kwargs["catalog_version_id"],
            query=kwargs["query"],
            offset=kwargs["offset"],
            limit=kwargs["limit"],
            returned=1,
            has_more=False,
            results=(
                {
                    "attribute_code": "ATTR_A",
                    "description": "Synthetic attribute description",
                    "numeric_type": "integer",
                },
            ),
        )

    def get_attribute(self, **kwargs: Any) -> dict[str, Any]:
        self._allow("attribute")
        if kwargs["attribute_code"].casefold() != "attr_a":
            from server.bureau_metadata.catalog_service import BureauCatalogLookupError

            raise BureauCatalogLookupError("synthetic unavailable")
        return {
            "catalog_version_id": VERSION_ID,
            "attribute_code": "ATTR_A",
            "description": "Synthetic attribute description",
            "numeric_type": "integer",
        }

    def list_special_values(self, **kwargs: Any) -> dict[str, Any]:
        self._allow("special")
        return {
            "catalog_version_id": VERSION_ID,
            "attribute_code": "ATTR_A",
            "offset": kwargs["offset"],
            "limit": kwargs["limit"],
            "returned": 1,
            "has_more": False,
            "special_values": [
                {
                    "value_code": "98",
                    "meaning": "Synthetic special meaning",
                    "definition_id": "synthetic-definition",
                }
            ],
        }

    def attribute_availability(self, **kwargs: Any) -> dict[str, Any]:
        self._allow("availability")
        return {
            "catalog_version_id": VERSION_ID,
            "attribute_code": "ATTR_A",
            "ordinary_min": "0",
            "ordinary_max": "100",
            "cross_bureau_availability": ["synthetic"],
        }

    def validate_integrity_as_administrator(self, **kwargs: Any) -> dict[str, Any]:
        self._allow("validate")
        return {
            "catalog_version_id": VERSION_ID,
            "integrity_status": "verified",
            "catalog_checksum": CATALOG_CHECKSUM,
        }


@pytest.fixture
def fake_service() -> FakeOperationalService:
    return FakeOperationalService()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, fake_service: FakeOperationalService) -> FastAPI:
    application = FastAPI()
    application.include_router(catalog_router.router, prefix="/api")
    application.dependency_overrides[catalog_router.get_operational_catalog_service] = (
        lambda: fake_service
    )
    application.dependency_overrides[require_user] = lambda: {
        "userId": "admin-synthetic",
        "role": "admin",
        "status": "active",
    }

    def synthetic_require_role(user: dict[str, Any], roles: set[str]) -> None:
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions.")

    monkeypatch.setattr(catalog_router, "require_role", synthetic_require_role)
    monkeypatch.setattr(
        catalog_router,
        "resolve_project_dataset_identity",
        lambda project_id, dataset_id, dataset_version_id, **_kwargs: {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "dataset_schema_hash": SCHEMA_CHECKSUM,
            "project_link": {"link_status": "active"},
        },
    )
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _preview_payload(**updates: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "dataset_id": "dataset-synthetic",
        "dataset_version_id": "version-synthetic",
        "schema_checksum": SCHEMA_CHECKSUM,
        "fields": [
            {"field_name": "ATTR_A", "description": "Synthetic attribute"},
            {"field_name": "target", "non_catalog_field": True},
        ],
        "target_field": "target",
    }
    payload.update(updates)
    return payload


def test_every_catalog_route_declares_its_own_require_user_dependency(app: FastAPI) -> None:
    routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and "bureau-catalog" in route.path
    ]
    assert routes
    for route in routes:
        dependency_calls = {
            dependency.call
            for dependency in route.dependant.dependencies
            if dependency.call is not None
        }
        assert require_user in dependency_calls, route.path


def test_unauthenticated_requests_fail_before_catalog_service(
    app: FastAPI,
    fake_service: FakeOperationalService,
) -> None:
    def unauthenticated():
        raise HTTPException(status_code=401, detail="Authentication required.")

    app.dependency_overrides[require_user] = unauthenticated
    response = TestClient(app).get("/api/bureau-catalogs")
    assert response.status_code == 401
    assert fake_service.registry.audits == []


def test_entitled_lookup_endpoints_are_bounded_and_exact(client: TestClient) -> None:
    versions = client.get("/api/bureau-catalogs?offset=0&limit=25")
    health = client.get(f"/api/bureau-catalogs/{VERSION_ID}/health")
    search = client.get(
        f"/api/bureau-catalogs/{VERSION_ID}/attributes",
        params={"q": "ATTR", "offset": 0, "limit": 25},
    )
    exact = client.get(f"/api/bureau-catalogs/{VERSION_ID}/attributes/attr_a")
    specials = client.get(
        f"/api/bureau-catalogs/{VERSION_ID}/attributes/ATTR_A/special-values",
        params={"offset": 0, "limit": 25},
    )
    availability = client.get(
        f"/api/bureau-catalogs/{VERSION_ID}/attributes/ATTR_A/availability"
    )

    assert [response.status_code for response in (versions, health, search, exact, specials, availability)] == [200] * 6
    assert versions.json()["returned"] == 1
    assert search.json()["results"][0]["attribute_code"] == "ATTR_A"
    assert search.json()["has_more"] is False
    assert exact.json()["attribute"]["attribute_code"] == "ATTR_A"
    assert specials.json()["special_values"][0]["value_code"] == "98"
    assert availability.json()["availability"]["ordinary_max"] == "100"
    serialized = " ".join(response.text for response in (versions, health, search, exact, specials, availability)).casefold()
    assert "restricted_storage_reference" not in serialized
    assert "physical_path" not in serialized


@pytest.mark.parametrize(
    ("path", "params"),
    [
        (f"/api/bureau-catalogs/{VERSION_ID}/attributes", {"q": "x" * 129}),
        (f"/api/bureau-catalogs/{VERSION_ID}/attributes", {"q": "ATTR", "limit": 51}),
        (
            f"/api/bureau-catalogs/{VERSION_ID}/attributes/ATTR_A/special-values",
            {"limit": 101},
        ),
        ("/api/bureau-catalogs", {"limit": 51}),
    ],
)
def test_unbounded_queries_are_rejected_by_transport(
    client: TestClient,
    path: str,
    params: dict[str, Any],
) -> None:
    assert client.get(path, params=params).status_code == 422


def test_non_entitled_user_receives_safe_403_and_bounded_audit(
    client: TestClient,
    fake_service: FakeOperationalService,
) -> None:
    fake_service.denied_actions.add("attribute")
    response = client.get(f"/api/bureau-catalogs/{VERSION_ID}/attributes/ATTR_A")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "bureau_catalog_access_denied"
    audit = fake_service.registry.audits[-1]
    assert audit["result_status"] == "denied_or_failed"
    assert "Synthetic attribute description" not in str(audit)


def test_unknown_exact_attribute_returns_safe_404(client: TestClient) -> None:
    response = client.get(f"/api/bureau-catalogs/{VERSION_ID}/attributes/DOES_NOT_EXIST")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "bureau_catalog_exact_resource_unavailable"


def test_admin_inventory_validate_search_and_retire(
    client: TestClient,
    fake_service: FakeOperationalService,
) -> None:
    inventory = client.get("/api/admin/bureau-catalogs")
    validation = client.post(
        f"/api/admin/bureau-catalogs/{VERSION_ID}/validate",
        json={},
    )
    search = client.get(
        f"/api/admin/bureau-catalogs/{VERSION_ID}/attributes",
        params={"q": "ATTR", "limit": 25},
    )
    exact = client.get(
        f"/api/admin/bureau-catalogs/{VERSION_ID}/attributes/ATTR_A"
    )
    retired = client.post(
        f"/api/admin/bureau-catalogs/{VERSION_ID}/retire",
        json={"expected_revision": 3},
    )
    assert [response.status_code for response in (inventory, validation, search, exact, retired)] == [200] * 5
    assert inventory.json()["catalogs"][0]["catalog_version_id"] == VERSION_ID
    assert validation.json()["verification"]["integrity_status"] == "verified"
    assert search.json()["results"][0]["attribute_code"] == "ATTR_A"
    assert exact.json()["attribute"]["attribute_code"] == "ATTR_A"
    assert retired.json()["catalog"]["retired_status"] == "retired"
    assert fake_service.registry.record.registry_revision == 4


def test_non_admin_is_denied_catalog_administration(app: FastAPI) -> None:
    app.dependency_overrides[require_user] = lambda: {
        "userId": "reader-synthetic",
        "role": "data_scientist",
        "status": "active",
    }
    response = TestClient(app).get("/api/admin/bureau-catalogs")
    assert response.status_code == 403


def test_admin_without_exact_entitlement_receives_safe_403(
    client: TestClient,
    fake_service: FakeOperationalService,
) -> None:
    fake_service.registry.deny_entitlement = True

    response = client.post(
        f"/api/admin/bureau-catalogs/{VERSION_ID}/validate",
        json={},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": {
            "code": "bureau_catalog_access_denied",
            "message": "Bureau catalog access is not authorized.",
        }
    }
    audit = fake_service.registry.audits[-1]
    assert audit["action"] == "catalog_admin_authorization"
    assert audit["result_status"] == "denied_or_failed"
    assert "synthetic denied" not in response.text


def test_admin_grant_and_revoke_are_strict_and_audited(
    client: TestClient,
    fake_service: FakeOperationalService,
) -> None:
    grant = client.post(
        f"/api/admin/bureau-catalogs/{VERSION_ID}/entitlements",
        json={
            "principal_id": "reader-synthetic",
            "tenant_id": None,
            "operations": ["catalog_health", "attribute_lookup"],
        },
    )
    revoke = client.post(
        "/api/admin/bureau-catalog-entitlements/bce_synthetic/revoke",
        json={"reason": "Synthetic acceptance"},
    )
    assert grant.status_code == 200
    assert revoke.status_code == 200
    assert set(grant.json()["entitlement"]["operations"]) == {
        "catalog_health",
        "attribute_lookup",
    }
    assert fake_service.registry.grants[0]["granted_by"] == "admin-synthetic"
    assert fake_service.registry.revocations == ["bce_synthetic"]

    unknown_operation = client.post(
        f"/api/admin/bureau-catalogs/{VERSION_ID}/entitlements",
        json={"principal_id": "reader-synthetic", "operations": ["bulk_export"]},
    )
    extra_field = client.post(
        f"/api/admin/bureau-catalogs/{VERSION_ID}/validate",
        json={"storage_path": "forbidden"},
    )
    assert unknown_operation.status_code == 422
    assert extra_field.status_code == 422


def test_crosswalk_preview_binds_exact_identity_and_never_persists(
    client: TestClient,
    fake_service: FakeOperationalService,
) -> None:
    response = client.post(
        f"/api/projects/project-synthetic/bureau-catalogs/{VERSION_ID}/crosswalk-preview",
        json=_preview_payload(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["identity"] == {
        "project_id": "project-synthetic",
        "dataset_id": "dataset-synthetic",
        "dataset_version_id": "version-synthetic",
        "schema_checksum": SCHEMA_CHECKSUM,
        "catalog_version_id": VERSION_ID,
    }
    assert body["preview_status"] == "candidate_only"
    assert body["persisted"] is False
    assert body["dataset_mutated"] is False
    assert body["governed_feature_set_changed"] is False
    assert body["crosswalk"]["approved_mappings"] == []
    call = fake_service.catalogs.crosswalk_calls[0]
    assert call["context"].project_id == "project-synthetic"
    assert call["context"].principal_id == "admin-synthetic"
    assert call["checksum"] == CATALOG_CHECKSUM


def test_project_access_is_required_before_catalog_crosswalk_entitlement(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: FakeOperationalService,
) -> None:
    def denied_project(*_args: Any, **_kwargs: Any):
        raise HTTPException(status_code=403, detail="Synthetic project denial.")

    monkeypatch.setattr(catalog_router, "resolve_project_dataset_identity", denied_project)
    response = TestClient(app).post(
        f"/api/projects/project-denied/bureau-catalogs/{VERSION_ID}/crosswalk-preview",
        json=_preview_payload(),
    )
    assert response.status_code == 403
    assert fake_service.catalogs.crosswalk_calls == []


def test_project_access_alone_does_not_grant_catalog_crosswalk_access(
    client: TestClient,
    fake_service: FakeOperationalService,
) -> None:
    fake_service.catalogs.deny_crosswalk = True
    response = client.post(
        f"/api/projects/project-synthetic/bureau-catalogs/{VERSION_ID}/crosswalk-preview",
        json=_preview_payload(),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "bureau_catalog_access_denied"


def test_crosswalk_rejects_stale_schema_and_unbounded_or_ambiguous_contracts(
    client: TestClient,
) -> None:
    stale = client.post(
        f"/api/projects/project-synthetic/bureau-catalogs/{VERSION_ID}/crosswalk-preview",
        json=_preview_payload(schema_checksum="d" * 64),
    )
    duplicate = client.post(
        f"/api/projects/project-synthetic/bureau-catalogs/{VERSION_ID}/crosswalk-preview",
        json=_preview_payload(
            fields=[{"field_name": "ATTR_A"}, {"field_name": "attr_a"}],
            target_field=None,
        ),
    )
    extra = client.post(
        f"/api/projects/project-synthetic/bureau-catalogs/{VERSION_ID}/crosswalk-preview",
        json={**_preview_payload(), "rows": [{"ATTR_A": 1}]},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "bureau_crosswalk_schema_identity_conflict"
    assert duplicate.status_code == 422
    assert extra.status_code == 422


def test_router_has_no_bulk_catalog_export_endpoint(app: FastAPI) -> None:
    paths = {
        route.path.casefold()
        for route in app.routes
        if isinstance(route, APIRoute) and "bureau-catalog" in route.path
    }
    assert all("export" not in path and "download" not in path for path in paths)

from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.bureau_metadata.catalog_binding import (
    CatalogBindingEvidenceReference,
    DatasetVersionCatalogIdentity,
    build_catalog_binding_revision,
)
from server.bureau_metadata.catalog_documentation import (
    record_binding_evidence_and_documentation,
)
from server.bureau_metadata.types import BureauCatalogKey


NOW = "2026-08-05T20:00:00Z"


def _binding(*, revision: int = 1, previous_revision_checksum: str | None = None):
    identity = DatasetVersionCatalogIdentity(
        tenant_id="tenant-a",
        project_id="project-a",
        dataset_id="dataset-a",
        dataset_version_id="version-a",
        activation_revision=2,
        schema_checksum="1" * 64,
        target_contract_id="target-a",
        predictor_authorization_id="predictors-a",
        catalog_version_id="catalog-version-a",
        catalog_key=BureauCatalogKey(
            provider="Synthetic Provider",
            product="Synthetic Product",
            edition="Test Edition",
            dictionary_version="1.0",
        ),
        catalog_checksum="2" * 64,
    )
    evidence = tuple(
        CatalogBindingEvidenceReference(
            evidence_id=f"evidence-{kind}",
            evidence_kind=kind,
            authority_id=f"authority-{kind}",
            checksum="3" * 64,
            recorded_at=NOW,
        )
        for kind in (
            "dataset_lineage",
            "catalog_registry",
            "catalog_entitlement",
        )
    )
    return build_catalog_binding_revision(
        identity=identity,
        revision=revision,
        status="active",
        actor_id="actor-a",
        server_recorded_at=NOW,
        evidence=evidence,
        previous_revision_checksum=previous_revision_checksum,
    )


class _CaptureRepository:
    def __init__(self, identity_key: str):
        self.identity_key = identity_key
        self.rows = []

    def upsert(self, record):
        current = next(
            (
                index
                for index, row in enumerate(self.rows)
                if row.get(self.identity_key) == record[self.identity_key]
            ),
            None,
        )
        if current is None:
            self.rows.append(dict(record))
        else:
            self.rows[current] = dict(record)
        return {self.identity_key: record[self.identity_key]}

    def list_for_project(self, project_id):
        return [row for row in self.rows if row.get("project_id") == project_id]


def _service():
    return SimpleNamespace(
        projects=SimpleNamespace(get=lambda project_id: {"project_id": project_id}),
        evidence=_CaptureRepository("evidence_id"),
        documentation=_CaptureRepository("package_id"),
    )


def test_binding_projection_is_bounded_idempotent_and_nonmutating(monkeypatch):
    service = _service()
    monkeypatch.setattr(
        "server.persistence.service.get_persistence_service", lambda: service
    )
    binding = _binding()
    first = record_binding_evidence_and_documentation(
        binding=binding,
        actor_id="actor-a",
        mapping_counts={
            "authoritative": 2,
            "review_required": 3,
            "unresolved": 4,
            "special_definitions_used": 5,
        },
    )
    second = record_binding_evidence_and_documentation(
        binding=binding,
        actor_id="actor-a",
        mapping_counts={
            "authoritative": 2,
            "review_required": 3,
            "unresolved": 4,
            "special_definitions_used": 5,
        },
    )
    assert first == second
    payload = service.evidence.rows[-1]["payload_json"]
    assert payload["binding_revision_checksum"] == binding.revision_checksum
    assert payload["mapping_counts"]["authoritative"] == 2
    assert payload["proprietary_catalog_embedded"] is False
    assert set(payload["mutation_impact"].values()) == {False}
    assert payload["treatment_policy"]["treatment_automatically_applied"] is False
    assert "description" not in str(payload).casefold()
    assert "special_value_definitions.jsonl" not in str(payload).casefold()
    assert service.documentation.rows[-1]["payload_json"][
        "complete_provider_catalog_embedded"
    ] is False


def test_binding_projection_requires_exact_actor(monkeypatch):
    service = _service()
    monkeypatch.setattr(
        "server.persistence.service.get_persistence_service", lambda: service
    )
    with pytest.raises(ValueError, match="actor"):
        record_binding_evidence_and_documentation(
            binding=_binding(), actor_id="another-actor"
        )
    assert service.evidence.rows == []
    assert service.documentation.rows == []


def test_new_revision_stales_only_prior_bureau_metadata_projection(monkeypatch):
    service = _service()
    monkeypatch.setattr(
        "server.persistence.service.get_persistence_service", lambda: service
    )
    first_binding = _binding()
    record_binding_evidence_and_documentation(
        binding=first_binding,
        actor_id="actor-a",
    )
    service.evidence.upsert(
        {
            "evidence_id": "unrelated-analysis-partition-evidence",
            "project_id": "project-a",
            "artifact_type": "analysis_partition",
            "status": "captured",
            "payload_json": {"revision": 1},
        }
    )
    second_binding = _binding(
        revision=2,
        previous_revision_checksum=first_binding.revision_checksum,
    )

    record_binding_evidence_and_documentation(
        binding=second_binding,
        actor_id="actor-a",
    )

    prior = next(
        row
        for row in service.evidence.rows
        if row["evidence_id"].endswith("-r1")
    )
    unrelated = next(
        row
        for row in service.evidence.rows
        if row["evidence_id"] == "unrelated-analysis-partition-evidence"
    )
    prior_doc = next(
        row for row in service.documentation.rows if row["package_id"].endswith("-r1")
    )
    assert prior["status"] == "stale"
    assert prior_doc["status"] == "stale"
    marker = prior["payload_json"]["metadata_staleness"]
    assert marker["scope"] == "bureau_metadata_only"
    assert marker["analysis_partition_invalidated"] is False
    assert marker["feature_manifest_invalidated"] is False
    assert marker["model_artifacts_invalidated"] is False
    assert unrelated["status"] == "captured"
    assert unrelated["payload_json"] == {"revision": 1}

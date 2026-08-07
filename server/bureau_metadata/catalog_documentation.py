"""Bounded Evidence Center and MDD references for bureau metadata governance.

This module deliberately stores project-relevant identities and counts only.
Provider catalog rows, descriptions, bulk special-value definitions, source
paths, and dataset values remain in their own restricted authorities.
"""

from __future__ import annotations

from typing import Any, Mapping

from .catalog_binding import DatasetCatalogBindingRevision


def _nonnegative_count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def bounded_mapping_counts(value: Mapping[str, Any] | None) -> dict[str, int]:
    source = value if isinstance(value, Mapping) else {}
    return {
        "authoritative": _nonnegative_count(source.get("authoritative")),
        "review_required": _nonnegative_count(source.get("review_required")),
        "unresolved": _nonnegative_count(source.get("unresolved")),
        "rejected": _nonnegative_count(source.get("rejected")),
        "special_definitions_used": _nonnegative_count(
            source.get("special_definitions_used")
        ),
        "contradictions": _nonnegative_count(source.get("contradictions")),
    }


def _project_payload(
    binding: DatasetCatalogBindingRevision,
    *,
    mapping_counts: Mapping[str, Any] | None,
    entitlement_verified: bool,
) -> dict[str, Any]:
    identity = binding.identity
    counts = bounded_mapping_counts(mapping_counts)
    return {
        "schema_version": "1.0",
        "record_type": "bureau_metadata_data_acquisition_reference",
        "project_id": identity.project_id,
        "dataset_id": identity.dataset_id,
        "dataset_version_id": identity.dataset_version_id,
        "activation_revision": identity.activation_revision,
        "schema_checksum": identity.schema_checksum,
        "target_contract_id": identity.target_contract_id,
        "predictor_authorization_id": identity.predictor_authorization_id,
        "binding_id": binding.binding_id,
        "binding_revision": binding.revision,
        "binding_revision_checksum": binding.revision_checksum,
        "binding_status": binding.status,
        "catalog_version_id": identity.catalog_version_id,
        "catalog_key": identity.catalog_key.model_dump(mode="json"),
        "catalog_checksum": identity.catalog_checksum,
        "entitlement_verified": bool(entitlement_verified),
        "crosswalk_id": binding.crosswalk_id,
        "crosswalk_revision": binding.crosswalk_revision,
        "mapping_counts": counts,
        "special_value_semantics": {
            "true_nulls_separate": True,
            "ordinary_outliers_separate": True,
            "provider_definitions_require_accepted_mapping": True,
        },
        "treatment_policy": {
            "metadata_informed_treatment": True,
            "treatment_automatically_selected": False,
            "treatment_automatically_applied": False,
            "limitations": (
                "Catalog metadata is advisory until an exact mapping is accepted; "
                "unresolved and stale mappings remain non-authoritative."
            ),
        },
        "mutation_impact": {
            "dataset_mutated": False,
            "target_contract_mutated": False,
            "treatment_mutated": False,
            "predictor_authorization_mutated": False,
            "analysis_partition_mutated": False,
            "feature_manifest_mutated": False,
        },
        "proprietary_catalog_embedded": False,
    }


def _stale_prior_metadata_projections(
    service: Any,
    *,
    binding: DatasetCatalogBindingRevision,
    current_evidence_id: str,
    current_package_id: str,
) -> None:
    """Stale only superseded bureau-metadata evidence and narrative.

    A catalog or crosswalk revision does not invalidate dataset, treatment,
    partition, feature, training, or model authorities.  The bounded marker
    makes that scope explicit while preserving every prior immutable binding
    reference in Evidence Center and MDD history.
    """

    project_id = binding.identity.project_id
    evidence_prefix = f"bureau-binding-{binding.binding_id}-r"
    package_prefix = f"mdd-bureau-{binding.binding_id}-r"
    marker = {
        "reason": "superseded_bureau_metadata_revision",
        "superseded_by_binding_revision": binding.revision,
        "scope": "bureau_metadata_only",
        "analysis_partition_invalidated": False,
        "feature_manifest_invalidated": False,
        "model_artifacts_invalidated": False,
    }
    for existing in service.evidence.list_for_project(project_id):
        evidence_id = str(existing.get("evidence_id") or "")
        if (
            evidence_id == current_evidence_id
            or not evidence_id.startswith(evidence_prefix)
            or existing.get("artifact_type") != "bureau_metadata_catalog_binding"
        ):
            continue
        payload = dict(existing.get("payload_json") or {})
        payload["metadata_staleness"] = marker
        service.evidence.upsert(
            {
                **existing,
                "status": "stale",
                "payload_json": payload,
            }
        )
    for existing in service.documentation.list_for_project(project_id):
        package_id = str(existing.get("package_id") or "")
        payload = dict(existing.get("payload_json") or {})
        if (
            package_id == current_package_id
            or not package_id.startswith(package_prefix)
            or payload.get("section_id") != "data_acquisition.bureau_metadata"
        ):
            continue
        payload["metadata_staleness"] = marker
        service.documentation.upsert(
            {
                **existing,
                "status": "stale",
                "updated_at": binding.server_recorded_at,
                "payload_json": payload,
            }
        )


def record_binding_evidence_and_documentation(
    *,
    binding: DatasetCatalogBindingRevision,
    actor_id: str,
    mapping_counts: Mapping[str, Any] | None = None,
    entitlement_verified: bool = True,
) -> dict[str, str]:
    """Persist bounded exact-version references after a binding revision.

    The binding authority remains the source of truth. Evidence and MDD records
    are deterministic projections, so retrying the same confirmed revision is
    idempotent and cannot create a second semantic authority.
    """

    actor = str(actor_id or "").strip()
    if not actor or actor != binding.actor_id:
        raise ValueError("Binding documentation actor is invalid.")
    from ..persistence.service import get_persistence_service

    service = get_persistence_service()
    if service.projects.get(binding.identity.project_id) is None:
        raise ValueError("The exact project is unavailable for binding evidence.")
    payload = _project_payload(
        binding,
        mapping_counts=mapping_counts,
        entitlement_verified=entitlement_verified,
    )
    evidence_id = f"bureau-binding-{binding.binding_id}-r{binding.revision}"
    package_id = f"mdd-bureau-{binding.binding_id}-r{binding.revision}"
    _stale_prior_metadata_projections(
        service,
        binding=binding,
        current_evidence_id=evidence_id,
        current_package_id=package_id,
    )
    evidence = service.evidence.upsert(
        {
            "evidence_id": evidence_id,
            "project_id": binding.identity.project_id,
            "workflow_type": "predictive_modeling",
            "step_id": "step01",
            "artifact_type": "bureau_metadata_catalog_binding",
            "status": "captured",
            "title": "Bureau Metadata Catalog Binding",
            "summary": (
                "Exact dataset-version catalog binding and governed mapping "
                "limitations recorded without embedding provider catalog content."
            ),
            "source_ref": f"bureau-catalog-binding:{binding.binding_id}:r{binding.revision}",
            "artifact_hash": binding.revision_checksum,
            "created_by": actor,
            "captured_at": binding.server_recorded_at,
            "payload_json": payload,
        }
    )
    documentation = service.documentation.upsert(
        {
            "package_id": package_id,
            "project_id": binding.identity.project_id,
            "package_type": "model_development_document",
            "status": "draft",
            "readiness_score": None,
            "section_count": 1,
            "completed_section_count": 1,
            "created_at": binding.server_recorded_at,
            "updated_at": binding.server_recorded_at,
            "created_by": actor,
            "payload_json": {
                "schema_version": "1.0",
                "section_id": "data_acquisition.bureau_metadata",
                "section_title": "Bureau Metadata and Special-Value Semantics",
                "evidence_id": evidence_id,
                "content": payload,
                "complete_provider_catalog_embedded": False,
            },
        }
    )
    if evidence.get("evidence_id") != evidence_id or documentation.get(
        "package_id"
    ) != package_id:
        raise RuntimeError("Binding evidence or documentation did not persist.")
    return {"evidence_id": evidence_id, "documentation_package_id": package_id}


__all__ = [
    "bounded_mapping_counts",
    "record_binding_evidence_and_documentation",
]

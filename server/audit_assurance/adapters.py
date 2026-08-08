"""Read-only adapters from existing artifact envelopes to evidence references.

Adapters accept already-resolved mappings and an explicit server-side context.
They never import DATASTORE/RESULTS, query persistence, choose first/latest
records, inspect browser state, or mutate the supplied artifact.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contracts import (
    AuditSubjectIdentity,
    EvidenceReference,
    WorkflowStage,
    _exact_identifier,
)


class ExistingArtifactKind(str, Enum):
    DATA_ACQUISITION = "data_acquisition"
    BUREAU_METADATA = "bureau_metadata"
    ANALYSIS_PARTITION = "analysis_partition"
    EDA = "eda"
    FEATURE_ENGINEERING = "feature_engineering"
    VALIDATION_DESIGN = "validation_design"
    MODEL_TRAINING = "model_training"


class ExistingEvidenceContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: AuditSubjectIdentity
    storage_reference: str
    sensitivity: str
    entitlement_policy_id: str
    retention_policy_id: str
    created_by_actor_id: str
    created_at: datetime
    lifecycle_state: str = "current"
    mdd_reference_ids: tuple[str, ...] = ()
    control_reference_ids: tuple[str, ...] = ()
    source_authority: str

    @field_validator("source_authority")
    @classmethod
    def source_must_be_server_authority(cls, value: str) -> str:
        allowed = {
            "artifact_registry",
            "backend_service",
            "dataset_library",
            "decision_registry",
            "durable_database",
            "evidence_graph",
            "model_registry",
        }
        if value not in allowed:
            raise ValueError(
                "Existing-evidence adaptation requires an explicit server authority."
            )
        return value


_STAGE_BY_KIND = {
    ExistingArtifactKind.DATA_ACQUISITION: WorkflowStage.DATA_ACQUISITION,
    # Bureau review and the analysis partition are governed sections of the
    # canonical Data Acquisition workflow stage in the shared wire contract.
    ExistingArtifactKind.BUREAU_METADATA: WorkflowStage.DATA_ACQUISITION,
    ExistingArtifactKind.ANALYSIS_PARTITION: WorkflowStage.DATA_ACQUISITION,
    ExistingArtifactKind.EDA: WorkflowStage.EDA,
    ExistingArtifactKind.FEATURE_ENGINEERING: WorkflowStage.FEATURE_ENGINEERING,
    ExistingArtifactKind.VALIDATION_DESIGN: WorkflowStage.VALIDATION_DESIGN,
    ExistingArtifactKind.MODEL_TRAINING: WorkflowStage.MODEL_TRAINING,
}

_ARTIFACT_ID_FIELDS = {
    ExistingArtifactKind.DATA_ACQUISITION: (
        "data_contract_id",
        "artifact_id",
        "evidence_id",
    ),
    ExistingArtifactKind.BUREAU_METADATA: (
        "special_value_review_id",
        "binding_id",
        "artifact_id",
        "evidence_id",
    ),
    ExistingArtifactKind.ANALYSIS_PARTITION: (
        "analysis_partition_id",
        "partition_id",
        "artifact_id",
    ),
    ExistingArtifactKind.EDA: ("eda_artifact_id", "artifact_id", "evidence_id"),
    ExistingArtifactKind.FEATURE_ENGINEERING: (
        "feature_manifest_id",
        "artifact_id",
    ),
    ExistingArtifactKind.VALIDATION_DESIGN: (
        "validation_design_id",
        "artifact_id",
    ),
    ExistingArtifactKind.MODEL_TRAINING: (
        "training_run_id",
        "artifact_id",
        "evidence_id",
    ),
}

_BLOCKED_EMBEDDED_KEYS = {
    "browser_authorization",
    "browser_state",
    "catalog_entries",
    "catalog_records",
    "catalog_rows",
    "client_authorization",
    "client_state",
    "cookie",
    "cookies",
    "customer_records",
    "dataset_rows",
    "final_holdout_membership",
    "holdout_indexes",
    "holdout_membership",
    "holdout_positions",
    "local_storage",
    "preview_rows",
    "provider_catalog_rows",
    "raw_dataset_rows",
    "raw_rows",
    "restricted_catalog",
    "restricted_catalog_entries",
    "restricted_catalog_content",
    "row_data",
    "sample_rows",
    "sealed_holdout_membership",
    "sealed_holdout_positions",
    "session_storage",
    "token",
    "x_holdout",
    "x_test",
    "y_holdout",
    "y_test",
}


def _walk_forbidden(value: Any, *, path: str = "artifact") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().casefold().replace("-", "_")
            if normalized in _BLOCKED_EMBEDDED_KEYS:
                raise ValueError(
                    f"{path}.{key} contains prohibited raw, holdout, catalog, or client authority content."
                )
            _walk_forbidden(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk_forbidden(item, path=f"{path}[{index}]")


def _containers(artifact: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    values: list[Mapping[str, Any]] = [artifact]
    for key in ("lineage", "identity", "payload", "contract"):
        nested = artifact.get(key)
        if isinstance(nested, Mapping):
            values.append(nested)
    return tuple(values)


def _read(artifact: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for container in _containers(artifact):
        for name in names:
            value = container.get(name)
            if value is not None and str(value).strip():
                return value
    return None


def _assert_exact_subject_matches(
    artifact: Mapping[str, Any],
    subject: AuditSubjectIdentity,
) -> None:
    comparisons = {
        "tenant_id": ("tenant_id",),
        "project_id": ("project_id",),
        "model_id": ("model_id",),
        "model_version_id": ("model_version_id",),
        "dataset_id": ("dataset_id",),
        "dataset_version_id": ("dataset_version_id",),
        "activation_revision": ("activation_revision",),
        "target_contract_id": ("target_contract_id",),
        "target_column": ("target_column",),
        "positive_value": ("positive_value", "target_event_value", "event_value"),
        "negative_value": (
            "negative_value",
            "target_non_event_value",
            "non_event_value",
        ),
        "predictor_authorization_id": ("predictor_authorization_id",),
        "analysis_partition_id": ("analysis_partition_id", "partition_id"),
        "analysis_partition_revision": (
            "analysis_partition_revision",
            "partition_revision",
        ),
        "feature_manifest_id": ("feature_manifest_id",),
        "feature_manifest_revision": ("feature_manifest_revision",),
        "feature_manifest_checksum": ("feature_manifest_checksum",),
        "materialization_id": ("materialization_id", "feature_materialization_id"),
        "validation_design_id": ("validation_design_id",),
        "validation_design_revision": ("validation_design_revision",),
        "training_preflight_id": ("training_preflight_id",),
        "training_job_id": ("training_job_id",),
        "training_run_id": ("training_run_id",),
        "candidate_id": ("candidate_id",),
        "candidate_decision_id": ("candidate_decision_id", "decision_id"),
        "evaluation_package_id": ("evaluation_package_id",),
        "interpretation_package_id": ("interpretation_package_id",),
        "scoring_run_id": ("scoring_run_id",),
        "deployment_id": ("deployment_id",),
        "monitoring_run_id": ("monitoring_run_id", "monitoring_plan_id"),
    }
    for subject_field, names in comparisons.items():
        supplied = _read(artifact, names)
        expected = getattr(subject, subject_field)
        expected_text = "" if expected is None else str(expected).strip()
        if supplied is not None and str(supplied).strip() != expected_text:
            raise ValueError(
                f"Existing artifact {subject_field} contradicts the exact audit subject."
            )


def adapt_existing_evidence(
    kind: ExistingArtifactKind,
    artifact: Mapping[str, Any],
    context: ExistingEvidenceContext,
) -> EvidenceReference:
    """Project one immutable existing artifact into a bounded reference."""

    if not isinstance(artifact, Mapping):
        raise TypeError("Existing artifact must be a read-only mapping.")
    snapshot = deepcopy(artifact)
    _walk_forbidden(snapshot)
    _assert_exact_subject_matches(snapshot, context.subject)

    artifact_id = _read(snapshot, _ARTIFACT_ID_FIELDS[kind])
    artifact_revision = _read(
        snapshot,
        ("artifact_revision", "revision", "contract_revision"),
    )
    artifact_checksum = _read(
        snapshot,
        (
            "artifact_checksum",
            "checksum",
            "source_checksum",
            "assignment_checksum",
            "contract_checksum",
        ),
    )
    evidence_id = _read(snapshot, ("evidence_id", "evidenceId"))
    if artifact_id is None or artifact_revision is None or artifact_checksum is None:
        raise ValueError(
            f"{kind.value} evidence requires its exact artifact ID, revision, and checksum."
        )
    if evidence_id is None:
        evidence_id = f"audit-evidence-{kind.value}-{artifact_id}"
    evidence_id = _exact_identifier(evidence_id, label="evidence_id")

    stage = _STAGE_BY_KIND[kind]
    context.subject.require_for_stage(stage)
    reference = EvidenceReference(
        evidence_id=evidence_id,
        evidence_type=kind.value,
        artifact_id=artifact_id,
        artifact_revision=artifact_revision,
        artifact_checksum=artifact_checksum,
        subject=context.subject,
        producing_workflow_stage=stage,
        bounded_retrieval_reference=context.storage_reference,
        sensitivity_classification=context.sensitivity,
        entitlement_requirement=context.entitlement_policy_id,
        retention_classification=context.retention_policy_id,
        created_by=context.created_by_actor_id,
        created_at=context.created_at,
        current_state=context.lifecycle_state,
        mdd_references=context.mdd_reference_ids,
        control_references=context.control_reference_ids,
    )
    if artifact != snapshot:
        raise RuntimeError("Read-only evidence adaptation mutated its source artifact.")
    return reference


__all__ = [
    "ExistingArtifactKind",
    "ExistingEvidenceContext",
    "adapt_existing_evidence",
]

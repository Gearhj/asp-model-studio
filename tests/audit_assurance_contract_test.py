from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timezone
import inspect
from pathlib import Path
import re

from pydantic import ValidationError
import pytest

import server.audit_assurance.adapters as adapters_module
from server.audit_assurance import (
    AUDIT_ASSURANCE_CONTRACT_VERSION,
    AuditActor,
    AuditEvent,
    AuditPackageManifest,
    AuditSubjectIdentity,
    ControlAssessment,
    EvidenceReference,
    ExistingArtifactKind,
    ExistingEvidenceContext,
    ResourceIdentity,
    WorkflowStage,
    adapt_existing_evidence,
    canonical_json_bytes,
)


SERVER_TIME = datetime(2026, 8, 7, 16, 30, tzinfo=timezone.utc)


def _typescript_contract_body(type_name: str) -> str:
    source = Path("src/lib/auditAssurance.ts").read_text(encoding="utf-8")
    match = re.search(
        rf"export type {re.escape(type_name)} = \{{(?P<body>.*?)\n\}};",
        source,
        flags=re.DOTALL,
    )
    assert match, f"TypeScript contract {type_name} was not found."
    return match["body"]


def _typescript_contract_keys(type_name: str) -> set[str]:
    return set(
        re.findall(
            r"^\s{2}([A-Za-z_][A-Za-z0-9_]*)\??:",
            _typescript_contract_body(type_name),
            re.MULTILINE,
        )
    )


def _digest(character: str) -> str:
    return character * 64


def _subject_payload() -> dict[str, object]:
    return {
        "tenant_id": "tenant-1",
        "project_id": "atlas-project-1",
        "model_id": "model-1",
        "model_version_id": "model-version-1",
        "dataset_id": "ds_heloc-1",
        "dataset_version_id": "v_heloc-1",
        "activation_revision": 3,
        "target_contract_id": "target-contract-1",
        "target_column": "bad_flag",
        "positive_value": 1,
        "negative_value": 0,
        "predictor_authorization_id": "predictor-auth-1",
        "analysis_partition_id": "analysis-partition-1",
        "analysis_partition_revision": 2,
        "feature_manifest_id": "feature-manifest-1",
        "feature_manifest_revision": 4,
        "feature_manifest_checksum": _digest("a"),
        "materialization_id": "materialization-1",
        "validation_design_id": "validation-design-1",
        "validation_design_revision": 2,
        "training_preflight_id": "training-preflight-1",
        "training_job_id": "training-job-1",
        "training_run_id": "training-run-1",
        "candidate_id": "candidate-1",
        "candidate_decision_id": "decision-1",
        "evaluation_package_id": "evaluation-package-1",
        "interpretation_package_id": "interpretation-package-1",
        "scoring_run_id": "scoring-run-1",
        "deployment_id": "deployment-1",
        "monitoring_run_id": "monitoring-run-1",
    }


def _subject(**updates: object) -> AuditSubjectIdentity:
    payload = _subject_payload()
    payload.update(updates)
    return AuditSubjectIdentity(**payload)


def _data_acquisition_subject() -> AuditSubjectIdentity:
    return AuditSubjectIdentity(
        tenant_id="tenant-1",
        project_id="atlas-project-1",
        dataset_id="ds_heloc-1",
        dataset_version_id="v_heloc-1",
        activation_revision=3,
        target_contract_id="target-contract-1",
        target_column="bad_flag",
        positive_value=1,
        negative_value=0,
        predictor_authorization_id="predictor-auth-1",
    )


def _actor(
    *,
    actor_id: str = "actor-1",
    role: str = "internal_audit",
    capacity: str = "human_reviewer",
) -> AuditActor:
    return AuditActor(
        actor_id=actor_id,
        actor_display_name="Bounded reviewer label",
        authenticated_principal=f"principal-{actor_id}",
        actor_role=role,
        acting_capacity=capacity,
        authorization_decision="allowed",
        server_timestamp=SERVER_TIME,
    )


def _event(**updates: object) -> AuditEvent:
    payload: dict[str, object] = {
        "audit_event_id": "audit-event-1",
        "event_type": "data_contract_reviewed",
        "action": "review",
        "resource_type": "data_contract",
        "resource_id": "data-contract-1",
        "subject": _subject(),
        "actor": _actor(),
        "decision_kind": "internal_audit_conclusion",
        "rationale": "The exact governed contract was reviewed.",
        "request_correlation_id": "correlation-1",
        "originating_workflow_stage": WorkflowStage.DATA_ACQUISITION,
        "source_authority": "durable_database",
        "authorization_result": "allowed",
        "server_timestamp": SERVER_TIME,
        "human_readable_summary": "The exact governed contract was reviewed.",
    }
    payload.update(updates)
    return AuditEvent(**payload)


def _evidence_context(
    *,
    subject: AuditSubjectIdentity | None = None,
    source_authority: str = "artifact_registry",
) -> ExistingEvidenceContext:
    return ExistingEvidenceContext(
        subject=subject or _subject(),
        storage_reference="artifact://assurance/reference-1",
        sensitivity="restricted",
        entitlement_policy_id="entitlement-policy-1",
        retention_policy_id="retention-policy-1",
        created_by_actor_id="actor-1",
        created_at=SERVER_TIME,
        lifecycle_state="current",
        mdd_reference_ids=("mdd-reference-1",),
        control_reference_ids=("control-reference-1",),
        source_authority=source_authority,
    )


def _evidence_reference(
    *, evidence_id: str = "evidence-1", artifact_id: str = "data-contract-1"
) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=evidence_id,
        evidence_type="data_acquisition",
        artifact_id=artifact_id,
        artifact_revision=2,
        artifact_checksum=_digest("c"),
        subject=_subject(),
        producing_workflow_stage=WorkflowStage.DATA_ACQUISITION,
        bounded_retrieval_reference="artifact://assurance/data-contract-1",
        sensitivity_classification="restricted",
        entitlement_requirement="entitlement-policy-1",
        retention_classification="retention-policy-1",
        created_by="actor-1",
        created_at=SERVER_TIME,
        current_state="current",
    )


def test_00_python_and_typescript_wire_contract_keys_are_identical() -> None:
    pairs = (
        ("AuditSubjectIdentity", AuditSubjectIdentity),
        ("AuditActor", AuditActor),
        ("AuditEvent", AuditEvent),
        ("EvidenceReference", EvidenceReference),
        ("ControlAssessment", ControlAssessment),
        ("AuditPackageManifest", AuditPackageManifest),
    )
    for type_name, python_contract in pairs:
        assert set(python_contract.model_fields) == _typescript_contract_keys(type_name)
    subject_wire = _typescript_contract_body("AuditSubjectIdentity")
    evidence_wire = _typescript_contract_body("EvidenceReference")
    event_wire = _typescript_contract_body("AuditEvent")
    control_wire = _typescript_contract_body("ControlAssessment")
    assert "tenant_id: string;" in subject_wire
    assert "tenant_id?:" not in subject_wire
    assert "artifact_revision: number;" in evidence_wire
    assert "artifact_revision?:" not in evidence_wire
    assert "source_authority: AuditSourceAuthority;" in event_wire
    assert 'conclusion_role?: Exclude<AuditActorRole, "service">;' in control_wire


def test_01_canonical_audit_identities_serialize_deterministically() -> None:
    payload = _subject_payload()
    reversed_payload = dict(reversed(tuple(payload.items())))
    left = AuditSubjectIdentity(**payload)
    right = AuditSubjectIdentity(**reversed_payload)

    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert left.canonical_checksum() == right.canonical_checksum()
    assert AUDIT_ASSURANCE_CONTRACT_VERSION == "1.0"
    assert "positive_value" in left.model_fields
    assert "target_event_value" not in left.model_fields
    with pytest.raises(ValidationError, match="tenant_id"):
        AuditSubjectIdentity(project_id="atlas-project-1")


def test_02_dataset_display_names_cannot_substitute_for_ids() -> None:
    with pytest.raises(ValidationError, match="dataset_id"):
        _subject(dataset_id="HELOC TRAIN")


def test_03_project_display_names_cannot_substitute_for_ids() -> None:
    with pytest.raises(ValidationError, match="project display name"):
        _subject(project_id="HELOC-Credit-Risk")


def test_04_first_and_latest_fallbacks_are_rejected() -> None:
    with pytest.raises(ValidationError, match="first/latest/browser"):
        _subject(dataset_version_id="v_latest")
    with pytest.raises(ValidationError, match="first/latest/browser"):
        ResourceIdentity(resource_type="dataset", resource_id="first")


def test_05_missing_applicable_stage_identity_fails_closed() -> None:
    incomplete = _subject(
        analysis_partition_id=None,
        analysis_partition_revision=None,
    )
    with pytest.raises(ValidationError, match="analysis_partition"):
        _event(subject=incomplete, originating_workflow_stage=WorkflowStage.EDA)


def test_06_events_preserve_actor_role_action_and_server_timestamp() -> None:
    event = _event()

    assert event.actor.actor_id == "actor-1"
    assert event.actor.actor_role == "internal_audit"
    assert event.action == "review"
    assert event.server_timestamp == SERVER_TIME
    assert event.actor.server_timestamp == SERVER_TIME


def test_07_events_preserve_before_after_revisions_and_checksums() -> None:
    event = _event(
        prior_revision=1,
        new_revision=2,
        before_checksum=_digest("d"),
        after_checksum=_digest("e"),
    )

    assert (event.prior_revision, event.new_revision) == (1, 2)
    assert event.before_checksum == _digest("d")
    assert event.after_checksum == _digest("e")


def test_08_evidence_references_retain_sensitivity_and_entitlement() -> None:
    reference = _evidence_reference()

    assert reference.sensitivity_classification == "restricted"
    assert reference.entitlement_requirement == "entitlement-policy-1"
    assert reference.retention_classification == "retention-policy-1"


def test_09_restricted_catalog_content_is_not_embedded() -> None:
    artifact = {
        "data_contract_id": "data-contract-1",
        "artifact_revision": 1,
        "artifact_checksum": _digest("1"),
        "restricted_catalog_content": [{"provider_definition": "restricted"}],
    }
    with pytest.raises(ValueError, match="prohibited"):
        adapt_existing_evidence(
            ExistingArtifactKind.DATA_ACQUISITION,
            artifact,
            _evidence_context(),
        )


def test_10_raw_dataset_rows_are_not_embedded() -> None:
    artifact = {
        "data_contract_id": "data-contract-1",
        "artifact_revision": 1,
        "artifact_checksum": _digest("2"),
        "payload": {"raw_dataset_rows": [[1, 2, 3]]},
    }
    with pytest.raises(ValueError, match="prohibited"):
        adapt_existing_evidence(
            ExistingArtifactKind.DATA_ACQUISITION,
            artifact,
            _evidence_context(),
        )


def test_11_sealed_holdout_membership_is_not_embedded() -> None:
    artifact = {
        "analysis_partition_id": "analysis-partition-1",
        "artifact_revision": 1,
        "artifact_checksum": _digest("3"),
        "sealed_holdout_membership": [4, 8, 15, 16, 23, 42],
    }
    with pytest.raises(ValueError, match="prohibited"):
        adapt_existing_evidence(
            ExistingArtifactKind.ANALYSIS_PARTITION,
            artifact,
            _evidence_context(),
        )


def test_12_system_observations_cannot_be_human_approval() -> None:
    with pytest.raises(ValidationError, match="human approval"):
        ControlAssessment(
            control_id="control-1",
            audit_profile_id="audit-profile-1",
            audit_profile_version="profile-version-1",
            subject=_subject(),
            assessment_status="effective",
            control_owner_id="service-1",
            assessment_timestamp=SERVER_TIME,
            conclusion_basis="automated_check",
            rationale="The deterministic control passed.",
            current_state="current",
        )


def test_13_developer_actions_cannot_be_independent_validation() -> None:
    with pytest.raises(ValidationError, match="independent_validation"):
        _event(
            actor=_actor(role="developer", capacity="developer"),
            decision_kind="validation_conclusion",
        )


def test_14_control_assessments_distinguish_checks_from_human_conclusions() -> None:
    automated = ControlAssessment(
        control_id="control-automated-1",
        audit_profile_id="audit-profile-1",
        audit_profile_version="profile-version-1",
        subject=_subject(),
        assessment_status="observation_only",
        control_owner_id="service-1",
        assessment_timestamp=SERVER_TIME,
        conclusion_basis="automated_check",
        rationale="A deterministic automated control passed.",
        current_state="current",
    )
    human = ControlAssessment(
        control_id="control-human-1",
        audit_profile_id="audit-profile-1",
        audit_profile_version="profile-version-1",
        subject=_subject(),
        assessment_status="effective",
        evidence_references=(_evidence_reference(),),
        control_owner_id="control-owner-1",
        reviewer_id="reviewer-1",
        assessment_timestamp=SERVER_TIME,
        conclusion_basis="human_review",
        conclusion_role="internal_audit",
        rationale="The reviewer concluded the objective is satisfied.",
        current_state="current",
    )

    assert automated.conclusion_basis == "automated_check"
    assert automated.assessment_status == "observation_only"
    assert automated.reviewer_id is None
    assert human.conclusion_basis == "human_review"
    assert human.assessment_status == "effective"
    assert human.conclusion_role == "internal_audit"


def test_15_manifest_hashing_is_deterministic() -> None:
    references = (
        _evidence_reference(evidence_id="evidence-2", artifact_id="artifact-2"),
        _evidence_reference(evidence_id="evidence-3", artifact_id="artifact-3"),
    )
    left = AuditPackageManifest.build(
        audit_package_id="manifest-1",
        package_revision=1,
        audit_profile_id="audit-profile-1",
        audit_profile_version="profile-version-1",
        subject=_subject(),
        as_of_timestamp=SERVER_TIME,
        included_evidence_references=references,
        excluded_or_redacted_evidence_summary="No evidence was excluded.",
        generated_by="actor-1",
    )
    right = AuditPackageManifest.build(
        audit_package_id="manifest-1",
        package_revision=1,
        audit_profile_id="audit-profile-1",
        audit_profile_version="profile-version-1",
        subject=_subject(),
        as_of_timestamp=SERVER_TIME,
        included_evidence_references=tuple(reversed(references)),
        excluded_or_redacted_evidence_summary="No evidence was excluded.",
        generated_by="actor-1",
    )

    assert left.included_evidence_references == right.included_evidence_references
    assert left.evidence_manifest_checksum == right.evidence_manifest_checksum
    with pytest.raises(ValidationError, match="canonical manifest"):
        AuditPackageManifest(
            **left.model_dump(exclude={"evidence_manifest_checksum"}),
            evidence_manifest_checksum=_digest("f"),
        )


@pytest.mark.parametrize(
    ("kind", "id_field", "artifact_id"),
    (
        (ExistingArtifactKind.DATA_ACQUISITION, "data_contract_id", "data-contract-1"),
        (
            ExistingArtifactKind.BUREAU_METADATA,
            "special_value_review_id",
            "special-value-review-1",
        ),
        (
            ExistingArtifactKind.ANALYSIS_PARTITION,
            "analysis_partition_id",
            "analysis-partition-1",
        ),
        (ExistingArtifactKind.EDA, "eda_artifact_id", "eda-artifact-1"),
        (
            ExistingArtifactKind.FEATURE_ENGINEERING,
            "feature_manifest_id",
            "feature-manifest-1",
        ),
        (
            ExistingArtifactKind.VALIDATION_DESIGN,
            "validation_design_id",
            "validation-design-1",
        ),
        (
            ExistingArtifactKind.MODEL_TRAINING,
            "training_run_id",
            "training-run-1",
        ),
    ),
)
def test_16_existing_artifacts_are_represented_without_mutation(
    kind: ExistingArtifactKind,
    id_field: str,
    artifact_id: str,
) -> None:
    artifact = {
        id_field: artifact_id,
        "artifact_revision": 7,
        "artifact_checksum": _digest("6"),
        "project_id": "atlas-project-1",
        "dataset_id": "ds_heloc-1",
        "dataset_version_id": "v_heloc-1",
        "activation_revision": 3,
        "target_contract_id": "target-contract-1",
        "target_column": "bad_flag",
        "positive_value": 1,
        "negative_value": 0,
        "predictor_authorization_id": "predictor-auth-1",
        "bounded_summary": {"status": "confirmed", "count": 22},
    }
    before = deepcopy(artifact)

    reference = adapt_existing_evidence(kind, artifact, _evidence_context())

    assert artifact == before
    assert reference.artifact_id == artifact_id
    assert reference.artifact_revision == 7
    assert reference.artifact_checksum == _digest("6")
    assert reference.evidence_type == kind.value


def test_17_adapter_has_no_live_authority_resolution_dependencies() -> None:
    tree = ast.parse(inspect.getsource(adapters_module))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert imported_roots.isdisjoint(
        {"requests", "sqlite3", "persistence", "runtime", "storage"}
    )
    exported_names = set(adapters_module.__dict__)
    assert exported_names.isdisjoint(
        {"DATASTORE", "RESULTS", "get_persistence_service", "get_active_identity"}
    )


def test_18_browser_or_client_state_is_never_authorization() -> None:
    with pytest.raises(ValidationError, match="server authority"):
        _evidence_context(source_authority="browser")
    with pytest.raises(ValidationError):
        AuditActor(
            actor_id="actor-2",
            authenticated_principal="principal-2",
            actor_role="analyst",
            acting_capacity="analyst",
            authorization_decision="allowed",
            service_identity_id="browser",
            server_timestamp=SERVER_TIME,
        )

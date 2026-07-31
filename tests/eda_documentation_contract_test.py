"""Governed EDA documentation and confirmation contract tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from server.eda.documentation_service import (
    EDADocumentationService,
    EDADocumentationValidationError,
)
from server.eda.documentation_types import EDADocumentationPayload


PROJECT_ID = "project-eda-docs"


def _evidence(**updates):
    value = {
        "evidenceId": "ev-eda-overview",
        "lineage_contract": "canonical_dataset_version",
        "project_id": PROJECT_ID,
        "dataset_id": "dataset-heloc",
        "dataset_version_id": "heloc-v1",
        "projectId": PROJECT_ID,
        "datasetIds": ["dataset-heloc"],
        "evidenceType": "eda",
        "title": "Stored EDA overview evidence",
        "artifactChecksum": "sha256:server-authoritative",
        "lineage": {
            "project_id": PROJECT_ID,
            "dataset_id": "dataset-heloc",
            "dataset_version_id": "heloc-v1",
            "lineage_contract": "canonical_dataset_version",
            "projectId": PROJECT_ID,
            "datasetId": "dataset-heloc",
            "datasetVersion": "heloc-v1",
        },
    }
    value.update(updates)
    return value


def _context(**updates):
    value = {
        "project_id": PROJECT_ID,
        "dataset_id": "dataset-heloc",
        "dataset_version_id": "heloc-v1",
        "dataset_version": "heloc-v1",
        "target": "bad_flag",
        "predictor_manifest_id": "pm-heloc-v1",
        "authorized_predictors": ["ExternalRiskEstimate", "MSinceOldestTradeOpen"],
        "target_source_exclusions": ["RiskPerformance"],
        "population_rows": 10_459,
        "duplicate_rows": 12,
        "data_revision": 7,
    }
    value.update(updates)
    return value


def _payload(**updates) -> EDADocumentationPayload:
    value = {
        "project_id": PROJECT_ID,
        "dataset_id": "dataset-heloc",
        "dataset_version_id": "heloc-v1",
        "dataset_version": "heloc-v1",
        "target": "bad_flag",
        "predictor_manifest_id": "pm-heloc-v1",
        "eda_analysis_version": "eda-1.1.0",
        "sections": {
            "overview": {
                "population": {"rows": 10_459},
                "target_source_exclusions": ["RiskPerformance"],
                "overall_readiness": "ready",
            },
            "target": {
                "definition": "Bad credit performance maps to bad_flag=1.",
                "event_prevalence": 0.263,
            },
            "predictors": {
                "selected_predictors": [
                    "ExternalRiskEstimate",
                    "MSinceOldestTradeOpen",
                ],
                "notable_findings": [],
            },
            "relationships": {
                "correlation_review": "Reviewed",
                "relationship_decisions": [],
            },
            "stability_and_segments": {
                "analysis_status": "not_available",
                "statement": "No governed observation-time field is available.",
            },
            "findings": {
                "duplicate_treatment": "Retain documented repeated observations.",
                "approved_findings": [],
            },
        },
        "evidence_references": [
            {
                "evidence_id": "ev-eda-overview",
                "title": "EDA overview evidence",
                "checksum": "sha256:abc",
            },
            # Duplicate IDs are canonicalized to one reference.
            {
                "evidence_id": "ev-eda-overview",
                "title": "Duplicate retry",
            },
        ],
        "decisions": [
            {
                "decision_id": "decision-duplicates",
                "category": "duplicates",
                "decision": "Retain",
                "rationale": "Repeated observations are valid.",
                "status": "approved",
            }
        ],
        "performance_metadata": {"workspace_duration_ms": 128},
        "duplicate_decision": "Retain documented repeated observations.",
        "target_source_exclusions": ["RiskPerformance"],
        "unresolved_blocking_findings": [],
        "reviewer_status": "approved",
    }
    value.update(updates)
    return EDADocumentationPayload.model_validate(value)


class EDADocumentationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1] / ".tmp"
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        self.tempdir = tempfile.TemporaryDirectory(dir=workspace_tmp)
        self.context = _context()
        self.evidence = {"ev-eda-overview": _evidence()}
        self.service = EDADocumentationService(
            Path(self.tempdir.name),
            context_provider=lambda _project_id: dict(self.context),
            evidence_provider=lambda evidence_id: self.evidence.get(evidence_id),
        )
        self.user = {
            "userId": "reviewer-17",
            "displayName": "Model Reviewer",
        }
        self.audit_patch = patch(
            "server.eda.documentation_service.audit_event",
            return_value=None,
        )
        self.audit_patch.start()

    def tearDown(self) -> None:
        self.audit_patch.stop()
        self.tempdir.cleanup()

    def test_draft_is_canonical_scoped_and_ready(self) -> None:
        state = self.service.upsert_draft(_payload(), self.user)
        self.assertEqual(state["status"], "ready_for_confirmation")
        self.assertIsNone(state["current_approved"])
        self.assertEqual(
            state["draft"]["governed_context"]["target_source_exclusions"],
            ["RiskPerformance"],
        )
        self.assertEqual(len(state["draft"]["evidence_references"]), 1)
        evidence = state["draft"]["evidence_references"][0]
        self.assertEqual(evidence["title"], "Stored EDA overview evidence")
        self.assertEqual(
            evidence["uri"],
            "/evidence-graph?evidenceId=ev-eda-overview",
        )
        self.assertEqual(
            evidence["checksum"],
            "sha256:server-authoritative",
        )
        self.assertEqual(evidence["evidence_type"], "eda")
        self.assertEqual(state["dataset_version_id"], "heloc-v1")
        self.assertEqual(state["draft"]["dataset_version_id"], "heloc-v1")
        self.assertEqual(state["draft"]["dataset_version"], "heloc-v1")
        self.assertTrue(
            state["draft"]["validation"]["ready_for_confirmation"]
        )

    def test_evidence_reference_requires_exact_canonical_triple(self) -> None:
        invalid_items = {
            "missing": None,
            "legacy-unscoped": {
                "evidenceId": "ev-eda-overview",
                "projectId": PROJECT_ID,
                "datasetIds": ["dataset-heloc"],
            },
            "other-project": _evidence(
                project_id="project-other",
                projectId="project-other",
            ),
            "other-dataset": _evidence(
                dataset_id="dataset-other",
                datasetIds=["dataset-other"],
            ),
            "other-version": _evidence(dataset_version_id="heloc-v2"),
            "contradictory-lineage": _evidence(
                lineage={
                    "project_id": PROJECT_ID,
                    "dataset_id": "dataset-heloc",
                    "dataset_version_id": "heloc-v2",
                },
            ),
        }
        for label, item in invalid_items.items():
            with self.subTest(label=label):
                self.evidence["ev-eda-overview"] = item
                with self.assertRaises(
                    EDADocumentationValidationError
                ) as raised:
                    self.service.upsert_draft(_payload(), self.user)
                self.assertEqual(
                    raised.exception.code,
                    "eda_evidence_context_mismatch",
                )
        self.assertFalse(any(Path(self.tempdir.name).glob("*.json")))

    def test_confirmation_rechecks_evidence_identity_after_draft(self) -> None:
        self.service.upsert_draft(_payload(), self.user)
        self.evidence["ev-eda-overview"] = _evidence(
            dataset_version_id="heloc-v2",
        )
        with self.assertRaises(EDADocumentationValidationError) as raised:
            self.service.confirm(_payload(), self.user)
        self.assertEqual(
            raised.exception.code,
            "eda_evidence_context_mismatch",
        )
        state = self.service.get_state(PROJECT_ID)
        self.assertIsNotNone(state["draft"])
        self.assertIsNone(state["current_approved"])

    def test_state_read_rejects_a_different_expected_version(self) -> None:
        current = self.service.get_state(
            PROJECT_ID,
            expected_dataset_id="dataset-heloc",
            expected_dataset_version_id="heloc-v1",
        )
        self.assertEqual(current["dataset_version_id"], "heloc-v1")
        with self.assertRaises(EDADocumentationValidationError) as raised:
            self.service.get_state(
                PROJECT_ID,
                expected_dataset_id="dataset-heloc",
                expected_dataset_version_id="heloc-v2",
            )
        self.assertEqual(
            raised.exception.code,
            "eda_documentation_context_mismatch",
        )

    def test_legacy_version_alias_is_compare_only(self) -> None:
        with self.assertRaises(EDADocumentationValidationError) as raised:
            self.service.upsert_draft(
                _payload(dataset_version="browser-profile-version"),
                self.user,
            )
        self.assertEqual(
            raised.exception.code,
            "eda_documentation_context_mismatch",
        )

    def test_confirmation_freezes_snapshot_with_server_actor(self) -> None:
        result = self.service.confirm(_payload(), self.user)
        self.assertFalse(result["idempotent"])
        self.assertTrue(result["next_step_eligible"])
        self.assertEqual(result["evidence_ids"], ["ev-eda-overview"])
        self.assertEqual(result["record"]["confirmed_by"], "reviewer-17")
        self.assertEqual(
            result["record"]["confirmed_by_display_name"],
            "Model Reviewer",
        )
        self.assertTrue(result["record"]["confirmed_at"].endswith("+00:00"))
        self.assertEqual(result["documentation_version"], "eda-doc-0001")

        state = self.service.get_state(PROJECT_ID)
        self.assertEqual(state["status"], "confirmed")
        self.assertIsNone(state["draft"])
        self.assertEqual(len(state["history"]), 1)

    def test_identical_confirmation_is_idempotent_and_non_duplicating(self) -> None:
        first = self.service.confirm(_payload(), self.user)
        # Volatile engine timing is recorded, but cannot manufacture a second
        # documentation version for otherwise identical analytical content.
        second = self.service.confirm(
            _payload(performance_metadata={"workspace_duration_ms": 987}),
            self.user,
        )
        self.assertTrue(second["idempotent"])
        self.assertEqual(second["confirmation_id"], first["confirmation_id"])
        self.assertEqual(
            second["documentation_version"],
            first["documentation_version"],
        )
        self.assertEqual(len(self.service.get_state(PROJECT_ID)["history"]), 1)

    def test_new_draft_marks_approval_stale_without_overwriting_it(self) -> None:
        confirmed = self.service.confirm(_payload(), self.user)
        changed = _payload(
            eda_analysis_version="eda-1.1.1",
            sections={
                **_payload().sections.model_dump(),
                "relationships": {
                    "correlation_review": "Changed threshold and reviewed again.",
                    "relationship_decisions": ["retain"],
                },
            },
        )
        state = self.service.upsert_draft(changed, self.user)
        self.assertEqual(state["status"], "stale")
        self.assertEqual(
            state["current_approved"]["confirmation_id"],
            confirmed["confirmation_id"],
        )
        self.assertEqual(
            state["current_approved"]["sections"]["relationships"][
                "correlation_review"
            ],
            "Reviewed",
        )
        self.assertIn("relationships", state["draft"]["changed_sections"])
        self.assertIn(
            "changed after the approved confirmation",
            state["current_approved"]["stale_reason"],
        )

    def test_dataset_version_change_invalidates_and_reopen_restores_state(self) -> None:
        self.service.confirm(_payload(), self.user)
        self.context["dataset_version_id"] = "heloc-v2"
        self.context["dataset_version"] = "heloc-v2"
        self.context["data_revision"] = 8
        stale = self.service.get_state(PROJECT_ID)
        self.assertEqual(stale["status"], "stale")
        self.assertIn(
            "dataset version",
            stale["current_approved"]["stale_reason"],
        )

        reopened = EDADocumentationService(
            Path(self.tempdir.name),
            context_provider=lambda _project_id: dict(self.context),
        ).get_state(PROJECT_ID)
        self.assertEqual(reopened["status"], "stale")
        self.assertEqual(len(reopened["history"]), 1)

    def test_confirmation_validation_is_fail_closed(self) -> None:
        cases = [
            (
                _payload(target_source_exclusions=[]),
                "target-source exclusions",
            ),
            (
                _payload(duplicate_decision="pending"),
                "duplicate-row treatment",
            ),
            (
                _payload(unresolved_blocking_findings=["Leakage decision pending"]),
                "unresolved blocking",
            ),
            (
                _payload(reviewer_status="pending"),
                "Reviewer status",
            ),
        ]
        for payload, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(
                    EDADocumentationValidationError
                ) as raised:
                    self.service.confirm(payload, self.user)
                self.assertEqual(raised.exception.code, "eda_confirmation_blocked")
                self.assertIn(expected.lower(), str(raised.exception).lower())

        with self.assertRaises(EDADocumentationValidationError) as raised:
            self.service.confirm(
                _payload(predictor_manifest_id="pm-stale"),
                self.user,
            )
        self.assertEqual(
            raised.exception.code,
            "eda_documentation_context_mismatch",
        )

    def test_target_source_cannot_reenter_selected_predictors(self) -> None:
        sections = _payload().sections.model_dump()
        sections["predictors"]["selected_predictors"].append(
            "RiskPerformance"
        )
        with self.assertRaises(EDADocumentationValidationError) as raised:
            self.service.confirm(_payload(sections=sections), self.user)
        self.assertIn(
            "not authorized",
            str(raised.exception).lower(),
        )

    def test_explicit_invalidation_is_idempotent(self) -> None:
        self.service.confirm(_payload(), self.user)
        first = self.service.invalidate(
            PROJECT_ID,
            "Correlation threshold changed.",
            self.user,
            upstream_revision="eda-1.1.1",
        )
        second = self.service.invalidate(
            PROJECT_ID,
            "Correlation threshold changed.",
            self.user,
            upstream_revision="eda-1.1.1",
        )
        self.assertEqual(first["status"], "stale")
        self.assertEqual(second["status"], "stale")
        self.assertEqual(len(second["history"]), 1)
        self.assertEqual(
            second["current_approved"]["stale_reasons"],
            ["Correlation threshold changed."],
        )

    def test_client_cannot_supply_confirmation_actor(self) -> None:
        value = _payload().model_dump()
        value["confirmed_by"] = "spoofed-admin"
        with self.assertRaises(ValidationError):
            EDADocumentationPayload.model_validate(value)

    def test_active_dataset_is_rejected_before_cross_project_access(self) -> None:
        service = EDADocumentationService(Path(self.tempdir.name))
        with (
            patch(
                "server.eda.documentation_service.active_project_id",
                return_value="another-project",
            ),
            patch(
                "server.eda.documentation_service.eda_workspace_service.authorized_dataset"
            ) as authorized_dataset,
        ):
            with self.assertRaises(
                EDADocumentationValidationError
            ) as raised:
                service._active_context(PROJECT_ID)
        self.assertEqual(
            raised.exception.code,
            "eda_project_scope_mismatch",
        )
        authorized_dataset.assert_not_called()


if __name__ == "__main__":
    unittest.main()

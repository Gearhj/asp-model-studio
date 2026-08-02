"""Isolated tests for governed findings, reviewer, completion, and MDD contracts."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from server.eda.documentation_service import (
    EDADocumentationService,
    EDADocumentationValidationError,
    _expected_child_inventory_from_contract,
)
from server.eda.documentation_types import (
    EDACompletionRequest,
    EDADocumentationPayload,
)


PROJECT_ID = "project-governed-eda-completion"


def _context():
    expected_children = _expected_child_inventory_from_contract(
        {}, duplicate_rows=12, target_source_exclusions=[]
    )
    return {
        "project_id": PROJECT_ID,
        "dataset_id": "dataset-governed",
        "dataset_version_id": "version-immutable-1",
        "dataset_version": "version-immutable-1",
        "target": "bad_flag",
        "predictor_manifest_id": "manifest-1",
        "authorized_predictors": ["ExternalRiskEstimate"],
        "target_source_exclusions": ["RiskPerformance"],
        "population_rows": 100,
        "duplicate_rows": 0,
        "data_revision": 1,
        "expected_parent_families": ["exact_duplicate_rows"],
        "expected_child_evidence_by_family": expected_children,
    }


def _child():
    descriptor = _expected_child_inventory_from_contract(
        {}, duplicate_rows=12, target_source_exclusions=[]
    )["exact_duplicate_rows"][0]
    return {
        key: copy.deepcopy(value)
        for key, value in descriptor.items()
        if key not in {"family", "authoritative_hash"}
    }


def _parent(**updates):
    child = _child()
    value = {
        "parent_id": "eda-parent-exact-duplicate-rows",
        "family": "exact_duplicate_rows",
        "title": "Exact duplicate rows",
        "category": "Data quality",
        "severity": "high",
        "requirement": "blocker",
        "child_ids": [child["id"]],
        "child_evidence": [child],
        "affected_variables": [],
        "evidence_references": ["overview.data_integrity.duplicate_rows"],
        "allowed_dispositions": [
            "unresolved",
            "accepted",
            "rejected",
            "deferred",
            "documented",
            "no_action_required",
        ],
        "reviewer_disposition": "rejected",
        "reviewer_rationale": "The recommendation is rejected after expert review.",
        "downstream_destination": None,
        "suggested_transformation": "No transformation",
        "eligible_for_completion": True,
        "rationale_required": True,
        "decision_origin": "reviewer",
        "mutation_applied": False,
    }
    value.update(updates)
    return value


def _stability_parent():
    descriptor = _expected_child_inventory_from_contract(
        {},
        duplicate_rows=0,
        target_source_exclusions=[],
        include_stability_not_available=True,
    )["stability_segments_unavailable"][0]
    child = {
        key: copy.deepcopy(value)
        for key, value in descriptor.items()
        if key not in {"family", "authoritative_hash"}
    }
    return {
        "parent_id": "eda-parent-stability-segments-unavailable",
        "family": "stability_segments_unavailable",
        "title": "Stability and Segments unavailable",
        "category": "Stability",
        "severity": "info",
        "requirement": "informational",
        "child_ids": [child["id"]],
        "child_evidence": [child],
        "affected_variables": [],
        "evidence_references": child["evidenceReferences"],
        "allowed_dispositions": [
            "unresolved",
            "accepted",
            "rejected",
            "deferred",
            "documented",
            "no_action_required",
            "not_applicable",
        ],
        "reviewer_disposition": "not_applicable",
        "reviewer_rationale": (
            "No governed time or segment field and no approved comparison "
            "population are available."
        ),
        "downstream_destination": "Documentation",
        "suggested_transformation": "No transformation",
        "eligible_for_completion": True,
        "rationale_required": False,
        "decision_origin": "system_informational_default",
        "mutation_applied": False,
    }


def _payload(**updates) -> EDADocumentationPayload:
    parent = _parent()
    stability_parent = _stability_parent()
    value = {
        "project_id": PROJECT_ID,
        "dataset_id": "dataset-governed",
        "dataset_version_id": "version-immutable-1",
        "dataset_version": "version-immutable-1",
        "target": "bad_flag",
        "predictor_manifest_id": "manifest-1",
        "eda_analysis_version": "eda-governance-test-v1",
        "governance_contract_version": "eda-governance-v2",
        "sections": {
            "overview": {
                "analysis_status": "analyzed",
                "governed_analytical_contract": {
                    "analysis_scope": "development_population",
                    "rows_used": 80,
                    "rows_excluded": 20,
                },
            },
            "target": {"analysis_status": "analyzed"},
            "predictors": {
                "analysis_status": "analyzed",
                "selected_predictors": ["ExternalRiskEstimate"],
                "governed_predictor_artifacts": [],
            },
            "relationships": {
                "analysis_status": "analyzed",
                "governed_relationship_artifact": {"artifact_id": "rel-1"},
            },
            "stability_and_segments": {
                "analysis_status": "not_available",
                "statement": "No governed time or segment fields",
                "limitation": {
                    "status": "not_applicable",
                    "reason": "no_approved_field_or_comparison_population",
                    "time_stability_assessed": False,
                    "segment_comparison_assessed": False,
                    "drift_assessed": False,
                    "psi_assessed": False,
                    "blocks_completion": False,
                },
            },
            "findings": {
                "parent_findings": [parent, stability_parent],
                "finding_groups": [
                    {
                        "family": parent["family"],
                        "title": parent["title"],
                        "parent_ids": [parent["parent_id"]],
                        "child_count": 1,
                        "requirement": "blocker",
                    },
                    {
                        "family": stability_parent["family"],
                        "title": stability_parent["title"],
                        "parent_ids": [stability_parent["parent_id"]],
                        "child_count": 1,
                        "requirement": "informational",
                    },
                ],
                "required_parent_finding_count": 1,
                "unresolved_parent_finding_count": 0,
                "eligible_parent_finding_count": 2,
                "informational_parent_finding_count": 1,
                "child_evidence_count": 2,
                "carry_forward": [],
                "automatic_transformations_applied": False,
            },
        },
        "evidence_references": [],
        "decisions": [
            {
                "decision_id": "decision-parent-duplicate",
                "parent_id": parent["parent_id"],
                "child_ids": parent["child_ids"],
                "finding_family": parent["family"],
                "category": "eda_parent_finding:Data quality",
                "decision": "rejected",
                "rationale": parent["reviewer_rationale"],
                "status": "rejected",
                "carry_forward_mode": "none",
                "mutation_applied": False,
                "evidence_references": parent["evidence_references"],
            }
        ],
        "reviewer_record": {
            "overall_conclusion": "EDA is acceptable for governed carry-forward.",
            "reviewer_commentary": "Required findings were reviewed against evidence.",
            "overall_review_status": "accepted",
            "required_conditions": [],
            "open_nonblocking_items": ["Stability is not applicable."],
            "evidence_references": [],
            "generated_draft_used": False,
        },
        "bulk_disposition_actions": [],
        "performance_metadata": {},
        "duplicate_decision": "No duplicate rows detected.",
        "target_source_exclusions": ["RiskPerformance"],
        "unresolved_blocking_findings": [],
        "reviewer_status": "approved",
    }
    value.update(updates)
    return EDADocumentationPayload.model_validate(value)


class EDAGovernedCompletionTests(unittest.TestCase):
    def setUp(self):
        workspace_tmp = Path(__file__).resolve().parents[1] / ".tmp"
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        self.tempdir = tempfile.TemporaryDirectory(dir=workspace_tmp)
        self.service = EDADocumentationService(
            Path(self.tempdir.name),
            context_provider=lambda _project_id: _context(),
        )
        self.user = {"userId": "reviewer-17", "displayName": "Reviewer 17"}
        self.audit_patch = patch(
            "server.eda.documentation_service.audit_event", return_value=None
        )
        self.audit_patch.start()

    def tearDown(self):
        self.audit_patch.stop()
        self.tempdir.cleanup()

    def test_authoritative_child_inventory_ignores_full_population_holdout_only_fields(self):
        contract = {
            "target": "bad_flag",
            "target_artifact": {
                "target": "bad_flag",
                "problem_type": "classification",
                "event_rate": 0.4,
                "event_count": 32,
                "valid_count": 80,
                "missing_count": 0,
            },
            "predictor_artifacts": {
                "ExternalRiskEstimate": {
                    "iv": 0.7,
                    "iv_woe": {
                        "bins": [
                            {
                                "bin_type": "ordinary_valid_range",
                                "event_rate": 0.2,
                            },
                            {
                                "bin_type": "ordinary_valid_range",
                                "event_rate": 0.6,
                            },
                        ]
                    },
                    "monotonicity": {"valid_value_shape": "Non-monotonic"},
                    "value_classification": {
                        "development_counts": {
                            "true_null": 8,
                            "bureau_special_value": 8,
                            "ordinary_valid_value": 64,
                            "parse_failure": 0,
                        },
                        "full_population_counts": {"true_null": 1000},
                    },
                    "special_values": {
                        "groups": [{"population_share": 0.1}],
                        "full_population_groups": [{"population_share": 0.9}],
                    },
                    "ordinary_outlier": {"rate": 0.95},
                }
            },
            "relationship_artifact": {
                "correlation": {
                    "columns": ["ExternalRiskEstimate"],
                    "pearson_matrix": [[1.0]],
                },
                "vif": [],
            },
            "full_population_target_profile": {"event_rate": 0.99},
        }
        baseline = _expected_child_inventory_from_contract(
            contract, duplicate_rows=0, target_source_exclusions=[]
        )
        changed = copy.deepcopy(contract)
        predictor = changed["predictor_artifacts"]["ExternalRiskEstimate"]
        predictor["value_classification"]["full_population_counts"] = {
            "true_null": 0,
            "ordinary_valid_value": 50000,
        }
        predictor["special_values"]["full_population_groups"] = []
        predictor["ordinary_outlier"] = {"rate": 0.0, "count": 0}
        changed["full_population_target_profile"] = {"event_rate": 0.01}
        changed["population_rows"] = 50000
        self.assertEqual(
            baseline,
            _expected_child_inventory_from_contract(
                changed, duplicate_rows=0, target_source_exclusions=[]
            ),
        )

    def test_rejected_parent_and_stability_na_are_completion_eligible(self):
        result = self.service.complete(
            EDACompletionRequest(payload=_payload(), idempotency_key="request-1"),
            self.user,
        )
        self.assertTrue(result["next_step_eligible"])
        record = result["record"]
        self.assertFalse(record["dataset_mutated"])
        self.assertFalse(record["feature_manifest_mutated"])
        self.assertEqual(
            record["mdd_structured_payload"]["stability_limitation"]["status"],
            "not_applicable",
        )
        self.assertFalse(
            record["mdd_structured_payload"]["stability_limitation"][
                "blocks_completion"
            ]
        )
        self.assertEqual(
            record["mdd_structured_payload"]["governed_analytical_contract"],
            _payload().sections.overview["governed_analytical_contract"],
        )
        self.assertEqual(
            record["mdd_structured_payload"]["governed_predictor_artifacts"],
            _payload().sections.predictors["governed_predictor_artifacts"],
        )
        self.assertEqual(
            record["mdd_structured_payload"]["governed_relationship_artifact"],
            _payload().sections.relationships[
                "governed_relationship_artifact"
            ],
        )

    def test_disposition_must_be_in_parent_allowed_dispositions(self):
        value = _payload().model_dump()
        value["sections"]["findings"]["parent_findings"][0][
            "reviewer_disposition"
        ] = "invented_status"
        value["sections"]["findings"]["unresolved_parent_finding_count"] = 1
        with self.assertRaisesRegex(
            ValueError, "outside its governed allowed dispositions"
        ):
            self.service.confirm(
                EDADocumentationPayload.model_validate(value), self.user
            )

    def test_parent_policy_fields_are_server_authoritative(self):
        cases = []

        relabeled = _payload().model_dump()
        relabeled["sections"]["findings"]["parent_findings"][0][
            "requirement"
        ] = "informational"
        cases.append((relabeled, "cannot change its canonical blocker requirement"))

        self_authorized = _payload().model_dump()
        self_authorized["sections"]["findings"]["parent_findings"][0][
            "allowed_dispositions"
        ].append("invented_status")
        self_authorized["sections"]["findings"]["parent_findings"][0][
            "reviewer_disposition"
        ] = "invented_status"
        cases.append((self_authorized, "outside its governed allowed dispositions"))

        lowered_severity = _payload().model_dump()
        lowered_severity["sections"]["findings"]["parent_findings"][0][
            "severity"
        ] = "info"
        cases.append(
            (
                lowered_severity,
                "maximum immutable child-evidence severity",
            )
        )

        unknown_family = _payload().model_dump()
        unknown_family["sections"]["findings"]["parent_findings"][0][
            "family"
        ] = "client_invented_family"
        cases.append((unknown_family, "unknown governed family"))

        for value, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.service.confirm(
                        EDADocumentationPayload.model_validate(value), self.user
                    )

    def test_parent_inventory_cannot_be_omitted_or_truncated(self):
        empty = _payload().model_dump()
        empty_findings = empty["sections"]["findings"]
        empty_findings["parent_findings"] = []
        empty_findings["finding_groups"] = []
        empty_findings["required_parent_finding_count"] = 0
        empty_findings["eligible_parent_finding_count"] = 0
        empty_findings["informational_parent_finding_count"] = 0
        empty_findings["child_evidence_count"] = 0
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            self.service.confirm(
                EDADocumentationPayload.model_validate(empty), self.user
            )

        truncated = _payload().model_dump()
        truncated_findings = truncated["sections"]["findings"]
        truncated_findings["parent_findings"] = [
            truncated_findings["parent_findings"][1]
        ]
        truncated_findings["finding_groups"] = [
            truncated_findings["finding_groups"][1]
        ]
        truncated_findings["required_parent_finding_count"] = 0
        truncated_findings["eligible_parent_finding_count"] = 1
        truncated_findings["informational_parent_finding_count"] = 1
        truncated_findings["child_evidence_count"] = 1
        with self.assertRaisesRegex(ValueError, "omitted current governed families"):
            self.service.confirm(
                EDADocumentationPayload.model_validate(truncated), self.user
            )

    def test_child_evidence_coverage_and_complete_content_are_authoritative(self):
        omitted = _payload().model_dump()
        parent = omitted["sections"]["findings"]["parent_findings"][0]
        parent["child_ids"] = []
        parent["child_evidence"] = []
        omitted["sections"]["findings"]["child_evidence_count"] = 1
        with self.assertRaisesRegex(
            ValueError, "immutable child evidence|exactly cover"
        ):
            self.service.confirm(
                EDADocumentationPayload.model_validate(omitted), self.user
            )

        modified = _payload().model_dump()
        modified_child = modified["sections"]["findings"]["parent_findings"][0][
            "child_evidence"
        ][0]
        modified_child["analyticalBasis"] = "Client-rewritten analytical basis."
        with self.assertRaisesRegex(
            ValueError, "complete backend-authoritative analytical record"
        ):
            self.service.confirm(
                EDADocumentationPayload.model_validate(modified), self.user
            )

    def test_completion_sequence_is_ordered_idempotent_and_nonduplicating(self):
        request = EDACompletionRequest(payload=_payload(), idempotency_key="request-1")
        first = self.service.complete(request, self.user)
        second = self.service.complete(request, self.user)
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(first["completion_id"], second["completion_id"])
        self.assertEqual(
            [item["stage"] for item in first["completion_sequence"]],
            [
                "validate",
                "persist_reviewer_record",
                "persist_dispositions",
                "persist_carry_forward_recommendations",
                "record_evidence",
                "update_mdd",
                "mark_eda_complete",
            ],
        )
        self.assertEqual(len(self.service.get_state(PROJECT_ID)["history"]), 1)

    def test_volatile_artifact_timestamps_do_not_duplicate_completion(self):
        first_value = _payload().model_dump()
        first_value["sections"]["overview"]["governed_analytical_contract"][
            "created_at"
        ] = "2026-08-01T10:00:00Z"
        first = self.service.complete(
            EDACompletionRequest(
                payload=EDADocumentationPayload.model_validate(first_value),
                idempotency_key="restart-stable-1",
            ),
            self.user,
        )
        second_value = copy.deepcopy(first_value)
        second_value["sections"]["overview"]["governed_analytical_contract"][
            "created_at"
        ] = "2026-08-01T11:00:00Z"
        second_value["performance_metadata"] = {
            "section_duration_ms": {"overview": 999},
            "section_cache_status": {"overview": "hit"},
        }
        second = self.service.complete(
            EDACompletionRequest(
                payload=EDADocumentationPayload.model_validate(second_value),
                idempotency_key="restart-stable-2",
            ),
            self.user,
        )
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(first["completion_id"], second["completion_id"])
        self.assertEqual(
            first["record"]["mdd_structured_payload"][
                "governed_analytical_contract"
            ]["created_at"],
            "2026-08-01T10:00:00Z",
        )
        self.assertEqual(len(self.service.get_state(PROJECT_ID)["history"]), 1)

    def test_stage_failure_is_safe_and_writes_nothing(self):
        original = self.service._completion_stage

        def fail_mdd(stage, **kwargs):
            if stage == "update_mdd":
                raise RuntimeError("synthetic MDD outage")
            return original(stage, **kwargs)

        with patch.object(self.service, "_completion_stage", side_effect=fail_mdd):
            with self.assertRaises(EDADocumentationValidationError) as raised:
                self.service.complete(
                    EDACompletionRequest(payload=_payload()), self.user
                )
        self.assertEqual(
            raised.exception.code, "eda_completion_update_mdd_failed"
        )
        state = self.service.get_state(PROJECT_ID)
        self.assertIsNone(state["current_approved"])
        self.assertEqual(state["history"], [])

    def test_missing_reviewer_commentary_fails_closed(self):
        value = _payload().model_dump()
        value["reviewer_record"]["reviewer_commentary"] = ""
        with self.assertRaises(EDADocumentationValidationError) as raised:
            self.service.complete(
                EDACompletionRequest(
                    payload=EDADocumentationPayload.model_validate(value)
                ),
                self.user,
            )
        self.assertEqual(raised.exception.code, "eda_confirmation_blocked")
        self.assertIn("commentary", str(raised.exception).lower())
        self.assertFalse(any(Path(self.tempdir.name).glob("*.json")))

    def test_unresolved_required_parent_fails_closed(self):
        value = _payload().model_dump()
        row = value["sections"]["findings"]["parent_findings"][0]
        row["reviewer_disposition"] = "unresolved"
        row["reviewer_rationale"] = ""
        row["eligible_for_completion"] = False
        value["sections"]["findings"]["unresolved_parent_finding_count"] = 1
        with self.assertRaises(EDADocumentationValidationError) as raised:
            self.service.confirm(
                EDADocumentationPayload.model_validate(value), self.user
            )
        self.assertIn("required parent", str(raised.exception).lower())

    def test_bulk_actor_and_timestamp_are_server_derived(self):
        value = _payload().model_dump()
        value["bulk_disposition_actions"] = [
            {
                "action_id": "bulk-1",
                "family": "exact_duplicate_rows",
                "parent_ids": ["eda-parent-exact-duplicate-rows"],
                "child_ids": [_child()["id"]],
                "prior_statuses": {
                    "eda-parent-exact-duplicate-rows": "unresolved"
                },
                "new_status": "rejected",
                "rationale": "Bulk review completed with evidence.",
                "destination": None,
                "mutation_applied": False,
            }
        ]
        value["sections"]["findings"]["bulk_disposition_audit"] = [
            {
                **copy.deepcopy(value["bulk_disposition_actions"][0]),
                "actor_hint": "spoofed-reviewer",
                "occurred_at": "1999-01-01T00:00:00Z",
            }
        ]
        result = self.service.confirm(
            EDADocumentationPayload.model_validate(value), self.user
        )
        audit = result["record"]["bulk_disposition_actions"][0]
        self.assertEqual(audit["actor"], "reviewer-17")
        self.assertEqual(audit["actor_display_name"], "Reviewer 17")
        self.assertTrue(audit["timestamp"].endswith("+00:00"))
        self.assertFalse(audit["mutation_applied"])
        section_audit = result["record"]["sections"]["findings"][
            "bulk_disposition_audit"
        ][0]
        mdd_audit = result["record"]["mdd_structured_payload"][
            "findings_and_dispositions"
        ]["bulk_disposition_audit"][0]
        for projected in (section_audit, mdd_audit):
            self.assertEqual(projected["actor"], "reviewer-17")
            self.assertEqual(projected["actor_display_name"], "Reviewer 17")
            self.assertTrue(projected["timestamp"].endswith("+00:00"))
            self.assertNotIn("actor_hint", projected)
            self.assertNotIn("occurred_at", projected)

        invalid = copy.deepcopy(value)
        invalid["bulk_disposition_actions"][0]["actor"] = "spoofed"
        with self.assertRaises(ValidationError):
            EDADocumentationPayload.model_validate(invalid)

    def test_mdd_staleness_names_sources_and_classification(self):
        self.service.confirm(_payload(), self.user)
        narrative = _payload().model_dump()
        narrative["sections"]["findings"]["reviewer_commentary"] = (
            "Narrative clarification only."
        )
        narrative["eda_analysis_version"] = "eda-governance-test-v2"
        state = self.service.upsert_draft(
            EDADocumentationPayload.model_validate(narrative), self.user
        )
        stale = state["draft"]["mdd_staleness"]
        self.assertIn("findings.reviewer_commentary", stale["changed_source_fields"])
        self.assertTrue(stale["narrative_only_staleness"])
        self.assertFalse(stale["analytical_staleness"])

        analytical = _payload().model_dump()
        analytical["sections"]["relationships"][
            "governed_relationship_artifact"
        ]["artifact_id"] = "rel-2"
        analytical["eda_analysis_version"] = "eda-governance-test-v3"
        state = self.service.upsert_draft(
            EDADocumentationPayload.model_validate(analytical), self.user
        )
        stale = state["draft"]["mdd_staleness"]
        self.assertTrue(stale["analytical_staleness"])
        self.assertIn(
            "relationships.governed_relationship_artifact.artifact_id",
            stale["changed_source_fields"],
        )


if __name__ == "__main__":
    unittest.main()

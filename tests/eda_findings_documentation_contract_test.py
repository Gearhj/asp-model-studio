import unittest

from pydantic import ValidationError

from server.eda.documentation_types import EDADocumentationPayload


def payload(decision):
    return {
        "project_id": "project-heloc",
        "dataset_id": "ds-heloc",
        "dataset_version_id": "heloc-v1",
        "dataset_version": "heloc-v1",
        "target": "bad_flag",
        "predictor_manifest_id": "eda-pm-heloc",
        "eda_analysis_version": "eda-findings-v1",
        "sections": {
            "overview": {"analysis_status": "analyzed"},
            "target": {"analysis_status": "analyzed"},
            "predictors": {"analysis_status": "analyzed"},
            "relationships": {"analysis_status": "analyzed"},
            "stability_and_segments": {"analysis_status": "not_available"},
            "findings": {
                "approved_findings": [],
                "rejected_findings": [],
                "unresolved_items": [],
                "automatic_transformations_applied": False,
            },
        },
        "evidence_references": [],
        "decisions": [decision],
        "performance_metadata": {},
        "target_source_exclusions": ["RiskPerformance"],
        "unresolved_blocking_findings": [],
        "reviewer_status": "reviewed",
    }


class EDAFindingsDocumentationContractTests(unittest.TestCase):
    def test_finding_decision_accepts_governed_draft_metadata(self):
        parsed = EDADocumentationPayload.model_validate(
            payload(
                {
                    "decision_id": "eda-findings-v1-finding-1",
                    "finding_id": "finding-1",
                    "category": "eda_finding:Predictors",
                    "decision": "accepted",
                    "rationale": "Availability at decision time was reviewed.",
                    "status": "approved",
                    "downstream_destination": "Validation",
                    "suggested_transformation": "Investigate further",
                    "carry_forward_mode": "draft_recommendation",
                    "mutation_applied": False,
                    "evidence_references": [
                        "predictors.predictor_visual_profiles.feature.metrics.iv"
                    ],
                }
            )
        )
        decision = parsed.decisions[0]
        self.assertEqual(decision.finding_id, "finding-1")
        self.assertEqual(decision.carry_forward_mode, "draft_recommendation")
        self.assertFalse(decision.mutation_applied)

    def test_finding_decision_rejects_claimed_automatic_mutation(self):
        with self.assertRaises(ValidationError):
            EDADocumentationPayload.model_validate(
                payload(
                    {
                        "decision_id": "eda-findings-v1-finding-1",
                        "finding_id": "finding-1",
                        "category": "eda_finding:Predictors",
                        "decision": "accepted",
                        "rationale": "Invalid mutation claim.",
                        "status": "approved",
                        "downstream_destination": "Feature Engineering",
                        "suggested_transformation": "Winsorization",
                        "carry_forward_mode": "draft_recommendation",
                        "mutation_applied": True,
                        "evidence_references": [],
                    }
                )
            )


if __name__ == "__main__":
    unittest.main()

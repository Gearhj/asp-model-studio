from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.persistence.db import Database, now_iso
from server.persistence.service import PersistenceService
from server.registry import router as registry_router
from server.registry.registry_service import RegistryService, summarize_evidence
from server.registry.schemas import TRANSPORTATION_REQUIRED_EVIDENCE


ADMIN_USER_ID = "user_eecc3a44ed694307"
PROJECT_ID = "transportation-registry-test"


class RegistryBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        test_directory = Path(__file__).resolve().parents[1] / ".tmp"
        test_directory.mkdir(parents=True, exist_ok=True)
        self.database_path = test_directory / "atlas_registry_test.db"
        self._remove_database_files()
        self.database = Database(self.database_path)
        self.database.initialize()
        self.persistence = PersistenceService(self.database)
        self.persistence.sync_user(
            {
                "userId": ADMIN_USER_ID,
                "displayName": "ATLAS Local Admin",
                "email": "admin@atlas.local",
                "role": "admin",
                "status": "active",
            }
        )
        self._seed_complete_transportation_project()
        self.registry = RegistryService(self.persistence)

    def tearDown(self) -> None:
        self._remove_database_files()

    def _remove_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def _seed_complete_transportation_project(self) -> None:
        timestamp = now_iso()
        optimization_state = {
            "studyCompleted": True,
            "businessObjective": "Minimize governed cash logistics transportation cost.",
            "decisionTitle": "Cash movement allocation",
            "recommendationStatus": "Recommended",
            "recommendationOwner": "ATLAS Local Admin",
            "recommendation": "Adopt the validated transportation allocation.",
            "implementationOwner": "Treasury Operations",
            "validation": {"score": 100, "status": "complete"},
        }
        self.persistence.projects.upsert(
            {
                "project_id": PROJECT_ID,
                "project_name": "Cash Logistics Transportation QA",
                "project_type": "optimization",
                "workflow_type": "optimization",
                "template_id": "transportation_logistics",
                "status": "active",
                "owner_user_id": ADMIN_USER_ID,
                "created_by": ADMIN_USER_ID,
                "updated_by": ADMIN_USER_ID,
                "created_at": timestamp,
                "updated_at": timestamp,
                "metadata_json": {
                    "optimizationState": optimization_state,
                    "riskTier": "Tier 2",
                    "tags": ["cash logistics", "operations research"],
                },
            }
        )
        steps = {f"optimization-{index}": "complete" for index in range(1, 15)}
        self.persistence.projects.upsert_workflow_state(
            PROJECT_ID,
            {
                "current_step_id": "optimization-14",
                "completed_steps_json": list(steps),
                "workflow_status_json": {"status": "complete", "steps": steps},
                "step_evidence_status_json": {step: "ready" for step in steps},
                "completed_by": ADMIN_USER_ID,
                "updated_at": timestamp,
            },
        )
        for index, artifact_type in enumerate(TRANSPORTATION_REQUIRED_EVIDENCE, start=1):
            self.persistence.evidence.upsert(
                {
                    "evidence_id": f"transportation-evidence-{index}",
                    "project_id": PROJECT_ID,
                    "workflow_type": "optimization",
                    "step_id": f"optimization-{min(index, 14)}",
                    "artifact_type": artifact_type,
                    "status": "ready",
                    "title": artifact_type.replace("_", " ").title(),
                    "summary": "Governed transportation optimization evidence.",
                    "created_by": ADMIN_USER_ID,
                    "created_at": timestamp,
                }
            )
        runs = (
            (
                "optimization-solver",
                {
                    "total_cost": 818.75,
                    "demand_fulfilled": 480,
                    "active_routes": 8,
                    "solver_status": "optimal",
                },
            ),
            ("optimization-scenarios", {"scenario_count": 5}),
            (
                "optimization-validation",
                {"validation_score": 100, "gate_status": "open"},
            ),
        )
        for index, (run_type, metrics) in enumerate(runs, start=1):
            self.persistence.runs.upsert(
                {
                    "run_id": f"transportation-run-{index}",
                    "project_id": PROJECT_ID,
                    "run_type": run_type,
                    "workflow_type": "optimization",
                    "status": "complete",
                    "started_at": timestamp,
                    "completed_at": timestamp,
                    "metrics_json": metrics,
                    "created_by": ADMIN_USER_ID,
                }
            )
        self.persistence.documentation.upsert(
            {
                "package_id": "transportation-documentation",
                "project_id": PROJECT_ID,
                "package_type": "optimization_study",
                "status": "complete",
                "readiness_score": 100,
                "section_count": 20,
                "completed_section_count": 20,
                "created_by": ADMIN_USER_ID,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )
        self.persistence.decisions.upsert(
            {
                "decision_id": "transportation-recommendation",
                "project_id": PROJECT_ID,
                "decision_type": "optimization_recommendation",
                "title": "Optimization recommendation",
                "summary": "Adopt the validated cash logistics allocation.",
                "status": "recommended",
                "owner": "ATLAS Local Admin",
                "created_by": ADMIN_USER_ID,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )
        for export_type in (
            "governed_json",
            "allocation_csv",
            "optimization_report",
            "python_code",
            "sas_compatible_code",
        ):
            self.persistence.exports.upsert(
                {
                    "export_id": f"transportation-export-{export_type}",
                    "project_id": PROJECT_ID,
                    "export_type": export_type,
                    "file_name": f"{export_type}.txt",
                    "created_by": ADMIN_USER_ID,
                    "created_at": timestamp,
                    "artifact_hash": f"hash-{export_type}",
                }
            )
        self.persistence.audit.create(
            {
                "audit_id": "transportation-audit",
                "project_id": PROJECT_ID,
                "user_id": ADMIN_USER_ID,
                "action_type": "optimization.study_completed",
                "entity_type": "project",
                "entity_id": PROJECT_ID,
                "title": "Optimization study completed",
                "summary": "Validation, evidence, and recommendation were persisted.",
                "created_at": timestamp,
            }
        )

    def test_completed_transportation_project_registry_classification_and_readiness(self) -> None:
        detail = self.registry.get_asset(PROJECT_ID)
        self.assertIsNotNone(detail)
        asset = detail["asset"]
        self.assertEqual(asset["asset_type"], "optimization_study")
        self.assertEqual(asset["workflow_type"], "optimization")
        self.assertEqual(asset["template_id"], "transportation_logistics")
        self.assertEqual(asset["lifecycle_status"], "Implementation Planned")
        self.assertEqual(asset["workflow_completion_percent"], 100)
        self.assertEqual(asset["evidence_status"], "Ready")
        self.assertEqual(asset["evidence_readiness_percent"], 75)
        self.assertEqual(asset["documentation_status"], "Complete")
        self.assertEqual(asset["documentation_readiness_percent"], 100)
        self.assertEqual(asset["validation_status"], "Complete")
        self.assertEqual(asset["validation_score"], 100)
        self.assertEqual(asset["recommendation_status"], "Recommended")
        self.assertEqual(asset["implementation_status"], "Plan complete")
        self.assertEqual(asset["monitoring_status"], "Plan complete")
        self.assertEqual(asset["open_action_count"], 0)
        self.assertIn("completed implementation plan", detail["lifecycle_derivation"]["matched_rule"].lower())

    def test_evidence_contract_deduplicates_types_and_matches_ready_package(self) -> None:
        records = [
            {"artifact_type": artifact_type, "status": "captured"}
            for artifact_type in TRANSPORTATION_REQUIRED_EVIDENCE
        ]
        records.extend(
            {"artifact_type": artifact_type, "status": "accepted"}
            for artifact_type in TRANSPORTATION_REQUIRED_EVIDENCE
        )
        summary = summarize_evidence(records, TRANSPORTATION_REQUIRED_EVIDENCE)
        self.assertEqual(summary["total_count"], len(TRANSPORTATION_REQUIRED_EVIDENCE))
        self.assertEqual(summary["coverage_score"], 100)
        self.assertTrue(summary["package_ready"])
        self.assertTrue(summary["package_approved"])
        self.assertEqual(summary["display_status"], "Approved")
        self.assertEqual(summary["missing_required_types"], [])

    def test_registry_summary_filters_actions_activity_and_owner_accountability(self) -> None:
        summary = self.registry.summary()
        self.assertEqual(summary["total_assets"], 1)
        self.assertEqual(summary["implementation_planned"], 1)
        self.assertEqual(summary["evidence_ready_count"], 1)
        self.assertEqual(summary["documentation_ready_count"], 1)
        self.assertEqual(summary["validation_complete_count"], 1)
        self.assertEqual(summary["open_action_count"], 0)
        self.assertEqual(summary["assets_by_type"], {"optimization_study": 1})

        filtered = self.registry.list_assets(
            asset_type="optimization_study",
            lifecycle_status="Implementation Planned",
            evidence_status="Ready",
            documentation_status="Complete",
            validation_status="Complete",
            search="Cash Logistics",
        )
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["project_id"], PROJECT_ID)
        self.assertEqual(self.registry.list_actions()["total"], 0)
        activity = self.registry.list_activity()
        self.assertGreater(activity["total"], 0)
        self.assertEqual(activity["items"][0]["project_id"], PROJECT_ID)
        owners = self.registry.owner_summaries()["items"]
        admin = next(owner for owner in owners if owner["user_id"] == ADMIN_USER_ID)
        self.assertEqual(admin["active_assets"], 1)
        self.assertEqual(admin["open_actions"], 0)
        self.assertEqual(admin["validation_records"], 1)
        self.assertEqual(admin["exports_generated"], 5)

    def test_incomplete_project_generates_only_real_governance_gaps(self) -> None:
        self.persistence.projects.upsert(
            {
                "project_id": "draft-project",
                "project_name": "Draft Model",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "owner_user_id": ADMIN_USER_ID,
                "metadata_json": {},
            }
        )
        detail = self.registry.get_asset("draft-project")
        action_types = {action["action_type"] for action in detail["open_actions"]}
        self.assertEqual(detail["asset"]["lifecycle_status"], "Draft")
        self.assertIn("incomplete_workflow", action_types)
        self.assertIn("missing_evidence", action_types)
        self.assertIn("missing_documentation", action_types)
        self.assertNotIn("validation_needed", action_types)
        self.assertNotIn("recommendation_draft", action_types)

    def test_registry_router_endpoints_return_service_payloads(self) -> None:
        with patch.object(registry_router, "get_registry_service", return_value=self.registry):
            assets = registry_router.list_registry_assets(limit=100, offset=0)
            summary = registry_router.get_registry_summary()
            actions = registry_router.get_registry_actions(limit=250)
            activity = registry_router.get_registry_activity(limit=100)
            owners = registry_router.get_registry_owners()
            detail = registry_router.get_registry_asset(PROJECT_ID)

        self.assertTrue(assets["ok"])
        self.assertEqual(assets["total"], 1)
        self.assertEqual(summary["summary"]["total_assets"], 1)
        self.assertEqual(actions["total"], 0)
        self.assertGreater(activity["total"], 0)
        self.assertEqual(owners["total"], 1)
        self.assertEqual(detail["asset"]["project_id"], PROJECT_ID)

    def test_registry_detail_missing_project_returns_404(self) -> None:
        with patch.object(registry_router, "get_registry_service", return_value=self.registry):
            with self.assertRaises(HTTPException) as context:
                registry_router.get_registry_asset("missing-project")
        self.assertEqual(context.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()

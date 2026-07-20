from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.monitoring.monitoring_service import MonitoringService
from server.persistence.db import Database, now_iso
from server.persistence.service import PersistenceService
from server.registry.registry_service import RegistryService


ADMIN = {"userId": "user_eecc3a44ed694307", "displayName": "ATLAS Local Admin", "email": "admin@atlas.local", "role": "admin", "status": "active"}
PROJECT_ID = "monitoring-center-project"


class MonitoringBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        test_directory = Path(__file__).resolve().parents[1] / ".tmp"
        test_directory.mkdir(parents=True, exist_ok=True)
        self.database_path = test_directory / "atlas_monitoring_test.db"
        self._remove_database_files()
        self.database = Database(self.database_path)
        self.database.initialize()
        self.persistence = PersistenceService(self.database)
        self.persistence.sync_user(ADMIN)
        self._seed_project()
        self.service = MonitoringService(self.persistence)
        self.registry = RegistryService(self.persistence)

    def tearDown(self) -> None:
        self._remove_database_files()

    def _remove_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def _seed_project(self) -> None:
        timestamp = now_iso()
        self.persistence.projects.upsert(
            {
                "project_id": PROJECT_ID,
                "project_name": "Monitoring Center QA",
                "project_type": "predictive_modeling",
                "workflow_type": "predictive_modeling",
                "template_id": "classification",
                "status": "active",
                "owner_user_id": ADMIN["userId"],
                "created_by": ADMIN["userId"],
                "created_at": timestamp,
                "updated_at": timestamp,
                "metadata_json": {"riskTier": "Tier 2", "businessPurpose": "Govern a production model."},
            }
        )

    def test_monitoring_lifecycle_registry_and_decision_outputs(self) -> None:
        detail = self.service.create_plan({"project_id": PROJECT_ID, "workflow_type": "predictive_modeling"}, ADMIN)
        plan = detail["plan"]
        self.assertEqual(plan["plan_status"], "draft")
        self.assertGreaterEqual(len(detail["metrics"]), 5)
        self.assertEqual(self.service.summary()["total_plans"], 1)

        activated = self.service.set_plan_status(plan["monitoring_plan_id"], "active", ADMIN)
        self.assertEqual(activated["plan"]["plan_status"], "active")

        run = self.service.create_run(plan["monitoring_plan_id"], {"run_name": "July production monitoring"}, ADMIN)
        run_id = run["monitoring_run_id"]
        self.assertEqual(self.service.start_run(run_id, ADMIN)["run_status"], "running")
        metric = activated["metrics"][0]
        completed = self.service.complete_run(
            run_id,
            {
                "summary": "Observed production monitoring metrics.",
                "observations": [
                    {
                        "monitoring_metric_id": metric["monitoring_metric_id"],
                        "observed_value": float(metric.get("breach_threshold") or metric.get("warning_threshold") or 1) + 1,
                        "baseline_value": 0.1,
                    }
                ],
            },
            ADMIN,
        )
        self.assertEqual(completed["run"]["run_status"], "completed")
        self.assertGreaterEqual(len(completed["observations"]), 1)
        plan_after_completion = self.service.plan_detail(plan["monitoring_plan_id"])
        self.assertGreaterEqual(len(plan_after_completion["alerts"]), 1)

        alert = plan_after_completion["alerts"][0]
        accepted = self.service.set_alert_status(alert["alert_id"], "accepted_risk", ADMIN, "Accepted for monitored remediation.")
        self.assertEqual(accepted["status"], "accepted_risk")
        review = self.service.create_validation_finding(alert["alert_id"], ADMIN)
        self.assertEqual(review["action"]["action_type"], "revalidation_review")

        asset = self.registry.get_asset(PROJECT_ID)["asset"]
        self.assertEqual(asset["monitoring_status"], "Active")
        self.assertGreaterEqual(asset["monitoring_open_alert_count"], 0)
        self.assertIsNotNone(asset["last_monitoring_run_at"])
        self.assertTrue(any(decision["decision_type"].startswith("monitoring_") for decision in self.persistence.decisions.list_for_project(PROJECT_ID)))
        self.assertTrue(any(audit["action_type"] == "monitoring_plan_activated" for audit in self.persistence.audit.list(project_id=PROJECT_ID)))
        self.assertTrue(any(evidence["artifact_type"] in {"monitoring_plan", "monitoring_run"} for evidence in self.persistence.evidence.list_for_project(PROJECT_ID)))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.persistence.db import Database, now_iso
from server.persistence.service import PersistenceService
from server.registry.registry_service import RegistryService
from server.validation.validation_service import ValidationService


ADMIN = {"userId": "user_eecc3a44ed694307", "displayName": "ATLAS Local Admin", "email": "admin@atlas.local", "role": "admin", "status": "active"}
# FND-005: a validation case may not be approved by the same person who
# submitted it, so the lifecycle test below (which submits as ADMIN) needs a
# second, independent validator identity to perform the final approval.
INDEPENDENT_VALIDATOR = {"userId": "user_independent_validator_fnd005", "displayName": "Independent Validator", "email": "independent.validator@atlas.local", "role": "validator", "status": "active"}
PROJECT_ID = "validation-center-project"


class ValidationBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        test_directory = Path(__file__).resolve().parents[1] / ".tmp"
        test_directory.mkdir(parents=True, exist_ok=True)
        self.database_path = test_directory / "atlas_validation_test.db"
        self._remove_database_files()
        self.database = Database(self.database_path)
        self.database.initialize()
        self.persistence = PersistenceService(self.database)
        self.persistence.sync_user(ADMIN)
        self.persistence.sync_user(INDEPENDENT_VALIDATOR)
        self._seed_project()
        self.service = ValidationService(self.persistence)
        self.registry = RegistryService(self.persistence)
        self.service.registry_service = self.registry

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
                "project_name": "Validation Center QA",
                "project_type": "optimization",
                "workflow_type": "optimization",
                "template_id": "transportation_logistics",
                "status": "active",
                "owner_user_id": ADMIN["userId"],
                "created_by": ADMIN["userId"],
                "created_at": timestamp,
                "updated_at": timestamp,
                "metadata_json": {"riskTier": "Tier 2", "optimizationState": {"recommendationStatus": "Draft"}},
            }
        )
        steps = {f"optimization-{index}": "complete" for index in range(1, 15)}
        self.persistence.projects.upsert_workflow_state(
            PROJECT_ID,
            {
                "current_step_id": "optimization-14",
                "completed_steps_json": list(steps),
                "workflow_status_json": {"steps": steps},
                "completed_by": ADMIN["userId"],
                "updated_at": timestamp,
            },
        )

    def test_validation_case_lifecycle_and_registry_integration(self) -> None:
        lookup = self.service.project_lookup(PROJECT_ID)
        self.assertIsNone(lookup["case"])
        self.assertEqual(self.service.queue({})["total"], 0)

        submitted = self.service.create_or_submit_case(
            PROJECT_ID,
            {"risk_tier": "Tier 2", "assigned_validator_name": "Independent Validation", "summary": "Ready for validation."},
            ADMIN,
        )
        validation_id = submitted["case"]["validation_id"]
        self.assertEqual(submitted["case"]["status"], "submitted")
        self.assertGreaterEqual(len(submitted["checklist"]), 6)
        self.assertEqual(self.service.queue({})["total"], 1)

        registry_asset = self.registry.get_asset(PROJECT_ID)["asset"]
        self.assertEqual(registry_asset["validation_status"], "Submitted for independent validation")
        self.assertEqual(registry_asset["lifecycle_status"], "Ready for Review")
        self.assertGreaterEqual(registry_asset["open_action_count"], 1)

        in_review = self.service.start_review(validation_id, ADMIN)
        self.assertEqual(in_review["case"]["status"], "in_review")
        self.assertEqual(self.registry.get_asset(PROJECT_ID)["asset"]["lifecycle_status"], "Validation")

        first_key = in_review["checklist"][0]["item_key"]
        checklist = self.service.update_checklist(validation_id, first_key, {"status": "passed", "result": "Validated"}, ADMIN)
        self.assertEqual(checklist["summary"]["checklist_passed"], 1)

        finding = self.service.upsert_finding(validation_id, {"title": "Resolve implementation monitoring evidence", "severity": "High", "status": "open"}, ADMIN)
        self.assertEqual(finding["summary"]["open_finding_count"], 1)
        self.assertGreaterEqual(self.registry.get_asset(PROJECT_ID)["asset"]["open_finding_count"], 1)

        challenge = self.service.upsert_challenge(validation_id, {"title": "Challenge scenario assumptions", "challenge_type": "methodology"}, ADMIN)
        challenge_id = challenge["challenges"][0]["challenge_id"]
        response = self.service.add_response(validation_id, challenge_id, {"response_text": "Scenario evidence has been linked."}, ADMIN)
        self.assertEqual(len(response["challenges"][0]["responses"]), 1)

        approved = self.service.approve(validation_id, {"decision": "approved_with_conditions", "final_score": 88, "decision_rationale": "Approved with monitoring evidence condition."}, INDEPENDENT_VALIDATOR)
        self.assertEqual(approved["case"]["status"], "approved_with_conditions")
        asset = self.registry.get_asset(PROJECT_ID)["asset"]
        self.assertEqual(asset["validation_status"], "Approved with conditions")
        self.assertEqual(asset["validation_score"], 88)
        self.assertEqual(asset["lifecycle_status"], "Approved with Conditions")
        self.assertGreaterEqual(len(approved["events"]), 6)
        self.assertGreaterEqual(len(self.persistence.audit.list(project_id=PROJECT_ID)), 6)
        self.assertTrue(any(decision["decision_type"].startswith("validation_") for decision in self.persistence.decisions.list_for_project(PROJECT_ID)))


if __name__ == "__main__":
    unittest.main()

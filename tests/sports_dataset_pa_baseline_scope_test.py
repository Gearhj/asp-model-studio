from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from server.persistence.db import Database, json_dumps
from server.sports_datasets.registry import SportsDatasetRegistry


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPOSITORY_ROOT / ".tmp"


class SportsDatasetPABaselineScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = SCRATCH_ROOT / f"sports-pa-baseline-scope-{uuid.uuid4().hex}"
        self.scratch.mkdir(parents=True, exist_ok=False)
        self.database = Database(self.scratch / "scope.db")
        self.database.initialize()
        self.registration_id = "sports-dataset-registration-rendered"
        self.project_id = "sports-project-rendered"
        recorded_at = "2026-08-17T00:00:00Z"
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sports_dataset_registrations (
                  registration_id, dataset_id, dataset_version_id, manifest_id,
                  manifest_sha, package_id, sport, league, evidence_cutoff,
                  published_at, logical_package_root, validation_status,
                  registered_at, last_validated_at, registered_by, rights_status,
                  limitation_count, active, totals_json, seasons_json,
                  evidence_coverage_json, metadata_json
                ) VALUES (?, 'dataset', 'dataset-version', 'manifest', ?, 'package',
                  'baseball', 'MLB', '2025-12-31', ?, 'exchange://dataset', 'VALID',
                  ?, ?, 'test', 'PASS', 0, 1, '{}', '[]', '{}', '{}')
                """,
                (self.registration_id, "a" * 64, recorded_at, recorded_at, recorded_at),
            )
            connection.execute(
                """
                INSERT INTO sports_research_projects (
                  project_id, registration_id, project_name, sport, league,
                  development_period, prior_history, forecast_lifecycle,
                  primary_target, secondary_targets_json, baseline_population,
                  upper_bound_population, research_purpose, workflow_evidence_json,
                  created_by, created_at, updated_at
                ) VALUES (?, ?, 'Rendered Project', 'baseball', 'MLB', '2023-2025',
                  '2022', 'RETROSPECTIVE_RESEARCH', 'PA outcome', '[]', 'baseline',
                  'upper', 'test', ?, 'test', ?, ?)
                """,
                (
                    self.project_id,
                    self.registration_id,
                    json_dumps({"identity_coverage_leakage": {"status": "NOT_CONFIGURED"}}, {}),
                    recorded_at,
                    recorded_at,
                ),
            )
        self.registry = SportsDatasetRegistry(self.database)
        self.registration = self.registry.get(self.registration_id)
        self.assertIsNotNone(self.registration)

    def tearDown(self) -> None:
        shutil.rmtree(self.scratch)

    def _render(self, *, parent_registration_id: str, project_id: str) -> dict:
        research = {
            "paBaseline": {
                "run": {
                    "parent": {"registrationId": parent_registration_id},
                    "projectId": project_id,
                },
                "decision": {"terminalStatus": "RESEARCH_BASELINE"},
            }
        }
        with patch(
            "server.sports_modeling.registry.SportsPAResearchRegistry.public_active",
            return_value=research,
        ):
            return self.registry.public_dataset(self.registration or {})

    def test_baseline_requires_exact_rendered_dataset_registration(self) -> None:
        result = self._render(
            parent_registration_id="sports-dataset-registration-other",
            project_id=self.project_id,
        )
        self.assertNotIn("paBaseline", result)
        self.assertEqual(result["project"]["status"], "REGISTERED_MODELING_BLOCKED")

    def test_baseline_requires_exact_rendered_governed_project(self) -> None:
        result = self._render(
            parent_registration_id=self.registration_id,
            project_id="sports-project-other",
        )
        self.assertNotIn("paBaseline", result)
        self.assertEqual(result["project"]["status"], "REGISTERED_MODELING_BLOCKED")

    def test_exact_dataset_and_project_lineage_attaches_baseline(self) -> None:
        result = self._render(
            parent_registration_id=self.registration_id,
            project_id=self.project_id,
        )
        self.assertEqual(
            result["paBaseline"]["run"]["parent"]["registrationId"],
            self.registration_id,
        )
        self.assertEqual(result["paBaseline"]["run"]["projectId"], self.project_id)
        self.assertEqual(
            result["project"]["status"],
            "REGISTERED_PA_RESEARCH_BASELINE",
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
import uuid
from pathlib import Path

from server.persistence.db import Database
from server.persistence.repositories.predictor_authorization_repository import (
    PredictorAuthorizationRepository,
)
from server.persistence.service import PersistenceService


class PredictorAuthorizationContractTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary_root = Path(__file__).resolve().parents[1] / ".tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.database_path = temporary_root / (
            f"predictor_authorization_{uuid.uuid4().hex}.db"
        )
        self.database = Database(self.database_path)
        self.database.initialize()
        persistence = PersistenceService(self.database)
        persistence.projects.upsert(
            {
                "project_id": "project-a",
                "project_name": "Predictor Authorization Test",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
            }
        )
        self.repository = PredictorAuthorizationRepository(self.database)

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    @staticmethod
    def record(identifier: str, predictors: list[str]) -> dict:
        return {
            "predictor_authorization_id": identifier,
            "project_id": "project-a",
            "dataset_id": "dataset-a",
            "dataset_version_id": "version-a",
            "target_contract_id": "target-contract-a",
            "target": "bad_flag",
            "authorized_predictors": predictors,
            "excluded_predictors": {
                "atlas_split": "Split or fold metadata cannot be used as a predictor"
            },
            "artifact_hash": identifier.removeprefix("predictor-auth-"),
            "created_by": "test-user",
            "created_at": "2026-08-01T12:00:00+00:00",
        }

    def test_exact_current_manifest_is_durable_and_reselection_is_explicit(self) -> None:
        first = self.repository.set_current(
            self.record("predictor-auth-aaaaaaaaaaaaaaaaaaaa", ["x1"])
        )
        self.assertEqual(first["status"], "current")
        exact = self.repository.get_current_exact(
            "project-a", "dataset-a", "version-a", "target-contract-a"
        )
        self.assertEqual(
            exact["predictor_authorization_id"],
            "predictor-auth-aaaaaaaaaaaaaaaaaaaa",
        )
        self.assertIsNone(
            self.repository.get_current_exact(
                "project-a", "dataset-a", "wrong-version", "target-contract-a"
            )
        )

        second = self.repository.set_current(
            self.record("predictor-auth-bbbbbbbbbbbbbbbbbbbb", ["x1", "x2"])
        )
        self.assertEqual(second["status"], "current")
        self.assertEqual(
            self.repository.get("predictor-auth-aaaaaaaaaaaaaaaaaaaa")["status"],
            "superseded",
        )

        restored = self.repository.set_current(
            self.record("predictor-auth-aaaaaaaaaaaaaaaaaaaa", ["x1"])
        )
        self.assertEqual(restored["status"], "current")
        self.assertEqual(
            self.repository.get("predictor-auth-bbbbbbbbbbbbbbbbbbbb")["status"],
            "superseded",
        )

    def test_manifest_rows_are_append_only(self) -> None:
        record = self.repository.set_current(
            self.record("predictor-auth-cccccccccccccccccccc", ["x1"])
        )
        with self.assertRaisesRegex(Exception, "append-only"):
            with self.database.transaction() as connection:
                connection.execute(
                    "DELETE FROM predictor_authorization_manifests WHERE predictor_authorization_id = ?",
                    (record["predictor_authorization_id"],),
                )


if __name__ == "__main__":
    unittest.main()

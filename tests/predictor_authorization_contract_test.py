from __future__ import annotations

import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from server.core.metadata_router import _persist_predictor_authorization
from server.preprocessing.predictor_authorization import (
    verify_durable_predictor_authorization,
)
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

    def test_data_acquisition_persists_deterministic_target_source_evidence(self) -> None:
        frame = pd.DataFrame(
            {
                "ordinary_predictor": [10, 10, 20, 20, 30, 30],
                "status_source": ["Good", "Bad", "Good", "Bad", "Good", "Bad"],
                "bad_flag": [0, 1, 0, 1, 0, 1],
            }
        )
        predictor_repository = Mock()
        evidence_repository = Mock()
        persistence = SimpleNamespace(
            ensure_project=Mock(),
            predictor_authorizations=predictor_repository,
            evidence=evidence_repository,
        )
        identity = {
            "dataset_id": "dataset-a",
            "dataset_version_id": "version-a",
        }
        with patch(
            "server.core.metadata_router.get_persistence_service",
            return_value=persistence,
        ):
            manifest = _persist_predictor_authorization(
                project_id="project-a",
                identity=identity,
                target="bad_flag",
                event_value=1,
                non_event_value=0,
                frame=frame,
                selected_columns=["ordinary_predictor", "status_source"],
                user={"userId": "reviewer-a"},
            )

        self.assertEqual(
            manifest["target_source_detection_scope"],
            "registered_population_pre_partition",
        )
        self.assertEqual(manifest["target_source_excluded"], ["status_source"])
        self.assertEqual(manifest["authorized_predictors"], ["ordinary_predictor"])
        self.assertEqual(
            manifest["target_source_evidence_ref"],
            manifest["predictor_authorization_id"],
        )
        evidence = manifest["target_source_fields"][0]
        self.assertEqual(evidence["field"], "status_source")
        self.assertEqual(evidence["compared_rows"], 6)
        self.assertEqual(evidence["coverage_rate"], 1.0)
        self.assertEqual(
            {(row["sourceValue"], row["targetValue"], row["rowCount"]) for row in evidence["mapping"]},
            {("Good", 0, 3), ("Bad", 1, 3)},
        )
        predictor_repository.set_current.assert_called_once_with(manifest)
        evidence_repository.upsert.assert_called_once()

        durable_record = {
            **manifest,
            "target_column": "bad_flag",
            "manifest_json": manifest,
        }
        verified = verify_durable_predictor_authorization(
            durable_record,
            project_id="project-a",
            dataset_id="dataset-a",
            dataset_version_id="version-a",
        )
        self.assertEqual(verified["target_source_fields"], [evidence])


if __name__ == "__main__":
    unittest.main()

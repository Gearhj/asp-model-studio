from __future__ import annotations

import sys
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.training.training_job_service import TrainingJobService  # noqa: E402
from server.training.candidate_contract import complete_training_contract  # noqa: E402


class TrainingJobScopeIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = {
            "project_id": "project-1",
            "dataset_id": "dataset-1",
            "dataset_version_id": "version-1",
        }
        self.store = SimpleNamespace(
            data_revision=7,
            meta={
                "split_status": "current",
                "feature_manifest": {
                    **self.identity,
                    "manifest_hash": "manifest-1",
                },
                "split_record": {
                    **self.identity,
                    "split_id": "split-1",
                    "validation_design": {
                        **self.identity,
                        "validation_design_id": "design-1",
                        "design_version": "design-version-1",
                    },
                },
            }
        )
        self.job = {
            **self.identity,
            "job_id": "job-1",
            "owner_user_id": "user-1",
            "data_revision": 7,
            "feature_manifest_version": "manifest-1",
            "split_id": "split-1",
            "validation_design_id": "design-1",
            "validation_design_version": "design-version-1",
            "_dataset_store": self.store,
            "overall_status": "running",
            "completed_at": None,
            "user_message": "",
            "message": "",
            "developer_details": [],
            "per_model_status": {
                "logreg": {"status": "running", "state": "running"}
            },
            "per_model_history": {"logreg": []},
        }
        self.job["contract"] = complete_training_contract(
            {
                **self.identity,
                "data_revision": 7,
                "target": "bad_flag",
                "problem_type": "classification",
                "event_value": 1,
                "non_event_value": 0,
                "feature_manifest_version": "manifest-1",
                "selected_original_features": ["feature_a"],
                "selected_engineered_features": [],
                "preprocessing_pipeline": [],
                "split_id": "split-1",
                "validation_design_id": "design-1",
                "validation_design_version": "design-version-1",
                "training_population_id": "training-population-1",
                "selection_partition_id": "training-population-1",
                "holdout_population_id": "holdout-population-1",
                "final_holdout_partition_id": "holdout-population-1",
                "fold_definition_id": "fold-definition-1",
                "final_holdout_status": "sealed",
                "holdout_isolation_status": "verified",
                "selection_resampling_status": "not_applied",
                "random_seed": 42,
                "calibration_configuration": {"requested": False},
                "runtime_environment": {},
            },
            feature_manifest=self.store.meta["feature_manifest"],
            store_meta=self.store.meta,
            training_job_id="job-1",
            training_run_id="run-1",
            created_by="user-1",
            created_at="2026-07-31T12:00:00+00:00",
            primary_metric="roc_auc",
        )

    def checkpoint_result(self, *_args, **_kwargs):
        return True, "", dict(self.identity)

    def test_current_validation_design_keeps_job_running(self):
        with patch(
            "server.training.training_job_service.validate_checkpoint_identity",
            side_effect=self.checkpoint_result,
        ):
            current, reason = TrainingJobService._scope_matches_job(self.job)

        self.assertTrue(current)
        self.assertEqual(reason, "")

    def test_design_change_interrupts_job_before_persistence(self):
        service = TrainingJobService()
        service._jobs[self.job["job_id"]] = self.job
        service._cancel_events[self.job["job_id"]] = Event()
        self.store.meta["split_record"]["validation_design"][
            "validation_design_id"
        ] = "design-2"

        with patch(
            "server.training.training_job_service.validate_checkpoint_identity",
            side_effect=self.checkpoint_result,
        ):
            interrupted = service._interrupt_if_scope_changed(
                self.job["job_id"]
            )

        self.assertTrue(interrupted)
        self.assertTrue(service._cancel_events[self.job["job_id"]].is_set())
        self.assertEqual(self.job["overall_status"], "interrupted")
        self.assertEqual(
            self.job["per_model_status"]["logreg"]["status"],
            "interrupted",
        )
        self.assertEqual(
            self.job["developer_details"][-1]["stage"],
            "canonical_scope_revalidation",
        )


if __name__ == "__main__":
    unittest.main()

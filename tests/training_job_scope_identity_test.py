from __future__ import annotations

import sys
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.training.training_job_service import TrainingJobService  # noqa: E402


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

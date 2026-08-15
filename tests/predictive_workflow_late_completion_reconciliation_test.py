from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path
from typing import Any

from server.persistence.db import Database, now_iso
from server.persistence.repositories.project_dataset_activation_repository import (
    ProjectDatasetActivationRepository,
)
from server.persistence.service import PersistenceService


PROJECT_ID = "project-late-completion"
DATASET_ID = "dataset-late-completion"
DATASET_VERSION_ID = "dataset-version-late-completion"
TARGET = "bad_flag"
MODEL_ID = "model-late-completion"
MODEL_VERSION_ID = "model-version-late-completion"
CANDIDATE_ID = "candidate-late-completion"
TRAINING_RUN_ID = "training-run-late-completion"
FEATURE_MANIFEST_VERSION = "feature-manifest-late-completion"
VALIDATION_DESIGN_ID = "validation-design-late-completion"
SPLIT_ID = "split-late-completion"
ARTIFACT_CHECKSUM = "sha256:model-late-completion"


class PredictiveWorkflowLateCompletionReconciliationTest(unittest.TestCase):
    """Late workflow completion is granted only by exact durable authority."""

    def setUp(self) -> None:
        self.temporary_root = Path(__file__).resolve().parents[1] / ".tmp" / (
            f"atlas-late-completion-{uuid.uuid4().hex}"
        )
        self.temporary_root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.temporary_root / "atlas_late_completion.db"
        self.database = Database(self.database_path)
        self.database.initialize()
        self.service = PersistenceService(self.database)
        self.user = {
            "userId": "late-completion-owner",
            "displayName": "Late Completion Owner",
            "email": "late-completion-owner@example.test",
            "role": "data_scientist",
        }
        self.service.sync_user(self.user)
        self.service.projects.upsert(
            {
                "project_id": PROJECT_ID,
                "project_name": "Late Completion Test",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "owner_user_id": self.user["userId"],
                "metadata_json": {},
            }
        )
        self._insert_current_finalized_model()

    def tearDown(self) -> None:
        expected_parent = Path(__file__).resolve().parents[1] / ".tmp"
        if self.temporary_root.parent == expected_parent:
            shutil.rmtree(self.temporary_root, ignore_errors=True)

    @staticmethod
    def _exact_model_identity() -> dict[str, str]:
        return {
            "modelId": MODEL_ID,
            "modelVersionId": MODEL_VERSION_ID,
            "candidateId": CANDIDATE_ID,
            "trainingRunId": TRAINING_RUN_ID,
            "featureManifestVersion": FEATURE_MANIFEST_VERSION,
            "validationDesignId": VALIDATION_DESIGN_ID,
            "splitId": SPLIT_ID,
            "artifactChecksum": ARTIFACT_CHECKSUM,
            "artifactVerificationStatus": "verified",
            "target": TARGET,
        }

    def _insert_current_finalized_model(self) -> None:
        timestamp = now_iso()
        self.service.models.upsert(
            {
                "model_id": MODEL_ID,
                "project_id": PROJECT_ID,
                "name": "Late Completion Champion",
                "problem_type": "classification",
                "status": "active",
                "owner_user_id": self.user["userId"],
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )
        self.service.model_versions.insert(
            {
                "model_version_id": MODEL_VERSION_ID,
                "model_id": MODEL_ID,
                "version_number": 1,
                "training_run_id": TRAINING_RUN_ID,
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": DATASET_VERSION_ID,
                "feature_manifest_version": FEATURE_MANIFEST_VERSION,
                "algorithm": "logistic_regression",
                "artifact_reference": "models/model-late-completion.joblib",
                "artifact_format": "joblib",
                "checksum": ARTIFACT_CHECKSUM,
                "artifact_size_bytes": 128,
                "publication_status": "finalized",
                "artifact_verified_at": timestamp,
                "finalized_at": timestamp,
                "lineage_status": "verified",
                "candidate_id": CANDIDATE_ID,
                "evaluation_package_id": "evaluation-package-late-completion",
                "candidate_decision_id": "candidate-decision-late-completion",
                "candidate_contract_hash": "candidate-contract-late-completion",
                "evaluation_package_contract_hash": "evaluation-contract-late-completion",
                "evaluation_package_integrity_status": "verified",
                "promotion_readiness_status": "verified",
                "target_name": TARGET,
                "validation_design_id": VALIDATION_DESIGN_ID,
                "split_id": SPLIT_ID,
                "created_by": self.user["userId"],
                "created_at": timestamp,
            }
        )
        self.service.models.upsert(
            {
                "model_id": MODEL_ID,
                "project_id": PROJECT_ID,
                "name": "Late Completion Champion",
                "problem_type": "classification",
                "status": "active",
                "owner_user_id": self.user["userId"],
                "current_version_id": MODEL_VERSION_ID,
                "current_version_generation": 1,
                "champion_updated_at": timestamp,
                "champion_updated_by": self.user["userId"],
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )

    def _write_completion_evidence(
        self,
        step_id: str,
        step_payload: dict[str, Any],
        *,
        model_overrides: dict[str, str] | None = None,
    ) -> str:
        exact_model = self._exact_model_identity()
        exact_model.update(model_overrides or {})
        evidence_id = f"evidence-{step_id}"
        canonical = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": DATASET_VERSION_ID,
            "lineage_contract": "canonical_dataset_version",
        }
        self.service.evidence.upsert(
            {
                "evidence_id": evidence_id,
                "project_id": PROJECT_ID,
                "workflow_type": "predictive-modeling",
                "step_id": step_id,
                "artifact_type": "workflow_completion",
                "status": "ready",
                "title": f"{step_id} completion",
                "source_ref": f"/{step_id}",
                "created_by": self.user["userId"],
                "payload_json": {
                    **canonical,
                    "status": "ready",
                    "lineage": {
                        **canonical,
                        "workflowStep": step_id,
                        **exact_model,
                    },
                    "payload": {
                        "workflowCompletionContract": (
                            "predictive_workflow_completion_v1"
                        ),
                        "stepId": step_id,
                        **exact_model,
                        **step_payload,
                    },
                },
            }
        )
        return evidence_id

    def _write_scoring_run(
        self,
        *,
        checksum: str | None,
        archived_at: str | None = None,
    ) -> None:
        timestamp = now_iso()
        self.service.scoring_runs.upsert(
            {
                "scoring_run_id": "scoring-run-late-completion",
                "project_id": PROJECT_ID,
                "user_id": self.user["userId"],
                "dataset_id": DATASET_ID,
                "dataset_version_id": DATASET_VERSION_ID,
                "dataset_identity": DATASET_VERSION_ID,
                "partition": "train",
                "model_id": MODEL_ID,
                "model_version": "1",
                "model_version_id": MODEL_VERSION_ID,
                "feature_manifest_version": FEATURE_MANIFEST_VERSION,
                "problem_type": "classification",
                "target": TARGET,
                "status": "completed",
                "created_at": timestamp,
                "completed_at": timestamp,
                "updated_at": timestamp,
                "checksum": checksum,
                "archived_at": archived_at,
            }
        )

    def _validate(self, step_id: str) -> tuple[bool, str, list[str]]:
        with self.database.connection() as connection:
            return ProjectDatasetActivationRepository._step_lineage_validation(
                connection,
                step_id=step_id,
                project_id=PROJECT_ID,
                dataset_id=DATASET_ID,
                dataset_version_id=DATASET_VERSION_ID,
            )

    def test_exact_current_model_and_canonical_completion_evidence_succeed(self) -> None:
        self._write_scoring_run(checksum="sha256:scoring-run")
        payloads = {
            "step10": {
                "scoredPartitions": ["train"],
                "scoredOutputCount": 1,
                "scoringRunIds": ["scoring-run-late-completion"],
            },
            "step11": {
                "documentTitle": "Model Development Document",
                "documentMode": "governance",
                "requiredSections": 12,
                "generatedAt": now_iso(),
            },
            "step12": {
                "implementationOwner": "Model Operations",
                "implementationTargetDate": "2026-09-01",
                "implementationEnvironment": "Production",
                "implementationNotesPresent": True,
            },
            "step13": {
                "monitoringCadence": "monthly",
                "monitoringMetrics": ["population_stability_index"],
                "monitoringNotesPresent": True,
                "escalationCount": 0,
            },
        }

        for step_id, payload in payloads.items():
            with self.subTest(step_id=step_id):
                evidence_id = self._write_completion_evidence(step_id, payload)
                valid, reason, artifact_ids = self._validate(step_id)
                self.assertTrue(valid, reason)
                self.assertEqual(artifact_ids, [evidence_id])

    def test_wrong_promoted_model_lineage_is_rejected(self) -> None:
        payload = {
            "documentTitle": "Model Development Document",
            "documentMode": "governance",
            "requiredSections": 12,
            "generatedAt": now_iso(),
        }
        mutations = {
            "model": {"modelId": "wrong-model"},
            "model_version": {"modelVersionId": "wrong-model-version"},
            "candidate": {"candidateId": "wrong-candidate"},
            "training_run": {"trainingRunId": "wrong-training-run"},
            "checksum": {"artifactChecksum": "sha256:wrong"},
        }

        for label, override in mutations.items():
            with self.subTest(lineage_field=label):
                self._write_completion_evidence(
                    "step11",
                    payload,
                    model_overrides=override,
                )
                valid, reason, artifact_ids = self._validate("step11")
                self.assertFalse(valid, reason)
                self.assertEqual(artifact_ids, [])

    def test_step10_requires_unarchived_checksum_backed_exact_scoring_run(self) -> None:
        self._write_completion_evidence(
            "step10",
            {
                "scoredPartitions": ["train"],
                "scoredOutputCount": 1,
                "scoringRunIds": ["scoring-run-late-completion"],
            },
        )

        valid, _, artifact_ids = self._validate("step10")
        self.assertFalse(valid)
        self.assertEqual(artifact_ids, [])

        self._write_scoring_run(checksum=None)
        valid, _, artifact_ids = self._validate("step10")
        self.assertFalse(valid)
        self.assertEqual(artifact_ids, [])

        self._write_scoring_run(
            checksum="sha256:scoring-run",
            archived_at=now_iso(),
        )
        valid, _, artifact_ids = self._validate("step10")
        self.assertFalse(valid)
        self.assertEqual(artifact_ids, [])

        self._write_scoring_run(checksum="sha256:scoring-run", archived_at=None)
        valid, reason, artifact_ids = self._validate("step10")
        self.assertTrue(valid, reason)
        self.assertEqual(artifact_ids, ["evidence-step10"])

    def test_step11_through_step13_require_step_specific_payloads(self) -> None:
        cases = {
            "step11": (
                {
                    "documentTitle": "Model Development Document",
                    "documentMode": "governance",
                    "requiredSections": 12,
                },
                {
                    "documentTitle": "Model Development Document",
                    "documentMode": "governance",
                    "requiredSections": 12,
                    "generatedAt": now_iso(),
                },
            ),
            "step12": (
                {
                    "implementationOwner": "Model Operations",
                    "implementationTargetDate": "2026-09-01",
                    "implementationEnvironment": "Production",
                },
                {
                    "implementationOwner": "Model Operations",
                    "implementationTargetDate": "2026-09-01",
                    "implementationEnvironment": "Production",
                    "implementationNotesPresent": False,
                },
            ),
            "step13": (
                {
                    "monitoringCadence": "monthly",
                    "monitoringMetrics": [],
                    "monitoringNotesPresent": False,
                    "escalationCount": 0,
                },
                {
                    "monitoringCadence": "monthly",
                    "monitoringMetrics": ["population_stability_index"],
                    "monitoringNotesPresent": False,
                    "escalationCount": 0,
                },
            ),
        }

        for step_id, (invalid_payload, valid_payload) in cases.items():
            with self.subTest(step_id=step_id, state="invalid"):
                self._write_completion_evidence(step_id, invalid_payload)
                valid, _, artifact_ids = self._validate(step_id)
                self.assertFalse(valid)
                self.assertEqual(artifact_ids, [])

            with self.subTest(step_id=step_id, state="valid"):
                evidence_id = self._write_completion_evidence(step_id, valid_payload)
                valid, reason, artifact_ids = self._validate(step_id)
                self.assertTrue(valid, reason)
                self.assertEqual(artifact_ids, [evidence_id])


if __name__ == "__main__":
    unittest.main()

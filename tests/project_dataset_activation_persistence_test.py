from __future__ import annotations

import json
import os
import shutil
import sqlite3
import unittest
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from fastapi import HTTPException

from server.core.dataset_store import DatasetStore, DatasetStoreProxy
from server.core.result_store import ResultStore, ResultStoreProxy
from server.datasets import dataset_registry
from server.datasets.dataset_identity import (
    active_dataset_identity,
    durable_active_dataset_identity,
    resolve_project_dataset_identity,
    validate_checkpoint_identity,
)
from server.persistence.db import Database
from server.persistence.repositories import (
    ProjectDatasetActivationConflictError,
    ProjectDatasetActivationRepository,
)
from server.persistence.service import PersistenceService


class ProjectDatasetActivationPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary_root = Path(__file__).resolve().parents[1] / ".tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.database_path = temporary_root / (
            f"atlas_project_dataset_activation_{uuid.uuid4().hex}.db"
        )
        self.dataset_root = temporary_root / (
            f"atlas_project_dataset_library_{uuid.uuid4().hex}"
        )
        self.dataset_root.mkdir(parents=True, exist_ok=True)
        self.database = Database(self.database_path)
        self.database.initialize()
        self.service = PersistenceService(self.database)
        self.user = {
            "userId": "activation-owner",
            "displayName": "Activation Owner",
            "email": "activation-owner@example.test",
            "role": "data_scientist",
        }
        self.service.sync_user(self.user)
        self.service.projects.upsert(
            {
                "project_id": "project-activation",
                "project_name": "Activation Test",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "owner_user_id": self.user["userId"],
                "metadata_json": {},
            }
        )
        self.service.projects.upsert_workflow_state(
            "project-activation",
            {
                "current_step_id": "step03",
                "completed_steps_json": ["step00", "step01", "step02"],
                "workflow_status_json": {
                    "status": "active",
                    "steps": {
                        "step00": "complete",
                        "step01": "complete",
                        "step02": "complete",
                        "step03": "active",
                    },
                },
                "step_evidence_status_json": {},
                "completed_by": self.user["userId"],
            },
        )
        self.repository = self.service.project_dataset_activations
        self._write_dataset_library()

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)
        expected_parent = Path(__file__).resolve().parents[1] / ".tmp"
        if self.dataset_root.parent == expected_parent:
            shutil.rmtree(self.dataset_root, ignore_errors=True)

    def _write_dataset_library(self, *, archived: bool = False, omit_v1: bool = False) -> None:
        datasets = [
            {
                "datasetId": "dataset-1",
                "name": "Dataset One",
                "sourceType": "registered",
                "ownerUserId": self.user["userId"],
                "archived": archived,
                "access": [],
                "target": "target",
                "versions": [
                    version
                    for version in (
                        {
                            "versionId": "dataset-version-1",
                            "label": "v1",
                            "fullDataPath": "dataset-1/versions/dataset-version-1/full_data.csv",
                            "hash": "hash-v1",
                            "schemaHash": "schema-v1",
                        },
                        {
                            "versionId": "dataset-version-2",
                            "label": "v2",
                            "fullDataPath": "dataset-1/versions/dataset-version-2/full_data.csv",
                            "hash": "hash-v2",
                            "schemaHash": "schema-v2",
                        },
                    )
                    if not (omit_v1 and version["versionId"] == "dataset-version-1")
                ],
            },
            {
                "datasetId": "dataset-2",
                "name": "Dataset Two",
                "sourceType": "registered",
                "ownerUserId": self.user["userId"],
                "archived": False,
                "access": [],
                "target": "target",
                "versions": [
                    {
                        "versionId": "dataset-version-3",
                        "label": "v3",
                        "fullDataPath": "dataset-2/versions/dataset-version-3/full_data.csv",
                        "hash": "hash-v3",
                        "schemaHash": "schema-v3",
                    }
                ],
            },
        ]
        for dataset in datasets:
            for version in dataset["versions"]:
                artifact = self.dataset_root / str(version["fullDataPath"])
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text("feature,target\n1,0\n2,1\n", encoding="utf-8")
        (self.dataset_root / "registry.json").write_text(
            json.dumps({"datasets": datasets}),
            encoding="utf-8",
        )
        (self.dataset_root / "project_links.json").write_text(
            json.dumps({"links": []}),
            encoding="utf-8",
        )
        (self.dataset_root / "users.json").write_text(
            json.dumps({"users": []}),
            encoding="utf-8",
        )

    @contextmanager
    def _identity_environment(self, *, service: PersistenceService | None = None):
        selected_service = service or self.service
        with (
            patch.dict(
                os.environ,
                {"ATLAS_DATASET_LIBRARY_ROOT": str(self.dataset_root)},
            ),
            patch.object(dataset_registry, "ARTIFACT_ROOT", self.dataset_root),
            patch.object(dataset_registry, "REGISTRY_PATH", self.dataset_root / "registry.json"),
            patch.object(dataset_registry, "PROJECT_LINKS_PATH", self.dataset_root / "project_links.json"),
            patch.object(dataset_registry, "USERS_PATH", self.dataset_root / "users.json"),
            patch(
                "server.persistence.service.get_persistence_service",
                return_value=selected_service,
            ),
            patch("server.datasets.dataset_identity.audit_event"),
            patch("server.security.security_store.audit_event"),
        ):
            yield

    def _activate(
        self,
        dataset_id: str = "dataset-1",
        version_id: str = "dataset-version-1",
        expected_revision: int | None = None,
    ) -> dict:
        return self.repository.activate_exact(
            project_id="project-activation",
            dataset_id=dataset_id,
            dataset_version_id=version_id,
            actor_user_id=self.user["userId"],
            expected_activation_revision=expected_revision,
            metadata={"source": "focused-test"},
        )

    def _event_count(self, event_type: str) -> int:
        with self.database.connection() as connection:
            return int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM project_dataset_activation_events
                    WHERE project_id = ? AND event_type = ?
                    """,
                    ("project-activation", event_type),
                ).fetchone()["count"]
            )

    def _insert_canonical_evidence(
        self,
        *,
        evidence_id: str,
        step_id: str,
        artifact_type: str,
        version_id: str = "dataset-version-1",
        lineage: dict | None = None,
        payload: dict | None = None,
        status: str = "ready",
    ) -> None:
        canonical_lineage = {
            "project_id": "project-activation",
            "dataset_id": "dataset-1",
            "dataset_version_id": version_id,
            "lineage_contract": "canonical_dataset_version",
            **(lineage or {}),
        }
        self.service.evidence.upsert(
            {
                "evidence_id": evidence_id,
                "project_id": "project-activation",
                "workflow_type": "predictive-modeling",
                "step_id": step_id,
                "artifact_type": artifact_type,
                "status": status,
                "title": f"Focused {step_id} evidence",
                "source_ref": f"/{step_id}",
                "artifact_hash": None,
                "created_by": self.user["userId"],
                "payload_json": {
                    "project_id": "project-activation",
                    "dataset_id": "dataset-1",
                    "dataset_version_id": version_id,
                    "lineage_contract": "canonical_dataset_version",
                    "lineage": canonical_lineage,
                    "status": "ready",
                    "payload": payload or {},
                },
            }
        )

    def _project_collaborator(self, permission_level: str = "view") -> dict:
        collaborator = {
            "userId": "project-collaborator",
            "displayName": "Project Collaborator",
            "email": "project-collaborator@example.test",
            "role": "data_scientist",
        }
        self.service.sync_user(collaborator)
        self.service.access.grant_permission(
            {
                "permission_id": f"permission-{uuid.uuid4().hex}",
                "resource_type": "project",
                "resource_id": "project-activation",
                "principal_type": "user",
                "principal_id": collaborator["userId"],
                "permission_level": permission_level,
                "granted_by_user_id": self.user["userId"],
                "metadata_json": {"source": "focused-test"},
            }
        )
        return collaborator

    def _grant_dataset_view(self, user_id: str, dataset_id: str = "dataset-1") -> None:
        registry_path = self.dataset_root / "registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        dataset = next(
            item
            for item in registry["datasets"]
            if item.get("datasetId") == dataset_id
        )
        dataset["access"] = [
            *(dataset.get("access") or []),
            {"userId": user_id, "role": "viewer"},
        ]
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

    def test_activation_is_atomic_idempotent_and_reconciles_effective_workflow(self) -> None:
        first = self._activate()
        self.assertTrue(first["changed"])
        self.assertEqual(first["link"]["link_status"], "active")
        self.assertEqual(first["active_selection"]["activation_revision"], 1)
        self.assertEqual(first["active_selection"]["activation_status"], "active")

        workflow = self.service.projects.get_workflow_state("project-activation") or {}
        self.assertEqual(
            workflow["completed_steps_json"],
            ["step00", "step01", "step02"],
        )
        workflow_status = workflow["workflow_status_json"]
        self.assertEqual(
            workflow_status["historicalCompletedSteps"],
            ["step00", "step01", "step02"],
        )
        self.assertEqual(
            workflow_status["effectiveCompletedSteps"],
            ["step00", "step01"],
        )
        self.assertEqual(workflow_status["effectiveCurrentStepId"], "step02")
        self.assertEqual(workflow_status["identityValidity"]["status"], "current")

        repeated = self._activate(expected_revision=1)
        self.assertFalse(repeated["changed"])
        self.assertEqual(repeated["active_selection"]["activation_revision"], 1)
        self.assertEqual(self._event_count("modeling_dataset_activated"), 1)

        state = self.repository.get_project_state("project-activation")
        self.assertEqual(len(state["links"]), 1)
        self.assertEqual(state["active_selection"]["dataset_version_id"], "dataset-version-1")

    def test_same_version_reactivation_revalidates_only_matching_current_evidence(self) -> None:
        first = self._activate()
        self.assertTrue(first["changed"])
        self._insert_canonical_evidence(
            evidence_id="evidence-eda-v1",
            step_id="step02",
            artifact_type="eda",
        )

        repeated = self._activate(expected_revision=1)
        self.assertFalse(repeated["changed"])
        workflow = self.service.projects.get_workflow_state("project-activation") or {}
        status = workflow["workflow_status_json"]
        self.assertEqual(
            status["effectiveCompletedSteps"],
            ["step00", "step01", "step02"],
        )
        self.assertEqual(
            status["effectiveSteps"]["step02"]["artifactIds"],
            ["evidence-eda-v1"],
        )

        # Same-revision activation must run validation again, not preserve the
        # prior effective list when its durable evidence becomes stale.
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE evidence_artifacts SET status = 'stale' WHERE evidence_id = ?",
                ("evidence-eda-v1",),
            )
        rechecked = self._activate(expected_revision=1)
        self.assertFalse(rechecked["changed"])
        status = (
            self.service.projects.get_workflow_state("project-activation") or {}
        )["workflow_status_json"]
        self.assertEqual(status["effectiveCompletedSteps"], ["step00", "step01"])
        self.assertEqual(status["effectiveSteps"]["step02"]["lineageStatus"], "stale")
        self.assertEqual(
            workflow["completed_steps_json"],
            ["step00", "step01", "step02"],
        )

    def test_different_version_activation_invalidates_prior_version_artifacts(self) -> None:
        self._activate()
        self._insert_canonical_evidence(
            evidence_id="evidence-eda-v1",
            step_id="step02",
            artifact_type="eda",
        )
        self._activate(expected_revision=1)

        changed = self._activate(
            dataset_id="dataset-1",
            version_id="dataset-version-2",
            expected_revision=1,
        )
        self.assertTrue(changed["changed"])
        self.assertEqual(changed["active_selection"]["activation_revision"], 2)
        workflow = self.service.projects.get_workflow_state("project-activation") or {}
        status = workflow["workflow_status_json"]
        self.assertEqual(status["effectiveCompletedSteps"], ["step00", "step01"])
        self.assertEqual(status["effectiveSteps"]["step02"]["lineageStatus"], "stale")
        self.assertEqual(
            workflow["completed_steps_json"],
            ["step00", "step01", "step02"],
        )

    def test_feature_completion_requires_matching_confirmed_and_materialized_hashes(self) -> None:
        self._activate()
        self.service.projects.upsert_workflow_history(
            "project-activation",
            {
                "current_step_id": "step06",
                "completed_steps_json": ["step05"],
                "workflow_status_json": {},
            },
        )
        self._insert_canonical_evidence(
            evidence_id="feature-evidence-mismatch",
            step_id="step05",
            artifact_type="feature_engineering",
            lineage={
                "manifestVersion": "manifest-good",
                "materializationHash": "materialization-good",
            },
            payload={
                "manifestHash": "manifest-good",
                "confirmedManifestHash": "manifest-other",
                "materializationHash": "materialization-good",
            },
        )
        self._activate(expected_revision=1)
        status = (
            self.service.projects.get_workflow_state("project-activation") or {}
        )["workflow_status_json"]
        self.assertNotIn("step05", status["effectiveCompletedSteps"])

        self._insert_canonical_evidence(
            evidence_id="feature-evidence-current",
            step_id="step05",
            artifact_type="feature_engineering",
            lineage={
                "manifestVersion": "manifest-good",
                "materializationHash": "materialization-good",
            },
            payload={
                "manifestHash": "manifest-good",
                "confirmedManifestHash": "manifest-good",
                "materializationHash": "materialization-good",
            },
        )
        self._activate(expected_revision=1)
        status = (
            self.service.projects.get_workflow_state("project-activation") or {}
        )["workflow_status_json"]
        self.assertIn("step05", status["effectiveCompletedSteps"])
        self.assertEqual(
            status["effectiveSteps"]["step05"]["artifactIds"],
            ["feature-evidence-current"],
        )

    def test_activation_creates_authoritative_fail_closed_workflow_when_missing(self) -> None:
        self.service.projects.upsert(
            {
                "project_id": "project-no-workflow",
                "project_name": "No Workflow Yet",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "owner_user_id": self.user["userId"],
                "metadata_json": {},
            }
        )
        result = self.repository.activate_exact(
            project_id="project-no-workflow",
            dataset_id="dataset-1",
            dataset_version_id="dataset-version-1",
            actor_user_id=self.user["userId"],
        )
        self.assertIsNotNone(result["workflow_effective_state"])
        workflow = self.service.projects.get_workflow_state("project-no-workflow") or {}
        self.assertEqual(workflow["completed_steps_json"], [])
        status = workflow["workflow_status_json"]
        self.assertEqual(status["effectiveCompletedSteps"], [])
        self.assertEqual(status["effectiveCurrentStepId"], "step01")
        self.assertEqual(
            status["datasetIdentity"],
            {
                "project_id": "project-no-workflow",
                "dataset_id": "dataset-1",
                "dataset_version_id": "dataset-version-1",
            },
        )
        self.assertEqual(status["identityValidity"]["activationRevision"], 1)

    def test_browser_workflow_save_cannot_replace_effective_lineage_state(self) -> None:
        self._activate()
        before = self.service.projects.get_workflow_state("project-activation") or {}
        protected_before = before["workflow_status_json"]

        saved = self.service.projects.upsert_workflow_history(
            "project-activation",
            {
                "current_step_id": "step13",
                "completed_steps_json": [f"step{index:02d}" for index in range(14)],
                "workflow_status_json": {
                    "workflowId": "predictive-modeling",
                    "datasetIdentity": {
                        "project_id": "project-activation",
                        "dataset_id": "attacker-dataset",
                        "dataset_version_id": "latest",
                    },
                    "hasDataset": True,
                    "effectiveCompletedSteps": [
                        f"step{index:02d}" for index in range(14)
                    ],
                    "effectiveCurrentStepId": "step13",
                    "identityValidity": {"status": "current"},
                },
                "step_evidence_status_json": {},
                "completed_by": self.user["userId"],
            },
        )
        status = saved["workflow_status_json"]
        for key in (
            "datasetIdentity",
            "hasDataset",
            "effectiveCompletedSteps",
            "effectiveCurrentStepId",
            "effectiveSteps",
            "identityValidity",
        ):
            self.assertEqual(status[key], protected_before[key])
        self.assertEqual(len(saved["completed_steps_json"]), 14)
        self.assertEqual(len(status["historicalCompletedSteps"]), 14)

    def test_browser_workflow_save_cannot_claim_or_audit_project_completion(self) -> None:
        from server.persistence import persistence_router

        self._activate()
        with (
            self._identity_environment(),
            patch.object(
                persistence_router,
                "get_persistence_service",
                return_value=self.service,
            ),
            patch.object(persistence_router, "audit_event") as audit,
        ):
            response = persistence_router.save_workflow_state(
                "project-activation",
                {
                    "currentStepId": "step13",
                    "historicalCompletedSteps": [
                        f"step{index:02d}" for index in range(14)
                    ],
                    "workflowStatus": {
                        "status": "complete",
                        "effectiveCompletedSteps": [
                            f"step{index:02d}" for index in range(14)
                        ],
                    },
                },
                user=self.user,
            )

        status = response["workflowState"]["workflowStatus"]
        self.assertEqual(status.get("status"), "active")
        self.assertNotEqual(status.get("status"), "complete")
        self.assertFalse(
            any(
                call.args and call.args[0] == "project.completed"
                for call in audit.call_args_list
            )
        )

    def test_browser_steps_map_cannot_grant_completion_omitted_from_history(self) -> None:
        self._activate()
        saved = self.service.projects.upsert_workflow_history(
            "project-activation",
            {
                "current_step_id": "step07",
                "completed_steps_json": ["step00", "step01", "step02"],
                "workflow_status_json": {
                    "steps": {
                        "step00": "complete",
                        "step01": "complete",
                        "step02": "complete",
                        "step07": "complete",
                    }
                },
                "completed_by": self.user["userId"],
            },
        )
        self.assertNotIn("step07", saved["workflow_status_json"]["steps"])

        self._activate(expected_revision=1)
        status = (
            self.service.projects.get_workflow_state("project-activation") or {}
        )["workflow_status_json"]
        self.assertNotIn("step07", status["effectiveSteps"])
        self.assertNotIn("step07", status["effectiveCompletedSteps"])

    def test_compare_and_set_serializes_competing_activations(self) -> None:
        self._activate()
        barrier = Barrier(2)

        def compete(dataset_id: str, version_id: str) -> tuple[str, object]:
            repository = ProjectDatasetActivationRepository(Database(self.database_path))
            barrier.wait(timeout=5)
            try:
                result = repository.activate_exact(
                    project_id="project-activation",
                    dataset_id=dataset_id,
                    dataset_version_id=version_id,
                    actor_user_id=self.user["userId"],
                    expected_activation_revision=1,
                )
                return "ok", result
            except ProjectDatasetActivationConflictError as exc:
                return "conflict", exc

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(
                    lambda values: compete(*values),
                    (("dataset-2", "dataset-version-2"), ("dataset-3", "dataset-version-3")),
                )
            )

        self.assertEqual(sorted(outcome[0] for outcome in outcomes), ["conflict", "ok"])
        active = self.repository.get_active_selection("project-activation") or {}
        self.assertEqual(active["activation_revision"], 2)
        self.assertIn(active["dataset_id"], {"dataset-2", "dataset-3"})
        self.assertEqual(self._event_count("modeling_dataset_activated"), 2)

    def test_failure_rolls_back_link_selection_event_and_workflow(self) -> None:
        before = self.service.projects.get_workflow_state("project-activation")
        with patch.object(
            ProjectDatasetActivationRepository,
            "_reconcile_workflow_identity",
            side_effect=RuntimeError("injected reconciliation failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected reconciliation failure"):
                self._activate()

        self.assertIsNone(self.repository.get_link("project-activation", "dataset-1"))
        self.assertIsNone(self.repository.get_active_selection("project-activation"))
        self.assertEqual(self._event_count("modeling_dataset_activated"), 0)
        self.assertEqual(
            self.service.projects.get_workflow_state("project-activation"),
            before,
        )

    def test_contradiction_and_unlink_fail_workflow_closed_without_losing_history(self) -> None:
        self._activate()
        contradiction = self.repository.record_contradiction(
            project_id="project-activation",
            actor_user_id=self.user["userId"],
            reason="Registered artifact checksum does not match durable identity.",
        )
        self.assertTrue(contradiction["changed"])
        self.assertEqual(
            contradiction["active_selection"]["activation_status"],
            "contradictory",
        )
        self.assertEqual(contradiction["active_selection"]["activation_revision"], 1)
        repeated = self.repository.record_contradiction(
            project_id="project-activation",
            actor_user_id=self.user["userId"],
            reason="Registered artifact checksum does not match durable identity.",
        )
        self.assertFalse(repeated["changed"])
        self.assertEqual(
            self._event_count("modeling_dataset_contradiction_detected"),
            1,
        )
        workflow = self.service.projects.get_workflow_state("project-activation") or {}
        self.assertEqual(
            workflow["workflow_status_json"]["identityValidity"]["status"],
            "contradictory",
        )
        self.assertEqual(workflow["completed_steps_json"], ["step00", "step01", "step02"])

        # A deliberate reactivation advances the revision and may repair the
        # diagnostic state; unlink then removes effective access without
        # deleting the historical selection identity.
        repaired = self._activate(expected_revision=1)
        self.assertEqual(repaired["active_selection"]["activation_revision"], 2)
        unlinked = self.repository.unlink_dataset(
            project_id="project-activation",
            dataset_id="dataset-1",
            actor_user_id=self.user["userId"],
        )
        self.assertEqual(unlinked["removed"], 1)
        self.assertEqual(unlinked["active_selection"]["activation_status"], "inactive")
        self.assertEqual(unlinked["active_selection"]["activation_revision"], 3)
        self.assertEqual(
            self.repository.get_link("project-activation", "dataset-1")["link_status"],
            "unlinked",
        )

    def test_unlink_audit_uses_lineage_only_when_removing_active_selection(self) -> None:
        self._activate()
        self.repository.authorize_link(
            project_id="project-activation",
            dataset_id="dataset-2",
            actor_user_id=self.user["userId"],
        )

        non_active = self.repository.unlink_dataset(
            project_id="project-activation",
            dataset_id="dataset-2",
            actor_user_id=self.user["userId"],
        )
        self.assertEqual(non_active["active_selection"]["dataset_id"], "dataset-1")
        self.assertEqual(non_active["active_selection"]["activation_revision"], 1)
        with self.database.connection() as connection:
            non_active_event = connection.execute(
                """
                SELECT * FROM project_dataset_activation_events
                WHERE project_id = ? AND dataset_id = ?
                  AND event_type = 'project_dataset_unlinked'
                ORDER BY created_at DESC LIMIT 1
                """,
                ("project-activation", "dataset-2"),
            ).fetchone()
        self.assertIsNotNone(non_active_event)
        self.assertIsNone(non_active_event["dataset_version_id"])
        self.assertIsNone(non_active_event["activation_revision"])

        active = self.repository.unlink_dataset(
            project_id="project-activation",
            dataset_id="dataset-1",
            actor_user_id=self.user["userId"],
        )
        self.assertEqual(active["active_selection"]["activation_revision"], 2)
        with self.database.connection() as connection:
            active_event = connection.execute(
                """
                SELECT * FROM project_dataset_activation_events
                WHERE project_id = ? AND dataset_id = ?
                  AND event_type = 'project_dataset_unlinked'
                ORDER BY created_at DESC LIMIT 1
                """,
                ("project-activation", "dataset-1"),
            ).fetchone()
        self.assertIsNotNone(active_event)
        self.assertEqual(active_event["dataset_version_id"], "dataset-version-1")
        self.assertEqual(active_event["activation_revision"], 2)

    def test_project_delete_cascades_current_state_but_preserves_deactivation_event(self) -> None:
        self._activate()
        self.repository.deactivate_project(
            project_id="project-activation",
            actor_user_id=self.user["userId"],
        )
        self.assertTrue(self.service.projects.delete("project-activation"))
        self.assertIsNone(self.repository.get_active_selection("project-activation"))
        self.assertEqual(self.repository.list_links("project-activation"), [])
        self.assertEqual(self._event_count("project_dataset_deactivated"), 1)

    def test_active_selection_has_composite_foreign_key_to_project_link(self) -> None:
        with self.database.connection() as connection:
            rows = connection.execute(
                "PRAGMA foreign_key_list(active_modeling_dataset_versions)"
            ).fetchall()
        link_columns = {
            (row["from"], row["to"])
            for row in rows
            if row["table"] == "project_dataset_links"
        }
        self.assertEqual(
            link_columns,
            {("project_id", "project_id"), ("dataset_id", "dataset_id")},
        )

    def test_link_write_failure_cannot_return_activation_success(self) -> None:
        from server.datasets import dataset_router

        with self.database.transaction() as connection:
            connection.execute(
                """
                CREATE TRIGGER fail_project_dataset_link
                BEFORE INSERT ON project_dataset_links
                BEGIN
                  SELECT RAISE(ABORT, 'injected durable link failure');
                END
                """
            )
        with (
            self._identity_environment(),
            patch.object(dataset_router, "get_persistence_service", return_value=self.service),
            patch.object(dataset_router, "_mirror_legacy_link"),
            patch.object(dataset_router, "schedule_checkpoint_save"),
        ):
            with self.assertRaisesRegex(sqlite3.IntegrityError, "durable link failure"):
                dataset_router.activate_dataset_version(
                    "dataset-1",
                    "dataset-version-1",
                    project_id="project-activation",
                    expected_activation_revision=None,
                    user=self.user,
                )
        self.assertIsNone(self.repository.get_link("project-activation", "dataset-1"))
        self.assertIsNone(self.repository.get_active_selection("project-activation"))

    def test_active_selection_write_failure_rolls_back_new_link(self) -> None:
        from server.datasets import dataset_router

        with self.database.transaction() as connection:
            connection.execute(
                """
                CREATE TRIGGER fail_active_dataset_selection
                BEFORE INSERT ON active_modeling_dataset_versions
                BEGIN
                  SELECT RAISE(ABORT, 'injected durable selection failure');
                END
                """
            )
        with (
            self._identity_environment(),
            patch.object(dataset_router, "get_persistence_service", return_value=self.service),
            patch.object(dataset_router, "_mirror_legacy_link"),
            patch.object(dataset_router, "schedule_checkpoint_save"),
        ):
            with self.assertRaisesRegex(sqlite3.IntegrityError, "selection failure"):
                dataset_router.activate_dataset_version(
                    "dataset-1",
                    "dataset-version-1",
                    project_id="project-activation",
                    expected_activation_revision=None,
                    user=self.user,
                )
        self.assertIsNone(self.repository.get_link("project-activation", "dataset-1"))
        self.assertIsNone(self.repository.get_active_selection("project-activation"))

    def test_successful_activation_response_contains_authoritative_contract(self) -> None:
        from server.datasets import dataset_router

        store = DatasetStore()
        results = ResultStore()
        with (
            self._identity_environment(),
            patch.object(dataset_router, "get_persistence_service", return_value=self.service),
            patch.object(dataset_router, "_mirror_legacy_link"),
            patch.object(dataset_router, "schedule_checkpoint_save"),
            patch.object(DatasetStoreProxy, "current", return_value=store),
            patch.object(ResultStoreProxy, "current", return_value=results),
        ):
            response = dataset_router.activate_dataset_version(
                "dataset-1",
                "dataset-version-1",
                project_id="project-activation",
                expected_activation_revision=None,
                user=self.user,
            )
        self.assertTrue(response["ok"])
        self.assertEqual(response["dataset_id"], "dataset-1")
        self.assertEqual(response["dataset_version_id"], "dataset-version-1")
        self.assertEqual(response["activation_revision"], 1)
        self.assertEqual(response["link"]["link_status"], "active")
        self.assertEqual(
            response["active_selection"]["activation_status"],
            "active",
        )
        self.assertEqual(store.meta["dataset_version_id"], "dataset-version-1")

    def test_post_commit_runtime_failure_is_compensated_as_contradictory(self) -> None:
        from server.datasets import dataset_router

        store = DatasetStore()
        results = ResultStore()
        with (
            self._identity_environment(),
            patch.object(dataset_router, "get_persistence_service", return_value=self.service),
            patch.object(dataset_router, "_mirror_legacy_link"),
            patch.object(dataset_router, "schedule_checkpoint_save"),
            patch.object(DatasetStoreProxy, "current", return_value=store),
            patch.object(ResultStoreProxy, "current", return_value=results),
            patch.object(
                dataset_router,
                "stamp_active_dataset_identity",
                side_effect=RuntimeError("injected cache hydration failure"),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                dataset_router.activate_dataset_version(
                    "dataset-1",
                    "dataset-version-1",
                    project_id="project-activation",
                    expected_activation_revision=None,
                    user=self.user,
                )
        self.assertEqual(raised.exception.status_code, 500)
        selection = self.repository.get_active_selection("project-activation") or {}
        self.assertEqual(selection["activation_status"], "contradictory")
        self.assertEqual(selection["dataset_version_id"], "dataset-version-1")
        self.assertEqual(selection["activation_revision"], 1)

    def test_two_links_never_choose_the_first_dataset(self) -> None:
        for dataset_id in ("dataset-1", "dataset-2"):
            self.repository.authorize_link(
                project_id="project-activation",
                dataset_id=dataset_id,
                actor_user_id=self.user["userId"],
            )
        with self._identity_environment():
            with self.assertRaises(HTTPException) as raised:
                durable_active_dataset_identity(
                    "project-activation",
                    user=self.user,
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIsNone(self.repository.get_active_selection("project-activation"))

    def test_multiple_versions_never_choose_latest_version(self) -> None:
        self._activate(version_id="dataset-version-1")
        store = DatasetStore()
        with self._identity_environment():
            identity = active_dataset_identity(
                "project-activation",
                user=self.user,
                store=store,
            )
        self.assertEqual(identity["dataset_version_id"], "dataset-version-1")
        self.assertNotEqual(identity["dataset_version_id"], "dataset-version-2")

    def test_active_identity_endpoint_returns_exact_triple_before_restart(self) -> None:
        from server.core import metadata_router

        self._activate()
        store = DatasetStore()
        with (
            self._identity_environment(),
            patch.object(DatasetStoreProxy, "current", return_value=store),
        ):
            response = metadata_router.get_active_identity(
                project_id="project-activation",
                user=self.user,
            )
        self.assertTrue(response["ok"])
        self.assertEqual(response["project_id"], "project-activation")
        self.assertEqual(response["dataset_id"], "dataset-1")
        self.assertEqual(response["dataset_version_id"], "dataset-version-1")
        self.assertEqual(response["activation_revision"], 1)

    def test_exact_identity_survives_persistence_service_reinitialization(self) -> None:
        self._activate()
        restarted_service = PersistenceService(Database(self.database_path))
        restarted_store = DatasetStore()
        with self._identity_environment(service=restarted_service):
            identity = active_dataset_identity(
                "project-activation",
                user=self.user,
                store=restarted_store,
            )
        self.assertEqual(
            (
                identity["project_id"],
                identity["dataset_id"],
                identity["dataset_version_id"],
                identity["activation_revision"],
            ),
            ("project-activation", "dataset-1", "dataset-version-1", 1),
        )

    def test_empty_runtime_cache_rehydrates_only_exact_durable_artifact(self) -> None:
        self._activate(version_id="dataset-version-1")
        store = DatasetStore()
        store.meta.update(
            {
                "project_id": "project-activation",
                "dataset_id": "dataset-1",
                "dataset_version_id": "dataset-version-2",
                "dataset_identity_status": "current",
            }
        )
        with self._identity_environment():
            identity = active_dataset_identity(
                "project-activation",
                user=self.user,
                store=store,
            )
        self.assertEqual(identity["dataset_version_id"], "dataset-version-1")
        self.assertEqual(store.meta["dataset_version_id"], "dataset-version-1")
        self.assertEqual(list(store.raw_df.columns), ["feature", "target"])

    def test_checkpoint_identity_cannot_grant_access_without_active_link(self) -> None:
        self._activate()
        checkpoint_store = DatasetStore()
        checkpoint_store.meta.update(
            {
                "project_id": "project-activation",
                "dataset_id": "dataset-1",
                "dataset_version_id": "dataset-version-1",
                "dataset_identity_status": "current",
                "activation_revision": 1,
            }
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE project_dataset_links SET link_status = 'unlinked'
                WHERE project_id = ? AND dataset_id = ?
                """,
                ("project-activation", "dataset-1"),
            )
        with (
            self._identity_environment(),
            patch("server.datasets.dataset_identity.get_user", return_value=self.user),
        ):
            valid, reason, identity = validate_checkpoint_identity(
                checkpoint_store,
                owner_user_id=self.user["userId"],
                project_id="project-activation",
            )
        self.assertFalse(valid)
        self.assertIsNone(identity)
        self.assertIn("contradictory", reason.casefold())

    def test_valid_link_without_selection_does_not_choose_any_version(self) -> None:
        self.repository.authorize_link(
            project_id="project-activation",
            dataset_id="dataset-1",
            actor_user_id=self.user["userId"],
        )
        with self._identity_environment():
            with self.assertRaises(HTTPException) as raised:
                durable_active_dataset_identity(
                    "project-activation",
                    user=self.user,
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("No exact", str(raised.exception.detail))

    def test_active_selection_with_inactive_link_is_diagnosed_contradictory(self) -> None:
        self._activate()
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE project_dataset_links SET link_status = 'revoked'
                WHERE project_id = ? AND dataset_id = ?
                """,
                ("project-activation", "dataset-1"),
            )
        with self._identity_environment():
            with self.assertRaises(HTTPException) as raised:
                durable_active_dataset_identity(
                    "project-activation",
                    user=self.user,
                )
        self.assertEqual(raised.exception.status_code, 409)
        selection = self.repository.get_active_selection("project-activation") or {}
        self.assertEqual(selection["activation_status"], "contradictory")
        self.assertEqual(selection["activation_revision"], 1)

    def test_missing_registered_version_fails_closed_and_preserves_diagnostic(self) -> None:
        self._activate()
        self._write_dataset_library(omit_v1=True)
        with self._identity_environment():
            with self.assertRaises(HTTPException) as raised:
                durable_active_dataset_identity(
                    "project-activation",
                    user=self.user,
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            (self.repository.get_active_selection("project-activation") or {})[
                "activation_status"
            ],
            "contradictory",
        )

    def test_archived_registered_dataset_fails_closed(self) -> None:
        self._activate()
        self._write_dataset_library(archived=True)
        with self._identity_environment():
            with self.assertRaises(HTTPException) as raised:
                durable_active_dataset_identity(
                    "project-activation",
                    user=self.user,
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            (self.repository.get_active_selection("project-activation") or {})[
                "activation_status"
            ],
            "contradictory",
        )

    def test_cross_project_version_resolution_requires_its_own_link(self) -> None:
        self.service.projects.upsert(
            {
                "project_id": "project-other",
                "project_name": "Other Project",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "owner_user_id": self.user["userId"],
                "metadata_json": {},
            }
        )
        self.repository.activate_exact(
            project_id="project-other",
            dataset_id="dataset-2",
            dataset_version_id="dataset-version-3",
            actor_user_id=self.user["userId"],
        )
        with self._identity_environment():
            with self.assertRaises(HTTPException) as raised:
                resolve_project_dataset_identity(
                    "project-activation",
                    "dataset-2",
                    "dataset-version-3",
                    user=self.user,
                )
        self.assertEqual(raised.exception.status_code, 409)

    def test_cross_user_project_access_fails_before_identity_disclosure(self) -> None:
        from server.core import metadata_router

        self._activate()
        intruder = {
            "userId": "intruder",
            "displayName": "Intruder",
            "email": "intruder@example.test",
            "role": "data_scientist",
        }
        self.service.sync_user(intruder)
        with self._identity_environment():
            with self.assertRaises(HTTPException) as raised:
                metadata_router.get_active_identity(
                    project_id="project-activation",
                    user=intruder,
                )
        self.assertEqual(raised.exception.status_code, 403)

    def test_anonymous_identity_resolution_cannot_inherit_authenticated_selection(self) -> None:
        self._activate()
        with self._identity_environment():
            with self.assertRaises(HTTPException) as raised:
                durable_active_dataset_identity(
                    "project-activation",
                    user=None,
                )
        self.assertIn(raised.exception.status_code, {401, 403})

    def test_authorized_project_serialization_returns_durable_link_and_selection(self) -> None:
        from server.persistence import persistence_router

        self._activate()
        with (
            self._identity_environment(),
            patch.object(
                persistence_router,
                "get_persistence_service",
                return_value=self.service,
            ),
            patch.object(persistence_router, "audit_event"),
        ):
            response = persistence_router.get_project(
                "project-activation",
                user=self.user,
            )
        project = response["project"]
        self.assertEqual(len(project["links"]), 1)
        self.assertEqual(project["links"][0]["datasetId"], "dataset-1")
        self.assertEqual(
            project["activeSelection"]["datasetVersionId"],
            "dataset-version-1",
        )

    def test_project_collaborator_without_dataset_acl_cannot_discover_durable_identity(self) -> None:
        from server.datasets import dataset_router
        from server.persistence import persistence_router

        self._activate()
        collaborator = self._project_collaborator()
        with (
            self._identity_environment(),
            patch.object(
                persistence_router,
                "get_persistence_service",
                return_value=self.service,
            ),
            patch.object(
                dataset_router,
                "get_persistence_service",
                return_value=self.service,
            ),
            patch.object(persistence_router, "audit_event"),
        ):
            listed = persistence_router.list_projects(user=collaborator)
            detailed = persistence_router.get_project(
                "project-activation",
                user=collaborator,
            )
            dataset_state = dataset_router.get_project_links(
                "project-activation",
                user=collaborator,
            )
            workflow_state = persistence_router.get_workflow_state(
                "project-activation",
                user=collaborator,
            )

        listed_project = next(
            item
            for item in listed["projects"]
            if item["projectId"] == "project-activation"
        )
        self.assertEqual(listed_project["links"], [])
        self.assertIsNone(listed_project["activeSelection"])
        self.assertEqual(detailed["project"]["links"], [])
        self.assertIsNone(detailed["project"]["activeSelection"])
        self.assertEqual(dataset_state["links"], [])
        self.assertIsNone(dataset_state["active_selection"])
        workflow_status = workflow_state["workflowState"]["workflowStatus"]
        self.assertIsNone(workflow_status["datasetIdentity"])
        self.assertEqual(
            workflow_status["identityValidity"]["status"],
            "unauthorized",
        )
        self.assertEqual(workflow_status["effectiveCompletedSteps"], ["step00"])
        self.assertNotIn("dataset-1", json.dumps(listed_project))
        self.assertNotIn("dataset-version-1", json.dumps(detailed))
        self.assertNotIn("dataset-1", json.dumps(dataset_state))
        self.assertNotIn("dataset-1", json.dumps(workflow_state))
        self.assertNotIn("dataset-version-1", json.dumps(workflow_state))

    def test_project_editor_without_dataset_acl_cannot_unlink_guessed_dataset_id(self) -> None:
        from server.datasets import dataset_router

        self._activate()
        collaborator = self._project_collaborator(permission_level="edit")
        with (
            self._identity_environment(),
            patch.object(
                dataset_router,
                "get_persistence_service",
                return_value=self.service,
            ),
            patch.object(dataset_router, "audit_event"),
            patch.object(dataset_router, "unlink_project_dataset") as legacy_unlink,
        ):
            with self.assertRaises(HTTPException) as raised:
                dataset_router.delete_project_link(
                    "project-activation",
                    "dataset-1",
                    user=collaborator,
                )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(
            raised.exception.detail,
            "Project dataset link was not found.",
        )
        legacy_unlink.assert_not_called()
        self.assertEqual(
            self.repository.get_link("project-activation", "dataset-1")["link_status"],
            "active",
        )
        self.assertEqual(
            self.repository.get_active_selection("project-activation")[
                "dataset_version_id"
            ],
            "dataset-version-1",
        )
        self.assertEqual(self._event_count("project_dataset_unlinked"), 0)

    def test_project_collaborator_with_dataset_acl_sees_exact_durable_identity(self) -> None:
        from server.datasets import dataset_router
        from server.persistence import persistence_router

        self._activate()
        collaborator = self._project_collaborator()
        self._grant_dataset_view(collaborator["userId"])
        with (
            self._identity_environment(),
            patch.object(
                persistence_router,
                "get_persistence_service",
                return_value=self.service,
            ),
            patch.object(
                dataset_router,
                "get_persistence_service",
                return_value=self.service,
            ),
            patch.object(persistence_router, "audit_event"),
        ):
            listed = persistence_router.list_projects(user=collaborator)
            detailed = persistence_router.get_project(
                "project-activation",
                user=collaborator,
            )
            dataset_state = dataset_router.get_project_links(
                "project-activation",
                user=collaborator,
            )
            workflow_state = persistence_router.get_workflow_state(
                "project-activation",
                user=collaborator,
            )

        listed_project = next(
            item
            for item in listed["projects"]
            if item["projectId"] == "project-activation"
        )
        self.assertEqual(listed_project["links"][0]["datasetId"], "dataset-1")
        self.assertEqual(
            listed_project["activeSelection"]["datasetVersionId"],
            "dataset-version-1",
        )
        self.assertEqual(detailed["project"]["links"][0]["datasetId"], "dataset-1")
        self.assertEqual(
            detailed["project"]["activeSelection"]["datasetVersionId"],
            "dataset-version-1",
        )
        self.assertEqual(dataset_state["links"][0]["datasetId"], "dataset-1")
        self.assertEqual(
            dataset_state["active_selection"]["datasetVersionId"],
            "dataset-version-1",
        )
        workflow_status = workflow_state["workflowState"]["workflowStatus"]
        self.assertEqual(
            workflow_status["datasetIdentity"]["dataset_id"],
            "dataset-1",
        )
        self.assertEqual(
            workflow_status["datasetIdentity"]["dataset_version_id"],
            "dataset-version-1",
        )


if __name__ == "__main__":
    unittest.main()

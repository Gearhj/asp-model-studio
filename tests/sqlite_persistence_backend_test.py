from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.persistence.db import Database, PersistenceUnavailableError
from server.persistence.persistence_router import (
    _evidence_record,
    delete_project,
    get_project,
    persistence_health,
    update_project,
)
from server.persistence.service import PersistenceService
from server.security import security_store


TEST_USER = {
    "userId": "test-user",
    "displayName": "Persistence Tester",
    "email": "persistence@atlas.local",
    "role": "data_scientist",
    "status": "active",
}
SEEDED_ADMIN_USER_ID = "user_eecc3a44ed694307"


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request_json(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    request = Request(url, headers=headers or {}, method="GET")
    try:
        with urlopen(request, timeout=3) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8"))


class SqlitePersistenceBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = Path(__file__).resolve().parents[1] / "server" / "data" / "atlas_persistence_test.db"
        self._remove_database_files()
        self.database = Database(self.database_path)
        self.health = self.database.initialize()
        self.service = PersistenceService(self.database)
        self.service.sync_user(TEST_USER)
        self.project = self.service.projects.upsert(
            {
                "project_id": "project-1",
                "project_name": "SQLite Test Project",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "owner_user_id": TEST_USER["userId"],
                "metadata_json": {"modelId": "00001"},
            }
        )

    def tearDown(self) -> None:
        self._remove_database_files()

    def _remove_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_database_initialization_creates_required_tables_without_dropping_data(self) -> None:
        expected = {
            "projects",
            "workflow_state",
            "datasets",
            "dataset_versions",
            "evidence_artifacts",
            "run_records",
            "decision_journal",
            "documentation_packages",
            "export_artifacts",
            "users",
            "schema_migrations",
            "audit_log",
            "demo_feedback",
        }
        self.assertTrue(self.health["ok"])
        self.assertTrue(expected.issubset(set(self.health["tables"])))
        with self.database.connection() as connection:
            applied_migrations = {
                row["version"]
                for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
            }
        self.assertIn("0004_export_storage_backfill.sql", applied_migrations)
        self.database.initialize()
        self.assertEqual(self.service.projects.get("project-1")["project_name"], "SQLite Test Project")

    def test_export_storage_backfill_normalizes_legacy_paths(self) -> None:
        timestamp = "2026-07-15T00:00:00+00:00"
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO export_artifacts (
                  export_id, project_id, export_type, file_name, file_path,
                  created_by, created_at, artifact_hash, metadata_json, storage_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-client-export",
                    "project-1",
                    "governed_json",
                    "legacy.json",
                    "-",
                    TEST_USER["userId"],
                    timestamp,
                    "legacy-hash",
                    "{}",
                    "client_generated",
                ),
            )
            connection.execute(
                """
                INSERT INTO export_artifacts (
                  export_id, project_id, export_type, file_name, file_path,
                  created_by, created_at, artifact_hash, metadata_json, storage_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "server-file-export",
                    "project-1",
                    "optimization_report",
                    "report.pdf",
                    "C:/atlas/exports/report.pdf",
                    TEST_USER["userId"],
                    timestamp,
                    "server-hash",
                    "{}",
                    "client_generated",
                ),
            )
            migration = Path(__file__).resolve().parents[1] / "server" / "persistence" / "migrations" / "0004_export_storage_backfill.sql"
            connection.executescript(migration.read_text(encoding="utf-8"))

        client_export = self.service.exports.get("legacy-client-export")
        server_export = self.service.exports.get("server-file-export")
        self.assertEqual(client_export["storage_mode"], "client_generated")
        self.assertEqual(client_export["file_path"], "not_applicable_client_download")
        self.assertEqual(server_export["storage_mode"], "server_file")
        self.assertEqual(server_export["file_path"], "C:/atlas/exports/report.pdf")

    def test_project_create_read_and_update(self) -> None:
        self.assertEqual(self.project["metadata_json"]["modelId"], "00001")
        updated = self.service.projects.upsert({**self.project, "project_name": "Updated Project", "metadata_json": {"modelId": "00002"}})
        self.assertEqual(updated["project_name"], "Updated Project")
        self.assertEqual(self.service.projects.get("project-1")["metadata_json"]["modelId"], "00002")

    def test_project_delete_cascades_project_scoped_records(self) -> None:
        self.service.projects.upsert_workflow_state(
            "project-1",
            {
                "current_step_id": "step02",
                "completed_steps_json": ["step01"],
                "workflow_status_json": {},
                "step_evidence_status_json": {},
            },
        )
        self.service.evidence.upsert(
            {
                "evidence_id": "delete-evidence",
                "project_id": "project-1",
                "artifact_type": "eda",
                "title": "Delete test evidence",
                "status": "ready",
                "payload_json": {},
            }
        )
        self.assertTrue(self.service.projects.delete("project-1"))
        self.assertIsNone(self.service.projects.get("project-1"))
        self.assertIsNone(self.service.projects.get_workflow_state("project-1"))
        self.assertEqual(self.service.evidence.list_for_project("project-1"), [])

    def test_delete_project_api_removes_persisted_project(self) -> None:
        with patch.dict(os.environ, {"ATLAS_SQLITE_PATH": str(self.database_path)}):
            update_project(
                "delete-api-project",
                {"projectName": "Delete API Project", "projectType": "optimization", "workflowType": "optimization"},
                TEST_USER,
            )
            result = delete_project("delete-api-project", TEST_USER)
            self.assertTrue(result["deleted"])
            with self.assertRaises(Exception) as context:
                get_project("delete-api-project", TEST_USER)
            self.assertEqual(getattr(context.exception, "status_code", None), 404)

    def test_transportation_template_persists_and_legacy_inference_is_safe(self) -> None:
        saved = self.service.projects.upsert(
            {
                "project_id": "transportation-project",
                "project_name": "Cash Logistics Transportation QA",
                "project_type": "optimization",
                "workflow_type": "optimization",
                "template_id": "transportation_logistics",
                "owner_user_id": TEST_USER["userId"],
                "metadata_json": {"optimizationTemplateId": "transportation_logistics"},
            }
        )
        self.assertEqual(saved["template_id"], "transportation_logistics")
        self.assertEqual(self.service.projects.get("transportation-project")["template_id"], "transportation_logistics")

        self.service.projects.upsert(
            {
                "project_id": "legacy-transportation-project",
                "project_name": "Legacy Transportation Network",
                "project_type": "optimization",
                "workflow_type": "optimization",
                "template_id": None,
                "owner_user_id": TEST_USER["userId"],
                "metadata_json": {},
            }
        )
        self.service.projects.upsert(
            {
                "project_id": "generic-optimization-project",
                "project_name": "Generic Resource Optimization",
                "project_type": "optimization",
                "workflow_type": "optimization",
                "template_id": None,
                "owner_user_id": TEST_USER["userId"],
                "metadata_json": {},
            }
        )
        migration = Path(__file__).resolve().parents[1] / "server" / "persistence" / "migrations" / "0002_optimization_template_id.sql"
        with self.database.transaction() as connection:
            connection.executescript(migration.read_text(encoding="utf-8"))
        self.assertEqual(self.service.projects.get("legacy-transportation-project")["template_id"], "transportation_logistics")
        self.assertIsNone(self.service.projects.get("generic-optimization-project")["template_id"])

    def test_workflow_state_save_and_load(self) -> None:
        saved = self.service.projects.upsert_workflow_state(
            "project-1",
            {
                "current_step_id": "step02",
                "completed_steps_json": ["step00", "step01"],
                "workflow_status_json": {"step02": "in_progress"},
                "step_evidence_status_json": {"step01": "ready"},
            },
        )
        self.assertEqual(saved["completed_steps_json"], ["step00", "step01"])
        self.assertEqual(self.service.projects.get_workflow_state("project-1")["current_step_id"], "step02")

    def test_evidence_run_documentation_export_and_decision_round_trip(self) -> None:
        evidence = self.service.evidence.upsert(
            {
                "evidence_id": "evidence-1",
                "project_id": "project-1",
                "workflow_type": "predictive-modeling",
                "step_id": "step02",
                "artifact_type": "eda",
                "title": "EDA Evidence",
                "status": "ready",
                "payload_json": {"rows": 100},
            }
        )
        run = self.service.runs.upsert(
            {
                "run_id": "run-1",
                "project_id": "project-1",
                "run_type": "model_training",
                "status": "complete",
                "parameters_json": {"algorithm": "logistic_regression"},
                "metrics_json": {"auc": 0.81},
            }
        )
        decision = self.service.decisions.upsert(
            {
                "decision_id": "decision-1",
                "project_id": "project-1",
                "decision_type": "champion_selection",
                "title": "Select champion",
                "payload_json": {"model": "Logistic Regression"},
            }
        )
        package = self.service.documentation.upsert(
            {
                "package_id": "package-1",
                "project_id": "project-1",
                "package_type": "model_development_document",
                "status": "ready",
                "readiness_score": 92,
                "section_count": 12,
                "completed_section_count": 11,
                "payload_json": {"quality": "ready"},
            }
        )
        exported = self.service.exports.upsert(
            {
                "export_id": "export-1",
                "project_id": "project-1",
                "export_type": "word",
                "file_name": "model-document.docx",
                "metadata_json": {"sizeBytes": 1024},
            }
        )
        self.assertEqual(evidence["payload_json"]["rows"], 100)
        self.assertAlmostEqual(run["metrics_json"]["auc"], 0.81)
        self.assertEqual(decision["payload_json"]["model"], "Logistic Regression")
        self.assertEqual(package["completed_section_count"], 11)
        self.assertEqual(exported["metadata_json"]["sizeBytes"], 1024)
        self.assertEqual(exported["storage_mode"], "client_generated")
        self.assertEqual(exported["file_path"], "not_applicable_client_download")
        self.assertEqual(len(self.service.evidence.list_for_project("project-1")), 1)
        self.assertEqual(len(self.service.runs.list_for_project("project-1")), 1)
        self.assertEqual(len(self.service.documentation.list_for_project("project-1")), 1)
        self.assertEqual(len(self.service.exports.list_for_project("project-1")), 1)

    def test_optimization_artifact_contract_round_trip(self) -> None:
        project_id = "optimization-contract-project"
        self.service.projects.upsert(
            {
                "project_id": project_id,
                "project_name": "Optimization Contract Project",
                "project_type": "optimization",
                "workflow_type": "optimization",
                "template_id": "transportation_logistics",
                "owner_user_id": TEST_USER["userId"],
                "metadata_json": {},
            }
        )
        run_contracts = {
            "optimization_input_normalization": ({"route_count": 42, "required_inputs_loaded": 5}, {"normalization_hash": "normalize-1"}),
            "optimization_solver": ({"solver_status": "optimal", "business_validity": "valid", "total_cost": 100.0}, {"decision_vector": [1, 2]}),
            "optimization_scenarios": ({"scenario_count": 4, "feasible_count": 4}, {"scenario_results": [{"name": "base"}]}),
            "optimization_sensitivity": ({"top_driver": "route_cost", "top_driver_cost_impact": 12.5}, {"tornado_results": []}),
            "optimization_validation": ({"validation_score": 100, "gate_status": "pass"}, {"validation_checklist": ["passed"]}),
        }
        for index, (run_type, (metrics, artifacts)) in enumerate(run_contracts.items(), start=1):
            self.service.runs.upsert(
                {
                    "run_id": f"optimization-run-{index}",
                    "project_id": project_id,
                    "run_type": run_type,
                    "workflow_type": "optimization",
                    "status": "complete",
                    "metrics_json": metrics,
                    "artifacts_json": artifacts,
                }
            )
        saved_runs = self.service.runs.list_for_project(project_id)
        self.assertEqual({run["run_type"] for run in saved_runs}, set(run_contracts))
        self.assertEqual(next(run for run in saved_runs if run["run_type"] == "optimization_solver")["metrics_json"]["business_validity"], "valid")

        allowed_statuses = {"generated", "captured", "ready", "approved", "stale", "rejected"}
        for index, requested_status in enumerate(("draft", "accepted", "ready", "stale"), start=1):
            record = _evidence_record(
                project_id,
                f"optimization-evidence-{index}",
                {
                    "workflowType": "optimization",
                    "stepId": f"optimization-{index}",
                    "artifactType": "optimization_validation",
                    "status": requested_status,
                    "title": "Optimization evidence",
                    "payload": {"statusSource": requested_status},
                },
                TEST_USER,
            )
            saved_evidence = self.service.evidence.upsert(record)
            self.assertIn(saved_evidence["status"], allowed_statuses)
        statuses = {item["status"] for item in self.service.evidence.list_for_project(project_id)}
        self.assertIn("generated", statuses)
        self.assertIn("approved", statuses)

        required_artifact_types = {
            "optimization_decision_charter",
            "optimization_input_bundle",
            "optimization_route_normalization",
            "optimization_formulation_readiness",
            "optimization_objective",
            "optimization_decision_variables",
            "optimization_constraints",
            "optimization_solver_configuration",
            "optimization_scenarios",
            "optimization_solution",
            "optimization_sensitivity",
            "optimization_validation",
            "optimization_recommendation",
            "optimization_implementation_plan",
            "optimization_monitoring_plan",
            "optimization_documentation_package",
            "optimization_reproducibility_code",
            "optimization_export",
        }
        for index, artifact_type in enumerate(sorted(required_artifact_types), start=1):
            self.service.evidence.upsert({
                "evidence_id": f"required-optimization-evidence-{index}",
                "project_id": project_id,
                "workflow_type": "optimization",
                "step_id": f"optimization-{min(index, 14)}",
                "artifact_type": artifact_type,
                "title": artifact_type.replace("_", " ").title(),
                "status": "captured",
                "created_by": TEST_USER["userId"],
                "payload_json": {"contract": "overnight-foundation"},
            })
        self.assertTrue(required_artifact_types.issubset({item["artifact_type"] for item in self.service.evidence.list_for_project(project_id)}))

        package = self.service.documentation.upsert(
            {
                "package_id": "optimization-study-package",
                "project_id": project_id,
                "package_type": "optimization_study",
                "status": "complete",
                "readiness_score": 100,
                "section_count": 20,
                "completed_section_count": 20,
                "payload_json": {"executiveSummary": "Ready", "reproducibilityAppendix": ["python", "sas"]},
            }
        )
        self.assertEqual((package["readiness_score"], package["completed_section_count"]), (100.0, 20))

        required_export_types = {
            "governed_json",
            "allocation_csv",
            "reproducibility_evidence",
            "optimization_report",
            "python_code",
            "sas_compatible_code",
        }
        for export_type in required_export_types:
            self.service.exports.upsert({
                "export_id": f"optimization-export-{export_type}",
                "project_id": project_id,
                "export_type": export_type,
                "file_name": f"{export_type}.txt",
                "created_by": TEST_USER["userId"],
                "artifact_hash": f"hash-{export_type}",
                "metadata_json": {"delivery": "browser_download", "clientOnly": True},
            })
        self.assertEqual({item["export_type"] for item in self.service.exports.list_for_project(project_id)}, required_export_types)

        required_decisions = {
            "formulation_strategy_selected",
            "input_bundle_confirmed",
            "solver_result_accepted",
            "validation_completed",
            "recommendation_recommended",
            "implementation_plan_completed",
            "optimization_study_completed",
        }
        for decision_type in required_decisions:
            self.service.decisions.upsert({
                "decision_id": f"decision-{decision_type}",
                "project_id": project_id,
                "decision_type": decision_type,
                "title": decision_type.replace("_", " ").title(),
                "status": "approved",
                "owner": TEST_USER["displayName"],
                "payload_json": {"contract": "overnight-foundation"},
            })
        self.assertEqual({item["decision_type"] for item in self.service.decisions.list_for_project(project_id)}, required_decisions)

        exported = self.service.exports.upsert(
            {
                "export_id": "optimization-browser-export",
                "project_id": project_id,
                "export_type": "governed_json",
                "file_name": "optimization-study.json",
                "file_path": None,
                "artifact_hash": "sha256-test",
                "metadata_json": {"delivery": "browser_download", "clientOnly": True, "fileExists": False},
            }
        )
        self.assertEqual(exported["file_path"], "not_applicable_client_download")
        self.assertEqual(exported["storage_mode"], "client_generated")
        self.assertFalse(exported["metadata_json"]["fileExists"])

    def test_user_activity_audit_and_demo_feedback_repositories(self) -> None:
        self.service.projects.upsert({**self.project, "created_by": TEST_USER["userId"], "updated_by": TEST_USER["userId"]})
        self.service.evidence.upsert({
            "evidence_id": "attributed-evidence",
            "project_id": "project-1",
            "artifact_type": "optimization_validation",
            "title": "Attributed evidence",
            "status": "captured",
            "created_by": TEST_USER["userId"],
        })
        self.service.runs.upsert({
            "run_id": "attributed-validation",
            "project_id": "project-1",
            "run_type": "optimization_validation",
            "status": "complete",
            "created_by": TEST_USER["userId"],
        })
        self.service.exports.upsert({
            "export_id": "attributed-export",
            "project_id": "project-1",
            "export_type": "optimization_report",
            "file_name": "optimization-report.pdf",
            "created_by": TEST_USER["userId"],
        })
        activity = self.service.users.activity_summary(TEST_USER["userId"])
        self.assertEqual(activity, {"projectCount": 1, "evidenceCount": 1, "validationCount": 1, "exportCount": 1})
        user = self.service.users.get(TEST_USER["userId"])
        self.assertEqual(user["status"], "active")
        self.assertTrue(user["last_active_at"])

        audit = self.service.audit.create({
            "audit_id": "audit-1",
            "project_id": "project-1",
            "user_id": TEST_USER["userId"],
            "action_type": "validation.completed",
            "entity_type": "run",
            "entity_id": "attributed-validation",
            "summary": "Validation completed by the persistence tester.",
            "metadata_json": {"gate": "pass"},
        })
        self.assertEqual(audit["metadata_json"]["gate"], "pass")
        self.assertEqual(self.service.audit.list(project_id="project-1")[0]["action_type"], "validation.completed")

        feedback_payload = {
            "feedback_id": "feedback-1",
            "project_id": "project-1",
            "user_id": TEST_USER["userId"],
            "route": "/workflow/optimization/10",
            "workflow_type": "optimization",
            "step_id": "optimization-10",
            "issue_type": "usability",
            "severity": "medium",
            "expected_behavior": "Validation results remain visible.",
            "actual_behavior": "The reviewer needed a clearer status.",
            "notes": "First pass",
        }
        self.service.feedback.upsert(feedback_payload)
        updated_feedback = self.service.feedback.upsert({**feedback_payload, "notes": "Updated without a duplicate."})
        self.assertEqual(updated_feedback["notes"], "Updated without a duplicate.")
        self.assertEqual(len(self.service.feedback.list(project_id="project-1")), 1)

    def test_dev_user_header_requires_explicit_loopback_and_missing_context_is_generic(self) -> None:
        request_with_header = SimpleNamespace(
            headers={"X-ATLAS-USER-ID": "local-dev-user"},
            cookies={},
            client=SimpleNamespace(host="127.0.0.1"),
        )
        local_user = {
            "userId": "local-dev-user",
            "displayName": "Local Dev User",
            "email": "local-dev@atlas.local",
            "role": "admin",
            "status": "active",
        }
        with (
            patch.object(security_store, "ATLAS_ENABLE_DEV_USER_HEADER", True),
            patch.object(security_store, "ATLAS_LOCAL_DEV", True),
            patch.object(security_store, "ATLAS_HOSTED_MODE", False),
            patch.object(security_store, "ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP", True),
            patch.object(security_store, "user_for_session", return_value=None),
            patch.object(security_store, "get_user", return_value=None),
            patch.object(security_store, "get_user_by_email", return_value=None),
            patch.object(security_store, "create_user", return_value=local_user) as create_user,
            patch.object(security_store, "set_active_user"),
        ):
            resolved = security_store.require_user(request_with_header)
        self.assertEqual(resolved["userId"], "local-dev-user")
        create_user.assert_called_once()

        seeded_admin = {
            "userId": SEEDED_ADMIN_USER_ID,
            "displayName": "ATLAS Local Admin",
            "email": "admin@atlas.local",
            "role": "admin",
            "status": "active",
        }
        seeded_request = SimpleNamespace(
            headers={"X-ATLAS-USER-ID": SEEDED_ADMIN_USER_ID},
            cookies={},
            client=SimpleNamespace(host="::1"),
        )
        with (
            patch.object(security_store, "ATLAS_ENABLE_DEV_USER_HEADER", True),
            patch.object(security_store, "ATLAS_LOCAL_DEV", True),
            patch.object(security_store, "ATLAS_HOSTED_MODE", False),
            patch.object(security_store, "user_for_session", return_value=None),
            patch.object(security_store, "get_user", return_value=seeded_admin),
            patch.object(security_store, "set_active_user"),
        ):
            resolved_admin = security_store.require_user(seeded_request)
        self.assertEqual(resolved_admin["userId"], SEEDED_ADMIN_USER_ID)

        request_without_context = SimpleNamespace(headers={}, cookies={}, client=SimpleNamespace(host="127.0.0.1"))
        with (
            patch.object(security_store, "ATLAS_AUTH_ENABLED", True),
            patch.object(security_store, "user_for_session", return_value=None),
            patch.object(security_store, "audit_event"),
        ):
            with self.assertRaises(security_store.AtlasUserContextError) as context:
                security_store.require_user(request_without_context)
        payload = context.exception.detail
        self.assertEqual(payload, {"error": "authentication required"})
        self.assertNotIn("X-ATLAS-USER-ID", str(payload))

    def test_http_health_and_projects_accept_seeded_admin_header(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        port = _available_port()
        data_root = repository_root / "server" / "data"
        data_root.mkdir(parents=True, exist_ok=True)
        test_prefix = f"atlas_api_context_{os.getpid()}_{port}"
        security_database = data_root / f"{test_prefix}_security.db"
        persistence_database = data_root / f"{test_prefix}_persistence.db"
        test_database_files = [
            Path(f"{database}{suffix}")
            for database in (security_database, persistence_database)
            for suffix in ("", "-wal", "-shm")
        ]
        for database_file in test_database_files:
            database_file.unlink(missing_ok=True)

        environment = os.environ.copy()
        environment.update(
            {
                "ATLAS_AUTH_ENABLED": "true",
                "ATLAS_DEV_MODE": "true",
                "ATLAS_LOCAL_DEV": "true",
                "ATLAS_HOSTED_MODE": "false",
                "ATLAS_ENABLE_DEV_USER_HEADER": "true",
                "ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP": "true",
                "ATLAS_LOCAL_ADMIN_USER_ID": SEEDED_ADMIN_USER_ID,
                "ATLAS_SECURITY_DB_PATH": str(security_database),
                "ATLAS_SQLITE_PATH": str(persistence_database),
            }
        )
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--no-access-log",
        ]
        process = subprocess.Popen(
            command,
            cwd=repository_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = ""
        try:
            health_url = f"http://127.0.0.1:{port}/api/persistence/health"
            deadline = time.monotonic() + 75
            health_status = 0
            health_payload: dict = {}
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    output = process.stdout.read() if process.stdout else ""
                    self.fail(f"Package-aware ATLAS backend exited during startup.\n{output}")
                try:
                    health_status, health_payload = _request_json(
                        health_url,
                        {"X-ATLAS-USER-ID": SEEDED_ADMIN_USER_ID},
                    )
                    break
                except OSError:
                    time.sleep(0.2)
            else:
                self.fail("Package-aware ATLAS backend did not become healthy within 75 seconds.")

            self.assertEqual(health_status, 200)
            self.assertEqual(health_payload, {"ok": True, "status": "running"})

            public_health_status, public_health_payload = _request_json(health_url)
            self.assertEqual(public_health_status, 200)
            self.assertEqual(public_health_payload, {"ok": True, "status": "running"})

            current_user_status, current_user_payload = _request_json(
                f"http://127.0.0.1:{port}/api/auth/me",
                {"X-ATLAS-USER-ID": SEEDED_ADMIN_USER_ID},
            )
            self.assertEqual(current_user_status, 200)
            self.assertEqual(current_user_payload["user"]["userId"], SEEDED_ADMIN_USER_ID)
            self.assertEqual(current_user_payload["user"]["status"], "active")

            project_url = f"http://127.0.0.1:{port}/api/projects"
            project_status, project_payload = _request_json(
                project_url,
                {"X-ATLAS-USER-ID": SEEDED_ADMIN_USER_ID},
            )
            self.assertEqual(project_status, 200)
            self.assertTrue(project_payload["ok"])
            self.assertEqual(project_payload["count"], 0)

            invalid_status, invalid_payload = _request_json(
                project_url,
                {"X-ATLAS-USER-ID": "user-does-not-exist"},
            )
            self.assertEqual(invalid_status, 401)
            self.assertEqual(invalid_payload, {"error": "authentication required"})

            timestamp = "2026-07-15T00:00:00+00:00"
            with sqlite3.connect(security_database) as connection:
                connection.execute(
                    "INSERT INTO users (user_id, email, display_name, role, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("inactive-test-user", "inactive@atlas.local", "Inactive Tester", "viewer", "inactive", timestamp, timestamp),
                )
            inactive_status, inactive_payload = _request_json(
                project_url,
                {"X-ATLAS-USER-ID": "inactive-test-user"},
            )
            self.assertEqual(inactive_status, 403)
            self.assertEqual(inactive_payload["detail"], "User is not active.")

            missing_status, missing_payload = _request_json(project_url)
            self.assertEqual(missing_status, 401)
            self.assertEqual(missing_payload, {"error": "authentication required"})
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                remaining_output, _ = process.communicate(timeout=10)
                output += remaining_output or ""
            except subprocess.TimeoutExpired:
                process.kill()
                remaining_output, _ = process.communicate(timeout=5)
                output += remaining_output or ""
            for database_file in test_database_files:
                for attempt in range(25):
                    try:
                        database_file.unlink(missing_ok=True)
                        break
                    except PermissionError:
                        if attempt < 24:
                            time.sleep(0.2)

    def test_health_and_project_api_reload_from_sqlite(self) -> None:
        with patch.dict(os.environ, {"ATLAS_SQLITE_PATH": str(self.database_path)}):
            health = persistence_health()
            self.assertTrue(health["ok"])
            created = update_project(
                "api-project",
                {
                    "projectName": "API Persistence Project",
                    "projectType": "optimization",
                    "workflowType": "optimization",
                    "templateId": "transportation_logistics",
                    "metadata": {"source": "api-test"},
                },
                TEST_USER,
            )
            self.assertTrue(created["ok"])
            reloaded = get_project("api-project", TEST_USER)
            self.assertEqual(reloaded["project"]["projectName"], "API Persistence Project")
            self.assertEqual(reloaded["project"]["templateId"], "transportation_logistics")
            self.assertEqual(reloaded["project"]["metadata"]["source"], "api-test")

    def test_database_unavailable_is_reported_without_process_crash(self) -> None:
        invalid_database = Database(self.database_path.parent)
        health = invalid_database.health()
        self.assertFalse(health["ok"])
        self.assertEqual(health["status"], "unavailable")
        with self.assertRaises(PersistenceUnavailableError):
            invalid_database.initialize()

    def test_inspection_and_reset_guards(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        inspected = subprocess.run(
            [sys.executable, "scripts/inspect_atlas_db.py", "--db", str(self.database_path), "--limit", "2"],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(inspected.returncode, 0, inspected.stdout + inspected.stderr)
        for label in ("Table counts", "Users", "Latest projects", "Latest audit events", "Latest demo feedback"):
            self.assertIn(label, inspected.stdout)

        disposable = self.database_path.with_name("atlas_reset_guard_test.db")
        disposable.unlink(missing_ok=True)
        refused = subprocess.run(
            [sys.executable, "scripts/reset_atlas_demo_db.py", "--db", str(disposable)],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("pass --yes", refused.stdout)
        self.assertFalse(disposable.exists())


if __name__ == "__main__":
    unittest.main()

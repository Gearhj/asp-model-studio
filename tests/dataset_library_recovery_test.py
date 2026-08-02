"""Isolated tests for exact Dataset Library forensic recovery.

The environment is bound to UUID-specific test roots before any server module
is imported.  No test in this file can resolve the checked-in Dataset Library,
security database, persistence database, or backup directory.

Run:
    .venv/Scripts/python.exe tests/dataset_library_recovery_test.py
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile
from contextlib import closing
from contextlib import redirect_stdout
from dataclasses import replace


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPOSITORY_ROOT))
_RUN_ID = uuid.uuid4().hex
_TEST_ROOT = (
    _REPOSITORY_ROOT / ".tmp" / f"dataset-library-recovery-{_RUN_ID}"
).resolve()
_LIBRARY_ROOT = _TEST_ROOT / "dataset-library"
_SECURITY_DB = _TEST_ROOT / "security" / "atlas_security.db"
_PERSISTENCE_DB = _TEST_ROOT / "persistence" / "atlas_local.db"
_EVIDENCE_ROOT = _TEST_ROOT / "evidence"
_BACKUP_ROOT = (
    Path(tempfile.gettempdir()) / f"atlas-dataset-recovery-backups-{_RUN_ID}"
).resolve()
os.environ.update(
    {
        "ATLAS_TEST_MODE": "1",
        "ATLAS_ENV": "test",
        "ATLAS_DATASET_LIBRARY_ROOT": str(_LIBRARY_ROOT),
        "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": str(_BACKUP_ROOT),
        "ATLAS_SECURITY_DB_PATH": str(_SECURITY_DB),
        "ATLAS_SQLITE_PATH": str(_PERSISTENCE_DB),
    }
)

from server.datasets.dataset_recovery import (  # noqa: E402
    DatasetRecoveryApplyError,
    DatasetRecoveryAuthorizationError,
    DatasetRecoveryConflictError,
    DatasetRecoveryEvidenceError,
    DatasetRecoveryRequest,
    DatasetRecoveryService,
)
from server.datasets.dataset_storage import (  # noqa: E402
    DatasetLibraryPaths,
    DatasetLibraryStorage,
    DatasetRecoveryPendingError,
    DatasetStoreMalformedError,
)
from server.datasets import dataset_registry  # noqa: E402
from server.persistence.db import Database  # noqa: E402
from server.persistence.service import PersistenceService  # noqa: E402


DATASET_ID = "dataset-recovery-exact"
VERSION_ID = "version-recovery-exact"
PROJECT_ID = "project-recovery-exact"
OWNER_ID = "user-recovery-owner"
OUTSIDER_ID = "user-recovery-outsider"
CREATED_AT = "2026-07-27T21:05:06.224214+00:00"
REGISTERED_AT = "2026-07-27T21:05:06.258195+00:00"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


class DatasetLibraryRecoveryTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self._environment = patch.dict(
            os.environ,
            {
                "ATLAS_TEST_MODE": "1",
                "ATLAS_ENV": "test",
                "ATLAS_DATASET_LIBRARY_ROOT": str(_LIBRARY_ROOT),
                "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": str(_BACKUP_ROOT),
                "ATLAS_SECURITY_DB_PATH": str(_SECURITY_DB),
                "ATLAS_SQLITE_PATH": str(_PERSISTENCE_DB),
            },
        )
        self._environment.start()
        self._safe_remove(_TEST_ROOT, _TEST_ROOT.parent)
        self._safe_remove(_BACKUP_ROOT, Path(tempfile.gettempdir()).resolve())
        for path in (
            _LIBRARY_ROOT,
            _SECURITY_DB.parent,
            _PERSISTENCE_DB.parent,
            _EVIDENCE_ROOT,
            _BACKUP_ROOT,
        ):
            path.mkdir(parents=True, exist_ok=True)
        (_LIBRARY_ROOT / "registry.json").write_bytes(_json_bytes({"datasets": []}))
        (_LIBRARY_ROOT / "project_links.json").write_bytes(
            _json_bytes({"links": []})
        )
        (_LIBRARY_ROOT / "users.json").write_bytes(
            _json_bytes(
                {
                    "currentUserId": OWNER_ID,
                    "users": [
                        {
                            "userId": OWNER_ID,
                            "displayName": "Recovery Owner",
                            "role": "data_scientist",
                        }
                    ],
                }
            )
        )
        self._create_security_database()
        self.database = Database(_PERSISTENCE_DB)
        self.database.initialize()
        persistence = PersistenceService(self.database)
        persistence.sync_user(
            {
                "userId": OWNER_ID,
                "displayName": "Recovery Owner",
                "email": "owner@example.test",
                "role": "data_scientist",
            }
        )
        persistence.sync_user(
            {
                "userId": OUTSIDER_ID,
                "displayName": "Recovery Outsider",
                "email": "outsider@example.test",
                "role": "data_scientist",
            }
        )
        persistence.projects.upsert(
            {
                "project_id": PROJECT_ID,
                "project_name": "Recovery Project",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "owner_user_id": OWNER_ID,
                "created_by": OWNER_ID,
                "metadata_json": {},
            }
        )
        self.paths = DatasetLibraryPaths.from_environment(
            backup_root=_BACKUP_ROOT
        )
        self.storage = DatasetLibraryStorage(self.paths)
        self.service = DatasetRecoveryService(
            storage=self.storage,
            security_database=_SECURITY_DB,
            persistence_database=_PERSISTENCE_DB,
        )

    def tearDown(self) -> None:
        self._environment.stop()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._safe_remove(_TEST_ROOT, _TEST_ROOT.parent)
        cls._safe_remove(_BACKUP_ROOT, Path(tempfile.gettempdir()).resolve())

    @staticmethod
    def _safe_remove(path: Path, expected_parent: Path) -> None:
        if path.exists() and path.parent.resolve() == expected_parent.resolve():
            shutil.rmtree(path)

    @staticmethod
    def _create_security_database() -> None:
        with closing(sqlite3.connect(_SECURITY_DB)) as connection:
            connection.executescript(
                """
                CREATE TABLE users (
                  user_id TEXT PRIMARY KEY,
                  display_name TEXT NOT NULL,
                  role TEXT NOT NULL,
                  status TEXT NOT NULL
                );
                """
            )
            connection.executemany(
                "INSERT INTO users VALUES (?, ?, ?, 'active')",
                (
                    (OWNER_ID, "Recovery Owner", "data_scientist"),
                    (OUTSIDER_ID, "Recovery Outsider", "data_scientist"),
                ),
            )
            connection.commit()

    def _artifact_directory(self) -> Path:
        return _LIBRARY_ROOT / DATASET_ID / "versions" / VERSION_ID

    def _build_evidence(
        self,
        *,
        owner_user_id: str | None = OWNER_ID,
        access: list[dict[str, str]] | None = None,
        duplicate_version: bool = False,
        metadata_dataset_id: str = DATASET_ID,
        metadata_version_id: str = VERSION_ID,
        authoritative_schema_hash: str | None = None,
        registry_link_version_id: str = VERSION_ID,
        project_linked_by: str = OWNER_ID,
    ) -> tuple[Path, dict[str, object], dict[str, object]]:
        artifact_directory = self._artifact_directory()
        artifact_directory.mkdir(parents=True, exist_ok=True)
        data_bytes = b"feature,target\n1,0\n2,1\n"
        schema_bytes = _json_bytes(
            {
                "columns": [
                    {"name": "feature", "dtype": "numeric"},
                    {"name": "target", "dtype": "categorical"},
                ]
            }
        )
        metadata = {
            "datasetId": metadata_dataset_id,
            "versionId": metadata_version_id,
            "originalFilename": "recovery.csv",
        }
        lineage = {
            "hash": _sha256_bytes(data_bytes),
            "originalFilename": "recovery.csv",
            "registeredAt": REGISTERED_AT,
            "registeredBy": OWNER_ID,
            "sourceType": "upload",
        }
        profile = {
            "rowCount": 2,
            "columnCount": 2,
            "profiledRows": 2,
            "targetCandidates": ["target"],
            "schema": [
                {"name": "feature", "dtype": "numeric"},
                {"name": "target", "dtype": "categorical"},
            ],
        }
        (artifact_directory / "data_full.csv").write_bytes(data_bytes)
        (artifact_directory / "schema.json").write_bytes(schema_bytes)
        (artifact_directory / "metadata.json").write_bytes(_json_bytes(metadata))
        (artifact_directory / "lineage.json").write_bytes(_json_bytes(lineage))
        (artifact_directory / "profile.json").write_bytes(_json_bytes(profile))
        (artifact_directory / "preview.json").write_bytes(_json_bytes({"rows": []}))
        (artifact_directory / "data_sample.csv").write_bytes(data_bytes)

        project_link = {
            "projectId": PROJECT_ID,
            "datasetId": DATASET_ID,
            "versionId": VERSION_ID,
            "datasetRole": "modeling",
            "linkedAt": "2026-07-27T22:00:00+00:00",
            "linkedBy": project_linked_by,
        }
        version = {
            "versionId": VERSION_ID,
            "createdAt": CREATED_AT,
            "createdBy": OWNER_ID,
            "originalFilename": "recovery.csv",
            "hash": _sha256_bytes(data_bytes),
            "schemaHash": authoritative_schema_hash or _sha256_bytes(schema_bytes),
            "rowCount": 2,
            "columnCount": 2,
            "profilePath": f"{DATASET_ID}/versions/{VERSION_ID}/profile.json",
            "previewPath": f"{DATASET_ID}/versions/{VERSION_ID}/preview.json",
            "fullDataPath": f"{DATASET_ID}/versions/{VERSION_ID}/data_full.csv",
            "samplePath": f"{DATASET_ID}/versions/{VERSION_ID}/data_sample.csv",
        }
        dataset_access = (
            access
            if access is not None
            else [{"userId": OWNER_ID, "role": "owner"}]
        )
        dataset = {
            "datasetId": DATASET_ID,
            "name": "Recovery Dataset",
            "description": "Exact authoritative recovery fixture",
            "domain": "General",
            "sourceType": "upload",
            "ownerUserId": owner_user_id,
            "ownerDisplayName": "Recovery Owner",
            "createdAt": CREATED_AT,
            "updatedAt": CREATED_AT,
            "archived": False,
            "access": dataset_access,
            "linkedProjects": [
                {
                    "projectId": PROJECT_ID,
                    "versionId": registry_link_version_id,
                    "datasetRole": "modeling",
                }
            ],
            "versions": [version, dict(version)] if duplicate_version else [version],
        }
        registry = {"datasets": [dataset]}
        links = {"links": [project_link]}
        archive_path = _EVIDENCE_ROOT / "authoritative-snapshot.zip"
        registry_member = "snapshot/server/artifacts/datasets/registry.json"
        links_member = "snapshot/server/artifacts/datasets/project_links.json"
        schema_member = (
            "snapshot/server/artifacts/datasets/"
            f"{DATASET_ID}/versions/{VERSION_ID}/schema.json"
        )
        registry_bytes = _json_bytes(registry)
        links_bytes = _json_bytes(links)
        with zipfile.ZipFile(
            archive_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr(registry_member, registry_bytes)
            archive.writestr(links_member, links_bytes)
            archive.writestr(schema_member, schema_bytes)
        archive_hash = _sha256_file(archive_path)

        def archive_source(
            member: str,
            payload: bytes,
            kind: str,
        ) -> dict[str, object]:
            return {
                "kind": kind,
                "container_path": str(archive_path),
                "member_path": member,
                "container_sha256": archive_hash,
                "member_sha256": _sha256_bytes(payload),
                "member_bytes": len(payload),
                "logical_snapshot_id": "authoritative-fixture-snapshot",
            }

        metadata_path = artifact_directory / "metadata.json"
        evidence = {
            "schema_version": "atlas.dataset-library-evidence.v1",
            "tier1_sources": [
                archive_source(
                    registry_member,
                    registry_bytes,
                    "authoritative_registry_snapshot",
                ),
                archive_source(
                    links_member,
                    links_bytes,
                    "authoritative_project_links_snapshot",
                ),
                archive_source(
                    schema_member,
                    schema_bytes,
                    "immutable_version_schema_snapshot",
                ),
            ],
            "tier2_sources": [
                {
                    "kind": "artifact_sidecar",
                    "path": str(metadata_path),
                    "sha256": _sha256_file(metadata_path),
                    "bytes": metadata_path.stat().st_size,
                    "family": "live-exact-artifact",
                }
            ],
            "dataset_record": dataset,
            "version_record": version,
            "project_link_record": project_link,
        }
        evidence_path = _EVIDENCE_ROOT / "recovery-evidence.json"
        evidence_path.write_bytes(_json_bytes(evidence))
        return evidence_path, dataset, project_link

    def _request(
        self,
        evidence_path: Path,
        *,
        actor_user_id: str = OWNER_ID,
        project_id: str | None = PROJECT_ID,
    ) -> DatasetRecoveryRequest:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        tier1_sources = evidence.get("tier1_sources") or []
        if tier1_sources:
            tier1_container = Path(tier1_sources[0]["container_path"])
            tier1_container_sha256 = str(tier1_sources[0]["container_sha256"])
        else:
            # Preserve an independently supplied trust anchor even when the
            # adversarial test removes every Tier 1 source from the report.
            tier1_container = _EVIDENCE_ROOT / "authoritative-snapshot.zip"
            tier1_container_sha256 = _sha256_file(tier1_container)
        return DatasetRecoveryRequest(
            dataset_id=DATASET_ID,
            dataset_version_id=VERSION_ID,
            project_id=project_id,
            actor_user_id=actor_user_id,
            evidence_report=evidence_path,
            trusted_tier1_container=tier1_container,
            trusted_tier1_container_sha256=tier1_container_sha256,
            backup_directory=_BACKUP_ROOT,
            reason="Focused exact-version recovery test",
        )

    def _drop_maintenance_migration(self) -> None:
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.execute("DROP TABLE dataset_library_maintenance_events")
            connection.execute(
                "DELETE FROM schema_migrations WHERE version IN (?, ?)",
                (
                    "0022_dataset_library_maintenance.sql",
                    "0023_dataset_library_maintenance_append_only.sql",
                ),
            )
            connection.commit()

    @staticmethod
    def _maintenance_migration_sql() -> str:
        migration_root = (
            _REPOSITORY_ROOT / "server" / "persistence" / "migrations"
        )
        return "\n".join(
            (migration_root / name).read_text(encoding="utf-8")
            for name in (
                "0022_dataset_library_maintenance.sql",
                "0023_dataset_library_maintenance_append_only.sql",
            )
        )

    def _recreate_maintenance_schema(self, migration_sql: str) -> None:
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.execute("DROP TABLE dataset_library_maintenance_events")
            connection.executescript(migration_sql)
            connection.commit()

    def _assert_terminal_trigger_blocks_committed_journal(
        self,
        trigger_body: str,
    ) -> sqlite3.Row | None:
        evidence_path, _, _ = self._build_evidence()
        original_event_writer = self.service._write_maintenance_event
        trigger_installed = False

        def write_with_terminal_trigger(**kwargs: object):
            nonlocal trigger_installed
            if kwargs.get("status") == "complete" and not trigger_installed:
                with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
                    connection.executescript(
                        """
                        CREATE TRIGGER adversarial_terminal_event_trigger
                        AFTER INSERT ON dataset_library_maintenance_events
                        WHEN NEW.event_status = 'complete'
                        BEGIN
                        """
                        + trigger_body
                        + """
                        END;
                        """
                    )
                    connection.commit()
                trigger_installed = True
            return original_event_writer(**kwargs)

        with patch.object(
            self.service,
            "_write_maintenance_event",
            side_effect=write_with_terminal_trigger,
        ):
            with self.assertRaises(DatasetRecoveryApplyError) as caught:
                self.service.apply(self._request(evidence_path))

        self.assertTrue(trigger_installed)
        report = caught.exception.recovery_report
        self.assertTrue(report["mutation"]["applied"])
        self.assertFalse(report["mutation"]["rolled_back"])
        self.assertEqual(report["audit"]["status"], "pending_after_commit")
        self.assertEqual(report["journal"]["status"], "commit_pending")
        journal = self.storage.read_recovery_journal(required=True)
        self.assertEqual(journal["status"], "commit_pending")
        self.assertNotIn("maintenanceEventId", journal)
        terminal_event_id = journal["plannedMaintenanceEventId"]
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                """
                SELECT * FROM dataset_library_maintenance_events
                WHERE maintenance_event_id = ?
                """,
                (terminal_event_id,),
            ).fetchone()

    def _backup_bundles(self) -> list[Path]:
        return sorted(_BACKUP_ROOT.glob("atlas-dataset-library-*"))

    def _cli_command(
        self,
        evidence_path: Path,
        *extra: str,
    ) -> list[str]:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        tier1_source = evidence["tier1_sources"][0]
        return [
            sys.executable,
            str(_REPOSITORY_ROOT / "scripts" / "dataset_library_recovery.py"),
            "--dry-run",
            "--dataset-id",
            DATASET_ID,
            "--dataset-version-id",
            VERSION_ID,
            "--project-id",
            PROJECT_ID,
            "--actor-user-id",
            OWNER_ID,
            "--evidence-report",
            str(evidence_path),
            "--trusted-tier1-container",
            str(tier1_source["container_path"]),
            "--trusted-tier1-container-sha256",
            str(tier1_source["container_sha256"]),
            "--backup-directory",
            str(_BACKUP_ROOT),
            "--reason",
            "CLI dry-run test",
            "--dataset-library-root",
            str(_LIBRARY_ROOT),
            "--security-db",
            str(_SECURITY_DB),
            "--persistence-db",
            str(_PERSISTENCE_DB),
            *extra,
        ]

    def test_dry_run_is_read_only_and_exact(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        registry_before = (_LIBRARY_ROOT / "registry.json").read_bytes()
        links_before = (_LIBRARY_ROOT / "project_links.json").read_bytes()
        database_before = _sha256_file(_PERSISTENCE_DB)

        report = self.service.plan(self._request(evidence_path))

        self.assertEqual(report["mode"], "dry_run")
        self.assertTrue(report["reconciliation"]["recovery_eligible"])
        self.assertTrue(report["plan"]["registry_change"])
        self.assertTrue(report["plan"]["legacy_project_links_change"])
        self.assertTrue(report["plan"]["durable_project_link_change"])
        self.assertFalse(report["plan"]["active_selection_change"])
        self.assertEqual(
            report["before"]["record_counts"],
            {
                "registry_dataset_records": 0,
                "registry_version_records": 0,
                "legacy_project_link_records": 0,
                "durable_project_link_records": 0,
                "active_selection_records": 0,
            },
        )
        self.assertEqual(
            report["after"]["record_counts"],
            {
                "registry_dataset_records": 1,
                "registry_version_records": 1,
                "legacy_project_link_records": 1,
                "durable_project_link_records": 1,
                "active_selection_records": 0,
            },
        )
        self.assertTrue(report["after"]["projected"])
        self.assertEqual(
            (_LIBRARY_ROOT / "registry.json").read_bytes(), registry_before
        )
        self.assertEqual(
            (_LIBRARY_ROOT / "project_links.json").read_bytes(), links_before
        )
        self.assertEqual(_sha256_file(_PERSISTENCE_DB), database_before)
        self.assertEqual(self._backup_bundles(), [])

    def test_cli_dry_run_returns_machine_readable_plan_without_writes(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        registry_before = (_LIBRARY_ROOT / "registry.json").read_bytes()
        links_before = (_LIBRARY_ROOT / "project_links.json").read_bytes()
        database_before = _sha256_file(_PERSISTENCE_DB)
        result = subprocess.run(
            self._cli_command(evidence_path),
            cwd=_REPOSITORY_ROOT,
            env={**os.environ, "ATLAS_TEST_MODE": "1", "ATLAS_ENV": "test"},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["mode"], "dry_run")
        self.assertEqual(report["scope"]["dataset_id"], DATASET_ID)
        self.assertEqual(report["scope"]["dataset_version_id"], VERSION_ID)
        self.assertEqual(
            (_LIBRARY_ROOT / "registry.json").read_bytes(), registry_before
        )
        self.assertEqual(
            (_LIBRARY_ROOT / "project_links.json").read_bytes(), links_before
        )
        self.assertEqual(_sha256_file(_PERSISTENCE_DB), database_before)
        self.assertEqual(self._backup_bundles(), [])

    def test_cli_report_output_rejects_every_authority_overlap(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        archive_path = Path(evidence["tier1_sources"][0]["container_path"])
        independent_trust_anchor = _TEST_ROOT / "independent-tier1-anchor.zip"
        independent_trust_anchor.write_bytes(b"independent trust anchor")
        protected_outputs = (
            _SECURITY_DB,
            Path(f"{_SECURITY_DB}-wal"),
            Path(f"{_SECURITY_DB}-shm"),
            _PERSISTENCE_DB,
            Path(f"{_PERSISTENCE_DB}-wal"),
            Path(f"{_PERSISTENCE_DB}-shm"),
            _LIBRARY_ROOT / "registry.json",
            _LIBRARY_ROOT / "project_links.json",
            evidence_path,
            archive_path,
            independent_trust_anchor,
            _BACKUP_ROOT,
        )
        registry_before = (_LIBRARY_ROOT / "registry.json").read_bytes()
        links_before = (_LIBRARY_ROOT / "project_links.json").read_bytes()
        security_before = _sha256_file(_SECURITY_DB)
        persistence_before = _sha256_file(_PERSISTENCE_DB)

        for protected in protected_outputs:
            with self.subTest(protected=protected.name):
                trust_anchor_override = (
                    (
                        "--trusted-tier1-container",
                        str(independent_trust_anchor),
                    )
                    if protected == independent_trust_anchor
                    else ()
                )
                result = subprocess.run(
                    self._cli_command(
                        evidence_path,
                        *trust_anchor_override,
                        "--report-output",
                        str(protected),
                    ),
                    cwd=_REPOSITORY_ROOT,
                    env={
                        **os.environ,
                        "ATLAS_TEST_MODE": "1",
                        "ATLAS_ENV": "test",
                    },
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
                self.assertEqual(
                    json.loads(result.stdout)["error_type"],
                    "UnsafeReportPath",
                )

        self.assertEqual(
            (_LIBRARY_ROOT / "registry.json").read_bytes(), registry_before
        )
        self.assertEqual(
            (_LIBRARY_ROOT / "project_links.json").read_bytes(), links_before
        )
        self.assertEqual(_sha256_file(_SECURITY_DB), security_before)
        self.assertEqual(_sha256_file(_PERSISTENCE_DB), persistence_before)

    def test_cli_report_output_preflight_fails_before_recovery(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        blocked_parent = _TEST_ROOT / "report-parent-is-a-file"
        blocked_parent.write_text("not a directory", encoding="utf-8")
        registry_before = (_LIBRARY_ROOT / "registry.json").read_bytes()
        links_before = (_LIBRARY_ROOT / "project_links.json").read_bytes()

        result = subprocess.run(
            self._cli_command(
                evidence_path,
                "--report-output",
                str(blocked_parent / "report.json"),
            ),
            cwd=_REPOSITORY_ROOT,
            env={**os.environ, "ATLAS_TEST_MODE": "1", "ATLAS_ENV": "test"},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
        self.assertEqual(json.loads(result.stdout)["error_type"], "UnsafeReportPath")
        self.assertEqual(
            (_LIBRARY_ROOT / "registry.json").read_bytes(), registry_before
        )
        self.assertEqual(
            (_LIBRARY_ROOT / "project_links.json").read_bytes(), links_before
        )

    def test_cli_report_persistence_failure_is_distinct_after_success(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        from scripts import dataset_library_recovery as recovery_cli

        output = io.StringIO()
        report_path = _TEST_ROOT / "reports" / "dry-run.json"
        argv = self._cli_command(
            evidence_path,
            "--report-output",
            str(report_path),
        )[2:]
        with patch.object(recovery_cli, "_persist_report", side_effect=OSError), redirect_stdout(output):
            exit_code = recovery_cli.main(argv)

        self.assertEqual(exit_code, 8)
        result = json.loads(output.getvalue())
        self.assertEqual(result["error_type"], "ReportPersistenceError")
        self.assertTrue(result["operation_succeeded"])
        self.assertEqual(result["service_exit_code"], 0)
        self.assertEqual(result["recovery_report"]["mode"], "dry_run")
        self.assertEqual(
            result["recovery_report"]["scope"]["dataset_version_id"], VERSION_ID
        )
        self.assertFalse(report_path.exists())

    def test_cli_report_persistence_failure_preserves_service_failure(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        from scripts import dataset_library_recovery as recovery_cli

        output = io.StringIO()
        report_path = _TEST_ROOT / "reports" / "failure.json"
        argv = self._cli_command(
            evidence_path,
            "--trusted-tier1-container-sha256",
            "0" * 64,
            "--report-output",
            str(report_path),
        )[2:]
        with patch.object(recovery_cli, "_persist_report", side_effect=OSError), redirect_stdout(output):
            exit_code = recovery_cli.main(argv)

        self.assertEqual(exit_code, 8)
        result = json.loads(output.getvalue())
        self.assertEqual(result["error_type"], "ReportPersistenceError")
        self.assertFalse(result["operation_succeeded"])
        self.assertEqual(result["service_exit_code"], 4)
        self.assertEqual(
            result["service_error_type"], "DatasetRecoveryEvidenceError"
        )
        self.assertEqual(
            result["recovery_report"]["scope"]["dataset_version_id"], VERSION_ID
        )
        self.assertFalse(result["recovery_report"]["mutation"]["attempted"])
        self.assertFalse(report_path.exists())

    def test_valid_recovery_is_durable_idempotent_and_never_activates(self) -> None:
        evidence_path, expected_dataset, expected_link = self._build_evidence()

        report = self.service.apply(self._request(evidence_path))

        self.assertTrue(report["mutation"]["applied"])
        self.assertIsNone(report["active_selection"]["after"])
        self.assertEqual(
            report["after"]["record_counts"],
            {
                "registry_dataset_records": 1,
                "registry_version_records": 1,
                "legacy_project_link_records": 1,
                "durable_project_link_records": 1,
                "active_selection_records": 0,
            },
        )
        self.assertFalse(report["after"]["projected"])
        registry = self.storage.read_registry()
        self.assertEqual(registry["datasets"], [expected_dataset])
        self.assertEqual(self.storage.read_links()["links"], [expected_link])
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.row_factory = sqlite3.Row
            durable_link = connection.execute(
                "SELECT * FROM project_dataset_links WHERE project_id = ? AND dataset_id = ?",
                (PROJECT_ID, DATASET_ID),
            ).fetchone()
            active = connection.execute(
                "SELECT * FROM active_modeling_dataset_versions WHERE project_id = ?",
                (PROJECT_ID,),
            ).fetchone()
            statuses = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT event_status FROM dataset_library_maintenance_events
                    WHERE operation_id = ? ORDER BY event_status
                    """,
                    (report["operation_id"],),
                ).fetchall()
            ]
        self.assertIsNotNone(durable_link)
        self.assertEqual(durable_link["link_status"], "active")
        self.assertIsNone(active)
        self.assertEqual(statuses, ["complete", "started"])
        bundles_before = self._backup_bundles()
        self.assertEqual(len(bundles_before), 1)
        bundle = bundles_before[0]
        self.assertTrue((bundle / "manifest.json").is_file())
        self.assertTrue((bundle / "atlas_persistence_before.sqlite3").is_file())
        self.assertTrue((bundle / "recovery_safety_manifest.json").is_file())
        safety_manifest = json.loads(
            (bundle / "recovery_safety_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            safety_manifest["storage_bundle_manifest_sha256"],
            _sha256_file(bundle / "manifest.json"),
        )
        self.assertEqual(
            report["backup"]["verification"]["status"],
            "verified",
        )
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            audit_backup_hash = connection.execute(
                """
                SELECT backup_manifest_sha256
                FROM dataset_library_maintenance_events
                WHERE operation_id = ? AND event_status = 'complete'
                """,
                (report["operation_id"],),
            ).fetchone()[0]
        self.assertEqual(
            audit_backup_hash,
            _sha256_file(bundle / "recovery_safety_manifest.json"),
        )

        restarted_storage = DatasetLibraryStorage(self.paths)
        restarted_service = DatasetRecoveryService(
            storage=restarted_storage,
            security_database=_SECURITY_DB,
            persistence_database=_PERSISTENCE_DB,
        )
        second = restarted_service.apply(self._request(evidence_path))

        self.assertTrue(second["mutation"]["idempotent"])
        self.assertFalse(second["mutation"]["attempted"])
        self.assertEqual(
            second["before"]["record_counts"],
            second["after"]["record_counts"],
        )
        self.assertIsNone(second["after"]["active_selection"])
        self.assertFalse(second["after"]["projected"])
        self.assertEqual(self._backup_bundles(), bundles_before)
        self.assertNotEqual(
            second["audit"]["maintenance_event_id"],
            report["audit"]["maintenance_event_id"],
        )
        self.assertEqual(
            second["audit"]["prior_maintenance_event_id"],
            report["audit"]["maintenance_event_id"],
        )
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.row_factory = sqlite3.Row
            maintenance_events = connection.execute(
                """
                SELECT maintenance_event_id, attempt_id, event_status,
                       backup_manifest_sha256, metadata_json
                FROM dataset_library_maintenance_events
                WHERE operation_id = ?
                ORDER BY created_at, maintenance_event_id
                """,
                (report["operation_id"],),
            ).fetchall()
        self.assertEqual(len(maintenance_events), 3)
        self.assertEqual(len({row["attempt_id"] for row in maintenance_events}), 2)
        idempotent_event = next(
            row
            for row in maintenance_events
            if row["maintenance_event_id"]
            == second["audit"]["maintenance_event_id"]
        )
        idempotent_metadata = json.loads(idempotent_event["metadata_json"])
        self.assertEqual(idempotent_event["event_status"], "complete")
        self.assertIsNone(idempotent_event["backup_manifest_sha256"])
        self.assertTrue(idempotent_metadata["idempotent"])
        self.assertFalse(idempotent_metadata["stateMutationPerformed"])
        self.assertFalse(idempotent_metadata["backupCreated"])
        self.assertFalse(idempotent_metadata["concurrentCompletionObserved"])
        self.assertEqual(
            idempotent_metadata["priorMaintenanceEventId"],
            report["audit"]["maintenance_event_id"],
        )
        recovered_version_ids = [
            version["versionId"]
            for version in restarted_storage.read_registry()["datasets"][0]["versions"]
        ]
        self.assertEqual(recovered_version_ids, [VERSION_ID])
        self.assertIsNone(restarted_service._active_selection(PROJECT_ID))
        self.assertEqual(
            restarted_service._durable_project_link(PROJECT_ID, DATASET_ID)[
                "link_status"
            ],
            "active",
        )
        restarted_registry = importlib.reload(dataset_registry)
        with patch.object(
            restarted_registry,
            "current_user",
            return_value={
                "userId": OWNER_ID,
                "displayName": "Recovery Owner",
                "role": "data_scientist",
            },
        ), patch.object(restarted_registry, "audit_event", return_value=None):
            data_acquisition_versions = restarted_registry.list_versions(DATASET_ID)
        self.assertEqual(
            [version["versionId"] for version in data_acquisition_versions],
            [VERSION_ID],
        )

    def test_backup_snapshots_must_match_exact_pre_recovery_authority_hashes(
        self,
    ) -> None:
        evidence_path, _, _ = self._build_evidence()
        original_create_backup = self.storage.create_backup_bundle
        wrong_snapshots = {
            "registry.json": {
                "datasets": [{"datasetId": "wrong-backup-dataset", "versions": []}]
            },
            "project_links.json": {
                "links": [
                    {
                        "projectId": PROJECT_ID,
                        "datasetId": "wrong-backup-dataset",
                        "versionId": "wrong-backup-version",
                    }
                ]
            },
        }

        for authority_name, wrong_payload in wrong_snapshots.items():
            with self.subTest(authority_name=authority_name):

                def create_self_consistent_wrong_backup(**kwargs: object):
                    backup = original_create_backup(**kwargs)
                    bundle = Path(str(backup["bundlePath"]))
                    snapshot = bundle / "snapshots" / authority_name
                    snapshot.write_bytes(_json_bytes(wrong_payload))
                    manifest_path = bundle / "manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    record = next(
                        item
                        for item in manifest["files"]
                        if item["sourceRelativePath"] == authority_name
                    )
                    record["sha256"] = _sha256_file(snapshot)
                    record["sizeBytes"] = snapshot.stat().st_size
                    manifest_path.write_bytes(_json_bytes(manifest))
                    backup["manifestSha256"] = _sha256_file(manifest_path)
                    return backup

                with patch.object(
                    self.storage,
                    "create_backup_bundle",
                    side_effect=create_self_consistent_wrong_backup,
                ):
                    with self.assertRaisesRegex(
                        DatasetRecoveryApplyError,
                        "exact pre-recovery authority state",
                    ):
                        self.service.apply(self._request(evidence_path))

                self.assertEqual(self.storage.read_registry(), {"datasets": []})
                self.assertEqual(self.storage.read_links(), {"links": []})
                self.assertIsNone(self.service._durable_project_link(PROJECT_ID, DATASET_ID))
                self.assertEqual(self._backup_bundles(), [])

    def test_tier1_trust_anchor_path_and_hash_must_match_exactly(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        request = self._request(evidence_path)
        alternate_archive = _EVIDENCE_ROOT / "same-bytes-different-archive.zip"
        shutil.copyfile(request.trusted_tier1_container, alternate_archive)
        registry_before = (_LIBRARY_ROOT / "registry.json").read_bytes()
        links_before = (_LIBRARY_ROOT / "project_links.json").read_bytes()

        mismatches = (
            replace(request, trusted_tier1_container=alternate_archive),
            replace(request, trusted_tier1_container_sha256="0" * 64),
        )
        for mismatched_request in mismatches:
            with self.subTest(
                trusted_container=mismatched_request.trusted_tier1_container.name,
                trusted_hash=mismatched_request.trusted_tier1_container_sha256,
            ):
                with self.assertRaisesRegex(
                    DatasetRecoveryEvidenceError,
                    "explicit trusted archive and checksum",
                ):
                    self.service.plan(mismatched_request)

        self.assertEqual(
            (_LIBRARY_ROOT / "registry.json").read_bytes(), registry_before
        )
        self.assertEqual(
            (_LIBRARY_ROOT / "project_links.json").read_bytes(), links_before
        )
        self.assertEqual(self._backup_bundles(), [])

    def test_successful_apply_commits_journal_and_unblocks_normal_reads(self) -> None:
        evidence_path, expected_dataset, expected_link = self._build_evidence()

        report = self.service.apply(self._request(evidence_path))

        journal = self.storage.read_recovery_journal(required=True)
        self.assertEqual(report["journal"]["status"], "committed")
        self.assertEqual(journal["status"], "committed")
        self.assertEqual(journal["operationId"], report["operation_id"])
        self.assertEqual(journal["attemptId"], report["journal"]["attempt_id"])
        self.assertEqual(
            journal["backupManifestSha256"],
            report["backup"]["safetyManifestSha256"],
        )
        self.assertEqual(
            journal["maintenanceEventId"], report["audit"]["maintenance_event_id"]
        )
        self.assertEqual(self.storage.read_registry()["datasets"], [expected_dataset])
        self.assertEqual(self.storage.read_links()["links"], [expected_link])

    def test_committed_recovery_proof_allows_later_catalog_transactions(self) -> None:
        evidence_path, expected_dataset, _ = self._build_evidence()
        self.service.apply(self._request(evidence_path))
        registry = self.storage.read_registry()
        registry["datasets"].append(
            {
                "datasetId": "later-legitimate-dataset",
                "name": "Later legitimate dataset",
                "ownerUserId": OWNER_ID,
                "versions": [],
            }
        )
        self.storage.atomic_write_json(
            self.storage.paths.registry_path,
            registry,
            expected_sha256=self.storage.sha256_file(
                self.storage.paths.registry_path
            ),
            shape_validator=lambda value: isinstance(value, dict)
            and isinstance(value.get("datasets"), list),
        )
        recovered = self.storage.read_registry()
        self.assertEqual(recovered["datasets"][0], expected_dataset)
        self.assertEqual(
            recovered["datasets"][1]["datasetId"],
            "later-legitimate-dataset",
        )

    def test_prepared_journal_blocks_normal_reads_and_recovery_plan(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        request = self._request(evidence_path)
        prepared = {
            "kind": "atlas_dataset_library_recovery_journal",
            "formatVersion": 1,
            "status": "prepared",
            "operationId": "dataset-recovery-interrupted-test",
            "attemptId": "dataset-recovery-attempt-interrupted-test",
            "createdAt": CREATED_AT,
            "actorUserId": OWNER_ID,
            "reason": "Simulated interrupted recovery",
            "projectId": PROJECT_ID,
            "datasetId": DATASET_ID,
            "datasetVersionId": VERSION_ID,
            "backupManifestSha256": "1" * 64,
            "before": {
                "registrySha256": "2" * 64,
                "projectLinksSha256": "3" * 64,
                "activeSelectionSha256": "4" * 64,
            },
        }
        self.storage.write_recovery_journal(prepared)

        with self.assertRaises(DatasetRecoveryPendingError):
            self.storage.read_registry()
        with self.assertRaises(DatasetRecoveryPendingError):
            self.storage.read_links()
        with self.assertRaises(DatasetRecoveryPendingError):
            self.service.plan(request)

        self.assertEqual(
            self.storage.read_registry(allow_pending_recovery=True),
            {"datasets": []},
        )
        self.assertEqual(
            self.storage.read_recovery_journal(required=True)["status"],
            "prepared",
        )
        self.assertEqual(self._backup_bundles(), [])

    def test_malformed_terminal_journals_fail_closed_instead_of_unblocking_reads(
        self,
    ) -> None:
        prepared = {
            "kind": "atlas_dataset_library_recovery_journal",
            "formatVersion": 1,
            "status": "prepared",
            "operationId": "dataset-recovery-terminal-schema-test",
            "attemptId": "dataset-recovery-attempt-terminal-schema-test",
            "createdAt": CREATED_AT,
            "actorUserId": OWNER_ID,
            "reason": "Validate terminal journal proof",
            "projectId": PROJECT_ID,
            "datasetId": DATASET_ID,
            "datasetVersionId": VERSION_ID,
            "backupManifestSha256": "1" * 64,
            "before": {
                "registrySha256": "2" * 64,
                "projectLinksSha256": "3" * 64,
                "activeSelectionSha256": "4" * 64,
            },
        }
        malformed_terminals = {
            "committed_without_after_proof": {
                **prepared,
                "status": "committed",
                "committedAt": CREATED_AT,
                "maintenanceEventId": "dataset-maintenance-terminal-schema-test",
            },
            "aborted_without_failure_proof": {
                **prepared,
                "status": "aborted",
                "abortedAt": CREATED_AT,
                "failedMaintenanceEventId": None,
            },
        }

        for label, journal in malformed_terminals.items():
            with self.subTest(label=label):
                self.storage.paths.recovery_journal_path.write_bytes(
                    _json_bytes(journal)
                )
                with self.assertRaises(DatasetStoreMalformedError):
                    self.storage.read_recovery_journal(required=True)
                with self.assertRaises(DatasetStoreMalformedError):
                    self.storage.read_registry()

    def test_forged_committed_journal_without_durable_event_stays_blocking(
        self,
    ) -> None:
        registry_hash = _sha256_file(_LIBRARY_ROOT / "registry.json")
        links_hash = _sha256_file(_LIBRARY_ROOT / "project_links.json")
        forged = {
            "kind": "atlas_dataset_library_recovery_journal",
            "formatVersion": 1,
            "status": "committed",
            "operationId": "dataset-recovery-forged-terminal-test",
            "attemptId": "dataset-recovery-attempt-forged-terminal-test",
            "createdAt": CREATED_AT,
            "committedAt": CREATED_AT,
            "actorUserId": OWNER_ID,
            "reason": "Forged terminal journal must remain blocked",
            "projectId": PROJECT_ID,
            "datasetId": DATASET_ID,
            "datasetVersionId": VERSION_ID,
            "backupManifestSha256": "1" * 64,
            "maintenanceEventId": "dataset-maintenance-does-not-exist",
            "before": {
                "registrySha256": registry_hash,
                "projectLinksSha256": links_hash,
                "activeSelectionSha256": "2" * 64,
            },
            "after": {
                "registrySha256": registry_hash,
                "projectLinksSha256": links_hash,
                "activeSelectionSha256": "2" * 64,
            },
        }
        self.storage.write_recovery_journal(forged)
        with self.assertRaises(DatasetRecoveryPendingError):
            self.storage.read_registry()
        with self.assertRaises(DatasetRecoveryPendingError):
            self.storage.read_links()

    def test_exact_creation_audit_corroborates_but_never_replaces_tier2(self) -> None:
        evidence_path, expected_dataset, _ = self._build_evidence()
        exact_metadata = {
            "name": expected_dataset["name"],
            "versionId": VERSION_ID,
            "outcome": "success",
        }
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.execute(
                """
                INSERT INTO audit_log (
                  audit_id, project_id, user_id, action_type,
                  entity_type, entity_id, created_at, metadata_json
                ) VALUES (?, ?, ?, 'dataset.created', 'dataset', ?, ?, ?)
                """,
                (
                    "audit-dataset-created-exact",
                    PROJECT_ID,
                    OWNER_ID,
                    DATASET_ID,
                    CREATED_AT,
                    json.dumps(exact_metadata, sort_keys=True),
                ),
            )
            connection.commit()

        report = self.service.plan(self._request(evidence_path))

        corroboration = report["reconciliation"][
            "creation_audit_corroboration"
        ]
        self.assertEqual(corroboration["status"], "verified")
        self.assertEqual(corroboration["audit_id"], "audit-dataset-created-exact")
        self.assertTrue(report["reconciliation"]["recovery_eligible"])
        self.assertTrue(
            any(
                source["tier"] == 2
                for source in report["evidence"]["sources"]
            )
        )

        conflicting_metadata = {**exact_metadata, "versionId": "wrong-version"}
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.execute(
                "UPDATE audit_log SET metadata_json = ? WHERE audit_id = ?",
                (
                    json.dumps(conflicting_metadata, sort_keys=True),
                    "audit-dataset-created-exact",
                ),
            )
            connection.commit()
        with self.assertRaisesRegex(
            DatasetRecoveryEvidenceError,
            "audit rows conflict",
        ):
            self.service.plan(self._request(evidence_path))

    def test_incompatible_maintenance_schema_fails_closed_without_repair(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.executescript(
                """
                DROP TABLE dataset_library_maintenance_events;
                CREATE TABLE dataset_library_maintenance_events (
                  maintenance_event_id TEXT PRIMARY KEY,
                  operation_id TEXT NOT NULL,
                  event_status TEXT NOT NULL
                );
                """
            )
            connection.commit()
        registry_before = (_LIBRARY_ROOT / "registry.json").read_bytes()
        links_before = (_LIBRARY_ROOT / "project_links.json").read_bytes()

        with self.assertRaisesRegex(
            DatasetRecoveryApplyError,
            "incompatible with migration 0022",
        ):
            self.service.apply(self._request(evidence_path))

        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(dataset_library_maintenance_events)"
                ).fetchall()
            }
        self.assertEqual(
            columns,
            {"maintenance_event_id", "operation_id", "event_status"},
        )
        self.assertEqual(
            (_LIBRARY_ROOT / "registry.json").read_bytes(), registry_before
        )
        self.assertEqual(
            (_LIBRARY_ROOT / "project_links.json").read_bytes(), links_before
        )
        self.assertFalse(self.storage.paths.recovery_journal_path.exists())
        self.assertEqual(self._backup_bundles(), [])

    def test_permissive_lookalike_maintenance_schema_is_rejected(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.executescript(
                """
                DROP TABLE dataset_library_maintenance_events;
                CREATE TABLE dataset_library_maintenance_events (
                  maintenance_event_id TEXT PRIMARY KEY,
                  attempt_id TEXT NOT NULL,
                  operation_id TEXT NOT NULL,
                  operation_type TEXT NOT NULL,
                  event_status TEXT NOT NULL,
                  actor_user_id TEXT NOT NULL,
                  project_id TEXT,
                  dataset_id TEXT NOT NULL,
                  dataset_version_id TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  evidence_report_sha256 TEXT NOT NULL,
                  backup_manifest_sha256 TEXT,
                  registry_before_sha256 TEXT,
                  registry_after_sha256 TEXT,
                  created_at TEXT NOT NULL,
                  metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX idx_dataset_library_maintenance_operation_event
                  ON dataset_library_maintenance_events(operation_id, event_status, created_at DESC);
                CREATE INDEX idx_dataset_library_maintenance_attempt
                  ON dataset_library_maintenance_events(attempt_id, created_at ASC);
                CREATE INDEX idx_dataset_library_maintenance_identity
                  ON dataset_library_maintenance_events(dataset_id, dataset_version_id, created_at DESC);
                CREATE INDEX idx_dataset_library_maintenance_project
                  ON dataset_library_maintenance_events(project_id, created_at DESC);
                """
            )
            connection.commit()

        with self.assertRaisesRegex(
            DatasetRecoveryApplyError,
            "executable table contract is incompatible",
        ):
            self.service.apply(self._request(evidence_path))

        self.assertEqual(self.storage.read_registry(), {"datasets": []})
        self.assertEqual(self.storage.read_links(), {"links": []})
        self.assertEqual(self._backup_bundles(), [])

    def test_sql_comments_cannot_masquerade_as_maintenance_checks(self) -> None:
        migration_sql = self._maintenance_migration_sql()
        operation_check = (
            "\n    CHECK (operation_type IN "
            "('reconcile', 'recover', 'verify', 'quarantine'))"
        )
        status_check = (
            "\n    CHECK (event_status IN "
            "('started', 'complete', 'failed', 'refused'))"
        )
        comments = (
            "  metadata_json TEXT NOT NULL DEFAULT '{}'\n"
            "  /* CHECK (operation_type IN "
            "('reconcile', 'recover', 'verify', 'quarantine')) */\n"
            "  -- CHECK (event_status IN "
            "('started', 'complete', 'failed', 'refused'))\n"
            ");"
        )
        permissive_sql = (
            migration_sql.replace(operation_check, "", 1)
            .replace(status_check, "", 1)
            .replace(
                "  metadata_json TEXT NOT NULL DEFAULT '{}'\n);",
                comments,
                1,
            )
        )
        self.assertNotEqual(permissive_sql, migration_sql)
        self._recreate_maintenance_schema(permissive_sql)

        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.execute(
                """
                INSERT INTO dataset_library_maintenance_events (
                  maintenance_event_id, attempt_id, operation_id,
                  operation_type, event_status, actor_user_id,
                  dataset_id, dataset_version_id, reason,
                  evidence_report_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "comment-bypass-event",
                    "comment-bypass-attempt",
                    "comment-bypass-operation",
                    "not-an-operation-type",
                    "not-an-event-status",
                    OWNER_ID,
                    DATASET_ID,
                    VERSION_ID,
                    "prove the lookalike table is permissive",
                    "a" * 64,
                    CREATED_AT,
                ),
            )
            connection.rollback()

        with self.assertRaisesRegex(
            DatasetRecoveryApplyError,
            "executable table contract is incompatible",
        ):
            self.service._maintenance_schema_available()

    def test_double_quoted_strings_cannot_masquerade_as_checks(self) -> None:
        migration_sql = self._maintenance_migration_sql()
        operation_check = (
            "\n    CHECK (operation_type IN "
            "('reconcile', 'recover', 'verify', 'quarantine'))"
        )
        status_check = (
            "\n    CHECK (event_status IN "
            "('started', 'complete', 'failed', 'refused'))"
        )
        permissive_sql = migration_sql.replace(
            operation_check,
            (
                "\n    CHECK (1 OR \"check (operation_type in "
                "('reconcile', 'recover', 'verify', 'quarantine'))\")"
            ),
            1,
        ).replace(
            status_check,
            (
                "\n    CHECK (1 OR \"check (event_status in "
                "('started', 'complete', 'failed', 'refused'))\")"
            ),
            1,
        )
        self.assertNotEqual(permissive_sql, migration_sql)
        self._recreate_maintenance_schema(permissive_sql)

        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.execute(
                """
                INSERT INTO dataset_library_maintenance_events (
                  maintenance_event_id, attempt_id, operation_id,
                  operation_type, event_status, actor_user_id,
                  dataset_id, dataset_version_id, reason,
                  evidence_report_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "dqs-bypass-event",
                    "dqs-bypass-attempt",
                    "dqs-bypass-operation",
                    "not-an-operation-type",
                    "not-an-event-status",
                    OWNER_ID,
                    DATASET_ID,
                    VERSION_ID,
                    "prove the double-quoted lookalike table is permissive",
                    "b" * 64,
                    CREATED_AT,
                ),
            )
            connection.rollback()

        with self.assertRaisesRegex(
            DatasetRecoveryApplyError,
            "executable table contract is incompatible",
        ):
            self.service._maintenance_schema_available()

    def test_generated_maintenance_columns_hidden_from_table_info_are_rejected(
        self,
    ) -> None:
        canonical_sql = self._maintenance_migration_sql()
        marker = "  metadata_json TEXT NOT NULL DEFAULT '{}'\n);"
        self.assertIn(marker, canonical_sql)
        for generated_kind, expected_hidden in (("VIRTUAL", 2), ("STORED", 3)):
            with self.subTest(generated_kind=generated_kind):
                migration_sql = canonical_sql.replace(
                    marker,
                    (
                        "  metadata_json TEXT NOT NULL DEFAULT '{}',\n"
                        "  concealed_extra TEXT GENERATED ALWAYS AS "
                        f"(operation_id) {generated_kind}\n"
                        ");"
                    ),
                    1,
                )
                self._recreate_maintenance_schema(migration_sql)
                with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
                    ordinary_names = {
                        row[1]
                        for row in connection.execute(
                            "PRAGMA table_info(dataset_library_maintenance_events)"
                        ).fetchall()
                    }
                    extended = {
                        row[1]: row[6]
                        for row in connection.execute(
                            "PRAGMA table_xinfo(dataset_library_maintenance_events)"
                        ).fetchall()
                    }
                self.assertNotIn("concealed_extra", ordinary_names)
                self.assertEqual(extended["concealed_extra"], expected_hidden)
                with self.assertRaisesRegex(
                    DatasetRecoveryApplyError,
                    "table is incompatible with migration 0022",
                ):
                    self.service._maintenance_schema_available()

    def test_partial_collated_and_unexpected_maintenance_indexes_are_rejected(
        self,
    ) -> None:
        variants = (
            (
                "partial",
                """
                DROP INDEX idx_dataset_library_maintenance_project;
                CREATE INDEX idx_dataset_library_maintenance_project
                  ON dataset_library_maintenance_events(project_id, created_at DESC)
                  WHERE project_id IS NOT NULL;
                """,
                "partial-index metadata",
            ),
            (
                "collation",
                """
                DROP INDEX idx_dataset_library_maintenance_attempt;
                CREATE INDEX idx_dataset_library_maintenance_attempt
                  ON dataset_library_maintenance_events(
                    attempt_id COLLATE NOCASE,
                    created_at ASC
                  );
                """,
                "collation",
            ),
            (
                "unexpected",
                """
                CREATE INDEX idx_dataset_library_maintenance_unexpected
                  ON dataset_library_maintenance_events(reason);
                """,
                "unexpected or missing index",
            ),
        )
        for name, mutation_sql, expected_error in variants:
            with self.subTest(index_variant=name):
                self._recreate_maintenance_schema(
                    self._maintenance_migration_sql()
                )
                with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
                    connection.executescript(mutation_sql)
                    connection.commit()
                with self.assertRaisesRegex(
                    DatasetRecoveryApplyError,
                    expected_error,
                ):
                    self.service._maintenance_schema_available()

    def test_maintenance_schema_rejects_attached_and_referencing_triggers(
        self,
    ) -> None:
        variants = (
            (
                "after-insert-delete",
                """
                CREATE TRIGGER adversarial_maintenance_delete
                AFTER INSERT ON dataset_library_maintenance_events
                BEGIN
                  DELETE FROM dataset_library_maintenance_events
                  WHERE maintenance_event_id = NEW.maintenance_event_id;
                END;
                """,
            ),
            (
                "after-insert-update",
                """
                CREATE TRIGGER adversarial_maintenance_update
                AFTER INSERT ON dataset_library_maintenance_events
                BEGIN
                  UPDATE dataset_library_maintenance_events
                  SET reason = 'mutated'
                  WHERE maintenance_event_id = NEW.maintenance_event_id;
                END;
                """,
            ),
            (
                "other-table-trigger-body",
                """
                CREATE TABLE adversarial_trigger_driver (id INTEGER);
                CREATE TRIGGER adversarial_cross_table_delete
                AFTER INSERT ON adversarial_trigger_driver
                BEGIN
                  DELETE FROM dataset_library_maintenance_events;
                END;
                """,
            ),
            (
                "uppercase-quoted-cross-table-reference",
                """
                CREATE TABLE adversarial_uppercase_driver (id INTEGER);
                CREATE TRIGGER adversarial_uppercase_cross_table_delete
                AFTER INSERT ON adversarial_uppercase_driver
                BEGIN
                  DELETE FROM "DATASET_LIBRARY_MAINTENANCE_EVENTS";
                END;
                """,
            ),
        )
        for name, trigger_sql in variants:
            with self.subTest(trigger_variant=name):
                self._recreate_maintenance_schema(
                    self._maintenance_migration_sql()
                )
                with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
                    connection.execute(
                        "DROP TRIGGER IF EXISTS adversarial_cross_table_delete"
                    )
                    connection.execute(
                        "DROP TABLE IF EXISTS adversarial_trigger_driver"
                    )
                    connection.execute(
                        "DROP TRIGGER IF EXISTS adversarial_uppercase_cross_table_delete"
                    )
                    connection.execute(
                        "DROP TABLE IF EXISTS adversarial_uppercase_driver"
                    )
                    connection.executescript(trigger_sql)
                    connection.commit()
                with self.assertRaisesRegex(
                    DatasetRecoveryApplyError,
                    "trigger inventory is incompatible",
                ):
                    self.service._maintenance_schema_available()

    def test_maintenance_schema_preserves_case_sensitive_check_literals(
        self,
    ) -> None:
        migration_sql = self._maintenance_migration_sql()
        altered_sql = migration_sql.replace(
            "'started', 'complete', 'failed', 'refused'",
            "'STARTED', 'COMPLETE', 'FAILED', 'REFUSED'",
            1,
        )
        self.assertNotEqual(altered_sql, migration_sql)
        self._recreate_maintenance_schema(altered_sql)
        with self.assertRaisesRegex(
            DatasetRecoveryApplyError,
            "executable table contract is incompatible",
        ):
            self.service._maintenance_schema_available()

    def test_maintenance_events_are_database_enforced_append_only(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        report = self.service.apply(self._request(evidence_path))
        event_id = report["audit"]["maintenance_event_id"]
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE dataset_library_maintenance_events SET reason = ? "
                    "WHERE maintenance_event_id = ?",
                    ("tampered", event_id),
                )
            connection.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM dataset_library_maintenance_events "
                    "WHERE maintenance_event_id = ?",
                    (event_id,),
                )
            connection.rollback()
            row = connection.execute(
                "SELECT event_status FROM dataset_library_maintenance_events "
                "WHERE maintenance_event_id = ?",
                (event_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "complete")

    def test_deleted_terminal_event_fails_exact_readback_before_commit(
        self,
    ) -> None:
        terminal_row = self._assert_terminal_trigger_blocks_committed_journal(
            """
              DELETE FROM dataset_library_maintenance_events
              WHERE maintenance_event_id = NEW.maintenance_event_id;
            """
        )
        self.assertIsNone(terminal_row)

    def test_mutated_terminal_event_fails_exact_readback_before_commit(
        self,
    ) -> None:
        terminal_row = self._assert_terminal_trigger_blocks_committed_journal(
            """
              UPDATE dataset_library_maintenance_events
              SET reason = 'tampered-after-insert', metadata_json = '{}'
              WHERE maintenance_event_id = NEW.maintenance_event_id;
            """
        )
        # The append-only BEFORE UPDATE trigger aborts the adversarial
        # AFTER INSERT mutation, so SQLite rolls the entire terminal insert
        # back and the commit-pending journal remains the sole durable marker.
        self.assertIsNone(terminal_row)

    def test_maintenance_index_column_order_is_verified(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.executescript(
                """
                DROP INDEX idx_dataset_library_maintenance_attempt;
                CREATE INDEX idx_dataset_library_maintenance_attempt
                  ON dataset_library_maintenance_events(created_at ASC, attempt_id ASC);
                """
            )
            connection.commit()

        with self.assertRaisesRegex(
            DatasetRecoveryApplyError,
            "incompatible columns or order, or collation",
        ):
            self.service.apply(self._request(evidence_path))

        self.assertEqual(self.storage.read_registry(), {"datasets": []})
        self.assertEqual(self.storage.read_links(), {"links": []})
        self.assertEqual(self._backup_bundles(), [])

    def test_pre_0022_database_is_backed_up_before_migration(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        self._drop_maintenance_migration()
        original_ensure = self.service._ensure_maintenance_schema
        observed = {"backup_preceded_migration": False}

        def ensure_after_backup() -> bool:
            bundles = self._backup_bundles()
            self.assertEqual(len(bundles), 1)
            self.assertTrue(
                (bundles[0] / "atlas_persistence_before.sqlite3").is_file()
            )
            with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
                table = connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table'
                      AND name = 'dataset_library_maintenance_events'
                    """
                ).fetchone()
            self.assertIsNone(table)
            observed["backup_preceded_migration"] = True
            return original_ensure()

        with patch.object(
            self.service,
            "_ensure_maintenance_schema",
            side_effect=ensure_after_backup,
        ):
            report = self.service.apply(self._request(evidence_path))

        self.assertTrue(observed["backup_preceded_migration"])
        self.assertTrue(report["mutation"]["applied"])
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            migration = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                ("0022_dataset_library_maintenance.sql",),
            ).fetchone()
            complete = connection.execute(
                """
                SELECT 1 FROM dataset_library_maintenance_events
                WHERE operation_id = ? AND event_status = 'complete'
                """,
                (report["operation_id"],),
            ).fetchone()
        self.assertIsNotNone(migration)
        self.assertIsNotNone(complete)

    def test_existing_0022_database_is_backed_up_before_0023_upgrade(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.execute(
                "DROP TRIGGER trg_dataset_library_maintenance_events_no_update"
            )
            connection.execute(
                "DROP TRIGGER trg_dataset_library_maintenance_events_no_delete"
            )
            connection.execute(
                "DELETE FROM schema_migrations WHERE version = ?",
                ("0023_dataset_library_maintenance_append_only.sql",),
            )
            connection.commit()

        original_ensure = self.service._ensure_maintenance_schema
        observed = {"backup_preceded_upgrade": False}

        def ensure_after_backup() -> bool:
            bundles = self._backup_bundles()
            self.assertEqual(len(bundles), 1)
            backup_database = bundles[0] / "atlas_persistence_before.sqlite3"
            self.assertTrue(backup_database.is_file())
            with closing(sqlite3.connect(backup_database)) as connection:
                migrations = {
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations WHERE version LIKE '002%dataset_library_maintenance%'"
                    ).fetchall()
                }
                triggers = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'dataset_library_maintenance_events'"
                ).fetchall()
            self.assertIn("0022_dataset_library_maintenance.sql", migrations)
            self.assertNotIn(
                "0023_dataset_library_maintenance_append_only.sql",
                migrations,
            )
            self.assertEqual(triggers, [])
            observed["backup_preceded_upgrade"] = True
            return original_ensure()

        with patch.object(
            self.service,
            "_ensure_maintenance_schema",
            side_effect=ensure_after_backup,
        ):
            report = self.service.apply(self._request(evidence_path))

        self.assertTrue(observed["backup_preceded_upgrade"])
        self.assertTrue(report["mutation"]["applied"])
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            migration = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                ("0023_dataset_library_maintenance_append_only.sql",),
            ).fetchone()
            triggers = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'dataset_library_maintenance_events'"
                ).fetchall()
            }
        self.assertIsNotNone(migration)
        self.assertEqual(
            triggers,
            {
                "trg_dataset_library_maintenance_events_no_update",
                "trg_dataset_library_maintenance_events_no_delete",
            },
        )

    def test_existing_complete_event_cannot_bypass_0023_upgrade(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        first = self.service.apply(self._request(evidence_path))
        first_event_id = first["audit"]["maintenance_event_id"]
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.execute(
                "DROP TRIGGER trg_dataset_library_maintenance_events_no_update"
            )
            connection.execute(
                "DROP TRIGGER trg_dataset_library_maintenance_events_no_delete"
            )
            connection.execute(
                "DELETE FROM schema_migrations WHERE version = ?",
                ("0023_dataset_library_maintenance_append_only.sql",),
            )
            connection.commit()

        second = self.service.apply(self._request(evidence_path))
        self.assertNotEqual(second["audit"]["maintenance_event_id"], first_event_id)
        self.assertFalse(second["mutation"]["idempotent"])
        self.assertTrue(second["mutation"]["applied"])
        self.assertEqual(len(self._backup_bundles()), 2)
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            migration = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                ("0023_dataset_library_maintenance_append_only.sql",),
            ).fetchone()
            triggers = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'dataset_library_maintenance_events'"
            ).fetchone()[0]
        self.assertIsNotNone(migration)
        self.assertEqual(triggers, 2)

    def test_failed_apply_rolls_back_files_and_inserted_durable_link(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        registry_before = (_LIBRARY_ROOT / "registry.json").read_bytes()
        links_before = (_LIBRARY_ROOT / "project_links.json").read_bytes()
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            activation_events_before = connection.execute(
                "SELECT * FROM project_dataset_activation_events ORDER BY activation_event_id"
            ).fetchall()

        with patch.object(
            self.service,
            "_active_selection",
            side_effect=[
                None,
                None,
                RuntimeError("injected post-link verification failure"),
            ],
        ):
            with self.assertRaises(DatasetRecoveryApplyError) as caught:
                self.service.apply(self._request(evidence_path))

        self.assertEqual(
            (_LIBRARY_ROOT / "registry.json").read_bytes(), registry_before
        )
        self.assertEqual(
            (_LIBRARY_ROOT / "project_links.json").read_bytes(), links_before
        )
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            link = connection.execute(
                "SELECT 1 FROM project_dataset_links WHERE project_id = ? AND dataset_id = ?",
                (PROJECT_ID, DATASET_ID),
            ).fetchone()
            failed = connection.execute(
                """
                SELECT metadata_json FROM dataset_library_maintenance_events
                WHERE event_status = 'failed'
                """
            ).fetchone()
            activation_events_after = connection.execute(
                """
                SELECT activation_event_id, event_type, metadata_json
                FROM project_dataset_activation_events
                ORDER BY created_at, activation_event_id
                """
            ).fetchall()
        self.assertIsNone(link)
        self.assertIsNotNone(failed)
        self.assertTrue(json.loads(failed[0])["rollbackComplete"])
        self.assertEqual(len(activation_events_after), len(activation_events_before) + 2)
        event_types = {row[1] for row in activation_events_after}
        self.assertIn("project_dataset_linked", event_types)
        self.assertIn("project_dataset_link_recovery_compensated", event_types)
        linked_event = next(
            row for row in activation_events_after if row[1] == "project_dataset_linked"
        )
        compensated_event = next(
            row
            for row in activation_events_after
            if row[1] == "project_dataset_link_recovery_compensated"
        )
        linked_metadata = json.loads(linked_event[2])
        compensated_metadata = json.loads(compensated_event[2])
        self.assertEqual(
            compensated_metadata["compensatedEventId"], linked_event[0]
        )
        self.assertEqual(
            compensated_metadata["recoveryOperationId"],
            linked_metadata["recoveryOperationId"],
        )
        journal = self.storage.read_recovery_journal(required=True)
        self.assertEqual(journal["status"], "aborted")
        self.assertEqual(
            caught.exception.recovery_report["journal"]["status"], "aborted"
        )
        self.assertEqual(self.storage.read_registry(), {"datasets": []})
        self.assertEqual(self.storage.read_links(), {"links": []})
        self.assertEqual(len(self._backup_bundles()), 1)

    def test_post_replace_failure_restores_the_original_valid_json(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        registry_before = (_LIBRARY_ROOT / "registry.json").read_bytes()
        links_before = (_LIBRARY_ROOT / "project_links.json").read_bytes()
        original_atomic_write = self.storage.atomic_write_json

        def fail_after_registry_replace(path: Path, payload: object, **kwargs: object):
            result = original_atomic_write(path, payload, **kwargs)
            if Path(path).name == "registry.json":
                raise RuntimeError("injected post-replace verification failure")
            return result

        with patch.object(
            self.storage,
            "atomic_write_json",
            side_effect=fail_after_registry_replace,
        ):
            with self.assertRaises(DatasetRecoveryApplyError):
                self.service.apply(self._request(evidence_path))

        self.assertEqual(
            (_LIBRARY_ROOT / "registry.json").read_bytes(), registry_before
        )
        self.assertEqual(
            (_LIBRARY_ROOT / "project_links.json").read_bytes(), links_before
        )
        self.assertEqual(self.storage.read_registry(), {"datasets": []})
        self.assertEqual(self.storage.read_links(), {"links": []})

    def test_commit_decision_write_failure_rolls_back_without_complete_event(
        self,
    ) -> None:
        evidence_path, _, _ = self._build_evidence()
        original_write_journal = self.storage.write_recovery_journal

        def fail_commit_decision(payload: object, **kwargs: object):
            if isinstance(payload, dict) and payload.get("status") == "commit_pending":
                raise OSError("injected commit-decision replacement failure")
            return original_write_journal(payload, **kwargs)

        with patch.object(
            self.storage,
            "write_recovery_journal",
            side_effect=fail_commit_decision,
        ):
            with self.assertRaises(DatasetRecoveryApplyError) as caught:
                self.service.apply(self._request(evidence_path))

        report = caught.exception.recovery_report
        self.assertFalse(report["mutation"]["applied"])
        self.assertTrue(report["mutation"]["rolled_back"])
        self.assertEqual(report["journal"]["status"], "aborted")
        self.assertEqual(self.storage.read_registry(), {"datasets": []})
        self.assertEqual(self.storage.read_links(), {"links": []})
        self.assertIsNone(self.service._durable_project_link(PROJECT_ID, DATASET_ID))
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            statuses = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT event_status FROM dataset_library_maintenance_events
                    WHERE operation_id = ? ORDER BY event_status
                    """,
                    (report["operation_id"],),
                ).fetchall()
            ]
        self.assertEqual(statuses, ["failed", "started"])

    def test_post_replace_commit_decision_error_is_reconciled_without_rollback(
        self,
    ) -> None:
        evidence_path, expected_dataset, expected_link = self._build_evidence()
        original_atomic_write = self.storage.atomic_write_json

        def fail_after_commit_decision_replace(
            path: Path, payload: object, **kwargs: object
        ):
            result = original_atomic_write(path, payload, **kwargs)
            if (
                Path(path) == self.storage.paths.recovery_journal_path
                and isinstance(payload, dict)
                and payload.get("status") == "commit_pending"
            ):
                raise OSError("injected post-replace commit-decision verification failure")
            return result

        with patch.object(
            self.storage,
            "atomic_write_json",
            side_effect=fail_after_commit_decision_replace,
        ):
            report = self.service.apply(self._request(evidence_path))

        self.assertTrue(report["mutation"]["applied"])
        self.assertEqual(report["journal"]["status"], "committed")
        self.assertEqual(self.storage.read_registry()["datasets"], [expected_dataset])
        self.assertEqual(self.storage.read_links()["links"], [expected_link])

    def test_post_replace_committed_journal_error_is_reconciled_without_rollback(
        self,
    ) -> None:
        evidence_path, expected_dataset, expected_link = self._build_evidence()
        original_atomic_write = self.storage.atomic_write_json

        def fail_after_committed_replace(
            path: Path, payload: object, **kwargs: object
        ):
            result = original_atomic_write(path, payload, **kwargs)
            if (
                Path(path) == self.storage.paths.recovery_journal_path
                and isinstance(payload, dict)
                and payload.get("status") == "committed"
            ):
                raise OSError("injected post-replace committed verification failure")
            return result

        with patch.object(
            self.storage,
            "atomic_write_json",
            side_effect=fail_after_committed_replace,
        ):
            report = self.service.apply(self._request(evidence_path))

        self.assertTrue(report["mutation"]["applied"])
        self.assertEqual(report["journal"]["status"], "committed")
        self.assertEqual(self.storage.read_registry()["datasets"], [expected_dataset])
        self.assertEqual(self.storage.read_links()["links"], [expected_link])

    def test_complete_event_failure_leaves_blocking_commit_pending_journal(
        self,
    ) -> None:
        evidence_path, expected_dataset, expected_link = self._build_evidence()
        original_event_writer = self.service._write_maintenance_event_reconciled

        def fail_complete_event(**kwargs: object):
            if kwargs.get("status") == "complete":
                raise OSError("injected complete-event persistence failure")
            return original_event_writer(**kwargs)

        with patch.object(
            self.service,
            "_write_maintenance_event_reconciled",
            side_effect=fail_complete_event,
        ):
            with self.assertRaises(DatasetRecoveryApplyError) as caught:
                self.service.apply(self._request(evidence_path))

        report = caught.exception.recovery_report
        self.assertTrue(report["mutation"]["applied"])
        self.assertFalse(report["mutation"]["rolled_back"])
        self.assertEqual(report["journal"]["status"], "commit_pending")
        self.assertEqual(report["audit"]["status"], "pending_after_commit")
        with self.assertRaises(DatasetRecoveryPendingError):
            self.storage.read_registry()
        self.assertEqual(
            self.storage.read_registry(allow_pending_recovery=True)["datasets"],
            [expected_dataset],
        )
        self.assertEqual(
            self.storage.read_links(allow_pending_recovery=True)["links"],
            [expected_link],
        )
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            statuses = [
                row[0]
                for row in connection.execute(
                    "SELECT event_status FROM dataset_library_maintenance_events"
                ).fetchall()
            ]
        self.assertEqual(statuses, ["started"])

        resumed = self.service.apply(self._request(evidence_path))
        self.assertTrue(resumed["resume"]["commitPendingFinalized"])
        self.assertFalse(resumed["resume"]["eventPreviouslyDurable"])
        self.assertEqual(resumed["journal"]["status"], "committed")
        self.assertEqual(
            self.storage.read_registry()["datasets"],
            [expected_dataset],
        )
        self.assertEqual(self.storage.read_links()["links"], [expected_link])
        committed_journal = self.storage.read_recovery_journal(required=True)
        self.assertTrue(committed_journal["durableLinkChanged"])
        durable_link = self.service._durable_project_link(PROJECT_ID, DATASET_ID)
        self.assertEqual(
            committed_journal["after"]["durableProjectLinkSha256"],
            self.service._state_sha256(durable_link),
        )
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            complete_metadata = json.loads(
                connection.execute(
                    """
                    SELECT metadata_json FROM dataset_library_maintenance_events
                    WHERE maintenance_event_id = ?
                    """,
                    (resumed["audit"]["maintenance_event_id"],),
                ).fetchone()[0]
            )
        self.assertTrue(complete_metadata["durableLinkChanged"])
        self.assertTrue(complete_metadata["durableLinkPresent"])

    def test_commit_pending_resume_rejects_swapped_durable_link(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        original_event_writer = self.service._write_maintenance_event_reconciled

        def fail_complete_event(**kwargs: object):
            if kwargs.get("status") == "complete":
                raise OSError("injected complete-event persistence failure")
            return original_event_writer(**kwargs)

        with patch.object(
            self.service,
            "_write_maintenance_event_reconciled",
            side_effect=fail_complete_event,
        ):
            with self.assertRaises(DatasetRecoveryApplyError):
                self.service.apply(self._request(evidence_path))

        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.execute(
                """
                UPDATE project_dataset_links
                SET linked_by = ?, updated_at = ?, metadata_json = ?
                WHERE project_id = ? AND dataset_id = ?
                """,
                (
                    OWNER_ID,
                    "2026-07-31T23:59:59+00:00",
                    json.dumps({"source": "unrelated-reauthorization"}),
                    PROJECT_ID,
                    DATASET_ID,
                ),
            )
            connection.commit()

        with self.assertRaises(DatasetRecoveryConflictError):
            self.service.apply(self._request(evidence_path))
        journal = self.storage.read_recovery_journal(required=True)
        self.assertEqual(journal["status"], "commit_pending")
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            complete_events = connection.execute(
                """
                SELECT COUNT(*) FROM dataset_library_maintenance_events
                WHERE operation_id = ? AND event_status = 'complete'
                """,
                (journal["operationId"],),
            ).fetchone()[0]
        self.assertEqual(complete_events, 0)

    def test_commit_pending_resume_rejects_tampered_safety_backup(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        original_event_writer = self.service._write_maintenance_event_reconciled

        def fail_complete_event(**kwargs: object):
            if kwargs.get("status") == "complete":
                raise OSError("injected complete-event persistence failure")
            return original_event_writer(**kwargs)

        with patch.object(
            self.service,
            "_write_maintenance_event_reconciled",
            side_effect=fail_complete_event,
        ):
            with self.assertRaises(DatasetRecoveryApplyError):
                self.service.apply(self._request(evidence_path))

        journal = self.storage.read_recovery_journal(required=True)
        bundle = Path(journal["backupProof"]["bundlePath"])
        registry_snapshot = bundle / "snapshots" / "registry.json"
        registry_snapshot.write_bytes(b'{"datasets":[{"tampered":true}]}\n')

        with self.assertRaises(DatasetRecoveryApplyError):
            self.service.apply(self._request(evidence_path))
        self.assertEqual(
            self.storage.read_recovery_journal(required=True)["status"],
            "commit_pending",
        )

    def test_commit_pending_with_durable_event_resumes_exact_journal(self) -> None:
        evidence_path, expected_dataset, _ = self._build_evidence()
        original_write_journal = self.service._write_recovery_journal_reconciled

        def fail_committed_journal(payload: object, **kwargs: object):
            if isinstance(payload, dict) and payload.get("status") == "committed":
                raise OSError("injected committed-journal persistence failure")
            return original_write_journal(payload, **kwargs)

        with patch.object(
            self.service,
            "_write_recovery_journal_reconciled",
            side_effect=fail_committed_journal,
        ):
            with self.assertRaises(DatasetRecoveryApplyError) as caught:
                self.service.apply(self._request(evidence_path))
        self.assertEqual(caught.exception.recovery_report["journal"]["status"], "commit_pending")
        with self.assertRaises(DatasetRecoveryPendingError):
            self.storage.read_registry()

        resumed = self.service.apply(self._request(evidence_path))
        self.assertTrue(resumed["resume"]["commitPendingFinalized"])
        self.assertTrue(resumed["resume"]["eventPreviouslyDurable"])
        self.assertEqual(self.storage.read_registry()["datasets"], [expected_dataset])

    def test_failed_event_failure_leaves_rolled_back_state_blocked(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        original_event_writer = self.service._write_maintenance_event_reconciled

        def fail_failed_event(**kwargs: object):
            if kwargs.get("status") == "failed":
                raise OSError("injected failed-event persistence failure")
            return original_event_writer(**kwargs)

        with patch.object(
            self.service,
            "_active_selection",
            side_effect=[None, None, RuntimeError("injected precommit failure")],
        ), patch.object(
            self.service,
            "_write_maintenance_event_reconciled",
            side_effect=fail_failed_event,
        ):
            with self.assertRaises(DatasetRecoveryApplyError) as caught:
                self.service.apply(self._request(evidence_path))

        report = caught.exception.recovery_report
        self.assertFalse(report["mutation"]["applied"])
        self.assertTrue(report["mutation"]["rolled_back"])
        self.assertEqual(report["journal"]["status"], "prepared")
        with self.assertRaises(DatasetRecoveryPendingError):
            self.storage.read_registry()
        self.assertEqual(
            self.storage.read_registry(allow_pending_recovery=True),
            {"datasets": []},
        )
        self.assertEqual(
            self.storage.read_links(allow_pending_recovery=True),
            {"links": []},
        )
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            statuses = [
                row[0]
                for row in connection.execute(
                    "SELECT event_status FROM dataset_library_maintenance_events"
                ).fetchall()
            ]
        self.assertEqual(statuses, ["started"])

    def test_post_commit_complete_event_error_is_reconciled(self) -> None:
        evidence_path, expected_dataset, _ = self._build_evidence()
        original_event_writer = self.service._write_maintenance_event

        def fail_after_complete_event(**kwargs: object):
            event_id = original_event_writer(**kwargs)
            if kwargs.get("status") == "complete":
                raise OSError("injected post-commit complete-event error")
            return event_id

        with patch.object(
            self.service,
            "_write_maintenance_event",
            side_effect=fail_after_complete_event,
        ):
            report = self.service.apply(self._request(evidence_path))

        self.assertTrue(report["mutation"]["applied"])
        self.assertEqual(report["journal"]["status"], "committed")
        self.assertEqual(self.storage.read_registry()["datasets"], [expected_dataset])

    def test_post_commit_failed_event_error_is_reconciled_before_abort(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        original_event_writer = self.service._write_maintenance_event

        def fail_after_failed_event(**kwargs: object):
            event_id = original_event_writer(**kwargs)
            if kwargs.get("status") == "failed":
                raise OSError("injected post-commit failed-event error")
            return event_id

        with patch.object(
            self.service,
            "_active_selection",
            side_effect=[None, None, RuntimeError("injected precommit failure")],
        ), patch.object(
            self.service,
            "_write_maintenance_event",
            side_effect=fail_after_failed_event,
        ):
            with self.assertRaises(DatasetRecoveryApplyError) as caught:
                self.service.apply(self._request(evidence_path))

        report = caught.exception.recovery_report
        self.assertFalse(report["mutation"]["applied"])
        self.assertTrue(report["mutation"]["rolled_back"])
        self.assertEqual(report["journal"]["status"], "aborted")
        self.assertEqual(self.storage.read_registry(), {"datasets": []})
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            statuses = sorted(
                row[0]
                for row in connection.execute(
                    "SELECT event_status FROM dataset_library_maintenance_events"
                ).fetchall()
            )
        self.assertEqual(statuses, ["failed", "started"])

    def test_post_replace_aborted_journal_error_is_reconciled(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        original_atomic_write = self.storage.atomic_write_json

        def fail_after_aborted_replace(
            path: Path, payload: object, **kwargs: object
        ):
            result = original_atomic_write(path, payload, **kwargs)
            if (
                Path(path) == self.storage.paths.recovery_journal_path
                and isinstance(payload, dict)
                and payload.get("status") == "aborted"
            ):
                raise OSError("injected post-replace aborted verification failure")
            return result

        with patch.object(
            self.service,
            "_active_selection",
            side_effect=[None, None, RuntimeError("injected precommit failure")],
        ), patch.object(
            self.storage,
            "atomic_write_json",
            side_effect=fail_after_aborted_replace,
        ):
            with self.assertRaises(DatasetRecoveryApplyError) as caught:
                self.service.apply(self._request(evidence_path))

        report = caught.exception.recovery_report
        self.assertFalse(report["mutation"]["applied"])
        self.assertTrue(report["mutation"]["rolled_back"])
        self.assertEqual(report["journal"]["status"], "aborted")
        self.assertEqual(self.storage.read_registry(), {"datasets": []})

    def test_postcommit_result_failure_never_rolls_back_committed_recovery(
        self,
    ) -> None:
        evidence_path, expected_dataset, expected_link = self._build_evidence()

        with patch.object(
            self.service,
            "_build_applied_report",
            side_effect=RuntimeError("injected postcommit result failure"),
        ):
            with self.assertRaises(DatasetRecoveryApplyError) as caught:
                self.service.apply(self._request(evidence_path))

        report = caught.exception.recovery_report
        self.assertTrue(report["mutation"]["applied"])
        self.assertFalse(report["mutation"]["rolled_back"])
        self.assertEqual(report["journal"]["status"], "committed")
        self.assertEqual(report["audit"]["status"], "complete")
        self.assertEqual(report["errors"][0]["phase"], "post_commit")
        self.assertEqual(self.storage.read_registry()["datasets"], [expected_dataset])
        self.assertEqual(self.storage.read_links()["links"], [expected_link])
        durable_link = self.service._durable_project_link(PROJECT_ID, DATASET_ID)
        self.assertIsNotNone(durable_link)
        self.assertEqual(durable_link["link_status"], "active")
        journal = self.storage.read_recovery_journal(required=True)
        self.assertEqual(journal["status"], "committed")
        self.assertEqual(
            journal["maintenanceEventId"], report["audit"]["maintenance_event_id"]
        )
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            statuses = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT event_status FROM dataset_library_maintenance_events
                    WHERE operation_id = ? ORDER BY event_status
                    """,
                    (report["operation_id"],),
                ).fetchall()
            ]
        self.assertEqual(statuses, ["complete", "started"])

    def test_json_rollbacks_continue_when_durable_compensation_fails(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        registry_before = (_LIBRARY_ROOT / "registry.json").read_bytes()
        links_before = (_LIBRARY_ROOT / "project_links.json").read_bytes()

        with patch.object(
            self.service,
            "_active_selection",
            side_effect=[None, None, RuntimeError("injected post-link failure")],
        ), patch.object(
            self.service,
            "_remove_recovery_durable_link",
            side_effect=RuntimeError("injected durable compensation failure"),
        ):
            with self.assertRaises(DatasetRecoveryApplyError):
                self.service.apply(self._request(evidence_path))

        self.assertEqual(
            (_LIBRARY_ROOT / "registry.json").read_bytes(), registry_before
        )
        self.assertEqual(
            (_LIBRARY_ROOT / "project_links.json").read_bytes(), links_before
        )
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            failed_metadata = json.loads(
                connection.execute(
                    """
                    SELECT metadata_json FROM dataset_library_maintenance_events
                    WHERE event_status = 'failed'
                    """
                ).fetchone()[0]
            )
        self.assertFalse(failed_metadata["rollbackComplete"])
        self.assertEqual(
            self.storage.read_recovery_journal(required=True)["status"],
            "prepared",
        )

    def test_postcommit_durable_link_error_is_exactly_compensated(self) -> None:
        """A repository error after COMMIT must not strand its durable link."""

        from server.persistence.repositories.project_dataset_activation_repository import (
            ProjectDatasetActivationRepository,
        )

        evidence_path, _, _ = self._build_evidence()
        original_authorize_link = ProjectDatasetActivationRepository.authorize_link

        def commit_then_raise(repository, **kwargs):
            original_authorize_link(repository, **kwargs)
            raise OSError("injected repository failure after durable commit")

        with patch.object(
            ProjectDatasetActivationRepository,
            "authorize_link",
            new=commit_then_raise,
        ):
            with self.assertRaises(DatasetRecoveryApplyError) as caught:
                self.service.apply(self._request(evidence_path))

        report = caught.exception.recovery_report
        self.assertFalse(report["mutation"]["applied"])
        self.assertTrue(report["mutation"]["rolled_back"])
        self.assertTrue(report["mutation"]["rollback_complete"])
        self.assertEqual(report["journal"]["status"], "aborted")
        self.assertEqual(self.storage.read_registry(), {"datasets": []})
        self.assertEqual(self.storage.read_links(), {"links": []})
        self.assertIsNone(
            self.service._durable_project_link(PROJECT_ID, DATASET_ID)
        )
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            surviving_links = connection.execute(
                """
                SELECT COUNT(*) FROM project_dataset_links
                WHERE project_id = ? AND dataset_id = ?
                """,
                (PROJECT_ID, DATASET_ID),
            ).fetchone()[0]
            compensation_events = connection.execute(
                """
                SELECT COUNT(*) FROM project_dataset_activation_events
                WHERE project_id = ? AND dataset_id = ?
                  AND event_type = 'project_dataset_link_recovery_compensated'
                  AND event_status = 'complete'
                """,
                (PROJECT_ID, DATASET_ID),
            ).fetchone()[0]
        self.assertEqual(surviving_links, 0)
        self.assertEqual(compensation_events, 1)

    def test_completed_event_does_not_hide_newly_missing_records(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        first = self.service.apply(self._request(evidence_path))
        (_LIBRARY_ROOT / "registry.json").write_bytes(_json_bytes({"datasets": []}))
        (_LIBRARY_ROOT / "project_links.json").write_bytes(_json_bytes({"links": []}))
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.execute(
                "DELETE FROM project_dataset_activation_events WHERE project_id = ?",
                (PROJECT_ID,),
            )
            connection.execute(
                "DELETE FROM project_dataset_links WHERE project_id = ?",
                (PROJECT_ID,),
            )
            connection.commit()

        second = self.service.apply(self._request(evidence_path))

        self.assertEqual(second["operation_id"], first["operation_id"])
        self.assertTrue(second["mutation"]["applied"])
        self.assertFalse(second["mutation"]["idempotent"])
        self.assertEqual(len(self.storage.read_registry()["datasets"]), 1)
        self.assertEqual(len(self.storage.read_links()["links"]), 1)
        self.assertEqual(len(self._backup_bundles()), 2)
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            maintenance_events = connection.execute(
                """
                SELECT maintenance_event_id, attempt_id, event_status
                FROM dataset_library_maintenance_events
                WHERE operation_id = ?
                ORDER BY created_at, maintenance_event_id
                """,
                (first["operation_id"],),
            ).fetchall()
        self.assertEqual(len(maintenance_events), 4)
        self.assertEqual(len({row[0] for row in maintenance_events}), 4)
        attempts = {row[1] for row in maintenance_events}
        self.assertEqual(len(attempts), 2)
        for attempt_id in attempts:
            self.assertEqual(
                {
                    row[2]
                    for row in maintenance_events
                    if row[1] == attempt_id
                },
                {"started", "complete"},
            )

    def test_artifact_directory_alone_is_not_authoritative(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["tier1_sources"] = []
        evidence_path.write_bytes(_json_bytes(evidence))

        with self.assertRaisesRegex(
            DatasetRecoveryEvidenceError,
            "Tier 1 authoritative registry",
        ):
            self.service.plan(self._request(evidence_path))

    def test_missing_or_nonindependent_tier2_is_rejected(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["tier2_sources"] = []
        evidence_path.write_bytes(_json_bytes(evidence))
        with self.assertRaisesRegex(
            DatasetRecoveryEvidenceError,
            "supplied, verified Tier 2",
        ):
            self.service.plan(self._request(evidence_path))

        evidence_path, _, _ = self._build_evidence()
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["tier2_sources"][0]["family"] = (
            "authoritative-fixture-snapshot"
        )
        evidence_path.write_bytes(_json_bytes(evidence))
        report = self.service.plan(self._request(evidence_path))
        self.assertTrue(report["reconciliation"]["recovery_eligible"])
        self.assertTrue(
            all(
                source["family"] != "authoritative-fixture-snapshot"
                for source in report["evidence"]["sources"]
            )
        )

    def test_arbitrary_tier2_bytes_and_unrecognized_tier1_kind_are_rejected(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        arbitrary = _EVIDENCE_ROOT / "arbitrary.txt"
        arbitrary.write_bytes(b"not an exact artifact or sidecar")
        evidence["tier2_sources"] = [
            {
                "kind": "artifact_sidecar",
                "path": str(arbitrary),
                "sha256": _sha256_file(arbitrary),
                "bytes": arbitrary.stat().st_size,
                "family": "independent-but-unbound",
            }
        ]
        evidence_path.write_bytes(_json_bytes(evidence))
        with self.assertRaisesRegex(
            DatasetRecoveryEvidenceError,
            "supplied, verified Tier 2",
        ):
            self.service.plan(self._request(evidence_path))

        evidence_path, _, _ = self._build_evidence()
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["tier1_sources"][0]["kind"] = "self_asserted_registry"
        evidence_path.write_bytes(_json_bytes(evidence))
        with self.assertRaisesRegex(
            DatasetRecoveryEvidenceError,
            "recognized authoritative source kind",
        ):
            self.service.plan(self._request(evidence_path))

    def test_missing_owner_evidence_is_rejected(self) -> None:
        evidence_path, _, _ = self._build_evidence(owner_user_id=None)

        with self.assertRaisesRegex(DatasetRecoveryEvidenceError, "owner evidence"):
            self.service.plan(self._request(evidence_path))

    def test_missing_acl_evidence_is_rejected(self) -> None:
        evidence_path, _, _ = self._build_evidence(access=[])

        with self.assertRaisesRegex(DatasetRecoveryEvidenceError, "ACL evidence"):
            self.service.plan(self._request(evidence_path))

    def test_ambiguous_exact_version_is_rejected(self) -> None:
        evidence_path, _, _ = self._build_evidence(duplicate_version=True)

        with self.assertRaisesRegex(DatasetRecoveryEvidenceError, "missing or ambiguous"):
            self.service.plan(self._request(evidence_path))

    def test_content_checksum_mismatch_is_rejected(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        (self._artifact_directory() / "data_full.csv").write_bytes(b"tampered")

        with self.assertRaisesRegex(DatasetRecoveryEvidenceError, "artifact checksum"):
            self.service.plan(self._request(evidence_path))

    def test_schema_checksum_mismatch_is_rejected(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        (self._artifact_directory() / "schema.json").write_bytes(b"{}\n")

        with self.assertRaisesRegex(DatasetRecoveryEvidenceError, "schema"):
            self.service.plan(self._request(evidence_path))

    def test_authoritative_schema_sources_must_agree(self) -> None:
        evidence_path, _, _ = self._build_evidence(
            authoritative_schema_hash="f" * 64
        )

        with self.assertRaisesRegex(
            DatasetRecoveryEvidenceError,
            "Authoritative schema checksums disagree",
        ):
            self.service.plan(self._request(evidence_path))

    def test_conflicting_artifact_dataset_id_is_rejected(self) -> None:
        evidence_path, _, _ = self._build_evidence(
            metadata_dataset_id="different-dataset"
        )

        with self.assertRaisesRegex(DatasetRecoveryEvidenceError, "requested identity"):
            self.service.plan(self._request(evidence_path))

    def test_conflicting_artifact_version_id_is_rejected(self) -> None:
        evidence_path, _, _ = self._build_evidence(
            metadata_version_id="different-version"
        )

        with self.assertRaisesRegex(DatasetRecoveryEvidenceError, "requested identity"):
            self.service.plan(self._request(evidence_path))

    def test_live_version_bound_to_another_dataset_is_rejected(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        (_LIBRARY_ROOT / "registry.json").write_bytes(
            _json_bytes(
                {
                    "datasets": [
                        {
                            "datasetId": "different-dataset",
                            "versions": [{"versionId": VERSION_ID}],
                        }
                    ]
                }
            )
        )

        with self.assertRaisesRegex(
            DatasetRecoveryConflictError,
            "already bound to another dataset",
        ):
            self.service.plan(self._request(evidence_path))

    def test_cross_user_and_anonymous_recovery_are_rejected(self) -> None:
        evidence_path, _, _ = self._build_evidence()

        with self.assertRaises(DatasetRecoveryAuthorizationError):
            self.service.plan(
                self._request(evidence_path, actor_user_id=OUTSIDER_ID)
            )
        with self.assertRaises(DatasetRecoveryEvidenceError):
            self.service.plan(self._request(evidence_path, actor_user_id=""))

    def test_current_revocation_is_not_overridden_by_historical_link(self) -> None:
        evidence_path, _, _ = self._build_evidence()
        with closing(sqlite3.connect(_PERSISTENCE_DB)) as connection:
            connection.execute(
                """
                INSERT INTO project_dataset_links (
                  project_id, dataset_id, link_status, linked_by, linked_at,
                  updated_at, metadata_json
                ) VALUES (?, ?, 'revoked', ?, ?, ?, '{}')
                """,
                (
                    PROJECT_ID,
                    DATASET_ID,
                    OWNER_ID,
                    REGISTERED_AT,
                    REGISTERED_AT,
                ),
            )
            connection.commit()

        with self.assertRaisesRegex(
            DatasetRecoveryConflictError,
            "revocation conflicts",
        ):
            self.service.plan(self._request(evidence_path))


if __name__ == "__main__":
    unittest.main(verbosity=2)

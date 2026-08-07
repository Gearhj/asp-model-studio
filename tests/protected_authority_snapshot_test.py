from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from scripts import protected_authority_snapshot as authority_snapshot
from scripts.protected_authority_snapshot import capture_snapshot, compare_snapshots
from tests.hermetic_test_roots import temporary_test_root


CATALOG_VERSION_ID = "catalog-version-synthetic-1"
CATALOG_CHECKSUM = "a" * 64
SOURCE_CHECKSUM = "b" * 64


@pytest.fixture
def tmp_path() -> Path:
    """Keep synthetic snapshot fixtures inside launcher-owned authority."""

    with temporary_test_root(
        "protected-authority-snapshot-",
        scope="protected-authority-snapshot-fixtures",
    ) as root:
        yield root


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _catalog_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE catalog_registry_metadata (
              schema_version TEXT PRIMARY KEY,
              created_at TEXT NOT NULL
            );
            CREATE TABLE bureau_catalog_versions (
              catalog_version_id TEXT PRIMARY KEY,
              catalog_id TEXT NOT NULL,
              provider_id TEXT NOT NULL,
              product_id TEXT NOT NULL,
              edition TEXT NOT NULL,
              country_or_region TEXT NOT NULL,
              source_release_version TEXT NOT NULL,
              source_checksum TEXT NOT NULL,
              normalized_catalog_checksum TEXT NOT NULL,
              record_count INTEGER NOT NULL,
              special_value_definition_count INTEGER NOT NULL,
              parser_build_version TEXT NOT NULL,
              schema_version TEXT NOT NULL,
              source_provenance_reference TEXT NOT NULL,
              restricted_storage_reference TEXT NOT NULL,
              installation_status TEXT NOT NULL,
              integrity_status TEXT NOT NULL,
              entitlement_classification TEXT NOT NULL,
              created_by TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              supersession_status TEXT NOT NULL,
              retired_status TEXT NOT NULL,
              registry_revision INTEGER NOT NULL
            );
            CREATE TABLE bureau_catalog_entitlements (
              entitlement_id TEXT PRIMARY KEY,
              principal_id TEXT NOT NULL,
              tenant_id TEXT,
              catalog_version_id TEXT NOT NULL,
              catalog_checksum TEXT NOT NULL,
              operations_json TEXT NOT NULL,
              status TEXT NOT NULL,
              expires_at TEXT,
              granted_by TEXT NOT NULL,
              granted_at TEXT NOT NULL,
              revoked_by TEXT,
              revoked_at TEXT,
              FOREIGN KEY(catalog_version_id)
                REFERENCES bureau_catalog_versions(catalog_version_id)
            );
            CREATE TABLE bureau_catalog_access_audit (
              audit_id TEXT PRIMARY KEY,
              actor TEXT NOT NULL,
              catalog_version_id TEXT,
              attribute_code TEXT,
              project_id TEXT,
              action TEXT NOT NULL,
              result_status TEXT NOT NULL,
              correlation_id TEXT NOT NULL,
              safe_detail TEXT,
              server_timestamp TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO catalog_registry_metadata VALUES (?, ?)",
            ("1.0", "2026-08-05T12:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO bureau_catalog_versions VALUES (
              ?, 'catalog-synthetic', 'provider-synthetic', 'product-synthetic',
              '2026', 'US', 'release-1', ?, ?, 12, 24, 'parser-1', '1.0',
              'source-reference-must-not-appear',
              'C:/restricted/path/must-not-appear',
              'installed', 'verified', 'restricted', 'system-catalog-installer',
              '2026-08-05T12:00:00Z', '2026-08-05T12:00:00Z',
              'current', 'active', 1
            )
            """,
            (CATALOG_VERSION_ID, SOURCE_CHECKSUM, CATALOG_CHECKSUM),
        )
        connection.execute(
            """
            INSERT INTO bureau_catalog_entitlements VALUES (
              'entitlement-1', 'reader-1', 'tenant-1', ?, ?,
              '["lookup"]', 'active', NULL, 'admin-1',
              '2026-08-05T12:01:00Z', NULL, NULL
            )
            """,
            (CATALOG_VERSION_ID, CATALOG_CHECKSUM),
        )
        connection.execute(
            """
            INSERT INTO bureau_catalog_access_audit VALUES (
              'audit-001', 'system-catalog-worker', ?, 'SYN001',
              'project-synthetic', 'catalog.lookup', 'allowed',
              'correlation-secret-must-not-appear',
              'message-body-must-not-appear', '2026-08-05T12:02:00Z'
            )
            """,
            (CATALOG_VERSION_ID,),
        )
        connection.commit()


def _security_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE users (
              user_id TEXT PRIMARY KEY,
              email TEXT UNIQUE NOT NULL,
              display_name TEXT NOT NULL,
              role TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              last_login_at TEXT,
              failed_login_count INTEGER NOT NULL DEFAULT 0,
              locked_until TEXT
            );
            CREATE TABLE credentials (
              user_id TEXT PRIMARY KEY,
              password_hash TEXT NOT NULL,
              password_algorithm TEXT NOT NULL,
              password_updated_at TEXT NOT NULL
            );
            CREATE TABLE sessions (
              session_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL REFERENCES users(user_id),
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              ip_address_hash TEXT,
              user_agent_hash TEXT,
              revoked_at TEXT
            );
            CREATE TABLE project_access (
              project_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              permission TEXT NOT NULL,
              granted_by_user_id TEXT,
              granted_at TEXT NOT NULL,
              PRIMARY KEY(project_id, user_id)
            );
            CREATE TABLE audit_events (
              audit_id TEXT PRIMARY KEY,
              timestamp TEXT NOT NULL,
              user_id TEXT,
              action TEXT NOT NULL,
              resource_type TEXT NOT NULL,
              resource_id TEXT,
              outcome TEXT NOT NULL,
              reason TEXT,
              metadata_json TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "user-sensitive-1",
                "private-email-must-not-appear@example.test",
                "Private Name Must Not Appear",
                "catalog_admin",
                "active",
                "2026-08-05T10:00:00Z",
                "2026-08-05T11:00:00Z",
                "2026-08-05T11:30:00Z",
                0,
                None,
            ),
        )
        connection.execute(
            "INSERT INTO credentials VALUES (?, ?, ?, ?)",
            (
                "user-sensitive-1",
                "password-hash-must-not-appear",
                "argon2id",
                "2026-08-05T10:00:00Z",
            ),
        )
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "replayable-session-id-must-not-appear",
                "user-sensitive-1",
                "2026-08-05T11:00:00Z",
                "2026-08-05T13:00:00Z",
                "2026-08-05T11:30:00Z",
                "ip-hash-must-not-appear",
                "user-agent-hash-must-not-appear",
                None,
            ),
        )
        connection.execute(
            "INSERT INTO project_access VALUES (?, ?, ?, ?, ?)",
            (
                "project-private-must-not-appear",
                "user-sensitive-1",
                "owner",
                "grantor-private-must-not-appear",
                "2026-08-05T10:05:00Z",
            ),
        )
        connection.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "security-audit-001",
                "2026-08-05T11:45:00Z",
                "user-sensitive-1",
                "catalog.read",
                "catalog_version",
                CATALOG_VERSION_ID,
                "allowed",
                "audit-reason-must-not-appear",
                '{"message":"audit-metadata-must-not-appear"}',
            ),
        )
        connection.commit()


def _primary_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE projects (
              project_id TEXT PRIMARY KEY,
              project_name TEXT NOT NULL,
              project_type TEXT NOT NULL,
              workflow_type TEXT NOT NULL,
              template_id TEXT,
              status TEXT NOT NULL,
              owner_user_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              metadata_json TEXT NOT NULL
            );
            CREATE TABLE audit_log (
              audit_id TEXT PRIMARY KEY,
              project_id TEXT,
              user_id TEXT,
              action_type TEXT NOT NULL,
              entity_type TEXT,
              entity_id TEXT,
              title TEXT,
              summary TEXT,
              created_at TEXT NOT NULL,
              metadata_json TEXT NOT NULL
            );
            CREATE TABLE analysis_partitions (
              analysis_partition_id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL REFERENCES projects(project_id),
              dataset_id TEXT NOT NULL,
              dataset_version_id TEXT NOT NULL,
              development_count INTEGER NOT NULL,
              holdout_count INTEGER NOT NULL,
              assignment_hash TEXT NOT NULL,
              status TEXT NOT NULL,
              revision INTEGER NOT NULL,
              final_holdout_status TEXT NOT NULL,
              holdout_isolation_status TEXT NOT NULL,
              row_assignments_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              sealed_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE run_records (
              run_id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL REFERENCES projects(project_id),
              run_type TEXT NOT NULL,
              workflow_type TEXT,
              status TEXT NOT NULL,
              started_at TEXT,
              completed_at TEXT,
              parameters_json TEXT NOT NULL,
              metrics_json TEXT NOT NULL,
              artifacts_json TEXT NOT NULL,
              error_json TEXT NOT NULL
            );
            CREATE TABLE candidate_selection_decisions (
              candidate_decision_id TEXT PRIMARY KEY,
              decision_status TEXT NOT NULL,
              project_id TEXT NOT NULL,
              dataset_id TEXT NOT NULL,
              dataset_version_id TEXT NOT NULL,
              feature_manifest_id TEXT NOT NULL,
              feature_manifest_hash TEXT,
              training_job_id TEXT NOT NULL,
              training_run_id TEXT NOT NULL,
              candidate_id TEXT NOT NULL,
              selection_metric_name TEXT NOT NULL,
              selection_metric_value REAL NOT NULL,
              selection_metric_source TEXT NOT NULL,
              selection_partition_id TEXT NOT NULL,
              ranking_snapshot_json TEXT NOT NULL,
              ranking_snapshot_hash TEXT NOT NULL,
              selection_rationale TEXT,
              selection_locked_at TEXT,
              actor TEXT,
              selection_integrity_status TEXT NOT NULL,
              selection_integrity_reason TEXT,
              holdout_isolation_status TEXT NOT NULL,
              holdout_isolation_reason TEXT,
              integrity_classified_at TEXT,
              integrity_classified_by TEXT,
              decision_contract_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "project-protected-1",
                "private-project-name-must-not-appear",
                "predictive",
                "predictive_modeling",
                None,
                "active",
                "owner-private-must-not-appear",
                "2026-08-05T09:00:00Z",
                "2026-08-05T12:00:00Z",
                '{"private":"project-metadata-must-not-appear"}',
            ),
        )
        connection.execute(
            "INSERT INTO audit_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "primary-audit-001",
                "project-protected-1",
                "actor-private-must-not-appear",
                "partition.confirm",
                "analysis_partition",
                "partition-1",
                "title-must-not-appear",
                "summary-message-must-not-appear",
                "2026-08-05T12:00:00Z",
                '{"message":"metadata-message-must-not-appear"}',
            ),
        )
        connection.execute(
            """
            INSERT INTO analysis_partitions VALUES (
              'partition-1', 'project-protected-1', 'dataset-1', 'version-1',
              80, 20, ?, 'current', 1, 'sealed', 'verified', ?,
              '2026-08-05T12:00:00Z', '2026-08-05T12:00:00Z',
              '2026-08-05T12:00:00Z'
            )
            """,
            ("c" * 64, '"holdout-row-membership-must-not-appear"'),
        )
        connection.execute(
            """
            INSERT INTO run_records VALUES (
              'train-run-1', 'project-protected-1', 'model_training',
              'predictive_modeling', 'completed', '2026-08-05T12:01:00Z',
              '2026-08-05T12:05:00Z',
              '{"secret":"training-parameters-must-not-appear"}',
              '{"metric":"training-metrics-must-not-appear"}',
              '{"artifact":"training-artifacts-must-not-appear"}',
              '{"error":"training-error-must-not-appear"}'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO candidate_selection_decisions VALUES (
              'candidate-decision-1', 'locked', 'project-protected-1',
              'dataset-1', 'version-1', 'feature-manifest-1', ?,
              'train-job-1', 'train-run-1', 'candidate-1',
              'roc_auc', 0.91, 'development_cv', 'development-partition-1',
              '[{"candidate":"ranking-payload-must-not-appear"}]', ?,
              'selection-rationale-must-not-appear',
              '2026-08-05T12:06:00Z', 'reviewer-private-must-not-appear',
              'verified', 'integrity-reason-must-not-appear', 'verified',
              'holdout-reason-must-not-appear', '2026-08-05T12:07:00Z',
              'classifier-private-must-not-appear', ?, '2026-08-05T12:06:00Z'
            )
            """,
            ("d" * 64, "e" * 64, "f" * 64),
        )
        connection.commit()


def _crosswalk_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE bureau_crosswalk_revisions (
              governance_id TEXT NOT NULL,
              revision INTEGER NOT NULL,
              revision_json TEXT NOT NULL,
              revision_checksum TEXT NOT NULL,
              previous_revision_checksum TEXT,
              project_id TEXT NOT NULL,
              dataset_id TEXT NOT NULL,
              dataset_version_id TEXT NOT NULL,
              catalog_checksum TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(governance_id, revision),
              UNIQUE(governance_id, revision_checksum)
            );
            CREATE TABLE bureau_crosswalk_heads (
              governance_id TEXT PRIMARY KEY,
              current_revision INTEGER NOT NULL,
              current_checksum TEXT NOT NULL,
              FOREIGN KEY(governance_id, current_revision)
                REFERENCES bureau_crosswalk_revisions(governance_id, revision)
            );
            """
        )
        connection.execute(
            """
            INSERT INTO bureau_crosswalk_revisions VALUES (
              'governance-private-must-not-appear', 1,
              '{"rationale":"crosswalk-rationale-must-not-appear"}',
              ?, NULL, 'project-private-must-not-appear',
              'dataset-private-must-not-appear',
              'version-private-must-not-appear', ?,
              '2026-08-05T14:00:00Z'
            )
            """,
            ("1" * 64, CATALOG_CHECKSUM),
        )
        connection.execute(
            """
            INSERT INTO bureau_crosswalk_revisions VALUES (
              'governance-private-must-not-appear', 2,
              '{"evidence":"crosswalk-evidence-must-not-appear"}',
              ?, ?, 'project-private-must-not-appear',
              'dataset-private-must-not-appear',
              'version-private-must-not-appear', ?,
              '2026-08-05T15:00:00Z'
            )
            """,
            ("2" * 64, "1" * 64, CATALOG_CHECKSUM),
        )
        connection.execute(
            "INSERT INTO bureau_crosswalk_heads VALUES (?, ?, ?)",
            ("governance-private-must-not-appear", 2, "2" * 64),
        )
        connection.commit()


def _catalog_manifest(database: Path, immutable_file: Path | None = None) -> dict[str, Any]:
    immutable = (
        [
            {
                "authority_id": "immutable-registry",
                "path": str(immutable_file),
                "required": True,
            }
        ]
        if immutable_file is not None
        else []
    )
    return {
        "schema_version": "1.0",
        "immutable_files": immutable,
        "sqlite_authorities": [
            {
                "authority_id": "catalog-db",
                "path": str(database),
                "profile": "bureau_catalog_registry",
                "required": True,
                "scope": {"catalog_version_id": CATALOG_VERSION_ID},
            }
        ],
    }


def test_capture_is_read_only_and_excludes_secrets_messages_and_memberships(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary.db"
    security = tmp_path / "security.db"
    catalog = tmp_path / "catalog.db"
    immutable = tmp_path / "registry.json"
    _primary_database(primary)
    _security_database(security)
    _catalog_database(catalog)
    immutable.write_text('{"safe":"identity"}', encoding="utf-8")
    before = {
        path: (_sha256(path), path.stat().st_mtime_ns)
        for path in (primary, security, catalog, immutable)
    }
    manifest = {
        "schema_version": "1.0",
        "immutable_files": [
            {
                "authority_id": "immutable-registry",
                "path": str(immutable),
                "required": True,
            }
        ],
        "sqlite_authorities": [
            {
                "authority_id": "primary-db",
                "path": str(primary),
                "profile": "atlas_primary",
                "required": True,
                "scope": {
                    "project_id": "project-protected-1",
                    "dataset_id": "dataset-1",
                    "dataset_version_id": "version-1",
                },
            },
            {
                "authority_id": "security-db",
                "path": str(security),
                "profile": "atlas_security",
                "required": True,
                "scope": {},
            },
            {
                "authority_id": "catalog-db",
                "path": str(catalog),
                "profile": "bureau_catalog_registry",
                "required": True,
                "scope": {"catalog_version_id": CATALOG_VERSION_ID},
            },
        ],
    }

    snapshot = capture_snapshot(manifest)
    rendered = json.dumps(snapshot, sort_keys=True)
    primary_logical = snapshot["sqlite_authorities"]["primary-db"]["logical"]
    run_records = primary_logical["projections"]["run_records"]
    candidate_decisions = primary_logical["projections"][
        "candidate_selection_decisions"
    ]

    assert snapshot["capture_complete"] is True
    assert run_records["row_count"] == 1
    assert run_records["status_counts"] == {"status": {"completed": 1}}
    assert run_records["timestamp_stats"]["completed_at"]["maximum"] == (
        "2026-08-05T12:05:00Z"
    )
    assert candidate_decisions["row_count"] == 1
    assert candidate_decisions["status_counts"] == {
        "decision_status": {"locked": 1},
        "holdout_isolation_status": {"verified": 1},
        "selection_integrity_status": {"verified": 1},
    }
    assert candidate_decisions["checksum_stats"]["decision_contract_hash"][
        "valid_sha256"
    ] == 1
    assert primary_logical["relationships"]["run_record_to_project"][
        "orphan_rows"
    ] == 0
    assert primary_logical["relationships"]["candidate_decision_to_project"][
        "orphan_rows"
    ] == 0
    assert snapshot["safety_contract"] == {
        "physical_paths_emitted": False,
        "credentials_selected": False,
        "message_bodies_selected": False,
        "row_memberships_selected": False,
        "holdout_data_selected": False,
        "sqlite_whole_file_authoritative": False,
    }
    prohibited = (
        str(tmp_path),
        "private-email-must-not-appear",
        "Private Name Must Not Appear",
        "password-hash-must-not-appear",
        "replayable-session-id-must-not-appear",
        "ip-hash-must-not-appear",
        "user-agent-hash-must-not-appear",
        "audit-reason-must-not-appear",
        "audit-metadata-must-not-appear",
        "correlation-secret-must-not-appear",
        "message-body-must-not-appear",
        "summary-message-must-not-appear",
        "holdout-row-membership-must-not-appear",
        "training-parameters-must-not-appear",
        "training-metrics-must-not-appear",
        "training-artifacts-must-not-appear",
        "training-error-must-not-appear",
        "ranking-payload-must-not-appear",
        "selection-rationale-must-not-appear",
        "integrity-reason-must-not-appear",
        "holdout-reason-must-not-appear",
        "C:/restricted/path/must-not-appear",
    )
    assert all(value not in rendered for value in prohibited)
    after = {
        path: (_sha256(path), path.stat().st_mtime_ns)
        for path in (primary, security, catalog, immutable)
    }
    assert after == before


def test_immutable_file_change_is_authoritative(tmp_path: Path) -> None:
    database = tmp_path / "catalog.db"
    immutable = tmp_path / "registry.json"
    _catalog_database(database)
    immutable.write_text("before", encoding="utf-8")
    manifest = _catalog_manifest(database, immutable)
    before = capture_snapshot(manifest)
    immutable.write_text("after", encoding="utf-8")
    after = capture_snapshot(manifest)

    comparison = compare_snapshots(before, after)

    assert comparison["passed"] is False
    assert "immutable_file_changed" in {
        item["code"] for item in comparison["authoritative_changes"]
    }


def test_whole_sqlite_hash_is_supplementary_when_safe_projections_do_not_change(
    tmp_path: Path,
) -> None:
    database = tmp_path / "catalog.db"
    _catalog_database(database)
    manifest = _catalog_manifest(database)
    before = capture_snapshot(manifest)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE irrelevant_cache(cache_key TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO irrelevant_cache VALUES ('not-authority')")
        connection.commit()
    after = capture_snapshot(manifest)

    comparison = compare_snapshots(before, after)

    assert comparison["passed"] is True
    assert comparison["authoritative_change_count"] == 0
    assert comparison["supplementary_changes"] == [
        {"code": "sqlite_whole_file_changed", "authority_id": "catalog-db"}
    ]


def test_locked_supplementary_file_hash_does_not_block_logical_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "security.db"
    _security_database(database)
    manifest = {
        "schema_version": "1.0",
        "immutable_files": [],
        "sqlite_authorities": [
            {
                "authority_id": "security-db",
                "path": str(database),
                "profile": "atlas_security",
                "required": True,
                "scope": {},
            }
        ],
    }
    before = capture_snapshot(manifest)

    def locked_hash(_path: Path) -> tuple[str, int]:
        raise PermissionError("synthetic sharing violation")

    monkeypatch.setattr(authority_snapshot, "_file_sha256", locked_hash)
    after = capture_snapshot(manifest)
    comparison = compare_snapshots(before, after)

    authority = after["sqlite_authorities"]["security-db"]
    assert after["capture_complete"] is True
    assert authority["available"] is True
    assert authority["required_tables_ok"] is True
    assert authority["whole_file"] == {
        "available": False,
        "comparison_policy": "supplementary",
        "scope": "main_database_file_only",
        "capture_error": "file_read_failed",
    }
    assert authority["logical"]["digest"] == before["sqlite_authorities"][
        "security-db"
    ]["logical"]["digest"]
    assert comparison["passed"] is True
    assert comparison["authoritative_change_count"] == 0
    assert comparison["supplementary_changes"] == [
        {
            "code": "sqlite_whole_file_availability_changed",
            "authority_id": "security-db",
        }
    ]


def test_identical_optional_unavailable_database_passes_with_warning(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "optional-never-created.db"
    manifest = {
        "schema_version": "1.0",
        "immutable_files": [],
        "sqlite_authorities": [
            {
                "authority_id": "optional-security-db",
                "path": str(missing),
                "profile": "atlas_security",
                "required": False,
                "scope": {},
            }
        ],
    }

    before = capture_snapshot(manifest)
    after = capture_snapshot(manifest)
    comparison = compare_snapshots(before, after)

    assert before["capture_complete"] is True
    assert after["capture_complete"] is True
    assert comparison["passed"] is True
    assert comparison["authoritative_changes"] == []
    assert comparison["baseline_warnings"] == [
        {
            "code": "optional_sqlite_authority_unavailable",
            "authority_id": "optional-security-db",
        }
    ]


def test_identical_required_unavailable_database_remains_blocking(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "required-never-created.db"
    manifest = {
        "schema_version": "1.0",
        "immutable_files": [],
        "sqlite_authorities": [
            {
                "authority_id": "required-security-db",
                "path": str(missing),
                "profile": "atlas_security",
                "required": True,
                "scope": {},
            }
        ],
    }

    before = capture_snapshot(manifest)
    after = capture_snapshot(manifest)
    comparison = compare_snapshots(before, after)

    assert before["capture_complete"] is False
    assert after["capture_complete"] is False
    assert comparison["passed"] is False
    assert "required_sqlite_authority_unavailable" in {
        item["code"] for item in comparison["authoritative_changes"]
    }


def test_status_revision_checksum_and_timestamp_changes_are_authoritative(
    tmp_path: Path,
) -> None:
    database = tmp_path / "catalog.db"
    _catalog_database(database)
    manifest = _catalog_manifest(database)
    before = capture_snapshot(manifest)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE bureau_catalog_versions
               SET integrity_status = 'failed',
                   normalized_catalog_checksum = ?,
                   registry_revision = 2,
                   updated_at = '2026-08-05T13:00:00Z'
             WHERE catalog_version_id = ?
            """,
            ("d" * 64, CATALOG_VERSION_ID),
        )
        connection.commit()
    after = capture_snapshot(manifest)

    projection = after["sqlite_authorities"]["catalog-db"]["logical"][
        "projections"
    ]["bureau_catalog_versions"]
    comparison = compare_snapshots(before, after)

    assert projection["status_counts"]["integrity_status"] == {"failed": 1}
    assert projection["revision_stats"]["registry_revision"]["maximum"] == 2
    assert projection["checksum_stats"]["normalized_catalog_checksum"][
        "valid_sha256"
    ] == 1
    assert projection["timestamp_stats"]["updated_at"]["maximum"] == (
        "2026-08-05T13:00:00Z"
    )
    assert comparison["passed"] is False
    assert "critical_logical_authority_changed" in {
        item["code"] for item in comparison["authoritative_changes"]
    }


def test_new_audit_row_fails_and_audit_summary_is_separate(tmp_path: Path) -> None:
    database = tmp_path / "catalog.db"
    _catalog_database(database)
    manifest = _catalog_manifest(database)
    before = capture_snapshot(manifest)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO bureau_catalog_access_audit VALUES (
              'audit-002', 'reader-2', ?, NULL, NULL, 'catalog.search',
              'denied', 'correlation-2', 'must-not-leak',
              '2026-08-05T13:00:00Z'
            )
            """,
            (CATALOG_VERSION_ID,),
        )
        connection.commit()
    after = capture_snapshot(manifest)

    audit = after["sqlite_authorities"]["catalog-db"]["audit"]
    table = audit["tables"]["bureau_catalog_access_audit"]
    comparison = compare_snapshots(before, after)

    assert audit["total_rows"] == 2
    assert table["max_id"] == "audit-002"
    assert table["max_server_timestamp"] == "2026-08-05T13:00:00Z"
    assert table["action_counts"] == {"catalog.lookup": 1, "catalog.search": 1}
    assert table["actor_classification"] == {
        "registered_or_external": 1,
        "system_or_service": 1,
    }
    assert table["binding_counts"] == {
        "entity_bound": 2,
        "project_bound": 1,
        "project_unbound": 1,
    }
    assert comparison["passed"] is False
    assert any(
        item["code"] == "new_live_audit_rows"
        and item["table"] == "bureau_catalog_access_audit"
        for item in comparison["authoritative_changes"]
    )
    assert "must-not-leak" not in json.dumps(after)


def test_relationship_orphan_is_detected_and_fails_comparison(tmp_path: Path) -> None:
    database = tmp_path / "catalog.db"
    _catalog_database(database)
    manifest = _catalog_manifest(database)
    before = capture_snapshot(manifest)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "UPDATE bureau_catalog_entitlements SET catalog_version_id = ?",
            ("missing-version",),
        )
        connection.commit()
    after = capture_snapshot(manifest)

    catalog = after["sqlite_authorities"]["catalog-db"]
    relationship = catalog["logical"]["relationships"][
        "entitlement_to_catalog_version"
    ]
    comparison = compare_snapshots(before, after)

    assert catalog["integrity_ok"] is False
    assert relationship["child_rows"] == 1
    assert relationship["matched_rows"] == 0
    assert relationship["orphan_rows"] == 1
    assert comparison["passed"] is False
    assert "relationship_integrity_regressed" in {
        item["code"] for item in comparison["authoritative_changes"]
    }
    assert "relationship_orphan_count_increased" in {
        item["code"] for item in comparison["authoritative_changes"]
    }


def test_unchanged_preexisting_orphan_passes_with_baseline_warning(
    tmp_path: Path,
) -> None:
    database = tmp_path / "catalog.db"
    _catalog_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "UPDATE bureau_catalog_entitlements SET catalog_version_id = ?",
            ("preexisting-missing-version",),
        )
        connection.commit()
    manifest = _catalog_manifest(database)

    before = capture_snapshot(manifest)
    after = capture_snapshot(manifest)
    comparison = compare_snapshots(before, after)

    assert before["sqlite_authorities"]["catalog-db"]["integrity_ok"] is False
    assert comparison["passed"] is True
    assert comparison["authoritative_change_count"] == 0
    assert comparison["baseline_warnings"] == [
        {
            "code": "preexisting_relationship_orphans",
            "authority_id": "catalog-db",
            "table": "entitlement_to_catalog_version",
            "orphan_rows": 1,
        }
    ]
    assert comparison["baseline_warning_count"] == 1


def test_increased_preexisting_orphan_count_fails(tmp_path: Path) -> None:
    database = tmp_path / "catalog.db"
    _catalog_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "UPDATE bureau_catalog_entitlements SET catalog_version_id = ?",
            ("preexisting-missing-version",),
        )
        connection.commit()
    manifest = _catalog_manifest(database)
    before = capture_snapshot(manifest)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            """
            INSERT INTO bureau_catalog_entitlements VALUES (
              'entitlement-2', 'reader-2', 'tenant-2',
              'new-missing-version', ?, '["lookup"]', 'active', NULL,
              'admin-1', '2026-08-05T13:00:00Z', NULL, NULL
            )
            """,
            (CATALOG_CHECKSUM,),
        )
        connection.commit()
    after = capture_snapshot(manifest)
    comparison = compare_snapshots(before, after)

    assert before["sqlite_authorities"]["catalog-db"]["logical"][
        "relationships"
    ]["entitlement_to_catalog_version"]["orphan_rows"] == 1
    assert after["sqlite_authorities"]["catalog-db"]["logical"][
        "relationships"
    ]["entitlement_to_catalog_version"]["orphan_rows"] == 2
    assert comparison["passed"] is False
    assert "relationship_orphan_count_increased" in {
        item["code"] for item in comparison["authoritative_changes"]
    }
    assert comparison["baseline_warning_count"] == 0


def test_security_projection_classifies_actor_role_without_emitting_identity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "security.db"
    _security_database(database)
    manifest = {
        "schema_version": "1.0",
        "immutable_files": [],
        "sqlite_authorities": [
            {
                "authority_id": "security-db",
                "path": str(database),
                "profile": "atlas_security",
                "required": True,
                "scope": {},
            }
        ],
    }

    snapshot = capture_snapshot(manifest)
    security = snapshot["sqlite_authorities"]["security-db"]
    audit = security["audit"]["tables"]["audit_events"]
    sessions = security["logical"]["projections"]["sessions"]
    rendered = json.dumps(snapshot, sort_keys=True)

    assert snapshot["capture_complete"] is True
    assert sessions["row_count"] == 1
    assert sessions["derived_status_counts"] == {
        "revoked_at": {"not_revoked": 1}
    }
    assert audit["actor_classification"] == {"role:catalog_admin": 1}
    assert "user-sensitive-1" not in rendered
    assert "replayable-session-id-must-not-appear" not in rendered
    assert "password-hash-must-not-appear" not in rendered


def test_crosswalk_governance_profile_hashes_payload_and_validates_head_link(
    tmp_path: Path,
) -> None:
    database = tmp_path / "crosswalk.db"
    _crosswalk_database(database)
    manifest = {
        "schema_version": "1.0",
        "immutable_files": [],
        "sqlite_authorities": [
            {
                "authority_id": "crosswalk-db",
                "path": str(database),
                "profile": "bureau_crosswalk_governance",
                "required": True,
                "scope": {
                    "governance_id": "governance-private-must-not-appear",
                    "project_id": "project-private-must-not-appear",
                    "dataset_id": "dataset-private-must-not-appear",
                    "dataset_version_id": "version-private-must-not-appear",
                    "catalog_checksum": CATALOG_CHECKSUM,
                },
            }
        ],
    }

    snapshot = capture_snapshot(manifest)
    authority = snapshot["sqlite_authorities"]["crosswalk-db"]
    revisions = authority["logical"]["projections"]["bureau_crosswalk_revisions"]
    head = authority["logical"]["projections"]["bureau_crosswalk_heads"]
    relationship = authority["logical"]["relationships"][
        "crosswalk_head_to_current_revision"
    ]
    rendered = json.dumps(snapshot, sort_keys=True)

    assert snapshot["capture_complete"] is True
    assert authority["integrity_ok"] is True
    assert revisions["row_count"] == 2
    assert revisions["revision_stats"]["revision"]["maximum"] == 2
    assert revisions["checksum_stats"]["revision_checksum"]["valid_sha256"] == 2
    assert revisions["timestamp_stats"]["created_at"]["maximum"] == (
        "2026-08-05T15:00:00Z"
    )
    assert head["revision_stats"]["current_revision"]["maximum"] == 2
    assert relationship["orphan_rows"] == 0
    assert authority["audit"] == {
        "tables": {},
        "total_rows": 0,
        "digest": hashlib.sha256(b"{}").hexdigest(),
    }
    assert "crosswalk-rationale-must-not-appear" not in rendered
    assert "crosswalk-evidence-must-not-appear" not in rendered
    assert "governance-private-must-not-appear" not in rendered


def test_crosswalk_payload_or_head_tampering_is_authoritative(tmp_path: Path) -> None:
    database = tmp_path / "crosswalk.db"
    _crosswalk_database(database)
    manifest = {
        "schema_version": "1.0",
        "immutable_files": [],
        "sqlite_authorities": [
            {
                "authority_id": "crosswalk-db",
                "path": str(database),
                "profile": "bureau_crosswalk_governance",
                "required": True,
                "scope": {"governance_id": "governance-private-must-not-appear"},
            }
        ],
    }
    before = capture_snapshot(manifest)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            """
            UPDATE bureau_crosswalk_revisions
               SET revision_json = '{"tampered":true}'
             WHERE revision = 1
            """
        )
        connection.execute(
            "UPDATE bureau_crosswalk_heads SET current_revision = 3"
        )
        connection.commit()
    after = capture_snapshot(manifest)

    authority = after["sqlite_authorities"]["crosswalk-db"]
    comparison = compare_snapshots(before, after)

    assert authority["integrity_ok"] is False
    assert authority["logical"]["relationships"][
        "crosswalk_head_to_current_revision"
    ]["orphan_rows"] == 1
    assert comparison["passed"] is False
    assert "critical_logical_authority_changed" in {
        item["code"] for item in comparison["authoritative_changes"]
    }
    assert "relationship_integrity_regressed" in {
        item["code"] for item in comparison["authoritative_changes"]
    }
    assert "relationship_orphan_count_increased" in {
        item["code"] for item in comparison["authoritative_changes"]
    }


def test_identical_snapshots_pass_with_no_changes(tmp_path: Path) -> None:
    database = tmp_path / "catalog.db"
    immutable = tmp_path / "registry.json"
    _catalog_database(database)
    immutable.write_text("stable", encoding="utf-8")
    manifest = _catalog_manifest(database, immutable)

    before = capture_snapshot(manifest)
    after = capture_snapshot(manifest)
    comparison = compare_snapshots(before, after)

    assert before["captured_at"] != ""
    assert comparison == {
        "schema_version": "1.0",
        "comparison_mode": "logical_and_audit_authoritative",
        "passed": True,
        "authoritative_change_count": 0,
        "authoritative_changes": [],
        "baseline_warning_count": 0,
        "baseline_warnings": [],
        "supplementary_change_count": 0,
        "supplementary_changes": [],
        "whole_sqlite_hash_authoritative": False,
    }

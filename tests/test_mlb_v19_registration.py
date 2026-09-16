"""One focused existing-schema append-only/idempotency protection."""
import copy
import sqlite3

import pytest

from scripts.register_mlb_v19_study import (
    DELIVERABLES, PROJECT_ID, SCHEMA, _append_only_authorizer, append_registration,
)


def test_registration_is_append_only_idempotent_and_completion_gated():
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE projects(project_id TEXT PRIMARY KEY,owner_user_id TEXT);
        CREATE TABLE users(user_id TEXT PRIMARY KEY);
        CREATE TABLE models(model_id TEXT PRIMARY KEY,current_version_id TEXT);
        CREATE TABLE run_records(run_id TEXT PRIMARY KEY,project_id TEXT,run_type TEXT,workflow_type TEXT,
            status TEXT,started_at TEXT,completed_at TEXT,parameters_json TEXT,metrics_json TEXT,
            artifacts_json TEXT,error_json TEXT,created_by TEXT);
        CREATE TABLE evidence_artifacts(evidence_id TEXT PRIMARY KEY,project_id TEXT,workflow_type TEXT,
            step_id TEXT,artifact_type TEXT,status TEXT,title TEXT,summary TEXT,source_ref TEXT,
            artifact_hash TEXT,created_by TEXT,created_at TEXT,captured_at TEXT,approved_at TEXT,payload_json TEXT);
        INSERT INTO users VALUES('owner');
        INSERT INTO models VALUES('V18','retained-version');
    """)
    connection.execute("INSERT INTO projects VALUES(?,?)", (PROJECT_ID, "owner"))
    connection.commit()
    connection.set_authorizer(_append_only_authorizer)
    manifest = {"schemaVersion": SCHEMA, "projectId": PROJECT_ID, "status": "COMPLETED",
                "studyId": "synthetic-registration-fixture", "startedAtUtc": "2026-09-10T00:00:00Z",
                "completedAtUtc": "2026-09-11T00:00:00Z", "verdict": "MLB_V18_RETAINED_AFTER_SPECIALIST_STUDY",
                "authority": {"status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED",
                              "wageringAuthority": False, "executionAllowedInAISP": False, "finalOotAccessed": False},
                "deliverables": {key: {"fixture": True} for key in DELIVERABLES}}
    reference = {"path": "SYNTHETIC_FIXTURE_NOT_REAL_STUDY", "sha256": "0" * 64, "byteCount": 1}
    assert append_registration(connection, manifest, reference)["status"] == "READY_TO_REGISTER_RESEARCH_ONLY"
    assert connection.execute("SELECT COUNT(*) FROM run_records").fetchone()[0] == 0
    first = append_registration(connection, manifest, reference, apply=True)
    assert first["status"] == "REGISTERED_RESEARCH_ONLY" and len(first["insertedIds"]) == 2
    assert append_registration(connection, manifest, reference, apply=True)["status"] == "NO_OP"
    assert connection.execute("SELECT COUNT(*) FROM run_records").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM evidence_artifacts").fetchone()[0] == 1
    assert connection.execute("SELECT current_version_id FROM models").fetchone()[0] == "retained-version"
    changed = copy.deepcopy(manifest)
    changed["verdict"] = "MLB_V19_GLOBAL_CHALLENGER_ONLY"
    with pytest.raises(ValueError, match="conflicts"):
        append_registration(connection, changed, reference, apply=True)
    changed["status"] = "RUNNING"
    with pytest.raises(ValueError, match="completed"):
        append_registration(connection, changed, reference, apply=True)
    with pytest.raises(sqlite3.DatabaseError, match="authorized"):
        connection.execute("UPDATE models SET current_version_id=?", ("unauthorized",))
    assert connection.execute("SELECT current_version_id FROM models").fetchone()[0] == "retained-version"
    connection.close()

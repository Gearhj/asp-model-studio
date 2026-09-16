"""One focused contract check for saved MLB research evidence serving."""
import hashlib
import json
import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.sports_current_statcast import mlb_regime_study_registration as registration
from server.sports_current_statcast import mlb_regime_study_ui as ui


def test_project_authenticated_checksum_reader_and_append_only_registration(tmp_path):
    study = tmp_path / "study"
    study.mkdir()

    def save(name, body):
        raw = json.dumps(body, sort_keys=True).encode()
        path = study / name
        path.write_bytes(raw)
        return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "byteCount": len(raw)}

    artifact = save("cluster-profiles.json", {"clusters": []})
    authority = {"status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED", "finalOotAccessed": False,
                 "wageringAuthority": False, "executionAllowedInAISP": False}
    ref = save("result.json", {"contract": registration.CONTRACT, "projectId": registration.PROJECT_ID,
               "studyId": "test-regime-study", "status": "COMPLETED", "authority": authority,
               "completedAtUtc": "2026-09-10T14:00:00Z", "verdict": "NO_DEMONSTRATED_IMPROVEMENT",
               "cohort": {"observations": 2}, "artifacts": [artifact]})
    save("latest.json", {"result": ref})
    database = tmp_path / "studio.db"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript("""
            CREATE TABLE projects(project_id TEXT PRIMARY KEY, owner_user_id TEXT);
            CREATE TABLE users(user_id TEXT PRIMARY KEY);
            CREATE TABLE run_records(run_id TEXT PRIMARY KEY, project_id TEXT, run_type TEXT, workflow_type TEXT,
                status TEXT, started_at TEXT, completed_at TEXT, parameters_json TEXT, metrics_json TEXT,
                artifacts_json TEXT, error_json TEXT, created_by TEXT);
            CREATE TABLE evidence_artifacts(evidence_id TEXT PRIMARY KEY, project_id TEXT, workflow_type TEXT,
                step_id TEXT, artifact_type TEXT, status TEXT, title TEXT, summary TEXT, source_ref TEXT,
                artifact_hash TEXT, created_by TEXT, created_at TEXT, captured_at TEXT, approved_at TEXT, payload_json TEXT);
        """)
        connection.execute("INSERT INTO users VALUES (?)", ("actual-owner",))
        connection.execute("INSERT INTO projects VALUES (?,?)", (registration.PROJECT_ID, "actual-owner"))
        original_project = connection.execute("SELECT * FROM projects").fetchall()

    with patch.object(registration, "ROOT", tmp_path), patch.object(registration, "STUDY_ROOT", study), patch.object(ui, "ROOT", study):
        first = registration.register_study(ref, database_path=database)
        assert first["status"] == "REGISTERED_RESEARCH_ONLY"
        assert registration.register_study(ref, database_path=database)["insertedIds"] == []
        catalog, allowed = ui.study_catalog()
        assert catalog["cohort"]["observations"] == 2 and catalog["calibration"] == []
        assert len(allowed) == 2 and catalog["warnings"] == []
        with pytest.raises(registration.MlbRegimeStudyError, match="checksum or byte count"):
            registration.register_study({**ref, "byteCount": ref["byteCount"] + 1}, database_path=database)
        with pytest.raises(registration.MlbRegimeStudyError, match="outside"):
            registration.checked_artifact({**ref, "path": str(tmp_path / "not-published.json")})

        app = FastAPI()
        app.include_router(ui.router)

        def unsigned():
            raise HTTPException(status_code=401, detail="Sign in")

        app.dependency_overrides[ui.require_user] = unsigned
        with TestClient(app) as client, patch.object(ui, "study_catalog") as not_called:
            assert client.get("/sports/mlb/regime-study").status_code == 401
            not_called.assert_not_called()
        app.dependency_overrides[ui.require_user] = lambda: {"userId": "viewer"}
        with TestClient(app) as client, patch.object(ui, "SharingService") as service:
            service.return_value.check_permission.return_value = {"allowed": False}
            assert client.get("/sports/mlb/regime-study").status_code == 403
            service.return_value.check_permission.return_value = {"allowed": True}
            assert client.get("/sports/mlb/regime-study").status_code == 200
            artifact_id = next(key for key, item in allowed.items() if item["sha256"] == artifact["sha256"])
            download = client.get(f"/sports/mlb/regime-study/artifacts/{artifact_id}")
            assert download.status_code == 200 and download.headers["x-artifact-sha256"] == artifact["sha256"]
            assert service.return_value.check_permission.call_args.args[-1] == "export"

        # A changed child is not advertised or registered, while the saved result remains visible.
        (study / "cluster-profiles.json").write_bytes(b"{}")
        catalog, allowed = ui.study_catalog()
        assert len(allowed) == 1 and "checksum" in catalog["warnings"][0]
        with pytest.raises(registration.MlbRegimeStudyError, match="checksum"):
            registration.register_study(ref, database_path=database)
        save("latest.json", {"result": {**ref, "sha256": "0" * 64}})
        catalog, allowed = ui.study_catalog()
        assert catalog["status"] == "NOT_AVAILABLE" and allowed == {}

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT * FROM projects").fetchall() == original_project
        assert connection.execute("SELECT COUNT(*) FROM run_records").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM evidence_artifacts").fetchone()[0] == 1
        assert connection.execute("SELECT DISTINCT created_by FROM run_records").fetchall() == [("actual-owner",)]

"""Focused regression protection for read-only laboratory evidence serving."""
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from server.sports_nfl_m1 import laboratory_ui as ui


def test_artifact_reference_rejects_outside_roots_and_changed_bytes():
    with tempfile.TemporaryDirectory(prefix="nfl-lab-links-") as directory:
        root = Path(directory)
        published = root / "published"
        published.mkdir()
        path = published / "result.json"
        raw = b'{"status":"COMPLETE"}'
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        with patch.object(ui, "ALLOWED_ROOTS", (published,)):
            assert ui._checked(path, digest)[2] == digest
            path.write_bytes(b'{"status":"REPLACED"}')
            with pytest.raises(ValueError, match="checksum"):
                ui._checked(path, digest)
            with pytest.raises(ValueError, match="outside"):
                ui._checked(published / ".." / "other.json")


def test_incomplete_publication_not_advertised_and_project_permission_required():
    with tempfile.TemporaryDirectory(prefix="nfl-lab-incomplete-") as directory:
        root = Path(directory)
        folders = tuple(root / str(index) for index in range(5))
        folders[1].mkdir()
        (folders[1] / "CURRENT.json").write_text(json.dumps({"status": "RUNNING", "path": str(root / "absent.json"), "sha256": "0" * 64}))
        with patch.object(ui, "LOCAL_OUTPUTS", folders):
            catalog, _ = ui.laboratory_catalog()
        assert not any(group["id"] == "semantic" for group in catalog["groups"])
        assert "Semantic laboratory: publication is not complete." in catalog["warnings"]
    with patch.object(ui, "SharingService") as service:
        service.return_value.check_permission.return_value = {"allowed": False}
        with pytest.raises(HTTPException) as error:
            ui._permission({"userId": "no-project-access", "role": "analyst"})
        assert error.value.status_code == 403


def test_current_state_results_are_verified_and_registration_is_append_only():
    import sqlite3
    from contextlib import closing
    from server.sports_nfl_m1 import current_state_registration as registration

    repair_root = ui.ROOT / "outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1"
    assert repair_root in ui.ALLOWED_ROOTS and repair_root in registration.ARTIFACT_ROOTS

    with tempfile.TemporaryDirectory(prefix="nfl-current-state-registration-") as directory:
        root = Path(directory)
        study = root / "study"
        study.mkdir()
        def save(name, body):
            raw = json.dumps(body, sort_keys=True).encode()
            path = study / name
            path.write_bytes(raw)
            return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "byteCount": len(raw)}
        authority = {"status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED", "wageringAuthority": False, "executionAllowedInAISP": False}
        fold = save("fold.json", {"eventCount": 32})
        declaration = save("declaration.json", {"declaredAtUtc": "2026-09-09T10:00:00Z"})
        ref = save("result.json", {**authority, "contract": "NFL_CURRENT_STATE_RECONSTRUCTED_STUDY_RESULT_V2",
                   "evidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF", "finalOotAccessed": False,
                   "completedAtUtc": "2026-09-09T12:00:00Z", "declaration": declaration, "artifacts": [fold, declaration],
                   "leaderboard": [{"pipelineId": "RESIDUAL_LAG48", "component": "RESIDUAL", "lagHours": 48,
                                    "metrics": {"raw": {"games": 32, "multiclassLogLoss": 0.67}},
                                    "subgroups": {"WEEKS_1_4": {"raw": {"games": 8, "multiclassLogLoss": 0.69}}}}]})
        publication = save("handoff.json", {**authority, "contract": "NFL_CURRENT_STATE_JOINT_DISTRIBUTION_HANDOFF_V2", "study": ref, "forecastCount": 16})
        quote_contract = save("quote-contract.json", {"evidenceClass": "OBSERVED_AS_OF", "required": ["observedAtUtc", "firstAvailableAtUtc"]})
        market = save("market-comparison.json", {"status": "PENDING_TIMESTAMPED_MARKET_EVIDENCE", "exportContract": quote_contract})
        quality = save("quality-notice.json", {"publicationDisposition": "DYNAMIC_ONLY_LEARNED_COMPONENTS_WITHHELD"})
        save("CURRENT.json", {"status": "COMPLETED", "result": ref, "publication": publication, "marketComparison": market,
                              "qualityNotice": quality, "publicationDisposition": "DYNAMIC_ONLY_LEARNED_COMPONENTS_WITHHELD"})
        folders = tuple(root / f"absent{index}" for index in range(5))
        with patch.object(ui, "CURRENT_STATE_OUTPUT", study), patch.object(ui, "FORWARD_OUTPUT", root / "absent-archive"), \
                patch.object(ui, "LOCAL_OUTPUTS", folders), patch.object(ui, "ALLOWED_ROOTS", (study,)):
            catalog, allowed = ui.laboratory_catalog()
        group = next(group for group in catalog["groups"] if group["id"] == "current-state")
        assert group["rows"][0]["multiclassLogLoss"] == 0.67
        assert group["rows"][0]["calibratedLogLoss"] is None
        assert group["rows"][0]["subgroups"]["WEEKS_1_4"]["games"] == 8
        assert "not historically observed" in group["note"]
        assert any(value[1] == fold["sha256"] for value in allowed.values())
        assert {publication["sha256"], market["sha256"], quote_contract["sha256"]} <= {value[1] for value in allowed.values()}
        assert quality["sha256"] in {value[1] for value in allowed.values()}
        assert "DYNAMIC baseline only" in group["note"] and "Historical study rows are retained" in group["note"]
        save("CURRENT.json", {"status": "COMPLETED", "result": ref, "publication": publication,
                              "qualityNotice": quality, "publicationDisposition": "REPAIRED_HISTORICAL_PRIOR_BASELINE"})
        with patch.object(ui, "CURRENT_STATE_OUTPUT", study), patch.object(ui, "FORWARD_OUTPUT", root / "absent-archive"), \
                patch.object(ui, "LOCAL_OUTPUTS", folders), patch.object(ui, "ALLOWED_ROOTS", (study,)):
            repaired_catalog, _ = ui.laboratory_catalog()
        repaired_group = next(group for group in repaired_catalog["groups"] if group["id"] == "current-state")
        assert "HISTORICAL_PRIOR_BASELINE" in repaired_group["note"] and "descriptive only" in repaired_group["note"]
        assert "DYNAMIC baseline only" not in repaired_group["note"] and repaired_group["rows"] == group["rows"]
        assert any(item["label"] == "Current-state repair delivery and verification" for item in repaired_catalog["artifacts"])
        database = root / "fixture.db"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.executescript("""
                CREATE TABLE users(user_id TEXT PRIMARY KEY);
                CREATE TABLE projects(project_id TEXT PRIMARY KEY,owner_user_id TEXT,metadata_json TEXT,status TEXT,champion_pointer TEXT);
                CREATE TABLE run_records(run_id TEXT PRIMARY KEY,project_id TEXT,run_type TEXT,workflow_type TEXT,status TEXT,
                    started_at TEXT,completed_at TEXT,parameters_json TEXT,metrics_json TEXT,artifacts_json TEXT,error_json TEXT,created_by TEXT);
                CREATE TABLE evidence_artifacts(evidence_id TEXT PRIMARY KEY,project_id TEXT,workflow_type TEXT,step_id TEXT,
                    artifact_type TEXT,status TEXT,title TEXT,summary TEXT,source_ref TEXT,artifact_hash TEXT,created_by TEXT,
                    created_at TEXT,captured_at TEXT,approved_at TEXT,payload_json TEXT);
            """)
            connection.execute("INSERT INTO users VALUES ('actual-owner')")
            connection.execute("INSERT INTO projects VALUES (?,?,?,?,?)", (ui.PROJECT_ID, "actual-owner", '{"keep":"all metadata"}', "in_progress", "unchanged-reference"))
            before_project = connection.execute("SELECT * FROM projects").fetchall()
        with patch.object(registration, "ROOT", root), patch.object(registration, "ARTIFACT_ROOTS", (study,)):
            first = registration.register_study(ref, database_path=database)
            assert first["status"] == "REGISTERED_RESEARCH_ONLY"
            with closing(sqlite3.connect(database)) as connection, connection:
                original_run = connection.execute("SELECT * FROM run_records").fetchall()
            enriched = registration.register_study(ref, publication, database_path=database)
            assert enriched["runId"] == first["runId"] and len(enriched["insertedIds"]) == 1
            repeated = registration.register_study(ref, publication, database_path=database)
            assert repeated["status"] == "NO_OP" and repeated["insertedIds"] == []
            with pytest.raises(registration.CurrentStateRegistrationError, match="checksum or byte count"):
                registration.register_study({**ref, "byteCount": ref["byteCount"] + 1}, database_path=database)
        with closing(sqlite3.connect(database)) as connection, connection:
            assert connection.execute("SELECT * FROM projects").fetchall() == before_project
            assert connection.execute("SELECT * FROM run_records").fetchall() == original_run
            assert connection.execute("SELECT COUNT(*) FROM evidence_artifacts").fetchone()[0] == 2
            assert connection.execute("SELECT DISTINCT created_by FROM run_records").fetchall() == [("actual-owner",)]

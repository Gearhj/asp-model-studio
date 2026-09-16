"""Append immutable MLB regime-study evidence without changing model authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from server.persistence.db import Database, json_dumps, now_iso

ROOT = Path(__file__).resolve().parents[2]
STUDY_ROOT = ROOT / "outputs/mlb-regime-hybrid-ensemble-v1"
PROJECT_ID = "asp-mtlozhdx"
CONTRACT = "MLB_REGIME_HYBRID_STUDY_V1"
DEFAULT_DATABASE_PATH = ROOT / ".runtime/asp-model-studio/persistence/asp_model_studio.db"


class MlbRegimeStudyError(ValueError):
    pass


def checked_artifact(ref: Mapping[str, Any]) -> Path:
    """Verify published bytes; never resolve arbitrary paths outside this study."""
    path = Path(ref["path"]).resolve()
    if not path.is_relative_to(STUDY_ROOT.resolve()):
        raise MlbRegimeStudyError("Artifact is outside the MLB regime-study output root.")
    if not path.is_file():
        raise MlbRegimeStudyError("Published artifact is unavailable.")
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            byte_count += len(chunk)
    if digest.hexdigest() != ref.get("sha256") or byte_count != ref.get("byteCount"):
        raise MlbRegimeStudyError("Artifact checksum or byte count differs from its publication.")
    return path


def read_result(ref: Mapping[str, Any], *, completed: bool = True) -> dict[str, Any]:
    result = json.loads(checked_artifact(ref).read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("contract") != CONTRACT or result.get("projectId") != PROJECT_ID:
        raise MlbRegimeStudyError("Expected the project-bound MLB regime-study contract.")
    authority = result.get("authority", result)
    if (not isinstance(authority, dict) or authority.get("status") != "RESEARCH_SHADOW"
            or authority.get("promotionStatus") != "NOT_PROMOTED"
            or authority.get("wageringAuthority") is not False
            or authority.get("executionAllowedInAISP") is not False
            or authority.get("finalOotAccessed") is not False):
        raise MlbRegimeStudyError("Expected research-only, nonexecuting evidence with Final OOT sealed.")
    if completed and (result.get("status") not in {"COMPLETED", "RESEARCH_SHADOW"}
                      or not result.get("completedAtUtc") or not result.get("studyId")):
        raise MlbRegimeStudyError("The MLB regime study is not completed.")
    return result


def register_study(result_ref: Mapping[str, Any], *, database_path: Path = DEFAULT_DATABASE_PATH) -> dict[str, Any]:
    """Verify first, then insert one run and evidence record idempotently."""
    result_ref = dict(result_ref)
    result = read_result(result_ref)
    for ref in result.get("artifacts", []):
        checked_artifact(ref)
    database_path = Path(database_path).resolve()
    if not database_path.is_relative_to(ROOT.resolve()) or not database_path.is_file():
        raise MlbRegimeStudyError("An existing Model Studio database is required; no database or AISP creation is allowed.")
    digest = result_ref["sha256"]
    run_id = "mlb-regime-study-" + digest
    evidence_id = "mlb-regime-evidence-" + digest
    inserted = []
    with Database(database_path).transaction() as connection:
        connection.execute("BEGIN IMMEDIATE")
        project = connection.execute("SELECT owner_user_id FROM projects WHERE project_id=?", (PROJECT_ID,)).fetchone()
        if project is None or not project["owner_user_id"]:
            raise MlbRegimeStudyError("The existing MLB project owner must be available.")
        owner = project["owner_user_id"]
        if connection.execute("SELECT user_id FROM users WHERE user_id=?", (owner,)).fetchone() is None:
            raise MlbRegimeStudyError("The MLB project owner is not a registered local user.")
        prior = connection.execute("SELECT project_id,artifacts_json FROM run_records WHERE run_id=?", (run_id,)).fetchone()
        if prior:
            if prior["project_id"] != PROJECT_ID or json.loads(prior["artifacts_json"]).get("result") != result_ref:
                raise MlbRegimeStudyError("Existing run identity conflicts; no historical record was changed.")
        else:
            connection.execute("""INSERT INTO run_records
                (run_id,project_id,run_type,workflow_type,status,started_at,completed_at,
                 parameters_json,metrics_json,artifacts_json,error_json,created_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, PROJECT_ID, "mlb_regime_hybrid_study", "mlb-forecasting", "completed",
                 result.get("startedAtUtc"), result["completedAtUtc"],
                 json_dumps({"studyId": result["studyId"], "authority": result.get("authority", {})}),
                 json_dumps({key: result.get(key) for key in ("verdict", "cohort", "baselineParity", "leaderboard", "gameSimulation")}),
                 json_dumps({"result": result_ref, "artifacts": result.get("artifacts", [])}), "{}", owner))
            inserted.append(run_id)
        prior = connection.execute("SELECT project_id,artifact_hash,source_ref FROM evidence_artifacts WHERE evidence_id=?", (evidence_id,)).fetchone()
        if prior:
            if (prior["project_id"], prior["artifact_hash"], prior["source_ref"]) != (PROJECT_ID, digest, result_ref["path"]):
                raise MlbRegimeStudyError("Existing evidence identity conflicts; no historical record was changed.")
        else:
            timestamp = now_iso()
            connection.execute("""INSERT INTO evidence_artifacts
                (evidence_id,project_id,workflow_type,step_id,artifact_type,status,title,summary,
                 source_ref,artifact_hash,created_by,created_at,captured_at,approved_at,payload_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (evidence_id, PROJECT_ID, "mlb-forecasting", "mlb-09", "research_evidence", "complete_development_only",
                 "MLB regime, residual specialist and ensemble study",
                 "Development evidence only; retained models, policy and prospective evidence remain unchanged.",
                 result_ref["path"], digest, owner, timestamp, timestamp, None,
                 json_dumps({"result": result_ref, "verdict": result.get("verdict"), "finalOotAccessed": False,
                             "wageringAuthority": False, "executionAllowedInAISP": False})))
            inserted.append(evidence_id)
    return {"status": "REGISTERED_RESEARCH_ONLY" if inserted else "NO_OP", "projectId": PROJECT_ID,
            "runId": run_id, "evidenceId": evidence_id, "insertedIds": inserted,
            "projectMetadataChanged": False, "workflowStateChanged": False, "championPointerChanged": False,
            "policyChanged": False, "aispWrites": 0, "modelFits": 0}

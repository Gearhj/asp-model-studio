"""Append completed V2 research evidence to the existing NFL project only.

No project, workflow, model, champion, sharing or source registration is changed.
The caller must explicitly invoke this adapter after producing immutable results.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from server.persistence.db import Database, json_dumps, now_iso
from .lab_registration import DEFAULT_DATABASE_PATH, PROJECT_ID

ROOT = Path(__file__).resolve().parents[2]
STUDY_ROOT = ROOT / "outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1"
ARTIFACT_ROOTS = (STUDY_ROOT, ROOT / "outputs/nfl-forward-vintages-v1",
                  ROOT / "outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1")
EVIDENCE_CLASS = "RETROSPECTIVE_RECONSTRUCTED_AS_OF"


class CurrentStateRegistrationError(ValueError):
    pass


def _verified(ref: Mapping[str, Any], *, json_object: bool = False):
    path = Path(ref["path"]).resolve()
    if not any(path.is_relative_to(root.resolve()) for root in ARTIFACT_ROOTS):
        raise CurrentStateRegistrationError("research evidence is outside the dedicated Model Studio output roots")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref["sha256"] or len(raw) != ref["byteCount"]:
        raise CurrentStateRegistrationError("research evidence checksum or byte count differs")
    if not json_object:
        return None
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise CurrentStateRegistrationError("research evidence must be a JSON object")
    return body


def _research_authority(body: Mapping[str, Any]):
    if (body.get("status") != "RESEARCH_SHADOW" or body.get("promotionStatus") != "NOT_PROMOTED"
            or body.get("wageringAuthority") is not False or body.get("executionAllowedInAISP") is not False):
        raise CurrentStateRegistrationError("only nonexecuting, unpromoted research-shadow evidence may be registered")


def register_study(result_ref: Mapping[str, Any], publication_ref: Mapping[str, Any] | None = None, *,
                   database_path: Path = DEFAULT_DATABASE_PATH) -> dict[str, Any]:
    """Checksum-verify first, then atomically append run/evidence, never upsert."""
    result_ref = dict(result_ref)
    result = _verified(result_ref, json_object=True)
    _research_authority(result)
    if (result.get("contract") != "NFL_CURRENT_STATE_RECONSTRUCTED_STUDY_RESULT_V2"
            or result.get("evidenceClass") != EVIDENCE_CLASS or result.get("finalOotAccessed") is not False):
        raise CurrentStateRegistrationError("expected completed reconstructed Development result with sealed OOT")
    if not result.get("completedAtUtc") or not result.get("leaderboard"):
        raise CurrentStateRegistrationError("incomplete studies cannot be registered")
    for ref in result.get("artifacts", []):
        _verified(ref)
    declaration = _verified(result["declaration"], json_object=True) if result.get("declaration") else {}
    publication = None
    if publication_ref is not None:
        publication_ref = dict(publication_ref)
        publication = _verified(publication_ref, json_object=True)
        _research_authority(publication)
        if (publication.get("schemaVersion", publication.get("contract")) != "NFL_CURRENT_STATE_JOINT_DISTRIBUTION_HANDOFF_V2"
                or publication.get("study") != result_ref):
            raise CurrentStateRegistrationError("publication must reference this exact reconstructed study")

    database_path = Path(database_path).resolve()
    if not database_path.is_relative_to(ROOT.resolve()) or not database_path.is_file():
        raise CurrentStateRegistrationError("existing Model Studio database is required; database creation or AISP access is prohibited")
    database = Database(database_path)
    run_id = "nfl-current-state-v2-" + result_ref["sha256"]
    evidence_specs = [("nfl-current-state-study-" + result_ref["sha256"], result_ref, "nfl-09",
                       "Current-state NFL reconstructed Development study", "complete_reconstructed_development_only",
                       {"result": result_ref, "evidenceClass": EVIDENCE_CLASS, "finalOotAccessed": False})]
    if publication_ref:
        evidence_specs.append(("nfl-current-state-publication-" + publication_ref["sha256"], publication_ref, "nfl-12",
                               "Current-state NFL precomputed research-shadow publication", "complete_research_shadow",
                               {"result": result_ref, "publication": publication_ref, "trainingEvidenceClass": EVIDENCE_CLASS,
                                "forecastCount": publication.get("forecastCount"), "wageringAuthority": False,
                                "executionAllowedInAISP": False}))
    inserted: list[str] = []
    with database.transaction() as connection:
        connection.execute("BEGIN IMMEDIATE")
        project = connection.execute("SELECT owner_user_id FROM projects WHERE project_id=?", (PROJECT_ID,)).fetchone()
        if project is None or not project["owner_user_id"]:
            raise CurrentStateRegistrationError("existing NFL project owner must be available")
        owner = project["owner_user_id"]
        if connection.execute("SELECT user_id FROM users WHERE user_id=?", (owner,)).fetchone() is None:
            raise CurrentStateRegistrationError("existing NFL project owner is not a registered local user")
        previous = connection.execute("SELECT project_id, artifacts_json FROM run_records WHERE run_id=?", (run_id,)).fetchone()
        if previous:
            if previous["project_id"] != PROJECT_ID or json.loads(previous["artifacts_json"]).get("result") != result_ref:
                raise CurrentStateRegistrationError("existing run identity conflicts; no historical record was changed")
        else:
            connection.execute("""INSERT INTO run_records
                (run_id,project_id,run_type,workflow_type,status,started_at,completed_at,
                 parameters_json,metrics_json,artifacts_json,error_json,created_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, PROJECT_ID, "nfl_current_state_reconstructed_study", "nfl-forecasting", "completed",
                 declaration.get("declaredAtUtc"), result["completedAtUtc"],
                 json_dumps({"evidenceClass": EVIDENCE_CLASS, "finalOotAccessed": False, "promotionStatus": "NOT_PROMOTED",
                             "wageringAuthority": False, "executionAllowedInAISP": False}),
                 json_dumps({key: result.get(key) for key in ("leaderboard", "pairedComparisons", "lag72Minus48", "actualFitAccounting", "lateCorrections")}),
                 json_dumps({"result": result_ref, "artifacts": result.get("artifacts", [])}), "{}", owner))
            inserted.append(run_id)
        timestamp = now_iso()
        for evidence_id, ref, step, title, status, payload in evidence_specs:
            previous = connection.execute("SELECT project_id,artifact_hash,source_ref FROM evidence_artifacts WHERE evidence_id=?", (evidence_id,)).fetchone()
            if previous:
                if (previous["project_id"], previous["artifact_hash"], previous["source_ref"]) != (PROJECT_ID, ref["sha256"], ref["path"]):
                    raise CurrentStateRegistrationError("existing evidence identity conflicts; no historical record was changed")
                continue
            connection.execute("""INSERT INTO evidence_artifacts
                (evidence_id,project_id,workflow_type,step_id,artifact_type,status,title,summary,
                 source_ref,artifact_hash,created_by,created_at,captured_at,approved_at,payload_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (evidence_id, PROJECT_ID, "nfl-forecasting", step, "research_evidence", status, title,
                 "Reconstructed Development is not observed historical vintage evidence. Forward observations remain separate; no promotion or wagering authority.",
                 ref["path"], ref["sha256"], owner, timestamp, timestamp, None, json_dumps(payload)))
            inserted.append(evidence_id)
    return {"status": "REGISTERED_RESEARCH_ONLY" if inserted else "NO_OP", "projectId": PROJECT_ID, "runId": run_id,
            "evidenceIds": [item[0] for item in evidence_specs], "insertedIds": inserted,
            "projectMetadataChanged": False, "workflowStateChanged": False, "championPointerChanged": False,
            "aispWrites": 0, "modelFits": 0}

"""Verify completed V19 evidence; default read-only plan, explicit --apply appends.

This is a narrow client of Model Studio's existing generic run/evidence schema.
It cannot update model, champion, workflow, project, AISP or existing evidence
records. The old regime-study contract and its discovery pointer are untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_datasets.consumer import canonical_json_bytes

STUDY_ROOT = ROOT / "outputs/mlb-v19-current-state-specialists-v1"
DATABASE = ROOT / ".runtime/asp-model-studio/persistence/asp_model_studio.db"
PROJECT_ID = "asp-mtlozhdx"
SCHEMA = "MLB_V19_STUDY_PUBLICATION_MANIFEST_V1"
VARIANTS = ("SEMANTIC_HGB", "SEMANTIC_EXTRA_TREES", "REGIME_HGB", "REGIME_CLUSTER_HGB")
ROWS = {1: 99780, 2: 100267, 3: 99926, 4: 100302, 5: 94157}
VERDICTS = {"MLB_V19_SPECIALIST_CHALLENGER_READY_FOR_PROSPECTIVE_SHADOW", "MLB_V19_GLOBAL_CHALLENGER_ONLY",
            "MLB_V18_RETAINED_AFTER_SPECIALIST_STUDY", "MLB_V19_STUDY_BLOCKED_ON_EVIDENCE"}
DELIVERABLES = {"feature_quality_audit", "ranked_source_gaps", "cold_start_specification", "failure_atlas",
                "cluster_analysis", "candidate_matrix", "matched_evaluation", "calibration_uncertainty",
                "executable_package", "game_simulation_comparison", "operational_readiness",
                "review_workbook", "recommendation"}


def json_text(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def require_completed_fields(value: dict) -> None:
    if (value.get("schemaVersion") != SCHEMA or value.get("projectId") != PROJECT_ID
            or value.get("status") != "COMPLETED" or value.get("verdict") not in VERDICTS
            or not value.get("studyId") or not value.get("startedAtUtc") or not value.get("completedAtUtc")):
        raise ValueError("Expected a completed, project-bound V19 publication manifest with final verdict")
    authority = value.get("authority", {})
    if (authority.get("status") != "RESEARCH_SHADOW" or authority.get("promotionStatus") != "NOT_PROMOTED"
            or authority.get("wageringAuthority") is not False or authority.get("executionAllowedInAISP") is not False
            or authority.get("finalOotAccessed") is not False):
        raise ValueError("Research-only authority and sealed Final OOT are required")
    if not DELIVERABLES.issubset(value.get("deliverables", {})):
        raise ValueError("Completed publication must reference all 13 reports/packages plus this checksum manifest")


def verify_manifest(path: Path) -> tuple[dict, dict, dict]:
    path = path.resolve()
    if not path.is_relative_to(STUDY_ROOT.resolve()):
        raise ValueError("V19 manifest is outside the isolated study output root")
    raw = path.read_bytes()
    value = json.loads(raw)
    require_completed_fields(value)
    manifest_ref = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "byteCount": len(raw)}
    verified = {}

    def check(ref: dict) -> Path:
        source = Path(ref["path"]).resolve()
        if not source.is_relative_to(STUDY_ROOT.resolve()):
            raise ValueError("Only isolated V19 publication artifacts may be registered")
        size = ref.get("byteCount", ref.get("bytes"))
        if not isinstance(size, int) or size < 1 or source.stat().st_size != size:
            raise ValueError("Artifact byte count differs or is absent")
        if source in verified:
            if verified[source] != (ref["sha256"], size):
                raise ValueError("Conflicting references for one immutable artifact")
            return source
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
        if digest.hexdigest() != ref["sha256"]:
            raise ValueError("Artifact checksum differs: " + str(source))
        verified[source] = (ref["sha256"], size)
        return source

    refs = value.get("files", [])
    if not isinstance(refs, list) or not refs:
        raise ValueError("A nonempty checksum/file list is required")
    by_path = {str(check(ref)): ref for ref in refs}
    for key in DELIVERABLES:
        delivered = check(value["deliverables"][key])
        if str(delivered) not in by_path:
            raise ValueError("A required deliverable is outside the manifest file list")
        if key == "review_workbook" and delivered.suffix.lower() != ".xlsx":
            raise ValueError("Editable review workbook must be an XLSX artifact")

    def listed_json(source: Path) -> dict:
        source = source.resolve()
        if str(source) not in by_path:
            raise ValueError("Mandatory completion receipt is not checksum-pinned by the final manifest: " + str(source))
        return json.loads(check(by_path[str(source)]).read_bytes())

    for number, rows in ROWS.items():
        complete = listed_json(STUDY_ROOT / f"folds/fold-{number}/complete.json")
        if complete.get("fold") != number or complete.get("globalFitsCompleted") != 4 or complete.get("validationRows") != rows:
            raise ValueError("All five matched global folds must be complete")
        artifacts = {Path(ref["path"]).name: ref for ref in complete["artifacts"]}
        for ref in artifacts.values():
            check(ref)
        for variant in VARIANTS:
            receipt = json.loads(check(artifacts[variant + "-verified.json"]).read_bytes())
            if (receipt.get("fold") != number or receipt.get("modelName") != variant
                    or receipt.get("modelReloadComparedRows") != rows or receipt.get("modelReloadMismatchCount") != 0
                    or receipt.get("fullPipelineReloadComparedRows") != 32 or receipt.get("fullPipelineReloadMismatchCount") != 0
                    or receipt.get("uncertaintyOnlyMeanInvariance") is not True or receipt.get("finalOotPayloadBytesRead") != 0):
                raise ValueError("Complete exact global/model/preprocessor reload verification required")
            for key in ("model", "predictions", "fixture"):
                check(receipt[key])
    package = listed_json(STUDY_ROOT / "evaluation/meta-study-package.json")
    if (package.get("matchedRows") != sum(ROWS.values()) or package.get("matchedGames") != 6570
            or package.get("finalOotPayloadBytesRead") != 0 or len(package.get("metaFoldCompletions", [])) != 5):
        raise ValueError("Completed matched meta evaluation is required")
    observed_folds = set()
    for ref in package["metaFoldCompletions"]:
        complete = json.loads(check(ref).read_bytes())
        number = complete.get("fold")
        if (number not in ROWS or number in observed_folds or complete.get("validationRows") != ROWS[number]
                or complete.get("fullFoldReloadComparedRows") != ROWS[number] or complete.get("reloadMismatchCount") != 0
                or complete.get("outcomeAndRealizedContextGateInvariance") is not True
                or complete.get("noFinalOotPayloadRead") is not True):
            raise ValueError("Meta fold exact reload and pregame routing verification required")
        observed_folds.add(number)
        for item in complete["artifacts"]:
            check(item)
    for ref in package["evaluationArtifacts"].values():
        check(ref)
    if {"raw", "calibrated", "actualSpecialistRouting", "incrementalClusterComparison", "developmentDecision"} - set(package["evaluationArtifacts"]):
        raise ValueError("Matched raw/calibrated, routing, cluster and final Development decision reports required")
    return value, manifest_ref, {"verifiedArtifacts": len(verified), "verifiedGlobalFits": 20,
                                "verifiedMetaFolds": 5, "matchedRows": sum(ROWS.values()), "matchedGames": 6570}


def append_registration(connection: sqlite3.Connection, manifest: dict, manifest_ref: dict, *, apply: bool = False) -> dict:
    """Use existing schema only; exact repeated identities are NO_OP, never updated."""
    require_completed_fields(manifest)
    connection.row_factory = sqlite3.Row
    if connection.execute("SELECT name FROM sqlite_master WHERE type=? AND tbl_name IN (?,?)",
                          ("trigger", "run_records", "evidence_artifacts")).fetchone():
        raise ValueError("Unexpected table trigger: no implicit mutation is authorized")
    owner = connection.execute("SELECT owner_user_id FROM projects WHERE project_id=?", (PROJECT_ID,)).fetchone()
    if not owner or not owner["owner_user_id"] or not connection.execute("SELECT 1 FROM users WHERE user_id=?", (owner["owner_user_id"],)).fetchone():
        raise ValueError("Existing MLB project and registered owner required; nothing will be created")
    digest = manifest_ref["sha256"]
    run_id, evidence_id = "mlb-v19-study-" + digest, "mlb-v19-evidence-" + digest
    run = {"run_id": run_id, "project_id": PROJECT_ID, "run_type": "mlb_v19_specialist_study",
           "workflow_type": "mlb-forecasting", "status": "completed", "started_at": manifest["startedAtUtc"],
           "completed_at": manifest["completedAtUtc"], "parameters_json": json_text({"studyId": manifest["studyId"], "authority": manifest["authority"]}),
           "metrics_json": json_text({"verdict": manifest["verdict"], "evidenceScope": "REUSED_DEVELOPMENT_RESEARCH_ONLY"}),
           "artifacts_json": json_text({"manifest": manifest_ref, "deliverables": manifest["deliverables"]}),
           "error_json": "{}", "created_by": owner["owner_user_id"]}
    evidence = {"evidence_id": evidence_id, "project_id": PROJECT_ID, "workflow_type": "mlb-forecasting", "step_id": "mlb-09",
                "artifact_type": "research_evidence", "status": "complete_development_only", "title": "MLB V19 global and specialist research study",
                "summary": "Development research only. V18 remains retained; no model, policy, workflow or promotion authority changed.",
                "source_ref": manifest_ref["path"], "artifact_hash": digest, "created_by": owner["owner_user_id"],
                "created_at": manifest["completedAtUtc"], "captured_at": manifest["completedAtUtc"], "approved_at": None,
                "payload_json": json_text({"manifest": manifest_ref, "verdict": manifest["verdict"], "authority": manifest["authority"]})}
    records = [("run_records", "run_id", run), ("evidence_artifacts", "evidence_id", evidence)]
    missing = []
    for table, id_column, record in records:
        existing = connection.execute(f"SELECT * FROM {table} WHERE {id_column}=?", (record[id_column],)).fetchone()
        if existing:
            if any(existing[key] != value for key, value in record.items()):
                raise ValueError("Existing V19 registration conflicts; no historical record was changed")
        else:
            missing.append((table, record))
    if apply:
        for table, record in missing:
            columns = list(record)
            connection.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", tuple(record[key] for key in columns))
    return {"status": ("REGISTERED_RESEARCH_ONLY" if apply else "READY_TO_REGISTER_RESEARCH_ONLY") if missing else "NO_OP",
            "projectId": PROJECT_ID, "runId": run_id, "evidenceId": evidence_id,
            "insertedIds": [record.get("run_id", record.get("evidence_id")) for _, record in missing] if apply else [],
            "proposedInsertCount": len(missing), "projectMetadataChanged": False, "workflowStateChanged": False,
            "championPointerChanged": False, "promotionChanged": False, "aispWrites": 0, "existingRowsUpdated": 0}


def _append_only_authorizer(action, table, column, database, trigger):
    if action == sqlite3.SQLITE_INSERT:
        return sqlite3.SQLITE_OK if table in {"run_records", "evidence_artifacts"} and trigger is None else sqlite3.SQLITE_DENY
    denied = {sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH,
              sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE,
              sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_DROP_TRIGGER}
    return sqlite3.SQLITE_DENY if action in denied else sqlite3.SQLITE_OK


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    manifest, ref, verification = verify_manifest(args.manifest)
    if not DATABASE.is_file():
        raise ValueError("Existing Model Studio database missing; no database creation authorized")
    connection = sqlite3.connect(DATABASE.resolve().as_uri() + ("?mode=rw" if args.apply else "?mode=ro"), uri=True, timeout=30)
    connection.set_authorizer(_append_only_authorizer)
    try:
        if args.apply:
            connection.execute("BEGIN IMMEDIATE")
        receipt = append_registration(connection, manifest, ref, apply=args.apply)
        if args.apply:
            connection.commit()
    except Exception:
        if args.apply:
            connection.rollback()
        raise
    finally:
        connection.close()
    print(json.dumps({**receipt, "manifest": ref, "verification": verification, "dryRun": not args.apply}, indent=2))


if __name__ == "__main__":
    main()

"""Exact, reference-only V18 exception authorized by James; not a generic promotion gate.

Artifact lineage can be verified while historical selection integrity is under
review. Neither a clean holdout nor new fitted parameters are asserted here.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ..persistence.db import decode_row
from ..persistence.repositories.model_registry_repository import (
    ModelRegistryConflictError, _insert_model_row, _insert_version_row,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/mlb-v18-conditional-champion-v1"
PROJECT = "asp-mtlozhdx"
MODEL = "model-mlb-v18-conditional-operational-champion-v1"
FORMAT = "mlb_v18_frozen_reference_v1"
STATUS = "conditional_operational_champion"
DECISION_SHA = "63db5695f6cc854ba8d4a8dfbb0acc93a6a786cdf9ae838b2235ff4efa85ccff"
PA_SHA = "44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b"
FLAGS = (STATUS, "prospective_authority", "historical_validation_under_review",
         "final_oot_sealed", "no_retroactive_forecasts", "no_real_money_wagering")


def descriptor(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def verify_reference(ref):
    path = Path(ref["path"]).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Conditional champion reference must remain inside Model Studio.")
    actual = descriptor(path)
    if actual["sha256"] != ref["sha256"] or actual["bytes"] != ref["bytes"]:
        raise ValueError("Conditional champion reference checksum/byte-count mismatch: " + str(path))
    return actual


def verify_manifest(path, digest, *, deserialize=False):
    path = Path(path).resolve()
    if not path.is_relative_to(OUT / "champion/sha256") or path.parent.name != digest:
        raise ValueError("Not a content-addressed V18 champion manifest.")
    ref = descriptor(path)
    if ref["sha256"] != digest:
        raise ValueError("Champion manifest digest mismatch.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (value.get("schemaVersion") != "MLB_V18_CONDITIONAL_CHAMPION_V1"
            or value.get("projectId") != PROJECT
            or value.get("authorization", {}).get("requestSha256") != DECISION_SHA
            or value.get("paArtifact", {}).get("sha256") != PA_SHA
            or value.get("status") != STATUS
            or any(value.get("authority", {}).get(flag) is not True for flag in FLAGS)
            or value.get("realMoneyExecutionAllowed") is not False):
        raise ValueError("Not the exact authorized conditional frozen V18 decision.")
    for asset in value["artifactReferences"]:
        verify_reference(asset)
    verify_reference(value["paArtifact"])
    result = {"checksum": digest, "sizeBytes": ref["bytes"], "manifest": value,
              "status": STATUS, "historicalValidation": "historical_validation_under_review"}
    if deserialize:
        from ..sports_current_statcast.stage3_corrected_preprocessing_artifacts import load_research_pipeline
        pa = value["paArtifact"]
        result["object"] = load_research_pipeline(
            {"relativePath": pa["relativePath"], "sha256": PA_SHA}, root=Path(pa["root"]))
    return result


def verify_record(service, record, *, deserialize=False):
    parent = service.models.get(MODEL)
    if (record.get("model_id") != MODEL or record.get("project_id") != PROJECT
            or record.get("archived_at") or record.get("quarantine_reason") or record.get("quarantined_at")
            or record.get("artifact_format") != FORMAT
            or record.get("publication_status") != "finalized"
            or record.get("lineage_status") != "verified"
            or record.get("approval_status") != STATUS
            or record.get("validation_status") != "historical_validation_under_review"
            or not parent or parent.get("archived") or parent.get("project_id") != PROJECT
            or parent.get("status") != STATUS):
        raise ValueError("Conditional champion registry identity/lifecycle mismatch.")
    checked = verify_manifest(record["artifact_reference"], record["checksum"], deserialize=deserialize)
    if checked["sizeBytes"] != record["artifact_size_bytes"]:
        raise ValueError("Conditional registry manifest byte count mismatch.")
    return checked


def register_authorized(service, user, path, digest):
    """Called only AFTER project edit authorization by model_registry_service."""
    checked = verify_manifest(path, digest)
    value = checked["manifest"]
    now = datetime.now(timezone.utc).isoformat()
    version_id = "mv-mlb-v18-conditional-" + digest[:24]
    model = {"model_id": MODEL, "project_id": PROJECT, "name": "MLB_V18_HGB_PA",
             "problem_type": "multiclass_classification", "status": STATUS,
             "owner_user_id": user["userId"], "created_at": now,
             "tags_json": list(FLAGS), "description": value["historicalIntegrityLimitation"]}
    training = value["trainingIdentity"]
    version = {
        "model_version_id": version_id, "model_id": MODEL, "project_id": PROJECT,
        "version_number": 18, "training_run_id": training.get("trainingRunId"),
        "dataset_id": training.get("datasetId"), "dataset_version_id": training.get("datasetVersionId"),
        "feature_manifest_version": value["featureContract"]["manifestSha256"],
        "algorithm": "HistGradientBoostingClassifier", "algorithm_version": "frozen_V18",
        "training_timestamp": training.get("originalTrainingTimestamp"),
        "training_parameters_json": training, "artifact_reference": str(Path(path).resolve()),
        "artifact_format": FORMAT, "checksum": digest, "artifact_size_bytes": checked["sizeBytes"],
        "publication_status": "finalized", "artifact_verified_at": now, "finalized_at": now,
        "idempotency_key": digest, "publication_fingerprint": digest, "lineage_status": "verified",
        "selection_integrity_status": "historical_validation_under_review",
        "final_holdout_status": "sealed_unread", "holdout_isolation_status": "final_oot_sealed",
        "promotion_readiness_status": STATUS, "target_name": value["targetContract"]["targetName"],
        "approval_status": STATUS, "validation_status": "historical_validation_under_review",
        "documentation_status": "documented", "model_contract_json": value,
        "evaluation_summary_json": {"historicalValidation": "under_review", "cleanFiveFoldClaim": False},
        "lineage_json": {"authority": value["authority"], "authorization": value["authorization"],
                         "artifactLineageMeaning": "bytes_and_frozen_identity_only_not_validation_integrity",
                         "predecessor": value["predecessor"]},
        "created_at": now, "created_by": user["userId"],
    }
    with service.database.transaction() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = decode_row(connection.execute("SELECT * FROM models WHERE model_id=?", (MODEL,)).fetchone())
        if existing:
            row = decode_row(connection.execute("SELECT * FROM model_versions WHERE model_version_id=?", (version_id,)).fetchone())
            if (not row or row["checksum"] != digest or existing["project_id"] != PROJECT
                    or existing["status"] != STATUS or existing["archived"]
                    or existing["current_version_id"] != version_id
                    or row.get("model_id") != MODEL or row.get("project_id") != PROJECT
                    or row.get("artifact_format") != FORMAT or row.get("artifact_reference") != version["artifact_reference"]
                    or row.get("artifact_size_bytes") != checked["sizeBytes"]
                    or row.get("archived_at") or row.get("quarantine_reason") or row.get("quarantined_at")
                    or row.get("publication_status") != "finalized" or row.get("lineage_status") != "verified"
                    or row.get("approval_status") != STATUS
                    or row.get("validation_status") != "historical_validation_under_review"):
                raise ModelRegistryConflictError("Conditional champion already exists with different lineage/pointer; no overwrite.")
            return {"modelId": MODEL, "modelVersionId": version_id, "sha256": digest, "operation": "EXACT_REUSE"}
        # Fail rather than displace another MLB champion that appeared concurrently.
        conflict = connection.execute("SELECT model_id FROM models WHERE project_id=? AND current_version_id IS NOT NULL AND archived=0", (PROJECT,)).fetchone()
        if conflict:
            raise ModelRegistryConflictError("Another current MLB registry pointer exists; explicit reconciliation required.")
        _insert_model_row(connection, model)
        _insert_version_row(connection, version)
        connection.execute("UPDATE models SET current_version_id=?,current_version_generation=1,champion_updated_at=?,champion_updated_by=? WHERE model_id=? AND current_version_id IS NULL", (version_id, now, user["userId"], MODEL))
    return {"modelId": MODEL, "modelVersionId": version_id, "sha256": digest, "operation": "REGISTERED_CONDITIONAL_CHAMPION"}


def prospective_decision_eligibility(*, effective_at, decision_at, event_id, first_pitch,
                                     forecast=None, quote_eligible=False, existing_policy_eligible=False,
                                     adjusted_edge=None, already_decided=False):
    """Portable handoff guard; does not award readiness, calculate stakes or write AISP."""
    def instant(value):
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("Explicit timezone required.")
        return parsed
    if already_decided:
        return "HISTORICAL_DECISION_IMMUTABLE"
    try:
        boundary, decision, start = map(instant, (effective_at, decision_at, first_pitch))
        if decision < boundary:
            return "GEN1_ERA_NO_RECOMPUTATION"
        if decision >= start:
            return "EVENT_ALREADY_STARTED"
        if not forecast:
            return "V18_FORECAST_MISSING_NO_GEN1_FALLBACK"
        if forecast.get("modelName") != "MLB_V18_HGB_PA" or forecast.get("paArtifactSha256") != PA_SHA:
            return "WRONG_MODEL_OR_ARTIFACT"
        if forecast.get("eventId") != event_id:
            return "EVENT_IDENTITY_MISMATCH"
        created, evidence = map(instant, (forecast["forecastCreatedAt"], forecast["evidenceCutoffAt"]))
        if not evidence <= created <= decision < start:
            return "INVALID_PREGAME_TEMPORAL_ORDER"
    except (ValueError, KeyError, TypeError):
        return "MISSING_OR_INVALID_TEMPORAL_EVIDENCE"
    if not quote_eligible or not existing_policy_eligible:
        return "EXISTING_QUOTE_READINESS_CUTOFF_OR_STAKE_RULE_NOT_MET"
    if adjusted_edge is None or not 0.02 <= adjusted_edge <= 1:
        return "EXISTING_2_PERCENT_ADJUSTED_EDGE_NOT_MET"
    return "ELIGIBLE_FOR_VIRTUAL_POLICY_EVALUATION_ONLY"

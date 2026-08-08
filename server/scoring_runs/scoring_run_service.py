"""ATLAS Persistent Scoring Runs -- domain service.

This is the ONLY place a ScoringRun row is created, read, listed, cancelled,
or archived. Every entry point re-authorizes via authorize_modeling_scope,
exactly like every other ATLAS modeling endpoint -- a scoring run's
projectId is never trusted as its own authorization signal.

Execution today is synchronous (eval_service.score_dataset runs inline within
the HTTP request, same as before this phase -- Predictive Modeling pages are
explicitly out of scope for redesign). A ScoringRun is therefore created
already in a terminal state ("completed" or "failed"); the "running"/"queued"
statuses and the cancel endpoint exist for contract completeness and forward
compatibility with a future async scoring pipeline, not because today's
scoring can actually be interrupted mid-flight -- this is disclosed, not
hidden, in the final report and in QUERY_PLANNER-style docs.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import HTTPException

from ..core.modeling_scope import authorize_modeling_scope
from ..core.result_store import RESULTS
from ..persistence.db import now_iso
from ..persistence.service import get_persistence_service
from .scoring_run_artifacts import read_scoring_run_rows, write_scoring_run_parquet

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def new_scoring_run_id() -> str:
    return f"sr-{uuid.uuid4().hex[:16]}"


def _camel(key: str) -> str:
    import re

    return re.sub(r"_([a-z0-9])", lambda match: match.group(1).upper(), key)


def _to_api(record: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in record.items():
        output_key = key[:-5] if key.endswith("_json") else key
        result[_camel(output_key)] = value
    return result


def create_scoring_run(
    user: Dict[str, Any],
    project_id: str,
    partition: str,
    score_result: Dict[str, Any],
    dataset_context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Persists one completed (or failed) scoring execution as a durable
    ScoringRun. Called additively from eval_router.py's /score/upload and
    /score/development-split AFTER the existing score_dataset() call succeeds
    -- the existing response shape and behavior are unchanged; this only adds
    a `scoringRunId` field and a durable side effect. Returns None (rather
    than raising) on any persistence failure, so a durability bug can never
    break the underlying scoring feature that already worked before this
    phase (Do-Not #7: "Do not remove existing scoring behavior")."""
    if not score_result.get("ok"):
        return None
    try:
        authorize_modeling_scope(user, project_id, "edit")

        scored_records = score_result.get("scored_rows") or []
        scored_columns = score_result.get("scored_columns") or []
        frame = (
            pd.DataFrame.from_records(scored_records)
            if scored_records
            else pd.DataFrame(columns=scored_columns)
        )

        scoring_run_id = new_scoring_run_id()
        artifact = write_scoring_run_parquet(scoring_run_id, frame)

        context = dataset_context or {}
        model_meta = score_result.get("model") or {}
        model_id = str(model_meta.get("model_key") or model_meta.get("name") or "final")
        model_version = str(RESULTS.training_timestamp or "unversioned")
        # Durable Model Registry, Phase F: model_meta IS RESULTS.final_model_metadata
        # (that's exactly what _resolve_scoring_model returns for the default
        # model="final"/"final_rfe" scoring path) -- once Save Final Model has run
        # through the registry (eval_router.py's _register_model_version), that
        # metadata dict carries real registry identities. Falls back to the
        # synthesized model_id/model_version above when no registry link exists yet
        # (e.g. a project scored before this phase, or scoring a named non-final
        # artifact that was never saved through the registry) -- never invents one.
        registry_model_id = model_meta.get("modelId")
        registry_model_version_id = model_meta.get("modelVersionId")
        training_dataset_id = (
            context.get("datasetId")
            or model_meta.get("training_dataset_id")
            or model_meta.get("trainingDatasetId")
            or model_meta.get("dataset_id")
            or model_meta.get("datasetId")
        )
        training_dataset_version_id = (
            context.get("datasetVersionId")
            or model_meta.get("training_dataset_version_id")
            or model_meta.get("trainingDatasetVersionId")
            or model_meta.get("dataset_version_id")
            or model_meta.get("datasetVersionId")
        )
        scoring_target = (
            score_result.get("target_column")
            or model_meta.get("target_name")
            or model_meta.get("targetName")
            or model_meta.get("target")
        )

        task = score_result.get("task")
        problem_type = "regression" if task == "regression" else ("classification" if task else None)
        prediction_column = "predicted_value" if task == "regression" else "prediction"
        probability_column = None if task == "regression" else "adjusted_score"
        residual_column = "atlas_residual" if task == "regression" else None

        timestamp = now_iso()
        record = {
            "scoring_run_id": scoring_run_id,
            "project_id": project_id,
            "user_id": str(user.get("userId") or ""),
            "dataset_id": training_dataset_id,
            "dataset_version_id": training_dataset_version_id,
            "dataset_identity": score_result.get("dataset_identity") or context.get("datasetIdentity"),
            "partition": str(partition or "test").lower(),
            # model_id keeps its existing display-friendly-algorithm-key semantics
            # (e.g. "logreg") -- unchanged, so existing filtering/display never breaks.
            # model_version_id is the REAL identity reference this phase adds; the
            # durable Model itself is always reachable by resolving model_versions.model_id
            # from it, never by trusting this text column as a registry key.
            "model_id": model_id,
            "model_version": model_version,
            "model_version_id": registry_model_version_id,
            "feature_manifest_version": context.get("featureManifestVersion") or model_meta.get("feature_manifest_version"),
            "problem_type": problem_type,
            "target": scoring_target,
            "status": "completed",
            "created_at": timestamp,
            "completed_at": timestamp,
            "started_by": str(user.get("userId") or ""),
            "execution_engine": "pandas",
            "query_version": "1.0",
            "row_count": int(score_result.get("rows") or len(frame)),
            "prediction_column": prediction_column,
            "probability_column": probability_column,
            "residual_column": residual_column,
            "output_artifact_id": scoring_run_id,
            "output_artifact_path": artifact["path"],
            "output_artifact_format": "parquet",
            "metrics_json": {
                "metrics": score_result.get("metrics"),
                "scoreSummary": score_result.get("score_summary"),
                "adjustedScoreSummary": score_result.get("adjusted_score_summary"),
                "lift": score_result.get("lift"),
            },
            "diagnostics_json": score_result.get("scoring_diagnostics") or {},
            "psi_json": score_result.get("psi") or {},
            "vsi_json": {"rows": score_result.get("vsi") or [], "scope": score_result.get("vsi_scope")},
            "evidence_links_json": [],
            "documentation_links_json": [],
            "lineage_json": {
                "modelSource": "RESULTS.final_model" if model_id in ("final", "final_rfe") else f"artifact:{model_id}",
                "datasetSource": context.get("source") or "upload",
                "trainingTimestamp": RESULTS.training_timestamp,
                "correctionMethod": (score_result.get("probability_correction") or {}).get("method"),
            },
            "retention_policy": "standard",
            "archived_at": None,
            "checksum": artifact["checksum"],
            "error_message": None,
            "updated_at": timestamp,
        }
        service = get_persistence_service()
        saved = service.scoring_runs.upsert(record)
        _record_evidence(service, project_id, user, saved)
        return _to_api(saved)
    except Exception:  # noqa: BLE001 -- durability is additive, never fatal to scoring itself
        return None


def create_failed_scoring_run(
    user: Dict[str, Any],
    project_id: str,
    partition: str,
    error_message: str,
    dataset_context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Phase O/J: a scoring attempt that failed (score_result.get('ok') is False)
    previously vanished entirely -- the user saw a one-time error toast and no
    durable record existed to inspect later. This persists a minimal ScoringRun
    row (status="failed", no output artifact, honest error_message) so failed
    runs remain inspectable in history, matching "Failed runs remain inspectable
    with an honest failure reason." Best-effort, like create_scoring_run -- a
    persistence bug here must never mask or replace the original error response
    the caller already returns to the user."""
    try:
        authorize_modeling_scope(user, project_id, "edit")
        scoring_run_id = new_scoring_run_id()
        timestamp = now_iso()
        context = dataset_context or {}
        record = {
            "scoring_run_id": scoring_run_id,
            "project_id": project_id,
            "user_id": str(user.get("userId") or ""),
            "dataset_id": context.get("datasetId"),
            "dataset_version_id": context.get("datasetVersionId"),
            "dataset_identity": context.get("datasetIdentity"),
            "partition": str(partition or "test").lower(),
            "model_id": None,
            "model_version": str(RESULTS.training_timestamp or "unversioned"),
            "feature_manifest_version": context.get("featureManifestVersion"),
            "problem_type": None,
            "target": None,
            "status": "failed",
            "created_at": timestamp,
            "completed_at": timestamp,
            "started_by": str(user.get("userId") or ""),
            "execution_engine": None,
            "query_version": "1.0",
            "row_count": None,
            "prediction_column": None,
            "probability_column": None,
            "residual_column": None,
            "output_artifact_id": None,
            "output_artifact_path": None,
            "output_artifact_format": None,
            "metrics_json": {},
            "diagnostics_json": {},
            "psi_json": {},
            "vsi_json": {},
            "evidence_links_json": [],
            "documentation_links_json": [],
            "lineage_json": {"datasetSource": context.get("source") or "upload"},
            "retention_policy": "standard",
            "archived_at": None,
            "checksum": None,
            "error_message": str(error_message or "Scoring failed for an unspecified reason."),
            "updated_at": timestamp,
        }
        service = get_persistence_service()
        saved = service.scoring_runs.upsert(record)
        return _to_api(saved)
    except Exception:  # noqa: BLE001 -- durability is additive, never fatal to the caller's error response
        return None


def _record_evidence(service, project_id: str, user: Dict[str, Any], scoring_run: Dict[str, Any]) -> None:
    """Phase H: every scoring run is referenceable from Evidence. Best-effort
    -- an evidence-write failure must never surface as a scoring failure."""
    try:
        metrics = scoring_run.get("metrics_json") or {}
        service.evidence.upsert(
            {
                "evidence_id": f"ev-scoring-{scoring_run['scoring_run_id']}",
                "project_id": project_id,
                "workflow_type": "predictive-modeling",
                "step_id": "scoring",
                "artifact_type": "scoring-run",
                "status": "captured",
                "title": f"Scoring Run -- {str(scoring_run.get('partition') or '').upper()} -- {scoring_run.get('model_id')}",
                "summary": f"{scoring_run.get('row_count')} rows scored against model '{scoring_run.get('model_id')}'.",
                "source_ref": scoring_run["scoring_run_id"],
                "artifact_hash": scoring_run.get("checksum"),
                "created_by": str(user.get("userId") or ""),
                "payload_json": {
                    "scoringRunId": scoring_run["scoring_run_id"],
                    "partition": scoring_run.get("partition"),
                    "modelId": scoring_run.get("model_id"),
                    # Durable Model Registry, Phase H: real registry identities, not
                    # inferred values -- None when this run predates the registry or
                    # scored a non-final named artifact never saved through it.
                    "modelVersionId": scoring_run.get("model_version_id"),
                    "datasetVersionId": scoring_run.get("dataset_version_id"),
                    "featureManifestVersion": scoring_run.get("feature_manifest_version"),
                    "rowCount": scoring_run.get("row_count"),
                    "metrics": metrics.get("metrics"),
                },
            }
        )
    except Exception:  # noqa: BLE001
        pass


def list_scoring_runs(user: Dict[str, Any], project_id: str, **filters: Any) -> List[Dict[str, Any]]:
    authorize_modeling_scope(user, project_id, "view")
    service = get_persistence_service()
    rows = service.scoring_runs.list(project_id=project_id, **filters)
    return [_to_api(row) for row in rows]


def _get_authorized(user: Dict[str, Any], scoring_run_id: str) -> Dict[str, Any]:
    service = get_persistence_service()
    row = service.scoring_runs.get(scoring_run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Scoring run not found.")
    if row.get("project_id"):
        authorize_modeling_scope(user, row["project_id"], "view")
    return row


def get_scoring_run(user: Dict[str, Any], scoring_run_id: str) -> Dict[str, Any]:
    return _to_api(_get_authorized(user, scoring_run_id))


def get_scoring_run_metrics(user: Dict[str, Any], scoring_run_id: str) -> Dict[str, Any]:
    row = _get_authorized(user, scoring_run_id)
    return {
        "scoringRunId": row["scoring_run_id"],
        "metrics": row.get("metrics_json") or {},
    }


def get_scoring_run_diagnostics(user: Dict[str, Any], scoring_run_id: str) -> Dict[str, Any]:
    row = _get_authorized(user, scoring_run_id)
    return {
        "scoringRunId": row["scoring_run_id"],
        "scoringDiagnostics": row.get("diagnostics_json") or {},
        "psi": row.get("psi_json") or {},
        "vsi": row.get("vsi_json") or {},
    }


def get_scoring_run_summary(user: Dict[str, Any], scoring_run_id: str) -> Dict[str, Any]:
    row = _get_authorized(user, scoring_run_id)
    api = _to_api(row)
    return {
        **api,
        "evidenceId": f"ev-scoring-{row['scoring_run_id']}",
        # Phase K: a ScoringRun is distinct from a registered Scored Dataset, but now
        # cross-linked via register_scored_dataset() (server/scoring/scoring_router.py)
        # when a user explicitly registers this run's output -- reads the real column,
        # not a hardcoded constant.
        "registrationStatus": row.get("registration_status") or "not_registered",
    }


def get_scoring_run_lineage(user: Dict[str, Any], scoring_run_id: str) -> Dict[str, Any]:
    row = _get_authorized(user, scoring_run_id)
    return {
        "scoringRunId": row["scoring_run_id"],
        "lineage": row.get("lineage_json") or {},
        "datasetId": row.get("dataset_id"),
        "datasetVersionId": row.get("dataset_version_id"),
        "datasetIdentity": row.get("dataset_identity"),
        "modelId": row.get("model_id"),
        "modelVersion": row.get("model_version"),
        "featureManifestVersion": row.get("feature_manifest_version"),
        "checksum": row.get("checksum"),
    }


def get_scoring_run_rows(user: Dict[str, Any], scoring_run_id: str, limit: int = 100) -> Dict[str, Any]:
    row = _get_authorized(user, scoring_run_id)
    path = row.get("output_artifact_path")
    if not path:
        raise HTTPException(status_code=409, detail="This scoring run has no output artifact.")
    bounded_limit = max(1, min(int(limit or 100), 5000))
    try:
        payload = read_scoring_run_rows(path, limit=bounded_limit)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"scoringRunId": scoring_run_id, **payload}


def cancel_scoring_run(user: Dict[str, Any], scoring_run_id: str) -> Dict[str, Any]:
    row = _get_authorized(user, scoring_run_id)
    if row.get("status") in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Scoring run is already '{row.get('status')}' -- scoring executes synchronously today, so it "
            "cannot be cancelled mid-flight; this endpoint only rejects an already-terminal run rather than "
            "silently pretending to cancel it.",
        )
    service = get_persistence_service()
    timestamp = now_iso()
    row["status"] = "cancelled"
    row["completed_at"] = timestamp
    row["updated_at"] = timestamp
    saved = service.scoring_runs.upsert(row)
    return _to_api(saved)


def archive_scoring_run(user: Dict[str, Any], scoring_run_id: str) -> Dict[str, Any]:
    row = _get_authorized(user, scoring_run_id)
    service = get_persistence_service()
    timestamp = now_iso()
    row["archived_at"] = timestamp
    row["updated_at"] = timestamp
    saved = service.scoring_runs.upsert(row)
    return _to_api(saved)


def compare_scoring_runs(user: Dict[str, Any], scoring_run_ids: List[str]) -> Dict[str, Any]:
    if len(scoring_run_ids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least two scoringRunIds to compare.")
    if len(scoring_run_ids) > 10:
        raise HTTPException(status_code=400, detail="Cannot compare more than 10 scoring runs at once.")
    rows = [_get_authorized(user, run_id) for run_id in scoring_run_ids]
    return {
        "runs": [
            {
                "scoringRunId": row["scoring_run_id"],
                "partition": row.get("partition"),
                "modelId": row.get("model_id"),
                "modelVersion": row.get("model_version"),
                "createdAt": row.get("created_at"),
                "rowCount": row.get("row_count"),
                "metrics": (row.get("metrics_json") or {}).get("metrics"),
                "psi": row.get("psi_json"),
            }
            for row in rows
        ]
    }


def archive_scoring_runs_for_project(project_id: str) -> int:
    """Project-deletion lifecycle hook (Phase I) -- called from
    persistence_router.delete_project. Archives (does not delete) every
    scoring run belonging to the project, matching the Dataset Library's
    survive-but-unlink precedent."""
    service = get_persistence_service()
    return service.scoring_runs.archive_for_project(project_id)

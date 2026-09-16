"""Register an immutable NFL Development laboratory result in Model Studio.

This adapter writes only research project, run, evidence, export, and unpromoted
model-version records.  It never advances a champion pointer.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from server.persistence.db import Database, json_dumps, now_iso
from server.persistence.service import PersistenceService
from server.sharing.sharing_service import SharingService


PROJECT_ID = "sports-project-nfl-overnight-model-lab-v1"
MODEL_ID = "model-nfl-overnight-research-finalist-v1"
DEFAULT_DATABASE_PATH = Path(r".runtime\asp-model-studio\persistence\asp_model_studio.db")


class NflLabRegistrationError(RuntimeError):
    """The research-only workflow receipt could not be registered exactly."""


def _load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise NflLabRegistrationError(f"expected JSON object: {path}")
    return value


def register_overnight_lab(
    analysis: Mapping[str, Any],
    *,
    manifest_sha256: str,
    handoff_path: str,
    handoff_sha256: str,
    database_path: Path = DEFAULT_DATABASE_PATH,
    user_id: str = "user_20e0f4e20ec9434c",
) -> dict[str, Any]:
    if analysis.get("finalOotAccessed") is not False:
        raise NflLabRegistrationError("sealed Final OOT disposition differs")
    if analysis.get("status") != "RESEARCH_SHADOW" or analysis.get("promotionStatus") != "NOT_PROMOTED":
        raise NflLabRegistrationError("only the unpromoted research result can be registered")
    database = Database(Path(database_path).resolve())
    service = PersistenceService(database)
    foundation_sha = str(analysis["foundationBundleSha256"])
    with database.connection() as connection:
        registration = connection.execute(
            "SELECT registration_id, dataset_version_id FROM sports_dataset_registrations WHERE manifest_sha = ? AND league = 'NFL'",
            (foundation_sha,),
        ).fetchone()
        user = connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if registration is None:
        raise NflLabRegistrationError("the exact NFL foundation is not registered in Model Studio")
    if user is None:
        raise NflLabRegistrationError("the configured local Model Studio owner is unavailable")
    timestamp = now_iso()
    user_context = {"userId": user_id, "role": "admin"}
    sports_metadata = {
        "projectId": PROJECT_ID, "sport": "Professional Football", "league": "NFL",
        "sportCode": "FOOTBALL", "leagueCode": "NFL",
        "workflowCode": "NFL_GAME_FORECAST_WORKFLOW_V1", "workflowAvailability": "RESEARCH_ONLY",
        "evidenceStatus": "RESEARCH_ONLY", "period": "1999–2024 Development",
        "workflowId": "nfl-forecasting", "lifecycle": "RESEARCH_SHADOW",
        "primaryTarget": "Home / Away / Tie Probability",
        "secondaryTargets": ["Home Score", "Away Score", "Margin", "Total"],
        "researchPurpose": "Compare bounded NFL score-model families and treatments under chronological validation.",
        "description": "Development-only NFL model laboratory; 2025 Final OOT remains sealed.",
    }
    existing_project = service.projects.get(PROJECT_ID)
    service.projects.upsert({
        "project_id": PROJECT_ID, "project_name": "NFL Overnight Model Laboratory",
        "project_type": "custom-workflow", "workflow_type": "nfl-forecasting",
        "template_id": "nfl-game-forecast-workflow-v1", "status": "active",
        "owner_user_id": user_id, "created_by": user_id, "updated_by": user_id,
        "metadata_json": {
            "sportsProject": sports_metadata, "modelId": MODEL_ID,
            "projectTools": {"experimentsEnabled": True, "decisionJournalEnabled": True,
                             "governanceEnabled": True, "notebookExportEnabled": False},
            "laboratoryManifestSha256": manifest_sha256,
        },
    })
    if existing_project is None:
        SharingService(service)._bootstrap_project_owner(user_context, PROJECT_ID)
    completed_steps = ["nfl-01", "nfl-02", "nfl-03", "nfl-08", "nfl-09", "nfl-10"]
    service.projects.upsert_workflow_state(PROJECT_ID, {
        "current_step_id": "nfl-04", "completed_steps_json": completed_steps,
        "workflow_status_json": {
            "status": "in_progress", "steps": {f"nfl-{number:02d}": (
                "complete" if f"nfl-{number:02d}" in completed_steps else "pending"
            ) for number in range(1, 13)},
            "researchOnly": True, "promotionStatus": "NOT_PROMOTED",
        },
        "step_evidence_status_json": {
            "nfl-08": "COMPLETE_DEVELOPMENT_EVIDENCE", "nfl-09": "COMPLETE_DEVELOPMENT_OOF",
            "nfl-10": "COMPLETE_DEVELOPMENT_CALIBRATION",
            "nfl-11": "NOT_PROMOTED", "nfl-12": "NOT_CONFIGURED",
        },
        "completed_by": user_id,
    })
    workflow_evidence = {
        "objective_forecast_contract": {"status": "COMPLETE", "evidence": "Home/away/tie and score targets frozen."},
        "data_evidence_manifest": {"status": "COMPLETE", "evidence": foundation_sha},
        "identity_coverage_leakage": {"status": "COMPLETE", "evidence": "Game-atomic chronological folds; 2025 unread."},
        "player_team_state": {"status": "PARTIAL_BASELINE", "evidence": "Registered 197-input long-history contract."},
        "participation_usage": {"status": "NOT_CONFIGURED"},
        "event_models": {"status": "NOT_APPLICABLE_SCORE_MODEL_LAB"},
        "game_simulation": {"status": "COMPLETE_BASELINE", "evidence": "Training-only paired residual score adapter."},
        "candidate_models_experiments": {"status": "COMPLETE_DEVELOPMENT_EVIDENCE", "manifestSha256": manifest_sha256},
        "temporal_validation": {"status": "COMPLETE_DEVELOPMENT_OOF", "evidence": "Five expanding folds, 2020–2024."},
        "calibration_reliability": {"status": "COMPLETE_DEVELOPMENT_EVIDENCE"},
        "model_graph_decision": {"status": "M1_RECIPE_RETAINED", "candidate": analysis["developmentSelectedPipeline"]},
        "export_to_asp": {"status": "NOT_CONFIGURED", "reason": "RESEARCH_ONLY_NOT_PROMOTED"},
    }
    with database.transaction() as connection:
        existing = connection.execute(
            "SELECT created_at, created_by FROM sports_research_projects WHERE project_id = ?", (PROJECT_ID,)
        ).fetchone()
        connection.execute(
            """
            INSERT INTO sports_research_projects (
              project_id, registration_id, project_name, sport, league, development_period,
              prior_history, forecast_lifecycle, primary_target, secondary_targets_json,
              baseline_population, upper_bound_population, research_purpose, workflow_evidence_json,
              created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
              workflow_evidence_json=excluded.workflow_evidence_json, updated_at=excluded.updated_at
            """,
            (PROJECT_ID, registration["registration_id"], "NFL Overnight Model Laboratory",
             "Professional Football", "NFL", "1999–2024", "Long-history pregame features",
             "Development OOF / research shadow", "Home / Away / Tie Probability",
             json_dumps(["Home Score", "Away Score", "Margin", "Total"], []),
             "Registered 197-input baseline", "F1/F2 bounded research variants",
             sports_metadata["researchPurpose"], json_dumps(workflow_evidence, {}),
             existing["created_by"] if existing else user_id,
             existing["created_at"] if existing else timestamp, timestamp),
        )
    run_id = f"nfl-overnight-{manifest_sha256[:20]}"
    service.runs.upsert({
        "run_id": run_id, "project_id": PROJECT_ID, "run_type": "nfl_model_laboratory",
        "workflow_type": "nfl-forecasting", "status": "completed",
        "started_at": analysis["pipelines"][0].get("startedAt") or timestamp,
        "completed_at": analysis["completedAt"],
        "parameters_json": {"matrixSha256": analysis["matrixSha256"], "finalOotAccessed": False},
        "metrics_json": {"leaderboard": analysis["leaderboard"], "pairedUncertaintyVersusM1": analysis["pairedUncertaintyVersusM1"]},
        "artifacts_json": {"handoffPath": handoff_path, "handoffSha256": handoff_sha256,
                           "manifestSha256": manifest_sha256, "reportPath": analysis["reportPath"]},
        "created_by": user_id,
    })
    model_version_id = f"model-version-nfl-{manifest_sha256[:20]}"
    existing_model = service.models.get(MODEL_ID)
    if existing_model and existing_model.get("current_version_id") is not None:
        raise NflLabRegistrationError("research model already has a champion pointer; registration stopped")
    service.models.upsert({
        "model_id": MODEL_ID, "project_id": PROJECT_ID, "name": "NFL Development Research Finalist",
        "problem_type": "multiclass_probability_and_score_regression", "status": "research_candidate",
        "owner_user_id": user_id, "current_version_id": None,
        "tags_json": ["NFL", "DEVELOPMENT_OOF", "RESEARCH_ONLY", "NOT_PROMOTED"],
        "description": "Preserved Development finalist; M1 remains retained and no champion pointer is assigned.",
    })
    if service.model_versions.get(model_version_id) is None:
        fitted = analysis["fittedDevelopmentArtifact"]
        version_number = service.model_versions.next_version_number(MODEL_ID)
        service.model_versions.insert({
            "model_version_id": model_version_id, "model_id": MODEL_ID, "version_number": version_number,
            "training_run_id": run_id, "project_id": PROJECT_ID,
            "dataset_id": "asp.nfl.gold-data-foundation.v1", "dataset_version_id": registration["dataset_version_id"],
            "feature_manifest_version": analysis["treatmentFeatureManifestSha256"],
            "algorithm": analysis["developmentSelectedPipeline"], "algorithm_version": "development-v1",
            "hyperparameters_json": fitted["state"]["parameters"],
            "training_parameters_json": {"maximumSeason": 2024, "finalOotAccessed": False},
            "metrics_summary_json": analysis["calibration"],
            "evaluation_summary_json": analysis["pairedUncertaintyVersusM1"],
            "interpretation_summary_json": analysis["comparisonFindings"],
            "artifact_reference": fitted["path"], "artifact_format": "joblib",
            "training_timestamp": analysis["completedAt"], "checksum": fitted["sha256"],
            "artifact_size_bytes": fitted["bytes"], "publication_status": "research_only",
            "lineage_status": "verified_development_only", "candidate_id": analysis["developmentSelectedPipeline"],
            "selection_metric_name": "HOME_AWAY_TIE_MULTICLASS_LOG_LOSS",
            "selection_metric_value": analysis["calibration"]["calibrated"]["multiclassLogLoss"],
            "selection_metric_source": "development_oof", "target_name": "home_away_tie",
            "approval_status": "not_approved", "validation_status": "development_oof_only",
            "documentation_status": "report_available", "created_by": user_id,
            "lineage_json": {"matrixSha256": analysis["matrixSha256"], "manifestSha256": manifest_sha256,
                             "finalOotAccessed": False, "promotionStatus": "NOT_PROMOTED"},
        })
    evidence_specs = [
        ("matrix", "nfl-08", analysis["matrixSha256"], "Frozen experiment matrix", analysis["matrixSha256"]),
        ("treatment-feature", "nfl-08", analysis["treatmentFeatureManifestSha256"], "Treatment and feature manifest", analysis["treatmentFeatureManifestPath"]),
        ("evaluation", "nfl-09", manifest_sha256, "Chronological model comparison", analysis["reportPath"]),
        ("calibration", "nfl-10", analysis["fittedCalibrationArtifact"]["sha256"], "Finalist calibration evidence", analysis["fittedCalibrationArtifact"]["path"]),
    ]
    for suffix, step_id, digest, title, source in evidence_specs:
        service.evidence.upsert({
            "evidence_id": f"nfl-lab-{suffix}-{digest[:20]}", "project_id": PROJECT_ID,
            "workflow_type": "nfl-forecasting", "step_id": step_id,
            "artifact_type": "research_evidence", "status": "complete_development_only",
            "title": title, "summary": "Development evidence; 2025 Final OOT sealed; not promoted.",
            "source_ref": source, "artifact_hash": digest, "created_by": user_id,
            "payload_json": {"manifestSha256": manifest_sha256, "finalOotAccessed": False,
                             "promotionStatus": "NOT_PROMOTED"},
        })
    service.exports.upsert({
        "export_id": f"nfl-lab-handoff-{handoff_sha256[:20]}", "project_id": PROJECT_ID,
        "export_type": "research_handoff", "file_name": Path(handoff_path).name,
        "file_path": str(Path(handoff_path).resolve()), "storage_mode": "server_file",
        "created_by": user_id, "artifact_hash": handoff_sha256,
        "metadata_json": {"status": "RESEARCH_SHADOW", "executionAllowedInAisp": False,
                          "wageringAuthority": False},
    })
    audit_id = f"audit_nfl_lab_{manifest_sha256[:20]}"
    if service.audit.get(audit_id) is None:
        service.audit.create({
            "audit_id": audit_id, "project_id": PROJECT_ID,
            "user_id": user_id, "action_type": "nfl.research_laboratory.registered",
            "entity_type": "run_record", "entity_id": run_id, "title": "NFL research laboratory registered",
            "summary": "Immutable Development-only result registered without promotion.", "created_at": timestamp,
            "metadata_json": {"manifestSha256": manifest_sha256, "finalOotAccessed": False},
        })
    model = service.models.get(MODEL_ID) or {}
    if model.get("current_version_id") is not None:
        raise NflLabRegistrationError("research registration unexpectedly assigned a champion pointer")
    return {
        "projectId": PROJECT_ID, "runId": run_id, "modelId": MODEL_ID,
        "modelVersionId": model_version_id, "championPointer": None,
        "registrationId": registration["registration_id"], "status": "REGISTERED_RESEARCH_ONLY",
    }


__all__ = ["NflLabRegistrationError", "PROJECT_ID", "register_overnight_lab"]

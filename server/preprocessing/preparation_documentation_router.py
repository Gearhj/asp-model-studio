from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from ..core.modeling_scope import authorize_modeling_scope
from ..security.security_store import require_user
from .predictor_authorization import governed_predictor_authorization


router = APIRouter()


def _current_source_stage() -> str:
    return "outlier_treated" if DATASTORE.meta.get("outlier_application") else "registered_dataset"


def _record_state(record: Any, dataset_version: str) -> str:
    if not isinstance(record, dict):
        return "draft"
    return "confirmed" if record.get("dataset_version") == dataset_version else "stale"


def _feature_documentation(manifest: Any, dataset_version: str) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        return {
            "status": "draft",
            "manifest_version": None,
            "accepted_features": [],
            "materialized_features": [],
            "pipeline_steps": [],
        }
    features = [
        row
        for row in manifest.get("features", [])
        if isinstance(row, dict) and row.get("origin") != "original"
    ]
    materialized = [
        row.get("feature_name")
        for row in features
        if row.get("materialization_status") == "materialized"
    ]
    manifest_hash = str(
        manifest.get("manifest_hash") or manifest.get("manifest_version") or ""
    )
    stale = manifest.get("dataset_version") != dataset_version
    current = (
        not stale
        and manifest.get("validation_status") == "passed"
        and manifest.get("materialization_status") == "current"
        and manifest.get("materialized_manifest_hash") == manifest_hash
        and manifest.get("confirmation_status") == "confirmed"
        and manifest.get("confirmed_manifest_hash") == manifest_hash
        and all(
            row.get("materialization_status") == "materialized"
            for row in features
        )
    )
    return {
        "status": "stale" if stale else "confirmed" if current else "draft",
        "manifest_version": manifest.get("manifest_version"),
        "manifest_hash": manifest_hash,
        "dataset_version": manifest.get("dataset_version"),
        "validation_status": manifest.get("validation_status"),
        "materialization_status": manifest.get("materialization_status"),
        "materialization_hash": manifest.get("materialization_hash"),
        "materialized_manifest_hash": manifest.get("materialized_manifest_hash"),
        "confirmation_status": manifest.get("confirmation_status"),
        "confirmed_manifest_hash": manifest.get("confirmed_manifest_hash"),
        "execution_history": manifest.get("execution_history") or [],
        "accepted_features": [
            {
                "feature_name": row.get("feature_name"),
                "origin": row.get("origin"),
                "formula_or_rule": row.get("formula_or_rule"),
                "source_features": row.get("source_features") or [],
                "rationale": row.get("user_rationale") or "",
                "evidence_reference": row.get("evidence_reference"),
                "materialization_status": row.get("materialization_status"),
            }
            for row in features
        ],
        "materialized_features": materialized,
        "pipeline_steps": manifest.get("pipeline_steps") or [],
        "split_status": manifest.get("split_status") or DATASTORE.meta.get("split_status") or "not_created",
    }


def _validation_documentation(
    design: Any,
    split_record: Any,
    feature_engineering: dict[str, Any],
    dataset_version: str,
) -> dict[str, Any]:
    if not isinstance(design, dict) or not design:
        return {
            "status": "draft",
            "validation_design_id": None,
            "design_version": None,
            "strategy": None,
            "completion_gates": {},
        }
    record = split_record if isinstance(split_record, dict) else {}
    gates = (
        design.get("completion_gates")
        if isinstance(design.get("completion_gates"), dict)
        else record.get("completion_gates")
        if isinstance(record.get("completion_gates"), dict)
        else {}
    )
    reasons: list[str] = []
    if design.get("status") != "approved":
        reasons.append("Validation Design is not approved.")
    if str(DATASTORE.meta.get("split_status") or "") != "current":
        reasons.append("The persisted split is not current.")
    development = (
        design.get("development_dataset")
        if isinstance(design.get("development_dataset"), dict)
        else {}
    )
    bound_dataset_version = (
        design.get("dataset_version")
        or design.get("development_dataset_version")
        or development.get("version_id")
    )
    if bound_dataset_version not in {None, "", dataset_version}:
        reasons.append("The development dataset version changed.")
    if (
        record.get("feature_manifest_version")
        and record.get("feature_manifest_version")
        != feature_engineering.get("manifest_hash")
    ):
        reasons.append("The Feature Engineering manifest changed.")
    if feature_engineering.get("status") != "confirmed":
        reasons.append("The Feature Engineering contract is not confirmed current.")
    failed_gates = [str(key) for key, value in gates.items() if value is not True]
    if failed_gates:
        reasons.append(
            "Validation completion gates require attention: "
            + ", ".join(failed_gates)
            + "."
        )
    status = "stale" if reasons else "confirmed"
    return {
        "status": status,
        "validation_design_id": design.get("validation_design_id"),
        "design_version": design.get("design_version"),
        "strategy": design.get("strategy"),
        "development_dataset_version": design.get("development_dataset_version"),
        "training_population_id": record.get("training_population_id"),
        "holdout_population_id": record.get("holdout_population_id"),
        "test_reference": record.get("test_reference"),
        "oot_reference": record.get("oot_reference"),
        "cv_design": record.get("cv_design") or design.get("cv_design") or {},
        "fold_architecture": record.get("fold_architecture") or {},
        "balancing_policy": design.get("balancing_policy")
        or record.get("balancing_policy")
        or {},
        "completion_gates": gates,
        "validation_risks": record.get("validation_risks") or [],
        "confirmation_actor": record.get("confirmation_actor")
        or design.get("approved_by"),
        "confirmation_time": record.get("confirmation_time")
        or design.get("approved_at"),
        "stale_reasons": reasons,
    }


def _training_documentation(
    execution: Any,
    decision: Any,
    feature_engineering: dict[str, Any],
    validation_design: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(execution, dict) or not execution:
        return {
            "status": "draft",
            "training_job_id": None,
            "job_status": None,
            "model_portfolio": [],
            "ranked_candidates": [],
            "model_selection_decision": decision
            if isinstance(decision, dict)
            else None,
        }
    reasons: list[str] = []
    if validation_design.get("status") != "confirmed":
        reasons.append("The approved Validation Design is not current.")
    if (
        execution.get("validation_design_version")
        and execution.get("validation_design_version")
        != validation_design.get("design_version")
    ):
        reasons.append("Training is bound to an earlier Validation Design version.")
    if (
        execution.get("feature_manifest_version")
        and execution.get("feature_manifest_version")
        != feature_engineering.get("manifest_hash")
    ):
        reasons.append("Training is bound to an earlier feature manifest.")
    decision_record = decision if isinstance(decision, dict) else None
    if decision_record and (
        decision_record.get("training_job_id") != execution.get("training_job_id")
        or decision_record.get("validation_design_version")
        != validation_design.get("design_version")
        or decision_record.get("feature_manifest_version")
        != feature_engineering.get("manifest_hash")
    ):
        reasons.append("The champion/challenger proposal is stale.")
    terminal_success = execution.get("status") == "complete"
    status = (
        "stale"
        if reasons
        else "confirmed"
        if terminal_success and decision_record is not None
        else "draft"
    )
    return {
        "status": status,
        "training_job_id": execution.get("training_job_id"),
        "job_status": execution.get("status"),
        "candidate_strategy": execution.get("candidate_strategy"),
        "model_portfolio": execution.get("requested_models") or [],
        "completed_models": execution.get("completed_models") or [],
        "failed_models": execution.get("failed_models") or [],
        "ranked_candidates": execution.get("ranked_candidates") or [],
        "validation_design_id": execution.get("validation_design_id"),
        "validation_design_version": execution.get("validation_design_version"),
        "feature_manifest_version": execution.get("feature_manifest_version"),
        "split_id": execution.get("split_id"),
        "tuning_policy": (execution.get("contract") or {}).get(
            "tuning_configuration"
        ),
        "cv_configuration": (execution.get("contract") or {}).get("cv_design"),
        "calibration_policy": (execution.get("contract") or {}).get(
            "calibration_configuration"
        ),
        "runtime_environment": (execution.get("contract") or {}).get(
            "runtime_environment"
        ),
        "runtime_ms": execution.get("runtime_ms"),
        "completed_at": execution.get("completed_at"),
        "model_selection_decision": decision_record,
        "decision_status": (
            decision_record.get("status") if decision_record else "pending"
        ),
        "stale_reasons": reasons,
    }


@router.get("/preparation/documentation")
def preparation_documentation(
    project_id: str = Query(...),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "view")
    frame = DATASTORE.raw_df if DATASTORE.raw_df is not None else DATASTORE.get_raw_active_df()
    dataset_version = str(DATASTORE.meta.get("dataset_version") or "unversioned")
    authorization = (
        governed_predictor_authorization(
            frame,
            target=DATASTORE.target,
            selected_columns=DATASTORE.get_selected_columns(),
        )
        if frame is not None and not frame.empty
        else {
            "authorized_predictors": [],
            "excluded_predictors": {},
            "target_source_excluded": [],
        }
    )

    outlier_application = DATASTORE.meta.get("outlier_application")
    outliers = {
        "status": _record_state(outlier_application, dataset_version),
        "application": outlier_application,
    }

    missing_application = DATASTORE.meta.get("missing_application")
    missing_validation = DATASTORE.meta.get("missing_validation")
    if isinstance(missing_application, dict):
        missing_status = _record_state(missing_application, dataset_version)
    elif isinstance(missing_validation, dict):
        missing_status = _record_state(missing_validation, dataset_version)
        if (
            missing_status == "confirmed"
            and missing_validation.get("source_stage") != _current_source_stage()
        ):
            missing_status = "stale"
    else:
        missing_status = "draft"
    missing = {
        "status": missing_status,
        "application": missing_application,
        "validation": missing_validation,
    }

    feature_engineering = _feature_documentation(
        DATASTORE.meta.get("feature_manifest"),
        dataset_version,
    )
    validation_design = _validation_documentation(
        DATASTORE.meta.get("validation_design"),
        DATASTORE.meta.get("split_record"),
        feature_engineering,
        dataset_version,
    )
    model_training = _training_documentation(
        DATASTORE.meta.get("training_execution"),
        DATASTORE.meta.get("model_selection_decision"),
        feature_engineering,
        validation_design,
    )
    statuses = [
        outliers["status"],
        missing["status"],
        feature_engineering["status"],
        validation_design["status"],
        model_training["status"],
    ]
    overall = (
        "stale"
        if "stale" in statuses
        else "confirmed"
        if all(status == "confirmed" for status in statuses)
        else "draft"
    )
    record = {
        "ok": True,
        "project_id": project_id,
        "dataset_version": dataset_version,
        "target": DATASTORE.target,
        "predictor_manifest_id": feature_engineering.get("manifest_version"),
        "status": overall,
        "predictor_authorization": authorization,
        "outliers": outliers,
        "missing_values": missing,
        "feature_engineering": feature_engineering,
        "validation_design": validation_design,
        "model_training": model_training,
        "governance": {
            "backend_enforced": True,
            "target_source_excluded": authorization.get("target_source_excluded", []),
            "automatic_feature_acceptance": False,
            "automatic_row_removal": False,
        },
    }
    stable = json.dumps(record, sort_keys=True, default=str, separators=(",", ":"))
    record["documentation_version"] = (
        f"prep-doc-{hashlib.sha256(stable.encode('utf-8')).hexdigest()[:12]}"
    )
    return json_safe(record)

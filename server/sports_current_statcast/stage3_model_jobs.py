"""Project-scoped experiment planning, queueing, and progress for Stage 3.

Mutable operational progress uses the existing ``run_records`` table.  Final
scientific evidence is an immutable content-addressed V2 receipt beside the
preserved V1 receipts.  The coordinator is deliberately single-worker and is
also protected by an interprocess lock.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..persistence.db import Database, json_dumps, json_loads, now_iso
from ..persistence.repositories.run_repository import RunRepository
from ..sports_cockpit.interprocess_lock import LockBusy, interprocess_lock
from ..sports_datasets.consumer import canonical_json_bytes
from ..sports_gold.contracts import GOLD_CLASS_ORDER
from .stage3_model_catalog import HARD_FIT_LIMIT, model_catalog, plan_configurations
from .stage3_model_eligibility import (
    assess_feature_set,
    build_feature_set_record,
    build_model_eligibility,
)
from .stage3_model_laboratory import (
    CURRENT_GOLD_DATASET_ID,
    EXPECTED_DEVELOPMENT,
    EXPECTED_FINAL_OOT,
    Stage3ModelLaboratoryError,
    _environment_identity,
    _evaluate_candidate,
    _fold_frame,
    _persist_run,
    _runtime_root,
    resolve_model_lab_authority,
)


MODEL_DEVELOPMENT_PLAN_SCHEMA_VERSION = "SPORTS_STAGE3_MODEL_DEVELOPMENT_PLAN_V1"
MODEL_DEVELOPMENT_JOB_TYPE = "sports_stage3_model_development"
MODEL_DEVELOPMENT_RECEIPT_SCHEMA_VERSION = "SPORTS_STAGE3_MODEL_DEVELOPMENT_RUN_RECEIPT_V2"

_ACTIVE_STATUSES = {"QUEUED", "RUNNING"}
_FORBIDDEN_PLAN_OPTIONS = {
    "finalOot", "holdout", "globalMatrix", "base22", "promote", "champion",
    "calibrateOnOot", "randomSplit", "provider",
}
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stage3-model-development")
_SUBMISSION_GUARD = threading.Lock()


def _sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _catalog_by_id() -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in model_catalog()}


def _transformations_for_subset(
    eligibility: Mapping[str, Any], ordered_features: list[str]
) -> dict[str, Any]:
    full = eligibility.get("transformationContracts") or {}
    by_name = {
        str(item.get("feature")): item
        for item in full.get("ordered") or []
        if isinstance(item, Mapping)
    }
    return {
        **dict(full),
        "ordered": [dict(by_name[name]) for name in ordered_features],
    }


def _custom_feature_set(
    eligibility: Mapping[str, Any], ordered_features: Any
) -> dict[str, Any]:
    if not isinstance(ordered_features, list) or not ordered_features:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_CUSTOM_FEATURES_REQUIRED",
            "A custom subset requires at least one ordered eligible predictor.",
        )
    names = [str(item) for item in ordered_features]
    if len(names) != len(set(names)):
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_CUSTOM_FEATURE_DUPLICATE",
            "The custom feature subset contains a duplicate predictor.",
        )
    eligible = set(eligibility.get("orderedFeatures") or [])
    rejected = [name for name in names if name not in eligible]
    if rejected:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_CUSTOM_FEATURE_INELIGIBLE",
            "Custom subset contains default-ineligible predictors: " + ", ".join(rejected),
        )
    payload = {
        "schemaVersion": "SPORTS_STAGE3_CUSTOM_ELIGIBLE_SUBSET_V1",
        "parentFeatureUniverseId": eligibility["featureSetId"],
        "parentFeatureUniverseChecksum": eligibility["checksum"],
        "orderedFeatures": names,
        "transformationContracts": _transformations_for_subset(eligibility, names),
        "finalOotTargetAccessed": False,
    }
    checksum = _sha(payload)
    return {
        **payload,
        "featureSetId": f"stage3-custom-modeling-subset-{checksum[:32]}",
        "featureSetKey": "CUSTOM_ELIGIBLE_SUBSET",
        "name": "Custom eligible subset",
        "version": 1,
        "status": "RUN_SCOPED_CONTENT_ADDRESSED_AUTHORITY",
        "checksum": checksum,
        "unavailableExclusions": [],
    }


def _feature_set_for_experiment(
    resolved: Any,
    eligibility: Mapping[str, Any],
    experiment: Mapping[str, Any],
) -> dict[str, Any] | None:
    algorithm_id = str(experiment.get("algorithmId") or "")
    if algorithm_id == "class_frequency_null":
        return None
    requested = str(experiment.get("featureUniverseId") or eligibility["featureSetId"])
    if requested in {"FULL_ELIGIBLE", eligibility["featureSetId"]}:
        return build_feature_set_record(eligibility)
    if requested == "CUSTOM_SUBSET":
        return _custom_feature_set(eligibility, experiment.get("orderedFeatures"))
    registered = next(
        (item for item in resolved.feature_sets if item.get("featureSetId") == requested),
        None,
    )
    if registered is None:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_FEATURE_UNIVERSE_UNKNOWN",
            f"Unknown project-bound feature universe: {requested}.",
            status_code=409,
        )
    assessment = assess_feature_set(registered, eligibility)
    if assessment["blockingFeatures"]:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_FEATURE_SET_NON_EXECUTABLE",
            "The preserved registration is not currently executable; blocking features: "
            + ", ".join(str(item["name"]) for item in assessment["blockingFeatures"]),
            status_code=409,
        )
    if assessment["reviewRequiredFeatures"]:
        rationale = str(experiment.get("eligibilityOverrideRationale") or "").strip()
        if len(rationale) < 20:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_FEATURE_SET_REVIEW_REQUIRED",
                "This preserved preset contains semantic-sparse predictors and requires a written prospective-semantics rationale.",
                status_code=409,
            )
        if experiment.get("prospectiveSemanticCompatibilityAcknowledged") is not True:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_FEATURE_SET_SEMANTIC_ACK_REQUIRED",
                "The scientist must explicitly acknowledge prospective semantic compatibility for the sparse-feature override.",
                status_code=409,
            )
        if experiment.get("foldLocalTreatmentAcknowledged") is not True:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_FEATURE_SET_FOLD_LOCAL_ACK_REQUIRED",
                "The scientist must explicitly acknowledge that treatment is fitted inside each chronological training fold.",
                status_code=409,
            )
        return {
            **dict(registered),
            "executionCompatibilityOverride": {
                "status": "SCIENTIST_REVIEWED_RUN_SCOPED_OVERRIDE",
                "rationale": rationale,
                "prospectiveSemanticCompatibilityAcknowledged": True,
                "foldLocalTreatmentAcknowledged": True,
                "reviewRequiredFeatures": [
                    str(item["name"]) for item in assessment["reviewRequiredFeatures"]
                ],
            },
        }
    return dict(registered)


def plan_model_development_queue(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_PLAN_INVALID", "The experiment plan must be an object."
        )
    present = sorted(_FORBIDDEN_PLAN_OPTIONS & set(payload))
    if present:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_FORBIDDEN_OPTION",
            "Forbidden experiment-plan option(s): " + ", ".join(present),
        )
    resolved = resolve_model_lab_authority(database, project_id)
    if str(payload.get("authorityKey") or "") != resolved.authority_key:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_AUTHORITY_STALE",
            "The experiment plan does not match the current project/Gold authority.",
            status_code=409,
        )
    if str(payload.get("splitContractId") or "") != str(resolved.split["contractId"]):
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_SPLIT_IDENTITY_MISMATCH",
            "The exact registered five-fold split v2 is required.",
            status_code=409,
        )
    eligibility = build_model_eligibility(resolved)
    catalog = _catalog_by_id()
    raw_experiments = payload.get("experiments")
    if not isinstance(raw_experiments, list) or not raw_experiments:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_EXPERIMENT_REQUIRED",
            "Add at least one model configuration to the experiment queue.",
        )
    default_seed = payload.get("seed", 20260901)
    if isinstance(default_seed, bool) or not isinstance(default_seed, int) or not 0 <= default_seed <= 2**32 - 1:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_SEED_INVALID", "Seed must be an unsigned 32-bit integer."
        )
    planned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_experiments, start=1):
        if not isinstance(raw, Mapping):
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_EXPERIMENT_INVALID",
                f"Experiment {index} is not an object.",
            )
        nested_forbidden = sorted(_FORBIDDEN_PLAN_OPTIONS & set(raw))
        if nested_forbidden:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_FORBIDDEN_OPTION",
                f"Experiment {index} contains forbidden option(s): " + ", ".join(nested_forbidden),
            )
        algorithm_id = str(raw.get("algorithmId") or "")
        algorithm = catalog.get(algorithm_id)
        if algorithm is None:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_ALGORITHM_UNKNOWN", f"Unknown algorithm: {algorithm_id}."
            )
        if not algorithm["available"]:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_ALGORITHM_HELD_CLOSED",
                f"{algorithm['label']} is {algorithm['status']}: {algorithm.get('unavailableReason') or 'not executable'}",
                status_code=409,
            )
        seed = raw.get("seed", default_seed)
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_SEED_INVALID", f"Experiment {index} has an invalid seed."
            )
        feature_set = _feature_set_for_experiment(resolved, eligibility, raw)
        try:
            tuning = plan_configurations(algorithm, raw, seed=int(seed))
        except (TypeError, ValueError) as exc:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_TUNING_INVALID", f"{algorithm['label']}: {exc}"
            ) from exc
        identity_payload = {
            "algorithmId": algorithm_id,
            "featureSetId": (feature_set or {}).get("featureSetId"),
            "featureSetChecksum": (feature_set or {}).get("checksum"),
            "eligibilityOverride": (feature_set or {}).get("executionCompatibilityOverride"),
            "tuningMode": tuning["tuningMode"],
            "gridPreset": tuning["gridPreset"],
            "configurations": tuning["configurations"],
            "configurationCount": tuning["configurationCount"],
            "seed": int(seed),
            "metric": "MULTICLASS_LOG_LOSS",
            "splitContractId": resolved.split["contractId"],
        }
        experiment_id = "stage3-model-experiment-" + _sha(identity_payload)[:32]
        if experiment_id in seen:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_EXPERIMENT_DUPLICATE",
                f"Duplicate queued experiment: {algorithm['label']} / {(feature_set or {}).get('name') or 'null'}.",
            )
        seen.add(experiment_id)
        planned.append(
            {
                "experimentId": experiment_id,
                "modelFamily": algorithm["family"],
                "algorithmId": algorithm_id,
                "algorithmLabel": algorithm["label"],
                "featureUniverseId": (feature_set or {}).get("featureSetId"),
                "featureUniverseName": (feature_set or {}).get("name") or "Feature-independent null reference",
                "featureUniverseChecksum": (feature_set or {}).get("checksum"),
                "featureCount": len((feature_set or {}).get("orderedFeatures") or []),
                "featureSetContract": feature_set,
                "tuning": tuning,
                "seed": int(seed),
                "metric": "MULTICLASS_LOG_LOSS",
                "preprocessingAuthority": "FIT_INSIDE_EACH_REGISTERED_TRAINING_FOLD_ONLY",
                "computeIntensity": algorithm["computeIntensity"],
                "status": "PLANNED",
            }
        )
    total_configurations = sum(int(item["tuning"]["configurationCount"]) for item in planned)
    total_fits = sum(int(item["tuning"]["totalFits"]) for item in planned)
    executable = total_fits <= HARD_FIT_LIMIT and all(
        item["tuning"]["configurations"] for item in planned
    )
    requires_ack = any(item["tuning"]["requiresAcknowledgement"] for item in planned) or total_fits > 250
    plan_payload = {
        "schemaVersion": MODEL_DEVELOPMENT_PLAN_SCHEMA_VERSION,
        "projectId": project_id,
        "authorityKey": resolved.authority_key,
        "featureUniverseId": eligibility["featureSetId"],
        "featureUniverseChecksum": eligibility["checksum"],
        "splitContractId": resolved.split["contractId"],
        "splitChecksum": resolved.split["checksum"],
        "foldCount": 5,
        "metric": "MULTICLASS_LOG_LOSS",
        "experiments": planned,
        "totalExperiments": len(planned),
        "totalConfigurations": total_configurations,
        "totalFits": total_fits,
        "requiresAcknowledgement": requires_ack,
        "acknowledged": payload.get("acknowledgeExcessiveFits") is True,
        "hardFitLimit": HARD_FIT_LIMIT,
        "executable": executable,
        "executionBlocker": (
            f"Queue requests {total_fits:,} fits, above the hard limit of {HARD_FIT_LIMIT:,}. Reduce the grid."
            if total_fits > HARD_FIT_LIMIT
            else "An oversized grid domain is inspectable but was not expanded into an executable plan."
            if not executable
            else None
        ),
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
        "providerCalls": 0,
        "promotionRequested": False,
    }
    return {**plan_payload, "planId": "stage3-model-plan-" + _sha(plan_payload)[:32], "checksum": _sha(plan_payload)}


def _assert_plan_current(
    resolved: Any, eligibility: Mapping[str, Any], plan: Mapping[str, Any]
) -> None:
    """Revalidate a queued plan before any development-row materialization."""

    unsigned = {key: value for key, value in plan.items() if key not in {"planId", "checksum"}}
    expected_checksum = _sha(unsigned)
    checks = {
        "projectId": resolved.project_id,
        "authorityKey": resolved.authority_key,
        "featureUniverseId": eligibility["featureSetId"],
        "featureUniverseChecksum": eligibility["checksum"],
        "splitContractId": resolved.split["contractId"],
        "splitChecksum": resolved.split["checksum"],
        "foldCount": 5,
        "metric": "MULTICLASS_LOG_LOSS",
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
        "providerCalls": 0,
        "promotionRequested": False,
        "checksum": expected_checksum,
    }
    for key, expected in checks.items():
        actual = plan.get(key)
        if isinstance(expected, bool):
            matches = actual is expected
        else:
            matches = actual == expected
        if not matches:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_QUEUED_AUTHORITY_STALE",
                f"Queued plan {key} no longer matches the exact current authority.",
                status_code=409,
            )
    if plan.get("planId") != "stage3-model-plan-" + expected_checksum[:32]:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_PLAN_INTEGRITY_INVALID",
            "Queued plan identity does not match its canonical content.",
            status_code=409,
        )


def _decode_job(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "jobId": row.get("run_id"),
        "projectId": row.get("project_id"),
        "status": str(row.get("status") or "").upper(),
        "createdBy": row.get("created_by"),
        "startedAt": row.get("started_at"),
        "completedAt": row.get("completed_at"),
        "plan": json_loads(row.get("parameters_json"), {}),
        "progress": json_loads(row.get("metrics_json"), {}),
        "artifacts": json_loads(row.get("artifacts_json"), {}),
        "error": json_loads(row.get("error_json"), {}),
    }


def _upsert_job(database: Database, job: Mapping[str, Any]) -> dict[str, Any]:
    return RunRepository(database).upsert(dict(job))


def _active_job(database: Database, project_id: str) -> dict[str, Any] | None:
    for row in RunRepository(database).list_for_project(project_id):
        if row.get("run_type") == MODEL_DEVELOPMENT_JOB_TYPE and str(row.get("status") or "").upper() in _ACTIVE_STATUSES:
            return row
    return None


def enqueue_model_development_job(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    plan = plan_model_development_queue(database, project_id, payload)
    if not plan["executable"]:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_PLAN_NOT_EXECUTABLE", str(plan["executionBlocker"])
        )
    if plan["requiresAcknowledgement"] and not plan["acknowledged"]:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_COMPUTE_ACK_REQUIRED",
            f"The queue contains {plan['totalFits']:,} fits; explicit acknowledgement is required.",
        )
    with _SUBMISSION_GUARD:
        claim_path = _runtime_root() / "locks" / f"{project_id}.model-development-claim.lock"
        try:
            with interprocess_lock(claim_path, blocking=True, timeout=10.0, stale_after=120.0):
                current = _active_job(database, project_id)
                if current is not None:
                    raise Stage3ModelLaboratoryError(
                        "MODEL_DEVELOPMENT_JOB_ALREADY_ACTIVE",
                        f"Project job {current['run_id']} is already {str(current['status']).upper()}.",
                        status_code=409,
                    )
                job_id = "stage3-model-job-" + uuid.uuid4().hex
                started = now_iso()
                row = _upsert_job(
                    database,
                    {
                        "run_id": job_id,
                        "project_id": project_id,
                        "run_type": MODEL_DEVELOPMENT_JOB_TYPE,
                        "workflow_type": "sports_stage3_model_development",
                        "status": "QUEUED",
                        "started_at": started,
                        "completed_at": None,
                        "parameters_json": plan,
                        "metrics_json": {
                            "state": "QUEUED",
                            "completedFits": 0,
                            "failedFits": 0,
                            "totalFits": plan["totalFits"],
                            "elapsedSeconds": 0.0,
                            "estimatedRemainingSeconds": None,
                            "message": "Waiting for the single project-scoped model-development worker.",
                        },
                        "artifacts_json": {
                            "coordinatorProcessId": os.getpid(),
                            "finalOotTargetAccessed": False,
                            "promotionStatus": "NOT_PROMOTED",
                        },
                        "error_json": {},
                        "created_by": actor_user_id,
                    },
                )
        except LockBusy as exc:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_JOB_CLAIM_BUSY",
                "Another process is claiming a project model-development job.",
                status_code=409,
            ) from exc
        _EXECUTOR.submit(
            _execute_job,
            str(database.path),
            job_id,
            project_id,
            actor_user_id,
            plan,
        )
    return {"ok": True, "job": _decode_job(row)}


def _execute_job(
    database_path: str,
    job_id: str,
    project_id: str,
    actor_user_id: str,
    plan: Mapping[str, Any],
) -> None:
    database = Database(database_path)
    started_clock = time.perf_counter()
    completed_fits = 0
    failed_fits = 0
    failures: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    frames: dict[str, Any] = {}
    lock_path = _runtime_root() / "locks" / f"{project_id}.model-development.lock"

    def update_progress(extra: Mapping[str, Any]) -> None:
        elapsed = time.perf_counter() - started_clock
        mean = elapsed / completed_fits if completed_fits else None
        remaining = (
            mean * max(0, int(plan["totalFits"]) - completed_fits - failed_fits)
            if mean is not None
            else None
        )
        row = RunRepository(database).get(job_id) or {}
        _upsert_job(
            database,
            {
                "run_id": job_id,
                "project_id": project_id,
                "run_type": MODEL_DEVELOPMENT_JOB_TYPE,
                "workflow_type": "sports_stage3_model_development",
                "status": "RUNNING",
                "started_at": row.get("started_at") or now_iso(),
                "completed_at": None,
                "parameters_json": plan,
                "metrics_json": {
                    "state": "RUNNING",
                    "completedFits": completed_fits,
                    "failedFits": failed_fits,
                    "totalFits": plan["totalFits"],
                    "elapsedSeconds": elapsed,
                    "estimatedRemainingSeconds": remaining,
                    "failures": failures,
                    **dict(extra),
                },
                "artifacts_json": json_loads(row.get("artifacts_json"), {}),
                "error_json": {},
                "created_by": actor_user_id,
            },
        )

    try:
        with interprocess_lock(lock_path, blocking=False, stale_after=86_400.0):
            resolved = resolve_model_lab_authority(database, project_id)
            eligibility = build_model_eligibility(resolved)
            _assert_plan_current(resolved, eligibility, plan)
            update_progress({"message": "Exact project, feature, treatment, and split authorities verified."})
            for experiment_index, experiment in enumerate(plan["experiments"], start=1):
                feature_set = experiment.get("featureSetContract")
                feature_key = str((feature_set or {}).get("featureSetId") or "NOT_APPLICABLE")
                if feature_key not in frames:
                    frames[feature_key] = _fold_frame(
                        resolved, list((feature_set or {}).get("orderedFeatures") or [])
                    )
                frame = frames[feature_key]
                configurations = list((experiment.get("tuning") or {}).get("configurations") or [])
                for config_index, hyperparameters in enumerate(configurations, start=1):
                    config_fits = 0

                    def on_fold(event: dict[str, Any]) -> None:
                        nonlocal completed_fits, config_fits
                        if event.get("event") == "FOLD_COMPLETED":
                            completed_fits += 1
                            config_fits += 1
                        update_progress(
                            {
                                "currentExperiment": experiment_index,
                                "experimentCount": plan["totalExperiments"],
                                "currentAlgorithm": experiment["algorithmId"],
                                "currentFeatureUniverse": experiment["featureUniverseName"],
                                "currentConfiguration": config_index,
                                "configurationCount": len(configurations),
                                "currentHyperparameters": hyperparameters,
                                "currentFold": event.get("fold"),
                                "foldCount": 5,
                                "message": f"{experiment['algorithmLabel']} · configuration {config_index}/{len(configurations)} · fold {event.get('fold')}/5",
                            }
                        )

                    try:
                        result = _evaluate_candidate(
                            frame,
                            model_family=str(experiment["algorithmId"]),
                            feature_set=feature_set,
                            split=resolved.split,
                            seed=int(experiment["seed"]),
                            hyperparameters=hyperparameters,
                            progress_callback=on_fold,
                        )
                        result["experimentId"] = experiment["experimentId"]
                        result["tuningMode"] = experiment["tuning"]["tuningMode"]
                        result["gridPreset"] = experiment["tuning"]["gridPreset"]
                        result["configurationIndex"] = config_index
                        result["developmentLabel"] = "DEVELOPMENT_CANDIDATE"
                        candidates.append(result)
                    except Exception as exc:  # one configuration cannot erase siblings
                        uncounted = 5 - config_fits
                        failed_fits += uncounted
                        failure = {
                            "experimentId": experiment["experimentId"],
                            "algorithmId": experiment["algorithmId"],
                            "configurationIndex": config_index,
                            "hyperparameters": hyperparameters,
                            "errorCode": getattr(exc, "code", "MODEL_DEVELOPMENT_CONFIGURATION_FAILED"),
                            "reason": str(exc),
                            "failedFits": uncounted,
                        }
                        failures.append(failure)
                        candidates.append(
                            {
                                "candidateId": "stage3-candidate-" + uuid.uuid4().hex,
                                "experimentId": experiment["experimentId"],
                                "modelFamily": experiment["algorithmId"],
                                "hyperparameters": hyperparameters,
                                "featureSetId": experiment["featureUniverseId"],
                                "featureSetName": experiment["featureUniverseName"],
                                "featureCount": experiment["featureCount"],
                                "status": "FAILED",
                                "foldsCompleted": config_fits,
                                "meanOofLogLoss": None,
                                "summedBrier": None,
                                "ece": None,
                                "accuracyDiagnostic": None,
                                "macroF1Diagnostic": None,
                                "folds": [],
                                "runtimeMs": 0,
                                "errorCode": failure["errorCode"],
                                "errorReason": failure["reason"],
                            }
                        )
                        update_progress({"message": f"Configuration failed closed: {exc}"})
            completed = [item for item in candidates if item.get("status") == "COMPLETE"]
            receipt = {
                "schemaVersion": MODEL_DEVELOPMENT_RECEIPT_SCHEMA_VERSION,
                "runId": "stage3-model-development-run-" + uuid.uuid4().hex,
                "createdAt": now_iso(),
                "createdByUserId": actor_user_id,
                "status": "COMPLETE" if len(completed) == len(candidates) else "PARTIAL",
                "identity": {
                    "projectId": project_id,
                    "projectName": resolved.project_name,
                    "registrationId": resolved.eda_authority.registration_id,
                    "datasetVersionId": resolved.eda_authority.dataset_version_id,
                    "sourceDatasetId": resolved.eda_authority.source_dataset_id,
                    "sourceManifestSha": resolved.eda_authority.source_manifest_sha,
                    "goldDatasetId": CURRENT_GOLD_DATASET_ID,
                    "goldManifestSha": resolved.eda_authority.gold_manifest_sha,
                    "contextualManifestSha": resolved.eda_authority.contextual_manifest_sha,
                    "authorityKey": resolved.authority_key,
                    "featureUniverseId": eligibility["featureSetId"],
                    "featureUniverseChecksum": eligibility["checksum"],
                    "splitContractId": resolved.split["contractId"],
                    "splitVersion": int(resolved.split["contractVersion"]),
                    "splitChecksum": resolved.split["checksum"],
                    "outlierPolicyId": resolved.outlier_policy["policyId"],
                    "outlierPolicyVersion": int(resolved.outlier_policy["policyVersion"]),
                    "outlierPolicyChecksum": resolved.outlier_policy["checksum"],
                    "missingPolicyId": resolved.missing_policy["policyId"],
                    "missingPolicyVersion": int(resolved.missing_policy["policyVersion"]),
                    "missingPolicyChecksum": resolved.missing_policy["checksum"],
                    "featureSetIds": sorted(
                        {str(item.get("featureSetId")) for item in candidates if item.get("featureSetId")}
                    ),
                    "planId": plan["planId"],
                    "planChecksum": plan["checksum"],
                    "targetOrder": list(GOLD_CLASS_ORDER),
                },
                "population": {
                    "scope": "DEVELOPMENT_ONLY",
                    "rows": EXPECTED_DEVELOPMENT[2],
                    "startDate": EXPECTED_DEVELOPMENT[0],
                    "endDate": EXPECTED_DEVELOPMENT[1],
                    "foldCount": 5,
                    "finalOotRows": EXPECTED_FINAL_OOT[2],
                    "finalOotLocked": True,
                    "finalOotTargetAccessed": False,
                    "finalOotScored": False,
                },
                "plan": plan,
                "environment": _environment_identity(),
                "candidates": candidates,
                "failures": failures,
                "runtimeMs": int((time.perf_counter() - started_clock) * 1000),
                "rankingMetric": "MULTICLASS_LOG_LOSS",
                "leadingCandidateLabel": "LEADING_DEVELOPMENT_CANDIDATE",
                "autoPromoted": False,
                "promotionStatus": "NOT_PROMOTED",
                "finalOotAccessed": False,
                "finalOotTargetsMaterialized": False,
                "legacyGlobalMatrixUsed": False,
                "providerCalls": 0,
            }
            persisted = _persist_run(receipt)
            row = RunRepository(database).get(job_id) or {}
            _upsert_job(
                database,
                {
                    "run_id": job_id,
                    "project_id": project_id,
                    "run_type": MODEL_DEVELOPMENT_JOB_TYPE,
                    "workflow_type": "sports_stage3_model_development",
                    "status": receipt["status"],
                    "started_at": row.get("started_at") or now_iso(),
                    "completed_at": now_iso(),
                    "parameters_json": plan,
                    "metrics_json": {
                        "state": receipt["status"],
                        "completedFits": completed_fits,
                        "failedFits": failed_fits,
                        "totalFits": plan["totalFits"],
                        "elapsedSeconds": time.perf_counter() - started_clock,
                        "estimatedRemainingSeconds": 0.0,
                        "failures": failures,
                        "message": "Immutable development evidence persisted; no model was promoted.",
                    },
                    "artifacts_json": {
                        "runId": persisted["runId"],
                        "runReceiptSha256": persisted["runReceiptSha256"],
                        "finalOotTargetAccessed": False,
                        "promotionStatus": "NOT_PROMOTED",
                    },
                    "error_json": {},
                    "created_by": actor_user_id,
                },
            )
    except LockBusy as exc:
        _finish_failed_job(database, job_id, project_id, actor_user_id, plan, "MODEL_DEVELOPMENT_LOCK_BUSY", str(exc))
    except Exception as exc:
        _finish_failed_job(
            database,
            job_id,
            project_id,
            actor_user_id,
            plan,
            getattr(exc, "code", "MODEL_DEVELOPMENT_JOB_FAILED"),
            str(exc),
        )


def _finish_failed_job(
    database: Database,
    job_id: str,
    project_id: str,
    actor_user_id: str,
    plan: Mapping[str, Any],
    code: str,
    reason: str,
) -> None:
    row = RunRepository(database).get(job_id) or {}
    _upsert_job(
        database,
        {
            "run_id": job_id,
            "project_id": project_id,
            "run_type": MODEL_DEVELOPMENT_JOB_TYPE,
            "workflow_type": "sports_stage3_model_development",
            "status": "FAILED",
            "started_at": row.get("started_at") or now_iso(),
            "completed_at": now_iso(),
            "parameters_json": plan,
            "metrics_json": json_loads(row.get("metrics_json"), {}),
            "artifacts_json": json_loads(row.get("artifacts_json"), {}),
            "error_json": {"code": code, "message": reason},
            "created_by": actor_user_id,
        },
    )


def get_model_development_job(
    database: Database, project_id: str, job_id: str
) -> dict[str, Any]:
    row = RunRepository(database).get(job_id)
    if row is None or row.get("project_id") != project_id or row.get("run_type") != MODEL_DEVELOPMENT_JOB_TYPE:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_JOB_NOT_FOUND", "The project-scoped model job does not exist.", status_code=404
        )
    return {"ok": True, "job": _decode_job(row)}


def list_model_development_jobs(database: Database, project_id: str) -> dict[str, Any]:
    rows = [
        _decode_job(row)
        for row in RunRepository(database).list_for_project(project_id)
        if row.get("run_type") == MODEL_DEVELOPMENT_JOB_TYPE
    ]
    return {"ok": True, "jobs": rows}


__all__ = [
    "MODEL_DEVELOPMENT_JOB_TYPE",
    "MODEL_DEVELOPMENT_PLAN_SCHEMA_VERSION",
    "MODEL_DEVELOPMENT_RECEIPT_SCHEMA_VERSION",
    "enqueue_model_development_job",
    "get_model_development_job",
    "list_model_development_jobs",
    "plan_model_development_queue",
]

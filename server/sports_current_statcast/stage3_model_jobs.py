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
import tempfile
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
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


MODEL_DEVELOPMENT_PLAN_SCHEMA_VERSION = "SPORTS_STAGE3_MODEL_DEVELOPMENT_PLAN_V2"
MODEL_DEVELOPMENT_JOB_TYPE = "sports_stage3_model_development"
MODEL_DEVELOPMENT_RECEIPT_SCHEMA_VERSION = "SPORTS_STAGE3_MODEL_DEVELOPMENT_RUN_RECEIPT_V2"

_ACTIVE_STATUSES = {"QUEUED", "RUNNING", "CANCEL_REQUESTED"}
_FORBIDDEN_PLAN_OPTIONS = {
    "finalOot", "holdout", "globalMatrix", "base22", "promote", "champion",
    "calibrateOnOot", "randomSplit", "provider",
}
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stage3-model-development")
_SUBMISSION_GUARD = threading.Lock()


def _physical_memory_bytes() -> int | None:
    """Return Windows physical memory without introducing a dependency."""

    try:
        import ctypes

        class _MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatus()
        status.length = ctypes.sizeof(_MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.total_physical)
    except Exception:  # pragma: no cover - informational resource evidence
        return None
    return None


def _parallelism(experiments: list[dict[str, Any]], requested: Any) -> dict[str, Any]:
    logical_cpus = max(1, int(os.cpu_count() or 1))
    memory_bytes = _physical_memory_bytes()
    memory_gib = memory_bytes / (1024**3) if memory_bytes else None
    high_memory = any(
        str(item.get("computeIntensity") or "").upper()
        in {"VERY_HIGH", "PROHIBITIVE"}
        for item in experiments
    )
    auto = 2 if logical_cpus >= 8 and (memory_gib is None or memory_gib >= 16) else 1
    if high_memory and memory_gib is not None and memory_gib < 24:
        auto = 1
    maximum = max(1, min(2, auto))
    if requested in (None, "", "AUTO"):
        mode = "AUTO"
        effective = maximum
    else:
        if isinstance(requested, bool):
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_PARALLELISM_INVALID",
                "Parallel candidate workers must be Auto, 1, or 2.",
            )
        try:
            effective = int(requested)
        except (TypeError, ValueError) as exc:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_PARALLELISM_INVALID",
                "Parallel candidate workers must be Auto, 1, or 2.",
            ) from exc
        if effective < 1 or effective > maximum:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_PARALLELISM_UNSAFE",
                f"This local resource envelope permits at most {maximum} concurrent candidate worker(s).",
            )
        mode = "MANUAL"
    return {
        "mode": mode,
        "requested": requested if requested not in (None, "") else "AUTO",
        "effectiveCandidateWorkers": effective,
        "maximumCandidateWorkers": maximum,
        "logicalCpuCount": logical_cpus,
        "physicalMemoryGiB": round(memory_gib, 2) if memory_gib is not None else None,
        "highMemoryCandidatePresent": high_memory,
        "estimatorNativeWorkers": 1,
        "nestedOversubscriptionProhibited": True,
    }


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


def _with_fold_local_selector(
    feature_set: dict[str, Any] | None,
    experiment: Mapping[str, Any],
) -> dict[str, Any] | None:
    selector = experiment.get("foldLocalSelector")
    if selector is None:
        return feature_set
    if feature_set is None or not isinstance(selector, Mapping):
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_SELECTOR_FEATURES_REQUIRED",
            "A fold-local selector requires a feature-bearing parent candidate.",
        )
    method = str(selector.get("method") or "").upper()
    if method not in {"RFE", "STABILITY_SELECTION", "COEFFICIENT_GUIDED_ELIMINATION"}:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_SELECTOR_METHOD_UNAVAILABLE",
            "Only leakage-safe fold-local RFE and coefficient-guided elimination are executable in this worker.",
            status_code=409,
        )
    features = list(feature_set.get("orderedFeatures") or [])
    minimum = int(selector.get("minimumRetainedFeatures") or 0)
    step = int(selector.get("eliminationStep") or 0)
    if not 1 <= minimum < len(features) or not 1 <= step < len(features):
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_SELECTOR_BOUNDS_INVALID",
            "The fold-local selector must preserve a non-empty reduced feature set.",
        )
    contract = {
        "schemaVersion": "SPORTS_STAGE3_FOLD_LOCAL_SELECTOR_FEATURE_SET_V1",
        "parentFeatureSetId": feature_set.get("featureSetId"),
        "parentFeatureSetChecksum": feature_set.get("checksum"),
        "orderedFeatures": features,
        "transformationContracts": feature_set.get("transformationContracts"),
        "foldLocalSelector": {
            "method": method,
            "minimumRetainedFeatures": minimum,
            "eliminationStep": step,
            "scoringMetric": "MULTICLASS_LOG_LOSS",
            "validationRowsSelectFeatures": False,
            "finalOotTargetAccessed": False,
            "refinementPlanId": selector.get("refinementPlanId"),
        },
        "finalOotTargetAccessed": False,
    }
    checksum = _sha(contract)
    return {
        **contract,
        "featureSetId": f"stage3-fold-local-reduced-challenger-{checksum[:32]}",
        "featureSetKey": "FOLD_LOCAL_REDUCED_CHALLENGER",
        "name": f"Fold-local {method.replace('_', ' ').title()} challenger",
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
        if experiment.get("foldLocalSelector") is not None:
            raise Stage3ModelLaboratoryError(
                "MODEL_DEVELOPMENT_SELECTOR_NOT_APPLICABLE",
                "The feature-independent reference cannot enter feature refinement.",
            )
        return None
    requested = str(experiment.get("featureUniverseId") or eligibility["featureSetId"])
    if requested in {"FULL_ELIGIBLE", eligibility["featureSetId"]}:
        return _with_fold_local_selector(build_feature_set_record(eligibility), experiment)
    if requested == "CUSTOM_SUBSET":
        return _with_fold_local_selector(
            _custom_feature_set(eligibility, experiment.get("orderedFeatures")),
            experiment,
        )
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
        return _with_fold_local_selector({
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
        }, experiment)
    return _with_fold_local_selector(dict(registered), experiment)


def plan_model_development_queue(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str | None = None,
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
        selector = (feature_set or {}).get("foldLocalSelector") or {}
        source_feature_count = len((feature_set or {}).get("orderedFeatures") or [])
        selector_fits_per_fold = 1
        if selector:
            selector_fits_per_fold = max(
                1,
                int(
                    (source_feature_count - int(selector["minimumRetainedFeatures"]) + int(selector["eliminationStep"]) - 1)
                    // int(selector["eliminationStep"])
                ) + 1,
            )
            tuning = {
                **tuning,
                "foldLocalSelector": dict(selector),
                "selectorFitsPerFold": selector_fits_per_fold,
                "fitsPerConfiguration": selector_fits_per_fold * 5,
                "totalFits": int(tuning["configurationCount"]) * selector_fits_per_fold * 5,
                "requiresAcknowledgement": True,
            }
        identity_payload = {
            "projectId": project_id,
            "goldDatasetId": CURRENT_GOLD_DATASET_ID,
            "goldManifestSha": resolved.eda_authority.gold_manifest_sha,
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
            "splitChecksum": resolved.split["checksum"],
            "outlierPolicyId": resolved.outlier_policy["policyId"],
            "outlierPolicyChecksum": resolved.outlier_policy["checksum"],
            "missingPolicyId": resolved.missing_policy["policyId"],
            "missingPolicyChecksum": resolved.missing_policy["checksum"],
            "environment": _environment_identity(),
            "targetOrder": list(GOLD_CLASS_ORDER),
            "parentCandidateFingerprint": raw.get("parentCandidateFingerprint"),
            "refinementPlanId": raw.get("refinementPlanId"),
            "foldLocalSelector": dict(selector) if selector else None,
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
                "candidateSpecificationTemplateSha256": _sha(identity_payload),
                "parentCandidateFingerprint": raw.get("parentCandidateFingerprint"),
                "refinementPlanId": raw.get("refinementPlanId"),
                "foldLocalSelector": dict(selector) if selector else None,
                "modelFamily": algorithm["family"],
                "algorithmId": algorithm_id,
                "algorithmLabel": algorithm["label"],
                "featureUniverseId": (feature_set or {}).get("featureSetId"),
                "featureUniverseName": (feature_set or {}).get("name") or "Feature-independent null reference",
                "featureUniverseChecksum": (feature_set or {}).get("checksum"),
                "featureCount": int(selector.get("minimumRetainedFeatures") or source_feature_count),
                "sourceFeatureCount": source_feature_count,
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
    parallelism = _parallelism(planned, payload.get("parallelWorkers", "AUTO"))
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
        "batchName": str(payload.get("batchName") or "Stage 3 multi-model development batch").strip()[:120],
        "createdByUserId": actor_user_id,
        "environment": _environment_identity(),
        "parallelism": parallelism,
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
        "environment": _environment_identity(),
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
    plan = plan_model_development_queue(
        database, project_id, payload, actor_user_id=actor_user_id
    )
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
                    current_plan = json_loads(current.get("parameters_json"), {})
                    if current_plan.get("checksum") == plan.get("checksum"):
                        return {
                            "ok": True,
                            "job": {
                                **_decode_job(current),
                                "idempotentReplay": True,
                            },
                        }
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
                            "parallelWorkers": plan["parallelism"]["effectiveCandidateWorkers"],
                            "completedConfigurations": 0,
                            "failedConfigurations": 0,
                            "remainingFits": plan["totalFits"],
                            "activeCandidates": [],
                            "completedCandidateReceipts": [],
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
    completed_configurations = 0
    failed_configurations = 0
    failures: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    candidate_receipts: list[dict[str, Any]] = []
    frames: dict[str, Any] = {}
    active_candidates: dict[str, dict[str, Any]] = {}
    progress_guard = threading.Lock()
    lock_path = _runtime_root() / "locks" / f"{project_id}.model-development.lock"
    worker_count = int((plan.get("parallelism") or {}).get("effectiveCandidateWorkers") or 1)

    def cancellation_requested() -> bool:
        row = RunRepository(database).get(job_id) or {}
        return str(row.get("status") or "").upper() == "CANCEL_REQUESTED"

    def update_progress(extra: Mapping[str, Any], *, state: str | None = None) -> None:
        elapsed = time.perf_counter() - started_clock
        finished = completed_fits + failed_fits
        mean = elapsed / finished if finished else None
        remaining_fits = max(0, int(plan["totalFits"]) - finished)
        remaining = mean * remaining_fits if mean is not None else None
        row = RunRepository(database).get(job_id) or {}
        row_status = str(row.get("status") or "").upper()
        effective_state = state or (
            "CANCEL_REQUESTED" if row_status == "CANCEL_REQUESTED" else "RUNNING"
        )
        _upsert_job(
            database,
            {
                "run_id": job_id,
                "project_id": project_id,
                "run_type": MODEL_DEVELOPMENT_JOB_TYPE,
                "workflow_type": "sports_stage3_model_development",
                "status": effective_state,
                "started_at": row.get("started_at") or now_iso(),
                "completed_at": None,
                "parameters_json": plan,
                "metrics_json": {
                    "state": effective_state,
                    "completedConfigurations": completed_configurations,
                    "failedConfigurations": failed_configurations,
                    "completedFits": completed_fits,
                    "failedFits": failed_fits,
                    "remainingFits": remaining_fits,
                    "totalFits": plan["totalFits"],
                    "parallelWorkers": worker_count,
                    "activeCandidates": list(active_candidates.values()),
                    "completedCandidateReceipts": list(candidate_receipts),
                    "elapsedSeconds": elapsed,
                    "estimatedRemainingSeconds": remaining,
                    "failures": list(failures),
                    **dict(extra),
                },
                "artifacts_json": {
                    **json_loads(row.get("artifacts_json"), {}),
                    "completedCandidateReceipts": list(candidate_receipts),
                },
                "error_json": {},
                "created_by": actor_user_id,
            },
        )

    def persist_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
        payload = {
            "schemaVersion": "SPORTS_STAGE3_CANDIDATE_ATTEMPT_RECEIPT_V1",
            "jobId": job_id,
            "projectId": project_id,
            "planId": plan["planId"],
            "planChecksum": plan["checksum"],
            "createdAt": now_iso(),
            "candidate": dict(candidate),
            "finalOotTargetAccessed": False,
            "promotionStatus": "NOT_PROMOTED",
        }
        digest = _sha(payload)
        directory = _runtime_root() / "candidate-attempts" / "objects" / "sha256"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{digest}.json"
        serialized = canonical_json_bytes(payload)
        if path.exists():
            if path.read_bytes() != serialized:
                raise Stage3ModelLaboratoryError(
                    "MODEL_DEVELOPMENT_CANDIDATE_OBJECT_COLLISION",
                    "A candidate attempt address contains different bytes.",
                    status_code=409,
                )
        else:
            handle, temporary = tempfile.mkstemp(prefix="stage3-candidate-", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(serialized)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return {
            "candidateId": candidate.get("candidateId"),
            "candidateReceiptSha256": digest,
            "status": candidate.get("status"),
        }

    try:
        with interprocess_lock(lock_path, blocking=False, stale_after=86_400.0):
            resolved = resolve_model_lab_authority(database, project_id)
            eligibility = build_model_eligibility(resolved)
            _assert_plan_current(resolved, eligibility, plan)
            with progress_guard:
                update_progress({"message": "Exact project, feature, treatment, split, and environment authorities verified."})

            tasks: list[dict[str, Any]] = []
            for experiment_index, experiment in enumerate(plan["experiments"], start=1):
                feature_set = experiment.get("featureSetContract")
                feature_key = str((feature_set or {}).get("featureSetId") or "NOT_APPLICABLE")
                if feature_key not in frames:
                    frames[feature_key] = _fold_frame(
                        resolved, list((feature_set or {}).get("orderedFeatures") or [])
                    )
                configurations = list((experiment.get("tuning") or {}).get("configurations") or [])
                for config_index, hyperparameters in enumerate(configurations, start=1):
                    tasks.append(
                        {
                            "taskId": f"{experiment['experimentId']}:{config_index}",
                            "experimentIndex": experiment_index,
                            "experiment": experiment,
                            "featureSet": feature_set,
                            "frame": frames[feature_key],
                            "configurationIndex": config_index,
                            "configurationCount": len(configurations),
                            "hyperparameters": hyperparameters,
                        }
                    )

            def execute_candidate(task: Mapping[str, Any]) -> dict[str, Any]:
                nonlocal completed_fits
                experiment = task["experiment"]
                config_fits = 0
                config_folds = 0

                def on_fold(event: dict[str, Any]) -> None:
                    nonlocal completed_fits, config_fits, config_folds
                    with progress_guard:
                        if event.get("event") in {"FOLD_SELECTOR_FIT_COMPLETED", "FOLD_COMPLETED"}:
                            completed_fits += 1
                            config_fits += 1
                        if event.get("event") == "FOLD_COMPLETED":
                            config_folds += 1
                        active_candidates[str(task["taskId"])] = {
                            "taskId": task["taskId"],
                            "algorithm": experiment["algorithmId"],
                            "algorithmLabel": experiment["algorithmLabel"],
                            "featureUniverse": experiment["featureUniverseName"],
                            "configuration": task["configurationIndex"],
                            "configurationCount": task["configurationCount"],
                            "hyperparameters": task["hyperparameters"],
                            "fold": event.get("fold"),
                            "foldCount": 5,
                            "status": event.get("event"),
                            "elapsedSeconds": time.perf_counter() - started_clock,
                        }
                        update_progress(
                            {
                                "message": f"{experiment['algorithmLabel']} · configuration {task['configurationIndex']}/{task['configurationCount']} · fold {event.get('fold')}/5",
                            }
                        )

                try:
                    result = _evaluate_candidate(
                        task["frame"],
                        model_family=str(experiment["algorithmId"]),
                        feature_set=task["featureSet"],
                        split=resolved.split,
                        seed=int(experiment["seed"]),
                        hyperparameters=task["hyperparameters"],
                        fold_local_selector=experiment.get("foldLocalSelector"),
                        progress_callback=on_fold,
                    )
                    result["experimentId"] = experiment["experimentId"]
                    result["candidateSpecificationTemplateSha256"] = experiment[
                        "candidateSpecificationTemplateSha256"
                    ]
                    result["tuningMode"] = experiment["tuning"]["tuningMode"]
                    result["gridPreset"] = experiment["tuning"]["gridPreset"]
                    result["configurationIndex"] = task["configurationIndex"]
                    result["developmentLabel"] = "DEVELOPMENT_CANDIDATE"
                    result["parentCandidateFingerprint"] = experiment.get("parentCandidateFingerprint")
                    result["refinementPlanId"] = experiment.get("refinementPlanId")
                    return {"ok": True, "candidate": result, "completedFits": config_fits, "completedFolds": config_folds}
                except Exception as exc:  # one configuration cannot erase siblings
                    return {
                        "ok": False,
                        "error": exc,
                        "completedFits": config_fits,
                        "completedFolds": config_folds,
                        "task": task,
                    }

            task_iter = iter(tasks)
            in_flight: dict[Future[dict[str, Any]], dict[str, Any]] = {}
            cancelled_tasks: list[dict[str, Any]] = []
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix=f"stage3-candidate-{project_id}",
            ) as candidate_pool:
                def submit_next() -> bool:
                    if cancellation_requested():
                        return False
                    try:
                        task = next(task_iter)
                    except StopIteration:
                        return False
                    future = candidate_pool.submit(execute_candidate, task)
                    in_flight[future] = task
                    with progress_guard:
                        active_candidates[str(task["taskId"])] = {
                            "taskId": task["taskId"],
                            "algorithm": task["experiment"]["algorithmId"],
                            "algorithmLabel": task["experiment"]["algorithmLabel"],
                            "featureUniverse": task["experiment"]["featureUniverseName"],
                            "configuration": task["configurationIndex"],
                            "configurationCount": task["configurationCount"],
                            "hyperparameters": task["hyperparameters"],
                            "fold": 0,
                            "foldCount": 5,
                            "status": "QUEUED_TO_WORKER",
                            "elapsedSeconds": 0.0,
                        }
                        update_progress({"message": f"Running up to {worker_count} independent candidate configuration(s) concurrently."})
                    return True

                for _ in range(worker_count):
                    if not submit_next():
                        break
                while in_flight:
                    done, _ = wait(tuple(in_flight), return_when=FIRST_COMPLETED)
                    for future in done:
                        task = in_flight.pop(future)
                        outcome = future.result()
                        with progress_guard:
                            active_candidates.pop(str(task["taskId"]), None)
                            if outcome["ok"]:
                                candidate = outcome["candidate"]
                                completed_configurations += 1
                            else:
                                exc = outcome["error"]
                                expected_fits = int((task["experiment"].get("tuning") or {}).get("fitsPerConfiguration") or 5)
                                uncounted = expected_fits - int(outcome["completedFits"])
                                failed_fits += uncounted
                                failed_configurations += 1
                                experiment = task["experiment"]
                                failure = {
                                    "experimentId": experiment["experimentId"],
                                    "algorithmId": experiment["algorithmId"],
                                    "configurationIndex": task["configurationIndex"],
                                    "hyperparameters": task["hyperparameters"],
                                    "errorCode": getattr(exc, "code", "MODEL_DEVELOPMENT_CONFIGURATION_FAILED"),
                                    "reason": str(exc),
                                    "failedFits": uncounted,
                                }
                                failures.append(failure)
                                candidate = {
                                    "candidateId": "stage3-candidate-" + uuid.uuid4().hex,
                                    "experimentId": experiment["experimentId"],
                                    "candidateSpecificationTemplateSha256": experiment["candidateSpecificationTemplateSha256"],
                                    "modelFamily": experiment["algorithmId"],
                                    "hyperparameters": task["hyperparameters"],
                                    "featureSetId": experiment["featureUniverseId"],
                                    "featureSetName": experiment["featureUniverseName"],
                                    "featureSetChecksum": experiment["featureUniverseChecksum"],
                                    "featureCount": experiment["featureCount"],
                                    "tuningMode": experiment["tuning"]["tuningMode"],
                                    "gridPreset": experiment["tuning"]["gridPreset"],
                                    "configurationIndex": task["configurationIndex"],
                                    "status": "FAILED",
                                    "foldsCompleted": int(outcome.get("completedFolds") or 0),
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
                            candidates.append(candidate)
                            candidate_receipts.append(persist_candidate(candidate))
                            update_progress(
                                {
                                    "message": (
                                        f"Persisted immutable candidate evidence for {candidate['modelFamily']}."
                                        if candidate["status"] == "COMPLETE"
                                        else f"Candidate failed closed: {candidate['errorReason']}"
                                    )
                                }
                            )
                        if not cancellation_requested():
                            submit_next()

                # Anything never submitted is safely cancelled; no claim is
                # made that a running estimator was interrupted.
                if cancellation_requested():
                    cancelled_tasks.extend(list(task_iter))

            completed = [item for item in candidates if item.get("status") == "COMPLETE"]
            cancelled_fits = sum(
                int((task["experiment"].get("tuning") or {}).get("fitsPerConfiguration") or 5)
                for task in cancelled_tasks
            )
            if cancelled_tasks:
                receipt_status = "CANCELLED_PARTIAL" if candidates else "CANCELLED"
            else:
                receipt_status = "COMPLETE" if len(completed) == len(candidates) else "PARTIAL"
            receipt = {
                "schemaVersion": MODEL_DEVELOPMENT_RECEIPT_SCHEMA_VERSION,
                "runId": "stage3-model-development-run-" + uuid.uuid4().hex,
                "createdAt": now_iso(),
                "createdByUserId": actor_user_id,
                "status": receipt_status,
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
                "cancelledUnstartedConfigurations": [
                    {
                        "experimentId": task["experiment"]["experimentId"],
                        "algorithmId": task["experiment"]["algorithmId"],
                        "configurationIndex": task["configurationIndex"],
                        "hyperparameters": task["hyperparameters"],
                    }
                    for task in cancelled_tasks
                ],
                "candidateAttemptReceipts": candidate_receipts,
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
                        "cancelledFits": cancelled_fits,
                        "completedConfigurations": completed_configurations,
                        "failedConfigurations": failed_configurations,
                        "cancelledConfigurations": len(cancelled_tasks),
                        "totalFits": plan["totalFits"],
                        "remainingFits": 0,
                        "parallelWorkers": worker_count,
                        "activeCandidates": [],
                        "completedCandidateReceipts": candidate_receipts,
                        "elapsedSeconds": time.perf_counter() - started_clock,
                        "estimatedRemainingSeconds": 0.0,
                        "failures": failures,
                        "message": (
                            "Unstarted work was cancelled; completed immutable evidence was preserved and no running fit was represented as interrupted."
                            if cancelled_tasks
                            else "Immutable development evidence persisted; no model was promoted."
                        ),
                    },
                    "artifacts_json": {
                        "runId": persisted["runId"],
                        "runReceiptSha256": persisted["runReceiptSha256"],
                        "finalOotTargetAccessed": False,
                        "promotionStatus": "NOT_PROMOTED",
                        "completedCandidateReceipts": candidate_receipts,
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


def cancel_unstarted_model_development_work(
    database: Database,
    project_id: str,
    job_id: str,
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    """Request cancellation of work not yet assigned to a candidate worker.

    Running estimators are deliberately allowed to finish so the UI never
    claims an unsafe interruption.  Their evidence remains immutable.
    """

    row = RunRepository(database).get(job_id)
    if row is None or row.get("project_id") != project_id or row.get("run_type") != MODEL_DEVELOPMENT_JOB_TYPE:
        raise Stage3ModelLaboratoryError(
            "MODEL_DEVELOPMENT_JOB_NOT_FOUND",
            "The project-scoped model job does not exist.",
            status_code=404,
        )
    status = str(row.get("status") or "").upper()
    if status not in _ACTIVE_STATUSES:
        return {"ok": True, "job": {**_decode_job(row), "idempotentReplay": True}}
    progress = json_loads(row.get("metrics_json"), {})
    progress.update(
        {
            "state": "CANCEL_REQUESTED",
            "cancelUnstartedRequested": True,
            "cancelRequestedAt": now_iso(),
            "message": "Queued or unstarted configurations will be cancelled. Active fits are allowed to finish and reconcile their immutable evidence.",
        }
    )
    updated = _upsert_job(
        database,
        {
            "run_id": job_id,
            "project_id": project_id,
            "run_type": MODEL_DEVELOPMENT_JOB_TYPE,
            "workflow_type": row.get("workflow_type") or "sports_stage3_model_development",
            "status": "CANCEL_REQUESTED",
            "started_at": row.get("started_at") or now_iso(),
            "completed_at": None,
            "parameters_json": json_loads(row.get("parameters_json"), {}),
            "metrics_json": progress,
            "artifacts_json": json_loads(row.get("artifacts_json"), {}),
            "error_json": {},
            "created_by": row.get("created_by") or actor_user_id,
        },
    )
    return {"ok": True, "job": _decode_job(updated)}


__all__ = [
    "MODEL_DEVELOPMENT_JOB_TYPE",
    "MODEL_DEVELOPMENT_PLAN_SCHEMA_VERSION",
    "MODEL_DEVELOPMENT_RECEIPT_SCHEMA_VERSION",
    "enqueue_model_development_job",
    "cancel_unstarted_model_development_work",
    "get_model_development_job",
    "list_model_development_jobs",
    "plan_model_development_queue",
]

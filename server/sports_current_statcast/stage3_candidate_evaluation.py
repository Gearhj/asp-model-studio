"""Project-bound Stage 3 candidate comparison, finalists, and refinement plans.

This module is intentionally read-mostly.  It derives comparison groups from
verified immutable Model Laboratory receipts and stores only explicit scientist
decisions or analysis/refinement requests in the existing ``run_records``
ledger.  It never reads the final OOT population, fits on page load, promotes a
model, or falls back to a legacy/global matrix.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from ..persistence.db import Database, json_loads, now_iso
from ..persistence.repositories.run_repository import RunRepository
from ..sports_datasets.consumer import canonical_json_bytes
from ..sports_gold.contracts import GOLD_CLASS_ORDER
from .stage3_model_catalog import model_catalog
from .stage3_model_eligibility import build_model_eligibility
from .stage3_model_jobs import (
    MODEL_DEVELOPMENT_JOB_TYPE,
    MODEL_DEVELOPMENT_PLAN_SCHEMA_VERSION,
    enqueue_model_development_job,
    plan_model_development_queue,
)
from .stage3_model_laboratory import (
    CURRENT_GOLD_DATASET_ID,
    EXPECTED_DEVELOPMENT,
    EXPECTED_FINAL_OOT,
    RUN_RECEIPT_SCHEMA_VERSION,
    RUN_RECEIPT_SCHEMA_VERSION_V2,
    Stage3ModelLaboratoryError,
    _read_runs,
    _runtime_root,
    resolve_model_lab_authority,
)


EVALUATION_SCHEMA_VERSION = "SPORTS_STAGE3_PROJECT_CANDIDATE_EVALUATION_V1"
FINALIST_RECEIPT_SCHEMA_VERSION = "SPORTS_STAGE3_FINALIST_SELECTION_RECEIPT_V1"
REFINEMENT_PLAN_SCHEMA_VERSION = "SPORTS_STAGE3_REFINEMENT_PLAN_V1"
ANALYSIS_RECEIPT_SCHEMA_VERSION = "SPORTS_STAGE3_EXPLICIT_ANALYSIS_RECEIPT_V1"
FINALIST_RUN_TYPE = "sports_stage3_finalist_selection"
REFINEMENT_RUN_TYPE = "sports_stage3_model_refinement"
ANALYSIS_RUN_TYPE = "sports_stage3_candidate_analysis"
INCREMENTAL_RECEIPT_SCHEMA_VERSION = "SPORTS_STAGE3_CANDIDATE_ATTEMPT_RECEIPT_V1"

_METRIC_KEYS = (
    "meanOofLogLoss",
    "summedBrier",
    "ece",
    "macroF1Diagnostic",
    "accuracyDiagnostic",
    "runtimeMs",
)
_ANALYSIS_KINDS = {"PERMUTATION_IMPORTANCE", "SHAP", "SENSITIVITY"}
_REFINEMENT_METHODS = {
    "RFE",
    "RFECV",
    "COEFFICIENT_GUIDED_ELIMINATION",
    "PERMUTATION_GUIDED_ELIMINATION",
    "SHAP_GUIDED_CANDIDATE",
    "FEATURE_FAMILY_ABLATION",
    "REDUNDANCY_PRUNING",
    "STABILITY_SELECTION",
}
_EVIDENCE_SOURCES = {
    "CURRENT_BATCH",
    "HISTORICAL_BASELINE",
    "INCREMENTAL_CURRENT_EVIDENCE",
}


def _sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _evidence_shape_error(message: str) -> Stage3ModelLaboratoryError:
    return Stage3ModelLaboratoryError(
        "STAGE3_CANDIDATE_EVIDENCE_SHAPE_INVALID",
        message,
        status_code=409,
    )


def _mapping_sequence(value: Any, *, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise _evidence_shape_error(f"{label} must be a JSON array of objects.")
    return list(value)


def _strict_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _persist_object(kind: str, value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    digest = _sha(payload)
    directory = _runtime_root() / kind / "objects" / "sha256"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}.json"
    serialized = canonical_json_bytes(payload)
    if path.exists():
        if path.read_bytes() != serialized:
            raise Stage3ModelLaboratoryError(
                "STAGE3_EVIDENCE_OBJECT_COLLISION",
                "A content-addressed Stage 3 evidence object contains different bytes.",
                status_code=409,
            )
    else:
        handle, temporary = tempfile.mkstemp(prefix=f"{kind}-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {**payload, "receiptSha256": digest}


def _experiment_for_candidate(run: Mapping[str, Any], candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    experiment_id = candidate.get("experimentId")
    raw_plan = run.get("plan")
    if raw_plan is None:
        return {}
    if not isinstance(raw_plan, Mapping):
        raise _evidence_shape_error("The candidate run plan must be a JSON object.")
    raw_experiments = raw_plan.get("experiments")
    if raw_experiments is None:
        return {}
    for experiment in _mapping_sequence(
        raw_experiments, label="The candidate run experiments"
    ):
        if experiment.get("experimentId") == experiment_id:
            return experiment
    return {}


def candidate_specification_payload(
    run: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the canonical scientific identity for one candidate attempt."""

    identity = run.get("identity") or {}
    if not isinstance(identity, Mapping):
        raise _evidence_shape_error("The candidate run identity must be a JSON object.")
    experiment = _experiment_for_candidate(run, candidate)
    feature_contract = experiment.get("featureSetContract") or {}
    if not isinstance(feature_contract, Mapping):
        raise _evidence_shape_error("The candidate feature-set contract must be a JSON object.")
    feature_checksum = candidate.get("featureSetChecksum") or experiment.get(
        "featureUniverseChecksum"
    )
    ordered_features = candidate.get("orderedFeatures")
    if ordered_features is None:
        ordered_features = feature_contract.get("orderedFeatures")
    if ordered_features is not None and not isinstance(ordered_features, list):
        raise _evidence_shape_error("Candidate orderedFeatures must be a JSON array.")
    ordered_identity = (
        _sha({"orderedFeatures": list(ordered_features or [])})
        if ordered_features is not None
        else feature_checksum
    )
    seed = experiment.get("seed", identity.get("seed"))
    environment = run.get("environment") or {}
    if not isinstance(environment, Mapping):
        raise _evidence_shape_error("The candidate run environment must be a JSON object.")
    hyperparameters = candidate.get("hyperparameters") or {}
    if not isinstance(hyperparameters, Mapping):
        raise _evidence_shape_error("Candidate hyperparameters must be a JSON object.")
    target_order = identity.get("targetOrder") or []
    if not isinstance(target_order, list):
        raise _evidence_shape_error("The candidate target order must be a JSON array.")
    return {
        "projectId": identity.get("projectId"),
        "goldDatasetId": identity.get("goldDatasetId"),
        "goldManifestSha": identity.get("goldManifestSha"),
        "splitContractId": identity.get("splitContractId"),
        "splitChecksum": identity.get("splitChecksum"),
        "featureSetId": candidate.get("featureSetId"),
        "featureSetChecksum": feature_checksum,
        "orderedFeatureIdentity": ordered_identity,
        "algorithmId": candidate.get("modelFamily"),
        "hyperparameters": dict(hyperparameters),
        "seed": seed,
        "outlierPolicyId": identity.get("outlierPolicyId"),
        "outlierPolicyChecksum": identity.get("outlierPolicyChecksum"),
        "missingPolicyId": identity.get("missingPolicyId"),
        "missingPolicyChecksum": identity.get("missingPolicyChecksum"),
        "codeEnvironment": dict(environment),
        "targetOrder": list(target_order),
        "parentCandidateFingerprint": experiment.get("parentCandidateFingerprint"),
        "refinementPlanId": experiment.get("refinementPlanId"),
    }


def candidate_specification_fingerprint(
    run: Mapping[str, Any], candidate: Mapping[str, Any]
) -> str:
    return "stage3-candidate-spec-" + _sha(
        candidate_specification_payload(run, candidate)
    )


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def _attempt_result_payload(candidate: Mapping[str, Any]) -> dict[str, Any]:
    folds = []
    raw_folds = candidate.get("folds")
    if raw_folds is None:
        raw_folds = []
    for fold in _mapping_sequence(raw_folds, label="Candidate folds"):
        raw_metrics = fold.get("metrics")
        if raw_metrics is None:
            raw_metrics = {}
        if not isinstance(raw_metrics, Mapping):
            raise _evidence_shape_error("Candidate fold metrics must be a JSON object.")
        metrics = raw_metrics
        folds.append(
            {
                "foldNumber": fold.get("foldNumber"),
                "multiclassLogLoss": _finite(metrics.get("multiclassLogLoss")),
                "summedBrier": _finite(metrics.get("summedBrier")),
                "ece": _finite(metrics.get("ece")),
                "accuracy": _finite(metrics.get("accuracy")),
                "macroF1": _finite(metrics.get("macroF1")),
            }
        )
    return {
        "status": candidate.get("status"),
        "metrics": {key: _finite(candidate.get(key)) for key in _METRIC_KEYS[:-1]},
        "folds": folds,
        "errorCode": candidate.get("errorCode"),
        "errorReason": candidate.get("errorReason"),
    }


def _materially_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if left.get("status") != right.get("status"):
        return False
    if left.get("status") != "COMPLETE":
        return left.get("errorCode") == right.get("errorCode") and left.get(
            "errorReason"
        ) == right.get("errorReason")
    left_metrics = left.get("metrics") or {}
    right_metrics = right.get("metrics") or {}
    for key in set(left_metrics) | set(right_metrics):
        a, b = left_metrics.get(key), right_metrics.get(key)
        if a is None or b is None:
            if a != b:
                return False
        elif not np.isclose(float(a), float(b), rtol=0.0, atol=1e-12):
            return False
    return left.get("folds") == right.get("folds")


def _attempt(run: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    schema = str(run.get("schemaVersion") or "")
    override_source = run.get("_evidenceSource")
    if override_source is not None:
        source = str(override_source)
        if source != "INCREMENTAL_CURRENT_EVIDENCE":
            raise _evidence_shape_error("The candidate run has an invalid evidence-source override.")
    elif schema == RUN_RECEIPT_SCHEMA_VERSION_V2:
        source = "CURRENT_BATCH"
    elif schema == RUN_RECEIPT_SCHEMA_VERSION:
        source = "HISTORICAL_BASELINE"
    else:
        raise _evidence_shape_error("The candidate run has an unsupported receipt schema.")
    if source not in _EVIDENCE_SOURCES:
        raise _evidence_shape_error("The candidate run has an unsupported evidence source.")
    experiment = _experiment_for_candidate(run, candidate)
    return {
        "attemptId": candidate.get("candidateId"),
        "candidateFingerprint": candidate_specification_fingerprint(run, candidate),
        "runId": run.get("runId"),
        "runReceiptSha256": run.get("runReceiptSha256"),
        "receiptSchemaVersion": schema,
        "evidenceSource": source,
        "createdAt": run.get("createdAt"),
        "status": candidate.get("status"),
        "modelFamily": candidate.get("modelFamily"),
        "featureSetId": candidate.get("featureSetId"),
        "featureSetName": candidate.get("featureSetName"),
        "featureSetChecksum": candidate.get("featureSetChecksum") or experiment.get("featureUniverseChecksum"),
        "featureCount": candidate.get("featureCount"),
        "hyperparameters": candidate.get("hyperparameters") or {},
        "tuningMode": candidate.get("tuningMode") or "FIXED_HISTORICAL",
        "gridPreset": candidate.get("gridPreset") or "HISTORICAL_BASELINE",
        "seed": experiment.get("seed", (run.get("identity") or {}).get("seed")),
        "foldsCompleted": candidate.get("foldsCompleted", 0),
        "meanOofLogLoss": _finite(candidate.get("meanOofLogLoss")),
        "foldStandardDeviation": _finite(
            (candidate.get("foldStability") or {}).get("logLossStdDev")
            if isinstance(candidate.get("foldStability"), Mapping)
            else candidate.get("foldStability")
        ),
        "summedBrier": _finite(candidate.get("summedBrier")),
        "ece": _finite(candidate.get("ece")),
        "macroF1": _finite(candidate.get("macroF1Diagnostic", candidate.get("macroF1"))),
        "accuracy": _finite(candidate.get("accuracyDiagnostic")),
        "runtimeMs": _finite(candidate.get("runtimeMs")),
        "errorCode": candidate.get("errorCode"),
        "errorReason": candidate.get("errorReason"),
        "folds": candidate.get("folds") or [],
        "classCalibration": candidate.get("classCalibration") or candidate.get("classCalibrationDiagnostics") or [],
        "modelComplexity": candidate.get("modelComplexity"),
        "interpretabilityEvidence": candidate.get("interpretabilityEvidence"),
        "evaluationEvidence": candidate.get("evaluationEvidence"),
        "orderedFeatures": list(candidate.get("orderedFeatures") or (experiment.get("featureSetContract") or {}).get("orderedFeatures") or []),
        "refinementEvidence": candidate.get("refinementEvidence"),
        "resultFingerprint": _sha(_attempt_result_payload(candidate)),
    }


def _group_attempts(runs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        if not isinstance(run, Mapping):
            raise _evidence_shape_error("A candidate run must be a JSON object.")
        raw_candidates = run.get("candidates")
        if raw_candidates is None:
            raw_candidates = []
        for candidate in _mapping_sequence(
            raw_candidates, label="Candidate run candidates"
        ):
            attempt = _attempt(run, candidate)
            groups[attempt["candidateFingerprint"]].append(attempt)

    rows: list[dict[str, Any]] = []
    for fingerprint, attempts in groups.items():
        attempts.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
        completed = [item for item in attempts if item["status"] == "COMPLETE"]
        failed = [item for item in attempts if item["status"] != "COMPLETE"]
        result_payloads = [
            _attempt_result_payload(
                {
                    **item,
                    "macroF1Diagnostic": item.get("macroF1"),
                    "accuracyDiagnostic": item.get("accuracy"),
                }
            )
            for item in attempts
        ]
        if len(attempts) == 1:
            reproducibility = "SINGLE_ATTEMPT"
        elif all(_materially_equal(result_payloads[0], item) for item in result_payloads[1:]):
            reproducibility = "REPRODUCED"
        else:
            reproducibility = "REPRODUCIBILITY_REVIEW_REQUIRED"
        representative = completed[0] if completed else attempts[0]
        complete_values = [item["meanOofLogLoss"] for item in completed if item["meanOofLogLoss"] is not None]
        aggregate_log_loss = float(np.mean(complete_values)) if complete_values else None
        rows.append(
            {
                "candidateFingerprint": fingerprint,
                "modelFamily": representative["modelFamily"],
                "featureSetId": representative["featureSetId"],
                "featureSetName": representative["featureSetName"],
                "featureCount": representative["featureCount"],
                "hyperparameters": representative["hyperparameters"],
                "tuningMode": representative["tuningMode"],
                "gridPreset": representative["gridPreset"],
                "status": "COMPLETE" if completed else "FAILED",
                "attemptCount": len(attempts),
                "completedAttemptCount": len(completed),
                "failedAttemptCount": len(failed),
                "reproducibilityStatus": reproducibility,
                "rankingEligible": bool(completed) and reproducibility != "REPRODUCIBILITY_REVIEW_REQUIRED",
                "evidenceSources": sorted({item["evidenceSource"] for item in attempts}),
                "meanOofLogLoss": aggregate_log_loss,
                "foldStandardDeviation": representative["foldStandardDeviation"],
                "summedBrier": representative["summedBrier"],
                "ece": representative["ece"],
                "macroF1": representative["macroF1"],
                "accuracy": representative["accuracy"],
                "runtimeMs": representative["runtimeMs"],
                "foldsCompleted": representative["foldsCompleted"],
                "immutableEvidenceIdentity": representative["runReceiptSha256"],
                "representativeAttemptId": representative["attemptId"],
                "attempts": attempts,
            }
        )
    return _rank_group_rows(rows)


def _rank_group_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows.sort(
        key=lambda item: (
            item["status"] != "COMPLETE",
            item["meanOofLogLoss"] if item["meanOofLogLoss"] is not None else float("inf"),
            str(item["modelFamily"]),
            str(item["featureSetName"]),
        )
    )
    rank = 0
    for row in rows:
        if row["rankingEligible"]:
            rank += 1
            row["rank"] = rank
            row["developmentLabel"] = "LEADING_DEVELOPMENT_CANDIDATE" if rank == 1 else "DEVELOPMENT_CANDIDATE"
        else:
            row["rank"] = None
            row["developmentLabel"] = "REPRODUCIBILITY_REVIEW_REQUIRED" if row["status"] == "COMPLETE" else "FAILED_CANDIDATE"
    return rows


def _decision_rows(database: Database, project_id: str, run_type: str) -> list[dict[str, Any]]:
    return [
        row
        for row in RunRepository(database).list_for_project(project_id)
        if row.get("run_type") == run_type
    ]


def _incremental_diagnostic(code: str, message: str, receipt: Any = None) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "candidateReceiptSha256": receipt,
    }


def _incremental_held_closed(
    row: Mapping[str, Any],
    plan_id: Any,
    diagnostic: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "status": "HELD_CLOSED",
        "jobId": row.get("run_id"),
        "planId": plan_id,
        "candidateGroups": [],
        "verifiedCandidateReceipts": 0,
        "heldClosedReceipts": 1,
        "diagnostics": [dict(diagnostic)],
        "rankingEligible": False,
        "finalistSelectionEligible": False,
    }


def _incremental_candidate_matches_plan(
    candidate: Mapping[str, Any],
    experiment: Mapping[str, Any],
) -> bool:
    """Bind an independently persisted candidate to every planned science field."""

    status = str(candidate.get("status") or "")
    tuning = experiment.get("tuning")
    if not isinstance(tuning, Mapping):
        return False
    configurations = tuning.get("configurations")
    if not isinstance(configurations, list) or any(
        not isinstance(item, Mapping) for item in configurations
    ):
        return False
    configuration_index = _strict_int(candidate.get("configurationIndex"))
    if configuration_index is None or not 1 <= configuration_index <= len(configurations):
        return False
    expected_configuration = configurations[configuration_index - 1]
    hyperparameters = candidate.get("hyperparameters")
    expected_resources = experiment.get("executionResources")
    candidate_resources = candidate.get("executionResources")
    if (
        not isinstance(hyperparameters, Mapping)
        or not isinstance(expected_resources, Mapping)
        or not isinstance(candidate_resources, Mapping)
    ):
        return False

    expected_count = _strict_int(experiment.get("featureCount"))
    expected_source_count = _strict_int(experiment.get("sourceFeatureCount"))
    candidate_count = _strict_int(candidate.get("featureCount"))
    feature_contract = experiment.get("featureSetContract")
    if feature_contract is None:
        feature_contract = {}
    if not isinstance(feature_contract, Mapping):
        return False
    planned_features = feature_contract.get("orderedFeatures") or []
    if not isinstance(planned_features, list):
        return False

    selector = experiment.get("foldLocalSelector")
    if selector is not None and not isinstance(selector, Mapping):
        return False
    refinement = candidate.get("refinementEvidence")
    if status == "COMPLETE" and selector:
        if not isinstance(refinement, Mapping):
            return False
        stable_features = refinement.get("stableRetainedFeatures")
        if not isinstance(stable_features, list):
            return False
        expected_feature_id = refinement.get("reducedFeatureSetId")
        expected_feature_name = "Stable fold-local reduced challenger"
        expected_feature_checksum = refinement.get("reducedFeatureSetChecksum")
        expected_features = stable_features
        refinement_valid = (
            refinement.get("status") == "FOLD_LOCAL_SELECTION_COMPLETE"
            and refinement.get("method") == selector.get("method")
            and refinement.get("validationRowsUsedForSelection") == 0
            and refinement.get("finalOotTargetAccessed") is False
            and len(stable_features) == expected_count
        )
    else:
        expected_feature_id = experiment.get("featureUniverseId")
        expected_feature_name = experiment.get("featureUniverseName")
        expected_feature_checksum = experiment.get("featureUniverseChecksum")
        expected_features = planned_features
        refinement_valid = refinement is None

    complete_shape_valid = True
    if status == "COMPLETE":
        raw_folds = candidate.get("folds")
        if not isinstance(raw_folds, list) or any(
            not isinstance(fold, Mapping) for fold in raw_folds
        ):
            complete_shape_valid = False
        else:
            fold_numbers = [_strict_int(fold.get("foldNumber")) for fold in raw_folds]
            complete_shape_valid = fold_numbers == [1, 2, 3, 4, 5] and all(
                isinstance(fold.get("metrics"), Mapping) for fold in raw_folds
            )
            if complete_shape_valid:
                complete_shape_valid = all(
                    all(
                        _finite(fold["metrics"].get(key)) is not None
                        for key in (
                            "multiclassLogLoss",
                            "summedBrier",
                            "ece",
                            "accuracy",
                            "macroF1",
                        )
                    )
                    for fold in raw_folds
                )
        complete_shape_valid = (
            complete_shape_valid
            and _strict_int(candidate.get("foldsCompleted")) == 5
            and isinstance(candidate.get("orderedFeatures"), list)
            and candidate.get("orderedFeatures") == expected_features
            and _strict_int(candidate.get("sourceFeatureCount")) == expected_source_count
            and all(
                _finite(candidate.get(key)) is not None for key in _METRIC_KEYS[:-1]
            )
        )
    elif status == "FAILED":
        raw_folds = candidate.get("folds")
        complete_shape_valid = isinstance(raw_folds, list) and all(
            isinstance(fold, Mapping) for fold in raw_folds
        )
    else:
        return False

    return bool(
        candidate.get("candidateSpecificationTemplateSha256")
        == experiment.get("candidateSpecificationTemplateSha256")
        and candidate.get("modelFamily") == experiment.get("algorithmId")
        and dict(hyperparameters) == dict(expected_configuration)
        and candidate.get("tuningMode") == tuning.get("tuningMode")
        and candidate.get("gridPreset") == tuning.get("gridPreset")
        and dict(candidate_resources) == dict(expected_resources)
        and candidate.get("featureSetId") == expected_feature_id
        and candidate.get("featureSetName") == expected_feature_name
        and candidate.get("featureSetChecksum") == expected_feature_checksum
        and candidate_count == expected_count
        and expected_count is not None
        and expected_source_count is not None
        and refinement_valid
        and complete_shape_valid
    )


def _incremental_experiment_shape_valid(experiment: Mapping[str, Any]) -> bool:
    tuning = experiment.get("tuning")
    feature_contract = experiment.get("featureSetContract")
    selector = experiment.get("foldLocalSelector")
    if not isinstance(tuning, Mapping):
        return False
    configurations = tuning.get("configurations")
    return bool(
        str(experiment.get("experimentId") or "")
        and str(experiment.get("algorithmId") or "")
        and isinstance(configurations, list)
        and bool(configurations)
        and all(isinstance(item, Mapping) for item in configurations)
        and _strict_int(tuning.get("configurationCount")) == len(configurations)
        and _strict_int(tuning.get("totalFits")) is not None
        and str(tuning.get("tuningMode") or "")
        and str(tuning.get("gridPreset") or "")
        and isinstance(experiment.get("executionResources"), Mapping)
        and (feature_contract is None or isinstance(feature_contract, Mapping))
        and (
            feature_contract is None
            or isinstance(feature_contract.get("orderedFeatures"), list)
        )
        and (selector is None or isinstance(selector, Mapping))
        and _strict_int(experiment.get("featureCount")) is not None
        and _strict_int(experiment.get("sourceFeatureCount")) is not None
    )


def _incremental_current_evidence(
    database: Database,
    project_id: str,
    resolved: Any,
    terminal_runs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Read independently persisted receipts from one active or orphaned batch.

    These receipts are useful progress evidence, but they are deliberately not
    merged into the final ranking or finalist authority until the batch writes
    its terminal V2 run receipt.
    """

    repository_rows = RunRepository(database).list_for_project(project_id)
    evidence_rows = [
        row
        for row in _mapping_sequence(repository_rows, label="Project run records")
        if row.get("run_type") == MODEL_DEVELOPMENT_JOB_TYPE
        and str(row.get("status") or "").upper()
        in {"QUEUED", "RUNNING", "CANCEL_REQUESTED", "INTERRUPTED", "FAILED"}
    ]
    if not evidence_rows:
        return {
            "status": "NONE",
            "jobId": None,
            "planId": None,
            "candidateGroups": [],
            "verifiedCandidateReceipts": 0,
            "heldClosedReceipts": 0,
            "diagnostics": [],
            "rankingEligible": False,
            "finalistSelectionEligible": False,
        }
    evidence_rows.sort(key=lambda row: str(row.get("started_at") or ""), reverse=True)
    row = evidence_rows[0]
    row_status = str(row.get("status") or "").upper()
    orphaned_terminal = row_status in {"INTERRUPTED", "FAILED"}
    plan = json_loads(row.get("parameters_json"), {})
    if not isinstance(plan, Mapping):
        return _incremental_held_closed(
            row,
            None,
            _incremental_diagnostic(
                "INCREMENTAL_PLAN_SHAPE_INVALID",
                "The active batch plan must decode to a JSON object.",
            ),
        )
    plan_id = plan.get("planId")
    terminal_plan_ids: set[Any] = set()
    for run in terminal_runs:
        if not isinstance(run, Mapping):
            raise _evidence_shape_error("A terminal candidate run must be a JSON object.")
        identity = run.get("identity") or {}
        if not isinstance(identity, Mapping):
            raise _evidence_shape_error("A terminal candidate run identity must be a JSON object.")
        terminal_plan_ids.add(identity.get("planId"))
    diagnostics: list[dict[str, Any]] = []
    unsigned_plan = {
        key: value for key, value in plan.items() if key not in {"planId", "checksum"}
    }
    expected_plan_sha = _sha(unsigned_plan) if unsigned_plan else None
    raw_experiments = plan.get("experiments")
    experiment_ids = (
        [str(item.get("experimentId") or "") for item in raw_experiments]
        if isinstance(raw_experiments, list)
        and all(isinstance(item, Mapping) for item in raw_experiments)
        else []
    )
    planned_configuration_count = (
        sum(
            int(item["tuning"]["configurationCount"])
            for item in raw_experiments
        )
        if isinstance(raw_experiments, list)
        and raw_experiments
        and all(
            isinstance(item, Mapping)
            and isinstance(item.get("tuning"), Mapping)
            and _strict_int(item["tuning"].get("configurationCount")) is not None
            for item in raw_experiments
        )
        else None
    )
    planned_fit_count = (
        sum(int(item["tuning"]["totalFits"]) for item in raw_experiments)
        if isinstance(raw_experiments, list)
        and raw_experiments
        and all(
            isinstance(item, Mapping)
            and isinstance(item.get("tuning"), Mapping)
            and _strict_int(item["tuning"].get("totalFits")) is not None
            for item in raw_experiments
        )
        else None
    )
    plan_shape_valid = (
        isinstance(raw_experiments, list)
        and bool(raw_experiments)
        and all(isinstance(item, Mapping) for item in raw_experiments)
        and all(_incremental_experiment_shape_valid(item) for item in raw_experiments)
        and len(experiment_ids) == len(set(experiment_ids))
        and isinstance(plan.get("environment"), Mapping)
    )
    if (
        not plan_shape_valid
        or plan.get("schemaVersion") != MODEL_DEVELOPMENT_PLAN_SCHEMA_VERSION
        or not expected_plan_sha
        or plan.get("checksum") != expected_plan_sha
        or plan_id != "stage3-model-plan-" + expected_plan_sha[:32]
        or plan.get("projectId") != project_id
        or plan.get("authorityKey") != resolved.authority_key
        or plan.get("splitContractId") != resolved.split["contractId"]
        or plan.get("splitChecksum") != resolved.split["checksum"]
        or _strict_int(plan.get("foldCount")) != 5
        or plan.get("metric") != "MULTICLASS_LOG_LOSS"
        or _strict_int(plan.get("totalExperiments")) != len(raw_experiments or [])
        or _strict_int(plan.get("totalConfigurations"))
        != planned_configuration_count
        or _strict_int(plan.get("totalFits")) != planned_fit_count
        or plan.get("finalOotLocked") is not True
        or plan.get("finalOotTargetAccessed") is not False
        or plan.get("providerCalls") != 0
        or plan.get("promotionRequested") is not False
    ):
        diagnostics.append(
            _incremental_diagnostic(
                "INCREMENTAL_PLAN_AUTHORITY_INVALID",
                "The active batch plan does not reconcile to current project authority.",
            )
        )
        return _incremental_held_closed(row, plan_id, diagnostics[0])

    if plan_id in terminal_plan_ids:
        return {
            "status": "TERMINAL_RECEIPT_AVAILABLE",
            "jobId": row.get("run_id"),
            "planId": plan_id,
            "candidateGroups": [],
            "verifiedCandidateReceipts": 0,
            "heldClosedReceipts": 0,
            "diagnostics": [],
            "rankingEligible": False,
            "finalistSelectionEligible": False,
        }

    progress = json_loads(row.get("metrics_json"), {})
    artifacts = json_loads(row.get("artifacts_json"), {})
    if not isinstance(progress, Mapping) or not isinstance(artifacts, Mapping):
        return _incremental_held_closed(
            row,
            plan_id,
            _incremental_diagnostic(
                "INCREMENTAL_RECEIPT_LEDGER_SHAPE_INVALID",
                "The active batch progress and artifact ledgers must decode to JSON objects.",
            ),
        )
    raw_pointers = artifacts.get("completedCandidateReceipts") or progress.get(
        "completedCandidateReceipts"
    ) or []
    if not isinstance(raw_pointers, list):
        return _incremental_held_closed(
            row,
            plan_id,
            _incremental_diagnostic(
                "INCREMENTAL_RECEIPT_LEDGER_SHAPE_INVALID",
                "The completed-candidate receipt ledger must be a JSON array.",
            ),
        )
    pointers: list[Mapping[str, Any]] = []
    seen_sha: set[str] = set()
    for pointer in raw_pointers:
        if not isinstance(pointer, Mapping):
            diagnostics.append(
                _incremental_diagnostic(
                    "INCREMENTAL_RECEIPT_POINTER_INVALID",
                    "A completed-candidate receipt pointer is not an object.",
                )
            )
            continue
        receipt_sha = str(pointer.get("candidateReceiptSha256") or "")
        if receipt_sha in seen_sha:
            continue
        seen_sha.add(receipt_sha)
        pointers.append(pointer)

    experiments = {
        str(item.get("experimentId") or ""): item for item in raw_experiments
    }
    verified_runs: list[dict[str, Any]] = []
    for pointer in pointers:
        receipt_sha = str(pointer.get("candidateReceiptSha256") or "")
        if len(receipt_sha) != 64 or any(char not in "0123456789abcdef" for char in receipt_sha):
            diagnostics.append(
                _incremental_diagnostic(
                    "INCREMENTAL_RECEIPT_ADDRESS_INVALID",
                    "A completed-candidate receipt has an invalid SHA-256 address.",
                    receipt_sha,
                )
            )
            continue
        path = (
            _runtime_root()
            / "candidate-attempts"
            / "objects"
            / "sha256"
            / f"{receipt_sha}.json"
        )
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            diagnostics.append(
                _incremental_diagnostic(
                    "INCREMENTAL_RECEIPT_UNREADABLE",
                    "A completed-candidate receipt could not be read.",
                    receipt_sha,
                )
            )
            continue
        if not isinstance(payload, Mapping):
            diagnostics.append(
                _incremental_diagnostic(
                    "INCREMENTAL_RECEIPT_SHAPE_INVALID",
                    "A completed-candidate receipt must decode to a JSON object.",
                    receipt_sha,
                )
            )
            continue
        candidate = payload.get("candidate") or {}
        if not isinstance(candidate, Mapping):
            diagnostics.append(
                _incremental_diagnostic(
                    "INCREMENTAL_RECEIPT_SHAPE_INVALID",
                    "A completed-candidate receipt candidate must be a JSON object.",
                    receipt_sha,
                )
            )
            continue
        experiment = experiments.get(str(candidate.get("experimentId") or ""), {})
        status = str(candidate.get("status") or "")
        exact = (
            hashlib.sha256(raw).hexdigest() == receipt_sha
            and canonical_json_bytes(payload) == raw
            and payload.get("schemaVersion") == INCREMENTAL_RECEIPT_SCHEMA_VERSION
            and payload.get("jobId") == row.get("run_id")
            and payload.get("projectId") == project_id
            and payload.get("planId") == plan_id
            and payload.get("planChecksum") == plan.get("checksum")
            and payload.get("finalOotTargetAccessed") is False
            and payload.get("promotionStatus") == "NOT_PROMOTED"
            and pointer.get("candidateId") == candidate.get("candidateId")
            and pointer.get("status") == status
            and status in {"COMPLETE", "FAILED"}
            and bool(experiment)
            and _incremental_candidate_matches_plan(candidate, experiment)
        )
        if not exact:
            diagnostics.append(
                _incremental_diagnostic(
                    "INCREMENTAL_RECEIPT_INTEGRITY_INVALID",
                    "A candidate receipt did not reconcile to its active plan and was held closed.",
                    receipt_sha,
                )
            )
            continue
        verified_runs.append(
            {
                "schemaVersion": INCREMENTAL_RECEIPT_SCHEMA_VERSION,
                "runId": f"{row.get('run_id')}:{receipt_sha[:16]}",
                "runReceiptSha256": receipt_sha,
                "createdAt": payload.get("createdAt"),
                "identity": {
                    "projectId": project_id,
                    "goldDatasetId": CURRENT_GOLD_DATASET_ID,
                    "goldManifestSha": resolved.eda_authority.gold_manifest_sha,
                    "splitContractId": resolved.split["contractId"],
                    "splitChecksum": resolved.split["checksum"],
                    "outlierPolicyId": resolved.outlier_policy["policyId"],
                    "outlierPolicyChecksum": resolved.outlier_policy["checksum"],
                    "missingPolicyId": resolved.missing_policy["policyId"],
                    "missingPolicyChecksum": resolved.missing_policy["checksum"],
                    "targetOrder": list(GOLD_CLASS_ORDER),
                },
                "environment": plan.get("environment") or {},
                "plan": plan,
                "candidates": [candidate],
                "_evidenceSource": "INCREMENTAL_CURRENT_EVIDENCE",
            }
        )

    groups = _group_attempts(verified_runs)
    for group in groups:
        group["rankingEligible"] = False
        group["rank"] = None
        group["developmentLabel"] = "INCREMENTAL_COMPLETE_NOT_SELECTION_ELIGIBLE"
        group["finalist"] = False
    return {
        "status": (
            "ORPHANED_TERMINAL_WITH_VERIFIED_EVIDENCE"
            if orphaned_terminal and groups
            else "ORPHANED_TERMINAL_NO_VERIFIED_EVIDENCE"
            if orphaned_terminal
            else "ACTIVE_WITH_VERIFIED_EVIDENCE"
            if groups
            else "ACTIVE_NO_VERIFIED_EVIDENCE"
        ),
        "jobId": row.get("run_id"),
        "planId": plan_id,
        "candidateGroups": groups,
        "verifiedCandidateReceipts": len(verified_runs),
        "heldClosedReceipts": len(diagnostics),
        "diagnostics": diagnostics,
        "rankingEligible": False,
        "finalistSelectionEligible": False,
    }


def project_candidate_evaluation(database: Database, project_id: str) -> dict[str, Any]:
    resolved = resolve_model_lab_authority(database, project_id)
    runs = _read_runs(project_id, resolved)
    current_runs = [
        run for run in runs if run.get("schemaVersion") == RUN_RECEIPT_SCHEMA_VERSION_V2
    ]
    historical_runs = [
        run for run in runs if run.get("schemaVersion") == RUN_RECEIPT_SCHEMA_VERSION
    ]
    current = _group_attempts(current_runs)
    historical = _group_attempts(historical_runs)
    current_fingerprints = {row["candidateFingerprint"] for row in current}
    source_groups = [*current, *historical]
    grouped = _rank_group_rows(
        [dict(row) for row in current]
        + [
            dict(row)
            for row in historical
            if row["candidateFingerprint"] not in current_fingerprints
        ]
    )
    incremental = _incremental_current_evidence(
        database, project_id, resolved, runs
    )
    finalist_rows = _decision_rows(database, project_id, FINALIST_RUN_TYPE)
    refinements = _decision_rows(database, project_id, REFINEMENT_RUN_TYPE)
    analyses = _decision_rows(database, project_id, ANALYSIS_RUN_TYPE)
    finalist_fingerprints: set[str] = set()
    finalist_receipts: list[dict[str, Any]] = []
    for row in finalist_rows:
        parameters = json_loads(row.get("parameters_json"), {})
        artifacts = json_loads(row.get("artifacts_json"), {})
        finalist_fingerprints.update(parameters.get("candidateFingerprints") or [])
        finalist_receipts.append(
            {
                "selectionId": row.get("run_id"),
                "status": row.get("status"),
                "createdAt": row.get("started_at"),
                "candidateFingerprints": parameters.get("candidateFingerprints") or [],
                "rationale": parameters.get("rationale"),
                "receiptSha256": artifacts.get("receiptSha256"),
            }
        )
    for collection in (grouped, current, historical):
        for row in collection:
            row["finalist"] = row["candidateFingerprint"] in finalist_fingerprints
    return {
        "ok": True,
        "schemaVersion": EVALUATION_SCHEMA_VERSION,
        "authority": {
            "projectId": project_id,
            "projectName": resolved.project_name,
            "goldDatasetId": CURRENT_GOLD_DATASET_ID,
            "goldManifestSha": resolved.eda_authority.gold_manifest_sha,
            "authorityKey": resolved.authority_key,
            "splitContractId": resolved.split["contractId"],
            "splitChecksum": resolved.split["checksum"],
            "outlierPolicyId": resolved.outlier_policy["policyId"],
            "missingPolicyId": resolved.missing_policy["policyId"],
            "targetOrder": list(GOLD_CLASS_ORDER),
            "legacyGlobalMatrixUsed": False,
            "base22FallbackAvailable": False,
        },
        "population": {
            "scope": "DEVELOPMENT_ONLY",
            "developmentRows": EXPECTED_DEVELOPMENT[2],
            "startDate": EXPECTED_DEVELOPMENT[0],
            "endDate": EXPECTED_DEVELOPMENT[1],
            "foldCount": 5,
            "finalOotRows": EXPECTED_FINAL_OOT[2],
            "finalOotStartDate": EXPECTED_FINAL_OOT[0],
            "finalOotEndDate": EXPECTED_FINAL_OOT[1],
            "finalOotLocked": True,
            "finalOotTargetAccessed": False,
            "finalOotScored": False,
        },
        "activity": {
            "immutableRunReceipts": len(runs),
            "historicalRunReceipts": sum(run.get("schemaVersion") == RUN_RECEIPT_SCHEMA_VERSION for run in runs),
            "currentBatchReceipts": sum(run.get("schemaVersion") == RUN_RECEIPT_SCHEMA_VERSION_V2 for run in runs),
            "uniqueCandidateSpecifications": len(
                {row["candidateFingerprint"] for row in source_groups}
            ),
            "attempts": sum(row["attemptCount"] for row in source_groups),
            "completedAttempts": sum(
                row["completedAttemptCount"] for row in source_groups
            ),
            "failedAttempts": sum(row["failedAttemptCount"] for row in source_groups),
            "incrementalVerifiedCandidateReceipts": incremental[
                "verifiedCandidateReceipts"
            ],
            "incrementalHeldClosedReceipts": incremental["heldClosedReceipts"],
            "modelFitsDisplayedAsProjectEvidence": sum(
                int(attempt.get("foldsCompleted") or 0)
                for row in source_groups for attempt in row["attempts"]
            ),
            "newFitsOnPageLoad": 0,
            "providerCalls": 0,
            "modelsPromoted": 0,
        },
        "currentBatches": current,
        "incrementalCurrentEvidence": incremental,
        "historicalEvidence": {
            "collapsedByDefault": bool(current),
            "banner": (
                "No new experiment was started by opening this page. Historical evidence was loaded from "
                f"{sum(run.get('schemaVersion') == RUN_RECEIPT_SCHEMA_VERSION for run in runs)} prior immutable run receipts."
            ),
            "candidates": historical,
        },
        "candidateGroups": grouped,
        "finalists": finalist_receipts,
        "refinements": [
            {
                "refinementId": row.get("run_id"),
                "status": row.get("status"),
                "plan": json_loads(row.get("parameters_json"), {}),
                "artifacts": json_loads(row.get("artifacts_json"), {}),
                "error": json_loads(row.get("error_json"), {}),
            }
            for row in refinements
        ],
        "analysisRequests": [
            {
                "analysisId": row.get("run_id"),
                "status": row.get("status"),
                "request": json_loads(row.get("parameters_json"), {}),
                "artifacts": json_loads(row.get("artifacts_json"), {}),
                "error": json_loads(row.get("error_json"), {}),
            }
            for row in analyses
        ],
        "selectionMetric": "MEAN_FIVE_FOLD_OOF_MULTICLASS_LOG_LOSS",
        "promotionStatus": "NOT_PROMOTED",
        "finalOotAccessed": False,
    }


def _candidate_group(
    database: Database, project_id: str, fingerprint: str
) -> tuple[Any, dict[str, Any]]:
    resolved = resolve_model_lab_authority(database, project_id)
    grouped = _group_attempts(_read_runs(project_id, resolved))
    candidate = next((item for item in grouped if item["candidateFingerprint"] == fingerprint), None)
    if candidate is None:
        raise Stage3ModelLaboratoryError(
            "STAGE3_EVALUATION_CANDIDATE_NOT_FOUND",
            "The verified project-bound candidate specification does not exist.",
            status_code=404,
        )
    return resolved, candidate


def save_finalist_selection(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    fingerprints = payload.get("candidateFingerprints")
    if not isinstance(fingerprints, list) or not fingerprints:
        raise Stage3ModelLaboratoryError(
            "STAGE3_FINALIST_SELECTION_REQUIRED",
            "Select at least one completed candidate for refinement.",
        )
    if len(fingerprints) != len(set(map(str, fingerprints))):
        raise Stage3ModelLaboratoryError(
            "STAGE3_FINALIST_SELECTION_DUPLICATE",
            "A finalist candidate was selected more than once.",
        )
    rationale = str(payload.get("rationale") or "").strip()
    if len(rationale) < 20:
        raise Stage3ModelLaboratoryError(
            "STAGE3_FINALIST_RATIONALE_REQUIRED",
            "A written finalist rationale of at least 20 characters is required.",
        )
    resolved = resolve_model_lab_authority(database, project_id)
    groups = {item["candidateFingerprint"]: item for item in _group_attempts(_read_runs(project_id, resolved))}
    selected = []
    for raw in fingerprints:
        fingerprint = str(raw)
        candidate = groups.get(fingerprint)
        if candidate is None or candidate["status"] != "COMPLETE":
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_CANDIDATE_INVALID",
                f"Finalist {fingerprint} is not a completed verified project-bound candidate.",
                status_code=409,
            )
        selected.append(
            {
                "candidateFingerprint": fingerprint,
                "modelFamily": candidate["modelFamily"],
                "featureSetId": candidate["featureSetId"],
                "meanOofLogLoss": candidate["meanOofLogLoss"],
                "warnings": [candidate["reproducibilityStatus"]]
                if candidate["reproducibilityStatus"] == "REPRODUCIBILITY_REVIEW_REQUIRED"
                else [],
                "attemptReceiptSha256s": [item["runReceiptSha256"] for item in candidate["attempts"]],
            }
        )
    body = {
        "schemaVersion": FINALIST_RECEIPT_SCHEMA_VERSION,
        "selectionId": "stage3-finalist-selection-" + uuid.uuid4().hex,
        "createdAt": now_iso(),
        "createdByUserId": actor_user_id,
        "projectId": project_id,
        "authorityKey": resolved.authority_key,
        "goldDatasetId": CURRENT_GOLD_DATASET_ID,
        "goldManifestSha": resolved.eda_authority.gold_manifest_sha,
        "splitContractId": resolved.split["contractId"],
        "outlierPolicyId": resolved.outlier_policy["policyId"],
        "missingPolicyId": resolved.missing_policy["policyId"],
        "evaluationBatch": str(payload.get("evaluationBatch") or "ALL_VERIFIED_PROJECT_EVIDENCE"),
        "candidateFingerprints": [item["candidateFingerprint"] for item in selected],
        "selectedCandidates": selected,
        "rationale": rationale,
        "primaryMetric": "MEAN_FIVE_FOLD_OOF_MULTICLASS_LOG_LOSS",
        "secondaryMetrics": ["SUMMED_MULTICLASS_BRIER", "ECE", "FOLD_STABILITY", "RUNTIME"],
        "decisionStatus": "FINALIST_FOR_REFINEMENT",
        "championSelected": False,
        "promotionStatus": "NOT_PROMOTED",
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
    }
    persisted = _persist_object("finalists", body)
    RunRepository(database).upsert(
        {
            "run_id": body["selectionId"],
            "project_id": project_id,
            "run_type": FINALIST_RUN_TYPE,
            "workflow_type": "sports_stage3_candidate_evaluation",
            "status": "FINALIST_FOR_REFINEMENT",
            "started_at": body["createdAt"],
            "completed_at": body["createdAt"],
            "parameters_json": body,
            "metrics_json": {"selectedCount": len(selected), "modelsPromoted": 0},
            "artifacts_json": {"receiptSha256": persisted["receiptSha256"]},
            "error_json": {},
            "created_by": actor_user_id,
        }
    )
    return {"ok": True, "selection": persisted}


def request_candidate_analysis(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    kind = str(payload.get("analysisKind") or "").upper()
    if kind not in _ANALYSIS_KINDS:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ANALYSIS_KIND_INVALID",
            "Analysis kind must be PERMUTATION_IMPORTANCE, SHAP, or SENSITIVITY.",
        )
    fingerprint = str(payload.get("candidateFingerprint") or "")
    resolved, candidate = _candidate_group(database, project_id, fingerprint)
    if candidate["status"] != "COMPLETE":
        raise Stage3ModelLaboratoryError(
            "STAGE3_ANALYSIS_CANDIDATE_INCOMPLETE",
            "Explicit analysis requires a completed candidate.",
            status_code=409,
        )
    if kind in {"SHAP", "SENSITIVITY"}:
        persisted_finalists = {
            str(item)
            for row in _decision_rows(database, project_id, FINALIST_RUN_TYPE)
            for item in (
                json_loads(row.get("parameters_json"), {}).get(
                    "candidateFingerprints"
                )
                or []
            )
        }
        if fingerprint not in persisted_finalists:
            raise Stage3ModelLaboratoryError(
                "STAGE3_ANALYSIS_FINALIST_REQUIRED",
                "SHAP and sensitivity analysis require an immutable finalist selection receipt.",
                status_code=409,
            )
    sample_size = int(payload.get("sampleSize") or 2_000)
    if not 100 <= sample_size <= 5_000:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ANALYSIS_SAMPLE_BOUNDS",
            "Development-only analysis sample size must be between 100 and 5,000.",
        )
    seed = int(payload.get("seed") or 20260901)
    if seed < 0 or seed > 2**32 - 1:
        raise Stage3ModelLaboratoryError("STAGE3_ANALYSIS_SEED_INVALID", "Seed is invalid.")
    target_class = str(payload.get("targetClass") or GOLD_CLASS_ORDER[0])
    if target_class not in GOLD_CLASS_ORDER:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ANALYSIS_TARGET_INVALID", "The selected target class is not governed."
        )
    sample_identity = _sha(
        {
            "projectId": project_id,
            "candidateFingerprint": fingerprint,
            "scope": "DEVELOPMENT_ONLY",
            "sampleSize": sample_size,
            "seed": seed,
            "targetClass": target_class,
        }
    )
    if kind == "SHAP" and importlib.util.find_spec("shap") is None:
        status = "NOT_AVAILABLE_DEPENDENCY_NOT_INSTALLED"
        limitation = "SHAP is not installed in the governed environment; permutation importance remains available as the safe fallback."
    else:
        # A model reloadable artifact/OOF row ledger is required for an honest
        # post-hoc computation.  V1 receipts deliberately contain aggregate
        # evidence only; never fabricate row-level analysis from their metrics.
        has_artifact = any(
            isinstance(attempt.get("evaluationEvidence"), Mapping)
            and attempt["evaluationEvidence"].get("reloadableArtifactSha256")
            for attempt in candidate["attempts"]
        )
        status = "QUEUED_FOR_EXPLICIT_DEVELOPMENT_ANALYSIS" if has_artifact else "EVIDENCE_NOT_CAPTURED_IN_IMMUTABLE_RECEIPT"
        limitation = None if has_artifact else "This immutable attempt did not capture a reloadable fold model and development-row prediction artifact. The affected analysis fails closed; other candidates remain available."
    body = {
        "schemaVersion": ANALYSIS_RECEIPT_SCHEMA_VERSION,
        "analysisId": "stage3-analysis-" + uuid.uuid4().hex,
        "createdAt": now_iso(),
        "createdByUserId": actor_user_id,
        "projectId": project_id,
        "authorityKey": resolved.authority_key,
        "candidateFingerprint": fingerprint,
        "analysisKind": kind,
        "status": status,
        "sample": {
            "scope": "DEVELOPMENT_ONLY",
            "size": sample_size,
            "seed": seed,
            "sampleIdentitySha256": sample_identity,
            "targetClass": target_class,
        },
        "limitations": [limitation] if limitation else [],
        "causalClaim": False,
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
        "modelsPromoted": 0,
    }
    persisted = _persist_object("analysis", body)
    RunRepository(database).upsert(
        {
            "run_id": body["analysisId"],
            "project_id": project_id,
            "run_type": ANALYSIS_RUN_TYPE,
            "workflow_type": "sports_stage3_candidate_analysis",
            "status": status,
            "started_at": body["createdAt"],
            "completed_at": body["createdAt"] if status != "QUEUED_FOR_EXPLICIT_DEVELOPMENT_ANALYSIS" else None,
            "parameters_json": body,
            "metrics_json": {"sampleSize": sample_size, "modelsPromoted": 0},
            "artifacts_json": {"receiptSha256": persisted["receiptSha256"], "sampleIdentitySha256": sample_identity},
            "error_json": {"code": status, "message": limitation} if limitation else {},
            "created_by": actor_user_id,
        }
    )
    return {"ok": True, "analysis": persisted}


def plan_model_refinement(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    fingerprint = str(payload.get("candidateFingerprint") or "")
    resolved, candidate = _candidate_group(database, project_id, fingerprint)
    if candidate["status"] != "COMPLETE" or not candidate.get("finalist"):
        # ``finalist`` is decorated by the full evaluation response, so resolve
        # persisted finalist decisions explicitly here.
        selected = {
            item
            for row in _decision_rows(database, project_id, FINALIST_RUN_TYPE)
            for item in (json_loads(row.get("parameters_json"), {}).get("candidateFingerprints") or [])
        }
        if fingerprint not in selected:
            raise Stage3ModelLaboratoryError(
                "STAGE3_REFINEMENT_FINALIST_REQUIRED",
                "Only an explicitly selected finalist may enter Model Refinement.",
                status_code=409,
            )
    method = str(payload.get("method") or "STABILITY_SELECTION").upper()
    if method not in _REFINEMENT_METHODS:
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_METHOD_INVALID", "The selected refinement method is unsupported."
        )
    feature_count = int(candidate.get("featureCount") or 0)
    if feature_count <= 0:
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_FEATURES_NOT_APPLICABLE",
            "The feature-independent reference cannot enter feature refinement.",
            status_code=409,
        )
    minimum = int(payload.get("minimumRetainedFeatures") or max(10, feature_count // 2))
    step = int(payload.get("eliminationStep") or max(1, feature_count // 20))
    if not 1 <= minimum < feature_count or not 1 <= step < feature_count:
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_BOUNDS_INVALID",
            "Minimum retained features and elimination step must preserve a non-empty reduced challenger.",
        )
    family = str(candidate.get("modelFamily") or "")
    classical_rfe = family in {
        "multinomial_logistic", "elastic_net_logistic", "decision_tree",
        "random_forest", "extra_trees", "xgboost", "lightgbm", "catboost",
        "linear_svm", "sgd_classifier",
    }
    coefficient_capable = family in {
        "multinomial_logistic", "elastic_net_logistic", "linear_svm", "sgd_classifier",
    }
    if method in {"RFE", "RFECV"} and not classical_rfe:
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_RFE_NOT_APPLICABLE",
            "Classical RFE is not compatible with this estimator; choose a governed alternative.",
        )
    if method == "STABILITY_SELECTION" and not classical_rfe:
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_NATIVE_RANKING_NOT_APPLICABLE",
            "This estimator exposes no compatible fold-local coefficient/native-importance selector; choose a governed permutation, family-ablation, or redundancy alternative.",
            status_code=409,
        )
    if method == "COEFFICIENT_GUIDED_ELIMINATION" and not coefficient_capable:
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_COEFFICIENTS_NOT_APPLICABLE",
            "Coefficient-guided elimination is available only for compatible linear finalists.",
            status_code=409,
        )
    expected_rounds = max(1, int(np.ceil((feature_count - minimum) / step)))
    expected_fits = (expected_rounds + 1) * 5
    plan_content = {
        "schemaVersion": REFINEMENT_PLAN_SCHEMA_VERSION,
        "projectId": project_id,
        "authorityKey": resolved.authority_key,
        "goldDatasetId": CURRENT_GOLD_DATASET_ID,
        "goldManifestSha": resolved.eda_authority.gold_manifest_sha,
        "splitContractId": resolved.split["contractId"],
        "parentCandidateFingerprint": fingerprint,
        "parentFeatureSetId": candidate.get("featureSetId"),
        "parentFeatureCount": feature_count,
        "method": method,
        "minimumRetainedFeatures": minimum,
        "eliminationStep": step,
        "scoringMetric": "MULTICLASS_LOG_LOSS",
        "foldLocalSelection": True,
        "validationRowsSelectFeatures": False,
        "stableSetRule": "TRAINING_FOLD_RANK_FREQUENCY_THEN_MEAN_TRAINING_ONLY_MAGNITUDE",
        "expectedSelectionRoundsPerFold": expected_rounds,
        "expectedFits": expected_fits,
        "reducedCandidateStatus": "NEW_IMMUTABLE_CANDIDATE_AFTER_EXPLICIT_EXECUTION",
        "parentCandidateMutated": False,
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
        "modelsPromoted": 0,
        "rationale": str(payload.get("rationale") or "").strip(),
    }
    checksum = _sha(plan_content)
    plan = {
        **plan_content,
        "planId": "stage3-refinement-plan-" + checksum[:32],
        "checksum": checksum,
        "createdAt": now_iso(),
        "createdByUserId": actor_user_id,
        "status": "PLANNED_NOT_EXECUTED",
    }
    persisted = _persist_object("refinement", plan)
    RunRepository(database).upsert(
        {
            "run_id": plan["planId"],
            "project_id": project_id,
            "run_type": REFINEMENT_RUN_TYPE,
            "workflow_type": "sports_stage3_model_refinement",
            "status": "PLANNED_NOT_EXECUTED",
            "started_at": plan["createdAt"],
            "completed_at": plan["createdAt"],
            "parameters_json": plan,
            "metrics_json": {"expectedFits": expected_fits, "actualFits": 0, "modelsPromoted": 0},
            "artifacts_json": {"receiptSha256": persisted["receiptSha256"]},
            "error_json": {},
            "created_by": actor_user_id,
        }
    )
    return {"ok": True, "plan": persisted}


def execute_model_refinement(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    """Create a reduced challenger from fold-local training-only stability evidence.

    The executable path is deliberately limited to methods whose evidence is
    already present in the immutable finalist receipt.  Classical RFE/RFECV
    plans remain reviewable but fail closed until their fold-local selector
    worker is explicitly implemented; they are never approximated by a global
    selection pass.
    """

    plan_id = str(payload.get("planId") or "")
    row = RunRepository(database).get(plan_id)
    if row is None or row.get("project_id") != project_id or row.get("run_type") != REFINEMENT_RUN_TYPE:
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_PLAN_NOT_FOUND",
            "The project-bound refinement plan does not exist.",
            status_code=404,
        )
    plan = json_loads(row.get("parameters_json"), {})
    if plan.get("status") != "PLANNED_NOT_EXECUTED" or str(row.get("status")) != "PLANNED_NOT_EXECUTED":
        artifacts = json_loads(row.get("artifacts_json"), {})
        if artifacts.get("modelDevelopmentJobId"):
            return {"ok": True, "jobId": artifacts["modelDevelopmentJobId"], "idempotentReplay": True}
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_PLAN_ALREADY_CONSUMED",
            "The immutable refinement plan has already been consumed.",
            status_code=409,
        )
    method = str(plan.get("method") or "")
    if method not in {"RFE", "STABILITY_SELECTION", "COEFFICIENT_GUIDED_ELIMINATION"}:
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_METHOD_EXECUTOR_UNAVAILABLE",
            "This plan remains reviewable, but its fold-local selector executor is not available. No global or validation-informed substitute was used.",
            status_code=409,
        )
    resolved, candidate = _candidate_group(
        database, project_id, str(plan["parentCandidateFingerprint"])
    )
    attempt = next((item for item in candidate["attempts"] if item["status"] == "COMPLETE"), None)
    if attempt is None:
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_PARENT_EVIDENCE_MISSING",
            "The finalist has no completed immutable attempt.",
            status_code=409,
        )
    ordered = list(attempt.get("orderedFeatures") or [])
    feature_id = candidate.get("featureSetId")
    if not ordered:
        eligibility = build_model_eligibility(resolved)
        if feature_id == eligibility.get("featureSetId"):
            ordered = list(eligibility.get("orderedFeatures") or [])
        else:
            registered = next(
                (item for item in resolved.feature_sets if item.get("featureSetId") == feature_id),
                None,
            )
            ordered = list((registered or {}).get("orderedFeatures") or [])
    if len(ordered) != int(plan.get("parentFeatureCount") or 0):
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_PARENT_FEATURE_IDENTITY_MISMATCH",
            "The finalist ordered feature identity could not be reconstructed exactly.",
            status_code=409,
        )
    experiment_payload = {
        "authorityKey": resolved.authority_key,
        "splitContractId": resolved.split["contractId"],
        "experiments": [
            {
                "algorithmId": candidate["modelFamily"],
                "featureUniverseId": feature_id,
                "tuningMode": "FIXED",
                "gridPreset": "CUSTOM",
                "fixedHyperparameters": candidate["hyperparameters"],
                "seed": int(attempt.get("seed") or 20260901),
                "parentCandidateFingerprint": candidate["candidateFingerprint"],
                "refinementPlanId": plan_id,
                "foldLocalSelector": {
                    "method": method,
                    "minimumRetainedFeatures": int(plan["minimumRetainedFeatures"]),
                    "eliminationStep": int(plan["eliminationStep"]),
                    "refinementPlanId": plan_id,
                },
            }
        ],
        "parallelWorkers": 1,
        "batchName": f"Reduced challenger from {candidate['modelFamily']} · {plan_id}",
        "acknowledgeExcessiveFits": False,
    }
    reviewed_plan = plan_model_development_queue(
        database,
        project_id,
        experiment_payload,
        actor_user_id=actor_user_id,
    )
    experiment_payload = {
        **experiment_payload,
        "expectedPlanId": reviewed_plan["planId"],
        "expectedPlanChecksum": reviewed_plan["checksum"],
    }
    job = enqueue_model_development_job(
        database,
        project_id,
        experiment_payload,
        actor_user_id=actor_user_id,
    )
    job_id = job["job"]["jobId"]
    artifacts = {
        **json_loads(row.get("artifacts_json"), {}),
        "modelDevelopmentJobId": job_id,
        "targetRetainedFeatureCount": int(plan["minimumRetainedFeatures"]),
        "foldLocalSelection": True,
        "validationRowsSelectFeatures": False,
    }
    updated_plan = {
        **plan,
        "status": "QUEUED_REDUCED_CHALLENGER",
        "reducedCandidateLabel": "REDUCED_CHALLENGER",
        "parentCandidateMutated": False,
    }
    RunRepository(database).upsert(
        {
            "run_id": plan_id,
            "project_id": project_id,
            "run_type": REFINEMENT_RUN_TYPE,
            "workflow_type": "sports_stage3_model_refinement",
            "status": "QUEUED_REDUCED_CHALLENGER",
            "started_at": row.get("started_at") or now_iso(),
            "completed_at": None,
            "parameters_json": updated_plan,
            "metrics_json": {
                "expectedFits": int(plan.get("expectedFits") or 0),
                "actualFits": 0,
                "targetRetainedFeatureCount": int(plan["minimumRetainedFeatures"]),
                "modelsPromoted": 0,
            },
            "artifacts_json": artifacts,
            "error_json": {},
            "created_by": row.get("created_by") or actor_user_id,
        }
    )
    return {
        "ok": True,
        "job": job["job"],
        "refinement": {
            "planId": plan_id,
            "parentCandidateFingerprint": candidate["candidateFingerprint"],
            "targetRetainedFeatureCount": int(plan["minimumRetainedFeatures"]),
            "foldLocalSelection": True,
            "validationRowsSelectFeatures": False,
            "reducedCandidateStatus": "QUEUED_NEW_IMMUTABLE_CANDIDATE",
            "finalOotTargetAccessed": False,
            "modelsPromoted": 0,
        },
    }


__all__ = [
    "ANALYSIS_RECEIPT_SCHEMA_VERSION",
    "EVALUATION_SCHEMA_VERSION",
    "FINALIST_RECEIPT_SCHEMA_VERSION",
    "REFINEMENT_PLAN_SCHEMA_VERSION",
    "candidate_specification_fingerprint",
    "candidate_specification_payload",
    "plan_model_refinement",
    "execute_model_refinement",
    "project_candidate_evaluation",
    "request_candidate_analysis",
    "save_finalist_selection",
]

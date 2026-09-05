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
    project_read_view,
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
DOWNSTREAM_SCHEMA_VERSION = "SPORTS_STAGE3_PROJECT_DOWNSTREAM_V1"
CALIBRATION_DECISION_SCHEMA_VERSION = "SPORTS_STAGE3_CALIBRATION_DECISION_V1"
GAME_EVALUATION_DECISION_SCHEMA_VERSION = "SPORTS_STAGE3_GAME_EVALUATION_DECISION_V1"
CHALLENGER_DECISION_SCHEMA_VERSION = "SPORTS_STAGE3_CHALLENGER_DECISION_V1"
REGISTRY_HANDOFF_SCHEMA_VERSION = "SPORTS_STAGE3_RESEARCH_HANDOFF_V1"
CALIBRATION_DECISION_RUN_TYPE = "sports_stage3_calibration_decision"
GAME_EVALUATION_DECISION_RUN_TYPE = "sports_stage3_game_evaluation_decision"
CHALLENGER_DECISION_RUN_TYPE = "sports_stage3_challenger_decision"
REGISTRY_HANDOFF_RUN_TYPE = "sports_stage3_research_handoff"

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


def _ordered_finalist_rows(database: Database, project_id: str) -> list[dict[str, Any]]:
    """Return immutable finalist decisions newest-first.

    Finalist receipts are an append-only decision history.  Current authority
    belongs to the newest receipt; older receipts remain auditable history and
    must never be unioned into the current selection.
    """

    return sorted(
        _decision_rows(database, project_id, FINALIST_RUN_TYPE),
        key=lambda row: (
            str(row.get("started_at") or row.get("completed_at") or ""),
            str(row.get("run_id") or ""),
        ),
        reverse=True,
    )


def _finalist_parameters(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {}
    parameters = json_loads(row.get("parameters_json"), {})
    if not isinstance(parameters, Mapping):
        raise _evidence_shape_error(
            "The current finalist-selection receipt parameters must be a JSON object."
        )
    return dict(parameters)


def _current_finalist_authority(
    database: Database, project_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    rows = _ordered_finalist_rows(database, project_id)
    row = rows[0] if rows else None
    return row, _finalist_parameters(row)


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


@project_read_view
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
    finalist_rows = _ordered_finalist_rows(database, project_id)
    refinements = _decision_rows(database, project_id, REFINEMENT_RUN_TYPE)
    analyses = _decision_rows(database, project_id, ANALYSIS_RUN_TYPE)
    finalist_fingerprints: set[str] = set()
    finalist_evidence_source: str | None = None
    finalist_receipts: list[dict[str, Any]] = []
    current_finalist_id = finalist_rows[0].get("run_id") if finalist_rows else None
    for index, row in enumerate(finalist_rows):
        parameters = _finalist_parameters(row)
        artifacts = json_loads(row.get("artifacts_json"), {})
        if not isinstance(artifacts, Mapping):
            raise _evidence_shape_error(
                "Finalist-selection artifacts must be a JSON object."
            )
        fingerprints = parameters.get("candidateFingerprints") or []
        if not isinstance(fingerprints, list):
            raise _evidence_shape_error(
                "Finalist-selection candidateFingerprints must be a JSON array."
            )
        if index == 0:
            finalist_fingerprints = {str(item) for item in fingerprints}
            requested_source = str(
                parameters.get("evidenceSource")
                or parameters.get("evaluationBatch")
                or ""
            )
            if requested_source in {"CURRENT_BATCH", "HISTORICAL_BASELINE"}:
                finalist_evidence_source = requested_source
            else:
                # Legacy V1 finalist receipts used ALL even when every bound
                # attempt came from one exact source. Resolve that source only
                # when the immutable attempt identities make it unambiguous.
                selected_candidates = parameters.get("selectedCandidates") or []
                receipt_shas = {
                    str(receipt)
                    for item in selected_candidates
                    if isinstance(item, Mapping)
                    for receipt in (item.get("attemptReceiptSha256s") or [])
                }
                matching_sources = {
                    str(attempt.get("evidenceSource"))
                    for group in source_groups
                    if group["candidateFingerprint"] in finalist_fingerprints
                    for attempt in group["attempts"]
                    if attempt.get("runReceiptSha256") in receipt_shas
                }
                if len(matching_sources) == 1:
                    finalist_evidence_source = matching_sources.pop()
        finalist_receipts.append(
            {
                "selectionId": row.get("run_id"),
                "status": row.get("status"),
                "createdAt": row.get("started_at"),
                "candidateFingerprints": fingerprints,
                "rationale": parameters.get("rationale"),
                "receiptSha256": artifacts.get("receiptSha256"),
                "evaluationBatch": parameters.get("evaluationBatch"),
                "selectedCandidates": parameters.get("selectedCandidates") or [],
                "authorityStatus": "CURRENT" if index == 0 else "SUPERSEDED",
                "supersededBySelectionId": None if index == 0 else current_finalist_id,
            }
        )
    for collection in (grouped, current, historical):
        for row in collection:
            row["finalist"] = (
                row["candidateFingerprint"] in finalist_fingerprints
                and finalist_evidence_source in row["evidenceSources"]
            )
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
            "developmentRows": int(resolved.split["development"]["rows"]),
            "startDate": str(resolved.split["development"]["startDate"]),
            "endDate": str(resolved.split["development"]["endDate"]),
            "foldCount": 5,
            "finalOotRows": int(resolved.split["finalOot"]["rows"]),
            "finalOotStartDate": str(resolved.split["finalOot"]["startDate"]),
            "finalOotEndDate": str(resolved.split["finalOot"]["endDate"]),
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
        "currentFinalistSelectionId": current_finalist_id,
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
    database: Database,
    project_id: str,
    fingerprint: str,
    *,
    evidence_source: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    resolved = resolve_model_lab_authority(database, project_id)
    runs = _read_runs(project_id, resolved)
    if evidence_source is not None:
        schema = {
            "CURRENT_BATCH": RUN_RECEIPT_SCHEMA_VERSION_V2,
            "HISTORICAL_BASELINE": RUN_RECEIPT_SCHEMA_VERSION,
        }.get(evidence_source)
        if schema is None:
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_EVIDENCE_SOURCE_INVALID",
                "The finalist evidence source is unsupported.",
                status_code=409,
            )
        runs = [run for run in runs if run.get("schemaVersion") == schema]
    grouped = _group_attempts(runs)
    candidate = next((item for item in grouped if item["candidateFingerprint"] == fingerprint), None)
    if candidate is None:
        raise Stage3ModelLaboratoryError(
            "STAGE3_EVALUATION_CANDIDATE_NOT_FOUND",
            "The verified project-bound candidate specification does not exist.",
            status_code=404,
        )
    return resolved, candidate


def _current_finalist_binding(
    database: Database,
    project_id: str,
    fingerprint: str,
    candidate: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Resolve one current finalist to its frozen source and attempt evidence."""

    _row, parameters = _current_finalist_authority(database, project_id)
    raw_fingerprints = parameters.get("candidateFingerprints") or []
    if not isinstance(raw_fingerprints, list) or fingerprint not in {
        str(item) for item in raw_fingerprints
    }:
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_FINALIST_REQUIRED",
            "Only a finalist in the current immutable selection receipt may enter this action.",
            status_code=409,
        )
    raw_selected = parameters.get("selectedCandidates") or []
    if not isinstance(raw_selected, list):
        raise _evidence_shape_error(
            "The current finalist selectedCandidates must be a JSON array."
        )
    selected = next(
        (
            item
            for item in raw_selected
            if isinstance(item, Mapping)
            and str(item.get("candidateFingerprint") or "") == fingerprint
        ),
        None,
    )
    if selected is None:
        raise Stage3ModelLaboratoryError(
            "STAGE3_FINALIST_ATTEMPT_EVIDENCE_MISSING",
            "The current finalist receipt does not identify its selected candidate evidence.",
            status_code=409,
        )
    explicit_sources = {
        str(value)
        for value in (
            selected.get("evidenceSource"),
            parameters.get("evidenceSource"),
            parameters.get("evaluationBatch"),
        )
        if str(value or "") in {"CURRENT_BATCH", "HISTORICAL_BASELINE"}
    }
    if len(explicit_sources) > 1:
        raise Stage3ModelLaboratoryError(
            "STAGE3_FINALIST_EVIDENCE_SOURCE_MISMATCH",
            "The current finalist receipt contains conflicting evidence-source identities.",
            status_code=409,
        )
    if explicit_sources:
        source = explicit_sources.pop()
    else:
        # Backward-compatible resolution for already persisted V1 selections:
        # infer only from their exact immutable run-receipt hashes.
        bound_receipts = {
            str(value)
            for value in (selected.get("attemptReceiptSha256s") or [])
        }
        inferred = {
            str(attempt.get("evidenceSource"))
            for attempt in (candidate.get("attempts") or [])
            if attempt.get("runReceiptSha256") in bound_receipts
        }
        if len(inferred) != 1:
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_EVIDENCE_SOURCE_AMBIGUOUS",
                "The current legacy finalist receipt cannot be resolved to one exact evidence source.",
                status_code=409,
            )
        source = inferred.pop()
    source_attempts = [
        attempt
        for attempt in (candidate.get("attempts") or [])
        if attempt.get("status") == "COMPLETE"
        and attempt.get("evidenceSource") == source
    ]
    if not source_attempts:
        raise Stage3ModelLaboratoryError(
            "STAGE3_FINALIST_EVIDENCE_SOURCE_MISMATCH",
            "The current finalist receipt has no matching completed source-bound attempt.",
            status_code=409,
        )
    available = {
        (
            str(item.get("attemptId") or ""),
            str(item.get("runId") or ""),
            str(item.get("runReceiptSha256") or ""),
        ): item
        for item in source_attempts
    }
    raw_bound = selected.get("attemptEvidence")
    if raw_bound is not None:
        if not isinstance(raw_bound, list) or any(
            not isinstance(item, Mapping) for item in raw_bound
        ):
            raise _evidence_shape_error(
                "The current finalist attemptEvidence must be a JSON array of objects."
            )
        bound = {
            (
                str(item.get("attemptId") or ""),
                str(item.get("runId") or ""),
                str(item.get("runReceiptSha256") or ""),
            )
            for item in raw_bound
        }
        if (
            not bound
            or len(bound) != len(raw_bound)
            or any(not all(identity) for identity in bound)
            or not bound.issubset(available)
        ):
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_ATTEMPT_EVIDENCE_MISMATCH",
                "The current finalist receipt no longer reconciles to its exact attempt evidence.",
                status_code=409,
            )
        representative = available.get(
            (
                str(selected.get("representativeAttemptId") or ""),
                str(selected.get("representativeRunId") or ""),
                str(selected.get("immutableEvidenceIdentity") or ""),
            )
        )
        if representative is None or (
            str(representative.get("attemptId") or ""),
            str(representative.get("runId") or ""),
            str(representative.get("runReceiptSha256") or ""),
        ) not in bound:
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_REPRESENTATIVE_EVIDENCE_MISMATCH",
                "The current finalist representative is not part of its bound attempt evidence.",
                status_code=409,
            )
    else:
        # Legacy immutable selections bound run receipt hashes but did not name
        # their representative attempt. Preserve those receipts and derive one
        # representative deterministically from only the originally bound runs.
        bound_receipts = {
            str(value) for value in (selected.get("attemptReceiptSha256s") or [])
        }
        legacy_attempts = [
            attempt
            for attempt in source_attempts
            if attempt.get("runReceiptSha256") in bound_receipts
        ]
        if not legacy_attempts:
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_ATTEMPT_EVIDENCE_MISMATCH",
                "The current legacy finalist no longer resolves to its bound immutable receipts.",
                status_code=409,
            )
        representative = next(
            (
                item
                for item in legacy_attempts
                if item.get("attemptId") == candidate.get("representativeAttemptId")
            ),
            legacy_attempts[0],
        )
    return source, {
        **dict(selected),
        "evidenceSource": source,
        "representativeAttemptId": representative["attemptId"],
        "representativeRunId": representative["runId"],
        "immutableEvidenceIdentity": representative["runReceiptSha256"],
    }


def _current_finalist_source(
    database: Database,
    project_id: str,
    fingerprint: str,
    candidate: Mapping[str, Any],
) -> str:
    source, _binding = _current_finalist_binding(
        database, project_id, fingerprint, candidate
    )
    return source


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
    evidence_source = str(payload.get("evaluationBatch") or "").upper()
    if evidence_source not in {"CURRENT_BATCH", "HISTORICAL_BASELINE"}:
        raise Stage3ModelLaboratoryError(
            "STAGE3_FINALIST_EVIDENCE_SOURCE_REQUIRED",
            "Finalist selection requires one exact evidence source: CURRENT_BATCH or HISTORICAL_BASELINE.",
            status_code=409,
        )
    raw_selections = payload.get("candidateSelections")
    if not isinstance(raw_selections, list) or any(
        not isinstance(item, Mapping) for item in raw_selections
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_FINALIST_EVIDENCE_BINDINGS_REQUIRED",
            "Finalist selection requires exact candidate, attempt, run, and receipt bindings.",
        )
    selection_by_fingerprint: dict[str, Mapping[str, Any]] = {}
    for item in raw_selections:
        fingerprint = str(item.get("candidateFingerprint") or "")
        if not fingerprint or fingerprint in selection_by_fingerprint:
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_EVIDENCE_BINDINGS_DUPLICATE",
                "Each finalist must have exactly one evidence binding.",
            )
        selection_by_fingerprint[fingerprint] = item
    requested_fingerprints = [str(item) for item in fingerprints]
    if set(selection_by_fingerprint) != set(requested_fingerprints):
        raise Stage3ModelLaboratoryError(
            "STAGE3_FINALIST_EVIDENCE_BINDINGS_MISMATCH",
            "Candidate evidence bindings must match the requested finalist fingerprints exactly.",
            status_code=409,
        )
    resolved = resolve_model_lab_authority(database, project_id)
    groups = {item["candidateFingerprint"]: item for item in _group_attempts(_read_runs(project_id, resolved))}
    selected = []
    for fingerprint in requested_fingerprints:
        candidate = groups.get(fingerprint)
        if candidate is None or candidate["status"] != "COMPLETE":
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_CANDIDATE_INVALID",
                f"Finalist {fingerprint} is not a completed verified project-bound candidate.",
                status_code=409,
            )
        binding = selection_by_fingerprint[fingerprint]
        if str(binding.get("evidenceSource") or "").upper() != evidence_source:
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_EVIDENCE_SOURCE_MISMATCH",
                f"Finalist {fingerprint} does not bind the requested {evidence_source} evidence source.",
                status_code=409,
            )
        source_attempts = [
            item
            for item in candidate["attempts"]
            if item.get("status") == "COMPLETE"
            and item.get("evidenceSource") == evidence_source
        ]
        source_attempts.sort(
            key=lambda item: (
                str(item.get("createdAt") or ""),
                str(item.get("runReceiptSha256") or ""),
                str(item.get("attemptId") or ""),
            ),
            reverse=True,
        )
        if not source_attempts:
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_EVIDENCE_SOURCE_MISMATCH",
                f"Finalist {fingerprint} has no completed verified {evidence_source} attempt.",
                status_code=409,
            )
        raw_attempt_evidence = binding.get("attemptEvidence")
        if not isinstance(raw_attempt_evidence, list) or any(
            not isinstance(item, Mapping) for item in raw_attempt_evidence
        ):
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_ATTEMPT_EVIDENCE_REQUIRED",
                f"Finalist {fingerprint} requires exact attempt/run/receipt evidence.",
            )

        def attempt_identity(item: Mapping[str, Any]) -> tuple[str, str, str]:
            return (
                str(item.get("attemptId") or ""),
                str(item.get("runId") or ""),
                str(item.get("runReceiptSha256") or ""),
            )

        available_attempts = {attempt_identity(item) for item in source_attempts}
        requested_attempts = {attempt_identity(item) for item in raw_attempt_evidence}
        if (
            not requested_attempts
            or len(requested_attempts) != len(raw_attempt_evidence)
            or any(not all(identity) for identity in requested_attempts)
            or not requested_attempts.issubset(available_attempts)
        ):
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_ATTEMPT_EVIDENCE_MISMATCH",
                f"Finalist {fingerprint} attempt evidence does not identify completed verified {evidence_source} attempts exactly.",
                status_code=409,
            )
        selected_source_attempts = [
            item
            for item in source_attempts
            if attempt_identity(item) in requested_attempts
        ]
        representative_attempt_id = str(binding.get("representativeAttemptId") or "")
        immutable_evidence_identity = str(binding.get("immutableEvidenceIdentity") or "")
        representative = next(
            (
                item
                for item in selected_source_attempts
                if item.get("attemptId") == representative_attempt_id
                and item.get("runReceiptSha256") == immutable_evidence_identity
            ),
            None,
        )
        if representative is None:
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_REPRESENTATIVE_EVIDENCE_MISMATCH",
                f"Finalist {fingerprint} representative attempt and receipt identity do not match verified {evidence_source} evidence.",
                status_code=409,
            )
        source_losses = [
            float(item["meanOofLogLoss"])
            for item in selected_source_attempts
            if item.get("meanOofLogLoss") is not None
        ]
        if not source_losses:
            raise Stage3ModelLaboratoryError(
                "STAGE3_FINALIST_METRIC_EVIDENCE_MISSING",
                f"Finalist {fingerprint} has no finite source-bound selection metric.",
                status_code=409,
            )
        source_result_fingerprints = {
            str(item.get("resultFingerprint") or "")
            for item in selected_source_attempts
        }
        exact_attempt_evidence = [
            {
                "attemptId": item["attemptId"],
                "runId": item["runId"],
                "runReceiptSha256": item["runReceiptSha256"],
                "receiptSchemaVersion": item["receiptSchemaVersion"],
                "createdAt": item["createdAt"],
                "resultFingerprint": item["resultFingerprint"],
            }
            for item in selected_source_attempts
        ]
        selected.append(
            {
                "candidateFingerprint": fingerprint,
                "modelFamily": candidate["modelFamily"],
                "featureSetId": candidate["featureSetId"],
                "meanOofLogLoss": float(np.mean(source_losses)),
                "evidenceSource": evidence_source,
                "representativeAttemptId": representative["attemptId"],
                "representativeRunId": representative["runId"],
                "immutableEvidenceIdentity": representative["runReceiptSha256"],
                "attemptEvidence": exact_attempt_evidence,
                "warnings": ["REPRODUCIBILITY_REVIEW_REQUIRED"]
                if len(source_result_fingerprints) > 1
                else [],
                # Retained for readers of the original receipt contract.  The
                # structured attemptEvidence above is the exact authority.
                "attemptReceiptSha256s": [
                    item["runReceiptSha256"] for item in selected_source_attempts
                ],
            }
        )
    prior_row, _prior_parameters = _current_finalist_authority(database, project_id)
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
        "evaluationBatch": evidence_source,
        "evidenceSource": evidence_source,
        "supersedesSelectionId": prior_row.get("run_id") if prior_row else None,
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
        try:
            evidence_source = _current_finalist_source(
                database, project_id, fingerprint, candidate
            )
        except Stage3ModelLaboratoryError as exc:
            if exc.code == "STAGE3_REFINEMENT_FINALIST_REQUIRED":
                raise Stage3ModelLaboratoryError(
                    "STAGE3_ANALYSIS_FINALIST_REQUIRED",
                    "SHAP and sensitivity require the current immutable finalist selection receipt.",
                    status_code=409,
                ) from exc
            raise
        resolved, candidate = _candidate_group(
            database,
            project_id,
            fingerprint,
            evidence_source=evidence_source,
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
    evidence_source, finalist_binding = _current_finalist_binding(
        database, project_id, fingerprint, candidate
    )
    resolved, candidate = _candidate_group(
        database,
        project_id,
        fingerprint,
        evidence_source=evidence_source,
    )
    if candidate["status"] != "COMPLETE":
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_PARENT_EVIDENCE_MISSING",
            "The current source-bound finalist has no completed immutable attempt.",
            status_code=409,
        )
    current_selection_row, _current_selection_parameters = (
        _current_finalist_authority(database, project_id)
    )
    parent_attempt = next(
        (
            item
            for item in candidate["attempts"]
            if item.get("status") == "COMPLETE"
            and item.get("attemptId")
            == finalist_binding.get("representativeAttemptId")
            and item.get("runId") == finalist_binding.get("representativeRunId")
            and item.get("runReceiptSha256")
            == finalist_binding.get("immutableEvidenceIdentity")
        ),
        None,
    )
    if parent_attempt is None:
        raise Stage3ModelLaboratoryError(
            "STAGE3_REFINEMENT_PARENT_EVIDENCE_MISSING",
            "The current source-bound finalist has no exact representative attempt.",
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
        "finalistSelectionId": current_selection_row.get("run_id")
        if current_selection_row
        else None,
        "parentCandidateFingerprint": fingerprint,
        "parentEvidenceSource": evidence_source,
        "parentAttemptId": parent_attempt["attemptId"],
        "parentRunId": parent_attempt["runId"],
        "parentRunReceiptSha256": parent_attempt["runReceiptSha256"],
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
        database,
        project_id,
        str(plan["parentCandidateFingerprint"]),
        evidence_source=str(plan.get("parentEvidenceSource") or ""),
    )
    attempt = next(
        (
            item
            for item in candidate["attempts"]
            if item["status"] == "COMPLETE"
            and item.get("attemptId") == plan.get("parentAttemptId")
            and item.get("runId") == plan.get("parentRunId")
            and item.get("runReceiptSha256")
            == plan.get("parentRunReceiptSha256")
        ),
        None,
    )
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


def _ordered_downstream_rows(
    database: Database, project_id: str, run_type: str
) -> list[dict[str, Any]]:
    return sorted(
        _decision_rows(database, project_id, run_type),
        key=lambda row: (
            str(row.get("started_at") or row.get("completed_at") or ""),
            str(row.get("run_id") or ""),
        ),
        reverse=True,
    )


def _downstream_receipts(
    database: Database, project_id: str, run_type: str
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    rows = _ordered_downstream_rows(database, project_id, run_type)
    current_id = rows[0].get("run_id") if rows else None
    for row in rows:
        body = json_loads(row.get("parameters_json"), {})
        artifacts = json_loads(row.get("artifacts_json"), {})
        if not isinstance(body, Mapping) or not isinstance(artifacts, Mapping):
            raise _evidence_shape_error(
                "A Stage 3 downstream decision receipt must decode to JSON objects."
            )
        receipts.append(
            {
                **dict(body),
                "receiptSha256": artifacts.get("receiptSha256"),
                "authorityStatus": (
                    "CURRENT" if row.get("run_id") == current_id else "SUPERSEDED"
                ),
                "ledgerStatus": row.get("status"),
            }
        )
    return receipts


def _current_downstream_receipt(
    database: Database, project_id: str, run_type: str
) -> dict[str, Any] | None:
    receipts = _downstream_receipts(database, project_id, run_type)
    return receipts[0] if receipts else None


def _current_finalist_details(
    database: Database, project_id: str
) -> tuple[Any, str | None, list[dict[str, Any]]]:
    resolved = resolve_model_lab_authority(database, project_id)
    selection_row, parameters = _current_finalist_authority(database, project_id)
    fingerprints = parameters.get("candidateFingerprints") or []
    if not isinstance(fingerprints, list):
        raise _evidence_shape_error(
            "The current finalist selection candidateFingerprints must be a JSON array."
        )
    all_groups = {
        item["candidateFingerprint"]: item
        for item in _group_attempts(_read_runs(project_id, resolved))
    }
    finalists: list[dict[str, Any]] = []
    for raw_fingerprint in fingerprints:
        fingerprint = str(raw_fingerprint)
        all_source_candidate = all_groups.get(fingerprint)
        if all_source_candidate is None:
            raise Stage3ModelLaboratoryError(
                "STAGE3_CURRENT_FINALIST_EVIDENCE_MISSING",
                "A current finalist no longer resolves to verified project-bound evidence.",
                status_code=409,
            )
        evidence_source, binding = _current_finalist_binding(
            database, project_id, fingerprint, all_source_candidate
        )
        _resolved, candidate = _candidate_group(
            database,
            project_id,
            fingerprint,
            evidence_source=evidence_source,
        )
        attempt = next(
            (
                item
                for item in candidate.get("attempts") or []
                if item.get("status") == "COMPLETE"
                and item.get("attemptId") == binding.get("representativeAttemptId")
                and item.get("runId") == binding.get("representativeRunId")
                and item.get("runReceiptSha256")
                == binding.get("immutableEvidenceIdentity")
            ),
            None,
        )
        if attempt is None:
            raise Stage3ModelLaboratoryError(
                "STAGE3_CURRENT_FINALIST_ATTEMPT_MISSING",
                "A current finalist no longer resolves to its exact representative attempt.",
                status_code=409,
            )
        evaluation = attempt.get("evaluationEvidence")
        reloadable_sha = (
            evaluation.get("reloadableArtifactSha256")
            if isinstance(evaluation, Mapping)
            else None
        )
        finalists.append(
            {
                "candidateFingerprint": fingerprint,
                "modelFamily": candidate.get("modelFamily"),
                "featureSetId": candidate.get("featureSetId"),
                "featureSetName": candidate.get("featureSetName"),
                "featureCount": candidate.get("featureCount"),
                "meanOofLogLoss": attempt.get("meanOofLogLoss"),
                "summedBrier": attempt.get("summedBrier"),
                "ece": attempt.get("ece"),
                "macroF1": attempt.get("macroF1"),
                "accuracy": attempt.get("accuracy"),
                "foldStandardDeviation": attempt.get("foldStandardDeviation"),
                "foldsCompleted": attempt.get("foldsCompleted"),
                "runtimeMs": attempt.get("runtimeMs"),
                "classCalibration": attempt.get("classCalibration") or [],
                "folds": attempt.get("folds") or [],
                "evidenceSource": evidence_source,
                "attemptId": attempt.get("attemptId"),
                "runId": attempt.get("runId"),
                "runReceiptSha256": attempt.get("runReceiptSha256"),
                "resultFingerprint": attempt.get("resultFingerprint"),
                "reloadableArtifactSha256": reloadable_sha,
                "reloadableArtifactAvailable": bool(reloadable_sha),
                "rowLevelOofArtifactAvailable": bool(
                    reloadable_sha
                    and isinstance(evaluation, Mapping)
                    and evaluation.get("status") == "AVAILABLE"
                ),
            }
        )
    return (
        resolved,
        str(selection_row.get("run_id")) if selection_row else None,
        finalists,
    )


def _historical_development_benchmark(
    project_id: str, resolved: Any
) -> dict[str, Any] | None:
    historical = _group_attempts(
        [
            run
            for run in _read_runs(project_id, resolved)
            if run.get("schemaVersion") == RUN_RECEIPT_SCHEMA_VERSION
        ]
    )
    best = next(
        (
            item
            for item in historical
            if item.get("rankingEligible")
            and item.get("meanOofLogLoss") is not None
        ),
        None,
    )
    if best is None:
        return None
    return {
        "candidateFingerprint": best.get("candidateFingerprint"),
        "modelFamily": best.get("modelFamily"),
        "featureSetId": best.get("featureSetId"),
        "featureSetName": best.get("featureSetName"),
        "meanOofLogLoss": best.get("meanOofLogLoss"),
        "evidenceSource": "HISTORICAL_BASELINE",
        "immutableEvidenceIdentity": best.get("immutableEvidenceIdentity"),
    }


def _require_current_finalist(
    database: Database, project_id: str, fingerprint: str
) -> tuple[Any, str, dict[str, Any]]:
    resolved, selection_id, finalists = _current_finalist_details(database, project_id)
    if not selection_id:
        raise Stage3ModelLaboratoryError(
            "STAGE3_CURRENT_FINALIST_SELECTION_REQUIRED",
            "Select and save at least one current project finalist before continuing.",
            status_code=409,
        )
    candidate = next(
        (
            item
            for item in finalists
            if item.get("candidateFingerprint") == fingerprint
        ),
        None,
    )
    if candidate is None:
        raise Stage3ModelLaboratoryError(
            "STAGE3_CURRENT_FINALIST_REQUIRED",
            "The requested candidate is not part of the current immutable finalist selection.",
            status_code=409,
        )
    return resolved, selection_id, candidate


def resolve_current_research_challenger(
    database: Database, project_id: str
) -> dict[str, Any]:
    """Resolve the complete, current research-challenger decision chain.

    Artifact construction is materially different from selecting an arbitrary
    finalist.  It is authorized only by one internally consistent chain:
    finalist -> calibration disposition -> game-evaluation disposition ->
    research-challenger decision -> metadata-only research handoff.  The
    returned private source objects let the artifact worker reproduce the exact
    representative attempt without treating a later/latest policy or run as an
    equivalent substitute.
    """

    resolved, finalist_selection_id, finalists = _current_finalist_details(
        database, project_id
    )
    calibration = _current_downstream_receipt(
        database, project_id, CALIBRATION_DECISION_RUN_TYPE
    )
    game_evaluation = _current_downstream_receipt(
        database, project_id, GAME_EVALUATION_DECISION_RUN_TYPE
    )
    selection = _current_downstream_receipt(
        database, project_id, CHALLENGER_DECISION_RUN_TYPE
    )
    handoff = _current_downstream_receipt(
        database, project_id, REGISTRY_HANDOFF_RUN_TYPE
    )
    fingerprint = str((selection or {}).get("candidateFingerprint") or "")
    candidate = next(
        (
            item
            for item in finalists
            if item.get("candidateFingerprint") == fingerprint
        ),
        None,
    )
    if (
        not finalist_selection_id
        or not calibration
        or not game_evaluation
        or not selection
        or not handoff
        or candidate is None
        or calibration.get("finalistSelectionId") != finalist_selection_id
        or calibration.get("candidateFingerprint") != fingerprint
        or calibration.get("disposition") != "RETAIN_RAW"
        or calibration.get("calibrationApplied") is not False
        or game_evaluation.get("finalistSelectionId") != finalist_selection_id
        or game_evaluation.get("candidateFingerprint") != fingerprint
        or game_evaluation.get("calibrationDecisionId")
        != calibration.get("decisionId")
        or selection.get("finalistSelectionId") != finalist_selection_id
        or selection.get("calibrationDecisionId") != calibration.get("decisionId")
        or selection.get("gameEvaluationDecisionId")
        != game_evaluation.get("decisionId")
        or selection.get("decision") != "REGISTER_RESEARCH_CHALLENGER"
        or selection.get("modelStatus") != "RESEARCH_CHALLENGER"
        or selection.get("promotionStatus") != "NOT_PROMOTED"
        or selection.get("championSelected") is not False
        or handoff.get("finalistSelectionId") != finalist_selection_id
        or handoff.get("selectionDecisionId") != selection.get("decisionId")
        or handoff.get("candidateFingerprint") != fingerprint
        or handoff.get("candidateAttemptId") != candidate.get("attemptId")
        or handoff.get("candidateRunReceiptSha256")
        != candidate.get("runReceiptSha256")
        or handoff.get("modelStatus") != "RESEARCH_CHALLENGER"
        or handoff.get("promotionStatus") != "NOT_PROMOTED"
        or handoff.get("modelsPromoted") != 0
        or handoff.get("finalOotTargetAccessed") is not False
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_RESEARCH_CHALLENGER_CHAIN_STALE",
            "The current finalist, review, challenger, and research-handoff receipts do not form one exact current authority chain.",
            status_code=409,
        )

    source_run = next(
        (
            run
            for run in _read_runs(project_id, resolved)
            if run.get("runId") == candidate.get("runId")
            and run.get("runReceiptSha256") == candidate.get("runReceiptSha256")
        ),
        None,
    )
    source_candidate = next(
        (
            item
            for item in (source_run or {}).get("candidates") or []
            if isinstance(item, Mapping)
            and item.get("candidateId") == candidate.get("attemptId")
        ),
        None,
    )
    if (
        source_run is None
        or source_candidate is None
        or source_candidate.get("status") != "COMPLETE"
        or candidate_specification_fingerprint(source_run, source_candidate)
        != fingerprint
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_RESEARCH_CHALLENGER_SOURCE_STALE",
            "The research challenger no longer resolves to its exact verified representative run and attempt.",
            status_code=409,
        )
    experiment = _experiment_for_candidate(source_run, source_candidate)
    feature_contract = experiment.get("featureSetContract") or {}
    if not isinstance(feature_contract, Mapping):
        raise _evidence_shape_error(
            "The research challenger's feature-set contract must be an object."
        )
    attempt_receipt_sha = next(
        (
            item.get("candidateReceiptSha256")
            for item in source_run.get("candidateAttemptReceipts") or []
            if isinstance(item, Mapping)
            and item.get("candidateId") == source_candidate.get("candidateId")
        ),
        None,
    )
    return {
        "projectId": project_id,
        "finalistSelectionId": finalist_selection_id,
        "calibrationDecisionId": calibration.get("decisionId"),
        "gameEvaluationDecisionId": game_evaluation.get("decisionId"),
        "selectionDecisionId": selection.get("decisionId"),
        "researchHandoffId": handoff.get("decisionId"),
        "registryEntryId": handoff.get("registryEntryId"),
        "candidateFingerprint": fingerprint,
        "candidateAttemptId": candidate.get("attemptId"),
        "candidateAttemptReceiptSha256": attempt_receipt_sha,
        "candidateRunId": candidate.get("runId"),
        "candidateRunReceiptSha256": candidate.get("runReceiptSha256"),
        "candidate": dict(candidate),
        "sourceRun": source_run,
        "sourceCandidate": source_candidate,
        "experiment": dict(experiment),
        "featureSetContract": dict(feature_contract),
        "calibration": calibration,
        "gameEvaluation": game_evaluation,
        "selection": selection,
        "handoff": handoff,
        "resolvedAuthority": resolved,
    }


def _persist_downstream_decision(
    database: Database,
    *,
    project_id: str,
    actor_user_id: str,
    kind: str,
    run_type: str,
    workflow_type: str,
    body: Mapping[str, Any],
) -> dict[str, Any]:
    persisted = _persist_object(kind, body)
    RunRepository(database).upsert(
        {
            "run_id": body["decisionId"],
            "project_id": project_id,
            "run_type": run_type,
            "workflow_type": workflow_type,
            "status": body["status"],
            "started_at": body["createdAt"],
            "completed_at": body["createdAt"],
            "parameters_json": dict(body),
            "metrics_json": {
                "modelFits": 0,
                "modelsPromoted": 0,
                "finalOotRowsAccessed": 0,
            },
            "artifacts_json": {"receiptSha256": persisted["receiptSha256"]},
            "error_json": {},
            "created_by": actor_user_id,
        }
    )
    return persisted


@project_read_view
def project_stage3_downstream(
    database: Database, project_id: str
) -> dict[str, Any]:
    resolved, finalist_selection_id, finalists = _current_finalist_details(
        database, project_id
    )
    historical_benchmark = _historical_development_benchmark(project_id, resolved)
    calibration = _downstream_receipts(
        database, project_id, CALIBRATION_DECISION_RUN_TYPE
    )
    game_evaluation = _downstream_receipts(
        database, project_id, GAME_EVALUATION_DECISION_RUN_TYPE
    )
    selections = _downstream_receipts(
        database, project_id, CHALLENGER_DECISION_RUN_TYPE
    )
    registry = _downstream_receipts(
        database, project_id, REGISTRY_HANDOFF_RUN_TYPE
    )
    current_calibration = calibration[0] if calibration else None
    current_game_evaluation = game_evaluation[0] if game_evaluation else None
    current_selection = selections[0] if selections else None
    current_registry = registry[0] if registry else None
    finalist_fingerprints = {
        str(item.get("candidateFingerprint") or "") for item in finalists
    }
    calibration_current = bool(
        current_calibration
        and current_calibration.get("finalistSelectionId") == finalist_selection_id
        and current_calibration.get("candidateFingerprint") in finalist_fingerprints
    )
    game_current = bool(
        current_game_evaluation
        and calibration_current
        and current_game_evaluation.get("finalistSelectionId") == finalist_selection_id
        and current_game_evaluation.get("candidateFingerprint")
        == current_calibration.get("candidateFingerprint")
        and current_game_evaluation.get("calibrationDecisionId")
        == current_calibration.get("decisionId")
    )
    selection_current_for_finalists = bool(
        current_selection
        and current_selection.get("finalistSelectionId") == finalist_selection_id
        and (
            not current_selection.get("candidateFingerprint")
            or current_selection.get("candidateFingerprint") in finalist_fingerprints
        )
    )
    selection_current = bool(
        selection_current_for_finalists
        and (
            current_selection.get("decision") != "REGISTER_RESEARCH_CHALLENGER"
            or (
                game_current
                and current_selection.get("candidateFingerprint")
                == current_game_evaluation.get("candidateFingerprint")
                and current_selection.get("calibrationDecisionId")
                == current_calibration.get("decisionId")
                and current_selection.get("gameEvaluationDecisionId")
                == current_game_evaluation.get("decisionId")
            )
        )
    )
    registry_current = bool(
        current_registry
        and selection_current
        and current_selection.get("decision") == "REGISTER_RESEARCH_CHALLENGER"
        and current_registry.get("finalistSelectionId") == finalist_selection_id
        and current_registry.get("selectionDecisionId")
        == current_selection.get("decisionId")
        and current_registry.get("candidateFingerprint")
        == current_selection.get("candidateFingerprint")
    )
    return {
        "ok": True,
        "schemaVersion": DOWNSTREAM_SCHEMA_VERSION,
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
            "finalistSelectionId": finalist_selection_id,
            "legacyGlobalMatrixUsed": False,
            "base22FallbackAvailable": False,
        },
        "population": {
            "scope": "DEVELOPMENT_ONLY",
            "developmentRows": int(resolved.split["development"]["rows"]),
            "startDate": str(resolved.split["development"]["startDate"]),
            "endDate": str(resolved.split["development"]["endDate"]),
            "finalOotRows": int(resolved.split["finalOot"]["rows"]),
            "finalOotStartDate": str(resolved.split["finalOot"]["startDate"]),
            "finalOotEndDate": str(resolved.split["finalOot"]["endDate"]),
            "finalOotLocked": True,
            "finalOotTargetAccessed": False,
            "finalOotScored": False,
        },
        "finalists": finalists,
        "historicalBenchmark": historical_benchmark,
        "calibrationDecisions": calibration,
        "gameEvaluationDecisions": game_evaluation,
        "selectionDecisions": selections,
        "registryEntries": registry,
        "gates": {
            "calibrationReady": bool(finalists),
            "calibrationDecisionCurrent": calibration_current,
            "gameEvaluationReady": calibration_current,
            "gameEvaluationDecisionCurrent": game_current,
            "challengerDecisionReady": calibration_current and game_current,
            "challengerDecisionCurrent": selection_current,
            "registryHandoffReady": bool(
                selection_current
                and current_selection.get("decision")
                == "REGISTER_RESEARCH_CHALLENGER"
            ),
            "registryHandoffCurrent": registry_current,
        },
        "limitations": {
            "rowLevelOofPredictions": "NOT_PERSISTED_IN_CURRENT_RECEIPTS",
            "reloadableModelArtifact": "NOT_PERSISTED_IN_CURRENT_RECEIPTS",
            "pregameLineupStarterAuthority": "NOT_AVAILABLE_FOR_CURRENT_GOLD",
            "postHocCalibrationExecutable": False,
            "wholeGameSimulationExecutable": False,
            "finalOotEvaluationAuthorized": False,
            "deploymentExecutable": False,
        },
        "activity": {
            "newFitsOnPageLoad": 0,
            "calibrationFits": 0,
            "simulationRuns": 0,
            "finalOotRowsAccessed": 0,
            "providerCalls": 0,
            "modelsPromoted": 0,
            "modelsExported": 0,
        },
        "workflowStatus": (
            "RESEARCH_HANDOFF_RECORDED"
            if registry_current
            else "RESEARCH_CHALLENGER_DECISION_RECORDED"
            if selection_current
            else "DEVELOPMENT_REVIEW_IN_PROGRESS"
        ),
    }


def save_project_calibration_decision(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    fingerprint = str(payload.get("candidateFingerprint") or "")
    disposition = str(payload.get("disposition") or "").upper()
    if disposition not in {"RETAIN_RAW", "DEFER_RECALIBRATION"}:
        raise Stage3ModelLaboratoryError(
            "STAGE3_CALIBRATION_DISPOSITION_INVALID",
            "Choose RETAIN_RAW or DEFER_RECALIBRATION for the current aggregate-only evidence.",
        )
    resolved, finalist_selection_id, candidate = _require_current_finalist(
        database, project_id, fingerprint
    )
    rationale = str(payload.get("rationale") or "").strip() or (
        "Record that no post-hoc calibration is applied to the finalist's aggregate five-fold OOF evidence."
        if disposition == "RETAIN_RAW"
        else "Defer post-hoc calibration until row-level OOF predictions are captured."
    )
    body = {
        "schemaVersion": CALIBRATION_DECISION_SCHEMA_VERSION,
        "decisionId": "stage3-calibration-decision-" + uuid.uuid4().hex,
        "createdAt": now_iso(),
        "createdByUserId": actor_user_id,
        "projectId": project_id,
        "authorityKey": resolved.authority_key,
        "goldDatasetId": CURRENT_GOLD_DATASET_ID,
        "goldManifestSha": resolved.eda_authority.gold_manifest_sha,
        "finalistSelectionId": finalist_selection_id,
        "candidateFingerprint": fingerprint,
        "candidateAttemptId": candidate["attemptId"],
        "candidateRunReceiptSha256": candidate["runReceiptSha256"],
        "evidenceSource": candidate["evidenceSource"],
        "disposition": disposition,
        "status": (
            "NO_POSTHOC_CALIBRATION_SELECTED"
            if disposition == "RETAIN_RAW"
            else "POSTHOC_CALIBRATION_DEFERRED"
        ),
        "rationale": rationale,
        "rawMetrics": {
            "meanOofLogLoss": candidate["meanOofLogLoss"],
            "summedBrier": candidate["summedBrier"],
            "ece": candidate["ece"],
            "classCalibration": candidate["classCalibration"],
        },
        "calibrationApplied": False,
        "calibrationMethod": (
            "NONE_NO_POSTHOC_CALIBRATION"
            if disposition == "RETAIN_RAW"
            else "NOT_EVALUATED_DEFERRED"
        ),
        "aggregateOnlyEvidence": True,
        "rowLevelOofProbabilitiesPersisted": False,
        "rowLevelOofArtifactAvailable": candidate["rowLevelOofArtifactAvailable"],
        "modelsFit": 0,
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
        "modelsPromoted": 0,
    }
    persisted = _persist_downstream_decision(
        database,
        project_id=project_id,
        actor_user_id=actor_user_id,
        kind="calibration-decisions",
        run_type=CALIBRATION_DECISION_RUN_TYPE,
        workflow_type="sports_stage3_calibration",
        body=body,
    )
    return {"ok": True, "decision": persisted}


def save_project_game_evaluation_decision(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    fingerprint = str(payload.get("candidateFingerprint") or "")
    disposition = str(payload.get("disposition") or "").upper()
    if disposition != "DEFER_UNTIL_EXECUTABLE_ARTIFACT":
        raise Stage3ModelLaboratoryError(
            "STAGE3_GAME_EVALUATION_DISPOSITION_INVALID",
            "The current evidence supports only an explicit deferral until an executable artifact and pregame participant authority exist.",
        )
    resolved, finalist_selection_id, candidate = _require_current_finalist(
        database, project_id, fingerprint
    )
    calibration = _current_downstream_receipt(
        database, project_id, CALIBRATION_DECISION_RUN_TYPE
    )
    if (
        not calibration
        or calibration.get("finalistSelectionId") != finalist_selection_id
        or calibration.get("candidateFingerprint") != fingerprint
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_CURRENT_CALIBRATION_DECISION_REQUIRED",
            "Save the current finalist's calibration disposition before recording game-evaluation readiness.",
            status_code=409,
        )
    rationale = str(payload.get("rationale") or "").strip() or (
        "Defer whole-game evaluation until a reloadable model and governed pregame lineup/starter authority exist."
    )
    body = {
        "schemaVersion": GAME_EVALUATION_DECISION_SCHEMA_VERSION,
        "decisionId": "stage3-game-evaluation-decision-" + uuid.uuid4().hex,
        "createdAt": now_iso(),
        "createdByUserId": actor_user_id,
        "projectId": project_id,
        "authorityKey": resolved.authority_key,
        "goldDatasetId": CURRENT_GOLD_DATASET_ID,
        "goldManifestSha": resolved.eda_authority.gold_manifest_sha,
        "finalistSelectionId": finalist_selection_id,
        "candidateFingerprint": fingerprint,
        "candidateAttemptId": candidate["attemptId"],
        "candidateRunReceiptSha256": candidate["runReceiptSha256"],
        "calibrationDecisionId": calibration["decisionId"],
        "disposition": disposition,
        "status": "GAME_EVALUATION_DEFERRED_MISSING_PREREQUISITES",
        "rationale": rationale,
        "missingPrerequisites": [
            "RELOADABLE_MODEL_ARTIFACT",
            "ROW_LEVEL_OOF_PREDICTIONS",
            "GOVERNED_PREGAME_LINEUP_AUTHORITY",
            "GOVERNED_PREGAME_STARTER_AUTHORITY",
        ],
        "gameSimulationRun": False,
        "gameLevelMetricsAvailable": False,
        "developmentResearchSelectionMayContinue": True,
        "deploymentMayContinue": False,
        "modelsFit": 0,
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
        "modelsPromoted": 0,
    }
    persisted = _persist_downstream_decision(
        database,
        project_id=project_id,
        actor_user_id=actor_user_id,
        kind="game-evaluation-decisions",
        run_type=GAME_EVALUATION_DECISION_RUN_TYPE,
        workflow_type="sports_stage3_game_evaluation",
        body=body,
    )
    return {"ok": True, "decision": persisted}


def save_project_challenger_decision(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    decision = str(payload.get("decision") or "").upper()
    if decision not in {
        "REGISTER_RESEARCH_CHALLENGER",
        "KEEP_INCUMBENT",
        "DEFER_DECISION",
    }:
        raise Stage3ModelLaboratoryError(
            "STAGE3_CHALLENGER_DECISION_INVALID",
            "Choose REGISTER_RESEARCH_CHALLENGER, KEEP_INCUMBENT, or DEFER_DECISION.",
        )
    fingerprint = str(payload.get("candidateFingerprint") or "")
    resolved, finalist_selection_id, finalists = _current_finalist_details(
        database, project_id
    )
    if not finalist_selection_id:
        raise Stage3ModelLaboratoryError(
            "STAGE3_CURRENT_FINALIST_SELECTION_REQUIRED",
            "A current immutable finalist selection is required.",
            status_code=409,
        )
    candidate = next(
        (
            item
            for item in finalists
            if item.get("candidateFingerprint") == fingerprint
        ),
        None,
    )
    if decision == "REGISTER_RESEARCH_CHALLENGER" and candidate is None:
        raise Stage3ModelLaboratoryError(
            "STAGE3_CURRENT_FINALIST_REQUIRED",
            "Select one current finalist as the research challenger.",
            status_code=409,
        )
    calibration = _current_downstream_receipt(
        database, project_id, CALIBRATION_DECISION_RUN_TYPE
    )
    game_evaluation = _current_downstream_receipt(
        database, project_id, GAME_EVALUATION_DECISION_RUN_TYPE
    )
    if decision == "REGISTER_RESEARCH_CHALLENGER" and (
        not calibration
        or not game_evaluation
        or calibration.get("finalistSelectionId") != finalist_selection_id
        or game_evaluation.get("finalistSelectionId") != finalist_selection_id
        or calibration.get("candidateFingerprint") != fingerprint
        or game_evaluation.get("candidateFingerprint") != fingerprint
        or game_evaluation.get("calibrationDecisionId")
        != calibration.get("decisionId")
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_CURRENT_DOWNSTREAM_REVIEW_REQUIRED",
            "Save calibration and game-evaluation dispositions for the same current finalist before advancing it.",
            status_code=409,
        )
    benchmark = _historical_development_benchmark(project_id, resolved)
    candidate_loss = candidate.get("meanOofLogLoss") if candidate else None
    benchmark_loss = benchmark.get("meanOofLogLoss") if benchmark else None
    delta = (
        float(candidate_loss) - float(benchmark_loss)
        if candidate_loss is not None and benchmark_loss is not None
        else None
    )
    rationale = str(payload.get("rationale") or "").strip() or {
        "REGISTER_RESEARCH_CHALLENGER": "Advance this finalist for research-only artifact completion and prospective validation.",
        "KEEP_INCUMBENT": "Retain the existing historical baseline while preserving the new finalist evidence.",
        "DEFER_DECISION": "Defer a challenger decision while preserving all development evidence.",
    }[decision]
    status = {
        "REGISTER_RESEARCH_CHALLENGER": "RESEARCH_CHALLENGER_SELECTED",
        "KEEP_INCUMBENT": "INCUMBENT_RETAINED",
        "DEFER_DECISION": "DECISION_DEFERRED",
    }[decision]
    body = {
        "schemaVersion": CHALLENGER_DECISION_SCHEMA_VERSION,
        "decisionId": "stage3-challenger-decision-" + uuid.uuid4().hex,
        "createdAt": now_iso(),
        "createdByUserId": actor_user_id,
        "projectId": project_id,
        "authorityKey": resolved.authority_key,
        "goldDatasetId": CURRENT_GOLD_DATASET_ID,
        "goldManifestSha": resolved.eda_authority.gold_manifest_sha,
        "finalistSelectionId": finalist_selection_id,
        "candidateFingerprint": fingerprint if candidate else None,
        "candidateAttemptId": candidate.get("attemptId") if candidate else None,
        "candidateRunReceiptSha256": (
            candidate.get("runReceiptSha256") if candidate else None
        ),
        "decision": decision,
        "status": status,
        "rationale": rationale,
        "developmentComparison": {
            "candidateMeanOofLogLoss": candidate_loss,
            "historicalBenchmarkMeanOofLogLoss": benchmark_loss,
            "candidateMinusBenchmarkLogLoss": delta,
            "candidateOutperformedBenchmark": delta is not None and delta < 0,
            "outperformanceRequiredToRegisterResearchChallenger": False,
        },
        "calibrationDecisionId": (
            calibration.get("decisionId") if calibration else None
        ),
        "gameEvaluationDecisionId": (
            game_evaluation.get("decisionId") if game_evaluation else None
        ),
        "modelStatus": (
            "RESEARCH_CHALLENGER"
            if decision == "REGISTER_RESEARCH_CHALLENGER"
            else "NOT_SELECTED"
        ),
        "championSelected": False,
        "promotionStatus": "NOT_PROMOTED",
        "deploymentStatus": "NOT_DEPLOYABLE",
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
        "modelsPromoted": 0,
    }
    persisted = _persist_downstream_decision(
        database,
        project_id=project_id,
        actor_user_id=actor_user_id,
        kind="challenger-decisions",
        run_type=CHALLENGER_DECISION_RUN_TYPE,
        workflow_type="sports_stage3_challenger_decision",
        body=body,
    )
    return {"ok": True, "decision": persisted}


def register_project_research_handoff(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    selection = _current_downstream_receipt(
        database, project_id, CHALLENGER_DECISION_RUN_TYPE
    )
    requested_selection_id = str(payload.get("selectionId") or "")
    resolved, finalist_selection_id, finalists = _current_finalist_details(
        database, project_id
    )
    if (
        not selection
        or selection.get("decision") != "REGISTER_RESEARCH_CHALLENGER"
        or selection.get("decisionId") != requested_selection_id
        or selection.get("finalistSelectionId") != finalist_selection_id
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_RESEARCH_CHALLENGER_SELECTION_REQUIRED",
            "The current research-challenger selection receipt is required for registration.",
            status_code=409,
        )
    fingerprint = str(selection.get("candidateFingerprint") or "")
    candidate = next(
        (
            item
            for item in finalists
            if item.get("candidateFingerprint") == fingerprint
        ),
        None,
    )
    if candidate is None:
        raise Stage3ModelLaboratoryError(
            "STAGE3_CURRENT_FINALIST_REQUIRED",
            "The research-challenger selection no longer resolves to a current finalist.",
            status_code=409,
        )
    calibration = _current_downstream_receipt(
        database, project_id, CALIBRATION_DECISION_RUN_TYPE
    )
    game_evaluation = _current_downstream_receipt(
        database, project_id, GAME_EVALUATION_DECISION_RUN_TYPE
    )
    if (
        not calibration
        or not game_evaluation
        or calibration.get("finalistSelectionId") != finalist_selection_id
        or game_evaluation.get("finalistSelectionId") != finalist_selection_id
        or selection.get("calibrationDecisionId") != calibration.get("decisionId")
        or selection.get("gameEvaluationDecisionId")
        != game_evaluation.get("decisionId")
        or game_evaluation.get("calibrationDecisionId")
        != calibration.get("decisionId")
        or calibration.get("candidateFingerprint") != fingerprint
        or game_evaluation.get("candidateFingerprint") != fingerprint
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_CURRENT_DOWNSTREAM_REVIEW_REQUIRED",
            "The research-challenger selection no longer resolves to the current calibration and game-evaluation decision chain.",
            status_code=409,
        )
    existing = _current_downstream_receipt(
        database, project_id, REGISTRY_HANDOFF_RUN_TYPE
    )
    if (
        existing
        and existing.get("selectionDecisionId") == requested_selection_id
        and existing.get("finalistSelectionId") == finalist_selection_id
        and existing.get("candidateFingerprint") == fingerprint
    ):
        return {"ok": True, "entry": existing, "idempotentReplay": True}
    body = {
        "schemaVersion": REGISTRY_HANDOFF_SCHEMA_VERSION,
        "decisionId": "stage3-research-handoff-" + uuid.uuid4().hex,
        "registryEntryId": "stage3-research-challenger-" + uuid.uuid4().hex,
        "createdAt": now_iso(),
        "createdByUserId": actor_user_id,
        "projectId": project_id,
        "authorityKey": resolved.authority_key,
        "goldDatasetId": CURRENT_GOLD_DATASET_ID,
        "goldManifestSha": resolved.eda_authority.gold_manifest_sha,
        "finalistSelectionId": finalist_selection_id,
        "selectionDecisionId": requested_selection_id,
        "candidateFingerprint": fingerprint,
        "candidateAttemptId": candidate["attemptId"],
        "candidateRunReceiptSha256": candidate["runReceiptSha256"],
        "modelFamily": candidate["modelFamily"],
        "featureSetId": candidate["featureSetId"],
        "featureSetName": candidate["featureSetName"],
        "featureCount": candidate["featureCount"],
        "status": "RESEARCH_CHALLENGER_HANDOFF_RECORDED",
        "modelStatus": "RESEARCH_CHALLENGER",
        "promotionStatus": "NOT_PROMOTED",
        "artifactStatus": "EXECUTABLE_ARTIFACT_NOT_MATERIALIZED",
        "exportStatus": "NOT_EXPORTED",
        "deploymentStatus": "NOT_DEPLOYABLE",
        "implementationStatus": "DEVELOPMENT_EVIDENCE_REGISTERED",
        "nextRequiredAction": "MATERIALIZE_RELOADABLE_MODEL_AND_ROW_LEVEL_OOF_EVIDENCE_THEN_RUN_GAME_LEVEL_VALIDATION",
        "historicalEvidencePreserved": True,
        "primaryBankrollAffected": False,
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
        "modelsFit": 0,
        "modelsPromoted": 0,
    }
    persisted = _persist_downstream_decision(
        database,
        project_id=project_id,
        actor_user_id=actor_user_id,
        kind="research-handoffs",
        run_type=REGISTRY_HANDOFF_RUN_TYPE,
        workflow_type="sports_stage3_registry_handoff",
        body=body,
    )
    return {"ok": True, "entry": persisted, "idempotentReplay": False}


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
    "resolve_current_research_challenger",
    "request_candidate_analysis",
    "save_finalist_selection",
    "project_stage3_downstream",
    "register_project_research_handoff",
    "save_project_calibration_decision",
    "save_project_challenger_decision",
    "save_project_game_evaluation_decision",
]

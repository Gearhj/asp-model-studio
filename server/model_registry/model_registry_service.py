"""ATLAS Durable Model Registry -- domain service.

This is the ONLY place a Model or ModelVersion row is created, read, listed,
compared, or archived. Every entry point re-authorizes via
authorize_modeling_scope, exactly like scoring_run_service.py and every other
ATLAS modeling endpoint -- a model's projectId is never trusted as its own
authorization signal.

A ModelVersion is immutable once created (Phase B requirement). Generic fitted
publication and the explicit reference-only conditional V18 decision are separate
authorized paths; neither may rewrite an existing version. The
ModelVersionRepository has no update-content method -- only
set_governance_status() (approval/validation/documentation stage transitions,
not content) and archive() exist as post-creation mutations.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from ..core.modeling_scope import authorize_modeling_scope
from ..governance.selection_integrity import (
    SelectionIntegrityError,
    assert_selection_integrity,
)
from ..persistence.db import json_dumps, now_iso
from ..persistence.repositories.model_registry_repository import (
    ModelRegistryConflictError,
)
from ..persistence.service import get_persistence_service
from ..preprocessing.execution_contract import (
    PreprocessingContractError,
    extract_final_preprocessing_artifact,
    validate_final_preprocessing_artifact,
)
from . import model_artifacts

TERMINAL_APPROVAL_STATUSES = {"approved", "rejected"}
FINALIZED_PUBLICATION_STATUS = "finalized"
VERIFIED_LINEAGE_STATUS = "verified"


def new_model_id() -> str:
    return f"model-{uuid.uuid4().hex[:16]}"


def new_model_version_id() -> str:
    return f"mv-{uuid.uuid4().hex[:16]}"


def _camel(key: str) -> str:
    import re

    return re.sub(r"_([a-z0-9])", lambda match: match.group(1).upper(), key)


def _to_api(record: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in record.items():
        output_key = key[:-5] if key.endswith("_json") else key
        result[_camel(output_key)] = value
    return result


def _required_text(value: Any, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail=f"Exact {label} is required for durable model publication.",
        )
    return normalized


def _governance_http_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=(
            "Final-model promotion is blocked because the durable selection/"
            f"holdout governance contract is not verified: {detail}"
        ),
    )


def _governance_metric(record: Dict[str, Any]) -> Dict[str, Any]:
    """Translate durable snake-case columns into the selection contract."""
    return {
        "name": record.get("selection_metric_name"),
        "value": record.get("selection_metric_value"),
        "source": record.get("selection_metric_source"),
        "partition_id": record.get("selection_partition_id"),
        "fold_definition_id": record.get("fold_definition_id"),
        "fold_count": record.get("fold_count"),
        "fold_values": record.get("fold_values_json"),
        "mean": record.get("selection_metric_mean"),
        "standard_deviation": record.get("selection_metric_std"),
        "out_of_fold_prediction_artifact_id": record.get(
            "out_of_fold_prediction_artifact_id"
        ),
        "threshold_source": record.get("threshold_source"),
        "calibration_source": record.get("calibration_source"),
        "created_at": record.get("selection_metric_created_at"),
    }


def _integrity_view(record: Dict[str, Any]) -> Dict[str, Any]:
    metric = _governance_metric(record)
    evidence = record.get("selection_evidence_json")
    if isinstance(evidence, dict):
        nested = evidence.get("selection_metric")
        evidence_metric = nested if isinstance(nested, dict) else evidence
        aliases = {
            "name": ("name", "selection_metric_name"),
            "value": ("value", "selection_metric_value", "mean"),
            "source": ("source", "selection_metric_source"),
            "partition_id": ("partition_id", "selection_partition_id"),
            "fold_definition_id": ("fold_definition_id",),
            "fold_count": ("fold_count",),
            "fold_values": ("fold_values",),
            "out_of_fold_prediction_artifact_id": (
                "out_of_fold_prediction_artifact_id",
            ),
            "threshold_source": ("threshold_source",),
            "calibration_source": ("calibration_source",),
            "created_at": ("created_at",),
        }
        for destination, keys in aliases.items():
            if metric.get(destination) not in (None, "", []):
                continue
            for key in keys:
                if evidence_metric.get(key) not in (None, "", []):
                    metric[destination] = evidence_metric[key]
                    break
    return {
        "training_job_id": record.get("training_job_id"),
        "training_run_id": record.get("training_run_id"),
        "candidate_id": record.get("candidate_id"),
        "candidate_decision_id": record.get("candidate_decision_id"),
        "evaluation_package_id": record.get("evaluation_package_id"),
        "selection_integrity_status": record.get(
            "selection_integrity_status"
        ),
        "holdout_isolation_status": record.get("holdout_isolation_status"),
        "selection_metric": metric,
    }


def _normalized_selection_metric(metric: Any) -> Dict[str, Any]:
    """Normalize candidate and durable metric aliases before exact comparison."""
    source = metric if isinstance(metric, dict) else {}

    def first(*keys: str) -> Any:
        for key in keys:
            if source.get(key) is not None:
                return source.get(key)
        return None

    return {
        "name": first("name", "selection_metric_name"),
        "value": first("value", "selection_metric_value", "mean"),
        "source": first("source", "selection_metric_source"),
        "partition_id": first("partition_id", "selection_partition_id"),
        "fold_definition_id": first("fold_definition_id"),
        "fold_count": first("fold_count"),
        "fold_values": first("fold_values"),
        "out_of_fold_prediction_artifact_id": first(
            "out_of_fold_prediction_artifact_id"
        ),
        "threshold_source": first("threshold_source"),
        "calibration_source": first("calibration_source"),
        "created_at": first("created_at"),
    }


def _canonical_governance_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _candidate_threshold_policy(candidate: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
    configuration = candidate.get("threshold_configuration")
    if not isinstance(configuration, dict):
        raise _governance_http_error(
            "the selected candidate has no immutable threshold configuration."
        )
    policy = {
        "locked_threshold": configuration.get("locked_threshold"),
        "threshold_source": configuration.get("threshold_source"),
        "threshold_locked_at": configuration.get("threshold_locked_at"),
        "selection_threshold_tuned": configuration.get(
            "selection_threshold_tuned"
        ),
    }
    problem_type = str(
        (candidate.get("target_definition") or {}).get("problem_type")
        or candidate.get("problem_type")
        or ""
    ).strip().casefold()
    locked_threshold = policy["locked_threshold"]
    invalid_classification_threshold = (
        problem_type == "classification"
        and (
            isinstance(locked_threshold, bool)
            or not isinstance(locked_threshold, (int, float))
            or not math.isfinite(float(locked_threshold))
            or not 0.0 <= float(locked_threshold) <= 1.0
        )
    )
    invalid_regression_threshold = (
        problem_type == "regression"
        and (
            locked_threshold is not None
            or policy["threshold_source"] != "not_applicable"
        )
    )
    if (
        problem_type not in {"classification", "regression"}
        or invalid_classification_threshold
        or invalid_regression_threshold
        or not str(policy["threshold_source"] or "").strip()
        or not str(policy["threshold_locked_at"] or "").strip()
        or policy["selection_threshold_tuned"] is not False
    ):
        raise _governance_http_error(
            "the selected candidate threshold policy is incomplete or mutable."
        )
    policy_hash = _canonical_governance_hash(policy)
    if str(configuration.get("threshold_policy_hash") or "") != policy_hash:
        raise _governance_http_error(
            "the selected candidate threshold-policy hash does not verify."
        )
    return policy, policy_hash


def _verify_evaluation_package_hashes(package: Dict[str, Any]) -> None:
    payload = package.get("package_payload_json")
    if not isinstance(payload, dict) or not payload:
        raise _governance_http_error(
            "the Evaluation package has no immutable payload."
        )
    content_hash = _canonical_governance_hash(payload)
    if content_hash != str(package.get("content_hash") or ""):
        raise _governance_http_error(
            "the Evaluation package payload/content hash does not verify."
        )
    contract_payload = {
        "evaluation_package_id": package.get("evaluation_package_id"),
        "completion_content_hash": payload.get("completion_content_hash"),
        "holdout_prediction_digest": payload.get(
            "holdout_prediction_digest"
        ),
        "candidate_decision_id": package.get("candidate_decision_id"),
        "holdout_exposure_id": package.get("holdout_exposure_id"),
        "content_hash": content_hash,
    }
    if _canonical_governance_hash(contract_payload) != str(
        package.get("evaluation_package_contract_hash") or ""
    ):
        raise _governance_http_error(
            "the Evaluation package contract hash does not verify."
        )
    exact_payload_bindings = {
        "evaluation_package_id": package.get("evaluation_package_id"),
        "candidate_decision_id": package.get("candidate_decision_id"),
        "holdout_exposure_id": package.get("holdout_exposure_id"),
        "final_holdout_partition_id": package.get(
            "final_holdout_partition_id"
        ),
        "project_id": package.get("project_id"),
        "dataset_id": package.get("dataset_id"),
        "dataset_version_id": package.get("dataset_version_id"),
        "training_run_id": package.get("training_run_id"),
        "candidate_id": package.get("candidate_id"),
    }
    for key, expected in exact_payload_bindings.items():
        if str(payload.get(key) or "") != str(expected or ""):
            raise _governance_http_error(
                f"the Evaluation package payload conflicts with exact {key}."
            )


def _parse_governance_time(value: Any, label: str) -> datetime:
    raw = _required_text(value, label)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _governance_http_error(f"{label} is not a valid timestamp.") from exc
    if parsed.utcoffset() is None:
        raise _governance_http_error(
            f"{label} must include an explicit timezone."
        )
    return parsed


def _canonical_package_summary(
    package: Dict[str, Any],
    exposure: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist only the exact durable Evaluation package, never browser data."""
    return {
        "evaluationPackageId": package["evaluation_package_id"],
        "status": package["package_status"],
        "candidateId": package["candidate_id"],
        "candidateDecisionId": package["candidate_decision_id"],
        "holdoutExposureId": package["holdout_exposure_id"],
        "finalHoldoutPartitionId": package["final_holdout_partition_id"],
        "selectionIntegrityStatus": package["selection_integrity_status"],
        "selectedCandidateContractHash": package[
            "selected_candidate_contract_hash"
        ],
        "selectionMetricCreatedAt": package[
            "selection_metric_created_at"
        ],
        "outOfFoldPredictionArtifactId": package[
            "out_of_fold_prediction_artifact_id"
        ],
        "holdoutIsolationStatus": package["holdout_isolation_status"],
        "finalHoldoutStatus": exposure["final_holdout_status"],
        "packageIntegrityStatus": package["package_integrity_status"],
        "selectionEvidence": package.get("selection_evidence_json") or {},
        "finalHoldoutEvidence": package.get("final_holdout_evidence_json")
        or {},
        "metricDefinitions": package.get("metric_definitions_json") or {},
        "thresholdPolicy": package.get("threshold_policy_json") or {},
        "isolationEvidence": package.get("isolation_evidence_json") or {},
        "canonicalLineage": package.get("canonical_lineage_json") or {},
        "thresholdLockedAt": package["threshold_locked_at"],
        "lockedThreshold": package["locked_threshold"],
        "thresholdSource": package["threshold_source"],
        "thresholdPolicyHash": package["threshold_policy_hash"],
        "holdoutExposedAt": package["holdout_exposed_at"],
        "recommendationsDerivedFromFinalHoldout": bool(
            package.get("recommendations_derived_from_final_holdout")
        ),
        "evaluationPackageContractHash": package[
            "evaluation_package_contract_hash"
        ],
        "contentHash": package["content_hash"],
    }


def _canonical_lineage(
    *,
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    training_run_id: str,
    feature_manifest_version: str,
    problem_type: str,
    algorithm: str,
    lineage: Optional[Dict[str, Any]],
    candidate_contract: Optional[Dict[str, Any]],
    evaluation_package_id: Optional[str],
) -> Dict[str, Any]:
    supplied = dict(lineage or {})
    embedded_contract = supplied.pop(
        "candidateContract",
        supplied.pop("candidate_contract", None),
    )
    contract = candidate_contract or embedded_contract
    if not isinstance(contract, dict):
        raise HTTPException(
            status_code=422,
            detail="The exact frozen model-candidate contract is required for promotion.",
        )
    contract = dict(contract)
    expected_contract_hash = str(contract.get("contract_hash") or "").strip()
    contract_payload = dict(contract)
    contract_payload.pop("contract_hash", None)
    actual_contract_hash = hashlib.sha256(
        json.dumps(
            contract_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    if not expected_contract_hash or expected_contract_hash != actual_contract_hash:
        raise HTTPException(
            status_code=409,
            detail="The frozen model-candidate contract is missing or has changed.",
        )
    required_contract_fields = (
        "project_id",
        "dataset_id",
        "dataset_version_id",
        "target_name",
        "target_contract_id",
        "predictor_manifest_id",
        "predictor_manifest_hash",
        "treatment_manifest_id",
        "treatment_manifest_hash",
        "feature_manifest_id",
        "feature_manifest_hash",
        "materialization_id",
        "validation_design_id",
        "validation_design_version",
        "split_id",
        "training_job_id",
        "training_run_id",
        "candidate_id",
        "algorithm_id",
        "hyperparameter_manifest",
        "calibration_configuration",
        "ranking_metric",
        "selection_metric",
        "threshold_configuration",
        "class_encoding",
        "selection_integrity_status",
        "holdout_isolation_status",
        "final_holdout_status",
        "selection_resampling_status",
        "training_population_id",
        "final_holdout_partition_id",
        "fold_definition_id",
        "created_by",
        "created_at",
        "runtime_environment",
        "random_seed",
    )
    missing_contract_fields = [
        key
        for key in required_contract_fields
        if key not in contract
        or contract.get(key) is None
        or (isinstance(contract.get(key), str) and not contract[key].strip())
    ]
    if missing_contract_fields:
        raise HTTPException(
            status_code=422,
            detail=(
                "The frozen model-candidate contract is incomplete: "
                + ", ".join(missing_contract_fields)
            ),
        )
    if contract.get("candidate_state") != "complete" or not bool(
        contract.get("champion_eligible")
    ):
        raise HTTPException(
            status_code=409,
            detail="Only a complete, champion-eligible supervised candidate may be promoted.",
        )
    try:
        assert_selection_integrity(contract)
    except SelectionIntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    target_definition = contract.get("target_definition")
    if not isinstance(target_definition, dict):
        raise HTTPException(
            status_code=422,
            detail="The candidate target definition is required for promotion.",
        )
    contract_problem_type = str(
        target_definition.get("problem_type") or ""
    ).strip()
    exact_bindings = {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "training_run_id": training_run_id,
        "feature_manifest_hash": feature_manifest_version,
        "algorithm_id": algorithm,
    }
    for key, expected in exact_bindings.items():
        if str(contract.get(key) or "").strip() != expected:
            raise HTTPException(
                status_code=409,
                detail=f"The candidate contract conflicts with the exact {key}.",
            )
    if contract_problem_type != problem_type:
        raise HTTPException(
            status_code=409,
            detail="The candidate target contract conflicts with the model problem type.",
        )
    exact_evaluation_package_id = _required_text(
        evaluation_package_id
        or supplied.get("evaluationPackageId")
        or supplied.get("evaluation_package_id"),
        "evaluation_package_id",
    )
    exact_candidate_decision_id = _required_text(
        supplied.get("candidateDecisionId")
        or supplied.get("candidate_decision_id"),
        "candidate_decision_id",
    )
    supplied_validation_design_version = _required_text(
        supplied.get("validationDesignVersion")
        or supplied.get("validation_design_version"),
        "validation_design_version",
    )
    validation_design_version = _required_text(
        contract.get("validation_design_version"),
        "candidate_contract.validation_design_version",
    )
    if supplied_validation_design_version != validation_design_version:
        raise HTTPException(
            status_code=409,
            detail=(
                "The evaluation lineage validation-design version conflicts "
                "with the frozen candidate contract."
            ),
        )
    canonical = {
        "projectId": project_id,
        "datasetId": dataset_id,
        "datasetVersionId": dataset_version_id,
        "trainingDatasetId": dataset_id,
        "trainingDatasetVersionId": dataset_version_id,
        "candidateId": str(contract["candidate_id"]),
        "trainingJobId": str(contract["training_job_id"]),
        "trainingRunId": training_run_id,
        "target": str(contract["target_name"]),
        "targetName": str(contract["target_name"]),
        "targetContractId": str(contract["target_contract_id"]),
        "targetDefinition": target_definition,
        "positiveClass": contract.get("positive_class"),
        "predictorManifestId": str(contract["predictor_manifest_id"]),
        "predictorManifestHash": str(contract["predictor_manifest_hash"]),
        "treatmentManifestId": str(contract["treatment_manifest_id"]),
        "treatmentManifestHash": str(contract["treatment_manifest_hash"]),
        "featureManifestId": str(contract["feature_manifest_id"]),
        "featureManifestHash": feature_manifest_version,
        "featureManifestVersion": feature_manifest_version,
        "validationDesignId": str(contract["validation_design_id"]),
        "validationDesignVersion": validation_design_version,
        "splitId": str(contract["split_id"]),
        "evaluationPackageId": exact_evaluation_package_id,
        "candidateDecisionId": exact_candidate_decision_id,
        "algorithmId": algorithm,
        "problemType": problem_type,
        "candidateContractHash": expected_contract_hash,
        "candidateContract": contract,
    }
    aliases = {
        "projectId": ("projectId", "project_id"),
        "datasetId": ("datasetId", "dataset_id"),
        "datasetVersionId": (
            "datasetVersionId",
            "dataset_version_id",
            "datasetVersion",
            "dataset_version",
        ),
        "trainingRunId": ("trainingRunId", "training_run_id"),
        "trainingJobId": ("trainingJobId", "training_job_id"),
        "candidateId": ("candidateId", "candidate_id"),
        "featureManifestVersion": (
            "featureManifestVersion",
            "feature_manifest_version",
        ),
        "validationDesignId": (
            "validationDesignId",
            "validation_design_id",
        ),
        "validationDesignVersion": (
            "validationDesignVersion",
            "validation_design_version",
        ),
        "splitId": ("splitId", "split_id"),
        "target": ("target", "target_name"),
        "problemType": ("problemType", "problem_type"),
        "evaluationPackageId": (
            "evaluationPackageId",
            "evaluation_package_id",
        ),
        "candidateDecisionId": (
            "candidateDecisionId",
            "candidate_decision_id",
        ),
    }
    for canonical_key, keys in aliases.items():
        expected = canonical[canonical_key]
        for key in keys:
            actual = supplied.get(key)
            if actual not in (None, "") and str(actual) != expected:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Model publication lineage conflicts with the exact "
                        f"{canonical_key} supplied by the governed workflow."
                    ),
                )
    # Remove aliases so downstream consumers see one unambiguous contract.
    for keys in aliases.values():
        for key in keys:
            supplied.pop(key, None)
    supplied_contract = supplied.pop("lineageContract", None)
    if supplied_contract not in (None, "", "exact_model_publication_v1"):
        raise HTTPException(
            status_code=409,
            detail="Model publication lineage uses an unsupported lineage contract.",
        )
    return {
        **supplied,
        **canonical,
        "lineageContract": "exact_model_publication_v1",
    }


def _durable_promotion_governance(
    service: Any,
    canonical_lineage: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Resolve and verify exact durable decision, exposure, and package rows.

    The caller-supplied Evaluation JSON is deliberately not an authority.  It
    supplies only the content-addressed package ID already bound into lineage.
    Every promotability decision below is made from SQLite governance rows.
    """
    repository = getattr(service, "holdout_governance", None)
    if repository is None:
        raise _governance_http_error("the governance repository is unavailable.")

    package_id = canonical_lineage["evaluationPackageId"]
    package_hint = repository.get_evaluation_package(package_id)
    if not package_hint:
        raise _governance_http_error(
            "the exact durable Evaluation package does not exist."
        )
    exposure_id = _required_text(
        package_hint.get("holdout_exposure_id"),
        "evaluation_package.holdout_exposure_id",
    )
    package = repository.get_evaluation_package_exact(
        evaluation_package_id=package_id,
        project_id=canonical_lineage["projectId"],
        dataset_id=canonical_lineage["datasetId"],
        dataset_version_id=canonical_lineage["datasetVersionId"],
        training_run_id=canonical_lineage["trainingRunId"],
        candidate_id=canonical_lineage["candidateId"],
        candidate_decision_id=canonical_lineage["candidateDecisionId"],
        holdout_exposure_id=exposure_id,
    )
    if not package:
        raise _governance_http_error(
            "the Evaluation package does not match the exact promotion lineage."
        )
    _verify_evaluation_package_hashes(package)

    decision = repository.get_selection_decision_exact(
        candidate_decision_id=canonical_lineage["candidateDecisionId"],
        project_id=canonical_lineage["projectId"],
        dataset_id=canonical_lineage["datasetId"],
        dataset_version_id=canonical_lineage["datasetVersionId"],
        validation_design_id=canonical_lineage["validationDesignId"],
        validation_design_version_id=canonical_lineage[
            "validationDesignVersion"
        ],
        split_id=canonical_lineage["splitId"],
        training_run_id=canonical_lineage["trainingRunId"],
        candidate_id=canonical_lineage["candidateId"],
    )
    if not decision:
        raise _governance_http_error(
            "the exact immutable candidate decision does not exist."
        )

    final_partition_id = _required_text(
        package.get("final_holdout_partition_id"),
        "evaluation_package.final_holdout_partition_id",
    )
    exposure = repository.get_holdout_exposure_exact(
        holdout_exposure_id=exposure_id,
        project_id=canonical_lineage["projectId"],
        dataset_version_id=canonical_lineage["datasetVersionId"],
        split_id=canonical_lineage["splitId"],
        final_holdout_partition_id=final_partition_id,
        candidate_decision_id=canonical_lineage["candidateDecisionId"],
        candidate_id=canonical_lineage["candidateId"],
    )
    if not exposure:
        raise _governance_http_error(
            "the exact final-holdout exposure does not exist."
        )

    candidate = canonical_lineage["candidateContract"]
    candidate_contract_hash = canonical_lineage["candidateContractHash"]
    threshold_policy, threshold_policy_hash = _candidate_threshold_policy(
        candidate
    )
    expected_pairs = (
        ("project_id", canonical_lineage["projectId"]),
        ("dataset_id", canonical_lineage["datasetId"]),
        ("dataset_version_id", canonical_lineage["datasetVersionId"]),
        ("feature_manifest_id", canonical_lineage["featureManifestId"]),
        ("feature_manifest_hash", canonical_lineage["featureManifestHash"]),
        ("treatment_manifest_id", canonical_lineage["treatmentManifestId"]),
        ("treatment_manifest_hash", canonical_lineage["treatmentManifestHash"]),
        ("validation_design_id", canonical_lineage["validationDesignId"]),
        (
            "validation_design_version_id",
            canonical_lineage["validationDesignVersion"],
        ),
        ("split_id", canonical_lineage["splitId"]),
        ("training_job_id", canonical_lineage["trainingJobId"]),
        ("training_run_id", canonical_lineage["trainingRunId"]),
        ("candidate_id", canonical_lineage["candidateId"]),
    )
    for record_name, record in (
        ("candidate decision", decision),
        ("Evaluation package", package),
    ):
        for key, expected in expected_pairs:
            if str(record.get(key) or "") != str(expected or ""):
                raise _governance_http_error(
                    f"the {record_name} conflicts with exact {key}."
                )
    materialization_id = _required_text(
        decision.get("materialization_id"),
        "candidate_decision.materialization_id",
    )
    if str(candidate.get("materialization_id") or "") != materialization_id:
        raise _governance_http_error(
            "the candidate contract conflicts with the locked materialization."
        )
    if package.get("materialization_id") != materialization_id:
        raise _governance_http_error(
            "the Evaluation package conflicts with the locked materialization."
        )
    for record_name, record in (
        ("candidate decision", decision),
        ("Evaluation package", package),
    ):
        if (
            str(record.get("selected_candidate_contract_hash") or "")
            != candidate_contract_hash
        ):
            raise _governance_http_error(
                f"the {record_name} is not bound to the selected candidate contract hash."
            )
        if str(record.get("threshold_policy_hash") or "") != threshold_policy_hash:
            raise _governance_http_error(
                f"the {record_name} threshold-policy hash does not match the candidate."
            )
    for key, expected in (
        ("project_id", canonical_lineage["projectId"]),
        ("dataset_id", canonical_lineage["datasetId"]),
        ("dataset_version_id", canonical_lineage["datasetVersionId"]),
        ("validation_design_id", canonical_lineage["validationDesignId"]),
        (
            "validation_design_version_id",
            canonical_lineage["validationDesignVersion"],
        ),
        ("split_id", canonical_lineage["splitId"]),
        ("candidate_decision_id", canonical_lineage["candidateDecisionId"]),
        ("candidate_id", canonical_lineage["candidateId"]),
    ):
        if str(exposure.get(key) or "") != str(expected or ""):
            raise _governance_http_error(
                f"the final-holdout exposure conflicts with exact {key}."
            )

    if str(decision.get("decision_status") or "").casefold() != "locked":
        raise _governance_http_error("the candidate decision is not locked.")
    if not decision.get("decision_contract_hash"):
        raise _governance_http_error(
            "the candidate decision has no immutable contract hash."
        )
    if not decision.get("ranking_snapshot_hash"):
        raise _governance_http_error(
            "the candidate decision has no immutable ranking snapshot."
        )
    if bool(exposure.get("invalidated_at")) or bool(
        exposure.get("invalidated_by")
    ) or bool(exposure.get("invalidation_reason")):
        raise _governance_http_error(
            "the final-holdout exposure was invalidated."
        )
    try:
        decision_metric = _normalized_selection_metric(
            assert_selection_integrity(_integrity_view(decision))
        )
        candidate_metric = _normalized_selection_metric(
            assert_selection_integrity(candidate)
        )
        package_metric = _normalized_selection_metric(
            assert_selection_integrity(_integrity_view(package))
        )
    except SelectionIntegrityError as exc:
        raise _governance_http_error(str(exc)) from exc
    for label, candidate_value, decision_value, package_value in (
        ("name", candidate_metric.get("name"), decision_metric.get("name"), package_metric.get("name")),
        ("value", candidate_metric.get("value"), decision_metric.get("value"), package_metric.get("value")),
        ("source", candidate_metric.get("source"), decision_metric.get("source"), package_metric.get("source")),
        ("partition", candidate_metric.get("partition_id"), decision_metric.get("partition_id"), package_metric.get("partition_id")),
        ("fold definition", candidate_metric.get("fold_definition_id"), decision_metric.get("fold_definition_id"), package_metric.get("fold_definition_id")),
        ("fold count", candidate_metric.get("fold_count"), decision_metric.get("fold_count"), package_metric.get("fold_count")),
        ("fold values", candidate_metric.get("fold_values"), decision_metric.get("fold_values"), package_metric.get("fold_values")),
        ("created at", candidate_metric.get("created_at"), decision_metric.get("created_at"), package_metric.get("created_at")),
        ("OOF artifact", candidate_metric.get("out_of_fold_prediction_artifact_id"), decision_metric.get("out_of_fold_prediction_artifact_id"), package_metric.get("out_of_fold_prediction_artifact_id")),
        ("threshold source", candidate_metric.get("threshold_source"), decision_metric.get("threshold_source"), package_metric.get("threshold_source")),
        ("calibration source", candidate_metric.get("calibration_source"), decision_metric.get("calibration_source"), package_metric.get("calibration_source")),
    ):
        if candidate_value != decision_value or candidate_value != package_value:
            raise _governance_http_error(
                f"selection metric {label} differs across candidate, decision, and package."
            )
    if not str(candidate_metric.get("created_at") or "").strip():
        raise _governance_http_error(
            "the selection metric has no immutable creation timestamp."
        )
    if not str(
        candidate_metric.get("out_of_fold_prediction_artifact_id") or ""
    ).strip():
        raise _governance_http_error(
            "the selection metric has no exact out-of-fold prediction artifact."
        )
    if str(decision.get("selection_partition_id") or "") == final_partition_id:
        raise _governance_http_error(
            "the selection partition is the final-holdout partition."
        )
    if str(candidate.get("final_holdout_partition_id") or "") != final_partition_id:
        raise _governance_http_error(
            "the final-holdout partition conflicts with the candidate contract."
        )

    if str(package.get("package_status") or "").casefold() != "complete":
        raise _governance_http_error("the Evaluation package is incomplete.")
    if str(package.get("package_integrity_status") or "").casefold() != "verified":
        raise _governance_http_error(
            "the Evaluation package integrity is not verified."
        )
    if str(package.get("holdout_isolation_status") or "").casefold() != "verified":
        raise _governance_http_error("holdout isolation is not verified.")
    if str(exposure.get("final_holdout_status") or "").casefold() != "evaluated":
        raise _governance_http_error("the final holdout has not been evaluated.")
    if exposure.get("evaluation_package_id") != package_id:
        raise _governance_http_error(
            "the evaluated holdout is not bound to this exact package."
        )
    if bool(package.get("recommendations_derived_from_final_holdout")):
        raise _governance_http_error(
            "the Evaluation package derived recommendations from the final holdout."
        )
    if package.get("threshold_policy_json") != {
        **threshold_policy,
        "threshold_policy_hash": threshold_policy_hash,
    }:
        raise _governance_http_error(
            "the Evaluation package threshold policy differs from the locked candidate policy."
        )
    for record_name, record in (
        ("candidate decision", decision),
        ("Evaluation package", package),
    ):
        if record.get("locked_threshold") != threshold_policy["locked_threshold"]:
            raise _governance_http_error(
                f"the {record_name} locked threshold differs from the candidate."
            )
        if str(record.get("threshold_source") or "") != str(
            threshold_policy["threshold_source"]
        ):
            raise _governance_http_error(
                f"the {record_name} threshold source differs from the candidate."
            )
        if str(record.get("threshold_locked_at") or "") != str(
            threshold_policy["threshold_locked_at"]
        ):
            raise _governance_http_error(
                f"the {record_name} threshold lock time differs from the candidate."
            )
    if not package.get("evaluation_package_contract_hash") or not package.get(
        "content_hash"
    ):
        raise _governance_http_error(
            "the Evaluation package has no immutable contract/content hash."
        )
    for evidence_field in (
        "selection_evidence_json",
        "final_holdout_evidence_json",
        "metric_definitions_json",
        "threshold_policy_json",
        "isolation_evidence_json",
    ):
        evidence = package.get(evidence_field)
        if not isinstance(evidence, dict) or not evidence:
            raise _governance_http_error(
                f"the Evaluation package has no {evidence_field}."
            )
    selection_locked_at = _parse_governance_time(
        decision.get("selection_locked_at"), "selection_locked_at"
    )
    threshold_locked_at = _parse_governance_time(
        package.get("threshold_locked_at"), "threshold_locked_at"
    )
    holdout_opened_at = _parse_governance_time(
        exposure.get("first_opened_at"), "holdout_exposed_at"
    )
    selection_metric_created_at = _parse_governance_time(
        decision.get("selection_metric_created_at"),
        "selection_metric_created_at",
    )
    if selection_metric_created_at > selection_locked_at:
        raise _governance_http_error(
            "the selection metric was created after the candidate decision lock."
        )
    if selection_locked_at >= holdout_opened_at:
        raise _governance_http_error(
            "the candidate decision was locked after holdout exposure."
        )
    if threshold_locked_at >= holdout_opened_at:
        raise _governance_http_error(
            "the evaluation threshold was locked after holdout exposure."
        )
    if str(package.get("holdout_exposed_at") or "") != str(
        exposure.get("first_opened_at") or ""
    ):
        raise _governance_http_error(
            "the package exposure time conflicts with the durable exposure ledger."
        )

    durable_lineage = package.get("canonical_lineage_json")
    if not isinstance(durable_lineage, dict):
        raise _governance_http_error(
            "the Evaluation package has no canonical lineage contract."
        )
    lineage_bindings = {
        "project_id": canonical_lineage["projectId"],
        "dataset_id": canonical_lineage["datasetId"],
        "dataset_version_id": canonical_lineage["datasetVersionId"],
        "training_job_id": canonical_lineage["trainingJobId"],
        "training_run_id": canonical_lineage["trainingRunId"],
        "candidate_id": canonical_lineage["candidateId"],
        "candidate_decision_id": canonical_lineage["candidateDecisionId"],
        "validation_design_id": canonical_lineage["validationDesignId"],
        "validation_design_version_id": canonical_lineage[
            "validationDesignVersion"
        ],
        "split_id": canonical_lineage["splitId"],
        "feature_manifest_id": canonical_lineage["featureManifestId"],
        "feature_manifest_hash": canonical_lineage["featureManifestHash"],
        "treatment_manifest_id": canonical_lineage["treatmentManifestId"],
        "treatment_manifest_hash": canonical_lineage[
            "treatmentManifestHash"
        ],
        "materialization_id": materialization_id,
        "evaluation_package_id": package_id,
        "holdout_exposure_id": exposure_id,
        "final_holdout_partition_id": final_partition_id,
    }
    for key, expected in lineage_bindings.items():
        camel_key = _camel(key)
        actual = durable_lineage.get(key, durable_lineage.get(camel_key))
        if str(actual or "") != str(expected or ""):
            raise _governance_http_error(
                f"the Evaluation package canonical lineage conflicts with {key}."
            )

    return decision, exposure, package


def _publication_fingerprint(payload: Dict[str, Any]) -> str:
    encoded = json_dumps(payload, {})
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _idempotency_storage_key(
    project_id: str,
    supplied_key: Optional[str],
    fingerprint: str,
) -> str:
    source = str(supplied_key or "").strip() or fingerprint
    return "idem-" + hashlib.sha256(
        f"{project_id}\0{source}".encode("utf-8")
    ).hexdigest()


def _record_lineage_error(record: Dict[str, Any]) -> str:
    governed_fields = {
        "candidate_decision_id": record.get("candidate_decision_id"),
        "candidate_decision_status": record.get("candidate_decision_status"),
        "candidate_decision_contract_hash": record.get(
            "candidate_decision_contract_hash"
        ),
        "selection_metric_name": record.get("selection_metric_name"),
        "selection_metric_value": record.get("selection_metric_value"),
        "selection_metric_source": record.get("selection_metric_source"),
        "selection_metric_created_at": record.get(
            "selection_metric_created_at"
        ),
        "out_of_fold_prediction_artifact_id": record.get(
            "out_of_fold_prediction_artifact_id"
        ),
        "selected_candidate_contract_hash": record.get(
            "selected_candidate_contract_hash"
        ),
        "selection_locked_at": record.get("selection_locked_at"),
        "holdout_exposure_id": record.get("holdout_exposure_id"),
        "final_holdout_partition_id": record.get(
            "final_holdout_partition_id"
        ),
        "threshold_locked_at": record.get("threshold_locked_at"),
        "threshold_source": record.get("threshold_source"),
        "threshold_policy_hash": record.get("threshold_policy_hash"),
        "evaluation_package_contract_hash": record.get(
            "evaluation_package_contract_hash"
        ),
        "evaluation_package_content_hash": record.get(
            "evaluation_package_content_hash"
        ),
    }
    if any(value in (None, "") for value in governed_fields.values()):
        return "The model version is missing durable selection/holdout provenance."
    if (
        record.get("threshold_source") != "not_applicable"
        and record.get("locked_threshold") is None
    ):
        return "The model version is missing its locked classification threshold."
    if (
        record.get("candidate_decision_status") != "locked"
        or record.get("selection_integrity_status") != "verified"
        or record.get("holdout_isolation_status") != "verified"
        or record.get("final_holdout_status") != "evaluated"
        or record.get("evaluation_package_integrity_status") != "verified"
        or record.get("promotion_readiness_status") != "verified"
        or record.get("selection_metric_source") == "final_holdout"
    ):
        return "The model version does not have verified promotion governance status."
    required = {
        "projectId": str(record.get("project_id") or ""),
        "datasetId": str(record.get("dataset_id") or ""),
        "datasetVersionId": str(record.get("dataset_version_id") or ""),
        "trainingRunId": str(record.get("training_run_id") or ""),
        "featureManifestVersion": str(
            record.get("feature_manifest_version") or ""
        ),
        "candidateId": str(record.get("candidate_id") or ""),
        "evaluationPackageId": str(record.get("evaluation_package_id") or ""),
        "candidateDecisionId": str(record.get("candidate_decision_id") or ""),
        "target": str(record.get("target_name") or ""),
        "validationDesignId": str(record.get("validation_design_id") or ""),
        "splitId": str(record.get("split_id") or ""),
    }
    if any(not value for value in required.values()):
        return "The model version is missing exact canonical lineage fields."
    lineage = record.get("lineage_json")
    if not isinstance(lineage, dict):
        return "The model version lineage payload is unavailable."
    if lineage.get("lineageContract") != "exact_model_publication_v1":
        return "The model version predates the exact publication lineage contract."
    for key, expected in required.items():
        if str(lineage.get(key) or "") != expected:
            return f"The model version lineage conflicts with {key}."
    candidate_contract = lineage.get("candidateContract")
    if not isinstance(candidate_contract, dict):
        return "The frozen candidate contract is unavailable."
    expected_hash = str(record.get("candidate_contract_hash") or "")
    candidate_payload = dict(candidate_contract)
    candidate_payload.pop("contract_hash", None)
    actual_hash = hashlib.sha256(
        json.dumps(
            candidate_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    if (
        not expected_hash
        or str(candidate_contract.get("contract_hash") or "") != expected_hash
        or actual_hash != expected_hash
    ):
        return "The frozen candidate contract hash does not verify."
    try:
        assert_selection_integrity(candidate_contract)
    except SelectionIntegrityError as exc:
        return str(exc)
    try:
        threshold_policy, threshold_policy_hash = _candidate_threshold_policy(
            candidate_contract
        )
    except HTTPException as exc:
        return str(exc.detail)
    if (
        record.get("locked_threshold") != threshold_policy["locked_threshold"]
        or str(record.get("threshold_source") or "")
        != str(threshold_policy["threshold_source"])
        or str(record.get("threshold_locked_at") or "")
        != str(threshold_policy["threshold_locked_at"])
        or str(record.get("threshold_policy_hash") or "")
        != threshold_policy_hash
        or str(record.get("selected_candidate_contract_hash") or "")
        != expected_hash
    ):
        return "The persisted candidate threshold/contract lock does not verify."
    if (
        str(record.get("selection_integrity_status") or "").strip().casefold()
        != "verified"
        or str(record.get("holdout_isolation_status") or "").strip().casefold()
        != "verified"
    ):
        return "The model version does not prove verified selection and final-holdout isolation."
    model_contract = record.get("model_contract_json")
    if not isinstance(model_contract, dict):
        return "The immutable model-version contract is unavailable."
    if model_contract.get("lockedThreshold") != record.get(
        "locked_threshold"
    ):
        return (
            "The immutable model-version contract conflicts with "
            "lockedThreshold."
        )
    for key, expected in (
        ("modelVersionId", str(record.get("model_version_id") or "")),
        ("projectId", required["projectId"]),
        ("candidateId", required["candidateId"]),
        ("evaluationPackageId", required["evaluationPackageId"]),
        ("candidateDecisionId", required["candidateDecisionId"]),
        ("candidateDecisionStatus", "locked"),
        (
            "candidateDecisionContractHash",
            str(record.get("candidate_decision_contract_hash") or ""),
        ),
        (
            "selectionLockedAt",
            str(record.get("selection_locked_at") or ""),
        ),
        (
            "selectionMetricCreatedAt",
            str(record.get("selection_metric_created_at") or ""),
        ),
        (
            "outOfFoldPredictionArtifactId",
            str(record.get("out_of_fold_prediction_artifact_id") or ""),
        ),
        (
            "selectedCandidateContractHash",
            str(record.get("selected_candidate_contract_hash") or ""),
        ),
        (
            "holdoutExposureId",
            str(record.get("holdout_exposure_id") or ""),
        ),
        (
            "finalHoldoutPartitionId",
            str(record.get("final_holdout_partition_id") or ""),
        ),
        ("finalHoldoutStatus", "evaluated"),
        (
            "thresholdLockedAt",
            str(record.get("threshold_locked_at") or ""),
        ),
        (
            "thresholdSource",
            str(record.get("threshold_source") or ""),
        ),
        (
            "thresholdPolicyHash",
            str(record.get("threshold_policy_hash") or ""),
        ),
        (
            "evaluationPackageContractHash",
            str(record.get("evaluation_package_contract_hash") or ""),
        ),
        (
            "evaluationPackageContentHash",
            str(record.get("evaluation_package_content_hash") or ""),
        ),
        ("evaluationPackageIntegrityStatus", "verified"),
        ("promotionReadinessStatus", "verified"),
        ("artifactChecksum", str(record.get("checksum") or "")),
    ):
        if str(model_contract.get(key) or "") != expected:
            return f"The immutable model-version contract conflicts with {key}."
    return ""


def _durable_governance_recovery_error(
    service: Any,
    record: Dict[str, Any],
) -> str:
    lineage = record.get("lineage_json")
    if not isinstance(lineage, dict):
        return "The durable publication lineage is unavailable."
    try:
        decision, exposure, package = _durable_promotion_governance(
            service,
            lineage,
        )
    except HTTPException as exc:
        return str(exc.detail)
    expected = {
        "candidate_decision_id": decision.get("candidate_decision_id"),
        "candidate_decision_status": decision.get("decision_status"),
        "candidate_decision_contract_hash": decision.get(
            "decision_contract_hash"
        ),
        "selection_metric_name": decision.get("selection_metric_name"),
        "selection_metric_value": decision.get("selection_metric_value"),
        "selection_metric_source": decision.get("selection_metric_source"),
        "selection_metric_created_at": decision.get(
            "selection_metric_created_at"
        ),
        "out_of_fold_prediction_artifact_id": decision.get(
            "out_of_fold_prediction_artifact_id"
        ),
        "selected_candidate_contract_hash": decision.get(
            "selected_candidate_contract_hash"
        ),
        "selection_integrity_status": decision.get(
            "selection_integrity_status"
        ),
        "selection_locked_at": decision.get("selection_locked_at"),
        "holdout_exposure_id": exposure.get("holdout_exposure_id"),
        "final_holdout_partition_id": exposure.get(
            "final_holdout_partition_id"
        ),
        "final_holdout_status": exposure.get("final_holdout_status"),
        "holdout_isolation_status": package.get("holdout_isolation_status"),
        "threshold_locked_at": package.get("threshold_locked_at"),
        "locked_threshold": package.get("locked_threshold"),
        "threshold_source": package.get("threshold_source"),
        "threshold_policy_hash": package.get("threshold_policy_hash"),
        "evaluation_package_contract_hash": package.get(
            "evaluation_package_contract_hash"
        ),
        "evaluation_package_content_hash": package.get("content_hash"),
        "evaluation_package_integrity_status": package.get(
            "package_integrity_status"
        ),
        "promotion_readiness_status": "verified",
    }
    for field, durable_value in expected.items():
        if record.get(field) != durable_value:
            return (
                "The model version governance provenance conflicts with its "
                f"durable {field}."
            )
    return ""


def _publication_response(
    model: Dict[str, Any],
    version: Dict[str, Any],
    *,
    idempotent_replay: bool,
) -> Dict[str, Any]:
    return {
        "model": _to_api(model),
        "modelVersion": _to_api(version),
        "promotion": {
            "status": FINALIZED_PUBLICATION_STATUS,
            "idempotentReplay": bool(idempotent_replay),
            "artifactVerified": True,
            "checksum": version.get("checksum"),
            "lineageStatus": version.get("lineage_status"),
            "championGeneration": int(
                model.get("current_version_generation") or 0
            ),
            "designation": (
                "champion"
                if model.get("current_version_id")
                == version.get("model_version_id")
                else "challenger"
            ),
            "championStatus": (
                "champion"
                if model.get("current_version_id")
                == version.get("model_version_id")
                else "challenger"
            ),
            "previousChampionModelVersionId": version.get(
                "previous_champion_version_id"
            ),
        },
    }


def _quarantine_recovery_failure(
    service: Any,
    record: Dict[str, Any],
    reason: str,
) -> None:
    model_version_id = str(record.get("model_version_id") or "")
    if model_version_id:
        service.model_versions.quarantine(model_version_id, reason)


def _verify_recoverable_version(
    service: Any,
    record: Dict[str, Any],
    *,
    deserialize: bool = False,
) -> Dict[str, Any]:
    """Verify all exact recovery invariants, quarantining any failed row.

    Authorization must happen before this helper is called by a request path.
    Publication calls have already authorized the exact project before staging.
    """
    from .mlb_v18_conditional import FORMAT, verify_record
    if record.get("artifact_format") == FORMAT:
        try:
            return verify_record(service, record, deserialize=deserialize)
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    reason = ""
    if record.get("archived_at"):
        reason = "Archived model versions cannot be recovered."
    elif record.get("publication_status") != FINALIZED_PUBLICATION_STATUS:
        reason = "The model version was not finalized by the durable publication flow."
    elif record.get("lineage_status") != VERIFIED_LINEAGE_STATUS:
        reason = "The model version lineage has not been verified."
    elif record.get("quarantine_reason") or record.get("quarantined_at"):
        reason = "The model version is quarantined and cannot be recovered."
    elif str(record.get("artifact_format") or "").lower() != "joblib":
        reason = "The model version artifact format is unsupported or unresolved."
    elif not record.get("artifact_reference") or not record.get("checksum"):
        reason = "The model version has no exact artifact reference and checksum."
    else:
        reason = _record_lineage_error(record)

    if not reason:
        reason = _durable_governance_recovery_error(service, record)

    model: Dict[str, Any] | None = None
    if not reason:
        model = service.models.get(str(record.get("model_id") or ""))
        if (
            not model
            or not model.get("project_id")
            or model.get("project_id") != record.get("project_id")
        ):
            reason = "The model version has no exact project-bound parent model."
        elif model.get("archived"):
            reason = "The parent model is archived and cannot be recovered."

    verification: Dict[str, Any] | None = None
    if not reason:
        try:
            verification = model_artifacts.verify_model_artifact(
                str(record["artifact_reference"]),
                expected_checksum=str(record["checksum"]),
                expected_model_version_id=str(record["model_version_id"]),
                deserialize=deserialize,
            )
            expected_size = record.get("artifact_size_bytes")
            if (
                expected_size is None
                or int(expected_size) <= 0
                or int(expected_size) != int(verification["sizeBytes"])
            ):
                reason = "The model artifact size does not match its registry record."
        except Exception:
            reason = "The model artifact failed exact path, checksum, or deserialize verification."

    if reason:
        _quarantine_recovery_failure(service, record, reason)
        raise HTTPException(
            status_code=409,
            detail="This exact model version is not recoverable from the durable registry.",
        )
    return verification or {}


def _get_or_create_model(
    service, user: Dict[str, Any], project_id: str, name: str, problem_type: Optional[str],
) -> Dict[str, Any]:
    existing = service.models.find_by_name(project_id, name)
    if existing:
        return existing
    timestamp = now_iso()
    record = {
        "model_id": new_model_id(),
        "project_id": project_id,
        "name": name,
        "problem_type": problem_type,
        "status": "active",
        "owner_user_id": str(user.get("userId") or ""),
        "created_at": timestamp,
        "updated_at": timestamp,
        "current_version_id": None,
        "archived": False,
        "archived_at": None,
        "tags_json": [],
        "description": None,
    }
    return service.models.upsert(record)


def reconcile_orphan_artifacts(
    *,
    minimum_age_seconds: float = 300.0,
) -> Dict[str, int]:
    service = get_persistence_service()
    return model_artifacts.reconcile_artifact_storage(
        service.model_versions.artifact_version_ids(),
        minimum_age_seconds=minimum_age_seconds,
    )


def create_model_version(
    user: Dict[str, Any],
    project_id: str,
    *,
    model_name: str,
    candidate_model_name: Optional[str] = None,
    problem_type: Optional[str],
    algorithm: str,
    algorithm_version: Optional[str],
    fitted_object: Any,
    hyperparameters: Optional[Dict[str, Any]] = None,
    training_parameters: Optional[Dict[str, Any]] = None,
    metrics_summary: Optional[Dict[str, Any]] = None,
    evaluation_summary: Optional[Dict[str, Any]] = None,
    interpretation_summary: Optional[Dict[str, Any]] = None,
    training_run_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    dataset_version_id: Optional[str] = None,
    feature_manifest_version: Optional[str] = None,
    training_timestamp: Optional[str] = None,
    lineage: Optional[Dict[str, Any]] = None,
    candidate_contract: Optional[Dict[str, Any]] = None,
    evaluation_package_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish one exact, immutable model version through a compensated flow.

    Serialization is staged, deserialized for verification, checksummed, and
    atomically moved before the relational model/version/champion transaction.
    If relational finalization fails, the immutable artifact is compensated.
    """
    project_id = _required_text(project_id, "project_id")
    authorize_modeling_scope(user, project_id, "edit")
    model_name = _required_text(model_name, "model name")
    candidate_model_name = _required_text(
        candidate_model_name or model_name,
        "candidate model name",
    )
    algorithm = _required_text(algorithm, "algorithm")
    problem_type = _required_text(problem_type, "problem_type").lower()
    if problem_type not in {"classification", "regression"}:
        raise HTTPException(
            status_code=409,
            detail="Only supervised classification or regression candidates may be promoted.",
        )
    dataset_id = _required_text(dataset_id, "dataset_id")
    dataset_version_id = _required_text(
        dataset_version_id,
        "dataset_version_id",
    )
    training_run_id = _required_text(training_run_id, "training_run_id")
    feature_manifest_version = _required_text(
        feature_manifest_version,
        "feature_manifest_version",
    )
    canonical_lineage = _canonical_lineage(
        project_id=project_id,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        training_run_id=training_run_id,
        feature_manifest_version=feature_manifest_version,
        problem_type=problem_type,
        algorithm=algorithm,
        lineage=lineage,
        candidate_contract=candidate_contract,
        evaluation_package_id=evaluation_package_id,
    )
    frozen_candidate = canonical_lineage["candidateContract"]
    try:
        final_preprocessing_artifact = extract_final_preprocessing_artifact(
            fitted_object
        )
        final_preprocessing_artifact = validate_final_preprocessing_artifact(
            final_preprocessing_artifact,
            frozen_candidate,
            candidate_decision_id=canonical_lineage[
                "candidateDecisionId"
            ],
        )
    except PreprocessingContractError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Final-model promotion requires an executable fitted on the "
                f"complete Development Population with verified preprocessing lineage: {exc}"
            ),
        ) from exc
    frozen_training_timestamp = str(
        frozen_candidate.get("created_at") or ""
    ).strip()
    if training_timestamp and str(training_timestamp) != frozen_training_timestamp:
        raise HTTPException(
            status_code=409,
            detail="The promotion training timestamp conflicts with the frozen candidate.",
        )
    training_timestamp = frozen_training_timestamp
    frozen_algorithm_version = frozen_candidate.get("algorithm_version")
    if (
        algorithm_version not in (None, "")
        and frozen_algorithm_version not in (None, "")
        and str(algorithm_version) != str(frozen_algorithm_version)
    ):
        raise HTTPException(
            status_code=409,
            detail="The algorithm version conflicts with the frozen candidate.",
        )
    algorithm_version = algorithm_version or frozen_algorithm_version
    frozen_hyperparameters = frozen_candidate.get("hyperparameter_manifest") or {}
    if (
        hyperparameters is not None
        and json_dumps(hyperparameters, {})
        != json_dumps(frozen_hyperparameters, {})
    ):
        raise HTTPException(
            status_code=409,
            detail="The hyperparameters conflict with the frozen candidate contract.",
        )
    hyperparameters = frozen_hyperparameters
    if not isinstance(evaluation_summary, dict):
        raise HTTPException(
            status_code=422,
            detail="A completed exact evaluation package is required for promotion.",
        )
    nested_evaluation_package = evaluation_summary.get("evaluationPackage")
    if not isinstance(nested_evaluation_package, dict):
        nested_evaluation_package = evaluation_summary.get("evaluation_package")
    if not isinstance(nested_evaluation_package, dict):
        nested_evaluation_package = {}
    supplied_evaluation_package_id = str(
        evaluation_summary.get("evaluationPackageId")
        or evaluation_summary.get("evaluation_package_id")
        or nested_evaluation_package.get("evaluationPackageId")
        or nested_evaluation_package.get("evaluation_package_id")
        or ""
    ).strip()
    if not supplied_evaluation_package_id:
        raise HTTPException(
            status_code=422,
            detail="The completed evaluation package has no exact package identity.",
        )
    if supplied_evaluation_package_id != canonical_lineage["evaluationPackageId"]:
        raise HTTPException(
            status_code=409,
            detail="The evaluation package conflicts with the promotion lineage.",
        )
    service = get_persistence_service()
    durable_decision, durable_exposure, durable_package = (
        _durable_promotion_governance(service, canonical_lineage)
    )
    package_lineage = durable_package.get("canonical_lineage_json")
    package_lineage = package_lineage if isinstance(package_lineage, dict) else {}
    if str(
        package_lineage.get("final_preprocessing_artifact_checksum") or ""
    ) != str(final_preprocessing_artifact["final_artifact_checksum"]):
        raise HTTPException(
            status_code=409,
            detail=(
                "The Evaluation package does not bind the exact final "
                "Development-fitted preprocessing artifact."
            ),
        )
    # Never persist caller/browser Evaluation fields.  Reconstruct the summary
    # from the exact immutable package and exposure rows that unlocked
    # promotion, making retries stable and tamper independent.
    evaluation_summary = _canonical_package_summary(
        durable_package,
        durable_exposure,
    )
    canonical_lineage.update(
        {
            "candidateDecisionStatus": durable_decision["decision_status"],
            "candidateDecisionContractHash": durable_decision[
                "decision_contract_hash"
            ],
            "selectionMetricName": durable_decision["selection_metric_name"],
            "selectionMetricValue": durable_decision["selection_metric_value"],
            "selectionMetricSource": durable_decision[
                "selection_metric_source"
            ],
            "selectionMetricCreatedAt": durable_decision[
                "selection_metric_created_at"
            ],
            "outOfFoldPredictionArtifactId": durable_decision[
                "out_of_fold_prediction_artifact_id"
            ],
            "selectedCandidateContractHash": durable_decision[
                "selected_candidate_contract_hash"
            ],
            "selectionIntegrityStatus": durable_decision[
                "selection_integrity_status"
            ],
            "selectionLockedAt": durable_decision["selection_locked_at"],
            "holdoutExposureId": durable_exposure["holdout_exposure_id"],
            "finalHoldoutPartitionId": durable_exposure[
                "final_holdout_partition_id"
            ],
            "finalHoldoutStatus": durable_exposure["final_holdout_status"],
            "holdoutIsolationStatus": durable_package[
                "holdout_isolation_status"
            ],
            "thresholdLockedAt": durable_package["threshold_locked_at"],
            "lockedThreshold": durable_package["locked_threshold"],
            "thresholdSource": durable_package["threshold_source"],
            "thresholdPolicyHash": durable_package[
                "threshold_policy_hash"
            ],
            "evaluationPackageContractHash": durable_package[
                "evaluation_package_contract_hash"
            ],
            "evaluationPackageContentHash": durable_package["content_hash"],
            "evaluationPackageIntegrityStatus": durable_package[
                "package_integrity_status"
            ],
            "promotionReadinessStatus": "verified",
            "preprocessingContractVersion": final_preprocessing_artifact[
                "preprocessing_contract_version"
            ],
            "preprocessingPolicyId": final_preprocessing_artifact[
                "preprocessing_policy_id"
            ],
            "preprocessingPolicyRevision": final_preprocessing_artifact[
                "preprocessing_policy_revision"
            ],
            "preprocessingPolicyHash": final_preprocessing_artifact[
                "preprocessing_policy_hash"
            ],
            "finalPreprocessingArtifactChecksum": final_preprocessing_artifact[
                "final_artifact_checksum"
            ],
            "preprocessingFitScope": final_preprocessing_artifact["fit_scope"],
            "preprocessingFitPopulationId": final_preprocessing_artifact[
                "fit_population_id"
            ],
            "preprocessingFitPopulationRows": final_preprocessing_artifact[
                "fit_population_rows"
            ],
            "preprocessingApplicationScope": final_preprocessing_artifact[
                "application_scope"
            ],
            "preprocessingApplicationPopulationId": final_preprocessing_artifact[
                "application_population_id"
            ],
            "preprocessingApplicationPopulationRows": final_preprocessing_artifact[
                "application_population_rows"
            ],
            "finalHoldoutParameterInfluence": False,
            "finalHoldoutUsedForSelection": False,
            "finalHoldoutTransformedOrMaterializedPrelock": False,
        }
    )
    # Reconcile only artifacts old enough that they cannot belong to another
    # normal in-flight publisher. This handles the narrow process-crash window
    # between atomic filesystem finalization and the SQLite commit.
    model_artifacts.reconcile_artifact_storage(
        service.model_versions.artifact_version_ids(),
        minimum_age_seconds=300.0,
    )
    model_version_id = new_model_version_id()
    timestamp = now_iso()
    staged: Dict[str, Any] | None = None
    finalized_artifact: Dict[str, Any] | None = None
    relational_committed = False
    try:
        staged = model_artifacts.stage_model_artifact(
            model_version_id,
            fitted_object,
        )
        fingerprint = _publication_fingerprint(
            {
                "projectId": project_id,
                "modelName": model_name,
                "candidateModelName": candidate_model_name,
                "problemType": problem_type,
                "algorithm": algorithm,
                "algorithmVersion": algorithm_version,
                "trainingRunId": training_run_id,
                "datasetId": dataset_id,
                "datasetVersionId": dataset_version_id,
                "featureManifestVersion": feature_manifest_version,
                "hyperparameters": hyperparameters or {},
                "trainingParameters": training_parameters or {},
                "metricsSummary": metrics_summary or {},
                "evaluationSummary": evaluation_summary or {},
                "interpretationSummary": interpretation_summary or {},
                "lineage": canonical_lineage,
                "artifactChecksum": staged["checksum"],
                "artifactFormat": staged["format"],
            }
        )
        durable_idempotency_key = _idempotency_storage_key(
            project_id,
            idempotency_key,
            fingerprint,
        )

        # Avoid publishing a second filesystem artifact on ordinary retries.
        # The repository repeats this check under BEGIN IMMEDIATE for races.
        existing = service.model_versions.find_by_idempotency(
            project_id,
            durable_idempotency_key,
        )
        if existing:
            if existing.get("publication_fingerprint") != fingerprint:
                raise ModelRegistryConflictError(
                    "The idempotency key was already used for different model content."
                )
            model_artifacts.discard_staged_model_artifact(staged)
            staged = None
            _verify_recoverable_version(service, existing)
            existing_model = service.models.get(existing["model_id"])
            if not existing_model or existing_model.get("project_id") != project_id:
                raise ModelRegistryConflictError(
                    "The idempotent model version has no exact project-bound parent."
                )
            return _publication_response(
                existing_model,
                existing,
                idempotent_replay=True,
            )

        finalized_artifact = model_artifacts.finalize_staged_model_artifact(staged)
        staged = None
        # Verify the immutable destination again before any relational state is
        # eligible to commit.
        model_artifacts.verify_model_artifact(
            finalized_artifact["path"],
            expected_checksum=finalized_artifact["checksum"],
            expected_model_version_id=model_version_id,
            deserialize=True,
        )
        model_record = {
            "model_id": new_model_id(),
            "project_id": project_id,
            "name": model_name,
            "problem_type": problem_type,
            "status": "active",
            "owner_user_id": str(user.get("userId") or ""),
            "created_at": timestamp,
            "updated_at": timestamp,
            "current_version_id": None,
            "current_version_generation": 0,
            "champion_updated_at": None,
            "champion_updated_by": None,
            "archived": False,
            "archived_at": None,
            "tags_json": [],
            "description": None,
        }
        model_version_contract = {
            "contractType": "immutable_model_version_v1",
            "modelVersionId": model_version_id,
            # The parent registry name is a stable project/context identity.
            # Preserve the server-resolved human candidate label separately in
            # the immutable version contract so restart recovery never has to
            # display an opaque model_id or infer a label from an algorithm id.
            "modelName": candidate_model_name,
            "candidateModelName": candidate_model_name,
            "projectId": project_id,
            "trainingDatasetId": dataset_id,
            "trainingDatasetVersionId": dataset_version_id,
            "candidateId": canonical_lineage["candidateId"],
            "trainingJobId": canonical_lineage["trainingJobId"],
            "trainingRunId": training_run_id,
            "evaluationPackageId": canonical_lineage["evaluationPackageId"],
            "candidateDecisionId": canonical_lineage["candidateDecisionId"],
            "candidateDecisionStatus": durable_decision["decision_status"],
            "candidateDecisionContractHash": durable_decision[
                "decision_contract_hash"
            ],
            "candidateContractHash": canonical_lineage[
                "candidateContractHash"
            ],
            "candidateContract": canonical_lineage["candidateContract"],
            "targetContractId": canonical_lineage["targetContractId"],
            "targetDefinition": canonical_lineage["targetDefinition"],
            "positiveClass": canonical_lineage["positiveClass"],
            "predictorManifestId": canonical_lineage["predictorManifestId"],
            "predictorManifestHash": canonical_lineage["predictorManifestHash"],
            "treatmentManifestId": canonical_lineage["treatmentManifestId"],
            "treatmentManifestHash": canonical_lineage["treatmentManifestHash"],
            "preprocessingContractVersion": final_preprocessing_artifact[
                "preprocessing_contract_version"
            ],
            "preprocessingPolicyId": final_preprocessing_artifact[
                "preprocessing_policy_id"
            ],
            "preprocessingPolicyRevision": final_preprocessing_artifact[
                "preprocessing_policy_revision"
            ],
            "preprocessingPolicyHash": final_preprocessing_artifact[
                "preprocessing_policy_hash"
            ],
            "finalPreprocessingArtifactChecksum": final_preprocessing_artifact[
                "final_artifact_checksum"
            ],
            "finalPreprocessingArtifact": final_preprocessing_artifact,
            "preprocessingFitScope": final_preprocessing_artifact["fit_scope"],
            "preprocessingFitPopulationId": final_preprocessing_artifact[
                "fit_population_id"
            ],
            "preprocessingFitPopulationRows": final_preprocessing_artifact[
                "fit_population_rows"
            ],
            "preprocessingApplicationScope": final_preprocessing_artifact[
                "application_scope"
            ],
            "preprocessingApplicationPopulationId": final_preprocessing_artifact[
                "application_population_id"
            ],
            "preprocessingApplicationPopulationRows": final_preprocessing_artifact[
                "application_population_rows"
            ],
            "finalHoldoutTargetAccessed": True,
            "finalHoldoutParameterInfluence": False,
            "finalHoldoutUsedForSelection": False,
            "finalHoldoutTransformedOrMaterializedPrelock": False,
            "finalHoldoutOpenedForFinalReporting": True,
            "featureManifestId": canonical_lineage["featureManifestId"],
            "featureManifestHash": canonical_lineage["featureManifestHash"],
            "validationDesignId": canonical_lineage["validationDesignId"],
            "validationDesignVersion": canonical_lineage[
                "validationDesignVersion"
            ],
            "splitId": canonical_lineage["splitId"],
            "algorithm": algorithm,
            "algorithmVersion": algorithm_version,
            "hyperparameters": hyperparameters or {},
            "calibrationConfiguration": canonical_lineage[
                "candidateContract"
            ].get("calibration_configuration")
            or {},
            "runtimeEnvironment": canonical_lineage["candidateContract"].get(
                "runtime_environment"
            )
            or {},
            "rankingMetric": canonical_lineage["candidateContract"].get(
                "ranking_metric"
            ),
            "selectionMetric": canonical_lineage["candidateContract"].get(
                "selection_metric"
            ),
            "selectionMetricCreatedAt": durable_decision[
                "selection_metric_created_at"
            ],
            "outOfFoldPredictionArtifactId": durable_decision[
                "out_of_fold_prediction_artifact_id"
            ],
            "selectedCandidateContractHash": durable_decision[
                "selected_candidate_contract_hash"
            ],
            "selectionIntegrityStatus": "verified",
            "selectionLockedAt": durable_decision["selection_locked_at"],
            "holdoutExposureId": durable_exposure["holdout_exposure_id"],
            "finalHoldoutPartitionId": durable_exposure[
                "final_holdout_partition_id"
            ],
            "finalHoldoutStatus": durable_exposure["final_holdout_status"],
            "holdoutIsolationStatus": "verified",
            "thresholdLockedAt": durable_package["threshold_locked_at"],
            "lockedThreshold": durable_package["locked_threshold"],
            "thresholdSource": durable_package["threshold_source"],
            "thresholdPolicyHash": durable_package[
                "threshold_policy_hash"
            ],
            "evaluationPackageContractHash": durable_package[
                "evaluation_package_contract_hash"
            ],
            "evaluationPackageContentHash": durable_package["content_hash"],
            "evaluationPackageIntegrityStatus": durable_package[
                "package_integrity_status"
            ],
            "promotionReadinessStatus": "verified",
            "randomSeed": canonical_lineage["candidateContract"].get(
                "random_seed"
            ),
            "artifactReference": finalized_artifact["path"],
            "artifactChecksum": finalized_artifact["checksum"],
            "artifactSizeBytes": finalized_artifact["sizeBytes"],
            "artifactFormat": finalized_artifact["format"],
            "createdBy": str(user.get("userId") or ""),
            "createdAt": timestamp,
        }
        version_record = {
            "model_version_id": model_version_id,
            # The repository binds model_id and version_number atomically.
            "model_id": model_record["model_id"],
            "version_number": 0,
            "training_run_id": training_run_id,
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "feature_manifest_version": feature_manifest_version,
            "algorithm": algorithm,
            "algorithm_version": algorithm_version,
            "hyperparameters_json": hyperparameters or {},
            "training_parameters_json": training_parameters or {},
            "metrics_summary_json": metrics_summary or {},
            "evaluation_summary_json": evaluation_summary or {},
            "interpretation_summary_json": interpretation_summary or {},
            "artifact_reference": finalized_artifact["path"],
            "artifact_format": finalized_artifact["format"],
            "artifact_size_bytes": finalized_artifact["sizeBytes"],
            "training_timestamp": training_timestamp or timestamp,
            "checksum": finalized_artifact["checksum"],
            "publication_status": FINALIZED_PUBLICATION_STATUS,
            "artifact_verified_at": timestamp,
            "finalized_at": timestamp,
            "idempotency_key": durable_idempotency_key,
            "publication_fingerprint": fingerprint,
            "lineage_status": VERIFIED_LINEAGE_STATUS,
            "quarantine_reason": None,
            "quarantined_at": None,
            "candidate_id": canonical_lineage["candidateId"],
            "evaluation_package_id": canonical_lineage[
                "evaluationPackageId"
            ],
            "candidate_decision_id": canonical_lineage[
                "candidateDecisionId"
            ],
            "candidate_decision_status": durable_decision["decision_status"],
            "candidate_decision_contract_hash": durable_decision[
                "decision_contract_hash"
            ],
            "selection_metric_name": durable_decision[
                "selection_metric_name"
            ],
            "selection_metric_value": durable_decision[
                "selection_metric_value"
            ],
            "selection_metric_source": durable_decision[
                "selection_metric_source"
            ],
            "selection_metric_created_at": durable_decision[
                "selection_metric_created_at"
            ],
            "out_of_fold_prediction_artifact_id": durable_decision[
                "out_of_fold_prediction_artifact_id"
            ],
            "selected_candidate_contract_hash": durable_decision[
                "selected_candidate_contract_hash"
            ],
            "selection_integrity_status": "verified",
            "selection_locked_at": durable_decision["selection_locked_at"],
            "holdout_exposure_id": durable_exposure["holdout_exposure_id"],
            "final_holdout_partition_id": durable_exposure[
                "final_holdout_partition_id"
            ],
            "final_holdout_status": durable_exposure[
                "final_holdout_status"
            ],
            "holdout_isolation_status": "verified",
            "threshold_locked_at": durable_package["threshold_locked_at"],
            "locked_threshold": durable_package["locked_threshold"],
            "threshold_source": durable_package["threshold_source"],
            "threshold_policy_hash": durable_package[
                "threshold_policy_hash"
            ],
            "evaluation_package_contract_hash": durable_package[
                "evaluation_package_contract_hash"
            ],
            "evaluation_package_content_hash": durable_package[
                "content_hash"
            ],
            "evaluation_package_integrity_status": durable_package[
                "package_integrity_status"
            ],
            "promotion_readiness_status": "verified",
            "target_name": canonical_lineage["target"],
            "validation_design_id": canonical_lineage[
                "validationDesignId"
            ],
            "split_id": canonical_lineage["splitId"],
            "candidate_contract_hash": canonical_lineage[
                "candidateContractHash"
            ],
            "model_contract_json": model_version_contract,
            "previous_champion_version_id": None,
            "approval_status": "unreviewed",
            "validation_status": "not_validated",
            "documentation_status": "not_documented",
            "lineage_json": canonical_lineage,
            "created_by": str(user.get("userId") or ""),
            "created_at": timestamp,
        }
        outcome = service.model_versions.publish_finalized(
            model_record,
            version_record,
        )
        if outcome["idempotent_replay"]:
            # A concurrent publisher won with the same key. Its artifact and
            # row are authoritative; compensate this unused unique path.
            _verify_recoverable_version(service, outcome["model_version"])
            model_artifacts.delete_model_artifact(model_version_id)
            finalized_artifact = None
        else:
            relational_committed = True
        return _publication_response(
            outcome["model"],
            outcome["model_version"],
            idempotent_replay=bool(outcome["idempotent_replay"]),
        )
    except ModelRegistryConflictError as exc:
        if staged is not None:
            model_artifacts.discard_staged_model_artifact(staged)
        if finalized_artifact is not None and not relational_committed:
            model_artifacts.delete_model_artifact(model_version_id)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        if staged is not None:
            model_artifacts.discard_staged_model_artifact(staged)
        if finalized_artifact is not None and not relational_committed:
            model_artifacts.delete_model_artifact(model_version_id)
        raise
    except Exception as exc:
        if staged is not None:
            model_artifacts.discard_staged_model_artifact(staged)
        if finalized_artifact is not None and not relational_committed:
            model_artifacts.delete_model_artifact(model_version_id)
        raise HTTPException(
            status_code=500,
            detail="Durable model publication could not be finalized.",
        ) from exc


def list_models(user: Dict[str, Any], project_id: str, **filters: Any) -> List[Dict[str, Any]]:
    authorize_modeling_scope(user, project_id, "view")
    service = get_persistence_service()
    rows = service.models.list(project_id=project_id, **filters)
    return [_to_api(row) for row in rows]


def _get_model_authorized(user: Dict[str, Any], model_id: str) -> Dict[str, Any]:
    service = get_persistence_service()
    row = service.models.get(model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    project_id = str(row.get("project_id") or "").strip()
    if not project_id:
        raise HTTPException(
            status_code=409,
            detail="This model has no exact project ownership and is unavailable.",
        )
    authorize_modeling_scope(user, project_id, "view")
    return row


def get_model(user: Dict[str, Any], model_id: str) -> Dict[str, Any]:
    return _to_api(_get_model_authorized(user, model_id))


def list_versions(user: Dict[str, Any], model_id: str, **filters: Any) -> List[Dict[str, Any]]:
    _get_model_authorized(user, model_id)
    service = get_persistence_service()
    rows = service.model_versions.list(model_id=model_id, **filters)
    return [_to_api(row) for row in rows]


def _get_version_authorized(user: Dict[str, Any], model_version_id: str) -> Dict[str, Any]:
    service = get_persistence_service()
    row = service.model_versions.get(model_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model version not found.")
    project_id = str(row.get("project_id") or "").strip()
    if not project_id:
        raise HTTPException(
            status_code=409,
            detail="This model version has no exact project ownership and is unavailable.",
        )
    # ACL evaluation deliberately precedes artifact/path inspection.
    authorize_modeling_scope(user, project_id, "view")
    parent = service.models.get(str(row.get("model_id") or ""))
    if not parent or parent.get("project_id") != project_id:
        _quarantine_recovery_failure(
            service,
            row,
            "The model version has no exact project-bound parent model.",
        )
        raise HTTPException(
            status_code=409,
            detail="This model version has no exact project-bound parent model.",
        )
    return row


def get_version(user: Dict[str, Any], model_version_id: str) -> Dict[str, Any]:
    return _to_api(_get_version_authorized(user, model_version_id))


def load_version_artifact(
    user: Dict[str, Any],
    model_version_id: str,
    *,
    expected_project_id: Optional[str] = None,
) -> Any:
    """Loads the actual fitted object back into memory -- used by the scoring
    fallback path when RESULTS.final_model is unavailable (e.g. after a
    process restart) but a durable ModelVersion + artifact exist."""
    row = _get_version_authorized(user, model_version_id)
    if (
        expected_project_id is not None
        and str(expected_project_id).strip() != row.get("project_id")
    ):
        raise HTTPException(
            status_code=409,
            detail="The requested project does not own this exact model version.",
        )
    service = get_persistence_service()
    verification = _verify_recoverable_version(
        service,
        row,
        deserialize=True,
    )
    executable = verification["object"]
    from .mlb_v18_conditional import FORMAT
    if row.get("artifact_format") == FORMAT:
        return executable
    model_contract = row.get("model_contract_json")
    model_contract = model_contract if isinstance(model_contract, dict) else {}
    candidate_contract = model_contract.get("candidateContract")
    embedded_record = model_contract.get("finalPreprocessingArtifact")
    if not isinstance(candidate_contract, dict) or not isinstance(
        embedded_record, dict
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "This model version predates verified final preprocessing "
                "lineage and cannot be executed. Recompute and republish it."
            ),
        )
    try:
        executable_record = extract_final_preprocessing_artifact(executable)
        executable_record = validate_final_preprocessing_artifact(
            executable_record,
            candidate_contract,
            candidate_decision_id=str(
                model_contract.get("candidateDecisionId") or ""
            )
            or None,
        )
    except PreprocessingContractError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "The registered executable has unverifiable final preprocessing "
                f"lineage: {exc}"
            ),
        ) from exc
    if executable_record != embedded_record:
        raise HTTPException(
            status_code=409,
            detail=(
                "The model-version contract conflicts with the final "
                "preprocessing artifact embedded in its executable."
            ),
        )
    return executable


def get_recovery_status(
    user: Dict[str, Any],
    project_id: str,
    model_version_id: str,
) -> Dict[str, Any]:
    project_id = _required_text(project_id, "project_id")
    row = _get_version_authorized(user, model_version_id)
    if row.get("project_id") != project_id:
        raise HTTPException(
            status_code=409,
            detail="The requested project does not own this exact model version.",
        )
    service = get_persistence_service()
    verification = _verify_recoverable_version(service, row)
    return {
        "status": verification.get("status", "ready"),
        "projectId": project_id,
        "modelId": row["model_id"],
        "modelVersionId": row["model_version_id"],
        "publicationStatus": row["publication_status"],
        "lineageStatus": row["lineage_status"],
        "artifactVerified": True,
        "checksum": verification["checksum"],
        "artifactFormat": row["artifact_format"],
        "historicalValidation": verification.get("historicalValidation"),
    }


def resolve_current_version_by_exact_context(
    user: Dict[str, Any],
    *,
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    target_name: str,
) -> Dict[str, Any]:
    project_id = _required_text(project_id, "project_id")
    dataset_id = _required_text(dataset_id, "dataset_id")
    dataset_version_id = _required_text(
        dataset_version_id,
        "dataset_version_id",
    )
    target_name = _required_text(target_name, "target_name")
    # Authorize the caller-supplied exact project before revealing whether a
    # champion exists for any of the other context values.
    authorize_modeling_scope(user, project_id, "view")
    service = get_persistence_service()
    matches = service.model_versions.find_current_by_exact_context(
        project_id=project_id,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        target_name=target_name,
    )
    context = {
        "projectId": project_id,
        "datasetId": dataset_id,
        "datasetVersionId": dataset_version_id,
        "targetName": target_name,
    }
    if not matches:
        return {
            "status": "not_ready",
            "reason": "no_exact_current_model_version",
            **context,
            "modelVersion": None,
        }
    if len(matches) != 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "More than one current model version matches the exact governed "
                "project, dataset version, and target context."
            ),
        )
    row = matches[0]
    verification = _verify_recoverable_version(service, row)
    parent = service.models.get(row["model_id"])
    if (
        not parent
        or parent.get("project_id") != project_id
        or parent.get("current_version_id") != row["model_version_id"]
    ):
        _quarantine_recovery_failure(
            service,
            row,
            "The exact-context champion pointer is not internally consistent.",
        )
        raise HTTPException(
            status_code=409,
            detail="The exact-context champion pointer is not internally consistent.",
        )
    model_contract = row.get("model_contract_json")
    model_contract = model_contract if isinstance(model_contract, dict) else {}
    model_name = str(
        model_contract.get("candidateModelName")
        or model_contract.get("modelName")
        or parent.get("name")
        or ""
    ).strip()
    return {
        "status": verification.get("status", "ready"),
        **context,
        "modelId": row["model_id"],
        "modelName": model_name,
        "modelVersionId": row["model_version_id"],
        "publicationStatus": row["publication_status"],
        "lineageStatus": row["lineage_status"],
        "artifactVerified": True,
        "checksum": verification["checksum"],
        "artifactFormat": row["artifact_format"],
        "modelVersion": _to_api(row),
        "historicalValidation": verification.get("historicalValidation"),
    }


def register_mlb_v18_conditional_champion(user, manifest_path, manifest_sha256):
    """James's frozen V18 prospective decision; no generic promotion-gate bypass."""
    from .mlb_v18_conditional import PROJECT, register_authorized
    authorize_modeling_scope(user, PROJECT, "edit")
    return register_authorized(get_persistence_service(), user, manifest_path, manifest_sha256)


def promote_champion(
    user: Dict[str, Any],
    model_id: str,
    model_version_id: str,
    *,
    expected_generation: Optional[int] = None,
) -> Dict[str, Any]:
    if expected_generation is not None:
        try:
            expected_generation = int(expected_generation)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail="expectedGeneration must be a non-negative integer.",
            ) from exc
        if expected_generation < 0:
            raise HTTPException(
                status_code=422,
                detail="expectedGeneration must be a non-negative integer.",
            )
    model = _get_model_authorized(user, model_id)
    authorize_modeling_scope(user, model["project_id"], "edit")
    version = _get_version_authorized(user, model_version_id)
    from .mlb_v18_conditional import FORMAT
    if version.get("artifact_format") == FORMAT:
        raise HTTPException(status_code=409, detail="Conditional V18 authority requires its separately versioned decision; generic promotion cannot remove the historical limitation.")
    if version.get("model_id") != model_id:
        raise HTTPException(
            status_code=409,
            detail="The requested champion is not a version of this model.",
        )
    service = get_persistence_service()
    _verify_recoverable_version(service, version)
    try:
        promoted = service.models.promote_champion(
            model_id,
            model_version_id,
            actor_user_id=str(user.get("userId") or ""),
            expected_generation=expected_generation,
        )
    except ModelRegistryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_api(promoted)


def archive_model(user: Dict[str, Any], model_id: str) -> Dict[str, Any]:
    row = _get_model_authorized(user, model_id)
    authorize_modeling_scope(user, row["project_id"], "edit")
    service = get_persistence_service()
    saved = service.models.archive(
        model_id,
        actor_user_id=str(user.get("userId") or ""),
    )
    return _to_api(saved)


def archive_version(user: Dict[str, Any], model_version_id: str) -> Dict[str, Any]:
    """Archiving a version preserves lineage (Phase L) -- the row and its
    artifact are never deleted, only marked archived_at. If this was the
    parent Model's current version, the Model's currentVersionId is honestly
    cleared rather than left silently pointing at an archived version."""
    row = _get_version_authorized(user, model_version_id)
    authorize_modeling_scope(user, row["project_id"], "edit")
    service = get_persistence_service()
    archived = service.model_versions.archive_and_clear_champion(
        model_version_id,
        actor_user_id=str(user.get("userId") or ""),
    )
    return _to_api(archived or row)


def compare_versions(user: Dict[str, Any], model_version_ids: List[str]) -> Dict[str, Any]:
    if len(model_version_ids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least two modelVersionIds to compare.")
    if len(model_version_ids) > 10:
        raise HTTPException(status_code=400, detail="Cannot compare more than 10 model versions at once.")
    rows = [_get_version_authorized(user, version_id) for version_id in model_version_ids]
    return {
        "versions": [
            {
                "modelVersionId": row["model_version_id"],
                "modelId": row["model_id"],
                "versionNumber": row["version_number"],
                "algorithm": row.get("algorithm"),
                "algorithmVersion": row.get("algorithm_version"),
                "hyperparameters": row.get("hyperparameters_json"),
                "metricsSummary": row.get("metrics_summary_json"),
                "datasetId": row.get("dataset_id"),
                "datasetVersionId": row.get("dataset_version_id"),
                "featureManifestVersion": row.get("feature_manifest_version"),
                "trainingTimestamp": row.get("training_timestamp"),
                "lineage": row.get("lineage_json"),
                "approvalStatus": row.get("approval_status"),
                "validationStatus": row.get("validation_status"),
            }
            for row in rows
        ]
    }


def set_governance_status(
    user: Dict[str, Any], model_version_id: str, *,
    approval_status: Optional[str] = None, validation_status: Optional[str] = None, documentation_status: Optional[str] = None,
) -> Dict[str, Any]:
    row = _get_version_authorized(user, model_version_id)
    authorize_modeling_scope(user, row["project_id"], "edit")
    from .mlb_v18_conditional import FORMAT
    if row.get("artifact_format") == FORMAT:
        raise HTTPException(status_code=409, detail="Conditional V18 governance is frozen in its decision manifest; publish a separately authorized successor.")
    service = get_persistence_service()
    updated = service.model_versions.set_governance_status(
        model_version_id, approval_status=approval_status, validation_status=validation_status, documentation_status=documentation_status,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Model version not found.")
    return _to_api(updated)


def archive_registry_for_project(project_id: str) -> Dict[str, int]:
    """Project-deletion lifecycle hook (Phase L, mirroring Phase I from the
    Persistent Scoring Runs phase) -- archives (never deletes) every Model and
    ModelVersion belonging to the project. Scoring Runs, Evidence, and
    Dataset Versions referencing an archived model/version are untouched."""
    service = get_persistence_service()
    versions_archived = service.model_versions.archive_for_project(project_id)
    models_archived = service.models.archive_for_project(project_id)
    return {"modelsArchived": models_archived, "versionsArchived": versions_archived}

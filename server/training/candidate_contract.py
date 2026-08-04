from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from importlib import metadata as importlib_metadata
import json
import math
import os
import platform
import re
from typing import Any, Mapping


class CandidateContractError(ValueError):
    """Raised when a completed candidate's frozen lineage is invalid."""


SELECTION_METRIC_FIELDS = (
    "selection_metric_name",
    "selection_metric_value",
    "selection_metric_source",
    "selection_partition_id",
    "fold_definition_id",
    "fold_count",
    "fold_values",
    "mean",
    "standard_deviation",
    "out_of_fold_prediction_artifact_id",
    "threshold_source",
    "calibration_source",
    "created_at",
)


def _normalized_metric(value: Any, problem_type: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")
    if problem_type == "regression":
        aliases = {
            "mean_absolute_error": "mae",
            "mean_squared_error": "mse",
            "root_mean_squared_error": "rmse",
            "r_squared": "r2",
            "r_2": "r2",
            "adjusted_r_squared": "adjusted_r2",
        }
        resolved = aliases.get(token, token)
        return resolved if resolved in {"mae", "mse", "rmse", "r2", "adjusted_r2"} else "r2"
    aliases = {
        "auc": "roc_auc",
        "roc": "roc_auc",
        "rocauc": "roc_auc",
        "prauc": "pr_auc",
        "average_precision": "pr_auc",
        "average_precision_score": "pr_auc",
    }
    resolved = aliases.get(token, token)
    return resolved if resolved in {
        "roc_auc", "pr_auc", "accuracy", "precision", "recall", "f1", "ks", "gini"
    } else "roc_auc"


def _json_default(value: Any) -> str:
    return str(value)


def canonical_contract_hash(payload: Mapping[str, Any] | list[Any] | Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _manifest_identity(prefix: str, payload: Mapping[str, Any]) -> tuple[str, str]:
    digest = canonical_contract_hash(payload)
    return f"{prefix}-{digest[:20]}", digest


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in (
        "numpy",
        "pandas",
        "scikit-learn",
        "xgboost",
        "lightgbm",
        "catboost",
        "interpret",
        "torch",
    ):
        try:
            versions[package] = importlib_metadata.version(package)
        except importlib_metadata.PackageNotFoundError:
            continue
    return versions


def complete_training_contract(
    base_contract: Mapping[str, Any],
    *,
    feature_manifest: Mapping[str, Any],
    store_meta: Mapping[str, Any],
    training_job_id: str,
    training_run_id: str,
    created_by: str,
    created_at: str,
    primary_metric: str,
) -> dict[str, Any]:
    """Add immutable governed lineage to a job contract captured at submission.

    The function consumes only the submission-time snapshot. Callers must not
    invoke it again from mutable workflow state when a background job finishes.
    """

    contract = deepcopy(dict(base_contract))
    target_semantics_authority = deepcopy(
        contract.get("target_semantics_authority")
        if isinstance(contract.get("target_semantics_authority"), Mapping)
        else {}
    )
    if target_semantics_authority:
        authority_payload = deepcopy(target_semantics_authority)
        recorded_authority_hash = str(
            authority_payload.pop("target_authority_hash", "") or ""
        )
        if (
            not recorded_authority_hash
            or recorded_authority_hash
            != canonical_contract_hash(authority_payload)
        ):
            raise CandidateContractError(
                "The governed training target authority is missing or has been modified."
            )
    target_definition = {
        "target_name": str(contract.get("target") or ""),
        "problem_type": str(contract.get("problem_type") or ""),
        "positive_class": contract.get("event_value"),
        "negative_class": contract.get("non_event_value"),
        "source_target_contract_id": str(
            contract.get("source_target_contract_id")
            or target_semantics_authority.get("source_target_contract_id")
            or ""
        ),
        "target_authority_hash": str(
            contract.get("target_authority_hash")
            or target_semantics_authority.get("target_authority_hash")
            or ""
        ),
        "authority_source": str(
            target_semantics_authority.get("authority_source") or ""
        ),
        "analysis_partition_id": str(
            contract.get("analysis_partition_id")
            or target_semantics_authority.get("analysis_partition_id")
            or ""
        ),
        "analysis_partition_revision": (
            contract.get("analysis_partition_revision")
            if contract.get("analysis_partition_revision") is not None
            else target_semantics_authority.get(
                "analysis_partition_revision"
            )
        ),
    }
    target_contract_id, _ = _manifest_identity("target", target_definition)

    predictor_payload = {
        "project_id": contract.get("project_id"),
        "dataset_id": contract.get("dataset_id"),
        "dataset_version_id": contract.get("dataset_version_id"),
        "target_name": target_definition["target_name"],
        "selected_original_features": list(
            contract.get("selected_original_features") or []
        ),
        "selected_engineered_features": list(
            contract.get("selected_engineered_features") or []
        ),
    }
    predictor_manifest_id, predictor_manifest_hash = _manifest_identity(
        "pm", predictor_payload
    )

    treatment_payload = {
        "project_id": contract.get("project_id"),
        "dataset_id": contract.get("dataset_id"),
        "dataset_version_id": contract.get("dataset_version_id"),
        "outlier_application": deepcopy(store_meta.get("outlier_application")),
        "missing_application": deepcopy(store_meta.get("missing_application")),
        "missing_validation": deepcopy(store_meta.get("missing_validation")),
        "preprocessing_pipeline": deepcopy(
            contract.get("preprocessing_pipeline") or []
        ),
    }
    treatment_manifest_id, treatment_manifest_hash = _manifest_identity(
        "tm", treatment_payload
    )

    feature_manifest_hash = str(
        feature_manifest.get("manifest_hash")
        or feature_manifest.get("manifest_version")
        or contract.get("feature_manifest_version")
        or ""
    )
    feature_manifest_id = str(
        feature_manifest.get("manifest_id")
        or feature_manifest.get("manifest_version")
        or feature_manifest_hash
    )
    materialization_id = str(
        feature_manifest.get("materialization_id")
        or feature_manifest.get("materialization_hash")
        or _manifest_identity(
            "materialization",
            {
                "project_id": contract.get("project_id"),
                "dataset_id": contract.get("dataset_id"),
                "dataset_version_id": contract.get("dataset_version_id"),
                "feature_manifest_id": feature_manifest_id,
                "feature_manifest_hash": feature_manifest_hash,
                "materialized_manifest_hash": feature_manifest.get(
                    "materialized_manifest_hash"
                ),
            },
        )[0]
    )

    runtime_environment = dict(contract.get("runtime_environment") or {})
    runtime_environment.update(
        {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "package_versions": _package_versions(),
            "code_version": str(os.getenv("ATLAS_CODE_VERSION") or "local"),
        }
    )
    worker_configuration = dict(contract.get("worker_configuration") or {})
    worker_configuration.setdefault(
        "requested_workers", runtime_environment.get("requested_workers", 1)
    )
    worker_configuration.setdefault(
        "honored_workers", runtime_environment.get("honored_workers", 1)
    )
    worker_configuration.setdefault(
        "execution_mode",
        runtime_environment.get("execution_mode") or "local_background_workers",
    )

    contract.update(
        {
            "training_job_id": training_job_id,
            "training_run_id": training_run_id,
            "training_dataset_id": contract.get("dataset_id"),
            "training_dataset_version_id": contract.get("dataset_version_id"),
            "target_name": target_definition["target_name"],
            "target_definition": target_definition,
            "target_contract_id": target_contract_id,
            "positive_class": target_definition["positive_class"],
            "predictor_manifest_id": predictor_manifest_id,
            "predictor_manifest_hash": predictor_manifest_hash,
            "treatment_manifest_id": treatment_manifest_id,
            "treatment_manifest_hash": treatment_manifest_hash,
            "feature_manifest_id": feature_manifest_id,
            "feature_manifest_hash": feature_manifest_hash,
            "materialization_id": materialization_id,
            "ranking_metric": _normalized_metric(
                primary_metric,
                target_definition["problem_type"],
            ),
            "created_by": created_by,
            "created_at": created_at,
            "runtime_environment": runtime_environment,
            "worker_configuration": worker_configuration,
        }
    )
    contract["contract_hash"] = canonical_contract_hash(contract)
    return contract


def _artifact_algorithm_version(artifact: Any) -> tuple[str, str | None]:
    if artifact is None:
        return "unavailable", None
    artifact_type = type(artifact)
    module_name = str(getattr(artifact_type, "__module__", "") or "")
    class_name = str(getattr(artifact_type, "__qualname__", "") or "")
    module_root = module_name.split(".", 1)[0]
    distribution = {
        "sklearn": "scikit-learn",
        "interpret": "interpret",
    }.get(module_root, module_root.replace("_", "-"))
    version: str | None = None
    if distribution:
        try:
            version = importlib_metadata.version(distribution)
        except importlib_metadata.PackageNotFoundError:
            version = None
    return ".".join(part for part in (module_name, class_name) if part), version


def build_candidate_contract(
    training_contract: Mapping[str, Any],
    *,
    algorithm_id: str,
    candidate_metrics: Mapping[str, Any],
    artifact: Any,
    created_at: str,
) -> dict[str, Any]:
    assert_training_contract_intact(training_contract)
    contract = deepcopy(dict(training_contract))
    training_run_id = str(contract.get("training_run_id") or "")
    if not training_run_id or not algorithm_id:
        raise CandidateContractError(
            "A training_run_id and algorithm_id are required to freeze a candidate."
        )
    algorithm_class, algorithm_version = _artifact_algorithm_version(artifact)
    candidate_id = "candidate-" + canonical_contract_hash(
        {
            "project_id": contract.get("project_id"),
            "training_run_id": training_run_id,
            "algorithm_id": algorithm_id,
        }
    )[:24]
    hyperparameter_manifest = deepcopy(
        candidate_metrics.get("best_params")
        or candidate_metrics.get("parameters")
        or {}
    )
    threshold_configuration = {
        "locked_threshold": candidate_metrics.get("locked_threshold"),
        "threshold_source": str(
            (candidate_metrics.get("selection_metric") or {}).get(
                "threshold_source"
            )
            or ""
        ),
        "threshold_locked_at": created_at,
        "selection_threshold_tuned": False,
    }
    threshold_configuration["threshold_policy_hash"] = canonical_contract_hash(
        threshold_configuration
    )
    candidate = {
        key: deepcopy(contract.get(key))
        for key in (
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "training_dataset_id",
            "training_dataset_version_id",
            "target",
            "target_name",
            "problem_type",
            "target_definition",
            "target_contract_id",
            "positive_class",
            "source_target_contract_id",
            "target_authority_hash",
            "target_semantics_authority",
            "analysis_partition_id",
            "analysis_partition_revision",
            "predictor_manifest_id",
            "predictor_manifest_hash",
            "treatment_manifest_id",
            "treatment_manifest_hash",
            "feature_manifest_id",
            "feature_manifest_hash",
            "feature_manifest_version",
            "materialization_id",
            "validation_design_id",
            "validation_design_version",
            "split_id",
            "training_population_id",
            "selection_partition_id",
            "holdout_population_id",
            "final_holdout_partition_id",
            "fold_definition_id",
            "final_holdout_status",
            "holdout_isolation_status",
            "selection_resampling_status",
            "validation_execution_policy",
            "training_job_id",
            "training_run_id",
            "ranking_metric",
            "created_by",
            "runtime_environment",
            "worker_configuration",
            "random_seed",
        )
    }
    candidate.update(
        {
            "candidate_id": candidate_id,
            "algorithm_id": algorithm_id,
            "algorithm_class": algorithm_class,
            "algorithm_version": algorithm_version or "unavailable",
            "hyperparameter_manifest": hyperparameter_manifest,
            "calibration_configuration": deepcopy(
                contract.get("calibration_configuration") or {}
            ),
            "selection_metric": deepcopy(
                candidate_metrics.get("selection_metric") or {}
            ),
            "selection_integrity_status": str(
                candidate_metrics.get("selection_integrity_status") or ""
            ),
            "class_encoding": deepcopy(
                candidate_metrics.get("class_encoding") or {}
            ),
            "validation_policy_execution": deepcopy(
                candidate_metrics.get("validation_policy_execution") or {}
            ),
            "threshold_configuration": threshold_configuration,
            "candidate_state": "complete",
            "champion_eligible": bool(
                candidate_metrics.get("champion_eligible", True)
            ),
            "created_at": created_at,
            "training_contract_hash": contract.get("contract_hash"),
        }
    )
    candidate["contract_hash"] = canonical_contract_hash(candidate)
    return candidate


def assert_training_contract_intact(contract: Mapping[str, Any]) -> None:
    payload = deepcopy(dict(contract))
    expected = str(payload.pop("contract_hash", "") or "")
    if not expected or expected != canonical_contract_hash(payload):
        raise CandidateContractError(
            "The frozen training contract is missing or has been modified."
        )
    missing_selection_lineage = [
        field
        for field in (
            "materialization_id",
            "training_population_id",
            "selection_partition_id",
            "holdout_population_id",
            "final_holdout_partition_id",
            "fold_definition_id",
            "final_holdout_status",
            "holdout_isolation_status",
            "selection_resampling_status",
        )
        if not str(contract.get(field) or "").strip()
    ]
    if missing_selection_lineage:
        raise CandidateContractError(
            "The frozen training contract lacks governed selection lineage: "
            + ", ".join(missing_selection_lineage)
        )
    if str(contract.get("final_holdout_status") or "") != "sealed":
        raise CandidateContractError(
            "The frozen training contract did not seal the final holdout."
        )
    if str(contract.get("holdout_isolation_status") or "") != "verified":
        raise CandidateContractError(
            "The frozen training contract did not verify final-holdout isolation."
        )
    if str(contract.get("selection_resampling_status") or "") != "not_applied":
        raise CandidateContractError(
            "The frozen training contract contains prohibited selection resampling."
        )


def classify_selection_integrity(record: Mapping[str, Any] | None) -> str:
    """Classify old or contaminated records without rewriting/deleting them."""
    if not isinstance(record, Mapping):
        return "legacy_unresolved"
    metric = record.get("selection_metric")
    if not isinstance(metric, Mapping):
        return "legacy_unresolved"
    source = str(metric.get("selection_metric_source") or "").casefold()
    if (
        "holdout" in source
        or str(record.get("selection_integrity_status") or "")
        == "invalid_final_holdout_ranking"
        or str(record.get("holdout_isolation_status") or "") not in {
            "",
            "verified",
        }
    ):
        return "invalid_final_holdout_ranking"
    if (
        source in {"out_of_fold", "cross_validation_mean"}
        and str(record.get("selection_integrity_status") or "") == "verified"
        and str(record.get("holdout_isolation_status") or "") == "verified"
        and str(metric.get("selection_partition_id") or "").strip()
        and str(metric.get("fold_definition_id") or "").strip()
    ):
        return "verified"
    return "legacy_unresolved"


def assert_candidate_contract_intact(contract: Mapping[str, Any]) -> None:
    payload = deepcopy(dict(contract))
    expected = str(payload.pop("contract_hash", "") or "")
    if not expected or expected != canonical_contract_hash(payload):
        raise CandidateContractError(
            "The frozen model-candidate contract is missing or has been modified."
        )
    required_text = (
        "project_id",
        "dataset_id",
        "dataset_version_id",
        "training_dataset_id",
        "training_dataset_version_id",
        "target_name",
        "target_contract_id",
        "predictor_manifest_id",
        "predictor_manifest_hash",
        "treatment_manifest_id",
        "treatment_manifest_hash",
        "feature_manifest_id",
        "feature_manifest_hash",
        "feature_manifest_version",
        "materialization_id",
        "validation_design_id",
        "validation_design_version",
        "split_id",
        "training_population_id",
        "selection_partition_id",
        "holdout_population_id",
        "final_holdout_partition_id",
        "fold_definition_id",
        "final_holdout_status",
        "holdout_isolation_status",
        "selection_integrity_status",
        "selection_resampling_status",
        "training_job_id",
        "training_run_id",
        "candidate_id",
        "algorithm_id",
        "algorithm_class",
        "algorithm_version",
        "ranking_metric",
        "created_by",
        "created_at",
        "training_contract_hash",
    )
    missing = [
        key for key in required_text if not str(contract.get(key) or "").strip()
    ]
    if missing:
        raise CandidateContractError(
            "The frozen model-candidate contract is incomplete: "
            + ", ".join(missing)
        )

    problem_type = str(contract.get("problem_type") or "").strip().casefold()
    if problem_type not in {"classification", "regression"}:
        raise CandidateContractError(
            "The frozen model-candidate contract has an invalid problem_type."
        )
    target_definition = contract.get("target_definition")
    if not isinstance(target_definition, Mapping):
        raise CandidateContractError(
            "The frozen model-candidate contract is missing its target_definition."
        )
    if (
        str(target_definition.get("target_name") or "").strip()
        != str(contract.get("target_name") or "").strip()
        or str(target_definition.get("problem_type") or "").strip().casefold()
        != problem_type
    ):
        raise CandidateContractError(
            "The frozen model-candidate target definition is contradictory."
        )
    if problem_type == "classification":
        if "positive_class" not in target_definition or "positive_class" not in contract:
            raise CandidateContractError(
                "The frozen classification candidate is missing its positive class."
            )
        if target_definition.get("positive_class") != contract.get("positive_class"):
            raise CandidateContractError(
                "The frozen classification candidate has conflicting positive classes."
            )
        if "negative_class" not in target_definition:
            raise CandidateContractError(
                "The frozen classification candidate is missing its negative class."
            )

    selection_metric = contract.get("selection_metric")
    if not isinstance(selection_metric, Mapping):
        raise CandidateContractError(
            "The frozen candidate is missing its governed selection_metric evidence."
        )
    if set(selection_metric.keys()) != set(SELECTION_METRIC_FIELDS):
        raise CandidateContractError(
            "The governed selection_metric does not have the exact required schema."
        )
    if str(selection_metric.get("selection_metric_source") or "") not in {
        "out_of_fold",
        "cross_validation_mean",
    }:
        raise CandidateContractError(
            "Candidate ranking evidence must come from governed training folds."
        )
    if "holdout" in str(selection_metric.get("selection_metric_source") or "").casefold():
        raise CandidateContractError(
            "Final-holdout evidence cannot be used for candidate ranking."
        )
    if (
        str(selection_metric.get("selection_metric_name") or "")
        != str(contract.get("ranking_metric") or "")
    ):
        raise CandidateContractError(
            "The candidate selection metric conflicts with the requested ranking metric."
        )
    for field in (
        "selection_metric_value",
        "mean",
        "standard_deviation",
    ):
        value = selection_metric.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise CandidateContractError(
                f"The governed selection_metric has an invalid {field}."
            )
    fold_count = selection_metric.get("fold_count")
    fold_values = selection_metric.get("fold_values")
    if (
        isinstance(fold_count, bool)
        or not isinstance(fold_count, int)
        or fold_count < 2
        or not isinstance(fold_values, list)
        or len(fold_values) != fold_count
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in fold_values
        )
    ):
        raise CandidateContractError(
            "The governed selection_metric has incomplete fold evidence."
        )
    expected_mean = sum(float(value) for value in fold_values) / fold_count
    expected_variance = sum(
        (float(value) - expected_mean) ** 2 for value in fold_values
    ) / fold_count
    if not math.isclose(
        float(selection_metric["mean"]), expected_mean, rel_tol=1e-9, abs_tol=1e-12
    ) or not math.isclose(
        float(selection_metric["standard_deviation"]),
        math.sqrt(expected_variance),
        rel_tol=1e-9,
        abs_tol=1e-12,
    ):
        raise CandidateContractError(
            "The governed selection_metric fold aggregates are inconsistent."
        )
    for selection_field, contract_field in (
        ("selection_partition_id", "selection_partition_id"),
        ("fold_definition_id", "fold_definition_id"),
    ):
        if str(selection_metric.get(selection_field) or "") != str(
            contract.get(contract_field) or ""
        ):
            raise CandidateContractError(
                f"The governed selection_metric conflicts with {contract_field}."
            )
    for field in (
        "out_of_fold_prediction_artifact_id",
        "threshold_source",
        "calibration_source",
        "created_at",
    ):
        if not str(selection_metric.get(field) or "").strip():
            raise CandidateContractError(
                f"The governed selection_metric is missing {field}."
            )
    if any(
        "holdout" in str(selection_metric.get(field) or "").casefold()
        for field in ("threshold_source", "calibration_source")
    ):
        raise CandidateContractError(
            "Threshold and calibration selection must not inspect the final holdout."
        )
    if str(contract.get("selection_integrity_status") or "") != "verified":
        raise CandidateContractError(
            "The candidate selection integrity status is not verified."
        )
    if str(contract.get("holdout_isolation_status") or "") != "verified":
        raise CandidateContractError(
            "The candidate final-holdout isolation status is not verified."
        )
    if str(contract.get("final_holdout_status") or "") != "sealed":
        raise CandidateContractError(
            "The candidate final holdout was not sealed during selection."
        )
    if str(contract.get("selection_resampling_status") or "") != "not_applied":
        raise CandidateContractError(
            "Candidate selection inherited prohibited population-level resampling."
        )
    threshold_configuration = contract.get("threshold_configuration")
    if (
        not isinstance(threshold_configuration, Mapping)
        or threshold_configuration.get("selection_threshold_tuned") is not False
        or str(threshold_configuration.get("threshold_source") or "")
        != str(selection_metric.get("threshold_source") or "")
        or not str(threshold_configuration.get("threshold_locked_at") or "").strip()
    ):
        raise CandidateContractError(
            "The candidate threshold provenance is incomplete or contradictory."
        )
    locked_threshold = threshold_configuration.get("locked_threshold")
    threshold_payload = {
        key: threshold_configuration.get(key)
        for key in (
            "locked_threshold",
            "threshold_source",
            "threshold_locked_at",
            "selection_threshold_tuned",
        )
    }
    if str(threshold_configuration.get("threshold_policy_hash") or "") != canonical_contract_hash(
        threshold_payload
    ):
        raise CandidateContractError(
            "The candidate threshold policy failed canonical hash verification."
        )
    if problem_type == "classification":
        if (
            isinstance(locked_threshold, bool)
            or not isinstance(locked_threshold, (int, float))
            or not math.isfinite(float(locked_threshold))
            or not 0.0 <= float(locked_threshold) <= 1.0
        ):
            raise CandidateContractError(
                "The classification candidate lacks a finite numeric locked threshold."
            )
    elif locked_threshold is not None:
        raise CandidateContractError(
            "A regression candidate cannot carry a classification threshold."
        )
    if problem_type == "classification":
        class_encoding = contract.get("class_encoding")
        if not isinstance(class_encoding, Mapping):
            raise CandidateContractError(
                "The frozen classification candidate lacks target-encoding provenance."
            )
        class_labels = class_encoding.get("class_labels")
        positive_index = class_encoding.get("positive_class_index")
        if (
            not isinstance(class_labels, list)
            or len(class_labels) != 2
            or isinstance(positive_index, bool)
            or not isinstance(positive_index, int)
            or positive_index not in {0, 1}
            or str(class_labels[positive_index])
            != str(class_encoding.get("positive_class_label") or "")
            or str(class_labels[positive_index])
            != str(contract.get("positive_class"))
            or str(class_encoding.get("fit_partition") or "") != "training_only"
        ):
            raise CandidateContractError(
                "The frozen classification candidate has invalid target-encoding provenance."
            )

    for key in ("hyperparameter_manifest", "calibration_configuration"):
        if not isinstance(contract.get(key), Mapping):
            raise CandidateContractError(
                f"The frozen model-candidate contract requires an object-valued {key}."
            )
    runtime_environment = contract.get("runtime_environment")
    if not isinstance(runtime_environment, Mapping):
        raise CandidateContractError(
            "The frozen model-candidate contract requires runtime_environment."
        )
    runtime_text = ("python_version", "platform", "code_version")
    missing_runtime = [
        key for key in runtime_text
        if not str(runtime_environment.get(key) or "").strip()
    ]
    if missing_runtime or not isinstance(runtime_environment.get("package_versions"), Mapping):
        raise CandidateContractError(
            "The frozen model-candidate runtime environment is incomplete."
        )
    worker_configuration = contract.get("worker_configuration")
    if not isinstance(worker_configuration, Mapping):
        raise CandidateContractError(
            "The frozen model-candidate contract requires worker_configuration."
        )
    for key in ("requested_workers", "honored_workers"):
        value = worker_configuration.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise CandidateContractError(
                f"The frozen model-candidate worker configuration has an invalid {key}."
            )
    if not str(worker_configuration.get("execution_mode") or "").strip():
        raise CandidateContractError(
            "The frozen model-candidate worker configuration is missing execution_mode."
        )
    random_seed = contract.get("random_seed")
    if isinstance(random_seed, bool) or not isinstance(random_seed, int):
        raise CandidateContractError(
            "The frozen model-candidate contract requires an integer random_seed."
        )
    if str(contract.get("candidate_state") or "").strip() != "complete":
        raise CandidateContractError(
            "The frozen model-candidate contract is not complete."
        )
    if not isinstance(contract.get("champion_eligible"), bool):
        raise CandidateContractError(
            "The frozen model-candidate contract requires a boolean champion_eligible flag."
        )

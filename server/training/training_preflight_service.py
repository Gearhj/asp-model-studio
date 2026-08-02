from __future__ import annotations

import math
import os
import time
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException

from ..core.dataset_store import DATASTORE
from ..datasets.dataset_identity import (
    assert_expected_active_identity,
    resolve_registered_version,
)
from ..persistence.service import get_persistence_service
from ..security.security_store import active_user
from .candidate_contract import canonical_contract_hash
from .trainer import MODEL_CATALOG
from .training_job_types import TrainingJobRequest


LARGE_RUN_FIT_THRESHOLD = max(
    1, int(os.getenv("ATLAS_LARGE_TRAINING_FIT_THRESHOLD", "160"))
)


def _package_for_algorithm(key: str, model: Any) -> str:
    if key.startswith("xgb"):
        return "xgboost"
    if key.startswith("lgbm"):
        return "lightgbm"
    if key.startswith("catboost"):
        return "catboost"
    if key in {"ebm", "ebm_reg"}:
        return "interpret"
    if key in {"deep_ffn", "cnn", "lstm"}:
        return "torch"
    if key == "tf_dnn":
        return "tensorflow"
    module_root = str(type(model).__module__ or "").split(".", 1)[0]
    return "scikit-learn" if module_root == "sklearn" else module_root


def _model_runtime_status(key: str) -> dict[str, Any]:
    spec = MODEL_CATALOG.get(key)
    if not spec:
        return {
            "available": False,
            "reason": "Model name is not recognized by the training backend.",
            "label": key,
            "algorithm_class": "unavailable",
            "algorithm_version": "unavailable",
        }
    try:
        model = spec.get("factory", lambda: None)()
    except Exception as exc:
        return {
            "available": False,
            "reason": (
                "Model dependency could not initialize "
                f"({type(exc).__name__})."
            ),
            "label": spec.get("label", key),
            "algorithm_class": "unavailable",
            "algorithm_version": "unavailable",
        }
    if model is None:
        return {
            "available": False,
            "reason": (
                f"{spec.get('label', key)} is unavailable in the current "
                "Python environment."
            ),
            "label": spec.get("label", key),
            "algorithm_class": "unavailable",
            "algorithm_version": "unavailable",
        }
    package = _package_for_algorithm(key, model)
    try:
        version = importlib_metadata.version(package) if package else "local"
    except importlib_metadata.PackageNotFoundError:
        version = "local"
    return {
        "available": True,
        "reason": "Available",
        "label": spec.get("label", key),
        "algorithm_class": (
            f"{type(model).__module__}.{type(model).__qualname__}"
        ),
        "algorithm_version": version,
    }


def _distribution(series: pd.Series, event_value: Any | None) -> dict[str, Any]:
    values = series.dropna()
    counts = values.value_counts()
    result: dict[str, Any] = {
        "rows": int(len(series)),
        "valid_rows": int(len(values)),
        "class_count": int(len(counts)),
        "classes": {str(key): int(value) for key, value in counts.items()},
        "events": None,
        "non_events": None,
        "event_rate": None,
        "event_value": event_value,
    }
    if len(counts) != 2:
        return result
    labels = list(counts.index)
    resolved = next((label for label in labels if str(label) == str(event_value)), None)
    if resolved is None:
        resolved = next((label for label in labels if str(label).strip() == "1"), labels[-1])
    events = int(counts[resolved])
    result.update({
        "event_value": resolved.item() if hasattr(resolved, "item") else resolved,
        "events": events,
        "non_events": int(len(values) - events),
        "event_rate": float(events / len(values)) if len(values) else None,
    })
    return result


def _model_available(key: str) -> tuple[bool, str]:
    status = _model_runtime_status(key)
    return bool(status["available"]), str(status["reason"])


def _finite_issues(frame: pd.DataFrame) -> tuple[list[str], list[str], list[str]]:
    all_missing: list[str] = []
    infinite: list[str] = []
    high_cardinality: list[str] = []
    for column in frame.columns:
        series = frame[column]
        if series.dropna().empty:
            all_missing.append(str(column))
        if pd.api.types.is_numeric_dtype(series):
            numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
            if np.isinf(numeric).any():
                infinite.append(str(column))
        elif int(series.nunique(dropna=True)) > 200:
            high_cardinality.append(str(column))
    return all_missing, infinite, high_cardinality


def _identity_error(
    record: dict[str, Any],
    identity: dict[str, Any],
    label: str,
) -> str:
    if not record:
        return (
            f"The {label} is missing. Recreate it for the exact active "
            "Dataset Library version."
        )
    expected = {
        "project_id": str(identity["project_id"]),
        "dataset_id": str(identity["dataset_id"]),
        "dataset_version_id": str(identity["dataset_version_id"]),
    }
    missing = [
        key
        for key in expected
        if not str(record.get(key) or "").strip()
    ]
    mismatched = [
        key
        for key, value in expected.items()
        if str(record.get(key) or "").strip()
        and str(record.get(key)) != value
    ]
    legacy = str(record.get("dataset_version") or "").strip()
    if legacy and legacy != expected["dataset_version_id"]:
        mismatched.append("dataset_version")
    if not missing and not mismatched:
        return ""
    return (
        f"The {label} is not bound to the exact active Dataset Library "
        "version. Recreate it before training."
    )


def _external_reference_error(reference: Any, role: str) -> str:
    """Require a persisted TEST/OOT pin to remain exact, readable, and allowed."""
    if reference in (None, {}):
        return ""
    if not isinstance(reference, dict):
        return f"The pinned {role} dataset reference is malformed."
    dataset_id = str(reference.get("dataset_id") or "").strip()
    dataset_version_id = str(reference.get("dataset_version_id") or "").strip()
    if not dataset_id or not dataset_version_id:
        return (
            f"The pinned {role} dataset reference does not contain an exact "
            "dataset_id and dataset_version_id."
        )
    for alias in ("version_id", "dataset_version"):
        compatibility_value = str(reference.get(alias) or "").strip()
        if compatibility_value and compatibility_value != dataset_version_id:
            return (
                f"The pinned {role} dataset reference contains conflicting "
                "version identifiers."
            )
    authenticated_user = active_user()
    if not authenticated_user:
        return (
            f"The pinned {role} dataset version cannot be revalidated because "
            "the authenticated user context is unavailable."
        )
    try:
        resolved = resolve_registered_version(
            dataset_id,
            dataset_version_id,
            user=authenticated_user,
        )
    except HTTPException as exc:
        return (
            f"The pinned {role} dataset version is stale, unavailable, or no "
            f"longer authorized: {exc.detail}"
        )
    if (
        str(resolved.get("dataset_id") or "") != dataset_id
        or str(resolved.get("dataset_version_id") or "") != dataset_version_id
    ):
        return f"The pinned {role} dataset version no longer resolves exactly."
    return ""


def training_preflight(request: TrainingJobRequest) -> dict[str, Any]:
    started = time.perf_counter()
    blocking: list[str] = []
    warnings: list[str] = []
    identity: dict[str, Any] = {}
    try:
        identity = assert_expected_active_identity(
            request.project_id,
            expected_dataset_id=request.dataset_id,
            expected_dataset_version_id=request.dataset_version_id,
            legacy_dataset_version=request.dataset_version,
            require_expected=True,
        )
    except HTTPException as exc:
        blocking.append(str(exc.detail))

    scoped_store = DATASTORE.current()
    # Candidate-selection preflight deliberately reads only the development
    # population. Final-holdout readiness comes from the sealed split contract,
    # never from inspecting final-holdout feature or target arrays.
    X_train = scoped_store.X_train
    y_train = scoped_store.y_train
    split_record = DATASTORE.meta.get("split_record") if isinstance(DATASTORE.meta.get("split_record"), dict) else {}
    manifest = DATASTORE.meta.get("feature_manifest") if isinstance(DATASTORE.meta.get("feature_manifest"), dict) else {}
    split_status = str(DATASTORE.meta.get("split_status") or "not_created")
    dataset_id = str(identity.get("dataset_id") or "")
    dataset_version_id = str(identity.get("dataset_version_id") or "")
    # Compatibility alias is always derived from the canonical version ID.
    dataset_version = dataset_version_id
    manifest_version = str(
        manifest.get("manifest_hash") or manifest.get("manifest_version") or ""
    )
    split_id = str(split_record.get("split_id") or "")
    training_population_id = str(split_record.get("training_population_id") or "")
    selection_partition_id = str(
        split_record.get("selection_partition_id") or training_population_id
    )
    final_holdout_partition_id = str(
        split_record.get("final_holdout_partition_id")
        or split_record.get("holdout_population_id")
        or ""
    )
    fold_definition_id = str(split_record.get("fold_definition_id") or "")
    final_holdout_status = str(
        split_record.get("final_holdout_status") or "legacy_unresolved"
    )
    holdout_isolation_status = str(
        split_record.get("holdout_isolation_status") or "legacy_unresolved"
    )
    validation_design = (
        split_record.get("validation_design")
        if isinstance(split_record.get("validation_design"), dict)
        else {}
    )
    validation_design_id = str(
        validation_design.get("validation_design_id") or ""
    )
    validation_design_version = str(
        validation_design.get("design_version") or ""
    )
    durable_holdout_exposure: dict[str, Any] | None = None
    durable_holdout_exposure_check = "not_checked"
    durable_partition_identity = {
        "project_id": str(identity.get("project_id") or request.project_id or ""),
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "validation_design_id": validation_design_id,
        "validation_design_version_id": validation_design_version,
        "split_id": split_id,
        "final_holdout_partition_id": final_holdout_partition_id,
    }
    if all(durable_partition_identity.values()):
        try:
            durable_holdout_exposure = (
                get_persistence_service()
                .holdout_governance.get_holdout_exposure_for_partition(
                    **durable_partition_identity
                )
            )
        except Exception as exc:
            durable_holdout_exposure_check = "verification_failed"
            blocking.append(
                "ATLAS could not verify the durable final-holdout exposure "
                "state, so candidate training is blocked: "
                f"{type(exc).__name__}."
            )
        else:
            durable_holdout_exposure_check = "verified"
            if durable_holdout_exposure is not None:
                exposure_status = str(
                    durable_holdout_exposure.get("final_holdout_status")
                    or "unknown"
                )
                blocking.append(
                    "The exact final-holdout partition already has a durable "
                    f"exposure record ({exposure_status}). It cannot be reused "
                    "for candidate ranking, feature selection, calibration, or "
                    "threshold tuning. Create and approve a new Validation Design."
                )
    cv_design = (
        split_record.get("cv_design")
        if isinstance(split_record.get("cv_design"), dict)
        else {}
    )
    cv_execution_splits = (
        split_record.get("cv_execution_splits")
        if isinstance(split_record.get("cv_execution_splits"), list)
        else []
    )
    target = str(DATASTORE.target or "")

    external_reference_errors = [
        error
        for reference, role in (
            (split_record.get("test_reference"), "TEST"),
            (split_record.get("oot_reference"), "OOT"),
        )
        if (
            error := _external_reference_error(
                reference,
                role,
            )
        )
    ]
    if external_reference_errors:
        split_status = "stale"
        blocking.extend(
            error + " Return to Balance & Split and rebuild Validation Design."
            for error in external_reference_errors
        )

    if split_status != "current" or X_train is None or y_train is None:
        blocking.append("A current governed validation split is required. Return to Balance & Split and create the split explicitly.")
    if not training_population_id or not selection_partition_id:
        blocking.append(
            "The governed training population identity is missing. Return to Balance & Split."
        )
    if (
        not final_holdout_partition_id
        or final_holdout_status != "sealed"
        or holdout_isolation_status != "verified"
    ):
        blocking.append(
            "The final holdout is not sealed under an exact partition identity. Return to Balance & Split."
        )
    if identity:
        for record, label in (
            (manifest, "feature manifest"),
            (split_record, "validation split"),
            (validation_design, "Validation Design"),
        ):
            error = _identity_error(record, identity, label)
            if error:
                blocking.append(error)
        development_dataset = (
            validation_design.get("development_dataset")
            if isinstance(
                validation_design.get("development_dataset"), dict
            )
            else {}
        )
        development_version = str(
            development_dataset.get("dataset_version_id")
            or development_dataset.get("version_id")
            or ""
        )
        if (
            str(development_dataset.get("dataset_id") or "")
            != str(identity["dataset_id"])
            or development_version != str(identity["dataset_version_id"])
        ):
            blocking.append(
                "The Validation Design development population is not pinned "
                "to the exact active Dataset Library version."
            )
    if not manifest_version:
        blocking.append(
            "A versioned feature manifest is required before training."
        )
    if not split_id:
        blocking.append(
            "A versioned validation split is required before training."
        )
    if not validation_design_id or not validation_design_version:
        blocking.append(
            "An approved, versioned Validation Design is required before training."
        )
    split_manifest_version = str(
        split_record.get("feature_manifest_version") or ""
    )
    if not split_manifest_version or split_manifest_version != manifest_version:
        blocking.append(
            "The validation split is not bound to the current feature manifest. "
            "Return to Balance & Split."
        )
    design_manifest_version = str(
        validation_design.get("feature_manifest_hash") or ""
    )
    if (
        not design_manifest_version
        or design_manifest_version != manifest_version
    ):
        blocking.append(
            "The Validation Design is not bound to the current feature manifest. "
            "Return to Balance & Split."
        )
    if request.feature_manifest_version and request.feature_manifest_version != manifest_version:
        blocking.append("Feature manifest version mismatch. Refresh Model Training after saving Final Predictor Review.")
    if request.split_id and request.split_id != split_id:
        blocking.append("Split ID mismatch. The approved validation split changed.")
    if validation_design and validation_design.get("status") != "approved":
        blocking.append(
            "The Validation Design is not approved. Return to Balance & Split."
        )
    completion_gates = split_record.get("completion_gates") or {}
    failed_validation_gates = [
        str(name) for name, passed in completion_gates.items() if passed is not True
    ]
    if validation_design and failed_validation_gates:
        blocking.append(
            "Validation Design completion gates are no longer satisfied: "
            + ", ".join(failed_validation_gates)
        )
    if request.validation_design_id and request.validation_design_id != validation_design_id:
        blocking.append(
            "Validation Design ID mismatch. Refresh Model Training from the approved handoff."
        )
    if (
        request.validation_design_version
        and request.validation_design_version != validation_design_version
    ):
        blocking.append(
            "Validation Design version mismatch. The approved validation contract changed."
        )
    if request.target and target and request.target != target:
        blocking.append(f"Target mismatch: request '{request.target}', active '{target}'.")
    if not target:
        blocking.append("No active target is defined.")

    manifest_selected = [
        str(row.get("feature_name"))
        for row in manifest.get("features", [])
        if isinstance(row, dict) and row.get("selected") and row.get("eligibility_status") == "eligible"
    ]
    engineered = [
        str(row.get("feature_name"))
        for row in manifest.get("features", [])
        if isinstance(row, dict) and row.get("selected") and row.get("eligibility_status") == "eligible" and row.get("origin") != "original"
    ]
    if validation_design and engineered and (
        manifest.get("validation_status") != "passed"
        or manifest.get("materialization_status") != "current"
        or manifest.get("materialized_manifest_hash") != manifest_version
        or manifest.get("confirmation_status") != "confirmed"
        or manifest.get("confirmed_manifest_hash") != manifest_version
    ):
        blocking.append(
            "The engineered feature contract is not validated, materialized, "
            "and confirmed current. Return to Feature Engineering."
        )
    originals = [name for name in manifest_selected if name not in engineered]
    trained_columns = [str(column) for column in X_train.columns] if X_train is not None else []
    missing_features = [name for name in manifest_selected if name not in trained_columns]
    unexpected_features = [name for name in trained_columns if manifest_selected and name not in manifest_selected]
    if not manifest_selected:
        blocking.append("The feature manifest has no selected predictors.")
    if missing_features:
        blocking.append("Selected features are missing from the training split: " + ", ".join(missing_features))
    if unexpected_features:
        blocking.append("The training split contains predictors outside the approved manifest: " + ", ".join(unexpected_features))
    if X_train is not None and X_train.shape[1] == 0:
        blocking.append("The training feature matrix is empty.")

    train_distribution = _distribution(y_train, request.event_value) if y_train is not None else {}
    governed_distributions = (
        split_record.get("distributions")
        if isinstance(split_record.get("distributions"), dict)
        else {}
    )
    # Presentation-only final-holdout aggregates were captured at split time.
    # They are not recomputed or inspected during candidate selection.
    test_distribution = (
        governed_distributions.get("holdout_untouched")
        if isinstance(governed_distributions.get("holdout_untouched"), dict)
        else {}
    )
    problem_type = request.problem_type or ("classification" if train_distribution.get("class_count", 0) <= 20 else "regression")
    if y_train is not None and y_train.isna().any():
        blocking.append("The training target contains missing values.")
    if problem_type == "classification":
        if train_distribution.get("class_count") != 2:
            blocking.append("The training target does not contain exactly two classes.")
        if not train_distribution.get("events"):
            blocking.append("The training split contains no positive-class events.")
        event_rate = train_distribution.get("event_rate")
        if isinstance(event_rate, float) and event_rate < 0.01:
            warnings.append("Rare-event target detected. Use PR-AUC, recall, lift, and calibration evidence rather than accuracy alone.")

    all_missing: list[str] = []
    infinite: list[str] = []
    high_cardinality: list[str] = []
    if X_train is not None:
        all_missing, infinite, high_cardinality = _finite_issues(X_train)
    if all_missing:
        blocking.append("All-missing training predictors cannot be fitted: " + ", ".join(all_missing))
    if infinite:
        blocking.append("Infinite numeric values must be treated before training: " + ", ".join(infinite))
    if high_cardinality:
        warnings.append("High-cardinality categorical predictors may expand memory use: " + ", ".join(high_cardinality[:8]))
    missing_value_columns = [str(column) for column in X_train.columns if X_train[column].isna().any()] if X_train is not None else []
    if missing_value_columns:
        warnings.append(f"Training-only imputation will be fitted for {len(missing_value_columns)} predictor(s) with missing values.")

    min_class_count = 0
    if y_train is not None and problem_type == "classification" and len(y_train.value_counts()) >= 2:
        min_class_count = int(y_train.value_counts().min())
    design_fold_method = str(cv_design.get("method") or "none")
    design_folds = int(cv_design.get("fold_count") or 0)
    cv_owned_by_design = bool(
        validation_design and design_fold_method != "none" and design_folds >= 2
    )
    execution_fold_count = (
        len(cv_execution_splits)
        if cv_owned_by_design and cv_execution_splits
        else design_folds
        if cv_owned_by_design
        else 0
    )
    if cv_owned_by_design and request.k_folds != design_folds:
        blocking.append(
            f"Cross-validation is locked by Validation Design at {design_folds} folds; "
            f"the training request attempted {request.k_folds}."
        )
    if not cv_owned_by_design:
        blocking.append(
            "Candidate selection requires an approved governed cross-validation design in Balance & Split."
        )
    if cv_owned_by_design and not fold_definition_id:
        blocking.append(
            "The approved Validation Design lacks an exact fold_definition_id. Return to Balance & Split and rebuild it."
        )
    if request.grid_search and validation_design and not cv_owned_by_design:
        blocking.append(
            "Hyperparameter search requires an approved cross-validation design in Balance & Split."
        )
    if cv_owned_by_design and not cv_execution_splits:
        blocking.append(
            "The approved Validation Design does not contain executable fold "
            "bindings. Return to Balance & Split and rebuild the design."
        )
    if (
        cv_owned_by_design
        and design_fold_method == "nested_cv"
        and request.grid_search
    ):
        blocking.append(
            "Nested-CV outer-loop execution is not available in the current "
            "trainer. Select a non-nested governed fold architecture or disable "
            "hyperparameter search."
        )
    invalid_execution_folds: list[int] = []
    if cv_owned_by_design and X_train is not None:
        for index, fold in enumerate(cv_execution_splits, start=1):
            if not isinstance(fold, dict):
                invalid_execution_folds.append(index)
                continue
            train_positions = fold.get("train_positions")
            validation_positions = fold.get("validation_positions")
            if (
                not isinstance(train_positions, list)
                or not isinstance(validation_positions, list)
                or not train_positions
                or not validation_positions
                or min([*train_positions, *validation_positions]) < 0
                or max([*train_positions, *validation_positions])
                >= len(X_train)
                or set(train_positions).intersection(validation_positions)
            ):
                invalid_execution_folds.append(index)
                continue
            if problem_type == "classification":
                training_target = y_train.iloc[train_positions]
                validation_target = y_train.iloc[validation_positions]
                if (
                    int(training_target.nunique(dropna=True)) != 2
                    or int(validation_target.nunique(dropna=True)) != 2
                ):
                    invalid_execution_folds.append(index)
        if invalid_execution_folds:
            blocking.append(
                "Executable Validation Design folds are invalid or lack both "
                "target classes: "
                + ", ".join(str(value) for value in invalid_execution_folds)
                + ". Return to Balance & Split."
            )
    requested_folds = design_folds if cv_owned_by_design else request.k_folds
    effective_folds = (
        execution_fold_count
        if cv_owned_by_design and execution_fold_count
        else min(max(2, requested_folds), max(2, min_class_count))
        if problem_type == "classification"
        else min(
            max(2, requested_folds),
            max(2, len(y_train) if y_train is not None else 2),
        )
    )
    cv_compatible = problem_type == "regression" or min_class_count >= 2
    if request.grid_search and not cv_compatible:
        blocking.append("Grid search requires at least two observations in every target class.")
    if (
        problem_type == "classification"
        and cv_owned_by_design
        and min_class_count < requested_folds
    ):
        blocking.append(
            f"The approved {requested_folds}-fold design is not event-count compatible "
            f"with the current training population; return to Balance & Split."
        )
    elif request.grid_search and effective_folds < requested_folds:
        blocking.append(
            f"The requested {requested_folds}-fold search is not event-count compatible "
            f"with the current training population; return to Balance & Split."
        )

    library_status: dict[str, Any] = {}
    compatibility: dict[str, Any] = {}
    calibration_compatibility: dict[str, Any] = {}
    for key, spec in MODEL_CATALOG.items():
        runtime_status = _model_runtime_status(key)
        available = bool(runtime_status["available"])
        reason = str(runtime_status["reason"])
        library_status[key] = runtime_status
    selected_algorithm_ids = list(dict.fromkeys(str(key) for key in request.models))
    if not selected_algorithm_ids:
        blocking.append("Select at least one compatible model before validation.")
    for key in selected_algorithm_ids:
        spec = MODEL_CATALOG.get(key)
        available = bool(library_status.get(key, {}).get("available"))
        task_match = bool(spec and (spec.get("task") == problem_type or (spec.get("kind") == "anomaly" and problem_type == "classification")))
        compatible = available and task_match
        reason = library_status.get(key, {}).get("reason") if not available else "Compatible" if task_match else f"Model does not support {problem_type}."
        compatibility[key] = {"compatible": compatible, "reason": reason}
        if not compatible:
            blocking.append(f"{spec.get('label', key) if spec else key}: {reason}")
        calibration_allowed = bool(problem_type == "classification" and spec and spec.get("kind") != "anomaly" and min_class_count >= 2)
        calibration_reason = "Compatible" if calibration_allowed else "Calibration requires binary classification with at least two observations per class and a supervised probability model."
        calibration_compatibility[key] = {"compatible": calibration_allowed, "reason": calibration_reason}
    selected_algorithm_versions = {
        key: str(
            library_status.get(key, {}).get("algorithm_version")
            or "unavailable"
        )
        for key in selected_algorithm_ids
    }
    stale_runtime_versions = [
        key
        for key, expected in request.selected_algorithm_versions.items()
        if key in selected_algorithm_versions
        and str(expected or "") != selected_algorithm_versions[key]
    ]
    if stale_runtime_versions:
        blocking.append(
            "The selected algorithm runtime changed after preflight: "
            + ", ".join(stale_runtime_versions)
            + ". Run preflight again."
        )
    if request.calibrate:
        incompatible_calibration = [key for key in request.models if not calibration_compatibility.get(key, {}).get("compatible")]
        if incompatible_calibration:
            blocking.append(
                "Calibration is incompatible with selected models: "
                + ", ".join(incompatible_calibration)
                + ". Disable calibration or change the portfolio."
            )

    rows = int(len(X_train)) if X_train is not None else 0
    columns = int(X_train.shape[1]) if X_train is not None else 0
    estimated_bytes = rows * max(columns, 1) * 8 * 4
    estimated_memory_mb = round(estimated_bytes / (1024 * 1024), 1)
    cpu_cap = max(1, min(4, os.cpu_count() or 1))
    memory_cap = 1 if estimated_memory_mb > 2_000 else 2 if estimated_memory_mb > 750 else cpu_cap
    recommended_parallel = max(1, min(len(selected_algorithm_ids) or 1, cpu_cap, memory_cap))
    balancing_policy = (
        split_record.get("balancing_policy")
        if isinstance(split_record.get("balancing_policy"), dict)
        else {}
    )
    selection_resampling_status = str(
        balancing_policy.get("selection_resampling_status") or "not_applied"
    )
    if selection_resampling_status != "not_applied":
        blocking.append(
            "Candidate-selection folds must not inherit population-level label resampling. Rebuild Validation Design without resampling."
        )
    if request.use_pca:
        blocking.append(
            "PCA is not implemented by the governed training pipeline and cannot be enabled."
        )
    if str(request.grid_search_level).lower() not in {
        "quick",
        "balanced",
        "thorough",
    }:
        blocking.append(
            "Grid-search level must be quick, balanced, or thorough."
        )

    tuning_candidates = (
        {"quick": 4, "balanced": 8, "thorough": 12}.get(
            str(request.grid_search_level).lower(), 4
        )
        if request.grid_search
        else 1
    )
    estimated_fits = (
        len(selected_algorithm_ids)
        * max(1, effective_folds)
        * tuning_candidates
    )
    calibration_supported_algorithm_ids = [
        key
        for key in selected_algorithm_ids
        if calibration_compatibility.get(key, {}).get("compatible")
    ]
    calibration_fits = (
        len(calibration_supported_algorithm_ids) * max(1, effective_folds)
        if request.calibrate
        else 0
    )
    estimated_fits += calibration_fits
    large_run_required = estimated_fits >= LARGE_RUN_FIT_THRESHOLD
    large_run_acknowledged = bool(request.large_job_confirmed)

    ready = not blocking
    unique_blocking = list(dict.fromkeys(blocking))
    unique_warnings = list(dict.fromkeys(warnings))

    def readiness_check(
        check_id: str,
        passed: bool,
        reason: str,
        *,
        warning: bool = False,
    ) -> dict[str, Any]:
        return {
            "check_id": check_id,
            "state": "warning" if passed and warning else "passed" if passed else "failed",
            "passed": bool(passed),
            "reason": reason,
        }

    identity_ready = bool(identity and dataset_id and dataset_version_id)
    feature_ready = bool(
        manifest_version
        and manifest_selected
        and not missing_features
        and not unexpected_features
    )
    validation_ready = bool(
        split_status == "current"
        and split_id
        and validation_design_id
        and validation_design_version
        and validation_design.get("status") == "approved"
        and cv_owned_by_design
        and cv_execution_splits
        and not invalid_execution_folds
    )
    target_ready = bool(target and y_train is not None)
    dependency_ready = bool(
        selected_algorithm_ids
        and all(
            compatibility.get(key, {}).get("compatible")
            for key in selected_algorithm_ids
        )
    )
    final_holdout_sealed = bool(
        final_holdout_partition_id
        and final_holdout_status == "sealed"
        and holdout_isolation_status == "verified"
        and durable_holdout_exposure is None
        and durable_holdout_exposure_check != "verification_failed"
    )
    checks = [
        readiness_check(
            "canonical_identity",
            identity_ready,
            "Exact canonical Dataset Library identity verified."
            if identity_ready
            else "The exact project, dataset, and dataset-version identity is unavailable or stale.",
        ),
        readiness_check(
            "target_contract",
            target_ready,
            f"Target {target} is available in the development population."
            if target_ready
            else "The governed target contract is missing.",
        ),
        readiness_check(
            "feature_contract",
            feature_ready,
            f"Feature manifest {manifest_version} provides {len(manifest_selected)} selected predictors."
            if feature_ready
            else "The feature manifest is missing, stale, or inconsistent with the development matrix.",
        ),
        readiness_check(
            "validation_design",
            validation_ready,
            f"Validation Design {validation_design_id} and split {split_id} are current."
            if validation_ready
            else "An approved current Validation Design with executable folds is required.",
        ),
        readiness_check(
            "dependencies",
            dependency_ready,
            "Every selected algorithm dependency and task contract is compatible."
            if dependency_ready
            else "One or more selected algorithms are unavailable or incompatible.",
        ),
        readiness_check(
            "data_type_compatibility",
            not all_missing and not infinite,
            "Development predictors contain no all-missing or infinite columns."
            if not all_missing and not infinite
            else "Development predictors contain unsupported all-missing or infinite values.",
        ),
        readiness_check(
            "encoding_requirements",
            True,
            "Categorical encoding is fitted inside governed development folds."
            + (
                f" {len(high_cardinality)} high-cardinality column(s) require review."
                if high_cardinality
                else ""
            ),
            warning=bool(high_cardinality),
        ),
        readiness_check(
            "scaling_requirements",
            True,
            "Algorithm-specific scaling is fitted inside governed development folds.",
        ),
        readiness_check(
            "calibration_compatibility",
            not request.calibrate
            or all(
                calibration_compatibility.get(key, {}).get("compatible")
                for key in selected_algorithm_ids
            ),
            "Calibration is disabled or compatible with every selected model."
            if not request.calibrate
            or all(
                calibration_compatibility.get(key, {}).get("compatible")
                for key in selected_algorithm_ids
            )
            else "Calibration is unsupported for at least one selected model.",
        ),
        readiness_check(
            "event_count_compatibility",
            cv_compatible
            and (
                problem_type != "classification"
                or min_class_count >= requested_folds
            ),
            "Development-population event counts support the approved folds."
            if cv_compatible
            and (
                problem_type != "classification"
                or min_class_count >= requested_folds
            )
            else "Development-population event counts do not support the approved folds.",
        ),
        readiness_check(
            "cv_compatibility",
            validation_ready,
            "Candidate selection is restricted to exact governed development folds."
            if validation_ready
            else "Executable governed cross-validation folds are unavailable.",
        ),
        readiness_check(
            "memory_and_workers",
            True,
            (
                f"Estimated memory is {estimated_memory_mb} MB; "
                f"{recommended_parallel} worker(s) will be honored."
            ),
            warning=request.max_parallel > max(1, recommended_parallel),
        ),
        readiness_check(
            "final_holdout_sealed",
            final_holdout_sealed,
            "The final holdout remains sealed; preflight read development data only."
            if final_holdout_sealed
            else "The exact final holdout is not sealed and verified for isolation.",
        ),
        readiness_check(
            "selection_resampling",
            selection_resampling_status == "not_applied",
            "No population-level label resampling contaminates candidate selection."
            if selection_resampling_status == "not_applied"
            else "Candidate-selection folds contain prohibited population-level resampling.",
        ),
    ]
    # If a specialized check has not represented a newly added fail-closed
    # condition, the contract-consistency check still makes the single result
    # internally non-contradictory and exposes every authoritative reason.
    checks.append(
        readiness_check(
            "contract_consistency",
            ready,
            "Every governed preflight condition passed."
            if ready
            else " | ".join(unique_blocking),
        )
    )

    manifest_id = str(
        manifest.get("manifest_id")
        or manifest.get("manifest_version")
        or manifest_version
    )
    target_contract = {
        "target": target,
        "problem_type": problem_type,
        "event_value": train_distribution.get(
            "event_value", request.event_value
        ),
        "non_event_value": request.non_event_value,
        "development_rows": rows,
        "development_events": train_distribution.get("events"),
        "status": "current" if target_ready else "missing",
    }
    portfolio = (
        scoped_store.meta.get("training_model_portfolio")
        if isinstance(
            scoped_store.meta.get("training_model_portfolio"), dict
        )
        else {}
    )
    selection_revision = int(portfolio.get("selection_revision") or 0)
    state_payload = {
        "project_id": request.project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "data_revision": int(scoped_store.data_revision),
        "feature_manifest_id": manifest_id,
        "feature_manifest_version": manifest_version,
        "validation_design_id": validation_design_id,
        "validation_design_version": validation_design_version,
        "split_id": split_id,
        "target_contract": target_contract,
        "selected_algorithm_ids": selected_algorithm_ids,
        "selected_algorithm_versions": selected_algorithm_versions,
        "k_folds": request.k_folds,
        "grid_search": request.grid_search,
        "grid_search_level": request.grid_search_level,
        "calibrate": request.calibrate,
        "use_pca": request.use_pca,
        "max_parallel": request.max_parallel,
        "candidate_strategy": request.candidate_strategy,
        "primary_metric": request.primary_metric,
        "final_holdout_partition_id": final_holdout_partition_id,
        "final_holdout_status": final_holdout_status,
        "holdout_isolation_status": holdout_isolation_status,
    }
    state_hash = canonical_contract_hash(state_payload)
    preflight_id = f"training-preflight-{state_hash[:20]}"
    created_at = datetime.now(timezone.utc).isoformat()
    result = {
        "ok": True,
        "ready": ready,
        "readiness_status": "ready" if ready else "blocked",
        "blocking_errors": unique_blocking,
        "warnings": unique_warnings,
        "checks": checks,
        "preflight_id": preflight_id,
        "state_hash": state_hash,
        "revision": int(scoped_store.data_revision) * 1_000_000
        + selection_revision,
        "canonical_data_revision": int(scoped_store.data_revision),
        "selection_revision": selection_revision,
        "created_at": created_at,
        "stale": False,
        "stale_reason": None,
        "project_id": request.project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "dataset_version": dataset_version,
        "target": target,
        "target_contract": target_contract,
        "event_value": train_distribution.get("event_value", request.event_value),
        "non_event_value": request.non_event_value,
        "problem_type": problem_type,
        "train_rows": rows,
        "test_rows": int(test_distribution.get("rows") or split_record.get("n_test") or 0),
        "train_events": train_distribution.get("events"),
        "test_events": test_distribution.get("events"),
        "train_event_rate": train_distribution.get("event_rate"),
        "test_event_rate": test_distribution.get("event_rate"),
        "selected_features": manifest_selected,
        "selected_original_features": originals,
        "engineered_features": engineered,
        "missing_features": missing_features,
        "unexpected_features": unexpected_features,
        "feature_manifest_version": manifest_version,
        "feature_manifest_id": manifest_id,
        "split_id": split_id,
        "training_population_id": training_population_id,
        "selection_partition_id": selection_partition_id,
        "holdout_population_id": final_holdout_partition_id,
        "final_holdout_partition_id": final_holdout_partition_id,
        "fold_definition_id": fold_definition_id,
        "final_holdout_status": final_holdout_status,
        "holdout_isolation_status": holdout_isolation_status,
        "durable_holdout_exposure_check": durable_holdout_exposure_check,
        "durable_holdout_exposure_status": (
            durable_holdout_exposure.get("final_holdout_status")
            if durable_holdout_exposure is not None
            else None
        ),
        "selection_resampling_status": selection_resampling_status,
        "split_status": split_status,
        "validation_design": validation_design,
        "validation_design_id": validation_design_id,
        "validation_design_version": validation_design_version,
        "cv_design": cv_design,
        "fold_architecture": split_record.get("fold_architecture") or {},
        "evaluation_population_role": split_record.get(
            "evaluation_population_role"
        ),
        "completion_gates": split_record.get("completion_gates") or {},
        "validation_risks": split_record.get("validation_risks") or [],
        "test_reference": split_record.get("test_reference"),
        "oot_reference": split_record.get("oot_reference"),
        "split_configuration": split_record.get("config") or {},
        "balancing_configuration": balancing_policy
        or {
            "method": (split_record.get("config") or {}).get(
                "balance_method", "none"
            )
        },
        "optional_library_status": library_status,
        "selected_algorithm_ids": selected_algorithm_ids,
        "selected_algorithm_versions": selected_algorithm_versions,
        "selected_algorithm_details": {
            key: {
                **library_status.get(key, {}),
                "compatible": bool(
                    compatibility.get(key, {}).get("compatible")
                ),
                "compatibility_reason": compatibility.get(key, {}).get(
                    "reason"
                ),
                "champion_eligible": bool(
                    MODEL_CATALOG.get(key, {}).get(
                        "champion_eligible",
                        MODEL_CATALOG.get(key, {}).get("kind") != "anomaly",
                    )
                ),
                "candidate_role": (
                    "diagnostic_only"
                    if MODEL_CATALOG.get(key, {}).get("kind") == "anomaly"
                    else "supervised_candidate"
                ),
            }
            for key in selected_algorithm_ids
        },
        "dependency_status": {
            "state": "ready" if dependency_ready else "blocked",
            "algorithms": {
                key: {
                    "available": bool(
                        library_status.get(key, {}).get("available")
                    ),
                    "compatible": bool(
                        compatibility.get(key, {}).get("compatible")
                    ),
                    "reason": compatibility.get(key, {}).get("reason"),
                }
                for key in selected_algorithm_ids
            },
        },
        "model_compatibility": compatibility,
        "calibration_compatibility": calibration_compatibility,
        "data_type_compatibility": {
            "compatible": not all_missing and not infinite,
            "all_missing_columns": all_missing,
            "infinite_columns": infinite,
            "high_cardinality_columns": high_cardinality,
        },
        "encoding_requirements": {
            "fit_scope": "development_fold_only",
            "required_columns": [
                str(column)
                for column in (
                    X_train.columns if X_train is not None else []
                )
                if not pd.api.types.is_numeric_dtype(X_train[column])
            ],
        },
        "scaling_requirements": {
            "fit_scope": "development_fold_only",
            "policy": "algorithm_specific_pipeline",
        },
        "event_count_compatibility": {
            "compatible": cv_compatible
            and (
                problem_type != "classification"
                or min_class_count >= requested_folds
            ),
            "minimum_class_count": min_class_count
            if problem_type == "classification"
            else None,
            "required_folds": requested_folds,
        },
        "cross_validation_compatibility": {
            "compatible": cv_compatible,
            "owned_by_validation_design": cv_owned_by_design,
            "method": design_fold_method,
            "requested_folds": requested_folds,
            "effective_folds": effective_folds,
            "execution_fold_count": execution_fold_count,
            "exact_fold_bindings": bool(cv_execution_splits),
            "minimum_class_count": min_class_count if problem_type == "classification" else None,
            "read_only": bool(validation_design),
        },
        "missing_value_columns": missing_value_columns,
        "infinite_value_columns": infinite,
        "estimated_memory_mb": estimated_memory_mb,
        "memory_estimate": {
            "estimated_mb": estimated_memory_mb,
            "basis": "development_population_only",
        },
        "recommended_parallelism": recommended_parallel,
        "worker_limit": recommended_parallel,
        "base_fit_count": estimated_fits - calibration_fits,
        "calibration_fit_count": calibration_fits,
        "calibration_supported_algorithm_ids": (
            calibration_supported_algorithm_ids if request.calibrate else []
        ),
        "estimated_fits": estimated_fits,
        "estimated_runtime_seconds": round(
            estimated_fits
            * max(rows, 1)
            * max(columns, 1)
            / 5_000_000,
            1,
        ),
        "large_run_status": (
            "acknowledged"
            if large_run_required and large_run_acknowledged
            else "acknowledgement_required"
            if large_run_required and ready
            else "not_large"
            if not large_run_required
            else "validation_blocked"
        ),
        "large_run": {
            "required": large_run_required,
            "threshold_fits": LARGE_RUN_FIT_THRESHOLD,
            "estimated_fits": estimated_fits,
            "acknowledged": large_run_acknowledged,
            "acknowledgement_required": bool(
                ready and large_run_required and not large_run_acknowledged
            ),
        },
        "final_holdout_sealed": final_holdout_sealed,
        "final_holdout_access": "contract_metadata_only",
        "selection_evidence_source": "development_population_cross_validation",
        "backend_status": "ready" if ready else "blocked",
        "worker_status": "ready" if dependency_ready else "blocked",
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    return result

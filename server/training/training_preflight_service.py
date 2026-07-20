from __future__ import annotations

import math
import os
import time
from typing import Any

import numpy as np
import pandas as pd

from ..core.dataset_store import DATASTORE
from .trainer import MODEL_CATALOG
from .training_job_types import TrainingJobRequest


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
    spec = MODEL_CATALOG.get(key)
    if not spec:
        return False, "Model name is not recognized by the training backend."
    try:
        model = spec.get("factory", lambda: None)()
    except Exception as exc:
        return False, f"Model dependency could not initialize: {exc}"
    if model is None:
        return False, f"{spec.get('label', key)} is unavailable in the current Python environment."
    return True, "Available"


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


def training_preflight(request: TrainingJobRequest) -> dict[str, Any]:
    started = time.perf_counter()
    blocking: list[str] = []
    warnings: list[str] = []
    X_train, X_test, y_train, y_test = DATASTORE.get_splits()
    split_record = DATASTORE.meta.get("split_record") if isinstance(DATASTORE.meta.get("split_record"), dict) else {}
    manifest = DATASTORE.meta.get("feature_manifest") if isinstance(DATASTORE.meta.get("feature_manifest"), dict) else {}
    split_status = str(DATASTORE.meta.get("split_status") or "not_created")
    dataset_version = str(DATASTORE.meta.get("dataset_version") or manifest.get("dataset_version") or "in-memory")
    source = DATASTORE.meta.get("source") if isinstance(DATASTORE.meta.get("source"), dict) else {}
    dataset_id = str(source.get("datasetId") or source.get("dataset_id") or DATASTORE.meta.get("dataset_id") or request.dataset_id or "")
    manifest_version = str(manifest.get("manifest_version") or "")
    split_id = str(split_record.get("split_id") or "")
    target = str(DATASTORE.target or "")

    if split_status != "current" or any(part is None for part in (X_train, X_test, y_train, y_test)):
        blocking.append("A current governed validation split is required. Return to Balance & Split and create the split explicitly.")
    if request.dataset_version and request.dataset_version != dataset_version:
        blocking.append(f"Dataset version mismatch: request {request.dataset_version}, active {dataset_version}.")
    if request.dataset_id and dataset_id and request.dataset_id != dataset_id:
        blocking.append(f"Dataset ID mismatch: request {request.dataset_id}, active {dataset_id}.")
    if request.feature_manifest_version and request.feature_manifest_version != manifest_version:
        blocking.append("Feature manifest version mismatch. Refresh Model Training after saving Final Predictor Review.")
    if request.split_id and request.split_id != split_id:
        blocking.append("Split ID mismatch. The approved validation split changed.")
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
    test_distribution = _distribution(y_test, request.event_value) if y_test is not None else {}
    problem_type = request.problem_type or ("classification" if train_distribution.get("class_count", 0) <= 20 else "regression")
    if y_train is not None and y_train.isna().any():
        blocking.append("The training target contains missing values.")
    if y_test is not None and y_test.isna().any():
        blocking.append("The holdout target contains missing values.")
    if problem_type == "classification":
        if train_distribution.get("class_count") != 2:
            blocking.append("The training target does not contain exactly two classes.")
        if test_distribution.get("class_count") != 2:
            blocking.append("The holdout target does not contain exactly two classes.")
        if not train_distribution.get("events"):
            blocking.append("The training split contains no positive-class events.")
        if not test_distribution.get("events"):
            blocking.append("The holdout split contains no positive-class events.")
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
    effective_folds = min(max(2, request.k_folds), max(2, min_class_count)) if problem_type == "classification" else min(max(2, request.k_folds), max(2, len(y_train) if y_train is not None else 2))
    cv_compatible = problem_type == "regression" or min_class_count >= 2
    if request.grid_search and not cv_compatible:
        blocking.append("Grid search requires at least two observations in every target class.")
    elif request.grid_search and effective_folds < request.k_folds:
        warnings.append(f"Cross-validation folds will be reduced from {request.k_folds} to {effective_folds} for event-count safety.")

    library_status: dict[str, Any] = {}
    compatibility: dict[str, Any] = {}
    calibration_compatibility: dict[str, Any] = {}
    for key, spec in MODEL_CATALOG.items():
        available, reason = _model_available(key)
        library_status[key] = {"available": available, "reason": reason, "label": spec.get("label", key)}
    for key in request.models:
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
    if request.calibrate:
        incompatible_calibration = [key for key in request.models if not calibration_compatibility.get(key, {}).get("compatible")]
        if incompatible_calibration:
            warnings.append("Calibration will be disabled for incompatible models: " + ", ".join(incompatible_calibration))

    rows = int(len(X_train)) if X_train is not None else 0
    columns = int(X_train.shape[1]) if X_train is not None else 0
    estimated_bytes = rows * max(columns, 1) * 8 * 4
    estimated_memory_mb = round(estimated_bytes / (1024 * 1024), 1)
    cpu_cap = max(1, min(4, os.cpu_count() or 1))
    memory_cap = 1 if estimated_memory_mb > 2_000 else 2 if estimated_memory_mb > 750 else cpu_cap
    recommended_parallel = max(1, min(len(request.models) or 1, cpu_cap, memory_cap))

    ready = not blocking
    return {
        "ok": True,
        "ready": ready,
        "blocking_errors": list(dict.fromkeys(blocking)),
        "warnings": list(dict.fromkeys(warnings)),
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "target": target,
        "event_value": train_distribution.get("event_value", request.event_value),
        "non_event_value": request.non_event_value,
        "problem_type": problem_type,
        "train_rows": rows,
        "test_rows": int(len(X_test)) if X_test is not None else 0,
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
        "split_id": split_id,
        "split_status": split_status,
        "split_configuration": split_record.get("config") or {},
        "balancing_configuration": (split_record.get("config") or {}).get("balance_method", "none"),
        "optional_library_status": library_status,
        "model_compatibility": compatibility,
        "calibration_compatibility": calibration_compatibility,
        "cross_validation_compatibility": {
            "compatible": cv_compatible,
            "requested_folds": request.k_folds,
            "effective_folds": effective_folds,
            "minimum_class_count": min_class_count if problem_type == "classification" else None,
        },
        "missing_value_columns": missing_value_columns,
        "infinite_value_columns": infinite,
        "estimated_memory_mb": estimated_memory_mb,
        "recommended_parallelism": recommended_parallel,
        "backend_status": "ready",
        "worker_status": "ready",
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }

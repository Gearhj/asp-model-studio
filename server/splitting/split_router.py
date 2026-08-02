from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from ..core.dataset_store import DATASTORE
from ..core.modeling_scope import authorize_modeling_scope
from ..core.pretraining_invalidation import invalidate_downstream_training_state
from ..core.result_store import RESULTS
from ..core.session_checkpoint import schedule_checkpoint_save
from ..datasets.dataset_identity import (
    active_dataset_identity,
    assert_expected_active_identity,
    resolve_registered_version,
)
from ..security.security_store import audit_event, require_user
from .split_service import split_service, target_distribution


router = APIRouter()


class SplitConfigPayload(BaseModel):
    project_id: str
    split_strategy: Literal[
        "holdout",
        "holdout_current",
        "separate_test",
        "separate_test_oot",
        "cross_validation",
        "hybrid",
    ] = "holdout"
    test_size: float = Field(default=0.2, ge=0.1, le=0.5)
    random_seed: int = Field(default=42, ge=0, le=2_147_483_647)
    stratify: bool = True
    balance_method: Literal["none", "undersample", "oversample", "smote"] = "none"
    minority_share: float = Field(default=0.5, ge=0.05, le=0.5)
    problem_type: Literal["classification", "regression"] = "classification"
    event_value: Any | None = None
    selected_features: list[str] = Field(default_factory=list)
    feature_manifest_version: str = ""
    dataset_id: str = ""
    dataset_version_id: str = ""
    # Backward-compatible expectation only; canonical identity is resolved
    # from the active project link.
    dataset_version: str = ""
    development_dataset_id: str = ""
    development_dataset_version_id: str = ""
    # Deprecated comparison-only alias.
    development_dataset_version: str = ""
    test_dataset_id: str = ""
    test_dataset_version_id: str = ""
    # Deprecated comparison-only alias.
    test_dataset_version: str = ""
    test_target_field: str = ""
    oot_dataset_id: str = ""
    oot_dataset_version_id: str = ""
    # Deprecated comparison-only alias.
    oot_dataset_version: str = ""
    oot_target_field: str = ""
    external_validation_mode: Literal[
        "none",
        "test",
        "oot",
        "test_oot",
    ] = "none"
    fold_method: Literal[
        "none",
        "k_fold",
        "stratified_k_fold",
        "repeated_stratified_k_fold",
        "group_k_fold",
        "stratified_group_k_fold",
        "time_series",
        "nested_cv",
    ] = "stratified_k_fold"
    fold_count: int = Field(default=5, ge=2, le=20)
    repeats: int = Field(default=1, ge=1, le=10)
    inner_fold_count: int = Field(default=3, ge=2, le=10)
    group_field: str = ""
    time_field: str = ""
    shuffle: bool = True
    scoring_fold_requirements: str = "Every validation fold must contain both target classes."
    tuning_scope: Literal[
        "none",
        "within_training_population",
        "nested_inner_folds",
    ] = "within_training_population"
    final_holdout_policy: Literal[
        "untouched_until_final_comparison",
        "external_test_only",
        "cv_only_no_final_holdout",
    ] = "untouched_until_final_comparison"
    holdout_protection_confirmed: bool = False
    cv_design_approved: bool = False
    schema_compatibility_confirmed: bool = False
    target_mapping_verified: bool = False
    balancing_scope: Literal["training_population_only"] = "training_population_only"
    class_weight_policy: Literal["none", "balanced", "custom"] = "none"
    threshold_optimization_policy: Literal["evaluation_only", "disabled"] = "evaluation_only"
    focal_loss_policy: Literal["supported_models_only", "disabled"] = "disabled"
    approval_note: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _current_store(proxy: Any) -> Any:
    """Resolve a scoped proxy while remaining compatible with direct tests."""
    current = getattr(proxy, "current", None)
    return current() if callable(current) else proxy


def _identity_fields(identity: dict[str, Any]) -> dict[str, str]:
    return {
        "project_id": str(identity["project_id"]),
        "dataset_id": str(identity["dataset_id"]),
        "dataset_version_id": str(identity["dataset_version_id"]),
        # Transitional response compatibility only.
        "dataset_version": str(identity["dataset_version_id"]),
    }


def _record_identity_is_current(
    record: dict[str, Any],
    identity: dict[str, Any],
) -> bool:
    if not record:
        return False
    canonical = _identity_fields(identity)
    if any(
        not str(record.get(key) or "").strip()
        or str(record.get(key)) != canonical[key]
        for key in ("project_id", "dataset_id", "dataset_version_id")
    ):
        return False
    legacy = str(record.get("dataset_version") or "").strip()
    return not legacy or legacy == canonical["dataset_version_id"]


def _require_record_identity(
    record: dict[str, Any],
    identity: dict[str, Any],
    label: str,
) -> None:
    if not _record_identity_is_current(record, identity):
        raise HTTPException(
            status_code=409,
            detail=(
                f"The {label} is not bound to the exact active Dataset Library "
                "version. Recreate it before continuing."
            ),
        )


def _selected_manifest_features(manifest: dict[str, Any]) -> list[str]:
    return [
        str(row.get("feature_name"))
        for row in manifest.get("features", [])
        if isinstance(row, dict) and row.get("selected") and row.get("eligibility_status") == "eligible"
    ]


def _manifest_concurrency_token(manifest: dict[str, Any]) -> str:
    """Fingerprint the governed fields that authorize a split computation."""
    return _stable_hash(
        {
            "identity": {
                key: manifest.get(key)
                for key in ("project_id", "dataset_id", "dataset_version_id")
            },
            "manifest_version": (
                manifest.get("manifest_hash")
                or manifest.get("manifest_version")
                or ""
            ),
            "validation_status": manifest.get("validation_status"),
            "materialization_status": manifest.get("materialization_status"),
            "materialized_manifest_hash": manifest.get(
                "materialized_manifest_hash"
            ),
            "confirmation_status": manifest.get("confirmation_status"),
            "confirmed_manifest_hash": manifest.get("confirmed_manifest_hash"),
            "selected_features": _selected_manifest_features(manifest),
        }
    )


def _external_reference_error(
    reference: Any,
    role: str,
    *,
    user: dict[str, Any] | None,
) -> str:
    """Re-resolve a persisted TEST/OOT reference without any latest fallback."""
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
        legacy = str(reference.get(alias) or "").strip()
        if legacy and legacy != dataset_version_id:
            return (
                f"The pinned {role} dataset reference contains conflicting "
                "version identifiers."
            )
    try:
        resolved = resolve_registered_version(
            dataset_id,
            dataset_version_id,
            user=user,
        )
    except HTTPException as exc:
        return (
            f"The pinned {role} dataset version is no longer available to "
            f"this project user: {exc.detail}"
        )
    if (
        str(resolved.get("dataset_id") or "") != dataset_id
        or str(resolved.get("dataset_version_id") or "") != dataset_version_id
    ):
        return f"The pinned {role} dataset version no longer resolves exactly."
    return ""


def _load_external_frame(
    dataset_id: str,
    dataset_version_id: str,
    role: str,
    *,
    user: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not dataset_id or not dataset_version_id:
        raise HTTPException(
            status_code=400,
            detail=f"Select and pin an immutable {role} dataset version.",
        )
    resolved = resolve_registered_version(
        dataset_id,
        dataset_version_id,
        user=user,
    )
    dataset = resolved["dataset"]
    version = resolved["version"]
    path = resolved["artifact_path"]
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"The pinned {role} dataset could not be read: {exc}",
        ) from exc
    if frame.empty:
        raise HTTPException(
            status_code=400,
            detail=f"The pinned {role} dataset has no rows.",
        )
    return frame, {
        "role": role,
        "dataset_id": dataset_id,
        "dataset_name": dataset.get("name"),
        "dataset_version_id": dataset_version_id,
        # Transitional compatibility alias derived from the canonical field.
        "version_id": dataset_version_id,
        "version_hash": version.get("hash"),
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "created_at": version.get("createdAt"),
    }


def _dtype_family(series: pd.Series) -> str:
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "categorical"


def _compatibility_matrix(
    development: pd.DataFrame,
    external: pd.DataFrame,
    selected: list[str],
    development_target: str,
    external_target: str,
    event_value: Any,
    time_field: str = "",
) -> dict[str, Any]:
    missing = [name for name in selected if name not in external.columns]
    common = [name for name in selected if name in external.columns]
    incompatible_types = [
        name
        for name in common
        if _dtype_family(development[name]) != _dtype_family(external[name])
    ]
    dev_target_values = (
        {str(value) for value in development[development_target].dropna().unique()}
        if development_target in development.columns
        else set()
    )
    ext_target_values = (
        {str(value) for value in external[external_target].dropna().unique()}
        if external_target in external.columns
        else set()
    )
    dev_distribution = target_distribution(
        development[development_target], event_value
    )
    ext_distribution = (
        target_distribution(external[external_target], event_value)
        if external_target in external.columns
        else {}
    )
    dev_missing = (
        float(development[common].isna().mean().mean()) if common else 0.0
    )
    ext_missing = float(external[common].isna().mean().mean()) if common else 1.0
    special_values = {-9.0, -8.0, -7.0}

    def special_rate(frame: pd.DataFrame) -> float:
        if not common:
            return 0.0
        numeric = frame[common].apply(pd.to_numeric, errors="coerce")
        return float(numeric.isin(special_values).sum().sum() / max(1, numeric.size))

    dev_special = special_rate(development)
    ext_special = special_rate(external)
    drifted: list[str] = []
    for name in common:
        if _dtype_family(development[name]) != "numeric":
            continue
        dev_values = pd.to_numeric(development[name], errors="coerce").dropna()
        ext_values = pd.to_numeric(external[name], errors="coerce").dropna()
        if not len(dev_values) or not len(ext_values):
            continue
        scale = float(dev_values.std())
        shift = abs(float(ext_values.mean()) - float(dev_values.mean()))
        if scale > 0 and shift / scale > 0.5:
            drifted.append(name)
    date_detail = "No governed time field selected."
    date_status = "not_applicable"
    if time_field:
        if time_field not in development.columns or time_field not in external.columns:
            date_detail = f"{time_field} is unavailable in one population."
            date_status = "failed"
        else:
            dev_dates = pd.to_datetime(development[time_field], errors="coerce")
            ext_dates = pd.to_datetime(external[time_field], errors="coerce")
            date_detail = (
                f"Development {dev_dates.min()} to {dev_dates.max()}; "
                f"external {ext_dates.min()} to {ext_dates.max()}."
            )
            date_status = "passed" if dev_dates.notna().any() and ext_dates.notna().any() else "failed"

    event_delta = None
    if (
        isinstance(dev_distribution.get("event_rate"), (int, float))
        and isinstance(ext_distribution.get("event_rate"), (int, float))
    ):
        event_delta = abs(
            float(dev_distribution["event_rate"])
            - float(ext_distribution["event_rate"])
        )
    checks = [
        {
            "check": "Column presence",
            "status": "passed" if not missing else "failed",
            "detail": "All governed predictors are present."
            if not missing
            else "Missing: " + ", ".join(missing),
        },
        {
            "check": "Data types",
            "status": "passed" if not incompatible_types else "failed",
            "detail": "Type families are compatible."
            if not incompatible_types
            else "Incompatible: " + ", ".join(incompatible_types),
        },
        {
            "check": "Target values",
            "status": "passed"
            if external_target in external.columns
            and ext_target_values
            and ext_target_values.issubset(dev_target_values)
            else "failed",
            "detail": f"Development {sorted(dev_target_values)}; external {sorted(ext_target_values)}.",
        },
        {
            "check": "Event rate",
            "status": "passed"
            if event_delta is not None and event_delta <= 0.10
            else "warning",
            "detail": (
                f"Absolute event-rate difference {event_delta:.2%}."
                if event_delta is not None
                else "Binary event rate is unavailable."
            ),
        },
        {
            "check": "Missingness",
            "status": "passed" if abs(dev_missing - ext_missing) <= 0.10 else "warning",
            "detail": f"Development {dev_missing:.2%}; external {ext_missing:.2%}.",
        },
        {
            "check": "Feature availability",
            "status": "passed" if len(common) == len(selected) else "failed",
            "detail": f"{len(common)} of {len(selected)} governed predictors available.",
        },
        {
            "check": "Special-value patterns",
            "status": "passed" if abs(dev_special - ext_special) <= 0.05 else "warning",
            "detail": f"Development {dev_special:.2%}; external {ext_special:.2%}.",
        },
        {
            "check": "Date range",
            "status": date_status,
            "detail": date_detail,
        },
        {
            "check": "Drift indicators",
            "status": "passed" if not drifted else "warning",
            "detail": "No large standardized mean shifts detected."
            if not drifted
            else f"{len(drifted)} predictors exceed the mean-shift screen: "
            + ", ".join(drifted[:8]),
        },
    ]
    blocking = [
        row for row in checks if row["status"] == "failed"
    ]
    return {
        "status": "passed" if not blocking else "failed",
        "checks": checks,
        "development_distribution": dev_distribution,
        "external_distribution": ext_distribution,
        "blocking_checks": [row["check"] for row in blocking],
    }


def _require_full_dataset(store: Any = DATASTORE):
    frame = store.get_base_df()
    if frame is None or frame.empty:
        raise HTTPException(status_code=400, detail="No full backend dataset is loaded.")
    target = str(store.target or "")
    if not target or target not in frame.columns:
        raise HTTPException(status_code=400, detail="Confirm a target column before creating a split.")
    return frame, target


def _current_status(
    project_id: str,
    *,
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scoped_store = _current_store(DATASTORE)
    identity = active_dataset_identity(project_id, user=user, store=scoped_store)
    meta = scoped_store.meta
    record = meta.get("split_record") if isinstance(meta.get("split_record"), dict) else {}
    manifest = meta.get("feature_manifest") if isinstance(meta.get("feature_manifest"), dict) else {}
    stored_status = str(meta.get("split_status") or "not_created")
    has_split = all(part is not None for part in scoped_store.get_splits())
    status = stored_status
    reason = ""
    current_manifest_version = str(
        manifest.get("manifest_hash") or manifest.get("manifest_version") or ""
    )
    if not current_manifest_version:
        raise HTTPException(
            status_code=409,
            detail=(
                "A governed feature manifest for the active Dataset Library "
                "version is required before Validation Design."
            ),
        )
    current_selected = _selected_manifest_features(manifest)
    current_target = str(scoped_store.target or "")
    has_engineered_features = any(
        isinstance(row, dict) and row.get("origin") != "original"
        for row in manifest.get("features") or []
    )
    record_selected = [str(value) for value in record.get("selected_features") or []]
    distributions = dict(record.get("distributions") or {})
    current_frame = scoped_store.get_base_df()
    if (
        "full_dataset" not in distributions
        and current_frame is not None
        and not current_frame.empty
        and current_target
        and current_target in current_frame.columns
    ):
        distributions["full_dataset"] = target_distribution(
            current_frame[current_target],
            record.get("event_value")
            if record
            else scoped_store.meta.get("event_value"),
        )
    validation_design = (
        record.get("validation_design")
        if isinstance(record.get("validation_design"), dict)
        else {}
    )
    if status == "current" and not _record_identity_is_current(record, identity):
        status = "stale"
        reason = (
            "Validation split is stale because it is not bound to the exact "
            "active Dataset Library version."
        )
    elif status == "current" and not _record_identity_is_current(manifest, identity):
        status = "stale"
        reason = (
            "Validation split is stale because the feature manifest is not "
            "bound to the exact active Dataset Library version."
        )
    elif (
        status == "current"
        and not _record_identity_is_current(validation_design, identity)
    ):
        status = "stale"
        reason = (
            "Validation split is stale because the validation design is not "
            "bound to the exact active Dataset Library version."
        )
    elif status == "current" and not has_split:
        status = "stale"
        reason = "Validation split is stale because split data is not loaded in the backend session."
    elif status == "current" and record.get("feature_manifest_version") and record.get("feature_manifest_version") != current_manifest_version:
        status = "stale"
        reason = "Validation split is stale because engineered features were updated."
    elif status == "current" and record_selected and record_selected != current_selected:
        status = "stale"
        reason = "Validation split is stale because the selected feature set changed."
    elif status == "current" and record.get("target") and record.get("target") != current_target:
        status = "stale"
        reason = "Validation split is stale because the target changed."
    elif (
        status == "current"
        and has_engineered_features
        and (
            manifest.get("confirmation_status") != "confirmed"
            or manifest.get("confirmed_manifest_hash")
            != current_manifest_version
        )
    ):
        status = "stale"
        reason = "Validation design is stale because the feature contract is no longer confirmed current."
    elif status == "current":
        for reference, role in (
            (record.get("test_reference"), "TEST"),
            (record.get("oot_reference"), "OOT"),
        ):
            external_error = _external_reference_error(
                reference,
                role,
                user=user,
            )
            if external_error:
                status = "stale"
                reason = external_error + " Rebuild Validation Design."
                break
        if status == "current":
            train_distribution = (
                (record.get("distributions") or {}).get(
                    "train_after_balancing"
                )
                or {}
            )
            holdout_distribution = (
                (record.get("distributions") or {}).get("holdout_untouched")
                or {}
            )
            if train_distribution.get("events") == 0:
                status = "stale"
                reason = "Training split has zero events."
            elif holdout_distribution.get("events") == 0:
                status = "stale"
                reason = "Holdout split has zero events."
    if not reason:
        if status == "current":
            reason = "Ready for next step. Validation split is current."
        elif has_split:
            reason = "Validation split is stale. Rebuild Validation Split."
        else:
            reason = "Create a governed validation split before continuing."
    return {
        "ok": True,
        **_identity_fields(identity),
        "status": status,
        "ready": status == "current" and has_split,
        "readiness_reason": reason,
        "has_split": has_split,
        "split_id": record.get("split_id"),
        "config_hash": record.get("config_hash"),
        "selected_feature_hash": record.get("selected_feature_hash"),
        "split_config_hash": record.get("split_config_hash"),
        "balancing_config_hash": record.get("balancing_config_hash"),
        "created_at": record.get("created_at"),
        "target": record.get("target"),
        "event_value": record.get("event_value"),
        "feature_manifest_version": record.get("feature_manifest_version"),
        "selected_features": record.get("selected_features") or [],
        "feature_count": len(record.get("selected_features") or []),
        "config": record.get("config") or {},
        "distributions": distributions,
        "n_train": record.get("n_train"),
        "n_test": record.get("n_test"),
        "original_train_rows": record.get("original_train_rows"),
        "duration_ms": record.get("duration_ms"),
        "execution_ms": record.get("execution_ms") or record.get("duration_ms"),
        "validation_design": record.get("validation_design") or {},
        "validation_design_id": (record.get("validation_design") or {}).get(
            "validation_design_id"
        ),
        "validation_design_version": (
            record.get("validation_design") or {}
        ).get("design_version"),
        "training_population_id": record.get("training_population_id"),
        "holdout_population_id": record.get("holdout_population_id"),
        "test_reference": record.get("test_reference"),
        "oot_reference": record.get("oot_reference"),
        "cv_design": record.get("cv_design") or {},
        "fold_architecture": record.get("fold_architecture") or {},
        "compatibility_matrix": record.get("compatibility_matrix") or {},
        "validation_risks": record.get("validation_risks") or [],
        "completion_gates": record.get("completion_gates") or {},
        "confirmation_actor": record.get("confirmation_actor"),
        "confirmation_time": record.get("confirmation_time"),
        "evaluation_population_role": record.get(
            "evaluation_population_role"
        ),
    }


@router.get("/status")
def balancing_split_status(
    project_id: str = Query(...),
    expected_dataset_id: str = Query(""),
    expected_dataset_version_id: str = Query(""),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    scoped_store = _current_store(DATASTORE)
    with scoped_store.state_lock:
        assert_expected_active_identity(
            project_id,
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_dataset_version_id,
            require_expected=True,
            user=user,
            store=scoped_store,
        )
        return _current_status(project_id, user=user)


@router.post("/config")
def balancing_split_config(payload: SplitConfigPayload, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, payload.project_id, "edit")
    started = time.perf_counter()
    scoped_store = _current_store(DATASTORE)
    scoped_results = _current_store(RESULTS)
    # Capture one immutable computation snapshot. Expensive compatibility and
    # split work happens outside the lock, but no output is publishable unless
    # this exact identity/revision/manifest contract still holds at commit.
    with scoped_store.state_lock:
        identity = assert_expected_active_identity(
            payload.project_id,
            expected_dataset_id=payload.dataset_id,
            expected_dataset_version_id=payload.dataset_version_id,
            legacy_dataset_version=payload.dataset_version,
            require_expected=True,
            user=user,
            store=scoped_store,
        )
        frame, target = _require_full_dataset(scoped_store)
        frame = frame.copy(deep=True)
        manifest = (
            deepcopy(scoped_store.meta.get("feature_manifest"))
            if isinstance(scoped_store.meta.get("feature_manifest"), dict)
            else {}
        )
        captured_data_revision = int(scoped_store.data_revision)
        captured_manifest_token = _manifest_concurrency_token(manifest)
    if (
        payload.development_dataset_id
        and payload.development_dataset_id != identity["dataset_id"]
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The requested development dataset does not match the active "
                "Dataset Library link."
            ),
        )
    if (
        payload.development_dataset_version_id
        and payload.development_dataset_version_id
        != identity["dataset_version_id"]
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The requested development dataset version does not match the "
                "active Dataset Library version."
            ),
        )
    if (
        payload.development_dataset_version
        and payload.development_dataset_version
        != identity["dataset_version_id"]
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The deprecated development dataset version expectation does "
                "not match the active Dataset Library version."
            ),
        )
    if (
        payload.development_dataset_version_id
        and payload.development_dataset_version
        and payload.development_dataset_version_id
        != payload.development_dataset_version
    ):
        raise HTTPException(
            status_code=409,
            detail="Conflicting development dataset version expectations were supplied.",
        )
    _require_record_identity(manifest, identity, "feature manifest")
    current_manifest_version = str(
        manifest.get("manifest_hash") or manifest.get("manifest_version") or ""
    )
    current_dataset_id = str(identity["dataset_id"])
    current_dataset_version = str(identity["dataset_version_id"])

    if payload.feature_manifest_version and current_manifest_version and payload.feature_manifest_version != current_manifest_version:
        raise HTTPException(status_code=409, detail="The feature manifest changed. Refresh Final Predictor Review before creating the split.")
    manifest_selected = _selected_manifest_features(manifest)
    selected = list(
        dict.fromkeys(
            payload.selected_features
            or manifest_selected
            or scoped_store.get_selected_columns()
        )
    )
    missing = [name for name in selected if name not in frame.columns]
    if missing:
        raise HTTPException(status_code=409, detail="Selected engineered features must be materialized before splitting: " + ", ".join(missing))
    if target in selected:
        raise HTTPException(status_code=400, detail="The target cannot be included in the predictor manifest.")

    engineered_features = [
        row
        for row in manifest.get("features") or []
        if isinstance(row, dict) and row.get("origin") != "original"
    ]
    if engineered_features and (
        manifest.get("validation_status") != "passed"
        or manifest.get("materialization_status") != "current"
        or manifest.get("materialized_manifest_hash")
        != current_manifest_version
        or manifest.get("confirmed_manifest_hash") != current_manifest_version
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The engineered feature contract must be validated, materialized, "
                "and confirmed current before Validation Design."
            ),
        )

    config = payload.model_dump(
        exclude={
            "project_id",
            "selected_features",
            "feature_manifest_version",
            "dataset_id",
            "dataset_version_id",
            "dataset_version",
            "development_dataset_id",
            "development_dataset_version_id",
            "development_dataset_version",
            "test_dataset_version",
            "oot_dataset_version",
        }
    )
    test_dataset_version_id = str(
        payload.test_dataset_version_id or ""
    ).strip()
    oot_dataset_version_id = str(
        payload.oot_dataset_version_id or ""
    ).strip()
    if (
        payload.test_dataset_version
        and payload.test_dataset_version != test_dataset_version_id
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The deprecated TEST dataset version expectation conflicts "
                "with test_dataset_version_id."
            ),
        )
    if (
        payload.oot_dataset_version
        and payload.oot_dataset_version != oot_dataset_version_id
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The deprecated OOT dataset version expectation conflicts "
                "with oot_dataset_version_id."
            ),
        )
    config["development_dataset_id"] = current_dataset_id
    config["development_dataset_version_id"] = current_dataset_version
    config["test_dataset_version_id"] = test_dataset_version_id
    config["oot_dataset_version_id"] = oot_dataset_version_id
    if payload.split_strategy in {"holdout", "holdout_current"} and "fold_method" not in payload.model_fields_set:
        config["fold_method"] = "none"
        config["tuning_scope"] = "none"
    if payload.split_strategy in {"cross_validation", "hybrid"} and config.get("fold_method") == "none":
        raise HTTPException(
            status_code=400,
            detail="Select and approve a cross-validation fold method for this strategy.",
        )
    if payload.split_strategy == "cross_validation":
        config["final_holdout_policy"] = "cv_only_no_final_holdout"
    config["target"] = target

    test_frame: pd.DataFrame | None = None
    test_reference: dict[str, Any] | None = None
    oot_frame: pd.DataFrame | None = None
    oot_reference: dict[str, Any] | None = None
    compatibility_matrix: dict[str, Any] = {
        "status": "not_applicable",
        "populations": {},
    }
    test_target = payload.test_target_field or target
    oot_target = payload.oot_target_field or target
    test_requested = (
        payload.split_strategy in {"separate_test", "separate_test_oot"}
        or payload.external_validation_mode in {"test", "test_oot"}
    )
    oot_requested = (
        payload.split_strategy == "separate_test_oot"
        or payload.external_validation_mode in {"oot", "test_oot"}
    )
    if test_requested:
        if not test_dataset_version_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Select and pin an exact immutable TEST "
                    "dataset_version_id."
                ),
            )
        test_frame, test_reference = _load_external_frame(
            payload.test_dataset_id,
            test_dataset_version_id,
            "TEST",
            user=user,
        )
        test_compatibility = _compatibility_matrix(
            frame,
            test_frame,
            selected,
            target,
            test_target,
            payload.event_value,
            payload.time_field,
        )
        compatibility_matrix = {
            "status": test_compatibility["status"],
            "populations": {"TEST": test_compatibility},
        }
        if test_compatibility["status"] != "passed":
            raise HTTPException(
                status_code=409,
                detail=(
                    "The pinned TEST dataset failed blocking compatibility checks: "
                    + ", ".join(test_compatibility["blocking_checks"])
                ),
            )
    if oot_requested:
        if not oot_dataset_version_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Select and pin an exact immutable OOT "
                    "dataset_version_id."
                ),
            )
        oot_frame, oot_reference = _load_external_frame(
            payload.oot_dataset_id,
            oot_dataset_version_id,
            "OOT",
            user=user,
        )
        oot_compatibility = _compatibility_matrix(
            frame,
            oot_frame,
            selected,
            target,
            oot_target,
            payload.event_value,
            payload.time_field,
        )
        compatibility_matrix["populations"]["OOT"] = oot_compatibility
        if oot_compatibility["status"] != "passed":
            compatibility_matrix["status"] = "failed"
            raise HTTPException(
                status_code=409,
                detail=(
                    "The pinned OOT dataset failed blocking compatibility checks: "
                    + ", ".join(oot_compatibility["blocking_checks"])
                ),
            )
        if compatibility_matrix["status"] == "not_applicable":
            compatibility_matrix["status"] = "passed"

    if test_requested or oot_requested:
        if not payload.schema_compatibility_confirmed:
            raise HTTPException(
                status_code=400,
                detail="Confirm the reviewed dataset compatibility matrix.",
            )
        if not payload.target_mapping_verified:
            raise HTTPException(
                status_code=400,
                detail="Verify the TEST/OOT target mapping before approval.",
            )
    if payload.split_strategy in {"holdout", "holdout_current", "hybrid"} and not payload.holdout_protection_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Confirm that the final holdout is protected from tuning and model selection.",
        )
    if config.get("fold_method") != "none" and not payload.cv_design_approved:
        raise HTTPException(
            status_code=400,
            detail="Approve the cross-validation design before creating the training populations.",
        )
    if (
        config.get("fold_method") != "none"
        and payload.balance_method in {"undersample", "oversample", "smote"}
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Fold-local resampling is required for cross-validation and is not "
                "silently approximated. Choose no resampling or class weights for "
                "this CV design."
            ),
        )

    try:
        result = split_service.make_validation_split(
            frame,
            target,
            selected,
            config,
            external_test_frame=(
                test_frame
                if payload.split_strategy in {"separate_test", "separate_test_oot"}
                else None
            ),
            external_test_target=test_target,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    committed_data_revision = captured_data_revision + 1
    config_payload = {
        **config,
        **_identity_fields(identity),
        "data_revision": committed_data_revision,
        "feature_manifest_version": current_manifest_version,
        "selected_features": selected,
    }
    config_hash = _stable_hash(config_payload)[:20]
    selected_feature_hash = _stable_hash({"selected_features": selected})[:20]
    split_config_hash = _stable_hash(
        {
            "split": {
                key: config.get(key)
                for key in (
                    "split_strategy",
                    "test_size",
                    "random_seed",
                    "stratify",
                    "group_field",
                    "time_field",
                    "final_holdout_policy",
                )
            }
        }
    )[:20]
    balancing_config_hash = _stable_hash(
        {
            "balancing": {
                key: config.get(key)
                for key in (
                    "balance_method",
                    "minority_share",
                    "balancing_scope",
                    "class_weight_policy",
                    "threshold_optimization_policy",
                    "focal_loss_policy",
                )
            }
        }
    )[:20]
    split_id = f"split-{config_hash}"
    design_seed = {
        "strategy": payload.split_strategy,
        **_identity_fields(identity),
        "data_revision": committed_data_revision,
        "feature_manifest_version": current_manifest_version,
        "target": target,
        "selected_feature_hash": selected_feature_hash,
        "split_config_hash": split_config_hash,
        "balancing_config_hash": balancing_config_hash,
        "test_reference": test_reference,
        "oot_reference": oot_reference,
        "fold_architecture": {
            key: value
            for key, value in result.fold_architecture.items()
            if key not in {"folds", "execution_splits"}
        },
    }
    design_hash = _stable_hash(design_seed)[:20]
    validation_design_id = f"validation-design-{design_hash}"
    design_version = f"vd-{design_hash}"
    training_population_id = f"population-train-{config_hash[:12]}"
    holdout_population_id = (
        f"population-{result.evaluation_population_role}-{config_hash[:12]}"
        if result.evaluation_population_role
        else None
    )
    distributions = {
        "full_dataset": target_distribution(frame[target], payload.event_value),
        "train_before_balancing": result.original_train_distribution,
        "train_after_balancing": result.applied_train_distribution,
        "holdout_untouched": result.test_distribution,
        "cv_folds": [
            {
                "repeat": fold.get("repeat"),
                "fold": fold.get("fold"),
                **(fold.get("validation_distribution") or {}),
            }
            for fold in result.fold_architecture.get("folds") or []
        ],
    }
    if test_frame is not None and test_target in test_frame.columns:
        distributions["test_untouched"] = target_distribution(
            test_frame[test_target], payload.event_value
        )
    if oot_frame is not None and oot_target in oot_frame.columns:
        distributions["oot_untouched"] = target_distribution(
            oot_frame[oot_target], payload.event_value
        )

    fold_rows = result.fold_architecture.get("folds") or []
    cv_execution_splits = (
        result.fold_architecture.get("execution_splits") or []
    )
    fold_definition_id = "fold-" + _stable_hash(
        {
            "training_population_id": training_population_id,
            "method": result.fold_architecture.get("method"),
            "random_seed": result.fold_architecture.get("random_seed"),
            "execution_splits": cv_execution_splits,
        }
    )[:20]
    fold_event_failure = any(
        fold.get("validation_distribution", {}).get("events") == 0
        or fold.get("validation_distribution", {}).get("non_events") == 0
        for fold in fold_rows
    )
    full_event_rate = distributions["full_dataset"].get("event_rate")
    full_events = distributions["full_dataset"].get("events")
    compatibility_failed = compatibility_matrix.get("status") == "failed"
    validation_risks = [
        {
            "risk": "Low event count",
            "status": "attention"
            if isinstance(full_events, int)
            and full_events < max(50, int(config.get("fold_count") or 2) * 10)
            else "low",
            "detail": f"{full_events if full_events is not None else 'N/A'} events in the governed population.",
        },
        {
            "risk": "Fold insufficiency",
            "status": "blocking" if fold_event_failure else "low",
            "detail": "Every validation fold contains both classes."
            if fold_rows and not fold_event_failure
            else "No CV folds configured."
            if not fold_rows
            else "At least one validation fold lacks event coverage.",
        },
        {
            "risk": "Target imbalance",
            "status": "attention"
            if isinstance(full_event_rate, (int, float))
            and not 0.20 <= float(full_event_rate) <= 0.80
            else "low",
            "detail": f"Governed event rate {float(full_event_rate):.2%}."
            if isinstance(full_event_rate, (int, float))
            else "Binary event rate is unavailable.",
        },
        {
            "risk": "Group leakage",
            "status": "low"
            if config.get("fold_method") in {"group_k_fold", "stratified_group_k_fold"}
            and config.get("group_field")
            else "not_applicable",
            "detail": "Group boundaries are preserved."
            if config.get("group_field")
            else "No group constraint selected.",
        },
        {
            "risk": "Time leakage",
            "status": "low"
            if config.get("fold_method") == "time_series" and config.get("time_field")
            else "not_applicable",
            "detail": "Chronological fold ordering is enforced."
            if config.get("time_field")
            else "No time constraint selected.",
        },
        {
            "risk": "Schema mismatch",
            "status": "blocking" if compatibility_failed else "low",
            "detail": "Pinned external populations passed blocking compatibility checks."
            if compatibility_matrix.get("status") == "passed"
            else "No external population is required."
            if compatibility_matrix.get("status") == "not_applicable"
            else "A blocking compatibility check failed.",
        },
        {
            "risk": "Holdout reuse",
            "status": "low"
            if payload.holdout_protection_confirmed
            else "blocking",
            "detail": config.get("final_holdout_policy"),
        },
        {
            "risk": "OOT unavailable",
            "status": "low" if oot_reference else "not_applicable",
            "detail": (
                f"Pinned {oot_reference.get('dataset_name')} "
                f"{oot_reference.get('dataset_version_id')}."
                if oot_reference
                else "No OOT population is part of this approved strategy."
            ),
        },
    ]
    event_coverage_sufficient = not fold_event_failure and not (
        result.original_train_distribution.get("events") == 0
        or result.test_distribution.get("events") == 0
    )
    external_required = test_requested or oot_requested
    oot_required = oot_requested
    feature_contract_current = not engineered_features or (
        manifest.get("confirmed_manifest_hash") == current_manifest_version
    )
    completion_gates = {
        "validation_strategy_selected": bool(payload.split_strategy),
        "dataset_versions_pinned": bool(current_dataset_id)
        and bool(current_dataset_version)
        and (not test_requested or bool(test_reference))
        and (not oot_required or bool(oot_reference)),
        "schema_compatibility_verified": not compatibility_failed,
        "target_mapping_verified": (
            payload.target_mapping_verified if external_required else True
        ),
        "feature_manifest_current": feature_contract_current,
        "target_and_target_source_excluded": target not in selected
        and not any(
            name in selected
            for name in (
                manifest.get("predictor_authorization", {}).get(
                    "target_source_excluded"
                )
                or []
            )
        ),
        "populations_created": bool(len(result.y_train)) and bool(len(result.y_test)),
        "event_coverage_sufficient": event_coverage_sufficient,
        "holdout_protection_confirmed": payload.holdout_protection_confirmed,
        "cv_design_approved": (
            payload.cv_design_approved
            if config.get("fold_method") != "none"
            else True
        ),
        "balancing_policy_recorded": bool(payload.balancing_scope),
    }
    failed_gates = [name for name, passed in completion_gates.items() if not passed]
    if failed_gates:
        raise HTTPException(
            status_code=409,
            detail="Validation Design gates failed: " + ", ".join(failed_gates),
        )
    approved_at = _now()
    actor = {
        "user_id": user.get("userId"),
        "display_name": user.get("displayName") or user.get("email") or "Current ATLAS user",
    }
    cv_design = {
        "method": result.fold_architecture.get("method"),
        "fold_count": result.fold_architecture.get("fold_count"),
        "repeats": result.fold_architecture.get("repeats"),
        "group_field": result.fold_architecture.get("group_field"),
        "time_field": result.fold_architecture.get("time_field"),
        "shuffle": result.fold_architecture.get("shuffle"),
        "random_seed": result.fold_architecture.get("random_seed"),
        "tuning_scope": config.get("tuning_scope"),
        "scoring_fold_requirements": config.get("scoring_fold_requirements"),
        "nested": result.fold_architecture.get("nested"),
        "inner_folds": result.fold_architecture.get("inner_folds"),
        "approved": payload.cv_design_approved
        if result.fold_architecture.get("enabled")
        else True,
        "execution_fold_count": len(cv_execution_splits),
        "fold_definition_id": fold_definition_id,
    }
    balancing_policy = {
        "method": payload.balance_method,
        "scope": payload.balancing_scope,
        "minority_share": payload.minority_share,
        "class_weight_policy": payload.class_weight_policy,
        "threshold_optimization_policy": payload.threshold_optimization_policy,
        "focal_loss_policy": payload.focal_loss_policy,
        "synthetic_rows_added": result.synthetic_rows_added,
        "rows_removed": result.rows_removed,
        "holdout_untouched": True,
        "test_untouched": True,
        "oot_untouched": True,
        "selection_resampling_status": "not_applied",
    }
    validation_design = {
        **_identity_fields(identity),
        "data_revision": committed_data_revision,
        "validation_design_id": validation_design_id,
        "design_version": design_version,
        "strategy": payload.split_strategy,
        "development_dataset": {
            "dataset_id": current_dataset_id,
            "dataset_version_id": current_dataset_version,
            # Transitional compatibility alias derived from the canonical ID.
            "version_id": current_dataset_version,
            "dataset_version": current_dataset_version,
        },
        "training_population_id": training_population_id,
        "selection_partition_id": training_population_id,
        "holdout_population_id": holdout_population_id,
        "final_holdout_partition_id": holdout_population_id,
        "final_holdout_status": "sealed" if holdout_population_id else "not_applicable",
        "holdout_isolation_status": "verified",
        "fold_definition_id": fold_definition_id,
        "test_reference": test_reference,
        "oot_reference": oot_reference,
        "split_seed": payload.random_seed,
        "stratification": payload.stratify,
        "group_field": payload.group_field or None,
        "time_field": payload.time_field or None,
        "fold_method": cv_design["method"],
        "number_of_folds": cv_design["fold_count"],
        "number_of_repeats": cv_design["repeats"],
        "tuning_scope": payload.tuning_scope,
        "final_holdout_use_policy": config.get("final_holdout_policy"),
        "balancing_scope": payload.balancing_scope,
        "balancing_policy": balancing_policy,
        "approved_by": actor,
        "approved_at": approved_at,
        "approval_note": payload.approval_note,
        "feature_manifest_hash": current_manifest_version,
        "target": target,
        "selected_feature_hash": selected_feature_hash,
        "status": "approved",
    }
    record = {
        **_identity_fields(identity),
        "data_revision": committed_data_revision,
        "split_id": split_id,
        "config_hash": config_hash,
        "selected_feature_hash": selected_feature_hash,
        "split_config_hash": split_config_hash,
        "balancing_config_hash": balancing_config_hash,
        "created_at": _now(),
        "target": target,
        "event_value": payload.event_value,
        "feature_manifest_version": current_manifest_version,
        "selected_features": selected,
        "config": config,
        "distributions": distributions,
        "validation_design": validation_design,
        "training_population_id": training_population_id,
        "selection_partition_id": training_population_id,
        "holdout_population_id": holdout_population_id,
        "final_holdout_partition_id": holdout_population_id,
        "final_holdout_status": "sealed" if holdout_population_id else "not_applicable",
        "holdout_isolation_status": "verified",
        "fold_definition_id": fold_definition_id,
        "test_reference": test_reference,
        "oot_reference": oot_reference,
        "cv_design": cv_design,
        "fold_architecture": {
            key: value
            for key, value in result.fold_architecture.items()
            if key != "execution_splits"
        },
        # Exact positional folds are persisted for the training engine but
        # intentionally omitted from status responses and evidence payloads.
        "cv_execution_splits": cv_execution_splits,
        "compatibility_matrix": compatibility_matrix,
        "validation_risks": validation_risks,
        "completion_gates": completion_gates,
        "balancing_policy": balancing_policy,
        "confirmation_actor": actor,
        "confirmation_time": approved_at,
        "evaluation_population_role": result.evaluation_population_role,
        "n_train": int(len(result.y_train)),
        "n_test": int(len(result.y_test)),
        "original_train_rows": result.original_train_rows,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    record["execution_ms"] = record["duration_ms"]
    committed_splits = (
        result.X_train.copy(deep=True),
        result.X_test.copy(deep=True),
        result.y_train.copy(deep=True),
        result.y_test.copy(deep=True),
    )
    with scoped_store.state_lock:
        current_identity = assert_expected_active_identity(
            payload.project_id,
            expected_dataset_id=identity["dataset_id"],
            expected_dataset_version_id=identity["dataset_version_id"],
            user=user,
            store=scoped_store,
        )
        current_manifest = (
            scoped_store.meta.get("feature_manifest")
            if isinstance(scoped_store.meta.get("feature_manifest"), dict)
            else {}
        )
        if (
            any(
                str(current_identity.get(key) or "")
                != str(identity.get(key) or "")
                for key in ("project_id", "dataset_id", "dataset_version_id")
            )
            or int(scoped_store.data_revision) != captured_data_revision
            or not _record_identity_is_current(current_manifest, identity)
            or _manifest_concurrency_token(current_manifest)
            != captured_manifest_token
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "The governed dataset or feature manifest changed while "
                    "Validation Design was being computed. Refresh Balance & "
                    "Split and rebuild from the current state."
                ),
            )
        for reference, role in (
            (test_reference, "TEST"),
            (oot_reference, "OOT"),
        ):
            external_error = _external_reference_error(
                reference,
                role,
                user=user,
            )
            if external_error:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        external_error
                        + " Refresh Balance & Split before committing."
                    ),
                )

        invalidation = invalidate_downstream_training_state(
            "Validation Design rebuilt",
            store=scoped_store,
            result_store=scoped_results,
            split_status="stale",
            bump_revision=True,
        )
        committed_data_revision = int(invalidation["data_revision"])
        if committed_data_revision != int(record["data_revision"]):
            raise RuntimeError(
                "Validation Design revision transition was not monotonic."
            )

        # Publish the four arrays and every matching metadata record together.
        # No consumer can observe a new split with an old design (or vice versa).
        scoped_store.meta["selected_columns"] = list(selected)
        (
            scoped_store.X_train,
            scoped_store.X_test,
            scoped_store.y_train,
            scoped_store.y_test,
        ) = committed_splits
        scoped_store.meta["split_record"] = record
        scoped_store.meta["split_config"] = config_payload
        scoped_store.meta["validation_design"] = validation_design
        scoped_store.meta["target_prevalence"] = {
            "original": distributions["full_dataset"].get("event_rate"),
            "train": distributions["train_after_balancing"].get("event_rate"),
            "test": distributions["holdout_untouched"].get("event_rate"),
        }
        scoped_store.meta["split_status"] = "current"
        manifest["split_status"] = "current"
        scoped_store.meta["feature_manifest"] = manifest
    audit_event(
        "modeling.validation_design.approved",
        "project",
        payload.project_id,
        "success",
        metadata={
            "validationDesignId": validation_design_id,
            "designVersion": design_version,
            "splitId": split_id,
            "strategy": payload.split_strategy,
            "datasetId": current_dataset_id,
            "datasetVersionId": current_dataset_version,
        },
        user_id=user.get("userId"),
    )
    schedule_checkpoint_save()
    public_record = {
        key: value
        for key, value in record.items()
        if key != "cv_execution_splits"
    }
    return {
        "ok": True,
        "status": "current",
        "ready": True,
        "readiness_reason": "Ready for next step. Validation split is current.",
        "has_split": True,
        **public_record,
    }

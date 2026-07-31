from __future__ import annotations

from copy import deepcopy
from functools import wraps
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from ..core.modeling_scope import authorize_modeling_scope
from ..core.pretraining_invalidation import invalidate_downstream_training_state
from ..core.session_checkpoint import save_checkpoint
from ..datasets.dataset_identity import (
    assert_expected_active_identity,
    coalesce_identity_expectations,
)
from ..security.security_store import require_user
from .outlier_service import outlier_service
from .feature_profile_service import information_value
from .predictor_authorization import (
    bureau_special_mask,
    bureau_special_summary,
    governed_predictor_authorization,
)


router = APIRouter()
MISSING_STRINGS = {"", "na", "n/a", "null", "none", "nan", "missing"}


def _state_locked_read(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        scoped_store = DATASTORE.current()
        with scoped_store.state_lock:
            return function(*args, **kwargs)

    return wrapped


class MissingRule(BaseModel):
    strategy: str = "None"
    constantValue: Optional[Any] = None


class MissingApplyRequest(BaseModel):
    project_id: str
    config: Dict[str, MissingRule] = Field(default_factory=dict)
    event_value: Any = None
    problem_type: str | None = None
    expected_dataset_id: str | None = None
    expected_dataset_version_id: str | None = None
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    dataset_version: str | None = None


class MissingValidateRequest(BaseModel):
    project_id: str
    event_value: Any = None
    problem_type: str | None = None
    expected_dataset_id: str | None = None
    expected_dataset_version_id: str | None = None
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    dataset_version: str | None = None


def _active_request_identity(
    request: Any,
    user: Dict[str, Any],
) -> Dict[str, Any]:
    dataset_id, dataset_version_id, legacy_version = (
        coalesce_identity_expectations(
            expected_dataset_id=request.expected_dataset_id,
            expected_dataset_version_id=request.expected_dataset_version_id,
            dataset_id=request.dataset_id,
            dataset_version_id=request.dataset_version_id,
            legacy_dataset_version=request.dataset_version,
        )
    )
    return assert_expected_active_identity(
        request.project_id,
        expected_dataset_id=dataset_id,
        expected_dataset_version_id=dataset_version_id,
        legacy_dataset_version=legacy_version,
        require_expected=True,
        user=user,
    )


def _identity_fields(identity: Dict[str, Any]) -> Dict[str, str]:
    dataset_version_id = str(identity["dataset_version_id"])
    return {
        "project_id": str(identity["project_id"]),
        "dataset_id": str(identity["dataset_id"]),
        "dataset_version_id": dataset_version_id,
        # Compatibility alias only; canonical identity remains dataset_version_id.
        "dataset_version": dataset_version_id,
    }


def _record_matches_identity(
    record: Any,
    identity: Dict[str, Any],
) -> bool:
    legacy = str(record.get("dataset_version") or "") if isinstance(record, dict) else ""
    return (
        isinstance(record, dict)
        and record.get("project_id") == identity["project_id"]
        and record.get("dataset_id") == identity["dataset_id"]
        and record.get("dataset_version_id") == identity["dataset_version_id"]
        and (not legacy or legacy == identity["dataset_version_id"])
    )


def _source_stage(identity: Dict[str, Any]) -> str:
    return (
        "outlier_treated"
        if _record_matches_identity(
            DATASTORE.meta.get("outlier_application"),
            identity,
        )
        else "registered_dataset"
    )


def _normalize_missing(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    for col in work.columns:
        if pd.api.types.is_object_dtype(work[col]) or pd.api.types.is_string_dtype(work[col]):
            text = work[col].astype("string")
            work.loc[text.str.strip().str.lower().isin(MISSING_STRINGS), col] = np.nan
    return work


def _feature_columns(df: pd.DataFrame) -> List[str]:
    return list(
        governed_predictor_authorization(
            df,
            target=DATASTORE.target,
            selected_columns=DATASTORE.get_selected_columns(),
        )["authorized_predictors"]
    )


def _authorization_with_full_source_exclusions(
    frame: pd.DataFrame,
) -> dict[str, Any]:
    authorization = governed_predictor_authorization(
        frame,
        target=DATASTORE.target,
        selected_columns=DATASTORE.get_selected_columns(),
    )
    raw = DATASTORE.raw_df
    if raw is None or raw.empty:
        return authorization
    full = governed_predictor_authorization(
        raw,
        target=DATASTORE.target,
        selected_columns=DATASTORE.get_selected_columns(),
    )
    return {
        **authorization,
        "target_source_excluded": sorted(
            set(authorization.get("target_source_excluded", []))
            | set(full.get("target_source_excluded", []))
        ),
        "excluded_predictors": {
            **full.get("excluded_predictors", {}),
            **authorization.get("excluded_predictors", {}),
        },
    }


def _is_numeric_like(series: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(series):
        return True
    non_missing = series.dropna()
    return bool(len(non_missing) and pd.to_numeric(non_missing, errors="coerce").notna().mean() >= 0.8)


def _display_dtype(series: pd.Series) -> str:
    return "float64" if _is_numeric_like(series) else str(series.dtype)


def _event_value(target: pd.Series, requested: Any) -> Any:
    if requested is not None and str(requested) != "":
        return requested
    return next((value for value in target.dropna().unique() if str(value) == "1"), None)


def _config_payload(config: Dict[str, MissingRule]) -> dict[str, dict[str, Any]]:
    return {key: value.dict() for key, value in sorted(config.items())}


def _config_signature(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _pre_missing_df(identity: Dict[str, Any]) -> pd.DataFrame:
    prior = DATASTORE.meta.get("outlier_application")
    if DATASTORE.meta.get("processed_stage") == "outliers" and DATASTORE.processed_df is not None:
        if not _record_matches_identity(prior, identity):
            raise HTTPException(
                status_code=409,
                detail=(
                    "The active outlier-treated frame is not bound to the exact "
                    "active Dataset Library version."
                ),
            )
        current = DATASTORE.get_active_df()
        if current is not None and not current.empty:
            return current

    source = DATASTORE.get_raw_active_df()
    if source is None or source.empty:
        raise HTTPException(status_code=400, detail="No full registered dataset is loaded.")
    if isinstance(prior, dict) and not _record_matches_identity(prior, identity):
        raise HTTPException(
            status_code=409,
            detail=(
                "The saved outlier treatment belongs to a different dataset "
                "identity. Reconfirm outlier treatment for the active version."
            ),
        )
    if _record_matches_identity(prior, identity) and isinstance(prior.get("config"), dict):
        try:
            source, _ = outlier_service.apply(
                source,
                config=prior["config"],
                global_method=str(prior.get("global_method") or "IQR_1_5"),
                target=DATASTORE.target,
                selected_columns=DATASTORE.get_selected_columns(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=f"The saved outlier treatment could not be reconstructed: {exc}") from exc
    return source


def _informative_missingness(
    feature: pd.Series,
    target: pd.Series | None,
    problem_type: str,
    event_value: Any,
) -> dict[str, Any]:
    missing = feature.isna()
    if target is None or not missing.any() or not (~missing).any():
        return {"informative": False, "missing_target_metric": None, "present_target_metric": None, "difference": None}
    if problem_type == "regression":
        numeric_target = pd.to_numeric(target, errors="coerce")
        missing_mean = numeric_target[missing].mean()
        present_mean = numeric_target[~missing].mean()
        scale = numeric_target.std(ddof=0)
        if pd.isna(missing_mean) or pd.isna(present_mean):
            return {"informative": False, "missing_target_metric": None, "present_target_metric": None, "difference": None}
        difference = float(missing_mean - present_mean)
        standardized = abs(difference) / float(scale) if pd.notna(scale) and float(scale) > 0 else 0.0
        return {
            "informative": standardized >= 0.1,
            "missing_target_metric": float(missing_mean),
            "present_target_metric": float(present_mean),
            "difference": difference,
            "standardized_difference": standardized,
        }

    if event_value is None:
        return {"informative": False, "missing_target_metric": None, "present_target_metric": None, "difference": None}
    valid = target.notna()
    event = target.astype(str) == str(event_value)
    missing_rate = float(event[missing & valid].mean()) if int((missing & valid).sum()) else None
    present_rate = float(event[(~missing) & valid].mean()) if int(((~missing) & valid).sum()) else None
    difference = missing_rate - present_rate if missing_rate is not None and present_rate is not None else None
    return {
        "informative": bool(difference is not None and abs(difference) >= 0.02),
        "missing_target_metric": missing_rate,
        "present_target_metric": present_rate,
        "difference": difference,
    }


def _number_label(value: float) -> str:
    magnitude = abs(float(value))
    if magnitude >= 1000:
        return f"{value:,.0f}"
    if magnitude >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


def _distribution_profile(values: pd.Series) -> dict[str, Any]:
    """Return a bounded, full-population distribution for the Missing Values UI.

    The histogram is aggregated on the backend rather than reconstructed from a
    browser sample. Bureau special values are deliberately removed from the
    ordinary-value bins and reported as their own governed population.
    """

    special_mask = bureau_special_mask(values)
    ordinary_source = values.mask(special_mask)
    missing_count = int(values.isna().sum())
    special_count = int(special_mask.sum())
    observed_count = int((values.notna() & ~special_mask).sum())

    if _is_numeric_like(values):
        numeric = pd.to_numeric(ordinary_source, errors="coerce")
        clean = numeric.dropna().astype(float)
        parse_failure_count = int((ordinary_source.notna() & numeric.isna()).sum())
        if clean.empty:
            return {
                "kind": "numeric",
                "bins": [],
                "observed_count": observed_count,
                "ordinary_numeric_count": 0,
                "missing_count": missing_count,
                "special_value_count": special_count,
                "parse_failure_count": parse_failure_count,
                "reference_cutoffs": None,
                "cutoff_semantics": "Ordinary-value cutoffs are unavailable because no numeric ordinary values were observed.",
            }

        distinct = int(clean.nunique())
        bin_count = max(1, min(14, distinct))
        counts, edges = np.histogram(clean.to_numpy(), bins=bin_count)
        bins = [
            {
                "label": f"{_number_label(float(edges[index]))} to {_number_label(float(edges[index + 1]))}",
                "lower": float(edges[index]),
                "upper": float(edges[index + 1]),
                "count": int(counts[index]),
            }
            for index in range(len(counts))
        ]
        first_quartile = float(clean.quantile(0.25))
        third_quartile = float(clean.quantile(0.75))
        spread = third_quartile - first_quartile
        return {
            "kind": "numeric",
            "bins": bins,
            "observed_count": observed_count,
            "ordinary_numeric_count": int(len(clean)),
            "missing_count": missing_count,
            "special_value_count": special_count,
            "parse_failure_count": parse_failure_count,
            "reference_cutoffs": {
                "lower": first_quartile - (1.5 * spread),
                "upper": third_quartile + (1.5 * spread),
                "method": "1.5 IQR ordinary-value reference",
            },
            "cutoff_semantics": (
                "Reference cutoffs describe the ordinary-value distribution inherited from the "
                "Outliers step. They are not missing-value treatments."
            ),
        }

    ordinary = ordinary_source.dropna().astype(str)
    counts = ordinary.value_counts(dropna=False).head(12)
    return {
        "kind": "categorical",
        "bins": [
            {
                "label": str(label),
                "lower": None,
                "upper": None,
                "count": int(count),
            }
            for label, count in counts.items()
        ],
        "observed_count": observed_count,
        "ordinary_numeric_count": None,
        "missing_count": missing_count,
        "special_value_count": special_count,
        "parse_failure_count": 0,
        "reference_cutoffs": None,
        "cutoff_semantics": "Low/high numeric cutoffs are not applicable to categorical predictors.",
    }


@router.get("/summary")
@_state_locked_read
def missing_summary(
    project_id: str = Query(...),
    event_value: Any = Query(default=None),
    problem_type: str | None = Query(default=None),
    expected_dataset_id: str | None = Query(default=None),
    expected_dataset_version_id: str | None = Query(default=None),
    dataset_id: str | None = Query(default=None),
    dataset_version_id: str | None = Query(default=None),
    dataset_version: str | None = Query(default=None),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "view")
    resolved_dataset_id, resolved_version_id, legacy_version = (
        coalesce_identity_expectations(
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_dataset_version_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
            legacy_dataset_version=dataset_version,
        )
    )
    identity = assert_expected_active_identity(
        project_id,
        expected_dataset_id=resolved_dataset_id,
        expected_dataset_version_id=resolved_version_id,
        legacy_dataset_version=legacy_version,
        require_expected=True,
        user=user,
    )
    work = _normalize_missing(_pre_missing_df(identity))
    target = DATASTORE.target if DATASTORE.target in work.columns else None
    y = work[target] if target else None
    resolved_problem = problem_type if problem_type in {"classification", "regression"} else "classification"
    resolved_event = _event_value(y, event_value) if y is not None and resolved_problem == "classification" else None
    event_rate = None
    if y is not None and resolved_event is not None:
        valid = y.notna()
        event_rate = float((y[valid].astype(str) == str(resolved_event)).mean()) if int(valid.sum()) else None

    stats: Dict[str, Any] = {}
    columns: List[Dict[str, Any]] = []
    total = int(len(work))
    feature_columns = _feature_columns(work)
    authorization = _authorization_with_full_source_exclusions(work)
    for col in feature_columns:
        feature = work[col]
        missing = int(feature.isna().sum())
        relationship = _informative_missingness(feature, y, resolved_problem, resolved_event)
        special_mask = bureau_special_mask(feature)
        numeric = pd.to_numeric(feature.mask(special_mask), errors="coerce")
        ordinary_numeric = numeric.dropna().astype(float)
        ordinary = feature.notna() & ~special_mask
        ordinary_mode = feature.loc[ordinary].mode(dropna=True)
        mode_value = ordinary_mode.iloc[0] if len(ordinary_mode) else None
        quantiles = (
            ordinary_numeric.quantile([0.25, 0.5, 0.75])
            if len(ordinary_numeric)
            else None
        )
        signal_metric = None
        association_status = "not_applicable"
        if y is not None:
            if resolved_problem == "classification":
                try:
                    signal_metric, resolved_event = information_value(
                        feature, y, resolved_event
                    )
                    association_status = "evaluated"
                except ValueError:
                    association_status = "target_definition_required"
            elif len(ordinary_numeric) >= 3:
                pairs = pd.DataFrame(
                    {
                        "feature": numeric,
                        "target": pd.to_numeric(y, errors="coerce"),
                    }
                ).dropna()
                if len(pairs) >= 3:
                    correlation = pairs["feature"].corr(pairs["target"])
                    if pd.notna(correlation):
                        signal_metric = float(correlation)
                        association_status = "evaluated"
        special_summary = bureau_special_summary(feature)
        stats[col] = {
            "missing": missing,
            "missingPct": float((missing / total) * 100) if total else 0.0,
            "total": total,
            "nonmissing_count": int(feature.notna().sum()),
            "observed_count": int(ordinary.sum()),
            "distinct_count": int(feature.nunique(dropna=True)),
            "mean": float(ordinary_numeric.mean()) if len(ordinary_numeric) else None,
            "mode": mode_value,
            "standard_deviation": (
                float(ordinary_numeric.std(ddof=0))
                if len(ordinary_numeric)
                else None
            ),
            "minimum": float(ordinary_numeric.min()) if len(ordinary_numeric) else None,
            "first_quartile": (
                float(quantiles.loc[0.25]) if quantiles is not None else None
            ),
            "median": float(quantiles.loc[0.5]) if quantiles is not None else None,
            "third_quartile": (
                float(quantiles.loc[0.75]) if quantiles is not None else None
            ),
            "maximum": float(ordinary_numeric.max()) if len(ordinary_numeric) else None,
            "information_value": (
                signal_metric if resolved_problem == "classification" else None
            ),
            "correlation_with_target": (
                signal_metric if resolved_problem == "regression" else None
            ),
            "association_status": association_status,
            "distribution": _distribution_profile(feature),
            **special_summary,
            **relationship,
        }
        columns.append({"name": col, "dtype": _display_dtype(work[col]), "role": "feature"})
    application = DATASTORE.meta.get("missing_application")
    validation = DATASTORE.meta.get("missing_validation")
    return json_safe({
        "ok": True,
        "scope": "full_dataset",
        **_identity_fields(identity),
        "rows": total,
        "columns": columns,
        "stats": stats,
        "target": target,
        "problem_type": resolved_problem,
        "event_value": resolved_event,
        "event_rate": event_rate,
        "rare_event": bool(event_rate is not None and event_rate < 0.05),
        "source_stage": _source_stage(identity),
        "application": (
            application
            if _record_matches_identity(application, identity)
            else None
        ),
        "validation": (
            validation
            if _record_matches_identity(validation, identity)
            else None
        ),
        "predictor_authorization": authorization,
    })


@router.post("/validate")
def validate_missing_values(
    request: MissingValidateRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Record a governed no-treatment decision without materializing a frame."""

    authorize_modeling_scope(user, request.project_id, "edit")
    scoped_store = DATASTORE.current()
    with scoped_store.state_lock:
        identity = _active_request_identity(request, user)
        input_revision = int(scoped_store.data_revision)
        work = _normalize_missing(_pre_missing_df(identity)).copy()
        features = _feature_columns(work)
        source_stage = _source_stage(identity)
        prior_validation = deepcopy(
            scoped_store.meta.get("missing_validation")
        )
    missing_cells = int(work[features].isna().sum().sum()) if features else 0
    if missing_cells:
        raise HTTPException(
            status_code=409,
            detail="Null values are present. Select and apply a governed treatment or explicitly preserve them.",
        )
    if (
        _record_matches_identity(prior_validation, identity)
        and prior_validation.get("source_stage") == source_stage
        and int(prior_validation.get("row_count") or -1) == int(len(work))
        and int(prior_validation.get("predictor_count") or -1) == len(features)
        and not DATASTORE.meta.get("missing_application")
    ):
        with scoped_store.state_lock:
            if int(scoped_store.data_revision) != input_revision:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "The governed dataset or preparation state changed "
                        "while missing values were being validated. Reload "
                        "the current plan before continuing."
                    ),
                )
        return json_safe({
            "ok": True,
            "scope": "full_dataset",
            **_identity_fields(identity),
            "validation": prior_validation,
            "idempotent": True,
        })
    validation = {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        **_identity_fields(identity),
        "source_stage": source_stage,
        "row_count": int(len(work)),
        "predictor_count": len(features),
        "missing_cells": 0,
        "strategy": "None",
        "status": "validated_no_treatment_required",
        "backend_materialization": False,
        "statement": "Validated, no treatment required.",
    }
    with scoped_store.state_lock:
        assert_expected_active_identity(
            request.project_id,
            expected_dataset_id=identity["dataset_id"],
            expected_dataset_version_id=identity["dataset_version_id"],
            user=user,
            store=scoped_store,
        )
        if int(scoped_store.data_revision) != input_revision:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The governed dataset or preparation state changed while "
                    "missing values were being validated. Reload and validate "
                    "again."
                ),
            )
        scoped_store.meta["missing_validation"] = validation
        scoped_store.meta.pop("missing_application", None)
        scoped_store.meta.pop("missing_config", None)
        invalidate_downstream_training_state(
            "The governed missing-value validation changed.",
            store=scoped_store,
            split_status="stale",
        )
    if not save_checkpoint():
        raise HTTPException(
            status_code=500,
            detail="Missing-value validation completed, but ATLAS could not persist the workflow checkpoint.",
        )
    return json_safe({
        "ok": True,
        "scope": "full_dataset",
        **_identity_fields(identity),
        "validation": validation,
    })


@router.post("/apply")
def apply_missing_values(request: MissingApplyRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    authorize_modeling_scope(user, request.project_id, "edit")
    scoped_store = DATASTORE.current()
    with scoped_store.state_lock:
        identity = _active_request_identity(request, user)
        input_revision = int(scoped_store.data_revision)
        source = _pre_missing_df(identity).copy()
        source_stage = _source_stage(identity)
        prior_application = deepcopy(
            scoped_store.meta.get("missing_application")
        )
    work = _normalize_missing(source)
    features = set(_feature_columns(work))
    before = int(work[list(features)].isna().sum().sum()) if features else 0
    if before == 0:
        raise HTTPException(
            status_code=409,
            detail="No null imputation is required for the current modeling population. Use validation instead of materialization.",
        )
    payload = _config_payload(request.config)
    config_signature = _config_signature(payload)
    if (
        _record_matches_identity(prior_application, identity)
        and prior_application.get("config_signature") == config_signature
        and prior_application.get("source_stage") == source_stage
        and DATASTORE.meta.get("processed_stage") == "missing_values"
        and DATASTORE.processed_df is not None
    ):
        with scoped_store.state_lock:
            if int(scoped_store.data_revision) != input_revision:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "The governed dataset or preparation state changed "
                        "while the missing-value plan was being evaluated. "
                        "Reload the current plan before continuing."
                    ),
                )
        return json_safe({
            "ok": True,
            "scope": "full_dataset",
            **_identity_fields(identity),
            "application": prior_application,
            "idempotent": True,
        })
    dropped_rows = 0
    applied: List[Dict[str, Any]] = []

    for col, rule in request.config.items():
        if col not in work.columns or col not in features:
            continue
        strategy = str(rule.strategy or "None").strip().lower()
        if strategy == "none":
            continue
        missing_before = int(work[col].isna().sum())
        if missing_before == 0:
            continue
        if strategy == "drop row":
            row_count = int(len(work))
            work = work.loc[~work[col].isna()].copy()
            removed = row_count - int(len(work))
            dropped_rows += removed
            applied.append({"feature": col, "strategy": rule.strategy, "filled": 0, "dropped_rows": removed})
            continue

        series = work[col]
        numeric = _is_numeric_like(series)
        if numeric:
            series = pd.to_numeric(series, errors="coerce")
            work[col] = series
        fill_value: Any = None
        if strategy == "mean" and numeric:
            fill_value = series.mean()
        elif strategy == "median" and numeric:
            fill_value = series.median()
        elif strategy in {"mode", "mean", "median"}:
            mode = series.dropna().mode()
            fill_value = mode.iloc[0] if len(mode) else ""
        elif strategy == "constant":
            fill_value = rule.constantValue if rule.constantValue is not None else ""
            if numeric:
                fill_value = pd.to_numeric(pd.Series([fill_value]), errors="coerce").iloc[0]
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported missing-value strategy '{rule.strategy}' for {col}.")
        if pd.isna(fill_value):
            raise HTTPException(status_code=400, detail=f"The selected strategy for {col} did not produce a valid fill value.")
        work[col] = series.fillna(fill_value)
        applied.append({"feature": col, "strategy": rule.strategy, "filled": missing_before, "value": str(fill_value)})

    application = {
        "applied_at": datetime.now(timezone.utc).isoformat(),
        **_identity_fields(identity),
        "config": payload,
        "config_signature": config_signature,
        "source_stage": source_stage,
        "rows_before": int(len(source)),
        "rows_after": int(len(work)),
        "missing_before": before,
        "missing_after": int(work[list(features)].isna().sum().sum()) if features else 0,
        "dropped_rows": int(dropped_rows),
        "treatments": applied,
    }
    with scoped_store.state_lock:
        assert_expected_active_identity(
            request.project_id,
            expected_dataset_id=identity["dataset_id"],
            expected_dataset_version_id=identity["dataset_version_id"],
            user=user,
            store=scoped_store,
        )
        if int(scoped_store.data_revision) != input_revision:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The governed dataset or preparation state changed while "
                    "missing-value treatments were being calculated. Reload "
                    "and apply the plan again."
                ),
            )
        scoped_store.set_processed(work)
        scoped_store.meta["processed_stage"] = "missing_values"
        scoped_store.meta["missing_config"] = payload
        scoped_store.meta["missing_application"] = application
        scoped_store.meta.pop("missing_validation", None)
        invalidate_downstream_training_state(
            "The governed missing-value treatment changed.",
            store=scoped_store,
            split_status="stale",
        )
    if not save_checkpoint():
        raise HTTPException(status_code=500, detail="Missing-value treatments were applied, but ATLAS could not persist the workflow checkpoint.")
    return json_safe({
        "ok": True,
        "scope": "full_dataset",
        **_identity_fields(identity),
        "application": application,
    })

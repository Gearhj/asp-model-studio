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

from ..analysis_partition.types import AnalysisPartitionError
from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from ..core.modeling_scope import authorize_modeling_scope
from ..core.pretraining_invalidation import invalidate_downstream_training_state
from ..core.result_store import RESULTS
from ..core.session_checkpoint import save_checkpoint
from ..datasets.dataset_identity import (
    assert_expected_active_identity,
    coalesce_identity_expectations,
)
from ..security.security_store import require_user
from .development_scope import (
    DevelopmentAnalysisScope,
    resolve_development_analysis_scope,
    scope_http_exception,
)
from .outlier_service import outlier_service
from .feature_profile_service import information_value
from .predictor_authorization import (
    bureau_special_mask,
    bureau_special_summary,
)
from .preprocessing_contract import (
    PREPROCESSING_CONTRACT_VERSION,
    FIT_SCOPE_DEVELOPMENT_PREVIEW,
    analytical_type,
    apply_missing_recipe,
    apply_outlier_recipe,
    assert_mutation_expectations,
    build_preprocessing_policy_record,
    capture_preprocessing_mutation_state,
    classify_preprocessing_record,
    decode_typed_scalar,
    fit_metadata,
    fit_missing_recipe,
    governed_special_mask,
    governed_special_values_for_feature,
    normalize_true_missing,
    quarantine_preprocessing_state,
    resolve_special_value_contract,
    restore_preprocessing_mutation_state,
    scope_lineage,
    special_mask,
)


router = APIRouter()


def _state_locked_read(function):
    """Authorize project scope before resolving and locking its store."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        project_id = kwargs.get("project_id")
        if project_id is None and args:
            project_id = args[0]
        user = kwargs.get("user") or {}
        authorize_modeling_scope(user, project_id, "view")
        scoped_store = DATASTORE.current()
        with scoped_store.state_lock:
            return function(*args, **kwargs)

    return wrapped
class MissingRule(BaseModel):
    strategy: str = "None"
    constantValue: Optional[Any] = None
    rationale: str = ""


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
    analysis_partition_id: str | None = None
    analysis_partition_revision: int | None = None
    preprocessing_contract_version: int | None = None
    expected_predictor_authorization_id: str | None = None
    expected_special_value_review_id: str | None = None
    expected_special_value_review_revision: int | None = None
    analytical_types: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    missing_tokens: Dict[str, List[str]] = Field(default_factory=dict)


class MissingValidateRequest(BaseModel):
    project_id: str
    event_value: Any = None
    problem_type: str | None = None
    expected_dataset_id: str | None = None
    expected_dataset_version_id: str | None = None
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    dataset_version: str | None = None
    analysis_partition_id: str | None = None
    analysis_partition_revision: int | None = None
    preprocessing_contract_version: int | None = None
    expected_predictor_authorization_id: str | None = None
    expected_special_value_review_id: str | None = None
    expected_special_value_review_revision: int | None = None


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


def _development_scope(
    identity: Dict[str, Any],
    scoped_store: Any,
    *,
    requested_target: Any = None,
    requested_event_value: Any = None,
    requested_problem_type: Any = None,
    analysis_partition_id: Any = None,
    analysis_partition_revision: Any = None,
    actor: Any = None,
) -> DevelopmentAnalysisScope:
    try:
        return resolve_development_analysis_scope(
            scoped_store,
            identity,
            requested_target=requested_target,
            requested_event_value=requested_event_value,
            requested_problem_type=requested_problem_type,
            expected_analysis_partition_id=analysis_partition_id,
            expected_analysis_partition_revision=analysis_partition_revision,
            actor=actor,
        )
    except AnalysisPartitionError as exc:
        raise scope_http_exception(exc) from exc


def _record_matches_scope(
    record: Any,
    identity: Dict[str, Any],
    scope: DevelopmentAnalysisScope,
) -> bool:
    special_contract = resolve_special_value_contract(
        identity=identity,
        scope=scope,
        store=DATASTORE.current(),
    )
    status, _ = classify_preprocessing_record(
        record,
        lineage=scope_lineage(scope, special_contract),
    )
    return status == "current"


def _full_dataset_application_metadata(
    scope: DevelopmentAnalysisScope,
) -> Dict[str, Any]:
    """Describe Development preview approval without holdout application."""

    return {
        **scope.metadata(),
        "scope": "development_population",
        "fit_scope": "development_preview",
        "application_scope": "none_prelock",
        "materialization_scope": "none",
        "application_source_population": None,
        "backend_materialization": False,
        "processed_frame_materialized": False,
        "sealed_holdout_transformed": False,
    }


def _public_application(record: Any) -> Any:
    """Return persisted v2 state verbatim; legacy records are quarantined."""

    return deepcopy(record) if isinstance(record, dict) else record


def _source_stage(identity: Dict[str, Any]) -> str:
    return (
        "outlier_policy_approved"
        if _record_matches_identity(
            DATASTORE.meta.get("outlier_application"),
            identity,
        )
        and int(
            (DATASTORE.meta.get("outlier_application") or {}).get(
                "preprocessing_contract_version"
            )
            or 0
        )
        == PREPROCESSING_CONTRACT_VERSION
        else "registered_dataset"
    )


def _normalize_missing(df: pd.DataFrame) -> pd.DataFrame:
    # V2 does not globally reinterpret legitimate category labels such as
    # "None" or "Missing". Feature-specific governed tokens are applied by
    # the fitted recipe when explicitly present in approved policy.
    return normalize_true_missing(df)


def _feature_columns(
    df: pd.DataFrame,
    authorization: dict[str, Any],
) -> List[str]:
    return [
        str(value)
        for value in authorization.get("authorized_predictors", [])
        if str(value) in df.columns
    ]


def _authorization_with_full_source_exclusions(
    frame: pd.DataFrame,
    authorization: dict[str, Any],
) -> dict[str, Any]:
    # The exact durable Data Acquisition manifest is the only authorization
    # source. Re-running deterministic target-source detection on the full
    # population here would inspect the sealed holdout target.
    return dict(authorization)


def _is_numeric_like(series: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(series):
        return True
    non_missing = series.dropna()
    return bool(len(non_missing) and pd.to_numeric(non_missing, errors="coerce").notna().mean() >= 0.8)


def _display_dtype(series: pd.Series) -> str:
    return "float64" if _is_numeric_like(series) else str(series.dtype)


def _config_payload(config: Dict[str, MissingRule]) -> dict[str, dict[str, Any]]:
    return {key: value.model_dump() for key, value in sorted(config.items())}


def _config_signature(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _structural_missing_count(
    frame: pd.DataFrame,
    features: List[str],
    *,
    special_value_contract: dict[str, Any],
    governed_tokens: dict[str, List[str]] | None = None,
) -> int:
    """Count governed null semantics without transforming the registered frame."""

    total = 0
    for feature in features:
        series = frame[feature]
        missing = series.isna().copy()
        tokens = {
            str(value).strip().casefold()
            for value in (governed_tokens or {}).get(feature, [])
        }
        if tokens:
            rendered = series.astype("string").str.strip().str.casefold()
            token_missing = rendered.isin(tokens).fillna(False)
            token_missing = token_missing & ~special_mask(
                series, feature, special_value_contract
            )
            missing = missing | token_missing
        total += int(missing.sum())
    return total


def _missingness_counts(
    frame: pd.DataFrame,
    features: List[str],
) -> dict[str, Any]:
    matrix = frame[features].isna() if features else None
    affected = matrix.any(axis=1) if matrix is not None else None
    maximum = (
        int(matrix.sum(axis=1).max())
        if matrix is not None and len(matrix)
        else 0
    )
    return {
        "flagged_cell_count": int(matrix.sum().sum())
        if matrix is not None
        else 0,
        "affected_row_count": int(affected.sum())
        if affected is not None
        else 0,
        "affected_row_rate": float(affected.mean())
        if affected is not None and len(affected)
        else 0.0,
        "affected_predictor_count": int(matrix.any(axis=0).sum())
        if matrix is not None
        else 0,
        "mean_flagged_features_per_affected_row": (
            float(matrix.sum(axis=1)[affected].mean())
            if matrix is not None and affected is not None and bool(affected.any())
            else 0.0
        ),
        "max_flagged_features_per_row": maximum,
        "maximum_flagged_features_on_one_row": maximum,
    }


def _pre_missing_df(
    identity: Dict[str, Any],
    *,
    authorization: dict[str, Any],
    target: str,
) -> pd.DataFrame:
    source = DATASTORE.get_raw_active_df(include_target=False)
    if source is None or source.empty:
        raise HTTPException(status_code=400, detail="No full registered dataset is loaded.")
    # Step04 policies do not globally materialize the sealed holdout. Missing
    # preview fitting applies the Development outlier recipe only to the exact
    # Development frame; the structural source remains immutable here.
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


def _distribution_profile(
    values: pd.Series,
    *,
    feature: str | None = None,
    special_value_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a bounded, full-population distribution for the Missing Values UI.

    The histogram is aggregated on the backend rather than reconstructed from a
    browser sample. Bureau special values are deliberately removed from the
    ordinary-value bins and reported as their own governed population.
    """

    protected_specials = (
        special_mask(values, feature, special_value_contract)
        if feature is not None and special_value_contract is not None
        else bureau_special_mask(values)
    )
    governed_specials = (
        governed_special_mask(values, feature, special_value_contract)
        if feature is not None and special_value_contract is not None
        else protected_specials
    )
    ordinary_source = values.mask(protected_specials)
    missing_count = int(values.isna().sum())
    special_count = int(governed_specials.sum())
    observed_count = int((values.notna() & ~protected_specials).sum())

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
                "protected_sentinel_excluded_count": int(protected_specials.sum()),
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
            "protected_sentinel_excluded_count": int(protected_specials.sum()),
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
        "protected_sentinel_excluded_count": int(protected_specials.sum()),
        "parse_failure_count": 0,
        "reference_cutoffs": None,
        "cutoff_semantics": "Low/high numeric cutoffs are not applicable to categorical predictors.",
    }


@router.get("/summary")
@_state_locked_read
def missing_summary(
    project_id: str = Query(...),
    target: str | None = Query(default=None),
    event_value: Any = Query(default=None),
    problem_type: str | None = Query(default=None),
    expected_dataset_id: str | None = Query(default=None),
    expected_dataset_version_id: str | None = Query(default=None),
    dataset_id: str | None = Query(default=None),
    dataset_version_id: str | None = Query(default=None),
    dataset_version: str | None = Query(default=None),
    analysis_partition_id: str | None = Query(default=None),
    analysis_partition_revision: int | None = Query(default=None),
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
    scoped_store = DATASTORE.current()
    scope = _development_scope(
        identity,
        scoped_store,
        requested_target=target,
        requested_event_value=event_value,
        requested_problem_type=problem_type,
        analysis_partition_id=analysis_partition_id,
        analysis_partition_revision=analysis_partition_revision,
        actor=user.get("userId"),
    )
    authorization = dict(scope.predictor_authorization)
    special_contract = resolve_special_value_contract(
        identity=identity,
        scope=scope,
        store=scoped_store,
    )
    lineage = scope_lineage(scope, special_contract)
    application = scoped_store.meta.get("missing_application")
    validation = scoped_store.meta.get("missing_validation")
    application_status, application_reasons = classify_preprocessing_record(
        application,
        lineage=lineage,
    )
    validation_status, validation_reasons = classify_preprocessing_record(
        validation,
        lineage=lineage,
    )
    stale_reasons = application_reasons or validation_reasons
    work = _normalize_missing(
        _pre_missing_df(
            identity,
            authorization=authorization,
            target=scope.target,
        ).drop(columns=[scope.target], errors="ignore")
    )
    development = _normalize_missing(
        scope.materialize_aligned_features(work)
    ).reset_index(drop=True)
    outlier_application = scoped_store.meta.get("outlier_application")
    outlier_status, _ = classify_preprocessing_record(
        outlier_application,
        lineage=lineage,
    )
    if outlier_status == "current" and isinstance(
        outlier_application.get("development_preview_fit"), dict
    ):
        development, _ = apply_outlier_recipe(
            development,
            recipe=outlier_application["development_preview_fit"],
            target=None,
            special_value_contract=special_contract,
        )
    y = scope.development_target.reset_index(drop=True)
    resolved_problem = scope.problem_type
    resolved_event = scope.event_value
    event_rate = None
    if resolved_event is not None:
        valid = y.notna()
        event_rate = float((y[valid].astype(str) == str(resolved_event)).mean()) if int(valid.sum()) else None

    stats: Dict[str, Any] = {}
    columns: List[Dict[str, Any]] = []
    registered_total = int(len(work))
    total = int(len(development))
    feature_columns = _feature_columns(work, authorization)
    authorization = _authorization_with_full_source_exclusions(
        work,
        authorization,
    )
    for col in feature_columns:
        feature = work[col]
        development_feature = development[col]
        missing = int(development_feature.isna().sum())
        relationship = _informative_missingness(
            development_feature,
            y,
            resolved_problem,
            resolved_event,
        )
        protected_special_mask = special_mask(
            feature, col, special_contract
        )
        development_protected_special_mask = special_mask(
            development_feature, col, special_contract
        )
        governed_special_value_mask = governed_special_mask(
            feature, col, special_contract
        )
        development_governed_special_mask = governed_special_mask(
            development_feature, col, special_contract
        )
        numeric = pd.to_numeric(
            development_feature.mask(development_protected_special_mask),
            errors="coerce",
        )
        ordinary_numeric = numeric.dropna().astype(float)
        registered_ordinary = feature.notna() & ~protected_special_mask
        development_ordinary = (
            development_feature.notna() & ~development_protected_special_mask
        )
        ordinary_mode = development_feature.loc[
            development_ordinary
        ].mode(dropna=True)
        mode_value = ordinary_mode.iloc[0] if len(ordinary_mode) else None
        quantiles = (
            ordinary_numeric.quantile([0.25, 0.5, 0.75])
            if len(ordinary_numeric)
            else None
        )
        signal_metric = None
        association_status = "not_applicable"
        if resolved_problem == "classification":
            try:
                signal_metric, resolved_event = information_value(
                    development_feature,
                    y,
                    resolved_event,
                )
                association_status = "evaluated"
            except ValueError:
                association_status = "target_definition_required"
        else:
            pairs = pd.DataFrame(
                {
                    "feature": pd.to_numeric(
                        development_feature, errors="coerce"
                    ),
                    "target": pd.to_numeric(y, errors="coerce"),
                }
            ).dropna()
            if len(pairs) >= 3:
                correlation = pairs["feature"].corr(pairs["target"])
                if pd.notna(correlation):
                    signal_metric = float(correlation)
                    association_status = "evaluated"
        special_values = governed_special_values_for_feature(
            col, special_contract
        )
        special_summary = {
            "special_value_count": int(development_governed_special_mask.sum()),
            "special_value_rate": int(development_governed_special_mask.sum())
            / max(int(development_feature.notna().sum()), 1),
            "protected_sentinel_excluded_count": int(
                development_protected_special_mask.sum()
            ),
            "special_values": {
                str(value): int(
                    special_mask(
                        development_feature,
                        col,
                        {"features": {col: {"values": [value]}}},
                    ).sum()
                )
                for value in special_values
            },
        }
        profile = analytical_type(development_feature)
        stats[col] = {
            "missing": missing,
            "missingPct": float((missing / total) * 100) if total else 0.0,
            "total": total,
            "nonmissing_count": int(development_feature.notna().sum()),
            "observed_count": int(development_ordinary.sum()),
            "distinct_count": int(development_feature.nunique(dropna=True)),
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
            "descriptive_scope": "development_preview_fit",
            "structural_distribution_scope": "registered_structural_node",
            "analytical_type": profile["analytical_type"],
            "classification_source": profile["classification_source"],
            "classification_requires_review": profile[
                "classification_requires_review"
            ],
            "distribution": _distribution_profile(
                development_feature,
                feature=col,
                special_value_contract=special_contract,
            ),
            "registered_structural": {
                "scope": "registered_structural_population",
                "row_count": registered_total,
                "missing": int(feature.isna().sum()),
                "missingPct": (
                    float(feature.isna().mean() * 100)
                    if registered_total
                    else 0.0
                ),
                "nonmissing_count": int(feature.notna().sum()),
                "observed_count": int(registered_ordinary.sum()),
                "distinct_count": int(feature.nunique(dropna=True)),
                "special_value_count": int(governed_special_value_mask.sum()),
                "special_value_rate": int(governed_special_value_mask.sum())
                / max(int(feature.notna().sum()), 1),
                "protected_sentinel_excluded_count": int(
                    protected_special_mask.sum()
                ),
                "special_values": {
                    str(value): int(
                        special_mask(
                            feature,
                            col,
                            {"features": {col: {"values": [value]}}},
                        ).sum()
                    )
                    for value in special_values
                },
                "distribution": _distribution_profile(
                    feature,
                    feature=col,
                    special_value_contract=special_contract,
                ),
            },
            **special_summary,
            **relationship,
        }
        columns.append({"name": col, "dtype": _display_dtype(work[col]), "role": "feature"})
    development_features = [
        feature for feature in feature_columns if feature in development.columns
    ]
    counts = _missingness_counts(development, development_features)
    registered_structural_counts = _missingness_counts(work, feature_columns)
    return json_safe({
        "ok": True,
        **_identity_fields(identity),
        **scope.metadata(),
        "rows": total,
        "row_count": total,
        "development_rows": int(len(y)),
        "registered_population_rows": registered_total,
        "registered_structural_row_count": registered_total,
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "preprocessing_lineage": lineage,
        "special_value_contract": special_contract,
        "counts": counts,
        "registered_structural_counts": registered_structural_counts,
        "columns": columns,
        "stats": stats,
        "target": scope.target,
        "problem_type": resolved_problem,
        "event_value": resolved_event,
        "event_rate": event_rate,
        "rare_event": bool(event_rate is not None and event_rate < 0.05),
        "source_stage": _source_stage(identity),
        "application": (
            _public_application(application)
            if application_status == "current"
            else None
        ),
        "validation": (
            validation
            if validation_status == "current"
            else None
        ),
        "legacy_artifact_status": (
            application_status
            if application_status.startswith("stale")
            else validation_status
            if validation_status.startswith("stale")
            else None
        ),
        "legacy_artifact_reasons": stale_reasons,
        "predictor_authorization": authorization,
        "final_holdout_predictors_in_structural_profile": True,
        "final_holdout_predictors_included_in_structural_profile": True,
    })


@router.post("/validate")
def validate_missing_values(
    request: MissingValidateRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Approve an explicit active NONE policy when governed null count is zero."""

    authorize_modeling_scope(user, request.project_id, "edit")
    scoped_store = DATASTORE.current()
    with scoped_store.state_lock:
        identity = _active_request_identity(request, user)
        scope = _development_scope(
            identity,
            scoped_store,
            requested_event_value=request.event_value,
            requested_problem_type=request.problem_type,
            analysis_partition_id=request.analysis_partition_id,
            analysis_partition_revision=request.analysis_partition_revision,
            actor=user.get("userId"),
        )
        special_contract = resolve_special_value_contract(
            identity=identity, scope=scope, store=scoped_store
        )
        lineage = scope_lineage(scope, special_contract)
        try:
            assert_mutation_expectations(request, lineage=lineage)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        source = _pre_missing_df(
            identity,
            authorization=scope.predictor_authorization,
            target=scope.target,
        ).drop(columns=[scope.target], errors="ignore")
        features = _feature_columns(source, scope.predictor_authorization)
        registered_row_count = int(len(source))
        missing_cells = _structural_missing_count(
            source,
            features,
            special_value_contract=special_contract,
        )
        outlier_application = deepcopy(
            scoped_store.meta.get("outlier_application")
        )
        prior_validation = deepcopy(
            scoped_store.meta.get("missing_validation")
        )
        prior_application = deepcopy(
            scoped_store.meta.get("missing_application")
        )
        previous_combined = deepcopy(
            scoped_store.meta.get("preprocessing_policy")
        )
        input_revision = int(scoped_store.data_revision)

    outlier_status, _ = classify_preprocessing_record(
        outlier_application, lineage=lineage
    )
    if outlier_status != "current" or not isinstance(
        (outlier_application or {}).get("development_preview_fit"), dict
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Approve the current preprocessing-v2 Outliers policy before "
                "confirming Missing Values."
            ),
        )
    if missing_cells:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{missing_cells} governed true-null predictor cell(s) are "
                "present. Select and apply an executable treatment."
            ),
        )

    missing_policy = {
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "artifact_kind": "approved_missing_policy",
        "status": "approved",
        "mode": "active_none_zero_null",
        "active_treatment": "NONE",
        "default_strategy": "NONE",
        "config": {},
        "analytical_types": {},
        "missing_tokens": {},
        "zero_null_validated": True,
        "true_null_cell_count": 0,
        "materialization_required": False,
        "processed_frame_created": False,
        "registered_structural_missing_count": 0,
    }
    policy_signature = _config_signature(missing_policy)
    missing_policy["missing_policy_id"] = f"mp-{policy_signature}"
    previous_missing_policy = (
        (previous_combined or {}).get("missing_policy")
        if isinstance((previous_combined or {}).get("missing_policy"), dict)
        else {}
    )
    missing_policy["missing_policy_revision"] = (
        int(previous_missing_policy.get("missing_policy_revision") or 1)
        if previous_missing_policy.get("missing_policy_id")
        == missing_policy["missing_policy_id"]
        else int(previous_missing_policy.get("missing_policy_revision") or 0)
        + 1
    )

    prior_status, _ = classify_preprocessing_record(
        prior_validation, lineage=lineage
    )
    combined_status, _ = classify_preprocessing_record(
        previous_combined, lineage=lineage
    )
    if (
        prior_status == "current"
        and not isinstance(prior_application, dict)
        and prior_validation.get("missing_policy_id")
        == missing_policy["missing_policy_id"]
        and combined_status == "current"
        and previous_combined.get("status") == "approved"
    ):
        with scoped_store.state_lock:
            if int(scoped_store.data_revision) != input_revision:
                raise HTTPException(
                    status_code=409,
                    detail="The preparation authority changed; reload and validate again.",
                )
        return json_safe(
            {
                "ok": True,
                **_identity_fields(identity),
                **_full_dataset_application_metadata(scope),
                "validation": prior_validation,
                "preprocessing_policy": previous_combined,
                "idempotent": True,
            }
        )

    try:
        development_after_outliers, _ = apply_outlier_recipe(
            scope.development_features,
            recipe=outlier_application["development_preview_fit"],
            special_value_contract=special_contract,
        )
        preview_fit = fit_missing_recipe(
            development_after_outliers,
            policy=missing_policy,
            fit=fit_metadata(
                fit_scope=FIT_SCOPE_DEVELOPMENT_PREVIEW,
                population_id=str(
                    scope.partition.get("development_partition_id")
                ),
                population_count=len(development_after_outliers),
                lineage=lineage,
                actor=str(user.get("userId") or "atlas-user"),
                application_scope="development_population_preview",
                application_population_id=str(
                    scope.partition.get("development_partition_id")
                ),
                application_population_rows=len(development_after_outliers),
                evidence_references=[],
            ),
            special_value_contract=special_contract,
        )
        _, preview = apply_missing_recipe(
            development_after_outliers,
            recipe=preview_fit,
            special_value_contract=special_contract,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    validated_at = datetime.now(timezone.utc).isoformat()
    validation = {
        "validated_at": validated_at,
        **_identity_fields(identity),
        **_full_dataset_application_metadata(scope),
        **lineage,
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "artifact_kind": "missing_policy_validation",
        "state": "approved",
        "status": "validated_no_treatment_required",
        "source_stage": "outlier_policy_approved",
        "row_count": int(len(development_after_outliers)),
        "registered_population_row_count": registered_row_count,
        "predictor_count": len(features),
        "missing_cells": 0,
        "strategy": "NONE",
        "missing_policy_id": missing_policy["missing_policy_id"],
        "outlier_policy_id": outlier_application["approved_policy"].get(
            "outlier_policy_id"
        ),
        "approved_policy": missing_policy,
        "development_preview_fit": preview_fit,
        "development_preview": preview,
        "counts": preview["counts"],
        "backend_materialization": False,
        "processed_frame_materialized": False,
        "sealed_holdout_transformed": False,
        "final_holdout_predictors_in_structural_profile": True,
        "final_holdout_predictors_included_in_structural_profile": True,
        "final_holdout_used_for_fit": False,
        "statement": "Active NONE policy validated: no governed true nulls.",
    }
    combined_policy = build_preprocessing_policy_record(
        lineage=lineage,
        special_value_contract=special_contract,
        actor=str(user.get("userId") or "atlas-user"),
        outlier_policy=outlier_application["approved_policy"],
        missing_policy=missing_policy,
        outlier_development_preview_fit=outlier_application[
            "development_preview_fit"
        ],
        missing_development_preview_fit=preview_fit,
        previous=previous_combined,
        approved_at=validated_at,
    )

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
                detail="The preparation authority changed; reload and validate again.",
            )
        result_store = RESULTS.current()
        rollback_snapshot = capture_preprocessing_mutation_state(
            scoped_store, result_store
        )
        quarantine_preprocessing_state(
            scoped_store,
            keys=(
                "missing_application",
                "missing_validation",
                "missing_policy",
                "missing_config",
                "preprocessing_policy",
                "feature_manifest",
                "feature_preview",
                "materialized_feature_names",
                "processed_stage",
            ),
            reason="A new governed missing-value NONE policy superseded dependent state.",
        )
        scoped_store.processed_df = None
        scoped_store.meta["missing_policy"] = missing_policy
        scoped_store.meta["missing_validation"] = validation
        scoped_store.meta["preprocessing_policy"] = combined_policy
        scoped_store.meta["preprocessing_state_status"] = "current"
        scoped_store.meta.pop("preprocessing_state_reason", None)
        invalidate_downstream_training_state(
            "The governed missing-value validation changed.",
            store=scoped_store,
            split_status="stale",
        )
        if not save_checkpoint():
            restore_preprocessing_mutation_state(
                scoped_store, result_store, rollback_snapshot
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "Missing-value NONE approval could not be persisted; "
                    "the in-memory workflow state was rolled back."
                ),
            )
    return json_safe(
        {
            "ok": True,
            **_identity_fields(identity),
            **_full_dataset_application_metadata(scope),
            "validation": validation,
            "preprocessing_policy": combined_policy,
        }
    )


@router.post("/apply")
def apply_missing_values(request: MissingApplyRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    authorize_modeling_scope(user, request.project_id, "edit")
    scoped_store = DATASTORE.current()
    with scoped_store.state_lock:
        identity = _active_request_identity(request, user)
        scope = _development_scope(
            identity,
            scoped_store,
            requested_event_value=request.event_value,
            requested_problem_type=request.problem_type,
            analysis_partition_id=request.analysis_partition_id,
            analysis_partition_revision=request.analysis_partition_revision,
            actor=user.get("userId"),
        )
        special_contract = resolve_special_value_contract(
            identity=identity, scope=scope, store=scoped_store
        )
        lineage = scope_lineage(scope, special_contract)
        try:
            assert_mutation_expectations(request, lineage=lineage)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        registered = _pre_missing_df(
            identity,
            authorization=scope.predictor_authorization,
            target=scope.target,
        ).drop(columns=[scope.target], errors="ignore")
        feature_list = _feature_columns(
            registered, scope.predictor_authorization
        )
        registered_row_count = int(len(registered))
        outlier_application = deepcopy(
            scoped_store.meta.get("outlier_application")
        )
        prior_application = deepcopy(
            scoped_store.meta.get("missing_application")
        )
        previous_combined = deepcopy(
            scoped_store.meta.get("preprocessing_policy")
        )
        input_revision = int(scoped_store.data_revision)

    outlier_status, _ = classify_preprocessing_record(
        outlier_application, lineage=lineage
    )
    if outlier_status != "current" or not isinstance(
        (outlier_application or {}).get("development_preview_fit"), dict
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Approve the current preprocessing-v2 Outliers policy before "
                "approving Missing Values."
            ),
        )

    normalized_config = {
        feature: (
            request.config[feature].model_dump()
            if feature in request.config
            else MissingRule().model_dump()
        )
        for feature in feature_list
    }
    normalized_tokens = {
        feature: [str(value) for value in request.missing_tokens.get(feature, [])]
        for feature in feature_list
        if request.missing_tokens.get(feature)
    }
    normalized_types = {
        feature: dict(request.analytical_types.get(feature) or {})
        for feature in feature_list
        if isinstance(request.analytical_types.get(feature), dict)
    }
    registered_missing_before = _structural_missing_count(
        registered,
        feature_list,
        special_value_contract=special_contract,
        governed_tokens=normalized_tokens,
    )
    if registered_missing_before == 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "No governed true-null treatment is active. Validate the "
                "zero-null NONE policy instead."
            ),
        )
    development_policy_null_count = _structural_missing_count(
        scope.development_features,
        [
            feature
            for feature in feature_list
            if feature in scope.development_features.columns
        ],
        special_value_contract=special_contract,
        governed_tokens=normalized_tokens,
    )
    if development_policy_null_count == 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "Governed nulls exist outside Development, but no missing "
                "estimator can be fit without holdout influence. Revise the "
                "registered population and seal a new Analysis Partition."
            ),
        )

    missing_policy = {
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "artifact_kind": "approved_missing_policy",
        "status": "approved",
        "mode": "fitted_imputation",
        "active_treatment": "FEATURE_SPECIFIC",
        "config": normalized_config,
        "analytical_types": normalized_types,
        "missing_tokens": normalized_tokens,
        "zero_null_validated": False,
        "true_null_cell_count": development_policy_null_count,
        "materialization_required": False,
        "processed_frame_created": False,
        "execution_scope": "fold_and_final_fit_only",
    }
    config_signature = _config_signature(missing_policy)
    missing_policy["missing_policy_id"] = f"mp-{config_signature}"
    previous_missing_policy = (
        (previous_combined or {}).get("missing_policy")
        if isinstance((previous_combined or {}).get("missing_policy"), dict)
        else {}
    )
    missing_policy["missing_policy_revision"] = (
        int(previous_missing_policy.get("missing_policy_revision") or 1)
        if previous_missing_policy.get("missing_policy_id")
        == missing_policy["missing_policy_id"]
        else int(previous_missing_policy.get("missing_policy_revision") or 0)
        + 1
    )
    prior_status, _ = classify_preprocessing_record(
        prior_application, lineage=lineage
    )
    if (
        prior_status == "current"
        and prior_application.get("config_signature") == config_signature
        and isinstance(previous_combined, dict)
        and previous_combined.get("status") == "approved"
    ):
        with scoped_store.state_lock:
            if int(scoped_store.data_revision) != input_revision:
                raise HTTPException(
                    status_code=409,
                    detail="The preparation authority changed; reload the plan.",
                )
        return json_safe(
            {
                "ok": True,
                **_identity_fields(identity),
                **_full_dataset_application_metadata(scope),
                "application": _public_application(prior_application),
                "preprocessing_policy": previous_combined,
                "idempotent": True,
            }
        )

    try:
        development_after_outliers, _ = apply_outlier_recipe(
            scope.development_features,
            recipe=outlier_application["development_preview_fit"],
            special_value_contract=special_contract,
        )
        development_missing_before = _structural_missing_count(
            development_after_outliers,
            [
                feature
                for feature in feature_list
                if feature in development_after_outliers.columns
            ],
            special_value_contract=special_contract,
            governed_tokens=normalized_tokens,
        )
        if development_missing_before != development_policy_null_count:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The Development missing-value decision population changed "
                    "while the preview was being prepared. Reload the plan."
                ),
            )
        preview_fit = fit_missing_recipe(
            development_after_outliers,
            policy=missing_policy,
            fit=fit_metadata(
                fit_scope=FIT_SCOPE_DEVELOPMENT_PREVIEW,
                population_id=str(
                    scope.partition.get("development_partition_id")
                ),
                population_count=len(development_after_outliers),
                lineage=lineage,
                actor=str(user.get("userId") or "atlas-user"),
                application_scope="development_population_preview",
                application_population_id=str(
                    scope.partition.get("development_partition_id")
                ),
                application_population_rows=len(development_after_outliers),
                evidence_references=[],
            ),
            special_value_contract=special_contract,
        )
        preview_frame, preview = apply_missing_recipe(
            development_after_outliers,
            recipe=preview_fit,
            special_value_contract=special_contract,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    remaining = int(
        preview_frame[
            [
                feature
                for feature in feature_list
                if feature in preview_frame.columns
            ]
        ].isna().sum().sum()
    )
    if remaining:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{remaining} governed true-null Development cell(s) remain. "
                "Every active null requires an executable fitted treatment."
            ),
        )

    applied_at = datetime.now(timezone.utc).isoformat()
    application = {
        "applied_at": applied_at,
        **_identity_fields(identity),
        **_full_dataset_application_metadata(scope),
        **lineage,
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "artifact_kind": "missing_policy_approval",
        "state": "approved",
        "source_stage": "outlier_policy_approved",
        "config": normalized_config,
        "config_signature": config_signature,
        "approved_policy": missing_policy,
        "outlier_policy_id": outlier_application["approved_policy"].get(
            "outlier_policy_id"
        ),
        "development_preview_fit": preview_fit,
        "development_preview": preview,
        "counts": preview["counts"],
        "row_count": int(len(development_after_outliers)),
        "registered_population_row_count": registered_row_count,
        "registered_structural_missing_count": registered_missing_before,
        "development_missing_before": development_missing_before,
        "development_missing_after": remaining,
        "dropped_rows": 0,
        "backend_materialization": False,
        "processed_frame_materialized": False,
        "sealed_holdout_transformed": False,
        "final_holdout_predictors_in_structural_profile": True,
        "final_holdout_predictors_included_in_structural_profile": True,
        "final_holdout_used_for_fit": False,
    }
    combined_policy = build_preprocessing_policy_record(
        lineage=lineage,
        special_value_contract=special_contract,
        actor=str(user.get("userId") or "atlas-user"),
        outlier_policy=outlier_application["approved_policy"],
        missing_policy=missing_policy,
        outlier_development_preview_fit=outlier_application[
            "development_preview_fit"
        ],
        missing_development_preview_fit=preview_fit,
        previous=previous_combined,
        approved_at=applied_at,
    )

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
                detail="The preparation authority changed; reload and apply again.",
            )
        result_store = RESULTS.current()
        rollback_snapshot = capture_preprocessing_mutation_state(
            scoped_store, result_store
        )
        quarantine_preprocessing_state(
            scoped_store,
            keys=(
                "missing_application",
                "missing_validation",
                "missing_policy",
                "missing_config",
                "preprocessing_policy",
                "feature_manifest",
                "feature_preview",
                "materialized_feature_names",
                "processed_stage",
            ),
            reason="A new governed missing-value policy superseded dependent state.",
        )
        scoped_store.processed_df = None
        scoped_store.meta["missing_config"] = normalized_config
        scoped_store.meta["missing_policy"] = missing_policy
        scoped_store.meta["missing_application"] = application
        scoped_store.meta["preprocessing_policy"] = combined_policy
        scoped_store.meta["preprocessing_state_status"] = "current"
        scoped_store.meta.pop("preprocessing_state_reason", None)
        invalidate_downstream_training_state(
            "The governed missing-value treatment changed.",
            store=scoped_store,
            split_status="stale",
        )
        if not save_checkpoint():
            restore_preprocessing_mutation_state(
                scoped_store, result_store, rollback_snapshot
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "Missing-value policy approval could not be persisted; "
                    "the in-memory workflow state was rolled back."
                ),
            )
    return json_safe(
        {
            "ok": True,
            **_identity_fields(identity),
            **_full_dataset_application_metadata(scope),
            "application": application,
            "preprocessing_policy": combined_policy,
        }
    )

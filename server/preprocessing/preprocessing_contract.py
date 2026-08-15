from __future__ import annotations

"""Versioned, leakage-safe preprocessing policy and recipe contracts.

Step 04 owns analyst-approved policy and a Development-only preview fit.  It
does not own fold or final fitting and must never materialize a transform over
the sealed holdout.  Training callers reuse the pure fit/apply helpers below
for each fold-training population and once for the final Development fit.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


PREPROCESSING_CONTRACT_VERSION = 2

FIT_SCOPE_DEVELOPMENT_PREVIEW = "development_preview"
FIT_SCOPE_FOLD_TRAINING = "fold_training"
FIT_SCOPE_CANDIDATE_DEVELOPMENT = "candidate_development_diagnostic"
FIT_SCOPE_FINAL_DEVELOPMENT = "final_development"
FIT_SCOPES = {
    FIT_SCOPE_DEVELOPMENT_PREVIEW,
    FIT_SCOPE_FOLD_TRAINING,
    FIT_SCOPE_CANDIDATE_DEVELOPMENT,
    FIT_SCOPE_FINAL_DEVELOPMENT,
}

OUTLIER_METHODS = (
    "NONE",
    "IQR_1_5",
    "IQR_3_0",
    "ZSCORE_3",
    "ZSCORE_4",
    "PCT_01_99",
    "PCT_05_95",
)

# ATLAS bureau-source contracts reserve these meaning-bearing codes. They are
# protected even when an older review representation omitted feature-level
# rows; no outlier or missing-value estimator may reinterpret them.
PROTECTED_BUREAU_SPECIAL_VALUES = (-9.0, -8.0, -7.0)

def _text(value: Any) -> str:
    return str(value or "").strip()


def _native(value: Any) -> Any:
    item = getattr(value, "item", None)
    if callable(item):
        try:
            value = item()
        except (TypeError, ValueError):
            pass
    return value


def _jsonable(value: Any) -> Any:
    value = _native(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def encode_typed_scalar(value: Any) -> dict[str, Any]:
    value = _native(value)
    if isinstance(value, bool):
        return {"kind": "boolean", "value": value}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("A fitted preprocessing value must be finite.")
        return {"kind": "number", "value": number}
    if value is None or pd.isna(value):
        raise ValueError("A fitted preprocessing value cannot be null.")
    return {"kind": "text", "value": str(value)}


def decode_typed_scalar(record: Mapping[str, Any]) -> Any:
    kind = _text(record.get("kind")).casefold()
    value = record.get("value")
    if kind == "boolean" and isinstance(value, bool):
        return value
    if kind == "number":
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("A fitted numeric preprocessing value must be finite.")
        return number
    if kind == "text":
        return str(value)
    raise ValueError("A fitted preprocessing value has no supported type tag.")


def fit_metadata(
    *,
    fit_scope: str,
    population_id: str,
    population_count: int,
    lineage: Mapping[str, Any] | None = None,
    fold_id: str | None = None,
    actor: str,
    application_scope: str,
    application_population_id: str,
    application_population_rows: int,
    evidence_references: Sequence[str] | None = None,
    fitted_at: str | None = None,
) -> dict[str, Any]:
    scope = _text(fit_scope)
    if scope not in FIT_SCOPES:
        raise ValueError(f"Unsupported preprocessing fit scope '{fit_scope}'.")
    identifier = _text(population_id)
    if not identifier:
        raise ValueError("A preprocessing fit population_id is required.")
    count = int(population_count)
    if count < 0:
        raise ValueError("A preprocessing fit population_count cannot be negative.")
    actor_value = _text(actor)
    application_scope_value = _text(application_scope)
    application_population_value = _text(application_population_id)
    if not actor_value:
        raise ValueError("A preprocessing fit actor is required.")
    if not application_scope_value or not application_population_value:
        raise ValueError(
            "A preprocessing application scope and population_id are required."
        )
    metadata = {
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "fit_scope": scope,
        "fit_population_id": identifier,
        "fit_population_count": count,
        "fit_population_rows": count,
        "holdout_excluded_from_fit": True,
        "final_holdout_used_for_fit": False,
        "fold_id": _text(fold_id) or None,
        "actor": actor_value,
        "fitted_at": _text(fitted_at) or datetime.now(timezone.utc).isoformat(),
        "application_scope": application_scope_value,
        "application_population_id": application_population_value,
        "application_population_rows": int(application_population_rows),
        "evidence_references": [
            _text(value) for value in (evidence_references or []) if _text(value)
        ],
    }
    for key in (
        "project_id",
        "dataset_id",
        "dataset_version_id",
        "target_contract_id",
        "predictor_authorization_id",
        "analysis_partition_id",
        "analysis_partition_revision",
        "source_checksum",
        "special_value_review_id",
        "special_value_review_revision",
        "special_value_detection_fingerprint",
    ):
        value = (lineage or {}).get(key)
        if value not in (None, ""):
            metadata[key] = value
    return metadata


def scope_lineage(scope: Any, special_value_contract: Mapping[str, Any] | None = None) -> dict[str, Any]:
    metadata = dict(scope.metadata())
    authorization = getattr(scope, "predictor_authorization", {})
    current_authorization_id = _text(
        authorization.get("predictor_authorization_id")
        if isinstance(authorization, Mapping)
        else ""
    )
    partition = getattr(scope, "partition", {})
    return {
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "project_id": _text(metadata.get("project_id")),
        "dataset_id": _text(metadata.get("dataset_id")),
        "dataset_version_id": _text(metadata.get("dataset_version_id")),
        "dataset_version": _text(metadata.get("dataset_version_id")),
        "target": _text(metadata.get("target")),
        "target_contract_id": _text(metadata.get("target_contract_id")),
        "predictor_authorization_id": current_authorization_id,
        "partition_predictor_authorization_id": _text(
            partition.get("predictor_authorization_id")
            if isinstance(partition, Mapping)
            else ""
        ),
        "analysis_partition_id": _text(metadata.get("analysis_partition_id")),
        "analysis_partition_revision": int(
            metadata.get("analysis_partition_revision") or 0
        ),
        "development_partition_id": _text(metadata.get("development_partition_id")),
        "source_checksum": _text(metadata.get("source_checksum")),
        "full_governed_population_rows": int(
            metadata.get("full_governed_population_rows") or 0
        ),
        "development_rows": int(metadata.get("development_rows") or 0),
        "sealed_holdout_rows": int(metadata.get("sealed_holdout_rows") or 0),
        "special_value_review_id": _text(
            (special_value_contract or {}).get("special_value_review_id")
        )
        or None,
        "special_value_review_revision": int(
            (special_value_contract or {}).get("revision") or 0
        ),
        "special_value_detection_fingerprint": _text(
            (special_value_contract or {}).get("detection_fingerprint")
        )
        or None,
    }


def build_preprocessing_policy_record(
    *,
    lineage: Mapping[str, Any],
    special_value_contract: Mapping[str, Any],
    actor: str,
    outlier_policy: Mapping[str, Any] | None,
    missing_policy: Mapping[str, Any] | None,
    outlier_development_preview_fit: Mapping[str, Any] | None,
    missing_development_preview_fit: Mapping[str, Any] | None,
    previous: Mapping[str, Any] | None = None,
    approved_at: str | None = None,
) -> dict[str, Any]:
    """Build the single canonical policy record consumed by training."""

    outlier_ready = bool(
        outlier_policy
        and outlier_policy.get("status") == "approved"
        and outlier_policy.get("outlier_policy_id")
    )
    missing_ready = bool(
        missing_policy
        and missing_policy.get("status") == "approved"
        and missing_policy.get("missing_policy_id")
    )
    executable = outlier_ready and missing_ready
    payload = {
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "lineage": dict(lineage),
        "special_value_contract": dict(special_value_contract),
        "outlier_policy": dict(outlier_policy or {}),
        "missing_policy": dict(missing_policy or {}),
    }
    policy_hash = canonical_hash(payload)
    prior_hash = _text((previous or {}).get("preprocessing_policy_hash"))
    prior_revision = int((previous or {}).get("preprocessing_policy_revision") or 0)
    revision = prior_revision if prior_hash == policy_hash else prior_revision + 1
    record = {
        **dict(lineage),
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "artifact_kind": (
            "approved_preprocessing_policy"
            if executable
            else "incomplete_preprocessing_policy"
        ),
        "preprocessing_policy_id": f"pp-{policy_hash[:20]}",
        "preprocessing_policy_revision": max(revision, 1),
        "preprocessing_policy_hash": policy_hash,
        "status": "approved" if executable else "incomplete_missing_policy",
        "executable": executable,
        "approved_by": _text(actor),
        "approved_at": _text(approved_at)
        or datetime.now(timezone.utc).isoformat(),
        "lineage": dict(lineage),
        "special_value_contract": dict(special_value_contract),
        "outlier_policy": dict(outlier_policy or {}),
        "missing_policy": dict(missing_policy or {}),
        "stage_status": {
            "outlier_policy": "approved" if outlier_ready else "required",
            "missing_policy": "approved" if missing_ready else "required",
        },
        "stage_evidence": {
            "outlier_policy_id": (outlier_policy or {}).get(
                "outlier_policy_id"
            ),
            "outlier_policy_revision": (outlier_policy or {}).get(
                "outlier_policy_revision"
            ),
            "missing_policy_id": (missing_policy or {}).get(
                "missing_policy_id"
            ),
            "missing_policy_revision": (missing_policy or {}).get(
                "missing_policy_revision"
            ),
        },
        "development_preview_fits": {
            "outlier": dict(outlier_development_preview_fit or {}) or None,
            "missing": dict(missing_development_preview_fit or {}) or None,
        },
        "development_preview_status": (
            "ready"
            if outlier_development_preview_fit
            or missing_development_preview_fit
            else "not_required"
        ),
        "fold_fitted_artifact_status": "required_during_training",
        "final_fitted_artifact_status": "required_during_training",
        "fold_fitted_artifacts": [],
        "final_fitted_artifact": None,
        "backend_materialization": False,
        "processed_frame_materialized": False,
        "sealed_holdout_transformed": False,
        "sealed_holdout_used_for_fit": False,
    }
    return record


def classify_preprocessing_record(
    record: Any,
    *,
    lineage: Mapping[str, Any],
) -> tuple[str, list[str]]:
    if not isinstance(record, Mapping):
        return "absent", []
    if int(record.get("preprocessing_contract_version") or 0) != PREPROCESSING_CONTRACT_VERSION:
        return "stale_legacy_unverified", [
            "The artifact predates preprocessing contract v2 and has no verifiable fit scope."
        ]
    reasons: list[str] = []
    for key in (
        "project_id",
        "dataset_id",
        "dataset_version_id",
        "target_contract_id",
        "predictor_authorization_id",
        "analysis_partition_id",
        "source_checksum",
    ):
        expected = _text(lineage.get(key))
        actual = _text(record.get(key))
        if expected and actual != expected:
            reasons.append(f"{key} does not match the current preprocessing authority")
    expected_revision = int(lineage.get("analysis_partition_revision") or 0)
    if expected_revision and int(record.get("analysis_partition_revision") or 0) != expected_revision:
        reasons.append("analysis_partition_revision does not match the current authority")
    for key in ("special_value_review_id", "special_value_detection_fingerprint"):
        expected = _text(lineage.get(key))
        actual = _text(record.get(key))
        if expected != actual:
            reasons.append(f"{key} does not match the current special-value authority")
    expected_special_revision = int(lineage.get("special_value_review_revision") or 0)
    if int(record.get("special_value_review_revision") or 0) != expected_special_revision:
        reasons.append("special_value_review_revision does not match the current authority")
    return ("current", []) if not reasons else ("stale_lineage", reasons)


def assert_mutation_expectations(
    request: Any,
    *,
    lineage: Mapping[str, Any],
) -> None:
    """Reject a v2 browser mutation reviewed against a stale authority.

    Every mutation must declare v2 and submit every mutable lineage
    expectation. Read-only summaries may classify legacy state, but a legacy
    or incomplete browser draft is never execution authority.
    """

    requested_version = getattr(request, "preprocessing_contract_version", None)
    if requested_version is None:
        raise ValueError(
            "Reload the preprocessing workspace; mutation requires the exact preprocessing-v2 authority."
        )
    if int(requested_version) != PREPROCESSING_CONTRACT_VERSION:
        raise ValueError("Reload the preprocessing workspace under contract v2.")
    checks = {
        "analysis_partition_id": getattr(request, "analysis_partition_id", None),
        "analysis_partition_revision": getattr(request, "analysis_partition_revision", None),
        "predictor_authorization_id": getattr(
            request, "expected_predictor_authorization_id", None
        ),
        "special_value_review_id": getattr(
            request, "expected_special_value_review_id", None
        ),
        "special_value_review_revision": getattr(
            request, "expected_special_value_review_revision", None
        ),
    }
    for key, supplied in checks.items():
        expected = lineage.get(key)
        if key == "special_value_review_id" and not _text(expected):
            if supplied not in (None, ""):
                raise ValueError("The special-value review changed; reload the plan.")
            continue
        if key.endswith("revision"):
            if supplied is None or int(supplied) != int(expected or 0):
                raise ValueError(f"The current {key} changed; reload the plan.")
        elif not _text(supplied) or _text(supplied) != _text(expected):
            raise ValueError(f"The current {key} changed; reload the plan.")


def quarantine_preprocessing_state(
    store: Any,
    *,
    keys: Sequence[str],
    reason: str,
) -> list[str]:
    """Move unverifiable current records to append-only runtime audit history."""

    quarantined: list[str] = []
    history = store.meta.setdefault("preprocessing_audit_history", [])
    if not isinstance(history, list):
        history = []
        store.meta["preprocessing_audit_history"] = history
    now = datetime.now(timezone.utc).isoformat()
    processed_stage = store.meta.get("processed_stage")
    for key in keys:
        record = store.meta.get(key)
        if record is None:
            continue
        history.append(
            {
                "state_key": key,
                "status": "stale_quarantined",
                "reason": str(reason),
                "quarantined_at": now,
                "record": deepcopy(record),
            }
        )
        store.meta.pop(key, None)
        quarantined.append(key)
    if store.processed_df is not None and quarantined:
        processed = store.processed_df
        try:
            hashed = pd.util.hash_pandas_object(processed, index=True).values
            processed_hash = hashlib.sha256(hashed.tobytes()).hexdigest()
        except Exception:
            processed_hash = "unavailable"
        history.append(
            {
                "state_key": "processed_df",
                "status": "stale_quarantined",
                "reason": str(reason),
                "quarantined_at": now,
                "record": {
                    "processed_stage": processed_stage,
                    "row_count": int(len(processed)),
                    "columns": [str(value) for value in processed.columns],
                    "processed_frame_hash": processed_hash,
                    "frame_retained_as_current": False,
                },
            }
        )
        store.processed_df = None
        store.meta.pop("processed_stage", None)
    if quarantined:
        store.meta["preprocessing_state_status"] = "stale"
        store.meta["preprocessing_state_reason"] = str(reason)
        store.data_revision += 1
        store.reset_splits()
    return quarantined


def capture_preprocessing_mutation_state(
    store: Any,
    result_store: Any,
) -> dict[str, Any]:
    """Capture reversible in-memory state before a governed policy commit."""

    return {
        "dataset": {
            "meta": deepcopy(store.meta),
            "processed_df": store.processed_df,
            "X_train": store.X_train,
            "X_test": store.X_test,
            "y_train": store.y_train,
            "y_test": store.y_test,
            "data_revision": int(store.data_revision),
        },
        "results": {
            "last_training_summary": deepcopy(
                result_store.last_training_summary
            ),
            "training_timestamp": result_store.training_timestamp,
            "model_availability": deepcopy(result_store.model_availability),
            # Fitted estimator objects are not mutated by invalidation; retain
            # their exact references instead of attempting unsafe deep copies.
            "model_artifacts": dict(result_store.model_artifacts),
            "model_artifact_metadata": deepcopy(
                result_store.model_artifact_metadata
            ),
            "final_model": result_store.final_model,
            "final_model_metadata": deepcopy(
                result_store.final_model_metadata
            ),
            "scoring_reference": deepcopy(result_store.scoring_reference),
            "holdout_evaluations": deepcopy(
                result_store.holdout_evaluations
            ),
        },
    }


def restore_preprocessing_mutation_state(
    store: Any,
    result_store: Any,
    snapshot: Mapping[str, Any],
) -> None:
    """Restore a failed policy commit without manufacturing new lineage."""

    dataset = snapshot.get("dataset")
    results = snapshot.get("results")
    if not isinstance(dataset, Mapping) or not isinstance(results, Mapping):
        raise ValueError("The preprocessing rollback snapshot is malformed.")
    store.meta = deepcopy(dataset["meta"])
    store.processed_df = dataset.get("processed_df")
    store.X_train = dataset.get("X_train")
    store.X_test = dataset.get("X_test")
    store.y_train = dataset.get("y_train")
    store.y_test = dataset.get("y_test")
    store.data_revision = int(dataset.get("data_revision") or 0)
    with result_store.state_lock:
        result_store.last_training_summary = deepcopy(
            results.get("last_training_summary")
        )
        result_store.training_timestamp = results.get("training_timestamp")
        result_store.model_availability = deepcopy(
            results.get("model_availability") or {}
        )
        result_store.model_artifacts = dict(
            results.get("model_artifacts") or {}
        )
        result_store.model_artifact_metadata = deepcopy(
            results.get("model_artifact_metadata") or {}
        )
        result_store.final_model = results.get("final_model")
        result_store.final_model_metadata = deepcopy(
            results.get("final_model_metadata")
        )
        result_store.scoring_reference = deepcopy(
            results.get("scoring_reference")
        )
        result_store.holdout_evaluations = deepcopy(
            results.get("holdout_evaluations") or {}
        )


def analytical_type(
    values: pd.Series,
    governed: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    governed_type = _text(
        (governed or {}).get("analytical_type")
        or (governed or {}).get("classification")
    ).casefold()
    governed_source = _text((governed or {}).get("source"))
    governed_reason = _text((governed or {}).get("reason"))
    if governed_type:
        aliases = {
            "continuous": "numeric_continuous",
            "numeric": "numeric_continuous",
            "ordinal": "numeric_ordinal",
            "discrete": "numeric_discrete",
            "binary": "boolean",
        }
        resolved = aliases.get(governed_type, governed_type)
        authoritative_support = _text(
            (governed or {}).get("authoritative_support")
        )
        trusted_source = governed_source in {
            "data_dictionary",
            "governed_metadata",
            "provider_metadata",
            "analyst_override",
        }
        supported = bool(authoritative_support and trusted_source)
        bounded = resolved in {
            "bounded_percentage",
            "bounded_rate",
            "percentage",
            "rate",
        }
        raw_business_min = (
            (governed or {}).get("business_min")
            if (governed or {}).get("business_min") is not None
            else (governed or {}).get("lower_bound")
        )
        raw_business_max = (
            (governed or {}).get("business_max")
            if (governed or {}).get("business_max") is not None
            else (governed or {}).get("upper_bound")
        )
        business_min: float | None = None
        business_max: float | None = None
        bounds_valid = not bounded
        if bounded:
            try:
                business_min = float(raw_business_min)
                business_max = float(raw_business_max)
                bounds_valid = bool(
                    math.isfinite(business_min)
                    and math.isfinite(business_max)
                    and business_min < business_max
                )
            except (TypeError, ValueError):
                bounds_valid = False
        supported = supported and bounds_valid
        eligible = (
            resolved == "numeric_continuous" or bounded
        ) and supported
        return {
            "analytical_type": (
                resolved if supported else "unknown_review_required"
            ),
            "outlier_eligible": eligible,
            "safe_default_method": "IQR_1_5" if eligible else "NONE",
            "eligibility_reason": governed_reason
            or (
                "Governed analytical type supplied by an authoritative source."
                if supported
                else "Analytical type lacks authoritative semantic support."
            ),
            "classification_source": governed_source or "unverified_metadata",
            "authoritative_support": authoritative_support or None,
            "classification_requires_review": not supported,
            "business_min": business_min,
            "business_max": business_max,
            "business_bounds_enforced": bool(bounded and supported),
        }
    nonmissing = values.dropna()
    if pd.api.types.is_bool_dtype(values):
        return {
            "analytical_type": "boolean",
            "outlier_eligible": False,
            "safe_default_method": "NONE",
            "eligibility_reason": "Boolean predictors do not have an ordinary continuous tail.",
            "classification_source": "physical_dtype",
            "authoritative_support": "boolean_physical_dtype",
            "classification_requires_review": False,
            "business_min": None,
            "business_max": None,
            "business_bounds_enforced": False,
        }
    numeric = pd.to_numeric(nonmissing, errors="coerce")
    numeric_rate = float(numeric.notna().mean()) if len(nonmissing) else 0.0
    if not pd.api.types.is_numeric_dtype(values) and numeric_rate < 0.8:
        return {
            "analytical_type": "categorical",
            "outlier_eligible": False,
            "safe_default_method": "NONE",
            "eligibility_reason": "Categorical predictors are not eligible for numeric tail capping.",
            "classification_source": "physical_dtype_and_parse_rate",
            "authoritative_support": "categorical_physical_dtype",
            "classification_requires_review": False,
            "business_min": None,
            "business_max": None,
            "business_bounds_enforced": False,
        }
    return {
        "analytical_type": "unknown_review_required",
        "outlier_eligible": False,
        "safe_default_method": "NONE",
        "eligibility_reason": (
            "Numeric storage does not establish continuous analytical semantics; "
            "governed metadata or an authoritative analyst override is required."
        ),
        "classification_source": "safe_unclassified_default",
        "authoritative_support": None,
        "classification_requires_review": True,
        "business_min": None,
        "business_max": None,
        "business_bounds_enforced": False,
    }


def _value_mask(series: pd.Series, value: Any) -> pd.Series:
    value = _native(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return pd.to_numeric(series, errors="coerce").eq(float(value)).fillna(False)
    return series.eq(value).fillna(False)


def special_values_for_feature(
    feature: str,
    special_value_contract: Mapping[str, Any] | None,
) -> list[Any]:
    features = (special_value_contract or {}).get("features")
    row = features.get(feature) if isinstance(features, Mapping) else None
    governed_values = (
        list(row.get("values") or []) if isinstance(row, Mapping) else []
    )
    values: list[Any] = []
    seen: set[str] = set()
    for value in [*governed_values, *PROTECTED_BUREAU_SPECIAL_VALUES]:
        marker = json.dumps(_jsonable(value), sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        values.append(value)
    return values


def governed_special_values_for_feature(
    feature: str,
    special_value_contract: Mapping[str, Any] | None,
) -> list[Any]:
    """Return only values explicitly governed for this exact feature.

    The broader preprocessing safety mask also protects the platform's
    reserved bureau sentinels when old or incomplete metadata is encountered.
    That fail-safe must not inflate the separately disclosed count of values
    actually classified by the exact special-value review contract.
    """

    features = (special_value_contract or {}).get("features")
    row = features.get(feature) if isinstance(features, Mapping) else None
    governed_values = (
        list(row.get("values") or []) if isinstance(row, Mapping) else []
    )
    values: list[Any] = []
    seen: set[str] = set()
    for value in governed_values:
        marker = json.dumps(_jsonable(value), sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        values.append(value)
    return values


def governed_special_mask(
    series: pd.Series,
    feature: str,
    special_value_contract: Mapping[str, Any] | None,
) -> pd.Series:
    mask = pd.Series(False, index=series.index, dtype=bool)
    for value in governed_special_values_for_feature(
        feature, special_value_contract
    ):
        mask = mask | _value_mask(series, value)
    return mask


def special_mask(
    series: pd.Series,
    feature: str,
    special_value_contract: Mapping[str, Any] | None,
) -> pd.Series:
    mask = pd.Series(False, index=series.index, dtype=bool)
    for value in special_values_for_feature(feature, special_value_contract):
        mask = mask | _value_mask(series, value)
    return mask


def apply_special_value_policy(
    frame: pd.DataFrame,
    special_value_contract: Mapping[str, Any] | None,
) -> pd.DataFrame:
    work = frame.copy(deep=True)
    features = (special_value_contract or {}).get("features")
    if not isinstance(features, Mapping):
        return work
    for feature, raw in features.items():
        if feature not in work.columns or not isinstance(raw, Mapping):
            continue
        default_policy = _text(raw.get("policy") or "preserve_informative").casefold()
        replacement = raw.get("replacement_value")
        overrides = raw.get("overrides") if isinstance(raw.get("overrides"), list) else []
        override_values = {
            json.dumps(_jsonable(item.get("value")), sort_keys=True)
            for item in overrides
            if isinstance(item, Mapping)
        }
        operations = [
            {
                "values": [value],
                "policy": default_policy,
                "replacement_value": replacement,
            }
            for value in raw.get("values", [])
            if json.dumps(_jsonable(value), sort_keys=True) not in override_values
        ]
        operations.extend(
            {
                "values": [item.get("value")],
                "policy": _text(item.get("policy")).casefold(),
                "replacement_value": item.get("replacement_value"),
            }
            for item in overrides
            if isinstance(item, Mapping)
        )
        for operation in operations:
            mask = pd.Series(False, index=work.index, dtype=bool)
            for value in operation["values"]:
                mask = mask | _value_mask(work[feature], value)
            policy = operation["policy"]
            if policy == "convert_to_missing":
                work.loc[mask, feature] = np.nan
            elif policy in {"convert_to_category", "documented_domain_mapping"}:
                if policy == "convert_to_category" and operation.get(
                    "replacement_value"
                ) is None:
                    # Category semantics are a modeling instruction; the
                    # meaning-bearing code itself remains unchanged.
                    continue
                if operation.get("replacement_value") is None:
                    raise ValueError(
                        f"The approved special-value mapping for {feature} has no replacement value."
                    )
                work.loc[mask, feature] = operation["replacement_value"]
            elif policy == "exclude_variable":
                work = work.drop(columns=[feature])
                break
            elif policy in {"preserve_informative", "leave_unchanged"}:
                continue
            else:
                raise ValueError(
                    f"The approved special-value policy '{policy}' for {feature} is not executable."
                )
    return work


def resolve_special_value_contract(
    *,
    identity: Mapping[str, Any],
    scope: Any,
    store: Any,
) -> dict[str, Any]:
    """Resolve exact durable review into a value-level executable contract."""

    row: Mapping[str, Any] | None = None
    try:
        from ..persistence.service import get_persistence_service

        candidate = get_persistence_service().special_value_reviews.get_exact(
            _text(identity.get("project_id")),
            _text(identity.get("dataset_id")),
            _text(identity.get("dataset_version_id")),
        )
        if isinstance(candidate, Mapping):
            row = candidate
    except Exception:
        row = None
    if row is None:
        cached = store.meta.get("special_value_review")
        if isinstance(cached, Mapping):
            row = cached
    if row is None:
        return {
            "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
            "status": "not_required",
            "special_value_review_id": None,
            "revision": 0,
            "detection_fingerprint": None,
            "features": {},
        }

    detection = row.get("detection_json") if isinstance(row.get("detection_json"), Mapping) else {}
    decisions = row.get("decisions_json")
    if not isinstance(decisions, list):
        decisions = row.get("variable_decisions")
    decisions = decisions if isinstance(decisions, list) else []
    decision_by_feature = {
        _text(item.get("variable")): item
        for item in decisions
        if isinstance(item, Mapping) and _text(item.get("variable"))
    }
    detected_rows = detection.get("variables") if isinstance(detection, Mapping) else []
    features: dict[str, Any] = {}
    for detected in detected_rows or []:
        if not isinstance(detected, Mapping) or not bool(detected.get("likely_bureau")):
            continue
        feature = _text(detected.get("variable"))
        if not feature:
            continue
        values = [
            item.get("value")
            for item in detected.get("special_values", []) or []
            if isinstance(item, Mapping) and item.get("value") is not None
        ]
        if not values:
            continue
        decision = decision_by_feature.get(feature, {})
        features[feature] = {
            "values": values,
            "policy": _text(decision.get("policy")) or "preserve_informative",
            "replacement_value": decision.get("replacement_value"),
            "rationale": _text(decision.get("rationale")),
            "overrides": list(decision.get("overrides") or []),
        }
    contract = {
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "status": _text(row.get("status")) or "not_started",
        "special_value_review_id": _text(row.get("special_value_review_id")) or None,
        "revision": int(row.get("revision") or 0),
        "detection_fingerprint": _text(row.get("detection_fingerprint")) or None,
        "features": features,
    }
    contract["contract_hash"] = canonical_hash(contract)
    return contract


def _thresholds(values: pd.Series, method: str) -> tuple[float, float]:
    clean = values.dropna().astype(float)
    if clean.empty:
        return 0.0, 0.0
    if method == "NONE":
        return float(clean.min()), float(clean.max())
    if method in {"ZSCORE_3", "ZSCORE_4"}:
        width = 3.0 if method == "ZSCORE_3" else 4.0
        mean = float(clean.mean())
        standard_deviation = float(clean.std(ddof=0))
        return mean - width * standard_deviation, mean + width * standard_deviation
    if method == "PCT_01_99":
        return float(clean.quantile(0.01)), float(clean.quantile(0.99))
    if method == "PCT_05_95":
        return float(clean.quantile(0.05)), float(clean.quantile(0.95))
    first_quartile = float(clean.quantile(0.25))
    third_quartile = float(clean.quantile(0.75))
    multiplier = 3.0 if method == "IQR_3_0" else 1.5
    spread = third_quartile - first_quartile
    return first_quartile - multiplier * spread, third_quartile + multiplier * spread


def fit_outlier_recipe(
    frame: pd.DataFrame,
    *,
    policy: Mapping[str, Any],
    fit: Mapping[str, Any],
    special_value_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if int(fit.get("fit_population_count") or -1) != int(len(frame)):
        raise ValueError("The outlier fit frame does not match its declared population count.")
    global_method = _text(policy.get("global_method") or "IQR_1_5").upper()
    if global_method not in OUTLIER_METHODS:
        raise ValueError(f"Unsupported global outlier method '{global_method}'.")
    config = policy.get("config") if isinstance(policy.get("config"), Mapping) else {}
    rationales = policy.get("rationales") if isinstance(policy.get("rationales"), Mapping) else {}
    treatments: list[dict[str, Any]] = []
    for feature in config:
        if feature not in frame.columns:
            continue
        governed_types = (
            policy.get("analytical_types")
            if isinstance(policy.get("analytical_types"), Mapping)
            else {}
        )
        profile = analytical_type(frame[feature], governed_types.get(feature))
        configured = _text(config.get(feature) or "USE_GLOBAL").upper()
        method = global_method if configured == "USE_GLOBAL" else configured
        if method not in OUTLIER_METHODS:
            raise ValueError(f"Unsupported outlier method '{method}' for {feature}.")
        if not profile["outlier_eligible"] and method != "NONE":
            if configured == "USE_GLOBAL":
                method = "NONE"
            else:
                raise ValueError(
                    f"{feature} is {profile['analytical_type']}; a non-NONE tail policy requires an authoritative numeric-continuous or bounded-rate classification and analyst rationale."
                )
        if method != "NONE" and not _text(rationales.get(feature)) and (
            isinstance(governed_types.get(feature), Mapping)
            and _text(governed_types.get(feature).get("source"))
            == "analyst_override"
        ):
            raise ValueError(
                f"{feature} requires analyst rationale for its semantic override."
            )
        numeric = pd.to_numeric(frame[feature], errors="coerce")
        ordinary = numeric.mask(special_mask(frame[feature], feature, special_value_contract))
        low, high = _thresholds(ordinary, method)
        statistical_low, statistical_high = low, high
        if method != "NONE" and profile["business_bounds_enforced"]:
            business_min = float(profile["business_min"])
            business_max = float(profile["business_max"])
            low = max(low, business_min)
            high = min(high, business_max)
            if low > high:
                low, high = business_min, business_max
        treatments.append(
            {
                "feature": str(feature),
                "configured_method": configured,
                "applied_method": method,
                "lower_threshold": low,
                "upper_threshold": high,
                "statistical_lower_threshold": statistical_low,
                "statistical_upper_threshold": statistical_high,
                "business_min": profile["business_min"],
                "business_max": profile["business_max"],
                "business_bounds_enforced": profile[
                    "business_bounds_enforced"
                ],
                "analytical_type": profile["analytical_type"],
                "outlier_eligible": bool(profile["outlier_eligible"]),
                "classification_source": profile["classification_source"],
                "classification_requires_review": profile[
                    "classification_requires_review"
                ],
                "fit_ordinary_count": int(ordinary.notna().sum()),
                "fit_null_excluded_count": int(frame[feature].isna().sum()),
                "fit_special_excluded_count": int(
                    special_mask(
                        frame[feature], feature, special_value_contract
                    ).sum()
                ),
                "special_values_preserved": special_values_for_feature(
                    str(feature), special_value_contract
                ),
            }
        )
    recipe = {
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "artifact_kind": "outlier_fitted_recipe",
        **dict(fit),
        "policy_hash": canonical_hash(dict(policy)),
        "special_value_contract_hash": (special_value_contract or {}).get("contract_hash"),
        "treatments": treatments,
        "fit_null_excluded_count": int(
            sum(row["fit_null_excluded_count"] for row in treatments)
        ),
        "fit_special_excluded_count": int(
            sum(row["fit_special_excluded_count"] for row in treatments)
        ),
    }
    recipe["recipe_hash"] = canonical_hash(recipe)
    return recipe


def apply_outlier_recipe(
    frame: pd.DataFrame,
    *,
    recipe: Mapping[str, Any],
    target: str | None = None,
    special_value_contract: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if int(recipe.get("preprocessing_contract_version") or 0) != PREPROCESSING_CONTRACT_VERSION:
        raise ValueError("Only a verified preprocessing v2 outlier recipe can be applied.")
    work = frame.copy(deep=True)
    row_flag_counts = pd.Series(0, index=work.index, dtype="int64")
    results: list[dict[str, Any]] = []
    for treatment in recipe.get("treatments", []) or []:
        if not isinstance(treatment, Mapping):
            raise ValueError("An outlier recipe treatment is malformed.")
        feature = _text(treatment.get("feature"))
        if not feature or feature == target or feature not in work.columns:
            continue
        method = _text(treatment.get("applied_method")).upper()
        numeric = pd.to_numeric(work[feature], errors="coerce")
        specials = special_mask(work[feature], feature, special_value_contract)
        if method == "NONE":
            changed = pd.Series(False, index=work.index, dtype=bool)
        else:
            low = float(treatment["lower_threshold"])
            high = float(treatment["upper_threshold"])
            clipped = numeric.clip(low, high).where(~specials, numeric)
            changed = numeric.notna() & clipped.ne(numeric)
            # Mutate only proven numeric outliers. Non-null parse failures,
            # categories, and governed special codes retain their original
            # values and dtype semantics.
            work.loc[changed, feature] = clipped.loc[changed]
        row_flag_counts = row_flag_counts + changed.astype("int64")
        eligible_count = int((numeric.notna() & ~specials).sum())
        results.append(
            {
                **dict(treatment),
                "flagged_cell_count": int(changed.sum()),
                "eligible_cell_count": eligible_count,
                "flagged_cell_rate": int(changed.sum()) / max(eligible_count, 1),
            }
        )
    affected = row_flag_counts > 0
    flagged_cells = int(row_flag_counts.sum())
    affected_rows = int(affected.sum())
    counts = {
        "flagged_cell_count": flagged_cells,
        "affected_row_count": affected_rows,
        "affected_row_rate": affected_rows / max(int(len(work)), 1),
        "affected_predictor_count": int(
            sum(row["flagged_cell_count"] > 0 for row in results)
        ),
        "mean_flagged_features_per_affected_row": (
            float(row_flag_counts[affected].mean()) if affected_rows else 0.0
        ),
        "max_flagged_features_per_row": int(row_flag_counts.max())
        if len(row_flag_counts)
        else 0,
        "maximum_flagged_features_on_one_row": int(row_flag_counts.max())
        if len(row_flag_counts)
        else 0,
    }
    return work, {"counts": counts, "treatments": results}


def normalize_true_missing(
    frame: pd.DataFrame,
    *,
    governed_tokens: Mapping[str, Sequence[str]] | None = None,
    special_value_contract: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Normalize only feature-specific, explicitly governed missing tokens."""

    work = frame.copy(deep=True)
    for column, tokens in (governed_tokens or {}).items():
        if column not in work.columns:
            continue
        canonical = {_text(value).casefold() for value in tokens}
        text = work[column].astype("string")
        governed_missing = text.str.strip().str.casefold().isin(canonical)
        governed_missing = governed_missing & ~special_mask(
            work[column], str(column), special_value_contract
        )
        work.loc[governed_missing, column] = np.nan
    return work


def fit_missing_recipe(
    frame: pd.DataFrame,
    *,
    policy: Mapping[str, Any],
    fit: Mapping[str, Any],
    special_value_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if int(fit.get("fit_population_count") or -1) != int(len(frame)):
        raise ValueError("The missing-value fit frame does not match its declared population count.")
    governed_tokens = (
        policy.get("missing_tokens")
        if isinstance(policy.get("missing_tokens"), Mapping)
        else {}
    )
    work = normalize_true_missing(
        frame,
        governed_tokens=governed_tokens,
        special_value_contract=special_value_contract,
    )
    config = policy.get("config") if isinstance(policy.get("config"), Mapping) else {}
    active_treatment = _text(policy.get("active_treatment")).upper()
    if active_treatment and active_treatment not in {"NONE", "FEATURE_SPECIFIC"}:
        raise ValueError(
            f"Unsupported active missing-value treatment '{active_treatment}'."
        )
    if active_treatment == "NONE":
        true_null_count = int(work.isna().sum().sum())
        if true_null_count:
            raise ValueError(
                "The active NONE missing-value policy is invalid because "
                f"{true_null_count} governed true-null cell(s) are present."
            )
        config = {}
    treatments: list[dict[str, Any]] = []
    for feature, raw_rule in config.items():
        if feature not in work.columns or not isinstance(raw_rule, Mapping):
            continue
        strategy = _text(raw_rule.get("strategy") or "None").casefold()
        if strategy == "none":
            continue
        if strategy == "drop row":
            raise ValueError(
                "Row deletion is not an executable preprocessing v2 missing-value policy."
            )
        series = work[feature]
        if int(series.isna().sum()) == 0:
            # A contingency choice is not an active estimator when there are
            # no governed true nulls in the fit population.
            continue
        ordinary = series.mask(special_mask(series, feature, special_value_contract))
        governed_types = (
            policy.get("analytical_types")
            if isinstance(policy.get("analytical_types"), Mapping)
            else {}
        )
        numeric_profile = analytical_type(ordinary, governed_types.get(feature))
        nonmissing = ordinary.dropna()
        numeric = bool(
            pd.api.types.is_numeric_dtype(ordinary)
            or (
                len(nonmissing)
                and pd.to_numeric(nonmissing, errors="coerce").notna().mean()
                >= 0.8
            )
        )
        fitted_value: Any
        if strategy in {"mean", "median"}:
            if not numeric:
                raise ValueError(
                    f"{feature} is not numeric; {strategy.title()} is not analytically eligible."
                )
            converted = pd.to_numeric(ordinary, errors="coerce")
            if int(converted.notna().sum()) == 0:
                raise ValueError(
                    f"{feature} has no ordinary observed numeric values from which to fit {strategy}."
                )
            fitted_value = converted.mean() if strategy == "mean" else converted.median()
        elif strategy == "mode":
            mode = ordinary.dropna().mode()
            if not len(mode):
                raise ValueError(
                    f"{feature} has no ordinary observed values from which to fit mode."
                )
            fitted_value = mode.iloc[0]
        elif strategy == "constant":
            fitted_value = raw_rule.get("constantValue")
            if numeric:
                fitted_value = pd.to_numeric(
                    pd.Series([fitted_value]), errors="coerce"
                ).iloc[0]
            if fitted_value is None or pd.isna(fitted_value):
                raise ValueError(
                    f"{feature} requires a non-null constant fill value."
                )
        else:
            raise ValueError(f"Unsupported missing-value strategy '{strategy}' for {feature}.")
        typed = encode_typed_scalar(fitted_value)
        treatments.append(
            {
                "feature": str(feature),
                "strategy": strategy,
                "fitted_value": typed,
                "fitted_dtype": str(series.dtype),
                "analytical_type": numeric_profile["analytical_type"],
                "fit_ordinary_count": int(ordinary.notna().sum()),
                "fit_null_excluded_count": int(series.isna().sum()),
                "fit_special_excluded_count": int(
                    special_mask(series, feature, special_value_contract).sum()
                ),
            }
        )
    recipe = {
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "artifact_kind": "missing_fitted_recipe",
        **dict(fit),
        "policy_hash": canonical_hash(dict(policy)),
        "special_value_contract_hash": (special_value_contract or {}).get("contract_hash"),
        "governed_missing_tokens": {
            str(feature): [str(value) for value in values]
            for feature, values in governed_tokens.items()
            if isinstance(values, (list, tuple))
        },
        "treatments": treatments,
        "fit_null_excluded_count": int(
            sum(row["fit_null_excluded_count"] for row in treatments)
        ),
        "fit_special_excluded_count": int(
            sum(row["fit_special_excluded_count"] for row in treatments)
        ),
    }
    recipe["recipe_hash"] = canonical_hash(recipe)
    return recipe


def apply_missing_recipe(
    frame: pd.DataFrame,
    *,
    recipe: Mapping[str, Any],
    target: str | None = None,
    special_value_contract: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if int(recipe.get("preprocessing_contract_version") or 0) != PREPROCESSING_CONTRACT_VERSION:
        raise ValueError("Only a verified preprocessing v2 missing-value recipe can be applied.")
    governed_tokens = (
        recipe.get("governed_missing_tokens")
        if isinstance(recipe.get("governed_missing_tokens"), Mapping)
        else {}
    )
    work = normalize_true_missing(
        frame,
        governed_tokens=governed_tokens,
        special_value_contract=special_value_contract,
    )
    row_flag_counts = pd.Series(0, index=work.index, dtype="int64")
    results: list[dict[str, Any]] = []
    for treatment in recipe.get("treatments", []) or []:
        if not isinstance(treatment, Mapping):
            raise ValueError("A missing-value recipe treatment is malformed.")
        feature = _text(treatment.get("feature"))
        if not feature or feature == target or feature not in work.columns:
            continue
        series = work[feature]
        missing = series.isna()
        fill_value = decode_typed_scalar(treatment.get("fitted_value") or {})
        # Fill only cells that were true nulls before any type conversion.
        # Non-null parse failures remain untouched and separately auditable.
        work.loc[missing, feature] = fill_value
        row_flag_counts = row_flag_counts + missing.astype("int64")
        results.append(
            {
                **dict(treatment),
                "flagged_cell_count": int(missing.sum()),
                "eligible_cell_count": int(len(series)),
                "flagged_cell_rate": int(missing.sum()) / max(int(len(series)), 1),
            }
        )
    affected = row_flag_counts > 0
    affected_rows = int(affected.sum())
    counts = {
        "flagged_cell_count": int(row_flag_counts.sum()),
        "affected_row_count": affected_rows,
        "affected_row_rate": affected_rows / max(int(len(work)), 1),
        "affected_predictor_count": int(
            sum(row["flagged_cell_count"] > 0 for row in results)
        ),
        "mean_flagged_features_per_affected_row": (
            float(row_flag_counts[affected].mean()) if affected_rows else 0.0
        ),
        "max_flagged_features_per_row": int(row_flag_counts.max())
        if len(row_flag_counts)
        else 0,
        "maximum_flagged_features_on_one_row": int(row_flag_counts.max())
        if len(row_flag_counts)
        else 0,
    }
    return work, {"counts": counts, "treatments": results}


_EXCLUSION_DECISION = re.compile(r"\b(exclude|drop|remove|deduplicat)", re.IGNORECASE)


def duplicate_exclusion_blockers(
    approved_eda_record: Mapping[str, Any] | None,
    *,
    executable_duplicate_recipe: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Block training when approved EDA requires exclusion without a recipe."""

    if not isinstance(approved_eda_record, Mapping):
        return []
    sections = approved_eda_record.get("sections")
    sections = sections if isinstance(sections, Mapping) else {}
    findings = sections.get("findings")
    findings = findings if isinstance(findings, Mapping) else {}
    decision = _text(
        approved_eda_record.get("duplicate_decision")
        or findings.get("duplicate_decision")
        or findings.get("duplicate_treatment")
    )
    if not decision or not _EXCLUSION_DECISION.search(decision):
        return []
    return [
        {
            "code": "approved_duplicate_exclusion_requires_population_revision",
            "message": (
                "The approved EDA decision requires exact-duplicate exclusion, "
                "which cannot be executed after the Analysis Partition is sealed. "
                "Create a revised registered population and confirm a new partition."
            ),
            "decision": decision,
        }
    ]

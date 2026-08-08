from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
import time
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

from ..core.dataset_store import DATASTORE
from ..core.modeling_scope import active_project_id
from ..core.pretraining_invalidation import invalidate_downstream_training_state
from ..core.session_checkpoint import schedule_checkpoint_save
from ..datasets.dataset_identity import (
    active_dataset_identity,
    assert_expected_active_identity,
)
from ..preprocessing.predictor_authorization import (
    bureau_special_mask,
    governed_predictor_authorization,
)
from ..preprocessing.quality_profile_service import governed_time_field
from .feature_types import FeatureDefinitionInput, FeatureManifestUpdateRequest
from .feature_manifest_store import load_current_manifest, persist_manifest_version


_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SPLIT_FIELD = re.compile(r"(^|_)(split|fold|partition|sample_role)($|_)", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _feature_summary_statistics(values: pd.Series) -> dict[str, Any]:
    """Profile one feature on the governed full population.

    Bureau special values remain governed values and are not folded into
    ordinary numeric summary statistics.
    """

    special_mask = bureau_special_mask(values)
    ordinary = values.mask(special_mask)
    numeric = pd.to_numeric(ordinary, errors="coerce").dropna()
    return {
        "row_count": int(len(values)),
        "missing_count": int(values.isna().sum()),
        "distinct_count": int(ordinary.nunique(dropna=True)),
        "mean": float(numeric.mean()) if len(numeric) else None,
        "standard_deviation": float(numeric.std(ddof=0)) if len(numeric) else None,
        "minimum": float(numeric.min()) if len(numeric) else None,
        "median": float(numeric.median()) if len(numeric) else None,
        "maximum": float(numeric.max()) if len(numeric) else None,
    }


def _manifest_hash(payload: dict[str, Any]) -> str:
    stable = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return f"fm-{hashlib.sha256(stable.encode('utf-8')).hexdigest()[:16]}"


def _materialization_hash(
    manifest_hash: str,
    identity: dict[str, Any],
    row_count: int,
    materialized_features: list[str],
) -> str:
    stable = json.dumps(
        {
            "manifest_hash": manifest_hash,
            "project_id": identity["project_id"],
            "dataset_id": identity["dataset_id"],
            "dataset_version_id": identity["dataset_version_id"],
            "row_count": row_count,
            "materialized_features": materialized_features,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"mt-{hashlib.sha256(stable.encode('utf-8')).hexdigest()[:16]}"


def _manifest_contract_payload(
    identity: dict[str, Any],
    features: list[dict[str, Any]],
    pipeline_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return only user-governed definition fields.

    Runtime status, profiling summaries, timestamps, and evidence references are
    deliberately excluded so materialization cannot make an unchanged contract
    appear stale.
    """

    feature_keys = (
        "feature_id",
        "feature_name",
        "display_name",
        "origin",
        "source_features",
        "transformation_type",
        "formula_or_rule",
        "output_datatype",
        "config",
        "selected",
        "exclusion_reason",
        "user_rationale",
    )
    pipeline_keys = (
        "step_id",
        "transformation_type",
        "selected_features",
        "config",
        "enabled",
        "fit_scope",
    )
    return {
        "project_id": identity["project_id"],
        "dataset_id": identity["dataset_id"],
        "dataset_version_id": identity["dataset_version_id"],
        # Compatibility alias derived only from the canonical version ID.
        "dataset_version": identity["dataset_version_id"],
        "features": [
            {key: row.get(key) for key in feature_keys}
            for row in features
        ],
        "pipeline_steps": [
            {key: row.get(key) for key in pipeline_keys}
            for row in pipeline_steps
        ],
    }


def _execution_event(
    stage: str,
    status: str,
    manifest_hash: str,
    detail: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": status,
        "manifest_hash": manifest_hash,
        "detail": detail,
        "recorded_at": _now(),
        **extra,
    }


def _existing_manifest() -> dict[str, Any]:
    manifest = DATASTORE.meta.get("feature_manifest")
    return manifest if isinstance(manifest, dict) else {}


def _persist_manifest(identity: dict[str, Any], manifest: dict[str, Any]) -> None:
    persisted = persist_manifest_version(identity, manifest)
    manifest["persistence_status"] = "persisted"
    manifest["definition_checksum"] = persisted["definition_checksum"]


def _semantic_unit(name: str) -> str:
    normalized = str(name or "").casefold()
    if normalized.startswith("percent"):
        return "percentage"
    if "fraction" in normalized:
        return "ratio"
    if normalized.startswith("num") or "trade_count" in normalized:
        return "count"
    if normalized.startswith("msince") or "month" in normalized or normalized == "averageminfile":
        return "months"
    if normalized.startswith("maxdelq"):
        return "ordinal_code"
    if "estimate" in normalized or "score" in normalized:
        return "score"
    return "unknown"


def _ordinary_numeric(frame: pd.DataFrame, name: str) -> pd.Series:
    values = pd.to_numeric(frame[name], errors="coerce")
    return values.mask(bureau_special_mask(values))


def _is_governed_date_source(frame: pd.DataFrame, name: str) -> bool:
    """Use the shared ATLAS date contract for source fields.

    CSV readers retain calendar text as ``object``.  Requiring a pandas
    datetime dtype here made the Date Derived builder unavailable even when
    Data Quality and EDA had already verified the same ISO date field.  The
    shared rule remains conservative: numeric durations never qualify, and
    text requires a date-like name plus a high supported-format parse rate.
    """

    return bool(name in frame.columns and governed_time_field(name, frame[name]))


def _governed_source_datatype(frame: pd.DataFrame, name: str) -> str:
    if _is_governed_date_source(frame, name):
        return "datetime64[ns]"
    return str(frame[name].dtype)


def _validate_engineered_definition(
    item: FeatureDefinitionInput,
    frame: pd.DataFrame,
) -> None:
    origin = item.origin
    sources = list(item.source_features)
    config = item.config or {}
    if item.transformation_type and item.transformation_type != origin:
        raise ValueError(
            f"Feature '{item.feature_name}' has a transformation type that does not match its builder."
        )

    def require_sources(count: int, label: str) -> None:
        if len(sources) != count:
            raise ValueError(
                f"Feature '{item.feature_name}' {label} requires exactly {count} source predictor{'s' if count != 1 else ''}."
            )

    def require_numeric() -> None:
        nonnumeric = [
            source
            for source in sources
            if source in frame.columns and not is_numeric_dtype(frame[source])
        ]
        if nonnumeric:
            raise ValueError(
                f"Feature '{item.feature_name}' requires numeric sources; invalid: {', '.join(nonnumeric)}."
            )

    if origin == "interaction":
        require_sources(2, "interaction")
        require_numeric()
        if sources[0].casefold() == sources[1].casefold():
            raise ValueError("Interaction features require two different source predictors.")
    elif origin == "numeric_bin":
        require_sources(1, "numeric-bin")
        require_numeric()
        mode = str(config.get("binning_mode") or "custom")
        if mode not in {"custom", "quantile"}:
            raise ValueError("Numeric-bin mode must be custom or quantile.")
        points_key = "cut_points" if mode == "custom" else "quantiles"
        points = [float(value) for value in config.get(points_key, [])]
        if not points:
            raise ValueError("Numeric bins require at least one governed cut point.")
        if points != sorted(set(points)):
            raise ValueError("Numeric-bin cut points must be unique and strictly increasing.")
        if mode == "quantile" and any(value <= 0 or value >= 1 for value in points):
            raise ValueError("Numeric-bin quantiles must be strictly between 0 and 1.")
        labels = [str(value).strip() for value in config.get("labels", [])]
        if len(labels) != len(points) + 1 or any(not value for value in labels):
            raise ValueError(
                "Numeric-bin labels must contain exactly one non-empty label more than the cut points."
            )
        if not str(config.get("missing_label") or "").strip():
            raise ValueError(
                "Numeric bins require a separate bureau-special or missing-value label."
            )
    elif origin == "categorical_rule":
        require_sources(1, "rule-category")
        rules = config.get("rules") or []
        if not isinstance(rules, list) or not rules:
            raise ValueError("Rule categories require at least one explicit rule.")
        supported = {
            "equals",
            "contains",
            "greater_than",
            "greater_than_or_equal",
            "less_than",
            "less_than_or_equal",
            "is_missing",
        }
        for rule in rules:
            operator = str((rule or {}).get("op") or "")
            if operator not in supported:
                raise ValueError(f"Unsupported categorical rule operator '{operator}'.")
            if operator in {
                "greater_than",
                "greater_than_or_equal",
                "less_than",
                "less_than_or_equal",
            }:
                require_numeric()
                try:
                    float((rule or {}).get("value"))
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "Numeric rule-category thresholds must be valid numbers."
                    ) from exc
        if not config.get("preserve_bureau_special_values", True) and not str(
            config.get("special_label") or ""
        ).strip():
            raise ValueError(
                "Rule categories must preserve bureau special values or define an explicit special-value label."
            )
    elif origin == "polynomial":
        require_sources(1, "polynomial")
        require_numeric()
        if int(config.get("degree") or 0) not in {2, 3}:
            raise ValueError("Polynomial degree must be 2 or 3.")
    elif origin == "arithmetic":
        require_sources(2, "arithmetic")
        require_numeric()
        operation = str(config.get("operation") or "")
        if operation not in {"add", "subtract", "multiply", "divide"}:
            raise ValueError(f"Unsupported arithmetic operation '{operation}'.")
        left_unit = str(config.get("left_unit") or _semantic_unit(sources[0]))
        right_unit = str(config.get("right_unit") or _semantic_unit(sources[1]))
        if operation in {"add", "subtract"} and (
            left_unit == "unknown"
            or right_unit == "unknown"
            or left_unit != right_unit
        ):
            raise ValueError(
                "Arithmetic addition and subtraction require source predictors with compatible governed units."
            )
        if operation == "divide" and str(
            config.get("zero_denominator_policy") or "return_null"
        ) != "return_null":
            raise ValueError(
                "Arithmetic division must use the governed return-null policy for zero denominators."
            )
        result_domain = str(config.get("result_domain") or "unrestricted")
        if result_domain not in {"unrestricted", "nonnegative"}:
            raise ValueError("Arithmetic result domain must be unrestricted or nonnegative.")
        if result_domain == "nonnegative" and all(source in frame.columns for source in sources):
            left = _ordinary_numeric(frame, sources[0])
            right = _ordinary_numeric(frame, sources[1])
            if operation == "add":
                result = left + right
            elif operation == "subtract":
                result = left - right
            elif operation == "multiply":
                result = left * right
            else:
                result = left / right.replace(0, np.nan)
            if bool((result.dropna() < 0).any()):
                raise ValueError(
                    "Arithmetic result violates the governed nonnegative domain."
                )
    elif origin == "date-derived":
        require_sources(1, "date-derived")
        if not _is_governed_date_source(frame, sources[0]):
            raise ValueError(
                "Date Derived requires a governed date or timestamp predictor; numeric duration fields are not dates."
            )
        if str(config.get("component") or "") not in {
            "year",
            "month",
            "quarter",
            "day_of_week",
        }:
            raise ValueError("Unsupported date-derived component.")
    else:
        raise ValueError(
            f"Feature origin '{origin}' is not an available deterministic builder."
        )


def _identity_fields(identity: dict[str, Any]) -> dict[str, str]:
    return {
        "project_id": str(identity["project_id"]),
        "dataset_id": str(identity["dataset_id"]),
        "dataset_version_id": str(identity["dataset_version_id"]),
        # Transitional response compatibility only.
        "dataset_version": str(identity["dataset_version_id"]),
    }


def _active_identity(
    project_id: str = "",
    *,
    expected_dataset_id: str = "",
    expected_dataset_version_id: str = "",
    legacy_dataset_version: str = "",
    require_expected: bool = False,
) -> dict[str, Any]:
    resolved_project_id = str(
        project_id
        or active_project_id()
        or DATASTORE.meta.get("project_id")
        or ""
    ).strip()
    if require_expected or (
        expected_dataset_id
        or expected_dataset_version_id
        or legacy_dataset_version
    ):
        return assert_expected_active_identity(
            resolved_project_id,
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_dataset_version_id,
            legacy_dataset_version=legacy_dataset_version,
            require_expected=require_expected,
        )
    return active_dataset_identity(resolved_project_id)


def _revalidate_identity(identity: dict[str, Any]) -> dict[str, Any]:
    """Fail closed if activation changed while a feature operation was running."""
    return _active_identity(
        str(identity["project_id"]),
        expected_dataset_id=str(identity["dataset_id"]),
        expected_dataset_version_id=str(identity["dataset_version_id"]),
    )


def _assert_data_revision(
    store: Any,
    expected_revision: int,
    operation: str,
) -> None:
    if int(store.data_revision) != int(expected_revision):
        raise ValueError(
            "The governed dataset or preparation state changed while "
            f"{operation}. Reload the current feature contract and try again."
        )


def _assert_record_identity(
    record: dict[str, Any],
    identity: dict[str, Any],
    label: str,
) -> None:
    if not record:
        return
    expected = _identity_fields(identity)
    missing = [
        key
        for key in ("project_id", "dataset_id", "dataset_version_id")
        if not str(record.get(key) or "").strip()
    ]
    mismatched = [
        key
        for key in ("project_id", "dataset_id", "dataset_version_id")
        if str(record.get(key) or "").strip()
        and str(record.get(key)) != expected[key]
    ]
    legacy_version = str(record.get("dataset_version") or "").strip()
    if legacy_version and legacy_version != expected["dataset_version_id"]:
        mismatched.append("dataset_version")
    if missing or mismatched:
        detail = (
            f"The stored {label} is not bound to the exact active Dataset "
            "Library version. Recreate it for the current dataset."
        )
        raise ValueError(detail)


def _source_selection_for_authorization(frame: pd.DataFrame) -> list[str]:
    """Return the governed source set independently of downstream outputs.

    ``selected_columns`` becomes the downstream model feature list after a
    Feature Manifest save, so it can contain engineered outputs and omit
    reviewer-deselected original predictors. Once a manifest exists, its
    original-row eligibility is the stable record of which source columns were
    authorized upstream. Keeping that source set separate prevents an immediate
    manifest refresh from changing original eligibility, exclusion reasons, or
    the saved contract hash.
    """

    frame_columns = {str(column) for column in frame.columns}
    original_rows = [
        row
        for row in _existing_manifest().get("features", [])
        if isinstance(row, dict) and row.get("origin") == "original"
    ]
    if original_rows:
        return [
            str(row.get("feature_name"))
            for row in original_rows
            if row.get("eligibility_status") == "eligible"
            and str(row.get("feature_name")) in frame_columns
        ]

    prior_materialized = set(
        DATASTORE.meta.get("materialized_feature_names") or []
    )
    target = str(DATASTORE.target or "")
    return [
        name
        for name in DATASTORE.get_selected_columns()
        if name in frame_columns
        and name not in prior_materialized
        and name != target
    ]


def _base_columns() -> list[str]:
    df = DATASTORE.get_base_df()
    if df is None:
        return []
    prior_materialized = set(DATASTORE.meta.get("materialized_feature_names") or [])
    source = df.drop(columns=[name for name in prior_materialized if name in df.columns], errors="ignore")
    authorization = governed_predictor_authorization(
        source,
        target=DATASTORE.target,
        selected_columns=_source_selection_for_authorization(source),
    )
    return list(authorization["authorized_predictors"])


def _source_authorization(df: pd.DataFrame | None = None) -> dict[str, Any]:
    source = df if df is not None else DATASTORE.get_base_df()
    if source is None:
        return {
            "authorized_predictors": [],
            "excluded_predictors": {},
            "target_source_excluded": [],
        }
    prior_materialized = set(DATASTORE.meta.get("materialized_feature_names") or [])
    source = source.drop(
        columns=[name for name in prior_materialized if name in source.columns],
        errors="ignore",
    )
    authorization = governed_predictor_authorization(
        source,
        target=DATASTORE.target,
        selected_columns=_source_selection_for_authorization(source),
    )
    raw = DATASTORE.raw_df
    if raw is None or raw.empty:
        return authorization
    full = governed_predictor_authorization(
        raw,
        target=DATASTORE.target,
        selected_columns=_source_selection_for_authorization(raw),
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


def _original_feature_rows(identity: dict[str, Any]) -> list[dict[str, Any]]:
    df = DATASTORE.get_base_df()
    if df is None:
        return []
    selected = set(DATASTORE.get_selected_columns())
    target = str(DATASTORE.target or "")
    prior_materialized = set(DATASTORE.meta.get("materialized_feature_names") or [])
    existing = {row.get("feature_name"): row for row in _existing_manifest().get("features", []) if isinstance(row, dict)}
    authorization = _source_authorization(df)
    authorized = set(authorization["authorized_predictors"])
    excluded = dict(authorization["excluded_predictors"])
    rows: list[dict[str, Any]] = []
    for column in df.columns:
        name = str(column)
        if name == target or name in prior_materialized:
            continue
        prior = existing.get(name, {})
        eligible = name in authorized and not _SPLIT_FIELD.search(name)
        exclusion_reason = ""
        if not eligible:
            exclusion_reason = excluded.get(name) or "Split or fold metadata cannot be used as a predictor."
        selected_by_manifest = (
            bool(prior.get("selected"))
            if "selected" in prior
            else bool(not selected or name in selected)
        )
        selected_for_model = bool(eligible and selected_by_manifest)
        if eligible and not selected_for_model:
            exclusion_reason = str(prior.get("exclusion_reason") or "")
        rows.append({
            **_identity_fields(identity),
            "feature_name": name,
            "display_name": prior.get("display_name") or name,
            "feature_id": prior.get("feature_id") or f"original-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:12]}",
            "origin": "original",
            "source_features": [name],
            "transformation_type": "source_column",
            "formula_or_rule": name,
            "output_datatype": _governed_source_datatype(df, name),
            "creation_status": "available",
            "materialization_status": "source",
            "pipeline_status": "not_applicable",
            "eligibility_status": "eligible" if eligible else "excluded",
            "leakage_status": "reviewed" if eligible else "locked",
            "selected": selected_for_model,
            "exclusion_reason": exclusion_reason,
            "created_at": prior.get("created_at") or _now(),
            "created_by": prior.get("created_by") or "Data Acquisition",
            "transformation_version": "source-v1",
            "profile_scope": "full_dataset",
            "summary_statistics": _feature_summary_statistics(df[column]),
            "evidence_reference": prior.get("evidence_reference"),
            "config": {},
            "user_rationale": prior.get("user_rationale") or "",
        })
    return rows


def _normalize_engineered(
    item: FeatureDefinitionInput,
    df_columns: set[str],
    existing_names: set[str],
    identity: dict[str, Any],
) -> dict[str, Any]:
    name = item.feature_name.strip()
    if not _VALID_NAME.fullmatch(name):
        raise ValueError(f"Feature name '{name}' must start with a letter or underscore and contain only letters, numbers, or underscores.")
    comparable_names = {value.casefold() for value in existing_names | df_columns}
    if name.casefold() in comparable_names:
        raise ValueError(f"Feature name '{name}' already exists.")
    target = str(DATASTORE.target or "")
    if name.casefold() == target.casefold() or any(source.casefold() == target.casefold() for source in item.source_features):
        raise ValueError(f"Feature '{name}' cannot use the target column.")
    authorization = _source_authorization()
    excluded = {
        str(source).casefold(): str(reason)
        for source, reason in authorization.get("excluded_predictors", {}).items()
    }
    unsafe_sources = [
        source
        for source in item.source_features
        if source.casefold() in excluded
    ]
    if unsafe_sources:
        detail = "; ".join(
            f"{source}: {excluded[source.casefold()]}"
            for source in unsafe_sources
        )
        raise ValueError(f"Feature '{name}' uses an excluded predictor ({detail}).")
    if any(_SPLIT_FIELD.search(source) for source in item.source_features):
        raise ValueError(f"Feature '{name}' cannot use split or fold metadata.")
    missing_sources = [source for source in item.source_features if source not in df_columns and source not in existing_names]
    if missing_sources:
        raise ValueError(f"Feature '{name}' references unavailable source columns: {', '.join(missing_sources)}.")
    if any(source.casefold() == name.casefold() for source in item.source_features):
        raise ValueError(f"Feature '{name}' cannot depend on itself.")
    validation_frame = DATASTORE.get_base_df()
    if validation_frame is None:
        raise ValueError("No full backend dataset is loaded.")
    _validate_engineered_definition(item, validation_frame)
    generated_id = hashlib.sha256(
        (
            f"{identity['project_id']}:{identity['dataset_id']}:"
            f"{identity['dataset_version_id']}:{name.casefold()}"
        ).encode("utf-8")
    ).hexdigest()[:16]
    row = item.model_dump()
    row.update({
        **_identity_fields(identity),
        "feature_id": item.feature_id or f"feature-{generated_id}",
        "display_name": item.display_name or name,
        "creation_status": "planned",
        "materialization_status": "not_materialized",
        "pipeline_status": "not_applicable",
        "eligibility_status": "eligible",
        "leakage_status": "reviewed",
        "created_at": _now(),
        "created_by": "Current ATLAS user",
        "transformation_version": "1",
        "profile_scope": "not_profiled",
        "summary_statistics": {},
        "evidence_reference": None,
    })
    return row


def get_manifest(
    project_id: str = "",
    *,
    expected_dataset_id: str = "",
    expected_dataset_version_id: str = "",
    legacy_dataset_version: str = "",
) -> dict[str, Any]:
    identity = _active_identity(
        project_id,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version_id=expected_dataset_version_id,
        legacy_dataset_version=legacy_dataset_version,
        require_expected=True,
    )
    existing = _existing_manifest()
    if not existing:
        durable = load_current_manifest(identity)
        if durable:
            existing = durable
            DATASTORE.meta["feature_manifest"] = existing
            DATASTORE.meta["materialized_feature_names"] = [
                str(row.get("feature_name"))
                for row in durable.get("features", [])
                if isinstance(row, dict)
                and row.get("origin") != "original"
                and row.get("selected")
                and row.get("eligibility_status") == "eligible"
                and row.get("materialization_status") == "materialized"
            ]
            if durable.get("preview_hash"):
                DATASTORE.meta["feature_preview"] = {
                    **_identity_fields(identity),
                    "preview_hash": durable["preview_hash"],
                    "manifest_hash": durable.get("manifest_hash"),
                    "previewed_at": durable.get("updated_at"),
                }
    _assert_record_identity(existing, identity, "feature manifest")
    originals = _original_feature_rows(identity)
    engineered = [
        {**row, **_identity_fields(identity)}
        for row in existing.get("features", [])
        if isinstance(row, dict) and row.get("origin") != "original"
    ]
    payload = {
        **_identity_fields(identity),
        "features": originals + engineered,
        "pipeline_steps": existing.get("pipeline_steps", []),
    }
    contract_payload = _manifest_contract_payload(
        identity,
        payload["features"],
        payload["pipeline_steps"],
    )
    version = _manifest_hash(contract_payload)
    engineered_rows = [
        row for row in payload["features"] if row.get("origin") != "original"
    ]
    legacy_materialized = bool(engineered_rows) and all(
        row.get("materialization_status") == "materialized"
        for row in engineered_rows
    )
    materialized_manifest_hash = str(
        existing.get("materialized_manifest_hash") or ""
    )
    materialization_hash = str(existing.get("materialization_hash") or "")
    if legacy_materialized and not materialized_manifest_hash:
        base_df = DATASTORE.get_base_df()
        materialized_manifest_hash = version
        materialization_hash = materialization_hash or _materialization_hash(
            version,
            identity,
            len(base_df) if base_df is not None else 0,
            [row["feature_name"] for row in engineered_rows],
        )
    materialization_status = str(
        existing.get("materialization_status") or "not_materialized"
    )
    if materialized_manifest_hash:
        materialization_status = (
            "current" if materialized_manifest_hash == version else "stale"
        )
    expected_materialized_outputs = [
        str(row.get("feature_name"))
        for row in engineered_rows
        if row.get("selected")
        and row.get("eligibility_status") == "eligible"
        and row.get("materialization_status") == "materialized"
    ]
    processed_columns = set(
        str(column)
        for column in (
            DATASTORE.current().processed_df.columns
            if DATASTORE.current().processed_df is not None
            else []
        )
    )
    if (
        materialization_status == "current"
        and expected_materialized_outputs
        and not set(expected_materialized_outputs).issubset(processed_columns)
    ):
        materialization_status = "stale"
    manifest = {
        "ok": True,
        "manifest_version": version,
        "manifest_hash": version,
        **_identity_fields(identity),
        "features": payload["features"],
        "pipeline_steps": payload["pipeline_steps"],
        "created_at": existing.get("created_at") or _now(),
        "updated_at": existing.get("updated_at") or _now(),
        "validation_status": existing.get("validation_status") or "passed",
        "validated_at": existing.get("validated_at") or _now(),
        "materialization_status": materialization_status,
        "materialization_hash": materialization_hash,
        "materialized_manifest_hash": materialized_manifest_hash,
        "materialized_at": existing.get("materialized_at"),
        "confirmation_status": (
            "confirmed"
            if existing.get("confirmed_manifest_hash") == version
            else "required"
        ),
        "confirmed_manifest_hash": str(
            existing.get("confirmed_manifest_hash") or ""
        ),
        "confirmed_at": existing.get("confirmed_at"),
        "preview_hash": (
            str((DATASTORE.meta.get("feature_preview") or {}).get("preview_hash") or "")
            if (DATASTORE.meta.get("feature_preview") or {}).get("manifest_hash") == version
            else str(existing.get("preview_hash") or "")
            if existing.get("manifest_hash") == version
            else ""
        ),
        "execution_history": list(existing.get("execution_history") or []),
        "split_status": existing.get("split_status") or DATASTORE.meta.get("split_status") or "not_created",
        "predictor_authorization": _source_authorization(),
        "persistence_status": (
            "persisted"
            if existing.get("persistence_status") == "persisted"
            or bool(existing.get("definition_checksum"))
            else "not_persisted"
        ),
        "definition_checksum": str(existing.get("definition_checksum") or ""),
    }
    _revalidate_identity(identity)
    return manifest


def update_manifest(request: FeatureManifestUpdateRequest) -> dict[str, Any]:
    scoped_store = DATASTORE.current()
    identity = _active_identity(
        request.project_id,
        expected_dataset_id=request.dataset_id,
        expected_dataset_version_id=request.dataset_version_id,
        legacy_dataset_version=request.dataset_version,
        require_expected=True,
    )
    with scoped_store.state_lock:
        input_revision = int(scoped_store.data_revision)
    df = DATASTORE.get_base_df()
    if df is None or df.empty:
        raise ValueError("No full backend dataset is loaded.")
    prior = get_manifest(
        identity["project_id"],
        expected_dataset_id=identity["dataset_id"],
        expected_dataset_version_id=identity["dataset_version_id"],
    )
    prior_by_id = {row.get("feature_id"): row for row in prior["features"] if row.get("origin") != "original"}
    originals = _original_feature_rows(identity)
    requested_originals = {
        item.feature_name: item
        for item in request.features
        if item.origin == "original"
    }
    for original in originals:
        requested = requested_originals.get(original["feature_name"])
        if requested and original["eligibility_status"] == "eligible":
            original["selected"] = bool(requested.selected)
            original["exclusion_reason"] = requested.exclusion_reason if not requested.selected else ""
    df_columns = set(_base_columns())
    engineered: list[dict[str, Any]] = []
    names: set[str] = set()
    for item in request.features:
        if item.origin == "original":
            continue
        row = _normalize_engineered(item, df_columns, names, identity)
        previous = prior_by_id.get(row["feature_id"])
        if previous and previous.get("feature_name") == row["feature_name"]:
            for key in ("created_at", "materialization_status", "creation_status", "summary_statistics", "profile_scope"):
                row[key] = previous.get(key, row.get(key))
        names.add(row["feature_name"])
        engineered.append(row)
    pipeline_steps = []
    for index, step in enumerate(request.pipeline_steps):
        step_payload = step.model_dump()
        stable_step_id = hashlib.sha256(
            json.dumps(
                {
                    "project_id": identity["project_id"],
                    "dataset_id": identity["dataset_id"],
                    "dataset_version_id": identity["dataset_version_id"],
                    "index": index,
                    "step": step_payload,
                },
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        pipeline_steps.append({
            **step_payload,
            "step_id": step.step_id or f"pipeline-{index + 1}-{stable_step_id}",
            "fit_scope": "training_only",
            "status": "configured" if step.enabled else "disabled",
        })
    payload = {
        **_identity_fields(identity),
        "features": originals + engineered,
        "pipeline_steps": pipeline_steps,
    }
    version = _manifest_hash(
        _manifest_contract_payload(
            identity,
            payload["features"],
            pipeline_steps,
        )
    )
    changed = version != prior.get("manifest_hash", prior.get("manifest_version"))
    prior_materialized_manifest_hash = str(
        prior.get("materialized_manifest_hash") or ""
    )
    execution_history = list(prior.get("execution_history") or [])
    execution_history.append(
        _execution_event(
            "validate_definitions",
            "passed",
            version,
            f"Validated {len(payload['features'])} feature definitions and {len(pipeline_steps)} training-only pipeline steps.",
        )
    )
    execution_history.append(
        _execution_event(
            "save_manifest",
            "completed",
            version,
            "Saved the governed feature contract.",
            previous_manifest_hash=prior.get("manifest_hash", prior.get("manifest_version")),
            contract_changed=changed,
        )
    )
    materialization_status = str(
        prior.get("materialization_status") or "not_materialized"
    )
    if changed and prior_materialized_manifest_hash:
        materialization_status = "stale"
        for row in engineered:
            if row.get("materialization_status") == "materialized":
                row["materialization_status"] = "stale"
    elif prior_materialized_manifest_hash == version:
        materialization_status = "current"
    manifest = {
        "ok": True,
        "manifest_version": version,
        "manifest_hash": version,
        **_identity_fields(identity),
        "features": payload["features"],
        "pipeline_steps": pipeline_steps,
        "created_at": prior.get("created_at") or _now(),
        "updated_at": _now(),
        "validation_status": "passed",
        "validated_at": _now(),
        "materialization_status": materialization_status,
        "materialization_hash": prior.get("materialization_hash") or "",
        "materialized_manifest_hash": prior_materialized_manifest_hash,
        "materialized_at": prior.get("materialized_at"),
        "confirmation_status": (
            "confirmed"
            if not changed and prior.get("confirmed_manifest_hash") == version
            else "required"
        ),
        "confirmed_manifest_hash": (
            str(prior.get("confirmed_manifest_hash") or "")
            if not changed
            else ""
        ),
        "confirmed_at": prior.get("confirmed_at") if not changed else None,
        "preview_hash": "",
        "execution_history": execution_history[-40:],
        "split_status": (
            "stale"
            if changed
            and (
                DATASTORE.X_train is not None
                or str(prior.get("split_status") or DATASTORE.meta.get("split_status"))
                in {"current", "stale"}
                or bool(DATASTORE.meta.get("validation_design"))
                or bool(DATASTORE.meta.get("split_record"))
            )
            else prior.get("split_status", "not_created")
        ),
        "predictor_authorization": _source_authorization(df),
    }
    with scoped_store.state_lock:
        _revalidate_identity(identity)
        _assert_data_revision(
            scoped_store,
            input_revision,
            "the feature manifest was being updated",
        )
        had_split = scoped_store.X_train is not None
        scoped_store.meta["feature_manifest"] = manifest
        scoped_store.meta["selected_columns"] = [
            row["feature_name"]
            for row in manifest["features"]
            if row.get("selected") and row.get("eligibility_status") == "eligible"
        ]
        if changed:
            scoped_store.meta.pop("feature_preview", None)
            invalidate_downstream_training_state(
                "The governed feature manifest changed.",
                store=scoped_store,
                split_status="stale" if had_split else "not_created",
            )
        _persist_manifest(identity, manifest)
    schedule_checkpoint_save()
    return manifest


def _apply_feature(frame: pd.DataFrame, feature: dict[str, Any]) -> pd.Series:
    origin = feature["origin"]
    sources = feature.get("source_features") or []
    config = feature.get("config") or {}
    if origin == "interaction":
        if len(sources) != 2:
            raise ValueError("Interaction features require exactly two source variables.")
        left = pd.to_numeric(frame[sources[0]], errors="coerce")
        right = pd.to_numeric(frame[sources[1]], errors="coerce")
        output = left * right
        if config.get("preserve_bureau_special_values", True):
            left_special = bureau_special_mask(left)
            right_special = bureau_special_mask(right)
            sentinel = left.where(left_special, right)
            output = output.where(~(left_special | right_special), sentinel)
        return output
    if origin == "polynomial":
        if len(sources) != 1:
            raise ValueError("Polynomial features require one source variable.")
        degree = int(config.get("degree") or 2)
        if degree not in {2, 3}:
            raise ValueError("Polynomial degree must be 2 or 3.")
        source = pd.to_numeric(frame[sources[0]], errors="coerce")
        output = source ** degree
        if config.get("preserve_bureau_special_values", True):
            output = output.where(~bureau_special_mask(source), source)
        return output
    if origin == "numeric_bin":
        if len(sources) != 1:
            raise ValueError("Numeric bins require one source variable.")
        numeric_source = pd.to_numeric(frame[sources[0]], errors="coerce")
        ordinary_source = numeric_source.mask(bureau_special_mask(numeric_source))
        if str(config.get("binning_mode") or "custom") == "quantile":
            fitted = feature.get("materialization_parameters") or {}
            fitted_cut_points = fitted.get("fitted_cut_points")
            if isinstance(fitted_cut_points, list) and fitted_cut_points:
                cut_points = sorted({float(value) for value in fitted_cut_points})
            else:
                quantiles = [
                    float(value)
                    for value in config.get("quantiles", [0.2, 0.4, 0.6, 0.8])
                    if 0 < float(value) < 1
                ]
                cut_points = sorted(
                    {
                        float(ordinary_source.quantile(value))
                        for value in quantiles
                        if pd.notna(ordinary_source.quantile(value))
                    }
                )
        else:
            cut_points = sorted(float(value) for value in config.get("cut_points", []))
        if not cut_points:
            raise ValueError("Numeric bins require at least one cut point.")
        labels = [str(value) for value in config.get("labels", [])]
        if (
            labels
            and len(labels) != len(cut_points) + 1
            and str(config.get("binning_mode") or "custom") == "quantile"
        ):
            labels = []
        if labels and len(labels) != len(cut_points) + 1:
            raise ValueError("Numeric-bin labels must contain one more value than cut points.")
        output = pd.cut(numeric_source, bins=[-np.inf, *cut_points, np.inf], labels=labels or None, include_lowest=True)
        if config.get("preserve_bureau_special_values", True):
            output = output.astype("object")
            special_label = str(config.get("special_value_label") or "").strip()
            for special in (-9.0, -8.0, -7.0):
                output.loc[numeric_source == special] = (
                    special_label or f"Bureau special {int(special)}"
                )
        if config.get("missing_label"):
            output = output.astype("object").where(output.notna(), str(config["missing_label"]))
        return output
    if origin == "categorical_rule":
        if len(sources) != 1:
            raise ValueError("Categorical rules require one source variable.")
        source = frame[sources[0]]
        output = pd.Series(str(config.get("else_label") or "Other"), index=frame.index, dtype="object")
        for rule in config.get("rules", []):
            op = str(rule.get("op") or "equals")
            value = rule.get("value")
            if op == "equals":
                mask = source.astype(str) == str(value)
            elif op == "contains":
                mask = source.astype(str).str.contains(str(value), case=False, na=False)
            elif op == "greater_than":
                mask = pd.to_numeric(source, errors="coerce") > float(value)
            elif op == "greater_than_or_equal":
                mask = pd.to_numeric(source, errors="coerce") >= float(value)
            elif op == "less_than":
                mask = pd.to_numeric(source, errors="coerce") < float(value)
            elif op == "less_than_or_equal":
                mask = pd.to_numeric(source, errors="coerce") <= float(value)
            elif op == "is_missing":
                mask = source.isna()
            else:
                raise ValueError(f"Unsupported categorical rule operator '{op}'.")
            output.loc[mask] = str(rule.get("then_label") or "Matched")
        if config.get("preserve_bureau_special_values", True):
            numeric_source = pd.to_numeric(source, errors="coerce")
            special_label = str(
                config.get("special_value_label")
                or config.get("special_label")
                or ""
            ).strip()
            for special in (-9.0, -8.0, -7.0):
                output.loc[numeric_source == special] = (
                    special_label or f"Bureau special {int(special)}"
                )
        return output
    if origin == "arithmetic":
        if len(sources) != 2:
            raise ValueError("Arithmetic features require exactly two source variables.")
        left = pd.to_numeric(frame[sources[0]], errors="coerce")
        right = pd.to_numeric(frame[sources[1]], errors="coerce")
        operation = str(config.get("operation") or "add")
        if operation == "add":
            output = left + right
        elif operation == "subtract":
            output = left - right
        elif operation == "multiply":
            output = left * right
        elif operation == "divide":
            output = left / right.replace(0, np.nan)
        else:
            raise ValueError(f"Unsupported arithmetic operation '{operation}'.")
        if config.get("preserve_bureau_special_values", True):
            left_special = bureau_special_mask(left)
            right_special = bureau_special_mask(right)
            sentinel = left.where(left_special, right)
            output = output.where(~(left_special | right_special), sentinel)
        return output
    if origin == "date-derived":
        if len(sources) != 1:
            raise ValueError("Date-derived features require one source variable.")
        parsed = pd.to_datetime(frame[sources[0]], errors="coerce")
        component = str(config.get("component") or "year")
        if component == "year":
            return parsed.dt.year
        if component == "month":
            return parsed.dt.month
        if component == "day_of_week":
            return parsed.dt.dayofweek
        if component == "quarter":
            return parsed.dt.quarter
        raise ValueError(f"Unsupported date component '{component}'.")
    raise ValueError(f"Feature origin '{origin}' is not a deterministic materialization type.")


def materialize_external_scoring_frame(
    frame: pd.DataFrame,
    manifest: dict[str, Any],
    *,
    model_features: list[str],
    expected_project_id: str,
    expected_dataset_id: str,
    expected_dataset_version_id: str,
    expected_manifest_hash: str,
) -> dict[str, Any]:
    """Reapply one exact governed feature contract to an external raw frame.

    This is deliberately a pure scoring-boundary operation: it copies the
    caller's frame, reads no DatasetStore state, writes no manifest/runtime
    state, and never accepts a target or partition.  Uploaded engineered
    columns are overwritten from their governed definitions so callers cannot
    substitute unverified derived values for the transformations used during
    training.
    """

    if frame is None or frame.empty:
        raise ValueError("External scoring requires a non-empty raw feature frame.")
    if not isinstance(manifest, dict):
        raise ValueError(
            "The exact training Feature Manifest is unavailable; external scoring is blocked."
        )

    expected_identity = {
        "project_id": str(expected_project_id or "").strip(),
        "dataset_id": str(expected_dataset_id or "").strip(),
        "dataset_version_id": str(expected_dataset_version_id or "").strip(),
    }
    missing_identity = [key for key, value in expected_identity.items() if not value]
    if missing_identity:
        raise ValueError(
            "The final model is missing exact training identity required for external scoring: "
            + ", ".join(missing_identity)
            + "."
        )
    for key, expected in expected_identity.items():
        actual = str(
            manifest.get(key)
            or (manifest.get("dataset_version") if key == "dataset_version_id" else "")
            or ""
        ).strip()
        if actual != expected:
            raise ValueError(
                f"The external scoring Feature Manifest does not match the final model {key}."
            )

    manifest_hash = str(
        manifest.get("manifest_hash") or manifest.get("manifest_version") or ""
    ).strip()
    expected_hash = str(expected_manifest_hash or "").strip()
    if not expected_hash or manifest_hash != expected_hash:
        raise ValueError(
            "The external scoring Feature Manifest does not match the exact training manifest."
        )
    if str(manifest.get("confirmation_status") or "").casefold() != "confirmed":
        raise ValueError(
            "The exact training Feature Manifest is not confirmed; external scoring is blocked."
        )
    if str(manifest.get("confirmed_manifest_hash") or "") != manifest_hash:
        raise ValueError(
            "The confirmed Feature Manifest hash does not match the exact training manifest."
        )
    if str(manifest.get("materialization_status") or "").casefold() != "current":
        raise ValueError(
            "The exact training Feature Manifest is not currently materialized."
        )
    if str(manifest.get("materialized_manifest_hash") or "") != manifest_hash:
        raise ValueError(
            "The materialized Feature Manifest hash does not match the exact training manifest."
        )

    governed_rows = [
        deepcopy(row)
        for row in (manifest.get("features") or [])
        if isinstance(row, dict)
        and row.get("selected") is True
        and str(row.get("eligibility_status") or "").casefold() == "eligible"
    ]
    engineered = {
        str(row.get("feature_name") or ""): row
        for row in governed_rows
        if str(row.get("origin") or "") != "original"
        and str(row.get("feature_name") or "")
    }

    required = {str(value) for value in model_features if str(value)}
    governed_names = {
        str(row.get("feature_name") or "") for row in governed_rows
    }
    undefined_model_features = sorted(required - governed_names)
    if undefined_model_features:
        raise ValueError(
            "The exact training Feature Manifest does not define final-model features: "
            + ", ".join(undefined_model_features)
            + "."
        )
    required_engineered = {name for name in required if name in engineered}
    changed = True
    while changed:
        changed = False
        for name in tuple(required_engineered):
            for source in engineered[name].get("source_features") or []:
                source_name = str(source)
                if source_name in engineered and source_name not in required_engineered:
                    required_engineered.add(source_name)
                    changed = True

    work = frame.copy(deep=True)
    # Canonicalize only unambiguous case-only raw-schema differences.  Two
    # colliding uploaded names fail closed instead of choosing one silently.
    casefolded: dict[str, list[Any]] = {}
    for column in work.columns:
        casefolded.setdefault(str(column).strip().casefold(), []).append(column)

    def require_source(source_name: str, output_name: str) -> None:
        if source_name in work.columns:
            return
        matches = casefolded.get(source_name.strip().casefold(), [])
        if len(matches) == 1:
            work[source_name] = work[matches[0]].copy()
            return
        if len(matches) > 1:
            raise ValueError(
                f"External scoring cannot resolve duplicate case-insensitive source columns for '{source_name}'."
            )
        raise ValueError(
            f"External scoring cannot materialize '{output_name}' because required raw source '{source_name}' is missing."
        )

    applied: list[str] = []
    pending = [
        row
        for row in governed_rows
        if str(row.get("feature_name") or "") in required_engineered
    ]
    while pending:
        pending_names = {str(row.get("feature_name") or "") for row in pending}
        progress = False
        for row in list(pending):
            name = str(row.get("feature_name") or "")
            sources = [str(source) for source in row.get("source_features") or []]
            if any(source in pending_names for source in sources):
                continue
            for source in sources:
                require_source(source, name)
            if (
                str(row.get("origin") or "") == "numeric_bin"
                and str((row.get("config") or {}).get("binning_mode") or "custom")
                == "quantile"
            ):
                parameters = row.get("materialization_parameters") or {}
                if not isinstance(parameters.get("fitted_cut_points"), list) or not parameters.get(
                    "fitted_cut_points"
                ):
                    raise ValueError(
                        f"External scoring cannot materialize quantile bin '{name}' because its frozen training cut points are unavailable."
                    )
            try:
                work[name] = _apply_feature(work, row)
            except Exception as exc:
                raise ValueError(
                    f"External scoring could not deterministically materialize '{name}': {exc}"
                ) from exc
            applied.append(name)
            pending.remove(row)
            progress = True
        if not progress:
            break

    if pending:
        raise ValueError(
            "The exact training Feature Manifest cannot resolve required engineered features: "
            + ", ".join(
                sorted(str(row.get("feature_name") or "") for row in pending)
            )
            + "."
        )

    missing_model_features: list[str] = []
    for feature in model_features:
        feature_name = str(feature)
        if feature_name in work.columns:
            continue
        matches = casefolded.get(feature_name.strip().casefold(), [])
        if len(matches) > 1:
            raise ValueError(
                f"External scoring cannot resolve duplicate case-insensitive model columns for '{feature_name}'."
            )
        if not matches:
            missing_model_features.append(feature_name)
        else:
            work[feature_name] = work[matches[0]].copy()
    if missing_model_features:
        raise ValueError(
            "External scoring is missing final-model features after exact manifest materialization: "
            + ", ".join(missing_model_features)
            + "."
        )

    return {
        # Prediction receives exactly the frozen feature list in its recorded
        # order. Unknown upload columns and the target never reach the model.
        "frame": work.loc[:, [str(feature) for feature in model_features]].copy(),
        "feature_manifest_hash": manifest_hash,
        "applied_engineered_features": applied,
        "model_feature_count": len(model_features),
        "holdout_accessed": False,
        "state_mutated": False,
    }


def preview_features(
    features: list[FeatureDefinitionInput],
    limit: int,
    expected_manifest_version: str = "",
    *,
    project_id: str = "",
    expected_dataset_id: str = "",
    expected_dataset_version_id: str = "",
    legacy_dataset_version: str = "",
) -> dict[str, Any]:
    scoped_store = DATASTORE.current()
    identity = _active_identity(
        project_id,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version_id=expected_dataset_version_id,
        legacy_dataset_version=legacy_dataset_version,
        require_expected=True,
    )
    with scoped_store.state_lock:
        input_revision = int(scoped_store.data_revision)
    df = DATASTORE.get_base_df()
    if df is None or df.empty:
        raise ValueError("No full backend dataset is loaded.")
    manifest = deepcopy(
        get_manifest(
            identity["project_id"],
            expected_dataset_id=identity["dataset_id"],
            expected_dataset_version_id=identity["dataset_version_id"],
        )
    )
    if (
        expected_manifest_version
        and expected_manifest_version != manifest["manifest_hash"]
    ):
        raise ValueError(
            "The feature plan changed. Save and refresh the manifest before previewing."
        )
    prior_materialized = set(
        DATASTORE.meta.get("materialized_feature_names") or []
    )
    baseline = df.drop(
        columns=[name for name in prior_materialized if name in df.columns],
        errors="ignore",
    )
    frame = baseline.head(limit).copy()
    if expected_manifest_version:
        definitions = [
            FeatureDefinitionInput(**row)
            for row in manifest["features"]
            if row.get("origin") != "original"
            and row.get("selected")
            and row.get("eligibility_status") == "eligible"
        ]
    else:
        definitions = [item for item in features if item.selected]
    outputs: list[str] = []
    for item in definitions:
        if item.origin == "original":
            continue
        normalized = _normalize_engineered(
            item,
            set(frame.columns),
            set(outputs),
            identity,
        )
        frame[normalized["feature_name"]] = _apply_feature(frame, normalized)
        outputs.append(normalized["feature_name"])
    columns = [
        *dict.fromkeys(
            source
            for item in definitions
            for source in item.source_features
            if source in frame.columns
        ),
        *outputs,
    ]
    rows = frame[columns].replace({np.nan: None}).to_dict(orient="records") if columns else []
    preview_hash = ""
    if expected_manifest_version:
        preview_hash = f"pv-{hashlib.sha256(f'{expected_manifest_version}:{limit}:{len(df)}'.encode('utf-8')).hexdigest()[:16]}"
        history = list(manifest.get("execution_history") or [])
        history.append(
            _execution_event(
                "preview_features",
                "completed",
                manifest["manifest_hash"],
                f"Previewed {len(outputs)} engineered features across {len(frame)} rows.",
                preview_hash=preview_hash,
            )
        )
        manifest["preview_hash"] = preview_hash
        manifest["execution_history"] = history[-40:]
        manifest["updated_at"] = _now()
        with scoped_store.state_lock:
            _revalidate_identity(identity)
            _assert_data_revision(
                scoped_store,
                input_revision,
                "the feature preview was being calculated",
            )
            scoped_store.meta["feature_preview"] = {
                **_identity_fields(identity),
                "preview_hash": preview_hash,
                "manifest_hash": manifest["manifest_hash"],
                "previewed_at": _now(),
                "preview_row_count": int(len(frame)),
            }
            scoped_store.meta["feature_manifest"] = manifest
            _persist_manifest(identity, manifest)
        schedule_checkpoint_save()
    return {
        "ok": True,
        **_identity_fields(identity),
        "scope": "rendered_sample",
        "manifest_hash": manifest["manifest_hash"] if expected_manifest_version else "",
        "preview_hash": preview_hash,
        "registered_row_count": int(len(df)),
        "preview_row_count": int(len(frame)),
        "columns": columns,
        "created_features": outputs,
        "rows": rows,
    }


def materialize_manifest(
    expected_version: str = "",
    expected_preview_hash: str = "",
    *,
    project_id: str = "",
    expected_dataset_id: str = "",
    expected_dataset_version_id: str = "",
    legacy_dataset_version: str = "",
) -> dict[str, Any]:
    started = time.perf_counter()
    scoped_store = DATASTORE.current()
    identity = _active_identity(
        project_id,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version_id=expected_dataset_version_id,
        legacy_dataset_version=legacy_dataset_version,
        require_expected=True,
    )
    with scoped_store.state_lock:
        input_revision = int(scoped_store.data_revision)
    manifest = deepcopy(
        get_manifest(
            identity["project_id"],
            expected_dataset_id=identity["dataset_id"],
            expected_dataset_version_id=identity["dataset_version_id"],
        )
    )
    if expected_version and expected_version != manifest["manifest_hash"]:
        raise ValueError("The feature plan changed. Refresh the manifest before materializing features.")
    df = DATASTORE.get_base_df()
    if df is None or df.empty:
        raise ValueError("No full backend dataset is loaded.")
    engineered_rows = [
        row
        for row in manifest["features"]
        if row.get("origin") != "original"
        and row.get("selected")
        and row.get("eligibility_status") == "eligible"
    ]
    preview_record = DATASTORE.meta.get("feature_preview") or {}
    if preview_record:
        _assert_record_identity(preview_record, identity, "feature preview")
    if engineered_rows and (
        not expected_preview_hash
        or expected_preview_hash != preview_record.get("preview_hash")
        or preview_record.get("manifest_hash") != manifest["manifest_hash"]
    ):
        raise ValueError(
            "Preview the saved feature contract before materializing the full dataset."
        )
    prior_materialized = set(DATASTORE.meta.get("materialized_feature_names") or [])
    expected_materialized_names = [
        row["feature_name"] for row in engineered_rows
    ]
    if (
        manifest.get("materialization_status") == "current"
        and manifest.get("materialized_manifest_hash") == manifest["manifest_hash"]
        and manifest.get("materialization_hash")
        and prior_materialized == set(expected_materialized_names)
        and scoped_store.processed_df is not None
        and set(expected_materialized_names).issubset(
            set(str(column) for column in scoped_store.processed_df.columns)
        )
    ):
        selected = [
            feature["feature_name"]
            for feature in manifest["features"]
            if feature.get("selected")
            and feature.get("eligibility_status") == "eligible"
        ]
        return {
            "ok": True,
            **_identity_fields(identity),
            "manifest_version": manifest["manifest_version"],
            "manifest_hash": manifest["manifest_hash"],
            "materialization_hash": manifest["materialization_hash"],
            "materialized_manifest_hash": manifest["manifest_hash"],
            "materialization_status": "current",
            "row_count": int(len(scoped_store.processed_df)),
            "original_feature_count": sum(
                1
                for row in manifest["features"]
                if row.get("origin") == "original"
            ),
            "engineered_feature_count": len(expected_materialized_names),
            "materialized_features": expected_materialized_names,
            "selected_features": selected,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "idempotent_replay": True,
        }
    frame = df.drop(columns=[column for column in prior_materialized if column in df.columns], errors="ignore").copy()
    materialized: list[str] = []
    failures: list[dict[str, str]] = []
    authorized_sources = set(_base_columns())
    created_names: set[str] = set()
    for feature in manifest["features"]:
        if feature.get("origin") == "original":
            continue
        if not feature.get("selected") or feature.get("eligibility_status") != "eligible":
            feature["creation_status"] = "planned"
            feature["materialization_status"] = "not_materialized"
            feature["profile_scope"] = "not_profiled"
            feature["summary_statistics"] = {}
            continue
        try:
            _normalize_engineered(
                FeatureDefinitionInput(**feature),
                authorized_sources,
                created_names,
                identity,
            )
            if (
                str(feature.get("origin") or "") == "numeric_bin"
                and str((feature.get("config") or {}).get("binning_mode") or "custom")
                == "quantile"
            ):
                source_names = [
                    str(value) for value in feature.get("source_features") or []
                ]
                if len(source_names) != 1 or source_names[0] not in frame.columns:
                    raise ValueError(
                        "Quantile-bin materialization requires one available source variable."
                    )
                numeric_source = pd.to_numeric(
                    frame[source_names[0]], errors="coerce"
                )
                ordinary_source = numeric_source.mask(
                    bureau_special_mask(numeric_source)
                )
                quantiles = [
                    float(value)
                    for value in (feature.get("config") or {}).get(
                        "quantiles", [0.2, 0.4, 0.6, 0.8]
                    )
                    if 0 < float(value) < 1
                ]
                fitted_cut_points = sorted(
                    {
                        float(ordinary_source.quantile(value))
                        for value in quantiles
                        if pd.notna(ordinary_source.quantile(value))
                    }
                )
                if not fitted_cut_points:
                    raise ValueError(
                        "Quantile-bin materialization produced no stable training cut points."
                    )
                feature["materialization_parameters"] = {
                    "fitted_cut_points": fitted_cut_points,
                    "fit_scope": "full_governed_population_target_independent",
                    "fit_row_count": int(len(frame)),
                    "source_feature": source_names[0],
                }
            frame[feature["feature_name"]] = _apply_feature(frame, feature)
            created_names.add(feature["feature_name"])
            feature["creation_status"] = "created"
            feature["materialization_status"] = "materialized"
            feature["profile_scope"] = "full_dataset"
            values = frame[feature["feature_name"]]
            feature["summary_statistics"] = _feature_summary_statistics(values)
            materialized.append(feature["feature_name"])
        except Exception as exc:
            feature["creation_status"] = "failed"
            feature["materialization_status"] = "failed"
            failures.append({"feature": feature["feature_name"], "error": str(exc)})
    if failures:
        raise ValueError("Feature materialization failed: " + "; ".join(f"{row['feature']}: {row['error']}" for row in failures))
    selected = [feature["feature_name"] for feature in manifest["features"] if feature.get("selected") and feature.get("eligibility_status") == "eligible"]
    materialization_hash = _materialization_hash(
        manifest["manifest_hash"],
        identity,
        len(frame),
        materialized,
    )
    history = list(manifest.get("execution_history") or [])
    history.append(
        _execution_event(
            "materialize_full_dataset",
            "completed",
            manifest["manifest_hash"],
            f"Materialized {len(materialized)} engineered features across {len(frame)} rows.",
            materialization_hash=materialization_hash,
        )
    )
    manifest["updated_at"] = _now()
    manifest["features"] = manifest["features"]
    next_split_status = (
        "stale"
        if str(manifest.get("split_status") or DATASTORE.meta.get("split_status"))
        == "stale"
        else "not_created"
    )
    manifest["split_status"] = next_split_status
    manifest["materialization_status"] = "current"
    manifest["materialization_hash"] = materialization_hash
    manifest["materialized_manifest_hash"] = manifest["manifest_hash"]
    manifest["materialized_at"] = _now()
    manifest["confirmation_status"] = "required"
    manifest["confirmed_manifest_hash"] = ""
    manifest["confirmed_at"] = None
    manifest["execution_history"] = history[-40:]
    with scoped_store.state_lock:
        _revalidate_identity(identity)
        _assert_data_revision(
            scoped_store,
            input_revision,
            "the feature dataset was being materialized",
        )
        scoped_store.set_processed(frame)
        scoped_store.meta["processed_stage"] = "feature_engineering"
        scoped_store.meta["materialized_feature_names"] = materialized
        scoped_store.meta["selected_columns"] = selected
        invalidate_downstream_training_state(
            "The governed feature dataset was materialized.",
            store=scoped_store,
            split_status=next_split_status,
        )
        # Store the materialized contract last, after invalidation marked the
        # prior manifest stale.
        scoped_store.meta["feature_manifest"] = manifest
        _persist_manifest(identity, manifest)
    schedule_checkpoint_save()
    return {
        "ok": True,
        **_identity_fields(identity),
        "manifest_version": manifest["manifest_version"],
        "manifest_hash": manifest["manifest_hash"],
        "materialization_hash": materialization_hash,
        "materialized_manifest_hash": manifest["manifest_hash"],
        "materialization_status": "current",
        "row_count": int(len(frame)),
        "original_feature_count": sum(1 for row in manifest["features"] if row.get("origin") == "original"),
        "engineered_feature_count": len(materialized),
        "materialized_features": materialized,
        "selected_features": selected,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "idempotent_replay": False,
    }


def confirm_manifest(
    expected_version: str = "",
    expected_materialization_hash: str = "",
    *,
    project_id: str = "",
    expected_dataset_id: str = "",
    expected_dataset_version_id: str = "",
    legacy_dataset_version: str = "",
) -> dict[str, Any]:
    scoped_store = DATASTORE.current()
    identity = _active_identity(
        project_id,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version_id=expected_dataset_version_id,
        legacy_dataset_version=legacy_dataset_version,
        require_expected=True,
    )
    with scoped_store.state_lock:
        input_revision = int(scoped_store.data_revision)
    manifest = get_manifest(
        identity["project_id"],
        expected_dataset_id=identity["dataset_id"],
        expected_dataset_version_id=identity["dataset_version_id"],
    )
    if expected_version and expected_version != manifest["manifest_hash"]:
        raise ValueError(
            "The feature contract changed. Refresh before confirming the feature set."
        )
    if manifest.get("validation_status") != "passed":
        raise ValueError("Validate and save the feature contract before confirmation.")
    if (
        manifest.get("materialization_status") != "current"
        or manifest.get("materialized_manifest_hash") != manifest["manifest_hash"]
    ):
        raise ValueError(
            "Materialize the current feature contract before confirming the feature set."
        )
    if (
        expected_materialization_hash
        and expected_materialization_hash != manifest.get("materialization_hash")
    ):
        raise ValueError(
            "The materialized dataset changed. Refresh before confirming the feature set."
        )
    history = list(manifest.get("execution_history") or [])
    history.append(
        _execution_event(
            "confirm_feature_set",
            "completed",
            manifest["manifest_hash"],
            "Confirmed that the materialized dataset exactly matches the governed feature contract.",
            materialization_hash=manifest.get("materialization_hash"),
        )
    )
    manifest["confirmation_status"] = "confirmed"
    manifest["confirmed_manifest_hash"] = manifest["manifest_hash"]
    manifest["confirmed_at"] = _now()
    manifest["updated_at"] = _now()
    manifest["execution_history"] = history[-40:]
    with scoped_store.state_lock:
        _revalidate_identity(identity)
        _assert_data_revision(
            scoped_store,
            input_revision,
            "the feature contract was being confirmed",
        )
        scoped_store.meta["feature_manifest"] = manifest
        _persist_manifest(identity, manifest)
    schedule_checkpoint_save()
    return manifest


def delete_feature(
    feature_id: str,
    project_id: str = "",
    *,
    expected_dataset_id: str = "",
    expected_dataset_version_id: str = "",
    legacy_dataset_version: str = "",
) -> dict[str, Any]:
    identity = _active_identity(
        project_id,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version_id=expected_dataset_version_id,
        legacy_dataset_version=legacy_dataset_version,
        require_expected=True,
    )
    manifest = get_manifest(
        identity["project_id"],
        expected_dataset_id=identity["dataset_id"],
        expected_dataset_version_id=identity["dataset_version_id"],
    )
    target = next((row for row in manifest["features"] if row.get("feature_id") == feature_id), None)
    if not target:
        raise ValueError("Feature was not found in the current manifest.")
    if target.get("origin") == "original":
        raise ValueError("Source features cannot be deleted. Deselect them in the governed predictor review instead.")
    remaining = [row for row in manifest["features"] if row.get("feature_id") != feature_id and row.get("origin") != "original"]
    request = FeatureManifestUpdateRequest(
        project_id=identity["project_id"],
        features=[FeatureDefinitionInput(**row) for row in remaining],
        pipeline_steps=manifest.get("pipeline_steps", []),
        dataset_id=identity["dataset_id"],
        dataset_version_id=identity["dataset_version_id"],
        dataset_version=identity["dataset_version_id"],
    )
    return update_manifest(request)

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any

import pandas as pd

from ..core.dataset_store import DATASTORE
from ..core.modeling_scope import active_project_id
from ..core.population_contract import (
    build_population_contract,
    calculate_duplicate_contract,
    partition_population_counts,
)
from ..datasets.dataset_identity import assert_expected_active_identity
from ..eda.analytical_contract import classify_feature_values
from .development_scope import resolve_development_analysis_scope


_DATE_NAME = re.compile(r"(^|_)(date|datetime|timestamp|time|dt)($|_)", re.IGNORECASE)
_DATE_TEXT = re.compile(
    r"^(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})(?:[ T].*)?$"
)
_LEAKAGE_NAME = re.compile(
    r"target|outcome|future|post[_ ]|label|response|charge.?off|default.?date|fraud.?confirmed",
    re.IGNORECASE,
)


def _json_value(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _dataset_hash(df: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update("|".join(map(str, df.columns)).encode("utf-8"))
    digest.update(str(df.shape).encode("utf-8"))
    if not df.empty:
        hashed = pd.util.hash_pandas_object(df, index=True).values
        digest.update(hashed.tobytes())
    return digest.hexdigest()


def _legitimate_date_range(name: str, series: pd.Series) -> dict[str, str] | None:
    values = series.dropna()
    if values.empty:
        return None
    if pd.api.types.is_datetime64_any_dtype(values):
        parsed = pd.to_datetime(values, errors="coerce")
    else:
        # Numeric values are never passed through date parsing. Text fields
        # require both a date-like name and a high supported-format match rate.
        if pd.api.types.is_numeric_dtype(values) or not _DATE_NAME.search(str(name)):
            return None
        text = values.astype(str).str.strip()
        matches = text.str.match(_DATE_TEXT)
        if float(matches.mean()) < 0.8:
            return None
        parsed = pd.to_datetime(text.where(matches), errors="coerce", utc=True)
    parsed = parsed.dropna()
    if parsed.empty:
        return None
    return {
        "column": str(name),
        "min": parsed.min().date().isoformat(),
        "max": parsed.max().date().isoformat(),
    }


def governed_time_field(name: str, series: pd.Series) -> dict[str, str] | None:
    """Public name for the governed date-field rule used across ATLAS.

    A field only qualifies as a time field when it genuinely IS one: a real
    datetime dtype, or text that both carries a date-like name and parses at a
    high rate. Numeric columns are never inferred as dates -- that rule is what
    stops a "Time" column holding elapsed seconds from being charted as a
    calendar axis. Exposed so the EDA Target workspace enforces exactly the same
    rule as the data-quality profile rather than inventing a second one.
    """
    return _legitimate_date_range(name, series)


def profile_active_dataset(
    target: str | None = None,
    event_value: Any = None,
    *,
    project_id: str = "",
    expected_dataset_id: str = "",
    expected_dataset_version_id: str = "",
    legacy_dataset_version: str = "",
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_project_id = str(
        project_id
        or active_project_id()
        or DATASTORE.meta.get("project_id")
        or ""
    ).strip()
    identity = assert_expected_active_identity(
        resolved_project_id,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version_id=expected_dataset_version_id,
        legacy_dataset_version=legacy_dataset_version,
        user=user,
    )
    df = DATASTORE.raw_df
    if df is None or df.empty:
        raise ValueError("No full backend dataset is loaded.")

    target = target if target in df.columns else DATASTORE.target if DATASTORE.target in df.columns else None
    row_count = int(df.shape[0])
    registered_predictor_frame = df.drop(columns=[target], errors="ignore")
    profile_columns = [str(column) for column in registered_predictor_frame.columns]
    column_count = int(len(profile_columns))
    partition = (
        DATASTORE.meta.get("analysis_partition")
        if isinstance(DATASTORE.meta.get("analysis_partition"), dict)
        else None
    )
    development_rows, holdout_rows = partition_population_counts(
        row_count,
        partition,
    )
    development_scope = None
    if development_rows is not None and target:
        try:
            development_scope = resolve_development_analysis_scope(
                DATASTORE.current(),
                {
                    **identity,
                    "dataset_content_hash": str(
                        DATASTORE.meta.get("dataset_content_hash") or ""
                    ),
                },
                requested_target=target,
                requested_event_value=event_value,
                require_documentation_ready=False,
                actor=str((user or {}).get("userId") or "quality-profile"),
            )
        except Exception:
            # Never fall back to the registered target after the holdout is
            # sealed. Target health remains explicitly unavailable instead.
            development_scope = None
    missingness: list[dict[str, Any]] = []
    constant_columns: list[str] = []
    near_zero_variance: list[str] = []
    high_cardinality: list[str] = []
    unexpected_types: list[str] = []
    outlier_prevalence: list[dict[str, Any]] = []
    date_ranges: list[dict[str, str]] = []

    for column in profile_columns:
        series = registered_predictor_frame[column]
        nonmissing = series.dropna()
        missingness.append({
            "column": str(column),
            "count": int(series.isna().sum()),
            "percent": float(series.isna().mean()) if row_count else 0.0,
        })
        distinct = int(nonmissing.nunique(dropna=True))
        if len(nonmissing) and distinct <= 1:
            constant_columns.append(str(column))
        if len(nonmissing) and distinct <= 5:
            top_share = float(nonmissing.value_counts(normalize=True, dropna=True).iloc[0])
            if top_share >= 0.99:
                near_zero_variance.append(str(column))
        if not pd.api.types.is_numeric_dtype(series) and len(nonmissing):
            if distinct > min(100, max(20, int(len(nonmissing) * 0.5))):
                high_cardinality.append(str(column))
            numeric_rate = float(pd.to_numeric(nonmissing, errors="coerce").notna().mean())
            if 0.1 < numeric_rate < 0.8:
                unexpected_types.append(str(column))
        date_range = _legitimate_date_range(str(column), series)
        if date_range:
            date_ranges.append(date_range)

    # Ordinary-value outlier prevalence is a target-independent diagnostic,
    # but after partition sealing it is still computed on Development so final
    # holdout predictors cannot influence IQR thresholds. The shared EDA value
    # classifier removes true nulls, governed bureau special codes, parse
    # failures, and non-finite values before the ordinary-value denominator.
    diagnostic_frame = (
        development_scope.development_features
        if development_scope is not None
        else registered_predictor_frame
    )
    outlier_scope = (
        "development_population"
        if development_scope is not None
        else "registered_population_pre_partition"
    )
    authorization = (
        development_scope.predictor_authorization
        if development_scope is not None
        else DATASTORE.meta.get("predictor_authorization")
    )
    authorized_predictors = {
        str(column)
        for column in (
            authorization.get("authorized_predictors", [])
            if isinstance(authorization, dict)
            else diagnostic_frame.columns
        )
    }
    for column in diagnostic_frame.columns:
        name = str(column)
        if name not in authorized_predictors:
            continue
        classification = classify_feature_values(
            name,
            diagnostic_frame[column],
            meta=DATASTORE.meta,
        )
        if not classification["is_numeric"]:
            continue
        ordinary_count = int(
            classification["masks"]["ordinary_valid_value"].sum()
        )
        outlier_count = int(classification["ordinary_outlier_mask"].sum())
        prevalence = outlier_count / max(ordinary_count, 1)
        if ordinary_count >= 10 and prevalence >= 0.01:
            outlier_prevalence.append(
                {
                    "column": name,
                    "count": outlier_count,
                    "percent": prevalence,
                    "rate": prevalence,
                    "denominator_rows": ordinary_count,
                    "unit": "ordinary_valid_predictor_rows",
                    "scope": outlier_scope,
                    "bureau_special_values_excluded": True,
                    "true_nulls_excluded": True,
                    "selection_authority": False,
                }
            )

    duplicate_contract = calculate_duplicate_contract(
        registered_predictor_frame,
        scope="registered_structural_population",
        target_column=None,
        target_included=False,
        writable_authority=False,
        purpose="registered_data_quality_structural_description",
    )
    duplicate_rows = int(duplicate_contract["redundant_duplicate_rows"])
    duplicate_ids: list[str] = []
    for column in profile_columns:
        if re.search(r"(^|_)(id|key|account|customer|number)($|_)", str(column), re.IGNORECASE):
            values = registered_predictor_frame[column].dropna()
            if len(values) and values.duplicated().any():
                duplicate_ids.append(str(column))

    potential_leakage = [
        str(column)
        for column in profile_columns
        if str(column) != target and _LEAKAGE_NAME.search(str(column))
    ]

    target_health: dict[str, Any] = {"target": target, "status": "not_evaluated"}
    if target and development_scope is not None:
        target_source = development_scope.development_target
        target_values = target_source.dropna()
        counts = target_values.value_counts(dropna=False)
        target_health = {
            "target": target,
            "status": "evaluated",
            "scope": "development_population",
            "nonmissingCount": int(len(target_values)),
            "missingCount": int(target_source.isna().sum()),
            "distinctCount": int(target_values.nunique()),
        }
        if 1 < len(counts) <= 20:
            governed_event = event_value
            if governed_event is None and any(str(value) == "1" for value in counts.index):
                governed_event = next(value for value in counts.index if str(value) == "1")
            target_health.update({
                "kind": "classification",
                "classDistribution": [
                    {"value": _json_value(index), "count": int(count), "percent": float(count / max(len(target_values), 1))}
                    for index, count in counts.items()
                ],
                "eventValue": _json_value(governed_event),
                "eventRate": float((target_values.astype(str) == str(governed_event)).mean()) if governed_event is not None else None,
            })
        else:
            numeric_target = pd.to_numeric(target_values, errors="coerce").dropna()
            target_health.update({
                "kind": "regression",
                "mean": float(numeric_target.mean()) if len(numeric_target) else None,
                "standardDeviation": float(numeric_target.std()) if len(numeric_target) > 1 else None,
                "minimum": float(numeric_target.min()) if len(numeric_target) else None,
                "maximum": float(numeric_target.max()) if len(numeric_target) else None,
            })
    elif target and development_rows is not None:
        target_health = {
            "target": target,
            "status": "unavailable_sealed_development_scope",
            "scope": "development_population",
        }
    elif target:
        # Before a partition is sealed, Data Acquisition may inspect the
        # registered target solely to establish partition/target readiness.
        target_source = df[target]
        target_values = target_source.dropna()
        counts = target_values.value_counts(dropna=False)
        target_health = {
            "target": target,
            "status": "evaluated",
            "scope": "registered_population_pre_partition",
            "nonmissingCount": int(len(target_values)),
            "missingCount": int(target_source.isna().sum()),
            "distinctCount": int(target_values.nunique()),
        }
        if 1 < len(counts) <= 20:
            governed_event = event_value
            if governed_event is None and any(str(value) == "1" for value in counts.index):
                governed_event = next(value for value in counts.index if str(value) == "1")
            target_health.update({
                "kind": "classification",
                "classDistribution": [
                    {"value": _json_value(index), "count": int(count), "percent": float(count / max(len(target_values), 1))}
                    for index, count in counts.items()
                ],
                "eventValue": _json_value(governed_event),
                "eventRate": float((target_values.astype(str) == str(governed_event)).mean()) if governed_event is not None else None,
            })
        else:
            numeric_target = pd.to_numeric(target_values, errors="coerce").dropna()
            target_health.update({
                "kind": "regression",
                "mean": float(numeric_target.mean()) if len(numeric_target) else None,
                "standardDeviation": float(numeric_target.std()) if len(numeric_target) > 1 else None,
                "minimum": float(numeric_target.min()) if len(numeric_target) else None,
                "maximum": float(numeric_target.max()) if len(numeric_target) else None,
            })
    warnings: list[str] = []
    if potential_leakage:
        warnings.append(f"Review {len(potential_leakage)} potential leakage candidate(s) before modeling.")
    if duplicate_rows:
        warnings.append(
            f"The registered predictor frame contains {duplicate_rows:,} redundant duplicate row(s)."
        )
    columns_with_missing = sum(1 for row in missingness if row["count"])
    if columns_with_missing:
        warnings.append(f"{columns_with_missing} column(s) contain missing values.")
    readiness = "needs_review" if warnings else "ready"
    identity = assert_expected_active_identity(
        resolved_project_id,
        expected_dataset_id=identity["dataset_id"],
        expected_dataset_version_id=identity["dataset_version_id"],
        user=user,
    )
    population_contract = build_population_contract(
        registered_rows=row_count,
        development_rows=development_rows,
        holdout_rows=holdout_rows,
        primary_scope="registered_structural_population",
        primary_purpose="registered_data_quality_profile",
        project_id=identity["project_id"],
        dataset_id=identity["dataset_id"],
        dataset_version_id=identity["dataset_version_id"],
        target=target,
        target_contract_id=DATASTORE.meta.get("target_contract_id"),
        predictor_authorization_id=DATASTORE.meta.get(
            "predictor_authorization_id"
        ),
        analysis_partition_id=DATASTORE.meta.get("analysis_partition_id"),
        analysis_partition_revision=(
            (DATASTORE.meta.get("analysis_partition") or {}).get("revision")
            if isinstance(DATASTORE.meta.get("analysis_partition"), dict)
            else None
        ),
        analysis_population_id=(
            (DATASTORE.meta.get("analysis_partition") or {}).get(
                "analysis_population_id"
            )
            if isinstance(DATASTORE.meta.get("analysis_partition"), dict)
            else None
        ),
        population_policy_id="registered_data_quality_profile",
        treatment_policy_id="non_mutating_profile",
        special_value_policy_id=DATASTORE.meta.get("special_value_policy_id"),
        analysis_rows=(
            len(development_scope.development_target)
            if development_scope is not None
            else row_count if development_rows is None else None
        ),
        fit_rows=None,
        application_rows=None,
        materialization_rows=None,
        registered_duplicate_contract=duplicate_contract,
        development_duplicate_contract=None,
        descriptive_scope="registered_structural_population",
        analysis_scope="registered_data_quality_profile",
        target_scope=(
            "development_population"
            if development_scope is not None
            else "registered_population_pre_partition"
            if target and development_rows is None
            else "unavailable_sealed_development_scope"
            if target
            else "not_applicable"
        ),
        fit_scope="not_applicable",
        application_scope="not_applicable_non_mutating_profile",
        materialization_scope="not_applicable_non_mutating_profile",
        render_scope="registered_aggregate_render",
        registered_structural_predictors_accessed=True,
        final_holdout_predictors_included_in_structural_profile=(
            holdout_rows is not None
        ),
        final_holdout_target_accessed=False,
        final_holdout_parameter_influence=False,
        final_holdout_used_for_selection=False,
        final_holdout_transformed_or_materialized_prelock=False,
        final_holdout_opened_for_final_reporting=False,
    )
    return {
        "ok": True,
        "project_id": identity["project_id"],
        "dataset_id": identity["dataset_id"],
        "dataset_version_id": identity["dataset_version_id"],
        "dataset_version": identity["dataset_version_id"],
        "datasetId": identity["dataset_id"],
        "datasetVersionId": identity["dataset_version_id"],
        # Transitional display compatibility; always the canonical ID.
        "datasetVersion": identity["dataset_version_id"],
        "profileScope": "registered_structural_population",
        "profiledRowCount": row_count,
        "registeredRowCount": row_count,
        "columnCount": column_count,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "datasetHash": _dataset_hash(registered_predictor_frame),
        "duplicateRows": duplicate_rows,
        "duplicateContract": duplicate_contract,
        "populationContract": population_contract,
        "populationCounts": population_contract["counts"],
        "duplicateIdCandidates": duplicate_ids,
        "missingness": sorted(missingness, key=lambda item: item["percent"], reverse=True),
        "constantColumns": constant_columns,
        "nearZeroVarianceColumns": near_zero_variance,
        "highCardinalityCategoricalColumns": high_cardinality,
        "unexpectedDatatypeColumns": unexpected_types,
        "potentialLeakageCandidates": potential_leakage,
        "outlierPrevalence": sorted(outlier_prevalence, key=lambda item: item["percent"], reverse=True),
        "outlierPrevalenceScope": outlier_scope,
        "classDistribution": target_health.get("classDistribution"),
        "continuousTargetSummary": target_health if target_health.get("kind") == "regression" else None,
        "targetHealth": target_health,
        "targetProfileScope": target_health.get("scope", "not_evaluated"),
        "dateRanges": date_ranges,
        "memoryEstimateMb": float(registered_predictor_frame.memory_usage(index=True, deep=True).sum() / 1024 / 1024),
        "registeredSchemaColumnCount": int(df.shape[1]),
        "warnings": warnings,
        "readinessStatus": readiness,
    }

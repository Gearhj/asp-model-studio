"""Shared governed population, holdout, and duplicate-count contract.

The modeling workflow has several legitimate populations: the immutable
registered dataset, the sealed development population, and the sealed final
holdout.  A scope label and a generic row count must never be assembled by
different callers because that permits a Development label to be paired with
the registered-population count.  This module produces one canonical,
hash-bound projection that keeps those values together and records why any
holdout predictors were inspected.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Mapping, Optional, Sequence

import pandas as pd


POPULATION_CONTRACT_VERSION = "atlas.governed-population/v1"
DUPLICATE_AUTHORITY_VERSION = "atlas.eda-duplicate-authority/v1"

PopulationScope = Literal[
    "registered_structural_population",
    "development_population",
    "rendered_sample",
]


def _nonnegative(value: Any, *, field: str) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer.") from exc
    if resolved < 0:
        raise ValueError(f"{field} cannot be negative.")
    return resolved


def _optional_nonnegative(value: Any, *, field: str) -> Optional[int]:
    if value is None or value == "":
        return None
    return _nonnegative(value, field=field)


def _stable_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def partition_population_counts(
    registered_rows: int,
    partition: Optional[Mapping[str, Any]],
) -> tuple[Optional[int], Optional[int]]:
    """Return reconciled development/holdout counts from a safe partition.

    An absent or non-current partition is represented explicitly as unknown
    rather than guessed from a split ratio.
    """

    registered = _nonnegative(registered_rows, field="registered_rows")
    if not isinstance(partition, Mapping):
        return None, None
    status = str(partition.get("status") or "").strip().lower()
    if status and status not in {"current", "confirmed", "sealed", "active"}:
        return None, None
    development = _optional_nonnegative(
        partition.get("development_count"), field="development_rows"
    )
    holdout = _optional_nonnegative(
        partition.get("holdout_count"), field="holdout_rows"
    )
    if development is None or holdout is None:
        return None, None
    if development + holdout != registered:
        raise ValueError(
            "Development and holdout counts do not reconcile to the registered population."
        )
    return development, holdout


def build_duplicate_contract_from_counts(
    *,
    scope: str,
    row_count: int,
    comparison_columns: Sequence[str],
    duplicate_group_count: int,
    duplicate_participant_rows: int,
    redundant_duplicate_rows: int,
    unique_rows_after_deduplication: int,
    target_column: Optional[str],
    target_included: bool,
    duplicate_participant_valid_target_rows: Optional[int],
    duplicate_participant_missing_target_rows: Optional[int],
    redundant_duplicate_valid_target_rows: Optional[int],
    redundant_duplicate_missing_target_rows: Optional[int],
    writable_authority: bool,
    purpose: str,
    keep_semantics: Literal["first", "last", "none"] = "first",
) -> dict[str, Any]:
    """Build the canonical duplicate projection from precomputed aggregates."""

    rows = _nonnegative(row_count, field="duplicate.row_count")
    groups = _nonnegative(
        duplicate_group_count, field="duplicate.duplicate_group_count"
    )
    participants = _nonnegative(
        duplicate_participant_rows, field="duplicate.duplicate_participant_rows"
    )
    redundant = _nonnegative(
        redundant_duplicate_rows, field="duplicate.redundant_duplicate_rows"
    )
    unique = _nonnegative(
        unique_rows_after_deduplication,
        field="duplicate.unique_rows_after_deduplication",
    )
    participant_valid_target = _optional_nonnegative(
        duplicate_participant_valid_target_rows,
        field="duplicate.duplicate_participant_valid_target_rows",
    )
    participant_missing_target = _optional_nonnegative(
        duplicate_participant_missing_target_rows,
        field="duplicate.duplicate_participant_missing_target_rows",
    )
    redundant_valid_target = _optional_nonnegative(
        redundant_duplicate_valid_target_rows,
        field="duplicate.redundant_duplicate_valid_target_rows",
    )
    redundant_missing_target = _optional_nonnegative(
        redundant_duplicate_missing_target_rows,
        field="duplicate.redundant_duplicate_missing_target_rows",
    )
    if participants > rows or redundant > participants or unique > rows:
        raise ValueError("Duplicate aggregates cannot exceed their comparison population.")
    if unique != rows - redundant:
        raise ValueError(
            "unique_rows_after_deduplication must equal row_count minus redundant_duplicate_rows."
        )
    if target_included:
        if None in {
            participant_valid_target,
            participant_missing_target,
            redundant_valid_target,
            redundant_missing_target,
        }:
            raise ValueError(
                "A target-inclusive duplicate contract requires participant and redundant duplicate target counts."
            )
        if int(participant_valid_target or 0) + int(
            participant_missing_target or 0
        ) != participants:
            raise ValueError(
                "Duplicate-participant valid and missing target counts must reconcile."
            )
        if int(redundant_valid_target or 0) + int(
            redundant_missing_target or 0
        ) != redundant:
            raise ValueError(
                "Redundant-duplicate valid and missing target counts must reconcile."
            )
    else:
        participant_valid_target = None
        participant_missing_target = None
        redundant_valid_target = None
        redundant_missing_target = None
    return {
        "scope": str(scope),
        "row_count": rows,
        "comparison_scope": "all_rows_exact_value_equality",
        "comparison_columns": [str(value) for value in comparison_columns],
        "comparison_column_count": len(comparison_columns),
        "duplicate_group_count": groups,
        "duplicate_participant_rows": participants,
        # Compatibility name is explicit about pandas ``duplicated(keep='first')``.
        "duplicate_rows": redundant,
        "redundant_duplicate_rows": redundant,
        "unique_rows_after_deduplication": unique,
        "target_column": str(target_column or "") or None,
        "target_included": bool(target_included),
        "duplicate_participant_valid_target_rows": participant_valid_target,
        "duplicate_participant_missing_target_rows": participant_missing_target,
        "redundant_duplicate_valid_target_rows": redundant_valid_target,
        "redundant_duplicate_missing_target_rows": redundant_missing_target,
        # Compatibility aliases explicitly use redundant-duplicate row units.
        "valid_target_rows": redundant_valid_target,
        "missing_target_rows": redundant_missing_target,
        "target_count_unit": "redundant_duplicate_rows",
        "keep_semantics": keep_semantics,
        "writable_authority": bool(writable_authority),
        "purpose": str(purpose),
    }


def calculate_duplicate_contract(
    frame: pd.DataFrame,
    *,
    scope: str,
    comparison_columns: Optional[Sequence[str]] = None,
    target_column: Optional[str] = None,
    target_included: bool,
    writable_authority: bool,
    purpose: str,
    keep_semantics: Literal["first", "last", "none"] = "first",
) -> dict[str, Any]:
    """Vectorized, shared exact-duplicate calculator.

    ``redundant_duplicate_rows`` matches ``DataFrame.duplicated(keep='first')``.
    ``duplicate_participant_rows`` includes the first member of every repeated
    group, and ``duplicate_group_count`` counts those repeated groups.
    """

    columns = (
        [str(value) for value in comparison_columns]
        if comparison_columns is not None
        else [str(value) for value in frame.columns]
    )
    missing_columns = [column for column in columns if column not in frame.columns]
    if missing_columns:
        raise ValueError(
            "Duplicate comparison columns are missing: " + ", ".join(missing_columns)
        )
    if target_included and (
        not target_column or str(target_column) not in frame.columns
    ):
        raise ValueError(
            "A target-inclusive duplicate calculation requires the target column."
        )
    row_count = int(len(frame))
    if columns:
        participants_mask = frame.duplicated(subset=columns, keep=False)
        participant_rows = int(participants_mask.sum())
        keep_arg: Any = False if keep_semantics == "none" else keep_semantics
        redundant_mask = frame.duplicated(subset=columns, keep=keep_arg)
        redundant_rows = int(redundant_mask.sum())
        if keep_semantics == "none":
            # ``none`` describes removing every participant, not keeping one.
            unique_after = row_count - participant_rows
        else:
            unique_after = row_count - redundant_rows
        if participant_rows:
            repeated = frame.loc[participants_mask, columns]
            group_count = int(
                repeated.value_counts(subset=columns, dropna=False).shape[0]
            )
        else:
            group_count = 0
    else:
        participant_rows = row_count if row_count > 1 else 0
        group_count = 1 if row_count > 1 else 0
        redundant_rows = max(0, row_count - 1)
        unique_after = min(row_count, 1)
        participants_mask = pd.Series(row_count > 1, index=frame.index)
        redundant_mask = pd.Series(False, index=frame.index)
        if row_count > 1:
            redundant_mask.iloc[1:] = True
    target_series = (
        frame[str(target_column)] if target_included and target_column else None
    )
    return build_duplicate_contract_from_counts(
        scope=scope,
        row_count=row_count,
        comparison_columns=columns,
        duplicate_group_count=group_count,
        duplicate_participant_rows=participant_rows,
        redundant_duplicate_rows=redundant_rows,
        unique_rows_after_deduplication=unique_after,
        target_column=target_column,
        target_included=target_included,
        duplicate_participant_valid_target_rows=(
            int((participants_mask & target_series.notna()).sum())
            if target_series is not None
            else None
        ),
        duplicate_participant_missing_target_rows=(
            int((participants_mask & target_series.isna()).sum())
            if target_series is not None
            else None
        ),
        redundant_duplicate_valid_target_rows=(
            int((redundant_mask & target_series.notna()).sum())
            if target_series is not None
            else None
        ),
        redundant_duplicate_missing_target_rows=(
            int((redundant_mask & target_series.isna()).sum())
            if target_series is not None
            else None
        ),
        writable_authority=writable_authority,
        purpose=purpose,
        keep_semantics=keep_semantics,
    )


def _legacy_duplicate_count_projection(
    *,
    scope: str,
    row_count: int,
    redundant_duplicate_rows: Optional[int],
    target_column: Optional[str],
    target_included: bool,
) -> Optional[dict[str, Any]]:
    """Expose a legacy redundant-row count without inventing group lineage."""

    if redundant_duplicate_rows is None:
        return None
    rows = _nonnegative(row_count, field="duplicate.row_count")
    redundant = _nonnegative(
        redundant_duplicate_rows,
        field="duplicate.redundant_duplicate_rows",
    )
    if redundant > rows:
        raise ValueError("Duplicate rows cannot exceed their comparison population.")
    return {
        "scope": str(scope),
        "row_count": rows,
        "comparison_scope": "unverified_legacy_redundant_count_only",
        "comparison_columns": None,
        "comparison_column_count": None,
        "duplicate_group_count": None,
        "duplicate_participant_rows": None,
        # These two aliases are the only observed legacy fact and retain the
        # exact pandas duplicated(keep='first') unit.
        "duplicate_rows": redundant,
        "redundant_duplicate_rows": redundant,
        "unique_rows_after_deduplication": rows - redundant,
        "target_column": str(target_column or "") or None,
        "target_included": bool(target_included),
        "duplicate_participant_valid_target_rows": None,
        "duplicate_participant_missing_target_rows": None,
        "redundant_duplicate_valid_target_rows": None,
        "redundant_duplicate_missing_target_rows": None,
        "valid_target_rows": None,
        "missing_target_rows": None,
        "target_count_unit": "unavailable_legacy_count_only",
        "keep_semantics": "first",
        "writable_authority": False,
        "purpose": "legacy_compatibility_projection",
        "verified": False,
        "calculation_status": "unverified_legacy_redundant_count_only",
    }


def build_population_contract(
    *,
    registered_rows: int,
    development_rows: Optional[int],
    holdout_rows: Optional[int],
    primary_scope: PopulationScope,
    primary_purpose: str,
    project_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    dataset_version_id: Optional[str] = None,
    target: Optional[str] = None,
    target_contract_id: Optional[str] = None,
    predictor_authorization_id: Optional[str] = None,
    analysis_partition_id: Optional[str] = None,
    analysis_partition_revision: Optional[int] = None,
    analysis_population_id: Optional[str] = None,
    population_policy_id: Optional[str] = None,
    treatment_policy_id: Optional[str] = None,
    treatment_policy_revision: Optional[int] = None,
    special_value_policy_id: Optional[str] = None,
    analysis_rows: Optional[int] = None,
    fit_rows: Optional[int] = None,
    application_rows: Optional[int] = None,
    materialization_rows: Optional[int] = None,
    registered_predictor_duplicate_rows: Optional[int] = None,
    development_analysis_duplicate_rows: Optional[int] = None,
    registered_duplicate_contract: Optional[Mapping[str, Any]] = None,
    development_duplicate_contract: Optional[Mapping[str, Any]] = None,
    rendered_rows: Optional[int] = None,
    descriptive_scope: str = "registered_structural_population",
    analysis_scope: str = "development_population",
    target_scope: str = "development_population",
    target_directed_scope: Optional[str] = None,
    fit_scope: str = "not_applicable",
    application_scope: str = "not_applicable",
    materialization_scope: str = "not_applicable",
    render_scope: str = "not_applicable",
    registered_structural_predictors_accessed: bool = False,
    final_holdout_target_accessed: bool = False,
    final_holdout_predictors_included_in_structural_profile: bool = False,
    final_holdout_parameter_influence: bool = False,
    final_holdout_used_for_selection: bool = False,
    final_holdout_transformed_or_materialized_prelock: bool = False,
    final_holdout_opened_for_final_reporting: bool = False,
) -> dict[str, Any]:
    """Build a canonical population contract with an inseparable primary scope.

    ``registered_predictor_duplicate_rows`` is the structural duplicate count
    over the registered predictor frame (target excluded).
    ``development_analysis_duplicate_rows`` is the decision-facing count over
    the governed development analysis frame (authorized predictors plus target).
    """

    registered = _nonnegative(registered_rows, field="registered_rows")
    development = _optional_nonnegative(
        development_rows, field="development_rows"
    )
    holdout = _optional_nonnegative(holdout_rows, field="holdout_rows")
    rendered = _optional_nonnegative(rendered_rows, field="rendered_rows")
    analysis_count = _optional_nonnegative(
        analysis_rows if analysis_rows is not None else development,
        field="analysis_rows",
    )
    fit_count = _optional_nonnegative(fit_rows, field="fit_rows")
    application_count = _optional_nonnegative(
        application_rows, field="application_rows"
    )
    materialization_count = _optional_nonnegative(
        materialization_rows, field="materialization_rows"
    )
    if (development is None) != (holdout is None):
        raise ValueError(
            "development_rows and holdout_rows must both be known or both be unknown."
        )
    if development is not None and development + int(holdout or 0) != registered:
        raise ValueError(
            "Development and holdout counts do not reconcile to the registered population."
        )

    if primary_scope == "registered_structural_population":
        primary_rows = registered
    elif primary_scope == "development_population":
        if development is None:
            raise ValueError(
                "A Development primary scope requires an exact development row count."
            )
        primary_rows = development
    elif primary_scope == "rendered_sample":
        if rendered is None:
            raise ValueError("A rendered-sample scope requires rendered_rows.")
        primary_rows = rendered
    else:  # pragma: no cover - guarded by the type and retained fail-closed
        raise ValueError(f"Unsupported primary population scope: {primary_scope}")

    registered_duplicates = _optional_nonnegative(
        registered_predictor_duplicate_rows,
        field="registered_predictor_duplicate_rows",
    )
    development_duplicates = _optional_nonnegative(
        development_analysis_duplicate_rows,
        field="development_analysis_duplicate_rows",
    )
    if registered_duplicates is not None and registered_duplicates > registered:
        raise ValueError("Registered duplicate rows cannot exceed registered rows.")
    if (
        development_duplicates is not None
        and development is not None
        and development_duplicates > development
    ):
        raise ValueError("Development duplicate rows cannot exceed development rows.")

    if registered_duplicate_contract is None:
        registered_duplicate_contract = _legacy_duplicate_count_projection(
            scope="registered_structural_population",
            row_count=registered,
            redundant_duplicate_rows=registered_duplicates,
            target_column=None,
            target_included=False,
        )
    if development_duplicate_contract is None and development is not None:
        development_duplicate_contract = _legacy_duplicate_count_projection(
            scope="development_population",
            row_count=development,
            redundant_duplicate_rows=development_duplicates,
            target_column=target,
            target_included=True,
        )

    projection: dict[str, Any] = {
        "contract_version": POPULATION_CONTRACT_VERSION,
        "identity": {
            "project_id": str(project_id or ""),
            "dataset_id": str(dataset_id or ""),
            "dataset_version_id": str(dataset_version_id or ""),
            "target": str(target or ""),
            "target_contract_id": str(target_contract_id or ""),
            "predictor_authorization_id": str(
                predictor_authorization_id or ""
            ),
            "analysis_partition_id": str(analysis_partition_id or ""),
            "analysis_partition_revision": (
                int(analysis_partition_revision)
                if analysis_partition_revision is not None
                else None
            ),
            "analysis_population_id": str(analysis_population_id or ""),
            "population_id": str(analysis_population_id or ""),
            "population_policy_id": str(population_policy_id or ""),
            "treatment_policy_id": str(treatment_policy_id or ""),
            "treatment_policy_revision": (
                int(treatment_policy_revision)
                if treatment_policy_revision is not None
                else None
            ),
            "special_value_policy_id": str(special_value_policy_id or ""),
        },
        "counts": {
            "registered_rows": registered,
            "development_rows": development,
            "holdout_rows": holdout,
            "analysis_rows": analysis_count,
            "fit_rows": fit_count,
            "application_rows": application_count,
            "materialization_rows": materialization_count,
            "rendered_rows": rendered,
            "reconciled": development is not None,
            "registered_population_rows": registered,
            "development_population_rows": development,
            "sealed_final_holdout_rows": holdout,
            "analysis_population_rows": analysis_count,
            "fit_population_rows": fit_count,
            "application_population_rows": application_count,
            "rendered_sample_rows": rendered,
        },
        "scopes": {
            "descriptive_scope": str(descriptive_scope),
            "analysis_scope": str(analysis_scope),
            "target_scope": str(target_scope),
            "target_directed_scope": str(
                target_directed_scope
                if target_directed_scope is not None
                else target_scope
            ),
            "fit_scope": str(fit_scope),
            "application_scope": str(application_scope),
            "materialization_scope": str(materialization_scope),
            "render_scope": str(render_scope),
        },
        "primary": {
            "scope": primary_scope,
            "purpose": str(primary_purpose or "").strip(),
            "row_count": primary_rows,
        },
        "partition": {
            "analysis_partition_id": str(analysis_partition_id or ""),
            "analysis_partition_revision": (
                int(analysis_partition_revision)
                if analysis_partition_revision is not None
                else None
            ),
            "analysis_population_id": str(analysis_population_id or ""),
        },
        "holdout_truth": {
            "status": "sealed" if holdout is not None else "not_available",
            "final_holdout_target_accessed": bool(
                final_holdout_target_accessed
            ),
            "final_holdout_predictors_included_in_structural_profile": bool(
                final_holdout_predictors_included_in_structural_profile
                or registered_structural_predictors_accessed
            ),
            "final_holdout_parameter_influence": bool(
                final_holdout_parameter_influence
            ),
            "final_holdout_used_for_selection": bool(
                final_holdout_used_for_selection
            ),
            "final_holdout_transformed_or_materialized_prelock": bool(
                final_holdout_transformed_or_materialized_prelock
            ),
            "final_holdout_opened_for_final_reporting": bool(
                final_holdout_opened_for_final_reporting
            ),
            "registered_structural_profile": {
                "predictors_accessed": bool(
                    registered_structural_predictors_accessed
                ),
                "target_accessed": False,
                "used_for_selection": False,
            },
            "development_target_directed_analysis": {
                "holdout_predictors_accessed": False,
                "holdout_target_accessed": False,
                "used_for_selection": False,
            },
            "final_holdout_evaluation": {
                "target_accessed": bool(final_holdout_target_accessed),
                "used_for_selection": bool(final_holdout_used_for_selection),
            },
        },
        "duplicates": {
            "registered_predictor_frame": (
                dict(registered_duplicate_contract)
                if registered_duplicate_contract is not None
                else None
            ),
            "development_analysis_frame": (
                dict(development_duplicate_contract)
                if development_duplicate_contract is not None
                else None
            ),
        },
        # Canonical count aliases are repeated at the root for transport
        # consumers that cannot safely traverse compatibility payloads.
        "registered_population_rows": registered,
        "development_population_rows": development,
        "sealed_final_holdout_rows": holdout,
        "analysis_population_rows": analysis_count,
        "fit_population_rows": fit_count,
        "application_population_rows": application_count,
        "rendered_sample_rows": rendered,
    }
    contract_hash = _stable_hash(projection)
    return {
        **projection,
        "contract_id": f"population-contract-{contract_hash[:20]}",
        "contract_hash": contract_hash,
    }


def primary_scope_projection(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return compatibility fields sourced from one primary contract node."""

    primary = contract.get("primary")
    if not isinstance(primary, Mapping):
        raise ValueError("Population contract is missing its primary scope.")
    return {
        "scope": str(primary.get("scope") or ""),
        "row_count": _nonnegative(primary.get("row_count"), field="row_count"),
        "population_contract": dict(contract),
        "population_counts": dict(contract.get("counts") or {}),
        "holdout_truth": dict(contract.get("holdout_truth") or {}),
    }


def build_eda_completion_contract(
    population_contract: Mapping[str, Any],
    *,
    duplicate_parent_id: str = "eda-parent-exact-duplicate-rows",
) -> dict[str, Any]:
    """Publish the backend-owned EDA duplicate decision boundary."""

    duplicates = population_contract.get("duplicates") or {}
    development = duplicates.get("development_analysis_frame") or {}
    partition = population_contract.get("partition") or {}
    duplicate_rows = _optional_nonnegative(
        development.get("duplicate_rows"), field="development_duplicate_rows"
    )
    projection = {
        "contract_version": DUPLICATE_AUTHORITY_VERSION,
        "population_contract_id": str(
            population_contract.get("contract_id") or ""
        ),
        "duplicate_authority": {
            "parent_id": duplicate_parent_id,
            "scope": "development_population",
            "duplicate_rows": duplicate_rows,
            "writable_source": "governed_parent_finding",
            "legacy_duplicate_decision": "read_only_compatibility_history",
            "resolution_actions": [
                "retain_current_population",
                "exclude_upstream_and_repartition",
            ],
        },
        "exclude_upstream_and_repartition": {
            "allowed_in_current_confirmation": False,
            "requires_registered_population_revision": True,
            "requires_analysis_partition_revision": True,
            "current_analysis_partition_id": str(
                partition.get("analysis_partition_id") or ""
            ),
            "current_analysis_partition_revision": partition.get(
                "analysis_partition_revision"
            ),
        },
    }
    contract_hash = _stable_hash(projection)
    return {
        **projection,
        "contract_id": f"eda-completion-contract-{contract_hash[:20]}",
        "contract_hash": contract_hash,
    }

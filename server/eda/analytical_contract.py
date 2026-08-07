"""Backend-authoritative analytical contract for governed EDA.

This module is intentionally independent of the EDA presentation layer.  It
resolves the exact materialized development partition, classifies values once,
and produces the predictor and relationship artifacts consumed by every EDA
workspace. It never reads final-holdout values; the only holdout datum it uses
is the row count recorded in the durable Analysis Partition contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ..preprocessing.bureau_registry import BUREAU_SPECIAL_VALUES, name_signals


CONTRACT_VERSION = "governed-eda-analytical-contract/1"
TARGET_ARTIFACT_VERSION = "governed-eda-target/1"
PREDICTOR_ARTIFACT_VERSION = "governed-eda-predictor/1"
RELATIONSHIP_ARTIFACT_VERSION = "governed-eda-relationships/1"
SUPPORTED_SCOPES = [
    "full_governed_population",
    "development_population",
    "out_of_fold",
    "final_holdout",
    "out_of_time",
    "bounded_visual_sample",
]
WOE_SMOOTHING_CONSTANT = 0.5
DEFAULT_REQUESTED_BINS = 10
MONOTONICITY_TOLERANCE = 0.005
MINIMUM_BAND_POPULATION = 20


class EDAAnalyticalContractError(ValueError):
    """Fail-closed analytical-scope error safe to expose as a 409 response."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "analysis_partition_stale",
        recovery: str | None = None,
        stale_artifacts: Iterable[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recovery = recovery or (
            "Return to Data Acquisition and confirm the governed Analysis Partition."
        )
        self.stale_artifacts = sorted(
            {str(value) for value in (stale_artifacts or []) if str(value)}
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json_scalar(value: Any) -> Any:
    """Normalize governed category values before they enter artifact lineage.

    Pandas returns NumPy scalar objects from ``unique`` and ``value_counts``.
    Those objects compare like their Python equivalents, which made the
    analytical tests pass, but FastAPI cannot serialize them.  Event identity
    is part of the durable analytical contract, so normalize it at this
    authoritative boundary rather than relying only on presentation code.
    """

    if value is None or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        return _json_scalar(value.item())
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _same_target_scalar(left: Any, right: Any) -> bool:
    """Compare category labels without letting a client redefine their type.

    Browser controls historically serialize numeric class labels as strings,
    so ``1`` and ``"1"`` remain compatible assertions.  Missing and present
    values are never equivalent, and every value returned to analytical code
    still comes from the durable partition rather than from this comparison.
    """

    normalized_left = _json_scalar(left)
    normalized_right = _json_scalar(right)
    if normalized_left is None or normalized_right is None:
        return normalized_left is None and normalized_right is None
    return str(normalized_left) == str(normalized_right)


def resolve_partition_target_authority(
    partition: dict[str, Any],
    *,
    target: str,
    requested_problem_type: str | None = None,
    requested_event_value: Any = None,
) -> dict[str, Any]:
    """Resolve target semantics only from an integrity-verified partition.

    Request values are compare-only assertions.  They may be omitted, but a
    supplied value that contradicts the documented Analysis Partition fails
    closed before any target-directed calculation or cache lookup.
    """

    try:
        from ..analysis_partition.types import AnalysisPartitionError
        from ..analysis_partition.service import analysis_partition_service

        authority = analysis_partition_service.target_authority_compatibility(
            partition
        )
    except ImportError as exc:
        raise EDAAnalyticalContractError(
            "Analysis Partition target authority is unavailable.",
            code="analysis_partition_required",
        ) from exc
    except AnalysisPartitionError as exc:
        raise EDAAnalyticalContractError(
            str(exc),
            code=exc.code,
            recovery=exc.recovery,
            stale_artifacts=exc.stale_artifacts,
        ) from exc

    governed_target = str(authority.get("target") or "").strip()
    if not governed_target or governed_target != str(target or "").strip():
        raise EDAAnalyticalContractError(
            "The requested target does not match the documented Analysis Partition target authority.",
            code="target_contract_stale",
            stale_artifacts=["target_eda", "predictor_eda", "relationship_eda"],
        )

    problem_type = str(authority.get("problem_type") or "").strip().lower()
    if problem_type not in {"classification", "regression"}:
        raise EDAAnalyticalContractError(
            "The documented Analysis Partition has no verified problem type.",
            code="analysis_partition_target_authority_unverified",
            stale_artifacts=["target_eda", "predictor_eda", "relationship_eda"],
        )
    requested_problem = str(requested_problem_type or "").strip().lower()
    if requested_problem and requested_problem != problem_type:
        raise EDAAnalyticalContractError(
            "The requested problem type contradicts the documented Analysis Partition target authority.",
            code="target_contract_stale",
            stale_artifacts=["target_eda", "predictor_eda", "relationship_eda"],
        )

    positive_value = _json_scalar(authority.get("event_value"))
    negative_value = _json_scalar(authority.get("non_event_value"))
    if requested_event_value is not None and (
        problem_type != "classification"
        or not _same_target_scalar(requested_event_value, positive_value)
    ):
        raise EDAAnalyticalContractError(
            "The requested event value contradicts the documented Analysis Partition target authority.",
            code="target_contract_stale",
            stale_artifacts=["target_eda", "predictor_eda", "relationship_eda"],
        )

    return {
        **dict(authority),
        "target": governed_target,
        "problem_type": problem_type,
        "positive_value": positive_value if problem_type == "classification" else None,
        "negative_value": negative_value if problem_type == "classification" else None,
    }


def _frame_hash(frame: pd.DataFrame, target: pd.Series) -> str:
    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    digest.update(pd.util.hash_pandas_object(target, index=True).values.tobytes())
    return digest.hexdigest()


def _event_rate(target: pd.Series, mask: pd.Series, event_value: Any) -> tuple[int, float | None]:
    eligible = mask & target.notna()
    count = int(eligible.sum())
    if count == 0:
        return 0, None
    events = int((target[eligible].astype(str) == str(event_value)).sum())
    return events, events / count


def _wilson_interval(events: int, rows: int, z: float = 1.959963984540054) -> list[float] | None:
    if rows <= 0:
        return None
    rate = events / rows
    denominator = 1 + (z * z / rows)
    centre = rate + (z * z / (2 * rows))
    margin = z * math.sqrt((rate * (1 - rate) / rows) + (z * z / (4 * rows * rows)))
    return [max(0.0, (centre - margin) / denominator), min(1.0, (centre + margin) / denominator)]


def _is_bureau_feature(feature: str, meta: dict[str, Any]) -> tuple[bool, list[str]]:
    source = meta.get("source") if isinstance(meta.get("source"), dict) else {}
    source_label = " ".join(str(source.get(key) or "") for key in ("filename", "datasetName", "name"))
    basis: list[str] = []
    if "heloc" in source_label.casefold():
        basis.append("registered_heloc_source")
    if name_signals(feature):
        basis.append("server_bureau_name_signal")
    review = meta.get("bureau_review") if isinstance(meta.get("bureau_review"), dict) else {}
    for row in review.get("variables") or []:
        if isinstance(row, dict) and str(row.get("variable") or "").casefold() == feature.casefold():
            basis.append("governed_bureau_review")
            break
    return bool(basis), basis


def _governed_special_definitions(
    feature: str,
    meta: dict[str, Any],
) -> tuple[dict[float, str], list[str]]:
    """Resolve a predictor's explicit special-value policy when available.

    A registered source name identifies the domain, not the set of sentinel
    codes for every predictor.  Per-feature reviewed policy therefore wins;
    the shared bureau registry is only the fallback for an identified bureau
    feature.  This preserves positive HELOC sentinels (96--99) without
    reclassifying the same ordinary number on a feature whose governed policy
    excludes it.
    """

    identified, basis = _is_bureau_feature(feature, meta)
    if not identified:
        return {}, basis
    review = meta.get("bureau_review") if isinstance(meta.get("bureau_review"), dict) else {}
    row = next(
        (
            item
            for item in review.get("variables") or []
            if isinstance(item, dict)
            and str(item.get("variable") or "").casefold() == feature.casefold()
        ),
        None,
    )
    if isinstance(row, dict):
        explicit_policy = row.get("special_value_policy")
        if isinstance(explicit_policy, dict):
            configured = (
                explicit_policy.get("included_codes")
                if isinstance(explicit_policy.get("included_codes"), list)
                else explicit_policy.get("allowed_codes")
            )
            if isinstance(configured, list):
                definitions: dict[float, str] = {}
                labels = explicit_policy.get("definitions")
                labels = labels if isinstance(labels, dict) else {}
                for value in configured:
                    try:
                        numeric = float(value)
                    except (TypeError, ValueError):
                        continue
                    definitions[numeric] = str(
                        labels.get(str(value))
                        or labels.get(str(int(numeric)) if numeric.is_integer() else str(numeric))
                        or BUREAU_SPECIAL_VALUES.get(int(numeric), "Configured bureau special value")
                    )
                return definitions, [*basis, "governed_per_feature_special_value_policy"]

        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        metadata_definitions = metadata.get("specialValueDefinitions") or metadata.get(
            "special_value_definitions"
        )
        if metadata_definitions:
            definitions = {}
            import re

            for token, label in re.findall(
                r"(-?\d+(?:\.\d+)?)\s*(?:=|:)\s*([^,;|]+)",
                str(metadata_definitions),
            ):
                numeric = float(token)
                definitions[numeric] = label.strip()
            if definitions:
                return definitions, [*basis, "governed_metadata_special_value_definitions"]

        reviewed_values = row.get("special_values")
        if isinstance(reviewed_values, list) and reviewed_values:
            definitions = {}
            for item in reviewed_values:
                if not isinstance(item, dict):
                    continue
                try:
                    numeric = float(item.get("value"))
                except (TypeError, ValueError):
                    continue
                definitions[numeric] = str(
                    item.get("definition")
                    or BUREAU_SPECIAL_VALUES.get(int(numeric), "Configured bureau special value")
                )
            if definitions:
                return definitions, [*basis, "governed_reviewed_special_values"]

    return {
        float(value): label for value, label in BUREAU_SPECIAL_VALUES.items()
    }, [*basis, "shared_bureau_registry"]


def classify_feature_values(
    feature: str,
    series: pd.Series,
    *,
    meta: dict[str, Any],
    target: pd.Series | None = None,
    event_value: Any = None,
) -> dict[str, Any]:
    """Return mutually exclusive governed value classes for one predictor."""

    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    is_numeric = bool(
        pd.api.types.is_numeric_dtype(series)
        or numeric.notna().sum() / max(int(series.notna().sum()), 1) >= 0.8
    )
    true_null = series.isna()
    parse_failure = series.notna() & numeric.isna() if is_numeric else pd.Series(False, index=series.index)
    definitions, identification_basis = _governed_special_definitions(feature, meta)
    allowed_codes = set(definitions)
    special = (
        numeric.isin(allowed_codes) & series.notna()
        if is_numeric and bool(definitions)
        else pd.Series(False, index=series.index)
    )
    ordinary_valid = (
        numeric.notna() & ~special
        if is_numeric
        else series.notna()
    )

    masks = {
        "true_null": true_null.astype(bool),
        "bureau_special_value": special.astype(bool),
        "ordinary_valid_value": ordinary_valid.astype(bool),
        "parse_failure": parse_failure.astype(bool),
    }
    overlap = sum(mask.astype(int) for mask in masks.values())
    if bool((overlap > 1).any()):
        raise EDAAnalyticalContractError(f"Value classes overlap for predictor '{feature}'.")

    ordinary = numeric[ordinary_valid] if is_numeric else pd.Series(dtype=float)
    outlier_mask = pd.Series(False, index=series.index, dtype=bool)
    lower = upper = None
    if is_numeric and not ordinary.empty:
        q1 = float(ordinary.quantile(0.25))
        q3 = float(ordinary.quantile(0.75))
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outlier_mask = ordinary_valid & ((numeric < lower) | (numeric > upper))
    if bool((outlier_mask & ~ordinary_valid).any()):
        raise EDAAnalyticalContractError(
            f"Ordinary outliers are not a subset of ordinary valid values for '{feature}'."
        )

    target_series = target if target is not None else pd.Series(index=series.index, dtype=object)
    ordinary_events, ordinary_event_rate = _event_rate(target_series, ordinary_valid, event_value)
    groups: list[dict[str, Any]] = []
    if bool(special.any()):
        for value, rows in numeric[special].value_counts().sort_index().items():
            value_mask = special & numeric.eq(value)
            events, rate = _event_rate(target_series, value_mask, event_value)
            row_count = int(value_mask.sum())
            numeric_value = float(value)
            groups.append(
                {
                    "code": int(numeric_value) if numeric_value.is_integer() else numeric_value,
                    "definition": definitions.get(
                        numeric_value,
                        BUREAU_SPECIAL_VALUES.get(
                            int(numeric_value), "Configured bureau special value"
                        ),
                    ),
                    "rows": row_count,
                    "population_share": row_count / max(len(series), 1),
                    "event_count": events,
                    "event_rate": rate,
                    "valid_value_event_rate_difference": (
                        rate - ordinary_event_rate
                        if rate is not None and ordinary_event_rate is not None
                        else None
                    ),
                    "event_rate_confidence_interval_95": _wilson_interval(events, row_count),
                }
            )

    return {
        "feature": feature,
        "is_numeric": is_numeric,
        "series": series,
        "numeric": numeric,
        "masks": masks,
        "ordinary_outlier_mask": outlier_mask,
        "counts": {
            "true_null": int(true_null.sum()),
            "bureau_special_value": int(special.sum()),
            "ordinary_valid_value": int(ordinary_valid.sum()),
            "ordinary_numeric_outlier": int(outlier_mask.sum()),
            "parse_failure": int(parse_failure.sum()),
        },
        "special_groups": groups,
        "special_identification_basis": identification_basis,
        "ordinary_event_count": ordinary_events,
        "ordinary_event_rate": ordinary_event_rate,
        "outlier_lower": _finite(lower),
        "outlier_upper": _finite(upper),
    }


def _reversal_count(rates: list[float | None], tolerance: float) -> int:
    directions: list[int] = []
    values = [float(value) for value in rates if value is not None]
    for left, right in zip(values, values[1:]):
        difference = right - left
        if abs(difference) <= tolerance:
            continue
        directions.append(1 if difference > 0 else -1)
    return sum(left != right for left, right in zip(directions, directions[1:]))


def _classify_monotonicity_with_tolerance(
    rates: list[float | None],
    tolerance: float,
) -> str:
    values = [float(value) for value in rates if value is not None]
    if len(values) < 3:
        return "Insufficient bins"
    directions: list[int] = []
    for left, right in zip(values, values[1:]):
        difference = right - left
        if abs(difference) <= tolerance:
            continue
        directions.append(1 if difference > 0 else -1)
    if not directions:
        return "Flat"
    if all(direction > 0 for direction in directions):
        return "Increasing"
    if all(direction < 0 for direction in directions):
        return "Decreasing"
    return "Non-monotonic"


def _ordinary_quantile_bins(
    values: pd.Series,
    target: pd.Series,
    event_value: Any,
    requested_bins: int,
) -> tuple[list[dict[str, Any]], int]:
    frame = pd.DataFrame({"value": values, "target": target}).dropna(subset=["value", "target"])
    if frame.empty:
        return [], 0
    population_limited_bins = max(1, len(frame) // MINIMUM_BAND_POPULATION)
    effective_request = min(
        requested_bins,
        int(frame["value"].nunique()),
        population_limited_bins,
    )
    if effective_request <= 1:
        bucket = pd.Series(0, index=frame.index, dtype=int)
    else:
        try:
            bucket = pd.qcut(frame["value"], q=effective_request, labels=False, duplicates="drop")
        except ValueError:
            bucket = pd.Series(0, index=frame.index, dtype=int)
    frame["bucket"] = bucket
    frame["event"] = frame["target"].astype(str).eq(str(event_value))
    rows: list[dict[str, Any]] = []
    for position, (_bucket, group) in enumerate(frame.groupby("bucket", observed=True, sort=True)):
        lower = float(group["value"].min())
        upper = float(group["value"].max())
        events = int(group["event"].sum())
        count = int(len(group))
        rows.append(
            {
                "bin_index": position + 1,
                "bin_type": "ordinary_valid_range",
                "label": f"[{lower:g}, {upper:g}]" if position == 0 else f"({lower:g}, {upper:g}]",
                "lower": lower,
                "upper": upper,
                "lower_inclusive": position == 0,
                "upper_inclusive": True,
                "count": count,
                "event_count": events,
                "non_event_count": count - events,
                "event_rate": events / count if count else None,
                "empty": False,
            }
        )
    # Tied values can still create a small edge bucket even after limiting the
    # requested count. Merge such a bucket with its nearest neighbor so the
    # reported minimum population is an enforced rule, not decorative metadata.
    while len(rows) > 1:
        small_index = next(
            (
                index
                for index, row in enumerate(rows)
                if int(row["count"]) < MINIMUM_BAND_POPULATION
            ),
            None,
        )
        if small_index is None:
            break
        neighbor_index = 1 if small_index == 0 else small_index - 1
        left_index, right_index = sorted((small_index, neighbor_index))
        left = rows[left_index]
        right = rows[right_index]
        count = int(left["count"]) + int(right["count"])
        events = int(left["event_count"]) + int(right["event_count"])
        merged = {
            **left,
            "lower": min(float(left["lower"]), float(right["lower"])),
            "upper": max(float(left["upper"]), float(right["upper"])),
            "count": count,
            "event_count": events,
            "non_event_count": count - events,
            "event_rate": events / count if count else None,
        }
        rows[left_index : right_index + 1] = [merged]
    for position, row in enumerate(rows):
        row["bin_index"] = position + 1
        row["lower_inclusive"] = position == 0
        row["upper_inclusive"] = True
        row["label"] = (
            f"[{float(row['lower']):g}, {float(row['upper']):g}]"
            if position == 0
            else f"({float(row['lower']):g}, {float(row['upper']):g}]"
        )
    return rows, len(rows)


def _iv_woe_artifact(
    *,
    feature: str,
    classification: dict[str, Any],
    target: pd.Series,
    event_value: Any,
    negative_value: Any,
    requested_bins: int,
    population_identity: str,
    scope: str,
) -> dict[str, Any]:
    numeric = classification["numeric"]
    ordinary_mask = classification["masks"]["ordinary_valid_value"] & target.notna()
    if classification["is_numeric"]:
        ordinary_bins, effective_bins = _ordinary_quantile_bins(
            numeric[ordinary_mask], target[ordinary_mask], event_value, requested_bins
        )
        binning_method = "development_population_quantile_actual_value_boundaries"
    else:
        category_frame = pd.DataFrame(
            {
                "value": classification["series"][ordinary_mask].astype(str),
                "target": target[ordinary_mask],
            }
        )
        ordered = category_frame["value"].value_counts()
        keep = set(ordered.head(50).index)
        category_frame["value"] = category_frame["value"].where(
            category_frame["value"].isin(keep), "__OTHER__"
        )
        category_frame["event"] = category_frame["target"].astype(str).eq(str(event_value))
        ordinary_bins = []
        for position, (category, group) in enumerate(
            category_frame.groupby("value", sort=False, dropna=False)
        ):
            events = int(group["event"].sum())
            count = int(len(group))
            ordinary_bins.append(
                {
                    "bin_index": position + 1,
                    "bin_type": "ordinary_category",
                    "label": str(category),
                    "lower": None,
                    "upper": None,
                    "lower_inclusive": None,
                    "upper_inclusive": None,
                    "count": count,
                    "event_count": events,
                    "non_event_count": count - events,
                    "event_rate": events / count if count else None,
                    "empty": False,
                }
            )
        effective_bins = len(ordinary_bins)
        binning_method = "development_population_governed_categorical_groups"
    rows = list(ordinary_bins)
    special_mask = classification["masks"]["bureau_special_value"] & target.notna()
    for group in classification["special_groups"]:
        group_mask = special_mask & numeric.eq(group["code"])
        events, rate = _event_rate(target, group_mask, event_value)
        count = int(group_mask.sum())
        rows.append(
            {
                "bin_index": len(rows) + 1,
                "bin_type": "bureau_special_group",
                "label": f"{group['code']}: {group['definition']}",
                "lower": None,
                "upper": None,
                "count": count,
                "event_count": events,
                "non_event_count": count - events,
                "event_rate": rate,
                "empty": False,
            }
        )
    for mask_name, label in (
        ("true_null", "True null"),
        ("parse_failure", "Parse failure"),
    ):
        mask = classification["masks"][mask_name] & target.notna()
        count = int(mask.sum())
        if count:
            events, rate = _event_rate(target, mask, event_value)
            rows.append(
                {
                    "bin_index": len(rows) + 1,
                    "bin_type": mask_name,
                    "label": label,
                    "lower": None,
                    "upper": None,
                    "count": count,
                    "event_count": events,
                    "non_event_count": count - events,
                    "event_rate": rate,
                    "empty": False,
                }
            )

    # Empty theoretical intervals are never materialized.  All nonempty bins,
    # including named special/missing groups, participate in IV with one
    # documented smoothing policy.
    event_total = sum(int(row["event_count"]) for row in rows)
    nonevent_total = sum(int(row["non_event_count"]) for row in rows)
    bin_count = len(rows)
    event_denominator = event_total + WOE_SMOOTHING_CONSTANT * bin_count
    nonevent_denominator = nonevent_total + WOE_SMOOTHING_CONSTANT * bin_count
    iv = 0.0
    for row in rows:
        event_distribution = (row["event_count"] + WOE_SMOOTHING_CONSTANT) / max(
            event_denominator, WOE_SMOOTHING_CONSTANT
        )
        nonevent_distribution = (row["non_event_count"] + WOE_SMOOTHING_CONSTANT) / max(
            nonevent_denominator, WOE_SMOOTHING_CONSTANT
        )
        woe = math.log(event_distribution / nonevent_distribution)
        contribution = (event_distribution - nonevent_distribution) * woe
        row.update(
            {
                "event_distribution": event_distribution,
                "non_event_distribution": nonevent_distribution,
                "woe": woe,
                "iv_contribution": contribution,
            }
        )
        iv += contribution

    base = {
        "feature": feature,
        "binning_method": binning_method,
        "requested_bins": requested_bins,
        "effective_nonempty_bins": effective_bins,
        "total_reported_groups": len(rows),
        "minimum_bin_population": MINIMUM_BAND_POPULATION,
        "minimum_bin_population_applies_to": "ordinary_valid_bins_only",
        "special_value_treatment": "separate_named_groups_outside_ordinary_quantiles",
        "missing_value_treatment": "separate_true_null_and_parse_failure_groups",
        "event_definition": {"positive_value": event_value, "negative_value": negative_value},
        "WoE_smoothing_constant": WOE_SMOOTHING_CONSTANT,
        "zero_event_handling": "additive_smoothing",
        "zero_nonevent_handling": "additive_smoothing",
        "analysis_scope": scope,
        "population_identity": population_identity,
        "bin_boundary_convention": (
            "first [observed_min, observed_max], subsequent (observed_min, observed_max]"
            if classification["is_numeric"]
            else "exact governed category label; rare levels collapse to __OTHER__"
        ),
        "collapsed_boundary_explanation": (
            "Repeated predictor values collapsed quantile boundaries; only nonempty observed-value bins are shown."
            if classification["is_numeric"] and effective_bins < requested_bins
            else None
        ),
        "empty_interval_policy": "suppressed",
        "iv": max(0.0, float(iv)),
        "bins": rows,
    }
    artifact_hash = _stable_hash(base)
    return {
        **base,
        "artifact_version": PREDICTOR_ARTIFACT_VERSION,
        "artifact_id": f"eda-iv-{artifact_hash[:20]}",
        "artifact_hash": artifact_hash,
    }


def _target_artifact(
    *,
    target_name: str,
    target: pd.Series,
    problem_type: str,
    positive_value: Any,
    negative_value: Any,
    population_identity: str,
    governed_lineage_base: dict[str, Any],
) -> dict[str, Any]:
    """Return the development-only target evidence used by governed decisions."""

    valid = target[target.notna()]
    base: dict[str, Any] = {
        "target": target_name,
        "problem_type": problem_type,
        "analysis_scope": "development_population",
        "analysis_population_id": population_identity,
        "population_rows": int(len(target)),
        "valid_count": int(len(valid)),
        "missing_count": int(target.isna().sum()),
        "distinct_value_count": int(valid.astype(str).nunique()),
        "positive_value": positive_value,
        "negative_value": negative_value,
        "final_holdout_accessed": False,
        "final_holdout_used_for_selection": False,
    }
    if problem_type == "classification":
        event_count = int((valid.astype(str) == str(positive_value)).sum())
        non_event_count = int(len(valid) - event_count)
        base.update(
            {
                "applicable": True,
                "event_count": event_count,
                "non_event_count": non_event_count,
                "event_rate": event_count / len(valid) if len(valid) else None,
                "non_event_rate": non_event_count / len(valid) if len(valid) else None,
                "class_distribution": [
                    {"value": str(value), "count": int(count)}
                    for value, count in valid.astype(str).value_counts().sort_index().items()
                ],
                "regression_summary": None,
            }
        )
        calculation_method = "development_population_class_prevalence"
    else:
        numeric = pd.to_numeric(valid, errors="coerce")
        parse_failure_count = int(numeric.isna().sum())
        numeric = numeric.dropna()
        summary = {
            "count": int(len(numeric)),
            "mean": _finite(numeric.mean()) if len(numeric) else None,
            "standard_deviation": _finite(numeric.std(ddof=1)) if len(numeric) > 1 else None,
            "minimum": _finite(numeric.min()) if len(numeric) else None,
            "q1": _finite(numeric.quantile(0.25)) if len(numeric) else None,
            "median": _finite(numeric.median()) if len(numeric) else None,
            "q3": _finite(numeric.quantile(0.75)) if len(numeric) else None,
            "maximum": _finite(numeric.max()) if len(numeric) else None,
        }
        base.update(
            {
                "applicable": True,
                "event_count": None,
                "non_event_count": None,
                "event_rate": None,
                "non_event_rate": None,
                "class_distribution": [],
                "parse_failure_count": parse_failure_count,
                "regression_summary": summary,
            }
        )
        calculation_method = "development_population_numeric_summary"

    artifact_hash = _stable_hash(base)
    artifact_id = f"eda-target-{artifact_hash[:20]}"
    return {
        **base,
        "artifact_id": artifact_id,
        "artifact_version": TARGET_ARTIFACT_VERSION,
        "artifact_hash": artifact_hash,
        "governed_lineage": {
            **governed_lineage_base,
            "artifact_id": artifact_id,
            "artifact_version": TARGET_ARTIFACT_VERSION,
            "artifact_hash": artifact_hash,
            "calculation_method": calculation_method,
        },
    }


def _predictor_artifact(
    *,
    feature: str,
    development_series: pd.Series,
    full_series: pd.Series,
    target: pd.Series,
    event_value: Any,
    negative_value: Any,
    meta: dict[str, Any],
    population_identity: str,
    requested_bins: int,
    governed_lineage_base: dict[str, Any],
    problem_type: str,
) -> dict[str, Any]:
    development_classification = classify_feature_values(
        feature,
        development_series,
        meta=meta,
        target=target if problem_type == "classification" else None,
        event_value=event_value if problem_type == "classification" else None,
    )
    full_classification = classify_feature_values(feature, full_series, meta=meta)
    if problem_type == "classification":
        iv_woe = _iv_woe_artifact(
            feature=feature,
            classification=development_classification,
            target=target,
            event_value=event_value,
            negative_value=negative_value,
            requested_bins=requested_bins,
            population_identity=population_identity,
            scope="development_population",
        )
        iv_woe["applicable"] = True
        iv_woe["not_applicable_reason"] = None
    else:
        iv_base = {
            "feature": feature,
            "applicable": False,
            "not_applicable_reason": "IV/WoE requires a governed classification event; the target is regression.",
            "binning_method": "not_applicable_for_regression",
            "requested_bins": requested_bins,
            "effective_nonempty_bins": 0,
            "total_reported_groups": 0,
            "minimum_bin_population": MINIMUM_BAND_POPULATION,
            "minimum_bin_population_applies_to": "ordinary_valid_bins_only",
            "analysis_scope": "development_population",
            "population_identity": population_identity,
            "event_definition": {"positive_value": None, "negative_value": None},
            "iv": None,
            "bins": [],
        }
        iv_hash = _stable_hash(iv_base)
        iv_woe = {
            **iv_base,
            "artifact_version": PREDICTOR_ARTIFACT_VERSION,
            "artifact_id": f"eda-iv-{iv_hash[:20]}",
            "artifact_hash": iv_hash,
        }
    ordinary_bin_type = (
        "ordinary_valid_range"
        if development_classification["is_numeric"]
        else "ordinary_category"
    )
    ordinary_rates = [
        row.get("event_rate")
        for row in iv_woe["bins"]
        if row.get("bin_type") == ordinary_bin_type
    ]
    monotonicity = {
        "applicable": problem_type == "classification",
        "not_applicable_reason": (
            None
            if problem_type == "classification"
            else "Event-rate monotonicity is not applicable to a regression target."
        ),
        "valid_value_shape": (
            _classify_monotonicity_with_tolerance(
                ordinary_rates, MONOTONICITY_TOLERANCE
            )
            if problem_type == "classification"
            and development_classification["is_numeric"]
            else "Not applicable"
            if problem_type != "classification"
            else "Not ordered (categorical)"
        ),
        "special_value_group_behavior": development_classification["special_groups"],
        "overall_relationship_summary": (
            "Ordinary valid-value shape and bureau special groups are reported separately."
        ),
        "method": (
            "ordered_event_rate_by_governed_quantile_bin"
            if problem_type == "classification"
            else "not_applicable_for_regression"
        ),
        "tolerance": MONOTONICITY_TOLERANCE,
        "reversal_count": (
            _reversal_count(ordinary_rates, MONOTONICITY_TOLERANCE)
            if problem_type == "classification"
            else None
        ),
        "minimum_band_population": MINIMUM_BAND_POPULATION,
        "requested_bins": requested_bins,
        "effective_bins": iv_woe["effective_nonempty_bins"],
        "special_value_policy": "excluded_from_ordinary_monotonicity_and_reported_as_named_groups",
        "analysis_scope": "development_population",
    }
    mono_hash = _stable_hash({"feature": feature, **monotonicity})
    monotonicity.update(
        {
            "artifact_version": PREDICTOR_ARTIFACT_VERSION,
            "artifact_id": f"eda-monotonicity-{mono_hash[:20]}",
            "artifact_hash": mono_hash,
        }
    )
    full_counts = full_classification["counts"]
    ordinary_distribution: dict[str, Any] | None = None
    if full_classification["is_numeric"]:
        ordinary_values = full_classification["numeric"][
            full_classification["masks"]["ordinary_valid_value"]
        ].dropna()
        histogram: list[dict[str, Any]] = []
        if not ordinary_values.empty:
            bin_count = min(20, max(1, int(ordinary_values.nunique())))
            counts, edges = np.histogram(ordinary_values.to_numpy(dtype=float), bins=bin_count)
            for index, count in enumerate(counts):
                lower = float(edges[index])
                upper = float(edges[index + 1])
                width = max(upper - lower, 1e-12)
                histogram.append(
                    {
                        "bin": index + 1,
                        "lower": lower,
                        "upper": upper,
                        "count": int(count),
                        "share": int(count) / max(len(ordinary_values), 1),
                        "density": int(count) / max(len(ordinary_values) * width, 1e-12),
                    }
                )
            quantiles = ordinary_values.quantile([0.25, 0.5, 0.75])
            ordinary_distribution = {
                "analysis_scope": "full_governed_population",
                "population_semantics": "ordinary_valid_numeric_values_only",
                "histogram": histogram,
                "density_basis": "ordinary_valid_numeric_values_only",
                "boxplot": {
                    "minimum": float(ordinary_values.min()),
                    "q1": float(quantiles.loc[0.25]),
                    "median": float(quantiles.loc[0.5]),
                    "q3": float(quantiles.loc[0.75]),
                    "maximum": float(ordinary_values.max()),
                },
                "rows_used": int(len(ordinary_values)),
                "rows_excluded": int(len(full_series) - len(ordinary_values)),
                "exclusion_reasons": [
                    "true_null",
                    "bureau_special_value",
                    "parse_failure",
                    "non_finite",
                ],
            }
    outlier = {
        "analysis_scope": "full_governed_population",
        "calculation_method": "1.5_iqr_over_ordinary_valid_numeric_values_only",
        "count": full_counts["ordinary_numeric_outlier"],
        "rate": full_counts["ordinary_numeric_outlier"] / max(full_counts["ordinary_valid_value"], 1),
        "denominator": full_counts["ordinary_valid_value"],
        "lower_cutoff": full_classification["outlier_lower"],
        "upper_cutoff": full_classification["outlier_upper"],
        "excludes_true_nulls": True,
        "excludes_bureau_special_values": True,
        "excludes_parse_failures": True,
    }
    artifact_base = {
        "feature": feature,
        "is_numeric": development_classification["is_numeric"],
        "target_problem_type": problem_type,
        "analysis_scope": "development_population",
        "population_identity": population_identity,
        "iv": iv_woe["iv"],
        "iv_artifact_id": iv_woe["artifact_id"],
        "monotonicity_artifact_id": monotonicity["artifact_id"],
        "special_value_policy": "named_groups_outside_ordinary_numeric_analysis",
        "correlation_with_target": (
            _finite(
                pd.DataFrame(
                    {
                        "x": development_classification["numeric"].where(
                            development_classification["masks"][
                                "ordinary_valid_value"
                            ]
                        ),
                        "y": pd.to_numeric(target, errors="coerce"),
                    }
                )
                .dropna()
                .corr()
                .iloc[0, 1]
            )
            if problem_type == "regression"
            and development_classification["is_numeric"]
            else None
        ),
        "value_classification": {
            "development_counts": development_classification["counts"],
            "full_population_counts": full_counts,
            "base_mutually_exclusive_classes": [
                "true_null",
                "bureau_special_value",
                "ordinary_valid_value",
                "parse_failure",
            ],
            "derived_subsets": {
                "ordinary_numeric_outlier": {
                    "parent_class": "ordinary_valid_value",
                    "semantics": "derived_subset_not_an_additional_base_class",
                }
            },
        },
    }
    artifact_hash = _stable_hash(artifact_base)
    result = {
        **artifact_base,
        "artifact_version": PREDICTOR_ARTIFACT_VERSION,
        "artifact_id": f"eda-predictor-{artifact_hash[:20]}",
        "artifact_hash": artifact_hash,
        "iv_woe": iv_woe,
        "monotonicity": monotonicity,
        "special_values": {
            "analysis_scope": "development_population",
            "policy": "separate_named_groups",
            # Decision-facing group behavior is development-only.  The full
            # structural inventory is preserved separately and deliberately
            # carries no target behavior.
            "groups": development_classification["special_groups"],
            "development_groups": development_classification["special_groups"],
            "ordinary_valid_event_count": development_classification[
                "ordinary_event_count"
            ],
            "ordinary_valid_event_rate": development_classification[
                "ordinary_event_rate"
            ],
            "full_population_groups": [
                {
                    "code": group["code"],
                    "definition": group["definition"],
                    "rows": group["rows"],
                    "population_share": group["population_share"],
                }
                for group in full_classification["special_groups"]
            ],
            "identified_by": full_classification["special_identification_basis"],
            "values_are_true_nulls": False,
            "values_are_ordinary_outliers": False,
            "values_enter_ordinary_quantiles": False,
        },
        "ordinary_outlier": outlier,
        "ordinary_distribution": ordinary_distribution,
    }
    for governed_artifact, method in (
        (result, "governed_predictor_summary"),
        (result["iv_woe"], "governed_iv_woe"),
        (result["monotonicity"], "governed_monotonicity"),
    ):
        governed_artifact["governed_lineage"] = {
            **governed_lineage_base,
            "artifact_id": governed_artifact["artifact_id"],
            "artifact_version": governed_artifact["artifact_version"],
            "artifact_hash": governed_artifact["artifact_hash"],
            "calculation_method": method,
        }
    return result


def _vif(work: pd.DataFrame) -> list[dict[str, Any]]:
    if work.shape[1] < 2 or len(work) < 5:
        return []
    standardized = (work - work.mean()) / work.std(ddof=0).replace(0, 1)
    rows: list[dict[str, Any]] = []
    for feature in standardized.columns:
        response = standardized[feature].to_numpy(dtype=float)
        design = standardized.drop(columns=[feature]).to_numpy(dtype=float)
        design = np.column_stack([np.ones(len(design)), design])
        try:
            fitted = design @ np.linalg.lstsq(design, response, rcond=None)[0]
            denominator = float(((response - response.mean()) ** 2).sum())
            r_squared = 1 - float(((response - fitted) ** 2).sum()) / denominator if denominator else 1.0
            value = 1 / max(1 - r_squared, 1e-9)
        except np.linalg.LinAlgError:
            value = float("inf")
        rows.append(
            {
                "feature": str(feature),
                "vif": _finite(value),
                "is_infinite": not math.isfinite(value),
                "status": "high" if value >= 10 else "review" if value >= 5 else "acceptable",
            }
        )
    return sorted(rows, key=lambda row: (bool(row["is_infinite"]), float(row["vif"] or 0)), reverse=True)


def _relationship_artifact(
    development: pd.DataFrame,
    predictor_artifacts: dict[str, dict[str, Any]],
    *,
    population_identity: str,
    meta: dict[str, Any],
    governed_lineage_base: dict[str, Any],
) -> dict[str, Any]:
    numeric: dict[str, pd.Series] = {}
    for feature in predictor_artifacts:
        if feature not in development.columns:
            continue
        series = development[feature]
        classification = classify_feature_values(feature, series, meta=meta)
        if not classification["is_numeric"]:
            continue
        numeric[feature] = classification["numeric"].where(
            classification["masks"]["ordinary_valid_value"]
        )
    frame = pd.DataFrame(numeric).replace([np.inf, -np.inf], np.nan)
    variances = (
        frame.var(skipna=True).replace(0, np.nan).dropna().sort_values(ascending=False)
        if not frame.empty
        else pd.Series(dtype=float)
    )
    frame = frame.loc[:, [str(column) for column in variances.index]]
    pearson = frame.corr(method="pearson") if frame.shape[1] >= 2 else pd.DataFrame()
    spearman = frame.corr(method="spearman") if frame.shape[1] >= 2 else pd.DataFrame()
    columns = [str(column) for column in pearson.columns]
    pair_counts = [
        [int((frame[left].notna() & frame[right].notna()).sum()) for right in columns]
        for left in columns
    ]
    pairwise_counts = [
        pair_counts[left][right]
        for left in range(len(columns))
        for right in range(left + 1, len(columns))
    ]
    if not pairwise_counts:
        pairwise_counts = [value for row in pair_counts for value in row]
    rows_used_min = min(pairwise_counts, default=0)
    rows_used_max = max(pairwise_counts, default=0)
    complete = frame.dropna()
    vif_rows = _vif(complete)
    vif_by_feature = {row["feature"]: row for row in vif_rows}
    base = {
        "analysis_scope": "development_population",
        "analysis_population_id": population_identity,
        "population_rows": int(len(development)),
        "special_value_representation": "excluded_from_ordinary_numeric_matrix",
        "missing_value_treatment": {
            "correlation": "pairwise_complete",
            "vif": "complete_case",
        },
        "correlation": {
            "columns": columns,
            "pearson_matrix": [[_finite(value) for value in row] for row in pearson.to_numpy()] if not pearson.empty else [],
            "spearman_matrix": [[_finite(value) for value in row] for row in spearman.to_numpy()] if not spearman.empty else [],
            "pairwise_row_counts": pair_counts,
            "method_default": "pearson",
            "methods_supported": ["pearson", "spearman"],
            "complete_case_policy": "pairwise_complete",
            "rows_used": rows_used_min,
            "rows_used_min": rows_used_min,
            "rows_used_max": rows_used_max,
            "rows_excluded": int(len(development) - rows_used_min),
            "rows_excluded_min": int(len(development) - rows_used_max),
            "rows_excluded_max": int(len(development) - rows_used_min),
            "scalar_compatibility_semantics": "conservative_minimum_pairwise_rows_and_maximum_pairwise_exclusions",
            "exclusion_reasons": ["true_null", "bureau_special_value", "parse_failure", "non_finite"],
        },
        "vif": vif_rows,
        "vif_by_feature": vif_by_feature,
        "vif_scope": {
            "analysis_population": "development_population",
            "population_rows": int(len(development)),
            "rows_used": int(len(complete)),
            "rows_excluded": int(len(development) - len(complete)),
            "exclusion_reasons": ["incomplete_case_after_special_value_exclusion"],
            "special_value_representation": "excluded_from_ordinary_numeric_matrix",
            "missing_value_treatment": "complete_case",
            "calculation_method": "ordinary_numeric_complete_case_ols_r_squared",
            "predictors_used": [str(column) for column in complete.columns],
        },
    }
    artifact_hash = _stable_hash(base)
    result = {
        **base,
        "artifact_version": RELATIONSHIP_ARTIFACT_VERSION,
        "artifact_id": f"eda-relationships-{artifact_hash[:20]}",
        "artifact_hash": artifact_hash,
    }
    result["governed_lineage"] = {
        **governed_lineage_base,
        "artifact_id": result["artifact_id"],
        "artifact_version": result["artifact_version"],
        "artifact_hash": result["artifact_hash"],
        "calculation_method": "governed_development_correlation_and_vif",
    }
    return result


def resolve_development_partition(
    *,
    store: Any,
    identity: dict[str, str],
    target: str,
    authorized_predictors: Iterable[str],
    predictor_manifest_id: str,
    expected_analysis_partition_id: str | None = None,
    expected_analysis_partition_revision: int | None = None,
) -> tuple[pd.DataFrame, pd.Series, dict[str, Any]]:
    """Resolve the durable development membership only.

    This boundary materializes only development membership and never calls a
    combined development/final-holdout accessor. The final Feature Engineering
    manifest is not an input: EDA is authorized by the Data Acquisition
    predictor manifest and the immutable pre-EDA Analysis Partition.
    """

    if not str(predictor_manifest_id or "").strip():
        raise EDAAnalyticalContractError(
            "Data Acquisition predictor authorization is required before target-directed EDA.",
            code="predictor_authorization_required",
            recovery=(
                "Return to Data Acquisition, confirm the target and predictor "
                "selection, then reserve the Analysis Partition."
            ),
            stale_artifacts=["predictor_eda", "relationship_eda"],
        )
    predictors = [
        str(feature).strip()
        for feature in authorized_predictors
        if str(feature).strip()
    ]
    if not predictors:
        raise EDAAnalyticalContractError(
            "The durable Data Acquisition authorization contains no model-eligible predictors.",
            code="predictor_authorization_required",
            recovery=(
                "Return to Data Acquisition and explicitly authorize at least "
                "one eligible predictor before running target-directed EDA."
            ),
            stale_artifacts=["predictor_eda", "relationship_eda"],
        )
    try:
        from ..analysis_partition.types import AnalysisPartitionError
        from ..analysis_partition.service import analysis_partition_service

        partition = analysis_partition_service.current(
            str(identity.get("project_id") or ""),
            str(identity.get("dataset_id") or ""),
            str(identity.get("dataset_version_id") or ""),
            target=target,
            target_contract_id=str(store.meta.get("target_contract_id") or "")
            or None,
            predictor_authorization_id=str(predictor_manifest_id or "")
            or None,
            require_documentation_ready=True,
        )
        expected_partition_id = str(
            expected_analysis_partition_id or ""
        ).strip()
        if (
            expected_partition_id
            and str(partition.get("analysis_partition_id") or "").strip()
            != expected_partition_id
        ) or (
            expected_analysis_partition_revision is not None
            and int(partition.get("revision") or 0)
            != int(expected_analysis_partition_revision)
        ):
            raise EDAAnalyticalContractError(
                "The current Analysis Partition changed before development materialization.",
                code="analysis_partition_stale",
                recovery=(
                    "Reload Data Acquisition and retry with the current "
                    "Analysis Partition ID and revision."
                ),
                stale_artifacts=[
                    "target_eda",
                    "predictor_eda",
                    "relationship_eda",
                ],
            )
        target_authority = resolve_partition_target_authority(
            partition,
            target=target,
        )
        development_features, development_target = (
            analysis_partition_service.materialize_development(
                store,
                partition,
                authorized_predictors=predictors,
            )
        )
    except ImportError as exc:
        raise EDAAnalyticalContractError(
            "Analysis partition authority is unavailable.",
            code="analysis_partition_required",
        ) from exc
    except AnalysisPartitionError as exc:
        raise EDAAnalyticalContractError(
            str(exc),
            code=exc.code,
            recovery=exc.recovery,
            stale_artifacts=exc.stale_artifacts,
        ) from exc

    expected_rows = int(partition.get("development_count") or 0)
    if (
        not isinstance(development_features, pd.DataFrame)
        or not isinstance(development_target, pd.Series)
        or development_features.empty
        or len(development_features) != len(development_target)
    ):
        raise EDAAnalyticalContractError(
            "The materialized development partition is missing or failed integrity validation.",
            code="analysis_partition_stale",
        )
    if expected_rows and len(development_features) != expected_rows:
        raise EDAAnalyticalContractError(
            "The materialized development row count does not match its durable Analysis Partition.",
            code="analysis_partition_stale",
        )
    if not development_features.index.equals(development_target.index):
        raise EDAAnalyticalContractError("Development predictors and target are not index-aligned.")
    missing = [feature for feature in predictors if feature not in development_features.columns]
    if missing:
        raise EDAAnalyticalContractError(
            "The development partition is missing authorized predictors: " + ", ".join(missing[:5])
        )
    split_id = str(partition.get("analysis_partition_id") or "")
    population_id = str(
        partition.get("development_partition_id")
        or f"development:{split_id}"
    )
    scope = {
        "split_id": split_id,
        "analysis_partition_id": split_id,
        "analysis_partition_revision": int(partition.get("revision") or 0),
        "analysis_partition_status": str(partition.get("status") or ""),
        "analysis_partition_artifact_hash": str(
            partition.get("artifact_hash") or ""
        ),
        "analysis_partition_assignment_hash": str(
            partition.get("assignment_hash") or ""
        ),
        "partition_predictor_authorization_id": str(
            partition.get("predictor_authorization_id") or ""
        ),
        "current_predictor_authorization_id": str(
            partition.get("current_predictor_authorization_id")
            or predictor_manifest_id
            or ""
        ),
        "predictor_authorization_lineage_status": str(
            partition.get("predictor_authorization_lineage_status")
            or "current"
        ),
        "target_contract_id": target_authority["target_contract_id"],
        "target": target_authority["target"],
        "problem_type": target_authority["problem_type"],
        "positive_value": target_authority["positive_value"],
        "negative_value": target_authority["negative_value"],
        "target_authority_source": target_authority["source"],
        "target_authority_compatibility_status": target_authority[
            "compatibility_status"
        ],
        "analysis_population_id": population_id,
        "analysis_scope": "development_population",
        "population_rows": expected_rows,
        "rows_used": expected_rows,
        "rows_excluded": int(partition.get("holdout_count") or 0),
        "exclusion_reasons": ["sealed_final_holdout_excluded"],
        "final_holdout_partition_id": str(
            partition.get("sealed_holdout_partition_id") or ""
        ),
        "final_holdout_status": str(
            partition.get("holdout_status") or "sealed"
        ),
        "holdout_isolation_status": str(
            partition.get("holdout_isolation_status") or "verified"
        ),
        "final_holdout_accessed": False,
        "final_holdout_used_for_selection": False,
    }
    # Partition membership is positional and the durable contract carries its
    # identity. Do not propagate arbitrary source labels into downstream EDA:
    # duplicate labels make pandas align by label in later joins/assignments
    # and can multiply rows shared by development and sealed holdout. A dense
    # positional index keeps every subsequent operation inside the materialized
    # development population.
    safe_features = (
        development_features.loc[:, predictors]
        .copy(deep=True)
        .reset_index(drop=True)
    )
    safe_target = development_target.copy(deep=True).reset_index(drop=True)
    safe_target.name = target
    return safe_features, safe_target, scope


def build_governed_eda_contract(
    *,
    project_id: str,
    full_frame: pd.DataFrame,
    target: str,
    event_value: Any,
    authorization: dict[str, Any],
    store: Any,
    created_by: str = "atlas_backend",
    requested_bins: int = DEFAULT_REQUESTED_BINS,
    expected_analysis_partition_id: str | None = None,
    expected_analysis_partition_revision: int | None = None,
) -> dict[str, Any]:
    """Build one shared analytical artifact for all governed EDA workspaces."""

    identity = {
        "project_id": str(project_id),
        "dataset_id": str(store.meta.get("dataset_id") or ""),
        "dataset_version_id": str(store.meta.get("dataset_version_id") or ""),
    }
    if not all(identity.values()):
        raise EDAAnalyticalContractError(
            "A complete canonical dataset identity is required for governed EDA.",
            code="dataset_identity_unavailable",
            recovery="Return to Data Acquisition and activate the exact registered Dataset Library version.",
        )
    activation_revision = int(store.meta.get("activation_revision") or 0)
    predictor_authorization_id = str(
        authorization.get("predictor_authorization_id")
        or authorization.get("manifest_version")
        or ""
    )
    predictor_manifest_id = str(
        authorization.get("manifest_version")
        or predictor_authorization_id
        or ""
    )
    if str(authorization.get("source") or "") != (
        "data_acquisition_predictor_authorization"
    ):
        raise EDAAnalyticalContractError(
            "The durable Data Acquisition predictor authorization is required before target-directed EDA.",
            code="predictor_authorization_required",
            recovery=(
                "Return to Data Acquisition and save the governed target and "
                "predictor selection before confirming the Analysis Partition."
            ),
            stale_artifacts=["predictor_eda", "relationship_eda"],
        )
    predictors = [str(feature) for feature in authorization.get("authorized_predictors") or []]
    development, development_target, scope = resolve_development_partition(
        store=store,
        identity=identity,
        target=target,
        authorized_predictors=predictors,
        predictor_manifest_id=predictor_manifest_id,
        expected_analysis_partition_id=expected_analysis_partition_id,
        expected_analysis_partition_revision=(
            expected_analysis_partition_revision
        ),
    )
    problem_type = str(scope["problem_type"])
    positive_value = _json_scalar(scope.get("positive_value"))
    negative_value = _json_scalar(scope.get("negative_value"))
    target_contract_id = str(scope.get("target_contract_id") or "")
    special_value_review_id = str(
        store.meta.get("special_value_review_id") or ""
    )
    special_value_review_revision = int(
        store.meta.get("special_value_review_revision") or 0
    )
    if event_value is not None and (
        problem_type != "classification"
        or not _same_target_scalar(event_value, positive_value)
    ):
        raise EDAAnalyticalContractError(
            "The requested event value contradicts the documented Analysis Partition target authority.",
            code="target_contract_stale",
            stale_artifacts=["target_eda", "predictor_eda", "relationship_eda"],
        )
    policy_payload = {
        "bureau_registry": sorted((str(key), value) for key, value in BUREAU_SPECIAL_VALUES.items()),
        "classes": ["true_null", "bureau_special_value", "ordinary_valid_value", "ordinary_numeric_outlier", "parse_failure"],
    }
    special_value_policy_id = f"eda-special-policy-{_stable_hash(policy_payload)[:20]}"
    calculation_method = {
        "target_directed": "development_partition_only",
        "iv_woe": (
            "quantile_actual_value_boundaries_additive_smoothing"
            if problem_type == "classification"
            else "not_applicable_for_regression"
        ),
        "monotonicity": (
            "ordinary_valid_event_rate_order"
            if problem_type == "classification"
            else "not_applicable_for_regression"
        ),
        "correlation": ["pearson", "spearman"],
        "vif": "complete_case_ols_r_squared",
    }
    created_at = _now()
    governed_lineage_base = {
        "backend_authoritative": True,
        **identity,
        "activation_revision": activation_revision,
        "target": target,
        "target_contract_id": target_contract_id,
        "problem_type": problem_type,
        "positive_value": positive_value,
        "negative_value": negative_value,
        "predictor_authorization_id": predictor_authorization_id,
        "predictor_manifest_id": predictor_manifest_id,
        "split_id": scope["split_id"],
        "analysis_partition_id": scope["analysis_partition_id"],
        "analysis_partition_revision": scope["analysis_partition_revision"],
        "analysis_partition_artifact_hash": scope[
            "analysis_partition_artifact_hash"
        ],
        "analysis_partition_assignment_hash": scope[
            "analysis_partition_assignment_hash"
        ],
        "special_value_review_id": special_value_review_id,
        "special_value_review_revision": special_value_review_revision,
        "development_partition_id": scope["analysis_population_id"],
        "sealed_holdout_partition_id": scope["final_holdout_partition_id"],
        "analysis_scope": "development_population",
        "analysis_population_id": scope["analysis_population_id"],
        "population_rows": int(len(full_frame)),
        "rows_used": int(scope["rows_used"]),
        "rows_excluded": int(scope["rows_excluded"]),
        "exclusion_reasons": list(scope["exclusion_reasons"]),
        "special_value_policy_id": special_value_policy_id,
        "missing_value_policy": "true_null_and_parse_failure_separate",
        "binning_specification": {
            "requested_bins": requested_bins,
            "method": "quantile_actual_value_boundaries",
            "empty_interval_policy": "suppressed",
        },
        "created_by": created_by,
        "created_at": created_at,
        "final_holdout_accessed": False,
        "final_holdout_used_for_selection": False,
    }
    target_artifact = _target_artifact(
        target_name=target,
        target=development_target,
        problem_type=problem_type,
        positive_value=positive_value,
        negative_value=negative_value,
        population_identity=scope["analysis_population_id"],
        governed_lineage_base=governed_lineage_base,
    )
    predictor_artifacts = {
        feature: _predictor_artifact(
            feature=feature,
            development_series=development[feature],
            full_series=full_frame[feature],
            target=development_target,
            event_value=positive_value,
            negative_value=negative_value,
            meta=store.meta,
            population_identity=scope["analysis_population_id"],
            requested_bins=requested_bins,
            governed_lineage_base=governed_lineage_base,
            problem_type=problem_type,
        )
        for feature in predictors
        if feature in full_frame.columns
    }
    relationship = _relationship_artifact(
        development,
        predictor_artifacts,
        population_identity=scope["analysis_population_id"],
        meta=store.meta,
        governed_lineage_base=governed_lineage_base,
    )
    stable = {
        **identity,
        "activation_revision": activation_revision,
        "target": target,
        "target_contract_id": target_contract_id,
        "problem_type": problem_type,
        "positive_value": positive_value,
        "negative_value": negative_value,
        "predictor_authorization_id": predictor_authorization_id,
        "predictor_manifest_id": predictor_manifest_id,
        "split_id": scope["split_id"],
        "analysis_partition_id": scope["analysis_partition_id"],
        "analysis_partition_revision": scope["analysis_partition_revision"],
        "analysis_partition_artifact_hash": scope[
            "analysis_partition_artifact_hash"
        ],
        "analysis_partition_assignment_hash": scope[
            "analysis_partition_assignment_hash"
        ],
        "special_value_review_id": special_value_review_id,
        "special_value_review_revision": special_value_review_revision,
        "development_hash": _frame_hash(development, development_target),
        "special_value_policy_id": special_value_policy_id,
        "missing_value_policy": "true_null_and_parse_failure_separate",
        "calculation_method": calculation_method,
        "target_artifact_id": target_artifact["artifact_id"],
        "predictor_artifact_ids": {key: value["artifact_id"] for key, value in predictor_artifacts.items()},
        "relationship_artifact_id": relationship["artifact_id"],
    }
    artifact_hash = _stable_hash(stable)
    return {
        "contract_version": CONTRACT_VERSION,
        "artifact_id": f"eda-contract-{artifact_hash[:20]}",
        "artifact_version": CONTRACT_VERSION,
        "artifact_hash": artifact_hash,
        "backend_authoritative": True,
        **identity,
        "activation_revision": activation_revision,
        "target": target,
        "target_contract_id": target_contract_id,
        "problem_type": problem_type,
        "positive_value": positive_value,
        "negative_value": negative_value,
        "predictor_authorization_id": predictor_authorization_id,
        "predictor_manifest_id": predictor_manifest_id,
        "split_id": scope["split_id"],
        "analysis_partition_id": scope["analysis_partition_id"],
        "analysis_partition_revision": scope["analysis_partition_revision"],
        "analysis_partition_artifact_hash": scope[
            "analysis_partition_artifact_hash"
        ],
        "analysis_partition_assignment_hash": scope[
            "analysis_partition_assignment_hash"
        ],
        "special_value_review_id": special_value_review_id,
        "special_value_review_revision": special_value_review_revision,
        "development_partition_id": scope["analysis_population_id"],
        "sealed_holdout_partition_id": scope["final_holdout_partition_id"],
        "analysis_scope": "development_population",
        "analysis_population_id": scope["analysis_population_id"],
        "population_rows": int(len(full_frame)),
        "rows_used": int(scope["rows_used"]),
        "rows_excluded": int(scope["rows_excluded"]),
        "exclusion_reasons": scope["exclusion_reasons"],
        "supported_scopes": SUPPORTED_SCOPES,
        "special_value_policy_id": special_value_policy_id,
        "missing_value_policy": "true_null_and_parse_failure_separate",
        "binning_specification": {
            "requested_bins": requested_bins,
            "method": "quantile_actual_value_boundaries",
            "empty_interval_policy": "suppressed",
        },
        "calculation_method": calculation_method,
        "created_by": created_by,
        "created_at": created_at,
        "development_scope": scope,
        "final_holdout_accessed": False,
        "final_holdout_used_for_selection": False,
        "target_artifact": target_artifact,
        "predictor_artifacts": predictor_artifacts,
        "relationship_artifact": relationship,
    }

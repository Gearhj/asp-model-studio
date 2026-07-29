from __future__ import annotations

import re
from typing import Any, Iterable

import pandas as pd

from ..core.dataset_store import DATASTORE


BUREAU_SPECIAL_VALUES = (-9.0, -8.0, -7.0)
_SPLIT_FIELD = re.compile(
    r"(^|_)(split|fold|partition|sample_role|dataset_role)($|_)",
    re.IGNORECASE,
)
_SYSTEM_FIELD = re.compile(
    r"(^|_)(row_id|record_id|load_id|batch_id|ingestion_id)($|_)",
    re.IGNORECASE,
)


def _string_set(values: Any) -> set[str]:
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {str(value).strip() for value in values if str(value).strip()}


def explicit_predictor_exclusions() -> set[str]:
    """Return predictor exclusions already established by upstream governance."""

    exclusions: set[str] = set()
    for key in (
        "target_source_excluded",
        "target_source_exclusions",
        "prohibited_columns",
        "system_columns",
        "split_columns",
    ):
        exclusions.update(_string_set(DATASTORE.meta.get(key)))

    authorization = DATASTORE.meta.get("predictor_authorization")
    if isinstance(authorization, dict):
        exclusions.update(_string_set(authorization.get("target_source_excluded")))
        exclusions.update(_string_set(authorization.get("excluded_predictors")))
    return exclusions


def detect_deterministic_target_sources(
    frame: pd.DataFrame,
    target: str | None,
    candidates: Iterable[str] | None = None,
) -> set[str]:
    """Detect low-cardinality columns that deterministically reveal the target.

    This is the pandas-side equivalent of the governed EDA authorization check.
    It deliberately relies on the observed mapping rather than a dataset-specific
    column name.  A candidate is excluded when every populated source value maps
    to exactly one populated target value.
    """

    if not target or target not in frame.columns:
        return set()
    target_values = frame[target]
    if int(target_values.dropna().nunique()) < 2:
        return set()

    names = list(candidates) if candidates is not None else [str(column) for column in frame.columns]
    found: set[str] = set()
    for name in names:
        if name == target or name not in frame.columns:
            continue
        source = frame[name]
        distinct = int(source.dropna().nunique())
        if distinct < 2 or distinct > 50:
            continue
        paired = pd.DataFrame({"source": source, "target": target_values}).dropna()
        if paired.empty or len(paired) / max(len(frame), 1) < 0.8:
            continue
        mapping_width = paired.groupby("source", dropna=True)["target"].nunique(dropna=True)
        if not mapping_width.empty and int(mapping_width.max()) == 1:
            found.add(name)
    return found


def governed_predictor_authorization(
    frame: pd.DataFrame,
    target: str | None = None,
    selected_columns: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Resolve the one authoritative predictor set used by preparation stages."""

    resolved_target = str(target or DATASTORE.target or "") or None
    selected = [
        str(name)
        for name in (
            list(selected_columns)
            if selected_columns is not None
            else DATASTORE.get_selected_columns()
        )
        if str(name) in frame.columns and str(name) != resolved_target
    ]
    selected_set = set(selected)
    candidate_names = selected or [
        str(column)
        for column in frame.columns
        if str(column) != resolved_target
    ]

    explicit = explicit_predictor_exclusions()
    deterministic = detect_deterministic_target_sources(
        frame,
        resolved_target,
        [
            str(column)
            for column in frame.columns
            if str(column) != resolved_target
        ],
    )
    excluded: dict[str, str] = {}
    # Record authoritative safety exclusions for the complete source schema,
    # not only the currently selected subset. Feature Engineering rewrites the
    # downstream selected-column list to include engineered outputs; an
    # unselected deterministic target source must retain its specific exclusion
    # reason instead of being downgraded to the generic "not selected" reason.
    for column in frame.columns:
        name = str(column)
        if name == resolved_target:
            continue
        if name in deterministic:
            excluded[name] = "Deterministic source of the modeling target"
        elif name in explicit:
            excluded[name] = "Excluded by the governed predictor authorization contract"
        elif _SPLIT_FIELD.search(name):
            excluded[name] = "Split or fold metadata cannot be used as a predictor"
        elif _SYSTEM_FIELD.search(name):
            excluded[name] = "System metadata cannot be used as a predictor"

    # When an upstream selection exists, every unselected source column remains
    # visible to authorization reporting but cannot silently re-enter a builder.
    if selected:
        for column in frame.columns:
            name = str(column)
            if name == resolved_target or name in selected_set or name in excluded:
                continue
            excluded[name] = "Not selected in the governed predictor manifest"

    authorized = [name for name in candidate_names if name not in excluded]
    return {
        "target": resolved_target,
        "authorized_predictors": authorized,
        "excluded_predictors": excluded,
        "target_source_excluded": sorted(deterministic | (explicit & set(frame.columns))),
        "selected_predictors": selected,
    }


def bureau_special_mask(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.isin(BUREAU_SPECIAL_VALUES)


def bureau_special_summary(values: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(values, errors="coerce")
    mask = bureau_special_mask(numeric)
    counts = {
        str(int(special)): int((numeric == special).sum())
        for special in BUREAU_SPECIAL_VALUES
        if int((numeric == special).sum()) > 0
    }
    count = int(mask.sum())
    return {
        "special_value_count": count,
        "special_value_rate": count / max(int(numeric.notna().sum()), 1),
        "special_values": counts,
    }

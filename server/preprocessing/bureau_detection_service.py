from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

import numpy as np
import pandas as pd

from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from .bureau_detection_types import BureauDetectionRequest
from .bureau_registry import BUREAU_SPECIAL_VALUES, name_signals


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _aligned_target_subset(mask: pd.Series, target: pd.Series) -> pd.Series:
    """Select target rows by position so duplicate index labels stay harmless."""

    if len(mask) != len(target):
        raise ValueError(
            "Development predictor and target rows are not positionally aligned."
        )
    positions = np.flatnonzero(mask.to_numpy(dtype=bool, copy=False))
    return target.iloc[positions]


def _event_rate(mask: pd.Series, target: pd.Series, event_value: Any) -> float | None:
    valid = _aligned_target_subset(mask, target).dropna()
    if valid.empty or event_value is None:
        return None
    return float((valid.astype(str) == str(event_value)).mean())


def _event_count(mask: pd.Series, target: pd.Series, event_value: Any) -> int | None:
    valid = _aligned_target_subset(mask, target).dropna()
    if valid.empty or event_value is None:
        return None
    return int((valid.astype(str) == str(event_value)).sum())


def _resolve_event(target: pd.Series | None, governed: Any) -> Any:
    def native_scalar(value: Any) -> Any:
        item = getattr(value, "item", None)
        if callable(item):
            try:
                value = item()
            except (TypeError, ValueError):
                pass
        return json_safe(value)

    if target is None or governed in (None, ""):
        raise ValueError(
            "The exact governed event value is required for bureau detection."
        )
    unique = list(pd.unique(target.dropna()))
    for value in unique:
        if str(value) == str(governed):
            return native_scalar(value)
    raise ValueError(
        "The governed event value is absent from the development population."
    )


def _metadata_special_values(text: str | None) -> dict[float, str]:
    output = {float(value): label for value, label in BUREAU_SPECIAL_VALUES.items()}
    if not text:
        return output
    for part in re.split(r"[;|]", text):
        match = re.search(r"-?\d+(?:\.\d+)?", part)
        if not match:
            continue
        value = float(match.group(0))
        label = part.replace(match.group(0), "").lstrip(" :=-").strip() or "Metadata-defined special value"
        output[value] = label
    return output


def detect_bureau_data(
    request: BureauDetectionRequest,
    *,
    authorized_predictors: list[str] | None = None,
    target_analysis_features: pd.DataFrame | None = None,
    target_analysis_target: pd.Series | None = None,
    target_analysis_scope: str = "",
    analysis_partition_id: str | None = None,
    analysis_partition_revision: int | None = None,
    development_partition_id: str | None = None,
    governed_event_value: Any = None,
    analysis_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Bureau structure belongs to the immutable activated Dataset Library
    # version. A downstream processed_df must never silently replace it.
    df = DATASTORE.get_raw_active_df(include_target=False)
    if df is None or df.empty:
        raise ValueError("No full backend dataset is loaded.")
    raw_df = DATASTORE.raw_df
    target_name = request.target if request.target in raw_df.columns else None
    if authorized_predictors is not None:
        predictors = list(dict.fromkeys(str(value).strip() for value in authorized_predictors if str(value).strip()))
        missing = [column for column in predictors if column not in raw_df.columns]
        if missing:
            raise ValueError("Authorized predictors are absent from the exact active dataset artifact.")
        df = raw_df.loc[:, list(predictors)].copy()
    else:
        raise ValueError(
            "Exact durable predictor authorization is required for bureau detection."
        )

    if target_analysis_target is None or target_analysis_features is None:
        raise ValueError(
            "The exact development population is required for target-aware bureau detection."
        )
    if target_analysis_scope != "development_population":
        raise ValueError(
            "Bureau target analysis is not bound to the development population."
        )
    event_value = _resolve_event(
        target_analysis_target,
        governed_event_value,
    )
    metadata = {row.variableName.lower(): row for row in request.metadata}
    variable_results: list[dict[str, Any]] = []
    special_row_mask = pd.Series(False, index=df.index)

    for column in df.columns:
        if column == target_name:
            continue
        series = df[column]
        numeric = pd.to_numeric(series, errors="coerce")
        metadata_row = metadata.get(str(column).lower())
        signals = name_signals(str(column))
        score = 0.0
        if signals:
            score += 0.5 if "configured bureau attribute prefix" in " ".join(signals) else 0.35
        if metadata_row:
            score += 0.65
            signals.append("Uploaded metadata identifies the variable as a bureau attribute.")
        definitions = _metadata_special_values(metadata_row.specialValueDefinitions if metadata_row else None)
        special_mask = numeric.isin(list(definitions))
        special_count = int(special_mask.sum())
        special_rate = special_count / max(len(series), 1)
        ordinary_mask = numeric.notna() & ~special_mask
        null_count = int(series.isna().sum())
        parse_failure_count = int((series.notna() & numeric.isna()).sum())
        distinct_special = sorted(float(value) for value in numeric[special_mask].dropna().unique())
        if special_count:
            if signals:
                score += min(0.25, 0.08 + special_rate)
                signals.append(f"{special_count:,} rows contain configured bureau special values.")
            elif len(distinct_special) >= 2 and special_rate >= 0.05:
                score += 0.2
                signals.append("Multiple special values are concentrated in the distribution, but no bureau name or metadata signal is present.")
        profile_rows: list[dict[str, Any]] = []
        analysis_numeric = (
            pd.to_numeric(target_analysis_features[column], errors="coerce")
            if target_analysis_target is not None
            and target_analysis_features is not None
            and column in target_analysis_features.columns
            else None
        )
        analysis_special_mask = (
            analysis_numeric.isin(list(definitions))
            if analysis_numeric is not None
            else None
        )
        analysis_regular_mask = (
            analysis_numeric.notna() & ~analysis_special_mask
            if analysis_numeric is not None and analysis_special_mask is not None
            else None
        )
        regular_event_rate = (
            _event_rate(
                analysis_regular_mask,
                target_analysis_target,
                event_value,
            )
            if analysis_numeric is not None
            and analysis_regular_mask is not None
            and target_analysis_target is not None
            else None
        )
        for value in distinct_special:
            mask = numeric == value
            count = int(mask.sum())
            analysis_mask = analysis_numeric == value if analysis_numeric is not None else None
            special_event_rate = (
                _event_rate(
                    analysis_mask,
                    target_analysis_target,
                    event_value,
                )
                if analysis_numeric is not None
                and analysis_mask is not None
                and target_analysis_target is not None
                else None
            )
            special_event_count = (
                _event_count(
                    analysis_mask,
                    target_analysis_target,
                    event_value,
                )
                if analysis_numeric is not None
                and analysis_mask is not None
                and target_analysis_target is not None
                else None
            )
            rate_difference = (
                special_event_rate - regular_event_rate
                if special_event_rate is not None
                and regular_event_rate is not None
                else None
            )
            if (
                rate_difference is not None
                and abs(rate_difference) >= 0.05
                and (signals or metadata_row)
            ):
                score += 0.05
            profile_rows.append({
                "value": int(value) if value.is_integer() else value,
                "definition": definitions.get(value, "Configured special value"),
                "count": count,
                "frequency": count / max(len(series), 1),
                "event_count": special_event_count,
                "event_rate": special_event_rate,
                "regular_event_rate": regular_event_rate,
                "event_rate_delta": rate_difference,
                "recommended_handling": "Preserve as informative special value" if rate_difference is not None and abs(rate_difference) >= 0.02 else "Review domain mapping before treatment",
            })
        score = min(1.0, score)
        if score >= 0.45 or metadata_row:
            likely_bureau = score >= 0.55
            if likely_bureau:
                special_row_mask = special_row_mask | special_mask
            variable_results.append({
                "variable": str(column),
                "confidence": score,
                "reasons": signals,
                "datatype": str(series.dtype),
                "special_value_count": special_count,
                "special_value_frequency": special_rate,
                "ordinary_value_count": int(ordinary_mask.sum()),
                "null_count": null_count,
                "parse_failure_count": parse_failure_count,
                "special_values": profile_rows,
                "metadata": metadata_row.model_dump() if metadata_row else None,
                "likely_bureau": likely_bureau,
            })

    likely = [row for row in variable_results if row["likely_bureau"]]
    confidence = max([row["confidence"] for row in likely], default=0.0)
    reasons = list(dict.fromkeys(reason for row in likely for reason in row["reasons"]))
    if request.manual_declaration == "contains":
        detected = True
        confidence = 1.0
        reasons.insert(0, "The reviewer declared that the dataset contains credit bureau variables.")
    elif request.manual_declaration == "does_not_contain":
        detected = False
        reasons.insert(0, "The reviewer declared that the dataset does not contain credit bureau variables.")
    elif request.manual_declaration == "manual_review":
        detected = bool(likely)
        reasons.insert(0, "The reviewer requested manual bureau-data review.")
    else:
        detected = bool(likely)

    result = {
        "ok": True,
        **dict(analysis_metadata or {}),
        "scope": "development_population",
        "analysis_scope": "development_population",
        "structural_scope": "full_governed_population_predictors_only",
        "target_analysis_scope": target_analysis_scope,
        "analysis_partition_id": analysis_partition_id,
        "analysis_partition_revision": analysis_partition_revision,
        "development_partition_id": development_partition_id,
        "final_holdout_accessed": False,
        "final_holdout_used_for_selection": False,
        "raw_dataset_target_fallback_used": False,
        "row_count": int(len(df)),
        "target": target_name,
        "event_value": event_value,
        "detected": detected,
        "confidence": confidence,
        "manual_declaration": request.manual_declaration,
        "reasons": reasons,
        "likely_variable_count": len(likely),
        "variables_with_special_values": sum(1 for row in likely if row["special_value_count"]),
        "rows_with_special_values": int(special_row_mask.sum()),
        "variables": variable_results,
        "reviewer_rationale": request.reviewer_rationale,
        "treatment_selections": request.treatment_selections,
        "metadata_source": "uploaded" if request.metadata else "none",
        "reviewed_at": _now(),
    }
    # Route handlers still perform a defensive outbound conversion before
    # publishing the review, but the service contract itself must never leak a
    # pandas/numpy scalar to another Python caller or response encoder.
    return json_safe(result)

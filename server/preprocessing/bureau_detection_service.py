from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

import pandas as pd

from ..core.dataset_store import DATASTORE
from .bureau_detection_types import BureauDetectionRequest
from .bureau_registry import BUREAU_SPECIAL_VALUES, name_signals


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_rate(values: pd.Series, target: pd.Series, event_value: Any) -> float | None:
    valid = target.loc[values.index].dropna()
    if valid.empty or event_value is None:
        return None
    return float((valid.astype(str) == str(event_value)).mean())


def _event_count(values: pd.Series, target: pd.Series, event_value: Any) -> int | None:
    valid = target.loc[values.index].dropna()
    if valid.empty or event_value is None:
        return None
    return int((valid.astype(str) == str(event_value)).sum())


def _resolve_event(target: pd.Series | None, requested: Any) -> Any:
    if target is None:
        return None
    unique = list(pd.unique(target.dropna()))
    if requested is not None:
        for value in unique:
            if str(value) == str(requested):
                return value
    for value in unique:
        if str(value).strip().lower() in {"1", "true", "yes", "bad", "fraud", "event"}:
            return value
    if len(unique) == 2:
        return target.value_counts().index[-1]
    return None


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


def detect_bureau_data(request: BureauDetectionRequest) -> dict[str, Any]:
    df = DATASTORE.get_base_df()
    if df is None or df.empty:
        raise ValueError("No full backend dataset is loaded.")
    target_name = request.target if request.target in df.columns else DATASTORE.target if DATASTORE.target in df.columns else None
    target = df[target_name] if target_name else None
    event_value = _resolve_event(target, request.event_value)
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
        regular_mask = ordinary_mask
        regular_event_rate = _event_rate(numeric[regular_mask], target, event_value) if target is not None else None
        for value in distinct_special:
            mask = numeric == value
            count = int(mask.sum())
            special_event_rate = _event_rate(numeric[mask], target, event_value) if target is not None else None
            special_event_count = _event_count(numeric[mask], target, event_value) if target is not None else None
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
        "scope": "full_dataset",
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
    DATASTORE.meta["bureau_review"] = result
    return result

from __future__ import annotations

from functools import lru_cache
from math import erf, exp, sqrt
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException

from ..datasets.dataset_registry import latest_version_id, require_dataset, version_dir


def normalize_column_name(value: str) -> str:
    return ".".join(str(value or "").strip().split())


def _resolve_column(columns: list[str], requested: str, required: bool = True) -> str | None:
    if not requested and not required:
        return None
    exact = {str(column): str(column) for column in columns}
    normalized = {normalize_column_name(column): str(column) for column in columns}
    resolved = exact.get(requested) or normalized.get(normalize_column_name(requested))
    if not resolved and required:
        raise HTTPException(status_code=422, detail=f"Mapped column '{requested}' was not found in the registered dataset version.")
    return resolved


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def _success_mask(series: pd.Series, success_event: str) -> pd.Series:
    expected = str(success_event).strip().lower()
    normalized = series.astype("string").str.strip().str.lower()
    aliases = {expected}
    if expected in {"true", "1", "yes", "y"}:
        aliases.update({"true", "1", "yes", "y"})
    if expected in {"false", "0", "no", "n"}:
        aliases.update({"false", "0", "no", "n"})
    return normalized.isin(aliases).fillna(False)


def _lift_statistics(treatment_count: int, control_count: int, treatment_successes: int, control_successes: int) -> dict[str, Any]:
    treatment_rate = treatment_successes / treatment_count if treatment_count else 0.0
    control_rate = control_successes / control_count if control_count else 0.0
    absolute_lift = treatment_rate - control_rate
    relative_lift = absolute_lift / control_rate if control_rate else 0.0
    total = treatment_count + control_count
    pooled = (treatment_successes + control_successes) / total if total else 0.0
    pooled_se = sqrt(max(0.0, pooled * (1.0 - pooled) * (1.0 / max(1, treatment_count) + 1.0 / max(1, control_count))))
    unpooled_se = sqrt(
        max(0.0, treatment_rate * (1.0 - treatment_rate) / max(1, treatment_count))
        + max(0.0, control_rate * (1.0 - control_rate) / max(1, control_count))
    )
    z_value = absolute_lift / pooled_se if pooled_se else 0.0
    p_value = 2.0 * (1.0 - _normal_cdf(abs(z_value)))
    return {
        "treatmentRate": float(treatment_rate),
        "controlRate": float(control_rate),
        "absoluteLift": float(absolute_lift),
        "relativeLift": float(relative_lift),
        "pValue": float(max(0.0, min(1.0, p_value))),
        "confidenceLow": float(absolute_lift - 1.96 * unpooled_se),
        "confidenceHigh": float(absolute_lift + 1.96 * unpooled_se),
    }


def _segment_rows(
    frame: pd.DataFrame,
    segment_column: str | None,
    treatment_column: str,
    treatment_value: str,
    control_value: str,
    outcome_column: str,
    success_event: str,
) -> list[dict[str, Any]]:
    if not segment_column or segment_column not in frame.columns:
        return []
    working = frame[[segment_column, treatment_column, outcome_column]].copy()
    working = working[working[treatment_column].astype("string").isin([treatment_value, control_value])]
    working = working[working[segment_column].notna()]
    if working.empty:
        return []
    working["__success"] = _success_mask(working[outcome_column], success_event).astype(int)
    grouped = (
        working.groupby([segment_column, treatment_column], dropna=False)["__success"]
        .agg(["count", "sum"])
        .reset_index()
    )
    totals = grouped.groupby(segment_column)["count"].sum().sort_values(ascending=False)
    output: list[dict[str, Any]] = []
    for segment in totals.head(50).index:
        rows = grouped[grouped[segment_column] == segment]
        treatment = rows[rows[treatment_column].astype(str) == treatment_value]
        control = rows[rows[treatment_column].astype(str) == control_value]
        treatment_count = int(treatment["count"].sum())
        control_count = int(control["count"].sum())
        treatment_successes = int(treatment["sum"].sum())
        control_successes = int(control["sum"].sum())
        stats = _lift_statistics(treatment_count, control_count, treatment_successes, control_successes)
        output.append({
            "segmentColumn": normalize_column_name(segment_column),
            "segment": str(segment),
            "treatmentCount": treatment_count,
            "controlCount": control_count,
            "treatmentConversionRate": stats["treatmentRate"],
            "controlConversionRate": stats["controlRate"],
            "absoluteLift": stats["absoluteLift"],
            "relativeLift": stats["relativeLift"],
            "pValue": stats["pValue"],
            "confidenceInterval": f"{stats['confidenceLow'] * 100:.2f}% to {stats['confidenceHigh'] * 100:.2f}%",
            "warning": "Small segment sample. Interpret directionally." if min(treatment_count, control_count) < 30 else "Segment has enough sample for review.",
        })
    return output


def _safe_records(frame: pd.DataFrame, limit: int = 2000) -> list[dict[str, Any]]:
    sample = frame.head(limit).copy()
    sample.columns = [normalize_column_name(column) for column in sample.columns]
    sample = sample.where(pd.notna(sample), None)
    records: list[dict[str, Any]] = []
    for record in sample.to_dict(orient="records"):
        records.append({key: value.item() if hasattr(value, "item") else value for key, value in record.items()})
    return records


@lru_cache(maxsize=32)
def _analyze_cached(
    path_text: str,
    modified_ns: int,
    dataset_name: str,
    unit_requested: str,
    treatment_requested: str,
    treatment_value: str,
    control_value: str,
    outcome_requested: str,
    success_event: str,
    exposure_requested: str,
    segment_requested: tuple[str, ...],
) -> dict[str, Any]:
    del modified_ns
    path = Path(path_text)
    header = pd.read_csv(path, nrows=0)
    raw_columns = [str(column) for column in header.columns]
    unit_column = _resolve_column(raw_columns, unit_requested)
    treatment_column = _resolve_column(raw_columns, treatment_requested)
    outcome_column = _resolve_column(raw_columns, outcome_requested)
    exposure_column = _resolve_column(raw_columns, exposure_requested, required=False)
    segment_columns = [resolved for requested in segment_requested if (resolved := _resolve_column(raw_columns, requested, required=False))]
    use_columns = list(dict.fromkeys([unit_column, treatment_column, outcome_column, exposure_column, *segment_columns]))
    use_columns = [column for column in use_columns if column]
    frame = pd.read_csv(path, usecols=use_columns, low_memory=False)

    treatment_text = frame[treatment_column].astype("string").str.strip()
    valid_treatment = treatment_text.isin([treatment_value, control_value])
    valid_unit = frame[unit_column].notna() & frame[unit_column].astype("string").str.strip().ne("")
    valid_outcome = frame[outcome_column].notna()
    valid = valid_treatment & valid_unit & valid_outcome
    analysis_frame = frame.loc[valid].copy()
    analysis_treatment = analysis_frame[treatment_column].astype("string").str.strip()
    success = _success_mask(analysis_frame[outcome_column], success_event)
    treatment_mask = analysis_treatment.eq(treatment_value)
    control_mask = analysis_treatment.eq(control_value)
    treatment_count = int(treatment_mask.sum())
    control_count = int(control_mask.sum())
    treatment_successes = int((success & treatment_mask).sum())
    control_successes = int((success & control_mask).sum())
    stats = _lift_statistics(treatment_count, control_count, treatment_successes, control_successes)
    row_count = int(len(frame))
    unit_values = frame.loc[valid_unit, unit_column].astype("string")
    unique_units = int(unit_values.nunique(dropna=True))
    mapped_count = treatment_count + control_count
    normalized_columns = [normalize_column_name(column) for column in raw_columns]

    profile = {
        "dataset": dataset_name,
        "rows": row_count,
        "columns": len(raw_columns),
        "uniqueUnits": unique_units,
        "duplicateUnits": max(0, int(len(unit_values)) - unique_units),
        "missingUnitId": int((~valid_unit).sum()),
        "missingTreatment": int(frame[treatment_column].isna().sum()),
        "missingOutcome": int(frame[outcome_column].isna().sum()),
        "invalidTreatment": int((frame[treatment_column].notna() & ~valid_treatment).sum()),
        "invalidOutcome": 0,
        "treatmentValuesDetected": [str(value) for value in frame[treatment_column].dropna().astype("string").value_counts().head(20).index],
        "outcomeValuesDetected": [str(value) for value in frame[outcome_column].dropna().astype("string").value_counts().head(20).index],
        "treatmentGroupCount": treatment_count,
        "controlGroupCount": control_count,
        "treatmentShare": treatment_count / mapped_count if mapped_count else 0.0,
        "controlShare": control_count / mapped_count if mapped_count else 0.0,
        "allocationRatio": treatment_count / control_count if control_count else 0.0,
    }
    summary = {
        "treatmentCount": treatment_count,
        "controlCount": control_count,
        "treatmentConversions": treatment_successes,
        "controlConversions": control_successes,
        "treatmentRate": stats["treatmentRate"],
        "controlRate": stats["controlRate"],
    }
    missing_by_column: dict[str, int] = {}
    for column in use_columns:
        series = frame[column]
        missing_by_column[normalize_column_name(column)] = int((series.isna() | series.astype("string").str.strip().eq("")).sum())
    exposure_summary: list[dict[str, Any]] = []
    if exposure_column:
        numeric_exposure = pd.to_numeric(analysis_frame[exposure_column], errors="coerce")
        for group in [control_value, treatment_value]:
            values = numeric_exposure.loc[analysis_treatment.eq(group)].dropna()
            exposure_summary.append({
                "group": group,
                "count": int(values.count()),
                "mean": float(values.mean()) if not values.empty else 0.0,
                "median": float(values.median()) if not values.empty else 0.0,
                "min": float(values.min()) if not values.empty else 0.0,
                "max": float(values.max()) if not values.empty else 0.0,
            })
    outcome_successes = treatment_successes + control_successes
    aggregates = {
        "outcomeSuccess": outcome_successes,
        "outcomeNonSuccess": int(len(analysis_frame)) - outcome_successes,
        "overallConversionRate": outcome_successes / len(analysis_frame) if len(analysis_frame) else 0.0,
        "missingByColumn": missing_by_column,
        "exposureAvailable": any(row["count"] > 0 for row in exposure_summary),
        "exposureSummary": exposure_summary,
    }
    day_segments = _segment_rows(analysis_frame, segment_columns[0] if segment_columns else None, treatment_column, treatment_value, control_value, outcome_column, success_event)
    hour_segments = _segment_rows(analysis_frame, segment_columns[1] if len(segment_columns) > 1 else None, treatment_column, treatment_value, control_value, outcome_column, success_event)
    display_frame = analysis_frame.rename(columns={column: normalize_column_name(column) for column in analysis_frame.columns})
    return {
        "status": {
            "dataset": dataset_name,
            "rowCount": row_count,
            "validAnalysisRecords": int(len(analysis_frame)),
            "fullDatasetAvailable": True,
            "previewOnly": False,
            "source": "full_dataset_artifact",
            "message": "Full registered dataset artifact analyzed. Browser rows are a bounded display sample; counts and statistics use the full artifact.",
        },
        "rows": _safe_records(display_frame),
        "profile": profile,
        "summary": summary,
        "daySegments": day_segments,
        "hourSegments": hour_segments,
        "aggregates": aggregates,
        "columns": normalized_columns,
    }


def analyze_registered_ab_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    dataset_id = str(payload.get("datasetId") or "").strip()
    if not dataset_id:
        raise HTTPException(status_code=422, detail="datasetId is required.")
    dataset = require_dataset(dataset_id)
    version_id = str(payload.get("versionId") or latest_version_id(dataset) or "").strip()
    if not version_id:
        raise HTTPException(status_code=409, detail="The selected dataset has no registered version.")
    path = version_dir(dataset_id, version_id) / "data_full.csv"
    if not path.exists():
        raise HTTPException(status_code=409, detail="Full dataset artifact is not loaded. Reopen or reload the confirmed dataset before running experiment analysis.")
    mapping = payload.get("mapping") or {}
    return _analyze_cached(
        str(path.resolve()),
        path.stat().st_mtime_ns,
        str(dataset.get("name") or dataset_id),
        str(mapping.get("unitIdColumn") or ""),
        str(mapping.get("treatmentColumn") or ""),
        str(mapping.get("treatmentValue") or ""),
        str(mapping.get("controlValue") or ""),
        str(mapping.get("outcomeColumn") or ""),
        str(mapping.get("successEvent") or "True"),
        str(mapping.get("exposureColumn") or ""),
        tuple(str(value) for value in (mapping.get("segmentColumns") or []) if str(value).strip()),
    )

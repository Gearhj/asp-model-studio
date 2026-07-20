from __future__ import annotations

import platform
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

import numpy as np
import pandas as pd
import scipy
import sklearn


ANALYSIS_VERSION = "1.0.0"
MAX_RESULT_ROWS = 2_000


def _safe(value: Any) -> Any:
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating,)): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)): return value.isoformat()
    if isinstance(value, dict): return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_safe(v) for v in value]
    if pd.isna(value): return None
    return value


def _bounded_rows(rows: list[Dict[str, Any]], limit: int = MAX_RESULT_ROWS) -> tuple[list[Dict[str, Any]], bool]:
    if len(rows) <= limit:
        return rows, False
    indices = np.linspace(0, len(rows) - 1, num=limit, dtype=int)
    return [rows[index] for index in indices], True


def table(table_id: str, title: str, rows: Iterable[Dict[str, Any]], columns: list[str] | None = None, **metadata: Any) -> Dict[str, Any]:
    clean, truncated = _bounded_rows([_safe(row) for row in rows])
    metadata = {**metadata, "chart_ready_subset": truncated, "row_limit": MAX_RESULT_ROWS}
    return {"table_id": table_id, "title": title, "columns": columns or (list(clean[0]) if clean else []), "rows": clean, "metadata": metadata}


def chart(chart_id: str, chart_type: str, title: str, data: list[Dict[str, Any]], *, x_field: str, x_label: str, y_fields: list[Dict[str, str]], subtitle: str = "", interpretation: str = "", **metadata: Any) -> Dict[str, Any]:
    bounded_data, truncated = _bounded_rows(data)
    metadata = {**metadata, "chart_ready_subset": True, "truncated": truncated, "row_limit": MAX_RESULT_ROWS}
    return _safe({"chart_id": chart_id, "chart_type": chart_type, "title": title, "subtitle": subtitle,
        "x_axis": {"field": x_field, "label": x_label, "type": "datetime" if "date" in x_field.lower() or "time" in x_field.lower() else "numeric"},
        "y_axes": y_fields, "series": [{"field": row["field"], "label": row.get("label") or row["field"]} for row in y_fields], "data": bounded_data,
        "reference_lines": metadata.pop("reference_lines", []), "reference_bands": metadata.pop("reference_bands", []), "annotations": metadata.pop("annotations", []),
        "documentation_caption": metadata.pop("documentation_caption", f"{title}."), "interpretation": interpretation, "metadata": metadata})


def result(analysis_type: str, context: Dict[str, Any], parameters: Dict[str, Any], *, statistics: Dict[str, Any] | None = None, tables: list[Dict[str, Any]] | None = None, charts: list[Dict[str, Any]] | None = None, diagnostics: list[Dict[str, Any]] | None = None, warnings: list[Dict[str, Any] | str] | None = None, interpretations: list[Dict[str, Any]] | None = None, status: str = "completed") -> Dict[str, Any]:
    normalized_warnings = [{"severity": "warning", "message": item} if isinstance(item, str) else item for item in (warnings or [])]
    return _safe({"analysis_id": f"analysis_{uuid.uuid4().hex[:16]}", "analysis_type": analysis_type, "analysis_version": ANALYSIS_VERSION,
        "project_id": context.get("project_id") or context.get("projectId"), "workflow_type": context.get("workflow_type") or context.get("workflowType"),
        "dataset_id": context.get("dataset_id"), "dataset_version_id": context.get("dataset_version_id"), "run_record_id": context.get("source_run_record_id"),
        "status": status, "created_at": datetime.now(timezone.utc).isoformat(), "created_by_user_id": context.get("requested_by_user_id"),
        "inputs": context.get("input_reference", {}), "parameters": parameters, "statistics": statistics or {}, "tables": tables or [], "charts": charts or [],
        "diagnostics": diagnostics or [], "warnings": normalized_warnings, "interpretations": interpretations or [],
        "evidence_payload": {}, "documentation_payload": {}, "validation_payload": {}, "monitoring_payload": {}, "lineage": context,
        "metadata": {"reproducibility": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__, "scikit_learn": sklearn.__version__}}})

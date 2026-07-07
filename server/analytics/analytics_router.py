from __future__ import annotations

import re
import sqlite3
import time
from io import BytesIO
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..security.security_store import audit_event, require_user
from .analytics_store import create_insight, delete_insight, diagnostics, get_insight, list_insights
from .export_utils import ExportDependencyError, build_excel_export, build_powerpoint_export, build_result_excel_export, build_word_export


router = APIRouter(dependencies=[Depends(require_user)])


class InsightRequest(BaseModel):
    title: str
    summary: str = ""
    datasetId: str
    versionId: str = ""
    projectId: Optional[str] = None
    businessQuestion: str = ""
    analysisType: str = "dataset_overview"
    evidence: Dict[str, Any] = Field(default_factory=dict)


class SqlRunRequest(BaseModel):
    sql: str
    datasetName: str = "primary_dataset"
    versionId: str = ""
    previewRows: list[Dict[str, Any]] = Field(default_factory=list)
    secondaryDatasetName: str = "secondary_dataset"
    secondaryPreviewRows: list[Dict[str, Any]] = Field(default_factory=list)


class AnalyticsExportRequest(BaseModel):
    exportTitle: str = "ATLAS Analytics Workbench Report"
    datasetName: str = "selected dataset"
    datasetId: str = ""
    versionId: str = ""
    businessQuestion: str = ""
    cleanedQuestion: str = ""
    analysisPlan: list[str] = Field(default_factory=list)
    targetVariable: str = ""
    previewRowCount: int = 0
    pivotConfig: Dict[str, Any] = Field(default_factory=dict)
    pivotRows: list[Dict[str, Any]] = Field(default_factory=list)
    pivotReadout: str = ""
    sqlResult: Dict[str, Any] = Field(default_factory=dict)
    sasResult: Dict[str, Any] = Field(default_factory=dict)
    pythonResult: Dict[str, Any] = Field(default_factory=dict)
    rResult: Dict[str, Any] = Field(default_factory=dict)
    generatedPython: str = ""
    generatedSql: str = ""
    generatedR: str = ""
    generatedSas: str = ""
    userEditedPython: str = ""
    userEditedSql: str = ""
    userEditedR: str = ""
    userEditedSas: str = ""
    savedInsight: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    linkedProjectId: str = ""
    createdAt: str = ""
    createdBy: str = "ATLAS local user"
    limitations: str = ""


class AnalyticsResultExportRequest(BaseModel):
    resultType: str
    exportTitle: str = "ATLAS Analysis Result"
    datasetName: str = "selected dataset"
    versionId: str = ""
    businessQuestion: str = ""
    resultPayload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    createdAt: str = ""


@router.get("/analytics/insights")
def get_insights(datasetId: Optional[str] = None, projectId: Optional[str] = None) -> Dict[str, Any]:
    return {"ok": True, "insights": list_insights(dataset_id=datasetId, project_id=projectId)}


@router.post("/analytics/insights")
def post_insight(payload: InsightRequest) -> Dict[str, Any]:
    return {"ok": True, "insight": create_insight(payload.model_dump())}


@router.get("/analytics/insights/{insight_id}")
def get_one_insight(insight_id: str) -> Dict[str, Any]:
    return {"ok": True, "insight": get_insight(insight_id)}


@router.delete("/analytics/insights/{insight_id}")
def delete_one_insight(insight_id: str) -> Dict[str, Any]:
    return delete_insight(insight_id)


@router.post("/analytics/audit-run")
def post_analysis_run(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    audit_event(
        "analytics.analysis.run",
        "dataset",
        str(payload.get("datasetId") or ""),
        "success",
        metadata={"analysisType": payload.get("analysisType"), "versionId": payload.get("versionId")},
    )
    return {"ok": True}


@router.post("/analytics/sql/run")
def run_preview_sql(payload: SqlRunRequest) -> Dict[str, Any]:
    started = time.perf_counter()
    sql = normalize_preview_sql(payload.sql, payload.datasetName, payload.versionId, payload.secondaryDatasetName)
    if not is_safe_select(sql):
        return {
            "ok": False,
            "status": "error",
            "columns": [],
            "rows": [],
            "rowCount": 0,
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "error": "Only a single SELECT statement is allowed. INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, ATTACH, PRAGMA, and multiple statements are blocked.",
        }

    try:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            primary_alias = safe_sql_name(payload.datasetName) or "primary_dataset"
            load_rows(conn, "primary_dataset", payload.previewRows)
            if primary_alias != "primary_dataset":
                load_rows(conn, primary_alias, payload.previewRows)
            if payload.secondaryPreviewRows:
                secondary_alias = safe_sql_name(payload.secondaryDatasetName) or "secondary_dataset"
                load_rows(conn, "secondary_dataset", payload.secondaryPreviewRows)
                if secondary_alias != "secondary_dataset":
                    load_rows(conn, secondary_alias, payload.secondaryPreviewRows)

            limited_sql = apply_sql_limit(sql, 500)
            cursor = conn.execute(limited_sql)
            result_rows = [dict(row) for row in cursor.fetchall()]
            columns = [description[0] for description in cursor.description or []]
        return {
            "ok": True,
            "status": "success",
            "columns": columns,
            "rows": result_rows,
            "rowCount": len(result_rows),
            "runtimeMs": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "columns": [],
            "rows": [],
            "rowCount": 0,
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "error": str(exc),
        }


@router.get("/analytics/diagnostics")
def get_analytics_diagnostics() -> Dict[str, Any]:
    return diagnostics()


@router.post("/analytics/export/excel")
def export_analytics_excel(payload: AnalyticsExportRequest) -> StreamingResponse:
    return stream_export(payload, "excel", "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", build_excel_export)


@router.post("/analytics/export/word")
def export_analytics_word(payload: AnalyticsExportRequest) -> StreamingResponse:
    return stream_export(payload, "word", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", build_word_export)


@router.post("/analytics/export/powerpoint")
def export_analytics_powerpoint(payload: AnalyticsExportRequest) -> StreamingResponse:
    return stream_export(payload, "powerpoint", "pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", build_powerpoint_export)


@router.post("/analytics/export/result/excel")
def export_analytics_result_excel(payload: AnalyticsResultExportRequest) -> StreamingResponse:
    allowed = {
        "column_explorer",
        "target_relationship",
        "group_comparison",
        "data_quality",
        "pivot",
        "sql_result",
        "sas_compatible_result",
        "r_result",
        "python_result",
    }
    if payload.resultType not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported analytics result export type: {payload.resultType}")
    try:
        content = build_result_excel_export(payload.model_dump())
    except ExportDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ATLAS could not create the Excel result export: {exc}") from exc
    filename = safe_export_filename(f"ATLAS-{payload.exportTitle}-{payload.datasetName}", "xlsx")
    audit_event(
        "analytics.result.export.created",
        "dataset",
        payload.datasetName,
        "success",
        metadata={"format": "excel", "resultType": payload.resultType, "versionId": payload.versionId},
    )
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def stream_export(payload: AnalyticsExportRequest, label: str, extension: str, media_type: str, builder) -> StreamingResponse:
    try:
        content = builder(payload.model_dump())
    except ExportDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ATLAS could not create the {label} export: {exc}") from exc
    filename = safe_export_filename(payload.datasetName or payload.datasetId or "atlas-analytics", extension)
    audit_event(
        "analytics.export.created",
        "dataset",
        payload.datasetId or "",
        "success",
        metadata={"format": label, "versionId": payload.versionId, "projectId": payload.linkedProjectId},
    )
    return StreamingResponse(
        BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def normalize_preview_sql(sql: str, dataset_name: str, version_id: str, secondary_name: str) -> str:
    normalized = sql.strip()
    primary_alias = safe_sql_name(dataset_name) or "primary_dataset"
    secondary_alias = safe_sql_name(secondary_name) or "secondary_dataset"
    logical_primary = f"atlas_dataset.{safe_sql_name(dataset_name)}_{safe_sql_name(version_id or 'current')}"
    normalized = re.sub(re.escape(logical_primary), primary_alias, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\batlas_dataset\.[A-Za-z0-9_]+\b", primary_alias, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bprimary_dataset\b", "primary_dataset", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bsecondary_dataset\b", "secondary_dataset", normalized, flags=re.IGNORECASE)
    if secondary_name:
        normalized = re.sub(rf"\b{re.escape(safe_sql_name(secondary_name))}\b", secondary_alias, normalized, flags=re.IGNORECASE)
    return normalized


def is_safe_select(sql: str) -> bool:
    stripped = strip_sql_comments(sql).strip().rstrip(";").strip()
    if not re.match(r"^select\b", stripped, re.IGNORECASE | re.DOTALL):
        return False
    if ";" in stripped:
        return False
    blocked = r"\b(insert|update|delete|drop|alter|create|attach|pragma|replace|vacuum|reindex|detach|truncate)\b"
    return not re.search(blocked, stripped, re.IGNORECASE)


def strip_sql_comments(sql: str) -> str:
    without_line = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    return re.sub(r"/\*.*?\*/", "", without_line, flags=re.DOTALL)


def apply_sql_limit(sql: str, max_rows: int) -> str:
    stripped = sql.strip().rstrip(";").strip()
    if re.search(r"\blimit\s+\d+\b", stripped, re.IGNORECASE):
        return stripped
    return f"SELECT * FROM ({stripped}) AS atlas_preview_query LIMIT {max_rows}"


def safe_sql_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", value or "").strip("_")
    if not safe:
        return ""
    if re.match(r"^\d", safe):
        safe = f"t_{safe}"
    return safe


def safe_export_filename(value: str, extension: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "atlas-analytics").strip("-._")
    if not safe:
        safe = "atlas-analytics"
    return f"{safe[:80]}-analytics-export.{extension}"


def load_rows(conn: sqlite3.Connection, table_name: str, rows: list[Dict[str, Any]]) -> None:
    columns = sorted({key for row in rows for key in row.keys()}) or ["empty"]
    quoted_columns = [quote_identifier(column) for column in columns]
    conn.execute(f"CREATE TABLE {quote_identifier(table_name)} ({', '.join(f'{column} TEXT' for column in quoted_columns)})")
    if not rows:
        return
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO {quote_identifier(table_name)} ({', '.join(quoted_columns)}) VALUES ({placeholders})",
        [[normalize_sql_value(row.get(column)) for column in columns] for row in rows],
    )


def quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) + chr(34))}"'


def normalize_sql_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, bool):
        return int(value)
    return str(value)

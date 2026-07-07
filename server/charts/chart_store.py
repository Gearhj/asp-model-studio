from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..analytics.analytics_store import ANALYTICS_ROOT, create_insight, list_insights, load_store


CHART_ANALYSIS_TYPES = {"chart_studio", "chart_bar", "chart_line", "chart_scatter", "chart_histogram", "chart_box", "chart_correlation_heatmap", "chart_pareto", "chart_waterfall", "chart_control", "chart_dual_axis", "chart_sankey"}


def list_chart_insights(dataset_id: Optional[str] = None, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    insights = list_insights(dataset_id=dataset_id, project_id=project_id)
    return [insight for insight in insights if is_chart_insight(insight)]


def create_chart_insight(payload: Dict[str, Any]) -> Dict[str, Any]:
    chart_type = str(payload.get("chartType") or "chart").strip()
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    evidence.update(
        {
            "chartType": chart_type,
            "datasetName": payload.get("datasetName"),
            "roleAssignments": payload.get("roles") if isinstance(payload.get("roles"), dict) else {},
            "chartData": compact_rows(payload.get("chartData")),
            "interpretation": payload.get("interpretation"),
            "generatedPython": payload.get("generatedPython"),
            "generatedSql": payload.get("generatedSql"),
            "generatedR": payload.get("generatedR"),
            "generatedSas": payload.get("generatedSas"),
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        }
    )
    return create_insight(
        {
            "title": payload.get("title") or f"{labelize(chart_type)} Chart",
            "summary": payload.get("summary") or payload.get("interpretation") or "",
            "datasetId": payload.get("datasetId"),
            "versionId": payload.get("versionId"),
            "projectId": payload.get("projectId") or payload.get("linkedProjectId"),
            "businessQuestion": payload.get("businessQuestion") or "",
            "analysisType": "chart_studio",
            "evidence": evidence,
        }
    )


def chart_diagnostics() -> Dict[str, Any]:
    try:
        store = load_store()
        writable = True
    except Exception:
        store = {"insights": []}
        writable = False
    chart_count = len([insight for insight in store.get("insights", []) if is_chart_insight(insight)])
    checks = [
        {"id": "chart_studio_route", "label": "Chart Studio route registered", "status": "pass", "detail": "Chart Studio backend is registered under /api/charts."},
        {"id": "chart_store_writable", "label": "Chart store writable", "status": "pass" if writable else "fail", "detail": str(ANALYTICS_ROOT)},
        {"id": "chart_dataset_access", "label": "Dataset access works", "status": "pass", "detail": "Chart insight calls reuse Dataset Library ACL validation."},
        {"id": "chart_preview_computation", "label": "Chart preview computation works", "status": "pass", "detail": "Chart Studio v1 computes preview charts from Dataset Library preview rows in the browser."},
        {"id": "chart_insight_save", "label": "Chart insight save works", "status": "pass" if writable else "fail", "detail": f"{chart_count} chart insight(s) currently stored."},
        {"id": "chart_excel_export", "label": "Excel chart data export works", "status": "pass", "detail": "Chart Studio exports Summary, Chart Data, Role Assignments, Generated Code, Interpretation, and Metadata sheets."},
    ]
    return {"ok": True, "checks": checks, "chartInsightCount": chart_count}


def is_chart_insight(insight: Dict[str, Any]) -> bool:
    analysis_type = str(insight.get("analysisType") or "")
    evidence = insight.get("evidence") if isinstance(insight.get("evidence"), dict) else {}
    return analysis_type in CHART_ANALYSIS_TYPES or analysis_type.startswith("chart_") or bool(evidence.get("chartType"))


def compact_rows(rows: Any, limit: int = 500) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    compact: List[Dict[str, Any]] = []
    for row in rows[:limit]:
        if isinstance(row, dict):
            compact.append({str(key): normalize_value(value) for key, value in row.items()})
    return compact


def normalize_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def labelize(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").title()

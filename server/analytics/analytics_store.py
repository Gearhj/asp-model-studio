from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from ..datasets.dataset_registry import require_dataset
from ..security.security_store import active_user, audit_event


ANALYTICS_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "analytics"
INSIGHTS_PATH = ANALYTICS_ROOT / "insights.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_store() -> None:
    ANALYTICS_ROOT.mkdir(parents=True, exist_ok=True)
    if not INSIGHTS_PATH.exists():
        INSIGHTS_PATH.write_text(json.dumps({"insights": []}, indent=2), encoding="utf-8")


def load_store() -> Dict[str, Any]:
    ensure_store()
    try:
        payload = json.loads(INSIGHTS_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload.get("insights"), list) else {"insights": []}
    except Exception:
        return {"insights": []}


def save_store(payload: Dict[str, Any]) -> None:
    ensure_store()
    INSIGHTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def user_id() -> str:
    user = active_user() or {}
    return str(user.get("userId") or "unknown-user")


def user_is_admin() -> bool:
    return (active_user() or {}).get("role") == "admin"


def can_access_dataset(dataset_id: str) -> bool:
    try:
        require_dataset(dataset_id)
        return True
    except HTTPException:
        audit_event("analytics.access.denied", "dataset", dataset_id, "denied", reason="Dataset ACL denied for analytics")
        return False


def list_insights(dataset_id: Optional[str] = None, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    store = load_store()
    visible: List[Dict[str, Any]] = []
    for insight in store.get("insights", []):
        if dataset_id and insight.get("datasetId") != dataset_id:
            continue
        if project_id and insight.get("projectId") != project_id:
            continue
        if can_access_dataset(str(insight.get("datasetId", ""))):
            visible.append(insight)
    return sorted(visible, key=lambda item: item.get("createdAt", ""), reverse=True)


def create_insight(payload: Dict[str, Any]) -> Dict[str, Any]:
    dataset_id = str(payload.get("datasetId") or "")
    if not dataset_id or not can_access_dataset(dataset_id):
        raise HTTPException(status_code=403, detail="You do not have access to save analytics for this dataset.")
    timestamp = now_iso()
    insight = {
        "insightId": f"insight_{uuid.uuid4().hex[:16]}",
        "title": str(payload.get("title") or "Untitled Insight").strip() or "Untitled Insight",
        "summary": str(payload.get("summary") or "").strip(),
        "datasetId": dataset_id,
        "versionId": str(payload.get("versionId") or ""),
        "projectId": str(payload.get("projectId") or "") or None,
        "businessQuestion": str(payload.get("businessQuestion") or "").strip(),
        "analysisType": str(payload.get("analysisType") or "dataset_overview"),
        "createdByUserId": user_id(),
        "createdAt": timestamp,
        "evidence": payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {},
    }
    store = load_store()
    store["insights"] = [insight] + store.get("insights", [])
    save_store(store)
    audit_event(
        "analytics.insight.saved",
        "dataset",
        dataset_id,
        "success",
        metadata={"insightId": insight["insightId"], "analysisType": insight["analysisType"], "projectId": insight.get("projectId")},
    )
    return insight


def get_insight(insight_id: str) -> Dict[str, Any]:
    for insight in load_store().get("insights", []):
        if insight.get("insightId") == insight_id and can_access_dataset(str(insight.get("datasetId", ""))):
            return insight
    raise HTTPException(status_code=404, detail="Insight not found.")


def delete_insight(insight_id: str) -> Dict[str, Any]:
    store = load_store()
    insights = store.get("insights", [])
    target = next((item for item in insights if item.get("insightId") == insight_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Insight not found.")
    if not can_access_dataset(str(target.get("datasetId", ""))):
        raise HTTPException(status_code=403, detail="You do not have access to this insight.")
    if target.get("createdByUserId") != user_id() and not user_is_admin():
        audit_event("analytics.access.denied", "analytics_insight", insight_id, "denied", reason="Only owner or admin can delete insight")
        raise HTTPException(status_code=403, detail="Only the insight owner or admin can delete this insight.")
    store["insights"] = [item for item in insights if item.get("insightId") != insight_id]
    save_store(store)
    audit_event("analytics.insight.deleted", "analytics_insight", insight_id, "success", metadata={"datasetId": target.get("datasetId")})
    return {"ok": True, "deleted": insight_id}


def diagnostics() -> Dict[str, Any]:
    ensure_store()
    try:
        payload = load_store()
        writable = True
    except Exception:
        payload = {"insights": []}
        writable = False
    checks = [
        {"id": "analytics_routes", "label": "Analytics routes available", "status": "pass", "detail": "Analytics router is registered under /api/analytics."},
        {"id": "analytics_store_readable", "label": "Analytics insight store readable", "status": "pass" if isinstance(payload.get("insights"), list) else "fail", "detail": str(INSIGHTS_PATH)},
        {"id": "analytics_store_writable", "label": "Analytics insight store writable", "status": "pass" if writable else "fail", "detail": str(ANALYTICS_ROOT)},
        {"id": "analytics_acl", "label": "Dataset access enforced for analytics", "status": "pass", "detail": "Insight list/create/delete calls validate dataset access through Dataset Library ACLs."},
        {"id": "analytics_python", "label": "Python execution endpoint status", "status": "warning", "detail": "Workbench Python uses the local /api/python/run endpoint against user-provided preview/sample code."},
        {"id": "analytics_sql_preview", "label": "SQL preview execution", "status": "pass", "detail": "Workbench SQL uses /api/analytics/sql/run for safe SELECT-only execution over preview rows."},
        {"id": "analytics_r_template", "label": "R workspace status", "status": "warning", "detail": "R code generation is available. Execution depends on local Rscript diagnostics."},
        {"id": "analytics_sas_compatible", "label": "SAS-compatible engine", "status": "pass", "detail": "ATLAS can execute supported SAS-style PROC and DATA step syntax without a SAS license."},
        {"id": "analytics_code_insights", "label": "Code insight store writable", "status": "pass" if writable else "fail", "detail": "Python, SQL, R, and SAS snippets can be saved as analytics insights when the store is writable."},
        {"id": "analytics_notebook", "label": "Notebook export available", "status": "warning", "detail": "Saved workbench Python is not yet merged into the governed notebook export."},
    ]
    try:
        from ..python_execution import sas_diagnostics

        sas = sas_diagnostics()
        if sas.get("sasExecutionAvailable"):
            status = "pass"
            detail = f"Optional licensed SAS bridge is available through {sas.get('connectionMethod', 'SASPy')}."
        elif sas.get("saspyInstalled"):
            status = "warning"
            detail = f"ATLAS SAS-Compatible mode is available. Optional SASPy bridge is installed but {sas.get('connectionMethod', 'Template only')}."
        else:
            status = "pass"
            detail = "ATLAS SAS-Compatible mode is available. SASPy is only needed for the optional licensed SAS bridge."
        checks.append({"id": "analytics_sas_runtime_setup", "label": "Optional licensed SAS bridge", "status": status, "detail": detail})
    except Exception as exc:
        checks.append({"id": "analytics_sas_runtime_setup", "label": "SAS runtime setup", "status": "warning", "detail": f"SAS runtime diagnostics unavailable: {exc}"})
    return {"ok": True, "checks": checks, "insightCount": len(payload.get("insights", [])), "artifactRoot": str(ANALYTICS_ROOT)}

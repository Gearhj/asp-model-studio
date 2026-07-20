from __future__ import annotations

from typing import Any, Dict

from ..persistence.db import now_iso


def capture(persistence: Any, analytical_run: Dict[str, Any], result: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    evidence_id = f"ev_analytics_{analytical_run['analytical_run_id']}"
    return persistence.evidence.upsert({"evidence_id": evidence_id, "project_id": analytical_run.get("project_id"), "workflow_type": analytical_run.get("workflow_type") or "analytics", "step_id": "analytics_engine", "artifact_type": "analytical_run", "status": "captured", "title": f"{result.get('analysis_type', 'Analytical')} result", "summary": "Structured analytical result, warnings, interpretations, tables, and chart specifications.", "source_ref": analytical_run["analytical_run_id"], "created_by": user.get("userId"), "created_at": now_iso(), "captured_at": now_iso(), "payload_json": result})

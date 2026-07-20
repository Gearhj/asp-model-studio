from __future__ import annotations

from typing import Any, Dict


def documentation_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    return {"type":"analytical_result","analysis_id":result.get("analysis_id"),"analysis_type":result.get("analysis_type"),"statistics":result.get("statistics"),"tables":result.get("tables"),"charts":result.get("charts"),"interpretations":result.get("interpretations"),"lineage":result.get("lineage")}

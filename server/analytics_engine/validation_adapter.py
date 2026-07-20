from __future__ import annotations
from typing import Any, Dict

def validation_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    return {"analysis_type":result.get("analysis_type"),"assumption_status":"review_required" if result.get("warnings") else "no_automated_issue","warnings":result.get("warnings"),"governing_metric":result.get("statistics"),"diagnostic_findings":result.get("interpretations")}

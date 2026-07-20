from __future__ import annotations

from typing import Any, Dict

from ..result_builder import result, table


def compute_llm_evaluation(payload: Dict[str, Any], context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    rows=payload.get("rows") or payload.get("evaluations") or []
    if not rows: return result("llm_evaluation",context,parameters,status="insufficient_data",warnings=["LLM evaluation requires reviewer or automated evaluation records."])
    numeric_fields=["groundedness","citation_accuracy","safety_compliance","latency_ms","cost","reviewer_agreement"]
    stats={field:sum(float(row.get(field) or 0) for row in rows if row.get(field) is not None)/max(sum(1 for row in rows if row.get(field) is not None),1) for field in numeric_fields}
    return result("llm_evaluation",context,parameters,statistics={**stats,"evaluation_count":len(rows)},tables=[table("llm_evaluation_records","LLM evaluation records",rows)])

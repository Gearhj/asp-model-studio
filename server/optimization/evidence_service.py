from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException


EVIDENCE_TYPE_BY_STAGE = {
    "decision_charter": "optimization_decision_charter",
    "input_bundle": "optimization_input_bundle",
    "data_profile": "optimization_data_profile",
    "route_normalization": "optimization_route_normalization",
    "formulation_readiness": "optimization_formulation_readiness",
    "objective": "optimization_objective",
    "decision_variables": "optimization_decision_variables",
    "constraints": "optimization_constraints",
    "solver_configuration": "optimization_solver_configuration",
    "baseline": "optimization_baseline",
    "scenarios": "optimization_scenarios",
    "solver_run": "optimization_solver_run",
    "solution": "optimization_solution",
    "sensitivity": "optimization_sensitivity",
    "validation": "optimization_validation",
    "recommendation": "optimization_recommendation",
    "implementation_plan": "optimization_implementation_plan",
    "monitoring_plan": "optimization_monitoring_plan",
    "code_reproducibility": "optimization_code_reproducibility",
}


FINAL_RESULT_STAGES = {"scenarios", "solver_run", "solution", "sensitivity", "validation", "recommendation"}


def build_transportation_evidence(
    stage: str,
    formulation: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or {}
    evidence_type = EVIDENCE_TYPE_BY_STAGE.get(stage)
    if not evidence_type:
        raise HTTPException(status_code=422, detail=f"Unsupported optimization evidence stage '{stage}'.")
    if stage in FINAL_RESULT_STAGES and (result or {}).get("businessValidityStatus") != "valid":
        raise HTTPException(
            status_code=409,
            detail="Invalid or placeholder optimization results cannot be captured as final evidence.",
        )
    input_tables = formulation.get("inputTables") or []
    return {
        "evidenceType": evidence_type,
        "projectId": context.get("projectId") or "",
        "title": f"Optimization {stage.replace('_', ' ').title()}",
        "status": "ready",
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "capturedBy": context.get("user") or "Local ATLAS User",
        "datasetVersions": [
            {
                "role": table.get("role"),
                "datasetId": table.get("datasetId"),
                "versionId": table.get("versionId"),
                "fileName": table.get("fileName"),
                "rowCount": table.get("rowCount"),
            }
            for table in input_tables
        ],
        "normalizationHash": formulation.get("normalizationHash"),
        "formulationId": formulation.get("formulationId"),
        "formulationVersion": formulation.get("formulationVersion"),
        "variableCount": len(formulation.get("variables") or []),
        "constraintCount": len(formulation.get("constraints") or []),
        "objectiveDirection": (formulation.get("objective") or {}).get("direction"),
        "solverMethod": "Linear programming (LP)",
        "runId": (result or {}).get("runId"),
        "solutionId": (result or {}).get("solutionId"),
        "businessValidityStatus": (result or {}).get("businessValidityStatus"),
        "chartMetadata": context.get("chartMetadata") or [],
        "codeReferences": context.get("codeReferences") or [],
        "decisionNotes": context.get("decisionNotes") or "",
        "metrics": {
            **(formulation.get("metrics") or {}),
            "totalCost": (result or {}).get("totalCost"),
            "demandFulfilled": (result or {}).get("demandFulfilled"),
            "unmetDemand": (result or {}).get("unmetDemand"),
            "activeRoutes": (result or {}).get("activeRoutes"),
        },
    }

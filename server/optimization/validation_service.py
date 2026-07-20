from __future__ import annotations

from typing import Any


def _check(check_id: str, label: str, passed: bool, evidence: str, *, requires_confirmation: bool = False) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "passed": bool(passed),
        "status": "pass" if passed else "fail",
        "evidence": evidence,
        "requiresConfirmation": requires_confirmation,
    }


def validate_transportation_decision(
    formulation: dict[str, Any],
    result: dict[str, Any],
    scenario_analysis: dict[str, Any] | None = None,
    sensitivity: dict[str, Any] | None = None,
    confirmations: dict[str, bool] | None = None,
) -> dict[str, Any]:
    scenario_analysis = scenario_analysis or {}
    sensitivity = sensitivity or {}
    confirmations = confirmations or {}
    scenario_results = scenario_analysis.get("results") or []
    checks = [
        _check("formulation_validity", "Formulation validity", formulation.get("formulationReady") is True, f"Formulation {formulation.get('formulationId') or 'not available'}."),
        _check("solver_feasibility", "Solver feasibility", result.get("solverFeasible") is True, str(result.get("solverMessage") or "No solver result.")),
        _check("business_feasibility", "Business feasibility", result.get("businessValidityStatus") == "valid", f"Business validity is {result.get('businessValidityStatus', 'unknown')}."),
        _check("demand_fulfillment", "Demand fulfillment", float(result.get("unmetDemand") or 0.0) <= 1e-6 and float(result.get("demandFulfilled") or 0.0) > 0, f"Fulfilled {result.get('demandFulfilled', 0):g} of {result.get('totalDemand', 0):g}."),
        _check("supply_compliance", "Supply compliance", all(row.get("feasible") for row in result.get("supplyConstraintResults") or []), "All generated supplier limits were evaluated."),
        _check("transport_compliance", "Transport capacity compliance", all(row.get("feasible") for row in result.get("transportConstraintResults") or []), "All generated transport limits were evaluated."),
        _check("scenario_coverage", "Scenario coverage", len(scenario_results) >= 5, f"{len(scenario_results)} transportation scenarios evaluated with feasible and infeasible outcomes reported as returned by the solver."),
        _check("sensitivity_coverage", "Sensitivity coverage", sensitivity.get("available") is True and len(sensitivity.get("rows") or []) >= 10, f"{len(sensitivity.get('rows') or [])} perturbations evaluated."),
        _check("evidence_completeness", "Evidence completeness", confirmations.get("evidenceCompleteness") is True, "Validator confirmation is required.", requires_confirmation=True),
        _check("implementation_readiness", "Implementation readiness", confirmations.get("implementationReadiness") is True, "Operations readiness confirmation is required.", requires_confirmation=True),
        _check("independent_review", "Independent review", confirmations.get("independentReview") is True, "Independent reviewer confirmation is required.", requires_confirmation=True),
    ]
    mathematical_ids = {"formulation_validity", "solver_feasibility", "business_feasibility", "demand_fulfillment", "supply_compliance", "transport_compliance"}
    mathematical_success = all(check["passed"] for check in checks if check["id"] in mathematical_ids)
    governance_acceptance = all(check["passed"] for check in checks if check["requiresConfirmation"])
    passed_count = sum(check["passed"] for check in checks)
    blockers = [check["label"] for check in checks if not check["passed"]]
    warnings: list[str] = []
    if result.get("objectiveValue") == 0 and float(result.get("totalDemand") or 0) > 0:
        warnings.append("Objective is zero for a positive-demand cost-minimization problem.")
    if not result.get("activeRoutes") and float(result.get("totalDemand") or 0) > 0:
        warnings.append("All decision values are zero despite positive demand.")
    if int((formulation.get("metrics") or {}).get("demandConstraintCount") or 0) == 0:
        warnings.append("No demand constraints exist.")
    recommendation_allowed = mathematical_success and governance_acceptance and not warnings
    return {
        "checks": checks,
        "score": round(100.0 * passed_count / len(checks), 1),
        "passedCount": passed_count,
        "totalCount": len(checks),
        "mathematicalSuccess": mathematical_success,
        "governanceAcceptance": governance_acceptance,
        "recommendationAllowed": recommendation_allowed,
        "status": "approved" if recommendation_allowed else "review_required",
        "blockers": blockers,
        "warnings": warnings,
    }

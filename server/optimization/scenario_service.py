from __future__ import annotations

from typing import Any

from .solver_service import solve_transportation_formulation
from .transportation_template_service import scaled_transportation_formulation


DEFAULT_TRANSPORTATION_SCENARIOS = [
    {
        "id": "base",
        "name": "Base Case",
        "demandMultiplier": 1.0,
        "supplyMultiplier": 1.0,
        "capacityMultiplier": 1.0,
        "routeCostMultiplier": 1.0,
        "inventoryCostMultiplier": 1.0,
        "note": "Current confirmed planning assumptions.",
    },
    {
        "id": "demand-surge",
        "name": "Demand Surge",
        "demandMultiplier": 1.15,
        "supplyMultiplier": 1.0,
        "capacityMultiplier": 1.0,
        "routeCostMultiplier": 1.0,
        "inventoryCostMultiplier": 1.0,
        "note": "Tests 15 percent higher demand with current capacity.",
    },
    {
        "id": "capacity-stress",
        "name": "Capacity Stress",
        "demandMultiplier": 1.0,
        "supplyMultiplier": 0.9,
        "capacityMultiplier": 0.85,
        "routeCostMultiplier": 1.0,
        "inventoryCostMultiplier": 1.0,
        "note": "Tests reduced supply and transport throughput.",
    },
    {
        "id": "transport-cost-increase",
        "name": "Transport Cost Increase",
        "demandMultiplier": 1.0,
        "supplyMultiplier": 1.0,
        "capacityMultiplier": 1.0,
        "routeCostMultiplier": 1.25,
        "inventoryCostMultiplier": 1.0,
        "note": "Tests a 25 percent increase in route costs.",
    },
    {
        "id": "severe-disruption",
        "name": "Severe Disruption",
        "demandMultiplier": 1.1,
        "supplyMultiplier": 0.85,
        "capacityMultiplier": 0.75,
        "routeCostMultiplier": 1.3,
        "inventoryCostMultiplier": 1.1,
        "note": "Combined demand, capacity, and cost stress.",
    },
]


def _multiplier(scenario: dict[str, Any], key: str) -> float:
    try:
        value = float(scenario.get(key, 1.0))
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, value)


def _decision_map(result: dict[str, Any]) -> dict[str, float]:
    return {
        row["variableName"]: float(row["quantity"])
        for row in result.get("decisionVector") or []
    }


def run_transportation_scenarios(
    formulation: dict[str, Any],
    scenarios: list[dict[str, Any]] | None = None,
    solver: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not formulation.get("formulationReady"):
        return {
            "available": False,
            "message": "Scenario analysis requires a valid route-level formulation with demand, supply, and transport-capacity constraints.",
            "results": [],
        }
    scenario_rows = scenarios or DEFAULT_TRANSPORTATION_SCENARIOS
    base_scenario = next((row for row in scenario_rows if row.get("id") == "base"), DEFAULT_TRANSPORTATION_SCENARIOS[0])
    base_formulation = scaled_transportation_formulation(
        formulation,
        demand_multiplier=_multiplier(base_scenario, "demandMultiplier"),
        supply_multiplier=_multiplier(base_scenario, "supplyMultiplier"),
        capacity_multiplier=_multiplier(base_scenario, "capacityMultiplier"),
        route_cost_multiplier=_multiplier(base_scenario, "routeCostMultiplier"),
        inventory_cost_multiplier=_multiplier(base_scenario, "inventoryCostMultiplier"),
    )
    base_result = solve_transportation_formulation(base_formulation, solver)
    base_cost = base_result.get("totalCost")
    base_decisions = _decision_map(base_result)
    base_bindings = {row["constraintName"] for row in base_result.get("bindingConstraints") or []}

    results: list[dict[str, Any]] = []
    for scenario in scenario_rows:
        scaled = scaled_transportation_formulation(
            formulation,
            demand_multiplier=_multiplier(scenario, "demandMultiplier"),
            supply_multiplier=_multiplier(scenario, "supplyMultiplier"),
            capacity_multiplier=_multiplier(scenario, "capacityMultiplier"),
            route_cost_multiplier=_multiplier(scenario, "routeCostMultiplier"),
            inventory_cost_multiplier=_multiplier(scenario, "inventoryCostMultiplier"),
        )
        result = base_result if scenario.get("id") == base_scenario.get("id") else solve_transportation_formulation(scaled, solver)
        decisions = _decision_map(result)
        turnover = sum(abs(decisions.get(name, 0.0) - base_decisions.get(name, 0.0)) for name in set(decisions) | set(base_decisions)) / 2.0
        bindings = {row["constraintName"] for row in result.get("bindingConstraints") or []}
        scenario_cost = result.get("totalCost")
        results.append({
            "scenarioId": scenario.get("id"),
            "scenarioName": scenario.get("name") or "Scenario",
            "note": scenario.get("note") or "",
            "parameters": {
                "demandMultiplier": _multiplier(scenario, "demandMultiplier"),
                "supplyMultiplier": _multiplier(scenario, "supplyMultiplier"),
                "capacityMultiplier": _multiplier(scenario, "capacityMultiplier"),
                "routeCostMultiplier": _multiplier(scenario, "routeCostMultiplier"),
                "inventoryCostMultiplier": _multiplier(scenario, "inventoryCostMultiplier"),
            },
            "solverStatus": result.get("solverStatus"),
            "businessValidityStatus": result.get("businessValidityStatus"),
            "totalCost": scenario_cost,
            "costChangeVersusBase": None if base_cost is None or scenario_cost is None else scenario_cost - base_cost,
            "costChangePercent": None if not base_cost or scenario_cost is None else (scenario_cost - base_cost) / base_cost,
            "demandFulfilled": result.get("demandFulfilled", 0.0),
            "totalDemand": result.get("totalDemand", 0.0),
            "unmetDemand": result.get("unmetDemand", 0.0),
            "activeRoutes": result.get("activeRoutes", 0),
            "allocationTurnover": turnover,
            "bindingConstraintCount": len(bindings),
            "bindingConstraintChanges": sorted(bindings.symmetric_difference(base_bindings)),
            "supplierUtilization": result.get("supplierUtilization") or [],
            "feasible": bool(result.get("solverFeasible")),
            "businessValid": result.get("businessValidityStatus") == "valid",
            "evidenceStatus": "capturable" if result.get("businessValidityStatus") == "valid" else "blocked",
            "warnings": result.get("warnings") or [],
            "errors": result.get("errors") or [],
        })
    return {
        "available": True,
        "baseRunId": base_result.get("runId"),
        "baseResult": base_result,
        "results": results,
        "scenarioCount": len(results),
        "validScenarioCount": sum(row["businessValid"] for row in results),
        "infeasibleScenarioCount": sum(not row["feasible"] for row in results),
    }

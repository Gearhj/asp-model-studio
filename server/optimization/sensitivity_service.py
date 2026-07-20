from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .solver_service import solve_transportation_formulation
from .transportation_template_service import scaled_transportation_formulation


DRIVERS = (
    ("Route cost", "route_cost_multiplier"),
    ("Inventory cost", "inventory_cost_multiplier"),
    ("Demand", "demand_multiplier"),
    ("Supplier supply", "supply_multiplier"),
    ("Transport capacity", "capacity_multiplier"),
)


def _decision_map(result: dict[str, Any]) -> dict[str, float]:
    return {
        row["variableName"]: float(row["quantity"])
        for row in result.get("decisionVector") or []
    }


def run_transportation_sensitivity(
    formulation: dict[str, Any],
    solver: dict[str, Any] | None = None,
    perturbation_percent: float = 10.0,
) -> dict[str, Any]:
    base = solve_transportation_formulation(formulation, solver)
    if base.get("businessValidityStatus") != "valid":
        raise HTTPException(
            status_code=409,
            detail="Sensitivity analysis unavailable because the current solution is not business-valid.",
        )
    change = min(50.0, max(1.0, float(perturbation_percent))) / 100.0
    base_cost = float(base["totalCost"])
    base_decisions = _decision_map(base)
    base_bindings = {row["constraintName"] for row in base.get("bindingConstraints") or []}
    rows: list[dict[str, Any]] = []
    for driver_label, keyword in DRIVERS:
        for direction_label, multiplier in (("Decrease", 1.0 - change), ("Increase", 1.0 + change)):
            kwargs = {
                "demand_multiplier": 1.0,
                "supply_multiplier": 1.0,
                "capacity_multiplier": 1.0,
                "route_cost_multiplier": 1.0,
                "inventory_cost_multiplier": 1.0,
            }
            kwargs[keyword] = multiplier
            perturbed = scaled_transportation_formulation(formulation, **kwargs)
            result = solve_transportation_formulation(perturbed, solver)
            decisions = _decision_map(result)
            turnover = sum(
                abs(decisions.get(name, 0.0) - base_decisions.get(name, 0.0))
                for name in set(decisions) | set(base_decisions)
            ) / 2.0
            binding_names = {row["constraintName"] for row in result.get("bindingConstraints") or []}
            total_cost = result.get("totalCost")
            rows.append({
                "driver": driver_label,
                "direction": direction_label,
                "multiplier": multiplier,
                "baseTotalCost": base_cost,
                "perturbedTotalCost": total_cost,
                "costChange": None if total_cost is None else total_cost - base_cost,
                "costChangePercent": None if total_cost is None or not base_cost else (total_cost - base_cost) / base_cost,
                "activeRouteChange": int(result.get("activeRoutes", 0)) - int(base.get("activeRoutes", 0)),
                "allocationTurnover": turnover,
                "bindingConstraintChanges": sorted(binding_names.symmetric_difference(base_bindings)),
                "demandFulfilled": result.get("demandFulfilled", 0.0),
                "unmetDemand": result.get("unmetDemand", 0.0),
                "feasible": bool(result.get("solverFeasible")),
                "businessValid": result.get("businessValidityStatus") == "valid",
            })
    ranked = sorted(
        rows,
        key=lambda row: abs(float(row["costChange"])) if row["costChange"] is not None else float("inf"),
        reverse=True,
    )
    largest = next((row for row in ranked if row["costChange"] is not None), None)
    unavailable_shadow_prices = sum(not row.get("available") for row in base.get("shadowPrices") or [])
    return {
        "available": True,
        "baseRunId": base.get("runId"),
        "baseTotalCost": base_cost,
        "perturbationPercent": change * 100.0,
        "rows": rows,
        "tornado": ranked,
        "shadowPrices": base.get("shadowPrices") or [],
        "shadowPriceStatus": "available" if unavailable_shadow_prices == 0 else "partially_available",
        "allocationTurnover": [
            {"driver": row["driver"], "direction": row["direction"], "turnover": row["allocationTurnover"]}
            for row in rows
        ],
        "demandStress": [row for row in rows if row["driver"] == "Demand"],
        "capacityStress": [row for row in rows if row["driver"] in {"Supplier supply", "Transport capacity"}],
        "conclusion": (
            f"{largest['driver']} {largest['direction'].lower()} produced the largest tested cost movement."
            if largest
            else "No valid cost movement was available from the tested perturbations."
        ),
        "fragileAreas": [
            f"{row['driver']} {row['direction'].lower()}"
            for row in ranked
            if not row["businessValid"] or row["bindingConstraintChanges"]
        ],
    }

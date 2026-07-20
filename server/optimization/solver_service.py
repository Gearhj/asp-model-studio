from __future__ import annotations

from math import isfinite
from time import perf_counter
from typing import Any
from uuid import uuid4

import numpy as np
from fastapi import HTTPException
from scipy.optimize import linprog


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    return result if isfinite(result) else fallback


def _float_list(value: Any) -> list[float]:
    if value is None:
        return []
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return []


def _constraint_arrays(
    formulation: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]], list[dict[str, Any]]]:
    variables = formulation.get("variables") or []
    name_index = {variable["name"]: index for index, variable in enumerate(variables)}
    equalities: list[dict[str, Any]] = []
    inequalities: list[dict[str, Any]] = []
    equality_rows: list[list[float]] = []
    equality_rhs: list[float] = []
    inequality_rows: list[list[float]] = []
    inequality_rhs: list[float] = []
    for constraint in formulation.get("constraints") or []:
        row = [0.0] * len(variables)
        for variable_name, coefficient in (constraint.get("coefficients") or {}).items():
            if variable_name not in name_index:
                raise HTTPException(
                    status_code=422,
                    detail=f"Constraint '{constraint.get('name')}' references unknown route variable '{variable_name}'.",
                )
            row[name_index[variable_name]] = _number(coefficient)
        sense = constraint.get("sense", "<=")
        rhs = _number(constraint.get("rhs"))
        if sense == "=":
            equalities.append(constraint)
            equality_rows.append(row)
            equality_rhs.append(rhs)
        elif sense == "<=":
            inequalities.append(constraint)
            inequality_rows.append(row)
            inequality_rhs.append(rhs)
        elif sense == ">=":
            inequalities.append({**constraint, "_solverSign": -1})
            inequality_rows.append([-value for value in row])
            inequality_rhs.append(-rhs)
        else:
            raise HTTPException(status_code=422, detail=f"Unsupported constraint sense '{sense}'.")
    return (
        np.asarray(equality_rows, dtype=float) if equality_rows else np.empty((0, len(variables))),
        np.asarray(equality_rhs, dtype=float),
        np.asarray(inequality_rows, dtype=float) if inequality_rows else np.empty((0, len(variables))),
        np.asarray(inequality_rhs, dtype=float),
        equalities,
        inequalities,
    )


def _greedy_baseline(formulation: dict[str, Any]) -> dict[str, Any]:
    routes = formulation.get("routes") or []
    customers = formulation.get("customers") or []
    suppliers = formulation.get("suppliers") or []
    remaining = {
        supplier["supplier"]: min(_number(supplier.get("supply_max")), _number(supplier.get("transport_capacity")))
        for supplier in suppliers
    }
    quantities: dict[str, float] = {route["variable_name"]: 0.0 for route in routes}
    unmet = 0.0
    for customer in customers:
        needed = _number(customer.get("demand"))
        candidates = sorted(
            (route for route in routes if route.get("customer") == customer.get("customer") and route.get("active", True)),
            key=lambda route: _number(route.get("total_unit_cost"), float("inf")),
        )
        for route in candidates:
            available = max(0.0, remaining.get(route["supplier"], 0.0))
            allocation = min(needed, available)
            quantities[route["variable_name"]] += allocation
            remaining[route["supplier"]] = available - allocation
            needed -= allocation
            if needed <= 1e-9:
                break
        unmet += max(0.0, needed)
    total_cost = sum(
        quantities[route["variable_name"]] * _number(route.get("total_unit_cost"))
        for route in routes
    )
    return {"totalCost": float(total_cost), "unmetDemand": float(unmet), "quantities": quantities}


def _constraint_results(
    formulation: dict[str, Any],
    values: np.ndarray,
    equality_constraints: list[dict[str, Any]],
    inequality_constraints: list[dict[str, Any]],
    equality_marginals: list[float],
    inequality_marginals: list[float],
    tolerance: float,
) -> list[dict[str, Any]]:
    name_index = {variable["name"]: index for index, variable in enumerate(formulation["variables"])}
    marginal_by_id: dict[str, float | None] = {}
    for index, constraint in enumerate(equality_constraints):
        marginal_by_id[constraint["id"]] = equality_marginals[index] if index < len(equality_marginals) else None
    for index, constraint in enumerate(inequality_constraints):
        marginal = inequality_marginals[index] if index < len(inequality_marginals) else None
        marginal_by_id[constraint["id"]] = -marginal if constraint.get("_solverSign") == -1 and marginal is not None else marginal

    output: list[dict[str, Any]] = []
    for constraint in formulation.get("constraints") or []:
        lhs = sum(
            _number(coefficient) * float(values[name_index[name]])
            for name, coefficient in (constraint.get("coefficients") or {}).items()
        )
        rhs = _number(constraint.get("rhs"))
        sense = constraint.get("sense", "<=")
        slack = rhs - lhs if sense == "<=" else lhs - rhs if sense == ">=" else -abs(lhs - rhs)
        feasible = abs(lhs - rhs) <= tolerance if sense == "=" else slack >= -tolerance
        output.append({
            "constraintId": constraint.get("id"),
            "constraintName": constraint.get("name"),
            "constraintType": constraint.get("constraintType"),
            "category": constraint.get("category"),
            "entity": constraint.get("entity"),
            "lhs": float(lhs),
            "sense": sense,
            "rhs": rhs,
            "slack": float(slack),
            "binding": abs(slack) <= max(tolerance, 1e-7),
            "feasible": bool(feasible),
            "shadowPrice": marginal_by_id.get(constraint.get("id")),
            "sourceTable": constraint.get("sourceTable"),
        })
    return output


def _empty_result(formulation: dict[str, Any], *, status: int, message: str, runtime_ms: float) -> dict[str, Any]:
    total_demand = _number((formulation.get("metrics") or {}).get("totalDemand"))
    return {
        "runId": f"run-{uuid4().hex[:16]}",
        "solutionId": None,
        "formulationId": formulation.get("formulationId"),
        "solverStatus": "infeasible" if status == 2 else "failed",
        "solverStatusCode": status,
        "solverMessage": message,
        "solverFeasible": False,
        "formulationValid": bool(formulation.get("formulationReady")),
        "businessValidityStatus": "invalid",
        "decisionReadiness": "blocked",
        "success": False,
        "objectiveValue": None,
        "totalCost": None,
        "demandFulfilled": 0.0,
        "totalDemand": total_demand,
        "unmetDemand": total_demand,
        "activeRoutes": 0,
        "totalRoutes": len(formulation.get("routes") or []),
        "runtimeMs": runtime_ms,
        "optimalityGap": None,
        "decisionVector": [],
        "allocationMatrix": [],
        "constraintResults": [],
        "demandConstraintResults": [],
        "supplyConstraintResults": [],
        "transportConstraintResults": [],
        "bindingConstraints": [],
        "shadowPrices": [],
        "supplierUtilization": [],
        "customerFulfillment": [],
        "costBreakdown": {"bySupplier": [], "byCustomer": [], "byRoute": []},
        "baseline": _greedy_baseline(formulation),
        "warnings": [],
        "errors": [message],
    }


def solve_transportation_formulation(
    formulation: dict[str, Any],
    solver: dict[str, Any] | None = None,
) -> dict[str, Any]:
    solver = solver or {}
    if not formulation.get("formulationReady"):
        blockers = [
            check["detail"]
            for check in formulation.get("readinessChecks") or []
            if check.get("status") == "fail"
        ]
        detail = "Formulation incomplete. The solver is configured, but the model is not ready to run."
        if blockers:
            detail += " " + " ".join(blockers[:4])
        raise HTTPException(status_code=422, detail=detail)

    variables = formulation.get("variables") or []
    metrics = formulation.get("metrics") or {}
    if len(variables) != len(formulation.get("routes") or []) or not variables:
        raise HTTPException(status_code=422, detail="Invalid transportation formulation: route-level decision variables are missing.")
    if int(metrics.get("demandConstraintCount") or 0) == 0:
        raise HTTPException(status_code=422, detail="Invalid transportation formulation: demand fulfillment is not enforced.")

    tolerance = max(1e-9, _number(solver.get("tolerance"), 1e-7))
    time_limit = max(1.0, _number(solver.get("timeLimitSeconds"), 30.0))
    objective = np.asarray([_number(variable.get("objectiveCoefficient")) for variable in variables], dtype=float)
    lower = np.asarray([max(0.0, _number(variable.get("lowerBound"))) for variable in variables], dtype=float)
    upper = np.asarray([
        np.inf if variable.get("upperBound") is None else _number(variable.get("upperBound"))
        for variable in variables
    ], dtype=float)
    a_eq, b_eq, a_ub, b_ub, equalities, inequalities = _constraint_arrays(formulation)
    started = perf_counter()
    result = linprog(
        objective,
        A_ub=a_ub if len(a_ub) else None,
        b_ub=b_ub if len(b_ub) else None,
        A_eq=a_eq if len(a_eq) else None,
        b_eq=b_eq if len(b_eq) else None,
        bounds=list(zip(lower, upper)),
        method="highs",
        options={
            "time_limit": time_limit,
            "dual_feasibility_tolerance": tolerance,
            "primal_feasibility_tolerance": tolerance,
        },
    )
    runtime_ms = (perf_counter() - started) * 1000.0
    if not result.success or result.x is None:
        return _empty_result(
            formulation,
            status=int(result.status),
            message=str(result.message),
            runtime_ms=runtime_ms,
        )

    values = np.asarray(result.x, dtype=float)
    equality_marginals = _float_list(getattr(getattr(result, "eqlin", None), "marginals", None))
    inequality_marginals = _float_list(getattr(getattr(result, "ineqlin", None), "marginals", None))
    reduced_costs = _float_list(getattr(getattr(result, "lower", None), "marginals", None))
    constraint_results = _constraint_results(
        formulation,
        values,
        equalities,
        inequalities,
        equality_marginals,
        inequality_marginals,
        tolerance * 10,
    )
    route_by_name = {route["variable_name"]: route for route in formulation.get("routes") or []}
    decision_vector: list[dict[str, Any]] = []
    for index, variable in enumerate(variables):
        route = route_by_name[variable["name"]]
        quantity = max(0.0, float(values[index]))
        decision_vector.append({
            "variableName": variable["name"],
            "supplier": route["supplier"],
            "customer": route["customer"],
            "quantity": quantity,
            "transportationCost": _number(route.get("transportation_cost")),
            "inventoryCost": _number(route.get("inventory_cost")),
            "totalUnitCost": _number(route.get("total_unit_cost")),
            "costContribution": quantity * _number(route.get("total_unit_cost")),
            "lowerBound": _number(variable.get("lowerBound")),
            "upperBound": variable.get("upperBound"),
            "reducedCost": float(reduced_costs[index]) if index < len(reduced_costs) else None,
            "status": "active" if quantity > tolerance else "unused",
        })

    customers = formulation.get("customers") or []
    suppliers = formulation.get("suppliers") or []
    customer_fulfillment: list[dict[str, Any]] = []
    for customer in customers:
        supplied = sum(row["quantity"] for row in decision_vector if row["customer"] == customer["customer"])
        demand = _number(customer.get("demand"))
        customer_fulfillment.append({
            "customer": customer["customer"],
            "demand": demand,
            "supplied": supplied,
            "unmet": max(0.0, demand - supplied),
            "fulfillmentRate": supplied / demand if demand > 0 else 0.0,
        })
    supplier_utilization: list[dict[str, Any]] = []
    for supplier in suppliers:
        used = sum(row["quantity"] for row in decision_vector if row["supplier"] == supplier["supplier"])
        supply_max = _number(supplier.get("supply_max"))
        transport_capacity = _number(supplier.get("transport_capacity"))
        effective_capacity = min(supply_max, transport_capacity)
        supplier_utilization.append({
            "supplier": supplier["supplier"],
            "used": used,
            "supplyMax": supply_max,
            "transportCapacity": transport_capacity,
            "effectiveCapacity": effective_capacity,
            "supplyUtilization": used / supply_max if supply_max > 0 else 0.0,
            "transportUtilization": used / transport_capacity if transport_capacity > 0 else 0.0,
            "bindingLimit": "transport capacity" if transport_capacity <= supply_max else "supply maximum",
        })

    total_demand = sum(_number(customer.get("demand")) for customer in customers)
    fulfilled = sum(row["supplied"] for row in customer_fulfillment)
    unmet = sum(row["unmet"] for row in customer_fulfillment)
    total_cost = float(np.dot(objective, values))
    all_zero = bool(np.all(np.abs(values) <= tolerance))
    demand_compliant = all(row["unmet"] <= tolerance * 10 for row in customer_fulfillment)
    constraints_compliant = all(row["feasible"] for row in constraint_results)
    positive_cost_problem = total_demand > 0 and bool(np.any(objective > 0))
    objective_valid = not positive_cost_problem or total_cost > tolerance
    business_valid = (
        bool(result.success)
        and formulation.get("formulationReady")
        and demand_compliant
        and constraints_compliant
        and not (total_demand > 0 and all_zero)
        and objective_valid
    )
    errors: list[str] = []
    if total_demand > 0 and all_zero:
        errors.append(
            "Invalid formulation: demand fulfillment is not enforced. The solver found a zero-allocation solution, which is mathematically feasible but not operationally valid."
        )
    if not demand_compliant:
        errors.append("Business feasibility failed because customer demand is not fully satisfied.")
    if not constraints_compliant:
        errors.append("Business feasibility failed because one or more capacity constraints are violated.")
    if not objective_valid:
        errors.append("A zero objective is not valid for positive demand with positive route costs.")

    baseline = _greedy_baseline(formulation)
    active_routes = sum(row["quantity"] > tolerance for row in decision_vector)
    allocation_matrix = [
        {
            "customer": customer["customer"],
            "allocations": {
                supplier["supplier"]: next(
                    row["quantity"]
                    for row in decision_vector
                    if row["customer"] == customer["customer"] and row["supplier"] == supplier["supplier"]
                )
                for supplier in suppliers
            },
        }
        for customer in customers
    ]
    by_supplier = [
        {
            "supplier": supplier["supplier"],
            "cost": sum(row["costContribution"] for row in decision_vector if row["supplier"] == supplier["supplier"]),
        }
        for supplier in suppliers
    ]
    by_customer = [
        {
            "customer": customer["customer"],
            "cost": sum(row["costContribution"] for row in decision_vector if row["customer"] == customer["customer"]),
        }
        for customer in customers
    ]
    binding = [row for row in constraint_results if row["binding"]]
    solution_id = f"solution-{uuid4().hex[:16]}" if business_valid else None
    output = {
        "runId": f"run-{uuid4().hex[:16]}",
        "solutionId": solution_id,
        "formulationId": formulation.get("formulationId"),
        "solverStatus": "optimal" if result.success else "review_required",
        "solverStatusCode": int(result.status),
        "solverMessage": str(result.message),
        "solverFeasible": bool(result.success),
        "formulationValid": bool(formulation.get("formulationReady")),
        "businessValidityStatus": "valid" if business_valid else "invalid",
        "decisionReadiness": "ready" if business_valid else "blocked",
        "success": bool(business_valid),
        "objectiveValue": total_cost,
        "totalCost": total_cost,
        "demandFulfilled": fulfilled,
        "totalDemand": total_demand,
        "unmetDemand": unmet,
        "activeRoutes": active_routes,
        "totalRoutes": len(decision_vector),
        "runtimeMs": runtime_ms,
        "iterations": int(getattr(result, "nit", 0) or 0),
        "optimalityGap": 0.0 if result.success else None,
        "decisionVector": decision_vector,
        "allocationMatrix": allocation_matrix,
        "constraintResults": constraint_results,
        "demandConstraintResults": [row for row in constraint_results if row["constraintType"] == "demand"],
        "supplyConstraintResults": [row for row in constraint_results if row["constraintType"] == "supply"],
        "transportConstraintResults": [row for row in constraint_results if row["constraintType"] == "transport_capacity"],
        "bindingConstraints": binding,
        "shadowPrices": [
            {
                "constraintName": row["constraintName"],
                "constraintType": row["constraintType"],
                "shadowPrice": row["shadowPrice"],
                "available": row["shadowPrice"] is not None,
            }
            for row in constraint_results
        ],
        "supplierUtilization": supplier_utilization,
        "customerFulfillment": customer_fulfillment,
        "costBreakdown": {
            "bySupplier": by_supplier,
            "byCustomer": by_customer,
            "byRoute": sorted(decision_vector, key=lambda row: row["costContribution"], reverse=True),
        },
        "baseline": baseline,
        "improvementVersusBaseline": baseline["totalCost"] - total_cost if baseline["unmetDemand"] <= tolerance else None,
        "residualTransportCapacity": sum(max(0.0, row["transportCapacity"] - row["used"]) for row in supplier_utilization),
        "warnings": list(formulation.get("warnings") or []),
        "errors": errors,
    }
    output.update({
        "run_id": output["runId"],
        "formulation_id": output["formulationId"],
        "solver_status": output["solverStatus"],
        "business_validity_status": output["businessValidityStatus"],
        "objective_value": output["objectiveValue"],
        "total_cost": output["totalCost"],
        "demand_fulfilled": output["demandFulfilled"],
        "total_demand": output["totalDemand"],
        "unmet_demand": output["unmetDemand"],
        "active_routes": output["activeRoutes"],
        "total_routes": output["totalRoutes"],
        "runtime_ms": output["runtimeMs"],
        "optimality_gap": output["optimalityGap"],
        "decision_vector": output["decisionVector"],
        "allocation_matrix": output["allocationMatrix"],
    })
    return output

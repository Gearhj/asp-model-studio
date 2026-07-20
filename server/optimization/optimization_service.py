from __future__ import annotations

from math import isfinite
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException
from scipy.optimize import Bounds, LinearConstraint, linprog, milp, minimize

from ..datasets.dataset_registry import latest_version_id, require_dataset, version_dir


def _normalize(value: str) -> str:
    return "".join(character.lower() for character in str(value or "") if character.isalnum())


def _resolve_column(columns: list[str], requested: str, required: bool = False) -> str | None:
    if not requested:
        if required:
            raise HTTPException(status_code=422, detail="A required optimization column has not been mapped.")
        return None
    exact = {column: column for column in columns}
    normalized = {_normalize(column): column for column in columns}
    result = exact.get(requested) or normalized.get(_normalize(requested))
    if not result and required:
        raise HTTPException(status_code=422, detail=f"Mapped column '{requested}' was not found in the registered dataset version.")
    return result


def _dataset_artifact(dataset_id: str, version_id: str | None) -> tuple[dict[str, Any], str, Path]:
    dataset = require_dataset(dataset_id)
    resolved_version = version_id or latest_version_id(dataset)
    if not resolved_version:
        raise HTTPException(status_code=422, detail="The selected dataset has no registered full-data version.")
    path = version_dir(dataset_id, resolved_version) / "data_full.csv"
    if not path.exists():
        raise HTTPException(status_code=409, detail="Full dataset artifact is not loaded. Reopen or reload the confirmed dataset before optimization analysis.")
    return dataset, resolved_version, path


def _finite_number(value: Any, fallback: float = 0.0) -> float:
    try:
        result = float(value)
        return result if isfinite(result) else fallback
    except (TypeError, ValueError):
        return fallback


def profile_registered_optimization_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    dataset_id = str(payload.get("datasetId") or "").strip()
    if not dataset_id:
        raise HTTPException(status_code=422, detail="Select a registered dataset before profiling optimization inputs.")
    dataset, version_id, path = _dataset_artifact(dataset_id, payload.get("versionId"))
    header = pd.read_csv(path, nrows=0)
    columns = [str(column) for column in header.columns]
    mapping = payload.get("mapping") or {}
    resolved = {
        key: _resolve_column(columns, str(mapping.get(key) or ""), required=False)
        for key in [
            "itemColumn",
            "objectiveColumn",
            "lowerBoundColumn",
            "upperBoundColumn",
            "costColumn",
            "riskColumn",
            "groupColumn",
        ]
    }
    if not resolved["itemColumn"] or not resolved["objectiveColumn"]:
        raise HTTPException(status_code=422, detail="Map an item identifier and objective coefficient before profiling the full optimization artifact.")
    selected_columns = list(dict.fromkeys(column for column in resolved.values() if column))
    frame = pd.read_csv(path, usecols=selected_columns, low_memory=False)
    row_count = int(len(frame))
    duplicate_items = 0
    candidate_rows: list[dict[str, Any]] = []
    valid_count = 0
    item_column = resolved["itemColumn"]
    objective_column = resolved["objectiveColumn"]
    if item_column and objective_column:
        working = frame[[column for column in selected_columns if column in frame.columns]].copy()
        working = working[working[item_column].notna() & working[objective_column].notna()]
        working["__objective"] = pd.to_numeric(working[objective_column], errors="coerce")
        working = working[working["__objective"].notna()]
        duplicate_items = int(working.duplicated(subset=[item_column]).sum())
        working = working.drop_duplicates(subset=[item_column], keep="first")
        valid_count = int(len(working))
        for _, row in working.head(250).iterrows():
            lower = _finite_number(row.get(resolved["lowerBoundColumn"]), 0.0) if resolved["lowerBoundColumn"] else 0.0
            upper_value = row.get(resolved["upperBoundColumn"]) if resolved["upperBoundColumn"] else None
            upper = _finite_number(upper_value, lower + 1.0) if upper_value is not None and not pd.isna(upper_value) else lower + 1.0
            if upper < lower:
                lower, upper = upper, lower
            candidate_rows.append({
                "name": str(row[item_column]),
                "objectiveCoefficient": _finite_number(row["__objective"]),
                "lowerBound": lower,
                "upperBound": upper,
                "integer": False,
                "riskCoefficient": _finite_number(row.get(resolved["riskColumn"]), 0.0) if resolved["riskColumn"] else 0.0,
                "costCoefficient": _finite_number(row.get(resolved["costColumn"]), 0.0) if resolved["costColumn"] else 0.0,
                "group": str(row.get(resolved["groupColumn"], "")) if resolved["groupColumn"] else "",
            })
    numeric_summary: list[dict[str, Any]] = []
    for column in selected_columns:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        valid = numeric.dropna()
        numeric_summary.append({
            "column": column,
            "validCount": int(len(valid)),
            "missingCount": int(frame[column].isna().sum()),
            "mean": float(valid.mean()) if not valid.empty else None,
            "minimum": float(valid.min()) if not valid.empty else None,
            "maximum": float(valid.max()) if not valid.empty else None,
        })
    warnings: list[str] = []
    if duplicate_items:
        warnings.append(f"{duplicate_items:,} duplicate item rows were detected; the first row per item is shown until aggregation is reviewed.")
    if len(candidate_rows) == 250:
        warnings.append("The browser decision-variable preview is capped at 250 unique items. The full artifact remains registered for governed analysis.")
    return {
        "datasetId": dataset_id,
        "versionId": version_id,
        "datasetName": dataset.get("name") or dataset_id,
        "fullArtifact": True,
        "rowCount": row_count,
        "columnCount": len(columns),
        "columns": columns,
        "resolvedMapping": resolved,
        "validOptimizationRows": int(valid_count),
        "duplicateItems": duplicate_items,
        "numericSummary": numeric_summary,
        "candidateVariables": candidate_rows,
        "warnings": warnings,
    }


def _validated_problem(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    variables = payload.get("variables") or []
    constraints = payload.get("constraints") or []
    if not variables:
        raise HTTPException(status_code=422, detail="Define at least one decision variable before solving.")
    names = [str(variable.get("name") or "").strip() for variable in variables]
    if any(not name for name in names):
        raise HTTPException(status_code=422, detail="Every decision variable requires a name.")
    if len(set(names)) != len(names):
        raise HTTPException(status_code=422, detail="Decision variable names must be unique.")
    name_index = {name: index for index, name in enumerate(names)}
    for variable in variables:
        lower = _finite_number(variable.get("lowerBound"), 0.0)
        upper_raw = variable.get("upperBound")
        upper = None if upper_raw is None else _finite_number(upper_raw, lower)
        if upper is not None and upper < lower:
            raise HTTPException(status_code=422, detail=f"Upper bound is below lower bound for '{variable.get('name')}'.")
    for constraint in constraints:
        unknown = set((constraint.get("coefficients") or {}).keys()) - set(name_index)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Constraint '{constraint.get('name')}' references unknown variables: {', '.join(sorted(unknown))}.")
    return variables, constraints, name_index


def _constraint_arrays(constraints: list[dict[str, Any]], name_index: dict[str, int]) -> tuple[list[list[float]], list[float], list[list[float]], list[float]]:
    a_ub: list[list[float]] = []
    b_ub: list[float] = []
    a_eq: list[list[float]] = []
    b_eq: list[float] = []
    for constraint in constraints:
        row = [0.0] * len(name_index)
        for name, coefficient in (constraint.get("coefficients") or {}).items():
            row[name_index[name]] = _finite_number(coefficient)
        rhs = _finite_number(constraint.get("rhs"))
        sense = constraint.get("sense", "<=")
        if sense == "<=":
            a_ub.append(row)
            b_ub.append(rhs)
        elif sense == ">=":
            a_ub.append([-value for value in row])
            b_ub.append(-rhs)
        else:
            a_eq.append(row)
            b_eq.append(rhs)
    return a_ub, b_ub, a_eq, b_eq


def _constraint_review(constraints: list[dict[str, Any]], values: np.ndarray, name_index: dict[str, int], tolerance: float) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for constraint in constraints:
        lhs = sum(_finite_number(coefficient) * float(values[name_index[name]]) for name, coefficient in (constraint.get("coefficients") or {}).items())
        rhs = _finite_number(constraint.get("rhs"))
        sense = constraint.get("sense", "<=")
        slack = rhs - lhs if sense == "<=" else lhs - rhs if sense == ">=" else -abs(lhs - rhs)
        output.append({
            "name": constraint.get("name") or "Constraint",
            "sense": sense,
            "lhs": float(lhs),
            "rhs": float(rhs),
            "slack": float(slack),
            "binding": abs(slack) <= max(tolerance * 10, 1e-6),
            "feasible": slack >= -max(tolerance * 10, 1e-6),
        })
    return output


def solve_optimization_problem(payload: dict[str, Any]) -> dict[str, Any]:
    variables, constraints, name_index = _validated_problem(payload)
    direction = payload.get("direction", "Maximize")
    method = payload.get("method", "Linear programming (LP)")
    tolerance = max(1e-10, _finite_number(payload.get("tolerance"), 1e-7))
    time_limit = max(1.0, _finite_number(payload.get("timeLimitSeconds"), 30.0))
    risk_penalty = max(0.0, _finite_number(payload.get("riskPenalty"), 0.0))
    objective = np.asarray([_finite_number(variable.get("objectiveCoefficient")) for variable in variables], dtype=float)
    risk = np.asarray([max(0.0, _finite_number(variable.get("riskCoefficient"))) for variable in variables], dtype=float)
    lower = np.asarray([_finite_number(variable.get("lowerBound"), 0.0) for variable in variables], dtype=float)
    upper = np.asarray([
        np.inf if variable.get("upperBound") is None else _finite_number(variable.get("upperBound"), lower[index])
        for index, variable in enumerate(variables)
    ], dtype=float)
    baseline = lower.copy()
    a_ub, b_ub, a_eq, b_eq = _constraint_arrays(constraints, name_index)
    minimize_c = -objective if direction == "Maximize" else objective
    started = perf_counter()
    iterations = 0
    optimality_gap: float | None = None

    if method == "Linear programming (LP)":
        result = linprog(
            minimize_c,
            A_ub=np.asarray(a_ub) if a_ub else None,
            b_ub=np.asarray(b_ub) if b_ub else None,
            A_eq=np.asarray(a_eq) if a_eq else None,
            b_eq=np.asarray(b_eq) if b_eq else None,
            bounds=list(zip(lower, upper)),
            method="highs",
            options={"time_limit": time_limit, "dual_feasibility_tolerance": tolerance, "primal_feasibility_tolerance": tolerance},
        )
        values = np.asarray(result.x if result.x is not None else baseline, dtype=float)
        success = bool(result.success)
        message = str(result.message)
        iterations = int(getattr(result, "nit", 0) or 0)
        optimality_gap = 0.0 if success else None
        solver_status = int(result.status)
    elif method == "Mixed-integer programming (MILP)":
        matrix_rows: list[list[float]] = []
        matrix_lower: list[float] = []
        matrix_upper: list[float] = []
        for constraint in constraints:
            row = [0.0] * len(name_index)
            for name, coefficient in (constraint.get("coefficients") or {}).items():
                row[name_index[name]] = _finite_number(coefficient)
            rhs = _finite_number(constraint.get("rhs"))
            sense = constraint.get("sense", "<=")
            matrix_rows.append(row)
            matrix_lower.append(rhs if sense in {">=", "="} else -np.inf)
            matrix_upper.append(rhs if sense in {"<=", "="} else np.inf)
        linear_constraint = LinearConstraint(np.asarray(matrix_rows), np.asarray(matrix_lower), np.asarray(matrix_upper)) if matrix_rows else None
        result = milp(
            c=minimize_c,
            integrality=np.asarray([1 if variable.get("integer") else 0 for variable in variables], dtype=int),
            bounds=Bounds(lower, upper),
            constraints=linear_constraint,
            options={"time_limit": time_limit, "mip_rel_gap": max(tolerance, 1e-6)},
        )
        values = np.asarray(result.x if result.x is not None else baseline, dtype=float)
        success = bool(result.success)
        message = str(result.message)
        iterations = int(getattr(result, "mip_node_count", 0) or 0)
        gap_value = getattr(result, "mip_gap", None)
        optimality_gap = float(gap_value) if gap_value is not None and isfinite(float(gap_value)) else (0.0 if success else None)
        solver_status = int(result.status)
    else:
        def nonlinear_objective(values: np.ndarray) -> float:
            linear_value = float(np.dot(objective, values))
            penalty = float(risk_penalty * np.dot(risk, values * values))
            adjusted = linear_value - penalty if direction == "Maximize" else linear_value + penalty
            return -adjusted if direction == "Maximize" else adjusted

        scipy_constraints: list[dict[str, Any]] = []
        for constraint in constraints:
            coefficients = np.zeros(len(variables), dtype=float)
            for name, coefficient in (constraint.get("coefficients") or {}).items():
                coefficients[name_index[name]] = _finite_number(coefficient)
            rhs = _finite_number(constraint.get("rhs"))
            sense = constraint.get("sense", "<=")
            if sense == "<=":
                scipy_constraints.append({"type": "ineq", "fun": lambda x, a=coefficients, b=rhs: b - float(np.dot(a, x))})
            elif sense == ">=":
                scipy_constraints.append({"type": "ineq", "fun": lambda x, a=coefficients, b=rhs: float(np.dot(a, x)) - b})
            else:
                scipy_constraints.append({"type": "eq", "fun": lambda x, a=coefficients, b=rhs: float(np.dot(a, x)) - b})
        start = np.where(np.isfinite(upper), (lower + upper) / 2.0, lower + 1.0)
        result = minimize(
            nonlinear_objective,
            start,
            method="SLSQP",
            bounds=list(zip(lower, upper)),
            constraints=scipy_constraints,
            options={"ftol": tolerance, "maxiter": max(100, int(time_limit * 50))},
        )
        values = np.asarray(result.x if result.x is not None else baseline, dtype=float)
        success = bool(result.success)
        message = str(result.message)
        iterations = int(getattr(result, "nit", 0) or 0)
        solver_status = int(result.status)

    runtime_ms = (perf_counter() - started) * 1000.0
    constraint_review = _constraint_review(constraints, values, name_index, tolerance)
    feasible = all(row["feasible"] for row in constraint_review)
    gross_objective = float(np.dot(objective, values))
    baseline_gross_objective = float(np.dot(objective, baseline))
    risk_cost = float(risk_penalty * np.dot(risk, values * values))
    baseline_risk_cost = float(risk_penalty * np.dot(risk, baseline * baseline))
    adjusted_objective = gross_objective - risk_cost if direction == "Maximize" else gross_objective + risk_cost
    baseline_objective = baseline_gross_objective - baseline_risk_cost if direction == "Maximize" else baseline_gross_objective + baseline_risk_cost
    improvement = adjusted_objective - baseline_objective if direction == "Maximize" else baseline_objective - adjusted_objective
    decisions = [
        {
            "name": variable["name"],
            "value": float(values[index]),
            "lowerBound": float(lower[index]),
            "upperBound": None if not np.isfinite(upper[index]) else float(upper[index]),
            "objectiveContribution": float(objective[index] * values[index]),
            "riskContribution": float(risk_penalty * risk[index] * values[index] * values[index]),
            "integer": bool(variable.get("integer")),
            "group": str(variable.get("group") or ""),
        }
        for index, variable in enumerate(variables)
    ]
    decisions.sort(key=lambda row: abs(row["objectiveContribution"]), reverse=True)
    return {
        "success": bool(success and feasible),
        "solverSuccess": success,
        "feasible": feasible,
        "status": "optimal" if success and feasible else "review_required",
        "solverStatus": solver_status,
        "message": message,
        "method": method,
        "direction": direction,
        "objectiveValue": gross_objective,
        "riskAdjustedObjective": adjusted_objective,
        "baselineObjective": baseline_objective,
        "baselineGrossObjective": baseline_gross_objective,
        "improvement": improvement,
        "riskPenaltyCost": risk_cost,
        "runtimeMs": runtime_ms,
        "iterations": iterations,
        "optimalityGap": optimality_gap,
        "decisionCount": len(decisions),
        "constraintCount": len(constraint_review),
        "bindingConstraintCount": sum(1 for row in constraint_review if row["binding"]),
        "decisions": decisions,
        "constraints": constraint_review,
    }

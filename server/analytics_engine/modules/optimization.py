from __future__ import annotations

from typing import Any, Dict

from ..result_builder import result, table


def compute_optimization_diagnostics(payload: Dict[str, Any], context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    solution=payload.get("solution") or payload.get("result") or payload; constraints=solution.get("constraints") or []; decisions=solution.get("decisions") or []
    if not solution.get("status") and not decisions: return result("optimization_diagnostics",context,parameters,status="insufficient_data",warnings=["Stored solver output is required before optimization diagnostics can be calculated."])
    binding=[row for row in constraints if row.get("binding")]; infeasible=[row for row in constraints if row.get("feasible") is False]
    statistics={"solver_status":solution.get("status"),"feasible":solution.get("feasible"),"objective_value":solution.get("objectiveValue"),"baseline_objective":solution.get("baselineObjective"),"objective_improvement":solution.get("improvement"),"optimality_gap":solution.get("optimalityGap"),"binding_constraint_count":len(binding),"infeasible_constraint_count":len(infeasible),"decision_count":len(decisions)}
    warnings=[]
    if solution.get("optimalityGap") not in (None,0) : warnings.append("A non-zero optimality gap remains; review solver tolerance and time limit.")
    if infeasible: warnings.append("One or more constraints are infeasible in the stored solution.")
    return result("optimization_diagnostics",context,parameters,statistics=statistics,tables=[table("constraint_utilization","Constraint utilization",constraints),table("decision_contributions","Decision contributions",decisions)],warnings=warnings)

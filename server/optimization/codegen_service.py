from __future__ import annotations

import json
from typing import Any


def generate_transportation_code(formulation: dict[str, Any], stage: str = "formulation") -> dict[str, Any]:
    routes = formulation.get("routes") or []
    customers = formulation.get("customers") or []
    suppliers = formulation.get("suppliers") or []
    compact = {
        "formulation_id": formulation.get("formulationId"),
        "normalization_hash": formulation.get("normalizationHash"),
        "routes": [
            {
                "variable": route["variable_name"],
                "supplier": route["supplier"],
                "customer": route["customer"],
                "transport_cost": route.get("transportation_cost", 0.0),
                "inventory_cost": route.get("inventory_cost", 0.0),
                "unit_cost": route["total_unit_cost"],
                "active": route.get("active", True),
                "upper_bound": route.get("upper_bound"),
            }
            for route in routes
        ],
        "demand": {row["customer"]: row["demand"] for row in customers},
        "supply_max": {row["supplier"]: row["supply_max"] for row in suppliers},
        "transport_capacity": {row["supplier"]: row["transport_capacity"] for row in suppliers},
    }
    payload = json.dumps(compact, indent=2)
    python = '''# ATLAS transportation optimization: __STAGE__
# Executable reference implementation using the governed, normalized route model.
import json
import numpy as np
import pandas as pd
from scipy.optimize import linprog

model = json.loads(__MODEL_JSON__)


def normalize_wide_route_costs(cost_matrix, supplier_column="supplier"):
    """Convert a governed wide supplier-by-customer cost matrix to route grain."""
    customer_columns = [column for column in cost_matrix.columns if column != supplier_column]
    route_table = cost_matrix.melt(
        id_vars=[supplier_column],
        value_vars=customer_columns,
        var_name="customer",
        value_name="transport_cost",
    ).rename(columns={supplier_column: "supplier"})
    route_table["variable"] = "ship__" + route_table["supplier"].astype(str) + "__" + route_table["customer"].astype(str)
    return route_table


def load_governed_transportation_inputs(file_map):
    """Optional file loader. The embedded governed route model below remains runnable."""
    cost_matrix = pd.read_csv(file_map["transportation_cost"])
    demand = pd.read_csv(file_map["demand"])
    supply = pd.read_csv(file_map["supply_max"])
    capacity = pd.read_csv(file_map["transport_capacity"])
    inventory = pd.read_csv(file_map["inventory_cost"]) if file_map.get("inventory_cost") else None
    routes = normalize_wide_route_costs(cost_matrix)
    return routes, demand, supply, capacity, inventory


routes = pd.DataFrame(model["routes"])
routes["total_unit_cost"] = routes["transport_cost"].fillna(0.0) + routes["inventory_cost"].fillna(0.0)
routes["variable_name"] = routes["variable"]
customers = list(model["demand"])
suppliers = list(model["supply_max"])
c = routes["total_unit_cost"].to_numpy(dtype=float)

A_eq = []
b_eq = []
for customer in customers:
    A_eq.append((routes["customer"] == customer).astype(float).tolist())
    b_eq.append(model["demand"][customer])

A_ub = []
b_ub = []
inequality_names = []
for supplier in suppliers:
    row = (routes["supplier"] == supplier).astype(float).tolist()
    A_ub.append(row)
    b_ub.append(model["supply_max"][supplier])
    inequality_names.append(f"supply__{supplier}")
    A_ub.append(row)
    b_ub.append(model["transport_capacity"][supplier])
    inequality_names.append(f"transport_capacity__{supplier}")

bounds = [
    (0.0, None if bool(route.active) and pd.isna(route.upper_bound) else (float(route.upper_bound) if bool(route.active) else 0.0))
    for route in routes.itertuples(index=False)
]

result = linprog(
    c,
    A_ub=np.asarray(A_ub, dtype=float),
    b_ub=np.asarray(b_ub, dtype=float),
    A_eq=np.asarray(A_eq, dtype=float),
    b_eq=np.asarray(b_eq, dtype=float),
    bounds=bounds,
    method="highs",
    options={"dual_feasibility_tolerance": 1e-7, "primal_feasibility_tolerance": 1e-7},
)
if not result.success:
    raise RuntimeError(result.message)

allocation = routes.copy()
allocation["quantity"] = result.x
allocation["cost_contribution"] = allocation["quantity"] * allocation["total_unit_cost"]
allocation["status"] = np.where(allocation["quantity"] > 1e-7, "active", "unused")
allocation["reduced_cost"] = np.asarray(result.lower.marginals, dtype=float)

demand_fulfillment = allocation.groupby("customer", as_index=False)["quantity"].sum()
demand_fulfillment["required_demand"] = demand_fulfillment["customer"].map(model["demand"])
demand_fulfillment["unmet_demand"] = demand_fulfillment["required_demand"] - demand_fulfillment["quantity"]

supplier_utilization = allocation.groupby("supplier", as_index=False)["quantity"].sum()
supplier_utilization["supply_max"] = supplier_utilization["supplier"].map(model["supply_max"])
supplier_utilization["transport_capacity"] = supplier_utilization["supplier"].map(model["transport_capacity"])
supplier_utilization["supply_utilization"] = supplier_utilization["quantity"] / supplier_utilization["supply_max"]
supplier_utilization["transport_utilization"] = supplier_utilization["quantity"] / supplier_utilization["transport_capacity"]

constraint_diagnostics = pd.DataFrame({
    "constraint": inequality_names,
    "slack": np.asarray(result.ineqlin.residual, dtype=float),
    "shadow_price": np.asarray(result.ineqlin.marginals, dtype=float),
})
constraint_diagnostics["binding"] = constraint_diagnostics["slack"].abs() <= 1e-7
demand_shadow_prices = pd.DataFrame({
    "customer": customers,
    "shadow_price": np.asarray(result.eqlin.marginals, dtype=float),
    "slack": np.asarray(result.eqlin.residual, dtype=float),
})


def solve_variant(route_cost_multiplier=1.0, demand_multiplier=1.0, supply_multiplier=1.0, capacity_multiplier=1.0):
    variant = linprog(
        c * route_cost_multiplier,
        A_ub=np.asarray(A_ub, dtype=float),
        b_ub=np.asarray(b_ub, dtype=float) * np.tile([supply_multiplier, capacity_multiplier], len(suppliers)),
        A_eq=np.asarray(A_eq, dtype=float),
        b_eq=np.asarray(b_eq, dtype=float) * demand_multiplier,
        bounds=bounds,
        method="highs",
    )
    return {"success": bool(variant.success), "total_cost": float(variant.fun) if variant.success else None, "message": variant.message}


scenarios = {
    "baseline": solve_variant(),
    "demand_plus_10pct": solve_variant(demand_multiplier=1.10),
    "capacity_minus_10pct": solve_variant(capacity_multiplier=0.90),
    "route_cost_plus_10pct": solve_variant(route_cost_multiplier=1.10),
    "severe_disruption": solve_variant(supply_multiplier=0.70, capacity_multiplier=0.70),
}
sensitivity = []
for driver, parameter in [("route_cost", "route_cost_multiplier"), ("demand", "demand_multiplier"), ("supply", "supply_multiplier"), ("transport_capacity", "capacity_multiplier")]:
    for direction, multiplier in [("decrease", 0.90), ("increase", 1.10)]:
        sensitivity.append({"driver": driver, "direction": direction, "multiplier": multiplier, **solve_variant(**{parameter: multiplier})})

allocation.to_csv("atlas_transportation_allocation.csv", index=False)
evidence = {
    "formulation_id": model["formulation_id"],
    "normalization_hash": model["normalization_hash"],
    "status": result.message,
    "total_cost": float(result.fun),
    "active_routes": int((allocation["quantity"] > 1e-7).sum()),
    "route_variable_count": int(len(allocation)),
    "demand_constraint_count": int(len(A_eq)),
    "supply_constraint_count": int(len(suppliers)),
    "transport_capacity_constraint_count": int(len(suppliers)),
    "demand_fulfilled": float(allocation["quantity"].sum()),
    "unmet_demand": float(demand_fulfillment["unmet_demand"].sum()),
    "allocation_csv": "atlas_transportation_allocation.csv",
    "constraint_diagnostics": constraint_diagnostics.to_dict(orient="records"),
    "demand_shadow_prices": demand_shadow_prices.to_dict(orient="records"),
    "supplier_utilization": supplier_utilization.to_dict(orient="records"),
    "scenario_results": scenarios,
    "sensitivity_results": sensitivity,
}
with open("atlas_transportation_evidence.json", "w", encoding="utf-8") as evidence_file:
    json.dump(evidence, evidence_file, indent=2)
print(json.dumps(evidence, indent=2))
'''
    python = python.replace("__STAGE__", stage).replace("__MODEL_JSON__", repr(payload))
    supplier_set = " ".join(f"'{row['supplier']}'" for row in suppliers)
    customer_set = " ".join(f"'{row['customer']}'" for row in customers)
    cost_rows = "\n".join(
        f"cost['{route['supplier']}','{route['customer']}'] = {float(route['total_unit_cost']):.12g};"
        for route in routes
    )
    demand_rows = "\n".join(f"demand['{row['customer']}'] = {float(row['demand']):.12g};" for row in customers)
    supply_rows = "\n".join(f"supply['{row['supplier']}'] = {float(row['supply_max']):.12g};" for row in suppliers)
    capacity_rows = "\n".join(f"capacity['{row['supplier']}'] = {float(row['transport_capacity']):.12g};" for row in suppliers)
    sas = f'''/* ATLAS SAS-compatible transportation optimization template: {stage}
   Runtime status: Template-only. Execute in a licensed SAS environment or adapt with SASPy.
   The embedded values below reproduce formulation {formulation.get("formulationId")}. */

/* Optional governed source loading examples. Update file references in a licensed SAS environment. */
proc import datafile="transportation_cost.csv" out=transport_cost_wide dbms=csv replace; guessingrows=max; run;
proc import datafile="demand.csv" out=demand_input dbms=csv replace; guessingrows=max; run;
proc import datafile="supply_max.csv" out=supply_input dbms=csv replace; guessingrows=max; run;
proc import datafile="transport_capacity.csv" out=capacity_input dbms=csv replace; guessingrows=max; run;
proc import datafile="inventory_cost.csv" out=inventory_input dbms=csv replace; guessingrows=max; run;

/* Route-table construction template. Transpose the wide route matrix, then join supplier costs. */
proc transpose data=transport_cost_wide out=route_cost_long(rename=(_name_=customer col1=transport_cost));
   by supplier;
run;
proc sql;
   create table normalized_routes as
   select r.supplier, r.customer,
          cats('ship__', r.supplier, '__', r.customer) as variable_name length=128,
          r.transport_cost,
          coalesce(i.inventory_cost, 0) as inventory_cost,
          calculated transport_cost + calculated inventory_cost as total_unit_cost
   from route_cost_long r
   left join inventory_input i on r.supplier = i.supplier;
quit;

proc optmodel;
   set SUPPLIERS = {{{supplier_set}}};
   set CUSTOMERS = {{{customer_set}}};
   num cost {{SUPPLIERS, CUSTOMERS}};
   num demand {{CUSTOMERS}};
   num supply {{SUPPLIERS}};
   num capacity {{SUPPLIERS}};
   {cost_rows}
   {demand_rows}
   {supply_rows}
   {capacity_rows}

   var Ship {{SUPPLIERS, CUSTOMERS}} >= 0;
   min TotalCost = sum {{s in SUPPLIERS, c in CUSTOMERS}} cost[s,c] * Ship[s,c];
   con DemandFulfillment {{c in CUSTOMERS}}:
      sum {{s in SUPPLIERS}} Ship[s,c] = demand[c];
   con SupplyMaximum {{s in SUPPLIERS}}:
      sum {{c in CUSTOMERS}} Ship[s,c] <= supply[s];
   con TransportCapacity {{s in SUPPLIERS}}:
      sum {{c in CUSTOMERS}} Ship[s,c] <= capacity[s];
   solve with lp;
   create data atlas_transportation_allocation from
      [supplier customer] quantity=Ship
      transport_cost=cost
      cost_contribution=(cost[supplier,customer] * Ship[supplier,customer]);
   print TotalCost Ship;
quit;

proc export data=atlas_transportation_allocation
   outfile="atlas_transportation_allocation.csv" dbms=csv replace;
run;
'''
    return {
        "generatorVersion": "transportation-codegen-v2",
        "stage": stage,
        "formulationId": formulation.get("formulationId"),
        "python": {"code": python, "runtimeStatus": "Executable", "language": "Python"},
        "sas": {"code": sas, "runtimeStatus": "Template-only", "language": "SAS-compatible"},
        "references": {
            "normalizationHash": formulation.get("normalizationHash"),
            "variableCount": len(formulation.get("variables") or []),
            "constraintCount": len(formulation.get("constraints") or []),
        },
    }

from __future__ import annotations

import hashlib
import json
import re
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException

from .input_bundle_service import TRANSPORTATION_INPUT_LABELS, load_transportation_input_bundle


def normalize_name(value: Any) -> str:
    return "".join(character.lower() for character in str(value or "") if character.isalnum())


def safe_name(value: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_")
    return cleaned or "Unknown"


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _column_by_name(frame: pd.DataFrame, requested: str) -> str | None:
    normalized = {normalize_name(column): str(column) for column in frame.columns}
    return normalized.get(normalize_name(requested)) if requested else None


def detect_column(
    frame: pd.DataFrame,
    requested: str,
    patterns: tuple[str, ...],
    *,
    exclude: set[str] | None = None,
    numeric: bool | None = None,
) -> tuple[str, int]:
    excluded = {normalize_name(value) for value in (exclude or set())}
    requested_column = _column_by_name(frame, requested)
    if requested_column and normalize_name(requested_column) not in excluded:
        return requested_column, 100

    candidates = [str(column) for column in frame.columns if normalize_name(column) not in excluded]
    for pattern in patterns:
        for column in candidates:
            if re.search(pattern, normalize_name(column), flags=re.IGNORECASE):
                return column, 95

    if numeric is not None:
        typed: list[str] = []
        for column in candidates:
            converted = pd.to_numeric(frame[column], errors="coerce")
            ratio = float(converted.notna().mean()) if len(frame) else 0.0
            if (numeric and ratio >= 0.8) or (not numeric and ratio < 0.8):
                typed.append(column)
        if typed:
            return typed[0], 72
    if candidates:
        return candidates[0], 55
    raise HTTPException(status_code=422, detail="ATLAS could not detect a required transportation input column.")


def _key_value_columns(
    frame: pd.DataFrame,
    mapping: dict[str, Any],
    key_field: str,
    value_field: str,
    key_patterns: tuple[str, ...],
    value_patterns: tuple[str, ...],
) -> tuple[str, str, int]:
    key, key_confidence = detect_column(
        frame,
        str(mapping.get(key_field) or ""),
        key_patterns,
        numeric=False,
    )
    value, value_confidence = detect_column(
        frame,
        str(mapping.get(value_field) or ""),
        value_patterns,
        exclude={key},
        numeric=True,
    )
    return key, value, min(key_confidence, value_confidence)


def _lookup(frame: pd.DataFrame, key_column: str, value_column: str) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for _, row in frame.iterrows():
        raw_key = row.get(key_column)
        key = normalize_name(raw_key)
        if not key or key in output:
            continue
        output[key] = {
            "label": str(raw_key).strip(),
            "value": finite_number(row.get(value_column)),
        }
    return output


def _table_profile(
    role: str,
    frame: pd.DataFrame,
    metadata: dict[str, Any],
    key_columns: list[str],
    value_columns: list[str],
    confidence: int,
) -> dict[str, Any]:
    duplicate_keys = 0
    if key_columns:
        duplicate_keys = int(frame.duplicated(subset=key_columns, keep=False).sum())
    missing_values = int(frame.isna().sum().sum())
    invalid_values = 0
    for column in value_columns:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        invalid_values += int((frame[column].notna() & numeric.isna()).sum())
    status = "ready"
    if duplicate_keys or invalid_values:
        status = "review"
    if frame.empty or not key_columns or not value_columns:
        status = "blocked"
    return {
        **{key: value for key, value in metadata.items() if key != "path"},
        "role": role,
        "label": TRANSPORTATION_INPUT_LABELS[role],
        "keyColumns": key_columns,
        "valueColumns": value_columns,
        "missingValues": missing_values,
        "duplicateKeys": duplicate_keys,
        "invalidValues": invalid_values,
        "schemaConfidence": confidence,
        "profileStatus": status,
        "evidenceStatus": "capturable" if status == "ready" else "needs_review",
    }


def _readiness_check(check_id: str, label: str, passed: bool, detail: str, warning: bool = False) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "pass" if passed else ("warning" if warning else "fail"),
        "detail": detail,
    }


def _compile_formulation(
    routes: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    variables: list[dict[str, Any]] = []
    for route in routes:
        variables.append({
            "name": route["variable_name"],
            "objectiveCoefficient": route["total_unit_cost"],
            "lowerBound": 0.0,
            "upperBound": route.get("upper_bound"),
            "integer": False,
            "riskCoefficient": 0.0,
            "costCoefficient": route["transportation_cost"],
            "group": route["supplier"],
            "supplier": route["supplier"],
            "customer": route["customer"],
            "transportationCost": route["transportation_cost"],
            "inventoryCost": route["inventory_cost"],
            "totalUnitCost": route["total_unit_cost"],
            "active": bool(route.get("active", True)),
        })

    constraints: list[dict[str, Any]] = []
    for customer in customers:
        coefficients = {
            route["variable_name"]: 1.0
            for route in routes
            if route["customer"] == customer["customer"]
        }
        constraints.append({
            "id": f"demand-{safe_name(customer['customer'])}",
            "name": f"Demand fulfillment: {customer['customer']}",
            "constraintType": "demand",
            "category": "Service",
            "coefficients": coefficients,
            "sense": "=",
            "rhs": customer["demand"],
            "hard": True,
            "sourceTable": "Demand table",
            "entity": customer["customer"],
        })
    for supplier in suppliers:
        coefficients = {
            route["variable_name"]: 1.0
            for route in routes
            if route["supplier"] == supplier["supplier"]
        }
        constraints.append({
            "id": f"supply-{safe_name(supplier['supplier'])}",
            "name": f"Supply maximum: {supplier['supplier']}",
            "constraintType": "supply",
            "category": "Capacity",
            "coefficients": coefficients,
            "sense": "<=",
            "rhs": supplier["supply_max"],
            "hard": True,
            "sourceTable": "Supply maximum table",
            "entity": supplier["supplier"],
        })
        constraints.append({
            "id": f"transport-{safe_name(supplier['supplier'])}",
            "name": f"Transport capacity: {supplier['supplier']}",
            "constraintType": "transport_capacity",
            "category": "Capacity",
            "coefficients": coefficients,
            "sense": "<=",
            "rhs": supplier["transport_capacity"],
            "hard": True,
            "sourceTable": "Transportation capacity table",
            "entity": supplier["supplier"],
        })

    equality = [constraint for constraint in constraints if constraint["sense"] == "="]
    inequality = [constraint for constraint in constraints if constraint["sense"] != "="]
    inspector = {
        "variableIndex": [variable["name"] for variable in variables],
        "objectiveVector": [variable["objectiveCoefficient"] for variable in variables],
        "lowerBounds": [variable["lowerBound"] for variable in variables],
        "upperBounds": [variable["upperBound"] for variable in variables],
        "equalityConstraintCount": len(equality),
        "inequalityConstraintCount": len(inequality),
        "equalityConstraintNames": [constraint["name"] for constraint in equality],
        "inequalityConstraintNames": [constraint["name"] for constraint in inequality],
        "equalityRhs": [constraint["rhs"] for constraint in equality],
        "inequalityRhs": [constraint["rhs"] for constraint in inequality],
        "nonZeroEqualityCoefficients": sum(len(constraint["coefficients"]) for constraint in equality),
        "nonZeroInequalityCoefficients": sum(len(constraint["coefficients"]) for constraint in inequality),
    }
    return variables, constraints, inspector


def normalize_transportation_frames(
    frames: dict[str, pd.DataFrame],
    mapping: dict[str, Any] | None = None,
    metadata: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    required_roles = ("transportationCost", "demand", "supplyMax", "transportCapacity")
    missing_roles = [role for role in required_roles if role not in frames]
    if missing_roles:
        raise HTTPException(
            status_code=422,
            detail=f"Transportation input bundle is incomplete. Missing required table roles: {', '.join(missing_roles)}.",
        )
    mapping = mapping or {}
    table_metadata = {item["role"]: item for item in (metadata or [])}
    cost_frame = frames["transportationCost"].copy()
    demand_frame = frames["demand"].copy()
    supply_frame = frames["supplyMax"].copy()
    capacity_frame = frames["transportCapacity"].copy()
    inventory_supplied = "inventoryCost" in frames
    inventory_frame = frames["inventoryCost"].copy() if inventory_supplied else None

    customer_column, cost_key_confidence = detect_column(
        cost_frame,
        str(mapping.get("costCustomerColumn") or ""),
        (r"customer", r"destination", r"demandlocation", r"location"),
        numeric=False,
    )
    requested_cost_supplier = str(mapping.get("costSupplierColumn") or "")
    requested_cost_value = str(mapping.get("costValueColumn") or "")
    named_supplier_column = next(
        (
            str(column)
            for column in cost_frame.columns
            if re.search(r"^(supplier|source|origin)(id|key|name)?$", normalize_name(column))
        ),
        "",
    )
    named_route_cost_column = next(
        (
            str(column)
            for column in cost_frame.columns
            if re.search(r"(route|transportation|transport|shipping)cost|^cost$", normalize_name(column))
        ),
        "",
    )
    long_route_format = bool(
        (requested_cost_supplier and requested_cost_value)
        or (named_supplier_column and named_route_cost_column)
    )
    cost_supplier_column = ""
    cost_value_column = ""
    cost_profile_keys: list[str]
    cost_profile_values: list[str]
    duplicate_route_count = 0
    if long_route_format:
        cost_supplier_column, supplier_confidence = detect_column(
            cost_frame,
            requested_cost_supplier,
            (r"supplier", r"source", r"origin"),
            exclude={customer_column},
            numeric=False,
        )
        cost_value_column, value_confidence = detect_column(
            cost_frame,
            requested_cost_value,
            (r"routecost", r"transportationcost", r"transportcost", r"shippingcost", r"cost"),
            exclude={customer_column, cost_supplier_column},
            numeric=True,
        )
        cost_key_confidence = min(cost_key_confidence, supplier_confidence, value_confidence)
        supplier_columns = list(dict.fromkeys(
            str(value).strip()
            for value in cost_frame[cost_supplier_column].tolist()
            if str(value).strip()
        ))
        duplicate_route_count = int(
            len(cost_frame)
            - cost_frame[[cost_supplier_column, customer_column]].drop_duplicates().shape[0]
        )
        cost_profile_keys = [cost_supplier_column, customer_column]
        cost_profile_values = [cost_value_column]
    else:
        supplier_columns = [str(column) for column in cost_frame.columns if str(column) != customer_column]
        cost_profile_keys = [customer_column]
        cost_profile_values = supplier_columns
    if not supplier_columns:
        raise HTTPException(status_code=422, detail="The route cost input does not contain supplier routes.")

    demand_key, demand_value, demand_confidence = _key_value_columns(
        demand_frame,
        mapping,
        "demandCustomerColumn",
        "demandValueColumn",
        (r"customer", r"destination", r"location"),
        (r"demand", r"required", r"quantity", r"volume", r"amount"),
    )
    supply_key, supply_value, supply_confidence = _key_value_columns(
        supply_frame,
        mapping,
        "supplySupplierColumn",
        "supplyValueColumn",
        (r"supplier", r"source", r"origin", r"location"),
        (r"supplymax", r"maximumsupply", r"supply", r"available", r"capacity"),
    )
    capacity_key, capacity_value, capacity_confidence = _key_value_columns(
        capacity_frame,
        mapping,
        "capacitySupplierColumn",
        "capacityValueColumn",
        (r"supplier", r"source", r"origin", r"location"),
        (r"transportcapacity", r"shippingcapacity", r"capacity", r"throughput"),
    )
    inventory_key = ""
    inventory_value = ""
    inventory_confidence = 100
    if inventory_frame is not None:
        inventory_key, inventory_value, inventory_confidence = _key_value_columns(
            inventory_frame,
            mapping,
            "inventorySupplierColumn",
            "inventoryValueColumn",
            (r"supplier", r"source", r"origin", r"location"),
            (r"inventorycost", r"handlingcost", r"holdingcost", r"cost"),
        )

    demand_lookup = _lookup(demand_frame, demand_key, demand_value)
    supply_lookup = _lookup(supply_frame, supply_key, supply_value)
    capacity_lookup = _lookup(capacity_frame, capacity_key, capacity_value)
    inventory_lookup = _lookup(inventory_frame, inventory_key, inventory_value) if inventory_frame is not None else {}

    raw_customers = [str(value).strip() for value in cost_frame[customer_column].tolist() if str(value).strip()]
    duplicate_customer_count = 0 if long_route_format else len(raw_customers) - len({normalize_name(value) for value in raw_customers})
    customers: list[dict[str, Any]] = []
    seen_customers: set[str] = set()
    for customer in raw_customers:
        key = normalize_name(customer)
        if key in seen_customers:
            continue
        seen_customers.add(key)
        customers.append({"customer": customer, "demand": (demand_lookup.get(key) or {}).get("value")})

    suppliers: list[dict[str, Any]] = []
    for supplier in supplier_columns:
        key = normalize_name(supplier)
        suppliers.append({
            "supplier": supplier,
            "supply_max": (supply_lookup.get(key) or {}).get("value"),
            "transport_capacity": (capacity_lookup.get(key) or {}).get("value"),
            "inventory_cost": (inventory_lookup.get(key) or {}).get("value") if inventory_supplied else 0.0,
        })

    rows_by_customer: dict[str, pd.Series] = {}
    route_cost_lookup: dict[tuple[str, str], float | None] = {}
    for _, row in cost_frame.iterrows():
        customer_key = normalize_name(row.get(customer_column))
        if not customer_key:
            continue
        if long_route_format:
            supplier_key = normalize_name(row.get(cost_supplier_column))
            if supplier_key and (supplier_key, customer_key) not in route_cost_lookup:
                route_cost_lookup[(supplier_key, customer_key)] = finite_number(row.get(cost_value_column))
        elif customer_key not in rows_by_customer:
            rows_by_customer[customer_key] = row

    routes: list[dict[str, Any]] = []
    for supplier in supplier_columns:
        supplier_record = next(item for item in suppliers if item["supplier"] == supplier)
        for customer_record in customers:
            customer = customer_record["customer"]
            row = rows_by_customer.get(normalize_name(customer))
            transportation_cost = (
                route_cost_lookup.get((normalize_name(supplier), normalize_name(customer)))
                if long_route_format
                else finite_number(row.get(supplier)) if row is not None else None
            )
            inventory_cost = supplier_record["inventory_cost"]
            total_unit_cost = None
            if transportation_cost is not None and inventory_cost is not None:
                total_unit_cost = transportation_cost + inventory_cost
            variable_name = f"x_{safe_name(supplier)}_{safe_name(customer)}"
            routes.append({
                "route_id": f"route_{safe_name(supplier)}_{safe_name(customer)}",
                "supplier": supplier,
                "customer": customer,
                "transportation_cost": transportation_cost,
                "demand": customer_record["demand"],
                "supply_max": supplier_record["supply_max"],
                "transport_capacity": supplier_record["transport_capacity"],
                "inventory_cost": inventory_cost,
                "total_unit_cost": total_unit_cost,
                "lower_bound": 0.0,
                "upper_bound": None,
                "variable_name": variable_name,
                "active": True,
                "source_tables": [
                    "Route cost matrix",
                    "Demand table",
                    "Supply maximum table",
                    "Transportation capacity table",
                ] + (["Inventory or handling cost table"] if inventory_supplied else []),
            })

    missing_route_costs = sum(route["transportation_cost"] is None for route in routes)
    negative_route_costs = sum(
        route["transportation_cost"] is not None and route["transportation_cost"] < 0
        for route in routes
    )
    customers_without_demand = [item["customer"] for item in customers if item["demand"] is None]
    suppliers_without_supply = [item["supplier"] for item in suppliers if item["supply_max"] is None]
    suppliers_without_capacity = [item["supplier"] for item in suppliers if item["transport_capacity"] is None]
    suppliers_without_inventory = [item["supplier"] for item in suppliers if inventory_supplied and item["inventory_cost"] is None]
    invalid_demand = [item["customer"] for item in customers if item["demand"] is not None and item["demand"] < 0]
    invalid_supply = [item["supplier"] for item in suppliers if item["supply_max"] is not None and item["supply_max"] < 0]
    invalid_capacity = [item["supplier"] for item in suppliers if item["transport_capacity"] is not None and item["transport_capacity"] < 0]

    total_demand = float(sum(item["demand"] or 0.0 for item in customers))
    total_supply = float(sum(item["supply_max"] or 0.0 for item in suppliers))
    total_capacity = float(sum(item["transport_capacity"] or 0.0 for item in suppliers))
    duplicate_routes = duplicate_route_count + len(routes) - len({route["route_id"] for route in routes})

    checks = [
        _readiness_check("customers_have_demand", "Every customer has demand", not customers_without_demand, f"{len(customers_without_demand)} customer(s) missing demand."),
        _readiness_check("suppliers_have_supply", "Every supplier has a supply maximum", not suppliers_without_supply, f"{len(suppliers_without_supply)} supplier(s) missing supply."),
        _readiness_check("suppliers_have_capacity", "Every supplier has transportation capacity", not suppliers_without_capacity, f"{len(suppliers_without_capacity)} supplier(s) missing capacity."),
        _readiness_check(
            "suppliers_have_inventory",
            "Inventory or handling cost policy",
            not suppliers_without_inventory,
            (
                f"{len(suppliers_without_inventory)} supplier(s) missing inventory cost."
                if inventory_supplied
                else "Inventory or handling cost was not supplied. The objective will use route transportation cost only."
            ),
        ),
        _readiness_check("route_costs_complete", "Route transportation costs are complete", missing_route_costs == 0, f"{missing_route_costs} route cost(s) are missing."),
        _readiness_check("route_costs_valid", "Route costs are nonnegative", negative_route_costs == 0, f"{negative_route_costs} route cost(s) are negative."),
        _readiness_check("keys_unique", "Customer and supplier keys are unique", duplicate_customer_count == 0 and duplicate_routes == 0, f"{duplicate_customer_count} duplicate customer row(s); {duplicate_routes} duplicate route(s)."),
        _readiness_check("demand_positive", "Demand is positive and valid", total_demand > 0 and not invalid_demand, f"Total demand is {total_demand:g}."),
        _readiness_check("supply_feasible", "Supply maximum covers demand", total_supply >= total_demand and not invalid_supply, f"Supply {total_supply:g} versus demand {total_demand:g}."),
        _readiness_check("capacity_feasible", "Transportation capacity covers demand", total_capacity >= total_demand and not invalid_capacity, f"Transport capacity {total_capacity:g} versus demand {total_demand:g}."),
    ]
    formulation_ready = all(check["status"] == "pass" for check in checks)

    valid_routes = [route for route in routes if route["total_unit_cost"] is not None]
    variables, constraints, inspector = _compile_formulation(valid_routes, customers, suppliers)
    normalization_payload = [
        [
            route["route_id"],
            route["transportation_cost"],
            route["inventory_cost"],
            route["demand"],
            route["supply_max"],
            route["transport_capacity"],
        ]
        for route in routes
    ]
    normalization_hash = hashlib.sha256(
        json.dumps(normalization_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    formulation_id = f"transport-{normalization_hash[:16]}"

    profile_specs = {
        "transportationCost": (cost_frame, cost_profile_keys, cost_profile_values, cost_key_confidence),
        "demand": (demand_frame, [demand_key], [demand_value], demand_confidence),
        "supplyMax": (supply_frame, [supply_key], [supply_value], supply_confidence),
        "transportCapacity": (capacity_frame, [capacity_key], [capacity_value], capacity_confidence),
    }
    if inventory_frame is not None:
        profile_specs["inventoryCost"] = (inventory_frame, [inventory_key], [inventory_value], inventory_confidence)
    input_tables = []
    for role, (frame, key_columns, value_columns, confidence) in profile_specs.items():
        input_tables.append(
            _table_profile(
                role,
                frame,
                table_metadata.get(role, {"role": role, "fullArtifact": bool(metadata)}),
                key_columns,
                value_columns,
                confidence,
            )
        )
    duplicate_input_keys = sum(int(table["duplicateKeys"]) for table in input_tables)
    if duplicate_input_keys:
        checks.append(
            _readiness_check(
                "input_keys_unique",
                "Input-table keys are unique",
                False,
                f"{duplicate_input_keys} duplicate key row(s) require correction.",
            )
        )
        formulation_ready = False
    resolved_mapping = {
        "costShape": "long_route_table" if long_route_format else "wide_matrix",
        "costCustomerColumn": customer_column,
        "costSupplierColumns": supplier_columns,
        "costSupplierColumn": cost_supplier_column,
        "costValueColumn": cost_value_column,
        "demandCustomerColumn": demand_key,
        "demandValueColumn": demand_value,
        "supplySupplierColumn": supply_key,
        "supplyValueColumn": supply_value,
        "capacitySupplierColumn": capacity_key,
        "capacityValueColumn": capacity_value,
        "inventorySupplierColumn": inventory_key,
        "inventoryValueColumn": inventory_value,
    }
    warnings: list[str] = []
    if not inventory_supplied:
        warnings.append("Inventory or handling cost was not supplied. The objective will use route transportation cost only.")
    if total_supply > total_demand and total_capacity < total_supply:
        warnings.append("Transportation capacity is the tighter feasibility limit, not supplier supply maximum.")
    if not formulation_ready:
        warnings.append("Formulation incomplete. The solver is configured, but the model is not ready to run.")

    return {
        "template": "transportation_logistics",
        "formulationId": formulation_id,
        "formulationVersion": "1.0",
        "normalizationHash": normalization_hash,
        "fullArtifact": bool(metadata),
        "inputTables": input_tables,
        "resolvedMapping": resolved_mapping,
        "customers": customers,
        "suppliers": suppliers,
        "routes": routes,
        "variables": variables,
        "constraints": constraints,
        "inspector": inspector,
        "objective": {
            "direction": "Minimize",
            "name": "Minimize total cash distribution cost",
            "unit": "Total distribution cost per planning period",
            "horizon": "One planning period",
            "expression": (
                "min sum(supplier, customer) x_supplier_customer * (transportation_cost_supplier_customer + inventory_cost_supplier)"
                if inventory_supplied
                else "min sum(supplier, customer) x_supplier_customer * transportation_cost_supplier_customer"
            ),
            "plainEnglish": (
                "ATLAS minimizes total distribution cost by choosing how much each supplier sends to each customer. Each route quantity is multiplied by route transportation cost plus supplier inventory or handling cost."
                if inventory_supplied
                else "ATLAS minimizes total distribution cost by choosing how much each supplier sends to each customer. Inventory or handling cost was not supplied, so each route quantity is multiplied by route transportation cost only."
            ),
        },
        "metrics": {
            "customerCount": len(customers),
            "supplierCount": len(suppliers),
            "routeCount": len(routes),
            "decisionVariableCount": len(variables),
            "demandConstraintCount": len(customers),
            "supplyConstraintCount": len(suppliers),
            "transportConstraintCount": len(suppliers),
            "nonNegativityBoundCount": len(variables),
            "routeUpperBoundCount": sum(route["upper_bound"] is not None for route in routes),
            "totalDemand": total_demand,
            "totalSupplyMax": total_supply,
            "totalTransportCapacity": total_capacity,
            "missingRouteCosts": missing_route_costs,
            "negativeRouteCosts": negative_route_costs,
            "duplicateRoutes": duplicate_routes,
            "customersWithoutDemand": len(customers_without_demand),
            "suppliersWithoutSupply": len(suppliers_without_supply),
            "suppliersWithoutCapacity": len(suppliers_without_capacity),
            "suppliersWithoutInventoryCost": len(suppliers_without_inventory),
            "inventoryCostSupplied": inventory_supplied,
        },
        "readinessChecks": checks,
        "formulationReady": formulation_ready,
        "formulationStatus": "ready" if formulation_ready else "blocked",
        "warnings": warnings,
    }


def build_transportation_formulation(payload: dict[str, Any]) -> dict[str, Any]:
    frames, metadata = load_transportation_input_bundle(payload)
    formulation = normalize_transportation_frames(frames, payload.get("mapping") or {}, metadata)
    route_overrides = payload.get("routeOverrides") or {}
    for route in formulation["routes"]:
        active = bool(route_overrides.get(route["route_id"], True))
        route["active"] = active
        route["upper_bound"] = None if active else 0.0
    variables, constraints, inspector = _compile_formulation(
        formulation["routes"], formulation["customers"], formulation["suppliers"]
    )
    variable_names = {variable["name"] for variable in variables}
    custom_constraints: list[dict[str, Any]] = []
    for index, custom in enumerate(payload.get("customConstraints") or []):
        coefficients = {
            str(name): float(value)
            for name, value in (custom.get("coefficients") or {}).items()
            if str(name) in variable_names and finite_number(value) is not None
        }
        if not coefficients:
            continue
        sense = custom.get("sense") if custom.get("sense") in {"<=", ">=", "="} else "<="
        custom_constraints.append({
            "id": str(custom.get("id") or f"custom-{index + 1}"),
            "name": str(custom.get("name") or f"Custom constraint {index + 1}"),
            "constraintType": "custom",
            "category": str(custom.get("category") or "Policy"),
            "coefficients": coefficients,
            "sense": sense,
            "rhs": float(custom.get("rhs") or 0.0),
            "hard": True,
            "sourceTable": "Reviewer-defined executable rule",
            "entity": "Custom",
        })
    constraints.extend(custom_constraints)
    inspector["inequalityConstraintCount"] += sum(row["sense"] != "=" for row in custom_constraints)
    inspector["equalityConstraintCount"] += sum(row["sense"] == "=" for row in custom_constraints)
    inspector["inequalityConstraintNames"].extend(row["name"] for row in custom_constraints if row["sense"] != "=")
    inspector["equalityConstraintNames"].extend(row["name"] for row in custom_constraints if row["sense"] == "=")
    formulation["variables"] = variables
    formulation["constraints"] = constraints
    formulation["inspector"] = inspector
    formulation["metrics"]["activeRouteCount"] = sum(route["active"] for route in formulation["routes"])
    formulation["metrics"]["routeUpperBoundCount"] = sum(route["upper_bound"] is not None for route in formulation["routes"])
    formulation["metrics"]["customConstraintCount"] = len(custom_constraints)
    return formulation


def scaled_transportation_formulation(
    formulation: dict[str, Any],
    *,
    demand_multiplier: float = 1.0,
    supply_multiplier: float = 1.0,
    capacity_multiplier: float = 1.0,
    route_cost_multiplier: float = 1.0,
    inventory_cost_multiplier: float = 1.0,
) -> dict[str, Any]:
    cloned = json.loads(json.dumps(formulation))
    for customer in cloned["customers"]:
        customer["demand"] *= demand_multiplier
    for supplier in cloned["suppliers"]:
        supplier["supply_max"] *= supply_multiplier
        supplier["transport_capacity"] *= capacity_multiplier
        supplier["inventory_cost"] *= inventory_cost_multiplier
    supplier_map = {item["supplier"]: item for item in cloned["suppliers"]}
    customer_map = {item["customer"]: item for item in cloned["customers"]}
    for route in cloned["routes"]:
        route["transportation_cost"] *= route_cost_multiplier
        route["inventory_cost"] = supplier_map[route["supplier"]]["inventory_cost"]
        route["total_unit_cost"] = route["transportation_cost"] + route["inventory_cost"]
        route["demand"] = customer_map[route["customer"]]["demand"]
        route["supply_max"] = supplier_map[route["supplier"]]["supply_max"]
        route["transport_capacity"] = supplier_map[route["supplier"]]["transport_capacity"]
    variables, constraints, inspector = _compile_formulation(cloned["routes"], cloned["customers"], cloned["suppliers"])
    cloned["variables"] = variables
    cloned["constraints"] = constraints
    cloned["inspector"] = inspector
    cloned["metrics"].update({
        "totalDemand": float(sum(item["demand"] for item in cloned["customers"])),
        "totalSupplyMax": float(sum(item["supply_max"] for item in cloned["suppliers"])),
        "totalTransportCapacity": float(sum(item["transport_capacity"] for item in cloned["suppliers"])),
    })
    cloned["aggregateFeasibility"] = (
        cloned["metrics"]["totalDemand"] > 0
        and cloned["metrics"]["totalSupplyMax"] >= cloned["metrics"]["totalDemand"]
        and cloned["metrics"]["totalTransportCapacity"] >= cloned["metrics"]["totalDemand"]
    )
    cloned["formulationReady"] = (
        cloned["metrics"]["totalDemand"] > 0
        and cloned["metrics"]["missingRouteCosts"] == 0
        and bool(cloned.get("variables"))
        and bool(cloned.get("constraints"))
    )
    cloned["formulationStatus"] = (
        "ready" if cloned["aggregateFeasibility"] else "ready_with_feasibility_warning"
    )
    return cloned

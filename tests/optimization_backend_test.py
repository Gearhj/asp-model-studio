from __future__ import annotations

import unittest
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.optimization import optimization_service as service
from server.optimization.codegen_service import generate_transportation_code
from server.optimization.scenario_service import run_transportation_scenarios
from server.optimization.sensitivity_service import run_transportation_sensitivity
from server.optimization.solver_service import solve_transportation_formulation
from server.optimization.transportation_template_service import normalize_transportation_frames
from server.optimization.validation_service import validate_transportation_decision
from server.evidence import evidence_store


class OptimizationBackendTest(unittest.TestCase):
    @staticmethod
    def transportation_frames() -> dict[str, pd.DataFrame]:
        fixture_dir = Path(__file__).parent / "fixtures" / "optimization"
        return {
            "transportationCost": pd.read_csv(fixture_dir / "date_transportation_cost.csv"),
            "demand": pd.read_csv(fixture_dir / "date_demand.csv"),
            "supplyMax": pd.read_csv(fixture_dir / "date_supply_max.csv"),
            "transportCapacity": pd.read_csv(fixture_dir / "date_transport_capacity.csv"),
            "inventoryCost": pd.read_csv(fixture_dir / "date_inventory_cost.csv"),
        }

    def test_linear_program_returns_optimal_feasible_solution(self) -> None:
        result = service.solve_optimization_problem({
            "direction": "Maximize",
            "method": "Linear programming (LP)",
            "tolerance": 1e-7,
            "timeLimitSeconds": 10,
            "riskPenalty": 0,
            "variables": [
                {"name": "A", "objectiveCoefficient": 5, "lowerBound": 0, "upperBound": 10, "integer": False, "riskCoefficient": 0},
                {"name": "B", "objectiveCoefficient": 3, "lowerBound": 0, "upperBound": 10, "integer": False, "riskCoefficient": 0},
            ],
            "constraints": [{"name": "Capacity", "coefficients": {"A": 1, "B": 1}, "sense": "<=", "rhs": 12}],
        })
        self.assertTrue(result["success"])
        self.assertTrue(result["feasible"])
        self.assertAlmostEqual(result["objectiveValue"], 56.0, places=5)
        self.assertEqual(result["bindingConstraintCount"], 1)
        decisions = {row["name"]: row["value"] for row in result["decisions"]}
        self.assertAlmostEqual(decisions["A"], 10.0, places=5)
        self.assertAlmostEqual(decisions["B"], 2.0, places=5)

    def test_mixed_integer_program_preserves_integer_decisions(self) -> None:
        result = service.solve_optimization_problem({
            "direction": "Maximize",
            "method": "Mixed-integer programming (MILP)",
            "variables": [
                {"name": "Campaign_A", "objectiveCoefficient": 5, "lowerBound": 0, "upperBound": 3, "integer": True, "riskCoefficient": 0},
                {"name": "Campaign_B", "objectiveCoefficient": 4, "lowerBound": 0, "upperBound": 3, "integer": True, "riskCoefficient": 0},
            ],
            "constraints": [{"name": "Slots", "coefficients": {"Campaign_A": 1, "Campaign_B": 1}, "sense": "<=", "rhs": 3}],
            "tolerance": 1e-6,
            "timeLimitSeconds": 10,
            "riskPenalty": 0,
        })
        self.assertTrue(result["success"])
        for decision in result["decisions"]:
            self.assertAlmostEqual(decision["value"], round(decision["value"]), places=6)
        self.assertAlmostEqual(result["objectiveValue"], 15.0, places=5)

    def test_risk_adjusted_nonlinear_reports_penalty_and_feasibility(self) -> None:
        result = service.solve_optimization_problem({
            "direction": "Maximize",
            "method": "Risk-adjusted nonlinear",
            "variables": [{"name": "Exposure", "objectiveCoefficient": 10, "lowerBound": 0, "upperBound": 10, "integer": False, "riskCoefficient": 1}],
            "constraints": [{"name": "Limit", "coefficients": {"Exposure": 1}, "sense": "<=", "rhs": 10}],
            "tolerance": 1e-7,
            "timeLimitSeconds": 10,
            "riskPenalty": 1,
        })
        self.assertTrue(result["success"])
        self.assertGreater(result["riskPenaltyCost"], 0)
        self.assertLess(result["riskAdjustedObjective"], result["objectiveValue"])

    def test_full_artifact_profile_uses_actual_rows_and_maps_candidates(self) -> None:
        frame = pd.DataFrame({
            "item id": ["A", "B", "C"],
            "expected value": [5.0, 3.0, 2.0],
            "minimum": [0, 0, 0],
            "maximum": [10, 8, 7],
            "risk": [0.1, 0.2, 0.3],
            "portfolio": ["Prime", "Prime", "Near-prime"],
        })

        def fake_read_csv(_path, nrows=None, usecols=None, **_kwargs):
            selected = frame[list(usecols)] if usecols else frame
            return selected.head(nrows) if nrows is not None else selected.copy()

        with patch.object(service, "_dataset_artifact", return_value=({"name": "Optimization Inputs"}, "v1", Path("data_full.csv"))):
            with patch.object(service.pd, "read_csv", side_effect=fake_read_csv):
                profile = service.profile_registered_optimization_dataset({
                    "datasetId": "optimization-inputs",
                    "versionId": "v1",
                    "mapping": {
                        "itemColumn": "item id",
                        "objectiveColumn": "expected value",
                        "lowerBoundColumn": "minimum",
                        "upperBoundColumn": "maximum",
                        "riskColumn": "risk",
                        "groupColumn": "portfolio",
                    },
                })
        self.assertTrue(profile["fullArtifact"])
        self.assertEqual(profile["rowCount"], 3)
        self.assertEqual(profile["validOptimizationRows"], 3)
        self.assertEqual(len(profile["candidateVariables"]), 3)
        self.assertEqual(profile["candidateVariables"][0]["name"], "A")

    def test_transportation_bundle_normalizes_to_route_level_formulation(self) -> None:
        formulation = normalize_transportation_frames(self.transportation_frames())
        self.assertTrue(formulation["formulationReady"])
        self.assertEqual(len(formulation["customers"]), 6)
        self.assertEqual(len(formulation["suppliers"]), 5)
        self.assertEqual(len(formulation["routes"]), 30)
        self.assertEqual(len(formulation["variables"]), 30)
        self.assertEqual(formulation["metrics"]["totalDemand"], 480)
        self.assertEqual(formulation["metrics"]["totalSupplyMax"], 1110)
        self.assertEqual(formulation["metrics"]["totalTransportCapacity"], 570)
        self.assertEqual(formulation["metrics"]["demandConstraintCount"], 6)
        self.assertEqual(formulation["metrics"]["supplyConstraintCount"], 5)
        self.assertEqual(formulation["metrics"]["transportConstraintCount"], 5)
        self.assertEqual(formulation["metrics"]["nonNegativityBoundCount"], 30)
        self.assertIn("x_Supplier1_Customer1", {row["name"] for row in formulation["variables"]})
        self.assertNotIn("Customer1", {row["name"] for row in formulation["variables"]})
        first = next(row for row in formulation["routes"] if row["supplier"] == "Supplier1" and row["customer"] == "Customer1")
        self.assertAlmostEqual(first["total_unit_cost"], 2.4)

    def test_transportation_profile_detects_duplicate_keys_and_missing_cost(self) -> None:
        frames = self.transportation_frames()
        frames["demand"] = pd.concat([frames["demand"], frames["demand"].iloc[[0]]], ignore_index=True)
        frames["transportationCost"].loc[0, "Supplier2"] = None
        formulation = normalize_transportation_frames(frames)
        demand_profile = next(row for row in formulation["inputTables"] if row["role"] == "demand")
        self.assertGreater(demand_profile["duplicateKeys"], 0)
        self.assertEqual(formulation["metrics"]["missingRouteCosts"], 1)
        self.assertFalse(formulation["formulationReady"])

    def test_transportation_profile_detects_missing_supplier_inventory_cost(self) -> None:
        frames = self.transportation_frames()
        frames["inventoryCost"].loc[0, "Inventory_Cost"] = None
        formulation = normalize_transportation_frames(frames)
        inventory_check = next(
            row for row in formulation["readinessChecks"] if row["id"] == "suppliers_have_inventory"
        )
        self.assertEqual(formulation["metrics"]["suppliersWithoutInventoryCost"], 1)
        self.assertEqual(inventory_check["status"], "fail")
        self.assertFalse(formulation["formulationReady"])

    def test_transportation_bundle_defaults_optional_inventory_cost_to_zero(self) -> None:
        frames = self.transportation_frames()
        del frames["inventoryCost"]
        formulation = normalize_transportation_frames(frames)
        self.assertTrue(formulation["formulationReady"])
        self.assertFalse(formulation["metrics"]["inventoryCostSupplied"])
        self.assertEqual(formulation["metrics"]["suppliersWithoutInventoryCost"], 0)
        self.assertTrue(all(route["inventory_cost"] == 0 for route in formulation["routes"]))
        self.assertEqual(
            formulation["objective"]["expression"],
            "min sum(supplier, customer) x_supplier_customer * transportation_cost_supplier_customer",
        )
        self.assertIn(
            "Inventory or handling cost was not supplied. The objective will use route transportation cost only.",
            formulation["warnings"],
        )

    def test_transportation_bundle_blocks_when_a_required_table_is_missing(self) -> None:
        frames = self.transportation_frames()
        del frames["demand"]
        with self.assertRaises(HTTPException) as captured:
            normalize_transportation_frames(frames)
        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("demand", str(captured.exception.detail))

    def test_transportation_route_costs_support_long_table_shape(self) -> None:
        frames = self.transportation_frames()
        frames["transportationCost"] = frames["transportationCost"].melt(
            id_vars=["Customers"],
            var_name="supplier",
            value_name="route_cost",
        )
        formulation = normalize_transportation_frames(frames)
        self.assertTrue(formulation["formulationReady"])
        self.assertEqual(formulation["resolvedMapping"]["costShape"], "long_route_table")
        self.assertEqual(len(formulation["routes"]), 30)
        first = next(
            row
            for row in formulation["routes"]
            if row["supplier"] == "Supplier1" and row["customer"] == "Customer1"
        )
        self.assertAlmostEqual(first["transportation_cost"], 2.0)
        self.assertAlmostEqual(first["total_unit_cost"], 2.4)

    def test_transportation_solver_fulfills_demand_and_respects_capacity(self) -> None:
        formulation = normalize_transportation_frames(self.transportation_frames())
        result = solve_transportation_formulation(formulation)
        self.assertTrue(result["success"])
        self.assertEqual(result["businessValidityStatus"], "valid")
        self.assertGreater(result["totalCost"], 0)
        self.assertAlmostEqual(result["demandFulfilled"], 480.0, places=5)
        self.assertAlmostEqual(result["unmetDemand"], 0.0, places=5)
        self.assertGreater(result["activeRoutes"], 0)
        self.assertEqual(len(result["decisionVector"]), 30)
        self.assertAlmostEqual(result["totalCost"], 818.75, places=2)
        self.assertTrue(all(row["quantity"] >= 0 for row in result["decisionVector"]))
        self.assertTrue(all(row["feasible"] for row in result["supplyConstraintResults"]))
        self.assertTrue(all(row["feasible"] for row in result["transportConstraintResults"]))

    def test_transportation_solver_rejects_zero_allocation_placeholder(self) -> None:
        formulation = normalize_transportation_frames(self.transportation_frames())
        formulation["constraints"] = [
            row for row in formulation["constraints"] if row.get("constraintType") != "demand"
        ]
        result = solve_transportation_formulation(formulation)
        self.assertFalse(result["success"])
        self.assertEqual(result["businessValidityStatus"], "invalid")
        self.assertEqual(result["decisionReadiness"], "blocked")
        self.assertTrue(any("zero-allocation" in message for message in result["errors"]))

    def test_transportation_scenarios_and_sensitivity_use_real_solution(self) -> None:
        formulation = normalize_transportation_frames(self.transportation_frames())
        scenarios = run_transportation_scenarios(formulation)
        self.assertEqual(scenarios["scenarioCount"], 5)
        base = next(row for row in scenarios["results"] if row["scenarioId"] == "base")
        cost_stress = next(row for row in scenarios["results"] if row["scenarioId"] == "transport-cost-increase")
        disruption = next(row for row in scenarios["results"] if row["scenarioId"] == "severe-disruption")
        self.assertGreater(base["totalCost"], 0)
        self.assertGreater(cost_stress["totalCost"], base["totalCost"])
        self.assertFalse(disruption["feasible"])
        self.assertGreater(disruption["unmetDemand"], 0)
        sensitivity = run_transportation_sensitivity(formulation, perturbation_percent=10)
        self.assertTrue(sensitivity["available"])
        self.assertEqual(len(sensitivity["rows"]), 10)
        route_increase = next(row for row in sensitivity["rows"] if row["driver"] == "Route cost" and row["direction"] == "Increase")
        self.assertGreater(route_increase["costChange"], 0)
        self.assertTrue(any(row["available"] for row in sensitivity["shadowPrices"]))

    def test_transportation_sensitivity_blocks_business_invalid_solution(self) -> None:
        formulation = normalize_transportation_frames(self.transportation_frames())
        formulation["constraints"] = [
            row for row in formulation["constraints"] if row.get("constraintType") != "demand"
        ]
        with self.assertRaises(HTTPException) as captured:
            run_transportation_sensitivity(formulation)
        self.assertEqual(captured.exception.status_code, 409)
        self.assertIn("not business-valid", str(captured.exception.detail))

    def test_transportation_validation_requires_active_governance_confirmation(self) -> None:
        formulation = normalize_transportation_frames(self.transportation_frames())
        result = solve_transportation_formulation(formulation)
        scenarios = run_transportation_scenarios(formulation)
        sensitivity = run_transportation_sensitivity(formulation)
        pending = validate_transportation_decision(formulation, result, scenarios, sensitivity, {})
        self.assertFalse(pending["recommendationAllowed"])
        approved = validate_transportation_decision(
            formulation,
            result,
            scenarios,
            sensitivity,
            {"evidenceCompleteness": True, "implementationReadiness": True, "independentReview": True},
        )
        self.assertTrue(approved["recommendationAllowed"])

    def test_generated_python_and_sas_code_use_route_level_formulation(self) -> None:
        formulation = normalize_transportation_frames(self.transportation_frames())
        code = generate_transportation_code(formulation, "solver_run")
        self.assertEqual(code["generatorVersion"], "transportation-codegen-v2")
        python_code = code["python"]["code"]
        sas_code = code["sas"]["code"]
        compile(python_code, "atlas_transportation_export.py", "exec")
        for phrase in [
            "normalize_wide_route_costs",
            "linprog",
            "A_eq",
            "A_ub",
            "demand_fulfillment",
            "supplier_utilization",
            "shadow_price",
            "solve_variant",
            "allocation.to_csv",
        ]:
            self.assertIn(phrase, python_code)
        sas_code_upper = sas_code.upper()
        for phrase in ["PROC IMPORT", "PROC TRANSPOSE", "PROC SQL", "PROC OPTMODEL", "DEMANDFULFILLMENT", "SUPPLYMAXIMUM", "TRANSPORTCAPACITY", "PROC EXPORT"]:
            self.assertIn(phrase, sas_code_upper)
        self.assertEqual(code["sas"]["runtimeStatus"], "Template-only")

    def test_optimization_evidence_coverage_requires_actual_captured_artifacts(self) -> None:
        artifact_types = [
            "optimization_decision_charter",
            "optimization_input_bundle",
            "optimization_formulation_readiness",
            "optimization_objective",
            "optimization_decision_variables",
            "optimization_constraints",
            "optimization_solver_configuration",
            "optimization_scenarios",
            "optimization_solution",
            "optimization_sensitivity",
            "optimization_validation",
            "optimization_recommendation",
            "optimization_implementation_plan",
            "optimization_monitoring_plan",
            "optimization_documentation_package",
            "optimization_reproducibility_code",
        ]
        rows = [
            {
                "evidenceId": f"ev-{index}",
                "evidenceType": evidence_type,
                "status": "ready",
                "supportsSections": [],
                "tags": ["optimization"],
            }
            for index, evidence_type in enumerate(artifact_types)
        ]
        with patch.object(evidence_store, "list_evidence", return_value=rows):
            complete = evidence_store.coverage("optimization-project")
        self.assertEqual(complete["workflowType"], "optimization")
        self.assertEqual(complete["coverageScore"], 100)
        self.assertEqual(complete["readyEvidence"], 16)
        self.assertEqual(complete["missingRecommended"], [])

        package_only = [row for row in rows if row["evidenceType"] == "optimization_documentation_package"]
        package_only[0]["supportsSections"] = evidence_store.DOCUMENTATION_SECTIONS["optimization_documentation_package"]
        with patch.object(evidence_store, "list_evidence", return_value=package_only):
            incomplete = evidence_store.coverage("optimization-project")
        self.assertLess(incomplete["coverageScore"], 100)
        self.assertIn("optimization_solution", incomplete["missingRecommended"])


if __name__ == "__main__":
    unittest.main()

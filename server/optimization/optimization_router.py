from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .optimization_service import profile_registered_optimization_dataset, solve_optimization_problem
from .codegen_service import generate_transportation_code
from .evidence_service import build_transportation_evidence
from .scenario_service import run_transportation_scenarios
from .schemas import (
    TransportationCodeRequest,
    TransportationEvidenceRequest,
    TransportationRequest,
    TransportationScenarioRequest,
    TransportationSensitivityRequest,
    TransportationValidationRequest,
)
from .sensitivity_service import run_transportation_sensitivity
from .solver_service import solve_transportation_formulation
from .transportation_template_service import build_transportation_formulation
from .validation_service import validate_transportation_decision


class OptimizationMapping(BaseModel):
    itemColumn: str = ""
    objectiveColumn: str = ""
    lowerBoundColumn: str = ""
    upperBoundColumn: str = ""
    costColumn: str = ""
    riskColumn: str = ""
    groupColumn: str = ""


class OptimizationProfileRequest(BaseModel):
    datasetId: str
    versionId: str | None = None
    mapping: OptimizationMapping = Field(default_factory=OptimizationMapping)


class OptimizationVariable(BaseModel):
    name: str
    objectiveCoefficient: float
    lowerBound: float = 0.0
    upperBound: float | None = None
    integer: bool = False
    riskCoefficient: float = 0.0
    group: str = ""


class OptimizationConstraint(BaseModel):
    name: str
    coefficients: dict[str, float] = Field(default_factory=dict)
    sense: Literal["<=", ">=", "="] = "<="
    rhs: float


class OptimizationSolveRequest(BaseModel):
    direction: Literal["Maximize", "Minimize"] = "Maximize"
    method: Literal[
        "Linear programming (LP)",
        "Mixed-integer programming (MILP)",
        "Risk-adjusted nonlinear",
    ] = "Linear programming (LP)"
    variables: list[OptimizationVariable]
    constraints: list[OptimizationConstraint] = Field(default_factory=list)
    tolerance: float = 1e-7
    timeLimitSeconds: float = 30.0
    riskPenalty: float = 0.0


router = APIRouter()


@router.post("/optimization/profile")
def post_optimization_profile(payload: OptimizationProfileRequest) -> dict[str, Any]:
    return {"ok": True, "profile": profile_registered_optimization_dataset(payload.model_dump())}


@router.post("/optimization/solve")
def post_optimization_solve(payload: OptimizationSolveRequest) -> dict[str, Any]:
    return {"ok": True, "result": solve_optimization_problem(payload.model_dump())}


@router.post("/optimization/transportation/formulate")
def post_transportation_formulation(payload: TransportationRequest) -> dict[str, Any]:
    request = payload.model_dump()
    formulation = build_transportation_formulation(request)
    return {
        "ok": True,
        "formulation": formulation,
        "code": generate_transportation_code(formulation, "formulation"),
    }


@router.post("/optimization/transportation/solve")
def post_transportation_solve(payload: TransportationRequest) -> dict[str, Any]:
    request = payload.model_dump()
    formulation = build_transportation_formulation(request)
    result = solve_transportation_formulation(formulation, request.get("solver"))
    return {"ok": True, "formulation": formulation, "result": result}


@router.post("/optimization/transportation/scenarios")
def post_transportation_scenarios(payload: TransportationScenarioRequest) -> dict[str, Any]:
    request = payload.model_dump()
    formulation = build_transportation_formulation(request)
    analysis = run_transportation_scenarios(
        formulation,
        request.get("scenarios") or None,
        request.get("solver"),
    )
    return {"ok": True, "formulation": formulation, "analysis": analysis}


@router.post("/optimization/transportation/sensitivity")
def post_transportation_sensitivity(payload: TransportationSensitivityRequest) -> dict[str, Any]:
    request = payload.model_dump()
    formulation = build_transportation_formulation(request)
    analysis = run_transportation_sensitivity(
        formulation,
        request.get("solver"),
        request.get("perturbationPercent", 10.0),
    )
    return {"ok": True, "formulation": formulation, "analysis": analysis}


@router.post("/optimization/transportation/validate")
def post_transportation_validation(payload: TransportationValidationRequest) -> dict[str, Any]:
    request = payload.model_dump()
    formulation = build_transportation_formulation(request)
    result = solve_transportation_formulation(formulation, request.get("solver"))
    scenarios = run_transportation_scenarios(formulation, None, request.get("solver"))
    sensitivity = run_transportation_sensitivity(formulation, request.get("solver"), 10.0)
    validation = validate_transportation_decision(
        formulation,
        result,
        scenarios,
        sensitivity,
        request.get("confirmations"),
    )
    return {
        "ok": True,
        "formulation": formulation,
        "result": result,
        "scenarios": scenarios,
        "sensitivity": sensitivity,
        "validation": validation,
    }


@router.post("/optimization/transportation/code")
def post_transportation_code(payload: TransportationCodeRequest) -> dict[str, Any]:
    request = payload.model_dump()
    formulation = build_transportation_formulation(request)
    return {"ok": True, "code": generate_transportation_code(formulation, request.get("stage", "formulation"))}


@router.post("/optimization/transportation/evidence")
def post_transportation_evidence(payload: TransportationEvidenceRequest) -> dict[str, Any]:
    request = payload.model_dump()
    formulation = build_transportation_formulation(request)
    stage = request.get("stage", "input_bundle")
    result = None
    if stage in {"scenarios", "solver_run", "solution", "sensitivity", "validation", "recommendation"}:
        result = solve_transportation_formulation(formulation, request.get("solver"))
    evidence = build_transportation_evidence(stage, formulation, result=result, context=request)
    return {"ok": True, "evidence": evidence}

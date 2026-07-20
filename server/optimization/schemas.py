from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DatasetReference(BaseModel):
    datasetId: str = ""
    versionId: str | None = None


class TransportationSolverConfiguration(BaseModel):
    method: str = "Linear programming (LP)"
    tolerance: float = 1e-7
    timeLimitSeconds: float = 30.0


class TransportationScenario(BaseModel):
    id: str
    name: str
    demandMultiplier: float = 1.0
    supplyMultiplier: float = 1.0
    capacityMultiplier: float = 1.0
    routeCostMultiplier: float = 1.0
    inventoryCostMultiplier: float = 1.0
    note: str = ""


class TransportationRequest(BaseModel):
    bundle: dict[str, DatasetReference] = Field(default_factory=dict)
    mapping: dict[str, Any] = Field(default_factory=dict)
    routeOverrides: dict[str, bool] = Field(default_factory=dict)
    customConstraints: list[dict[str, Any]] = Field(default_factory=list)
    solver: TransportationSolverConfiguration = Field(default_factory=TransportationSolverConfiguration)


class TransportationScenarioRequest(TransportationRequest):
    scenarios: list[TransportationScenario] = Field(default_factory=list)


class TransportationSensitivityRequest(TransportationRequest):
    perturbationPercent: float = 10.0


class TransportationValidationRequest(TransportationRequest):
    confirmations: dict[str, bool] = Field(default_factory=dict)


class TransportationCodeRequest(TransportationRequest):
    stage: str = "formulation"


class TransportationEvidenceRequest(TransportationRequest):
    stage: str = "input_bundle"
    projectId: str = ""
    user: str = "Local ATLAS User"
    decisionNotes: str = ""
    chartMetadata: list[dict[str, Any]] = Field(default_factory=list)

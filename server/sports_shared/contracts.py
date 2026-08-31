"""Versioned, sport-neutral contracts for ASP Model Studio workflows.

The objects in this module are metadata contracts only.  Importing or
validating them performs no persistence, data access, model fitting, scoring,
simulation, or provider activity.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Iterable, Literal, Mapping, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SPORT_REGISTRY_V1 = "SPORT_REGISTRY_V1"
SPORT_WORKFLOW_MANIFEST_V1 = "SPORT_WORKFLOW_MANIFEST_V1"
SPORT_MODEL_METADATA_V1 = "SPORT_MODEL_METADATA_V1"
SPORT_SIMULATION_METADATA_V1 = "SPORT_SIMULATION_METADATA_V1"


class SportCode(str, Enum):
    BASEBALL = "BASEBALL"
    FOOTBALL = "FOOTBALL"
    BASKETBALL = "BASKETBALL"
    MMA = "MMA"


class LeagueCode(str, Enum):
    MLB = "MLB"
    NFL = "NFL"
    NBA = "NBA"
    WNBA = "WNBA"
    UFC = "UFC"


class ParticipantType(str, Enum):
    TEAM = "TEAM"
    INDIVIDUAL = "INDIVIDUAL"


class SportAvailabilityState(str, Enum):
    LIVE = "LIVE"
    RESEARCH_SHADOW = "RESEARCH_SHADOW"
    DEVELOPMENT = "DEVELOPMENT"
    PLANNED = "PLANNED"
    UNAVAILABLE = "UNAVAILABLE"


class WorkflowAvailability(str, Enum):
    ENABLED = "ENABLED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    PLANNED = "PLANNED"
    BLOCKED_BY_MISSING_EVIDENCE = "BLOCKED_BY_MISSING_EVIDENCE"
    UNAVAILABLE = "UNAVAILABLE"


LEAGUE_SPORT_RELATION: Mapping[LeagueCode, SportCode] = {
    LeagueCode.MLB: SportCode.BASEBALL,
    LeagueCode.NFL: SportCode.FOOTBALL,
    LeagueCode.NBA: SportCode.BASKETBALL,
    LeagueCode.WNBA: SportCode.BASKETBALL,
    LeagueCode.UFC: SportCode.MMA,
}

LEAGUE_PARTICIPANT_RELATION: Mapping[LeagueCode, ParticipantType] = {
    LeagueCode.MLB: ParticipantType.TEAM,
    LeagueCode.NFL: ParticipantType.TEAM,
    LeagueCode.NBA: ParticipantType.TEAM,
    LeagueCode.WNBA: ParticipantType.TEAM,
    LeagueCode.UFC: ParticipantType.INDIVIDUAL,
}

_LEGACY_SPORT_LABELS: Mapping[str, SportCode] = {
    "Baseball": SportCode.BASEBALL,
    "Professional Football": SportCode.FOOTBALL,
    "Basketball": SportCode.BASKETBALL,
    "Mixed Martial Arts": SportCode.MMA,
    "MMA": SportCode.MMA,
}


class SportContractError(ValueError):
    """Raised when sport, workflow, route, or dataset identities disagree."""


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


class SportRegistryLeague(FrozenContract):
    leagueCode: LeagueCode
    displayName: str = Field(min_length=1)
    participantType: ParticipantType
    availability: WorkflowAvailability
    workflowCodes: Tuple[str, ...] = Field(min_length=1)
    projectCreationSelectable: bool


class SportRegistryEntry(FrozenContract):
    sportCode: SportCode
    displayName: str = Field(min_length=1)
    availability: SportAvailabilityState
    participantType: ParticipantType
    leagues: Tuple[SportRegistryLeague, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_league_relationships(self) -> "SportRegistryEntry":
        codes = [item.leagueCode for item in self.leagues]
        if len(codes) != len(set(codes)):
            raise ValueError("leagueCode values must be unique within a sport")
        for league in self.leagues:
            if LEAGUE_SPORT_RELATION[league.leagueCode] != self.sportCode:
                raise ValueError(f"{league.leagueCode.value} is not governed by {self.sportCode.value}")
            if LEAGUE_PARTICIPANT_RELATION[league.leagueCode] != league.participantType:
                raise ValueError(f"{league.leagueCode.value} participant type is invalid")
            if league.participantType != self.participantType:
                raise ValueError("sport and league participant types must agree")
        return self


class SportRegistry(FrozenContract):
    schemaVersion: Literal["SPORT_REGISTRY_V1"]
    sports: Tuple[SportRegistryEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_registry(self) -> "SportRegistry":
        sport_codes = [item.sportCode for item in self.sports]
        league_codes = [league.leagueCode for item in self.sports for league in item.leagues]
        workflow_codes = [code for item in self.sports for league in item.leagues for code in league.workflowCodes]
        if len(sport_codes) != len(set(sport_codes)):
            raise ValueError("sportCode values must be unique")
        if len(league_codes) != len(set(league_codes)):
            raise ValueError("leagueCode values must be unique across the registry")
        if len(workflow_codes) != len(set(workflow_codes)):
            raise ValueError("workflowCode values must be unique across the registry")
        return self


class CanonicalIdentityContract(FrozenContract):
    contractCode: str = Field(min_length=1)
    requiredKeys: Tuple[str, ...] = Field(min_length=1)
    nameOnlyMatchingAllowed: bool = False
    mismatchPolicy: Literal["REJECT"] = "REJECT"


class PointInTimePolicy(FrozenContract):
    cutoffRule: str = Field(min_length=1)
    eventTimeFields: Tuple[str, ...] = Field(min_length=1)
    targetOutcomeAllowedBeforeScoring: bool = False
    futureEvidenceAllowed: bool = False
    marketDataAllowedAsPredictor: bool = False
    missingEvidencePolicy: str = Field(min_length=1)


class WorkflowStage(FrozenContract):
    stageCode: str = Field(min_length=1)
    displayName: str = Field(min_length=1)
    description: str = Field(min_length=1)
    availability: WorkflowAvailability
    requiredEvidenceFamilies: Tuple[str, ...]
    componentCode: str = Field(min_length=1)
    completionContract: str = Field(min_length=1)


class ValidationTemplate(FrozenContract):
    templateCode: str = Field(min_length=1)
    displayName: str = Field(min_length=1)
    groupingUnit: str = Field(min_length=1)
    rules: Tuple[str, ...] = Field(min_length=1)
    randomSplitAllowed: bool = False
    finalOotLocked: bool = True


class SportWorkflowManifest(FrozenContract):
    schemaVersion: Literal["SPORT_WORKFLOW_MANIFEST_V1"]
    sportCode: SportCode
    leagueCode: LeagueCode
    workflowCode: str = Field(min_length=1)
    compatibleWorkflowIds: Tuple[str, ...] = Field(min_length=1)
    displayName: str = Field(min_length=1)
    description: str = Field(min_length=1)
    availability: WorkflowAvailability
    participantType: ParticipantType
    projectTemplateSelectable: bool
    liveNavigationVisible: bool
    modelingEnabled: bool
    simulationEnabled: bool
    readinessMessage: str = Field(min_length=1)
    supportedDatasetGrains: Tuple[str, ...] = Field(min_length=1)
    supportedPredictionUnits: Tuple[str, ...] = Field(min_length=1)
    supportedTargets: Tuple[str, ...] = Field(min_length=1)
    forecastLifecycles: Tuple[str, ...] = Field(min_length=1)
    canonicalIdentityContract: CanonicalIdentityContract
    requiredEvidenceFamilies: Tuple[str, ...]
    optionalEvidenceFamilies: Tuple[str, ...]
    pointInTimePolicy: PointInTimePolicy
    workflowStages: Tuple[WorkflowStage, ...] = Field(min_length=1)
    developmentSteps: Tuple[str, ...] = Field(min_length=1)
    validationTemplates: Tuple[ValidationTemplate, ...] = Field(min_length=1)
    candidateModelFamilies: Tuple[str, ...]
    primaryMetrics: Tuple[str, ...] = Field(min_length=1)
    secondaryMetrics: Tuple[str, ...]
    calibrationRequirements: Tuple[str, ...]
    simulatorAdapterCode: str = Field(min_length=1)
    supportedMarketTypes: Tuple[str, ...]
    deploymentRestrictions: Tuple[str, ...] = Field(min_length=1)
    monitoringMetrics: Tuple[str, ...]
    documentationRequirements: Tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "compatibleWorkflowIds",
        "supportedDatasetGrains",
        "supportedPredictionUnits",
        "supportedTargets",
        "forecastLifecycles",
        "requiredEvidenceFamilies",
        "optionalEvidenceFamilies",
        "developmentSteps",
        "candidateModelFamilies",
        "primaryMetrics",
        "secondaryMetrics",
        "calibrationRequirements",
        "supportedMarketTypes",
        "deploymentRestrictions",
        "monitoringMetrics",
        "documentationRequirements",
    )
    @classmethod
    def validate_unique_ordered_values(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        if any(not str(item).strip() for item in value):
            raise ValueError("manifest list values must be non-empty strings")
        if len(value) != len(set(value)):
            raise ValueError("manifest list values must be unique")
        return value

    @model_validator(mode="after")
    def validate_manifest_relationships(self) -> "SportWorkflowManifest":
        if LEAGUE_SPORT_RELATION[self.leagueCode] != self.sportCode:
            raise ValueError("leagueCode does not belong to sportCode")
        if LEAGUE_PARTICIPANT_RELATION[self.leagueCode] != self.participantType:
            raise ValueError("participantType does not match leagueCode")
        stage_codes = [stage.stageCode for stage in self.workflowStages]
        if len(stage_codes) != len(set(stage_codes)):
            raise ValueError("workflow stage codes must be unique")
        if self.availability in {
            WorkflowAvailability.PLANNED,
            WorkflowAvailability.BLOCKED_BY_MISSING_EVIDENCE,
            WorkflowAvailability.UNAVAILABLE,
        } and (self.projectTemplateSelectable or self.liveNavigationVisible):
            raise ValueError("unfinished workflows cannot be selectable or live navigation destinations")
        if self.availability == WorkflowAvailability.RESEARCH_ONLY and self.modelingEnabled:
            raise ValueError("research-only workflow cannot enable model development in Phase 1")
        if self.availability != WorkflowAvailability.ENABLED and self.simulationEnabled:
            raise ValueError("only an enabled workflow may expose executable simulation")
        return self


class DatasetIdentityEnvelope(FrozenContract):
    datasetId: str = Field(min_length=1)
    datasetVersionId: str = Field(min_length=1)
    manifestSha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sportCode: SportCode
    leagueCode: LeagueCode
    datasetGrain: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_relation(self) -> "DatasetIdentityEnvelope":
        if LEAGUE_SPORT_RELATION[self.leagueCode] != self.sportCode:
            raise ValueError("dataset leagueCode does not belong to sportCode")
        return self


class DatasetBindingDescriptor(DatasetIdentityEnvelope):
    predictionUnits: Tuple[str, ...] = Field(min_length=1)
    activationEligible: bool = True


class ModelSportMetadataEnvelope(FrozenContract):
    schemaVersion: Literal["SPORT_MODEL_METADATA_V1"]
    modelId: str = Field(min_length=1)
    modelVersion: str = Field(min_length=1)
    sportCode: SportCode
    leagueCode: LeagueCode
    workflowCode: str = Field(min_length=1)
    predictionUnit: str = Field(min_length=1)
    target: str = Field(min_length=1)
    datasetIdentity: DatasetIdentityEnvelope
    featureContract: str = Field(min_length=1)
    validationContract: str = Field(min_length=1)
    simulatorAdapterCode: str = Field(min_length=1)
    promotionState: str = Field(min_length=1)
    marketDataUsedAsPredictor: bool = False

    @model_validator(mode="after")
    def reject_cross_sport_or_market_input(self) -> "ModelSportMetadataEnvelope":
        if self.datasetIdentity.sportCode != self.sportCode or self.datasetIdentity.leagueCode != self.leagueCode:
            raise ValueError("model and dataset sport identities must agree")
        if self.marketDataUsedAsPredictor:
            raise ValueError("sportsbook market data is post-model comparison evidence, not a core predictor")
        return self


class SimulationSportMetadataEnvelope(FrozenContract):
    schemaVersion: Literal["SPORT_SIMULATION_METADATA_V1"]
    simulationId: str = Field(min_length=1)
    sportCode: SportCode
    leagueCode: LeagueCode
    workflowCode: str = Field(min_length=1)
    predictionUnit: str = Field(min_length=1)
    target: str = Field(min_length=1)
    datasetIdentity: DatasetIdentityEnvelope
    modelId: str = Field(min_length=1)
    modelVersion: str = Field(min_length=1)
    simulatorAdapterCode: str = Field(min_length=1)
    seed: int
    draws: int = Field(gt=0)
    assumptions: Tuple[str, ...] = Field(min_length=1)
    executable: bool
    deploymentState: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_relation(self) -> "SimulationSportMetadataEnvelope":
        if self.datasetIdentity.sportCode != self.sportCode or self.datasetIdentity.leagueCode != self.leagueCode:
            raise ValueError("simulation and dataset sport identities must agree")
        return self


def canonical_sport_code(value: SportCode | str) -> SportCode:
    if isinstance(value, SportCode):
        return value
    candidate = str(value).strip()
    try:
        return SportCode(candidate.upper())
    except ValueError:
        if candidate in _LEGACY_SPORT_LABELS:
            return _LEGACY_SPORT_LABELS[candidate]
        raise SportContractError(f"Unknown sport identity: {candidate!r}") from None


def canonical_league_code(value: LeagueCode | str) -> LeagueCode:
    if isinstance(value, LeagueCode):
        return value
    candidate = str(value).strip().upper()
    try:
        return LeagueCode(candidate)
    except ValueError:
        raise SportContractError(f"Unknown league identity: {candidate!r}") from None


def validate_dataset_binding(
    manifest: SportWorkflowManifest,
    binding: DatasetBindingDescriptor,
    *,
    required_prediction_unit: str | None = None,
) -> DatasetBindingDescriptor:
    """Fail closed when dataset sport, league, grain, or prediction unit differs."""

    if binding.sportCode != manifest.sportCode or binding.leagueCode != manifest.leagueCode:
        raise SportContractError("Dataset sport/league identity is incompatible with the workflow manifest")
    if binding.datasetGrain not in manifest.supportedDatasetGrains:
        raise SportContractError(f"Dataset grain {binding.datasetGrain!r} is not supported by {manifest.workflowCode}")
    if required_prediction_unit is not None:
        if required_prediction_unit not in manifest.supportedPredictionUnits:
            raise SportContractError("Requested prediction unit is not supported by the workflow manifest")
        if required_prediction_unit not in binding.predictionUnits:
            raise SportContractError("Dataset does not authorize the requested prediction unit")
    if not binding.activationEligible:
        raise SportContractError("Dataset authority is read-only and cannot be activated for this workflow")
    return binding


def validate_model_sport_metadata(
    manifest: SportWorkflowManifest,
    envelope: ModelSportMetadataEnvelope,
) -> ModelSportMetadataEnvelope:
    if envelope.sportCode != manifest.sportCode or envelope.leagueCode != manifest.leagueCode:
        raise SportContractError("Model sport/league identity is incompatible with the workflow manifest")
    if envelope.workflowCode not in {manifest.workflowCode, *manifest.compatibleWorkflowIds}:
        raise SportContractError("Model workflow identity is incompatible with the workflow manifest")
    if envelope.predictionUnit not in manifest.supportedPredictionUnits:
        raise SportContractError("Model prediction unit is incompatible with the workflow manifest")
    if envelope.target not in manifest.supportedTargets:
        raise SportContractError("Model target is incompatible with the workflow manifest")
    if envelope.simulatorAdapterCode != manifest.simulatorAdapterCode:
        raise SportContractError("Model simulator adapter is incompatible with the workflow manifest")
    return envelope


def validate_simulation_sport_metadata(
    manifest: SportWorkflowManifest,
    envelope: SimulationSportMetadataEnvelope,
) -> SimulationSportMetadataEnvelope:
    if envelope.sportCode != manifest.sportCode or envelope.leagueCode != manifest.leagueCode:
        raise SportContractError("Simulation sport/league identity is incompatible with the workflow manifest")
    if envelope.workflowCode not in {manifest.workflowCode, *manifest.compatibleWorkflowIds}:
        raise SportContractError("Simulation workflow identity is incompatible with the workflow manifest")
    if envelope.predictionUnit not in manifest.supportedPredictionUnits:
        raise SportContractError("Simulation prediction unit is incompatible with the workflow manifest")
    if envelope.target not in manifest.supportedTargets:
        raise SportContractError("Simulation target is incompatible with the workflow manifest")
    if envelope.simulatorAdapterCode != manifest.simulatorAdapterCode:
        raise SportContractError("Simulation adapter is incompatible with the workflow manifest")
    if envelope.executable and not manifest.simulationEnabled:
        raise SportContractError("Workflow does not authorize executable simulation")
    return envelope


def contract_payload(value: BaseModel) -> Dict[str, Any]:
    return value.model_dump(mode="json")


__all__ = [
    "CanonicalIdentityContract",
    "DatasetBindingDescriptor",
    "DatasetIdentityEnvelope",
    "LEAGUE_PARTICIPANT_RELATION",
    "LEAGUE_SPORT_RELATION",
    "LeagueCode",
    "ModelSportMetadataEnvelope",
    "ParticipantType",
    "PointInTimePolicy",
    "SPORT_MODEL_METADATA_V1",
    "SPORT_REGISTRY_V1",
    "SPORT_SIMULATION_METADATA_V1",
    "SPORT_WORKFLOW_MANIFEST_V1",
    "SimulationSportMetadataEnvelope",
    "SportAvailabilityState",
    "SportCode",
    "SportContractError",
    "SportRegistry",
    "SportRegistryEntry",
    "SportRegistryLeague",
    "SportWorkflowManifest",
    "ValidationTemplate",
    "WorkflowAvailability",
    "WorkflowStage",
    "canonical_league_code",
    "canonical_sport_code",
    "contract_payload",
    "validate_dataset_binding",
    "validate_model_sport_metadata",
    "validate_simulation_sport_metadata",
]

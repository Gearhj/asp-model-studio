"""Non-selectable Phase-1 UFC roadmap manifest."""

from __future__ import annotations

from ..sports_shared.contracts import (
    CanonicalIdentityContract, LeagueCode, ParticipantType, PointInTimePolicy,
    SPORT_WORKFLOW_MANIFEST_V1, SportCode, SportWorkflowManifest,
    ValidationTemplate, WorkflowAvailability, WorkflowStage,
)


UFC_WORKFLOW_MANIFEST = SportWorkflowManifest(
    schemaVersion=SPORT_WORKFLOW_MANIFEST_V1,
    sportCode=SportCode.MMA,
    leagueCode=LeagueCode.UFC,
    workflowCode="UFC_BOUT_FORECAST_WORKFLOW_V1",
    compatibleWorkflowIds=("ufc-forecasting",),
    displayName="UFC Bout Forecasting — Planned",
    description="Planned fighter/bout workflow; no governed live project is available.",
    availability=WorkflowAvailability.PLANNED,
    participantType=ParticipantType.INDIVIDUAL,
    projectTemplateSelectable=False,
    liveNavigationVisible=False,
    modelingEnabled=False,
    simulationEnabled=False,
    readinessMessage="Planned only; governed bout evidence, modeling workflow, and deployment authority do not exist.",
    supportedDatasetGrains=("FIGHTER_BOUT", "ROUND", "BOUT_STATE", "BOUT"),
    supportedPredictionUnits=("FIGHTER_BOUT", "ROUND", "BOUT"),
    supportedTargets=("BOUT_WINNER", "METHOD_OF_VICTORY", "ROUND_OF_FINISH", "DECISION_PROBABILITY"),
    forecastLifecycles=("PRE_BOUT_PLANNED",),
    canonicalIdentityContract=CanonicalIdentityContract(
        contractCode="UFC_CANONICAL_EVENT_BOUT_FIGHTER_ROUND_IDENTITY_V1",
        requiredKeys=("canonical_event_id", "canonical_bout_id", "canonical_fighter_id"),
    ),
    requiredEvidenceFamilies=(),
    optionalEvidenceFamilies=("FIGHTER_HISTORY", "STYLE_MATCHUP", "AGE", "LAYOFF", "WEIGHT_CLASS", "WEIGHT_CUT", "CAMP_INJURY"),
    pointInTimePolicy=PointInTimePolicy(
        cutoffRule="Planned evidence must predate the bout start.",
        eventTimeFields=("scheduled_bout_time", "source_cutoff"),
        missingEvidencePolicy="BLOCK_UNTIL_GOVERNED_EVIDENCE_EXISTS",
    ),
    workflowStages=(WorkflowStage(
        stageCode="ufc-planned",
        displayName="Planned fighter/bout workflow",
        description="Roadmap metadata only.",
        availability=WorkflowAvailability.PLANNED,
        requiredEvidenceFamilies=(),
        componentCode="NO_LIVE_COMPONENT",
        completionContract="UNAVAILABLE_UNTIL_SEPARATE_GOVERNED_IMPLEMENTATION",
    ),),
    developmentSteps=("PLANNED_BOUT_DATA_FOUNDATION", "PLANNED_MATCHUP_MODELING", "PLANNED_ROUND_FINISH_SIMULATION"),
    validationTemplates=(ValidationTemplate(
        templateCode="UFC_PLANNED_EVENT_GROUPED_CHRONOLOGICAL_V1",
        displayName="Planned bout-event chronological validation",
        groupingUnit="CANONICAL_EVENT",
        rules=("EVENT_GROUPED", "CHRONOLOGICAL", "FIGHTER_HISTORY_POINT_IN_TIME", "NO_RANDOM_BOUT_LEAKAGE"),
    ),),
    candidateModelFamilies=(),
    primaryMetrics=("BOUT_WIN_LOG_LOSS", "BRIER"),
    secondaryMetrics=("METHOD_LOG_LOSS", "CALIBRATION_ERROR"),
    calibrationRequirements=("NOT_AVAILABLE_UNTIL_IMPLEMENTED",),
    simulatorAdapterCode="UFC_ROUND_FINISH_SIMULATOR_PLANNED",
    supportedMarketTypes=("MONEYLINE", "METHOD_OF_VICTORY", "ROUND_TOTAL"),
    deploymentRestrictions=("PLANNED", "NOT_SELECTABLE", "NOT_EXECUTABLE", "NO_MODELING"),
    monitoringMetrics=(),
    documentationRequirements=("SEPARATE_DATA_FOUNDATION_REQUIRED", "SEPARATE_WORKFLOW_ACCEPTANCE_REQUIRED"),
)


__all__ = ["UFC_WORKFLOW_MANIFEST"]

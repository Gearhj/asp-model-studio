"""Non-selectable Phase-1 NBA and WNBA roadmap manifests."""

from __future__ import annotations

from ..sports_shared.contracts import (
    CanonicalIdentityContract, LeagueCode, ParticipantType, PointInTimePolicy,
    SPORT_WORKFLOW_MANIFEST_V1, SportCode, SportWorkflowManifest,
    ValidationTemplate, WorkflowAvailability, WorkflowStage,
)


def _manifest(league: LeagueCode, workflow_code: str, compatible_id: str) -> SportWorkflowManifest:
    return SportWorkflowManifest(
        schemaVersion=SPORT_WORKFLOW_MANIFEST_V1,
        sportCode=SportCode.BASKETBALL,
        leagueCode=league,
        workflowCode=workflow_code,
        compatibleWorkflowIds=(compatible_id,),
        displayName=f"{league.value} Game Forecasting — Planned",
        description="Planned possession-based basketball workflow; no governed live project is available.",
        availability=WorkflowAvailability.PLANNED,
        participantType=ParticipantType.TEAM,
        projectTemplateSelectable=False,
        liveNavigationVisible=False,
        modelingEnabled=False,
        simulationEnabled=False,
        readinessMessage="Planned only; governed datasets, workflow implementation, and promotion authority are not registered.",
        supportedDatasetGrains=("POSSESSION", "STINT", "PLAYER_GAME", "TEAM_GAME", "GAME"),
        supportedPredictionUnits=("POSSESSION", "STINT", "PLAYER_GAME", "TEAM_GAME", "GAME"),
        supportedTargets=("HOME_AWAY_SCORE", "HOME_WIN_PROBABILITY", "SCORE_MARGIN", "TOTAL_POINTS"),
        forecastLifecycles=("PREGAME_PLANNED",),
        canonicalIdentityContract=CanonicalIdentityContract(
            contractCode=f"{league.value}_CANONICAL_GAME_TEAM_PLAYER_POSSESSION_IDENTITY_V1",
            requiredKeys=("canonical_game_id", "canonical_team_id", "canonical_player_id", "canonical_possession_id"),
        ),
        requiredEvidenceFamilies=(),
        optionalEvidenceFamilies=("LINEUPS", "PLAYER_AVAILABILITY", "REST", "BACK_TO_BACKS", "POSSESSION_STATE"),
        pointInTimePolicy=PointInTimePolicy(
            cutoffRule="Planned pregame evidence must predate tipoff.",
            eventTimeFields=("scheduled_tipoff", "source_cutoff"),
            missingEvidencePolicy="BLOCK_UNTIL_GOVERNED_EVIDENCE_EXISTS",
        ),
        workflowStages=(WorkflowStage(
            stageCode=f"{league.value.lower()}-planned",
            displayName="Planned basketball workflow",
            description="Roadmap metadata only.",
            availability=WorkflowAvailability.PLANNED,
            requiredEvidenceFamilies=(),
            componentCode="NO_LIVE_COMPONENT",
            completionContract="UNAVAILABLE_UNTIL_SEPARATE_GOVERNED_IMPLEMENTATION",
        ),),
        developmentSteps=("PLANNED_DATA_FOUNDATION", "PLANNED_POSSESSION_MODELING", "PLANNED_GAME_SIMULATION"),
        validationTemplates=(ValidationTemplate(
            templateCode=f"{league.value}_PLANNED_CHRONOLOGICAL_GAME_GROUPED_V1",
            displayName="Planned basketball chronological validation",
            groupingUnit="CANONICAL_GAME",
            rules=("DATE_ATOMIC", "GAME_GROUPED", "SEASON_HOLDOUT", "NO_RANDOM_EVENT_SPLIT"),
        ),),
        candidateModelFamilies=(),
        primaryMetrics=("GAME_WIN_LOG_LOSS", "SCORE_MAE"),
        secondaryMetrics=("CALIBRATION_ERROR", "TOTAL_POINTS_MAE"),
        calibrationRequirements=("NOT_AVAILABLE_UNTIL_IMPLEMENTED",),
        simulatorAdapterCode="BASKETBALL_POSSESSION_SIMULATOR_PLANNED",
        supportedMarketTypes=("MONEYLINE", "POINT_SPREAD", "GAME_TOTAL"),
        deploymentRestrictions=("PLANNED", "NOT_SELECTABLE", "NOT_EXECUTABLE", "NO_MODELING"),
        monitoringMetrics=(),
        documentationRequirements=("SEPARATE_DATA_FOUNDATION_REQUIRED", "SEPARATE_WORKFLOW_ACCEPTANCE_REQUIRED"),
    )


NBA_WORKFLOW_MANIFEST = _manifest(LeagueCode.NBA, "NBA_GAME_FORECAST_WORKFLOW_V1", "nba-forecasting")
WNBA_WORKFLOW_MANIFEST = _manifest(LeagueCode.WNBA, "WNBA_GAME_FORECAST_WORKFLOW_V1", "wnba-forecasting")


__all__ = ["NBA_WORKFLOW_MANIFEST", "WNBA_WORKFLOW_MANIFEST"]

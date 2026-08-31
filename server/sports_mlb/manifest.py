"""The exact MLB reference workflow manifest for the current program."""

from __future__ import annotations

from ..sports_shared.contracts import (
    CanonicalIdentityContract,
    LeagueCode,
    ParticipantType,
    PointInTimePolicy,
    SPORT_WORKFLOW_MANIFEST_V1,
    SportCode,
    SportWorkflowManifest,
    ValidationTemplate,
    WorkflowAvailability,
    WorkflowStage,
)


def _stage(code: str, name: str, description: str, component: str, evidence: tuple[str, ...]) -> WorkflowStage:
    return WorkflowStage(
        stageCode=code,
        displayName=name,
        description=description,
        availability=WorkflowAvailability.ENABLED,
        requiredEvidenceFamilies=evidence,
        componentCode=component,
        completionContract="PROJECT_BOUND_EVIDENCE_AND_EXPLICIT_USER_DECISION",
    )


MLB_WORKFLOW_MANIFEST = SportWorkflowManifest(
    schemaVersion=SPORT_WORKFLOW_MANIFEST_V1,
    sportCode=SportCode.BASEBALL,
    leagueCode=LeagueCode.MLB,
    workflowCode="MLB_GAME_FORECAST_WORKFLOW_V1",
    compatibleWorkflowIds=("mlb-forecasting",),
    displayName="MLB Game Forecasting",
    description="Governed plate-appearance-to-whole-game MLB research workflow.",
    availability=WorkflowAvailability.ENABLED,
    participantType=ParticipantType.TEAM,
    projectTemplateSelectable=True,
    liveNavigationVisible=True,
    modelingEnabled=True,
    simulationEnabled=True,
    readinessMessage="Enabled for project-bound governed MLB evidence; final OOT and promotion remain separately gated.",
    supportedDatasetGrains=("PLATE_APPEARANCE", "PLAYER_GAME", "TEAM_GAME", "GAME"),
    supportedPredictionUnits=("PLATE_APPEARANCE", "PLAYER_GAME", "TEAM_GAME", "GAME"),
    supportedTargets=(
        "EIGHT_CLASS_PLATE_APPEARANCE_OUTCOME",
        "JOINT_SCORE_DISTRIBUTION",
        "HOME_WIN_PROBABILITY",
        "RUN_DIFFERENTIAL",
        "TOTAL_RUNS",
    ),
    forecastLifecycles=("PREGAME", "FINAL_PREGAME", "POSTGAME_EVALUATION"),
    canonicalIdentityContract=CanonicalIdentityContract(
        contractCode="MLB_CANONICAL_GAME_TEAM_PLAYER_PA_IDENTITY_V1",
        requiredKeys=("canonical_game_id", "canonical_team_id", "canonical_player_id", "canonical_pa_id"),
    ),
    requiredEvidenceFamilies=(
        "BATTER_STATE",
        "PITCHER_STATE",
        "LINEUPS",
        "BULLPEN",
        "PARK",
        "GAME_CONTEXT",
    ),
    optionalEvidenceFamilies=("WEATHER", "TRAVEL", "CALENDAR", "CIRCADIAN_STATE", "MARKET_COMPARISON"),
    pointInTimePolicy=PointInTimePolicy(
        cutoffRule="Every predictor must be observable before the target plate appearance or governed pregame cutoff.",
        eventTimeFields=("game_date", "scheduled_first_pitch", "source_cutoff", "derivation_cutoff"),
        missingEvidencePolicy="PRESERVE_ROW_WITH_EXPLICIT_MISSINGNESS_AND_FOLD_LOCAL_TREATMENT",
    ),
    workflowStages=(
        _stage("mlb-01", "Project & Forecast Objective", "Bind the MLB target, population, clock, and success criteria.", "MLB_OBJECTIVE", ()),
        _stage("mlb-02", "Data Evidence & Quality", "Review exact source and Gold authority, identity, coverage, and point-in-time quality.", "MLB_DATA_QUALITY", ("GAME_CONTEXT",)),
        _stage("mlb-03", "PA Model Development", "Develop the governed eight-class plate-appearance model inside the project-bound cockpit.", "MLB_PA_MODELING_COCKPIT", ("BATTER_STATE", "PITCHER_STATE")),
        _stage("mlb-04", "Participation & Game Context", "Govern lineups, starter duration, and bullpen participation inputs.", "MLB_PARTICIPATION_CONTEXT", ("LINEUPS", "BULLPEN")),
        _stage("mlb-05", "Game Simulation", "Convert PA probabilities and participation into whole-game score distributions.", "MLB_GAME_SIMULATION", ("LINEUPS", "BULLPEN", "GAME_CONTEXT")),
        _stage("mlb-06", "Candidate Comparison", "Compare coherent PA, participation, simulation, and ensemble systems.", "MLB_CANDIDATE_COMPARISON", ()),
        _stage("mlb-07", "Validation & Calibration", "Run game-grouped chronological validation and governed calibration.", "MLB_VALIDATION_CALIBRATION", ()),
        _stage("mlb-08", "Champion Decision", "Record the evidence-bound champion/challenger decision without automatic promotion.", "MLB_CHAMPION_DECISION", ()),
        _stage("mlb-09", "Export / Deployment", "Package only an explicitly approved immutable forecasting graph.", "MLB_EXPORT_DEPLOYMENT", ()),
    ),
    developmentSteps=(
        "OBJECTIVE",
        "DATA_AND_POPULATION",
        "EDA_DATA_PROFILE",
        "OUTLIERS",
        "MISSING_VALUES",
        "FEATURE_ENGINEERING",
        "PLAYER_SEGMENTATION",
        "SPLIT_AND_BALANCE",
        "MODEL_LAB",
        "TUNING",
        "EVALUATION",
        "CALIBRATION",
        "SIMULATION_IMPACT",
        "CHAMPION_CHALLENGER",
        "REGISTRY_AND_EVIDENCE",
    ),
    validationTemplates=(
        ValidationTemplate(
            templateCode="MLB_EXPANDING_DATE_ATOMIC_GAME_GROUPED_V1",
            displayName="MLB rolling-origin chronological validation",
            groupingUnit="CANONICAL_GAME",
            rules=("CHRONOLOGICAL", "DATE_ATOMIC", "CANONICAL_GAME_GROUPED", "EXPANDING_WINDOW", "FINAL_OOT_LOCKED"),
        ),
    ),
    candidateModelFamilies=("REGULARIZED_LOGISTIC", "HISTOGRAM_GRADIENT_BOOSTING", "EXTRA_TREES", "XGBOOST", "GOVERNED_ENSEMBLE"),
    primaryMetrics=("MULTICLASS_LOG_LOSS", "SUMMED_BRIER", "CALIBRATION_ERROR", "GAME_WIN_LOG_LOSS"),
    secondaryMetrics=("CLASS_CALIBRATION", "ACCURACY", "MACRO_F1", "RUN_MAE", "TOTAL_RUN_MAE"),
    calibrationRequirements=("OOF_ONLY_SELECTION", "FINAL_OOT_NOT_USED_FOR_SELECTION", "CLASS_AND_GAME_LEVEL_RELIABILITY"),
    simulatorAdapterCode="MLB_WHOLE_GAME_MONTE_CARLO_SIMULATOR",
    supportedMarketTypes=("FULL_GAME_MONEYLINE", "FIRST_FIVE_MONEYLINE", "RUN_LINE", "FULL_GAME_TOTAL", "FIRST_FIVE_TOTAL"),
    deploymentRestrictions=("NO_AUTOMATIC_PROMOTION", "FINAL_OOT_LOCKED_UNTIL_GOVERNED_EVALUATION", "MARKETS_ARE_POST_MODEL_COMPARISONS", "MONTE_CARLO_THEATER_REQUIRES_SEPARATE_LIVE_PAYLOAD_AUTHORITY"),
    monitoringMetrics=("LOG_LOSS", "BRIER", "CALIBRATION", "RUN_MAE", "TOTAL_RUN_MAE", "FEATURE_DRIFT"),
    documentationRequirements=("DATASET_LINEAGE", "FEATURE_CONTRACT", "TEMPORAL_SPLIT", "CALIBRATION", "SIMULATION_ASSUMPTIONS", "PROMOTION_DECISION"),
)


__all__ = ["MLB_WORKFLOW_MANIFEST"]

"""NFL Phase-1 workflow metadata bound to existing research-only assets."""

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


def _research_stage(code: str, name: str, description: str, component: str, *, blocked: bool = False) -> WorkflowStage:
    return WorkflowStage(
        stageCode=code,
        displayName=name,
        description=description,
        availability=(
            WorkflowAvailability.BLOCKED_BY_MISSING_EVIDENCE
            if blocked
            else WorkflowAvailability.RESEARCH_ONLY
        ),
        requiredEvidenceFamilies=(),
        componentCode=component,
        completionContract="READ_ONLY_RESEARCH_EVIDENCE; NO PROJECT ACTIVATION OR PROMOTION",
    )


NFL_WORKFLOW_MANIFEST = SportWorkflowManifest(
    schemaVersion=SPORT_WORKFLOW_MANIFEST_V1,
    sportCode=SportCode.FOOTBALL,
    leagueCode=LeagueCode.NFL,
    workflowCode="NFL_GAME_FORECAST_WORKFLOW_V1",
    compatibleWorkflowIds=("nfl-forecasting",),
    displayName="NFL Game Forecasting Research Shadow",
    description="Football-specific game, score-distribution, and prospective research-shadow workflow metadata.",
    availability=WorkflowAvailability.RESEARCH_ONLY,
    participantType=ParticipantType.TEAM,
    projectTemplateSelectable=False,
    liveNavigationVisible=False,
    modelingEnabled=False,
    simulationEnabled=False,
    readinessMessage="Governed NFL foundation and M1 research-shadow assets exist, but their registrations are read-only, not workspace-activation eligible, and not promoted.",
    supportedDatasetGrains=("PLAY", "DRIVE", "PLAYER_GAME", "TEAM_GAME", "GAME_PREGAME"),
    supportedPredictionUnits=("PLAY", "DRIVE", "PLAYER_GAME", "TEAM_GAME", "GAME"),
    supportedTargets=("HOME_AWAY_SCORE", "HOME_WIN_PROBABILITY", "MARGIN", "TOTAL_POINTS", "SPREAD_COVER_PROBABILITY", "TOTALS_PROBABILITY"),
    forecastLifecycles=("PREGAME_RESEARCH_SHADOW", "FINAL_PREGAME_RESEARCH_SHADOW", "POSTGAME_RESEARCH_EVALUATION"),
    canonicalIdentityContract=CanonicalIdentityContract(
        contractCode="NFL_CANONICAL_GAME_TEAM_PLAYER_PLAY_IDENTITY_V1",
        requiredKeys=("canonical_game_id", "canonical_team_id", "canonical_player_id", "canonical_play_id"),
    ),
    requiredEvidenceFamilies=("GAME_PREGAME_GOLD", "FINAL_SCORE_TRUTH", "TEAM_STRENGTH", "SCHEDULE_AND_REST"),
    optionalEvidenceFamilies=("QUARTERBACK_DEPTH_CHART", "INJURY_AVAILABILITY", "PLAY_DRIVE_EFFICIENCY", "TRAVEL", "WEATHER", "VENUE", "COACHING", "SCHEDULE_STRENGTH", "MARKET_COMPARISON_AFTER_SCORING"),
    pointInTimePolicy=PointInTimePolicy(
        cutoffRule="Use only evidence available before scheduled kickoff; never use target-game plays, participation, snaps, or score.",
        eventTimeFields=("game_date", "scheduled_kickoff", "source_cutoff", "forecast_cutoff"),
        missingEvidencePolicy="EXPLICIT_SOURCE_ERA_AND_MISSING_HISTORY_INDICATORS",
    ),
    workflowStages=(
        _research_stage("nfl-01", "NFL Forecast Objective", "Review the football game-level target and research-shadow boundary.", "NFL_OBJECTIVE"),
        _research_stage("nfl-02", "NFL Data Evidence & Quality", "Review the governed NFL pregame and play-state Gold authorities.", "NFL_DATA_QUALITY"),
        _research_stage("nfl-03", "NFL Game Forecast Model Research", "Inspect existing chronological M1 benchmark and frozen research artifact lineage.", "NFL_GAME_MODEL_RESEARCH"),
        _research_stage("nfl-04", "Roster, Availability & Game Context", "Govern quarterback, depth-chart, injury, rest, venue, and weather evidence.", "NFL_ROSTER_AVAILABILITY_CONTEXT", blocked=True),
        _research_stage("nfl-05", "Football Score Distribution Simulation", "Define football score, margin, and total distributions without enabling a visual simulator.", "NFL_SCORE_DISTRIBUTION_RESEARCH"),
        _research_stage("nfl-06", "NFL Candidate Comparison", "Compare football game-level candidates only within governed chronological evidence.", "NFL_CANDIDATE_COMPARISON"),
        _research_stage("nfl-07", "Weekly Validation & Calibration", "Use weekly, game-grouped, season-aware chronological validation.", "NFL_VALIDATION_CALIBRATION"),
        _research_stage("nfl-08", "NFL Research Decision", "Preserve the NOT_PROMOTED research conclusion and market comparison.", "NFL_RESEARCH_DECISION"),
        _research_stage("nfl-09", "NFL Research Export", "Expose only immutable non-executable research-shadow metadata.", "NFL_RESEARCH_EXPORT"),
    ),
    developmentSteps=("OBJECTIVE", "GAME_POPULATION", "TEAM_QUARTERBACK_PROFILE", "ROSTER_AVAILABILITY", "FEATURE_TIERS", "RECENCY_STRATEGY", "TEMPORAL_SPLIT", "SCORE_MODEL_LAB", "DISTRIBUTION_VALIDATION", "CALIBRATION", "MARKET_COMPARISON", "RESEARCH_DECISION", "RESEARCH_ARTIFACT_LINEAGE"),
    validationTemplates=(
        ValidationTemplate(
            templateCode="NFL_EXPANDING_WEEKLY_GAME_GROUPED_V1",
            displayName="NFL season-aware expanding validation",
            groupingUnit="CANONICAL_GAME",
            rules=("WEEKLY_SLATES", "SEASON_AND_WEEK_BOUNDARIES", "GAME_GROUPED_CHRONOLOGY", "LOW_SAMPLE_SIZE_DISCLOSURE", "PROSPECTIVE_SEASON_HOLDOUT", "NO_RANDOM_EVENT_SPLIT"),
        ),
    ),
    candidateModelFamilies=("LEAGUE_PRIOR", "ELO", "REGULARIZED_SCORE_MODEL", "HISTOGRAM_GRADIENT_BOOSTING", "EXTRA_TREES", "XGBOOST_RESEARCH_SHADOW", "GOVERNED_ENSEMBLE"),
    primaryMetrics=("HOME_WIN_LOG_LOSS", "BRIER", "JOINT_SCORE_NLL", "HOME_AWAY_POINTS_MAE"),
    secondaryMetrics=("CALIBRATION_ERROR", "MARGIN_MAE", "TOTAL_POINTS_MAE", "DISTRIBUTION_COVERAGE", "CRPS"),
    calibrationRequirements=("CHRONOLOGICAL_OOF_ONLY", "FINAL_SEASON_OOT_UNTOUCHED", "GAME_LEVEL_CALIBRATION"),
    simulatorAdapterCode="NFL_MONTE_CARLO_FIELD_SIMULATOR",
    supportedMarketTypes=("MONEYLINE", "POINT_SPREAD", "GAME_TOTAL"),
    deploymentRestrictions=("RESEARCH_SHADOW", "NOT_PROMOTED", "NOT_EXECUTABLE", "NO_WORKSPACE_DATASET_ACTIVATION", "NO_OFFICIAL_PICKS", "MARKETS_ARE_POST_MODEL_COMPARISONS"),
    monitoringMetrics=("HOME_WIN_LOG_LOSS", "BRIER", "CALIBRATION", "HOME_AWAY_POINTS_MAE", "MARGIN_MAE", "TOTAL_POINTS_MAE"),
    documentationRequirements=("FOUNDATION_MANIFEST", "SOURCE_ERA_REPORT", "TEMPORAL_SPLIT", "MODEL_MANIFEST_AND_BINARY_HASH", "MARKET_BENCHMARK_CONCLUSION", "RESEARCH_SHADOW_STATUS"),
)


__all__ = ["NFL_WORKFLOW_MANIFEST"]

import type {
  LeagueCode,
  ParticipantType,
  SportCode,
  WorkflowAvailability,
} from "./sportRegistry";

export type WorkflowStageManifest = {
  code: string;
  name: string;
  description: string;
  availability: WorkflowAvailability;
  requiredEvidence: readonly string[];
  developmentSteps: readonly string[];
};

export type DevelopmentStepManifest = {
  code: string;
  name: string;
  applies: boolean;
  availability: WorkflowAvailability;
  componentCode: string;
};

export type SportWorkflowManifestV1 = {
  schemaVersion: "SPORT_WORKFLOW_MANIFEST_V1";
  sportCode: SportCode;
  leagueCode: LeagueCode;
  workflowCode: string;
  displayName: string;
  description: string;
  availability: WorkflowAvailability;
  participantType: ParticipantType;
  supportedPredictionUnits: readonly string[];
  supportedTargets: readonly string[];
  forecastLifecycles: readonly string[];
  canonicalIdentityContract: string;
  requiredEvidenceFamilies: readonly string[];
  optionalEvidenceFamilies: readonly string[];
  pointInTimePolicy: string;
  workflowStages: readonly WorkflowStageManifest[];
  developmentSteps: readonly DevelopmentStepManifest[];
  validationTemplates: readonly string[];
  candidateModelFamilies: readonly string[];
  primaryMetrics: readonly string[];
  secondaryMetrics: readonly string[];
  calibrationRequirements: readonly string[];
  simulatorAdapterCode: string;
  supportedMarketTypes: readonly string[];
  deploymentRestrictions: readonly string[];
  monitoringMetrics: readonly string[];
  documentationRequirements: readonly string[];
};

const SHARED_STAGE_CODES = [
  ["PROJECT_FORECAST_OBJECTIVE", "Project & Forecast Objective"],
  ["DATA_EVIDENCE_QUALITY", "Data Evidence & Quality"],
  ["MODEL_DEVELOPMENT", "Model Development"],
  ["PARTICIPATION_EVENT_CONTEXT", "Participation / Roster & Event Context"],
  ["SIMULATION", "Simulation"],
  ["CANDIDATE_COMPARISON", "Candidate Comparison"],
  ["VALIDATION_CALIBRATION", "Validation & Calibration"],
  ["CHAMPION_DECISION", "Champion Decision"],
  ["EXPORT_DEPLOYMENT", "Export / Deployment"],
] as const;

function stages(
  availability: WorkflowAvailability,
  stage4Name: string,
  stepPrefix: string,
): WorkflowStageManifest[] {
  return SHARED_STAGE_CODES.map(([code, name], index) => ({
    code,
    name: index === 3 ? stage4Name : name,
    description: index === 2
      ? "Run the sport-owned development sequence without leaking validation or sealed evidence."
      : `Governed ${name.toLowerCase()} for this sport package.`,
    availability,
    requiredEvidence: index === 0 ? [] : [`${stepPrefix}_PRIOR_STAGE_EVIDENCE`],
    developmentSteps: index === 2 ? [
      `${stepPrefix}_OBJECTIVE`,
      `${stepPrefix}_DATA_POPULATION`,
      `${stepPrefix}_DATA_PROFILE`,
      `${stepPrefix}_OUTLIERS`,
      `${stepPrefix}_MISSING_VALUES`,
      `${stepPrefix}_FEATURE_ENGINEERING`,
      `${stepPrefix}_SEGMENTATION`,
      `${stepPrefix}_TEMPORAL_SPLIT`,
      `${stepPrefix}_MODEL_LABORATORY`,
      `${stepPrefix}_EVALUATION`,
      `${stepPrefix}_CALIBRATION`,
      `${stepPrefix}_SIMULATION_IMPACT`,
      `${stepPrefix}_CHAMPION_CHALLENGER`,
      `${stepPrefix}_REGISTRY_EVIDENCE`,
    ] : [],
  }));
}

function developmentSteps(
  prefix: string,
  availability: WorkflowAvailability,
  segmentation: string,
  laboratory: string,
): DevelopmentStepManifest[] {
  const names = [
    "Objective",
    "Data & Population",
    "Data Profile",
    "Outliers",
    "Missing Values",
    "Feature Engineering",
    segmentation,
    "Temporal Split",
    laboratory,
    "Evaluation",
    "Calibration",
    "Simulation Impact",
    "Champion / Challenger",
    "Registry & Evidence",
  ];
  return names.map((name, index) => ({
    code: `${prefix}_${[
      "OBJECTIVE", "DATA_POPULATION", "DATA_PROFILE", "OUTLIERS", "MISSING_VALUES",
      "FEATURE_ENGINEERING", "SEGMENTATION", "TEMPORAL_SPLIT", "MODEL_LABORATORY",
      "EVALUATION", "CALIBRATION", "SIMULATION_IMPACT",
      "CHAMPION_CHALLENGER", "REGISTRY_EVIDENCE",
    ][index]}`,
    name,
    applies: true,
    availability,
    componentCode: `${prefix}_${String(index + 1).padStart(2, "0")}_COMPONENT`,
  }));
}

export const MLB_GAME_FORECAST_WORKFLOW_V1: SportWorkflowManifestV1 = {
  schemaVersion: "SPORT_WORKFLOW_MANIFEST_V1",
  sportCode: "BASEBALL",
  leagueCode: "MLB",
  workflowCode: "MLB_GAME_FORECAST_WORKFLOW_V1",
  displayName: "MLB Game Forecast Workflow",
  description: "The governed MLB reference workflow, including the current nine-stage program and fourteen-step development cockpit.",
  availability: "ENABLED",
  participantType: "TEAM",
  supportedPredictionUnits: ["PLATE_APPEARANCE", "PLAYER_GAME", "TEAM_GAME", "GAME"],
  supportedTargets: ["EIGHT_CLASS_PA_OUTCOME", "JOINT_SCORE_DISTRIBUTION", "HOME_WIN_PROBABILITY", "RUN_DIFFERENTIAL", "TOTAL_RUNS"],
  forecastLifecycles: ["PREGAME_EARLY", "PREGAME_FINAL", "POSTGAME_EVALUATION"],
  canonicalIdentityContract: "MLB_CANONICAL_GAME_PLAYER_TEAM_IDENTITY_V1",
  requiredEvidenceFamilies: ["GAME", "PLATE_APPEARANCE", "BATTER_STATE", "PITCHER_STATE", "LINEUP", "STARTER", "BULLPEN"],
  optionalEvidenceFamilies: ["PARK", "WEATHER", "TRAVEL", "CALENDAR", "CIRCADIAN", "GAME_CONTEXT"],
  pointInTimePolicy: "Use evidence timestamped before the forecast cutoff; keep chronological game-date groups and final OOT sealed.",
  workflowStages: stages("ENABLED", "Participation & Game Context", "MLB"),
  developmentSteps: developmentSteps("MLB", "ENABLED", "Player Segmentation", "Plate-Appearance Model Laboratory"),
  validationTemplates: ["CHRONOLOGICAL", "DATE_ATOMIC", "CANONICAL_GAME_GROUPED", "EXPANDING_WINDOW", "FINAL_OOT_LOCKED"],
  candidateModelFamilies: ["MULTINOMIAL_LOGISTIC", "HISTOGRAM_GRADIENT_BOOSTING", "EXTRA_TREES", "SPORT_SPECIFIC_ENSEMBLE"],
  primaryMetrics: ["MULTICLASS_LOG_LOSS", "SUMMED_BRIER", "CALIBRATION_ERROR"],
  secondaryMetrics: ["CLASS_CALIBRATION", "GAME_LOG_LOSS", "RUN_MAE"],
  calibrationRequirements: ["OOF_ONLY", "CLASSWISE_RELIABILITY", "NO_FINAL_OOT_SELECTION"],
  simulatorAdapterCode: "MLB_GAME_SIMULATOR",
  supportedMarketTypes: ["MONEYLINE", "RUN_LINE", "TOTAL"],
  deploymentRestrictions: ["NO_AUTOMATIC_PROMOTION", "MARKETS_POST_MODEL_ONLY", "FINAL_OOT_LOCKED"],
  monitoringMetrics: ["LOG_LOSS", "BRIER", "ECE", "RUN_MAE", "DRIFT"],
  documentationRequirements: ["DATA_LINEAGE", "FEATURE_CONTRACT", "TEMPORAL_SPLIT", "LIMITATIONS", "MODEL_CARD"],
};

export const NFL_GAME_FORECAST_WORKFLOW_V1: SportWorkflowManifestV1 = {
  schemaVersion: "SPORT_WORKFLOW_MANIFEST_V1",
  sportCode: "FOOTBALL",
  leagueCode: "NFL",
  workflowCode: "NFL_GAME_FORECAST_WORKFLOW_V1",
  displayName: "NFL Game Forecast Workflow",
  description: "A research-only NFL workflow contract with weekly, game-level chronology. It is not an MLB plate-appearance workflow and is not deployment authority.",
  availability: "RESEARCH_ONLY",
  participantType: "TEAM",
  supportedPredictionUnits: ["PLAY", "DRIVE", "PLAYER_GAME", "TEAM_GAME", "GAME"],
  supportedTargets: ["HOME_AWAY_SCORE", "HOME_WIN_PROBABILITY", "MARGIN", "TOTAL_POINTS", "SPREAD_COVER_PROBABILITY", "TOTALS_PROBABILITY"],
  forecastLifecycles: ["PREGAME_EARLY", "PREGAME_FINAL", "POSTGAME_EVALUATION"],
  canonicalIdentityContract: "NFL_CANONICAL_GAME_PLAYER_TEAM_IDENTITY_V1",
  requiredEvidenceFamilies: ["SCHEDULE", "TEAM_GAME", "QUARTERBACK", "ROSTER", "REST", "VENUE"],
  optionalEvidenceFamilies: ["PLAY_BY_PLAY", "DRIVE", "INJURY_AVAILABILITY", "SNAP_SHARE", "WEATHER", "TRAVEL", "COACHING"],
  pointInTimePolicy: "Group games by weekly slate and kickoff; use only evidence known before kickoff and never randomly split events from one game.",
  workflowStages: stages("RESEARCH_ONLY", "Roster, Availability & Game Context", "NFL"),
  developmentSteps: developmentSteps("NFL", "RESEARCH_ONLY", "Team / Quarterback Segmentation", "Game Forecast Model Laboratory"),
  validationTemplates: ["WEEKLY_SLATE_GROUPED", "SEASON_BOUNDARY_AWARE", "EXPANDING_WINDOW", "PROSPECTIVE_SEASON_HOLDOUT", "NO_RANDOM_EVENT_SPLIT"],
  candidateModelFamilies: ["ELO_BASELINE", "REGULARIZED_SCORE_MODEL", "HISTOGRAM_GRADIENT_BOOSTING", "EXTRA_TREES", "XGBOOST_WHEN_GOVERNED"],
  primaryMetrics: ["HOME_WIN_LOG_LOSS", "BRIER", "JOINT_SCORE_NLL"],
  secondaryMetrics: ["HOME_POINTS_MAE", "AWAY_POINTS_MAE", "MARGIN_MAE", "TOTAL_POINTS_MAE"],
  calibrationRequirements: ["OOF_ONLY", "WEEKLY_RELIABILITY", "NO_PROSPECTIVE_SELECTION"],
  simulatorAdapterCode: "NFL_MONTE_CARLO_FIELD_SIMULATOR",
  supportedMarketTypes: ["MONEYLINE", "SPREAD", "TOTAL"],
  deploymentRestrictions: ["RESEARCH_ONLY", "NOT_PROMOTED", "NO_OFFICIAL_BANKROLL", "MARKETS_POST_MODEL_ONLY"],
  monitoringMetrics: ["LOG_LOSS", "BRIER", "CALIBRATION", "SCORE_MAE", "MARKET_COMPARISON"],
  documentationRequirements: ["DATA_LINEAGE", "SOURCE_ERA", "FEATURE_CONTRACT", "TEMPORAL_SPLIT", "LIMITATIONS", "MODEL_CARD"],
};

function plannedManifest(
  sportCode: SportCode,
  leagueCode: LeagueCode,
  workflowCode: string,
  displayName: string,
  participantType: ParticipantType,
  predictionUnits: readonly string[],
  targets: readonly string[],
  stage4: string,
  segmentation: string,
  laboratory: string,
  simulator: string,
): SportWorkflowManifestV1 {
  return {
    schemaVersion: "SPORT_WORKFLOW_MANIFEST_V1",
    sportCode,
    leagueCode,
    workflowCode,
    displayName,
    description: "Planned manifest metadata only. No governed evidence, functional workflow, model, simulation, or completion state is claimed.",
    availability: "PLANNED",
    participantType,
    supportedPredictionUnits: predictionUnits,
    supportedTargets: targets,
    forecastLifecycles: ["PREGAME"],
    canonicalIdentityContract: `${leagueCode}_IDENTITY_CONTRACT_NOT_CONFIGURED`,
    requiredEvidenceFamilies: [],
    optionalEvidenceFamilies: [],
    pointInTimePolicy: "NOT_CONFIGURED",
    workflowStages: stages("PLANNED", stage4, leagueCode),
    developmentSteps: developmentSteps(leagueCode, "PLANNED", segmentation, laboratory),
    validationTemplates: [],
    candidateModelFamilies: [],
    primaryMetrics: [],
    secondaryMetrics: [],
    calibrationRequirements: [],
    simulatorAdapterCode: simulator,
    supportedMarketTypes: [],
    deploymentRestrictions: ["PLANNED", "NOT_SELECTABLE", "NOT_EXECUTABLE"],
    monitoringMetrics: [],
    documentationRequirements: ["FUTURE_EVIDENCE_AND_RIGHTS_REVIEW"],
  };
}

export const NBA_GAME_FORECAST_WORKFLOW_V1 = plannedManifest(
  "BASKETBALL", "NBA", "NBA_GAME_FORECAST_WORKFLOW_V1", "NBA Game Forecast Workflow", "TEAM",
  ["POSSESSION", "STINT", "PLAYER_GAME", "TEAM_GAME", "GAME"], ["SCORE_MARGIN", "TOTAL_POINTS", "HOME_WIN_PROBABILITY"],
  "Roster, Rotation & Game Context", "Lineup / Rotation Segmentation", "Possession Model Laboratory", "NBA_POSSESSION_SIMULATOR_NOT_CONFIGURED",
);

export const WNBA_GAME_FORECAST_WORKFLOW_V1 = plannedManifest(
  "BASKETBALL", "WNBA", "WNBA_GAME_FORECAST_WORKFLOW_V1", "WNBA Game Forecast Workflow", "TEAM",
  ["POSSESSION", "STINT", "PLAYER_GAME", "TEAM_GAME", "GAME"], ["SCORE_MARGIN", "TOTAL_POINTS", "HOME_WIN_PROBABILITY"],
  "Roster, Rotation & Game Context", "Lineup / Rotation Segmentation", "Possession Model Laboratory", "WNBA_POSSESSION_SIMULATOR_NOT_CONFIGURED",
);

export const UFC_BOUT_FORECAST_WORKFLOW_V1 = plannedManifest(
  "MMA", "UFC", "UFC_BOUT_FORECAST_WORKFLOW_V1", "UFC Bout Forecast Workflow", "INDIVIDUAL",
  ["FIGHTER_BOUT", "ROUND", "BOUT_STATE"], ["BOUT_WINNER", "METHOD", "ROUND", "DURATION"],
  "Fighter Availability, Camp & Bout Context", "Fighter Style / Matchup Segmentation", "Bout Model Laboratory", "UFC_ROUND_FINISH_SIMULATOR_NOT_CONFIGURED",
);

export const SPORT_WORKFLOW_MANIFEST_V1 = [
  MLB_GAME_FORECAST_WORKFLOW_V1,
  NFL_GAME_FORECAST_WORKFLOW_V1,
  NBA_GAME_FORECAST_WORKFLOW_V1,
  WNBA_GAME_FORECAST_WORKFLOW_V1,
  UFC_BOUT_FORECAST_WORKFLOW_V1,
] as const;

export function workflowManifestForLeague(leagueCode: LeagueCode) {
  return SPORT_WORKFLOW_MANIFEST_V1.find((manifest) => manifest.leagueCode === leagueCode);
}

export function workflowManifestForCode(workflowCode: string | undefined) {
  return SPORT_WORKFLOW_MANIFEST_V1.find((manifest) => manifest.workflowCode === workflowCode);
}

export function validateSportWorkflowManifestV1(value: unknown): value is SportWorkflowManifestV1 {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  const arrays = [
    "supportedPredictionUnits", "supportedTargets", "forecastLifecycles", "requiredEvidenceFamilies",
    "optionalEvidenceFamilies", "workflowStages", "developmentSteps", "validationTemplates",
    "candidateModelFamilies", "primaryMetrics", "secondaryMetrics", "calibrationRequirements",
    "supportedMarketTypes", "deploymentRestrictions", "monitoringMetrics", "documentationRequirements",
  ];
  return candidate.schemaVersion === "SPORT_WORKFLOW_MANIFEST_V1"
    && typeof candidate.sportCode === "string"
    && typeof candidate.leagueCode === "string"
    && typeof candidate.workflowCode === "string"
    && typeof candidate.displayName === "string"
    && typeof candidate.description === "string"
    && typeof candidate.availability === "string"
    && typeof candidate.participantType === "string"
    && typeof candidate.canonicalIdentityContract === "string"
    && typeof candidate.pointInTimePolicy === "string"
    && typeof candidate.simulatorAdapterCode === "string"
    && arrays.every((key) => Array.isArray(candidate[key]));
}

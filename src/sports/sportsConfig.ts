export type SportsWorkflowKey = "mlb" | "nfl";

export type SportsWorkflowStep = {
  id: string;
  number: number;
  title: string;
  purpose: string;
  prerequisites: string[];
  outputs: string[];
  sections: string[];
  status: "not_configured" | "ready" | "complete";
};

export type SportsWorkflow = {
  key: SportsWorkflowKey;
  id: string;
  sport: string;
  league: string;
  title: string;
  status: "ACTIVE WORKFLOW" | "WORKFLOW FOUNDATION";
  description: string;
  outputs: string[];
  steps: SportsWorkflowStep[];
};

function step(
  workflow: SportsWorkflowKey,
  number: number,
  title: string,
  purpose: string,
  sections: string[],
  outputs: string[],
  prerequisites: string[] = [],
): SportsWorkflowStep {
  return {
    id: `${workflow}-${String(number).padStart(2, "0")}`,
    number,
    title,
    purpose,
    prerequisites,
    outputs,
    sections,
    status: "not_configured",
  };
}

export const MLB_WORKFLOW: SportsWorkflow = {
  key: "mlb",
  id: "mlb-forecasting",
  sport: "Baseball",
  league: "MLB",
  title: "MLB Forecasting",
  status: "ACTIVE WORKFLOW",
  description:
    "Develop player-level true-talent models, plate-appearance probabilities, starter and bullpen usage, base-out transitions, and complete game simulations.",
  outputs: [
    "Win probability",
    "Projected score",
    "Run differential",
    "Total runs",
    "Player outcomes",
    "Run-line and total probabilities",
    "Future player-prop and parlay distributions",
  ],
  steps: [
    step("mlb", 1, "Project & Forecast Contract", "Define the exact forecast decision, evaluation clock, eligible population, and intended outputs before evidence is registered.", ["Forecast target", "Lifecycle", "Research population", "Strict versus enhanced evidence", "Development period", "Intended outputs"], ["Versioned forecast contract"]),
    step("mlb", 2, "Baseball Data Evidence", "Register immutable evidence boundaries for the baseball modeling population.", ["Games", "Plate appearances", "Play transitions", "Batting", "Pitching", "Fielding", "Player priors", "Starter usage", "Bullpen usage", "Weather", "Source rights"], ["SPORTS_DATASET_MANIFEST_V1 reference", "Evidence inventory"], ["Project & Forecast Contract"]),
    step("mlb", 3, "Identity, Coverage & Leakage", "Prove identity coverage and point-in-time integrity before features or labels are used.", ["Player identity", "Team identity", "Game identity", "Lineup coverage", "Starter coverage", "Bullpen coverage", "Event taxonomy", "Source rights", "Point-in-time integrity"], ["Coverage report", "Leakage review"], ["Baseball Data Evidence"]),
    step("mlb", 4, "Hitter & Pitcher State", "Estimate durable talent and time-varying player state without leaking future information.", ["True talent", "Multi-season priors", "Dynamic state", "Platoon effects", "Rookie and minimal-history handling"], ["Hitter state artifacts", "Pitcher state artifacts"], ["Identity, Coverage & Leakage"]),
    step("mlb", 5, "Lineup, Starter & Bullpen Usage", "Model who will participate, when they will participate, and for how long.", ["Projected and confirmed lineup", "Starter-duration model", "Reliever availability", "Bullpen-usage model"], ["Participation scenarios", "Usage distributions"], ["Hitter & Pitcher State"]),
    step("mlb", 6, "Plate-Appearance Models", "Estimate mutually exclusive plate-appearance outcomes from player, matchup, venue, and context state.", ["Hierarchical / empirical-Bayesian event model", "Multinomial logistic baseline", "Gradient-boosted challenger"], ["Calibrated event probabilities", "Candidate comparison"], ["Hitter & Pitcher State", "Lineup, Starter & Bullpen Usage"]),
    step("mlb", 7, "Base-Out Game Simulation", "Propagate event and usage uncertainty through innings and complete games.", ["24 base-out states", "Runner advancement", "Substitutions", "Bullpen transitions", "Extra innings"], ["Home and away score distributions", "Total runs", "Run differential", "Player outcomes"], ["Plate-Appearance Models", "Lineup, Starter & Bullpen Usage"]),
    step("mlb", 8, "Candidate Model Laboratory", "Compare coherent baselines, component challengers, simulators, residual models, and ensembles.", ["Event baseline", "Boosted event model", "Poisson", "Negative Binomial", "Shared-environment count model", "Simulator", "Residual model", "Ensemble"], ["Experiment evidence", "Candidate ranking"], ["Base-Out Game Simulation"]),
    step("mlb", 9, "Temporal Validation", "Evaluate forward-looking performance with sports-native time boundaries.", ["Rolling-origin folds", "Game-date grouping", "Strict versus enhanced population", "Prospective plan"], ["Temporal fold evidence", "Prospective evaluation plan"], ["Candidate Model Laboratory"]),
    step("mlb", 10, "Calibration & Reliability", "Test probability, distribution, subgroup, missingness, and out-of-distribution reliability.", ["Multiclass log loss", "Brier score", "Calibration", "Score-distribution error", "OOD", "Missingness", "Uncertainty"], ["Reliability report", "Calibration artifacts"], ["Temporal Validation"]),
    step("mlb", 11, "Model Graph & Decision", "Select a governed component graph and assign honest lifecycle states.", ["DEVELOPMENT", "RESEARCH CHALLENGER", "RESEARCH CANDIDATE", "SHADOW", "OPERATIONAL", "RETIRED"], ["Approved component DAG", "Selection decision"], ["Calibration & Reliability"]),
    step("mlb", 12, "Export MLB Bundle", "Package the approved graph for future immutable execution in ASP.", ["SPORTS_MODEL_BUNDLE_V1", "Schemas", "Dependencies", "Checksums", "Validation evidence"], ["Immutable MLB model bundle"], ["Model Graph & Decision"]),
  ],
};

export const NFL_WORKFLOW: SportsWorkflow = {
  key: "nfl",
  id: "nfl-forecasting",
  sport: "Professional Football",
  league: "NFL",
  title: "NFL Forecasting",
  status: "WORKFLOW FOUNDATION",
  description:
    "Develop quarterback and roster state, offensive and defensive unit models, coaching tendencies, drive-outcome models, and score and spread simulations.",
  outputs: [
    "Win probability",
    "Margin distribution",
    "Total points",
    "Spread-cover probability",
    "Player outcomes",
    "Future prop and parlay distributions",
  ],
  steps: [
    step("nfl", 1, "Project & Forecast Contract", "Define the forecast clock, target, population, and allowed evidence for the NFL research program.", ["Forecast target", "Lifecycle", "Development seasons", "Evaluation clock", "Intended outputs"], ["Versioned forecast contract"]),
    step("nfl", 2, "NFL Data Evidence", "Register immutable NFL evidence families and their temporal availability.", ["Play-by-play", "Rosters", "Injuries", "Participation", "Snap counts", "Schedules", "Officials", "Trades", "Depth charts", "Weather", "Permitted market evidence"], ["SPORTS_DATASET_MANIFEST_V1 reference", "Evidence inventory"], ["Project & Forecast Contract"]),
    step("nfl", 3, "Identity, Roster Coverage & Leakage", "Validate player, team, game, roster, and transaction identity at each forecast cutoff.", ["Player identity", "Team identity", "Game identity", "Roster coverage", "Transaction timing", "Point-in-time integrity"], ["Coverage report", "Leakage review"], ["NFL Data Evidence"]),
    step("nfl", 4, "Quarterback, Player & Unit State", "Estimate the state of quarterbacks, players, and interacting offensive, defensive, and special-teams units.", ["QB value", "Expected snap share", "Pass offense", "Rush offense", "Pass defense", "Rush defense", "Offensive line", "Pass rush", "Coverage", "Special teams"], ["Player state artifacts", "Unit state artifacts"], ["Identity, Roster Coverage & Leakage"]),
    step("nfl", 5, "Injuries, Participation & Coaching", "Represent availability scenarios, replacement value, pace, and coaching decisions.", ["Practice status", "Active / inactive scenarios", "Replacement value", "Coaching tendencies", "Pace", "Pass rate over expected", "Fourth-down decisions"], ["Participation scenarios", "Coaching policy features"], ["Quarterback, Player & Unit State"]),
    step("nfl", 6, "Drive and Play Models", "Estimate possession outcomes and optional play-level transitions from state and context.", ["Touchdown", "Field goal", "Punt", "Turnover", "Turnover on downs", "Safety", "End of period"], ["Drive outcome probabilities", "Play transition artifacts"], ["Quarterback, Player & Unit State", "Injuries, Participation & Coaching"]),
    step("nfl", 7, "Drive-Level Game Simulation", "Propagate possession, field position, clock, score state, and participation uncertainty to final outcomes.", ["Possessions", "Field position", "Clock", "Score state", "Final margin", "Total points"], ["Joint score distribution", "Margin and total distributions"], ["Drive and Play Models"]),
    step("nfl", 8, "Candidate Model Laboratory", "Compare state, power-rating, drive, boosted, simulation, residual, and ensemble candidates.", ["Dynamic Bayesian team state", "Elo / power baseline", "Drive model", "XGBoost challenger", "Simulator", "Residual model", "Ensemble"], ["Experiment evidence", "Candidate ranking"], ["Drive-Level Game Simulation"]),
    step("nfl", 9, "Temporal Validation", "Evaluate candidates across realistic weekly and seasonal forecast boundaries.", ["Same-week grouping", "Rolling seasons", "Early versus late season", "Backup-QB games", "Prospective evaluation"], ["Temporal fold evidence", "Prospective evaluation plan"], ["Candidate Model Laboratory"]),
    step("nfl", 10, "Calibration & Reliability", "Assess probability, score-distribution, subgroup, injury-scenario, and OOD reliability.", ["Brier score", "Log loss", "Calibration error", "Calibration slope", "Score MAE / RMSE", "Distribution score", "Subgroup stability", "OOD"], ["Reliability report", "Calibration artifacts"], ["Temporal Validation"]),
    step("nfl", 11, "Model Graph & Decision", "Select the component graph and record lifecycle status without overstating readiness.", ["DEVELOPMENT", "RESEARCH CHALLENGER", "RESEARCH CANDIDATE", "SHADOW", "OPERATIONAL", "RETIRED"], ["Approved component DAG", "Selection decision"], ["Calibration & Reliability"]),
    step("nfl", 12, "Export NFL Bundle", "Prepare the approved graph for future immutable execution in ASP.", ["SPORTS_MODEL_BUNDLE_V1", "Schemas", "Dependencies", "Checksums", "Validation evidence"], ["Immutable NFL model bundle"], ["Model Graph & Decision"]),
  ],
};

export const SPORTS_WORKFLOWS = [MLB_WORKFLOW, NFL_WORKFLOW] as const;

export const PLANNED_SPORTS = [
  { name: "College Football", league: "NCAA Football", icon: "CFB" },
  { name: "NBA & WNBA", league: "Professional Basketball", icon: "BKB" },
  { name: "NHL", league: "Professional Hockey", icon: "HKY" },
  { name: "MMA", league: "UFC", icon: "MMA" },
  { name: "Boxing", league: "Boxing — General", icon: "BOX" },
] as const;

export const PIPELINE_NODES = [
  "Sports Data",
  "Player & Team State",
  "Participation & Usage",
  "Event / Drive Models",
  "Game Simulation",
  "Validation & Calibration",
  "ASP Model Bundle",
] as const;

export const LEAGUES_BY_SPORT: Record<string, string[]> = {
  Baseball: ["MLB"],
  "Professional Football": ["NFL"],
  "College Football": ["NCAA Football"],
  Basketball: ["NBA"],
  "Women’s Basketball": ["WNBA"],
  Hockey: ["NHL"],
  MMA: ["UFC"],
  Boxing: ["Boxing — General"],
};

export const TARGETS_BY_WORKFLOW: Record<string, string[]> = {
  "mlb-forecasting": [
    "Joint Score Distribution",
    "Home Win Probability",
    "Run Differential",
    "Total Runs",
    "Plate-Appearance Outcome",
    "Player Outcome Distribution",
  ],
  "nfl-forecasting": [
    "Joint Score Distribution",
    "Home Win Probability",
    "Margin",
    "Total Points",
    "Drive Outcome",
    "Player Outcome Distribution",
  ],
};

export const FORECAST_LIFECYCLES = [
  "Preseason",
  "Pregame — Early",
  "Pregame — Final",
  "In-game",
  "Postgame Evaluation",
  "Player Prop",
  "Market Research",
] as const;

export const sportsWorkflowDefinitions = SPORTS_WORKFLOWS.map((workflow) => ({
  id: workflow.id,
  label: workflow.title,
  description: workflow.description,
  projectType: "custom-workflow" as const,
  steps: workflow.steps.map((item) => ({
    id: item.id,
    label: item.title,
    shortLabel: item.title.split(" ").slice(0, 2).join(" "),
    route: `/workflows/${workflow.key}#${item.id}`,
    description: item.purpose,
    required: true,
    status: "pending" as const,
  })),
}));

export type SportsProjectMetadata = {
  projectId: string;
  sport: string;
  league: string;
  period: string;
  workflowId: "mlb-forecasting" | "nfl-forecasting";
  lifecycle: string;
  primaryTarget: string;
  secondaryTargets: string[];
  researchPurpose: string;
  description: string;
};

const SPORTS_PROJECT_META_PREFIX = "asp-sports-project-meta:";

export function saveSportsProjectMetadata(metadata: SportsProjectMetadata) {
  localStorage.setItem(`${SPORTS_PROJECT_META_PREFIX}${metadata.projectId}`, JSON.stringify(metadata));
}

export function loadSportsProjectMetadata(projectId: string): SportsProjectMetadata | null {
  try {
    const parsed = JSON.parse(localStorage.getItem(`${SPORTS_PROJECT_META_PREFIX}${projectId}`) || "null");
    return parsed?.projectId === projectId ? parsed as SportsProjectMetadata : null;
  } catch {
    return null;
  }
}

export function deleteSportsProjectMetadata(projectId: string) {
  localStorage.removeItem(`${SPORTS_PROJECT_META_PREFIX}${projectId}`);
}

export function isSportsWorkflow(workflowId: string | undefined) {
  return workflowId === "mlb-forecasting" || workflowId === "nfl-forecasting";
}

export function sportsWorkflowForId(workflowId: string | undefined) {
  return SPORTS_WORKFLOWS.find((workflow) => workflow.id === workflowId) ?? MLB_WORKFLOW;
}

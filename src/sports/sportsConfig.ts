import type { SportsPhase4Study } from "./sportsEvidenceApi";

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
    step("mlb", 11, "Model Graph & Decision", "Record a governed research component graph and assign an honest terminal research state.", ["RESEARCH_CHALLENGER", "RESEARCH_BASELINE", "REJECTED_BASELINE", "BLOCKED"], ["Governed research component DAG", "Research selection decision"], ["Calibration & Reliability"]),
    step("mlb", 12, "Export MLB Bundle", "Package the approved graph for future immutable execution in ASP.", ["SPORTS_MODEL_BUNDLE_V1", "Schemas", "Dependencies", "Checksums", "Validation evidence"], ["Immutable MLB model bundle"], ["Model Graph & Decision"]),
  ],
};

export type MlbPaBaselineStepPresentation = Pick<SportsWorkflowStep, "purpose" | "sections" | "outputs" | "prerequisites"> & {
  status: string;
};

const MLB_PA_BASELINE_STEP_PRESENTATIONS: Partial<Record<number, MlbPaBaselineStepPresentation>> = {
  4: {
    status: "BASELINE COMPLETE",
    purpose: "Use only latest eligible Y-minus-one BATTING and PITCHING priors plus explicit missing-history indicators for the bounded PA baseline; dynamic player state and platoon effects remain not configured.",
    sections: ["Y-minus-one BATTING priors", "Y-minus-one PITCHING priors", "Missing-prior indicators", "Fold-local imputation", "Dynamic state — NOT_CONFIGURED", "Platoon effects — NOT_CONFIGURED"],
    outputs: ["MLB_PA_FEATURE_VIEW_V1 prior blocks", "Fold-local preprocessing evidence", "Dynamic state and platoon — NOT_CONFIGURED"],
    prerequisites: ["Identity, Coverage & Leakage"],
  },
  6: {
    status: "BASELINE COMPLETE",
    purpose: "Fit the governed C0 frequency baseline and C1–C4 multinomial-logistic PA candidates from verified component state and Y-minus-one priors only.",
    sections: ["C0 global frequency", "C1 context-only logistic", "C2 batter-prior logistic", "C3 pitcher-prior logistic", "C4 combined logistic", "Handedness / platoon / boosted challenger — NOT_CONFIGURED"],
    outputs: ["Eight-class PA probabilities", "C0–C4 candidate comparison", "No complete game forecast"],
    prerequisites: ["Identity, Coverage & Leakage", "Bounded Y-minus-one prior state"],
  },
  8: {
    status: "PA CANDIDATES COMPLETE",
    purpose: "Compare only the five registered C0–C4 plate-appearance research candidates under the frozen 2024 selection policy.",
    sections: ["C0–C4 PA candidates", "Runtime and convergence", "2024 selection evidence", "Simulator / count / residual / ensemble candidates — NOT_CONFIGURED"],
    outputs: ["C0–C4 experiment evidence", "Selected PA research candidate"],
    prerequisites: ["Plate-Appearance Models"],
  },
  9: {
    status: "RETROSPECTIVE COMPLETE",
    purpose: "Evaluate the internal 2023 tuning split, 2023-to-2024 fold, and frozen through-2024-to-2025 retrospective rolling-origin fold without using 2025 for selection.",
    sections: ["Date-atomic internal 2023 tuning", "2023 → 2024", "Through 2024 → 2025", "No random split", "Prospective evidence — NOT_CONFIGURED"],
    outputs: ["Registered rolling-origin fold evidence", "Prospective evaluation — NOT_CONFIGURED"],
    prerequisites: ["C0–C4 PA candidate evidence"],
  },
  10: {
    status: "REGISTERED EVIDENCE COMPLETE",
    purpose: "Inspect registered log loss, Brier, ECE, prevalence, confusion, reliability, frozen temperature scaling, and whole-game bootstrap evidence only.",
    sections: ["Log loss and Brier", "Top-label and classwise reliability", "Prevalence and confusion", "Frozen temperature", "Game-cluster bootstrap", "OOD / subgroup / prospective monitoring — NOT_CONFIGURED"],
    outputs: ["Calibration and reliability evidence", "Bootstrap intervals", "OOD and prospective monitoring — NOT_CONFIGURED"],
    prerequisites: ["Retrospective rolling-origin validation"],
  },
  11: {
    status: "RESEARCH GRAPH COMPLETE",
    purpose: "Record the governed conditional-PA evidence graph and its terminal research decision without implying simulator, deployment, or export authority.",
    sections: ["20-node research graph", "28 directed edges", "Terminal research status", "Future Gen-2 nodes — NOT_CONFIGURED"],
    outputs: ["Governed PA research component DAG", "Terminal research decision"],
    prerequisites: ["Registered retrospective calibration and reliability evidence"],
  },
};

export function mlbPaBaselineStepPresentation(step: SportsWorkflowStep) {
  return MLB_PA_BASELINE_STEP_PRESENTATIONS[step.number];
}

function completedComponent(status: string | undefined) {
  return Boolean(status) && !String(status).endsWith("_BLOCKED");
}

export function mlbPhase4StepPresentation(step: SportsWorkflowStep, study: SportsPhase4Study | undefined): MlbPaBaselineStepPresentation | undefined {
  if (!study) return undefined;
  const dynamic = study.components.dynamicState;
  const participation = [study.components.lineup, study.components.starterDuration, study.components.bullpenUsage];
  const recordedParticipation = participation.filter(Boolean);
  const completeParticipation = participation.filter((component) => completedComponent(component?.status));
  if (step.number === 4 && dynamic) {
    return {
      status: dynamic.status.endsWith("_BLOCKED") ? "BLOCKED" : dynamic.status.includes("BASELINE") ? "RESEARCH BASELINE" : "COMPLETE · DYNAMIC RESEARCH",
      purpose: "Construct strictly prior-date Bayesian batter and pitcher state, preserve missing history, and compare the bounded D1–D4 candidates with the frozen Phase 3 D0 comparator.",
      sections: ["Static, cumulative, and recency state", "Prior-date-only PA outcomes", "ESS and uncertainty", "Missing-history coverage", "Platoon — NOT_CONFIGURED"],
      outputs: ["MLB_DYNAMIC_PLAYER_STATE_V1", "Dynamic PA candidate evidence", "Dynamic-state research decision"],
      prerequisites: ["Exact identity bridge", "Frozen MLB_PA_FEATURE_VIEW_V1 and Phase 3 D0 evidence"],
    };
  }
  if (step.number === 5 && recordedParticipation.length) {
    return {
      status: recordedParticipation.length === 3 && completeParticipation.length === 3 ? "COMPLETE · RETROSPECTIVE RESEARCH" : "PARTIAL · RETROSPECTIVE RESEARCH",
      purpose: "Evaluate prior-only lineup, conditional starter-duration, and bullpen-usage components while keeping actual target-game participation and workload strictly on the target side.",
      sections: ["Prior-only lineup candidate pools", "Conditional starter duration", "Prior-only reliever candidate pools", "Measured uncovered participants", "Prospective roster feeds — NOT_CONFIGURED"],
      outputs: ["Lineup component decision", "Starter-duration component decision", "Bullpen-usage component decision"],
      prerequisites: ["Dynamic state research artifact", "Registered retrospective participation and usage targets"],
    };
  }
  if (step.number === 6 && dynamic) {
    return {
      status: dynamic.status.endsWith("_BLOCKED") ? "PHASE 3 COMPLETE · DYNAMIC BLOCKED" : "COMPLETE · PHASE 3 + DYNAMIC EVIDENCE",
      purpose: "Preserve the Phase 3 static C4 baseline and add bounded dynamic-state logistic challengers without changing its registered result.",
      sections: ["Frozen D0 raw C4", "D1–D4 multinomial logistic candidates", "No boosted event model", "No handedness or platoon features"],
      outputs: ["Static-versus-dynamic PA comparison", "Frozen 2024 and 2025 evidence"],
      prerequisites: ["MLB_DYNAMIC_PLAYER_STATE_V1"],
    };
  }
  if ([8, 9, 10].includes(step.number)) {
    return {
      status: "COMPLETE · COMPONENT SCOPE",
      purpose: step.number === 8
        ? "Compare only the registered Phase 3, dynamic-state, lineup, starter-duration, and bullpen candidates; simulator, residual, and ensemble candidates remain not configured."
        : step.number === 9
          ? "Evaluate component research with date-atomic inner-2023 tuning, 2023-to-2024 selection, and through-2024-to-2025 frozen retrospective evidence."
          : "Record only supplied component loss, Brier, calibration, duration-error, coverage, subgroup, and clustered-bootstrap evidence.",
      sections: step.number === 8
        ? ["Phase 3 C0–C4", "Dynamic D0–D4", "Lineup L0–L2", "Starter S0–S3", "Bullpen B0–B2", "Simulator / residual / ensemble — NOT_CONFIGURED"]
        : step.number === 9
          ? ["Date-atomic inner 2023", "2024 selection evidence", "Frozen 2025 retrospective evidence", "No prospective evidence"]
          : ["PA calibration", "Participation calibration", "Duration errors", "Candidate-pool coverage", "Missing-history and ESS evidence"],
      outputs: step.number === 8 ? ["Component candidate ledger"] : step.number === 9 ? ["Component temporal-fold evidence"] : ["Component reliability evidence"],
      prerequisites: ["Registered Phase 4 component evidence"],
    };
  }
  if (step.number === 11 && study.graph?.nodes.length) {
    return {
      status: "COMPLETE · RESEARCH ONLY",
      purpose: "Extend the immutable Phase 3 graph with dynamic-state and participation research nodes while withholding simulation, bundle, deployment, and monitoring authority.",
      sections: ["Parent-linked Phase 4 graph", "Component decisions", "Future feeds and simulator nodes — NOT_CONFIGURED"],
      outputs: ["Governed Phase 4 research graph", "Research component decisions"],
      prerequisites: ["Registered component metrics and limitations"],
    };
  }
  return undefined;
}

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

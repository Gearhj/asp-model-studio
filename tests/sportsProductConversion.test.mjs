import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);

const PATHS = Object.freeze({
  index: "index.html",
  brand: "src/config/brand.ts",
  brandLogo: "src/components/BrandLogo.tsx",
  shell: "src/apps/ModelingApp.tsx",
  sidebar: "src/components/Sidebar.tsx",
  config: "src/sports/sportsConfig.ts",
  home: "src/sports/StudioHome.tsx",
  library: "src/sports/WorkflowLibrary.tsx",
  workflow: "src/sports/ForecastWorkflow.tsx",
  newProject: "src/sports/NewSportsProject.tsx",
  sportsProjects: "src/sports/SportsProjects.tsx",
  projectOverview: "src/sports/SportsProjectOverview.tsx",
  modules: "src/sports/StudioModules.tsx",
  phase4Surfaces: "src/sports/Phase4Surfaces.tsx",
  evidenceApi: "src/sports/sportsEvidenceApi.ts",
  evidenceSurfaces: "src/sports/SportsEvidenceSurfaces.tsx",
  sportsPaRegistry: "server/sports_modeling/registry.py",
  sportsPhase4Registry: "server/sports_phase4/registry.py",
  sportsPhase4Migration: "server/persistence/migrations/0034_sports_phase4_research_registry.sql",
  serverPersistence: "src/lib/serverPersistence.ts",
  analytics: "src/steps/AnalyticsWorkbench.tsx",
  sqlLab: "src/steps/SqlDataStudio.tsx",
  visualization: "src/steps/ChartStudio.tsx",
  documentation: "src/steps/ModelDocumentationStudio.tsx",
});

const sourceCache = new Map();

async function source(path) {
  if (!sourceCache.has(path)) {
    sourceCache.set(path, readFile(new URL(path, ROOT), "utf8"));
  }
  try {
    return await sourceCache.get(path);
  } catch (error) {
    assert.fail(`${path} must exist as a live Phase 1 sports-product surface: ${error.message}`);
  }
}

function assertIncludesAll(text, expected, subject) {
  for (const value of expected) {
    assert.ok(text.includes(value), `${subject} must include ${JSON.stringify(value)}`);
  }
}

function assertInOrder(text, expected, subject) {
  let previous = -1;
  for (const value of expected) {
    const position = text.indexOf(value, previous + 1);
    assert.notEqual(position, -1, `${subject} is missing ${JSON.stringify(value)}`);
    assert.ok(position > previous, `${subject} has ${JSON.stringify(value)} out of order`);
    previous = position;
  }
}

function section(text, startMarker, endMarker) {
  const start = text.indexOf(startMarker);
  const end = text.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(start, -1, `Missing section marker ${JSON.stringify(startMarker)}`);
  assert.notEqual(end, -1, `Missing section marker ${JSON.stringify(endMarker)}`);
  return text.slice(start, end);
}

function assertNearby(text, first, second, subject, maximumDistance = 500) {
  const firstPositions = [];
  const secondPositions = [];
  for (let index = text.indexOf(first); index !== -1; index = text.indexOf(first, index + 1)) {
    firstPositions.push(index);
  }
  for (let index = text.indexOf(second); index !== -1; index = text.indexOf(second, index + 1)) {
    secondPositions.push(index);
  }
  const paired = firstPositions.some((left) => secondPositions.some((right) => Math.abs(left - right) <= maximumDistance));
  assert.ok(paired, `${subject} must pair ${JSON.stringify(first)} with ${JSON.stringify(second)}`);
}

test("ASP Model Studio identity is used by the document, brand, shell, and sports home", async () => {
  const [index, brand, brandLogo, shell, home] = await Promise.all([
    source(PATHS.index),
    source(PATHS.brand),
    source(PATHS.brandLogo),
    source(PATHS.shell),
    source(PATHS.home),
  ]);
  const brandedSurfaces = [index, brand, brandLogo, shell, home].join("\n");

  assert.match(brand, /productName:\s*["']ASP Model Studio["']/);
  assert.match(brand, /productSubtitle:\s*["']Sports Forecasting, Simulation & Model Intelligence["']/);
  assert.match(index, /<title>[^<]*ASP Model Studio[^<]*Sports Forecasting, Simulation (?:&amp;|&) Model Intelligence[^<]*<\/title>/);
  assertIncludesAll(
    brandedSurfaces,
    [
      "Build, simulate, validate, and deploy sophisticated sports forecasting systems.",
      "Develop player, team, event, usage, and game-simulation models through one governed analytical workflow.",
      "Build the Models Behind the Game",
      "ASP Model Studio brings player state, team dynamics, event models, simulations, validation, and deployment into one sports-science workflow.",
    ],
    "sports-native product identity",
  );

  assert.doesNotMatch(index, /ATLAS|Enterprise AI Model Development Platform|Regulated AI\/ML/i);
  assert.doesNotMatch(brand, /ATLAS|Enterprise AI Model Development Platform|Regulated AI\/ML/i);
  assert.doesNotMatch(brandLogo, /atlas-logo|atlas-icon|atlas-favicon/i);
  assert.doesNotMatch(shell, /Loading ATLAS|Restore ATLAS Guide|title=["']Restore ATLAS Guide["']/i);
});

test("MLB and NFL expose ordered twelve-step sports workflow contracts", async () => {
  const config = await source(PATHS.config);
  const workflowPage = await source(PATHS.workflow);
  const mlb = section(config, "export const MLB_WORKFLOW", "export const NFL_WORKFLOW");
  const nfl = section(config, "export const NFL_WORKFLOW", "export const SPORTS_WORKFLOWS");

  assertIncludesAll(mlb, ["MLB Forecasting", "ACTIVE WORKFLOW"], "MLB workflow");
  assertIncludesAll(nfl, ["NFL Forecasting", "WORKFLOW FOUNDATION"], "NFL workflow");
  assert.equal((mlb.match(/step\(["']mlb["']/g) ?? []).length, 12, "MLB must have exactly twelve steps");
  assert.equal((nfl.match(/step\(["']nfl["']/g) ?? []).length, 12, "NFL must have exactly twelve steps");

  assertInOrder(
    mlb,
    [
      "Project & Forecast Contract",
      "Baseball Data Evidence",
      "Identity, Coverage & Leakage",
      "Hitter & Pitcher State",
      "Lineup, Starter & Bullpen Usage",
      "Plate-Appearance Models",
      "Base-Out Game Simulation",
      "Candidate Model Laboratory",
      "Temporal Validation",
      "Calibration & Reliability",
      "Model Graph & Decision",
      "Export MLB Bundle",
    ],
    "MLB workflow",
  );
  assertInOrder(
    nfl,
    [
      "Project & Forecast Contract",
      "NFL Data Evidence",
      "Identity, Roster Coverage & Leakage",
      "Quarterback, Player & Unit State",
      "Injuries, Participation & Coaching",
      "Drive and Play Models",
      "Drive-Level Game Simulation",
      "Candidate Model Laboratory",
      "Temporal Validation",
      "Calibration & Reliability",
      "Model Graph & Decision",
      "Export NFL Bundle",
    ],
    "NFL workflow",
  );
  assertIncludesAll(workflowPage, ["purpose", "prerequisites", "outputs", "Not Configured"], "workflow step presentation");
});

test("workflow library presents only the active sports foundations and honest planned sports", async () => {
  const [config, library] = await Promise.all([source(PATHS.config), source(PATHS.library)]);
  const workflowLibrary = `${config}\n${library}`;

  assertIncludesAll(
    workflowLibrary,
    [
      "MLB Forecasting",
      "ACTIVE WORKFLOW",
      "NFL Forecasting",
      "WORKFLOW FOUNDATION",
      "NBA",
      "WNBA",
      "MMA",
      "UFC",
      "PLANNED",
    ],
    "sports workflow library",
  );
  assert.doesNotMatch(library, /Predictive Modeling|Experimental Design|Optimization|Time Series Forecasting|LLM \/ Generative AI/);
  assert.doesNotMatch(workflowLibrary, /\bsoccer\b/i, "soccer must not be advertised as a near-term workflow");
});

test("the live shell registers every primary sports route", async () => {
  const shell = await source(PATHS.shell);
  const requiredRoutes = [
    "/dashboard",
    "/projects/new",
    "/projects/open",
    "/templates",
    "/workflows/mlb",
    "/workflows/nfl",
    "/data-warehouse",
    "/model-laboratory",
    "/simulation-studio",
    "/evaluation-calibration",
    "/model-graph",
    "/registry-deployment",
    "/forward-monitoring",
    "/research-tools",
    "/analytics",
    "/sql-lab",
    "/visualization-studio",
    "/model-documentation",
    "/data-sources-rights",
    "/users-settings",
  ];
  for (const route of requiredRoutes) {
    assert.ok(shell.includes(`path="${route}"`) || shell.includes(`path='${route}'`), `ModelingApp must register ${route}`);
  }
});

test("sidebar labels navigate to the sports-native product surfaces", async () => {
  const sidebar = await source(PATHS.sidebar);
  const navigation = [
    ["/dashboard", "Studio Home"],
    ["/projects/open", "Sports Projects"],
    ["/templates", "Sports Workflows"],
    ["/data-warehouse", "Data Warehouse"],
    ["/model-laboratory", "Model Laboratory"],
    ["/simulation-studio", "Simulation Studio"],
    ["/evaluation-calibration", "Evaluation & Calibration"],
    ["/model-graph", "Model Graph"],
    ["/registry-deployment", "Registry & Deployment"],
    ["/forward-monitoring", "Forward Monitoring"],
    ["/research-tools", "Research Tools"],
    ["/analytics", "Analytics Workbench"],
    ["/sql-lab", "SQL Lab"],
    ["/visualization-studio", "Visualization Studio"],
    ["/model-documentation", "Model Documentation"],
    ["/data-sources-rights", "Data Sources & Rights"],
    ["/users-settings", "Users & Settings"],
  ];
  for (const [route, label] of navigation) {
    assertNearby(sidebar, route, label, "sports sidebar navigation");
  }
  assertIncludesAll(sidebar, ["Core", "Research Tools", "Administration"], "sports sidebar navigation groups");

  assert.doesNotMatch(sidebar, /Credit Risk Studio|Credit Bureau|Bureau Catalog|HELOC|Lending/i);
  assert.doesNotMatch(sidebar, /to=["']\/credit-risk-studio["']|to=["']\/admin\/bureau-catalogs["']/i);
});

test("sports research routes retain the working generic studio tools", async () => {
  const shell = await source(PATHS.shell);
  assertIncludesAll(
    shell,
    [
      'lazy(() => import("../steps/AnalyticsWorkbench"))',
      'lazy(() => import("../steps/SqlDataStudio"))',
      'lazy(() => import("../steps/ChartStudio"))',
      'lazy(() => import("../steps/ModelDocumentationStudio"))',
      '<AnalyticsWorkbench />',
      '<SqlDataStudio />',
      '<ChartStudio />',
      '<ModelDocumentationStudio />',
    ],
    "retained working studio tools",
  );
});

test("home, workflow, warehouse, graph, bundle, and monitoring surfaces stay honest when empty", async () => {
  const [home, workflow, modules, evidenceSurfaces, sportsProjects, projectOverview] = await Promise.all([
    source(PATHS.home),
    source(PATHS.workflow),
    source(PATHS.modules),
    source(PATHS.evidenceSurfaces),
    source(PATHS.sportsProjects),
    source(PATHS.projectOverview),
  ]);

  assertIncludesAll(
    home,
    [
      "Sports Projects",
      "Registered Datasets",
      "Active Experiments",
      "Research Challengers",
      "Model Bundles",
      "Monitoring Plans",
      "No sports projects have been created yet.",
      "No governed sports dataset is registered in this workspace.",
      "Feature authority is",
      "modeling blocked",
      "governedProject.status",
    ],
    "Studio Home",
  );
  assertIncludesAll(sportsProjects, ["No sports projects have been created yet."], "Sports Projects");
  assertIncludesAll(projectOverview, ["Not Configured", "prerequisites", "outputs"], "sports project overview");
  assertIncludesAll(
    workflow,
    [
      "No ASP dataset manifest registered.",
      "Export remains disabled.",
      "Future MLB simulation blueprint",
      "No transition engine, probabilities, or simulation results exist",
      "Not Configured",
    ],
    "sport-specific workflow",
  );
  assertIncludesAll(
    `${modules}\n${evidenceSurfaces}`,
    [
      "No Sports Dataset Registered",
      "SPORTS_DATASET_MANIFEST_V1",
      "Register approved MLB exchange",
      "No Experiment Run",
      "No Simulation Run",
      "No Evaluation Evidence",
      "No Model Graph",
      "No standalone ASP model bundle has been approved or exported.",
      "SPORTS_MODEL_BUNDLE_V1",
      "No Monitoring Plan",
      "No Research Session",
      "No Data Source Registered",
      "Administrative Activity Not Loaded",
      "Legacy workflow unavailable in ASP Model Studio",
    ],
    "shared sports studio modules",
  );
});

test("sports project creation captures dependent league, lifecycle, and forecast-target metadata", async () => {
  const [newProject, config] = await Promise.all([source(PATHS.newProject), source(PATHS.config)]);

  assertIncludesAll(
    newProject,
    [
      "Project name",
      "Sport",
      "League",
      "Season or development period",
      "Workflow template",
      "Forecast lifecycle",
      "Primary target",
      "Secondary targets",
      "Research purpose",
      "Project description",
      "MLB Current-Data Game Forecast Challenger",
      "2023–2026-08-13",
      "SPORT_REGISTRY_V1",
      "workflowManifestForLeague",
      "No workspace dataset is silently linked",
    ],
    "sports project form",
  );
  assert.match(newProject, /sport\.leagues\.map/, "league options must depend on the selected canonical sport");
  assert.match(newProject, /manifest\?\.supportedTargets/, "forecast targets must depend on the selected workflow manifest");
  assertIncludesAll(
    config,
    [
      "Baseball",
      "Football",
      "Basketball",
      "MMA",
      "MLB",
      "NFL",
      "NBA",
      "WNBA",
      "UFC",
      "Preseason",
      "Pregame — Early",
      "Pregame — Final",
      "In-game",
      "Postgame Evaluation",
      "Player Prop",
      "Market Research",
      "Joint Score Distribution",
      "Home Win Probability",
      "Run Differential",
      "Total Runs",
      "Plate-Appearance Outcome",
      "Margin",
      "Total Points",
      "Drive Outcome",
      "Player Outcome Distribution",
    ],
    "sports project metadata",
  );
  assert.doesNotMatch(`${newProject}\n${config}`, /sportsbook|wagering/i);
});

test("closeout layout and project removal remain explicit and target-local", async () => {
  const [brandLogo, shell, sportsProjects, config, serverPersistence] = await Promise.all([
    source(PATHS.brandLogo),
    source(PATHS.shell),
    source(PATHS.sportsProjects),
    source(PATHS.config),
    source(PATHS.serverPersistence),
  ]);

  assertIncludesAll(brandLogo, ["whitespace-normal", "leading-4"], "wrapping sidebar product subtitle");
  assertIncludesAll(shell, ["md:max-w-56", "xl:max-w-72", "user.displayName"], "desktop account label");
  assertIncludesAll(
    sportsProjects,
    [
      "Remove local project",
      "Confirm removal",
      "deleteProjectFromDatabase",
      "deleteSportsProjectMetadata",
      "deleteLocalProject",
      "isolated target-local database",
      "No browser record was removed.",
    ],
    "supported target-local sports-project removal",
  );
  assertIncludesAll(config, ["SPORTS_PROJECT_META_PREFIX", "localStorage.removeItem"], "sports metadata cleanup");
  assertIncludesAll(serverPersistence, ['method: "DELETE"'], "target-local database cleanup");
});

test("Phase 2 dataset evidence is fetched, registered, and rendered through governed endpoints", async () => {
  const [api, surfaces, modules] = await Promise.all([
    source(PATHS.evidenceApi),
    source(PATHS.evidenceSurfaces),
    source(PATHS.modules),
  ]);

  assertIncludesAll(
    api,
    [
      '"/sports/datasets/active"',
      "/sports/datasets/register-approved",
      'method: "POST"',
      'credentials: "include"',
      "ActiveSportsDataset",
      "SportsFeatureAudit",
      "SportsDatasetTotals",
      "SportsTemporalFold",
      "RegisteredSportsProject",
      "partitionAuthoritySha",
      "value.projectName",
      "value.workflowEvidence",
      "value.featureAudit",
      "item.displayName",
      "item.sourceName",
      "item.description",
      "JSON.stringify(item.predicate",
      "response.status === 404",
      "hasEnvelopeKey && !isRecord(payload[key])",
      "logicalExchangeUri",
      'startsWith("asp-model-exchange://")',
    ],
    "governed sports dataset client",
  );
  assert.doesNotMatch(api, /sports\/modeling\/pa-baseline/, "blocked Milestone B must not have a speculative frontend client");
  const registrationFunction = section(api, "export async function registerApprovedSportsDataset", "function useEvidence");
  assert.doesNotMatch(registrationFunction, /body\s*:/, "the browser must not submit a filesystem path or request body when registering the approved exchange");

  assertIncludesAll(
    surfaces,
    [
      "Data Warehouse",
      "Register approved MLB exchange",
      "Administrator permission is required",
      "The browser submits no filesystem path",
      "Family volume",
      "Season coverage",
      "Population composition",
      "Temporal fold timeline",
      "Evidence coverage matrix",
      "Source rights",
      "Known limitations",
      "Plate-appearance feature authority",
      "Batter Y-1 joins",
      "Pitcher Y-1 joins",
      "Fuzzy or inferred identity matching used",
      "Registered manifest evidence",
      "Target-local reference withheld",
      "logicalExchangeUri(dataset.logicalRoot)",
      "Partition authority SHA-256",
    ],
    "API-driven Data Warehouse",
  );
  assert.match(modules, /return\s+<DataWarehouseEvidencePage\s*\/>/, "the live warehouse route must render governed evidence");
  assert.doesNotMatch(surfaces, /C:\\Users|asp-model-exchange\\datasets/i, "frontend source must never expose a physical exchange path");
});

test("Phase 3 identity bridge evidence is normalized, inspectable, and clears only the obsolete bridge blocker", async () => {
  const [api, surfaces] = await Promise.all([
    source(PATHS.evidenceApi),
    source(PATHS.evidenceSurfaces),
  ]);

  assertIncludesAll(
    api,
    [
      "SportsIdentityBridge",
      "SportsIdentityBridgeTotals",
      "SportsIdentityBridgeJoinAudit",
      "SportsIdentityBridgeRights",
      "normalizeIdentityBridge",
      "normalizePublicEvidenceRows",
      "identityBridge: normalizeIdentityBridge(raw.identityBridge)",
      "registrationId",
      "contractName",
      "contractVersion",
      "manifestId",
      "manifestSha",
      "packageId",
      "parentRegistrationId",
      "parentManifestSha",
      "parentPartitionAuthoritySha",
      "aliasAuthoritySha",
      "dimensionAuthoritySha",
      "validationReportSha",
      "logicalRoot",
      "validationStatus",
      "registeredAt",
      "active",
      "packageFiles",
      "packageBytes",
      "aliasRows",
      "portablePlayers",
      "governedPlayers",
      "primaryPortablePlayers",
      "primaryGovernedPlayers",
      "namespaces",
      "joinContracts",
      "joinReferences",
      "namespaceEvidence",
      "joinAudit",
      "artifactId",
      "artifactSha",
      "logicalUri",
      "totalReferences",
      "resolvedReferences",
      "mappingRate",
      "unresolvedReferences",
      "ambiguousReferences",
      "multiplyMappedReferences",
      "joins",
      "yMinus1Coverage",
      "allowedPurposes",
      "prohibitedPurposes",
      "limitations",
      "noNamesOrFuzzyMatching",
    ],
    "normalized SPORTS_IDENTITY_BRIDGE_V1 client contract",
  );

  assertIncludesAll(
    surfaces,
    [
      "IdentityBridgeAuthority",
      "MLB identity bridge",
      "No governed MLB identity bridge is registered.",
      "SPORTS_IDENTITY_BRIDGE_V1",
      "Identity bridge totals",
      "Exact join audit",
      "Parent authority binding",
      "Namespace evidence",
      "Join contracts",
      "Y−1 prior coverage",
      "Bridge rights",
      "Bridge limitations",
      "Show immutable bridge identifiers",
      "Logical bridge root",
      "Logical join audit",
      "hasValidatedIdentityBridge",
      "BRIDGE VALIDATED",
      "clears the former package-only bridge blocker",
      "Feature materialization remains a separate governed action.",
      "Name-based or fuzzy matching used:",
      "Target-local reference withheld",
      "logicalExchangeUri(bridge.logicalRoot)",
    "logicalSportsEvidenceUri(audit.logicalUri)",
    ],
    "governed identity bridge presentation",
  );
  assert.match(surfaces, /bridge\?\.active[\s\S]*bridge\.noNamesOrFuzzyMatching[\s\S]*isValidatedStatus\(bridge\.validationStatus\)[\s\S]*isValidatedStatus\(bridge\.joinAudit\.status\)/, "the old blocker must clear only for an active, exact-match bridge with validated registration and join audit states");
  assert.doesNotMatch(surfaces, /value=\{bridge\.logicalRoot\}|value=\{audit\.logicalUri\}/, "raw bridge locations must never be rendered without logical-URI validation");
  assert.doesNotMatch(surfaces, /C:\\Users|\\\\Users|file:\/\//i, "identity bridge presentation must not embed a physical path");
});

test("Phase 3 PA baseline evidence drives research-only model, evaluation, graph, registry, project, and workflow states", async () => {
  const [api, modules, home, overview, workflow, projects, config, backendRegistry] = await Promise.all([
    source(PATHS.evidenceApi),
    source(PATHS.modules),
    source(PATHS.home),
    source(PATHS.projectOverview),
    source(PATHS.workflow),
    source(PATHS.sportsProjects),
    source(PATHS.config),
    source(PATHS.sportsPaRegistry),
  ]);

  assertIncludesAll(
    api,
    [
      "SportsPaBaseline",
      "SportsPaFeatureView",
      "SportsPaExperiment",
      "SportsPaCandidate",
      "SportsPaFold",
      "SportsPaMetrics",
      "SportsPaCalibration",
      "SportsPaBootstrapComparison",
      "SportsPaRegistry",
      "SportsPaGraph",
      "SPORTS_PA_TERMINAL_STATUSES",
      '"RESEARCH_CHALLENGER"',
      '"RESEARCH_BASELINE"',
      '"REJECTED_BASELINE"',
      '"BLOCKED"',
      "normalizePaBaseline",
      "normalizePaCandidate",
      "normalizePaMetrics",
      "normalizePaCalibration",
      "normalizePaGraph",
      "paBaseline: normalizePaBaseline(raw.paBaseline)",
      "const run = isRecord(value.run) ? value.run : value",
      "value.experiment ?? run.experiment",
      "value.classOrder ?? run.classOrder",
      "normalizePaRegistry(value.registry)",
      "decisionRecord?.rationale",
      "decisionRecord?.limitations",
      "value.displayName",
      "value.candidateType",
      "value.config",
      "value.foldMetrics",
      "value.trainingSeasons",
      "value.validationRows",
      "value.aggregateMetrics",
      "value.aggregateMetrics.selection2024",
      "value.raw2025",
      "value.scaled2025",
      "value.selected",
      "value.artifacts",
      "value.baselineCandidateId",
      "evidence.logLossDifference",
      "sanitizePublicEvidenceValue",
    ],
    "defensive PA baseline client contract",
  );

  assertIncludesAll(
    modules,
    [
      "Candidate model ledger",
      "Candidate folds",
      "Hyperparameters",
      "Convergence",
      "Feature-view lineage",
      "logicalSportsEvidenceUri(baseline.featureView.logicalRoot)",
      "2024 calibration and 2025 final comparison",
      "Frozen 2024 / 2025 candidate fold comparison",
      "C0 global",
      "C1 context",
      "candidateComparisonIds",
      "Aggregate selection metrics (2024)",
      "Final 2025 prevalence and confusion",
      "Provided final reliability bins",
      "Final 2025 classwise reliability",
      "Final 2025 probability histograms",
      "MetricEvidenceChart",
      "ClasswiseReliabilityEvidence",
      "ProbabilityHistogramEvidence",
      "No calibration observations",
      "Paired bootstrap comparisons",
      "replicate arrays are intentionally withheld",
      'aria-label="Research model graph nodes"',
      'aria-label="Research model graph edges"',
      "Registered research evidence graph",
      "NOT_CONFIGURED",
      "Research artifact registry",
      "Terminal research status",
      "Approved graphs",
      "Exported bundles",
      "Target environments",
      "EXPORT DISABLED",
      "No Experiment Run",
      "No Evaluation Evidence",
      "No Model Graph",
    ],
    "evidence-bound PA research surfaces",
  );
  const terminalVocabulary = section(modules, "Terminal research vocabulary", "Remaining Gen-2 components");
  assertIncludesAll(terminalVocabulary, ["RESEARCH_CHALLENGER", "RESEARCH_BASELINE", "REJECTED_BASELINE", "BLOCKED"], "terminal PA research vocabulary");
  assert.doesNotMatch(terminalVocabulary, /OPERATIONAL|PRODUCTION|SHADOW|RETIRED/, "terminal research vocabulary must not imply a delivery lifecycle");
  assert.match(modules, /topLabelReliability\.flatMap/, "reliability marks must be derived only from supplied bins");
  assert.match(modules, /metrics\.classwiseReliability/, "classwise reliability curves must use supplied class bins");
  assert.match(modules, /metrics\.probabilityHistograms/, "probability histograms must use supplied class bins");
  assert.doesNotMatch(modules, /replicateDifferences/, "individual bootstrap replicate arrays must not be rendered");
  assert.match(modules, /baseline \? decision \|\| "BLOCKED" : "NOT CONFIGURED"/, "empty PA surfaces must not invent a BLOCKED terminal decision");
  assert.doesNotMatch(api, /artifactId:\s*publicString\(value\.artifactId\s*\?\?\s*artifacts\[0\]/, "the client must not relabel the first registry artifact as a model artifact");
  assert.doesNotMatch(api, /modelId:\s*modelId\s*\|\|/, "the client must not fabricate a model identity when the public registry did not provide one");
  assert.doesNotMatch(api, /contractSha:\s*publicString\(value\.contractSha\s*\?\?\s*value\.contentSha\)/, "feature-view content SHA must not be mislabeled as feature-contract authority");
  assert.doesNotMatch(api, /artifactId:\s*featureViewId/, "feature-view identity must not be fabricated as an artifact identity");
  assert.doesNotMatch(api, /featureContractArtifact/, "artifact-envelope SHA must not substitute for the semantic feature-contract SHA");
  assertIncludesAll(api, ['publicString(artifact.artifactType) === "FEATURE_VIEW"', "normalizedFeatureView.logicalRoot", "normalizedFeatureView.artifactSha", "normalizedFeatureView.artifactBytes"], "exact feature-view artifact reconciliation");
  assert.doesNotMatch(`${api}\n${modules}`, /C:\\Users|\\\\Users|file:\/\//i, "PA baseline sources must not embed physical locations");

  assertIncludesAll(home, ["activeDataset?.paBaseline", "sportsPaDecisionStatus", "baseline?.experiment", "RESEARCH_CHALLENGER", "RESEARCH_BASELINE", "REJECTED_BASELINE", "Exported bundles remain 0"], "Studio Home PA status projection");
  assertIncludesAll(overview, ["boundDataset?.paBaseline", "sportsPaDecisionStatus", "Research graph", "terminal research status"], "project overview PA status projection");
  assertIncludesAll(workflow, ["boundDataset?.paBaseline", "sportsPaDecisionStatus", "Research graph", "research graph is evidence only", "Export remains disabled."], "workflow PA status projection");
  assertIncludesAll(overview, ['decision !== "BLOCKED"', 'decision === "BLOCKED" && step.number === 11', 'governedPresentation?.status || evidence?.status || baselineStatus', 'step.number === 12', '"NOT_CONFIGURED"'], "project workflow evidence precedence");
  assertIncludesAll(workflow, ['decision !== "BLOCKED"', 'decision === "BLOCKED" && step.number === 11', 'governedPresentation?.status || evidence?.status || baselineStatus', 'step.number === 12', '"NOT_CONFIGURED"', 'baseline.calibration ? "COMPLETE"'], "workflow evidence precedence");
  assertIncludesAll(config, ["mlbPaBaselineStepPresentation", 'status: "BASELINE COMPLETE"', 'status: "PA CANDIDATES COMPLETE"', 'status: "RETROSPECTIVE COMPLETE"', 'status: "REGISTERED EVIDENCE COMPLETE"', "Dynamic state — NOT_CONFIGURED", "Simulator / count / residual / ensemble candidates — NOT_CONFIGURED", "OOD / subgroup / prospective monitoring — NOT_CONFIGURED"], "honest Phase 3 workflow scope projection");
  assertIncludesAll(backendRegistry, ['f"FOLD_{season}_PREDICTIONS"', '"predictionArtifact"', '"artifacts": public_artifacts'], "fold prediction artifact projection");
  assertIncludesAll(projects, ["sportsPaDecisionStatus", "terminalStatus", "REJECTED_BASELINE", "BLOCKED"], "sports project PA status projection");
});

test("Phase 4 component evidence is normalized, scoped, graphed, and rendered without simulation or deployment claims", async () => {
  const [api, surfaces, modules, shell, sidebar, config, workflow, overview, home, registry, migration] = await Promise.all([
    source(PATHS.evidenceApi),
    source(PATHS.phase4Surfaces),
    source(PATHS.modules),
    source(PATHS.shell),
    source(PATHS.sidebar),
    source(PATHS.config),
    source(PATHS.workflow),
    source(PATHS.projectOverview),
    source(PATHS.home),
    source(PATHS.sportsPhase4Registry),
    source(PATHS.sportsPhase4Migration),
  ]);

  assertIncludesAll(api, [
    "SportsPhase4Study",
    "SportsPhase4Component",
    "SportsPhase4Artifact",
    "SportsPhase4ComponentType",
    '"DYNAMIC_PLAYER_STATE"',
    '"LINEUP_PROJECTION"',
    '"STARTER_DURATION"',
    '"BULLPEN_USAGE"',
    "normalizePhase4Artifact",
    "normalizePhase4Component",
    "normalizePhase4Study",
    "phase4: normalizePhase4Study(raw.phase4)",
    "sanitizePublicEvidenceValue",
  ], "defensive Phase 4 browser contract");
  assert.doesNotMatch(`${api}\n${surfaces}`, /C:\\Users|\\\\Users|file:\/\//i, "Phase 4 browser sources must not expose physical references");

  assertIncludesAll(shell, [
    'path="/player-team-state"',
    "<PlayerTeamStatePage />",
    'path="/participation-usage"',
    "<ParticipationUsagePage />",
  ], "Phase 4 protected routes");
  assertIncludesAll(sidebar, ["Player & Team State", "Participation & Usage"], "Phase 4 navigation");
  assertIncludesAll(modules, [
    "Phase4ModelLaboratorySection",
    "Phase4EvaluationSection",
    "Phase4GraphSection",
    "Phase4RegistrySection",
    "Phase4SimulationStatus",
  ], "Phase 4 cross-studio integration");
  assertIncludesAll(surfaces, [
    "MLB_DYNAMIC_PLAYER_STATE_V1",
    "D0 · frozen raw C4",
    "D0–D4 temporal comparison",
    "Candidate selection uses 2024 only",
    "Point-in-time batter and pitcher state",
    "Actual historical lineup and batting order are retrospective targets only.",
    "CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY",
    "never injected into the candidate pool",
    "FoldMetricChart",
    "Phase 4 parent-linked research graph",
    "Metadata and logical artifact references only",
    "Still not configured",
    "Confirmed-lineup and probable-starter feeds",
  ], "evidence-bound Phase 4 surfaces");
  assert.match(surfaces, /Game simulations[\s\S]*0|game simulator/i, "Phase 4 must not imply an executed game simulation");
  assert.doesNotMatch(surfaces, /operational|production deployment|bundle authorized/i, "Phase 4 surfaces must remain research-only");

  assertIncludesAll(config, [
    "mlbPhase4StepPresentation",
    "COMPLETE · DYNAMIC RESEARCH",
    "PARTIAL · RETROSPECTIVE RESEARCH",
    "PHASE 3 + DYNAMIC EVIDENCE",
    "COMPLETE · COMPONENT SCOPE",
    "COMPLETE · RESEARCH ONLY",
    "Platoon — NOT_CONFIGURED",
    "Simulator / residual / ensemble — NOT_CONFIGURED",
  ], "honest Phase 4 workflow scopes");
  assertIncludesAll(workflow, ["mlbPhase4StepPresentation", "governedPresentation", "Registered Phase 4 research graph", "Phase 4 component research is not a game simulator or bundle authority."], "workflow Phase 4 projection");
  assertIncludesAll(overview, ["boundDataset?.phase4", "mlbPhase4StepPresentation", "Research graph · Phase 4", "No game simulation or export bundle is implied."], "project Phase 4 projection");
  assertIncludesAll(home, ["activeDataset?.phase4", "phase4Components", "Phase 4 component research", "Simulations, bundles, and monitoring remain 0"], "home Phase 4 projection");

  assertIncludesAll(registry, [
    "MLB_PHASE4_RESEARCH_STUDY_V1",
    "SportsPhase4Registry",
    "build_phase4_study_payload",
    "build_phase4_graph",
    "semantic_study_core_sha",
    "semantic_study_sha",
    "asp-model-studio-runtime://sports-phase4/",
    "deploymentAuthorized",
    "simulationAuthorized",
    "bundleAuthorized",
    "NOT_CONFIGURED",
  ], "Phase 4 metadata registry");
  assertIncludesAll(migration, [
    "sports_phase4_studies",
    "sports_phase4_components",
    "sports_phase4_artifact_references",
    "sports_phase4_model_graph_nodes",
    "sports_phase4_model_graph_edges",
  ], "Phase 4 additive migration");
  assert.doesNotMatch(migration, /\bBLOB\b|prediction_rows|model_bytes/i, "Phase 4 SQLite schema must not store artifact bytes or prediction rows");
});

test("governed MLB project evidence survives reload without a duplicate browser-only project", async () => {
  const [home, projects, overview, workflow] = await Promise.all([
    source(PATHS.home),
    source(PATHS.sportsProjects),
    source(PATHS.projectOverview),
    source(PATHS.workflow),
  ]);

  assertIncludesAll(home, ["useActiveSportsDataset", "Governed MLB project registered", "No model experiment has been run."], "governed Studio Home state");

  assertIncludesAll(
    projects,
    [
      "useActiveSportsDataset",
      "governedProject",
      "project.projectId !== governedProject.projectId",
      "project.projectName !== governedProject.name",
      "Open governed project",
      "Governed project bound to the active immutable dataset registration",
      "loadProjectSnapshot",
    ],
    "governed sports project registry",
  );
  const governedOpen = section(projects, "function openGovernedProject", "async function removeProject");
  assertIncludesAll(
    governedOpen,
    [
      "useWorkflowStore.getState().loadProjectSnapshot",
      "hasDataset: false",
      "datasetIdentity: null",
    ],
    "atomic governed-project snapshot open",
  );
  assert.doesNotMatch(governedOpen, /useWorkflowStore\.setState/, "governed project open must not retain stale effective state through a partial store mutation");
  assertIncludesAll(
    overview,
    [
      "useActiveSportsDataset",
      "workspaceDataset?.project?.projectId === projectId",
      "const boundDataset = governedProject ? workspaceDataset : null",
      "governedStages",
      "Workflow evidence",
      "stages have registered evidence",
      "governedProject.status",
      "sports-status--amber",
      "plate-appearance-to-player-prior identity bridge",
      "workspace available, not bound",
      "No governed project evidence is inferred.",
      "No plate-appearance model, game simulation, or export is implied.",
    ],
    "governed MLB project overview",
  );
  assert.doesNotMatch(overview, /\.project\.name\s*===\s*projectName/, "project evidence must never bind by display name");
  assertIncludesAll(
    workflow,
    [
      "useActiveSportsDataset",
      "workspaceDataset?.project?.projectId === activeProjectId",
      "const boundDataset = governedProject ? workspaceDataset : null",
      "Stage status comes from governed project evidence",
      "Registered evidence",
      "Project-bound immutable dataset registration",
      "workspace available, not bound to active project",
      "governed stage evidence remains project-scoped",
      "Export remains disabled.",
    ],
    "governed MLB workflow evidence",
  );
  assert.doesNotMatch(workflow, /activeProjectName|\.project\.name\s*===|!activeProjectId/, "workflow evidence must bind only to the exact governed project ID");
});

test("live sports shell, navigation, home, templates, project creation, and research tools expose no finance positioning", async () => {
  const livePaths = [
    PATHS.shell,
    PATHS.sidebar,
    PATHS.home,
    PATHS.library,
    PATHS.newProject,
    PATHS.analytics,
    PATHS.sqlLab,
    PATHS.visualization,
    PATHS.documentation,
  ];
  const sources = await Promise.all(livePaths.map(async (path) => [path, await source(path)]));
  const forbiddenVisibleLanguage = /financial(?:-services| services| institutions?| model development)|regulated banking|credit risk|credit bureau|HELOC|loan performance|borrower outcomes?|banking policy|bureau variable|home lending|personal lending|auto lending/i;

  for (const [path, text] of sources) {
    const visibleSource = text
      .split("\n")
      .filter((line) => !line.includes(".replace(/\\b"))
      .join("\n");
    assert.doesNotMatch(visibleSource, forbiddenVisibleLanguage, `${path} must not expose finance-product positioning`);
  }
});

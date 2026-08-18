import { expect, test, type Page, type Route } from "@playwright/test";

const PA_RUN_ID = `sports-pa-research-run:sha256:${"9".repeat(64)}`;
const STUDY_ID = `sports-phase4-study:sha256:${"a".repeat(64)}`;
const CLASS_ORDER = ["STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE", "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH"];

type Evidence = Record<string, unknown>;

function calibrationBins(rowCount: number) {
  return Array.from({ length: 10 }, (_, binIndex) => ({
    binIndex,
    count: Math.floor(rowCount / 10),
    meanProbability: (binIndex + 0.45) / 10,
    observedRate: (binIndex + 0.4) / 10,
    meanConfidence: (binIndex + 0.55) / 10,
    accuracy: (binIndex + 0.5) / 10,
  }));
}

function binaryMetrics(rowCount: number, logLoss: number, brierScore: number, recall: number) {
  return {
    rowCount,
    binaryLogLoss: logLoss,
    brierScore,
    top9Recall: recall,
    top3Recall: recall - 0.1,
    top5Recall: recall,
    calibration: { expectedCalibrationError: 0.031, bins: calibrationBins(rowCount) },
    topLabelCalibration: { expectedCalibrationError: 0.028, acceptable: true, bins: calibrationBins(rowCount) },
  };
}

function dynamicMetrics(rowCount: number, logLoss: number, brierScore: number) {
  return {
    schemaVersion: "MLB_PA_METRICS_V1",
    classOrder: CLASS_ORDER,
    rowCount,
    logLoss,
    brierScore,
    topLabelEce: 0.008,
    classwiseEce: Object.fromEntries(CLASS_ORDER.map((name) => [name, 0.01])),
    topLabelReliability: calibrationBins(rowCount),
  };
}

function fold(validationSeason: number, metrics: Evidence, status = "COMPLETE") {
  return {
    foldId: validationSeason === 2024 ? "train-2023-validate-2024" : "train-through-2024-validate-2025",
    trainingSeasons: validationSeason === 2024 ? [2023] : [2023, 2024],
    validationSeason,
    trainingRows: validationSeason === 2024 ? 184_104 : 366_553,
    validationRows: validationSeason === 2024 ? 182_449 : 182_926,
    status,
    metrics: status === "COMPLETE" ? metrics : null,
  };
}

function candidate(candidateId: string, metrics2024: Evidence, metrics2025: Evidence, displayName = candidateId) {
  return {
    candidateId,
    displayName,
    config: { estimator: "bounded research model", featureCount: 12 },
    runtimeSeconds: 12.5,
    eligible: true,
    foldMetrics: [fold(2024, metrics2024), fold(2025, metrics2025)],
  };
}

function component(
  componentType: string,
  contractName: string,
  decision: string,
  candidates: Evidence[],
  selectedCandidateId: string,
  coverage: Evidence,
) {
  const selected = candidates.find((row) => row.candidateId === selectedCandidateId) as Evidence;
  const selectedFolds = selected.foldMetrics as Evidence[];
  return {
    componentId: `sports-phase4-component:${componentType.toLowerCase()}:sha256:${(componentType === "DYNAMIC_PLAYER_STATE" ? "1" : componentType === "LINEUP_PROJECTION" ? "2" : componentType === "STARTER_DURATION" ? "3" : "4").repeat(64)}`,
    componentType,
    contractName,
    contractSha: "c".repeat(64),
    descriptor: {
      snapshotCount: componentType === "DYNAMIC_PLAYER_STATE" ? 1_204_118 : undefined,
      selectedPolicyId: componentType === "DYNAMIC_PLAYER_STATE" ? `mlb-dynamic-player-state-policy:sha256:${"d".repeat(64)}` : undefined,
      selectionPolicy: "2024_ONLY",
    },
    candidates,
    selected: { candidateId: selectedCandidateId, selectionSeason: 2024 },
    folds: selectedFolds,
    metrics: { selection2024: selectedFolds[0].metrics, final2025: selectedFolds[1].metrics },
    calibration: { selection2024: (selectedFolds[0].metrics as Evidence).calibration, final2025: (selectedFolds[1].metrics as Evidence).calibration },
    bootstrap: [{ validationSeason: 2024, pointEstimate: -0.01 }, { validationSeason: 2025, pointEstimate: -0.005 }],
    coverage,
    decision: {
      decision,
      rationale: `${contractName} has valid retrospective evidence; prospective suitability is not claimed.`,
      limitations: ["No roster, injury, transaction, or announcement authority is registered."],
      researchOnly: true,
      deploymentAuthorized: false,
    },
    artifactIds: [`sports-phase4-artifact:component_card:sha256:${(componentType === "DYNAMIC_PLAYER_STATE" ? "5" : componentType === "LINEUP_PROJECTION" ? "6" : componentType === "STARTER_DURATION" ? "7" : "8").repeat(64)}`],
  };
}

const dynamicCandidates = [
  candidate("D0", dynamicMetrics(182_449, 1.4843, 0.7068), dynamicMetrics(182_926, 1.4817, 0.7064), "Frozen Phase 3 raw C4"),
  candidate("D1", dynamicMetrics(182_449, 1.4829, 0.7061), dynamicMetrics(182_926, 1.4808, 0.7059)),
  candidate("D2", dynamicMetrics(182_449, 1.4831, 0.7062), dynamicMetrics(182_926, 1.4811, 0.7060)),
  candidate("D3", dynamicMetrics(182_449, 1.4819, 0.7058), dynamicMetrics(182_926, 1.4798, 0.7054)),
  candidate("D4", dynamicMetrics(182_449, 1.4812, 0.7055), dynamicMetrics(182_926, 1.4792, 0.7050), "Recency-weighted batter and pitcher state"),
];

const lineupCandidates = [
  candidate("L0", binaryMetrics(480_000, 0.49, 0.16, 0.92), binaryMetrics(482_000, 0.48, 0.15, 0.93), "Trailing start-frequency baseline"),
  candidate("L1", binaryMetrics(480_000, 0.46, 0.14, 0.95), binaryMetrics(482_000, 0.45, 0.14, 0.95), "Regularized lineup logistic"),
];
const starterCandidates = [
  candidate("S0", { bfpMae: 4.9, bfpRmse: 6.2, outsMae: 4.1 }, { bfpMae: 4.8, bfpRmse: 6.1, outsMae: 4.0 }, "Global duration baseline"),
  candidate("S1", { bfpMae: 4.6, bfpRmse: 5.9, outsMae: 3.9 }, { bfpMae: 4.5, bfpRmse: 5.8, outsMae: 3.8 }, "Pitcher rolling baseline"),
  candidate("S2", { bfpMae: 4.3, bfpRmse: 5.5, outsMae: 3.6 }, { bfpMae: 4.2, bfpRmse: 5.4, outsMae: 3.5 }, "Regularized duration model"),
];
const bullpenCandidates = [
  candidate("B0", binaryMetrics(170_000, 0.56, 0.19, 0.81), binaryMetrics(172_000, 0.55, 0.18, 0.82), "Recency/workload baseline"),
  candidate("B1", binaryMetrics(170_000, 0.52, 0.17, 0.86), binaryMetrics(172_000, 0.51, 0.17, 0.86), "Regularized appearance logistic"),
];

const components = {
  dynamicState: component(
    "DYNAMIC_PLAYER_STATE",
    "MLB_DYNAMIC_PLAYER_STATE_V1",
    "DYNAMIC_STATE_RESEARCH_CHALLENGER",
    dynamicCandidates,
    "D4",
    {
      selectedCandidateId: "D4",
      snapshotRows: 1_204_118,
      missingHistoryRows: 4_112,
      subgroups: [2024, 2025].flatMap((validationSeason) => [
        { validationSeason, subgroup: "MISSING_HISTORY", rowCount: 1_800, finalMetrics: { logLoss: 1.58 } },
        { validationSeason, subgroup: "HAS_HISTORY_ESS_LT_100", rowCount: 21_000, finalMetrics: { logLoss: 1.51 } },
        { validationSeason, subgroup: "HAS_HISTORY_ESS_100_TO_299", rowCount: 60_000, finalMetrics: { logLoss: 1.48 } },
        { validationSeason, subgroup: "HAS_HISTORY_ESS_GE_300", rowCount: 99_649, finalMetrics: { logLoss: 1.45 } },
      ]),
    },
  ),
  lineup: component("LINEUP_PROJECTION", "MLB_LINEUP_PROJECTION_V1", "LINEUP_RESEARCH_COMPONENT", lineupCandidates, "L1", { poolCoverage2024: 0.956, poolCoverage2025: 0.958, targetTeamGames: 9_718 }),
  starterDuration: component("STARTER_DURATION", "MLB_STARTER_DURATION_V1", "STARTER_DURATION_RESEARCH_COMPONENT", starterCandidates, "S2", { targetRows: 14_578, conditioning: "CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY" }),
  bullpenUsage: component("BULLPEN_USAGE", "MLB_BULLPEN_USAGE_V1", "BULLPEN_USAGE_RESEARCH_COMPONENT", bullpenCandidates, "B1", { poolCoverage2024: 0.952, poolCoverage2025: 0.954, zeroRelieverTeamGames: 92 }),
};

const artifacts = Object.values(components).map((value, index) => ({
  artifactId: value.artifactIds[0],
  artifactType: "COMPONENT_CARD",
  logicalUri: `asp-model-studio-runtime://sports-phase4/objects/sha256/${index}${index}/${["5", "6", "7", "8"][index].repeat(64)}/component-card.json`,
  sha256: ["5", "6", "7", "8"][index].repeat(64),
  byteCount: 4096 + index,
  mediaType: "application/json",
}));

const activeDatasetResponse = {
  ok: true,
  dataset: {
    registrationId: "sports-dataset-1b58d5d1def2c9b7",
    datasetId: "mlb-fd1",
    datasetVersionId: "v1",
    manifestId: "manifest",
    manifestSha: "1".repeat(64),
    packageId: "mlb-fd1",
    sport: "baseball",
    league: "MLB",
    evidenceCutoff: "2025-12-31",
    publishedAt: "2026-08-01T00:00:00Z",
    logicalRoot: "asp-model-exchange://mlb-fd1",
    validationStatus: "VALID",
    registeredAt: "2026-08-17T12:00:00Z",
    rightsStatus: "APPROVED_RESEARCH",
    limitationCount: 1,
    active: true,
    seasons: [2021, 2022, 2023, 2024, 2025],
    totals: {},
    families: [],
    seasonCoverage: [],
    populations: [],
    folds: [],
    evidenceCoverage: [],
    rights: [],
    limitations: [],
    phase4: {
      schemaVersion: "MLB_PHASE4_RESEARCH_STUDY_V1",
      studyId: STUDY_ID,
      studySha: "b".repeat(64),
      studyIdentity: { createdAt: "2026-08-17T16:00:00Z", codeRevision: "git:8a47e70+worktree:fixture" },
      projectId: "sports-project-mlb-fd1-1b58d5d1def2",
      dataset: { registrationId: "sports-dataset-1b58d5d1def2c9b7" },
      identityBridge: { registrationId: "sports-identity-bridge-6b69e7dcf4c5db76" },
      phase3Baseline: { runId: PA_RUN_ID, status: "RESEARCH_BASELINE" },
      components,
      artifacts,
      graph: {
        graphId: `sports-phase4-model-graph:sha256:${"e".repeat(64)}`,
        parentGraphId: `mlb-pa-model-graph:sha256:${"f".repeat(64)}`,
        nodes: [
          { nodeId: "phase3-baseline", label: "Frozen Phase 3 raw C4 baseline", status: "COMPLETE" },
          { nodeId: "dynamic-pa-research", label: "Dynamic plate-appearance research", status: "COMPLETE" },
          { nodeId: "lineup-projection", label: "Lineup projection research", status: "COMPLETE" },
          { nodeId: "starter-duration", label: "Starter duration research", status: "COMPLETE" },
          { nodeId: "bullpen-usage", label: "Bullpen usage research", status: "COMPLETE" },
          { nodeId: "game-simulator", label: "Game simulator", status: "NOT_CONFIGURED" },
          { nodeId: "export-bundle", label: "ASP export bundle", status: "NOT_CONFIGURED" },
        ],
        edges: [{ edgeId: "edge-1", sourceNodeId: "phase3-baseline", targetNodeId: "dynamic-pa-research", relation: "FROZEN_COMPARATOR_FOR" }],
      },
      decision: {
        researchOnly: true,
        deploymentAuthorized: false,
        simulationAuthorized: false,
        bundleAuthorized: false,
        limitations: ["Diagnostic at C:\\Users\\private\\phase4.json"],
      },
      registry: { registeredAt: "2026-08-17T16:05:00Z", lastValidatedAt: "2026-08-17T16:05:00Z", active: true },
    },
  },
};

async function fulfillJson(route: Route, status: number, body: Record<string, unknown>) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installMocks(page: Page) {
  const calls = { auth: 0, activeDataset: 0, unexpected: [] as string[] };
  await page.addInitScript(() => { localStorage.clear(); sessionStorage.clear(); });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/auth/me" && request.method() === "GET") {
      calls.auth += 1;
      await fulfillJson(route, 200, { ok: true, user: { userId: "phase4-user", displayName: "Phase 4 Researcher", email: "phase4@local", role: "user", status: "active" } });
      return;
    }
    if (pathname === "/api/sports/datasets/active" && request.method() === "GET") {
      calls.activeDataset += 1;
      await fulfillJson(route, 200, activeDatasetResponse);
      return;
    }
    calls.unexpected.push(`${request.method()} ${pathname}`);
    await fulfillJson(route, 404, { ok: false, detail: "Unexpected Phase 4 browser-harness request." });
  });
  return calls;
}

async function expectResponsive(page: Page, width: number, height: number) {
  const dimensions = await page.evaluate(() => ({
    width: window.innerWidth,
    height: window.innerHeight,
    documentWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions).toMatchObject({ width, height });
  expect(dimensions.documentWidth).toBeLessThanOrEqual(width + 1);
  await expect(page.locator("#root")).not.toBeEmpty();
}

test.use({ screenshot: "off", trace: "off", video: "off" });

test("Phase 4 components remain lineage-bound, research-only, charted, and responsive", async ({ page }) => {
  const calls = await installMocks(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/player-team-state?phase4-browser=dynamic");
  await expect(page.getByRole("heading", { name: "Player & Team State" })).toBeVisible();
  await expect(page.locator("body")).toContainText("DYNAMIC_STATE_RESEARCH_CHALLENGER");
  await expect(page.locator("body")).toContainText("D0–D4 temporal comparison");
  await expect(page.locator("body")).toContainText("Recency-weighted batter and pitcher state");
  await expect(page.getByRole("figure", { name: "Dynamic-state log loss by effective-sample-size group" })).toBeVisible();
  await expectResponsive(page, 1440, 900);

  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/participation-usage?phase4-browser=participation");
  await expect(page.getByRole("heading", { name: "Participation & Usage" })).toBeVisible();
  await expect(page.locator("body")).toContainText("LINEUP_RESEARCH_COMPONENT");
  await expect(page.locator("body")).toContainText("STARTER_DURATION_RESEARCH_COMPONENT");
  await expect(page.locator("body")).toContainText("BULLPEN_USAGE_RESEARCH_COMPONENT");
  await expect(page.locator("body")).toContainText("CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY");
  await expect(page.locator("body")).toContainText("Simulator status");
  await expect(page.locator("body")).toContainText("NOT CONFIGURED");
  await expectResponsive(page, 1024, 768);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/evaluation-calibration?phase4-browser=evaluation");
  await expect(page.getByRole("heading", { name: "Evaluation & Calibration" })).toBeVisible();
  await expect(page.getByRole("figure", { name: /MLB_DYNAMIC_PLAYER_STATE_V1 logLoss by candidate and fold/ })).toBeVisible();
  await expect(page.getByRole("figure", { name: /MLB_BULLPEN_USAGE_V1 selected-candidate calibration/ })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("C:\\Users\\private");
  await expectResponsive(page, 390, 844);

  await page.goto("/model-graph?phase4-browser=graph");
  await expect(page.locator("body")).toContainText("Phase 4 parent-linked research graph");
  await expect(page.locator("body")).toContainText("Game simulator");
  await expect(page.locator("body")).toContainText("NOT_CONFIGURED");

  await page.goto("/registry-deployment?phase4-browser=registry");
  await expect(page.locator("body")).toContainText(STUDY_ID);
  await expect(page.locator("body")).toContainText("Metadata and logical artifact references only");
  const phase4Registry = page.getByRole("heading", { name: "Phase 4 research registry" }).locator("xpath=ancestor::section");
  await expect(phase4Registry).not.toContainText("OPERATIONAL");
  await expect(phase4Registry).not.toContainText("PRODUCTION");
  await expect(page.getByText("EXPORT DISABLED", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Export unavailable" })).toBeDisabled();

  expect(calls.auth).toBeGreaterThanOrEqual(5);
  expect(calls.activeDataset).toBeGreaterThanOrEqual(5);
  expect(calls.unexpected).toEqual([]);
  expect(pageErrors).toEqual([]);
});

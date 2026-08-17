import { expect, test, type Page, type Route } from "@playwright/test";

const RUN_ID = "sports-pa-research-run:sha256:9ee241378320fb820aab2531a6525d2d4624d42e7ff6c406e147f28c6800fd07";
const RUN_SHA = "dc62d2bd07df9ddd26494512c748a5859cf9667cdc901f002f6d2a86b619658e";
const PREDICTIONS_2024 = "sports-pa-artifact:fold_2024_predictions:sha256:85215c590d04dd9d97f6037b69522d0602214b4a244b7160289ba6db0c6ac8cd";
const PREDICTIONS_2025 = "sports-pa-artifact:fold_2025_predictions:sha256:0263d4fc031fe4851160ac3ee0cd86dcacdf2152a861ea3ade6fdab0f04d6be1";
const FIRST_ARTIFACT_CANARY = `sports-pa-artifact:bootstrap_evidence:sha256:${"a".repeat(64)}`;
const CLASS_ORDER = ["STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE", "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH"];
const FEATURE_NAMES = [
  "context_inning", "context_top_bottom", "context_outs_before", "context_base_mask_before", "context_batting_score_diff_before",
  "batter_log1p_pa", "batter_avg", "batter_obp", "batter_slg", "batter_so_per_pa", "batter_bb_hbp_per_pa", "batter_hr_per_pa", "batter_prior_missing",
  "pitcher_log1p_bfp", "pitcher_era9", "pitcher_whip", "pitcher_so_per_bfp", "pitcher_bb_per_bfp", "pitcher_hr_per_bfp", "pitcher_hbp_per_bfp", "pitcher_gs_per_g", "pitcher_prior_missing",
];

type Evidence = Record<string, unknown>;

function metricEvidence(
  rowCount: number,
  logLoss: number,
  brierScore: number,
  topLabelEce: number,
) {
  const prevalence = Object.fromEntries(CLASS_ORDER.map((label, index) => [label, index === 0 ? 0.453 : 0.547 / 7]));
  const binCount = 10;
  const countForBin = (binIndex: number) => binIndex === binCount - 1
    ? rowCount - Math.floor(rowCount / binCount) * (binCount - 1)
    : Math.floor(rowCount / binCount);
  const classwiseReliability = Object.fromEntries(CLASS_ORDER.map((label) => [label, Array.from({ length: binCount }, (_, binIndex) => {
    const meanProbability = (binIndex + 0.5) / binCount;
    const realizedFrequency = Math.max(0, meanProbability - topLabelEce);
    return {
      binIndex,
      lowerBound: binIndex / binCount,
      upperBound: (binIndex + 1) / binCount,
      upperBoundInclusive: binIndex === binCount - 1,
      count: countForBin(binIndex),
      meanProbability,
      realizedFrequency,
      gap: realizedFrequency - meanProbability,
      absoluteGap: Math.abs(realizedFrequency - meanProbability),
    };
  })]));
  const probabilityHistograms = Object.fromEntries(CLASS_ORDER.map((label) => [label, Array.from({ length: binCount }, (_, binIndex) => ({
    binIndex,
    lowerBound: binIndex / binCount,
    upperBound: (binIndex + 1) / binCount,
    upperBoundInclusive: binIndex === binCount - 1,
    count: countForBin(binIndex),
    populationShare: countForBin(binIndex) / rowCount,
  }))]));
  const topLabelReliability = Array.from({ length: binCount }, (_, binIndex) => {
    const meanConfidence = (binIndex + 0.5) / binCount;
    const accuracy = Math.max(0, meanConfidence - topLabelEce);
    return {
      binIndex,
      lowerBound: binIndex / binCount,
      upperBound: (binIndex + 1) / binCount,
      upperBoundInclusive: binIndex === binCount - 1,
      count: countForBin(binIndex),
      meanConfidence,
      accuracy,
      gap: accuracy - meanConfidence,
      absoluteGap: Math.abs(accuracy - meanConfidence),
    };
  });
  return {
    schemaVersion: "MLB_PA_METRICS_V1",
    classOrder: CLASS_ORDER,
    rowCount,
    binCount,
    binningRule: "FIXED_EQUAL_WIDTH_LEFT_CLOSED_FINAL_RIGHT_CLOSED",
    logLoss,
    brierScore,
    brierDefinition: "MEAN_SUMMED_ONE_VS_ALL_SQUARED_ERROR",
    classwiseBrier: Object.fromEntries(CLASS_ORDER.map((label) => [label, brierScore / CLASS_ORDER.length])),
    topLabelEce,
    top1Accuracy: 0.451986,
    balancedAccuracy: 0.126589,
    macroF1: 0.117421,
    weightedF1: 0.410202,
    perClass: Object.fromEntries(CLASS_ORDER.map((label) => [label, { precision: 0.2, recall: 0.2, f1: 0.2, support: 1_000 }])),
    confusionMatrix: CLASS_ORDER.map((_, row) => CLASS_ORDER.map((__, column) => row === column ? 1_000 + row : 25 + column)),
    confusionMatrixAxes: { rows: "realized", columns: "predicted" },
    realizedPrevalence: prevalence,
    predictedPrevalence: prevalence,
    argmaxPrevalence: prevalence,
    topLabelReliability,
    classwiseReliability,
    probabilityHistograms,
  };
}

const predictionArtifacts: Record<number, Evidence> = {
  2024: {
    artifactId: PREDICTIONS_2024,
    artifactType: "FOLD_2024_PREDICTIONS",
    logicalUri: "asp-model-studio-runtime://sports-modeling/runs/fold-2024-predictions.parquet",
    sha256: "85215c590d04dd9d97f6037b69522d0602214b4a244b7160289ba6db0c6ac8cd",
    byteCount: 10_240,
    mediaType: "application/vnd.apache.parquet",
  },
  2025: {
    artifactId: PREDICTIONS_2025,
    artifactType: "FOLD_2025_PREDICTIONS",
    logicalUri: "asp-model-studio-runtime://sports-modeling/runs/fold-2025-predictions.parquet",
    sha256: "0263d4fc031fe4851160ac3ee0cd86dcacdf2152a861ea3ade6fdab0f04d6be1",
    byteCount: 10_480,
    mediaType: "application/vnd.apache.parquet",
  },
};

const candidateDefinitions = [
  ["C0", "Global eight-class frequency", 1.5002493728, 0.7126234442, 0.0090001222, 1.4993422793, 0.7124396981, 0.00582220075],
  ["C1", "Conditional PA-state context", 1.495832891, 0.7116255822, 0.009037767, 1.4945479337, 0.7114441284, 0.0059171306],
  ["C2", "PA-state context plus batter prior", 1.4865434132, 0.7077458307, 0.0105649073, null, null, null],
  ["C3", "PA-state context plus pitcher prior", 1.4934717413, 0.7106391089, 0.0110113809, null, null, null],
  ["C4", "Combined PA-state and batter/pitcher priors", 1.484254849, 0.706785908, 0.0117306649, 1.4816765958, 0.7063844063, 0.0037567915],
] as const;

const candidates = candidateDefinitions.map((definition, ordinal) => {
  const [candidateId, displayName, ll2024, brier2024, ece2024, ll2025, brier2025, ece2025] = definition;
  const secondFoldComplete = ll2025 !== null && brier2025 !== null && ece2025 !== null;
  return {
    candidateId,
    candidateType: candidateId === "C0" ? "GLOBAL_CLASS_FREQUENCY" : "MULTINOMIAL_LOGISTIC_L2",
    displayName,
    ordinal,
    config: candidateId === "C0" ? { estimator: "empirical_class_frequency" } : { regularization: "l2", C: candidateId === "C3" ? 0.2 : 1 },
    runtimeSeconds: [1.095861, 173.264391, 172.838523, 106.557615, 400.187006][ordinal],
    convergence: candidateId === "C0" ? { status: "NOT_APPLICABLE" } : { status: "CONVERGED", converged: true },
    foldMetrics: [
      {
        foldId: "train-2023-validate-2024",
        status: "COMPLETE",
        trainingSeasons: [2023],
        validationSeason: 2024,
        trainingRows: 184_104,
        validationRows: 182_449,
        metrics: metricEvidence(182_449, ll2024, brier2024, ece2024),
        predictionArtifact: predictionArtifacts[2024],
      },
      {
        foldId: "train-through-2024-validate-2025",
        status: secondFoldComplete ? "COMPLETE" : "NOT_RUN_BY_POLICY",
        trainingSeasons: [2023, 2024],
        validationSeason: 2025,
        trainingRows: 366_553,
        validationRows: 182_926,
        metrics: secondFoldComplete
          ? metricEvidence(182_926, ll2025 as number, brier2025 as number, ece2025 as number)
          : null,
        predictionArtifact: secondFoldComplete ? predictionArtifacts[2025] : null,
      },
    ],
    aggregateMetrics: {
      selection2024: metricEvidence(182_449, ll2024, brier2024, ece2024),
    },
    eligible: true,
    selected: candidateId === "C4",
    rejectionReasons: [],
  };
});

const registryArtifacts = [
  {
    artifactId: FIRST_ARTIFACT_CANARY,
    artifactType: "BOOTSTRAP_EVIDENCE",
    logicalUri: "asp-model-studio-runtime://sports-modeling/runs/bootstrap-comparisons.json",
    sha256: "a".repeat(64),
    byteCount: 4_096,
    mediaType: "application/json",
  },
  predictionArtifacts[2024],
  predictionArtifacts[2025],
  {
    artifactId: "sports-pa-artifact:model_state:sha256:8aaf8af4e5b66231c557499a8cfef3f8303a905d0e53570b88c1b3efc569a12e",
    artifactType: "MODEL_STATE",
    logicalUri: "asp-model-studio-runtime://sports-modeling/runs/model-2024.json",
    sha256: "8aaf8af4e5b66231c557499a8cfef3f8303a905d0e53570b88c1b3efc569a12e",
    byteCount: 81_920,
    mediaType: "application/json",
  },
  {
    artifactId: "sports-pa-artifact:model_state:sha256:77f241f1da33ff716ff460ef1042d30a3195841a314cd6232b40d318dc18ad5e",
    artifactType: "MODEL_STATE",
    logicalUri: "asp-model-studio-runtime://sports-modeling/runs/model-2025.json",
    sha256: "77f241f1da33ff716ff460ef1042d30a3195841a314cd6232b40d318dc18ad5e",
    byteCount: 92_160,
    mediaType: "application/json",
  },
  {
    artifactId: "sports-pa-artifact:feature_view:sha256:42884747dfb610564bf0c85ab30f6c16d09b2a01982ddbc4e9ccb485f2ddb53f",
    artifactType: "FEATURE_VIEW",
    logicalUri: "asp-model-studio-runtime://sports-modeling/feature-views/mlb-pa-v1.parquet",
    sha256: "42884747dfb610564bf0c85ab30f6c16d09b2a01982ddbc4e9ccb485f2ddb53f",
    byteCount: 11_574_290,
    mediaType: "application/vnd.apache.parquet",
  },
  ...[
    ...Array(6).fill("MODEL_STATE"),
    ...Array(6).fill("PREPROCESSOR_STATE"),
    "FEATURE_VIEW_RUN_BINDING", "FEATURE_CONTRACT", "FEATURE_SCHEMA", "CLASS_ORDER",
    "EXPERIMENT_METRICS", "CONFUSION_MATRICES", "CALIBRATION_EVIDENCE", "LINEAGE", "MODEL_CARD", "FINAL_CHECKPOINT",
  ].map((artifactType, index) => {
    const sha256 = String(index + 1).padStart(64, "0");
    return {
      artifactId: `sports-pa-artifact:${artifactType.toLowerCase()}:sha256:${sha256}`,
      artifactType,
      logicalUri: `asp-model-studio-runtime://sports-modeling/runs/evidence-${String(index + 1).padStart(2, "0")}.json`,
      sha256,
      byteCount: 1_000 + index,
      mediaType: "application/json",
    };
  }),
];

const final2025 = metricEvidence(182_926, 1.4818116443, 0.7064658937, 0.0084925382);

const activeDatasetResponse = {
  ok: true,
  dataset: {
    registrationId: "sports-dataset-1b58d5d1def2c9b7",
    datasetId: "asp.mlb.open-data.fd1",
    datasetVersionId: "asp.mlb.open-data.fd1:sha256:1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49",
    manifestId: "sports-dataset-manifest:sha256:1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49",
    manifestSha: "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49",
    partitionAuthoritySha: "8dec143b06622af068665b9fd1ad419a0353e76f0e0083b4c3459b8fce3cb437",
    packageId: "sha256-1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49",
    sport: "Baseball",
    league: "MLB",
    evidenceCutoff: "2026-08-15",
    publishedAt: "2026-08-15T00:00:00Z",
    logicalRoot: "asp-model-exchange://datasets/mlb-fd1/manifest-sha256-1b58d5d1def2c9b7",
    validationStatus: "VALID",
    registeredAt: "2026-08-17T15:06:23.850176Z",
    rightsStatus: "PASS",
    limitationCount: 4,
    active: true,
    seasons: [2023, 2024, 2025],
    totals: {
      packageFiles: 329,
      parquetFiles: 329,
      rows: 549_479,
      parquetBytes: 339_818_557,
      games: 7_287,
      plateAppearances: 549_479,
      transitions: 0,
      starterTargets: 0,
      bullpenAppearances: 0,
      playerPriors: 0,
      partitions: 329,
      playerIdentityCoverage: 1,
    },
    families: [{ family: "plate_appearances", rows: 549_479 }],
    seasonCoverage: [
      { season: 2023, games: 2_430, plateAppearances: 184_104, transitions: 0, starterTargets: 0, bullpenAppearances: 0 },
      { season: 2024, games: 2_430, plateAppearances: 182_449, transitions: 0, starterTargets: 0, bullpenAppearances: 0 },
      { season: 2025, games: 2_427, plateAppearances: 182_926, transitions: 0, starterTargets: 0, bullpenAppearances: 0 },
    ],
    populations: [],
    folds: [
      { foldId: "train-2023-validate-2024", trainingSeasons: [2023], validationSeason: 2024, trainingRows: 184_104, validationRows: 182_449 },
      { foldId: "train-through-2024-validate-2025", trainingSeasons: [2023, 2024], validationSeason: 2025, trainingRows: 366_553, validationRows: 182_926 },
    ],
    evidenceCoverage: { plateAppearances: { status: "COMPLETE", rows: 549_479 } },
    rights: [],
    limitations: ["Research-only conditional PA component; internal note at /home/operator/run.json."],
    project: {
      projectId: "sports-project-mlb-fd1-1b58d5d1def2",
      projectName: "MLB Gen-2 Free-Data Baseline",
      status: "REGISTERED_PA_RESEARCH_BASELINE",
      workflowId: "mlb-forecasting",
      sport: "Baseball",
      league: "MLB",
      workflowEvidence: {
        candidate_models_experiments: { status: "COMPLETE", evidence: RUN_ID },
        temporal_validation: { status: "COMPLETE", evidence: "Frozen 2024 and 2025 folds" },
        calibration_reliability: { status: "COMPLETE", evidence: "2024-only temperature fit; frozen 2025 evaluation" },
        model_graph_decision: { status: "COMPLETE", evidence: "Research graph only" },
        export_to_asp: { status: "NOT_CONFIGURED", evidence: "No bundle exported" },
      },
    },
    paBaseline: {
      run: {
        schemaVersion: "MLB_PA_RESEARCH_RUN_V1",
        runId: RUN_ID,
        runSha: RUN_SHA,
        projectId: "sports-project-mlb-fd1-1b58d5d1def2",
        terminalStatus: "RESEARCH_BASELINE",
        classOrder: CLASS_ORDER,
        experiment: {
          experimentId: "mlb-pa-experiment:sha256:a7aaf28c180cded23179735ea00ddb45582e58148a49b447f0754c3cb2c9cf7e",
          objective: "Eight-class conditional terminal plate-appearance outcome research",
          seed: 20260817,
          trainingContractVersion: "MLB_PA_FEATURE_VIEW_V1",
        },
      },
      featureView: {
        featureViewId: "mlb-pa-feature-view:sha256:74b9c24bb57dd75061a5de0f967c4a57e492eab9e016be950a036292bf8f958b",
        contractName: "MLB_PA_FEATURE_VIEW",
        contractVersion: "MLB_PA_FEATURE_VIEW_V1",
        contractSha: "fc3227fe1488f0cf422dc40c634a9b0b1c432828d479a68ea6ba7a0dce038d1e",
        contentSha: "74b9c24bb57dd75061a5de0f967c4a57e492eab9e016be950a036292bf8f958b",
        rowCount: 549_479,
        featureCount: 22,
        featureNames: FEATURE_NAMES,
        seasons: [2023, 2024, 2025],
        logicalUri: "asp-model-studio-runtime://sports-modeling/feature-views/mlb-pa-v1.parquet",
        artifactSha: "42884747dfb610564bf0c85ab30f6c16d09b2a01982ddbc4e9ccb485f2ddb53f",
        artifactBytes: 11_574_290,
      },
      candidates,
      selected: {
        candidateId: "C4",
        selectionMetric: "2024_LOG_LOSS_THEN_BRIER_THEN_ORDINAL",
        rationale: "C4 was selected using the frozen 2024 fold only.",
      },
      calibration: {
        schemaVersion: "MLB_PA_CALIBRATION_V1",
        decision: "RETAINED",
        method: "SCALAR_TEMPERATURE_ON_LOG_PROBABILITIES",
        sourceSeason: 2024,
        candidateId: "C4",
        fittedTemperature: 0.976518973285,
        retainedTemperature: 0.976518973285,
        retained: true,
        rationale: "The temperature was fit on 2024 only; internal note at \\\\server\\share\\run.json.",
        raw2024: metricEvidence(182_449, 1.484254849, 0.706785908, 0.0117306649),
        scaled2024: metricEvidence(182_449, 1.4840562071, 0.7066613133, 0.0047150032),
        raw2025: metricEvidence(182_926, 1.4816765958, 0.7063844063, 0.0037567915),
        scaled2025: final2025,
        final2025,
      },
      bootstrapComparisons: [
        {
          baselineCandidateId: "C0",
          comparatorName: "C0 global frequency",
          foldId: "train-through-2024-validate-2025",
          validationSeason: 2025,
          resamples: 500,
          seed: 20260817,
          evidence: {
            resampleCount: 500,
            logLossDifference: { pointEstimate: -0.01766568, bootstrapMean: -0.01766, percentileInterval: { lower: -0.01863901, upper: -0.01669094 }, probabilitySelectedBetter: 1 },
            brierScoreDifference: { pointEstimate: -0.00605529, bootstrapMean: -0.00605, percentileInterval: { lower: -0.00643152, upper: -0.0056653 }, probabilitySelectedBetter: 1 },
          },
        },
      ],
      decision: {
        terminalStatus: "RESEARCH_BASELINE",
        rationale: "Research evidence is recorded; internal note at C:\\Users\\james\\private\\run.json.",
        researchOnly: true,
        deploymentAuthorized: false,
        limitations: ["No prospective evidence has been collected.", "No game simulation or export is configured."],
      },
      // Deliberately matches the real public registry shape: there is no modelId or
      // singular artifactId. The browser must not invent either from the run or the
      // first artifact in this array.
      registry: {
        runCreatedAt: "2026-08-17T15:06:23.850176Z",
        registeredAt: "2026-08-17T15:20:00.000000Z",
        lastValidatedAt: "2026-08-17T15:20:00.000000Z",
        active: true,
        artifacts: registryArtifacts,
      },
      graph: {
        graphId: "mlb-pa-model-graph:sha256:c42cec805870c4eae5f935aa406714e5cecd0f46ff0dfd2ca78d57e2397de18b",
        nodes: [{ nodeId: "feature-view", nodeType: "FEATURE_VIEW", label: "MLB PA feature view", status: "COMPLETE" }],
        edges: [],
      },
    },
  },
};

async function fulfillJson(route: Route, status: number, body: Record<string, unknown>) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installPhaseThreeMocks(page: Page) {
  const calls = { auth: 0, activeDataset: 0, unexpected: [] as string[] };
  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/auth/me" && request.method() === "GET") {
      calls.auth += 1;
      await fulfillJson(route, 200, {
        ok: true,
        user: {
          userId: "phase-three-browser-user",
          displayName: "Phase Three Researcher",
          email: "phase-three@asp-model-studio.local",
          role: "user",
          status: "active",
        },
      });
      return;
    }
    if (pathname === "/api/sports/datasets/active" && request.method() === "GET") {
      calls.activeDataset += 1;
      await fulfillJson(route, 200, activeDatasetResponse);
      return;
    }
    calls.unexpected.push(`${request.method()} ${pathname}`);
    await fulfillJson(route, 404, { ok: false, detail: "No other API is available in the Phase 3 browser harness." });
  });
  return calls;
}

async function expectResponsiveShell(page: Page, width: number, height: number) {
  const dimensions = await page.evaluate(() => ({
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    documentWidth: document.documentElement.scrollWidth,
    rootWidth: document.getElementById("root")?.getBoundingClientRect().width ?? 0,
  }));
  expect(dimensions.innerWidth).toBe(width);
  expect(dimensions.innerHeight).toBe(height);
  expect(dimensions.documentWidth, `document overflowed at ${width}x${height}`).toBeLessThanOrEqual(width + 1);
  expect(dimensions.rootWidth).toBeLessThanOrEqual(width + 1);
  await expect(page.locator("#root")).not.toBeEmpty();

  const mobileMenu = page.getByRole("button", { name: "Open navigation" });
  if (width < 1024) {
    await expect(mobileMenu).toBeVisible();
    const aside = await page.locator("aside").boundingBox();
    expect(aside, "mobile navigation aside should be rendered off-canvas").not.toBeNull();
    expect((aside?.x ?? 0) + (aside?.width ?? 0)).toBeLessThanOrEqual(1);
  } else {
    await expect(mobileMenu).toBeHidden();
    await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  }
}

test.use({ screenshot: "off", trace: "off", video: "off" });

test("Phase 3 PA evidence stays research-only, lineage-true, and responsive", async ({ page }) => {
  const calls = await installPhaseThreeMocks(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/model-laboratory?phase3-browser=baseline");
  await expect(page.getByRole("heading", { name: "Model Laboratory" })).toBeVisible();
  await expect(page.locator("body")).toContainText("RESEARCH_BASELINE");
  await expect(page.locator("body")).toContainText("1 selected by evidence");
  const selectedLedger = page
    .getByRole("table", { name: "Combined PA-state and batter/pitcher priors temporal folds" })
    .locator("xpath=ancestor::article");
  await expect(selectedLedger).toContainText("SELECTED");
  await expect(selectedLedger).toContainText(PREDICTIONS_2024);
  await expect(selectedLedger).toContainText(PREDICTIONS_2025);
  await expect(selectedLedger).not.toContainText("Not recorded");
  await expectResponsiveShell(page, 1440, 900);

  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/registry-deployment?phase3-browser=registry");
  await expect(page.getByRole("heading", { name: "Registry & Deployment" })).toBeVisible();
  const registryTable = page.getByRole("table", { name: "PA research model registry" });
  await expect(registryTable).toContainText("Research run");
  await expect(registryTable).toContainText(RUN_ID);
  await expect(registryTable).toContainText("Combined PA-state and batter/pitcher priors");
  await expect(registryTable).toContainText("28");
  await expect(registryTable).not.toContainText(FIRST_ARTIFACT_CANARY);
  await expect(registryTable).not.toContainText("Model ID");
  await expect(registryTable).not.toContainText("Artifact ID");
  await expect(page.getByText(FIRST_ARTIFACT_CANARY, { exact: true })).toBeVisible();
  await expect(page.locator("body")).toContainText("Research graph evidence only");
  await expect(page.locator("body")).toContainText("Target-local reference withheld");
  await expect(page.locator("body")).not.toContainText("C:\\Users\\james");
  await expect(page.locator("body")).toContainText("No Bundle Exported");
  await expect(page.getByText("EXPORT DISABLED", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Export unavailable" })).toBeDisabled();
  await expect(page.getByText("No standalone ASP model bundle has been approved or exported.", { exact: true })).toBeVisible();
  await expectResponsiveShell(page, 1024, 768);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/evaluation-calibration?phase3-browser=evaluation");
  await expect(page.getByRole("heading", { name: "Evaluation & Calibration" })).toBeVisible();
  await expect(page.getByRole("img", { name: /registered evaluation rows compared/i }).first()).toBeVisible();
  await expect(page.getByRole("table", { name: "Temporal evaluation metric comparison" }).last()).toContainText("1.481812");
  await expect(page.getByText("Fitted temperature", { exact: true }).locator("..")).toContainText("0.976519");
  await expect(page.locator("body")).not.toContainText("\\\\server\\share");
  await expect(page.getByRole("img", { name: "10 provided reliability bins" })).toBeVisible();
  await expect(page.getByRole("img", { name: "8 supplied classwise reliability curves" })).toBeVisible();
  await expect(page.getByRole("img", { name: "8 supplied predicted-probability histograms" })).toBeVisible();
  await expect(page.getByText("No Evaluation Evidence", { exact: true })).toHaveCount(0);
  await expectResponsiveShell(page, 390, 844);

  // The modeling dev entry uses React StrictMode, so each mount may issue the
  // same read twice. Either way every full-page route load must be authenticated
  // and must resolve the nested active-dataset authority through our harness.
  expect(calls.auth).toBeGreaterThanOrEqual(3);
  expect(calls.activeDataset).toBeGreaterThanOrEqual(3);
  expect(calls.unexpected).toEqual([]);
  expect(pageErrors).toEqual([]);
});

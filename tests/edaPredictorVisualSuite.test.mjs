import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const read = async (path) =>
  (await readFile(new URL(`../${path}`, import.meta.url), "utf8")).replace(
    /\r\n/g,
    "\n"
  );

const [
  dataSource,
  typeSource,
  landscapeSource,
  secondarySource,
  lazySource,
  barrelSource,
  distributionSource,
  performanceSource,
] = await Promise.all([
  read("src/components/eda/visual/predictorVisualData.ts"),
  read("src/components/eda/visual/predictorVisualTypes.ts"),
  read("src/components/eda/visual/PredictorSignalLandscape.tsx"),
  read("src/components/eda/visual/PredictorSecondaryInsights.tsx"),
  read("src/components/eda/visual/LazyPredictorSecondaryInsights.tsx"),
  read("src/components/eda/visual/PredictorVisualSuite.tsx"),
  read("src/components/eda/visual/PredictorDistributionExplorer.tsx"),
  read("src/visual-intelligence/performance.ts"),
]);

const transpiledData = ts.transpileModule(dataSource, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const dataModule = await import(
  `data:text/javascript;base64,${Buffer.from(transpiledData).toString("base64")}`
);

function contract(profileCount) {
  return {
    version: "eda-predictor-visual-v1",
    request_mode: "single_batched_workspace_request",
    scope: "full_dataset_aggregates",
    profile_count: profileCount,
    event_rate_shape_limit: 8,
    raw_observations_included: false,
    server_authorized_predictors_only: true,
    target_excluded: true,
    target_source_exclusions_disclosed_at_response_root: true,
    non_overlapping_quality_buckets: [
      "null_missing",
      "bureau_special_value",
      "ordinary_outlier",
    ],
    additional_vif_computation: false,
    vif_status: "pending_relationship_review",
  };
}

function numericProfile(feature) {
  return {
    feature,
    kind: "numeric",
    scope: "full_dataset_aggregates",
    population_rows: 100,
    metrics: {
      iv: 0.24,
      missing_rate: 0.1,
      outlier_count: 4,
      outlier_rate: 0.05,
      distinct_count: 72,
      skewness: 1.4,
      monotonicity: "increasing",
      vif: null,
      vif_status: "pending_relationship_review",
      special_prevalence: 0.1,
    },
    ordinary_outlier: {
      count: 4,
      rate: 0.05,
      denominator: 80,
      excludes_nulls: true,
      excludes_bureau_special_values: true,
      semantics: "regular_numeric_iqr_only",
    },
    missing: {
      count: 10,
      rate: 0.1,
      event_rate: 0.2,
      semantics: "null_only",
    },
    bureau_special: {
      identified: true,
      count: 10,
      prevalence: 0.1,
      regular_numeric_count: 80,
      values: [
        {
          value: -7,
          definition: "Condition not met",
          count: 10,
          prevalence: 0.1,
          event_rate: 0.3,
        },
      ],
      missing_values_included: false,
    },
    event_rate_shape: {
      kind: "quantile",
      scope: "full_dataset_aggregates",
      limit: 8,
      groups: [
        { label: "Q1", count: 40, event_rate: 0.1 },
        { label: "Q2", count: 40, event_rate: 0.3 },
      ],
      returned_groups: 2,
      truncated: false,
      raw_observations_included: false,
    },
  };
}

function categoricalProfile(feature) {
  return {
    feature,
    kind: "categorical",
    scope: "full_dataset_aggregates",
    population_rows: 100,
    metrics: {
      iv: 0.08,
      missing_rate: 0.05,
      outlier_count: null,
      outlier_rate: null,
      distinct_count: 3,
      skewness: null,
      monotonicity: null,
      vif: null,
      vif_status: "not_applicable_categorical",
      special_prevalence: 0,
    },
    missing: {
      count: 5,
      rate: 0.05,
      event_rate: 0.2,
      semantics: "null_only",
    },
    bureau_special: {
      identified: false,
      count: 0,
      prevalence: 0,
      values: [],
      missing_values_included: false,
    },
    event_rate_shape: {
      kind: "top_levels",
      scope: "full_dataset_aggregates",
      limit: 8,
      groups: [
        { label: "A", count: 55, event_rate: 0.1 },
        { label: "B", count: 40, event_rate: 0.2 },
      ],
      returned_groups: 2,
      truncated: false,
      raw_observations_included: false,
    },
  };
}

test("canonical adapter fails closed and excludes target-lineage fields", () => {
  const profiles = [
    numericProfile("utilization"),
    categoricalProfile("region"),
    numericProfile("bad_flag"),
    numericProfile("RiskPerformance"),
  ];
  const rows = dataModule.buildAuthorizedPredictorVisualData({
    predictorVisualProfiles: profiles,
    predictorVisualContract: contract(profiles.length),
    authorizedPredictors: [
      "utilization",
      "region",
      "bad_flag",
      "RiskPerformance",
    ],
    target: "outcome",
    targetSourceExcluded: ["RiskPerformance"],
    rowCount: 100,
  });
  assert.deepEqual(
    rows.map((row) => row.feature),
    ["utilization", "region"]
  );
  const numeric = rows[0];
  assert.equal(numeric.ordinaryOutlierPopulationRate, 0.04);
  assert.equal(numeric.ordinaryInlierPopulationRate, 0.76);
  assert.equal(
    numeric.missingRate +
      numeric.specialValueRate +
      numeric.ordinaryOutlierPopulationRate +
      numeric.ordinaryInlierPopulationRate,
    1
  );
  assert.equal(numeric.specialValueDetails[0].value, "-7");

  const invalidContract = {
    ...contract(profiles.length),
    raw_observations_included: true,
  };
  assert.deepEqual(
    dataModule.buildAuthorizedPredictorVisualData({
      predictorVisualProfiles: profiles,
      predictorVisualContract: invalidContract,
      authorizedPredictors: ["utilization", "region"],
      target: "outcome",
      rowCount: 100,
    }),
    []
  );
});

test("suite uses one already-loaded aggregate response and bounded marks", () => {
  const combined = [
    dataSource,
    landscapeSource,
    secondarySource,
    lazySource,
  ].join("\n");
  assert.doesNotMatch(combined, /\bfetch\s*\(/);
  assert.match(typeSource, /predictorVisualProfiles\?: PredictorVisualProfile\[\]/);
  assert.match(typeSource, /predictorVisualContract\?: PredictorVisualContract/);
  assert.match(dataSource, /single_batched_workspace_request/);
  assert.match(dataSource, /PREDICTOR_VISUAL_MAX_MARKS = 60/);
  assert.match(dataSource, /PREDICTOR_GALLERY_MAX = 10/);
  assert.match(dataSource, /PREDICTOR_MATRIX_MAX_ROWS = 30/);
});

test("primary landscape is static while secondary insights are lazy", () => {
  assert.match(barrelSource, /PredictorSignalLandscape/);
  assert.match(barrelSource, /default.*LazyPredictorSecondaryInsights/);
  assert.match(lazySource, /\blazy\s*\(/);
  assert.match(lazySource, /import\("\.\/PredictorSecondaryInsights"\)/);
  assert.match(lazySource, /IntersectionObserver/);
  assert.match(lazySource, /rootMargin: "360px 0px"/);
});

test("four distinct visuals expose purpose, controls, accessibility, and export", () => {
  assert.match(landscapeSource, /Predictor Signal Landscape/);
  assert.match(landscapeSource, /Which predictors stand out/);
  assert.match(secondarySource, /Predictor Quality Matrix/);
  assert.match(secondarySource, /Where are quality or treatment risks/);
  assert.match(secondarySource, /Event-Rate Shape Gallery/);
  assert.match(secondarySource, /How does target behavior vary/);
  assert.match(secondarySource, /Missingness \/ Special-Value Map/);
  assert.match(secondarySource, /What exceptional values require treatment/);
  assert.match(landscapeSource + secondarySource, /Export CSV/);
  assert.match(landscapeSource + secondarySource, /role="button"/);
  assert.match(landscapeSource + secondarySource, /tabIndex=\{0\}/);
  assert.match(landscapeSource + secondarySource, /onKeyDown/);
  assert.match(secondarySource, /mutually exclusive/i);
  assert.doesNotMatch(secondarySource, /data-outlier-marker/);
});

test("motion, linked selection, and exact performance events are wired", () => {
  const visuals = landscapeSource + secondarySource;
  assert.match(visuals, /runAtlasD3Transition/);
  assert.match(visuals, /useReducedMotion/);
  assert.match(visuals, /useEdaVisualSelection/);
  assert.match(visuals, /setSelectedVariable/);
  assert.match(landscapeSource, /"predictor-landscape-ready"/);
  assert.match(visuals, /"interaction-response"/);
  assert.match(performanceSource, /\| "predictor-landscape-ready"/);
  assert.match(performanceSource, /\| "interaction-response"/);
  assert.match(performanceSource, /\| "distribution-explorer-ready"/);
  assert.match(performanceSource, /name\.endsWith\("-ready"\)/);
  assert.match(distributionSource, /"distribution-explorer-ready"/);
  assert.match(
    distributionSource,
    /if \(!activeRange && !initialUnbrushedReadyRecorded\.current\)/
  );
});

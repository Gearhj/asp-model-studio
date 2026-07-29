import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

async function importTypeScript(path) {
  const output = ts.transpileModule(read(path), {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: path,
  }).outputText;
  return import(
    `data:text/javascript;base64,${Buffer.from(output).toString("base64")}`
  );
}

const sources = {
  outliers: read("src/steps/Step04_Outliers.tsx"),
  missing: read("src/steps/Step04_MissingValues.tsx"),
  features: read("src/steps/Step05_EncodingScaling.tsx"),
  chrome: read(
    "src/components/preparation/PreparationPageChrome.tsx",
  ),
  styles: read(
    "src/components/preparation/preparation-premium.css",
  ),
  recommendations: read("src/lib/featureRecommendations.ts"),
  governance: read("src/lib/preparationGovernance.ts"),
  authorization: read(
    "server/preprocessing/predictor_authorization.py",
  ),
  outlierService: read("server/preprocessing/outlier_service.py"),
  outlierRouter: read("server/preprocessing/outlier_router.py"),
  missingRouter: read("server/preprocessing/missing_router.py"),
  featureService: read("server/features/feature_service.py"),
  preparationDocs: read(
    "server/preprocessing/preparation_documentation_router.py",
  ),
  mdd: read("src/steps/ModelDocumentationStudio.tsx"),
  mddPanel: read(
    "src/components/documentation/PreparationDocumentationLiveLink.tsx",
  ),
};

const [outlierHelpers, featureRecommendations] = await Promise.all([
  importTypeScript("src/lib/outlierPremium.ts"),
  importTypeScript("src/lib/featureRecommendations.ts"),
]);

test("shared preparation pages use compact governed identity and responsive footer-safe composition", () => {
  for (const page of [
    sources.outliers,
    sources.missing,
    sources.features,
  ]) {
    assert.match(page, /hideHeader/);
    assert.match(page, /PreparationPageIdentity/);
    assert.match(page, /PreparationQuickSummary/);
  }
  assert.match(sources.chrome, /Predictive Modeling/);
  assert.match(sources.chrome, /Backend enforced/);
  assert.match(sources.chrome, /Dataset/);
  assert.match(sources.chrome, /Target/);
  assert.match(sources.chrome, /Manifest/);
  assert.match(sources.styles, /@media \(max-width: 1024px\)/);
  assert.match(sources.styles, /@media \(prefers-reduced-motion: reduce\)/);
});

test("outliers exposes coordinated premium diagnostics and explicit governed states", () => {
  for (const phrase of [
    "Outlier Burden Landscape",
    "Treatment Impact Preview",
    "Method Comparison",
    "Outlier / Skew / Special-Value Pattern Map",
    "Preview only — no backend mutation",
    "Override rationale",
    "Suggested",
    "Selected",
    "Applying",
    "Applied",
    "Failed",
    "Stale",
  ]) {
    assert.ok(
      sources.outliers.includes(phrase),
      `missing outlier contract: ${phrase}`,
    );
  }
  assert.match(sources.outliers, /acknowledged_high_impact/);
  assert.doesNotMatch(sources.outliers, /window\.confirm/);
  assert.match(sources.outliers, /outlier-high-impact-inline-notice/);
  assert.match(sources.outliers, /no rows were removed/i);
  assert.match(sources.outlierRouter, /idempotent/);
  assert.match(sources.outlierRouter, /High-impact confirmation is required/);
});

test("outlier method comparison is deterministic and nonmutating", () => {
  const input = [1, 2, 3, 4, 5, 100];
  const before = [...input];
  const rows = outlierHelpers.buildOutlierMethodComparisons(input, {
    lower: 0,
    upper: 10,
  });
  assert.deepEqual(input, before);
  assert.equal(rows.length, 7);
  assert.deepEqual(
    rows.map((row) => row.method),
    [
      "None",
      "1.5 IQR capping",
      "Winsorization 0.5 / 99.5",
      "Percentile capping 5 / 95",
      "Log1p",
      "Robust scaling",
      "Custom bounds",
    ],
  );
  assert.equal(rows[0].changedValues, 0);
  assert.ok(rows[1].changedValues > 0);
  assert.equal(rows.at(-1).maximum, 10);
});

test("outlier paired previews cap the rendered sample without mutating it", () => {
  const input = [-10, 0, 5, 20];
  const before = [...input];
  const after = outlierHelpers.applyOutlierPreviewTreatment(input, {
    method: "IQR_1_5",
    lower_threshold: 0,
    upper_threshold: 10,
  });
  assert.deepEqual(input, before);
  assert.deepEqual(after, [0, 0, 5, 10]);

  const none = outlierHelpers.applyOutlierPreviewTreatment(input, {
    method: "NONE",
    lower_threshold: 0,
    upper_threshold: 10,
  });
  assert.deepEqual(none, input);

  const histograms = outlierHelpers.buildCommonHistogramPair(input, after, 6);
  assert.equal(histograms.before.reduce((sum, count) => sum + count, 0), 4);
  assert.equal(histograms.after.reduce((sum, count) => sum + count, 0), 4);
  assert.equal(histograms.minimum, -10);
  assert.equal(histograms.maximum, 20);
});

test("outlier backend separates bureau specials and enforces predictor authorization", () => {
  assert.match(sources.authorization, /BUREAU_SPECIAL_VALUES = \(-9\.0, -8\.0, -7\.0\)/);
  assert.match(sources.authorization, /detect_deterministic_target_sources/);
  assert.match(sources.outlierService, /ordinary = numeric\.mask\(special_mask\)/);
  assert.match(sources.outlierService, /special_values_preserved/);
  assert.match(sources.outlierService, /authorized_predictors/);
  assert.doesNotMatch(
    sources.outlierService,
    /for column in df\.columns:[\s\S]{0,80}_numeric/,
  );
});

test("missing values presents the truthful HELOC zero-null decision", () => {
  assert.match(
    sources.missing,
    /No null imputation is required for the current modeling\s+population\./,
  );
  assert.match(
    sources.missing,
    /Bureau special values remain governed values and are\s+handled separately\./,
  );
  assert.match(sources.missing, /Recommended strategy:[\s\S]*None/);
  assert.match(sources.missing, /Validated, no treatment required/);
  assert.match(sources.missing, /No processed frame will be created/);
  assert.match(sources.missing, /Missingness and Imputation Map/);
  assert.match(sources.missing, /projectedImputationValue/);
  assert.doesNotMatch(sources.missing, /title="Missingness Profile"/);
  assert.doesNotMatch(sources.missing, /title="Missing vs Special-Value Profile"/);
  assert.match(sources.missing, /Missingness Mechanism Review/);
  assert.match(sources.missing, /globalStrategy === "Constant"/);
});

test("zero-null backend uses validation rather than materialization", () => {
  assert.match(sources.missingRouter, /@router\.post\("\/validate"\)/);
  assert.match(
    sources.missingRouter,
    /"backend_materialization": False/,
  );
  assert.match(
    sources.missingRouter,
    /Use validation instead of materialization/,
  );
  const validationBody =
    sources.missingRouter.match(
      /def validate_missing_values[\s\S]*?(?=\n@router\.post\("\/apply"\))/,
    )?.[0] ?? "";
  assert.doesNotMatch(validationBody, /set_processed/);
});

test("recommendation engine produces the seven conservative HELOC candidates without target use", () => {
  const availableFeatures = [
    "NumTotalTrades",
    "NumSatisfactoryTrades",
    "ExternalRiskEstimate",
    "NetFractionRevolvingBurden",
    "AverageMInFile",
    "NumTrades60Ever2DerogPubRec",
    "NumTrades90Ever2DerogPubRec",
    "NumInqLast6M",
    "NumInqLast6Mexcl7days",
    "PercentTradesNeverDelq",
  ];
  const recommendations =
    featureRecommendations.buildFeatureRecommendations({
      availableFeatures,
      excludedFeatures: {
        bad_flag: "Target column",
        RiskPerformance:
          "Deterministic source of the modeling target",
      },
    });
  assert.equal(recommendations.length, 7);
  assert.deepEqual(
    recommendations.map((row) => row.featureName),
    [
      "non_satisfactory_trade_count",
      "external_risk_band",
      "high_revolving_burden_flag",
      "average_months_in_file_squared",
      "delinquency_severity_composite",
      "inquiry_window_difference",
      "external_risk_x_never_delinquent",
    ],
  );
  assert.ok(recommendations.every((row) => row.eligible));
  assert.ok(
    recommendations.every(
      (row) =>
        !row.sourceFeatures.includes("bad_flag") &&
        !row.sourceFeatures.includes("RiskPerformance"),
    ),
  );
  assert.ok(
    recommendations.every(
      (row) => !/expected lift|will improve|guaranteed/i.test(row.expectedBenefit),
    ),
  );
});

test("feature recommendations remain review-only and expose complete decision cards", () => {
  for (const phrase of [
    "Recommendation Landscape",
    "Accept to Plan",
    "Reject",
    "Defer",
    "Potential analytical benefit",
    "Leakage assessment",
    "Validation requirement",
    "no expected lift claim",
    "never auto-accepted",
  ]) {
    assert.ok(
      sources.features.includes(phrase),
      `missing feature recommendation contract: ${phrase}`,
    );
  }
  assert.match(sources.features, /recommendationToFeatureDraft/);
  assert.match(sources.features, /setDirty\(true\)/);
  assert.match(sources.features, /No feature was added or materialized/);
});

test("builder safety distinguishes deterministic materialization from learned pipeline work", () => {
  assert.match(
    sources.features,
    /Unavailable: no governed date predictor is present\./,
  );
  assert.match(sources.features, /Duration fields[\s\S]*not calendar dates/);
  assert.match(sources.features, /Binning mode/);
  assert.match(sources.features, /zero-denominator policy/);
  assert.match(sources.features, /Polynomial terms can magnify scale/);
  assert.match(sources.features, /Deterministic before split/);
  assert.match(sources.features, /fit on training data only/);
  assert.match(sources.featureService, /binning_mode/);
  assert.match(sources.featureService, /preserve_bureau_special_values/);
});

test("feature plan exposes recommendation, preview, lineage, pipeline, and redundancy views", () => {
  for (const phrase of [
    "Recommendation Before / After Preview",
    "Feature Lineage Graph",
    "Plan Pipeline",
    "Transformation Plan",
    "Pipeline Transformations",
    "Predictor Redundancy Check",
  ]) {
    assert.ok(sources.features.includes(phrase));
  }
  assert.match(sources.features, /previewFeaturePlan/);
  assert.match(sources.features, /materializeFeatureManifest/);
  assert.match(sources.features, /Run VIF diagnostics/);
});

test("cross-page EDA carry-forward remains a destination draft until accepted", () => {
  assert.match(sources.governance, /draft_recommendation/);
  assert.match(sources.governance, /destinationMatches/);
  assert.match(sources.chrome, /never mutate this plan automatically/);
  assert.match(sources.outliers, /CarryForwardPanel/);
  assert.match(sources.missing, /CarryForwardPanel/);
  assert.match(sources.features, /CarryForwardPanel/);
});

test("Model Documentation Studio reads live preparation decisions and stale state", () => {
  assert.match(sources.mdd, /PreparationDocumentationLiveLink/);
  assert.match(sources.mddPanel, /Preparation Decision Record/);
  assert.match(sources.mddPanel, /Validated, no treatment required/);
  assert.match(sources.mddPanel, /Confirmed/);
  assert.match(sources.mddPanel, /Stale/);
  assert.match(sources.preparationDocs, /documentation_version/);
  assert.match(sources.preparationDocs, /accepted_features/);
  assert.match(sources.preparationDocs, /materialized_features/);
  assert.match(sources.preparationDocs, /target_source_excluded/);
});

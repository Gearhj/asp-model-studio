import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const acquisition = read("src/steps/Step01_DataAcquisition.tsx");
const eda = read("src/steps/Step02_EDA.tsx");
const outliers = read("src/steps/Step04_Outliers.tsx");
const missing = read("src/steps/Step04_MissingValues.tsx");
const features = read("src/steps/Step05_EncodingScaling.tsx");
const missingBackend = read("server/preprocessing/missing_router.py");
const featureBackend = read("server/features/feature_service.py");

test("Data Acquisition elevates the authoritative target decision", () => {
  assert.match(acquisition, /data-testid="data-acquisition-target-setup"/);
  assert.match(acquisition, /Required modeling decision/);
  assert.match(acquisition, /Identify the Target Variable/);
  assert.match(acquisition, /border-2 border-blue-500/);
  assert.match(acquisition, /Target contract confirmed: \$\{props\.target\}/);
  assert.match(acquisition, /data-testid="confirm-initial-target-contract"/);
  assert.match(acquisition, /Confirm Target &amp; Predictor Contract/);
});

test("EDA names the Data Acquisition target and event in source exclusion", () => {
  assert.match(eda, /const configuredTarget = String\(data\.target/);
  assert.match(eda, /data\.event_value/);
  assert.match(eda, /Data Acquisition target: \$\{configuredTarget\}/);
  assert.match(eda, /Target excluded from predictors/);
});

test("Outliers uses one inline apply action and clips capped evidence", () => {
  assert.match(outliers, /data-testid="outlier-global-treatment"/);
  assert.match(outliers, /data-testid="outlier-apply-treatments"/);
  assert.match(outliers, /data-testid="outlier-high-impact-inline-notice"/);
  assert.doesNotMatch(outliers, /window\.confirm/);
  assert.match(outliers, /clipToThresholds/);
  assert.match(outliers, /outlier-capped-histogram-clip/);

  const tableStart = outliers.indexOf("function OutlierFeatureTable");
  const tableEnd = outliers.indexOf("function CutoffHistogramGallery", tableStart);
  const table = outliers.slice(tableStart, tableEnd);
  assert.ok(table.indexOf("Predictor") < table.indexOf("Outliers"));
  assert.ok(table.indexOf("Outliers") < table.indexOf("Nonmissing"));
  assert.doesNotMatch(table, />Type</);
});

test("Missing Values exposes live count, rate, and imputed value", () => {
  assert.match(missing, />Missing</);
  assert.match(missing, />Missing rate</);
  assert.match(missing, />Imputed value</);
  assert.match(missing, /projectedImputationValue\(/);
  assert.match(missing, /data-testid=\{`missing-imputed-value-\$\{column\.name\}`\}/);
  assert.match(missing, /Missingness and Imputation Map/);
  assert.match(missing, /data-testid=\{`missing-impact-value-\$\{column\.name\}`\}/);
  assert.match(missing, /data-testid="missing-distribution-gallery"/);
  assert.match(missing, /<MissingDistributionHistogram/);
  assert.match(
    missing,
    /selected\.strategy === "Constant"[\s\S]{0,220}\? \{[\s\S]{0,160}constantValue: String\(selected\.constantValue \?\? ""\)[\s\S]{0,120}: \{ strategy: selected\.strategy \}/,
  );
  assert.match(missingBackend, /"mode": mode_value/);
});

test("Feature Engineering renders builder before a live summary inventory", () => {
  assert.match(features, /prep-feature-builder-launcher order-\[10\]/);
  assert.match(features, /order-\[20\]" data-testid="feature-set-review"/);
  assert.match(features, /data-testid="feature-builder-configuration"/);
  assert.match(features, /Add to feature inventory/);
  assert.match(features, /Feature Inventory and Summary Statistics/);
  assert.match(features, />Std dev</);
  assert.match(featureBackend, /def _feature_summary_statistics/);
  assert.match(featureBackend, /"standard_deviation"/);
});

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

const outliers = read("src/steps/Step04_Outliers.tsx");
const missing = read("src/steps/Step04_MissingValues.tsx");
const modelDevelopmentDocument = read(
  "src/lib/modelDevelopmentDocument.ts",
);

function sectionBody(source, id) {
  const marker = `id="${id}"`;
  const markerIndex = source.indexOf(marker);
  assert.notEqual(markerIndex, -1, `missing section ${id}`);
  const start = source.lastIndexOf("<AtlasWorkflowSection", markerIndex);
  const end = source.indexOf("</AtlasWorkflowSection>", markerIndex);
  assert.ok(start >= 0 && end > markerIndex, `could not isolate section ${id}`);
  return source.slice(start, end);
}

function selectByTestId(source, testId) {
  const marker = `data-testid="${testId}"`;
  const markerIndex = source.indexOf(marker);
  assert.notEqual(markerIndex, -1, `missing select ${testId}`);
  const start = source.lastIndexOf("<select", markerIndex);
  const end = source.indexOf("</select>", markerIndex);
  assert.ok(start >= 0 && end > markerIndex, `could not isolate select ${testId}`);
  return source.slice(start, end);
}

function functionBody(source, functionName, nextFunctionName) {
  const start = source.indexOf(`function ${functionName}`);
  assert.notEqual(start, -1, `missing function ${functionName}`);
  const end = nextFunctionName
    ? source.indexOf(`function ${nextFunctionName}`, start + 1)
    : source.indexOf("\n  return (", start + 1);
  assert.ok(end > start, `could not isolate function ${functionName}`);
  return source.slice(start, end);
}

test("Outliers makes an open all-feature summary table the primary decision surface", () => {
  const section = sectionBody(outliers, "outlier-feature-summary-table");
  const table = functionBody(
    outliers,
    "OutlierFeatureTable",
    "CutoffHistogramGallery",
  );

  assert.match(section, /<OutlierFeatureTable/);
  assert.match(table, /data-testid="outlier-feature-summary-table"/);
  assert.match(table, /<table/);
  assert.match(table, /\{rows\.map\(\(row\) =>/);
  assert.doesNotMatch(table, /<details|<Pagination|pagedRows/);

  for (const contract of [
    /row\.nonmissing_count/,
    /row\.missing_count/,
    /row\.special_value_count/,
    /row\.distinct_count/,
    /row\.mean/,
    /row\.standard_deviation/,
    /row\.minimum/,
    /row\.quantiles\??\.p(?:05|25)/,
    /row\.quantiles\??\.median/,
    /row\.quantiles\??\.p(?:75|95)/,
    /row\.maximum/,
    /row\.signal_metric/,
  ]) {
    assert.match(table, contract);
  }
});

test("Outlier global treatment immediately drives every inheriting table row", () => {
  const globalSelect = selectByTestId(outliers, "outlier-global-treatment");
  const changeGlobal = functionBody(
    outliers,
    "changeGlobalMethod",
    "applyGlobalSelection",
  );

  assert.match(globalSelect, /onChange=\{\(event\) =>[\s\S]*changeGlobalMethod/);
  assert.doesNotMatch(globalSelect, /\bdisabled=/);
  assert.match(changeGlobal, /setGlobalMethod\(method\)/);
  assert.match(changeGlobal, /summary table and cutoff histograms have been updated/i);
  assert.match(
    outliers,
    /configured === "USE_GLOBAL"[\s\S]{0,120}\? globalMethod/,
  );
  assert.match(
    outliers,
    /configured === storedGlobal && !hasOverrideRationale[\s\S]{0,120}"USE_GLOBAL"/,
  );
  assert.match(
    outliers,
    /row\.methods\?\.\[[\s\S]{0,120}effectiveMethod\([\s\S]{0,120}globalMethod/,
  );
});

test("Outlier table leads with predictor and treatment-dependent count", () => {
  const table = functionBody(
    outliers,
    "OutlierFeatureTable",
    "CutoffHistogramGallery",
  );
  const predictorHeader = table.indexOf("Predictor");
  const outlierHeader = table.indexOf("Outliers", predictorHeader);
  const nonmissingHeader = table.indexOf("Nonmissing", outlierHeader);

  assert.ok(predictorHeader >= 0, "the table must lead with a Predictor header");
  assert.ok(
    predictorHeader < outlierHeader && outlierHeader < nonmissingHeader,
    "Predictor, Outliers, and Nonmissing must be the leading columns",
  );
  assert.doesNotMatch(table, />Type</);
  assert.match(table, /data-testid="outlier-count-cell"/);
  assert.match(table, /method\?\.outlier_count\.toLocaleString\(\)/);
  assert.match(table, /data-effective-method=\{method\?\.method/);
  assert.match(
    table,
    /row\.methods\?\.\[[\s\S]{0,120}effectiveMethod\(configured, globalMethod\)/,
  );
});

test("Outlier feature overrides are usable and can explicitly return to global", () => {
  const overrideSelect = selectByTestId(
    outliers,
    "outlier-feature-override",
  );
  const tableSection = sectionBody(outliers, "outlier-feature-summary-table");

  assert.match(overrideSelect, /value=\{configured\}/);
  assert.match(overrideSelect, /onChange\(/);
  assert.match(tableSection, /onChange=\{changeFeature\}/);
  assert.match(overrideSelect, /<option value="USE_GLOBAL">/);
  assert.match(overrideSelect, /Use global/i);
  assert.doesNotMatch(overrideSelect, /\bdisabled=/);
  assert.match(
    outliers,
    /method === "USE_GLOBAL"[\s\S]{0,300}delete next\[feature\]/,
  );
});

test("Outlier histograms default to the top 10 by IV and expose active low/high cutoffs", () => {
  const countSelect = selectByTestId(outliers, "outlier-histogram-limit");

  assert.match(outliers, /useState\(10\)/);
  assert.match(
    outliers,
    /Math\.abs\(right\.signal_metric \?\? 0\)[\s\S]{0,180}Math\.abs\(left\.signal_metric \?\? 0\)/,
  );
  assert.match(
    outliers,
    /signalRankedRows\.slice\([\s\S]{0,100}histogramLimit/,
  );
  assert.match(countSelect, /value=\{10\}[\s\S]*Top 10/i);
  assert.match(countSelect, /value=\{20\}[\s\S]*Top 20/i);
  assert.match(countSelect, />\s*All predictors</i);
  assert.match(outliers, /Top Predictors by IV/);
  assert.match(outliers, /Ten predictors are shown by default/i);
  assert.match(
    outliers,
    /data-testid="outlier-cutoff-histogram-gallery"/,
  );
  assert.match(outliers, /data-testid="outlier-low-cutoff"/);
  assert.match(outliers, /data-testid="outlier-high-cutoff"/);
  assert.match(outliers, /Low cutoff/);
  assert.match(outliers, /High cutoff/);
  assert.match(
    outliers,
    /effectiveMethod\(config\[row\.feature\], globalMethod\)/,
  );
  assert.match(outliers, /method\??\.lower_threshold|method\.lower_threshold/);
  assert.match(outliers, /method\??\.upper_threshold|method\.upper_threshold/);
  assert.match(outliers, /testId="outlier-before-histogram"/);
  assert.match(outliers, /testId="outlier-after-histogram"/);
  assert.match(
    outliers,
    /applyOutlierPreviewTreatment\(sample, method\)/,
  );
  assert.match(
    outliers,
    /buildCommonHistogramPair\(sample, treatedSample\)/,
  );
  assert.match(outliers, /title="Before capping"/);
  assert.match(outliers, /title="After capping"/);
  assert.match(outliers, /clipToThresholds/);
  assert.match(outliers, /outlier-capped-histogram-clip/);
  assert.match(outliers, /clipPath: `inset/);
});

test("Outlier apply is adjacent to the global selector and never opens a blocking alert", () => {
  const section = sectionBody(outliers, "outlier-feature-summary-table");
  const selector = section.indexOf('data-testid="outlier-global-treatment"');
  const apply = section.indexOf('data-testid="outlier-apply-treatments"');
  const table = section.indexOf("<OutlierFeatureTable");

  assert.ok(selector >= 0 && apply > selector && apply < table);
  assert.match(section, /outlier-high-impact-inline-notice/);
  assert.doesNotMatch(outliers, /window\.confirm/);
});

test("Missing Values makes an open all-feature stats and treatment table primary", () => {
  const section = sectionBody(missing, "missing-feature-table");

  assert.match(section, /All-Feature Missing-Value Summary and Treatment/);
  assert.match(
    section,
    /<table[^>]*data-testid="missing-all-feature-table"/,
  );
  assert.match(section, /\{rows\.map\(\(column\) =>/);
  assert.doesNotMatch(section, /<details|<Pagination|pagedRows/);

  for (const contract of [
    /stats\?\.missing/,
    /stats\?\.missingPct/,
    /stats\?\.special_value_count/,
    /stats\?\.nonmissing_count/,
    /stats\?\.distinct_count/,
    /stats\?\.mean/,
    /stats\?\.standard_deviation/,
    /stats\?\.minimum/,
    /stats\?\.first_quartile/,
    /stats\?\.median/,
    /stats\?\.third_quartile/,
    /stats\?\.maximum/,
    /stats\?\.information_value|stats\?\.correlation_with_target/,
    /projectedImputationValue\(/,
  ]) {
    assert.match(section, contract);
  }
});

test("Missing global and feature controls stay live when true-null count is zero", () => {
  const globalSelect = selectByTestId(missing, "missing-global-strategy");
  const updateGlobal = functionBody(
    missing,
    "updateGlobalStrategy",
    "updateGlobalConstant",
  );
  const overrideMarker = "data-testid={`missing-override-${column.name}`}";
  const markerIndex = missing.indexOf(overrideMarker);
  assert.notEqual(markerIndex, -1, "missing per-feature override select");
  const overrideStart = missing.lastIndexOf("<select", markerIndex);
  const overrideEnd = missing.indexOf("</select>", markerIndex);
  const overrideSelect = missing.slice(overrideStart, overrideEnd);

  assert.match(globalSelect, /updateGlobalStrategy\(/);
  assert.doesNotMatch(globalSelect, /\bdisabled=/);
  assert.match(updateGlobal, /setGlobalStrategy\(strategy\)/);
  assert.match(updateGlobal, /buildGlobalConfig\(strategy, globalConstant\)/);
  assert.match(updateGlobal, /setConfig\(next\)/);
  assert.doesNotMatch(missing, /disabled=\{totalMissing === 0\}/);
  assert.match(missing, /function migrateLegacyPolicy\(/);
  assert.match(
    missing,
    /storedPolicy = migrateLegacyPolicy\([\s\S]{0,120}safePayload\.columns/,
  );

  assert.match(overrideSelect, /value="USE_GLOBAL"/);
  assert.match(overrideSelect, /Use global/i);
  assert.match(overrideSelect, /useGlobalStrategy\(column\)/);
  assert.doesNotMatch(overrideSelect, /\bdisabled=/);
  assert.match(
    missing,
    /data-testid=\{`missing-projection-\$\{column\.name\}`\}/,
  );
});

test("Missingness impact map uses IV-ranked expansion and live imputation values", () => {
  const countSelect = selectByTestId(missing, "missing-impact-count");
  const section = sectionBody(missing, "missing-treatment-impact");

  assert.match(missing, /useState\(10\)/);
  assert.match(
    missing,
    /information_value \?\? -1\)[\s\S]{0,160}information_value \?\? -1\)/,
  );
  assert.match(
    missing,
    /ivRankedColumns\.slice\(0, impactLimit\)/,
  );
  assert.match(countSelect, /value=\{10\}[\s\S]*Top 10 by IV/i);
  assert.match(countSelect, /value=\{20\}[\s\S]*Top 20 by IV/i);
  assert.match(countSelect, />\s*All predictors\s*</i);
  assert.match(section, /Select additional predictors/i);
  assert.match(section, /additionalImpactFeatures/);
  assert.match(
    missing,
    /data-testid=\{`missing-impact-\$\{column\.name\}`\}/,
  );
  assert.match(missing, /Missing burden/);
  assert.match(missing, /Imputed value/);
  assert.match(missing, /function projectedImputationValue\(/);
  assert.match(missing, /strategy === "Mean"/);
  assert.match(missing, /strategy === "Median"/);
  assert.match(missing, /stats\?\.mode/);
  assert.match(
    missing,
    /data-testid=\{`missing-impact-value-\$\{column\.name\}`\}/,
  );
  assert.doesNotMatch(section, /ordinary-value histogram/);
});

test("MDD captures the active global policies, inheritance, and explicit overrides", () => {
  assert.match(
    modelDevelopmentDocument,
    /function loadMissingTreatmentSummary\(projectId: string\)/,
  );
  assert.match(
    modelDevelopmentDocument,
    /function loadOutlierTreatmentSummary\(projectId: string\)/,
  );
  assert.match(
    modelDevelopmentDocument,
    /modeling-tool-missing-config:\$\{projectId\}/,
  );
  assert.match(
    modelDevelopmentDocument,
    /modeling-tool-outlier-methods:\$\{projectId\}/,
  );
  assert.match(
    modelDevelopmentDocument,
    /modeling-tool-outlier-global-method:\$\{projectId\}/,
  );
  assert.match(modelDevelopmentDocument, /"Global strategy"/);
  assert.match(modelDevelopmentDocument, /"Global method"/);
  assert.match(modelDevelopmentDocument, /"Inherited predictors"/);
  assert.match(modelDevelopmentDocument, /"Explicit overrides"/);
});

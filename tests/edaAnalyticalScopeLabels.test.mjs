import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

const step = read("src/steps/Step02_EDA.tsx");
const targetVisual = read("src/components/eda/TargetVisualInsights.tsx");
const targetWorkspace = read("src/components/eda/TargetIntelligenceWorkspace.tsx");
const targetPredictor = read("src/components/eda/TargetByPredictorPanel.tsx");
const landscape = read("src/components/eda/visual/PredictorSignalLandscape.tsx");
const distribution = read("src/components/eda/visual/PredictorDistributionExplorer.tsx");
const secondary = read("src/components/eda/visual/PredictorSecondaryInsights.tsx");
const correlation = read("src/components/eda/visual/CorrelationExplorer.tsx");
const relationship = read("src/components/eda/visual/RelationshipExplorer.tsx");
const vif = read("src/components/eda/visual/VifExplorer.tsx");

function includesAll(source, markers) {
  for (const marker of markers) {
    assert.match(source, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
}

test("target-directed preview and drilldown identify the Development Population", () => {
  includesAll(targetVisual, [
    "Top five server-authorized predictors by IV from the Development Population",
    "Development Population · {formatCount(preview?.population_rows)} rows",
    "final holdout accessed",
  ]);
  assert.doesNotMatch(targetVisual, /ranked from one batched full-population aggregate/);
  includesAll(targetWorkspace, [
    "Target by Predictor",
    "exact Development Population",
    "sealed final holdout is excluded",
  ]);
  includesAll(targetPredictor, [
    "Development Population · target-directed analysis",
    "Development rows",
    "Development Population target-by-predictor chart",
  ]);
});

test("predictor mixed-scope visuals disclose metric-by-metric scope", () => {
  includesAll(landscape, [
    "Mixed scope · Development signal · Full governed structure",
    "IV / target association (Development)",
    "Null missingness (Full governed)",
    "governed mixed scope: Development Population signal and Full Governed Population structure",
  ]);
  includesAll(distribution, [
    'data-scope="governed_mixed_scope"',
    "Full Governed Population · distribution",
    "Development Population · {developmentRows",
    "Selected target rate (Development)",
    "IV by bin · Development Population",
    "Governed mixed-scope chart",
  ]);
  includesAll(secondary, [
    "Development Population · target-directed event-rate bands and baseline",
    "Mixed scope · IV, monotonicity, and VIF use the Development Population",
    "Full Governed Population · structural missingness",
  ]);
});

test("predictor inventory separates structural and target-directed fields", () => {
  includesAll(step, [
    "Full Governed Population · structure",
    "Development Population · target signal",
    "Category Event Rate\" scope=\"Development Population",
    "IV (Development)",
    "Missing rows (Full governed)",
    "Event rate when missing (Development)",
  ]);
});

test("relationship, correlation, and VIF surfaces disclose development-only evidence", () => {
  includesAll(correlation, [
    "Development Population matrix",
    'data-analysis-scope="development_population"',
    "pairwise-complete Development Population observations",
  ]);
  includesAll(relationship, [
    "Development Population · bounded visual sample",
    'data-source-population="development_population"',
    "Ineligible / excluded",
    "sealed final holdout",
  ]);
  includesAll(vif, [
    "Development Population VIF bars",
    "Development Population · ${Number(scope.rows_used",
    "sealed final holdout is never accessed",
  ]);
  includesAll(step, [
    "Development Population source:",
    "complete-case rows eligible",
    "deterministically rendered for visualization only",
    "Strong correlated pairs · Development Population",
  ]);
});

test("conditional target analyses do not reuse the full-population target baseline", () => {
  includesAll(targetWorkspace, [
    "const developmentEventRate = useMemo",
    'name: "Development rows"',
    "Development Population target-directed analysis",
    "vs development",
  ]);
  assert.doesNotMatch(targetWorkspace, /populationEventRate=\{balance\?\.eventRate/);
});

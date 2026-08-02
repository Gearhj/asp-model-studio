// EDA-PREDICTORS-001 and EDA-EXPLORER-001: the Predictor Diagnostics
// instructional block is gone, and development EDA no longer exposes Scoring
// Run controls that are invalid before any split or durable run exists.
import fs from "node:fs";
import assert from "node:assert/strict";

const eda = fs.readFileSync("src/steps/Step02_EDA.tsx", "utf8");
const panel = fs.readFileSync("src/visual-intelligence/production/VisualAnalysisPanel.tsx", "utf8");
const distribution = fs.readFileSync(
  "src/components/eda/visual/PredictorDistributionExplorer.tsx",
  "utf8",
);
const packageJson = JSON.parse(fs.readFileSync("package.json", "utf8"));

assert.equal(packageJson.scripts["test:eda-development-context"], "node tests/edaDevelopmentContext.test.mjs");

// --- EDA-PREDICTORS-001: the instructional block is removed -----------------

assert.doesNotMatch(eda, /data-testid="predictor-diagnostics-workflow"/, "The four-step instructional workflow must be removed.");
assert.doesNotMatch(eda, /1\. Search or sort/, "The numbered workflow steps must be gone.");
assert.doesNotMatch(
  eda,
  /title="Predictor Diagnostics"/,
  "The Predictor Diagnostics heading must be gone."
);
assert.doesNotMatch(
  eda,
  /Review predictor quality, target relationship, missingness, distribution, outliers, information value, and leakage indicators/,
  "The explanatory paragraph must be removed."
);
// Renamed, not replaced with another instructional card.
assert.match(eda, /title="Detailed Predictor Profiles"/, "The functional area must have a concise inventory title.");

// Retained controls.
assert.match(eda, /placeholder="Search predictors"/, "Search must be retained.");
assert.match(eda, /Sort by target signal/, "Sort must be retained.");
assert.match(eda, /Show \{value\}/, "Page-size control must be retained.");
assert.match(eda, /Full Governed Population · structure/, "The structural scope indicator must be retained.");
assert.match(eda, /Development Population · target signal/, "The target-directed scope indicator must be explicit.");

// --- EDA-PREDICTORS/inventory behavior is preserved ------------------------

assert.match(eda, /data-testid="data-table-count"/, "Result counts must remain.");
assert.match(eda, /Showing \$\{inventoryCount\.shown\.toLocaleString\(\)\} of/, "Shown/matching/total counts must remain.");
assert.match(eda, /data-testid="data-table-filter-notice"/, "The active-search disclosure must remain.");
assert.match(eda, /data-selected-predictor=/, "The selected predictor must be highlighted in place.");
assert.match(eda, /title="All numeric predictors"/, "The full numeric inventory title must remain.");
assert.match(eda, /title="All categorical predictors"/, "The full categorical inventory title must remain.");

// --- EDA-EXPLORER-001 / Part E: development vs scoring context -------------

assert.match(panel, /analysisContext\?: "development" \| "scoring"/, "An explicit analysis context must exist.");
assert.match(panel, /analysisContext = "scoring"/, "Existing Evaluation/Scoring usage must default to the scoring context.");

// The Scoring Run selector (Partition / Status / archived / prev-next) is gated.
assert.match(
  panel,
  /\{analysisContext !== "development" \? \(\s*<ScoringRunSelector/,
  "The Scoring Run selector must be suppressed on development EDA."
);
// Run comparison is gated.
assert.match(
  panel,
  /\{analysisContext !== "development" \? \(\s*<button type="button" data-testid="va-compare-runs"/,
  "Compare Runs must be suppressed on development EDA."
);

// Phase 1 EDA now owns a purpose-built development explorer, so it must not
// mount the scoring-oriented panel or its legacy sampled prototype.
assert.match(
  eda,
  /<PredictorDistributionExplorer/,
  "Development EDA must mount the governed mixed-scope predictor explorer."
);
assert.doesNotMatch(
  eda,
  /<VisualAnalysisPanel/,
  "Development EDA must not mount the scoring-oriented visual-analysis shell."
);
assert.doesNotMatch(
  eda,
  /<DistributionExplorer/,
  "Development EDA must not mount the legacy sampled distribution prototype."
);
assert.doesNotMatch(
  eda,
  /durable TRAIN\/TEST\/OOT scoring run/,
  "Development EDA must not advertise TRAIN/TEST/OOT scoring runs."
);
assert.match(
  distribution,
  /Governed mixed-scope visual intelligence/,
  "The predictor explorer needs an explicit governed mixed-scope label."
);
assert.match(
  distribution,
  /Distribution, statistical markers, missingness, and outlier bounds use the Full[\s\S]*Development Population/,
  "The explorer needs an explicit structural-versus-target-directed scope statement."
);
assert.match(
  distribution,
  /eda\/workspace\/distribution/,
  "Development EDA must use the governed distribution aggregation endpoint."
);

// Evaluation/Scoring pages must keep their Scoring Run controls.
const scoringUsages = ["src/steps/Step08_Evaluation.tsx", "src/steps/Step10_Scoring.tsx"].filter((file) => fs.existsSync(file));
for (const file of scoringUsages) {
  const source = fs.readFileSync(file, "utf8");
  if (!source.includes("VisualAnalysisPanel")) continue;
  assert.doesNotMatch(
    source,
    /analysisContext="development"/,
    `${file} is a scoring context and must retain Scoring Run controls`
  );
}

console.log("edaDevelopmentContext.test.mjs: all checks passed.");

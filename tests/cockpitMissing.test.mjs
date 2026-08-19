// Phase 6E.3 — Missing Values page (cockpit step 05): blank-page repair + scientist UX (static checks).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (p) => readFile(new URL(p, ROOT), "utf8");
const [steps1, ui, shell] = await Promise.all([
  read("src/sports/cockpit/cockpitSteps1.tsx"),
  read("src/sports/cockpit/cockpitUi.tsx"),
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
]);
const missing = steps1.slice(steps1.indexOf("05 Missing Values"), steps1.indexOf("06 Feature Engineering"));

test("BLANK-PAGE REPAIR: analytical body auto-loads on mount (no manual Preview gate)", () => {
  // reactive auto-preview on the policy key — the body is not gated behind a manual click
  assert.ok(missing.includes('post.run("/cockpit/missing", { policy: JSON.parse(previewKey) })'));
  assert.ok(missing.includes("useEffect(") && missing.includes("[previewKey]"));
  // there is no longer a standalone "Preview" button as the only trigger
  assert.ok(!/onClick=\{preview\}/.test(missing));
});

test("the analytical region always renders a state — never blank", () => {
  assert.ok(missing.includes("Calculating development-fold missingness"));         // loading
  assert.ok(missing.includes("Missing-value analysis could not be loaded"));        // error
  assert.ok(missing.includes("No missing values were detected"));                   // zero-missing
  assert.ok(missing.includes("d.featuresWithMissing > 0"));                         // data
});

test("summary cards render and react to preview", () => {
  assert.ok(missing.includes('label="Observations"') && missing.includes("d.totalObservations"));
  assert.ok(missing.includes('label="Features analyzed"') && missing.includes("continuous +"));
  assert.ok(missing.includes('label="Features with missing values"') && missing.includes("d.featuresWithMissing"));
  assert.ok(missing.includes('label="Missing values"') && missing.includes("d.totalMissing"));
});

test("summary table exists with MISSING as the first quantitative column, default sort desc", () => {
  assert.ok(missing.includes('title="Missingness summary"'));
  const iFeature = missing.indexOf('label="Feature"');
  const iMissing = missing.indexOf('label="Missing"');
  const iPct = missing.indexOf('label="Missing %"');
  assert.ok(iFeature > 0 && iMissing > iFeature && iPct > iMissing);
  assert.ok(missing.includes('useState<{ key: "feature" | "missing" | "missingPct"; dir: 1 | -1 }>({ key: "missing", dir: -1 })'));
  // fill value + type + indicator + override columns
  assert.ok(missing.includes(">Fill value<") && missing.includes(">Type<") && missing.includes(">Indicator<") && missing.includes(">Override<"));
});

test("global method change updates the preview treatment without saving", () => {
  assert.ok(missing.includes("MISSING_METHODS") && missing.includes('{ value: "median"') && missing.includes('{ value: "none"'));
  assert.ok(missing.includes("const unsaved = savedKey !== previewKey"));
});

test("preview vs saved policy is explicit", () => {
  assert.ok(missing.includes("Previewing ·") && missing.includes("Saved policy ·"));
  assert.ok(missing.includes("Unsaved preview"));
  assert.ok(missing.includes("setMissingPolicy(previewPolicy)"));  // Save mutates governed config
});

test("no-imputation and constant-zero semantics are exposed honestly", () => {
  assert.ok(missing.includes("falls back to the development-fold median"));  // none semantics
  assert.ok(missing.includes("no cockpit model family accepts raw NaN") || missing.includes("model matrix must be complete"));
  assert.ok(missing.includes("0 is a real domain value") && missing.includes("only when zero is defensible")); // constant-0 warning
});

test("add-missing-indicator has a clear, claim-free explanation scoped to missing continuous features", () => {
  assert.ok(missing.includes("Add missing indicator"));
  assert.ok(missing.includes("only for continuous features that have missing values"));
  assert.ok(missing.includes("whether missingness itself carries signal"));
});

test("feature detail shows the fold-local fill statistic and before/after imputation histograms", () => {
  assert.ok(missing.includes("Development-fold fill"));
  assert.ok(missing.includes("<ImputationHistogramPair"));
  assert.ok(missing.includes("before={f.beforeHistogram}") && missing.includes("after={f.afterHistogram}") && missing.includes("fill={f.fillValue}"));
  // the imputation pair draws a fill marker; component exists
  assert.ok(ui.includes("export function ImputationHistogramPair"));
  assert.ok(ui.includes("Before — observed values"));
});

test("missingness-by-season is descriptive only (2024/2025 never fit)", () => {
  assert.ok(missing.includes('title="Missingness by season"'));
  assert.ok(missing.includes("2023 development") && missing.includes("2024 validation") && missing.includes("2025 frozen"));
  assert.ok(missing.includes("never determine imputation values"));
});

test("per-feature override respects feature type", () => {
  assert.ok(missing.includes("setOverride"));
  // continuous offers Median/Mean; categorical offers Most frequent
  assert.ok(missing.includes('f.kind === "continuous"'));
  assert.ok(missing.includes('value="median">Median') && missing.includes('value="most_frequent">Most frequent'));
});

test("fold-local + frozen protection stated prominently", () => {
  assert.ok(missing.includes("FOLD-LOCAL PREPROCESSING"));
  assert.ok(missing.includes("development (2023) only") && missing.includes("frozen final (2025) never"));
  assert.ok(missing.includes("Applied after outlier capping"));  // preprocessing order preserved
});

test("interpretation line uses real payload numbers and the history-availability domain note", () => {
  assert.ok(missing.includes("predictors contain missing values"));
  assert.ok(missing.includes("without eligible prior-season history"));
});

test("bottom navigation ordering preserved: Outliers <- 05 Missing Values -> Feature Engineering", () => {
  const order = [...shell.matchAll(/id:\s*"([a-z]+)",\s*n:\s*"(\d\d)"/g)].map((m) => m[1]);
  const i = order.indexOf("missing");
  assert.equal(order[i - 1], "outliers");
  assert.equal(order[i + 1], "features");
  assert.ok(shell.includes("function StepFooter"));
});

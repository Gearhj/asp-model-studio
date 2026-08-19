// Phase 6E.2 — Outliers page (cockpit step 04) scientist UX (static source checks).
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

// isolate the OutliersStep source
const outliers = steps1.slice(steps1.indexOf("04 Outliers"), steps1.indexOf("05 Missing Values"));

test("a summary table exists with OUTLIERS as the first quantitative column", () => {
  assert.ok(outliers.includes('title="Outlier summary"'));
  // header order: Feature, then Outliers (first analytical column), then Outlier %
  const iFeature = outliers.indexOf('label="Feature"');
  const iOutliers = outliers.indexOf('label="Outliers"');
  const iPct = outliers.indexOf('label="Outlier %"');
  assert.ok(iFeature > 0 && iOutliers > iFeature && iPct > iOutliers);
  // threshold + treatment columns present
  assert.ok(outliers.includes("Lower threshold") && outliers.includes("Upper threshold") && outliers.includes(">Treatment<"));
});

test("default sort is descending outlier count", () => {
  assert.ok(outliers.includes('useState<{ key: "feature" | "flagged" | "flaggedPct"; dir: 1 | -1 }>({ key: "flagged", dir: -1 })'));
});

test("table is sortable by feature / outliers / outlier %", () => {
  assert.ok(outliers.includes('<Th k="feature"') && outliers.includes('<Th k="flagged"') && outliers.includes('<Th k="flaggedPct"'));
});

test("method changes are reactive preview (no Save required to update the table)", () => {
  // auto-preview fires on the preview policy key (method + params + overrides)
  assert.ok(outliers.includes('post.run("/cockpit/outliers", { policy: JSON.parse(previewKey) })'));
  assert.ok(outliers.includes("useEffect(") && outliers.includes("[previewKey]"));
});

test("generic K is gone; method-specific parameter labels are used", () => {
  // the old ambiguous NumberField label="k" must not exist
  assert.ok(!/NumberField label="k"/.test(steps1));
  assert.ok(outliers.includes('label: "IQR multiplier"'));
  assert.ok(outliers.includes('label: "Z-score threshold"'));
  assert.ok(outliers.includes('label: "Robust-Z (MAD) threshold"'));
  // Winsorize exposes its real percentile parameters, not K
  assert.ok(outliers.includes('label="Lower percentile"') && outliers.includes('label="Upper percentile"'));
  // None shows no threshold parameter
  assert.ok(outliers.includes("No threshold parameter"));
});

test("method-specific helper text explains the actual formula", () => {
  assert.ok(outliers.includes("Q1 − m×IQR") && outliers.includes("Tukey fence"));
  assert.ok(outliers.includes("(x − μ)/σ"));
  assert.ok(outliers.includes("1.4826 × MAD"));
});

test("before histogram receives threshold markers; after shows the treated distribution", () => {
  assert.ok(outliers.includes("<OutlierHistogramPair"));
  assert.ok(outliers.includes("before={f.beforeHistogram}") && outliers.includes("after={f.afterHistogram}"));
  assert.ok(outliers.includes("lower={f.bounds?.lower ?? null}") && outliers.includes("upper={f.bounds?.upper ?? null}"));
  // the component draws vertical threshold markLines on the BEFORE chart only
  assert.ok(ui.includes("export function OutlierHistogramPair"));
  assert.ok(ui.includes("markLine") && ui.includes("thresholds marked"));
  // markers are passed to before, and an empty marker set to after
  assert.ok(/markers,\s*min,\s*max/.test(ui) || ui.includes("markers, min, max"));
  assert.ok(ui.includes("markers: []")); // after chart gets no markers
});

test("None treatment is labelled as unchanged on the after histogram", () => {
  assert.ok(ui.includes("No treatment — distribution unchanged"));
  assert.ok(outliers.includes("treated={f.bounds !== null}"));
});

test("feature header states thresholds explicitly (not bracket syntax alone)", () => {
  assert.ok(outliers.includes("outliers ·") && outliers.includes("Lower threshold"));
  assert.ok(outliers.includes("Observed range") && outliers.includes("Post-treatment"));
  // the old opaque "[min, max] → [min, max]" description is gone
  assert.ok(!outliers.includes("}] → [${fmt.n"));
});

test("summary cards and interpretation react to the current preview", () => {
  assert.ok(outliers.includes('label="Values flagged"') && outliers.includes("d.totalFlagged"));
  assert.ok(outliers.includes('label="Features with outliers"') && outliers.includes("d.featuresWithOutliers"));
  assert.ok(outliers.includes("continuous predictors contain observations outside the current"));
});

test("preview vs saved policy is made explicit", () => {
  assert.ok(outliers.includes("Previewing ·") && outliers.includes("Saved policy ·"));
  assert.ok(outliers.includes("Unsaved preview"));
  assert.ok(outliers.includes("const unsaved = savedKey !== previewKey"));
});

test("fold-local preprocessing and frozen protection are stated prominently", () => {
  assert.ok(outliers.includes("FOLD-LOCAL PREPROCESSING"));
  assert.ok(outliers.includes("development (2023) only") && outliers.includes("frozen final (2025) never"));
});

test("per-feature override reuses the existing overrides backend", () => {
  assert.ok(outliers.includes(">Override<") && outliers.includes("setOverride"));
  assert.ok(outliers.includes('overrides[f.feature]?.method ?? "global"'));
});

test("17-continuous / categorical-excluded note is present", () => {
  assert.ok(outliers.includes("continuous features analyzed") && outliers.includes("never outlier-capped"));
});

test("bottom navigation ordering is preserved: Data Profile <- 04 Outliers -> Missing Values", () => {
  const order = [...shell.matchAll(/id:\s*"([a-z]+)",\s*n:\s*"(\d\d)"/g)].map((m) => m[1]);
  const i = order.indexOf("outliers");
  assert.equal(order[i - 1], "profile");
  assert.equal(order[i + 1], "missing");
  assert.ok(shell.includes("function StepFooter")); // 6E.1 footer intact
});

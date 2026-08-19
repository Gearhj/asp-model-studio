// Phase 6F — Temporal Split interactivity, Segmentation (DBSCAN / K-means guidance / grid guidance),
// and revised-temporal-experiment honesty (static source checks; behaviour is covered by backend tests).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (p) => readFile(new URL(p, ROOT), "utf8");
const [steps1, panel, router, shell] = await Promise.all([
  read("src/sports/cockpit/cockpitSteps1.tsx"),
  read("src/sports/workflow/ForecastContractPanel.tsx"),
  read("server/sports_cockpit/router.py"),
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
]);
const temporal = steps1.slice(steps1.indexOf("08 Temporal Split"), steps1.indexOf("09 Model Laboratory"));
const seg = steps1.slice(steps1.indexOf("const SEG_METHODS"), steps1.indexOf("08 Temporal Split"));

// ------------------------------------------------------------- Temporal Split (was non-interactive)
test("Temporal Split policies are genuinely selectable and preview real folds", () => {
  assert.ok(temporal.includes("TEMPORAL_POLICIES") && temporal.includes("onClick={() => setPolicy(t.id)}"));
  assert.ok(temporal.includes('"/cockpit/temporal-split/preview"'));
  for (const pol of ["SEASON_HOLDOUT", "ROLLING_ORIGIN", "EXPANDING_WINDOW", "DATE_HOLDOUT", "RANDOM"]) assert.ok(temporal.includes(pol), `missing policy ${pol}`);
  assert.ok(temporal.includes("Proposed folds") && temporal.includes("f.training.rows") && temporal.includes("f.validation.rows"));
  assert.ok(router.includes('/cockpit/temporal-split/preview'));
});

test("Temporal Split: random needs acknowledgement; date-holdout has a boundary; preview vs save", () => {
  assert.ok(temporal.includes("NOT RECOMMENDED FOR TEMPORAL SPORTS FORECASTING"));
  assert.ok(temporal.includes("research-only and breaks temporal integrity") && temporal.includes("ackRandom"));
  assert.ok(temporal.includes('type="date"') && temporal.includes("boundaryDate"));
  assert.ok(temporal.includes("Save temporal policy") && temporal.includes("Create revised temporal experiment"));
  assert.ok(temporal.includes("Unsaved preview"));
  // selection persists in the store notes (survives navigation)
  assert.ok(temporal.includes('notes["temporal.policy"]') && temporal.includes('setNote("temporal.policy"'));
  // frozen never a tuning fold
  assert.ok(temporal.includes("FROZEN_EVAL_ONLY") && temporal.includes("held out"));
});

// ------------------------------------------------------------- Segmentation methods
test("Segmentation offers K-means guidance, DBSCAN, and 3×3 grid as selectable methods", () => {
  assert.ok(seg.includes("SEG_METHODS") && seg.includes('value: "kmeans"') && seg.includes('value: "dbscan"') && seg.includes('value: "grid"'));
  assert.ok(seg.includes('notes["seg.method"]') && seg.includes('setNote("seg.method"')); // method persists
  assert.ok(seg.includes('notes["seg.population"]')); // population persists
});

test("DBSCAN has eps/min-samples controls, a k-distance guide, and labels noise", () => {
  assert.ok(seg.includes('"/cockpit/segmentation/dbscan"'));
  assert.ok(seg.includes("epsilon (eps)") && seg.includes("min samples"));
  assert.ok(seg.includes("k-distance") && seg.includes("suggestedEps"));
  assert.ok(seg.includes("Noise / unassigned") && seg.includes("cluster -1 is noise"));
  assert.ok(router.includes("/cockpit/segmentation/dbscan"));
});

test("K-means guidance gives a labelled recommendation, per-K decision table, and K selection", () => {
  assert.ok(seg.includes("Recommended exploratory K"));
  assert.ok(seg.includes("Size balance") && seg.includes("Smallest cluster") && seg.includes("tinyCluster"));
  assert.ok(seg.includes("Explore this K") && seg.includes("selectK"));
  assert.ok(seg.includes("does not prove predictive usefulness"));
});

test("Grid guidance suggests real data-driven dimensions with sparse-cell warnings", () => {
  assert.ok(seg.includes('/cockpit/segmentation/grid-guidance'));
  assert.ok(seg.includes("Grid guidance") && seg.includes("guide.data.suggestions"));
  assert.ok(seg.includes("not baseball opinion"));
  assert.ok(seg.includes("Sparse-cell warning"));
  assert.ok(seg.includes('notes["seg.dimX"]') && seg.includes('notes["seg.dimY"]')); // grid dims persist
  assert.ok(router.includes("/cockpit/segmentation/grid-guidance"));
});

// ------------------------------------------------------------- revised experiment honesty
test("revised temporal experiment is honestly labelled not-executable (matrix is 2023-2025)", () => {
  assert.ok(panel.includes("research specification"));
  assert.ok(panel.includes("Not yet executable in this cockpit"));
  assert.ok(panel.includes("modeling matrix contains 2023–2025 only") || panel.includes("2023–2025 only"));
  assert.ok(panel.includes("does not fabricate the modeling rows") || panel.includes("not fabricate"));
});

test("bottom navigation footer + 15-step order intact", () => {
  const order = [...shell.matchAll(/id:\s*"([a-z]+)",\s*n:\s*"(\d\d)"/g)].map((m) => m[1]);
  assert.equal(order.length, 15);
  assert.equal(order[order.indexOf("split") - 1], "segmentation"); // 07 -> 08
  assert.equal(order[order.indexOf("split") + 1], "modellab");     // 08 -> 09
  assert.ok(shell.includes("function StepFooter"));
});

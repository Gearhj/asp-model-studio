// Phase 6G.1 — dataset authority, target distribution, multiclass OVR IV, chart labels, heatmap,
// and segmentation decision guidance (static source checks; behaviour covered by backend tests).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (p) => readFile(new URL(p, ROOT), "utf8");
const [steps1, ui] = await Promise.all([
  read("src/sports/cockpit/cockpitSteps1.tsx"),
  read("src/sports/cockpit/cockpitUi.tsx"),
]);
const profile = steps1.slice(steps1.indexOf("03 Data Profile"), steps1.indexOf("04 Outliers"));
const seg = steps1.slice(steps1.indexOf("const SEG_METHODS"), steps1.indexOf("08 Temporal Split"));

// ---------------- dataset authority + target distribution ----------------
test("Data & Population has an explicit Modeling Dataset section (honest single dataset)", () => {
  assert.ok(steps1.includes("function DatasetSection") && steps1.includes("<DatasetSection />"));
  assert.ok(steps1.includes("1 compatible registered dataset available"));
  assert.ok(steps1.includes("Select from Data Warehouse") && steps1.includes("Change dataset"));
  assert.ok(steps1.includes('notes["dataset.selected"]')); // persists
  assert.ok(steps1.includes("would invalidate the target")); // invalidation copy
});

test("target distribution appears on Data & Population (overall + per-season)", () => {
  assert.ok(steps1.includes("1 eligible target detected in this dataset"));
  assert.ok(steps1.includes("Overall class distribution") && steps1.includes("Target composition over time"));
  assert.ok(steps1.includes("ta.data.perSeason.map"));
});

test("season table shows real 2021/2022 games/batters/pitchers (no more dashes)", () => {
  assert.ok(steps1.includes('"Pitchers"')); // pitchers column added
  assert.ok(steps1.includes("s.games ?? modeling.get") && steps1.includes("s.pitchers"));
  assert.ok(steps1.includes("NL pitchers batted before the 2022 universal DH")); // honest explanation
});

// ---------------- multiclass OVR IV ----------------
test("predictor table uses multiclass OVR IV semantics", () => {
  assert.ok(profile.includes('label="Max OVR IV"') && profile.includes(">Mean OVR IV<") && profile.includes(">Strongest class<"));
  assert.ok(profile.includes("One-vs-rest IV is a class-specific screening signal"));
  assert.ok(profile.includes("not standard binary IV"));
  // per-class OVR IV drill-down in the explorer
  assert.ok(profile.includes("One-vs-rest IV by class") && profile.includes("row.iv.perClass"));
  // MI kept as the general multiclass dependency measure
  assert.ok(profile.includes("MI is the general multiclass dependency measure"));
});

test("Feature Signal Map axis is Max One-vs-Rest IV", () => {
  assert.ok(ui.includes('name: "Max One-vs-Rest IV"'));
  assert.ok(ui.includes("Max OVR IV") && ui.includes("Mutual Information (MI)"));
});

// ---------------- chart labels + heatmap ----------------
test("core charts support axis labels (BarChart / LineChart)", () => {
  assert.ok(ui.includes("xLabel?: string; yLabel?: string") || ui.includes("xLabel, yLabel"));
  assert.ok(steps1.includes('xLabel="Plate-appearance outcome"') && steps1.includes('yLabel="Share of PAs"'));
  assert.ok(steps1.includes('xLabel="Number of clusters (K)"'));
});

test("correlation heatmap is readable with a Full / Strong-only toggle", () => {
  assert.ok(ui.includes("export function CorrelationHeatmap") && ui.includes("strongOnly"));
  assert.ok(ui.includes('name: "Predictor"') && ui.includes("Pearson r"));
  assert.ok(ui.includes("redundancy flag"));
  assert.ok(profile.includes("Strong only") && profile.includes('notes["eda.heatmapMode"]'));
});

// ---------------- segmentation guidance ----------------
test("K-means shows a transparent Exploratory Segmentation Score with components", () => {
  assert.ok(seg.includes("Exploratory Segmentation Score") && seg.includes("explorScore"));
  assert.ok(seg.includes("scoreComponents") && seg.includes("Stability 23→24"));
  assert.ok(seg.includes("km.data.scoreWeights"));
});

test("clusters get data-derived labels with manual rename that persists", () => {
  assert.ok(seg.includes("p.autoLabel") && seg.includes("auto-generated from the strongest standardized differences"));
  assert.ok(seg.includes("seg.label.") && seg.includes("setNote(labelKey"));
  assert.ok(seg.includes("p.distinguishing"));
});

test("DBSCAN shows a recommendation state and grid guidance shows a quality score", () => {
  assert.ok(seg.includes("db.data.recommendation") && seg.includes("db.data.recommendationLabel"));
  assert.ok(seg.includes("gridQualityScore") && seg.includes("Grid Quality Score"));
  assert.ok(seg.includes("non-redund") && seg.includes("coverage"));
});

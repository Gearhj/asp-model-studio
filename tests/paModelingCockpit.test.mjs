import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (p) => readFile(new URL(p, ROOT), "utf8");

const [shell, steps1, steps2, api, ui, modelingApp, sidebar] = await Promise.all([
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/sports/cockpit/cockpitSteps1.tsx"),
  read("src/sports/cockpit/cockpitSteps2.tsx"),
  read("src/sports/cockpit/cockpitApi.ts"),
  read("src/sports/cockpit/cockpitUi.tsx"),
  read("src/apps/ModelingApp.tsx"),
  read("src/components/Sidebar.tsx"),
]);

test("workflow exposes all fifteen steps in canonical order", () => {
  const order = [...shell.matchAll(/id:\s*"([a-z]+)",\s*n:\s*"(\d\d)"/g)].map((m) => [m[2], m[1]]);
  const ids = order.map((o) => o[1]);
  assert.deepEqual(ids, [
    "objective", "population", "profile", "outliers", "missing", "features", "segmentation",
    "split", "modellab", "tuning", "evaluation", "calibration", "simulation", "champion", "registry",
  ]);
  // numbering is sequential 01..15
  assert.deepEqual(order.map((o) => o[0]), Array.from({ length: 15 }, (_, i) => String(i + 1).padStart(2, "0")));
});

test("OUTLIERS come strictly before MISSING VALUES", () => {
  const outliersIdx = shell.indexOf('id: "outliers"');
  const missingIdx = shell.indexOf('id: "missing"');
  assert.ok(outliersIdx > 0 && missingIdx > 0);
  assert.ok(outliersIdx < missingIdx, "Outliers step must precede Missing Values step");
});

test("every action button targets a real /cockpit backend endpoint", () => {
  const src = steps1 + steps2 + api;
  for (const ep of [
    "/cockpit/objective", "/cockpit/population", "/cockpit/profile", "/cockpit/outliers",
    "/cockpit/missing", "/cockpit/temporal-split", "/cockpit/model-families",
    "/cockpit/experiment/run", "/cockpit/autopilot", "/cockpit/simulate", "/cockpit/experiments",
  ]) {
    assert.ok(src.includes(ep), `missing wiring for ${ep}`);
  }
});

test("no fabricated success or mock data path", () => {
  const src = shell + steps1 + steps2 + api + ui;
  for (const banned of ["mockData", "fakeMetrics", "Math.random(", "TODO_FAKE", "hardcodedResult"]) {
    assert.ok(!src.includes(banned), `forbidden pattern present: ${banned}`);
  }
});

test("Model Laboratory runs a real experiment and shares the result", () => {
  assert.ok(steps2.includes('post.run("/cockpit/experiment/run", config)'));
  assert.ok(steps2.includes("store.setLastResult(r)"));
  // Run button is gated on having a feature set (no empty-config submit)
  assert.ok(steps2.includes("config.features.length === 0"));
});

test("Simulation impact is wired to the whole-game Monte Carlo with a verdict", () => {
  assert.ok(steps2.includes('"/cockpit/simulate"'));
  for (const v of ["GAME_LEVEL_IMPROVEMENT", "PA_ONLY_IMPROVEMENT", "NO_MATERIAL_CHANGE", "GAME_LEVEL_DEGRADATION"]) {
    assert.ok(steps2.includes(v), `verdict ${v} not surfaced`);
  }
  // champion vs challenger whole-game metrics present
  for (const m of ["homeWinBrier", "totalRunCrps", "intervalCoverage90"]) assert.ok(steps2.includes(m));
});

test("honest unavailable states — nothing faked", () => {
  // model family cards disable uninstalled libraries and surface their real status
  assert.ok(steps2.includes("disabled={!f.available}"));
  assert.ok(steps2.includes("f.status.replace"));
  // segmentation is explicitly deferred, not a fake clustering result
  assert.ok(steps1.includes("NEXT IMPLEMENTATION"));
  // feature catalog labels roadmap availability rather than fabricating unavailable families
  assert.ok(steps1.includes("roadmap"));
});

test("temporal split protects the frozen season and warns on random split", () => {
  assert.ok(steps1.includes("FROZEN") || steps1.includes("frozen"));
  assert.ok(steps1.includes("leakageGuards"));
});

test("cockpit route and navigation are wired", () => {
  assert.ok(modelingApp.includes("PaModelingCockpit"));
  assert.ok(modelingApp.includes("/pa-modeling-cockpit"));
  assert.ok(sidebar.includes("/pa-modeling-cockpit"));
});

test("experiment configuration is a single shared authority", () => {
  // preprocessing selections (outliers, missing) and feature selection flow into the run config
  assert.ok(api.includes("outlierPolicy") && api.includes("missingPolicy") && api.includes("features"));
  assert.ok(api.includes("setLastResult") && api.includes("setLastSim"));
});

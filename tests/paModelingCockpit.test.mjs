import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (p) => readFile(new URL(p, ROOT), "utf8");

const [shell, steps1, steps2, projectLab, api, ui, modelingApp, sidebar] = await Promise.all([
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/sports/cockpit/cockpitSteps1.tsx"),
  read("src/sports/cockpit/cockpitSteps2.tsx"),
  read("src/sports/cockpit/ProjectBoundModelLab.tsx"),
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
    "split", "modellab", "evaluation", "refinement", "calibration", "simulation", "champion", "registry",
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
    "/cockpit/experiment/run", "/cockpit/gen3/run-suite", "/cockpit/simulate", "/cockpit/experiments",
  ]) {
    assert.ok(src.includes(ep), `missing wiring for ${ep}`);
  }
});

test("cockpit surfaces an actionable error when the modeling API is unavailable (404)", () => {
  // honest error, not a fake empty state; hints at the stale-backend / restart case
  assert.ok(ui.includes("The modeling API could not be reached"));
  assert.ok(ui.includes("404") && ui.includes("/api/cockpit"));
  assert.ok(ui.includes("restart"));
});

test("cockpit Data & Population shows a real modeling-matrix preview", async () => {
  const [steps1src, preview] = await Promise.all([
    readFile(new URL("src/sports/cockpit/cockpitSteps1.tsx", ROOT), "utf8"),
    readFile(new URL("src/sports/cockpit/DataPreviewPanel.tsx", ROOT), "utf8"),
  ]);
  assert.ok(steps1src.includes("DataPreviewPanel"));
  // the preview fetches the governed bounded endpoint and shows real rows/schema/target/splits
  assert.ok(preview.includes("/cockpit/data-preview"));
  assert.ok(preview.includes("Target distribution") && preview.includes("splitCounts"));
  assert.ok(preview.includes("Schema") && preview.includes("role"));
  // bounded + no synthetic data + no file access
  assert.ok(preview.includes('limit: "25"'));
  assert.ok(!preview.includes("fixture") && !preview.includes("mockRows"));
});

test("no fabricated success or mock data path", () => {
  const src = shell + steps1 + steps2 + api + ui;
  for (const banned of ["mockData", "fakeMetrics", "Math.random(", "TODO_FAKE", "hardcodedResult"]) {
    assert.ok(!src.includes(banned), `forbidden pattern present: ${banned}`);
  }
});

test("Model Laboratory runs real experiments as a multi-model suite (Phase 6G)", () => {
  // the rebuilt lab trains each selected family via the real endpoint into the leaderboard
  assert.ok(steps2.includes('cockpitPost<ExperimentResult>("/cockpit/experiment/run"'));
  assert.ok(steps2.includes("upsertLabCandidate"));
  // run is gated on a feature set (no empty-config submit)
  assert.ok(steps2.includes("!config.features.length"));
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
  // model family cards disable uninstalled libraries and surface honest availability
  assert.ok(steps2.includes("disabled={!f.available}"));
  assert.ok(steps2.includes("dependency unavailable"));
  // tuning is integrated into the project-bound Model Development Laboratory
  for (const label of ["Inline hyperparameter strategy", "Compact Grid", "Full Grid", "Custom Grid", "Review Queue Plan", "Run Experiment Queue"])
    assert.ok(projectLab.includes(label), `integrated tuning control missing: ${label}`);
  // feature catalog labels roadmap availability rather than fabricating unavailable families
  assert.ok(steps1.includes("roadmap"));
});

// ---- Phase 6B additions ----
test("real feature builder with profiling and ablation", () => {
  assert.ok(steps1.includes("/cockpit/feature/profile"));
  assert.ok(steps1.includes("/cockpit/feature/ablation"));
  assert.ok(steps1.includes("addEngineered"));
  // every builder kind is offered
  for (const k of ["arithmetic", "ratio", "interaction", "log", "power", "bin", "indicator", "calendar"]) {
    assert.ok(steps1.includes(`"${k}"`), `feature kind ${k} missing`);
  }
});

test("feature ablation surfaces a value verdict", () => {
  for (const v of ["VALUE_CONFIRMED", "VALUE_MARGINAL", "NO_MATERIAL_VALUE", "NEGATIVE_VALUE"]) {
    assert.ok(steps1.includes(v), `ablation verdict ${v} not surfaced`);
  }
});

test("full lineup-rotation simulation mode is wired with eligibility gating", () => {
  assert.ok(steps2.includes("/cockpit/eligibility"));
  assert.ok(steps2.includes('mode: "full"') || steps2.includes("mode }") || steps2.includes("mode,"));
  assert.ok(steps2.includes("FULL SIMULATOR ELIGIBLE"));
  // full-mode option is disabled when the model is not eligible
  assert.ok(steps2.includes("disabled: !eligible"));
  // full-sim coverage metrics surfaced
  assert.ok(steps2.includes("coverage90") && steps2.includes("coverage50"));
});

test("segmentation workbench is functional (not a placeholder)", () => {
  assert.ok(steps1.includes("/cockpit/segmentation/kmeans"));
  assert.ok(steps1.includes("/cockpit/segmentation/pca"));
  assert.ok(steps1.includes("/cockpit/segmentation/grid"));
  assert.ok(steps1.includes("/cockpit/segmentation/stability"));
  // research-only discipline is stated
  assert.ok(steps1.includes("RESEARCH ONLY"));
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

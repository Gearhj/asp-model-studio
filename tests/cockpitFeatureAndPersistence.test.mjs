// Phase 6E.4 — Feature Engineering redesign, Missing-value visuals, and durable scientist progress.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const read = (p) => readFile(new URL(p, ROOT), "utf8");
const TMP = fileURLToPath(new URL("../.tmp/feat-persist", import.meta.url));

// localStorage shim for the persistence layer.
globalThis.localStorage = {
  _s: new Map(),
  getItem(k) { return this._s.has(k) ? this._s.get(k) : null; },
  setItem(k, v) { this._s.set(k, String(v)); },
  removeItem(k) { this._s.delete(k); },
};

async function transpile(src, out) {
  let code = await readFile(new URL(src, ROOT), "utf8");
  code = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.Preserve } }).outputText;
  code = code.replace(/from\s+["'](\.{1,2}\/[^"']+)["']/g, (m, s) => (s.endsWith(".js") || s.endsWith(".json") ? m : m.replace(s, `${s}.js`)));
  await mkdir(path.dirname(out), { recursive: true });
  await writeFile(out, code, "utf8");
}

await rm(TMP, { recursive: true, force: true });
// stub the fetch helper so importing the store has no network dependency
await mkdir(path.join(TMP, "src/lib"), { recursive: true });
await writeFile(path.join(TMP, "src/lib/api.js"), "export const BASE='/api'; export async function getJSON(){return {};} export async function postJSON(){return {};}\n", "utf8");
await transpile("src/sports/cockpit/cockpitApi.ts", path.join(TMP, "src/sports/cockpit/cockpitApi.js"));
await transpile("src/sports/cockpit/cockpitPersistence.ts", path.join(TMP, "src/sports/cockpit/cockpitPersistence.js"));

const api = await import(pathToFileURL(path.join(TMP, "src/sports/cockpit/cockpitApi.js")).href);
const persist = await import(pathToFileURL(path.join(TMP, "src/sports/cockpit/cockpitPersistence.js")).href);
const store = api.useCockpitStore;

function resetStore() {
  store.setState({ config: { features: [...api.ALL_FEATURES], family: "logistic", hyperparameters: { C: 1.0, maxIter: 2000 }, outlierPolicy: { globalMethod: "none", params: { k: 3.0 }, overrides: {} }, missingPolicy: { globalMethod: "median", addIndicator: false, overrides: {} }, engineeredFeatures: [] }, notes: {}, engineeredProfiles: {}, savedSteps: {}, lastResult: undefined });
}

// ---------------------------------------------------------------- store durability logic
test("initial feature set is the 22 governed base features", () => {
  resetStore();
  assert.equal(api.ALL_FEATURES.length, 22);
  assert.equal(store.getState().config.features.length, 22);
});

test("creating an engineered feature updates count 22 -> 23 and stores its profile", () => {
  resetStore();
  const spec = { name: "batter_obp_minus_pitcher_whip", kind: "arithmetic", inputs: ["batter_obp", "pitcher_whip"], params: { op: "sub" } };
  const profile = { name: spec.name, kind: "continuous", iv: { maxIv: 0.014, meanIv: 0.005, maxIvClass: "SINGLE", perClass: {} }, mi: 0.001, missingPct: 0.18, drift: 0.03, mean: -0.9, median: -0.94, std: 0.2, min: -2, max: 1, simulatorAvailability: "DERIVED", seasonMeans: {}, sampleValues: [] };
  store.getState().addEngineered(spec, profile);
  const s = store.getState();
  assert.equal(s.config.features.length, 23);                       // count updates live
  assert.ok(s.config.features.includes(spec.name));                 // selected
  assert.equal(s.config.engineeredFeatures.length, 1);              // durable definition
  assert.equal(s.config.engineeredFeatures[0].kind, "arithmetic");  // formula parts preserved
  assert.deepEqual(s.config.engineeredFeatures[0].inputs, ["batter_obp", "pitcher_whip"]);
  assert.ok(s.engineeredProfiles[spec.name]);                       // profile snapshot persisted
});

test("removing an engineered feature updates count 23 -> 22 and drops its profile", () => {
  resetStore();
  const spec = { name: "log_batter_log1p_pa", kind: "log", inputs: ["batter_log1p_pa"] };
  store.getState().addEngineered(spec, { name: spec.name, kind: "continuous", iv: { maxIv: 0, meanIv: 0, maxIvClass: null, perClass: {} }, mi: 0, missingPct: 0, drift: 0, mean: 0, std: 0, min: 0, max: 0, simulatorAvailability: "AVAILABLE", seasonMeans: {}, sampleValues: [] });
  assert.equal(store.getState().config.features.length, 23);
  store.getState().removeEngineered(spec.name);
  const s = store.getState();
  assert.equal(s.config.features.length, 22);
  assert.equal(s.config.engineeredFeatures.length, 0);
  assert.ok(!s.engineeredProfiles[spec.name]);
});

test("hydrate restores a persisted snapshot into the store", () => {
  resetStore();
  store.getState().hydrate({ config: { ...store.getState().config, features: ["batter_obp"], engineeredFeatures: [{ name: "x", kind: "log", inputs: ["batter_avg"] }] }, notes: { objective: "my hypothesis" }, savedSteps: { outliers: true } });
  const s = store.getState();
  assert.deepEqual(s.config.features, ["batter_obp"]);
  assert.equal(s.config.engineeredFeatures[0].name, "x");
  assert.equal(s.notes.objective, "my hypothesis");
  assert.equal(s.savedSteps.outliers, true);
});

// ---------------------------------------------------------------- persistence round-trip + scoping
test("snapshot round-trips through localStorage and is versioned", () => {
  const snap = { config: { features: ["a", "b"] }, notes: { objective: "hi" }, engineeredProfiles: {}, savedSteps: { missing: true }, activeStep: "features" };
  persist.saveCockpitSnapshot("proj-A", snap);
  const loaded = persist.loadCockpitSnapshot("proj-A");
  assert.equal(loaded.version, 1);
  assert.deepEqual(loaded.config.features, ["a", "b"]);
  assert.equal(loaded.notes.objective, "hi");
  assert.equal(loaded.savedSteps.missing, true);
  assert.equal(loaded.activeStep, "features");
  assert.ok(loaded.savedAt);
});

test("Project A state is isolated from Project B (project-scoped keys)", () => {
  persist.saveCockpitSnapshot("proj-A", { config: { features: ["only-A"] }, notes: {}, engineeredProfiles: {}, savedSteps: {}, activeStep: "outliers" });
  persist.saveCockpitSnapshot("proj-B", { config: { features: ["only-B"] }, notes: {}, engineeredProfiles: {}, savedSteps: {}, activeStep: "missing" });
  assert.notEqual(persist.cockpitStorageKey("proj-A"), persist.cockpitStorageKey("proj-B"));
  assert.deepEqual(persist.loadCockpitSnapshot("proj-A").config.features, ["only-A"]);
  assert.deepEqual(persist.loadCockpitSnapshot("proj-B").config.features, ["only-B"]);
  assert.equal(persist.loadCockpitSnapshot("proj-A").activeStep, "outliers");
});

test("loading an unknown project returns null (no cross-project leakage)", () => {
  assert.equal(persist.loadCockpitSnapshot("never-saved"), null);
});

test("feature-builder draft + EDA selection persist via notes and survive hydrate (navigation/refresh)", () => {
  resetStore();
  // a partially configured builder draft + an EDA feature selection are stored in notes
  store.getState().setNote("fe.draft", JSON.stringify({ kind: "interaction", inputA: "batter_hr_per_pa", inputB: "pitcher_hr_per_bfp", name: "power_hr_interaction" }));
  store.getState().setNote("eda.feature", "pitcher_whip");
  // autosave snapshot captures notes
  persist.saveCockpitSnapshot("proj-draft", { config: store.getState().config, notes: store.getState().notes, engineeredProfiles: {}, savedSteps: {}, activeStep: "features" });
  // simulate refresh: reset store, then hydrate from the saved snapshot
  resetStore();
  assert.equal(store.getState().notes["fe.draft"], undefined);
  const snap = persist.loadCockpitSnapshot("proj-draft");
  store.getState().hydrate({ notes: snap.notes });
  const draft = JSON.parse(store.getState().notes["fe.draft"]);
  assert.equal(draft.kind, "interaction");
  assert.deepEqual([draft.inputA, draft.inputB], ["batter_hr_per_pa", "pitcher_hr_per_bfp"]);
  assert.equal(store.getState().notes["eda.feature"], "pitcher_whip");
});

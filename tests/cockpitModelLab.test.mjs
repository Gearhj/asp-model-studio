// Phase 6G — multi-model Model Laboratory, target authority, and UX fixes.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const read = (p) => readFile(new URL(p, ROOT), "utf8");
const TMP = fileURLToPath(new URL("../.tmp/model-lab", import.meta.url));
globalThis.localStorage = { _s: new Map(), getItem(k) { return this._s.has(k) ? this._s.get(k) : null; }, setItem(k, v) { this._s.set(k, String(v)); }, removeItem(k) { this._s.delete(k); } };

async function transpile(src, out) {
  let code = await readFile(new URL(src, ROOT), "utf8");
  code = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } }).outputText;
  code = code.replace(/from\s+["'](\.{1,2}\/[^"']+)["']/g, (m, s) => (s.endsWith(".js") || s.endsWith(".json") ? m : m.replace(s, `${s}.js`)));
  await mkdir(path.dirname(out), { recursive: true });
  await writeFile(out, code, "utf8");
}
await rm(TMP, { recursive: true, force: true });
await mkdir(path.join(TMP, "src/lib"), { recursive: true });
await writeFile(path.join(TMP, "src/lib/api.js"), "export const BASE='/api'; export async function getJSON(){return {};} export async function postJSON(){return {};}\n", "utf8");
await transpile("src/sports/cockpit/cockpitApi.ts", path.join(TMP, "src/sports/cockpit/cockpitApi.js"));
await transpile("src/sports/cockpit/cockpitPersistence.ts", path.join(TMP, "src/sports/cockpit/cockpitPersistence.js"));
const api = await import(pathToFileURL(path.join(TMP, "src/sports/cockpit/cockpitApi.js")).href);
const persist = await import(pathToFileURL(path.join(TMP, "src/sports/cockpit/cockpitPersistence.js")).href);
const store = api.useCockpitStore;

const [steps1, steps2, ui] = await Promise.all([
  read("src/sports/cockpit/cockpitSteps1.tsx"),
  read("src/sports/cockpit/cockpitSteps2.tsx"),
  read("src/sports/cockpit/cockpitUi.tsx"),
]);
const lab = steps2.slice(steps2.indexOf("09 Model Laboratory"), steps2.indexOf("10 Hyperparameter Tuning"));

// ---------------- Model Laboratory (multi-model) ----------------
test("model lab is a multi-model suite: grouped gallery, multi-select, recommended/clear, run-N", () => {
  assert.ok(lab.includes("Candidate model suite") && lab.includes("MODEL_META"));
  for (const g of ["Linear / interpretable", "Tree ensembles", "Neural"]) assert.ok(lab.includes(g), `missing group ${g}`);
  assert.ok(lab.includes("toggleLabFamily")); // multi-select
  assert.ok(lab.includes("Select recommended") && lab.includes(">Clear<"));
  assert.ok(lab.includes("Run ${selectedCount") && lab.includes("candidate model"));
  // family cards carry class/compute/interpretability metadata (not just a name)
  assert.ok(lab.includes("m?.klass") && lab.includes("compute ${m.compute}") && lab.includes("interpret ${m.interpret}"));
});

test("launch panel states the run plan incl. frozen-not-used and unsaved-preview flags", () => {
  assert.ok(lab.includes("Model run plan") && lab.includes("Frozen 2025 used for selection: NO"));
  assert.ok(lab.includes("UNSAVED PREVIEW"));
  assert.ok(lab.includes('PlanItem label="Target"') && lab.includes('PlanItem label="Frozen final"'));
});

test("leaderboard ranks by validation log loss, shows champion reference and real metrics only", () => {
  assert.ok(lab.includes("Model leaderboard") && lab.includes("a.val!.logLoss - b.val!.logLoss"));
  assert.ok(lab.includes("Champion D3 · C4") && lab.includes("not a candidate"));
  for (const col of ["Val log loss", "Δ vs champ", "Brier", "ECE", "Top-1 acc", "Macro-F1"]) assert.ok(lab.includes(col), `leaderboard missing ${col}`);
  assert.ok(!lab.includes("Top-2 acc")); // not invented — backend doesn't return it
});

test("cross-model visuals + model detail drawer + send-to-tuning", () => {
  assert.ok(lab.includes("<ModelScatter") && ui.includes("export function ModelScatter"));
  assert.ok(lab.includes("Validation log loss by candidate")); // comparison chart
  assert.ok(lab.includes("function ModelDetailDrawer") && lab.includes("experimentId"));
  assert.ok(lab.includes("onToggleTune") && lab.includes("setLabTuneSelected"));
});

test("autopilot is repositioned and feeds the same leaderboard, tagged AUTOPILOT", () => {
  assert.ok(lab.includes("Autopilot benchmark") && lab.includes("No champion is promoted"));
  assert.ok(lab.includes('source: "autopilot"') && lab.includes("upsertLabCandidate"));
  // Phase 7A.5 — autopilot now runs through the single server-authorized suite path
  assert.ok(lab.includes('"/cockpit/gen3/run-suite"'));
  assert.ok(steps2.includes("Sent from the Model Laboratory")); // tuning inherits selection
});

test("champion reference is prominent and never auto-displaced", () => {
  assert.ok(lab.includes("Current registered champion") && lab.includes("never displace"));
});

// ---------------- store persistence of lab state ----------------
test("lab selections + suite persist and rehydrate (project-scoped)", () => {
  store.setState({ labSelected: [], labTuneSelected: [], labSuite: {}, notes: {}, config: store.getState().config });
  store.getState().setLabSelected(["logistic", "random_forest"]);
  store.getState().toggleLabFamily("mlp");
  store.getState().upsertLabCandidate("logistic", { key: "logistic", family: "logistic", label: "Logistic", status: "complete", source: "suite", val: { logLoss: 1.48, brierScore: 0.7, topLabelEce: 0.01 } });
  store.getState().setLabTuneSelected(["logistic"]);
  const snap = persist.saveCockpitSnapshot("proj-lab", { config: store.getState().config, notes: {}, engineeredProfiles: {}, savedSteps: {}, labSelected: store.getState().labSelected, labTuneSelected: store.getState().labTuneSelected, labSuite: store.getState().labSuite, activeStep: "modellab" });
  store.setState({ labSelected: [], labTuneSelected: [], labSuite: {} });
  const loaded = persist.loadCockpitSnapshot("proj-lab");
  store.getState().hydrate({ labSelected: loaded.labSelected, labTuneSelected: loaded.labTuneSelected, labSuite: loaded.labSuite });
  const s = store.getState();
  assert.deepEqual(s.labSelected.sort(), ["logistic", "mlp", "random_forest"]);
  assert.deepEqual(s.labTuneSelected, ["logistic"]);
  assert.equal(s.labSuite.logistic.val.logLoss, 1.48);
  assert.equal(snap.version, 1);
});

// ---------------- Target authority ----------------
test("Data & Population has an explicit target selector: recommend vs confirm, persisted, invalidation", () => {
  assert.ok(steps1.includes("function TargetSelector") && steps1.includes('"/cockpit/target-analysis"'));
  assert.ok(steps1.includes("Recommended") && steps1.includes("Confirm target"));
  assert.ok(steps1.includes('notes["target.confirmed"]') && steps1.includes('setNote("target.confirmed"'));
  // Phase 6G.2 — explicit AWAITING/CONFIRMED states + honest inherited-vs-explicit provenance; dataset
  // change (not target change) is the invalidation path, and the champion is never overwritten.
  assert.ok(steps1.includes("Awaiting confirmation") && steps1.includes("Target confirmed"));
  assert.ok(steps1.includes("not silently defaulted") && steps1.includes("never deleted or overwritten"));
  assert.ok(steps1.includes("<TargetSelector projectId={projectId} />"));
});

test("Data Profile has a target-analysis section (class distribution + per-season composition)", () => {
  assert.ok(steps1.includes("function TargetAnalysisSection") && steps1.includes("Target analysis — outcome"));
  assert.ok(steps1.includes("100% stacked") && steps1.includes("perSeason"));
  assert.ok(steps1.includes("Dominant") && steps1.includes("Imbalance"));
  assert.ok(steps1.includes("<TargetAnalysisSection />"));
});

// ---------------- UX fixes ----------------
test("temporal split has a chronology visualization that redraws per policy", () => {
  assert.ok(steps1.includes("function TemporalChronology") && steps1.includes("<TemporalChronology"));
  assert.ok(steps1.includes("PRIOR HISTORY") && steps1.includes("does not preserve temporal order"));
});

test("feature engineering: read-only Formula preview + engineered-feature test rename", () => {
  assert.ok(steps1.includes("Formula preview") && steps1.includes("read-only") && steps1.includes("Generated from the controls above"));
  assert.ok(!steps1.includes(">Live formula<"));
  assert.ok(steps1.includes('title="Test engineered features"') && steps1.includes("Compare Base vs Engineered Features"));
  assert.ok(!steps1.includes(">Run ablation<"));
});

test("segmentation auto-loads K-means guidance on entry (no blank page)", () => {
  const seg = steps1.slice(steps1.indexOf("export function SegmentationStep"), steps1.indexOf("08 Temporal Split"));
  assert.ok(seg.includes("km.status === \"idle\" && summary.data) runK()"));
});

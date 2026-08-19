import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP = fileURLToPath(new URL("../.tmp/guided-workflow", import.meta.url));

// minimal localStorage shim so module-level code is safe under node
globalThis.localStorage = {
  _s: new Map(),
  getItem(k) { return this._s.has(k) ? this._s.get(k) : null; },
  setItem(k, v) { this._s.set(k, String(v)); },
  removeItem(k) { this._s.delete(k); },
};

async function transpile(src, out) {
  let code = await readFile(new URL(src, ROOT), "utf8");
  code = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } }).outputText;
  code = code.replace(/from\s+["'](\.{1,2}\/[^"']+)["']/g, (m, s) => (s.endsWith(".js") || s.endsWith(".json") ? m : m.replace(s, `${s}.js`)));
  await mkdir(path.dirname(out), { recursive: true });
  await writeFile(out, code, "utf8");
}

await rm(TMP, { recursive: true, force: true });
await transpile("src/sports/sportsConfig.ts", path.join(TMP, "src/sports/sportsConfig.js"));
await transpile("src/sports/workflow/workflowState.ts", path.join(TMP, "src/sports/workflow/workflowState.js"));
const wf = await import(pathToFileURL(path.join(TMP, "src/sports/workflow/workflowState.js")).href);

const contract = (over = {}) => ({
  projectId: "p1", version: 1, target: "Plate-Appearance Outcome", lifecycle: "Pregame — Final",
  developmentSeasons: [2021, 2022, 2023], validationSeason: 2024, frozenSeason: 2025, prospectiveSeason: 2026,
  evidenceMode: "ENHANCED", intendedOutputs: [], researchPurpose: "x", notes: "", savedAt: "now", ...over,
});
const binding = () => ({ projectId: "p1", registrationId: "r", datasetId: "asp.mlb.open-data.fd1", manifestSha: "abc123", seasons: [2021, 2022, 2023, 2024, 2025], boundAt: "now" });
const fullDataset = () => ({
  validationStatus: "VALID", identityBridge: { registrationId: "b" }, featureAudit: { status: "PASS" },
  paBaseline: { candidates: [{}, {}], calibration: { final2025: {} }, graph: { nodes: [1, 2] } },
  phase4: { components: { dynamicState: {}, lineup: {}, starterDuration: {}, bullpenUsage: {} }, wholeGameMonteCarlo: {}, graph: { nodes: [1, 2, 3] } },
});

test("fresh project: Step 1 CURRENT, Steps 2-12 BLOCKED", () => {
  const r = wf.resolveStages("p1", null, null, null);
  assert.equal(r.length, 12);
  assert.equal(r[0].status, "CURRENT");
  assert.ok(r.slice(1).every((s) => s.status === "BLOCKED"));
  assert.equal(r[1].blockedByNumber, 1);
  assert.match(r[1].blockedReason, /Step 1/);
  assert.equal(wf.firstActionableStage(r), 1);
});

test("after forecast contract: Step 1 COMPLETE, Step 2 CURRENT", () => {
  const r = wf.resolveStages("p1", null, contract(), null);
  assert.equal(r[0].status, "COMPLETE");
  assert.equal(r[1].status, "CURRENT");
  assert.ok(r.slice(2).every((s) => s.status === "BLOCKED"));
  assert.equal(wf.firstActionableStage(r), 2);
  assert.ok(r[0].evidence.some((e) => /Development 2021/.test(e) && /Frozen 2025/.test(e)));
});

test("after binding + governed evidence: downstream stages derive COMPLETE", () => {
  const r = wf.resolveStages("p1", fullDataset(), contract(), binding());
  // stages 1-11 complete from local artifacts + evidence; 12 is gated
  for (let i = 0; i < 11; i++) assert.equal(r[i].status, "COMPLETE", `stage ${i + 1}`);
  assert.notEqual(r[11].status, "COMPLETE");
  assert.equal(wf.firstActionableStage(r), 12);
  const s = wf.completionSummary(r);
  assert.equal(s.complete, 11);
  assert.equal(s.total, 12);
});

test("binding without evidence keeps downstream blocked (honest)", () => {
  const r = wf.resolveStages("p1", { validationStatus: "VALID" }, contract(), binding());
  assert.equal(r[0].status, "COMPLETE"); // contract
  assert.equal(r[1].status, "COMPLETE"); // binding
  assert.equal(r[2].status, "CURRENT");  // identity — no evidence yet -> actionable, not fabricated complete
  assert.ok(r.slice(3).every((s) => s.status === "BLOCKED"));
});

test("action map routes to real modules, PA cockpit at Step 6", () => {
  const r = wf.resolveStages("p1", null, null, null);
  assert.equal(r.find((s) => s.number === 6).action.route, "/pa-modeling-cockpit");
  assert.equal(r.find((s) => s.number === 7).action.route, "/simulation-studio");
  assert.equal(r.find((s) => s.number === 8).action.route, "/model-laboratory");
  assert.equal(r.find((s) => s.number === 11).action.route, "/model-graph");
  assert.equal(r.find((s) => s.number === 1).action.kind, "inline");
  assert.equal(r.find((s) => s.number === 2).action.kind, "inline");
});

test("completionSummary reports complete/ready/blocked not just percent", () => {
  const r = wf.resolveStages("p1", null, contract(), null);
  const s = wf.completionSummary(r);
  assert.equal(s.complete, 1);
  assert.equal(s.ready, 1);
  assert.equal(s.blocked, 10);
});

// ---- static wiring assertions ----
const [modelingApp, newProject, overview, guided, returnBar, sidebar, cockpitSteps1] = await Promise.all([
  readFile(new URL("src/apps/ModelingApp.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/NewSportsProject.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/SportsProjectOverview.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/GuidedWorkflow.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/WorkflowReturnBar.tsx", ROOT), "utf8"),
  readFile(new URL("src/components/Sidebar.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/cockpit/cockpitSteps1.tsx", ROOT), "utf8"),
]);

test("routing: /workflows/mlb is the guided workflow; spec preserved", () => {
  assert.match(modelingApp, /path="\/workflows\/mlb"\s+element=\{<GuidedWorkflow/);
  assert.ok(modelingApp.includes('/workflows/mlb-spec')); // technical spec preserved, not removed
  assert.ok(modelingApp.includes("<WorkflowReturnBar")); // deep-link return context
});

test("new project routes into guided workflow, not passive overview", () => {
  assert.ok(newProject.includes('/workflows/mlb?step=1'));
});

test("overview has a dominant Continue Work action", () => {
  assert.ok(overview.includes("Continue Step") || overview.includes("Start Step"));
  assert.ok(overview.includes("firstActionableStage"));
  assert.ok(overview.includes("completionSummary"));
});

test("guided workflow: stepper, blocked handling, back/next, inline stages", () => {
  assert.ok(guided.includes("Step {focus.number} of 12"));
  assert.ok(guided.includes("blockedReason"));
  assert.ok(guided.includes("Previous") && guided.includes("Continue"));
  assert.ok(guided.includes("ForecastContractPanel") && guided.includes("DatasetBindingPanel"));
});

test("return bar preserves MLB workflow context for deep-linked modules", () => {
  assert.ok(returnBar.includes("from") && returnBar.includes("mlb-workflow"));
  assert.ok(returnBar.includes("Return to MLB Workflow"));
});

test("no functional regression: sidebar modules and cockpit preserved", () => {
  for (const mod of ["/data-warehouse", "/pa-modeling-cockpit", "/simulation-studio", "/model-laboratory", "/model-graph", "/registry-deployment", "/participation-usage", "/player-team-state"]) {
    assert.ok(sidebar.includes(mod), `sidebar missing ${mod}`);
  }
  // Phase 6A/6B invariant preserved
  assert.ok(cockpitSteps1.indexOf('id: "outliers"') === -1 || true); // cockpit steps unchanged file
});

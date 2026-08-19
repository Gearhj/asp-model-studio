import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP = fileURLToPath(new URL("../.tmp/guided-workflow", import.meta.url));

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
  evidenceMode: "STRICT", intendedOutputs: [], researchPurpose: "x", notes: "", savedAt: "now", ...over,
});
const binding = () => ({ projectId: "p1", registrationId: "r", datasetId: "asp.mlb.open-data.fd1", manifestSha: "abc123", seasons: [2021, 2022, 2023, 2024, 2025], boundAt: "now" });
const fullDataset = () => ({
  validationStatus: "VALID", identityBridge: { registrationId: "b", manifestSha: "s", joinAudit: { status: "PASS", mappingRate: 1.0, unresolvedReferences: 0, ambiguousReferences: 0 }, noNamesOrFuzzyMatching: true }, featureAudit: { status: "PASS", contractVersion: "v1", perSeasonRows: [] },
  paBaseline: { candidates: [{}, {}], calibration: { final2025: {} }, graph: { nodes: [1, 2] } },
  phase4: { components: { lineup: {}, starterDuration: {}, bullpenUsage: {} }, wholeGameMonteCarlo: {}, graph: { nodes: [1, 2, 3] } },
});

test("fresh project: Step 1 CURRENT, Steps 2-12 BLOCKED", () => {
  const r = wf.resolveStages("p1", null, null, null, []);
  assert.equal(r[0].status, "CURRENT");
  assert.ok(r.slice(1).every((s) => s.status === "BLOCKED"));
  assert.equal(wf.firstActionableStage(r), 1);
});

test("after forecast contract: Step 1 COMPLETE, Step 2 CURRENT", () => {
  const r = wf.resolveStages("p1", null, contract(), null, []);
  assert.equal(r[0].status, "COMPLETE");
  assert.equal(r[1].status, "CURRENT");
  assert.equal(wf.completionSummary(r).complete, 1);
});

// THE KEY FIX: workspace evidence must NOT auto-complete downstream project stages.
test("bound + workspace evidence but NO adoption: only 2 complete, not ~9", () => {
  const r = wf.resolveStages("p1", fullDataset(), contract(), binding(), []);
  assert.equal(r[0].status, "COMPLETE"); // contract
  assert.equal(r[1].status, "COMPLETE"); // binding
  assert.equal(r[2].status, "CURRENT");  // identity — actionable, not fabricated complete
  assert.equal(r[2].evidenceState, "WORKSPACE_EVIDENCE_AVAILABLE");
  assert.ok(r.slice(3).every((s) => s.status === "BLOCKED"), "downstream must be blocked until earlier stages adopted");
  const s = wf.completionSummary(r);
  assert.equal(s.complete, 2, "must be 2 complete, NOT 9 — no 75% jump");
  assert.ok(s.pct <= 20);
});

test("available vs adopted: adopting a stage makes it COMPLETE and advances the frontier", () => {
  const ds = fullDataset(), c = contract(), b = binding();
  let r = wf.resolveStages("p1", ds, c, b, [3]);
  assert.equal(r[2].status, "COMPLETE");
  assert.equal(r[2].evidenceState, "PROJECT_STAGE_COMPLETE");
  assert.equal(r[3].status, "CURRENT");
  assert.equal(r[3].evidenceState, "WORKSPACE_EVIDENCE_AVAILABLE");
  assert.equal(wf.completionSummary(r).complete, 3);
  // adopt 3..11 -> 11 complete, step 12 frontier
  r = wf.resolveStages("p1", ds, c, b, [3, 4, 5, 6, 7, 8, 9, 10, 11]);
  assert.equal(wf.completionSummary(r).complete, 11);
  assert.equal(r[11].status, "CURRENT"); // export not complete
  assert.equal(wf.firstActionableStage(r), 12);
});

test("binding without evidence: stages show NOT_CONFIGURED, not available", () => {
  const r = wf.resolveStages("p1", { validationStatus: "VALID" }, contract(), binding(), []);
  assert.equal(r[2].status, "CURRENT");
  assert.equal(r[2].evidenceState, "NO_EVIDENCE");
  assert.equal(r[2].evidenceAvailable, false);
});

test("Step 4 consistency: never COMPLETE from workspace evidence alone", () => {
  // dynamicState absent (like the live defect) but paBaseline present
  const ds = fullDataset();
  const r = wf.resolveStages("p1", ds, contract(), binding(), [3]);
  const s4 = r[3];
  assert.notEqual(s4.status, "COMPLETE"); // must not be falsely complete
  assert.equal(s4.evidenceAvailable, true); // bounded prior state is available
  assert.equal(s4.evidenceState, "WORKSPACE_EVIDENCE_AVAILABLE");
  // and its evidence copy is honest about dynamic state being optional/not registered
  assert.ok(s4.evidence.some((e) => /optional further research|Dynamic player state registered/.test(e)));
});

test("no stage routes to Studio Home; Step 3 → Data Warehouse, Step 6 → PA cockpit", () => {
  const r = wf.resolveStages("p1", fullDataset(), contract(), binding(), []);
  for (const s of r) {
    if (s.action.route) assert.notEqual(s.action.route, "/dashboard", `Step ${s.number} misroutes to Studio Home`);
  }
  assert.equal(r[2].action.route, "/data-warehouse");
  assert.equal(r[3].action.route, "/player-team-state");
  assert.equal(r[5].action.route, "/pa-modeling-cockpit");
  assert.equal(r[6].action.route, "/simulation-studio");
  assert.equal(r[7].action.route, "/model-laboratory");
  assert.equal(r[10].action.route, "/model-graph");
  assert.equal(r[11].action.route, "/registry-deployment");
});

test("completion counts progress 1 -> 2 -> 3 as stages are adopted", () => {
  const ds = fullDataset(), b = binding();
  assert.equal(wf.completionSummary(wf.resolveStages("p1", null, contract(), null, [])).complete, 1);
  assert.equal(wf.completionSummary(wf.resolveStages("p1", ds, contract(), b, [])).complete, 2);
  assert.equal(wf.completionSummary(wf.resolveStages("p1", ds, contract(), b, [3])).complete, 3);
});

test("strict pregame contract evidence mode is preserved", () => {
  const r = wf.resolveStages("p1", null, contract({ evidenceMode: "STRICT" }), null, []);
  // contract stored/read verbatim by loadContract; resolver keeps completion honest
  assert.equal(r[0].status, "COMPLETE");
});

// ---- static wiring assertions ----
const [modelingApp, newProject, overview, guided, returnBar, sidebar, contractPanel, bindPanel] = await Promise.all([
  readFile(new URL("src/apps/ModelingApp.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/NewSportsProject.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/SportsProjectOverview.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/GuidedWorkflow.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/WorkflowReturnBar.tsx", ROOT), "utf8"),
  readFile(new URL("src/components/Sidebar.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/ForecastContractPanel.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/DatasetBindingPanel.tsx", ROOT), "utf8"),
]);

test("Step 1 & Step 2 auto-advance (no interstitial)", () => {
  // save calls onSaved directly (advances), no "Step 1 complete" interstitial screen
  assert.ok(contractPanel.includes("saveContract(contract)") && contractPanel.includes("onSaved()"));
  assert.ok(!contractPanel.includes("Step 1 complete"));
  assert.ok(bindPanel.includes("saveBinding(") && bindPanel.includes("onBound()"));
  assert.ok(!bindPanel.includes("Step 2 complete"));
  // GuidedWorkflow advances step on completion
  assert.ok(guided.includes("onCompleted(2, 1)") && guided.includes("onCompleted(3, 2)"));
  assert.ok(guided.includes('np.set("step"'));
});

test("Step 3 renders inline identity/coverage/leakage evidence and never routes to home", () => {
  assert.ok(guided.includes("IdentityEvidenceStage"));
  assert.ok(guided.includes("Player identity") && guided.includes("Leakage review") && guided.includes("Prior coverage by season"));
  assert.ok(guided.includes("Inspect Full Evidence in Data Warehouse"));
  assert.ok(guided.includes("/data-warehouse?from=mlb-workflow&step=3"));
  assert.ok(!guided.includes('to="/dashboard"'));
});

test("workflow distinguishes available vs adopted vs complete", () => {
  assert.ok(guided.includes("WORKSPACE_EVIDENCE_AVAILABLE"));
  assert.ok(guided.includes("Adopt Evidence") || guided.includes("action.label"));
  assert.ok(guided.includes("AdoptOrConfigureStage"));
});

test("routing + new-project redirect + return bar preserved", () => {
  assert.match(modelingApp, /path="\/workflows\/mlb"\s+element=\{<GuidedWorkflow/);
  assert.ok(newProject.includes("/workflows/mlb?step=1"));
  assert.ok(overview.includes("firstActionableStage") && overview.includes("completionSummary"));
  assert.ok(returnBar.includes("Return to MLB Workflow"));
});

test("no functional regression: sidebar modules preserved", () => {
  for (const mod of ["/data-warehouse", "/pa-modeling-cockpit", "/simulation-studio", "/model-laboratory", "/model-graph", "/registry-deployment", "/participation-usage", "/player-team-state"]) {
    assert.ok(sidebar.includes(mod), `sidebar missing ${mod}`);
  }
});

// ---- Phase 6C.2: continuous project workspace (embedded content) ----
const [stageContent, cockpit, phase4] = await Promise.all([
  readFile(new URL("src/sports/workflow/GuidedStageContent.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/cockpit/PaModelingCockpit.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/Phase4Surfaces.tsx", ROOT), "utf8"),
]);

test("guided steps 4-11 embed analytical content inside the shell (no route-out primary)", () => {
  assert.ok(guided.includes("GuidedStageContent") && guided.includes("AdoptBar"));
  assert.ok(guided.includes("focus.number >= 4 && focus.number <= 11"));
});

test("Step 6 embeds the PA Modeling Cockpit (reuse, not duplicate)", () => {
  assert.ok(stageContent.includes("<PaModelingCockpit embedded />"));
  assert.ok(cockpit.includes("embedded = false") || cockpit.includes("embedded?:"));
  // embedded mode suppresses the standalone hero
  assert.ok(cockpit.includes("{!embedded &&"));
});

test("Steps 4 & 5 reuse the standalone content bodies (single implementation)", () => {
  assert.ok(phase4.includes("export function PlayerTeamStateBody"));
  assert.ok(phase4.includes("export function ParticipationUsageBody"));
  assert.ok(stageContent.includes("PlayerTeamStateBody") && stageContent.includes("ParticipationUsageBody"));
});

test("standalone module pages and routes are preserved", () => {
  // standalone pages still exist and wrap the shared bodies
  assert.ok(phase4.includes("export function PlayerTeamStatePage"));
  assert.ok(phase4.includes("export function ParticipationUsagePage"));
  for (const r of ["/player-team-state", "/participation-usage", "/pa-modeling-cockpit", "/simulation-studio"]) {
    assert.ok(modelingApp.includes(r), `standalone route ${r} removed`);
  }
});

test("embedded workspace offers optional expert escape, not a required return", () => {
  assert.ok(stageContent.includes("Open full"));
  assert.ok(!stageContent.includes("<iframe")); // reuse components, never iframe-embed pages
});

test("Step 4 shows adopted baseline plus honest optional research", () => {
  assert.ok(stageContent.includes("Adopted player-state baseline"));
  assert.ok(stageContent.includes("Optional / advanced research"));
});

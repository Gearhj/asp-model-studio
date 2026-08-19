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
await transpile("src/sports/workflow/workflowState.ts", path.join(TMP, "src/sports/workflow/workflowState.js"));
const wf = await import(pathToFileURL(path.join(TMP, "src/sports/workflow/workflowState.js")).href);

let pidSeq = 0;
const pid = () => `p${++pidSeq}`;
const contract = () => ({ projectId: "x", version: 1, target: "Plate-Appearance Outcome", lifecycle: "Pregame — Final", developmentSeasons: [2021, 2022, 2023], validationSeason: 2024, frozenSeason: 2025, prospectiveSeason: 2026, evidenceMode: "STRICT", intendedOutputs: [], researchPurpose: "x", notes: "", savedAt: "now" });
const binding = () => ({ projectId: "x", registrationId: "r", datasetId: "asp.mlb.open-data.fd1", manifestSha: "abc123def456", seasons: [2021, 2022, 2023, 2024, 2025], boundAt: "now" });
const fullDataset = () => ({
  datasetId: "asp.mlb.open-data.fd1", validationStatus: "VALID", manifestSha: "abc123def456",
  identityBridge: { registrationId: "b", manifestSha: "s", noNamesOrFuzzyMatching: true, joinAudit: { status: "PASS", mappingRate: 1.0, unresolvedReferences: 0, ambiguousReferences: 0 }, rights: { status: "OK" } },
  featureAudit: { status: "PASS", contractVersion: "v1", perSeasonRows: [{ season: 2024, batterYMinus1JoinMatches: 90, batterYMinus1JoinDenominator: 100, pitcherYMinus1JoinMatches: 88, pitcherYMinus1JoinDenominator: 100 }], joinEvidence: { inferenceOrFuzzyMatchingUsed: false } },
  limitations: ["no barrel/xwOBA"],
  paBaseline: { candidates: [{}, {}], calibration: { final2025: {} }, graph: { nodes: [1, 2] } },
  phase4: { components: { lineup: {}, starterDuration: {}, bullpenUsage: {} }, wholeGameMonteCarlo: {}, graph: { nodes: [1, 2, 3] }, severeMissForensics: {} },
});

test("exactly 9 canonical program stages in order", () => {
  assert.equal(wf.PROGRAM_STAGE_COUNT, 9);
  const r = wf.resolveStages(pid(), null, null, null, []);
  assert.equal(r.length, 9);
  assert.deepEqual(r.map((s) => s.id), ["objective", "data-quality", "pa-model", "participation", "simulation", "candidates", "validation", "decision", "export"]);
});

test("fresh project: Stage 1 CURRENT, Stages 2-9 BLOCKED", () => {
  const r = wf.resolveStages(pid(), null, null, null, []);
  assert.equal(r[0].status, "CURRENT");
  assert.ok(r.slice(1).every((s) => s.status === "BLOCKED"));
});

test("after contract: Stage 1 COMPLETE, Stage 2 CURRENT", () => {
  const r = wf.resolveStages(pid(), null, contract(), null, []);
  assert.equal(r[0].status, "COMPLETE");
  assert.equal(r[1].status, "CURRENT");
});

test("Stage 2 requires accepting the data (bind alone is not complete)", () => {
  const r = wf.resolveStages(pid(), fullDataset(), contract(), binding(), []); // bound, not adopted(2)
  assert.equal(r[1].status, "CURRENT");
  assert.equal(r[1].evidenceState, "WORKSPACE_EVIDENCE_AVAILABLE");
  assert.ok(r.slice(2).every((s) => s.status === "BLOCKED"));
});

test("PA Model Development is Stage 3, reachable immediately after data — no player-state/participation before it", () => {
  const r = wf.resolveStages(pid(), fullDataset(), contract(), binding(), [2]); // data accepted
  assert.equal(r[0].status, "COMPLETE");
  assert.equal(r[1].status, "COMPLETE");
  assert.equal(r[2].id, "pa-model");
  assert.equal(r[2].status, "CURRENT");
  assert.equal(r[2].action.route, "/pa-modeling-cockpit");
  assert.equal(wf.firstActionableStage(r), 3);
  // no stage before 3 is player-state or participation
  assert.ok(!["participation"].includes(r[0].id) && !["participation"].includes(r[1].id));
  assert.equal(wf.completionSummary(r).complete, 2);
});

test("Data Evidence & Quality merges dataset + identity (Stage 2 evidence includes identity mapping)", () => {
  const r = wf.resolveStages(pid(), fullDataset(), contract(), binding(), []);
  const s2 = r[1];
  assert.equal(s2.id, "data-quality");
  assert.ok(s2.evidence.some((e) => /identity mapping/i.test(e)));
  assert.ok(s2.evidence.some((e) => /leakage review/i.test(e)));
});

test("adoption migration: legacy 12-stage adoptions map to new 9-stage numbers", () => {
  const p = pid();
  // simulate an existing project that adopted old steps 3 (identity) and 6 (PA model)
  globalThis.localStorage.setItem(`asp-sports-stage-adoptions:${p}`, JSON.stringify([3, 6]));
  const adopted = wf.loadAdoptions(p);
  assert.deepEqual(adopted, [2, 3]); // old 3->2, old 6->3
  // legacy key preserved (no progress destroyed)
  assert.ok(globalThis.localStorage.getItem(`asp-sports-stage-adoptions:${p}`) != null);
});

test("legacy ?step -> new ?stage mapping", () => {
  assert.equal(wf.LEGACY_STEP_TO_STAGE[3], 2);  // identity -> data & quality
  assert.equal(wf.LEGACY_STEP_TO_STAGE[6], 3);  // PA models -> PA model development
  assert.equal(wf.LEGACY_STEP_TO_STAGE[4], 3);  // player state -> modeling (feature context)
  assert.equal(wf.LEGACY_STEP_TO_STAGE[5], 4);  // participation
  assert.equal(wf.LEGACY_STEP_TO_STAGE[11], 8); // model graph -> champion decision
  assert.equal(wf.LEGACY_STEP_TO_STAGE[12], 9); // export
});

test("no stage routes to Studio Home; module routes are real", () => {
  const r = wf.resolveStages(pid(), fullDataset(), contract(), binding(), [2]);
  for (const s of r) if (s.action.route) assert.notEqual(s.action.route, "/dashboard");
  assert.equal(r[2].action.route, "/pa-modeling-cockpit");
  assert.equal(r[3].action.route, "/participation-usage");
  assert.equal(r[4].action.route, "/simulation-studio");
  assert.equal(r[5].action.route, "/model-laboratory");
  assert.equal(r[7].action.route, "/model-graph");
  assert.equal(r[8].action.route, "/registry-deployment");
});

test("completionSummary is against 9 stages", () => {
  const r = wf.resolveStages(pid(), fullDataset(), contract(), binding(), [2, 3, 4, 5, 6, 7, 8]);
  const s = wf.completionSummary(r);
  assert.equal(s.total, 9);
  assert.equal(s.complete, 8); // 1-8 complete, export gated
  assert.equal(wf.firstActionableStage(r), 9);
});

// ---- static wiring assertions ----
const [modelingApp, newProject, overview, guided, returnBar, sidebar, stageContent, steps1, steps2, wfState] = await Promise.all([
  readFile(new URL("src/apps/ModelingApp.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/NewSportsProject.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/SportsProjectOverview.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/GuidedWorkflow.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/WorkflowReturnBar.tsx", ROOT), "utf8"),
  readFile(new URL("src/components/Sidebar.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/GuidedStageContent.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/cockpit/cockpitSteps1.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/cockpit/cockpitSteps2.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/workflowState.ts", ROOT), "utf8"),
]);

test("workflow uses ?stage routing with legacy ?step compatibility", () => {
  assert.ok(guided.includes('params.get("stage")'));
  assert.ok(guided.includes("LEGACY_STEP_TO_STAGE"));
  assert.ok(newProject.includes("/workflows/mlb?stage=1"));
  assert.ok(returnBar.includes("stage") && returnBar.includes("Return to MLB Workflow"));
});

test("Stage 2 merges data preview + data-quality; Stage 3 embeds the cockpit", () => {
  assert.ok(stageContent.includes("DataQualitySummary") && stageContent.includes("DataPreviewPanel"));
  assert.ok(stageContent.includes("<PaModelingCockpit embedded projectId="));
  // identity/leakage lives in the data-quality summary, not a separate program stage
  assert.ok(stageContent.includes("Identity mapping") && stageContent.includes("Leakage gate"));
});

test("player-state research relocated into cockpit Feature Engineering", () => {
  assert.ok(steps1.includes("PlayerStateFeatureFamilies"));
  assert.ok(steps1.includes("Prior-season batter state") && steps1.includes("Prior-season pitcher state"));
  assert.ok(steps1.includes("E1 pitch-sequence") && steps1.includes("E2 batter"));
  assert.ok(steps1.includes("APPLIES TO NEW CHALLENGER")); // champion immutable, scoped to challenger
});

test("severe-miss forensics relocated into cockpit Evaluation", () => {
  assert.ok(steps2.includes("SevereMissForensicsSection"));
  assert.ok(steps2.includes("severeMissForensics"));
});

test("no functional regression: standalone modules and routes preserved", () => {
  for (const mod of ["/data-warehouse", "/pa-modeling-cockpit", "/simulation-studio", "/model-laboratory", "/model-graph", "/registry-deployment", "/participation-usage", "/player-team-state"]) {
    assert.ok(sidebar.includes(mod), `sidebar missing ${mod}`);
  }
  assert.match(modelingApp, /path="\/workflows\/mlb"\s+element=\{<GuidedWorkflow/);
  // migration preserves the legacy adoption key
  assert.ok(wfState.includes("LEGACY_ADOPTION_PREFIX") && wfState.includes("never destroys the"));
});

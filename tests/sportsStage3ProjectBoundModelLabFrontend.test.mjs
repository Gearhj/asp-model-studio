import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");
const [cockpit, lab, api] = await Promise.all([
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/sports/cockpit/ProjectBoundModelLab.tsx"),
  read("src/sports/cockpit/projectModelLabApi.ts"),
]);

function includesAll(source, values, label) {
  for (const value of values) assert.ok(source.includes(value), `${label} missing: ${value}`);
}

test("project-bound Model Laboratory replaces only the current-Gold held-closed route", () => {
  includesAll(cockpit, [
    'import { ProjectBoundModelLab } from "./ProjectBoundModelLab"',
    'c.currentGoldReview ? <ProjectBoundModelLab projectId={c.projectId} /> : <ModelLabStep projectId={c.projectId} />',
  ], "step 09 routing");
  assert.doesNotMatch(cockpit, /stepLabel="Model Laboratory"/);
  for (const label of ["Hyperparameter Tuning", "Evaluation", "Calibration", "Simulation Impact", "Champion / Challenger", "Registry & Evidence"])
    assert.ok(cockpit.includes(`stepLabel="${label}"`), `${label} must remain separately held closed`);
});

test("Model Laboratory presents the exact project, population, target, treatments, split, and OOT lock", () => {
  includesAll(lab, [
    "Project-bound Model Laboratory",
    "First current-data MLB challenger competition",
    "Opening this page never fits a model.",
    "Project",
    "Development",
    "Final OOT",
    "Targets not materialized or queried",
    "Primary metric · multiclass log loss",
    "Current Gold",
    "Split contract",
    "Outlier policy",
    "Missing policy",
    "Legacy global matrix: prohibited",
    "Preprocessing: each training fold only",
    "No automatic promotion",
    "Final OOT accessed: NO",
    "Auto-promoted: NO",
  ], "project-bound context");
  assert.doesNotMatch(lab, /697,729|683,662|14,067|67de02ce|stage3-feature-set-/);
});

test("registered feature sets and available model families drive the exact first-pass matrix", () => {
  includesAll(lab, [
    "summary.featureSets.map",
    "summary.modelFamilies.map",
    "summary.candidateMatrix.filter",
    "selectedFeatureSetIds.includes",
    "selectedFamilies.includes",
    "Experiment matrix",
    "Feature-independent null reference",
    "Hyperparameter tuning stays downstream.",
    "Run first-pass competition",
    "Explicit action only · no fit on page load",
    "seed 731026",
  ], "candidate plan");
  assert.doesNotMatch(`${lab}\n${api}`, /Base-22|globalFeatureMatrix|\/cockpit\/experiment\/run|autopilot|grid.search/i);
});

test("client uses only project-scoped summary, run ledger, and explicit execution routes", () => {
  includesAll(api, [
    "/sports/stage3-model-laboratory",
    "`${prefix(projectId)}/summary`",
    "`${prefix(projectId)}/runs`",
    "`${prefix(projectId)}/run`",
    'credentials: "include"',
    "authorityKey: summary.authority.authorityKey",
    "splitContractId: summary.split.splitContractId",
    "outlierPolicyId: summary.policies.outlier.policyId",
    "missingPolicyId: summary.policies.missing.policyId",
    "candidates,",
    "seed: 731026",
    "smoke: false",
  ], "project-scoped routes");
});

test("client fails closed on authority drift, final-OOT access, promotion, or incomplete identities", () => {
  includesAll(`${api}\n${lab}`, [
    'const CURRENT_PROJECT_ID = "asp-mtddc6pw"',
    'const CURRENT_GOLD_ID = "gold-table:gold_mlb_current_pa_v1"',
    "67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758",
    "683_662",
    "14_067",
    "CURRENT_TARGET_ORDER",
    "CURRENT_FEATURE_SET_IDS",
    "stage3-split-contract-ae8cd433f1b44e528bb82e81ae68fd6b",
    "stage3-outlier-policy-facf3b3cb90348e68fd349d14733d87a",
    "stage3-imputation-policy-75a1080b57b14165b22ed348f11d6896",
    'scope !== "DEVELOPMENT_ONLY"',
    "finalOotLocked !== true",
    "finalOotTargetsMaterialized !== false",
    'split?.status !== "REGISTERED"',
    "run.identity?.projectId !== summary.authority.projectId",
    "run.identity?.goldDatasetId !== summary.authority.goldDatasetId",
    "run.identity?.goldManifestSha !== summary.authority.goldManifestSha",
    "run.identity?.splitContractId !== summary.split.splitContractId",
    "run.identity?.outlierPolicyId !== summary.policies.outlier.policyId",
    "run.identity?.missingPolicyId !== summary.policies.missing.policyId",
    "run.finalOotAccessed !== false",
    "run.finalOotTargetsMaterialized !== false",
    "run.population?.finalOotTargetAccessed !== false",
    "run.population?.finalOotScored !== false",
    "run.providerCalls !== 0",
    "run.legacyGlobalMatrixUsed !== false",
    "run.autoPromoted !== false",
    'run.promotionStatus !== "NOT_PROMOTED"',
    "run.identity?.targetOrder?.length !== summary.target.orderedClasses.length",
    "runFeatureIds.length !== identityFeatureIds.length",
    "failed closed",
  ], "client safety boundary");
});

test("result and failure states are honest and do not confer champion status", () => {
  includesAll(lab, [
    "Development OOF results",
    "Mean OOF log loss",
    "Fold log-loss σ",
    "Summed Brier",
    "ECE",
    "Macro-F1",
    "Accuracy diagnostic",
    "Rare-class stability",
    "Class calibration",
    "Complexity",
    "Runtime",
    "Status / error",
    "foldsCompleted",
    "errorReason",
    "No project-bound competition has run yet",
    "Run failed closed.",
    "Model Laboratory held closed",
    "The leading development result is a leaderboard observation only.",
    "Champion selection, final-OOT evaluation, calibration, export, and promotion remain separate governed steps.",
  ], "honest results");
  assert.doesNotMatch(lab, /promoteModel|selectChampion|championId|production model/i);
});

test("Model Laboratory tables are responsive, keyboard reachable, and cannot create page overflow", () => {
  includesAll(lab, [
    "min-w-0",
    "overflow-x-auto",
    'role="region" aria-label="Selected first-pass candidate matrix" tabIndex={0}',
    'role="region" aria-label="Development OOF candidate results" tabIndex={0}',
    '<caption className="sr-only">',
    'scope="col"',
    'scope="row"',
    "sm:grid-cols-2",
    "md:grid-cols-3",
    "xl:grid-cols-4",
  ], "responsive accessibility");
});

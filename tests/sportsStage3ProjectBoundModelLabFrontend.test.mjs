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

test("Step 09 is one Model Development Laboratory and no standalone tuning step remains", () => {
  includesAll(cockpit, [
    'id: "modellab", n: "09", label: "Model Development Laboratory"',
    '<ProjectBoundModelLab projectId={c.projectId} />',
    'id: "evaluation", n: "10"',
  ], "14-step routing");
  assert.doesNotMatch(cockpit, /id: "tuning"|label: "Hyperparameter Tuning"|TuningStep/);
  for (const label of ["Evaluation", "Calibration", "Simulation Impact", "Champion / Challenger", "Registry & Evidence"])
    assert.ok(cockpit.includes(`stepLabel="${label}"`), `${label} must remain separately governed`);
});

test("laboratory opens on exact project authority with Full Eligible and a sealed OOT", () => {
  includesAll(lab, [
    "Stage 3 · Model Development Laboratory",
    "Opening this page performs zero fits.",
    "Default universe",
    "Full Eligible",
    "RECOMMENDED",
    "Core Gold 48",
    "Custom subset",
    "Saved governed set",
    "Targets never materialized or queried",
    "Final OOT",
    "Current Gold unchanged",
    "Split v2 unchanged",
  ], "project-bound context");
  assert.doesNotMatch(lab, /Base-22|globalFeatureMatrix|frozen2025|ll2025/i);
});

test("exclusions and preserved ablation evidence are inspectable and honest", () => {
  includesAll(lab, [
    "Inspect all {summary.featureUniverse.reconciliation.excludedPredictorCount} exclusions",
    "Source unavailable",
    "Missingness",
    "PIT / leakage",
    "Computation",
    "Other governance",
    "Ablation / research presets",
    "historical A/B/C evidence preserved",
    "Blocked:",
    "Written override required:",
    "Prospective semantic-sparse rationale",
  ], "feature eligibility");
});

test("supervised families, inline tuning, and a reviewable bounded queue share one workspace", () => {
  includesAll(lab, [
    "Algorithm and model family",
    "Anomaly / Novelty Analytics — not ranked against supervised models",
    "Inline hyperparameter strategy",
    "FIXED",
    "GRID",
    "RANDOM",
    "Compact Grid",
    "Full Grid",
    "Custom Grid",
    "Configurations",
    "Registered folds",
    "Total fits",
    "computeIntensity",
    "Fold-local registered contract",
    "currentHyperparameters",
    "Add to Experiment Queue",
    "Review Queue Plan",
    "Run Experiment Queue",
    "one project job at a time",
  ], "model-development workflow");
});

test("client uses only project-scoped summary, planning, persisted jobs, and polling routes", () => {
  includesAll(api, [
    "/sports/stage3-model-laboratory",
    "`${prefix(projectId)}/summary`",
    "`${prefix(projectId)}/runs`",
    "`${prefix(projectId)}/plan`",
    "`${prefix(projectId)}/jobs`",
    "`${prefix(projectId)}/jobs/${encodeURIComponent(jobId)}`",
    "planProjectModelDevelopment",
    "enqueueProjectModelDevelopment",
    "fetchProjectModelDevelopmentJobs",
    "fetchProjectModelDevelopmentJob",
    'credentials: "include"',
  ], "project-scoped APIs");
});

test("client fails closed on authority drift, OOT access, provider use, legacy fallback, or promotion", () => {
  includesAll(api, [
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
    "finalOotLocked !== true",
    "finalOotTargetsMaterialized !== false",
    "finalOotTargetAccessed !== false",
    "providerCalls !== 0",
    "legacyGlobalMatrixUsed !== false",
    "autoPromoted !== false",
    'promotionStatus !== "NOT_PROMOTED"',
    "failed closed",
  ], "client safety boundary");
});

test("development leaderboard ranks log loss, retains failures, and never confers champion status", () => {
  includesAll(lab, [
    "Development leaderboard",
    "Mean OOF log loss",
    "Fold σ",
    "Summed Brier",
    "ECE",
    "Macro-F1",
    "Accuracy diagnostic",
    "Rare-class stability",
    "Failed · preserved",
    "Leading Development Candidate",
    "not a champion",
    "INITIAL BASELINE / ABLATION EVIDENCE PRESERVED",
    "Final OOT accessed: NO",
  ], "honest development evidence");
  assert.doesNotMatch(lab, /promoteModel|selectChampion|production model/i);
});

test("tables are keyboard reachable and bounded inside horizontal scroll regions", () => {
  includesAll(lab, [
    "min-w-0",
    "overflow-x-auto",
    'role="region" aria-label="Excluded predictors" tabIndex={0}',
    'role="region" aria-label="Experiment queue" tabIndex={0}',
    'role="region" aria-label="Development leaderboard" tabIndex={0}',
    '<caption className="sr-only">',
    'scope="col"',
    "sm:grid-cols-2",
    "xl:grid-cols-4",
  ], "responsive accessibility");
});

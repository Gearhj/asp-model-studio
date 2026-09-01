import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");
const [cockpit, lab, evaluation, refinement, comparison, api] = await Promise.all([
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/sports/cockpit/ProjectBoundModelLab.tsx"),
  read("src/sports/cockpit/ProjectBoundCandidateEvaluation.tsx"),
  read("src/sports/cockpit/ProjectBoundModelRefinement.tsx"),
  read("src/sports/cockpit/ProjectCandidateComparison.tsx"),
  read("src/sports/cockpit/projectModelLabApi.ts"),
]);

const includesAll = (source, values, label) => values.forEach((value) => assert.ok(source.includes(value), `${label} missing: ${value}`));

test("Stage 3 exposes the governed fifteen-step model-development sequence", () => {
  includesAll(cockpit, [
    'id: "modellab", n: "09", label: "Model Development Laboratory"',
    '<ProjectBoundModelLab projectId={c.projectId} go={c.go} />',
    'id: "evaluation", n: "10", label: "Candidate Evaluation"',
    'id: "refinement", n: "11", label: "Model Refinement & Explainability"',
    'id: "registry", n: "15", label: "Registry, Export & Implementation"',
  ], "fifteen-step routing");
  assert.doesNotMatch(cockpit, /id: "tuning"|label: "Hyperparameter Tuning"|TuningStep/);
});

test("Model Laboratory is an explicit multi-model batch builder with bounded concurrency", () => {
  includesAll(lab, [
    "Select all available models", "Clear all", "Select recommended baseline bundle",
    "Select family", "Clear family", "Use this feature universe for all selected models",
    "Full Eligible", "Core Gold 48 benchmark", "Custom Eligible Subset",
    "FIXED", "GRID", "RANDOM", "Compact Grid", "Full Grid", "Custom Grid",
    "Review exact batch plan", "Save Draft Batch", "Clear Unstarted Queue",
    "Run ${plan?.totalExperiments", "Parallel candidate workers",
    "Auto (resource-aware)", "2 workers if safe",
    "One active batch per project", "Each fold owns its preprocessing and estimator",
    "Batch failed before completion", "job.error?.code", "job.error?.message",
  ], "multi-model controls");
  assert.ok(lab.includes("Opening this page performs zero fits."));
  assert.ok(lab.includes("Final OOT") && lab.includes("No training, tuning, calibration, or selection access"));
});

test("saved feature choices reconcile to the current content-addressed authority", () => {
  includesAll(lab, [
    "function currentFeatureUniverseId(",
    'requested === summary.featureUniverse.featureSetId',
    'requested === "CUSTOM_SUBSET"',
    "summary.featureSets.some((item) => item.featureSetId === requested)",
    "return summary.featureUniverse.featureSetId",
    "featureUniverseId: currentFeatureUniverseId(restored.featureUniverseId, next)",
  ], "content-addressed feature-authority reconciliation");
});

test("current batches and historical immutable baselines remain visually distinct", () => {
  includesAll(lab, [
    "A · Current project batch", "B · Historical verified baselines",
    "current-batch-evidence", "historical-baseline-evidence",
    "Immutable V1 receipts are grouped by scientific fingerprint",
  ], "receipt grouping");
  includesAll(comparison, [
    "One bar and one ranked row per canonical candidate specification", "Immutable attempt history",
    "reproducibilityStatus", "Failed candidates",
  ], "comparison evidence");
});

test("Evaluation compares project-bound development evidence and selects finalists only", () => {
  includesAll(evaluation, [
    "Project-bound receipts only", "CURRENT_BATCH", "HISTORICAL_BASELINE",
    "Five-fold log-loss distribution", "one-vs-rest lift / cumulative gains",
    "Cross-model fold variability", "Runtime versus OOF log loss", "Eight-class confusion evidence",
    "EVIDENCE NOT CAPTURED IN HISTORICAL RECEIPT", "PERMUTATION_IMPORTANCE", "SHAP", "SENSITIVITY",
    "SHAP and sensitivity require a saved finalist receipt", "Save immutable finalist receipt",
    "Not champion", "Not promoted", "Final OOT locked",
  ], "Candidate Evaluation");
  assert.doesNotMatch(evaluation, /selectChampion|promoteModel|auto.?promot/i);
});

test("Refinement creates immutable reduced challengers without mutating parents", () => {
  includesAll(refinement, [
    "Only explicit Evaluation finalists enter", "RFE", "RFECV",
    "STABILITY_SELECTION", "COEFFICIENT_GUIDED_ELIMINATION",
    "Minimum retained", "Elimination step", "Expected selector fits",
    "Create immutable refinement plan", "Run supported reduced challenger",
    "FULL MODEL", "REDUCED CHALLENGER", "PARSIMONY",
  ], "refinement workflow");
  assert.ok(refinement.includes("Final OOT") && refinement.includes("Never used for selection"));
  assert.doesNotMatch(refinement, /promoteModel|selectChampion/);
});

test("client uses project-scoped plan, jobs, cancellation, Evaluation, finalist, analysis, and refinement routes", () => {
  includesAll(api, [
    "/sports/stage3-model-laboratory", "`${prefix(projectId)}/summary`", "`${prefix(projectId)}/plan`",
    "`${prefix(projectId)}/jobs`", "cancel-unstarted", "stage3-candidate-evaluation",
    "`${evaluationPrefix(projectId)}/finalists`", "`${evaluationPrefix(projectId)}/analysis`",
    "stage3-model-refinement/plan", "stage3-model-refinement/execute", 'credentials: "include"',
  ], "project-scoped APIs");
});

test("client preserves exact current authority and fails closed on OOT, legacy, provider, or promotion drift", () => {
  includesAll(api, [
    'const CURRENT_PROJECT_ID = "asp-mtddc6pw"',
    'const CURRENT_GOLD_ID = "gold-table:gold_mlb_current_pa_v1"',
    "67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758",
    "683_662", "14_067", "CURRENT_TARGET_ORDER", "CURRENT_FEATURE_SET_IDS",
    "finalOotLocked !== true", "finalOotTargetAccessed !== false", "providerCalls !== 0",
    "legacyGlobalMatrixUsed !== false", "autoPromoted !== false", 'promotionStatus !== "NOT_PROMOTED"',
  ], "client safety boundary");
});

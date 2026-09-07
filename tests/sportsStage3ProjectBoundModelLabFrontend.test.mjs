import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");
const [cockpit, lab, evaluation, refinement, comparison, tuningDecision, api] = await Promise.all([
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/sports/cockpit/ProjectBoundModelLab.tsx"),
  read("src/sports/cockpit/ProjectBoundCandidateEvaluation.tsx"),
  read("src/sports/cockpit/ProjectBoundModelRefinement.tsx"),
  read("src/sports/cockpit/ProjectCandidateComparison.tsx"),
  read("src/sports/cockpit/GovernedTuningDecisionPanel.tsx"),
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
    "Select all resource-safe models", "Clear all", "Select recommended baseline bundle",
    "Select resource-safe family", "Clear family", "Use this feature universe for all selected models",
    "Full Eligible", "MLB Core Challenger", "Custom Eligible Subset",
    "FIXED", "GRID", "RANDOM", "Compact Grid", "Full Grid", "Custom Grid",
    "Review exact batch plan", "Save Draft Batch", "Clear draft selections",
    "Cancel unstarted configurations", "Cancellation recorded · active fits draining",
    "Recording cancellation…", "Batch cancelled after preserving completed evidence",
    "Run ${plan?.totalExperiments", "Parallel candidate workers",
    "Auto (resource-aware)", "2 workers if safe",
    "One active batch per project", "Resource-safe defaults use one fixed configuration per selected algorithm",
    "High-memory candidates run exclusively", "bounded native CPU budget",
    "Batch failed before completion", "job.error?.code", "job.error?.message",
    "summary.treatment.includedFeatureCount", "11 derived bindings unreachable",
  ], "multi-model controls");
  assert.ok(lab.includes('tuningMode: "FIXED"'), "new drafts must start with fixed configurations");
  assert.ok(lab.includes("item.available && item.automaticBundleEligible"), "automatic bundles must exclude guarded/manual algorithms");
  assert.ok(lab.includes("asp-stage3-multimodel:v3:"), "stale unsafe GRID drafts must not be restored");
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

test("legacy runtime-only draft parameters migrate without hiding scientist edits", () => {
  includesAll(lab, [
    "const LEGACY_RUNTIME_PARAMETER_OWNERS",
    'n_jobs: new Set(["random_forest", "extra_trees", "xgboost", "lightgbm", "knn"])',
    'thread_count: new Set(["catboost"])',
    "function withoutLegacyRuntimeParameters",
    "function migrateLegacyRuntimeJson",
    "allowed.has(key) || !legacyOwners?.has(algorithm.id)",
    "Array.isArray(entry) && entry.length === 1 && entry[0] === 1",
    "entry !== 1",
    "fixedText: migrateLegacyRuntimeJson(restoredFixedText, algorithm, false)",
    "customGridText: migrateLegacyRuntimeJson(restoredGridText, algorithm, true)",
    "withoutLegacyRuntimeParameters(fixedInput, algorithm, false)",
    "withoutLegacyRuntimeParameters(customInput, algorithm, true)",
  ], "legacy runtime-only draft migration");
  assert.match(lab, /if \(!parsed\) return value/, "invalid scientist JSON must remain visible instead of being silently reset");
});

test("current batches and historical immutable baselines remain visually distinct", () => {
  includesAll(lab, [
    "Completed configurations so far — interim evidence",
    "Interim results are not final-ranked and cannot be selected as finalists",
    "A · Terminal current project batch", "B · Historical verified baselines",
    "incremental-current-evidence", "current-batch-evidence", "historical-baseline-evidence",
    "Immutable V1 receipts are grouped by scientific fingerprint",
  ], "receipt grouping");
  includesAll(comparison, [
    "One bar and one ranked row per canonical candidate specification", "Immutable attempt history",
    "reproducibilityStatus", "Failed candidates",
  ], "comparison evidence");
});

test("active job polling refreshes Evaluation only for new complete receipts and terminal state", () => {
  includesAll(lab, [
    "completedReceiptSignature", "completedReceiptsSignature",
    "terminalEvaluationJob",
    "candidateReceiptSha256", "nextReceiptSignature",
    "!terminal && nextReceiptSignature !== completedReceiptsSignature.current",
    "terminal && terminalEvaluationJob.current !== job.jobId",
    "const nextEvaluation = await fetchProjectCandidateEvaluation(projectId)", "setEvaluation(nextEvaluation)",
    "if (polling) return", "evaluationReceiptCount >= jobReceiptCount",
  ], "incremental receipt polling");
  assert.ok(lab.includes("2_000"), "job progress must continue polling every two seconds");
});

test("launch binds the exact reviewed plan and reports terminal progress honestly", () => {
  includesAll(api, [
    "expectedPlanId: reviewedPlan.planId", "expectedPlanChecksum: reviewedPlan.checksum",
    "value.job.plan?.planId !== reviewedPlan.planId", "value.job.plan?.checksum !== reviewedPlan.checksum",
    "The queued job did not bind the exact reviewed plan and final-OOT lock",
  ], "reviewed-plan binding");
  includesAll(lab, [
    'cancelledTerminal ? "Cancelled"', 'stoppedTerminal ? "Stopped"',
    'completedTerminal ? "Complete"', 'ordinaryRemaining > 0 && progress.estimatedRemainingSeconds <= 0',
    "Cancelled-configuration count unavailable", "Interim receipts held closed",
  ], "honest terminal and held-closed progress");
});

test("interrupted work is terminal, failed closed, and preserves completed evidence", () => {
  includesAll(api, [
    "ModelDevelopmentJobStatus", '| "INTERRUPTED"',
    '"FAILED", "INTERRUPTED"',
  ], "interrupted status contract");
  includesAll(lab, [
    'const interruptedTerminal = job.status === "INTERRUPTED"',
    "const stoppedTerminal = failedTerminal || interruptedTerminal",
    "Batch was interrupted and is held closed",
    "Completed immutable candidate receipts remain preserved",
    "terminalUnfinishedValue", "progress.unstartedFits", "progress.unresolvedFits",
    "progress.interruptedCandidates.length", "Unfinished work:",
  ], "interrupted terminal UI");
  assert.ok(lab.includes('!["QUEUED", "RUNNING", "CANCEL_REQUESTED"].includes(job.status)'), "INTERRUPTED must never be polled as active");
});

test("runtime admission distinguishes planned capacity from workers actually admitted", () => {
  includesAll(api, [
    "runtimeAdmission", "plannedCandidateWorkers", "effectiveCandidateWorkers",
    "availableMemoryGiBAtStart", "admissionPolicy",
    "pendingFits", "unstartedFits", "unresolvedFits", "interruptedCandidates",
  ], "runtime progress contract");
  includesAll(lab, [
    "up to {plan.parallelism.effectiveCandidateWorkers} candidate worker(s) planned",
    "Runtime workers", "admittedWorkersValue", "runtime-worker-admission",
    "candidate worker(s) admitted from an upper bound of",
    "GiB available at start", "Admission not reported",
    "progress.cancellationPendingFits ?? progress.pendingFits ?? ordinaryRemaining",
  ], "runtime admission UI");
});

test("client contract carries resource scheduling and incremental evidence authority", () => {
  includesAll(api, [
    "automaticBundleEligible", "ModelComputeGuard", "ModelExecutionResources",
    "schedulingPolicy", "maximumEstimatorNativeWorkers", "exclusiveCandidateWorkers",
    "incrementalCurrentEvidence", "rankingEligible: false", "finalistSelectionEligible: false",
  ], "resource-aware API contract");
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
  includesAll(comparison, [
    '"ROC-AUC": "macroOvrRocAuc"', "Sort by ${heading}",
    "number(group.macroOvrRocAuc)", "colSpan={19}",
  ], "sortable candidate comparison");
  assert.doesNotMatch(evaluation, /selectChampion|promoteModel|auto.?promot/i);
});

test("Model Lab and Evaluation expose the frozen tuning decision without widening authority", () => {
  includesAll(lab, [
    "GovernedTuningDecisionPanel", "Tuning decision frozen · stop boundary",
    "Feature refinement, calibration, SHAP, recursive feature elimination",
  ], "Model Lab tuning decision");
  includesAll(evaluation, [
    "GovernedTuningDecisionPanel", "Tuning decision stop boundary",
    "The frozen tuning decision creates no finalist authority",
    "Post-tuning analyses are held closed",
  ], "Evaluation tuning decision");
  includesAll(tuningDecision, [
    "Governed compact tuning decision", "First screen", "Best tuned",
    "Null baseline", "Absolute improvement", "Relative improvement", "Worst fold", "Fold SD",
    "ROC-AUC", "Exact hyperparameters", "Game-clustered HGB − RF",
    "Immutable run identity", "immutableModelRunReceiptSha256",
    "Shared class-frequency null beside every comparison",
    "FINAL OOT SEALED", "ADVANCE_TO_REFINEMENT",
    "RETAIN_AS_DIVERSITY_CHALLENGER", "NO_TUNING_GAIN", "REQUIRES_REPAIR",
    "no new finalist label", "No champion · no promotion",
  ], "governed tuning panel");
  assert.ok(api.includes("tuningDecision?: Record<string, any> | null"));
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

test("Refinement presents truthful parent evidence and only executable selectors", () => {
  includesAll(refinement, [
    "representativeAttemptId", "hasRankingEvidence", "representativeEvidenceAttempt",
    "EVIDENCE ·", "HISTORICAL_BASELINE", "NO RANKING PREVIEW IN PARENT RECEIPT",
    "No feature ranking is fabricated", "recompute ranking evidence from training rows independently inside each chronological training fold",
    "CURRENT_EXECUTOR_METHODS", '"RFE", "STABILITY_SELECTION", "COEFFICIENT_GUIDED_ELIMINATION"',
    "PLAN_ONLY_EXECUTOR_UNAVAILABLE", "INCOMPATIBLE_WITH_SELECTED_ESTIMATOR",
    "disabled={!state.executable}", "disabled={!methodExecution.executable}",
    "planned && methodExecution.executable", "plan-only designs until a fold-local executor exists",
    "(expectedRounds + 1) * 5",
  ], "refinement evidence and execution capability");
  assert.doesNotMatch(refinement, /executable reduction will fail closed for this candidate/);
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
    'const CURRENT_GOLD_ID = "gold-table:gold_mlb_current_pa_v1"',
    "67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758",
    "683_662", "14_067", "CURRENT_TARGET_ORDER", "CURRENT_FEATURE_SET_IDS",
    "finalOotLocked !== true", "finalOotTargetAccessed !== false", "providerCalls !== 0",
    "legacyGlobalMatrixUsed !== false", "autoPromoted !== false", 'promotionStatus !== "NOT_PROMOTED"',
  ], "client safety boundary");
  assert.doesNotMatch(api, /CURRENT_PROJECT_ID/, "Project identity must come from the selected project request");
});

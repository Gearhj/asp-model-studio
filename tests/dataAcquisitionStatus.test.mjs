// Data Acquisition status and predictor interpretation integrity.
//
// PROVEN ROOT CAUSE guarded here: the page had TWO derivations of "is this
// ready" rendered in THREE places --
//   hero        `nextDisabledReason ? "Needs review" : "Ready"`  (ignores findings)
//   strip       `readiness.status` mapping                        (uses findings)
//   checkpoint  `READINESS_LABELS[readiness.status]`              (uses findings)
// -- so "Ready", "Blocked", and "Ready with Warnings" could describe one state
// simultaneously. Every visible status now derives from one model.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/data-acquisition-status-tests", import.meta.url));

async function transpile(sourcePath, outputName) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const patched = source.replace(/import\.meta\.env\?\.\w+ as string \| undefined/g, "undefined");
  const output = ts.transpileModule(patched, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const outPath = path.join(TMP_DIR, outputName);
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, output, "utf8");
  return import(pathToFileURL(outPath).href);
}

await rm(TMP_DIR, { recursive: true, force: true });
const status = await transpile("src/lib/dataAcquisitionStatus.ts", "dataAcquisitionStatus.js");
const profile = await transpile("src/lib/governedProfile.ts", "governedProfile.js");
const step01 = await readFile(new URL("src/steps/Step01_DataAcquisition.tsx", ROOT), "utf8");
const service = await readFile(new URL("server/preprocessing/governed_profile_service.py", ROOT), "utf8");

/** The loaded, profiled CLASS_TRAIN state. */
function classTrain(overrides = {}) {
  return status.deriveDataAcquisitionStatus({
    hasSelectedVersion: true, isRegisteredAsset: true, isLinkedToProject: true,
    isLoaded: true, isLoading: false, loadError: null,
    target: "Class", eventValue: 1, nonEventValue: 0, selectedPredictorCount: 30,
    profilePhase: "ready", profileError: null,
    authoritativeEventCount: 360, authoritativeNonEventCount: 170524,
    duplicateRows: 52, columnsWithMissingValues: 29,
    unusuallyStrongPredictorCount: 4, isRareEvent: true,
    reviewCompleted: false, ...overrides,
  });
}

// --- Cases 1-12: every state combination -----------------------------------

test("1. no dataset selected", () => {
  const state = status.deriveDataAcquisitionStatus({
    hasSelectedVersion: false, isRegisteredAsset: false, isLinkedToProject: false,
    isLoaded: false, isLoading: false, target: "", selectedPredictorCount: 0, reviewCompleted: false,
  });
  assert.equal(state.loadState, "not_selected");
  assert.equal(state.readiness, "blocked");
  assert.equal(state.canContinue, false);
  assert.equal(state.registrationState, "unknown");
});

test("2. registered version selected but not loaded", () => {
  const state = status.deriveDataAcquisitionStatus({
    hasSelectedVersion: true, isRegisteredAsset: true, isLinkedToProject: true,
    isLoaded: false, isLoading: false, target: "", selectedPredictorCount: 0, reviewCompleted: false,
  });
  assert.equal(state.loadState, "selected_not_loaded");
  assert.equal(state.loadLabel, "Selected, not loaded");
  assert.equal(state.registrationState, "registered");
  assert.equal(state.linkState, "linked");
  assert.equal(state.recommendedAction, "Load the selected Dataset Version.");
  assert.equal(state.currentActiveMilestone, "Load required");
});

test("3-4. loading, then loaded and profiling", () => {
  const loading = classTrain({ isLoading: true, isLoaded: false, profilePhase: "idle" });
  assert.equal(loading.loadState, "loading");
  assert.equal(loading.loadTone, "info");

  const profiling = classTrain({ profilePhase: "quality" });
  assert.equal(profiling.loadState, "loaded");
  assert.equal(profiling.readiness, "unavailable");
  assert.match(profiling.currentActiveMilestone, /Profiling/);
});

test("5. profile complete with non-blocking warnings", () => {
  const state = classTrain();
  assert.equal(state.readiness, "ready_with_warnings");
  assert.equal(state.reviewState, "review_required");
  assert.equal(state.canContinue, true, "warnings never block");
  assert.deepEqual(state.blockingReasons, []);
  assert.ok(state.warnings.some((w) => /52 duplicate/.test(w)));
  assert.ok(state.warnings.some((w) => /29 column/.test(w)));
  assert.ok(state.warnings.some((w) => /Rare-event/.test(w)));
  assert.ok(state.warnings.some((w) => /unusually strong/i.test(w)));
});

test("6. profile complete without warnings", () => {
  const state = classTrain({
    duplicateRows: 0, columnsWithMissingValues: 0, unusuallyStrongPredictorCount: 0, isRareEvent: false,
  });
  assert.equal(state.readiness, "ready");
  assert.equal(state.readinessTone, "success");
  assert.equal(state.continueLabel, "Mark Complete & Continue to EDA");
});

test("7. invalid event mapping blocks", () => {
  const state = classTrain({ eventValue: 1, nonEventValue: 1 });
  assert.equal(state.readiness, "blocked");
  assert.equal(state.canContinue, false);
  assert.ok(state.blockingReasons.some((r) => /cannot be the same/.test(r)));
});

test("8. zero authoritative events blocks", () => {
  const zeroEvents = classTrain({ authoritativeEventCount: 0 });
  assert.equal(zeroEvents.readiness, "blocked");
  assert.ok(zeroEvents.blockingReasons.some((r) => /no events/.test(r)));
  const zeroNonEvents = classTrain({ authoritativeNonEventCount: 0 });
  assert.ok(zeroNonEvents.blockingReasons.some((r) => /no non-events/.test(r)));
});

test("9-10. missing full artifact and profile failure block", () => {
  const missing = classTrain({ profilePhase: "artifact_missing" });
  assert.equal(missing.readiness, "blocked");
  assert.ok(missing.blockingReasons.some((r) => /complete data artifact/.test(r)));

  const failed = classTrain({ profilePhase: "failed", profileError: "boom" });
  assert.equal(failed.readiness, "blocked");
  assert.ok(failed.blockingReasons.includes("boom"));
});

test("11-12. review required, then completed", () => {
  const required = classTrain();
  assert.equal(required.reviewState, "review_required");
  assert.equal(required.reviewLabel, "Review required");
  assert.equal(required.continueLabel, "Acknowledge Warnings & Continue to EDA");

  const done = classTrain({ reviewCompleted: true });
  assert.equal(done.reviewState, "completed");
  assert.equal(done.reviewTone, "success");
  assert.equal(done.continueLabel, "Continue to EDA");
  assert.match(done.recommendedAction, /complete/i);
});

// --- Cases 13-16: the contradiction itself ---------------------------------

test("13. Ready with Warnings is never Blocked", () => {
  const state = classTrain();
  assert.equal(state.readiness, "ready_with_warnings");
  assert.notEqual(state.readiness, "blocked");
  assert.notEqual(state.readinessLabel, "Blocked");
  assert.equal(state.readinessTone, "warning");
  // Review is amber, not red -- the old page painted this "Blocked".
  assert.equal(state.reviewTone, "warning");
  assert.equal(state.canContinue, true);
});

test("14. Blocked disables progression", () => {
  const state = classTrain({ profilePhase: "failed", profileError: "profile failed" });
  assert.equal(state.canContinue, false);
  assert.equal(state.readinessTone, "danger");
  assert.equal(state.continueLabel, "Resolve blockers to continue");
});

test("15. a registered selected dataset is never labelled Not registered", () => {
  const state = classTrain({ isLoaded: false });
  assert.equal(status.registrationLabel(state.registrationState), "Registered");
  assert.notEqual(status.registrationLabel(state.registrationState), "Not registered");
  assert.equal(status.projectLinkLabel(state.linkState), "Linked");
  // The hero no longer derives registration from an upload filename.
  assert.doesNotMatch(step01, /value: fileName \|\| "Not registered"/);
  assert.match(step01, /registrationLabel\(acquisitionStatus\.registrationState\)/);
});

test("16. a successful load uses success semantics", () => {
  assert.equal(classTrain().loadTone, "success");
  assert.match(step01, /Loaded\|Registered\|Cached\|Linked\|Saved/, "a successful message must map to green");
  assert.match(step01, /border-emerald-200 bg-emerald-50/);
  assert.match(step01, /data-testid="data-acquisition-message"/);
  assert.match(step01, /aria-live="polite"/);
});

test("every visible status reads from the one shared model", () => {
  assert.match(step01, /deriveDataAcquisitionStatus\(/, "the shared derivation must be used");
  assert.match(step01, /value: acquisitionStatus\.readinessLabel/, "the hero must read the shared state");
  assert.match(step01, /acquisitionStatus\.reviewState === "completed"/, "the strip must read the shared state");
  assert.match(step01, /nextDisabled=\{!acquisitionStatus\.canContinue\}/, "progression must read the shared state");
  // The old independent derivation no longer gates progression.
  assert.doesNotMatch(step01, /nextDisabled=\{!!nextDisabledReason\}/);
});

// --- Cases 17-25: predictor interpretation ---------------------------------

test("17. the target is excluded from predictor near-zero variance", () => {
  assert.match(service, /if distinct <= 1 and str\(column\) != target:/);
  assert.match(service, /if str\(column\) in constant_columns or str\(column\) == target:/);
  assert.match(service, /"targetExcludedFromPredictorFindings"/);
});

test("18. IV >= 0.50 produces unusually-strong review semantics", () => {
  const strong = profile.signalStrength({ iv: 3.2824, ivStatus: "available" });
  assert.equal(strong.key, "unusually_strong");
  assert.equal(strong.label, "Unusually strong");
  assert.equal(strong.reviewRecommended, true);
  assert.equal(strong.tone, "warning", "amber, not green");
  assert.equal(profile.signalStrength({ iv: 0.4, ivStatus: "available" }).key, "strong");
  assert.equal(profile.signalStrength({ iv: 0.15, ivStatus: "available" }).key, "medium");
  assert.equal(profile.signalStrength({ iv: 0.05, ivStatus: "available" }).key, "weak");
  assert.equal(profile.signalStrength({ iv: 0.001, ivStatus: "available" }).key, "not_predictive");
});

test("19. high IV alone never yields likely or confirmed leakage", () => {
  const state = profile.leakageScreen({ iv: 3.6283, ivStatus: "available", role: "eligible", eligible: true });
  assert.equal(state, "review_recommended");
  assert.notEqual(state, "likely_leakage");
  assert.notEqual(state, "confirmed_leakage");
  assert.equal(profile.LEAKAGE_SCREEN_LABELS[state], "Review recommended");
  // A normal IV reports the precise meaning, not the ambiguous "Eligible".
  const normal = profile.leakageScreen({ iv: 0.12, ivStatus: "available", role: "eligible", eligible: true });
  assert.equal(profile.LEAKAGE_SCREEN_LABELS[normal], "No automated leakage signal");
  assert.doesNotMatch(step01, /leakageRole \? "Excluded" : "Eligible"/, "the ambiguous label must be gone");
});

test("20. high IV does not automatically deselect the predictor", () => {
  // The weak-signal planner only ever removes predictors BELOW the threshold.
  const plan = profile.planWeakSignalExclusion({
    profile: {
      analysisScope: { mode: "governed_version" },
      predictors: [{ predictor: "V4", eligible: true, iv: 3.2824, ivStatus: "available" }],
      predictorSummary: { evaluated: 1, total: 1, unavailable: 0, failed: 0, leakageReview: 0 },
    },
    loading: false, error: null, problemType: "classification", selected: ["V4"],
  });
  assert.deepEqual(plan.affected, [], "an unusually strong predictor is never auto-removed");
  assert.match(step01, /do not block Data Acquisition/i);
});

test("21-22. counts exclude the target and report all 30 predictors", () => {
  const predictors = Array.from({ length: 30 }, (_, index) => ({
    predictor: `V${index + 1}`, eligible: true, role: "eligible", iv: 0.2, ivStatus: "available",
  }));
  // The target is present in the response but is NOT an eligible predictor.
  predictors.push({ predictor: "Class", eligible: false, role: "target", iv: null, ivStatus: "unavailable_not_eligible" });
  const counts = profile.predictorEvaluationCounts({ predictors }, "Class");
  assert.equal(counts.evaluated, 30);
  assert.equal(counts.unavailable.length, 0, "the target must not appear as an unavailable predictor");
  assert.equal(counts.targetExcluded, "Class");
  assert.equal(counts.summaryText, "30 predictors evaluated");
  assert.doesNotMatch(counts.summaryText, /unavailable/);
});

test("23. a genuinely unavailable predictor is named with its reason", () => {
  const counts = profile.predictorEvaluationCounts({
    predictors: [
      { predictor: "V1", eligible: true, role: "eligible", iv: 0.3, ivStatus: "available" },
      { predictor: "V17", eligible: true, role: "eligible", iv: null, ivStatus: "unavailable_insufficient_population" },
      { predictor: "Class", eligible: false, role: "target", iv: null, ivStatus: "unavailable_not_eligible" },
    ],
  }, "Class");
  assert.equal(counts.evaluated, 1);
  assert.equal(counts.unavailable.length, 1);
  assert.equal(counts.unavailable[0].predictor, "V17");
  assert.match(counts.unavailable[0].reason, /insufficient population/i);
  assert.match(counts.summaryText, /1 predictor unavailable/);
});

test("24-25. unavailable IV is not zero and is excluded from strength bands", () => {
  const row = { iv: null, ivStatus: "unavailable_no_events" };
  assert.equal(profile.signalStrength(row), null, "an unavailable IV has no strength band");
  assert.equal(profile.formatIv(null), "Not available");
  const counts = profile.predictorEvaluationCounts({
    predictors: [
      { predictor: "A", eligible: true, role: "eligible", iv: null, ivStatus: "failed" },
      { predictor: "B", eligible: true, role: "eligible", iv: 0.9, ivStatus: "available" },
    ],
  }, "Class");
  assert.equal(counts.unusuallyStrong, 1, "only computed values count toward a band");
  assert.equal(counts.evaluated, 1);
});

test("the high-IV explanation is shown and is conservative", () => {
  assert.match(profile.HIGH_IV_EXPLANATION, /post-outcome information/);
  assert.match(profile.HIGH_IV_EXPLANATION, /unavailable at scoring time/);
  assert.match(step01, /data-testid="high-iv-explanation"/);
  assert.match(step01, /data-testid="signal-strength-cell"/);
  assert.match(step01, /data-testid="predictor-evaluation-summary"/);
});

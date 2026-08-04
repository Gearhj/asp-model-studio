// Data Acquisition full-population profiling and IV integrity -- frontend tests.
//
// Each block names the proven root cause it guards:
//   1. backend asserting full_dataset for whatever was in DATASTORE
//   2. silent browser-preview fallback on a failed governed request
//   3. Number(null) rendering an unavailable IV as 0.0000
//   4. preview-derived zero event rate creating a false population blocker
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/governed-profile-tests", import.meta.url));

async function transpile(sourcePath, outputName) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const patched = source
    .replace(/import\.meta\.env\?\.\w+ as string \| undefined/g, "undefined")
    .replace('from "./datasetIdentity";', 'from "./datasetIdentity.js";');
  const output = ts.transpileModule(patched, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const outPath = path.join(TMP_DIR, outputName);
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, output, "utf8");
  return import(pathToFileURL(outPath).href);
}

await rm(TMP_DIR, { recursive: true, force: true });
await transpile("src/lib/datasetIdentity.ts", "datasetIdentity.js");
const lib = await transpile("src/lib/governedProfile.ts", "governedProfile.js");
const lifecycle = await transpile("src/lib/dataAcquisitionLifecycle.ts", "dataAcquisitionLifecycle.js");

const step01 = await readFile(new URL("src/steps/Step01_DataAcquisition.tsx", ROOT), "utf8");
const hook = await readFile(new URL("src/lib/useTargetProfile.ts", ROOT), "utf8");
const workspace = await readFile(new URL("src/components/eda/TargetIntelligenceWorkspace.tsx", ROOT), "utf8");
const packageJson = JSON.parse(await readFile(new URL("package.json", ROOT), "utf8"));

// --- Root cause 3: null must never render as a number ----------------------

test("IV formatting never coerces null into 0.0000", () => {
  // Number(null) === 0 is what produced the red wall of 0.0000.
  assert.equal(Number(null), 0, "precondition: the old formatter's coercion still behaves this way");
  assert.equal(lib.formatIv(null), "Not available");
  assert.equal(lib.formatIv(undefined), "Not available");
  assert.equal(lib.formatIv(Number.NaN), "Not available");
  // A genuine zero is still a zero.
  assert.equal(lib.formatIv(0), "0.0000");
});

test("a positive IV below 0.0001 renders as <0.0001, never as 0.0000", () => {
  assert.equal(lib.formatIv(0.00002), "<0.0001");
  assert.equal(lib.formatIv(0.000099), "<0.0001");
  assert.equal(lib.formatIv(0.0001), "0.0001");
  assert.equal(lib.formatIv(0.1234567), "0.1235");
  // Full precision remains available for the accessible detail.
  assert.match(lib.formatIvExact(0.00002), /^0\.00002/);
});

test("every IV state renders as text, never as a number", () => {
  assert.equal(lib.ivCellText({ iv: null, ivStatus: "pending" }), "Calculating");
  assert.equal(lib.ivCellText({ iv: 0.42, ivStatus: "available" }), "0.4200");
  assert.equal(lib.ivCellText({ iv: null, ivStatus: "unavailable_no_events" }), lib.IV_STATUS_LABELS.unavailable_no_events);
  assert.equal(lib.ivCellText({ iv: null, ivStatus: "preview_only" }), lib.IV_STATUS_LABELS.preview_only);
  assert.equal(lib.ivCellText({ iv: null, ivStatus: "failed" }), lib.IV_STATUS_LABELS.failed);
  for (const [status, label] of Object.entries(lib.IV_STATUS_LABELS)) {
    if (status === "available") continue;
    assert.doesNotMatch(label, /^0(\.0+)?$/, `${status} must not read as a number`);
  }
});

test("the Variable Summary renders IV through the status-aware formatter", () => {
  assert.match(step01, /ivCellText\(governedIv\(row\.column\)\)/, "IV cells must use the status-aware formatter");
  assert.doesNotMatch(
    step01,
    /\{formatNumber\(targetInfo\.kind === "continuous" \? row\.corr : row\.iv\)\}/,
    "the coercing formatter must no longer render IV"
  );
  assert.match(step01, /data-testid="iv-cell"/);
  assert.match(step01, /data-iv-status=/, "each IV cell must expose its calculation status");
  assert.match(step01, /data-testid="iv-status-cell"/, "a calculation-status column must exist");
});

// --- Root cause 2: no silent preview fallback ------------------------------

test("a failed governed profile is never replaced by a browser computation", () => {
  assert.doesNotMatch(
    step01,
    /\.catch\(\(\) => alive && setFeatureProfile\(browserProfile\(\)\)\)/,
    "the silent feature-profile fallback must be gone"
  );
  assert.doesNotMatch(
    step01,
    /\.catch\(\(\) => alive && setQuality\(browserQuality\(\)\)\)/,
    "the silent quality-profile fallback must be gone"
  );
  assert.match(step01, /Full-population data quality profiling failed/, "a failure must be surfaced");
  assert.match(step01, /data-testid="profile-retry"/, "a retry action must exist");
  // The profile client itself has no fallback path at all.
  assert.doesNotMatch(hook, /browserProfile|profileFeaturesInBrowser/);
});

test("the profile request carries no client-asserted governance", () => {
  const body = lib.buildTargetProfileKey({
    projectId: "p", datasetId: "d", versionId: "v", target: "Class", eventValue: 1, nonEventValue: 0,
  });
  assert.match(body, /^governed_version\|p\|d\|v\|/);
  const draft = lib.buildTargetProfileKey({
    projectId: "p", datasetId: null, versionId: null, target: "Class", workspaceFingerprint: "wsfp_a",
  });
  assert.match(draft, /^workspace\|p\|\|\|wsfp_a\|/);
});

// --- Part E: mapping changes invalidate dependent results ------------------

test("changing the event mapping is a different analytical identity", () => {
  const base = { projectId: "p", datasetId: "d", versionId: "v", target: "Class", eventValue: 1, nonEventValue: 0 };
  const reversed = { ...base, eventValue: 0, nonEventValue: 1 };
  const otherTarget = { ...base, target: "Other" };
  const otherVersion = { ...base, versionId: "v2" };
  const keys = [base, reversed, otherTarget, otherVersion].map(lib.buildTargetProfileKey);
  assert.equal(new Set(keys).size, 4, "each change must produce a distinct identity");
});

test("a stale response cannot overwrite a newer mapping", () => {
  assert.match(hook, /activeKeyRef\.current !== key/, "responses must be rejected when the identity moved on");
  assert.match(hook, /setState\(\{ \.\.\.IDLE, phase: "quality", ivLoading: true \}\)/,
    "a new mapping must clear the previous mapping's numbers immediately");
});

test("duplicate renders issue one active request per identity", async () => {
  lib.clearTargetProfileCache();
  let calls = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  globalThis.fetch = async () => {
    calls += 1;
    await gate;
    return {
      ok: true,
      json: async () => ({
        ok: true,
        datasetId: "d",
        datasetVersionId: "v",
        predictors: [],
        analysisScope: { mode: "governed_version", projectId: "p" },
      }),
    };
  };
  const request = { projectId: "p", datasetId: "d", versionId: "v", target: "Class" };
  const promises = [lib.fetchTargetProfile(request), lib.fetchTargetProfile(request), lib.fetchTargetProfile(request)];
  assert.equal(calls, 1, "three identical requests must produce exactly one active query");
  assert.equal(lib.activeTargetProfileRequests(), 1);
  release();
  await Promise.all(promises);
  await lib.fetchTargetProfile(request);
  assert.equal(calls, 1, "a resolved result must be reused");
});

test("a legacy version with no complete artifact surfaces the machine-readable reason", async () => {
  lib.clearTargetProfileCache();
  globalThis.fetch = async () => ({
    ok: false,
    status: 409,
    json: async () => ({
      detail: {
        reason: "full_artifact_missing",
        message: "Dataset version v_old does not contain a complete data artifact",
        disclosure: "Legacy Dataset Version: Full Artifact Unavailable.",
        datasetId: "ds_old", versionId: "v_old", sampleSubstituted: false,
        recovery: ["Select a Dataset Version that has a complete governed artifact.", "Or re-register the original source file."],
      },
    }),
  });
  await assert.rejects(
    () => lib.fetchTargetProfile({ projectId: "p", datasetId: "ds_old", versionId: "v_old", target: "Class" }),
    (error) => {
      assert.equal(error.name, "ProfileUnavailableError");
      assert.equal(error.status, 409);
      assert.equal(error.isLegacyArtifactMissing, true);
      assert.equal(error.detail.sampleSubstituted, false, "the sample must never be substituted");
      assert.equal(error.detail.recovery.length, 2, "recovery actions must be offered so the user never dead-ends");
      return true;
    }
  );
  assert.match(step01, /data-testid="legacy-artifact-missing"/, "the UI must distinguish a legacy version");
  assert.match(step01, /Legacy Dataset Version: Full Artifact Unavailable/);
});

// --- Root cause 4: a preview may not block the registered population -------

test("a preview with no events cannot create a registered-population blocker", () => {
  const quality = {
    profileScope: "preview_profile", profiledRowCount: 100, registeredRowCount: 170884, rowCount: 170884,
    duplicateRows: 1, missing: [], constantColumns: [], nearZeroVarianceColumns: [],
    unexpectedDatatypeColumns: [], potentialLeakageColumns: [], classBalance: { eventRate: 0, majorityClassPercent: 1 },
  };
  const previewScoped = lifecycle.computeReadinessStatus({
    quality, target: "Class", registeredRowCount: 170884, selectedPredictorCount: 30,
    profileScopeMode: "preview_only", authoritativeEventCount: 360,
  });
  assert.notEqual(previewScoped.status, "blocked", "a preview must not block a population with 360 events");
  assert.ok(
    previewScoped.reasons.some((reason) => /browser preview contains no event records/i.test(reason)),
    "the honest preview message must be shown instead"
  );
  assert.ok(
    !previewScoped.reasons.some((reason) => /no events in the registered population/i.test(reason)),
    "the false claim must not appear"
  );
});

test("a genuine population with zero events still blocks", () => {
  const quality = {
    profileScope: "full_dataset", profiledRowCount: 170884, registeredRowCount: 170884, rowCount: 170884,
    duplicateRows: 52, missing: [], constantColumns: [], nearZeroVarianceColumns: [],
    unexpectedDatatypeColumns: [], potentialLeakageColumns: [], classBalance: { eventRate: 0, majorityClassPercent: 1 },
  };
  const governed = lifecycle.computeReadinessStatus({
    quality, target: "Class", registeredRowCount: 170884, selectedPredictorCount: 30,
    profileScopeMode: "governed_version", authoritativeEventCount: 0,
  });
  assert.equal(governed.status, "blocked");
  assert.ok(governed.reasons.some((reason) => /no events in the registered population/i.test(reason)));
});

// --- Part H: weak-signal automation safety ---------------------------------

function profileWith(predictors, mode = "governed_version") {
  return {
    analysisScope: { mode },
    predictors,
    predictorSummary: { total: predictors.length, evaluated: predictors.filter((p) => p.ivStatus === "available").length, unavailable: 0, failed: 0, leakageReview: 0 },
  };
}

test("weak-signal exclusion is disabled while profiling is pending", () => {
  const plan = lib.planWeakSignalExclusion({
    profile: null, loading: true, error: null, problemType: "classification", selected: ["a"],
  });
  assert.equal(plan.eligible, false);
  assert.match(plan.blockedReason, /still running/i);
});

test("weak-signal exclusion is disabled for a preview-only profile", () => {
  const plan = lib.planWeakSignalExclusion({
    profile: profileWith([{ predictor: "a", eligible: true, iv: null, ivStatus: "preview_only" }], "preview_only"),
    loading: false, error: null, problemType: "classification", selected: ["a"],
  });
  assert.equal(plan.eligible, false);
  assert.match(plan.blockedReason, /browser-preview only/i);
});

test("weak-signal exclusion is disabled when the profile failed", () => {
  const plan = lib.planWeakSignalExclusion({
    profile: null, loading: false, error: "boom", problemType: "classification", selected: ["a"],
  });
  assert.equal(plan.eligible, false);
  assert.match(plan.blockedReason, /profiling failed/i);
});

test("an unavailable IV never deselects a predictor", () => {
  const plan = lib.planWeakSignalExclusion({
    profile: profileWith([
      { predictor: "genuinely_weak", eligible: true, iv: 0.002, ivStatus: "available" },
      { predictor: "unavailable", eligible: true, iv: null, ivStatus: "unavailable_no_events" },
      { predictor: "failed", eligible: true, iv: null, ivStatus: "failed" },
      { predictor: "strong", eligible: true, iv: 0.9, ivStatus: "available" },
    ]),
    loading: false, error: null, problemType: "classification",
    selected: ["genuinely_weak", "unavailable", "failed", "strong"],
  });
  assert.equal(plan.eligible, true);
  assert.deepEqual(plan.affected, ["genuinely_weak"], "only a computed, genuinely weak IV may be removed");
  assert.deepEqual(plan.protectedFromRemoval.sort(), ["failed", "unavailable"]);
  assert.equal(plan.threshold, lib.WEAK_SIGNAL_IV_THRESHOLD);
  assert.equal(plan.threshold, 0.01, "the configured ATLAS threshold stays 0.01, not the descriptive 0.02 band");
});

test("the weak-signal action requires explicit confirmation, shows the count, and can be undone", () => {
  assert.match(step01, /data-testid="weak-signal-apply"/, "an explicit apply action must exist");
  assert.match(step01, /Apply to \{weakSignalPlan\.affected\.length\} predictor\(s\)/, "the affected count must be shown first");
  assert.match(step01, /data-testid="weak-signal-undo"/, "undo must be available");
  assert.match(step01, /data-testid="weak-signal-blocked-reason"/, "the blocked reason must be visible text");
  // Toggling no longer applies the filter as a side effect.
  assert.doesNotMatch(step01, /if \(event\.target\.checked\) applyWeakSignalFilter\(\);/);
  // Comment lines are stripped: the module documents the old defect by name.
  const executable = step01
    .split(String.fromCharCode(10))
    .filter((line) => !line.trim().startsWith("//"))
    .join(" ");
  assert.doesNotMatch(executable, /Number\(row\.iv\)/, "null IV must never be coerced for a threshold comparison");
});

test("the weak-signal decision records the full profile identity", () => {
  const block = step01.slice(step01.indexOf("function applyWeakSignalFilter"), step01.indexOf("function undoWeakSignalFilter"));
  for (const field of ["scopeMode", "datasetId", "datasetVersionId", "target", "eventValue", "nonEventValue", "calculationVersion", "affected"]) {
    assert.ok(block.includes(field), `the decision journal entry must record ${field}`);
  }
});

// --- Part I: Atlas Guide precision -----------------------------------------

test("a rare event rate never renders as 0.00%", () => {
  assert.equal(lib.formatEventRatePrecise(360 / 170884), "0.2107%");
  assert.notEqual(lib.formatEventRatePrecise(360 / 170884), "0.00%");
  assert.equal(lib.formatEventRatePrecise(0), "0%");
  assert.equal(lib.formatEventRatePrecise(null), "Not available");
  assert.equal(lib.formatEventRatePrecise(0.5), "50.00%");
  // Progressively more digits below 1%.
  assert.match(lib.formatEventRatePrecise(0.00002), /e-|0\.00200%|0\.002%/);
  assert.ok(!lib.formatEventRatePrecise(0.000001).startsWith("0.00%"));
});

test("Data Acquisition exposes backend-authoritative event evidence rather than preview-derived counts", () => {
  assert.match(step01, /authoritativeEventCount: governedProfile\.profile\?\.quality\.eventCount \?\? governedProfile\.quality\?\.quality\.eventCount \?\? null/);
  assert.match(step01, /governedProfile\.quality\?\.quality\.eventRate \?\? governedProfile\.profile\?\.quality\.eventRate/,
    "the governed profile must be preferred over any preview-derived event rate");
});

// --- Part J: Target Intelligence correction ---------------------------------

test("Governed Definitions is removed but Analysis Scope and Target Identity remain", async () => {
  const banner = await readFile(new URL("src/components/eda/AnalysisScopeBanner.tsx", ROOT), "utf8");
  assert.match(banner, /data-testid="analysis-scope-banner"/, "the banner component must still exist");
  assert.doesNotMatch(workspace, /data-testid="target-governance-definitions"/, "the redundant section must be gone");
  assert.doesNotMatch(workspace, /Governed definitions/);
  assert.doesNotMatch(workspace, /View full governance definition/);
  // Preserved.
  assert.match(workspace, /<AnalysisScopeBanner/, "the Analysis Scope banner must still be rendered");
  assert.match(workspace, /data-testid="target-identity"/, "Target Identity must remain");
  for (const testId of ["target-identity-column", "target-positive-value", "target-identity-missing", "target-identity-rows", "target-identity-dataset-id", "target-identity-version"]) {
    assert.ok(workspace.includes(`"${testId}"`), `${testId} must remain`);
  }
  // Replaced with a compact, keyboard-reachable link (an anchor, not a div).
  assert.match(workspace, /data-testid="target-view-project-context"/);
  assert.match(workspace, /<Link[\s\S]{0,200}to=\{projectWorkflowRoute\(projectId, "\/step00"\)\}[\s\S]{0,200}data-testid="target-view-project-context"/);
});

test("the phase registers its test script and adds no console noise", async () => {
  // Scoped to the modules this phase authored. Step01 carries pre-existing
  // console calls that are out of scope here and are left untouched.
  const profileLib = await readFile(new URL("src/lib/governedProfile.ts", ROOT), "utf8");
  for (const source of [profileLib, hook]) {
    assert.doesNotMatch(source, /console\.(log|warn|error|debug)\(/);
  }
  assert.equal(
    packageJson.scripts["test:governed-profile"],
    "node tests/governedProfile.test.mjs && .\\.venv\\Scripts\\python.exe tests\\governed_profile_test.py"
  );
});

// ---------------------------------------- signal strength vs leakage (Part H) ---
test("automated leakage evidence is independent of IV", () => {
  // PROVEN DEFECT: leakageScreen returned "review_recommended" whenever
  // iv >= 0.5, so association strength WAS the leakage verdict -- flagging ~23
  // of 30 governed CLASS_TRAIN predictors purely because the PCA components
  // separate the target well. An independent reference implementation confirmed
  // that separation is real signal, not leakage.
  const strong = { iv: 3.28, ivStatus: "available", role: "predictor", eligible: true };
  assert.equal(lib.leakageScreen(strong), "no_automated_signal",
    "a high IV alone must NOT produce a leakage state");
  // ...but it is still surfaced for human review through signal strength.
  const strength = lib.signalStrength(strong);
  assert.equal(strength.key, "unusually_strong");
  assert.equal(strength.reviewRecommended, true);

  // Real evidence -- from server-side checks, not from IV -- still flags.
  assert.equal(
    lib.leakageScreen({ iv: 0.01, ivStatus: "available", role: "potential_leakage", eligible: true }),
    "review_recommended",
    "actual leakage evidence must still be reported",
  );
  // A weak predictor with no evidence is clean.
  assert.equal(
    lib.leakageScreen({ iv: 0.01, ivStatus: "available", role: "predictor", eligible: true }),
    "no_automated_signal",
  );
  // High IV never escalates to a confirmed verdict.
  for (const iv of [0.5, 1.5, 3.6, 99]) {
    const state = lib.leakageScreen({ iv, ivStatus: "available", role: "predictor", eligible: true });
    assert.notEqual(state, "confirmed_leakage");
    assert.notEqual(state, "likely_leakage");
  }
});

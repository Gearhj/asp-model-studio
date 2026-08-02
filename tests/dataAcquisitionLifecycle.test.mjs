// UX-DATAACQ-001..004 + Parts F/H1/H3: unit tests for the Data Acquisition
// lifecycle decisions. These call the real exported functions (transpiled from
// TypeScript, the same approach tests/dataAcquisition.test.mjs uses) rather than
// pattern-matching rendered source, so the persistence/readiness/event-rate
// logic is verified behaviorally.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/data-acquisition-lifecycle-tests", import.meta.url));

async function transpileSource(sourcePath, outputPath) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, output, "utf8");
}

async function compile() {
  await rm(TMP_DIR, { recursive: true, force: true });
  await transpileSource("src/lib/dataAcquisitionLifecycle.ts", path.join(TMP_DIR, "dataAcquisitionLifecycle.js"));
  return import(pathToFileURL(path.join(TMP_DIR, "dataAcquisitionLifecycle.js")).href);
}

const lib = await compile();

const LIBRARY_LINK = { datasetId: "ds-class-train", versionId: "v-2026-01-01", datasetName: "CLASS_TRAIN" };

function baseQuality(overrides = {}) {
  return {
    profileScope: "full_dataset",
    profiledRowCount: 170884,
    registeredRowCount: 170884,
    rowCount: 170884,
    columnCount: 31,
    duplicateRows: 0,
    duplicateIdCandidates: [],
    constantColumns: [],
    nearZeroVarianceColumns: [],
    highCardinalityCategoricals: [],
    unexpectedDatatypeColumns: [],
    potentialLeakageColumns: [],
    outlierPrevalence: [],
    dateRanges: [],
    missing: [],
    memoryEstimateMb: 42,
    ...overrides,
  };
}

// --- Part C: source-aware persistence -------------------------------------

test("a Dataset Library version resolves to Existing Library Version and a read-only status panel", () => {
  const kind = lib.resolveDatasetSourceKind({ sourceType: "existing", libraryLink: LIBRARY_LINK });
  assert.equal(kind, "existing-library-version");
  assert.equal(lib.resolvePersistenceMode(kind), "registered-status");
  assert.equal(lib.DATASET_SOURCE_LABELS[kind], "Existing Library Version");
});

test("a new unregistered upload keeps the workspace-vs-register choice", () => {
  const kind = lib.resolveDatasetSourceKind({ sourceType: "upload", libraryLink: null });
  assert.equal(kind, "workspace-upload");
  assert.equal(lib.resolvePersistenceMode(kind), "choice");
});

test("an unregistered SQL/cloud/python import is labelled Imported Unregistered Data and keeps the choice", () => {
  for (const sourceType of ["sql", "cloud", "python"]) {
    const kind = lib.resolveDatasetSourceKind({ sourceType, libraryLink: null });
    assert.equal(kind, "imported-unregistered", `${sourceType} without a registered asset`);
    assert.equal(lib.resolvePersistenceMode(kind), "choice");
  }
});

test("an import that resolves to a registered asset shows the registered status panel instead of the choice", () => {
  const kind = lib.resolveDatasetSourceKind({ sourceType: "sql", libraryLink: LIBRARY_LINK });
  assert.equal(kind, "registered-library-asset");
  assert.equal(lib.resolvePersistenceMode(kind), "registered-status");
});

test("derived and scored datasets are distinct states with their own persistence mode", () => {
  const derived = lib.resolveDatasetSourceKind({ sourceType: "upload", libraryLink: LIBRARY_LINK, isDerived: true });
  assert.equal(derived, "derived-dataset");
  assert.equal(lib.resolvePersistenceMode(derived), "derived-choice");

  const scored = lib.resolveDatasetSourceKind({ sourceType: "upload", libraryLink: LIBRARY_LINK, isScored: true });
  assert.equal(scored, "scored-dataset");
  assert.equal(lib.resolvePersistenceMode(scored), "derived-choice");
});

test("derived registration never uses overwrite language and distinguishes new asset from new version", () => {
  assert.equal(lib.resolveRegistrationActionLabel("derived-dataset", false), "Register Derived Dataset");
  assert.equal(lib.resolveRegistrationActionLabel("derived-dataset", true), "Register as New Dataset Version");
  assert.equal(lib.resolveRegistrationActionLabel("scored-dataset", false), "Register Scored Dataset");
  assert.equal(lib.resolveRegistrationActionLabel("workspace-upload", false), "Register Development Dataset");
  for (const kind of ["derived-dataset", "scored-dataset", "workspace-upload"]) {
    for (const hasAsset of [true, false]) {
      assert.doesNotMatch(lib.resolveRegistrationActionLabel(kind, hasAsset), /overwrit/i);
    }
  }
});

test("an identical dataset/version is reported as already linked and a different one is not", () => {
  assert.equal(lib.isAlreadyLinked(LIBRARY_LINK, { datasetId: "ds-class-train", versionId: "v-2026-01-01" }), true);
  assert.equal(lib.isAlreadyLinked(LIBRARY_LINK, { datasetId: "ds-class-train", versionId: "v-2026-06-01" }), false);
  assert.equal(lib.isAlreadyLinked(LIBRARY_LINK, { datasetId: "ds-other", versionId: "v-2026-01-01" }), false);
  assert.equal(lib.isAlreadyLinked(null, { datasetId: "ds-class-train", versionId: "v-2026-01-01" }), false);
});

test("every source kind has a distinct user-facing label", () => {
  const labels = Object.values(lib.DATASET_SOURCE_LABELS);
  assert.equal(labels.length, 6);
  assert.equal(new Set(labels).size, 6);
  for (const expected of [
    "Workspace Upload",
    "Registered Dataset Library Asset",
    "Existing Library Version",
    "Derived Dataset",
    "Scored Dataset",
    "Imported Unregistered Data",
  ]) {
    assert.ok(labels.includes(expected), `missing source label: ${expected}`);
  }
});

// --- Part D: readiness status from existing findings only ------------------

test("a clean full-dataset profile is Ready", () => {
  const result = lib.computeReadinessStatus({
    quality: baseQuality({ classBalance: { eventRate: 0.0021, majorityClassPercent: 0.9979 } }),
    target: "Class",
    registeredRowCount: 170884,
    selectedPredictorCount: 29,
  });
  // A rare-event rate is a warning, not a blocker.
  assert.equal(result.status, "ready_with_warnings");
  assert.match(result.reasons.join(" "), /Rare-event target: 0\.21%/);
});

test("duplicates and missingness produce Ready with Warnings, not Review Required", () => {
  const result = lib.computeReadinessStatus({
    quality: baseQuality({ duplicateRows: 52, missing: [{ column: "V1", percent: 0.02 }] }),
    target: "Class",
    registeredRowCount: 170884,
    selectedPredictorCount: 29,
  });
  assert.equal(result.status, "ready_with_warnings");
  assert.match(result.reasons.join(" "), /52 duplicate row/);
  assert.match(result.reasons.join(" "), /1 column\(s\) contain missing values/);
});

test("leakage candidates escalate to Review Required", () => {
  const result = lib.computeReadinessStatus({
    quality: baseQuality({ potentialLeakageColumns: ["future_chargeback_flag"] }),
    target: "Class",
    registeredRowCount: 170884,
    selectedPredictorCount: 29,
  });
  assert.equal(result.status, "review_required");
});

test("a preview-only profile escalates to Review Required", () => {
  const result = lib.computeReadinessStatus({
    quality: baseQuality({ profileScope: "preview_profile", profiledRowCount: 100 }),
    target: "Class",
    registeredRowCount: 170884,
    selectedPredictorCount: 29,
  });
  assert.equal(result.status, "review_required");
  assert.match(result.reasons.join(" "), /preview profile/i);
});

test("only genuine blockers are Blocked", () => {
  const ready = { quality: baseQuality(), target: "Class", registeredRowCount: 170884, selectedPredictorCount: 29 };
  assert.equal(lib.computeReadinessStatus({ ...ready, quality: null }).status, "blocked");
  assert.equal(lib.computeReadinessStatus({ ...ready, registeredRowCount: 0 }).status, "blocked");
  assert.equal(lib.computeReadinessStatus({ ...ready, target: "" }).status, "blocked");
  assert.equal(lib.computeReadinessStatus({ ...ready, selectedPredictorCount: 0 }).status, "blocked");
  assert.equal(
    lib.computeReadinessStatus({ ...ready, quality: baseQuality({ classBalance: { eventRate: 0, majorityClassPercent: 1 } }) }).status,
    "blocked"
  );
});

test("readiness labels and tones cover every status with red reserved for blocked", () => {
  for (const status of ["ready", "ready_with_warnings", "review_required", "blocked"]) {
    assert.ok(lib.READINESS_LABELS[status], `missing label for ${status}`);
    assert.ok(lib.READINESS_TONES[status], `missing tone for ${status}`);
  }
  assert.equal(lib.READINESS_LABELS.ready_with_warnings, "Ready with Warnings");
  assert.equal(lib.READINESS_TONES.ready, "success");
  assert.equal(lib.READINESS_TONES.blocked, "danger");
  assert.notEqual(lib.READINESS_TONES.ready_with_warnings, "danger");
  assert.notEqual(lib.READINESS_TONES.review_required, "danger");
});

// --- Part F: authoritative event rate ------------------------------------

test("a rare event rate is never rounded down to zero", () => {
  assert.equal(lib.formatEventRate(0.0021), "0.21%");
  assert.equal(lib.formatEventRate(0.001), "0.10%");
  assert.equal(lib.formatEventRate(0.00021), "0.021%");
  assert.equal(lib.formatEventRate(0.000021), "0.0021%");
  assert.doesNotMatch(lib.formatEventRate(0.0000021), /^0\.00%$/);
  assert.equal(lib.formatEventRate(0), "0%");
  assert.equal(lib.formatEventRate(null), "Not evaluated");
  assert.equal(lib.formatEventRate(undefined), "Not evaluated");
});

test("the backend full-dataset profile wins over the browser preview rate", () => {
  const resolved = lib.resolveAuthoritativeEventRate({
    quality: baseQuality({ classBalance: { eventRate: 0.0021, majorityClassPercent: 0.9979 } }),
    previewEventRate: 0, // 100-row preview contains no events
    completeBrowserDataset: false,
  });
  assert.equal(resolved.rate, 0.0021);
  assert.equal(resolved.scope, "full_population");
  assert.equal(resolved.isAuthoritative, true);
  assert.equal(lib.formatEventRate(resolved.rate), "0.21%");
});

test("a preview-derived rate is returned only when explicitly scoped Preview only", () => {
  const resolved = lib.resolveAuthoritativeEventRate({
    quality: baseQuality({ profileScope: "preview_profile", classBalance: { eventRate: 0, majorityClassPercent: 1 } }),
    previewEventRate: 0,
    completeBrowserDataset: false,
  });
  assert.equal(resolved.scope, "preview_only");
  assert.equal(resolved.isAuthoritative, false);
  assert.equal(lib.EVENT_RATE_SCOPE_LABELS[resolved.scope], "Preview only");
});

test("a complete browser dataset is authoritative for its own rate", () => {
  const resolved = lib.resolveAuthoritativeEventRate({
    quality: baseQuality({ profileScope: "complete_browser_dataset" }),
    previewEventRate: 0.25,
    completeBrowserDataset: true,
  });
  assert.equal(resolved.rate, 0.25);
  assert.equal(resolved.scope, "complete_browser_dataset");
  assert.equal(resolved.isAuthoritative, true);
});

// --- Part H1: load milestones --------------------------------------------

test("the seven real load milestones are exposed in order", () => {
  assert.deepEqual([...lib.DATASET_LOAD_STAGES], [
    "Authorizing dataset access",
    "Resolving dataset version",
    "Reading governed schema",
    "Profiling target and predictors",
    "Evaluating data quality",
    "Preparing browser preview",
    "Ready for modeling",
  ]);
});

test("stage states progress from pending through active to complete", () => {
  assert.deepEqual(lib.resolveStageStates(lib.IDLE_LOAD_PROGRESS), Array(7).fill("pending"));

  const midway = lib.resolveStageStates({ phase: "loading", activeStageIndex: 2, failedStageIndex: null, error: null });
  assert.deepEqual(midway.slice(0, 2), ["complete", "complete"]);
  assert.equal(midway[2], "active");
  assert.deepEqual(midway.slice(3), Array(4).fill("pending"));

  assert.deepEqual(
    lib.resolveStageStates({ phase: "loaded", activeStageIndex: 6, failedStageIndex: null, error: null }),
    Array(7).fill("complete")
  );
});

test("a failure preserves completed milestones and never reports completion", () => {
  const states = lib.resolveStageStates({ phase: "failed", activeStageIndex: 3, failedStageIndex: 3, error: "boom" });
  assert.deepEqual(states.slice(0, 3), ["complete", "complete", "complete"]);
  assert.equal(states[3], "failed");
  assert.deepEqual(states.slice(4), Array(3).fill("pending"));
  assert.equal(states.filter((state) => state === "complete").length, 3);

  const summary = lib.summarizeLoadProgress({ phase: "failed", activeStageIndex: 3, failedStageIndex: 3, error: "boom" });
  assert.match(summary.label, /Failed at Profiling target and predictors/);
  assert.notEqual(summary.completed, summary.total);
});

test("progress is reported as discrete milestones, never a synthetic percentage", () => {
  const summary = lib.summarizeLoadProgress({ phase: "loading", activeStageIndex: 4, failedStageIndex: null, error: null });
  assert.equal(summary.total, 7);
  assert.equal(summary.completed, 4);
  assert.doesNotMatch(summary.label, /%/);
  assert.equal(lib.summarizeLoadProgress(lib.IDLE_LOAD_PROGRESS).label, "Not started");
  assert.equal(
    lib.summarizeLoadProgress({ phase: "loaded", activeStageIndex: 6, failedStageIndex: null, error: null }).label,
    "7 of 7 milestones complete"
  );
});

// --- Part H3: target distribution ---------------------------------------

const CLASS_TRAIN_DISTRIBUTION = [
  { value: "0", count: 170525, percent: 170525 / 170884 },
  { value: "1", count: 359, percent: 359 / 170884 },
];

test("the target distribution is folded from authoritative full-population counts", () => {
  const distribution = lib.buildTargetDistribution({
    target: "Class",
    classDistribution: CLASS_TRAIN_DISTRIBUTION,
    eventValue: "1",
  });
  assert.equal(distribution.eventCount, 359);
  assert.equal(distribution.nonEventCount, 170525);
  assert.equal(distribution.totalRows, 170884);
  assert.equal(lib.formatEventRate(distribution.eventPercent), "0.21%");
  assert.equal(lib.formatEventRate(distribution.nonEventPercent), "99.79%");
  assert.equal(distribution.isRareEvent, true);
  assert.ok(distribution.imbalanceRatio > 400 && distribution.imbalanceRatio < 500);
});

test("without an explicit event value the minority class is treated as the event", () => {
  const distribution = lib.buildTargetDistribution({
    target: "Class",
    classDistribution: CLASS_TRAIN_DISTRIBUTION,
    eventValue: null,
  });
  assert.equal(distribution.eventValue, "1");
  assert.equal(distribution.eventCount, 359);
});

test("multi-class encodings aggregate every non-event class instead of dropping rows", () => {
  const distribution = lib.buildTargetDistribution({
    target: "Status",
    classDistribution: [
      { value: "fraud", count: 100, percent: 0.01 },
      { value: "clean", count: 8000, percent: 0.8 },
      { value: "unknown", count: 1900, percent: 0.19 },
    ],
    eventValue: "fraud",
  });
  assert.equal(distribution.eventCount, 100);
  assert.equal(distribution.nonEventCount, 9900);
  assert.equal(distribution.eventCount + distribution.nonEventCount, distribution.totalRows);
});

test("a distribution without at least two classes is unavailable rather than misleading", () => {
  assert.equal(lib.buildTargetDistribution({ target: "Class", classDistribution: null, eventValue: "1" }), null);
  assert.equal(lib.buildTargetDistribution({ target: "", classDistribution: CLASS_TRAIN_DISTRIBUTION, eventValue: "1" }), null);
  assert.equal(
    lib.buildTargetDistribution({ target: "Class", classDistribution: [{ value: "0", count: 10, percent: 1 }], eventValue: "1" }),
    null
  );
});

test("class counts can be computed from a complete in-memory dataset", () => {
  const rows = [
    ...Array.from({ length: 997 }, () => ({ Class: "0" })),
    ...Array.from({ length: 3 }, () => ({ Class: "1" })),
    { Class: "" }, // blank target values are excluded, not counted as a class
  ];
  const distribution = lib.computeClassDistributionFromRows(rows, "Class");
  assert.equal(distribution.length, 2);
  assert.equal(distribution.find((row) => row.value === "1").count, 3);
  assert.equal(distribution.find((row) => row.value === "0").count, 997);

  const folded = lib.buildTargetDistribution({ target: "Class", classDistribution: distribution, eventValue: "1" });
  assert.equal(folded.totalRows, 1000);
  assert.equal(lib.formatEventRate(folded.eventPercent), "0.30%");
});

test("class counts are unavailable for degenerate or high-cardinality targets", () => {
  assert.equal(lib.computeClassDistributionFromRows([], "Class"), null);
  assert.equal(lib.computeClassDistributionFromRows([{ Class: "1" }], ""), null);
  assert.equal(lib.computeClassDistributionFromRows([{ Class: "1" }, { Class: "1" }], "Class"), null);
  const highCardinality = Array.from({ length: 50 }, (_unused, index) => ({ Class: `value-${index}` }));
  assert.equal(lib.computeClassDistributionFromRows(highCardinality, "Class"), null);
});

test("the rare-event view is only offered for genuinely unreadable minority classes, and discloses its scale", () => {
  const rare = lib.buildTargetDistribution({ target: "Class", classDistribution: CLASS_TRAIN_DISTRIBUTION, eventValue: "1" });
  assert.equal(lib.shouldOfferRareEventView(rare), true);

  const balanced = lib.buildTargetDistribution({
    target: "Class",
    classDistribution: [{ value: "0", count: 600, percent: 0.6 }, { value: "1", count: 400, percent: 0.4 }],
    eventValue: "1",
  });
  assert.equal(lib.shouldOfferRareEventView(balanced), false);
  assert.equal(lib.shouldOfferRareEventView(null), false);

  assert.match(lib.RARE_EVENT_SCALE_DISCLOSURE, /do not represent true relative magnitude/);
  assert.match(lib.RARE_EVENT_TAKEAWAY, /PR-AUC/);
  assert.match(lib.RARE_EVENT_TAKEAWAY, /Accuracy may be misleading/);
});

test("the accessible summary reports the same values the chart plots", () => {
  const distribution = lib.buildTargetDistribution({
    target: "Class",
    classDistribution: CLASS_TRAIN_DISTRIBUTION,
    eventValue: "1",
  });
  const summary = lib.describeTargetDistribution(distribution);
  assert.match(summary, /Target Class/);
  assert.match(summary, /359 rows/);
  assert.match(summary, /0\.21%/);
  assert.match(summary, /170,525 rows/);
  assert.match(summary, /99\.79%/);
  assert.match(summary, /Total rows 170,884/);
  assert.equal(lib.describeTargetDistribution(null), "Target distribution is not available.");
});

test("browser restoration probes durable identity without automatically activating it", async () => {
  const source = await readFile(
    new URL("src/steps/Step01_DataAcquisition.tsx", ROOT),
    "utf8",
  );
  const start = source.indexOf("const restoreExactIdentity = async () =>");
  const end = source.indexOf("void restoreExactIdentity();", start);
  assert.notEqual(start, -1, "missing exact identity restoration flow");
  assert.notEqual(end, -1, "missing exact identity restoration invocation");
  const restore = source.slice(start, end);

  assert.match(restore, /fetch\([\s\S]*?\/data\/active-identity\?project_id=/);
  assert.doesNotMatch(
    restore,
    /activateDatasetVersion\(/,
    "browser cache restoration must never change durable active selection",
  );
  assert.doesNotMatch(restore, /linkDatasetToProject\(/);
  assert.match(restore, /setReactivationRequired\(true\)/);
  assert.match(restore, /Reactivate it explicitly below/);
});

test("explicit Load performs one combined durable project-link activation", async () => {
  const source = await readFile(
    new URL("src/steps/Step01_DataAcquisition.tsx", ROOT),
    "utf8",
  );
  const start = source.indexOf("onLoad={async () => {");
  const end = source.indexOf("\n    />", start);
  assert.notEqual(start, -1, "missing explicit Dataset Library load action");
  assert.ok(end > start, "missing explicit Dataset Library load action boundary");
  const load = source.slice(start, end);

  assert.equal(
    (load.match(/activateDatasetVersion\(/g) ?? []).length,
    1,
    "explicit Load must invoke the transactional link-and-activate command once",
  );
  assert.doesNotMatch(
    load,
    /linkDatasetToProject\(/,
    "explicit Load must not split project linking from active-version selection",
  );
  assert.match(
    load,
    /const activation = await activateDatasetVersion\(\s*selectedLibraryDatasetId,\s*selectedLibraryVersionId,\s*projectId\s*\)/,
  );
  assert.match(load, /const canonical = assertExactDatasetActivation\(/);
  assert.match(load, /activation\.activation_revision/);

  const activation = load.indexOf("await activateDatasetVersion(");
  const preview = load.indexOf("await getDatasetPreview(");
  const success = load.indexOf('phase: "loaded"');
  assert.ok(activation >= 0 && preview > activation);
  assert.ok(success > preview, "loaded success must follow durable activation and exact preview recovery");
});

test("target and predictor partial saves retain the existing canonical and profiling envelope", async () => {
  const source = await readFile(
    new URL("src/steps/Step01_DataAcquisition.tsx", ROOT),
    "utf8",
  );
  const selectionStart = source.indexOf(
    "function saveKeptSelection(nextKept:",
  );
  const selectionEnd = source.indexOf(
    "function applyWeakSignalFilter",
    selectionStart,
  );
  const targetStart = source.indexOf("const updateTarget = (next: string)");
  const targetEnd = source.indexOf(
    "// Debounced on registerName changes",
    targetStart,
  );
  assert.ok(selectionStart >= 0 && selectionEnd > selectionStart);
  assert.ok(targetStart >= 0 && targetEnd > targetStart);

  for (const [label, block] of [
    ["predictor selection", source.slice(selectionStart, selectionEnd)],
    ["target selection", source.slice(targetStart, targetEnd)],
  ]) {
    assert.match(block, /const currentDataset = loadLocalDataset\(\)/);
    assert.match(
      block,
      /saveLocalDataset\(\{\s*\.\.\.\(currentDataset \?\? \{\}\),/,
      `${label} must merge into the stored envelope instead of replacing it`,
    );
    assert.doesNotMatch(
      block,
      /dataset_id:\s*undefined|dataset_version_id:\s*undefined|data_access:\s*undefined|data_quality:\s*undefined/,
    );
  }
});

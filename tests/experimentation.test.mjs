import fs from "node:fs";
import assert from "node:assert/strict";
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const abLib = fs.readFileSync("src/lib/abTestingWorkflow.ts", "utf8");
const persistenceSource = fs.readFileSync("src/lib/abTestingWorkflowPersistence.ts", "utf8");
const workflows = fs.readFileSync("src/config/workflows.ts", "utf8");
const workflowPage = fs.readFileSync("src/steps/WorkflowPlaceholderStep.tsx", "utf8");
const stepShell = fs.readFileSync("src/components/StepShell.tsx", "utf8");
const overview = fs.readFileSync("src/steps/ProjectOverview.tsx", "utf8");
const packageJson = JSON.parse(fs.readFileSync("package.json", "utf8"));
const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/experimentation-tests", import.meta.url));

class MemoryStorage {
  constructor() {
    this.map = new Map();
  }
  get length() {
    return this.map.size;
  }
  clear() {
    this.map.clear();
  }
  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }
  key(index) {
    return Array.from(this.map.keys())[index] ?? null;
  }
  removeItem(key) {
    this.map.delete(key);
  }
  setItem(key, value) {
    this.map.set(String(key), String(value));
  }
}

const browserEvents = [];
globalThis.localStorage = new MemoryStorage();
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};
globalThis.window = {
  dispatchEvent(event) {
    browserEvents.push(event);
    return true;
  },
};

async function transpileSource(sourcePath, outputPath) {
  const source = fs.readFileSync(new URL(sourcePath, ROOT), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, output, "utf8");
}

await rm(TMP_DIR, { recursive: true, force: true });
await transpileSource("src/config/workflows.ts", path.join(TMP_DIR, "src/config/workflows.js"));
await transpileSource("src/lib/abTestingWorkflowPersistence.ts", path.join(TMP_DIR, "src/lib/abTestingWorkflowPersistence.js"));
const workflowConfig = await import(pathToFileURL(path.join(TMP_DIR, "src/config/workflows.js")).href);
const abPersistence = await import(pathToFileURL(path.join(TMP_DIR, "src/lib/abTestingWorkflowPersistence.js")).href);

assert.equal(packageJson.scripts["test:experimentation"], "node tests/experimentation.test.mjs");

for (const expected of [
  'dataset: "AB_MARKETING.csv"',
  'unitIdColumn: "user.id"',
  'treatmentColumn: "test.group"',
  'treatmentValue: "ad"',
  'controlValue: "psa"',
  'outcomeColumn: "converted"',
  'successEvent: "True"',
  'exposureColumn: "total.ads"',
  '"most.ads.day"',
  '"most.ads.hour"',
  "isSuccessOutcome",
  "summarizeAbGroups",
  "allocationImbalance",
  "analyzeAbLift",
  "segmentLiftRows",
  "decisionRecommendationReason",
]) {
  assert.match(abLib, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing A/B library artifact: ${expected}`);
}

for (const expected of [
  "saveAbTestingStep",
  "loadAbTestingStep",
  "atlas-workflow-node-state",
  "atlas-ab-testing-workflow-step",
  "workflowType: \"ab_testing\"",
  "stepRoute?: string",
  "compactAbTestingStepPayload",
  "compactCalculatedMetrics",
  "safeSetLocalStorage",
  "pruneAbTestingWorkflowStorage",
  "clearAbTestingWorkflowStorage",
  "AB_TESTING_MAX_PAYLOAD_BYTES",
]) {
  assert.match(persistenceSource, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing A/B persistence artifact: ${expected}`);
}

for (const expected of [
  "Treatment column defaults to",
  "Treatment value defaults to",
  "Control value defaults to",
  "Outcome column defaults to",
  "Experiment unit ID column",
  "Exposure column defaults to",
  "Segment columns include",
  "Allocation imbalance warning",
  "total.ads is exposure / intensity, not necessarily baseline covariate",
  "Control conversion rate",
  "Treatment conversion rate",
  "Absolute lift",
  "Relative lift",
  "Standard error",
  "Confidence interval",
  "P-value",
  "Segment analysis by most.ads.day and most.ads.hour",
  "Bonferroni correction",
  "Benjamini-Hochberg FDR",
  "It does not rely only on p-value",
  "Save Evidence",
  "Open Model Evidence Center",
  "Attach to Model Documentation Studio",
  "Export Experiment Evidence Pack",
  "Model Documentation Studio Mapping",
  "onComplete();",
  "return false;",
  "saveAbTestingStep(",
  "stateRef.current",
  "handleAbTestingMarkCompleteAndNext",
  "ab-testing-mark-complete-next",
  "A/B Testing Save Debug",
  "Emergency: Clear A/B Testing cached workflow state",
  "This should not be required during normal workflow use",
  "Payload size:",
  "Saved compact A/B Testing step",
  "reclaimWorkflowStorage();",
  "may not persist locally because",
  "None for current step.",
  "Last action:",
  "Navigating to ${nextRoute}",
  "A/B Testing workflow step saved.",
  "A/B Testing workflow step could not be saved.",
]) {
  assert.match(workflowPage, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing A/B workflow UI artifact: ${expected}`);
}

for (const expected of [
  "onNextClick?: React.MouseEventHandler<HTMLButtonElement>",
  "nextButtonTestId?: string",
  "nextStatusLine?: React.ReactNode",
  "nextDebugPanel?: React.ReactNode",
  'type="button"',
  "data-testid={nextButtonTestId}",
  "onClick={onNextClick ?? handleNext}",
]) {
  assert.match(stepShell, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing visible StepShell button artifact: ${expected}`);
}

for (const expected of [
  "Experiment Name",
  "Treatment Sample Size",
  "Control Sample Size",
  "Treatment Conversion Rate",
  "Control Conversion Rate",
  "Absolute Lift",
  "Relative Lift",
  "Decision recommendation",
]) {
  assert.match(overview, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing A/B overview artifact: ${expected}`);
}

const workflowRoutes = workflowConfig.getWorkflowDefinition("ab-testing").steps.map((step) => step.route);
assert.deepEqual(workflowRoutes.slice(0, 15), [
  "/workflow/ab-testing/1",
  "/workflow/ab-testing/2",
  "/workflow/ab-testing/3",
  "/workflow/ab-testing/4",
  "/workflow/ab-testing/5",
  "/workflow/ab-testing/6",
  "/workflow/ab-testing/7",
  "/workflow/ab-testing/8",
  "/workflow/ab-testing/9",
  "/workflow/ab-testing/10",
  "/workflow/ab-testing/11",
  "/workflow/ab-testing/12",
  "/workflow/ab-testing/13",
  "/workflow/ab-testing/14",
  "/workflow/ab-testing/15",
]);

const persistenceCases = [
  ["ab-testing-1", "objective", "SAVE_TEST_PROJECT_CONTEXT_123", "/workflow/ab-testing/2"],
  ["ab-testing-2", "objective", "SAVE_TEST_EXPERIMENT_SETUP_123", "/workflow/ab-testing/3"],
  ["ab-testing-3", "objective", "SAVE_TEST_POPULATION_ELIGIBILITY_123", "/workflow/ab-testing/4"],
  ["ab-testing-4", "objective", "SAVE_TEST_TREATMENT_CONTROL_123", "/workflow/ab-testing/5"],
];

for (const [stepId, field, value, nextRoute] of persistenceCases) {
  localStorage.setItem(`atlas-ab-testing-workflow-step:ab-persistence-test:${stepId}`, JSON.stringify({ datasetRows: Array.from({ length: 1000 }, () => ({ stale: true })) }));
  localStorage.setItem(`atlas-workflow-node-state:ab-persistence-test:${stepId}`, JSON.stringify({ previewRows: Array.from({ length: 1000 }, () => ({ stale: true })) }));
  const formValues = {
    objective: "",
    inputs: "",
    assumptions: "",
    validation: "",
    risks: "",
    decision: "",
    rationale: "",
    notes: "",
    numeric: {},
    [field]: value,
  };
  const result = abPersistence.saveAbTestingStep({
    projectId: "ab-persistence-test",
    workflowType: "ab_testing",
    stepId,
    stepSlug: stepId,
    stepNumber: Number(stepId.replace("ab-testing-", "")),
    stepRoute: `/workflow/ab-testing/${stepId.replace("ab-testing-", "")}`,
    formValues: {
      ...formValues,
      analysisSnapshot: { huge: "x".repeat(150000) },
      simulationResults: { powerByIteration: Array.from({ length: 1000 }, (_, index) => ({ index })) },
      previewRows: Array.from({ length: 100 }, () => ({ shouldNotPersist: true })),
    },
    calculatedMetrics: {
      nextRoute,
      datasetRows: Array.from({ length: 100 }, () => ({ shouldNotPersist: true })),
      previewRows: [{ shouldNotPersist: true }],
      variableSummaryTable: [{ shouldNotPersist: true }],
      downstreamSections: [{ shouldNotPersist: true }],
      route: `/workflow/ab-testing/${stepId.replace("ab-testing-", "")}`,
    },
    reviewerNotes: "reviewer note",
    evidenceStatus: "saved",
    completed: true,
    updatedAt: "2026-07-11T00:00:00.000Z",
  });
  const reloaded = abPersistence.loadAbTestingStep("ab-persistence-test", stepId);
  assert.equal(reloaded[field], value, `${stepId} must restore typed text after remount or reload.`);
  assert.equal(JSON.parse(localStorage.getItem(result.workflowNodeStorageKey))[field], value, `${stepId} must save typed text to workflow-node storage.`);
  const auditPayload = JSON.parse(localStorage.getItem(result.auditStorageKey));
  assert.equal(auditPayload.formValues[field], value, `${stepId} must save typed text to the A/B audit key.`);
  assert.equal(auditPayload.completed, true);
  assert.equal(auditPayload.workflowType, "ab_testing");
  assert.equal(auditPayload.stepNumber, Number(stepId.replace("ab-testing-", "")));
  assert.equal(auditPayload.formValues.analysisSnapshot, undefined, `${stepId} must not save analysis snapshots.`);
  assert.equal(auditPayload.formValues.simulationResults, undefined, `${stepId} must not save simulation results.`);
  assert.equal(auditPayload.formValues.previewRows, undefined, `${stepId} must not save preview rows.`);
  assert.equal(auditPayload.calculatedMetrics.datasetRows, undefined, `${stepId} must not save dataset rows.`);
  assert.equal(auditPayload.calculatedMetrics.previewRows, undefined, `${stepId} must not save preview rows.`);
  assert.equal(auditPayload.calculatedMetrics.variableSummaryTable, undefined, `${stepId} must not save variable summaries.`);
  assert.equal(auditPayload.calculatedMetrics.downstreamSections, undefined, `${stepId} must not save downstream sections.`);
  assert.equal(result.payloadBytes < abPersistence.AB_TESTING_MAX_PAYLOAD_BYTES, true, `${stepId} payload must be under 100 KB.`);
  assert.equal(result.browserCacheWritten, true, `${stepId} compact browser cache should write successfully.`);
  assert.equal(result.prunedKeys.some((key) => key.endsWith(`:${stepId}`)), true, `${stepId} must automatically prune stale current-step A/B cache before saving.`);
  assert.equal(result.retriedAfterQuota, false);
}

class QuotaOnceStorage extends MemoryStorage {
  constructor() {
    super();
    this.remainingFailures = 1;
  }
  setItem(key, value) {
    if (this.remainingFailures > 0) {
      this.remainingFailures -= 1;
      const error = new Error("quota forced once");
      error.name = "QuotaExceededError";
      throw error;
    }
    super.setItem(key, value);
  }
}

const quotaOnceStorage = new QuotaOnceStorage();
quotaOnceStorage.remainingFailures = 0;
quotaOnceStorage.setItem("atlas-ab-testing-workflow-step:ab-persistence-test:ab-testing-stale", "x".repeat(120000));
quotaOnceStorage.remainingFailures = 1;
const quotaRetryResult = abPersistence.saveAbTestingStep({
  projectId: "ab-persistence-test",
  workflowType: "ab_testing",
  stepId: "ab-testing-1",
  stepSlug: "ab-testing-1",
  stepNumber: 1,
  formValues: { objective: "SAVE_TEST_PROJECT_CONTEXT_123" },
  completed: true,
}, quotaOnceStorage);
assert.equal(quotaRetryResult.browserCacheWritten, true, "A/B save must retry after quota and succeed when pruning frees space.");
assert.equal(quotaRetryResult.retriedAfterQuota, true, "A/B save must report quota retry.");
assert.equal(quotaRetryResult.prunedKeys.some((key) => key.includes("ab-testing-stale")), true, "Quota retry must aggressively prune stale A/B keys.");
assert.equal(JSON.parse(quotaOnceStorage.getItem(quotaRetryResult.workflowNodeStorageKey)).objective, "SAVE_TEST_PROJECT_CONTEXT_123");

const failingStorage = {
  length: 0,
  getItem() {
    return null;
  },
  key() {
    return null;
  },
  removeItem() {},
  setItem() {
    const error = new Error("quota forced");
    error.name = "QuotaExceededError";
    throw error;
  },
};
const quotaResult = abPersistence.saveAbTestingStep({
  projectId: "ab-persistence-test",
  workflowType: "ab_testing",
  stepId: "ab-testing-1",
  stepSlug: "ab-testing-1",
  stepNumber: 1,
  formValues: { objective: "SAVE_TEST_PROJECT_CONTEXT_123" },
  completed: true,
}, failingStorage);
assert.equal(quotaResult.browserCacheWritten, false);
assert.equal(quotaResult.retriedAfterQuota, true);
assert.match(quotaResult.browserCacheError, /quota forced|Local storage quota exceeded/);

const oversizedInputResult = abPersistence.saveAbTestingStep({
  projectId: "ab-persistence-test",
  workflowType: "ab_testing",
  stepId: "ab-testing-1",
  stepSlug: "ab-testing-1",
  stepNumber: 1,
  formValues: { objective: "x".repeat(150000) },
  completed: true,
});
assert.equal(oversizedInputResult.payloadBytes < abPersistence.AB_TESTING_MAX_PAYLOAD_BYTES, true, "Oversized text input must be compacted under the payload limit before storage.");

localStorage.setItem("atlas-ab-testing-workflow-step:ab-persistence-test:ab-testing-old", "x".repeat(120000));
localStorage.setItem("atlas-workflow-node-state:ab-persistence-test:ab-testing-old", JSON.stringify({ objective: "old" }));
localStorage.setItem("atlas-workflow-node-state:ab-persistence-test:predictive-step", JSON.stringify({ objective: "keep" }));
const removedKeys = abPersistence.clearAbTestingWorkflowStorage("ab-persistence-test");
assert.equal(removedKeys.some((key) => key.includes("ab-testing-old")), true);
assert.equal(localStorage.getItem("atlas-workflow-node-state:ab-persistence-test:predictive-step") !== null, true, "Clear cache must not remove unrelated workflow state.");

const throwingStorage = {
  getItem() {
    return null;
  },
  length: 0,
  key() {
    return null;
  },
  removeItem() {},
  setItem() {
    throw new Error("forced save failure");
  },
};
const throwingResult = abPersistence.saveAbTestingStep({
  projectId: "ab-persistence-test",
  workflowType: "ab_testing",
  stepId: "ab-testing-1",
  stepSlug: "ab-testing-1",
  formValues: { objective: "SAVE_TEST_PROJECT_CONTEXT_123" },
  completed: true,
}, throwingStorage);
assert.equal(throwingResult.browserCacheWritten, false);
assert.match(throwingResult.browserCacheError, /forced save failure/);

console.log("experimentation workflow checks passed");

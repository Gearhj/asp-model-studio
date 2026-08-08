import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  buildTrainingPreflightSignature,
  createBoundedSaveQueue,
  estimateTrainingPortfolio,
  resolveTrainingPreflightLifecycle,
  trainingActionLabel,
} from "../src/lib/modelTrainingInteraction.ts";

const trainingPage = await readFile(
  new URL("../src/steps/Step06_Train.tsx", import.meta.url),
  "utf8",
);
const identityProvider = await readFile(
  new URL("../src/components/PredictiveIdentityProvider.tsx", import.meta.url),
  "utf8",
);

function block(start, end) {
  const startIndex = trainingPage.search(start);
  assert.notEqual(startIndex, -1, `missing block ${start}`);
  const source = trainingPage.slice(startIndex);
  const endIndex = source.search(end);
  assert.notEqual(endIndex, -1, `missing block end ${end}`);
  return source.slice(0, endIndex);
}

const wait = (milliseconds = 0) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

test("portfolio estimates update immediately and calibrate compatible models only", () => {
  assert.equal(estimateTrainingPortfolio({
    selectedModelCount: 3,
    folds: 5,
    tuningCandidates: 4,
    calibrationRequested: false,
    workers: 2,
    featureCount: 22,
  }).estimatedFits, 60);
  const large = estimateTrainingPortfolio({
    selectedModelCount: 10,
    folds: 5,
    tuningCandidates: 4,
    calibrationRequested: true,
    calibrationModelCount: 7,
    workers: 2,
    featureCount: 22,
  });
  assert.equal(large.baseFits, 200);
  assert.equal(large.calibrationFits, 35);
  assert.equal(large.estimatedFits, 235);
  assert.equal(large.largeRun, true);
});

test("one lifecycle prevents contradictory current readiness", () => {
  assert.equal(resolveTrainingPreflightLifecycle({ hasPreflight: false, current: false, loading: false, ready: false }), "missing");
  assert.equal(resolveTrainingPreflightLifecycle({ hasPreflight: true, current: false, loading: false, ready: true }), "stale");
  assert.equal(resolveTrainingPreflightLifecycle({ hasPreflight: true, current: true, loading: true, ready: true }), "validating");
  assert.equal(resolveTrainingPreflightLifecycle({ hasPreflight: true, current: true, loading: false, ready: false }), "blocked");
  assert.equal(resolveTrainingPreflightLifecycle({ hasPreflight: true, current: true, loading: false, ready: true }), "ready");
  assert.match(trainingPage, /readiness=\{readiness\}[\s\S]*?preflightLifecycle=\{preflightLifecycle\}/);
  assert.doesNotMatch(trainingPage, /readiness=\{preflightCurrent\s*\?[\s\S]*?splitStatus/);
  assert.match(trainingPage, /currentReadinessStripItems\(authoritativePreflight\)/);
});

test("job-launch metadata cannot make an authoritative preflight look stale", () => {
  const technicalPayload = {
    project_id: "atlas-project",
    dataset_id: "dataset",
    dataset_version_id: "version",
    models: ["logreg", "dtree"],
    user: "hydrating-user-label",
    requested_at: "2026-08-01T20:00:00.000Z",
  };
  const launchPayload = {
    ...technicalPayload,
    user: "resolved-user-label",
    requested_at: "2026-08-01T20:00:01.000Z",
    retry_parent_job_id: "",
  };
  assert.equal(
    buildTrainingPreflightSignature(technicalPayload),
    buildTrainingPreflightSignature(launchPayload),
  );
});

test("primary action exposes every visible execution state", () => {
  assert.equal(trainingActionLabel({ executionState: "idle", jobActive: false, largeRun: false, acknowledged: false, preflightReady: false }), "Validate & Train Selected Models");
  assert.equal(trainingActionLabel({ executionState: "validating", jobActive: false, largeRun: false, acknowledged: false, preflightReady: false }), "Validating selected models...");
  assert.equal(trainingActionLabel({ executionState: "validation_failed", jobActive: false, largeRun: false, acknowledged: false, preflightReady: false }), "Retry validation");
  assert.equal(trainingActionLabel({ executionState: "start_failed", jobActive: false, largeRun: false, acknowledged: false, preflightReady: true }), "Retry governed training");
  assert.equal(trainingActionLabel({ executionState: "acknowledgement_required", jobActive: false, largeRun: true, acknowledged: false, preflightReady: true }), "Acknowledge and Start Governed Training");
  assert.equal(trainingActionLabel({ executionState: "starting", jobActive: false, largeRun: false, acknowledged: false, preflightReady: true }), "Starting governed training...");
  assert.equal(trainingActionLabel({ executionState: "job_created", jobActive: true, largeRun: false, acknowledged: false, preflightReady: true }), "Training job created");
});

test("rapid portfolio saves are coalesced and never overlap", async () => {
  let active = 0;
  let maximumActive = 0;
  let releaseFirst;
  let firstStarted;
  const firstStartedPromise = new Promise((resolve) => { firstStarted = resolve; });
  const firstReleasePromise = new Promise((resolve) => { releaseFirst = resolve; });
  const saved = [];
  const queue = createBoundedSaveQueue({
    debounceMs: 0,
    async save(entry) {
      active += 1;
      maximumActive = Math.max(maximumActive, active);
      saved.push(entry.value);
      if (saved.length === 1) {
        firstStarted();
        await firstReleasePromise;
      }
      active -= 1;
      return { ok: true };
    },
  });
  queue.schedule("first");
  await firstStartedPromise;
  queue.schedule("superseded");
  queue.schedule("latest");
  releaseFirst();
  await queue.flush();
  assert.deepEqual(saved, ["first", "latest"]);
  assert.equal(maximumActive, 1);
  queue.dispose();
});

test("failed persistence remains visible and can retry without navigation", async () => {
  let attempts = 0;
  let failed;
  let saved = false;
  const queue = createBoundedSaveQueue({
    debounceMs: 0,
    async save() {
      attempts += 1;
      if (attempts === 1) throw new Error("safe persistence failure");
      return { ok: true };
    },
    onError(entry) { failed = entry; },
    onSaved() { saved = true; },
  });
  queue.schedule({ models: ["logreg"] });
  await queue.flush();
  assert.ok(failed);
  queue.retry(failed);
  await wait();
  await queue.flush();
  assert.equal(saved, true);
  assert.equal(attempts, 2);
  assert.match(trainingPage, /data-testid="portfolio-persistence-status"/);
  assert.match(trainingPage, /Retry save/);
  queue.dispose();
});

test("model toggles, suites, and clear remain in-page and preserve view controls", () => {
  const toggle = block(/function toggleModel\(/, /\n\s*function applyModelSuite/);
  const suite = block(/function applyModelSuite\(/, /\n\s*function applyCandidateStrategy/);
  for (const source of [toggle, suite]) {
    assert.doesNotMatch(source, /location\.reload|window\.location|navigate\(|logDecision|setModelSearch|setFamilyFilter|setInterpretabilityFilter|setSelectedOnly|setCompactPortfolio/);
  }
  assert.doesNotMatch(trainingPage, /setPreflight\(null\)/);
  assert.doesNotMatch(identityProvider, /PROJECT_SAVE_STATUS_EVENT|atlas-project-save-status/);
  assert.match(identityProvider, /atlas-dataset-identity-updated/);
  assert.match(trainingPage, /createBoundedSaveQueue/);
  assert.match(trainingPage, /"\/model\/train\/selection"/);
});

test("hyperparameter controls expose separate stable accessible names", () => {
  assert.match(trainingPage, /data-testid="hyperparameter-search-control"/);
  assert.match(trainingPage, /htmlFor="hyperparameter-search-enabled"/);
  assert.match(trainingPage, /id="hyperparameter-search-enabled"/);
  assert.match(trainingPage, /<span id="hyperparameter-search-title">Hyperparameter search<\/span>/);
  assert.match(trainingPage, /htmlFor="hyperparameter-search-depth"/);
  assert.match(trainingPage, /id="hyperparameter-search-depth"/);
  assert.match(trainingPage, /<span className="atlas-label">Hyperparameter search depth<\/span>/);
});

test("governed execution is idempotent, holdout-safe, and activates Live Training", () => {
  const start = block(/async function startTraining\(/, /\n\s*async function retryFailedModels/);
  assert.match(start, /trainingSubmissionLocked\.current/);
  assert.match(start, /expected_preflight_id/);
  assert.match(start, /expected_preflight_state_hash/);
  assert.match(start, /selected_algorithm_versions/);
  assert.match(start, /idempotency_key/);
  assert.match(start, /if \(!check\?\.ready\)[\s\S]*?return;/);
  assert.match(start, /requestJson<TrainingJob>\("\/model\/train\/jobs"/);
  assert.match(trainingPage, /data-testid="live-training-active-region"/);
  assert.match(trainingPage, /liveTrainingRef\.current\?\.focus/);
  assert.match(trainingPage, /Final holdout \{authoritativePreflight\.final_holdout_sealed/);
  assert.match(trainingPage, /development_population_cross_validation/);
  assert.match(trainingPage, /PlanEquation value=\{calibration \? `\+ \$\{calibrationFits\}`/);
  assert.match(trainingPage, /estimatedRuntimeSeconds=\{displayedEstimatedRuntimeSeconds\}/);
  assert.match(trainingPage, /setExecutionState\("start_failed"\)/);
  assert.match(trainingPage, /No known dependency issue; authoritative validation pending/);
});

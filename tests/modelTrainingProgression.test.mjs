import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

const [trainingPage, trainer, jobService, router] = await Promise.all([
  read("src/steps/Step06_Train.tsx"),
  read("server/training/trainer.py"),
  read("server/training/training_job_service.py"),
  read("server/training/trainer_router.py"),
]);

assert.match(
  trainer,
  /class AtlasXGBClassifier\(ClassifierMixin, BaseEstimator\)/,
  "XGBoost classification must use the sklearn-compatible composition adapter.",
);
assert.match(
  trainer,
  /class AtlasXGBRegressor\(RegressorMixin, BaseEstimator\)/,
  "XGBoost regression must use the sklearn-compatible composition adapter.",
);
assert.match(trainer, /SMALL_DATA_NEURAL_THRESHOLD = 12_000/);
assert.match(trainer, /"name": "small_data_fast"/);
assert.match(trainer, /"n_iter_no_change": 6/);

assert.match(
  jobService,
  /elif job\["completed_count"\] == 0:[\s\S]*?final_status = "failed"[\s\S]*?else:[\s\S]*?final_status = "complete"/,
  "An optional candidate failure must not fail a job that retained successful candidates.",
);
assert.match(jobService, /"requested_models": job\["requested_models"\]/);
assert.match(
  router,
  /last_summary = scoped_results\.get_last_summary\(\)/,
  "Training recovery must read the exact authorized project scope, not a process-global latest result.",
);
assert.match(router, /str\(last_summary\.get\("status"\) or ""\) == "complete"/);

assert.match(
  trainingPage,
  /nextDisabled=\{[\s\S]*?!datasetIdentity[\s\S]*?job\?\.overall_status !== "complete"[\s\S]*?!championEligibleResults\.length[\s\S]*?\}/,
  "Continue must become available as soon as the canonical dataset remains bound and a completed run has an eligible candidate.",
);
assert.doesNotMatch(
  trainingPage,
  /nextDisabled=\{[^}]*selectionDecision/,
  "A separately saved proposal must not deadlock the page-level Continue action.",
);
assert.match(
  trainingPage,
  /proposalFormCurrent[\s\S]*?\? selectionDecision[\s\S]*?: await saveModelSelectionDecision\(\)/,
  "Continue must immutably lock the exact candidate when the current selection has not been saved.",
);
assert.match(trainingPage, /Continue will immutably lock the exact candidate/);
assert.match(trainingPage, /completed candidates remain usable/);
assert.match(trainingPage, /Exclude failed from next run/);
assert.match(trainingPage, /Small-data neural profile active/);

console.log("Model Training reliability and progression contract assertions passed.");

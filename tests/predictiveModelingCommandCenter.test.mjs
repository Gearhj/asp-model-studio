import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);
const read = (path) => readFile(new URL(path, root), "utf8");

const [
  featureUi,
  validationUi,
  trainingUi,
  featureClient,
  featureService,
  splitRouter,
  splitService,
  trainingPreflight,
  trainingJobs,
  trainingRouter,
  documentationBackend,
  documentationUi,
] = await Promise.all([
  read("src/steps/Step05_EncodingScaling.tsx"),
  read("src/steps/Step06_BalancingSplit.tsx"),
  read("src/steps/Step06_Train.tsx"),
  read("src/lib/featureManifest.ts"),
  read("server/features/feature_service.py"),
  read("server/splitting/split_router.py"),
  read("server/splitting/split_service.py"),
  read("server/training/training_preflight_service.py"),
  read("server/training/training_job_service.py"),
  read("server/training/trainer_router.py"),
  read("server/preprocessing/preparation_documentation_router.py"),
  read("src/components/documentation/PreparationDocumentationLiveLink.tsx"),
]);

test("Feature Engineering presents a governed, readable transformation contract", () => {
  for (const heading of [
    "Include",
    "Feature",
    "Kind",
    "Type",
    "Source or rule",
    "Status",
    "Review",
  ]) {
    assert.ok(featureUi.includes(heading), `missing transformation column: ${heading}`);
  }
  assert.match(featureUi, /data-testid="feature-set-review"/);
  assert.match(featureUi, /max-h-\[32rem\][\s\S]*overflow-auto/);
  assert.match(featureUi, /visibleReviewFeatures\.map/);
  for (const action of [
    "Review details",
    "Edit definition",
    "Apply draft edit",
  ]) {
    assert.ok(featureUi.includes(action), `missing row action: ${action}`);
  }
  for (const detail of [
    "Full formula",
    "Source variables",
    "Transformation parameters",
    "Preview statistics",
    "Target association",
    "Source correlation",
    "Leakage review",
    "Creation history",
    "Materialization history",
  ]) {
    assert.ok(featureUi.includes(detail), `missing feature detail: ${detail}`);
  }
});

test("Feature Engineering makes the seven-stage execution pipeline and hash gate explicit", () => {
  for (const stage of [
    "Build plan",
    "Validate definitions",
    "Save manifest",
    "Preview features",
    "Materialize full dataset",
    "Confirm set current",
    "Continue",
  ]) {
    assert.ok(featureUi.includes(stage), `missing execution stage: ${stage}`);
  }
  for (const state of [
    "Not started",
    "Ready",
    "In progress",
    "Complete",
    "Failed",
    "Stale",
  ]) {
    assert.ok(featureUi.includes(state), `missing execution state: ${state}`);
  }
  assert.match(featureUi, /manifest_hash/);
  assert.match(featureUi, /materialized_manifest_hash/);
  assert.match(featureUi, /confirmed_manifest_hash/);
  assert.match(featureClient, /confirmFeatureManifest/);
  assert.match(featureService, /Preview the saved feature contract before materializing/);
  assert.match(featureService, /materialized_manifest_hash.*manifest_hash/s);
  assert.match(featureService, /DATASTORE\.reset_splits\(\)/);
});

test("Validation Design owns all five strategies, folds, protections, and visuals", () => {
  assert.match(validationUi, /title="Training and Validation Design"/);
  for (const testId of [
    "advanced-balancing-settings",
    "advanced-external-validation",
    "compact-final-predictor-review",
  ]) {
    assert.match(validationUi, new RegExp(`<section data-testid="${testId}">`));
    assert.doesNotMatch(
      validationUi,
      new RegExp(`<details[^>]*data-testid="${testId}"`),
    );
  }
  for (const strategy of [
    "Holdout from Current Development Dataset",
    "Separate TEST Dataset",
    "Separate TEST and OOT Datasets",
    "Cross-Validation Strategy",
    "Hybrid Holdout plus Cross-Validation",
  ]) {
    assert.ok(validationUi.includes(strategy), `missing validation strategy: ${strategy}`);
  }
  for (const control of [
    "Fold method",
    "Number of folds",
    "Repeats",
    "Governed group field",
    "Governed time field",
    "Shuffle before folding",
    "Inner tuning folds",
  ]) {
    assert.ok(validationUi.includes(control), `missing CV control: ${control}`);
  }
  for (const visual of [
    "Population Partition Visual",
    "Fold Architecture Visual",
    "Class-Balance Preservation Visual",
    "Dataset Compatibility Matrix",
    "Validation Risk Summary",
    "Completion Gates",
  ]) {
    assert.ok(validationUi.includes(visual), `missing validation visual: ${visual}`);
  }
  assert.match(splitService, /separate_test_oot/);
  assert.match(splitService, /RepeatedStratifiedKFold/);
  assert.match(splitService, /StratifiedGroupKFold/);
  assert.match(splitService, /TimeSeriesSplit/);
  assert.match(splitRouter, /validation_design_id/);
  assert.match(splitRouter, /test_reference/);
  assert.match(splitRouter, /oot_reference/);
  assert.match(splitRouter, /holdout_protection/);
});

test("Balancing is training-only and the HELOC recommendation is honest", () => {
  assert.match(validationUi, /Balancing policy · training population only/i);
  assert.match(validationUi, /No balancing is applied to holdout, TEST, or OOT/);
  assert.match(validationUi, /No balancing required/);
  assert.match(validationUi, /Threshold optimization: Evaluation only/);
  assert.match(splitService, /original_train_rows/);
  assert.match(splitService, /synthetic_rows_added/);
  assert.match(splitService, /rows_removed/);
  assert.match(splitRouter, /global resampling before cross-validation|fold-local/i);
});

test("Model Training consumes locked inputs and acts as Mission Control", () => {
  for (const section of [
    "Training Mission Control",
    "Locked Inputs",
    "Candidate Strategy",
    "Model Portfolio",
    "Training Plan",
    "Live Training",
    "Candidate Leaderboard",
    "Champion / Challenger Review",
    "Evidence and Documentation",
  ]) {
    assert.ok(trainingUi.includes(section), `missing training section: ${section}`);
  }
  assert.match(trainingUi, /Cross-validation folds · read-only/);
  assert.doesNotMatch(trainingUi, /value=\{kFolds\}[^>]*onChange/);
  assert.match(trainingUi, /Inherited from .*Validation Design/s);
  assert.match(trainingPreflight, /Cross-validation is locked by Validation Design/);
  assert.match(trainingPreflight, /exact_fold_bindings/);
  assert.match(trainingJobs, /_cv_execution_splits/);
  assert.match(trainingJobs, /cv_splits=/);
  assert.match(trainingPreflight, /return to Balance & Split/);
  assert.match(trainingJobs, /estimated_fits >= 160/);
  assert.match(trainingJobs, /large_job_confirmed/);
});

test("Training execution, diagnostic separation, and governed proposal are explicit", () => {
  for (const phrase of [
    "Cancel queued only",
    "Retry failed",
    "Metrics persisted",
    "Diagnostic only",
    "Performance versus Interpretability frontier",
    "Only verified non-holdout selection evidence appears here",
    "Calibration treatment versus discrimination",
    "Runtime versus performance",
    "Candidate decision lock",
  ]) {
    assert.ok(trainingUi.includes(phrase), `missing training behavior: ${phrase}`);
  }
  assert.match(trainingJobs, /job\["overall_status"\] = "running"/);
  assert.match(trainingJobs, /result_persistence/);
  assert.match(trainingRouter, /Final approval remains in downstream Evaluation/);
  for (const rationale of [
    "metric_justification",
    "interpretability_justification",
    "calibration_considerations",
    "fairness_validation_prerequisites",
    "deployment_constraints",
  ]) {
    assert.ok(trainingRouter.includes(rationale), `missing decision field: ${rationale}`);
  }
});

test("live MDD links feature, validation, training, and stale-state contracts", () => {
  for (const contract of [
    "feature_engineering",
    "validation_design",
    "model_training",
    "training_job_id",
    "ranked_candidates",
    "model_selection_decision",
    "stale_reasons",
  ]) {
    assert.ok(documentationBackend.includes(contract), `missing MDD contract: ${contract}`);
  }
  assert.match(documentationBackend, /Training is bound to an earlier Validation Design version/);
  assert.match(documentationBackend, /champion\/challenger proposal is stale/);
  assert.match(documentationUi, /Validation Design/);
  assert.match(documentationUi, /Model Training/);
  assert.match(documentationUi, /dataset, manifest, split, or decision/);
});

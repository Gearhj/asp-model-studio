import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);
const read = (path) => readFile(new URL(path, root), "utf8");

const [
  bureauUi,
  bureauClient,
  bureauService,
  validationUi,
  splitRouter,
  trainingUi,
  modelDocument,
] = await Promise.all([
  read("src/components/BureauReviewPanel.tsx"),
  read("src/lib/bureauDetection.ts"),
  read("server/preprocessing/bureau_detection_service.py"),
  read("src/steps/Step06_BalancingSplit.tsx"),
  read("server/splitting/split_router.py"),
  read("src/steps/Step06_Train.tsx"),
  read("src/lib/modelDevelopmentDocument.ts"),
]);

const activeValidationUi = validationUi.split(
  "Retained temporarily as migration reference",
)[0];

test("special-value review renders a governed, readable twelve-column table", () => {
  for (const heading of [
    "Special value",
    "Definition",
    "Count",
    "Population share",
    "Development event count",
    "Development event rate",
    "Development regular-value event rate",
    "Development event-rate difference",
    "Default action",
    "Override action",
    "Rationale",
    "Review status",
  ]) {
    assert.ok(bureauUi.includes(heading), `missing special-value column: ${heading}`);
  }
  assert.match(bureauUi, /data-testid="special-value-treatment-table"/);
  assert.match(bureauUi, /min-w-\[1900px\]/);
  assert.match(bureauUi, /sticky top-0/);
  assert.match(bureauUi, /text-right font-medium tabular-nums/);
  assert.doesNotMatch(bureauUi, /font-mono tabular-nums/);
});

test("feature-level table, defaults, overrides, and scoped rationale are explicit", () => {
  for (const contract of [
    "Feature-level Special-Value Treatment Table",
    "Search features",
    "Selected treatment",
    "Recommended treatment",
    "Override",
    "Required because this value overrides the variable default.",
    "Rationale required",
  ]) {
    assert.ok(bureauUi.includes(contract), `missing review contract: ${contract}`);
  }
  assert.match(bureauUi, /override:\s*true/);
  assert.match(bureauUi, /treatmentRequiresRationale\(/);
  assert.match(bureauClient, /variableDefaults/);
  assert.match(bureauClient, /status:\s*"draft"\s*\|\s*"confirmed"/);
});

test("special-value semantics and section completion remain governed", () => {
  for (const text of [
    "Save Draft Review",
    "Confirm Special-Value Treatment",
    "null missing values",
    "parse failures",
    "ordinary outliers",
  ]) {
    assert.ok(bureauUi.toLowerCase().includes(text.toLowerCase()), `missing semantic/evidence text: ${text}`);
  }
  for (const field of [
    "ordinary_value_count",
    "null_count",
    "parse_failure_count",
    "event_count",
    "rows_with_special_values",
  ]) {
    assert.ok(bureauService.includes(field), `missing backend special-value field: ${field}`);
  }
  assert.match(modelDocument, /Governed review status/);
  assert.match(modelDocument, /variableDefaults/);
});

test("the rendered validation flow exposes the two governed validation choices", () => {
  for (const text of [
    "Training and Validation Design",
    "Data Acquisition Analysis Partition",
    'data-testid="analysis-partition-read-only-summary"',
    "K-fold cross-validation",
    "Traditional TRAIN / TEST / OOT setup",
    "TEST and OOT datasets are selected later",
    "Holdout remains untouched",
    "Development event rate",
    "Current policy",
  ]) {
    assert.ok(activeValidationUi.includes(text), `missing standard validation path: ${text}`);
  }
  assert.match(activeValidationUi, /useState\(5\)/);
  assert.match(activeValidationUi, /value === 5 \? " · recommended"/);
  assert.doesNotMatch(activeValidationUi, /data-testid="validation-strategy-selector"/);
  assert.doesNotMatch(activeValidationUi, /<ValidationStrategyCard/);
});

test("balancing, external validation, and predictor review remain visible workflow sections", () => {
  assert.match(
    activeValidationUi,
    /<section data-testid="advanced-balancing-settings">[\s\S]*title="Advanced Balancing Settings"/,
  );
  assert.match(
    activeValidationUi,
    /<section data-testid="advanced-external-validation">[\s\S]*title="Advanced External Validation Data"/,
  );
  assert.doesNotMatch(
    activeValidationUi,
    /<details[^>]*data-testid="advanced-(?:balancing-settings|external-validation)"/,
  );
  assert.match(activeValidationUi, /External validation datasets are optional/);
  assert.match(activeValidationUi, /Use separate TEST dataset/);
  assert.match(activeValidationUi, /Use OOT dataset/);
  assert.match(activeValidationUi, /Use both TEST and OOT/);
  assert.match(
    activeValidationUi,
    /<section data-testid="compact-final-predictor-review">[\s\S]*title="Final Predictor Review"/,
  );
  assert.doesNotMatch(
    activeValidationUi,
    /<details[^>]*data-testid="compact-final-predictor-review"/,
  );
  assert.match(activeValidationUi, /View Full Predictor Contract/);
  assert.match(splitRouter, /external_validation_mode/);
});

test("readiness is exact, lazy full-population fallback is absent, and drafts auto-save", () => {
  for (const blocker of [
    "Create and confirm the current feature manifest before defining validation.",
    "At least one projected fold lacks event coverage.",
    "Select an immutable TEST version or disable external TEST.",
    "Select an immutable OOT version or disable external OOT.",
  ]) {
    assert.ok(activeValidationUi.includes(blocker), `missing exact blocker: ${blocker}`);
  }
  assert.match(activeValidationUi, /saveValidationDraft\(datasetIdentity/);
  assert.match(activeValidationUi, /canonicalDatasetStorageKey\(VALIDATION_DRAFT_PREFIX, identity\)/);
  assert.match(activeValidationUi, /Draft auto-saved/);
  assert.match(activeValidationUi, /Retry target distribution/);
  assert.doesNotMatch(
    splitRouter,
    /"full_dataset"\s+not\s+in\s+distributions[\s\S]*target_distribution\(/,
  );
});

test("one action creates the governed contract, evidence, MDD handoff, and training inheritance", () => {
  assert.equal(
    (activeValidationUi.match(/nextButtonTestId="create-validation-design-and-continue"/g) ?? []).length,
    1,
  );
  assert.match(activeValidationUi, /Create Validation Design & Continue/);
  assert.match(activeValidationUi, /split_strategy:\s*"hybrid"/);
  assert.match(activeValidationUi, /holdout_protection_confirmed:\s*true/);
  assert.match(activeValidationUi, /cv_design_approved:\s*true/);
  assert.match(activeValidationUi, /title:\s*"Created Validation Design"/);
  assert.match(trainingUi, /Validation Design|validation design/i);
  assert.match(trainingUi, /cv_design|fold_architecture/);
});

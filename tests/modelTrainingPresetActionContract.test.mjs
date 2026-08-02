import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const trainingPage = await readFile(
  new URL("../src/steps/Step06_Train.tsx", import.meta.url),
  "utf8",
);
const trainingInteraction = await readFile(
  new URL("../src/lib/modelTrainingInteraction.ts", import.meta.url),
  "utf8",
);

function sourceBlock(startPattern, endPattern) {
  const start = trainingPage.search(startPattern);
  assert.notEqual(start, -1, `missing source block start: ${startPattern}`);
  const remainder = trainingPage.slice(start);
  const end = remainder.search(endPattern);
  assert.notEqual(end, -1, `missing source block end: ${endPattern}`);
  return remainder.slice(0, end);
}

function quotedValues(source) {
  return [...source.matchAll(/"([^"]+)"/g)].map((match) => match[1]);
}

function classificationModelsForPreset(key) {
  const preset = sourceBlock(
    new RegExp(`key:\\s*"${key}"`),
    /\n\s*},\n\s*{\s*\n\s*key:|\n\s*},\n\] as const/,
  );
  const match = preset.match(/classification:\s*\[([\s\S]*?)\]/);
  assert.ok(match, `${key} must define an explicit classification suite`);
  return quotedValues(match[1]);
}

function classificationCatalog() {
  const definitions = sourceBlock(
    /const MODEL_DEFINITIONS: ModelDefinition\[\] = \[/,
    /\n\];/,
  );
  return [...definitions.matchAll(
    /\{\s*key:\s*"([^"]+)"[\s\S]*?task:\s*"classification"[\s\S]*?\},/g,
  )].map((match) => match[1]);
}

function estimateFits({
  models,
  folds = 5,
  tuningCandidates = 1,
  calibrate = false,
}) {
  const base = models * Math.max(1, folds) * tuningCandidates;
  return base + (calibrate ? models * Math.max(1, folds) : 0);
}

function deriveActionState({
  models,
  folds = 5,
  tuningCandidates = 1,
  calibrate = false,
  confirmed = false,
}) {
  const fits = estimateFits({ models, folds, tuningCandidates, calibrate });
  const large = fits >= 160;
  return {
    fits,
    large,
    // Technical validation remains reachable. Explicit confirmation gates only
    // the subsequent job-creation request.
    validateEnabled: models > 0,
    canCreateJob: models > 0 && (!large || confirmed),
  };
}

test("Balanced and Full Research presets keep technical validation reachable", () => {
  const balanced = classificationModelsForPreset("balanced_bench");
  const research = classificationCatalog();

  assert.equal(balanced.length, 11, "Balanced Challenger Bench contract changed");
  assert.equal(research.length, 26, "Full Research Bench contract changed");
  assert.equal(new Set(balanced).size, balanced.length);
  assert.equal(new Set(research).size, research.length);

  for (const [name, models] of [
    ["Balanced Challenger Bench", balanced.length],
    ["Full Research Bench", research.length],
  ]) {
    const ordinary = deriveActionState({ models });
    assert.equal(
      ordinary.validateEnabled,
      true,
      `${name} must expose Validate & Train Selected Models`,
    );
    assert.equal(ordinary.canCreateJob, true);

    const quickTuning = deriveActionState({
      models,
      tuningCandidates: 4,
    });
    assert.equal(
      quickTuning.large,
      true,
      `${name} with quick tuning must exercise the large-job path`,
    );
    assert.equal(
      quickTuning.validateEnabled,
      true,
      `${name} technical validation must not be disabled by workload size`,
    );
    assert.equal(
      quickTuning.canCreateJob,
      false,
      `${name} job creation must wait for explicit acknowledgement`,
    );
    assert.equal(
      deriveActionState({
        models,
        tuningCandidates: 4,
        confirmed: true,
      }).canCreateJob,
      true,
      `${name} must become trainable after acknowledgement`,
    );
  }
});

test("suite clicks select only currently compatible candidates", () => {
  assert.match(trainingPage, /function applyModelSuite\(/);
  const applySuite = sourceBlock(
    /function applyModelSuite\(/,
    /\n\s*function |\n\s*async function |\n\s*const [A-Za-z0-9_]+ = async/,
  );
  assert.match(
    applySuite,
    /\.filter\(\(key\) =>[\s\S]*?compatibleModelKeys\.has\(key\)\)/,
    "Preset selection must not silently include unavailable or incompatible models",
  );
  assert.match(
    trainingPage,
    /onClick=\{\(\) => \{[\s\S]*?applyModelSuite\(suiteKeys\);[\s\S]*?\}\}/,
    "Every preset card must use the governed suite-selection path",
  );
});

test("large-job acknowledgement is visible while validation remains actionable", () => {
  const blockedExpression = sourceBlock(
    /const trainActionBlocked\s*=/,
    /;\s*\n\s*const primaryTrainingActionLabel/,
  );
  assert.doesNotMatch(
    blockedExpression,
    /\blargeJob\b/,
    "A planning estimate alone must not disable the technical validation action",
  );
  assert.match(
    blockedExpression,
    /executionState\s*===\s*"acknowledgement_required"[\s\S]*?!largeJobConfirmed/,
    "Only a successful authoritative large-run validation may gate job creation",
  );

  assert.match(trainingInteraction, /Validate & Train Selected Models/);
  assert.match(trainingPage, /id="large-job-confirmation"/);
  assert.match(trainingPage, /data-testid="large-job-confirmation"/);
  assert.match(
    trainingPage,
    /largeJobConfirmationRef\.current\?\.focus\(\)/,
    "Attempting a large run must focus the visible acknowledgement control",
  );
  assert.match(
    trainingPage,
    /largeJob[\s\S]*?!largeJobConfirmed[\s\S]*?return/,
    "Job creation must stop after preflight until workload is acknowledged",
  );

  assert.match(
    trainingInteraction,
    /large_job_confirmed:\s*false/,
    "The technical preflight signature must normalize the governance-only acknowledgement",
  );
  assert.match(
    trainingPage,
    /const currentSignature\s*=\s*useMemo\([\s\S]*?buildTrainingPreflightSignature\(requestPayload\)/,
    "Acknowledging workload must not invalidate an otherwise current technical preflight",
  );
});

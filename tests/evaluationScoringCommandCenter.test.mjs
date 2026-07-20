import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const ordered = (source, labels, context) => {
  let cursor = -1;
  for (const label of labels) {
    const index = source.indexOf(label);
    assert.ok(index > cursor, `${context}: expected ${label} after the prior command-center section.`);
    cursor = index;
  }
};

const evaluation = read("src/steps/Step08_Evaluation.tsx");
const interpretation = read("src/steps/Step09_Interpretation.tsx");
const scoring = read("src/steps/Step10_Scoring.tsx");
const evaluationRouter = read("server/evaluation/eval_router.py");
const evaluationService = read("server/evaluation/eval_service.py");

ordered(evaluation, [
  'data-testid="atlas-performance-summary"',
  'data-testid="top-candidate-comparison"',
  'data-testid="interactive-model-explorer"',
  'data-testid="threshold-operating-policy"',
  'data-testid="dataset-performance"',
  'data-testid="stability-calibration"',
  'data-testid="full-leaderboard"',
  'data-testid="interpretation-comparison-tray"',
], "Evaluation");

assert.doesNotMatch(evaluation, /localCurvesFor|buildLocalDeciles/, "Evaluation must not fabricate local model curves or deciles.");
assert.match(evaluation, /\/eval\/command_center/, "Evaluation must request backend-calculated command-center diagnostics.");
assert.match(evaluation, /DecisionTreeDiagnostic/, "Evaluation must retain model-specific tree diagnostics.");
assert.match(evaluation, /KnnDiagnostic/, "Evaluation must retain model-specific KNN diagnostics.");
assert.match(evaluation, /CoefficientDiagnostic/, "Evaluation must retain coefficient diagnostics for linear models.");
assert.match(evaluation, /Targetless models remain separate/, "Evaluation must isolate anomaly diagnostics from supervised ranking.");
assert.match(evaluationRouter, /\/eval\/command_center/, "The backend must expose the Evaluation command-center endpoint.");
assert.match(evaluationService, /Persisted holdout labels and scores are unavailable/, "The backend must report unavailable artifacts instead of fabricating output.");

assert.match(interpretation, /evaluation_candidate_selected|workflow_setting_changed/, "Interpretation review must preserve an auditable candidate action.");
assert.doesNotMatch(interpretation, /champion_model_selected/, "Opening a candidate in Interpretation must not imply Champion approval.");

ordered(scoring, [
  'data-testid="final-model-scoring-contract"',
  'data-testid="train-scoring-zone"',
  'data-testid="test-scoring-zone"',
  'data-testid="oot-scoring-zone"',
  'data-testid="cross-dataset-performance"',
  'data-testid="stability-command-center"',
  'data-testid="scored-output-registration"',
  'data-testid="scoring-developer-tools"',
], "Scoring");

assert.match(scoring, /Prediction PSI/, "Scoring must expose prediction-distribution PSI.");
assert.match(scoring, /Variable Stability Index/, "Scoring must explain feature-level VSI.");
assert.match(scoring, /development TRAIN/, "Scoring must identify the governed drift reference.");
assert.match(scoring, /Save as Evidence/, "Stability diagnostics must be saveable as evidence.");
assert.match(scoring, /Add to Monitoring Plan/, "Stability diagnostics must feed monitoring.");
assert.match(scoring, /Full output/, "Registration must distinguish full scored output from preview rows.");
assert.match(scoring, /showDeveloperTools=\{false\}/, "Scoring must avoid a duplicate StepShell developer panel.");
assert.match(evaluationService, /stability_reference.*development_train/s, "Backend scoring drift must reference development TRAIN.");
assert.match(evaluationService, /final_model_version/, "The final-model contract must expose a model version.");
assert.match(evaluationService, /source_estimator_class/, "A saved fitted candidate must preserve its estimator class for the scoring contract.");
assert.match(evaluationService, /artifact_hash/, "The final-model contract must expose artifact identity.");

console.log("Evaluation, Interpretation handoff, and Scoring command-center checks passed.");

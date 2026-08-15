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
  'data-testid="primary-model-results-table"',
  'data-testid="interactive-model-explorer"',
  'data-testid="stability-calibration"',
  'data-testid="model-score-distribution"',
], "Evaluation");

const primaryTable = evaluation.slice(
  evaluation.indexOf('data-testid="primary-model-results-table"'),
  evaluation.indexOf('data-testid="selection-evidence"'),
);
assert.match(primaryTable, /<ModelResultRow/, "Evaluation model table rows must open the review workspace directly.");
assert.doesNotMatch(primaryTable, />Actions</, "The primary model results table must not expose a separate Actions column.");
assert.match(evaluation, /function ModelScoreDistribution/, "Evaluation must replace the persistent comparison tray with a model-score distribution view.");
assert.match(evaluation, /function ModelComparisonDistributionPlot/, "Evaluation must render the full model-family comparison chart.");
assert.match(evaluation, /className="h-auto min-w-\[1280px\] w-full"/, "The model comparison chart must retain a true large canvas instead of being squeezed by the side panels.");
assert.match(evaluation, /overflow-x-auto rounded-xl border border-indigo-200/, "The large comparison canvas must remain usable inside a narrower workflow viewport.");
assert.match(evaluation, /familyColor\(modelFamily\(row\.model\)\)/, "The model comparison chart must color marks by model family.");
assert.match(evaluation, /metric\?\.fold_values/, "The comparison distribution must use persisted per-fold scores.");
assert.doesNotMatch(evaluation, /standardDeviation\s*:\s*metric|0\.0045/, "The comparison chart must not synthesize fold distributions from a fallback spread.");
assert.match(evaluation, /function ModelReviewEvidence/, "Evaluation must expose detailed performance metrics in the model review workspace.");
assert.match(evaluation, /champion \? statusPill\("Champion"/, "The first ranked model must be labeled Champion.");
assert.doesNotMatch(evaluation, /localCurvesFor|buildLocalDeciles|buildSelectionReviewArtifacts|buildSelectionCurves|buildSelectionLift|total\s*=\s*1000/, "Evaluation must not fabricate local model curves, deciles, or confusion evidence.");
assert.match(evaluation, /\/eval\/command_center/, "Evaluation must request backend-calculated command-center diagnostics.");
assert.match(evaluation, /reviewParams\.set\("evidence_scope", "selection_review"\)/, "Every selected model must request explicit development-only review evidence.");
assert.match(evaluation, /params\.set\("evidence_scope", "selection_review"\)/, "Selected-model threshold metrics must come from explicit selection-review evidence.");
assert.match(evaluation, /response\.evidence_scope !== "selection_review"/, "Selection review responses must fail closed when the backend omits their evidence scope.");
assert.match(evaluation, /function RegressionReviewDashboard/, "Regression candidates must receive real residual charts and tables even though classification-only threshold diagnostics are skipped.");
const reportingPackageEffect = evaluation.slice(
  evaluation.indexOf("if (!lockedCandidate || !selectionDecision || !lockedCandidateReady)"),
  evaluation.indexOf("function selectForReview"),
);
assert.doesNotMatch(reportingPackageEffect, /problemType !== "classification"/, "The governed reporting package must still be completed for a locked regression candidate.");
assert.match(evaluation, /evaluation_package_id=\$\{encodeURIComponent\(exactEvaluationPackageId\)\}/, "Interpretation handoff must carry the explicit completed evaluation package.");
assert.match(evaluation, /DecisionTreeDiagnostic/, "Evaluation must retain model-specific tree diagnostics.");
assert.match(evaluation, /KnnDiagnostic/, "Evaluation must retain model-specific KNN diagnostics.");
assert.match(evaluation, /CoefficientDiagnostic/, "Evaluation must retain coefficient diagnostics for linear models.");
assert.match(evaluation, /Targetless models remain separate/, "Evaluation must isolate anomaly diagnostics from supervised ranking.");
assert.match(evaluationRouter, /\/eval\/command_center/, "The backend must expose the Evaluation command-center endpoint.");
assert.match(evaluationService, /Persisted \{population\} labels and scores are unavailable/, "The backend must report unavailable holdout or out-of-fold artifacts instead of fabricating output.");
assert.match(evaluationService, /Persisted out-of-fold labels and scores are unavailable/, "Selection review must fail closed when a candidate has no persisted OOF evidence.");
assert.match(evaluation, /Final-holdout metrics below are evidence reports, not threshold recommendations/, "Evaluation must label final-holdout threshold metrics as reporting-only.");
assert.doesNotMatch(evaluation, /Maximize F1|Target Recall|Target Precision|Review Capacity/, "Evaluation must not expose threshold recommendations derived from the final holdout.");
assert.doesNotMatch(evaluation, /onPointerDown=\{selectPoint\}/, "The final-holdout ROC must not act as a threshold tuner.");
assert.match(evaluationService, /recommendations_derived_from_final_holdout["']?: False/, "The API must explicitly record that holdout-derived recommendations are disabled.");

assert.match(interpretation, /requestedCandidateDecisionId/, "Interpretation review must preserve the exact locked candidate decision.");
assert.match(interpretation, /fallback_used === true/, "Interpretation must reject any fallback decision lookup.");
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

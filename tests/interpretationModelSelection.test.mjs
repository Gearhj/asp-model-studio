import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/steps/Step09_Interpretation.tsx", import.meta.url),
  "utf8",
);

assert.match(source, /const currentRunCandidates = ranked\.filter/, "Interpretation must derive candidates from the exact current training run.");
assert.match(source, /setModels\(currentRunCandidates\)/, "Every exact current-run supervised candidate must populate the selector.");
assert.match(source, /setSelectedModel\(requestedSelection\.candidate_id \?\? ""\)/, "The Evaluation handoff candidate must remain the default selection.");
assert.match(source, /data-testid="interpretation-model-selector"/, "The model selector must be prominent and testable.");
assert.match(source, /disabled=\{models\.length < 2\}/, "The selector must be enabled whenever multiple exact candidates exist.");
assert.match(source, /selectModelForInterpretation\(event\.target\.value\)/, "Changing the selector must change the model under review.");

const queryBuilder = source.slice(
  source.indexOf("const interpretationContextQuery"),
  source.indexOf("const interpretationContextReady"),
);
assert.match(queryBuilder, /candidateRequestParams\(selectedCandidate\)/, "Every analysis must use exact frozen candidate lineage.");
assert.match(queryBuilder, /if \(selectedIsEvaluationCandidate\)[\s\S]*evaluation_package_id[\s\S]*candidate_decision_id/, "The Evaluation candidate must keep its reporting package and decision.");
assert.match(queryBuilder, /else \{\s*params\.set\("evidence_scope", "selection_review"\);\s*\}/, "Other candidates must use explicit selection-review scope.");
assert.doesNotMatch(queryBuilder, /else \{[\s\S]*evaluation_package_id/, "Selection review must not claim an Evaluation package.");
assert.doesNotMatch(queryBuilder, /else \{[\s\S]*candidate_decision_id/, "Selection review must not claim the Evaluation candidate decision.");
assert.match(source, /selectionReviewEnvelopeMatches/, "Selection-review responses must be checked against exact returned lineage.");
assert.match(source, /!artifact\.interpretation_artifact\?\.evaluation_package/, "Selection-review responses must reject reporting-package claims.");

for (const endpoint of [
  "/interpretation/importance",
  "/interpretation/details",
  "/interpretation/hyperparameters",
  "/interpretation/shap",
  "/interpretation/pdp",
  "/interpretation/sensitivity",
  "/interpretation/sensitivity_summary",
  "/interpretation/vif",
  "/interpretation/decision_boundary",
  "/eval/tree",
  "/interpretation/rfe",
]) {
  assert.ok(source.includes(endpoint), `Selected-model workflow must refresh ${endpoint}.`);
}

assert.match(source, /SelectedModelSummary/, "Interpretation must show a strong model-specific summary hierarchy.");
assert.match(source, /ModelFamilyGlyph/, "Interpretation must show model-family-specific graphics.");
assert.match(source, /rank === 1[\s\S]*Champion/, "The top-ranked current-run model must be labeled Champion.");
assert.doesNotMatch(source, />Locked candidate</, "The UI must not mislabel an unfinalized model as locked.");

assert.match(source, /insideDomain\(cell\.x, cell\.y\)/, "Decision-boundary grid cells must be filtered to plot domains.");
assert.match(source, /insideDomain\(point\.x, point\.y\)/, "Decision-boundary observations must be filtered to plot domains.");
assert.match(source, /<clipPath id=\{clipId\}/, "Decision-boundary marks must be clipped to SVG plot bounds.");
assert.match(source, /clipPath=\{`url\(#\$\{clipId\}\)`\}/, "Both boundary layers must use the plot clip path.");

assert.match(source, /if \(!selectedIsEvaluationCandidate\)[\s\S]*Selection-review candidates cannot be promoted/, "Promotion must fail closed for a non-Evaluation selection.");
assert.match(source, /disabled=\{!selectedCandidate \|\| !evaluationPackageId \|\| !promotionReadiness\.ready \|\| !selectedIsEvaluationCandidate/, "Save as Final Model must only enable for the exact promotion-ready Evaluation candidate.");
assert.match(source, /nextDisabled=\{!finalModelReady\}/, "Continue must still require a verified saved final model.");

console.log("Interpretation multi-model selection, evidence-scope, promotion, and chart-boundary checks passed.");

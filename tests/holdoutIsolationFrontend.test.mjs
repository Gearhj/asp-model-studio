import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const training = read("src/steps/Step06_Train.tsx");
const evaluation = read("src/steps/Step08_Evaluation.tsx");
const interpretation = read("src/steps/Step09_Interpretation.tsx");
const promotion = read("src/model-registry/finalModelPromotionClient.ts");
const provenance = read("src/lib/selectionProvenance.ts");

assert.match(training, /rankVerifiedSelectionCandidates/);
assert.match(training, /verifiedSelectionMetric/);
assert.match(training, /status:\s*"proposed"/);
assert.match(training, /parseLockedSelectionDecision\(response\.decision\)/);
assert.doesNotMatch(training, /body:\s*JSON\.stringify\(\{[\s\S]*?status:\s*"locked"/);
assert.match(training, /selected_candidate_id:/);
assert.match(training, /selection_ranking_snapshot:/);
assert.match(training, /Final holdout remains sealed until Evaluation/);
assert.doesNotMatch(training, /sortMetric/);

assert.match(evaluation, /lockedDecisionMatchesCandidate/);
assert.match(evaluation, /candidate_decision_id", selectionDecision\.decision_id/);
assert.match(evaluation, /data-testid="selection-evidence"/);
assert.match(evaluation, /data-testid="final-holdout-evidence"/);
assert.match(evaluation, /Final-holdout values never appear in or alter the ranking/);
assert.match(evaluation, /disabled=\{!locked\}/);
const rankedTable = evaluation.slice(
  evaluation.indexOf("function LeaderboardRow"),
  evaluation.indexOf("function AnomalyDiagnostics"),
);
const comparisonCard = evaluation.slice(
  evaluation.indexOf("function ComparisonRow"),
  evaluation.indexOf("function MiniMetric"),
);
for (const source of [rankedTable, comparisonCard]) {
  assert.doesNotMatch(source, /formatMetric\(model\.pr_auc\)/);
  assert.doesNotMatch(source, /formatMetric\(model\.auc\)/);
  assert.doesNotMatch(source, /formatMetric\(model\.rmse\)/);
}

assert.match(interpretation, /requestedCandidateDecisionId/);
assert.match(interpretation, /fallback_used === true/);
assert.match(interpretation, /normalizeGovernedEvaluationPackage/);
assert.match(interpretation, /resolvePromotionReadiness/);
assert.match(interpretation, /candidateDecision: selectionDecision/);
assert.match(interpretation, /disabled=\{!selectedCandidate \|\| !evaluationPackageId \|\| !promotionReadiness\.ready/);
assert.doesNotMatch(interpretation, /loadInterpretationCandidates/);

assert.match(promotion, /candidate_decision_id: readiness\.candidateDecisionId/);
assert.match(promotion, /evaluationPackageIntegrityStatus !== "verified"/);
assert.match(promotion, /promotionReadinessStatus !== "verified"/);
assert.match(promotion, /finalHoldoutStatus !== "evaluated"/);
assert.match(promotion, /resolvePromotionReadiness/);

for (const required of [
  "cross_validation_mean",
  "out_of_fold",
  "training_validation_partition",
  "selection_integrity_status",
  "holdout_isolation_status",
  "selection_ranking_snapshot_hash",
  "first_opened_at",
  "reporting_only",
]) {
  assert.ok(provenance.includes(required), `Missing fail-closed provenance contract: ${required}`);
}

console.log("Frontend holdout-isolation contract checks passed.");

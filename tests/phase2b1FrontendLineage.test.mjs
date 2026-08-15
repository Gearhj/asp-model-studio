import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const evaluation = read("src/steps/Step08_Evaluation.tsx");
const interpretation = read("src/steps/Step09_Interpretation.tsx");
const candidates = read("src/lib/interpretationCandidates.ts");
const promotion = read("src/model-registry/finalModelPromotionClient.ts");
const readiness = read("src/lib/finalModelReadiness.ts");

for (const field of [
  "candidate_id",
  "training_job_id",
  "training_run_id",
  "project_id",
  "dataset_id",
  "dataset_version_id",
  "target",
  "feature_manifest_version",
  "validation_design_id",
  "validation_design_version",
  "split_id",
]) {
  assert.match(candidates, new RegExp(`"${field}"`), `Candidate contract must require ${field}.`);
}
assert.match(candidates, /canonicalDatasetStorageKey\("atlas-interpretation-candidates"/);
assert.match(candidates, /candidateMatchesDataset/);
assert.match(candidates, /REQUIRED_FIELDS\.every/);
assert.match(candidates, /assertEmbeddedContractMatches/);
assert.match(candidates, /Candidate row conflicts with its frozen/);

assert.match(evaluation, /requireLocalDatasetCanonicalIdentity/);
assert.match(evaluation, /exactCandidateRows/);
assert.match(evaluation, /candidateRequestParams\(lockedCandidate\)/);
assert.match(evaluation, /candidate_id=\$\{encodeURIComponent\(candidate\.candidate_id\)\}/);
assert.match(evaluation, /evaluation_package_id=\$\{encodeURIComponent\(exactEvaluationPackageId\)\}/);
assert.match(evaluation, /!exactEvaluationPackageId/);
assert.match(evaluation, /openInterpretation\(lockedModel, comparison\)/);
assert.match(evaluation, /rankVerifiedSelectionCandidates/);
assert.match(evaluation, /lockedDecisionMatchesCandidate/);
assert.match(evaluation, /data-testid="selection-evidence"/);
assert.match(evaluation, /data-testid="final-holdout-evidence"/);
assert.match(evaluation, /verified out-of-fold development selection/);
assert.match(evaluation, /A separate reporting-only package/);
assert.match(evaluation, /params\.set\("evidence_scope", "selection_review"\)[\s\S]*params\.set\("threshold"/, "Interactive thresholds must be calculated only from development selection-review evidence.");
assert.match(evaluation, /Final-holdout metrics below are evidence reports, not threshold recommendations/);
assert.match(evaluation, /function RegressionReviewDashboard/);
assert.doesNotMatch(evaluation, /loadLocalRanked|modeling-tool-training-summary/);
assert.doesNotMatch(evaluation, /eval\/curves\?model=/);
assert.doesNotMatch(evaluation, /selectedModel \?\? leader/);

assert.match(interpretation, /requestedCandidateId/);
assert.match(interpretation, /requestedTrainingRunId/);
assert.match(interpretation, /requestedEvaluationPackageId/);
assert.match(interpretation, /requestedCandidateDecisionId/);
assert.match(interpretation, /candidateRequestParams\(selectedCandidate\)/);
assert.match(interpretation, /params\.set\("evaluation_package_id", requestedEvaluationPackageId\)/);
assert.match(interpretation, /params\.set\("model_version_id", finalPromotion\.modelVersionId\)/);
assert.match(interpretation, /promoteExactCandidate\(/);
assert.match(interpretation, /candidateDecision: selectionDecision/);
assert.match(interpretation, /evaluationPackage: governedEvaluationPackage/);
assert.match(interpretation, /resolvePromotionReadiness/);
assert.match(interpretation, /data-testid="interpretation-selection-holdout-provenance"/);
assert.match(interpretation, /data-testid="exact-candidate-promotion"/);
assert.match(interpretation, /restoreExactFinalModel\(API_BASE, activeIdentity, target, \{/);
for (const exactHandoffField of [
  "candidateId: requestedCandidateId",
  "trainingRunId: requestedTrainingRunId",
  "candidateDecisionId: requestedCandidateDecisionId",
  "evaluationPackageId: requestedEvaluationPackageId",
]) {
  assert.match(interpretation, new RegExp(exactHandoffField));
}
assert.match(interpretation, /data-testid="durable-final-model-contract"/);
assert.match(interpretation, /!models\.length && finalModelReady && finalPromotion/);
assert.match(interpretation, /Registered final model recovered/);
assert.doesNotMatch(interpretation, /selectedCandidates\[0\]|LOCAL_SELECTED_INTERPRETATION_MODEL_KEY/);
assert.doesNotMatch(interpretation, /interpretation\/importance\?model=/);
assert.doesNotMatch(interpretation, /model=final/);
assert.doesNotMatch(interpretation, /promoteRfeFinalModel|\/interpretation\/rfe\/save_final/);

assert.match(promotion, /Promotion did not return a durable model_version_id/);
assert.match(promotion, /promotion\.status !== "finalized"/);
assert.match(promotion, /promotion\.artifactVerified !== true/);
assert.match(promotion, /promotion\.lineageStatus !== "verified"/);
assert.match(promotion, /model\.currentVersionId/);
assert.match(promotion, /\/model\/save_final/);
assert.match(promotion, /evaluation_package_id: evaluationPackageId/);
assert.match(promotion, /candidate_decision_id: readiness\.candidateDecisionId/);
assert.match(promotion, /resolvePromotionReadiness/);
assert.match(promotion, /version\.evaluationPackageId, evaluationPackageId/);
assert.match(promotion, /version\.candidateDecisionId, candidateDecisionId/);
assert.match(promotion, /evaluationPackageIntegrityStatus/);
assert.match(promotion, /promotionReadinessStatus/);
assert.doesNotMatch(promotion, /\/interpretation\/rfe\/save_final|\bkeep\b/);
assert.match(promotion, /recovery-status\?projectId=/);
assert.match(promotion, /recovery\.publicationStatus !== "finalized"/);
assert.match(promotion, /recovery\.artifactVerified !== true/);
assert.match(promotion, /normalizedExactHandoff/);
assert.match(promotion, /assertEqual\(restoredIdentity\.candidateId, exactHandoff\.candidateId, "candidate_id"\)/);
assert.match(promotion, /assertEqual\(restoredIdentity\.trainingRunId, exactHandoff\.trainingRunId, "training_run_id"\)/);
assert.match(promotion, /assertEqual\(restoredIdentity\.candidateDecisionId, exactHandoff\.candidateDecisionId, "candidate_decision_id"\)/);
assert.match(promotion, /assertEqual\(restoredIdentity\.evaluationPackageId, exactHandoff\.evaluationPackageId, "evaluation_package_id"\)/);
assert.match(promotion, /Promote this candidate explicitly before continuing; no current-model fallback was used/);
assert.doesNotMatch(promotion, /listModels|listVersions|\[0\]|latest/i);

assert.match(readiness, /FINAL_MODEL_DURABILITY_MESSAGE/);
assert.match(readiness, /modelVersionId &&/);
assert.match(readiness, /checksum &&/);
assert.match(readiness, /lineageComplete/);
assert.doesNotMatch(readiness, /if \(!expected \|\| !actual\) return true/);

console.log("Phase 2B1 frontend exact-candidate and durable-promotion contract checks passed (72 assertions).");

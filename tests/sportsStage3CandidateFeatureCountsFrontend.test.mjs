import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const source = await readFile(new URL("src/sports/cockpit/candidateFeatureCounts.ts", ROOT), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { candidateFeatureSummary, representativeCandidateAttempt } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);

function group({ corrected = true } = {}) {
  const featureCount = corrected ? 273 : 218;
  const attempt = {
    attemptId: "bound-attempt", runReceiptSha256: "bound-receipt", status: "COMPLETE",
    featureCount, orderedFeatures: Array.from({ length: featureCount }, (_, index) =>
      corrected && index >= 218 ? `source_${index - 218}__prior_v1__output` : `source_${index}`),
    folds: Array.from({ length: 5 }, (_, index) => ({ foldNumber: index + 1, preprocessing: corrected ? {
      kind: "MLB_SEMANTIC_TREATMENT_V1", actualSourceFeatureCount: 218, actualModelFeatureCount: 273,
      // Categorical expansion is not the model schema count.
      transformedFeatureCount: 324,
    } : { kind: "FOLD_LOCAL_REGISTERED_TRANSFORMATION_CONTRACT" } })),
  };
  return { featureCount, representativeAttemptId: "bound-attempt", immutableEvidenceIdentity: "bound-receipt", attempts: [attempt] };
}

test("corrected count breakdown comes from preserved fold receipts, not the dropped top-level DTO field", () => {
  const value = group();
  assert.equal(value.physicalSourceFeatureCount, undefined);
  assert.equal(candidateFeatureSummary(value), "273 model inputs · 218 source predictors + 55 added prior outputs");
  value.sourceFeatureCount = 273;
  value.attempts[0].sourceFeatureCount = 273;
  assert.equal(candidateFeatureSummary(value), "273 model inputs · 218 source predictors + 55 added prior outputs");
});

test("baseline source schema remains 218 without borrowing the successor counts", () => {
  assert.equal(candidateFeatureSummary(group({ corrected: false })), "218 source predictors");
});

test("a failed corrected attempt without fold evidence never calls its 273 inputs source predictors", () => {
  const value = group();
  value.attempts[0].status = "FAILED";
  value.attempts[0].folds = [];
  assert.equal(candidateFeatureSummary(value), "273 model inputs · source/output breakdown unavailable");
  value.attempts[0].orderedFeatures = [];
  assert.equal(candidateFeatureSummary(value), "273 model inputs · source/output breakdown unavailable");
});

test("optional physical count works without a fold payload and reconciles against existing folds", () => {
  const value = group();
  value.attempts[0].folds = [];
  value.attempts[0].physicalSourceFeatureCount = 218;
  assert.equal(candidateFeatureSummary(value), "273 model inputs · 218 source predictors + 55 added prior outputs");
  value.physicalSourceFeatureCount = 219;
  assert.match(candidateFeatureSummary(value), /breakdown unavailable/);
});

test("all fold counts must agree and be nonnegative exact integers", () => {
  for (const change of [
    { actualSourceFeatureCount: 219 }, { actualSourceFeatureCount: -1 },
    { actualSourceFeatureCount: 218.5 }, { actualSourceFeatureCount: "218" },
    { actualSourceFeatureCount: null }, { actualSourceFeatureCount: 274 },
    { actualModelFeatureCount: 324 }, { kind: "LEGACY_TRANSFORM" },
  ]) {
    const value = group();
    Object.assign(value.attempts[0].folds[4].preprocessing, change);
    assert.match(candidateFeatureSummary(value), /breakdown unavailable/);
  }
});

test("breakdown and detail use the exact representative attempt and immutable receipt", () => {
  const value = group();
  const other = structuredClone(value.attempts[0]);
  other.runReceiptSha256 = "different-receipt";
  other.folds.forEach((fold) => { fold.preprocessing.actualSourceFeatureCount = 200; });
  value.attempts.unshift(other);
  assert.equal(representativeCandidateAttempt(value).runReceiptSha256, "bound-receipt");
  assert.equal(candidateFeatureSummary(value), "273 model inputs · 218 source predictors + 55 added prior outputs");
});

test("Candidate Evaluation renders the receipt-bound summary with a pre-encoding explanation", async () => {
  const evaluation = await readFile(new URL("src/sports/cockpit/ProjectBoundCandidateEvaluation.tsx", ROOT), "utf8");
  assert.ok(evaluation.includes("{candidateFeatureSummary(group)}"));
  assert.ok(evaluation.includes("Model inputs are counted before categorical one-hot expansion."));
  assert.ok(evaluation.includes("representativeCandidateAttempt(group)"));
  assert.doesNotMatch(evaluation, /\{group\.featureCount\} source predictors/);
});

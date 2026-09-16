import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const [evaluation, api] = await Promise.all([
  readFile(new URL("src/sports/cockpit/ProjectBoundCandidateEvaluation.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/cockpit/projectModelLabApi.ts", ROOT), "utf8"),
]);

const includesAll = (source, values, label) => values.forEach((value) => {
  assert.ok(source.includes(value), `${label} missing: ${value}`);
});

test("Candidate Evaluation defaults, details, and finalist controls to one exact evidence source", () => {
  includesAll(evaluation, [
    'useState<FinalistEvaluationBatch>("CURRENT_BATCH")',
    "function groupsForSource",
    "data.currentBatches",
    "data.historicalEvidence.candidates",
    "hydrateSourceSelection",
    "setSelected(new Set(complete.slice(0, 2)",
    "setFinalists(new Set(complete.filter((item) => item.finalist)",
    'options={["CURRENT_BATCH", "HISTORICAL_BASELINE"]}',
    'data-testid="active-evaluation-source"',
    "sourceGroups.filter((item) => item.status === \"COMPLETE\")",
    ">{source} EVIDENCE ONLY</span>",
    "evidence from another source is never selected silently",
  ], "source-scoped Candidate Evaluation");
  assert.doesNotMatch(evaluation, /options=\{\["ALL", "CURRENT_BATCH", "HISTORICAL_BASELINE"\]\}/);
  assert.doesNotMatch(evaluation, /data\.candidateGroups\.filter\(\(item\) => item\.status === "COMPLETE"\)/);
});

test("changing evidence source cannot silently retain another source's local selection", () => {
  includesAll(evaluation, [
    "const changeSource = (nextSource: FinalistEvaluationBatch)",
    "setRationale(\"\")",
    "hydrateSourceSelection(data, nextSource)",
    "setSelected(new Set(complete.slice(0, 2)",
    "setFinalists(new Set(complete.filter((item) => item.finalist)",
    "otherSourceHasLatestSelection",
    'data-testid="other-source-finalist-history"',
    "remains immutable history; switch evidence sources to inspect it",
  ], "source-change reset and immutable-history note");
  assert.doesNotMatch(evaluation, /setSource\(value as typeof source\)/);
});

test("finalist saves bind the active source and exact attempt/run/receipt identities", () => {
  includesAll(evaluation, [
    '.filter((attempt) => attempt.status === "COMPLETE" && attempt.evidenceSource === source)',
    "candidateSelections",
    "candidateFingerprints: candidateSelections.map",
    "representativeAttemptId: representative.attemptId",
    "immutableEvidenceIdentity: representative.runReceiptSha256",
    "attemptEvidence: attempts.map",
    "runId: attempt.runId",
    "runReceiptSha256: attempt.runReceiptSha256",
    "evaluationBatch: source",
  ], "exact finalist evidence request");
  includesAll(api, [
    "export type FinalistEvaluationBatch",
    "export type FinalistCandidateSelection",
    "export type SaveProjectCandidateFinalistsPayload",
    "payload: SaveProjectCandidateFinalistsPayload",
    "payload,",
  ], "typed finalist API contract");
  assert.doesNotMatch(api, /evaluationBatch\s*=\s*"ALL_VERIFIED_PROJECT_EVIDENCE"/);
  assert.doesNotMatch(evaluation, /saveProjectCandidateFinalists\(projectId,\s*\[\.\.\.finalists\]/);
});

test("Model Refinement navigation follows only the latest persisted selection for the active source", () => {
  includesAll(evaluation, [
    "function latestFinalistSource",
    'item.authorityStatus === "CURRENT"',
    "persistedFinalistSource === source",
    "disabled={!persistedSourceFinalists}",
    "Save a ${source} finalist receipt before continuing.",
  ], "source-bound refinement handoff");
  assert.doesNotMatch(evaluation, /disabled=\{!data\.candidateGroups\.some\(\(item\) => item\.finalist\)\}/);
});

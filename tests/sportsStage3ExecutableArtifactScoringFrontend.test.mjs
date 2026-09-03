import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const ROOT = new URL("../", import.meta.url);
const [workflow, api] = await Promise.all([
  readFile(new URL("src/sports/cockpit/ProjectBoundDownstreamWorkflow.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/cockpit/projectModelLabApi.ts", ROOT), "utf8"),
]);

test("artifact API uses the bounded project-scoped plan and persisted-job endpoints", () => {
  for (const functionName of [
    "fetchProjectStage3ExecutableArtifact",
    "planProjectStage3ExecutableArtifact",
    "enqueueProjectStage3ExecutableArtifact",
    "fetchProjectStage3ExecutableArtifactJob",
    "cancelUnstartedProjectStage3ExecutableArtifact",
  ]) assert.match(api, new RegExp(`export async function ${functionName}`));

  assert.match(api, /sports\/stage3-executable-artifact`/);
  assert.match(api, /expectedPlanId: reviewedPlan\.planId/);
  assert.match(api, /expectedPlanChecksum: reviewedPlan\.checksum/);
  assert.match(api, /jobs\/\$\{encodeURIComponent\(jobId\)\}\/cancel-unstarted/);
  assert.match(api, /The executable-artifact job did not bind the exact reviewed plan/);
});

test("artifact responses are rejected unless exact authority and verified completion reconcile", () => {
  assert.match(api, /CURRENT_CHALLENGER_FINGERPRINT = "stage3-candidate-spec-1348285dbc6b9afb0445f0c26953564675c2afb4a4d838aff913314d85e71138"/);
  assert.match(api, /CURRENT_CHALLENGER_FEATURE_COUNT = 234/);
  assert.match(api, /CURRENT_OOF_ROWS = 501_590/);
  assert.match(api, /value\.workload\.modelFits !== 6/);
  assert.match(api, /value\.execution\.computeClass !== "VERY_HIGH"/);
  assert.match(api, /value\.status === "EXECUTABLE_RESEARCH_ARTIFACT_MATERIALIZED"/);
  assert.match(api, /metrics\.status === "PASS"/);
  assert.match(api, /reload\.freshProcess === true/);
  assert.match(api, /fixture\.status === "PASS"/);
  assert.match(api, /value\.status === "COMPLETE"/);
  assert.match(api, /exactExecutableArtifact\(value\.artifact, projectId\)/);
  assert.match(api, /EXECUTABLE_RESEARCH_ARTIFACT_VERIFICATION_FAILED/);
  assert.match(workflow, /The prior job record is retained, but the artifact is not treated as materialized or scoreable/);
  assert.match(api, /activity\.finalOotRowsAccessed !== 0/);
  assert.match(api, /activity\.modelsPromoted !== 0/);
  assert.match(api, /activity\.championsMutated !== 0/);
});

test("Step 15 reviews frozen science, restores real progress, and only renders verified completion", () => {
  assert.match(workflow, /BUILD EXECUTABLE RESEARCH ARTIFACT/);
  assert.match(workflow, /Review comes before execution/);
  assert.match(workflow, /Planning starts zero model fits/);
  assert.match(workflow, /Five-fold OOF/);
  assert.match(workflow, /Final development fit/);
  assert.match(workflow, /Expected artifacts/);
  assert.match(workflow, /Zero-OOT guarantee/);
  assert.match(workflow, /Launch exact reviewed artifact job/);
  assert.match(workflow, /fetchProjectStage3ExecutableArtifactJob/);
  assert.match(workflow, /window\.setInterval\(\(\) => void poll\(\), 2_500\)/);
  assert.match(workflow, /OOF rows persisted/);
  assert.match(workflow, /Fresh-process reload/);
  assert.match(workflow, /persistedArtifact\?\.status === "EXECUTABLE_RESEARCH_ARTIFACT_MATERIALIZED"/);
  assert.match(workflow, /persistedArtifact === null && artifactJob\?\.status === "COMPLETE"/);
  assert.match(workflow, /EXECUTABLE RESEARCH ARTIFACT MATERIALIZED/);
  assert.match(workflow, /Metric reproduction/);
  assert.match(workflow, /Verification fixture/);
});

test("governed-game API fails closed without lineup and starter authority", () => {
  for (const functionName of [
    "fetchProjectStage3GameScoring",
    "enqueueProjectStage3GameScoring",
    "fetchProjectStage3GameScoringJob",
  ]) assert.match(api, new RegExp(`export async function ${functionName}`));

  assert.match(api, /sports\/stage3-game-scoring`/);
  assert.match(api, /GOVERNED_PREGAME_LINEUP_STARTER_AUTHORITY_UNAVAILABLE/);
  assert.match(api, /Current game readiness must remain blocked and empty/);
  assert.match(api, /value\.games\.length !== 0/);
  assert.match(api, /value\.activity\.providerCalls !== 0/);
  assert.match(api, /value\.activity\.actualTargetOutcomesRead !== false/);
  assert.match(api, /exactEvidenceReference\(value\.lineupEvidence\)/);
  assert.match(api, /exactEvidenceReference\(value\.starterEvidence\)/);
});

test("whole-game results require genuine normalized and reconciled evidence", () => {
  assert.match(api, /exactJointDistribution\(value\.jointScoreDistribution, value\.draws\)/);
  assert.match(api, /exactScoreDistribution\(value\.runDifferenceDistribution, "homeRunDifference", value\.draws\)/);
  assert.match(api, /closeToOne\(value\.homeWinProbability \+ value\.awayWinProbability\)/);
  assert.match(api, /value\.actualTargetOutcomesRead !== false/);
  assert.match(api, /value\.sportsbookPredictorsUsed !== false/);
  assert.match(api, /reconciliation\.status === "PASSED"/);
  assert.match(api, /reconciliation\.legalBaseOutStates === true/);
  assert.match(api, /reconciliation\.allDrawsTerminated === true/);
  assert.match(api, /sha256\(value\.scoringReceiptSha256\)/);
});

test("Step 15 shows honest readiness, exact blocked reasons, and genuine score receipts", () => {
  assert.match(workflow, /SCORE GOVERNED GAMES/);
  assert.match(workflow, /Current game readiness: BLOCKED/);
  assert.match(workflow, /No provider was called, no game was fabricated, and no scoring job was created/);
  assert.match(workflow, /Game-by-game pregame evidence/);
  assert.match(workflow, /Lineup <b>\{game\.lineupEvidence\?\.status \?\? "MISSING"\}/);
  assert.match(workflow, /Starters <b>\{game\.starterEvidence\?\.status \?\? "MISSING"\}/);
  assert.match(workflow, /Score selected governed games/);
  assert.match(workflow, /data-testid="stage3-genuine-scoring-results"/);
  assert.match(workflow, /Most likely final score/);
  assert.match(workflow, /Feature vector SHA/);
  assert.match(workflow, /Scoring receipt SHA/);
});

test("research status labels remain exact and no production claim is introduced", () => {
  assert.match(workflow, /RESEARCH CHALLENGER/);
  assert.match(workflow, /NOT PROMOTED/);
  assert.match(workflow, /OOT LOCKED/);
  assert.doesNotMatch(workflow, />PRODUCTION READY</);
  assert.doesNotMatch(workflow, />DEPLOYABLE</);
});

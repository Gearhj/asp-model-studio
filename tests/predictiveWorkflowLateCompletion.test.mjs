import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

function between(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  assert.notEqual(start, -1, `missing start marker: ${startMarker}`);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.ok(end > start, `missing end marker after ${startMarker}: ${endMarker}`);
  return source.slice(start, end);
}

const completionEvidence = read("src/lib/predictiveWorkflowCompletionEvidence.ts");
const serverPersistence = read("src/lib/serverPersistence.ts");
const stepShell = read("src/components/StepShell.tsx");
const step08 = read("src/steps/Step08_Evaluation.tsx");
const step10 = read("src/steps/Step10_Scoring.tsx");
const step11 = read("src/steps/Step11_ModelDevelopmentDocument.tsx");
const step12 = read("src/steps/Step12_ModelImplementation.tsx");
const step13 = read("src/steps/Step13_ModelMonitoring.tsx");

const handleNext = between(stepShell, "const handleNext = async () =>", "\n  return (");
const step08Advance = between(step08, "async function openInterpretation", "\n  async function openComparison");
const step11Continue = between(step11, "async function handleContinue()", "\n  return (");

test("late-workflow completion evidence requires full exact promoted lineage and a durable database mirror", () => {
  const requiredModelFields = [
    "modelId",
    "modelVersionId",
    "modelName",
    "candidateId",
    "trainingRunId",
    "featureManifestVersion",
    "validationDesignId",
    "splitId",
    "artifactChecksum",
    "artifactVerificationStatus",
    "target",
  ];

  for (const field of requiredModelFields) {
    assert.match(
      completionEvidence,
      new RegExp(`\\b${field}: string;`),
      `${field} must be mandatory in the exact promoted-model identity`,
    );
    assert.doesNotMatch(
      completionEvidence,
      new RegExp(`\\b${field}\\?: string;`),
      `${field} must not be optional`,
    );
    assert.match(
      completionEvidence,
      new RegExp(`${field}: input\\.model\\.${field}\\.trim\\(\\)`),
      `${field} must be normalized from the exact supplied lineage`,
    );
  }

  assert.match(completionEvidence, /requireCanonicalDatasetIdentity\(/);
  assert.match(completionEvidence, /Object\.values\(exactModel\)\.some\(\(value\) => !value\)/);
  assert.match(completionEvidence, /exactModel\.artifactVerificationStatus !== "verified"/);
  assert.match(completionEvidence, /buildCanonicalEvidenceEnvelope\(identity, \{/);
  assert.match(completionEvidence, /workflowCompletionContract: "predictive_workflow_completion_v1"/);
  assert.match(completionEvidence, /completionAuthority: "durable_canonical_evidence"/);
  assert.match(completionEvidence, /browserFallbackUsed: false/);
  assert.match(
    completionEvidence,
    /return createEvidence\([\s\S]*buildPredictiveWorkflowCompletionEvidence\(input\),[\s\S]*\{ requireDatabaseMirror: true \},[\s\S]*\);/,
  );
});

test("Steps 10 through 13 persist their exact completion evidence before the workflow completion save path", () => {
  const pages = [
    ["step10", step10],
    ["step11", step11],
    ["step12", step12],
    ["step13", step13],
  ];

  for (const [stepId, source] of pages) {
    assert.match(source, /persistPredictiveWorkflowCompletionEvidence/);
    assert.match(source, new RegExp(`stepId: "${stepId}"`));
  }

  for (const field of [
    "modelId",
    "modelVersionId",
    "modelName",
    "candidateId",
    "trainingRunId",
    "featureManifestVersion",
    "validationDesignId",
    "splitId",
    "artifactChecksum",
    "artifactVerificationStatus",
    "target",
  ]) {
    assert.match(step10, new RegExp(`\\b${field}:`), `Step 10 must supply ${field}`);
  }
  for (const source of [step11, step12, step13]) {
    assert.match(source, /model: promotedModel\.identity/);
  }

  const callbackIndex = handleNext.indexOf("const result = await onNext()");
  const workflowSnapshotIndex = handleNext.indexOf("workflowCompletionSnapshot(");
  const effectiveSaveIndex = handleNext.indexOf("await saveWorkflowStateToDatabase(completedSnapshot, currentStep)");
  const localCompletionIndex = handleNext.indexOf("markComplete(");
  const navigationIndex = handleNext.indexOf("navigate(guardedTargetPath)");
  assert.ok(callbackIndex >= 0);
  assert.ok(workflowSnapshotIndex > callbackIndex);
  assert.ok(effectiveSaveIndex > workflowSnapshotIndex);
  assert.ok(localCompletionIndex > effectiveSaveIndex);
  assert.ok(navigationIndex > localCompletionIndex);

  const step11EvidenceIndex = step11Continue.indexOf("await persistPredictiveWorkflowCompletionEvidence(");
  const step11SnapshotIndex = step11Continue.indexOf("workflowCompletionSnapshot(");
  const step11SaveIndex = step11Continue.indexOf('await saveWorkflowStateToDatabase(completedSnapshot, "step11")');
  const step11NavigationIndex = step11Continue.indexOf("navigate(projectWorkflowRoute(");
  assert.ok(step11EvidenceIndex >= 0);
  assert.ok(step11SnapshotIndex > step11EvidenceIndex);
  assert.ok(step11SaveIndex > step11SnapshotIndex);
  assert.ok(step11NavigationIndex > step11SaveIndex);
});

test("every Evaluation navigation route converges on the effective Step 08 completion save", () => {
  assert.equal(
    (step08.match(/\bnavigate\(/g) ?? []).length,
    1,
    "Evaluation must have one navigation sink so no action can bypass effective completion",
  );
  const snapshotIndex = step08Advance.indexOf("workflowCompletionSnapshot(");
  const effectiveSaveIndex = step08Advance.indexOf('await saveWorkflowStateToDatabase(completedSnapshot, "step08")');
  const failureIndex = step08Advance.indexOf("if (!persisted)");
  const localCompletionIndex = step08Advance.indexOf('markComplete("step08")');
  const navigationIndex = step08Advance.indexOf("navigate(projectWorkflowRoute(");

  assert.ok(snapshotIndex >= 0);
  assert.ok(effectiveSaveIndex > snapshotIndex);
  assert.ok(failureIndex > effectiveSaveIndex);
  assert.ok(localCompletionIndex > failureIndex);
  assert.ok(navigationIndex > localCompletionIndex);
  assert.match(step08, /async function openComparison\(\)[\s\S]*await openInterpretation\(selectedModel, comparison\)/);
  assert.match(step08, /onNextClick=\{\(\) => void openComparison\(\)\}/);
  assert.match(step08, /onInterpret=\{\(\) => openInterpretation\(model\)\}/);
  assert.match(step08, /onOpen=\{\(\) => openInterpretation\(model\)\}/);
});

test("an optional required step accepts a workflow save only when the backend returns current effective completion", () => {
  const effectiveCheck = between(
    serverPersistence,
    "function responseEffectivelyCompletesStep(",
    "\nexport async function saveWorkflowStateToDatabase",
  );
  const durableSave = between(
    serverPersistence,
    "export async function saveWorkflowStateToDatabase(",
    "\nfunction readOptimizationState",
  );

  assert.match(effectiveCheck, /effectiveCompletedSteps/);
  assert.match(effectiveCheck, /effectiveSteps\?\.\[stepId\]/);
  assert.match(effectiveCheck, /completed\.includes\(stepId\)/);
  assert.match(effectiveCheck, /step\?\.effectiveStatus === "complete"/);
  assert.match(effectiveCheck, /step\?\.lineageStatus === "current"/);

  assert.match(durableSave, /requiredEffectiveStepId\?: string/);
  assert.match(
    durableSave,
    /requiredEffectiveStepId[\s\S]*&& !responseEffectivelyCompletesStep\(response, requiredEffectiveStepId\)/,
  );
  assert.match(durableSave, /PersistenceResponseValidationError/);
  assert.match(durableSave, /return false;/);
  assert.match(durableSave, /return true;/);
});

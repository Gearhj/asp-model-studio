import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

const featurePage = read("src/steps/Step05_EncodingScaling.tsx");
const stepShell = read("src/components/StepShell.tsx");
const featureClient = read("src/lib/featureManifest.ts");
const evidenceGraph = read("src/lib/evidenceGraph.ts");
const mddCompletion = read("src/lib/featureEngineeringCompletion.ts");
const serverPersistence = read("src/lib/serverPersistence.ts");
const outliersPage = read("src/steps/Step04_Outliers.tsx");
const missingValuesPage = read("src/steps/Step04_MissingValues.tsx");

function between(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  assert.notEqual(start, -1, `missing start marker: ${startMarker}`);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.ok(end > start, `missing end marker after ${startMarker}: ${endMarker}`);
  return source.slice(start, end);
}

const finalizer = between(
  featurePage,
  "async function finalizeFeatureSetAndContinue()",
  "async function completeStep(",
);
const completeStep = between(
  featurePage,
  "async function completeStep(",
  "const documentationStatus =",
);
const handleNext = between(
  stepShell,
  "const handleNext = async () =>",
  "\n  return (",
);
const materializeClient = between(
  featureClient,
  "export async function materializeFeatureManifest(",
  "export async function confirmFeatureManifest(",
);
const createEvidence = between(
  evidenceGraph,
  "export async function createEvidence(",
  "export async function updateEvidence(",
);
const continueGate = between(
  featurePage,
  "const continueDisabledReason =",
  "const continueStatus =",
);

test("completion failures identify the exact stage and stop before navigation", () => {
  for (const stage of [
    "Validating and saving the versioned Feature Manifest",
    "Previewing included deterministic features",
    "Materializing included deterministic features",
    "Confirming the exact saved and materialized feature contract",
    "Recording durable Feature Engineering evidence",
    "Verifying the live preparation and MDD contract",
  ]) {
    assert.match(finalizer, new RegExp(stage));
  }

  assert.match(finalizer, /let failedStage\s*=/);
  assert.match(finalizer, /failedStage = label;[\s\S]*setAdvancingStage\(label\)/);
  assert.match(
    finalizer,
    /Feature Engineering failed during \$\{failedStage\}:/,
  );
  assert.match(finalizer, /catch \(cause\)[\s\S]*return false;/);
  assert.doesNotMatch(finalizer, /\bnavigate\s*\(/);

  const completionIndex = handleNext.indexOf("await onNext()");
  const rejectionGateIndex = handleNext.indexOf("if (result === false) return;");
  const navigationIndex = handleNext.indexOf("navigate(guardedTargetPath)");
  assert.ok(completionIndex >= 0);
  assert.ok(rejectionGateIndex > completionIndex);
  assert.ok(navigationIndex > rejectionGateIndex);
});

test("MDD draft attachment failure is deferred after durable Feature Engineering evidence", () => {
  assert.match(
    finalizer,
    /let mddSyncWarning = "";/,
    "Feature Engineering must explicitly track a deferred MDD attachment warning",
  );
  assert.match(
    finalizer,
    /try \{[\s\S]*Updating the exact Model Development Document draft[\s\S]*syncFeatureEngineeringMdd\([\s\S]*\} catch \(cause\) \{/,
    "MDD attachment must be attempted, but handled independently from the navigation gate",
  );
  assert.match(
    finalizer,
    /mddSyncWarning\s*=\s*[\s\S]*ATLAS could not attach the Feature Engineering evidence to the MDD draft/,
  );
  assert.match(
    finalizer,
    /const documentation = await runStage\([\s\S]*Verifying the live preparation and MDD contract/,
    "preparation documentation readback remains a required gate after deferred MDD attachment",
  );
  assert.match(
    finalizer,
    /mddSyncWarning[\s\S]*MDD draft attachment was deferred/,
    "the user-facing success path must disclose the deferred documentation attachment",
  );
});

test("the CTA uses a synchronous ref lock to reject duplicate submissions", () => {
  assert.match(featurePage, /const advancingRef = useRef\(false\)/);
  const guardIndex = finalizer.indexOf("if (advancingRef.current) return false;");
  const lockIndex = finalizer.indexOf("advancingRef.current = true;");
  const firstAwaitIndex = finalizer.indexOf("await ");
  const finallyIndex = finalizer.indexOf("finally {");
  const unlockIndex = finalizer.indexOf("advancingRef.current = false;");

  assert.ok(guardIndex >= 0, "missing duplicate-submission guard");
  assert.ok(lockIndex > guardIndex, "lock must follow the guard");
  assert.ok(lockIndex < firstAwaitIndex, "lock must be acquired before the first await");
  assert.ok(finallyIndex > firstAwaitIndex, "unlock must be protected by finally");
  assert.ok(unlockIndex > finallyIndex, "finally must always release the lock");
});

test("preview includes selected drafts only and materialization uses the exact saved contract", () => {
  assert.match(
    finalizer,
    /previewFeaturePlan\([\s\S]*currentDrafts\.filter\(\(draft\) => draft\.selected\)[\s\S]*currentManifest\.manifest_hash/,
  );
  assert.match(
    finalizer,
    /materializeFeatureManifest\([\s\S]*currentManifest\.manifest_hash,[\s\S]*previewHash/,
  );
  assert.match(
    featurePage,
    /drafts\.filter\(\(draft\) => draft\.selected\)\.every\(\(draft\) =>[\s\S]*feature\.materialization_status === "materialized"/,
  );

  assert.match(materializeClient, /manifest_version: manifestVersion/);
  assert.match(materializeClient, /preview_hash: previewHash/);
  assert.doesNotMatch(
    materializeClient,
    /\bfeatures\s*:/,
    "materialization must replay the saved server manifest, not accept caller feature definitions",
  );
});

test("Feature Engineering awaits the durable evidence database mirror", () => {
  assert.match(
    completeStep,
    /await createEvidence\([\s\S]*\{ requireDatabaseMirror: true \}\)/,
  );
  assert.match(
    createEvidence,
    /const mirrored = await saveEvidenceToDatabase\(/,
  );
  assert.match(
    createEvidence,
    /options\.requireDatabaseMirror && !mirrored[\s\S]*throw new Error/,
  );
  assert.match(completeStep, /return evidence;/);
});

test("completion attaches and verifies one exact Feature Engineering MDD record", () => {
  assert.match(
    finalizer,
    /await runStage\([\s\S]*Updating the exact Model Development Document draft[\s\S]*syncFeatureEngineeringMdd\([\s\S]*datasetIdentity,[\s\S]*evidence,[\s\S]*currentManifest/,
  );
  assert.match(
    mddCompletion,
    /project-context\/\$\{encodeURIComponent\(projectId\)\}/,
  );
  assert.match(
    mddCompletion,
    /\/model-documentation\/ensure-working-draft[\s\S]*templateType: "model_development_document"[\s\S]*const matching = await loadFeatureEngineeringMdds\(projectId\)/,
    "a fresh project must idempotently ensure one draft MDD and then re-read exact project scope",
  );
  assert.match(mddCompletion, /document\.documentStatus === "working_draft"/);
  assert.match(mddCompletion, /matching\.length !== 1/);
  assert.match(mddCompletion, /sectionId: "feature_engineering"/);
  for (const field of [
    "project_id",
    "dataset_id",
    "dataset_version_id",
    "manifest_hash",
    "materialization_hash",
  ]) {
    assert.match(
      mddCompletion,
      new RegExp(`item\\.${field} === (?:identity\\.${field}|manifest\\.${field})`),
      `MDD verification is missing exact ${field}`,
    );
  }
  assert.match(mddCompletion, /matchingAttachments\.length !== 1/);
});

test("durable workflow completion is accepted before local completion and navigation", () => {
  assert.match(featurePage, /\bnextRequireDurableWorkflowSave\b/);
  assert.match(
    stepShell,
    /nextRequireDurableWorkflowSave \|\| snapshot\.projectType === "predictive-modeling"/,
  );
  assert.match(
    serverPersistence,
    /export async function saveWorkflowStateToDatabase\([\s\S]*method: "PUT"/,
  );

  const durableSaveIndex = handleNext.indexOf(
    "await saveWorkflowStateToDatabase(completedSnapshot, currentStep)",
  );
  const durableFailureIndex = handleNext.indexOf("if (!persisted)");
  const localCompletionIndex = handleNext.indexOf("markComplete(");
  const navigationIndex = handleNext.indexOf("navigate(guardedTargetPath)");
  assert.ok(durableSaveIndex >= 0);
  assert.ok(durableFailureIndex > durableSaveIndex);
  assert.match(
    handleNext.slice(durableFailureIndex, localCompletionIndex),
    /throw new Error/,
  );
  assert.ok(localCompletionIndex > durableFailureIndex);
  assert.ok(navigationIndex > localCompletionIndex);
});

test("a stale split is visible context, not a Feature Engineering navigation gate", () => {
  assert.doesNotMatch(finalizer, /split_status|splitStatus/);
  assert.doesNotMatch(continueGate, /split_status|splitStatus|\bstale\b/i);
  assert.match(
    featurePage,
    /StatusMetric label="Split status"[\s\S]*warning=\{manifest\?\.split_status === "stale"\}/,
  );
});

test("Outliers, Missing Values, and Feature Engineering use the shared measured action bar", () => {
  for (const [label, source] of [
    ["Outliers", outliersPage],
    ["Missing Values", missingValuesPage],
    ["Feature Engineering", featurePage],
  ]) {
    assert.match(source, /<StepShell\b[\s\S]*\bnextAlwaysVisible\b/, `${label} must opt into the shared bar`);
  }
  assert.match(stepShell, /resolveWorkflowActionBarBounds\(/);
  assert.match(stepShell, /workflowBarRef/);
  assert.match(stepShell, /ResizeObserver/);
  assert.doesNotMatch(stepShell, /lg:left-\[17rem\]|lg:right-6/);
});

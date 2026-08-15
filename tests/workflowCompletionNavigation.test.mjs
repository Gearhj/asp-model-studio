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

const stepShell = read("src/components/StepShell.tsx");
const step11 = read("src/steps/Step11_ModelDevelopmentDocument.tsx");
const serverPersistence = read("src/lib/serverPersistence.ts");
const localProjects = read("src/lib/localProjects.ts");
const handleNext = between(stepShell, "const handleNext = async () =>", "\n  return (");
const step11Continue = between(step11, "async function handleContinue()", "\n  return (");

test("every predictive StepShell continuation waits for durable workflow completion", () => {
  assert.match(
    handleNext,
    /nextRequireDurableWorkflowSave \|\| snapshot\.projectType === "predictive-modeling"/,
  );
  const snapshotIndex = handleNext.indexOf("workflowCompletionSnapshot(");
  const durableSaveIndex = handleNext.indexOf("await saveWorkflowStateToDatabase(completedSnapshot, currentStep)");
  const durableFailureIndex = handleNext.indexOf("if (!persisted)");
  const localCompletionIndex = handleNext.indexOf("markComplete(");
  const compatibilitySaveIndex = handleNext.indexOf("saveActiveProjectBeforeNavigation(");
  const navigationIndex = handleNext.indexOf("navigate(guardedTargetPath)");

  assert.ok(snapshotIndex >= 0);
  assert.ok(durableSaveIndex > snapshotIndex);
  assert.ok(durableFailureIndex > durableSaveIndex);
  assert.ok(localCompletionIndex > durableFailureIndex);
  assert.ok(compatibilitySaveIndex > localCompletionIndex);
  assert.ok(navigationIndex > compatibilitySaveIndex);
  assert.match(
    handleNext.slice(compatibilitySaveIndex, navigationIndex),
    /completedSnapshot/,
    "the compatibility mirror must reuse the accepted next-step snapshot instead of recomputing the old browser route",
  );
  assert.match(
    handleNext.slice(durableFailureIndex, localCompletionIndex),
    /throw new Error\(DURABLE_WORKFLOW_COMPLETION_ERROR\)/,
  );
});

test("Documentation Review uses the same fail-closed durable continuation", () => {
  const snapshotIndex = step11Continue.indexOf("workflowCompletionSnapshot(");
  const durableSaveIndex = step11Continue.indexOf('await saveWorkflowStateToDatabase(completedSnapshot, "step11")');
  const durableFailureIndex = step11Continue.indexOf("if (!persisted)");
  const localCompletionIndex = step11Continue.indexOf('markComplete("step11")');
  const compatibilitySaveIndex = step11Continue.indexOf("upsertProjectSnapshot(completedSnapshot");
  const navigationIndex = step11Continue.indexOf("navigate(projectWorkflowRoute(");

  assert.ok(snapshotIndex >= 0);
  assert.ok(durableSaveIndex > snapshotIndex);
  assert.ok(durableFailureIndex > durableSaveIndex);
  assert.ok(localCompletionIndex > durableFailureIndex);
  assert.ok(compatibilitySaveIndex > localCompletionIndex);
  assert.ok(navigationIndex > compatibilitySaveIndex);
  assert.doesNotMatch(step11Continue, /upsertProjectFromState/);
});

test("the durable error is generic and the delayed project mirror remains compatibility-only", () => {
  assert.match(
    serverPersistence,
    /DURABLE_WORKFLOW_COMPLETION_ERROR[\s\S]*could not durably record this workflow step's completion/,
  );
  assert.doesNotMatch(serverPersistence, /Feature Engineering completion/);
  assert.match(localProjects, /queueProjectDatabaseSave\(record\.snapshot\)/);
  assert.match(
    localProjects,
    /saveActiveProjectBeforeNavigation\([\s\S]*snapshotOverride\?: WorkflowProjectSnapshot[\s\S]*const snapshot = snapshotOverride \?\? createSnapshotFromState\(state\)[\s\S]*upsertProjectSnapshot\(snapshot, "browser"\)/,
  );
  assert.match(serverPersistence, /setTimeout\([\s\S]*void saveProjectToDatabase\(queued\)/);
  assert.match(handleNext, /await saveWorkflowStateToDatabase\(completedSnapshot, currentStep\)/);
});

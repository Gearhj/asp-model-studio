import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

const panel = read("src/components/StepPythonPanel.tsx");
const studio = read("src/steps/NotebookStudio.tsx");
const notebookApi = read("src/lib/notebookStudio.ts");

test("predictive code panels require backend-confirmed scope while other workflows keep their saved context", () => {
  assert.match(
    panel,
    /const predictiveProject =[\s\S]*"predictive-modeling"/,
  );
  assert.match(
    panel,
    /if \(!predictiveProject\) \{[\s\S]*setReproducibilityContext\(null\)[\s\S]*return;/,
  );
  assert.match(
    panel,
    /const exactDataAcquisitionContextReady = predictiveProject[\s\S]*Boolean\(currentReproducibilityContext\)[\s\S]*Boolean\(String\(projectType/,
  );
  assert.match(
    panel,
    /: predictiveProject[\s\S]*previewRows: \[\][\s\S]*: \{[\s\S]*previewRows: activeDataset\?\.rows\.slice\(0, 500\)/,
    "Predictive requests must fail closed; non-predictive requests retain preview context.",
  );
  assert.match(panel, /canSave: exactDataAcquisitionContextReady/);
});

test("Notebook Studio links carry the exact target and Analysis Partition identity", () => {
  for (const field of [
    "projectId",
    "datasetId",
    "versionId",
    "target",
    "eventValue",
    "nonEventValue",
    "targetContractId",
    "analysisPartitionId",
    "analysisPartitionRevision",
  ]) {
    assert.ok(panel.includes(`${field}:`), `Missing Notebook Studio route field: ${field}`);
  }
  assert.match(panel, /new URLSearchParams\(\{/);
  assert.match(panel, /to=\{notebookStudioPath\}/);

  assert.match(studio, /const routedProjectId = searchParams\.get\("projectId"\) \|\| projectId/);
  assert.match(studio, /const routedTargetContractId = searchParams\.get\("targetContractId"\) \|\| ""/);
  assert.match(studio, /const routedAnalysisPartitionId = searchParams\.get\("analysisPartitionId"\) \|\| ""/);
  assert.match(studio, /routedAnalysisPartitionRevision > 0/);
  assert.match(
    studio,
    /identityUnchanged[\s\S]*targetContractId: identityUnchanged[\s\S]*analysisPartitionRevision: identityUnchanged/,
    "Changing the selected version must invalidate inherited predictive scope.",
  );
});

test("saved notebooks and run-cell requests transport the complete predictive scope", () => {
  for (const field of [
    "target",
    "eventValue",
    "nonEventValue",
    "targetContractId",
    "analysisPartitionId",
    "analysisPartitionRevision",
  ]) {
    assert.match(
      notebookApi,
      new RegExp(`${field}\\?:`),
      `AtlasNotebook must persist ${field}.`,
    );
    assert.match(
      notebookApi,
      new RegExp(`${field}: context\\.${field}`),
      `run-cell must send ${field}.`,
    );
  }
});

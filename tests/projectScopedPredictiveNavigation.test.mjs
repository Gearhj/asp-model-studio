import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);

const renderedNavigationFiles = [
  "src/components/eda/TargetIntelligenceWorkspace.tsx",
  "src/steps/Step02_EDA.tsx",
  "src/steps/Step04_Outliers.tsx",
  "src/steps/Step06_BalancingSplit.tsx",
  "src/steps/Step06_Train.tsx",
  "src/steps/Step08_Evaluation.tsx",
  "src/steps/Step10_Scoring.tsx",
  "src/steps/Step11_ModelDevelopmentDocument.tsx",
  "src/steps/Dashboard.tsx",
  "src/steps/CreditRiskStudio.tsx",
  "src/steps/IntelligentWorkbench.tsx",
  "src/steps/ModelDiagnostics.tsx",
  "src/steps/ModelDocumentationStudio.tsx",
  "src/steps/NotebookExport.tsx",
  "src/steps/ProjectOverview.tsx",
];

const forbiddenDirectNavigation = [
  /\bhref\s*=\s*["'`]\/step(?:0[0-9]|1[0-3])\b/,
  /\bto\s*=\s*["'`]\/step(?:0[0-9]|1[0-3])\b/,
  /\bnavigate\(\s*["'`]\/step(?:0[0-9]|1[0-3])\b/,
  /window\.location\.(?:assign|replace)\(\s*["'`]\/step(?:0[0-9]|1[0-3])\b/,
  /window\.location\.href\s*=\s*["'`]\/step(?:0[0-9]|1[0-3])\b/,
];

test("rendered Predictive navigation never targets an unscoped legacy step route", async () => {
  for (const file of renderedNavigationFiles) {
    const source = await readFile(new URL(file, ROOT), "utf8");
    for (const pattern of forbiddenDirectNavigation) {
      assert.doesNotMatch(source, pattern, `${file} contains direct legacy workflow navigation`);
    }
  }
});

test("high-impact workflow transitions preserve the exact project and target suffix", async () => {
  const [target, eda, split, training, evaluation, scoring] = await Promise.all(
    [
      "src/components/eda/TargetIntelligenceWorkspace.tsx",
      "src/steps/Step02_EDA.tsx",
      "src/steps/Step06_BalancingSplit.tsx",
      "src/steps/Step06_Train.tsx",
      "src/steps/Step08_Evaluation.tsx",
      "src/steps/Step10_Scoring.tsx",
    ].map((file) => readFile(new URL(file, ROOT), "utf8")),
  );

  assert.match(target, /navigate\(projectWorkflowRoute\(projectId, "\/step01"\)\)/);
  assert.match(target, /to=\{projectWorkflowRoute\(projectId, "\/step00"\)\}/);
  assert.match(eda, /projectWorkflowRoute\(projectId, "\/step01#analysis-partition-readiness"\)/);
  assert.match(split, /projectWorkflowRoute\(projectId, "\/step01"\)\}\?analysisPartition=reset/);
  assert.match(training, /to=\{projectWorkflowRoute\(projectId, "\/step05"\)\}/);
  assert.match(evaluation, /navigate\(projectWorkflowRoute\(projectId, `\/step09\?candidate_id=/);
  assert.match(scoring, /projectWorkflowRoute\(projectId, `\/step08\?scoringRunId=/);
});

test("utility surfaces scope workflow links or fail closed to project selection", async () => {
  const sources = await Promise.all(
    [
      "src/steps/Dashboard.tsx",
      "src/steps/IntelligentWorkbench.tsx",
      "src/steps/ModelDiagnostics.tsx",
      "src/steps/ModelDocumentationStudio.tsx",
      "src/steps/NotebookExport.tsx",
      "src/steps/ProjectOverview.tsx",
    ].map((file) => readFile(new URL(file, ROOT), "utf8")),
  );

  for (const source of sources) {
    assert.match(source, /projectWorkflowRoute/);
  }
  assert.match(sources[0], /projectId \? projectWorkflowRoute\(projectId, targetPath\) : "\/projects\/open"/);
  assert.match(sources[2], /projectId \? projectWorkflowRoute\(projectId, "\/step10"\) : "\/projects\/open"/);
  assert.match(sources[3], /projectId \? projectWorkflowRoute\(projectId, "\/step11"\) : "\/projects\/open"/);
  assert.match(sources[4], /readiness\.projectId \? projectWorkflowRoute\(readiness\.projectId, "\/step01"\) : "\/projects\/open"/);
  assert.match(sources[5], /projectId \? projectWorkflowRoute\(projectId, targetPath\) : "\/projects\/open"/);
});

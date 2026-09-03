import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const ROOT = new URL("../", import.meta.url);
const [workflow, api] = await Promise.all([
  readFile(new URL("src/sports/cockpit/ProjectBoundDownstreamWorkflow.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/cockpit/projectModelLabApi.ts", ROOT), "utf8"),
]);
const cockpit = await readFile(new URL("src/sports/cockpit/PaModelingCockpit.tsx", ROOT), "utf8");
const guidedWorkflow = await readFile(new URL("src/sports/workflow/GuidedWorkflow.tsx", ROOT), "utf8");

test("Steps 12-15 expose a project-bound research decision path", () => {
  for (const component of [
    "ProjectBoundCalibration",
    "ProjectBoundGameEvaluation",
    "ProjectBoundChampionDecision",
    "ProjectBoundRegistryHandoff",
  ]) assert.match(workflow, new RegExp(`export function ${component}`));

  assert.match(workflow, /You do not need to beat the current model to proceed/);
  assert.match(workflow, /NOT EVALUATED/);
  assert.match(workflow, /No reloadable row-level OOF probability artifact was persisted/);
  assert.match(workflow, /Current Gold does not provide governed target-game lineup and starter authority/);
  assert.match(workflow, /NOT DEPLOYABLE/);
  assert.match(workflow, /NOT EXPORTED/);
  assert.match(workflow, /Final OOT locked/);
});

test("downstream writes use the bounded endpoints and dispositions", () => {
  assert.match(api, /sports\/stage3-downstream`/);
  assert.match(api, /DEFER_RECALIBRATION/);
  assert.match(api, /DEFER_UNTIL_EXECUTABLE_ARTIFACT/);
  assert.match(api, /REGISTER_RESEARCH_CHALLENGER/);
  assert.match(api, /KEEP_INCUMBENT/);
  assert.match(api, /DEFER_DECISION/);
  assert.match(api, /finalOotLocked !== true/);
  assert.match(api, /modelsPromoted \?\? 0\) !== 0/);
});

test("downstream navigation cannot bypass the earliest missing prerequisite", () => {
  assert.match(workflow, /function earliestMissingPrerequisite/);
  assert.match(workflow, /return \{ id: "calibration", label: "Step 12 · Calibration" \}/);
  assert.match(workflow, /return \{ id: "simulation", label: "Step 13 · Simulation & Game-Level Evaluation" \}/);
  assert.match(workflow, /return hasResearchSelection \? null : \{ id: "champion", label: "Step 14 · Champion \/ Challenger Decision" \}/);
  assert.match(workflow, /usePrerequisiteRedirect\(data, "simulation", go\)/);
  assert.match(workflow, /usePrerequisiteRedirect\(data, "champion", go\)/);
  assert.match(workflow, /earliestMissingPrerequisite\(data, "registry"\)/);
  assert.match(workflow, /Go to \{prerequisite\.label\}/);
  assert.match(cockpit, /suppressNext=\{Boolean\(currentGoldReview\)/);
});

test("held-closed messages are explicit non-interactive status text", () => {
  assert.match(workflow, /role="status" aria-label="Implementation status"/);
  assert.match(workflow, /Status: implementation held closed until a deployable artifact exists/);
  assert.match(guidedWorkflow, /role="status" aria-label="Workflow status"/);
  assert.match(guidedWorkflow, /Status: project-bound development only · promotion unavailable/);
});

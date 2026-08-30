import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");

const [handoff, cockpit, steps, stageContent, workflow, client] = await Promise.all([
  read("src/sports/cockpit/ProjectBoundStage3.tsx"),
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/sports/cockpit/cockpitSteps1.tsx"),
  read("src/sports/workflow/GuidedStageContent.tsx"),
  read("src/sports/workflow/GuidedWorkflow.tsx"),
  read("src/sports/workflow/currentGoldDataReview.ts"),
]);

test("Stage 3 inherits the project-scoped Stage 2 authority automatically", () => {
  assert.ok(workflow.includes("useProjectStage3DataAuthority"));
  assert.ok(workflow.includes("focus.number === 2"));
  assert.ok(stageContent.includes("currentGoldReview={currentGoldReview}"));
  assert.ok(stageContent.includes("ProjectBoundStage3Intro"));
  assert.ok(cockpit.includes("currentGoldReview={c.currentGoldReview}"));
  assert.ok(steps.includes("ProjectBoundModelingCharter"));
  assert.ok(steps.includes("ProjectBoundPopulation"));
  assert.ok(client.includes("populationReconciliation"));
  assert.ok(client.includes("/sports/stage3-eda/metadata"));
  assert.ok(client.includes('scope !== "DEVELOPMENT_ONLY"'));
  assert.ok(client.includes("finalOotTargetAccessed") && client.includes("legacyGlobalMatrixUsed") && client.includes("providerCalls !== 0"));
  assert.ok(client.includes("data: { stage3Handoff: CurrentGoldDataReview }"));
});

test("the Modeling Charter is meaningful, editable, and has no inherited champion", () => {
  assert.ok(handoff.includes("Can a current, leakage-safe plate-appearance model improve"));
  for (const field of [
    "Modeling question",
    "Prediction unit",
    "Eight-class PA target",
    "Downstream game-simulation use",
    "Primary model-selection metric",
    "Secondary metrics",
    "Comparison benchmarks",
    "Forecast-time restrictions",
    "Deployment intent",
  ]) assert.ok(handoff.includes(field), `missing charter field: ${field}`);
  assert.ok(handoff.includes("Multiclass log loss"));
  assert.ok(handoff.includes('value="None yet"'));
  assert.doesNotMatch(handoff, /Project champion[^\n]*D3|Project champion[^\n]*C4/);
  assert.ok(workflow.includes("Project champion: None yet"));
  assert.ok(!workflow.includes("Adopt Current PA Champion & Continue"));
});

test("the active population and governed target are exact and final OOT stays locked", () => {
  for (const name of [
    "STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE",
    "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH",
  ]) assert.ok(handoff.includes(`"${name}"`), `missing governed class ${name}`);
  assert.ok(handoff.includes("Use Project-Bound Current Gold Population — Recommended"));
  assert.ok(handoff.includes("review.goldAuthority.rowCount"));
  assert.ok(handoff.includes("review.matrix.development.rows"));
  assert.ok(handoff.includes("review.matrix.finalOot.rows"));
  assert.ok(handoff.includes("context?.addedFeatureCount"));
  assert.ok(handoff.includes("context?.totalFeatureCount"));
  assert.ok(handoff.includes("Excluded source PAs"));
  assert.ok(handoff.includes("exclusionReasonStatus"));
  assert.ok(handoff.includes('value="LOCKED"'));
  assert.ok(handoff.includes("No final-OOT outcome counts are exposed"));
});

test("legacy datasets are absent from the primary page and later legacy execution paths fail closed", () => {
  assert.ok(handoff.includes("Advanced authority, manifests, hashes, and identity details"));
  assert.doesNotMatch(handoff, /Show legacy\/reference datasets|MLB_PA_V1 \/ Base-22|INCOMPATIBLE_WITH_CURRENT_PROJECT_CONTRACT/);
  assert.ok(handoff.includes("ProjectBoundLaterStepGate"));
  assert.ok(cockpit.includes('currentGoldReview ? null : "/cockpit/objective"'));
  assert.ok(cockpit.includes("ProjectBoundDataProfile"));
  for (const label of [
    "Outliers", "Missing Values", "Feature Engineering",
    "Player Segmentation", "Temporal Split", "Model Laboratory", "Hyperparameter Tuning",
    "Evaluation", "Calibration", "Simulation Impact", "Champion / Challenger", "Registry & Evidence",
  ]) assert.ok(cockpit.includes(`stepLabel="${label}"`), `legacy fallback remains for ${label}`);
  assert.ok(workflow.includes("Legacy modeling execution held closed"));
  assert.doesNotMatch(workflow, /Open full PA Modeling Cockpit/);
});

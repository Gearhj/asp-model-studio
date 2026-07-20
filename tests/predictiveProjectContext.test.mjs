import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const [page, context, persistence, shell] = await Promise.all([
  read("src/steps/Step00_ProjectContext.tsx"),
  read("src/lib/projectContext.ts"),
  read("src/lib/projectPersistence.ts"),
  read("src/components/StepShell.tsx"),
]);

for (const value of [
  "Step 0: Define the Modeling Mission", "Project Setup", "Decision foundation",
  "Business Decision and Intended Use", "Target and Population", "Observation and Performance Windows",
  "Project Context Review", "Model ID", "Project Name", "Project Type", "Model Type", "Deployment Mode",
  "Business Objective", "Intended Model Use", "Optional Use Boundaries", "Approved Uses", "Prohibited Uses",
  "Target Definition", "Population Definition", "Observation Window", "Performance Window",
  "Modeling Mission Summary",
  "Continue to Data Acquisition",
]) assert.match(page, new RegExp(value), `Project Context must include ${value}`);

for (const value of [
  "Generate Modeling Mission Summary",
  "AI draft - not saved until accepted",
  "Accept Summary",
  "Edit Summary",
  "Discard",
  "This summary is not required to complete the page",
]) assert.match(page, new RegExp(value), `Project Context must include AI summary control: ${value}`);

for (const value of [
  "modelId", "projectName", "modelType", "businessObjective", "intendedModelUse", "targetDefinition",
  "populationDefinition", "observationWindow", "performanceWindow", "deploymentMode", "approvedUses",
  "prohibitedUses", "modelTypeSelection", "modelingMissionSummary", "acceptedAiDrafts", "completionStatus",
  "completedAt", "completedBy", "updatedBy",
]) assert.match(context, new RegExp(value), `Persisted Project Context field missing: ${value}`);

assert.match(page, /scrollIntoView/);
assert.match(page, /savePredictiveProjectContextToDatabase/);
assert.match(page, /buildMissionSummary\(context\)/);
assert.match(persistence, /modeling-tool-project-context/);
assert.match(shell, /nextExtraActions/);
assert.match(page, /showDeveloperTools=\{false\}/, "Project Context must suppress the generic code panel.");
assert.doesNotMatch(page, /Save Draft/, "Project Context must not expose a separate Save Draft button.");
assert.doesNotMatch(page, /Validate Page/, "Project Context must not expose a separate Validate Page button.");
assert.doesNotMatch(page, /Mark Page Complete/, "Project Context must not expose a separate Mark Page Complete button.");
assert.doesNotMatch(page, /nextExtraActions=/, "Project Context must only show Continue to Data Acquisition in the sticky footer.");
assert.doesNotMatch(page, /Validation Plan/, "Project Context must not render the legacy Validation Plan selector.");
assert.doesNotMatch(page, /data-testid="validation-contract-readonly"/, "Project Context must not show validation status before Balance & Split.");
assert.doesNotMatch(page, /data-testid="target-column-binding"/, "Project Context must not show target binding before Data Acquisition.");
assert.doesNotMatch(page, /<b>Validation:<\/b>/, "Project Context must not show a validation cell.");
assert.doesNotMatch(page, /TRAIN \/ TEST \/ OOT/, "Project Context must not render premature validation choices.");
assert.doesNotMatch(page, /validationDesign/, "Project Context must not treat the legacy validation field as authoritative.");
assert.doesNotMatch(page, /Model Charter/, "Project Context must not render the large Model Charter section.");
assert.doesNotMatch(page, /Project Context readiness/, "Project Context must not render the readiness strip.");
assert.doesNotMatch(page, /data-testid="model-charter"/, "Project Context must not expose the old charter test id.");
assert.doesNotMatch(page, /context\.modelingMissionSummary \|\| buildMissionSummary|context\.modelingMissionSummary \|\| generatedMissionSummary|const missionSummary/, "Project Context must not auto-generate a visible mission summary.");
assert.doesNotMatch(page, /How to Choose|How to choose/, "Model Type and Deployment Mode must keep normal dropdown behavior without Project Context help popups.");
assert.doesNotMatch(page, /const aiActions:[\s\S]*"Draft from current project context"[\s\S]*\];/, "Project Context narrative fields must not show the AI action dropdown.");
assert.doesNotMatch(page, /modelingMissionSummary: generatedMissionSummary/, "Completing the page must not require or persist an automatic summary.");

for (const prohibited of [
  "Target Definition and Label Governance", "Initial Key Model Risks", "Success Criteria and Performance Requirements",
  "Governance and Stakeholders", "Planned Development and Validation Structure", "Leakage Prevention Strategy",
  "Target Column Name", "Positive Class Value", "Population Start Date", "Stakeholders",
]) assert.doesNotMatch(page, new RegExp(prohibited), `Project Context must not visibly include ${prohibited}`);

assert.doesNotMatch(page, /\u2014/, "Visible Project Context copy must not use em dashes");
console.log("Simplified Predictive Project Context contract tests passed.");

import fs from "node:fs";
import assert from "node:assert/strict";

const workflows = fs.readFileSync("src/config/workflows.ts", "utf8");
const placeholderStep = fs.readFileSync("src/steps/WorkflowPlaceholderStep.tsx", "utf8");
const newProject = fs.readFileSync("src/steps/NewProject.tsx", "utf8");
const overview = fs.readFileSync("src/steps/ProjectOverview.tsx", "utf8");
const packageJson = JSON.parse(fs.readFileSync("package.json", "utf8"));

const expectedAbSteps = [
  "Project Context",
  "Experiment Setup",
  "Population and Eligibility",
  "Treatment / Control Design",
  "Data Acquisition",
  "Randomization Check",
  "Metrics Setup",
  "Power and Sample Size",
  "Experiment EDA",
  "Experiment Analysis",
  "Segment Analysis",
  "Business Impact",
  "Decision Recommendation",
  "Documentation Review",
  "Monitoring / Follow-up",
];

assert.equal(packageJson.scripts["test:project-types"], "node tests/projectTypes.test.mjs");
assert.match(workflows, /id: "ab-testing"/);
assert.match(workflows, /projectType: "ab-testing"/);
assert.match(workflows, /placeholderSteps\("ab-testing"/);

let lastIndex = -1;
for (const label of expectedAbSteps) {
  const index = workflows.indexOf(`["${label}"`);
  assert.notEqual(index, -1, `Missing A/B workflow step: ${label}`);
  assert.ok(index > lastIndex, `A/B workflow step is out of order: ${label}`);
  lastIndex = index;
}

assert.match(newProject, /getWorkflowForProjectType\(projectType\)/);
assert.match(newProject, /workflowId: selectedWorkflow\.id/);
assert.match(newProject, /projectType/);
assert.match(newProject, /requiresModelId = projectType === "predictive-modeling"/);
assert.match(newProject, /projectIdentifier = modelId\.trim\(\) \|\| `\$\{selectedWorkflow\.id\}-\$\{Date\.now\(\)\}`/);
assert.match(newProject, /disabled=\{!canStartProject\}/);
assert.match(placeholderStep, /projectType === "ab-testing"/);
assert.match(placeholderStep, /<AbTestingWorkflowStep/);
assert.match(placeholderStep, /A\/B Testing Workflow/);
assert.match(overview, /A\/B Testing Summary/);
assert.match(overview, /AB_MARKETING_DEFAULTS/);

console.log("project type workflow checks passed");

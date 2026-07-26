// UX-NEWPROJECT-001 (generalized): focused source-level checks proving the
// unified Project Setup section is now the SAME shared, schema-driven
// component for every workflow type -- not a Predictive-Modeling-only branch.
// Follows this repo's established pattern (see tests/projectTypes.test.mjs,
// tests/workflowLibrary.test.mjs) of asserting against the real .ts/.tsx
// source rather than introducing a new component-test framework (none exists
// in this repo today -- see the final report for why real behavioral/visual
// coverage instead lives in the Playwright spec tests/e2e/new-project-ux.spec.ts).
import fs from "node:fs";
import assert from "node:assert/strict";

const pageSource = fs.readFileSync("src/steps/NewProject.tsx", "utf8");
const configSource = fs.readFileSync("src/config/projectSetupForms.ts", "utf8");
const packageJson = JSON.parse(fs.readFileSync("package.json", "utf8"));

assert.equal(packageJson.scripts["test:new-project"], "node tests/newProjectUx.test.mjs");

// ---- Shared architecture: ONE component, config-driven, no per-workflow forks ----

assert.match(pageSource, /function UnifiedProjectSetupSection/, "Expected the generalized shared component.");
assert.doesNotMatch(pageSource, /PredictiveModelingSetupSection/, "The old Predictive-Modeling-only component must not remain.");
assert.equal((pageSource.match(/<UnifiedProjectSetupSection/g) || []).length, 1, "Expected exactly one render call site (no per-workflow duplication).");
assert.doesNotMatch(pageSource, /requiresModelId/, "Validation must be config-driven, not a hardcoded Predictive-Modeling boolean.");
assert.doesNotMatch(pageSource, /<AtlasPageHero/, "The old light hero must be fully removed (no per-workflow branch back to it).");
assert.doesNotMatch(pageSource, /Project Details/, "The old right-column 'Project Details' panel must be fully removed.");
assert.doesNotMatch(pageSource, /<aside/, "No right-column form/aside should remain on this page.");

// Structural: the unified section is CALLED before the Workflow Library.
const usageIndex = pageSource.indexOf("<UnifiedProjectSetupSection");
const workflowLibraryIndex = pageSource.indexOf('title="Choose Project Type"');
assert.notEqual(usageIndex, -1);
assert.notEqual(workflowLibraryIndex, -1);
assert.ok(usageIndex < workflowLibraryIndex, "Unified setup section must be rendered before the Workflow Library.");

// Darker, flat (no-gradient) ATLAS treatment, shared by every workflow type (one definition).
const definitionIndex = pageSource.indexOf('data-testid="unified-setup-section"');
assert.notEqual(definitionIndex, -1);
assert.match(pageSource, /bg-blue-950/, "Expected a flat dark-navy background.");
assert.doesNotMatch(pageSource.slice(definitionIndex - 300, definitionIndex + 3000), /gradient/i, "The unified section must not use a gradient.");

// Guidance and completion logic live in the shared config module, called once, not
// duplicated per workflow inside the page component.
assert.match(pageSource, /computeSetupGuidance\(setupConfig, setupValues\)/);
assert.match(pageSource, /isProjectSetupComplete\(setupConfig, setupValues\)/);
assert.doesNotMatch(pageSource, /"Enter both required fields to continue\."/, "Guidance copy must live in the config module, not be duplicated in the page.");

// ---- Config module: one entry per exposed workflow type, verbatim copy ----

const expectedEntries = [
  "predictive-modeling", "ab-testing", "optimization", "time_series_forecasting",
  "llm_generative_ai", "graph-analytics", "computer-vision", "reinforcement-learning", "custom-workflow",
];
for (const key of expectedEntries) {
  // Object keys may or may not be quoted depending on whether they're valid JS
  // identifiers (e.g. "ab-testing" needs quotes, optimization does not).
  assert.match(configSource, new RegExp(`"?${key}"?:\\s*\\{`), `Missing config entry for ${key}`);
}

const expectedHeadings = [
  "Create the model record that will anchor this project",
  "Create the project record that will anchor this experiment",
  "Create the project record that will anchor this optimization study",
  "Create the project record that will anchor this forecasting study",
  "Create the project record that will anchor this AI workflow",
  "Create the project record that will anchor this graph analysis",
  "Create the project record that will anchor this computer vision workflow",
  "Create the project record that will anchor this reinforcement-learning study",
  "Create the project record that will anchor this workflow",
];
for (const heading of expectedHeadings) {
  assert.match(configSource, new RegExp(heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing heading: ${heading}`);
}

const expectedButtonLabels = [
  "Create Predictive Modeling Project",
  "Create Experimentation Project",
  "Create Optimization Project",
  "Create Time Series & Forecasting Project",
  "Create LLM / Generative AI Project",
  "Create Graph Analytics Project",
  "Create Computer Vision Project",
  "Create Reinforcement Learning Project",
  "Create Custom Workflow Project",
];
for (const label of expectedButtonLabels) {
  assert.match(configSource, new RegExp(`buttonLabel: "${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`), `Missing button label: ${label}`);
}

// Predictive Modeling: both Model Name and Model ID required (unchanged behavior).
assert.match(configSource, /"predictive-modeling":\s*\{[\s\S]{0,900}?nameField:\s*\{[\s\S]{0,150}?label: "Model Name"[\s\S]{0,150}?required: true/);
assert.match(configSource, /"predictive-modeling":\s*\{[\s\S]{0,1300}?modelIdField:\s*\{[\s\S]{0,150}?label: "Model ID #"[\s\S]{0,150}?required: true/);

// Other workflow types: Project Name required, Model ID optional (not forced required).
assert.match(configSource, /optimization:\s*\{[\s\S]{0,700}?nameField:\s*\{ label: "Project Name",[\s\S]{0,80}?required: true \}/);
assert.match(configSource, /optimization:\s*\{[\s\S]{0,700}?modelIdField: OPTIONAL_MODEL_ID_FIELD/);

// Custom Workflow: Model ID has no product meaning here -- hidden entirely, not
// merely optional (no field, no placeholder rendered).
assert.match(configSource, /"custom-workflow":\s*\{[\s\S]{0,900}?modelIdField: null/);

// Guidance is computed generically from field validity -- not forked per workflow type.
// Uses each field's short guidanceLabel ("Model ID"), not the punctuated visible
// label ("Model ID #"), so sentences read naturally -- matches the brief's exact
// copy ("Enter a Model ID to continue.", not "...Model ID #...").
assert.match(configSource, /export function computeSetupGuidance/);
assert.match(configSource, /guidanceLabel: "Model ID"/);
assert.match(configSource, /"Enter both required fields to continue\."/);
assert.match(configSource, /`Enter a \$\{missing\[0\]\.label\} to continue\.`/);
assert.match(configSource, /`\$\{config\.modelIdField\.guidanceLabel \?\? config\.modelIdField\.label\} is optional\.`/);
assert.match(configSource, /"Ready to create the project\."/);

// Placeholders: real content is never pre-filled; a fixed example placeholder for
// Predictive Modeling, a generic placeholder elsewhere.
assert.match(configSource, /"Credit Card Fraud Detection Model"/);
assert.match(configSource, /PROJECT_NAME_PLACEHOLDER = "Untitled ATLAS Project"/);
assert.match(pageSource, /const \[modelId, setModelId\] = useState\(""\)/);
assert.match(pageSource, /const \[projectName, setProjectName\] = useState\(""\)/);

// Accessibility: required semantics driven by config, optional field exposed as
// aria-required={false} (via config.modelIdField.required), not omitted.
assert.match(pageSource, /aria-required="true"/);
assert.match(pageSource, /aria-required=\{config\.modelIdField\.required\}/);
assert.match(pageSource, /aria-invalid=\{nameInvalid\}/);
assert.match(pageSource, /aria-describedby=\{`\$\{nameFieldId\}-helper`\}/);
assert.match(pageSource, /role="status" aria-live="polite" data-testid="setup-guidance"/);

// Defensive fallback exists for any ProjectType not explicitly configured.
assert.match(configSource, /export function resolveProjectSetupFormConfig/);
assert.match(configSource, /buttonLabel: "Create Project"/);

console.log("newProjectUx.test.mjs: all checks passed.");

// UX-GLOBAL-HTC-001: the "How to Choose" expandable guidance pattern (dropdown-
// explanation popovers, selected-option definition cards, and inline "Best used
// when" / "Avoid when" panels tied to dropdowns) has been removed globally --
// not just on Project Context. This is a dedicated source-level regression
// test (following this repo's established fs.readFileSync + assert.match
// pattern -- see tests/projectTypes.test.mjs) so any future reintroduction of
// the pattern anywhere in the app fails a focused, fast, non-browser check.
import fs from "node:fs";
import assert from "node:assert/strict";

const packageJson = JSON.parse(fs.readFileSync("package.json", "utf8"));
assert.equal(packageJson.scripts["test:how-to-choose-removal"], "node tests/howToChooseRemoval.test.mjs");

// 1/6. The two files that implemented the global chooser-guidance mechanism no
// longer exist at all -- not merely emptied or hidden.
assert.equal(fs.existsSync("src/components/AtlasSelectDecisionSupport.tsx"), false, "AtlasSelectDecisionSupport.tsx (the global dark dropdown-explanation popover) must be deleted, not just unmounted.");
assert.equal(fs.existsSync("src/lib/selectDecisionSupport.ts"), false, "selectDecisionSupport.ts (the definition/useWhen/example data source) must be deleted -- dead configuration used only by the removed panels.");
assert.equal(fs.existsSync("tests/selectDecisionSupport.test.mjs"), false, "The obsolete dedicated test for the removed system must be deleted.");
assert.equal(packageJson.scripts["test:select-guidance"], undefined, "The obsolete test:select-guidance script must be removed from package.json.");

// 2/7/8/9. Scan every user-facing .tsx page/component for the banned patterns --
// covers shared components, Predictive Modeling (Step00_ProjectContext.tsx),
// and non-Predictive workflows (WorkflowPlaceholderStep.tsx covers Experimental
// Design/A-B Testing; OptimizationWorkflowStep.tsx and
// TransportationOptimizationWorkflow.tsx cover Optimization).
function listTsxFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = `${dir}/${entry.name}`;
    if (entry.isDirectory()) out.push(...listTsxFiles(full));
    else if (entry.name.endsWith(".tsx") || entry.name.endsWith(".ts")) out.push(full);
  }
  return out;
}

const bannedPatterns = [
  [/How to [Cc]hoose/, "'How to Choose' text"],
  [/\bAbSelectionGuide\b/, "AbSelectionGuide component"],
  [/\bDropdownDefinition\b/, "DropdownDefinition component"],
  [/\bAtlasSelectDecisionSupport\b/, "AtlasSelectDecisionSupport component"],
  [/getSelectionGuidance/, "getSelectionGuidance call/import"],
  [/Best used when/, "'Best used when' phrase"],
  [/Avoid when[:"]/, "'Avoid when' phrase"],
];

const offenders = [];
for (const file of listTsxFiles("src")) {
  const source = fs.readFileSync(file, "utf8");
  for (const [pattern, description] of bannedPatterns) {
    if (pattern.test(source)) offenders.push(`${file}: ${description}`);
  }
}
assert.deepEqual(offenders, [], `Found reintroduced How-to-Choose patterns:\n${offenders.join("\n")}`);

// 3/4/5. Specific named surfaces the brief calls out, confirmed individually
// (redundant with the scan above, but pins the exact required files so a
// rename/move of the scan logic can't silently stop covering them).
const projectContext = fs.readFileSync("src/steps/Step00_ProjectContext.tsx", "utf8");
assert.doesNotMatch(projectContext, /How to [Cc]hoose/, "Project Context (Deployment Mode) must not render a How to Choose panel.");

const workflowPlaceholder = fs.readFileSync("src/steps/WorkflowPlaceholderStep.tsx", "utf8");
assert.doesNotMatch(workflowPlaceholder, /How to [Cc]hoose/, "Shared/Experimental-Design workflow page must not render a How to Choose panel.");

const optimizationStep = fs.readFileSync("src/features/optimization/OptimizationWorkflowStep.tsx", "utf8");
assert.doesNotMatch(optimizationStep, /How to [Cc]hoose|Best used when/, "Optimization workflow must not render a How to Choose panel or 'Best used when' guidance.");

const modelingApp = fs.readFileSync("src/apps/ModelingApp.tsx", "utf8");
assert.doesNotMatch(modelingApp, /AtlasSelectDecisionSupport/, "The app shell must no longer globally mount the select decision-support popover.");

console.log("howToChooseRemoval.test.mjs: all checks passed.");

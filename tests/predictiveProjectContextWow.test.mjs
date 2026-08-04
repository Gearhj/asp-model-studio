import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const [page, contextSource, writingAssist, guide, shell, persistence] = await Promise.all([
  read("src/steps/Step00_ProjectContext.tsx"),
  read("src/lib/projectContext.ts"),
  read("src/components/LLMWritingAssist.tsx"),
  read("src/components/CopilotCard.tsx"),
  read("src/components/StepShell.tsx"),
  read("src/lib/projectPersistence.ts"),
]);

const exactModelTypes = [
  "Generic Binary Classification",
  "Fraud Classification",
  "Transaction Fraud Classification",
  "Application Fraud Classification",
  "Identity Fraud Classification",
  "Account Takeover Classification",
  "First-Party Fraud Classification",
  "Credit Risk Classification",
  "Customer Response Classification",
  "Attrition Classification",
  "Other Binary Classification",
];
const deploymentModes = ["Research", "Development", "Validation", "Limited Pilot", "Production Candidate", "Production"];
const aiActions = [
  "Draft from current project context",
  "Improve clarity",
  "Rewrite for business audience",
  "Rewrite for data scientist",
  "Rewrite for model validator",
  "Shorten",
  "Expand",
  "Identify missing information",
];

assert.match(page, /export default function Step00ProjectContext/, "Project Context page must load as an exported route component.");
assert.match(page, /Step 0: Define the Modeling Mission/);
assert.match(page, /data-testid="model-identity-card"/);
assert.match(page, /Project Setup/);
assert.match(page, /Decision foundation/);
assert.match(page, /Business Decision and Intended Use/);
assert.match(page, /Target and Population/);
assert.match(page, /Observation and Performance Windows/);
assert.match(page, /Project Context Review/);
assert.match(page, /context\.modelTypeSelection/);
assert.match(page, /context\.fraudDetails\.deploymentMode/);

assert.doesNotMatch(page, /Validation Plan/, "Visible legacy Validation Plan must be removed.");
assert.doesNotMatch(page, /TRAIN \/ TEST \/ OOT/, "Premature validation choices must not be visible.");
assert.doesNotMatch(page, /validationDesign/, "Legacy validation values must not drive this page.");
assert.doesNotMatch(page, /Pending Data Review/);
assert.doesNotMatch(page, /\/balancing_split\/status/);
assert.doesNotMatch(page, /Read-only contract from Balance &amp; Split/);

for (const option of exactModelTypes) assert.match(contextSource, new RegExp(option), `Missing professional model type: ${option}`);
for (const option of deploymentModes) assert.match(page, new RegExp(option), `Missing deployment mode: ${option}`);
assert.match(page, /readOnly aria-readonly="true"/, "Model identity controls must preserve read-only fields.");
assert.match(page, /value="Predictive Modeling" readOnly/);

for (const action of aiActions) assert.match(writingAssist, new RegExp(action), `Missing ATLAS AI action: ${action}`);
assert.match(writingAssist, /Proposed draft/);
assert.match(writingAssist, /Your text is unchanged until you accept it/);
assert.match(writingAssist, /onAcceptDraft\(draft, draftAction\)/);
assert.match(writingAssist, /strictGrounding/);
assert.match(writingAssist, /Use only supplied accepted project context\. Do not invent facts\./);
assert.match(page, /acceptedAiDrafts/);
assert.match(page, /acceptedBy: currentUserId \|\| current\.updatedBy/);

assert.match(page, /<details[^>]*className="mt-4/s, "Optional Use Boundaries must be collapsed by default.");
for (const field of ["approvedUses", "prohibitedUses", "humanReviewRequired", "overrideAuthority"]) assert.match(page, new RegExp(field));
assert.doesNotMatch(page, /data-testid="target-column-binding"/);
assert.doesNotMatch(page, /localDataset\?\.target/);
assert.match(page, /Physical columns are selected during Data Acquisition/);

assert.match(page, /reviewItems\(context\)/);
assert.match(page, /Complete/);
assert.match(page, /Incomplete/);
assert.match(page, /Needs clarification/);
assert.match(page, /buildMissionSummary/);
assert.match(page, /Copy Summary/);
assert.match(page, /Save to Evidence Center/);
assert.match(page, /draft documentation language/);

assert.match(page, /completionStatus: "complete"/);
assert.match(page, /nextDisabled=\{!isComplete\}/);
assert.match(page, /onNext=\{continueToDataAcquisition\}/);
assert.match(shell, /if \(result === false\) return/);
assert.match(page, /markWorkflowStepComplete\("step00"\)/);
assert.match(page, /useProjectContextAutosave/);
assert.match(page, /publishSavedProjectMetadata/);
assert.match(page, /onHydrated: \(hydrated\) => setContext\(hydrated\)/);
assert.match(page, /sourceRoute: "\/step00"/);
assert.doesNotMatch(page, /validationDesign: saved/, "Evidence payload must not promote a legacy Project Context validation choice.");

assert.match(guide, /buildProjectContextRecommendations/);
assert.match(guide, /Complete the modeling mission/);
assert.match(guide, /physical target binding/);
assert.match(guide, /Project Context is complete/);
assert.match(guide, /if \(context\.route === "\/step00"\) return buildProjectContextRecommendations\(context\)/, "Project Context must use its dedicated recommendation contract.");

assert.match(persistence, /readStorageKeys\(localStorage, \["modeling-tool-project-context"\]\)/, "Project reopen snapshots must retain Project Context.");
for (const field of ["modelTypeSelection", "modelingMissionSummary", "acceptedAiDrafts", "completionStatus", "completedAt", "completedBy", "updatedBy"]) {
  assert.match(contextSource, new RegExp(field), `Missing persisted field: ${field}`);
}

class MemoryStorage {
  #values = new Map();
  getItem(key) { return this.#values.has(key) ? this.#values.get(key) : null; }
  setItem(key, value) { this.#values.set(key, String(value)); }
  removeItem(key) { this.#values.delete(key); }
  clear() { this.#values.clear(); }
}

globalThis.localStorage = new MemoryStorage();
const transpiled = ts.transpileModule(contextSource, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText;
const contextModule = await import(`data:text/javascript;base64,${Buffer.from(transpiled).toString("base64")}`);

localStorage.setItem("modeling-tool-project-context", JSON.stringify({
  modelId: "model-ctx-001",
  projectName: "Fraud Review Prioritization",
  modelType: "fraud",
  businessObjective: "Prioritize potentially fraudulent transactions for investigator review.",
  intendedModelUse: "Investigators use ranked alerts and retain final disposition authority.",
  targetDefinition: "Confirmed transaction fraud after investigation.",
  populationDefinition: "Eligible card transactions presented for authorization.",
  observationWindow: "Transaction attributes available at authorization time.",
  performanceWindow: "Fraud outcome finalized within 90 days after the transaction.",
  fraudDetails: { deploymentMode: "Pilot", validationDesign: "Separate TRAIN / TEST / OOT", completedAt: "2026-07-18T10:00:00.000Z" },
}));
const migrated = contextModule.loadProjectContext();
assert.equal(migrated.modelTypeSelection, "Fraud Classification");
assert.equal(migrated.fraudDetails.deploymentMode, "Limited Pilot");
assert.equal(migrated.completionStatus, "complete");
assert.equal(migrated.completedAt, "2026-07-18T10:00:00.000Z");
assert.equal(migrated.fraudDetails.validationDesign, "Separate TRAIN / TEST / OOT", "Legacy value remains compatible but hidden.");

const persisted = contextModule.saveProjectContext({
  ...migrated,
  modelTypeSelection: "Transaction Fraud Classification",
  modelingMissionSummary: "A grounded modeling mission summary.",
  acceptedAiDrafts: [{ field: "businessObjective", action: "Improve clarity", text: "Grounded accepted text.", acceptedAt: "2026-07-18T11:00:00.000Z", acceptedBy: "user_test" }],
  completionStatus: "complete",
  completedAt: "2026-07-18T11:05:00.000Z",
  completedBy: "user_test",
  updatedBy: "user_test",
});
const reopened = contextModule.loadProjectContext();
assert.equal(reopened.projectName, persisted.projectName);
assert.equal(reopened.modelTypeSelection, "Transaction Fraud Classification");
assert.equal(reopened.modelingMissionSummary, "A grounded modeling mission summary.");
assert.equal(reopened.acceptedAiDrafts[0].acceptedBy, "user_test");
assert.equal(reopened.completedBy, "user_test");

console.log("Predictive Modeling Project Context wow contract tests passed.");

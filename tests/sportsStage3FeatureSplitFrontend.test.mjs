import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");
const [cockpit, feature, split, api, modelingApp] = await Promise.all([
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/sports/cockpit/ProjectBoundFeatureEngineering.tsx"),
  read("src/sports/cockpit/ProjectBoundSplitBalance.tsx"),
  read("src/sports/cockpit/projectFeatureSplitApi.ts"),
  read("src/apps/ModelingApp.tsx"),
]);

function includesAll(source, values, label) {
  for (const value of values) assert.ok(source.includes(value), `${label} missing: ${value}`);
}

test("project-bound Feature Engineering and Split & Balance replace the legacy held-closed surfaces", () => {
  includesAll(cockpit, [
    "ProjectBoundFeatureEngineering",
    "ProjectBoundSplitBalance",
    'label: "Split & Balance"',
  ], "cockpit routing");
  assert.doesNotMatch(cockpit, /stepLabel="Feature Engineering"/);
  assert.doesNotMatch(cockpit, /stepLabel="Temporal Split"/);
});

test("the standalone cockpit hydrates the exact backend project and redacted Stage 3 authority", () => {
  includesAll(modelingApp, [
    "useCanonicalSportsProject",
    "useProjectStage3DataAuthority",
    "projectIdentity.status === \"ready\"",
    "currentGoldReview={currentGoldReview}",
    "projectName={projectName}",
    "Project authority unavailable",
  ], "standalone project authority");
  assert.doesNotMatch(modelingApp, /<PaModelingCockpit projectId=\{projectId\} \/>/);
});

test("Feature Engineering presents a decision-first, project-bound candidate workspace", () => {
  includesAll(feature, [
    "Core Gold 48",
    "Candidate library",
    "Contextual candidates",
    "Feature families",
    "Interactions",
    "Final OOT",
    "No global transformation fit",
    "Recommended experimental plan",
    "Seven declared feature families",
    "Candidate feature-set builder",
    "Registered candidate sets",
    "Family coverage heatmap",
    "Missingness by family",
    "Project-bound feature inventory",
    "Transformation contracts",
    "Bounded interaction workspace",
    "Fit independently within each chronological training fold.",
    "Current Gold unchanged",
    "Final OOT target inaccessible",
    "Model activity 0",
  ], "feature workspace");
});

test("feature inventory and builder expose the required filters, details, versioning, and registration controls", () => {
  includesAll(feature, [
    "Search feature inventory",
    "Feature family filter",
    "Core contextual filter",
    "Feature status filter",
    "Feature data type filter",
    "Forecast availability filter",
    "Simulation state filter",
    "Interaction membership filter",
    "Source availability filter",
    "Save immutable draft",
    "Register candidate set",
    "Duplicate",
    "Retire registered feature set",
    "feature-engineering-detail-drawer",
    "Descriptive target comparison",
    "Development-only and not a selection decision.",
  ], "feature decisions");
});

test("Split & Balance exposes honest five-fold design, balance, manual validation, and immutable registration", () => {
  includesAll(split, [
    "Split & Balance",
    "five expanding-window folds",
    "Canonical game",
    "Date atomic",
    "No random split",
    "Natural base rates",
    "Preprocessing: training fold only",
    "Recommended chronological design",
    "Exact five-fold contract",
    "Training growth and validation size",
    "Overall eight-class balance",
    "Class balance by fold",
    "NO RANDOM OVERSAMPLING",
    "NO SMOTE",
    "NO UNDERSAMPLING",
    "Cold start, missingness, and feature-set coverage",
    "Recommended automatic",
    "Manual dates",
    'max="2026-08-13"',
    "Random split unavailable",
    "Split quality gates",
    "Save immutable draft",
    "Register split contract",
    "Project champion:",
    "None yet",
  ], "split workspace");
});

test("Split & Balance locks the supported design and requires explicit manual gaps", () => {
  includesAll(split, [
    "const foldCount = 5",
    'LockedOption label="Fold count" value="5 (required)"',
    "disabled: mode === \"AUTOMATIC\"",
    "const [allowGaps, setAllowGaps] = useState(false)",
    'allowGaps: mode === "MANUAL" ? allowGaps : false',
    "Allow explicit validation gaps",
    "must be assigned exactly once",
  ], "supported split controls");
  assert.doesNotMatch(split, /setFoldCount/);
  assert.doesNotMatch(split, /<NumberInput label="Fold count"/);
});

test("visible split edits cannot silently register an older immutable draft", () => {
  includesAll(split, [
    "currentDesignFingerprint",
    "currentDraftFingerprint",
    "validationStale",
    "draftMatchesVisibleDesign",
    "Unsaved changes.",
    "Save a new exact draft before registration.",
    "Reload exact saved design",
    "nextContractState.draft ?? nextContractState.registered",
    "versionDesignFingerprint(restored)",
  ], "saved split integrity");
  assert.match(
    split,
    /disabled=\{mutation\.busy \|\| !contractState\.draft \|\| validationStale \|\| !draftMatchesVisibleDesign/,
  );
  const registerBlock = split.slice(split.indexOf("const register ="), split.indexOf("if (state.status"));
  assert.doesNotMatch(registerBlock, /selectedFeatureSetIds|\bnotes\b/);
});

test("split history, comparison, and handoff use immutable registered identities", () => {
  includesAll(split, [
    "Immutable split version history",
    "Selected split version comparison",
    "Compare version A",
    "Compare version B",
    "Save superseding draft",
    "registeredFeatureIdentitiesAvailable",
    "registered split contract’s",
  ], "split lifecycle");
  includesAll(api, [
    "allowGaps: boolean;",
    "qualityGates: SplitQualityGate[];",
    "allowGaps: Boolean(contract?.allowGaps)",
    "(contract?.qualityGates ?? []).map(normalizedSplitGate)",
  ], "split version contract");
});

test("split timeline and tables are keyboard and narrow-screen safe", () => {
  includesAll(split, [
    'role="region" aria-label="Chronological split timeline" tabIndex={0}',
    'role="region" aria-label="Exact five-fold split contract" tabIndex={0}',
    'role="region" aria-label="Manual fold date boundaries" tabIndex={0}',
    'role="group" aria-label={label}',
    'aria-pressed={value === option.value}',
    '<caption className="sr-only">',
    'scope="col"',
    'scope="row"',
  ], "split accessibility");
  assert.doesNotMatch(split, /flex min-w-\[560px\][^"\n]*overflow-x-auto/);
});

test("client routes are project-bound and fail closed on OOT, legacy matrices, provider calls, or model activity", () => {
  includesAll(api, [
    "/sports/stage3-feature-engineering",
    "/sports/stage3-split-balance",
    'scope === "DEVELOPMENT_ONLY"',
    "finalOotLocked",
    "finalOotTargetAccessed === false",
    "finalOotUsedForSelection === false",
    "legacyGlobalMatrixUsed === false",
    "providerCalls === 0",
    "Object.values(activity).every",
    "NO_CURRENT_FEATURE_SET",
    "NO_CURRENT_SPLIT_CONTRACT",
  ], "project-bound client");
  assert.doesNotMatch(`${feature}\n${split}\n${api}`, /fit_model|score_model|promote_model|sportsbook/i);
});

test("both studios constrain horizontal overflow to analytical tables and use responsive grids", () => {
  includesAll(feature, ["min-w-0", "overflow-x-auto", "sm:grid-cols-2", "xl:grid-cols"], "feature responsiveness");
  includesAll(split, ["min-w-0", "overflow-x-auto", "sm:grid-cols-2", "xl:grid-cols"], "split responsiveness");
});

test("Feature Engineering labels absent adopted treatment authority honestly", () => {
  includesAll(feature, [
    "adoptedPolicyLabel",
    'policy.policyId !== "NOT_ADOPTED"',
    ': "Not adopted"',
    "Outlier ${adoptedPolicyLabel",
    "Missing ${adoptedPolicyLabel",
  ], "treatment lineage labels");
  assert.doesNotMatch(
    feature,
    /label="Outlier policy" value=\{`v\$\{summary\.data\.treatmentPolicies\.outlier\.version\}`\}/,
  );
  assert.doesNotMatch(
    feature,
    /label="Missing policy" value=\{`v\$\{summary\.data\.treatmentPolicies\.missing\.version\}`\}/,
  );
});

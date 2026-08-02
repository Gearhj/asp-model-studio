import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import vm from "node:vm";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

async function importTypeScript(path) {
  const output = ts.transpileModule(read(path), {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: path,
  }).outputText;
  return import(
    `data:text/javascript;base64,${Buffer.from(output).toString("base64")}`
  );
}

const navigation = await importTypeScript(
  "src/lib/edaWorkspaceNavigation.ts",
);
const findingsSource = read("src/lib/edaFindings.ts");
const governanceSource = read("src/lib/edaFindingGovernance.ts");

function compileCommonJs(source, fileName, requireImpl = () => {
  throw new Error(`Unexpected import while compiling ${fileName}.`);
}) {
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName,
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(output, {
    module,
    exports: module.exports,
    require: requireImpl,
    console,
    JSON,
    Math,
    Object,
    Number,
    String,
    Array,
    Boolean,
    Map,
    Set,
    Date,
    Error,
  });
  return module.exports;
}

const findings = compileCommonJs(findingsSource, "edaFindings.ts");
const governance = compileCommonJs(
  governanceSource,
  "edaFindingGovernance.ts",
  (specifier) => {
    if (specifier === "./edaFindings") return findings;
    throw new Error(`Unexpected governance import: ${specifier}`);
  },
);
const step = read("src/steps/Step02_EDA.tsx");
const styles = read("src/components/eda/eda-premium.css");
const app = read("src/apps/ModelingApp.tsx");
const secondary = read(
  "src/components/eda/visual/PredictorSecondaryInsights.tsx",
);
const vifPlan = read(
  "src/components/eda/visual/VifResolutionPlanPanel.tsx",
);

class MemoryStorage {
  map = new Map();
  getItem(key) {
    return this.map.get(key) ?? null;
  }
  setItem(key, value) {
    this.map.set(key, String(value));
  }
}

test("tab preference is scoped and survives refresh with route precedence", () => {
  const storage = new MemoryStorage();
  const key = navigation.edaTabStorageKey({
    projectId: "project-a",
    datasetId: "dataset-a",
    datasetVersionId: "version-1",
  });
  assert.notEqual(
    key,
    navigation.edaTabStorageKey({
      projectId: "project-a",
      datasetId: "dataset-a",
      datasetVersionId: "version-2",
    }),
  );
  const route = navigation.persistEdaWorkspaceTab({
    tab: "relationships",
    storage,
    storageKey: key,
    currentUrl: "http://127.0.0.1:5174/step02?phase=review#current",
  });
  assert.equal(storage.getItem(key), "relationships");
  assert.equal(
    route,
    "/step02?phase=review&edaTab=relationships#current",
  );
  assert.equal(
    navigation.readEdaWorkspaceTab({ storage, storageKey: key }),
    "relationships",
  );
  assert.equal(
    navigation.readEdaWorkspaceTab({
      search: "?edaTab=predictors",
      storage,
      storageKey: key,
    }),
    "predictors",
  );
  assert.equal(
    navigation.readEdaWorkspaceTab({
      search: "?edaTab=not-a-workspace",
      storage,
      storageKey: key,
    }),
    "relationships",
  );
});

test("arrow, Home, and End keys implement a wrapping tablist model", () => {
  assert.equal(
    navigation.tabForKeyboardNavigation("overview", "ArrowLeft"),
    "findings",
  );
  assert.equal(
    navigation.tabForKeyboardNavigation("findings", "ArrowRight"),
    "overview",
  );
  assert.equal(
    navigation.tabForKeyboardNavigation("relationships", "Home"),
    "overview",
  );
  assert.equal(
    navigation.tabForKeyboardNavigation("target", "End"),
    "findings",
  );
  assert.equal(
    navigation.tabForKeyboardNavigation("target", "Enter"),
    null,
  );
});

test("status badges expose review, unresolved-parent, complete, and N/A states", () => {
  const badges = navigation.buildEdaTabBadges({
    loadedTabs: ["overview", "target", "predictors", "findings"],
    sectionPayloads: {
      predictors: { required_review_count: 4 },
    },
    unresolvedParentFindings: 3,
    governedFieldAvailabilityKnown: true,
    hasGovernedTimeFields: false,
    hasGovernedSegmentFields: false,
  });
  assert.deepEqual(badges.overview, { kind: "complete", label: "Complete" });
  assert.deepEqual(badges.predictors, {
    kind: "review",
    label: "4 review",
    count: 4,
  });
  assert.deepEqual(badges.findings, {
    kind: "unresolved",
    label: "3 unresolved",
    count: 3,
  });
  assert.deepEqual(badges.stability, { kind: "na", label: "N/A" });
  assert.equal(badges.relationships.kind, "pending");
});

test("required parent count honors governed dispositions and informational rows", () => {
  assert.equal(
    navigation.requiredUnresolvedParentFindingCount({
      payload: { unresolved_parent_finding_count: 7 },
    }),
    7,
  );
  const payload = {
    parent_findings: [
      { parent_id: "p1", severity: "high", status: "unresolved" },
      { parent_id: "p2", severity: "moderate", status: "unresolved" },
      { parent_id: "p3", severity: "info", status: "unresolved" },
      { parent_id: "p4", requirement: "not_applicable", required: false },
    ],
  };
  assert.equal(
    navigation.requiredUnresolvedParentFindingCount({
      payload,
      decisions: {
        p1: { disposition: "rejected", rationale: "Governed rejection" },
      },
    }),
    1,
  );
});

test("local parent decisions resolve generated parent findings by parent ID", () => {
  const parents = governance.generateEdaParentFindings({
    overview: {
      headline: { duplicate_rows: 17 },
      data_integrity: { duplicate_rows: 17 },
    },
  });
  assert.equal(parents.length, 1);
  const unresolved = governance.summarizeFindingGovernance(parents, {
    status: "accepted",
    commentary: "Reviewer commentary",
  });
  assert.equal(unresolved.unresolved_parent_finding_count, 1);

  const parentId = parents[0].parentId;
  const resolved = governance.summarizeFindingGovernance(parents, {
    status: "accepted",
    commentary: "Reviewer commentary",
    parentDecisions: {
      [parentId]: {
        disposition: "accepted",
        rationale: "Valid repeated observations were reviewed and documented.",
        destination: "Feature Engineering",
        transformation: "No transformation",
      },
    },
  });
  assert.equal(resolved.unresolved_parent_finding_count, 0);
  assert.equal(resolved.parent_findings[0].parent_id, parentId);
  assert.equal(resolved.parent_findings[0].eligible_for_completion, true);
  assert.match(
    step,
    /summarizeFindingGovernance\(\s*generateEdaParentFindings\(resolvedSections\),\s*findings,?\s*\)/,
  );
  assert.match(
    step,
    /findingsGovernance\.unresolved_parent_finding_count/,
  );
});

test("completion summary is precise and links directly to Findings", () => {
  assert.deepEqual(
    navigation.summarizeEdaCompletionBlockers([
      {
        id: "required-parent-findings",
        message: "3 parent findings require a governed disposition and rationale.",
        destination: "findings",
      },
    ]),
    {
      text: "3 parent findings require a governed disposition and rationale.",
      destination: "findings",
      count: 1,
    },
  );
  assert.equal(
    navigation.summarizeEdaCompletionBlockers([]).text,
    "All required findings have governed dispositions. EDA is ready to confirm.",
  );
  assert.equal(navigation.isEdaOverallStatusEligible("Accepted"), true);
  assert.equal(
    navigation.isEdaOverallStatusEligible("Accepted with Conditions"),
    true,
  );
  assert.equal(navigation.isEdaOverallStatusEligible("Rejected"), false);
});

test("EDA tab rail is prominent, programmatic, persistent, and keyboard accessible", () => {
  for (const marker of [
    "readEdaWorkspaceTab",
    "persistEdaWorkspaceTab",
    "tabForKeyboardNavigation",
    'role="tablist"',
    'role="tab"',
    "aria-selected={selected}",
    "aria-controls={`eda-tabpanel-${tab.id}`}",
    "tabIndex={selected ? 0 : -1}",
    "onKeyDown={(event) => handleEdaTabKeyDown(event, tab.id)}",
    'role="tabpanel"',
    "aria-labelledby={`eda-tab-${activeTab}`}",
  ]) {
    assert.ok(step.includes(marker), `Missing navigation contract: ${marker}`);
  }
  assert.match(
    styles,
    /\.eda-tab-rail \.atlas-tab-button\s*\{[\s\S]*min-height:\s*2\.875rem/,
  );
  assert.match(
    styles,
    /\.eda-tab-rail \.atlas-tab-button-active\s*\{[\s\S]*background:\s*#0f2747;[\s\S]*color:\s*#ffffff/,
  );
  assert.match(
    styles,
    /\.eda-tab-rail \.atlas-tab-button:focus-visible\s*\{[\s\S]*outline:\s*2px solid/,
  );
});

test("badges, section navigation, ownership cleanup, and sticky completion are wired", () => {
  for (const marker of [
    "edaTabBadges[tab.id]",
    "eda-tab-status--${badge.kind}",
    'nextFooterTestId="eda-completion-bar"',
    'nextStatusTestId="eda-completion-summary"',
    'data-testid="eda-completion-direct-action"',
    "nextAlwaysVisible",
    'label="Predictors"',
    'label="Relationships"',
  ]) {
    assert.ok(step.includes(marker), `Missing status/navigation marker: ${marker}`);
  }
  for (const label of [
    "Signal",
    "Deep Dive",
    "Shape Gallery",
    "Quality Matrix",
    "Special Values",
    "Inventory",
    "Correlation",
    "Strong Pairs",
    "VIF",
    "Resolution Plan",
    "Visual Explorer",
    "Pairwise Plot",
  ]) {
    assert.ok(step.includes(`label: "${label}"`), `Missing section link: ${label}`);
  }
  assert.doesNotMatch(
    step,
    /title="Target association ranking"/,
    "Relationships must not duplicate the predictor-to-target ranking.",
  );
  assert.match(secondary, /anchorId="eda-predictors-shape-gallery"/);
  assert.match(secondary, /anchorId="eda-predictors-quality-matrix"/);
  assert.match(secondary, /anchorId="eda-predictors-special-values"/);
  assert.match(vifPlan, /id="eda-relationships-resolution-plan"/);
});

test("Power User mode defaults the Guide to a reopenable full-width drawer state", () => {
  for (const marker of [
    "edaPowerGuideCollapsed",
    'location.pathname === "/step02"',
    'loadModelingMode() === "advanced"',
    'data-eda-power-guide-layout={edaPowerGuideCollapsed ? "drawer-collapsed" : "available"}',
    'data-testid={edaPowerGuideCollapsed ? "eda-power-user-guide-restore" : undefined}',
    "setEdaPowerGuideCollapsed(false)",
  ]) {
    assert.ok(app.includes(marker), `Missing Power User layout behavior: ${marker}`);
  }
  assert.match(
    app,
    /effectiveGuideMode === "hidden"\s*\?\s*"xl:grid-cols-1"/,
  );
});

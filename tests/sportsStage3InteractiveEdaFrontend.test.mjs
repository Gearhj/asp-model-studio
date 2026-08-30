import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");
const [workbench, client, cockpit, stage3Shell, panel, persistence, backend] = await Promise.all([
  read("src/sports/cockpit/ProjectBoundDataProfile.tsx"),
  read("src/sports/cockpit/projectEdaApi.ts"),
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/sports/cockpit/ProjectBoundStage3.tsx"),
  read("src/visual-intelligence/EChartsPanel.tsx"),
  read("src/sports/cockpit/cockpitPersistence.ts"),
  read("server/sports_current_statcast/stage3_eda.py"),
]);

test("the project-bound profile uses the unified compact Stage 3 shell", () => {
  assert.ok(cockpit.includes("<ProjectBoundDataProfile state={c.currentGoldReview} projectId={c.projectId} go={c.go} />"));
  assert.ok(cockpit.includes(": <ProfileStep />"), "standalone legacy behavior remains isolated");
  assert.ok(cockpit.includes("Stage3CompactHeader"));
  assert.ok(cockpit.includes("Stage3AuthorityAudit"));
  assert.ok(cockpit.includes('data-testid="stage3-compact-header"'));
  assert.ok(!cockpit.includes("ProjectBoundStage3ProfileShell"), "the former permanent summary column must not consume canvas width");
});

test("Target opens first and exactly five analytical tabs remain primary", () => {
  assert.ok(workbench.includes('useState<TabId>("target")'));
  const start = workbench.indexOf("const TABS:");
  const end = workbench.indexOf("];", start) + 2;
  const primaryTabs = workbench.slice(start, end);
  const expected = ["Target & Class Balance", "Distributions", "Relationships", "Time & Stability", "Players & Cold Start"];
  let prior = -1;
  for (const label of expected) {
    const index = primaryTabs.indexOf(`label: "${label}"`);
    assert.ok(index > prior, `missing or out-of-order primary tab: ${label}`);
    prior = index;
  }
  for (const removed of ["Overview", "Missingness & Outliers", "Saved Views"]) {
    assert.doesNotMatch(primaryTabs, new RegExp(`label: "${removed}"`));
  }
});

test("the analytical client stays project-bound, development-only, abortable, cached, and OOT locked", () => {
  assert.ok(client.includes("/sports/stage3-eda/metadata"));
  assert.ok(client.includes("/sports/stage3-eda/query"));
  assert.ok(client.includes("AbortController") && client.includes("controller.abort()"));
  assert.ok(client.includes("metadataCache") && client.includes("queryCache"));
  assert.ok(client.includes("responseAuthorityKey(value.authority) !== authorityKey"));
  assert.ok(client.includes('scope !== "DEVELOPMENT_ONLY"'));
  assert.ok(client.includes("!value.population.finalOotLocked"));
  assert.ok(workbench.includes("Final OOT locked") && workbench.includes("Targets excluded from every EDA query"));
  assert.ok(workbench.includes("Final OOT is never filterable"));
});

test("relationship selection is explicit and discoverable", () => {
  for (const text of [
    "Selected-variable tray", "Add variable", "Clear all", "Maximum", "Selection reason",
    "Core Gold-48", "Batter performance", "Pitcher performance", "Recent form",
    "Simulation state", "Calendar", "Rest and travel", "Circadian", "Division and repeat opponent",
    "Scatter X", "Scatter Y", "Optional target stratification", "Association heatmap", "Pairwise matrix",
    "Exactly this ordered set is queried", "Show nonselectable metadata",
  ]) assert.ok(workbench.includes(text), `missing relationship UX: ${text}`);
  assert.ok(workbench.includes('stratifyBy: scatterDisplayMode === "scatter" && scatterTarget === "outcome" ? "outcome" : undefined'));
  assert.ok(workbench.includes('aria-label="Relationship view"'));
  assert.ok(workbench.includes("const hexRadius = 1 / 28") && workbench.includes("roundedAxial"), "hexbin must use a genuine axial hex grid");
  assert.ok(client.includes("projectEdaVariableSelection"));
});

test("target and data-quality summaries provide guidance without automatic treatment", () => {
  for (const text of [
    "Target decision summary", "Dominant class", "Rarest class", "Imbalance ratio",
    "Season stability", "Smallest rare sample", "NO AUTO REBALANCING",
    "Data Quality Snapshot", "Physical missingness", "Cold-start prevalence",
    "Material missingness", "Source / computation failures", "Potential descriptive outliers",
    "Open Missing Values", "Open Outliers",
  ]) assert.ok(workbench.includes(text), `missing decision summary: ${text}`);
  assert.ok(client.includes("targetSummary") && client.includes("dataQualitySnapshot"));
  assert.ok(workbench.includes("no automatic weighting or oversampling"));
});

test("time stability produces a written, multi-variable assessment and never defaults to context inning", () => {
  for (const text of [
    "Stability Assessment", "Written development-only takeaway", "Target mix", "Stable features",
    "Moderate review", "High review", "Source-era changes", "Cold-start shift",
    "Direction / magnitude", "Periods affected", "PSI / KS", "Coverage shift", "Likely cause", "Next action",
    "row-volume troughs", "chronological validation",
  ]) assert.ok(workbench.toLowerCase().includes(text.toLowerCase()) || client.toLowerCase().includes(text.toLowerCase()) || backend.toLowerCase().includes(text.toLowerCase()), `missing stability guidance: ${text}`);
  assert.ok(client.includes('defaultStabilityVariableExcluded: "context_inning"'));
  assert.ok(workbench.includes('name !== "context_inning"'));
});

test("saved analyses are a compact project-scoped drawer with full lifecycle controls", () => {
  assert.ok(workbench.includes('const BOOKMARKS_KEY = "stage3.eda.variableBookmarks"'));
  assert.ok(workbench.includes('const SAVED_VIEWS_KEY = "stage3.eda.savedViews"'));
  assert.ok(workbench.includes("SavedAnalysesDrawer") && workbench.includes("Saved analyses ("));
  for (const text of ["Save analysis", "Reopen", "Update from current", "Rename", "Delete", "Bookmarked variables", "Saved analyses are analytical bookmarks, not modeling decisions."]) {
    assert.ok(workbench.includes(text), `missing saved-analysis control: ${text}`);
  }
  assert.ok(workbench.includes("bookmarkedVariables: bookmarks") && workbench.includes("sourceTab: activeTab"));
  assert.ok(stage3Shell.includes("bookmarkedVariables") && stage3Shell.includes("sourceTab"));
  assert.ok(persistence.includes("notes: s.notes") && persistence.includes("localStorage"));
  assert.doesNotMatch(workbench, /localStorage/);
});

test("bounded charts and safety invariants remain intact", () => {
  for (const text of [
    "Histogram", "Smoothed density", "ECDF", "Box plot", "Violin plot", "Log scale",
    "Pearson", "Spearman", "Cramér", "correlation ratio", "HASH_SMALLEST_CANONICAL_PA_V1",
    "Reset zoom and brush", "Download chart image", "Download aggregated chart data",
    "The full population never enters the browser", "no read can fit or score a model",
    "final-OOT class composition is inaccessible",
  ]) assert.ok(workbench.includes(text) || client.includes(text), `missing bounded capability: ${text}`);
  assert.ok(panel.includes("BoxplotChart"));
  assert.doesNotMatch(client, /\/cockpit\/|experiment\/run|autopilot|\/activate|\/promote/);
  assert.doesNotMatch(workbench, /postJSON|model-family|hyperparameter/);
});

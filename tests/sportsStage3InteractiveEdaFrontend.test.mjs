import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");
const [workbench, client, cockpit, panel, persistence] = await Promise.all([
  read("src/sports/cockpit/ProjectBoundDataProfile.tsx"),
  read("src/sports/cockpit/projectEdaApi.ts"),
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/visual-intelligence/EChartsPanel.tsx"),
  read("src/sports/cockpit/cockpitPersistence.ts"),
]);

test("the project-bound profile replaces only the project Stage 3 gate", () => {
  assert.ok(cockpit.includes("<ProjectBoundDataProfile state={c.currentGoldReview} projectId={c.projectId} go={c.go} />"));
  assert.ok(cockpit.includes(": <ProfileStep />"), "standalone legacy behavior remains isolated");
  assert.doesNotMatch(workbench, /\/cockpit\/profile|\/cockpit\/correlation|MLB_PA_V1|FD1/);
});

test("all eight primary scientist-facing tabs are present", () => {
  for (const label of [
    "Overview", "Distributions", "Relationships", "Target & Class Balance",
    "Missingness & Outliers", "Time & Stability", "Players & Cold Start", "Saved Views",
  ]) assert.ok(workbench.includes(`label: "${label}"`), `missing ${label}`);
});

test("the lazy analytical client is project and authority bound, abortable, cached, and OOT locked", () => {
  assert.ok(client.includes("/sports/stage3-eda/metadata"));
  assert.ok(client.includes("/sports/stage3-eda/query"));
  assert.ok(client.includes("AbortController"));
  assert.ok(client.includes("controller.abort()"));
  assert.ok(client.includes("metadataCache") && client.includes("queryCache"));
  assert.ok(client.includes("authorityKey") && client.includes("reviewDigest"));
  assert.ok(client.includes("responseAuthorityKey(value.authority) !== authorityKey"));
  assert.ok(client.includes("responseIsSafe(value)"));
  assert.ok(client.includes('scope !== "DEVELOPMENT_ONLY"'));
  assert.ok(client.includes("!value.population.finalOotLocked"));
  assert.ok(workbench.includes("Final OOT locked") && workbench.includes("Targets excluded from every EDA query"));
  assert.ok(workbench.includes("Final OOT is never filterable"));
});

test("tab changes cannot render stale analytical payloads and null associations stay not estimable", () => {
  assert.ok(client.includes("state.requestKey !== requestKey"));
  assert.ok(client.includes('status: query ? "loading" as const : "idle" as const'));
  assert.ok(client.includes("value: number | null"));
  assert.ok(workbench.includes("estimableCells"));
  assert.ok(workbench.includes("never rendered as zero"));
});

test("variable exploration and global development filters cover the governed analytical contract", () => {
  for (const text of [
    "Variable explorer", "featureFamily", "sourceLineage", "pointInTimeTreatment",
    "availabilityEra", "proxyWarning", "Bookmark variable for review",
    "Season", "Start date", "End date", "Month", "Outcome class", "Batter canonical ID",
    "Pitcher canonical ID", "Batting team", "Fielding team", "Home / away: all", "Day of week",
    "History: all", "All feature families", "Observed / missing: all",
    "Simulation state: all", "context_inning", "context_outs_before", "Min sample",
  ]) assert.ok(workbench.includes(text), `missing explorer/filter contract: ${text}`);
});

test("interactive charts expose bounded controls and every required diagnostic family", () => {
  for (const text of [
    "Histogram", "Smoothed density", "ECDF", "Box plot", "Violin plot", "Log scale",
    "Stratify by", "Association heatmap", "Scatter / density", "Pairwise matrix",
    "Missingness matrix / co-missingness", "Missingness reason categories", "Extreme observations",
    "Distribution drift", "PSI", "KS", "Cold-start target composition",
    "Reset zoom and brush", "Download chart image", "Download aggregated chart data",
  ]) assert.ok(workbench.includes(text), `missing chart capability: ${text}`);
  assert.ok(panel.includes("BoxplotChart"), "boxplot renderer must be registered");
  assert.ok(client.includes("HASH_SMALLEST_CANONICAL_PA_V1"));
  assert.ok(workbench.includes("The full population never enters the browser"));
});

test("saved views and handoffs are project-scoped analytical bookmarks", () => {
  assert.ok(workbench.includes('const BOOKMARKS_KEY = "stage3.eda.variableBookmarks"'));
  assert.ok(workbench.includes('const SAVED_VIEWS_KEY = "stage3.eda.savedViews"'));
  assert.ok(workbench.includes("useCockpitStore") && workbench.includes("setNote(SAVED_VIEWS_KEY"));
  assert.ok(workbench.includes('setNote("stage3.eda.handoff"'));
  assert.ok(workbench.includes("storedBookmarks.authorityKey === authorityKey"));
  assert.ok(workbench.includes("view.authorityKey !== authorityKey") && workbench.includes("STALE_AUTHORITY"));
  assert.ok(persistence.includes("notes: s.notes") && persistence.includes("localStorage"));
  assert.doesNotMatch(workbench, /localStorage/);
  for (const text of ["Open in Outliers", "Open in Missing Values", "Bookmark for Feature Engineering", "analytical bookmarks—not model decisions"]) {
    assert.ok(workbench.includes(text), `missing handoff: ${text}`);
  }
});

test("EDA remains descriptive and never fits, scores, selects, or exposes OOT outcomes", () => {
  assert.ok(workbench.includes("no read can fit or score a model"));
  assert.ok(workbench.includes("descriptive, not automatic feature selection"));
  assert.ok(workbench.includes("no automatic treatment"));
  assert.ok(workbench.includes("final-OOT class composition is inaccessible"));
  assert.doesNotMatch(client, /\/cockpit\/|experiment\/run|autopilot|activate|promote/);
  assert.doesNotMatch(workbench, /postJSON|model-family|hyperparameter/);
});

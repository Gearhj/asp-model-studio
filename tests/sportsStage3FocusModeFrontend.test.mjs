import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");

const [
  app,
  sidebar,
  guidedWorkflow,
  guidedContent,
  cockpit,
  profile,
  stage3,
  focusMode,
  drawer,
  edaClient,
] = await Promise.all([
  read("src/apps/ModelingApp.tsx"),
  read("src/components/Sidebar.tsx"),
  read("src/sports/workflow/GuidedWorkflow.tsx"),
  read("src/sports/workflow/GuidedStageContent.tsx"),
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/sports/cockpit/ProjectBoundDataProfile.tsx"),
  read("src/sports/cockpit/ProjectBoundStage3.tsx"),
  read("src/sports/cockpit/stage3FocusMode.tsx"),
  read("src/sports/cockpit/CockpitDrawer.tsx"),
  read("src/sports/cockpit/projectEdaApi.ts"),
]);

function includesAll(source, values, label) {
  for (const value of values) {
    assert.ok(source.includes(value), `${label} is missing: ${value}`);
  }
}

test("Modeling Focus Mode is project-scoped, persistent, default-on, and only overrides the global sidebar", () => {
  includesAll(focusMode, [
    "asp-stage3-focus-mode:",
    "storageKey(projectId)",
    "stored === null ? true",
    "localStorage.setItem(storageKey(projectId), String(next))",
    "stage3SurfaceActive && focusModeEnabled",
    "useProjectStage3FocusPreference",
    "useStage3FocusMode",
  ], "focus-mode preference contract");
  includesAll(app, [
    "Stage3FocusModeProvider",
    "stage3SurfaceActive",
    "stage3Focus.enabled",
    "data-stage3-focus-mode",
    "max-w-none",
  ], "application focus-mode integration");
  includesAll(sidebar, [
    "effectiveCompact = compact || focusModeActive",
    "data-modeling-focus-rail",
    "Exit modeling focus mode",
  ], "sidebar focus override");
  assert.ok(sidebar.includes('localStorage.setItem("asp-sidebar-mode"'), "ordinary sidebar preference must remain independently persisted");
  assert.doesNotMatch(sidebar, /asp-sidebar-mode[^\n]+focusMode/i, "Focus Mode must not overwrite the ordinary sidebar preference");
});

test("Stage 3 removes duplicate permanent rails and the generic hero while retaining one merged navigator", () => {
  includesAll(guidedWorkflow, [
    'data-stage3-workspace={focus.number === 3 ? "true" : undefined}',
    "focus.number !== 3 ? <section className=\"sports-hero-panel",
    "focus.number !== 3 ? <nav",
    "resolutions={resolutions}",
    "onGoProgramStage={onGoStage}",
  ], "focused guided-workflow shell");
  includesAll(guidedContent, ["programStages", "onGoProgramStage", "projectName"], "merged-navigation handoff");
  includesAll(cockpit, [
    "Workflow navigator",
    "All nine program stages",
    "all fifteen Stage 3 steps",
    "programStages.map",
    "STEPS.map",
    "goProgram",
    "goStep",
    'testId="stage3-workflow-navigator"',
  ], "merged workflow navigator");
  assert.doesNotMatch(cockpit, /lg:grid-cols-\[260px_minmax\(0,1fr\)\]/, "the permanent fifteen-step rail must not return");
});

test("individual Stage 3 pages use a compact sticky authority header", () => {
  includesAll(cockpit, [
    "Stage3CompactHeader",
    'data-testid="stage3-compact-header"',
    "Stage 3 of 9",
    "Step {Number(step.n)}",
    'CompactFact label="Development"',
    "Final OOT",
    "Current Gold",
    "Point-in-time",
    "Focus Mode",
    "Authority & Audit",
    "AutosaveBadge",
  ], "compact Stage 3 header");
  assert.doesNotMatch(cockpit, /Interactive modeling cockpit[\s\S]{0,800}MLB Plate-Appearance Model/, "individual cockpit pages must not render the old dark hero");
  assert.doesNotMatch(profile, /Project-bound analytical workbench[\s\S]{0,500}Explore development evidence without touching the holdout/, "Data Profile must not repeat a large generic hero below the compact header");
  assert.ok(cockpit.includes("sticky") && cockpit.includes("top-0"), "the compact header must stay accessible while scrolling");
});

test("the permanent Variable Explorer is replaced by an accessible governed picker drawer", () => {
  assert.doesNotMatch(profile, /data-testid="stage3-eda-variable-explorer"/, "Variable Explorer must not occupy a permanent column");
  includesAll(profile, [
    "VariablePickerDrawer",
    'title="Add a variable"',
    'testId="stage3-eda-variable-picker"',
    "Search variables",
    "Model-selectable predictors appear by default",
    "Show nonselectable metadata",
    "Feature family",
    "Contract tier",
    "Data type",
    "Role",
    "Missingness",
    "Exact source lineage",
    "Availability era",
    "Bookmarked variables only",
    "Point-in-time",
    "Proxy / warning status",
    "addAndClose",
    'aria-haspopup="dialog"',
  ], "variable picker");
  includesAll(drawer, [
    "createPortal",
    'role="dialog"',
    'aria-modal="true"',
    "FOCUSABLE_SELECTOR",
    'event.key === "Escape"',
    'event.key !== "Tab"',
    "applicationRoot.inert = true",
    'document.body.style.overflow = "hidden"',
    "returnFocusRef",
  ], "shared accessible drawer");
});

test("selected-variable and chart assignments stay explicit on a full-width sticky analytical canvas", () => {
  includesAll(profile, [
    "Selected variables",
    "Add variable",
    "Feature-family preset",
    "Scatter X",
    "Scatter Y",
    "Optional target stratification",
    "Association method",
    "Pairwise matrix",
    "2–6 variables",
    "Deterministic point sample",
    "Primary variable",
    "Optional stratification variable",
    "Distribution chart type",
    "Bins",
    "Save analysis",
    "stage3-eda-sticky-controls",
    "stage3-fullscreen-chart",
    "Maximize2",
  ], "full-width analytical controls");
  const selectedTray = profile.slice(
    profile.indexOf('data-testid="stage3-eda-selected-variable-tray"'),
    profile.indexOf("export function ProjectBoundDataProfile"),
  );
  assert.ok(selectedTray.includes("> Clear all</button>"), "the selected-variable tray must expose the requested Clear all action");
  includesAll(cockpit, ['data-testid="stage3-analytical-canvas"', "min-w-0"], "analytical canvas");
  assert.doesNotMatch(profile, /lg:grid-cols-\[270px_minmax\(0,1fr\)\]/, "the old Variable Explorer/chart split must not remain");
});

test("Authority & Audit retains compact safeguards and complete detailed evidence", () => {
  includesAll(cockpit, [
    "Authority & Audit",
    'testId="stage3-authority-audit-drawer"',
    "Stage3AuthorityAudit",
    "Project-linked source authority",
    "Current Gold authority",
    "Manifest",
    "Review digest",
    "Population reconciliation",
    "Exact ordered feature contract",
    "Source manifest",
    "Final OOT",
    "Model activity",
  ], "authority and audit drawer");
  includesAll(stage3, [
    "review.sourceAuthority",
    "review.goldAuthority",
    "review.matrix.finalOot.rows",
    "review.pointInTimeReview",
    "review.leakageGate",
  ], "project-bound authority source");
});

test("focus redesign preserves development-only EDA, saved analyses, and zero modeling mutation", () => {
  includesAll(edaClient, [
    'scope !== "DEVELOPMENT_ONLY"',
    "finalOotLocked",
    "finalOotTargetAccessed",
    "legacyGlobalMatrixUsed",
    "providerCalls === 0",
  ], "EDA safety client");
  includesAll(profile, [
    "SAVED_VIEWS_KEY",
    "Saved analyses",
    "Save current analysis",
    "Reopen",
    "Update from current",
    "Delete",
    "Final OOT is never filterable",
    "final-OOT class composition is inaccessible",
  ], "saved-analysis and safety continuity");
  const redesignedSurface = `${cockpit}\n${profile}\n${focusMode}\n${drawer}`;
  assert.doesNotMatch(redesignedSurface, /experiment\/run|\/activate|\/promote|postJSON|fit_model|score_model/i, "the layout task must not add a modeling mutation path");
});

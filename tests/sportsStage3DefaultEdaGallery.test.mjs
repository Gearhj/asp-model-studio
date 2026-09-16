import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");

const [workbench, gallery, client, backend] = await Promise.all([
  read("src/sports/cockpit/ProjectBoundDataProfile.tsx"),
  read("src/sports/cockpit/Stage3DistributionGallery.tsx"),
  read("src/sports/cockpit/projectEdaApi.ts"),
  read("server/sports_current_statcast/stage3_eda.py"),
]);

function includesAll(source, values, label) {
  for (const value of values) {
    assert.ok(source.includes(value), `${label} is missing: ${value}`);
  }
}

function orderedBlock(source, startToken, endToken) {
  const start = source.indexOf(startToken);
  assert.notEqual(start, -1, `missing block start: ${startToken}`);
  const end = source.indexOf(endToken, start);
  assert.ok(end > start, `missing block end after ${startToken}: ${endToken}`);
  return source.slice(start, end);
}

test("the default Stage 3 EDA entry presents the exact prominent five-section decision path", () => {
  assert.ok(workbench.includes('useState<TabId>("target")'), "Target & Class Balance must remain the default section");
  const tabs = orderedBlock(workbench, "const TABS:", "];\n\n// Saved analyses");
  const expected = [
    [1, "Target & Class Balance"],
    [2, "Distributions"],
    [3, "Relationships"],
    [4, "Time & Stability"],
    [5, "Players & Cold Start"],
  ];
  let previous = -1;
  for (const [number, label] of expected) {
    const index = tabs.indexOf(`number: ${number}, label: "${label}"`);
    assert.ok(index > previous, `missing or out-of-order section ${number}: ${label}`);
    previous = index;
  }
  assert.equal((tabs.match(/label: "/g) ?? []).length, 5, "primary navigation must contain exactly five analytical sections");
  includesAll(workbench, [
    'data-testid="stage3-eda-section-nav"',
    'aria-label="Stage 3 analytical sections"',
    'aria-current={activeTab === tab.id ? "page" : undefined}',
    'aria-controls="stage3-active-analytical-section"',
    "{tab.number}",
  ], "five-section navigation");
});

test("selection and chart controls are owned by their analytical section rather than a universal tray", () => {
  includesAll(workbench, [
    'data-testid="stage3-relationship-local-selection"',
    'aria-label="Relationship controls"',
    'aria-label="Time and stability controls"',
    'data-testid="stage3-time-comparison-controls"',
    'aria-label="Stability comparison period grouping"',
    'aria-label="Stability comparison start date"',
    'aria-label="Stability comparison end date"',
    'max="2026-08-13"',
    "granularity: timeGranularity",
    "Stage3DistributionGallery",
  ], "section-local control ownership");
  const selectedTrayUses = workbench.match(/<SelectedVariableTray section=/g) ?? [];
  assert.equal(selectedTrayUses.length, 2, "only Relationships and Time & Stability may render a selected-variable tray");
  assert.ok(workbench.includes('<SelectedVariableTray section="Relationship"'), "Relationships must retain explicit variable ownership");
  assert.ok(workbench.includes('<SelectedVariableTray section="Stability"'), "Time & Stability must retain explicit variable ownership");
  assert.doesNotMatch(workbench, /<SelectedVariableTray section="Distribution"/, "the default all-variable gallery must not be gated by a Distribution selection tray");
});

test("Distributions is an all-variable, grouped, customizable project gallery", () => {
  includesAll(gallery, [
    'data-testid="stage3-distribution-gallery"',
    'aria-label="All-variable analytical distribution gallery"',
    "All-variable development profile",
    "Every eligible project-bound predictor is accessible here.",
    "Customize gallery",
    'testId="stage3-gallery-customize"',
    "This changes presentation only; it does not select model features.",
    "Restore all eligible",
    "CORE_GOLD_48",
    "CALENDAR",
    "REST_AND_TRAVEL",
    "CIRCADIAN",
    "DIVISION_AND_REPEAT_OPPONENT",
    "INTERACTIONS",
    "MISSINGNESS_INDICATORS",
    "...families.map((item) => item.name)",
    "...variables.map((variable) => variable.featureFamily)",
    "data-gallery-family={group.name}",
  ], "grouped gallery");
  includesAll(gallery, [
    'data-testid="stage3-gallery-local-controls"',
    'aria-label="Search variables"',
    'aria-label="Show feature family"',
    'aria-label="Show data type"',
    'aria-label="Core or contextual"',
    'aria-label="Selectable or active"',
    'aria-label="Missingness threshold"',
    'aria-label="Sort gallery"',
    "Show only bookmarked",
  ], "gallery-local filtering and sorting");
});

test("gallery cards route every governed variable type to bounded useful defaults", () => {
  includesAll(gallery, [
    '"continuous" | "low-cardinality" | "binary" | "categorical" | "missingness-indicator"',
    'queryType: categorical ? "category_counts" as const : "distribution" as const',
    'settings: categorical ? { topN: categoryTopN } : { bins: 24, stratifyBy: "outcome" }',
    'aria-label={`Top N levels for ${variable.name}`}',
    "remaining governed levels are grouped as Other with their own target composition",
    "displayedCategoryRows",
    "data.otherCategory",
    "category frequency",
    "target composition by level",
    "development ${summaryMode}",
    'aria-label="Detailed continuous summary chart"',
    "Density",
    "ECDF",
    "Log scale",
    "horizontal target stratified ${targetMode} plot",
    'aria-label="Target stratified shape"',
    "targetViolinOption",
    'value="violin"',
    "All eight governed outcomes remain explicit.",
    'row.observedCount === 0 ? " (n=0)"',
    "value ?? Number.NaN",
    "Linked field:",
    "Reason:",
    "The complete indicator column does not imply the underlying feature is complete.",
    "Missing count",
    "Q1 / Q3",
    "P05 / P95",
  ], "type-aware gallery defaults");
  includesAll(client, [
    "observedCount: number",
    "missingCount: number",
    "lowerFence: number | null",
    "upperFence: number | null",
    "outlierCount: number",
    'otherCategory: { value: "Other"',
  ], "target-stratified distribution response contract");
  includesAll(backend, [
    "if stratify == \"outcome\"",
    "for outcome in GOLD_CLASS_ORDER",
    '"observedCount": observed_count',
    '"lowerFence":',
    '"upperFence":',
    '"outlierCount": outlier_count',
    '"density": stratum_density_rows',
    '"otherCategory": other_category',
  ], "governed target-stratified backend aggregation");
  assert.doesNotMatch(gallery, /queryType:\s*"pairwise_sample"/, "distribution cards must not fetch raw pairwise samples");
});

test("large galleries defer aggregate requests and rendering until a card approaches the viewport", () => {
  includesAll(gallery, [
    "function useNearViewport",
    'typeof IntersectionObserver === "undefined"',
    "new IntersectionObserver",
    'rootMargin: "700px 0px"',
    "queryType: categorical",
    ": null, [categorical, categoryTopN, filters, near, variable.name, variable.selectable]",
    'data-windowed-query={near ? "active" : "deferred"}',
    'contentVisibility: "auto"',
    'containIntrinsicSize: "720px"',
    "Windowed profile: aggregate query begins near the viewport.",
    "one bounded, cached aggregate request only when they approach the viewport",
  ], "lazy and windowed gallery");
  includesAll(client, ["AbortController", "controller.abort()", "queryCache"], "cancelled and cached aggregate queries");
});

test("excluded metadata is inspectable without issuing an unauthorized analytical query", () => {
  includesAll(gallery, [
    "near && variable.selectable",
    "Governance metadata inspection only.",
    "This field is not a model candidate, so no distribution or target query is issued.",
    "METADATA ONLY",
  ], "metadata-only inspection");
});

test("Relationships opens with the exact useful six-variable default and governed presets", () => {
  const defaults = orderedBlock(workbench, "const RELATIONSHIP_DEFAULT_NAMES", "] as const;");
  const expectedDefaults = ["batter_avg", "batter_obp", "batter_slg", "pitcher_era9", "pitcher_whip", "pitcher_so_per_bfp"];
  assert.deepEqual([...defaults.matchAll(/"([^"]+)"/g)].map((match) => match[1]), expectedDefaults);
  includesAll(workbench, [
    "Suggested starting set — customize as needed.",
    "Restore default set",
    "Move ${variable.name} earlier",
    "Move ${variable.name} later",
    "relationshipDefaultNames(variables, maxVariables)",
    'tab === "relationships" && relationshipDefaultsAppliedAuthority.current !== authorityKey',
    "assignRelationshipSelection(relationshipDefaults)",
    'data-testid="stage3-relationship-immediate-previews"',
    'data-testid="stage3-relationship-association-preview"',
    'data-testid="stage3-relationship-pairwise-preview"',
    'data-testid="stage3-pairwise-matrix-controls"',
    'aria-label="Pairwise matrix diagonal distribution method"',
    'aria-label="Pairwise matrix lower triangle cell method"',
    'aria-label="Pairwise matrix upper triangle cell method"',
    'data-testid="stage3-literal-pairwise-matrix"',
    "pairwiseDiagonalChart",
    "pairwiseOffDiagonalChart",
    "Lower triangle",
    "Upper triangle",
    'queryType: "association"',
    'queryType: "pairwise_sample"',
  ], "Relationship default and immediate previews");
  for (const preset of [
    "Batter performance",
    "Pitcher performance",
    "Batter versus pitcher",
    "Recent form",
    "Simulation state",
    "Calendar",
    "Rest and travel",
    "Circadian",
    "Division and repeat opponent",
    "Core Gold-48 subset",
  ]) {
    assert.ok(workbench.includes(`"${preset}"`), `missing Relationship preset: ${preset}`);
  }
});

test("gallery reads stay development-only and retain practical downstream handoffs", () => {
  includesAll(workbench, [
    "Final OOT locked",
    "Targets excluded from every EDA query",
    "Development-only EDA; no read can fit or score a model.",
    'setNote("stage3.eda.handoff"',
  ], "workbench safety banner and persisted handoff");
  includesAll(gallery, [
    "No raw PA rows or final-OOT targets are returned.",
    "Bounded aggregate evidence only. Final-OOT targets remain locked.",
    "Open in Outliers",
    "Open in Missing Values",
    "Bookmark for Feature Engineering",
  ], "per-card governed handoffs");
  includesAll(client, [
    'scope !== "DEVELOPMENT_ONLY"',
    "!value.population.finalOotLocked",
    "finalOotTargetAccessed",
    "finalOotUsedForSelection",
    "providerCalls === 0",
  ], "client fail-closed safety checks");
  const analyticalSurface = `${workbench}\n${gallery}`;
  assert.doesNotMatch(analyticalSurface, /experiment\/run|\/activate|\/promote|fit_model|score_model|model-family|hyperparameter/i, "the gallery must not add model mutation or selection paths");
});

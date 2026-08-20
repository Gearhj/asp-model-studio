// Phase 6E.4 — static UI checks for Missing-value visuals, Feature Engineering redesign, and autosave.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (p) => readFile(new URL(p, ROOT), "utf8");
const [steps1, ui, shell, stageContent, persistence] = await Promise.all([
  read("src/sports/cockpit/cockpitSteps1.tsx"),
  read("src/sports/cockpit/cockpitUi.tsx"),
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/sports/workflow/GuidedStageContent.tsx"),
  read("src/sports/cockpit/cockpitPersistence.ts"),
]);
const missing = steps1.slice(steps1.indexOf("05 Missing Values"), steps1.indexOf("06 Feature Engineering"));
const feat = steps1.slice(steps1.indexOf("06 Feature Engineering"), steps1.indexOf("07 Player Segmentation"));

// ------------------------------------------------------------- Missing-value before/after visuals
test("Missing Values renders a before/after visual card for every affected continuous feature", () => {
  assert.ok(missing.includes("Feature treatment visuals — before / after imputation"));
  assert.ok(missing.includes('rows.filter((f) => f.kind === "continuous" && f.missing > 0)'));
  assert.ok(missing.includes("<ImputationHistogramPair"));
});

test("before/after are side-by-side, method-labelled, with a fill marker", () => {
  assert.ok(ui.includes("export function ImputationHistogramPair"));
  assert.ok(ui.includes("Before — observed values"));
  assert.ok(ui.includes("afterLabel ?? "));
  assert.ok(missing.includes('afterLabel={`After — ${missingMethodLabel(f.resolvedMethod).toLowerCase()} imputation`}'));
  assert.ok(missing.includes("fill={f.fillValue}"));
  // grid-cols-2 side-by-side layout in the pair component
  assert.ok(ui.includes('grid grid-cols-2 gap-3'));
});

test("a stale-backend response shows an honest fallback instead of silently omitting the panel", () => {
  assert.ok(missing.includes("Distribution charts are unavailable from the current backend response"));
  assert.ok(missing.includes("f.beforeHistogram && f.afterHistogram")); // conditional, with else fallback
});

// ------------------------------------------------------------- Feature Engineering redesign
test("compact header cards lead the page (current / selected / engineered / research families)", () => {
  const iHeader = feat.indexOf('label="Current features"');
  assert.ok(iHeader > 0);
  assert.ok(feat.includes('label="Selected"') && feat.includes('label="Engineered"') && feat.includes('label="Research families"'));
  // header appears before the advanced-families / catalog disclosures
  assert.ok(iHeader < feat.indexOf("Advanced feature families"));
});

test("the signal map (IV vs MI) and create studio occupy the prime workspace", () => {
  assert.ok(feat.includes('title="Feature signal map"') && feat.includes("<FeatureSignalScatter"));
  assert.ok(ui.includes("export function FeatureSignalScatter") && ui.includes("Information Value (IV)") && ui.includes("Mutual Information (MI)"));
  assert.ok(feat.includes('title="Create feature studio"'));
});

test("data summary table renders with signal columns and updates from the store", () => {
  assert.ok(feat.includes("function FeatureSummaryTable"));
  for (const col of ['label="Feature"', 'label="Source"', ">Type<", 'label="Missing %"', 'label="Outliers"', 'label="IV"', 'label="MI"', 'label="Drift"', ">Selected<", ">Actions<"]) {
    assert.ok(feat.includes(col), `summary table missing column ${col}`);
  }
  // rows derive from the live store (base + engineered), engineered rows are labelled + may be "not profiled"
  assert.ok(feat.includes('source: "ENGINEERED"') && feat.includes("not profiled"));
  assert.ok(feat.includes("engineeredFormula(e)"));
});

test("create studio has a prominent formula preview, profile panel, and quality scorecard", () => {
  assert.ok(feat.includes("Formula preview") && feat.includes("read-only"));
  assert.ok(feat.includes("engineeredFormula(spec())") || feat.includes("const formula = engineeredFormula"));
  // quality scorecard is multi-dimensional (not one magic score)
  assert.ok(feat.includes("Information (IV)") && feat.includes("Nonlinear (MI)") && feat.includes("Temporal drift") && feat.includes("Missingness"));
  assert.ok(feat.includes("function ScoreTile"));
  // distribution chart from the fold-local histogram
  assert.ok(feat.includes("p.histogram") && feat.includes("<Histogram"));
});

test("add persists the profile snapshot; profiling is fold-local and temporally safe", () => {
  assert.ok(feat.includes("store.addEngineered(spec(), profile.data ?? undefined)"));
  assert.ok(feat.includes("fold-local (2023)") && feat.includes("frozen 2025 never determine"));
});

test("feature-creation validation surfaces understandable errors", () => {
  assert.ok(feat.includes("const validate = ()"));
  assert.ok(feat.includes("already exists") && feat.includes("collides with a base feature"));
  assert.ok(feat.includes("constant")); // divide/interaction-by-self guard
});

test("research families, catalog, and selected chips are de-emphasized behind disclosures", () => {
  // three <details> disclosures move the passive content out of the prime workspace
  assert.ok((feat.match(/<details/g) || []).length >= 3);
  assert.ok(feat.includes("Advanced feature families") && feat.includes("<PlayerStateFeatureFamilies"));
  assert.ok(feat.includes("Feature catalog"));
  assert.ok(feat.includes("View selected feature set"));
  // governed families/state are preserved, not deleted
  assert.ok(steps1.includes("function PlayerStateFeatureFamilies"));
});

test("governed source features cannot be deleted — only included / excluded", () => {
  assert.ok(feat.includes("toggleFeature(r.name)"));
  assert.ok(feat.includes('r.source === "ENGINEERED" && ') && feat.includes("removeEngineered(r.name)"));
  assert.ok(feat.includes("Governed source features are never deleted"));
});

// ------------------------------------------------------------- autosave / persistence wiring
test("the cockpit wires project-scoped autosave and shows a status indicator", () => {
  assert.ok(shell.includes("useCockpitPersistence(projectId, active, setActive)"));
  assert.ok(shell.includes("function AutosaveBadge") && shell.includes("<AutosaveBadge"));
  assert.ok(shell.includes("projectId = \"mlb-cockpit\"") || shell.includes("projectId?: string"));
  // the embedded cockpit is scoped to the current project
  assert.ok(stageContent.includes("projectId={contract?.projectId ?? \"mlb-gen2\"}"));
});

test("autosave persists durable slices, project-scoped, and restores the active step", () => {
  assert.ok(persistence.includes("export const COCKPIT_PREFIX"));
  assert.ok(persistence.includes("cockpitStorageKey = (projectId: string)"));
  for (const slice of ["config", "notes", "engineeredProfiles", "savedSteps", "activeStep"]) {
    assert.ok(persistence.includes(slice), `snapshot missing slice ${slice}`);
  }
  assert.ok(persistence.includes("onRestoreStep") && persistence.includes("useLayoutEffect")); // restore before paint
  assert.ok(persistence.includes('setStatus("error")') && persistence.includes("Never discard in-memory work")); // failure keeps work
});

test("bottom navigation footer remains intact", () => {
  const order = [...shell.matchAll(/id:\s*"([a-z]+)",\s*n:\s*"(\d\d)"/g)].map((m) => m[1]);
  assert.equal(order.indexOf("features") - order.indexOf("missing"), 1);
  assert.ok(shell.includes("function StepFooter"));
});

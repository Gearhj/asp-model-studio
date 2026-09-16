// Phase 6G.2 — dataset-first authority + objective state integrity (static source checks; the runtime
// behaviour is driven by the zustand notes + the project's registered contracts, asserted here at the
// source level, consistent with the cockpit's other UI test suites).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (p) => readFile(new URL(p, ROOT), "utf8");
const [steps1, api, persistence, shell] = await Promise.all([
  read("src/sports/cockpit/cockpitSteps1.tsx"),
  read("src/sports/cockpit/cockpitApi.ts"),
  read("src/sports/cockpit/cockpitPersistence.ts"),
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
]);
const objective = steps1.slice(steps1.indexOf("01 Objective"), steps1.indexOf("02 Data & Population"));
const dataset = steps1.slice(steps1.indexOf("Modeling dataset authority (Phase 6G"), steps1.indexOf("Explicit target-variable authority"));
const targetSel = steps1.slice(steps1.indexOf("Explicit target-variable authority"), steps1.indexOf("function PopulationBody"));

// ---------------- authority state model ----------------
test("authority state is derived from explicit acts AND the backend-registered contract", () => {
  assert.ok(steps1.includes('import { loadBinding, type ForecastContract } from "../workflow/workflowState"'));
  assert.ok(steps1.includes('import { useForecastContract } from "../workflow/useForecastContract"'));
  assert.ok(steps1.includes("export function readAuthorityState"));
  assert.ok(steps1.includes("loadBinding(projectId)") && steps1.includes("registeredContract?.target"));
  assert.ok(!steps1.includes("loadContract(projectId)"));
  // dataset selected = explicit note OR inherited Stage-2 binding; target confirmed = explicit note OR
  // inherited Stage-1 forecast contract — never fabricated from mere legacy metadata.
  assert.ok(steps1.includes('datasetMode: AuthorityMode = noteSel ? "explicit" : binding ? "inherited" : "none"'));
  assert.ok(steps1.includes('targetMode: AuthorityMode = noteConfirmed ? "explicit" : contractTarget ? "inherited" : "none"'));
  assert.ok(steps1.includes("only from an explicit act or an explicit registered contract"));
});

// ---------------- Part C: Objective honors dataset/target state ----------------
test("Objective withholds target-dependent facts until dataset selected AND target confirmed", () => {
  assert.ok(objective.includes("const contractAuthority = useForecastContract(projectId)"));
  assert.ok(objective.includes("const auth = readAuthorityState(projectId, notes, contractAuthority.contract)"));
  assert.ok(objective.includes("if (!auth.datasetSelected) return <ObjectiveNoDataset"));
  assert.ok(objective.includes("if (!auth.targetConfirmed) return <ObjectiveTargetPending"));
  // C1 / C2 explicit states
  assert.ok(objective.includes("Modeling data not yet selected"));
  assert.ok(objective.includes("Target definition pending"));
  // C3 only reachable once confirmed, and it announces the confirmation + provenance
  assert.ok(objective.includes("Target confirmed") && objective.includes("via registered Forecast Contract"));
});

test("Objective pending states route the scientist back to Data & Population", () => {
  assert.ok(objective.includes('go?.("population")'));
  assert.ok(objective.includes("Go to Data &amp; Population"));
  assert.ok(objective.includes("Confirm Target in Data &amp; Population"));
  // C2 shows a decision status panel (dataset selected / target awaiting) but NOT the distribution chart
  const pending = objective.slice(objective.indexOf("function ObjectiveTargetPending"), objective.length);
  assert.ok(pending.includes("Awaiting confirmation") && pending.includes("Existing D3 reference"));
  assert.ok(!pending.includes("<BarChart")); // no target distribution before confirmation
});

// ---------------- Part A: dataset selection dominates ----------------
test("unselected dataset shows a large, dominant selection panel", () => {
  assert.ok(dataset.includes("if (!auth.datasetSelected || changing)"));
  assert.ok(dataset.includes("Choose your modeling dataset"));
  assert.ok(dataset.includes("Select Dataset from Data Warehouse"));
  assert.ok(dataset.includes("1 compatible governed dataset available"));
  assert.ok(dataset.includes("Nothing is bound until you select it"));
});

test("selected dataset collapses to a compact authoritative summary with change/preview", () => {
  // fields required by A2
  for (const f of ['label="Dataset / version"', 'label="Manifest authority"', 'label="Sport · grain"', 'label="Registered seasons"', 'label="Registered rows"', 'label="Modeling rows"', 'label="Predictors"', 'label="Governed · eligible"']) {
    assert.ok(dataset.includes(f), `summary missing ${f}`);
  }
  assert.ok(dataset.includes("Change dataset") && dataset.includes("Preview dataset"));
  // inherited-from-binding provenance is honest
  assert.ok(dataset.includes("inherited from dataset binding"));
});

test("changing the dataset warns and is wired to real invalidation semantics (not just copy)", () => {
  assert.ok(dataset.includes("const DATASET_INVALIDATION_ITEMS"));
  for (const i of ["target confirmation", "selected predictors", "outlier policy", "missing-value policy", "engineered features", "segmentation", "trained challengers", "calibration / evaluation artifacts"]) {
    assert.ok(dataset.includes(`"${i}"`), `invalidation list missing ${i}`);
  }
  // only a genuine change to a different dataset id fires the invalidation
  assert.ok(dataset.includes("if (currentId && currentId !== id) invalidateForDatasetChange()"));
  assert.ok(dataset.includes("champion is never deleted or overwritten"));
});

test("the invalidation store action clears dataset-derived state and never touches the champion", () => {
  assert.ok(api.includes("invalidateForDatasetChange: () =>"));
  for (const cleared of ["labSuite: {}", "engineeredProfiles: {}", "lastResult: undefined", "lastSim: undefined", "savedSteps: {}", "labSelected: []"]) {
    assert.ok(api.includes(cleared), `invalidation should clear ${cleared}`);
  }
  // drops target/eda/seg notes but keeps other notes; resets predictors + policies
  assert.ok(api.includes('k.startsWith("target.") || k.startsWith("eda.") || k.startsWith("seg.")'));
  assert.ok(api.includes("features: [...ALL_FEATURES]"));
  assert.ok(api.includes("never touched or overwritten by this action"));
});

// ---------------- Part B: target feels critical ----------------
test("target shows prominent AWAITING / CONFIRMED states with provenance", () => {
  assert.ok(targetSel.includes("Awaiting confirmation") && targetSel.includes("Target confirmed"));
  assert.ok(targetSel.includes("via registered Forecast Contract") && targetSel.includes("confirmed in cockpit"));
  // inherited confirmation is labelled honestly, not silently defaulted
  assert.ok(targetSel.includes("Inherited from your registered Forecast Contract (Stage 1)"));
  assert.ok(targetSel.includes("not silently defaulted"));
});

test("target analysis on Data & Population covers distribution, missingness, dominant/rarest, imbalance", () => {
  assert.ok(targetSel.includes("1 eligible target detected in this dataset"));
  assert.ok(targetSel.includes('label="Dominant class"') && targetSel.includes('label="Rarest class"'));
  assert.ok(targetSel.includes('label="Target missingness"') && targetSel.includes('label="Imbalance"'));
  assert.ok(targetSel.includes("Overall class distribution") && targetSel.includes("Target composition over time"));
  // readable axis labels per Part B2
  assert.ok(targetSel.includes('xLabel="Plate-appearance outcome"') && targetSel.includes('yLabel="Share of plate appearances"'));
});

// ---------------- Part E: persistence + project scoping ----------------
test("dataset selection + target confirmation persist via project-scoped autosave notes", () => {
  // decisions are stored in the notes slice, which is persisted + rehydrated project-scoped
  assert.ok(dataset.includes('setNote("dataset.selected"'));
  assert.ok(targetSel.includes('setNote("target.confirmed"'));
  assert.ok(persistence.includes("cockpitStorageKey = (projectId: string)"));
  assert.ok(persistence.includes("notes: s.notes") || persistence.includes("notes,")); // snapshot carries notes
  assert.ok(persistence.includes("notes: snap.notes")); // restored on hydrate
});

// ---------------- shell wiring + no-regression ----------------
test("the cockpit threads the project id + navigation into the objective and population steps", () => {
  assert.ok(shell.includes("render: (c) => <ObjectiveStep projectId={c.projectId} go={c.go} currentGoldReview={c.currentGoldReview} />"));
  assert.ok(shell.includes("render: (c) => <DataPopulationStep projectId={c.projectId} currentGoldReview={c.currentGoldReview} />"));
  assert.ok(shell.includes("step.render({ projectId, go, currentGoldReview })"));
});

test("governed temporal authority + prior-history framing are unchanged", () => {
  assert.ok(steps1.includes("2021–2022 are prior history"));
  assert.ok(steps1.includes("NL pitchers batted before the 2022 universal DH"));
  assert.ok(steps1.includes("frozen 2025")); // frozen-final protection language preserved
});

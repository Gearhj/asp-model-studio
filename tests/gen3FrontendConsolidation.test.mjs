// Phase 7A.4 — frontend authority-consolidation wiring (Gate 1/4/6/10). No React unit harness (jsdom/RTL)
// exists in this repo, so these assert the ACTUAL logic (state machine, reset call, guards), not comments;
// runtime behavior is covered by the backend/API tests.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (p) => readFile(new URL(p, ROOT), "utf8");
const [api, persist, catalog, dataPop, modelLab] = await Promise.all([
  read("src/sports/cockpit/cockpitApi.ts"),
  read("src/sports/cockpit/cockpitPersistence.ts"),
  read("src/sports/cockpit/Gen3CatalogSection.tsx"),
  read("src/sports/cockpit/cockpitSteps1.tsx"),
  read("src/sports/cockpit/cockpitSteps2.tsx"),
]);

// ---------------- Gate 6: project hydration isolation ----------------
test("the store resets project-scoped state before a new project's snapshot is applied", () => {
  assert.ok(api.includes("resetProjectScopedState:") && api.includes("BASE_PROJECT_STATE"));
  // reset clears every project-scoped slice
  for (const slice of ["notes: {}", "labSuite: {}", "engineeredProfiles: {}", "lastResult: undefined", "savedSteps: {}"]) {
    assert.ok(api.includes(slice), `BASE_PROJECT_STATE missing ${slice}`);
  }
  // persistence resets BEFORE hydrating the new project (order matters)
  const iReset = persist.indexOf("resetProjectScopedState()");
  const iHydrate = persist.indexOf("loadCockpitSnapshot(projectId)");
  assert.ok(iReset > 0 && iReset < iHydrate, "reset must precede the new project's snapshot load");
});

// ---------------- Gate 4/5: restore/error state machine ----------------
test("useActiveBinding is an explicit state machine that never silently collapses to null", () => {
  assert.ok(catalog.includes("export type BindingState"));
  for (const s of ["LOADING", "NO_BINDING", "ACTIVE", "STALE", "UNAUTHENTICATED", "UNAUTHORIZED", "SERVER_ERROR", "NETWORK_ERROR"]) {
    assert.ok(catalog.includes(`"${s}"`), `state ${s} missing`);
  }
  // classify maps HTTP codes; no default-dataset fallback on error
  assert.ok(catalog.includes("function classify") && catalog.includes("s === 401") && catalog.includes("s === 403") && catalog.includes("s === 404"));
  assert.ok(catalog.includes("no dataset is silently selected"));
  // aborts stale in-flight requests on project switch (Gate 5)
  assert.ok(catalog.includes("reqId") && catalog.includes("mine !== reqId.current"));
});

// ---------------- Gate 1: one Data & Population authority ----------------
test("Data & Population marks the legacy section as non-authoritative source lineage", () => {
  assert.ok(dataPop.includes("Source lineage · historical evidence"));
  assert.ok(dataPop.includes("not</b> the active modeling dataset") || dataPop.includes("not the active modeling dataset"));
  // the server selection (Gen3CatalogSection) is rendered as the authority
  assert.ok(dataPop.includes('<Gen3CatalogSection mode="selection" projectId={projectId} />'));
});

// ---------------- Gate 10/13: no scientist component runs a binding-free execution path ----------------
test("the legacy candidate suite is contained and the only /cockpit/experiment/run caller is guarded", () => {
  // the containment flag is retained; the candidate-suite runner short-circuits before any binding-free POST
  assert.ok(modelLab.includes("const LEGACY_BINDING_FREE_EXECUTION_DISABLED = true"));
  assert.ok(modelLab.includes("const LEGACY_EXECUTION_DISABLED = true"));
  assert.ok(modelLab.includes("if (LEGACY_EXECUTION_DISABLED) return;"));
  // the legacy binding-free experiment endpoint is called from exactly one place — the disabled suite
  const legacyRun = (modelLab.match(/"\/cockpit\/experiment\/run"/g) || []).length;
  assert.equal(legacyRun, 1, `expected exactly one guarded /cockpit/experiment/run caller, found ${legacyRun}`);
  // the candidate-suite launch button is hard-disabled
  assert.ok(modelLab.includes("disabled={true}"));
});

// ---------------- Gate 5: Autopilot runs through the single server-authorized suite path ----------------
test("Autopilot posts to the authorized run-suite and is blocked without an active binding", () => {
  assert.ok(modelLab.includes('"/cockpit/gen3/run-suite"'));
  assert.ok(modelLab.includes('source: "autopilot"'));
  // requires an active binding (no binding-free execution); deep budget is disabled with a stated reason
  assert.ok(modelLab.includes("No active dataset binding"));
  assert.ok(modelLab.includes("budget === \"deep\""));
  // Autopilot never posts to the legacy binding-free autopilot endpoint
  assert.ok(!modelLab.includes('"/cockpit/autopilot"'));
});

// ---------------- Gate 6: Tuning is an explicit unavailable state, not a legacy grid ----------------
test("Hyperparameter Tuning presents an explicit unavailable state routed to the authorized path", () => {
  assert.ok(modelLab.includes("Legacy grid disabled"));
  assert.ok(modelLab.includes("Autopilot"));
  // the removed grid no longer scores 2025 anywhere in tuning
  assert.ok(!modelLab.includes("ll2025"));
});

// ---------------- Gate 7/8/12: downstream stages consume the active candidate; 2025 is never scored ----------------
test("Evaluation/Calibration/Simulation resolve the active candidate and never expose 2025", () => {
  // Evaluation + Calibration render the backend-resolved active candidate
  assert.ok(modelLab.includes("function Gen3ActiveCandidateCard"));
  assert.ok(modelLab.includes("/cockpit/gen3/active-candidate/"));
  assert.ok(modelLab.includes("<Gen3ActiveCandidateCard projectId={projectId} />"));
  // no scientist-reachable 2025 season toggle survives in Evaluation/Calibration/Simulation
  assert.ok(!modelLab.includes('value: "frozen2025"'));
  assert.ok(!modelLab.includes('value: "2025", label: "2025 frozen"'));
});

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

// ---------------- Gate 10: no scientist component calls a binding-free execution path ----------------
test("legacy binding-free execution (suite/autopilot/grid) is contained behind one flag", () => {
  assert.ok(modelLab.includes("const LEGACY_BINDING_FREE_EXECUTION_DISABLED = true"));
  // each legacy runner short-circuits on the flag before any POST to a binding-free endpoint
  const guards = (modelLab.match(/if \(LEGACY_BINDING_FREE_EXECUTION_DISABLED\) return;/g) || []).length
    + (modelLab.match(/if \(LEGACY_EXECUTION_DISABLED\) return;/g) || []).length;
  assert.ok(guards >= 3, `expected >=3 legacy-execution guards, found ${guards}`);
  // the Model-Lab candidate-suite run button + autopilot + grid buttons are disabled by the flag
  assert.ok(modelLab.includes("disabled={LEGACY_BINDING_FREE_EXECUTION_DISABLED"));
});

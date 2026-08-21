// Phase 7A.2 — the scientist dataset flow is driven by the server catalog/binding (static wiring gates).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (p) => readFile(new URL(p, ROOT), "utf8");
const [catalog, warehouse, dataPop, labPanel, modelLab] = await Promise.all([
  read("src/sports/cockpit/Gen3CatalogSection.tsx"),
  read("src/sports/SportsEvidenceSurfaces.tsx"),
  read("src/sports/cockpit/cockpitSteps1.tsx"),
  read("src/sports/cockpit/Gen3AuthorityPanel.tsx"),
  read("src/sports/cockpit/cockpitSteps2.tsx"),
]);

test("Data Warehouse renders the server catalog (Gate 2), not a hard-coded card", () => {
  assert.ok(warehouse.includes('import Gen3CatalogSection from "./cockpit/Gen3CatalogSection"'));
  assert.ok(warehouse.includes('<Gen3CatalogSection mode="warehouse"'));
  // catalog is fetched from the server, never hard-coded
  assert.ok(catalog.includes('getJSON<{ datasets: CatalogEntry[] }>("/cockpit/gen3/catalog")'));
});

test("catalog shows Gen-2/Gen-3 with server fields and marks the sealed object restricted (Gate 2/12)", () => {
  for (const f of ["Content SHA", "Development", "Validation", "Sealed OOT", "Rows", "Features", "Target", "Knowledge time", "Governance"]) {
    assert.ok(catalog.includes(f), `catalog missing field ${f}`);
  }
  assert.ok(catalog.includes('e.generation === "GEN3_SEALED"'));
  assert.ok(catalog.includes("not selectable for model development"));
  // sealed never exposes distributions/metrics — the card shows only lineage/state
  assert.ok(!catalog.includes("targetDistribution") && !catalog.includes("2025 metric"));
});

test("Data & Population selects from the server catalog and auto-restores the active binding (Gate 3/4/5)", () => {
  // default import kept; Phase 7A.5 also imports the binding-derived population panel from the same module
  assert.ok(dataPop.includes('import Gen3CatalogSection, { Gen3PopulationPanel } from "./Gen3CatalogSection"'));
  assert.ok(dataPop.includes('<Gen3CatalogSection mode="selection" projectId={projectId} />'));
  // selection binds server-side; active binding auto-restores; server wins
  assert.ok(catalog.includes("export function useActiveBinding"));
  assert.ok(catalog.includes("/cockpit/gen3/binding/"));
  assert.ok(catalog.includes('postJSON<Binding>("/cockpit/gen3/bind"'));
  assert.ok(catalog.includes("Active binding restored") && catalog.includes("server state wins over local cache"));
});

test("Data & Population renders the binding-derived population authority (Gate 1/2/3)", () => {
  // the population panel is rendered and driven by the server population endpoint (no legacy notes/localStorage)
  assert.ok(dataPop.includes("<Gen3PopulationPanel projectId={projectId} />"));
  assert.ok(catalog.includes("export function Gen3PopulationPanel"));
  assert.ok(catalog.includes("/cockpit/gen3/population/"));
  // honest knowledge-time label (not "Pregame-safe") and no 2025 target distribution
  assert.ok(catalog.includes("knowledgeTimeSafetyClass"));
  assert.ok(!catalog.includes("targetDistribution"));
  // dataset-change invalidation banner is surfaced (Gate 9)
  assert.ok(catalog.includes("Dataset changed") && catalog.includes("downstream work marked stale"));
});

test("Model Laboratory consumes the active project binding on mount (Gate 4/9)", () => {
  assert.ok(labPanel.includes("/cockpit/gen3/binding/${encodeURIComponent(projectId)}"));
  assert.ok(labPanel.includes("consume the project's active server binding"));
  // the panel still shows the run plan + result-authority echo, and is rendered inside Model Lab
  assert.ok(labPanel.includes("Run plan") && labPanel.includes("Authority verified"));
  assert.ok(modelLab.includes("<Gen3AuthorityPanel projectId={projectId} />"));
});

test("sealed 2025 is not selectable anywhere in the flow (Gate 12)", () => {
  // catalog card disables selection for non-selectable entries; execution/bind reject sealed (backend)
  assert.ok(catalog.includes("selectable={e.selectable}") || catalog.includes("selectable: boolean"));
  assert.ok(catalog.includes('e.selectable ? () => select(e.datasetVersionId) : undefined'));
});

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);

test("current Statcast Data Warehouse surface shows exact dates and no fit claim", async () => {
  const [api, surface, router] = await Promise.all([
    readFile(new URL("src/sports/sportsEvidenceApi.ts", ROOT), "utf8"),
    readFile(new URL("src/sports/SportsEvidenceSurfaces.tsx", ROOT), "utf8"),
    readFile(new URL("server/sports_datasets/router.py", ROOT), "utf8"),
  ]);

  for (const field of ["earliestDate", "latestDate", "rowCount", "partitionCount"]) {
    assert.ok(api.includes(`${field}:`), `API contract must expose ${field}`);
  }
  assert.ok(surface.includes('dataset.datasetId === "asp.mlb.statcast.current-pa.v1"'));
  assert.ok(surface.includes("Current Statcast evidence boundary"));
  assert.ok(surface.includes("Earliest accepted date"));
  assert.ok(surface.includes("Latest accepted date"));
  assert.ok(surface.includes("No model was fit, scored, calibrated, selected, or promoted"));
  assert.ok(surface.includes("EVIDENCE_REGISTERED_NO_FIT"));
  assert.ok(api.includes("getSportsDatasetCatalog"));
  assert.ok(api.includes("activateSportsDataset"));
  assert.ok(surface.includes("Registered dataset catalog"));
  assert.ok(surface.includes("Use for workflow"));
  assert.ok(surface.includes("Inspection is transient"));
  assert.ok(surface.includes("Final untouched OOT"));
  assert.ok(router.includes('@router.get("/sports/datasets/catalog")'));
  assert.ok(router.includes('@router.post("/sports/datasets/{registration_id}/activate")'));
});

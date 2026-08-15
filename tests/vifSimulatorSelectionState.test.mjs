import assert from "node:assert/strict";
import test from "node:test";

import { resolveVifSimulatorCandidate } from "../src/lib/vifSimulatorSelection.ts";

const rows = Object.freeze([
  Object.freeze({ featureName: "acceptable", zone: "acceptable" }),
  Object.freeze({ featureName: "review", zone: "review" }),
  Object.freeze({ featureName: "material", zone: "material" }),
]);

test("a selected VIF row is the simulator candidate regardless of zone", () => {
  assert.equal(
    resolveVifSimulatorCandidate(rows, "acceptable")?.featureName,
    "acceptable",
  );
  assert.equal(
    resolveVifSimulatorCandidate(rows, "material")?.featureName,
    "material",
  );
});

test("opening without VIF selection prefers material then review, never acceptable", () => {
  assert.equal(resolveVifSimulatorCandidate(rows, null)?.featureName, "material");
  assert.equal(
    resolveVifSimulatorCandidate(rows.slice(0, 2), null)?.featureName,
    "review",
  );
  assert.equal(resolveVifSimulatorCandidate(rows.slice(0, 1), null), null);
});

test("an unrelated selection cannot become the simulator candidate", () => {
  assert.equal(resolveVifSimulatorCandidate(rows, "generic-eda-selection"), null);
});

test("candidate resolution is non-mutating", () => {
  const before = JSON.stringify(rows);
  resolveVifSimulatorCandidate(rows, null);
  assert.equal(JSON.stringify(rows), before);
});

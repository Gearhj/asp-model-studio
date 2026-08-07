import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

const acquisition = read("src/steps/Step01_DataAcquisition.tsx");
const identityProvider = read("src/components/PredictiveIdentityProvider.tsx");

function between(source, startMarker, endMarker, label) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(start, -1, `Missing ${label} start marker.`);
  assert.ok(end > start, `Missing ${label} end marker.`);
  return source.slice(start, end);
}

test("a draft target change cannot trigger authoritative identity rehydration", () => {
  const refreshEffect = between(
    identityProvider,
    "  useEffect(() => {\n    const refresh = () => retry();",
    "  }, [retry]);",
    "identity refresh effect",
  );

  assert.match(refreshEffect, /atlas-dataset-identity-updated/);
  assert.match(refreshEffect, /REPRODUCIBILITY_CONTEXT_CONFIRMED_EVENT/);
  assert.doesNotMatch(
    refreshEffect,
    /REPRODUCIBILITY_CONTEXT_PENDING_EVENT/,
    "A browser-only draft must not unmount Data Acquisition or clear its loaded dataset.",
  );
});

test("target selection preserves the loaded dataset envelope and exact identity", () => {
  const targetUpdate = between(
    acquisition,
    "  const updateTarget = (next: string) => {",
    "\n  // Debounced on registerName changes",
    "target update handler",
  );

  assert.match(targetUpdate, /markReproducibilityContextPending\(\)/);
  assert.match(targetUpdate, /const currentDataset = loadLocalDataset\(\)/);
  assert.match(targetUpdate, /saveLocalDataset\(\{[\s\S]*\.\.\.\(currentDataset \?\? \{\}\)/);
  assert.match(targetUpdate, /dataset_library: currentDataset\?\.dataset_library/);
  for (const destructiveAction of [
    "navigate(",
    "setSearchParams(",
    "window.location",
    "location.reload",
    "clearProjectDataset",
    "setActiveDatasetIdentity(null)",
    "setLoadedLibraryIdentity(null)",
    "setSelectedLibraryDatasetId(\"\")",
    "setSelectedLibraryVersionId(\"\")",
    "setHeaders([])",
    "setRows([])",
  ]) {
    assert.ok(
      !targetUpdate.includes(destructiveAction),
      `Target selection must not perform ${destructiveAction}.`,
    );
  }

  const exactRestore = between(
    acquisition,
    "    const restoreExactIdentity = async () => {",
    "    void restoreExactIdentity();",
    "exact Dataset Library restoration",
  );
  assert.match(exactRestore, /setSelectedLibraryDatasetId\(resolved\.dataset_id\)/);
  assert.match(exactRestore, /setSelectedLibraryVersionId\(resolved\.dataset_version_id\)/);
  assert.match(exactRestore, /setSourceType\("existing"\)/);
});

test("the required target column is an unmissable and accessible decision control", () => {
  const targetSetup = between(
    acquisition,
    "function TargetSetup(props:",
    "\nfunction PreviewProfilingSettings(",
    "target setup",
  );

  assert.match(targetSetup, /role="region"/);
  assert.match(targetSetup, /aria-labelledby="data-acquisition-target-heading"/);
  assert.match(targetSetup, /id="data-acquisition-target-heading"/);
  assert.match(targetSetup, /data-testid="target-column-priority-control"/);
  assert.match(targetSetup, /border-2 border-blue-600/);
  assert.match(targetSetup, /data-testid="target-column-select"/);
  assert.match(targetSetup, /required\s+aria-required="true"/);
  assert.match(targetSetup, /aria-describedby="data-acquisition-target-help"/);
  assert.match(targetSetup, /<option value="" disabled>Select a target column<\/option>/);
  assert.match(targetSetup, /Your loaded dataset stays selected/);
  assert.match(targetSetup, /role="status"[\s\S]*aria-live="polite"/);
});

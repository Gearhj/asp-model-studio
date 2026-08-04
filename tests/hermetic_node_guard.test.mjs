import assert from "node:assert/strict";
import test from "node:test";

import { validateConfig } from "../scripts/hermetic_node_guard.mjs";

function validEnvironment() {
  const root = process.env.ATLAS_HERMETIC_ROOT;
  return {
    ATLAS_HERMETIC_MODE: "HERMETIC_REGRESSION",
    ATLAS_TEST_MODE: "1",
    ATLAS_PROCESS_ROLE: "test",
    ATLAS_RUN_ID: process.env.ATLAS_RUN_ID,
    ATLAS_TEST_NAME: "hermetic-node-guard",
    ATLAS_HERMETIC_ROOT: root,
    ATLAS_BROWSER_STORAGE_ROOT: process.env.ATLAS_BROWSER_STORAGE_ROOT,
    ATLAS_PLAYWRIGHT_OUTPUT_ROOT: process.env.ATLAS_PLAYWRIGHT_OUTPUT_ROOT,
    ATLAS_TEST_BACKEND_URL: "http://atlas-hermetic.invalid",
  };
}

test("accepts isolated browser roots and a non-live backend category", () => {
  const result = validateConfig(validEnvironment());
  assert.equal(result.mode, "HERMETIC_REGRESSION");
});

for (const backend of ["http://127.0.0.1:8001", "http://localhost:5174", "http://[::1]:8001"]) {
  test(`rejects live development endpoint ${new URL(backend).port}`, () => {
    assert.throws(
      () => validateConfig({ ...validEnvironment(), ATLAS_TEST_BACKEND_URL: backend }),
      /HERMETIC_NODE_GUARD_REJECTED:live-backend/,
    );
  });
}

test("rejects browser storage outside the child root", () => {
  assert.throws(
    () => validateConfig({
      ...validEnvironment(),
      ATLAS_BROWSER_STORAGE_ROOT: process.env.ATLAS_LIVE_REPOSITORY_ROOT,
    }),
    /HERMETIC_NODE_GUARD_REJECTED:browser-root/,
  );
});

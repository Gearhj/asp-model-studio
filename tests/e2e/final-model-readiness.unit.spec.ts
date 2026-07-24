import { test, expect } from "@playwright/test";
import {
  resolveFinalModelReadiness,
  FINAL_MODEL_CONTEXT_MISMATCH_MESSAGE,
} from "../../src/lib/finalModelReadiness";

/**
 * Stage B.6 regression coverage for the Scoring page's final-model readiness resolution.
 * These run in Node (no browser fixture) and exercise the exact pure logic that
 * Step10_Scoring.tsx feeds each /model/final/status response through.
 *
 * Root cause being locked in: the old inline comparison skipped a field only when the
 * SAVED METADATA side was empty, so a missing local expectation (sessionStorage is
 * per-tab) was treated as a mismatch, and Scoring displayed "belongs to a different
 * project, dataset version, or target" even while the backend reported ready: true.
 */

const savedMetadata = {
  name: "final_model",
  project_id: "proj-1",
  dataset_version: "Class|classification|360|4|20|amount,velocity",
  target: "Class",
};

const matchingContext = {
  projectId: "proj-1",
  datasetVersion: savedMetadata.dataset_version,
  target: "Class",
};

test.describe("resolveFinalModelReadiness", () => {
  test("ready + fully matching local context -> ready, no error, metadata kept", () => {
    const view = resolveFinalModelReadiness({ ready: true, metadata: savedMetadata }, matchingContext);
    expect(view.ready).toBe(true);
    expect(view.error).toBe("");
    expect(view.metadata).toEqual(savedMetadata);
  });

  test("ready + absent local expectation (new tab / no sessionStorage dataset) -> ready, no error", () => {
    // The Stage B.6 defect: this exact input used to produce the mismatch error.
    const view = resolveFinalModelReadiness(
      { ready: true, metadata: savedMetadata },
      { projectId: "proj-1", datasetVersion: "", target: "" }
    );
    expect(view.ready).toBe(true);
    expect(view.error).toBe("");
    expect(view.metadata).toEqual(savedMetadata);
  });

  test("genuine dataset-version mismatch still rejects with the mismatch error", () => {
    const view = resolveFinalModelReadiness(
      { ready: true, metadata: savedMetadata },
      { ...matchingContext, datasetVersion: "different-version" }
    );
    expect(view.ready).toBe(false);
    expect(view.error).toBe(FINAL_MODEL_CONTEXT_MISMATCH_MESSAGE);
    expect(view.metadata).toEqual({});
  });

  test("genuine target mismatch still rejects", () => {
    const view = resolveFinalModelReadiness(
      { ready: true, metadata: savedMetadata },
      { ...matchingContext, target: "OtherTarget" }
    );
    expect(view.ready).toBe(false);
    expect(view.error).toBe(FINAL_MODEL_CONTEXT_MISMATCH_MESSAGE);
  });

  test("genuine project mismatch still rejects", () => {
    const view = resolveFinalModelReadiness({ ready: true, metadata: savedMetadata }, {
      ...matchingContext,
      projectId: "someone-elses-project",
    });
    expect(view.ready).toBe(false);
    expect(view.error).toBe(FINAL_MODEL_CONTEXT_MISMATCH_MESSAGE);
  });

  test("metadata missing a context field skips that comparison (unchanged behavior)", () => {
    const view = resolveFinalModelReadiness(
      { ready: true, metadata: { name: "final_model", project_id: "proj-1" } },
      matchingContext
    );
    expect(view.ready).toBe(true);
    expect(view.error).toBe("");
  });

  test("backend not ready -> not ready and no mismatch error, regardless of context", () => {
    const notReadyMatching = resolveFinalModelReadiness({ ready: false, metadata: {} }, matchingContext);
    expect(notReadyMatching.ready).toBe(false);
    expect(notReadyMatching.error).toBe("");

    const notReadyMismatched = resolveFinalModelReadiness(
      { ready: false, metadata: savedMetadata },
      { ...matchingContext, datasetVersion: "different-version" }
    );
    expect(notReadyMismatched.ready).toBe(false);
    expect(notReadyMismatched.error).toBe("");
  });

  test("a later response for a changed context recomputes from scratch (no sticky error)", () => {
    // The resolver is pure: the error can only exist as a function of the LATEST response
    // and the LATEST local expectation, so an earlier mismatch cannot linger. (The
    // component side additionally ignores out-of-order responses via its stale-guard,
    // asserted in tests/predictiveModelingRepair.test.mjs.)
    const first = resolveFinalModelReadiness(
      { ready: true, metadata: savedMetadata },
      { ...matchingContext, datasetVersion: "different-version" }
    );
    expect(first.error).toBe(FINAL_MODEL_CONTEXT_MISMATCH_MESSAGE);
    const second = resolveFinalModelReadiness({ ready: true, metadata: savedMetadata }, matchingContext);
    expect(second.error).toBe("");
    expect(second.ready).toBe(true);
  });

  test("null/undefined response -> not ready, no error", () => {
    const view = resolveFinalModelReadiness(null, matchingContext);
    expect(view.ready).toBe(false);
    expect(view.error).toBe("");
    expect(view.metadata).toEqual({});
  });
});

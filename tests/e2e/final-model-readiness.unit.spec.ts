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
  dataset_id: "ds-1",
  dataset_version_id: "dsv-1",
  target: "Class",
  candidate_id: "cand-1",
  training_run_id: "run-1",
  feature_manifest_version: "fm-1",
  validation_design_id: "vd-1",
  split_id: "split-1",
  model_version_id: "mv-1",
  artifact_verified: true,
  checksum: "sha256:abc",
  promotion_status: "finalized",
  lineage_status: "verified",
  designation: "champion",
  candidate_decision_id: "decision-1",
  evaluation_package_id: "eval-1",
  holdout_exposure_id: "exposure-1",
  selection_integrity_status: "verified",
  holdout_isolation_status: "verified",
  evaluation_package_integrity_status: "verified",
  promotion_readiness_status: "verified",
  final_holdout_status: "evaluated",
};

const matchingContext = {
  projectId: "proj-1",
  datasetId: "ds-1",
  datasetVersion: savedMetadata.dataset_version_id,
  target: "Class",
};

test.describe("resolveFinalModelReadiness", () => {
  test("ready + fully matching local context -> ready, no error, metadata kept", () => {
    const view = resolveFinalModelReadiness({ ready: true, metadata: savedMetadata }, matchingContext);
    expect(view.ready).toBe(true);
    expect(view.error).toBe("");
    expect(view.metadata).toEqual(savedMetadata);
  });

  test("ready + absent canonical local expectation fails closed", () => {
    const view = resolveFinalModelReadiness(
      { ready: true, metadata: savedMetadata },
      { projectId: "proj-1", datasetVersion: "", target: "" }
    );
    expect(view.ready).toBe(false);
    expect(view.error).toBe(FINAL_MODEL_CONTEXT_MISMATCH_MESSAGE);
    expect(view.metadata).toEqual({});
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

  test("metadata missing durable lineage fails closed", () => {
    const view = resolveFinalModelReadiness(
      { ready: true, metadata: { name: "final_model", project_id: "proj-1" } },
      matchingContext
    );
    expect(view.ready).toBe(false);
    expect(view.error).not.toBe("");
  });

  test("legacy or contaminated promotion evidence fails closed", () => {
    for (const override of [
      { candidate_decision_id: "" },
      { selection_integrity_status: "legacy_unresolved" },
      { holdout_isolation_status: "invalid_final_holdout_ranking" },
      { evaluation_package_integrity_status: "invalid" },
      { promotion_readiness_status: "blocked" },
      { final_holdout_status: "opened" },
    ]) {
      const view = resolveFinalModelReadiness(
        { ready: true, metadata: { ...savedMetadata, ...override } },
        matchingContext,
      );
      expect(view.ready).toBe(false);
      expect(view.metadata).toEqual({});
    }
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

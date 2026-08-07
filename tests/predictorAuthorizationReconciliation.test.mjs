import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  analysisPartitionMembershipPreserved,
  canonicalPredictorSelectionKey,
  derivePredictorAuthorizationDraftState,
  predictorAuthorizationLineageMatches,
  shouldHydratePredictorSelectionFromGovernedBaseline,
} from "../src/lib/predictorAuthorizationReconciliation.ts";

const ROOT = new URL("..", import.meta.url);
const acquisition = await readFile(
  new URL("src/steps/Step01_DataAcquisition.tsx", ROOT),
  "utf8",
);
const stepShell = await readFile(
  new URL("src/components/StepShell.tsx", ROOT),
  "utf8",
);

function partition(overrides = {}) {
  return {
    analysis_partition_id: "ap-1",
    project_id: "project-1",
    dataset_id: "dataset-1",
    dataset_version_id: "version-1",
    revision: 4,
    assignment_hash: "assignment-hash",
    artifact_hash: "artifact-hash",
    population_fingerprint: "population-fingerprint",
    target_population_fingerprint: "target-population-fingerprint",
    predictor_authorization_id: "pa-1",
    ...overrides,
  };
}

function functionBody(source, name) {
  const start = source.indexOf(`async function ${name}(`);
  assert.ok(start >= 0, `missing ${name}`);
  const openingBrace = source.indexOf("{", start);
  let depth = 0;
  for (let index = openingBrace; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  assert.fail(`could not isolate ${name}`);
}

test("predictor keys are canonical and order independent", () => {
  assert.equal(
    canonicalPredictorSelectionKey(["beta", "alpha", "beta"]),
    JSON.stringify(["alpha", "beta"]),
  );
  assert.equal(
    canonicalPredictorSelectionKey(["alpha", "beta"]),
    canonicalPredictorSelectionKey(["beta", "alpha"]),
  );
  assert.notEqual(
    canonicalPredictorSelectionKey(["alpha|beta"]),
    canonicalPredictorSelectionKey(["alpha", "beta"]),
  );
  assert.notEqual(
    canonicalPredictorSelectionKey([" feature "]),
    canonicalPredictorSelectionKey(["feature"]),
  );
});

test("a changed nonempty selection exposes an actionable governed update", () => {
  const state = derivePredictorAuthorizationDraftState({
    partitionCurrent: true,
    confirmedSelectionKey: "alpha|beta",
    selectedPredictors: ["alpha"],
    saving: false,
    baselinePhase: "ready",
  });
  assert.equal(state.dirty, true);
  assert.equal(state.canUpdate, true);
  assert.match(state.reason, /Save the predictor selection/);
});

test("zero selected predictors remain blocked with the truthful local-draft reason", () => {
  const state = derivePredictorAuthorizationDraftState({
    partitionCurrent: true,
    confirmedSelectionKey: "alpha|beta",
    selectedPredictors: [],
    saving: false,
    baselinePhase: "ready",
  });
  assert.equal(state.dirty, true);
  assert.equal(state.canUpdate, false);
  assert.match(state.reason, /Approve at least one eligible predictor/);
});

test("an unchanged or still-saving selection cannot issue a duplicate update", () => {
  const current = derivePredictorAuthorizationDraftState({
    partitionCurrent: true,
    confirmedSelectionKey: canonicalPredictorSelectionKey(["alpha", "beta"]),
    selectedPredictors: ["beta", "alpha"],
    saving: false,
    baselinePhase: "ready",
  });
  assert.deepEqual(current, {
    dirty: false,
    canUpdate: false,
    needsBaseline: false,
    canRetryBaseline: false,
    reason: "",
    actionLabel: "Predictor Authorization Current",
  });
  const saving = derivePredictorAuthorizationDraftState({
    partitionCurrent: true,
    confirmedSelectionKey: canonicalPredictorSelectionKey(["alpha", "beta"]),
    selectedPredictors: ["alpha"],
    saving: true,
    baselinePhase: "ready",
  });
  assert.equal(saving.dirty, true);
  assert.equal(saving.canUpdate, false);
  assert.match(saving.actionLabel, /Updating/);
});

test("a current partition fails closed while its exact predictor baseline is loading and exposes a retry after failure", () => {
  const pending = derivePredictorAuthorizationDraftState({
    partitionCurrent: true,
    confirmedSelectionKey: "",
    selectedPredictors: ["alpha"],
    saving: false,
    baselinePhase: "pending",
  });
  assert.equal(pending.dirty, true);
  assert.equal(pending.needsBaseline, true);
  assert.equal(pending.canUpdate, false);
  assert.equal(pending.canRetryBaseline, false);
  assert.match(pending.reason, /verifying the exact/i);

  const failed = derivePredictorAuthorizationDraftState({
    partitionCurrent: true,
    confirmedSelectionKey: "",
    selectedPredictors: ["alpha"],
    saving: false,
    baselinePhase: "error",
  });
  assert.equal(failed.dirty, true);
  assert.equal(failed.needsBaseline, true);
  assert.equal(failed.canRetryBaseline, true);
  assert.match(failed.actionLabel, /Retry/);
});

test("an untouched stale browser selection hydrates from the exact governed baseline without overwriting an explicit draft", () => {
  const base = {
    partitionCurrent: true,
    baselineExact: true,
    governedPredictors: ["alpha", "beta"],
    localPredictors: [],
  };
  assert.equal(
    shouldHydratePredictorSelectionFromGovernedBaseline({
      ...base,
      selectionTouched: false,
    }),
    true,
  );
  assert.equal(
    shouldHydratePredictorSelectionFromGovernedBaseline({
      ...base,
      selectionTouched: true,
    }),
    false,
  );
  assert.equal(
    shouldHydratePredictorSelectionFromGovernedBaseline({
      ...base,
      baselineExact: false,
      selectionTouched: false,
    }),
    false,
  );
});

test("a changed authorization is accepted only when immutable partition membership is preserved", () => {
  const baseline = partition();
  const changedAuthorization = partition({
    predictor_authorization_id: "pa-1",
    current_predictor_authorization_id: "pa-2",
    predictor_authorization_lineage_status: "changed_partition_preserved",
  });
  assert.equal(
    analysisPartitionMembershipPreserved(
      baseline,
      changedAuthorization,
    ),
    true,
  );
  for (const changed of [
    { analysis_partition_id: "ap-2" },
    { revision: 5 },
    { assignment_hash: "different-assignment" },
    { artifact_hash: "different-artifact" },
    { population_fingerprint: "different-population" },
  ]) {
    assert.equal(
      analysisPartitionMembershipPreserved(
        baseline,
        partition(changed),
      ),
      false,
    );
  }
});

test("predictor-authorization lineage must match the newly returned contract and the backend preservation status", () => {
  assert.equal(
    predictorAuthorizationLineageMatches(
      {
        predictor_authorization_id: "pa-1",
        current_predictor_authorization_id: "pa-2",
        predictor_authorization_lineage_status: "changed_partition_preserved",
      },
      "pa-2",
    ),
    true,
  );
  assert.equal(
    predictorAuthorizationLineageMatches(
      {
        predictor_authorization_id: "pa-1",
        current_predictor_authorization_id: "pa-2",
        predictor_authorization_lineage_status: "current",
      },
      "pa-2",
    ),
    false,
  );
  assert.equal(
    predictorAuthorizationLineageMatches(
      {
        predictor_authorization_id: "pa-1",
        current_predictor_authorization_id: "pa-2",
        predictor_authorization_lineage_status: "changed_partition_preserved",
      },
      "pa-3",
    ),
    false,
  );
});

test("Data Acquisition reconciles predictors without previewing, confirming, or resetting membership", () => {
  assert.match(acquisition, /data-testid="update-predictor-authorization"/);
  assert.match(acquisition, /data-testid="predictor-authorization-draft-status"/);
  assert.match(
    acquisition,
    /predictor_authorization\?\.selected_predictors \?\? \[\]/,
  );
  assert.match(
    acquisition,
    /shouldHydratePredictorSelectionFromGovernedBaseline/,
  );
  assert.match(acquisition, /predictorSelectionTouched\.current = true/);
  assert.match(acquisition, /canRetryBaseline/);
  assert.match(acquisition, /onBlockedNextClick=\{resolveDataAcquisitionBlocker\}/);
  assert.match(acquisition, /"credit-bureau-review"/);
  assert.match(acquisition, /data-testid="predictor-select-all"/);
  assert.match(
    acquisition,
    /predictorAuthorizationVerificationError \|\|\s+predictorAuthorizationDraft\.canUpdate/,
  );
  assert.match(stepShell, /nextDisabled && !onBlockedNextClick/);
  assert.match(
    stepShell,
    /onClick=\{nextDisabled \? onBlockedNextClick : onNextClick \?\? handleNext\}/,
  );
  assert.doesNotMatch(
    acquisition,
    /The approved predictor set changed after the Analysis Partition was verified/,
  );
  const update = functionBody(acquisition, "updatePredictorAuthorization");
  const persistIndex = update.indexOf("persistDataset(canonical)");
  const statusIndex = update.indexOf("readAnalysisPartitionReadiness(");
  const membershipIndex = update.indexOf(
    "analysisPartitionMembershipPreserved(baseline, current)",
  );
  assert.ok(persistIndex >= 0 && statusIndex > persistIndex);
  assert.ok(membershipIndex > statusIndex);
  assert.match(update, /predictorAuthorizationLineageMatches/);
  assert.match(update, /setConfirmedPartitionPredictorKey\(submittedPredictorKey\)/);
  assert.match(update, /predictorAuthorizationOperationRevision\.current/);
  assert.match(update, /operationRevision !== predictorAuthorizationOperationRevision\.current/);
  assert.doesNotMatch(
    update,
    /readAnalysisPartitionPreview|createOrReuseAnalysisPartition|reset_existing|confirmGovernedAnalysisPartitionReset/,
  );
});

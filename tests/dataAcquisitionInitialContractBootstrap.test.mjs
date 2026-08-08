import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  claimInitialContractBootstrapAttempt,
  decideInitialContractBootstrap,
  initialContractBootstrapKey,
  releaseInitialContractBootstrapAttempt,
} from "../src/lib/dataAcquisitionInitialContractBootstrap.ts";

const identity = {
  project_id: "project-fresh",
  dataset_id: "dataset-fresh",
  dataset_version_id: "version-fresh",
};

const targetPendingContext = {
  ok: true,
  state: "target_pending",
  project_id: identity.project_id,
  context_id: "context-fresh",
  identity: {
    ...identity,
    dataset_name: "Fresh dataset",
    dataset_version_label: "v1",
    source_type: "upload",
    activation_revision: 1,
    governed_population_rows: 100,
    source_columns: 3,
  },
  target_contract: null,
  predictor_authorization: null,
  analysis_partition: null,
  authority: {
    binding: "exact_registered_version",
    fallback_used: false,
    browser_state_authoritative: false,
    row_data_included: false,
    assignments_included: false,
    target_aggregates_included: false,
    final_holdout_access: "protected_metadata_only",
  },
};

test("a fresh exact identity claims one initial target and predictor bootstrap", () => {
  const selectedPredictors = ["income", "age"];
  const decision = decideInitialContractBootstrap({
    context: targetPendingContext,
    identity,
    target: "bad_flag",
    selectedPredictors,
    backendSynced: true,
    targetSelectionConfirmed: true,
    localPartitionPresent: false,
  });
  assert.deepEqual(decision, {
    shouldBootstrap: true,
    reason: "fresh_target_pending",
  });

  const key = initialContractBootstrapKey({
    identity,
    target: "bad_flag",
    eventValue: 1,
    nonEventValue: 0,
    selectedPredictors,
  });
  const attempted = new Set();
  assert.equal(claimInitialContractBootstrapAttempt(attempted, key), true);
  assert.equal(
    claimInitialContractBootstrapAttempt(attempted, key),
    false,
    "the same render/mount identity must not issue a second bootstrap",
  );
  releaseInitialContractBootstrapAttempt(attempted, key);
  assert.equal(
    claimInitialContractBootstrapAttempt(attempted, key),
    true,
    "an attempt aborted before persistence begins must be claimable by the surviving effect",
  );
});

test("an inferred target does not bootstrap before explicit target confirmation", () => {
  assert.deepEqual(
    decideInitialContractBootstrap({
      context: targetPendingContext,
      identity,
      target: "bad_flag",
      selectedPredictors: ["income"],
      backendSynced: true,
      targetSelectionConfirmed: false,
      localPartitionPresent: false,
    }),
    { shouldBootstrap: false, reason: "input_incomplete" },
  );
});

test("current target authority or a sealed partition disables the initial bootstrap", () => {
  const authorityContext = {
    ...targetPendingContext,
    state: "partition_pending",
    target_contract: {
      target_contract_id: "target-contract-current",
      target: "bad_flag",
      event_value: 1,
      non_event_value: 0,
    },
    predictor_authorization: {
      predictor_authorization_id: "predictor-auth-current",
      status: "current",
      authorized_predictors: ["income"],
      selected_predictors: ["income"],
      excluded_fields: { bad_flag: "target" },
      deterministic_source_exclusions: [],
      target_source_detection_scope: "development_population",
      funnel: {
        source_column_count: 2,
        target_exclusions: [{ field: "bad_flag", reason: "target" }],
        candidate_predictor_count: 1,
        selected_predictor_count: 1,
        authorized_predictor_count: 1,
        additional_exclusions: {},
        model_ready_status: "not_established_in_data_acquisition",
      },
    },
  };
  assert.deepEqual(
    decideInitialContractBootstrap({
      context: authorityContext,
      identity,
      target: "bad_flag",
      selectedPredictors: ["income"],
      backendSynced: true,
      targetSelectionConfirmed: true,
      localPartitionPresent: false,
    }),
    { shouldBootstrap: false, reason: "authority_already_exists" },
  );
  assert.deepEqual(
    decideInitialContractBootstrap({
      context: authorityContext,
      identity,
      target: "bad_flag",
      selectedPredictors: ["income"],
      backendSynced: true,
      targetSelectionConfirmed: true,
      allowAuthorityReplacement: true,
      localPartitionPresent: false,
    }),
    { shouldBootstrap: true, reason: "explicit_authority_reconfirmation" },
    "an explicit pre-partition reconfirmation may update changed mapping or predictors",
  );

  assert.deepEqual(
    decideInitialContractBootstrap({
      context: {
        ...authorityContext,
        identity: { ...authorityContext.identity, dataset_id: "other-dataset" },
      },
      identity,
      target: "bad_flag",
      selectedPredictors: ["income"],
      backendSynced: true,
      targetSelectionConfirmed: true,
      allowAuthorityReplacement: true,
      localPartitionPresent: false,
    }),
    { shouldBootstrap: false, reason: "identity_mismatch" },
    "identity mismatch must win over the presence of prior authority",
  );

  assert.deepEqual(
    decideInitialContractBootstrap({
      context: targetPendingContext,
      identity,
      target: "bad_flag",
      selectedPredictors: ["income"],
      backendSynced: true,
      targetSelectionConfirmed: true,
      localPartitionPresent: true,
    }),
    { shouldBootstrap: false, reason: "partition_already_exists" },
  );
});

test("exact bootstrap read-back explicitly retriggers special-value detection and partition preview", () => {
  const acquisition = readFileSync(
    new URL("../src/steps/Step01_DataAcquisition.tsx", import.meta.url),
    "utf8",
  );
  const bureauPanel = readFileSync(
    new URL("../src/components/BureauReviewPanel.tsx", import.meta.url),
    "utf8",
  );
  assert.match(
    acquisition,
    /verifiedExact[\s\S]*setBureauDetectionRefreshRevision\(\(revision\) => revision \+ 1\)/,
  );
  assert.match(
    acquisition,
    /refreshRevision=\{bureauDetectionRefreshRevision\}/,
  );
  assert.match(
    acquisition,
    /data-testid="confirm-initial-target-contract"/,
  );
  assert.match(
    acquisition,
    /targetSelectionRevision === 0[\s\S]{0,1800}Confirm Target &amp; Predictor Contract/,
  );
  assert.match(
    bureauPanel,
    /datasetIdentity\?\.activation_revision,[\s\S]{0,120}refreshRevision,/,
  );
  assert.match(
    acquisition,
    /pendingInitialTargetContractId[\s\S]*pendingInitialPredictorAuthorizationId[\s\S]*readAnalysisPartitionPreview/,
  );
  assert.match(
    acquisition,
    /verified\.target_contract\?\.event_value[\s\S]{0,500}verified\.target_contract\?\.non_event_value[\s\S]{0,500}verified\.predictor_authorization\?\.selected_predictors/,
  );
  assert.match(
    acquisition,
    /const governedPredictorKey = canonicalPredictorSelectionKey\([\s\S]{0,160}authorized_predictors/,
    "the effective browser selection must compare with the backend-authorized set, not rejected submissions",
  );
  assert.match(
    acquisition,
    /const authorizedPredictors =[\s\S]{0,1600}setKept\([\s\S]{0,320}setTargetSelectionRevision\(0\)/,
    "exact read-back must align the browser to the authorized set and end the confirmation attempt",
  );
  assert.ok(
    (acquisition.match(/setTargetSelectionRevision\(0\)/g)?.length ?? 0) >= 3,
    "loading a new source, changing class mapping, and changing pre-partition predictors must reset confirmation",
  );
  assert.match(
    acquisition,
    /backendSynced = true;[\s\S]{0,180}notifyReproducibilityContextConfirmed\(\);[\s\S]{0,180}setBureauDetectionRefreshRevision/,
  );
  assert.match(
    acquisition,
    /return \(\) => \{[\s\S]{0,900}if \(!persistenceStarted\) \{[\s\S]{0,120}controller\.abort\(\)/,
    "a React rerender must not abort an exact target-contract write after persistence starts",
  );
  const partitionRefreshes = acquisition.match(
    /setBureauDetectionRefreshRevision\(\(revision\) => revision \+ 1\)/g,
  );
  assert.ok(
    (partitionRefreshes?.length ?? 0) >= 3,
    "initial bootstrap and successful partition transitions must refresh detection",
  );
  assert.match(
    acquisition,
    /specialValueReviewMatchesCurrentPartition[\s\S]*analysis_partition_assignment_hash[\s\S]*analysis_partition_artifact_hash/,
  );
  assert.match(
    acquisition,
    /if \(!specialValueReviewMatchesCurrentPartition\)[\s\S]{0,300}final Data Acquisition handoff requires a confirmed Special-Value Treatment Review/,
  );
});

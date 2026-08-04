import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync(
  "src/lib/dataAcquisitionReproducibility.ts",
  "utf8",
);
const panelSource = fs.readFileSync("src/components/StepPythonPanel.tsx", "utf8");
const backendSource = fs.readFileSync("server/core/metadata_router.py", "utf8");

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2021,
    module: ts.ModuleKind.CommonJS,
    esModuleInterop: true,
  },
  fileName: "dataAcquisitionReproducibility.ts",
}).outputText;
const moduleRecord = { exports: {} };
const sandbox = {
  module: moduleRecord,
  exports: moduleRecord.exports,
  require(specifier) {
    if (specifier === "./serverPersistence") {
      return {
        persistenceRequest: async () => {
          throw new Error("Network access is not used by this pure generator test.");
        },
      };
    }
    throw new Error(`Unexpected test import: ${specifier}`);
  },
  window: { dispatchEvent() {} },
  CustomEvent: class CustomEvent {},
  AbortController,
  URL,
  JSON,
  String,
  Date,
  Error,
  console,
};
vm.runInNewContext(compiled, sandbox, {
  filename: "dataAcquisitionReproducibility.js",
});
const contract = moduleRecord.exports;

const maliciousDatasetName = `loan\"; __import__('os').system('never-run') #`;
const maliciousTarget = `bad'); %put SHOULD_NOT_RUN; /*`;
const current = {
  ok: true,
  state: "current",
  project_id: "project-exact",
  context_id: "repro-context-exact",
  identity: {
    project_id: "project-exact",
    dataset_name: maliciousDatasetName,
    dataset_id: "dataset-exact",
    dataset_version_id: "version-exact-7",
    dataset_version_label: "Version 7",
    source_type: "registered_upload",
    activation_revision: 4,
    governed_population_rows: 120,
    source_columns: 5,
  },
  target_contract: {
    target_contract_id: "target-contract-exact",
    target: maliciousTarget,
    event_value: `1\"\nraise RuntimeError('never-run')`,
    non_event_value: 0,
  },
  predictor_authorization: {
    predictor_authorization_id: "predictor-auth-exact",
    status: "current",
    authorized_predictors: ["feature_a", "feature_'quoted"],
    selected_predictors: ["feature_a", "feature_'quoted"],
    excluded_fields: {
      source_target: "Governed deterministic source",
      "fold; stop;": "Split metadata",
    },
    deterministic_source_exclusions: ["source_target"],
    target_source_detection_scope: "development_partition",
    funnel: {
      source_column_count: 5,
      target_exclusions: [
        { field: maliciousTarget, reason: "Selected modeling outcome; never authorized as a predictor" },
      ],
      candidate_predictor_count: 4,
      selected_predictor_count: 2,
      authorized_predictor_count: 2,
      additional_exclusions: { "fold; stop;": "Split metadata" },
      model_ready_status: "not_established_in_data_acquisition",
    },
  },
  analysis_partition: {
    analysis_partition_id: "analysis-partition-exact-r3",
    revision: 3,
    status: "current",
    development_share: 0.8,
    holdout_share: 0.2,
    development_rows: 96,
    sealed_holdout_rows: 24,
    random_seed: 42,
    stratification_policy: "target",
    stratification_field: maliciousTarget,
    final_holdout_status: "sealed",
    holdout_isolation_status: "verified",
  },
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

const validated = contract.validateDataAcquisitionReproducibilityContext(current);
assert.equal(validated.state, "current");
assert.equal(contract.isCurrentDataAcquisitionReproducibilityContext(validated), true);
assert.equal(validated.predictor_authorization.funnel.source_column_count, 5);
assert.equal(validated.predictor_authorization.funnel.authorized_predictor_count, 2);

const python = contract.buildDataAcquisitionPythonContext(validated);
for (const field of [
  "PROJECT_ID",
  "DATASET_NAME",
  "DATASET_ID",
  "DATASET_VERSION_ID",
  "TARGET",
  "EVENT_VALUE",
  "NON_EVENT_VALUE",
  "AUTHORIZED_PREDICTORS",
  "EXCLUDED_FIELDS",
  "DETERMINISTIC_SOURCE_EXCLUSIONS",
  "ANALYSIS_PARTITION_ID",
  "ANALYSIS_PARTITION_REVISION",
  "DEVELOPMENT_ROWS",
  "SEALED_HOLDOUT_ROWS",
]) {
  assert.ok(python.includes(field), `Python context must include ${field}.`);
}
assert.match(python, /no local filesystem path is assumed/i);
assert.match(python, /final holdout remains sealed/i);
assert.doesNotMatch(python, /atlas\.load_dataset|read_csv|ATLAS_DATASET_PATH/);
const embeddedPythonJson = python.match(/_atlas_json\.loads\((.+)\)/)?.[1];
assert.ok(embeddedPythonJson, "Python must embed one safely quoted JSON string.");
const decodedPythonMetadata = JSON.parse(JSON.parse(embeddedPythonJson));
assert.equal(decodedPythonMetadata.dataset_name, maliciousDatasetName);
assert.equal(decodedPythonMetadata.target, maliciousTarget);

const sas = contract.buildDataAcquisitionSasContext(validated);
assert.match(sas, /call symputx\('atlas_dataset_version_id'/i);
assert.match(sas, /call symputx\('atlas_analysis_partition_id'/i);
assert.match(sas, /protected_metadata_only/);
assert.match(sas, /bad''\); %put SHOULD_NOT_RUN; \/\*/);
assert.doesNotMatch(
  sas,
  /\blibname\b|\bcaslib\b|\bproc\s+import\b|\bdsn\s*=|path\/to|cloud:\/\/|set\s+atlas\./i,
);
assert.equal(
  contract.sasCharacterLiteral(`a'; %put injected; /*`),
  `'a''; %put injected; /*'`,
);

const metadata = JSON.parse(
  contract.buildDataAcquisitionMetadataContext(validated),
);
assert.equal(metadata.dataset_id, "dataset-exact");
assert.equal(metadata.dataset_version_id, "version-exact-7");
assert.equal(metadata.development_rows, 96);
assert.equal(metadata.sealed_holdout_rows, 24);
assert.equal(metadata.final_holdout_access, "protected_metadata_only");
assert.equal("row_assignments" in metadata, false);
assert.equal("event_counts" in metadata, false);

const fingerprint = contract.buildConfirmedDataAcquisitionCodeContext(
  validated,
  "python",
);
assert.equal(fingerprint.datasetId, "dataset-exact");
assert.match(fingerprint.predictorManifestId, /predictor-auth-exact/);
assert.match(fingerprint.predictorManifestId, /analysis-partition-exact-r3/);
assert.match(fingerprint.predictorManifestId, /revision-3/);
const changedPartition = structuredClone(current);
changedPartition.analysis_partition.analysis_partition_id =
  "analysis-partition-exact-r4";
changedPartition.analysis_partition.revision = 4;
const changedFingerprint = contract.buildConfirmedDataAcquisitionCodeContext(
  changedPartition,
  "python",
);
assert.notEqual(
  fingerprint.predictorManifestId,
  changedFingerprint.predictorManifestId,
  "A partition revision must invalidate the current code-draft identity.",
);

for (const state of ["identity_pending", "target_pending", "partition_pending"]) {
  assert.throws(
    () =>
      contract.buildDataAcquisitionPythonContext({
        ...current,
        state,
        identity: null,
        target_contract: null,
        predictor_authorization: null,
        analysis_partition: null,
      }),
    /before generating code|before publishing current development code/,
  );
}
assert.throws(
  () =>
    contract.validateDataAcquisitionReproducibilityContext({
      ...current,
      state: "identity_pending",
    }),
  /must not publish stale governed metadata/,
);
assert.throws(
  () =>
    contract.validateDataAcquisitionReproducibilityContext({
      ...current,
      authority: { ...current.authority, fallback_used: true },
    }),
  /exact, metadata-only authority contract/,
);

assert.match(panelSource, /fetchDataAcquisitionReproducibilityContext/);
assert.match(panelSource, /buildDataAcquisitionPythonContext/);
assert.match(panelSource, /buildDataAcquisitionSasContext/);
assert.match(panelSource, /buildDataAcquisitionMetadataContext/);
assert.match(panelSource, /language: "metadata"/);
assert.match(panelSource, /Download \.py/);
assert.match(panelSource, /Download \.sas/);
assert.match(panelSource, /REPRODUCIBILITY_CONTEXT_PENDING_EVENT/);
assert.match(panelSource, /Generated code is withheld until the backend confirms/);
assert.doesNotMatch(
  panelSource,
  /path\/to\/modeling_data|GOVERNED_DSN|source\.governed_table|atlas\.governed_interchange|path\/to\/sas\/library|ATLAS_DATASET_PATH/,
);

assert.match(backendSource, /@router\.get\("\/data\/reproducibility-context"\)/);
assert.match(backendSource, /get_current_exact\(/);
assert.match(backendSource, /"fallback_used": False/);
assert.match(backendSource, /"assignments_included": False/);
assert.match(backendSource, /"target_aggregates_included": False/);
const endpointSource = backendSource.slice(
  backendSource.indexOf('@router.get("/data/reproducibility-context")'),
  backendSource.indexOf('@router.get("/columns")'),
);
assert.doesNotMatch(endpointSource, /get_sample|row_assignments_json|event_counts_json|artifact_path/);

console.log("dataAcquisitionReproducibility.test.mjs: all checks passed.");

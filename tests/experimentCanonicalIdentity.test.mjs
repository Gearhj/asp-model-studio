import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import test, { after } from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = await mkdtemp(
  path.join(tmpdir(), "atlas-canonical-experiments-"),
);

class MemoryStorage {
  values = new Map();

  clear() {
    this.values.clear();
  }

  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }

  setItem(key, value) {
    this.values.set(key, String(value));
  }

  removeItem(key) {
    this.values.delete(key);
  }
}

globalThis.localStorage = new MemoryStorage();
globalThis.window = { dispatchEvent() {} };
globalThis.CustomEvent = class {
  constructor(type) {
    this.type = type;
  }
};
globalThis.fetch = async () => ({ ok: false });

async function transpile(sourcePath, outputName, replacements = []) {
  let source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
      importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
    },
  }).outputText;
  source = replacements.reduce(
    (current, [pattern, replacement]) =>
      current.replaceAll(pattern, replacement),
    output,
  );
  const outputPath = path.join(TMP_DIR, outputName);
  await writeFile(outputPath, source, "utf8");
  return outputPath;
}

await writeFile(
  path.join(TMP_DIR, "decisionJournal.mjs"),
  "export function logDecision() {}\n",
  "utf8",
);
await writeFile(
  path.join(TMP_DIR, "brand.mjs"),
  'export const BRAND = { productName: "ATLAS", productSubtitle: "Test" };\n',
  "utf8",
);
await writeFile(
  path.join(TMP_DIR, "localDataset.mjs"),
  [
    "let current = null;",
    "export function setLocalDataset(value) { current = value; }",
    "export function loadLocalDataset() { return current; }",
    "",
  ].join("\n"),
  "utf8",
);
await writeFile(
  path.join(TMP_DIR, "edaDocumentationApi.mjs"),
  "export async function getEdaDocumentationState() { throw new Error('not used'); }\n",
  "utf8",
);
await writeFile(
  path.join(TMP_DIR, "datasetLibrary.mjs"),
  'export const DATASET_API_BASE = "http://127.0.0.1:8001/api";\n',
  "utf8",
);

const datasetIdentityPath = await transpile(
  "src/lib/datasetIdentity.ts",
  "datasetIdentity.mjs",
);
const preparationPath = await transpile(
  "src/lib/preparationGovernance.ts",
  "preparationGovernance.mjs",
  [
    ['"./edaDocumentationApi"', '"./edaDocumentationApi.mjs"'],
    ['"./datasetLibrary"', '"./datasetLibrary.mjs"'],
    ['"./datasetIdentity"', '"./datasetIdentity.mjs"'],
  ],
);
const experimentPath = await transpile(
  "src/lib/experimentTracking.ts",
  "experimentTracking.mjs",
  [
    ['"./decisionJournal"', '"./decisionJournal.mjs"'],
    ['"./localDataset"', '"./localDataset.mjs"'],
    ['"../config/brand"', '"./brand.mjs"'],
    ['"./datasetIdentity"', '"./datasetIdentity.mjs"'],
    ['"./preparationGovernance"', '"./preparationGovernance.mjs"'],
  ],
);

const experiments = await import(pathToFileURL(experimentPath).href);
const datasetIdentity = await import(
  pathToFileURL(datasetIdentityPath).href
);
const preparation = await import(pathToFileURL(preparationPath).href);
const localDataset = await import(
  pathToFileURL(path.join(TMP_DIR, "localDataset.mjs")).href
);

after(async () => {
  await rm(TMP_DIR, { recursive: true, force: true });
});

const IDENTITY = {
  project_id: "project-001",
  dataset_id: "dataset-heloc",
  dataset_version_id: "version-immutable-001",
};

function canonicalRecord(overrides = {}) {
  return {
    experimentId: "experiment-001",
    timestamp: "2026-07-30T12:00:00.000Z",
    ...IDENTITY,
    trainingJobId: "training-job-001",
    selectedFeatures: ["risk_score"],
    preprocessingSteps: {},
    balancingMethod: "none",
    splitStrategy: "holdout",
    modelKey: "logreg",
    modelType: "Logistic Regression",
    hyperparameters: null,
    metrics: { auc: 0.81 },
    calibrationStatus: "not calibrated",
    interpretability: 95,
    runtimeMs: 100,
    champion: false,
    notes: "Candidate",
    ...overrides,
  };
}

test("legacy target-row-count-hash experiments are stale and ignored", () => {
  localStorage.clear();
  localStorage.setItem(
    experiments.EXPERIMENT_TRACKING_KEY,
    JSON.stringify([
      {
        ...canonicalRecord(),
        project_id: undefined,
        dataset_id: undefined,
        dataset_version_id: undefined,
        datasetHash: "deadbeef",
        datasetVersion: "bad_flag-100-deadbeef",
      },
      canonicalRecord(),
      canonicalRecord({
        experimentId: "contradictory-alias",
        datasetVersion: "bad_flag-100-cafebabe",
      }),
    ]),
  );

  assert.deepEqual(
    experiments.loadExperiments().map((record) => record.experimentId),
    ["experiment-001"],
  );
});

test("experiment selection requires the exact canonical triple and never falls back", () => {
  localStorage.clear();
  const otherVersion = canonicalRecord({
    experimentId: "experiment-version-002",
    dataset_version_id: "version-immutable-002",
  });
  const otherProject = canonicalRecord({
    experimentId: "experiment-project-002",
    project_id: "project-002",
  });
  localStorage.setItem(
    experiments.EXPERIMENT_TRACKING_KEY,
    JSON.stringify([canonicalRecord(), otherVersion, otherProject]),
  );

  assert.deepEqual(
    experiments
      .loadExperiments(IDENTITY)
      .map((record) => record.experimentId),
    ["experiment-001"],
  );
  assert.deepEqual(
    experiments.loadExperiments({
      ...IDENTITY,
      dataset_version_id: "version-does-not-exist",
    }),
    [],
  );
});

test("new training experiments store canonical identity and explicit artifact IDs", async () => {
  localStorage.clear();
  localDataset.setLocalDataset({
    headers: ["risk_score", "bad_flag"],
    rows: [
      { risk_score: 640, bad_flag: 0 },
      { risk_score: 515, bad_flag: 1 },
    ],
    target: "bad_flag",
    selected_columns: ["risk_score"],
    dataset_id: IDENTITY.dataset_id,
    dataset_version_id: IDENTITY.dataset_version_id,
    dataset_version: IDENTITY.dataset_version_id,
    dataset_library: {
      datasetId: IDENTITY.dataset_id,
      versionId: IDENTITY.dataset_version_id,
    },
    data_access: {
      accessMetadataId: "access-metadata-001",
      hash: "content-hash-001",
    },
  });

  const captured = await experiments.recordTrainingExperiments({
    apiBase: "http://127.0.0.1:8001/api",
    datasetIdentity: IDENTITY,
    trainingJobId: "training-job-explicit-001",
    ranked: [
      {
        key: "logreg",
        name: "Logistic Regression",
        task: "classification",
        auc: 0.82,
      },
    ],
    selectedModelKeys: ["logreg"],
    trainingSettings: {},
    runtimeMs: 1200,
    calibrated: false,
  });

  assert.equal(captured.length, 1);
  assert.equal(captured[0].project_id, IDENTITY.project_id);
  assert.equal(captured[0].dataset_id, IDENTITY.dataset_id);
  assert.equal(
    captured[0].dataset_version_id,
    IDENTITY.dataset_version_id,
  );
  assert.equal(captured[0].trainingJobId, "training-job-explicit-001");
  assert.equal(captured[0].accessMetadataId, "access-metadata-001");
  assert.equal(captured[0].datasetContentHash, "content-hash-001");
  assert.equal(Object.hasOwn(captured[0], "datasetVersion"), false);
  assert.equal(Object.hasOwn(captured[0], "datasetHash"), false);
});

test("recording rejects identity drift and a missing training artifact ID", async () => {
  await assert.rejects(
    experiments.recordTrainingExperiments({
      apiBase: "http://127.0.0.1:8001/api",
      datasetIdentity: {
        ...IDENTITY,
        dataset_version_id: "version-stale",
      },
      trainingJobId: "training-job-stale",
      ranked: [],
      selectedModelKeys: [],
      trainingSettings: {},
      runtimeMs: 0,
      calibrated: false,
    }),
    /does not match the exact Dataset Library version/,
  );

  await assert.rejects(
    experiments.recordTrainingExperiments({
      apiBase: "http://127.0.0.1:8001/api",
      datasetIdentity: IDENTITY,
      trainingJobId: "",
      ranked: [],
      selectedModelKeys: [],
      trainingSettings: {},
      runtimeMs: 0,
      calibrated: false,
    }),
    /explicit training job artifact ID/,
  );
});

test("preparation state is exact-version scoped and ignores global and other-version values", async () => {
  localStorage.clear();
  const otherIdentity = {
    ...IDENTITY,
    dataset_version_id: "version-immutable-002",
  };
  const scopedKey = (prefix, identity) =>
    datasetIdentity.canonicalDatasetStorageKey(prefix, identity);

  localStorage.setItem(
    "modeling-tool-outlier-methods",
    JSON.stringify({ leaked_global_feature: "GLOBAL_LEAK" }),
  );
  localStorage.setItem(
    "modeling-tool-missing-config",
    JSON.stringify({ leakedGlobalMissing: true }),
  );
  localStorage.setItem("splitStrategy", "GLOBAL_SPLIT_LEAK");
  localStorage.setItem("balanceMethod", "GLOBAL_BALANCE_LEAK");
  localStorage.setItem(
    scopedKey("modeling-tool-outlier-methods", otherIdentity),
    JSON.stringify({ leaked_other_version: "OTHER_VERSION_LEAK" }),
  );
  localStorage.setItem(
    scopedKey("modeling-tool-missing-config", otherIdentity),
    JSON.stringify({ leakedOtherMissing: true }),
  );
  localStorage.setItem(
    scopedKey("modeling-tool-outlier-methods", IDENTITY),
    JSON.stringify({ risk_score: "IQR_1_5" }),
  );
  localStorage.setItem(
    scopedKey("modeling-tool-outlier-global-method", IDENTITY),
    "IQR_3_0",
  );
  localStorage.setItem(
    scopedKey("atlas:outlier-rationales", IDENTITY),
    JSON.stringify({ risk_score: "Exact-version rationale" }),
  );
  localStorage.setItem(
    scopedKey("modeling-tool-missing-config", IDENTITY),
    JSON.stringify({
      policyVersion: 2,
      globalStrategy: "Median",
      config: { risk_score: { strategy: "Median" } },
      overrideFeatures: [],
    }),
  );
  localStorage.setItem(
    scopedKey("atlas-validation-design-draft-v2", IDENTITY),
    JSON.stringify({
      holdoutSize: 0.2,
      randomSeed: 42,
      foldMethod: "stratified_k_fold",
      foldCount: 7,
      foldLocalPreprocessing: "fit_transform_per_fold",
      balanceMethod: "smote",
      minorityShare: 0.4,
      externalValidationMode: "oot",
      ootDatasetId: "dataset-oot",
      browserPartitionAuthority: "must-not-survive",
    }),
  );
  localStorage.setItem(
    scopedKey("modeling-tool-training-config", IDENTITY),
    JSON.stringify({ candidateStrategy: "balanced" }),
  );

  const state =
    preparation.loadCanonicalPreparationBrowserState(IDENTITY);
  assert.deepEqual(state.outlierMethods, { risk_score: "IQR_1_5" });
  assert.equal(state.outlierGlobalMethod, "IQR_3_0");
  assert.deepEqual(state.outlierRationales, {
    risk_score: "Exact-version rationale",
  });
  assert.equal(state.missingPolicy.globalStrategy, "Median");
  assert.equal(state.splitStrategy, "Requires exact Analysis Partition");
  assert.equal(state.balanceMethod, "smote");
  assert.equal(state.balanceRatio, "0.4");
  assert.equal(state.kFolds, "7");
  assert.deepEqual(state.validationDraft, {
    foldMethod: "stratified_k_fold",
    foldLocalPreprocessing: "fit_transform_per_fold",
    balanceMethod: "smote",
    externalValidationMode: "oot",
    ootDatasetId: "dataset-oot",
    foldCount: 7,
    minorityShare: 0.4,
  });
  assert.doesNotMatch(
    JSON.stringify(state.validationDraft),
    /holdoutSize|randomSeed|browserPartitionAuthority/,
  );
  assert.deepEqual(state.trainingConfig, {
    candidateStrategy: "balanced",
  });
  assert.doesNotMatch(JSON.stringify(state), /GLOBAL_LEAK|OTHER_VERSION_LEAK/);

  assert.throws(
    () =>
      preparation.loadCanonicalPreparationBrowserState({
        project_id: IDENTITY.project_id,
        dataset_id: IDENTITY.dataset_id,
      }),
    /dataset_version_id/,
  );

  localDataset.setLocalDataset({
    headers: ["risk_score", "bad_flag"],
    rows: [{ risk_score: 640, bad_flag: 0 }],
    target: "bad_flag",
    selected_columns: ["risk_score"],
    dataset_id: IDENTITY.dataset_id,
    dataset_version_id: IDENTITY.dataset_version_id,
    dataset_version: IDENTITY.dataset_version_id,
    dataset_library: {
      datasetId: IDENTITY.dataset_id,
      versionId: IDENTITY.dataset_version_id,
    },
  });
  const captured = await experiments.recordTrainingExperiments({
    apiBase: "http://127.0.0.1:8001/api",
    datasetIdentity: IDENTITY,
    trainingJobId: "training-job-preparation-001",
    ranked: [{ key: "logreg", name: "Logistic Regression", auc: 0.8 }],
    selectedModelKeys: ["logreg"],
    trainingSettings: { tuning: "quick" },
    runtimeMs: 200,
    calibrated: false,
  });
  assert.equal(captured[0].balancingMethod, "smote");
  assert.equal(
    captured[0].splitStrategy,
    "Requires exact Analysis Partition",
  );
  assert.doesNotMatch(
    JSON.stringify(captured[0].preprocessingSteps.validationDesign),
    /holdoutSize|randomSeed|browserPartitionAuthority/,
  );
  assert.equal(
    captured[0].preprocessingSteps.outlierGlobalMethod,
    "IQR_3_0",
  );
  assert.equal(
    captured[0].preprocessingSteps.missingStrategies.globalStrategy,
    "Median",
  );
  assert.doesNotMatch(
    JSON.stringify(captured[0].preprocessingSteps),
    /GLOBAL_LEAK|OTHER_VERSION_LEAK/,
  );
});

test("documentation sources select and render only canonical experiment identity", async () => {
  const [tracking, training, document, governance, notebook, documentPage] =
    await Promise.all([
      readFile(new URL("src/lib/experimentTracking.ts", ROOT), "utf8"),
      readFile(new URL("src/steps/Step06_Train.tsx", ROOT), "utf8"),
      readFile(new URL("src/lib/modelDevelopmentDocument.ts", ROOT), "utf8"),
      readFile(new URL("src/lib/governanceReport.ts", ROOT), "utf8"),
      readFile(new URL("src/lib/notebookExport.ts", ROOT), "utf8"),
      readFile(
        new URL("src/steps/Step11_ModelDevelopmentDocument.tsx", ROOT),
        "utf8",
      ),
    ]);

  assert.match(tracking, /project_id:\s*string/);
  assert.match(tracking, /dataset_id:\s*string/);
  assert.match(tracking, /dataset_version_id:\s*string/);
  assert.match(tracking, /requireLocalDatasetCanonicalIdentity/);
  assert.doesNotMatch(
    tracking,
    /datasetVersion:\s*`\$\{dataset\.target[\s\S]*dataset\.rows\.length/,
  );
  assert.match(training, /datasetIdentity,\s*\n\s*trainingJobId:\s*current\.job_id/);
  for (const source of [document, governance, notebook, documentPage]) {
    assert.match(source, /requireLocalDatasetCanonicalIdentity/);
    assert.match(source, /loadExperiments\(datasetIdentity|loadExperiments\(identity/);
  }
  for (const source of [tracking, document, governance, notebook]) {
    assert.match(source, /loadCanonicalPreparationBrowserState/);
  }
  for (const source of [document, governance, notebook]) {
    assert.doesNotMatch(source, /experiments\[0\]/);
    assert.doesNotMatch(
      source,
      /localStorage\.getItem\(["'](?:modeling-tool-(?:outlier-methods|missing-config)|splitStrategy|balanceMethod|balanceRatio|kFolds)/,
    );
  }
  assert.doesNotMatch(
    document,
    /resolveDocumentDatasetIdentity[\s\S]{0,500}catch\s*\{/,
  );
  assert.doesNotMatch(
    governance,
    /resolveGovernanceDatasetIdentity[\s\S]{0,500}catch\s*\{/,
  );
  assert.doesNotMatch(document, /startsWith\(expectedPrefix\)/);
  assert.doesNotMatch(document, /exact\.length\s*\?\s*exact\s*:\s*experiments/);
  assert.doesNotMatch(document, /champion\?\.datasetVersion/);
  assert.doesNotMatch(governance, /champion\.datasetVersion/);
  assert.match(notebook, /ANALYSIS_PARTITION_ASSIGNMENT_PATH/);
  assert.match(notebook, /EXACT_ANALYSIS_PARTITION_ASSIGNMENT\.json/);
  assert.match(notebook, /development_positions/);
  assert.match(notebook, /holdout_positions/);
  assert.match(notebook, /X_development = X\.iloc/);
  assert.match(notebook, /Final holdout rows \(sealed, not materialized\)/);
  assert.match(notebook, /DEVELOPMENT_VALIDATION_ASSIGNMENT_PATH/);
  assert.match(notebook, /EXACT_GOVERNED_DEVELOPMENT_VALIDATION_ASSIGNMENT\.json/);
  assert.match(notebook, /X_validation = X\.iloc/);
  assert.match(notebook, /sealed final holdout cannot be used for candidate ranking/i);
  assert.match(notebook, /Balancing status: planning only/);
  assert.doesNotMatch(notebook, /display\(y_train\.value_counts/);
  assert.doesNotMatch(
    notebook,
    /from sklearn\.model_selection import train_test_split/,
  );
  assert.doesNotMatch(notebook, /test_size\s*=\s*0\.20/);
  assert.doesNotMatch(notebook, /\bX_test\b|\by_test\b/);
  assert.doesNotMatch(
    notebook,
    /roc_auc_score\(y_test|predict(?:_proba)?\(X_test/,
  );
});

import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/workflow-navigation-state-tests", import.meta.url));

class MemoryStorage {
  constructor() {
    this.map = new Map();
  }
  get length() {
    return this.map.size;
  }
  clear() {
    this.map.clear();
  }
  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }
  key(index) {
    return Array.from(this.map.keys())[index] ?? null;
  }
  removeItem(key) {
    this.map.delete(key);
  }
  setItem(key, value) {
    this.map.set(String(key), String(value));
  }
}

globalThis.localStorage = new MemoryStorage();
globalThis.sessionStorage = new MemoryStorage();

async function transpileSource(sourcePath, outputPath) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  let output = ts.transpileModule(source, {
    compilerOptions: {
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  output = output.replace(/from\s+["'](\.{1,2}\/[^"']+)["']/g, (match, specifier) => {
    if (specifier.endsWith(".js") || specifier.endsWith(".json") || specifier.endsWith(".css")) return match;
    return match.replace(specifier, `${specifier}.js`);
  });
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, output, "utf8");
}

async function importLocalDatasetModule() {
  await rm(TMP_DIR, { recursive: true, force: true });
  // localDataset.ts's project/user scoping (Stage 6.2) pulls in two tiny
  // ambient-cache modules -- transpile them alongside it so the isolated
  // import graph resolves without dragging in the full zustand store/auth
  // API surface this lightweight harness doesn't set up.
  await transpileSource("src/lib/activeProjectContext.ts", path.join(TMP_DIR, "src/lib/activeProjectContext.js"));
  await transpileSource("src/lib/authSession.ts", path.join(TMP_DIR, "src/lib/authSession.js"));
  await transpileSource("src/lib/localDataset.ts", path.join(TMP_DIR, "src/lib/localDataset.js"));
  return import(pathToFileURL(path.join(TMP_DIR, "src/lib/localDataset.js")).href);
}

test("Data Acquisition selected columns rehydrate without excluded variables", async () => {
  const { saveLocalDataset, loadLocalDataset } = await importLocalDatasetModule();
  sessionStorage.clear();

  saveLocalDataset({
    headers: ["Time", "Class", "V1", "V2"],
    rows: [
      { Time: 1, Class: 0, V1: -0.1, V2: 0.2 },
      { Time: 2, Class: 1, V1: 0.5, V2: -0.3 },
    ],
    target: "Class",
    selected_columns: ["V1", "V2"],
    problem_type: "classification",
  });

  const restored = loadLocalDataset();
  assert.deepEqual(restored.headers, ["V1", "V2", "Class"]);
  assert.deepEqual(restored.selected_columns, ["V1", "V2"]);
  assert.equal(restored.headers.includes("Time"), false);
});

test("explicit empty feature selections stay empty instead of defaulting to all columns", async () => {
  const { saveLocalDataset, loadLocalDataset } = await importLocalDatasetModule();
  sessionStorage.clear();

  saveLocalDataset({
    headers: ["Time", "Class", "V1"],
    rows: [{ Time: 1, Class: 0, V1: -0.1 }],
    target: "Class",
    selected_columns: [],
    problem_type: "classification",
  });

  const restored = loadLocalDataset();
  assert.deepEqual(restored.headers, ["Class"]);
  assert.deepEqual(restored.selected_columns, []);
});

test("target and checkbox-style partial saves preserve canonical identity and subordinate metadata", async () => {
  const { saveLocalDataset, loadLocalDataset } = await importLocalDatasetModule();
  sessionStorage.clear();

  const accessMetadata = {
    accessMetadataId: "access-snapshot-1",
    accessSourceId: "source-snapshot-1",
    hash: "sha256-fixture",
    sourceType: "existing",
    sourceLabel: "Exact registered test version",
    samplingMethod: "full",
    samplingDetail: "All rows",
    importedAt: "2026-07-30T12:00:00.000Z",
    rows: 2,
    columns: 4,
    columnNames: ["V1", "V2", "Class", "Outcome"],
  };
  const qualityMetadata = {
    profileScope: "full_dataset",
    profiledRowCount: 2,
    registeredRowCount: 2,
    rowCount: 2,
    columnCount: 4,
    duplicateRows: 0,
    duplicateIdCandidates: [],
    constantColumns: [],
    nearZeroVarianceColumns: [],
    highCardinalityCategoricals: [],
    unexpectedDatatypeColumns: [],
    potentialLeakageColumns: [],
    outlierPrevalence: [],
    dateRanges: [],
    missing: [],
    memoryEstimateMb: 0.01,
  };
  saveLocalDataset({
    headers: ["V1", "V2", "Class", "Outcome"],
    rows: [
      { V1: 1, V2: 10, Class: 0, Outcome: 1 },
      { V1: 2, V2: 20, Class: 1, Outcome: 0 },
    ],
    target: "Class",
    selected_columns: ["V1", "V2", "Outcome"],
    problem_type: "classification",
    dataset_id: "dataset-exact",
    dataset_version_id: "version-exact",
    dataset_version: "version-exact",
    dataset_library: {
      datasetId: "dataset-exact",
      versionId: "version-exact",
      datasetName: "Exact fixture",
    },
    data_access: accessMetadata,
    data_quality: qualityMetadata,
  });

  const beforeTargetEdit = loadLocalDataset();
  saveLocalDataset({
    ...beforeTargetEdit,
    headers: ["V1", "V2", "Class", "Outcome"],
    rows: beforeTargetEdit.rows,
    target: "Outcome",
    selected_columns: ["V1", "V2", "Class"],
  });

  const afterTargetEdit = loadLocalDataset();
  assert.equal(afterTargetEdit.dataset_id, "dataset-exact");
  assert.equal(afterTargetEdit.dataset_version_id, "version-exact");
  assert.deepEqual(afterTargetEdit.data_access, accessMetadata);
  assert.deepEqual(afterTargetEdit.data_quality, qualityMetadata);

  saveLocalDataset({
    ...afterTargetEdit,
    selected_columns: ["V1", "Class"],
  });
  const afterCheckboxEdit = loadLocalDataset();
  assert.equal(afterCheckboxEdit.dataset_id, "dataset-exact");
  assert.equal(afterCheckboxEdit.dataset_version_id, "version-exact");
  assert.deepEqual(afterCheckboxEdit.data_access, accessMetadata);
  assert.deepEqual(afterCheckboxEdit.data_quality, qualityMetadata);
  assert.deepEqual(afterCheckboxEdit.selected_columns, ["V1", "Class"]);
});

test("workflow pages contain remount-safe state rehydration hooks", async () => {
  const [
    dataAcquisition,
    train,
    missing,
    featureEngineering,
    workflowPlaceholder,
  ] = await Promise.all([
    readFile(new URL("../src/steps/Step01_DataAcquisition.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/steps/Step06_Train.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/steps/Step04_MissingValues.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/steps/Step05_EncodingScaling.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/steps/WorkflowPlaceholderStep.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(dataAcquisition, /loadLocalDataset/);
  assert.match(dataAcquisition, /Restored the cached modeling dataset/);
  assert.match(train, /selected_map/);
  assert.match(train, /buildInitialSelected/);
  assert.match(train, /hasSavedSelectionForProblem/);
  assert.match(missing, /const CONFIG_KEY = "modeling-tool-missing-config"/);
  assert.match(
    missing,
    /localStorage\.getItem\(\s*canonicalDatasetStorageKey\(CONFIG_KEY,\s*datasetIdentity\)/,
  );
  assert.match(
    featureEngineering,
    /getFeatureManifest\(datasetIdentity\)/,
  );
  assert.match(featureEngineering, /setDrafts\(payload\.features\.filter/);
  // On navigation to a new step, the placeholder reloads that step's saved node state.
  assert.match(workflowPlaceholder, /const restored = loadNodeState\(projectId, step\.id\);/);
  assert.match(workflowPlaceholder, /setState\(restored\);/);
});

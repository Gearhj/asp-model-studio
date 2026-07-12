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
  assert.match(missing, /localStorage\.getItem\(MISSING_CONFIG_KEY\)/);
  assert.match(featureEngineering, /FEATURE_CONFIG_KEY/);
  // On navigation to a new step, the placeholder reloads that step's saved node state.
  assert.match(workflowPlaceholder, /const restored = loadNodeState\(projectId, step\.id\);/);
  assert.match(workflowPlaceholder, /setState\(restored\);/);
});

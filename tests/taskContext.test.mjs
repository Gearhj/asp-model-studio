// Visual Intelligence Foundation Phase 0: shared task-context resolver.
// Confirms backend training truth wins over the local dataset cache, and that
// an absent/errored backend answer falls back to the local cache honestly
// (never silently defaulting to "classification").
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/task-context-tests", import.meta.url));

class MemoryStorage {
  constructor() { this.map = new Map(); }
  get length() { return this.map.size; }
  clear() { this.map.clear(); }
  getItem(key) { return this.map.has(key) ? this.map.get(key) : null; }
  key(index) { return Array.from(this.map.keys())[index] ?? null; }
  removeItem(key) { this.map.delete(key); }
  setItem(key, value) { this.map.set(String(key), String(value)); }
}
globalThis.sessionStorage = new MemoryStorage();

async function transpileSource(sourcePath, outputPath) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  let output = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  output = output.replace(/from\s+["'](\.{1,2}\/[^"']+)["']/g, (match, specifier) => {
    if (specifier.endsWith(".js") || specifier.endsWith(".json") || specifier.endsWith(".css")) return match;
    return match.replace(specifier, `${specifier}.js`);
  });
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, output, "utf8");
}

async function loadModule() {
  await rm(TMP_DIR, { recursive: true, force: true });
  await transpileSource("src/lib/activeProjectContext.ts", path.join(TMP_DIR, "src/lib/activeProjectContext.js"));
  await transpileSource("src/lib/authSession.ts", path.join(TMP_DIR, "src/lib/authSession.js"));
  await transpileSource("src/lib/datasetIdentity.ts", path.join(TMP_DIR, "src/lib/datasetIdentity.js"));
  await transpileSource("src/lib/localDataset.ts", path.join(TMP_DIR, "src/lib/localDataset.js"));
  await transpileSource("src/lib/scopedTrainingHistory.ts", path.join(TMP_DIR, "src/lib/scopedTrainingHistory.js"));
  await transpileSource("src/lib/taskContext.ts", path.join(TMP_DIR, "src/lib/taskContext.js"));
  return import(pathToFileURL(path.join(TMP_DIR, "src/lib/taskContext.js")).href);
}

const mod = await loadModule();
const { deriveTaskContext } = mod;

test("backend regression truth wins even when the local dataset cache says classification", () => {
  const localDataset = { headers: ["Class", "V1"], rows: [{ Class: 0, V1: 1 }], target: "Class", selected_columns: ["V1"], problem_type: "classification" };
  const result = deriveTaskContext({ problem_type: "regression", target: "MedHouseVal" }, localDataset);
  assert.equal(result.problemType, "regression");
  assert.equal(result.target, "MedHouseVal");
  assert.equal(result.source, "backend-training");
});

test("uses explicit target-contract metadata when no backend training summary exists", () => {
  const localDataset = { headers: ["MedHouseVal", "AveRooms"], rows: Array.from({ length: 20 }, (_, i) => ({ MedHouseVal: i * 0.3, AveRooms: i })), target: "MedHouseVal", selected_columns: ["AveRooms"], problem_type: "regression" };
  const result = deriveTaskContext(null, localDataset);
  assert.equal(result.problemType, "regression");
  assert.equal(result.source, "target-contract-metadata");
});

test("returns null problemType (never defaults to classification) when nothing is known", () => {
  const result = deriveTaskContext(null, null);
  assert.equal(result.problemType, null);
  assert.equal(result.source, "unknown");
});

test("backend summary with an unrecognized problem_type uses explicit target-contract metadata instead", () => {
  const localDataset = { headers: ["MedHouseVal"], rows: Array.from({ length: 20 }, (_, i) => ({ MedHouseVal: i })), target: "MedHouseVal", selected_columns: [], problem_type: "regression" };
  const result = deriveTaskContext({ problem_type: "anomaly" }, localDataset);
  assert.equal(result.problemType, "regression");
  assert.equal(result.source, "target-contract-metadata");
});

test("browser target values never infer problem type without authoritative metadata", () => {
  const targetBearingRows = {
    headers: ["Class", "V1"],
    rows: [{ Class: 0, V1: 1 }, { Class: 1, V1: 2 }],
    target: "Class",
    selected_columns: ["V1"],
  };
  const result = deriveTaskContext(null, targetBearingRows);
  assert.equal(result.problemType, null);
  assert.equal(result.target, null);
  assert.equal(result.source, "unknown");
});

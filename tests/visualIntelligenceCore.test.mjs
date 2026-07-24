// Visual Intelligence Foundation Phase 1: unit tests for the pure-calculation
// modules (large-data policy, D3 overlay statistics, query result adapters).
// These do not require a browser -- they transpile the TS source directly,
// matching the pattern used by tests/browserDatasetState.test.mjs etc.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/visual-intelligence-core-tests", import.meta.url));

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

async function loadModules() {
  await rm(TMP_DIR, { recursive: true, force: true });
  await transpileSource("src/visual-intelligence/largeDataPolicy.ts", path.join(TMP_DIR, "src/visual-intelligence/largeDataPolicy.js"));
  await transpileSource("src/visual-intelligence/types.ts", path.join(TMP_DIR, "src/visual-intelligence/types.js"));
  await transpileSource("src/visual-intelligence/adapters/queryResultAdapter.ts", path.join(TMP_DIR, "src/visual-intelligence/adapters/queryResultAdapter.js"));
  return {
    largeDataPolicy: await import(pathToFileURL(path.join(TMP_DIR, "src/visual-intelligence/largeDataPolicy.js")).href),
    types: await import(pathToFileURL(path.join(TMP_DIR, "src/visual-intelligence/types.js")).href),
    adapter: await import(pathToFileURL(path.join(TMP_DIR, "src/visual-intelligence/adapters/queryResultAdapter.js")).href),
  };
}

const modules = await loadModules();

test("chooseRenderStrategy follows the documented thresholds", () => {
  const { chooseRenderStrategy } = modules.largeDataPolicy;
  assert.equal(chooseRenderStrategy(500), "direct-svg");
  assert.equal(chooseRenderStrategy(2000), "direct-svg");
  assert.equal(chooseRenderStrategy(2001), "canvas");
  assert.equal(chooseRenderStrategy(25000), "canvas");
  assert.equal(chooseRenderStrategy(25001), "aggregate");
  assert.equal(chooseRenderStrategy(100000), "aggregate");
  assert.equal(chooseRenderStrategy(100001), "server-query");
});

test("safeMinMax never spreads the array into Math.min/Math.max (works past the JS engine argument-count limit)", () => {
  const { safeMinMax } = modules.largeDataPolicy;
  const large = Array.from({ length: 200_000 }, (_, i) => (i % 7) - 3);
  const result = safeMinMax(large);
  assert.equal(result.min, -3);
  assert.equal(result.max, 3);
});

test("safeMinMax returns null for an empty array", () => {
  assert.equal(modules.largeDataPolicy.safeMinMax([]), null);
});

test("streamingMeanStd matches a naive two-pass computation", () => {
  const { streamingMeanStd } = modules.largeDataPolicy;
  const values = [2, 4, 4, 4, 5, 5, 7, 9];
  const result = streamingMeanStd(values);
  assert.ok(Math.abs(result.mean - 5) < 1e-9);
  assert.ok(Math.abs(result.std - 2.138089935) < 1e-6); // sample std (n-1 denominator)
  assert.equal(result.n, 8);
});

test("streamingMedian handles even and odd counts", () => {
  const { streamingMedian } = modules.largeDataPolicy;
  assert.equal(streamingMedian([1, 3, 2]), 2);
  assert.equal(streamingMedian([1, 2, 3, 4]), 2.5);
  assert.equal(streamingMedian([]), null);
});

test("reservoirSample preserves size and never exceeds source length", () => {
  const { reservoirSample } = modules.largeDataPolicy;
  const source = Array.from({ length: 10_000 }, (_, i) => i);
  const sample = reservoirSample(source, 500, () => 0.42);
  assert.equal(sample.length, 500);
  assert.ok(sample.every((v) => v >= 0 && v < 10_000));
  const smallSource = [1, 2, 3];
  assert.deepEqual(reservoirSample(smallSource, 10), [1, 2, 3]);
});

test("referencesMatch treats undefined fields as unasserted, not mismatched", () => {
  const { referencesMatch } = modules.types;
  const a = { authenticatedUserId: "u1", projectId: "p1", sourceType: "workspace" };
  const b = { authenticatedUserId: "u1", projectId: "p1", sourceType: "workspace", datasetId: "d1" };
  assert.equal(referencesMatch(a, b), true);
});

test("referencesMatch rejects a genuine project mismatch", () => {
  const { referencesMatch } = modules.types;
  const a = { authenticatedUserId: "u1", projectId: "p1", sourceType: "workspace" };
  const b = { authenticatedUserId: "u1", projectId: "p2", sourceType: "workspace" };
  assert.equal(referencesMatch(a, b), false);
});

test("adaptRegressionRows computes residual as actual - prediction and drops null rows", () => {
  const { adaptRegressionRows } = modules.adapter;
  const rows = adaptRegressionRows([1, 2, null, 4], [1.5, 1.5, 5, null]);
  assert.equal(rows.length, 2);
  assert.ok(Math.abs(rows[0].residual - (1 - 1.5)) < 1e-9);
  assert.ok(Math.abs(rows[1].residual - (2 - 1.5)) < 1e-9);
});

test("adaptClassificationRows preserves actual/predictedScore pairing and drops nulls", () => {
  const { adaptClassificationRows } = modules.adapter;
  const rows = adaptClassificationRows([1, 0, null], [0.9, 0.1, 0.5]);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].actual, 1);
  assert.equal(rows[0].predictedScore, 0.9);
});

test("acceptOrRejectContext rejects a mismatched project/model context", () => {
  const { acceptOrRejectContext } = modules.adapter;
  const expected = { authenticatedUserId: "u1", projectId: "p1", sourceType: "evaluation-result", modelId: "linreg" };
  const received = { authenticatedUserId: "u1", projectId: "p1", sourceType: "evaluation-result", modelId: "dt_reg" };
  const result = acceptOrRejectContext(expected, received);
  assert.equal(result.accepted, false);
});

test("assertProblemType throws when a regression view receives classification data", () => {
  const { assertProblemType } = modules.adapter;
  assert.throws(() => assertProblemType("regression", "classification", "RegressionDiagnosticExplorer"));
  assert.doesNotThrow(() => assertProblemType("regression", "regression", "RegressionDiagnosticExplorer"));
  assert.doesNotThrow(() => assertProblemType("regression", null, "RegressionDiagnosticExplorer"));
});

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const read = async (path) =>
  (await readFile(new URL(`../${path}`, import.meta.url), "utf8")).replace(
    /\r\n/g,
    "\n",
  );

const helperSource = await read(
  "src/components/eda/visual/predictorVisibleLimits.ts",
);
const landscapeSource = await read(
  "src/components/eda/visual/PredictorSignalLandscape.tsx",
);
const barrelSource = await read(
  "src/components/eda/visual/PredictorVisualSuite.tsx",
);

const transpiled = ts.transpileModule(helperSource, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2021,
  },
}).outputText;
const limits = await import(
  `data:text/javascript;base64,${Buffer.from(transpiled).toString("base64")}`
);

test("visible predictor choices expose every exact count", () => {
  assert.deepEqual(limits.buildPredictorVisibleLimitOptions(5), [1, 2, 3, 4, 5]);
  assert.deepEqual(
    limits.buildPredictorVisibleLimitOptions(12),
    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
  );
  assert.deepEqual(
    limits.buildPredictorVisibleLimitOptions(21),
    Array.from({ length: 21 }, (_unused, index) => index + 1),
  );
  assert.deepEqual(
    limits.buildPredictorVisibleLimitOptions(30),
    Array.from({ length: 30 }, (_unused, index) => index + 1),
  );
});

test("the hard ceiling remains bounded without duplicate labels", () => {
  assert.deepEqual(
    limits.buildPredictorVisibleLimitOptions(24),
    Array.from({ length: 24 }, (_unused, index) => index + 1),
  );
  assert.deepEqual(
    limits.buildPredictorVisibleLimitOptions(40),
    Array.from({ length: 40 }, (_unused, index) => index + 1),
  );
  assert.deepEqual(
    limits.buildPredictorVisibleLimitOptions(60),
    Array.from({ length: 60 }, (_unused, index) => index + 1),
  );
  assert.deepEqual(
    limits.buildPredictorVisibleLimitOptions(91),
    Array.from({ length: 60 }, (_unused, index) => index + 1),
  );
  for (const count of [1, 5, 12, 21, 24, 30, 40, 60, 91]) {
    const options = limits.buildPredictorVisibleLimitOptions(count);
    assert.equal(new Set(options).size, options.length);
    assert.deepEqual(options, [...options].sort((left, right) => left - right));
  }
});

test("default and restored selections resolve to a real option", () => {
  assert.equal(limits.resolvePredictorVisibleLimit(undefined, 5), 5);
  assert.equal(limits.resolvePredictorVisibleLimit(undefined, 12), 12);
  assert.equal(limits.resolvePredictorVisibleLimit(undefined, 21), 21);
  assert.equal(limits.resolvePredictorVisibleLimit(undefined, 30), 24);
  assert.equal(limits.resolvePredictorVisibleLimit(30, 30), 30);
  assert.equal(limits.resolvePredictorVisibleLimit(60, 30), 30);
  assert.equal(limits.resolvePredictorVisibleLimit(21, 30), 21);
});

test("visible predictor preference persists within dataset and target identity", () => {
  const memory = new Map();
  const storage = {
    getItem(key) {
      return memory.get(key) ?? null;
    },
    setItem(key, value) {
      memory.set(key, value);
    },
  };
  const key = limits.predictorVisibleLimitStorageKey(
    "heloc-v1",
    "bad_flag",
  );
  assert.equal(
    limits.predictorVisibleLimitStorageKey("heloc-v1", "bad_flag"),
    key,
  );
  assert.notEqual(
    limits.predictorVisibleLimitStorageKey("heloc-v2", "bad_flag"),
    key,
  );
  assert.equal(limits.persistPredictorVisibleLimit(storage, key, 21), true);
  assert.equal(
    limits.loadPersistedPredictorVisibleLimit(storage, key, 21),
    21,
  );
  assert.equal(
    limits.loadPersistedPredictorVisibleLimit(storage, key, 30),
    21,
  );
});

test("landscape consumes the exported helper and stores only user changes", () => {
  for (const marker of [
    "buildPredictorVisibleLimitOptions",
    "loadPersistedPredictorVisibleLimit",
    "persistPredictorVisibleLimit",
    "predictorVisibleLimitStorageKey",
    'data-testid="predictor-visible-limit"',
    "data-option-count",
    "visibleLimitOptions.map",
    "data-feature={row.feature}",
    'data-selected={isSelected ? "true" : "false"}',
  ]) {
    assert.match(
      landscapeSource,
      new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
    );
  }
  assert.doesNotMatch(
    landscapeSource,
    /\{\[12,\s*24,\s*40,\s*60\]\.map/,
  );
  assert.match(barrelSource, /buildPredictorVisibleLimitOptions/);
});

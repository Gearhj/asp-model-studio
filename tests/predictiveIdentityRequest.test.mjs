import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import test, { after } from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TEMP = await mkdtemp(path.join(tmpdir(), "atlas-identity-request-"));

after(async () => {
  await rm(TEMP, { recursive: true, force: true });
});

const source = await readFile(
  new URL("src/lib/predictiveIdentityRequest.ts", ROOT),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const modulePath = path.join(TEMP, "predictiveIdentityRequest.mjs");
await writeFile(modulePath, compiled, "utf8");
const { settlePredictiveIdentityRequest } = await import(pathToFileURL(modulePath).href);

test("cleanup abort during dataset restore is consumed without an unhandled rejection", async () => {
  const controller = new AbortController();
  const unhandled = [];
  const onUnhandled = (error) => unhandled.push(error);
  process.on("unhandledRejection", onUnhandled);
  try {
    let publishCount = 0;
    const settled = settlePredictiveIdentityRequest(
      () => new Promise((_resolve, reject) => {
        controller.signal.addEventListener("abort", () => {
          reject(new DOMException("signal is aborted without reason", "AbortError"));
        }, { once: true });
      }),
      {
        signal: controller.signal,
        generation: 7,
        currentGeneration: () => 7,
      },
      () => { publishCount += 1; },
    );

    controller.abort();
    assert.equal(await settled, "cancelled");
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(publishCount, 0);
    assert.deepEqual(unhandled, []);
  } finally {
    process.off("unhandledRejection", onUnhandled);
  }
});

test("a superseded generation cannot publish a failure state", async () => {
  const controller = new AbortController();
  let currentGeneration = 11;
  let rejectRestore;
  const published = [];
  const settled = settlePredictiveIdentityRequest(
    () => new Promise((_resolve, reject) => { rejectRestore = reject; }),
    {
      signal: controller.signal,
      generation: 11,
      currentGeneration: () => currentGeneration,
    },
    (error) => published.push(error),
  );

  currentGeneration = 12;
  rejectRestore(new Error("the superseded request failed late"));
  assert.equal(await settled, "cancelled");
  assert.deepEqual(published, []);
});

test("a genuine error from the active request remains fail-closed and visible", async () => {
  const controller = new AbortController();
  const failure = new TypeError("active restore network failure");
  const published = [];
  const result = await settlePredictiveIdentityRequest(
    async () => { throw failure; },
    {
      signal: controller.signal,
      generation: 19,
      currentGeneration: () => 19,
    },
    (error) => published.push(error),
  );

  assert.equal(result, "failed");
  assert.deepEqual(published, [failure]);
});

test("an AbortError from a still-active request is not mistaken for cleanup", async () => {
  const controller = new AbortController();
  const failure = new DOMException("upstream aborted unexpectedly", "AbortError");
  const published = [];
  const result = await settlePredictiveIdentityRequest(
    async () => { throw failure; },
    {
      signal: controller.signal,
      generation: 23,
      currentGeneration: () => 23,
    },
    (error) => published.push(error),
  );

  assert.equal(controller.signal.aborted, false);
  assert.equal(result, "failed");
  assert.deepEqual(published, [failure]);
});

test("the provider uses the settlement guard and does not rethrow cleanup aborts", async () => {
  const provider = await readFile(
    new URL("src/components/PredictiveIdentityProvider.tsx", ROOT),
    "utf8",
  );
  assert.match(provider, /void settlePredictiveIdentityRequest\(async \(\) =>/);
  assert.doesNotMatch(provider, /if \(controller\.signal\.aborted\) throw error/);
  assert.match(provider, /currentGeneration: \(\) => requestGeneration\.current/);
  assert.match(provider, /const failed = projectFailure\(routeProjectId, error, "identity"\)/);
});

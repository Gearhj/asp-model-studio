// Target Distribution client contract: request de-duplication, immutable-result
// caching, and identity keying. These are the mechanisms that stop React
// re-renders and dependency churn from issuing duplicate analytical queries.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/target-distribution-tests", import.meta.url));

async function compile() {
  await rm(TMP_DIR, { recursive: true, force: true });
  const source = await readFile(new URL("src/lib/targetDistributionApi.ts", ROOT), "utf8");
  // `import.meta.env` is Vite-specific; neutralize it for the Node test runtime.
  const patched = source.replace(/import\.meta\.env\?\.\w+ as string \| undefined/g, "undefined");
  const output = ts.transpileModule(patched, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const outPath = path.join(TMP_DIR, "targetDistributionApi.js");
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, output, "utf8");
  return import(pathToFileURL(outPath).href);
}

const api = await compile();

async function compileLifecycle() {
  const source = await readFile(new URL("src/lib/dataAcquisitionLifecycle.ts", ROOT), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const outPath = path.join(TMP_DIR, "dataAcquisitionLifecycle.js");
  await writeFile(outPath, output, "utf8");
  return import(pathToFileURL(outPath).href);
}

const lifecycle = await compileLifecycle();

const BASE_REQUEST = {
  projectId: "proj-1",
  datasetId: "ds-class-train",
  versionId: "v-1",
  target: "Class",
  eventValue: 1,
  nonEventValue: 0,
};

function stubFetch({ delayMs = 0, payload = null, fail = false } = {}) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) });
    if (delayMs) await new Promise((resolve) => setTimeout(resolve, delayMs));
    if (fail) return { ok: false, json: async () => ({ detail: "boom" }) };
    return {
      ok: true,
      json: async () => payload ?? {
        ok: true, supported: true, resolution: "exact", datasetId: BASE_REQUEST.datasetId,
        versionId: BASE_REQUEST.versionId, target: BASE_REQUEST.target,
        classDistribution: [
          { value: "0", count: 170524, percent: 0.9978933 },
          { value: "1", count: 360, percent: 0.0021067 },
        ],
        totalRowCount: 170884, cached: false, durationMs: 120,
      },
    };
  };
  return calls;
}

test.beforeEach(() => api.clearTargetDistributionCache());

test("the request key is the full immutable identity of the aggregate", () => {
  const base = api.buildTargetDistributionKey(BASE_REQUEST);
  assert.equal(base, api.buildTargetDistributionKey({ ...BASE_REQUEST }));

  for (const change of [
    { projectId: "proj-2" },
    { datasetId: "ds-other" },
    { versionId: "v-2" },
    { target: "Amount" },
    { eventValue: 2 },
    { nonEventValue: 9 },
    { forceExact: true },
  ]) {
    assert.notEqual(
      api.buildTargetDistributionKey({ ...BASE_REQUEST, ...change }),
      base,
      `changing ${Object.keys(change)[0]} must produce a different identity`
    );
  }
});

// 4 -- duplicate renders do not issue duplicate active queries.
test("concurrent identical requests share a single in-flight query", async () => {
  const calls = stubFetch({ delayMs: 30 });
  const results = await Promise.all([
    api.fetchTargetDistribution(BASE_REQUEST),
    api.fetchTargetDistribution({ ...BASE_REQUEST }),
    api.fetchTargetDistribution({ ...BASE_REQUEST }),
    api.fetchTargetDistribution({ ...BASE_REQUEST }),
  ]);
  assert.equal(calls.length, 1, "four identical concurrent requests must issue one network call");
  for (const result of results) assert.equal(result.totalRowCount, 170884);
});

test("StrictMode cleanup cancels only its caller; the remount exits loading and renders the governed distribution", async () => {
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    await gate;
    return {
      ok: true,
      json: async () => ({
        ok: true,
        supported: true,
        resolution: "exact",
        datasetId: BASE_REQUEST.datasetId,
        versionId: BASE_REQUEST.versionId,
        target: BASE_REQUEST.target,
        classDistribution: [
          { value: "0", count: 750, percent: 0.75 },
          { value: "1", count: 250, percent: 0.25 },
        ],
        totalRowCount: 1000,
        cached: false,
        durationMs: 12,
      }),
    };
  };

  let panelState = "loading";
  const firstMount = new AbortController();
  const firstWait = api.fetchTargetDistribution(BASE_REQUEST, { signal: firstMount.signal });
  const remountWait = api.fetchTargetDistribution({ ...BASE_REQUEST });

  // React StrictMode cleans up the first effect immediately. That cleanup must
  // not own or abort the de-duplicated fetch the remount has joined.
  firstMount.abort();
  await assert.rejects(firstWait, (error) => error?.name === "AbortError");
  assert.equal(panelState, "loading");
  assert.equal(calls.length, 1, "StrictMode remount must join one governed aggregate");
  assert.equal(calls[0].init.signal, undefined, "no caller signal may own the shared network request");

  release();
  const result = await remountWait;
  const rendered = lifecycle.buildTargetDistribution({
    target: result.target,
    classDistribution: result.classDistribution,
    eventValue: BASE_REQUEST.eventValue,
    nonEventValue: BASE_REQUEST.nonEventValue,
  });
  panelState = rendered ? "ready" : "empty";

  assert.equal(panelState, "ready", "the remounted panel must leave loading");
  assert.equal(rendered.totalRows, 1000);
  assert.equal(rendered.eventCount, 250);
  assert.equal(rendered.nonEventCount, 750);
  assert.equal(rendered.eventPercent, 0.25);
  assert.equal(rendered.nonEventPercent, 0.75);
});

// 5 -- cache is used for the same immutable version and target.
test("a resolved immutable aggregate is served from cache without refetching", async () => {
  const calls = stubFetch();
  await api.fetchTargetDistribution(BASE_REQUEST);
  assert.equal(calls.length, 1);

  const cached = api.peekCachedTargetDistribution(BASE_REQUEST);
  assert.ok(cached, "the resolved result should be cached");
  assert.equal(cached.totalRowCount, 170884);

  await api.fetchTargetDistribution({ ...BASE_REQUEST });
  await api.fetchTargetDistribution({ ...BASE_REQUEST });
  assert.equal(calls.length, 1, "repeat requests for the same identity must not hit the network");
});

// 6 / 7 -- changing target or version invalidates the prior result.
test("changing the target or the version misses the cache and refetches", async () => {
  const calls = stubFetch();
  await api.fetchTargetDistribution(BASE_REQUEST);
  assert.equal(calls.length, 1);

  assert.equal(api.peekCachedTargetDistribution({ ...BASE_REQUEST, target: "Amount" }), null);
  await api.fetchTargetDistribution({ ...BASE_REQUEST, target: "Amount" });
  assert.equal(calls.length, 2);

  assert.equal(api.peekCachedTargetDistribution({ ...BASE_REQUEST, versionId: "v-2" }), null);
  await api.fetchTargetDistribution({ ...BASE_REQUEST, versionId: "v-2" });
  assert.equal(calls.length, 3);
});

// 13 -- a different project can never read another project's cached aggregate.
test("a different project never reads the prior project's cached aggregate", async () => {
  const calls = stubFetch();
  await api.fetchTargetDistribution(BASE_REQUEST);
  assert.equal(api.peekCachedTargetDistribution({ ...BASE_REQUEST, projectId: "proj-2" }), null);
  await api.fetchTargetDistribution({ ...BASE_REQUEST, projectId: "proj-2" });
  assert.equal(calls.length, 2);
});

// 2 -- only bounded aggregate rows are consumed.
test("the client only ever receives bounded aggregate rows", async () => {
  stubFetch();
  const result = await api.fetchTargetDistribution(BASE_REQUEST);
  assert.equal(result.classDistribution.length, 2);
  for (const row of result.classDistribution) {
    assert.deepEqual(Object.keys(row).sort(), ["count", "percent", "value"]);
  }
  assert.ok(!("rows" in result), "no raw rows may be returned to the browser");
  assert.ok(JSON.stringify(result).length < 2000, "aggregate payload must stay small");
});

// 8 -- rare-event proportions survive the round trip intact.
test("the rare-event proportion is preserved exactly", async () => {
  stubFetch();
  const result = await api.fetchTargetDistribution(BASE_REQUEST);
  const event = result.classDistribution.find((row) => row.value === "1");
  assert.equal(event.count, 360);
  assert.ok(event.percent > 0 && event.percent < 0.01);
  assert.equal(Math.round(event.percent * 1e7) / 1e7, 0.0021067);
});

// 12 -- failures reject so the caller can present a retry.
test("a failed query rejects with the server detail and is not cached", async () => {
  const calls = stubFetch({ fail: true });
  await assert.rejects(() => api.fetchTargetDistribution(BASE_REQUEST), /boom/);
  assert.equal(api.peekCachedTargetDistribution(BASE_REQUEST), null, "a failure must not be cached");

  // A retry issues a fresh call rather than replaying the failure.
  stubFetch();
  const result = await api.fetchTargetDistribution(BASE_REQUEST);
  assert.equal(result.totalRowCount, 170884);
  assert.equal(calls.length, 1);
});

test("the forceExact flag is sent to the server and keyed separately", async () => {
  const calls = stubFetch();
  await api.fetchTargetDistribution(BASE_REQUEST);
  await api.fetchTargetDistribution({ ...BASE_REQUEST, forceExact: true });
  assert.equal(calls.length, 2, "an exact recalculation must not reuse the sampled entry");
  assert.equal(calls[0].body.forceExact, false);
  assert.equal(calls[1].body.forceExact, true);
});

test("the request body carries the exact immutable identity", async () => {
  const calls = stubFetch();
  await api.fetchTargetDistribution(BASE_REQUEST);
  assert.deepEqual(calls[0].body, {
    projectId: "proj-1", datasetId: "ds-class-train", versionId: "v-1",
    target: "Class", eventValue: 1, nonEventValue: 0, forceExact: false,
  });
  assert.match(calls[0].url, /\/analytics\/target-distribution$/);
});

import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import test, { after } from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TEMP = await mkdtemp(path.join(tmpdir(), "atlas-predictive-identity-"));

async function transpile(sourcePath, outputName) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
      importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
    },
  }).outputText.replace(
    /from\s+["']\.\/datasetIdentity["'];/g,
    'from "./datasetIdentity.mjs";',
  );
  const target = path.join(TEMP, outputName);
  await writeFile(target, compiled, "utf8");
  return target;
}

after(async () => {
  await rm(TEMP, { recursive: true, force: true });
});

await transpile("src/lib/datasetIdentity.ts", "datasetIdentity.mjs");
const readinessPath = await transpile(
  "src/lib/predictiveIdentityReadiness.ts",
  "predictiveIdentityReadiness.mjs",
);
const trainingPath = await transpile(
  "src/lib/scopedTrainingHistory.ts",
  "scopedTrainingHistory.mjs",
);
const readiness = await import(pathToFileURL(readinessPath).href);
const training = await import(pathToFileURL(trainingPath).href);

const EXACT = {
  project_id: "atlas-heloc",
  dataset_id: "ds-heloc",
  dataset_version_id: "v-registered-1",
};

function classify(overrides = {}) {
  return readiness.classifyPredictiveIdentity({
    projectId: EXACT.project_id,
    hasDataset: true,
    persistedIdentity: EXACT,
    activeProbe: { kind: "ready", identity: EXACT },
    localProbe: { kind: "exact", identity: EXACT },
    ...overrides,
  });
}

test("canonical route readiness exposes one explicit nine-state contract", () => {
  assert.deepEqual(readiness.PREDICTIVE_IDENTITY_STATUSES, [
    "idle",
    "loading",
    "ready",
    "missing",
    "stale",
    "legacy_unresolved",
    "contradictory",
    "unauthorized",
    "error",
  ]);
});

test("exact persisted, backend, and browser identities are ready", () => {
  const result = classify();
  assert.equal(result.status, "ready");
  assert.deepEqual(result.identity, EXACT);
});

test("an absent browser sample may be rehydrated only after exact backend verification", () => {
  const result = classify({ localProbe: { kind: "missing" } });
  assert.equal(result.status, "ready");
  assert.deepEqual(result.identity, EXACT);
});

test("a project with no selected dataset reports missing", () => {
  const result = classify({
    hasDataset: false,
    persistedIdentity: null,
    localProbe: { kind: "missing" },
    activeProbe: { kind: "http_error", status: 409 },
  });
  assert.equal(result.status, "missing");
  assert.equal(result.identity, null);
});

test("hasDataset without a canonical triple is legacy_unresolved", () => {
  const result = classify({
    persistedIdentity: null,
    localProbe: { kind: "missing" },
    activeProbe: { kind: "http_error", status: 409 },
  });
  assert.equal(result.status, "legacy_unresolved");
  assert.match(result.message, /will not choose/i);
});

test("legacy pseudo-version evidence is not promoted", () => {
  const result = classify({
    persistedIdentity: { project_id: EXACT.project_id, dataset_id: EXACT.dataset_id, dataset_version: "20260729-hash" },
    activeProbe: { kind: "http_error", status: 409 },
  });
  assert.equal(result.status, "legacy_unresolved");
  assert.equal(result.identity, null);
});

test("an exact persisted triple with no active backend scope is stale", () => {
  const result = classify({ activeProbe: { kind: "http_error", status: 409 } });
  assert.equal(result.status, "stale");
});

test("dataset disagreement between workflow and backend fails closed", () => {
  const result = classify({
    activeProbe: { kind: "ready", identity: { ...EXACT, dataset_id: "ds-other" } },
  });
  assert.equal(result.status, "contradictory");
  assert.equal(result.identity, null);
});

test("version disagreement between workflow and backend fails closed", () => {
  const result = classify({
    activeProbe: { kind: "ready", identity: { ...EXACT, dataset_version_id: "v-other" } },
  });
  assert.equal(result.status, "contradictory");
});

test("a cross-project active identity is rejected", () => {
  const result = classify({
    activeProbe: { kind: "ready", identity: { ...EXACT, project_id: "atlas-other" } },
  });
  assert.equal(result.status, "contradictory");
});

test("a conflicting browser dataset is rejected", () => {
  const result = classify({
    localProbe: { kind: "exact", identity: { ...EXACT, dataset_version_id: "v-browser-other" } },
  });
  assert.equal(result.status, "contradictory");
});

test("legacy browser state remains legacy_unresolved", () => {
  assert.equal(classify({ localProbe: { kind: "legacy_unresolved" } }).status, "legacy_unresolved");
});

test("401 and 403 remain authorization states rather than missing identity", () => {
  const unauthenticated = classify({ activeProbe: { kind: "http_error", status: 401 } });
  const forbidden = classify({ activeProbe: { kind: "http_error", status: 403 } });
  assert.equal(unauthenticated.status, "unauthorized");
  assert.equal(unauthenticated.httpStatus, 401);
  assert.equal(forbidden.status, "unauthorized");
  assert.equal(forbidden.httpStatus, 403);
});

test("network and unexpected HTTP failures remain errors", () => {
  assert.equal(classify({ activeProbe: { kind: "network_error" } }).status, "error");
  const serverError = classify({ activeProbe: { kind: "http_error", status: 500 } });
  assert.equal(serverError.status, "error");
  assert.equal(serverError.httpStatus, 500);
});

test("blank project scope is idle", () => {
  assert.equal(classify({ projectId: "" }).status, "idle");
});

test("an incomplete active backend response is contradictory", () => {
  assert.equal(classify({ activeProbe: { kind: "ready", identity: { project_id: EXACT.project_id } } }).status, "contradictory");
});

test("backend-active but workflow-versionless projects do not become ready", () => {
  const legacy = classify({ persistedIdentity: null });
  const contradiction = classify({ persistedIdentity: null, hasDataset: false });
  assert.equal(legacy.status, "legacy_unresolved");
  assert.equal(contradiction.status, "contradictory");
});

function response(status, payload) {
  return {
    status,
    ok: status >= 200 && status < 300,
    async json() { return payload; },
  };
}

test("training history refuses to call fetch before all canonical identifiers resolve", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return response(200, { ok: true, summary: {} });
  };
  await assert.rejects(
    training.requestScopedTrainingHistory({ project_id: EXACT.project_id }),
    /dataset_id/,
  );
  assert.equal(calls, 0);
});

test("training history sends the exact project, dataset, and version", async () => {
  let requestedUrl = "";
  globalThis.fetch = async (url) => {
    requestedUrl = String(url);
    return response(200, { ok: true, summary: { ranked: [{ key: "candidate-1" }] } });
  };
  const result = await training.requestScopedTrainingHistory(EXACT);
  const url = new URL(requestedUrl);
  assert.equal(url.pathname, "/api/train/last");
  assert.equal(url.searchParams.get("project_id"), EXACT.project_id);
  assert.equal(url.searchParams.get("dataset_id"), EXACT.dataset_id);
  assert.equal(url.searchParams.get("dataset_version_id"), EXACT.dataset_version_id);
  assert.equal(result.status, "success");
});

test("no prior training is an empty state for both 404 and null summary", async () => {
  globalThis.fetch = async () => response(404, { detail: "not found" });
  assert.equal((await training.requestScopedTrainingHistory(EXACT)).status, "empty");
  globalThis.fetch = async () => response(200, { ok: true, summary: null });
  assert.equal((await training.requestScopedTrainingHistory(EXACT)).status, "empty");
});

test("training history distinguishes 401, 403, 409, 422, and network errors", async () => {
  for (const [httpStatus, expected] of [[401, "unauthenticated"], [403, "unauthorized"], [409, "stale"], [422, "invalid"]]) {
    globalThis.fetch = async () => response(httpStatus, {});
    const result = await training.requestScopedTrainingHistory(EXACT);
    assert.equal(result.status, expected);
    assert.equal(result.httpStatus, httpStatus);
  }
  globalThis.fetch = async () => { throw new TypeError("network unavailable"); };
  assert.equal((await training.requestScopedTrainingHistory(EXACT)).status, "network_error");
});

test("an aborted history request is reported separately", async () => {
  const controller = new AbortController();
  globalThis.fetch = async (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
  });
  const pending = training.requestScopedTrainingHistory(EXACT, controller.signal);
  controller.abort();
  assert.equal((await pending).status, "aborted");
});

test("frontend wiring keeps identity-dependent rendering and notebook construction lazy", async () => {
  const [provider, panel, notebook, app, shell, atlas, copilot, persistence, projectPages, step01] = await Promise.all([
    readFile(new URL("src/components/PredictiveIdentityProvider.tsx", ROOT), "utf8"),
    readFile(new URL("src/components/StepPythonPanel.tsx", ROOT), "utf8"),
    readFile(new URL("src/lib/notebookExport.ts", ROOT), "utf8"),
    readFile(new URL("src/apps/ModelingApp.tsx", ROOT), "utf8"),
    readFile(new URL("src/components/StepShell.tsx", ROOT), "utf8"),
    readFile(new URL("src/AtlasApp.tsx", ROOT), "utf8"),
    readFile(new URL("src/components/CopilotCard.tsx", ROOT), "utf8"),
    readFile(new URL("src/lib/serverPersistence.ts", ROOT), "utf8"),
    readFile(new URL("src/steps/ProjectUtilityPages.tsx", ROOT), "utf8"),
    readFile(new URL("src/steps/Step01_DataAcquisition.tsx", ROOT), "utf8"),
  ]);

  assert.match(provider, /status:\s*"loading"/);
  assert.match(provider, /requestGeneration\.current/);
  assert.match(provider, /controller\.abort\(\)/);
  assert.match(provider, /readiness\.status === "ready"/);
  assert.doesNotMatch(provider, /latestVersion|links\[0\]|versions\[0\]/);
  assert.match(panel, /!supportsRoute \|\| !expanded \|\| readiness\.status !== "ready"/);
  assert.match(panel, /const workflowRoute = normalizeWorkflowRoute\(location\.pathname\)/);
  assert.match(panel, /getNotebookSectionsForRoute\(workflowRoute\)/);
  assert.match(panel, /error instanceof DatasetIdentityError/);
  assert.match(panel, /step-python-panel-identity-disabled/);
  assert.match(notebook, /requireLocalDatasetCanonicalIdentity/);
  assert.match(notebook, /getNotebookSectionsForRoute/);
  assert.match(app, /<PredictiveIdentityGate>/);
  assert.match(app, /resetKey=\{`\$\{projectId\}:\$\{location\.pathname\}`\}/);
  assert.match(shell, /step-python-panel-safe-fallback/);
  assert.match(atlas, /<ErrorBoundary/);
  assert.match(copilot, /requestScopedTrainingHistory<TrainingSummary>/);
  assert.doesNotMatch(copilot, /fetch\(`\$\{API_BASE\}\/train\/last/);
  assert.match(persistence, /datasetIdentity:\s*snapshot\.datasetIdentity \?\? null/);
  assert.match(projectPages, /workflowStatus\?\.datasetIdentity \?\? null/);
  assert.match(step01, /if \(!workflowDatasetIdentity\) return;/);
  assert.match(step01, /resolveExactReopenDatasetIdentity\(workflowDatasetIdentity, \[localIdentity\]\)/);
  assert.match(step01, /no verified Dataset Library binding/);
  assert.match(step01, /setWorkflowDatasetIdentity\(canonical\)/);
});

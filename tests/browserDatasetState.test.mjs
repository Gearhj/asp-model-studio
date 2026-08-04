// Predictive Modeling Repair Stage 6.2: project-scoped browser dataset state.
// Exercises src/lib/localDataset.ts's scoped storage contract directly
// (buildProjectDatasetStorageKey / loadProjectDataset / saveProjectDataset /
// clearProjectDataset / clearUserDatasetState / clearLegacyUnscopedDatasetState)
// plus the ambient loadLocalDataset()/saveLocalDataset() wrappers that resolve
// the active (userId, projectId) via src/lib/authSession.ts and
// src/lib/activeProjectContext.ts.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/browser-dataset-state-tests", import.meta.url));

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

async function loadModules() {
  await rm(TMP_DIR, { recursive: true, force: true });
  await transpileSource("src/lib/activeProjectContext.ts", path.join(TMP_DIR, "src/lib/activeProjectContext.js"));
  await transpileSource("src/lib/authSession.ts", path.join(TMP_DIR, "src/lib/authSession.js"));
  await transpileSource("src/lib/localDataset.ts", path.join(TMP_DIR, "src/lib/localDataset.js"));
  return {
    dataset: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/localDataset.js")).href),
    activeProject: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/activeProjectContext.js")).href),
    authSession: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/authSession.js")).href),
  };
}

const modules = await loadModules();
const { buildProjectDatasetStorageKey, loadProjectDataset, saveProjectDataset, clearProjectDataset, clearUserDatasetState, clearLegacyUnscopedDatasetState, loadLocalDataset, saveLocalDataset } = modules.dataset;
const { setCachedProjectId } = modules.activeProject;
const { setCachedUserId } = modules.authSession;

function makeDataset(overrides = {}) {
  return {
    headers: ["Class", "V1", "V2"],
    rows: [{ Class: 0, V1: 0.1, V2: -0.2 }],
    target: "Class",
    selected_columns: ["V1", "V2"],
    problem_type: "classification",
    ...overrides,
  };
}

test("buildProjectDatasetStorageKey never uses project name, dataset name, or filename", () => {
  const key = buildProjectDatasetStorageKey("user-a", "project-1");
  assert.equal(key, "atlas:modeling-dataset:user-a:project-1");
});

test("a project only loads the browser snapshot created for the same user and project id", () => {
  sessionStorage.clear();
  saveProjectDataset("user-a", "project-A", makeDataset({ headers: ["Class", "V1"], selected_columns: ["V1"] }));
  saveProjectDataset("user-a", "project-B", makeDataset({ headers: ["MedHouseVal", "AveRooms"], target: "MedHouseVal", selected_columns: ["AveRooms"], problem_type: "regression" }));

  const projectA = loadProjectDataset("user-a", "project-A");
  const projectB = loadProjectDataset("user-a", "project-B");
  assert.equal(projectA.target, "Class");
  assert.equal(projectB.target, "MedHouseVal");
  assert.notDeepEqual(projectA.headers, projectB.headers);
});

test("switching projects shows an honest empty state, not a stale project's rows", () => {
  sessionStorage.clear();
  saveProjectDataset("user-a", "project-A", makeDataset());
  const freshProject = loadProjectDataset("user-a", "project-C");
  assert.equal(freshProject, null);
});

test("returning to a previously scoped project restores its own state", () => {
  sessionStorage.clear();
  saveProjectDataset("user-a", "project-A", makeDataset({ dataset_version: "v1" }));
  saveProjectDataset("user-a", "project-B", makeDataset({ target: "MedHouseVal", headers: ["MedHouseVal"], selected_columns: [], problem_type: "regression" }));
  const restoredA = loadProjectDataset("user-a", "project-A");
  assert.equal(restoredA.dataset_version, "v1");
  assert.equal(restoredA.target, "Class");
});

test("two users on the same project id do not share browser cache", () => {
  sessionStorage.clear();
  saveProjectDataset("user-a", "shared-project", makeDataset({ dataset_version: "user-a-version" }));
  saveProjectDataset("user-b", "shared-project", makeDataset({ dataset_version: "user-b-version", target: "MedHouseVal", headers: ["MedHouseVal"], selected_columns: [], problem_type: "regression" }));
  assert.equal(loadProjectDataset("user-a", "shared-project").dataset_version, "user-a-version");
  assert.equal(loadProjectDataset("user-b", "shared-project").dataset_version, "user-b-version");
});

test("same filename/dataset name in two projects does not collide (key is id-based, not name-based)", () => {
  sessionStorage.clear();
  saveProjectDataset("user-a", "project-1", makeDataset({ dataset_library: { datasetId: "ds-1", versionId: "v1", datasetName: "CLASS_TRAIN.csv" } }));
  saveProjectDataset("user-a", "project-2", makeDataset({ dataset_library: { datasetId: "ds-2", versionId: "v9", datasetName: "CLASS_TRAIN.csv" } }));
  assert.equal(loadProjectDataset("user-a", "project-1").dataset_library.datasetId, "ds-1");
  assert.equal(loadProjectDataset("user-a", "project-2").dataset_library.datasetId, "ds-2");
});

test("existing Dataset Library versions remain pinned independently per project", () => {
  sessionStorage.clear();
  saveProjectDataset("user-a", "project-1", makeDataset({ dataset_library: { datasetId: "ds-1", versionId: "v1", datasetName: "Shared Asset" } }));
  saveProjectDataset("user-a", "project-2", makeDataset({ dataset_library: { datasetId: "ds-1", versionId: "v2", datasetName: "Shared Asset" } }));
  assert.equal(loadProjectDataset("user-a", "project-1").dataset_library.versionId, "v1");
  assert.equal(loadProjectDataset("user-a", "project-2").dataset_library.versionId, "v2");
});

test("dataset version change invalidates stale cached identity for that project", () => {
  sessionStorage.clear();
  saveProjectDataset("user-a", "project-1", makeDataset({ dataset_version: "v1", rows: [{ Class: 0, V1: 1, V2: 2 }] }));
  saveProjectDataset("user-a", "project-1", makeDataset({ dataset_version: "v2", rows: [{ Class: 1, V1: 9, V2: 9 }] }));
  const restored = loadProjectDataset("user-a", "project-1");
  assert.equal(restored.dataset_version, "v2");
  assert.deepEqual(restored.rows, [{ V1: 9, V2: 9 }]);
  assert.equal(restored.target, "Class", "target contract metadata remains available");
  assert.equal(restored.target_values_included, false);
});

test("target values are never persisted in a new project-scoped browser cache", () => {
  sessionStorage.clear();
  saveProjectDataset("user-a", "project-1", makeDataset({
    rows: [{ Class: 1, V1: 7, V2: 8 }],
  }));
  const raw = JSON.parse(sessionStorage.getItem(buildProjectDatasetStorageKey("user-a", "project-1")));
  assert.equal(raw.cache_schema_version, 2);
  assert.equal(raw.target_values_included, false);
  assert.equal(Object.hasOwn(raw.rows[0], "Class"), false);
  assert.deepEqual(raw.rows[0], { V1: 7, V2: 8 });
});

test("an exact-ID legacy cache containing target values is quarantined for backend refetch", () => {
  sessionStorage.clear();
  const key = buildProjectDatasetStorageKey("user-a", "project-1");
  sessionStorage.setItem(key, JSON.stringify({
    ...makeDataset(),
    dataset_id: "ds-1",
    dataset_version_id: "v1",
  }));
  assert.equal(loadProjectDataset("user-a", "project-1"), null);
  assert.equal(sessionStorage.getItem(key), null);
});

test("project deletion removes that project's browser snapshot", () => {
  sessionStorage.clear();
  saveProjectDataset("user-a", "project-1", makeDataset());
  saveProjectDataset("user-a", "project-2", makeDataset());
  clearProjectDataset("user-a", "project-1");
  assert.equal(loadProjectDataset("user-a", "project-1"), null);
  assert.notEqual(loadProjectDataset("user-a", "project-2"), null);
});

test("sign-out clears the outgoing user's scoped state so the next signed-in identity in this tab cannot read it", () => {
  sessionStorage.clear();
  saveProjectDataset("user-a", "project-1", makeDataset());
  saveProjectDataset("user-a", "project-2", makeDataset());
  saveProjectDataset("user-b", "project-1", makeDataset({ target: "MedHouseVal", headers: ["MedHouseVal"], selected_columns: [], problem_type: "regression" }));
  clearUserDatasetState("user-a");
  assert.equal(loadProjectDataset("user-a", "project-1"), null);
  assert.equal(loadProjectDataset("user-a", "project-2"), null);
  assert.notEqual(loadProjectDataset("user-b", "project-1"), null);
});

test("legacy unscoped key is discarded on first use and never mapped into any project", () => {
  sessionStorage.clear();
  sessionStorage.setItem("modeling-tool-dataset", JSON.stringify(makeDataset({ dataset_version: "legacy" })));
  const result = loadProjectDataset("user-a", "project-1");
  assert.equal(result, null, "legacy content must not be surfaced under any real project key");
  assert.equal(sessionStorage.getItem("modeling-tool-dataset"), null, "legacy key must be removed, not left in place");
});

test("clearLegacyUnscopedDatasetState is a safe no-op when no legacy key exists", () => {
  sessionStorage.clear();
  assert.doesNotThrow(() => clearLegacyUnscopedDatasetState());
});

test("browser cache absence does not create a backend authorization bypass (loadProjectDataset returns null, never a default/anonymous fallback dataset)", () => {
  sessionStorage.clear();
  const result = loadProjectDataset("unauthenticated-anonymous-fallback", "any-project");
  assert.equal(result, null);
});

test("ambient loadLocalDataset/saveLocalDataset resolve the currently active user and project without touching the raw sessionStorage key", () => {
  sessionStorage.clear();
  setCachedUserId("user-a");
  setCachedProjectId("project-A");
  saveLocalDataset(makeDataset({ dataset_version: "ambient-A" }));

  setCachedProjectId("project-B");
  const emptyForB = loadLocalDataset();
  assert.equal(emptyForB, null);

  setCachedProjectId("project-A");
  const restoredA = loadLocalDataset();
  assert.equal(restoredA.dataset_version, "ambient-A");

  // The raw legacy/unscoped key is never written by the ambient wrappers.
  assert.equal(sessionStorage.getItem("modeling-tool-dataset"), null);
});

test("ambient wrappers isolate two different signed-in users sharing the same active project id", () => {
  sessionStorage.clear();
  setCachedUserId("user-a");
  setCachedProjectId("project-shared");
  saveLocalDataset(makeDataset({ dataset_version: "user-a-ambient" }));

  setCachedUserId("user-b");
  const forUserB = loadLocalDataset();
  assert.equal(forUserB, null);

  setCachedUserId("user-a");
  assert.equal(loadLocalDataset().dataset_version, "user-a-ambient");
});

import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/open-project-tests", import.meta.url));

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

const browserEvents = [];
globalThis.localStorage = new MemoryStorage();
globalThis.sessionStorage = new MemoryStorage();
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};
globalThis.window = {
  location: { pathname: "/" },
  dispatchEvent(event) {
    browserEvents.push(event);
    return true;
  },
  addEventListener() {},
  removeEventListener() {},
};
globalThis.fetch = async () => ({ ok: true, json: async () => ({ ok: true }) });

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

async function compileTestModules() {
  await rm(TMP_DIR, { recursive: true, force: true });
  await transpileSource("src/config/workflows.ts", path.join(TMP_DIR, "src/config/workflows.js"));
  await transpileSource("src/config/optimizationTemplates.ts", path.join(TMP_DIR, "src/config/optimizationTemplates.js"));
  await transpileSource("src/lib/projectImportValidation.ts", path.join(TMP_DIR, "src/lib/projectImportValidation.js"));
  await transpileSource("src/lib/projectPersistence.ts", path.join(TMP_DIR, "src/lib/projectPersistence.js"));
  await transpileSource("src/lib/api.ts", path.join(TMP_DIR, "src/lib/api.js"));
  await transpileSource("src/lib/serverPersistence.ts", path.join(TMP_DIR, "src/lib/serverPersistence.js"));
  await transpileSource("src/lib/activeProjectContext.ts", path.join(TMP_DIR, "src/lib/activeProjectContext.js"));
  await transpileSource("src/lib/authSession.ts", path.join(TMP_DIR, "src/lib/authSession.js"));
  await transpileSource("src/lib/datasetIdentity.ts", path.join(TMP_DIR, "src/lib/datasetIdentity.js"));
  await transpileSource("src/lib/authoritativeProjectContext.ts", path.join(TMP_DIR, "src/lib/authoritativeProjectContext.js"));
  await transpileSource("src/lib/projectScopedRoutes.ts", path.join(TMP_DIR, "src/lib/projectScopedRoutes.js"));
  await transpileSource("src/lib/localDataset.ts", path.join(TMP_DIR, "src/lib/localDataset.js"));
  await transpileSource("src/lib/localProjects.ts", path.join(TMP_DIR, "src/lib/localProjects.js"));
  await transpileSource("src/lib/projectRegistryLoadState.ts", path.join(TMP_DIR, "src/lib/projectRegistryLoadState.js"));
  return {
    localProjects: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/localProjects.js")).href),
    persistence: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/projectPersistence.js")).href),
    projectImportValidation: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/projectImportValidation.js")).href),
    projectRegistryLoadState: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/projectRegistryLoadState.js")).href),
    workflows: await import(pathToFileURL(path.join(TMP_DIR, "src/config/workflows.js")).href),
  };
}

const modules = await compileTestModules();

function resetStorage() {
  localStorage.clear();
  sessionStorage.clear();
  modules?.localProjects?.clearVolatileProjectRegistryForTests?.();
  browserEvents.length = 0;
  window.location.pathname = "/";
}

function predictiveSnapshot(overrides = {}) {
  const workflow = modules.workflows.getWorkflowDefinition("predictive-modeling");
  return {
    projectId: "open-project-predictive",
    modelId: "15211",
    projectName: "Open Project Predictive Test",
    projectType: "predictive-modeling",
    workflowId: workflow.id,
    workflowSteps: workflow.steps.map((step, index) => ({ ...step, status: index < 2 ? "complete" : "pending" })),
    currentStepId: "step01",
    hasDataset: true,
    ...overrides,
  };
}

function experimentalSnapshot(overrides = {}) {
  const workflow = modules.workflows.getWorkflowDefinition("experimental-design");
  return {
    projectId: "open-project-experimental",
    modelId: "4520",
    projectName: "Open Project Experimental Test",
    projectType: "experimental-design",
    workflowId: workflow.id,
    workflowSteps: workflow.steps.map((step, index) => ({ ...step, status: index < 4 ? "complete" : "pending" })),
    currentStepId: "experimental-design-4",
    hasDataset: false,
    ...overrides,
  };
}

function registryProject(projectId, projectName = projectId) {
  return { projectId, projectName };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function httpError(status) {
  const error = new Error(`HTTP ${status}`);
  error.status = status;
  return error;
}

test("/projects/open route is registered", async () => {
  const source = await readFile(new URL("../src/apps/ModelingApp.tsx", import.meta.url), "utf8");
  assert.match(source, /<Route[\s\S]{0,120}path="\/projects\/open"[\s\S]{0,360}<OpenProject/);
});

test("Open Project navigation targets are absolute", async () => {
  const sidebar = await readFile(new URL("../src/components/Sidebar.tsx", import.meta.url), "utf8");
  const dashboard = await readFile(new URL("../src/steps/Dashboard.tsx", import.meta.url), "utf8");
  assert.match(sidebar, /to="\/projects\/open"/);
  assert.match(dashboard, /to="\/projects\/open"/);
  assert.doesNotMatch(dashboard, /Open Existing Project[\s\S]{0,120}to="\/step01"/);
  assert.doesNotMatch(`${sidebar}\n${dashboard}`, /navigate\(["'](?:\.\.\/)?projects\/open["']\)|window\.location\s*=\s*["']projects\/open["']/);
});

test("Open Project page includes Recent Projects, import, empty state, and repair UI", async () => {
  const source = await readFile(new URL("../src/steps/ProjectUtilityPages.tsx", import.meta.url), "utf8");
  assert.match(source, /Recent Projects/);
  assert.match(source, /Import Project/);
  assert.match(source, /No local projects yet/);
  assert.match(source, /Repair Recent Projects/);
  assert.match(source, /Project Recovery/);
  assert.match(source, /Recover Current Project/);
  assert.match(source, /Export Current Project Backup/);
  assert.match(source, /Rebuild Recent Projects Index/);
  assert.match(source, /Compact Browser Project Storage/);
  assert.match(source, /Project Storage Diagnostics/);
  assert.match(source, /getLocalProjectsRegistryStatus/);
  assert.match(source, /Deep Recovery Scan/);
  assert.match(source, /Scan Browser Storage/);
  assert.match(source, /Scan Server Artifacts/);
  assert.match(source, /Scan Dataset Links/);
  assert.match(source, /Recover Selected Projects/);
  assert.match(source, /Export Recovery Report/);
  assert.match(source, /Detailed View/);
  assert.match(source, /OPEN_PROJECT_VIEW_MODE_KEY/);
  assert.match(source, /atlas-open-project-view-mode/);
  assert.match(source, /readSavedViewMode\(OPEN_PROJECT_VIEW_MODE_KEY,\s*"detail"\)/);
  assert.match(source, /ProjectSortKey/);
  assert.match(source, /EnterpriseProjectTable/);
  assert.match(source, /SortableProjectHeader/);
  assert.match(source, /compareProjectRows/);
  assert.match(source, /Project Type/);
  assert.match(source, /Current Stage/);
  assert.match(source, /Progress/);
  assert.match(source, /Linked Datasets/);
  assert.match(source, /Last Modified/);
  assert.match(source, /Storage Location/);
  assert.match(source, /Recovery Status/);
  assert.match(source, /min-w-\[940px\]/);
  assert.match(source, /sticky right-0/);
  assert.match(source, /Delete project/);
  assert.match(source, /deleteProjectFromDatabase/);
  assert.match(source, /Dataset Library assets and source data files are retained/);
  assert.match(source, /inferProjectStorageLocation/);
  assert.match(source, /inferProjectRecoveryStatus/);
  assert.match(source, /Predictive Modeling/);
  assert.match(source, /Experimental Design/);
  assert.match(source, /Regression/);
  assert.match(source, /Classification/);
  assert.match(source, /ProjectDetailTable/);
  assert.match(source, /RecoveryCandidateTable/);
  assert.match(source, /Advanced Recovery Tools/);
  assert.match(source, /shouldAutoExpandRecoveryTools/);
  assert.ok(
    source.indexOf("projectListSection") < source.indexOf("Advanced Recovery Tools"),
    "Open Project should define/render the normal project launcher before advanced recovery tooling."
  );
});

test("Open Project storage loads with no projects", () => {
  resetStorage();
  assert.deepEqual(modules.localProjects.loadLocalProjects(), []);
  const status = modules.localProjects.getLocalProjectsRegistryStatus();
  assert.equal(status.ok, true);
  assert.equal(status.projectCount, 0);
});

test("Open Project storage loads valid Recent Projects", () => {
  resetStorage();
  const record = modules.localProjects.upsertProjectSnapshot(predictiveSnapshot(), "browser");
  const projects = modules.localProjects.loadLocalProjects();
  assert.equal(record.projectId, "open-project-predictive");
  assert.equal(projects.length, 1);
  assert.equal(projects[0].projectName, "Open Project Predictive Test");
});

test("corrupted Recent Projects registry reports repair state without throwing", () => {
  resetStorage();
  localStorage.setItem(modules.localProjects.LOCAL_PROJECTS_KEY, "{ not-json");
  const status = modules.localProjects.getLocalProjectsRegistryStatus();
  assert.equal(status.corrupted, true);
  assert.equal(status.validProjects.length, 0);
  assert.deepEqual(modules.localProjects.loadLocalProjects(), []);
});

test("repair Recent Projects preserves valid project records", () => {
  resetStorage();
  const valid = {
    projectId: "valid-project",
    modelId: "10001",
    projectName: "Valid Browser Project",
    projectType: "predictive-modeling",
    workflowId: "predictive-modeling",
    createdAt: "2026-07-03T00:00:00.000Z",
    lastModified: "2026-07-03T00:00:00.000Z",
    source: "browser",
    snapshot: predictiveSnapshot({ projectId: "valid-project", projectName: "Valid Browser Project" }),
  };
  localStorage.setItem(modules.localProjects.LOCAL_PROJECTS_KEY, JSON.stringify([valid, { broken: true }]));
  const result = modules.localProjects.repairLocalProjectsRegistry();
  assert.equal(result.projects.length, 1);
  assert.equal(result.projects[0].projectId, "valid-project");
});

test("thin project snapshots remain openable from Recent Projects", () => {
  resetStorage();
  const record = modules.localProjects.upsertProjectSnapshot(experimentalSnapshot(), "browser");
  const thin = modules.persistence.thinProjectForStorage(record);
  modules.localProjects.saveLocalProjects([thin]);
  const projects = modules.localProjects.loadLocalProjects();
  assert.equal(projects.length, 1);
  assert.equal(projects[0].snapshot.currentStepId, "experimental-design-4");
  assert.equal(projects[0].snapshot.workflowId, "experimental-design");
});

test("opening a project restores compact persisted state", () => {
  resetStorage();
  localStorage.setItem("atlas-workflow-node-state:open-project-experimental:experimental-design-4", JSON.stringify({ objective: "Pricing Strategy\n- Current\n- Personalized" }));
  const record = modules.localProjects.upsertProjectSnapshot(experimentalSnapshot(), "browser");
  const warnings = modules.localProjects.restoreLocalProjectArtifacts(record.snapshot);
  assert.equal(Array.isArray(warnings), true);
  assert.equal(localStorage.getItem("atlas-workflow-node-state:open-project-experimental:experimental-design-4") !== null, true);
});

test("quota write failure preserves active project in recovery registry without throwing", () => {
  resetStorage();
  const originalSetItem = localStorage.setItem.bind(localStorage);
  localStorage.setItem = () => {
    throw new Error("quota");
  };
  const result = modules.localProjects.saveActiveProjectBeforeNavigation(predictiveSnapshot());
  localStorage.setItem = originalSetItem;
  assert.equal(result.ok, true);
  assert.match(result.message, /quota|storage/i);
  const status = modules.localProjects.getLocalProjectsRegistryStatus();
  assert.equal(status.volatileFallback, true);
  assert.equal(modules.localProjects.loadLocalProjects()[0].projectName, "Open Project Predictive Test");
});

test("safe localStorage write reports quota errors without throwing", () => {
  resetStorage();
  const originalSetItem = localStorage.setItem.bind(localStorage);
  localStorage.setItem = () => {
    const error = new Error("QuotaExceededError");
    error.name = "QuotaExceededError";
    throw error;
  };
  const result = modules.localProjects.safeSetLocalStorage("atlas-test", "value");
  localStorage.setItem = originalSetItem;
  assert.equal(result.ok, false);
  assert.equal(result.quotaExceeded, true);
  assert.match(result.errorMessage, /QuotaExceededError/);
});

test("storage diagnostics expose registry fallback and largest keys", () => {
  resetStorage();
  localStorage.setItem("modeling-tool-decision-journal", "x".repeat(90000));
  const originalSetItem = localStorage.setItem.bind(localStorage);
  localStorage.setItem = (key, value) => {
    if (String(key) === modules.localProjects.LOCAL_PROJECTS_KEY) throw new Error("quota");
    originalSetItem(key, value);
  };
  modules.localProjects.saveActiveProjectBeforeNavigation(predictiveSnapshot());
  localStorage.setItem = originalSetItem;
  const diagnostics = modules.localProjects.getProjectStorageDiagnostics("open-project-predictive", predictiveSnapshot().workflowSteps);
  assert.equal(diagnostics.volatileFallback, true);
  assert.equal(diagnostics.largestKeys.some((item) => item.key === "modeling-tool-decision-journal"), true);
});

test("save-before-navigation infers predictive current step from browser route", () => {
  resetStorage();
  window.location.pathname = "/step07";
  const result = modules.localProjects.saveActiveProjectBeforeNavigation(predictiveSnapshot({ currentStepId: "step00" }));
  assert.equal(result.ok, true);
  const projects = modules.localProjects.loadLocalProjects();
  assert.equal(projects[0].snapshot.currentStepId, "step07");
});

test("save-before-navigation infers experimental current step from browser route", () => {
  resetStorage();
  window.location.pathname = "/workflow/experimental-design/8";
  const result = modules.localProjects.saveActiveProjectBeforeNavigation(experimentalSnapshot({ currentStepId: "experimental-design-1" }));
  assert.equal(result.ok, true);
  const projects = modules.localProjects.loadLocalProjects();
  assert.equal(projects[0].snapshot.currentStepId, "experimental-design-8");
});

test("import validation errors are returned inline-style and do not throw", () => {
  resetStorage();
  const validation = modules.projectImportValidation.validateProjectImport({ not: "a project" });
  assert.equal(validation.ok, false);
  assert.equal(validation.errors.length > 0, true);
});

test("save-before-navigation infers predictive current step from a project-scoped route", () => {
  resetStorage();
  window.location.pathname = "/projects/open-project-predictive/step07";
  const result = modules.localProjects.saveActiveProjectBeforeNavigation(
    predictiveSnapshot({ currentStepId: "step00" }),
  );
  assert.equal(result.ok, true);
  const projects = modules.localProjects.loadLocalProjects();
  assert.equal(projects[0].snapshot.currentStepId, "step07");
});

test("project registry 1: a successful project response produces the rendered list state", async () => {
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async () => [registryProject("project-success", "Successful Project")],
  });
  const state = await controller.load();
  const source = await readFile(new URL("../src/steps/ProjectUtilityPages.tsx", import.meta.url), "utf8");
  assert.equal(state.status, "success");
  assert.equal(state.projects[0].projectName, "Successful Project");
  assert.equal(state.error, null);
  assert.match(source, /data-testid="project-registry-list"/);
  assert.match(source, /registryLoadState\.status === "success"/);
});

test("project registry 2: 132 valid records never produce the obsolete backend-unavailable state", async () => {
  const projects = Array.from({ length: 132 }, (_, index) => registryProject(`project-${index + 1}`));
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async () => projects,
  });
  const state = await controller.load();
  const source = await readFile(new URL("../src/steps/ProjectUtilityPages.tsx", import.meta.url), "utf8");
  assert.equal(state.status, "success");
  assert.equal(state.projects.length, 132);
  assert.equal(state.error, null);
  assert.doesNotMatch(source, /Backend project registry unavailable/);
});

test("project registry 3: two duplicate successful requests cannot create an error", async () => {
  const gates = [];
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async () => {
      const gate = deferred();
      gates.push(gate);
      return gate.promise;
    },
  });
  const older = controller.load();
  const newer = controller.load();
  gates[1].resolve([registryProject("newer-success")]);
  await newer;
  gates[0].resolve([registryProject("older-success")]);
  await older;
  const state = controller.getState();
  assert.equal(state.status, "success");
  assert.equal(state.projects[0].projectId, "newer-success");
  assert.equal(state.error, null);
});

test("project registry 4: a successful retry clears the prior failure", async () => {
  let attempt = 0;
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async () => {
      attempt += 1;
      if (attempt === 1) throw new TypeError("Failed to fetch");
      return [registryProject("retry-success")];
    },
  });
  assert.equal((await controller.load()).status, "error");
  const recovered = await controller.load();
  assert.equal(recovered.status, "success");
  assert.equal(recovered.projects[0].projectId, "retry-success");
  assert.equal(recovered.error, null);
});

test("project registry 5: an older failure arriving after newer success is ignored", async () => {
  const olderGate = deferred();
  let call = 0;
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async () => {
      call += 1;
      if (call === 1) return olderGate.promise;
      return [registryProject("authoritative-success")];
    },
  });
  const older = controller.load();
  await controller.load();
  olderGate.reject(new TypeError("Failed to fetch"));
  await older;
  const state = controller.getState();
  assert.equal(state.status, "success");
  assert.equal(state.projects[0].projectId, "authoritative-success");
  assert.equal(state.error, null);
});

test("project registry 6: an older success cannot overwrite a newer authenticated session", async () => {
  const olderGate = deferred();
  let call = 0;
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async () => {
      call += 1;
      if (call === 1) return olderGate.promise;
      return [registryProject("session-b-project")];
    },
  });
  const sessionA = controller.load();
  await controller.load();
  olderGate.resolve([registryProject("session-a-project")]);
  await sessionA;
  const state = controller.getState();
  assert.equal(state.status, "success");
  assert.deepEqual(state.projects.map((project) => project.projectId), ["session-b-project"]);
});

test("project registry 7: AbortError from a superseded request never renders an error", async () => {
  let call = 0;
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async (signal) => {
      call += 1;
      if (call > 1) return [registryProject("remount-success")];
      return new Promise((resolve, reject) => {
        signal.addEventListener("abort", () => {
          const error = new Error("superseded");
          error.name = "AbortError";
          reject(error);
        }, { once: true });
      });
    },
  });
  const superseded = controller.load();
  const remount = controller.load();
  await Promise.all([superseded, remount]);
  const state = controller.getState();
  assert.equal(state.status, "success");
  assert.equal(state.projects[0].projectId, "remount-success");
  assert.equal(state.error, null);
});

test("project registry 8: StrictMode cleanup and remount remain race-safe", async () => {
  const firstGate = deferred();
  let call = 0;
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async () => {
      call += 1;
      if (call === 1) return firstGate.promise;
      return [registryProject("strictmode-remount")];
    },
  });
  const firstMount = controller.load();
  controller.dispose();
  const secondMount = controller.load();
  await secondMount;
  firstGate.resolve([registryProject("strictmode-stale")]);
  await firstMount;
  const state = controller.getState();
  assert.equal(call, 2);
  assert.equal(state.status, "success");
  assert.equal(state.projects[0].projectId, "strictmode-remount");
});

test("project registry 9: a valid empty response produces an empty state", async () => {
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async () => [],
  });
  const state = await controller.load();
  assert.equal(state.status, "empty");
  assert.deepEqual(state.projects, []);
  assert.equal(state.error, null);
});

test("project registry 10: malformed HTTP 200 data produces a response-validation error", async () => {
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async () => ({ ok: true, projects: "not-an-array" }),
  });
  const state = await controller.load();
  assert.equal(state.status, "error");
  assert.equal(state.error.kind, "response");
  assert.match(state.error.message, /invalid response|projects array/i);
  assert.doesNotMatch(state.error.message, /Failed to fetch/i);
  assert.deepEqual(state.projects, []);
});

test("project registry 11: HTTP 401 follows the sign-in contract", async () => {
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async () => { throw httpError(401); },
  });
  const state = await controller.load();
  const appSource = await readFile(new URL("../src/apps/ModelingApp.tsx", import.meta.url), "utf8");
  assert.equal(state.status, "error");
  assert.equal(state.error.kind, "authentication");
  assert.match(state.error.message, /Sign in again/);
  assert.match(appSource, /onSessionExpired/);
  assert.match(appSource, /navigate\("\/login", \{ replace: true \}\)/);
  assert.doesNotMatch(state.error.message, /backend.*unavailable/i);
});

test("project registry 12: HTTP 403 produces authorization state instead of backend-unavailable", async () => {
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async () => { throw httpError(403); },
  });
  const state = await controller.load();
  assert.equal(state.status, "error");
  assert.equal(state.error.kind, "authorization");
  assert.match(state.error.message, /permission/);
  assert.doesNotMatch(state.error.message, /backend.*unavailable/i);
});

test("project registry 13: a genuine latest network failure produces network error state", async () => {
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async () => { throw new TypeError("Failed to fetch"); },
  });
  const state = await controller.load();
  assert.equal(state.status, "error");
  assert.equal(state.error.kind, "network");
  assert.match(state.error.message, /could not reach ATLAS/i);
  assert.deepEqual(state.projects, []);
});

test("project registry 14: controlled retry recovers from a genuine network failure", async () => {
  const responses = [new TypeError("Failed to fetch"), [registryProject("network-recovery")]];
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async () => {
      const response = responses.shift();
      if (response instanceof Error) throw response;
      return response;
    },
  });
  const failed = await controller.load();
  assert.equal(failed.status, "error");
  const recovered = await controller.load();
  assert.equal(recovered.status, "success");
  assert.equal(recovered.projects[0].projectId, "network-recovery");
  assert.equal(recovered.error, null);
});

test("project registry 15: authoritative success, empty, and error states cannot coexist", () => {
  const registry = modules.projectRegistryLoadState;
  const loading = registry.startProjectRegistryLoad(registry.initialProjectRegistryLoadState(), 1);
  const success = registry.resolveProjectRegistryLoad(loading, 1, [registryProject("invariant-success")]);
  assert.equal(success.status, "success");
  assert.equal(success.projects.length, 1);
  assert.equal(success.error, null);

  const nextLoading = registry.startProjectRegistryLoad(success, 2);
  assert.deepEqual(nextLoading.projects, []);
  assert.equal(nextLoading.error, null);
  const failed = registry.rejectProjectRegistryLoad(nextLoading, 2, new TypeError("Failed to fetch"));
  assert.equal(failed.status, "error");
  assert.deepEqual(failed.projects, []);
  assert.ok(failed.error);

  const emptyLoading = registry.startProjectRegistryLoad(failed, 3);
  const empty = registry.resolveProjectRegistryLoad(emptyLoading, 3, []);
  assert.equal(empty.status, "empty");
  assert.deepEqual(empty.projects, []);
  assert.equal(empty.error, null);
});

test("project registry 16: focused tests use synthetic data and do not write browser or live runtime state", async () => {
  resetStorage();
  const localKeysBefore = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index));
  const sessionKeysBefore = Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index));
  let receivedSignal = false;
  const controller = modules.projectRegistryLoadState.createProjectRegistryLoadController({
    loadProjects: async (signal) => {
      receivedSignal = signal instanceof AbortSignal;
      return [registryProject("synthetic-project-only")];
    },
  });
  const state = await controller.load();
  assert.equal(receivedSignal, true);
  assert.equal(state.status, "success");
  assert.deepEqual(Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)), localKeysBefore);
  assert.deepEqual(Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index)), sessionKeysBefore);
});

test("project registry root-cause regression: launcher removes bundle fan-out and isolates optional enrichment", async () => {
  const source = await readFile(new URL("../src/steps/ProjectUtilityPages.tsx", import.meta.url), "utf8");
  assert.match(source, /getProjectWorkflowStateFromDatabase/);
  assert.match(source, /workerCount = Math\.min\(8, records\.length\)/);
  assert.match(source, /enriched\[index\] = records\[index\]/);
  assert.doesNotMatch(source, /getProjectPersistenceBundle/);
  assert.doesNotMatch(source, /Backend project registry unavailable/);
});

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
  await transpileSource("src/lib/projectImportValidation.ts", path.join(TMP_DIR, "src/lib/projectImportValidation.js"));
  await transpileSource("src/lib/projectPersistence.ts", path.join(TMP_DIR, "src/lib/projectPersistence.js"));
  await transpileSource("src/lib/localProjects.ts", path.join(TMP_DIR, "src/lib/localProjects.js"));
  return {
    localProjects: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/localProjects.js")).href),
    persistence: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/projectPersistence.js")).href),
    projectImportValidation: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/projectImportValidation.js")).href),
    workflows: await import(pathToFileURL(path.join(TMP_DIR, "src/config/workflows.js")).href),
  };
}

const modules = await compileTestModules();

function resetStorage() {
  localStorage.clear();
  sessionStorage.clear();
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

test("/projects/open route is registered", async () => {
  const source = await readFile(new URL("../src/apps/ModelingApp.tsx", import.meta.url), "utf8");
  assert.match(source, /<Route\s+path="\/projects\/open"\s+element=\{<OpenProject\s*\/>\}/);
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
  assert.match(source, /getLocalProjectsRegistryStatus/);
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

test("save-before-navigation returns failure without throwing", () => {
  resetStorage();
  const originalSetItem = localStorage.setItem.bind(localStorage);
  localStorage.setItem = () => {
    throw new Error("quota");
  };
  const result = modules.localProjects.saveActiveProjectBeforeNavigation(predictiveSnapshot());
  localStorage.setItem = originalSetItem;
  assert.equal(result.ok, false);
  assert.match(result.message, /quota|storage/i);
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

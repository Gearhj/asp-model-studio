import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/persistence-tests", import.meta.url));

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
  await transpileSource("src/lib/artifactStorage.ts", path.join(TMP_DIR, "src/lib/artifactStorage.js"));
  await transpileSource("src/lib/projectImportValidation.ts", path.join(TMP_DIR, "src/lib/projectImportValidation.js"));
  await transpileSource("src/lib/projectPersistence.ts", path.join(TMP_DIR, "src/lib/projectPersistence.js"));
  await transpileSource("src/lib/api.ts", path.join(TMP_DIR, "src/lib/api.js"));
  await transpileSource("src/lib/serverPersistence.ts", path.join(TMP_DIR, "src/lib/serverPersistence.js"));
  // localProjects.ts's project-deletion cleanup now sweeps the scoped
  // dataset sessionStorage key (src/lib/localDataset.ts, Stage 6.2) -- its
  // own two tiny ambient-cache deps must be transpiled alongside it.
  await transpileSource("src/lib/activeProjectContext.ts", path.join(TMP_DIR, "src/lib/activeProjectContext.js"));
  await transpileSource("src/lib/authSession.ts", path.join(TMP_DIR, "src/lib/authSession.js"));
  await transpileSource("src/lib/localDataset.ts", path.join(TMP_DIR, "src/lib/localDataset.js"));
  await transpileSource("src/lib/localProjects.ts", path.join(TMP_DIR, "src/lib/localProjects.js"));
  return {
    artifactStorage: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/artifactStorage.js")).href),
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
}

function setJson(storage, key, value) {
  storage.setItem(key, JSON.stringify(value));
}

function predictiveSnapshot(overrides = {}) {
  const workflow = modules.workflows.getWorkflowDefinition("predictive-modeling");
  return {
    projectId: "predictive-test",
    modelId: "15211",
    projectName: "Predictive Persistence Test",
    projectType: "predictive-modeling",
    workflowId: workflow.id,
    workflowSteps: workflow.steps.map((step, index) => ({ ...step, status: index < 8 ? "complete" : "pending" })),
    currentStepId: "step08",
    hasDataset: true,
    ...overrides,
  };
}

function experimentalSnapshot(overrides = {}) {
  const workflow = modules.workflows.getWorkflowDefinition("experimental-design");
  return {
    projectId: "experimental-test",
    modelId: "4520",
    projectName: "Experimental Persistence Test",
    projectType: "experimental-design",
    workflowId: workflow.id,
    workflowSteps: workflow.steps.map((step, index) => ({ ...step, status: index < 9 ? "complete" : "pending" })),
    currentStepId: "experimental-design-9",
    hasDataset: false,
    ...overrides,
  };
}

function seedPredictiveArtifacts(projectId = "predictive-test") {
  setJson(localStorage, "modeling-tool-project-context", {
    projectName: "Predictive Persistence Test",
    targetDefinition: "Class indicates confirmed fraud.",
    primarySuccessMetric: ["AUC", "KS"],
  });
  setJson(localStorage, "modeling-tool-missing-config", {
    V1: { strategy: "Median" },
    V2: { strategy: "Median" },
  });
  setJson(localStorage, "modeling-tool-outlier-methods", {
    Amount: { method: "winsorize", lower: 1, upper: 99 },
  });
  setJson(localStorage, "modeling-tool-decision-journal", Array.from({ length: 130 }, (_, index) => ({
    timestamp: `2026-07-03T12:${String(index % 60).padStart(2, "0")}:00.000Z`,
    workflowStep: "Model Training",
    actionType: "changed",
    subject: `entry-${index}`,
    previousValue: "old",
    newValue: "new",
  })));
  setJson(localStorage, `atlas-workflow-node-state:${projectId}:step09`, {
    objective: "Interpret model",
    analysisSnapshot: { large: true },
    simulationResults: {
      inputs: { minimumDetectableLift: 0.05 },
      powerByIteration: Array.from({ length: 200 }, (_, index) => ({ achievedPower: index / 200, estimatedLift: index / 1000 })),
    },
  });
  setJson(sessionStorage, "modeling-tool-dataset", {
    headers: ["Class", "Amount", "V1", "V2"],
    target: "Class",
    selected_columns: ["Amount", "V1", "V2"],
    problem_type: "classification",
    rows: Array.from({ length: 250 }, (_, index) => ({ Class: index % 50 === 0 ? 1 : 0, Amount: index, V1: index / 10, V2: index / 20 })),
  });
  setJson(sessionStorage, "modeling-tool-training-summary", {
    problem_type: "classification",
    ranked: Array.from({ length: 35 }, (_, index) => ({ key: `model-${index}`, name: `Model ${index}`, auc: 0.9 - index / 1000 })),
  });
}

function seedExperimentalArtifacts(projectId = "experimental-test") {
  setJson(localStorage, `atlas-workflow-node-state:${projectId}:experimental-design-3`, {
    objective: "Pricing Strategy\n- Current Pricing\n- Personalized Pricing\n\nContact Channel\n- Email\n- SMS",
    decision: "Two-factor design approved.",
  });
  setJson(localStorage, `atlas-workflow-node-state:${projectId}:experimental-design-4`, {
    objective: "Pricing Strategy\n- Current Pricing\n- Personalized Pricing\n\nContact Channel\n- Email\n- SMS",
    decision: "Four treatment cells approved.",
  });
  setJson(localStorage, `atlas-workflow-node-state:${projectId}:experimental-design-8`, {
    method: "Launch readiness simulation",
    simulationResults: {
      meanPower: 0.812,
      wrongWinnerRisk: 0.043,
      launchRecommendation: "Proceed",
      powerByIteration: Array.from({ length: 500 }, (_, index) => ({ achievedPower: 0.75 + (index % 20) / 100 })),
    },
  });
}

test("compact project snapshot creation excludes regulated browser artifacts", () => {
  resetStorage();
  seedPredictiveArtifacts();
  const snapshot = modules.persistence.buildPersistedProjectState("predictive-test");
  assert.ok(snapshot);
  assert.equal(snapshot.datasetPreview, undefined);
  assert.deepEqual(snapshot.sessionStorage, {});
  assert.deepEqual(snapshot.localStorage, {
    "modeling-tool-project-context": {
      projectName: "Predictive Persistence Test",
      targetDefinition: "Class indicates confirmed fraud.",
      primarySuccessMetric: ["AUC", "KS"],
    },
  });
  assert.deepEqual(snapshot.workflowNodeStates, {});
  assert.equal(snapshot.missingArtifacts.some((warning) => warning.includes("regulated data")), true);
});

test("quota-safe compaction trims oversized registry artifacts", () => {
  const compacted = modules.persistence.compactProjectForStorage({
    snapshot: {
      projectId: "p",
      persistedLocalState: {
        schemaVersion: 1,
        savedAt: "2026-07-03T00:00:00.000Z",
        localStorage: {
          "modeling-tool-decision-journal": Array.from({ length: 90 }, (_, index) => ({ index })),
          "modeling-tool-mlflow-lite-experiments": Array.from({ length: 70 }, (_, index) => ({ index })),
        },
        sessionStorage: {},
        workflowNodeStates: {},
        missingArtifacts: [],
        storageEstimateBytes: 0,
      },
    },
  });
  assert.equal(compacted.snapshot.persistedLocalState.localStorage["modeling-tool-decision-journal"].length, 50);
  assert.equal(compacted.snapshot.persistedLocalState.localStorage["modeling-tool-mlflow-lite-experiments"].length, 30);
});

test("thin project fallback preserves project metadata without large embedded artifacts", () => {
  const thin = modules.persistence.thinProjectForStorage({
    projectId: "p",
    snapshot: {
      projectId: "p",
      projectName: "Quota Test",
      projectType: "experimental-design",
      workflowId: "experimental-design",
      workflowSteps: [],
      currentStepId: "experimental-design-8",
      persistedLocalState: {
        schemaVersion: 1,
        savedAt: "2026-07-03T00:00:00.000Z",
        localStorage: { huge: "x".repeat(1000) },
        sessionStorage: { huge: "x".repeat(1000) },
        workflowNodeStates: { huge: { rows: Array.from({ length: 1000 }, (_, index) => index) } },
        datasetPreview: {
          headers: ["a"],
          target: null,
          selected_columns: ["a"],
          rowCount: 1000,
          previewRows: Array.from({ length: 50 }, (_, index) => ({ a: index })),
          artifactStatus: "preview_restored_requires_reload",
        },
        missingArtifacts: [],
        storageEstimateBytes: 999999,
      },
    },
  });
  assert.equal(thin.snapshot.projectName, "Quota Test");
  assert.deepEqual(thin.snapshot.persistedLocalState.localStorage, {});
  assert.deepEqual(thin.snapshot.persistedLocalState.workflowNodeStates, {});
  assert.equal(thin.snapshot.persistedLocalState.datasetPreview, undefined);
  assert.equal(thin.snapshot.restoreWarnings.length > 0, true);
});

test("predictive project snapshot save and restore does not rehydrate regulated artifacts", () => {
  resetStorage();
  seedPredictiveArtifacts();
  const record = modules.localProjects.upsertProjectSnapshot(predictiveSnapshot());
  assert.equal(modules.localProjects.loadLocalProjects().length, 1);

  localStorage.removeItem("modeling-tool-project-context");
  sessionStorage.removeItem("modeling-tool-dataset");
  localStorage.removeItem("atlas-workflow-node-state:predictive-test:step09");

  const warnings = modules.localProjects.restoreLocalProjectArtifacts(record.snapshot);
  assert.equal(localStorage.getItem("modeling-tool-project-context"), null);
  assert.equal(sessionStorage.getItem("modeling-tool-dataset"), null);
  assert.equal(localStorage.getItem("atlas-workflow-node-state:predictive-test:step09"), null);
  assert.equal(warnings.some((warning) => warning.includes("regulated data")), true);
});

test("experimental design snapshot save and restore leaves page artifacts out of localStorage", () => {
  resetStorage();
  seedExperimentalArtifacts();
  const record = modules.localProjects.upsertProjectSnapshot(experimentalSnapshot());

  localStorage.removeItem("atlas-workflow-node-state:experimental-test:experimental-design-3");
  localStorage.removeItem("atlas-workflow-node-state:experimental-test:experimental-design-8");

  const warnings = modules.localProjects.restoreLocalProjectArtifacts(record.snapshot);
  assert.equal(localStorage.getItem("atlas-workflow-node-state:experimental-test:experimental-design-3"), null);
  assert.equal(localStorage.getItem("atlas-workflow-node-state:experimental-test:experimental-design-8"), null);
  assert.equal(warnings.some((warning) => warning.includes("regulated data")), true);
});

test("corrupted registry and missing artifact references are handled without crashing", () => {
  resetStorage();
  localStorage.setItem("atlas-local-projects", "{not-json");
  assert.deepEqual(modules.localProjects.loadLocalProjects(), []);

  const warnings = modules.persistence.restoreProjectSnapshotArtifacts({
    ...predictiveSnapshot({ projectId: "missing-artifact-test" }),
    persistedLocalState: {
      schemaVersion: 1,
      savedAt: "2026-07-03T00:00:00.000Z",
      localStorage: {},
      sessionStorage: {},
      workflowNodeStates: {},
      missingArtifacts: ["Model artifact requires rerun."],
      storageEstimateBytes: 12,
    },
  });
  assert.deepEqual(warnings, ["Model artifact requires rerun."]);
});

test("artifact restore summaries classify compact restore status", () => {
  const summary = modules.artifactStorage.summarizeArtifactRestore({
    ...experimentalSnapshot(),
    persistedLocalState: {
      workflowNodeStates: {
        "experimental-design-8": { simulationResults: { meanPower: 0.81, powerByIteration: [] } },
      },
      missingArtifacts: [],
    },
  });
  assert.equal(summary.status, "simulation_summary_only");
  assert.equal(summary.label, "Restored with simulation summary only");
});

test("project import validation rejects invalid imports and accepts valid snapshots", () => {
  const invalid = modules.projectImportValidation.validateProjectImport({ projectName: "", projectType: "not-real" });
  assert.equal(invalid.ok, false);
  assert.equal(invalid.errors.length > 0, true);

  const valid = modules.projectImportValidation.validateProjectImport(experimentalSnapshot({ currentStepId: "does-not-exist" }));
  assert.equal(valid.ok, true);
  assert.equal(valid.snapshot.projectName, "Experimental Persistence Test");
  assert.equal(valid.snapshot.currentStepId, "experimental-design-1");
  assert.equal(valid.warnings.length > 0, true);
});

test("Recent Projects repair recovers legacy workflow evidence", () => {
  resetStorage();
  setJson(localStorage, "atlas-workflow-node-state:legacy-exp:experimental-design-3", {
    objective: "Pricing Strategy\n- Current\n- Personalized",
    decision: "Factors documented.",
  });
  const migration = modules.localProjects.migrateLegacyLocalProjects();
  const projects = modules.localProjects.loadLocalProjects();
  assert.equal(migration.migrated, 1);
  assert.equal(migration.recoveredExperimentalDesign, true);
  assert.equal(projects[0].projectId, "legacy-exp");
  assert.equal(projects[0].projectType, "experimental-design");
});

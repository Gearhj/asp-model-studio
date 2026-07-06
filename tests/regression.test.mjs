import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/regression-tests", import.meta.url));

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
  requestAnimationFrame(callback) {
    callback();
  },
  scrollTo() {},
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

function setJson(storage, key, value) {
  storage.setItem(key, JSON.stringify(value));
}

function estimateBytes(value) {
  return new TextEncoder().encode(typeof value === "string" ? value : JSON.stringify(value)).length;
}

function predictiveSnapshot(overrides = {}) {
  const workflow = modules.workflows.getWorkflowDefinition("predictive-modeling");
  return {
    projectId: "regression-predictive",
    modelId: "15211",
    projectName: "Regression Predictive Project",
    projectType: "predictive-modeling",
    workflowId: workflow.id,
    workflowSteps: workflow.steps.map((step, index) => ({ ...step, status: index < 2 ? "complete" : "pending" })),
    currentStepId: "step00",
    hasDataset: true,
    ...overrides,
  };
}

function seedLargeArtifacts(projectId = "regression-predictive") {
  setJson(localStorage, "modeling-tool-project-context", {
    projectName: "Regression Predictive Project",
    businessObjective: "x".repeat(6000),
    targetDefinition: "Class is the target.",
  });
  setJson(localStorage, "modeling-tool-decision-journal", Array.from({ length: 250 }, (_, index) => ({
    timestamp: `2026-07-03T12:${String(index % 60).padStart(2, "0")}:00.000Z`,
    workflowStep: "Model Training",
    actionType: "changed",
    subject: `entry-${index}`,
    previousValue: "x".repeat(200),
    newValue: "y".repeat(200),
  })));
  setJson(localStorage, `atlas-workflow-node-state:${projectId}:step09`, {
    objective: "Interpret model",
    analysisSnapshot: { large: "z".repeat(100000) },
    simulationResults: {
      powerByIteration: Array.from({ length: 2000 }, (_, index) => ({ achievedPower: index / 2000, estimatedLift: index / 100000 })),
    },
  });
  setJson(sessionStorage, "modeling-tool-dataset", {
    headers: ["Class", "Amount", "V1", "V2"],
    target: "Class",
    selected_columns: ["Amount", "V1", "V2"],
    problem_type: "classification",
    rows: Array.from({ length: 5000 }, (_, index) => ({ Class: index % 100 === 0 ? 1 : 0, Amount: index, V1: index / 10, V2: index / 20 })),
  });
}

test("Recent Projects registry entry remains small and references project-scoped snapshot", () => {
  resetStorage();
  seedLargeArtifacts();
  modules.localProjects.upsertProjectSnapshot(predictiveSnapshot());
  const registryRaw = localStorage.getItem(modules.localProjects.LOCAL_PROJECTS_KEY);
  assert.ok(registryRaw);
  assert.equal(registryRaw.includes("persistedLocalState"), false);
  assert.equal(registryRaw.includes("powerByIteration"), false);
  assert.ok(estimateBytes(registryRaw) < 100 * 1024);
  const registry = JSON.parse(registryRaw);
  assert.equal(registry.length, 1);
  assert.ok(estimateBytes(registry[0]) < 5 * 1024);
  assert.equal(typeof registry[0].snapshotStorageKey, "string");
  assert.ok(localStorage.getItem(`${modules.localProjects.PROJECT_SNAPSHOT_KEY_PREFIX}${registry[0].projectId}`));
});

test("Project Context to Data Acquisition save uses route-aware current step without quota-sized registry", () => {
  resetStorage();
  seedLargeArtifacts();
  window.location.pathname = "/step00";
  const result = modules.localProjects.saveActiveProjectBeforeNavigation(predictiveSnapshot({ currentStepId: "dashboard" }));
  assert.equal(result.ok, true);
  const projects = modules.localProjects.loadLocalProjects();
  assert.equal(projects.length, 1);
  assert.equal(projects[0].snapshot.currentStepId, "step00");
  assert.ok(estimateBytes(localStorage.getItem(modules.localProjects.LOCAL_PROJECTS_KEY)) < 100 * 1024);
});

test("save-before-navigation falls back to thin snapshot if compact artifact save is too large", () => {
  resetStorage();
  seedLargeArtifacts();
  const originalSetItem = localStorage.setItem.bind(localStorage);
  localStorage.setItem = (key, value) => {
    if (String(key).startsWith(modules.localProjects.PROJECT_SNAPSHOT_KEY_PREFIX) && String(value).length > 50000) {
      throw new Error("quota");
    }
    originalSetItem(key, value);
  };
  const result = modules.localProjects.saveActiveProjectBeforeNavigation(predictiveSnapshot());
  localStorage.setItem = originalSetItem;
  assert.equal(result.ok, true);
  const projects = modules.localProjects.loadLocalProjects();
  assert.equal(projects.length, 1);
  assert.ok(estimateBytes(projects[0].snapshot) <= 50 * 1024 || !projects[0].snapshot.persistedLocalState);
});

test("save-before-navigation replaces an oversized existing project snapshot before fallback", () => {
  resetStorage();
  seedLargeArtifacts();
  const snapshotKey = `${modules.localProjects.PROJECT_SNAPSHOT_KEY_PREFIX}regression-predictive`;
  localStorage.setItem(snapshotKey, "x".repeat(200000));
  const originalSetItem = localStorage.setItem.bind(localStorage);
  localStorage.setItem = (key, value) => {
    if (String(key) === snapshotKey && localStorage.getItem(snapshotKey) && String(value).length < 50000) {
      throw new Error("old oversized value still blocks replacement");
    }
    if (String(key) === snapshotKey && String(value).length > 50000) {
      throw new Error("quota");
    }
    originalSetItem(key, value);
  };
  const result = modules.localProjects.saveActiveProjectBeforeNavigation(predictiveSnapshot());
  localStorage.setItem = originalSetItem;
  assert.equal(result.ok, true);
  const saved = localStorage.getItem(snapshotKey);
  assert.ok(saved);
  assert.ok(saved.length < 50000);
  assert.doesNotMatch(saved, /persistedLocalState/);
});

test("Data Acquisition route uses right-side Atlas Guide layout", async () => {
  const source = await readFile(new URL("../src/apps/ModelingApp.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /location\.pathname === "\/step01" \? "xl:grid-cols-1"/);
  assert.match(source, /xl:grid-cols-\[minmax\(0,1fr\)_320px\]/);
  assert.doesNotMatch(source, /location\.pathname === "\/step01"[\s\S]{0,120}<CopilotCard/);
});

test("Data Acquisition upload handler accepts valid small CSV affordances and rejects invalid extensions inline", async () => {
  const source = await readFile(new URL("../src/steps/Step01_DataAcquisition.tsx", import.meta.url), "utf8");
  const helper = await readFile(new URL("../src/lib/dataAcquisitionUpload.ts", import.meta.url), "utf8");
  assert.match(source, /export function parseCSV/);
  assert.match(helper, /BROWSER_PARSE_EXTENSIONS = new Set\(\["csv", "txt", "json"\]\)/);
  assert.match(helper, /RECOGNIZED_UPLOAD_EXTENSIONS/);
  assert.match(helper, /not an allowed project data file type/);
  assert.match(source, /Dataset preview is saved locally\. Backend sync did not complete/);
});

test("Model Training source allows more than three selectable models and unlocked baselines", async () => {
  const source = await readFile(new URL("../src/steps/Step06_Train.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /selectedModels\.length\s*>=\s*3|maxSelected|maxModel/i);
  assert.doesNotMatch(source, /key === "logreg"[\s\S]{0,120}disabled/);
  assert.doesNotMatch(source, /key === "rf"[\s\S]{0,120}disabled/);
  assert.match(source, /Select at least one model before training/);
  assert.match(source, /models,\s*k_folds/s);
});

test("Go to Evaluation navigates to /step08 with quota-tolerant save", async () => {
  const source = await readFile(new URL("../src/steps/Step06_Train.tsx", import.meta.url), "utf8");
  assert.match(source, /saveActiveProjectBeforeNavigation/);
  assert.match(source, /navigate\("\/step08"\)/);
  assert.match(source, /void recordTrainingExperiments/);
});

test("Feature Engineering respects selected columns from Data Acquisition", async () => {
  const source = await readFile(new URL("../src/steps/Step05_EncodingScaling.tsx", import.meta.url), "utf8");
  assert.match(source, /filterRowsToHeaders/);
  assert.match(source, /localDataset\?\.headers\.length/);
  assert.match(source, /allowedHeaders\.has\(column\.name\)/);
});

test("Model Training includes Decision Tree Regressor baseline and regression grid search", async () => {
  const frontend = await readFile(new URL("../src/steps/Step06_Train.tsx", import.meta.url), "utf8");
  const backend = await readFile(new URL("../server/training/trainer.py", import.meta.url), "utf8");

  assert.match(frontend, /dt_reg/);
  assert.match(frontend, /Decision Tree Regressor/);
  assert.match(frontend, /DEFAULT_REGRESSION_SELECTION[\s\S]*dt_reg:\s*true/);
  assert.match(backend, /DecisionTreeRegressor/);
  assert.match(backend, /"dt_reg"/);
  assert.match(backend, /neg_root_mean_squared_error/);
});

test("Predictive workflow uses regression-safe labels and metrics", async () => {
  const projectContext = await readFile(new URL("../src/steps/Step00_ProjectContext.tsx", import.meta.url), "utf8");
  const dataAcquisition = await readFile(new URL("../src/steps/Step01_DataAcquisition.tsx", import.meta.url), "utf8");
  const balancing = await readFile(new URL("../src/steps/Step06_BalancingSplit.tsx", import.meta.url), "utf8");
  const scoring = await readFile(new URL("../src/steps/Step10_Scoring.tsx", import.meta.url), "utf8");
  const modelDocument = await readFile(new URL("../src/lib/modelDevelopmentDocument.ts", import.meta.url), "utf8");

  assert.match(projectContext, /Overprediction cost/);
  assert.match(projectContext, /Underprediction cost/);
  assert.match(dataAcquisition, /Corr\(Target\)/);
  assert.match(dataAcquisition, /Target Mean/);
  assert.match(dataAcquisition, /props\.targetInfo\.kind === "continuous"/);
  assert.match(balancing, /Regression Split Validation/);
  assert.match(balancing, /Balancing, SMOTE, class weights, and event-rate controls are not applicable/);
  assert.match(scoring, /External Validation Dataset/);
  assert.match(scoring, /Out-of-Time Dataset/);
  assert.match(modelDocument, /Overprediction cost/);
  assert.match(modelDocument, /Not applicable for continuous-target regression/);
});

test("Interpretation renders structured decision tree logic instead of raw tree dump", async () => {
  const source = await readFile(new URL("../src/steps/Step09_Interpretation.tsx", import.meta.url), "utf8");
  assert.match(source, /\/eval\/tree\?model=/);
  assert.match(source, /DecisionTreeExplanation/);
  assert.match(source, /Terminal Decision Rules/);
  assert.match(source, /Decision Path Diagram/);
});

test("Interpretation has task-aware regression coefficient and tree displays", async () => {
  const source = await readFile(new URL("../src/steps/Step09_Interpretation.tsx", import.meta.url), "utf8");
  const evalService = await readFile(new URL("../server/evaluation/eval_service.py", import.meta.url), "utf8");

  assert.match(source, /Regression Equation/);
  assert.match(source, /Linear Regression Statistical Output/);
  assert.match(source, /Coefficient Inference Table/);
  assert.match(source, /Diagnostic Notes/);
  assert.match(source, /Not available/);
  assert.match(source, /CoefficientTable/);
  assert.match(source, /Model Fit Summary/);
  assert.match(source, /p Value/);
  assert.match(source, /95% CI Lower/);
  assert.match(source, /LinearRegressionInterpretationReadout/);
  assert.match(source, /Root Prediction/);
  assert.match(source, /Prediction \$/);
  assert.match(evalService, /model_type/);
  assert.match(evalService, /prediction_value/);
  assert.match(evalService, /_linear_regression_inference/);
  assert.match(evalService, /standard_error/);
  assert.match(evalService, /p_value/);
  assert.match(evalService, /confidence_interval_lower/);
  assert.match(evalService, /confidence_interval_upper/);
  assert.match(evalService, /standardized_weight/);
  assert.match(evalService, /residual_standard_error/);
  assert.match(evalService, /f_statistic/);
  assert.match(evalService, /condition_number/);
  assert.match(evalService, /Statistical inference unavailable because the transformed design matrix is singular/);
  assert.match(evalService, /Statistical inference unavailable because SciPy is unavailable/);
  assert.match(evalService, /scipy_stats/);
});

test("Linear Regression interpretation path is scoped to current project and rejects stale artifacts", async () => {
  const trainPage = await readFile(new URL("../src/steps/Step06_Train.tsx", import.meta.url), "utf8");
  const evalPage = await readFile(new URL("../src/steps/Step08_Evaluation.tsx", import.meta.url), "utf8");
  const interpretationPage = await readFile(new URL("../src/steps/Step09_Interpretation.tsx", import.meta.url), "utf8");
  const trainerService = await readFile(new URL("../server/training/trainer_service.py", import.meta.url), "utf8");
  const trainerRouter = await readFile(new URL("../server/training/trainer_router.py", import.meta.url), "utf8");
  const evalRouter = await readFile(new URL("../server/evaluation/eval_router.py", import.meta.url), "utf8");
  const evalService = await readFile(new URL("../server/evaluation/eval_service.py", import.meta.url), "utf8");
  const resultStore = await readFile(new URL("../server/core/result_store.py", import.meta.url), "utf8");

  assert.match(trainPage, /project_id:\s*projectId/);
  assert.match(trainPage, /dataset_version:\s*localDatasetVersion\(currentDataset\)/);
  assert.match(trainPage, /target:\s*currentDataset\?\.target/);
  assert.match(trainPage, /problem_type:\s*trainingProblemType/);
  assert.match(evalPage, /LOCAL_SELECTED_INTERPRETATION_MODEL_KEY/);
  assert.match(evalPage, /sessionStorage\.setItem\(LOCAL_SELECTED_INTERPRETATION_MODEL_KEY,\s*selected\)/);
  assert.match(interpretationPage, /interpretationContextQuery/);
  assert.match(interpretationPage, /project_id/);
  assert.match(interpretationPage, /dataset_version/);
  assert.match(interpretationPage, /LinearRegressionDebugPanel/);
  assert.match(interpretationPage, /artifact_has_metadata/);
  assert.match(trainerRouter, /project_id = str\(request\.get\("project_id"\)/);
  assert.match(trainerService, /artifact_metadata/);
  assert.match(trainerService, /training_run_id/);
  assert.match(resultStore, /model_artifact_metadata/);
  assert.match(resultStore, /get_model_artifact_metadata/);
  assert.match(evalRouter, /\/interpretation\/debug/);
  assert.match(evalService, /_artifact_context_mismatch/);
  assert.match(evalService, /The selected model artifact does not match the current/);
  assert.match(evalService, /Please retrain/);
});

test("Model Development Document summarizes material predictive decisions by default", async () => {
  const modelDocument = await readFile(new URL("../src/lib/modelDevelopmentDocument.ts", import.meta.url), "utf8");
  const documentPage = await readFile(new URL("../src/steps/Step11_ModelDevelopmentDocument.tsx", import.meta.url), "utf8");

  assert.match(modelDocument, /summarizeMaterialReportDecisions/);
  assert.match(modelDocument, /formatMaterialDecisionTable/);
  assert.match(modelDocument, /Decision Area/);
  assert.match(modelDocument, /Final Decision/);
  assert.match(modelDocument, /Owner \/ Source/);
  assert.match(modelDocument, /includeFullDecisionJournalAppendix/);
  assert.match(modelDocument, /Full Audit Appendix/);
  assert.match(modelDocument, /mode === "governance"/);
  assert.match(modelDocument, /mode === "executive"\s*\?\s*\[\]/);
  assert.doesNotMatch(modelDocument, /mode !== "executive"[\s\S]{0,160}formatDecisions\(decisions\)/);
  assert.doesNotMatch(modelDocument, /title: "Material Decision Summary"[\s\S]{0,160}formatDecisions\(materialDecisions\)/);
  assert.match(documentPage, /Include Full Decision Journal Appendix/);
});

test("Open Project and Experimental Design project restore still load through existing APIs", () => {
  resetStorage();
  const workflow = modules.workflows.getWorkflowDefinition("experimental-design");
  const record = modules.localProjects.upsertProjectSnapshot({
    projectId: "regression-experimental",
    modelId: "4520",
    projectName: "Regression Experimental Project",
    projectType: "experimental-design",
    workflowId: workflow.id,
    workflowSteps: workflow.steps.map((step, index) => ({ ...step, status: index < 4 ? "complete" : "pending" })),
    currentStepId: "experimental-design-4",
    hasDataset: false,
  });
  const projects = modules.localProjects.loadLocalProjects();
  assert.equal(projects.length, 1);
  assert.equal(projects[0].projectId, "regression-experimental");
  const warnings = modules.localProjects.restoreLocalProjectArtifacts(record.snapshot);
  assert.equal(Array.isArray(warnings), true);
});

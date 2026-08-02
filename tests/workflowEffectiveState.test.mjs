import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import test, { after } from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TEMP = await mkdtemp(path.join(tmpdir(), "atlas-effective-workflow-"));

after(async () => {
  await rm(TEMP, { recursive: true, force: true });
});

const source = await readFile(new URL("src/lib/workflowEffectiveState.ts", ROOT), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
    importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
  },
}).outputText;
const modulePath = path.join(TEMP, "workflowEffectiveState.mjs");
await writeFile(modulePath, output, "utf8");
const lib = await import(pathToFileURL(modulePath).href);

const IDENTITY = {
  project_id: "atlas-project",
  dataset_id: "dataset-heloc",
  dataset_version_id: "version-registered-1",
  activation_revision: 7,
};

const steps = Array.from({ length: 14 }, (_, index) => ({
  id: `step${String(index).padStart(2, "0")}`,
  label: `Step ${index}`,
  route: `/step${String(index).padStart(2, "0")}`,
  description: "Synthetic workflow step",
  status: "complete",
}));

function view(overrides = {}) {
  return lib.deriveEffectiveWorkflowView({
    workflowSteps: steps,
    projectType: "predictive-modeling",
    datasetIdentity: IDENTITY,
    backendState: null,
    ...overrides,
  });
}

function backend({ identity = IDENTITY, validity = "current", completed = ["step00", "step01", "step02"] } = {}) {
  return {
    historicalCompletedSteps: steps.map((step) => step.id),
    effectiveCompletedSteps: completed,
    effectiveCurrentStepId: "step03",
    workflowStatus: {
      datasetIdentity: identity,
      identityValidity: {
        status: validity,
        activationRevision: 7,
      },
      effectiveSteps: Object.fromEntries(completed.map((stepId) => [stepId, {
        effectiveStatus: "complete",
        lineageStatus: "current",
      }])),
    },
  };
}

test("historical completion is preserved but cannot grant predictive validity", () => {
  const result = view();
  assert.equal(result.authoritative, false);
  assert.equal(result.effectiveCompletedSteps.length, 0);
  assert.equal(result.effectiveCurrentStepId, "step01");
  assert.ok(result.effectiveWorkflowSteps.every((step) => step.status === "pending"));
  assert.ok(steps.every((step) => step.status === "complete"), "history must remain unchanged");
});

test("a browser PUT-shaped legacy workflow payload cannot grant effective completion", () => {
  const result = view({
    backendState: {
      completedSteps: steps.map((step) => step.id),
      currentStepId: "step13",
      workflowStatus: {
        datasetIdentity: IDENTITY,
        steps: Object.fromEntries(steps.map((step) => [step.id, "complete"])),
      },
    },
  });
  assert.equal(result.historicalCompletedSteps.length, steps.length);
  assert.equal(result.authoritative, false);
  assert.equal(result.effectiveCompletedSteps.length, 0);
  assert.equal(result.effectiveCurrentStepId, "step01");
});

test("same exact active identity accepts backend effective completion only", () => {
  const result = view({ backendState: backend() });
  assert.equal(result.authoritative, true);
  assert.equal(result.identityValidity, "current");
  assert.deepEqual(result.effectiveCompletedSteps, ["step00", "step01", "step02"]);
  assert.equal(result.effectiveCurrentStepId, "step03");
  assert.equal(result.historicalCompletedSteps.length, 14);
});

test("effectiveSteps cannot grant completion when the authoritative completed list omits it", () => {
  const state = backend({ completed: ["step00", "step01"] });
  state.workflowStatus.effectiveSteps.step07 = {
    effectiveStatus: "complete",
    lineageStatus: "current",
  };
  const result = view({ backendState: state });
  assert.deepEqual(result.effectiveCompletedSteps, ["step00", "step01"]);
  assert.equal(result.effectiveWorkflowSteps.find((step) => step.id === "step07")?.status, "pending");
});

test("workflow-state GET may carry effective fields inside workflowStatus", () => {
  const state = backend();
  const nested = {
    completedSteps: state.historicalCompletedSteps,
    workflowStatus: {
      ...state.workflowStatus,
      historicalCompletedSteps: state.historicalCompletedSteps,
      effectiveCompletedSteps: state.effectiveCompletedSteps,
      effectiveCurrentStepId: state.effectiveCurrentStepId,
    },
  };
  const result = view({ backendState: nested });
  assert.equal(result.authoritative, true);
  assert.deepEqual(result.effectiveCompletedSteps, ["step00", "step01", "step02"]);
  assert.equal(result.effectiveCurrentStepId, "step03");
});

test("different backend version fails every dataset-dependent step closed", () => {
  const result = view({
    backendState: backend({
      identity: { ...IDENTITY, dataset_version_id: "version-other" },
      completed: steps.map((step) => step.id),
    }),
  });
  assert.equal(result.effectiveWorkflowSteps.find((step) => step.id === "step00")?.status, "complete");
  assert.ok(
    result.effectiveWorkflowSteps
      .filter((step) => step.id !== "step00")
      .every((step) => step.status === "pending"),
  );
  assert.equal(result.effectiveCurrentStepId, "step01", "contradictory identity resumes at explicit reactivation");
});

test("a stale workflow activation revision cannot race a newer active identity", () => {
  const result = view({
    datasetIdentity: { ...IDENTITY, activation_revision: 8 },
    backendState: backend({ completed: steps.map((step) => step.id) }),
  });
  assert.equal(result.authoritative, true);
  assert.equal(result.effectiveWorkflowSteps.find((step) => step.id === "step00")?.status, "complete");
  assert.ok(
    result.effectiveWorkflowSteps
      .filter((step) => step.id !== "step00")
      .every((step) => step.status === "pending"),
  );
  assert.equal(result.effectiveCurrentStepId, "step01");
});

test("a current workflow requires an authoritative positive activation revision", () => {
  const result = view({
    datasetIdentity: {
      project_id: IDENTITY.project_id,
      dataset_id: IDENTITY.dataset_id,
      dataset_version_id: IDENTITY.dataset_version_id,
    },
    backendState: backend(),
  });
  assert.deepEqual(result.effectiveCompletedSteps, ["step00"]);
  assert.equal(result.effectiveCurrentStepId, "step01");
});

test("missing or stale identity cannot be promoted by effectiveCompletedSteps", () => {
  const missing = view({ datasetIdentity: null, backendState: backend() });
  const stale = view({ backendState: backend({ validity: "stale", completed: steps.map((step) => step.id) }) });
  for (const result of [missing, stale]) {
    assert.ok(
      result.effectiveWorkflowSteps
        .filter((step) => step.id !== "step00")
        .every((step) => step.status === "pending"),
    );
  }
});

test("a stale per-step lineage record overrides a nominal complete status", () => {
  const state = backend();
  state.workflowStatus.effectiveSteps.step02 = {
    effectiveStatus: "complete",
    lineageStatus: "stale",
  };
  const result = view({ backendState: state });
  assert.equal(result.effectiveWorkflowSteps.find((step) => step.id === "step02")?.status, "pending");
});

test("non-predictive workflows retain compatibility when no effective contract exists", () => {
  const result = view({ projectType: "experimental-design", datasetIdentity: null });
  assert.equal(result.effectiveCompletedSteps.length, steps.length);
});

test("all shared progress and resume surfaces consume the effective view", async () => {
  const [store, app, sidebar, dashboard, overview, projects, persistence, step01, datasets] = await Promise.all([
    readFile(new URL("src/state/useWorkflowStore.ts", ROOT), "utf8"),
    readFile(new URL("src/apps/ModelingApp.tsx", ROOT), "utf8"),
    readFile(new URL("src/components/Sidebar.tsx", ROOT), "utf8"),
    readFile(new URL("src/steps/Dashboard.tsx", ROOT), "utf8"),
    readFile(new URL("src/steps/ProjectOverview.tsx", ROOT), "utf8"),
    readFile(new URL("src/steps/ProjectUtilityPages.tsx", ROOT), "utf8"),
    readFile(new URL("src/lib/serverPersistence.ts", ROOT), "utf8"),
    readFile(new URL("src/steps/Step01_DataAcquisition.tsx", ROOT), "utf8"),
    readFile(new URL("src/lib/datasetLibrary.ts", ROOT), "utf8"),
  ]);

  for (const surface of [app, sidebar, dashboard, overview]) {
    assert.match(surface, /selectEffectiveWorkflowSteps/);
  }
  assert.doesNotMatch(overview, /Math\.max\(completed,\s*backendCompletedSteps\)/);
  assert.match(projects, /projectEffectiveWorkflow\(project\)/);
  assert.match(projects, /effective\.effectiveCurrentStepId/);
  assert.match(projects, /authoritativeWorkflowReadinessByProject\.get\(project\.projectId\)/);
  assert.doesNotMatch(
    projects,
    /function backendWorkflowReadiness\(project:[\s\S]*?return project\.backendMetadata/,
    "browser/imported backendMetadata must not grant authoritative readiness",
  );
  assert.match(store, /partialize:[\s\S]*effectiveWorkflowSteps:/);
  assert.match(persistence, /historicalCompletedSteps:\s*completedSteps/);
  assert.doesNotMatch(persistence, /effectiveCompletedSteps:\s*completedSteps/);
  assert.match(step01, /explicit-dataset-reactivation-required/);
  assert.doesNotMatch(step01.slice(
    step01.indexOf("const restoreExactIdentity = async () =>"),
    step01.indexOf("void restoreExactIdentity();"),
  ), /activateDatasetVersion\(/);
  assert.match(datasets, /requireDurableDatasetActivation/);
  assert.match(datasets, /link_status !== "active"/);
  assert.match(datasets, /activation_status !== "active"/);
});

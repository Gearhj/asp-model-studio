import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/sqlite-persistence-tests", import.meta.url));

async function transpile(sourcePath, outputPath) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  let output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  output = output.replace(/from\s+["'](\.{1,2}\/[^"']+)["']/g, (match, specifier) =>
    specifier.endsWith(".js") ? match : match.replace(specifier, `${specifier}.js`)
  );
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, output, "utf8");
}

await rm(TMP_DIR, { recursive: true, force: true });
const evidenceStatusContract = await readFile(new URL("shared/evidence_status_contract.json", ROOT), "utf8");
await mkdir(path.join(TMP_DIR, "shared"), { recursive: true });
await writeFile(path.join(TMP_DIR, "shared/evidence_status_contract.json.js"), `export default ${evidenceStatusContract};\n`, "utf8");
await transpile("src/lib/api.ts", path.join(TMP_DIR, "src/lib/api.js"));
await transpile("src/lib/projectPersistence.ts", path.join(TMP_DIR, "src/lib/projectPersistence.js"));
await transpile("src/config/optimizationTemplates.ts", path.join(TMP_DIR, "src/config/optimizationTemplates.js"));
await transpile("src/lib/serverPersistence.ts", path.join(TMP_DIR, "src/lib/serverPersistence.js"));
await transpile("src/lib/persistedEvidenceStatus.ts", path.join(TMP_DIR, "src/lib/persistedEvidenceStatus.js"));

const events = [];
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};
globalThis.window = { dispatchEvent: (event) => events.push(event) };

const persistence = await import(pathToFileURL(path.join(TMP_DIR, "src/lib/serverPersistence.js")).href);
const evidenceStatus = await import(pathToFileURL(path.join(TMP_DIR, "src/lib/persistedEvidenceStatus.js")).href);

test("persisted evidence readiness distinguishes generated, captured, ready, and approved", () => {
  const summary = evidenceStatus.summarizePersistedEvidence([
    { artifactType: "objective", status: "generated" },
    { artifactType: "constraints", status: "captured" },
    { artifactType: "validation", status: "ready" },
    { artifactType: "recommendation", status: "approved" },
  ]);
  assert.equal(summary.coverageScore, 63);
  assert.equal(summary.capturedCount, 3);
  assert.equal(summary.readyCount, 2);
  assert.equal(summary.approvedCount, 1);
  assert.equal(summary.packageReady, false);
  assert.match(summary.statusLabel, /ready/);
  assert.equal(evidenceStatus.persistedEvidenceStatusToLegacy("captured"), "ready");
  assert.equal(evidenceStatus.persistedEvidenceStatusToLegacy("stale"), "deprecated");
});

test("backend failure preserves the local fallback and emits Backend unavailable", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };
  const ok = await persistence.saveProjectToDatabase({
    projectId: "fallback-project",
    modelId: "00001",
    projectName: "Fallback Project",
    projectType: "predictive-modeling",
    workflowId: "predictive-modeling",
    workflowSteps: [{ id: "step00", status: "complete" }],
    currentStepId: "step01",
    hasDataset: false,
  });
  assert.equal(ok, false);
  const last = events.at(-1)?.detail;
  assert.equal(last.status, "backend_unavailable");
  assert.match(last.message, /local browser persistence/i);
});

test("project mirror writes project before workflow state and reports database success", async () => {
  events.length = 0;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, method: init.method, body: JSON.parse(init.body) });
    return { ok: true, json: async () => ({ ok: true }) };
  };
  const ok = await persistence.saveProjectToDatabase({
    projectId: "database-project",
    modelId: "00002",
    projectName: "Database Project",
    projectType: "optimization",
    workflowId: "optimization",
    workflowSteps: [
      { id: "optimization-1", status: "complete" },
      { id: "optimization-2", status: "in_progress" },
    ],
    currentStepId: "optimization-2",
    hasDataset: true,
    templateId: "transportation_logistics",
  });
  assert.equal(ok, true);
  assert.equal(calls.length, 2);
  assert.match(calls[0].url, /\/api\/projects\/database-project$/);
  assert.match(calls[1].url, /workflow-state$/);
  assert.equal(calls[0].body.templateId, "transportation_logistics");
  assert.deepEqual(calls[1].body.completedSteps, ["optimization-1"]);
  assert.equal(events.at(-1).detail.status, "database_saved");
});

test("workflow completion snapshot advances a copied snapshot without mutating browser state", () => {
  const original = {
    projectId: "completion-project",
    modelId: "00003",
    projectName: "Completion Project",
    projectType: "predictive-modeling",
    workflowId: "predictive-modeling",
    workflowSteps: [
      { id: "step10", route: "/step10", status: "in_progress" },
      { id: "step11", route: "/step11", status: "pending" },
    ],
    currentStepId: "step10",
    hasDataset: true,
  };
  const completed = persistence.workflowCompletionSnapshot(original, "step10", "step11");

  assert.notEqual(completed, original);
  assert.equal(completed.currentStepId, "step11");
  assert.equal(completed.workflowSteps[0].status, "complete");
  assert.equal(completed.workflowSteps[1].status, "pending");
  assert.equal(original.currentStepId, "step10");
  assert.equal(original.workflowSteps[0].status, "in_progress");
});

test("durable workflow completion does not resolve before the authoritative PUT", async () => {
  const calls = [];
  let releaseResponse;
  let requestStarted;
  const started = new Promise((resolve) => {
    requestStarted = resolve;
  });
  globalThis.fetch = (url, init) => {
    calls.push({ url, method: init.method, body: JSON.parse(init.body) });
    requestStarted();
    return new Promise((resolve) => {
      releaseResponse = () => resolve({ ok: true, json: async () => ({ ok: true }) });
    });
  };
  const snapshot = persistence.workflowCompletionSnapshot({
    projectId: "durable-completion-project",
    modelId: "00004",
    projectName: "Durable Completion Project",
    projectType: "predictive-modeling",
    workflowId: "predictive-modeling",
    workflowSteps: [
      { id: "step12", route: "/step12", status: "in_progress" },
      { id: "step13", route: "/step13", status: "pending" },
    ],
    currentStepId: "step12",
    hasDataset: true,
  }, "step12", "step13");
  let settled = false;
  const pending = persistence.saveWorkflowStateToDatabase(snapshot).then((result) => {
    settled = true;
    return result;
  });

  await started;
  assert.equal(settled, false);
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /\/api\/projects\/durable-completion-project\/workflow-state$/);
  assert.equal(calls[0].method, "PUT");
  assert.equal(calls[0].body.currentStepId, "step13");
  assert.deepEqual(calls[0].body.completedSteps, ["step12"]);

  releaseResponse();
  assert.equal(await pending, true);
  assert.equal(settled, true);
});

test("required workflow completion succeeds only when the backend confirms current effective state", async () => {
  events.length = 0;
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      ok: true,
      workflowState: {
        workflowStatus: {
          effectiveCompletedSteps: ["step12"],
          effectiveSteps: {
            step12: {
              effectiveStatus: "complete",
              lineageStatus: "current",
            },
          },
        },
      },
    }),
  });

  const ok = await persistence.saveWorkflowStateToDatabase({
    projectId: "effective-completion-project",
    modelId: "00005",
    projectName: "Effective Completion Project",
    projectType: "predictive-modeling",
    workflowId: "predictive-modeling",
    workflowSteps: [{ id: "step12", route: "/step12", status: "complete" }],
    currentStepId: "step13",
    hasDataset: true,
  }, "step12");

  assert.equal(ok, true);
  assert.equal(events.at(-1)?.detail?.status, "database_saved");
});

test("HTTP 200 historical workflow status cannot unlock forward navigation", async () => {
  events.length = 0;
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      ok: true,
      workflowState: {
        workflowStatus: {
          effectiveCompletedSteps: [],
          effectiveSteps: {
            step12: {
              effectiveStatus: "pending",
              lineageStatus: "stale",
            },
          },
        },
      },
    }),
  });

  const ok = await persistence.saveWorkflowStateToDatabase({
    projectId: "historical-only-project",
    modelId: "00006",
    projectName: "Historical Only Project",
    projectType: "predictive-modeling",
    workflowId: "predictive-modeling",
    workflowSteps: [{ id: "step12", route: "/step12", status: "complete" }],
    currentStepId: "step13",
    hasDataset: true,
  }, "step12");

  assert.equal(ok, false);
  assert.equal(events.at(-1)?.detail?.status, "database_save_failed");
  assert.match(events.at(-1)?.detail?.message ?? "", /canonical completion evidence/i);
});

test("template changes and client-only exports persist explicit backend contracts", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, method: init.method, body: JSON.parse(init.body) });
    return { ok: true, json: async () => ({ ok: true }) };
  };
  await persistence.saveProjectTemplateToDatabase("transport-project", "transportation_logistics");
  await persistence.saveExportToDatabase("transport-project", {
    exportId: "export-json",
    exportType: "governed_json",
    fileName: "optimization-study.json",
    artifactHash: "sha256-test",
    metadata: { delivery: "browser_download", clientOnly: true, fileExists: false },
  });
  assert.equal(calls[0].body.templateId, "transportation_logistics");
  assert.equal(calls[0].body.metadata.optimizationState, null);
  assert.equal(calls[1].body.filePath, undefined);
  assert.deepEqual(calls[1].body.metadata, { delivery: "browser_download", clientOnly: true, fileExists: false });
});

test("SQLite persistence source contains all required frontend integration points", async () => {
  const [localProjects, evidence, documentation, workflow, optimization, overview, evidenceCenter, openProject, documentationStudio, sidebar, copilot] = await Promise.all([
    readFile(new URL("../src/lib/localProjects.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/evidenceGraph.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/modelDocumentation.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/state/useWorkflowStore.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/features/optimization/TransportationOptimizationWorkflow.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/steps/ProjectOverview.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/steps/EvidenceGraph.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/steps/ProjectUtilityPages.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/steps/ModelDocumentationStudio.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/Sidebar.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/CopilotCard.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(localProjects, /queueProjectDatabaseSave/);
  assert.match(evidence, /saveEvidenceToDatabase/);
  assert.match(documentation, /saveDocumentationToDatabase/);
  assert.match(documentation, /saveExportToDatabase/);
  assert.match(workflow, /persistActiveProject/);
  for (const runType of [
    "optimization_input_normalization",
    "optimization_solver",
    "optimization_scenarios",
    "optimization_sensitivity",
    "optimization_validation",
  ]) assert.match(optimization, new RegExp(runType));
  for (const exportType of [
    "governed_json",
    "allocation_csv",
    "reproducibility_evidence",
    "optimization_report",
    "python_code",
    "sas_compatible_code",
  ]) assert.match(optimization, new RegExp(exportType));
  assert.match(optimization, /readinessScore:\s*status === "complete" \? 100/);
  assert.match(optimization, /sectionCount:\s*DOCUMENTATION_SECTIONS\.length/);
  assert.match(optimization, /const DOCUMENTATION_SECTIONS = \[/);
  assert.match(overview, /getProjectPersistenceBundle/);
  assert.match(overview, /persistenceBundle\?\.evidence/);
  assert.match(overview, /persistenceBundle\?\.documentation/);
  assert.match(evidenceCenter, /getProjectPersistenceBundle/);
  assert.match(overview, /summarizePersistedEvidence/);
  assert.match(evidenceCenter, /summarizePersistedEvidence/);
  assert.match(documentationStudio, /summarizePersistedEvidence/);
  assert.match(sidebar, /optimizationWorkflowStepStatus/);
  assert.match(copilot, /deriveOptimizationEvidenceSummary/);
  assert.match(openProject, /source:\s*"database"/);
  assert.match(openProject, /ATLAS database/);
});

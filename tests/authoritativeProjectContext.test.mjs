import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";
import test, { after } from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TEMP = await mkdtemp(
  path.join(tmpdir(), `atlas-project-context-${randomUUID()}-`),
);

async function transpile(sourcePath, outputName) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
      importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
    },
  }).outputText
    .replace(/from\s+["']\.\/datasetIdentity["'];/g, 'from "./datasetIdentity.mjs";')
    .replace(/from\s+["']\.\.\/config\/workflows["'];/g, 'from "./workflows.mjs";');
  const target = path.join(TEMP, outputName);
  await writeFile(target, output, "utf8");
  return target;
}

after(async () => {
  await rm(TEMP, { recursive: true, force: true });
});

await transpile("src/lib/datasetIdentity.ts", "datasetIdentity.mjs");
await transpile("src/config/workflows.ts", "workflows.mjs");
const modulePath = await transpile(
  "src/lib/authoritativeProjectContext.ts",
  "authoritativeProjectContext.mjs",
);
const context = await import(pathToFileURL(modulePath).href);

const PROJECT_ID = "atlas-project-a";
const DATASET_ID = "dataset-a";
const VERSION_ID = "version-a-001";

function project(overrides = {}) {
  return {
    projectId: PROJECT_ID,
    projectName: "Project A",
    projectType: "predictive-modeling",
    workflowType: "predictive-modeling",
    ownerUserId: "user-a",
    updatedAt: "2026-08-02T12:00:00Z",
    metadata: {
      modelId: "model-a",
      projectContextRevision: "1785186305905-context",
      projectContextSavedAt: "2026-08-02T12:00:30Z",
      projectContext: {
        projectName: "Project A",
        modelId: "model-a",
        businessObjective: "Governed fixture objective",
      },
    },
    activeSelection: {
      projectId: PROJECT_ID,
      datasetId: DATASET_ID,
      datasetVersionId: VERSION_ID,
    },
    ...overrides,
  };
}

function workflow(overrides = {}) {
  return {
    projectId: PROJECT_ID,
    currentStepId: "step01",
    updatedAt: "2026-08-02T12:01:00Z",
    workflowStatus: {
      workflowId: "predictive-modeling",
      projectType: "predictive-modeling",
      datasetIdentity: {
        project_id: PROJECT_ID,
        dataset_id: DATASET_ID,
        dataset_version_id: VERSION_ID,
      },
      steps: { step00: "complete", step01: "in_progress" },
    },
    ...overrides,
  };
}

function identity(overrides = {}) {
  return {
    ok: true,
    project_id: PROJECT_ID,
    dataset_id: DATASET_ID,
    dataset_version_id: VERSION_ID,
    activation_revision: 1,
    ...overrides,
  };
}

function resolve(overrides = {}) {
  return context.resolveAuthoritativeProjectContext({
    routeProjectId: PROJECT_ID,
    projectPayload: project(),
    workflowState: workflow(),
    activeIdentityPayload: identity(),
    requireWorkflow: true,
    requireActiveIdentity: true,
    loadedAt: "2026-08-02T12:02:00Z",
    ...overrides,
  });
}

test("authoritative context exposes explicit resolving and failure states", () => {
  assert.deepEqual(context.AUTHORITATIVE_PROJECT_CONTEXT_STATUSES, [
    "idle",
    "resolving",
    "ready",
    "not_found",
    "unauthorized",
    "workflow_unavailable",
    "identity_unavailable",
    "contradictory",
    "error",
  ]);
});

test("exact project, workflow, and active identity publish one ready context", () => {
  const result = resolve();
  assert.equal(result.status, "ready");
  assert.equal(result.routeProjectId, PROJECT_ID);
  assert.equal(result.project.projectId, PROJECT_ID);
  assert.equal(result.project.projectName, "Project A");
  assert.equal(result.project.metadataRevision, "1785186305905-context");
  assert.equal(result.project.metadataSavedAt, "2026-08-02T12:00:30Z");
  assert.equal(result.project.projectContext.businessObjective, "Governed fixture objective");
  assert.equal(result.activeDatasetIdentity.project_id, PROJECT_ID);
  assert.equal(result.activeDatasetIdentity.dataset_id, DATASET_ID);
  assert.equal(result.activeDatasetIdentity.dataset_version_id, VERSION_ID);
  assert.equal(result.activeDatasetIdentity.activation_revision, 1);
  assert.equal(result.loadedAt, "2026-08-02T12:02:00Z");
});

test("Credit Risk Studio is an exact predictive-modeling workflow", () => {
  const result = resolve({
    projectPayload: project({ workflowType: "credit-risk-studio" }),
    workflowState: workflow({
      workflowStatus: {
        workflowId: "credit-risk-studio",
        projectType: "predictive-modeling",
        datasetIdentity: {
          project_id: PROJECT_ID,
          dataset_id: DATASET_ID,
          dataset_version_id: VERSION_ID,
        },
      },
    }),
  });
  assert.equal(result.status, "ready");
  assert.equal(result.project.workflowId, "credit-risk-studio");
});

test("a non-predictive or unknown workflow is rejected on predictive routes", () => {
  for (const workflowType of ["ab-testing", "unknown-workflow"]) {
    const result = resolve({ projectPayload: project({ workflowType }) });
    assert.equal(result.status, "contradictory", workflowType);
    assert.match(result.message, /different project or workflow type/i);
  }
});

test("project and workflow-state governed workflow identities must agree", () => {
  const result = resolve({
    projectPayload: project({ workflowType: "credit-risk-studio" }),
    workflowState: workflow(),
  });
  assert.equal(result.status, "contradictory");
  assert.match(result.message, /different governed workflows/i);
});

test("project and workflow-state project types must agree when declared", () => {
  const result = resolve({
    workflowState: workflow({
      workflowStatus: {
        workflowId: "predictive-modeling",
        projectType: "ab-testing",
      },
    }),
  });
  assert.equal(result.status, "contradictory");
  assert.match(result.message, /different governed workflows/i);
});

test("route and project response disagreement fails closed", () => {
  const result = resolve({ projectPayload: project({ projectId: "atlas-project-b" }) });
  assert.equal(result.status, "contradictory");
  assert.match(result.message, /project response/i);
});

test("route and workflow response disagreement fails closed", () => {
  const result = resolve({ workflowState: workflow({ projectId: "atlas-project-b" }) });
  assert.equal(result.status, "contradictory");
  assert.match(result.message, /workflow-state response/i);
});

test("route and active identity disagreement fails closed", () => {
  const result = resolve({
    activeIdentityPayload: identity({ project_id: "atlas-project-b" }),
  });
  assert.equal(result.status, "contradictory");
  assert.match(result.message, /different project/i);
});

test("project active selection cannot disagree with exact active identity", () => {
  const result = resolve({
    projectPayload: project({
      activeSelection: {
        projectId: PROJECT_ID,
        datasetId: "dataset-b",
        datasetVersionId: VERSION_ID,
      },
    }),
  });
  assert.equal(result.status, "contradictory");
  assert.match(result.message, /different dataset versions/i);
});

test("workflow dataset identity cannot disagree with exact active identity", () => {
  const result = resolve({
    workflowState: workflow({
      workflowStatus: {
        datasetIdentity: {
          project_id: PROJECT_ID,
          dataset_id: DATASET_ID,
          dataset_version_id: "version-b",
        },
      },
    }),
  });
  assert.equal(result.status, "contradictory");
});

test("a project dataset claim without an active identity is unavailable", () => {
  const result = resolve({ activeIdentityPayload: null, requireActiveIdentity: false });
  assert.equal(result.status, "identity_unavailable");
  assert.equal(result.project.projectId, PROJECT_ID);
});

test("a new project with no dataset claim may hydrate for Data Acquisition", () => {
  const result = resolve({
    projectPayload: project({ activeSelection: null }),
    workflowState: workflow({ workflowStatus: { steps: { step00: "complete" } } }),
    activeIdentityPayload: null,
    requireActiveIdentity: false,
  });
  assert.equal(result.status, "ready");
  assert.equal(result.activeDatasetIdentity, null);
});

test("missing workflow state has a precise controlled status", () => {
  const result = resolve({ workflowState: null });
  assert.equal(result.status, "workflow_unavailable");
  assert.equal(result.project.projectId, PROJECT_ID);
});

test("only explicit project-scoped paths yield a project authority key", () => {
  assert.equal(
    context.projectIdFromScopedPathname(`/projects/${PROJECT_ID}/step01`),
    PROJECT_ID,
  );
  assert.equal(
    context.projectIdFromScopedPathname(`/projects/${PROJECT_ID}/predictive/eda`),
    PROJECT_ID,
  );
  assert.equal(context.projectIdFromScopedPathname("/step01"), null);
  assert.equal(context.projectIdFromScopedPathname("/projects/open/step01"), null);
  assert.equal(context.projectIdFromScopedPathname("/projects/new/step01"), null);
});

test("scoped step parsing and construction preserve the exact encoded project", () => {
  const encoded = context.scopedWorkflowPath("project with spaces", "/step02");
  assert.equal(encoded, "/projects/project%20with%20spaces/step02");
  assert.equal(context.stepIdFromScopedPathname(encoded), "step02");
  assert.equal(
    context.projectIdFromScopedPathname(`/projects/${PROJECT_ID}/step01b`),
    PROJECT_ID,
  );
  assert.equal(
    context.stepIdFromScopedPathname(`/projects/${PROJECT_ID}/step01b`),
    "step01b",
  );
});

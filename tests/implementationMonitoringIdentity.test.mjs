import assert from "node:assert/strict";
import fs from "node:fs";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/implementation-monitoring-identity-tests", import.meta.url));

async function compile(relativePath, outputName, replacements = []) {
  let source = await readFile(new URL(relativePath, ROOT), "utf8");
  for (const [from, to] of replacements) source = source.replaceAll(from, to);
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const outputPath = path.join(TMP_DIR, outputName);
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, output, "utf8");
  return outputPath;
}

await rm(TMP_DIR, { recursive: true, force: true });
const projectContextPath = await compile("src/lib/projectContext.ts", "projectContext.js");
await compile("src/lib/finalModelReadiness.ts", "finalModelReadiness.js");
const identityPath = await compile(
  "src/lib/implementationMonitoringIdentity.ts",
  "implementationMonitoringIdentity.js",
  [
    ['"./finalModelReadiness"', '"./finalModelReadiness.js"'],
    ['"./projectContext"', '"./projectContext.js"'],
  ],
);
const monitoringPath = await compile(
  "src/lib/modelMonitoring.ts",
  "modelMonitoring.js",
  [['"./projectContext"', '"./projectContext.js"']],
);

globalThis.localStorage = {
  _data: new Map(),
  getItem(key) { return this._data.has(key) ? this._data.get(key) : null; },
  setItem(key, value) { this._data.set(key, String(value)); },
  removeItem(key) { this._data.delete(key); },
  clear() { this._data.clear(); },
};

const contextLib = await import(pathToFileURL(projectContextPath).href);
const identityLib = await import(pathToFileURL(identityPath).href);
const monitoringLib = await import(pathToFileURL(monitoringPath).href);

function statusMetadata(overrides = {}) {
  return {
    name: "HELOC governed champion",
    project_id: "project-a",
    dataset_id: "dataset-a",
    training_dataset_id: "dataset-a",
    dataset_version_id: "version-a",
    training_dataset_version_id: "version-a",
    target: "bad_flag",
    target_name: "bad_flag",
    model_id: "model-a",
    model_version_id: "model-version-a",
    candidate_id: "candidate-a",
    training_run_id: "training-run-a",
    feature_manifest_version: "feature-manifest-a",
    validation_design_id: "validation-design-a",
    split_id: "split-a",
    artifact_verified: true,
    artifact_verification_status: "verified",
    artifact_checksum: "sha256:abc",
    promotion_status: "finalized",
    lineage_status: "verified",
    designation: "champion",
    candidate_decision_id: "decision-a",
    evaluation_package_id: "evaluation-a",
    holdout_exposure_id: "holdout-a",
    selection_integrity_status: "verified",
    holdout_isolation_status: "verified",
    evaluation_package_integrity_status: "verified",
    promotion_readiness_status: "verified",
    final_holdout_status: "evaluated",
    ...overrides,
  };
}

const expectedA = {
  projectId: "project-a",
  datasetId: "dataset-a",
  datasetVersion: "version-a",
  target: "bad_flag",
};

function exactIdentity(overrides = {}) {
  const result = identityLib.resolveExactPromotedModelIdentity(
    { ready: true, metadata: statusMetadata(overrides) },
    expectedA,
  );
  assert.equal(result.ready, true, result.error);
  return result.identity;
}

test("resolves the exact durable model and model-version identity", () => {
  const identity = exactIdentity();
  assert.equal(identity.projectId, "project-a");
  assert.equal(identity.modelId, "model-a");
  assert.equal(identity.modelVersionId, "model-version-a");
  assert.equal(identity.datasetVersionId, "version-a");
  assert.equal(identity.candidateId, "candidate-a");
  assert.equal(identity.artifactVerificationStatus, "verified");
});

test("fails closed for a model returned from another project", () => {
  const result = identityLib.resolveExactPromotedModelIdentity(
    { ready: true, metadata: statusMetadata({ project_id: "project-b" }) },
    expectedA,
  );
  assert.equal(result.ready, false);
  assert.equal(result.identity, null);
  assert.match(result.error, /does not match the exact project/i);
});

test("backend identity overwrites arbitrary browser identity values", () => {
  const identity = exactIdentity();
  const contaminated = {
    ...contextLib.defaultProjectContext,
    promotedModelId: "user-entered-model",
    promotedModelVersionId: "user-entered-version",
    promotedCandidateId: "user-entered-candidate",
  };
  const bound = identityLib.bindPromotedModelIdentity(contaminated, identity);
  assert.equal(bound.promotedModelId, "model-a");
  assert.equal(bound.promotedModelVersionId, "model-version-a");
  assert.equal(bound.promotedCandidateId, "candidate-a");
  assert.equal(identityLib.projectContextMatchesPromotedModel(bound, identity), true);
});

test("implementation context is isolated across two projects and two users", () => {
  localStorage.clear();
  const identityA = exactIdentity();
  const identityB = {
    ...identityA,
    projectId: "project-b",
    datasetId: "dataset-b",
    datasetVersionId: "version-b",
    target: "target-b",
    modelId: "model-b",
    modelVersionId: "model-version-b",
    candidateId: "candidate-b",
    trainingRunId: "training-run-b",
  };
  const contextA = identityLib.bindPromotedModelIdentity(
    { ...contextLib.defaultProjectContext, implementationOwner: "Owner A" },
    identityA,
  );
  const contextB = identityLib.bindPromotedModelIdentity(
    { ...contextLib.defaultProjectContext, implementationOwner: "Owner B" },
    identityB,
  );
  contextLib.saveProjectContext(contextA, "project-a", "user-a");
  contextLib.saveProjectContext(contextB, "project-b", "user-a");
  contextLib.saveProjectContext(
    { ...contextLib.defaultProjectContext, implementationOwner: "Other user" },
    "project-a",
    "user-b",
  );
  localStorage.setItem("modeling-tool-project-context", JSON.stringify({
    ...contextLib.defaultProjectContext,
    implementationOwner: "Legacy global attacker",
    promotedModelVersionId: "wrong-global-version",
  }));

  const restoredA = contextLib.loadProjectContext("project-a", "user-a");
  const restoredB = contextLib.loadProjectContext("project-b", "user-a");
  assert.equal(restoredA.implementationOwner, "Owner A");
  assert.equal(restoredA.promotedModelVersionId, "model-version-a");
  assert.equal(restoredB.implementationOwner, "Owner B");
  assert.equal(restoredB.promotedModelVersionId, "model-version-b");
  assert.equal(contextLib.loadProjectContext("project-a", "user-b").implementationOwner, "Other user");
  assert.notEqual(restoredA.implementationOwner, "Legacy global attacker");
});

test("Step12-to-Step13 carry-forward requires the same exact registry identity", () => {
  localStorage.clear();
  const identity = exactIdentity();
  const step12Saved = identityLib.bindPromotedModelIdentity(
    { ...contextLib.defaultProjectContext, implementationOwner: "Governed owner" },
    identity,
  );
  contextLib.saveProjectContext(step12Saved, "project-a", "user-a");
  const step13Loaded = contextLib.loadProjectContext("project-a", "user-a");
  assert.equal(identityLib.projectContextMatchesPromotedModel(step13Loaded, identity), true);
  assert.equal(
    identityLib.projectContextMatchesPromotedModel(
      step13Loaded,
      { ...identity, modelVersionId: "a-newer-promoted-version" },
    ),
    false,
    "Monitoring must block when the registry's exact promoted version changed after implementation handoff",
  );
});

test("Monitoring current-model card is built from the exact promoted identity only", () => {
  const identity = exactIdentity({ modelName: "Exact promoted champion" });
  const context = identityLib.bindPromotedModelIdentity(
    { ...contextLib.defaultProjectContext, implementationOwner: "Governed owner" },
    identity,
  );
  const exactModels = monitoringLib.loadProductionModels(context, identity);
  assert.deepEqual(
    {
      modelId: exactModels[0].modelId,
      modelVersionId: exactModels[0].modelVersionId,
      modelName: exactModels[0].modelName,
    },
    {
      modelId: "model-a",
      modelVersionId: "model-version-a",
      modelName: "Exact promoted champion",
    },
  );
  const blockedModels = monitoringLib.loadProductionModels(context, null);
  assert.equal(
    blockedModels.some((model) => model.modelId === "model-a"),
    false,
    "a browser-carried identity must not create the current-model card without exact backend verification",
  );
});

test("Step12 and Step13 hydrate and acknowledge exact-project durable context before navigation", () => {
  const step12 = fs.readFileSync("src/steps/Step12_ModelImplementation.tsx", "utf8");
  const step13 = fs.readFileSync("src/steps/Step13_ModelMonitoring.tsx", "utf8");
  const hook = fs.readFileSync("src/lib/useExactPromotedModelIdentity.ts", "utf8");

  for (const source of [step12, step13]) {
    assert.match(source, /useProjectContextAutosave\(/, "each page must hydrate and save through the durable project-context lifecycle");
    assert.match(source, /migrateStoredContext\(projectReadiness\.project\.projectContext\)/, "the initial form must use backend-authoritative project metadata");
    assert.match(source, /publishSavedProjectMetadata/, "an acknowledged save must refresh the authoritative provider");
    assert.match(source, /await autosave\.saveNow\(next\)/, "navigation must await an exact durable acknowledgement");
    assert.match(source, /if \(!persisted\)/, "failed persistence must keep the page open");
    assert.match(source, /page remains open/i, "the failure path must be visible and retryable");
    assert.match(source, /autosave\.hydrated && !autosave\.hydrating/, "editing and navigation must wait for exact-project hydration");
    assert.doesNotMatch(source, /loadProjectContext/, "browser storage must not hydrate these governed forms");
    assert.doesNotMatch(source, /saveProjectContext/, "browser storage must not acknowledge these governed forms");
    assert.doesNotMatch(source, /(?:localStorage|sessionStorage)/, "page code must not treat browser storage as authority");
    assert.ok(
      source.indexOf("await autosave.saveNow(next)") < source.indexOf("logDecision({"),
      "the durable save acknowledgement must precede completion logging and navigation",
    );
  }
  assert.match(step12, /value=\{promotedModel\.identity\?\.modelId/);
  assert.match(step12, /value=\{promotedModel\.identity\?\.modelVersionId/);
  assert.ok((step12.match(/readOnly/g) || []).length >= 2);
  assert.doesNotMatch(step12, /update\("modelId"/);
  assert.match(step12, /data-testid="implementation-plan-save-status"/);
  assert.match(step13, /projectContextMatchesPromotedModel/);
  assert.match(step13, /loadProductionModels\([\s\S]*promotedModel\.identity/);
  assert.match(step13, /data-testid="monitoring-plan-save-status"/);
  assert.match(step13, /disabled=\{!durableContextReady\}/, "monitoring controls must stay disabled during hydration");
  assert.match(hook, /buildFinalModelStatusQuery/);
  assert.match(hook, /credentials: "include"/);
  assert.match(hook, /userId: userId\.trim\(\)/, "authenticated user must be part of the request lifecycle scope");
});

console.log("implementationMonitoringIdentity.test.mjs: all checks passed.");

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
  path.join(tmpdir(), `atlas-project-metadata-${randomUUID()}-`),
);

async function transpile(sourcePath, outputName) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
      importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
    },
  }).outputText;
  const target = path.join(TEMP, outputName);
  await writeFile(target, output, "utf8");
  return target;
}

after(async () => {
  await rm(TEMP, { recursive: true, force: true });
});

const modulePath = await transpile(
  "src/lib/projectContextMetadata.ts",
  "projectContextMetadata.mjs",
);
const metadata = await import(pathToFileURL(modulePath).href);

const PROJECT_ID = "atlas-project-metadata";
const USER_ID = "user-metadata-owner";
const CURRENT_REVISION = "1785186305905-current";

function projectContext(overrides = {}) {
  return {
    projectName: "HELOC Baseline",
    description: "Governed HELOC predictive-modeling project.",
    problemStatement: "Estimate the probability of serious credit delinquency.",
    modelType: "generic classification",
    modelTypeSelection: "Generic Binary Classification",
    primaryDatasetId: "ds_heloc_train_6bdb184b_05905",
    primaryDatasetName: "HELOC_TRAIN",
    objectives: ["Develop a governed risk model."],
    successCriteria: ["Preserve exact canonical lineage."],
    stakeholders: ["Model Risk Management"],
    constraints: ["Final holdout remains evaluation-only."],
    regulatoryRequirements: ["Document model lineage."],
    sensitiveFeatures: [],
    explainabilityRequirements: "Provide reason-level evidence.",
    businessObjectives: ["Support consistent underwriting review."],
    assumptions: ["Development evidence is representative."],
    fraudDetails: null,
    ...overrides,
  };
}

function readyContext() {
  const targetContract = {
    targetColumn: "bad_flag",
    eventValue: 1,
    nonEventValue: 0,
  };
  const authContext = {
    userId: USER_ID,
    roles: ["model-developer"],
  };
  const analysisPartition = {
    developmentPartitionId: "partition-development",
    finalHoldoutPartitionId: "partition-final-holdout",
  };
  const workflowState = {
    currentStepId: "step00",
    targetContract,
    authContext,
    analysisPartition,
  };
  const activeDatasetIdentity = {
    project_id: PROJECT_ID,
    dataset_id: "ds_heloc_train_6bdb184b_05905",
    dataset_version_id: "v_1785186305905_6bdb184b",
    activation_revision: 7,
  };
  return {
    status: "ready",
    routeProjectId: PROJECT_ID,
    project: {
      projectId: PROJECT_ID,
      projectName: "HELOC Baseline",
      projectType: "predictive-modeling",
      workflowId: "predictive-modeling",
      modelId: "model-before-save",
      ownerUserId: USER_ID,
      updatedAt: "2026-08-02T12:00:00.000Z",
      metadataRevision: CURRENT_REVISION,
      metadataSavedAt: "2026-08-02T12:00:00.000Z",
      projectContext: projectContext(),
      projectTools: { predictiveModeling: true },
    },
    workflowState,
    activeDatasetIdentity,
    backendRevision: "workflow-revision-41",
    loadedAt: "2026-08-02T12:01:00.000Z",
    message: "The exact authorized project identity is ready.",
  };
}

function update(overrides = {}) {
  return {
    projectId: PROJECT_ID,
    projectRevision: "1785186306905-next",
    requestId: "project-context-save:project-context-metadata:1785186306905-next:11",
    projectName: "HELOC Updated",
    modelId: "model-after-save",
    changedFields: ["projectName", "modelId"],
    source: "user_save",
    savedAt: "2026-08-02T12:02:00.000Z",
    actorUserId: USER_ID,
    requestSequence: 11,
    projectContext: projectContext({
      projectName: "HELOC Updated",
      description: "Updated governed HELOC predictive-modeling project.",
    }),
    ...overrides,
  };
}

test("metadata revisions distinguish same, older, newer, and unknown values", () => {
  assert.equal(
    metadata.compareProjectMetadataRevisions(CURRENT_REVISION, CURRENT_REVISION),
    "same",
  );
  assert.equal(
    metadata.compareProjectMetadataRevisions(
      CURRENT_REVISION,
      "1785186304905-older",
    ),
    "older",
  );
  assert.equal(
    metadata.compareProjectMetadataRevisions(
      CURRENT_REVISION,
      "1785186306905-newer",
    ),
    "newer",
  );
  assert.equal(
    metadata.compareProjectMetadataRevisions(CURRENT_REVISION, "opaque-revision"),
    "unknown",
  );
  assert.equal(
    metadata.compareProjectMetadataRevisions(
      CURRENT_REVISION,
      "1785186305905-different-write-same-millisecond",
    ),
    "unknown",
  );
  assert.equal(
    metadata.compareProjectMetadataRevisions(
      "2026-08-02T12:00:00.000Z",
      "2026-08-02T12:00:01.000Z",
    ),
    "newer",
  );
});

test("same and older revisions are ignored without changing authoritative state", () => {
  const readiness = readyContext();
  const duplicate = metadata.applyProjectMetadataUpdate({
    readiness,
    update: update({ projectRevision: CURRENT_REVISION }),
    currentUserId: USER_ID,
    lastRequestSequence: 10,
  });
  assert.equal(duplicate.disposition, "duplicate");
  assert.strictEqual(duplicate.readiness, readiness);
  assert.equal(duplicate.requestSequence, 10);

  const stale = metadata.applyProjectMetadataUpdate({
    readiness,
    update: update({ projectRevision: "1785186304905-older" }),
    currentUserId: USER_ID,
    lastRequestSequence: 10,
  });
  assert.equal(stale.disposition, "stale_revision");
  assert.strictEqual(stale.readiness, readiness);
  assert.equal(stale.requestSequence, 10);

  const validOpaqueAfterStale = metadata.applyProjectMetadataUpdate({
    readiness,
    update: update({
      projectRevision: "opaque-legitimate-follow-up",
      requestSequence: 11,
    }),
    currentUserId: USER_ID,
    lastRequestSequence: stale.requestSequence,
  });
  assert.equal(validOpaqueAfterStale.disposition, "applied");
  assert.equal(
    validOpaqueAfterStale.readiness.project.metadataRevision,
    "opaque-legitimate-follow-up",
  );
});

test("a newer revision updates presentation metadata in place without replacing governed identity", () => {
  const readiness = readyContext();
  const identity = readiness.activeDatasetIdentity;
  const workflow = readiness.workflowState;
  const target = workflow.targetContract;
  const auth = workflow.authContext;
  const partition = workflow.analysisPartition;
  const updatedProjectContext = projectContext({
    projectName: "HELOC Updated",
    description: "Saved by the user after authoritative hydration.",
  });

  const result = metadata.applyProjectMetadataUpdate({
    readiness,
    update: update({
      requestSequence: 1,
      projectContext: updatedProjectContext,
    }),
    currentUserId: USER_ID,
    lastRequestSequence: 99,
  });

  assert.equal(result.disposition, "applied");
  assert.equal(result.requestSequence, 1);
  assert.notStrictEqual(result.readiness, readiness);
  assert.notStrictEqual(result.readiness.project, readiness.project);
  assert.equal(result.readiness.project.projectName, "HELOC Updated");
  assert.equal(result.readiness.project.modelId, "model-after-save");
  assert.equal(result.readiness.project.metadataRevision, "1785186306905-next");
  assert.equal(
    result.readiness.project.metadataSavedAt,
    "2026-08-02T12:02:00.000Z",
  );
  assert.strictEqual(result.readiness.project.projectContext, updatedProjectContext);
  assert.equal(result.readiness.project.updatedAt, "2026-08-02T12:02:00.000Z");

  assert.strictEqual(result.readiness.activeDatasetIdentity, identity);
  assert.strictEqual(result.readiness.workflowState, workflow);
  assert.strictEqual(result.readiness.workflowState.targetContract, target);
  assert.strictEqual(result.readiness.workflowState.authContext, auth);
  assert.strictEqual(result.readiness.workflowState.analysisPartition, partition);
  assert.equal(result.readiness.backendRevision, "workflow-revision-41");
  assert.equal(result.readiness.routeProjectId, PROJECT_ID);
  assert.equal(result.readiness.loadedAt, "2026-08-02T12:01:00.000Z");

  assert.equal(readiness.project.projectName, "HELOC Baseline");
  assert.equal(readiness.project.modelId, "model-before-save");
  assert.equal(readiness.project.metadataRevision, CURRENT_REVISION);
  assert.equal(readiness.project.metadataSavedAt, "2026-08-02T12:00:00.000Z");
  assert.equal(readiness.project.projectContext.projectName, "HELOC Baseline");
});

test("an unknown but sequenced revision can refresh metadata without blocking identity", () => {
  const readiness = readyContext();
  const result = metadata.applyProjectMetadataUpdate({
    readiness,
    update: update({ projectRevision: "opaque-revision-from-authority" }),
    currentUserId: USER_ID,
    lastRequestSequence: 10,
  });

  assert.equal(result.disposition, "applied");
  assert.equal(result.readiness.project.metadataRevision, "opaque-revision-from-authority");
  assert.strictEqual(
    result.readiness.activeDatasetIdentity,
    readiness.activeDatasetIdentity,
  );
  assert.strictEqual(result.readiness.workflowState, readiness.workflowState);
});

test("wrong project, wrong user, and a non-increasing opaque revision sequence fail closed", () => {
  const readiness = readyContext();
  const cases = [
    {
      expected: "wrong_project",
      candidate: update({ projectId: "atlas-other-project" }),
      lastRequestSequence: 10,
    },
    {
      expected: "wrong_user",
      candidate: update({ actorUserId: "user-other" }),
      lastRequestSequence: 10,
    },
    {
      expected: "stale_sequence",
      candidate: update({
        projectRevision: "opaque-revision-without-ordering",
        requestSequence: 10,
      }),
      lastRequestSequence: 10,
    },
  ];

  for (const item of cases) {
    const result = metadata.applyProjectMetadataUpdate({
      readiness,
      update: item.candidate,
      currentUserId: USER_ID,
      lastRequestSequence: item.lastRequestSequence,
    });
    assert.equal(result.disposition, item.expected);
    assert.strictEqual(result.readiness, readiness);
    assert.equal(result.requestSequence, item.lastRequestSequence);
  }
});

test("metadata updates cannot apply before authoritative identity is ready", () => {
  const resolving = {
    status: "resolving",
    routeProjectId: PROJECT_ID,
    project: null,
    workflowState: null,
    activeDatasetIdentity: null,
    backendRevision: "",
    loadedAt: "",
    message: "Loading project context...",
  };
  const result = metadata.applyProjectMetadataUpdate({
    readiness: resolving,
    update: update(),
    currentUserId: USER_ID,
    lastRequestSequence: 10,
  });

  assert.equal(result.disposition, "identity_not_ready");
  assert.strictEqual(result.readiness, resolving);
  assert.equal(result.requestSequence, 10);
});

test("changed fields are sorted and include additions, removals, and nested changes", () => {
  const previous = {
    projectName: "HELOC Baseline",
    description: "Old description",
    fraudDetails: { fraudType: "none" },
    unchanged: true,
  };
  const next = {
    projectName: "HELOC Updated",
    fraudDetails: { fraudType: "application" },
    modelTypeSelection: "Generic Binary Classification",
    unchanged: true,
  };

  assert.deepEqual(metadata.changedProjectContextFields(previous, next), [
    "description",
    "fraudDetails",
    "modelTypeSelection",
    "projectName",
  ]);
  assert.deepEqual(metadata.changedProjectContextFields(null, next), [
    "fraudDetails",
    "modelTypeSelection",
    "projectName",
    "unchanged",
  ]);
});

test("a user-save compatibility event is registered once per request and revision", () => {
  const emitted = new Set();
  const candidate = update();
  assert.equal(metadata.registerProjectMetadataEvent(emitted, candidate), true);
  assert.equal(metadata.registerProjectMetadataEvent(emitted, candidate), false);
  assert.equal(
    metadata.registerProjectMetadataEvent(
      emitted,
      update({ requestId: "different-request", projectRevision: candidate.projectRevision }),
    ),
    false,
  );
  assert.equal(
    metadata.registerProjectMetadataEvent(
      emitted,
      update({ requestId: candidate.requestId, projectRevision: "1785186307905-different-revision" }),
    ),
    false,
  );
  assert.equal(
    metadata.registerProjectMetadataEvent(
      emitted,
      update({ source: "background_verification", projectRevision: "1785186307905-background" }),
    ),
    false,
  );
  assert.equal(
    metadata.registerProjectMetadataEvent(
      emitted,
      update({
        projectRevision: "1785186307905-another-save",
        requestId: "project-context-save:project-context-metadata:1785186307905-another-save:12",
      }),
    ),
    true,
  );
});

test("the compatibility payload is typed, correlated, and excludes Project Context content", () => {
  const candidate = update();
  assert.deepEqual(metadata.projectContextUpdatedEventDetail(candidate), {
    project_id: candidate.projectId,
    project_revision: candidate.projectRevision,
    request_id: candidate.requestId,
    changed_fields: candidate.changedFields,
    source: "user_save",
    saved_at: candidate.savedAt,
  });
  assert.equal(
    Object.hasOwn(metadata.projectContextUpdatedEventDetail(candidate), "projectContext"),
    false,
  );
  assert.equal(
    metadata.projectContextUpdatedEventDetail(
      update({ source: "background_verification" }),
    ),
    null,
  );
});

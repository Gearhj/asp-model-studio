import { expect, test } from "@playwright/test";
import type { ExperimentRecord } from "../../src/lib/experimentTracking";
import type { ExactPromotedModelIdentity } from "../../src/lib/implementationMonitoringIdentity";
import { resolveModelDocumentationChampion } from "../../src/lib/modelDocumentationChampion";

const DATASET_IDENTITY = {
  project_id: "project-a",
  dataset_id: "dataset-a",
  dataset_version_id: "version-a",
};

const PROMOTED: ExactPromotedModelIdentity = {
  projectId: "project-a",
  datasetId: "dataset-a",
  datasetVersionId: "version-a",
  target: "target",
  modelId: "model-a",
  modelVersionId: "model-version-a",
  modelName: "Logistic Regression",
  candidateId: "candidate-a",
  trainingRunId: "training-run-a",
  featureManifestVersion: "manifest-a",
  validationDesignId: "validation-a",
  splitId: "split-a",
  artifactChecksum: "sha256:artifact-a",
  artifactVerificationStatus: "verified",
};

function experiment(overrides: Partial<ExperimentRecord> = {}): ExperimentRecord {
  return {
    experimentId: "browser-experiment-a",
    timestamp: "2030-01-01T00:00:00.000Z",
    project_id: "project-a",
    dataset_id: "dataset-a",
    dataset_version_id: "version-a",
    trainingJobId: "training-run-a",
    selectedFeatures: ["x"],
    preprocessingSteps: {},
    balancingMethod: "none",
    splitStrategy: "governed",
    modelKey: "logreg",
    modelType: "Logistic Regression",
    hyperparameters: null,
    metrics: { auc: 0.8 },
    calibrationStatus: "not calibrated",
    interpretability: 95,
    runtimeMs: 100,
    champion: false,
    notes: "supplementary only",
    ...overrides,
  };
}

test("documentation champion is the exact durable model version, not a browser champion flag", () => {
  const staleBrowserChampion = experiment({
    experimentId: "stale-browser-champion",
    trainingJobId: "older-run",
    modelType: "Random Forest",
    modelKey: "rf",
    champion: true,
  });
  const exactSupplement = experiment({ champion: false });

  const resolved = resolveModelDocumentationChampion({
    projectId: "project-a",
    datasetIdentity: DATASET_IDENTITY,
    target: "target",
    promotedModelIdentity: PROMOTED,
    experiments: [staleBrowserChampion, exactSupplement],
  });

  expect(resolved.ready).toBe(true);
  expect(resolved.identity?.modelVersionId).toBe("model-version-a");
  expect(resolved.identity?.candidateId).toBe("candidate-a");
  expect(resolved.supplementaryExperiment?.experimentId).toBe("browser-experiment-a");
  expect(resolved.supplementaryExperiment?.champion).toBe(false);
});

test("documentation champion fails closed on contradictory canonical scope", () => {
  for (const promotedModelIdentity of [
    { ...PROMOTED, projectId: "other-project" },
    { ...PROMOTED, datasetId: "other-dataset" },
    { ...PROMOTED, datasetVersionId: "other-version" },
    { ...PROMOTED, target: "other-target" },
  ]) {
    const resolved = resolveModelDocumentationChampion({
      projectId: "project-a",
      datasetIdentity: DATASET_IDENTITY,
      target: "target",
      promotedModelIdentity,
      experiments: [experiment()],
    });
    expect(resolved.ready).toBe(false);
    expect(resolved.identity).toBeNull();
    expect(resolved.error).toContain("contradicts");
  }
});

test("documentation champion requires complete durable lineage and artifact verification", () => {
  for (const promotedModelIdentity of [
    { ...PROMOTED, modelVersionId: "" },
    { ...PROMOTED, candidateId: "" },
    { ...PROMOTED, trainingRunId: "" },
    { ...PROMOTED, artifactChecksum: "" },
    { ...PROMOTED, artifactVerificationStatus: "failed" },
  ]) {
    const resolved = resolveModelDocumentationChampion({
      projectId: "project-a",
      datasetIdentity: DATASET_IDENTITY,
      target: "target",
      promotedModelIdentity,
      experiments: [],
    });
    expect(resolved.ready).toBe(false);
    expect(resolved.identity).toBeNull();
    expect(resolved.supplementaryExperiment).toBeNull();
  }
});

test("ambiguous browser diagnostics are ignored without replacing durable authority", () => {
  const resolved = resolveModelDocumentationChampion({
    projectId: "project-a",
    datasetIdentity: DATASET_IDENTITY,
    target: "target",
    promotedModelIdentity: PROMOTED,
    experiments: [experiment(), experiment({ experimentId: "duplicate" })],
  });

  expect(resolved.ready).toBe(true);
  expect(resolved.identity?.modelVersionId).toBe("model-version-a");
  expect(resolved.supplementaryExperiment).toBeNull();
});

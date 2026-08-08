import { expect, test } from "@playwright/test";
import {
  buildExactScoringHistoryFilters,
  buildFinalModelStatusQuery,
  eligibleDurableScoringPartitions,
  resolveCanonicalScoringDatasetVersion,
  resolveFinalModelVersionDisplay,
  type ExactScoringContinuationContext,
} from "../../src/lib/scoringContinuation";
import type { ScoringRunSummary } from "../../src/scoring-runs/scoringRunClient";

const exactContext: ExactScoringContinuationContext = {
  projectId: "project-exact",
  datasetId: "dataset-exact",
  datasetVersionId: "dataset-version-exact",
  target: "bad_flag",
  modelVersionId: "model-version-exact",
};

function completedRun(overrides: Partial<ScoringRunSummary> = {}): ScoringRunSummary {
  return {
    scoringRunId: "scoring-run-exact",
    projectId: exactContext.projectId,
    userId: "user-1",
    datasetId: exactContext.datasetId,
    datasetVersionId: exactContext.datasetVersionId,
    datasetIdentity: "Governed development TRAIN split",
    partition: "train",
    modelId: "logreg",
    modelVersion: "training-run-display-version",
    modelVersionId: exactContext.modelVersionId,
    problemType: "classification",
    target: exactContext.target,
    status: "completed",
    createdAt: "2026-08-07T12:00:00.000Z",
    completedAt: "2026-08-07T12:00:01.000Z",
    rowCount: 100,
    predictionColumn: "prediction",
    probabilityColumn: "adjusted_score",
    residualColumn: null,
    checksum: "sha256:scoring-output",
    archivedAt: null,
    ...overrides,
  };
}

test.describe("Step 10 exact final-model status and durable continuation", () => {
  test("shows the durable registry model version instead of dataset lineage", () => {
    expect(
      resolveFinalModelVersionDisplay({
        model_version_id: "model-version-durable",
        modelVersionId: "model-version-camel",
        final_model_version: "legacy-display-version",
        dataset_version: "dataset-version-must-not-render",
      }),
    ).toBe("model-version-durable");

    expect(
      resolveFinalModelVersionDisplay({
        modelVersionId: "model-version-camel",
        final_model_version: "legacy-display-version",
      }),
    ).toBe("model-version-camel");
  });

  test("never substitutes a dataset version for a missing model version", () => {
    expect(
      resolveFinalModelVersionDisplay({
        dataset_version: "dataset-version-must-not-render",
      }),
    ).toBe("Version unavailable");
    expect(
      resolveFinalModelVersionDisplay({
        final_model_version: "legacy-display-version",
      }),
    ).toBe("legacy-display-version");
  });

  test("builds the backend-required exact final-model status query", () => {
    const query = buildFinalModelStatusQuery(exactContext);
    expect(Object.fromEntries(query.entries())).toEqual({
      project_id: exactContext.projectId,
      dataset_id: exactContext.datasetId,
      dataset_version_id: exactContext.datasetVersionId,
      target: exactContext.target,
    });
    expect([...query.keys()]).toEqual([
      "project_id",
      "dataset_id",
      "dataset_version_id",
      "target",
    ]);
  });

  test("fails closed instead of issuing a partial final-model status request", () => {
    for (const field of ["projectId", "datasetId", "datasetVersionId", "target"] as const) {
      expect(() => buildFinalModelStatusQuery({ ...exactContext, [field]: "" })).toThrow(
        /exact project, dataset, immutable dataset version, and target/i,
      );
    }
  });

  test("builds visible scoring history filters for the exact promoted identity", () => {
    expect(buildExactScoringHistoryFilters(exactContext, { includeArchived: true, limit: 20 })).toEqual({
      datasetId: exactContext.datasetId,
      datasetVersionId: exactContext.datasetVersionId,
      modelVersionId: exactContext.modelVersionId,
      target: exactContext.target,
      includeArchived: true,
      limit: 20,
    });
  });

  test("fails closed instead of loading project-wide scoring history", () => {
    for (const field of ["projectId", "datasetId", "datasetVersionId", "modelVersionId", "target"] as const) {
      expect(() => buildExactScoringHistoryFilters({ ...exactContext, [field]: "" })).toThrow(
        /exact project, dataset, immutable dataset version, promoted model version, and target/i,
      );
    }
  });

  test("uses promoted training dataset-version lineage and never the legacy display field", () => {
    expect(resolveCanonicalScoringDatasetVersion({
      training_dataset_version_id: "training-version-exact",
      dataset_version_id: "registered-version-fallback",
      dataset_version: "legacy-version-must-not-be-used",
    })).toBe("training-version-exact");

    expect(resolveCanonicalScoringDatasetVersion({
      dataset_version_id: "registered-version-fallback",
      dataset_version: "legacy-version-must-not-be-used",
    })).toBe("registered-version-fallback");

    expect(resolveCanonicalScoringDatasetVersion({
      dataset_version: "legacy-version-must-not-be-used",
    })).toBe("");
  });

  test("accepts only completed, non-archived durable runs for the exact identity", () => {
    const eligible = completedRun();
    const rejected = [
      completedRun({ scoringRunId: "wrong-project", projectId: "other-project" }),
      completedRun({ scoringRunId: "wrong-dataset", datasetId: "other-dataset" }),
      completedRun({ scoringRunId: "wrong-dataset-version", datasetVersionId: "other-version" }),
      completedRun({ scoringRunId: "wrong-model-version", modelVersionId: "other-model-version" }),
      completedRun({ scoringRunId: "wrong-target", target: "other_target" }),
      completedRun({ scoringRunId: "failed", status: "failed", checksum: null }),
      completedRun({ scoringRunId: "cancelled", status: "cancelled" }),
      completedRun({ scoringRunId: "archived", archivedAt: "2026-08-07T12:05:00.000Z" }),
      completedRun({ scoringRunId: "missing-checksum", checksum: null }),
    ];

    expect(eligibleDurableScoringPartitions([eligible, ...rejected], exactContext)).toEqual(["train"]);
  });

  test("deduplicates exact completed runs by scored population", () => {
    expect(eligibleDurableScoringPartitions([
      completedRun({ scoringRunId: "train-1", partition: "train" }),
      completedRun({ scoringRunId: "train-2", partition: "train" }),
      completedRun({ scoringRunId: "test-1", partition: "test" }),
      completedRun({ scoringRunId: "oot-1", partition: "oot" }),
    ], exactContext)).toEqual(["train", "test", "oot"]);
  });
});

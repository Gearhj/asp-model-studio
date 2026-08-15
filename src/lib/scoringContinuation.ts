import type {
  ListScoringRunsFilters,
  ScoringPartition,
  ScoringRunSummary,
} from "../scoring-runs/scoringRunClient";

export type FinalModelStatusContext = {
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  target: string;
};

export type ExactScoringContinuationContext = FinalModelStatusContext & {
  modelVersionId: string;
};

export type CanonicalScoringDatasetVersionMetadata = {
  training_dataset_version_id?: unknown;
  dataset_version_id?: unknown;
  dataset_version?: unknown;
};

const exactText = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

/**
 * Resolve the immutable dataset version carried by the promoted model contract.
 *
 * `dataset_version` is a legacy display field and is deliberately excluded. It
 * cannot establish whether evidence belongs to the exact registered training
 * version used to create the promoted model.
 */
export function resolveCanonicalScoringDatasetVersion(
  metadata: CanonicalScoringDatasetVersionMetadata,
): string {
  return (
    exactText(metadata.training_dataset_version_id) ||
    exactText(metadata.dataset_version_id)
  );
}

/**
 * Build the only filters the visible Step 10 history is allowed to use. A
 * project-wide list is not an acceptable fallback because it could expose runs
 * from another dataset version, target, or promoted model within the project.
 */
export function buildExactScoringHistoryFilters(
  context: ExactScoringContinuationContext,
  options: { includeArchived?: boolean; limit?: number } = {},
): ListScoringRunsFilters {
  const datasetId = exactText(context.datasetId);
  const datasetVersionId = exactText(context.datasetVersionId);
  const modelVersionId = exactText(context.modelVersionId);
  const target = exactText(context.target);
  if (
    !exactText(context.projectId) ||
    !datasetId ||
    !datasetVersionId ||
    !modelVersionId ||
    !target
  ) {
    throw new Error(
      "Scoring history requires the exact project, dataset, immutable dataset version, promoted model version, and target.",
    );
  }
  return {
    datasetId,
    datasetVersionId,
    modelVersionId,
    target,
    includeArchived: options.includeArchived ?? false,
    limit: options.limit ?? 20,
  };
}

export type FinalModelVersionMetadata = {
  [key: string]: unknown;
  model_version_id?: unknown;
  modelVersionId?: unknown;
  final_model_version?: unknown;
};

/**
 * Return the registered model identity shown by Step 10.
 *
 * The final-status contract's `model_version_id` (or its camel-case transport
 * alias) is the durable Model Registry key and must win over the older display
 * label. Dataset-version fields are intentionally not accepted here: a
 * training dataset version is lineage, not a model version.
 */
export function resolveFinalModelVersionDisplay(
  metadata: FinalModelVersionMetadata,
): string {
  return (
    exactText(metadata.model_version_id) ||
    exactText(metadata.modelVersionId) ||
    exactText(metadata.final_model_version) ||
    "Version unavailable"
  );
}

/**
 * Build the fail-closed query required by FastAPI's `/model/final/status`
 * contract.  A partial request is never useful: FastAPI rejects it with 422,
 * and, more importantly, it cannot prove which registered artifact is current.
 */
export function buildFinalModelStatusQuery(
  context: FinalModelStatusContext,
): URLSearchParams {
  const projectId = exactText(context.projectId);
  const datasetId = exactText(context.datasetId);
  const datasetVersionId = exactText(context.datasetVersionId);
  const target = exactText(context.target);
  if (!projectId || !datasetId || !datasetVersionId || !target) {
    throw new Error(
      "Final-model status requires the exact project, dataset, immutable dataset version, and target.",
    );
  }
  return new URLSearchParams({
    project_id: projectId,
    dataset_id: datasetId,
    dataset_version_id: datasetVersionId,
    target,
  });
}

/**
 * Build the exact promoted identity shared by both Step 10 scoring endpoints.
 * Endpoint-specific fields (population, correction method, and optional priors)
 * are appended by the caller, but no request may omit any identity dimension.
 */
export function buildExactScoringRequestQuery(
  context: ExactScoringContinuationContext,
): URLSearchParams {
  const projectId = exactText(context.projectId);
  const datasetId = exactText(context.datasetId);
  const datasetVersionId = exactText(context.datasetVersionId);
  const target = exactText(context.target);
  const modelVersionId = exactText(context.modelVersionId);
  if (
    !projectId ||
    !datasetId ||
    !datasetVersionId ||
    !target ||
    !modelVersionId
  ) {
    throw new Error(
      "Scoring requires the exact project, dataset, immutable dataset version, target, and promoted model version.",
    );
  }
  return new URLSearchParams({
    project_id: projectId,
    dataset_id: datasetId,
    dataset_version_id: datasetVersionId,
    target,
    model_version_id: modelVersionId,
  });
}

/**
 * Resolve the refresh-durable scoring populations that can satisfy Step 10's
 * continuation gate.  The browser never treats project history in general as
 * proof: the run must be completed, active, checksum-backed, and bound to the
 * exact registered model version and training dataset identity currently shown.
 */
export function eligibleDurableScoringPartitions(
  runs: ScoringRunSummary[],
  context: ExactScoringContinuationContext,
): ScoringPartition[] {
  const expected = {
    projectId: exactText(context.projectId),
    datasetId: exactText(context.datasetId),
    datasetVersionId: exactText(context.datasetVersionId),
    target: exactText(context.target),
    modelVersionId: exactText(context.modelVersionId),
  };
  if (Object.values(expected).some((value) => !value)) return [];

  const eligible = new Set<ScoringPartition>();
  for (const run of runs) {
    if (
      run.status !== "completed" ||
      exactText(run.archivedAt) ||
      !exactText(run.checksum) ||
      exactText(run.projectId) !== expected.projectId ||
      exactText(run.datasetId) !== expected.datasetId ||
      exactText(run.datasetVersionId) !== expected.datasetVersionId ||
      exactText(run.target) !== expected.target ||
      exactText(run.modelVersionId) !== expected.modelVersionId
    ) {
      continue;
    }
    eligible.add(run.partition);
  }
  return (["train", "test", "oot"] as const).filter((partition) =>
    eligible.has(partition),
  );
}

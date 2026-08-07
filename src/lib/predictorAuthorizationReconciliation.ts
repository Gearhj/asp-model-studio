export type PredictorAuthorizationDraftState = {
  dirty: boolean;
  canUpdate: boolean;
  needsBaseline: boolean;
  canRetryBaseline: boolean;
  reason: string;
  actionLabel: string;
};

export function canonicalPredictorSelectionKey(
  predictors: readonly string[],
): string {
  const exact = [...new Set(predictors.map((value) => String(value)))].sort(
    (left, right) => (left < right ? -1 : left > right ? 1 : 0),
  );
  return exact.length ? JSON.stringify(exact) : "";
}

export function derivePredictorAuthorizationDraftState(input: {
  partitionCurrent: boolean;
  confirmedSelectionKey: string;
  selectedPredictors: readonly string[];
  saving: boolean;
  baselinePhase: "idle" | "loading" | "pending" | "ready" | "error";
}): PredictorAuthorizationDraftState {
  const selectedSelectionKey = canonicalPredictorSelectionKey(
    input.selectedPredictors,
  );
  const dirty = Boolean(
    input.partitionCurrent &&
      input.confirmedSelectionKey &&
      input.confirmedSelectionKey !== selectedSelectionKey,
  );

  if (input.partitionCurrent && !input.confirmedSelectionKey) {
    const failed = input.baselinePhase === "error";
    return {
      dirty: true,
      canUpdate: false,
      needsBaseline: true,
      canRetryBaseline: failed,
      reason: failed
        ? "ATLAS could not verify the exact predictor-authorization baseline. Retry the governed context check before updating predictors."
        : "ATLAS is verifying the exact predictor-authorization baseline. Predictor changes remain a draft until that check finishes.",
      actionLabel: failed
        ? "Retry Predictor Authorization Context"
        : "Verifying Predictor Authorization...",
    };
  }

  if (!dirty) {
    return {
      dirty: false,
      canUpdate: false,
      needsBaseline: false,
      canRetryBaseline: false,
      reason: "",
      actionLabel: "Predictor Authorization Current",
    };
  }
  if (!input.selectedPredictors.length) {
    return {
      dirty: true,
      canUpdate: false,
      needsBaseline: false,
      canRetryBaseline: false,
      reason: "Approve at least one eligible predictor before updating the governed authorization.",
      actionLabel: "Update Predictor Authorization",
    };
  }
  if (input.saving) {
    return {
      dirty: true,
      canUpdate: false,
      needsBaseline: false,
      canRetryBaseline: false,
      reason: "Saving the predictor selection and verifying preserved partition membership.",
      actionLabel: "Updating Predictor Authorization...",
    };
  }
  return {
    dirty: true,
    canUpdate: true,
    needsBaseline: false,
    canRetryBaseline: false,
    reason: "Save the predictor selection to update the governed authorization. The sealed Analysis Partition membership will be preserved.",
    actionLabel: "Update Predictor Authorization",
  };
}

export function shouldHydratePredictorSelectionFromGovernedBaseline(input: {
  partitionCurrent: boolean;
  baselineExact: boolean;
  selectionTouched: boolean;
  governedPredictors: readonly string[];
  localPredictors: readonly string[];
}): boolean {
  const governedSelectionKey = canonicalPredictorSelectionKey(
    input.governedPredictors,
  );
  return Boolean(
    input.partitionCurrent &&
      input.baselineExact &&
      !input.selectionTouched &&
      governedSelectionKey &&
      governedSelectionKey !==
        canonicalPredictorSelectionKey(input.localPredictors),
  );
}

function exactText(value: unknown): string {
  return String(value ?? "").trim();
}

/**
 * Predictor authorization may change without redrawing the Analysis Partition.
 * A successful reconciliation must prove that the immutable membership identity
 * returned by the backend is byte-for-byte the same as the verified baseline.
 */
export function analysisPartitionMembershipPreserved(
  baseline: Record<string, unknown>,
  refreshed: Record<string, unknown>,
): boolean {
  const requiredTextFields = [
    "analysis_partition_id",
    "project_id",
    "dataset_id",
    "dataset_version_id",
    "assignment_hash",
    "artifact_hash",
  ] as const;
  if (
    !requiredTextFields.every((field) => {
      const expected = exactText(baseline[field]);
      return Boolean(expected) && expected === exactText(refreshed[field]);
    })
  ) {
    return false;
  }

  const baselineRevision = Number(baseline.revision);
  if (
    !Number.isInteger(baselineRevision) ||
    baselineRevision <= 0 ||
    Number(refreshed.revision) !== baselineRevision
  ) {
    return false;
  }

  for (const field of [
    "population_fingerprint",
    "target_population_fingerprint",
  ] as const) {
    const expected = exactText(baseline[field]);
    if (expected && expected !== exactText(refreshed[field])) return false;
  }
  return true;
}

export function predictorAuthorizationLineageMatches(
  refreshed: Record<string, unknown>,
  expectedAuthorizationId: string,
): boolean {
  const expected = exactText(expectedAuthorizationId);
  const creation = exactText(refreshed.predictor_authorization_id);
  const current = exactText(
    refreshed.current_predictor_authorization_id ??
      refreshed.predictor_authorization_id,
  );
  const status = exactText(
    refreshed.predictor_authorization_lineage_status,
  );
  if (!expected || !creation || current !== expected) return false;
  return current === creation
    ? status === "current"
    : status === "changed_partition_preserved";
}

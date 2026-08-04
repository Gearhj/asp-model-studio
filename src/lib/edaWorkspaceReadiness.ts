export type EdaBlockedWorkspaceReadiness = {
  code: string;
  message: string;
  recovery: string;
  staleArtifacts: string[];
  structuralOverviewAvailable: boolean;
  targetDirectedAvailable: false;
  finalHoldoutAccessed: boolean;
};

const DEFAULT_CODE = "analysis_partition_required";
const DEFAULT_MESSAGE =
  "EDA requires a current Analysis Partition before governed analysis can begin.";
const DEFAULT_RECOVERY =
  "Return to Data Acquisition, review the selected development/final-holdout Analysis Partition, and confirm it explicitly.";

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function text(value: unknown, fallback: string): string {
  const normalized = typeof value === "string" ? value.trim() : "";
  return normalized || fallback;
}

/**
 * Recognize the fail-closed HTTP 200 envelope returned by the structural-only
 * EDA entry route. A partial response is readiness evidence, not an ordinary
 * Overview payload, and must never be admitted into analytical UI state.
 */
export function readBlockedEdaWorkspaceReadiness(
  payload: unknown,
): EdaBlockedWorkspaceReadiness | null {
  const envelope = record(payload);
  const readiness = record(envelope.governed_readiness);
  const status = String(readiness.status ?? "").trim().toLowerCase();
  const partial = envelope.partial === true;
  const targetDirectedUnavailable =
    readiness.target_directed_available === false;

  if (!partial && status !== "blocked" && !targetDirectedUnavailable) {
    return null;
  }

  return {
    code: text(readiness.code, DEFAULT_CODE),
    message: text(readiness.message, DEFAULT_MESSAGE),
    recovery: text(readiness.recovery, DEFAULT_RECOVERY),
    staleArtifacts: Array.isArray(readiness.stale_artifacts)
      ? readiness.stale_artifacts
          .filter((item): item is string => typeof item === "string")
          .map((item) => item.trim())
          .filter(Boolean)
      : [],
    structuralOverviewAvailable:
      readiness.structural_overview_available === true,
    targetDirectedAvailable: false,
    finalHoldoutAccessed: readiness.final_holdout_accessed === true,
  };
}

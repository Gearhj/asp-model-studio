import evidenceStatusContract from "../../shared/evidence_status_contract.json";

export type PersistedEvidenceStatus = "generated" | "captured" | "ready" | "approved" | "stale" | "rejected";

export type PersistedEvidenceLike = {
  status?: unknown;
  artifactType?: unknown;
};

const EXPECTED_STATUS_WEIGHT: Record<PersistedEvidenceStatus, number> = {
  generated: 0.25,
  captured: 0.5,
  ready: 0.75,
  approved: 1,
  stale: 0.1,
  rejected: 0,
};

const STATUS_WEIGHT = Object.fromEntries(
  Object.entries(evidenceStatusContract).map(([status, definition]) => [status, definition.weight]),
) as Record<PersistedEvidenceStatus, number>;

for (const [status, expected] of Object.entries(EXPECTED_STATUS_WEIGHT)) {
  if (STATUS_WEIGHT[status as PersistedEvidenceStatus] !== expected) {
    throw new Error(`Evidence status contract mismatch for ${status}.`);
  }
}

const STATUS_ALIAS = Object.fromEntries(
  Object.entries(evidenceStatusContract).flatMap(([status, definition]) =>
    definition.aliases.map((alias) => [alias, status]),
  ),
) as Record<string, PersistedEvidenceStatus>;

export function normalizePersistedEvidenceStatus(value: unknown): PersistedEvidenceStatus {
  const status = String(value || "generated").trim().toLowerCase();
  return STATUS_ALIAS[status] ?? "generated";
}

export function persistedEvidenceStatusToLegacy(value: unknown) {
  const status = normalizePersistedEvidenceStatus(value);
  if (status === "approved") return "accepted" as const;
  if (status === "ready" || status === "captured") return "ready" as const;
  if (status === "stale") return "deprecated" as const;
  if (status === "rejected") return "needs_review" as const;
  return "draft" as const;
}

export function summarizePersistedEvidence(
  records: PersistedEvidenceLike[],
  options: { requiredCount?: number; deduplicateByArtifactType?: boolean } = {},
) {
  const normalized = options.deduplicateByArtifactType
    ? [...records.reduce((byType, record) => {
        const key = String(record.artifactType || `artifact-${byType.size}`);
        const current = byType.get(key);
        const nextStatus = normalizePersistedEvidenceStatus(record.status);
        if (!current || STATUS_WEIGHT[nextStatus] > STATUS_WEIGHT[normalizePersistedEvidenceStatus(current.status)]) {
          byType.set(key, record);
        }
        return byType;
      }, new Map<string, PersistedEvidenceLike>()).values()]
    : records;
  const statuses = normalized.map((record) => normalizePersistedEvidenceStatus(record.status));
  const requiredCount = Math.max(1, options.requiredCount ?? normalized.length ?? 1);
  const generatedCount = statuses.filter((status) => status === "generated").length;
  const capturedCount = statuses.filter((status) => ["captured", "ready", "approved"].includes(status)).length;
  const readyCount = statuses.filter((status) => ["ready", "approved"].includes(status)).length;
  const approvedCount = statuses.filter((status) => status === "approved").length;
  const staleCount = statuses.filter((status) => status === "stale").length;
  const rejectedCount = statuses.filter((status) => status === "rejected").length;
  const weightedTotal = statuses.reduce((total, status) => total + STATUS_WEIGHT[status], 0);
  const coverageScore = Math.min(100, Math.round((weightedTotal / requiredCount) * 100));
  const packageReady = normalized.length >= requiredCount && readyCount >= requiredCount && staleCount === 0 && rejectedCount === 0;
  const packageApproved = normalized.length >= requiredCount && approvedCount >= requiredCount;
  const statusLabel = packageApproved
    ? "Evidence package approved"
    : packageReady
      ? "Evidence package ready"
      : rejectedCount
        ? `${rejectedCount} evidence artifact${rejectedCount === 1 ? "" : "s"} rejected`
        : staleCount
          ? `${staleCount} evidence artifact${staleCount === 1 ? "" : "s"} stale`
          : readyCount
            ? `${readyCount} of ${requiredCount} evidence artifacts ready`
            : capturedCount
              ? `${capturedCount} of ${requiredCount} evidence artifacts captured`
              : generatedCount
                ? `${generatedCount} of ${requiredCount} evidence artifacts generated`
                : "No governed evidence recorded";
  return {
    totalCount: normalized.length,
    requiredCount,
    generatedCount,
    capturedCount,
    readyCount,
    approvedCount,
    staleCount,
    rejectedCount,
    coverageScore,
    packageReady,
    packageApproved,
    statusLabel,
  };
}

export function summarizeOptimizationEvidenceRecords(records: Array<{ generated?: boolean; captured?: boolean; ready?: boolean; approved?: boolean }>) {
  return summarizePersistedEvidence(records
    .filter((record) => record.generated || record.captured || record.ready || record.approved)
    .map((record) => ({
      status: record.approved ? "approved" : record.ready ? "ready" : record.captured ? "captured" : "generated",
    })), { requiredCount: records.length });
}

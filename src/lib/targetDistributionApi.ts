// Target Distribution -- dedicated bounded server aggregate.
//
// The chart used to read its counts out of the full data-quality profile, which
// profiles every column and only then yields two rows of grouped counts. This
// module calls a purpose-built endpoint that runs a single DuckDB GROUP BY over
// the governed artifact and returns bounded aggregate rows only.
import type { ClassDistributionRow } from "./dataAcquisitionLifecycle";

const API_BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

export type TargetDistributionResolution = "exact" | "sampled" | "unsupported";

export type TargetDistributionSampling = {
  samplingMethod: string;
  seed: number;
  sampledRowCount: number;
  sourceRowCount: number;
};

export type TargetDistributionResult = {
  ok: boolean;
  supported: boolean;
  resolution: TargetDistributionResolution;
  reason?: string;
  datasetId: string;
  versionId: string;
  target: string;
  classDistribution: ClassDistributionRow[];
  totalRowCount: number;
  artifactFormat?: "parquet" | "csv";
  engine?: string;
  cached: boolean;
  durationMs: number;
  sampling?: TargetDistributionSampling;
};

export type TargetDistributionRequest = {
  projectId: string;
  datasetId: string;
  versionId: string;
  target: string;
  eventValue?: unknown;
  nonEventValue?: unknown;
  forceExact?: boolean;
};

/** Identity of one immutable aggregate. Any change here is a different result. */
export function buildTargetDistributionKey(request: TargetDistributionRequest): string {
  return [
    request.projectId,
    request.datasetId,
    request.versionId,
    request.target,
    String(request.eventValue ?? ""),
    String(request.nonEventValue ?? ""),
    request.forceExact ? "exact" : "auto",
  ].join("|");
}

// In-flight requests keyed by identity. React StrictMode double-mounts effects and
// dependency churn can fire the same query several times in a row; joining the
// existing promise means duplicate renders never issue duplicate active queries.
const inFlight = new Map<string, Promise<TargetDistributionResult>>();

// Successful results for immutable (dataset, version, target) tuples. The data is
// immutable by construction, so a hit is always safe; a changed version or target
// produces a different key and therefore never reads a stale entry.
const resultCache = new Map<string, TargetDistributionResult>();

export function peekCachedTargetDistribution(request: TargetDistributionRequest): TargetDistributionResult | null {
  return resultCache.get(buildTargetDistributionKey(request)) ?? null;
}

export function clearTargetDistributionCache(): void {
  resultCache.clear();
  inFlight.clear();
}

export async function fetchTargetDistribution(
  request: TargetDistributionRequest,
  options: { signal?: AbortSignal } = {}
): Promise<TargetDistributionResult> {
  const key = buildTargetDistributionKey(request);

  const cached = resultCache.get(key);
  if (cached) return cached;

  const existing = inFlight.get(key);
  if (existing) return existing;

  const promise = (async () => {
    const response = await fetch(`${API_BASE}/analytics/target-distribution`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        projectId: request.projectId,
        datasetId: request.datasetId,
        versionId: request.versionId,
        target: request.target,
        eventValue: request.eventValue ?? null,
        nonEventValue: request.nonEventValue ?? null,
        forceExact: Boolean(request.forceExact),
      }),
      signal: options.signal,
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.detail ?? "The target distribution could not be calculated.");
    }
    const result = payload as TargetDistributionResult;
    resultCache.set(key, result);
    return result;
  })();

  inFlight.set(key, promise);
  try {
    return await promise;
  } finally {
    inFlight.delete(key);
  }
}

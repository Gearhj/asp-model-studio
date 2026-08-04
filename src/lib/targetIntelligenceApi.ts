// EDA Target Intelligence -- bounded server aggregates and durable findings.
//
// Follows the identity / in-flight-dedup / immutable-result-cache contract
// already proven by targetDistributionApi.ts: React StrictMode double-mounts and
// dependency churn must never produce a second active query for the same
// analytical identity, and a response for a superseded identity must never land.
import type {
  AnalysisScope,
  TargetAssessmentResult,
  TargetByPredictorResult,
  TargetFinding,
  TargetPredictorAnalysisType,
} from "./targetIntelligence";

const API_BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

// ---------------------------------------------------------------------------
// Request identities
// ---------------------------------------------------------------------------

export type TargetAssessmentRequest = {
  projectId: string;
  datasetId: string;
  versionId: string;
  target: string;
  eventValue?: unknown;
  nonEventValue?: unknown;
  confidenceLevel?: number;
};

export type TargetByPredictorRequest = {
  projectId: string;
  /** Empty when the project has no registered Dataset Library version; the
   *  request then goes to the full-population EDA workspace path instead of the
   *  immutable-artifact path. Both are exact, bounded, and server-side. */
  datasetId: string;
  versionId: string;
  target: string;
  predictor: string;
  analysisType: TargetPredictorAnalysisType;
  eventValue?: unknown;
  bands?: number;
  topCategories?: number;
  includeMissing?: boolean;
  /** Draft path only: the workspace dataset this analysis belongs to. */
  workspaceFingerprint?: string | null;
};

/** The scope a request is issued FOR. Included in every identity so a draft
 *  response can never satisfy a governed request, or vice versa. */
function requestedScopeMode(request: { datasetId: string; versionId: string }): string {
  return request.datasetId && request.versionId ? "governed_version" : "workspace_draft";
}

export function buildTargetAssessmentKey(request: TargetAssessmentRequest): string {
  return [
    requestedScopeMode(request),
    request.projectId,
    request.datasetId,
    request.versionId,
    request.target,
    String(request.eventValue ?? ""),
    String(request.nonEventValue ?? ""),
    String(request.confidenceLevel ?? 0.95),
  ].join("|");
}

export function buildTargetByPredictorKey(request: TargetByPredictorRequest): string {
  return [
    requestedScopeMode(request),
    request.projectId,
    request.datasetId,
    request.versionId,
    // A draft request is only interchangeable with another draft request over
    // the SAME workspace dataset, so the fingerprint is part of its identity.
    request.workspaceFingerprint ?? "",
    request.target,
    request.predictor,
    request.analysisType,
    String(request.eventValue ?? ""),
    String(request.bands ?? ""),
    String(request.topCategories ?? ""),
    request.includeMissing === false ? "no-missing" : "with-missing",
  ].join("|");
}

// ---------------------------------------------------------------------------
// Shared dedup + cache machinery
// ---------------------------------------------------------------------------

type Store<T> = { inFlight: Map<string, Promise<T>>; results: Map<string, T> };

function createStore<T>(): Store<T> {
  return { inFlight: new Map(), results: new Map() };
}

const assessmentStore = createStore<TargetAssessmentResult>();
const predictorStore = createStore<TargetByPredictorResult>();

/** Test/diagnostic counters -- how many active requests a rerender actually issued. */
const counters = { assessmentRequests: 0, predictorRequests: 0, cacheHits: 0 };

export function targetIntelligenceCounters(): Readonly<typeof counters> {
  return { ...counters };
}

export function clearTargetIntelligenceCache(): void {
  assessmentStore.inFlight.clear();
  assessmentStore.results.clear();
  predictorStore.inFlight.clear();
  predictorStore.results.clear();
  counters.assessmentRequests = 0;
  counters.predictorRequests = 0;
  counters.cacheHits = 0;
}

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) {
    throw new Error(
      typeof payload?.detail === "string" ? payload.detail : "The target analysis could not be completed."
    );
  }
  return payload as T;
}

async function dedup<T>(
  store: Store<T>,
  key: string,
  counterKey: "assessmentRequests" | "predictorRequests",
  run: () => Promise<T>
): Promise<T> {
  const cached = store.results.get(key);
  if (cached) {
    counters.cacheHits += 1;
    return cached;
  }
  const existing = store.inFlight.get(key);
  if (existing) return existing;

  counters[counterKey] += 1;
  const promise = run().then((result) => {
    store.results.set(key, result);
    return result;
  });
  store.inFlight.set(key, promise);
  try {
    return await promise;
  } finally {
    store.inFlight.delete(key);
  }
}

/** Number of distinct queries currently in flight -- asserted by the perf tests. */
export function activeTargetIntelligenceRequests(): number {
  return assessmentStore.inFlight.size + predictorStore.inFlight.size;
}

// ---------------------------------------------------------------------------
// Parts D / E / F
// ---------------------------------------------------------------------------

export function peekTargetAssessment(request: TargetAssessmentRequest): TargetAssessmentResult | null {
  return assessmentStore.results.get(buildTargetAssessmentKey(request)) ?? null;
}

export function fetchTargetAssessment(
  request: TargetAssessmentRequest,
  options: { signal?: AbortSignal } = {}
): Promise<TargetAssessmentResult> {
  const key = buildTargetAssessmentKey(request);
  return dedup(assessmentStore, key, "assessmentRequests", () =>
    postJson<TargetAssessmentResult>(
      "/analytics/target-assessment",
      {
        projectId: request.projectId,
        datasetId: request.datasetId,
        versionId: request.versionId,
        target: request.target,
        eventValue: request.eventValue ?? null,
        nonEventValue: request.nonEventValue ?? null,
        confidenceLevel: request.confidenceLevel ?? 0.95,
      },
      options.signal
    )
  );
}

// ---------------------------------------------------------------------------
// Part G
// ---------------------------------------------------------------------------

export function peekTargetByPredictor(request: TargetByPredictorRequest): TargetByPredictorResult | null {
  return predictorStore.results.get(buildTargetByPredictorKey(request)) ?? null;
}

export function fetchTargetByPredictor(
  request: TargetByPredictorRequest,
  options: { signal?: AbortSignal } = {}
): Promise<TargetByPredictorResult> {
  const key = buildTargetByPredictorKey(request);
  // A registered version is scanned as an immutable artifact; an unregistered
  // project is aggregated over the full in-memory backend population. Neither
  // path returns rows -- only bounded grouped counts.
  const registered = Boolean(request.datasetId && request.versionId);
  return dedup(predictorStore, key, "predictorRequests", () =>
    registered
      ? postJson<TargetByPredictorResult>(
          "/analytics/target-by-predictor",
          {
            projectId: request.projectId,
            datasetId: request.datasetId,
            versionId: request.versionId,
            target: request.target,
            predictor: request.predictor,
            analysisType: request.analysisType,
            eventValue: request.eventValue ?? null,
            bands: request.bands ?? 10,
            topCategories: request.topCategories ?? 12,
            includeMissing: request.includeMissing !== false,
          },
          options.signal
        )
      : postJson<TargetByPredictorResult>(
          "/eda/target-by-predictor",
          {
            project_id: request.projectId,
            // Deliberately no dataset/version: the draft endpoint derives
            // workspace_draft scope from server state and must not be offered a
            // governance claim to echo back.
            target: request.target,
            event_value: request.eventValue ?? null,
            predictor: request.predictor,
            analysis_type: request.analysisType,
            bands: request.bands ?? 10,
            top_categories: request.topCategories ?? 12,
            include_missing: request.includeMissing !== false,
          },
          options.signal
        )
  );
}

// ---------------------------------------------------------------------------
// Part J -- durable findings
// ---------------------------------------------------------------------------

export type TargetFindingScope = {
  projectId: string;
  /** Governed queries name a version; draft queries name a fingerprint. Sending
   *  neither returns everything the project has, labeled by scope. */
  scopeMode?: "governed_version" | "workspace_draft";
  datasetId?: string;
  versionId?: string;
  workspaceFingerprint?: string | null;
  target?: string;
};

export type TargetFindingListing = { findings: TargetFinding[]; legacyFindings: TargetFinding[] };

export async function listTargetFindings(scope: TargetFindingScope, signal?: AbortSignal): Promise<TargetFindingListing> {
  const params = new URLSearchParams({ projectId: scope.projectId });
  if (scope.scopeMode) params.set("scopeMode", scope.scopeMode);
  if (scope.datasetId) params.set("datasetId", scope.datasetId);
  if (scope.versionId) params.set("versionId", scope.versionId);
  if (scope.workspaceFingerprint) params.set("workspaceFingerprint", scope.workspaceFingerprint);
  if (scope.target) params.set("target", scope.target);
  const response = await fetch(`${API_BASE}/analytics/target-findings?${params.toString()}`, {
    credentials: "include",
    signal,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) {
    throw new Error(typeof payload?.detail === "string" ? payload.detail : "Target findings could not be loaded.");
  }
  return {
    findings: (payload.findings ?? []) as TargetFinding[],
    legacyFindings: (payload.legacyFindings ?? []) as TargetFinding[],
  };
}

export async function createTargetFinding(input: {
  projectId: string;
  /** Empty for a draft finding. The SERVER decides the resulting scope; these
   *  are inputs to resolution, not a governance claim. */
  datasetId: string;
  versionId: string;
  workspaceFingerprint?: string | null;
  target: string;
  analysisType: string;
  title: string;
  detail: string;
  severity: TargetFinding["severity"];
  metadata?: Record<string, unknown>;
}): Promise<TargetFinding> {
  const payload = await postJson<{ finding: TargetFinding }>("/analytics/target-findings", {
    ...input,
    workspaceFingerprint: input.workspaceFingerprint ?? "",
    status: "open",
    metadata: input.metadata ?? {},
  });
  return payload.finding;
}

/** Controlled carry-forward: copies a draft finding onto a governed version.
 *  The draft record is preserved; the copy starts at status "open". */
export async function promoteTargetFinding(
  findingId: string,
  input: { projectId: string; datasetId: string; versionId: string }
): Promise<TargetFinding> {
  const payload = await postJson<{ finding: TargetFinding }>(
    `/analytics/target-findings/${encodeURIComponent(findingId)}/promote`,
    input
  );
  return payload.finding;
}

// ---------------------------------------------------------------------------
// Part C -- governed evidence is created by the SERVER, not asserted here
// ---------------------------------------------------------------------------

export type GovernedEvidenceResult = {
  ok: boolean;
  evidenceId: string;
  analysisScope: AnalysisScope;
  mddEligible: boolean;
  createdAt: string;
};

export type GovernedTargetSummaryExport = {
  ok: true;
  scopeMode: "governed_version";
  markers: [];
  governed: true;
  datasetId: string;
  datasetVersionId: string;
  artifactChecksum: string;
  target: string;
  exact: boolean;
  sampled: boolean;
  evidenceEligible: boolean;
  mddEligible: boolean;
  analysisPopulationId: string;
  analysisPartitionId: string;
  analysisPartitionRevision: number;
  splitId: string;
  populationScope: "development_population";
  populationRows: number;
  fullGovernedPopulationRows: number;
  finalHoldoutAccessed: false;
  finalHoldoutUsedForSelection: false;
  generatedAt: string;
  classBalance: TargetAssessmentResult["classBalance"];
  imbalance: TargetAssessmentResult["imbalance"];
  confidenceInterval: TargetAssessmentResult["confidenceInterval"];
  disclosure: string;
};

/**
 * Requests a governed Target Intelligence evidence artifact.
 *
 * Note what is NOT sent: scope mode, evidence eligibility, class counts, event
 * rate, imbalance, interval, checksum. The server recomputes every figure and
 * re-resolves every governance fact, so this call cannot assert governance --
 * it can only ask for it and be refused with a 409 if the analysis is a draft.
 */
export async function saveGovernedTargetEvidence(input: {
  projectId: string;
  datasetId: string;
  versionId: string;
  target: string;
  eventValue?: unknown;
  nonEventValue?: unknown;
  predictor?: string | null;
  predictorAnalysisType?: TargetPredictorAnalysisType | null;
  predictorBands?: number;
  predictorTopCategories?: number;
  predictorIncludeMissing?: boolean;
  timeField?: string | null;
  segmentField?: string | null;
  chartSpecification?: Record<string, unknown>;
  title?: string | null;
  notes?: string;
}): Promise<GovernedEvidenceResult> {
  return postJson<GovernedEvidenceResult>("/analytics/target-evidence", {
    projectId: input.projectId,
    datasetId: input.datasetId,
    versionId: input.versionId,
    target: input.target,
    eventValue: input.eventValue ?? null,
    nonEventValue: input.nonEventValue ?? null,
    predictor: input.predictor ?? null,
    predictorAnalysisType: input.predictorAnalysisType ?? null,
    predictorBands: input.predictorBands ?? 10,
    predictorTopCategories: input.predictorTopCategories ?? 12,
    predictorIncludeMissing: input.predictorIncludeMissing !== false,
    timeField: input.timeField ?? null,
    segmentField: input.segmentField ?? null,
    chartSpecification: input.chartSpecification ?? {},
    title: input.title ?? null,
    notes: input.notes ?? "",
  });
}

/**
 * Downloads a governed Target Intelligence summary only after the backend
 * re-resolves the exact documented development population. The browser sends
 * selection identity, never calculated counts, scope, or governance claims.
 */
export async function exportGovernedTargetSummary(input: {
  projectId: string;
  datasetId: string;
  versionId: string;
  target: string;
  eventValue?: unknown;
  nonEventValue?: unknown;
}): Promise<GovernedTargetSummaryExport> {
  return postJson<GovernedTargetSummaryExport>(
    "/analytics/target-summary-export",
    {
      projectId: input.projectId,
      datasetId: input.datasetId,
      versionId: input.versionId,
      target: input.target,
      eventValue: input.eventValue ?? null,
      nonEventValue: input.nonEventValue ?? null,
    }
  );
}

export async function updateTargetFinding(
  findingId: string,
  input: {
    projectId: string;
    title?: string;
    detail?: string;
    severity?: TargetFinding["severity"];
    status?: TargetFinding["status"];
  }
): Promise<TargetFinding> {
  const response = await fetch(`${API_BASE}/analytics/target-findings/${encodeURIComponent(findingId)}`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) {
    throw new Error(typeof payload?.detail === "string" ? payload.detail : "The target finding could not be updated.");
  }
  return payload.finding as TargetFinding;
}

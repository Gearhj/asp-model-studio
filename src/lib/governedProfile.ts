// Governed target-dependent profiling -- client contract.
//
// Replaces the browser-side quality/IV fallback that produced the acceptance
// defect. Four root causes are closed here and in the components that use this:
//
//   1. the backend asserted "full_dataset" for whatever was in DATASTORE
//      -> the server now returns an explicit, derived analysisScope;
//   2. a failed governed request silently became a 100-row preview computation
//      -> there is no fallback path in this module at all;
//   3. Number(null) === 0 rendered "not estimable" IV as 0.0000
//      -> formatIv() never coerces, and null is "Not available";
//   4. a preview-derived zero event rate produced a registered-population
//      blocker -> readiness consumers must check scope before blocking.
//
// The browser NEVER decides scope. Every governance field is read, not derived.

const API_BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

export type ProfileScopeMode = "governed_version" | "workspace_draft" | "preview_only";

/** Stable machine-readable reason a legacy version cannot be profiled. */
export const FULL_ARTIFACT_MISSING = "full_artifact_missing";

export type IvStatus =
  | "pending"
  | "available"
  | "unavailable_no_events"
  | "unavailable_no_non_events"
  | "unavailable_nonbinary_target"
  | "unavailable_invalid_event_mapping"
  | "unavailable_insufficient_population"
  | "unavailable_not_eligible"
  | "failed"
  | "preview_only";

/** Reader-facing explanation of every non-available IV state. Zero is never one
 *  of these -- a zero IV means a genuinely computed zero. */
export const IV_STATUS_LABELS: Record<IvStatus, string> = {
  pending: "Calculating",
  available: "Available",
  unavailable_no_events: "Not estimable - no events in this population",
  unavailable_no_non_events: "Not estimable - no non-events in this population",
  unavailable_nonbinary_target: "Not estimable - target is not binary",
  unavailable_invalid_event_mapping: "Not estimable - event value not found in the target",
  unavailable_insufficient_population: "Not estimable - insufficient population",
  unavailable_not_eligible: "Not applicable - not an eligible predictor",
  failed: "Calculation failed",
  preview_only: "Not calculated - browser preview only",
};

export type IvBin = {
  bin: number;
  label: string;
  population: number;
  eventCount: number;
  nonEventCount: number;
  eventRate: number | null;
  woe: number;
  ivContribution: number;
  isMissingBin?: boolean;
  isOtherBin?: boolean;
  collapsedCategoryCount?: number;
  lowerBound?: number | null;
  upperBound?: number | null;
};

export type PredictorProfile = {
  predictor: string;
  role: string;
  eligible: boolean;
  exclusionReason: string;
  iv: number | null;
  ivStatus: IvStatus;
  ivStrength: { key: string; label: string } | null;
  bins: IvBin[];
  binningMethod?: string | null;
  effectiveBinCount: number;
  grouping?: { distinctCategoryCount: number; collapsedCategoryCount: number; groupingApplied: boolean; rule: string } | null;
  totalEvents?: number;
  totalNonEvents?: number;
  smoothingMethod?: string;
  smoothingConstant?: number;
  reconciled?: boolean;
  failureReason?: string;
};

export type QualityProfile = {
  populationRows: number;
  columnCount: number;
  duplicateRows: number;
  columnsWithMissingValues: number;
  missingness: Array<{ column: string; count: number; percent: number; distinctCount: number }>;
  constantColumns: string[];
  nearZeroVarianceColumns: string[];
  highCardinalityColumns: string[];
  potentialLeakageColumns: string[];
  dateFields: string[];
  targetMissingCount: number;
  targetDistinctCount: number;
  eventCount: number;
  nonEventCount: number;
  eventRate: number | null;
};

export type TargetMapping = {
  target: string;
  eventValue: string | null;
  nonEventValue: string;
  eventValueResolution: "configured" | "defaulted_to_one" | "event_value_absent" | "unresolved";
  distinctCount: number;
  isBinary: boolean;
  missingTargetCount: number;
  validTargetCount: number;
  eventCount: number;
  nonEventCount: number;
  eventRate: number | null;
};

export type TargetProfileResult = {
  ok: boolean;
  analysisScope: {
    mode: ProfileScopeMode;
    label: string;
    projectId: string;
    datasetId: string | null;
    datasetVersionId: string | null;
    datasetName: string;
    datasetFingerprint: string | null;
    artifactChecksum: string | null;
    target: string;
    populationRows: number;
    profiledRows?: number;
    exact: boolean;
    sampled: boolean;
    immutableVersion: boolean;
    evidenceEligible: boolean;
    mddEligible: boolean;
    decisionReady?: boolean;
    disclosure: string;
    resolvedAt: string;
  };
  scopeIdentity: string;
  profileScope: ProfileScopeMode;
  calculationVersion: string;
  generatedAt: string;
  datasetId: string | null;
  datasetVersionId: string | null;
  datasetName: string;
  artifactChecksum: string | null;
  target: string;
  targetMapping: TargetMapping;
  quality: QualityProfile;
  problemType: "classification" | "regression";
  predictors: PredictorProfile[];
  predictorSummary: {
    total: number;
    evaluated: number;
    unavailable: number;
    previewOnly?: number;
    failed: number;
    leakageReview: number;
  };
  methodology: Record<string, unknown>;
  artifactResolutions: number;
  datasetScans: number;
  cached: boolean;
  durationMs: number;
};

/** A legacy version with no complete artifact. Carries the machine-readable
 *  reason and the recovery actions, so the UI never dead-ends. */
export type FullArtifactMissingError = {
  reason: typeof FULL_ARTIFACT_MISSING;
  message: string;
  disclosure: string;
  datasetId: string;
  datasetName?: string;
  versionId: string;
  declaredRowCount?: number;
  recovery: string[];
  sampleSubstituted: false;
};

export class ProfileUnavailableError extends Error {
  readonly detail: FullArtifactMissingError | null;
  readonly status: number;
  constructor(message: string, status: number, detail: FullArtifactMissingError | null) {
    super(message);
    this.name = "ProfileUnavailableError";
    this.detail = detail;
    this.status = status;
  }
  get isLegacyArtifactMissing(): boolean {
    return this.detail?.reason === FULL_ARTIFACT_MISSING;
  }
}

// ---------------------------------------------------------------------------
// Request identity -- dataset, version, target AND event mapping
// ---------------------------------------------------------------------------

export type TargetProfileRequest = {
  projectId: string;
  datasetId: string | null;
  versionId: string | null;
  target: string;
  eventValue?: unknown;
  nonEventValue?: unknown;
  problemType?: "classification" | "regression";
  includeIv?: boolean;
  selectedColumns?: string[];
  /** Draft/preview identity, so a replacement upload is a different request. */
  workspaceFingerprint?: string | null;
};

/**
 * Complete analytical identity.
 *
 * Changing the dataset, version, target, event mapping, problem type, project,
 * or workspace fingerprint produces a different key -- which is what makes a
 * response for an old mapping incapable of satisfying or overwriting a new one.
 */
export function buildTargetProfileKey(request: TargetProfileRequest): string {
  return [
    request.datasetId && request.versionId ? "governed_version" : "workspace",
    request.projectId,
    request.datasetId ?? "",
    request.versionId ?? "",
    request.workspaceFingerprint ?? "",
    request.target,
    String(request.eventValue ?? ""),
    String(request.nonEventValue ?? ""),
    request.problemType ?? "classification",
    request.includeIv === false ? "quality" : "iv",
    (request.selectedColumns ?? []).slice().sort().join(","),
  ].join("|");
}

const inFlight = new Map<string, Promise<TargetProfileResult>>();
const results = new Map<string, TargetProfileResult>();
const counters = { requests: 0, cacheHits: 0 };

export function targetProfileCounters(): Readonly<typeof counters> {
  return { ...counters };
}

export function activeTargetProfileRequests(): number {
  return inFlight.size;
}

export function clearTargetProfileCache(): void {
  inFlight.clear();
  results.clear();
  counters.requests = 0;
  counters.cacheHits = 0;
}

export function peekTargetProfile(request: TargetProfileRequest): TargetProfileResult | null {
  return results.get(buildTargetProfileKey(request)) ?? null;
}

/**
 * Requests a target-dependent profile.
 *
 * There is deliberately NO catch-and-fall-back-to-the-browser here. A failure
 * throws, and the caller must show the failure. That is the single change that
 * makes it impossible for a 100-row preview to masquerade as the registered
 * population.
 */
export async function fetchTargetProfile(
  request: TargetProfileRequest,
  options: { signal?: AbortSignal } = {}
): Promise<TargetProfileResult> {
  const key = buildTargetProfileKey(request);
  const cached = results.get(key);
  if (cached) {
    counters.cacheHits += 1;
    return cached;
  }
  const existing = inFlight.get(key);
  if (existing) return existing;

  counters.requests += 1;
  const promise = (async () => {
    const response = await fetch(`${API_BASE}/data/target-profile`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      signal: options.signal,
      body: JSON.stringify({
        project_id: request.projectId,
        dataset_id: request.datasetId ?? null,
        version_id: request.versionId ?? null,
        target: request.target,
        event_value: request.eventValue ?? null,
        non_event_value: request.nonEventValue ?? null,
        problem_type: request.problemType ?? "classification",
        include_iv: request.includeIv !== false,
        selected_columns: request.selectedColumns ?? [],
      }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) {
      const detail = payload?.detail;
      const structured =
        detail && typeof detail === "object" && detail.reason === FULL_ARTIFACT_MISSING
          ? (detail as FullArtifactMissingError)
          : null;
      throw new ProfileUnavailableError(
        structured?.message ??
          (typeof detail === "string" ? detail : "Target-dependent profiling is unavailable."),
        response.status,
        structured
      );
    }
    const result = payload as TargetProfileResult;
    results.set(key, result);
    return result;
  })();

  inFlight.set(key, promise);
  try {
    return await promise;
  } finally {
    inFlight.delete(key);
  }
}

// ---------------------------------------------------------------------------
// Display -- Part D precision rules
// ---------------------------------------------------------------------------

/**
 * Formats an IV for display.
 *
 * Root cause 3: the old `formatNumber` did `Number(value)`, and `Number(null)`
 * is `0`, which is finite -- so a genuinely unavailable IV rendered as the
 * highly misleading `0.0000`. This never coerces: null is "Not available", and
 * a positive value too small for four decimals is shown as "<0.0001" rather
 * than being rounded down to a zero it is not.
 */
export function formatIv(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Not available";
  if (value > 0 && value < 0.0001) return "<0.0001";
  return value.toFixed(4);
}

/** Full precision for the accessible detail / tooltip. */
export function formatIvExact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Not available";
  return value.toPrecision(12).replace(/0+$/, "").replace(/\.$/, "");
}

/** Cell text for any IV state, so a status never becomes a number. */
export function ivCellText(row: Pick<PredictorProfile, "iv" | "ivStatus">): string {
  if (row.ivStatus === "pending") return "Calculating";
  if (row.ivStatus === "available") return formatIv(row.iv);
  return IV_STATUS_LABELS[row.ivStatus] ?? "Not available";
}

/**
 * Rare-event-safe rate formatting for the Atlas Guide and page headers.
 *
 * Part I: a 0.2107% event rate must never round to "0.00%". Digits scale with
 * magnitude so a nonzero rate can never display as zero.
 */
export function formatEventRatePrecise(rate: number | null | undefined): string {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return "Not available";
  const percent = rate * 100;
  if (percent === 0) return "0%";
  if (percent >= 1) return `${percent.toFixed(2)}%`;
  if (percent >= 0.1) return `${percent.toFixed(4)}%`;
  if (percent >= 0.01) return `${percent.toFixed(4)}%`;
  if (percent >= 0.001) return `${percent.toFixed(5)}%`;
  return `${percent.toExponential(2)}%`;
}

// ---------------------------------------------------------------------------
// Part H: weak-signal automation safety
// ---------------------------------------------------------------------------

/** The configured ATLAS weak-signal threshold. Deliberately distinct from the
 *  0.02 "not predictive" descriptive band -- they answer different questions
 *  and must not be silently unified. */
export const WEAK_SIGNAL_IV_THRESHOLD = 0.01;
export const WEAK_SIGNAL_CORRELATION_THRESHOLD = 0.05;

export type WeakSignalPlan = {
  eligible: boolean;
  blockedReason: string | null;
  affected: string[];
  protectedFromRemoval: string[];
  threshold: number;
  scopeMode: ProfileScopeMode | null;
};

/**
 * Decides whether automatic weak-signal exclusion may run, and exactly which
 * predictors it would affect.
 *
 * Safety rules, all of which the previous implementation violated by treating a
 * null IV as zero: never act while pending, never act on preview_only or a
 * failed profile, and never deselect a predictor whose IV is merely unavailable.
 */
export function planWeakSignalExclusion(input: {
  profile: TargetProfileResult | null;
  loading: boolean;
  error: string | null;
  problemType: "classification" | "regression";
  selected: string[];
  correlations?: Record<string, number | null>;
}): WeakSignalPlan {
  const { profile, loading, error, problemType, selected } = input;
  const base: WeakSignalPlan = {
    eligible: false,
    blockedReason: null,
    affected: [],
    protectedFromRemoval: [],
    threshold: problemType === "regression" ? WEAK_SIGNAL_CORRELATION_THRESHOLD : WEAK_SIGNAL_IV_THRESHOLD,
    scopeMode: profile?.analysisScope.mode ?? null,
  };

  if (loading) return { ...base, blockedReason: "Target-dependent profiling is still running." };
  if (error) return { ...base, blockedReason: `Automatic exclusion is unavailable because profiling failed: ${error}` };
  if (!profile) return { ...base, blockedReason: "No authoritative predictor profile is available yet." };
  if (problemType === "classification" && profile.analysisScope.mode === "preview_only") {
    return {
      ...base,
      blockedReason:
        "This profile is browser-preview only. Automatic weak-signal exclusion is disabled because Information Value cannot be estimated from a preview.",
    };
  }
  if (profile.predictorSummary.evaluated === 0) {
    return { ...base, blockedReason: "No predictor produced an Information Value, so there is nothing to act on." };
  }

  const chosen = new Set(selected);
  const affected: string[] = [];
  const protectedFromRemoval: string[] = [];
  for (const row of profile.predictors) {
    if (!row.eligible || !chosen.has(row.predictor)) continue;
    if (row.ivStatus !== "available" || row.iv === null) {
      // Unavailable is NOT weak. A predictor is never dropped for a value that
      // was never computed.
      protectedFromRemoval.push(row.predictor);
      continue;
    }
    if (row.iv < base.threshold) affected.push(row.predictor);
  }
  return { ...base, eligible: true, affected, protectedFromRemoval };
}

// ---------------------------------------------------------------------------
// Part E/F: association strength vs automated leakage screening
// ---------------------------------------------------------------------------
//
// These answer DIFFERENT questions and must never be collapsed into one label.
// The old table showed a 3.28 IV in green next to Leakage Status "Eligible",
// which reads as unconditional approval of an association that in fact needs
// human review.

export const UNUSUALLY_STRONG_IV = 0.5;

export const HIGH_IV_EXPLANATION =
  "Very strong separation can be legitimate, but it can also indicate post-outcome information, " +
  "target leakage, unstable bins, or a variable that is unavailable at scoring time.";

export type SignalStrength = {
  key: string;
  label: string;
  reviewRecommended: boolean;
  tone: "neutral" | "info" | "warning";
};

/** Association strength only. Says nothing about leakage. */
export function signalStrength(row: Pick<PredictorProfile, "iv" | "ivStatus">): SignalStrength | null {
  if (row.ivStatus !== "available" || row.iv === null || !Number.isFinite(row.iv)) return null;
  const iv = row.iv;
  if (iv >= UNUSUALLY_STRONG_IV)
    return { key: "unusually_strong", label: "Unusually strong", reviewRecommended: true, tone: "warning" };
  if (iv >= 0.3) return { key: "strong", label: "Strong", reviewRecommended: false, tone: "info" };
  if (iv >= 0.1) return { key: "medium", label: "Medium", reviewRecommended: false, tone: "info" };
  if (iv >= 0.02) return { key: "weak", label: "Weak", reviewRecommended: false, tone: "neutral" };
  return { key: "not_predictive", label: "Not predictive", reviewRecommended: false, tone: "neutral" };
}

export type LeakageScreenState =
  | "no_automated_signal"
  | "review_recommended"
  | "likely_leakage"
  | "confirmed_leakage"
  | "not_applicable";

export const LEAKAGE_SCREEN_LABELS: Record<LeakageScreenState, string> = {
  no_automated_signal: "No automated leakage signal",
  review_recommended: "Review recommended",
  likely_leakage: "Likely leakage",
  confirmed_leakage: "Confirmed leakage",
  not_applicable: "Not applicable",
};

/**
 * Automated leakage screening, kept conservative.
 *
 * A high IV alone may raise `review_recommended`. It can NEVER produce
 * `likely_leakage` or `confirmed_leakage` -- those require a structural rule or
 * an explicit reviewer decision, neither of which this function has.
 */
export function leakageScreen(row: Pick<PredictorProfile, "iv" | "ivStatus" | "role" | "eligible">): LeakageScreenState {
  if (!row.eligible) return row.role === "potential_leakage" ? "review_recommended" : "not_applicable";
  if (row.ivStatus !== "available" || row.iv === null) return "no_automated_signal";
  return row.iv >= UNUSUALLY_STRONG_IV ? "review_recommended" : "no_automated_signal";
}

export type PredictorEvaluationCounts = {
  evaluated: number;
  unavailable: Array<{ predictor: string; reason: string }>;
  unusuallyStrong: number;
  leakageReview: number;
  targetExcluded: string | null;
  summaryText: string;
};

/**
 * Part F: counts by ANALYTICAL ROLE.
 *
 * The old "30 evaluated, 1 unavailable" counted the target itself as an
 * unavailable predictor, so the user could not tell whether a real predictor
 * had failed. The target and non-predictor roles are excluded entirely, and any
 * genuinely unavailable predictor is named with its reason.
 */
export function predictorEvaluationCounts(
  profile: TargetProfileResult | null,
  target: string
): PredictorEvaluationCounts {
  const rows = profile?.predictors ?? [];
  const predictors = rows.filter((row) => row.eligible && row.predictor !== target);
  const evaluated = predictors.filter((row) => row.ivStatus === "available");
  const unavailable = predictors
    .filter((row) => row.ivStatus !== "available")
    .map((row) => ({ predictor: row.predictor, reason: IV_STATUS_LABELS[row.ivStatus] ?? "Not available" }));
  const unusuallyStrong = evaluated.filter((row) => (row.iv ?? 0) >= UNUSUALLY_STRONG_IV).length;
  const leakageReview = predictors.filter((row) => leakageScreen(row) === "review_recommended").length;
  const summaryText = unavailable.length
    ? `${evaluated.length} predictors evaluated - ${unavailable.length} predictor${unavailable.length === 1 ? "" : "s"} unavailable`
    : `${evaluated.length} predictors evaluated`;
  return {
    evaluated: evaluated.length,
    unavailable,
    unusuallyStrong,
    leakageReview,
    targetExcluded: target || null,
    summaryText,
  };
}

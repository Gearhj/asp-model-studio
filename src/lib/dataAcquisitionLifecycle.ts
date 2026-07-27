// Data Acquisition lifecycle logic (UX-DATAACQ-001..004 + engaging-UX parts H1/H3).
//
// Everything here is pure and dependency-free so it can be unit tested directly
// (see tests/dataAcquisitionLifecycle.test.mjs) rather than only asserted against
// rendered source text. Step01_DataAcquisition.tsx holds the React wiring; the
// decisions -- which persistence UI applies, what readiness status the existing
// findings imply, which event rate is authoritative -- live here.
import type { DataQualitySummary } from "./enterpriseDataAccess";

/** The six source states the page must always be able to name (UX-DATAACQ-004 / Part C7). */
export type DatasetSourceKind =
  | "workspace-upload"
  | "registered-library-asset"
  | "existing-library-version"
  | "derived-dataset"
  | "scored-dataset"
  | "imported-unregistered";

export const DATASET_SOURCE_LABELS: Record<DatasetSourceKind, string> = {
  "workspace-upload": "Workspace Upload",
  "registered-library-asset": "Registered Dataset Library Asset",
  "existing-library-version": "Existing Library Version",
  "derived-dataset": "Derived Dataset",
  "scored-dataset": "Scored Dataset",
  "imported-unregistered": "Imported Unregistered Data",
};

export type DatasetLibraryLink = {
  datasetId: string;
  versionId: string;
  datasetName?: string;
  datasetRole?: string;
  sourceType?: string;
  ownerDisplayName?: string;
  rowCount?: number;
  columnCount?: number;
  linkedAt?: string;
};

/**
 * Resolves which of the six source states currently applies.
 *
 * The governing signal is whether the active data is backed by a *registered*
 * Dataset Library asset+version (an immutable governed identity), not the raw
 * source-type radio selection -- a SQL/Python/cloud import that resolves to a
 * registered asset is a registered asset, and an upload that was registered
 * during this session is no longer an unregistered workspace file.
 */
export function resolveDatasetSourceKind(input: {
  sourceType: "upload" | "existing" | "sql" | "cloud" | "python";
  libraryLink?: DatasetLibraryLink | null;
  registeredDatasetId?: string | null;
  isDerived?: boolean;
  isScored?: boolean;
}): DatasetSourceKind {
  if (input.isScored) return "scored-dataset";
  if (input.isDerived) return "derived-dataset";

  const hasGovernedIdentity = Boolean(input.libraryLink?.datasetId && input.libraryLink?.versionId);
  if (hasGovernedIdentity) {
    // Picking a version out of the Library reads as "Existing Library Version";
    // arriving at the same governed identity through any other path reads as
    // the broader "Registered Dataset Library Asset".
    return input.sourceType === "existing" ? "existing-library-version" : "registered-library-asset";
  }
  if (input.registeredDatasetId) return "registered-library-asset";
  if (input.sourceType === "upload") return "workspace-upload";
  return "imported-unregistered";
}

/**
 * Which persistence UI the Dataset Persistence section must render.
 *
 * "registered-status" is a read-only status panel -- offering "Project Workspace
 * Only" vs "Register in Dataset Library" for data that is *already* a registered
 * governed asset is the confusion reported in UX-DATAACQ-004, and implies a
 * duplicate-registration or overwrite risk that does not exist.
 */
export type PersistenceMode = "registered-status" | "choice" | "derived-choice";

export function resolvePersistenceMode(kind: DatasetSourceKind): PersistenceMode {
  switch (kind) {
    case "registered-library-asset":
    case "existing-library-version":
      return "registered-status";
    case "derived-dataset":
    case "scored-dataset":
      return "derived-choice";
    case "workspace-upload":
    case "imported-unregistered":
      return "choice";
  }
}

/** Registration verb, so a derived dataset is never described as overwriting its source (Part C4). */
export function resolveRegistrationActionLabel(kind: DatasetSourceKind, hasExistingAsset: boolean): string {
  if (kind === "scored-dataset") return "Register Scored Dataset";
  if (kind === "derived-dataset") return hasExistingAsset ? "Register as New Dataset Version" : "Register Derived Dataset";
  return "Register Development Dataset";
}

/** True when the given registered dataset/version is already the project's link (Part C6). */
export function isAlreadyLinked(
  libraryLink: DatasetLibraryLink | null | undefined,
  candidate: { datasetId: string; versionId: string }
): boolean {
  if (!libraryLink?.datasetId || !libraryLink?.versionId) return false;
  return libraryLink.datasetId === candidate.datasetId && libraryLink.versionId === candidate.versionId;
}

// ---------------------------------------------------------------------------
// Part D: readiness status derived from existing findings only
// ---------------------------------------------------------------------------

export type ReadinessStatus = "ready" | "ready_with_warnings" | "review_required" | "blocked";

export const READINESS_LABELS: Record<ReadinessStatus, string> = {
  ready: "Ready",
  ready_with_warnings: "Ready with Warnings",
  review_required: "Review Required",
  blocked: "Blocked",
};

export type ReadinessTone = "success" | "warning" | "danger" | "info";

export const READINESS_TONES: Record<ReadinessStatus, ReadinessTone> = {
  ready: "success",
  ready_with_warnings: "warning",
  review_required: "warning",
  blocked: "danger",
};

/**
 * QUALITY FINDINGS ONLY -- NOT the page lifecycle state.
 *
 * Part A closure: this function used to be a SECOND lifecycle derivation. Its
 * `.status` was rendered by the readiness checkpoint while the hero rendered a
 * different derivation, so "Ready with warnings" and "Blocked" could describe
 * one state at once. The single lifecycle authority is now
 * `deriveDataAcquisitionStatus()` in src/lib/dataAcquisitionStatus.ts.
 *
 * What survives here is the FINDINGS list (`reasons`) and a coarse severity used
 * only to order those findings. Nothing in Data Acquisition may render `.status`
 * as a lifecycle label or use it to gate progression -- an invariant asserted by
 * tests/dataAcquisitionStatus.test.mjs.
 *
 * No new quality rules are introduced: every branch below keys off a field that
 * quality profiling (browser or backend) already populates.
 *
 * Blocked is reserved for conditions that genuinely prevent modeling -- no
 * profile, no rows, no target, or a target with no usable variation. Leakage
 * candidates escalate to Review Required because a human must adjudicate them.
 */
export function computeReadinessStatus(input: {
  quality: DataQualitySummary | null;
  target: string;
  registeredRowCount: number;
  selectedPredictorCount: number;
  /** Governance scope of the profile the findings came from. Root cause 4: a
   *  zero event rate observed in a bounded preview must never be reported as a
   *  property of the registered population. */
  profileScopeMode?: "governed_version" | "workspace_draft" | "preview_only" | null;
  /** Authoritative event count, when a governed profile has resolved. */
  authoritativeEventCount?: number | null;
}): { status: ReadinessStatus; reasons: string[] } {
  const { quality, target, registeredRowCount, selectedPredictorCount } = input;
  const reasons: string[] = [];

  if (!quality) return { status: "blocked", reasons: ["Quality profiling has not been generated."] };
  if (!registeredRowCount) return { status: "blocked", reasons: ["No registered modeling rows are available."] };
  if (!target) return { status: "blocked", reasons: ["No target column is confirmed."] };
  if (!selectedPredictorCount) return { status: "blocked", reasons: ["No predictors are approved for modeling."] };

  // A no-events blocker is a claim about the REGISTERED POPULATION, so it may
  // only be raised from a population-scope profile. Previously any preview whose
  // 100 rows happened to contain no fraud events produced this blocker on a
  // dataset with 360 events.
  const eventRate = quality.classBalance?.eventRate;
  // Only an explicit preview scope suppresses the blocker. An UNKNOWN scope is
  // treated as population-scoped, because that was the old contract's meaning
  // and weakening it would let a real zero-event target through unblocked. The
  // defect is fixed by callers now declaring `preview_only` when that is true.
  const populationScoped = input.profileScopeMode !== "preview_only";
  const authoritativeEventCount = input.authoritativeEventCount;

  const governedHasEvents = typeof authoritativeEventCount === "number" && authoritativeEventCount > 0;

  if (eventRate === 0 && input.profileScopeMode === "preview_only") {
    // The honest message: say what the preview shows AND what the governed
    // population actually contains, instead of the false population claim.
    reasons.push(
      governedHasEvents
        ? `The browser preview contains no event records. The governed population contains ${authoritativeEventCount!.toLocaleString()} events and is used for target-dependent profiling.`
        : "The browser preview contains no event records. Target-dependent profiling uses the governed population instead."
    );
  } else if (eventRate === 0 && populationScoped && !governedHasEvents) {
    return { status: "blocked", reasons: ["The target has no events in the registered population."] };
  }

  if (quality.potentialLeakageColumns.length) {
    reasons.push(`${quality.potentialLeakageColumns.length} potential leakage candidate(s) require review.`);
  }
  if (quality.constantColumns.length) {
    reasons.push(`${quality.constantColumns.length} constant column(s) detected.`);
  }
  if (quality.duplicateRows) {
    reasons.push(`${quality.duplicateRows.toLocaleString()} duplicate row(s) detected.`);
  }
  const columnsWithMissing = quality.missing.filter((row) => row.percent > 0).length;
  if (columnsWithMissing) {
    reasons.push(`${columnsWithMissing} column(s) contain missing values.`);
  }
  if (quality.nearZeroVarianceColumns.length) {
    reasons.push(`${quality.nearZeroVarianceColumns.length} near-zero-variance column(s) detected.`);
  }
  if (quality.unexpectedDatatypeColumns.length) {
    reasons.push(`${quality.unexpectedDatatypeColumns.length} column(s) have unexpected datatypes.`);
  }
  if (typeof eventRate === "number" && eventRate > 0 && eventRate < 0.01) {
    reasons.push(`Rare-event target: ${formatEventRate(eventRate)} event rate.`);
  }
  if (quality.profileScope === "preview_profile") {
    reasons.push("Findings are based on a preview profile, not the full registered dataset.");
  }

  // Leakage candidates and a preview-only profile are the two findings a reviewer
  // must actively clear; everything else is a warning the analyst can proceed past.
  if (quality.potentialLeakageColumns.length || quality.profileScope === "preview_profile") {
    return { status: "review_required", reasons };
  }
  if (reasons.length) return { status: "ready_with_warnings", reasons };
  return { status: "ready", reasons: [] };
}

// ---------------------------------------------------------------------------
// Part F: authoritative event rate
// ---------------------------------------------------------------------------

/**
 * Rare-event-safe percentage formatting.
 *
 * `toFixed(2)` renders a genuine 0.21% event rate as "0.21%" but renders a
 * 0.0004 rate as "0.04%" and a 0.00004 rate as "0.00%" -- silently reporting
 * "no events" for a dataset that has them. Digits therefore scale with
 * magnitude so a nonzero rate never displays as zero.
 */
export function formatEventRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return "Not evaluated";
  const percent = rate * 100;
  if (percent === 0) return "0%";
  // Keep at least two significant digits below 1%, so 0.021% never collapses to
  // "0.02%" and 0.0021% never collapses to "0.00%".
  if (percent >= 0.1) return `${percent.toFixed(2)}%`;
  if (percent >= 0.01) return `${percent.toFixed(3)}%`;
  if (percent >= 0.001) return `${percent.toFixed(4)}%`;
  return `${percent.toExponential(2)}%`;
}

export type EventRateScope = "full_population" | "complete_browser_dataset" | "preview_only";

export const EVENT_RATE_SCOPE_LABELS: Record<EventRateScope, string> = {
  full_population: "Full registered population",
  complete_browser_dataset: "Complete browser dataset",
  preview_only: "Preview only",
};

/**
 * Picks the authoritative event rate for display.
 *
 * Root cause of the 0.00% vs 0.21% inconsistency in UX-DATAACQ/Part F: the
 * Target Profile computed its rate from the browser preview (~100 rows), which
 * for a 0.21% rare-event dataset usually contains zero events -> 0/100 -> 0.00%.
 * The Data Quality section meanwhile read the backend full-population profile
 * and correctly showed ~0.21%. Backend profiling therefore wins whenever it is
 * available, and a preview-derived rate is only ever returned explicitly
 * labelled "Preview only".
 */
export function resolveAuthoritativeEventRate(input: {
  quality: DataQualitySummary | null;
  previewEventRate: number | null;
  completeBrowserDataset: boolean;
}): { rate: number | null; scope: EventRateScope; isAuthoritative: boolean } {
  const backendRate = input.quality?.classBalance?.eventRate;
  if (input.quality?.profileScope === "full_dataset" && typeof backendRate === "number") {
    return { rate: backendRate, scope: "full_population", isAuthoritative: true };
  }
  if (input.completeBrowserDataset) {
    const rate = typeof backendRate === "number" ? backendRate : input.previewEventRate;
    return { rate, scope: "complete_browser_dataset", isAuthoritative: true };
  }
  return { rate: input.previewEventRate, scope: "preview_only", isAuthoritative: false };
}

// ---------------------------------------------------------------------------
// Part H1: dataset load milestones
// ---------------------------------------------------------------------------

export const DATASET_LOAD_STAGES = [
  "Authorizing dataset access",
  "Resolving dataset version",
  "Reading governed schema",
  "Profiling target and predictors",
  "Evaluating data quality",
  "Preparing browser preview",
  "Ready for modeling",
] as const;

export type DatasetLoadStage = (typeof DATASET_LOAD_STAGES)[number];

export type DatasetLoadPhase = "idle" | "loading" | "loaded" | "failed";

export type DatasetLoadProgress = {
  phase: DatasetLoadPhase;
  /** Index of the stage currently in flight, or the stage that failed. */
  activeStageIndex: number;
  failedStageIndex: number | null;
  error: string | null;
};

export const IDLE_LOAD_PROGRESS: DatasetLoadProgress = {
  phase: "idle",
  activeStageIndex: -1,
  failedStageIndex: null,
  error: null,
};

/**
 * Per-stage display state. Milestones are discrete and derived from real
 * observed progress -- there is deliberately no synthetic percentage, because
 * the backend cannot report intra-stage completion (Part H1 requirements 2/3).
 */
export type StageState = "pending" | "active" | "complete" | "failed";

export function resolveStageStates(progress: DatasetLoadProgress): StageState[] {
  return DATASET_LOAD_STAGES.map((_stage, index) => {
    if (progress.phase === "idle") return "pending";
    if (progress.phase === "loaded") return "complete";
    if (progress.phase === "failed") {
      if (progress.failedStageIndex === null) return "pending";
      if (index < progress.failedStageIndex) return "complete";
      if (index === progress.failedStageIndex) return "failed";
      return "pending";
    }
    if (index < progress.activeStageIndex) return "complete";
    if (index === progress.activeStageIndex) return "active";
    return "pending";
  });
}

/** Completed milestone count out of total -- segmented progress, not a fake percentage. */
export function summarizeLoadProgress(progress: DatasetLoadProgress): { completed: number; total: number; label: string } {
  const states = resolveStageStates(progress);
  const completed = states.filter((state) => state === "complete").length;
  const total = DATASET_LOAD_STAGES.length;
  if (progress.phase === "idle") return { completed: 0, total, label: "Not started" };
  if (progress.phase === "loaded") return { completed: total, total, label: `${total} of ${total} milestones complete` };
  if (progress.phase === "failed") {
    return { completed, total, label: `Failed at ${DATASET_LOAD_STAGES[progress.failedStageIndex ?? 0]}` };
  }
  return { completed, total, label: `${DATASET_LOAD_STAGES[progress.activeStageIndex] ?? "Working"}...` };
}

// ---------------------------------------------------------------------------
// Part H3: target distribution from authoritative aggregates
// ---------------------------------------------------------------------------

export type ClassDistributionRow = { value: unknown; count: number; percent: number };

export type TargetDistribution = {
  target: string;
  eventValue: string;
  nonEventValue: string;
  eventCount: number;
  eventPercent: number;
  nonEventCount: number;
  nonEventPercent: number;
  imbalanceRatio: number | null;
  totalRows: number;
  isRareEvent: boolean;
};

/**
 * Folds a governed class distribution into event vs non-event using the
 * project's explicit event value. Any class that is not the event value is
 * aggregated into non-event, so multi-valued encodings still produce an honest
 * binary view rather than silently dropping classes.
 */
export function buildTargetDistribution(input: {
  target: string;
  classDistribution: ClassDistributionRow[] | null | undefined;
  eventValue: unknown;
  nonEventValue?: unknown;
}): TargetDistribution | null {
  const rows = input.classDistribution;
  if (!input.target || !Array.isArray(rows) || rows.length < 2) return null;

  const totalRows = rows.reduce((sum, row) => sum + (Number(row.count) || 0), 0);
  if (!totalRows) return null;

  const eventKey = input.eventValue === null || input.eventValue === undefined ? null : String(input.eventValue);
  const resolvedEventKey =
    eventKey !== null && rows.some((row) => String(row.value) === eventKey)
      ? eventKey
      // Without an explicit event value, the minority class is the event -- the
      // same convention the existing browser-side target profiling uses.
      : String([...rows].sort((a, b) => (Number(a.count) || 0) - (Number(b.count) || 0))[0]?.value);

  const eventCount = rows
    .filter((row) => String(row.value) === resolvedEventKey)
    .reduce((sum, row) => sum + (Number(row.count) || 0), 0);
  const nonEventCount = totalRows - eventCount;

  const nonEventLabel =
    rows.length === 2
      ? String(rows.find((row) => String(row.value) !== resolvedEventKey)?.value ?? "")
      : input.nonEventValue !== undefined && input.nonEventValue !== null && String(input.nonEventValue)
        ? String(input.nonEventValue)
        : `Not ${resolvedEventKey}`;

  const eventPercent = eventCount / totalRows;
  return {
    target: input.target,
    eventValue: resolvedEventKey,
    nonEventValue: nonEventLabel,
    eventCount,
    eventPercent,
    nonEventCount,
    nonEventPercent: nonEventCount / totalRows,
    imbalanceRatio: eventCount ? nonEventCount / eventCount : null,
    totalRows,
    isRareEvent: eventPercent > 0 && eventPercent < 0.01,
  };
}

/**
 * Class counts from in-memory rows.
 *
 * Only safe to call when the browser genuinely holds the complete registered
 * dataset -- callers must not pass a bounded preview, because the resulting
 * counts would misrepresent the modeling population.
 */
export function computeClassDistributionFromRows(
  rows: Record<string, unknown>[],
  target: string
): ClassDistributionRow[] | null {
  if (!target || !rows.length) return null;
  const counts = new Map<string, number>();
  for (const row of rows) {
    const raw = row[target];
    if (raw === null || raw === undefined || String(raw).trim() === "") continue;
    const key = String(raw);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  if (counts.size < 2 || counts.size > 20) return null;
  const total = Array.from(counts.values()).reduce((sum, count) => sum + count, 0);
  if (!total) return null;
  return Array.from(counts.entries()).map(([value, count]) => ({ value, count, percent: count / total }));
}

export type DistributionViewMode = "population" | "rare-event";

/** Only offered when the event bar would be visually unreadable at true scale. */
export function shouldOfferRareEventView(distribution: TargetDistribution | null): boolean {
  return Boolean(distribution && distribution.eventPercent > 0 && distribution.eventPercent < 0.05);
}

export const RARE_EVENT_SCALE_DISCLOSURE =
  "Visual scale is adjusted so the minority class is legible. Bar lengths in this view do not represent true relative magnitude.";

export const RARE_EVENT_TAKEAWAY =
  "Rare-event target detected. Accuracy may be misleading. Emphasize PR-AUC, recall, precision, F1, KS, lift, and calibration.";

/** Text equivalent of the chart, so the accessible summary always matches the plotted values. */
export function describeTargetDistribution(distribution: TargetDistribution | null): string {
  if (!distribution) return "Target distribution is not available.";
  const parts = [
    `Target ${distribution.target}.`,
    `Event value ${distribution.eventValue}: ${distribution.eventCount.toLocaleString()} rows, ${formatEventRate(distribution.eventPercent)}.`,
    `Non-event value ${distribution.nonEventValue}: ${distribution.nonEventCount.toLocaleString()} rows, ${formatEventRate(distribution.nonEventPercent)}.`,
    `Total rows ${distribution.totalRows.toLocaleString()}.`,
  ];
  if (distribution.imbalanceRatio !== null) {
    parts.push(`Imbalance ratio ${distribution.imbalanceRatio.toFixed(1)} non-events per event.`);
  }
  return parts.join(" ");
}

// One authoritative Data Acquisition status model.
//
// PROVEN ROOT CAUSE of the contradictory labels (all three were live at once):
//
//   1. Hero "Dataset"            Step01:1465  `fileName || "Not registered"`
//      Keyed on an UPLOAD FILENAME, never on registration state. A registered
//      Dataset Library version that is selected but not yet loaded has no
//      filename, so the page called a governed, linked asset "Not registered".
//
//   2. Hero "Modeling Readiness" Step01:1469  `nextDisabledReason ? ... : "Ready"`
//      `dataAcquisitionDisabledReason` only inspects isImporting / hasHeaders /
//      hasTarget / importError / predictor count. It never consults the governed
//      profile or any quality finding, so it reported "Ready" while findings
//      were outstanding.
//
//   3. Strip "Quality reviewed"  Step01:1503  `readiness.status` mapping
//      A DIFFERENT derivation (`computeReadinessStatus`) that DOES consult
//      quality findings, and a third rendering of the same idea in the
//      checkpoint panel (`READINESS_LABELS[readiness.status]`).
//
// Two derivations of "is this page ready", rendered in three places, with no
// shared source. That is why "Ready", "Blocked", and "Ready with Warnings"
// could all appear simultaneously for one underlying state.
//
// This module is the single derivation. Every visible Data Acquisition status
// must read from `deriveDataAcquisitionStatus`.

export type DataLoadState = "not_selected" | "selected_not_loaded" | "loading" | "loaded" | "failed";

export type AnalyticalReadiness = "unavailable" | "blocked" | "ready_with_warnings" | "ready";

export type UserReviewState = "not_started" | "review_required" | "completed";

export type RegistrationState = "unknown" | "registered" | "unregistered_upload";

export type ProjectLinkState = "unknown" | "linked" | "not_linked";

export type StatusTone = "success" | "info" | "warning" | "danger" | "neutral";

export type DataAcquisitionStatus = {
  loadState: DataLoadState;
  readiness: AnalyticalReadiness;
  reviewState: UserReviewState;
  registrationState: RegistrationState;
  linkState: ProjectLinkState;
  /** Progression is allowed. False only for genuine blockers. */
  canContinue: boolean;
  /** Non-empty ONLY when progression is genuinely impossible. */
  blockingReasons: string[];
  /** Findings that need attention but never prevent progression. */
  warnings: string[];
  recommendedAction: string;
  currentActiveMilestone: string;
  /** Labels + tones, so no caller invents its own wording or colour. */
  loadLabel: string;
  readinessLabel: string;
  reviewLabel: string;
  readinessTone: StatusTone;
  loadTone: StatusTone;
  reviewTone: StatusTone;
  /** Bottom action text, derived from the same state as everything else. */
  continueLabel: string;
};

export const LOAD_STATE_LABELS: Record<DataLoadState, string> = {
  not_selected: "No dataset selected",
  selected_not_loaded: "Selected, not loaded",
  loading: "Loading",
  loaded: "Version loaded",
  failed: "Load failed",
};

export const READINESS_STATE_LABELS: Record<AnalyticalReadiness, string> = {
  unavailable: "Not evaluated",
  blocked: "Blocked",
  ready_with_warnings: "Ready with warnings",
  ready: "Ready",
};

export const REVIEW_STATE_LABELS: Record<UserReviewState, string> = {
  not_started: "Not started",
  review_required: "Review required",
  completed: "Complete",
};

// Part D: one tone per state, used everywhere. Amber never means success and
// green never means "warnings outstanding".
const READINESS_TONE: Record<AnalyticalReadiness, StatusTone> = {
  unavailable: "neutral",
  blocked: "danger",
  ready_with_warnings: "warning",
  ready: "success",
};

const LOAD_TONE: Record<DataLoadState, StatusTone> = {
  not_selected: "neutral",
  selected_not_loaded: "info",
  loading: "info",
  loaded: "success",
  failed: "danger",
};

const REVIEW_TONE: Record<UserReviewState, StatusTone> = {
  not_started: "neutral",
  review_required: "warning",
  completed: "success",
};

export type DataAcquisitionStatusInput = {
  /** A Dataset Library version is chosen (datasetId + versionId present). */
  hasSelectedVersion: boolean;
  /** The selection is a registered Library asset rather than an ad-hoc upload. */
  isRegisteredAsset: boolean;
  /** The dataset is linked to the current project. */
  isLinkedToProject: boolean;
  /** The backend holds the population (headers present and backend synced). */
  isLoaded: boolean;
  isLoading: boolean;
  loadError?: string | null;
  target: string;
  eventValue?: unknown;
  nonEventValue?: unknown;
  selectedPredictorCount: number;
  /** Governed profile outcome, when one has resolved. */
  profilePhase?: "idle" | "quality" | "iv" | "ready" | "failed" | "artifact_missing";
  profileError?: string | null;
  authoritativeEventCount?: number | null;
  authoritativeNonEventCount?: number | null;
  duplicateRows?: number | null;
  columnsWithMissingValues?: number | null;
  unusuallyStrongPredictorCount?: number | null;
  isRareEvent?: boolean;
  /** Set once the user completes the page's review action. */
  reviewCompleted: boolean;
};

/**
 * Derives every Data Acquisition status from one input set.
 *
 * The three dimensions are deliberately independent: a dataset can be LOADED
 * (green) while readiness is READY WITH WARNINGS (amber) and review is REVIEW
 * REQUIRED (amber). Those are not contradictions -- they answer different
 * questions. What the page must never do is answer the SAME question two ways.
 */
export function deriveDataAcquisitionStatus(input: DataAcquisitionStatusInput): DataAcquisitionStatus {
  const registrationState: RegistrationState = !input.hasSelectedVersion
    ? "unknown"
    : input.isRegisteredAsset
      ? "registered"
      : "unregistered_upload";
  const linkState: ProjectLinkState = !input.hasSelectedVersion
    ? "unknown"
    : input.isLinkedToProject
      ? "linked"
      : "not_linked";

  const loadState: DataLoadState = input.loadError
    ? "failed"
    : input.isLoading
      ? "loading"
      : input.isLoaded
        ? "loaded"
        : input.hasSelectedVersion
          ? "selected_not_loaded"
          : "not_selected";

  // --- Blocking conditions. Each genuinely prevents progression. ----------
  const blockingReasons: string[] = [];
  if (loadState === "not_selected") {
    blockingReasons.push("Select a Dataset Version before continuing.");
  }
  if (loadState === "failed") {
    blockingReasons.push(input.loadError || "The dataset could not be loaded.");
  }
  if (input.profilePhase === "artifact_missing") {
    blockingReasons.push(
      "This Dataset Version has no complete data artifact, so full-population profiling cannot run."
    );
  }
  if (input.profilePhase === "failed") {
    blockingReasons.push(input.profileError || "The required full-population profile failed.");
  }
  if (loadState === "loaded" && !input.target) {
    blockingReasons.push("Confirm the target variable before continuing.");
  }
  if (
    loadState === "loaded" &&
    input.target &&
    input.eventValue !== undefined &&
    input.nonEventValue !== undefined &&
    input.eventValue !== null &&
    input.nonEventValue !== null &&
    String(input.eventValue).trim() === String(input.nonEventValue).trim()
  ) {
    blockingReasons.push("The event value and non-event value cannot be the same.");
  }
  if (input.profilePhase === "ready") {
    if (input.authoritativeEventCount === 0) {
      blockingReasons.push("The authoritative population contains no events for the configured event value.");
    }
    if (input.authoritativeNonEventCount === 0) {
      blockingReasons.push("The authoritative population contains no non-events for the configured event value.");
    }
  }
  if (loadState === "loaded" && input.selectedPredictorCount === 0) {
    blockingReasons.push("Approve at least one eligible predictor before continuing.");
  }

  // --- Warnings. None of these ever block. -------------------------------
  const warnings: string[] = [];
  if (input.duplicateRows) {
    warnings.push(
      `${input.duplicateRows.toLocaleString()} duplicate row(s) detected. Reviewed later during data treatment.`
    );
  }
  if (input.columnsWithMissingValues) {
    warnings.push(
      `${input.columnsWithMissingValues.toLocaleString()} column(s) contain missing values. Treated on the Missing Values step.`
    );
  }
  if (input.isRareEvent) {
    warnings.push("Rare-event target prevalence. Stratified splitting and rank-based metrics are required downstream.");
  }
  if (input.unusuallyStrongPredictorCount) {
    warnings.push(
      `${input.unusuallyStrongPredictorCount} predictor(s) show unusually strong association and require human review for leakage or scoring-time availability.`
    );
  }

  // --- Analytical readiness ----------------------------------------------
  let readiness: AnalyticalReadiness;
  if (blockingReasons.length) {
    readiness = "blocked";
  } else if (loadState !== "loaded" || !input.profilePhase || input.profilePhase === "idle") {
    readiness = "unavailable";
  } else if (input.profilePhase === "quality" || input.profilePhase === "iv") {
    readiness = "unavailable";
  } else {
    readiness = warnings.length ? "ready_with_warnings" : "ready";
  }

  // --- User review --------------------------------------------------------
  // Review is a USER action, not an analytical verdict. It is "review required"
  // (amber), never "blocked" (red), whenever the analysis is available and the
  // user has not yet acknowledged it.
  const reviewState: UserReviewState = input.reviewCompleted
    ? "completed"
    : readiness === "ready_with_warnings" || readiness === "ready"
      ? "review_required"
      : "not_started";

  const canContinue = blockingReasons.length === 0 && readiness !== "unavailable";

  // --- Recommended action and active milestone ----------------------------
  let recommendedAction: string;
  let currentActiveMilestone: string;
  if (loadState === "not_selected") {
    recommendedAction = "Select a governed Dataset Version to begin.";
    currentActiveMilestone = "Select a source";
  } else if (loadState === "selected_not_loaded") {
    recommendedAction = "Load the selected Dataset Version.";
    currentActiveMilestone = "Load required";
  } else if (loadState === "loading") {
    recommendedAction = "ATLAS is loading the governed Dataset Version.";
    currentActiveMilestone = "Loading the registered population";
  } else if (loadState === "failed") {
    recommendedAction = "Resolve the load failure, then retry.";
    currentActiveMilestone = "Load failed";
  } else if (input.profilePhase === "quality" || input.profilePhase === "iv") {
    recommendedAction = "Full-population profiling is running.";
    currentActiveMilestone = input.profilePhase === "quality" ? "Profiling data quality" : "Calculating predictor associations";
  } else if (blockingReasons.length) {
    recommendedAction = blockingReasons[0];
    currentActiveMilestone = "Blocked";
  } else if (reviewState === "completed") {
    recommendedAction = "Data Acquisition is complete. Continue to Exploratory Data Analysis.";
    currentActiveMilestone = "Complete";
  } else if (warnings.length) {
    recommendedAction = "Review the quality findings and predictor associations, then continue.";
    currentActiveMilestone = "Review required";
  } else {
    recommendedAction = "Mark Data Acquisition complete and continue to Exploratory Data Analysis.";
    currentActiveMilestone = "Ready";
  }

  const continueLabel = !canContinue
    ? "Resolve blockers to continue"
    : reviewState === "completed"
      ? "Continue to EDA"
      : warnings.length
        ? "Acknowledge Warnings & Continue to EDA"
        : "Mark Complete & Continue to EDA";

  return {
    loadState,
    readiness,
    reviewState,
    registrationState,
    linkState,
    canContinue,
    blockingReasons,
    warnings,
    recommendedAction,
    currentActiveMilestone,
    loadLabel: LOAD_STATE_LABELS[loadState],
    readinessLabel: READINESS_STATE_LABELS[readiness],
    reviewLabel: REVIEW_STATE_LABELS[reviewState],
    readinessTone: READINESS_TONE[readiness],
    loadTone: LOAD_TONE[loadState],
    reviewTone: REVIEW_TONE[reviewState],
    continueLabel,
  };
}

/** Part C: truthful registration wording. A registered Library asset is never
 *  described as "Not registered" merely because it has no upload filename. */
export function registrationLabel(state: RegistrationState): string {
  if (state === "registered") return "Registered";
  if (state === "unregistered_upload") return "Not registered";
  return "Not selected";
}

export function projectLinkLabel(state: ProjectLinkState): string {
  if (state === "linked") return "Linked";
  if (state === "not_linked") return "Not linked";
  return "Not selected";
}

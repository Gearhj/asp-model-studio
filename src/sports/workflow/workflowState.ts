// Scientist-first MLB PROGRAM workflow state (Phase 6D): 9 canonical program stages, each a real
// scientist activity or governed decision. The detailed 15-stage PA Modeling Cockpit is nested
// inside Program Stage 3 (PA Model Development) and is NOT counted as program stages.
//
// Honest project-evidence semantics (from Phase 6C.1): existing WORKSPACE evidence is not the same
// as PROJECT-ADOPTED evidence, which is not the same as a COMPLETE program stage. Forecast contracts
// are backend-authoritative; localStorage is only a project-scoped compatibility cache for legacy
// records. Dataset binding and per-stage adoptions retain their existing local workflow persistence.
import type { ActiveSportsDataset } from "../sportsEvidenceApi";

// ---------------------------------------------------------------------------- persisted artifacts
export type TemporalDesignMode = "SEASON_ROLES" | "CUSTOM_DATES_ROLLING_ORIGIN";

export type ForecastDateRange = {
  startDate: string;
  endDate: string;
};

export type ForecastContractCoverage = {
  earliestDate: string;
  latestDate: string;
  registrationId: string;
  datasetId: string;
  datasetVersionId: string;
  manifestSha: string;
  family?: string;
  populationId?: string;
  rowCount?: number;
  partitionCount?: number;
};

export type ChronologicalValidationRequirement = {
  required: true;
  configurationStage: "VALIDATION_CALIBRATION";
  foldCount: 5;
  window: "EXPANDING";
  validationBlocks: "DATE_ATOMIC";
  grouping: "CANONICAL_GAME";
  shuffle: false;
  preprocessing: "FOLD_LOCAL";
  boundaryOptions: ["BALANCED_BY_GAME_COUNT", "MANUAL_DATE_RANGES"];
  finalOotUse: "REPORTING_ONLY";
  exactBoundaries: null;
};

export const DEFERRED_CHRONOLOGICAL_VALIDATION: ChronologicalValidationRequirement = {
  required: true,
  configurationStage: "VALIDATION_CALIBRATION",
  foldCount: 5,
  window: "EXPANDING",
  validationBlocks: "DATE_ATOMIC",
  grouping: "CANONICAL_GAME",
  shuffle: false,
  preprocessing: "FOLD_LOCAL",
  boundaryOptions: ["BALANCED_BY_GAME_COUNT", "MANUAL_DATE_RANGES"],
  finalOotUse: "REPORTING_ONLY",
  exactBoundaries: null,
};

export type ForecastContract = {
  projectId: string;
  version: number;
  target: string;
  lifecycle: string;
  /** Missing on legacy records; absence is normalized to SEASON_ROLES. */
  temporalDesignMode?: TemporalDesignMode;
  developmentSeasons?: number[];
  validationSeason?: number | null;
  frozenSeason?: number | null;
  prospectiveSeason?: number | null;
  eligibleEvidence?: ForecastDateRange | null;
  developmentSelection?: ForecastDateRange | null;
  finalOot?: ForecastDateRange | null;
  chronologicalValidation?: ChronologicalValidationRequirement;
  coverageAuthority?: ForecastContractCoverage | null;
  evidenceMode: "STRICT" | "ENHANCED";
  intendedOutputs: string[];
  researchPurpose: string;
  notes: string;
  savedAt: string;
};

export type DatasetBinding = {
  projectId: string;
  registrationId: string;
  datasetId: string;
  manifestSha: string;
  seasons: number[];
  boundAt: string;
};

export type CustomTemporalValidation = {
  valid: boolean;
  fieldErrors: Partial<Record<
    | "eligibleEvidenceStart"
    | "eligibleEvidenceEnd"
    | "developmentSelectionStart"
    | "developmentSelectionEnd"
    | "finalOotStart"
    | "finalOotEnd",
    string
  >>;
  errors: string[];
  missingIntervals: ForecastDateRange[];
  coverageMessage: string | null;
};

const CONTRACT_PREFIX = "asp-sports-forecast-contract:";
const BINDING_PREFIX = "asp-sports-dataset-binding:";
const PROGRAM_ADOPTION_PREFIX = "asp-sports-program-adoptions:"; // Phase 6D 9-stage adoptions
const LEGACY_ADOPTION_PREFIX = "asp-sports-stage-adoptions:";    // Phase 6C 12-stage adoptions

// Old (12-stage) → new (9-stage) adoption mapping. Old 4 (Hitter & Pitcher State) is relocated into
// cockpit Feature Engineering and is not a program stage, so it maps to nothing.
const LEGACY_ADOPTION_MAP: Record<number, number> = { 3: 2, 6: 3, 5: 4, 7: 5, 8: 6, 9: 7, 10: 7, 11: 8, 12: 9 };
// Backward-compatible deep-link mapping for old ?step=N bookmarks.
export const LEGACY_STEP_TO_STAGE: Record<number, number> = { 1: 1, 2: 2, 3: 2, 4: 3, 5: 4, 6: 3, 7: 5, 8: 6, 9: 7, 10: 7, 11: 8, 12: 9 };

export function loadContract(projectId: string): ForecastContract | null {
  try {
    const raw = JSON.parse(localStorage.getItem(`${CONTRACT_PREFIX}${projectId}`) || "null");
    return normalizeForecastContract(raw, projectId);
  } catch {
    return null;
  }
}
/** Compatibility cache only. The backend forecast-contract endpoint is authoritative. */
export function saveContract(contract: ForecastContract) {
  localStorage.setItem(`${CONTRACT_PREFIX}${contract.projectId}`, JSON.stringify(normalizeForecastContract(contract, contract.projectId)));
}

export function normalizeForecastContract(value: unknown, expectedProjectId = ""): ForecastContract | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<ForecastContract>;
  const projectId = String(raw.projectId || "").trim();
  if (!projectId || (expectedProjectId && projectId !== expectedProjectId)) return null;
  const mode: TemporalDesignMode = raw.temporalDesignMode === "CUSTOM_DATES_ROLLING_ORIGIN"
    ? "CUSTOM_DATES_ROLLING_ORIGIN"
    : "SEASON_ROLES";
  const range = (candidate: unknown): ForecastDateRange | null => {
    if (!candidate || typeof candidate !== "object") return null;
    const item = candidate as Partial<ForecastDateRange>;
    return { startDate: String(item.startDate || ""), endDate: String(item.endDate || "") };
  };
  const flatRange = (candidate: unknown, start: unknown, end: unknown): ForecastDateRange | null => {
    const nested = range(candidate);
    if (nested) return nested;
    if (typeof start !== "string" && typeof end !== "string") return null;
    return { startDate: String(start || ""), endDate: String(end || "") };
  };
  const custom = mode === "CUSTOM_DATES_ROLLING_ORIGIN";
  return {
    projectId,
    version: Number.isInteger(raw.version) && Number(raw.version) >= 0 ? Number(raw.version) : 0,
    target: String(raw.target || "Plate-Appearance Outcome"),
    lifecycle: String(raw.lifecycle || "Pregame — Final"),
    temporalDesignMode: mode,
    developmentSeasons: custom ? [] : Array.isArray(raw.developmentSeasons)
      ? raw.developmentSeasons.filter((item): item is number => Number.isInteger(item))
      : [...DEFAULT_TEMPORAL.developmentSeasons],
    validationSeason: custom ? null : Number.isInteger(raw.validationSeason) ? Number(raw.validationSeason) : DEFAULT_TEMPORAL.validationSeason,
    frozenSeason: custom ? null : Number.isInteger(raw.frozenSeason) ? Number(raw.frozenSeason) : DEFAULT_TEMPORAL.frozenSeason,
    prospectiveSeason: custom ? null : Number.isInteger(raw.prospectiveSeason) ? Number(raw.prospectiveSeason) : DEFAULT_TEMPORAL.prospectiveSeason,
    eligibleEvidence: flatRange(raw.eligibleEvidence, (raw as any).eligibleEvidenceStart, (raw as any).eligibleEvidenceEnd),
    developmentSelection: flatRange(raw.developmentSelection, (raw as any).developmentSelectionStart, (raw as any).developmentSelectionEnd),
    finalOot: flatRange(raw.finalOot, (raw as any).finalOotStart, (raw as any).finalOotEnd),
    chronologicalValidation: raw.chronologicalValidation?.required === true
      ? raw.chronologicalValidation
      : DEFERRED_CHRONOLOGICAL_VALIDATION,
    coverageAuthority: raw.coverageAuthority ?? (raw as any).sourceAuthority ?? null,
    evidenceMode: raw.evidenceMode === "ENHANCED" ? "ENHANCED" : "STRICT",
    intendedOutputs: Array.isArray(raw.intendedOutputs) ? raw.intendedOutputs.map(String) : [],
    researchPurpose: String(raw.researchPurpose || ""),
    notes: String(raw.notes || ""),
    savedAt: String(raw.savedAt || (raw as any).registeredAt || ""),
  };
}

export function temporalDesignMode(contract: ForecastContract | null | undefined): TemporalDesignMode {
  return contract?.temporalDesignMode === "CUSTOM_DATES_ROLLING_ORIGIN"
    ? "CUSTOM_DATES_ROLLING_ORIGIN"
    : "SEASON_ROLES";
}

export function isCanonicalIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day;
}

function addIsoDays(value: string, days: number): string {
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day + days));
  return parsed.toISOString().slice(0, 10);
}

export function missingCoverageIntervals(requested: ForecastDateRange, coverage: ForecastContractCoverage): ForecastDateRange[] {
  if (!isCanonicalIsoDate(requested.startDate) || !isCanonicalIsoDate(requested.endDate)
      || !isCanonicalIsoDate(coverage.earliestDate) || !isCanonicalIsoDate(coverage.latestDate)) return [];
  const missing: ForecastDateRange[] = [];
  if (requested.startDate < coverage.earliestDate) {
    missing.push({ startDate: requested.startDate, endDate: requested.endDate < coverage.earliestDate ? requested.endDate : addIsoDays(coverage.earliestDate, -1) });
  }
  if (requested.endDate > coverage.latestDate) {
    missing.push({ startDate: requested.startDate > coverage.latestDate ? requested.startDate : addIsoDays(coverage.latestDate, 1), endDate: requested.endDate });
  }
  return missing.filter((item) => item.startDate <= item.endDate);
}

export function seasonRoleCoverageError(
  developmentStart: number,
  frozenSeason: number,
  coverage: ForecastContractCoverage | null,
): string | null {
  if (!coverage || !isCanonicalIsoDate(coverage.earliestDate) || !isCanonicalIsoDate(coverage.latestDate)) {
    return "Registered source date coverage is unavailable. Forecast-contract registration is blocked.";
  }
  const earliestYear = Number(coverage.earliestDate.slice(0, 4));
  const latestYear = Number(coverage.latestDate.slice(0, 4));
  if (developmentStart < earliestYear) {
    return `Registered source evidence currently begins on ${coverage.earliestDate}. Development season ${developmentStart} is not available in the Data Warehouse.`;
  }
  if (frozenSeason > latestYear) {
    return `Registered source evidence currently ends on ${coverage.latestDate}. Frozen final season ${frozenSeason} is not available in the Data Warehouse. Missing interval: ${addIsoDays(coverage.latestDate, 1)} through ${frozenSeason}-12-31.`;
  }
  return null;
}

export function validateCustomTemporalDesign(input: {
  eligibleEvidence: ForecastDateRange;
  developmentSelection: ForecastDateRange;
  finalOot: ForecastDateRange;
}, coverage: ForecastContractCoverage | null): CustomTemporalValidation {
  const fieldErrors: CustomTemporalValidation["fieldErrors"] = {};
  const values = [
    ["eligibleEvidenceStart", input.eligibleEvidence.startDate],
    ["eligibleEvidenceEnd", input.eligibleEvidence.endDate],
    ["developmentSelectionStart", input.developmentSelection.startDate],
    ["developmentSelectionEnd", input.developmentSelection.endDate],
    ["finalOotStart", input.finalOot.startDate],
    ["finalOotEnd", input.finalOot.endDate],
  ] as const;
  for (const [field, value] of values) {
    if (!isCanonicalIsoDate(value)) fieldErrors[field] = "Enter a valid calendar date.";
  }
  const errors: string[] = [];
  const comparable = Object.keys(fieldErrors).length === 0;
  if (comparable) {
    if (input.eligibleEvidence.startDate > input.eligibleEvidence.endDate) errors.push("Eligible evidence start must not be after its end.");
    if (input.developmentSelection.startDate > input.developmentSelection.endDate) errors.push("Development and model-selection start must not be after its end.");
    if (input.finalOot.startDate > input.finalOot.endDate) errors.push("Final OOT start must not be after its end.");
    if (input.developmentSelection.startDate < input.eligibleEvidence.startDate || input.developmentSelection.endDate > input.eligibleEvidence.endDate) {
      errors.push("Development and model selection must lie within the eligible evidence range.");
    }
    if (input.finalOot.startDate < input.eligibleEvidence.startDate || input.finalOot.endDate > input.eligibleEvidence.endDate) {
      errors.push("Final OOT must lie within the eligible evidence range.");
    }
    if (input.finalOot.startDate <= input.developmentSelection.endDate) {
      errors.push("Final OOT must begin after development and model selection ends; the ranges must not overlap.");
    }
  }
  const missingIntervals = comparable && coverage ? missingCoverageIntervals(input.eligibleEvidence, coverage) : [];
  let coverageMessage: string | null = null;
  if (!coverage) {
    coverageMessage = "Registered source date coverage is unavailable. Forecast-contract registration is blocked.";
  } else if (missingIntervals.length) {
    const requestedEnd = input.eligibleEvidence.endDate;
    const future = requestedEnd > coverage.latestDate;
    coverageMessage = future
      ? `Registered source evidence currently ends on ${coverage.latestDate}. The requested ${requestedEnd.slice(0, 4)} evaluation period is not available in the Data Warehouse.`
      : `Registered source evidence currently begins on ${coverage.earliestDate}. The requested evidence period is not available in the Data Warehouse.`;
  }
  return {
    valid: Object.keys(fieldErrors).length === 0 && errors.length === 0 && coverageMessage === null,
    fieldErrors,
    errors,
    missingIntervals,
    coverageMessage,
  };
}
export function loadBinding(projectId: string): DatasetBinding | null {
  try {
    const raw = JSON.parse(localStorage.getItem(`${BINDING_PREFIX}${projectId}`) || "null");
    return raw?.projectId === projectId ? (raw as DatasetBinding) : null;
  } catch {
    return null;
  }
}
export function saveBinding(binding: DatasetBinding) {
  localStorage.setItem(`${BINDING_PREFIX}${binding.projectId}`, JSON.stringify(binding));
}

/** Program-stage adoptions (9-stage). Migrates 12-stage adoptions on first read; never destroys the
 *  legacy key, so no project progress is lost. */
export function loadAdoptions(projectId: string): number[] {
  try {
    const rawNew = localStorage.getItem(`${PROGRAM_ADOPTION_PREFIX}${projectId}`);
    if (rawNew != null) {
      const arr = JSON.parse(rawNew);
      return Array.isArray(arr) ? arr.filter((n) => typeof n === "number") : [];
    }
    const rawOld = localStorage.getItem(`${LEGACY_ADOPTION_PREFIX}${projectId}`);
    if (rawOld != null) {
      const old = JSON.parse(rawOld);
      const mapped = Array.isArray(old)
        ? [...new Set(old.map((n: number) => LEGACY_ADOPTION_MAP[n]).filter((n): n is number => typeof n === "number"))].sort((a, b) => a - b)
        : [];
      localStorage.setItem(`${PROGRAM_ADOPTION_PREFIX}${projectId}`, JSON.stringify(mapped));
      return mapped;
    }
    return [];
  } catch {
    return [];
  }
}
export function adoptStage(projectId: string, stage: number) {
  const current = new Set(loadAdoptions(projectId));
  current.add(stage);
  localStorage.setItem(`${PROGRAM_ADOPTION_PREFIX}${projectId}`, JSON.stringify([...current].sort((a, b) => a - b)));
}
export function resetAdoption(projectId: string, stage: number) {
  const current = new Set(loadAdoptions(projectId));
  current.delete(stage);
  localStorage.setItem(`${PROGRAM_ADOPTION_PREFIX}${projectId}`, JSON.stringify([...current].sort((a, b) => a - b)));
}

// ---------------------------------------------------------------------------- stage metadata
export type StageStatus = "COMPLETE" | "CURRENT" | "READY" | "BLOCKED" | "STALE";
export type DecisionClass = "CONFIGURE" | "REVIEW_AND_DECIDE" | "ANALYZE" | "DECIDE" | "TERMINAL" | "BLOCKED";
export type EvidenceState = "NO_EVIDENCE" | "WORKSPACE_EVIDENCE_AVAILABLE" | "PROJECT_STAGE_COMPLETE" | "BLOCKED";
export type ActionKind = "inline_contract" | "inline_binding" | "inline_adopt" | "route" | "export_gated";
export type StageAction = { label: string; kind: ActionKind; route?: string; moduleLabel?: string };

type ProgramStage = {
  number: number; id: string; title: string; purpose: string; decisionClass: DecisionClass;
  why: string; est: string; route?: string; moduleLabel?: string;
};

// The 9 canonical MLB PROGRAM stages.
export const PROGRAM_STAGES: ProgramStage[] = [
  { number: 1, id: "objective", title: "Project & Forecast Objective", decisionClass: "CONFIGURE",
    purpose: "Define exactly what is predicted, the evaluation clock, the eligible population, and how success is measured.",
    why: "Locks the target and broad temporal boundary while protecting the untouched final OOT period from leakage.", est: "~2 min" },
  { number: 2, id: "data-quality", title: "Data Evidence & Quality", decisionClass: "REVIEW_AND_DECIDE",
    purpose: "Review the actual bound data and confirm it is suitable for modeling: coverage, identity, point-in-time integrity, and limitations.",
    why: "You must see and trust the data — identity mapping and leakage checks are part of validating the dataset.", est: "~2 min",
    route: "/data-warehouse", moduleLabel: "Data Warehouse" },
  { number: 3, id: "pa-model", title: "PA Model Development", decisionClass: "ANALYZE",
    purpose: "Develop, profile, engineer features for, tune, evaluate, and compare plate-appearance outcome models in the cockpit.",
    why: "The plate-appearance model is the core forecasting unit fed into the whole-game simulator — this is where you build.", est: "modeling",
    route: "/pa-modeling-cockpit", moduleLabel: "PA Modeling Cockpit" },
  { number: 4, id: "participation", title: "Participation & Game Context", decisionClass: "REVIEW_AND_DECIDE",
    purpose: "Choose the projected lineup, starter identity/duration, and bullpen usage components used to turn PA probabilities into whole games.",
    why: "PA models estimate event probabilities; participation determines who takes those PAs and for how long.", est: "review & adopt",
    route: "/participation-usage", moduleLabel: "Participation & Usage" },
  { number: 5, id: "simulation", title: "Game Simulation", decisionClass: "ANALYZE",
    purpose: "Combine PA probabilities, participation, and base-out transitions to produce whole-game score distributions.",
    why: "This is the product's whole-game forecast — the reason a better PA metric matters.", est: "analyze",
    route: "/simulation-studio", moduleLabel: "Simulation Studio" },
  { number: 6, id: "candidates", title: "Candidate Comparison", decisionClass: "ANALYZE",
    purpose: "Compare coherent forecasting-system candidates — PA challengers, component variants, simulators, and ensembles.",
    why: "Broader than PA-family experimentation: compares whole forecasting systems on equal footing.", est: "review",
    route: "/model-laboratory", moduleLabel: "Candidate Model Laboratory" },
  { number: 7, id: "validation", title: "Validation & Calibration", decisionClass: "REVIEW_AND_DECIDE",
    purpose: "Configure exact chronological folds inside the registered development boundary, then evaluate final OOT performance, calibration, reliability, and subgroups.",
    why: "Sports-native temporal validation and calibration are the only honest measure of trustworthy forecasts.", est: "review & adopt",
    route: "/evaluation-calibration", moduleLabel: "Evaluation & Calibration" },
  { number: 8, id: "decision", title: "Champion Decision", decisionClass: "DECIDE",
    purpose: "Record the governed component graph and an honest terminal research decision: champion, challengers, and what failed.",
    why: "This is the governed decision that determines what may be exported.", est: "decide",
    route: "/model-graph", moduleLabel: "Model Graph" },
  { number: 9, id: "export", title: "Export / Deployment", decisionClass: "TERMINAL",
    purpose: "Package the approved graph for future immutable execution — gated until a governed decision exists.",
    why: "Export requires a governed Champion Decision from Stage 8.", est: "gated",
    route: "/registry-deployment", moduleLabel: "Registry" },
];

export const PROGRAM_STAGE_COUNT = PROGRAM_STAGES.length;

// ---------------------------------------------------------------------------- resolver
export type StageResolution = {
  number: number;
  id: string;
  title: string;
  purpose: string;
  whyItMatters: string;
  estMinutes: string;
  decisionClass: DecisionClass;
  status: StageStatus;
  evidenceState: EvidenceState;
  evidenceAvailable: boolean;
  adopted: boolean;
  requiredFor: string;
  blockedByNumber?: number;
  blockedReason?: string;
  action: StageAction;
  evidence: string[];
};

function ok(v: unknown): boolean {
  return Boolean(v);
}

/** Reusable workspace evidence for program stage n (only meaningful once bound). */
function evidenceAvailableFor(n: number, bound: boolean, dataset: ActiveSportsDataset | null): { available: boolean; evidence: string[] } {
  if (!bound) return { available: false, evidence: [] };
  const pa = dataset?.paBaseline;
  const p4 = dataset?.phase4;
  switch (n) {
    case 2: {
      const ja = dataset?.identityBridge?.joinAudit;
      return {
        available: ok(dataset?.identityBridge) || ok(dataset?.featureAudit),
        evidence: [
          `Registered dataset ${dataset?.datasetId} (${dataset?.validationStatus})`,
          ja ? `Player identity mapping ${(((ja.mappingRate ?? 0) <= 1 ? (ja.mappingRate ?? 0) * 100 : ja.mappingRate)).toFixed(1)}% · ${ja.unresolvedReferences ?? 0} unresolved` : "Player identity bridge registered",
          "Point-in-time leakage review present",
        ],
      };
    }
    case 3:
      return { available: ok(pa?.candidates?.length), evidence: pa?.candidates?.length ? [`${pa.candidates.length} PA candidates (C0–C4) registered`, "Calibrated eight-class probabilities"] : [] };
    case 4: {
      const parts = [p4?.components?.lineup, p4?.components?.starterDuration, p4?.components?.bullpenUsage].filter(Boolean);
      return { available: parts.length > 0, evidence: parts.length ? [`${parts.length}/3 participation components registered`, "Lineup · starter duration · bullpen usage"] : [] };
    }
    case 5:
      return { available: ok(p4?.wholeGameMonteCarlo), evidence: p4?.wholeGameMonteCarlo ? ["Whole-game Monte Carlo research baseline", "Base-out transition authority registered"] : [] };
    case 6:
      return { available: ok(pa?.candidates?.length), evidence: pa?.candidates?.length ? ["Component candidate ledger", "2024 selection evidence"] : [] };
    case 7:
      return { available: ok(pa?.calibration), evidence: pa?.calibration ? ["Rolling-origin folds · frozen 2025 evidence", "Log loss · Brier · ECE · reliability"] : [] };
    case 8: {
      const nodes = p4?.graph?.nodes?.length || pa?.graph?.nodes?.length;
      return { available: ok(nodes), evidence: nodes ? [`Research graph · ${nodes} nodes`, "Terminal research decision recorded"] : [] };
    }
    default:
      return { available: false, evidence: [] };
  }
}

function stageAction(s: ProgramStage, evidenceAvailable: boolean): StageAction {
  if (s.number === 1) return { label: "Save & Register Forecast Contract", kind: "inline_contract" };
  if (s.number === 2) return { label: "Accept Data & Continue", kind: "inline_binding", route: s.route, moduleLabel: s.moduleLabel };
  if (s.number === 9) return { label: "Export MLB Bundle", kind: "export_gated", route: s.route };
  if (s.number === 3) return { label: "Open PA Modeling Cockpit", kind: "route", route: s.route, moduleLabel: s.moduleLabel };
  if (evidenceAvailable) return { label: "Adopt Evidence & Continue", kind: "inline_adopt", route: s.route, moduleLabel: s.moduleLabel };
  return { label: `Open ${s.moduleLabel} to configure`, kind: "route", route: s.route, moduleLabel: s.moduleLabel };
}

export function resolveStages(
  projectId: string,
  dataset: ActiveSportsDataset | null,
  contract = loadContract(projectId),
  binding = loadBinding(projectId),
  adoptions = loadAdoptions(projectId),
): StageResolution[] {
  const bound = ok(binding) && ok(dataset) && ok(dataset?.validationStatus);
  const adoptedSet = new Set(adoptions);

  // base completion per stage
  const base: boolean[] = PROGRAM_STAGES.map((s) => {
    if (s.number === 1) return ok(contract);
    if (s.number === 2) return bound && adoptedSet.has(2); // data reviewed + accepted (incl. identity/quality)
    if (s.number === 9) return false;                       // export always gated
    return adoptedSet.has(s.number);
  });
  const complete: boolean[] = [];
  for (let i = 0; i < base.length; i++) complete[i] = base[i] && (i === 0 || complete[i - 1]);

  let currentAssigned = false;
  return PROGRAM_STAGES.map((s, i) => {
    const n = s.number;
    const { available, evidence } = evidenceAvailableFor(n, bound, dataset);
    const adopted = adoptedSet.has(n);

    let status: StageStatus;
    let blockedByNumber: number | undefined;
    let blockedReason: string | undefined;
    if (complete[i]) {
      status = "COMPLETE";
    } else {
      const firstIncompletePrereq = PROGRAM_STAGES.slice(0, i).findIndex((_, j) => !complete[j]);
      if (firstIncompletePrereq === -1) {
        status = currentAssigned ? "READY" : "CURRENT";
        currentAssigned = true;
      } else {
        status = "BLOCKED";
        blockedByNumber = firstIncompletePrereq + 1;
        blockedReason = `Complete Stage ${firstIncompletePrereq + 1} — ${PROGRAM_STAGES[firstIncompletePrereq].title}`;
      }
    }

    let evidenceState: EvidenceState;
    if (status === "BLOCKED") evidenceState = "BLOCKED";
    else if (complete[i]) evidenceState = "PROJECT_STAGE_COMPLETE";
    else if (n >= 2 && available) evidenceState = "WORKSPACE_EVIDENCE_AVAILABLE";
    else evidenceState = "NO_EVIDENCE";

    const decisionClass: DecisionClass = status === "BLOCKED" ? "BLOCKED" : s.decisionClass;

    return {
      number: n,
      id: s.id,
      title: s.title,
      purpose: s.purpose,
      whyItMatters: s.why,
      estMinutes: s.est,
      decisionClass,
      status,
      evidenceState,
      evidenceAvailable: available,
      adopted,
      requiredFor: "",
      blockedByNumber,
      blockedReason,
      action: stageAction(s, available),
      evidence,
    };
  });
}

/** First actionable incomplete stage — the canonical Continue Work target. */
export function firstActionableStage(resolutions: StageResolution[]): number {
  const current = resolutions.find((r) => r.status === "CURRENT");
  if (current) return current.number;
  const ready = resolutions.find((r) => r.status === "READY");
  if (ready) return ready.number;
  const incomplete = resolutions.find((r) => r.status !== "COMPLETE");
  return incomplete ? incomplete.number : resolutions.length;
}

/** Next stage after `after` that still needs work. */
export function nextActionable(resolutions: StageResolution[], after: number): number {
  const next = resolutions.find((r) => r.number > after && r.status !== "COMPLETE");
  return next ? next.number : Math.min(after + 1, resolutions.length);
}

export function completionSummary(resolutions: StageResolution[]) {
  const complete = resolutions.filter((r) => r.status === "COMPLETE").length;
  const ready = resolutions.filter((r) => r.status === "CURRENT" || r.status === "READY").length;
  const blocked = resolutions.filter((r) => r.status === "BLOCKED").length;
  const available = resolutions.filter((r) => r.evidenceState === "WORKSPACE_EVIDENCE_AVAILABLE").length;
  const total = resolutions.length;
  return { complete, ready, blocked, available, total, pct: Math.round((complete / total) * 100) };
}

// ------------------------------------------------------------------ governed temporal authority
// Phase 6E — single source of truth mirroring the registered FD1 dataset manifest `temporal_contract`
// and the backend feature contract (server/sports_modeling/feature_contract.py, TARGET_SEASONS).
// The governed dataset classifies seasons by ROLE:
//   • 2021–2022 = PRIOR_ONLY_HISTORY — retained ONLY to construct Y−1 player priors for the primary
//     modeling seasons. The `prior_only` population is contractually prohibited from
//     PRIMARY_2023_2025_TARGET_TRAINING ("History retained for prior construction; never primary
//     target rows"). 2021 additionally has no eligible ≤2020 prior (the earliest registered
//     player_prior source season is 2021), so every 2021 PA would be prior-missing.
//   • 2023–2025 = PRIMARY_GEN2_MODELING — the PA modeling matrix (feature view, 549,479 rows).
// Therefore the modeling development window is 2023 only; validation 2024; frozen final 2025. Source
// evidence spans 2021–2025, but SOURCE EVIDENCE ≠ MODELING DEVELOPMENT. The platform must never claim
// 2021–2023 development when the model trains on 2023.
export const GOVERNED_TEMPORAL = {
  sourceEvidenceSeasons: [2021, 2022, 2023, 2024, 2025],
  priorOnlyHistorySeasons: [2021, 2022],
  developmentSeasons: [2023],
  validationSeason: 2024,
  frozenSeason: 2025,
  prospectiveSeason: 2026,
  priorOnlyReason:
    "2021–2022 are registered PRIOR_ONLY_HISTORY — retained only to build Y−1 player priors for 2023–2025 and contractually prohibited from primary target training. 2021 additionally has no eligible ≤2020 prior, so every 2021 plate appearance would be prior-missing.",
} as const;

// The earliest season that may serve as a modeling target/development season.
export const MODELING_START_SEASON = GOVERNED_TEMPORAL.developmentSeasons[0];

// Reconcile a (possibly legacy) contract development window with the governed modeling authority so
// display surfaces never *claim* 2021–2023 development. No silent drift: prior-only history seasons
// are dropped and the result is the governed development window when nothing valid remains.
export function governedDevelopmentSeasons(seasons: number[] | undefined | null): number[] {
  const allowed = new Set<number>(GOVERNED_TEMPORAL.developmentSeasons);
  const kept = (seasons ?? []).filter((s) => allowed.has(s));
  return kept.length ? kept : [...GOVERNED_TEMPORAL.developmentSeasons];
}

// Compact "2021–2023 → 2024 → 2025" style label for the governed development window of a contract.
export function developmentWindowLabel(contract: ForecastContract | null): string {
  if (temporalDesignMode(contract) === "CUSTOM_DATES_ROLLING_ORIGIN") {
    const range = contract?.developmentSelection;
    return range?.startDate && range?.endDate ? `${range.startDate}–${range.endDate}` : "Custom dates not configured";
  }
  const dev = governedDevelopmentSeasons(contract?.developmentSeasons);
  return dev.length > 1 ? `${dev[0]}–${dev[dev.length - 1]}` : String(dev[0]);
}

export function validationWindowLabel(contract: ForecastContract | null): string {
  if (temporalDesignMode(contract) === "CUSTOM_DATES_ROLLING_ORIGIN") {
    return "Exact folds deferred to Validation & Calibration";
  }
  return contract?.validationSeason ? String(contract.validationSeason) : String(DEFAULT_TEMPORAL.validationSeason);
}

export function finalOotWindowLabel(contract: ForecastContract | null): string {
  if (temporalDesignMode(contract) === "CUSTOM_DATES_ROLLING_ORIGIN") {
    const range = contract?.finalOot;
    return range?.startDate && range?.endDate ? `${range.startDate}–${range.endDate}` : "Custom dates not configured";
  }
  return contract?.frozenSeason ? String(contract.frozenSeason) : String(DEFAULT_TEMPORAL.frozenSeason);
}

export function temporalPolicyLabel(contract: ForecastContract | null): string {
  if (!contract) return "Not configured";
  if (temporalDesignMode(contract) === "CUSTOM_DATES_ROLLING_ORIGIN") {
    return `${developmentWindowLabel(contract)} → OOT ${finalOotWindowLabel(contract)}`;
  }
  return `${developmentWindowLabel(contract)} → ${validationWindowLabel(contract)} → ${finalOotWindowLabel(contract)}`;
}

// Default proposed temporal policy for the current project (owner-reviewable). Development is the
// governed modeling window (2023); 2021–2022 remain source-only prior history.
export const DEFAULT_TEMPORAL = {
  developmentSeasons: [...GOVERNED_TEMPORAL.developmentSeasons],
  validationSeason: GOVERNED_TEMPORAL.validationSeason,
  frozenSeason: GOVERNED_TEMPORAL.frozenSeason,
  prospectiveSeason: GOVERNED_TEMPORAL.prospectiveSeason,
};

// Per-season role + development-start eligibility under the current registered Gen-2 policy. Source
// evidence spans 2021–2025, but only 2023 is an eligible development start: 2021 has no ≤2020 prior,
// 2021–2022 are PRIOR_ONLY_HISTORY, 2025 is frozen. The Stage 1 UI shows all seasons honestly with
// these reasons — the data exists, but earlier seasons carry another governed role.
export type SeasonPolicy = { role: string; eligibleDevStart: boolean; reason: string };
export const SEASON_ROLE_POLICY: Record<number, SeasonPolicy> = {
  2021: { role: "PRIOR HISTORY", eligibleDevStart: false, reason: "No pre-2021 registered history exists, so Y−1 player-state features are unavailable for essentially the entire season." },
  2022: { role: "PRIOR HISTORY", eligibleDevStart: false, reason: "Available source evidence, but reserved as PRIOR_ONLY_HISTORY under the current Gen-2 registration (prohibited from primary target training)." },
  2023: { role: "DEVELOPMENT", eligibleDevStart: true, reason: "Current Gen-2 development start." },
  2024: { role: "VALIDATION", eligibleDevStart: false, reason: "Validation season — selects the model; never a development target." },
  2025: { role: "FROZEN FINAL", eligibleDevStart: false, reason: "Frozen final — never used for development, tuning, or model selection." },
  2026: { role: "FUTURE", eligibleDevStart: false, reason: "Prospective — not yet registered evidence." },
};
export function isEligibleDevelopmentStart(season: number): boolean {
  return SEASON_ROLE_POLICY[season]?.eligibleDevStart === true;
}

// A "revised temporal experiment" is a RESEARCH DRAFT — it NEVER overwrites the registered Gen-2
// forecast contract. Persisted under a distinct project-scoped key so the governed authority is safe.
const TEMPORAL_DRAFT_PREFIX = "asp-sports-temporal-draft:";
export type TemporalDraft = {
  projectId: string; developmentSeasons: number[]; validationSeason: number; frozenSeason: number;
  excludePriorFamilies: boolean; rationale: string; savedAt: string;
};
export function saveTemporalDraft(draft: TemporalDraft) {
  localStorage.setItem(`${TEMPORAL_DRAFT_PREFIX}${draft.projectId}`, JSON.stringify(draft));
}
export function loadTemporalDraft(projectId: string): TemporalDraft | null {
  try {
    const raw = JSON.parse(localStorage.getItem(`${TEMPORAL_DRAFT_PREFIX}${projectId}`) || "null");
    return raw?.projectId === projectId ? (raw as TemporalDraft) : null;
  } catch {
    return null;
  }
}

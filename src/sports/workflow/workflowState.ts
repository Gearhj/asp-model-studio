// Scientist-first MLB PROGRAM workflow state (Phase 6D): 9 canonical program stages, each a real
// scientist activity or governed decision. The detailed 15-stage PA Modeling Cockpit is nested
// inside Program Stage 3 (PA Model Development) and is NOT counted as program stages.
//
// Honest project-evidence semantics (from Phase 6C.1): existing WORKSPACE evidence is not the same
// as PROJECT-ADOPTED evidence, which is not the same as a COMPLETE program stage. Persisted per
// project in localStorage (no data copy, no duplicate registration, no governance change): forecast
// contract, dataset binding, and per-stage adoptions.
import type { ActiveSportsDataset } from "../sportsEvidenceApi";

// ---------------------------------------------------------------------------- persisted artifacts
export type ForecastContract = {
  projectId: string;
  version: number;
  target: string;
  lifecycle: string;
  developmentSeasons: number[];
  validationSeason: number;
  frozenSeason: number;
  prospectiveSeason: number | null;
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
    return raw?.projectId === projectId ? (raw as ForecastContract) : null;
  } catch {
    return null;
  }
}
export function saveContract(contract: ForecastContract) {
  localStorage.setItem(`${CONTRACT_PREFIX}${contract.projectId}`, JSON.stringify(contract));
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
    why: "Locks the target and temporal policy and prevents 2025 frozen-evaluation leakage.", est: "~2 min" },
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
    purpose: "Evaluate forward-looking performance and calibration: 2024 validation, 2025 frozen evaluation, reliability, subgroups.",
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
export function developmentWindowLabel(contract: { developmentSeasons?: number[] } | null): string {
  const dev = governedDevelopmentSeasons(contract?.developmentSeasons);
  return dev.length > 1 ? `${dev[0]}–${dev[dev.length - 1]}` : String(dev[0]);
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

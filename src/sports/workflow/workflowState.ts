// Canonical guided-workflow state with honest project-evidence semantics.
//
// Key distinction (Phase 6C.1): existing WORKSPACE evidence is not the same as PROJECT-ADOPTED
// evidence, which is not the same as a COMPLETE project stage. A brand-new project must not be
// marked complete merely because historical workspace evidence exists — the project must adopt it.
//
// Persisted per project (localStorage; no data copy, no duplicate registration, no governance
// change): forecast contract (Step 1), dataset binding (Step 2), and per-stage adoptions (3–11).
import { MLB_WORKFLOW, type SportsWorkflowStep } from "../sportsConfig";
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
const ADOPTION_PREFIX = "asp-sports-stage-adoptions:";

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

/** Per-project stage adoptions (which stages the project has explicitly adopted evidence for). */
export function loadAdoptions(projectId: string): number[] {
  try {
    const raw = JSON.parse(localStorage.getItem(`${ADOPTION_PREFIX}${projectId}`) || "[]");
    return Array.isArray(raw) ? raw.filter((n) => typeof n === "number") : [];
  } catch {
    return [];
  }
}
export function adoptStage(projectId: string, stage: number) {
  const current = new Set(loadAdoptions(projectId));
  current.add(stage);
  localStorage.setItem(`${ADOPTION_PREFIX}${projectId}`, JSON.stringify([...current].sort((a, b) => a - b)));
}
export function resetAdoption(projectId: string, stage: number) {
  const current = new Set(loadAdoptions(projectId));
  current.delete(stage);
  localStorage.setItem(`${ADOPTION_PREFIX}${projectId}`, JSON.stringify([...current].sort((a, b) => a - b)));
}

// ---------------------------------------------------------------------------- stage metadata
export type StageStatus = "COMPLETE" | "CURRENT" | "READY" | "BLOCKED" | "STALE";
// Decision-driven role of a stage for the current project.
export type DecisionClass = "CONFIGURE" | "REVIEW_AND_DECIDE" | "ANALYZE" | "OPTIONAL_CUSTOMIZATION" | "AUTO_SATISFIED" | "BLOCKED" | "TERMINAL";
export type EvidenceState =
  | "NO_EVIDENCE"
  | "WORKSPACE_EVIDENCE_AVAILABLE"
  | "PROJECT_EVIDENCE_ADOPTED"
  | "PROJECT_STAGE_COMPLETE"
  | "BLOCKED";
export type StageClass = "CONFIGURE" | "REVIEW_ADOPT" | "ANALYZE" | "DECIDE" | "EXPORT";
export type ActionKind = "inline_contract" | "inline_binding" | "inline_adopt" | "route" | "export_gated";
export type StageAction = { label: string; kind: ActionKind; route?: string; moduleLabel?: string };

const CLASS: Record<number, StageClass> = {
  1: "CONFIGURE", 2: "REVIEW_ADOPT", 3: "REVIEW_ADOPT", 4: "REVIEW_ADOPT", 5: "REVIEW_ADOPT",
  6: "ANALYZE", 7: "ANALYZE", 8: "ANALYZE", 9: "REVIEW_ADOPT", 10: "REVIEW_ADOPT", 11: "DECIDE", 12: "EXPORT",
};
const ROUTE: Record<number, string> = {
  3: "/data-warehouse", 4: "/player-team-state", 5: "/participation-usage", 6: "/pa-modeling-cockpit", 7: "/simulation-studio",
  8: "/model-laboratory", 9: "/evaluation-calibration", 10: "/evaluation-calibration", 11: "/model-graph", 12: "/registry-deployment",
};
const MODULE_LABEL: Record<number, string> = {
  3: "Data Warehouse", 4: "Player & Team State", 5: "Participation & Usage", 6: "PA Modeling Cockpit",
  7: "Simulation Studio", 8: "Candidate Model Laboratory", 9: "Evaluation", 10: "Evaluation & Calibration", 11: "Model Graph", 12: "Registry",
};
const WHY: Record<number, string> = {
  1: "Locks the prediction target, evaluation clock, and eligible population — and prevents 2025 frozen-evaluation leakage.",
  2: "Points this project at governed, immutable evidence so every downstream result is reproducible.",
  3: "Confirms players map exactly and that no future information leaks into features or labels.",
  4: "Prior-season talent and time-varying state are the strongest signal available in the free data.",
  5: "Who plays, when, and for how long drives whole-game outcomes as much as the PA model.",
  6: "The plate-appearance model is the core forecasting unit fed into the whole-game simulator.",
  7: "Turns per-PA probabilities into full-game score distributions — the product's whole-game forecast.",
  8: "Compares coherent component/model/simulator candidates and ensembles on equal footing.",
  9: "Sports-native temporal validation is the only honest measure of forward-looking performance.",
  10: "Calibration determines whether the probabilities can be trusted, not just ranked.",
  11: "Records the governed research component graph and an honest terminal research decision.",
  12: "Packages an approved graph for future immutable execution — gated until the decision exists.",
};
const EST: Record<number, string> = {
  1: "~2 min", 2: "~1 min", 3: "~2 min", 4: "review & adopt", 5: "review & adopt",
  6: "analyze", 7: "analyze", 8: "review", 9: "review & adopt", 10: "review & adopt", 11: "decide", 12: "gated",
};

// ---------------------------------------------------------------------------- resolver
export type StageResolution = {
  number: number;
  id: string;
  title: string;
  purpose: string;
  whyItMatters: string;
  estMinutes: string;
  classification: StageClass;
  decisionClass: DecisionClass;
  status: StageStatus;
  evidenceState: EvidenceState;
  evidenceAvailable: boolean;
  adopted: boolean;
  autoSatisfied: boolean;
  requiredFor: string;
  blockedByNumber?: number;
  blockedReason?: string;
  action: StageAction;
  evidence: string[];
};

function ok(v: unknown): boolean {
  return Boolean(v);
}

// Stages the current PA project foundation auto-satisfies (no required scientist decision).
// Step 4: the adopted bounded Y-1 batter/pitcher prior state is sufficient for the PA baseline.
// Step 5: participation components are prerequisites for FULL-GAME SIMULATION (Step 7), not for
// training/evaluating the PA classifier — so PA modeling is not blocked on them.
function autoSatisfiedFor(n: number, bound: boolean, dataset: ActiveSportsDataset | null): boolean {
  if (!bound) return false;
  if (n === 4) return ok(dataset?.paBaseline) || true; // Y-1 prior-state baseline is always available once bound
  if (n === 5) return true; // no participation component is required to develop the PA model
  return false;
}

const REQUIRED_FOR: Record<number, string> = {
  4: "Player-state baseline (bounded Y−1 priors) is sufficient for PA modeling",
  5: "Required for full-game simulation (Step 7), not for PA model training",
};

/** Whether reusable workspace evidence exists for stage n (only meaningful once bound). */
function evidenceAvailableFor(n: number, bound: boolean, dataset: ActiveSportsDataset | null): { available: boolean; evidence: string[] } {
  if (!bound) return { available: false, evidence: [] };
  const pa = dataset?.paBaseline;
  const p4 = dataset?.phase4;
  switch (n) {
    case 3:
      return { available: ok(dataset?.identityBridge) || ok(dataset?.featureAudit), evidence: ["Player identity bridge registered", "Point-in-time leakage review present"] };
    case 4:
      return { available: ok(pa), evidence: ["Bounded Y−1 batter & pitcher prior state (used by the PA baseline)", p4?.components?.dynamicState ? "Dynamic player state registered" : "Dynamic state & E1/E2 features are optional further research (not yet registered)"] };
    case 5: {
      const parts = [p4?.components?.lineup, p4?.components?.starterDuration, p4?.components?.bullpenUsage].filter(Boolean);
      return { available: parts.length > 0, evidence: parts.length ? [`${parts.length} participation components registered`, "Lineup · starter duration · bullpen usage"] : [] };
    }
    case 6:
      return { available: ok(pa?.candidates?.length), evidence: pa?.candidates?.length ? [`${pa.candidates.length} PA candidates (C0–C4)`, "Calibrated eight-class probabilities"] : [] };
    case 7:
      return { available: ok(p4?.wholeGameMonteCarlo), evidence: p4?.wholeGameMonteCarlo ? ["Whole-game Monte Carlo research baseline", "Base-out transition authority registered"] : [] };
    case 8:
      return { available: ok(pa?.candidates?.length), evidence: pa?.candidates?.length ? ["Component candidate ledger", "2024 selection evidence"] : [] };
    case 9:
      return { available: ok(pa?.calibration?.final2025), evidence: pa?.calibration?.final2025 ? ["Rolling-origin folds registered", "Frozen 2025 retrospective evidence"] : [] };
    case 10:
      return { available: ok(pa?.calibration), evidence: pa?.calibration ? ["Log loss · Brier · ECE", "Reliability & bootstrap intervals"] : [] };
    case 11: {
      const nodes = p4?.graph?.nodes?.length || pa?.graph?.nodes?.length;
      return { available: ok(nodes), evidence: nodes ? [`Research graph · ${nodes} nodes`, "Terminal research decision recorded"] : [] };
    }
    default:
      return { available: false, evidence: [] };
  }
}

function stageAction(n: number, evidenceAvailable: boolean): StageAction {
  if (n === 1) return { label: "Save & Register Forecast Contract", kind: "inline_contract" };
  if (n === 2) return { label: "Use Dataset & Continue", kind: "inline_binding" };
  if (n === 12) return { label: "Export MLB Bundle", kind: "export_gated", route: ROUTE[12] };
  if (evidenceAvailable) {
    const verb = CLASS[n] === "ANALYZE" ? "Adopt Current Evidence & Continue" : "Adopt Evidence & Continue";
    return { label: verb, kind: "inline_adopt", route: ROUTE[n], moduleLabel: MODULE_LABEL[n] };
  }
  return { label: `Open ${MODULE_LABEL[n]} to configure`, kind: "route", route: ROUTE[n], moduleLabel: MODULE_LABEL[n] };
}

export function resolveStages(
  projectId: string,
  dataset: ActiveSportsDataset | null,
  contract = loadContract(projectId),
  binding = loadBinding(projectId),
  adoptions = loadAdoptions(projectId),
): StageResolution[] {
  const steps = MLB_WORKFLOW.steps;
  const bound = ok(binding) && ok(dataset) && ok(dataset?.validationStatus);
  const adoptedSet = new Set(adoptions);

  // base completion per stage (before enforcing the linear prerequisite chain).
  // Auto-satisfied foundation stages (4, 5) complete automatically once the project is bound —
  // there is no required scientist decision, so they never gate the path to modeling.
  const base: boolean[] = steps.map((s) => {
    if (s.number === 1) return ok(contract);
    if (s.number === 2) return bound;
    if (s.number === 12) return false;
    return adoptedSet.has(s.number) || autoSatisfiedFor(s.number, bound, dataset);
  });
  // linear completion: a stage is complete only if it and all predecessors are base-complete
  const complete: boolean[] = [];
  for (let i = 0; i < steps.length; i++) complete[i] = base[i] && (i === 0 || complete[i - 1]);

  let currentAssigned = false;
  return steps.map((step, i) => {
    const n = step.number;
    const { available, evidence } = evidenceAvailableFor(n, bound, dataset);
    const adopted = adoptedSet.has(n);

    let status: StageStatus;
    let blockedByNumber: number | undefined;
    let blockedReason: string | undefined;
    if (complete[i]) {
      status = "COMPLETE";
    } else {
      const firstIncompletePrereq = steps.slice(0, i).findIndex((_, j) => !complete[j]);
      if (firstIncompletePrereq === -1) {
        status = currentAssigned ? "READY" : "CURRENT";
        currentAssigned = true;
      } else {
        status = "BLOCKED";
        blockedByNumber = firstIncompletePrereq + 1;
        blockedReason = `Complete Step ${firstIncompletePrereq + 1} — ${steps[firstIncompletePrereq].title}`;
      }
    }

    const autoSat = autoSatisfiedFor(n, bound, dataset) && !adopted;

    let evidenceState: EvidenceState;
    if (status === "BLOCKED") evidenceState = "BLOCKED";
    else if (complete[i]) evidenceState = "PROJECT_STAGE_COMPLETE";
    else if (n >= 3 && available) evidenceState = "WORKSPACE_EVIDENCE_AVAILABLE";
    else evidenceState = "NO_EVIDENCE";

    // decision-driven role for the current project
    let decisionClass: DecisionClass;
    if (status === "BLOCKED") decisionClass = "BLOCKED";
    else if (n === 12) decisionClass = "TERMINAL";
    else if (autoSat || (complete[i] && autoSatisfiedFor(n, bound, dataset) && !adopted)) decisionClass = "AUTO_SATISFIED";
    else decisionClass = (CLASS[n] === "REVIEW_ADOPT" ? "REVIEW_AND_DECIDE" : CLASS[n] === "DECIDE" ? "REVIEW_AND_DECIDE" : CLASS[n] === "EXPORT" ? "TERMINAL" : CLASS[n]) as DecisionClass;

    return {
      number: n,
      id: step.id,
      title: step.title,
      purpose: step.purpose,
      whyItMatters: WHY[n] || "",
      estMinutes: EST[n] || "",
      classification: CLASS[n],
      decisionClass,
      status,
      evidenceState,
      evidenceAvailable: available,
      adopted,
      autoSatisfied: autoSatisfiedFor(n, bound, dataset),
      requiredFor: REQUIRED_FOR[n] || "",
      blockedByNumber,
      blockedReason,
      action: stageAction(n, available),
      evidence,
    };
  });
}

/** First actionable incomplete stage number — the canonical Continue Work target. */
export function firstActionableStage(resolutions: StageResolution[]): number {
  const current = resolutions.find((r) => r.status === "CURRENT");
  if (current) return current.number;
  const ready = resolutions.find((r) => r.status === "READY");
  if (ready) return ready.number;
  const incomplete = resolutions.find((r) => r.status !== "COMPLETE");
  return incomplete ? incomplete.number : resolutions.length;
}

/** Next stage after `after` that still needs work (skips COMPLETE / auto-satisfied stages). */
export function nextActionable(resolutions: StageResolution[], after: number): number {
  const next = resolutions.find((r) => r.number > after && r.status !== "COMPLETE");
  return next ? next.number : Math.min(after + 1, resolutions.length);
}

export function completionSummary(resolutions: StageResolution[]) {
  const complete = resolutions.filter((r) => r.status === "COMPLETE").length;
  const ready = resolutions.filter((r) => r.status === "CURRENT" || r.status === "READY").length;
  const blocked = resolutions.filter((r) => r.status === "BLOCKED").length;
  const available = resolutions.filter((r) => r.evidenceState === "WORKSPACE_EVIDENCE_AVAILABLE").length;
  // Foundation = Steps 1–5 (contract, data, identity, player-state, participation).
  const foundation = resolutions.slice(0, 5);
  const foundationComplete = foundation.every((r) => r.status === "COMPLETE");
  const foundationDone = foundation.filter((r) => r.status === "COMPLETE").length;
  return { complete, ready, blocked, available, total: resolutions.length, pct: Math.round((complete / resolutions.length) * 100), foundationComplete, foundationDone };
}

// Default proposed temporal policy for the current project (owner-reviewable).
export const DEFAULT_TEMPORAL = {
  developmentSeasons: [2021, 2022, 2023],
  validationSeason: 2024,
  frozenSeason: 2025,
  prospectiveSeason: 2026,
};

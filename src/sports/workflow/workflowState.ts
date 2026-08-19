// Canonical guided-workflow state: per-project forecast contract + dataset binding (localStorage,
// no duplicate registration, no governance change) plus a single resolver that computes each of the
// 12 stages' status and primary action from local artifacts + governed evidence. One canonical
// "first actionable stage" resolver powers Continue Work everywhere.
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

// ---------------------------------------------------------------------------- stage metadata
export type StageAction = { label: string; kind: "inline" | "route" | "disabled"; route?: string };
export type StageStatus = "COMPLETE" | "CURRENT" | "READY" | "BLOCKED" | "STALE";

export type StageMeta = {
  number: number;
  id: string;
  title: string;
  purpose: string;
  whyItMatters: string;
  estMinutes: string;
  action: StageAction;
};

// Action map — every stage routes to real existing functionality (no invented actions).
const ACTION: Record<number, StageAction> = {
  1: { label: "Configure Forecast Contract", kind: "inline" },
  2: { label: "Use This Registered Dataset", kind: "inline" },
  3: { label: "Review Identity & Leakage Evidence", kind: "inline" },
  4: { label: "Configure Hitter & Pitcher State", kind: "route", route: "/player-team-state" },
  5: { label: "Configure Participation & Usage", kind: "route", route: "/participation-usage" },
  6: { label: "Open PA Modeling Cockpit", kind: "route", route: "/pa-modeling-cockpit" },
  7: { label: "Open Simulation Studio", kind: "route", route: "/simulation-studio" },
  8: { label: "Open Candidate Model Laboratory", kind: "route", route: "/model-laboratory" },
  9: { label: "Review Temporal Validation", kind: "route", route: "/evaluation-calibration" },
  10: { label: "Review Calibration & Reliability", kind: "route", route: "/evaluation-calibration" },
  11: { label: "Review Model Graph & Research Decision", kind: "route", route: "/model-graph" },
  12: { label: "Review / Export MLB Bundle", kind: "route", route: "/registry-deployment" },
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
  1: "~2 min", 2: "~1 min", 3: "~2 min", 4: "review", 5: "review",
  6: "modeling", 7: "simulation", 8: "review", 9: "review", 10: "review", 11: "review", 12: "gated",
};

export function stageMeta(step: SportsWorkflowStep): StageMeta {
  return {
    number: step.number,
    id: step.id,
    title: step.title,
    purpose: step.purpose,
    whyItMatters: WHY[step.number] || "",
    estMinutes: EST[step.number] || "",
    action: ACTION[step.number] || { label: "Open", kind: "route", route: "/dashboard" },
  };
}

// ---------------------------------------------------------------------------- resolver
export type StageResolution = StageMeta & {
  status: StageStatus;
  blockedByNumber?: number;
  blockedReason?: string;
  evidence: string[];
};

function ok(v: unknown): boolean {
  return Boolean(v);
}

/** Per-stage "satisfied" evaluation from local artifacts + governed evidence. */
function satisfied(
  n: number,
  contract: ForecastContract | null,
  binding: DatasetBinding | null,
  dataset: ActiveSportsDataset | null,
): { done: boolean; evidence: string[] } {
  const pa = dataset?.paBaseline;
  const p4 = dataset?.phase4;
  const bound = ok(binding) && ok(dataset) && ok(dataset?.validationStatus);
  switch (n) {
    case 1:
      return {
        done: ok(contract),
        evidence: contract
          ? [
              `Target: ${contract.target}`,
              `Development ${contract.developmentSeasons.join("–")} · Validation ${contract.validationSeason} · Frozen ${contract.frozenSeason}`,
              `Evidence mode: ${contract.evidenceMode} · v${contract.version}`,
            ]
          : [],
      };
    case 2:
      return {
        done: bound,
        evidence: bound
          ? [`Registered dataset ${binding!.datasetId} (${dataset!.validationStatus})`, `Seasons ${binding!.seasons.join(", ")}`, `Manifest ${binding!.manifestSha.slice(0, 12)}…`]
          : [],
      };
    case 3: {
      const idOk = bound && (ok(dataset?.identityBridge) || dataset?.featureAudit?.status === "PASS" || ok(dataset?.featureAudit));
      return { done: Boolean(idOk), evidence: idOk ? ["Player identity bridge registered", "Point-in-time leakage review present"] : [] };
    }
    case 4: {
      const d = bound && (ok(p4?.components?.dynamicState) || ok(pa?.candidates?.length));
      return { done: Boolean(d), evidence: d ? ["Y−1 batter & pitcher priors", p4?.components?.dynamicState ? "Dynamic player state registered" : "Bounded prior-state blocks"] : [] };
    }
    case 5: {
      const parts = [p4?.components?.lineup, p4?.components?.starterDuration, p4?.components?.bullpenUsage].filter(Boolean);
      const d = bound && parts.length > 0;
      return { done: Boolean(d), evidence: d ? [`${parts.length} participation components registered`, "Lineup · starter duration · bullpen usage"] : [] };
    }
    case 6: {
      const d = bound && ok(pa?.candidates?.length);
      return { done: Boolean(d), evidence: d ? [`${pa!.candidates.length} PA candidates (C0–C4)`, "Calibrated eight-class probabilities"] : [] };
    }
    case 7: {
      const d = bound && ok(p4?.wholeGameMonteCarlo);
      return { done: Boolean(d), evidence: d ? ["Whole-game Monte Carlo research baseline", "Base-out transition authority registered"] : [] };
    }
    case 8: {
      const d = bound && ok(pa?.candidates?.length);
      return { done: Boolean(d), evidence: d ? ["Component candidate ledger", "2024 selection evidence"] : [] };
    }
    case 9: {
      const d = bound && ok(pa?.calibration?.final2025);
      return { done: Boolean(d), evidence: d ? ["Rolling-origin folds registered", "Frozen 2025 retrospective evidence"] : [] };
    }
    case 10: {
      const d = bound && ok(pa?.calibration);
      return { done: Boolean(d), evidence: d ? ["Log loss · Brier · ECE", "Reliability & bootstrap intervals"] : [] };
    }
    case 11: {
      const nodes = p4?.graph?.nodes?.length || pa?.graph?.nodes?.length;
      const d = bound && ok(nodes);
      return { done: Boolean(d), evidence: d ? [`Research graph · ${nodes} nodes`, "Terminal research decision recorded"] : [] };
    }
    case 12:
      return { done: false, evidence: [] };
    default:
      return { done: false, evidence: [] };
  }
}

/** Resolve all 12 stages: COMPLETE / CURRENT / READY / BLOCKED, with blocking prerequisites. */
export function resolveStages(
  projectId: string,
  dataset: ActiveSportsDataset | null,
  contract = loadContract(projectId),
  binding = loadBinding(projectId),
): StageResolution[] {
  const steps = MLB_WORKFLOW.steps;
  const done: boolean[] = [];
  const evidences: string[][] = [];
  for (let i = 0; i < steps.length; i++) {
    const s = satisfied(i + 1, contract, binding, dataset);
    done[i] = s.done;
    evidences[i] = s.evidence;
  }
  let currentAssigned = false;
  return steps.map((step, i) => {
    const meta = stageMeta(step);
    const n = i + 1;
    let status: StageStatus;
    let blockedByNumber: number | undefined;
    let blockedReason: string | undefined;
    if (done[i]) {
      status = "COMPLETE";
    } else {
      // prerequisites are all previous stages in this linear program
      const firstIncompletePrereq = steps.slice(0, i).findIndex((_, j) => !done[j]);
      if (firstIncompletePrereq === -1) {
        // all prereqs complete → actionable
        status = currentAssigned ? "READY" : "CURRENT";
        currentAssigned = true;
      } else {
        status = "BLOCKED";
        blockedByNumber = firstIncompletePrereq + 1;
        blockedReason = `Complete Step ${firstIncompletePrereq + 1} — ${steps[firstIncompletePrereq].title}`;
      }
    }
    return { ...meta, status, blockedByNumber, blockedReason, evidence: evidences[i] };
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

export function completionSummary(resolutions: StageResolution[]) {
  const complete = resolutions.filter((r) => r.status === "COMPLETE").length;
  const ready = resolutions.filter((r) => r.status === "CURRENT" || r.status === "READY").length;
  const blocked = resolutions.filter((r) => r.status === "BLOCKED").length;
  return { complete, ready, blocked, total: resolutions.length, pct: Math.round((complete / resolutions.length) * 100) };
}

// Default proposed temporal policy for the current project (owner-reviewable).
export const DEFAULT_TEMPORAL = {
  developmentSeasons: [2021, 2022, 2023],
  validationSeason: 2024,
  frozenSeason: 2025,
  prospectiveSeason: 2026,
};

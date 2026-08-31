import type { LeagueCode, SportCode } from "./sportRegistry";
import { workflowManifestForLeague } from "./workflowManifest";

export type PersistedSportIdentity = {
  sportCode?: string;
  leagueCode?: string;
  workflowCode?: string;
  sport?: string;
  league?: string;
};

export type WorkflowRouteDecision =
  | { allowed: true; sportCode: SportCode; leagueCode: LeagueCode; workflowCode: string }
  | { allowed: false; reason: string };

const LEGACY_WORKFLOW_IDENTITY: Record<string, { sportCode: SportCode; leagueCode: LeagueCode; workflowCode: string }> = {
  "mlb-forecasting": { sportCode: "BASEBALL", leagueCode: "MLB", workflowCode: "MLB_GAME_FORECAST_WORKFLOW_V1" },
  "nfl-forecasting": { sportCode: "FOOTBALL", leagueCode: "NFL", workflowCode: "NFL_GAME_FORECAST_WORKFLOW_V1" },
};

const LEGACY_SPORT_CODE: Record<string, SportCode> = {
  BASEBALL: "BASEBALL",
  BASEBALL_MLB: "BASEBALL",
  FOOTBALL: "FOOTBALL",
  PROFESSIONAL_FOOTBALL: "FOOTBALL",
  BASKETBALL: "BASKETBALL",
  MMA: "MMA",
  MIXED_MARTIAL_ARTS: "MMA",
};

function normalizedKey(value: string | undefined) {
  return String(value || "").trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "");
}

export function canonicalProjectSportIdentity(
  workflowId: string | undefined,
  metadata: PersistedSportIdentity | null | undefined,
): WorkflowRouteDecision {
  const legacy = LEGACY_WORKFLOW_IDENTITY[String(workflowId || "").trim()];
  if (!legacy) return { allowed: false, reason: "The persisted project does not identify a supported sports workflow manifest." };

  const declaredSport = metadata?.sportCode
    ? normalizedKey(metadata.sportCode) as SportCode
    : metadata?.sport
      ? LEGACY_SPORT_CODE[normalizedKey(metadata.sport)]
      : undefined;
  const declaredLeague = normalizedKey(metadata?.leagueCode || metadata?.league) as LeagueCode;
  const declaredWorkflow = String(metadata?.workflowCode || "").trim();

  if (declaredSport && declaredSport !== legacy.sportCode) {
    return { allowed: false, reason: `Persisted sport ${declaredSport} conflicts with immutable workflow ${workflowId}.` };
  }
  if (declaredLeague && declaredLeague !== legacy.leagueCode) {
    return { allowed: false, reason: `Persisted league ${declaredLeague} conflicts with immutable workflow ${workflowId}.` };
  }
  if (declaredWorkflow && declaredWorkflow !== legacy.workflowCode) {
    return { allowed: false, reason: `Persisted manifest ${declaredWorkflow} conflicts with immutable workflow ${workflowId}.` };
  }

  return { allowed: true, ...legacy };
}

export function resolveSportAwareWorkflowRoute(
  requestedLeagueCode: LeagueCode,
  workflowId: string | undefined,
  metadata: PersistedSportIdentity | null | undefined,
): WorkflowRouteDecision {
  const identity = canonicalProjectSportIdentity(workflowId, metadata);
  if (!identity.allowed) return identity;
  if (identity.leagueCode !== requestedLeagueCode) {
    return {
      allowed: false,
      reason: `Route league ${requestedLeagueCode} does not match persisted project league ${identity.leagueCode}.`,
    };
  }
  const manifest = workflowManifestForLeague(identity.leagueCode);
  if (!manifest || manifest.workflowCode !== identity.workflowCode) {
    return { allowed: false, reason: "The persisted project workflow manifest is missing or incompatible." };
  }
  if (!["ENABLED", "RESEARCH_ONLY"].includes(manifest.availability)) {
    return { allowed: false, reason: `The ${identity.leagueCode} workflow is ${manifest.availability} and cannot be opened.` };
  }
  return identity;
}

export function projectMatchesLeagueFilter(
  filter: "ALL" | "MLB" | "NFL",
  workflowId: string | undefined,
  metadata: PersistedSportIdentity | null | undefined,
) {
  if (filter === "ALL") return true;
  const identity = canonicalProjectSportIdentity(workflowId, metadata);
  return identity.allowed && identity.leagueCode === filter;
}

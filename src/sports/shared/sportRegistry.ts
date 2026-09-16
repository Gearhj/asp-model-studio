export type SportCode = "BASEBALL" | "FOOTBALL" | "BASKETBALL" | "MMA";

export type LeagueCode = "MLB" | "NFL" | "NBA" | "WNBA" | "UFC";

export type ParticipantType = "TEAM" | "INDIVIDUAL";

export type SportAvailabilityState =
  | "LIVE"
  | "RESEARCH_SHADOW"
  | "DEVELOPMENT"
  | "PLANNED"
  | "UNAVAILABLE";

export type WorkflowAvailability =
  | "ENABLED"
  | "RESEARCH_ONLY"
  | "PLANNED"
  | "BLOCKED_BY_MISSING_EVIDENCE"
  | "UNAVAILABLE";

export type LeagueRegistryEntry = {
  leagueCode: LeagueCode;
  displayName: string;
  participantType: ParticipantType;
  availability: SportAvailabilityState;
  workflowAvailability: WorkflowAvailability;
  projectCreationEnabled: boolean;
  readinessMessage: string;
};

export type SportRegistryEntry = {
  sportCode: SportCode;
  displayName: string;
  participantType: ParticipantType;
  availability: SportAvailabilityState;
  leagues: readonly LeagueRegistryEntry[];
};

export type SportRegistryV1 = {
  schemaVersion: "SPORT_REGISTRY_V1";
  sports: readonly SportRegistryEntry[];
};

/**
 * Canonical product vocabulary shared with AI Sports Predictor.
 * A registry entry is capability metadata, not evidence that a workflow or
 * model has been completed.
 */
export const SPORT_REGISTRY_V1: SportRegistryV1 = {
  schemaVersion: "SPORT_REGISTRY_V1",
  sports: [
    {
      sportCode: "BASEBALL",
      displayName: "Baseball",
      participantType: "TEAM",
      availability: "LIVE",
      leagues: [
        {
          leagueCode: "MLB",
          displayName: "Major League Baseball",
          participantType: "TEAM",
          availability: "LIVE",
          workflowAvailability: "ENABLED",
          projectCreationEnabled: true,
          readinessMessage: "The governed MLB workflow is available now.",
        },
      ],
    },
    {
      sportCode: "FOOTBALL",
      displayName: "Football",
      participantType: "TEAM",
      availability: "RESEARCH_SHADOW",
      leagues: [
        {
          leagueCode: "NFL",
          displayName: "National Football League",
          participantType: "TEAM",
          availability: "RESEARCH_SHADOW",
          workflowAvailability: "RESEARCH_ONLY",
          projectCreationEnabled: false,
          readinessMessage: "Governed NFL research assets exist, but the workflow remains research-only and cannot promote or deploy a model.",
        },
      ],
    },
    {
      sportCode: "BASKETBALL",
      displayName: "Basketball",
      participantType: "TEAM",
      availability: "PLANNED",
      leagues: [
        {
          leagueCode: "NBA",
          displayName: "National Basketball Association",
          participantType: "TEAM",
          availability: "PLANNED",
          workflowAvailability: "PLANNED",
          projectCreationEnabled: false,
          readinessMessage: "Planned registration only; no governed NBA workflow is available.",
        },
        {
          leagueCode: "WNBA",
          displayName: "Women's National Basketball Association",
          participantType: "TEAM",
          availability: "PLANNED",
          workflowAvailability: "PLANNED",
          projectCreationEnabled: false,
          readinessMessage: "Planned registration only; no governed WNBA workflow is available.",
        },
      ],
    },
    {
      sportCode: "MMA",
      displayName: "Mixed Martial Arts",
      participantType: "INDIVIDUAL",
      availability: "PLANNED",
      leagues: [
        {
          leagueCode: "UFC",
          displayName: "UFC",
          participantType: "INDIVIDUAL",
          availability: "PLANNED",
          workflowAvailability: "PLANNED",
          projectCreationEnabled: false,
          readinessMessage: "Planned registration only; no governed UFC workflow is available.",
        },
      ],
    },
  ],
};

export const LIVE_PROJECT_FILTER_LEAGUES = ["ALL", "MLB", "NFL"] as const;
export type LiveProjectLeagueFilter = (typeof LIVE_PROJECT_FILTER_LEAGUES)[number];

export function sportRegistryEntry(sportCode: SportCode) {
  return SPORT_REGISTRY_V1.sports.find((sport) => sport.sportCode === sportCode);
}

export function leagueRegistryEntry(leagueCode: LeagueCode) {
  return SPORT_REGISTRY_V1.sports
    .flatMap((sport) => sport.leagues.map((league) => ({ sport, league })))
    .find(({ league }) => league.leagueCode === leagueCode);
}

export function sportCodeForLeague(leagueCode: LeagueCode): SportCode | null {
  return leagueRegistryEntry(leagueCode)?.sport.sportCode ?? null;
}

export function selectableLeagueEntries() {
  return SPORT_REGISTRY_V1.sports.flatMap((sport) =>
    sport.leagues
      .filter((league) => league.projectCreationEnabled)
      .map((league) => ({ sport, league })),
  );
}

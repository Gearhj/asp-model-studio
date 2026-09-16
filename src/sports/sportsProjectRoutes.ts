export const SPORTS_PROJECT_ID_PARAM = "projectId";

export function canonicalSportsProjectId(urlProjectId: string | null | undefined, stateProjectId: string | null | undefined) {
  return String(urlProjectId || "").trim() || String(stateProjectId || "").trim();
}

export function sportsProjectOverviewRoute(projectId: string) {
  const params = new URLSearchParams({ [SPORTS_PROJECT_ID_PARAM]: projectId.trim() });
  return `/project-overview?${params.toString()}`;
}

export function mlbWorkflowRoute(projectId: string, stage = 1, extra: Record<string, string | number | undefined> = {}) {
  const params = new URLSearchParams({
    [SPORTS_PROJECT_ID_PARAM]: projectId.trim(),
    stage: String(stage),
  });
  for (const [key, value] of Object.entries(extra)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return `/workflows/mlb?${params.toString()}`;
}

export function sportWorkflowRoute(leagueCode: "MLB" | "NFL", projectId: string, stage?: number) {
  const params = new URLSearchParams({ [SPORTS_PROJECT_ID_PARAM]: projectId.trim() });
  if (stage !== undefined) params.set("stage", String(stage));
  return `/workflows/${leagueCode.toLowerCase()}?${params.toString()}`;
}

// Ambient cache of the workflow store's current projectId, kept in sync by a
// subscription set up in src/state/useWorkflowStore.ts. Exists as its own
// tiny module (mirroring src/lib/authSession.ts's userId cache) so that
// src/lib/localDataset.ts can resolve "which project is active" without
// importing the zustand store module directly -- that import would create a
// cycle (localProjects.ts -> localDataset.ts -> useWorkflowStore.ts ->
// localProjects.ts) and would drag the store's own dependency graph into
// every lightweight test harness that imports localDataset.ts in isolation.
let cachedProjectId = "";

export function setCachedProjectId(projectId: string) {
  cachedProjectId = projectId || "";
}

export function getCachedProjectId(): string {
  return cachedProjectId;
}

export type InterpretationCandidate = {
  key: string;
  name: string;
  task?: "classification" | "regression" | "anomaly";
  selectedAt: string;
};

const keyFor = (projectId: string) => `atlas-interpretation-candidates:${projectId}`;

export function loadInterpretationCandidates(projectId: string): InterpretationCandidate[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(keyFor(projectId)) || "[]");
    return Array.isArray(parsed) ? parsed.filter((item): item is InterpretationCandidate => Boolean(item?.key && item?.name)) : [];
  } catch {
    return [];
  }
}

export function saveInterpretationCandidates(projectId: string, candidates: InterpretationCandidate[]) {
  localStorage.setItem(keyFor(projectId), JSON.stringify(candidates));
  return candidates;
}

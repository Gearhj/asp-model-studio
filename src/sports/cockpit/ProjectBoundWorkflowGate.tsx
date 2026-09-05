import { useEffect, useState, type ReactNode } from "react";
import { getJSON } from "../../lib/api";
import { getCachedUserId } from "../../lib/authSession";

type WorkflowState = {
  ok: boolean; workflowBlocked?: boolean;
  authority: { projectId: string; projectName: string; authorityKey: string | null };
  population: { developmentRows: number | null; finalOotRows: number | null; finalOotLocked: boolean; finalOotTargetsMaterialized: boolean };
  readiness: { ready: boolean; blockers: string[] };
  treatment?: { status: string; canAdopt: boolean };
  historicalEvidence?: { status: string; split: { version: number; foldCount: number }; featureSets: { featureSetId: string; name: string; featureCount: number }[]; runs: { runId: string; receiptSha256: string; candidates: { candidateId: string; modelFamily: string; status: string; meanOofLogLoss: number | null }[] }[]; limitation: string };
  priorAuthority?: { status: string; featureCounts?: { readyGovernedPriorV1?: number; readyGovernedPriorV2?: number; retiredByScientificDecision?: number }; wave2?: { authorityId?: string; authorityChecksum?: string; foldAuthorities?: unknown[]; finalDevelopmentAuthority?: { fittedId?: string } } | null };
  audit: { providerCalls: number; finalOotTargetAccessed: boolean; legacyGlobalMatrixUsed: boolean };
};

export function ProjectBoundWorkflowGate({ projectId, stepLabel, children }: { projectId: string; stepLabel: string; children: ReactNode }) {
  const [state, setState] = useState<WorkflowState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const userId = getCachedUserId();
  useEffect(() => {
    let active = true;
    setState(null); setError(null);
    if (!projectId || !userId) { setError("Select an authenticated project before opening model development."); return; }
    getJSON<WorkflowState>(`/projects/${encodeURIComponent(projectId)}/sports/stage3-model-laboratory/summary`).then((value) => {
      if (!active) return;
      if (value.ok !== true || value.authority?.projectId !== projectId || (!value.workflowBlocked && !value.authority?.authorityKey)
          || value.population?.finalOotLocked !== true || value.population?.finalOotTargetsMaterialized !== false
          || value.audit?.providerCalls !== 0 || value.audit?.finalOotTargetAccessed !== false
          || value.audit?.legacyGlobalMatrixUsed !== false) throw new Error("The selected project authority failed verification.");
      setState(value);
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Project prerequisites unavailable."); });
    return () => { active = false; };
  }, [projectId, userId]);
  if (error) return <section role="alert" className="min-w-0 break-words rounded-xl border border-amber-300 bg-amber-50 p-5"><h2>{stepLabel}</h2><p>{error}</p></section>;
  if (!state || state.authority.projectId !== projectId) return <p role="status">Loading selected project prerequisites…</p>;
  if (!state.workflowBlocked) return <>{children}</>;
  return <section data-testid="project-workflow-blocked" className="min-w-0 max-w-full space-y-4 break-words rounded-xl border border-amber-300 bg-amber-50 p-5">
    <h2 className="text-lg font-semibold">{stepLabel}</h2>
    <p className="font-semibold">{state.authority.projectName}</p><p className="break-all text-xs">{projectId}</p>
    <p>Development: {state.population.developmentRows?.toLocaleString() ?? "not authenticated"} rows · Final OOT: {state.population.finalOotRows?.toLocaleString() ?? "not authenticated"} rows — locked</p>
    <p>Treatment: {state.treatment?.status ?? "Not registered"}.{state.historicalEvidence ? " Original adopted configuration preserved." : " Adoption remains blocked."}</p>
    {!state.historicalEvidence && <p>{stepLabel === "Candidate Evaluation" ? "No candidate evidence is available for this project before its model-development prerequisites are complete." : stepLabel.includes("Refinement") ? "No finalist evidence is available for this project. Refinement remains blocked." : "This project is awaiting its governed modeling prerequisites."}</p>}
    {state.historicalEvidence && <div className="space-y-3"><h3 className="font-semibold">Verified historical evidence</h3><p>Split version {state.historicalEvidence.split.version} · {state.historicalEvidence.split.foldCount} chronological folds · {state.historicalEvidence.featureSets.length} registered feature sets · {state.historicalEvidence.runs.length} verified run receipts</p>
      <ul>{state.historicalEvidence.featureSets.map((item) => <li key={item.featureSetId}>{item.name}: {item.featureCount} features</li>)}</ul>
      {state.historicalEvidence.runs.map((run) => <details key={run.receiptSha256}><summary className="break-all">Run {run.runId}: {run.candidates.length} candidates</summary><ul>{run.candidates.map((candidate) => <li key={candidate.candidateId}>{candidate.modelFamily} · {candidate.status} · OOF log loss {candidate.meanOofLogLoss?.toFixed(6) ?? "unavailable"}</li>)}</ul></details>)}
      <p>{state.historicalEvidence.limitation}</p></div>}
    <ul className="list-disc pl-5">{state.readiness.blockers.map((reason, index) => <li key={index}>{reason}</li>)}</ul>
    {state.priorAuthority && <div className="space-y-2">
      <p>Prior authority: {state.priorAuthority.status === "AUTHENTICATED" ? "Authenticated" : "Canonical Wave 2 authority unavailable"}.</p>
      {state.priorAuthority.featureCounts && <p>V1 priors: {state.priorAuthority.featureCounts.readyGovernedPriorV1 ?? 0} · V2 priors: {state.priorAuthority.featureCounts.readyGovernedPriorV2 ?? 0} · Retired features: {state.priorAuthority.featureCounts.retiredByScientificDecision ?? 0} · Folds: {state.priorAuthority.wave2?.foldAuthorities?.length ?? 0}</p>}
      {state.priorAuthority.status === "AUTHENTICATED" && <details><summary>Verified authority identifiers</summary><p className="break-all text-xs">Bundle: {state.priorAuthority.wave2?.authorityId}</p><p className="break-all text-xs">Final development: {state.priorAuthority.wave2?.finalDevelopmentAuthority?.fittedId}</p></details>}
    </div>}
    <button type="button" disabled aria-describedby="project-workflow-block-reason" className="max-w-full whitespace-normal rounded border border-amber-400 px-4 py-2">Queue model development for this project</button>
    <p id="project-workflow-block-reason">Complete the listed prerequisites before any model can run. Navigation performs no fits, scoring, calibration, promotion, or final-OOT access.</p>
  </section>;
}

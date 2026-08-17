import { AlertTriangle, ArrowRight, CheckCircle2, CircleDashed, Database, GitBranch, Target } from "lucide-react";
import { Link } from "react-router-dom";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { loadSportsProjectMetadata, mlbPaBaselineStepPresentation, sportsWorkflowForId } from "./sportsConfig";
import { sportsIdentityBridgeIsValidated, sportsPaDecisionStatus, type SportsProjectStage, useActiveSportsDataset } from "./sportsEvidenceApi";

export default function SportsProjectOverview() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const workflowId = useWorkflowStore((state) => state.workflowId);
  const workflowSteps = useWorkflowStore((state) => state.workflowSteps);
  const datasetEvidence = useActiveSportsDataset();
  const workflow = sportsWorkflowForId(workflowId);
  const metadata = loadSportsProjectMetadata(projectId);
  const workspaceDataset = datasetEvidence.status === "ready" ? datasetEvidence.data : null;
  const governedProject = workspaceDataset?.project?.projectId === projectId ? workspaceDataset.project : null;
  const boundDataset = governedProject ? workspaceDataset : null;
  const baseline = boundDataset?.paBaseline;
  const decision = sportsPaDecisionStatus(baseline?.decision) || sportsPaDecisionStatus(baseline?.status) || (baseline ? "BLOCKED" : null);
  const projectBlocked = decision
    ? decision === "BLOCKED" || decision === "REJECTED_BASELINE"
    : governedProject?.status?.toLowerCase().includes("blocked") === true;
  const identityBridgeReason = !sportsIdentityBridgeIsValidated(boundDataset?.identityBridge) && boundDataset?.featureAudit?.missingBridge.isMissing
    ? boundDataset.featureAudit.missingBridge.reason
    : "";
  const governedStages = governedProject?.stages ?? [];
  const completed = governedProject
    ? governedStages.filter((stage) => ["complete", "completed"].includes(stage.status.toLowerCase())).length
    : workflowSteps.filter((step) => step.status === "complete").length;
  const governedEvidenceCount = governedProject
    ? governedStages.filter((stage) => !["pending", "not_configured", "not configured"].includes(stage.status.toLowerCase())).length
    : completed;
  const baselineEvidenceCount = baseline
    ? (baseline.candidates.length ? 2 : 0)
      + (baseline.calibration?.final2025 ? 1 : 0)
      + (baseline.calibration ? 1 : 0)
      + (baseline.graph?.nodes.length ? 1 : 0)
    : 0;
  const evidenced = Math.max(governedEvidenceCount, baselineEvidenceCount);
  const progress = Math.round((evidenced / Math.max(1, workflow.steps.length)) * 100);
  const displayName = governedProject?.name || (projectName === "Untitled Sports Project" ? `${workflow.title} Project` : projectName);
  const datasetLabel = boundDataset
    ? `${boundDataset.datasetId} · ${boundDataset.validationStatus} · project bound`
    : workspaceDataset
      ? `${workspaceDataset.datasetId} · workspace available, not bound`
    : datasetEvidence.status === "loading"
      ? "Loading evidence…"
      : datasetEvidence.status === "error"
        ? "Evidence unavailable"
        : "No Dataset Registered";
  const nextMilestone = workflow.key === "nfl"
    ? "Register the first immutable ASP sports dataset manifest and begin the NFL drive-outcome baseline experiment."
    : decision === "RESEARCH_CHALLENGER"
      ? "Review the registered PA research challenger and its bootstrap comparison evidence."
      : decision === "RESEARCH_BASELINE"
        ? "Preserve the PA research baseline and plan prospective evidence; bundle export remains unavailable."
        : decision === "REJECTED_BASELINE"
          ? "Review why the PA candidate was rejected before configuring another research run."
          : decision === "BLOCKED"
            ? baseline?.decisionReason || "Resolve the recorded PA baseline blocker before another governed run."
    : identityBridgeReason
      ? "Register the governed plate-appearance-to-player-prior identity bridge required for exact Y−1 joins."
      : boundDataset
        ? "Review the registered evidence, temporal folds, and limitations before any model work begins."
        : workspaceDataset
          ? "Bind this project through the governed dataset-registration flow before using workspace evidence."
      : "Register the first immutable ASP sports dataset manifest and begin the MLB plate-appearance baseline experiment.";

  function governedStage(stepId: string, number: number, title: string): SportsProjectStage | undefined {
    return governedStages.find((stage) => stage.stepId === stepId || stage.number === number || stage.title?.toLowerCase() === title.toLowerCase());
  }

  return (
    <div className="sports-page-shell">
      <section className="sports-hero-panel p-6 sm:p-8 lg:p-10">
        <div className="relative z-10 grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-end">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="sports-status sports-status--teal">{workflow.status}</span>
              <span className="sports-status border-white/15 bg-white/10 text-slate-200">{workflow.league}</span>
              {governedProject ? <span className={`sports-status max-w-full whitespace-normal break-words text-center leading-4 ${projectBlocked ? "sports-status--amber" : "sports-status--green"}`}>{decision || governedProject.status || "REGISTERED"}</span> : null}
            </div>
            <h1 className="mt-5 text-3xl font-semibold tracking-tight text-white sm:text-4xl lg:text-[42px]">{displayName}</h1>
            <p className="mt-4 max-w-3xl text-[15px] leading-7 text-slate-300">{governedProject?.researchPurpose || metadata?.researchPurpose || "Configure the forecast contract to establish this project’s research purpose."}</p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to={`/workflows/${workflow.key}`} className="sports-primary-button">Open {workflow.league} workflow <ArrowRight size={17} /></Link>
              <Link to="/data-warehouse" className="sports-dark-button"><Database size={17} /> Data evidence</Link>
            </div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-5 backdrop-blur">
            <div className="flex items-end justify-between"><span className="text-sm font-medium text-slate-300">Workflow evidence</span><strong className="text-3xl tabular-nums text-white">{progress}%</strong></div>
            <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10"><span className="block h-full rounded-full bg-gradient-to-r from-teal-400 to-cyan-300" style={{ width: `${progress}%` }} /></div>
            <p className="mt-3 text-xs leading-5 text-slate-400">{evidenced} of {workflow.steps.length} stages have registered evidence; {completed} are complete. No completion is inferred from page visits.</p>
          </div>
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric icon={<Target size={19} />} label="Primary target" value={governedProject?.primaryTarget || metadata?.primaryTarget || "Not Configured"} />
        <Metric icon={<CircleDashed size={19} />} label="Forecast lifecycle" value={governedProject?.forecastLifecycle || metadata?.lifecycle || "Not Configured"} />
        <Metric icon={<Database size={19} />} label="Sports dataset" value={datasetLabel} />
        <Metric icon={<GitBranch size={19} />} label="Model graph" value={baseline?.graph?.nodes.length ? `Research graph · ${decision || "BLOCKED"}` : "No Model Graph"} />
      </section>

      {governedProject ? <section className="sports-panel p-5 sm:p-6" aria-label="Governed MLB forecast contract"><p className="sports-kicker">Governed forecast contract</p><div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><ContractFact label="Development period" value={governedProject.developmentPeriod} /><ContractFact label="Prior history" value={governedProject.priorHistory} /><ContractFact label="Baseline population" value={governedProject.baselinePopulation} /><ContractFact label="Upper-bound research" value={governedProject.upperBoundPopulation} /></div>{governedProject.secondaryTargets?.length ? <div className="mt-5 border-t border-slate-100 pt-4"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Secondary targets</div><div className="mt-2 flex flex-wrap gap-2">{governedProject.secondaryTargets.map((target) => <span key={target} className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs font-semibold text-slate-700">{target}</span>)}</div></div> : null}</section> : null}

      <section className="sports-panel overflow-hidden">
        <div className="border-b border-slate-200 p-5 sm:p-7">
          <p className="sports-kicker">Shared sports modeling workflow</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">From forecast contract to terminal research decision</h2>
          <p className="mt-2 max-w-3xl text-[15px] leading-7 text-slate-600">Every step exposes its purpose, prerequisites, expected outputs, and evidence state. {governedProject ? "Statuses come from the governed project registration; page visits never imply completion." : "The workflow begins empty by design."}</p>
        </div>
        <div className="grid gap-px bg-slate-200 lg:grid-cols-2">
          {workflow.steps.map((step) => {
            const stored = workflowSteps.find((item) => item.id === step.id);
            const evidence = governedStage(step.id, step.number, step.title);
            const phase3Presentation = baseline && decision !== "BLOCKED" && workflow.key === "mlb" ? mlbPaBaselineStepPresentation(step) : undefined;
            const baselineStatus = baseline && decision === "BLOCKED" && step.number === 11 ? "BLOCKED"
              : baseline && step.number === 6 && baseline.candidates.length ? "COMPLETE"
              : baseline && step.number === 8 && baseline.candidates.length ? "COMPLETE"
                : baseline && step.number === 9 && baseline.calibration?.final2025 ? "COMPLETE"
                  : baseline && step.number === 10 && baseline.calibration ? "COMPLETE"
                    : baseline && step.number === 11 && baseline.graph?.nodes.length ? "COMPLETE"
                      : step.number === 12 ? "NOT_CONFIGURED"
                        : undefined;
            const evidenceStatus = step.number === 12
              ? "NOT_CONFIGURED"
              : decision === "BLOCKED" && step.number === 11
                ? "BLOCKED"
                : phase3Presentation?.status || evidence?.status || baselineStatus || (stored?.status === "complete" ? "COMPLETE" : "NOT CONFIGURED");
            const complete = evidenceStatus.toLowerCase().includes("complete");
            const blocked = evidenceStatus.toLowerCase() === "blocked";
            const configured = !["pending", "not_configured", "not configured"].includes(evidenceStatus.toLowerCase());
            return (
              <article id={step.id} key={step.id} className="bg-white p-5 sm:p-6">
                <div className="flex items-start gap-4">
                  <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-sm font-bold tabular-nums ${complete ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>{complete ? <CheckCircle2 size={19} /> : step.number}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <h3 className="text-lg font-semibold text-slate-950">{step.title}</h3>
                      <span className={`sports-status ${complete ? "sports-status--green" : blocked ? "sports-status--amber" : configured ? "sports-status--teal" : "sports-status--neutral"}`}>{evidenceStatus.toUpperCase()}</span>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-600">{phase3Presentation?.purpose || step.purpose}</p>
                    {evidence?.evidence?.length ? <ul className={`mt-3 grid gap-1 text-xs leading-5 ${blocked ? "text-amber-900" : "text-emerald-800"}`}>{evidence.evidence.map((item) => <li key={item} className="flex gap-2">{blocked ? <AlertTriangle size={14} className="mt-0.5 shrink-0" /> : <CheckCircle2 size={14} className="mt-0.5 shrink-0" />}{item}</li>)}</ul> : null}
                    <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
                      <summary className="cursor-pointer font-semibold text-slate-800">Prerequisites & expected outputs</summary>
                      <div className="mt-3 grid gap-4 sm:grid-cols-2">
                        <List label="Prerequisites" items={(phase3Presentation?.prerequisites || step.prerequisites).length ? (phase3Presentation?.prerequisites || step.prerequisites) : ["None — starting step"]} />
                        <List label="Expected outputs" items={phase3Presentation?.outputs || step.outputs} />
                      </div>
                    </details>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="rounded-2xl border border-cyan-900/30 bg-slate-950 p-6 text-white shadow-xl sm:p-7">
        <p className="sports-kicker text-cyan-300">Next platform milestone</p>
        <h2 className="mt-2 text-xl font-semibold">{nextMilestone}</h2>
        <p className="mt-3 text-sm leading-6 text-slate-400">{boundDataset
          ? baseline ? `Run ${baseline.runId} is bound to registration ${boundDataset.registrationId} with terminal research status ${decision || "BLOCKED"}. No game simulation or export bundle is implied.` : `${identityBridgeReason ? `${identityBridgeReason} ` : ""}Bound to registration ${boundDataset.registrationId}. No plate-appearance model, game simulation, or export is implied.`
          : workspaceDataset
            ? "A validated MLB dataset is available in this workspace, but it is not bound to this project. No governed project evidence is inferred."
            : "Explanatory milestone only. No connection to the external sports exchange has been created."}</p>
      </section>
    </div>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <div className="sports-panel p-4 sm:p-5"><div className="flex items-center gap-2 text-teal-700">{icon}<span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span></div><div className="mt-3 text-lg font-semibold text-slate-950">{value}</div></div>;
}

function ContractFact({ label, value }: { label: string; value?: string }) {
  return <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 text-sm font-semibold text-slate-900">{value || "Not recorded"}</div></div>;
}

function List({ label, items }: { label: string; items: string[] }) {
  return <div><div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</div><ul className="mt-2 grid gap-1.5 text-sm text-slate-600">{items.map((item) => <li key={item} className="flex gap-2"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />{item}</li>)}</ul></div>;
}

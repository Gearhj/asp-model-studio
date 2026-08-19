import { ArrowRight, CheckCircle2, CircleDot, Database, GitBranch, Lock, PlayCircle, Target } from "lucide-react";
import { Link } from "react-router-dom";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { loadSportsProjectMetadata, sportsWorkflowForId } from "./sportsConfig";
import { sportsPaDecisionStatus, useActiveSportsDataset } from "./sportsEvidenceApi";
import {
  resolveStages, firstActionableStage, completionSummary, loadContract, loadBinding,
  type StageResolution, type StageStatus,
} from "./workflow/workflowState";

const STATUS_CHIP: Record<StageStatus, string> = {
  COMPLETE: "sports-status--green",
  CURRENT: "sports-status--teal",
  READY: "sports-status--teal",
  BLOCKED: "sports-status--neutral",
  STALE: "sports-status--amber",
};
const STATUS_LABEL: Record<StageStatus, string> = { COMPLETE: "Complete", CURRENT: "Current stage", READY: "Ready", BLOCKED: "Blocked", STALE: "Requires review" };

export default function SportsProjectOverview() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const workflowId = useWorkflowStore((state) => state.workflowId);
  const datasetEvidence = useActiveSportsDataset();
  const workflow = sportsWorkflowForId(workflowId);
  const metadata = loadSportsProjectMetadata(projectId);
  const dataset = datasetEvidence.status === "ready" ? datasetEvidence.data : null;
  const contract = loadContract(projectId);
  const binding = loadBinding(projectId);
  const isMlb = workflow.key === "mlb";

  const resolutions = isMlb ? resolveStages(projectId, dataset, contract, binding) : [];
  const summary = isMlb ? completionSummary(resolutions) : { complete: 0, ready: 0, blocked: 0, total: 9, pct: 0 };
  const nextStep = isMlb ? firstActionableStage(resolutions) : 1;
  const nextRes = resolutions.find((r) => r.number === nextStep);
  const baseline = dataset?.paBaseline;
  const phase4 = dataset?.phase4;
  const decision = sportsPaDecisionStatus(baseline?.decision) || sportsPaDecisionStatus(baseline?.status);
  const displayName = projectName && projectName !== "Untitled Sports Project" ? projectName : `${workflow.title} Project`;
  const datasetLabel = binding ? `${binding.datasetId} · project bound` : dataset ? `${dataset.datasetId} · available, not bound` : datasetEvidence.status === "loading" ? "Loading evidence…" : "No dataset bound";
  const isNew = summary.complete === 0;

  return (
    <div className="sports-page-shell space-y-5">
      {/* Hero with dominant Continue Work */}
      <section className="sports-hero-panel p-6 sm:p-8 lg:p-10">
        <div className="relative z-10 grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-end">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="sports-status sports-status--teal">{workflow.status}</span>
              <span className="sports-status border-white/15 bg-white/10 text-slate-200">{workflow.league}</span>
              {decision ? <span className="sports-status sports-status--green">{decision}</span> : null}
            </div>
            <h1 className="mt-5 text-3xl font-semibold tracking-tight text-white sm:text-4xl lg:text-[42px]">{displayName}</h1>
            {isMlb && nextRes ? (
              <p className="mt-3 text-[15px] leading-7 text-slate-300">
                {isNew ? "Let’s set up your MLB forecasting program." : "Welcome back."} Next: <b className="text-cyan-200">Stage {nextRes.number} — {nextRes.title}</b>.
              </p>
            ) : (
              <p className="mt-4 max-w-3xl text-[15px] leading-7 text-slate-300">{metadata?.researchPurpose || "Configure the forecast contract to establish this project’s research purpose."}</p>
            )}
            <div className="mt-6 flex flex-wrap gap-3">
              {isMlb ? (
                <Link to={`/workflows/mlb?stage=${nextStep}`} className="sports-primary-button text-base">
                  <PlayCircle size={18} /> {isNew ? "Start Stage 1" : `Continue Stage ${nextStep}`} <ArrowRight size={17} />
                </Link>
              ) : (
                <Link to={`/workflows/${workflow.key}`} className="sports-primary-button">Open {workflow.league} workflow <ArrowRight size={17} /></Link>
              )}
              <Link to="/data-warehouse" className="sports-dark-button"><Database size={17} /> Data evidence</Link>
            </div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-5 backdrop-blur">
            <div className="flex items-end justify-between"><span className="text-sm font-medium text-slate-300">Program completion</span><strong className="text-3xl tabular-nums text-white">{summary.pct}%</strong></div>
            <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10"><span className="block h-full rounded-full bg-gradient-to-r from-teal-400 to-cyan-300" style={{ width: `${summary.pct}%` }} /></div>
            <p className="mt-3 text-xs leading-5 text-slate-400">{summary.complete} of {summary.total} complete · {summary.ready} ready · {(summary as any).available ?? 0} evidence available · {summary.blocked} blocked</p>
          </div>
        </div>
      </section>

      {/* Metrics */}
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric icon={<Target size={19} />} label="Forecast target" value={contract?.target || metadata?.primaryTarget || "Not configured"} />
        <Metric icon={<CircleDot size={19} />} label="Temporal policy" value={contract ? `${contract.developmentSeasons[0]}–${contract.developmentSeasons.slice(-1)[0]} → ${contract.validationSeason} → ${contract.frozenSeason}` : "Not configured"} />
        <Metric icon={<Database size={19} />} label="Sports dataset" value={datasetLabel} />
        <Metric icon={<GitBranch size={19} />} label="Model graph" value={phase4?.graph?.nodes.length ? `${phase4.graph.nodes.length} nodes` : baseline?.graph?.nodes.length ? `${decision || "research"}` : "No graph yet"} />
      </section>

      {/* Stage dashboard */}
      {isMlb && (
        <section className="sports-panel overflow-hidden">
          <div className="border-b border-slate-200 p-5 sm:p-6">
            <p className="sports-kicker">Guided workflow</p>
            <h2 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">Your 9-stage MLB program</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">Each stage shows its status and the exact next action. Status comes from registered evidence — page visits never imply completion.</p>
          </div>
          <div className="grid gap-px bg-slate-200 lg:grid-cols-2">
            {resolutions.map((r) => <StageCard key={r.id} r={r} />)}
          </div>
        </section>
      )}
    </div>
  );
}

function StageCard({ r }: { r: StageResolution }) {
  const complete = r.status === "COMPLETE";
  const blocked = r.status === "BLOCKED";
  const actionable = r.status === "CURRENT" || r.status === "READY";
  return (
    <article className="bg-white p-5">
      <div className="flex items-start gap-3">
        <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl text-sm font-bold tabular-nums ${complete ? "bg-emerald-100 text-emerald-700" : actionable ? "bg-cyan-100 text-cyan-700" : "bg-slate-100 text-slate-500"}`}>
          {complete ? <CheckCircle2 size={18} /> : blocked ? <Lock size={15} /> : r.number}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h3 className="text-base font-semibold text-slate-950">{r.title}</h3>
            <span className={`sports-status ${STATUS_CHIP[r.status]}`}>{r.evidenceState === "WORKSPACE_EVIDENCE_AVAILABLE" && r.status !== "COMPLETE" ? "Available" : STATUS_LABEL[r.status]}</span>
          </div>
          {blocked ? (
            <p className="mt-2 text-sm text-slate-500">Requires: {r.blockedReason}</p>
          ) : (
            <p className="mt-2 text-sm leading-6 text-slate-600">{r.purpose}</p>
          )}
          <div className="mt-3">
            {blocked ? (
              <Link to={`/workflows/mlb?stage=${r.blockedByNumber}`} className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-600 hover:text-slate-900">Complete Step {r.blockedByNumber} <ArrowRight size={14} /></Link>
            ) : (
              <Link to={`/workflows/mlb?stage=${r.number}`} className={`inline-flex items-center gap-1.5 text-sm font-semibold ${complete ? "text-slate-600 hover:text-slate-900" : "text-cyan-700 hover:text-cyan-800"}`}>
                {complete ? "Review" : r.action.label} <ArrowRight size={14} />
              </Link>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <div className="sports-panel p-4 sm:p-5"><div className="flex items-center gap-2 text-teal-700">{icon}<span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span></div><div className="mt-3 text-lg font-semibold text-slate-950">{value}</div></div>;
}

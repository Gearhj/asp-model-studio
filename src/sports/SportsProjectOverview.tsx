import { ArrowRight, CheckCircle2, CircleDashed, Database, GitBranch, Target } from "lucide-react";
import { Link } from "react-router-dom";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { loadSportsProjectMetadata, sportsWorkflowForId } from "./sportsConfig";

export default function SportsProjectOverview() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const workflowId = useWorkflowStore((state) => state.workflowId);
  const workflowSteps = useWorkflowStore((state) => state.workflowSteps);
  const workflow = sportsWorkflowForId(workflowId);
  const metadata = loadSportsProjectMetadata(projectId);
  const completed = workflowSteps.filter((step) => step.status === "complete").length;
  const progress = Math.round((completed / Math.max(1, workflowSteps.length)) * 100);
  const nextMilestone = workflow.key === "nfl"
    ? "Register the first immutable ASP sports dataset manifest and begin the NFL drive-outcome baseline experiment."
    : "Register the first immutable ASP sports dataset manifest and begin the MLB plate-appearance baseline experiment.";

  return (
    <div className="sports-page-shell">
      <section className="sports-hero-panel p-6 sm:p-8 lg:p-10">
        <div className="relative z-10 grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-end">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="sports-status sports-status--teal">{workflow.status}</span>
              <span className="sports-status border-white/15 bg-white/10 text-slate-200">{workflow.league}</span>
            </div>
            <h1 className="mt-5 text-3xl font-semibold tracking-tight text-white sm:text-4xl lg:text-[42px]">{projectName === "Untitled Sports Project" ? `${workflow.title} Project` : projectName}</h1>
            <p className="mt-4 max-w-3xl text-[15px] leading-7 text-slate-300">{metadata?.researchPurpose || "Configure the forecast contract to establish this project’s research purpose."}</p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to={`/workflows/${workflow.key}`} className="sports-primary-button">Open {workflow.league} workflow <ArrowRight size={17} /></Link>
              <Link to="/data-warehouse" className="sports-dark-button"><Database size={17} /> Data evidence</Link>
            </div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-5 backdrop-blur">
            <div className="flex items-end justify-between"><span className="text-sm font-medium text-slate-300">Workflow completion</span><strong className="text-3xl tabular-nums text-white">{progress}%</strong></div>
            <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10"><span className="block h-full rounded-full bg-gradient-to-r from-teal-400 to-cyan-300" style={{ width: `${progress}%` }} /></div>
            <p className="mt-3 text-xs leading-5 text-slate-400">{completed} of {workflowSteps.length} steps complete. No completion is inferred from page visits.</p>
          </div>
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric icon={<Target size={19} />} label="Primary target" value={metadata?.primaryTarget || "Not Configured"} />
        <Metric icon={<CircleDashed size={19} />} label="Forecast lifecycle" value={metadata?.lifecycle || "Not Configured"} />
        <Metric icon={<Database size={19} />} label="Sports dataset" value="No Dataset Registered" />
        <Metric icon={<GitBranch size={19} />} label="Model graph" value="No Model Graph" />
      </section>

      <section className="sports-panel overflow-hidden">
        <div className="border-b border-slate-200 p-5 sm:p-7">
          <p className="sports-kicker">Shared sports modeling workflow</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">From forecast contract to ASP execution bundle</h2>
          <p className="mt-2 max-w-3xl text-[15px] leading-7 text-slate-600">Every step exposes its purpose, prerequisites, expected outputs, and evidence state. The workflow begins empty by design.</p>
        </div>
        <div className="grid gap-px bg-slate-200 lg:grid-cols-2">
          {workflow.steps.map((step) => {
            const stored = workflowSteps.find((item) => item.id === step.id);
            const complete = stored?.status === "complete";
            return (
              <article id={step.id} key={step.id} className="bg-white p-5 sm:p-6">
                <div className="flex items-start gap-4">
                  <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-sm font-bold tabular-nums ${complete ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>{complete ? <CheckCircle2 size={19} /> : step.number}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <h3 className="text-lg font-semibold text-slate-950">{step.title}</h3>
                      <span className={`sports-status ${complete ? "sports-status--green" : "sports-status--neutral"}`}>{complete ? "COMPLETE" : "NOT CONFIGURED"}</span>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-600">{step.purpose}</p>
                    <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
                      <summary className="cursor-pointer font-semibold text-slate-800">Prerequisites & expected outputs</summary>
                      <div className="mt-3 grid gap-4 sm:grid-cols-2">
                        <List label="Prerequisites" items={step.prerequisites.length ? step.prerequisites : ["None — starting step"]} />
                        <List label="Expected outputs" items={step.outputs} />
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
        <p className="mt-3 text-sm leading-6 text-slate-400">Explanatory milestone only. No connection to the external ASP warehouse has been created.</p>
      </section>
    </div>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <div className="sports-panel p-4 sm:p-5"><div className="flex items-center gap-2 text-teal-700">{icon}<span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span></div><div className="mt-3 text-lg font-semibold text-slate-950">{value}</div></div>;
}

function List({ label, items }: { label: string; items: string[] }) {
  return <div><div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</div><ul className="mt-2 grid gap-1.5 text-sm text-slate-600">{items.map((item) => <li key={item} className="flex gap-2"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500" />{item}</li>)}</ul></div>;
}

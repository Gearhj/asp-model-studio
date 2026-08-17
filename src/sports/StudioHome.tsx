import { Link } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  Box,
  ChevronRight,
  CircleDot,
  Clock3,
  Database,
  FlaskConical,
  FolderKanban,
  Gauge,
  Layers3,
  Network,
  PackageCheck,
  Plus,
  Radar,
  ShieldCheck,
  Sparkles,
  Target,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { formatProjectDate, loadLocalProjects } from "../lib/localProjects";
import {
  MLB_WORKFLOW,
  NFL_WORKFLOW,
  PIPELINE_NODES,
  PLANNED_SPORTS,
  isSportsWorkflow,
} from "./sportsConfig";
import { useActiveSportsDataset } from "./sportsEvidenceApi";

type StatusCard = {
  label: string;
  value: number;
  helper: string;
  icon: LucideIcon;
  tone: "cyan" | "blue" | "amber" | "emerald";
};

const pipelineIcons: LucideIcon[] = [Database, Layers3, Target, Network, Gauge, ShieldCheck, PackageCheck];

const statusTone: Record<StatusCard["tone"], string> = {
  cyan: "border-cyan-200/80 bg-cyan-50/70 text-cyan-800",
  blue: "border-blue-200/80 bg-blue-50/70 text-blue-800",
  amber: "border-amber-200/80 bg-amber-50/70 text-amber-800",
  emerald: "border-emerald-200/80 bg-emerald-50/70 text-emerald-800",
};

export default function StudioHome() {
  const datasetEvidence = useActiveSportsDataset();
  const activeDataset = datasetEvidence.status === "ready" ? datasetEvidence.data : null;
  const governedProject = activeDataset?.project ?? null;
  const sportsProjects = loadLocalProjects().filter((project) => isSportsWorkflow(project.workflowId));
  const localProjects = governedProject ? sportsProjects.filter((project) => project.projectId !== governedProject.projectId && project.projectName !== governedProject.name) : sportsProjects;
  const registeredDatasets = activeDataset ? 1 : 0;
  const recentProjects = localProjects.slice(0, governedProject ? 3 : 4);
  const projectCount = localProjects.length + (governedProject ? 1 : 0);
  const featureBlocked = activeDataset?.featureAudit?.status === "BLOCKED";
  const projectBlocked = governedProject?.status?.toLowerCase().includes("blocked") === true;
  const modelingLimitation = activeDataset?.featureAudit?.missingBridge.reason
    || activeDataset?.limitations.find((item) => /identity|bridge|prior/i.test(item));
  const datasetHelper = activeDataset
    ? `${activeDataset.datasetId} · ${activeDataset.validationStatus}`
    : datasetEvidence.status === "error"
      ? "Governed registry unavailable"
      : datasetEvidence.status === "loading"
        ? "Checking governed registry"
        : "No dataset registered";
  const statusCards: StatusCard[] = [
    { label: "Sports Projects", value: projectCount, helper: governedProject ? (projectBlocked ? "Governed MLB project · modeling blocked" : "Governed MLB project registered") : projectCount ? "Target-local projects" : "No project created", icon: FolderKanban, tone: projectBlocked ? "amber" : "cyan" },
    { label: "Registered Datasets", value: registeredDatasets, helper: datasetHelper, icon: Database, tone: "blue" },
    { label: "Active Experiments", value: 0, helper: "No experiment run", icon: FlaskConical, tone: "amber" },
    { label: "Research Challengers", value: 0, helper: "No challenger selected", icon: Activity, tone: "amber" },
    { label: "Model Bundles", value: 0, helper: "No bundle exported", icon: Box, tone: "emerald" },
    { label: "Monitoring Plans", value: 0, helper: "No plan configured", icon: Radar, tone: "blue" },
  ];

  return (
    <main className="sports-page-shell w-full space-y-6 pb-8 text-slate-950">
      <section className="relative isolate overflow-hidden rounded-3xl border border-slate-800 bg-slate-950 text-white shadow-[0_24px_70px_-32px_rgba(2,132,199,0.7)]">
        <div
          className="pointer-events-none absolute inset-0 opacity-40"
          aria-hidden="true"
          style={{
            backgroundImage:
              "linear-gradient(rgba(56,189,248,.08) 1px, transparent 1px), linear-gradient(90deg, rgba(56,189,248,.08) 1px, transparent 1px), radial-gradient(circle at 86% 8%, rgba(34,211,238,.28), transparent 31%), radial-gradient(circle at 4% 92%, rgba(37,99,235,.24), transparent 30%)",
            backgroundSize: "34px 34px, 34px 34px, auto, auto",
          }}
        />
        <div className="relative grid gap-8 px-5 py-7 sm:px-7 sm:py-9 xl:grid-cols-[minmax(0,0.86fr)_minmax(560px,1.14fr)] xl:items-center xl:px-10 xl:py-11">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-300/25 bg-cyan-300/10 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-100">
              <Sparkles size={14} aria-hidden="true" /> Sports model command center
            </div>
            <h1 className="mt-5 max-w-3xl text-4xl font-semibold leading-[1.05] tracking-[-0.035em] text-white sm:text-5xl">
              Build the Models Behind the Game
            </h1>
            <p className="mt-4 max-w-2xl text-base font-semibold leading-7 text-cyan-100">
              Build, simulate, validate, and deploy sophisticated sports forecasting systems.
            </p>
            <p className="mt-2 max-w-2xl text-[15px] leading-7 text-slate-300 sm:text-base">
              ASP Model Studio brings player state, team dynamics, event models, simulations, validation, and deployment into one sports-science workflow.
            </p>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-cyan-100/80">
              Develop player, team, event, usage, and game-simulation models through one governed analytical workflow.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Link
                to="/projects/new"
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-cyan-300 px-5 py-2.5 text-sm font-semibold text-slate-950 shadow-lg shadow-cyan-950/30 transition hover:bg-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200"
              >
                <Plus size={17} aria-hidden="true" /> Create Sports Project
              </Link>
              <Link
                to="/workflows"
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-white/20 bg-white/10 px-5 py-2.5 text-sm font-semibold text-white transition hover:border-white/30 hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200"
              >
                Explore Workflows <ArrowRight size={17} aria-hidden="true" />
              </Link>
            </div>
          </div>

          <PipelineMap />
        </div>
      </section>

      <section aria-labelledby="studio-status-heading">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.15em] text-cyan-700">Target-local state</div>
            <h2 id="studio-status-heading" className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">Studio status</h2>
          </div>
          <span className="inline-flex items-center gap-2 text-xs font-medium text-slate-500">
            <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" /> Honest local state
          </span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
          {statusCards.map((item) => (
            <article key={item.label} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div className={`flex h-9 w-9 items-center justify-center rounded-xl border ${statusTone[item.tone]}`}>
                  <item.icon size={17} aria-hidden="true" />
                </div>
                <span className="font-mono text-3xl font-semibold tabular-nums tracking-tight text-slate-950">{item.value}</span>
              </div>
              <div className="mt-4 text-sm font-semibold text-slate-900">{item.label}</div>
              <div className="mt-1 text-xs leading-5 text-slate-500">{item.helper}</div>
            </article>
          ))}
        </div>
      </section>

      <section aria-labelledby="sport-workflows-heading" className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.15em] text-cyan-700">Sport systems</div>
            <h2 id="sport-workflows-heading" className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">Forecasting workflows</h2>
          </div>
          <Link to="/workflows" className="inline-flex items-center gap-1.5 text-sm font-semibold text-blue-700 hover:text-blue-900">
            View workflow library <ChevronRight size={16} aria-hidden="true" />
          </Link>
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <WorkflowFeatureCard workflow={MLB_WORKFLOW} />
          <WorkflowFeatureCard workflow={NFL_WORKFLOW} />
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(330px,0.75fr)]">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">Roadmap</div>
              <h2 className="mt-1 text-xl font-semibold text-slate-950">Planned sports</h2>
            </div>
            <Clock3 size={20} className="text-slate-400" aria-hidden="true" />
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {PLANNED_SPORTS.map((sport) => (
              <article key={sport.name} className="rounded-xl border border-dashed border-slate-300 bg-slate-50/80 p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-semibold tracking-[0.12em] text-slate-500">{sport.icon}</span>
                  <span className="rounded-full border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold tracking-wide text-slate-500">PLANNED</span>
                </div>
                <h3 className="mt-5 text-sm font-semibold text-slate-800">{sport.name}</h3>
                <p className="mt-1 text-xs leading-5 text-slate-500">{sport.league}</p>
              </article>
            ))}
          </div>
        </div>

        <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 p-5 text-white shadow-sm sm:p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.15em] text-amber-300">Next platform milestone</div>
              <h2 className="mt-2 text-xl font-semibold">{activeDataset ? (featureBlocked ? "MLB evidence registered · feature view blocked" : "MLB evidence registered") : "Establish the MLB evidence baseline"}</h2>
            </div>
            <CircleDot size={21} className="shrink-0 text-amber-300" aria-hidden="true" />
          </div>
          <p className="mt-4 text-[15px] leading-7 text-slate-300">
            {activeDataset ? (modelingLimitation || "Review the registered evidence and limitations before model work begins.") : "Register the first immutable ASP sports dataset manifest and begin the MLB plate-appearance baseline experiment."}
          </p>
          <div className="mt-5 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-xs leading-5 text-slate-400">
            {activeDataset ? `Registration ${activeDataset.registrationId} is ${activeDataset.validationStatus}. Feature authority is ${activeDataset.featureAudit?.status || "not audited"}. No model experiment has been run.` : datasetEvidence.status === "error" ? "The governed dataset registry could not be read. No registration is inferred from browser-local project snapshots." : "No governed sports dataset is registered in this workspace."}
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6" aria-labelledby="recent-activity-heading">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">Target-local activity</div>
            <h2 id="recent-activity-heading" className="mt-1 text-xl font-semibold text-slate-950">Recent activity</h2>
          </div>
          {(recentProjects.length > 0 || governedProject) && (
            <Link to="/projects/open" className="text-sm font-semibold text-blue-700 hover:text-blue-900">Open sports projects</Link>
          )}
        </div>
        {recentProjects.length || governedProject ? (
          <div className="mt-4 divide-y divide-slate-100">
            {governedProject ? <article className="flex flex-col gap-3 py-4 first:pt-0 sm:flex-row sm:items-center sm:justify-between"><div className="flex min-w-0 items-center gap-3"><div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${projectBlocked ? "bg-amber-900 text-amber-100" : "bg-emerald-900 text-cyan-200"}`}><ShieldCheck size={18} aria-hidden="true" /></div><div className="min-w-0"><h3 className="break-words text-sm font-semibold text-slate-950">{governedProject.name}</h3><p className="mt-0.5 text-xs text-slate-500">MLB Forecasting · {governedProject.developmentPeriod || "Development period not recorded"}</p></div></div><span className={`inline-flex w-fit max-w-full whitespace-normal break-words rounded-full px-2.5 py-1 text-xs font-semibold ${projectBlocked ? "bg-amber-100 text-amber-900" : "bg-emerald-100 text-emerald-800"}`}>{governedProject.status || "REGISTERED"}</span></article> : null}
            {recentProjects.map((project) => (
              <article key={project.projectId} className="flex flex-col gap-3 py-4 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-900 text-cyan-300">
                    <FolderKanban size={18} aria-hidden="true" />
                  </div>
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-slate-950">{project.projectName}</h3>
                    <p className="mt-0.5 text-xs text-slate-500">{project.workflowId === MLB_WORKFLOW.id ? "MLB Forecasting" : "NFL Forecasting"} · Updated {formatProjectDate(project.lastModified)}</p>
                  </div>
                </div>
                <span className="inline-flex w-fit items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">Target-local</span>
              </article>
            ))}
          </div>
        ) : (
          <div className="mt-5 flex flex-col items-center rounded-2xl border border-dashed border-slate-300 bg-slate-50/70 px-5 py-9 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white text-slate-400 shadow-sm ring-1 ring-slate-200">
              <FolderKanban size={22} aria-hidden="true" />
            </div>
            <h3 className="mt-4 text-base font-semibold text-slate-900">No sports projects have been created yet.</h3>
            <p className="mt-2 max-w-lg text-sm leading-6 text-slate-500">Create a project to establish its forecast contract, evidence boundary, experiments, and governed model graph.</p>
            <Link to="/projects/new" className="atlas-primary-button mt-5">Create Sports Project</Link>
          </div>
        )}
      </section>
    </main>
  );
}

function PipelineMap() {
  return (
    <div className="rounded-2xl border border-white/15 bg-slate-900/75 p-4 shadow-2xl backdrop-blur sm:p-5">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 pb-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-300">Governed system graph</div>
          <div className="mt-1 text-sm font-semibold text-white">Evidence to executable forecast</div>
        </div>
        <span className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-300/10 px-2.5 py-1 text-[11px] font-semibold text-cyan-100">
          <span className="h-1.5 w-1.5 rounded-full bg-cyan-300" aria-hidden="true" /> WORKFLOW SHELL
        </span>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        {PIPELINE_NODES.map((node, index) => {
          const Icon = pipelineIcons[index];
          return (
            <div key={node} className={`relative flex items-center gap-3 rounded-xl border px-3 py-2.5 ${index === PIPELINE_NODES.length - 1 ? "border-cyan-300/35 bg-cyan-300/10 sm:col-span-2 xl:col-span-1 2xl:col-span-2" : "border-white/10 bg-white/[0.045]"}`}>
              <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${index === PIPELINE_NODES.length - 1 ? "bg-cyan-300 text-slate-950" : "bg-slate-800 text-cyan-300"}`}>
                <Icon size={16} aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <div className="font-mono text-[11px] font-semibold text-slate-500">{String(index + 1).padStart(2, "0")}</div>
                <div className="truncate text-xs font-semibold text-slate-100 sm:text-sm">{node}</div>
              </div>
              {index < PIPELINE_NODES.length - 1 && <ChevronRight size={14} className="ml-auto shrink-0 text-slate-600" aria-hidden="true" />}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WorkflowFeatureCard({ workflow }: { workflow: typeof MLB_WORKFLOW | typeof NFL_WORKFLOW }) {
  const isMlb = workflow.key === "mlb";
  return (
    <article className="group relative isolate overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 p-5 text-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-xl sm:p-6">
      <div className={`pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full blur-3xl ${isMlb ? "bg-cyan-500/20" : "bg-blue-500/20"}`} aria-hidden="true" />
      <div className="relative">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className={`flex h-11 w-11 items-center justify-center rounded-2xl border ${isMlb ? "border-cyan-300/30 bg-cyan-300/10 text-cyan-300" : "border-blue-300/30 bg-blue-300/10 text-blue-300"}`}>
            {isMlb ? <CircleDot size={22} aria-hidden="true" /> : <Target size={22} aria-hidden="true" />}
          </div>
          <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold tracking-wide ${isMlb ? "border-emerald-300/25 bg-emerald-300/10 text-emerald-200" : "border-blue-300/25 bg-blue-300/10 text-blue-200"}`}>
            {workflow.status}
          </span>
        </div>
        <div className="mt-5 text-xs font-semibold uppercase tracking-[0.15em] text-slate-400">{workflow.sport} · {workflow.league}</div>
        <h3 className="mt-1 text-2xl font-semibold tracking-tight text-white">{workflow.title}</h3>
        <p className="mt-3 max-w-2xl text-[15px] leading-7 text-slate-300">{workflow.description}</p>
        <div className="mt-5 flex flex-wrap gap-2">
          {workflow.outputs.slice(0, 4).map((output) => (
            <span key={output} className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs font-medium text-slate-300">{output}</span>
          ))}
        </div>
        <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-4">
          <span className="font-mono text-xs text-slate-400">12-stage analytical workflow</span>
          <Link to={`/workflows/${workflow.key}`} className={`inline-flex items-center gap-2 text-sm font-semibold ${isMlb ? "text-cyan-300 hover:text-cyan-200" : "text-blue-300 hover:text-blue-200"}`}>
            Open workflow <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
      </div>
    </article>
  );
}

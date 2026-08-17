import { Link, useLocation } from "react-router-dom";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  Database,
  FileCheck2,
  FlaskConical,
  Gauge,
  GitBranch,
  LockKeyhole,
  Network,
  PackageCheck,
  Radio,
  Route,
  ShieldCheck,
  SlidersHorizontal,
  Target,
  UsersRound,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useWorkflowStore } from "../state/useWorkflowStore";
import {
  MLB_WORKFLOW,
  NFL_WORKFLOW,
  type SportsWorkflow,
  type SportsWorkflowKey,
  type SportsWorkflowStep,
} from "./sportsConfig";
import { type ActiveSportsDataset, type SportsProjectStage, useActiveSportsDataset } from "./sportsEvidenceApi";

type ForecastWorkflowProps = {
  workflowKey?: SportsWorkflowKey;
};

const stepIcons: LucideIcon[] = [
  Target,
  Database,
  ShieldCheck,
  UsersRound,
  SlidersHorizontal,
  GitBranch,
  Gauge,
  FlaskConical,
  Clock3,
  CheckCircle2,
  Network,
  PackageCheck,
];

export default function ForecastWorkflow({ workflowKey }: ForecastWorkflowProps) {
  const location = useLocation();
  const resolvedKey = workflowKey ?? (location.pathname.toLowerCase().includes("nfl") ? "nfl" : "mlb");
  const workflow = resolvedKey === "nfl" ? NFL_WORKFLOW : MLB_WORKFLOW;
  const activeProjectId = useWorkflowStore((state) => state.projectId);
  const datasetEvidence = useActiveSportsDataset();
  const workspaceDataset = resolvedKey === "mlb" && datasetEvidence.status === "ready" ? datasetEvidence.data : null;
  const governedProject = workspaceDataset?.project?.projectId === activeProjectId ? workspaceDataset.project : null;
  const boundDataset = governedProject ? workspaceDataset : null;
  const governedStages = governedProject?.stages ?? [];
  const evidencedSteps = governedStages.length
    ? governedStages.filter((stage) => !["pending", "not_configured", "not configured"].includes(stage.status.toLowerCase())).length
    : workflow.steps.filter((step) => step.status !== "not_configured").length;
  const blockedSteps = governedStages.filter((stage) => stage.status.toLowerCase() === "blocked").length;
  const evidenceFor = (step: SportsWorkflowStep) => governedStages.find((stage) => stage.stepId === step.id || stage.number === step.number || stage.title?.toLowerCase() === step.title.toLowerCase());

  return (
    <main className="sports-page-shell w-full space-y-6 pb-10 text-slate-950">
      <section className="relative isolate overflow-hidden rounded-3xl border border-slate-800 bg-slate-950 text-white shadow-[0_24px_70px_-36px_rgba(14,165,233,0.7)]">
        <div
          className="pointer-events-none absolute inset-0 opacity-45"
          aria-hidden="true"
          style={{
            backgroundImage:
              resolvedKey === "mlb"
                ? "radial-gradient(circle at 88% 9%, rgba(34,211,238,.3), transparent 28%), linear-gradient(45deg, transparent 49.7%, rgba(34,211,238,.08) 50%, transparent 50.3%)"
                : "radial-gradient(circle at 88% 9%, rgba(59,130,246,.3), transparent 28%), repeating-linear-gradient(90deg, transparent 0, transparent 9.7%, rgba(96,165,250,.07) 10%)",
          }}
        />
        <div className="relative px-5 py-6 sm:px-7 sm:py-8 lg:px-9">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Link to="/workflows" className="inline-flex items-center gap-2 text-sm font-semibold text-slate-300 transition hover:text-white">
              <ArrowLeft size={16} aria-hidden="true" /> Workflow Library
            </Link>
            <span className={`rounded-full border px-3 py-1.5 text-[11px] font-semibold tracking-[0.09em] ${resolvedKey === "mlb" ? "border-emerald-300/25 bg-emerald-300/10 text-emerald-200" : "border-blue-300/25 bg-blue-300/10 text-blue-200"}`}>
              {workflow.status}
            </span>
          </div>

          <div className="mt-8 grid gap-7 xl:grid-cols-[minmax(0,1fr)_400px] xl:items-end">
            <div>
              <div className={`inline-flex h-12 w-12 items-center justify-center rounded-2xl border ${resolvedKey === "mlb" ? "border-cyan-300/25 bg-cyan-300/10 text-cyan-300" : "border-blue-300/25 bg-blue-300/10 text-blue-300"}`}>
                {resolvedKey === "mlb" ? <CircleDot size={24} aria-hidden="true" /> : <Target size={24} aria-hidden="true" />}
              </div>
              <div className="mt-5 text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{workflow.sport} · {workflow.league}</div>
              <h1 className="mt-2 text-3xl font-semibold tracking-[-0.035em] text-white sm:text-4xl">{workflow.title}</h1>
              <p className="mt-4 max-w-4xl text-[15px] leading-7 text-slate-300 sm:text-base">{workflow.description}</p>
              {resolvedKey === "nfl" && (
                <div className="mt-5 inline-flex items-center gap-2 rounded-xl border border-blue-300/20 bg-blue-300/10 px-3 py-2 text-xs font-medium text-blue-100">
                  <AlertCircle size={15} aria-hidden="true" /> Workflow foundation only. No NFL models or data are configured.
                </div>
              )}
            </div>
            <WorkflowReadiness workflow={workflow} evidencedSteps={evidencedSteps} blockedSteps={blockedSteps} />
          </div>
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label={`${workflow.league} workflow status`}>
        <SummaryCard label="Workflow stages" value="12" helper="Full governed path" icon={Route} />
        <SummaryCard label="Evidence states" value={String(evidencedSteps)} helper={blockedSteps ? `${blockedSteps} blocked stage shown separately` : "No status inferred"} icon={SlidersHorizontal} />
        <SummaryCard
          label="Dataset manifest"
          value={boundDataset?.validationStatus || (workspaceDataset ? "Available" : datasetEvidence.status === "error" ? "Unavailable" : "None")}
          helper={boundDataset
            ? `${boundDataset.datasetId} · project bound`
            : workspaceDataset
              ? `${workspaceDataset.datasetId} · workspace available, not bound to active project`
              : datasetEvidence.status === "error"
                ? "Evidence service could not be read"
                : "No governed registration"}
          icon={Database}
          warning={!boundDataset}
        />
        <SummaryCard label="Approved graph" value="None" helper="No bundle available" icon={Network} warning />
      </section>

      {resolvedKey === "mlb" && datasetEvidence.status === "error" ? <section className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950" role="alert"><strong>Governed sports evidence unavailable.</strong> Workflow stage status is not inferred while the registration service cannot be read.</section> : null}

      <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6" aria-labelledby="workflow-map-heading">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.15em] text-cyan-700">Shared sports modeling workflow</div>
            <h2 id="workflow-map-heading" className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">From objective to ASP export</h2>
          </div>
          <span className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-600">
            <LockKeyhole size={13} aria-hidden="true" /> 12 gated stages
          </span>
        </div>
        <div className="mt-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {workflow.steps.map((step, index) => {
            const Icon = stepIcons[index];
            return (
              <a key={step.id} href={`#${step.id}`} className="group relative flex min-h-20 items-center gap-3 rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-3 transition hover:border-cyan-300 hover:bg-cyan-50/60">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-500 shadow-sm transition group-hover:border-cyan-200 group-hover:text-cyan-700">
                  <Icon size={16} aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <div className="font-mono text-[11px] font-semibold text-slate-400">STEP {String(step.number).padStart(2, "0")}</div>
                  <div className="mt-0.5 text-xs font-semibold leading-5 text-slate-800">{step.title}</div>
                </div>
                <ChevronRight size={14} className="ml-auto shrink-0 text-slate-300" aria-hidden="true" />
              </a>
            );
          })}
        </div>
      </section>

      {resolvedKey === "mlb" ? <BaseOutSimulator blocked={boundDataset?.featureAudit?.status === "BLOCKED"} /> : <DriveSimulator />}

      <section aria-labelledby="workflow-specification-heading">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">Technical specification</div>
            <h2 id="workflow-specification-heading" className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">Workflow stages</h2>
          </div>
          <span className="text-xs font-medium text-slate-500">Stage status comes from governed project evidence</span>
        </div>
        <div className="grid items-start gap-4 xl:grid-cols-2">
          {workflow.steps.map((step, index) => (
            <WorkflowStepCard
              key={step.id}
              step={step}
              workflow={workflow}
              icon={stepIcons[index]}
              evidence={evidenceFor(step)}
              boundDataset={boundDataset}
              workspaceDataset={workspaceDataset}
            />
          ))}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center rounded-2xl border border-amber-200 bg-amber-50/70 p-5 sm:p-6">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-800">
            <AlertCircle size={18} aria-hidden="true" />
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-amber-800">Export gate</div>
            <h2 className="mt-1 text-lg font-semibold text-slate-950">No model graph has been approved for export.</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">SPORTS_MODEL_BUNDLE_V1 becomes available only after evidence, temporal validation, calibration, and graph decisions are complete.</p>
          </div>
        </div>
        <button type="button" disabled className="inline-flex min-h-10 cursor-not-allowed items-center justify-center gap-2 rounded-xl bg-slate-200 px-4 py-2 text-sm font-semibold text-slate-500">
          <LockKeyhole size={15} aria-hidden="true" /> Export {workflow.league} Bundle
        </button>
      </section>
    </main>
  );
}

function WorkflowReadiness({ workflow, evidencedSteps, blockedSteps }: { workflow: SportsWorkflow; evidencedSteps: number; blockedSteps: number }) {
  return (
    <div className="rounded-2xl border border-white/15 bg-white/[0.055] p-4 backdrop-blur sm:p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Workflow readiness</div>
          <div className="mt-1 text-lg font-semibold text-white">{evidencedSteps ? "Evidence registered" : "Not configured"}</div>
        </div>
        <span className="font-mono text-3xl font-semibold tabular-nums text-cyan-300">{evidencedSteps}<span className="text-base text-slate-500">/12</span></span>
      </div>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10" aria-label={`${evidencedSteps} of 12 stages have registered evidence; ${blockedSteps} blocked`}>
        <div className="h-full rounded-full bg-cyan-300" style={{ width: `${(evidencedSteps / 12) * 100}%` }} />
      </div>
      {blockedSteps ? <p className="mt-3 text-xs font-semibold text-amber-200">{blockedSteps} stage is blocked and is not counted as complete.</p> : null}
      <div className="mt-5 border-t border-white/10 pt-4">
        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Intended outputs</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {workflow.outputs.slice(0, 4).map((output) => (
            <span key={output} className="rounded-lg border border-white/10 bg-slate-950/40 px-2.5 py-1.5 text-xs font-medium text-slate-300">{output}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ label, value, helper, icon: Icon, warning = false }: { label: string; value: string; helper: string; icon: LucideIcon; warning?: boolean }) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${warning ? "bg-amber-50 text-amber-700 ring-1 ring-amber-100" : "bg-blue-50 text-blue-700 ring-1 ring-blue-100"}`}>
          <Icon size={17} aria-hidden="true" />
        </div>
        <div className={`font-mono text-2xl font-semibold tabular-nums ${warning ? "text-amber-800" : "text-slate-950"}`}>{value}</div>
      </div>
      <h2 className="mt-4 text-sm font-semibold text-slate-900">{label}</h2>
      <p className="mt-1 text-xs leading-5 text-slate-500">{helper}</p>
    </article>
  );
}

function BaseOutSimulator({ blocked }: { blocked: boolean }) {
  const states = [
    { label: "Empty", occupied: [] as number[] },
    { label: "1st", occupied: [1] },
    { label: "2nd", occupied: [2] },
    { label: "3rd", occupied: [3] },
    { label: "1st + 2nd", occupied: [1, 2] },
    { label: "1st + 3rd", occupied: [1, 3] },
    { label: "2nd + 3rd", occupied: [2, 3] },
    { label: "Loaded", occupied: [1, 2, 3] },
  ];
  const pipeline = ["Hitter & pitcher state", "Plate-appearance outcome", "Base-out transition", "Usage & substitutions", "Score distribution"];

  return (
    <section className="relative overflow-hidden rounded-3xl border border-cyan-200 bg-gradient-to-br from-slate-950 via-slate-900 to-cyan-950 p-5 text-white shadow-sm sm:p-7" aria-labelledby="base-out-heading">
      <div className="pointer-events-none absolute -right-28 -top-28 h-72 w-72 rounded-full border border-cyan-300/10" aria-hidden="true" />
      <div className="relative grid gap-7 xl:grid-cols-[280px_minmax(0,1fr)]">
        <div>
          <div className="flex flex-wrap items-center gap-2"><div className="text-xs font-semibold uppercase tracking-[0.15em] text-cyan-300">Future MLB simulation blueprint</div><span className="rounded-full border border-amber-300/30 bg-amber-300/10 px-2.5 py-1 text-[11px] font-semibold uppercase text-amber-200">{blocked ? "Blocked upstream · not configured" : "Not configured"}</span></div>
          <h2 id="base-out-heading" className="mt-2 text-2xl font-semibold tracking-tight text-white">24-state base-out design</h2>
          <p className="mt-3 text-sm leading-6 text-slate-300">Eight runner configurations combine with zero, one, or two outs in the intended design. No transition engine, probabilities, or simulation results exist in this workspace.</p>
          <div className="mt-5 flex justify-center rounded-2xl border border-white/10 bg-white/[0.045] p-5">
            <LargeDiamond />
          </div>
        </div>

        <div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Runner configurations</div>
            <span className="font-mono text-xs text-cyan-300">8 × 3 OUT COUNTS = 24 STATES</span>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {states.map((state) => (
              <div key={state.label} className="rounded-xl border border-white/10 bg-white/[0.045] px-3 py-3">
                <div className="flex items-center justify-between gap-3">
                  <BaseOccupancy occupied={state.occupied} />
                  <span className="text-xs font-semibold text-slate-200">{state.label}</span>
                </div>
                <div className="mt-3 flex gap-1.5" aria-label="Zero, one, and two out variants">
                  {[0, 1, 2].map((outs) => <span key={outs} className="rounded-md bg-slate-800 px-2 py-1 font-mono text-[11px] text-slate-400">{outs} OUT</span>)}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-5">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Planned simulator pipeline</div>
            <div className="mt-3 grid gap-2 lg:grid-cols-5">
              {pipeline.map((label, index) => (
                <div key={label} className={`relative rounded-xl border px-3 py-3 text-xs font-semibold leading-5 ${index === pipeline.length - 1 ? "border-cyan-300/30 bg-cyan-300/10 text-cyan-100" : "border-white/10 bg-slate-950/35 text-slate-300"}`}>
                  <span className="block font-mono text-[11px] text-slate-500">{String(index + 1).padStart(2, "0")}</span>
                  {label}
                  {index < pipeline.length - 1 && <ArrowRight size={14} className="absolute -right-2.5 top-1/2 z-10 hidden -translate-y-1/2 text-cyan-500 lg:block" aria-hidden="true" />}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function LargeDiamond() {
  return (
    <div className="relative h-40 w-40" aria-label="Baseball diamond with first, second, and third base occupied">
      <div className="absolute inset-5 rotate-45 rounded-[18px] border border-cyan-300/45 bg-cyan-300/[0.055] shadow-[inset_0_0_32px_rgba(34,211,238,0.08)]" />
      <div className="absolute left-1/2 top-1 -translate-x-1/2 rotate-45 border border-cyan-200 bg-cyan-300 p-2 shadow-lg shadow-cyan-950" />
      <div className="absolute right-1 top-1/2 -translate-y-1/2 rotate-45 border border-cyan-200 bg-cyan-300 p-2 shadow-lg shadow-cyan-950" />
      <div className="absolute bottom-1 left-1/2 -translate-x-1/2 rotate-45 border border-white/40 bg-white/15 p-2" />
      <div className="absolute left-1 top-1/2 -translate-y-1/2 rotate-45 border border-cyan-200 bg-cyan-300 p-2 shadow-lg shadow-cyan-950" />
      <div className="absolute left-1/2 top-1/2 flex h-10 w-10 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-amber-200/30 bg-amber-300/10 text-[11px] font-bold text-amber-200">STATE</div>
    </div>
  );
}

function BaseOccupancy({ occupied }: { occupied: number[] }) {
  const baseClass = (base: number) => occupied.includes(base) ? "border-cyan-200 bg-cyan-300" : "border-slate-600 bg-slate-800";
  return (
    <div className="relative h-8 w-10" aria-hidden="true">
      <span className={`absolute right-0 top-3 h-2.5 w-2.5 rotate-45 border ${baseClass(1)}`} />
      <span className={`absolute left-1/2 top-0 h-2.5 w-2.5 -translate-x-1/2 rotate-45 border ${baseClass(2)}`} />
      <span className={`absolute left-0 top-3 h-2.5 w-2.5 rotate-45 border ${baseClass(3)}`} />
    </div>
  );
}

function DriveSimulator() {
  const outcomes = ["Touchdown", "Field goal", "Punt", "Turnover", "Turnover on downs", "Safety", "End of period"];
  const pipeline = ["QB, player & unit state", "Participation & coaching", "Drive / play outcomes", "Clock & field position", "Joint score distribution"];
  return (
    <section className="relative overflow-hidden rounded-3xl border border-blue-200 bg-gradient-to-br from-slate-950 via-slate-900 to-blue-950 p-5 text-white shadow-sm sm:p-7" aria-labelledby="drive-engine-heading">
      <div className="relative grid gap-7 xl:grid-cols-[minmax(0,1fr)_330px]">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.15em] text-blue-300">NFL simulation foundation</div>
          <h2 id="drive-engine-heading" className="mt-2 text-2xl font-semibold tracking-tight text-white">Drive-level game engine</h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">Possession outcomes interact with field position, clock, score state, participation scenarios, and coaching policy to form a future joint score distribution.</p>
          <div className="mt-5 overflow-hidden rounded-2xl border border-white/10 bg-slate-950/35 p-4">
            <div
              className="relative grid min-h-32 grid-cols-5 gap-px overflow-hidden rounded-xl border border-blue-300/20 bg-blue-950/40"
              style={{ backgroundImage: "repeating-linear-gradient(90deg, transparent 0, transparent calc(10% - 1px), rgba(147,197,253,.13) 10%)" }}
            >
              {["OWN 20", "MIDFIELD", "RED ZONE", "GOAL", "NEXT DRIVE"].map((zone, index) => (
                <div key={zone} className="relative flex items-end justify-center px-1 pb-3 text-center font-mono text-[11px] font-semibold text-blue-200/60">
                  {zone}
                  {index === 1 && <span className="absolute left-1/2 top-8 h-5 w-8 -translate-x-1/2 rounded-[50%] border border-amber-200/60 bg-amber-300/15" aria-hidden="true" />}
                </div>
              ))}
              <div className="absolute left-[12%] right-[12%] top-1/2 h-px bg-blue-300/25" aria-hidden="true" />
              <div className="absolute left-[18%] top-1/2 h-2.5 w-2.5 -translate-y-1/2 animate-pulse rounded-full bg-blue-300 shadow-[0_0_16px_rgba(147,197,253,.8)]" aria-hidden="true" />
            </div>
          </div>
          <div className="mt-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {pipeline.map((label, index) => (
              <div key={label} className={`relative rounded-xl border px-3 py-3 text-xs font-semibold leading-5 ${index === pipeline.length - 1 ? "border-blue-300/30 bg-blue-300/10 text-blue-100" : "border-white/10 bg-white/[0.04] text-slate-300"}`}>
                <span className="block font-mono text-[11px] text-slate-500">{String(index + 1).padStart(2, "0")}</span>
                {label}
                {index < pipeline.length - 1 && <ArrowRight size={14} className="absolute -right-2.5 top-1/2 z-10 hidden -translate-y-1/2 text-blue-400 lg:block" aria-hidden="true" />}
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/[0.045] p-5">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400"><Radio size={14} aria-hidden="true" /> Drive outcomes</div>
          <div className="mt-4 space-y-2">
            {outcomes.map((outcome, index) => (
              <div key={outcome} className="flex items-center gap-3 rounded-xl border border-white/10 bg-slate-950/30 px-3 py-2.5">
                <span className={`h-2 w-2 rounded-full ${index < 2 ? "bg-blue-300" : "bg-slate-600"}`} aria-hidden="true" />
                <span className="text-xs font-medium text-slate-300">{outcome}</span>
                <span className="ml-auto font-mono text-[11px] text-slate-600">PENDING</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function WorkflowStepCard({
  step,
  workflow,
  icon: Icon,
  evidence,
  boundDataset,
  workspaceDataset,
}: {
  step: SportsWorkflowStep;
  workflow: SportsWorkflow;
  icon: LucideIcon;
  evidence?: SportsProjectStage;
  boundDataset: ActiveSportsDataset | null;
  workspaceDataset: ActiveSportsDataset | null;
}) {
  const isEvidenceStep = step.number === 2;
  const isGraphStep = step.number === 11;
  const isExportStep = step.number === 12;
  const evidenceStatus = evidence?.status || "Not Configured";
  const configured = !["pending", "not_configured", "not configured"].includes(evidenceStatus.toLowerCase());
  const complete = ["complete", "completed"].includes(evidenceStatus.toLowerCase());
  const blocked = evidenceStatus.toLowerCase() === "blocked";
  return (
    <article id={step.id} className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="flex items-start gap-4">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-slate-200 bg-slate-50 text-slate-600">
          <Icon size={19} aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="font-mono text-[11px] font-semibold tracking-[0.1em] text-slate-400">STEP {String(step.number).padStart(2, "0")}</div>
            <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.06em] ${complete ? "border-emerald-200 bg-emerald-50 text-emerald-800" : blocked ? "border-amber-300 bg-amber-50 text-amber-900" : configured ? "border-cyan-200 bg-cyan-50 text-cyan-800" : "border-slate-200 bg-slate-100 text-slate-600"}`}>{evidenceStatus.replaceAll("_", " ")}</span>
          </div>
          <h3 className="mt-1 text-lg font-semibold text-slate-950">{step.title}</h3>
          <p className="mt-2 text-[15px] leading-6 text-slate-600">{step.purpose}</p>
        </div>
      </div>

      {evidence?.evidence?.length ? <div className={`mt-5 rounded-xl border px-4 py-3 ${blocked ? "border-amber-200 bg-amber-50" : "border-emerald-200 bg-emerald-50"}`}><div className={`text-xs font-semibold uppercase tracking-wide ${blocked ? "text-amber-900" : "text-emerald-800"}`}>{blocked ? "Registered blocker evidence" : "Registered evidence"}</div><ul className={`mt-2 grid gap-1 text-xs leading-5 ${blocked ? "text-amber-950" : "text-emerald-950"}`}>{evidence.evidence.map((item) => <li key={item} className="flex gap-2">{blocked ? <AlertCircle size={14} className="mt-0.5 shrink-0" /> : <CheckCircle2 size={14} className="mt-0.5 shrink-0" />}{item}</li>)}</ul></div> : null}

      {isEvidenceStep && !workspaceDataset && (
        <div className="mt-5 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-950">
          <Database size={17} className="mt-0.5 shrink-0" aria-hidden="true" />
          <div>
            <div className="text-sm font-semibold">No ASP dataset manifest registered.</div>
            <div className="mt-0.5 text-xs leading-5 text-amber-800">No governed SPORTS_DATASET_MANIFEST_V1 registration exists in this workspace.</div>
          </div>
        </div>
      )}

      {isEvidenceStep && workspaceDataset && !boundDataset && (
        <div className="mt-5 flex items-start gap-3 rounded-xl border border-cyan-200 bg-cyan-50 px-4 py-3 text-cyan-950">
          <Database size={17} className="mt-0.5 shrink-0" aria-hidden="true" />
          <div>
            <div className="text-sm font-semibold">Workspace dataset available · not bound to active project.</div>
            <div className="mt-0.5 break-all text-xs leading-5 text-cyan-800">{workspaceDataset.datasetId} is registered, but governed stage evidence remains project-scoped.</div>
          </div>
        </div>
      )}

      {isEvidenceStep && boundDataset && (
        <div className="mt-5 flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-emerald-950">
          <Database size={17} className="mt-0.5 shrink-0" aria-hidden="true" />
          <div><div className="text-sm font-semibold">Project-bound immutable dataset registration {boundDataset.validationStatus}</div><div className="mt-0.5 break-all text-xs leading-5 text-emerald-800">{boundDataset.datasetId} · registration {boundDataset.registrationId}</div></div>
        </div>
      )}

      {isGraphStep && (
        <div className="mt-5 flex items-start gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-blue-950">
          <Network size={17} className="mt-0.5 shrink-0" aria-hidden="true" />
          <div>
            <div className="text-sm font-semibold">No model graph</div>
            <div className="mt-0.5 text-xs leading-5 text-blue-800">Lifecycle decisions remain empty until candidate and reliability evidence exists.</div>
          </div>
        </div>
      )}

      {isExportStep && (
        <div className="mt-5 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-950">
          <LockKeyhole size={17} className="mt-0.5 shrink-0" aria-hidden="true" />
          <div>
            <div className="text-sm font-semibold">No model graph has been approved for export.</div>
            <div className="mt-0.5 text-xs leading-5 text-amber-800">The future {workflow.league} artifact follows SPORTS_MODEL_BUNDLE_V1.</div>
          </div>
        </div>
      )}

      <div className="mt-5">
        <div className="text-xs font-semibold uppercase tracking-[0.13em] text-slate-500">Scope</div>
        <div className="mt-2 flex flex-wrap gap-2">
          {step.sections.map((section) => (
            <span key={section} className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs font-medium leading-5 text-slate-700">{section}</span>
          ))}
        </div>
      </div>

      <div className="mt-5 grid gap-4 border-t border-slate-100 pt-4 sm:grid-cols-2">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500"><LockKeyhole size={13} aria-hidden="true" /> Prerequisites</div>
          <p className="mt-2 text-xs leading-5 text-slate-600">{step.prerequisites.length ? step.prerequisites.join(" · ") : "None — this is the workflow entry point."}</p>
        </div>
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500"><FileCheck2 size={13} aria-hidden="true" /> Expected outputs</div>
          <p className="mt-2 text-xs leading-5 text-slate-600">{step.outputs.join(" · ")}</p>
        </div>
      </div>
    </article>
  );
}

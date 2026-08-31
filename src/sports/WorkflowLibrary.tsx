import { Link } from "react-router-dom";
import {
  ArrowRight,
  Braces,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  Database,
  FlaskConical,
  Layers3,
  LockKeyhole,
  Network,
  ShieldCheck,
  Target,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { PLANNED_SPORTS, SPORTS_WORKFLOWS } from "./sportsConfig";

const workflowSignals: Record<"mlb" | "nfl", { icon: LucideIcon; eyebrow: string; accent: string; iconClass: string }> = {
  mlb: {
    icon: CircleDot,
    eyebrow: "Primary active system",
    accent: "from-cyan-400/20 via-transparent to-transparent",
    iconClass: "border-cyan-300/25 bg-cyan-300/10 text-cyan-300",
  },
  nfl: {
    icon: Target,
    eyebrow: "Next sport foundation",
    accent: "from-blue-400/20 via-transparent to-transparent",
    iconClass: "border-blue-300/25 bg-blue-300/10 text-blue-300",
  },
};

export default function WorkflowLibrary() {
  return (
    <main className="sports-page-shell w-full space-y-6 pb-8 text-slate-950">
      <section className="relative isolate overflow-hidden rounded-3xl border border-slate-800 bg-slate-950 px-5 py-7 text-white shadow-[0_22px_64px_-34px_rgba(14,165,233,0.65)] sm:px-7 sm:py-9 lg:px-9">
        <div
          className="pointer-events-none absolute inset-0 opacity-50"
          aria-hidden="true"
          style={{
            backgroundImage:
              "radial-gradient(circle at 92% 12%, rgba(34,211,238,.24), transparent 28%), linear-gradient(115deg, transparent 58%, rgba(59,130,246,.11) 58.2%, transparent 58.5%), linear-gradient(rgba(56,189,248,.055) 1px, transparent 1px), linear-gradient(90deg, rgba(56,189,248,.055) 1px, transparent 1px)",
            backgroundSize: "auto, auto, 38px 38px, 38px 38px",
          }}
        />
        <div className="relative grid gap-7 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-end">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-300">Sports workflow library</div>
            <h1 className="mt-3 text-3xl font-semibold tracking-[-0.03em] text-white sm:text-4xl">Build from a sport-native model architecture</h1>
            <p className="mt-4 max-w-3xl text-[15px] leading-7 text-slate-300 sm:text-base">
              Select a governed research path for player and team state, participation, event dynamics, simulation, temporal validation, calibration, and bundle export.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to="/projects/new" className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-cyan-300 px-5 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200">
                Create Sports Project <ArrowRight size={16} aria-hidden="true" />
              </Link>
              <Link to="/dashboard" className="inline-flex min-h-11 items-center justify-center rounded-xl border border-white/20 bg-white/10 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-white/15">
                Return to Studio Home
              </Link>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2 rounded-2xl border border-white/10 bg-white/[0.045] p-3 backdrop-blur">
            <HeroStat value="2" label="Workflow shells" />
            <HeroStat value="12" label="Stages each" />
            <HeroStat value="3" label="Planned leagues" />
          </div>
        </div>
      </section>

      <section aria-labelledby="available-workflows-heading">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.15em] text-cyan-700">Available now</div>
            <h2 id="available-workflows-heading" className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">Forecasting systems</h2>
          </div>
          <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm">
            <ShieldCheck size={14} className="text-emerald-600" aria-hidden="true" /> No data or model results are preloaded
          </span>
        </div>
        <div className="grid gap-5 xl:grid-cols-2">
          {SPORTS_WORKFLOWS.map((workflow) => {
            const signal = workflowSignals[workflow.key];
            const Icon = signal.icon;
            return (
              <article key={workflow.id} className="group relative isolate overflow-hidden rounded-3xl border border-slate-800 bg-slate-950 p-5 text-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-xl sm:p-7">
                <div className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${signal.accent}`} aria-hidden="true" />
                <div className="relative flex h-full flex-col">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className={`flex h-12 w-12 items-center justify-center rounded-2xl border ${signal.iconClass}`}>
                      <Icon size={24} aria-hidden="true" />
                    </div>
                    <span className={`rounded-full border px-3 py-1.5 text-[11px] font-semibold tracking-[0.08em] ${workflow.key === "mlb" ? "border-emerald-300/25 bg-emerald-300/10 text-emerald-200" : "border-blue-300/25 bg-blue-300/10 text-blue-200"}`}>
                      {workflow.status}
                    </span>
                  </div>

                  <div className="mt-6 text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{signal.eyebrow} · {workflow.league}</div>
                  <h3 className="mt-2 text-3xl font-semibold tracking-tight text-white">{workflow.title}</h3>
                  <p className="mt-4 text-[15px] leading-7 text-slate-300">{workflow.description}</p>

                  <div className="mt-6 grid gap-5 border-t border-white/10 pt-5 sm:grid-cols-[minmax(0,1fr)_210px]">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.13em] text-slate-500">Primary outputs</div>
                      <ul className="mt-3 grid gap-x-4 gap-y-2 sm:grid-cols-2" aria-label={`${workflow.title} outputs`}>
                        {workflow.outputs.map((output) => (
                          <li key={output} className="flex items-start gap-2 text-xs leading-5 text-slate-300">
                            <Check size={14} className="mt-0.5 shrink-0 text-cyan-300" aria-hidden="true" /> {output}
                          </li>
                        ))}
                      </ul>
                    </div>
                    <MiniArchitecture sport={workflow.key} />
                  </div>

                  <div className="mt-7 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-5">
                    <div className="flex items-center gap-3 text-xs text-slate-400">
                      <span className="font-mono tabular-nums">12 stages</span>
                      <span className="h-1 w-1 rounded-full bg-slate-600" aria-hidden="true" />
                      <span>Not configured</span>
                    </div>
                    <Link to={workflow.key === "mlb" ? "/workflows/mlb-spec" : "/workflows/nfl"} className={`inline-flex min-h-10 items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition ${workflow.key === "mlb" ? "bg-cyan-300 text-slate-950 hover:bg-cyan-200" : "border border-blue-300/25 bg-blue-300/10 text-blue-200 hover:bg-blue-300/15"}`}>
                      Explore {workflow.league} workflow <ArrowRight size={16} aria-hidden="true" />
                    </Link>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7" aria-labelledby="workflow-standard-heading">
        <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)] xl:items-center">
          <div>
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-700 ring-1 ring-blue-100">
              <Network size={19} aria-hidden="true" />
            </div>
            <h2 id="workflow-standard-heading" className="mt-4 text-xl font-semibold text-slate-950">One research standard, sport-specific mechanics</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">Both workflows preserve the same evidence and governance spine while exposing the event model and simulator native to each sport.</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <StandardNode icon={Database} title="Evidence" detail="Immutable manifest" />
            <StandardNode icon={Layers3} title="State" detail="Player, team, usage" />
            <StandardNode icon={FlaskConical} title="Experiment" detail="Temporal candidates" />
            <StandardNode icon={ShieldCheck} title="Decision" detail="Calibrated graph" />
          </div>
        </div>
      </section>

      <section aria-labelledby="planned-workflows-heading">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">Product roadmap</div>
            <h2 id="planned-workflows-heading" className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">Planned sport templates</h2>
          </div>
          <span className="inline-flex items-center gap-2 text-xs font-medium text-slate-500"><Clock3 size={14} aria-hidden="true" /> Roadmap only</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
          {PLANNED_SPORTS.map((sport) => (
            <article key={sport.name} aria-disabled="true" className="relative min-h-48 overflow-hidden rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-5 text-slate-700">
              <div className="pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full border border-slate-200" aria-hidden="true" />
              <div className="flex items-start justify-between gap-3">
                <div className="flex h-9 min-w-9 items-center justify-center rounded-xl border border-slate-200 bg-white px-2 font-mono text-[11px] font-bold tracking-wider text-slate-500 shadow-sm">{sport.icon}</div>
                <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-semibold tracking-[0.08em] text-slate-500">PLANNED</span>
              </div>
              <h3 className="mt-7 text-lg font-semibold text-slate-800">{sport.name}</h3>
              <p className="mt-1 text-sm text-slate-500">{sport.league}</p>
              <div className="mt-5 inline-flex items-center gap-1.5 text-xs font-medium text-slate-400"><LockKeyhole size={13} aria-hidden="true" /> Template not yet available</div>
            </article>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-4 rounded-2xl border border-cyan-200 bg-cyan-50/70 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.15em] text-cyan-800">Start with the forecast contract</div>
          <h2 className="mt-1 text-xl font-semibold text-slate-950">Ready to establish a sports research project?</h2>
          <p className="mt-1 text-sm leading-6 text-slate-600">Choose the sport, lifecycle, evidence population, and forecast targets before any experiment begins.</p>
        </div>
        <Link to="/projects/new" className="atlas-primary-button shrink-0">Create Sports Project <ChevronRight size={16} aria-hidden="true" /></Link>
      </section>
    </main>
  );
}

function HeroStat({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-slate-950/40 px-3 py-3 text-center">
      <div className="font-mono text-2xl font-semibold tabular-nums text-cyan-300">{value}</div>
      <div className="mt-1 text-[11px] font-medium leading-4 text-slate-400">{label}</div>
    </div>
  );
}

function MiniArchitecture({ sport }: { sport: "mlb" | "nfl" }) {
  const labels = sport === "mlb" ? ["Player state", "PA outcomes", "Base-out sim"] : ["Unit state", "Drive outcomes", "Game sim"];
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.04] p-3">
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
        <Braces size={13} aria-hidden="true" /> System path
      </div>
      <div className="mt-3 space-y-2">
        {labels.map((label, index) => (
          <div key={label} className="flex items-center gap-2 text-xs text-slate-300">
            <span className={`h-2 w-2 rounded-full ${index === labels.length - 1 ? "bg-cyan-300" : "bg-slate-600"}`} aria-hidden="true" />
            <span>{label}</span>
            {index < labels.length - 1 && <ChevronRight size={12} className="ml-auto text-slate-600" aria-hidden="true" />}
          </div>
        ))}
      </div>
    </div>
  );
}

function StandardNode({ icon: Icon, title, detail }: { icon: LucideIcon; title: string; detail: string }) {
  return (
    <div className="relative rounded-2xl border border-slate-200 bg-slate-50/80 p-4">
      <Icon size={18} className="text-blue-700" aria-hidden="true" />
      <h3 className="mt-3 text-sm font-semibold text-slate-900">{title}</h3>
      <p className="mt-1 text-xs leading-5 text-slate-500">{detail}</p>
      <ChevronRight size={14} className="absolute right-3 top-3 text-slate-300" aria-hidden="true" />
    </div>
  );
}

// Interactive MLB PA Modeling Cockpit (Phase 6A) — the 15-step scientist workbench shell.
import { useState } from "react";
import {
  Target, Database, ScanSearch, TriangleAlert, CircleSlash, Wand2, Boxes, CalendarClock,
  FlaskConical, SlidersHorizontal, BarChart3, Gauge, Orbit, Trophy, ClipboardList, Cpu,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEndpoint, useCockpitStore, type Objective } from "./cockpitApi";
import {
  ObjectiveStep, DataPopulationStep, ProfileStep, OutliersStep, MissingStep,
  FeatureEngineeringStep, SegmentationStep, TemporalSplitStep,
} from "./cockpitSteps1";
import {
  ModelLabStep, TuningStep, EvaluationStep, CalibrationStep, SimulationStep,
  ChampionChallengerStep, RegistryStep,
} from "./cockpitSteps2";

type Step = { id: string; n: string; label: string; icon: LucideIcon; group: string; render: () => JSX.Element };

const STEPS: Step[] = [
  { id: "objective", n: "01", label: "Objective", icon: Target, group: "Frame", render: () => <ObjectiveStep /> },
  { id: "population", n: "02", label: "Data & Population", icon: Database, group: "Frame", render: () => <DataPopulationStep /> },
  { id: "profile", n: "03", label: "Data Profile", icon: ScanSearch, group: "Understand", render: () => <ProfileStep /> },
  { id: "outliers", n: "04", label: "Outliers", icon: TriangleAlert, group: "Prepare", render: () => <OutliersStep /> },
  { id: "missing", n: "05", label: "Missing Values", icon: CircleSlash, group: "Prepare", render: () => <MissingStep /> },
  { id: "features", n: "06", label: "Feature Engineering", icon: Wand2, group: "Prepare", render: () => <FeatureEngineeringStep /> },
  { id: "segmentation", n: "07", label: "Player Segmentation", icon: Boxes, group: "Prepare", render: () => <SegmentationStep /> },
  { id: "split", n: "08", label: "Temporal Split", icon: CalendarClock, group: "Prepare", render: () => <TemporalSplitStep /> },
  { id: "modellab", n: "09", label: "Model Laboratory", icon: FlaskConical, group: "Model", render: () => <ModelLabStep /> },
  { id: "tuning", n: "10", label: "Hyperparameter Tuning", icon: SlidersHorizontal, group: "Model", render: () => <TuningStep /> },
  { id: "evaluation", n: "11", label: "Evaluation", icon: BarChart3, group: "Assess", render: () => <EvaluationStep /> },
  { id: "calibration", n: "12", label: "Calibration", icon: Gauge, group: "Assess", render: () => <CalibrationStep /> },
  { id: "simulation", n: "13", label: "Simulation Impact", icon: Orbit, group: "Assess", render: () => <SimulationStep /> },
  { id: "champion", n: "14", label: "Champion / Challenger", icon: Trophy, group: "Decide", render: () => <ChampionChallengerStep /> },
  { id: "registry", n: "15", label: "Registry & Evidence", icon: ClipboardList, group: "Decide", render: () => <RegistryStep /> },
];

export default function PaModelingCockpit() {
  const [active, setActive] = useState("objective");
  const obj = useEndpoint<Objective>("/cockpit/objective");
  const { config, savedSteps, lastResult } = useCockpitStore();
  const step = STEPS.find((s) => s.id === active)!;
  const groups = [...new Set(STEPS.map((s) => s.group))];

  return (
    <div className="min-w-0 space-y-4 pb-10">
      {/* Persistent context header */}
      <header className="relative isolate overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white shadow-xl">
        <div className="pointer-events-none absolute inset-0 opacity-70" aria-hidden="true"
          style={{ backgroundImage: "radial-gradient(circle at 85% 12%, rgba(34,211,238,.20), transparent 26%), linear-gradient(rgba(148,163,184,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,.05) 1px, transparent 1px)", backgroundSize: "auto, 32px 32px, 32px 32px" }} />
        <div className="relative flex flex-col gap-4 p-5 sm:p-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <span className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-cyan-400/15 text-cyan-200 ring-1 ring-cyan-300/20"><Cpu size={22} /></span>
              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200">Interactive modeling cockpit</span>
            </div>
            <h1 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">MLB Plate-Appearance Model</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">A data scientist's workbench over the governed D3 feature view — profile predictors, control outlier &amp; missing policy, engineer features, tune and compare model families, and prove whether a better plate-appearance metric actually improves the whole-game simulator.</p>
          </div>
          <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-white/10 bg-white/10 text-xs sm:grid-cols-3">
            {[
              ["Dataset", "MLB FD1 · governed"],
              ["Target", "8-class PA outcome"],
              ["Champion", obj.data ? obj.data.champion.modelId : "…"],
              ["Feature set", `${config.features.length} selected`],
              ["Active experiment", lastResult ? lastResult.family : "none"],
              ["Temporal policy", "2023→2024→2025"],
            ].map(([k, v]) => (
              <div key={k} className="min-w-0 bg-slate-950/70 px-3.5 py-2.5 backdrop-blur-sm"><dt className="text-[11px] text-slate-400">{k}</dt><dd className="mt-0.5 break-words font-semibold text-white">{v}</dd></div>
            ))}
          </dl>
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        {/* Step navigation */}
        <nav className="lg:sticky lg:top-4 lg:self-start">
          <div className="space-y-3 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
            {groups.map((g) => (
              <div key={g}>
                <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">{g}</div>
                <div className="space-y-0.5">
                  {STEPS.filter((s) => s.group === g).map((s) => {
                    const on = s.id === active;
                    const done = savedSteps[s.id] || (s.id === "modellab" && lastResult);
                    return (
                      <button key={s.id} onClick={() => setActive(s.id)}
                        className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-colors ${on ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                        <span className={`text-[10px] font-semibold tabular-nums ${on ? "text-cyan-300" : "text-slate-400"}`}>{s.n}</span>
                        <s.icon size={15} className={on ? "text-cyan-300" : "text-slate-400"} />
                        <span className="min-w-0 flex-1 truncate font-medium">{s.label}</span>
                        {done ? <span className={`h-1.5 w-1.5 rounded-full ${on ? "bg-cyan-300" : "bg-emerald-500"}`} /> : null}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </nav>

        {/* Active step */}
        <div className="min-w-0">
          <div className="mb-3 flex items-center gap-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900 text-cyan-200"><step.icon size={18} /></span>
            <div><div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-700">Step {step.n} · {step.group}</div>
              <h2 className="text-xl font-semibold tracking-tight text-slate-950">{step.label}</h2></div>
          </div>
          {step.render()}
        </div>
      </div>
    </div>
  );
}

import { useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Check, CircleAlert, Sparkles } from "lucide-react";
import { upsertProjectFromState } from "../lib/localProjects";
import { useWorkflowStore } from "../state/useWorkflowStore";
import {
  FORECAST_LIFECYCLES,
  LEAGUES_BY_SPORT,
  MLB_WORKFLOW,
  NFL_WORKFLOW,
  TARGETS_BY_WORKFLOW,
  saveSportsProjectMetadata,
} from "./sportsConfig";

const SPORT_OPTIONS = Object.keys(LEAGUES_BY_SPORT);

function workflowForSport(sport: string) {
  if (sport === "Baseball") return MLB_WORKFLOW;
  if (sport === "Professional Football") return NFL_WORKFLOW;
  return null;
}

export default function NewSportsProject() {
  const navigate = useNavigate();
  const startProjectFromWorkflow = useWorkflowStore((state) => state.startProjectFromWorkflow);
  const [projectName, setProjectName] = useState("");
  const [sport, setSport] = useState("Baseball");
  const [league, setLeague] = useState("MLB");
  const [period, setPeriod] = useState("");
  const [lifecycle, setLifecycle] = useState<(typeof FORECAST_LIFECYCLES)[number]>("Pregame — Final");
  const [primaryTarget, setPrimaryTarget] = useState("Joint Score Distribution");
  const [secondaryTargets, setSecondaryTargets] = useState<string[]>(["Home Win Probability"]);
  const [researchPurpose, setResearchPurpose] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");

  const workflow = workflowForSport(sport);
  const targets = workflow ? TARGETS_BY_WORKFLOW[workflow.id] : [];
  const canCreate = Boolean(projectName.trim() && period.trim() && researchPurpose.trim() && workflow);

  const workflowLabel = useMemo(() => {
    if (workflow) return workflow.title;
    return `${sport} — Planned workflow`;
  }, [sport, workflow]);

  function selectSport(nextSport: string) {
    const nextWorkflow = workflowForSport(nextSport);
    setSport(nextSport);
    setLeague(LEAGUES_BY_SPORT[nextSport][0]);
    setPrimaryTarget(nextWorkflow ? TARGETS_BY_WORKFLOW[nextWorkflow.id][0] : "");
    setSecondaryTargets(nextWorkflow ? [TARGETS_BY_WORKFLOW[nextWorkflow.id][1]] : []);
  }

  function toggleSecondary(target: string) {
    setSecondaryTargets((current) => current.includes(target) ? current.filter((item) => item !== target) : [...current, target]);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!workflow) {
      setError("This sport is on the product roadmap. Choose MLB or NFL to create a Phase 1 project.");
      return;
    }
    if (!canCreate) {
      setError("Complete the required project identity, development period, and research purpose fields.");
      return;
    }

    startProjectFromWorkflow({
      modelId: `${workflow.league.toLowerCase()}-${Date.now().toString(36)}`,
      projectName: projectName.trim(),
      projectType: "custom-workflow",
      workflowId: workflow.id as "mlb-forecasting" | "nfl-forecasting",
      workflowSteps: workflow.steps.map((item) => ({
        id: item.id,
        label: item.title,
        shortLabel: item.title.split(" ").slice(0, 2).join(" "),
        route: `/workflows/${workflow.key}#${item.id}`,
        description: item.purpose,
        required: true,
        status: "pending",
      })),
    });

    const state = useWorkflowStore.getState();
    const record = upsertProjectFromState(state);
    if (!record) {
      setError("ASP Model Studio could not create the local project record. No project was registered.");
      return;
    }
    saveSportsProjectMetadata({
      projectId: state.projectId,
      sport,
      league,
      period: period.trim(),
      workflowId: workflow.id as "mlb-forecasting" | "nfl-forecasting",
      lifecycle,
      primaryTarget,
      secondaryTargets,
      researchPurpose: researchPurpose.trim(),
      description: description.trim(),
    });
    // Enter the guided workflow directly at Step 1 — never strand the user on a passive overview.
    navigate(workflow.key === "mlb" ? "/workflows/mlb?stage=1" : "/project-overview");
  }

  return (
    <div className="sports-page-shell">
      <section className="sports-hero-panel overflow-hidden p-6 sm:p-8 lg:p-10">
        <div className="relative z-10 max-w-4xl">
          <div className="sports-eyebrow text-cyan-200"><Sparkles size={16} /> Sports project registration</div>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-white sm:text-4xl lg:text-[42px]">Create a sports forecasting program</h1>
          <p className="mt-4 max-w-3xl text-[15px] leading-7 text-slate-300 sm:text-base">
            Define the sport, forecast clock, research target, and evidence boundary. The studio will configure a governed workflow without inventing data, experiments, or model readiness.
          </p>
        </div>
      </section>

      <form onSubmit={submit} className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,.65fr)]">
        <section className="sports-panel p-5 sm:p-7">
          <div className="flex items-center justify-between gap-4 border-b border-slate-200 pb-5">
            <div>
              <p className="sports-kicker">Project identity</p>
              <h2 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">Forecast contract</h2>
            </div>
            <span className="sports-status sports-status--neutral">NOT CONFIGURED</span>
          </div>

          <div className="mt-6 grid gap-5 md:grid-cols-2">
            <Field label="Project name" required className="md:col-span-2">
              <input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="MLB Gen-2 Free-Data Baseline" />
            </Field>
            <Field label="Sport" required>
              <select value={sport} onChange={(event) => selectSport(event.target.value)}>
                {SPORT_OPTIONS.map((option) => <option key={option}>{option}</option>)}
              </select>
            </Field>
            <Field label="League" required>
              <select value={league} onChange={(event) => setLeague(event.target.value)}>
                {LEAGUES_BY_SPORT[sport].map((option) => <option key={option}>{option}</option>)}
              </select>
            </Field>
            <Field label="Season or development period" required help="Example development window only; no season data is registered by this form.">
              <input value={period} onChange={(event) => setPeriod(event.target.value)} placeholder="2023–2025" />
            </Field>
            <Field label="Workflow template" required>
              <select value={workflowLabel} disabled>
                <option>{workflowLabel}</option>
              </select>
            </Field>
            <Field label="Forecast lifecycle" required>
              <select value={lifecycle} onChange={(event) => setLifecycle(event.target.value as typeof lifecycle)}>
                {FORECAST_LIFECYCLES.map((option) => <option key={option}>{option}</option>)}
              </select>
            </Field>
            <Field label="Primary target" required>
              <select value={primaryTarget} onChange={(event) => setPrimaryTarget(event.target.value)} disabled={!workflow}>
                {targets.map((target) => <option key={target}>{target}</option>)}
              </select>
            </Field>
            <Field label="Research purpose" required className="md:col-span-2">
              <input value={researchPurpose} onChange={(event) => setResearchPurpose(event.target.value)} placeholder="Establish a leakage-safe game simulation baseline" />
            </Field>
            <Field label="Project description" className="md:col-span-2">
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={4} placeholder="Document scope, decision context, and known limitations." />
            </Field>
          </div>

          {error && (
            <div className="mt-5 flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-950" role="alert">
              <CircleAlert className="mt-0.5 shrink-0" size={18} /> {error}
            </div>
          )}

          <button type="submit" disabled={!canCreate} className="sports-primary-button mt-6 w-full justify-center sm:w-auto">
            Create Sports Project <ArrowRight size={17} />
          </button>
        </section>

        <aside className="grid content-start gap-6">
          <section className="sports-panel p-5 sm:p-6">
            <p className="sports-kicker">Illustrative baseline</p>
            <h2 className="mt-1 text-xl font-semibold text-slate-950">Example forecast program</h2>
            <dl className="mt-4 grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm">
              <div className="grid gap-1 sm:grid-cols-[150px_minmax(0,1fr)] sm:items-baseline">
                <dt className="font-semibold text-slate-500">Project</dt>
                <dd className="font-semibold text-slate-900">MLB Gen-2 Free-Data Baseline</dd>
              </div>
              <div className="grid gap-1 sm:grid-cols-[150px_minmax(0,1fr)] sm:items-baseline">
                <dt className="font-semibold text-slate-500">Development</dt>
                <dd className="font-semibold tabular-nums text-slate-900">2023–2025</dd>
              </div>
              <div className="grid gap-1 sm:grid-cols-[150px_minmax(0,1fr)] sm:items-baseline">
                <dt className="font-semibold text-slate-500">Prospective evaluation</dt>
                <dd className="font-semibold tabular-nums text-slate-900">2026</dd>
              </div>
            </dl>
            <p className="mt-3 text-xs leading-5 text-slate-500">Guidance only. No historical or prospective evidence is created, loaded, or implied.</p>
          </section>

          <section className="sports-panel p-5 sm:p-6">
            <p className="sports-kicker">Secondary targets</p>
            <h2 className="mt-1 text-xl font-semibold text-slate-950">Joint research outputs</h2>
            {workflow ? (
              <div className="mt-4 grid gap-2">
                {targets.filter((target) => target !== primaryTarget).map((target) => {
                  const checked = secondaryTargets.includes(target);
                  return (
                    <button key={target} type="button" onClick={() => toggleSecondary(target)} className={`flex items-center gap-3 rounded-xl border px-3 py-3 text-left text-sm font-medium transition ${checked ? "border-teal-300 bg-teal-50 text-teal-950" : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"}`}>
                      <span className={`grid h-5 w-5 shrink-0 place-items-center rounded-md border ${checked ? "border-teal-600 bg-teal-600 text-white" : "border-slate-300"}`}>{checked && <Check size={13} />}</span>
                      {target}
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-600">Target configuration will arrive with this planned workflow.</p>
            )}
          </section>

          <section className="rounded-2xl border border-cyan-900/40 bg-slate-950 p-5 text-white shadow-xl">
            <p className="sports-kicker text-cyan-300">Evidence boundary</p>
            <h2 className="mt-2 text-xl font-semibold">No warehouse connection is created here.</h2>
            <p className="mt-3 text-sm leading-6 text-slate-300">Sports data registration arrives through the immutable SPORTS_DATASET_MANIFEST_V1 contract in Phase 2.</p>
          </section>
        </aside>
      </form>
    </div>
  );
}

function Field({ label, required = false, help, className = "", children }: { label: string; required?: boolean; help?: string; className?: string; children: React.ReactNode }) {
  return (
    <label className={`sports-field ${className}`}>
      <span>{label}{required && <b>Required</b>}</span>
      {children}
      {help && <small className="text-xs font-normal leading-5 text-slate-500">{help}</small>}
    </label>
  );
}

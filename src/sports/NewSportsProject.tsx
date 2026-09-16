import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Check, CircleAlert, Database, Sparkles } from "lucide-react";
import { upsertProjectFromState } from "../lib/localProjects";
import { flushProjectDatabaseSave } from "../lib/serverPersistence";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { mlbWorkflowRoute, sportsProjectOverviewRoute } from "./sportsProjectRoutes";
import { FORECAST_LIFECYCLES, MLB_WORKFLOW, NFL_WORKFLOW, saveSportsProjectMetadata } from "./sportsConfig";
import { SPORT_REGISTRY_V1, leagueRegistryEntry, type LeagueCode, type SportCode } from "./shared/sportRegistry";
import { workflowManifestForLeague } from "./shared/workflowManifest";

function legacyWorkflow(leagueCode: LeagueCode) {
  return leagueCode === "MLB" ? MLB_WORKFLOW : leagueCode === "NFL" ? NFL_WORKFLOW : null;
}

export default function NewSportsProject() {
  const navigate = useNavigate();
  const startProjectFromWorkflow = useWorkflowStore((state) => state.startProjectFromWorkflow);
  const [sportCode, setSportCode] = useState<SportCode>("BASEBALL");
  const [leagueCode, setLeagueCode] = useState<LeagueCode>("MLB");
  const [projectName, setProjectName] = useState("");
  const [period, setPeriod] = useState("");
  const [lifecycle, setLifecycle] = useState<(typeof FORECAST_LIFECYCLES)[number]>("Pregame — Final");
  const [primaryTarget, setPrimaryTarget] = useState("JOINT_SCORE_DISTRIBUTION");
  const [secondaryTargets, setSecondaryTargets] = useState<string[]>(["HOME_WIN_PROBABILITY"]);
  const [researchPurpose, setResearchPurpose] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const pendingProjectIdRef = useRef("");

  const sport = SPORT_REGISTRY_V1.sports.find((item) => item.sportCode === sportCode) ?? SPORT_REGISTRY_V1.sports[0];
  const league = leagueRegistryEntry(leagueCode)?.league ?? sport.leagues[0];
  const manifest = workflowManifestForLeague(leagueCode);
  const workflow = legacyWorkflow(leagueCode);
  const targets = manifest?.supportedTargets ?? [];
  const creationAvailable = Boolean(league?.projectCreationEnabled && workflow && manifest && ["ENABLED", "RESEARCH_ONLY"].includes(manifest.availability));
  const canCreate = Boolean(projectName.trim() && period.trim() && researchPurpose.trim() && primaryTarget && creationAvailable && !creating);

  function selectSport(nextSportCode: SportCode) {
    const nextSport = SPORT_REGISTRY_V1.sports.find((item) => item.sportCode === nextSportCode);
    const nextLeague = nextSport?.leagues[0];
    if (!nextSport || !nextLeague || nextSport.availability === "PLANNED") return;
    setSportCode(nextSportCode);
    selectLeague(nextLeague.leagueCode);
  }

  function selectLeague(nextLeagueCode: LeagueCode) {
    const nextManifest = workflowManifestForLeague(nextLeagueCode);
    const nextLeague = leagueRegistryEntry(nextLeagueCode)?.league;
    if (!nextManifest || !nextLeague) return;
    setLeagueCode(nextLeagueCode);
    setPrimaryTarget(nextManifest.supportedTargets[0] ?? "");
    setSecondaryTargets(nextManifest.supportedTargets[1] ? [nextManifest.supportedTargets[1]] : []);
  }

  function toggleSecondary(target: string) {
    setSecondaryTargets((current) => current.includes(target) ? current.filter((item) => item !== target) : [...current, target]);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!creationAvailable || !workflow || !manifest || !league) {
      setError("This workflow is planned or unavailable. No project, target, or evidence binding was created.");
      return;
    }
    if (!canCreate) {
      setError("Complete the required forecast contract, development period, target, and research-purpose fields.");
      return;
    }
    setCreating(true);
    startProjectFromWorkflow({
      projectId: pendingProjectIdRef.current || undefined,
      modelId: `${workflow.league.toLowerCase()}-${Date.now().toString(36)}`,
      projectName: projectName.trim(),
      projectType: "custom-workflow",
      workflowId: workflow.id as "mlb-forecasting" | "nfl-forecasting",
      workflowSteps: workflow.steps.map((item) => ({ id: item.id, label: item.title, shortLabel: item.title.split(" ").slice(0, 2).join(" "), route: `/workflows/${workflow.key}#${item.id}`, description: item.purpose, required: true, status: "pending" })),
    });
    const state = useWorkflowStore.getState();
    pendingProjectIdRef.current = state.projectId;
    const record = upsertProjectFromState(state);
    if (!record) {
      setError("ASP Model Studio could not create the local project record. No project was registered.");
      setCreating(false);
      return;
    }
    const sportsMetadata = {
      projectId: state.projectId, sport: sport.displayName, league: league.leagueCode, sportCode, leagueCode,
      workflowCode: manifest.workflowCode, workflowAvailability: manifest.availability,
      evidenceStatus: manifest.availability === "RESEARCH_ONLY" ? "RESEARCH_ONLY" as const : "UNBOUND" as const,
      period: period.trim(), workflowId: workflow.id as "mlb-forecasting" | "nfl-forecasting", lifecycle, primaryTarget,
      secondaryTargets, researchPurpose: researchPurpose.trim(), description: description.trim(),
    };
    saveSportsProjectMetadata(sportsMetadata);
    const persisted = await flushProjectDatabaseSave(record.snapshot, { sportsProject: sportsMetadata });
    if (!persisted) {
      setError("The project is saved in this browser but could not be registered in the ASP Model Studio backend. Restore the backend and submit again; the existing canonical project ID will be reused.");
      setCreating(false);
      return;
    }
    navigate(workflow.key === "mlb" ? mlbWorkflowRoute(state.projectId, 1) : sportsProjectOverviewRoute(state.projectId));
  }

  return <div className="sports-page-shell">
    <section className="sports-hero-panel overflow-hidden p-6 sm:p-8 lg:p-10"><div className="relative z-10 max-w-4xl"><div className="sports-eyebrow text-cyan-200"><Sparkles size={16} /> SPORT_WORKFLOW_MANIFEST_V1 registration</div><h1 className="mt-4 text-3xl font-semibold tracking-tight text-white sm:text-4xl">Create a sport-native forecasting program</h1><p className="mt-4 max-w-3xl text-[15px] leading-7 text-slate-300">Select sport, league, workflow, forecast contract, development period, target, and governed evidence in that order. No dataset or model is inferred.</p></div></section>
    <form onSubmit={submit} className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,.65fr)]">
      <section className="sports-panel p-5 sm:p-7">
        <div className="flex items-center justify-between gap-4 border-b border-slate-200 pb-5"><div><p className="sports-kicker">Project identity</p><h2 className="mt-1 text-2xl font-semibold text-slate-950">Governed creation sequence</h2></div><span className="sports-status sports-status--neutral">{manifest?.availability ?? "UNAVAILABLE"}</span></div>
        <div className="mt-6 grid gap-5">
          <CreationStep number="1" title="Select sport" description="Canonical SportCode; league names are never used as sport names."><Field label="Sport" required><select value={sportCode} onChange={(event) => selectSport(event.target.value as SportCode)}>{SPORT_REGISTRY_V1.sports.map((option) => <option key={option.sportCode} value={option.sportCode} disabled={option.availability === "PLANNED"}>{option.displayName} · {option.sportCode} — {option.availability}</option>)}</select></Field></CreationStep>
          <CreationStep number="2" title="Select league or promotion" description="The league must belong to the selected sport."><Field label="League" required><select value={leagueCode} onChange={(event) => selectLeague(event.target.value as LeagueCode)}>{sport.leagues.map((option) => <option key={option.leagueCode} value={option.leagueCode} disabled={!option.projectCreationEnabled}>{option.displayName} · {option.leagueCode} — {option.workflowAvailability}</option>)}</select></Field></CreationStep>
          <CreationStep number="3" title="Select workflow template" description="Manifest availability is capability metadata, not workflow completion."><Field label="Workflow template" required><select value={manifest?.workflowCode ?? ""} disabled><option>{manifest ? `${manifest.displayName} — ${manifest.availability}` : "No workflow manifest available"}</option></select></Field>{manifest?.availability === "RESEARCH_ONLY" ? <p className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">NFL is research-only. Registration cannot promote, deploy, or connect it to an official bankroll.</p> : null}</CreationStep>
          <CreationStep number="4" title="Define forecast contract" description="Freeze project identity and forecast lifecycle before evidence binding."><div className="grid gap-4 md:grid-cols-2"><Field label="Project name" required><input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="MLB Current-Data Game Forecast Challenger" /></Field><Field label="Forecast lifecycle" required><select value={lifecycle} onChange={(event) => setLifecycle(event.target.value as typeof lifecycle)}>{FORECAST_LIFECYCLES.map((option) => <option key={option}>{option}</option>)}</select></Field></div></CreationStep>
          <CreationStep number="5" title="Define development period" description="This records requested temporal scope; it does not load or rebuild data."><Field label="Season or development period" required help="No season data is registered by this form."><input value={period} onChange={(event) => setPeriod(event.target.value)} placeholder="2023–2026-08-13" /></Field></CreationStep>
          <CreationStep number="6" title="Select target" description="Only targets declared by the selected sport manifest are available."><div className="grid gap-4"><Field label="Primary target" required><select value={primaryTarget} onChange={(event) => setPrimaryTarget(event.target.value)} disabled={!creationAvailable}>{targets.map((target) => <option key={target}>{target}</option>)}</select></Field><Field label="Research purpose" required><input value={researchPurpose} onChange={(event) => setResearchPurpose(event.target.value)} placeholder="Establish a point-in-time forecast benchmark" /></Field><Field label="Project description"><textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} /></Field></div></CreationStep>
          <CreationStep number="7" title="Bind eligible governed evidence" description="Binding requires exact sport, league, grain, identity, target, temporal policy, rights, and sealed-evidence compatibility."><div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4"><Database className="mt-0.5 shrink-0 text-cyan-700" size={19} /><div><p className="text-sm font-semibold text-slate-900">Evidence status: {manifest?.availability === "RESEARCH_ONLY" ? "RESEARCH_ONLY" : "UNBOUND"}</p><p className="mt-1 text-xs leading-5 text-slate-600">No workspace dataset is silently linked. Evidence is selected and verified in the project’s Data Evidence stage.</p></div></div></CreationStep>
        </div>
        {error ? <div className="mt-5 flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950" role="alert"><CircleAlert size={18} />{error}</div> : null}
        <button type="submit" disabled={!canCreate} className="sports-primary-button mt-6 w-full justify-center sm:w-auto">{creating ? "Registering project…" : manifest?.availability === "RESEARCH_ONLY" ? "Create Research-Only Project" : "Create Sports Project"} <ArrowRight size={17} /></button>
      </section>
      <aside className="grid content-start gap-6">
        <section className="sports-panel p-5"><p className="sports-kicker">Capability state</p><h2 className="mt-1 text-xl font-semibold">Available now, research-only, planned</h2><div className="mt-4 grid gap-2">{SPORT_REGISTRY_V1.sports.flatMap((item) => item.leagues.map((entry) => <div key={entry.leagueCode} className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 p-3"><div><div className="text-sm font-semibold">{entry.leagueCode}</div><div className="text-xs text-slate-500">{item.displayName}</div></div><span className="sports-status sports-status--neutral">{entry.workflowAvailability}</span></div>))}</div></section>
        <section className="sports-panel p-5"><p className="sports-kicker">Secondary targets</p><h2 className="mt-1 text-xl font-semibold">Joint research outputs</h2><div className="mt-4 grid gap-2">{targets.filter((target) => target !== primaryTarget).map((target) => { const checked = secondaryTargets.includes(target); return <button key={target} type="button" onClick={() => toggleSecondary(target)} className={`flex items-center gap-3 rounded-xl border px-3 py-3 text-left text-sm ${checked ? "border-teal-300 bg-teal-50" : "border-slate-200"}`}><span className={`grid h-5 w-5 place-items-center rounded-md border ${checked ? "bg-teal-600 text-white" : "border-slate-300"}`}>{checked ? <Check size={13} /> : null}</span>{target}</button>; })}</div></section>
      </aside>
    </form>
  </div>;
}

function CreationStep({ number, title, description, children }: { number: string; title: string; description: string; children: React.ReactNode }) {
  return <section className="rounded-2xl border border-slate-200 p-4 sm:p-5"><div className="mb-4 flex items-start gap-3"><span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-slate-950 text-sm font-bold text-cyan-200">{number}</span><div><h3 className="font-semibold text-slate-950">{title}</h3><p className="mt-1 text-xs leading-5 text-slate-500">{description}</p></div></div>{children}</section>;
}

function Field({ label, required = false, help, children }: { label: string; required?: boolean; help?: string; children: React.ReactNode }) {
  return <label className="sports-field"><span>{label}{required ? <b>Required</b> : null}</span>{children}{help ? <small className="text-xs font-normal leading-5 text-slate-500">{help}</small> : null}</label>;
}

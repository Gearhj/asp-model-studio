import { useState } from "react";
import { ArrowRight, FolderKanban, Plus, Trash2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { deleteLocalProject, loadLocalProjects } from "../lib/localProjects";
import { deleteProjectFromDatabase, PersistenceHttpError } from "../lib/serverPersistence";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { deleteSportsProjectMetadata, isSportsWorkflow, loadSportsProjectMetadata, sportsWorkflowForId } from "./sportsConfig";
import { type RegisteredSportsProject, useActiveSportsDataset } from "./sportsEvidenceApi";

export default function SportsProjects() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState(() => loadLocalProjects().filter((project) => isSportsWorkflow(project.workflowId)));
  const [pendingRemovalId, setPendingRemovalId] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [removalError, setRemovalError] = useState("");
  const datasetEvidence = useActiveSportsDataset();
  const governedProject = datasetEvidence.status === "ready" ? datasetEvidence.data.project ?? null : null;
  const localProjects = governedProject
    ? projects.filter((project) => project.projectId !== governedProject.projectId && project.projectName !== governedProject.name)
    : projects;

  function openProject(projectId: string) {
    const project = projects.find((item) => item.projectId === projectId);
    if (!project) return;
    useWorkflowStore.getState().loadProjectSnapshot(project.snapshot);
    navigate("/project-overview");
  }

  function openGovernedProject(project: RegisteredSportsProject) {
    const workflow = sportsWorkflowForId(project.workflowId || "mlb-forecasting");
    const evidenceByStep = new Map((project.stages ?? []).flatMap((stage) => {
      const keys = [stage.stepId, stage.number ? String(stage.number) : undefined, stage.title].filter(Boolean) as string[];
      return keys.map((key) => [key.toLowerCase(), stage] as const);
    }));
    const workflowSteps = workflow.steps.map((item) => {
      const stage = evidenceByStep.get(item.id.toLowerCase())
        ?? evidenceByStep.get(String(item.number))
        ?? evidenceByStep.get(item.title.toLowerCase());
      const complete = stage && ["complete", "completed"].includes(stage.status.toLowerCase());
      return {
        id: item.id,
        label: item.title,
        shortLabel: item.title.split(" ").slice(0, 2).join(" "),
        route: `/workflows/${workflow.key}#${item.id}`,
        description: item.purpose,
        required: true,
        status: complete ? "complete" as const : "pending" as const,
      };
    });
    useWorkflowStore.getState().loadProjectSnapshot({
      projectId: project.projectId,
      modelId: "",
      projectName: project.name,
      projectType: "custom-workflow",
      workflowId: workflow.id,
      workflowSteps,
      currentStepId: workflowSteps[0]?.id ?? "mlb-01",
      hasDataset: false,
      datasetIdentity: null,
    });
    navigate("/project-overview");
  }

  async function removeProject(projectId: string) {
    setRemovingId(projectId);
    setRemovalError("");
    try {
      await deleteProjectFromDatabase(projectId);
    } catch (error) {
      if (!(error instanceof PersistenceHttpError && error.status === 404)) {
        setRemovalError(error instanceof Error ? error.message : "The target-local project record could not be removed.");
        setRemovingId(null);
        return;
      }
    }
    deleteSportsProjectMetadata(projectId);
    const remaining = deleteLocalProject(projectId).filter((project) => isSportsWorkflow(project.workflowId));
    setProjects(remaining);
    setPendingRemovalId(null);
    setRemovingId(null);
    if (useWorkflowStore.getState().projectId === projectId) useWorkflowStore.getState().reset();
  }

  return (
    <div className="sports-page-shell">
      <section className="flex flex-col gap-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:flex-row sm:items-end sm:justify-between sm:p-8">
        <div>
          <p className="sports-kicker">Portfolio</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">Sports Projects</h1>
          <p className="mt-3 max-w-3xl text-[15px] leading-7 text-slate-600">Isolated MLB and NFL forecasting programs registered in this ASP Model Studio workspace.</p>
        </div>
        <Link to="/projects/new" className="sports-primary-button"><Plus size={17} /> Create Sports Project</Link>
      </section>

      {datasetEvidence.status === "loading" && localProjects.length === 0 ? (
        <section className="sports-panel grid min-h-[260px] place-items-center p-8 text-center" role="status"><div><FolderKanban size={26} className="mx-auto animate-pulse text-cyan-700" /><h2 className="mt-4 text-xl font-semibold text-slate-950">Loading governed project registry</h2><p className="mt-2 text-sm text-slate-600">Checking the active sports dataset registration.</p></div></section>
      ) : datasetEvidence.status === "error" && localProjects.length === 0 ? (
        <section className="sports-panel grid min-h-[260px] place-items-center border-amber-200 bg-amber-50 p-8 text-center" role="alert"><div><FolderKanban size={26} className="mx-auto text-amber-700" /><h2 className="mt-4 text-xl font-semibold text-amber-950">Governed project registry unavailable</h2><p className="mt-2 max-w-xl text-sm text-amber-900">{datasetEvidence.error}</p></div></section>
      ) : localProjects.length === 0 && !governedProject ? (
        <section className="sports-panel grid min-h-[360px] place-items-center p-8 text-center">
          <div className="max-w-lg">
            <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-slate-200 bg-slate-50 text-slate-500"><FolderKanban size={26} /></span>
            <h2 className="mt-5 text-2xl font-semibold text-slate-950">No sports projects have been created yet.</h2>
            <p className="mt-3 text-[15px] leading-7 text-slate-600">Start with the active MLB workflow or establish an NFL workflow foundation.</p>
            <Link to="/projects/new" className="sports-primary-button mt-6">Create Sports Project <ArrowRight size={17} /></Link>
          </div>
        </section>
      ) : (
        <section className="grid gap-4 lg:grid-cols-2">
          {governedProject ? <GovernedProjectCard project={governedProject} onOpen={() => openGovernedProject(governedProject)} /> : null}
          {localProjects.map((project) => {
            const workflow = sportsWorkflowForId(project.workflowId);
            const metadata = loadSportsProjectMetadata(project.projectId);
            const complete = project.snapshot.workflowSteps.filter((step) => step.status === "complete").length;
            return (
              <article key={project.projectId} className="sports-panel p-5 sm:p-6">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <span className="sports-status sports-status--neutral">{workflow.league}</span>
                    <h2 className="mt-3 text-xl font-semibold text-slate-950">{project.projectName}</h2>
                    <p className="mt-1 text-sm text-slate-500">{workflow.title} · {metadata?.period || "Development period not configured"}</p>
                  </div>
                  <span className="sports-status sports-status--amber">NOT CONFIGURED</span>
                </div>
                <div className="mt-5 grid grid-cols-2 gap-3 border-y border-slate-100 py-4 sm:grid-cols-3">
                  <Fact label="Lifecycle" value={metadata?.lifecycle || "Not configured"} />
                  <Fact label="Primary target" value={metadata?.primaryTarget || "Not configured"} />
                  <Fact label="Workflow" value={`${complete} / ${project.snapshot.workflowSteps.length}`} />
                </div>
                <div className="mt-5 flex flex-wrap gap-2">
                  <button onClick={() => openProject(project.projectId)} className="sports-secondary-button">Open project <ArrowRight size={16} /></button>
                  <button type="button" onClick={() => { setPendingRemovalId(project.projectId); setRemovalError(""); }} className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-red-200 bg-white px-4 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-50">
                    <Trash2 size={16} /> Remove local project
                  </button>
                </div>
                {pendingRemovalId === project.projectId && (
                  <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-950" role="alert">
                    <p className="font-semibold">Remove this target-local project?</p>
                    <p className="mt-1 text-xs leading-5 text-red-800">This removes its saved workflow record and sports metadata from this browser and the isolated target-local database. Dataset Library assets are retained.</p>
                    {removalError && <p className="mt-2 rounded-lg border border-red-300 bg-white px-3 py-2 font-semibold" role="status">{removalError} No browser record was removed.</p>}
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button type="button" disabled={removingId === project.projectId} onClick={() => void removeProject(project.projectId)} className="inline-flex min-h-9 items-center rounded-lg bg-red-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-800 disabled:cursor-wait disabled:opacity-60">{removingId === project.projectId ? "Removing…" : "Confirm removal"}</button>
                      <button type="button" disabled={removingId === project.projectId} onClick={() => { setPendingRemovalId(null); setRemovalError(""); }} className="inline-flex min-h-9 items-center rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-semibold text-red-800 hover:bg-red-100 disabled:opacity-60">Cancel</button>
                    </div>
                  </div>
                )}
                <details className="mt-4 text-xs text-slate-500">
                  <summary className="cursor-pointer font-semibold">Technical details</summary>
                  <div className="mt-2 break-all rounded-lg bg-slate-50 p-3">Project ID: {project.projectId}</div>
                </details>
              </article>
            );
          })}
        </section>
      )}
    </div>
  );
}

function GovernedProjectCard({ project, onOpen }: { project: RegisteredSportsProject; onOpen: () => void }) {
  const evidencedStages = (project.stages ?? []).filter((stage) => !["pending", "not_configured", "not configured"].includes(stage.status.toLowerCase())).length;
  const projectBlocked = (project.status || "").toLowerCase().includes("blocked");
  return <article className={`sports-panel ${projectBlocked ? "border-amber-200" : "border-emerald-200"} p-5 sm:p-6`} data-governed-sports-project={project.projectId}>
    <div className="flex flex-wrap items-start justify-between gap-4"><div className="min-w-0 flex-1"><span className="sports-status sports-status--teal">{project.league || "MLB"}</span><h2 className="mt-3 break-words text-xl font-semibold text-slate-950">{project.name}</h2><p className="mt-1 text-sm text-slate-500">Governed project bound to the active immutable dataset registration · {project.developmentPeriod || "development period not recorded"}</p></div><span className={`sports-status ${projectBlocked ? "sports-status--amber" : "sports-status--green"} max-w-full whitespace-normal break-words text-center leading-4`}>{project.status || "REGISTERED"}</span></div>
    <div className="mt-5 grid grid-cols-2 gap-3 border-y border-slate-100 py-4 sm:grid-cols-3"><Fact label="Lifecycle" value={project.forecastLifecycle || "Not recorded"} /><Fact label="Primary target" value={project.primaryTarget || "Not recorded"} /><Fact label="Workflow evidence" value={`${evidencedStages} / 12`} /></div>
    <div className="mt-5"><button type="button" onClick={onOpen} className="sports-secondary-button">Open governed project <ArrowRight size={16} /></button></div>
    <details className="mt-4 text-xs text-slate-500"><summary className="cursor-pointer font-semibold">Technical details</summary><div className="mt-2 break-all rounded-lg bg-slate-50 p-3">Project ID: {project.projectId}</div></details>
  </article>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</div><div className="mt-1 text-sm font-semibold text-slate-800">{value}</div></div>;
}

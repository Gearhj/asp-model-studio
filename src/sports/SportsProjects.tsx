import { useState } from "react";
import { ArrowRight, FolderKanban, Plus, Trash2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { deleteLocalProject, loadLocalProjects } from "../lib/localProjects";
import { deleteProjectFromDatabase, PersistenceHttpError } from "../lib/serverPersistence";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { deleteSportsProjectMetadata, isSportsWorkflow, loadSportsProjectMetadata, sportsWorkflowForId } from "./sportsConfig";

export default function SportsProjects() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState(() => loadLocalProjects().filter((project) => isSportsWorkflow(project.workflowId)));
  const [pendingRemovalId, setPendingRemovalId] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [removalError, setRemovalError] = useState("");

  function openProject(projectId: string) {
    const project = projects.find((item) => item.projectId === projectId);
    if (!project) return;
    useWorkflowStore.getState().loadProjectSnapshot(project.snapshot);
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

      {projects.length === 0 ? (
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
          {projects.map((project) => {
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

function Fact({ label, value }: { label: string; value: string }) {
  return <div><div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</div><div className="mt-1 text-sm font-semibold text-slate-800">{value}</div></div>;
}

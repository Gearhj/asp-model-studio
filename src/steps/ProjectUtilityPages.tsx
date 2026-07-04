import { Link, useNavigate } from "react-router-dom";
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { Calendar, Copy, Database, Download, FileArchive, FileInput, FolderOpen, FolderPlus, Pencil, Plus, RefreshCw, Save, Settings2, Trash2 } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import {
  currentWorkflowStage,
  deleteLocalProject,
  duplicateLocalProject,
  formatProjectDate,
  getLocalProjectsRegistryStatus,
  getProjectPersistenceDebug,
  importLocalProject,
  loadLocalProjects,
  migrateLegacyLocalProjects,
  projectProgress,
  repairLocalProjectsRegistry,
  renameLocalProject,
  saveProjectSnapshotFromState,
  type LocalProjectRecord,
  type LocalProjectsRegistryStatus,
  upsertProjectFromState,
  workflowLabel,
} from "../lib/localProjects";
import { validateProjectImport } from "../lib/projectImportValidation";
import { useWorkflowStore } from "../state/useWorkflowStore";

export function OpenProject() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [projects, setProjects] = useState<LocalProjectRecord[]>([]);
  const [importMessage, setImportMessage] = useState("");
  const [registryStatus, setRegistryStatus] = useState<LocalProjectsRegistryStatus>(() => ({
    ok: true,
    corrupted: false,
    message: "",
    projectCount: 0,
    validProjects: [],
  }));
  const loadProjectSnapshot = useWorkflowStore((state) => state.loadProjectSnapshot);
  const activeProjectId = useWorkflowStore((state) => state.projectId);
  const setProjectName = useWorkflowStore((state) => state.setProjectName);
  const resetProject = useWorkflowStore((state) => state.reset);

  useEffect(() => {
    const status = getLocalProjectsRegistryStatus();
    setRegistryStatus(status);
    if (status.corrupted) {
      setProjects(status.validProjects);
      setImportMessage(status.message);
      return;
    }
    try {
      const migration = migrateLegacyLocalProjects();
      const nextStatus = getLocalProjectsRegistryStatus();
      setRegistryStatus(nextStatus);
      setProjects(loadLocalProjects());
      if (migration.migrated > 0) {
        setImportMessage(`Recovered ${migration.migrated} browser-saved project${migration.migrated === 1 ? "" : "s"} from legacy ATLAS storage.`);
      }
    } catch (error) {
      setProjects(loadLocalProjects());
      setImportMessage(error instanceof Error ? `Open Project loaded, but project registry maintenance failed: ${error.message}` : "Open Project loaded, but project registry maintenance failed.");
    }
    // Keep the launcher route resilient even when registry migration fails.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openProject = (project: LocalProjectRecord) => {
    loadProjectSnapshot(project.snapshot);
    const route = currentWorkflowStage(project.snapshot.workflowSteps, project.snapshot.currentStepId)?.route || "/project-overview";
    navigate(route);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const repairRegistry = () => {
    try {
      const result = repairLocalProjectsRegistry();
      const status = getLocalProjectsRegistryStatus();
      setRegistryStatus(status);
      setProjects(result.projects);
      setImportMessage(result.message);
    } catch (error) {
      setImportMessage(error instanceof Error ? `Recent Projects repair failed: ${error.message}` : "Recent Projects repair failed.");
    }
  };

  const duplicateProject = (event: React.MouseEvent, project: LocalProjectRecord) => {
    event.stopPropagation();
    const { projects: nextProjects, duplicate } = duplicateLocalProject(project.projectId);
    setProjects(nextProjects);
    if (duplicate) setImportMessage(`Duplicated "${project.projectName}".`);
  };

  const renameProject = (event: React.MouseEvent, project: LocalProjectRecord) => {
    event.stopPropagation();
    const nextName = window.prompt("Rename project", project.projectName);
    if (!nextName || !nextName.trim()) return;
    const nextProjects = renameLocalProject(project.projectId, nextName);
    setProjects(nextProjects);
    if (project.projectId === activeProjectId) setProjectName(nextName.trim());
    setImportMessage(`Renamed project to "${nextName.trim()}".`);
  };

  const removeProject = (event: React.MouseEvent, project: LocalProjectRecord) => {
    event.stopPropagation();
    const confirmed = window.confirm(`Delete "${project.projectName}" from local recent projects? This will not remove source data files from your machine.`);
    if (!confirmed) return;
    setProjects(deleteLocalProject(project.projectId));
    if (project.projectId === activeProjectId) resetProject();
    setImportMessage(`Deleted "${project.projectName}" from Recent Projects.`);
  };

  const importProjectFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      const validation = validateProjectImport(parsed);
      if (!validation.ok) {
        setImportMessage(`Import rejected: ${validation.errors.join(" ")}`);
        return;
      }
      const imported = importLocalProject(parsed);
      if (!imported) {
        setImportMessage("The selected file does not look like an ATLAS project export.");
        return;
      }
      setProjects(loadLocalProjects());
      setImportMessage(`Imported "${imported.projectName}".${validation.warnings.length ? ` ${validation.warnings.join(" ")}` : ""}`);
    } catch {
      setImportMessage("Could not import that file. Select a valid ATLAS project JSON export.");
    }
  };

  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <BrandLogo size="md" variant="light" showSubtitle className="mb-4" />
            <div className="flex items-center gap-2">
              <FolderOpen size={20} className="text-blue-600" />
              <h1 className="text-xl font-semibold text-slate-950">Recent Projects</h1>
            </div>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
              Browser-saved projects appear below automatically. Use file import only for exported .atlas or .json project packages.
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-3 lg:min-w-[520px]">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
            >
              <FolderOpen size={16} />
              Open Local Project...
            </button>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
            >
              <FileInput size={16} />
              Import Project...
            </button>
            <Link
              to="/projects/new"
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
            >
              <Plus size={16} />
              Create New Project
            </Link>
          </div>
        </div>
        <input ref={fileInputRef} type="file" accept="application/json,.json,.atlas" className="hidden" onChange={importProjectFile} />
        {registryStatus.corrupted && (
          <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
            <div className="font-semibold">Recent Projects index needs repair</div>
            <p className="mt-1">{registryStatus.message}</p>
            <button
              type="button"
              onClick={repairRegistry}
              className="mt-3 inline-flex items-center gap-2 rounded-lg bg-amber-900 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-amber-800"
            >
              <RefreshCw size={15} />
              Repair Recent Projects
            </button>
          </div>
        )}
        {importMessage && <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{importMessage}</div>}
      </section>

      {projects.length === 0 ? (
        <EmptyProjects />
      ) : (
        <section className="space-y-3">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Browser Projects</h2>
            <p className="mt-1 text-sm text-slate-600">These projects are stored in this browser and do not require a manual export to reopen.</p>
          </div>
          <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-3">
            {projects.map((project) => (
              <ProjectCard
                key={project.projectId}
                project={project}
                isActive={project.projectId === activeProjectId}
                onOpen={openProject}
                onDuplicate={duplicateProject}
                onRename={renameProject}
                onDelete={removeProject}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function ProjectCard({
  project,
  isActive,
  onOpen,
  onDuplicate,
  onRename,
  onDelete,
}: {
  project: LocalProjectRecord;
  isActive: boolean;
  onOpen: (project: LocalProjectRecord) => void;
  onDuplicate: (event: React.MouseEvent, project: LocalProjectRecord) => void;
  onRename: (event: React.MouseEvent, project: LocalProjectRecord) => void;
  onDelete: (event: React.MouseEvent, project: LocalProjectRecord) => void;
}) {
  const progress = projectProgress(project.snapshot.workflowSteps);
  const currentStage = currentWorkflowStage(project.snapshot.workflowSteps, project.snapshot.currentStepId);
  const label = workflowLabel(project.projectType, project.workflowId);

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={() => onOpen(project)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onOpen(project);
      }}
      className="group cursor-pointer rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold text-slate-950">{project.projectName}</h2>
            {isActive && <span className="rounded-full bg-blue-50 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-blue-700">Current</span>}
            <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
              {project.source === "imported" ? "Imported" : "Browser saved"}
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-600">{label}</p>
        </div>
        {project.modelId && (
          <span className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs font-semibold text-slate-700">
            ID {project.modelId}
          </span>
        )}
      </div>

      <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="flex items-center justify-between gap-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
          <span>{progress.complete} of {progress.total} steps complete</span>
          <span>{progress.percent}%</span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
          <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${progress.percent}%` }} />
        </div>
        <div className="mt-3 grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
          <Meta label="Current stage" value={currentStage?.label ?? "Not started"} />
          <Meta label="Workflow type" value={project.projectType.replace(/-/g, " ")} />
        </div>
      </div>

      <div className="mt-4 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
        <div className="flex items-center gap-2">
          <Calendar size={14} />
          <span>Created {formatProjectDate(project.createdAt)}</span>
        </div>
        <div className="flex items-center gap-2">
          <Calendar size={14} />
          <span>Modified {formatProjectDate(project.lastModified)}</span>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onOpen(project);
          }}
          className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
        >
          <FolderOpen size={15} />
          Open
        </button>
        <CardButton icon={<Copy size={15} />} label="Duplicate" onClick={(event) => onDuplicate(event, project)} />
        <CardButton icon={<Pencil size={15} />} label="Rename" onClick={(event) => onRename(event, project)} />
        <CardButton icon={<Trash2 size={15} />} label="Delete" onClick={(event) => onDelete(event, project)} danger />
      </div>
    </article>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-0.5 capitalize text-slate-900">{value}</div>
    </div>
  );
}

function CardButton({ icon, label, onClick, danger = false }: { icon: React.ReactNode; label: string; onClick: (event: React.MouseEvent) => void; danger?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold shadow-sm ${
        danger
          ? "border-red-200 bg-white text-red-700 hover:bg-red-50"
          : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function EmptyProjects() {
  return (
    <section className="rounded-xl border border-dashed border-slate-300 bg-white/80 p-8 text-center shadow-sm">
      <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-2xl bg-blue-50 text-blue-700">
        <FolderPlus size={36} />
      </div>
      <h2 className="mt-4 text-lg font-semibold text-slate-950">No local projects yet</h2>
      <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-600">
        Create your first ATLAS project or import a project JSON export. Once a project exists, it will appear here as a reusable workspace card.
      </p>
      <Link
        to="/projects/new"
        className="mt-5 inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
      >
        <Plus size={16} />
        Create New Project
      </Link>
    </section>
  );
}

export function ExportsPage() {
  return (
    <UtilityPage
      icon={<FileArchive size={20} />}
      title="Exports"
      description="Use Governance, Notebook, Decision Journal, Experiment Comparison, and Model Development Document exports from the Current Project tools."
      actionLabel="Open Governance Report"
      actionPath="/governance-report"
    />
  );
}

export function SettingsPage() {
  const workflowState = useWorkflowStore((state) => ({
    hasDataset: state.hasDataset,
    projectId: state.projectId,
    modelId: state.modelId,
    projectName: state.projectName,
    projectType: state.projectType,
    workflowId: state.workflowId,
    workflowSteps: state.workflowSteps,
    currentStepId: state.currentStepId,
    projectTools: state.projectTools,
  }));
  const [debug, setDebug] = useState(() => getProjectPersistenceDebug(workflowState.projectId, workflowState.workflowSteps));
  const [message, setMessage] = useState("");

  const refresh = () => setDebug(getProjectPersistenceDebug(workflowState.projectId, workflowState.workflowSteps));

  const saveNow = () => {
    try {
      saveProjectSnapshotFromState(useWorkflowStore.getState());
      setMessage("Project snapshot saved successfully.");
      refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save the current project snapshot.");
    }
  };

  const exportCurrentProject = () => {
    const project = loadLocalProjects().find((item) => item.projectId === workflowState.projectId);
    if (!project) {
      setMessage("Save the current project before exporting.");
      return;
    }
    const blob = new Blob([JSON.stringify(project, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${project.projectName.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase() || "atlas-project"}.atlas`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const repairIndex = () => {
    const migration = migrateLegacyLocalProjects();
    upsertProjectFromState(useWorkflowStore.getState());
    setMessage(`Recent Projects repaired. ${migration.migrated} legacy project${migration.migrated === 1 ? "" : "s"} recovered.`);
    refresh();
  };

  const clearCurrentProjectCache = () => {
    const confirmed = window.confirm("Clear cached workflow-node artifacts for the current project? This does not delete the Recent Project card.");
    if (!confirmed || typeof localStorage === "undefined") return;
    const prefix = `atlas-workflow-node-state:${workflowState.projectId}:`;
    const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).filter(
      (key): key is string => Boolean(key?.startsWith(prefix))
    );
    keys.forEach((key) => localStorage.removeItem(key));
    setMessage(`Cleared ${keys.length} workflow-node cache entr${keys.length === 1 ? "y" : "ies"} for this project.`);
    refresh();
  };

  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
        <div className="flex items-center gap-2">
          <Settings2 size={20} />
          <h1 className="text-xl font-semibold text-slate-950">Settings</h1>
        </div>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
          Global ATLAS settings will live here. Challenge Mode and workflow-specific settings are currently available inside Atlas Guide and each workflow step.
        </p>
      </section>

      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Database size={18} className="text-blue-700" />
              <h2 className="text-base font-semibold text-slate-950">Project Persistence Debug</h2>
            </div>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Inspect the browser snapshot used by Recent Projects. Use this if a project does not reopen with expected page inputs.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={saveNow} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
              <Save size={15} />
              Save Now
            </button>
            <button type="button" onClick={exportCurrentProject} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <Download size={15} />
              Export Project
            </button>
            <button type="button" onClick={repairIndex} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <RefreshCw size={15} />
              Repair Recent Projects
            </button>
            <button type="button" onClick={clearCurrentProjectCache} className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-700 shadow-sm hover:bg-red-50">
              <Trash2 size={15} />
              Clear Local Project Cache
            </button>
          </div>
        </div>
        {message && <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{message}</div>}
        <div className="mt-4 grid gap-3 lg:grid-cols-4">
          <MetaCard label="Project ID" value={debug.projectId} />
          <MetaCard label="Snapshot size" value={`${Math.round(debug.snapshotBytes / 1024).toLocaleString()} KB`} />
          <MetaCard label="Last saved" value={debug.lastSavedAt ? formatProjectDate(debug.lastSavedAt) : "Not saved"} />
          <MetaCard label="Restore status" value={debug.restoreStatus} />
          <MetaCard label="Registry size" value={`${Math.round(debug.registryBytes / 1024).toLocaleString()} KB`} />
          <MetaCard label="Workflow steps saved" value={`${debug.workflowStepsSaved}`} />
          <MetaCard label="Storage usage" value={`${Math.round(debug.storageUsageBytes / 1024).toLocaleString()} KB`} />
          <MetaCard label="Dataset preview" value={debug.datasetPreviewAvailable ? "Available" : "Missing"} />
          <MetaCard label="Training summary" value={debug.trainingSummaryAvailable ? "Available" : "Missing"} />
          <MetaCard label="Missing node states" value={`${debug.missingWorkflowSteps.length}`} />
          <MetaCard label="Current step" value={workflowState.currentStepId} />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <DebugList title="Local Storage Keys" items={debug.localStorageKeys} />
          <DebugList title="Session Storage Keys" items={debug.sessionStorageKeys} />
          <DebugList title="Workflow Node Keys" items={debug.workflowStepKeys} />
          <DebugList title="Missing Artifacts" items={debug.missingArtifacts} empty="No missing large artifacts recorded for the saved snapshot." />
          <DebugList title="Missing Workflow Artifacts" items={debug.missingWorkflowSteps} empty="All workflow node artifacts currently have saved keys." />
        </div>
      </section>
    </div>
  );
}

function MetaCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950" title={value}>
        {value}
      </div>
    </div>
  );
}

function DebugList({ title, items, empty = "None" }: { title: string; items: string[]; empty?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <div className="mt-2 max-h-40 overflow-auto rounded-md bg-white p-2 font-mono text-[11px] leading-5 text-slate-700">
        {items.length ? items.map((item) => <div key={item} className="break-all">{item}</div>) : <div className="font-sans text-slate-500">{empty}</div>}
      </div>
    </div>
  );
}

function UtilityPage({
  icon,
  title,
  description,
  actionLabel,
  actionPath,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  actionLabel: string;
  actionPath: string;
}) {
  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
        <div className="flex items-center gap-2">
          {icon}
          <h1 className="text-xl font-semibold text-slate-950">{title}</h1>
        </div>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">{description}</p>
        <Link to={actionPath} className="mt-4 inline-flex rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
          {actionLabel}
        </Link>
      </section>
    </div>
  );
}

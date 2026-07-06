import { useState } from "react";
import type React from "react";
import { NavLink } from "react-router-dom";
import {
  BookOpenCheck,
  Boxes,
  ChevronDown,
  ChevronRight,
  Database,
  FileArchive,
  FileClock,
  FileText,
  FlaskConical,
  FolderOpen,
  Gauge,
  Home,
  NotebookTabs,
  Plus,
  Settings2,
  Activity,
  ShieldCheck,
  UserCircle,
  Users,
  Workflow,
} from "lucide-react";
import BrandLogo from "./BrandLogo";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { saveActiveProjectBeforeNavigation } from "../lib/localProjects";

function linkClass(isActive: boolean, nested = false) {
  return [
    "flex min-h-9 items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
    nested ? "pl-8" : "",
    isActive ? "bg-blue-600 text-white shadow-sm" : "text-slate-200 hover:bg-white/10 hover:text-white",
  ].join(" ");
}

function statusClass(status?: string) {
  if (status === "complete") return "bg-emerald-400 ring-2 ring-emerald-400/20";
  if (status === "in_progress") return "bg-sky-400 ring-2 ring-sky-400/20";
  if (status === "skipped") return "bg-amber-400 ring-2 ring-amber-400/20";
  return "bg-white/25";
}

export default function Sidebar() {
  const [workflowOpen, setWorkflowOpen] = useState(true);
  const workflowSteps = useWorkflowStore((state) => state.workflowSteps);
  const projectName = useWorkflowStore((state) => state.projectName);
  const workflowId = useWorkflowStore((state) => state.workflowId);
  const saveBeforeOpenProject = () => {
    saveActiveProjectBeforeNavigation(useWorkflowStore.getState());
  };

  return (
    <aside className="hidden w-64 shrink-0 border-r border-slate-900 bg-[#071526] shadow-[1px_0_0_rgba(15,23,42,0.2)] lg:block">
      <div className="border-b border-white/10 px-4 py-4">
        <BrandLogo size="sm" variant="dark" showSubtitle />
      </div>

      <nav className="flex flex-col gap-5 px-3 py-4">
        <NavGroup label="Home">
          <NavLink to="/dashboard" className={({ isActive }) => linkClass(isActive)}>
            <Home size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Atlas Home</span>
          </NavLink>
        </NavGroup>

        <NavGroup label="Projects">
          <NavLink to="/projects/new" className={({ isActive }) => linkClass(isActive)}>
            <Plus size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">New Project</span>
          </NavLink>
          <NavLink to="/projects/open" onClick={saveBeforeOpenProject} className={({ isActive }) => linkClass(isActive)}>
            <FolderOpen size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Open Project</span>
          </NavLink>
          <NavLink to="/templates" className={({ isActive }) => linkClass(isActive)}>
            <Boxes size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Templates</span>
          </NavLink>
          <NavLink to="/datasets" className={({ isActive }) => linkClass(isActive)}>
            <Database size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Dataset Library</span>
          </NavLink>
        </NavGroup>

        <NavGroup label="Current Project" detail={projectName}>
          <NavLink to="/project-overview" className={({ isActive }) => linkClass(isActive)}>
            <Gauge size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Overview</span>
          </NavLink>

          <button
            type="button"
            className="flex min-h-9 w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium text-slate-200 transition hover:bg-white/10 hover:text-white"
            onClick={() => setWorkflowOpen((current) => !current)}
          >
            {workflowOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            <Workflow size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Workflow</span>
          </button>

          {workflowOpen && (
            <div className="grid gap-1">
              {workflowSteps.map((step) => (
                <NavLink key={step.id} to={step.route} className={({ isActive }) => linkClass(isActive, true)}>
                  <span className={`h-2 w-2 shrink-0 rounded-full ${statusClass(step.status)}`} />
                  <span className="min-w-0 flex-1 truncate" title={step.label}>
                    {step.label}
                  </span>
                </NavLink>
              ))}
            </div>
          )}

          <NavLink to="/experiments" className={({ isActive }) => linkClass(isActive)}>
            <FlaskConical size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Experiments</span>
          </NavLink>
          <NavLink to="/journal" className={({ isActive }) => linkClass(isActive)}>
            <FileClock size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Decision Journal</span>
          </NavLink>
          <NavLink to="/governance-report" className={({ isActive }) => linkClass(isActive)}>
            <BookOpenCheck size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Governance</span>
          </NavLink>
          <NavLink to="/notebook-export" className={({ isActive }) => linkClass(isActive)}>
            <NotebookTabs size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Notebook</span>
          </NavLink>
          <NavLink to="/exports" className={({ isActive }) => linkClass(isActive)}>
            <FileArchive size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Exports</span>
          </NavLink>
        </NavGroup>

        <NavGroup label="Settings">
          <NavLink to="/account" className={({ isActive }) => linkClass(isActive)}>
            <UserCircle size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Account</span>
          </NavLink>
          <NavLink to="/admin/users" className={({ isActive }) => linkClass(isActive)}>
            <Users size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">User Administration</span>
          </NavLink>
          <NavLink to="/audit" className={({ isActive }) => linkClass(isActive)}>
            <ShieldCheck size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Audit Log</span>
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => linkClass(isActive)}>
            <Settings2 size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Settings</span>
          </NavLink>
          <NavLink to="/system/diagnostics" className={({ isActive }) => linkClass(isActive)}>
            <Activity size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">System Diagnostics</span>
          </NavLink>
          {workflowId === "predictive-modeling" && (
            <NavLink to="/step11" className={({ isActive }) => linkClass(isActive)}>
              <FileText size={17} className="shrink-0" />
              <span className="min-w-0 flex-1 truncate">Model Document</span>
            </NavLink>
          )}
        </NavGroup>
      </nav>
    </aside>
  );
}

function NavGroup({ label, detail, children }: { label: string; detail?: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-1.5">
      <div className="px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</div>
      {detail && <div className="px-3 text-[11px] font-medium leading-4 text-slate-500">{detail}</div>}
      {children}
    </section>
  );
}

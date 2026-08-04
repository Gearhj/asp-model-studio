import { useEffect, useMemo, useState } from "react";
import type React from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  BookOpenCheck,
  Boxes,
  ChevronDown,
  ChevronRight,
  Database,
  FileArchive,
  FileClock,
  FileCode2,
  FlaskConical,
  FolderOpen,
  Gauge,
  Home,
  NotebookTabs,
  Plus,
  Settings2,
  Activity,
  Bell,
  BarChart3,
  LineChart,
  Landmark,
  LayoutDashboard,
  Network,
  FolderKanban,
  ShieldCheck,
  Share2,
  ClipboardCheck,
  PanelLeftClose,
  PanelLeftOpen,
  UserCircle,
  Users,
  Workflow,
} from "lucide-react";
import BrandLogo from "./BrandLogo";
import { selectEffectiveWorkflowSteps, useWorkflowStore } from "../state/useWorkflowStore";
import { saveActiveProjectBeforeNavigation } from "../lib/localProjects";
import { loadTransportationOptimizationSnapshot, optimizationWorkflowStepStatus, type OptimizationWorkflowStatus } from "../lib/transportationOptimizationEvidence";
import {
  normalizeWorkflowRoute,
  projectWorkflowNavigationPath,
  scopedProjectIdForPathname,
} from "../lib/projectScopedRoutes";
import { useAuthoritativeProjectContext } from "./PredictiveIdentityProvider";

function linkClass(isActive: boolean, nested = false) {
  return [
    "relative flex min-h-9 items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300",
    nested ? "pl-8" : "",
    isActive
      ? "bg-blue-500/[0.15] text-white shadow-sm before:absolute before:left-0 before:top-2 before:h-[calc(100%-1rem)] before:w-1 before:rounded-full before:bg-sky-300"
      : "text-slate-300 hover:bg-white/10 hover:text-white",
  ].join(" ");
}

function statusClass(status?: string) {
  if (status === "complete") return "bg-emerald-400 ring-2 ring-emerald-400/20";
  if (status === "in_progress") return "bg-sky-400 ring-2 ring-sky-400/20";
  if (status === "skipped") return "bg-amber-400 ring-2 ring-amber-400/20";
  return "bg-white/25";
}

function optimizationStatusClass(status: OptimizationWorkflowStatus) {
  if (status === "Current") return "bg-blue-400/20 text-blue-100";
  if (status === "Evidence") return "bg-emerald-400/20 text-emerald-100";
  if (status === "Complete") return "bg-teal-400/20 text-teal-100";
  if (status === "Blocked") return "bg-amber-400/20 text-amber-100";
  return "bg-white/10 text-slate-300";
}

export default function Sidebar() {
  const [workflowOpen, setWorkflowOpen] = useState(true);
  const [compact, setCompact] = useState(() => localStorage.getItem("atlas-sidebar-mode") === "compact");
  const [optimizationVersion, setOptimizationVersion] = useState(0);
  const location = useLocation();
  const workflowSteps = useWorkflowStore(selectEffectiveWorkflowSteps);
  const projectName = useWorkflowStore((state) => state.projectName);
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectType = useWorkflowStore((state) => state.projectType);
  const normalizedPathname = normalizeWorkflowRoute(location.pathname);
  const routeProjectId = scopedProjectIdForPathname(location.pathname);
  const { readiness: projectReadiness } = useAuthoritativeProjectContext();
  const readyRouteProject = routeProjectId
    && projectReadiness.status === "ready"
    && projectReadiness.routeProjectId === routeProjectId
      ? projectReadiness.project
      : null;
  const displayedProjectName = routeProjectId
    ? readyRouteProject?.projectName || "Loading project context..."
    : projectName;
  const projectContextReady = !routeProjectId || Boolean(readyRouteProject);
  const displayedProjectId = readyRouteProject?.projectId || projectId;
  const displayedProjectType = readyRouteProject?.projectType || projectType;
  const optimizationState = useMemo(() => projectType === "optimization" ? loadTransportationOptimizationSnapshot(projectId) : null, [optimizationVersion, projectId, projectType]);

  useEffect(() => {
    const refresh = () => setOptimizationVersion((value) => value + 1);
    window.addEventListener("atlas-workflow-node-updated", refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener("atlas-workflow-node-updated", refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);
  const saveBeforeOpenProject = () => {
    saveActiveProjectBeforeNavigation(useWorkflowStore.getState());
  };

  const toggleCompact = () => {
    setCompact((current) => {
      const next = !current;
      localStorage.setItem("atlas-sidebar-mode", next ? "compact" : "expanded");
      return next;
    });
  };

  return (
    <aside className={`hidden h-screen shrink-0 border-r border-slate-900 bg-[#071526] shadow-[1px_0_0_rgba(15,23,42,0.2)] transition-[width] duration-200 lg:sticky lg:top-0 lg:block ${compact ? "w-20 [&_span]:hidden [&_section>div]:hidden [&_a]:justify-center [&_a]:gap-0 [&_a]:px-2 [&_button]:justify-center [&_button]:gap-0 [&_button]:px-2" : "w-64"}`}>
      <div className={`flex items-center border-b border-white/10 py-4 ${compact ? "justify-center px-2" : "justify-between px-4"}`}>
        <BrandLogo size="sm" variant="dark" showSubtitle={!compact} />
        <button type="button" onClick={toggleCompact} className="rounded-lg p-2 text-slate-300 hover:bg-white/10 hover:text-white" title={compact ? "Expand navigation" : "Collapse navigation"}>
          {compact ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
        </button>
      </div>

      <nav className={`flex h-[calc(100vh-73px)] flex-col gap-5 overflow-y-auto py-4 ${compact ? "px-2" : "px-3"}`}>
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
        </NavGroup>

        <NavGroup label="Management">
          <NavLink to="/management-dashboard" className={({ isActive }) => linkClass(isActive)}>
            <LayoutDashboard size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Management Dashboard</span>
          </NavLink>
          <NavLink to="/registry" className={({ isActive }) => linkClass(isActive)}>
            <FolderKanban size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Model / Decision Registry</span>
          </NavLink>
          <NavLink to="/validation" className={({ isActive }) => linkClass(isActive)}>
            <ClipboardCheck size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Validation Queue</span>
          </NavLink>
          <NavLink to="/monitoring" className={({ isActive }) => linkClass(isActive)}>
            <Activity size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Monitoring Center</span>
          </NavLink>
          <NavLink to="/model-evidence-center" className={({ isActive }) => linkClass(isActive)}>
            <Network size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Model Evidence Center</span>
          </NavLink>
          <NavLink to="/audit" className={({ isActive }) => linkClass(isActive)}>
            <ShieldCheck size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Audit Log</span>
          </NavLink>
          <NavLink to="/sharing" className={({ isActive }) => linkClass(isActive)}>
            <Share2 size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Shared with Me</span>
          </NavLink>
          <NavLink to="/notifications" className={({ isActive }) => linkClass(isActive)}>
            <Bell size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Notifications</span>
          </NavLink>
        </NavGroup>

        <NavGroup label="Data and Analysis">
          <NavLink to="/datasets" className={({ isActive }) => linkClass(isActive)}>
            <Database size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Dataset Library</span>
          </NavLink>
          <NavLink to="/sql-data-studio" className={({ isActive }) => linkClass(isActive)}>
            <FileCode2 size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">SQL Data Studio</span>
          </NavLink>
          <NavLink to="/analytics" className={({ isActive }) => linkClass(isActive)}>
            <BarChart3 size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Analytics Workbench</span>
          </NavLink>
          <NavLink to="/chart-studio" className={({ isActive }) => linkClass(isActive)}>
            <BarChart3 size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Chart Studio</span>
          </NavLink>
          <NavLink to="/notebook-studio" className={({ isActive }) => linkClass(isActive)}>
            <NotebookTabs size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Notebook Studio</span>
          </NavLink>
        </NavGroup>

        <NavGroup label="Model Lifecycle">
          <NavLink to="/model-diagnostics" className={({ isActive }) => linkClass(isActive)}>
            <LineChart size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Model Diagnostics</span>
          </NavLink>
          <NavLink to="/model-document-studio" className={({ isActive }) => linkClass(isActive)}>
            <BookOpenCheck size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Model Documentation Studio</span>
          </NavLink>
          <NavLink to="/credit-risk-studio" className={({ isActive }) => linkClass(isActive)}>
            <Landmark size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Credit Risk Studio</span>
          </NavLink>
        </NavGroup>

        <NavGroup label="Current Project" detail={displayedProjectName}>
          {projectContextReady ? (
            <NavLink to="/project-overview" className={({ isActive }) => linkClass(isActive)}>
              <Gauge size={17} className="shrink-0" />
              <span className="min-w-0 flex-1 truncate">Overview</span>
            </NavLink>
          ) : (
            <div className="flex min-h-9 items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium text-slate-400" aria-disabled="true">
              <Gauge size={17} className="shrink-0" />
              <span className="min-w-0 flex-1 truncate">Loading project context...</span>
            </div>
          )}

          <button
            type="button"
            className="flex min-h-9 w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium text-slate-200 transition hover:bg-white/10 hover:text-white"
            onClick={() => setWorkflowOpen((current) => !current)}
          >
            {workflowOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            <Workflow size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Workflow</span>
          </button>

          {workflowOpen && projectContextReady && (
            <div className="grid gap-1">
              {workflowSteps.map((step, index) => {
                const active = normalizedPathname === normalizeWorkflowRoute(step.route);
                const targetPath = displayedProjectType === "predictive-modeling"
                  ? projectWorkflowNavigationPath({
                      targetPath: step.route,
                      routeProjectId,
                      projectId: displayedProjectId,
                      projectName: displayedProjectName,
                      projectType: displayedProjectType,
                    })
                  : step.route;
                const optimizationStatus = projectType === "optimization"
                  ? optimizationWorkflowStepStatus(optimizationState, index + 1, { current: active, storeComplete: step.status === "complete" })
                  : null;
                return <NavLink key={step.id} to={targetPath} className={() => linkClass(active, true)}>
                  <span className={`h-2 w-2 shrink-0 rounded-full ${optimizationStatus === "Evidence" ? "bg-emerald-400 ring-2 ring-emerald-400/20" : optimizationStatus === "Complete" ? "bg-teal-400 ring-2 ring-teal-400/20" : optimizationStatus === "Current" ? "bg-blue-400 ring-2 ring-blue-400/20" : optimizationStatus === "Blocked" ? "bg-amber-400 ring-2 ring-amber-400/20" : statusClass(step.status)}`} />
                  <span className="min-w-0 flex-1 truncate" title={step.label}>{step.label}</span>
                  {optimizationStatus && <span className={`shrink-0 rounded px-1.5 py-0.5 text-[8px] font-semibold uppercase ${optimizationStatusClass(optimizationStatus)}`}>{optimizationStatus}</span>}
                </NavLink>;
              })}
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

        <NavGroup label="Administration">
          <NavLink to="/account" className={({ isActive }) => linkClass(isActive)}>
            <UserCircle size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Account</span>
          </NavLink>
          <NavLink to="/admin/users" className={({ isActive }) => linkClass(isActive)}>
            <Users size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">User Administration</span>
          </NavLink>
          <NavLink to="/admin" className={({ isActive }) => linkClass(isActive)}>
            <ShieldCheck size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Admin Console</span>
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => linkClass(isActive)}>
            <Settings2 size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">Settings</span>
          </NavLink>
          <NavLink to="/system/diagnostics" className={({ isActive }) => linkClass(isActive)}>
            <Activity size={17} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">System Diagnostics</span>
          </NavLink>
        </NavGroup>
      </nav>
    </aside>
  );
}

function NavGroup({ label, detail, children }: { label: string; detail?: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-1.5">
      <div className="px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</div>
      {detail && (
        <div
          className="px-3 text-[11px] font-medium leading-4 text-slate-500"
          data-testid={label === "Current Project" ? "sidebar-current-project" : undefined}
        >
          {detail}
        </div>
      )}
      {children}
    </section>
  );
}

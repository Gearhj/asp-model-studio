import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BarChart3,
  Beaker,
  BookOpenCheck,
  Boxes,
  ChartNoAxesCombined,
  ChevronLeft,
  ChevronRight,
  Database,
  FileCode2,
  FlaskConical,
  Cpu,
  FolderKanban,
  GitBranch,
  Home,
  Menu,
  Microscope,
  Network,
  Orbit,
  Settings2,
  ShieldCheck,
  Trophy,
  Users,
  Workflow,
  X,
} from "lucide-react";
import BrandLogo from "./BrandLogo";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { isSportsWorkflow, sportsWorkflowForId } from "../sports/sportsConfig";

type NavItem = { to: string; label: string; icon: LucideIcon };

const NAV_GROUPS: Array<{ label: string; items: NavItem[] }> = [
  {
    label: "Core",
    items: [
      { to: "/dashboard", label: "Studio Home", icon: Home },
      { to: "/projects/open", label: "Sports Projects", icon: FolderKanban },
      { to: "/templates", label: "Sports Workflows", icon: Trophy },
      { to: "/data-warehouse", label: "Data Warehouse", icon: Database },
      { to: "/player-team-state", label: "Player & Team State", icon: Activity },
      { to: "/participation-usage", label: "Participation & Usage", icon: Users },
      { to: "/model-laboratory", label: "Model Laboratory", icon: FlaskConical },
      { to: "/pa-modeling-cockpit", label: "PA Modeling Cockpit", icon: Cpu },
      { to: "/simulation-studio", label: "Simulation Studio", icon: Orbit },
      { to: "/evaluation-calibration", label: "Evaluation & Calibration", icon: ChartNoAxesCombined },
      { to: "/model-graph", label: "Model Graph", icon: GitBranch },
      { to: "/registry-deployment", label: "Registry & Deployment", icon: Boxes },
      { to: "/forward-monitoring", label: "Forward Monitoring", icon: Activity },
    ],
  },
  {
    label: "Research Tools",
    items: [
      { to: "/research-tools", label: "Research Tools", icon: Microscope },
      { to: "/analytics", label: "Analytics Workbench", icon: Beaker },
      { to: "/sql-lab", label: "SQL Lab", icon: FileCode2 },
      { to: "/visualization-studio", label: "Visualization Studio", icon: BarChart3 },
      { to: "/model-documentation", label: "Model Documentation", icon: BookOpenCheck },
    ],
  },
  {
    label: "Administration",
    items: [
      { to: "/data-sources-rights", label: "Data Sources & Rights", icon: ShieldCheck },
      { to: "/users-settings", label: "Users & Settings", icon: Users },
    ],
  },
];

export default function Sidebar() {
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [compact, setCompact] = useState(() => localStorage.getItem("asp-sidebar-mode") === "compact");
  const projectName = useWorkflowStore((state) => state.projectName);
  const workflowId = useWorkflowStore((state) => state.workflowId);
  const hasSportsProject = isSportsWorkflow(workflowId) && projectName !== "Untitled Sports Project";
  const workflow = sportsWorkflowForId(workflowId);

  useEffect(() => setMobileOpen(false), [location.pathname]);

  function toggleCompact() {
    setCompact((current) => {
      localStorage.setItem("asp-sidebar-mode", current ? "expanded" : "compact");
      return !current;
    });
  }

  return (
    <>
      <div className="fixed inset-x-0 top-0 z-40 flex h-16 items-center justify-between border-b border-white/10 bg-[#071526] px-4 shadow-lg lg:hidden">
        <BrandLogo size="sm" variant="dark" showSubtitle={false} />
        <button type="button" onClick={() => setMobileOpen(true)} className="grid h-10 w-10 place-items-center rounded-xl border border-white/10 bg-white/5 text-white" aria-label="Open navigation">
          <Menu size={21} />
        </button>
      </div>

      {mobileOpen && <button type="button" className="fixed inset-0 z-40 bg-slate-950/65 backdrop-blur-sm lg:hidden" onClick={() => setMobileOpen(false)} aria-label="Close navigation overlay" />}

      <aside className={`fixed inset-y-0 left-0 z-50 flex w-[min(88vw,300px)] flex-col border-r border-white/10 bg-[#071526] shadow-2xl transition-transform duration-200 lg:sticky lg:top-0 lg:h-screen lg:shrink-0 lg:translate-x-0 ${mobileOpen ? "translate-x-0" : "-translate-x-full"} ${compact ? "lg:w-[82px]" : "lg:w-[278px]"}`}>
        <div className={`flex min-h-[76px] items-center border-b border-white/10 ${compact ? "justify-center px-3" : "justify-between px-4"}`}>
          <BrandLogo size="sm" variant={compact ? "icon" : "dark"} showSubtitle={!compact} />
          <button type="button" onClick={() => setMobileOpen(false)} className="grid h-9 w-9 place-items-center rounded-lg text-slate-300 hover:bg-white/10 hover:text-white lg:hidden" aria-label="Close navigation"><X size={19} /></button>
          {!compact && <button type="button" onClick={toggleCompact} className="hidden h-9 w-9 place-items-center rounded-lg text-slate-400 hover:bg-white/10 hover:text-white lg:grid" aria-label="Collapse navigation"><ChevronLeft size={18} /></button>}
          {compact && <button type="button" onClick={toggleCompact} className="absolute -right-3 top-6 hidden h-7 w-7 place-items-center rounded-full border border-slate-700 bg-[#0c2037] text-slate-300 shadow-lg lg:grid" aria-label="Expand navigation"><ChevronRight size={15} /></button>}
        </div>

        <nav className={`flex-1 space-y-6 overflow-y-auto py-5 ${compact ? "px-2" : "px-3"}`} aria-label="Primary navigation">
          {hasSportsProject && (
            <NavSection label="Current Project" compact={compact}>
              <div className={`${compact ? "hidden" : "mx-2 mb-2 rounded-xl border border-cyan-300/10 bg-cyan-300/[0.06] px-3 py-2"}`}>
                <div className="truncate text-sm font-semibold text-white">{projectName}</div>
                <div className="mt-0.5 text-xs text-cyan-200">{workflow.league} · {workflow.status === "ACTIVE WORKFLOW" ? "Active" : "Foundation"}</div>
              </div>
              <NavigationLink item={{ to: "/project-overview", label: "Project Overview", icon: Network }} compact={compact} />
              <NavigationLink item={{ to: `/workflows/${workflow.key}`, label: `${workflow.league} Workflow`, icon: Workflow }} compact={compact} />
            </NavSection>
          )}

          {NAV_GROUPS.map((group) => (
            <NavSection key={group.label} label={group.label} compact={compact}>
              {group.items.map((item) => <NavigationLink key={item.to} item={item} compact={compact} />)}
            </NavSection>
          ))}
        </nav>

        <div className={`border-t border-white/10 p-3 ${compact ? "text-center" : ""}`}>
          <div className={`rounded-xl border border-teal-300/10 bg-teal-300/[0.06] p-3 ${compact ? "grid place-items-center" : ""}`}>
            <span className="inline-flex h-2 w-2 rounded-full bg-teal-300 shadow-[0_0_10px_rgba(94,234,212,.8)]" />
            {!compact && <><div className="mt-2 text-xs font-semibold uppercase tracking-[0.12em] text-teal-200">Phase 1 workspace</div><div className="mt-1 text-xs leading-5 text-slate-400">Local · isolated · authenticated</div></>}
          </div>
        </div>
      </aside>
    </>
  );
}

function NavSection({ label, compact, children }: { label: string; compact: boolean; children: React.ReactNode }) {
  return <section><div className={`mb-2 px-3 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 ${compact ? "sr-only" : ""}`}>{label}</div><div className="grid gap-1">{children}</div></section>;
}

function NavigationLink({ item, compact }: { item: NavItem; compact: boolean }) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      title={compact ? item.label : undefined}
      className={({ isActive }) => `relative flex min-h-10 items-center rounded-xl text-[13.5px] font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 ${compact ? "justify-center px-2" : "gap-3 px-3"} ${isActive ? "bg-cyan-300/[0.12] text-white before:absolute before:left-0 before:top-2 before:h-[calc(100%-1rem)] before:w-1 before:rounded-full before:bg-cyan-300" : "text-slate-300 hover:bg-white/[0.07] hover:text-white"}`}
    >
      <Icon size={17} className="shrink-0" />
      {!compact && <span>{item.label}</span>}
    </NavLink>
  );
}

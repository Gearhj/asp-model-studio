import { NavLink } from "react-router-dom";
import {
  BarChart3,
  BrainCircuit,
  BriefcaseBusiness,
  ClipboardList,
  Database,
  FileText,
  FileClock,
  FlaskConical,
  Gauge,
  LineChart,
  Microscope,
  NotebookTabs,
  UploadCloud,
  ScanSearch,
  Settings2,
  Shuffle,
  SlidersHorizontal,
} from "lucide-react";
import { useWorkflowStore } from "../state/useWorkflowStore";
import BrandLogo from "./BrandLogo";

const items = [
  { to: "/workbench", label: "AI Workbench", icon: BrainCircuit, id: "workbench" },
  { to: "/experiments", label: "Experiments", icon: FlaskConical, id: "experiments" },
  { to: "/journal", label: "Decision Journal", icon: FileClock, id: "journal" },
  { to: "/governance-report", label: "Governance Report", icon: FileText, id: "governance-report" },
  { to: "/notebook-export", label: "Notebook Export", icon: NotebookTabs, id: "notebook-export" },
  { to: "/dashboard", label: "Atlas Home", icon: Gauge, id: "dashboard" },
  { to: "/step00", label: "Project Context", icon: BriefcaseBusiness, id: "step00" },
  { to: "/step01", label: "Data Acquisition", icon: Database, id: "step01" },
  { to: "/step01b", label: "Credit Bureau Review", icon: ClipboardList, id: "step01b" },
  { to: "/step02", label: "EDA", icon: BarChart3, id: "step02" },
  { to: "/step03", label: "Outliers", icon: ScanSearch, id: "step03" },
  { to: "/step04", label: "Missing Values", icon: ClipboardList, id: "step04" },
  { to: "/step05", label: "Feature Engineering", icon: Settings2, id: "step05" },
  { to: "/step06", label: "Balance & Split", icon: Shuffle, id: "step06" },
  { to: "/step07", label: "Model Training", icon: SlidersHorizontal, id: "step07" },
  { to: "/step08", label: "Evaluation", icon: LineChart, id: "step08" },
  { to: "/step09", label: "Interpretation", icon: Microscope, id: "step09" },
  { to: "/step10", label: "Scoring", icon: UploadCloud, id: "step10" },
  { to: "/step11", label: "Model Development Document", icon: FileText, id: "step11" },
] as const;

export default function Sidebar() {
  const steps = useWorkflowStore((state) => state.steps);

  return (
    <aside className="hidden w-60 shrink-0 border-r border-slate-900 bg-[#071526] shadow-[1px_0_0_rgba(15,23,42,0.2)] lg:block">
      <div className="border-b border-white/10 px-4 py-4">
        <BrandLogo size="sm" variant="dark" showSubtitle />
      </div>

      <nav className="flex flex-col gap-1.5 px-3 py-4">
        {items.map((item) => {
          const Icon = item.icon;
          const done = steps[item.id as keyof typeof steps] === "completed";

          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                [
                  "flex min-h-10 items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
                  isActive
                    ? "bg-blue-600 text-white shadow-sm"
                    : "text-slate-200 hover:bg-white/10 hover:text-white",
                ].join(" ")
              }
            >
              <Icon size={17} className="shrink-0" />
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
              {done && <span className="h-2 w-2 rounded-full bg-emerald-400 ring-2 ring-emerald-400/20" />}
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}

import { NavLink } from "react-router-dom";
import {
  BarChart3,
  ClipboardList,
  Database,
  Gauge,
  LineChart,
  Microscope,
  ScanSearch,
  Settings2,
  Shuffle,
  SlidersHorizontal,
} from "lucide-react";
import { useWorkflowStore } from "../state/useWorkflowStore";

const items = [
  { to: "/dashboard", label: "Dashboard", icon: Gauge, id: "dashboard" },
  { to: "/step01", label: "Data Acquisition", icon: Database, id: "step01" },
  { to: "/step02", label: "EDA", icon: BarChart3, id: "step02" },
  { to: "/step03", label: "Outliers", icon: ScanSearch, id: "step03" },
  { to: "/step04", label: "Missing Values", icon: ClipboardList, id: "step04" },
  { to: "/step05", label: "Feature Engineering", icon: Settings2, id: "step05" },
  { to: "/step06", label: "Balance & Split", icon: Shuffle, id: "step06" },
  { to: "/step07", label: "Model Training", icon: SlidersHorizontal, id: "step07" },
  { to: "/step08", label: "Evaluation", icon: LineChart, id: "step08" },
  { to: "/step09", label: "Interpretation", icon: Microscope, id: "step09" },
] as const;

export default function Sidebar() {
  const steps = useWorkflowStore((state) => state.steps);

  return (
    <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white lg:block">
      <div className="border-b border-slate-200 px-5 py-5">
        <div className="text-sm font-semibold text-slate-950">DS Workflow</div>
        <div className="mt-1 text-xs text-slate-500">Regulated ML pipeline</div>
      </div>

      <nav className="flex flex-col gap-1 px-3 py-4">
        {items.map((item) => {
          const Icon = item.icon;
          const done = steps[item.id as keyof typeof steps] === "completed";

          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                [
                  "flex min-h-10 items-center gap-3 rounded-md px-3 py-2 text-sm font-medium",
                  isActive
                    ? "bg-indigo-50 text-indigo-700"
                    : "text-slate-700 hover:bg-slate-50 hover:text-slate-950",
                ].join(" ")
              }
            >
              <Icon size={17} className="shrink-0" />
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
              {done && <span className="h-2 w-2 rounded-full bg-emerald-500" />}
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}

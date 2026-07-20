import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BrainCircuit, Route, TerminalSquare } from "lucide-react";
import { logDecision } from "../lib/decisionJournal";
import { loadModelingMode, modeDescription, saveModelingMode, type ModelingMode } from "../lib/modelingMode";

const guidedLinks = [
  { to: "/dashboard", label: "Atlas Home" },
  { to: "/step00", label: "Context" },
  { to: "/step07", label: "Train" },
  { to: "/step08", label: "Evaluate" },
];

const advancedLinks = [
  { to: "/workbench", label: "Workbench" },
  { to: "/experiments", label: "Experiments" },
  { to: "/notebook-export", label: "Notebook" },
  { to: "/governance-report", label: "Governance" },
];

export default function ModeSwitcher() {
  const [mode, setMode] = useState<ModelingMode>(() => loadModelingMode());

  useEffect(() => {
    const refresh = () => setMode(loadModelingMode());
    window.addEventListener("modeling-mode-updated", refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener("modeling-mode-updated", refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  const updateMode = (next: ModelingMode) => {
    if (next === mode) return;
    saveModelingMode(next);
    setMode(next);
    logDecision({
      workflowStep: "Application Shell",
      actionType: "workflow_setting_changed",
      subject: "Dual-mode modeling mode",
      previousValue: mode,
      newValue: next,
      systemRecommendation:
        "Use Guided mode for workflow guardrails and Advanced mode for Python, experiments, notebook export, and governance documentation without resetting state.",
      followStatus: "not_applicable",
    });
  };

  const links = mode === "advanced" ? advancedLinks : guidedLinks;

  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/70 px-3 py-2 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            {mode === "advanced" ? <TerminalSquare size={13} /> : <Route size={13} />}
            Dual-mode modeling
          </div>
          <div className="mt-1 hidden text-xs font-medium text-slate-700 2xl:block">{modeDescription(mode)}</div>
        </div>
        <div className="inline-flex rounded-lg border border-slate-200 bg-slate-100 p-1">
          <button
            type="button"
            className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${
              mode === "guided" ? "bg-white text-slate-950 shadow-sm" : "text-slate-600 hover:text-slate-950"
            }`}
            onClick={() => updateMode("guided")}
          >
            Guided
          </button>
          <button
            type="button"
            className={`inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-semibold transition ${
              mode === "advanced" ? "bg-slate-950 text-white shadow-sm" : "text-slate-600 hover:text-slate-950"
            }`}
            onClick={() => updateMode("advanced")}
          >
            <BrainCircuit size={13} />
            Power User
          </button>
        </div>
      </div>
      <div className="mt-2 hidden flex-wrap gap-1.5 2xl:flex">
        {links.map((link) => (
          <Link
            key={link.to}
            to={link.to}
            className="rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 hover:border-slate-300 hover:text-slate-950"
          >
            {link.label}
          </Link>
        ))}
      </div>
    </div>
  );
}

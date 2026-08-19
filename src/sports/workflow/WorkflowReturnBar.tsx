// Persistent "Return to MLB Workflow" breadcrumb shown on any module opened from the guided
// workflow (detected via ?from=mlb-workflow&step=N). One component preserves context for every
// deep-linked module — the user is never stranded.
import { Link, useLocation } from "react-router-dom";
import { ArrowLeft, Workflow } from "lucide-react";
import { MLB_WORKFLOW } from "../sportsConfig";

export default function WorkflowReturnBar() {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  if (params.get("from") !== "mlb-workflow") return null;
  const step = Number(params.get("step")) || 0;
  const stepDef = MLB_WORKFLOW.steps.find((s) => s.number === step);
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-cyan-200 bg-cyan-50/70 px-4 py-2.5">
      <div className="flex min-w-0 items-center gap-2 text-sm text-slate-700">
        <Workflow size={16} className="shrink-0 text-cyan-700" />
        <span className="truncate">
          <span className="font-semibold text-slate-900">MLB Workflow</span>
          {stepDef ? <> <span className="text-slate-400">›</span> Step {step} <span className="text-slate-400">›</span> <span className="font-semibold text-slate-900">{stepDef.title}</span></> : null}
        </span>
      </div>
      <Link to={`/workflows/mlb${step ? `?step=${step}` : ""}`} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-cyan-300 bg-white px-3 py-1.5 text-sm font-semibold text-cyan-800 hover:bg-cyan-50">
        <ArrowLeft size={14} /> Return to MLB Workflow
      </Link>
    </div>
  );
}

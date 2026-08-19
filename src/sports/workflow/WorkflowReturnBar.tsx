// Persistent "Return to MLB Workflow" breadcrumb shown on any module opened from the program
// workflow (detected via ?from=mlb-workflow&stage=N). One component preserves context for every
// deep-linked module — the user is never stranded. Accepts old ?step=N and maps it forward.
import { Link, useLocation } from "react-router-dom";
import { ArrowLeft, Workflow } from "lucide-react";
import { PROGRAM_STAGES, LEGACY_STEP_TO_STAGE } from "./workflowState";

export default function WorkflowReturnBar() {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  if (params.get("from") !== "mlb-workflow") return null;
  const legacyStep = Number(params.get("step")) || 0;
  const stage = Number(params.get("stage")) || (legacyStep ? LEGACY_STEP_TO_STAGE[legacyStep] || 0 : 0);
  const stageDef = PROGRAM_STAGES.find((s) => s.number === stage);
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-cyan-200 bg-cyan-50/70 px-4 py-2.5">
      <div className="flex min-w-0 items-center gap-2 text-sm text-slate-700">
        <Workflow size={16} className="shrink-0 text-cyan-700" />
        <span className="truncate">
          <span className="font-semibold text-slate-900">MLB Program</span>
          {stageDef ? <> <span className="text-slate-400">›</span> Stage {stage} <span className="text-slate-400">›</span> <span className="font-semibold text-slate-900">{stageDef.title}</span></> : null}
        </span>
      </div>
      <Link to={`/workflows/mlb${stage ? `?stage=${stage}` : ""}`} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-cyan-300 bg-white px-3 py-1.5 text-sm font-semibold text-cyan-800 hover:bg-cyan-50">
        <ArrowLeft size={14} /> Return to MLB Workflow
      </Link>
    </div>
  );
}

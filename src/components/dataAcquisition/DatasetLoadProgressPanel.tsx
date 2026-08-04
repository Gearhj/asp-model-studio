// Part H1: staged dataset-load progress.
//
// Milestones are discrete and reflect real observed backend work. There is no
// synthetic percentage anywhere in this component: the backend cannot report
// intra-stage completion, so segmented milestone status is shown instead of a
// continuous bar that would imply precision ATLAS does not have.
import { Check, CircleDashed, Loader2, TriangleAlert } from "lucide-react";
import {
  DATASET_LOAD_STAGES,
  type DatasetLoadProgress,
  resolveStageStates,
  summarizeLoadProgress,
  type StageState,
} from "../../lib/dataAcquisitionLifecycle";

const stateStyles: Record<StageState, { row: string; icon: string }> = {
  pending: { row: "border-slate-200 bg-white text-slate-500", icon: "text-slate-400" },
  active: { row: "border-blue-400 bg-blue-50 text-blue-950", icon: "text-blue-700" },
  complete: { row: "border-emerald-300 bg-emerald-50 text-emerald-950", icon: "text-emerald-700" },
  failed: { row: "border-red-300 bg-red-50 text-red-950", icon: "text-red-700" },
};

/** Text label per state, so the track is understandable without color (Part H2/7). */
const stateLabels: Record<StageState, string> = {
  pending: "Pending",
  active: "In progress",
  complete: "Complete",
  failed: "Failed",
};

function StageIcon({ state }: { state: StageState }) {
  const className = `${stateStyles[state].icon} shrink-0`;
  if (state === "complete") return <Check size={14} className={className} aria-hidden="true" />;
  if (state === "failed") return <TriangleAlert size={14} className={className} aria-hidden="true" />;
  if (state === "active") return <Loader2 size={14} className={`${className} motion-safe:animate-spin`} aria-hidden="true" />;
  return <CircleDashed size={14} className={className} aria-hidden="true" />;
}

export default function DatasetLoadProgressPanel({ progress }: { progress: DatasetLoadProgress }) {
  if (progress.phase === "idle") return null;

  const states = resolveStageStates(progress);
  const summary = summarizeLoadProgress(progress);

  if (progress.phase === "loaded") {
    return (
      <details
        className="mt-4 rounded-xl border border-emerald-300 bg-emerald-50/70"
        data-testid="dataset-load-progress"
        data-load-phase={progress.phase}
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">
          <span className="flex min-w-0 items-center gap-3">
            <span className="rounded-full bg-emerald-100 p-1.5 text-emerald-700" aria-hidden="true">
              <Check size={15} />
            </span>
            <span>
              <span className="block text-sm font-semibold text-emerald-950">Dataset loaded and verified</span>
              <span className="mt-0.5 block text-xs text-emerald-800">{summary.completed} of {summary.total} checks completed</span>
            </span>
          </span>
          <span className="shrink-0 text-xs font-semibold text-emerald-800">View load details</span>
        </summary>
        <div className="border-t border-emerald-200 bg-white px-4 py-3">
          <ol className="grid gap-1.5" data-testid="dataset-load-completed-details">
            {DATASET_LOAD_STAGES.map((stage, index) => (
              <li
                key={stage}
                className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-medium ${stateStyles[states[index]].row}`}
                data-stage={stage}
                data-stage-state={states[index]}
              >
                <StageIcon state={states[index]} />
                <span className="min-w-0 flex-1 truncate">{stage}</span>
                <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide opacity-80">
                  {stateLabels[states[index]]}
                </span>
              </li>
            ))}
          </ol>
        </div>
      </details>
    );
  }

  return (
    <div
      className="mt-4 rounded-xl border border-slate-300 bg-white p-4"
      data-testid="dataset-load-progress"
      data-load-phase={progress.phase}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-bold uppercase tracking-wide text-slate-600">Dataset load progress</div>
        <div className="text-xs font-semibold text-slate-700" data-testid="dataset-load-milestone-count">
          {summary.completed} of {summary.total} milestones
        </div>
      </div>

      {/* Segmented milestone track -- one segment per real stage, never a percentage. */}
      <div className="mt-3 flex gap-1" aria-hidden="true">
        {states.map((state, index) => (
          <div
            key={DATASET_LOAD_STAGES[index]}
            className={`h-1.5 flex-1 rounded-full ${
              state === "complete"
                ? "bg-emerald-500"
                : state === "active"
                  ? "bg-blue-500"
                  : state === "failed"
                    ? "bg-red-500"
                    : "bg-slate-200"
            }`}
          />
        ))}
      </div>

      <ol className="mt-3 grid gap-1.5">
        {DATASET_LOAD_STAGES.map((stage, index) => (
          <li
            key={stage}
            className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${stateStyles[states[index]].row}`}
            data-stage={stage}
            data-stage-state={states[index]}
          >
            <StageIcon state={states[index]} />
            <span className="min-w-0 flex-1 truncate">{stage}</span>
            <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide opacity-80">
              {stateLabels[states[index]]}
            </span>
          </li>
        ))}
      </ol>

      {/* Announces the active stage without moving focus. */}
      <p className="mt-3 text-xs text-slate-600" role="status" aria-live="polite" data-testid="dataset-load-status">
        {summary.label}
      </p>

      {progress.phase === "failed" && progress.error && (
        <p className="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-900" data-testid="dataset-load-error">
          {progress.error}
        </p>
      )}
    </div>
  );
}

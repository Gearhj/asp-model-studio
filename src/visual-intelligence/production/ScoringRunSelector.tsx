// ATLAS Visual Intelligence Production Integration, Phase F -- reusable
// Scoring Run selector. Used by the production panels (Step02/Step08) AND by
// Step10's history panel's "Compare" flow, so run-selection UI is defined
// exactly once.
import { useEffect, useMemo, useState } from "react";
import { listScoringRuns, type ScoringRunStatus, type ScoringRunSummary } from "../../scoring-runs/scoringRunClient";
import type { ProblemType, ScoringPartition } from "../types";

export type ScoringRunSelectorProps = {
  projectId: string;
  value: string | null;
  onChange: (scoringRunId: string | null) => void;
  problemType?: ProblemType | null;
  modelId?: string;
  compareValue?: string[];
  onCompareChange?: (ids: string[]) => void;
  compareEnabled?: boolean;
};

function primaryMetric(run: ScoringRunSummary): string {
  const metrics = run.metrics?.metrics;
  if (!metrics) return "-";
  if (typeof metrics.rmse === "number") return `RMSE ${metrics.rmse.toFixed(3)}`;
  if (typeof metrics.auc === "number") return `AUC ${metrics.auc.toFixed(3)}`;
  if (typeof metrics.accuracy === "number") return `Acc ${(metrics.accuracy * 100).toFixed(1)}%`;
  return "-";
}

export default function ScoringRunSelector({ projectId, value, onChange, problemType, modelId, compareValue, onCompareChange, compareEnabled }: ScoringRunSelectorProps) {
  const [runs, setRuns] = useState<ScoringRunSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [partitionFilter, setPartitionFilter] = useState<ScoringPartition | "">("");
  const [statusFilter, setStatusFilter] = useState<ScoringRunStatus | "">("");
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    listScoringRuns(projectId, {
      partition: partitionFilter || undefined,
      status: statusFilter || undefined,
      modelId,
      problemType: problemType ?? undefined,
      includeArchived: showArchived,
      limit: 100,
    })
      .then((result) => !cancelled && setRuns(result))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Failed to load scoring runs."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [projectId, partitionFilter, statusFilter, showArchived, modelId, problemType]);

  const sorted = useMemo(() => [...runs].sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1)), [runs]);
  const currentIndex = useMemo(() => sorted.findIndex((r) => r.scoringRunId === value), [sorted, value]);

  return (
    <div className="space-y-2 rounded-md border border-slate-200 bg-white p-3" data-testid="scoring-run-selector">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label className="grid gap-0.5">
          <span className="font-semibold uppercase text-slate-500">Partition</span>
          <select data-testid="scoring-run-partition-filter" className="rounded border border-slate-300 px-2 py-1" value={partitionFilter} onChange={(e) => setPartitionFilter(e.target.value as ScoringPartition | "")}>
            <option value="">All</option>
            <option value="train">TRAIN</option>
            <option value="test">TEST</option>
            <option value="oot">OOT</option>
          </select>
        </label>
        <label className="grid gap-0.5">
          <span className="font-semibold uppercase text-slate-500">Status</span>
          <select className="rounded border border-slate-300 px-2 py-1" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as ScoringRunStatus | "")}>
            <option value="">All</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </label>
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Show archived
        </label>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
            disabled={currentIndex <= 0}
            onClick={() => onChange(sorted[currentIndex - 1]?.scoringRunId ?? null)}
            aria-label="Previous scoring run"
          >
            ← Prev
          </button>
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
            disabled={currentIndex === -1 || currentIndex >= sorted.length - 1}
            onClick={() => onChange(sorted[currentIndex + 1]?.scoringRunId ?? null)}
            aria-label="Next scoring run"
          >
            Next →
          </button>
        </div>
      </div>

      {error ? <p className="text-xs text-rose-700">{error}</p> : null}
      {loading ? (
        <p role="status" aria-live="polite" className="text-xs text-slate-500">Loading scoring runs...</p>
      ) : sorted.length === 0 ? (
        <p className="text-xs text-slate-500">No durable scoring runs found for the current filters. Score TRAIN/TEST/OOT from the Scoring page to create one.</p>
      ) : (
        <ul className="max-h-64 divide-y divide-slate-100 overflow-y-auto text-xs" role="listbox" aria-label="Scoring runs">
          {sorted.map((run) => (
            <li key={run.scoringRunId} className={`flex items-center gap-2 py-1.5 ${run.scoringRunId === value ? "bg-blue-50" : ""}`}>
              {compareEnabled ? (
                <input
                  type="checkbox"
                  aria-label={`Select ${run.scoringRunId} for comparison`}
                  data-testid="scoring-run-compare-checkbox"
                  checked={(compareValue ?? []).includes(run.scoringRunId)}
                  onChange={(e) => {
                    if (!onCompareChange) return;
                    const next = e.target.checked
                      ? [...(compareValue ?? []), run.scoringRunId]
                      : (compareValue ?? []).filter((id) => id !== run.scoringRunId);
                    onCompareChange(next);
                  }}
                />
              ) : null}
              <button
                type="button"
                role="option"
                aria-selected={run.scoringRunId === value}
                data-testid="scoring-run-option"
                className={`flex-1 rounded px-2 py-1 text-left hover:bg-slate-50 ${run.scoringRunId === value ? "font-semibold text-blue-900" : "text-slate-700"}`}
                onClick={() => onChange(run.scoringRunId)}
              >
                <span className="font-semibold uppercase">{run.partition}</span>{" "}
                <span className="text-slate-500">{new Date(run.createdAt).toLocaleString()}</span>{" "}
                <span className="text-slate-500">· {run.modelId ?? "model"}</span>{" "}
                <span className="text-slate-500">· {run.rowCount?.toLocaleString() ?? "-"} rows</span>{" "}
                <span className="text-slate-500">· {primaryMetric(run)}</span>{" "}
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${run.status === "completed" ? "bg-emerald-100 text-emerald-800" : run.status === "failed" ? "bg-rose-100 text-rose-800" : "bg-slate-100 text-slate-700"}`}>{run.status}</span>{" "}
                {run.registrationStatus === "registered" ? (
                  <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-indigo-800">registered</span>
                ) : null}
                {run.archivedAt ? <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-600">archived</span> : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

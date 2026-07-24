// ATLAS Visual Intelligence Production Integration, Phase G -- durable Scoring
// Run comparison. Reuses the existing GET /api/scoring-runs/compare endpoint
// (built in the Persistent Scoring Runs phase) rather than recomputing
// comparisons client-side. Compatibility (project/problemType/target) is
// already enforced server-side by that endpoint's per-run authorization;
// this panel additionally warns, client-side, when the selected runs differ
// in model or partition, since those are legitimate but easily-misread
// comparisons (Phase G requirement 3: distinguish model-performance
// difference from dataset/partition difference).
import { useState } from "react";
import ScoringRunSelector from "./ScoringRunSelector";
import { compareScoringRuns } from "../../scoring-runs/scoringRunClient";

type CompareRow = {
  scoringRunId: string;
  partition: string;
  modelId: string | null;
  modelVersion: string | null;
  createdAt: string;
  rowCount: number | null;
  metrics: Record<string, number | null> | null;
  psi: { value?: number; status?: string } | null;
};

export default function RunComparePanel({ projectId, anchorRunId }: { projectId: string; anchorRunId: string | null }) {
  const [selected, setSelected] = useState<string[]>(anchorRunId ? [anchorRunId] : []);
  const [rows, setRows] = useState<CompareRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleCompare() {
    if (selected.length < 2) {
      setError("Select at least two scoring runs to compare.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await compareScoringRuns(selected);
      setRows(result.runs as CompareRow[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Comparison failed.");
    } finally {
      setLoading(false);
    }
  }

  const distinctModels = rows ? new Set(rows.map((r) => r.modelId)).size : 0;
  const distinctPartitions = rows ? new Set(rows.map((r) => r.partition)).size : 0;

  return (
    <div className="space-y-2 rounded-md border border-slate-200 bg-white p-3" data-testid="va-compare-panel">
      <p className="text-xs text-slate-600">Select 2-10 scoring runs to compare threshold-independent metrics, PSI, and row counts side by side.</p>
      <ScoringRunSelector projectId={projectId} value={null} onChange={() => {}} compareEnabled compareValue={selected} onCompareChange={setSelected} />
      <button type="button" data-testid="va-run-compare" className="atlas-secondary-button text-xs" onClick={handleCompare} disabled={loading}>
        {loading ? "Comparing..." : `Compare ${selected.length} runs`}
      </button>
      {error ? <p className="text-xs text-rose-700">{error}</p> : null}
      {rows ? (
        <div className="overflow-x-auto">
          {distinctModels > 1 ? (
            <p className="mb-2 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800">
              These runs use different models -- differences below may reflect model performance, not just data drift.
            </p>
          ) : null}
          {distinctPartitions > 1 ? (
            <p className="mb-2 rounded border border-blue-200 bg-blue-50 px-2 py-1 text-xs text-blue-800">
              These runs span different partitions -- differences below may reflect dataset/partition distribution, not just model behavior.
            </p>
          ) : null}
          <table className="w-full text-left text-xs" data-testid="va-compare-table">
            <thead>
              <tr className="border-b border-slate-200 text-slate-500">
                <th className="py-1 pr-3">Run</th>
                <th className="py-1 pr-3">Partition</th>
                <th className="py-1 pr-3">Model</th>
                <th className="py-1 pr-3">Created</th>
                <th className="py-1 pr-3">Rows</th>
                <th className="py-1 pr-3">Metrics</th>
                <th className="py-1 pr-3">PSI</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.scoringRunId} className="border-b border-slate-100">
                  <td className="py-1 pr-3 font-mono">{row.scoringRunId}</td>
                  <td className="py-1 pr-3 uppercase">{row.partition}</td>
                  <td className="py-1 pr-3">{row.modelId ?? "-"}</td>
                  <td className="py-1 pr-3">{new Date(row.createdAt).toLocaleString()}</td>
                  <td className="py-1 pr-3">{row.rowCount?.toLocaleString() ?? "-"}</td>
                  <td className="py-1 pr-3">
                    {row.metrics
                      ? Object.entries(row.metrics)
                          .filter(([, v]) => typeof v === "number")
                          .slice(0, 3)
                          .map(([k, v]) => `${k}=${(v as number).toFixed(3)}`)
                          .join(", ") || "-"
                      : "-"}
                  </td>
                  <td className="py-1 pr-3">{row.psi?.value !== undefined ? `${row.psi.value.toFixed(3)} (${row.psi.status})` : "n/a"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

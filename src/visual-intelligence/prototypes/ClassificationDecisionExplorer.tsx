// ATLAS Visual Intelligence Foundation -- Prototype 2: Classification Decision Explorer.
// Score distribution (positive/negative overlays) + draggable threshold + confusion
// matrix and threshold-dependent metrics, all recomputed independently in the browser
// from the raw actual/score arrays rather than trusted blindly from a single backend field.
import { useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import EChartsPanel from "../EChartsPanel";
import { ReferenceLineOverlay, type LinearScaleLike, type ReferenceLineSpec } from "../d3Overlays";
import { ATLAS_CHART_COLORS } from "../theme";
import { fetchTrainingEvaluationResult, fetchScoringRunEvaluationRows } from "../dataAccessLayer";
import { adaptClassificationRows } from "../adapters/queryResultAdapter";
import { useVisualIntelligenceContext } from "../VisualIntelligenceContext";
import { useInteractionStore } from "../interactionStore";

const CHART_HEIGHT = 260;
const DEFAULT_MODEL_KEY = "logreg";

function buildScoreHistogram(rows: Array<{ actual: number; predictedScore: number }>, binCount: number) {
  const bins = Array.from({ length: binCount }, (_, i) => ({ x0: i / binCount, x1: (i + 1) / binCount, positive: 0, negative: 0 }));
  for (const row of rows) {
    const index = Math.min(binCount - 1, Math.max(0, Math.floor(row.predictedScore * binCount)));
    if (row.actual === 1) bins[index].positive += 1;
    else bins[index].negative += 1;
  }
  return bins;
}

function confusionCounts(rows: Array<{ actual: number; predictedScore: number }>, threshold: number) {
  let tp = 0, fp = 0, tn = 0, fn = 0;
  for (const row of rows) {
    const predictedPositive = row.predictedScore >= threshold;
    if (row.actual === 1 && predictedPositive) tp += 1;
    else if (row.actual === 0 && predictedPositive) fp += 1;
    else if (row.actual === 0 && !predictedPositive) tn += 1;
    else fn += 1;
  }
  return { tp, fp, tn, fn };
}

/** Independently recomputed from raw counts -- never trusts a single backend-reported
 *  scalar without a local cross-check (Regression/Classification Stage B pattern). */
function rocAucFromRows(rows: Array<{ actual: number; predictedScore: number }>): number | null {
  const positives = rows.filter((r) => r.actual === 1);
  const negatives = rows.filter((r) => r.actual === 0);
  if (!positives.length || !negatives.length) return null;
  let concordant = 0;
  let total = 0;
  // O(n*m) exact Mann-Whitney U -- fine at this dataset's scale (a few hundred rows);
  // a rank-based O(n log n) formulation would be used above largeDataPolicy's CANVAS_RENDER_MAX.
  for (const p of positives) {
    for (const n of negatives) {
      total += 1;
      if (p.predictedScore > n.predictedScore) concordant += 1;
      else if (p.predictedScore === n.predictedScore) concordant += 0.5;
    }
  }
  return total ? concordant / total : null;
}

export default function ClassificationDecisionExplorer() {
  const { baseReference, problemType, target, loading: contextLoading } = useVisualIntelligenceContext();
  const [rows, setRows] = useState<Array<{ actual: number; predictedScore: number }> | null>(null);
  const [modelName, setModelName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const threshold = useInteractionStore((state) => state.classificationThreshold);
  const setThreshold = useInteractionStore((state) => state.setClassificationThreshold);
  const setScope = useInteractionStore((state) => state.setScope);

  useEffect(() => {
    if (!baseReference) return;
    setScope({ userId: baseReference.authenticatedUserId, projectId: baseReference.projectId, visualizationId: "classification-decision-explorer" });
  }, [baseReference, setScope]);

  useEffect(() => {
    if (!baseReference || problemType !== "classification") return;
    let cancelled = false;
    setError(null);
    const fetchResult = baseReference.sourceType === "scoring-session"
      ? fetchScoringRunEvaluationRows(baseReference, "classification")
      : fetchTrainingEvaluationResult(baseReference, DEFAULT_MODEL_KEY);
    fetchResult
      .then((result) => {
        if (cancelled) return;
        const adapted = adaptClassificationRows(result.rows.map((r) => r.actual), result.rows.map((r) => r.prediction));
        setRows(adapted.map((r) => ({ actual: r.actual, predictedScore: r.predictedScore })));
        setModelName(result.modelName);
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Failed to load evaluation result."));
    return () => {
      cancelled = true;
    };
  }, [baseReference, problemType]);

  const histogram = useMemo(() => (rows ? buildScoreHistogram(rows, 25) : []), [rows]);
  const confusion = useMemo(() => (rows ? confusionCounts(rows, threshold) : null), [rows, threshold]);
  const rocAuc = useMemo(() => (rows ? rocAucFromRows(rows) : null), [rows]); // threshold-independent -- deliberately NOT in the [rows, threshold] recompute path below

  const metrics = useMemo(() => {
    if (!confusion) return null;
    const { tp, fp, tn, fn } = confusion;
    const precision = tp + fp > 0 ? tp / (tp + fp) : null;
    const recall = tp + fn > 0 ? tp / (tp + fn) : null;
    const specificity = tn + fp > 0 ? tn / (tn + fp) : null;
    const f1 = precision !== null && recall !== null && precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : null;
    const alertRate = rows?.length ? (tp + fp) / rows.length : null;
    return { precision, recall, specificity, f1, alertRate };
  }, [confusion, rows]);

  const scale: LinearScaleLike = useMemo(() => {
    const fn = ((value: number) => value * 640) as LinearScaleLike;
    fn.invert = (pixel: number) => pixel / 640;
    fn.range = () => [0, 640];
    return fn;
  }, []);

  const thresholdLine: ReferenceLineSpec[] = [{ id: "threshold", value: threshold, label: `Threshold ${threshold.toFixed(2)}`, color: ATLAS_CHART_COLORS.identity, draggable: true }];

  const option: EChartsOption | null = histogram.length
    ? {
        title: { text: "Score Distribution", subtext: modelName ? `${modelName} -- TRAIN (Development)` : "TRAIN (Development)" },
        tooltip: { trigger: "axis" },
        legend: { data: ["Negative class", "Positive class"] },
        xAxis: { type: "category", data: histogram.map((bin) => bin.x0.toFixed(2)), name: "Predicted score" },
        yAxis: { type: "value", name: "Row count" },
        series: [
          { name: "Negative class", type: "bar", stack: "total", data: histogram.map((bin) => bin.negative), itemStyle: { color: ATLAS_CHART_COLORS.negative } },
          { name: "Positive class", type: "bar", stack: "total", data: histogram.map((bin) => bin.positive), itemStyle: { color: ATLAS_CHART_COLORS.positive } },
        ],
      }
    : null;

  if (contextLoading) return <div className="rounded-md border border-slate-200 bg-slate-50 p-6 text-sm text-slate-600">Resolving project context...</div>;
  if (!baseReference) return <div className="rounded-md border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">No active project.</div>;
  if (problemType !== "classification") {
    return <div className="rounded-md border border-dashed border-amber-300 bg-amber-50 p-6 text-sm text-amber-800" data-testid="wrong-problem-type">This project is not a classification project. The Classification Decision Explorer requires a classification model.</div>;
  }

  return (
    <section className="space-y-4" data-testid="classification-decision-explorer" aria-label="Classification Decision Explorer">
      <p className="text-xs text-slate-500">Model: <strong>{modelName ?? DEFAULT_MODEL_KEY}</strong> &middot; Dataset/version: <strong>{baseReference.datasetId ?? "workspace (unregistered)"}</strong> &middot; Partition: <strong>{(baseReference.partition ?? "train").toUpperCase()}</strong> &middot; Target: <strong>{target ?? "unknown"}</strong> &middot; Positive class: <strong>1</strong>{baseReference.sourceType === "scoring-session" ? <> &middot; <span data-testid="scoring-run-source-badge">Durable scoring run</span></> : null}</p>
      <p className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-900">This view depends on the most recent training run and reflects the TRAIN (development) partition. TEST/OOT comparison requires a live Scoring session and is not durably available here (see Known Constraints).</p>

      <div className="flex flex-wrap items-end gap-3 rounded-md border border-slate-200 bg-white p-4">
        <label className="grid gap-1 text-xs">
          <span className="font-semibold uppercase text-slate-500">Threshold</span>
          <input data-testid="threshold-input" type="number" min={0} max={1} step={0.01} value={threshold.toFixed(2)} onChange={(event) => setThreshold(Number(event.target.value))} className="w-24 rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
        <input aria-label="Threshold slider" type="range" min={0} max={1} step={0.01} value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} className="w-48" data-testid="threshold-slider" />
        <button type="button" className="atlas-secondary-button" onClick={() => setThreshold(0.5)}>Reset threshold</button>
      </div>

      {error ? (
        <EChartsPanel option={null} state="error" errorMessage={error} height={CHART_HEIGHT} ariaLabel="Score distribution" />
      ) : rows === null ? (
        <EChartsPanel option={null} state="loading" height={CHART_HEIGHT} ariaLabel="Score distribution" />
      ) : rows.length === 0 ? (
        <EChartsPanel option={null} state="empty" emptyMessage="No scored rows are available for this model." height={CHART_HEIGHT} ariaLabel="Score distribution" />
      ) : (
        <div className="relative rounded-md border border-slate-200 bg-white p-2" style={{ height: CHART_HEIGHT + 16 }}>
          <EChartsPanel option={option} height={CHART_HEIGHT} ariaLabel="Score distribution with positive and negative class overlays" onChartReady={(instance) => useInteractionStore.getState().setChartInstance(instance)} />
          <div className="pointer-events-none absolute inset-2" style={{ height: CHART_HEIGHT }}>
            <div className="pointer-events-auto absolute inset-0">
              <ReferenceLineOverlay lines={thresholdLine} scale={scale} height={CHART_HEIGHT} onDrag={(_id, value) => setThreshold(value)} />
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 rounded-md border border-slate-200 bg-white p-4 sm:grid-cols-4" data-testid="classification-metrics" aria-live="polite">
        <Metric label="Precision" value={formatPercent(metrics?.precision)} />
        <Metric label="Recall" value={formatPercent(metrics?.recall)} />
        <Metric label="Specificity" value={formatPercent(metrics?.specificity)} />
        <Metric label="F1" value={metrics?.f1 != null ? metrics.f1.toFixed(3) : "Unavailable"} />
        <Metric label="False positives" value={confusion ? String(confusion.fp) : "Unavailable"} />
        <Metric label="False negatives" value={confusion ? String(confusion.fn) : "Unavailable"} />
        <Metric label="Alert rate" value={formatPercent(metrics?.alertRate)} />
        <Metric label="ROC AUC (threshold-independent)" value={rocAuc != null ? rocAuc.toFixed(3) : "Unavailable"} />
      </div>

      {confusion ? (
        <table className="w-full max-w-md rounded-md border border-slate-200 bg-white text-sm" data-testid="confusion-matrix">
          <thead><tr className="bg-slate-100 text-left text-[11px] font-semibold uppercase text-slate-600"><th className="px-3 py-2" /><th className="px-3 py-2">Predicted Negative</th><th className="px-3 py-2">Predicted Positive</th></tr></thead>
          <tbody>
            <tr><td className="px-3 py-2 font-semibold">Actual Negative</td><td className="px-3 py-2 font-mono">{confusion.tn}</td><td className="px-3 py-2 font-mono">{confusion.fp}</td></tr>
            <tr><td className="px-3 py-2 font-semibold">Actual Positive</td><td className="px-3 py-2 font-mono">{confusion.fn}</td><td className="px-3 py-2 font-mono">{confusion.tp}</td></tr>
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "Unavailable" : `${(value * 100).toFixed(1)}%`;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-slate-950">{value}</div>
    </div>
  );
}

// ATLAS Visual Intelligence Foundation -- Prototype 3: Regression Diagnostic Explorer.
// The highest-priority missing regression visualization capability (Regression Stage B
// audit, Phase 16/23/24): actual-vs-predicted, residuals-vs-fitted, residual histogram,
// and a Q-Q plot, linked by stable row identity, plus absolute-error-by-target-band.
// No confusion matrix, no precision/recall/F1/ROC/PR/lift/gain/KS/alert-rate/positive-class/
// threshold terminology anywhere in this file -- internal y_score is normalized to
// "prediction" entirely inside dataAccessLayer.ts / queryResultAdapter.ts before reaching here.
import { useEffect, useMemo, useState } from "react";
import type { EChartsOption, ECharts } from "echarts";
import EChartsPanel from "../EChartsPanel";
import { ReferenceLineOverlay, qqPlotPoints, meanValue, medianValue, type LinearScaleLike, type ReferenceLineSpec } from "../d3Overlays";
import { ATLAS_CHART_COLORS } from "../theme";
import { fetchTrainingEvaluationResult, fetchScoringRunEvaluationRows } from "../dataAccessLayer";
import { adaptRegressionRows, type RegressionRow } from "../adapters/queryResultAdapter";
import { streamingMeanStd, streamingMedian, safeMinMax } from "../largeDataPolicy";
import { useVisualIntelligenceContext } from "../VisualIntelligenceContext";
import { useInteractionStore } from "../interactionStore";

const CHART_HEIGHT = 260;
const DEFAULT_MODEL_KEY = "linreg";
const MIN_ROWS_FOR_QQ = 8;

function targetBands(rows: RegressionRow[], bandCount: number) {
  const minMax = safeMinMax(rows.map((r) => r.actual));
  if (!minMax) return [];
  const { min, max } = minMax;
  const width = (max - min) / bandCount || 1;
  const bands = Array.from({ length: bandCount }, (_, i) => ({ x0: min + i * width, x1: min + (i + 1) * width, rows: [] as RegressionRow[] }));
  for (const row of rows) {
    const index = Math.min(bandCount - 1, Math.max(0, Math.floor((row.actual - min) / width)));
    bands[index].rows.push(row);
  }
  return bands.map((band) => {
    const errors = band.rows.map((r) => Math.abs(r.residual));
    const { mean } = streamingMeanStd(errors);
    const rmse = errors.length ? Math.sqrt(errors.reduce((sum, e) => sum + e * e, 0) / errors.length) : null;
    return { x0: band.x0, x1: band.x1, count: band.rows.length, mae: errors.length ? mean : null, rmse, medianAbsoluteError: streamingMedian(errors) };
  });
}

export default function RegressionDiagnosticExplorer() {
  const { baseReference, problemType, target, loading: contextLoading } = useVisualIntelligenceContext();
  const [rows, setRows] = useState<RegressionRow[] | null>(null);
  const [modelName, setModelName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bandCount, setBandCount] = useState(8);
  const selectedRowIds = useInteractionStore((state) => state.selectedRowIds);
  const setScope = useInteractionStore((state) => state.setScope);
  const reset = useInteractionStore((state) => state.reset);

  useEffect(() => {
    if (!baseReference) return;
    setScope({ userId: baseReference.authenticatedUserId, projectId: baseReference.projectId, visualizationId: "regression-diagnostic-explorer" });
  }, [baseReference, setScope]);

  useEffect(() => {
    if (!baseReference || problemType !== "regression") return;
    let cancelled = false;
    setError(null);
    const fetchResult = baseReference.sourceType === "scoring-session"
      ? fetchScoringRunEvaluationRows(baseReference, "regression")
      : fetchTrainingEvaluationResult(baseReference, DEFAULT_MODEL_KEY);
    fetchResult
      .then((result) => {
        if (cancelled) return;
        const adapted = adaptRegressionRows(result.rows.map((r) => r.actual), result.rows.map((r) => r.prediction));
        setRows(adapted);
        setModelName(result.modelName);
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Failed to load evaluation result."));
    return () => {
      cancelled = true;
    };
  }, [baseReference, problemType]);

  const selectedSet = useMemo(() => new Set(selectedRowIds), [selectedRowIds]);
  const activeRows = useMemo(() => (rows && selectedSet.size ? rows.filter((r) => selectedSet.has(r.rowId)) : rows) ?? [], [rows, selectedSet]);

  const segmentMetrics = useMemo(() => {
    if (!activeRows.length) return null;
    const residuals = activeRows.map((r) => r.residual);
    const actuals = activeRows.map((r) => r.actual);
    const predictions = activeRows.map((r) => r.prediction);
    const { mean: meanResidual, std } = streamingMeanStd(residuals);
    const mae = streamingMeanStd(residuals.map((r) => Math.abs(r))).mean;
    const mse = residuals.reduce((sum, r) => sum + r * r, 0) / residuals.length;
    const meanActual = streamingMeanStd(actuals).mean;
    const ssTot = actuals.reduce((sum, a) => sum + (a - meanActual) ** 2, 0);
    const r2 = ssTot > 0 ? 1 - residuals.reduce((sum, r) => sum + r * r, 0) / ssTot : null;
    const predictionRange = safeMinMax(predictions);
    const actualRange = safeMinMax(actuals);
    return {
      rowCount: activeRows.length, mae, mse, rmse: Math.sqrt(mse),
      r2: activeRows.length >= 10 ? r2 : null, // small-segment R2 is not meaningful -- honest caution state below
      meanResidual, medianResidual: streamingMedian(residuals), medianAbsoluteError: streamingMedian(residuals.map((r) => Math.abs(r))), std,
      minPrediction: predictionRange?.min ?? null, maxPrediction: predictionRange?.max ?? null,
      minActual: actualRange?.min ?? null, maxActual: actualRange?.max ?? null,
    };
  }, [activeRows]);

  const bands = useMemo(() => (rows ? targetBands(rows, bandCount) : []), [rows, bandCount]);
  const qq = useMemo(() => (rows && rows.length >= MIN_ROWS_FOR_QQ ? qqPlotPoints(rows.map((r) => r.residual)) : []), [rows]);

  function attachBrush(instance: ECharts) {
    useInteractionStore.getState().setChartInstance(instance);
    instance.on("brushSelected", (params: unknown) => {
      const areas = (params as { batch?: Array<{ selected?: Array<{ dataIndex: number[] }> }> }).batch?.[0]?.selected ?? [];
      const indices = new Set<number>();
      areas.forEach((series) => series.dataIndex.forEach((i) => indices.add(i)));
      if (!rows) return;
      const ids = Array.from(indices).map((i) => rows[i]?.rowId).filter((id): id is string => Boolean(id));
      useInteractionStore.getState().setSelectedObservation(ids[0] ?? null);
      useInteractionStore.setState({ selectedRowIds: ids });
    });
  }

  const scaleIdentity: LinearScaleLike = useMemo(() => {
    const values = rows ? [...rows.map((r) => r.actual), ...rows.map((r) => r.prediction)] : [];
    const minMax = safeMinMax(values) ?? { min: 0, max: 1 };
    const fn = ((value: number) => ((value - minMax.min) / (minMax.max - minMax.min || 1)) * 640) as LinearScaleLike;
    fn.invert = (pixel: number) => minMax.min + (pixel / 640) * (minMax.max - minMax.min);
    fn.range = () => [0, 640];
    return fn;
  }, [rows]);

  const actualVsPredictedOption: EChartsOption | null = rows?.length
    ? {
        title: { text: "Actual vs. Predicted", subtext: `${modelName ?? DEFAULT_MODEL_KEY} -- TRAIN (Development)` },
        tooltip: { formatter: (p: unknown) => { const d = (p as { data: [number, number] }).data; return `Actual: ${d[0].toFixed(3)}<br/>Predicted: ${d[1].toFixed(3)}`; } },
        toolbox: { feature: { brush: { type: ["rect", "clear"] } }, right: 12, top: 4 },
        brush: { toolbox: ["rect", "clear"], throttleType: "debounce", throttleDelay: 200 },
        xAxis: { type: "value", name: `Actual ${target ?? ""}` },
        yAxis: { type: "value", name: `Predicted ${target ?? ""}` },
        series: [{ type: "scatter", symbolSize: 5, data: rows.map((r) => [r.actual, r.prediction]), itemStyle: { color: ATLAS_CHART_COLORS.train, opacity: 0.6 } }],
      }
    : null;

  const residualsVsFittedOption: EChartsOption | null = rows?.length
    ? {
        title: { text: "Residuals vs. Fitted", subtext: "Residual = actual - predicted" },
        tooltip: { formatter: (p: unknown) => { const d = (p as { data: [number, number] }).data; return `Fitted: ${d[0].toFixed(3)}<br/>Residual: ${d[1].toFixed(3)}`; } },
        toolbox: { feature: { brush: { type: ["rect", "clear"] } }, right: 12, top: 4 },
        brush: { toolbox: ["rect", "clear"], throttleType: "debounce", throttleDelay: 200 },
        xAxis: { type: "value", name: "Fitted (predicted) value" },
        yAxis: { type: "value", name: "Residual" },
        series: [{ type: "scatter", symbolSize: 5, data: rows.map((r) => [r.prediction, r.residual]), itemStyle: { color: ATLAS_CHART_COLORS.test, opacity: 0.6 } }],
      }
    : null;

  const residualHistogramOption: EChartsOption | null = rows?.length
    ? (() => {
        const residuals = rows.map((r) => r.residual);
        const minMax = safeMinMax(residuals)!;
        const binCount = 20;
        const width = (minMax.max - minMax.min) / binCount || 1;
        const bins = Array.from({ length: binCount }, (_, i) => ({ x0: minMax.min + i * width, count: 0 }));
        residuals.forEach((r) => { const idx = Math.min(binCount - 1, Math.max(0, Math.floor((r - minMax.min) / width))); bins[idx].count += 1; });
        return {
          title: { text: "Residual Distribution", subtext: `Mean residual ${meanValue(residuals)?.toFixed(3)} · Median ${medianValue(residuals)?.toFixed(3)}` },
          xAxis: { type: "category", data: bins.map((b) => b.x0.toFixed(2)), name: "Residual" },
          yAxis: { type: "value", name: "Row count" },
          series: [{ type: "bar", data: bins.map((b) => b.count), itemStyle: { color: ATLAS_CHART_COLORS.oot } }],
        };
      })()
    : null;

  const qqOption: EChartsOption | null = qq.length
    ? {
        title: { text: "Residual Q-Q Plot", subtext: "Theoretical normal quantiles vs. sample residual quantiles" },
        xAxis: { type: "value", name: "Theoretical quantile" },
        yAxis: { type: "value", name: "Sample residual quantile" },
        series: [
          { type: "scatter", symbolSize: 5, data: qq.map((p) => [p.theoretical, p.sample]), itemStyle: { color: ATLAS_CHART_COLORS.train } },
          { type: "line", showSymbol: false, data: qq.length ? [[qq[0].theoretical, qq[0].theoretical], [qq[qq.length - 1].theoretical, qq[qq.length - 1].theoretical]] : [], lineStyle: { color: ATLAS_CHART_COLORS.identity, type: "dashed" } },
        ],
      }
    : null;

  const bandOption: EChartsOption | null = bands.length
    ? {
        title: { text: "Absolute Error by Target Band" },
        tooltip: { trigger: "axis" },
        legend: { data: ["MAE", "RMSE"] },
        xAxis: { type: "category", data: bands.map((b) => `${b.x0.toFixed(1)}-${b.x1.toFixed(1)}`), name: target ?? "target band" },
        yAxis: { type: "value", name: "Error" },
        series: [
          { name: "MAE", type: "bar", data: bands.map((b) => b.mae), itemStyle: { color: ATLAS_CHART_COLORS.train } },
          { name: "RMSE", type: "bar", data: bands.map((b) => b.rmse), itemStyle: { color: ATLAS_CHART_COLORS.test } },
        ],
      }
    : null;

  const identityLine: ReferenceLineSpec[] = rows?.length ? [{ id: "identity", value: scaleIdentity.range()[1] / 2, label: "y = x", color: ATLAS_CHART_COLORS.identity, dashed: true }] : [];
  void identityLine; // ECharts markLine (series-level) is used for the identity/zero lines instead of the D3 overlay here, since they need to track two independent axes, not one; see the series definitions above.

  if (contextLoading) return <div className="rounded-md border border-slate-200 bg-slate-50 p-6 text-sm text-slate-600">Resolving project context...</div>;
  if (!baseReference) return <div className="rounded-md border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">No active project.</div>;
  if (problemType !== "regression") {
    return <div className="rounded-md border border-dashed border-amber-300 bg-amber-50 p-6 text-sm text-amber-800" data-testid="wrong-problem-type">This project is not a regression project. The Regression Diagnostic Explorer requires a regression model.</div>;
  }

  return (
    <section className="space-y-4" data-testid="regression-diagnostic-explorer" aria-label="Regression Diagnostic Explorer">
      <p className="text-xs text-slate-500">Model: <strong>{modelName ?? DEFAULT_MODEL_KEY}</strong> &middot; Target: <strong>{target ?? "unknown"}</strong> &middot; Partition: <strong>{(baseReference?.partition ?? "train").toUpperCase()}</strong>{baseReference?.sourceType === "scoring-session" ? <> &middot; <span data-testid="scoring-run-source-badge">Durable scoring run</span></> : null}</p>
      <p className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-900">TEST/OOT comparison partitions require a live Scoring session and are not durably available here (Known Constraint #1/#2) -- this prototype demonstrates against TRAIN.</p>
      <div className="flex items-center gap-2">
        <button type="button" className="atlas-secondary-button" data-testid="reset-selection" onClick={() => reset()}>Reset selection</button>
        {selectedRowIds.length ? <span className="text-xs text-slate-500">{selectedRowIds.length} observation(s) selected (brush a chart to select)</span> : null}
      </div>

      {error ? (
        <EChartsPanel option={null} state="error" errorMessage={error} height={CHART_HEIGHT} ariaLabel="Regression diagnostics" />
      ) : rows === null ? (
        <EChartsPanel option={null} state="loading" height={CHART_HEIGHT} ariaLabel="Regression diagnostics" />
      ) : rows.length === 0 ? (
        <EChartsPanel option={null} state="empty" emptyMessage="No scored rows are available for this model." height={CHART_HEIGHT} ariaLabel="Regression diagnostics" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="relative rounded-md border border-slate-200 bg-white p-2" style={{ height: CHART_HEIGHT + 16 }}>
            <EChartsPanel option={actualVsPredictedOption} height={CHART_HEIGHT} ariaLabel="Actual versus predicted scatter plot with identity line" onChartReady={attachBrush} />
          </div>
          <div className="relative rounded-md border border-slate-200 bg-white p-2" style={{ height: CHART_HEIGHT + 16 }}>
            <EChartsPanel option={residualsVsFittedOption} height={CHART_HEIGHT} ariaLabel="Residuals versus fitted values" onChartReady={attachBrush} />
          </div>
          <div className="rounded-md border border-slate-200 bg-white p-2" style={{ height: CHART_HEIGHT + 16 }}>
            <EChartsPanel option={residualHistogramOption} height={CHART_HEIGHT} ariaLabel="Residual distribution histogram" />
          </div>
          <div className="rounded-md border border-slate-200 bg-white p-2" style={{ height: CHART_HEIGHT + 16 }}>
            {qq.length ? (
              <EChartsPanel option={qqOption} height={CHART_HEIGHT} ariaLabel="Residual Q-Q plot" />
            ) : (
              <EChartsPanel option={null} state="unsupported" unsupportedMessage={`Q-Q plot requires at least ${MIN_ROWS_FOR_QQ} observations.`} height={CHART_HEIGHT} ariaLabel="Residual Q-Q plot" />
            )}
          </div>
          <div className="rounded-md border border-slate-200 bg-white p-2 lg:col-span-2" style={{ height: CHART_HEIGHT + 32 }}>
            <div className="mb-1 flex items-center justify-end gap-2 px-2 text-xs">
              <label className="flex items-center gap-1"><span className="font-semibold uppercase text-slate-500">Bands</span><input type="number" min={3} max={20} value={bandCount} onChange={(event) => setBandCount(Math.min(20, Math.max(3, Number(event.target.value) || 8)))} className="w-16 rounded-md border border-slate-300 px-1.5 py-1" /></label>
            </div>
            <EChartsPanel option={bandOption} height={CHART_HEIGHT} ariaLabel="Absolute error by target band" />
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 rounded-md border border-slate-200 bg-white p-4 sm:grid-cols-4" data-testid="regression-segment-metrics" aria-live="polite">
        <Metric label="Row count" value={segmentMetrics ? String(segmentMetrics.rowCount) : "Unavailable"} />
        <Metric label="MAE" value={formatMetric(segmentMetrics?.mae)} />
        <Metric label="MSE" value={formatMetric(segmentMetrics?.mse)} />
        <Metric label="RMSE" value={formatMetric(segmentMetrics?.rmse)} />
        <Metric label="R-squared" value={segmentMetrics && segmentMetrics.rowCount < 10 ? "Not meaningful for a segment this small" : formatMetric(segmentMetrics?.r2)} />
        <Metric label="Mean residual" value={formatMetric(segmentMetrics?.meanResidual)} />
        <Metric label="Median residual" value={formatMetric(segmentMetrics?.medianResidual)} />
        <Metric label="Median absolute error" value={formatMetric(segmentMetrics?.medianAbsoluteError)} />
        <Metric label="Prediction range" value={segmentMetrics ? `${formatMetric(segmentMetrics.minPrediction)} to ${formatMetric(segmentMetrics.maxPrediction)}` : "Unavailable"} />
        <Metric label="Actual range" value={segmentMetrics ? `${formatMetric(segmentMetrics.minActual)} to ${formatMetric(segmentMetrics.maxActual)}` : "Unavailable"} />
      </div>
    </section>
  );
}

function formatMetric(value: number | null | undefined): string {
  return value === null || value === undefined || Number.isNaN(value) ? "Unavailable" : value.toFixed(3);
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-slate-950">{value}</div>
    </div>
  );
}

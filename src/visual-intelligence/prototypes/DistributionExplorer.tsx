// ATLAS Visual Intelligence Foundation -- Prototype 1: Interactive Distribution Explorer.
// ECharts histogram + D3 statistical overlays (mean/median/percentile) + brush selection,
// with selected-segment aggregation computed via the Data Access Layer (DuckDB-Wasm above
// the direct-render threshold, a plain streaming pass below it).
import { useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import EChartsPanel from "../EChartsPanel";
import { BrushOverlay, ReferenceLineOverlay, meanValue, medianValue, percentileValue, type LinearScaleLike, type BrushRange, type ReferenceLineSpec } from "../d3Overlays";
import { ATLAS_CHART_COLORS } from "../theme";
import { fetchWorkspaceRows, fetchScoringRunRows, computeSegmentAggregate, isStaleResult, type SegmentAggregateResult } from "../dataAccessLayer";
import { chooseRenderStrategy } from "../largeDataPolicy";
import { useVisualIntelligenceContext } from "../VisualIntelligenceContext";
import { useInteractionStore } from "../interactionStore";
import type { VisualDatasetReference } from "../types";

const CHART_HEIGHT = 280;

function buildHistogram(values: number[], binCount: number) {
  if (!values.length) return { bins: [] as Array<{ x0: number; x1: number; count: number }>, min: 0, max: 1 };
  let min = values[0];
  let max = values[0];
  for (const v of values) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (min === max) max = min + 1;
  const width = (max - min) / binCount;
  const bins = Array.from({ length: binCount }, (_, i) => ({ x0: min + i * width, x1: min + (i + 1) * width, count: 0 }));
  for (const v of values) {
    const index = Math.min(binCount - 1, Math.max(0, Math.floor((v - min) / width)));
    bins[index].count += 1;
  }
  return { bins, min, max };
}

export default function DistributionExplorer() {
  const { baseReference, problemType, target, loading: contextLoading } = useVisualIntelligenceContext();
  const [rows, setRows] = useState<Record<string, unknown>[] | null>(null);
  const [numericFields, setNumericFields] = useState<string[]>([]);
  const [variable, setVariable] = useState<string>("");
  const [binCount, setBinCount] = useState(20);
  const [showMean, setShowMean] = useState(true);
  const [showMedian, setShowMedian] = useState(true);
  const [percentile, setPercentileValue] = useState<number | null>(null);
  const [partition] = useState<"train">("train"); // only TRAIN/workspace is durably available -- see Known Constraint #1
  const [segment, setSegment] = useState<BrushRange>(null);
  const [cutoffInput, setCutoffInput] = useState<{ min: string; max: string }>({ min: "", max: "" });
  const [segmentAggregate, setSegmentAggregate] = useState<SegmentAggregateResult | null>(null);
  const [aggregateLoading, setAggregateLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sampled, setSampled] = useState(false);
  const requestRef = useRef<VisualDatasetReference | null>(null);
  const scope = useInteractionStore((state) => state.scope);
  const setScope = useInteractionStore((state) => state.setScope);

  useEffect(() => {
    if (!baseReference) return;
    setScope({ userId: baseReference.authenticatedUserId, projectId: baseReference.projectId, visualizationId: "distribution-explorer" });
  }, [baseReference, setScope]);

  useEffect(() => {
    if (!baseReference) return;
    let cancelled = false;
    requestRef.current = baseReference;
    setError(null);
    const fetchRows = baseReference.sourceType === "scoring-session"
      ? fetchScoringRunRows(baseReference, { maxRows: 5000 })
      : fetchWorkspaceRows(baseReference, { maxRows: 5000 });
    fetchRows
      .then((result) => {
        if (cancelled || isStaleResult(baseReference, requestRef.current ?? baseReference)) return;
        setRows(result.rows);
        setSampled(result.meta.sampled);
        const fields = result.rows.length
          ? Object.keys(result.rows[0]).filter((key) => result.rows.every((row) => row[key] === null || row[key] === "" || Number.isFinite(Number(row[key]))))
          : [];
        setNumericFields(fields);
        setVariable((current) => (current && fields.includes(current) ? current : fields[0] ?? ""));
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Failed to load workspace data."));
    return () => {
      cancelled = true;
    };
  }, [baseReference]);

  const values = useMemo(() => {
    if (!rows || !variable) return [];
    return rows.map((row) => Number(row[variable])).filter(Number.isFinite);
  }, [rows, variable]);

  const histogram = useMemo(() => buildHistogram(values, binCount), [values, binCount]);
  const mean = useMemo(() => (showMean ? meanValue(values) : null), [values, showMean]);
  const median = useMemo(() => (showMedian ? medianValue(values) : null), [values, showMedian]);
  const pctValue = useMemo(() => (percentile !== null ? percentileValue(values, percentile) : null), [values, percentile]);

  useEffect(() => {
    if (!baseReference || !rows || !variable) return;
    let cancelled = false;
    setAggregateLoading(true);
    const range = segment ? { min: Math.min(segment.start, segment.end), max: Math.max(segment.start, segment.end) } : {};
    const positiveValue = problemType === "classification" ? 1 : undefined;
    computeSegmentAggregate(baseReference, rows, variable, range, positiveValue)
      .then((result) => !cancelled && setSegmentAggregate(result))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Segment aggregation failed."))
      .finally(() => !cancelled && setAggregateLoading(false));
    return () => {
      cancelled = true;
    };
  }, [baseReference, rows, variable, segment, problemType]);

  const scale: LinearScaleLike = useMemo(() => {
    const domainMin = histogram.min;
    const domainMax = histogram.max;
    const rangeStart = 0;
    const rangeEnd = 640; // matches the panel's typical rendered width; ResizeObserver keeps ECharts itself responsive independently
    const fn = ((value: number) => rangeStart + ((value - domainMin) / (domainMax - domainMin || 1)) * (rangeEnd - rangeStart)) as LinearScaleLike;
    fn.invert = (pixel: number) => domainMin + ((pixel - rangeStart) / (rangeEnd - rangeStart)) * (domainMax - domainMin);
    fn.range = () => [rangeStart, rangeEnd];
    return fn;
  }, [histogram.min, histogram.max]);

  const referenceLines: ReferenceLineSpec[] = [];
  if (mean !== null) referenceLines.push({ id: "mean", value: mean, label: `Mean ${mean.toFixed(2)}`, color: ATLAS_CHART_COLORS.mean });
  if (median !== null) referenceLines.push({ id: "median", value: median, label: `Median ${median.toFixed(2)}`, color: ATLAS_CHART_COLORS.median, dashed: true });
  if (pctValue !== null) referenceLines.push({ id: "percentile", value: pctValue, label: `P${percentile} ${pctValue.toFixed(2)}`, color: ATLAS_CHART_COLORS.oot, dashed: true });

  const option: EChartsOption | null = histogram.bins.length
    ? {
        title: { text: `Distribution of ${variable}`, subtext: "Interactive Distribution Explorer -- Visual Intelligence Foundation prototype" },
        tooltip: { trigger: "axis", formatter: (params: unknown) => {
          const p = (params as Array<{ axisValue: string; data: number }>)[0];
          return `${p.axisValue}<br/>Rows: ${p.data}`;
        } },
        xAxis: { type: "category", data: histogram.bins.map((bin) => `${bin.x0.toFixed(1)}-${bin.x1.toFixed(1)}`), name: variable },
        yAxis: { type: "value", name: "Row count" },
        series: [{ type: "bar", data: histogram.bins.map((bin) => bin.count), itemStyle: { color: ATLAS_CHART_COLORS.train }, barCategoryGap: "10%" }],
      }
    : null;

  if (contextLoading) return <div className="rounded-md border border-slate-200 bg-slate-50 p-6 text-sm text-slate-600">Resolving project context...</div>;
  if (!baseReference) return <div className="rounded-md border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">No active project. Open a Predictive Modeling project to use the Distribution Explorer.</div>;

  const insufficientData = rows !== null && values.length < 5;
  const unsupportedVariable = rows !== null && !numericFields.length;

  return (
    <section className="space-y-4" data-testid="distribution-explorer" aria-label="Interactive Distribution Explorer">
      <div className="flex flex-wrap items-end gap-3 rounded-md border border-slate-200 bg-white p-4">
        <label className="grid gap-1 text-xs">
          <span className="font-semibold uppercase text-slate-500">Variable</span>
          <select data-testid="variable-selector" className="rounded-md border border-slate-300 px-2 py-1.5 text-sm" value={variable} onChange={(event) => setVariable(event.target.value)}>
            {numericFields.map((field) => <option key={field} value={field}>{field}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold uppercase text-slate-500">Bin count</span>
          <input data-testid="bin-count-input" type="number" min={5} max={60} value={binCount} onChange={(event) => setBinCount(Math.min(60, Math.max(5, Number(event.target.value) || 20)))} className="w-20 rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
        <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={showMean} onChange={(event) => setShowMean(event.target.checked)} /> Mean</label>
        <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={showMedian} onChange={(event) => setShowMedian(event.target.checked)} /> Median</label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold uppercase text-slate-500">Percentile</span>
          <select data-testid="percentile-selector" className="rounded-md border border-slate-300 px-2 py-1.5 text-sm" value={percentile ?? ""} onChange={(event) => setPercentileValue(event.target.value ? Number(event.target.value) : null)}>
            <option value="">None</option>
            {[10, 25, 75, 90, 95, 99].map((p) => <option key={p} value={p}>P{p}</option>)}
          </select>
        </label>
        <div className="grid gap-1 text-xs">
          <span className="font-semibold uppercase text-slate-500">Numeric cutoff (min / max)</span>
          <div className="flex gap-1">
            <input aria-label="Segment minimum" type="number" value={cutoffInput.min} onChange={(event) => {
              const next = { ...cutoffInput, min: event.target.value };
              setCutoffInput(next);
              setSegment({ start: Number(next.min) || histogram.min, end: next.max ? Number(next.max) : histogram.max });
            }} className="w-24 rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
            <input aria-label="Segment maximum" type="number" value={cutoffInput.max} onChange={(event) => {
              const next = { ...cutoffInput, max: event.target.value };
              setCutoffInput(next);
              setSegment({ start: next.min ? Number(next.min) : histogram.min, end: Number(next.max) || histogram.max });
            }} className="w-24 rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
          </div>
        </div>
        <button type="button" data-testid="reset-button" className="atlas-secondary-button" onClick={() => { setSegment(null); setCutoffInput({ min: "", max: "" }); }}>Reset</button>
      </div>

      {sampled ? <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800" data-testid="sampled-notice">This view uses a bounded sample of the workspace dataset (up to 5,000 rows), not the full population.</p> : null}
      {problemType ? <p className="text-xs text-slate-500">Problem type: <strong>{problemType}</strong>{target ? <> &middot; Target: <strong>{target}</strong></> : null} &middot; Partition: <strong>{(baseReference?.partition ?? partition).toUpperCase()}</strong>{baseReference?.sourceType === "scoring-session" ? <> &middot; <span data-testid="scoring-run-source-badge">Durable scoring run</span></> : null}</p> : null}

      {unsupportedVariable ? (
        <EChartsPanel option={null} state="unsupported" unsupportedMessage="No numeric variables were found in the current workspace dataset." height={CHART_HEIGHT} ariaLabel="Distribution histogram" />
      ) : insufficientData ? (
        <EChartsPanel option={null} state="unsupported" unsupportedMessage="Fewer than 5 valid numeric observations are available for this variable." height={CHART_HEIGHT} ariaLabel="Distribution histogram" />
      ) : error ? (
        <EChartsPanel option={null} state="error" errorMessage={error} height={CHART_HEIGHT} ariaLabel="Distribution histogram" />
      ) : rows === null ? (
        <EChartsPanel option={null} state="loading" height={CHART_HEIGHT} ariaLabel="Distribution histogram" />
      ) : (
        <div className="relative rounded-md border border-slate-200 bg-white p-2" style={{ height: CHART_HEIGHT + 16 }}>
          <EChartsPanel option={option} height={CHART_HEIGHT} ariaLabel={`Distribution histogram of ${variable}`} renderer={chooseRenderStrategy(values.length) === "direct-svg" ? "svg" : "canvas"} onChartReady={(instance) => useInteractionStore.getState().setChartInstance(instance)} />
          <div className="pointer-events-none absolute inset-2" style={{ height: CHART_HEIGHT }}>
            <div className="pointer-events-auto absolute inset-0">
              <BrushOverlay scale={scale} height={CHART_HEIGHT} onBrush={(range) => { setSegment(range); setCutoffInput(range ? { min: range.start.toFixed(2), max: range.end.toFixed(2) } : { min: "", max: "" }); }} />
              <ReferenceLineOverlay lines={referenceLines} scale={scale} height={CHART_HEIGHT} />
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 rounded-md border border-slate-200 bg-white p-4 sm:grid-cols-4" data-testid="segment-metrics" aria-live="polite">
        <Metric label="Selected rows" value={aggregateLoading ? "..." : String(segmentAggregate?.rowCount ?? values.length)} />
        <Metric label="% of population" value={aggregateLoading ? "..." : values.length ? `${(((segmentAggregate?.rowCount ?? values.length) / values.length) * 100).toFixed(1)}%` : "Unavailable"} />
        <Metric label="Mean" value={formatMetric(segmentAggregate?.mean)} />
        <Metric label="Median" value={formatMetric(segmentAggregate?.median)} />
        <Metric label="Std. deviation" value={formatMetric(segmentAggregate?.std)} />
        <Metric label="Minimum" value={formatMetric(segmentAggregate?.min)} />
        <Metric label="Maximum" value={formatMetric(segmentAggregate?.max)} />
        {problemType === "classification" ? <Metric label="Target rate" value={segmentAggregate?.targetRate != null ? `${(segmentAggregate.targetRate * 100).toFixed(2)}%` : "Unavailable"} /> : null}
        {problemType === "regression" ? <Metric label="Avg. target" value={formatMetric(segmentAggregate?.mean)} /> : null}
      </div>
      {segmentAggregate ? <p className="text-[11px] text-slate-400">Aggregation method: {segmentAggregate.aggregationMethod} &middot; {segmentAggregate.queryDurationMs.toFixed(1)}ms</p> : null}
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

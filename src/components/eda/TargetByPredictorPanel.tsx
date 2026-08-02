// Part G: Target by Predictor -- on-demand, bounded, server-side.
//
// Nothing here runs on mount. The analyst chooses a predictor and an analysis
// type and presses Run Analysis; only then is a single grouped aggregate issued
// over the governed artifact. The chart plots the returned bounded rows -- the
// predictor column and the target column never reach the browser.
import { useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import type * as echarts from "echarts/core";
import { LoaderCircle, Play, RotateCcw, Search, Download } from "lucide-react";
import EChartsPanel, { exportChartAsPng, type EChartsPanelState } from "../../visual-intelligence/EChartsPanel";
import { formatEventRate } from "../../lib/dataAcquisitionLifecycle";
import {
  describeTargetByPredictor,
  formatCount,
  type TargetByPredictorResult,
  type TargetPredictorAnalysisType,
  type TargetPredictorBoxPlot,
  type TargetPredictorGroup,
} from "../../lib/targetIntelligence";
import type { TargetByPredictorState } from "../../lib/useTargetIntelligence";
import StatisticalBoxPlot, {
  type BoxPlotSeries,
} from "./visual/StatisticalBoxPlot";

const RATE_COLOR = "#b91c1c";
const COUNT_COLOR = "#1d4ed8";
const REFERENCE_COLOR = "#0f766e";
const MISSING_COLOR = "#b45309";

export type PredictorOption = { feature: string; kind: "numeric" | "categorical"; iv?: number | null };

function groupLabel(row: TargetPredictorGroup): string {
  return row.category ?? row.label ?? "Group";
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function targetBoxPlotSeries(
  rows: TargetPredictorBoxPlot[] | undefined,
): BoxPlotSeries[] {
  return (rows ?? []).flatMap((row) => {
    if (
      !isFiniteNumber(row.minimum) ||
      !isFiniteNumber(row.q1) ||
      !isFiniteNumber(row.median) ||
      !isFiniteNumber(row.q3) ||
      !isFiniteNumber(row.maximum) ||
      !isFiniteNumber(row.whiskerLow) ||
      !isFiniteNumber(row.whiskerHigh)
    ) {
      return [];
    }
    return [
      {
        id: row.targetClass,
        label: row.label,
        count: row.population,
        minimum: row.minimum,
        q1: row.q1,
        median: row.median,
        q3: row.q3,
        maximum: row.maximum,
        whiskerLow: row.whiskerLow,
        whiskerHigh: row.whiskerHigh,
        outlierCount: row.outlierCount,
        color: row.targetClass === "event" ? "#dc2626" : "#0f766e",
      },
    ];
  });
}

/**
 * Event rate per group as bars, event count as a companion line on a second
 * axis, and the Development Population event rate as a reference line -- so a band cannot
 * be read as "high risk" without also seeing how few events it holds and how
 * far it actually sits from the Development Population baseline.
 */
function buildOption(result: TargetByPredictorResult, reducedMotion: boolean): EChartsOption {
  const rows: TargetPredictorGroup[] = [
    ...result.rows,
    ...(result.missingGroup ? [result.missingGroup] : []),
    ...(result.otherGroup ? [result.otherGroup] : []),
  ];
  const categories = rows.map(groupLabel);
  const reference = result.populationEventRate ?? 0;

  return {
    animation: !reducedMotion,
    animationDuration: reducedMotion ? 0 : 320,
    animationEasing: "cubicOut",
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    legend: { top: 0, data: ["Event rate", "Event count"] },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params: unknown) => {
        const items = Array.isArray(params) ? (params as Array<{ dataIndex: number }>) : [];
        const row = rows[items[0]?.dataIndex ?? 0];
        if (!row) return "";
        const range =
          row.lowerBound !== null && row.lowerBound !== undefined && row.upperBound !== null && row.upperBound !== undefined
            ? `<br/>Range: ${row.lowerBound.toLocaleString()} to ${row.upperBound.toLocaleString()}`
            : "";
        return (
          `<strong>${groupLabel(row)}</strong>` +
          `<br/>Event rate: ${formatEventRate(row.eventRate)}` +
          `<br/>Events: ${row.eventCount.toLocaleString()}` +
          `<br/>Development rows: ${row.population.toLocaleString()}` +
          range +
          (row.smallGroup ? "<br/><em>Small group -- rate is unstable</em>" : "")
        );
      },
    },
    xAxis: { type: "category", data: categories, axisLabel: { interval: 0, rotate: categories.length > 8 ? 35 : 0, fontSize: 11 } },
    yAxis: [
      {
        type: "value",
        name: "Event rate",
        axisLabel: { formatter: (value: number) => formatEventRate(value) },
      },
      {
        type: "value",
        name: "Event count",
        splitLine: { show: false },
        axisLabel: { formatter: (value: number) => value.toLocaleString() },
      },
    ],
    series: [
      {
        name: "Event rate",
        type: "bar",
        yAxisIndex: 0,
        barMaxWidth: 46,
        data: rows.map((row) => ({
          value: row.eventRate ?? 0,
          itemStyle: {
            color: row.isMissingGroup ? MISSING_COLOR : RATE_COLOR,
            opacity: row.smallGroup ? 0.55 : 1,
            borderRadius: [4, 4, 0, 0],
          },
        })),
        markLine: reference
          ? {
              silent: true,
              symbol: "none",
              lineStyle: { color: REFERENCE_COLOR, type: "dashed" },
              label: { formatter: `Development ${formatEventRate(reference)}`, fontSize: 10, color: REFERENCE_COLOR },
              data: [{ yAxis: reference }],
            }
          : undefined,
      },
      {
        name: "Event count",
        type: "line",
        yAxisIndex: 1,
        symbol: "circle",
        symbolSize: 7,
        lineStyle: { color: COUNT_COLOR, width: 2 },
        itemStyle: { color: COUNT_COLOR },
        data: rows.map((row) => row.eventCount),
      },
    ],
  };
}

const PHASE_LABELS: Record<TargetByPredictorState["phase"], string> = {
  idle: "No analysis has been run for this predictor.",
  queued: "Queued",
  running: "Aggregating the governed dataset...",
  cached: "Cached result",
  ready: "Exact result",
  unsupported: "This predictor produced no usable groups.",
  failed: "Analysis failed",
};

export default function TargetByPredictorPanel({
  predictors,
  requestedPredictor,
  state,
  disabledReason,
  scopeNotice,
  onRun,
  onReset,
}: {
  predictors: PredictorOption[];
  /** Optional selection initiated by the bounded Target predictor preview. */
  requestedPredictor?: string;
  state: TargetByPredictorState;
  /** Set when the analysis genuinely cannot run, so the controls explain why. */
  disabledReason?: string;
  /** Set when the analysis runs against a different (still exact) population
   *  than an immutable registered version, so the scope is never implicit. */
  scopeNotice?: string;
  onRun: (input: {
    predictor: string;
    analysisType: TargetPredictorAnalysisType;
    bands: number;
    includeMissing: boolean;
  }) => void;
  onReset: () => void;
}) {
  const [search, setSearch] = useState("");
  const [predictor, setPredictor] = useState("");
  const [analysisType, setAnalysisType] = useState<TargetPredictorAnalysisType>("numeric_quantile");
  const [bands, setBands] = useState(10);
  const [includeMissing, setIncludeMissing] = useState(true);
  const chartRef = useRef<echarts.ECharts | null>(null);

  const reducedMotion =
    typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;

  const matches = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = needle ? predictors.filter((item) => item.feature.toLowerCase().includes(needle)) : predictors;
    return filtered.slice(0, 300);
  }, [predictors, search]);

  const result = state.result;
  const boxPlotSeries =
    result?.analysisType === "numeric_quantile"
      ? targetBoxPlotSeries(result.boxPlotByTarget)
      : [];

  useEffect(() => {
    const requested = requestedPredictor || result?.predictor || "";
    const option = predictors.find((item) => item.feature === requested);
    if (!option || requested === predictor) return;
    setPredictor(requested);
    setSearch("");
    setAnalysisType(option.kind === "numeric" ? "numeric_quantile" : "categorical");
  }, [predictor, predictors, requestedPredictor, result?.predictor]);

  const option = useMemo(
    () => (result && result.rows.length ? buildOption(result, reducedMotion) : null),
    [result, reducedMotion]
  );

  const chartState: EChartsPanelState =
    state.phase === "running" || state.phase === "queued"
      ? "loading"
      : state.phase === "failed"
        ? "error"
        : state.phase === "unsupported"
          ? "unsupported"
          : option
            ? "ready"
            : "empty";

  function handleSelect(feature: string) {
    setPredictor(feature);
    const option = predictors.find((item) => item.feature === feature);
    // The default analysis type follows the predictor's actual kind rather than
    // leaving a numeric selection pointed at a categorical analysis.
    if (option) setAnalysisType(option.kind === "numeric" ? "numeric_quantile" : "categorical");
  }

  return (
    <div className="space-y-4" data-testid="target-by-predictor">
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr_0.8fr_1fr]">
          <label className="block">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Predictor</span>
            <div className="relative mt-1">
              <Search size={14} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search predictors"
                data-testid="target-predictor-search"
                className="w-full rounded-lg border border-slate-300 py-1.5 pl-7 pr-2 text-sm"
              />
            </div>
            <select
              value={predictor}
              onChange={(event) => handleSelect(event.target.value)}
              data-testid="target-predictor-select"
              className="mt-2 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
              size={1}
            >
              <option value="">Select a predictor</option>
              {matches.map((item) => (
                <option key={item.feature} value={item.feature}>
                  {item.feature} ({item.kind === "numeric" ? "numeric" : "categorical"})
                </option>
              ))}
            </select>
            <span className="mt-1 block text-[11px] text-slate-500" data-testid="target-predictor-match-count">
              {matches.length.toLocaleString()} of {predictors.length.toLocaleString()} predictors shown
            </span>
          </label>

          <label className="block">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Analysis type</span>
            <select
              value={analysisType}
              onChange={(event) => setAnalysisType(event.target.value as TargetPredictorAnalysisType)}
              data-testid="target-analysis-type"
              className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
            >
              <option value="numeric_quantile">Event rate by quantile band</option>
              <option value="categorical">Event rate by category</option>
            </select>
          </label>

          <label className="block">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Bands</span>
            <input
              type="number"
              min={2}
              max={20}
              value={bands}
              disabled={analysisType !== "numeric_quantile"}
              onChange={(event) => setBands(Math.max(2, Math.min(20, Number(event.target.value) || 10)))}
              data-testid="target-band-count"
              className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm disabled:bg-slate-100 disabled:text-slate-400"
            />
          </label>

          <div className="flex flex-col justify-end gap-2">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={includeMissing}
                onChange={(event) => setIncludeMissing(event.target.checked)}
                data-testid="target-include-missing"
              />
              Include missing as a separate group
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                className="atlas-primary-button flex-1"
                data-testid="target-run-analysis"
                disabled={!predictor || !!disabledReason || state.phase === "running" || state.phase === "queued"}
                onClick={() => onRun({ predictor, analysisType, bands, includeMissing })}
              >
                {state.phase === "running" || state.phase === "queued" ? (
                  <LoaderCircle size={15} className="animate-spin" />
                ) : (
                  <Play size={15} />
                )}
                Run Analysis
              </button>
              <button
                type="button"
                className="atlas-secondary-button"
                data-testid="target-reset-analysis"
                onClick={() => {
                  setPredictor("");
                  setSearch("");
                  setBands(10);
                  setIncludeMissing(true);
                  onReset();
                }}
              >
                <RotateCcw size={15} /> Reset
              </button>
            </div>
          </div>
        </div>

        {disabledReason ? (
          <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950">{disabledReason}</p>
        ) : null}
        {scopeNotice ? (
          <p className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700" data-testid="target-predictor-scope-notice">
            {scopeNotice}
          </p>
        ) : null}

        <p
          className="mt-3 text-xs font-semibold text-slate-600"
          role="status"
          aria-live="polite"
          data-testid="target-predictor-phase"
          data-query-phase={state.phase}
        >
          {PHASE_LABELS[state.phase]}
          {state.phase === "failed" && state.error ? `: ${state.error}` : ""}
          {(state.phase === "ready" || state.phase === "cached") && result
            ? ` -- ${result.analyzedRowCount.toLocaleString()} rows aggregated on the server in ${result.durationMs} ms; ${
                result.rows.length + (result.missingGroup ? 1 : 0) + (result.otherGroup ? 1 : 0)
              } bounded rows returned.`
            : ""}
        </p>
      </div>

      {result && result.rows.length ? (
        <>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">
                  {result.target} event rate by {result.predictor}
                </h3>
                <p className="mt-1 text-xs text-slate-600" data-testid="target-predictor-result-scope">
                  Development Population · target-directed analysis · sealed final holdout excluded
                </p>
              </div>
              <button
                type="button"
                className="atlas-secondary-button"
                data-testid="target-export-chart"
                onClick={() => {
                  if (chartRef.current) {
                    exportChartAsPng(chartRef.current, `target-by-${result.predictor}.png`);
                  }
                }}
              >
                <Download size={14} /> Export chart
              </button>
            </div>
            <div className="mt-3">
              <EChartsPanel
                option={option}
                state={chartState}
                height={300}
                onChartReady={(instance) => {
                  chartRef.current = instance;
                }}
                ariaLabel={`Development Population target-by-predictor chart. ${describeTargetByPredictor(result, formatEventRate)} The sealed final holdout is excluded.`}
                loadingMessage="Aggregating the Development Population..."
                emptyMessage="Run an analysis to plot event rate by group."
                errorMessage={state.error ?? "The analysis could not be rendered."}
              />
            </div>
            {boxPlotSeries.length ? (
              <div className="mt-4">
                <StatisticalBoxPlot
                  title={`${result.predictor} by ${result.target} class`}
                  subtitle="Development Population comparison of the predictor’s center, spread, whiskers, and outlier burden for the event and non-event classes."
                  series={boxPlotSeries}
                  valueLabel={result.predictor}
                  dataTestId="target-predictor-box-plot"
                  note="Quartiles, observed whiskers, extremes, and outlier counts are aggregated exactly on the server from the Development Population; the sealed final holdout is excluded. Raw predictor and target values do not leave the governed analysis service."
                />
              </div>
            ) : null}
            <p className="sr-only" data-testid="target-by-predictor-summary">
              {describeTargetByPredictor(result, formatEventRate)}
            </p>
          </div>

          <GroupTable result={result} />
          <AnalyticalSummary result={result} />
        </>
      ) : null}
    </div>
  );
}

function GroupTable({ result }: { result: TargetByPredictorResult }) {
  const rows: TargetPredictorGroup[] = [
    ...result.rows,
    ...(result.missingGroup ? [result.missingGroup] : []),
    ...(result.otherGroup ? [result.otherGroup] : []),
  ];
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="min-w-full text-sm" data-testid="target-by-predictor-table">
        <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2">Group</th>
            {result.analysisType === "numeric_quantile" ? <th className="px-3 py-2">Band range</th> : null}
            {result.analysisType === "numeric_quantile" ? <th className="px-3 py-2">Mean</th> : null}
            <th className="px-3 py-2 text-right">Development rows</th>
            <th className="px-3 py-2 text-right">Events</th>
            <th className="px-3 py-2 text-right">Event rate</th>
            <th className="px-3 py-2">Note</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={groupLabel(row)} className="border-t border-slate-100">
              <td className="px-3 py-2 font-medium text-slate-900">{groupLabel(row)}</td>
              {result.analysisType === "numeric_quantile" ? (
                <td className="px-3 py-2 text-slate-600">
                  {row.lowerBound === null || row.lowerBound === undefined
                    ? "Not applicable"
                    : `${row.lowerBound.toLocaleString(undefined, { maximumFractionDigits: 4 })} - ${(row.upperBound ?? 0).toLocaleString(undefined, { maximumFractionDigits: 4 })}`}
                </td>
              ) : null}
              {result.analysisType === "numeric_quantile" ? (
                <td className="px-3 py-2 text-slate-600">
                  {row.meanValue === null || row.meanValue === undefined
                    ? "Not applicable"
                    : row.meanValue.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                </td>
              ) : null}
              <td className="px-3 py-2 text-right tabular-nums">{formatCount(row.population)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{formatCount(row.eventCount)}</td>
              <td className="px-3 py-2 text-right tabular-nums font-semibold">{formatEventRate(row.eventRate)}</td>
              <td className="px-3 py-2 text-xs text-amber-800">
                {row.isOtherGroup
                  ? `${row.collapsedCategoryCount} categories aggregated`
                  : row.smallGroup
                    ? "Small group -- unstable rate"
                    : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AnalyticalSummary({ result }: { result: TargetByPredictorResult }) {
  const summary = result.summary;
  return (
    <div className="rounded-lg border border-teal-300 bg-teal-50 p-4" data-testid="target-predictor-analytical-summary">
      <h3 className="text-sm font-semibold text-teal-950">Analytical summary</h3>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Item label="Highest event rate" value={summary.highest ? `${summary.highest.label} -- ${formatEventRate(summary.highest.eventRate)}` : "Not available"} />
        <Item label="Lowest event rate" value={summary.lowest ? `${summary.lowest.label} -- ${formatEventRate(summary.lowest.eventRate)}` : "Not available"} />
        <Item label="Event-rate spread" value={formatEventRate(summary.eventRateSpread)} />
        <Item label="Monotonicity" value={summary.monotonicity} />
        <Item
          label="Event concentration"
          value={summary.eventConcentration === null ? "Not available" : `${(summary.eventConcentration * 100).toFixed(1)}% of events in the highest band`}
        />
        <Item
          label="Missing-value effect"
          value={
            summary.missingEffect
              ? `${formatEventRate(summary.missingEffect.missingEventRate)} vs ${formatEventRate(summary.missingEffect.presentEventRate)} present${summary.missingEffect.materialDifference ? " -- material difference, review" : ""}`
              : "No missing values in this predictor"
          }
        />
      </dl>
      <p className="mt-3 text-sm text-teal-950" data-testid="target-predictor-interpretation">
        {summary.interpretation}
      </p>
      {summary.limitations.length ? (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-teal-900" data-testid="target-predictor-limitations">
          {summary.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-teal-200 bg-white px-3 py-2">
      <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm font-semibold text-slate-900">{value}</dd>
    </div>
  );
}

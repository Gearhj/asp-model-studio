// Part H3: Target Distribution panel.
//
// Renders authoritative full-population class aggregates (from the backend
// quality profile) through the shared ECharts wrapper -- never from the browser
// preview, and never through a second competing chart library.
import { useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import EChartsPanel, { type EChartsPanelState } from "../../visual-intelligence/EChartsPanel";
import {
  type DistributionViewMode,
  type TargetDistribution,
  describeTargetDistribution,
  formatEventRate,
  RARE_EVENT_SCALE_DISCLOSURE,
  RARE_EVENT_TAKEAWAY,
  shouldOfferRareEventView,
} from "../../lib/dataAcquisitionLifecycle";

const EVENT_COLOR = "#b91c1c";
const NON_EVENT_COLOR = "#1d4ed8";

function buildOption(distribution: TargetDistribution, mode: DistributionViewMode, reducedMotion: boolean): EChartsOption {
  const rows =
    mode === "population"
      ? [
          { name: `Non-event (${distribution.nonEventValue})`, value: distribution.nonEventCount, color: NON_EVENT_COLOR },
          { name: `Event (${distribution.eventValue})`, value: distribution.eventCount, color: EVENT_COLOR },
        ]
      : [
          { name: `Event (${distribution.eventValue})`, value: distribution.eventCount, color: EVENT_COLOR },
        ];

  return {
    animation: !reducedMotion,
    animationDuration: reducedMotion ? 0 : 300,
    grid: { left: 8, right: 72, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      valueFormatter: (value) => Number(value).toLocaleString(),
    },
    xAxis: {
      type: "value",
      name: mode === "population" ? "Rows (true scale)" : "Rows (minority class only)",
      nameLocation: "middle",
      nameGap: 28,
      axisLabel: { formatter: (value: number) => value.toLocaleString() },
    },
    yAxis: { type: "category", data: rows.map((row) => row.name) },
    series: [
      {
        type: "bar",
        data: rows.map((row) => ({ value: row.value, itemStyle: { color: row.color, borderRadius: [0, 4, 4, 0] } })),
        barMaxWidth: 44,
        label: {
          show: true,
          position: "right",
          formatter: (params: { dataIndex: number }) => {
            const count = rows[params.dataIndex]?.value ?? 0;
            const percent = count === distribution.eventCount ? distribution.eventPercent : distribution.nonEventPercent;
            return `${count.toLocaleString()}  (${formatEventRate(percent)})`;
          },
          fontSize: 11,
          color: "#0f172a",
        },
      },
    ],
  };
}

export type TargetDistributionQueryState = {
  phase: "idle" | "queued" | "running" | "cached" | "exact" | "sampled" | "unsupported" | "failed";
  elapsedMs: number;
  error: string | null;
  sampling?: { samplingMethod: string; seed: number; sampledRowCount: number; sourceRowCount: number };
  retry: () => void;
  calculateExact: () => void;
};

/** Distinct, honest labels for each query state -- never a generic indefinite "Loading...". */
const QUERY_STATE_LABELS: Record<TargetDistributionQueryState["phase"], string> = {
  idle: "",
  queued: "Queued",
  running: "Calculating target distribution from the registered dataset...",
  cached: "Cached result",
  exact: "Exact result",
  sampled: "Estimated from stratified sample",
  unsupported: "Not charted",
  failed: "Query failed",
};

export default function TargetDistributionPanel({
  distribution,
  state,
  scopeLabel,
  errorMessage,
  query,
}: {
  distribution: TargetDistribution | null;
  state: EChartsPanelState;
  /** Which population the counts describe, so the analyst always knows the scope. */
  scopeLabel: string;
  errorMessage?: string;
  /** Server-aggregate lifecycle, when the counts come from a registered version. */
  query?: TargetDistributionQueryState;
}) {
  const [mode, setMode] = useState<DistributionViewMode>("population");
  const reducedMotion =
    typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;

  const option = useMemo(
    () => (distribution ? buildOption(distribution, mode, reducedMotion) : null),
    [distribution, mode, reducedMotion]
  );

  const offerRareEventView = shouldOfferRareEventView(distribution);
  const summary = describeTargetDistribution(distribution);

  return (
    <section
      className="rounded-xl border-2 border-blue-300 bg-blue-50 p-5 shadow-sm"
      data-testid="target-distribution-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Target setup</div>
          <h2 className="mt-1 text-base font-semibold text-blue-950">Target Distribution</h2>
          <p className="mt-1 text-sm text-slate-700">
            Class counts from the {scopeLabel}. Preview row limits do not affect these aggregates.
          </p>
          {query && query.phase !== "idle" && (
            <p
              className="mt-2 text-xs font-semibold text-slate-600"
              data-testid="target-distribution-query-state"
              data-query-phase={query.phase}
              role="status"
              aria-live="polite"
            >
              {QUERY_STATE_LABELS[query.phase]}
              {(query.phase === "running" || query.phase === "queued") && query.elapsedMs > 700
                ? ` (${(query.elapsedMs / 1000).toFixed(1)}s)`
                : ""}
            </p>
          )}
        </div>
        {offerRareEventView && (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Target distribution view mode">
            <button
              type="button"
              onClick={() => setMode("population")}
              aria-pressed={mode === "population"}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${mode === "population" ? "border-blue-700 bg-blue-700 text-white" : "border-blue-300 bg-white text-blue-900 hover:bg-blue-100"}`}
            >
              Population Scale
            </button>
            <button
              type="button"
              onClick={() => setMode("rare-event")}
              aria-pressed={mode === "rare-event"}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${mode === "rare-event" ? "border-blue-700 bg-blue-700 text-white" : "border-blue-300 bg-white text-blue-900 hover:bg-blue-100"}`}
            >
              Rare-Event Detail
            </button>
          </div>
        )}
      </div>

      {distribution && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Event count" value={distribution.eventCount.toLocaleString()} tone="danger" />
          <MetricCard label="Event rate" value={formatEventRate(distribution.eventPercent)} tone="danger" testId="target-distribution-event-rate" />
          <MetricCard label="Non-event count" value={distribution.nonEventCount.toLocaleString()} tone="info" />
          <MetricCard label="Non-event rate" value={formatEventRate(distribution.nonEventPercent)} tone="info" />
          <MetricCard
            label="Imbalance ratio"
            value={distribution.imbalanceRatio === null ? "Not available" : `${distribution.imbalanceRatio.toFixed(1)} : 1`}
            tone="neutral"
          />
          <MetricCard label="Total rows used" value={distribution.totalRows.toLocaleString()} tone="neutral" />
          <MetricCard label="Target column" value={distribution.target} tone="neutral" />
          <MetricCard label="Positive / negative value" value={`${distribution.eventValue} / ${distribution.nonEventValue}`} tone="neutral" />
        </div>
      )}

      <div className="mt-4 rounded-lg border border-blue-200 bg-white p-3">
        <EChartsPanel
          option={option}
          state={state}
          height={mode === "population" ? 200 : 150}
          ariaLabel={`Target distribution chart. ${summary}`}
          emptyMessage="Confirm a target column to see its distribution."
          loadingMessage="Calculating target distribution from the registered dataset..."
          errorMessage={errorMessage ?? query?.error ?? "The target distribution could not be computed."}
          unsupportedMessage="Target distribution is shown for classification targets."
        />
      </div>

      {query?.phase === "sampled" && query.sampling && (
        <div
          className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950"
          data-testid="sampled-estimate-disclosure"
        >
          <div className="font-semibold">Estimated from stratified sample</div>
          <p className="mt-1">
            {query.sampling.sampledRowCount.toLocaleString()} of {query.sampling.sourceRowCount.toLocaleString()} rows
            sampled using {query.sampling.samplingMethod.replace(/_/g, " ")} (seed {query.sampling.seed}). These are
            estimates, not exact population counts.
          </p>
          <button
            type="button"
            onClick={query.calculateExact}
            data-testid="calculate-exact-distribution"
            className="mt-2 rounded-lg border border-amber-400 bg-white px-3 py-1.5 text-xs font-semibold text-amber-900 hover:bg-amber-100"
          >
            Calculate Exact Distribution
          </button>
        </div>
      )}

      {query?.phase === "failed" && (
        <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-900" data-testid="target-distribution-error">
          <p>{query.error ?? "The target distribution could not be calculated."}</p>
          <button
            type="button"
            onClick={query.retry}
            data-testid="retry-target-distribution"
            className="mt-2 rounded-lg border border-red-300 bg-white px-3 py-1.5 text-xs font-semibold text-red-900 hover:bg-red-100"
          >
            Retry
          </button>
        </div>
      )}

      {mode === "rare-event" && (
        <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950" data-testid="rare-event-scale-disclosure">
          <span className="font-semibold">Adjusted scale:</span> {RARE_EVENT_SCALE_DISCLOSURE}
        </p>
      )}

      {distribution?.isRareEvent && (
        <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950" data-testid="rare-event-takeaway">
          {RARE_EVENT_TAKEAWAY}
        </p>
      )}

      {/* Screen-reader equivalent of the chart, always in sync with the plotted values. */}
      <p className="sr-only" data-testid="target-distribution-summary">{summary}</p>
    </section>
  );
}

function MetricCard({
  label,
  value,
  tone,
  testId,
}: {
  label: string;
  value: string;
  tone: "danger" | "info" | "neutral";
  testId?: string;
}) {
  const toneClass =
    tone === "danger" ? "text-red-900" : tone === "info" ? "text-blue-900" : "text-slate-900";
  return (
    <div className="rounded-lg border border-blue-200 bg-white px-3 py-2" data-testid={testId}>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 truncate text-sm font-semibold ${toneClass}`} title={value}>{value}</div>
    </div>
  );
}

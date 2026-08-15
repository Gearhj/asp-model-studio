import { useEffect, useMemo, useRef, useState } from "react";
import {
  Download,
  Focus,
  ScatterChart,
  ShieldCheck,
} from "lucide-react";
import {
  interpolateRgb,
  scaleLinear,
  scaleSqrt,
  select,
} from "d3";
import { useEdaVisualSelection } from "../../../state/useEdaVisualSelection";
import {
  recordEdaPerformance,
} from "../../../visual-intelligence/performance";
import {
  runAtlasD3Transition,
} from "../../../visual-intelligence/motion";
import { useReducedMotion } from "../../../visual-intelligence/useReducedMotion";
import {
  buildAuthorizedPredictorVisualData,
  downloadPredictorCsv,
  formatPredictorMetric,
  metricValue,
  predictorCsv,
} from "./predictorVisualData";
import {
  buildPredictorVisibleLimitOptions,
  loadPersistedPredictorVisibleLimit,
  persistPredictorVisibleLimit,
  predictorVisibleLimitStorageKey,
} from "./predictorVisibleLimits";
import type {
  PredictorLandscapeMetric,
  PredictorVisualDatum,
  PredictorVisualSuiteProps,
} from "./predictorVisualTypes";

const WIDTH = 920;
const HEIGHT = 430;
const MARGIN = { top: 30, right: 34, bottom: 64, left: 82 };

const METRICS: Array<{
  key: PredictorLandscapeMetric;
  label: string;
  kind: "rate" | "number" | "score";
}> = [
  { key: "signal", label: "IV / target association (Development)", kind: "score" },
  { key: "eventRateSpread", label: "Event-rate spread (Development)", kind: "rate" },
  { key: "missingRate", label: "Null missingness (Full governed)", kind: "rate" },
  { key: "outlierRate", label: "Outlier prevalence (Full governed)", kind: "rate" },
  { key: "distinctRatio", label: "Distinct-count ratio (Full governed)", kind: "rate" },
  { key: "skewness", label: "Skewness (Full governed)", kind: "number" },
  { key: "monotonicityScore", label: "Monotonic direction (Development)", kind: "number" },
  { key: "vif", label: "VIF (Development)", kind: "number" },
  { key: "specialValueRate", label: "Bureau special-value rate (Full governed)", kind: "rate" },
];

export default function PredictorSignalLandscape(
  props: PredictorVisualSuiteProps
) {
  const rows = useMemo(
    () => buildAuthorizedPredictorVisualData(props),
    [
      props.authorizedPredictors,
      props.categoricalPredictors,
      props.missingness,
      props.numericPredictors,
      props.predictorVisualContract,
      props.predictorVisualProfiles,
      props.rowCount,
      props.specialValues,
      props.target,
      props.targetSourceExcluded,
      props.vif,
    ]
  );
  const [xMetric, setXMetric] =
    useState<PredictorLandscapeMetric>("signal");
  const [yMetric, setYMetric] =
    useState<PredictorLandscapeMetric>("eventRateSpread");
  const [rankMetric, setRankMetric] =
    useState<PredictorLandscapeMetric>("signal");
  const rankMetricLabel =
    METRICS.find((metric) => metric.key === rankMetric)?.label ?? "selected ranking metric";
  const visibleLimitStorageKey = useMemo(
    () =>
      predictorVisibleLimitStorageKey(
        props.datasetVersion,
        props.target,
      ),
    [props.datasetVersion, props.target]
  );
  const visibleLimitOptions = useMemo(
    () => buildPredictorVisibleLimitOptions(rows.length),
    [rows.length]
  );
  const [limit, setLimit] = useState(() =>
    loadPersistedPredictorVisibleLimit(
      typeof window === "undefined" ? null : window.localStorage,
      visibleLimitStorageKey,
      rows.length,
    )
  );
  const [activeFeature, setActiveFeature] = useState<string | null>(null);
  const selectedVariable = useEdaVisualSelection(
    (state) => state.selectedVariable
  );
  const setSelectedVariable = useEdaVisualSelection(
    (state) => state.setSelectedVariable
  );
  const setHover = useEdaVisualSelection((state) => state.setHover);
  const reducedMotion = useReducedMotion();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const readyStartedAt = useRef(
    typeof performance === "undefined" ? 0 : performance.now()
  );
  const readyRecorded = useRef(false);

  useEffect(() => {
    setLimit(
      loadPersistedPredictorVisibleLimit(
        typeof window === "undefined" ? null : window.localStorage,
        visibleLimitStorageKey,
        rows.length,
      ),
    );
  }, [rows.length, visibleLimitStorageKey]);

  const visible = useMemo(
    () =>
      [...rows]
        .sort(
          (left, right) =>
            Math.abs(metricValue(right, rankMetric)) -
              Math.abs(metricValue(left, rankMetric)) ||
            left.feature.localeCompare(right.feature)
        )
        .slice(0, Math.min(limit, rows.length)),
    [limit, rankMetric, rows]
  );
  const xValues = visible.map((row) => metricValue(row, xMetric));
  const yValues = visible.map((row) => metricValue(row, yMetric));
  const xDomain = paddedDomain(xValues);
  const yDomain = paddedDomain(yValues);
  const x = scaleLinear()
    .domain(xDomain)
    .nice()
    .range([MARGIN.left, WIDTH - MARGIN.right]);
  const y = scaleLinear()
    .domain(yDomain)
    .nice()
    .range([HEIGHT - MARGIN.bottom, MARGIN.top]);
  const radius = scaleSqrt()
    .domain([0, Math.max(1, ...visible.map((row) => row.distinctCount))])
    .range([6, 18]);
  const xConfig = metricConfig(xMetric);
  const yConfig = metricConfig(yMetric);
  const active =
    visible.find((row) => row.feature === activeFeature) ??
    visible.find((row) => row.feature === selectedVariable) ??
    null;

  useEffect(() => {
    if (!svgRef.current || !visible.length) return;
    const marks = select(svgRef.current).selectAll<
      SVGCircleElement,
      unknown
    >("[data-landscape-mark]");
    if (!reducedMotion) marks.attr("r", 0).style("opacity", 0);
    const transition = runAtlasD3Transition(
      marks,
      (target) =>
        target
          .attr("r", function () {
            return Number(
              (this as SVGCircleElement).dataset.radius ?? 6
            );
          })
          .style("opacity", 1),
      {
        chartId: "predictor-signal-landscape",
        channel: "bubbles",
        kind: "enter",
        reducedMotion,
        markCount: visible.length,
      }
    );
    if (!readyRecorded.current) {
      readyRecorded.current = true;
      recordEdaPerformance("predictor-landscape-ready", readyStartedAt.current, {
        chart: "predictor-signal-landscape",
        phase: "ready",
        predictorCount: visible.length,
        reducedMotion,
      });
    }
    return transition.cancel;
  }, [reducedMotion, visible, xMetric, yMetric]);

  function selectPredictor(row: PredictorVisualDatum) {
    const startedAt =
      typeof performance === "undefined" ? 0 : performance.now();
    setSelectedVariable(row.feature, "input");
    setActiveFeature(row.feature);
    window.requestAnimationFrame(() => {
      recordEdaPerformance("interaction-response", startedAt, {
        chart: "predictor-signal-landscape",
        phase: "painted-selection-response",
        feature: row.feature,
      });
    });
  }

  function changeVisibleLimit(nextLimit: number) {
    setLimit(nextLimit);
    persistPredictorVisibleLimit(
      typeof window === "undefined" ? null : window.localStorage,
      visibleLimitStorageKey,
      nextLimit,
    );
  }

  if (!rows.length) {
    return <PredictorLandscapeEmpty />;
  }

  return (
    <section
      className={`overflow-hidden rounded-2xl border border-indigo-200 bg-white shadow-sm ${props.className ?? ""}`}
      data-testid="predictor-signal-landscape"
      data-visible-count={visible.length}
    >
      <header className="border-b border-indigo-100 bg-indigo-50/70 px-5 py-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div className="flex items-center gap-2 text-indigo-700">
              <ScatterChart size={18} aria-hidden="true" />
              <span className="text-xs font-semibold uppercase tracking-[0.14em]">
                Cross-predictor signal
              </span>
            </div>
            <h3 className="mt-1 text-lg font-semibold text-slate-950">
              Predictor Signal Landscape
            </h3>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
              Which predictors stand out? Compare signal, target shape, and
              quality dimensions. Bubble size represents distinct-count scale;
              color represents null missingness. This is a governed mixed-scope
              view: IV, event-rate shape, monotonicity, and VIF use the
              Development Population; missingness, outliers, and distinct counts
              use the Full Governed Population.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 font-semibold text-emerald-800">
              <ShieldCheck size={13} aria-hidden="true" />
              Mixed scope · Development signal · Full governed structure
            </span>
            <button
              type="button"
              className="atlas-secondary-button"
              onClick={() =>
                downloadPredictorCsv(
                  "atlas-predictor-signal-landscape.csv",
                  predictorCsv(visible, [
                    "signal",
                    "iv",
                    "correlation",
                    "eventRateSpread",
                    "missingRate",
                    "outlierRate",
                    "distinctRatio",
                    "monotonicity",
                    "vif",
                    "specialValueRate",
                  ])
                )
              }
            >
              <Download size={14} aria-hidden="true" />
              Export CSV
            </button>
          </div>
        </div>
        <p className="mt-3 rounded-lg border border-indigo-100 bg-white px-3 py-2 text-xs leading-5 text-slate-600">
          This view supports investigation; it does not select, retain, or drop
          model features automatically.
        </p>
      </header>

      <div className="grid gap-3 border-b border-slate-100 px-5 py-3 md:grid-cols-4">
        <MetricSelect
          label="Horizontal axis"
          value={xMetric}
          onChange={setXMetric}
        />
        <MetricSelect
          label="Vertical axis"
          value={yMetric}
          onChange={setYMetric}
        />
        <MetricSelect
          label="Rank visible predictors"
          value={rankMetric}
          onChange={setRankMetric}
        />
        <label className="grid gap-1 text-xs font-semibold text-slate-600">
          Visible predictors
          <select
            className="atlas-input"
            value={limit}
            onChange={(event) =>
              changeVisibleLimit(Number(event.target.value))
            }
            data-testid="predictor-visible-limit"
            data-option-count={visibleLimitOptions.length}
          >
            {visibleLimitOptions.map((value) => (
              <option key={value} value={value}>
                Top {value}
              </option>
            ))}
          </select>
          <span className="text-[11px] font-normal leading-4 text-slate-500">
            Top means highest-ranked by the current ranking criterion:{" "}
            <strong>{rankMetricLabel}</strong>.
          </span>
        </label>
      </div>

      <div className="relative px-3 pb-2 pt-4">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-auto min-h-[330px] w-full"
          role="img"
          aria-labelledby="predictor-landscape-title predictor-landscape-desc"
        >
          <title id="predictor-landscape-title">
            Predictor Signal Landscape
          </title>
          <desc id="predictor-landscape-desc">
            Interactive mixed-scope bubble plot of authorized predictors.
            Target-directed signal uses the Development Population while
            structural quality counts use the Full Governed Population. Use Tab
            to focus a predictor and Enter or Space to synchronize it with the
            Distribution Explorer.
          </desc>
          {x.ticks(6).map((tick) => (
            <g key={`x-${tick}`}>
              <line
                x1={x(tick)}
                x2={x(tick)}
                y1={MARGIN.top}
                y2={HEIGHT - MARGIN.bottom}
                stroke="#e2e8f0"
              />
              <text
                x={x(tick)}
                y={HEIGHT - MARGIN.bottom + 22}
                textAnchor="middle"
                className="fill-slate-500 text-[11px]"
              >
                {formatPredictorMetric(tick, xConfig.kind)}
              </text>
            </g>
          ))}
          {y.ticks(5).map((tick) => (
            <g key={`y-${tick}`}>
              <line
                x1={MARGIN.left}
                x2={WIDTH - MARGIN.right}
                y1={y(tick)}
                y2={y(tick)}
                stroke="#e2e8f0"
              />
              <text
                x={MARGIN.left - 12}
                y={y(tick) + 4}
                textAnchor="end"
                className="fill-slate-500 text-[11px]"
              >
                {formatPredictorMetric(tick, yConfig.kind)}
              </text>
            </g>
          ))}
          <text
            x={(MARGIN.left + WIDTH - MARGIN.right) / 2}
            y={HEIGHT - 12}
            textAnchor="middle"
            className="fill-slate-700 text-xs font-semibold"
          >
            {xConfig.label}
          </text>
          <text
            transform={`translate(18 ${(MARGIN.top + HEIGHT - MARGIN.bottom) / 2}) rotate(-90)`}
            textAnchor="middle"
            className="fill-slate-700 text-xs font-semibold"
          >
            {yConfig.label}
          </text>
          {visible.map((row) => {
            const isSelected = row.feature === selectedVariable;
            const isActive = row.feature === activeFeature;
            const markRadius = radius(row.distinctCount);
            const fill = interpolateRgb(
              "#2563eb",
              "#dc2626"
            )(Math.min(1, row.missingRate * 5));
            return (
              <g key={row.feature}>
                {isSelected ? (
                  <circle
                    cx={x(metricValue(row, xMetric))}
                    cy={y(metricValue(row, yMetric))}
                    r={markRadius + 6}
                    fill="none"
                    stroke="#0f172a"
                    strokeWidth={2}
                    strokeDasharray="3 3"
                    aria-hidden="true"
                  />
                ) : null}
                <circle
                  data-landscape-mark
                  data-feature={row.feature}
                  data-selected={isSelected ? "true" : "false"}
                  data-radius={markRadius}
                  cx={x(metricValue(row, xMetric))}
                  cy={y(metricValue(row, yMetric))}
                  r={markRadius}
                  fill={fill}
                  fillOpacity={isSelected || isActive ? 0.95 : 0.72}
                  stroke={isSelected ? "#0f172a" : "#ffffff"}
                  strokeWidth={isSelected ? 3 : 1.5}
                  className="cursor-pointer outline-none transition-[fill-opacity,stroke-width] duration-150 focus-visible:stroke-indigo-950 motion-reduce:transition-none"
                  role="button"
                  tabIndex={0}
                  aria-label={landscapeAriaLabel(row, xConfig, yConfig)}
                  onMouseEnter={() => {
                    setActiveFeature(row.feature);
                    setHover({
                      kind: "variable",
                      variable: row.feature,
                      source: "input",
                    });
                  }}
                  onMouseLeave={() => {
                    setActiveFeature(null);
                    setHover(null);
                  }}
                  onFocus={() => {
                    setActiveFeature(row.feature);
                    setHover({
                      kind: "variable",
                      variable: row.feature,
                      source: "keyboard",
                    });
                  }}
                  onBlur={() => {
                    setActiveFeature(null);
                    setHover(null);
                  }}
                  onClick={() => selectPredictor(row)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      selectPredictor(row);
                    }
                  }}
                >
                  <title>{landscapeAriaLabel(row, xConfig, yConfig)}</title>
                </circle>
                {(isSelected || isActive) && (
                  <text
                    x={x(metricValue(row, xMetric))}
                    y={y(metricValue(row, yMetric)) - markRadius - 8}
                    textAnchor="middle"
                    className="pointer-events-none fill-slate-950 text-[11px] font-semibold"
                  >
                    {shortLabel(row.feature)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        <div className="mx-2 mb-3 grid gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs sm:grid-cols-3">
          <div>
            <div className="font-semibold text-slate-900">
              {active?.feature ?? "Focus or hover a predictor"}
            </div>
            <div className="mt-1 text-slate-600">
              {active
                ? `${xConfig.label}: ${formatPredictorMetric(
                    metricValue(active, xMetric),
                    xConfig.kind
                  )}`
                : "Raw metric details appear here."}
            </div>
          </div>
          <div className="text-slate-600">
            {active
              ? `${yConfig.label}: ${formatPredictorMetric(
                  metricValue(active, yMetric),
                  yConfig.kind
                )}`
              : "Bubble size: distinct-count scale"}
          </div>
          <div className="text-slate-600">
            {active
              ? active.reviewSignals.length
                ? `Review: ${active.reviewSignals.join(", ")}`
                : "No configured review threshold triggered"
              : "Blue → red: increasing null missingness"}
          </div>
        </div>
      </div>

      <details className="border-t border-slate-100 px-5 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-indigo-700">
          Accessible predictor comparison table
        </summary>
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full text-left text-xs">
            <thead className="bg-slate-100 text-slate-600">
              <tr>
                {[
                  "Predictor",
                  xConfig.label,
                  yConfig.label,
                  "Missing",
                  "Distinct",
                  "Review signals",
                ].map((label) => (
                  <th key={label} className="px-3 py-2 font-semibold">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr
                  key={row.feature}
                  data-feature={row.feature}
                  data-selected={
                    row.feature === selectedVariable ? "true" : "false"
                  }
                  className={
                    row.feature === selectedVariable
                      ? "bg-indigo-50"
                      : "border-t border-slate-100"
                  }
                >
                  <td className="px-3 py-2 font-semibold text-slate-900">
                    <button
                      type="button"
                      className="text-left hover:text-indigo-700"
                      onClick={() => selectPredictor(row)}
                    >
                      {row.feature}
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    {formatPredictorMetric(
                      metricValue(row, xMetric),
                      xConfig.kind
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {formatPredictorMetric(
                      metricValue(row, yMetric),
                      yConfig.kind
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {formatPredictorMetric(row.missingRate, "rate")}
                  </td>
                  <td className="px-3 py-2">
                    {row.distinctCount.toLocaleString()}
                  </td>
                  <td className="px-3 py-2">
                    {row.reviewSignals.join(", ") || "None"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

function MetricSelect({
  label,
  value,
  onChange,
}: {
  label: string;
  value: PredictorLandscapeMetric;
  onChange: (value: PredictorLandscapeMetric) => void;
}) {
  return (
    <label className="grid gap-1 text-xs font-semibold text-slate-600">
      {label}
      <select
        className="atlas-input"
        value={value}
        onChange={(event) =>
          onChange(event.target.value as PredictorLandscapeMetric)
        }
      >
        {METRICS.map((metric) => (
          <option key={metric.key} value={metric.key}>
            {metric.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function metricConfig(metric: PredictorLandscapeMetric) {
  return (
    METRICS.find((candidate) => candidate.key === metric) ?? METRICS[0]
  );
}

function paddedDomain(values: number[]): [number, number] {
  const finiteValues = values.filter(Number.isFinite);
  if (!finiteValues.length) return [0, 1];
  const minimum = Math.min(...finiteValues);
  const maximum = Math.max(...finiteValues);
  if (minimum === maximum) {
    const padding = Math.max(0.05, Math.abs(minimum) * 0.1);
    return [minimum - padding, maximum + padding];
  }
  const padding = (maximum - minimum) * 0.08;
  return [minimum - padding, maximum + padding];
}

function landscapeAriaLabel(
  row: PredictorVisualDatum,
  xConfig: (typeof METRICS)[number],
  yConfig: (typeof METRICS)[number]
) {
  return [
    row.feature,
    "governed mixed scope: Development Population signal and Full Governed Population structure",
    `${xConfig.label} ${formatPredictorMetric(
      metricValue(row, xConfig.key),
      xConfig.kind
    )}`,
    `${yConfig.label} ${formatPredictorMetric(
      metricValue(row, yConfig.key),
      yConfig.kind
    )}`,
    `missingness ${formatPredictorMetric(row.missingRate, "rate")}`,
    row.reviewSignals.length
      ? `review signals ${row.reviewSignals.join(", ")}`
      : "no configured review threshold triggered",
    "Activate to open this predictor in the Distribution Explorer",
  ].join(". ");
}

function shortLabel(value: string) {
  return value.length > 24 ? `${value.slice(0, 22)}…` : value;
}

function PredictorLandscapeEmpty() {
  return (
    <section
      className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6"
      data-testid="predictor-signal-landscape"
    >
      <div className="flex items-center gap-2 text-slate-900">
        <Focus size={18} aria-hidden="true" />
        <h3 className="font-semibold">Predictor Signal Landscape</h3>
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-600">
        No server-authorized predictor aggregates are available. The visual
        fails closed rather than displaying the target or an excluded
        target-source field.
      </p>
    </section>
  );
}

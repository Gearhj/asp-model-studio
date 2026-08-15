import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Download,
  Grid3X3,
  LineChart,
  ShieldCheck,
} from "lucide-react";
import {
  curveMonotoneX,
  interpolateRgb,
  line,
  scaleLinear,
  select,
} from "d3";
import { useEdaVisualSelection } from "../../../state/useEdaVisualSelection";
import { runAtlasD3Transition } from "../../../visual-intelligence/motion";
import { recordEdaPerformance } from "../../../visual-intelligence/performance";
import { useReducedMotion } from "../../../visual-intelligence/useReducedMotion";
import {
  buildAuthorizedPredictorVisualData,
  downloadPredictorCsv,
  formatPredictorMetric,
  PREDICTOR_GALLERY_MAX,
  PREDICTOR_MATRIX_MAX_ROWS,
  predictorCsv,
} from "./predictorVisualData";
import type {
  PredictorVisualDatum,
  PredictorVisualSuiteProps,
} from "./predictorVisualTypes";

export default function PredictorSecondaryInsights(
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

  if (!rows.length) {
    return (
      <section
        className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6"
        data-testid="predictor-secondary-insights"
      >
        <h3 className="font-semibold text-slate-950">
          Secondary predictor insights
        </h3>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          No server-authorized predictor aggregates are available. Secondary
          visuals fail closed and never substitute the target or an excluded
          target-source field.
        </p>
      </section>
    );
  }

  return (
    <div
      className={`space-y-5 ${props.className ?? ""}`}
      data-testid="predictor-secondary-insights"
      data-aggregate-boundary="single-batched-predictor-response"
    >
      <EventRateShapeGallery
        rows={rows}
        populationEventRate={props.populationEventRate ?? null}
      />
      <PredictorQualityMatrix rows={rows} />
      <MissingnessSpecialValueMap rows={rows} />
    </div>
  );
}

export function EventRateShapeGallery({
  rows,
  populationEventRate,
}: {
  rows: PredictorVisualDatum[];
  populationEventRate: number | null;
}) {
  const [limit, setLimit] = useState(8);
  const [activeFeature, setActiveFeature] = useState<string | null>(null);
  const selectedVariable = useEdaVisualSelection(
    (state) => state.selectedVariable
  );
  const setSelectedVariable = useEdaVisualSelection(
    (state) => state.setSelectedVariable
  );
  const setHover = useEdaVisualSelection((state) => state.setHover);
  const reducedMotion = useReducedMotion();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const galleryRows = useMemo(
    () =>
      rows
        .filter(
          (row) =>
            row.eventRateBins.filter((bin) => bin.eventRate !== null).length >=
            2
        )
        .sort(
          (left, right) =>
            right.signal - left.signal ||
            left.feature.localeCompare(right.feature)
        )
        .slice(0, Math.min(limit, PREDICTOR_GALLERY_MAX)),
    [limit, rows]
  );
  const selectedGalleryRow =
    galleryRows.find((row) => row.feature === selectedVariable) ??
    rows.find((row) => row.feature === selectedVariable) ??
    galleryRows[0] ??
    null;
  const liftTableRows = selectedGalleryRow ? [selectedGalleryRow] : [];
  const baseline =
    weightedBaseline(selectedGalleryRow ?? galleryRows[0]) ??
    (galleryRows.length ? null : finite(populationEventRate));
  const maximumRate = Math.max(
    0.01,
    baseline ?? 0,
    ...galleryRows.flatMap((row) =>
      row.eventRateBins.map((bin) => bin.eventRate ?? 0)
    )
  );
  const y = scaleLinear()
    .domain([0, Math.min(1, maximumRate * 1.12)])
    .range([106, 12]);

  useEffect(() => {
    if (!containerRef.current || !galleryRows.length) return;
    const paths = select(containerRef.current).selectAll<
      SVGPathElement,
      unknown
    >("[data-event-shape-line]");
    if (!reducedMotion) {
      paths
        .attr("stroke-dasharray", "360 360")
        .attr("stroke-dashoffset", 360)
        .style("opacity", 0.35);
    }
    const transition = runAtlasD3Transition(
      paths,
      (target) =>
        target.attr("stroke-dashoffset", 0).style("opacity", 1),
      {
        chartId: "event-rate-shape-gallery",
        channel: "sparklines",
        kind: "enter",
        reducedMotion,
        markCount: galleryRows.length,
      }
    );
    return transition.cancel;
  }, [galleryRows, reducedMotion]);

  function choose(row: PredictorVisualDatum) {
    const startedAt =
      typeof performance === "undefined" ? 0 : performance.now();
    setSelectedVariable(row.feature, "input");
    setActiveFeature(row.feature);
    window.requestAnimationFrame(() => {
      recordEdaPerformance("interaction-response", startedAt, {
        chart: "event-rate-shape-gallery",
        phase: "painted-selection-response",
        feature: row.feature,
      });
    });
  }

  return (
    <InsightSection
      testId="event-rate-shape-gallery"
      anchorId="eda-predictors-shape-gallery"
      icon={<LineChart size={18} aria-hidden="true" />}
      eyebrow="Target behavior comparison"
      title="Event-Rate Shape Gallery"
      question="How does target behavior vary across predictors?"
      scopeNote="Development Population · target-directed event-rate bands and baseline · sealed final holdout excluded"
      action={
        <div className="flex flex-wrap gap-2">
          <label className="flex items-center gap-2 text-xs font-semibold text-slate-600">
            Show
            <select
              className="atlas-input py-1.5"
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value))}
            >
              {[6, 8, 10].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="atlas-secondary-button"
            onClick={() =>
              downloadPredictorCsv(
                "atlas-event-rate-shape-gallery.csv",
                eventShapeCsv(galleryRows)
              )
            }
          >
            <Download size={14} aria-hidden="true" />
            Export CSV
          </button>
        </div>
      }
    >
      {!galleryRows.length ? (
        <p className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-sm leading-6 text-slate-600">
          Quantile event-rate aggregates are unavailable. ATLAS does not issue
          one request per predictor to synthesize this gallery.
        </p>
      ) : (
        <>
          <div
            ref={containerRef}
            className="grid gap-3 md:grid-cols-2 xl:grid-cols-4"
          >
            {galleryRows.map((row) => {
              const x = scaleLinear()
                .domain([
                  0,
                  Math.max(1, row.eventRateBins.length - 1),
                ])
                .range([12, 214]);
              const path = line<(typeof row.eventRateBins)[number]>()
                .defined((bin) => bin.eventRate !== null)
                .x((_bin, index) => x(index))
                .y((bin) => y(bin.eventRate ?? 0))
                .curve(curveMonotoneX)(row.eventRateBins);
              const isSelected = selectedVariable === row.feature;
              const isActive = activeFeature === row.feature;
              return (
                <button
                  key={row.feature}
                  type="button"
                  onClick={() => choose(row)}
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
                  className={`rounded-xl border p-3 text-left outline-none transition ${
                    isSelected
                      ? "border-indigo-500 bg-indigo-50 ring-2 ring-indigo-100"
                      : "border-slate-200 bg-white hover:border-indigo-300"
                  } focus-visible:ring-2 focus-visible:ring-indigo-500 motion-reduce:transition-none`}
                  aria-label={`${shapeSummary(row)}. Activate to open ${row.feature} in the Distribution Explorer.`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span
                      className="truncate text-sm font-semibold text-slate-950"
                      title={row.feature}
                    >
                      {row.feature}
                    </span>
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                        row.monotonicity.toLowerCase().includes("non")
                          ? "bg-amber-100 text-amber-800"
                          : "bg-emerald-100 text-emerald-800"
                      }`}
                    >
                      {row.monotonicity}
                    </span>
                  </div>
                  <svg
                    viewBox="0 0 226 120"
                    className="mt-2 h-28 w-full"
                    role="img"
                    aria-label={shapeSummary(row)}
                  >
                    {baseline !== null ? (
                      <line
                        x1={12}
                        x2={214}
                        y1={y(baseline)}
                        y2={y(baseline)}
                        stroke="#94a3b8"
                        strokeDasharray="4 3"
                      />
                    ) : null}
                    <path
                      data-event-shape-line
                      d={path ?? ""}
                      fill="none"
                      stroke={isSelected ? "#4338ca" : "#2563eb"}
                      strokeWidth={isSelected || isActive ? 3 : 2.25}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    {row.eventRateBins.map((bin, index) =>
                      bin.eventRate === null ? null : (
                        <circle
                          key={`${row.feature}-${index}`}
                          cx={x(index)}
                          cy={y(bin.eventRate)}
                          r={isActive ? 4 : 3}
                          fill="#ffffff"
                          stroke="#1d4ed8"
                          strokeWidth={2}
                        >
                          <title>
                            {bin.label}:{" "}
                            {formatPredictorMetric(bin.eventRate, "rate")},{" "}
                            {bin.count.toLocaleString()} rows
                          </title>
                        </circle>
                      )
                    )}
                  </svg>
                  <div className="mt-1 flex items-center justify-between text-[11px] text-slate-500">
                    <span>
                      Spread{" "}
                      {formatPredictorMetric(row.eventRateSpread, "rate")}
                    </span>
                    <span>{row.eventRateBins.length} bands</span>
                  </div>
                </button>
              );
            })}
          </div>
          <p className="mt-3 text-xs leading-5 text-slate-500">
            Dashed line: Development Population event-rate baseline. Curves use the
            quantile aggregates already returned in the single Predictor
            response; no per-predictor chart request is issued.
          </p>
          <div
            className="mt-4 overflow-hidden rounded-xl border border-blue-200 bg-blue-50/30"
            data-testid="eda-iv-by-bin"
            data-primary-analysis="true"
            data-visible-by-default="true"
          >
            <button
              type="button"
              className="flex w-full items-center justify-between bg-blue-50/70 px-4 py-3 text-left"
              data-testid="eda-iv-by-bin-toggle"
            >
              <span>
                <span className="text-sm font-semibold text-slate-950">
                  IV by bin · Development Population
                </span>
                <span className="ml-2 text-xs text-slate-500">
                  {selectedGalleryRow
                    ? `${selectedGalleryRow.feature} lift detail; sealed final holdout excluded`
                    : "Associated event-rate lift detail; sealed final holdout excluded"}
                </span>
              </span>
              <span className="text-xs font-semibold text-blue-700">
                Visible
              </span>
            </button>
            <EventRateLiftTable
              rows={liftTableRows}
              fallbackBaseline={populationEventRate}
            />
          </div>
        </>
      )}
    </InsightSection>
  );
}

function EventRateLiftTable({
  rows,
  fallbackBaseline,
}: {
  rows: PredictorVisualDatum[];
  fallbackBaseline: number | null;
}) {
  const selectedRow = rows[0] ?? null;
  if (selectedRow) {
    const baseline = weightedBaseline(selectedRow) ?? finite(fallbackBaseline);
    const usableBins = selectedRow.eventRateBins.filter(
      (bin) => bin.eventRate !== null && bin.count > 0,
    );
    const highest = usableBins.reduce<(typeof usableBins)[number] | null>(
      (best, bin) =>
        best === null || (bin.eventRate ?? -Infinity) > (best.eventRate ?? -Infinity)
          ? bin
          : best,
      null,
    );
    return (
      <div className="mt-0 overflow-x-auto rounded-b-xl border-t border-slate-200 bg-white">
        <div className="border-b border-slate-200 bg-slate-50 px-3 py-2">
          <h4 className="text-sm font-semibold text-slate-950">
            Associated lift table · {selectedRow.feature}
          </h4>
          <p className="mt-1 text-xs text-slate-600">
            Highest-risk band: {highest?.label ?? "Not available"}. Lift compares each
            development-population band against this predictor&apos;s weighted baseline.
            The sealed final holdout is excluded.
          </p>
        </div>
        <table className="min-w-full text-sm" data-testid="event-rate-shape-lift-table">
          <thead className="bg-slate-950 text-left text-[11px] uppercase tracking-wide text-white">
            <tr>
              <th className="px-3 py-2">Band</th>
              <th className="px-3 py-2 text-right">Development rows</th>
              <th className="px-3 py-2 text-right">Event rate</th>
              <th className="px-3 py-2 text-right">Baseline</th>
              <th className="px-3 py-2 text-right">Lift</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {selectedRow.eventRateBins.map((bin) => {
              const lift =
                baseline && baseline > 0 && bin.eventRate !== null
                  ? bin.eventRate / baseline
                  : null;
              return (
                <tr key={`${selectedRow.feature}-${bin.label}`}>
                  <td className="px-3 py-2 font-semibold text-slate-950">
                    {bin.label}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {bin.count.toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatPredictorMetric(bin.eventRate, "rate")}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatPredictorMetric(baseline, "rate")}
                  </td>
                  <td className="px-3 py-2 text-right font-semibold tabular-nums text-blue-700">
                    {lift === null ? "Not available" : `${lift.toFixed(2)}x`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }
  const liftRows = rows.map((row) => {
    const baseline = weightedBaseline(row) ?? finite(fallbackBaseline);
    const usableBins = row.eventRateBins.filter(
      (bin) => bin.eventRate !== null && bin.count > 0,
    );
    const highest = usableBins.reduce<(typeof usableBins)[number] | null>(
      (best, bin) =>
        best === null || (bin.eventRate ?? -Infinity) > (best.eventRate ?? -Infinity)
          ? bin
          : best,
      null,
    );
    const lowest = usableBins.reduce<(typeof usableBins)[number] | null>(
      (best, bin) =>
        best === null || (bin.eventRate ?? Infinity) < (best.eventRate ?? Infinity)
          ? bin
          : best,
      null,
    );
    return { row, baseline, highest, lowest };
  });

  return (
    <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <div className="border-b border-slate-200 bg-slate-50 px-3 py-2">
        <h4 className="text-sm font-semibold text-slate-950">
          Associated lift table
        </h4>
        <p className="mt-1 text-xs text-slate-600">
          Lift compares each predictor&apos;s highest development-population band
          against its weighted development baseline. The sealed final holdout is excluded.
        </p>
      </div>
      <table className="min-w-full text-sm" data-testid="event-rate-shape-lift-table">
        <thead className="bg-slate-950 text-left text-[11px] uppercase tracking-wide text-white">
          <tr>
            <th className="px-3 py-2">Predictor</th>
            <th className="px-3 py-2 text-right">Baseline</th>
            <th className="px-3 py-2">Highest-risk band</th>
            <th className="px-3 py-2 text-right">Highest rate</th>
            <th className="px-3 py-2 text-right">Lift</th>
            <th className="px-3 py-2">Lowest-risk band</th>
            <th className="px-3 py-2 text-right">Spread</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {liftRows.map(({ row, baseline, highest, lowest }) => {
            const lift =
              baseline && baseline > 0 && highest?.eventRate !== null && highest?.eventRate !== undefined
                ? highest.eventRate / baseline
                : null;
            return (
              <tr key={row.feature} className="align-top">
                <td className="px-3 py-2 font-semibold text-slate-950">
                  {row.feature}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatPredictorMetric(baseline, "rate")}
                </td>
                <td className="px-3 py-2">
                  {highest?.label ?? "Not available"}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatPredictorMetric(highest?.eventRate ?? null, "rate")}
                </td>
                <td className="px-3 py-2 text-right font-semibold tabular-nums text-blue-700">
                  {lift === null ? "Not available" : `${lift.toFixed(2)}x`}
                </td>
                <td className="px-3 py-2">
                  {lowest?.label ?? "Not available"}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatPredictorMetric(row.eventRateSpread, "rate")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

type MatrixMetric = {
  key: string;
  label: string;
  value: (row: PredictorVisualDatum) => number | null;
  format: (value: number | null) => string;
};

const MATRIX_METRICS: MatrixMetric[] = [
  {
    key: "iv",
    label: "IV",
    value: (row) => row.iv,
    format: (value) => formatPredictorMetric(value, "score"),
  },
  {
    key: "missing",
    label: "Missing",
    value: (row) => row.missingRate,
    format: (value) => formatPredictorMetric(value, "rate"),
  },
  {
    key: "outlier",
    label: "Outlier",
    value: (row) => row.outlierRate,
    format: (value) => formatPredictorMetric(value, "rate"),
  },
  {
    key: "distinct",
    label: "Distinct",
    value: (row) => row.distinctRatio,
    format: (value) => formatPredictorMetric(value, "rate"),
  },
  {
    key: "skew",
    label: "|Skew|",
    value: (row) =>
      row.skewness === null ? null : Math.abs(row.skewness),
    format: (value) => formatPredictorMetric(value),
  },
  {
    key: "monotonic",
    label: "Shape",
    value: (row) =>
      row.monotonicity === "Not evaluated"
        ? null
        : Math.abs(row.monotonicityScore),
    format: (_value) => "See shape label",
  },
  {
    key: "vif",
    label: "VIF",
    value: (row) => row.vif,
    format: (value) => formatPredictorMetric(value),
  },
  {
    key: "special",
    label: "Special",
    value: (row) => row.specialValueRate,
    format: (value) => formatPredictorMetric(value, "rate"),
  },
];

export function PredictorQualityMatrix({
  rows,
}: {
  rows: PredictorVisualDatum[];
}) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState("review");
  const [reviewOnly, setReviewOnly] = useState(false);
  const [activeCell, setActiveCell] = useState<{
    feature: string;
    metric: string;
  } | null>(null);
  const selectedVariable = useEdaVisualSelection(
    (state) => state.selectedVariable
  );
  const setSelectedVariable = useEdaVisualSelection(
    (state) => state.setSelectedVariable
  );
  const setHover = useEdaVisualSelection((state) => state.setHover);
  const reducedMotion = useReducedMotion();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const normalizedSearch = search.trim().toLowerCase();
  const domains = useMemo(
    () =>
      new Map(
        MATRIX_METRICS.map((metric) => {
          const values = rows
            .map(metric.value)
            .filter((value): value is number => value !== null);
          return [
            metric.key,
            [
              Math.min(0, ...(values.length ? values : [0])),
              Math.max(0, ...(values.length ? values : [1])),
            ] as [number, number],
          ];
        })
      ),
    [rows]
  );
  const visible = useMemo(() => {
    const filtered = rows.filter(
      (row) =>
        (!normalizedSearch ||
          row.feature.toLowerCase().includes(normalizedSearch)) &&
        (!reviewOnly || row.reviewSignals.length > 0)
    );
    const metric = MATRIX_METRICS.find(
      (candidate) => candidate.key === sortKey
    );
    return [...filtered]
      .sort((left, right) => {
        if (sortKey === "name") {
          return left.feature.localeCompare(right.feature);
        }
        if (sortKey === "review") {
          return (
            right.reviewSignals.length - left.reviewSignals.length ||
            right.signal - left.signal
          );
        }
        return (
          Math.abs(metric?.value(right) ?? -Infinity) -
          Math.abs(metric?.value(left) ?? -Infinity)
        );
      })
      .slice(0, PREDICTOR_MATRIX_MAX_ROWS);
  }, [normalizedSearch, reviewOnly, rows, sortKey]);
  const rowHeight = 34;
  const labelWidth = 238;
  const cellWidth = 88;
  const top = 50;
  const width = labelWidth + MATRIX_METRICS.length * cellWidth + 12;
  const height = top + visible.length * rowHeight + 16;
  const activeRow = rows.find(
    (row) => row.feature === activeCell?.feature
  );
  const activeMetric = MATRIX_METRICS.find(
    (metric) => metric.key === activeCell?.metric
  );

  useEffect(() => {
    if (!svgRef.current || !visible.length) return;
    const cells = select(svgRef.current).selectAll<
      SVGRectElement,
      unknown
    >("[data-quality-cell]");
    if (!reducedMotion) cells.attr("width", 0).style("opacity", 0.25);
    const transition = runAtlasD3Transition(
      cells,
      (target) =>
        target
          .attr("width", function () {
            return Number((this as SVGRectElement).dataset.width ?? 0);
          })
          .style("opacity", 1),
      {
        chartId: "predictor-quality-matrix",
        channel: "cells",
        kind: "enter",
        reducedMotion,
        markCount: visible.length * MATRIX_METRICS.length,
        largeData:
          visible.length * MATRIX_METRICS.length > 180,
      }
    );
    return transition.cancel;
  }, [reducedMotion, sortKey, visible]);

  function choose(row: PredictorVisualDatum, metric: MatrixMetric) {
    const startedAt =
      typeof performance === "undefined" ? 0 : performance.now();
    setActiveCell({ feature: row.feature, metric: metric.key });
    setSelectedVariable(row.feature, "input");
    window.requestAnimationFrame(() => {
      recordEdaPerformance("interaction-response", startedAt, {
        chart: "predictor-quality-matrix",
        phase: "painted-selection-response",
        feature: row.feature,
        metric: metric.key,
      });
    });
  }

  return (
    <InsightSection
      testId="predictor-quality-matrix"
      anchorId="eda-predictors-quality-matrix"
      icon={<Grid3X3 size={18} aria-hidden="true" />}
      eyebrow="Comparable quality dimensions"
      title="Predictor Quality Matrix"
      question="Where are quality or treatment risks?"
      scopeNote="Mixed scope · IV, monotonicity, and VIF use the Development Population; missingness, outliers, distinct counts, skew, and special-value burden use the Full Governed Population"
      action={
        <button
          type="button"
          className="atlas-secondary-button"
          onClick={() =>
            downloadPredictorCsv(
              "atlas-predictor-quality-matrix.csv",
              predictorCsv(visible, [
                "iv",
                "missingRate",
                "outlierRate",
                "distinctRatio",
                "skewness",
                "monotonicity",
                "vif",
                "specialValueRate",
                "reviewSignals",
              ])
            )
          }
        >
          <Download size={14} aria-hidden="true" />
          Export CSV
        </button>
      }
    >
      <div className="grid gap-3 border-b border-slate-100 pb-3 md:grid-cols-[minmax(220px,1fr)_220px_auto]">
        <label className="grid gap-1 text-xs font-semibold text-slate-600">
          Filter predictors
          <input
            className="atlas-input"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search authorized predictors"
          />
        </label>
        <label className="grid gap-1 text-xs font-semibold text-slate-600">
          Sort rows
          <select
            className="atlas-input"
            value={sortKey}
            onChange={(event) => setSortKey(event.target.value)}
          >
            <option value="review">Review burden</option>
            {MATRIX_METRICS.map((metric) => (
              <option key={metric.key} value={metric.key}>
                {metric.label}
              </option>
            ))}
            <option value="name">Predictor name</option>
          </select>
        </label>
        <label className="flex items-end gap-2 pb-2 text-xs font-semibold text-slate-700">
          <input
            type="checkbox"
            checked={reviewOnly}
            onChange={(event) => setReviewOnly(event.target.checked)}
          />
          Review-heavy only
        </label>
      </div>

      <div className="mt-3 overflow-x-auto">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${width} ${Math.max(height, 110)}`}
          className="min-w-[860px] w-full"
          role="img"
          aria-labelledby="quality-matrix-title quality-matrix-desc"
        >
          <title id="quality-matrix-title">Predictor Quality Matrix</title>
          <desc id="quality-matrix-desc">
            Governed mixed-scope normalized heatmap of authorized predictors by
            eight quality dimensions. Target-directed metrics use the Development
            Population and structural metrics use the Full Governed Population.
            Raw values are available by keyboard focus and hover.
          </desc>
          <defs>
            <pattern
              id="predictor-matrix-unavailable"
              width="6"
              height="6"
              patternUnits="userSpaceOnUse"
            >
              <rect width="6" height="6" fill="#f1f5f9" />
              <path d="M0 6L6 0" stroke="#cbd5e1" strokeWidth="1" />
            </pattern>
          </defs>
          {MATRIX_METRICS.map((metric, column) => (
            <text
              key={metric.key}
              x={labelWidth + column * cellWidth + cellWidth / 2}
              y={28}
              textAnchor="middle"
              className="fill-slate-600 text-[11px] font-semibold"
            >
              {metric.label}
            </text>
          ))}
          {visible.map((row, rowIndex) => {
            const y = top + rowIndex * rowHeight;
            const isSelected = selectedVariable === row.feature;
            return (
              <g key={row.feature}>
                <rect
                  x={2}
                  y={y - 3}
                  width={width - 8}
                  height={rowHeight - 2}
                  rx={5}
                  fill={isSelected ? "#eef2ff" : "transparent"}
                />
                {row.reviewSignals.length ? (
                  <circle
                    cx={12}
                    cy={y + 11}
                    r={4}
                    fill="#f59e0b"
                  >
                    <title>
                      {row.reviewSignals.length} configured review signal
                      {row.reviewSignals.length === 1 ? "" : "s"}
                    </title>
                  </circle>
                ) : null}
                <text
                  x={24}
                  y={y + 15}
                  className={`text-[11px] ${
                    isSelected
                      ? "fill-indigo-950 font-semibold"
                      : "fill-slate-800"
                  }`}
                >
                  {truncate(row.feature, 31)}
                </text>
                {MATRIX_METRICS.map((metric, column) => {
                  const value = metric.value(row);
                  const domain = domains.get(metric.key) ?? [0, 1];
                  const normalized = normalizedValue(value, domain);
                  const fill =
                    value === null
                      ? "url(#predictor-matrix-unavailable)"
                      : interpolateRgb("#eff6ff", "#1d4ed8")(normalized);
                  const x = labelWidth + column * cellWidth + 3;
                  const label = `${row.feature}, ${metric.label}: ${metric.format(
                    value
                  )}`;
                  const formattedValue = metric.format(value);
                  const showInlineValue =
                    value !== null &&
                    (normalized >= 0.52 ||
                      isSelected ||
                      (activeCell?.feature === row.feature &&
                        activeCell.metric === metric.key));
                  return (
                    <g key={`${row.feature}-${metric.key}`}>
                      <rect
                      key={`${row.feature}-${metric.key}`}
                      data-quality-cell
                      data-width={cellWidth - 6}
                      x={x}
                      y={y}
                      width={cellWidth - 6}
                      height={rowHeight - 8}
                      rx={4}
                      fill={fill}
                      stroke={
                        activeCell?.feature === row.feature &&
                        activeCell.metric === metric.key
                          ? "#0f172a"
                          : "#ffffff"
                      }
                      strokeWidth={2}
                      role="button"
                      tabIndex={0}
                      aria-label={`${label}. Activate to synchronize this predictor.`}
                      className="cursor-pointer outline-none focus-visible:stroke-indigo-950"
                      onMouseEnter={() => {
                        setActiveCell({
                          feature: row.feature,
                          metric: metric.key,
                        });
                        setHover({
                          kind: "variable",
                          variable: row.feature,
                          source: "input",
                        });
                      }}
                      onMouseLeave={() => {
                        setActiveCell(null);
                        setHover(null);
                      }}
                      onFocus={() => {
                        setActiveCell({
                          feature: row.feature,
                          metric: metric.key,
                        });
                        setHover({
                          kind: "variable",
                          variable: row.feature,
                          source: "keyboard",
                        });
                      }}
                      onBlur={() => {
                        setActiveCell(null);
                        setHover(null);
                      }}
                      onClick={() => choose(row, metric)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          choose(row, metric);
                        }
                      }}
                    >
                      <title>{label}</title>
                      </rect>
                      {showInlineValue ? (
                        <text
                          x={x + (cellWidth - 6) / 2}
                          y={y + (rowHeight - 8) / 2 + 4}
                          textAnchor="middle"
                          className={`pointer-events-none text-[9px] font-bold ${
                            normalized >= 0.72 ? "fill-white" : "fill-slate-700"
                          }`}
                        >
                          {formattedValue}
                        </text>
                      ) : null}
                    </g>
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>

      <div className="mt-3 grid gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs sm:grid-cols-[1fr_auto]">
        <div className="text-slate-700">
          {activeRow && activeMetric
            ? `${activeRow.feature} · ${activeMetric.label}: ${activeMetric.format(
                activeMetric.value(activeRow)
              )}`
            : "Hover or focus a cell for its raw value."}
        </div>
        <div className="text-slate-500">
          Pale → dark = low → high within each column. Hatched = unavailable.
        </div>
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-500">
        Column normalization supports comparison; it is not an automatic
        feature-selection score and does not duplicate the correlation matrix.
        Showing {visible.length} of {rows.length} authorized predictors.
      </p>

      <QualityMatrixFallback rows={visible} onSelect={setSelectedVariable} />
    </InsightSection>
  );
}

export function MissingnessSpecialValueMap({
  rows,
}: {
  rows: PredictorVisualDatum[];
}) {
  const [sortKey, setSortKey] = useState("special");
  const [reviewOnly, setReviewOnly] = useState(false);
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
  const visible = useMemo(
    () =>
      [...rows]
        .filter(
          (row) =>
            !reviewOnly ||
            row.missingRate > 0 ||
            (row.specialValueRate ?? 0) > 0 ||
            (row.outlierRate ?? 0) > 0
        )
        .sort((left, right) => {
          const value = (row: PredictorVisualDatum) =>
            sortKey === "missing"
              ? row.missingRate
              : sortKey === "outlier"
                ? row.outlierRate ?? -1
                : sortKey === "name"
                  ? 0
                  : row.specialValueRate ?? -1;
          return sortKey === "name"
            ? left.feature.localeCompare(right.feature)
            : value(right) - value(left);
        })
        .slice(0, PREDICTOR_MATRIX_MAX_ROWS),
    [reviewOnly, rows, sortKey]
  );
  const width = 940;
  const labelWidth = 250;
  const right = 52;
  const top = 48;
  const rowHeight = 34;
  const height = top + visible.length * rowHeight + 26;
  const x = scaleLinear()
    .domain([0, 1])
    .range([labelWidth, width - right]);
  const active = rows.find((row) => row.feature === activeFeature) ?? null;

  useEffect(() => {
    if (!svgRef.current || !visible.length) return;
    const segments = select(svgRef.current).selectAll<
      SVGRectElement,
      unknown
    >("[data-quality-segment]");
    if (!reducedMotion) segments.attr("width", 0).style("opacity", 0.35);
    const segmentTransition = runAtlasD3Transition(
      segments,
      (target) =>
        target
          .attr("width", function () {
            return Number((this as SVGRectElement).dataset.width ?? 0);
          })
          .style("opacity", 1),
      {
        chartId: "missingness-special-value-map",
        channel: "segments",
        kind: "enter",
        reducedMotion,
        markCount: visible.length * 4,
      }
    );
    return () => {
      segmentTransition.cancel();
    };
  }, [reducedMotion, sortKey, visible]);

  function choose(row: PredictorVisualDatum) {
    const startedAt =
      typeof performance === "undefined" ? 0 : performance.now();
    setSelectedVariable(row.feature, "input");
    setActiveFeature(row.feature);
    window.requestAnimationFrame(() => {
      recordEdaPerformance("interaction-response", startedAt, {
        chart: "missingness-special-value-map",
        phase: "painted-selection-response",
        feature: row.feature,
      });
    });
  }

  return (
    <InsightSection
      testId="missingness-special-value-map"
      anchorId="eda-predictors-special-values"
      icon={<AlertTriangle size={18} aria-hidden="true" />}
      eyebrow="Exceptional-value structure"
      title="Missingness / Special-Value Map"
      question="What exceptional values require treatment?"
      scopeNote="Full Governed Population · structural missingness, ordinary outliers, and bureau-special inventory"
      action={
        <button
          type="button"
          className="atlas-secondary-button"
          onClick={() =>
            downloadPredictorCsv(
              "atlas-missingness-special-value-map.csv",
              predictorCsv(visible, [
                "missingCount",
                "missingRate",
                "specialValueCount",
                "specialValueRate",
                "specialValueTreatment",
                "outlierRate",
              ])
            )
          }
        >
          <Download size={14} aria-hidden="true" />
          Export CSV
        </button>
      }
    >
      <div className="flex flex-wrap items-end gap-4 border-b border-slate-100 pb-3">
        <label className="grid min-w-52 gap-1 text-xs font-semibold text-slate-600">
          Sort predictors
          <select
            className="atlas-input"
            value={sortKey}
            onChange={(event) => setSortKey(event.target.value)}
          >
            <option value="special">Bureau special-value rate</option>
            <option value="missing">Null missingness</option>
            <option value="outlier">Ordinary numeric outlier rate</option>
            <option value="name">Predictor name</option>
          </select>
        </label>
        <label className="flex items-center gap-2 pb-2 text-xs font-semibold text-slate-700">
          <input
            type="checkbox"
            checked={reviewOnly}
            onChange={(event) => setReviewOnly(event.target.checked)}
          />
          Show exceptional-value rows only
        </label>
      </div>

      <div className="mt-3 overflow-x-auto">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${width} ${Math.max(height, 120)}`}
          className="min-w-[820px] w-full"
          role="img"
          aria-labelledby="special-map-title special-map-desc"
        >
          <title id="special-map-title">
            Missingness and Special-Value Map
          </title>
          <desc id="special-map-desc">
            Mutually exclusive ordinary inlier, ordinary outlier, null-missing,
            and bureau-special shares for authorized predictors across the Full
            Governed Population.
          </desc>
          {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
            <g key={tick}>
              <line
                x1={x(tick)}
                x2={x(tick)}
                y1={top - 8}
                y2={height - 12}
                stroke="#e2e8f0"
              />
              <text
                x={x(tick)}
                y={22}
                textAnchor="middle"
                className="fill-slate-500 text-[11px]"
              >
                {formatPredictorMetric(tick, "rate")}
              </text>
            </g>
          ))}
          {visible.map((row, index) => {
            const y = top + index * rowHeight;
            const missing = Math.min(1, row.missingRate);
            const special =
              row.specialValueRate === null
                ? null
                : Math.min(row.specialValueRate, Math.max(0, 1 - missing));
            const ordinaryOutlier = Math.min(
              row.ordinaryOutlierPopulationRate ?? 0,
              Math.max(0, 1 - missing - (special ?? 0))
            );
            const ordinaryInlier = Math.min(
              row.ordinaryInlierPopulationRate ??
                row.regularValueRate ??
                Math.max(0, 1 - missing - (special ?? 0)),
              Math.max(0, 1 - missing - (special ?? 0) - ordinaryOutlier)
            );
            const segments = [
              {
                key: "ordinary-inlier",
                label: "Ordinary in-range values",
                value: ordinaryInlier,
                fill: "#2563eb",
              },
              {
                key: "ordinary-outlier",
                label: "Ordinary numeric outliers",
                value: ordinaryOutlier,
                fill: "#be123c",
              },
              {
                key: "missing",
                label: "Null missingness",
                value: missing,
                fill: "#94a3b8",
              },
              {
                key: "special",
                label: "Bureau special values",
                value: special ?? 0,
                fill: "#f59e0b",
              },
            ];
            let offset = 0;
            const isSelected = selectedVariable === row.feature;
            return (
              <g
                key={row.feature}
                role="button"
                tabIndex={0}
                aria-label={specialMapAriaLabel(row)}
                className="cursor-pointer outline-none focus-visible:[&>rect]:stroke-indigo-950"
                onClick={() => choose(row)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    choose(row);
                  }
                }}
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
              >
                <text
                  x={8}
                  y={y + 15}
                  className={`text-[11px] ${
                    isSelected
                      ? "fill-indigo-950 font-semibold"
                      : "fill-slate-800"
                  }`}
                >
                  {truncate(row.feature, 33)}
                </text>
                <rect
                  x={labelWidth - 5}
                  y={y - 3}
                  width={width - labelWidth - right + 10}
                  height={27}
                  rx={5}
                  fill="transparent"
                  stroke={isSelected ? "#4338ca" : "transparent"}
                  strokeWidth={2}
                />
                {segments.map((segment) => {
                  const segmentX = x(offset);
                  const segmentWidth = Math.max(
                    0,
                    x(offset + segment.value) - segmentX
                  );
                  offset += segment.value;
                  return segment.value <= 0 ? null : (
                    <rect
                      key={segment.key}
                      data-quality-segment
                      data-width={segmentWidth}
                      x={segmentX}
                      y={y}
                      width={segmentWidth}
                      height={18}
                      fill={segment.fill}
                    >
                      <title>
                        {row.feature} · {segment.label}:{" "}
                        {formatPredictorMetric(segment.value, "rate")}
                      </title>
                    </rect>
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>

      <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-600">
        <Legend color="#2563eb" label="Ordinary in-range" />
        <Legend color="#be123c" label="Ordinary outlier" />
        <Legend color="#94a3b8" label="Null missing" />
        <Legend color="#f59e0b" label="Bureau special" />
      </div>
      <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
        Bureau special values are meaning-bearing values, not null missingness.
        All four stacked shares are mutually exclusive. Ordinary outliers are
        computed only over regular numeric values after nulls and bureau
        special values are excluded.
      </div>
      <div className="mt-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
        {active
          ? `${active.feature}: null missing ${formatPredictorMetric(
              active.missingRate,
              "rate"
            )}; bureau special ${
              active.specialValueRate === null
                ? "not profiled"
                : formatPredictorMetric(active.specialValueRate, "rate")
            }; treatment ${active.specialValueTreatment}; ordinary numeric outlier rate ${formatPredictorMetric(
              active.outlierRate,
              "rate"
            )}.`
          : "Hover or focus a row for treatment-state detail."}
      </div>

      <SpecialValueFallback rows={visible} onSelect={setSelectedVariable} />
    </InsightSection>
  );
}

function InsightSection({
  testId,
  anchorId,
  icon,
  eyebrow,
  title,
  question,
  scopeNote,
  action,
  children,
}: {
  testId: string;
  anchorId: string;
  icon: React.ReactNode;
  eyebrow: string;
  title: string;
  question: string;
  scopeNote: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section
      id={anchorId}
      className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
      data-testid={testId}
    >
      <header className="border-b border-slate-100 bg-slate-50/80 px-5 py-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div className="flex items-center gap-2 text-indigo-700">
              {icon}
              <span className="text-xs font-semibold uppercase tracking-[0.14em]">
                {eyebrow}
              </span>
            </div>
            <h3 className="mt-1 text-lg font-semibold text-slate-950">
              {title}
            </h3>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              {question}
            </p>
            <p
              className="mt-2 text-xs font-semibold leading-5 text-indigo-800"
              data-testid={`${testId}-scope`}
            >
              {scopeNote}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">
              <ShieldCheck size={13} aria-hidden="true" />
              Authorized · aggregate only
            </span>
            {action}
          </div>
        </div>
      </header>
      <div className="p-5">{children}</div>
    </section>
  );
}

function QualityMatrixFallback({
  rows,
  onSelect,
}: {
  rows: PredictorVisualDatum[];
  onSelect: (feature: string, source?: "input") => void;
}) {
  return (
    <details className="mt-3 border-t border-slate-100 pt-3">
      <summary className="cursor-pointer text-sm font-semibold text-indigo-700">
        Accessible quality matrix table
      </summary>
      <div className="mt-3 overflow-x-auto">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-slate-100 text-slate-600">
            <tr>
              {["Predictor", ...MATRIX_METRICS.map((metric) => metric.label)].map(
                (label) => (
                  <th key={label} className="px-3 py-2 font-semibold">
                    {label}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.feature} className="border-t border-slate-100">
                <td className="px-3 py-2 font-semibold">
                  <button
                    type="button"
                    className="text-left hover:text-indigo-700"
                    onClick={() => onSelect(row.feature, "input")}
                  >
                    {row.feature}
                  </button>
                </td>
                {MATRIX_METRICS.map((metric) => (
                  <td key={metric.key} className="px-3 py-2">
                    {metric.key === "monotonic"
                      ? row.monotonicity
                      : metric.format(metric.value(row))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function SpecialValueFallback({
  rows,
  onSelect,
}: {
  rows: PredictorVisualDatum[];
  onSelect: (feature: string, source?: "input") => void;
}) {
  return (
    <details className="mt-3 border-t border-slate-100 pt-3">
      <summary className="cursor-pointer text-sm font-semibold text-indigo-700">
        Accessible exceptional-value table
      </summary>
      <div className="mt-3 overflow-x-auto">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-slate-100 text-slate-600">
            <tr>
              {[
                "Predictor",
                "Null missing",
                "Bureau special",
                "Treatment",
                "Numeric outlier flag",
              ].map((label) => (
                <th key={label} className="px-3 py-2 font-semibold">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.feature} className="border-t border-slate-100">
                <td className="px-3 py-2 font-semibold">
                  <button
                    type="button"
                    className="text-left hover:text-indigo-700"
                    onClick={() => onSelect(row.feature, "input")}
                  >
                    {row.feature}
                  </button>
                </td>
                <td className="px-3 py-2">
                  {formatPredictorMetric(row.missingRate, "rate")}
                </td>
                <td className="px-3 py-2">
                  {formatPredictorMetric(row.specialValueRate, "rate")}
                </td>
                <td className="px-3 py-2">
                  {row.specialValueTreatment}
                </td>
                <td className="px-3 py-2">
                  {formatPredictorMetric(row.outlierRate, "rate")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function Legend({
  color,
  label,
  diamond = false,
  pattern = false,
}: {
  color?: string;
  label: string;
  diamond?: boolean;
  pattern?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`h-3 w-3 border border-white shadow-sm ${
          diamond ? "rotate-45" : "rounded-sm"
        } ${pattern ? "bg-slate-200 [background-image:linear-gradient(135deg,transparent_40%,#94a3b8_40%,#94a3b8_50%,transparent_50%)]" : ""}`}
        style={pattern ? undefined : { backgroundColor: color }}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}

function normalizedValue(
  value: number | null,
  domain: [number, number]
) {
  if (value === null) return 0;
  const [minimum, maximum] = domain;
  if (minimum === maximum) return value === 0 ? 0 : 1;
  return Math.max(0, Math.min(1, (value - minimum) / (maximum - minimum)));
}

function shapeSummary(row: PredictorVisualDatum) {
  const bands = row.eventRateBins
    .map(
      (bin) =>
        `${bin.label} ${formatPredictorMetric(bin.eventRate, "rate")}`
    )
    .join(", ");
  return `${row.feature}. ${row.monotonicity}. Event-rate spread ${formatPredictorMetric(
    row.eventRateSpread,
    "rate"
  )}. ${bands}`;
}

function weightedBaseline(row?: PredictorVisualDatum) {
  if (!row) return null;
  let population = 0;
  let events = 0;
  for (const bin of row.eventRateBins) {
    if (bin.eventRate === null || bin.count <= 0) continue;
    population += bin.count;
    events += bin.eventRate * bin.count;
  }
  return population > 0 ? events / population : null;
}

function eventShapeCsv(rows: PredictorVisualDatum[]) {
  const escape = (value: unknown) =>
    `"${String(value ?? "").replace(/"/g, '""')}"`;
  return [
    ["feature", "band", "count", "event_rate", "monotonicity"]
      .map(escape)
      .join(","),
    ...rows.flatMap((row) =>
      row.eventRateBins.map((bin) =>
        [
          row.feature,
          bin.label,
          bin.count,
          bin.eventRate,
          row.monotonicity,
        ]
          .map(escape)
          .join(",")
      )
    ),
  ].join("\n");
}

function specialMapAriaLabel(row: PredictorVisualDatum) {
  return [
    row.feature,
    `null missing ${formatPredictorMetric(row.missingRate, "rate")}`,
    `bureau special ${
      row.specialValueRate === null
        ? "not profiled"
        : formatPredictorMetric(row.specialValueRate, "rate")
    }`,
    `treatment ${row.specialValueTreatment}`,
    `ordinary numeric outlier rate ${formatPredictorMetric(
      row.outlierRate,
      "rate"
    )}`,
    "Activate to synchronize this predictor",
  ].join(". ");
}

function truncate(value: string, maximum: number) {
  return value.length > maximum ? `${value.slice(0, maximum - 1)}…` : value;
}

function finite(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

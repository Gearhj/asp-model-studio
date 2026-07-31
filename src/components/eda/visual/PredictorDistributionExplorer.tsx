import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import {
  AlertTriangle,
  BarChart3,
  Check,
  Download,
  RefreshCw,
  RotateCcw,
} from "lucide-react";
import {
  ATLAS_MOTION_TOKENS,
  createChartMotionController,
  runAtlasD3Transition,
} from "../../../visual-intelligence/motion";
import { useReducedMotion } from "../../../visual-intelligence/useReducedMotion";
import { recordEdaPerformance } from "../../../visual-intelligence/performance";
import {
  useEdaVisualSelection,
  type EdaNumericRange,
} from "../../../state/useEdaVisualSelection";
import StatisticalBoxPlot, {
  type BoxPlotSeries,
} from "./StatisticalBoxPlot";
import { assertExactDatasetIdentity } from "../../../lib/datasetIdentity";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type NumericPredictor = {
  feature: string;
  iv?: number | null;
  missing_rate?: number | null;
  event_rate_by_quantile?: Array<{
    bucket?: string;
    quantile?: string;
    minimum?: number | null;
    maximum?: number | null;
    count?: number;
    events?: number;
    event_rate?: number | null;
  }>;
};

type DistributionBin = {
  key: string;
  bin: number;
  lower: number;
  upper: number;
  count: number;
  share: number;
  valid_share: number;
  density: number;
  event_count: number | null;
  non_event_count: number | null;
  event_rate: number | null;
};

type DistributionMetrics = {
  active: boolean;
  minimum: number | null;
  maximum: number | null;
  row_count: number;
  population_share: number;
  valid_share: number;
  mean: number | null;
  median: number | null;
  standard_deviation: number | null;
  q1: number | null;
  q3: number | null;
  minimum_value: number | null;
  maximum_value: number | null;
  event_count: number | null;
  target_rate: number | null;
  lower_percentile: number;
  upper_percentile: number;
};

type DistributionResponse = {
  ok: boolean;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  section: "distribution";
  feature: string;
  target: string;
  problem_type: "classification" | "regression";
  row_count: number;
  duration_ms: number;
  cache_status: "hit" | "miss";
  dataset_version: string;
  requested_bins: number;
  returned_bins: number;
  engine: string;
  resolution: "exact";
  bins: DistributionBin[];
  missing_bucket: {
    label: string;
    count: number;
    share: number;
    event_count: number | null;
    non_event_count: number | null;
    event_rate: number | null;
  };
  selected_subset: DistributionMetrics;
  statistics: {
    count: number;
    missing_count: number;
    missing_rate: number;
    mean: number | null;
    standard_deviation: number | null;
    minimum: number | null;
    q1: number | null;
    median: number | null;
    q3: number | null;
    maximum: number | null;
    outlier_lower: number | null;
    outlier_upper: number | null;
    outlier_count: number;
  };
  markers: {
    mean: number | null;
    median: number | null;
    q1: number | null;
    q3: number | null;
    outlier_lower: number | null;
    outlier_upper: number | null;
  };
  iv: number | null;
  iv_by_bin: Array<{
    label: string;
    count: number;
    event_count: number;
    non_event_count: number;
    event_rate: number;
    woe: number;
    iv_contribution: number;
    missing: boolean;
  }>;
  predictor_authorization?: {
    manifest_version: string;
    authorized_predictors: string[];
    target_source_excluded: string[];
  };
};

type Props = {
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  target: string;
  problemType: "classification" | "regression";
  eventValue?: unknown;
  datasetVersion: string;
  predictors: NumericPredictor[];
  histogramBins: number;
  onHistogramBins: (value: number) => void;
};

type CacheEntry = {
  createdAt: number;
  promise: Promise<DistributionResponse>;
};

const distributionRequests = new Map<string, CacheEntry>();
const REQUEST_CACHE_MS = 30_000;
const MAX_REQUEST_CACHE_ENTRIES = 48;

function requestKey(body: Record<string, unknown>) {
  return JSON.stringify(body, Object.keys(body).sort());
}

function fetchDistribution(
  body: Record<string, unknown>,
  datasetVersion: string,
  force = false,
): Promise<DistributionResponse> {
  const now = Date.now();
  for (const [cachedKey, entry] of distributionRequests) {
    if (now - entry.createdAt >= REQUEST_CACHE_MS) {
      distributionRequests.delete(cachedKey);
    }
  }
  const key = requestKey({ ...body, dataset_version: datasetVersion });
  const existing = distributionRequests.get(key);
  if (!force && existing && now - existing.createdAt < REQUEST_CACHE_MS) {
    return existing.promise;
  }
  const promise = fetch(`${API_BASE}/eda/workspace/distribution`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(async (response) => {
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) {
      const detail = payload?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : detail?.message ?? payload?.message ?? payload?.error;
      throw new Error(String(message || "Distribution aggregation failed."));
    }
    return payload as DistributionResponse;
  });
  distributionRequests.set(key, { createdAt: now, promise });
  while (distributionRequests.size > MAX_REQUEST_CACHE_ENTRIES) {
    const oldest = distributionRequests.keys().next().value as string | undefined;
    if (!oldest) break;
    distributionRequests.delete(oldest);
  }
  promise.catch(() => {
    if (distributionRequests.get(key)?.promise === promise) distributionRequests.delete(key);
  });
  return promise;
}

function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => setWidth(Math.max(320, Math.round(element.getBoundingClientRect().width)));
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function distributionBoxPlotSeries(
  data: DistributionResponse | null,
): BoxPlotSeries[] {
  const statistics = data?.statistics;
  if (
    !statistics ||
    !finite(statistics.minimum) ||
    !finite(statistics.q1) ||
    !finite(statistics.median) ||
    !finite(statistics.q3) ||
    !finite(statistics.maximum)
  ) {
    return [];
  }
  const lowerFence = finite(statistics.outlier_lower)
    ? statistics.outlier_lower
    : statistics.minimum;
  const upperFence = finite(statistics.outlier_upper)
    ? statistics.outlier_upper
    : statistics.maximum;
  return [
    {
      id: data.feature,
      label: data.feature,
      count: statistics.count,
      minimum: statistics.minimum,
      q1: statistics.q1,
      median: statistics.median,
      q3: statistics.q3,
      maximum: statistics.maximum,
      whiskerLow: Math.max(statistics.minimum, lowerFence),
      whiskerHigh: Math.min(statistics.maximum, upperFence),
      outlierCount: statistics.outlier_count,
      color: "#2563eb",
    },
  ];
}

function formatNumber(value: unknown, digits = 2) {
  if (value === null || value === undefined || value === "") return "Not available";
  const number = Number(value);
  return Number.isFinite(number)
    ? number.toLocaleString(undefined, { maximumFractionDigits: digits })
    : "Not available";
}

function formatPercent(value: unknown, digits = 1) {
  if (value === null || value === undefined || value === "") return "Not available";
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(digits)}%` : "Not available";
}

function formatNumericRange(
  minimum: unknown,
  maximum: unknown,
  digits = 3,
  fallback = "Not available",
) {
  if (!finite(minimum) || !finite(maximum)) return fallback;
  return `${formatNumber(minimum, digits)} – ${formatNumber(maximum, digits)}`;
}

function formatLift(eventRate: unknown, populationEventRate: number | null) {
  if (!finite(eventRate) || !finite(populationEventRate) || populationEventRate <= 0) {
    return "Not available";
  }
  return `${(eventRate / populationEventRate).toFixed(2)}×`;
}

/**
 * Selection requests return the same full-population visual payload alongside
 * new subset metrics. Comparing only the fields consumed by DistributionChart
 * keeps its object identity stable so a brush update does not replay every
 * chart transition.
 */
function populationVisualSignature(data: DistributionResponse) {
  return JSON.stringify([
    data.dataset_version,
    data.feature,
    data.target,
    data.problem_type,
    data.row_count,
    data.requested_bins,
    data.returned_bins,
    data.bins.map((row) => [
      row.key,
      row.bin,
      row.lower,
      row.upper,
      row.count,
      row.share,
      row.valid_share,
      row.density,
      row.event_count,
      row.non_event_count,
      row.event_rate,
    ]),
    data.markers,
    data.missing_bucket,
  ]);
}

function downloadRows(filename: string, rows: Record<string, unknown>[]) {
  if (!rows.length) return;
  const headers = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const quote = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const csv = [
    headers.map(quote).join(","),
    ...rows.map((row) => headers.map((header) => quote(row[header])).join(",")),
  ].join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function PredictorDistributionExplorer({
  projectId,
  datasetId,
  datasetVersionId,
  target,
  problemType,
  eventValue,
  datasetVersion,
  predictors,
  histogramBins,
  onHistogramBins,
}: Props) {
  const reducedMotion = useReducedMotion();
  const selectedVariable = useEdaVisualSelection((state) => state.selectedVariable);
  const selectedRange = useEdaVisualSelection((state) => state.selectedRange);
  const setSelectedVariable = useEdaVisualSelection((state) => state.setSelectedVariable);
  const setSelectedRange = useEdaVisualSelection((state) => state.setSelectedRange);
  const selectedQuantile = useEdaVisualSelection((state) => state.selectedQuantile);
  const setSelectedQuantile = useEdaVisualSelection((state) => state.setSelectedQuantile);
  const setHover = useEdaVisualSelection((state) => state.setHover);
  const clearSelection = useEdaVisualSelection((state) => state.clearSelection);
  const available = useMemo(
    () => predictors.map((row) => row.feature).filter(Boolean),
    [predictors],
  );
  const variable =
    (selectedVariable && available.includes(selectedVariable) ? selectedVariable : null) ??
    available[0] ??
    "";
  const activeRange =
    selectedRange && selectedRange.feature === variable ? selectedRange : null;
  const selectedProfile = predictors.find((row) => row.feature === variable);

  const [data, setData] = useState<DistributionResponse | null>(null);
  const [chartData, setChartData] = useState<DistributionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [showDensity, setShowDensity] = useState(true);
  const [showEventRate, setShowEventRate] = useState(problemType === "classification");
  const [showTargetClass, setShowTargetClass] = useState(false);
  const [showOutliers, setShowOutliers] = useState(false);
  const [showIv, setShowIv] = useState(true);
  const [quantileDisplayMode, setQuantileDisplayMode] = useState<
    "compact" | "expanded"
  >("compact");
  const [hoveredBin, setHoveredBin] = useState<DistributionBin | null>(null);
  const [rangeInput, setRangeInput] = useState({ min: "", max: "" });
  const [motionPhase, setMotionPhase] = useState<"idle" | "animating" | "settled">("idle");
  const requestSequence = useRef(0);
  const consumedReload = useRef(0);
  const initialUnbrushedReadyRecorded = useRef(false);
  const motionController = useRef(createChartMotionController());

  useEffect(() => {
    if (variable && selectedVariable !== variable) setSelectedVariable(variable, "distribution");
  }, [selectedVariable, setSelectedVariable, variable]);

  useEffect(() => {
    if (!activeRange) {
      setRangeInput({ min: "", max: "" });
      return;
    }
    setRangeInput({
      min: String(activeRange.min),
      max: String(activeRange.max),
    });
  }, [activeRange?.feature, activeRange?.min, activeRange?.max]);

  useEffect(() => {
    setHoveredBin(null);
    setHover(null);
  }, [datasetVersion, histogramBins, setHover, variable]);

  useEffect(() => {
    if (!variable) return;
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    const startedAt = performance.now();
    const body: Record<string, unknown> = {
      project_id: projectId,
      expected_dataset_id: datasetId,
      expected_dataset_version_id: datasetVersionId,
      dataset_version: datasetVersionId,
      target,
      event_value: eventValue,
      problem_type: problemType,
      feature: variable,
      histogram_bins: histogramBins,
      selected_features: available,
      ...(activeRange
        ? { selection_min: activeRange.min, selection_max: activeRange.max }
        : {}),
    };
    setLoading(true);
    setError("");
    const force = reload > consumedReload.current;
    if (force) consumedReload.current = reload;
    fetchDistribution(body, datasetVersion, force)
      .then((payload) => {
        if (requestSequence.current !== sequence) return;
        assertExactDatasetIdentity(
          {
            project_id: projectId,
            dataset_id: datasetId,
            dataset_version_id: datasetVersionId,
          },
          payload,
          "EDA predictor distribution response",
        );
        if (
          payload.feature !== variable ||
          payload.dataset_version !== datasetVersion ||
          payload.requested_bins !== histogramBins
        ) {
          throw new Error(
            "The distribution response did not match the active dataset, predictor, and bin request.",
          );
        }
        setData(payload);
        setChartData((current) =>
          current &&
          populationVisualSignature(current) === populationVisualSignature(payload)
            ? current
            : payload,
        );
        recordEdaPerformance(activeRange ? "brush-response" : "chart-update", startedAt, {
          feature: variable,
          serverDurationMs: payload.duration_ms,
          cacheStatus: payload.cache_status,
          selected: Boolean(activeRange),
        });
        if (!activeRange && !initialUnbrushedReadyRecorded.current) {
          initialUnbrushedReadyRecorded.current = true;
          recordEdaPerformance("distribution-explorer-ready", startedAt, {
            feature: variable,
            serverDurationMs: payload.duration_ms,
            cacheStatus: payload.cache_status,
            selected: false,
          });
        }
      })
      .catch((cause) => {
        if (requestSequence.current !== sequence) return;
        setError(cause instanceof Error ? cause.message : "Distribution aggregation failed.");
      })
      .finally(() => {
        if (requestSequence.current === sequence) setLoading(false);
      });
  }, [
    activeRange?.feature,
    activeRange?.max,
    activeRange?.min,
    available,
    eventValue,
    datasetId,
    datasetVersionId,
    datasetVersion,
    histogramBins,
    problemType,
    projectId,
    reload,
    target,
    variable,
  ]);

  const displayData =
    data &&
    data.dataset_version === datasetVersion &&
    data.feature === variable &&
    data.requested_bins === histogramBins
      ? data
      : null;
  const displayChartData =
    chartData &&
    chartData.dataset_version === datasetVersion &&
    chartData.feature === variable &&
    chartData.requested_bins === histogramBins
      ? chartData
      : null;
  const metricData =
    displayData &&
    ((!activeRange && !displayData.selected_subset.active) ||
      (activeRange &&
        displayData.selected_subset.active &&
        Math.abs(Number(displayData.selected_subset.minimum) - activeRange.min) < 1e-9 &&
        Math.abs(Number(displayData.selected_subset.maximum) - activeRange.max) < 1e-9))
      ? displayData
      : null;
  const boxPlotSeries = distributionBoxPlotSeries(displayData);
  const populationEventRate = useMemo(() => {
    if (problemType !== "classification") return null;
    let events = 0;
    let total = 0;
    const addCounts = (
      eventCount: number | null | undefined,
      nonEventCount: number | null | undefined,
    ) => {
      if (!finite(eventCount) || !finite(nonEventCount)) return;
      events += eventCount;
      total += eventCount + nonEventCount;
    };
    displayChartData?.bins.forEach((row) =>
      addCounts(row.event_count, row.non_event_count),
    );
    if (displayChartData) {
      addCounts(
        displayChartData.missing_bucket.event_count,
        displayChartData.missing_bucket.non_event_count,
      );
    }
    if (total > 0) return events / total;

    selectedProfile?.event_rate_by_quantile?.forEach((row) => {
      if (!finite(row.events) || !finite(row.count)) return;
      events += row.events;
      total += row.count;
    });
    return total > 0 ? events / total : null;
  }, [
    displayChartData,
    problemType,
    selectedProfile?.event_rate_by_quantile,
  ]);

  const applyRange = useCallback(() => {
    const min = Number(rangeInput.min);
    const max = Number(rangeInput.max);
    if (!Number.isFinite(min) || !Number.isFinite(max)) return;
    setSelectedRange({
      feature: variable,
      min: Math.min(min, max),
      max: Math.max(min, max),
      source: "input",
    });
  }, [rangeInput.max, rangeInput.min, setSelectedRange, variable]);

  const selectBin = useCallback(
    (bin: DistributionBin, source: EdaNumericRange["source"] = "distribution") => {
      setSelectedRange({
        feature: variable,
        min: bin.lower,
        max: bin.upper,
        source,
      });
    },
    [setSelectedRange, variable],
  );
  const handleHover = useCallback(
    (bin: DistributionBin | null) => {
      setHoveredBin(bin);
      setHover(
        bin
          ? {
              kind: "range",
              range: {
                feature: variable,
                min: bin.lower,
                max: bin.upper,
                source: "distribution",
              },
              source: "distribution",
            }
          : null,
      );
    },
    [setHover, variable],
  );
  const handleBrush = useCallback(
    (range: [number, number] | null) => {
      if (!range) {
        setSelectedRange(null);
        return;
      }
      setSelectedRange({
        feature: variable,
        min: Math.min(range[0], range[1]),
        max: Math.max(range[0], range[1]),
        source: "distribution",
      });
    },
    [setSelectedRange, variable],
  );

  if (!available.length) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600">
        No server-authorized numeric predictors are available for distribution analysis.
      </div>
    );
  }

  return (
    <section
      className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
      data-testid="predictor-distribution-explorer"
      data-motion-phase={motionPhase}
      data-reduced-motion={reducedMotion ? "true" : "false"}
      aria-labelledby="predictor-distribution-title"
    >
      <div className="border-b border-slate-200 bg-gradient-to-r from-slate-950 via-slate-900 to-blue-950 px-5 py-4 text-white">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-blue-200">
              <BarChart3 size={15} />
              Full-population visual intelligence
            </div>
            <h3 id="predictor-distribution-title" className="mt-1 text-lg font-semibold">
              Predictor Distribution Explorer
            </h3>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-300">
              Server-aggregated bins, statistical markers, target behavior, missingness, and
              a non-mutating range selection for the governed predictor manifest.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-blue-400/40 bg-blue-400/10 px-2.5 py-1 text-[11px] font-semibold text-blue-100">
              Full Dataset Aggregation
            </span>
            <span className="rounded-full border border-slate-500 bg-slate-800 px-2.5 py-1 text-[11px] font-semibold text-slate-200">
              {displayData?.row_count?.toLocaleString() ?? "—"} rows
            </span>
          </div>
        </div>
      </div>

      <div className="border-b border-slate-200 bg-slate-50/80 p-4">
        <div className="grid gap-3 xl:grid-cols-[minmax(220px,1.3fr)_140px_repeat(4,auto)_auto] xl:items-end">
          <label>
            <span className="atlas-label">Authorized predictor</span>
            <select
              className="atlas-input mt-1"
              value={variable}
              onChange={(event) => setSelectedVariable(event.target.value, "distribution")}
              data-testid="eda-distribution-variable"
            >
              {available.map((feature) => (
                <option key={feature} value={feature}>
                  {feature}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="atlas-label">Bins</span>
            <select
              className="atlas-input mt-1"
              value={histogramBins}
              onChange={(event) => onHistogramBins(Number(event.target.value))}
              data-testid="eda-distribution-bins"
            >
              {[10, 15, 20, 24, 30, 40, 50, 60].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <OverlayToggle
            label="Density"
            checked={showDensity}
            onChange={setShowDensity}
          />
          <OverlayToggle
            label="Event rate"
            checked={showEventRate}
            onChange={setShowEventRate}
            disabled={problemType !== "classification"}
          />
          <OverlayToggle
            label="Target classes"
            checked={showTargetClass}
            onChange={setShowTargetClass}
            disabled={problemType !== "classification"}
          />
          <OverlayToggle
            label="Outlier bounds"
            checked={showOutliers}
            onChange={setShowOutliers}
          />
          <div className="flex gap-2">
            <button
              type="button"
              className="atlas-secondary-button"
              onClick={() => setReload((value) => value + 1)}
              disabled={loading}
            >
              <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
            <button
              type="button"
              className="atlas-secondary-button"
              onClick={clearSelection}
              disabled={!activeRange}
            >
              <RotateCcw size={15} />
              Clear selection
            </button>
          </div>
        </div>
      </div>

      {error ? (
        <div className="m-4 flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          <AlertTriangle size={17} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold">Distribution unavailable</div>
            <div className="mt-1">{error}</div>
          </div>
        </div>
      ) : null}

      <div className="p-4 sm:p-5">
        <DistributionChart
          data={displayChartData}
          variable={variable}
          activeRange={activeRange}
          reducedMotion={reducedMotion}
          showDensity={showDensity}
          showEventRate={showEventRate}
          showTargetClass={showTargetClass}
          showOutliers={showOutliers}
          hoveredBin={hoveredBin}
          onHover={handleHover}
          onSelectBin={selectBin}
          onBrush={handleBrush}
          onMotionPhase={setMotionPhase}
          motionController={motionController.current}
          loading={loading}
        />

        {boxPlotSeries.length ? (
          <div className="mt-4">
            <StatisticalBoxPlot
              title={`${variable} box plot`}
              subtitle="The box shows Q1 to Q3, the center line is the median, and the whiskers use the backend IQR fences clipped to the observed range."
              series={boxPlotSeries}
              valueLabel={variable}
              dataTestId="eda-predictor-box-plot"
              note="Rose endpoints mark the observed minimum and maximum. The reported outlier count is computed over the full population; no raw predictor values are loaded into the browser."
            />
          </div>
        ) : null}

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
          <dl
            className="grid grid-cols-2 gap-3 sm:grid-cols-4"
            aria-live="polite"
            aria-busy={loading && !metricData}
            data-testid="eda-predictor-metric-grid"
          >
            <Metric
              label="Selected rows"
              value={
                loading && !metricData
                  ? "Updating"
                  : formatNumber(metricData?.selected_subset.row_count, 0)
              }
            />
            <Metric
              label="Population share"
              value={
                loading && !metricData
                  ? "Updating"
                  : formatPercent(metricData?.selected_subset.population_share)
              }
            />
            <Metric
              label="Selected mean"
              value={
                loading && !metricData
                  ? "Updating"
                  : formatNumber(metricData?.selected_subset.mean, 3)
              }
            />
            <Metric
              label="Selected median"
              value={
                loading && !metricData
                  ? "Updating"
                  : formatNumber(metricData?.selected_subset.median, 3)
              }
            />
            <Metric
              label="IQR (Q1 – Q3)"
              value={
                loading && !metricData
                  ? "Updating"
                  : formatNumericRange(
                      metricData?.selected_subset.q1,
                      metricData?.selected_subset.q3,
                    )
              }
            />
            <Metric
              label={problemType === "classification" ? "Selected target rate" : "Target rate"}
              value={
                problemType === "classification"
                  ? loading && !metricData
                    ? "Updating"
                    : formatPercent(metricData?.selected_subset.target_rate, 2)
                  : "Not applicable"
              }
            />
            <Metric
              label="Selected range"
              value={
                activeRange
                  ? formatNumericRange(activeRange.min, activeRange.max)
                  : "Full population"
              }
            />
          </dl>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-600">
              Numeric range
            </div>
            <div className="mt-2 grid grid-cols-[1fr_1fr_auto] gap-2">
              <input
                type="number"
                className="atlas-input"
                aria-label="Selected range minimum"
                placeholder="Minimum"
                value={rangeInput.min}
                onChange={(event) => setRangeInput((current) => ({ ...current, min: event.target.value }))}
                onKeyDown={(event) => event.key === "Enter" && applyRange()}
              />
              <input
                type="number"
                className="atlas-input"
                aria-label="Selected range maximum"
                placeholder="Maximum"
                value={rangeInput.max}
                onChange={(event) => setRangeInput((current) => ({ ...current, max: event.target.value }))}
                onKeyDown={(event) => event.key === "Enter" && applyRange()}
              />
              <button type="button" className="atlas-primary-button" onClick={applyRange}>
                <Check size={15} />
                Apply
              </button>
            </div>
            <div className="mt-2 text-xs leading-5 text-slate-600">
              Drag the chart brush or enter exact cutoffs. Selection changes analytical scope only;
              the dataset is never mutated.
            </div>
          </div>
        </div>

        {problemType === "classification" && selectedProfile?.event_rate_by_quantile?.length ? (
          <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-base font-semibold text-slate-950">Linked quantile view</div>
                <div className="mt-1 text-sm leading-5 text-slate-600">
                  Select a quantile to move the histogram brush; brushed ranges highlight overlapping quantiles.
                </div>
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <div
                  className="inline-flex rounded-lg border border-slate-200 bg-slate-100 p-0.5"
                  role="group"
                  aria-label="Quantile card display"
                  data-testid="eda-quantile-display-mode"
                >
                  {(["compact", "expanded"] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      aria-pressed={quantileDisplayMode === mode}
                      onClick={() => setQuantileDisplayMode(mode)}
                      className={`rounded-md px-3 py-1.5 text-xs font-semibold capitalize transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-1 motion-reduce:transition-none ${
                        quantileDisplayMode === mode
                          ? "bg-white text-blue-800 shadow-sm"
                          : "text-slate-600 hover:bg-white/70 hover:text-slate-900"
                      }`}
                    >
                      {mode}
                    </button>
                  ))}
                </div>
                <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
                  Full Dataset Aggregation
                </span>
              </div>
            </div>
            <div
              className={`mt-4 grid gap-3 sm:grid-cols-2 ${
                quantileDisplayMode === "compact"
                  ? "lg:grid-cols-3 xl:grid-cols-5"
                  : "lg:grid-cols-3"
              }`}
              data-testid="eda-quantile-grid"
              data-display-mode={quantileDisplayMode}
            >
              {selectedProfile.event_rate_by_quantile.map((row, index) => {
                const min = finite(row.minimum) ? row.minimum : Number.NaN;
                const max = finite(row.maximum) ? row.maximum : Number.NaN;
                const validBounds = finite(min) && finite(max);
                const label = String(row.bucket ?? row.quantile ?? `Q${index + 1}`);
                const bandRange = validBounds
                  ? formatNumericRange(min, max, 2)
                  : "Range unavailable";
                const eventRate = formatPercent(row.event_rate, 2);
                const rowCount = formatNumber(row.count, 0);
                const lift = formatLift(row.event_rate, populationEventRate);
                const overlaps =
                  validBounds &&
                  activeRange &&
                  max >= activeRange.min &&
                  min <= activeRange.max;
                const pinned =
                  selectedQuantile?.feature === variable &&
                  selectedQuantile.index === index;
                return (
                  <button
                    key={`${label}-${index}`}
                    type="button"
                    className={`rounded-xl border text-left shadow-sm transition-[border-color,background-color,color,box-shadow,transform] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 motion-reduce:transform-none motion-reduce:transition-none disabled:cursor-not-allowed disabled:opacity-60 ${
                      quantileDisplayMode === "compact"
                        ? "min-h-[9rem] p-3"
                        : "min-h-[11rem] p-4"
                    } ${
                      pinned
                        ? "border-blue-800 bg-blue-700 text-white shadow-md ring-2 ring-blue-300 ring-offset-2"
                        : overlaps
                          ? "border-blue-400 bg-blue-50 text-blue-950 ring-1 ring-blue-200 hover:-translate-y-0.5 hover:shadow-md"
                          : "border-slate-200 bg-slate-50 text-slate-800 hover:-translate-y-0.5 hover:border-blue-400 hover:bg-white hover:shadow-md"
                    }`}
                    disabled={!validBounds}
                    onClick={() =>
                      validBounds &&
                      setSelectedQuantile({
                        feature: variable,
                        label,
                        index,
                        min,
                        max,
                      })
                    }
                    aria-pressed={pinned}
                    aria-label={`${label}; band ${bandRange}; event rate ${eventRate}; ${rowCount} rows; lift versus population ${lift}${pinned ? "; pinned" : ""}`}
                    data-quantile-index={index}
                  >
                    <span className="flex items-start justify-between gap-2">
                      <span className="block text-xs font-bold uppercase tracking-[0.12em] opacity-80">
                        {label}
                      </span>
                      {pinned ? (
                        <span className="rounded-full bg-white/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide">
                          Pinned
                        </span>
                      ) : null}
                    </span>
                    <span className="mt-3 block text-[11px] font-semibold uppercase tracking-wide opacity-70">
                      Event rate
                    </span>
                    <span
                      className={`mt-0.5 block font-bold tabular-nums ${
                        quantileDisplayMode === "compact" ? "text-xl" : "text-2xl"
                      }`}
                    >
                      {eventRate}
                    </span>
                    <span className="mt-3 block text-[11px] font-semibold uppercase tracking-wide opacity-70">
                      Band range
                    </span>
                    <span
                      className={`mt-0.5 block break-words font-semibold tabular-nums ${
                        quantileDisplayMode === "compact" ? "text-xs" : "text-sm"
                      }`}
                    >
                      {bandRange}
                    </span>
                    <span className="mt-3 grid grid-cols-2 gap-3 border-t border-current/20 pt-2.5">
                      <span>
                        <span className="block text-[10px] font-semibold uppercase tracking-wide opacity-70">
                          Rows
                        </span>
                        <span className="mt-0.5 block text-sm font-bold tabular-nums">
                          {rowCount}
                        </span>
                      </span>
                      <span>
                        <span className="block text-[10px] font-semibold uppercase tracking-wide opacity-70">
                          Lift vs population
                        </span>
                        <span className="mt-0.5 block text-sm font-bold tabular-nums">
                          {lift}
                        </span>
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        <div className="mt-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_260px]">
          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-sm font-semibold text-slate-950">Full-population markers</div>
                <div className="mt-1 text-xs text-slate-500">
                  Mean and median animate to their new positions when the predictor changes.
                </div>
              </div>
              <div className="flex flex-wrap gap-2 text-xs">
                <MarkerPill color="bg-blue-600" label={`Mean ${formatNumber(displayData?.markers.mean, 3)}`} />
                <MarkerPill color="bg-fuchsia-600" label={`Median ${formatNumber(displayData?.markers.median, 3)}`} />
                <MarkerPill color="bg-slate-500" label={`Q1–Q3 ${formatNumber(displayData?.markers.q1, 2)}–${formatNumber(displayData?.markers.q3, 2)}`} />
              </div>
            </div>
          </div>
          <div
            className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-3"
            data-testid="eda-missing-bucket"
          >
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
              Separate missing bucket
            </div>
            <div className="mt-1 text-xl font-semibold text-slate-950">
              {formatNumber(displayData?.missing_bucket.count, 0)}
            </div>
            <div className="text-xs text-slate-600">
              {formatPercent(displayData?.missing_bucket.share)} of population
              {problemType === "classification"
                ? ` · target rate ${formatPercent(displayData?.missing_bucket.event_rate, 2)}`
                : ""}
            </div>
          </div>
        </div>

        {problemType === "classification" ? (
        <div
          className="mt-4 overflow-hidden rounded-xl border border-blue-200 bg-blue-50/30"
          data-testid="eda-iv-by-bin"
          data-primary-analysis="true"
          data-visible-by-default="true"
        >
          <button
            type="button"
            className="flex w-full items-center justify-between bg-blue-50/70 px-4 py-3 text-left"
            onClick={() => setShowIv((value) => !value)}
            aria-expanded={showIv}
            data-testid="eda-iv-by-bin-toggle"
          >
            <span>
              <span className="text-sm font-semibold text-slate-950">IV by bin</span>
              <span className="ml-2 text-xs text-slate-500">
                WoE and signed IV contribution · total IV {formatNumber(displayData?.iv, 4)}
              </span>
            </span>
            <span className="text-xs font-semibold text-blue-700">{showIv ? "Collapse" : "Expand"}</span>
          </button>
          {showIv ? <IvTable rows={displayData?.iv_by_bin ?? []} /> : null}
        </div>
        ) : null}

        <details
          className="mt-4 rounded-xl border border-slate-200 bg-slate-50/70"
          data-testid="eda-distribution-accessibility-alternative"
        >
          <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-900">
            Accessibility and export alternative
            <span className="ml-2 text-xs font-normal text-slate-500">
              Tabular bins and CSV
            </span>
          </summary>
          <div className="border-t border-slate-200 p-4">
            <button
              type="button"
              className="atlas-secondary-button mb-3"
              onClick={() =>
                downloadRows(
                  `atlas-eda-${variable.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-distribution.csv`,
                  (displayData?.bins ?? []) as unknown as Record<string, unknown>[],
                )
              }
              disabled={!displayData?.bins.length}
            >
              <Download size={15} />
              Export current bins
            </button>
            <DistributionDataTable bins={displayData?.bins ?? []} problemType={problemType} />
          </div>
        </details>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500">
          <span>
            Engine: {displayData?.engine ?? "server full-population aggregation"} · resolution: exact ·
            no raw predictor column loaded into the browser
          </span>
          <span>
            Server {formatNumber(displayData?.duration_ms, 0)} ms · motion{" "}
            {reducedMotion ? "disabled by preference" : `${ATLAS_MOTION_TOKENS.durationMs.enter}/${ATLAS_MOTION_TOKENS.durationMs.update} ms`}
          </span>
        </div>
      </div>
    </section>
  );
}

function DistributionChart({
  data,
  variable,
  activeRange,
  reducedMotion,
  showDensity,
  showEventRate,
  showTargetClass,
  showOutliers,
  hoveredBin,
  onHover,
  onSelectBin,
  onBrush,
  onMotionPhase,
  motionController,
  loading,
}: {
  data: DistributionResponse | null;
  variable: string;
  activeRange: EdaNumericRange | null;
  reducedMotion: boolean;
  showDensity: boolean;
  showEventRate: boolean;
  showTargetClass: boolean;
  showOutliers: boolean;
  hoveredBin: DistributionBin | null;
  onHover: (bin: DistributionBin | null) => void;
  onSelectBin: (bin: DistributionBin, source?: EdaNumericRange["source"]) => void;
  onBrush: (range: [number, number] | null) => void;
  onMotionPhase: (phase: "idle" | "animating" | "settled") => void;
  motionController: ReturnType<typeof createChartMotionController>;
  loading: boolean;
}) {
  const { ref: containerRef, width } = useElementWidth<HTMLDivElement>();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const brushRef = useRef<d3.BrushBehavior<null> | null>(null);
  const brushScaleRef = useRef<d3.ScaleLinear<number, number> | null>(null);
  const prior = useRef<{ feature: string; width: number; rendered: boolean }>({
    feature: "",
    width: 0,
    rendered: false,
  });
  const height = 390;

  useEffect(() => {
    if (!svgRef.current || !data?.bins.length || width <= 0) return;
    const svg = d3.select(svgRef.current);
    const revision = motionController.beginRevision();
    const margin = { top: 34, right: 64, bottom: 52, left: 64 };
    const plotWidth = Math.max(180, width - margin.left - margin.right);
    const plotHeight = height - margin.top - margin.bottom;
    const x = d3
      .scaleLinear()
      .domain([
        d3.min(data.bins, (row) => row.lower) ?? 0,
        d3.max(data.bins, (row) => row.upper) ?? 1,
      ])
      .nice()
      .range([margin.left, margin.left + plotWidth]);
    const y = d3
      .scaleLinear()
      .domain([0, d3.max(data.bins, (row) => row.count) ?? 1])
      .nice()
      .range([margin.top + plotHeight, margin.top]);
    const densityY = d3
      .scaleLinear()
      .domain([0, d3.max(data.bins, (row) => row.density) ?? 1])
      .range([margin.top + plotHeight, margin.top + 8]);
    const eventY = d3
      .scaleLinear()
      .domain([0, Math.max(0.01, d3.max(data.bins, (row) => row.event_rate ?? 0) ?? 0.01)])
      .nice()
      .range([margin.top + plotHeight, margin.top + 8]);

    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll<SVGGElement, unknown>("g.plot-root").data([null]).join("g").attr("class", "plot-root");
    const plot = svg.select<SVGGElement>("g.plot-root");
    const isResize =
      prior.current.rendered &&
      prior.current.feature === data.feature &&
      prior.current.width !== width;
    const isEnter = !prior.current.rendered;
    const immediate = isResize;
    onMotionPhase(reducedMotion || immediate ? "settled" : "animating");

    const bars = plot
      .selectAll<SVGRectElement, DistributionBin>("rect.distribution-bar")
      // Bin ordinal is the stable visual identity. Keeping it across predictor
      // changes lets existing bars morph to new bounds/counts; only added or
      // removed ordinals enter/exit when the requested bin count changes.
      .data(data.bins, (row) => String(row.bin));
    const exiting = bars.exit();
    const exitRun = runAtlasD3Transition(
      exiting,
      (target) =>
        target
          .attr("y", margin.top + plotHeight)
          .attr("height", 0)
          .attr("opacity", 0),
      {
        chartId: "eda-predictor-distribution",
        channel: "bars-exit",
        kind: "exit",
        reducedMotion,
        immediate,
        signal: revision.signal,
      },
    );
    exitRun.finished.then(() => exiting.remove());

    const entered = bars
      .enter()
      .append("rect")
      .attr("class", "distribution-bar")
      .attr("rx", 2)
      .attr("y", margin.top + plotHeight)
      .attr("height", 0)
      .attr("opacity", 0.15)
      .attr("tabindex", 0)
      .attr("role", "button");
    const merged = entered.merge(bars);
    merged
      .attr(
        "aria-label",
        (row) =>
          `${variable}, ${formatNumber(row.lower, 3)} to ${formatNumber(row.upper, 3)}: ${row.count.toLocaleString()} rows, ${formatPercent(row.share)} of population${row.event_rate == null ? "" : `, target rate ${formatPercent(row.event_rate, 2)}`}`,
      )
      .on("focus pointerenter", (_event, row) => onHover(row))
      .on("blur pointerleave", () => onHover(null))
      .on("click", (_event, row) => onSelectBin(row))
      .on("keydown", (event, row) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelectBin(row, "keyboard");
        }
      });

    const barRun = runAtlasD3Transition(
      merged,
      (targetSelection) =>
        targetSelection
          .attr("x", (row) => x(row.lower) + 1)
          .attr("width", (row) => Math.max(1, x(row.upper) - x(row.lower) - 2))
          .attr("y", (row) => y(row.count))
          .attr("height", (row) => margin.top + plotHeight - y(row.count)),
      {
        chartId: "eda-predictor-distribution",
        channel: "bars",
        kind: isEnter ? "enter" : "update",
        reducedMotion,
        immediate,
        markCount: data.bins.length,
        signal: revision.signal,
      },
    );

    const xAxisGroup = plot
      .selectAll<SVGGElement, unknown>("g.x-axis")
      .data([null])
      .join("g")
      .attr("class", "x-axis")
      .attr("transform", `translate(0,${margin.top + plotHeight})`);
    const yAxisGroup = plot
      .selectAll<SVGGElement, unknown>("g.y-axis")
      .data([null])
      .join("g")
      .attr("class", "y-axis")
      .attr("transform", `translate(${margin.left},0)`);
    const axisRunX = runAtlasD3Transition(
      xAxisGroup,
      (targetSelection) =>
        targetSelection.call(
          d3
            .axisBottom(x)
            .ticks(Math.max(3, Math.min(8, Math.floor(plotWidth / 100))))
            .tickSizeOuter(0),
        ),
      {
        chartId: "eda-predictor-distribution",
        channel: "x-axis",
        kind: "axis",
        reducedMotion,
        immediate,
        signal: revision.signal,
      },
    );
    const axisRunY = runAtlasD3Transition(
      yAxisGroup,
      (targetSelection) =>
        targetSelection.call(d3.axisLeft(y).ticks(5).tickFormat(d3.format("~s"))),
      {
        chartId: "eda-predictor-distribution",
        channel: "y-axis",
        kind: "axis",
        reducedMotion,
        immediate,
        signal: revision.signal,
      },
    );
    plot
      .selectAll(".x-axis text,.y-axis text")
      .attr("fill", "#475569")
      .attr("font-size", 10);
    plot.selectAll(".x-axis path,.y-axis path,.x-axis line,.y-axis line").attr("stroke", "#cbd5e1");

    const markerRows = [
      finite(data.markers.mean)
        ? { id: "mean", value: data.markers.mean, label: "Mean", color: "#2563eb", dash: null }
        : null,
      finite(data.markers.median)
        ? { id: "median", value: data.markers.median, label: "Median", color: "#a21caf", dash: "5,4" }
        : null,
      finite(data.markers.q1)
        ? { id: "q1", value: data.markers.q1, label: "Q1", color: "#64748b", dash: "2,4" }
        : null,
      finite(data.markers.q3)
        ? { id: "q3", value: data.markers.q3, label: "Q3", color: "#64748b", dash: "2,4" }
        : null,
    ].filter(Boolean) as Array<{
      id: string;
      value: number;
      label: string;
      color: string;
      dash: string | null;
    }>;
    if (showOutliers) {
      if (finite(data.markers.outlier_lower)) {
        markerRows.push({
          id: "outlier-lower",
          value: data.markers.outlier_lower,
          label: "Lower outlier bound",
          color: "#b45309",
          dash: "2,4",
        });
      }
      if (finite(data.markers.outlier_upper)) {
        markerRows.push({
          id: "outlier-upper",
          value: data.markers.outlier_upper,
          label: "Upper outlier bound",
          color: "#b45309",
          dash: "2,4",
        });
      }
    }
    const markers = plot
      .selectAll<SVGGElement, (typeof markerRows)[number]>("g.stat-marker")
      .data(markerRows, (row) => row.id)
      .join(
        (enter) => {
          const group = enter.append("g").attr("class", "stat-marker").attr("opacity", 0);
          group.append("line");
          group.append("text");
          return group;
        },
        (update) => update,
        (exit) => exit.remove(),
      );
    const markerRun = runAtlasD3Transition(
      markers,
      (targetSelection) =>
        targetSelection
          .attr("opacity", 1)
          .attr("transform", (row) => `translate(${x(row.value)},0)`),
      {
        chartId: "eda-predictor-distribution",
        channel: "markers",
        kind: "marker",
        reducedMotion,
        immediate,
        signal: revision.signal,
      },
    );
    markers
      .select("line")
      .attr("y1", margin.top)
      .attr("y2", margin.top + plotHeight)
      .attr("stroke", (row) => row.color)
      .attr("stroke-width", 1.5)
      .attr("stroke-dasharray", (row) => row.dash);
    markers
      .select("text")
      .attr("x", 4)
      .attr("y", (_row, index) => margin.top + 12 + index * 14)
      .attr("fill", (row) => row.color)
      .attr("font-size", 10)
      .attr("font-weight", 700)
      .text((row) => `${row.label} ${formatNumber(row.value, 3)}`);

    const line = d3
      .line<DistributionBin>()
      .x((row) => x((row.lower + row.upper) / 2))
      .y((row) => densityY(row.density))
      .curve(d3.curveMonotoneX);
    const densityJoin = plot
      .selectAll<SVGPathElement, DistributionBin[]>("path.density-line")
      .data(showDensity ? [data.bins] : []);
    densityJoin.exit().remove();
    const densityEntered = densityJoin
      .enter()
      .append("path")
      .attr("class", "density-line")
      .attr("fill", "none")
      .attr("stroke", "#0f766e")
      .attr("stroke-width", 2.25)
      .attr("pointer-events", "none")
      .attr("d", (rows) => line(rows) ?? "")
      .each(function prepareLineReveal() {
        const length = this.getTotalLength();
        d3.select(this)
          .attr("stroke-dasharray", `${length} ${length}`)
          .attr("stroke-dashoffset", length);
      });
    const densityPath = densityEntered.merge(densityJoin);
    const densityRun = runAtlasD3Transition(
      densityPath,
      (targetSelection) =>
        targetSelection
          .attr("d", (rows) => line(rows) ?? "")
          .attr("stroke-dashoffset", 0),
      {
        chartId: "eda-predictor-distribution",
        channel: "density",
        kind: isEnter ? "enter" : "update",
        reducedMotion,
        immediate,
        signal: revision.signal,
      },
    );
    densityRun.finished.then(() => {
      if (!revision.signal.aborted) {
        densityPath.attr("stroke-dasharray", null).attr("stroke-dashoffset", null);
      }
    });

    const eventLine = d3
      .line<DistributionBin>()
      .defined((row) => finite(row.event_rate))
      .x((row) => x((row.lower + row.upper) / 2))
      .y((row) => eventY(row.event_rate ?? 0))
      .curve(d3.curveMonotoneX);
    const eventPath = plot
      .selectAll<SVGPathElement, DistributionBin[]>("path.event-rate-line")
      .data(showEventRate && data.problem_type === "classification" ? [data.bins] : [])
      .join("path")
      .attr("class", "event-rate-line")
      .attr("fill", "none")
      .attr("stroke", "#ea580c")
      .attr("stroke-width", 2)
      .attr("stroke-dasharray", "6,3")
      .attr("pointer-events", "none");
    const eventRun = runAtlasD3Transition(
      eventPath,
      (targetSelection) => targetSelection.attr("d", (rows) => eventLine(rows) ?? ""),
      {
        chartId: "eda-predictor-distribution",
        channel: "event-rate",
        kind: isEnter ? "enter" : "update",
        reducedMotion,
        immediate,
        signal: revision.signal,
      },
    );

    const targetClassLine = (key: "event_count" | "non_event_count") =>
      d3
        .line<DistributionBin>()
        .defined((row) => finite(row[key]))
        .x((row) => x((row.lower + row.upper) / 2))
        .y((row) => y(row[key] ?? 0))
        .curve(d3.curveMonotoneX);
    const targetClassSeries = showTargetClass && data.problem_type === "classification"
      ? [
          { key: "event_count" as const, color: "#059669", dash: null },
          { key: "non_event_count" as const, color: "#475569", dash: "3,3" },
        ]
      : [];
    const targetClassPaths = plot
      .selectAll<SVGPathElement, (typeof targetClassSeries)[number]>(
        "path.target-class-line",
      )
      .data(targetClassSeries, (row) => row.key)
      .join("path")
      .attr("class", (row) => `target-class-line target-class-${row.key}`)
      .attr("fill", "none")
      .attr("stroke", (row) => row.color)
      .attr("stroke-width", 1.75)
      .attr("stroke-dasharray", (row) => row.dash)
      .attr("pointer-events", "none");
    const targetClassRun = runAtlasD3Transition(
      targetClassPaths,
      (targetSelection) =>
        targetSelection.attr("d", (row) => targetClassLine(row.key)(data.bins) ?? ""),
      {
        chartId: "eda-predictor-distribution",
        channel: "target-classes",
        kind: isEnter ? "enter" : "update",
        reducedMotion,
        immediate,
        signal: revision.signal,
      },
    );

    const brushGroup = plot
      .selectAll<SVGGElement, unknown>("g.range-brush")
      .data([null])
      .join("g")
      .attr("class", "range-brush");
    const brush = d3
      .brushX<null>()
      .extent([
        [margin.left, margin.top],
        [margin.left + plotWidth, margin.top + plotHeight],
      ])
      .on("end", (event) => {
        if (!event.sourceEvent) return;
        if (!event.selection) {
          onBrush(null);
          return;
        }
        const [start, end] = event.selection as [number, number];
        onBrush([x.invert(start), x.invert(end)]);
      });
    brushGroup.call(brush);
    brushRef.current = brush;
    brushScaleRef.current = x;
    brushGroup
      .selectAll<SVGRectElement, unknown>(".selection")
      .attr("fill", "#2563eb")
      .attr("fill-opacity", 0.12)
      .attr("stroke", "#1d4ed8");
    brushGroup
      .selectAll<SVGRectElement, unknown>(".overlay")
      .attr("aria-label", `Brush a numeric range for ${variable}`)
      .attr("role", "presentation")
      .on("pointermove", (event) => {
        const [pointerX] = d3.pointer(event, svgRef.current);
        const value = x.invert(pointerX);
        const row =
          data.bins.find(
            (candidate, index) =>
              value >= candidate.lower &&
              (value < candidate.upper || index === data.bins.length - 1),
          ) ?? null;
        onHover(row);
      })
      .on("pointerleave", () => onHover(null));

    plot
      .selectAll<SVGTextElement, unknown>("text.x-title")
      .data([null])
      .join("text")
      .attr("class", "x-title")
      .attr("x", margin.left + plotWidth / 2)
      .attr("y", height - 10)
      .attr("text-anchor", "middle")
      .attr("font-size", 11)
      .attr("font-weight", 700)
      .attr("fill", "#334155")
      .text(variable);
    plot
      .selectAll<SVGTextElement, unknown>("text.y-title")
      .data([null])
      .join("text")
      .attr("class", "y-title")
      .attr("transform", `translate(14,${margin.top + plotHeight / 2}) rotate(-90)`)
      .attr("text-anchor", "middle")
      .attr("font-size", 10)
      .attr("font-weight", 700)
      .attr("fill", "#64748b")
      .text("Rows");

    const settled = Promise.all([
      barRun.finished,
      axisRunX.finished,
      axisRunY.finished,
      markerRun.finished,
      densityRun.finished,
      eventRun.finished,
      targetClassRun.finished,
      exitRun.finished,
    ]).then(() => {
      if (!revision.signal.aborted) onMotionPhase("settled");
    });
    void motionController.track(settled);
    prior.current = { feature: data.feature, width, rendered: true };

    return () => {
      revision.signal.aborted || motionController.cancel();
    };
  }, [
    data,
    height,
    motionController,
    onBrush,
    onHover,
    onMotionPhase,
    onSelectBin,
    reducedMotion,
    showDensity,
    showEventRate,
    showTargetClass,
    showOutliers,
    variable,
    width,
  ]);

  useEffect(() => {
    if (!svgRef.current || !data?.bins.length) return;
    const brush = brushRef.current;
    const x = brushScaleRef.current;
    if (!brush || !x) return;
    const brushGroup = d3
      .select(svgRef.current)
      .selectAll<SVGGElement, unknown>("g.range-brush")
      .data([null]);
    if (brushGroup.empty()) return;
    brushGroup.call(
      brush.move,
      activeRange ? [x(activeRange.min), x(activeRange.max)] : null,
    );
  }, [
    activeRange?.feature,
    activeRange?.max,
    activeRange?.min,
    data,
    width,
  ]);

  useEffect(() => {
    if (!svgRef.current) return;
    const bars = d3
      .select(svgRef.current)
      .selectAll<SVGRectElement, DistributionBin>("rect.distribution-bar");
    const opacity = (row: DistributionBin) => {
      if (activeRange) {
        return row.upper >= activeRange.min && row.lower <= activeRange.max
          ? 0.95
          : 0.22;
      }
      return hoveredBin && hoveredBin.key !== row.key ? 0.5 : 0.9;
    };
    const fill = (row: DistributionBin) => {
      if (hoveredBin?.key === row.key) return "#1d4ed8";
      if (
        activeRange &&
        row.upper >= activeRange.min &&
        row.lower <= activeRange.max
      ) {
        return "#2563eb";
      }
      return "#60a5fa";
    };
    bars.interrupt("atlas-distribution-highlight");
    if (reducedMotion) {
      bars.attr("opacity", opacity).attr("fill", fill);
      return;
    }
    bars
      .transition("atlas-distribution-highlight")
      .duration(ATLAS_MOTION_TOKENS.durationMs.highlight)
      .attr("opacity", opacity)
      .attr("fill", fill);
  }, [activeRange?.max, activeRange?.min, hoveredBin?.key, reducedMotion, data]);

  return (
    <div
      ref={containerRef}
      className="relative min-h-[390px] overflow-hidden rounded-xl border border-slate-200 bg-gradient-to-b from-white to-slate-50"
    >
      {loading ? (
        <div className="pointer-events-none absolute right-3 top-3 z-10 rounded-full border border-blue-200 bg-white/95 px-2.5 py-1 text-[11px] font-semibold text-blue-700 shadow-sm">
          {activeRange
            ? "Updating selected-subset metrics…"
            : "Updating full population…"}
        </div>
      ) : null}
      {hoveredBin ? (
        <div
          className="pointer-events-none absolute left-3 top-3 z-10 max-w-[300px] rounded-lg border border-slate-200 bg-slate-950/95 px-3 py-2 text-xs text-white shadow-xl"
          data-testid="eda-distribution-tooltip"
          role="status"
        >
          <div className="font-semibold">
            {formatNumber(hoveredBin.lower, 3)} to {formatNumber(hoveredBin.upper, 3)}
          </div>
          <div className="mt-1 text-slate-200">
            {hoveredBin.count.toLocaleString()} rows · {formatPercent(hoveredBin.share)} of population
          </div>
          {hoveredBin.event_rate != null ? (
            <div className="text-orange-200">
              {formatNumber(hoveredBin.event_count, 0)} events ·{" "}
              {formatNumber(hoveredBin.non_event_count, 0)} non-events · target rate{" "}
              {formatPercent(hoveredBin.event_rate, 2)}
            </div>
          ) : null}
          <div className="text-slate-300">
            Missing bucket: {formatNumber(data?.missing_bucket.count, 0)} rows ·{" "}
            {formatPercent(data?.missing_bucket.share)} of population
          </div>
        </div>
      ) : null}
      <svg
        ref={svgRef}
        className="block h-[390px] w-full"
        role="img"
        aria-busy={loading}
        aria-label={
          data
            ? `Full-population histogram of ${data.feature}. Mean ${formatNumber(data.markers.mean, 3)}, median ${formatNumber(data.markers.median, 3)}. Use Tab to focus bins, Enter to select a bin, or the numeric range inputs below.`
            : "Full-population distribution chart is loading."
        }
        data-testid="eda-distribution-svg"
      />
      {!data ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-white/55 text-sm text-slate-600 backdrop-blur-[1px]">
          {loading ? "Aggregating the full population…" : "Distribution data is not available."}
        </div>
      ) : null}
    </div>
  );
}

function OverlayToggle({
  label,
  checked,
  onChange,
  disabled = false,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label
      className={`flex h-10 items-center gap-2 rounded-lg border px-3 text-xs font-semibold ${
        checked && !disabled
          ? "border-blue-300 bg-blue-50 text-blue-900"
          : "border-slate-200 bg-white text-slate-600"
      } ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-h-24 min-w-0 rounded-xl bg-slate-50 px-3.5 py-3">
      <dt className="text-xs font-semibold uppercase leading-4 tracking-wide text-slate-600">
        {label}
      </dt>
      <dd className="mt-2 break-words text-xl font-bold leading-tight tabular-nums text-slate-950 sm:text-2xl">
        {value}
      </dd>
    </div>
  );
}

function MarkerPill({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 font-semibold tabular-nums text-slate-700">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}

function IvTable({ rows }: { rows: DistributionResponse["iv_by_bin"] }) {
  if (!rows.length) {
    return (
      <div className="border-t border-slate-200 px-4 py-5 text-sm text-slate-500">
        IV-by-bin detail is available for binary classification targets with a resolved event value.
      </div>
    );
  }
  return (
    <div className="max-h-80 overflow-auto border-t border-slate-200">
      <table className="w-full min-w-[760px] text-xs">
        <thead className="sticky top-0 bg-slate-950 text-white">
          <tr>
            {["Bin", "Rows", "Events", "Non-events", "Event rate", "WoE", "IV contribution"].map(
              (label) => (
                <th key={label} className="px-3 py-2.5 text-left text-[10px] uppercase tracking-wide">
                  {label}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row, index) => (
            <tr key={`${row.label}-${index}`} className={row.missing ? "bg-amber-50" : "even:bg-slate-50"}>
              <td className="px-3 py-2.5 font-medium text-slate-900">{row.label}</td>
              <td className="px-3 py-2.5 tabular-nums">{row.count.toLocaleString()}</td>
              <td className="px-3 py-2.5 tabular-nums">{row.event_count.toLocaleString()}</td>
              <td className="px-3 py-2.5 tabular-nums">{row.non_event_count.toLocaleString()}</td>
              <td className="px-3 py-2.5 tabular-nums">{formatPercent(row.event_rate, 2)}</td>
              <td className="px-3 py-2.5 tabular-nums">{formatNumber(row.woe, 4)}</td>
              <td className="px-3 py-2.5 tabular-nums">{formatNumber(row.iv_contribution, 5)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DistributionDataTable({
  bins,
  problemType,
}: {
  bins: DistributionBin[];
  problemType: "classification" | "regression";
}) {
  if (!bins.length) return <div className="text-sm text-slate-500">No bins are available.</div>;
  return (
    <div className="max-h-72 overflow-auto">
      <table className="w-full min-w-[680px] text-xs">
        <thead className="sticky top-0 bg-slate-100 text-slate-700">
          <tr>
            {["Lower", "Upper", "Rows", "Population share", ...(problemType === "classification" ? ["Events", "Target rate"] : [])].map(
              (label) => (
                <th key={label} className="px-3 py-2 text-left text-[10px] uppercase tracking-wide">
                  {label}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {bins.map((row) => (
            <tr key={row.key}>
              <td className="px-3 py-2 tabular-nums">{formatNumber(row.lower, 5)}</td>
              <td className="px-3 py-2 tabular-nums">{formatNumber(row.upper, 5)}</td>
              <td className="px-3 py-2 tabular-nums">{row.count.toLocaleString()}</td>
              <td className="px-3 py-2 tabular-nums">{formatPercent(row.share, 2)}</td>
              {problemType === "classification" ? (
                <>
                  <td className="px-3 py-2 tabular-nums">{formatNumber(row.event_count, 0)}</td>
                  <td className="px-3 py-2 tabular-nums">{formatPercent(row.event_rate, 2)}</td>
                </>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

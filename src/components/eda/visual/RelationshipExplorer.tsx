import React, {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AlertTriangle,
  Download,
  LoaderCircle,
  RefreshCw,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";

import {
  useEdaVisualSelection,
  type EdaNumericRange,
  type EdaPinnedPair,
  type EdaRelationshipMode,
} from "../../../state/useEdaVisualSelection";
import { recordEdaPerformance } from "../../../visual-intelligence/performance";
import { useReducedMotion } from "../../../visual-intelligence/useReducedMotion";

const RelationshipWebGL = lazy(() => import("./RelationshipWebGL"));

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

const DEFAULT_CAMERA: RelationshipCamera = {
  alpha: 22,
  beta: 38,
  distance: 190,
  center: [0, 0, 0],
  autoRotate: false,
};

const POINT_COLORS: Record<string, string> = {
  event: "#e11d48",
  non_event: "#2563eb",
  missing: "#64748b",
  Population: "#2563eb",
};

export type RelationshipPoint = {
  id: string;
  x: number;
  y: number;
  z: number | null;
  size: number | null;
  target_group: string;
  segment_group: string | null;
  selection_value: number | null;
};

export type RelationshipPairMetric = {
  a: string;
  b: string;
  correlation: number | null;
  n: number;
};

export type RelationshipSampleResponse = {
  ok: boolean;
  scope: "rendered_sample";
  dataset_id?: string | null;
  dataset_version: string;
  predictor_manifest_id: string;
  population_rows: number;
  eligible_rows: number;
  requested_rows: number;
  returned_rows: number;
  sampled: boolean;
  sampling: {
    method: string;
    seed_id: string;
    missing_rows_excluded: number;
    maximum_rows: number;
  };
  axes: { x: string; y: string; z: string | null };
  encodings: {
    point_size: string | null;
    segment: string | null;
    selection_feature: string | null;
  };
  pair_metrics: RelationshipPairMetric[];
  target_encoding: {
    kind: string;
    target: string;
    groups: string[];
  };
  points: RelationshipPoint[];
  cache_status: "hit" | "miss";
};

export type RelationshipColorMode = "target" | "segment" | "none";

export type RelationshipCamera = {
  alpha: number;
  beta: number;
  distance: number;
  center: [number, number, number];
  autoRotate: boolean;
};

type RelationshipExplorerProps = {
  projectId: string;
  target: string;
  eventValue?: unknown;
  problemType: "classification" | "regression";
  datasetVersion: string;
  predictorManifestId: string;
  numericFields: string[];
  segmentFields: string[];
  selectedRange: EdaNumericRange | null;
  initialPair: EdaPinnedPair | null;
  vifVariable: string | null;
  onClose?: () => void;
};

const responseCache = new Map<string, Promise<RelationshipSampleResponse>>();

function boundedCacheSet(
  key: string,
  value: Promise<RelationshipSampleResponse>,
) {
  responseCache.set(key, value);
  while (responseCache.size > 12) {
    const oldest = responseCache.keys().next().value;
    if (typeof oldest === "string") responseCache.delete(oldest);
    else break;
  }
}

function safeObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function formatNumber(value: unknown, digits = 3): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return "Not available";
  return number.toLocaleString(undefined, {
    maximumFractionDigits: digits,
  });
}

function colorForPoint(
  point: RelationshipPoint,
  mode: RelationshipColorMode,
  segmentPalette: Map<string, string>,
): string {
  if (mode === "none") return POINT_COLORS.Population;
  if (mode === "target") {
    return POINT_COLORS[point.target_group] ?? "#7c3aed";
  }
  return segmentPalette.get(point.segment_group ?? "Missing") ?? "#64748b";
}

function deviceSampleCap(): 1000 | 2500 | 5000 {
  if (typeof navigator === "undefined") return 2500;
  const memory = Number(
    (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 4,
  );
  const cores = Number(navigator.hardwareConcurrency ?? 4);
  if (memory <= 4 || cores <= 4) return 1000;
  if (memory >= 8 && cores >= 8) return 5000;
  return 2500;
}

function supportsWebGL(): boolean {
  if (typeof document === "undefined") return false;
  try {
    const canvas = document.createElement("canvas");
    return Boolean(
      canvas.getContext("webgl2", { failIfMajorPerformanceCaveat: true }) ||
        canvas.getContext("webgl", { failIfMajorPerformanceCaveat: true }),
    );
  } catch {
    return false;
  }
}

function downloadText(
  filename: string,
  text: string,
  type: string,
): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function hardenCsvCell(value: unknown): string {
  const raw = String(value ?? "");
  const hardened = /^[=+\-@]/.test(raw) ? `'${raw}` : raw;
  return `"${hardened.replace(/"/g, '""')}"`;
}

function inLinkedRange(
  point: RelationshipPoint,
  selectedRange: EdaNumericRange | null,
): boolean {
  if (!selectedRange || point.selection_value == null) return false;
  return (
    point.selection_value >= selectedRange.min &&
    point.selection_value <= selectedRange.max
  );
}

function axisExtent(
  points: RelationshipPoint[],
  accessor: (point: RelationshipPoint) => number,
): [number, number] {
  const values = points.map(accessor).filter(Number.isFinite);
  if (!values.length) return [0, 1];
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  if (minimum === maximum) return [minimum - 0.5, maximum + 0.5];
  const padding = (maximum - minimum) * 0.04;
  return [minimum - padding, maximum + padding];
}

function Scatter2D({
  response,
  colorMode,
  opacity,
  selectedRange,
}: {
  response: RelationshipSampleResponse;
  colorMode: RelationshipColorMode;
  opacity: number;
  selectedRange: EdaNumericRange | null;
}) {
  const width = 960;
  const height = 500;
  const margin = { top: 24, right: 26, bottom: 64, left: 78 };
  const [xMin, xMax] = axisExtent(response.points, (point) => point.x);
  const [yMin, yMax] = axisExtent(response.points, (point) => point.y);
  const xPosition = (value: number) =>
    margin.left +
    ((value - xMin) / Math.max(xMax - xMin, Number.EPSILON)) *
      (width - margin.left - margin.right);
  const yPosition = (value: number) =>
    height -
    margin.bottom -
    ((value - yMin) / Math.max(yMax - yMin, Number.EPSILON)) *
      (height - margin.top - margin.bottom);
  const segmentPalette = new Map<string, string>();
  Array.from(
    new Set(response.points.map((point) => point.segment_group ?? "Missing")),
  ).forEach((group, index) => {
    segmentPalette.set(
      group,
      ["#2563eb", "#e11d48", "#0f766e", "#7c3aed", "#d97706", "#0891b2"][
        index % 6
      ],
    );
  });
  const sizes = response.points
    .map((point) => point.size)
    .filter((value): value is number => value != null && Number.isFinite(value));
  const sizeMin = sizes.length ? Math.min(...sizes) : 0;
  const sizeMax = sizes.length ? Math.max(...sizes) : 0;
  const radius = (point: RelationshipPoint) => {
    if (point.size == null || sizeMax <= sizeMin) return 3.5;
    return 2.5 + ((point.size - sizeMin) / (sizeMax - sizeMin)) * 5;
  };

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="min-h-[430px] min-w-[760px] w-full"
        role="img"
        aria-label={`Two-dimensional scatter plot of ${response.axes.x} by ${response.axes.y}.`}
        data-testid="relationship-2d-scatter"
      >
        <rect width={width} height={height} fill="#ffffff" />
        {[0, 0.25, 0.5, 0.75, 1].map((step) => {
          const x =
            margin.left + step * (width - margin.left - margin.right);
          const y =
            margin.top + step * (height - margin.top - margin.bottom);
          return (
            <React.Fragment key={step}>
              <line
                x1={x}
                x2={x}
                y1={margin.top}
                y2={height - margin.bottom}
                stroke="#e2e8f0"
              />
              <line
                x1={margin.left}
                x2={width - margin.right}
                y1={y}
                y2={y}
                stroke="#e2e8f0"
              />
            </React.Fragment>
          );
        })}
        {response.points.map((point) => {
          const linked = inLinkedRange(point, selectedRange);
          return (
            <circle
              key={point.id}
              cx={xPosition(point.x)}
              cy={yPosition(point.y)}
              r={radius(point) + (linked ? 2.5 : 0)}
              fill={colorForPoint(point, colorMode, segmentPalette)}
              fillOpacity={
                selectedRange ? (linked ? Math.max(opacity, 0.85) : 0.1) : opacity
              }
              stroke={linked ? "#0f172a" : "#ffffff"}
              strokeWidth={linked ? 1.8 : 0.4}
              data-linked-match={selectedRange ? String(linked) : undefined}
            >
              <title>
                {`${response.axes.x}: ${formatNumber(point.x)}; ${
                  response.axes.y
                }: ${formatNumber(point.y)}; ${point.target_group}`}
              </title>
            </circle>
          );
        })}
        <line
          x1={margin.left}
          x2={width - margin.right}
          y1={height - margin.bottom}
          y2={height - margin.bottom}
          stroke="#475569"
        />
        <line
          x1={margin.left}
          x2={margin.left}
          y1={margin.top}
          y2={height - margin.bottom}
          stroke="#475569"
        />
        <text
          x={(margin.left + width - margin.right) / 2}
          y={height - 18}
          textAnchor="middle"
          className="fill-slate-900 text-[14px] font-semibold"
        >
          {response.axes.x}
        </text>
        <text
          x={18}
          y={(margin.top + height - margin.bottom) / 2}
          textAnchor="middle"
          transform={`rotate(-90 18 ${
            (margin.top + height - margin.bottom) / 2
          })`}
          className="fill-slate-900 text-[14px] font-semibold"
        >
          {response.axes.y}
        </text>
        <text
          x={margin.left}
          y={height - margin.bottom + 22}
          className="fill-slate-600 text-[11px]"
        >
          {formatNumber(xMin)}
        </text>
        <text
          x={width - margin.right}
          y={height - margin.bottom + 22}
          textAnchor="end"
          className="fill-slate-600 text-[11px]"
        >
          {formatNumber(xMax)}
        </text>
        <text
          x={margin.left - 10}
          y={height - margin.bottom}
          textAnchor="end"
          className="fill-slate-600 text-[11px]"
        >
          {formatNumber(yMin)}
        </text>
        <text
          x={margin.left - 10}
          y={margin.top + 4}
          textAnchor="end"
          className="fill-slate-600 text-[11px]"
        >
          {formatNumber(yMax)}
        </text>
      </svg>
    </div>
  );
}

function Density2D({
  response,
  selectedRange,
}: {
  response: RelationshipSampleResponse;
  selectedRange: EdaNumericRange | null;
}) {
  const width = 960;
  const height = 500;
  const margin = { top: 24, right: 26, bottom: 64, left: 78 };
  const xBins = 24;
  const yBins = 18;
  const [xMin, xMax] = axisExtent(response.points, (point) => point.x);
  const [yMin, yMax] = axisExtent(response.points, (point) => point.y);
  const bins = useMemo(() => {
    const counts = new Map<
      string,
      { x: number; y: number; count: number; linked: number }
    >();
    for (const point of response.points) {
      const x = Math.min(
        xBins - 1,
        Math.max(
          0,
          Math.floor(
            ((point.x - xMin) / Math.max(xMax - xMin, Number.EPSILON)) * xBins,
          ),
        ),
      );
      const y = Math.min(
        yBins - 1,
        Math.max(
          0,
          Math.floor(
            ((point.y - yMin) / Math.max(yMax - yMin, Number.EPSILON)) * yBins,
          ),
        ),
      );
      const key = `${x}:${y}`;
      const current = counts.get(key) ?? { x, y, count: 0, linked: 0 };
      current.count += 1;
      if (inLinkedRange(point, selectedRange)) current.linked += 1;
      counts.set(key, current);
    }
    return Array.from(counts.values());
  }, [response.points, selectedRange, xMax, xMin, yMax, yMin]);
  const maximum = Math.max(1, ...bins.map((bin) => bin.count));
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const cellWidth = innerWidth / xBins;
  const cellHeight = innerHeight / yBins;

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="min-h-[430px] min-w-[760px] w-full"
        role="img"
        aria-label={`Sample density view of ${response.axes.x} by ${response.axes.y}.`}
        data-testid="relationship-density"
      >
        <rect width={width} height={height} fill="#ffffff" />
        {bins.map((bin) => {
          const intensity = Math.sqrt(bin.count / maximum);
          const linkedShare = bin.linked / Math.max(bin.count, 1);
          return (
            <rect
              key={`${bin.x}:${bin.y}`}
              x={margin.left + bin.x * cellWidth}
              y={height - margin.bottom - (bin.y + 1) * cellHeight}
              width={Math.max(1, cellWidth - 1)}
              height={Math.max(1, cellHeight - 1)}
              fill={linkedShare > 0 ? "#e11d48" : "#2563eb"}
              fillOpacity={0.12 + intensity * 0.82}
              stroke={linkedShare > 0 ? "#881337" : "#ffffff"}
              strokeWidth={linkedShare > 0 ? 1.5 : 0.5}
            >
              <title>{`${bin.count} rendered rows${
                selectedRange ? `; ${bin.linked} linked` : ""
              }`}</title>
            </rect>
          );
        })}
        <line
          x1={margin.left}
          x2={width - margin.right}
          y1={height - margin.bottom}
          y2={height - margin.bottom}
          stroke="#475569"
        />
        <line
          x1={margin.left}
          x2={margin.left}
          y1={margin.top}
          y2={height - margin.bottom}
          stroke="#475569"
        />
        <text
          x={(margin.left + width - margin.right) / 2}
          y={height - 18}
          textAnchor="middle"
          className="fill-slate-900 text-[14px] font-semibold"
        >
          {response.axes.x}
        </text>
        <text
          x={18}
          y={(margin.top + height - margin.bottom) / 2}
          textAnchor="middle"
          transform={`rotate(-90 18 ${
            (margin.top + height - margin.bottom) / 2
          })`}
          className="fill-slate-900 text-[14px] font-semibold"
        >
          {response.axes.y}
        </text>
      </svg>
    </div>
  );
}

export default function RelationshipExplorer({
  projectId,
  target,
  eventValue,
  problemType,
  datasetVersion,
  predictorManifestId,
  numericFields,
  segmentFields,
  selectedRange,
  initialPair,
  vifVariable,
  onClose,
}: RelationshipExplorerProps) {
  const axes = useEdaVisualSelection((state) => state.relationshipAxes);
  const mode = useEdaVisualSelection((state) => state.relationshipMode);
  const setAxes = useEdaVisualSelection((state) => state.setRelationshipAxes);
  const setMode = useEdaVisualSelection((state) => state.setRelationshipMode);
  const reducedMotion = useReducedMotion();
  const [sampleCap] = useState(deviceSampleCap);
  const [sampleLimit, setSampleLimit] = useState<number>(() =>
    Math.min(2500, deviceSampleCap()),
  );
  const [sizeFeature, setSizeFeature] = useState("");
  const [segmentFeature, setSegmentFeature] = useState("");
  const [colorMode, setColorMode] =
    useState<RelationshipColorMode>("target");
  const [opacity, setOpacity] = useState(0.7);
  const [showGrid, setShowGrid] = useState(true);
  const [showLegend, setShowLegend] = useState(true);
  const [camera, setCamera] = useState<RelationshipCamera>(DEFAULT_CAMERA);
  const [response, setResponse] =
    useState<RelationshipSampleResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [webglAvailable] = useState(supportsWebGL);
  const [webglFailed, setWebglFailed] = useState(false);
  const activationStartedRef = useRef<number | null>(null);

  useEffect(() => {
    if (initialPair) {
      setAxes({ x: initialPair.a, y: initialPair.b });
    }
  }, [initialPair?.a, initialPair?.b, setAxes]);

  useEffect(() => {
    if (initialPair) return;
    if (vifVariable && !axes.x) setAxes({ x: vifVariable });
  }, [axes.x, initialPair, setAxes, vifVariable]);

  useEffect(() => {
    if (reducedMotion && camera.autoRotate) {
      setCamera((current) => ({ ...current, autoRotate: false }));
    }
  }, [camera.autoRotate, reducedMotion]);

  const requestSignature = useMemo(() => {
    if (!axes.x || !axes.y || axes.x === axes.y) return "";
    return JSON.stringify({
      project_id: projectId,
      target,
      event_value: eventValue,
      problem_type: problemType,
      dataset_version: datasetVersion,
      predictor_manifest_id: predictorManifestId,
      x_feature: axes.x,
      y_feature: axes.y,
      z_feature: axes.z || undefined,
      point_size_feature: sizeFeature || undefined,
      segment_feature: segmentFeature || undefined,
      selection_feature:
        selectedRange && numericFields.includes(selectedRange.feature)
          ? selectedRange.feature
          : undefined,
      sample_limit: Math.min(sampleLimit, sampleCap),
    });
  }, [
    axes.x,
    axes.y,
    axes.z,
    datasetVersion,
    eventValue,
    numericFields,
    predictorManifestId,
    problemType,
    projectId,
    sampleCap,
    sampleLimit,
    segmentFeature,
    selectedRange?.feature,
    sizeFeature,
    target,
  ]);

  useEffect(() => {
    if (!requestSignature) {
      setResponse(null);
      return undefined;
    }
    let active = true;
    setLoading(true);
    setError("");
    let request = responseCache.get(requestSignature);
    if (!request) {
      request = fetch(`${API_BASE}/eda/relationship-sample`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: requestSignature,
      }).then(async (result) => {
        const payload = await result.json().catch(() => null);
        if (!result.ok || !payload?.ok) {
          const detail = safeObject(payload?.detail);
          const rejected = Array.isArray(detail.rejected_fields)
            ? detail.rejected_fields
                .map((row) => safeObject(row))
                .map(
                  (row) =>
                    `${String(row.role ?? "field")}: ${String(
                      row.field ?? "unknown",
                    )} (${String(row.reason ?? "not authorized")})`,
                )
                .join("; ")
            : "";
          throw new Error(
            `${String(
              detail.message ??
                payload?.message ??
                "The governed relationship sample could not be loaded.",
            )}${rejected ? ` ${rejected}` : ""}`,
          );
        }
        return payload as RelationshipSampleResponse;
      });
      request.catch(() => responseCache.delete(requestSignature));
      boundedCacheSet(requestSignature, request);
    }
    request
      .then((payload) => {
        if (active) setResponse(payload);
      })
      .catch((cause) => {
        if (active) {
          setResponse(null);
          setError(
            cause instanceof Error
              ? cause.message
              : "The governed relationship sample could not be loaded.",
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [requestSignature]);

  const activateMode = useCallback(
    (nextMode: EdaRelationshipMode) => {
      if (nextMode === "3d") {
        activationStartedRef.current =
          typeof performance === "undefined" ? 0 : performance.now();
      }
      setMode(nextMode);
    },
    [setMode],
  );

  useEffect(() => {
    if (
      mode === "3d" &&
      response &&
      axes.z &&
      activationStartedRef.current != null
    ) {
      recordEdaPerformance(
        "3d-activation",
        activationStartedRef.current,
        {
          returnedRows: response.returned_rows,
          deviceCap: sampleCap,
        },
      );
      activationStartedRef.current = null;
    }
  }, [axes.z, mode, response, sampleCap]);

  const linkedRows = useMemo(
    () =>
      selectedRange &&
      response?.encodings.selection_feature === selectedRange.feature
        ? response.points.filter((point) =>
            inLinkedRange(point, selectedRange),
          ).length
        : null,
    [response, selectedRange],
  );

  const updateCamera = useCallback((next: RelationshipCamera) => {
    setCamera(next);
  }, []);
  const handleContextLost = useCallback(() => {
    setWebglFailed(true);
    setMode("2d");
  }, [setMode]);

  const nudgeCamera = (
    changes: Partial<
      Pick<RelationshipCamera, "alpha" | "beta" | "distance" | "center">
    >,
  ) => {
    setCamera((current) => ({ ...current, ...changes }));
  };

  const exportState = () => {
    downloadText(
      `atlas-relationship-state-${Date.now()}.json`,
      JSON.stringify(
        {
          schema: "atlas.relationship-explorer.v1",
          datasetVersion,
          predictorManifestId,
          target,
          axes,
          encodings: {
            colorMode,
            pointSize: sizeFeature || null,
            segment: segmentFeature || null,
            opacity,
          },
          sampleLimit: Math.min(sampleLimit, sampleCap),
          mode,
          grid: showGrid,
          legend: showLegend,
          camera,
          selectedRange,
          responseScope: response
            ? {
                populationRows: response.population_rows,
                eligibleRows: response.eligible_rows,
                returnedRows: response.returned_rows,
                seedId: response.sampling.seed_id,
              }
            : null,
          exportedAt: new Date().toISOString(),
        },
        null,
        2,
      ),
      "application/json;charset=utf-8",
    );
  };

  const exportSample = () => {
    if (!response) return;
    const headers = [
      "point_id",
      response.axes.x,
      response.axes.y,
      response.axes.z || "z",
      response.encodings.point_size || "point_size",
      "target_group",
      "segment_group",
      response.encodings.selection_feature || "selection_value",
    ];
    const rows = response.points.map((point) => [
      point.id,
      point.x,
      point.y,
      point.z,
      point.size,
      point.target_group,
      point.segment_group,
      point.selection_value,
    ]);
    downloadText(
      `atlas-relationship-sample-${Date.now()}.csv`,
      [
        headers.map(hardenCsvCell).join(","),
        ...rows.map((row) => row.map(hardenCsvCell).join(",")),
      ].join("\n"),
      "text/csv;charset=utf-8",
    );
  };

  const axisOption = (
    field: string,
    role: "x" | "y" | "z",
  ): React.ReactNode => {
    const usedByOtherAxis =
      (role !== "x" && axes.x === field) ||
      (role !== "y" && axes.y === field) ||
      (role !== "z" && axes.z === field);
    return (
      <option key={field} value={field} disabled={usedByOtherAxis}>
        {field}
      </option>
    );
  };

  return (
    <section
      className="bg-white p-4 sm:p-5"
      aria-labelledby="relationship-explorer-title"
      data-testid="relationship-explorer"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-indigo-700">
            Governed visual sample · Relationship Explorer
          </div>
          <h3
            id="relationship-explorer-title"
            className="mt-1 text-xl font-bold text-slate-950"
          >
            Configure and explore
          </h3>
          <p className="mt-1 max-w-4xl text-sm text-slate-600">
            Explore one server-authorized bounded sample in 2D, density, or 3D.
            Modes, camera, opacity, grid, legend, target coloring, and range
            highlighting reuse the same sample.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="atlas-secondary-button"
            onClick={exportSample}
            disabled={!response}
          >
            <Download size={14} /> Export sample
          </button>
          <button
            type="button"
            className="atlas-secondary-button"
            onClick={exportState}
          >
            <Download size={14} /> Export state
          </button>
          {onClose ? (
            <button
              type="button"
              className="atlas-secondary-button"
              onClick={onClose}
              aria-label="Close Relationship Explorer"
            >
              <X size={15} /> Close
            </button>
          ) : null}
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <label>
          <span className="atlas-label">X axis</span>
          <select
            className="atlas-input mt-1"
            value={axes.x ?? ""}
            onChange={(event) =>
              setAxes({ x: event.target.value || null })
            }
          >
            <option value="">Select X</option>
            {numericFields.map((field) => axisOption(field, "x"))}
          </select>
        </label>
        <label>
          <span className="atlas-label">Y axis</span>
          <select
            className="atlas-input mt-1"
            value={axes.y ?? ""}
            onChange={(event) =>
              setAxes({ y: event.target.value || null })
            }
          >
            <option value="">Select Y</option>
            {numericFields.map((field) => axisOption(field, "y"))}
          </select>
        </label>
        <label>
          <span className="atlas-label">Z axis · explicitly selected</span>
          <select
            className="atlas-input mt-1"
            value={axes.z ?? ""}
            onChange={(event) =>
              setAxes({ z: event.target.value || null })
            }
          >
            <option value="">No Z selected</option>
            {numericFields.map((field) => axisOption(field, "z"))}
          </select>
        </label>
        <label>
          <span className="atlas-label">Point size · optional</span>
          <select
            className="atlas-input mt-1"
            value={sizeFeature}
            onChange={(event) => setSizeFeature(event.target.value)}
          >
            <option value="">Uniform size</option>
            {numericFields.map((field) => (
              <option key={field} value={field}>
                {field}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="atlas-label">Color</span>
          <select
            className="atlas-input mt-1"
            value={colorMode}
            onChange={(event) =>
              setColorMode(event.target.value as RelationshipColorMode)
            }
          >
            <option value="target">Target group</option>
            <option value="none">No grouping</option>
            <option value="segment" disabled={!segmentFeature}>
              Approved segment
            </option>
          </select>
        </label>
        <label>
          <span className="atlas-label">Approved segment · optional</span>
          <select
            className="atlas-input mt-1"
            value={segmentFeature}
            onChange={(event) => {
              setSegmentFeature(event.target.value);
              if (!event.target.value && colorMode === "segment") {
                setColorMode("target");
              }
            }}
          >
            <option value="">No segment</option>
            {segmentFields.map((field) => (
              <option key={field} value={field}>
                {field}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="atlas-label">
            Rendered rows · device cap {sampleCap.toLocaleString()}
          </span>
          <select
            className="atlas-input mt-1"
            value={sampleLimit}
            onChange={(event) => setSampleLimit(Number(event.target.value))}
          >
            {[500, 1000, 2500, 5000]
              .filter((value) => value <= sampleCap)
              .map((value) => (
                <option key={value} value={value}>
                  {value.toLocaleString()}
                </option>
              ))}
          </select>
        </label>
        <label>
          <span className="atlas-label">
            Point opacity · {Math.round(opacity * 100)}%
          </span>
          <input
            className="mt-3 w-full accent-indigo-600"
            type="range"
            min="0.15"
            max="1"
            step="0.05"
            value={opacity}
            onChange={(event) => setOpacity(Number(event.target.value))}
          />
        </label>
      </div>

      <div className="mt-4 flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-3 lg:flex-row lg:items-center lg:justify-between">
        <div
          className="inline-flex w-fit rounded-lg border border-slate-200 bg-slate-50 p-1"
          role="group"
          aria-label="Relationship view"
        >
          {(
            [
              ["2d", "2D Scatter"],
              ["density", "Density"],
              ["3d", "3D Explorer"],
            ] as Array<[EdaRelationshipMode, string]>
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={mode === value}
              className={`rounded-md px-3 py-2 text-xs font-semibold ${
                mode === value
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-slate-700 hover:bg-white"
              }`}
              onClick={() => activateMode(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-700">
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={showGrid}
              onChange={(event) => setShowGrid(event.target.checked)}
            />
            Grid
          </label>
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={showLegend}
              onChange={(event) => setShowLegend(event.target.checked)}
            />
            Legend
          </label>
          <span>
            Sample signature:{" "}
            <strong className="font-mono">
              {response?.sampling.seed_id ?? "pending"}
            </strong>
          </span>
        </div>
      </div>

      {loading ? (
        <div
          className="mt-4 flex min-h-[430px] items-center justify-center rounded-xl border border-slate-200 bg-white text-sm text-slate-600"
          role="status"
        >
          <LoaderCircle size={18} className="mr-2 animate-spin" />
          Loading governed relationship sample…
        </div>
      ) : error ? (
        <div
          className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900"
          role="alert"
        >
          <div className="flex items-start gap-2">
            <AlertTriangle size={18} className="mt-0.5 shrink-0" />
            <div>
              <div className="font-semibold">
                Relationship sample unavailable
              </div>
              <div className="mt-1">{error}</div>
            </div>
          </div>
        </div>
      ) : !axes.x || !axes.y ? (
        <div className="mt-4 rounded-xl border border-dashed border-indigo-300 bg-white p-8 text-center text-sm text-slate-600">
          Pin a heatmap pair or select distinct X and Y predictors to begin.
        </div>
      ) : response ? (
        <div className="mt-4 space-y-4">
          {mode === "2d" ? (
            <Scatter2D
              response={response}
              colorMode={colorMode}
              opacity={opacity}
              selectedRange={selectedRange}
            />
          ) : null}
          {mode === "density" ? (
            <Density2D response={response} selectedRange={selectedRange} />
          ) : null}
          {mode === "3d" && !axes.z ? (
            <div className="rounded-xl border border-amber-300 bg-amber-50 p-6 text-sm text-amber-950">
              Choose an explicit Z predictor above. ATLAS will preserve X and Y
              while it requests the new complete-case cohort.
            </div>
          ) : null}
          {mode === "3d" && axes.z && (!webglAvailable || webglFailed) ? (
            <div
              className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950"
              role="alert"
            >
              WebGL is unavailable or its context was lost. The same variables
              and governed sample remain available in 2D.
              <button
                type="button"
                className="atlas-secondary-button ml-3"
                onClick={() => setMode("2d")}
              >
                Use 2D fallback
              </button>
            </div>
          ) : null}
          {mode === "3d" && axes.z && webglAvailable && !webglFailed ? (
            <>
              <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white p-3">
                <button
                  type="button"
                  className="atlas-secondary-button"
                  onClick={() =>
                    nudgeCamera({ beta: camera.beta - 12 })
                  }
                >
                  Rotate left
                </button>
                <button
                  type="button"
                  className="atlas-secondary-button"
                  onClick={() =>
                    nudgeCamera({ beta: camera.beta + 12 })
                  }
                >
                  Rotate right
                </button>
                <button
                  type="button"
                  className="atlas-secondary-button"
                  onClick={() =>
                    nudgeCamera({ alpha: camera.alpha + 10 })
                  }
                >
                  Rotate up
                </button>
                <button
                  type="button"
                  className="atlas-secondary-button"
                  onClick={() =>
                    nudgeCamera({ alpha: camera.alpha - 10 })
                  }
                >
                  Rotate down
                </button>
                <button
                  type="button"
                  className="atlas-secondary-button"
                  onClick={() =>
                    nudgeCamera({
                      distance: Math.max(60, camera.distance - 20),
                    })
                  }
                >
                  <ZoomIn size={14} /> Zoom in
                </button>
                <button
                  type="button"
                  className="atlas-secondary-button"
                  onClick={() =>
                    nudgeCamera({
                      distance: Math.min(420, camera.distance + 20),
                    })
                  }
                >
                  <ZoomOut size={14} /> Zoom out
                </button>
                {(
                  [
                    ["Pan left", [-5, 0, 0]],
                    ["Pan right", [5, 0, 0]],
                    ["Pan up", [0, 5, 0]],
                    ["Pan down", [0, -5, 0]],
                  ] as Array<[string, [number, number, number]]>
                ).map(([label, delta]) => (
                  <button
                    key={label}
                    type="button"
                    className="atlas-secondary-button"
                    onClick={() =>
                      nudgeCamera({
                        center: [
                          camera.center[0] + delta[0],
                          camera.center[1] + delta[1],
                          camera.center[2] + delta[2],
                        ],
                      })
                    }
                  >
                    {label}
                  </button>
                ))}
                <button
                  type="button"
                  className="atlas-secondary-button"
                  onClick={() => setCamera(DEFAULT_CAMERA)}
                >
                  <RefreshCw size={14} /> Reset camera
                </button>
                <label className="ml-auto inline-flex items-center gap-2 text-xs font-semibold text-slate-700">
                  <input
                    type="checkbox"
                    checked={!reducedMotion && camera.autoRotate}
                    disabled={reducedMotion}
                    onChange={(event) =>
                      setCamera((current) => ({
                        ...current,
                        autoRotate: event.target.checked,
                      }))
                    }
                  />
                  Auto-rotate
                </label>
              </div>
              <Suspense
                fallback={
                  <div
                    className="flex h-[560px] items-center justify-center rounded-xl border border-slate-200 bg-white text-sm text-slate-600"
                    role="status"
                  >
                    <LoaderCircle
                      size={18}
                      className="mr-2 animate-spin"
                    />
                    Loading the optional WebGL renderer…
                  </div>
                }
              >
                <RelationshipWebGL
                  points={response.points}
                  xLabel={response.axes.x}
                  yLabel={response.axes.y}
                  zLabel={response.axes.z ?? axes.z}
                  colorMode={colorMode}
                  opacity={opacity}
                  showGrid={showGrid}
                  showLegend={showLegend}
                  camera={camera}
                  selectedRange={selectedRange}
                  reducedMotion={reducedMotion}
                  onCameraChange={updateCamera}
                  onContextLost={handleContextLost}
                />
              </Suspense>
            </>
          ) : null}

          <div
            className="grid gap-3 rounded-xl border border-slate-200 bg-white p-4 sm:grid-cols-2 xl:grid-cols-4"
            aria-live="polite"
          >
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Population
              </div>
              <div className="mt-1 text-xl font-bold tabular-nums text-slate-950">
                {response.population_rows.toLocaleString()}
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Complete-case eligible
              </div>
              <div className="mt-1 text-xl font-bold tabular-nums text-slate-950">
                {response.eligible_rows.toLocaleString()}
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Rendered sample
              </div>
              <div className="mt-1 text-xl font-bold tabular-nums text-slate-950">
                {response.returned_rows.toLocaleString()}
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Linked range overlap
              </div>
              <div className="mt-1 text-xl font-bold tabular-nums text-slate-950">
                {linkedRows == null
                  ? "No linked range"
                  : linkedRows.toLocaleString()}
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">
            This view uses {response.returned_rows.toLocaleString()} deterministically
            sampled rows from {response.eligible_rows.toLocaleString()} complete-case
            rows in a governed population of{" "}
            {response.population_rows.toLocaleString()}. Visual separation,
            clustering, or overlap does not establish predictor usefulness or
            model quality. Confirm any hypothesis with full-population
            statistics and governed validation.
          </div>

          <details className="rounded-xl border border-slate-200 bg-white p-3">
            <summary className="cursor-pointer text-sm font-semibold text-slate-900">
              Accessible rendered-sample table (first 100 rows)
            </summary>
            <div className="mt-3 max-h-80 overflow-auto">
              <table className="min-w-full border-collapse text-xs">
                <caption className="sr-only">
                  Bounded relationship sample. Raw target values are not
                  included.
                </caption>
                <thead className="sticky top-0 bg-slate-100">
                  <tr>
                    <th className="border p-2 text-left">{response.axes.x}</th>
                    <th className="border p-2 text-left">{response.axes.y}</th>
                    {response.axes.z ? (
                      <th className="border p-2 text-left">
                        {response.axes.z}
                      </th>
                    ) : null}
                    <th className="border p-2 text-left">Target group</th>
                    <th className="border p-2 text-left">Linked range</th>
                  </tr>
                </thead>
                <tbody>
                  {response.points.slice(0, 100).map((point) => (
                    <tr key={point.id}>
                      <td className="border p-2 tabular-nums">
                        {formatNumber(point.x)}
                      </td>
                      <td className="border p-2 tabular-nums">
                        {formatNumber(point.y)}
                      </td>
                      {response.axes.z ? (
                        <td className="border p-2 tabular-nums">
                          {formatNumber(point.z)}
                        </td>
                      ) : null}
                      <td className="border p-2">{point.target_group}</td>
                      <td className="border p-2">
                        {selectedRange
                          ? inLinkedRange(point, selectedRange)
                            ? "Included"
                            : "Outside"
                          : "Not selected"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </div>
      ) : null}
    </section>
  );
}

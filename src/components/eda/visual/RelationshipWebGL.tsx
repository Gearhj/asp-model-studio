import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts/core";
import { LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { Scatter3DChart } from "echarts-gl/charts";
import { Grid3DComponent } from "echarts-gl/components";

import type {
  RelationshipCamera,
  RelationshipColorMode,
  RelationshipPoint,
} from "./RelationshipExplorer";
import type { EdaNumericRange } from "../../../state/useEdaVisualSelection";

echarts.use([
  Scatter3DChart,
  Grid3DComponent,
  TooltipComponent,
  LegendComponent,
  CanvasRenderer,
]);

const PALETTE = [
  "#2563eb",
  "#e11d48",
  "#0f766e",
  "#7c3aed",
  "#d97706",
  "#0891b2",
  "#4f46e5",
  "#65a30d",
];

function safeLabel(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function groupForPoint(
  point: RelationshipPoint,
  colorMode: RelationshipColorMode,
): string {
  if (colorMode === "target") return point.target_group || "missing";
  if (colorMode === "segment") return point.segment_group || "Missing";
  return "Population";
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

export default function RelationshipWebGL({
  points,
  xLabel,
  yLabel,
  zLabel,
  colorMode,
  opacity,
  showGrid,
  showLegend,
  camera,
  selectedRange,
  reducedMotion,
  onCameraChange,
  onContextLost,
}: {
  points: RelationshipPoint[];
  xLabel: string;
  yLabel: string;
  zLabel: string;
  colorMode: RelationshipColorMode;
  opacity: number;
  showGrid: boolean;
  showLegend: boolean;
  camera: RelationshipCamera;
  selectedRange: EdaNumericRange | null;
  reducedMotion: boolean;
  onCameraChange: (camera: RelationshipCamera) => void;
  onContextLost: () => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const cameraFrameRef = useRef<number | null>(null);
  const cameraRef = useRef(camera);
  cameraRef.current = camera;

  const option = useMemo(() => {
    const finiteSizes = points
      .map((point) => point.size)
      .filter((value): value is number => value != null && Number.isFinite(value));
    const minimumSize = finiteSizes.length ? Math.min(...finiteSizes) : 0;
    const maximumSize = finiteSizes.length ? Math.max(...finiteSizes) : 0;
    const pointSize = (value: number | null, linked: boolean) => {
      if (value == null || maximumSize <= minimumSize) return linked ? 13 : 7;
      const scaled = 5 + ((value - minimumSize) / (maximumSize - minimumSize)) * 10;
      return linked ? scaled + 5 : scaled;
    };
    const grouped = new Map<
      string,
      { regular: RelationshipPoint[]; linked: RelationshipPoint[] }
    >();
    for (const point of points) {
      const group = groupForPoint(point, colorMode);
      const bucket = grouped.get(group) ?? { regular: [], linked: [] };
      bucket[inLinkedRange(point, selectedRange) ? "linked" : "regular"].push(
        point,
      );
      grouped.set(group, bucket);
    }

    const series: Record<string, unknown>[] = [];
    Array.from(grouped.entries()).forEach(([group, bucket], index) => {
      const color = PALETTE[index % PALETTE.length];
      if (bucket.regular.length) {
        series.push({
          name: group,
          type: "scatter3D",
          coordinateSystem: "cartesian3D",
          dimensions: ["x", "y", "z", "size", "id"],
          data: bucket.regular.map((point) => ({
            name: point.id,
            value: [point.x, point.y, point.z, point.size, point.id],
            symbolSize: pointSize(point.size, false),
          })),
          shading: "lambert",
          silent: false,
          itemStyle: { color, opacity },
          emphasis: {
            itemStyle: {
              opacity: 1,
              borderColor: "#0f172a",
              borderWidth: 1,
            },
          },
        });
      }
      if (bucket.linked.length) {
        series.push({
          name: `${group} · linked selection`,
          type: "scatter3D",
          coordinateSystem: "cartesian3D",
          dimensions: ["x", "y", "z", "size", "id"],
          data: bucket.linked.map((point) => ({
            name: point.id,
            value: [point.x, point.y, point.z, point.size, point.id],
            symbolSize: pointSize(point.size, true),
          })),
          shading: "lambert",
          silent: false,
          itemStyle: {
            color,
            opacity: 1,
            borderColor: "#ffffff",
            borderWidth: 2,
          },
        });
      }
    });

    return {
      animation: !reducedMotion,
      backgroundColor: "#ffffff",
      tooltip: {
        show: true,
        formatter: (params: { seriesName?: string; value?: unknown[] }) => {
          const value = Array.isArray(params.value) ? params.value : [];
          return [
            `<strong>${safeLabel(params.seriesName)}</strong>`,
            `${safeLabel(xLabel)}: ${safeLabel(value[0])}`,
            `${safeLabel(yLabel)}: ${safeLabel(value[1])}`,
            `${safeLabel(zLabel)}: ${safeLabel(value[2])}`,
          ].join("<br/>");
        },
      },
      legend: {
        show: showLegend,
        type: "scroll",
        top: 4,
        textStyle: { color: "#334155", fontSize: 11 },
      },
      xAxis3D: {
        type: "value",
        name: xLabel,
        nameTextStyle: { color: "#0f172a", fontSize: 12 },
        axisLabel: { color: "#475569", fontSize: 10 },
        splitLine: { show: showGrid, lineStyle: { color: "#e2e8f0" } },
      },
      yAxis3D: {
        type: "value",
        name: yLabel,
        nameTextStyle: { color: "#0f172a", fontSize: 12 },
        axisLabel: { color: "#475569", fontSize: 10 },
        splitLine: { show: showGrid, lineStyle: { color: "#e2e8f0" } },
      },
      zAxis3D: {
        type: "value",
        name: zLabel,
        nameTextStyle: { color: "#0f172a", fontSize: 12 },
        axisLabel: { color: "#475569", fontSize: 10 },
        splitLine: { show: showGrid, lineStyle: { color: "#e2e8f0" } },
      },
      grid3D: {
        show: showGrid,
        boxWidth: 120,
        boxDepth: 90,
        boxHeight: 90,
        environment: "#ffffff",
        light: {
          main: { intensity: 1.15, shadow: false },
          ambient: { intensity: 0.55 },
        },
        viewControl: {
          alpha: camera.alpha,
          beta: camera.beta,
          distance: camera.distance,
          center: camera.center,
          autoRotate: reducedMotion ? false : camera.autoRotate,
          autoRotateSpeed: 7,
          damping: reducedMotion ? 0 : 0.8,
          panSensitivity: 1,
          rotateSensitivity: 1,
          zoomSensitivity: 1,
        },
      },
      series,
    };
  }, [
    camera,
    colorMode,
    opacity,
    points,
    reducedMotion,
    selectedRange,
    showGrid,
    showLegend,
    xLabel,
    yLabel,
    zLabel,
  ]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const chart = echarts.init(container, undefined, {
      renderer: "canvas",
      devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2),
    });
    chartRef.current = chart;

    const handleCamera = (event: unknown) => {
      const payload = event as Partial<RelationshipCamera>;
      if (
        !Number.isFinite(payload.alpha) ||
        !Number.isFinite(payload.beta) ||
        !Number.isFinite(payload.distance)
      ) {
        return;
      }
      if (cameraFrameRef.current != null) {
        window.cancelAnimationFrame(cameraFrameRef.current);
      }
      cameraFrameRef.current = window.requestAnimationFrame(() => {
        onCameraChange({
          alpha: Number(payload.alpha),
          beta: Number(payload.beta),
          distance: Number(payload.distance),
          center:
            Array.isArray(payload.center) && payload.center.length === 3
              ? [
                  Number(payload.center[0]),
                  Number(payload.center[1]),
                  Number(payload.center[2]),
                ]
              : cameraRef.current.center,
          autoRotate: reducedMotion ? false : cameraRef.current.autoRotate,
        });
      });
    };
    chart.on("grid3dcamerachanged", handleCamera);

    const canvas = container.querySelector("canvas");
    const handleContextLost = (event: Event) => {
      event.preventDefault();
      onContextLost();
    };
    canvas?.addEventListener("webglcontextlost", handleContextLost);

    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(container);
    return () => {
      resizeObserver.disconnect();
      canvas?.removeEventListener("webglcontextlost", handleContextLost);
      chart.off("grid3dcamerachanged", handleCamera);
      if (cameraFrameRef.current != null) {
        window.cancelAnimationFrame(cameraFrameRef.current);
      }
      chart.dispose();
      chartRef.current = null;
    };
  }, [onCameraChange, onContextLost, reducedMotion]);

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: true, lazyUpdate: false });
  }, [option]);

  return (
    <div
      ref={containerRef}
      className="h-[560px] w-full rounded-xl border border-slate-200 bg-white"
      role="img"
      tabIndex={0}
      aria-label={`Interactive 3D relationship plot. X ${xLabel}; Y ${yLabel}; Z ${zLabel}.`}
      data-testid="relationship-webgl"
    />
  );
}

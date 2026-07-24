// ATLAS Visual Intelligence Foundation -- shared ECharts React wrapper.
// Every production chart in the VI prototypes renders through this component
// rather than each calling echarts.init() directly, so lifecycle (init/resize/
// dispose), loading/empty/error/unsupported states, and ARIA/export wiring are
// implemented once.
import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import type { EChartsOption } from "echarts";
import { LineChart, BarChart, ScatterChart, CustomChart, HeatmapChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent, DataZoomComponent, MarkLineComponent, MarkAreaComponent, BrushComponent, ToolboxComponent } from "echarts/components";
import { CanvasRenderer, SVGRenderer } from "echarts/renderers";
import { ATLAS_ECHARTS_THEME } from "./theme";

echarts.use([
  LineChart, BarChart, ScatterChart, CustomChart, HeatmapChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, DataZoomComponent, MarkLineComponent, MarkAreaComponent, BrushComponent, ToolboxComponent,
  CanvasRenderer, SVGRenderer,
]);

echarts.registerTheme("atlas", ATLAS_ECHARTS_THEME as unknown as Record<string, unknown>);

export type EChartsPanelState = "ready" | "loading" | "empty" | "error" | "unsupported";

export type EChartsPanelProps = {
  option: EChartsOption | null;
  state?: EChartsPanelState;
  emptyMessage?: string;
  errorMessage?: string;
  unsupportedMessage?: string;
  height?: number;
  ariaLabel: string;
  /** Large data (>25k rows per largeDataPolicy.ts) forces Canvas; small data may use SVG
   *  when explicitly requested by a caller that wants crisper vector export. */
  renderer?: "canvas" | "svg";
  onChartReady?: (instance: echarts.ECharts) => void;
  className?: string;
};

/** Reusable panel: safe init/dispose, responsive resize via ResizeObserver, and the four
 *  required non-happy-path states (loading/empty/error/unsupported) rendered consistently. */
export default function EChartsPanel({
  option, state = "ready", emptyMessage = "No data available for this view.",
  errorMessage = "This chart could not be rendered.", unsupportedMessage = "This visualization is not supported for the current selection.",
  height = 320, ariaLabel, renderer = "canvas", onChartReady, className,
}: EChartsPanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);
  const [initError, setInitError] = useState<string | null>(null);
  const reducedMotion = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;

  useEffect(() => {
    if (!containerRef.current || state !== "ready" || !option) return undefined;
    let instance = instanceRef.current;
    try {
      if (!instance || instance.isDisposed()) {
        instance = echarts.init(containerRef.current, "atlas", { renderer });
        instanceRef.current = instance;
        onChartReady?.(instance);
      }
      instance.setOption(option, { notMerge: true, silent: reducedMotion });
      setInitError(null);
    } catch (error) {
      setInitError(error instanceof Error ? error.message : "Unknown ECharts error.");
    }

    const resizeObserver = new ResizeObserver(() => instance?.resize());
    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, [option, state, renderer, onChartReady, reducedMotion]);

  useEffect(() => () => {
    instanceRef.current?.dispose();
    instanceRef.current = null;
  }, []);

  if (state === "loading") {
    return <div role="status" aria-live="polite" aria-label={`${ariaLabel}: loading`} className={`flex items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-sm text-slate-600 ${className ?? ""}`} style={{ height }}>Loading...</div>;
  }
  if (state === "empty") {
    return <div role="status" aria-label={`${ariaLabel}: empty`} className={`flex items-center justify-center rounded-md border border-dashed border-slate-300 bg-white text-sm text-slate-500 ${className ?? ""}`} style={{ height }}>{emptyMessage}</div>;
  }
  if (state === "unsupported") {
    return <div role="status" aria-label={`${ariaLabel}: unsupported`} className={`flex items-center justify-center rounded-md border border-dashed border-amber-300 bg-amber-50 text-sm text-amber-800 ${className ?? ""}`} style={{ height }}>{unsupportedMessage}</div>;
  }
  if (state === "error" || initError) {
    return <div role="alert" aria-label={`${ariaLabel}: error`} className={`flex items-center justify-center rounded-md border border-red-200 bg-red-50 text-sm text-red-700 ${className ?? ""}`} style={{ height }}>{initError ?? errorMessage}</div>;
  }
  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={ariaLabel}
      tabIndex={0}
      data-visual-intelligence-chart="true"
      className={className}
      style={{ height, width: "100%" }}
    />
  );
}

export function exportChartAsPng(instance: echarts.ECharts, filename: string) {
  const url = instance.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#ffffff" });
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
}

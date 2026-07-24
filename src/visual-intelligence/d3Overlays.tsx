// ATLAS Visual Intelligence Foundation -- D3 overlay layer.
//
// ECharts renders the base chart; D3 is layered ONLY for the analytical
// overlays and interactions ECharts doesn't natively express well: reference
// lines with precise statistical positioning, draggable thresholds, and brush
// selection with pixel-accurate coordinate math. This file is pure calculation
// + a thin SVG overlay component -- it never owns application state (React/the
// interaction store does).
import { useEffect, useRef } from "react";
import * as d3 from "d3";
type D3BrushEvent<T> = d3.D3BrushEvent<T>;

export type LinearScaleLike = {
  (value: number): number;
  invert: (pixel: number) => number;
  range: () => [number, number];
};

/** A vertical reference line (mean/median/percentile/identity/zero-residual/threshold),
 *  positioned in DATA units and converted to pixels via the caller-supplied scale --
 *  callers never hand-compute pixel coordinates themselves. */
export type ReferenceLineSpec = {
  id: string;
  value: number;
  label: string;
  color: string;
  dashed?: boolean;
  draggable?: boolean;
};

export function meanValue(values: readonly number[]): number | null {
  if (!values.length) return null;
  let sum = 0;
  for (const value of values) sum += value;
  return sum / values.length;
}

export function medianValue(values: readonly number[]): number | null {
  if (!values.length) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

export function percentileValue(values: readonly number[], p: number): number | null {
  if (!values.length) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.round((p / 100) * (sorted.length - 1))));
  return sorted[index];
}

/** Theoretical normal quantiles for a Q-Q plot, using the Beasley-Springer-Moro
 *  approximation of the inverse normal CDF -- no external stats dependency. */
export function normalQuantile(p: number): number {
  if (p <= 0) return Number.NEGATIVE_INFINITY;
  if (p >= 1) return Number.POSITIVE_INFINITY;
  const a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.383577518672690e2, -3.066479806614716e1, 2.506628277459239];
  const b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1];
  const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416];
  const pLow = 0.02425;
  if (p < pLow) {
    const q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  if (p <= 1 - pLow) {
    const q = p - 0.5;
    const r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }
  const q = Math.sqrt(-2 * Math.log(1 - p));
  return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
}

export function qqPlotPoints(residuals: readonly number[]): Array<{ theoretical: number; sample: number }> {
  if (residuals.length < 3) return [];
  const sorted = residuals.slice().sort((a, b) => a - b);
  const n = sorted.length;
  return sorted.map((sample, i) => ({ theoretical: normalQuantile((i + 0.5) / n), sample }));
}

type ReferenceLineOverlayProps = {
  lines: ReferenceLineSpec[];
  scale: LinearScaleLike;
  height: number;
  onDrag?: (id: string, value: number) => void;
  reducedMotion?: boolean;
};

/** SVG overlay drawn on top of an ECharts canvas (absolutely positioned, same
 *  pixel box) for reference lines and drag interactions. Every draggable line
 *  also has a numeric-input equivalent rendered by the caller (Phase L
 *  requirement: every drag interaction needs a keyboard/numeric equivalent) --
 *  this component only handles the pointer/drag half. */
export function ReferenceLineOverlay({ lines, scale, height, onDrag, reducedMotion }: ReferenceLineOverlayProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    const [rangeStart, rangeEnd] = scale.range();
    const groups = svg.selectAll<SVGGElement, ReferenceLineSpec>("g.atlas-reference-line").data(lines, (d) => d.id);

    groups.exit().remove();
    const entered = groups.enter().append("g").attr("class", "atlas-reference-line");
    entered.append("line").attr("class", "atlas-reference-line-path");
    entered.append("text").attr("class", "atlas-reference-line-label");

    const merged = entered.merge(groups);
    merged.each(function draw(d) {
      const g = d3.select(this);
      const x = scale(d.value);
      const line = g.select<SVGLineElement>("line.atlas-reference-line-path");
      const apply = reducedMotion ? line : (line.transition().duration(150) as unknown as typeof line);
      apply
        .attr("x1", x).attr("x2", x).attr("y1", 0).attr("y2", height)
        .attr("stroke", d.color).attr("stroke-width", 1.5)
        .attr("stroke-dasharray", d.dashed ? "4,3" : null);
      g.select<SVGTextElement>("text.atlas-reference-line-label")
        .attr("x", Math.min(Math.max(x + 4, rangeStart), rangeEnd - 60))
        .attr("y", 12)
        .attr("fill", d.color)
        .attr("font-size", 10)
        .attr("font-weight", 600)
        .text(d.label);

      if (d.draggable && onDrag) {
        (g.style("cursor", "ew-resize") as unknown as d3.Selection<SVGGElement, ReferenceLineSpec, null, undefined>).call(
          d3.drag<SVGGElement, ReferenceLineSpec>().on("drag", (event) => {
            const newValue = scale.invert(Math.min(rangeEnd, Math.max(rangeStart, event.x)));
            onDrag(d.id, newValue);
          })
        );
      }
    });
  }, [lines, scale, height, onDrag, reducedMotion]);

  return <svg ref={svgRef} className="pointer-events-auto absolute inset-0" width="100%" height={height} aria-hidden="true" />;
}

export type BrushRange = { start: number; end: number } | null;

type BrushOverlayProps = {
  scale: LinearScaleLike;
  height: number;
  onBrush: (range: BrushRange) => void;
};

/** Horizontal brush selection (drag to select a numeric range). Always paired by the
 *  caller with a numeric min/max text input (keyboard-accessible equivalent, Phase L). */
export function BrushOverlay({ scale, height, onBrush }: BrushOverlayProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    const [rangeStart, rangeEnd] = scale.range();
    const brushBehavior = d3.brushX<unknown>()
      .extent([[rangeStart, 0], [rangeEnd, height]])
      .on("end", (event: D3BrushEvent<unknown>) => {
        if (!event.selection) {
          onBrush(null);
          return;
        }
        const [x0, x1] = event.selection as [number, number];
        onBrush({ start: scale.invert(x0), end: scale.invert(x1) });
      });
    svg.selectAll("g.atlas-brush").remove();
    svg.append("g").attr("class", "atlas-brush").call(brushBehavior);
  }, [scale, height, onBrush]);

  return <svg ref={svgRef} className="pointer-events-auto absolute inset-0" width="100%" height={height} aria-label="Drag to select a numeric range" role="slider" tabIndex={0} />;
}

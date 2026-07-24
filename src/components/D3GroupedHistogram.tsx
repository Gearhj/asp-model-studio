import React, { useEffect, useMemo, useRef } from "react";
import * as d3 from "d3";
import { sampleArray, toBool, toNumber } from "../lib/d3Utils";


type Row = { value: number | null; label?: number | string };
type CleanedRow = { v: number; lbl: "Event" | "Non-Event" };
type HistogramSeries = { lbl: "Non-Event" | "Event"; bins: Array<number[] & { x0?: number; x1?: number }> };
type Props = {
  data: Row[];
  feature: string;
  bins: number;
  mode: "grouped" | "stacked";
  height?: number;
  showDensity?: boolean;
};

export default function D3GroupedHistogram({
  data,
  feature,
  bins,
  mode,
  height = 480,
  showDensity = false,
}: Props) {
  const ref = useRef<SVGSVGElement | null>(null);

  const cleaned = useMemo(() => {
    const arr = (data || []).reduce<CleanedRow[]>((acc, r: Row) => {
      const value = toNumber(r?.value);
      if (value !== null) {
        acc.push({
          v: value,
          lbl: r?.label === 1 || r?.label === "Event" ? "Event" : "Non-Event",
        });
      }
      return acc;
    }, []);

    // cap sample for perf
    return sampleArray(arr, Math.min(arr.length, 20000));
  }, [data]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const svg = d3.select(el);
    svg.selectAll("*").remove();

    const width = el.clientWidth || 900;
    const margin = { top: 24, right: 16, bottom: 40, left: 56 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const g = svg
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("width", "100%")
      .attr("height", height)
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    if (!cleaned.length) {
      g.append("text")
        .attr("x", innerW / 2)
        .attr("y", innerH / 2)
        .attr("text-anchor", "middle")
        .attr("fill", "#6b7280")
        .text("No numeric data to plot");
      return;
    }

    // x scale by value
    const x = d3.scaleLinear()
      .domain(d3.extent(cleaned, (d: CleanedRow) => d.v) as [number, number])
      .nice()
      .range([0, innerW]);

    // compute bins overall to share bin edges across groups
    const thresholds = x.ticks(Math.max(5, Math.min(80, bins || 20)));
    const binGen = d3.bin().domain(x.domain() as [number, number]).thresholds(thresholds);

    const byLabel = d3.group(cleaned, (d: CleanedRow) => d.lbl);
    const labels = ["Non-Event", "Event"] as const;
    const colors = d3.scaleOrdinal<string, string>().domain(labels as unknown as string[]).range(["#60a5fa", "#f87171"]);

    const series = labels.map((lbl): HistogramSeries => {
      const arr = byLabel.get(lbl) ?? [];
      const vs = arr.map((d: CleanedRow) => d.v);
      return { lbl, bins: binGen(vs) as HistogramSeries["bins"] };
    });

    const yMax = d3.max(series, (s: HistogramSeries) => d3.max(s.bins, (b: number[]) => b.length)) || 1;
    const yStackMax = d3.max(
      series[0].bins.map((_: number[], i: number) => (series[0].bins[i]?.length || 0) + (series[1].bins[i]?.length || 0))
    ) || 1;

    const y = d3.scaleLinear()
      .domain([0, mode === "stacked" ? yStackMax : yMax])
      .nice()
      .range([innerH, 0]);

    // axes
    g.append("g")
      .attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x).ticks(10))
      .call((ax: any) => ax.selectAll("text").style("font-size", "11px"));

    g.append("g")
      .call(d3.axisLeft(y).ticks(6))
      .call((ax: any) => ax.selectAll("text").style("font-size", "11px"));

    // grouped/stacked bars
    const bandwidth = (innerW / thresholds.length) * 0.9;
    const groupBand = d3.scaleBand().domain(labels as unknown as string[]).range([0, bandwidth]).padding(0.08);

    series.forEach((s: HistogramSeries) => {
      const grp = g.append("g").attr("fill", colors(s.lbl));
      s.bins.forEach((b: HistogramSeries["bins"][number], i: number) => {
        const x0 = x(b.x0 as number);
        const x1 = x(b.x1 as number);
        const w = Math.max(1, x1 - x0);

        let bx = x0;
        let by = y(b.length);
        let bh = innerH - by;

        if (mode === "grouped") {
          bx = x0 + groupBand(s.lbl)!;
          by = y(b.length);
          bh = innerH - by;
          grp.append("rect").attr("x", bx).attr("y", by).attr("width", Math.max(1, groupBand.bandwidth())).attr("height", bh);
        } else {
          // stacked: draw in order
          const other = series[0].lbl === s.lbl ? series[1].bins[i] : series[0].bins[i];
          const below = other ? other.length : 0;
          const top = b.length + below;
          by = y(top);
          bh = innerH - by - (innerH - y(below));
          grp.append("rect").attr("x", x0).attr("y", by).attr("width", Math.max(1, w)).attr("height", Math.max(0, bh));
        }
      });
    });

    // legend
    const legend = g.append("g").attr("transform", `translate(0,-8)`);
    labels.forEach((lbl, i) => {
      const row = legend.append("g").attr("transform", `translate(${i * 110},0)`);
      row.append("rect").attr("width", 14).attr("height", 14).attr("fill", colors(lbl));
      row.append("text").attr("x", 18).attr("y", 12).style("font-size", "12px").text(lbl);
    });

    // title
    g.append("text")
      .attr("x", innerW / 2)
      .attr("y", -8)
      .attr("text-anchor", "middle")
      .style("font-weight", 600)
      .style("font-size", "13px")
      .text(`Histogram — ${feature}`);

    // optional kernel density overlay (overall)
    if (showDensity) {
      const all = cleaned.map((d: CleanedRow) => d.v);
      const kde = kernelDensityEstimator(kernelEpanechnikov(7), x.ticks(60));
      const density = kde(all);

      const y2 = d3.scaleLinear().domain([0, d3.max(density, (d: [number, number]) => d[1]) || 1]).range([innerH, 0]);

      const line = d3.line()
        .curve(d3.curveBasis)
        .x((d: [number, number]) => x(d[0]))
        .y((d: [number, number]) => y2(d[1]));

      g.append("path")
        .datum(density)
        .attr("fill", "none")
        .attr("stroke", "#111827")
        .attr("stroke-width", 1.25)
        .attr("d", line as any)
        .attr("opacity", 0.9);
    }

    function kernelDensityEstimator(kernel: (v: number) => number, X: number[]) {
      return (V: number[]) =>
        X.map((x: number): [number, number] => [x, d3.mean(V, (v: number) => kernel(x - v)) as number]);
    }
    function kernelEpanechnikov(k: number) {
      return (v: number) => Math.abs((v /= k)) <= 1 ? 0.75 * (1 - v * v) / k : 0;
    }
  }, [cleaned, feature, bins, mode, height, showDensity]);

  return <svg ref={ref} style={{ width: "100%", display: "block" }} height={height} />;
}

import React, { useEffect, useMemo, useRef } from "react";
import * as d3 from "d3";
import { sampleArray, toBool, toNumber } from "../lib/d3Utils";


type Row = { category: string; label?: number | string };
type PreparedRow = { k: string; all: number; event: number; nonevent: number };
type CountTuple = [string, Omit<PreparedRow, "k">];
type Props = {
  data: Row[];
  feature: string;
  topK?: number;
  mode: "grouped" | "stacked";
  height?: number;
};

export default function D3GroupedBar({ data, feature, topK = 20, mode, height = 480 }: Props) {
  const ref = useRef<SVGSVGElement | null>(null);

  const prepared = useMemo(() => {
    const rows = data || [];
    const counts = d3.rollups(
      rows,
      (arr: Row[]) => ({
        all: arr.length,
        event: arr.filter((r: Row) => r?.label === 1 || r?.label === "Event").length,
        nonevent: arr.filter((r: Row) => !(r?.label === 1 || r?.label === "Event")).length,
      }),
      (r: Row) => r.category ?? "Unknown"
    ) as CountTuple[];
    const sorted = counts.sort((a: CountTuple, b: CountTuple) => d3.descending(a[1].all, b[1].all)).slice(0, topK);
    return sorted.map(([k, v]: CountTuple): PreparedRow => ({ k, ...v }));
  }, [data, topK]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const svg = d3.select(el);
    svg.selectAll("*").remove();

    const width = el.clientWidth || 900;
    const margin = { top: 24, right: 16, bottom: 120, left: 64 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const g = svg
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("width", "100%")
      .attr("height", height)
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    if (!prepared.length) {
      g.append("text")
        .attr("x", innerW / 2)
        .attr("y", innerH / 2)
        .attr("text-anchor", "middle")
        .attr("fill", "#6b7280")
        .text("No categorical data to plot");
      return;
    }

    const categories = prepared.map((d: PreparedRow) => d.k);
    const x = d3.scaleBand().domain(categories).range([0, innerW]).padding(0.12);

    const labels = ["Non-Event", "Event"] as const;
    const colors = d3.scaleOrdinal<string, string>().domain(labels as unknown as string[]).range(["#60a5fa", "#f87171"]);

    const yMax = d3.max(prepared, (d: PreparedRow) => Math.max(d.event, d.nonevent)) || 1;
    const yStackMax = d3.max(prepared, (d: PreparedRow) => d.event + d.nonevent) || 1;

    const y = d3.scaleLinear().domain([0, mode === "stacked" ? yStackMax : yMax]).nice().range([innerH, 0]);
    const xGroup = d3.scaleBand().domain(labels as unknown as string[]).range([0, x.bandwidth()]).padding(0.08);

    g.append("g")
      .attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x))
      .selectAll("text")
      .style("font-size", "11px")
      .attr("text-anchor", "end")
      .attr("transform", "rotate(-35)");

    g.append("g").call(d3.axisLeft(y).ticks(6)).selectAll("text").style("font-size", "11px");

    const cat = g.append("g");
    prepared.forEach((d: PreparedRow) => {
      const x0 = x(d.k)!;
      if (mode === "grouped") {
        // Non-Event
        cat.append("rect")
          .attr("x", x0 + xGroup("Non-Event")!)
          .attr("y", y(d.nonevent))
          .attr("width", xGroup.bandwidth())
          .attr("height", innerH - y(d.nonevent))
          .attr("fill", colors("Non-Event"));
        // Event
        cat.append("rect")
          .attr("x", x0 + xGroup("Event")!)
          .attr("y", y(d.event))
          .attr("width", xGroup.bandwidth())
          .attr("height", innerH - y(d.event))
          .attr("fill", colors("Event"));
      } else {
        // stacked
        const y0 = y(d.nonevent + d.event);
        const y1 = y(d.nonevent);
        // Non-Event (bottom)
        cat.append("rect")
          .attr("x", x0)
          .attr("y", y1)
          .attr("width", x.bandwidth())
          .attr("height", innerH - y1)
          .attr("fill", colors("Non-Event"));
        // Event (top)
        cat.append("rect")
          .attr("x", x0)
          .attr("y", y0)
          .attr("width", x.bandwidth())
          .attr("height", y1 - y0)
          .attr("fill", colors("Event"));
      }
    });

    // legend
    const legend = g.append("g").attr("transform", `translate(0,-8)`);
    labels.forEach((lbl, i) => {
      const row = legend.append("g").attr("transform", `translate(${i * 110},0)`);
      row.append("rect").attr("width", 14).attr("height", 14).attr("fill", colors(lbl));
      row.append("text").attr("x", 18).attr("y", 12).style("font-size", "12px").text(lbl);
    });

    g.append("text")
      .attr("x", innerW / 2)
      .attr("y", -8)
      .attr("text-anchor", "middle")
      .style("font-weight", 600)
      .style("font-size", "13px")
      .text(`Bar Chart — ${feature}`);
  }, [prepared, feature, mode, height]);

  return <svg ref={ref} style={{ width: "100%", display: "block" }} height={height} />;
}

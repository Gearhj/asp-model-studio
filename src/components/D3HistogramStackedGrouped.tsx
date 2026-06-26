// @ts-nocheck
import React, { useEffect, useRef, useState } from "react";
import * as d3 from "d3";

const BASE =
  (import.meta as any)?.env?.VITE_API_BASE?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type Props = {
  feature: string;
  bins: number;
  layout: "grouped" | "stacked";
  samplePct: number;
};

type ServerPayload = {
  ok: boolean;
  feature: string;
  layout: "grouped" | "stacked";
  edges: number[];
  overall?: number[];
  event?: number[];
  nonevent?: number[];
  target_name?: string;
};

export default function D3HistogramStackedGrouped({
  feature,
  bins,
  layout,
  samplePct,
}: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [data, setData] = useState<ServerPayload | null>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        setError("");
        const resp = await fetch(`${BASE}/eda/d3_histogram`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            dataset_id: "",
            feature,
            bins,
            layout,
            sample_pct: samplePct,
          }),
        });
        const js: ServerPayload = await resp.json();
        if (!resp.ok || !js?.ok) throw new Error("Histogram error");
        if (alive) setData(js);
      } catch (e: any) {
        if (alive) {
          setData(null);
          setError(e?.message || "Failed to render histogram");
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [feature, bins, layout, samplePct]);

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    if (!data) return;

    const margin = { top: 28, right: 28, bottom: 50, left: 60 };
    const width = svgRef.current?.clientWidth || 900;
    const height = 320;

    const innerW = Math.max(300, width - margin.left - margin.right);
    const innerH = Math.max(140, height - margin.top - margin.bottom);

    const g = svg
      .attr("width", width)
      .attr("height", height)
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    const edges = Array.isArray(data.edges) ? data.edges : [];
    const centers = d3.pairs(edges).map(([a, b]) => (a + b) / 2);

    const series: { name: string; values: number[] }[] = [];
    if (Array.isArray(data.nonevent))
      series.push({ name: "Non-Event", values: data.nonevent! });
    if (Array.isArray(data.event))
      series.push({ name: "Event", values: data.event! });
    if (series.length === 0 && Array.isArray(data.overall))
      series.push({ name: "Overall", values: data.overall! });

    const x = d3
      .scaleBand()
      .domain(centers.map((c) => String(c)))
      .range([0, innerW])
      .padding(0.08);

    const maxY =
      layout === "stacked"
        ? d3.max(centers, (_, i) =>
            d3.sum(series.map((s) => s.values[i] || 0)),
          ) || 1
        : d3.max(series, (s) => d3.max(s.values) || 0) || 1;

    const y = d3.scaleLinear().domain([0, maxY]).nice().range([innerH, 0]);

    const color = d3
      .scaleOrdinal<string>()
      .domain(series.map((s) => s.name))
      .range(["#60a5fa", "#f87171", "#34d399"]); // blue, red, green

    g.append("g")
      .attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x).tickValues(x.domain().filter((_, i) => i % 2 === 0)))
      .selectAll("text")
      .attr("font-size", 10);

    g.append("g").call(d3.axisLeft(y));

    if (layout === "grouped") {
      const sub = d3
        .scaleBand()
        .domain(series.map((s) => s.name))
        .range([0, x.bandwidth()])
        .padding(0.12);

      const groups = g
        .append("g")
        .selectAll("g")
        .data(centers)
        .join("g")
        .attr("transform", (c) => `translate(${x(String(c))},0)`);

      series.forEach((s) => {
        groups
          .append("rect")
          .attr("x", sub(s.name)!)
          .attr("width", sub.bandwidth())
          .attr("y", innerH)
          .attr("height", 0)
          .attr("fill", color(s.name) as string)
          .transition()
          .duration(550)
          .attr("y", (_, i) => y(s.values[i] || 0))
          .attr("height", (_, i) => innerH - y(s.values[i] || 0));
      });
    } else {
      const stacked = d3.stack<number>().keys(d3.range(series.length))(
        centers.map((_, i) => series.map((s) => s.values[i] || 0)),
      );

      g.selectAll("g.layer")
        .data(stacked)
        .join("g")
        .attr("class", "layer")
        .attr("fill", (_, k) => color(series[k].name) as string)
        .selectAll("rect")
        .data((d) => d)
        .join("rect")
        .attr("x", (_, i) => x(String(centers[i]))!)
        .attr("width", x.bandwidth())
        .attr("y", innerH)
        .attr("height", 0)
        .transition()
        .duration(550)
        .attr("y", (d) => y(d[1]))
        .attr("height", (d) => y(d[0]) - y(d[1]));
    }

    g.append("text")
      .attr("x", innerW / 2)
      .attr("y", innerH + 36)
      .attr("text-anchor", "middle")
      .attr("font-size", 12)
      .text(`Bins (feature: ${data.feature})`);

    g.append("text")
      .attr("transform", "rotate(-90)")
      .attr("x", -innerH / 2)
      .attr("y", -44)
      .attr("text-anchor", "middle")
      .attr("font-size", 12)
      .text("Count");

    const legend = g
      .append("g")
      .attr("transform", `translate(${innerW + 20},${margin.top})`);

    series.forEach((s, i) => {
      const row = legend
        .append("g")
        .attr("transform", `translate(0,${i * 20})`);
      row
        .append("rect")
        .attr("width", 12)
        .attr("height", 12)
        .attr("fill", color(s.name) as string);
      row
        .append("text")
        .attr("x", 18)
        .attr("y", 10)
        .style("font-size", "12px")
        .text(s.name);
    });
  }, [data]);

  return (
    <svg
      ref={svgRef}
      style={{ width: "100%", height: 360, display: "block" }}
      aria-label="Histogram"
    >
      {error && (
        <text x="10" y="20" fill="crimson" fontSize="12">
          {error}
        </text>
      )}
    </svg>
  );
}

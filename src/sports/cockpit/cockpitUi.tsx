// Shared cockpit UI primitives + echarts chart wrappers. Light theme, slate/cyan language
// consistent with the rest of ASP Model Studio.
import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import ReactECharts from "echarts-for-react";

export const fmt = {
  n: (v: number | null | undefined, d = 4) => (v === null || v === undefined || Number.isNaN(v) ? "—" : v.toFixed(d)),
  int: (v: number | null | undefined) => (v === null || v === undefined ? "—" : Math.round(v).toLocaleString()),
  pct: (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(d)}%`),
  signed: (v: number | null | undefined, d = 4) => (v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}`),
};

const ACCENT = "#0891b2"; // cyan-600
const GRID = { left: 40, right: 16, top: 16, bottom: 28 };

export function Card({ title, description, icon: Icon, action, children, className = "" }:
  { title: string; description?: string; icon?: LucideIcon; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm ${className}`}>
      <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 gap-3">
          {Icon ? (
            <span className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-900 text-cyan-200">
              <Icon size={18} aria-hidden="true" />
            </span>
          ) : null}
          <div className="min-w-0">
            <h2 className="text-lg font-semibold tracking-tight text-slate-950">{title}</h2>
            {description ? <p className="mt-0.5 max-w-3xl text-sm leading-6 text-slate-600">{description}</p> : null}
          </div>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Pill({ label, tone = "slate" }: { label: string; tone?: "slate" | "emerald" | "amber" | "rose" | "cyan" | "violet" }) {
  const tones: Record<string, string> = {
    slate: "border-slate-200 bg-slate-50 text-slate-700",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-800",
    amber: "border-amber-200 bg-amber-50 text-amber-800",
    rose: "border-rose-200 bg-rose-50 text-rose-800",
    cyan: "border-cyan-200 bg-cyan-50 text-cyan-800",
    violet: "border-violet-200 bg-violet-50 text-violet-800",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${tones[tone]}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden="true" />
      {label}
    </span>
  );
}

export function MetricCard({ label, value, detail, tone }: { label: string; value: string; detail?: string; tone?: "up" | "down" | null }) {
  const color = tone === "up" ? "text-emerald-600" : tone === "down" ? "text-rose-600" : "text-slate-950";
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums tracking-tight ${color}`}>{value}</div>
      {detail ? <div className="mt-0.5 text-xs text-slate-500">{detail}</div> : null}
    </div>
  );
}

export function Button({ children, onClick, disabled, tone = "primary", size = "md" }:
  { children: ReactNode; onClick?: () => void; disabled?: boolean; tone?: "primary" | "ghost" | "dark"; size?: "sm" | "md" }) {
  const tones: Record<string, string> = {
    primary: "bg-cyan-600 text-white hover:bg-cyan-500 disabled:bg-slate-300",
    dark: "bg-slate-900 text-white hover:bg-slate-800 disabled:bg-slate-300",
    ghost: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-50",
  };
  const sizes = size === "sm" ? "px-3 py-1.5 text-xs" : "px-4 py-2 text-sm";
  return (
    <button onClick={onClick} disabled={disabled}
      className={`inline-flex items-center gap-2 rounded-lg font-semibold transition-colors disabled:cursor-not-allowed ${tones[tone]} ${sizes}`}>
      {children}
    </button>
  );
}

export function Segmented<T extends string>({ options, value, onChange }:
  { options: { value: T; label: string; disabled?: boolean }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex flex-wrap gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1">
      {options.map((o) => (
        <button key={o.value} disabled={o.disabled} onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
            value === o.value ? "bg-slate-900 text-white" : o.disabled ? "text-slate-300" : "text-slate-600 hover:bg-white"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function NumberField({ label, value, onChange, step = 1, min }: { label: string; value: number; onChange: (v: number) => void; step?: number; min?: number }) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      <input type="number" value={value} step={step} min={min}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm tabular-nums text-slate-900 focus:border-cyan-500 focus:outline-none" />
    </label>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-sm text-slate-600">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" />
      {label || "Working…"}
    </div>
  );
}

export function LoadGate({ state, children }: { state: { status: string; error?: string }; children: ReactNode }) {
  if (state.status === "loading" || state.status === "idle") return <Spinner label="Loading governed evidence…" />;
  if (state.status === "error") {
    const is404 = /\b404\b/.test(state.error || "");
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
        <div className="font-semibold">The modeling API could not be reached.</div>
        {is404 ? (
          <p className="mt-1 leading-6">The cockpit endpoint returned <b>404</b>. The backend service is likely running an older build that predates the modeling cockpit — restart the ASP Model Studio backend to load the <code>/api/cockpit</code> routes, then reload this page.</p>
        ) : (
          <p className="mt-1 leading-6">The backend may be unavailable. Confirm the ASP Model Studio backend is running, then reload.</p>
        )}
        <p className="mt-2 font-mono text-xs text-rose-500">{state.error}</p>
      </div>
    );
  }
  return <>{children}</>;
}

// -------------------------------------------------------------------------- charts
function chart(option: any, height = 220) {
  return <ReactECharts option={option} style={{ height, width: "100%" }} opts={{ renderer: "svg" }} notMerge lazyUpdate />;
}

export function BarChart({ categories, values, height = 220, color = ACCENT, horizontal = false, valueFmt }:
  { categories: string[]; values: number[]; height?: number; color?: string; horizontal?: boolean; valueFmt?: (v: number) => string }) {
  const cat = { type: "category", data: categories, axisLabel: { fontSize: 10, color: "#64748b" } };
  const val = { type: "value", axisLabel: { fontSize: 10, color: "#64748b" } };
  return chart({
    grid: GRID,
    xAxis: horizontal ? val : cat,
    yAxis: horizontal ? { ...cat, inverse: true } : val,
    tooltip: { trigger: "axis", valueFormatter: (v: number) => (valueFmt ? valueFmt(v) : String(v)) },
    series: [{ type: "bar", data: values, itemStyle: { color, borderRadius: horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0] } }],
  }, height);
}

export function Histogram({ bins, color = ACCENT, height = 160 }: { bins: { lo: number; hi: number; count: number }[]; color?: string; height?: number }) {
  const cats = bins.map((b) => b.lo.toFixed(2));
  return chart({
    grid: { left: 44, right: 10, top: 10, bottom: 22 },
    xAxis: { type: "category", data: cats, axisLabel: { show: false }, axisTick: { show: false } },
    yAxis: { type: "value", axisLabel: { fontSize: 9, color: "#94a3b8" }, splitLine: { lineStyle: { color: "#f1f5f9" } } },
    tooltip: { trigger: "axis", formatter: (p: any) => { const b = bins[p[0].dataIndex]; return `[${b.lo.toFixed(2)}, ${b.hi.toFixed(2)})<br/><b>${b.count.toLocaleString()}</b>`; } },
    series: [{ type: "bar", data: bins.map((b) => b.count), itemStyle: { color }, barCategoryGap: "8%" }],
  }, height);
}

export function BeforeAfter({ before, after, height = 150 }:
  { before: { lo: number; hi: number; count: number }[]; after: { lo: number; hi: number; count: number }[]; height?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Before</div>
        <Histogram bins={before} color="#f59e0b" height={height} />
      </div>
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">After</div>
        <Histogram bins={after} color="#0891b2" height={height} />
      </div>
    </div>
  );
}

// Outlier before/after pair with threshold markers drawn ON the before histogram. Before and after
// share the same value x-axis domain (the backend bins both on the same reference), so the scientist
// can compare capping impact directly. Markers are only drawn when the threshold falls inside the
// visible domain; a one-sided threshold shows a single marker.
type HistBin = { lo: number; hi: number; count: number };
function outlierHistOption(
  bins: HistBin[],
  { color, markers, min, max }: { color: string; markers: { value: number; label: string; color: string }[]; min: number; max: number },
) {
  const visible = markers.filter((m) => Number.isFinite(m.value) && m.value >= min && m.value <= max);
  return {
    grid: { left: 42, right: 14, top: 14, bottom: 20 },
    xAxis: { type: "value", min, max, axisLabel: { fontSize: 9, color: "#94a3b8" }, axisTick: { show: false } },
    yAxis: { type: "value", axisLabel: { fontSize: 9, color: "#94a3b8" }, splitLine: { lineStyle: { color: "#f1f5f9" } } },
    tooltip: {
      trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (p: any) => { const b = bins[p[0].dataIndex]; return b ? `[${b.lo.toFixed(3)}, ${b.hi.toFixed(3)})<br/><b>${b.count.toLocaleString()}</b>` : ""; },
    },
    series: [{
      type: "bar", data: bins.map((b) => [(b.lo + b.hi) / 2, b.count]), itemStyle: { color }, barWidth: "96%",
      markLine: visible.length ? {
        symbol: ["none", "none"], silent: true, animation: false,
        data: visible.map((m) => ({
          xAxis: m.value,
          lineStyle: { color: m.color, type: "dashed", width: 1.5 },
          label: { show: true, position: "insideEndTop", fontSize: 9, color: m.color, formatter: `${m.label} ${m.value.toFixed(2)}` },
        })),
      } : undefined,
    }],
  };
}

export function OutlierHistogramPair({ before, after, lower, upper, treated, height = 150 }:
  { before: HistBin[]; after: HistBin[]; lower: number | null; upper: number | null; treated: boolean; height?: number }) {
  if (!before.length) return null;
  const min = before[0].lo;
  const max = before[before.length - 1].hi;
  const markers = [
    ...(lower !== null && lower !== undefined ? [{ value: lower, label: "Lower", color: "#e11d48" }] : []),
    ...(upper !== null && upper !== undefined ? [{ value: upper, label: "Upper", color: "#e11d48" }] : []),
  ];
  return (
    <div className="grid grid-cols-2 gap-3">
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Before · thresholds marked</div>
        {chart(outlierHistOption(before, { color: "#f59e0b", markers, min, max }), height)}
      </div>
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{treated ? "After treatment" : "No treatment — distribution unchanged"}</div>
        {chart(outlierHistOption(after, { color: treated ? "#0891b2" : "#cbd5e1", markers: [], min, max }), height)}
      </div>
    </div>
  );
}

export function CalibrationChart({ reliability, height = 240 }: { reliability: { meanPredicted: number; observed: number; count: number }[]; height?: number }) {
  const pts = reliability.filter((r) => r.count > 0).map((r) => [r.meanPredicted, r.observed]);
  return chart({
    grid: { left: 44, right: 16, top: 16, bottom: 32 },
    xAxis: { type: "value", min: 0, max: 1, name: "Predicted", nameLocation: "middle", nameGap: 22, axisLabel: { fontSize: 10 } },
    yAxis: { type: "value", min: 0, max: 1, name: "Observed", axisLabel: { fontSize: 10 } },
    tooltip: { trigger: "item", formatter: (p: any) => `pred ${p.value[0].toFixed(3)}<br/>obs ${p.value[1].toFixed(3)}` },
    series: [
      { type: "line", data: [[0, 0], [1, 1]], lineStyle: { color: "#cbd5e1", type: "dashed" }, symbol: "none" },
      { type: "scatter", data: pts, symbolSize: 8, itemStyle: { color: ACCENT } },
    ],
  }, height);
}

export function ConfusionHeatmap({ matrix, labels, height = 300 }: { matrix: number[][]; labels: string[]; height?: number }) {
  const data: [number, number, number][] = [];
  const rowSums = matrix.map((r) => r.reduce((a, b) => a + b, 0) || 1);
  for (let i = 0; i < matrix.length; i++)
    for (let j = 0; j < matrix[i].length; j++) data.push([j, matrix.length - 1 - i, matrix[i][j] / rowSums[i]]);
  const short = labels.map((l) => l.replace("STRIKEOUT", "K").replace("WALK_HBP_CI", "BB").replace("HOME_RUN", "HR").replace("OTHER_REACH", "ROE").replace("BIP_OUT", "OUT"));
  return chart({
    grid: { left: 52, right: 12, top: 10, bottom: 60 },
    xAxis: { type: "category", data: short, splitArea: { show: true }, axisLabel: { fontSize: 9, rotate: 45 }, name: "predicted", nameLocation: "middle", nameGap: 40 },
    yAxis: { type: "category", data: [...short].reverse(), splitArea: { show: true }, axisLabel: { fontSize: 9 } },
    visualMap: { min: 0, max: 1, calculable: false, show: false, inRange: { color: ["#f8fafc", "#67e8f9", "#0891b2", "#0e7490"] } },
    tooltip: { formatter: (p: any) => `${p.value[2] ? (p.value[2] * 100).toFixed(1) : 0}% of row` },
    series: [{ type: "heatmap", data, label: { show: true, fontSize: 8, formatter: (p: any) => (p.value[2] > 0.02 ? (p.value[2] * 100).toFixed(0) : "") } }],
  }, height);
}

export function GroupedBars({ categories, series, height = 260, valueFmt }:
  { categories: string[]; series: { name: string; data: number[]; color: string }[]; height?: number; valueFmt?: (v: number) => string }) {
  return chart({
    grid: { left: 48, right: 16, top: 30, bottom: 40 },
    legend: { top: 0, textStyle: { fontSize: 11 } },
    xAxis: { type: "category", data: categories, axisLabel: { fontSize: 10, rotate: categories.length > 4 ? 20 : 0 } },
    yAxis: { type: "value", axisLabel: { fontSize: 10 } },
    tooltip: { trigger: "axis", valueFormatter: (v: number) => (valueFmt ? valueFmt(v) : String(v)) },
    series: series.map((s) => ({ name: s.name, type: "bar", data: s.data, itemStyle: { color: s.color, borderRadius: [3, 3, 0, 0] } })),
  }, height);
}

const CLUSTER_COLORS = ["#0891b2", "#7c3aed", "#f59e0b", "#e11d48", "#10b981", "#6366f1", "#ec4899", "#14b8a6", "#f97316", "#8b5cf6", "#0ea5e9", "#84cc16", "#ef4444", "#a855f7", "#22d3ee"];

export function ScatterClusters({ points, height = 320 }: { points: { x: number; y: number; cluster: number }[]; height?: number }) {
  const byCluster = new Map<number, [number, number][]>();
  for (const p of points) {
    if (!byCluster.has(p.cluster)) byCluster.set(p.cluster, []);
    byCluster.get(p.cluster)!.push([p.x, p.y]);
  }
  const series = [...byCluster.entries()].sort((a, b) => a[0] - b[0]).map(([c, data]) => ({
    name: `Cluster ${c}`, type: "scatter", data, symbolSize: 7, itemStyle: { color: CLUSTER_COLORS[c % CLUSTER_COLORS.length], opacity: 0.75 },
  }));
  return chart({
    grid: { left: 44, right: 16, top: 26, bottom: 30 },
    legend: { top: 0, textStyle: { fontSize: 10 } },
    xAxis: { type: "value", scale: true, name: "PC1", nameLocation: "middle", nameGap: 20, axisLabel: { fontSize: 10 } },
    yAxis: { type: "value", scale: true, name: "PC2", axisLabel: { fontSize: 10 } },
    tooltip: { trigger: "item" },
    series,
  }, height);
}

export function LineChart({ categories, series, height = 220 }:
  { categories: string[]; series: { name: string; data: (number | null)[]; color: string }[]; height?: number }) {
  return chart({
    grid: { left: 48, right: 16, top: 28, bottom: 28 },
    legend: { top: 0, textStyle: { fontSize: 11 } },
    xAxis: { type: "category", data: categories, axisLabel: { fontSize: 10 } },
    yAxis: { type: "value", scale: true, axisLabel: { fontSize: 10 } },
    tooltip: { trigger: "axis" },
    series: series.map((s) => ({ name: s.name, type: "line", data: s.data, smooth: true, itemStyle: { color: s.color }, lineStyle: { color: s.color } })),
  }, height);
}

// ATLAS Visual Intelligence Foundation -- shared ECharts theme adapter.
// Restrained, professional palette matching ATLAS's existing slate/blue identity
// (see src/index.css / Tailwind config) -- no gradients, no glow, no decorative 3D.
export const ATLAS_CHART_COLORS = {
  axis: "#475569", // slate-600
  grid: "#e2e8f0", // slate-200
  text: "#0f172a", // slate-950
  subtleText: "#64748b", // slate-500
  train: "#2563eb", // blue-600
  test: "#0f766e", // teal-700
  oot: "#b45309", // amber-700
  positive: "#0f766e",
  negative: "#b91c1c", // red-700
  mean: "#7c3aed", // violet-600
  median: "#ea580c", // orange-600
  identity: "#334155", // slate-700
  warning: "#b45309",
  fail: "#b91c1c",
  pass: "#15803d", // green-700
} as const;

export const ATLAS_ECHARTS_THEME = {
  color: [ATLAS_CHART_COLORS.train, ATLAS_CHART_COLORS.test, ATLAS_CHART_COLORS.oot],
  backgroundColor: "transparent",
  textStyle: { fontFamily: "inherit", color: ATLAS_CHART_COLORS.text },
  title: { textStyle: { fontSize: 14, fontWeight: 600, color: ATLAS_CHART_COLORS.text }, subtextStyle: { fontSize: 11, color: ATLAS_CHART_COLORS.subtleText } },
  grid: { left: 56, right: 24, top: 48, bottom: 48, containLabel: true },
  categoryAxis: {
    axisLine: { lineStyle: { color: ATLAS_CHART_COLORS.axis } },
    axisLabel: { color: ATLAS_CHART_COLORS.subtleText, fontSize: 11 },
    splitLine: { show: false },
  },
  valueAxis: {
    axisLine: { show: false },
    axisLabel: { color: ATLAS_CHART_COLORS.subtleText, fontSize: 11 },
    splitLine: { lineStyle: { color: ATLAS_CHART_COLORS.grid } },
  },
  tooltip: {
    backgroundColor: "#0f172a",
    borderWidth: 0,
    textStyle: { color: "#f8fafc", fontSize: 12 },
    padding: [8, 12],
    confine: true, // keeps tooltips within the chart viewport (Phase L requirement)
  },
  legend: { textStyle: { color: ATLAS_CHART_COLORS.subtleText, fontSize: 11 } },
} as const;

export function partitionColor(partition: "train" | "test" | "oot" | string): string {
  if (partition === "train") return ATLAS_CHART_COLORS.train;
  if (partition === "test") return ATLAS_CHART_COLORS.test;
  if (partition === "oot") return ATLAS_CHART_COLORS.oot;
  return ATLAS_CHART_COLORS.subtleText;
}

export function statusColor(status: "pass" | "warning" | "fail" | string): string {
  if (status === "pass") return ATLAS_CHART_COLORS.pass;
  if (status === "warning") return ATLAS_CHART_COLORS.warning;
  if (status === "fail") return ATLAS_CHART_COLORS.fail;
  return ATLAS_CHART_COLORS.subtleText;
}

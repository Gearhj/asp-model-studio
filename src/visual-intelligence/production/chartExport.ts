// ATLAS Visual Intelligence Production Integration, Phase I -- consistent chart
// export behavior, shared by all three production panels. PNG export reuses
// the already-built (but previously unwired) exportChartAsPng from
// EChartsPanel.tsx; CSV/JSON export operate only on the BOUNDED analytical
// result already held in component state -- never a raw multi-row dataset.
import { exportChartAsPng } from "../EChartsPanel";
import type * as echarts from "echarts/core";
import type { VisualAnalysisContext } from "./visualAnalysisContext";

function exportFilenameBase(analysisType: string, context: VisualAnalysisContext): string {
  const parts = [
    context.projectId,
    analysisType,
    context.partition ?? "na",
    context.scoringRunId ?? context.datasetVersionId ?? "workspace",
    new Date().toISOString().slice(0, 10),
  ];
  return parts.map((part) => String(part).replace(/[^a-zA-Z0-9_-]+/g, "-")).join("_");
}

export function exportChartPng(instance: echarts.ECharts | null, analysisType: string, context: VisualAnalysisContext): boolean {
  if (!instance) return false;
  exportChartAsPng(instance, `${exportFilenameBase(analysisType, context)}.png`);
  return true;
}

export function exportVisualizationSpecJson(spec: Record<string, unknown>, analysisType: string, context: VisualAnalysisContext): void {
  const blob = new Blob([JSON.stringify({ context, spec }, null, 2)], { type: "application/json" });
  downloadBlob(blob, `${exportFilenameBase(analysisType, context)}.json`);
}

/**
 * Exports the currently-displayed BOUNDED analytical result as CSV -- e.g.
 * histogram bins, a confusion matrix, a diagnostics summary -- never raw
 * source rows (Phase I requirement 2). `rows` must already be the bounded,
 * already-rendered result set. `sampled`/`approximate` prepend an honest
 * label to the filename so a sampled/approximate export can never be
 * mistaken for an exact full-population export (Phase I requirement 3/4).
 */
export function exportBoundedResultCsv(
  rows: Array<Record<string, unknown>>,
  analysisType: string,
  context: VisualAnalysisContext,
  options: { sampled?: boolean; approximate?: boolean } = {}
): void {
  if (!rows.length) return;
  const columns = Array.from(rows.reduce((set, row) => { Object.keys(row).forEach((k) => set.add(k)); return set; }, new Set<string>()));
  const escape = (value: unknown) => {
    const text = value === null || value === undefined ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const lines = [columns.join(","), ...rows.map((row) => columns.map((c) => escape(row[c])).join(","))];
  const labelPrefix = [options.sampled ? "sampled" : null, options.approximate ? "approximate" : null].filter(Boolean).join("-");
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  downloadBlob(blob, `${labelPrefix ? labelPrefix + "_" : ""}${exportFilenameBase(analysisType, context)}.csv`);
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

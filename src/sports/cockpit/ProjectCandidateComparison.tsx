import { useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import { AlertTriangle, ChevronDown, ChevronRight, History, ShieldCheck } from "lucide-react";
import type { CandidateGroup } from "./projectModelLabApi";

type MetricKey = "meanOofLogLoss" | "summedBrier" | "ece" | "macroF1" | "accuracy" | "runtimeMs";

const METRICS: Record<MetricKey, { label: string; lower: boolean; digits: number }> = {
  meanOofLogLoss: { label: "Multiclass Log Loss", lower: true, digits: 6 },
  summedBrier: { label: "Summed Multiclass Brier", lower: true, digits: 6 },
  ece: { label: "ECE", lower: true, digits: 6 },
  macroF1: { label: "Macro-F1 diagnostic", lower: false, digits: 4 },
  accuracy: { label: "Accuracy diagnostic", lower: false, digits: 4 },
  runtimeMs: { label: "Runtime", lower: true, digits: 0 },
};

const number = (value: number | null | undefined, digits = 6) => value == null ? "—" : value.toFixed(digits);
const short = (value: string) => value.length > 20 ? `${value.slice(0, 16)}…` : value;
const human = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

export function ProjectCandidateComparison({
  groups,
  title = "Development candidate comparison",
  source = "ALL",
  onSourceChange,
}: {
  groups: CandidateGroup[];
  title?: string;
  source?: "ALL" | "CURRENT_BATCH" | "HISTORICAL_BASELINE";
  onSourceChange?: (source: "ALL" | "CURRENT_BATCH" | "HISTORICAL_BASELINE") => void;
}) {
  const [metric, setMetric] = useState<MetricKey>("meanOofLogLoss");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const filtered = useMemo(() => groups.filter((group) => source === "ALL" || group.evidenceSources.includes(source)), [groups, source]);
  const completed = useMemo(() => filtered.filter((group) => group.status === "COMPLETE" && group[metric] != null).sort((a, b) => {
    const delta = Number(a[metric]) - Number(b[metric]);
    return METRICS[metric].lower ? delta : -delta;
  }), [filtered, metric]);
  const failed = filtered.filter((group) => group.status !== "COMPLETE");
  const nullReference = completed.find((group) => group.modelFamily === "class_frequency_null")?.[metric] as number | null | undefined;
  const option = useMemo(() => ({
    animation: false,
    grid: { left: 230, right: 35, top: 24, bottom: 42 },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (items: any[]) => {
        const index = items?.[0]?.dataIndex ?? 0;
        const group = completed[index];
        return group ? `<b>${human(group.modelFamily)}</b><br/>${group.featureSetName}<br/>${METRICS[metric].label}: ${number(group[metric] as number, METRICS[metric].digits)}<br/>Fold SD: ${number(group.foldStandardDeviation, 6)}<br/>Attempts: ${group.attemptCount} · ${human(group.reproducibilityStatus)}` : "";
      },
    },
    xAxis: {
      type: "value",
      name: `${METRICS[metric].label} · ${METRICS[metric].lower ? "lower is better" : "higher is better"}`,
      nameLocation: "middle",
      nameGap: 30,
      axisLabel: { fontSize: 10, color: "#64748b" },
      scale: true,
    },
    yAxis: {
      type: "category",
      inverse: true,
      data: completed.map((group) => `${human(group.modelFamily)} · ${group.featureSetName}`),
      axisLabel: { width: 210, overflow: "truncate", fontSize: 10, color: "#334155" },
    },
    series: [
      {
        name: METRICS[metric].label,
        type: "bar",
        data: completed.map((group, index) => ({
          value: group[metric],
          itemStyle: { color: index === 0 && metric === "meanOofLogLoss" ? "#0f766e" : "#0891b2", borderRadius: [0, 4, 4, 0] },
        })),
        barMaxWidth: 22,
        markLine: nullReference == null ? undefined : {
          silent: true,
          symbol: "none",
          label: { formatter: "Class-frequency null", color: "#7c2d12", fontSize: 10 },
          lineStyle: { color: "#f97316", type: "dashed", width: 1.5 },
          data: [{ xAxis: nullReference }],
        },
      },
      ...(metric === "meanOofLogLoss" ? [{
        name: "Fold standard deviation",
        type: "custom",
        silent: true,
        renderItem: (_params: any, api: any) => {
          const value = api.value(0);
          const category = api.value(1);
          const deviation = api.value(2);
          const start = api.coord([value - deviation, category]);
          const end = api.coord([value + deviation, category]);
          return { type: "group", children: [
            { type: "line", shape: { x1: start[0], y1: start[1], x2: end[0], y2: end[1] }, style: { stroke: "#0f172a", lineWidth: 1 } },
            { type: "line", shape: { x1: start[0], y1: start[1] - 4, x2: start[0], y2: start[1] + 4 }, style: { stroke: "#0f172a", lineWidth: 1 } },
            { type: "line", shape: { x1: end[0], y1: end[1] - 4, x2: end[0], y2: end[1] + 4 }, style: { stroke: "#0f172a", lineWidth: 1 } },
          ] };
        },
        encode: { x: [0, 2], y: 1 },
        data: completed.map((group, index) => [group.meanOofLogLoss, index, group.foldStandardDeviation ?? 0]),
        z: 10,
      }] : []),
    ],
  }), [completed, metric, nullReference]);

  return (
    <section className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="candidate-comparison">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h3 className="text-sm font-semibold text-slate-950">{title}</h3><p className="mt-1 text-xs text-slate-500">One bar and one ranked row per canonical candidate specification. Historical attempts remain expandable immutable evidence.</p></div>
        <div className="flex flex-wrap gap-2">
          <label className="text-[10px] font-semibold uppercase text-slate-500">Metric<select value={metric} onChange={(event) => setMetric(event.target.value as MetricKey)} className="ml-2 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs normal-case text-slate-800">{Object.entries(METRICS).map(([key, item]) => <option key={key} value={key}>{item.label}</option>)}</select></label>
          {onSourceChange ? <label className="text-[10px] font-semibold uppercase text-slate-500">Evidence<select value={source} onChange={(event) => onSourceChange(event.target.value as typeof source)} className="ml-2 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs normal-case text-slate-800"><option value="ALL">All verified</option><option value="CURRENT_BATCH">Current batches</option><option value="HISTORICAL_BASELINE">Historical baseline</option></select></label> : null}
        </div>
      </div>
      <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-2" data-testid="candidate-log-loss-chart">
        {completed.length ? <ReactECharts option={option} style={{ height: Math.max(300, completed.length * 42), width: "100%" }} opts={{ renderer: "svg" }} notMerge lazyUpdate /> : <div className="grid h-64 place-items-center text-sm text-slate-500">No completed candidate has this metric. Failed candidates are not plotted as zero.</div>}
      </div>
      <div role="region" aria-label="Candidate comparison table" tabIndex={0} className="mt-3 overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full min-w-[1500px] text-left text-[11px]"><thead className="sticky top-0 bg-slate-50"><tr>{["", "Rank", "Candidate", "Family", "Feature universe", "Hyperparameters", "Tuning", "Attempts", "Folds", "Log loss", "Fold SD", "Brier", "ECE", "Macro-F1", "Accuracy", "Runtime", "Status", "Immutable evidence"].map((heading) => <th key={heading} className="border-b border-slate-200 px-2 py-2 uppercase tracking-wide text-slate-500">{heading}</th>)}</tr></thead>
          <tbody>{filtered.map((group) => {
            const isExpanded = expanded.has(group.candidateFingerprint);
            return [<tr key={group.candidateFingerprint} className={group.rank === 1 ? "bg-emerald-50/60" : "bg-white"}>
              <td className="border-b border-slate-100 px-2 py-2"><button type="button" aria-label={`${isExpanded ? "Collapse" : "Expand"} attempt history`} onClick={() => setExpanded((current) => { const next = new Set(current); if (next.has(group.candidateFingerprint)) next.delete(group.candidateFingerprint); else next.add(group.candidateFingerprint); return next; })} className="rounded p-1 text-slate-500 hover:bg-slate-100">{isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</button></td>
              <td className="border-b border-slate-100 px-2 py-2 font-semibold">{group.rank ?? "—"}</td><td className="border-b border-slate-100 px-2 py-2"><b>{human(group.modelFamily)}</b><div className="text-[9px] text-slate-500">{group.developmentLabel.replaceAll("_", " ")}</div></td><td className="border-b border-slate-100 px-2 py-2">{human(group.modelFamily)}</td><td className="border-b border-slate-100 px-2 py-2">{group.featureSetName}</td><td className="max-w-60 truncate border-b border-slate-100 px-2 py-2 font-mono text-[9px]" title={JSON.stringify(group.hyperparameters)}>{JSON.stringify(group.hyperparameters)}</td><td className="border-b border-slate-100 px-2 py-2">{human(group.tuningMode)}</td><td className="border-b border-slate-100 px-2 py-2">{group.attemptCount} ({group.completedAttemptCount} complete / {group.failedAttemptCount} failed)</td><td className="border-b border-slate-100 px-2 py-2">{group.foldsCompleted}/5</td><td className="border-b border-slate-100 px-2 py-2 font-semibold tabular-nums">{number(group.meanOofLogLoss)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{number(group.foldStandardDeviation)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{number(group.summedBrier)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{number(group.ece)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{number(group.macroF1, 4)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{number(group.accuracy, 4)}</td><td className="border-b border-slate-100 px-2 py-2">{group.runtimeMs == null ? "—" : `${(group.runtimeMs / 1000).toFixed(1)}s`}</td><td className="border-b border-slate-100 px-2 py-2"><span className={`inline-flex rounded-full border px-2 py-1 text-[9px] font-semibold ${group.status === "COMPLETE" ? group.reproducibilityStatus === "REPRODUCED" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-900" : "border-rose-200 bg-rose-50 text-rose-800"}`}>{human(group.status === "COMPLETE" ? group.reproducibilityStatus : "FAILED")}</span></td><td className="border-b border-slate-100 px-2 py-2 font-mono text-[9px]" title={group.immutableEvidenceIdentity}>{short(group.immutableEvidenceIdentity)}</td>
            </tr>, isExpanded ? <tr key={`${group.candidateFingerprint}:attempts`}><td colSpan={18} className="border-b border-slate-200 bg-slate-50 p-3"><div className="flex items-center gap-2 text-xs font-semibold text-slate-800"><History size={14} /> Immutable attempt history</div><div className="mt-2 grid gap-2 lg:grid-cols-2">{group.attempts.map((attempt) => <div key={`${attempt.runReceiptSha256}:${attempt.attemptId}`} className="rounded-lg border border-slate-200 bg-white p-3"><div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{attempt.evidenceSource === "CURRENT_BATCH" ? "Current batch" : "Historical baseline"}</span><span className={`rounded-full border px-2 py-0.5 text-[9px] font-semibold ${attempt.status === "COMPLETE" ? "border-emerald-200 text-emerald-800" : "border-rose-200 text-rose-800"}`}>{attempt.status}</span></div><div className="mt-2 grid grid-cols-2 gap-1 text-[10px] text-slate-600"><span>Log loss <b className="text-slate-900">{number(attempt.meanOofLogLoss)}</b></span><span>Seed <b className="text-slate-900">{attempt.seed ?? "—"}</b></span><span>Created <b className="text-slate-900">{attempt.createdAt || "—"}</b></span><span>Runtime <b className="text-slate-900">{attempt.runtimeMs == null ? "—" : `${(attempt.runtimeMs / 1000).toFixed(1)}s`}</b></span></div>{attempt.errorReason ? <p className="mt-2 text-[10px] text-rose-700">{attempt.errorCode}: {attempt.errorReason}</p> : null}<div className="mt-2 truncate font-mono text-[9px] text-slate-400" title={attempt.runReceiptSha256}>{attempt.runReceiptSha256}</div></div>)}</div></td></tr> : null];
          })}</tbody></table>
      </div>
      {failed.length ? <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 p-3" data-testid="failed-candidate-evidence"><div className="flex items-center gap-2 text-xs font-semibold text-rose-900"><AlertTriangle size={14} /> Failed candidates remain evidence; none is plotted as zero</div><div className="mt-2 flex flex-wrap gap-2">{failed.map((group) => <span key={group.candidateFingerprint} className="rounded-full border border-rose-200 bg-white px-2 py-1 text-[10px] text-rose-800">{human(group.modelFamily)} · {group.featureSetName} · {group.attemptCount} attempt(s)</span>)}</div></div> : null}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-slate-500"><ShieldCheck size={13} className="text-emerald-600" /><span>Leading development candidate is not a champion.</span><span>Accuracy and macro-F1 are diagnostics.</span><span>Final OOT remains locked.</span></div>
    </section>
  );
}

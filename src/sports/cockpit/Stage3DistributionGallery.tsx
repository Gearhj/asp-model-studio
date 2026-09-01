import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import type { CustomSeriesRenderItem, EChartsOption } from "echarts";
import {
  AlertTriangle,
  BarChart3,
  Bookmark,
  BookmarkCheck,
  Boxes,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Filter,
  Loader2,
  Maximize2,
  RefreshCw,
  Search,
  Settings2,
} from "lucide-react";
import EChartsPanel from "../../visual-intelligence/EChartsPanel";
import { CockpitDrawer } from "./CockpitDrawer";
import {
  useProjectEdaQuery,
  type CategoryCountsData,
  type DistributionData,
  type ProjectEdaEnvelope,
  type ProjectEdaFamily,
  type ProjectEdaFilters,
  type ProjectEdaVariable,
} from "./projectEdaApi";

export type GalleryVariableKind = "continuous" | "low-cardinality" | "binary" | "categorical" | "missingness-indicator";
type GalleryHandoff = "outliers" | "missing" | "features";
type GallerySort = "family" | "name" | "missingness" | "cardinality" | "association";

const TARGET_ORDER = ["STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE", "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH"];
const FAMILY_PRIORITY = ["CORE_GOLD_48", "CALENDAR", "REST_AND_TRAVEL", "CIRCADIAN", "DIVISION_AND_REPEAT_OPPONENT", "INTERACTIONS", "MISSINGNESS_INDICATORS"];

function numeric(variable: ProjectEdaVariable): boolean {
  return /numeric|int|float|double|number/i.test(variable.dataType);
}

export function classifyGalleryVariable(variable: ProjectEdaVariable): GalleryVariableKind {
  const name = variable.name.toLowerCase();
  if (variable.role === "MISSINGNESS_INDICATOR" || /(_missing|_insufficient|missing_indicator|insufficient_history)/.test(name)) return "missingness-indicator";
  if (/^(is_|has_|played_|crossed_|returned_|first_game_|previous_game_was_|doubleheader_)/.test(name) || variable.uniqueCount === 2) return "binary";
  if (!numeric(variable)) return "categorical";
  if ((variable.uniqueCount !== null && variable.uniqueCount <= 16) || /(inning|outs|base_mask|day_of_week|game_number|month|season_phase|top_bottom)/.test(name)) return "low-cardinality";
  return "continuous";
}

function familyRank(name: string): number {
  const exact = FAMILY_PRIORITY.indexOf(name);
  if (exact >= 0) return exact;
  const normalized = name.toUpperCase().replaceAll(/[^A-Z0-9]+/g, "_");
  const fuzzy = FAMILY_PRIORITY.findIndex((candidate) => normalized.includes(candidate) || candidate.includes(normalized));
  return fuzzy >= 0 ? fuzzy : FAMILY_PRIORITY.length + 1;
}

function interleaveKinds(variables: ProjectEdaVariable[]): ProjectEdaVariable[] {
  const order: GalleryVariableKind[] = ["continuous", "low-cardinality", "missingness-indicator", "binary", "categorical"];
  const buckets = new Map(order.map((kind) => [kind, variables.filter((variable) => classifyGalleryVariable(variable) === kind)]));
  const output: ProjectEdaVariable[] = [];
  for (let index = 0; output.length < variables.length; index += 1) {
    for (const kind of order) {
      const variable = buckets.get(kind)?.[index];
      if (variable) output.push(variable);
    }
  }
  return output;
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return Math.abs(value) >= 1000 ? value.toLocaleString(undefined, { maximumFractionDigits: digits }) : value.toFixed(digits);
}

function displayedCategoryRows(data: CategoryCountsData): CategoryCountsData["categories"] {
  return data.otherCategory ? [...data.categories, data.otherCategory] : data.categories;
}

function frequencyOption(data: CategoryCountsData): EChartsOption {
  const rows = displayedCategoryRows(data);
  return {
    animationDuration: 220,
    grid: { left: 112, right: 16, top: 8, bottom: 28, containLabel: true },
    tooltip: { trigger: "axis", confine: true },
    xAxis: { type: "value", name: "Share (%)", max: 100 },
    yAxis: { type: "category", data: rows.map((row) => row.value), axisLabel: { width: 108, overflow: "truncate" } },
    series: [{ type: "bar", data: rows.map((row) => row.percent), itemStyle: { color: "#0891b2", borderRadius: [0, 4, 4, 0] } }],
  };
}

function targetCompositionOption(data: CategoryCountsData, taxonomy: string[]): EChartsOption {
  const rows = displayedCategoryRows(data);
  return {
    animationDuration: 220,
    color: ["#0891b2", "#2563eb", "#7c3aed", "#db2777", "#ea580c", "#ca8a04", "#059669", "#475569"],
    grid: { left: 112, right: 16, top: 32, bottom: 28, containLabel: true },
    tooltip: { trigger: "axis", confine: true },
    legend: { type: "scroll", top: 0, textStyle: { fontSize: 9 } },
    xAxis: { type: "value", name: "Within level (%)", max: 100 },
    yAxis: { type: "category", data: rows.map((row) => row.value), axisLabel: { width: 108, overflow: "truncate" } },
    series: taxonomy.map((outcome) => ({
      name: outcome,
      type: "bar",
      stack: "outcome",
      data: rows.map((row) => row.targetComposition.find((item) => item.value === outcome)?.percent ?? 0),
    })),
  };
}

function histogramOption(data: DistributionData, logScale = false): EChartsOption {
  return {
    animationDuration: 220,
    grid: { left: 48, right: 16, top: 10, bottom: 42, containLabel: true },
    tooltip: { trigger: "axis", confine: true },
    xAxis: { type: "category", name: data.variable, data: data.histogram.map((row) => `${formatNumber(row.binStart)}–${formatNumber(row.binEnd)}`), axisLabel: { hideOverlap: true } },
    yAxis: { type: logScale ? "log" : "value", name: "Rows" },
    dataZoom: [{ type: "inside" }],
    series: [{ type: "bar", data: data.histogram.map((row) => row.count), itemStyle: { color: "#0e7490", borderRadius: [3, 3, 0, 0] } }],
  };
}

function densityOption(data: DistributionData, logScale = false): EChartsOption {
  return {
    animationDuration: 220,
    grid: { left: 48, right: 16, top: 10, bottom: 42, containLabel: true },
    tooltip: { trigger: "axis", confine: true },
    xAxis: { type: "value", name: data.variable },
    yAxis: { type: logScale ? "log" : "value", name: "Density" },
    dataZoom: [{ type: "inside" }],
    series: [{ type: "line", showSymbol: false, areaStyle: { opacity: 0.16 }, data: data.density.map((row) => [row.value, row.density]), lineStyle: { color: "#0e7490", width: 2 }, itemStyle: { color: "#0e7490" } }],
  };
}

function ecdfOption(data: DistributionData, logScale = false): EChartsOption {
  return {
    animationDuration: 220,
    grid: { left: 48, right: 16, top: 10, bottom: 42, containLabel: true },
    tooltip: { trigger: "axis", confine: true },
    xAxis: { type: logScale ? "log" : "value", name: data.variable },
    yAxis: { type: "value", min: 0, max: 100, name: "Cumulative (%)" },
    dataZoom: [{ type: "inside" }],
    series: [{ type: "line", showSymbol: false, step: "end", data: data.ecdf.map((row) => [row.value, row.cumulativePercent]), lineStyle: { color: "#0e7490", width: 2 } }],
  };
}

function targetBoxOption(data: DistributionData, logScale = false): EChartsOption {
  const strata = TARGET_ORDER.map((outcome) => data.stratified.find((row) => row.stratum === outcome)).filter((row): row is DistributionData["stratified"][number] => Boolean(row));
  return {
    animationDuration: 220,
    grid: { left: 116, right: 18, top: 10, bottom: 36, containLabel: true },
    tooltip: {
      trigger: "item",
      confine: true,
      formatter: (rawParams) => {
        const params = (Array.isArray(rawParams) ? rawParams[0] : rawParams) as { name?: string; data?: { value?: number[]; sampleCount?: number; missingCount?: number } };
        const values = params.data?.value ?? [];
        return `<b>${params.name ?? "Outcome"}</b><br/>n=${(params.data?.sampleCount ?? 0).toLocaleString()} · missing=${(params.data?.missingCount ?? 0).toLocaleString()}<br/>min ${formatNumber(values[0])} · Q1 ${formatNumber(values[1])}<br/>median ${formatNumber(values[2])} · Q3 ${formatNumber(values[3])}<br/>max ${formatNumber(values[4])}`;
      },
    },
    xAxis: { type: logScale ? "log" : "value", name: data.variable },
    yAxis: { type: "category", data: strata.map((row) => `${row.stratum}${row.observedCount === 0 ? " (n=0)" : row.observedCount < 1_000 ? " †" : ""}`), axisLabel: { fontSize: 9 } },
    series: [{
      name: "Development-only outcome strata",
      type: "boxplot",
      data: strata.map((row) => ({
        name: row.stratum,
        sampleCount: row.observedCount,
        missingCount: row.missingCount,
        // ECharts skips NaN coordinates, so a governed zero-count class remains named on the
        // axis without fabricating a zero-valued box summary.
        value: [row.min, row.q1, row.median, row.q3, row.max].map((value) => value ?? Number.NaN),
        itemStyle: { opacity: row.observedCount ? 0.9 : 0.25 },
      })),
    }],
  };
}

function targetViolinOption(data: DistributionData, logScale = false): EChartsOption {
  const strata = TARGET_ORDER.map((outcome) => data.stratified.find((row) => row.stratum === outcome)).filter((row): row is DistributionData["stratified"][number] => Boolean(row));
  const colors = ["#0891b2", "#2563eb", "#7c3aed", "#db2777", "#ea580c", "#ca8a04", "#059669", "#475569"];
  const extent = strata.flatMap((row) => (row.density ?? []).map((point) => point.value)).filter((value) => Number.isFinite(value) && (!logScale || value > 0));
  const minimum = extent.length ? Math.min(...extent) : 0;
  const maximum = extent.length ? Math.max(...extent) : 1;
  const series = strata.map((row, index) => {
    const density = (row.density ?? []).filter((point) => Number.isFinite(point.value) && Number.isFinite(point.density) && (!logScale || point.value > 0));
    const peak = density.length ? Math.max(...density.map((point) => point.density)) : 0;
    const renderItem: CustomSeriesRenderItem = (_params, api) => {
      if (!density.length || !peak) return null;
      const upper = density.map((point) => api.coord([point.value, index - (point.density / peak) * 0.34]));
      const lower = [...density].reverse().map((point) => api.coord([point.value, index + (point.density / peak) * 0.34]));
      return { type: "polygon", shape: { points: [...upper, ...lower] }, style: api.style({ fill: colors[index], stroke: colors[index], opacity: 0.62 }) };
    };
    return { name: row.stratum, type: "custom" as const, coordinateSystem: "cartesian2d" as const, renderItem, data: [[row.median ?? minimum, index]] };
  });
  return {
    animationDuration: 220,
    grid: { left: 116, right: 18, top: 10, bottom: 36, containLabel: true },
    tooltip: {
      trigger: "item",
      confine: true,
      formatter: (rawParams) => {
        const params = (Array.isArray(rawParams) ? rawParams[0] : rawParams) as { seriesName?: string };
        const row = strata.find((item) => item.stratum === params.seriesName);
        return `<b>${row?.stratum ?? "Outcome"}</b><br/>n=${(row?.observedCount ?? 0).toLocaleString()} · missing=${(row?.missingCount ?? 0).toLocaleString()}<br/>Q1 ${formatNumber(row?.q1)} · median ${formatNumber(row?.median)} · Q3 ${formatNumber(row?.q3)}`;
      },
    },
    xAxis: { type: logScale ? "log" : "value", name: data.variable, min: minimum, max: maximum },
    yAxis: { type: "value", min: -0.5, max: Math.max(0.5, strata.length - 0.5), interval: 1, axisLabel: { fontSize: 9, formatter: (value: number) => { const row = strata[Math.round(value)]; return row ? `${row.stratum}${row.observedCount === 0 ? " (n=0)" : row.observedCount < 1_000 ? " †" : ""}` : ""; } }, splitLine: { show: false } },
    series,
  };
}

function associationScore(data: DistributionData): number {
  const means = data.stratified.map((row) => row.mean).filter((value): value is number => value !== null && Number.isFinite(value));
  const spread = means.length > 1 ? Math.max(...means) - Math.min(...means) : 0;
  const scale = Number(data.statistics.std ?? 0);
  return scale > 0 ? Math.abs(spread / scale) : Math.abs(spread);
}

function useNearViewport(): { ref: RefObject<HTMLElement>; near: boolean } {
  const ref = useRef<HTMLElement>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || near) return undefined;
    if (typeof IntersectionObserver === "undefined") {
      setNear(true);
      return undefined;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setNear(true);
        observer.disconnect();
      }
    }, { rootMargin: "700px 0px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, [near]);
  return { ref, near };
}

function Skeleton({ variable }: { variable: ProjectEdaVariable }) {
  return <div className="space-y-3" role="status" aria-label={`${variable.name} profile deferred`}><div className="h-40 animate-pulse rounded-xl bg-slate-100" /><div className="h-40 animate-pulse rounded-xl bg-slate-100" /><p className="text-center text-[10px] text-slate-500">Windowed profile: aggregate query begins near the viewport.</p></div>;
}

function CardCharts({ data, variable, taxonomy, detail = false, summaryMode = "histogram", targetMode = "box", logScale = false }: { data: DistributionData | CategoryCountsData; variable: ProjectEdaVariable; taxonomy: string[]; detail?: boolean; summaryMode?: "histogram" | "density" | "ecdf"; targetMode?: "box" | "violin"; logScale?: boolean }) {
  const kind = classifyGalleryVariable(variable);
  const height = detail ? 340 : 205;
  if ("categories" in data) {
    return <div className={`grid gap-3 ${detail ? "xl:grid-cols-2" : "2xl:grid-cols-2"}`}><EChartsPanel option={frequencyOption(data)} height={height} ariaLabel={`${variable.name} category frequency`} /><EChartsPanel option={targetCompositionOption(data, taxonomy)} height={height} ariaLabel={`${variable.name} target composition by level`} /></div>;
  }
  const summary = summaryMode === "density" ? densityOption(data, logScale) : summaryMode === "ecdf" ? ecdfOption(data, logScale) : histogramOption(data, logScale);
  const target = targetMode === "violin" ? targetViolinOption(data, logScale) : targetBoxOption(data, logScale);
  return <div className={`grid gap-3 ${detail ? "xl:grid-cols-2" : "2xl:grid-cols-2"}`}><EChartsPanel option={summary} height={height} ariaLabel={`${variable.name} development ${summaryMode}`} /><div><EChartsPanel option={target} height={height} ariaLabel={`${variable.name} horizontal target stratified ${targetMode} plot`} /><p className="mt-1 text-[9px] text-slate-500">† Rare stratum: fewer than 1,000 observed development rows. All eight governed outcomes remain explicit.</p></div>{kind === "continuous" && detail ? <div className="xl:col-span-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">The summary view supports histogram, bounded density, ECDF, and log scaling. Target strata switch between exact box summaries and bounded per-class density violins; no raw development rows enter the browser.</div> : null}</div>;
}

function ProfileFacts({ variable, data }: { variable: ProjectEdaVariable; data: DistributionData | CategoryCountsData }) {
  if ("categories" in data) {
    return <div className="grid grid-cols-3 gap-2 text-[10px]"><Fact label="Levels shown" value={String(displayedCategoryRows(data).length)} /><Fact label="Missing" value={data.missingCount.toLocaleString()} /><Fact label="Other" value={data.otherCount.toLocaleString()} /></div>;
  }
  return <div className="grid grid-cols-2 gap-2 text-[10px] sm:grid-cols-5"><Fact label="Observed" value={formatNumber(data.statistics.count, 0)} /><Fact label="Missing count" value={formatNumber(data.statistics.missingCount, 0)} /><Fact label="Missing" value={`${formatNumber(data.statistics.missingPercent, 1)}%`} /><Fact label="Min / max" value={`${formatNumber(data.statistics.min)} / ${formatNumber(data.statistics.max)}`} /><Fact label="Mean" value={formatNumber(data.statistics.mean)} /><Fact label="Median" value={formatNumber(data.statistics.median)} /><Fact label="Q1 / Q3" value={`${formatNumber(data.statistics.q25)} / ${formatNumber(data.statistics.q75)}`} /><Fact label="P05 / P95" value={`${formatNumber(data.statistics.q05)} / ${formatNumber(data.statistics.q95)}`} /><Fact label="P01 / P99" value={`${formatNumber(data.statistics.q01)} / ${formatNumber(data.statistics.q99)}`} /><Fact label="Std. dev." value={formatNumber(data.statistics.std)} /></div>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5"><div className="font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-0.5 truncate font-mono text-slate-900" title={value}>{value}</div></div>;
}

function ProfileCard({ projectId, authorityKey, variable, filters, taxonomy, bookmarked, toggleBookmark, handoff, reportAssociation }: { projectId: string; authorityKey: string; variable: ProjectEdaVariable; filters: ProjectEdaFilters; taxonomy: string[]; bookmarked: boolean; toggleBookmark: (name: string) => void; handoff: (name: string, destination: GalleryHandoff) => void; reportAssociation: (name: string, score: number) => void }) {
  const { ref, near } = useNearViewport();
  const [detail, setDetail] = useState(false);
  const [detailSummaryMode, setDetailSummaryMode] = useState<"histogram" | "density" | "ecdf">("histogram");
  const [detailTargetMode, setDetailTargetMode] = useState<"box" | "violin">("box");
  const [detailLogScale, setDetailLogScale] = useState(false);
  const [categoryTopN, setCategoryTopN] = useState(12);
  const detailTrigger = useRef<HTMLButtonElement>(null);
  const kind = classifyGalleryVariable(variable);
  const categorical = kind !== "continuous";
  const request = useMemo(() => near && variable.selectable ? {
    queryType: categorical ? "category_counts" as const : "distribution" as const,
    variables: [variable.name],
    filters,
    settings: categorical ? { topN: categoryTopN } : { bins: 24, stratifyBy: "outcome" },
  } : null, [categorical, categoryTopN, filters, near, variable.name, variable.selectable]);
  const result = useProjectEdaQuery<DistributionData | CategoryCountsData>(projectId, authorityKey, request);
  const numericResult = result.value && !("categories" in result.value.data) ? result.value.data : null;
  const logScaleEligible = Number(numericResult?.statistics.min ?? 0) > 0;
  useEffect(() => {
    if (result.value && !("categories" in result.value.data)) reportAssociation(variable.name, associationScore(result.value.data));
  }, [reportAssociation, result.value, variable.name]);
  const linked = variable.name.replace(/(_missing|_insufficient|_indicator)$/i, "");
  const reason = /insufficient/i.test(variable.name) ? "INSUFFICIENT_HISTORY" : /missing/i.test(variable.name) ? "SOURCE_MISSING / NO_PRIOR_HISTORY" : "EXPLICIT_STATE";

  return <article ref={ref as RefObject<HTMLElement>} data-testid={`stage3-gallery-card-${variable.name}`} data-gallery-kind={kind} data-windowed-query={near ? "active" : "deferred"} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" style={{ contentVisibility: "auto", containIntrinsicSize: "720px" }}>
    <div className="flex min-w-0 items-start gap-3"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-1.5"><h4 className="break-all font-mono text-sm font-semibold text-slate-950">{variable.name}</h4><span className="rounded-full bg-cyan-50 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-cyan-800">{kind.replace("-", " ")}</span><span className="rounded-full bg-slate-100 px-2 py-0.5 text-[9px] font-semibold text-slate-600">{variable.core ? "CORE" : "CONTEXT"}</span>{!variable.selectable ? <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[9px] font-semibold text-amber-800">METADATA ONLY</span> : null}</div><p className="mt-1 text-xs leading-5 text-slate-600">{variable.definition}</p></div><button type="button" aria-label={`${bookmarked ? "Remove" : "Add"} bookmark for ${variable.name}`} aria-pressed={bookmarked} onClick={() => toggleBookmark(variable.name)} className={`rounded-lg border p-2 ${bookmarked ? "border-amber-300 bg-amber-50 text-amber-700" : "border-slate-200 text-slate-500"}`}>{bookmarked ? <BookmarkCheck size={15} /> : <Bookmark size={15} />}</button>{variable.selectable ? <button ref={detailTrigger} type="button" onClick={() => setDetail(true)} className="rounded-lg border border-slate-200 p-2 text-slate-600" aria-label={`Open detailed distribution for ${variable.name}`}><Maximize2 size={15} /></button> : null}</div>
    {kind === "categorical" && variable.selectable ? <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[10px] text-slate-600"><label className="font-semibold text-slate-700">Top-N levels<select aria-label={`Top N levels for ${variable.name}`} value={categoryTopN} onChange={(event) => setCategoryTopN(Number(event.target.value))} className="ml-2 rounded border border-slate-300 bg-white px-2 py-1 font-normal"><option value={5}>5</option><option value={10}>10</option><option value={12}>12</option><option value={20}>20</option></select></label><span>Missing stays explicit; remaining governed levels are grouped as Other with their own target composition.</span></div> : null}
    <div className="mt-3">{!variable.selectable ? <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-900"><b>Governance metadata inspection only.</b> This field is not a model candidate, so no distribution or target query is issued.</div> : !near ? <Skeleton variable={variable} /> : result.status === "loading" || result.status === "idle" ? <div className="flex min-h-[420px] items-center justify-center rounded-xl border border-slate-200 bg-slate-50 text-xs text-slate-600" role="status"><Loader2 size={15} className="mr-2 animate-spin" />Loading bounded aggregate profile…</div> : result.status === "error" || !result.value ? <div className="flex min-h-[240px] flex-col items-center justify-center rounded-xl border border-rose-200 bg-rose-50 p-5 text-center text-xs text-rose-800" role="alert"><AlertTriangle size={18} /><p className="mt-2">{result.error || "Profile unavailable."}</p><button type="button" onClick={result.retry} className="mt-3 inline-flex items-center gap-1 rounded-lg bg-rose-900 px-3 py-2 font-semibold text-white"><RefreshCw size={12} />Retry</button></div> : <><ProfileFacts variable={variable} data={result.value.data} /><div className="mt-3"><CardCharts data={result.value.data} variable={variable} taxonomy={taxonomy} /></div></>}</div>
    {kind === "missingness-indicator" ? <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-2 text-[10px] leading-4 text-amber-900"><b>Linked field:</b> {linked || "governed history source"} · <b>Reason:</b> {reason}. The complete indicator column does not imply the underlying feature is complete.</div> : null}
    <dl className="mt-3 grid gap-2 border-t border-slate-100 pt-3 text-[10px] sm:grid-cols-3"><div><dt className="font-semibold uppercase text-slate-500">Feature family</dt><dd className="mt-0.5 break-words text-slate-800">{variable.featureFamily}</dd></div><div><dt className="font-semibold uppercase text-slate-500">Source lineage</dt><dd className="mt-0.5 break-all text-slate-800">{variable.sourceLineage}</dd></div><div><dt className="font-semibold uppercase text-slate-500">Point in time</dt><dd className="mt-0.5 text-slate-800">{variable.pointInTimeTreatment}</dd></div></dl>
    {variable.selectable ? <div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => setDetail(true)} className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-2.5 py-1.5 text-[10px] font-semibold text-white"><ExternalLink size={11} />Open detailed distribution</button><button type="button" onClick={() => handoff(variable.name, "outliers")} className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-[10px] font-semibold text-slate-700">Open in Outliers</button><button type="button" onClick={() => handoff(variable.name, "missing")} className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-[10px] font-semibold text-slate-700">Open in Missing Values</button><button type="button" onClick={() => handoff(variable.name, "features")} className="rounded-lg border border-cyan-200 bg-cyan-50 px-2.5 py-1.5 text-[10px] font-semibold text-cyan-800">Bookmark for Feature Engineering</button></div> : null}
    <CockpitDrawer open={detail} onClose={() => setDetail(false)} returnFocusRef={detailTrigger} title={variable.name} eyebrow="Full-width development profile" description="Bounded aggregate evidence only. Final-OOT targets remain locked." widthClassName="max-w-none" testId="stage3-gallery-detail"><div className="space-y-4 p-4 sm:p-6">{result.value ? <><ProfileFacts variable={variable} data={result.value.data} />{!categorical ? <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3"><label className="text-xs font-semibold text-slate-700">Summary chart<select aria-label="Detailed continuous summary chart" value={detailSummaryMode} onChange={(event) => setDetailSummaryMode(event.target.value as "histogram" | "density" | "ecdf")} className="ml-2 rounded-lg border border-slate-300 bg-white px-2 py-1.5 font-normal"><option value="histogram">Histogram</option><option value="density">Density</option><option value="ecdf">ECDF</option></select></label><label className="text-xs font-semibold text-slate-700">Target shape<select aria-label="Target stratified shape" value={detailTargetMode} onChange={(event) => setDetailTargetMode(event.target.value as "box" | "violin")} className="ml-2 rounded-lg border border-slate-300 bg-white px-2 py-1.5 font-normal"><option value="box">Box</option><option value="violin">Violin</option></select></label><label title={logScaleEligible ? "Use logarithmic axes" : "Log axes require strictly positive observed values"} className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-700"><input type="checkbox" disabled={!logScaleEligible} checked={detailLogScale && logScaleEligible} onChange={(event) => setDetailLogScale(event.target.checked)} />Log scale</label><span className="ml-auto text-[10px] text-slate-500">Presentation only · governed population unchanged</span></div> : null}<CardCharts data={result.value.data} variable={variable} taxonomy={taxonomy} detail summaryMode={detailSummaryMode} targetMode={detailTargetMode} logScale={detailLogScale && logScaleEligible} /></> : <Skeleton variable={variable} />}</div></CockpitDrawer>
  </article>;
}

function GalleryCustomizationDrawer({ open, close, returnFocusRef, variables, hidden, setHidden }: { open: boolean; close: () => void; returnFocusRef: RefObject<HTMLElement>; variables: ProjectEdaVariable[]; hidden: Set<string>; setHidden: (next: Set<string>) => void }) {
  const [search, setSearch] = useState("");
  const visible = variables.filter((variable) => !search || `${variable.name} ${variable.featureFamily}`.toLowerCase().includes(search.toLowerCase()));
  return <CockpitDrawer open={open} onClose={close} returnFocusRef={returnFocusRef} title="Customize gallery" eyebrow="Secondary gallery control" description="Choose which governed variables remain visible. This changes presentation only; it does not select model features." widthClassName="max-w-2xl" testId="stage3-gallery-customize" footer={<div className="flex w-full items-center justify-between"><button type="button" onClick={() => setHidden(new Set())} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700">Restore all eligible</button><button type="button" onClick={close} className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white">Done</button></div>}><div className="p-4 sm:p-5"><label className="text-xs font-semibold text-slate-700">Search governed variables<input value={search} onChange={(event) => setSearch(event.target.value)} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" /></label><div className="mt-4 space-y-2">{visible.map((variable) => <label key={variable.name} className="flex items-start gap-2 rounded-lg border border-slate-200 p-3 text-xs"><input type="checkbox" checked={!hidden.has(variable.name)} onChange={(event) => { const next = new Set(hidden); if (event.target.checked) next.delete(variable.name); else next.add(variable.name); setHidden(next); }} /><span><b className="font-mono text-slate-900">{variable.name}</b><br /><span className="text-slate-500">{variable.featureFamily} · {classifyGalleryVariable(variable)} · {variable.selectable ? "model-selectable" : "metadata only"}</span></span></label>)}</div></div></CockpitDrawer>;
}

export function Stage3DistributionGallery({ projectId, authorityKey, variables, families, filters, taxonomy, bookmarks, toggleBookmark, handoff }: { projectId: string; authorityKey: string; variables: ProjectEdaVariable[]; families: ProjectEdaFamily[]; filters: ProjectEdaFilters; taxonomy: string[]; bookmarks: string[]; toggleBookmark: (name: string) => void; handoff: (name: string, destination: GalleryHandoff) => void }) {
  const [search, setSearch] = useState("");
  const [family, setFamily] = useState("");
  const [kind, setKind] = useState<GalleryVariableKind | "">("");
  const [tier, setTier] = useState<"" | "core" | "context">("");
  const [availability, setAvailability] = useState<"active" | "all">("active");
  const [missingThreshold, setMissingThreshold] = useState(100);
  const [bookmarksOnly, setBookmarksOnly] = useState(false);
  const [sort, setSort] = useState<GallerySort>("family");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [customizeOpen, setCustomizeOpen] = useState(false);
  const customizeTrigger = useRef<HTMLButtonElement>(null);
  const [associationScores, setAssociationScores] = useState<Record<string, number>>({});
  const reportAssociation = useCallback((name: string, score: number) => setAssociationScores((current) => current[name] === score ? current : { ...current, [name]: score }), []);
  const declaredFamilies = useMemo(() => [...new Set([...families.map((item) => item.name), ...variables.map((variable) => variable.featureFamily)])].sort((a, b) => familyRank(a) - familyRank(b) || a.localeCompare(b)), [families, variables]);
  const candidates = useMemo(() => variables.filter((variable) =>
    !hidden.has(variable.name)
    && (availability === "all" || variable.selectable)
    && (!search || `${variable.name} ${variable.label} ${variable.definition} ${variable.featureFamily}`.toLowerCase().includes(search.toLowerCase()))
    && (!family || variable.featureFamily === family)
    && (!kind || classifyGalleryVariable(variable) === kind)
    && (!tier || (tier === "core" ? variable.core : !variable.core))
    && variable.missingPercent <= missingThreshold
    && (!bookmarksOnly || bookmarks.includes(variable.name)),
  ).sort((a, b) => {
    if (sort === "name") return a.name.localeCompare(b.name);
    if (sort === "missingness") return b.missingPercent - a.missingPercent || a.name.localeCompare(b.name);
    if (sort === "cardinality") return (b.uniqueCount ?? -1) - (a.uniqueCount ?? -1) || a.name.localeCompare(b.name);
    if (sort === "association") return (associationScores[b.name] ?? -1) - (associationScores[a.name] ?? -1) || a.name.localeCompare(b.name);
    return familyRank(a.featureFamily) - familyRank(b.featureFamily) || a.featureFamily.localeCompare(b.featureFamily) || a.name.localeCompare(b.name);
  }), [associationScores, availability, bookmarks, bookmarksOnly, family, hidden, kind, missingThreshold, search, sort, tier, variables]);
  const grouped = useMemo(() => declaredFamilies.map((name) => {
    const familyVariables = candidates.filter((variable) => variable.featureFamily === name);
    return { name, variables: sort === "family" ? interleaveKinds(familyVariables) : familyVariables };
  }).filter((group) => group.variables.length), [candidates, declaredFamilies, sort]);
  const kindCounts = useMemo(() => candidates.reduce<Record<GalleryVariableKind, number>>((counts, variable) => ({ ...counts, [classifyGalleryVariable(variable)]: counts[classifyGalleryVariable(variable)] + 1 }), { continuous: 0, "low-cardinality": 0, binary: 0, categorical: 0, "missingness-indicator": 0 }), [candidates]);

  return <section className="space-y-4" data-testid="stage3-distribution-gallery" data-gallery-windowing="intersection-observer-plus-css-content-visibility" aria-label="All-variable analytical distribution gallery">
    <section className="rounded-2xl border border-cyan-200 bg-gradient-to-br from-cyan-50 to-white p-4 shadow-sm"><div className="flex flex-wrap items-start gap-3"><div><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Boxes size={17} className="text-cyan-700" />All-variable development profile</div><p className="mt-1 max-w-3xl text-xs leading-5 text-slate-600">Every eligible project-bound predictor is accessible here. Cards use native render windowing and issue one bounded, cached aggregate request only when they approach the viewport. No raw PA rows or final-OOT targets are returned.</p></div><button ref={customizeTrigger} type="button" onClick={() => setCustomizeOpen(true)} className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-cyan-300 bg-white px-3 py-2 text-xs font-semibold text-cyan-900"><Settings2 size={14} />Customize gallery</button></div><div className="mt-3 flex flex-wrap gap-2 text-[10px]">{Object.entries(kindCounts).map(([label, count]) => <span key={label} className="rounded-full border border-slate-200 bg-white px-2 py-1 font-semibold text-slate-700">{label.replace("-", " ")} · {count}</span>)}</div></section>
    <section className="stage3-flow-controls relative z-10 rounded-2xl border border-slate-200 bg-white/95 p-3 shadow-md backdrop-blur" data-testid="stage3-gallery-local-controls"><div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4"><label className="relative xl:col-span-2"><span className="sr-only">Search variables</span><Search size={14} className="absolute left-3 top-2.5 text-slate-400" /><input aria-label="Search variables" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search variables, definitions, or lineage" className="w-full rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-xs" /></label><select aria-label="Show feature family" value={family} onChange={(event) => setFamily(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs"><option value="">All feature families</option>{declaredFamilies.map((name) => <option key={name}>{name}</option>)}</select><select aria-label="Show data type" value={kind} onChange={(event) => setKind(event.target.value as GalleryVariableKind | "")} className="rounded-lg border border-slate-300 px-3 py-2 text-xs"><option value="">All governed data types</option><option value="continuous">Continuous numeric</option><option value="low-cardinality">Low-cardinality numeric</option><option value="binary">Binary</option><option value="categorical">Categorical</option><option value="missingness-indicator">Missingness indicator</option></select><select aria-label="Core or contextual" value={tier} onChange={(event) => setTier(event.target.value as "" | "core" | "context")} className="rounded-lg border border-slate-300 px-3 py-2 text-xs"><option value="">Core + contextual</option><option value="core">Core Gold-48</option><option value="context">Contextual candidates</option></select><select aria-label="Selectable or active" value={availability} onChange={(event) => setAvailability(event.target.value as "active" | "all")} className="rounded-lg border border-slate-300 px-3 py-2 text-xs"><option value="active">Model-selectable active only</option><option value="all">Inspect excluded metadata</option></select><label className="flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-[10px] font-semibold text-slate-600">Max missing %<input aria-label="Missingness threshold" type="number" min={0} max={100} value={missingThreshold} onChange={(event) => setMissingThreshold(Math.max(0, Math.min(100, Number(event.target.value))))} className="w-16 rounded border border-slate-200 px-1 py-0.5" /></label><select aria-label="Sort gallery" value={sort} onChange={(event) => setSort(event.target.value as GallerySort)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs"><option value="family">Sort: feature-family order</option><option value="name">Sort: variable name</option><option value="missingness">Sort: missingness</option><option value="cardinality">Sort: cardinality</option><option value="association">Sort: absolute descriptive target association (loaded)</option></select></div><div className="mt-2 flex flex-wrap items-center gap-2"><label className="inline-flex items-center gap-1.5 text-xs text-slate-700"><input type="checkbox" checked={bookmarksOnly} onChange={(event) => setBookmarksOnly(event.target.checked)} />Show only bookmarked</label><span className="ml-auto text-[10px] text-slate-500"><b>{candidates.length}</b> visible of {variables.filter((variable) => variable.selectable).length} eligible · filters cancel unneeded card requests</span></div></section>
    {grouped.map((group) => { const closed = collapsed.has(group.name); return <section key={group.name} className="rounded-2xl border border-slate-200 bg-slate-50/60 p-3" data-gallery-family={group.name}><button type="button" aria-expanded={!closed} onClick={() => setCollapsed((current) => { const next = new Set(current); if (next.has(group.name)) next.delete(group.name); else next.add(group.name); return next; })} className="flex w-full items-center gap-2 rounded-xl bg-white px-3 py-3 text-left shadow-sm">{closed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}<BarChart3 size={16} className="text-cyan-700" /><span className="font-semibold text-slate-950">{group.name}</span><span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">{group.variables.length} profiles</span><span className="ml-auto text-[10px] text-slate-500">{closed ? "Expand family" : "Collapse family"}</span></button>{!closed ? <div className="mt-3 grid items-start gap-4 2xl:grid-cols-2">{group.variables.map((variable) => <ProfileCard key={variable.name} projectId={projectId} authorityKey={authorityKey} variable={variable} filters={filters} taxonomy={taxonomy} bookmarked={bookmarks.includes(variable.name)} toggleBookmark={toggleBookmark} handoff={handoff} reportAssociation={reportAssociation} />)}</div> : null}</section>; })}
    {!grouped.length ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center"><Filter size={22} className="mx-auto text-slate-400" /><p className="mt-2 text-sm font-semibold text-slate-800">No profile cards match the current gallery controls.</p></div> : null}
    <GalleryCustomizationDrawer open={customizeOpen} close={() => setCustomizeOpen(false)} returnFocusRef={customizeTrigger} variables={availability === "all" ? variables : variables.filter((variable) => variable.selectable)} hidden={hidden} setHidden={setHidden} />
  </section>;
}

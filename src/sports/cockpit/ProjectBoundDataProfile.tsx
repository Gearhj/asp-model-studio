import { useCallback, useEffect, useMemo, useState } from "react";
import type { EChartsOption, ECharts } from "echarts";
import {
  AlertTriangle,
  BarChart3,
  Bookmark,
  BookmarkCheck,
  Box,
  CalendarRange,
  ChevronDown,
  CircleOff,
  Database,
  Download,
  Filter,
  GitCompareArrows,
  ImageDown,
  LineChart,
  Loader2,
  Lock,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  SlidersHorizontal,
  Snowflake,
  Sparkles,
  Star,
  TableProperties,
  Trash2,
  Users,
  Wand2,
  X,
} from "lucide-react";
import EChartsPanel, { exportChartAsPng } from "../../visual-intelligence/EChartsPanel";
import { useCockpitStore } from "./cockpitApi";
import type { CurrentGoldReviewState } from "../workflow/currentGoldDataReview";
import {
  compactProjectEdaFilters,
  downloadAggregatedCsv,
  useProjectEdaMetadata,
  useProjectEdaQuery,
  type AssociationData,
  type CategoryCountsData,
  type ColdStartData,
  type DistributionData,
  type MissingnessData,
  type OutliersData,
  type OverviewData,
  type PairwiseData,
  type ProjectEdaEnvelope,
  type ProjectEdaFilters,
  type ProjectEdaFamily,
  type ProjectEdaQuery,
  type ProjectEdaVariable,
  type TemporalData,
} from "./projectEdaApi";

type TabId = "overview" | "distributions" | "relationships" | "target" | "missingness" | "time" | "players" | "saved";
type RelationshipMode = "association" | "scatter" | "pairwise";
type DistributionMode = "histogram" | "density" | "ecdf" | "box" | "violin";
type MissingnessMode = "missingness" | "outliers";
type StratifyBy = "" | "outcome" | "season" | "month";
type AssociationMethod = "auto" | "pearson" | "spearman";

type EdaView = {
  id: string;
  authorityKey: string;
  name: string;
  tab: TabId;
  selectedVariables: string[];
  filters: ProjectEdaFilters;
  settings: {
    distributionMode: DistributionMode;
    relationshipMode: RelationshipMode;
    missingnessMode: MissingnessMode;
    bins: number;
    topN: number;
    logScale: boolean;
    stratifyBy: StratifyBy;
    associationMethod: AssociationMethod;
    samplingSeed: number;
  };
  notes: string;
  savedAt: string;
};

type VariableBookmarks = { authorityKey: string; names: string[] };

const TABS: { id: TabId; label: string; icon: typeof BarChart3 }[] = [
  { id: "overview", label: "Overview", icon: Sparkles },
  { id: "distributions", label: "Distributions", icon: BarChart3 },
  { id: "relationships", label: "Relationships", icon: GitCompareArrows },
  { id: "target", label: "Target & Class Balance", icon: TableProperties },
  { id: "missingness", label: "Missingness & Outliers", icon: CircleOff },
  { id: "time", label: "Time & Stability", icon: CalendarRange },
  { id: "players", label: "Players & Cold Start", icon: Users },
  { id: "saved", label: "Saved Views", icon: Bookmark },
];

const TARGET_ORDER = ["STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE", "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH"];
const DEFAULT_SEED = 7_310_2026;
const BOOKMARKS_KEY = "stage3.eda.variableBookmarks";
const SAVED_VIEWS_KEY = "stage3.eda.savedViews";

const palette = ["#0891b2", "#2563eb", "#7c3aed", "#db2777", "#ea580c", "#ca8a04", "#059669", "#475569"];

function int(value: number | null | undefined) {
  return Number(value ?? 0).toLocaleString();
}

function pct(value: number | null | undefined) {
  return `${Number(value ?? 0).toFixed(1)}%`;
}

function parseStored<T>(raw: string | undefined, fallback: T): T {
  if (!raw) return fallback;
  try { return JSON.parse(raw) as T; } catch { return fallback; }
}

function rowsFrom(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.map((row) => row && typeof row === "object" ? row as Record<string, unknown> : { value: row });
}

function chartBase(): EChartsOption {
  return {
    animationDuration: 280,
    color: palette,
    grid: { left: 50, right: 22, top: 34, bottom: 52, containLabel: true },
    tooltip: { trigger: "axis", confine: true },
    toolbox: { right: 4, feature: { dataZoom: {}, restore: {} } },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 17, bottom: 5 }],
  };
}

function barOption(labels: string[], values: number[], name: string, horizontal = false): EChartsOption {
  return {
    ...chartBase(),
    xAxis: horizontal ? { type: "value", name } : { type: "category", data: labels, axisLabel: { rotate: labels.length > 8 ? 35 : 0 } },
    yAxis: horizontal ? { type: "category", data: labels, axisLabel: { width: 150, overflow: "truncate" } } : { type: "value", name },
    series: [{ name, type: "bar", data: values, itemStyle: { borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0] } }],
  };
}

function lineOption(labels: string[], series: { name: string; values: (number | null)[] }[], yName: string): EChartsOption {
  return {
    ...chartBase(),
    legend: { top: 0 },
    xAxis: { type: "category", data: labels, boundaryGap: false },
    yAxis: { type: "value", name: yName },
    series: series.map((item) => ({ name: item.name, type: "line", data: item.values, showSymbol: labels.length < 20, smooth: 0.18, connectNulls: false })),
  };
}

function QueryStatus({ status, error }: { status: string; error: string | null }) {
  if (status === "loading" || status === "idle") return <div className="flex min-h-[260px] items-center justify-center rounded-xl border border-slate-200 bg-white text-sm text-slate-500"><Loader2 size={17} className="mr-2 animate-spin text-cyan-600" />Computing a bounded development-only analytical view…</div>;
  if (status === "error") return <div className="flex min-h-[220px] items-center justify-center rounded-xl border border-rose-200 bg-rose-50 p-6 text-center text-sm text-rose-800"><AlertTriangle size={18} className="mr-2" />{error || "The analytical query failed."}</div>;
  return null;
}

function Metric({ label, value, detail, accent = "slate" }: { label: string; value: string; detail: string; accent?: "slate" | "cyan" | "emerald" | "amber" }) {
  const tones = { slate: "border-slate-200", cyan: "border-cyan-200 bg-cyan-50/40", emerald: "border-emerald-200 bg-emerald-50/40", amber: "border-amber-200 bg-amber-50/50" };
  return <div className={`rounded-xl border bg-white p-3 ${tones[accent]}`}><div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</div><div className="mt-1 text-xl font-semibold tabular-nums text-slate-950">{value}</div><div className="mt-1 text-[11px] leading-4 text-slate-500">{detail}</div></div>;
}

function EvidenceStrip({ envelope }: { envelope: ProjectEdaEnvelope<unknown> }) {
  const filters = Object.entries(envelope.population.filtersApplied ?? {}).filter(([, value]) => value !== "" && value !== undefined && !(Array.isArray(value) && value.length === 0));
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[10px] text-slate-600" data-testid="stage3-eda-chart-evidence">
      <span className="rounded-full bg-slate-900 px-2 py-1 font-semibold text-white">DEVELOPMENT ONLY</span>
      <span><b>{int(envelope.population.rowsRepresented)}</b> rows represented</span>
      <span>• {envelope.population.aggregation}</span>
      {envelope.population.sampling ? <span className="rounded-full border border-cyan-200 bg-cyan-50 px-2 py-1 font-semibold text-cyan-800">Sample {int(envelope.population.sampling.sampleSize)} / {int(envelope.population.sampling.populationSize)} · seed {envelope.population.sampling.seed} · {envelope.population.sampling.method}</span> : <span>• aggregated, no row sample</span>}
      <span className="ml-auto">Filters: {filters.length ? filters.map(([key, value]) => `${key}=${Array.isArray(value) ? value.join("|") : value && typeof value === "object" ? JSON.stringify(value) : String(value)}`).join(" · ") : "none"}</span>
    </div>
  );
}

function ChartCard({ title, description, option, ariaLabel, envelope, exportRows = [] }: { title: string; description: string; option: EChartsOption | null; ariaLabel: string; envelope: ProjectEdaEnvelope<unknown>; exportRows?: Record<string, unknown>[] }) {
  const [chart, setChart] = useState<ECharts | null>(null);
  const capture = useCallback((instance: ECharts) => setChart(instance), []);
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h4 className="font-semibold text-slate-950">{title}</h4><p className="mt-0.5 text-xs leading-5 text-slate-500">{description}</p></div>
        <div className="flex gap-1">
          <button type="button" title="Reset zoom and brush" onClick={() => { chart?.dispatchAction({ type: "dataZoom", start: 0, end: 100 }); chart?.dispatchAction({ type: "brush", command: "clear", areas: [] }); }} className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50"><RotateCcw size={14} /></button>
          <button type="button" title="Download chart image" disabled={!chart} onClick={() => chart && exportChartAsPng(chart, `${title.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}.png`)} className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50 disabled:opacity-40"><ImageDown size={14} /></button>
          <button type="button" title="Download aggregated chart data" disabled={!exportRows.length} onClick={() => downloadAggregatedCsv(`${title.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}.csv`, exportRows)} className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50 disabled:opacity-40"><Download size={14} /></button>
        </div>
      </div>
      <div className="mt-3"><EvidenceStrip envelope={envelope} /><EChartsPanel option={option} state={option ? "ready" : "empty"} height={310} ariaLabel={ariaLabel} onChartReady={capture} /></div>
    </section>
  );
}

function MultiSelect({ label, values, options, onChange }: { label: string; values: (string | number)[]; options: (string | number)[]; onChange: (next: (string | number)[]) => void }) {
  return (
    <details className="relative rounded-lg border border-slate-200 bg-white px-3 py-2">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-xs font-semibold text-slate-700">{label}<span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px]">{values.length || "All"}</span><ChevronDown size={13} /></summary>
      <div className="absolute left-0 z-30 mt-2 max-h-56 min-w-52 overflow-auto rounded-xl border border-slate-200 bg-white p-2 shadow-xl">
        {options.map((option) => {
          const on = values.map(String).includes(String(option));
          return <label key={String(option)} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-slate-50"><input type="checkbox" checked={on} onChange={() => onChange(on ? values.filter((value) => String(value) !== String(option)) : [...values, option])} />{String(option)}</label>;
        })}
      </div>
    </details>
  );
}

function GlobalFilters({ filters, setFilters, metadata }: { filters: ProjectEdaFilters; setFilters: (next: ProjectEdaFilters) => void; metadata: { seasons: number[]; months: number[]; outcomes: string[] } }) {
  const set = (key: keyof ProjectEdaFilters, value: unknown) => setFilters({ ...filters, [key]: value });
  const active = Object.keys(compactProjectEdaFilters(filters)).length;
  return (
    <details open className="sticky top-2 z-20 rounded-2xl border border-slate-200 bg-white/95 shadow-sm backdrop-blur" data-testid="stage3-eda-global-filters">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-semibold text-slate-900"><Filter size={15} className="text-cyan-700" /> Development-only filters <span className="rounded-full bg-cyan-50 px-2 py-0.5 text-[10px] text-cyan-800">{active} active</span><span className="ml-auto text-[11px] font-normal text-slate-500">Final OOT is never filterable</span><ChevronDown size={14} /></summary>
      <div className="grid gap-2 border-t border-slate-100 p-3 sm:grid-cols-2 xl:grid-cols-5">
        <MultiSelect label="Season" values={filters.seasons ?? []} options={metadata.seasons} onChange={(value) => set("seasons", value.map(Number))} />
        <label className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[10px] font-semibold uppercase text-slate-500">Start date<input type="date" value={filters.startDate ?? ""} max="2026-08-13" onChange={(event) => set("startDate", event.target.value)} className="mt-1 block w-full text-xs font-normal text-slate-800 outline-none" /></label>
        <label className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[10px] font-semibold uppercase text-slate-500">End date<input type="date" value={filters.endDate ?? ""} max="2026-08-13" onChange={(event) => set("endDate", event.target.value)} className="mt-1 block w-full text-xs font-normal text-slate-800 outline-none" /></label>
        <MultiSelect label="Month" values={filters.months ?? []} options={metadata.months} onChange={(value) => set("months", value.map(Number))} />
        <MultiSelect label="Day of week" values={filters.daysOfWeek ?? []} options={["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]} onChange={(value) => set("daysOfWeek", value.map(String))} />
        <MultiSelect label="Outcome class" values={filters.outcomes ?? []} options={metadata.outcomes} onChange={(value) => set("outcomes", value.map(String))} />
        <input aria-label="Batter filter" value={filters.batter ?? ""} onChange={(event) => set("batter", event.target.value)} placeholder="Batter canonical ID" className="rounded-lg border border-slate-200 px-3 py-2 text-xs" />
        <input aria-label="Pitcher filter" value={filters.pitcher ?? ""} onChange={(event) => set("pitcher", event.target.value)} placeholder="Pitcher canonical ID" className="rounded-lg border border-slate-200 px-3 py-2 text-xs" />
        <input aria-label="Batting team filter" value={filters.battingTeam ?? ""} onChange={(event) => set("battingTeam", event.target.value)} placeholder="Batting team" className="rounded-lg border border-slate-200 px-3 py-2 text-xs" />
        <input aria-label="Fielding team filter" value={filters.fieldingTeam ?? ""} onChange={(event) => set("fieldingTeam", event.target.value)} placeholder="Fielding team" className="rounded-lg border border-slate-200 px-3 py-2 text-xs" />
        <select aria-label="Home away context" value={filters.homeAway ?? ""} onChange={(event) => set("homeAway", event.target.value)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs"><option value="">Home / away: all</option><option value="HOME">Home</option><option value="AWAY">Away</option></select>
        <select aria-label="History status" value={filters.historyStatus ?? ""} onChange={(event) => set("historyStatus", event.target.value)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs"><option value="">History: all</option><option value="COLD_START">Cold start</option><option value="ESTABLISHED">Established</option><option value="INSUFFICIENT_HISTORY">Insufficient</option></select>
        <select aria-label="Missingness filter" value={filters.missingness ?? ""} onChange={(event) => set("missingness", event.target.value)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs"><option value="">Observed / missing: all</option><option value="MISSING">Missing</option><option value="OBSERVED">Observed</option></select>
        <select aria-label="Simulation state field" value={filters.simulationState?.field ?? ""} onChange={(event) => set("simulationState", event.target.value ? { field: event.target.value, value: 0 } : undefined)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs"><option value="">Simulation state: all</option><option value="context_inning">Inning</option><option value="context_top_bottom">Top / bottom</option><option value="context_outs_before">Outs before PA</option><option value="context_base_mask_before">Base mask before PA</option><option value="context_batting_score_diff_before">Batting score differential</option></select>
        {filters.simulationState ? <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs">State value<input aria-label="Simulation state value" type="number" value={filters.simulationState.value} onChange={(event) => set("simulationState", { ...filters.simulationState!, value: Number(event.target.value) })} className="w-full min-w-0 outline-none" /></label> : null}
        <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs">Min sample<input type="number" min={0} step={100} value={filters.minimumSampleSize ?? 0} onChange={(event) => set("minimumSampleSize", Number(event.target.value))} className="w-full min-w-0 outline-none" /></label>
      </div>
      <div className="mx-3 mb-3 flex flex-wrap items-center gap-2">{active ? <button type="button" onClick={() => setFilters({})} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"><X size={12} /> Clear all filters</button> : null}<span className="text-[10px] text-slate-500">Feature-family filtering is available in the variable explorer because it scopes variables, not population rows.</span></div>
    </details>
  );
}

function VariableExplorer({ variables, selected, setSelected, bookmarked, toggleBookmark }: { variables: ProjectEdaVariable[]; selected: string[]; setSelected: (next: string[]) => void; bookmarked: string[]; toggleBookmark: (name: string) => void }) {
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("");
  const [family, setFamily] = useState("");
  const [source, setSource] = useState("");
  const [dataType, setDataType] = useState("");
  const [category, setCategory] = useState("");
  const [missingness, setMissingness] = useState("");
  const [selectability, setSelectability] = useState("");
  const families = [...new Set(variables.map((variable) => variable.featureFamily))].sort();
  const roles = [...new Set(variables.map((variable) => variable.role))].sort();
  const dataTypes = [...new Set(variables.map((variable) => variable.dataType))].sort();
  const categories = [...new Set(variables.map((variable) => variable.category))].sort();
  const filtered = variables.filter((variable) =>
    (!search || `${variable.name} ${variable.label} ${variable.definition}`.toLowerCase().includes(search.toLowerCase())) &&
    (!role || variable.role === role) && (!family || variable.featureFamily === family) &&
    (!source || (source === "CORE" ? variable.core : !variable.core)) &&
    (!dataType || variable.dataType === dataType) && (!category || variable.category === category) &&
    (!missingness || (missingness === "MISSING" ? variable.missingPercent > 0 : variable.missingPercent === 0)) &&
    (!selectability || (selectability === "SELECTABLE" ? variable.selectable : !variable.selectable)),
  );
  const primary = variables.find((variable) => variable.name === selected[0]);
  const choose = (name: string) => {
    if (selected.includes(name)) setSelected(selected.filter((item) => item !== name));
    else setSelected([...selected, name].slice(-6));
  };
  return (
    <aside className="space-y-3 lg:sticky lg:top-2 lg:max-h-[calc(100vh-1rem)] lg:overflow-auto" data-testid="stage3-eda-variable-explorer">
      <section className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-cyan-700"><Search size={14} /> Variable explorer</div>
        <div className="relative mt-3"><Search size={13} className="absolute left-2.5 top-2.5 text-slate-400" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search 254 candidates" className="w-full rounded-lg border border-slate-200 py-2 pl-8 pr-2 text-xs" /></div>
        <div className="mt-2 grid grid-cols-2 gap-2"><select value={role} onChange={(event) => setRole(event.target.value)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-[11px]"><option value="">All roles</option>{roles.map((item) => <option key={item}>{item}</option>)}</select><select value={source} onChange={(event) => setSource(event.target.value)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-[11px]"><option value="">Core + context</option><option value="CORE">Core Gold-48</option><option value="CONTEXT">Contextual</option></select><select value={dataType} onChange={(event) => setDataType(event.target.value)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-[11px]"><option value="">All data types</option>{dataTypes.map((item) => <option key={item}>{item}</option>)}</select><select value={selectability} onChange={(event) => setSelectability(event.target.value)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-[11px]"><option value="">Selectable + locked</option><option value="SELECTABLE">Selectable only</option><option value="LOCKED">Nonselectable only</option></select><select value={missingness} onChange={(event) => setMissingness(event.target.value)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-[11px]"><option value="">Any missingness</option><option value="MISSING">Has missing values</option><option value="COMPLETE">Physically complete</option></select><select value={category} onChange={(event) => setCategory(event.target.value)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-[11px]"><option value="">All entity/categories</option>{categories.map((item) => <option key={item}>{item}</option>)}</select></div>
        <select value={family} onChange={(event) => setFamily(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[11px]"><option value="">All feature families</option>{families.map((item) => <option key={item}>{item}</option>)}</select>
        <div className="mt-3 flex items-center justify-between text-[10px] font-semibold uppercase text-slate-400"><span>{filtered.length} variables</span><span>{selected.length}/6 selected</span></div>
        <div className="mt-1 max-h-[410px] space-y-1 overflow-auto pr-1">
          {filtered.map((variable) => {
            const on = selected.includes(variable.name);
            return <div key={variable.name} className={`rounded-lg border p-2 ${on ? "border-cyan-300 bg-cyan-50" : "border-slate-100 hover:border-slate-200"}`}>
              <div className="flex items-start gap-2"><input aria-label={`Select ${variable.name}`} type="checkbox" checked={on} disabled={!variable.selectable} onChange={() => choose(variable.name)} className="mt-0.5" /><button type="button" disabled={!variable.selectable} onClick={() => choose(variable.name)} className={`min-w-0 flex-1 text-left ${variable.selectable ? "" : "cursor-not-allowed opacity-60"}`}><div className="truncate font-mono text-[11px] font-semibold text-slate-800">{variable.name}</div><div className="mt-0.5 flex flex-wrap gap-1"><span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] text-slate-600">{variable.dataType}</span><span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] text-slate-600">{variable.role}</span><span className="rounded bg-cyan-50 px-1.5 py-0.5 text-[9px] text-cyan-700">{variable.core ? "CORE" : "CONTEXT"}</span>{!variable.selectable ? <span className="rounded bg-rose-50 px-1.5 py-0.5 text-[9px] text-rose-700">NONSELECTABLE</span> : null}{variable.missingPercent > 0 ? <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[9px] text-amber-700">{pct(variable.missingPercent)} missing</span> : null}</div></button><button type="button" title="Bookmark variable for review" onClick={() => toggleBookmark(variable.name)} className={bookmarked.includes(variable.name) ? "text-amber-500" : "text-slate-300 hover:text-amber-500"}>{bookmarked.includes(variable.name) ? <Star size={14} fill="currentColor" /> : <Star size={14} />}</button></div>
            </div>;
          })}
        </div>
      </section>
      {primary ? <section className="rounded-2xl border border-slate-200 bg-slate-950 p-4 text-white"><div className="text-[10px] font-semibold uppercase tracking-wide text-cyan-300">Selected variable</div><div className="mt-1 break-all font-mono text-sm font-semibold">{primary.name}</div><p className="mt-2 text-xs leading-5 text-slate-300">{primary.definition}</p><dl className="mt-3 space-y-2 text-[11px]"><Info label="Family" value={primary.featureFamily} /><Info label="Source lineage" value={primary.sourceLineage} /><Info label="Point-in-time" value={primary.pointInTimeTreatment} /><Info label="Availability era" value={primary.availabilityEra} /><Info label="Unique values" value={primary.uniqueCount === null ? "Not reported" : int(primary.uniqueCount)} /><Info label="Selectable" value={primary.selectable ? "Yes — review only" : "No"} /></dl>{primary.proxyWarning ? <div className="mt-3 rounded-lg border border-amber-400/30 bg-amber-300/10 p-2 text-[11px] leading-4 text-amber-100"><AlertTriangle size={12} className="mr-1 inline" />{primary.proxyWarning}</div> : null}</section> : null}
    </aside>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-slate-500">{label}</dt><dd className="mt-0.5 break-words text-slate-200">{value}</dd></div>;
}

export function ProjectBoundDataProfile({ state, projectId, go }: { state: CurrentGoldReviewState; projectId: string; go: (id: string) => void }) {
  const { notes, setNote } = useCockpitStore();
  const authorityKey = state.review
    ? [state.review.sourceAuthority.manifestSha, state.review.goldAuthority.manifestSha, state.review.contextualFeaturePack?.manifestSha256 ?? "no-context", state.review.reviewDigest].join(":")
    : "authority-pending";
  const metadata = useProjectEdaMetadata(projectId, authorityKey, state.status === "ready" && Boolean(state.review));
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [selectedVariables, setSelectedVariables] = useState<string[]>([]);
  const [filters, setFilters] = useState<ProjectEdaFilters>({});
  const [distributionMode, setDistributionMode] = useState<DistributionMode>("histogram");
  const [relationshipMode, setRelationshipMode] = useState<RelationshipMode>("association");
  const [missingnessMode, setMissingnessMode] = useState<MissingnessMode>("missingness");
  const [bins, setBins] = useState(30);
  const [topN, setTopN] = useState(20);
  const [logScale, setLogScale] = useState(false);
  const [stratifyBy, setStratifyBy] = useState<StratifyBy>("");
  const [associationMethod, setAssociationMethod] = useState<AssociationMethod>("auto");
  const [samplingSeed, setSamplingSeed] = useState(DEFAULT_SEED);
  const [viewName, setViewName] = useState("");
  const [viewNotes, setViewNotes] = useState("");
  const storedBookmarks = parseStored<VariableBookmarks | string[]>(notes[BOOKMARKS_KEY], { authorityKey, names: [] });
  const bookmarks = !Array.isArray(storedBookmarks) && storedBookmarks.authorityKey === authorityKey ? storedBookmarks.names : [];
  const savedViews = parseStored<EdaView[]>(notes[SAVED_VIEWS_KEY], []);
  const variables = metadata.value?.data.variables ?? [];

  useEffect(() => {
    if (!selectedVariables.length && variables.length) {
      const initial = variables.find((variable) => variable.selectable && variable.dataType.toLowerCase().match(/int|float|double|number|numeric/)) ?? variables.find((variable) => variable.selectable);
      if (initial) setSelectedVariables([initial.name]);
    }
  }, [variables, selectedVariables.length]);

  const selected = variables.filter((variable) => selectedVariables.includes(variable.name));
  const primary = selected[0];
  const numericPrimary = primary && /int|float|double|number|numeric/i.test(primary.dataType);
  const query = useMemo<ProjectEdaQuery | null>(() => {
    if (!metadata.value || activeTab === "saved") return null;
    const primaryOnly = primary ? [primary.name] : [];
    const selectedUpToLimit = selectedVariables.slice(0, 6);
    if (activeTab === "overview" || activeTab === "target") return { queryType: "overview", filters, variables: primaryOnly };
    if (activeTab === "distributions") return { filters, variables: primaryOnly, queryType: numericPrimary ? "distribution" : "category_counts", settings: { bins, topN, stratifyBy, logScale } };
    if (activeTab === "relationships") return selectedVariables.length < 2 ? null : { filters, variables: selectedUpToLimit, queryType: relationshipMode === "association" ? "association" : "pairwise_sample", settings: { seed: samplingSeed, sampleSize: Math.min(2500, metadata.value.data.queryLimits.maxSampleRows), mode: relationshipMode, method: associationMethod } };
    if (activeTab === "missingness") return missingnessMode === "outliers" && !numericPrimary ? null : { filters, variables: missingnessMode === "outliers" ? primaryOnly : selectedUpToLimit, queryType: missingnessMode, settings: { method: "IQR", limit: 50 } };
    if (activeTab === "time") return { filters, variables: primaryOnly, queryType: "temporal", settings: { granularity: "month", driftMethods: ["PSI", "KS"] } };
    return { filters, variables: primaryOnly, queryType: "cold_start" };
  }, [metadata.value, activeTab, filters, selectedVariables, numericPrimary, bins, topN, stratifyBy, logScale, relationshipMode, associationMethod, samplingSeed, missingnessMode]);
  const analytical = useProjectEdaQuery<unknown>(projectId, authorityKey, query);

  const toggleBookmark = (name: string) => setNote(BOOKMARKS_KEY, JSON.stringify({ authorityKey, names: bookmarks.includes(name) ? bookmarks.filter((item) => item !== name) : [...bookmarks, name] } satisfies VariableBookmarks));
  const saveView = () => {
    const name = viewName.trim() || `${TABS.find((tab) => tab.id === activeTab)?.label} · ${new Date().toLocaleDateString()}`;
    const view: EdaView = { id: globalThis.crypto?.randomUUID?.() ?? `${Date.now()}`, authorityKey, name, tab: activeTab, selectedVariables, filters: compactProjectEdaFilters(filters), settings: { distributionMode, relationshipMode, missingnessMode, bins, topN, logScale, stratifyBy, associationMethod, samplingSeed }, notes: viewNotes.trim(), savedAt: new Date().toISOString() };
    setNote(SAVED_VIEWS_KEY, JSON.stringify([...savedViews, view]));
    setViewName(""); setViewNotes("");
  };
  const restoreView = (view: EdaView) => {
    if (view.authorityKey !== authorityKey) return;
    setActiveTab(view.tab); setSelectedVariables(view.selectedVariables); setFilters(view.filters); setDistributionMode(view.settings.distributionMode); setRelationshipMode(view.settings.relationshipMode); setMissingnessMode(view.settings.missingnessMode); setBins(view.settings.bins); setTopN(view.settings.topN); setLogScale(view.settings.logScale); setStratifyBy(view.settings.stratifyBy ?? ""); setAssociationMethod(view.settings.associationMethod ?? "auto"); setSamplingSeed(view.settings.samplingSeed);
  };
  const handoff = (destination: "outliers" | "missing" | "features") => {
    setNote("stage3.eda.handoff", JSON.stringify({ destination, selectedVariables, filters: compactProjectEdaFilters(filters), authorityKey, createdAt: new Date().toISOString() }));
    go(destination);
  };

  if (state.status === "loading" || state.status === "idle" || metadata.status === "loading" || metadata.status === "idle") return <QueryStatus status="loading" error={null} />;
  if (state.status === "error" || !state.review) return <QueryStatus status="error" error={state.error || "Project-bound Stage 3 authority unavailable."} />;
  if (metadata.status === "error" || !metadata.value) return <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6"><QueryStatus status="error" error={metadata.error} /><button type="button" onClick={() => void metadata.refresh()} className="mx-auto mt-3 flex items-center gap-2 rounded-lg bg-rose-900 px-3 py-2 text-xs font-semibold text-white"><RefreshCw size={13} />Retry metadata</button></div>;

  const meta = metadata.value.data;
  return (
    <div className="space-y-4" data-testid="stage3-project-bound-eda-workbench">
      <header className="relative overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 p-5 text-white shadow-xl">
        <div className="pointer-events-none absolute inset-0 opacity-70" style={{ backgroundImage: "radial-gradient(circle at 90% 0%, rgba(34,211,238,.2), transparent 28%), linear-gradient(rgba(148,163,184,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,.05) 1px, transparent 1px)", backgroundSize: "auto, 28px 28px, 28px 28px" }} />
        <div className="relative flex flex-wrap items-start justify-between gap-4"><div><div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-cyan-300">Project-bound analytical workbench</div><h3 className="mt-2 text-2xl font-semibold">Explore development evidence without touching the holdout</h3><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">All summaries are computed server-side from <b>{metadata.value.authority.goldDatasetId}</b>. Charts are descriptive research tools; bookmarks do not select features and no read can fit or score a model.</p></div><div className="rounded-xl border border-amber-300/30 bg-amber-300/10 p-3 text-amber-100"><div className="flex items-center gap-2 text-xs font-semibold uppercase"><Lock size={15} /> Final OOT locked</div><div className="mt-1 text-xl font-semibold tabular-nums">{int(metadata.value.population.finalOotRows)}</div><div className="text-[11px]">Targets excluded from every EDA query</div></div></div>
        <div className="relative mt-4 grid gap-2 sm:grid-cols-3"><div className="rounded-lg border border-white/10 bg-white/5 p-2 text-xs"><span className="text-slate-400">Development population</span><b className="ml-2 tabular-nums">{int(metadata.value.population.rows)}</b></div><div className="rounded-lg border border-white/10 bg-white/5 p-2 text-xs"><span className="text-slate-400">Cutoff</span><b className="ml-2">{metadata.value.population.developmentEndDate}</b></div><div className="rounded-lg border border-white/10 bg-white/5 p-2 text-xs"><span className="text-slate-400">Authority digest</span><b className="ml-2 font-mono">{metadata.value.authority.reviewDigest.slice(0, 14)}…</b></div></div>
      </header>

      <section className="grid gap-2 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm sm:grid-cols-2 xl:grid-cols-5" data-testid="stage3-eda-readiness-strip">
        <Readiness label="Project / source identity" status="PASS" detail={`${state.review.sourceAuthority.datasetId} → ${state.review.goldAuthority.datasetId}`} />
        <Readiness label="Player / game identity" status={(state.review.identity.unresolvedPlayerIdentities + state.review.identity.ambiguousPlayerIdentities + state.review.identity.unresolvedGameIdentities + state.review.identity.ambiguousGameIdentities) === 0 ? "PASS" : "BLOCKED"} detail="Unresolved and ambiguous identities" />
        <Readiness label="Point-in-time review" status={state.review.pointInTimeReview.status} detail={state.review.pointInTimeReview.detail} />
        <Readiness label="Leakage gate" status={state.review.leakageGate.status} detail={state.review.leakageGate.detail} />
        <Readiness label="Model activity" status="PASS" detail="0 fits · 0 scores · 0 selections · 0 promotions" />
      </section>

      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white p-1 shadow-sm"><nav className="flex min-w-max gap-1" aria-label="Data profile workbench tabs">{TABS.map((tab) => <button type="button" key={tab.id} onClick={() => setActiveTab(tab.id)} aria-current={activeTab === tab.id ? "page" : undefined} className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-2.5 text-xs font-semibold ${activeTab === tab.id ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}><tab.icon size={14} className={activeTab === tab.id ? "text-cyan-300" : "text-slate-400"} />{tab.label}</button>)}</nav></div>

      {activeTab !== "saved" ? <GlobalFilters filters={filters} setFilters={setFilters} metadata={meta.filterOptions} /> : null}

      <div className="grid min-w-0 gap-4 lg:grid-cols-[270px_minmax(0,1fr)]">
        <VariableExplorer variables={variables} selected={selectedVariables} setSelected={setSelectedVariables} bookmarked={bookmarks} toggleBookmark={toggleBookmark} />
        <main className="min-w-0 space-y-4">
          {activeTab !== "saved" ? <WorkbenchControls tab={activeTab} primary={primary} selectedCount={selectedVariables.length} distributionMode={distributionMode} setDistributionMode={setDistributionMode} relationshipMode={relationshipMode} setRelationshipMode={setRelationshipMode} associationMethod={associationMethod} setAssociationMethod={setAssociationMethod} missingnessMode={missingnessMode} setMissingnessMode={setMissingnessMode} bins={bins} setBins={setBins} topN={topN} setTopN={setTopN} logScale={logScale} setLogScale={setLogScale} stratifyBy={stratifyBy} setStratifyBy={setStratifyBy} seed={samplingSeed} setSeed={setSamplingSeed} limits={meta.queryLimits} /> : null}
          {activeTab === "relationships" && selectedVariables.length < 2 ? <div className="rounded-2xl border border-dashed border-cyan-300 bg-cyan-50/40 p-10 text-center"><GitCompareArrows size={24} className="mx-auto text-cyan-700" /><div className="mt-3 font-semibold text-slate-900">Select at least two variables</div><p className="mt-1 text-sm text-slate-600">The association and pairwise endpoints require 2–6 variables. Choose them in the variable explorer; no request has been sent.</p></div> : null}
          {activeTab === "missingness" && missingnessMode === "outliers" && !numericPrimary ? <div className="rounded-2xl border border-dashed border-amber-300 bg-amber-50/40 p-10 text-center"><Box size={24} className="mx-auto text-amber-700" /><div className="mt-3 font-semibold text-slate-900">Select one numeric variable</div><p className="mt-1 text-sm text-slate-600">Descriptive IQR and robust-z diagnostics require a numeric primary variable. No invalid request has been sent.</p></div> : null}
          {activeTab !== "saved" && !(activeTab === "relationships" && selectedVariables.length < 2) && !(activeTab === "missingness" && missingnessMode === "outliers" && !numericPrimary) && analytical.status !== "ready" ? <QueryStatus status={analytical.status} error={analytical.error} /> : null}
          {activeTab !== "saved" && analytical.value ? <TabContent tab={activeTab} relationshipMode={relationshipMode} distributionMode={distributionMode} logScale={logScale} missingnessMode={missingnessMode} envelope={analytical.value} taxonomy={meta.targetTaxonomy} families={meta.families} variables={selected} handoff={handoff} /> : null}
          {activeTab === "saved" ? <SavedViewsPanel views={savedViews} authorityKey={authorityKey} bookmarks={bookmarks} variables={variables} viewName={viewName} setViewName={setViewName} viewNotes={viewNotes} setViewNotes={setViewNotes} saveView={saveView} restoreView={restoreView} removeView={(id) => setNote(SAVED_VIEWS_KEY, JSON.stringify(savedViews.filter((view) => view.id !== id)))} handoff={handoff} /> : null}
          {activeTab !== "saved" ? <section className="rounded-2xl border border-cyan-200 bg-cyan-50/40 p-4"><div className="flex flex-wrap items-center gap-3"><div><div className="text-xs font-semibold uppercase text-cyan-800"><Save size={14} className="mr-1 inline" /> Save this analytical view</div><p className="mt-1 text-xs text-cyan-900">Stores filters, variables, chart settings, deterministic seed, and notes in the existing project-scoped cockpit autosave.</p></div><input value={viewName} onChange={(event) => setViewName(event.target.value)} placeholder="View name" className="ml-auto rounded-lg border border-cyan-200 bg-white px-3 py-2 text-xs text-slate-800" /><input value={viewNotes} onChange={(event) => setViewNotes(event.target.value)} placeholder="Scientist notes (optional)" className="min-w-56 flex-1 rounded-lg border border-cyan-200 bg-white px-3 py-2 text-xs text-slate-800" /><button type="button" onClick={saveView} className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-800 px-3 py-2 text-xs font-semibold text-white"><BookmarkCheck size={14} /> Save view</button></div></section> : null}
        </main>
      </div>
    </div>
  );
}

function Readiness({ label, status, detail }: { label: string; status: string; detail: string }) {
  const blocked = status === "FAIL" || status === "BLOCKED";
  const warning = status === "REVIEW" || status.includes("CONDITION") || status === "WARNING";
  return <div className={`rounded-xl border p-3 ${blocked ? "border-rose-200 bg-rose-50" : warning ? "border-amber-200 bg-amber-50" : "border-emerald-200 bg-emerald-50"}`}><div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div><div className={`mt-1 text-xs font-semibold ${blocked ? "text-rose-800" : warning ? "text-amber-800" : "text-emerald-800"}`}>{status.replaceAll("_", " ")}</div><p className="mt-1 line-clamp-2 text-[10px] leading-4 text-slate-600">{detail}</p></div>;
}

function WorkbenchControls({ tab, primary, selectedCount, distributionMode, setDistributionMode, relationshipMode, setRelationshipMode, associationMethod, setAssociationMethod, missingnessMode, setMissingnessMode, bins, setBins, topN, setTopN, logScale, setLogScale, stratifyBy, setStratifyBy, seed, setSeed, limits }: { tab: TabId; primary?: ProjectEdaVariable; selectedCount: number; distributionMode: DistributionMode; setDistributionMode: (value: DistributionMode) => void; relationshipMode: RelationshipMode; setRelationshipMode: (value: RelationshipMode) => void; associationMethod: AssociationMethod; setAssociationMethod: (value: AssociationMethod) => void; missingnessMode: MissingnessMode; setMissingnessMode: (value: MissingnessMode) => void; bins: number; setBins: (value: number) => void; topN: number; setTopN: (value: number) => void; logScale: boolean; setLogScale: (value: boolean) => void; stratifyBy: StratifyBy; setStratifyBy: (value: StratifyBy) => void; seed: number; setSeed: (value: number) => void; limits: { maxBins: number; maxCategories: number; maxVariables: number; maxSampleRows: number } }) {
  if (!["distributions", "relationships", "missingness", "time"].includes(tab)) return null;
  return <section className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm"><div className="flex flex-wrap items-center gap-2"><SlidersHorizontal size={15} className="text-cyan-700" /><span className="mr-2 text-xs font-semibold uppercase tracking-wide text-slate-600">Chart controls</span>{tab === "distributions" ? <><select value={distributionMode} onChange={(event) => setDistributionMode(event.target.value as DistributionMode)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs"><option value="histogram">Histogram</option><option value="density">Smoothed density</option><option value="ecdf">ECDF</option><option value="box">Box plot</option><option value="violin">Violin plot</option></select><label className="flex items-center gap-1 text-xs">Bins<input type="range" min={10} max={limits.maxBins} value={bins} onChange={(event) => setBins(Number(event.target.value))} />{bins}</label><label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={logScale} onChange={(event) => setLogScale(event.target.checked)} /> Log scale</label><label className="flex items-center gap-1 text-xs">Stratify by<select value={stratifyBy} onChange={(event) => setStratifyBy(event.target.value as StratifyBy)} className="rounded border border-slate-200 px-2 py-1"><option value="">None</option><option value="outcome">Outcome</option><option value="season">Season</option><option value="month">Month</option></select></label><label className="flex items-center gap-1 text-xs">Top N<input type="number" min={3} max={limits.maxCategories} value={topN} onChange={(event) => setTopN(Number(event.target.value))} className="w-14 rounded border border-slate-200 px-1 py-1" /></label></> : null}{tab === "relationships" ? <><select value={relationshipMode} onChange={(event) => setRelationshipMode(event.target.value as RelationshipMode)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs"><option value="association">Association heatmap</option><option value="scatter">Scatter / density</option><option value="pairwise">Pairwise matrix</option></select>{relationshipMode === "association" ? <select aria-label="Association method" value={associationMethod} onChange={(event) => setAssociationMethod(event.target.value as AssociationMethod)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs"><option value="auto">Method: auto by type</option><option value="pearson">Pearson (numeric)</option><option value="spearman">Spearman (numeric)</option></select> : <label className="flex items-center gap-1 text-xs">Seed<input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} className="w-28 rounded border border-slate-200 px-2 py-1" /></label>}<span className="text-[11px] text-slate-500">{selectedCount}/{limits.maxVariables} variables · max {int(limits.maxSampleRows)} sampled rows</span></> : null}{tab === "missingness" ? <select value={missingnessMode} onChange={(event) => setMissingnessMode(event.target.value as MissingnessMode)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs"><option value="missingness">Missingness diagnostics</option><option value="outliers">Descriptive outliers</option></select> : null}{tab === "time" ? <span className="text-xs text-slate-600">Monthly development evidence · PSI and KS are descriptive only</span> : null}<span className="ml-auto truncate text-[11px] text-slate-500">Primary: <b className="font-mono text-slate-700">{primary?.name || "select a variable"}</b></span></div></section>;
}

function TabContent({ tab, envelope, distributionMode, logScale, relationshipMode, missingnessMode, taxonomy, families, variables, handoff }: { tab: TabId; envelope: ProjectEdaEnvelope<unknown>; distributionMode: DistributionMode; logScale: boolean; relationshipMode: RelationshipMode; missingnessMode: MissingnessMode; taxonomy: string[]; families: ProjectEdaFamily[]; variables: ProjectEdaVariable[]; handoff: (destination: "outliers" | "missing" | "features") => void }) {
  if (tab === "overview") return <OverviewTab envelope={envelope as ProjectEdaEnvelope<OverviewData>} families={families} />;
  if (tab === "target") return <TargetTab envelope={envelope as ProjectEdaEnvelope<OverviewData>} taxonomy={taxonomy} />;
  if (tab === "distributions") return <DistributionTab envelope={envelope as ProjectEdaEnvelope<DistributionData | CategoryCountsData>} mode={distributionMode} logScale={logScale} variable={variables[0]} />;
  if (tab === "relationships") return <RelationshipsTab envelope={envelope as ProjectEdaEnvelope<AssociationData | PairwiseData>} mode={relationshipMode} />;
  if (tab === "missingness") return <MissingOutlierTab envelope={envelope as ProjectEdaEnvelope<MissingnessData | OutliersData>} mode={missingnessMode} handoff={handoff} />;
  if (tab === "time") return <TemporalTab envelope={envelope as ProjectEdaEnvelope<TemporalData>} />;
  return <ColdStartTab envelope={envelope as ProjectEdaEnvelope<ColdStartData>} />;
}

function OverviewTab({ envelope, families }: { envelope: ProjectEdaEnvelope<OverviewData>; families: ProjectEdaFamily[] }) {
  const data = envelope.data;
  const target = barOption(data.targetDistribution.map((row) => row.value), data.targetDistribution.map((row) => row.percent), "Share of development PAs (%)");
  const time = lineOption(data.rowsByMonth.map((row) => row.period), [{ name: "Plate appearances", values: data.rowsByMonth.map((row) => row.count) }], "Rows");
  const family: EChartsOption = { ...chartBase(), legend: { top: 0 }, xAxis: { type: "value", max: 100, name: "%" }, yAxis: { type: "category", data: data.featureFamilyCoverage.map((row) => row.family), axisLabel: { width: 170, overflow: "truncate" } }, series: [{ name: "Coverage", type: "bar", data: data.featureFamilyCoverage.map((row) => row.coveragePercent), stack: "coverage" }, { name: "Missing", type: "bar", data: data.featureFamilyCoverage.map((row) => row.missingPercent), stack: "coverage" }] };
  const history = barOption(data.historyDepth.map((row) => row.label), data.historyDepth.map((row) => row.count), "Players", true);
  const exclusions = data.summary.rowExclusions;
  return <div className="space-y-4"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><Metric label="Development rows" value={int(data.summary.developmentRows)} detail={`${data.summary.startDate} – ${data.summary.endDate}`} accent="cyan" /><Metric label="Games" value={int(data.summary.games)} detail="canonical game identities" /><Metric label="Batters / pitchers" value={`${int(data.summary.batters)} / ${int(data.summary.pitchers)}`} detail="development population" /><Metric label="Physical missingness" value={pct(data.summary.overallMissingPercent)} detail="across candidate library" accent="amber" /><Metric label="Cold start" value={pct(data.summary.coldStartPercent)} detail={`${int(exclusions.excludedRows)} source exclusions disclosed`} /></div><section className="rounded-2xl border border-slate-200 bg-white p-4"><div className="flex flex-wrap items-center gap-2"><div className="text-xs font-semibold uppercase tracking-wide text-slate-600">Source-to-Gold row reconciliation</div><span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-800">{exclusions.reasonStatus}</span></div><div className="mt-3 grid gap-2 sm:grid-cols-3"><Metric label="Accepted source PAs" value={int(exclusions.sourceRows)} detail="registered current source" /><Metric label="Model-ready PAs" value={int(exclusions.goldRows)} detail="Current Gold authority" /><Metric label="Excluded source PAs" value={int(exclusions.excludedRows)} detail="exact difference; never silently summarized" accent="amber" /></div><div className="mt-3 overflow-auto"><table className="w-full min-w-[520px] text-xs"><thead><tr className="text-left text-slate-500">{["Season", "Source", "Gold", "Excluded"].map((label) => <th key={label} className="border-b px-2 py-2">{label}</th>)}</tr></thead><tbody>{exclusions.bySeason.map((row) => <tr key={row.season}><td className="border-b px-2 py-2 font-semibold">{row.season}</td><td className="border-b px-2 py-2">{int(row.sourceRows)}</td><td className="border-b px-2 py-2">{int(row.goldRows)}</td><td className="border-b px-2 py-2">{int(row.excludedRows)}</td></tr>)}</tbody></table></div>{Object.keys(exclusions.reasonCounts).length ? <p className="mt-3 text-xs text-slate-600">Exact registered reasons: {Object.entries(exclusions.reasonCounts).map(([reason, count]) => `${reason} ${int(count)}`).join(" · ")}</p> : <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">The registered authority does not contain a reconciling causal ledger, so no reason is invented. Unsupported concentration cuts: {exclusions.unsupportedConcentrations.join(", ")}.</p>}</section><div className="grid gap-4 xl:grid-cols-2"><ChartCard title="Governed target distribution" description="Eight-class development-only base rates." option={target} ariaLabel="Development target distribution" envelope={envelope} exportRows={rowsFrom(data.targetDistribution)} /><ChartCard title="Development population by month" description="Row volume; no final-OOT dates are queried." option={time} ariaLabel="Development population by month" envelope={envelope} exportRows={rowsFrom(data.rowsByMonth)} /><ChartCard title="Feature-family coverage" description="Coverage and physical missingness by declared family." option={family} ariaLabel="Feature family coverage" envelope={envelope} exportRows={rowsFrom(data.featureFamilyCoverage)} /><ChartCard title="Prior-history depth" description="Player population across governed history-depth buckets." option={history} ariaLabel="Players by prior history depth" envelope={envelope} exportRows={rowsFrom(data.historyDepth)} /></div><section className="rounded-2xl border border-slate-200 bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h4 className="font-semibold text-slate-950">Declared feature-family contracts</h4><span className="text-[11px] text-slate-500">EDA comparison only · no family is adopted here</span></div><div className="mt-3 overflow-auto"><table className="w-full min-w-[760px] text-xs"><thead><tr className="text-left text-slate-500">{["Family", "Features", "Active", "Inactive", "Coverage", "Missing", "Governance"].map((label) => <th key={label} className="border-b px-2 py-2">{label}</th>)}</tr></thead><tbody>{families.map((item) => <tr key={item.name}><td className="border-b px-2 py-2 font-semibold">{item.name}</td><td className="border-b px-2 py-2">{int(item.featureCount)}</td><td className="border-b px-2 py-2">{int(item.activeCount)}</td><td className="border-b px-2 py-2">{int(item.featureCount - item.activeCount)}</td><td className="border-b px-2 py-2">{pct(item.coveragePercent)}</td><td className="border-b px-2 py-2">{pct(item.missingPercent)}</td><td className="border-b px-2 py-2">{item.proxyWarning || "Point-in-time registered"}</td></tr>)}</tbody></table></div><details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-semibold text-slate-700">Show exact ordered family inventories</summary><div className="mt-3 space-y-2">{families.map((item) => <div key={item.name}><div className="text-[10px] font-semibold uppercase text-slate-500">{item.name}</div><p className="mt-1 break-words font-mono text-[10px] leading-5 text-slate-600">{item.orderedFeatures.join(" · ")}</p></div>)}</div></details></section></div>;
}

function DistributionTab({ envelope, mode, logScale, variable }: { envelope: ProjectEdaEnvelope<DistributionData | CategoryCountsData>; mode: DistributionMode; logScale: boolean; variable?: ProjectEdaVariable }) {
  if ("categories" in envelope.data) {
    const data = envelope.data;
    const categoryOption = barOption(data.categories.map((row) => row.value), data.categories.map((row) => row.percent), "Share (%)", true);
    if (logScale) categoryOption.xAxis = { type: "log", name: "Share (%)", min: 0.01 };
    return <div className="space-y-4"><ChartCard title={`${data.variable} category distribution`} description="Top categories with bounded other grouping and explicit missing category." option={categoryOption} ariaLabel={`Categorical distribution of ${data.variable}`} envelope={envelope} exportRows={rowsFrom(data.categories)} /><div className="grid gap-3 sm:grid-cols-2"><Metric label="Missing category" value={int(data.missingCount)} detail="never silently dropped" accent="amber" /><Metric label="Other categories" value={int(data.otherCount)} detail="bounded top-N aggregation" /></div></div>;
  }
  const data = envelope.data;
  let option: EChartsOption;
  let exportRows: Record<string, unknown>[] = [];
  if (mode === "density" || mode === "violin") {
    const density = data.density;
    option = mode === "density" ? lineOption(density.map((row) => String(row.value)), [{ name: "Density", values: density.map((row) => row.density) }], "Density") : { ...chartBase(), legend: { top: 0 }, xAxis: { type: "value", name: data.variable }, yAxis: { type: "value", axisLabel: { show: false }, min: (value: { max: number }) => -value.max, max: (value: { max: number }) => value.max }, series: [{ name: "Upper density", type: "line", smooth: true, symbol: "none", areaStyle: { opacity: 0.35 }, data: density.map((row) => [row.value, row.density]) }, { name: "Lower density", type: "line", smooth: true, symbol: "none", areaStyle: { opacity: 0.35 }, data: density.map((row) => [row.value, -row.density]) }] } as EChartsOption;
    exportRows = rowsFrom(density);
  } else if (mode === "ecdf") {
    option = { ...lineOption(data.ecdf.map((row) => String(row.value)), [{ name: "Cumulative %", values: data.ecdf.map((row) => row.cumulativePercent) }], "Cumulative %"), yAxis: { type: "value", min: 0, max: 100, name: "Cumulative %" } };
    exportRows = rowsFrom(data.ecdf);
  } else if (mode === "box") {
    const b = data.box;
    option = { ...chartBase(), tooltip: { trigger: "item" }, xAxis: { type: "category", data: [data.variable] }, yAxis: { type: "value" }, series: [{ name: "Five-number summary", type: "boxplot", data: b.min === null || b.q1 === null || b.median === null || b.q3 === null || b.max === null ? [] : [[b.min, b.q1, b.median, b.q3, b.max]] }] } as EChartsOption;
    exportRows = [b as unknown as Record<string, unknown>];
  } else {
    option = barOption(data.histogram.map((row) => `${row.binStart.toPrecision(4)}–${row.binEnd.toPrecision(4)}`), data.histogram.map((row) => row.count), "Rows");
    exportRows = rowsFrom(data.histogram);
  }
  if (logScale && mode !== "box" && mode !== "violin" && mode !== "ecdf") option.yAxis = { type: "log", name: mode === "density" ? "Density (log)" : "Rows (log)", min: 0.000001 };
  const stats = Object.entries(data.statistics);
  return <div className="space-y-4"><ChartCard title={`${mode === "violin" ? "Violin" : mode[0].toUpperCase() + mode.slice(1)} · ${data.variable}`} description={`${variable?.definition || "Selected numeric variable"} Tooltips, zoom, brush/reset, image and aggregated-data export are available.`} option={option} ariaLabel={`${mode} distribution of ${data.variable}`} envelope={envelope} exportRows={exportRows} /><section className="rounded-2xl border border-slate-200 bg-white p-4"><h4 className="font-semibold text-slate-950">Summary statistics and percentiles</h4><div className="mt-3 grid gap-2 sm:grid-cols-3 xl:grid-cols-6">{stats.map(([name, value]) => <div key={name} className="rounded-lg bg-slate-50 p-2"><div className="text-[10px] uppercase text-slate-500">{name}</div><div className="mt-1 font-mono text-xs font-semibold text-slate-800">{value === null ? "NA" : Number(value).toLocaleString(undefined, { maximumFractionDigits: 5 })}</div></div>)}</div></section>{data.stratified.length ? <section className="overflow-auto rounded-2xl border border-slate-200 bg-white p-4"><h4 className="font-semibold text-slate-950">Target / season strata</h4><table className="mt-3 w-full min-w-[600px] text-xs"><thead><tr className="text-left text-slate-500">{["Stratum", "Rows", "Mean", "Median", "Missing %"].map((label) => <th key={label} className="border-b px-2 py-2">{label}</th>)}</tr></thead><tbody>{data.stratified.map((row) => <tr key={row.stratum}><td className="border-b px-2 py-2 font-semibold">{row.stratum}</td><td className="border-b px-2 py-2">{int(row.count)}</td><td className="border-b px-2 py-2">{row.mean ?? "—"}</td><td className="border-b px-2 py-2">{row.median ?? "—"}</td><td className="border-b px-2 py-2">{pct(row.missingPercent)}</td></tr>)}</tbody></table></section> : null}</div>;
}

function RelationshipsTab({ envelope, mode }: { envelope: ProjectEdaEnvelope<AssociationData | PairwiseData>; mode: RelationshipMode }) {
  if ("cells" in envelope.data) {
    const data = envelope.data;
    const index = new Map(data.variables.map((name, i) => [name, i]));
    const estimableCells = data.cells.filter((cell): cell is typeof cell & { value: number } => cell.value !== null && Number.isFinite(cell.value));
    const option: EChartsOption = { ...chartBase(), tooltip: { position: "top", formatter: (params: unknown) => { const p = params as { data?: { value?: [number, number, number]; method?: string; rows?: number } }; return `${data.variables[p.data?.value?.[1] ?? 0]} × ${data.variables[p.data?.value?.[0] ?? 0]}<br/><b>${Number(p.data?.value?.[2]).toFixed(3)}</b><br/>${p.data?.method} · ${int(p.data?.rows)} rows`; } }, xAxis: { type: "category", data: data.variables, axisLabel: { rotate: 35 } }, yAxis: { type: "category", data: data.variables }, visualMap: { min: -1, max: 1, calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#0e7490", "#f8fafc", "#be123c"] } }, series: [{ type: "heatmap", data: estimableCells.map((cell) => ({ value: [index.get(cell.x) ?? 0, index.get(cell.y) ?? 0, cell.value], method: cell.method, rows: cell.rows })), label: { show: data.variables.length <= 8, formatter: (params: unknown) => Number((params as { value?: [number, number, number] }).value?.[2]).toFixed(2) } }] } as EChartsOption;
    return <div className="space-y-4"><section className="rounded-xl border border-cyan-200 bg-cyan-50 p-3 text-xs leading-5 text-cyan-900"><b>Methods remain explicit:</b> Pearson for numeric linear, Spearman for numeric monotonic, Cramér’s V for categorical pairs, and correlation ratio for numeric–categorical relationships. Unlike measures are labeled and are not presented as interchangeable. Degenerate pairs are left blank as not estimable; they are never rendered as zero.</section><ChartCard title="Correlation / association heatmap" description={`Methods present: ${data.methods.join(" · ")}. Values are descriptive, not automatic feature selection.`} option={option} ariaLabel="Project-bound association heatmap" envelope={envelope} exportRows={rowsFrom(data.cells)} /></div>;
  }
  const data = envelope.data;
  const numeric = data.variables.filter((name) => data.rows.some((row) => typeof row[name] === "number"));
  const pairs: [string, string][] = [];
  for (let i = 0; i < numeric.length; i += 1) for (let j = i + 1; j < numeric.length; j += 1) if (pairs.length < (mode === "pairwise" ? 9 : 1)) pairs.push([numeric[i], numeric[j]]);
  return <div className="space-y-4"><section className="rounded-xl border border-cyan-200 bg-cyan-50 p-3 text-xs text-cyan-900"><b>Deterministic point sample:</b> {int(data.sampleSize)} of {int(data.populationSize)} rows · seed {data.seed} · {data.method}. The full population never enters the browser, and point-level sample download is disabled by default.</section>{!pairs.length ? <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">Select at least two numeric variables for a scatter or pairwise view.</div> : <div className={mode === "pairwise" ? "grid gap-4 xl:grid-cols-2" : "space-y-4"}>{pairs.map(([x, y]) => { const rows = data.rows.filter((row) => typeof row[x] === "number" && typeof row[y] === "number"); const option: EChartsOption = { ...chartBase(), tooltip: { trigger: "item" }, brush: { toolbox: ["rect", "polygon", "clear"], xAxisIndex: 0, yAxisIndex: 0 }, xAxis: { type: "value", name: x, scale: true }, yAxis: { type: "value", name: y, scale: true }, series: [{ type: "scatter", large: rows.length > 1000, symbolSize: 5, data: rows.map((row) => [row[x], row[y]]), itemStyle: { opacity: 0.42 } }] }; return <ChartCard key={`${x}:${y}`} title={`${x} × ${y}`} description="Scatter/density view with tooltip, zoom and rectangular brushing. Trend is descriptive only." option={option} ariaLabel={`Scatter plot ${x} by ${y}`} envelope={envelope} />; })}</div>}</div>;
}

function TargetTab({ envelope, taxonomy }: { envelope: ProjectEdaEnvelope<OverviewData>; taxonomy: string[] }) {
  const data = envelope.data;
  const classes = taxonomy.length ? taxonomy : TARGET_ORDER;
  const seasons = [...new Set(data.targetBySeason.map((row) => row.season))].sort();
  const seasonSeries = classes.map((target) => ({ name: target, type: "bar" as const, stack: "target", data: seasons.map((season) => data.targetBySeason.find((row) => row.season === season && row.value === target)?.percent ?? 0) }));
  const bySeason: EChartsOption = { ...chartBase(), legend: { type: "scroll", top: 0 }, xAxis: { type: "category", data: seasons.map(String) }, yAxis: { type: "value", max: 100, name: "Share (%)" }, series: seasonSeries };
  const months = [...new Set(data.targetByMonth.map((row) => row.period))].sort();
  const byMonth = lineOption(months, classes.map((target) => ({ name: target, values: months.map((period) => data.targetByMonth.find((row) => row.period === period && row.value === target)?.percent ?? null) })), "Share (%)");
  const stateRows = data.targetBySimulationState.filter((row) => row.field === "context_outs_before");
  const states = [...new Set(stateRows.map((row) => String(row.state)))].sort((left, right) => Number(left) - Number(right));
  const byState: EChartsOption = { ...chartBase(), legend: { type: "scroll", top: 0 }, xAxis: { type: "category", data: states.map((state) => `${state} outs`) }, yAxis: { type: "value", max: 100, name: "Share (%)" }, series: classes.map((target) => ({ name: target, type: "bar", stack: "target", data: states.map((state) => stateRows.find((row) => String(row.state) === state && row.value === target)?.percent ?? 0) })) };
  const total = data.targetDistribution.reduce((sum, row) => sum + row.count, 0);
  const confidenceRows = data.targetDistribution.map((row) => {
    const p = total ? row.count / total : 0;
    const z = 1.959963984540054;
    const denominator = 1 + (z * z) / Math.max(total, 1);
    const center = (p + (z * z) / (2 * Math.max(total, 1))) / denominator;
    const half = z * Math.sqrt((p * (1 - p) + (z * z) / (4 * Math.max(total, 1))) / Math.max(total, 1)) / denominator;
    return { ...row, lower95: 100 * Math.max(0, center - half), upper95: 100 * Math.min(1, center + half) };
  });
  return <div className="space-y-4"><section className="rounded-2xl border border-slate-200 bg-white p-4"><div className="text-xs font-semibold uppercase tracking-wide text-cyan-700">Exact governed taxonomy</div><div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">{classes.map((name, index) => <div key={name} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-xs"><span className="mr-2 text-slate-400">{index + 1}</span><b>{name}</b></div>)}</div><p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><b>Probability calibration is primary;</b> class imbalance is a property of baseball and is not automatically corrected. This workbench makes no oversampling or class-weight recommendation.</p><p className="mt-2 text-xs text-slate-600">Use outcome stratification on the Distributions tab for one-feature class comparisons, or the global history and simulator-state filters for governed development-only slices.</p></section><div className="grid gap-4 xl:grid-cols-2"><ChartCard title="Class counts and proportions" description="Development base rates, including rare-class sample sizes." option={barOption(data.targetDistribution.map((row) => row.value), data.targetDistribution.map((row) => row.percent), "Share (%)")} ariaLabel="Eight class balance" envelope={envelope} exportRows={rowsFrom(confidenceRows)} /><ChartCard title="Class balance by season" description="Development seasons only; final-OOT class composition is inaccessible." option={bySeason} ariaLabel="Class distribution by development season" envelope={envelope} exportRows={rowsFrom(data.targetBySeason)} /><ChartCard title="Class balance by month" description="Monthly development-only target composition through 2026-08-13." option={byMonth} ariaLabel="Class distribution by development month" envelope={envelope} exportRows={rowsFrom(data.targetByMonth)} /><ChartCard title="Class balance by simulator state" description="Outcome composition by outs-before; other simulator states remain available through the global exact state filter." option={byState} ariaLabel="Class distribution by simulation state" envelope={envelope} exportRows={rowsFrom(stateRows)} /></div><section className="overflow-auto rounded-2xl border border-slate-200 bg-white p-4"><h4 className="font-semibold text-slate-950">Rare-class evidence and 95% binomial intervals</h4><p className="mt-1 text-xs text-slate-500">Wilson intervals describe development base-rate precision; they are not model-selection thresholds.</p><table className="mt-3 w-full min-w-[620px] text-xs"><thead><tr className="text-left text-slate-500">{["Class", "Rows", "Share", "95% interval"].map((label) => <th key={label} className="border-b px-2 py-2">{label}</th>)}</tr></thead><tbody>{confidenceRows.map((row) => <tr key={row.value}><td className="border-b px-2 py-2 font-mono font-semibold">{row.value}</td><td className="border-b px-2 py-2">{int(row.count)}</td><td className="border-b px-2 py-2">{pct(row.percent)}</td><td className="border-b px-2 py-2">{row.lower95.toFixed(3)}% – {row.upper95.toFixed(3)}%</td></tr>)}</tbody></table></section></div>;
}

function MissingOutlierTab({ envelope, mode, handoff }: { envelope: ProjectEdaEnvelope<MissingnessData | OutliersData>; mode: MissingnessMode; handoff: (destination: "outliers" | "missing" | "features") => void }) {
  if ("variables" in envelope.data) {
    const data = envelope.data;
    const vars = data.variables.slice().sort((a, b) => b.missingPercent - a.missingPercent);
    const names = [...new Set(data.coMissingness.flatMap((row) => [row.x, row.y]))];
    const index = new Map(names.map((name, i) => [name, i]));
    const co: EChartsOption = { ...chartBase(), xAxis: { type: "category", data: names, axisLabel: { rotate: 35 } }, yAxis: { type: "category", data: names }, visualMap: { min: 0, max: Math.max(1, ...data.coMissingness.map((row) => row.percent)), calculable: true, orient: "horizontal", bottom: 0 }, series: [{ type: "heatmap", data: data.coMissingness.map((row) => [index.get(row.x), index.get(row.y), row.percent]) }] };
    return <div className="space-y-4"><div className="grid gap-4 xl:grid-cols-2"><ChartCard title="Predictor missingness" description="Affected rows and physical missingness; indicator completeness is not treated as feature completeness." option={barOption(vars.map((row) => row.name), vars.map((row) => row.missingPercent), "Missing (%)", true)} ariaLabel="Predictor missingness bar chart" envelope={envelope} exportRows={rowsFrom(vars)} /><ChartCard title="Missingness matrix / co-missingness" description="Joint missingness across the selected variables; server-aggregated so no raw row matrix is transferred." option={co} ariaLabel="Missingness matrix and co-missingness heatmap" envelope={envelope} exportRows={rowsFrom(data.coMissingness)} /><ChartCard title="Missingness reason categories" description="Cold-start and source-era absence remain separate from identity or computation failure." option={barOption(data.reasons.map((row) => row.reason), data.reasons.map((row) => row.count), "Rows", true)} ariaLabel="Missingness reason categories" envelope={envelope} exportRows={rowsFrom(data.reasons)} /><ChartCard title="Missingness through time" description="Development-only season/month comparison." option={lineOption([...new Set(data.byPeriod.map((row) => row.period))], vars.slice(0, 4).map((variable) => ({ name: variable.name, values: [...new Set(data.byPeriod.map((row) => row.period))].map((period) => data.byPeriod.find((row) => row.period === period && row.variable === variable.name)?.missingPercent ?? null) })), "Missing %")} ariaLabel="Missingness over time" envelope={envelope} exportRows={rowsFrom(data.byPeriod)} /></div><HandoffActions handoff={handoff} selected="missing" /></div>;
  }
  const data = envelope.data;
  const option: EChartsOption = { ...chartBase(), tooltip: { trigger: "item" }, xAxis: { type: "time", name: "Game date" }, yAxis: { type: "value", name: data.variable, scale: true }, series: [{ type: "scatter", data: data.extremes.map((row) => [row.gameDate, row.value, row.side, row.canonicalPaId]), symbolSize: 7 }, { type: "line", name: "Lower threshold", showSymbol: false, data: data.extremes.map((row) => [row.gameDate, data.thresholds.lower]) }, { type: "line", name: "Upper threshold", showSymbol: false, data: data.extremes.map((row) => [row.gameDate, data.thresholds.upper]) }] };
  return <div className="space-y-4"><div className="grid gap-3 sm:grid-cols-3"><Metric label="Descriptive method" value={data.method} detail="no treatment applied" /><Metric label="Flagged observations" value={int(data.count)} detail={`${pct(data.percent)} of filtered development rows`} accent="amber" /><Metric label="Thresholds" value={`${data.thresholds.lower ?? "—"} / ${data.thresholds.upper ?? "—"}`} detail="lower / upper" /></div><ChartCard title={`Extreme observations · ${data.variable}`} description="Robust descriptive flags by date. Data Profile never clips, winsorizes, drops, or imputes a row. Point-level export is disabled by default." option={option} ariaLabel={`Outliers for ${data.variable}`} envelope={envelope} /><HandoffActions handoff={handoff} selected="outliers" /></div>;
}

function TemporalTab({ envelope }: { envelope: ProjectEdaEnvelope<TemporalData> }) {
  const data = envelope.data;
  const main = lineOption(data.series.map((row) => row.period), [{ name: "Mean", values: data.series.map((row) => row.mean) }, { name: "Median", values: data.series.map((row) => row.median) }], data.variable);
  const missing = lineOption(data.series.map((row) => row.period), [{ name: "Missing %", values: data.series.map((row) => row.missingPercent) }, { name: "Rows (scaled)", values: data.series.map((row) => row.count) }], "Value");
  const drift = lineOption(data.drift.map((row) => row.period), [{ name: "PSI", values: data.drift.map((row) => row.psi) }, { name: "KS", values: data.drift.map((row) => row.ks) }], "Drift diagnostic");
  const periods = data.series.map((row) => row.period);
  const targetMix: EChartsOption = { ...chartBase(), legend: { type: "scroll", top: 0 }, xAxis: { type: "category", data: periods }, yAxis: { type: "value", max: 100, name: "Share (%)" }, series: TARGET_ORDER.map((target) => ({ name: target, type: "line", stack: "target", areaStyle: { opacity: 0.2 }, showSymbol: false, data: data.series.map((row) => row.targetComposition.find((item) => item.value === target)?.percent ?? 0) })) };
  const targetRows = data.series.flatMap((row) => row.targetComposition.map((item) => ({ period: row.period, ...item })));
  return <div className="space-y-4"><section className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><b>Descriptive stability diagnostics only.</b> PSI and KS highlight changing distributions and source eras; they do not select a feature, threshold, or model. The 2026 comparison stops on 2026-08-13.</section><div className="grid gap-4 xl:grid-cols-2"><ChartCard title={`${data.variable} through time`} description={`${data.granularity} development aggregates; mean and median.`} option={main} ariaLabel={`${data.variable} monthly stability`} envelope={envelope} exportRows={rowsFrom(data.series)} /><ChartCard title="Coverage and row volume" description="Missingness and available evidence through time." option={missing} ariaLabel="Feature coverage through time" envelope={envelope} exportRows={rowsFrom(data.series)} /><ChartCard title="Target mix through time" description="Development-only class composition; final-OOT outcomes are not materialized." option={targetMix} ariaLabel="Target mix through development time" envelope={envelope} exportRows={rowsFrom(targetRows)} /><ChartCard title="Distribution drift" description="PSI and KS against each documented baseline period; source-era shifts remain visible." option={drift} ariaLabel="Feature distribution drift" envelope={envelope} exportRows={rowsFrom(data.drift)} /></div></div>;
}

function ColdStartTab({ envelope }: { envelope: ProjectEdaEnvelope<ColdStartData> }) {
  const data = envelope.data;
  const bars: EChartsOption = { ...chartBase(), legend: { top: 0 }, xAxis: { type: "category", data: ["Batter", "Pitcher"] }, yAxis: { type: "value", name: "Rows" }, series: [{ name: "No prior history", type: "bar", data: [data.batter.noPriorRows, data.pitcher.noPriorRows] }, { name: "Insufficient history", type: "bar", data: [data.batter.insufficientRows, data.pitcher.insufficientRows] }] };
  const periods = [...new Set([...data.batter.byPeriod.map((row) => row.period), ...data.pitcher.byPeriod.map((row) => row.period)])].sort();
  const time = lineOption(periods, [{ name: "Batter no history", values: periods.map((period) => data.batter.byPeriod.find((row) => row.period === period)?.noPriorRows ?? 0) }, { name: "Pitcher no history", values: periods.map((period) => data.pitcher.byPeriod.find((row) => row.period === period)?.noPriorRows ?? 0) }], "Rows");
  const composition: EChartsOption = { ...chartBase(), legend: { type: "scroll", top: 0 }, xAxis: { type: "category", data: [...new Set(data.targetComposition.map((row) => row.scope))] }, yAxis: { type: "value", max: 100, name: "Share (%)" }, series: TARGET_ORDER.map((target) => ({ name: target, type: "bar", stack: "target", data: [...new Set(data.targetComposition.map((row) => row.scope))].map((scope) => data.targetComposition.find((row) => row.scope === scope && row.value === target)?.percent ?? 0) })) };
  return <div className="space-y-4"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><Metric label="Cold-start rows" value={int(data.summary.coldStartRows)} detail={`${pct(data.summary.coldStartPercent)} of development`} accent="amber" /><Metric label="Affected games" value={int(data.summary.affectedGames)} detail="canonical development games" /><Metric label="Affected teams" value={int(data.summary.affectedTeams)} detail="exact canonical teams" /><Metric label="Affected batters" value={int(data.batter.affectedPlayers)} detail={`${int(data.batter.affectedGames)} games · ${int(data.batter.affectedTeams)} teams`} /><Metric label="Affected pitchers" value={int(data.pitcher.affectedPlayers)} detail={`${int(data.pitcher.affectedGames)} games · ${int(data.pitcher.affectedTeams)} teams`} /></div><div className="grid gap-4 xl:grid-cols-2"><ChartCard title="Batter and pitcher history sufficiency" description="Cold-start rows are retained; this view informs later fold-local priors or imputation." option={bars} ariaLabel="Batter pitcher cold start counts" envelope={envelope} exportRows={[{ entity: "Batter", noPrior: data.batter.noPriorRows, insufficient: data.batter.insufficientRows }, { entity: "Pitcher", noPrior: data.pitcher.noPriorRows, insufficient: data.pitcher.insufficientRows }]} /><ChartCard title="Cold-start prevalence through time" description="Unseen players by development season/month." option={time} ariaLabel="Cold start over time" envelope={envelope} exportRows={rowsFrom([...data.batter.byPeriod, ...data.pitcher.byPeriod])} /><div className="xl:col-span-2"><ChartCard title="Cold-start target composition" description="Development-only target mix for established versus low-history players." option={composition} ariaLabel="Cold start target composition" envelope={envelope} exportRows={rowsFrom(data.targetComposition)} /></div></div></div>;
}

function HandoffActions({ handoff, selected }: { handoff: (destination: "outliers" | "missing" | "features") => void; selected: "missing" | "outliers" }) {
  return <section className="rounded-2xl border border-slate-200 bg-white p-4"><div className="text-xs font-semibold uppercase text-slate-500">Analytical handoff · no automatic treatment</div><div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => handoff("outliers")} className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold ${selected === "outliers" ? "bg-amber-700 text-white" : "border border-slate-200 text-slate-700"}`}><Box size={14} /> Open in Outliers</button><button type="button" onClick={() => handoff("missing")} className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold ${selected === "missing" ? "bg-amber-700 text-white" : "border border-slate-200 text-slate-700"}`}><CircleOff size={14} /> Open in Missing Values</button><button type="button" onClick={() => handoff("features")} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700"><Wand2 size={14} /> Bookmark for Feature Engineering</button></div><p className="mt-2 text-[11px] text-slate-500">Selected variables, filters, and exact data authority are persisted in the project-scoped workbench draft before navigation; later steps remain governed independently.</p></section>;
}

function SavedViewsPanel({ views, authorityKey, bookmarks, variables, viewName, setViewName, viewNotes, setViewNotes, saveView, restoreView, removeView, handoff }: { views: EdaView[]; authorityKey: string; bookmarks: string[]; variables: ProjectEdaVariable[]; viewName: string; setViewName: (value: string) => void; viewNotes: string; setViewNotes: (value: string) => void; saveView: () => void; restoreView: (view: EdaView) => void; removeView: (id: string) => void; handoff: (destination: "outliers" | "missing" | "features") => void }) {
  return <div className="space-y-4"><section className="rounded-2xl border border-cyan-200 bg-cyan-50/40 p-4"><div className="text-xs font-semibold uppercase text-cyan-800"><BookmarkCheck size={14} className="mr-1 inline" /> Project-level saved views</div><p className="mt-1 text-xs leading-5 text-cyan-900">Views survive navigation, project reopen, and frontend restart through the existing project-scoped cockpit persistence. They are analytical bookmarks—not model decisions.</p><div className="mt-3 flex flex-wrap gap-2"><input value={viewName} onChange={(event) => setViewName(event.target.value)} placeholder="View name" className="min-w-44 flex-1 rounded-lg border border-cyan-200 bg-white px-3 py-2 text-xs" /><input value={viewNotes} onChange={(event) => setViewNotes(event.target.value)} placeholder="Notes" className="min-w-44 flex-1 rounded-lg border border-cyan-200 bg-white px-3 py-2 text-xs" /><button type="button" onClick={saveView} className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-800 px-3 py-2 text-xs font-semibold text-white"><Save size={14} /> Save current state</button></div></section><section className="rounded-2xl border border-slate-200 bg-white p-4"><h4 className="font-semibold text-slate-950">Saved analytical views</h4>{views.length ? <div className="mt-3 grid gap-3 xl:grid-cols-2">{views.map((view) => { const stale = view.authorityKey !== authorityKey; return <article key={view.id} className={`rounded-xl border p-3 ${stale ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50"}`}><div className="flex items-start gap-2"><div className="min-w-0 flex-1"><div className="font-semibold text-slate-900">{view.name}</div><div className="mt-1 text-[10px] uppercase text-slate-500">{TABS.find((tab) => tab.id === view.tab)?.label} · {new Date(view.savedAt).toLocaleString()}</div></div><button title="Delete saved view" type="button" onClick={() => removeView(view.id)} className="text-slate-400 hover:text-rose-600"><Trash2 size={14} /></button></div><p className="mt-2 text-xs text-slate-600">{view.notes || "No note."}</p><div className="mt-2 text-[11px] text-slate-500">{view.selectedVariables.length} variables · {Object.keys(view.filters).length} filters · seed {view.settings.samplingSeed}</div>{stale ? <div className="mt-3 rounded-lg border border-amber-300 bg-white p-2 text-[11px] font-semibold text-amber-900"><AlertTriangle size={12} className="mr-1 inline" /> STALE_AUTHORITY — this view cannot be restored after the project dataset binding changed.</div> : <button type="button" onClick={() => restoreView(view)} className="mt-3 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white">Restore view</button>}</article>; })}</div> : <div className="mt-4 rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No saved views yet.</div>}</section><section className="rounded-2xl border border-slate-200 bg-white p-4"><h4 className="font-semibold text-slate-950">Bookmarked variables</h4>{bookmarks.length ? <div className="mt-3 flex flex-wrap gap-2">{bookmarks.map((name) => { const variable = variables.find((item) => item.name === name); return <span key={name} title={variable?.definition} className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 font-mono text-[11px] font-semibold text-amber-900"><Star size={11} fill="currentColor" />{name}</span>; })}</div> : <p className="mt-2 text-xs text-slate-500">Star variables in the explorer to collect a review list.</p>}<div className="mt-4 flex flex-wrap gap-2"><button type="button" onClick={() => handoff("features")} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700">Open Feature Engineering</button><button type="button" onClick={() => handoff("outliers")} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700">Open Outliers</button><button type="button" onClick={() => handoff("missing")} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700">Open Missing Values</button></div></section></div>;
}

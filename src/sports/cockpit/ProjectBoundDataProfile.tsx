import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
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
  FolderOpen,
  GitCompareArrows,
  ImageDown,
  LineChart,
  Loader2,
  Lock,
  Maximize2,
  Pencil,
  Plus,
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
import { CockpitDrawer } from "./CockpitDrawer";
import { Stage3DistributionGallery } from "./Stage3DistributionGallery";
import { useCockpitStore } from "./cockpitApi";
import type { CurrentGoldReviewState } from "../workflow/currentGoldDataReview";
import {
  compactProjectEdaFilters,
  downloadAggregatedCsv,
  projectEdaVariableSelection,
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

type TabId = "target" | "distributions" | "relationships" | "time" | "players";
type LegacyTabId = TabId | "overview" | "missingness" | "saved";
type RelationshipMode = "association" | "scatter" | "pairwise";
type ScatterDisplayMode = "scatter" | "hexbin";
type DistributionMode = "histogram" | "density" | "ecdf" | "box" | "violin";
type MissingnessMode = "missingness" | "outliers";
type StratifyBy = "" | "outcome" | "season" | "month";
type AssociationMethod = "auto" | "pearson" | "spearman";
type PlayerRole = "both" | "batter" | "pitcher";
type PairwiseDiagonalMethod = "histogram" | "density";
type PairwiseCellMethod = "scatter" | "hexbin";
type TimeGranularity = "month" | "season";

type EdaView = {
  id: string;
  authorityKey: string;
  name: string;
  tab: LegacyTabId;
  selectedVariables: string[];
  filters: ProjectEdaFilters;
  settings: {
    distributionMode: DistributionMode;
    relationshipMode: RelationshipMode;
    scatterDisplayMode?: ScatterDisplayMode;
    missingnessMode?: MissingnessMode;
    bins: number;
    topN: number;
    logScale: boolean;
    stratifyBy: StratifyBy;
    associationMethod: AssociationMethod;
    samplingSeed: number;
    scatterX?: string;
    scatterY?: string;
    scatterTarget?: string;
    pairwiseDiagonalMethod?: PairwiseDiagonalMethod;
    pairwiseLowerMethod?: PairwiseCellMethod;
    pairwiseUpperMethod?: PairwiseCellMethod;
    timeGranularity?: TimeGranularity;
  };
  notes: string;
  savedAt: string;
};

type VariableBookmarks = { authorityKey: string; names: string[] };

const TABS: { id: TabId; number: number; label: string; purpose: string; icon: typeof BarChart3 }[] = [
  { id: "target", number: 1, label: "Target & Class Balance", purpose: "Understand the prediction target and its stability.", icon: TableProperties },
  { id: "distributions", number: 2, label: "Distributions", purpose: "Review every candidate variable and its outcome-stratified shape.", icon: BarChart3 },
  { id: "relationships", number: 3, label: "Relationships", purpose: "Inspect associations, interactions, redundancy, and pairwise structure.", icon: GitCompareArrows },
  { id: "time", number: 4, label: "Time & Stability", purpose: "Identify seasonal patterns, drift, and source-era changes.", icon: CalendarRange },
  { id: "players", number: 5, label: "Players & Cold Start", purpose: "Understand low-history batters and pitchers.", icon: Users },
];

// Saved analyses created by the previous eight-tab workbench remain reopenable.
// These labels are migration metadata, not primary navigation.
const LEGACY_TABS: { id: LegacyTabId; label: string; reopenAs: TabId }[] = [
  { id: "overview", label: "Overview", reopenAs: "target" },
  { id: "missingness", label: "Missingness & Outliers", reopenAs: "distributions" },
  { id: "saved", label: "Saved Views", reopenAs: "target" },
];

function reopenTab(tab: LegacyTabId | string): TabId {
  if (TABS.some((item) => item.id === tab)) return tab as TabId;
  return LEGACY_TABS.find((item) => item.id === tab)?.reopenAs ?? "target";
}

const TARGET_ORDER = ["STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE", "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH"];
const DEFAULT_SEED = 7_310_2026;
const BOOKMARKS_KEY = "stage3.eda.variableBookmarks";
const SAVED_VIEWS_KEY = "stage3.eda.savedViews";
const CURRENT_CONTEXT_KEY = "stage3.eda.currentContext";
const RELATIONSHIP_DEFAULT_NAMES = ["batter_avg", "batter_obp", "batter_slg", "pitcher_era9", "pitcher_whip", "pitcher_so_per_bfp"] as const;
const RELATIONSHIP_PRESET_LABELS = [
  "Batter performance",
  "Pitcher performance",
  "Batter versus pitcher",
  "Recent form",
  "Simulation state",
  "Calendar",
  "Rest and travel",
  "Circadian",
  "Division and repeat opponent",
  "Core Gold-48 subset",
] as const;

const palette = ["#0891b2", "#2563eb", "#7c3aed", "#db2777", "#ea580c", "#ca8a04", "#059669", "#475569"];

function int(value: number | null | undefined) {
  return Number(value ?? 0).toLocaleString();
}

function pct(value: number | null | undefined) {
  return `${Number(value ?? 0).toFixed(1)}%`;
}

function isNumericVariable(variable: ProjectEdaVariable | undefined): boolean {
  return Boolean(variable && /numeric|int|float|double|number/i.test(variable.dataType));
}

function deterministicVariables(variables: ProjectEdaVariable[]): ProjectEdaVariable[] {
  return [...variables].sort((left, right) => `${left.featureFamily}\u0000${left.role}\u0000${left.name}`.localeCompare(`${right.featureFamily}\u0000${right.role}\u0000${right.name}`));
}

function relationshipDefaultNames(variables: ProjectEdaVariable[], maxVariables: number): string[] {
  const eligible = deterministicVariables(variables.filter((variable) => variable.selectable && isNumericVariable(variable)));
  const byName = new Map(eligible.map((variable) => [variable.name, variable]));
  const reservedExactNames = new Set<string>(RELATIONSHIP_DEFAULT_NAMES.filter((name) => byName.has(name)));
  const chosen: ProjectEdaVariable[] = [];
  const used = new Set<string>();
  const add = (variable: ProjectEdaVariable | undefined) => {
    if (!variable || used.has(variable.name) || chosen.length >= maxVariables) return;
    chosen.push(variable);
    used.add(variable.name);
  };

  for (const requested of RELATIONSHIP_DEFAULT_NAMES) {
    const exact = byName.get(requested);
    if (exact) {
      add(exact);
      continue;
    }
    const entity = requested.startsWith("batter_") ? "batter" : "pitcher";
    add(eligible.find((variable) => !used.has(variable.name) && !reservedExactNames.has(variable.name) && variable.core && variable.role === "PREGAME_FEATURE" && variable.name.startsWith(`${entity}_`)));
  }
  for (const variable of eligible.filter((item) => item.role === "PREGAME_FEATURE" && item.core)) add(variable);
  for (const variable of eligible.filter((item) => item.role === "PREGAME_FEATURE")) add(variable);
  for (const variable of eligible) add(variable);
  return chosen.slice(0, Math.min(maxVariables, RELATIONSHIP_DEFAULT_NAMES.length)).map((variable) => variable.name);
}

function relationshipPresetNames(label: string, variables: ProjectEdaVariable[], maxVariables: number): string[] {
  const eligible = deterministicVariables(variables.filter((variable) => variable.selectable));
  const matches = (pattern: RegExp) => eligible.filter((variable) => pattern.test(`${variable.name} ${variable.featureFamily}`));
  let selected: ProjectEdaVariable[] = [];
  if (label === "Batter performance") selected = eligible.filter((variable) => variable.name.startsWith("batter_"));
  else if (label === "Pitcher performance") selected = eligible.filter((variable) => variable.name.startsWith("pitcher_"));
  else if (label === "Batter versus pitcher") {
    const batter = eligible.filter((variable) => variable.name.startsWith("batter_")).slice(0, Math.ceil(maxVariables / 2));
    const pitcher = eligible.filter((variable) => variable.name.startsWith("pitcher_")).slice(0, Math.floor(maxVariables / 2));
    selected = [...batter, ...pitcher];
  } else if (label === "Recent form") selected = matches(/recent|last100|last250|rolling|decay/i);
  else if (label === "Simulation state") selected = eligible.filter((variable) => variable.role === "SIMULATION_GENERATED_STATE");
  else if (label === "Calendar") selected = matches(/calendar|day_of_week|month|holiday|weekend|start_hour|series_/i);
  else if (label === "Rest and travel") selected = matches(/rest|travel|road_trip|home_stand|previous_game|games_last|doubleheader/i);
  else if (label === "Circadian") selected = matches(/circadian|body_clock|time_zone|eastward|westward|morning_/i);
  else if (label === "Division and repeat opponent") selected = matches(/division|interleague|same_league|repeat_opponent|series_rematch|rivalry/i);
  else if (label === "Core Gold-48 subset") selected = eligible.filter((variable) => variable.core);
  return selected.slice(0, maxVariables).map((variable) => variable.name);
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
  const [expandedChart, setExpandedChart] = useState<ECharts | null>(null);
  const [expanded, setExpanded] = useState(false);
  const expandTriggerRef = useRef<HTMLButtonElement>(null);
  const capture = useCallback((instance: ECharts) => setChart(instance), []);
  const captureExpanded = useCallback((instance: ECharts) => setExpandedChart(instance), []);
  return (
    <>
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h4 className="font-semibold text-slate-950">{title}</h4><p className="mt-0.5 text-xs leading-5 text-slate-500">{description}</p></div>
          <div className="flex gap-1">
            <button type="button" aria-label={`Reset ${title} zoom and brush`} title="Reset zoom and brush" onClick={() => { chart?.dispatchAction({ type: "dataZoom", start: 0, end: 100 }); chart?.dispatchAction({ type: "brush", command: "clear", areas: [] }); }} className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50"><RotateCcw size={14} /></button>
            <button ref={expandTriggerRef} type="button" aria-haspopup="dialog" aria-expanded={expanded} aria-label={`Expand ${title} full screen`} title="Expand chart" onClick={() => setExpanded(true)} className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50"><Maximize2 size={14} /></button>
            <button type="button" aria-label={`Download ${title} image`} title="Download chart image" disabled={!chart} onClick={() => chart && exportChartAsPng(chart, `${title.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}.png`)} className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50 disabled:opacity-40"><ImageDown size={14} /></button>
            <button type="button" aria-label={`Download ${title} aggregated data`} title="Download aggregated chart data" disabled={!exportRows.length} onClick={() => downloadAggregatedCsv(`${title.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}.csv`, exportRows)} className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50 disabled:opacity-40"><Download size={14} /></button>
          </div>
        </div>
        <div className="mt-3"><EvidenceStrip envelope={envelope} /><EChartsPanel option={option} state={option ? "ready" : "empty"} height={310} ariaLabel={ariaLabel} onChartReady={capture} /></div>
      </section>
      <CockpitDrawer open={expanded} onClose={() => { setExpanded(false); setExpandedChart(null); }} title={title} description={`${description} Full-screen development-only analytical view.`} returnFocusRef={expandTriggerRef} widthClassName="max-w-none" testId="stage3-fullscreen-chart" footer={<div className="flex flex-wrap justify-end gap-2"><button type="button" onClick={() => { expandedChart?.dispatchAction({ type: "dataZoom", start: 0, end: 100 }); expandedChart?.dispatchAction({ type: "brush", command: "clear", areas: [] }); }} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700">Reset zoom and brush</button><button type="button" disabled={!expandedChart} onClick={() => expandedChart && exportChartAsPng(expandedChart, `${title.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}.png`)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40">Download image</button><button type="button" disabled={!exportRows.length} onClick={() => downloadAggregatedCsv(`${title.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}.csv`, exportRows)} className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">Download data</button></div>}>
        <div className="p-4 sm:p-5"><EvidenceStrip envelope={envelope} /><EChartsPanel option={option} state={option ? "ready" : "empty"} height={Math.max(460, (globalThis.innerHeight || 800) - 230)} ariaLabel={`${ariaLabel}, full-screen view`} onChartReady={captureExpanded} /></div>
      </CockpitDrawer>
    </>
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
    <details className="relative rounded-xl border border-slate-200 bg-white/95 shadow-sm backdrop-blur" data-testid="stage3-eda-global-filters">
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
      <div className="mx-3 mb-3 flex flex-wrap items-center gap-2">{active ? <button type="button" onClick={() => setFilters({})} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"><X size={12} /> Clear all filters</button> : null}<span className="text-[10px] text-slate-500">Feature-family filtering is available in the Add Variable picker because it scopes variables, not population rows.</span></div>
    </details>
  );
}

function PlayerColdStartControls({ role, setRole, filters, setFilters, metadata }: { role: PlayerRole; setRole: (next: PlayerRole) => void; filters: ProjectEdaFilters; setFilters: (next: ProjectEdaFilters) => void; metadata: { seasons: number[]; months: number[] } }) {
  const set = (key: keyof ProjectEdaFilters, value: unknown) => setFilters({ ...filters, [key]: value });
  return <section className="rounded-xl border border-cyan-200 bg-white p-3 shadow-sm" aria-label="Players and cold-start controls" data-testid="stage3-player-cold-start-controls">
    <div className="flex flex-wrap items-center gap-2"><Users size={15} className="text-cyan-700" /><span className="mr-2 text-xs font-semibold uppercase tracking-wide text-slate-700">Role and history population</span>{(["both", "batter", "pitcher"] as const).map((value) => <button key={value} type="button" aria-pressed={role === value} onClick={() => setRole(value)} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${role === value ? "bg-slate-900 text-white" : "border border-slate-200 bg-white text-slate-700"}`}>{value === "both" ? "Batters + pitchers" : value === "batter" ? "Batters" : "Pitchers"}</button>)}<span className="ml-auto text-[10px] text-slate-500">Development-only history evidence · cold-start rows are retained</span></div>
    <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-6"><select aria-label="Player history-sufficiency state" value={filters.historyStatus ?? ""} onChange={(event) => set("historyStatus", event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs"><option value="">All history states</option><option value="COLD_START">No prior history</option><option value="INSUFFICIENT_HISTORY">Insufficient history</option><option value="ESTABLISHED">Established history</option></select><MultiSelect label="Season" values={filters.seasons ?? []} options={metadata.seasons} onChange={(values) => set("seasons", values.map(Number))} /><MultiSelect label="Month" values={filters.months ?? []} options={metadata.months} onChange={(values) => set("months", values.map(Number))} />{role !== "pitcher" ? <input aria-label="Cold-start batting team filter" value={filters.battingTeam ?? ""} onChange={(event) => set("battingTeam", event.target.value)} placeholder="Batting team canonical ID" className="rounded-lg border border-slate-300 px-3 py-2 text-xs" /> : null}{role !== "batter" ? <input aria-label="Cold-start fielding team filter" value={filters.fieldingTeam ?? ""} onChange={(event) => set("fieldingTeam", event.target.value)} placeholder="Fielding team canonical ID" className="rounded-lg border border-slate-300 px-3 py-2 text-xs" /> : null}{role !== "pitcher" ? <input aria-label="Cold-start batter filter" value={filters.batter ?? ""} onChange={(event) => set("batter", event.target.value)} placeholder="Batter canonical ID" className="rounded-lg border border-slate-300 px-3 py-2 text-xs" /> : null}{role !== "batter" ? <input aria-label="Cold-start pitcher filter" value={filters.pitcher ?? ""} onChange={(event) => set("pitcher", event.target.value)} placeholder="Pitcher canonical ID" className="rounded-lg border border-slate-300 px-3 py-2 text-xs" /> : null}</div>
  </section>;
}

function VariablePickerDrawer({ open, close, returnFocusRef, variables, selected, setSelected, bookmarked, toggleBookmark, maxVariables }: { open: boolean; close: () => void; returnFocusRef: RefObject<HTMLElement>; variables: ProjectEdaVariable[]; selected: string[]; setSelected: (next: string[]) => void; bookmarked: string[]; toggleBookmark: (name: string) => void; maxVariables: number }) {
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("");
  const [family, setFamily] = useState("");
  const [contractTier, setContractTier] = useState("");
  const [sourceLineage, setSourceLineage] = useState("");
  const [availabilityEra, setAvailabilityEra] = useState("");
  const [dataType, setDataType] = useState("");
  const [category, setCategory] = useState("");
  const [missingness, setMissingness] = useState("");
  const [warningStatus, setWarningStatus] = useState("");
  const [bookmarksOnly, setBookmarksOnly] = useState(false);
  const [showNonselectable, setShowNonselectable] = useState(false);
  const [inspectedName, setInspectedName] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const families = [...new Set(variables.map((variable) => variable.featureFamily))].sort();
  const roles = [...new Set(variables.map((variable) => variable.role))].sort();
  const dataTypes = [...new Set(variables.map((variable) => variable.dataType))].sort();
  const categories = [...new Set(variables.map((variable) => variable.category))].sort();
  const sourceLineages = [...new Set(variables.map((variable) => variable.sourceLineage))].sort();
  const availabilityEras = [...new Set(variables.map((variable) => variable.availabilityEra))].sort();
  const filtered = variables.filter((variable) =>
    (showNonselectable || variable.selectable) &&
    (!search || `${variable.name} ${variable.label} ${variable.definition} ${variable.featureFamily} ${variable.sourceLineage} ${variable.pointInTimeTreatment} ${variable.availabilityEra} ${variable.proxyWarning ?? ""}`.toLowerCase().includes(search.toLowerCase())) &&
    (!role || variable.role === role) && (!family || variable.featureFamily === family) &&
    (!contractTier || (contractTier === "CORE" ? variable.core : !variable.core)) &&
    (!sourceLineage || variable.sourceLineage === sourceLineage) &&
    (!availabilityEra || variable.availabilityEra === availabilityEra) &&
    (!dataType || variable.dataType === dataType) && (!category || variable.category === category) &&
    (!missingness || (missingness === "MISSING" ? variable.missingPercent > 0 : variable.missingPercent === 0)) &&
    (!warningStatus || (warningStatus === "WARNING" ? Boolean(variable.proxyWarning) : !variable.proxyWarning)) &&
    (!bookmarksOnly || bookmarked.includes(variable.name)),
  );
  const inspected = variables.find((variable) => variable.name === inspectedName) ?? variables.find((variable) => variable.name === selected[0]) ?? filtered[0];

  useEffect(() => {
    if (!open || inspectedName || !inspected) return;
    setInspectedName(inspected.name);
  }, [inspected, inspectedName, open]);

  const addAndClose = (variable: ProjectEdaVariable) => {
    if (!variable.selectable || selected.includes(variable.name) || selected.length >= maxVariables) return;
    setSelected([...selected, variable.name]);
    close();
  };

  const resetFilters = () => {
    setSearch(""); setRole(""); setFamily(""); setContractTier(""); setSourceLineage(""); setAvailabilityEra(""); setDataType(""); setCategory(""); setMissingness(""); setWarningStatus(""); setBookmarksOnly(false); setShowNonselectable(false);
  };

  return (
    <CockpitDrawer
      open={open}
      onClose={close}
      title="Add a variable"
      eyebrow="Variable explorer"
      description="Search the governed predictor contract. Model-selectable predictors appear by default; metadata remains inspectable only after the explicit toggle."
      initialFocusRef={searchRef}
      returnFocusRef={returnFocusRef}
      widthClassName="max-w-4xl"
      testId="stage3-eda-variable-picker"
      footer={<div className="flex flex-wrap items-center gap-2"><span className="mr-auto text-xs text-slate-600" aria-live="polite"><b>{selected.length}</b> of {maxVariables} selected · {filtered.length} visible candidates</span><button type="button" onClick={resetFilters} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700">Reset picker filters</button><button type="button" onClick={close} className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white">Done</button></div>}
    >
      <div className="grid min-h-full min-w-0 lg:grid-cols-[minmax(0,1fr)_300px]">
        <section className="min-w-0 p-4 sm:p-5">
          <label htmlFor="stage3-variable-search" className="text-xs font-semibold text-slate-800">Search variables</label>
          <div className="relative mt-1"><Search size={14} className="pointer-events-none absolute left-3 top-2.5 text-slate-400" /><input ref={searchRef} id="stage3-variable-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name, definition, lineage, era, or warning" className="w-full rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm focus:border-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-100" /></div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <PickerSelect label="Role" value={role} setValue={setRole} options={roles} allLabel="All roles" />
            <PickerSelect label="Contract tier" value={contractTier} setValue={setContractTier} options={["CORE", "CONTEXT"]} allLabel="Core + contextual" optionLabel={(value) => value === "CORE" ? "Core Gold-48" : "Contextual"} />
            <PickerSelect label="Feature family" value={family} setValue={setFamily} options={families} allLabel="All feature families" />
            <PickerSelect label="Data type" value={dataType} setValue={setDataType} options={dataTypes} allLabel="All data types" />
            <PickerSelect label="Entity / category" value={category} setValue={setCategory} options={categories} allLabel="All entity / categories" />
            <PickerSelect label="Missingness" value={missingness} setValue={setMissingness} options={["MISSING", "COMPLETE"]} allLabel="Any missingness" optionLabel={(value) => value === "MISSING" ? "Has missing values" : "Physically complete"} />
            <PickerSelect label="Availability era" value={availabilityEra} setValue={setAvailabilityEra} options={availabilityEras} allLabel="All availability eras" />
            <PickerSelect label="Proxy / warning status" value={warningStatus} setValue={setWarningStatus} options={["WARNING", "CLEAR"]} allLabel="Warnings and clear" optionLabel={(value) => value === "WARNING" ? "Has proxy or warning" : "No proxy warning"} />
            <label className="sm:col-span-2 text-xs font-semibold text-slate-700">Exact source lineage<select value={sourceLineage} onChange={(event) => setSourceLineage(event.target.value)} className="mt-1 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-xs font-normal text-slate-800"><option value="">All governed sources</option>{sourceLineages.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-2.5 text-[11px] leading-4 text-slate-600"><input type="checkbox" checked={bookmarksOnly} onChange={(event) => setBookmarksOnly(event.target.checked)} className="mt-0.5" /><span><b>Bookmarked variables only</b><br />Use the existing project-scoped review list.</span></label>
            <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-2.5 text-[11px] leading-4 text-slate-600"><input type="checkbox" checked={showNonselectable} onChange={(event) => setShowNonselectable(event.target.checked)} className="mt-0.5" /><span><b>Show nonselectable metadata</b><br />Identifiers, targets, grouping, time, and lineage fields remain inspectable but cannot enter queries.</span></label>
          </div>
          <div className="mt-4 flex items-center justify-between text-[10px] font-semibold uppercase tracking-wide text-slate-500"><span>{filtered.length} variables</span><span>{selected.length}/{maxVariables} selected</span></div>
          <div className="mt-2 space-y-2" role="list" aria-label="Governed variables">
            {filtered.map((variable) => {
              const on = selected.includes(variable.name);
              const reason = projectEdaVariableSelection(variable);
              const atLimit = !on && selected.length >= maxVariables;
              const reasonId = `variable-reason-${variable.name.replaceAll(/[^a-zA-Z0-9_-]/g, "-")}`;
              return <article key={variable.name} role="listitem" className={`rounded-xl border p-3 ${inspected?.name === variable.name ? "border-cyan-400 bg-cyan-50/60" : on ? "border-cyan-200 bg-white" : "border-slate-200 bg-white"}`}>
                <div className="flex min-w-0 items-start gap-2">
                  <button type="button" onClick={() => setInspectedName(variable.name)} aria-pressed={inspected?.name === variable.name} className="min-w-0 flex-1 text-left focus:outline-none focus:ring-2 focus:ring-cyan-500"><div className="break-all font-mono text-xs font-semibold text-slate-900">{variable.name}</div><div className="mt-1 flex flex-wrap gap-1"><span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] text-slate-600">{variable.dataType}</span><span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] text-slate-600">{variable.role}</span><span className="rounded bg-cyan-50 px-1.5 py-0.5 text-[9px] text-cyan-700">{variable.core ? "CORE" : "CONTEXT"}</span>{on ? <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-700">SELECTED</span> : null}{!variable.selectable ? <span className="rounded bg-rose-50 px-1.5 py-0.5 text-[9px] text-rose-700">NONSELECTABLE</span> : null}{variable.proxyWarning ? <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[9px] text-amber-800">PROXY / WARNING</span> : null}</div><p id={reasonId} className={`mt-1 text-[10px] leading-4 ${reason.selectable ? "text-emerald-700" : "text-rose-700"}`}>{reason.label} · {reason.detail}</p></button>
                  <button type="button" aria-label={`${bookmarked.includes(variable.name) ? "Remove" : "Add"} bookmark for ${variable.name}`} aria-pressed={bookmarked.includes(variable.name)} onClick={() => toggleBookmark(variable.name)} className={`rounded-lg border p-2 ${bookmarked.includes(variable.name) ? "border-amber-300 bg-amber-50 text-amber-600" : "border-slate-200 text-slate-400 hover:text-amber-600"}`}><Star size={14} fill={bookmarked.includes(variable.name) ? "currentColor" : "none"} aria-hidden="true" /></button>
                  <button type="button" disabled={!variable.selectable || on || atLimit} aria-describedby={!variable.selectable ? reasonId : undefined} onClick={() => addAndClose(variable)} className="rounded-lg bg-cyan-800 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400">{on ? "Selected" : "Add"}</button>
                </div>
              </article>;
            })}
            {!filtered.length ? <div className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">No variables match these picker filters.</div> : null}
          </div>
        </section>
        <aside className="min-w-0 border-t border-slate-200 bg-slate-950 p-4 text-white lg:border-l lg:border-t-0">
          <div className="lg:sticky lg:top-4">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-cyan-300">Variable detail</div>
            {inspected ? <><div className="mt-1 break-all font-mono text-sm font-semibold">{inspected.name}</div><p className="mt-2 text-xs leading-5 text-slate-300">{inspected.definition}</p><dl className="mt-3 space-y-2 text-[11px]"><Info label="Selection reason" value={projectEdaVariableSelection(inspected).detail} /><Info label="Family" value={inspected.featureFamily} /><Info label="Source lineage" value={inspected.sourceLineage} /><Info label="Point-in-time" value={inspected.pointInTimeTreatment} /><Info label="Availability era" value={inspected.availabilityEra} /><Info label="Missingness" value={pct(inspected.missingPercent)} /><Info label="Unique values" value={inspected.uniqueCount === null ? "Not reported" : int(inspected.uniqueCount)} /><Info label="Selectable" value={inspected.selectable ? "Yes — descriptive review only" : "No — governance locked"} /></dl>{inspected.proxyWarning ? <div className="mt-3 rounded-lg border border-amber-400/30 bg-amber-300/10 p-2 text-[11px] leading-4 text-amber-100"><AlertTriangle size={12} className="mr-1 inline" />{inspected.proxyWarning}</div> : null}</> : <p className="mt-2 text-xs text-slate-400">Choose a variable to inspect its definition and authority.</p>}
          </div>
        </aside>
      </div>
    </CockpitDrawer>
  );
}

function PickerSelect({ label, value, setValue, options, allLabel, optionLabel = (item) => item }: { label: string; value: string; setValue: (value: string) => void; options: string[]; allLabel: string; optionLabel?: (value: string) => string }) {
  return <label className="text-xs font-semibold text-slate-700">{label}<select value={value} onChange={(event) => setValue(event.target.value)} className="mt-1 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-xs font-normal text-slate-800"><option value="">{allLabel}</option>{options.map((item) => <option key={item} value={item}>{optionLabel(item)}</option>)}</select></label>;
}

function Info({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-slate-500">{label}</dt><dd className="mt-0.5 break-words text-slate-200">{value}</dd></div>;
}

function SelectedVariableTray({ section, variables, selectedNames, setSelectedNames, maxVariables, bookmarked, toggleBookmark, pickerOpen, openPicker, restoreDefaults }: { section: "Distribution" | "Relationship" | "Stability"; variables: ProjectEdaVariable[]; selectedNames: string[]; setSelectedNames: (next: string[]) => void; maxVariables: number; bookmarked: string[]; toggleBookmark: (name: string) => void; pickerOpen: boolean; openPicker: (trigger: HTMLButtonElement) => void; restoreDefaults?: () => void }) {
  const [familyPreset, setFamilyPreset] = useState("");
  const selected = selectedNames.map((name) => variables.find((variable) => variable.name === name)).filter((variable): variable is ProjectEdaVariable => Boolean(variable));
  const families = [...new Set(variables.filter((variable) => variable.selectable).map((variable) => variable.featureFamily))].sort();
  const applyPreset = (label: string) => {
    const next = relationshipPresetNames(label, variables, maxVariables);
    if (next.length) setSelectedNames(next);
  };
  const applyFamily = () => {
    if (!familyPreset) return;
    setSelectedNames(deterministicVariables(variables.filter((variable) => variable.selectable && variable.featureFamily === familyPreset)).slice(0, maxVariables).map((variable) => variable.name));
  };
  const moveSelected = (index: number, direction: -1 | 1) => {
    const destination = index + direction;
    if (destination < 0 || destination >= selectedNames.length) return;
    const reordered = [...selectedNames];
    [reordered[index], reordered[destination]] = [reordered[destination], reordered[index]];
    setSelectedNames(reordered);
  };
  return (
    <section className="rounded-xl border border-cyan-200 bg-gradient-to-r from-cyan-50 via-white to-slate-50 p-2.5 shadow-sm" data-testid="stage3-eda-selected-variable-tray">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-cyan-800">{section} variables {section === "Relationship" ? <span className="normal-case tracking-normal text-slate-500">· Selected-variable tray</span> : null}</span>
        <span className="rounded-full bg-cyan-800 px-2 py-0.5 text-[10px] font-semibold text-white">{selected.length}/{maxVariables}</span>
        <div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto py-0.5" role="list" aria-label="Ordered selected variables">
          {selected.map((variable, index) => { const reason = projectEdaVariableSelection(variable); const bookmarkedVariable = bookmarked.includes(variable.name); return <div role="listitem" key={variable.name} title={`${reason.label}: ${reason.detail}`} className="group flex shrink-0 items-center gap-1.5 rounded-lg border border-cyan-200 bg-white px-2 py-1.5 shadow-sm"><span className="rounded-full bg-cyan-800 px-1.5 py-0.5 text-[9px] font-semibold text-white">{index + 1}</span><span className="font-mono text-[10px] font-semibold text-slate-800">{variable.name}</span><button type="button" disabled={index === 0} aria-label={`Move ${variable.name} earlier`} onClick={() => moveSelected(index, -1)} className="text-slate-400 hover:text-cyan-700 disabled:opacity-25">←</button><button type="button" disabled={index === selected.length - 1} aria-label={`Move ${variable.name} later`} onClick={() => moveSelected(index, 1)} className="text-slate-400 hover:text-cyan-700 disabled:opacity-25">→</button><button type="button" aria-label={`${bookmarkedVariable ? "Remove" : "Add"} bookmark for ${variable.name}`} aria-pressed={bookmarkedVariable} onClick={() => toggleBookmark(variable.name)} className={bookmarkedVariable ? "text-amber-500" : "text-slate-300 hover:text-amber-500"}><Star size={11} fill={bookmarkedVariable ? "currentColor" : "none"} /></button><button type="button" aria-label={`Remove ${variable.name} from selected variables`} onClick={() => setSelectedNames(selectedNames.filter((name) => name !== variable.name))} className="text-slate-300 hover:text-rose-600"><X size={11} /></button></div>; })}
          {!selected.length ? <span className="self-center text-[11px] text-slate-500">None selected · Target remains available</span> : null}
        </div>
        <button type="button" aria-haspopup="dialog" aria-expanded={pickerOpen} onClick={(event) => openPicker(event.currentTarget)} className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-cyan-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-cyan-800"><Plus size={13} /> Add variable</button>
        {restoreDefaults ? <button type="button" onClick={restoreDefaults} className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-cyan-300 bg-white px-2 py-1.5 text-xs font-semibold text-cyan-800"><RotateCcw size={12} /> Restore default set</button> : null}
        <button type="button" disabled={!selected.length} onClick={() => setSelectedNames([])} className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs font-semibold text-slate-600 disabled:opacity-40"><X size={13} /> Clear all</button>
      </div>
      {section === "Relationship" ? <p className="mt-2 text-[11px] font-medium text-cyan-900">Suggested starting set — customize as needed.</p> : null}
      <details className="mt-2 border-t border-cyan-100 pt-2"><summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-wide text-slate-500">Feature-family and quick presets · Maximum {maxVariables}</summary><div className="mt-2 flex flex-wrap items-center gap-2"><select aria-label="Feature family preset" value={familyPreset} onChange={(event) => setFamilyPreset(event.target.value)} className="min-w-48 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs"><option value="">Feature-family preset…</option>{families.map((family) => <option key={family}>{family}</option>)}</select><button type="button" disabled={!familyPreset} onClick={applyFamily} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 disabled:opacity-40">Apply family</button>{RELATIONSHIP_PRESET_LABELS.map((label) => { const enabled = relationshipPresetNames(label, variables, maxVariables).length > 0; return <button key={label} type="button" disabled={!enabled} onClick={() => applyPreset(label)} className="rounded-full border border-slate-200 bg-white px-2 py-1 text-[10px] hover:border-cyan-300 hover:text-cyan-800 disabled:cursor-not-allowed disabled:opacity-40">{label}</button>; })}<span className="ml-auto text-[10px] text-slate-500">Nonselectable metadata is never added.</span></div></details>
    </section>
  );
}

function TimeComparisonControls({ filters, setFilters, granularity, setGranularity }: { filters: ProjectEdaFilters; setFilters: (next: ProjectEdaFilters) => void; granularity: TimeGranularity; setGranularity: (next: TimeGranularity) => void }) {
  const setStartDate = (startDate: string) => setFilters({
    ...filters,
    startDate: startDate || undefined,
    endDate: startDate && filters.endDate && filters.endDate < startDate ? startDate : filters.endDate,
  });
  const setEndDate = (endDate: string) => setFilters({
    ...filters,
    startDate: endDate && filters.startDate && filters.startDate > endDate ? endDate : filters.startDate,
    endDate: endDate || undefined,
  });
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm" aria-label="Time and stability comparison periods" data-testid="stage3-time-comparison-controls">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-56 flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">Comparison-period controls</div>
          <p className="mt-1 text-xs leading-5 text-slate-600">Compare contiguous development periods using the same project-bound filters. The earliest included period is the baseline; each later period is evaluated through the selected development end date.</p>
        </div>
        <label className="text-[10px] font-semibold uppercase text-slate-500">Period grouping<select aria-label="Stability comparison period grouping" value={granularity} onChange={(event) => setGranularity(event.target.value as TimeGranularity)} className="mt-1 block min-w-36 rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-normal normal-case text-slate-800"><option value="month">Monthly periods</option><option value="season">Season periods</option></select></label>
        <label className="text-[10px] font-semibold uppercase text-slate-500">Comparison start<input aria-label="Stability comparison start date" type="date" value={filters.startDate ?? ""} max="2026-08-13" onChange={(event) => setStartDate(event.target.value)} className="mt-1 block rounded-lg border border-slate-200 px-2.5 py-2 text-xs font-normal text-slate-800" /></label>
        <label className="text-[10px] font-semibold uppercase text-slate-500">Comparison end<input aria-label="Stability comparison end date" type="date" value={filters.endDate ?? ""} max="2026-08-13" onChange={(event) => setEndDate(event.target.value)} className="mt-1 block rounded-lg border border-slate-200 px-2.5 py-2 text-xs font-normal text-slate-800" /></label>
        <button type="button" onClick={() => setFilters({ ...filters, startDate: undefined, endDate: undefined })} disabled={!filters.startDate && !filters.endDate} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40">Use full development window</button>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-[10px]"><span className="rounded-full bg-slate-900 px-2 py-1 font-semibold text-white">DEVELOPMENT ONLY</span><span className="rounded-full border border-cyan-200 bg-cyan-50 px-2 py-1 text-cyan-900">PSI + KS remain descriptive</span><span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-amber-900">Final OOT locked after 2026-08-13</span></div>
    </section>
  );
}

export function ProjectBoundDataProfile({ state, projectId, go }: { state: CurrentGoldReviewState; projectId: string; go: (id: string) => void }) {
  const { notes, setNote } = useCockpitStore();
  const authorityKey = state.review
    ? [state.review.sourceAuthority.manifestSha, state.review.goldAuthority.manifestSha, state.review.contextualFeaturePack?.manifestSha256 ?? "no-context", state.review.reviewDigest].join(":")
    : "authority-pending";
  const metadata = useProjectEdaMetadata(projectId, authorityKey, state.status === "ready" && Boolean(state.review));
  const [activeTab, setActiveTab] = useState<TabId>("target");
  const [selectedVariables, setSelectedVariables] = useState<string[]>([]);
  const [filters, setFilters] = useState<ProjectEdaFilters>({});
  const [distributionMode, setDistributionMode] = useState<DistributionMode>("histogram");
  const [relationshipMode, setRelationshipMode] = useState<RelationshipMode>("association");
  const [scatterDisplayMode, setScatterDisplayMode] = useState<ScatterDisplayMode>("scatter");
  const [bins, setBins] = useState(30);
  const [topN, setTopN] = useState(20);
  const [logScale, setLogScale] = useState(false);
  const [stratifyBy, setStratifyBy] = useState<StratifyBy>("");
  const [associationMethod, setAssociationMethod] = useState<AssociationMethod>("auto");
  const [samplingSeed, setSamplingSeed] = useState(DEFAULT_SEED);
  const [scatterX, setScatterX] = useState("");
  const [scatterY, setScatterY] = useState("");
  const [scatterTarget, setScatterTarget] = useState("");
  const [pairwiseDiagonalMethod, setPairwiseDiagonalMethod] = useState<PairwiseDiagonalMethod>("histogram");
  const [pairwiseLowerMethod, setPairwiseLowerMethod] = useState<PairwiseCellMethod>("scatter");
  const [pairwiseUpperMethod, setPairwiseUpperMethod] = useState<PairwiseCellMethod>("hexbin");
  const [timeGranularity, setTimeGranularity] = useState<TimeGranularity>("month");
  const [playerRole, setPlayerRole] = useState<PlayerRole>("both");
  const [viewName, setViewName] = useState("");
  const [viewNotes, setViewNotes] = useState("");
  const [activeDrawer, setActiveDrawer] = useState<"variables" | "saved" | null>(null);
  const drawerReturnFocusRef = useRef<HTMLElement | null>(null);
  const [contextHydratedAuthority, setContextHydratedAuthority] = useState("");
  const previousAuthority = useRef("");
  const relationshipDefaultsAppliedAuthority = useRef("");
  const sectionSelectionsAuthority = useRef("");
  const relationshipSelection = useRef<string[]>([]);
  const stabilitySelection = useRef<string[]>([]);
  const storedBookmarks = parseStored<VariableBookmarks | string[]>(notes[BOOKMARKS_KEY], { authorityKey, names: [] });
  const bookmarks = !Array.isArray(storedBookmarks) && storedBookmarks.authorityKey === authorityKey ? storedBookmarks.names : [];
  const savedViews = parseStored<EdaView[]>(notes[SAVED_VIEWS_KEY], []).filter((view) => view && typeof view === "object" && typeof view.id === "string");
  const variables = metadata.value?.data.variables ?? [];
  const maxVariables = metadata.value?.data.queryLimits.maxVariables ?? 6;

  useEffect(() => {
    if (!variables.length || contextHydratedAuthority === authorityKey) return;
    const stored = parseStored<{ authorityKey: string; activeTab: LegacyTabId; selectedVariables: string[]; filters: ProjectEdaFilters } | null>(notes[CURRENT_CONTEXT_KEY], null);
    const selectable = new Set(variables.filter((variable) => variable.selectable).map((variable) => variable.name));
    if (stored?.authorityKey === authorityKey) {
      // Ordinary entry always begins with the decision-oriented target review.
      // Explicit saved-analysis reopen is the only action that restores another tab.
      setActiveTab("target");
      setSelectedVariables((stored.selectedVariables ?? []).filter((name) => selectable.has(name)).slice(0, maxVariables));
      setFilters(stored.filters ?? {});
    } else {
      const defaults = (metadata.value?.data.decisionGuidance?.defaultStabilityVariables ?? [])
        .filter((name) => selectable.has(name) && name !== "context_inning")
        .slice(0, maxVariables);
      const initial = variables.find((variable) => variable.selectable && isNumericVariable(variable) && variable.name !== "context_inning") ?? variables.find((variable) => variable.selectable);
      setActiveTab("target");
      setSelectedVariables(defaults.length ? defaults : initial ? [initial.name] : []);
      setFilters({});
    }
    previousAuthority.current = authorityKey;
    setContextHydratedAuthority(authorityKey);
  }, [authorityKey, contextHydratedAuthority, maxVariables, metadata.value, notes, variables]);

  useEffect(() => {
    if (contextHydratedAuthority !== authorityKey || previousAuthority.current !== authorityKey) return;
    const value = JSON.stringify({ authorityKey, activeTab, selectedVariables, filters: compactProjectEdaFilters(filters) });
    if (notes[CURRENT_CONTEXT_KEY] !== value) setNote(CURRENT_CONTEXT_KEY, value);
  }, [activeTab, authorityKey, contextHydratedAuthority, filters, notes, selectedVariables, setNote]);

  const selected = selectedVariables.map((name) => variables.find((variable) => variable.name === name)).filter((variable): variable is ProjectEdaVariable => Boolean(variable));
  const primary = selected[0];
  const selectedNumeric = selected.filter(isNumericVariable);
  const relationshipDefaults = useMemo(() => relationshipDefaultNames(variables, maxVariables), [maxVariables, variables]);
  const stabilityDefaults = useMemo(() => (metadata.value?.data.decisionGuidance.defaultStabilityVariables ?? [])
    .filter((name) => variables.some((variable) => variable.name === name && variable.selectable) && name !== "context_inning")
    .slice(0, maxVariables), [maxVariables, metadata.value, variables]);

  useEffect(() => {
    if (!variables.length || sectionSelectionsAuthority.current === authorityKey) return;
    relationshipSelection.current = relationshipDefaults;
    stabilitySelection.current = stabilityDefaults;
    sectionSelectionsAuthority.current = authorityKey;
  }, [authorityKey, relationshipDefaults, stabilityDefaults, variables.length]);

  const assignRelationshipSelection = useCallback((names: string[]) => {
    const governed = names.filter((name) => variables.some((variable) => variable.name === name && variable.selectable)).slice(0, maxVariables);
    const numeric = governed.filter((name) => isNumericVariable(variables.find((variable) => variable.name === name)));
    setSelectedVariables(governed);
    setScatterX(numeric[0] ?? "");
    setScatterY(numeric[1] ?? "");
    setScatterTarget("");
  }, [maxVariables, variables]);

  const setSectionVariables = useCallback((names: string[]) => {
    if (activeTab === "relationships") {
      relationshipSelection.current = names;
      assignRelationshipSelection(names);
    } else {
      if (activeTab === "time") stabilitySelection.current = names;
      setSelectedVariables(names);
    }
  }, [activeTab, assignRelationshipSelection]);

  const selectAnalyticalTab = (tab: TabId) => {
    if (activeTab === "relationships") relationshipSelection.current = selectedVariables;
    if (activeTab === "time") stabilitySelection.current = selectedVariables;
    if (tab === "relationships") {
      const firstRelationshipEntry = relationshipDefaultsAppliedAuthority.current !== authorityKey;
      if (tab === "relationships" && relationshipDefaultsAppliedAuthority.current !== authorityKey) relationshipDefaultsAppliedAuthority.current = authorityKey;
      assignRelationshipSelection(firstRelationshipEntry ? relationshipDefaults : relationshipSelection.current.length ? relationshipSelection.current : relationshipDefaults);
    } else if (tab === "time") {
      setSelectedVariables(stabilitySelection.current.length ? stabilitySelection.current : stabilityDefaults);
    }
    setActiveTab(tab);
  };

  const restoreRelationshipDefaults = () => {
    relationshipDefaultsAppliedAuthority.current = authorityKey;
    relationshipSelection.current = relationshipDefaults;
    assignRelationshipSelection(relationshipDefaults);
  };

  useEffect(() => {
    const numericNames = selectedNumeric.map((variable) => variable.name);
    const nextX = numericNames.includes(scatterX) ? scatterX : numericNames[0] ?? "";
    const nextY = numericNames.includes(scatterY) && scatterY !== nextX ? scatterY : numericNames.find((name) => name !== nextX) ?? "";
    if (nextX !== scatterX) setScatterX(nextX);
    if (nextY !== scatterY) setScatterY(nextY);
    if (scatterTarget && scatterTarget !== "outcome" && !selectedVariables.includes(scatterTarget)) setScatterTarget("");
  }, [scatterTarget, scatterX, scatterY, selectedNumeric, selectedVariables]);

  const relationshipVariables = relationshipMode === "scatter"
    ? [...new Set([scatterX, scatterY, scatterDisplayMode === "scatter" && scatterTarget !== "outcome" ? scatterTarget : ""].filter(Boolean))]
    : selectedVariables.slice(0, maxVariables);
  const relationshipPreviewVariables = selectedVariables.slice(0, maxVariables);
  const relationshipPreviewReady = relationshipPreviewVariables.length >= 2;
  const relationshipReady = relationshipMode === "scatter"
    ? Boolean(scatterX && scatterY && scatterX !== scatterY)
    : relationshipVariables.length >= 2;
  const query = useMemo<ProjectEdaQuery | null>(() => {
    if (!metadata.value) return null;
    if (activeTab === "target") return { queryType: "overview", filters, variables: [] };
    if (activeTab === "distributions") return null; // The all-variable gallery owns bounded, lazy per-card queries.
    if (activeTab === "relationships") return relationshipMode === "scatter" && relationshipReady ? { filters, variables: relationshipVariables, queryType: "pairwise_sample", settings: { seed: samplingSeed, sampleSize: Math.min(2500, metadata.value.data.queryLimits.maxSampleRows), mode: relationshipMode, method: associationMethod, scatterX, scatterY, scatterTarget: scatterDisplayMode === "scatter" ? scatterTarget || undefined : undefined, stratifyBy: scatterDisplayMode === "scatter" && scatterTarget === "outcome" ? "outcome" : undefined } } : null;
    if (activeTab === "time") {
      const requested = selectedVariables.filter((name) => name !== "context_inning").slice(0, maxVariables);
      return requested.length ? { filters, variables: requested, queryType: "temporal", settings: { granularity: timeGranularity, driftMethods: ["PSI", "KS"] } } : null;
    }
    return { filters, variables: [], queryType: "cold_start" };
  }, [metadata.value, activeTab, filters, relationshipMode, relationshipReady, relationshipVariables, associationMethod, samplingSeed, scatterDisplayMode, scatterX, scatterY, scatterTarget, selectedVariables, maxVariables, timeGranularity]);
  const analytical = useProjectEdaQuery<unknown>(projectId, authorityKey, query);
  const relationshipAssociationQuery = useMemo<ProjectEdaQuery | null>(() => activeTab === "relationships" && relationshipPreviewReady
    ? { filters, variables: relationshipPreviewVariables, queryType: "association", settings: { method: associationMethod } }
    : null, [activeTab, associationMethod, filters, relationshipPreviewReady, relationshipPreviewVariables]);
  const relationshipPairwiseQuery = useMemo<ProjectEdaQuery | null>(() => activeTab === "relationships" && relationshipPreviewReady && metadata.value
    ? { filters, variables: relationshipPreviewVariables, queryType: "pairwise_sample", settings: { seed: samplingSeed, sampleSize: Math.min(2500, metadata.value.data.queryLimits.maxSampleRows), mode: "pairwise" } }
    : null, [activeTab, filters, metadata.value, relationshipPreviewReady, relationshipPreviewVariables, samplingSeed]);
  const relationshipAssociationPreview = useProjectEdaQuery<AssociationData>(projectId, authorityKey, relationshipAssociationQuery);
  const relationshipPairwisePreview = useProjectEdaQuery<PairwiseData>(projectId, authorityKey, relationshipPairwiseQuery);

  const toggleBookmark = (name: string) => setNote(BOOKMARKS_KEY, JSON.stringify({ authorityKey, names: bookmarks.includes(name) ? bookmarks.filter((item) => item !== name) : [...bookmarks, name] } satisfies VariableBookmarks));
  const persistViews = (next: EdaView[]) => setNote(SAVED_VIEWS_KEY, JSON.stringify(next));
  const snapshotView = (id: string, name: string, notesValue: string): EdaView => ({
    id,
    authorityKey,
    name,
    tab: activeTab,
    selectedVariables,
    filters: compactProjectEdaFilters(filters),
    settings: { distributionMode, relationshipMode, scatterDisplayMode, bins, topN, logScale, stratifyBy, associationMethod, samplingSeed, scatterX, scatterY, scatterTarget: scatterTarget || undefined, pairwiseDiagonalMethod, pairwiseLowerMethod, pairwiseUpperMethod, timeGranularity },
    notes: notesValue,
    savedAt: new Date().toISOString(),
  });
  const saveView = () => {
    const name = viewName.trim() || `${TABS.find((tab) => tab.id === activeTab)?.label} · ${new Date().toLocaleDateString()}`;
    persistViews([...savedViews, snapshotView(globalThis.crypto?.randomUUID?.() ?? `${Date.now()}`, name, viewNotes.trim())]);
    setViewName(""); setViewNotes("");
  };
  const updateView = (id: string) => persistViews(savedViews.map((view) => view.id === id ? snapshotView(id, view.name, view.notes) : view));
  const renameView = (id: string, name: string) => persistViews(savedViews.map((view) => view.id === id ? { ...view, name: name.trim() || view.name, savedAt: new Date().toISOString() } : view));
  const removeView = (id: string) => persistViews(savedViews.filter((view) => view.id !== id));
  const openDrawer = (drawer: "variables" | "saved", trigger: HTMLElement) => {
    drawerReturnFocusRef.current = trigger;
    setActiveDrawer(drawer);
  };
  const restoreView = (view: EdaView) => {
    if (view.authorityKey !== authorityKey) return;
    const settings = view.settings ?? {} as EdaView["settings"];
    const selectable = new Set(variables.filter((variable) => variable.selectable).map((variable) => variable.name));
    if (reopenTab(view.tab) === "relationships") {
      relationshipDefaultsAppliedAuthority.current = authorityKey;
      relationshipSelection.current = (view.selectedVariables ?? []).filter((name) => selectable.has(name)).slice(0, maxVariables);
    }
    if (reopenTab(view.tab) === "time") stabilitySelection.current = (view.selectedVariables ?? []).filter((name) => selectable.has(name)).slice(0, maxVariables);
    setActiveTab(reopenTab(view.tab)); setSelectedVariables((view.selectedVariables ?? []).filter((name) => selectable.has(name)).slice(0, maxVariables)); setFilters(view.filters ?? {}); setDistributionMode(settings.distributionMode ?? "histogram"); setRelationshipMode(settings.relationshipMode ?? "association"); setScatterDisplayMode(settings.scatterDisplayMode ?? "scatter"); setBins(settings.bins ?? 30); setTopN(settings.topN ?? 20); setLogScale(settings.logScale ?? false); setStratifyBy(settings.stratifyBy ?? ""); setAssociationMethod(settings.associationMethod ?? "auto"); setSamplingSeed(settings.samplingSeed ?? DEFAULT_SEED); setScatterX(settings.scatterX ?? ""); setScatterY(settings.scatterY ?? ""); setScatterTarget(settings.scatterTarget ?? ""); setPairwiseDiagonalMethod(settings.pairwiseDiagonalMethod ?? "histogram"); setPairwiseLowerMethod(settings.pairwiseLowerMethod ?? "scatter"); setPairwiseUpperMethod(settings.pairwiseUpperMethod ?? "hexbin"); setTimeGranularity(settings.timeGranularity ?? "month"); setActiveDrawer(null);
  };
  const handoff = (destination: "outliers" | "missing" | "features") => {
    setNote("stage3.eda.handoff", JSON.stringify({ destination, selectedVariables, bookmarkedVariables: bookmarks, filters: compactProjectEdaFilters(filters), authorityKey, sourceTab: activeTab, createdAt: new Date().toISOString() }));
    go(destination);
  };
  const handoffVariable = (name: string, destination: "outliers" | "missing" | "features") => {
    setNote("stage3.eda.handoff", JSON.stringify({ destination, selectedVariables: [name], bookmarkedVariables: bookmarks, filters: compactProjectEdaFilters(filters), authorityKey, sourceTab: "distributions", createdAt: new Date().toISOString() }));
    go(destination);
  };

  if (state.status === "loading" || state.status === "idle" || metadata.status === "loading" || metadata.status === "idle") return <QueryStatus status="loading" error={null} />;
  if (state.status === "error" || !state.review) return <QueryStatus status="error" error={state.error || "Project-bound Stage 3 authority unavailable."} />;
  if (metadata.status === "error" || !metadata.value) return <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6"><QueryStatus status="error" error={metadata.error} /><button type="button" onClick={() => void metadata.refresh()} className="mx-auto mt-3 flex items-center gap-2 rounded-lg bg-rose-900 px-3 py-2 text-xs font-semibold text-white"><RefreshCw size={13} />Retry metadata</button></div>;

  const meta = metadata.value.data;
  return (
    <div className="space-y-4" data-testid="stage3-project-bound-eda-workbench">
      <section className="stage3-flow-controls relative z-10 space-y-2 rounded-2xl border border-slate-200 bg-slate-100/95 p-1.5 shadow-lg backdrop-blur" data-testid="stage3-eda-sticky-controls">
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[10px] font-semibold text-amber-900"><Lock size={12} aria-hidden="true" /> Final OOT locked · Targets excluded from every EDA query <span className="ml-auto font-medium text-slate-600">Development-only EDA; no read can fit or score a model.</span></div>
        <div className="flex items-center gap-2 rounded-xl bg-white p-1 shadow-sm"><nav className="grid min-w-0 flex-1 grid-flow-col auto-cols-[minmax(180px,1fr)] gap-1 overflow-x-auto" aria-label="Stage 3 analytical sections" data-testid="stage3-eda-section-nav">{TABS.map((tab) => <button type="button" key={tab.id} onClick={() => selectAnalyticalTab(tab.id)} aria-current={activeTab === tab.id ? "page" : undefined} aria-controls="stage3-active-analytical-section" aria-description={tab.purpose} title={`${tab.label}: ${tab.purpose}`} className={`group flex min-w-44 items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:ring-offset-1 ${activeTab === tab.id ? "bg-slate-900 text-white shadow-sm" : "border border-transparent text-slate-700 hover:border-slate-200 hover:bg-slate-50"}`}><span className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-xs font-bold tabular-nums ${activeTab === tab.id ? "bg-cyan-400/20 text-cyan-200" : "bg-slate-100 text-slate-500 group-hover:bg-cyan-50 group-hover:text-cyan-700"}`}>{tab.number}</span><tab.icon size={15} className={activeTab === tab.id ? "text-cyan-300" : "text-slate-400"} /><span className="min-w-0"><span className="block text-xs font-semibold leading-4">{tab.label}</span><span className={`mt-0.5 hidden text-[9px] leading-3 xl:block ${activeTab === tab.id ? "text-slate-300" : "text-slate-500"}`}>{tab.purpose}</span></span></button>)}</nav><button type="button" aria-haspopup="dialog" aria-expanded={activeDrawer === "saved"} onClick={(event) => openDrawer("saved", event.currentTarget)} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs font-semibold text-cyan-900"><Bookmark size={14} /> Saved <span className="rounded-full bg-cyan-800 px-1.5 py-0.5 text-[9px] text-white">{savedViews.filter((view) => view.authorityKey === authorityKey).length}</span></button></div>
        <GlobalFilters filters={filters} setFilters={setFilters} metadata={meta.filterOptions} />
      </section>

      <main id="stage3-active-analytical-section" className="min-w-0 space-y-4">
          {activeTab === "distributions" ? <Stage3DistributionGallery projectId={projectId} authorityKey={authorityKey} variables={variables} families={meta.families} filters={filters} taxonomy={meta.targetTaxonomy} bookmarks={bookmarks} toggleBookmark={toggleBookmark} handoff={handoffVariable} /> : null}
          {activeTab === "relationships" ? <section className="space-y-2" aria-label="Relationship controls" data-testid="stage3-relationship-local-selection"><SelectedVariableTray section="Relationship" variables={variables} selectedNames={selectedVariables} setSelectedNames={setSectionVariables} maxVariables={maxVariables} bookmarked={bookmarks} toggleBookmark={toggleBookmark} pickerOpen={activeDrawer === "variables"} openPicker={(trigger) => openDrawer("variables", trigger)} restoreDefaults={restoreRelationshipDefaults} /><WorkbenchControls tab={activeTab} primary={primary} selected={selected} distributionMode={distributionMode} setDistributionMode={setDistributionMode} relationshipMode={relationshipMode} setRelationshipMode={setRelationshipMode} scatterDisplayMode={scatterDisplayMode} setScatterDisplayMode={setScatterDisplayMode} associationMethod={associationMethod} setAssociationMethod={setAssociationMethod} bins={bins} setBins={setBins} topN={topN} setTopN={setTopN} logScale={logScale} setLogScale={setLogScale} stratifyBy={stratifyBy} setStratifyBy={setStratifyBy} seed={samplingSeed} setSeed={setSamplingSeed} limits={meta.queryLimits} scatterX={scatterX} setScatterX={setScatterX} scatterY={scatterY} setScatterY={setScatterY} scatterTarget={scatterTarget} setScatterTarget={setScatterTarget} pairwiseDiagonalMethod={pairwiseDiagonalMethod} setPairwiseDiagonalMethod={setPairwiseDiagonalMethod} pairwiseLowerMethod={pairwiseLowerMethod} setPairwiseLowerMethod={setPairwiseLowerMethod} pairwiseUpperMethod={pairwiseUpperMethod} setPairwiseUpperMethod={setPairwiseUpperMethod} /></section> : null}
          {activeTab === "time" ? <section className="space-y-2" aria-label="Time and stability controls"><SelectedVariableTray section="Stability" variables={variables} selectedNames={selectedVariables} setSelectedNames={setSectionVariables} maxVariables={maxVariables} bookmarked={bookmarks} toggleBookmark={toggleBookmark} pickerOpen={activeDrawer === "variables"} openPicker={(trigger) => openDrawer("variables", trigger)} /><TimeComparisonControls filters={filters} setFilters={setFilters} granularity={timeGranularity} setGranularity={setTimeGranularity} /></section> : null}
          {activeTab === "players" ? <PlayerColdStartControls role={playerRole} setRole={setPlayerRole} filters={filters} setFilters={setFilters} metadata={meta.filterOptions} /> : null}
          {activeTab === "time" && !primary ? <div className="rounded-2xl border border-dashed border-cyan-300 bg-cyan-50/40 p-10 text-center"><BarChart3 size={24} className="mx-auto text-cyan-700" /><div className="mt-3 font-semibold text-slate-900">Select a stability variable</div><p className="mt-1 text-sm text-slate-600">Use the compact Stability variables control or a feature-family preset. No analytical request has been sent.</p></div> : null}
          {activeTab === "relationships" && !relationshipPreviewReady ? <div className="rounded-2xl border border-dashed border-cyan-300 bg-cyan-50/40 p-10 text-center"><GitCompareArrows size={24} className="mx-auto text-cyan-700" /><div className="mt-3 font-semibold text-slate-900">Choose 2–6 relationship variables</div><p className="mt-1 text-sm text-slate-600">The association heatmap and pairwise matrix use exactly the ordered variables shown in the Relationship variables tray. No request has been sent.</p></div> : null}
          {activeTab === "relationships" && relationshipMode === "scatter" && relationshipPreviewReady && !relationshipReady ? <div className="rounded-2xl border border-dashed border-cyan-300 bg-cyan-50/40 p-6 text-center"><GitCompareArrows size={22} className="mx-auto text-cyan-700" /><div className="mt-2 font-semibold text-slate-900">Assign distinct numeric X and Y variables</div><p className="mt-1 text-xs text-slate-600">The optional color / target assignment may be any selected variable. Axes are never inferred from hidden metadata.</p></div> : null}
          {query && analytical.status !== "ready" ? <QueryStatus status={analytical.status} error={analytical.error} /> : null}
          {activeTab === "relationships" && relationshipMode === "scatter" && analytical.value ? <RelationshipsTab envelope={analytical.value as ProjectEdaEnvelope<PairwiseData>} mode="scatter" scatterDisplayMode={scatterDisplayMode} scatterX={scatterX} scatterY={scatterY} scatterTarget={scatterTarget} /> : null}
          {activeTab === "relationships" && relationshipPreviewReady ? <section className="space-y-4" aria-label="Immediate relationship previews" data-testid="stage3-relationship-immediate-previews"><div className="rounded-xl border border-cyan-200 bg-cyan-50 p-3"><div className="text-xs font-semibold uppercase tracking-wide text-cyan-900">Immediate governed previews</div><p className="mt-1 text-xs leading-5 text-cyan-900">The selected 2–6 variables populate both the association heatmap and deterministic pairwise matrix. The focused-view control above remains available for scatter or hexbin work.</p></div><div data-testid="stage3-relationship-association-preview">{relationshipAssociationPreview.status !== "ready" ? <QueryStatus status={relationshipAssociationPreview.status} error={relationshipAssociationPreview.error} /> : null}{relationshipAssociationPreview.value ? <RelationshipsTab envelope={relationshipAssociationPreview.value} mode="association" scatterDisplayMode={scatterDisplayMode} scatterX={scatterX} scatterY={scatterY} scatterTarget={scatterTarget} /> : null}</div><div data-testid="stage3-relationship-pairwise-preview">{relationshipPairwisePreview.status !== "ready" ? <QueryStatus status={relationshipPairwisePreview.status} error={relationshipPairwisePreview.error} /> : null}{relationshipPairwisePreview.value ? <RelationshipsTab envelope={relationshipPairwisePreview.value} mode="pairwise" scatterDisplayMode={scatterDisplayMode} scatterX={scatterX} scatterY={scatterY} scatterTarget={scatterTarget} pairwiseDiagonalMethod={pairwiseDiagonalMethod} pairwiseLowerMethod={pairwiseLowerMethod} pairwiseUpperMethod={pairwiseUpperMethod} /> : null}</div></section> : null}
          {activeTab !== "relationships" && analytical.value ? <TabContent tab={activeTab} relationshipMode={relationshipMode} scatterDisplayMode={scatterDisplayMode} distributionMode={distributionMode} logScale={logScale} envelope={analytical.value} taxonomy={meta.targetTaxonomy} variables={selected} scatterX={scatterX} scatterY={scatterY} scatterTarget={scatterTarget} playerRole={playerRole} handoff={handoff} /> : null}
          <section className="rounded-2xl border border-slate-200 bg-white p-3" data-testid="stage3-eda-chart-toolbar"><div className="flex flex-wrap items-center gap-2"><div><div className="text-xs font-semibold text-slate-800">Save or hand off this analysis</div><p className="mt-0.5 text-[11px] text-slate-500">The compact drawer stores the exact variable order, relationship assignments, filters, settings, seed, and notes.</p></div><button type="button" aria-haspopup="dialog" aria-expanded={activeDrawer === "saved"} onClick={(event) => openDrawer("saved", event.currentTarget)} className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-cyan-800 px-3 py-2 text-xs font-semibold text-white"><Save size={13} /> Save analysis</button><button type="button" onClick={() => handoff("outliers")} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700">Open in Outliers</button><button type="button" onClick={() => handoff("missing")} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700">Open in Missing Values</button></div></section>
      </main>
      <VariablePickerDrawer open={activeDrawer === "variables"} close={() => setActiveDrawer(null)} returnFocusRef={drawerReturnFocusRef} variables={variables} selected={selectedVariables} setSelected={setSectionVariables} bookmarked={bookmarks} toggleBookmark={toggleBookmark} maxVariables={maxVariables} />
      <SavedAnalysesDrawer open={activeDrawer === "saved"} close={() => setActiveDrawer(null)} returnFocusRef={drawerReturnFocusRef} views={savedViews} authorityKey={authorityKey} bookmarks={bookmarks} variables={variables} selectedVariables={selectedVariables} setSelectedVariables={setSelectedVariables} maxVariables={maxVariables} viewName={viewName} setViewName={setViewName} viewNotes={viewNotes} setViewNotes={setViewNotes} saveView={saveView} restoreView={restoreView} renameView={renameView} updateView={updateView} removeView={removeView} toggleBookmark={toggleBookmark} handoff={handoff} />
    </div>
  );
}

function WorkbenchControls({ tab, primary, selected, distributionMode, setDistributionMode, relationshipMode, setRelationshipMode, scatterDisplayMode, setScatterDisplayMode, associationMethod, setAssociationMethod, bins, setBins, topN, setTopN, logScale, setLogScale, stratifyBy, setStratifyBy, seed, setSeed, limits, scatterX, setScatterX, scatterY, setScatterY, scatterTarget, setScatterTarget, pairwiseDiagonalMethod, setPairwiseDiagonalMethod, pairwiseLowerMethod, setPairwiseLowerMethod, pairwiseUpperMethod, setPairwiseUpperMethod }: { tab: TabId; primary?: ProjectEdaVariable; selected: ProjectEdaVariable[]; distributionMode: DistributionMode; setDistributionMode: (value: DistributionMode) => void; relationshipMode: RelationshipMode; setRelationshipMode: (value: RelationshipMode) => void; scatterDisplayMode: ScatterDisplayMode; setScatterDisplayMode: (value: ScatterDisplayMode) => void; associationMethod: AssociationMethod; setAssociationMethod: (value: AssociationMethod) => void; bins: number; setBins: (value: number) => void; topN: number; setTopN: (value: number) => void; logScale: boolean; setLogScale: (value: boolean) => void; stratifyBy: StratifyBy; setStratifyBy: (value: StratifyBy) => void; seed: number; setSeed: (value: number) => void; limits: { maxBins: number; maxCategories: number; maxVariables: number; maxSampleRows: number }; scatterX: string; setScatterX: (value: string) => void; scatterY: string; setScatterY: (value: string) => void; scatterTarget: string; setScatterTarget: (value: string) => void; pairwiseDiagonalMethod: PairwiseDiagonalMethod; setPairwiseDiagonalMethod: (value: PairwiseDiagonalMethod) => void; pairwiseLowerMethod: PairwiseCellMethod; setPairwiseLowerMethod: (value: PairwiseCellMethod) => void; pairwiseUpperMethod: PairwiseCellMethod; setPairwiseUpperMethod: (value: PairwiseCellMethod) => void }) {
  if (!["distributions", "relationships", "time"].includes(tab)) return null;
  const numeric = selected.filter(isNumericVariable);
  return <section className="rounded-xl border border-slate-200 bg-white p-2.5 shadow-sm"><div className="flex flex-wrap items-center gap-2"><SlidersHorizontal size={15} className="text-cyan-700" /><span className="mr-2 text-xs font-semibold uppercase tracking-wide text-slate-600">Chart controls</span>{tab === "distributions" ? <><select aria-label="Distribution chart type" value={distributionMode} onChange={(event) => setDistributionMode(event.target.value as DistributionMode)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs"><option value="histogram">Histogram</option><option value="density">Smoothed density</option><option value="ecdf">ECDF</option><option value="box">Box plot</option><option value="violin">Violin plot</option></select><label className="flex items-center gap-1 text-xs">Bins<input type="range" min={10} max={limits.maxBins} value={bins} onChange={(event) => setBins(Number(event.target.value))} />{bins}</label><label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={logScale} onChange={(event) => setLogScale(event.target.checked)} /> Log scale</label><label className="flex items-center gap-1 text-xs">Optional stratification variable<select value={stratifyBy} onChange={(event) => setStratifyBy(event.target.value as StratifyBy)} className="rounded border border-slate-200 px-2 py-1"><option value="">None</option><option value="outcome">Outcome</option><option value="season">Season</option><option value="month">Month</option></select></label><label className="flex items-center gap-1 text-xs">Top N<input type="number" min={3} max={limits.maxCategories} value={topN} onChange={(event) => setTopN(Number(event.target.value))} className="w-14 rounded border border-slate-200 px-1 py-1" /></label></> : null}{tab === "relationships" ? <><select aria-label="Relationship view" value={relationshipMode} onChange={(event) => setRelationshipMode(event.target.value as RelationshipMode)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs"><option value="association">Association heatmap</option><option value="scatter">Scatter / density</option><option value="pairwise">Pairwise matrix</option></select>{relationshipMode === "association" ? <select aria-label="Association method" value={associationMethod} onChange={(event) => setAssociationMethod(event.target.value as AssociationMethod)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs"><option value="auto">Method: auto by type</option><option value="pearson">Pearson (numeric)</option><option value="spearman">Spearman (numeric)</option></select> : <label className="flex items-center gap-1 text-xs">Seed<input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} className="w-28 rounded border border-slate-200 px-2 py-1" /></label>}<span className="text-[11px] text-slate-500">{selected.length}/{limits.maxVariables} selected · max {int(limits.maxSampleRows)} sampled rows</span></> : null}{tab === "time" ? <span className="text-xs text-slate-600">Monthly development evidence · PSI and KS are descriptive only</span> : null}<span className="ml-auto truncate text-[11px] text-slate-500">Primary variable: <b className="font-mono text-slate-700">{primary?.name || "select a variable"}</b></span></div>
    {tab === "relationships" ? <div className="mt-3 border-t border-slate-100 pt-3">
      {relationshipMode === "scatter" ? <div className="grid gap-2 md:grid-cols-4"><label className="text-[10px] font-semibold uppercase text-slate-500">Display<select aria-label="Scatter display" value={scatterDisplayMode} onChange={(event) => setScatterDisplayMode(event.target.value as ScatterDisplayMode)} className="mt-1 block w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs normal-case text-slate-800"><option value="scatter">Scatter points</option><option value="hexbin">Hexbin density</option></select></label><label className="text-[10px] font-semibold uppercase text-slate-500">Scatter X<select aria-label="Scatter X variable" value={scatterX} onChange={(event) => setScatterX(event.target.value)} className="mt-1 block w-full rounded-lg border border-slate-200 bg-white px-2 py-2 font-mono text-xs normal-case text-slate-800"><option value="">Choose numeric X…</option>{numeric.map((variable) => <option key={variable.name} value={variable.name} disabled={variable.name === scatterY}>{variable.name}</option>)}</select></label><label className="text-[10px] font-semibold uppercase text-slate-500">Scatter Y<select aria-label="Scatter Y variable" value={scatterY} onChange={(event) => setScatterY(event.target.value)} className="mt-1 block w-full rounded-lg border border-slate-200 bg-white px-2 py-2 font-mono text-xs normal-case text-slate-800"><option value="">Choose numeric Y…</option>{numeric.map((variable) => <option key={variable.name} value={variable.name} disabled={variable.name === scatterX}>{variable.name}</option>)}</select></label><label className="text-[10px] font-semibold uppercase text-slate-500">Optional target stratification<select aria-label="Optional scatter target" value={scatterTarget} onChange={(event) => setScatterTarget(event.target.value)} disabled={scatterDisplayMode === "hexbin"} className="mt-1 block w-full rounded-lg border border-slate-200 bg-white px-2 py-2 font-mono text-xs normal-case text-slate-800 disabled:bg-slate-100"><option value="">None — single series</option><option value="outcome">Governed outcome · development only</option>{selected.filter((variable) => ![scatterX, scatterY].includes(variable.name) && !isNumericVariable(variable)).map((variable) => <option key={variable.name} value={variable.name}>{variable.name}</option>)}</select></label><p className="md:col-span-4 text-[10px] leading-4 text-slate-500">X and Y are explicit and numeric. Hexbin density aggregates the same deterministic development-only sample and disables target color. Optional outcome stratification is never treated as a predictor; final-OOT targets are never requested.</p></div> : <><div className="flex flex-wrap items-center gap-2 text-[11px]"><span className="font-semibold text-slate-700">{relationshipMode === "association" ? "Heatmap rows and columns" : "Pairwise matrix variables"}:</span>{selected.map((variable, index) => <span key={variable.name} className="rounded-full border border-cyan-200 bg-cyan-50 px-2 py-1 font-mono text-cyan-900">{index + 1}. {variable.name}</span>)}{!selected.length ? <span className="text-slate-500">none selected</span> : null}<span className="ml-auto text-slate-500">Exactly this ordered set is queried (2–6 variables); numeric, categorical, and mixed pairs are rendered explicitly.</span></div>{relationshipMode === "pairwise" ? <div className="mt-3 grid gap-2 border-t border-slate-100 pt-3 sm:grid-cols-3" data-testid="stage3-pairwise-matrix-controls"><label className="text-[10px] font-semibold uppercase text-slate-500">Diagonal distribution method<select aria-label="Pairwise matrix diagonal distribution method" value={pairwiseDiagonalMethod} onChange={(event) => setPairwiseDiagonalMethod(event.target.value as PairwiseDiagonalMethod)} className="mt-1 block w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-normal normal-case text-slate-800"><option value="histogram">Histogram</option><option value="density">Smoothed density</option></select></label><label className="text-[10px] font-semibold uppercase text-slate-500">Lower-triangle cell method<select aria-label="Pairwise matrix lower triangle cell method" value={pairwiseLowerMethod} onChange={(event) => setPairwiseLowerMethod(event.target.value as PairwiseCellMethod)} className="mt-1 block w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-normal normal-case text-slate-800"><option value="scatter">Scatter points</option><option value="hexbin">Hexbin density</option></select></label><label className="text-[10px] font-semibold uppercase text-slate-500">Upper-triangle cell method<select aria-label="Pairwise matrix upper triangle cell method" value={pairwiseUpperMethod} onChange={(event) => setPairwiseUpperMethod(event.target.value as PairwiseCellMethod)} className="mt-1 block w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-normal normal-case text-slate-800"><option value="scatter">Scatter points</option><option value="hexbin">Hexbin density</option></select></label><p className="sm:col-span-3 text-[10px] leading-4 text-slate-500">Numeric cells use the selected triangle method. Categorical and mixed-type cells remain explicit type-aware count or strip views; no incompatible method is silently applied.</p></div> : null}</>}
    </div> : null}
  </section>;
}

function TabContent({ tab, envelope, distributionMode, logScale, relationshipMode, scatterDisplayMode, taxonomy, variables, scatterX, scatterY, scatterTarget, playerRole, handoff }: { tab: TabId; envelope: ProjectEdaEnvelope<unknown>; distributionMode: DistributionMode; logScale: boolean; relationshipMode: RelationshipMode; scatterDisplayMode: ScatterDisplayMode; taxonomy: string[]; variables: ProjectEdaVariable[]; scatterX: string; scatterY: string; scatterTarget: string; playerRole: PlayerRole; handoff: (destination: "outliers" | "missing" | "features") => void }) {
  if (tab === "target") return <TargetTab envelope={envelope as ProjectEdaEnvelope<OverviewData>} taxonomy={taxonomy} handoff={handoff} />;
  if (tab === "distributions") return <DistributionTab envelope={envelope as ProjectEdaEnvelope<DistributionData | CategoryCountsData>} mode={distributionMode} logScale={logScale} variable={variables[0]} />;
  if (tab === "relationships") return <RelationshipsTab envelope={envelope as ProjectEdaEnvelope<AssociationData | PairwiseData>} mode={relationshipMode} scatterDisplayMode={scatterDisplayMode} scatterX={scatterX} scatterY={scatterY} scatterTarget={scatterTarget} />;
  if (tab === "time") return <TemporalTab envelope={envelope as ProjectEdaEnvelope<TemporalData>} />;
  return <ColdStartTab envelope={envelope as ProjectEdaEnvelope<ColdStartData>} role={playerRole} />;
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
    return <div className="space-y-4"><DistributionPrimeSummary envelope={envelope} variable={variable} mode={mode} categoryCount={data.categories.length} /><ChartCard title={`${data.variable} category distribution`} description="Top categories with bounded other grouping and explicit missing category." option={categoryOption} ariaLabel={`Categorical distribution of ${data.variable}`} envelope={envelope} exportRows={rowsFrom(data.categories)} /><div className="grid gap-3 sm:grid-cols-2"><Metric label="Missing category" value={int(data.missingCount)} detail="never silently dropped" accent="amber" /><Metric label="Other categories" value={int(data.otherCount)} detail="bounded top-N aggregation" /></div></div>;
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
  return <div className="space-y-4"><DistributionPrimeSummary envelope={envelope} variable={variable} mode={mode} statistics={data.statistics} /><ChartCard title={`${mode === "violin" ? "Violin" : mode[0].toUpperCase() + mode.slice(1)} · ${data.variable}`} description={`${variable?.definition || "Selected numeric variable"} Tooltips, zoom, brush/reset, image and aggregated-data export are available.`} option={option} ariaLabel={`${mode} distribution of ${data.variable}`} envelope={envelope} exportRows={exportRows} /><section className="rounded-2xl border border-slate-200 bg-white p-4"><h4 className="font-semibold text-slate-950">Summary statistics and percentiles</h4><div className="mt-3 grid gap-2 sm:grid-cols-3 xl:grid-cols-6">{stats.map(([name, value]) => <div key={name} className="rounded-lg bg-slate-50 p-2"><div className="text-[10px] uppercase text-slate-500">{name}</div><div className="mt-1 font-mono text-xs font-semibold text-slate-800">{value === null ? "NA" : Number(value).toLocaleString(undefined, { maximumFractionDigits: 5 })}</div></div>)}</div></section>{data.stratified.length ? <section className="overflow-auto rounded-2xl border border-slate-200 bg-white p-4"><h4 className="font-semibold text-slate-950">Target / season strata</h4><table className="mt-3 w-full min-w-[600px] text-xs"><thead><tr className="text-left text-slate-500">{["Stratum", "Rows", "Mean", "Median", "Missing %"].map((label) => <th key={label} className="border-b px-2 py-2">{label}</th>)}</tr></thead><tbody>{data.stratified.map((row) => <tr key={row.stratum}><td className="border-b px-2 py-2 font-semibold">{row.stratum}</td><td className="border-b px-2 py-2">{int(row.count)}</td><td className="border-b px-2 py-2">{row.mean ?? "—"}</td><td className="border-b px-2 py-2">{row.median ?? "—"}</td><td className="border-b px-2 py-2">{pct(row.missingPercent)}</td></tr>)}</tbody></table></section> : null}</div>;
}

function DistributionPrimeSummary({ envelope, variable, mode, statistics, categoryCount }: { envelope: ProjectEdaEnvelope<DistributionData | CategoryCountsData>; variable?: ProjectEdaVariable; mode: DistributionMode; statistics?: Record<string, number | null>; categoryCount?: number }) {
  const mean = Number(statistics?.mean);
  const median = Number(statistics?.median);
  const standardDeviation = Number(statistics?.std ?? statistics?.standard_deviation);
  const skew = Number.isFinite(mean) && Number.isFinite(median) && Number.isFinite(standardDeviation) && standardDeviation > 0 ? (3 * (mean - median)) / standardDeviation : null;
  const skewLabel = skew === null ? "Not estimable" : Math.abs(skew) < 0.2 ? "Approximately symmetric" : skew > 0 ? `Right-skew proxy (${skew.toFixed(2)})` : `Left-skew proxy (${skew.toFixed(2)})`;
  const range = statistics && statistics.min !== null && statistics.max !== null && statistics.min !== undefined && statistics.max !== undefined ? `${Number(statistics.min).toLocaleString()} – ${Number(statistics.max).toLocaleString()}` : categoryCount === undefined ? "Not estimable" : `${int(categoryCount)} displayed categories`;
  return <section className="rounded-2xl border border-cyan-200 bg-cyan-50/50 p-4" data-testid="stage3-distribution-prime-summary"><div className="flex flex-wrap items-start gap-3"><div><div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-800">Distribution summary</div><h4 className="mt-1 font-semibold text-slate-950">{variable?.name ?? "Selected variable"}</h4></div><span className="ml-auto rounded-full border border-cyan-200 bg-white px-2.5 py-1 text-[10px] font-semibold text-cyan-900">{mode.toUpperCase()}</span></div><div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-5"><Metric label="Variable type" value={variable?.dataType ?? "Unknown"} detail={variable?.featureFamily ?? "Feature family unavailable"} /><Metric label="Development missing" value={pct(variable?.missingPercent)} detail={variable?.role ?? "Role unavailable"} accent={Number(variable?.missingPercent ?? 0) > 0 ? "amber" : "slate"} /><Metric label="Range / cardinality" value={range} detail="Development-only observed evidence" /><Metric label="Approximate shape" value={categoryCount === undefined ? skewLabel : "Categorical"} detail="Pearson median-skew proxy; descriptive only" /><Metric label="Rows represented" value={int(envelope.population.rowsRepresented)} detail={`${activeFilterCount(envelope)} active population filter(s)`} accent="cyan" /></div>{variable?.proxyWarning ? <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900"><b>Proxy warning:</b> {variable.proxyWarning}</p> : null}</section>;
}

type PairwiseCellChart = { option: EChartsOption | null; label: string; rows: number };

function pairwiseDiagonalChart(rows: PairwiseData["rows"], variable: string, method: PairwiseDiagonalMethod): PairwiseCellChart {
  const observed = rows.map((row) => row[variable]).filter((value) => value !== null && value !== undefined);
  const numeric = observed.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  if (!observed.length) return { option: null, label: `${method} · no observed values`, rows: 0 };
  if (numeric.length !== observed.length) {
    const counts = new Map<string, number>();
    observed.forEach((value) => counts.set(String(value), (counts.get(String(value)) ?? 0) + 1));
    const categories = [...counts.entries()].sort((left, right) => right[1] - left[1]).slice(0, 12);
    return { option: { grid: { left: 34, right: 8, top: 8, bottom: 42, containLabel: true }, tooltip: { trigger: "axis", confine: true }, xAxis: { type: "category", data: categories.map(([value]) => value), axisLabel: { rotate: 40, hideOverlap: true } }, yAxis: { type: "value", name: "Rows" }, series: [{ type: "bar", data: categories.map(([, count]) => count) }] }, label: "Categorical frequency fallback", rows: observed.length };
  }
  const minimum = Math.min(...numeric); const maximum = Math.max(...numeric);
  if (method === "density") {
    const mean = numeric.reduce((sum, value) => sum + value, 0) / numeric.length;
    const deviation = Math.sqrt(numeric.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(1, numeric.length - 1));
    const bandwidth = Math.max(Number.EPSILON, 1.06 * (deviation || Math.max(1, maximum - minimum) / 6) * numeric.length ** -0.2);
    const span = Math.max(Number.EPSILON, maximum - minimum); const points = Array.from({ length: 28 }, (_, index) => minimum + (span * index) / 27);
    const density = points.map((point) => numeric.reduce((sum, value) => sum + Math.exp(-0.5 * ((point - value) / bandwidth) ** 2), 0) / (numeric.length * bandwidth * Math.sqrt(2 * Math.PI)));
    return { option: { grid: { left: 36, right: 8, top: 8, bottom: 30, containLabel: true }, tooltip: { trigger: "axis", confine: true }, xAxis: { type: "value", scale: true }, yAxis: { type: "value", name: "Density" }, series: [{ type: "line", smooth: true, symbol: "none", areaStyle: { opacity: 0.22 }, data: points.map((point, index) => [point, density[index]]) }] }, label: "Smoothed density", rows: numeric.length };
  }
  const binCount = 14; const width = Math.max(Number.EPSILON, (maximum - minimum) / binCount); const counts = Array.from({ length: binCount }, () => 0);
  numeric.forEach((value) => { counts[Math.min(binCount - 1, Math.floor((value - minimum) / width))] += 1; });
  return { option: { grid: { left: 36, right: 8, top: 8, bottom: 38, containLabel: true }, tooltip: { trigger: "axis", confine: true }, xAxis: { type: "category", data: counts.map((_, index) => (minimum + (index + 0.5) * width).toPrecision(3)), axisLabel: { rotate: 40, hideOverlap: true } }, yAxis: { type: "value", name: "Rows" }, series: [{ type: "bar", data: counts }] }, label: "Histogram · 14 bins", rows: numeric.length };
}

function pairwiseOffDiagonalChart(rows: PairwiseData["rows"], x: string, y: string, method: PairwiseCellMethod): PairwiseCellChart {
  const complete = rows.filter((row) => row[x] !== null && row[x] !== undefined && row[y] !== null && row[y] !== undefined);
  if (!complete.length) return { option: null, label: `${method} · no complete pairs`, rows: 0 };
  const xNumeric = complete.every((row) => typeof row[x] === "number" && Number.isFinite(row[x]));
  const yNumeric = complete.every((row) => typeof row[y] === "number" && Number.isFinite(row[y]));
  if (xNumeric && yNumeric) {
    const points = complete.map((row) => [Number(row[x]), Number(row[y])]);
    if (method === "hexbin") {
      const xs = points.map(([value]) => value); const ys = points.map(([, value]) => value);
      const xMin = Math.min(...xs); const xMax = Math.max(...xs); const yMin = Math.min(...ys); const yMax = Math.max(...ys); const radius = 1 / 20;
      const bins = new Map<string, number>();
      points.forEach(([xValue, yValue]) => {
        const normalizedX = (xValue - xMin) / Math.max(Number.EPSILON, xMax - xMin); const normalizedY = (yValue - yMin) / Math.max(Number.EPSILON, yMax - yMin);
        const axialQ = ((Math.sqrt(3) / 3) * normalizedX - normalizedY / 3) / radius; const axialR = ((2 / 3) * normalizedY) / radius;
        let cubeX = Math.round(axialQ); let cubeZ = Math.round(axialR); const cubeY = Math.round(-axialQ - axialR);
        const xError = Math.abs(cubeX - axialQ); const yError = Math.abs(cubeY + axialQ + axialR); const zError = Math.abs(cubeZ - axialR);
        if (xError > yError && xError > zError) cubeX = -cubeY - cubeZ; else if (zError > yError) cubeZ = -cubeX - cubeY;
        const key = `${cubeX}:${cubeZ}`; bins.set(key, (bins.get(key) ?? 0) + 1);
      });
      const binned = [...bins.entries()].map(([key, count]) => { const [q, r] = key.split(":").map(Number); return [xMin + radius * Math.sqrt(3) * (q + r / 2) * (xMax - xMin), yMin + radius * 1.5 * r * (yMax - yMin), count]; });
      const maximumCount = Math.max(1, ...binned.map((value) => value[2]));
      return { option: { grid: { left: 38, right: 8, top: 8, bottom: 32, containLabel: true }, tooltip: { trigger: "item", confine: true }, visualMap: { show: false, min: 1, max: maximumCount, dimension: 2, inRange: { color: ["#cffafe", "#0891b2", "#164e63"] } }, xAxis: { type: "value", scale: true }, yAxis: { type: "value", scale: true }, series: [{ type: "scatter", symbol: "path://M0,-8 L6.93,-4 L6.93,4 L0,8 L-6.93,4 L-6.93,-4 Z", symbolSize: 10, data: binned }] }, label: `Hexbin density · ${binned.length} occupied bins`, rows: complete.length };
    }
    return { option: { grid: { left: 38, right: 8, top: 8, bottom: 32, containLabel: true }, tooltip: { trigger: "item", confine: true }, xAxis: { type: "value", scale: true }, yAxis: { type: "value", scale: true }, series: [{ type: "scatter", symbolSize: 4, large: complete.length > 1000, data: points, itemStyle: { opacity: 0.38 } }] }, label: "Scatter points", rows: complete.length };
  }
  if (!xNumeric && !yNumeric) {
    const xValues = [...new Set(complete.map((row) => String(row[x])))].sort().slice(0, 12); const yValues = [...new Set(complete.map((row) => String(row[y])))].sort().slice(0, 12);
    const xIndex = new Map(xValues.map((value, index) => [value, index])); const yIndex = new Map(yValues.map((value, index) => [value, index])); const counts = new Map<string, number>();
    complete.forEach((row) => { const xValue = String(row[x]); const yValue = String(row[y]); if (xIndex.has(xValue) && yIndex.has(yValue)) { const key = `${xValue}\u0000${yValue}`; counts.set(key, (counts.get(key) ?? 0) + 1); } });
    const cells = [...counts.entries()].map(([key, count]) => { const [xValue, yValue] = key.split("\u0000"); return [xIndex.get(xValue) ?? 0, yIndex.get(yValue) ?? 0, count]; });
    return { option: { grid: { left: 42, right: 8, top: 8, bottom: 42, containLabel: true }, tooltip: { trigger: "item", confine: true }, visualMap: { show: false, min: 0, max: Math.max(1, ...cells.map((cell) => Number(cell[2]))) }, xAxis: { type: "category", data: xValues, axisLabel: { rotate: 40, hideOverlap: true } }, yAxis: { type: "category", data: yValues, axisLabel: { hideOverlap: true } }, series: [{ type: "heatmap", data: cells }] }, label: "Type-aware categorical count heatmap", rows: complete.length };
  }
  const numericName = xNumeric ? x : y; const categoryName = xNumeric ? y : x; const categories = [...new Set(complete.map((row) => String(row[categoryName])))].sort().slice(0, 12);
  const values = complete.filter((row) => typeof row[numericName] === "number" && categories.includes(String(row[categoryName]))).map((row) => [String(row[categoryName]), Number(row[numericName])]);
  return { option: { grid: { left: 42, right: 8, top: 8, bottom: 42, containLabel: true }, tooltip: { trigger: "item", confine: true }, xAxis: { type: "category", data: categories, axisLabel: { rotate: 40, hideOverlap: true } }, yAxis: { type: "value", scale: true }, series: [{ type: "scatter", symbolSize: 4, large: values.length > 1000, data: values, itemStyle: { opacity: 0.38 } }] }, label: "Type-aware mixed strip plot", rows: values.length };
}

function PairwiseMatrix({ envelope, diagonalMethod, lowerMethod, upperMethod }: { envelope: ProjectEdaEnvelope<PairwiseData>; diagonalMethod: PairwiseDiagonalMethod; lowerMethod: PairwiseCellMethod; upperMethod: PairwiseCellMethod }) {
  const data = envelope.data;
  return <div className="space-y-4"><RelationshipPrimeSummary envelope={envelope} variables={data.variables} mode="pairwise" method={`diagonal ${diagonalMethod} · lower ${lowerMethod} · upper ${upperMethod}`} strongest={`${data.variables.length} × ${data.variables.length} literal matrix`} sample={`${int(data.sampleSize)} / ${int(data.populationSize)} · seed ${data.seed}`} /><section className="rounded-xl border border-cyan-200 bg-cyan-50 p-3 text-xs leading-5 text-cyan-900"><b>Literal pairwise-matrix contract:</b> diagonal cells use {diagonalMethod}; lower-triangle numeric cells use {lowerMethod}; upper-triangle numeric cells use {upperMethod}. Categorical and mixed cells disclose their type-aware fallback. Every cell uses the same deterministic development-only sample; final-OOT targets remain locked.</section><section className="overflow-x-auto rounded-2xl border border-slate-200 bg-white p-3" data-testid="stage3-literal-pairwise-matrix"><EvidenceStrip envelope={envelope} /><table className="border-separate border-spacing-2" style={{ minWidth: `${140 + data.variables.length * 230}px` }}><caption className="sr-only">Pairwise matrix with diagonal distributions, lower-triangle cells, and upper-triangle cells</caption><thead><tr><th scope="col" className="w-32 p-2 text-left text-[10px] uppercase text-slate-500">Y \ X</th>{data.variables.map((variable) => <th key={variable} scope="col" className="w-56 break-all p-2 text-left font-mono text-[10px] text-slate-700">{variable}</th>)}</tr></thead><tbody>{data.variables.map((y, rowIndex) => <tr key={y}><th scope="row" className="w-32 break-all p-2 text-left align-top font-mono text-[10px] text-slate-700">{y}</th>{data.variables.map((x, columnIndex) => { const region = rowIndex === columnIndex ? "Diagonal" : rowIndex > columnIndex ? "Lower triangle" : "Upper triangle"; const chart = rowIndex === columnIndex ? pairwiseDiagonalChart(data.rows, x, diagonalMethod) : pairwiseOffDiagonalChart(data.rows, x, y, rowIndex > columnIndex ? lowerMethod : upperMethod); return <td key={`${y}:${x}`} className="w-56 rounded-xl border border-slate-200 bg-slate-50 p-2 align-top"><div className="flex items-start justify-between gap-2"><span className="text-[9px] font-semibold uppercase tracking-wide text-cyan-800">{region}</span><span className="text-[9px] tabular-nums text-slate-500">n={int(chart.rows)}</span></div><div className="mt-1 min-h-8 text-[10px] font-medium leading-4 text-slate-700">{chart.label}</div><EChartsPanel option={chart.option} state={chart.option ? "ready" : "empty"} height={170} ariaLabel={`${region} pairwise cell, ${x} by ${y}, ${chart.label}`} /></td>; })}</tr>)}</tbody></table></section></div>;
}

function RelationshipsTab({ envelope, mode, scatterDisplayMode, scatterX, scatterY, scatterTarget, pairwiseDiagonalMethod = "histogram", pairwiseLowerMethod = "scatter", pairwiseUpperMethod = "hexbin" }: { envelope: ProjectEdaEnvelope<AssociationData | PairwiseData>; mode: RelationshipMode; scatterDisplayMode: ScatterDisplayMode; scatterX: string; scatterY: string; scatterTarget: string; pairwiseDiagonalMethod?: PairwiseDiagonalMethod; pairwiseLowerMethod?: PairwiseCellMethod; pairwiseUpperMethod?: PairwiseCellMethod }) {
  if ("cells" in envelope.data) {
    const data = envelope.data;
    const index = new Map(data.variables.map((name, i) => [name, i]));
    const estimableCells = data.cells.filter((cell): cell is typeof cell & { value: number } => cell.value !== null && Number.isFinite(cell.value));
    const option: EChartsOption = { ...chartBase(), tooltip: { position: "top", formatter: (params: unknown) => { const p = params as { data?: { value?: [number, number, number]; method?: string; rows?: number } }; return `${data.variables[p.data?.value?.[1] ?? 0]} × ${data.variables[p.data?.value?.[0] ?? 0]}<br/><b>${Number(p.data?.value?.[2]).toFixed(3)}</b><br/>${p.data?.method} · ${int(p.data?.rows)} rows`; } }, xAxis: { type: "category", data: data.variables, axisLabel: { rotate: 35 } }, yAxis: { type: "category", data: data.variables }, visualMap: { min: -1, max: 1, calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#0e7490", "#f8fafc", "#be123c"] } }, series: [{ type: "heatmap", data: estimableCells.map((cell) => ({ value: [index.get(cell.x) ?? 0, index.get(cell.y) ?? 0, cell.value], method: cell.method, rows: cell.rows })), label: { show: data.variables.length <= 8, formatter: (params: unknown) => Number((params as { value?: [number, number, number] }).value?.[2]).toFixed(2) } }] } as EChartsOption;
    const strongest = [...estimableCells].filter((cell) => cell.x !== cell.y).sort((a, b) => Math.abs(b.value) - Math.abs(a.value))[0];
    return <div className="space-y-4"><RelationshipPrimeSummary envelope={envelope} variables={data.variables} mode={mode} method={data.methods.join(" · ")} strongest={strongest ? `${strongest.x} × ${strongest.y} · ${strongest.value.toFixed(3)}` : "No estimable non-diagonal pair"} /><section className="rounded-xl border border-cyan-200 bg-cyan-50 p-3 text-xs leading-5 text-cyan-900"><b>Methods remain explicit:</b> Pearson for numeric linear, Spearman for numeric monotonic, Cramér’s V for categorical pairs, and correlation ratio for numeric–categorical relationships. Unlike measures are labeled and are not presented as interchangeable. Degenerate pairs are left blank as not estimable; they are never rendered as zero.</section><ChartCard title="Correlation / association heatmap" description={`Methods present: ${data.methods.join(" · ")}. Values are descriptive, not automatic feature selection.`} option={option} ariaLabel="Project-bound association heatmap" envelope={envelope} exportRows={rowsFrom(data.cells)} /></div>;
  }
  const data = envelope.data;
  if (mode === "pairwise") return <PairwiseMatrix envelope={envelope as ProjectEdaEnvelope<PairwiseData>} diagonalMethod={pairwiseDiagonalMethod} lowerMethod={pairwiseLowerMethod} upperMethod={pairwiseUpperMethod} />;
  const pairs: [string, string][] = [];
  if (mode === "scatter" && data.variables.includes(scatterX) && data.variables.includes(scatterY) && scatterX !== scatterY) pairs.push([scatterX, scatterY]);
  return <div className="space-y-4"><RelationshipPrimeSummary envelope={envelope} variables={data.variables} mode={mode} method={data.method} strongest={mode === "scatter" ? `${scatterX || "X not assigned"} × ${scatterY || "Y not assigned"}` : `${pairs.length} explicit pair(s)`} sample={`${int(data.sampleSize)} / ${int(data.populationSize)} · seed ${data.seed}${scatterTarget ? ` · target ${scatterTarget}` : ""}`} /><section className="rounded-xl border border-cyan-200 bg-cyan-50 p-3 text-xs text-cyan-900"><b>Deterministic point sample:</b> {int(data.sampleSize)} of {int(data.populationSize)} rows · seed {data.seed} · {data.method}. {data.stratifyBy === "outcome" ? "Color uses the governed development-only outcome; it is not a predictor. " : ""}The full population never enters the browser, and point-level sample download is disabled by default.</section>{!pairs.length ? <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">Select two numeric variables for scatter/hexbin, or 2–6 variables for a pairwise matrix.</div> : <div className="space-y-4">{pairs.map(([x, y]) => {
    const complete = data.rows.filter((row) => row[x] !== null && row[x] !== undefined && row[y] !== null && row[y] !== undefined);
    const xNumeric = complete.some((row) => typeof row[x] === "number");
    const yNumeric = complete.some((row) => typeof row[y] === "number");
    if (!complete.length) return <div key={`${x}:${y}`} className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500">{x} × {y}: no complete sampled pairs.</div>;

    let option: EChartsOption;
    let description: string;
    let ariaLabel: string;
    if (xNumeric && yNumeric) {
      const rows = complete.filter((row) => typeof row[x] === "number" && typeof row[y] === "number");
      if (mode === "scatter" && scatterDisplayMode === "hexbin") {
        const xs = rows.map((row) => Number(row[x])); const ys = rows.map((row) => Number(row[y]));
        const xMin = Math.min(...xs); const xMax = Math.max(...xs); const yMin = Math.min(...ys); const yMax = Math.max(...ys);
        const hexRadius = 1 / 28;
        const roundedAxial = (q: number, r: number): [number, number] => {
          let cubeX = Math.round(q); let cubeZ = Math.round(r); const cubeY = Math.round(-q - r);
          const xError = Math.abs(cubeX - q); const yError = Math.abs(cubeY + q + r); const zError = Math.abs(cubeZ - r);
          if (xError > yError && xError > zError) cubeX = -cubeY - cubeZ;
          else if (zError > yError) cubeZ = -cubeX - cubeY;
          return [cubeX, cubeZ];
        };
        const counts = new Map<string, number>();
        for (const row of rows) {
          const normalizedX = (Number(row[x]) - xMin) / Math.max(Number.EPSILON, xMax - xMin);
          const normalizedY = (Number(row[y]) - yMin) / Math.max(Number.EPSILON, yMax - yMin);
          const [q, r] = roundedAxial(((Math.sqrt(3) / 3) * normalizedX - normalizedY / 3) / hexRadius, ((2 / 3) * normalizedY) / hexRadius);
          const key = `${q}:${r}`; counts.set(key, (counts.get(key) ?? 0) + 1);
        }
        const binned = [...counts.entries()].map(([key, count]) => {
          const [q, r] = key.split(":").map(Number);
          const centerX = hexRadius * Math.sqrt(3) * (q + r / 2);
          const centerY = hexRadius * 1.5 * r;
          return [xMin + centerX * (xMax - xMin), yMin + centerY * (yMax - yMin), count];
        });
        const maxCount = Math.max(1, ...binned.map((row) => row[2]));
        option = { ...chartBase(), tooltip: { trigger: "item", formatter: (params: unknown) => { const value = (params as { value?: number[] }).value ?? []; return `${x}: ${Number(value[0]).toPrecision(5)}<br/>${y}: ${Number(value[1]).toPrecision(5)}<br/><b>${int(value[2])} sampled rows</b>`; } }, visualMap: { min: 1, max: maxCount, dimension: 2, calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#cffafe", "#0891b2", "#164e63"] } }, xAxis: { type: "value", name: x, scale: true }, yAxis: { type: "value", name: y, scale: true }, series: [{ name: "Hexbin density", type: "scatter", symbol: "path://M0,-8 L6.93,-4 L6.93,4 L0,8 L-6.93,4 L-6.93,-4 Z", symbolSize: (value: number[]) => 8 + Math.sqrt(Number(value[2]) / maxCount) * 18, data: binned }] } as EChartsOption;
        description = `Hexbin density over the deterministic sample (${binned.length} occupied bins); target color is disabled.`;
        ariaLabel = `Hexbin density plot ${x} by ${y}`;
      } else {
        const strata = mode === "scatter" && scatterTarget ? [...new Set(rows.map((row) => String(row[scatterTarget] ?? "MISSING")))] : [];
        const series = strata.length
          ? strata.map((stratum) => ({ name: stratum, type: "scatter" as const, large: rows.length > 1000, symbolSize: 5, data: rows.filter((row) => String(row[scatterTarget] ?? "MISSING") === stratum).map((row) => [row[x], row[y]]), itemStyle: { opacity: 0.48 } }))
          : [{ name: `${x} × ${y}`, type: "scatter" as const, large: rows.length > 1000, symbolSize: 5, data: rows.map((row) => [row[x], row[y]]), itemStyle: { opacity: 0.42 } }];
        option = { ...chartBase(), legend: strata.length ? { type: "scroll", top: 0 } : undefined, tooltip: { trigger: "item" }, brush: { toolbox: ["rect", "polygon", "clear"], xAxisIndex: 0, yAxisIndex: 0 }, xAxis: { type: "value", name: x, scale: true }, yAxis: { type: "value", name: y, scale: true }, series };
        description = `${mode === "scatter" ? "Explicit X/Y" : "Pairwise numeric"} view${strata.length ? ` stratified by ${scatterTarget}` : ""}; trend is descriptive only.`;
        ariaLabel = `Scatter plot ${x} by ${y}`;
      }
    } else if (!xNumeric && !yNumeric) {
      const xValues = [...new Set(complete.map((row) => String(row[x])))].sort().slice(0, 20);
      const yValues = [...new Set(complete.map((row) => String(row[y])))].sort().slice(0, 20);
      const xIndex = new Map(xValues.map((value, index) => [value, index])); const yIndex = new Map(yValues.map((value, index) => [value, index]));
      const counts = new Map<string, number>(); for (const row of complete) { const xv = String(row[x]); const yv = String(row[y]); if (!xIndex.has(xv) || !yIndex.has(yv)) continue; const key = `${xv}\u0000${yv}`; counts.set(key, (counts.get(key) ?? 0) + 1); }
      const cells = [...counts.entries()].map(([key, count]) => { const [xv, yv] = key.split("\u0000"); return [xIndex.get(xv) ?? 0, yIndex.get(yv) ?? 0, count]; });
      option = { ...chartBase(), tooltip: { trigger: "item" }, visualMap: { min: 0, max: Math.max(1, ...cells.map((row) => Number(row[2]))), calculable: true, orient: "horizontal", left: "center", bottom: 0 }, xAxis: { type: "category", name: x, data: xValues, axisLabel: { rotate: 35 } }, yAxis: { type: "category", name: y, data: yValues }, series: [{ type: "heatmap", data: cells }] } as EChartsOption;
      description = "Pairwise categorical count heatmap over the deterministic sample; top 20 observed levels per axis."; ariaLabel = `Categorical pairwise heatmap ${x} by ${y}`;
    } else {
      const numericName = xNumeric ? x : y; const categoryName = xNumeric ? y : x;
      const categories = [...new Set(complete.map((row) => String(row[categoryName])))].sort().slice(0, 20);
      const rows = complete.filter((row) => typeof row[numericName] === "number" && categories.includes(String(row[categoryName])));
      option = { ...chartBase(), tooltip: { trigger: "item" }, xAxis: { type: "category", name: categoryName, data: categories, axisLabel: { rotate: 35 } }, yAxis: { type: "value", name: numericName, scale: true }, series: [{ name: `${numericName} by ${categoryName}`, type: "scatter", symbolSize: 5, large: rows.length > 1000, data: rows.map((row) => [String(row[categoryName]), row[numericName]]), itemStyle: { opacity: 0.42 } }] } as EChartsOption;
      description = "Pairwise mixed-type strip plot over the deterministic sample; top 20 observed categories."; ariaLabel = `Mixed pairwise plot ${x} by ${y}`;
    }
    return <ChartCard key={`${x}:${y}`} title={`${x} × ${y}`} description={description} option={option} ariaLabel={ariaLabel} envelope={envelope} />;
  })}</div>}</div>;
}

function RelationshipPrimeSummary({ envelope, variables, mode, method, strongest, sample }: { envelope: ProjectEdaEnvelope<AssociationData | PairwiseData>; variables: string[]; mode: RelationshipMode; method: string; strongest: string; sample?: string }) {
  return <section className="rounded-2xl border border-cyan-200 bg-cyan-50/50 p-4" data-testid="stage3-relationship-prime-summary"><div className="flex flex-wrap items-start gap-3"><div><div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-800">Relationship summary</div><h4 className="mt-1 font-semibold text-slate-950">{variables.length} explicitly assigned variable{variables.length === 1 ? "" : "s"}</h4></div><span className="ml-auto rounded-full border border-cyan-200 bg-white px-2.5 py-1 text-[10px] font-semibold text-cyan-900">{mode.replaceAll("_", " ").toUpperCase()}</span></div><div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4"><Metric label="Ordered variables" value={variables.join(" · ") || "None assigned"} detail="Exactly this set is queried" /><Metric label="Method" value={method} detail="Pair-type method remains visible" /><Metric label="Strongest / assigned view" value={strongest} detail="Descriptive association; not a selection" accent="cyan" /><Metric label="Population / sample" value={sample ?? `${int(envelope.population.rowsRepresented)} represented`} detail={`${activeFilterCount(envelope)} active population filter(s)`} /></div><p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs leading-5 text-amber-900"><b>Causal warning:</b> association, scatter structure, and model utility are different questions. No chart establishes causation or adopts a predictor.</p></section>;
}

function activeFilterCount(envelope: ProjectEdaEnvelope<unknown>) {
  return Object.values(envelope.population.filtersApplied ?? {}).filter((value) => value !== "" && value !== undefined && !(Array.isArray(value) && value.length === 0)).length;
}

function TargetTab({ envelope, taxonomy, handoff }: { envelope: ProjectEdaEnvelope<OverviewData>; taxonomy: string[]; handoff: (destination: "outliers" | "missing" | "features") => void }) {
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
  const summary = data.targetSummary;
  const quality = data.dataQualitySnapshot;
  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-cyan-200 bg-cyan-50/40 p-4" data-testid="stage3-target-decision-summary">
        <div className="flex flex-wrap items-center gap-2"><div><div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-800">Target decision summary</div><h4 className="mt-1 font-semibold text-slate-950">What the development evidence says</h4></div><span className="ml-auto rounded-full border border-cyan-300 bg-white px-2.5 py-1 text-[10px] font-semibold text-cyan-900">{summary.status.replaceAll("_", " ")}</span></div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
          <Metric label="Dominant class" value={summary.dominantClass?.value ?? "—"} detail={summary.dominantClass ? `${int(summary.dominantClass.count)} · ${pct(summary.dominantClass.percent)}` : "not represented"} />
          <Metric label="Rarest class" value={summary.rarestClass?.value ?? "—"} detail={summary.rarestClass ? `${int(summary.rarestClass.count)} · ${pct(summary.rarestClass.percent)}` : "not represented"} accent="amber" />
          <Metric label="Imbalance ratio" value={summary.imbalanceRatio === null ? "—" : `${summary.imbalanceRatio.toFixed(2)}×`} detail="dominant / rarest" />
          <Metric label="Season stability" value={summary.seasonToSeasonStability.status.replaceAll("_", " ")} detail={`${summary.seasonToSeasonStability.maxClassShareRangePct?.toFixed(3) ?? "—"} pp max range`} />
          <Metric label="Smallest rare sample" value={int(summary.minimumRareClassSampleSize)} detail={summary.minimumRareClassSeason ? `season ${summary.minimumRareClassSeason}` : "no cross-season sample"} />
          <Metric label="Decision" value="NO AUTO REBALANCING" detail="no automatic weighting or oversampling" />
        </div>
        <p className="mt-3 text-xs leading-5 text-cyan-950">{summary.conclusion} This is descriptive guidance only; chronological validation remains authoritative.</p>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4" data-testid="stage3-eda-data-quality-snapshot">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Data Quality Snapshot</div><h4 className="mt-1 font-semibold text-slate-950">Signals to carry into the dedicated preparation steps</h4><p className="mt-1 text-xs text-slate-500">No treatment is applied here. Counts are scoped to the current development-only evidence.</p></div><span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[10px] font-semibold text-slate-700">{quality.decision.replaceAll("_", " ")}</span></div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          <Metric label="Physical missingness" value={pct(quality.overallPhysicalMissingPercent)} detail="macro predictor-cell rate" />
          <Metric label="Cold-start prevalence" value={pct(quality.coldStartPercent)} detail={`${int(quality.coldStartRows)} development rows`} accent="amber" />
          <Metric label="Material missingness" value={int(quality.featuresWithMaterialMissingness)} detail={`features at ≥${quality.materialMissingnessThresholdPct}%`} />
          <Metric label="Source / computation failures" value={int(quality.failureReasonRows.sourceMissingRows + quality.failureReasonRows.sourceNotAvailableForEraRows + quality.failureReasonRows.computationFailureRows)} detail={`${int(quality.failureReasonRows.computationFailureRows)} computation failures`} />
          <Metric label="Potential descriptive outliers" value={int(quality.potentialDescriptiveOutliers.count)} detail={`${quality.potentialDescriptiveOutliers.variable} · ${quality.potentialDescriptiveOutliers.method}`} accent="amber" />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3"><p className="mr-auto max-w-3xl text-[10px] leading-4 text-slate-500">{quality.failureReasonRows.note} The outlier count is representative-feature evidence, not a cross-feature treatment decision.</p><button type="button" onClick={() => handoff("missing")} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700">Open Missing Values</button><button type="button" onClick={() => handoff("outliers")} className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white">Open Outliers</button></div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4"><div className="text-xs font-semibold uppercase tracking-wide text-cyan-700">Exact governed taxonomy</div><div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">{classes.map((name, index) => <div key={name} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-xs"><span className="mr-2 text-slate-400">{index + 1}</span><b>{name}</b></div>)}</div><p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><b>Probability calibration is primary;</b> class imbalance is a property of baseball and is not automatically corrected. This workbench makes no oversampling or class-weight recommendation.</p><p className="mt-2 text-xs text-slate-600">Use outcome stratification on the Distributions tab for one-feature class comparisons, or the global history and simulator-state filters for governed development-only slices.</p></section>
      <div className="grid gap-4 xl:grid-cols-2"><ChartCard title="Class counts and proportions" description="Development base rates, including rare-class sample sizes." option={barOption(data.targetDistribution.map((row) => row.value), data.targetDistribution.map((row) => row.percent), "Share (%)")} ariaLabel="Eight class balance" envelope={envelope} exportRows={rowsFrom(confidenceRows)} /><ChartCard title="Class balance by season" description="Development seasons only; final-OOT class composition is inaccessible." option={bySeason} ariaLabel="Class distribution by development season" envelope={envelope} exportRows={rowsFrom(data.targetBySeason)} /><ChartCard title="Class balance by month" description="Monthly development-only target composition through 2026-08-13." option={byMonth} ariaLabel="Class distribution by development month" envelope={envelope} exportRows={rowsFrom(data.targetByMonth)} /><ChartCard title="Class balance by simulator state" description="Outcome composition by outs-before; other simulator states remain available through the global exact state filter." option={byState} ariaLabel="Class distribution by simulation state" envelope={envelope} exportRows={rowsFrom(stateRows)} /></div>
      <section className="overflow-auto rounded-2xl border border-slate-200 bg-white p-4"><h4 className="font-semibold text-slate-950">Rare-class evidence and 95% binomial intervals</h4><p className="mt-1 text-xs text-slate-500">Wilson intervals describe development base-rate precision; they are not model-selection thresholds.</p><table className="mt-3 w-full min-w-[620px] text-xs"><thead><tr className="text-left text-slate-500">{["Class", "Rows", "Share", "95% interval"].map((label) => <th key={label} className="border-b px-2 py-2">{label}</th>)}</tr></thead><tbody>{confidenceRows.map((row) => <tr key={row.value}><td className="border-b px-2 py-2 font-mono font-semibold">{row.value}</td><td className="border-b px-2 py-2">{int(row.count)}</td><td className="border-b px-2 py-2">{pct(row.percent)}</td><td className="border-b px-2 py-2">{row.lower95.toFixed(3)}% – {row.upper95.toFixed(3)}%</td></tr>)}</tbody></table></section>
    </div>
  );
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
  const assessment = data.stabilityAssessment;
  const main = lineOption(data.series.map((row) => row.period), [{ name: "Mean", values: data.series.map((row) => row.mean) }, { name: "Median", values: data.series.map((row) => row.median) }], data.variable);
  const missing = lineOption(data.series.map((row) => row.period), [{ name: "Missing %", values: data.series.map((row) => row.missingPercent) }, { name: "Rows (scaled)", values: data.series.map((row) => row.count) }], "Value");
  const drift = lineOption(data.drift.map((row) => row.period), [{ name: "PSI", values: data.drift.map((row) => row.psi) }, { name: "KS", values: data.drift.map((row) => row.ks) }], "Drift diagnostic");
  const periods = data.series.map((row) => row.period);
  const targetMix: EChartsOption = { ...chartBase(), legend: { type: "scroll", top: 0 }, xAxis: { type: "category", data: periods }, yAxis: { type: "value", max: 100, name: "Share (%)" }, series: TARGET_ORDER.map((target) => ({ name: target, type: "line", stack: "target", areaStyle: { opacity: 0.2 }, showSymbol: false, data: data.series.map((row) => row.targetComposition.find((item) => item.value === target)?.percent ?? 0) })) };
  const targetRows = data.series.flatMap((row) => row.targetComposition.map((item) => ({ period: row.period, ...item })));
  return <div className="space-y-4"><section className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><b>Descriptive stability diagnostics only.</b> PSI and KS highlight changing distributions and source eras; they do not select a feature, threshold, or model. The 2026 comparison stops on 2026-08-13.</section><section className="rounded-2xl border border-slate-200 bg-white p-4" data-testid="stage3-stability-assessment"><div className="flex flex-wrap items-start gap-3"><div><div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Stability Assessment</div><h4 className="mt-1 font-semibold text-slate-950">Written development-only takeaway</h4></div><span className="ml-auto rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[10px] font-semibold text-amber-900">{assessment.overallStatus.replaceAll("_", " ")}</span></div><div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-6"><Metric label="Target mix" value={assessment.targetMix.status.replaceAll("_", " ")} detail={`${assessment.targetMix.maxClassShareRangePct?.toFixed(3) ?? "—"} pp max range`} /><Metric label="Stable features" value={int(assessment.featureCounts.stable)} detail={assessment.featureCounts.scope.replaceAll("_", " ")} /><Metric label="Moderate review" value={int(assessment.featureCounts.moderateReview)} detail="descriptive review only" accent="amber" /><Metric label="High review" value={int(assessment.featureCounts.highReview)} detail="material diagnostic shift" accent="amber" /><Metric label="Source-era changes" value={int(assessment.featureCounts.sourceEraChange)} detail={assessment.sourceEraEvidenceStatus.replaceAll("_", " ").toLowerCase()} /><Metric label="Cold-start shift" value={assessment.coldStartShift.status.replaceAll("_", " ")} detail={`${assessment.coldStartShift.maxRangePct.toFixed(2)} pp range`} /></div><p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-700">{assessment.recommendedNextAction}</p><p className="mt-2 text-[11px] leading-5 text-slate-500">{assessment.rowVolumeNote}</p><div className="mt-3 overflow-auto"><table className="w-full min-w-[980px] text-xs"><thead><tr className="text-left text-slate-500">{["Variable", "Status", "Direction / magnitude", "Periods affected", "PSI / KS", "Coverage shift", "Likely cause", "Next action"].map((label) => <th key={label} className="border-b px-2 py-2">{label}</th>)}</tr></thead><tbody>{assessment.selectedVariables.map((item) => <tr key={item.variable}><td className="border-b px-2 py-2 font-mono font-semibold">{item.variable}</td><td className="border-b px-2 py-2">{item.status.replaceAll("_", " ")}</td><td className="border-b px-2 py-2">{item.direction.replaceAll("_", " ")} · {item.magnitude === null ? "—" : item.magnitude.toFixed(4)}{item.relativeMagnitudePct === null ? "" : ` (${item.relativeMagnitudePct.toFixed(1)}%)`}</td><td className="border-b px-2 py-2">{item.affectedPeriods.length ? item.affectedPeriods.join(", ") : "none flagged"}</td><td className="border-b px-2 py-2">{item.methods.join(" + ")} · {item.psiMax.toFixed(3)} / {item.ksMax?.toFixed(3) ?? "NA"}</td><td className="border-b px-2 py-2">{item.coverageShiftPct.toFixed(2)} pp ({item.coverageRangePct.toFixed(2)} pp range)</td><td className="border-b px-2 py-2">{item.likelyCause.replaceAll("_", " ").toLowerCase()}</td><td className="border-b px-2 py-2">{item.recommendedNextAction}</td></tr>)}</tbody></table></div></section><div className="grid gap-4 xl:grid-cols-2"><ChartCard title={`${data.variable} through time`} description={`${data.granularity} development aggregates; mean and median.`} option={main} ariaLabel={`${data.variable} monthly stability`} envelope={envelope} exportRows={rowsFrom(data.series)} /><ChartCard title="Coverage and row volume" description="Missingness and available evidence through time." option={missing} ariaLabel="Feature coverage through time" envelope={envelope} exportRows={rowsFrom(data.series)} /><ChartCard title="Target mix through time" description="Development-only class composition; final-OOT outcomes are not materialized." option={targetMix} ariaLabel="Target mix through development time" envelope={envelope} exportRows={rowsFrom(targetRows)} /><ChartCard title="Distribution drift" description="PSI and KS against each documented baseline period; source-era shifts remain visible." option={drift} ariaLabel="Feature distribution drift" envelope={envelope} exportRows={rowsFrom(data.drift)} /></div></div>;
}

function ColdStartTab({ envelope, role }: { envelope: ProjectEdaEnvelope<ColdStartData>; role: PlayerRole }) {
  const data = envelope.data;
  const entities = role === "batter" ? [{ label: "Batter", data: data.batter }] : role === "pitcher" ? [{ label: "Pitcher", data: data.pitcher }] : [{ label: "Batter", data: data.batter }, { label: "Pitcher", data: data.pitcher }];
  const bars: EChartsOption = { ...chartBase(), legend: { top: 0 }, xAxis: { type: "category", data: entities.map((entity) => entity.label) }, yAxis: { type: "value", name: "Rows" }, series: [{ name: "No prior history", type: "bar", data: entities.map((entity) => entity.data.noPriorRows) }, { name: "Insufficient history", type: "bar", data: entities.map((entity) => entity.data.insufficientRows) }] };
  const periods = [...new Set([...data.batter.byPeriod.map((row) => row.period), ...data.pitcher.byPeriod.map((row) => row.period)])].sort();
  const time = lineOption(periods, entities.map((entity) => ({ name: `${entity.label} no history`, values: periods.map((period) => entity.data.byPeriod.find((row) => row.period === period)?.noPriorRows ?? 0) })), "Rows");
  const allScopes = [...new Set(data.targetComposition.map((row) => row.scope))];
  const scopes = role === "both" ? allScopes : allScopes.filter((scope) => scope.toLowerCase().includes(role));
  const displayedScopes = scopes.length ? scopes : allScopes;
  const composition: EChartsOption = { ...chartBase(), legend: { type: "scroll", top: 0 }, xAxis: { type: "category", data: displayedScopes }, yAxis: { type: "value", max: 100, name: "Share (%)" }, series: TARGET_ORDER.map((target) => ({ name: target, type: "bar", stack: "target", data: displayedScopes.map((scope) => data.targetComposition.find((row) => row.scope === scope && row.value === target)?.percent ?? 0) })) };
  const exportRows = entities.map((entity) => ({ entity: entity.label, noPrior: entity.data.noPriorRows, insufficient: entity.data.insufficientRows }));
  return <div className="space-y-4"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><Metric label="Cold-start rows" value={int(data.summary.coldStartRows)} detail={`${pct(data.summary.coldStartPercent)} of development`} accent="amber" /><Metric label="Affected games" value={int(data.summary.affectedGames)} detail="canonical development games" /><Metric label="Affected teams" value={int(data.summary.affectedTeams)} detail="exact canonical teams" />{role !== "pitcher" ? <Metric label="Affected batters" value={int(data.batter.affectedPlayers)} detail={`${int(data.batter.affectedGames)} games · ${int(data.batter.affectedTeams)} teams`} /> : null}{role !== "batter" ? <Metric label="Affected pitchers" value={int(data.pitcher.affectedPlayers)} detail={`${int(data.pitcher.affectedGames)} games · ${int(data.pitcher.affectedTeams)} teams`} /> : null}</div><div className="grid gap-4 xl:grid-cols-2"><ChartCard title="Batter and pitcher history sufficiency" description="Cold-start rows are retained; this view informs later fold-local priors or imputation." option={bars} ariaLabel="Batter pitcher cold start counts" envelope={envelope} exportRows={exportRows} /><ChartCard title="Cold-start prevalence through time" description="Unseen players by development season/month." option={time} ariaLabel="Cold start over time" envelope={envelope} exportRows={rowsFrom(entities.flatMap((entity) => entity.data.byPeriod))} /><div className="xl:col-span-2"><ChartCard title="Cold-start target composition" description="Development-only target mix for established versus low-history players." option={composition} ariaLabel="Cold start target composition" envelope={envelope} exportRows={rowsFrom(data.targetComposition.filter((row) => displayedScopes.includes(row.scope)))} /></div></div></div>;
}

function HandoffActions({ handoff, selected }: { handoff: (destination: "outliers" | "missing" | "features") => void; selected: "missing" | "outliers" }) {
  return <section className="rounded-2xl border border-slate-200 bg-white p-4"><div className="text-xs font-semibold uppercase text-slate-500">Analytical handoff · no automatic treatment</div><div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => handoff("outliers")} className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold ${selected === "outliers" ? "bg-amber-700 text-white" : "border border-slate-200 text-slate-700"}`}><Box size={14} /> Open in Outliers</button><button type="button" onClick={() => handoff("missing")} className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold ${selected === "missing" ? "bg-amber-700 text-white" : "border border-slate-200 text-slate-700"}`}><CircleOff size={14} /> Open in Missing Values</button><button type="button" onClick={() => handoff("features")} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700"><Wand2 size={14} /> Bookmark for Feature Engineering</button></div><p className="mt-2 text-[11px] text-slate-500">Selected variables, filters, and exact data authority are persisted in the project-scoped workbench draft before navigation; later steps remain governed independently.</p></section>;
}

function SavedAnalysesDrawer({ open, close, returnFocusRef, views, authorityKey, bookmarks, variables, selectedVariables, setSelectedVariables, maxVariables, viewName, setViewName, viewNotes, setViewNotes, saveView, restoreView, renameView, updateView, removeView, toggleBookmark, handoff }: { open: boolean; close: () => void; returnFocusRef: RefObject<HTMLElement>; views: EdaView[]; authorityKey: string; bookmarks: string[]; variables: ProjectEdaVariable[]; selectedVariables: string[]; setSelectedVariables: (next: string[]) => void; maxVariables: number; viewName: string; setViewName: (value: string) => void; viewNotes: string; setViewNotes: (value: string) => void; saveView: () => void; restoreView: (view: EdaView) => void; renameView: (id: string, name: string) => void; updateView: (id: string) => void; removeView: (id: string) => void; toggleBookmark: (name: string) => void; handoff: (destination: "outliers" | "missing" | "features") => void }) {
  const currentViews = views.filter((view) => view.authorityKey === authorityKey);
  const staleViews = views.filter((view) => view.authorityKey !== authorityKey);
  const addBookmark = (name: string) => {
    if (selectedVariables.includes(name) || selectedVariables.length >= maxVariables) return;
    const variable = variables.find((item) => item.name === name);
    if (variable?.selectable) setSelectedVariables([...selectedVariables, name]);
  };
  return <CockpitDrawer open={open} onClose={close} returnFocusRef={returnFocusRef} title="Analytical bookmarks" eyebrow={`Saved analyses (${currentViews.length})`} description="Saved analyses are analytical bookmarks, not modeling decisions." widthClassName="max-w-xl" testId="stage3-saved-analyses-drawer" footer={<button type="button" onClick={close} className="ml-auto block rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white">Done</button>}>
    <div className="space-y-4 p-4 sm:p-5">
      <section className="rounded-xl border border-cyan-200 bg-cyan-50/50 p-3"><div className="text-xs font-semibold text-cyan-900">Save analysis</div><div className="mt-2 grid gap-2 sm:grid-cols-2"><label className="text-[11px] font-semibold text-cyan-900">Analysis name<input value={viewName} onChange={(event) => setViewName(event.target.value)} placeholder="Analysis name" className="mt-1 w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-xs font-normal text-slate-900" /></label><label className="text-[11px] font-semibold text-cyan-900">Scientist notes<input value={viewNotes} onChange={(event) => setViewNotes(event.target.value)} placeholder="Scientist notes" className="mt-1 w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-xs font-normal text-slate-900" /></label></div><button type="button" onClick={saveView} className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-cyan-800 px-3 py-2 text-xs font-semibold text-white"><Save size={13} /> Save current analysis</button></section>
      <section><h3 className="text-sm font-semibold text-slate-900">Current-authority analyses</h3>{currentViews.length ? <div className="mt-2 space-y-2">{currentViews.map((view) => <article key={view.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="flex items-start gap-2"><div className="min-w-0 flex-1"><input aria-label={`Rename ${view.name}`} defaultValue={view.name} onBlur={(event) => renameView(view.id, event.target.value)} className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-sm font-semibold text-slate-900 hover:border-slate-200 focus:border-cyan-300 focus:bg-white" /><div className="mt-1 text-[10px] uppercase text-slate-500">{TABS.find((tab) => tab.id === reopenTab(view.tab))?.label} · {new Date(view.savedAt).toLocaleString()}</div><p className="mt-1 text-xs text-slate-600">{view.notes || "No scientist note."}</p><div className="mt-1 text-[10px] text-slate-500">{view.selectedVariables.length} variables · {Object.keys(view.filters).length} filters · seed {view.settings.samplingSeed}</div></div><Pencil size={13} className="mt-1 text-slate-400" aria-hidden="true" /></div><div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => restoreView(view)} className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-2.5 py-1.5 text-xs font-semibold text-white"><FolderOpen size={13} /> Reopen</button><button type="button" onClick={() => updateView(view.id)} className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700">Update from current</button><button type="button" onClick={() => removeView(view.id)} className="ml-auto inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-rose-700"><Trash2 size={12} /> Delete</button></div></article>)}</div> : <p className="mt-2 rounded-lg border border-dashed border-slate-300 p-3 text-xs text-slate-500">No saved analysis for this authority yet. Save the current chart state above.</p>}{staleViews.length ? <p className="mt-2 text-[10px] text-amber-700">{staleViews.length} saved analysis{staleViews.length === 1 ? " is" : "es are"} retained under an older authority and cannot be reopened here.</p> : null}</section>
      <section className="border-t border-slate-200 pt-4"><h3 className="text-sm font-semibold text-slate-900">Bookmarked variables</h3><p className="mt-1 text-[11px] text-slate-500">Add governed bookmarks to the selected-variable tray or remove the bookmark.</p>{bookmarks.length ? <div className="mt-2 space-y-2">{bookmarks.map((name) => { const variable = variables.find((item) => item.name === name); return <div key={name} className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2"><Star size={12} fill="currentColor" className="text-amber-500" /><span className="min-w-0 flex-1 truncate font-mono text-[11px] font-semibold text-amber-950">{name}</span><button type="button" disabled={!variable?.selectable || selectedVariables.includes(name) || selectedVariables.length >= maxVariables} onClick={() => addBookmark(name)} className="rounded border border-amber-300 bg-white px-2 py-1 text-[10px] font-semibold text-amber-900 disabled:opacity-40">Add to tray</button><button type="button" onClick={() => toggleBookmark(name)} className="rounded p-1 text-amber-700" aria-label={`Remove bookmark ${name}`}><X size={12} /></button></div>; })}</div> : <p className="mt-2 text-xs text-slate-500">No bookmarked variables.</p>}<div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => handoff("missing")} className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-700">Open Missing Values</button><button type="button" onClick={() => handoff("outliers")} className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-700">Open Outliers</button></div></section>
    </div>
  </CockpitDrawer>;
}

function SavedViewsPanel({ views, authorityKey, bookmarks, variables, viewName, setViewName, viewNotes, setViewNotes, saveView, restoreView, removeView, handoff }: { views: EdaView[]; authorityKey: string; bookmarks: string[]; variables: ProjectEdaVariable[]; viewName: string; setViewName: (value: string) => void; viewNotes: string; setViewNotes: (value: string) => void; saveView: () => void; restoreView: (view: EdaView) => void; removeView: (id: string) => void; handoff: (destination: "outliers" | "missing" | "features") => void }) {
  return <div className="space-y-4"><section className="rounded-2xl border border-cyan-200 bg-cyan-50/40 p-4"><div className="text-xs font-semibold uppercase text-cyan-800"><BookmarkCheck size={14} className="mr-1 inline" /> Project-level saved views</div><p className="mt-1 text-xs leading-5 text-cyan-900">Views survive navigation, project reopen, and frontend restart through the existing project-scoped cockpit persistence. They are analytical bookmarks—not model decisions.</p><div className="mt-3 flex flex-wrap gap-2"><input value={viewName} onChange={(event) => setViewName(event.target.value)} placeholder="View name" className="min-w-44 flex-1 rounded-lg border border-cyan-200 bg-white px-3 py-2 text-xs" /><input value={viewNotes} onChange={(event) => setViewNotes(event.target.value)} placeholder="Notes" className="min-w-44 flex-1 rounded-lg border border-cyan-200 bg-white px-3 py-2 text-xs" /><button type="button" onClick={saveView} className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-800 px-3 py-2 text-xs font-semibold text-white"><Save size={14} /> Save current state</button></div></section><section className="rounded-2xl border border-slate-200 bg-white p-4"><h4 className="font-semibold text-slate-950">Saved analytical views</h4>{views.length ? <div className="mt-3 grid gap-3 xl:grid-cols-2">{views.map((view) => { const stale = view.authorityKey !== authorityKey; return <article key={view.id} className={`rounded-xl border p-3 ${stale ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50"}`}><div className="flex items-start gap-2"><div className="min-w-0 flex-1"><div className="font-semibold text-slate-900">{view.name}</div><div className="mt-1 text-[10px] uppercase text-slate-500">{TABS.find((tab) => tab.id === view.tab)?.label} · {new Date(view.savedAt).toLocaleString()}</div></div><button title="Delete saved view" type="button" onClick={() => removeView(view.id)} className="text-slate-400 hover:text-rose-600"><Trash2 size={14} /></button></div><p className="mt-2 text-xs text-slate-600">{view.notes || "No note."}</p><div className="mt-2 text-[11px] text-slate-500">{view.selectedVariables.length} variables · {Object.keys(view.filters).length} filters · seed {view.settings.samplingSeed}</div>{stale ? <div className="mt-3 rounded-lg border border-amber-300 bg-white p-2 text-[11px] font-semibold text-amber-900"><AlertTriangle size={12} className="mr-1 inline" /> STALE_AUTHORITY — this view cannot be restored after the project dataset binding changed.</div> : <button type="button" onClick={() => restoreView(view)} className="mt-3 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white">Restore view</button>}</article>; })}</div> : <div className="mt-4 rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No saved views yet.</div>}</section><section className="rounded-2xl border border-slate-200 bg-white p-4"><h4 className="font-semibold text-slate-950">Bookmarked variables</h4>{bookmarks.length ? <div className="mt-3 flex flex-wrap gap-2">{bookmarks.map((name) => { const variable = variables.find((item) => item.name === name); return <span key={name} title={variable?.definition} className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 font-mono text-[11px] font-semibold text-amber-900"><Star size={11} fill="currentColor" />{name}</span>; })}</div> : <p className="mt-2 text-xs text-slate-500">Star variables in the explorer to collect a review list.</p>}<div className="mt-4 flex flex-wrap gap-2"><button type="button" onClick={() => handoff("features")} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700">Open Feature Engineering</button><button type="button" onClick={() => handoff("outliers")} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700">Open Outliers</button><button type="button" onClick={() => handoff("missing")} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700">Open Missing Values</button></div></section></div>;
}

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Filter, LoaderCircle, Play, Search } from "lucide-react";
import StepShell from "../components/StepShell";
import {
  AtlasAttentionPanel,
  AtlasDataScopeBadge,
  AtlasExecutionStatus,
  AtlasStatusStrip,
  AtlasWorkflowSection,
  type AtlasWorkflowMetric,
} from "../components/ui/AtlasWorkflow";
import { logDecision } from "../lib/decisionJournal";
import { createEvidence } from "../lib/evidenceGraph";
import { loadLocalDataset } from "../lib/localDataset";
import { useWorkflowStore } from "../state/useWorkflowStore";

type MissingStrategy = "None" | "Mean" | "Median" | "Mode" | "Constant" | "Drop Row";
type MissingConfig = Record<string, { strategy: MissingStrategy; constantValue?: string }>;
type ColumnInfo = { name: string; dtype: string; role: "feature" };
type MissingStats = {
  missing: number;
  missingPct: number;
  total: number;
  informative: boolean;
  missing_target_metric: number | null;
  present_target_metric: number | null;
  difference: number | null;
  standardized_difference?: number | null;
};
type MissingApplication = {
  applied_at: string;
  dataset_version: string;
  config: MissingConfig;
  config_signature: string;
  source_stage: string;
  rows_before: number;
  rows_after: number;
  missing_before: number;
  missing_after: number;
  dropped_rows: number;
  treatments: Array<{ feature: string; strategy: MissingStrategy; filled: number; value?: string; dropped_rows?: number }>;
};
type MissingSummary = {
  ok: boolean;
  scope: "full_dataset";
  rows: number;
  columns: ColumnInfo[];
  stats: Record<string, MissingStats>;
  target: string | null;
  problem_type: "classification" | "regression";
  event_value: unknown;
  event_rate: number | null;
  rare_event: boolean;
  source_stage: string;
  dataset_version: string;
  application?: MissingApplication | null;
};

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") || "http://127.0.0.1:8001/api";
const CONFIG_KEY = "modeling-tool-missing-config";
const PAGE_SIZE = 20;
const STRATEGIES: MissingStrategy[] = ["None", "Mean", "Median", "Mode", "Constant", "Drop Row"];
const STRATEGY_GUIDANCE: Record<MissingStrategy, string> = {
  None: "Preserve missing values for a downstream estimator that supports them, or when no missing values exist.",
  Mean: "Fill numeric values with the full-data mean. Prefer only for approximately symmetric variables.",
  Median: "Fill numeric values with the full-data median. Prefer for skewed variables or variables with heavy tails.",
  Mode: "Fill with the most common full-data value. Appropriate for categorical and discrete fields.",
  Constant: "Fill with an explicit governed value such as Unknown. This can preserve the meaning of missingness.",
  "Drop Row": "Remove records with missing values. Use only when loss is small and population bias has been reviewed.",
};

function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  return fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  }).then(async (response) => {
    const payload = await response.json().catch(() => null);
    if (!response.ok || payload?.ok === false) throw new Error(payload?.detail ?? payload?.error ?? `ATLAS request failed with HTTP ${response.status}.`);
    return payload as T;
  });
}

function isNumeric(column: ColumnInfo) {
  return /int|float|double|decimal|number|numeric/i.test(column.dtype);
}

function normalizeConfig(columns: ColumnInfo[], config: MissingConfig): MissingConfig {
  return Object.fromEntries(columns.map((column) => [column.name, config[column.name] ?? { strategy: "None" }]));
}

function configMatchesApplication(summary: MissingSummary | null, config: MissingConfig) {
  if (!summary?.application) return false;
  return JSON.stringify(normalizeConfig(summary.columns, config)) === JSON.stringify(normalizeConfig(summary.columns, summary.application.config));
}

function pct(value: number | null | undefined, alreadyPercent = false) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "Not available";
  return `${(alreadyPercent ? value : value * 100).toFixed(2)}%`;
}

function strategyOptions(column: ColumnInfo) {
  return isNumeric(column) ? STRATEGIES : STRATEGIES.filter((strategy) => !["Mean", "Median"].includes(strategy));
}

export default function Step04MissingValues() {
  const localDataset = loadLocalDataset();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [summary, setSummary] = useState<MissingSummary | null>(null);
  const [config, setConfig] = useState<MissingConfig>({});
  const [globalStrategy, setGlobalStrategy] = useState<MissingStrategy>("None");
  const [globalConstant, setGlobalConstant] = useState("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<"missing" | "name" | "informative">("missing");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadSummary() {
    setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams();
      if (localDataset?.event_value !== undefined && localDataset?.event_value !== null) query.set("event_value", String(localDataset.event_value));
      if (localDataset?.problem_type) query.set("problem_type", localDataset.problem_type);
      const payload = await requestJson<MissingSummary>(`/missing/summary?${query.toString()}`);
      let stored: MissingConfig = {};
      try { stored = JSON.parse(localStorage.getItem(CONFIG_KEY) || "{}"); } catch { stored = {}; }
      const source = Object.keys(stored).length ? stored : payload.application?.config ?? {};
      setSummary(payload);
      setConfig(normalizeConfig(payload.columns, source));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Full-data missingness analysis is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadSummary(); }, []);
  useEffect(() => {
    try { localStorage.setItem(CONFIG_KEY, JSON.stringify(config)); }
    catch { setMessage("Selections are retained for this session, but browser persistence is unavailable."); }
  }, [config]);

  const totalMissing = summary?.columns.reduce((sum, column) => sum + (summary.stats[column.name]?.missing ?? 0), 0) ?? 0;
  const informativeCount = summary?.columns.filter((column) => summary.stats[column.name]?.informative).length ?? 0;
  const applied = configMatchesApplication(summary, config);
  const rows = useMemo(() => {
    const filtered = (summary?.columns ?? []).filter((column) => column.name.toLowerCase().includes(search.trim().toLowerCase()));
    return [...filtered].sort((a, b) => {
      if (sortBy === "name") return a.name.localeCompare(b.name);
      if (sortBy === "informative") return Number(summary?.stats[b.name]?.informative ?? false) - Number(summary?.stats[a.name]?.informative ?? false) || (summary?.stats[b.name]?.missingPct ?? 0) - (summary?.stats[a.name]?.missingPct ?? 0);
      return (summary?.stats[b.name]?.missingPct ?? 0) - (summary?.stats[a.name]?.missingPct ?? 0);
    });
  }, [search, sortBy, summary]);
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pagedRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function updateStrategy(column: string, strategy: MissingStrategy) {
    logDecision({ workflowStep: "Missing Values", actionType: "missing_value_strategy_selected", subject: column, previousValue: config[column]?.strategy ?? "None", newValue: strategy });
    setConfig((current) => ({ ...current, [column]: { ...current[column], strategy } }));
    setMessage("Treatment selections changed. Apply them before continuing.");
  }

  function updateConstant(column: string, constantValue: string) {
    setConfig((current) => ({ ...current, [column]: { strategy: "Constant", constantValue } }));
    setMessage("Treatment selections changed. Apply them before continuing.");
  }

  function buildGlobalConfig(strategy: MissingStrategy, constantValue: string) {
    if (!summary) return null;
    const next = Object.fromEntries(summary.columns.map((column) => {
      const compatible = !isNumeric(column) && ["Mean", "Median"].includes(strategy) ? "Mode" : strategy;
      return [column.name, { strategy: compatible, constantValue: compatible === "Constant" ? constantValue : undefined }];
    })) as MissingConfig;
    return next;
  }

  function updateGlobalStrategy(strategy: MissingStrategy) {
    setGlobalStrategy(strategy);
    const next = buildGlobalConfig(strategy, globalConstant);
    if (!next) return;
    setConfig(next);
    setMessage("Compatible defaults updated. Apply treatments to materialize them on the full dataset.");
  }

  function updateGlobalConstant(value: string) {
    setGlobalConstant(value);
    if (globalStrategy !== "Constant") return;
    const next = buildGlobalConfig("Constant", value);
    if (!next) return;
    setConfig(next);
    setMessage("Constant defaults updated. Apply treatments to materialize them on the full dataset.");
  }

  async function applyTreatments() {
    if (!summary) throw new Error("Full-data missingness analysis must load before treatments can be applied.");
    const missingConstant = summary.columns.find((column) => config[column.name]?.strategy === "Constant" && !String(config[column.name]?.constantValue ?? "").trim());
    if (missingConstant) throw new Error(`Enter a constant value for ${missingConstant.name} before applying treatments.`);
    setApplying(true);
    setError("");
    try {
      const payload = await requestJson<{ ok: true; scope: "full_dataset"; application: MissingApplication }>("/missing/apply", {
        method: "POST",
        body: JSON.stringify({ config: normalizeConfig(summary.columns, config), event_value: summary.event_value, problem_type: summary.problem_type }),
      });
      setSummary((current) => current ? { ...current, application: payload.application } : current);
      setMessage(`Applied ${payload.application.treatments.length.toLocaleString()} full-data treatment decisions. Missing cells changed from ${payload.application.missing_before.toLocaleString()} to ${payload.application.missing_after.toLocaleString()}.`);
      return payload.application;
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : "Missing-value treatments could not be applied.";
      setError(detail);
      throw new Error(detail);
    } finally {
      setApplying(false);
    }
  }

  async function completeStep() {
    const application = applied && summary?.application ? summary.application : await applyTreatments();
    await createEvidence({
      projectId,
      projectName,
      evidenceType: "missing_values",
      title: "Full-Data Missing-Value Treatment",
      summary: `${application.treatments.length.toLocaleString()} treatments were applied to the full dataset. Missing cells changed from ${application.missing_before.toLocaleString()} to ${application.missing_after.toLocaleString()}.`,
      sourcePage: "Missing Values",
      sourceRoute: "/step04",
      datasetIds: [application.dataset_version],
      modelIds: [], documentIds: [], notebookIds: [],
      supportsSections: ["Missing Value Treatment", "Data Quality", "Feature Engineering"],
      tags: ["predictive_modeling", "missing_values", "full_dataset"],
      status: "ready",
      importance: "high",
      lineage: { datasetVersion: application.dataset_version, sourceStage: application.source_stage, rowsBefore: application.rows_before, rowsAfter: application.rows_after, scope: "full_dataset" },
      payload: application,
    });
    return true;
  }

  const heroMetrics: AtlasWorkflowMetric[] = [
    { label: "Data Scope", value: summary ? "Full Dataset" : "Unavailable", tone: summary ? "info" : "warning" },
    { label: "Rows Reviewed", value: summary?.rows.toLocaleString() ?? "Loading" },
    { label: "Missing Cells", value: totalMissing.toLocaleString(), tone: totalMissing ? "warning" : "success" },
    { label: "Affected Predictors", value: summary?.columns.filter((column) => (summary.stats[column.name]?.missing ?? 0) > 0).length.toLocaleString() ?? "0" },
    { label: "Informative Flags", value: informativeCount.toLocaleString(), tone: informativeCount ? "warning" : "neutral" },
    { label: "Treatment State", value: applied ? "Applied" : "Selected only", tone: applied ? "success" : "warning" },
  ];

  return (
    <StepShell
      title="Step 4: Missing Values"
      subtitle="Assess missingness on the full post-outlier population, review target relationships, and materialize governed treatment decisions before feature engineering."
      variant="preparation"
      heroMetrics={heroMetrics}
      nextPath="/step05"
      onNext={completeStep}
      nextDisabled={loading || !summary || !!error || applying}
      nextDisabledReason={error || "Load the full-data missingness profile before continuing."}
      nextStatusLine={applied ? "The current full-data treatment configuration is applied and ready for Feature Engineering." : "Selected strategies will be applied to the full dataset before navigation."}
    >
      {loading ? <div className="atlas-workflow-section flex min-h-56 items-center justify-center"><LoaderCircle className="animate-spin text-blue-600" size={28} /></div> : null}
      {error ? <AtlasAttentionPanel title="Missing-value analysis is blocked" tone="danger">{error}</AtlasAttentionPanel> : null}
      {summary ? <div className="space-y-5">
        <AtlasStatusStrip items={[
          { label: "Input stage", state: "complete", detail: summary.source_stage === "outlier_treated" ? "Applied outlier treatments" : "Registered dataset" },
          { label: "Missingness review", state: "complete", detail: `${summary.columns.length.toLocaleString()} predictors` },
          { label: "Backend materialization", state: applied ? "complete" : "warning", detail: applied ? "Current" : "Selected, not applied" },
        ]} />

        {summary.rare_event ? <AtlasAttentionPanel title="Rare-event missingness review" tone="warning">The governed event rate is {pct(summary.event_rate)}. Missingness indicators can carry useful signal in rare-event models, so review event-rate differences before choosing simple imputation or row deletion.</AtlasAttentionPanel> : null}
        {informativeCount ? <AtlasAttentionPanel title="Potentially informative missingness" tone="warning">{informativeCount.toLocaleString()} predictor{informativeCount === 1 ? "" : "s"} show a material target difference when missing. Consider an explicit missingness indicator or constant category before erasing that signal.</AtlasAttentionPanel> : null}
        {!totalMissing ? <AtlasAttentionPanel title="No missing values detected" tone="info">The full post-outlier modeling population has no missing predictor cells. Keep the default None strategy unless scoring-time behavior requires a documented fallback.</AtlasAttentionPanel> : null}

        <AtlasWorkflowSection eyebrow="Treatment Policy" title="Global strategy and feature overrides" description="Selections remain recommendations until ATLAS applies them to the full backend dataset." tone="info" action={<AtlasDataScopeBadge scope="full_dataset" rows={summary.rows} />}>
          <div className="grid gap-4 lg:grid-cols-[minmax(240px,320px)_minmax(180px,240px)_minmax(0,1fr)] lg:items-end">
            <label className="grid gap-1 text-sm font-medium text-slate-700">Global strategy<select className="atlas-input" value={globalStrategy} onChange={(event) => updateGlobalStrategy(event.target.value as MissingStrategy)}>{STRATEGIES.map((strategy) => <option key={strategy}>{strategy}</option>)}</select><span className="text-xs font-normal leading-5 text-slate-500">{STRATEGY_GUIDANCE[globalStrategy]}</span></label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">Global constant<input className="atlas-input" value={globalConstant} onChange={(event) => updateGlobalConstant(event.target.value)} disabled={globalStrategy !== "Constant"} placeholder="Required for Constant" /></label>
            <div className="text-sm leading-6 text-slate-600">Changing the global strategy immediately updates compatible feature-level selections. Numeric-only global choices use Mode for categorical predictors. Review overrides before applying.</div>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-slate-200 pt-4">
            <AtlasExecutionStatus state={applying ? "running" : applied ? "complete" : "idle"} label={applying ? "Applying full-data treatments" : applied ? "Current configuration applied" : "Selections not yet applied"} detail={summary.application?.applied_at ? `Last applied ${new Date(summary.application.applied_at).toLocaleString()}` : "Apply explicitly or continue to materialize treatments."} />
            <button type="button" className="atlas-primary-button" onClick={() => void applyTreatments()} disabled={applying}><Play size={16} /> Apply treatments</button>
          </div>
        </AtlasWorkflowSection>

        {message ? <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">{message}</div> : null}

        <AtlasWorkflowSection eyebrow="Feature Review" title="Missingness and selected treatment" description="Missing counts and target relationships use the full post-outlier modeling population.">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <label className="relative min-w-64 flex-1"><Search size={16} className="pointer-events-none absolute left-3 top-2.5 text-slate-400" /><input className="atlas-input pl-9" value={search} onChange={(event) => { setSearch(event.target.value); setPage(0); }} placeholder="Search predictors" aria-label="Search predictors" /></label>
            <label className="flex items-center gap-2 text-sm text-slate-600"><Filter size={16} /><select className="atlas-input min-w-48" value={sortBy} onChange={(event) => { setSortBy(event.target.value as typeof sortBy); setPage(0); }}><option value="missing">Missing rate</option><option value="informative">Informative flags</option><option value="name">Feature name</option></select></label>
          </div>
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-[1040px] w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500"><tr><th className="px-3 py-2">Feature</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Missing</th><th className="px-3 py-2">Rate</th><th className="px-3 py-2">Target difference</th><th className="px-3 py-2">Selected strategy</th><th className="px-3 py-2">Constant</th></tr></thead>
              <tbody>{pagedRows.map((column) => {
                const stats = summary.stats[column.name];
                const selected = config[column.name] ?? { strategy: "None" as MissingStrategy };
                return <tr key={column.name} className={`border-t border-slate-100 ${stats?.informative ? "bg-amber-50" : "hover:bg-blue-50"}`}>
                  <td className="px-3 py-2 font-medium text-slate-900">{column.name}</td><td className="px-3 py-2 text-slate-600">{isNumeric(column) ? "Numeric" : "Categorical"}</td><td className="px-3 py-2 tabular-nums">{stats?.missing.toLocaleString() ?? "Not available"}</td><td className="px-3 py-2 tabular-nums">{pct(stats?.missingPct, true)}</td><td className={`px-3 py-2 tabular-nums ${stats?.informative ? "font-semibold text-amber-800" : "text-slate-600"}`}>{stats?.difference == null ? "Not evaluated" : summary.problem_type === "classification" ? `${stats.difference >= 0 ? "+" : ""}${pct(stats.difference)}` : stats.difference.toFixed(4)}{stats?.informative ? " - review" : ""}</td>
                  <td className="px-3 py-2"><select className="atlas-input min-w-40" value={selected.strategy} onChange={(event) => updateStrategy(column.name, event.target.value as MissingStrategy)}>{strategyOptions(column).map((strategy) => <option key={strategy}>{strategy}</option>)}</select></td>
                  <td className="px-3 py-2"><input className="atlas-input min-w-44" value={selected.constantValue ?? ""} onChange={(event) => updateConstant(column.name, event.target.value)} disabled={selected.strategy !== "Constant"} placeholder="Required for Constant" /></td>
                </tr>;
              })}</tbody>
            </table>
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500"><span>Showing {rows.length ? page * PAGE_SIZE + 1 : 0}-{Math.min((page + 1) * PAGE_SIZE, rows.length)} of {rows.length.toLocaleString()}</span><div className="flex items-center gap-2"><button className="atlas-secondary-button" type="button" disabled={page === 0} onClick={() => setPage((current) => Math.max(0, current - 1))}>Previous</button><span>Page {page + 1} of {pageCount}</span><button className="atlas-secondary-button" type="button" disabled={page >= pageCount - 1} onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}>Next</button></div></div>
        </AtlasWorkflowSection>

        <div className={`rounded-lg border px-4 py-3 text-sm ${applied ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}><div className="flex items-center gap-2 font-semibold">{applied ? <CheckCircle2 size={17} /> : null}{applied ? "Applied treatment" : "Selected treatment only"}</div><p className="mt-1">{applied ? `${summary.application?.treatments.length.toLocaleString()} actual treatments are materialized in the backend modeling frame.` : "The controls above describe the intended treatment. ATLAS will not call it applied until backend materialization succeeds."}</p></div>
      </div> : null}
    </StepShell>
  );
}

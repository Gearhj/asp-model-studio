import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Filter, LoaderCircle, Play, Search, SlidersHorizontal } from "lucide-react";
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
import { safeArray, safeObject } from "../lib/workflowSafety";

type MethodKey = "NONE" | "IQR_1_5" | "IQR_3_0" | "ZSCORE_3" | "ZSCORE_4" | "PCT_01_99" | "PCT_05_95";
type FeatureMethodKey = MethodKey | "USE_GLOBAL";

type MethodResult = {
  method: MethodKey;
  lower_threshold: number;
  upper_threshold: number;
  outlier_count: number;
  outlier_rate: number;
};

type OutlierFeature = {
  feature: string;
  datatype: string;
  nonmissing_count: number;
  missing_count: number;
  signal_metric: number | null;
  association_status: string;
  methods: Record<MethodKey, MethodResult>;
  rendered_sample: number[];
  rendered_sample_count: number;
  quantiles: Record<string, number | null>;
};

type OutlierApplication = {
  applied_at: string;
  dataset_version: string;
  row_count: number;
  global_method: MethodKey;
  config: Record<string, FeatureMethodKey>;
  treatments: Array<{
    feature: string;
    configured_method: FeatureMethodKey;
    applied_method: MethodKey;
    changed_values: number;
    lower_threshold: number;
    upper_threshold: number;
  }>;
  changed_values: number;
};

type OutlierSummary = {
  ok: boolean;
  scope: "full_dataset";
  row_count: number;
  dataset_version: string;
  target: string | null;
  problem_type: "classification" | "regression";
  event_value: unknown;
  event_rate: number | null;
  rare_event: boolean;
  features: OutlierFeature[];
  application?: OutlierApplication | null;
};

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") || "http://127.0.0.1:8001/api";
const CONFIG_KEY = "modeling-tool-outlier-methods";
const GLOBAL_KEY = "modeling-tool-outlier-global-method";
const PAGE_SIZE = 20;

const METHOD_OPTIONS: Array<{ key: MethodKey; label: string; guidance: string }> = [
  { key: "NONE", label: "None - preserve observed values", guidance: "Use when tail values are plausible business observations or may carry predictive signal." },
  { key: "IQR_1_5", label: "1.5 IQR", guidance: "A standard robust screen for moderately unusual values." },
  { key: "IQR_3_0", label: "3.0 IQR", guidance: "A conservative robust screen when extreme values may be meaningful." },
  { key: "ZSCORE_3", label: "3 standard deviations", guidance: "Use for approximately symmetric numeric variables." },
  { key: "ZSCORE_4", label: "4 standard deviations", guidance: "A less aggressive normal-based cap." },
  { key: "PCT_01_99", label: "Winsorize 0.5% and 99.5%", guidance: "Caps only the most extreme tails while preserving most observations." },
  { key: "PCT_05_95", label: "Winsorize 5% and 95%", guidance: "Use only when tail values are known quality or stability concerns." },
];

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

function effectiveMethod(configured: FeatureMethodKey | undefined, globalMethod: MethodKey): MethodKey {
  return !configured || configured === "USE_GLOBAL" ? globalMethod : configured;
}

function normalizedConfig(features: OutlierFeature[], config: Record<string, FeatureMethodKey>) {
  return Object.fromEntries(safeArray<OutlierFeature>(features).map((row) => [row.feature, config[row.feature] ?? "USE_GLOBAL"]));
}

function configMatchesApplication(summary: OutlierSummary | null, config: Record<string, FeatureMethodKey>, globalMethod: MethodKey) {
  const application = summary?.application;
  if (!summary || !application || application.global_method !== globalMethod) return false;
  return JSON.stringify(normalizedConfig(summary.features, config)) === JSON.stringify(normalizedConfig(summary.features, application.config));
}

function fmt(value: number | null | undefined, digits = 4) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "Not evaluated";
}

function pct(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : "Not available";
}

function Histogram({ values, method, after }: { values: number[]; method: MethodResult | null; after?: boolean }) {
  const safeMethod = method ?? { method: "NONE" as MethodKey, lower_threshold: 0, upper_threshold: 0, outlier_count: 0, outlier_rate: 0 };
  const safeValues = safeArray<number>(values);
  const bins = useMemo(() => {
    if (!safeValues.length) return [];
    const rendered = after && safeMethod.method !== "NONE"
      ? safeValues.map((value) => Math.max(safeMethod.lower_threshold, Math.min(safeMethod.upper_threshold, value)))
      : safeValues;
    const minimum = Math.min(...rendered, safeMethod.lower_threshold);
    const maximum = Math.max(...rendered, safeMethod.upper_threshold);
    const width = (maximum - minimum) / 18 || 1;
    const counts = Array.from({ length: 18 }, () => 0);
    rendered.forEach((value) => {
      const index = Math.min(17, Math.max(0, Math.floor((value - minimum) / width)));
      counts[index] += 1;
    });
    return counts;
  }, [after, safeMethod, safeValues]);
  const maximum = Math.max(1, ...bins);
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="text-xs font-semibold text-slate-800">{after ? "After selected treatment" : "Before treatment"}</div>
      <div className="mt-3 flex h-32 items-end gap-1" aria-label={after ? "Rendered post-treatment histogram" : "Rendered pre-treatment histogram"}>
        {bins.length ? bins.map((count, index) => (
          <div key={index} className={`min-w-0 flex-1 ${after ? "bg-blue-500" : "bg-slate-400"}`} style={{ height: `${Math.max(3, (count / maximum) * 100)}%` }} />
        )) : <div className="self-center text-xs text-slate-500">No rendered values are available.</div>}
      </div>
      <div className="mt-2 flex justify-between gap-3 text-[11px] text-slate-500">
        <span>Low {fmt(safeMethod.lower_threshold, 3)}</span>
        <span>High {fmt(safeMethod.upper_threshold, 3)}</span>
      </div>
    </div>
  );
}

export default function Step04Outliers() {
  const localDataset = loadLocalDataset();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [summary, setSummary] = useState<OutlierSummary | null>(null);
  const [config, setConfig] = useState<Record<string, FeatureMethodKey>>({});
  const [globalMethod, setGlobalMethod] = useState<MethodKey>(() => (localStorage.getItem(GLOBAL_KEY) as MethodKey) || "IQR_1_5");
  const [selectedFeature, setSelectedFeature] = useState("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<"signal" | "outliers" | "name">("signal");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadSummary() {
    setLoading(true);
    setError("");
    try {
      const payload = await requestJson<OutlierSummary>("/outliers/summary", {
        method: "POST",
        body: JSON.stringify({
          target: localDataset?.target,
          event_value: localDataset?.event_value,
          problem_type: localDataset?.problem_type,
        }),
      });
      const features = safeArray<OutlierFeature>(payload.features).map((feature) => ({
        ...feature,
        methods: safeObject(feature.methods) as Record<MethodKey, MethodResult>,
        rendered_sample: safeArray<number>(feature.rendered_sample),
        quantiles: safeObject(feature.quantiles) as Record<string, number | null>,
      }));
      const safePayload = { ...payload, features };
      let stored: Record<string, FeatureMethodKey> = {};
      try { stored = JSON.parse(localStorage.getItem(CONFIG_KEY) || "{}"); } catch { stored = {}; }
      const source = Object.keys(stored).length ? stored : safePayload.application?.config ?? {};
      const next = normalizedConfig(safePayload.features, source);
      setSummary(safePayload);
      setConfig(next);
      if (!localStorage.getItem(GLOBAL_KEY) && safePayload.application?.global_method) setGlobalMethod(safePayload.application.global_method);
      setSelectedFeature((current) => current && safePayload.features.some((row) => row.feature === current) ? current : safePayload.features[0]?.feature ?? "");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Full-data outlier analysis is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadSummary(); }, []);
  useEffect(() => {
    try {
      localStorage.setItem(CONFIG_KEY, JSON.stringify(config));
      localStorage.setItem(GLOBAL_KEY, globalMethod);
    } catch {
      setMessage("Selections are retained for this session, but browser persistence is unavailable.");
    }
  }, [config, globalMethod]);

  const rows = useMemo(() => {
    const filtered = safeArray<OutlierFeature>(summary?.features).filter((row) => row.feature.toLowerCase().includes(search.trim().toLowerCase()));
    return [...filtered].sort((a, b) => {
      if (sortBy === "name") return a.feature.localeCompare(b.feature);
      if (sortBy === "outliers") {
        const aMethod = a.methods?.[effectiveMethod(config[a.feature], globalMethod)];
        const bMethod = b.methods?.[effectiveMethod(config[b.feature], globalMethod)];
        return (bMethod?.outlier_count ?? 0) - (aMethod?.outlier_count ?? 0);
      }
      return Math.abs(b.signal_metric ?? 0) - Math.abs(a.signal_metric ?? 0);
    });
  }, [config, globalMethod, search, sortBy, summary]);
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pagedRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const selected = safeArray<OutlierFeature>(summary?.features).find((row) => row.feature === selectedFeature) ?? safeArray<OutlierFeature>(summary?.features)[0];
  const selectedMethod = selected ? selected.methods?.[effectiveMethod(config[selected.feature], globalMethod)] : null;
  const applied = configMatchesApplication(summary, config, globalMethod);
  const changedValues = safeArray<OutlierFeature>(summary?.features).reduce((sum, row) => sum + (row.methods?.[effectiveMethod(config[row.feature], globalMethod)]?.outlier_count ?? 0), 0);

  function changeFeature(feature: string, method: FeatureMethodKey) {
    logDecision({
      workflowStep: "Outlier Analysis",
      actionType: "outlier_method_selected",
      subject: feature,
      previousValue: config[feature] ?? "USE_GLOBAL",
      newValue: method,
    });
    setConfig((current) => ({ ...current, [feature]: method }));
    setMessage("Treatment selections changed. Apply them before continuing.");
  }

  function applyGlobalSelection() {
    setConfig((current) => Object.fromEntries(Object.keys(current).map((feature) => [feature, "USE_GLOBAL"])));
    setMessage("All features now inherit the selected global method. Apply treatments to materialize the change.");
  }

  async function applyTreatments() {
    if (!summary) throw new Error("Full-data outlier analysis must load before treatments can be applied.");
    setApplying(true);
    setError("");
    try {
      const payload = await requestJson<{ ok: true; scope: "full_dataset"; application: OutlierApplication }>("/outliers/apply", {
        method: "POST",
        body: JSON.stringify({
          config: normalizedConfig(safeArray<OutlierFeature>(summary.features), config),
          global_method: globalMethod,
          target: summary.target,
          event_value: summary.event_value,
          problem_type: summary.problem_type,
        }),
      });
      setSummary((current) => current ? { ...current, application: payload.application } : current);
      setMessage(`${payload.application.changed_values.toLocaleString()} full-data values were treated across ${payload.application.treatments.length.toLocaleString()} numeric predictors.`);
      return payload.application;
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : "Outlier treatments could not be applied.";
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
      evidenceType: "outliers",
      title: "Full-Data Outlier Treatment",
      summary: `${application.changed_values.toLocaleString()} values were treated across ${application.treatments.length.toLocaleString()} numeric predictors using the governed full dataset.`,
      sourcePage: "Outlier Analysis",
      sourceRoute: "/step03",
      datasetIds: [application.dataset_version],
      modelIds: [], documentIds: [], notebookIds: [],
      supportsSections: ["Outlier Treatment", "Data Quality", "Feature Engineering"],
      tags: ["predictive_modeling", "outliers", "full_dataset"],
      status: "ready",
      importance: "high",
      lineage: { datasetVersion: application.dataset_version, rowCount: application.row_count, scope: "full_dataset" },
      payload: application,
    });
    return true;
  }

  const heroMetrics: AtlasWorkflowMetric[] = [
    { label: "Data Scope", value: summary ? "Full Dataset" : "Unavailable", tone: summary ? "info" : "warning" },
    { label: "Rows Analyzed", value: summary?.row_count.toLocaleString() ?? "Loading" },
    { label: "Numeric Predictors", value: safeArray<OutlierFeature>(summary?.features).length.toLocaleString() },
    { label: summary?.problem_type === "regression" ? "Signal Metric" : "Signal Metric", value: summary?.problem_type === "regression" ? "Correlation" : "Information Value" },
    { label: "Values Flagged", value: changedValues.toLocaleString() },
    { label: "Treatment State", value: applied ? "Applied" : "Selected only", tone: applied ? "success" : "warning" },
  ];

  return (
    <StepShell
      title="Step 3: Outlier Analysis"
      subtitle="Review numeric tails on the full registered modeling population, choose governed treatments, and materialize those treatments before missing-value handling."
      variant="analysis"
      heroMetrics={heroMetrics}
      nextPath="/step04"
      onNext={completeStep}
      nextDisabled={loading || !summary || !!error || !safeArray<OutlierFeature>(summary.features).length || applying}
      nextDisabledReason={error || "Load the full-data outlier profile before continuing."}
      nextStatusLine={applied ? "The current full-data treatment configuration is applied and ready for Missing Values." : "The selected treatments will be applied to the full dataset before navigation."}
    >
      {loading ? <div className="atlas-workflow-section flex min-h-56 items-center justify-center"><LoaderCircle className="animate-spin text-blue-600" size={28} /></div> : null}
      {error ? <AtlasAttentionPanel title="Outlier analysis is unavailable because the feature profile could not be loaded" tone="danger"><div className="space-y-3"><p>{error}</p><div className="flex flex-wrap gap-2"><button type="button" className="atlas-primary-button" onClick={() => void loadSummary()}>Retry</button><a className="atlas-secondary-button" href="/step01">Go to Data Acquisition</a><a className="atlas-secondary-button" href="/step02">Go to EDA</a></div><details className="rounded-lg border border-red-200 bg-white p-3"><summary className="cursor-pointer text-sm font-semibold text-red-950">Technical details</summary><pre className="mt-2 whitespace-pre-wrap text-xs text-slate-700">{error}</pre></details></div></AtlasAttentionPanel> : null}
      {summary ? (
        <div className="space-y-5">
          <AtlasStatusStrip items={[
            { label: "Registered population", state: "complete", detail: `${summary.row_count.toLocaleString()} rows` },
            { label: "Treatment selection", state: "complete", detail: `${safeArray<OutlierFeature>(summary.features).length.toLocaleString()} numeric predictors` },
            { label: "Backend materialization", state: applied ? "complete" : "warning", detail: applied ? "Current" : "Selected, not applied" },
          ]} />

          {summary.rare_event ? (
            <AtlasAttentionPanel title="Rare-event treatment review" tone="warning">
              The governed event rate is {pct(summary.event_rate)}. Extreme values may carry disproportionate signal in rare-event models. Preserve operationally plausible tails unless there is a documented quality or stability reason to cap them.
            </AtlasAttentionPanel>
          ) : null}

          <AtlasWorkflowSection
            eyebrow="Treatment Policy"
            title="Global method and feature overrides"
            description="Selections remain recommendations until ATLAS applies them to the full backend dataset."
            tone="info"
            action={<AtlasDataScopeBadge scope="full_dataset" rows={summary.row_count} />}
          >
            <div className="grid gap-4 lg:grid-cols-[minmax(260px,380px)_minmax(0,1fr)_auto] lg:items-end">
              <label className="grid gap-1 text-sm font-medium text-slate-700">
                Global method
                <select className="atlas-input" value={globalMethod} onChange={(event) => { setGlobalMethod(event.target.value as MethodKey); setMessage("Global method changed. Apply treatments to materialize the change."); }}>
                  {METHOD_OPTIONS.map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}
                </select>
                <span className="text-xs font-normal leading-5 text-slate-500">{METHOD_OPTIONS.find((option) => option.key === globalMethod)?.guidance}</span>
              </label>
              <div className="text-sm leading-6 text-slate-600">Use the global policy as a controlled default, then override only variables whose business meaning or tail behavior requires a different decision.</div>
              <button type="button" className="atlas-secondary-button" onClick={applyGlobalSelection}><SlidersHorizontal size={16} /> Use global for all</button>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-slate-200 pt-4">
              <AtlasExecutionStatus state={applying ? "running" : applied ? "complete" : "idle"} label={applying ? "Applying full-data treatments" : applied ? "Current configuration applied" : "Selections not yet applied"} detail={summary.application?.applied_at ? `Last applied ${new Date(summary.application.applied_at).toLocaleString()}` : "Apply explicitly or continue to materialize treatments."} />
              <button type="button" className="atlas-primary-button" onClick={() => void applyTreatments()} disabled={applying}><Play size={16} /> Apply treatments</button>
            </div>
          </AtlasWorkflowSection>

          {message ? <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">{message}</div> : null}

          <AtlasWorkflowSection eyebrow="Feature Review" title="Numeric predictor treatments" description="Counts and signal metrics use the full dataset. Histograms use a bounded rendered sample and do not define treatment counts.">
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <label className="relative min-w-64 flex-1">
                <Search size={16} className="pointer-events-none absolute left-3 top-2.5 text-slate-400" />
                <input className="atlas-input pl-9" value={search} onChange={(event) => { setSearch(event.target.value); setPage(0); }} placeholder="Search predictors" aria-label="Search predictors" />
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-600"><Filter size={16} /><select className="atlas-input min-w-48" value={sortBy} onChange={(event) => { setSortBy(event.target.value as typeof sortBy); setPage(0); }}><option value="signal">Signal strength</option><option value="outliers">Flagged values</option><option value="name">Feature name</option></select></label>
            </div>
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="min-w-[860px] w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500"><tr><th className="px-3 py-2">Feature</th><th className="px-3 py-2">Full-data flagged</th><th className="px-3 py-2">Rate</th><th className="px-3 py-2">{summary.problem_type === "regression" ? "Correlation" : "IV"}</th><th className="px-3 py-2">Selected treatment</th></tr></thead>
                <tbody>{pagedRows.map((row) => {
                  const method = row.methods?.[effectiveMethod(config[row.feature], globalMethod)] ?? { method: "NONE" as MethodKey, lower_threshold: 0, upper_threshold: 0, outlier_count: 0, outlier_rate: 0 };
                  return <tr key={row.feature} className={`border-t border-slate-100 hover:bg-blue-50 ${selected?.feature === row.feature ? "bg-blue-50" : ""}`} onClick={() => setSelectedFeature(row.feature)}>
                    <td className="cursor-pointer px-3 py-2 font-medium text-slate-900">{row.feature}</td>
                    <td className="px-3 py-2 tabular-nums">{method.outlier_count.toLocaleString()}</td>
                    <td className="px-3 py-2 tabular-nums">{pct(method.outlier_rate)}</td>
                    <td className="px-3 py-2 tabular-nums">{fmt(row.signal_metric)}</td>
                    <td className="px-3 py-2" onClick={(event) => event.stopPropagation()}><select className="atlas-input min-w-56" value={config[row.feature] ?? "USE_GLOBAL"} onChange={(event) => changeFeature(row.feature, event.target.value as FeatureMethodKey)}><option value="USE_GLOBAL">Use global method</option>{METHOD_OPTIONS.map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}</select></td>
                  </tr>;
                })}</tbody>
              </table>
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500"><span>Showing {rows.length ? page * PAGE_SIZE + 1 : 0}-{Math.min((page + 1) * PAGE_SIZE, rows.length)} of {rows.length.toLocaleString()}</span><div className="flex items-center gap-2"><button className="atlas-secondary-button" type="button" disabled={page === 0} onClick={() => setPage((current) => Math.max(0, current - 1))}>Previous</button><span>Page {page + 1} of {pageCount}</span><button className="atlas-secondary-button" type="button" disabled={page >= pageCount - 1} onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}>Next</button></div></div>
          </AtlasWorkflowSection>

          {selected && selectedMethod ? (
            <AtlasWorkflowSection eyebrow="Selected Predictor" title={selected.feature} description={`${selected.rendered_sample_count.toLocaleString()} values are rendered from ${selected.nonmissing_count.toLocaleString()} nonmissing full-data values.`} tone="neutral" action={<AtlasDataScopeBadge scope="rendered_sample" rows={selected.rendered_sample_count} />}>
              <div className="grid gap-4 lg:grid-cols-2"><Histogram values={safeArray<number>(selected.rendered_sample)} method={selectedMethod} /><Histogram values={safeArray<number>(selected.rendered_sample)} method={selectedMethod} after /></div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3"><div className="text-xs uppercase text-slate-500">Full-data flagged</div><div className="mt-1 text-lg font-semibold">{selectedMethod.outlier_count.toLocaleString()}</div></div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3"><div className="text-xs uppercase text-slate-500">Applied method</div><div className="mt-1 font-semibold">{METHOD_OPTIONS.find((option) => option.key === selectedMethod.method)?.label}</div></div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3"><div className="text-xs uppercase text-slate-500">Median</div><div className="mt-1 text-lg font-semibold">{fmt(selected.quantiles.median, 3)}</div></div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3"><div className="text-xs uppercase text-slate-500">Selection state</div><div className={`mt-1 flex items-center gap-2 font-semibold ${applied ? "text-emerald-700" : "text-amber-700"}`}>{applied ? <CheckCircle2 size={16} /> : null}{applied ? "Applied" : "Selected only"}</div></div>
              </div>
            </AtlasWorkflowSection>
          ) : null}
        </div>
      ) : null}
    </StepShell>
  );
}

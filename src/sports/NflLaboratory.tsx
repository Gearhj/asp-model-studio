import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Download, FlaskConical, RefreshCw, ShieldCheck } from "lucide-react";
import { BASE } from "../lib/api";

type MetricRow = {
  pipelineId?: string; id?: string; family?: string; treatment?: string; design?: string; featureVariant?: string;
  games?: number; observations?: number; multiclassLogLoss?: number; calibratedLogLoss?: number;
  multiclassBrier?: number; marginMae?: number; totalMae?: number; status?: string;
  metrics?: Record<string, number>; earlySeasonMetrics?: Record<string, number>;
  subgroups?: Record<string, Record<string, number>>;
};
type Artifact = { id: string; label: string; category: string; href: string; sha256: string; bytes: number; filename: string };
type Laboratory = {
  status: string; promotionStatus: string; retainedModel: string; wageringAuthority: boolean;
  groups: Array<{ id: string; label: string; status: string; rows: MetricRow[]; note: string; pairedComparison?: unknown }>;
  artifacts: Artifact[]; treatments: Record<string, string>; featureVariants: Record<string, string>; warnings: string[];
};

const number = (value: unknown, places = 4) => typeof value === "number" && Number.isFinite(value) ? value.toFixed(places) : "Not available";
const metric = (row: MetricRow, key: keyof MetricRow): number | undefined => {
  const value = row[key] ?? row.metrics?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
};

export default function NflLaboratory() {
  const [data, setData] = useState<Laboratory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [query, setQuery] = useState("");
  const [metricMode, setMetricMode] = useState<"multiclassLogLoss" | "calibratedLogLoss">("multiclassLogLoss");
  const [cohort, setCohort] = useState("FULL_SEASON");
  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    fetch(`${BASE}/sports/nfl/laboratory`, { credentials: "include", signal: controller.signal, headers: { Accept: "application/json" } })
      .then(async response => {
        if (response.status === 401) throw new Error("Sign in to Model Studio to view the registered NFL laboratory.");
        if (response.status === 403) throw new Error("Your account needs access to the NFL laboratory project.");
        if (!response.ok) throw new Error(`NFL laboratory evidence could not be loaded (HTTP ${response.status}).`);
        return response.json() as Promise<Laboratory>;
      }).then(setData).catch(reason => { if (reason.name !== "AbortError") setError(reason.message); });
    return () => controller.abort();
  }, [reload]);
  const groups = useMemo(() => (data?.groups ?? []).map(group => ({ ...group,
    rows: group.rows.filter(row => JSON.stringify([row.pipelineId, row.id, row.family, row.treatment, row.design]).toLowerCase().includes(query.toLowerCase()))
      .map(row => cohort === "FULL_SEASON" ? row : ({ pipelineId: row.pipelineId, id: row.id, family: row.family, treatment: row.treatment, design: row.design, ...(row.subgroups?.[cohort] ?? {}) })),
  })), [data, query, cohort]);
  const count = data?.groups.reduce((sum, group) => sum + group.rows.length, 0) ?? 0;
  const chartRows = groups.flatMap(group => group.rows.map(row => ({ ...row, group: group.label })))
    .filter(row => metric(row, metricMode) !== undefined).sort((a, b) => metric(a, metricMode)! - metric(b, metricMode)!).slice(0, 8);
  const categories = [...new Set(data?.artifacts.map(artifact => artifact.category) ?? [])];

  return <section id="nfl-laboratory" className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6" aria-labelledby="nfl-laboratory-heading">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-blue-700"><FlaskConical size={16} /> NFL research laboratory</div>
        <h2 id="nfl-laboratory-heading" className="mt-2 text-2xl font-semibold text-slate-900">Models, semantic treatments and evidence</h2>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-600">Completed Development comparisons and saved artifacts. Reopening this page does not fit a model or rerun a study.</p>
      </div>
      <button type="button" onClick={() => setReload(value => value + 1)} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700"><RefreshCw size={15} /> Refresh evidence</button>
    </div>
    <div className="mt-5 flex flex-wrap gap-2 text-xs font-semibold">
      {["RESEARCH SHADOW", "NOT PROMOTED", "NO WAGERING AUTHORITY", "FINAL OOT SEALED"].map(label => <span key={label} className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-blue-900">{label}</span>)}
    </div>
    {error ? <div role="alert" className="mt-5 flex gap-2 rounded-xl bg-amber-50 p-4 text-sm text-amber-950"><AlertCircle size={18} /> {error}</div> : !data ? <p role="status" className="mt-6 text-sm text-slate-600">Loading saved laboratory evidence…</p> : <>
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <Summary label="Saved completed results" value={String(count)} detail="Original and semantic studies remain separately identified" />
        <Summary label="Retained reference model" value={data.retainedModel} detail="Research completion does not change model authority" />
        <Summary label="Verified artifact links" value={String(data.artifacts.length)} detail="Original checksums rechecked before download" />
      </div>
      <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-700"><ShieldCheck className="mr-2 inline text-blue-600" size={18} />Raw scores and their joint distribution are separate from calibrated home/away/tie probabilities unless a verified distribution adjustment says otherwise. Lower loss is better; rankings after model selection are exploratory, not independent proof of improvement.</div>
      <details className="mt-5 rounded-xl border border-slate-200 p-4" open>
        <summary className="cursor-pointer font-semibold text-slate-900">What the treatments mean</summary>
        <dl className="mt-4 grid gap-4 text-sm md:grid-cols-2">{Object.entries(data.treatments).map(([name, definition]) => <div key={name}><dt className="font-semibold text-blue-800">{name}</dt><dd className="mt-1 leading-6 text-slate-600">{definition}</dd></div>)}</dl>
        <p className="mt-4 text-xs leading-5 text-slate-500">T0–T2 are legacy generic-treatment comparisons, not the new semantic cold-start implementation. C1–C3 appear as completed results only when supported evidence was actually run. Unsupported quarterback information is not treated as a known starter.</p>
        <dl className="mt-3 text-xs leading-5 text-slate-600">{Object.entries(data.featureVariants).map(([name, definition]) => <div key={name}><dt className="inline font-semibold">{name}: </dt><dd className="inline">{definition}</dd></div>)}</dl>
      </details>
      <div className="mt-6 flex flex-wrap items-end justify-between gap-3">
        <label className="text-sm font-medium text-slate-700">Filter models or treatments<input value={query} onChange={event => setQuery(event.target.value)} placeholder="For example: C1, XGBOOST or T2" className="mt-1 block w-72 rounded-lg border border-slate-300 px-3 py-2 font-normal" /></label>
        <label className="text-sm font-medium text-slate-700">Evaluation cohort<select value={cohort} onChange={event => setCohort(event.target.value)} className="ml-2 rounded-lg border border-slate-300 px-3 py-2"><option value="FULL_SEASON">Full season</option><option value="WEEKS_1_4">Weeks 1–4</option><option value="WEEKS_1_2">Weeks 1–2</option></select></label>
        <label className="text-sm font-medium text-slate-700">Chart probability scale<select value={metricMode} onChange={event => setMetricMode(event.target.value as typeof metricMode)} className="ml-2 rounded-lg border border-slate-300 px-3 py-2"><option value="multiclassLogLoss">Raw three-way log loss</option><option value="calibratedLogLoss">Calibrated three-way log loss</option></select></label>
      </div>
      <figure className="mt-5 rounded-xl border border-slate-200 p-4" aria-label="Exploratory log-loss comparison">
        <figcaption className="mb-3 text-sm font-semibold text-slate-800">Lowest eight available losses · {metricMode === "multiclassLogLoss" ? "raw" : "calibrated"} · absolute scale 0–1</figcaption>
        <div className="space-y-3">{chartRows.map(row => <div key={`${row.group}-${row.pipelineId ?? row.id}`} className="grid gap-1 md:grid-cols-[20rem_1fr_5rem] md:items-center"><span className="break-all text-xs text-slate-700">{row.pipelineId ?? row.id}</span><div className="h-4 rounded bg-slate-100"><div className="h-4 rounded bg-blue-600" style={{ width: `${Math.min(1, metric(row, metricMode)!) * 100}%` }} /></div><span className="text-xs tabular-nums text-slate-700">{number(metric(row, metricMode), 6)}</span></div>)}</div>
        {!chartRows.length && <p className="text-sm text-slate-500">No completed measurements match this filter and probability scale.</p>}
        <p className="mt-3 text-xs text-slate-500">Only same-cohort paired results support comparisons. A missing calibrated value is unavailable, not zero.</p>
      </figure>
      {groups.map(group => <div key={group.id} className="mt-6">
        <h3 className="text-lg font-semibold text-slate-900">{group.label}</h3><p className="mt-1 text-sm leading-6 text-slate-600">{group.note}</p>
        <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-xs"><caption className="sr-only">{group.label} results</caption><thead className="bg-slate-100 text-slate-700"><tr>{["Pipeline", "Treatment", "Games", "Raw log loss", "Calibrated log loss", "Summed 3-way Brier", "Margin MAE, pts", "Total MAE, pts"].map(label => <th key={label} className="whitespace-nowrap px-3 py-3 font-semibold">{label}</th>)}</tr></thead><tbody>{group.rows.map(row => <tr key={row.pipelineId ?? row.id} className="border-b border-slate-100"><td className="px-3 py-3 font-medium text-slate-800">{row.pipelineId ?? row.id}</td><td className="px-3 py-3">{row.treatment ?? row.design ?? "Declared baseline"}</td><td className="px-3 py-3 tabular-nums">{metric(row, "games") ?? row.observations ?? "—"}</td>{(["multiclassLogLoss", "calibratedLogLoss", "multiclassBrier", "marginMae", "totalMae"] as const).map(key => <td key={key} className="whitespace-nowrap px-3 py-3 tabular-nums">{number(metric(row, key), key.includes("Mae") ? 3 : 6)}</td>)}</tr>)}</tbody></table></div>
        {group.pairedComparison ? <details className="mt-3 rounded-lg bg-slate-50 p-3"><summary className="cursor-pointer text-sm font-semibold text-slate-700">Matched-cohort paired comparison and uncertainty</summary><pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs leading-5 text-slate-600">{JSON.stringify(group.pairedComparison, null, 2)}</pre></details> : null}
      </div>)}
      <div className="mt-7"><h3 className="text-lg font-semibold text-slate-900">Verified research artifacts</h3><p className="mt-1 text-sm text-slate-600">Downloads contain research evidence only. Models are not executed by AISP.</p>
        {categories.map(category => <details key={category} className="mt-3 rounded-xl border border-slate-200 p-4" open={!category.includes("predictions")}><summary className="cursor-pointer text-sm font-semibold text-slate-800">{category} ({data.artifacts.filter(item => item.category === category).length})</summary><ul className="mt-3 grid gap-3 md:grid-cols-2">{data.artifacts.filter(item => item.category === category).map(artifact => <li key={artifact.id}><a href={`${BASE}${artifact.href}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm font-medium text-blue-700 underline decoration-blue-200 underline-offset-4"><Download size={14} />{artifact.label}</a><p className="mt-1 break-all text-[10px] text-slate-500">{artifact.bytes.toLocaleString()} bytes · SHA-256 {artifact.sha256}</p></li>)}</ul></details>)}
      </div>
      {data.warnings.length > 0 && <div role="status" className="mt-5 rounded-xl bg-amber-50 p-4 text-sm text-amber-950"><p className="font-semibold">Evidence limitations</p><ul className="mt-2 list-disc space-y-1 pl-5">{data.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul></div>}
    </>}
  </section>;
}

function Summary({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-xl border border-slate-200 p-4"><p className="text-xs font-medium text-slate-500">{label}</p><p className="mt-2 break-words text-lg font-semibold text-slate-900">{value}</p><p className="mt-2 text-xs leading-5 text-slate-500">{detail}</p></div>;
}

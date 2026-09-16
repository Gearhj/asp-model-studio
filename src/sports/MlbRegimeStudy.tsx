import { useEffect, useState } from "react";
import { AlertCircle, Download, FlaskConical, RefreshCw } from "lucide-react";
import { BASE } from "../lib/api";
import { Card, MetricCard, Pill } from "./cockpit/cockpitUi";

type Value = string | number | boolean | null | Value[] | { [key: string]: Value };
type Row = { [key: string]: Value };
type Artifact = { id: string; label: string; category: string; href: string; sha256: string; bytes: number };
type Study = {
  status: string; studyId?: string; completedAtUtc?: string; verdict?: string;
  cohort?: Row; baselineParity?: Row; gameSimulation?: Row; authority?: Row;
  clusterProfiles?: Row[]; stability?: Row[]; failureRegimes?: Row[]; specialistEligibility?: Row[];
  leaderboard?: Row[]; influence?: Row[]; calibration?: Row[];
  selectedArchitecture?: string; diagnosticChallenger?: string; selection?: Row; coldStart?: Row; currentShadow?: Row;
  uncertaintyIntervals?: Row; foldMetrics?: Row[]; regimeMetrics?: Row[]; monthlyEvaluation?: Row[]; removalSensitivity?: Row[];
  artifacts: Artifact[]; limitations?: Value[]; warnings: string[];
};

const label = (key: string) => key.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/[_-]/g, " ");
const display = (value: Value | undefined): string => {
  if (value === null || value === undefined) return "Not available";
  if (typeof value === "number") return Number.isFinite(value) ? (Number.isInteger(value) ? value.toLocaleString() : value.toFixed(6)) : "Not available";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map(display).join(" · ") || "Not available";
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${label(key)}: ${display(item)}`).join("; ") || "Not available";
  return value;
};

function Facts({ value }: { value?: Row }) {
  if (!value || !Object.keys(value).length) return <p className="text-sm text-slate-500">Not available in this publication.</p>;
  return <dl className="grid gap-x-6 gap-y-3 text-xs md:grid-cols-2">{Object.entries(value).map(([key, item]) => <div key={key}><dt className="font-semibold capitalize text-slate-700">{label(key)}</dt><dd className="mt-1 break-words leading-5 text-slate-600">{typeof item === "object" && item !== null ? <details><summary className="cursor-pointer text-cyan-800">{Array.isArray(item) ? `${item.length} recorded entries` : "Recorded details"}</summary><p className="mt-2 whitespace-pre-wrap">{display(item)}</p></details> : display(item)}</dd></div>)}</dl>;
}

function EvidenceTable({ title, note, rows = [] }: { title: string; note: string; rows?: Row[] }) {
  const columns = [...new Set(rows.flatMap(row => Object.keys(row)))];
  return <details className="rounded-xl border border-slate-200 p-4" open={title === "Global and specialist comparison" || title === "Cluster profiles and populations"}>
    <summary className="cursor-pointer text-sm font-semibold text-slate-900">{title}{rows.length > 0 ? ` (${rows.length})` : ""}</summary>
    <p className="mt-2 text-xs leading-5 text-slate-500">{note}</p>
    {!rows.length ? <p className="mt-3 text-sm text-amber-800">Not available or not supported in this publication; no zero value is inferred.</p> : <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-xs"><caption className="sr-only">{title}</caption><thead className="bg-slate-50"><tr>{columns.map(key => <th key={key} scope="col" className="whitespace-nowrap px-3 py-2 font-semibold capitalize text-slate-600">{label(key)}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index} className="border-b border-slate-100">{columns.map(key => <td key={key} className="min-w-28 max-w-lg px-3 py-3 align-top leading-5 text-slate-700">{typeof row[key] === "object" && row[key] !== null ? <details><summary className="cursor-pointer text-cyan-800">Recorded details</summary><p className="mt-2 min-w-64 whitespace-pre-wrap break-words">{display(row[key])}</p></details> : display(row[key])}</td>)}</tr>)}</tbody></table></div>}
  </details>;
}

function FailureHeatmap({ rows = [], classOrder = [] }: { rows?: Row[]; classOrder?: Value[] }) {
  // Discovery publishes membership-weighted observed-minus-predicted residuals,
  // not later specialist loss deltas. Keep both the fold and class axes intact.
  const cells = rows.flatMap(row => Array.isArray(row.foldEvidence) ? row.foldEvidence.flatMap(evidence => {
    if (!evidence || typeof evidence !== "object" || Array.isArray(evidence) || !Array.isArray(evidence.residual)) return [];
    return [{ name: `${display(row.clusterId)} · fold ${display(evidence.fold)}`, residual: evidence.residual }];
  }) : []);
  if (!cells.length) return null;
  const scale = Math.max(...cells.flatMap(row => row.residual.filter((value): value is number => typeof value === "number" && Number.isFinite(value)).map(Math.abs)), 0.000001);
  return <figure className="rounded-xl border border-slate-200 p-4"><figcaption className="text-sm font-semibold text-slate-900">Discovery failure-regime residual heatmap</figcaption><p className="mt-1 text-xs leading-5 text-slate-500">Membership-weighted observed minus global-predicted class frequency. Positive means the class occurred more often than predicted. This is earlier discovery evidence, not specialist performance or a later evaluation result.</p><div className="mt-3 overflow-x-auto"><table className="w-full text-left text-[11px]"><thead><tr><th scope="col" className="px-2 py-2">Regime and discovery fold</th>{classOrder.map((name, index) => <th key={index} scope="col" className="px-2 py-2">{display(name)}</th>)}</tr></thead><tbody>{cells.map((row, index) => <tr key={index}><th scope="row" className="whitespace-nowrap px-2 py-2 font-medium">{row.name}</th>{row.residual.map((value, column) => {
    const number = typeof value === "number" && Number.isFinite(value) ? value : null;
    return <td key={column} className="px-2 py-2 tabular-nums" style={number === null ? undefined : { backgroundColor: `rgba(${number < 0 ? "6,182,212" : "244,63,94"},${0.05 + 0.25 * Math.abs(number) / scale})` }}>{number === null ? "Not available" : `${number > 0 ? "+" : ""}${number.toFixed(4)}`}</td>;
  })}</tr>)}</tbody></table></div></figure>;
}

export default function MlbRegimeStudy() {
  const [data, setData] = useState<Study | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [phase, setPhase] = useState("EVALUATION_RAW");
  const [calibrationModel, setCalibrationModel] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    fetch(`${BASE}/sports/mlb/regime-study`, { credentials: "include", signal: controller.signal, headers: { Accept: "application/json" } })
      .then(async response => {
        if (response.status === 401) throw new Error("Sign in to view the saved MLB study.");
        if (response.status === 403) throw new Error("Your account needs access to the MLB study project.");
        if (!response.ok) throw new Error(`MLB study evidence could not be loaded (HTTP ${response.status}).`);
        return response.json() as Promise<Study>;
      }).then(setData).catch(reason => { if (reason.name !== "AbortError") setError(reason.message); });
    return () => controller.abort();
  }, [reload]);
  const phases = [...new Set((data?.leaderboard ?? []).map(row => row.phase).filter((value): value is string => typeof value === "string"))];
  const selectedPhase = phases.includes(phase) ? phase : phases[0];
  const selectedModel = calibrationModel || data?.diagnosticChallenger || data?.selectedArchitecture || "V18";
  const calibrationRows = (data?.calibration ?? []).filter(row => row.phase === selectedPhase && (row.model === "V18" || row.model === selectedModel)).flatMap(row => Array.isArray(row.perClass) ? row.perClass.filter((item): item is Row => item !== null && typeof item === "object" && !Array.isArray(item)).map(item => ({ model: row.model, phase: row.phase, ...item })) : []);

  return <section id="mlb-regime-study" aria-label="MLB regime and hybrid study">
    <Card title="MLB regime and hybrid study" icon={FlaskConical} description="Saved Development evidence: stable player/context groups, bounded specialists and the unchanged global fallback. Viewing this section never starts a model or simulation." action={<button type="button" onClick={() => setReload(value => value + 1)} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700"><RefreshCw size={14} />Refresh evidence</button>}>
      <div className="flex flex-wrap gap-2"><Pill label="Research only" tone="cyan" /><Pill label="Not promoted" /><Pill label="No wagering authority" /><Pill label="Final OOT sealed" tone="amber" /></div>
      {error ? <div role="alert" className="mt-4 flex gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"><AlertCircle size={16} />{error}</div> : !data ? <p role="status" className="mt-4 text-sm text-slate-500">Loading saved study evidence…</p> : <div className="mt-5 space-y-5">
        <div className="grid gap-3 md:grid-cols-3"><MetricCard label="Publication state" value={data.status.replace(/_/g, " ")} /><MetricCard label="Verified artifact links" value={String(data.artifacts.length)} detail="Checksums and byte counts verified" /><MetricCard label="Evidence completed" value={data.completedAtUtc ?? "Not available"} detail="Not a refreshed forecast or source-evidence timestamp" /></div>
        {data.verdict && <p className="rounded-lg bg-slate-50 p-3 text-sm leading-6 text-slate-700"><b>Scientific conclusion:</b> {data.verdict.replace(/_/g, " ")}</p>}
        {data.studyId && <p className="break-all text-xs text-slate-500">Study: {data.studyId}</p>}
        <details className="rounded-xl border border-slate-200 p-4" open><summary className="cursor-pointer text-sm font-semibold text-slate-900">Development dates, populations and baseline parity</summary><div className="mt-3 space-y-4"><Facts value={data.cohort} /><Facts value={data.baselineParity} /></div></details>
        {phases.length > 0 && <label className="block text-xs font-semibold text-slate-700">Comparison population and probability scale<select value={selectedPhase} onChange={event => setPhase(event.target.value)} className="ml-3 rounded-lg border border-slate-300 bg-white px-3 py-2 font-normal">{phases.map(value => <option key={value} value={value}>{label(value)}</option>)}</select></label>}
        <EvidenceTable title="Global and specialist comparison" rows={data.leaderboard?.filter(row => row.phase === selectedPhase)} note="Compare matching chronological evaluation populations and probability definitions. Earlier discovery or weight-fitting periods are not independent evaluation evidence." />
        <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm font-semibold text-slate-900">Frozen architecture selection</summary><div className="mt-3"><Facts value={{ selectedArchitecture: data.selectedArchitecture ?? null, diagnosticChallenger: data.diagnosticChallenger ?? null, ...data.selection }} /></div></details>
        <EvidenceTable title="Cluster profiles and populations" rows={data.clusterProfiles} note="Definitions, feature profiles, population/exposure and interpretation come from the published train-era specification." />
        <EvidenceTable title="Chronological cluster stability" rows={data.stability} note="Membership stability and adequate exposure matter; statistical separation alone does not establish predictive value." />
        <FailureHeatmap rows={data.failureRegimes} classOrder={Array.isArray(data.authority?.classOrder) ? data.authority.classOrder : []} />
        <EvidenceTable title="Persistent failure regimes" rows={data.failureRegimes} note="Earlier out-of-fold evidence defines failure regimes; later evaluation cannot redefine its own specialists." />
        <EvidenceTable title="Specialist eligibility and fallback" rows={data.specialistEligibility} note="Unsupported or undersized regimes retain the global fallback. Qualification is not model promotion." />
        <EvidenceTable title="Specialist influence and sensitivity" rows={data.influence} note="Recorded affected fractions, adjustment magnitudes and removal checks; missing checks remain unavailable." />
        <EvidenceTable title="Matched regime evaluation" rows={data.regimeMetrics} note="Later evaluation remains distinct from the earlier failure-regime discovery criteria." />
        <EvidenceTable title="Cluster, month and team removal sensitivity" rows={data.removalSensitivity} note="Removal diagnostics do not redefine or refit the frozen architecture." />
        <label className="block text-xs font-semibold text-slate-700">Calibration comparison with V18<select value={selectedModel} onChange={event => setCalibrationModel(event.target.value)} className="ml-3 rounded-lg border border-slate-300 bg-white px-3 py-2 font-normal">{[...new Set((data.calibration ?? []).map(row => row.model).filter((value): value is string => typeof value === "string"))].map(value => <option key={value}>{value}</option>)}</select></label>
        <EvidenceTable title="Per-class calibration and reliability" rows={calibrationRows} note="Shows V18 and the selected saved comparison on the selected population/scale. Intercept and slope are evaluation diagnostics, not fitted forecast calibration in this view. Empty reliability bins remain unavailable." />
        <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm font-semibold text-slate-900">Dependence-aware paired uncertainty</summary><p className="mt-2 text-xs leading-5 text-slate-500">Game, temporal-block and repeated-identity sensitivities are separately identified, not one joint-dependence guarantee.</p><div className="mt-3"><Facts value={data.uncertaintyIntervals} /></div></details>
        <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm font-semibold text-slate-900">Cold-start evidence and current-shadow disposition</summary><div className="mt-3 space-y-4"><Facts value={data.coldStart} /><Facts value={data.currentShadow} /></div></details>
        <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm font-semibold text-slate-900">PA-to-game simulator comparison</summary><div className="mt-3"><Facts value={data.gameSimulation} /></div></details>
        <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm font-semibold text-slate-900">Evidence authority</summary><div className="mt-3"><Facts value={data.authority} /></div></details>
        <div><h3 className="text-sm font-semibold text-slate-900">Verified research artifacts</h3><p className="mt-1 text-xs text-slate-500">Export access is required. AISP receives precomputed evidence only; this study grants no execution or wagering authority.</p><ul className="mt-3 grid gap-3 md:grid-cols-2">{data.artifacts.map(artifact => <li key={artifact.id}><a href={`${BASE}${artifact.href}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm text-cyan-800 underline"><Download size={14} />{artifact.label}</a><p className="mt-1 break-all text-[10px] leading-4 text-slate-500">{artifact.category} · {artifact.bytes.toLocaleString()} bytes · SHA-256 {artifact.sha256}</p></li>)}</ul></div>
        {(data.limitations?.length || data.warnings.length) ? <div role="status" className="rounded-xl bg-amber-50 p-4 text-sm text-amber-950"><h3 className="font-semibold">Source, timing and applicability limitations</h3><ul className="mt-2 list-disc space-y-2 pl-5">{[...(data.limitations ?? []).map(display), ...data.warnings].map((warning, index) => <li key={index} className="leading-6">{warning}</li>)}</ul></div> : null}
      </div>}
    </Card>
  </section>;
}

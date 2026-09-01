import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FlaskConical,
  Gauge,
  Layers3,
  Loader2,
  Lock,
  Play,
  RefreshCw,
  ShieldCheck,
  TableProperties,
} from "lucide-react";
import {
  fetchProjectModelLabRuns,
  fetchProjectModelLabSummary,
  runProjectModelLab,
  type ModelLabCandidatePlan,
  type ModelLabRun,
  type ProjectModelLabSummary,
} from "./projectModelLabApi";

type LoadState = "loading" | "ready" | "error";

const int = (value: number) => new Intl.NumberFormat("en-US").format(value);
const decimal = (value: number | null, digits = 6) => value == null ? "—" : value.toFixed(digits);
const duration = (value: number | null) => value == null ? "—" : value < 1_000 ? `${Math.round(value)} ms` : `${(value / 1_000).toFixed(1)} s`;
const short = (value: string) => value.length > 18 ? `${value.slice(0, 14)}…` : value;
const human = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

export function ProjectBoundModelLab({ projectId }: { projectId: string }) {
  const [state, setState] = useState<LoadState>("loading");
  const [summary, setSummary] = useState<ProjectModelLabSummary | null>(null);
  const [runs, setRuns] = useState<ModelLabRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [selectedFeatureSetIds, setSelectedFeatureSetIds] = useState<string[]>([]);
  const [selectedFamilies, setSelectedFamilies] = useState<string[]>([]);
  const selectionAuthority = useRef<string | null>(null);
  const request = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setState("loading");
    setError(null);
    try {
      const next = await fetchProjectModelLabSummary(projectId, controller.signal);
      if (controller.signal.aborted) return;
      setSummary(next);
      if (selectionAuthority.current !== next.authority.authorityKey) {
        selectionAuthority.current = next.authority.authorityKey;
        setSelectedFeatureSetIds(next.featureSets.map((item) => item.featureSetId));
        setSelectedFamilies(next.modelFamilies.filter((item) => item.available).map((item) => item.id));
      }
      try {
        const history = await fetchProjectModelLabRuns(projectId, next, controller.signal);
        if (!controller.signal.aborted) setRuns(history);
      } catch {
        if (!controller.signal.aborted) setRuns(next.latestRun ? [next.latestRun] : []);
      }
      setState("ready");
    } catch (caught) {
      if (controller.signal.aborted) return;
      setSummary(null);
      setRuns([]);
      setState("error");
      setError(caught instanceof Error ? caught.message : "The project-bound Model Laboratory authority could not be loaded.");
    }
  }, [projectId]);

  useEffect(() => {
    void load();
    return () => request.current?.abort();
  }, [load]);

  const candidates = useMemo(() => {
    if (!summary) return [];
    return summary.candidateMatrix.filter((item) =>
      selectedFamilies.includes(item.modelFamily)
      && (item.featureSetId == null || selectedFeatureSetIds.includes(item.featureSetId)),
    );
  }, [selectedFamilies, selectedFeatureSetIds, summary]);

  const execute = async () => {
    if (!summary || !summary.readiness.ready || !candidates.length || running) return;
    setRunning(true);
    setRunError(null);
    try {
      const result = await runProjectModelLab(
        projectId,
        summary,
        candidates.map((item) => ({ modelFamily: item.modelFamily, featureSetId: item.featureSetId })),
      );
      setRuns((current) => [result, ...current.filter((item) => item.runId !== result.runId)]);
    } catch (caught) {
      setRunError(caught instanceof Error ? caught.message : "The first-pass competition failed closed.");
    } finally {
      setRunning(false);
    }
  };

  if (state === "loading") return <Loading />;
  if (state === "error" || !summary) return <Failure message={error || "Project authority unavailable."} retry={load} />;

  const latest = runs[0] ?? summary.latestRun;
  return (
    <div className="min-w-0 space-y-4" data-testid="stage3-project-bound-model-laboratory">
      <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white shadow-sm" data-testid="model-lab-project-context">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/10 px-4 py-4 sm:px-5">
          <div>
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-300"><FlaskConical size={14} />Project-bound Model Laboratory</div>
            <h2 className="mt-1 text-xl font-semibold">First current-data MLB challenger competition</h2>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-300">Explicit development-only execution across the exact registered feature sets and five chronological folds. Opening this page never fits a model.</p>
          </div>
          <StatusBadge ready={summary.readiness.ready} />
        </div>
        <div className="grid gap-px bg-white/10 sm:grid-cols-2 xl:grid-cols-4">
          <DarkFact label="Project" value={summary.authority.projectName} detail={summary.authority.projectId} />
          <DarkFact label="Development" value={`${int(summary.population.developmentRows)} rows`} detail={`${summary.population.startDate} → ${summary.population.endDate}`} />
          <DarkFact label="Final OOT" value={`${int(summary.population.finalOotRows)} locked`} detail="Targets not materialized or queried" tone="rose" />
          <DarkFact label="Target" value={`${summary.target.orderedClasses.length}-class ${summary.target.name}`} detail="Primary metric · multiclass log loss" />
        </div>
      </section>

      {!summary.readiness.ready ? <BlockingReasons blockers={summary.readiness.blockers} /> : null}

      <section className="grid min-w-0 gap-4 xl:grid-cols-2">
        <AuthorityCard title="Exact scientific authority" icon={<ShieldCheck size={16} />}>
          <AuthorityRows rows={[
            ["Current Gold", summary.authority.goldDatasetId, summary.authority.goldManifestSha],
            ["Split contract", `v${summary.split.version} · ${summary.split.foldCount} folds`, summary.split.splitContractId],
            ["Outlier policy", `v${summary.policies.outlier.version} · ${summary.policies.outlier.status}`, summary.policies.outlier.policyId],
            ["Missing policy", `v${summary.policies.missing.version} · ${summary.policies.missing.status}`, summary.policies.missing.policyId],
          ]} />
          <div className="mt-3 flex flex-wrap gap-2 text-[10px] font-semibold">
            <Pill label="Legacy global matrix: prohibited" tone="rose" />
            <Pill label="Preprocessing: each training fold only" tone="cyan" />
            <Pill label="No automatic promotion" tone="slate" />
          </div>
        </AuthorityCard>

        <AuthorityCard title="Chronological validation" icon={<Clock3 size={16} />}>
          <div className="space-y-2">
            {summary.split.folds.map((fold) => <div key={fold.foldNumber} className="grid grid-cols-[48px_minmax(0,1fr)] gap-2 rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px]"><div className="grid place-items-center rounded-md bg-slate-900 font-semibold text-white">F{fold.foldNumber}</div><div className="min-w-0"><div className="truncate font-semibold text-slate-900">Train {fold.trainingStart} → {fold.trainingEnd} · {int(fold.trainRows)}</div><div className="truncate text-cyan-800">Validate {fold.validationStart} → {fold.validationEnd} · {int(fold.validationRows)}</div></div></div>)}
          </div>
          <p className="mt-3 flex items-center gap-1.5 text-[11px] text-rose-700"><Lock size={12} />Final OOT {summary.population.finalOotStartDate} → {summary.population.finalOotEndDate} remains inaccessible to fit, score, tuning, calibration, and feature selection.</p>
        </AuthorityCard>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="model-lab-feature-sets">
        <SectionTitle icon={<Layers3 size={16} />} title="Feature sets" description="Select among the exact immutable registered A/B/C contracts. No default or global-matrix fallback exists." />
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          {summary.featureSets.map((item) => {
            const selected = selectedFeatureSetIds.includes(item.featureSetId);
            return <label key={item.featureSetId} className={`cursor-pointer rounded-xl border p-3 ${selected ? "border-cyan-500 bg-cyan-50 ring-1 ring-cyan-100" : "border-slate-200 bg-white"}`}><div className="flex items-start gap-2"><input type="checkbox" checked={selected} onChange={() => setSelectedFeatureSetIds((current) => current.includes(item.featureSetId) ? current.filter((id) => id !== item.featureSetId) : [...current, item.featureSetId])} /><div className="min-w-0"><div className="font-semibold text-slate-950">{item.name}</div><div className="mt-0.5 text-[10px] uppercase text-slate-500">v{item.version} · {item.featureCount} predictors · {item.status}</div></div></div><div className="mt-2 truncate font-mono text-[10px] text-slate-500" title={item.featureSetId}>{item.featureSetId}</div><div className="mt-1 truncate font-mono text-[9px] text-slate-400" title={item.checksum}>{item.checksum}</div></label>;
          })}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="model-lab-model-families">
        <SectionTitle icon={<Gauge size={16} />} title="Model families" description="A bounded first pass: one null reference and fixed, reasonable algorithm specifications. Hyperparameter tuning stays downstream." />
        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {summary.modelFamilies.map((family) => {
            const selected = selectedFamilies.includes(family.id);
            return <label key={family.id} className={`rounded-xl border p-3 ${family.available ? selected ? "border-cyan-500 bg-cyan-50" : "border-slate-200" : "cursor-not-allowed border-slate-200 bg-slate-50 opacity-65"}`}><div className="flex gap-2"><input type="checkbox" disabled={!family.available} checked={selected} onChange={() => setSelectedFamilies((current) => current.includes(family.id) ? current.filter((id) => id !== family.id) : [...current, family.id])} /><div><div className="text-sm font-semibold text-slate-950">{family.label}</div><div className="mt-1 text-[10px] uppercase text-slate-500">{family.available ? human(family.status) : "Unavailable — not installed"}</div></div></div>{!family.available && family.unavailableReason ? <p className="mt-2 text-[10px] leading-4 text-slate-500">{family.unavailableReason}</p> : null}</label>;
          })}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="model-lab-experiment-matrix">
        <SectionTitle icon={<TableProperties size={16} />} title="Experiment matrix" description={`${candidates.length} exact candidate${candidates.length === 1 ? "" : "s"} will run. The null reference is feature-independent; each algorithm candidate binds one immutable feature-set identity.`} />
        <div role="region" aria-label="Selected first-pass candidate matrix" tabIndex={0} className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-xs"><caption className="sr-only">Project-bound first-pass Model Laboratory candidates</caption><thead><tr>{["Candidate", "Model family", "Feature set", "Feature identity", "Plan status"].map((heading) => <th key={heading} scope="col" className="border-b border-slate-200 px-3 py-2 uppercase text-slate-500">{heading}</th>)}</tr></thead><tbody>{candidates.map((item) => <CandidateRow key={item.candidateKey} candidate={item} />)}</tbody></table>
        </div>
        {!candidates.length ? <p role="alert" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">Select at least one available model family and one applicable feature contract.</p> : null}
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-cyan-200 bg-cyan-50/50 p-3">
          <button type="button" onClick={() => void execute()} disabled={!summary.readiness.ready || !candidates.length || running} className="inline-flex items-center gap-2 rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white shadow-sm disabled:cursor-not-allowed disabled:bg-slate-300"><Play size={15} />{running ? "Running first-pass competition…" : "Run first-pass competition"}</button>
          {running ? <span role="status" className="inline-flex items-center gap-2 text-xs text-cyan-900"><Loader2 size={14} className="animate-spin" />Five chronological folds · training-fold-only preprocessing · final OOT locked</span> : <span className="text-xs text-slate-600">Explicit action only · no fit on page load · seed 731026 · no promotion</span>}
        </div>
        {runError ? <p role="alert" className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900"><b>Run failed closed.</b> {runError}</p> : null}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="model-lab-results">
        <SectionTitle icon={<CheckCircle2 size={16} />} title="Development OOF results" description="Ranked by mean five-fold OOF multiclass log loss. Accuracy is not the selection authority; no candidate is called champion or promoted here." />
        {latest ? <Results run={latest} /> : <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center"><FlaskConical className="mx-auto text-slate-400" size={24} /><p className="mt-2 text-sm font-semibold text-slate-800">No project-bound competition has run yet</p><p className="mt-1 text-xs text-slate-500">Review the exact matrix, then use the explicit run action. Loading this page performed zero model fits.</p></div>}
      </section>

      <section className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-[11px] text-slate-600" data-testid="model-lab-authority-footer"><div className="flex flex-wrap items-center gap-2"><Pill label="Current Gold unchanged" tone="emerald" /><Pill label="Final OOT unopened" tone="rose" /><Pill label="No model promotion" tone="slate" /><span className="ml-auto max-w-full truncate font-mono" title={summary.authority.authorityKey}>Authority {short(summary.authority.authorityKey)}</span></div></section>
    </div>
  );
}

function CandidateRow({ candidate }: { candidate: ModelLabCandidatePlan }) {
  return <tr><th scope="row" className="border-b border-slate-100 px-3 py-2 font-mono text-[10px] text-slate-700">{candidate.candidateKey}</th><td className="border-b border-slate-100 px-3 py-2 font-semibold text-slate-900">{human(candidate.modelFamily)}</td><td className="border-b border-slate-100 px-3 py-2">{candidate.featureSetName || "Feature-independent null reference"}</td><td className="max-w-72 truncate border-b border-slate-100 px-3 py-2 font-mono text-[10px] text-slate-500" title={candidate.featureSetId || "NOT_APPLICABLE"}>{candidate.featureSetId || "NOT_APPLICABLE"}</td><td className="border-b border-slate-100 px-3 py-2"><Pill label={human(candidate.status)} tone={candidate.status.includes("BLOCK") ? "rose" : "cyan"} /></td></tr>;
}

function Results({ run }: { run: ModelLabRun }) {
  const ranked = [...run.candidates].sort((left, right) => {
    if (left.meanOofLogLoss == null) return 1;
    if (right.meanOofLogLoss == null) return -1;
    return left.meanOofLogLoss - right.meanOofLogLoss;
  });
  return <><div className="mt-3 flex flex-wrap gap-2 text-[10px]"><Pill label={`Run ${short(run.runId)}`} tone="slate" /><Pill label={human(run.status)} tone={run.status === "COMPLETE" ? "emerald" : "amber"} /><Pill label="Final OOT accessed: NO" tone="rose" /><Pill label="Auto-promoted: NO" tone="slate" /></div><div role="region" aria-label="Development OOF candidate results" tabIndex={0} className="mt-3 overflow-x-auto"><table className="w-full min-w-[1500px] text-left text-xs"><caption className="sr-only">Five-fold development-only Model Laboratory results</caption><thead><tr>{["Rank", "Model family", "Feature set", "Folds", "Mean OOF log loss", "Fold log-loss σ", "Summed Brier", "ECE", "Macro-F1", "Accuracy diagnostic", "Rare-class stability", "Class calibration", "Complexity", "Runtime", "Status / error"].map((heading) => <th key={heading} scope="col" className="border-b border-slate-200 px-3 py-2 uppercase text-slate-500">{heading}</th>)}</tr></thead><tbody>{ranked.map((item, index) => <tr key={item.candidateId} className={item.meanOofLogLoss != null && index === 0 ? "bg-cyan-50/60" : ""}><td className="border-b border-slate-100 px-3 py-2 font-semibold">{item.meanOofLogLoss == null ? "—" : index + 1}</td><td className="border-b border-slate-100 px-3 py-2 font-semibold text-slate-900">{human(item.modelFamily)}</td><td className="border-b border-slate-100 px-3 py-2">{item.featureSetName || "Feature-independent null reference"}</td><td className="border-b border-slate-100 px-3 py-2 tabular-nums">{item.foldsCompleted} / 5</td><td className="border-b border-slate-100 px-3 py-2 font-mono font-semibold">{decimal(item.meanOofLogLoss)}</td><td className="border-b border-slate-100 px-3 py-2 font-mono">{decimal(item.foldStability)}</td><td className="border-b border-slate-100 px-3 py-2 font-mono">{decimal(item.summedBrier)}</td><td className="border-b border-slate-100 px-3 py-2 font-mono">{decimal(item.ece)}</td><td className="border-b border-slate-100 px-3 py-2 font-mono">{decimal(item.macroF1)}</td><td className="border-b border-slate-100 px-3 py-2 font-mono">{decimal(item.accuracyDiagnostic)}</td><td className="border-b border-slate-100 px-3 py-2">{item.rareClassStability ?? "—"}</td><td className="border-b border-slate-100 px-3 py-2">{item.classCalibrationDiagnostics.length ? `${item.classCalibrationDiagnostics.length} class rows` : "—"}</td><td className="border-b border-slate-100 px-3 py-2">{item.modelComplexity ?? "—"}</td><td className="border-b border-slate-100 px-3 py-2 tabular-nums">{duration(item.runtimeMs)}</td><td className="border-b border-slate-100 px-3 py-2"><Pill label={human(item.status)} tone={item.status === "COMPLETE" ? "emerald" : item.status === "FAILED" ? "rose" : "amber"} />{item.errorReason ? <div className="mt-1 max-w-80 text-[10px] leading-4 text-rose-700">{item.errorReason}</div> : null}</td></tr>)}</tbody></table></div><p className="mt-3 text-[11px] text-slate-500">The leading development result is a leaderboard observation only. Champion selection, final-OOT evaluation, calibration, export, and promotion remain separate governed steps.</p></>;
}

function Loading() { return <section className="grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white" role="status" data-testid="model-lab-loading"><div className="text-center"><Loader2 className="mx-auto animate-spin text-cyan-700" size={24} /><p className="mt-2 text-sm font-semibold text-slate-800">Resolving exact project execution authority…</p><p className="mt-1 text-xs text-slate-500">No model request is issued while the page loads.</p></div></section>; }
function Failure({ message, retry }: { message: string; retry: () => Promise<void> }) { return <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5" role="alert" data-testid="model-lab-error"><div className="flex items-center gap-2 font-semibold text-rose-900"><AlertTriangle size={17} />Model Laboratory held closed</div><p className="mt-2 text-sm leading-6 text-rose-800">{message}</p><button type="button" onClick={() => void retry()} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-rose-900 px-3 py-2 text-xs font-semibold text-white"><RefreshCw size={13} />Retry exact authority</button></section>; }
function BlockingReasons({ blockers }: { blockers: string[] }) { return <section className="rounded-2xl border border-rose-200 bg-rose-50 p-4" role="alert"><div className="flex items-center gap-2 text-sm font-semibold text-rose-900"><AlertTriangle size={16} />Execution remains held closed</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-rose-800">{(blockers.length ? blockers : ["The exact project-bound execution contract is incomplete."]).map((item) => <li key={item}>{item}</li>)}</ul></section>; }
function StatusBadge({ ready }: { ready: boolean }) { return <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase ${ready ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200" : "border-rose-400/40 bg-rose-400/10 text-rose-200"}`}>{ready ? <CheckCircle2 size={12} /> : <Lock size={12} />}{ready ? "Ready for first-pass competition" : "Held closed"}</span>; }
function DarkFact({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: "rose" }) { return <div className="min-w-0 bg-slate-950 px-4 py-3 sm:px-5"><div className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">{label}</div><div className={`mt-0.5 truncate font-semibold ${tone === "rose" ? "text-rose-300" : "text-white"}`}>{value}</div><div className="mt-0.5 truncate text-[10px] text-slate-400" title={detail}>{detail}</div></div>; }
function AuthorityCard({ title, icon, children }: { title: string; icon: JSX.Element; children: ReactNode }) { return <section className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><h3 className="flex items-center gap-2 text-sm font-semibold text-slate-950">{icon}{title}</h3><div className="mt-3">{children}</div></section>; }
function AuthorityRows({ rows }: { rows: [string, string, string][] }) { return <dl className="space-y-2">{rows.map(([label, value, identity]) => <div key={label} className="grid min-w-0 gap-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 sm:grid-cols-[120px_minmax(0,1fr)]"><dt className="text-[10px] font-semibold uppercase text-slate-500">{label}</dt><dd className="min-w-0"><div className="truncate text-xs font-semibold text-slate-900">{value}</div><div className="truncate font-mono text-[9px] text-slate-500" title={identity}>{identity}</div></dd></div>)}</dl>; }
function SectionTitle({ icon, title, description }: { icon: JSX.Element; title: string; description: string }) { return <div className="flex items-start gap-2"><span className="mt-0.5 text-cyan-700">{icon}</span><div><h3 className="text-sm font-semibold text-slate-950">{title}</h3><p className="mt-0.5 text-xs leading-5 text-slate-500">{description}</p></div></div>; }
function Pill({ label, tone }: { label: string; tone: "emerald" | "cyan" | "rose" | "amber" | "slate" }) { const style = { emerald: "border-emerald-200 bg-emerald-50 text-emerald-800", cyan: "border-cyan-200 bg-cyan-50 text-cyan-800", rose: "border-rose-200 bg-rose-50 text-rose-800", amber: "border-amber-200 bg-amber-50 text-amber-800", slate: "border-slate-200 bg-slate-50 text-slate-700" }[tone]; return <span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold ${style}`}>{label}</span>; }

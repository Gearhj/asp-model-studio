import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, ArrowRight, CheckCircle2, FlaskConical, GitBranch,
  Layers3, Loader2, Lock, Play, RefreshCw, Scissors,
  Sparkles,
} from "lucide-react";
import {
  executeProjectModelRefinement,
  fetchProjectCandidateEvaluation,
  planProjectModelRefinement,
  requestProjectCandidateAnalysis,
  type CandidateGroup,
  type ProjectCandidateEvaluation,
} from "./projectModelLabApi";

const METHODS = [
  { id: "STABILITY_SELECTION", label: "Fold-local stability selection", description: "Uses training-fold rankings only; a stable set is frozen by a declared frequency/magnitude rule." },
  { id: "COEFFICIENT_GUIDED_ELIMINATION", label: "Coefficient-guided elimination", description: "Compatible linear finalists only; sign and magnitude stability remain diagnostic." },
  { id: "RFE", label: "Recursive feature elimination", description: "Compatible estimators only; selection is learned independently inside every chronological training fold." },
  { id: "RFECV", label: "Fold-local RFECV", description: "Plan-only design: the current backend does not execute this selector." },
  { id: "PERMUTATION_GUIDED_ELIMINATION", label: "Permutation-guided elimination", description: "Plan-only design: the current backend does not execute this selector." },
  { id: "FEATURE_FAMILY_ABLATION", label: "Feature-family ablation", description: "Plan-only design: the current backend does not execute this selector." },
  { id: "REDUNDANCY_PRUNING", label: "Redundancy pruning", description: "Plan-only design: the current backend does not execute this selector." },
] as const;
type RefinementMethodId = typeof METHODS[number]["id"];
const CURRENT_EXECUTOR_METHODS = new Set<RefinementMethodId>([
  "RFE", "STABILITY_SELECTION", "COEFFICIENT_GUIDED_ELIMINATION",
]);
const CLASSICAL_REFINEMENT_FAMILIES = new Set([
  "multinomial_logistic", "elastic_net_logistic", "decision_tree", "random_forest",
  "extra_trees", "xgboost", "lightgbm", "catboost", "linear_svm", "sgd_classifier",
]);
const COEFFICIENT_REFINEMENT_FAMILIES = new Set([
  "multinomial_logistic", "elastic_net_logistic", "linear_svm", "sgd_classifier",
]);

function hasRankingEvidence(attempt: CandidateGroup["attempts"][number]) {
  const evidence = attempt.interpretabilityEvidence;
  if (!evidence) return false;
  if (Array.isArray(evidence.nativeTopFeatureStability) && evidence.nativeTopFeatureStability.length > 0) return true;
  const coefficients = evidence.perClassCoefficientStability;
  return Boolean(coefficients && typeof coefficients === "object"
    && Object.values(coefficients).some((rows) => Array.isArray(rows) && rows.length > 0));
}

function representativeEvidenceAttempt(candidate: CandidateGroup | null) {
  if (!candidate) return null;
  const complete = candidate.attempts.filter((attempt) => attempt.status === "COMPLETE");
  const representative = complete.find((attempt) => attempt.attemptId === candidate.representativeAttemptId);
  if (representative && hasRankingEvidence(representative)) return representative;
  const byEvidenceQuality = complete
    .filter(hasRankingEvidence)
    .sort((left, right) => (left.meanOofLogLoss ?? Number.POSITIVE_INFINITY) - (right.meanOofLogLoss ?? Number.POSITIVE_INFINITY)
      || right.foldsCompleted - left.foldsCompleted);
  return byEvidenceQuality[0] ?? representative ?? complete[0] ?? null;
}

function refinementExecution(modelFamily: string, method: RefinementMethodId) {
  if (!CURRENT_EXECUTOR_METHODS.has(method)) return {
    executable: false,
    status: "PLAN_ONLY_EXECUTOR_UNAVAILABLE" as const,
    reason: "Plan-only method: its fold-local executor is not available in the current backend.",
  };
  if ((method === "RFE" || method === "STABILITY_SELECTION") && !CLASSICAL_REFINEMENT_FAMILIES.has(modelFamily)) return {
    executable: false,
    status: "INCOMPATIBLE_WITH_SELECTED_ESTIMATOR" as const,
    reason: "This method is incompatible with the selected estimator family.",
  };
  if (method === "COEFFICIENT_GUIDED_ELIMINATION" && !COEFFICIENT_REFINEMENT_FAMILIES.has(modelFamily)) return {
    executable: false,
    status: "INCOMPATIBLE_WITH_SELECTED_ESTIMATOR" as const,
    reason: "Coefficient-guided elimination requires a compatible linear estimator.",
  };
  return {
    executable: true,
    status: "EXECUTABLE_RECOMPUTES_FOLD_LOCAL_RANKING" as const,
    reason: "Executable now; ranking evidence is recomputed independently inside each chronological training fold.",
  };
}
const int = (value: number) => new Intl.NumberFormat("en-US").format(value);
const human = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

export function ProjectBoundModelRefinement({ projectId, go }: { projectId: string; go?: (id: string) => void }) {
  const [data, setData] = useState<ProjectCandidateEvaluation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fingerprint, setFingerprint] = useState("");
  const [method, setMethod] = useState<RefinementMethodId>("STABILITY_SELECTION");
  const [minimum, setMinimum] = useState(10);
  const [step, setStep] = useState(5);
  const [rationale, setRationale] = useState("");
  const [planned, setPlanned] = useState<Record<string, any> | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setLoading(true); setError(null);
    try {
      const next = await fetchProjectCandidateEvaluation(projectId, controller.signal);
      if (controller.signal.aborted) return;
      setData(next);
      const finalists = next.candidateGroups.filter((item) => item.finalist && item.status === "COMPLETE");
      setFingerprint((current) => current && finalists.some((item) => item.candidateFingerprint === current) ? current : finalists[0]?.candidateFingerprint ?? "");
    } catch (caught) { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Model Refinement could not be loaded."); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }, [projectId]);
  useEffect(() => { void load(); return () => request.current?.abort(); }, [load]);
  const finalists = data?.candidateGroups.filter((item) => item.finalist && item.status === "COMPLETE") ?? [];
  const candidate = finalists.find((item) => item.candidateFingerprint === fingerprint) ?? null;
  useEffect(() => {
    if (!candidate) return;
    setMinimum(Math.max(10, Math.floor(candidate.featureCount / 2)));
    setStep(Math.max(1, Math.floor(candidate.featureCount / 20)));
    setPlanned(null); setAction(null);
  }, [candidate?.candidateFingerprint]);
  useEffect(() => {
    if (!candidate || refinementExecution(candidate.modelFamily, method).executable) return;
    const replacement = METHODS.find((item) => refinementExecution(candidate.modelFamily, item.id).executable);
    if (replacement) {
      setMethod(replacement.id);
      setPlanned(null);
    }
  }, [candidate?.candidateFingerprint, candidate?.modelFamily, method]);
  const expectedRounds = candidate ? Math.max(1, Math.ceil((candidate.featureCount - minimum) / Math.max(1, step))) : 0;
  const expectedFits = candidate ? (expectedRounds + 1) * 5 : 0;
  const interpretationAttempt = useMemo(() => representativeEvidenceAttempt(candidate), [candidate]);
  const interpretation = interpretationAttempt?.interpretabilityEvidence;
  const methodExecution = refinementExecution(candidate?.modelFamily ?? "", method);
  const rankings = useMemo(() => {
    const rows = (interpretation?.nativeTopFeatureStability ?? []) as Array<Record<string, any>>;
    if (rows.length) return rows.map((item) => ({ feature: String(item.feature), folds: Number(item.topFoldAppearances ?? 0), magnitude: Number(item.meanNativeMagnitude ?? 0) }));
    const coefficients = interpretation?.perClassCoefficientStability as Record<string, Array<Record<string, any>>> | undefined;
    return Object.values(coefficients ?? {}).flat().map((item) => ({ feature: String(item.feature), folds: Number(item.topFoldAppearances ?? 0), magnitude: Math.abs(Number(item.meanCoefficient ?? 0)) })).sort((a, b) => b.folds - a.folds || b.magnitude - a.magnitude);
  }, [interpretation]);
  const createPlan = async () => {
    if (!candidate || !methodExecution.executable) return;
    setAction(null); setError(null);
    try {
      const result = await planProjectModelRefinement(projectId, { candidateFingerprint: candidate.candidateFingerprint, method, minimumRetainedFeatures: minimum, eliminationStep: step, rationale });
      setPlanned(result.plan); setAction(`Immutable plan ${result.plan.planId} created. No model was fit.`); await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "The refinement plan failed closed."); }
  };
  const execute = async () => {
    if (!planned?.planId) return;
    setAction(null); setError(null);
    try { const result = await executeProjectModelRefinement(projectId, planned.planId); setAction(`Reduced challenger queued as project batch ${result.job.jobId}. The parent remains unchanged and the new candidate returns to Evaluation.`); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Reduced-challenger execution failed closed."); }
  };
  const requestAnalysis = async (kind: "SHAP" | "SENSITIVITY") => {
    if (!candidate || !data) return;
    try { const result = await requestProjectCandidateAnalysis(projectId, { candidateFingerprint: candidate.candidateFingerprint, analysisKind: kind, sampleSize: 2000, seed: 20260901, targetClass: data.authority.targetOrder[0] }); setAction(`${human(kind)}: ${human(String(result.analysis.status))}. ${result.analysis.limitations?.join(" ") ?? ""}`); }
    catch (caught) { setError(caught instanceof Error ? caught.message : `${kind} failed closed.`); }
  };

  if (loading) return <Loading />;
  if (error && !data) return <Failure message={error} retry={load} />;
  if (!data) return null;
  return <div className="min-w-0 space-y-4" data-testid="project-bound-model-refinement">
    <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white"><div className="grid gap-px bg-slate-800 lg:grid-cols-[minmax(0,1.7fr)_repeat(3,minmax(150px,0.7fr))]"><div className="bg-slate-950 p-5"><div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-300"><Scissors size={14} /> Step 11 · Model Refinement &amp; Explainability</div><h2 className="mt-2 text-xl font-semibold">Create parsimonious challengers without leaking validation or OOT</h2><p className="mt-1 text-xs leading-5 text-slate-300">Only explicit Evaluation finalists enter. Parent candidates remain immutable; a reduced model receives a new feature-set and candidate identity.</p></div><DarkFact label="Finalists" value={String(finalists.length)} detail="Selected in Evaluation, not champions" /><DarkFact label="Refinement plans" value={String(data.refinements.length)} detail="Immutable, project-bound evidence" /><DarkFact label="Final OOT" value={`${int(data.population.finalOotRows)} locked`} detail="Never used for selection" tone="rose" /></div></section>
    {!finalists.length ? <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5"><div className="flex items-center gap-2 text-sm font-semibold text-amber-950"><Lock size={16} />No finalist has been selected</div><p className="mt-2 text-xs leading-5 text-amber-900">Return to Candidate Evaluation, compare completed candidates, and save an immutable FINALIST FOR REFINEMENT receipt. No top-ranked candidate is selected automatically.</p><button type="button" onClick={() => go?.("evaluation")} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-amber-900 px-3 py-2 text-xs font-semibold text-white">Return to Candidate Evaluation <ArrowRight size={13} /></button></section> : <>
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><FlaskConical size={15} className="text-cyan-700" />Select a finalist</div><div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">{finalists.map((item) => <button key={item.candidateFingerprint} type="button" onClick={() => setFingerprint(item.candidateFingerprint)} className={`rounded-xl border p-3 text-left ${fingerprint === item.candidateFingerprint ? "border-cyan-500 bg-cyan-50" : "border-slate-200 bg-white"}`}><b className="text-xs text-slate-950">{human(item.modelFamily)}</b><p className="mt-1 text-[10px] text-slate-500">{item.featureSetName} · {item.featureCount} predictors · log loss {item.meanOofLogLoss?.toFixed(6)}</p><div className="mt-2 flex flex-wrap gap-1"><span className="inline-flex rounded-full border border-violet-200 bg-violet-50 px-2 py-1 text-[9px] font-semibold text-violet-900">FINALIST FOR REFINEMENT</span><span className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-[9px] font-semibold text-slate-700">EVIDENCE · {human(representativeEvidenceAttempt(item)?.evidenceSource ?? item.evidenceSources[0] ?? "UNKNOWN")}</span></div></button>)}</div></section>
      {candidate ? <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]"><article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Layers3 size={15} className="text-cyan-700" />Feature evidence and stability</div><p className="mt-1 text-[10px] text-slate-500">Parent evidence: {human(interpretationAttempt?.evidenceSource ?? "UNKNOWN")} · attempt {interpretationAttempt?.attemptId ?? "not available"}</p><div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4"><Metric label="Current features" value={String(candidate.featureCount)} /><Metric label="Target retained" value={String(minimum)} /><Metric label="Expected rounds/fold" value={String(expectedRounds)} /><Metric label="Expected selector fits" value={String(expectedFits)} /></div>{rankings.length ? <div className="mt-3 max-h-80 overflow-auto rounded-xl border border-slate-200"><table className="w-full text-left text-[10px]"><thead className="sticky top-0 bg-slate-50"><tr><th className="px-3 py-2">Training-only ranked feature</th><th className="px-3 py-2">Top-fold appearances</th><th className="px-3 py-2">Mean magnitude</th></tr></thead><tbody>{rankings.slice(0, 50).map((item) => <tr key={item.feature}><td className="border-t border-slate-100 px-3 py-2">{item.feature}</td><td className="border-t border-slate-100 px-3 py-2">{item.folds}/5</td><td className="border-t border-slate-100 px-3 py-2 font-mono">{item.magnitude.toFixed(6)}</td></tr>)}</tbody></table></div> : <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><b>NO RANKING PREVIEW IN PARENT RECEIPT.</b> {interpretationAttempt?.evidenceSource === "HISTORICAL_BASELINE" ? "The selected finalist is a HISTORICAL BASELINE receipt, and its immutable parent receipt did not persist a fold-local feature-ranking preview." : `The selected ${human(interpretationAttempt?.evidenceSource ?? "parent")} receipt did not persist a fold-local feature-ranking preview.`} No feature ranking is fabricated. Supported refinement methods recompute ranking evidence from training rows independently inside each chronological training fold; validation and final OOT rows do not select features.</div>}<div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-[10px] leading-5 text-slate-700"><b>Correlated/redundant groups:</b> not computed automatically. Redundancy analysis must be an explicit development-only action with fold-local treatment. Simulator-generated state must remain inside valid baseball constraints during sensitivity analysis.</div></article>
      <aside className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><GitBranch size={15} className="text-cyan-700" />Configure refinement</div>
        <label className="mt-3 block text-[10px] font-semibold uppercase text-slate-500">Method
          <select value={method} onChange={(event) => { setMethod(event.target.value as RefinementMethodId); setPlanned(null); }} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2 text-xs normal-case text-slate-800">
            {METHODS.map((item) => {
              const state = refinementExecution(candidate.modelFamily, item.id);
              const suffix = state.status === "PLAN_ONLY_EXECUTOR_UNAVAILABLE" ? " — plan only" : state.executable ? "" : " — incompatible";
              return <option key={item.id} value={item.id} disabled={!state.executable}>{item.label}{suffix}</option>;
            })}
          </select>
        </label>
        <p className="mt-2 text-[10px] leading-4 text-slate-500">{METHODS.find((item) => item.id === method)?.description}</p>
        <div data-testid="refinement-method-execution-state" className={`mt-2 rounded-lg border p-2 text-[10px] leading-4 ${methodExecution.executable ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
          <b>{human(methodExecution.status)}</b><br />{methodExecution.reason}
        </div>
        <p className="mt-2 text-[9px] leading-4 text-slate-500">RFECV, permutation-guided elimination, feature-family ablation, and redundancy pruning remain visible as plan-only designs until a fold-local executor exists.</p>
        <div className="mt-3 grid grid-cols-2 gap-2"><label className="text-[10px] font-semibold uppercase text-slate-500">Minimum retained<input type="number" min={1} max={candidate.featureCount - 1} value={minimum} onChange={(event) => { setMinimum(Number(event.target.value)); setPlanned(null); }} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2 text-xs normal-case" /></label><label className="text-[10px] font-semibold uppercase text-slate-500">Elimination step<input type="number" min={1} max={candidate.featureCount - 1} value={step} onChange={(event) => { setStep(Number(event.target.value)); setPlanned(null); }} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2 text-xs normal-case" /></label></div>
        <label className="mt-3 block text-[10px] font-semibold uppercase text-slate-500">Scientific rationale<textarea value={rationale} onChange={(event) => setRationale(event.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2 text-xs normal-case" /></label>
        <button type="button" onClick={() => void createPlan()} disabled={!methodExecution.executable} title={methodExecution.executable ? undefined : methodExecution.reason} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"><Scissors size={13} />Create immutable refinement plan</button>
        {planned && methodExecution.executable ? <button type="button" onClick={() => void execute()} className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-cyan-700 px-3 py-2 text-xs font-semibold text-white"><Play size={13} />Run supported reduced challenger · {planned.expectedFits} selector fits</button> : null}
        <div className="mt-3 grid grid-cols-2 gap-2"><button type="button" onClick={() => void requestAnalysis("SHAP")} className="rounded-lg border border-violet-300 bg-violet-50 px-2 py-2 text-[10px] font-semibold text-violet-900"><Sparkles size={12} className="mr-1 inline" />Request SHAP</button><button type="button" onClick={() => void requestAnalysis("SENSITIVITY")} className="rounded-lg border border-violet-300 bg-violet-50 px-2 py-2 text-[10px] font-semibold text-violet-900"><Sparkles size={12} className="mr-1 inline" />Sensitivity</button></div>
      </aside></section> : null}
    </>}
    {action ? <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs leading-5 text-emerald-900"><CheckCircle2 size={14} className="mr-1 inline" />{action}</section> : null}
    {error ? <section role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs leading-5 text-rose-900"><AlertTriangle size={14} className="mr-1 inline" />{error}</section> : null}
    <section className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="flex flex-wrap items-center gap-2"><Pill label="FULL MODEL parent immutable" tone="cyan" /><Pill label="REDUCED CHALLENGER gets new identity" tone="emerald" /><Pill label="PARSIMONY CANDIDATE only" tone="amber" /><Pill label="0 promoted" tone="rose" /><Pill label="Final OOT unopened" tone="rose" /><button type="button" onClick={() => go?.("evaluation")} className="ml-auto inline-flex items-center gap-1 text-xs font-semibold text-cyan-800">Return reduced candidates to Evaluation <ArrowRight size={13} /></button></div></section>
  </div>;
}

function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-lg border border-slate-200 bg-white p-2"><div className="text-[9px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 text-xs font-semibold text-slate-900">{value}</div></div>; }
function DarkFact({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: "rose" }) { return <div className="min-w-0 bg-slate-950 px-4 py-4"><div className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">{label}</div><div className={`mt-1 truncate text-sm font-semibold ${tone === "rose" ? "text-rose-300" : "text-white"}`}>{value}</div><div className="mt-1 truncate text-[9px] text-slate-400">{detail}</div></div>; }
function Pill({ label, tone }: { label: string; tone: "emerald" | "cyan" | "rose" | "amber" }) { const style = { emerald: "border-emerald-200 bg-emerald-50 text-emerald-800", cyan: "border-cyan-200 bg-cyan-50 text-cyan-800", rose: "border-rose-200 bg-rose-50 text-rose-800", amber: "border-amber-200 bg-amber-50 text-amber-900" }[tone]; return <span className={`inline-flex rounded-full border px-2 py-1 text-[9px] font-semibold ${style}`}>{label}</span>; }
function Loading() { return <section className="grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white" role="status"><div className="text-center"><Loader2 className="mx-auto animate-spin text-cyan-700" size={24} /><p className="mt-2 text-sm font-semibold text-slate-800">Resolving finalist and refinement authority…</p><p className="mt-1 text-xs text-slate-500">No selection, SHAP, sensitivity, or model run occurs on page load.</p></div></section>; }
function Failure({ message, retry }: { message: string; retry: () => Promise<void> }) { return <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5" role="alert"><div className="flex items-center gap-2 font-semibold text-rose-900"><AlertTriangle size={17} />Model Refinement held closed</div><p className="mt-2 text-sm text-rose-800">{message}</p><button type="button" onClick={() => void retry()} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-rose-900 px-3 py-2 text-xs font-semibold text-white"><RefreshCw size={13} />Retry exact authority</button></section>; }

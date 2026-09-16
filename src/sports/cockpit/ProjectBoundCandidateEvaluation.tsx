import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactECharts from "echarts-for-react";
import {
  AlertTriangle, BarChart3, ChevronRight,
  Gauge, GitCompareArrows, Loader2, RefreshCw, Save, Search,
  ShieldCheck, Sparkles, Target,
} from "lucide-react";
import {
  fetchProjectCandidateEvaluation,
  requestProjectCandidateAnalysis,
  saveProjectCandidateFinalists,
  type CandidateGroup,
  type FinalistCandidateSelection,
  type FinalistEvaluationBatch,
  type ProjectCandidateEvaluation,
} from "./projectModelLabApi";
import { ProjectCandidateComparison } from "./ProjectCandidateComparison";
import { GovernedTuningDecisionPanel } from "./GovernedTuningDecisionPanel";
import { candidateFeatureSummary, representativeCandidateAttempt } from "./candidateFeatureCounts";

const int = (value: number) => new Intl.NumberFormat("en-US").format(value);
const decimal = (value: number | null | undefined, digits = 6) => value == null ? "—" : value.toFixed(digits);
const human = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

function groupsForSource(data: ProjectCandidateEvaluation, source: FinalistEvaluationBatch) {
  return source === "CURRENT_BATCH" ? data.currentBatches : data.historicalEvidence.candidates;
}

function latestFinalistSource(data: ProjectCandidateEvaluation): FinalistEvaluationBatch | null {
  const receipt = data.finalists.find((item) => item.authorityStatus === "CURRENT") ?? data.finalists[0];
  if (!receipt) return null;
  const declared = String(receipt.evidenceSource ?? receipt.evaluationBatch ?? "").toUpperCase();
  if (declared === "CURRENT_BATCH" || declared === "HISTORICAL_BASELINE") return declared;
  const boundSources = new Set(
    (Array.isArray(receipt.selectedCandidates) ? receipt.selectedCandidates : [])
      .map((item: Record<string, any>) => String(item?.evidenceSource ?? "").toUpperCase())
      .filter((item: string): item is FinalistEvaluationBatch => item === "CURRENT_BATCH" || item === "HISTORICAL_BASELINE"),
  );
  return boundSources.size === 1 ? [...boundSources][0] : null;
}

function finalistBinding(group: CandidateGroup, source: FinalistEvaluationBatch): FinalistCandidateSelection {
  const attempts = group.attempts
    .filter((attempt) => attempt.status === "COMPLETE" && attempt.evidenceSource === source)
    .sort((left, right) =>
      String(right.createdAt).localeCompare(String(left.createdAt))
      || String(left.attemptId).localeCompare(String(right.attemptId))
      || String(left.runReceiptSha256).localeCompare(String(right.runReceiptSha256))
    );
  if (!attempts.length) {
    throw new Error(`${source} evidence is not available for ${group.candidateFingerprint}.`);
  }
  const representative = attempts.find((attempt) =>
    attempt.attemptId === group.representativeAttemptId
    && attempt.runReceiptSha256 === group.immutableEvidenceIdentity
  ) ?? attempts[0];
  const requiredIdentities = [
    representative.attemptId,
    representative.runId,
    representative.runReceiptSha256,
    ...attempts.flatMap((attempt) => [attempt.attemptId, attempt.runId, attempt.runReceiptSha256]),
  ];
  if (requiredIdentities.some((identity) => !String(identity || "").trim())) {
    throw new Error(`${source} evidence identity is incomplete for ${group.candidateFingerprint}.`);
  }
  return {
    candidateFingerprint: group.candidateFingerprint,
    evidenceSource: source,
    representativeAttemptId: representative.attemptId,
    immutableEvidenceIdentity: representative.runReceiptSha256,
    attemptEvidence: attempts.map((attempt) => ({
      attemptId: attempt.attemptId,
      runId: attempt.runId,
      runReceiptSha256: attempt.runReceiptSha256,
    })),
  };
}

export function ProjectBoundCandidateEvaluation({ projectId, go }: { projectId: string; go?: (id: string) => void }) {
  const [data, setData] = useState<ProjectCandidateEvaluation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<FinalistEvaluationBatch>("CURRENT_BATCH");
  const [family, setFamily] = useState("ALL");
  const [feature, setFeature] = useState("ALL");
  const [status, setStatus] = useState("COMPLETE");
  const [finalistFilter, setFinalistFilter] = useState("ALL");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [finalists, setFinalists] = useState<Set<string>>(new Set());
  const [rationale, setRationale] = useState("");
  const [className, setClassName] = useState("STRIKEOUT");
  const [analysisMessage, setAnalysisMessage] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const request = useRef<AbortController | null>(null);
  const sourceRef = useRef<FinalistEvaluationBatch>("CURRENT_BATCH");

  const hydrateSourceSelection = useCallback((next: ProjectCandidateEvaluation, activeSource: FinalistEvaluationBatch) => {
    const groups = groupsForSource(next, activeSource);
    const complete = groups.filter((item) => item.status === "COMPLETE");
    sourceRef.current = activeSource;
    setSource(activeSource);
    setSelected(new Set(complete.slice(0, 2).map((item) => item.candidateFingerprint)));
    setFinalists(new Set(complete.filter((item) => item.finalist).map((item) => item.candidateFingerprint)));
  }, []);

  const load = useCallback(async () => {
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setLoading(true); setError(null);
    try {
      const next = await fetchProjectCandidateEvaluation(projectId, controller.signal);
      if (controller.signal.aborted) return;
      setData(next);
      const requestedSource = sourceRef.current;
      const activeSource = requestedSource === "CURRENT_BATCH" && !next.currentBatches.length
        ? "HISTORICAL_BASELINE"
        : requestedSource === "HISTORICAL_BASELINE" && !next.historicalEvidence.candidates.length && next.currentBatches.length
          ? "CURRENT_BATCH"
          : requestedSource;
      hydrateSourceSelection(next, activeSource);
    } catch (caught) { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Candidate Evaluation could not be loaded."); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }, [hydrateSourceSelection, projectId]);
  useEffect(() => { void load(); return () => request.current?.abort(); }, [load]);

  const sourceGroups = useMemo(() => data ? groupsForSource(data, source) : [], [data, source]);
  const filtered = useMemo(() => sourceGroups.filter((candidate) =>
    (family === "ALL" || candidate.modelFamily === family)
    && (feature === "ALL" || candidate.featureSetId === feature)
    && (status === "ALL" || candidate.status === status)
    && (finalistFilter === "ALL" || (finalistFilter === "FINALIST" ? candidate.finalist : !candidate.finalist))
  ), [family, feature, finalistFilter, sourceGroups, status]);
  const details = sourceGroups.filter((candidate) => selected.has(candidate.candidateFingerprint)).slice(0, 3);
  const families = [...new Set(sourceGroups.map((item) => item.modelFamily))];
  const features = [...new Map(sourceGroups.map((item) => [String(item.featureSetId), { id: String(item.featureSetId), label: item.featureSetName }])).values()];
  const persistedFinalistSource = data ? latestFinalistSource(data) : null;
  const persistedSourceFinalists = persistedFinalistSource === source
    && sourceGroups.some((item) => item.status === "COMPLETE" && item.finalist);
  const otherSourceHasLatestSelection = persistedFinalistSource != null && persistedFinalistSource !== source;

  const changeSource = (nextSource: FinalistEvaluationBatch) => {
    if (nextSource === source) return;
    sourceRef.current = nextSource;
    setFamily("ALL");
    setFeature("ALL");
    setStatus("COMPLETE");
    setFinalistFilter("ALL");
    setRationale("");
    if (data) hydrateSourceSelection(data, nextSource);
    else setSource(nextSource);
  };

  const toggleDetail = (fingerprint: string) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(fingerprint)) next.delete(fingerprint);
    else if (next.size < 3) next.add(fingerprint);
    return next;
  });
  const toggleFinalist = (fingerprint: string) => setFinalists((current) => { const next = new Set(current); if (next.has(fingerprint)) next.delete(fingerprint); else next.add(fingerprint); return next; });
  const saveFinalists = async () => {
    if (!finalists.size || rationale.trim().length < 20) return;
    setSaving(true); setError(null);
    try {
      const selectedGroups = sourceGroups.filter((group) => group.status === "COMPLETE" && finalists.has(group.candidateFingerprint));
      if (selectedGroups.length !== finalists.size) throw new Error(`${source} finalist selection contains stale or unavailable evidence.`);
      const candidateSelections = selectedGroups.map((group) => finalistBinding(group, source));
      await saveProjectCandidateFinalists(projectId, {
        candidateFingerprints: candidateSelections.map((item) => item.candidateFingerprint),
        candidateSelections,
        rationale,
        evaluationBatch: source,
      });
      await load();
    }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Finalist selection failed closed."); }
    finally { setSaving(false); }
  };
  const analyze = async (group: CandidateGroup, kind: "PERMUTATION_IMPORTANCE" | "SHAP" | "SENSITIVITY") => {
    try {
      const result = await requestProjectCandidateAnalysis(projectId, { candidateFingerprint: group.candidateFingerprint, analysisKind: kind, sampleSize: 2000, seed: 20260901, targetClass: className });
      setAnalysisMessage((current) => ({ ...current, [`${group.candidateFingerprint}:${kind}`]: `${human(String(result.analysis.status))}${result.analysis.limitations?.length ? ` — ${result.analysis.limitations.join(" ")}` : ""}` }));
    } catch (caught) { setAnalysisMessage((current) => ({ ...current, [`${group.candidateFingerprint}:${kind}`]: caught instanceof Error ? caught.message : "Analysis failed closed." })); }
  };

  if (loading) return <Loading />;
  if (error && !data) return <Failure message={error} retry={load} />;
  if (!data) return null;

  return <div className="min-w-0 space-y-4" data-testid="project-bound-candidate-evaluation">
    <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white"><div className="grid gap-px bg-slate-800 lg:grid-cols-[minmax(0,1.6fr)_repeat(4,minmax(120px,0.6fr))]"><div className="bg-slate-950 p-5"><div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-300"><BarChart3 size={14} /> Step 10 · Candidate Evaluation</div><h2 className="mt-2 text-xl font-semibold">Compare verified development evidence in depth</h2><p className="mt-1 text-xs leading-5 text-slate-300">Project-bound receipts only. Opening Evaluation performs no fit, tuning, calibration, SHAP, refinement, or promotion.</p></div><DarkFact label="Unique candidates" value={String(data.activity.uniqueCandidateSpecifications)} detail={`${data.activity.attempts} immutable attempts`} /><DarkFact label="Development" value={`${int(data.population.developmentRows)} rows`} detail={`${data.population.foldCount} chronological folds`} /><DarkFact label="Activity" value={`${data.activity.modelFitsDisplayedAsProjectEvidence} preserved fold fits`} detail={`${data.activity.newFitsOnPageLoad} new fits on page load`} /><DarkFact label="Final OOT" value={`${int(data.population.finalOotRows)} locked`} detail="No Evaluation access" tone="rose" /></div></section>
    <section className="rounded-2xl border border-cyan-200 bg-cyan-50 p-4"><div className="flex items-center gap-2 text-sm font-semibold text-cyan-950"><ShieldCheck size={16} />Project-bound evidence authority</div><p className="mt-1 text-xs leading-5 text-cyan-900">{data.historicalEvidence.banner} The apparent duplicate rows were matching attempts from distinct immutable receipts; the default view now groups them by full scientific fingerprint.</p><div className="mt-2 flex flex-wrap gap-2"><Pill label={`${data.activity.historicalRunReceipts} historical receipts`} tone="cyan" /><Pill label={`${data.activity.currentBatchReceipts} current batch receipts`} tone="slate" /><Pill label="Legacy global matrix impossible" tone="emerald" /><Pill label="Base-22 fallback impossible" tone="emerald" /><Pill label="0 promoted" tone="rose" /></div></section>
    {data.tuningDecision ? <GovernedTuningDecisionPanel decision={data.tuningDecision} /> : null}

    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Search size={15} className="text-cyan-700" />Evaluation batch selector</div><span className={`rounded-full border px-2.5 py-1 text-[10px] font-bold tracking-wide ${source === "CURRENT_BATCH" ? "border-emerald-300 bg-emerald-50 text-emerald-900" : "border-amber-300 bg-amber-50 text-amber-900"}`} data-testid="active-evaluation-source">{source} EVIDENCE ONLY</span></div><p className="mt-1 text-[10px] leading-4 text-slate-500">The active evidence source controls the comparison and default detail panels. Sources are never silently mixed. {data.tuningDecision ? "The frozen tuning decision creates no finalist authority." : "The pre-tuning workflow can also bind an immutable finalist selection receipt."}</p><div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-6"><Filter label="Evidence" value={source} onChange={(value) => changeSource(value as FinalistEvaluationBatch)} options={["CURRENT_BATCH", "HISTORICAL_BASELINE"]} /><Filter label="Algorithm family" value={family} onChange={setFamily} options={["ALL", ...families]} /><label className="text-[10px] font-semibold uppercase text-slate-500">Feature universe<select value={feature} onChange={(event) => setFeature(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-xs normal-case text-slate-800"><option value="ALL">All</option>{features.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label><Filter label="Status" value={status} onChange={setStatus} options={["ALL", "COMPLETE", "FAILED"]} />{data.tuningDecision ? null : <Filter label="Finalist designation" value={finalistFilter} onChange={setFinalistFilter} options={["ALL", "FINALIST", "NOT_FINALIST"]} />}<label className="text-[10px] font-semibold uppercase text-slate-500">One-vs-rest class<select value={className} onChange={(event) => setClassName(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-xs normal-case text-slate-800">{data.authority.targetOrder.map((item) => <option key={item}>{item}</option>)}</select></label></div></section>

    <ProjectCandidateComparison groups={filtered} title={`${human(source)} Evaluation overview`} source={source} />
    <EvaluationOverviewDiagnostics groups={filtered} />

    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="flex items-center gap-2 text-sm font-semibold text-slate-950"><GitCompareArrows size={15} className="text-cyan-700" />Side-by-side inspection</h3><p className="mt-1 text-xs text-slate-500">Select up to three completed {human(source)} candidate specifications. Historical receipts without row/model artifacts fail closed only for the affected diagnostic.</p></div><span className="text-xs font-semibold text-slate-500">{selected.size}/3 selected</span></div><div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">{filtered.filter((item) => item.status === "COMPLETE").map((item) => <label key={item.candidateFingerprint} className={`flex items-start gap-2 rounded-lg border p-3 ${selected.has(item.candidateFingerprint) ? "border-cyan-400 bg-cyan-50" : "border-slate-200"}`}><input type="checkbox" checked={selected.has(item.candidateFingerprint)} onChange={() => toggleDetail(item.candidateFingerprint)} disabled={!selected.has(item.candidateFingerprint) && selected.size >= 3} className="mt-0.5" /><span><b className="block text-xs text-slate-900">{human(item.modelFamily)}</b><span className="block text-[10px] font-semibold text-cyan-800">{source}</span><span className="block text-[10px] text-slate-500">{item.featureSetName} · log loss {decimal(item.meanOofLogLoss)}</span></span></label>)}</div></section>

    {details.length ? <section className="grid gap-4 xl:grid-cols-2" data-testid="candidate-detail-panels">{details.map((group) => <CandidateDetail key={group.candidateFingerprint} group={group} className={className} analysisMessage={analysisMessage} onAnalyze={analyze} finalist={finalists.has(group.candidateFingerprint)} persistedFinalist={group.finalist} onFinalist={() => toggleFinalist(group.candidateFingerprint)} tuningComplete={Boolean(data.tuningDecision)} />)}</section> : null}

    {data.tuningDecision ? <section className="rounded-2xl border border-slate-800 bg-slate-950 p-4 text-white" data-testid="tuning-stop-boundary"><div className="flex items-center gap-2 text-sm font-semibold"><Target size={16} className="text-cyan-300" />Tuning decision stop boundary</div><p className="mt-2 text-xs leading-5 text-slate-300">The first-screen advance-to-tuning receipt remains immutable history. This assignment creates no new finalist label and grants no refinement, calibration, feature-selection, simulation, champion, promotion, export, or deployment authority.</p><div className="mt-3 flex flex-wrap gap-2"><Pill label="Not champion" tone="amber" /><Pill label="Not promoted" tone="rose" /><Pill label="Final OOT locked" tone="rose" /></div></section> : <section className="rounded-2xl border border-slate-800 bg-slate-950 p-4 text-white" data-testid="finalist-selection"><div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2 text-sm font-semibold"><Target size={16} className="text-cyan-300" />Finalist selection for refinement</div><span className={`rounded-full border px-2.5 py-1 text-[10px] font-bold ${source === "CURRENT_BATCH" ? "border-emerald-400 bg-emerald-400/10 text-emerald-200" : "border-amber-400 bg-amber-400/10 text-amber-200"}`}>{source} ONLY</span></div><p className="mt-1 text-xs leading-5 text-slate-300">Choose one or more completed candidates from the active evidence source. Saving binds every selected attempt and immutable run receipt from {source}; evidence from another source is never selected silently.</p>{otherSourceHasLatestSelection ? <p className="mt-2 rounded-lg border border-amber-400/50 bg-amber-400/10 px-3 py-2 text-[10px] leading-4 text-amber-100" data-testid="other-source-finalist-history">No {human(source)} finalists are currently saved. The latest {human(persistedFinalistSource)} finalist receipt remains immutable history; switch evidence sources to inspect it.</p> : null}<div className="mt-3 flex flex-wrap gap-2">{sourceGroups.filter((item) => item.status === "COMPLETE").map((item) => <label key={item.candidateFingerprint} className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${finalists.has(item.candidateFingerprint) ? "border-cyan-400 bg-cyan-400/10" : "border-slate-700"}`}><input type="checkbox" checked={finalists.has(item.candidateFingerprint)} onChange={() => toggleFinalist(item.candidateFingerprint)} /><span><b>{human(item.modelFamily)} · {item.featureSetName}</b><span className="ml-2 font-mono text-[9px] text-cyan-200">{source}</span></span></label>)}</div><label className="mt-3 block text-[10px] font-semibold uppercase text-slate-400">Written scientific rationale<textarea value={rationale} onChange={(event) => setRationale(event.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs normal-case text-white" placeholder="Explain the primary metric, secondary evidence, stability, complexity, and warnings considered." /></label><div className="mt-3 flex flex-wrap gap-3"><button type="button" title="Save immutable finalist receipt" onClick={() => void saveFinalists()} disabled={!finalists.size || rationale.trim().length < 20 || saving} className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-600">{saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Save {human(source)} finalist receipt</button><button type="button" onClick={() => go?.("refinement")} disabled={!persistedSourceFinalists} title={!persistedSourceFinalists ? `Save a ${source} finalist receipt before continuing.` : undefined} className="inline-flex items-center gap-2 rounded-lg border border-slate-600 px-4 py-2 text-sm font-semibold disabled:text-slate-500">Continue to Model Refinement <ChevronRight size={14} /></button></div><div className="mt-3 flex flex-wrap gap-2"><Pill label="Not champion" tone="amber" /><Pill label="Not promoted" tone="rose" /><Pill label="Final OOT locked" tone="rose" /></div></section>}
    {error ? <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900">{error}</p> : null}
  </div>;
}

function CandidateDetail({ group, className, analysisMessage, onAnalyze, finalist, persistedFinalist, onFinalist, tuningComplete }: { group: CandidateGroup; className: string; analysisMessage: Record<string, string>; onAnalyze: (group: CandidateGroup, kind: "PERMUTATION_IMPORTANCE" | "SHAP" | "SENSITIVITY") => Promise<void>; finalist: boolean; persistedFinalist: boolean; onFinalist: () => void; tuningComplete: boolean }) {
  const attempt = representativeCandidateAttempt(group)!;
  const evaluation = attempt.evaluationEvidence;
  const interpretation = attempt.interpretabilityEvidence;
  const folds = attempt.folds ?? [];
  const foldLosses = folds.map((fold) => Number(fold.metrics?.multiclassLogLoss)).filter(Number.isFinite);
  const calibration = attempt.classCalibration ?? [];
  const selectedCalibration = calibration.find((item: any) => item.class === className);
  const lift = evaluation?.oneVsRestLiftByClass?.[className] as Array<Record<string, any>> | undefined;
  const confusion = evaluation?.confusionMatrix as number[][] | undefined;
  const normalizedConfusion = evaluation?.normalizedConfusionMatrix as number[][] | undefined;
  const importance = (interpretation?.nativeTopFeatureStability ?? interpretation?.topFeatures ?? []) as Array<Record<string, any>>;
  const coefficients = (interpretation?.perClassCoefficientStability?.[className] ?? []) as Array<Record<string, any>>;
  return <article className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="text-sm font-semibold text-slate-950">{human(group.modelFamily)}</h3><p className="text-[10px] text-slate-500" data-testid="candidate-feature-counts" title="Model inputs are counted before categorical one-hot expansion.">{group.featureSetName} · {candidateFeatureSummary(group)}</p><span className="mt-1 inline-flex rounded-full border border-cyan-200 bg-cyan-50 px-2 py-0.5 font-mono text-[9px] font-semibold text-cyan-900">{attempt.evidenceSource}</span></div>{tuningComplete ? <span className="rounded-full border border-slate-300 bg-slate-50 px-2 py-1 text-[10px] font-semibold text-slate-700">Tuning evidence only</span> : <label className="flex items-center gap-2 rounded-full border border-cyan-200 bg-cyan-50 px-2 py-1 text-[10px] font-semibold text-cyan-900"><input type="checkbox" checked={finalist} onChange={onFinalist} /> Finalist for refinement</label>}</div><div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4"><Metric label="OOF log loss" value={decimal(group.meanOofLogLoss)} /><Metric label="Summed Brier" value={decimal(group.summedBrier)} /><Metric label="ECE" value={decimal(group.ece)} /><Metric label="Fold SD" value={decimal(group.foldStandardDeviation)} /></div>
    <Diagnostic title="Five-fold log-loss distribution" icon={<Gauge size={14} />}>{foldLosses.length ? <ReactECharts option={{ animation: false, grid: { left: 38, right: 10, top: 10, bottom: 28 }, xAxis: { type: "category", data: foldLosses.map((_value, index) => `F${index + 1}`), axisLabel: { fontSize: 9 } }, yAxis: { type: "value", scale: true, axisLabel: { fontSize: 9 } }, tooltip: { trigger: "axis" }, series: [{ type: "bar", data: foldLosses, itemStyle: { color: "#0891b2" } }] }} style={{ height: 160 }} opts={{ renderer: "svg" }} /> : <Unavailable text="Fold metric evidence was not captured." />}</Diagnostic>
    <Diagnostic title={`${className} reliability / calibration`} icon={<Target size={14} />}>{selectedCalibration ? <div className="grid grid-cols-2 gap-2 text-[10px]"><Metric label="Support" value={int(Number(selectedCalibration.support ?? 0))} /><Metric label="Observed rate" value={decimal(Number(selectedCalibration.observedRate), 4)} /><Metric label="Mean predicted" value={decimal(Number(selectedCalibration.meanPredictedProbability), 4)} /><Metric label="One-v-rest Brier" value={decimal(Number(selectedCalibration.oneVsRestBrier), 5)} /></div> : <Unavailable text="Class calibration evidence was not captured in this receipt." />}</Diagnostic>
    <Diagnostic title="Eight-class confusion evidence" icon={<GitCompareArrows size={14} />}>{confusion?.length && normalizedConfusion?.length ? <div className="grid gap-3 2xl:grid-cols-2"><ConfusionMatrix title="Counts" matrix={confusion} classes={evaluation?.orderedClasses ?? []} normalized={false} /><ConfusionMatrix title="Row-normalized" matrix={normalizedConfusion} classes={evaluation?.orderedClasses ?? []} normalized /></div> : <Unavailable text="EVIDENCE NOT CAPTURED IN HISTORICAL RECEIPT — confusion values are not fabricated as zero." />}</Diagnostic>
    <Diagnostic title={`${className} one-vs-rest lift / cumulative gains`} icon={<BarChart3 size={14} />}>{lift?.length ? <ReactECharts option={{ animation: false, grid: { left: 38, right: 10, top: 10, bottom: 28 }, xAxis: { type: "category", data: lift.map((item) => `D${item.decile}`), axisLabel: { fontSize: 9 } }, yAxis: [{ type: "value", name: "Lift", axisLabel: { fontSize: 9 } }, { type: "value", name: "Gain", min: 0, max: 1, axisLabel: { fontSize: 9 } }], tooltip: { trigger: "axis" }, series: [{ type: "bar", data: lift.map((item) => item.lift), itemStyle: { color: "#0f766e" } }, { type: "line", yAxisIndex: 1, data: lift.map((item) => item.cumulativeGain), itemStyle: { color: "#f97316" } }] }} style={{ height: 180 }} opts={{ renderer: "svg" }} /> : <Unavailable text="EVIDENCE NOT CAPTURED IN HISTORICAL RECEIPT — no binary lift curve is fabricated for this eight-class model." />}</Diagnostic>
    <Diagnostic title="Model-appropriate feature evidence" icon={<Sparkles size={14} />}>{coefficients.length ? <Importance rows={coefficients.map((item) => ({ feature: item.feature, value: item.meanCoefficient }))} valueLabel={`${className} coefficient`} /> : importance.length ? <Importance rows={importance.map((item) => ({ feature: item.feature, value: item.meanNativeMagnitude ?? item.nativeImportance ?? item.meanAbsoluteCoefficient }))} valueLabel="Native diagnostic magnitude" /> : <Unavailable text={group.modelFamily === "class_frequency_null" ? "NOT APPLICABLE — feature-independent reference." : "EVIDENCE NOT CAPTURED IN HISTORICAL RECEIPT. Unsupported importance is not shown as zero."} />}</Diagnostic>
    {tuningComplete ? <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-[10px] leading-4 text-slate-700"><b>Post-tuning analyses are held closed.</b> SHAP, sensitivity, permutation importance, feature refinement, and calibration require later governed stages.</div> : <div className="mt-3 rounded-xl border border-violet-200 bg-violet-50 p-3"><div className="text-xs font-semibold text-violet-950">Explicit development-only analysis</div><p className="mt-1 text-[10px] leading-4 text-violet-800">No action runs on page load. Sample: 2,000 deterministic development rows · seed 20260901 · final OOT excluded. SHAP and sensitivity require a saved finalist receipt.</p><div className="mt-2 flex flex-wrap gap-2">{(["PERMUTATION_IMPORTANCE", "SHAP", "SENSITIVITY"] as const).map((kind) => { const finalistRequired = kind !== "PERMUTATION_IMPORTANCE"; return <button key={kind} type="button" disabled={finalistRequired && !persistedFinalist} title={finalistRequired && !persistedFinalist ? "Save this candidate as a finalist before requesting this analysis." : undefined} onClick={() => void onAnalyze(group, kind)} className="rounded-lg border border-violet-300 bg-white px-2 py-1.5 text-[10px] font-semibold text-violet-900 disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400">Request {human(kind)}</button>; })}</div>{(["PERMUTATION_IMPORTANCE", "SHAP", "SENSITIVITY"] as const).map((kind) => analysisMessage[`${group.candidateFingerprint}:${kind}`] ? <p key={kind} className="mt-2 text-[10px] leading-4 text-violet-900"><b>{human(kind)}:</b> {analysisMessage[`${group.candidateFingerprint}:${kind}`]}</p> : null)}</div>}
    <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3"><summary className="cursor-pointer text-[10px] font-semibold text-slate-700">Exact hyperparameters, complexity, and evidence identity</summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all text-[9px] text-slate-600">{JSON.stringify({ hyperparameters: group.hyperparameters, complexity: attempt.modelComplexity, receipt: attempt.runReceiptSha256, fingerprint: group.candidateFingerprint }, null, 2)}</pre></details><div className="mt-3 flex flex-wrap gap-2"><Pill label="Development/model-selection evidence" tone="cyan" /><Pill label="No generalization claim" tone="amber" /><Pill label="Not promoted" tone="rose" /></div></article>;
}

function EvaluationOverviewDiagnostics({ groups }: { groups: CandidateGroup[] }) {
  const completed = groups.filter((group) => group.status === "COMPLETE" && group.meanOofLogLoss != null);
  const foldRows = completed.filter((group) => group.foldStandardDeviation != null);
  const runtimeRows = completed.filter((group) => group.runtimeMs != null);
  const label = (group: CandidateGroup) => `${human(group.modelFamily)} · ${group.featureSetName}`;
  return <section className="grid min-w-0 gap-4 xl:grid-cols-2" data-testid="evaluation-overview-diagnostics">
    <Diagnostic title="Cross-model fold variability" icon={<Gauge size={14} />}>{foldRows.length ? <ReactECharts option={{ animation: false, grid: { left: 210, right: 18, top: 12, bottom: 30 }, tooltip: { trigger: "axis" }, xAxis: { type: "value", name: "Five-fold log-loss SD · lower is more stable", nameLocation: "middle", nameGap: 25, axisLabel: { fontSize: 9 } }, yAxis: { type: "category", inverse: true, data: foldRows.map(label), axisLabel: { width: 190, overflow: "truncate", fontSize: 9 } }, series: [{ type: "bar", data: foldRows.map((group) => group.foldStandardDeviation), itemStyle: { color: "#7c3aed" }, barMaxWidth: 20 }] }} style={{ height: Math.max(230, foldRows.length * 34) }} opts={{ renderer: "svg" }} /> : <Unavailable text="Fold-variability evidence was not captured for the selected receipts." />}</Diagnostic>
    <Diagnostic title="Runtime versus OOF log loss" icon={<BarChart3 size={14} />}>{runtimeRows.length ? <ReactECharts option={{ animation: false, grid: { left: 52, right: 24, top: 18, bottom: 42 }, tooltip: { trigger: "item", formatter: (item: any) => `${item.data.name}<br/>Runtime: ${(item.data.value[0] / 1000).toFixed(1)}s<br/>Log loss: ${Number(item.data.value[1]).toFixed(6)}` }, xAxis: { type: "value", name: "Runtime (ms)", nameLocation: "middle", nameGap: 28, axisLabel: { fontSize: 9 } }, yAxis: { type: "value", name: "OOF log loss", scale: true, axisLabel: { fontSize: 9 } }, series: [{ type: "scatter", symbolSize: 11, data: runtimeRows.map((group) => ({ name: label(group), value: [group.runtimeMs, group.meanOofLogLoss] })), itemStyle: { color: "#0891b2" } }] }} style={{ height: 280 }} opts={{ renderer: "svg" }} /> : <Unavailable text="Runtime-versus-loss evidence was not captured for the selected receipts." />}</Diagnostic>
  </section>;
}

function ConfusionMatrix({ title, matrix, classes, normalized }: { title: string; matrix: number[][]; classes: string[]; normalized: boolean }) {
  return <div className="min-w-0"><div className="mb-1 text-[9px] font-semibold uppercase tracking-wide text-slate-500">{title} · rows actual / columns predicted</div><div className="overflow-x-auto rounded-lg border border-slate-200 bg-white"><table className="min-w-[520px] text-center text-[9px]"><thead><tr><th className="border-b border-r border-slate-200 bg-slate-50 px-1 py-1 text-left">Actual</th>{classes.map((item) => <th key={item} title={item} className="border-b border-slate-200 bg-slate-50 px-1 py-1 font-semibold text-slate-500">{item.slice(0, 4)}</th>)}</tr></thead><tbody>{matrix.map((row, rowIndex) => <tr key={`${title}:${classes[rowIndex] ?? rowIndex}`}><th title={classes[rowIndex]} className="border-r border-slate-200 bg-slate-50 px-1 py-1 text-left font-semibold text-slate-600">{(classes[rowIndex] ?? String(rowIndex)).slice(0, 7)}</th>{row.map((value, columnIndex) => <td key={columnIndex} className={`px-1 py-1 tabular-nums ${rowIndex === columnIndex ? "bg-emerald-50 font-semibold text-emerald-900" : "text-slate-600"}`}>{normalized ? `${(Number(value) * 100).toFixed(1)}%` : int(Number(value))}</td>)}</tr>)}</tbody></table></div></div>;
}

function Importance({ rows, valueLabel }: { rows: Array<{ feature: string; value: number }>; valueLabel: string }) { return <div className="space-y-1.5">{rows.slice(0, 10).map((row) => <div key={row.feature} className="grid grid-cols-[minmax(0,1fr)_80px] gap-2 text-[10px]"><span className="truncate text-slate-700" title={row.feature}>{row.feature}</span><span className="text-right font-mono text-slate-900" title={valueLabel}>{Number(row.value).toFixed(5)}</span></div>)}</div>; }
function Diagnostic({ title, icon, children }: { title: string; icon: JSX.Element; children: React.ReactNode }) { return <section className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3"><h4 className="flex items-center gap-2 text-xs font-semibold text-slate-900">{icon}{title}</h4><div className="mt-2">{children}</div></section>; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-lg border border-slate-200 bg-white p-2"><div className="text-[9px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 text-xs font-semibold text-slate-900">{value}</div></div>; }
function Unavailable({ text }: { text: string }) { return <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-[10px] leading-4 text-amber-900">{text}</div>; }
function Filter({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: string[] }) { return <label className="text-[10px] font-semibold uppercase text-slate-500">{label}<select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-xs normal-case text-slate-800">{options.map((item) => <option key={item} value={item}>{human(item)}</option>)}</select></label>; }
function Pill({ label, tone }: { label: string; tone: "emerald" | "cyan" | "rose" | "amber" | "slate" }) { const style = { emerald: "border-emerald-200 bg-emerald-50 text-emerald-800", cyan: "border-cyan-200 bg-cyan-50 text-cyan-800", rose: "border-rose-200 bg-rose-50 text-rose-800", amber: "border-amber-200 bg-amber-50 text-amber-900", slate: "border-slate-200 bg-slate-50 text-slate-700" }[tone]; return <span className={`inline-flex rounded-full border px-2 py-1 text-[9px] font-semibold ${style}`}>{label}</span>; }
function DarkFact({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: "rose" }) { return <div className="min-w-0 bg-slate-950 px-4 py-4"><div className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">{label}</div><div className={`mt-1 truncate text-sm font-semibold ${tone === "rose" ? "text-rose-300" : "text-white"}`}>{value}</div><div className="mt-1 truncate text-[9px] text-slate-400" title={detail}>{detail}</div></div>; }
function Loading() { return <section className="grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white" role="status"><div className="text-center"><Loader2 className="mx-auto animate-spin text-cyan-700" size={24} /><p className="mt-2 text-sm font-semibold text-slate-800">Verifying immutable project candidate receipts…</p><p className="mt-1 text-xs text-slate-500">No model or analysis action runs on page load.</p></div></section>; }
function Failure({ message, retry }: { message: string; retry: () => Promise<void> }) { return <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5" role="alert"><div className="flex items-center gap-2 font-semibold text-rose-900"><AlertTriangle size={17} />Candidate Evaluation held closed</div><p className="mt-2 text-sm text-rose-800">{message}</p><button type="button" onClick={() => void retry()} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-rose-900 px-3 py-2 text-xs font-semibold text-white"><RefreshCw size={13} />Retry verified receipts</button></section>; }

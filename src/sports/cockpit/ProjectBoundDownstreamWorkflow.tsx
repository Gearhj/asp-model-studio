import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  CheckCircle2,
  ClipboardList,
  Database,
  FileCheck2,
  Gauge,
  Loader2,
  Lock,
  Orbit,
  RefreshCw,
  Scale,
  ShieldCheck,
  Trophy,
} from "lucide-react";
import {
  cancelUnstartedProjectStage3ExecutableArtifact,
  enqueueProjectStage3ExecutableArtifact,
  enqueueProjectStage3GameScoring,
  fetchProjectStage3ExecutableArtifact,
  fetchProjectStage3ExecutableArtifactJob,
  fetchProjectStage3GameScoring,
  fetchProjectStage3GameScoringJob,
  fetchProjectStage3Downstream,
  planProjectStage3ExecutableArtifact,
  registerProjectResearchHandoff,
  saveProjectCalibrationDecision,
  saveProjectGameEvaluationDecision,
  saveProjectResearchSelection,
  type ProjectDownstreamDecision,
  type ProjectDownstreamFinalist,
  type ProjectStage3Downstream,
  type ProjectStage3ExecutableArtifact,
  type ProjectStage3GameScoring,
  type Stage3ExecutableArtifact,
  type Stage3ExecutableArtifactJob,
  type Stage3ExecutableArtifactPlan,
  type Stage3GameReadiness,
  type Stage3GameScoringJob,
  type Stage3GovernedGameScore,
} from "./projectModelLabApi";

type StepProps = { projectId: string; go?: (id: string) => void };
type DownstreamStepId = "calibration" | "simulation" | "champion" | "registry";
type MissingPrerequisite = { id: Exclude<DownstreamStepId, "registry">; label: string };

const int = (value: number) => new Intl.NumberFormat("en-US").format(value);
const human = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const metric = (value: number | null | undefined, digits = 6) => value == null || !Number.isFinite(value) ? "Not evaluated" : value.toFixed(digits);

function useDownstream(projectId: string) {
  const [data, setData] = useState<ProjectStage3Downstream | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError(null);
    try {
      const next = await fetchProjectStage3Downstream(projectId, controller.signal);
      if (!controller.signal.aborted) setData(next);
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "The project-bound downstream authority could not be loaded.");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [projectId]);
  useEffect(() => {
    void load();
    return () => request.current?.abort();
  }, [load]);
  return { data, loading, error, setError, load };
}

function useSelectedFinalist(data: ProjectStage3Downstream | null, preferredFingerprint?: string) {
  const [fingerprint, setFingerprint] = useState("");
  useEffect(() => {
    const finalists = data?.finalists ?? [];
    setFingerprint((current) => current && finalists.some((item) => item.candidateFingerprint === current)
      ? current
      : preferredFingerprint && finalists.some((item) => item.candidateFingerprint === preferredFingerprint)
        ? preferredFingerprint
        : finalists[0]?.candidateFingerprint ?? "");
  }, [data, preferredFingerprint]);
  return {
    fingerprint,
    setFingerprint,
    candidate: data?.finalists.find((item) => item.candidateFingerprint === fingerprint) ?? null,
  };
}

function currentDecisionFor(
  data: ProjectStage3Downstream | null,
  decisions: ProjectDownstreamDecision[] | undefined,
  fingerprint: string,
) {
  if (!data || !fingerprint) return undefined;
  return (decisions ?? []).find((item) =>
    item.authorityStatus === "CURRENT"
    && item.finalistSelectionId === data.authority.finalistSelectionId
    && item.candidateFingerprint === fingerprint,
  );
}

function earliestMissingPrerequisite(
  data: ProjectStage3Downstream | null,
  target: DownstreamStepId,
): MissingPrerequisite | null {
  if (!data || target === "calibration") return null;
  const finalistSelectionId = data.authority.finalistSelectionId;
  const currentCalibrations = new Set((data.calibrationDecisions ?? [])
    .filter((item) => item.authorityStatus === "CURRENT" && item.finalistSelectionId === finalistSelectionId)
    .map((item) => item.candidateFingerprint));
  if (!currentCalibrations.size) return { id: "calibration", label: "Step 12 · Calibration" };
  if (target === "simulation") return null;

  const currentGameEvaluations = new Set((data.gameEvaluationDecisions ?? [])
    .filter((item) => item.authorityStatus === "CURRENT"
      && item.finalistSelectionId === finalistSelectionId
      && currentCalibrations.has(item.candidateFingerprint))
    .map((item) => item.candidateFingerprint));
  if (!currentGameEvaluations.size) return { id: "simulation", label: "Step 13 · Simulation & Game-Level Evaluation" };
  if (target === "champion") return null;

  const hasResearchSelection = (data.selectionDecisions ?? []).some((item) =>
    item.authorityStatus === "CURRENT"
    && item.finalistSelectionId === finalistSelectionId
    && item.decision === "REGISTER_RESEARCH_CHALLENGER"
    && currentGameEvaluations.has(item.candidateFingerprint),
  );
  return hasResearchSelection ? null : { id: "champion", label: "Step 14 · Champion / Challenger Decision" };
}

function usePrerequisiteRedirect(
  data: ProjectStage3Downstream | null,
  target: DownstreamStepId,
  go?: (id: string) => void,
) {
  const missing = useMemo(() => earliestMissingPrerequisite(data, target), [data, target]);
  useEffect(() => {
    if (missing && go) go(missing.id);
  }, [go, missing]);
  return missing;
}

function PrerequisiteRedirect({ prerequisite, onGo }: { prerequisite: MissingPrerequisite; onGo?: () => void }) {
  return <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-amber-950" role="status" data-testid="downstream-prerequisite-redirect">
    <div className="flex items-center gap-2 text-sm font-semibold"><Lock size={16} />A required decision is missing</div>
    <p className="mt-2 text-xs leading-5">{prerequisite.label} must be completed before this page is available. No decision was skipped or inferred.</p>
    {onGo ? <button type="button" onClick={onGo} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-amber-950 px-3 py-2 text-xs font-semibold text-white">Go to {prerequisite.label} <ArrowRight size={13} /></button> : null}
  </section>;
}

function PageState({ loading, error, retry, children }: { loading: boolean; error: string | null; retry: () => Promise<void>; children: ReactNode }) {
  if (loading) return <section className="grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white" role="status"><div className="text-center"><Loader2 size={24} className="mx-auto animate-spin text-cyan-700" /><p className="mt-2 text-sm font-semibold text-slate-900">Resolving exact finalist evidence…</p><p className="mt-1 text-xs text-slate-500">No fit, score, calibration, simulation, or OOT access occurs on page load.</p></div></section>;
  if (error) return <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5" role="alert"><div className="flex items-center gap-2 font-semibold text-rose-950"><AlertTriangle size={17} />Project-bound workflow held closed</div><p className="mt-2 text-sm text-rose-800">{error}</p><button type="button" onClick={() => void retry()} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-rose-900 px-3 py-2 text-xs font-semibold text-white"><RefreshCw size={13} />Retry exact authority</button></section>;
  return <>{children}</>;
}

function StepHeader({ icon, eyebrow, title, description, data }: { icon: ReactNode; eyebrow: string; title: string; description: string; data: ProjectStage3Downstream }) {
  return <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white">
    <div className="grid gap-px bg-slate-800 xl:grid-cols-[minmax(0,1.75fr)_repeat(3,minmax(150px,.65fr))]">
      <div className="bg-slate-950 p-5"><div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-300">{icon}{eyebrow}</div><h2 className="mt-2 text-xl font-semibold">{title}</h2><p className="mt-1 max-w-3xl text-xs leading-5 text-slate-300">{description}</p></div>
      <DarkFact label="Development evidence" value={int(data.population.developmentRows)} detail={`${data.population.startDate} → ${data.population.endDate}`} />
      <DarkFact label="Explicit finalists" value={String(data.finalists.length)} detail="Immutable five-fold OOF evidence" />
      <DarkFact label="Final OOT" value={`${int(data.population.finalOotRows)} locked`} detail="No target access or scoring" tone="rose" />
    </div>
  </section>;
}

function FinalistPicker({ finalists, fingerprint, onChange }: { finalists: ProjectDownstreamFinalist[]; fingerprint: string; onChange: (value: string) => void }) {
  return <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
    <div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Database size={15} className="text-cyan-700" />Choose the finalist evidence to review</div>
    {finalists.length ? <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">{finalists.map((item) => <button key={item.candidateFingerprint} type="button" onClick={() => onChange(item.candidateFingerprint)} className={`rounded-xl border p-3 text-left transition ${fingerprint === item.candidateFingerprint ? "border-cyan-500 bg-cyan-50 shadow-sm" : "border-slate-200 bg-white hover:border-cyan-300"}`}>
      <div className="flex items-start justify-between gap-2"><b className="text-xs text-slate-950">{human(item.modelFamily)}</b><span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-1 text-[9px] font-semibold text-violet-900">FINALIST</span></div>
      <p className="mt-1 text-[10px] leading-4 text-slate-500">{item.featureSetName} · {item.featureCount} predictors</p>
      <div className="mt-2 grid grid-cols-2 gap-1 text-[10px]"><span>Log loss <b>{metric(item.meanOofLogLoss)}</b></span><span>ECE <b>{metric(item.ece)}</b></span></div>
      <p className="mt-2 truncate font-mono text-[9px] text-slate-400" title={item.immutableEvidenceIdentity ?? item.runReceiptSha256}>{item.immutableEvidenceIdentity ?? item.runReceiptSha256 ?? "Verified receipt"}</p>
    </button>)}</div> : <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-900"><b>No explicit finalist receipt exists.</b> Return to Candidate Evaluation and save finalist evidence first.</div>}
  </section>;
}

function LatestDecision({ label, decisions, fingerprint, finalistSelectionId }: { label: string; decisions: ProjectDownstreamDecision[]; fingerprint?: string; finalistSelectionId?: string | null }) {
  const rows = decisions.filter((item) =>
    (!fingerprint || item.candidateFingerprint === fingerprint)
    && (!finalistSelectionId || item.finalistSelectionId === finalistSelectionId)
    && item.authorityStatus === "CURRENT",
  );
  const latest = rows[0];
  if (!latest) return <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600"><b>{label}:</b> no decision recorded yet.</div>;
  const state = String(latest.disposition ?? latest.decision ?? latest.status ?? "RECORDED");
  const digest = latest.receiptSha256 ?? latest.checksum;
  return <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs leading-5 text-emerald-900"><CheckCircle2 size={14} className="mr-1 inline" /><b>{label}: {human(state)}</b>{latest.rationale ? <span> — {String(latest.rationale)}</span> : null}{digest ? <p className="mt-1 truncate font-mono text-[9px] text-emerald-700" title={String(digest)}>{String(digest)}</p> : null}</div>;
}

function SafetyStrip() {
  return <section className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="flex flex-wrap gap-2"><Pill tone="cyan" label="DEVELOPMENT OOF only" /><Pill tone="rose" label="Final OOT locked" /><Pill tone="amber" label="No promotion" /><Pill tone="emerald" label="0 provider calls" /><Pill tone="slate" label="No legacy matrix" /></div></section>;
}

export function ProjectBoundCalibration({ projectId, go }: StepProps) {
  const { data, loading, error, setError, load } = useDownstream(projectId);
  const { candidate, fingerprint, setFingerprint } = useSelectedFinalist(data);
  const calibrationDecision = currentDecisionFor(data, data?.calibrationDecisions, fingerprint);
  const [disposition, setDisposition] = useState<"RETAIN_RAW" | "DEFER_RECALIBRATION">("RETAIN_RAW");
  const [rationale, setRationale] = useState("Record no post-hoc recalibration for this aggregate five-fold development evidence; a later artifact-producing run must persist the probabilities it evaluates.");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    setNotice(null);
    setRationale(disposition === "RETAIN_RAW"
      ? "Record no post-hoc recalibration for this aggregate five-fold development evidence; a later artifact-producing run must persist the probabilities it evaluates."
      : "Defer recalibration until a governed rerun persists cross-fitted row-level OOF probabilities.");
  }, [disposition, fingerprint]);
  const save = async () => {
    if (!candidate) return;
    setSaving(true); setError(null); setNotice(null);
    try {
      await saveProjectCalibrationDecision(projectId, { candidateFingerprint: candidate.candidateFingerprint, disposition, rationale: rationale.trim() });
      setNotice("Immutable calibration disposition recorded. No calibrator was fit, and no unpersisted row-level probabilities are claimed.");
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "The calibration disposition failed closed."); }
    finally { setSaving(false); }
  };
  return <PageState loading={loading} error={error} retry={load}>{data ? <div className="min-w-0 space-y-4" data-testid="project-bound-calibration">
    <StepHeader icon={<Gauge size={14} />} eyebrow="Step 12 · Calibration" title="Decide how to carry the observed OOF probabilities forward" description="Review the exact five-fold raw calibration evidence already stored in each finalist receipt. This step records a disposition; it does not invent row-level predictions or fit a calibrator." data={data} />
    <FinalistPicker finalists={data.finalists} fingerprint={fingerprint} onChange={setFingerprint} />
    {candidate ? <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Scale size={15} className="text-cyan-700" />Raw five-fold OOF calibration evidence</div><div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4"><Metric label="OOF log loss" value={metric(candidate.meanOofLogLoss)} /><Metric label="Summed Brier" value={metric(candidate.summedBrier)} /><Metric label="ECE" value={metric(candidate.ece)} /><Metric label="Folds" value={`${candidate.foldsCompleted}/5`} /></div>
        <div className="mt-3 overflow-auto rounded-xl border border-slate-200"><table className="w-full min-w-[720px] text-left text-[10px]"><thead className="bg-slate-50 text-slate-600"><tr><th className="px-3 py-2">Outcome class</th><th className="px-3 py-2">Support</th><th className="px-3 py-2">Mean predicted</th><th className="px-3 py-2">Observed</th><th className="px-3 py-2">Absolute gap</th><th className="px-3 py-2">One-vs-rest Brier</th></tr></thead><tbody>{candidate.classCalibration.map((row) => <tr key={row.class}><td className="border-t border-slate-100 px-3 py-2 font-semibold">{human(row.class)}</td><td className="border-t border-slate-100 px-3 py-2">{int(row.support)}</td><td className="border-t border-slate-100 px-3 py-2 font-mono">{metric(row.meanPredictedProbability)}</td><td className="border-t border-slate-100 px-3 py-2 font-mono">{metric(row.observedRate)}</td><td className="border-t border-slate-100 px-3 py-2 font-mono">{metric(row.absoluteCalibrationError)}</td><td className="border-t border-slate-100 px-3 py-2 font-mono">{metric(row.oneVsRestBrier)}</td></tr>)}</tbody></table></div>
        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><AlertTriangle size={14} className="mr-1 inline" /><b>No reloadable row-level OOF probability artifact was persisted.</b> Aggregate ECE and class diagnostics are real evidence, but they are not enough to fit and independently evaluate Platt, isotonic, or temperature calibration now. Missing evidence is shown as not evaluated—not zero.</div>
      </article>
      <aside className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><FileCheck2 size={15} className="text-cyan-700" />Calibration disposition</div><div className="mt-3 space-y-2"><Choice active={disposition === "RETAIN_RAW"} title="No post-hoc recalibration" detail="Preserve the aggregate diagnostics as recorded; no row-level probabilities or calibrator are claimed." onClick={() => setDisposition("RETAIN_RAW")} /><Choice active={disposition === "DEFER_RECALIBRATION"} title="Defer recalibration" detail="Require a later artifact-producing rerun before calibration is evaluated." onClick={() => setDisposition("DEFER_RECALIBRATION")} /></div><label className="mt-3 block text-[10px] font-semibold uppercase text-slate-500">Scientific rationale<textarea rows={4} value={rationale} onChange={(event) => setRationale(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal normal-case text-slate-800" /></label><button type="button" disabled={saving || rationale.trim().length < 8} onClick={() => void save()} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">{saving ? <Loader2 size={13} className="animate-spin" /> : <FileCheck2 size={13} />}Record immutable disposition</button><p className="mt-2 text-[10px] leading-4 text-slate-500">This decision is development-only. It neither opens final OOT nor qualifies the candidate for deployment.</p></aside>
    </section> : null}
    <LatestDecision label="Current calibration disposition" decisions={data.calibrationDecisions} fingerprint={fingerprint} finalistSelectionId={data.authority.finalistSelectionId} />
    {notice ? <Notice>{notice}</Notice> : null}
    <SafetyStrip />
    <div className="flex justify-end"><button type="button" disabled={!calibrationDecision} onClick={() => go?.("simulation")} className="inline-flex items-center gap-2 rounded-lg bg-cyan-700 px-4 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">Continue to game-level evidence <ArrowRight size={13} /></button></div>
  </div> : null}</PageState>;
}

export function ProjectBoundGameEvaluation({ projectId, go }: StepProps) {
  const { data, loading, error, setError, load } = useDownstream(projectId);
  const missingPrerequisite = usePrerequisiteRedirect(data, "simulation", go);
  const preferred = data?.calibrationDecisions.find((item) => item.authorityStatus === "CURRENT" && item.finalistSelectionId === data.authority.finalistSelectionId)?.candidateFingerprint;
  const { candidate, fingerprint, setFingerprint } = useSelectedFinalist(data, preferred);
  const calibration = currentDecisionFor(data, data?.calibrationDecisions, fingerprint);
  const gameDecision = currentDecisionFor(data, data?.gameEvaluationDecisions, fingerprint);
  const [rationale, setRationale] = useState("Defer game simulation until a governed executable PA artifact and pregame lineup/starter inputs exist; preserve this candidate as development evidence only.");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const save = async () => {
    if (!candidate) return;
    setSaving(true); setError(null); setNotice(null);
    try {
      await saveProjectGameEvaluationDecision(projectId, { candidateFingerprint: candidate.candidateFingerprint, disposition: "DEFER_UNTIL_EXECUTABLE_ARTIFACT", rationale: rationale.trim() });
      setNotice("Game-level deferral recorded. The PA finalist remains eligible for a research-only selection decision; no game metrics were fabricated.");
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "The game-level evidence decision failed closed."); }
    finally { setSaving(false); }
  };
  return <PageState loading={loading} error={error} retry={load}>{data ? missingPrerequisite ? <PrerequisiteRedirect prerequisite={missingPrerequisite} onGo={() => go?.(missingPrerequisite.id)} /> : <div className="min-w-0 space-y-4" data-testid="project-bound-game-evaluation">
    <StepHeader icon={<Orbit size={14} />} eyebrow="Step 13 · Simulation & Game-Level Evaluation" title="Separate valid PA evidence from game simulation that has not run" description="The finalists have valid plate-appearance OOF diagnostics. Whole-game evaluation requires a reloadable fitted model plus governed pregame lineup and starter inputs; those authorities are not present in these receipts." data={data} />
    <FinalistPicker finalists={data.finalists} fingerprint={fingerprint} onChange={setFingerprint} />
    {candidate ? <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Orbit size={15} className="text-cyan-700" />Game-evaluation readiness</div><div className="mt-3 grid gap-2 sm:grid-cols-3"><Readiness state="AVAILABLE" title="PA development evidence" detail={`Five-fold OOF log loss ${metric(candidate.meanOofLogLoss)} across ${candidate.foldsCompleted} folds.`} /><Readiness state="MISSING" title="Executable finalist artifact" detail="No reloadable fitted estimator or row-level OOF probability file is bound to this receipt." /><Readiness state="MISSING" title="Pregame game inputs" detail="Current Gold does not provide governed target-game lineup and starter authority for simulation." /></div>
        <div className="mt-4 rounded-xl border border-slate-200"><div className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-[10px] font-semibold uppercase text-slate-600">Honest game-level scorecard</div><div className="grid gap-px bg-slate-200 sm:grid-cols-2 lg:grid-cols-4"><UnavailableMetric label="Win probability" /><UnavailableMetric label="Expected runs" /><UnavailableMetric label="Run distribution" /><UnavailableMetric label="Game log loss / Brier" /></div></div>
        <div className="mt-3 rounded-xl border border-cyan-200 bg-cyan-50 p-3 text-xs leading-5 text-cyan-950"><ShieldCheck size={14} className="mr-1 inline" /><b>Explicit deferral is not a failed PA model.</b> It records that game-level evidence is outside the executable evidence currently persisted. No placeholder score, synthetic lineup, postgame information, or legacy model is substituted.</div>
      </article>
      <aside className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Lock size={15} className="text-cyan-700" />Record the evidence boundary</div><div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><b>DEFER UNTIL EXECUTABLE ARTIFACT</b><br />The only scientifically valid action for the current receipt.</div>{!calibration ? <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-[10px] leading-4 text-rose-900"><b>Step 12 is required for this exact finalist.</b> Return to Calibration and record its disposition first.</div> : null}<label className="mt-3 block text-[10px] font-semibold uppercase text-slate-500">Reason<textarea rows={5} value={rationale} onChange={(event) => setRationale(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal normal-case text-slate-800" /></label><button type="button" disabled={saving || !calibration || rationale.trim().length < 8} onClick={() => void save()} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">{saving ? <Loader2 size={13} className="animate-spin" /> : <Lock size={13} />}Record development-only deferral</button></aside>
    </section> : null}
    <LatestDecision label="Current game-evaluation disposition" decisions={data.gameEvaluationDecisions} fingerprint={fingerprint} finalistSelectionId={data.authority.finalistSelectionId} />
    {notice ? <Notice>{notice}</Notice> : null}
    <SafetyStrip />
    <div className="flex justify-end"><button type="button" disabled={!gameDecision} onClick={() => go?.("champion")} className="inline-flex items-center gap-2 rounded-lg bg-cyan-700 px-4 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">Continue to development decision <ArrowRight size={13} /></button></div>
  </div> : null}</PageState>;
}

export function ProjectBoundChampionDecision({ projectId, go }: StepProps) {
  const { data, loading, error, setError, load } = useDownstream(projectId);
  const missingPrerequisite = usePrerequisiteRedirect(data, "champion", go);
  const preferred = data?.gameEvaluationDecisions.find((item) => item.authorityStatus === "CURRENT" && item.finalistSelectionId === data.authority.finalistSelectionId)?.candidateFingerprint;
  const { candidate, fingerprint, setFingerprint } = useSelectedFinalist(data, preferred);
  const calibration = currentDecisionFor(data, data?.calibrationDecisions, fingerprint);
  const gameDecision = currentDecisionFor(data, data?.gameEvaluationDecisions, fingerprint);
  const currentSelection = currentDecisionFor(data, data?.selectionDecisions, fingerprint);
  const [decision, setDecision] = useState<"REGISTER_RESEARCH_CHALLENGER" | "KEEP_INCUMBENT" | "DEFER_DECISION">("REGISTER_RESEARCH_CHALLENGER");
  const [rationale, setRationale] = useState("Register this finalist as a development research challenger for further artifact-producing evaluation; do not promote or replace the incumbent.");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    const copy = decision === "REGISTER_RESEARCH_CHALLENGER"
      ? "Register this finalist as a development research challenger for further artifact-producing evaluation; do not promote or replace the incumbent."
      : decision === "KEEP_INCUMBENT"
        ? "Keep the existing historical development benchmark as the incumbent and preserve this finalist as evaluated evidence."
        : "Defer the selection decision until additional governed development evidence is available.";
    setRationale(copy); setNotice(null);
  }, [decision, fingerprint]);
  const delta = candidate?.meanOofLogLoss != null && data?.historicalBenchmark?.meanOofLogLoss != null
    ? candidate.meanOofLogLoss - data.historicalBenchmark.meanOofLogLoss : null;
  const save = async () => {
    if (!candidate) return;
    setSaving(true); setError(null); setNotice(null);
    try {
      await saveProjectResearchSelection(projectId, { candidateFingerprint: candidate.candidateFingerprint, decision, rationale: rationale.trim() });
      setNotice(decision === "REGISTER_RESEARCH_CHALLENGER" ? "Research-challenger selection recorded. This is not a champion or promotion decision." : "Development selection decision recorded.");
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "The development selection failed closed."); }
    finally { setSaving(false); }
  };
  return <PageState loading={loading} error={error} retry={load}>{data ? missingPrerequisite ? <PrerequisiteRedirect prerequisite={missingPrerequisite} onGo={() => go?.(missingPrerequisite.id)} /> : <div className="min-w-0 space-y-4" data-testid="project-bound-champion-decision">
    <StepHeader icon={<Trophy size={14} />} eyebrow="Step 14 · Champion / Challenger Decision" title="Make a bounded development decision—not a promotion" description="A finalist does not have to beat the historical benchmark to be retained as a research challenger. Champion or production status still requires executable artifacts, game evaluation, untouched OOT, and a later explicit promotion review." data={data} />
    <FinalistPicker finalists={data.finalists} fingerprint={fingerprint} onChange={setFingerprint} />
    {candidate ? <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Scale size={15} className="text-cyan-700" />Development evidence comparison</div><div className="mt-3 overflow-hidden rounded-xl border border-slate-200"><div className="grid grid-cols-[minmax(0,1fr)_repeat(3,minmax(110px,.45fr))] bg-slate-50 px-3 py-2 text-[9px] font-semibold uppercase text-slate-500"><span>Evidence</span><span>OOF log loss</span><span>Feature set</span><span>Status</span></div><ComparisonRow name={`${human(candidate.modelFamily)} · selected finalist`} score={candidate.meanOofLogLoss} detail={candidate.featureSetName} status="RESEARCH CANDIDATE" /><ComparisonRow name={String(data.historicalBenchmark?.label ?? "Historical development benchmark")} score={data.historicalBenchmark?.meanOofLogLoss} detail={String(data.historicalBenchmark?.featureSetName ?? "Prior immutable evidence")} status="INCUMBENT BENCHMARK" /></div>
        <div className={`mt-3 rounded-xl border p-3 text-xs leading-5 ${delta != null && delta <= 0 ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}><b>{delta == null ? "Direct delta unavailable." : `${delta > 0 ? "+" : ""}${delta.toFixed(6)} log loss versus the historical benchmark (${delta <= 0 ? "lower is better" : "current finalist is higher"}).`}</b><br />This development comparison alone cannot establish a champion. Different feature contracts and missing downstream evidence remain material.</div>
        <div className="mt-3 rounded-xl border border-cyan-200 bg-cyan-50 p-3 text-xs leading-5 text-cyan-950"><b>You do not need to beat the current model to proceed.</b> “Register research challenger” means preserve the candidate for the next governed experiment. It does not replace, implement, export, or promote anything.</div>
      </article>
      <aside className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Trophy size={15} className="text-cyan-700" />Record one development decision</div><div className="mt-3 space-y-2"><Choice active={decision === "REGISTER_RESEARCH_CHALLENGER"} title="Register research challenger" detail="Preserve this candidate for the next governed artifact-producing study." onClick={() => setDecision("REGISTER_RESEARCH_CHALLENGER")} /><Choice active={decision === "KEEP_INCUMBENT"} title="Keep incumbent" detail="Do not advance this finalist; retain its evidence." onClick={() => setDecision("KEEP_INCUMBENT")} /><Choice active={decision === "DEFER_DECISION"} title="Defer decision" detail="Record that no selection is justified yet." onClick={() => setDecision("DEFER_DECISION")} /></div>{decision === "REGISTER_RESEARCH_CHALLENGER" && (!calibration || !gameDecision) ? <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-[10px] leading-4 text-rose-900"><b>This exact finalist has an incomplete evidence chain.</b> Record its Step 12 calibration disposition and Step 13 game-evaluation boundary first.</div> : null}<label className="mt-3 block text-[10px] font-semibold uppercase text-slate-500">Decision rationale<textarea rows={4} value={rationale} onChange={(event) => setRationale(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal normal-case text-slate-800" /></label><button type="button" disabled={saving || rationale.trim().length < 8 || (decision === "REGISTER_RESEARCH_CHALLENGER" && (!calibration || !gameDecision))} onClick={() => void save()} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">{saving ? <Loader2 size={13} className="animate-spin" /> : <FileCheck2 size={13} />}Save immutable decision</button><div className="mt-3 flex flex-wrap gap-1"><Pill tone="rose" label="NOT CHAMPION" /><Pill tone="amber" label="NOT PROMOTED" /><Pill tone="slate" label="OOT UNOPENED" /></div></aside>
    </section> : null}
    <LatestDecision label="Latest selection decision" decisions={data.selectionDecisions} fingerprint={fingerprint} finalistSelectionId={data.authority.finalistSelectionId} />
    {notice ? <Notice>{notice}</Notice> : null}
    <SafetyStrip />
    <div className="flex justify-end"><button type="button" disabled={currentSelection?.decision !== "REGISTER_RESEARCH_CHALLENGER"} onClick={() => go?.("registry")} className="inline-flex items-center gap-2 rounded-lg bg-cyan-700 px-4 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">Continue to research registry <ArrowRight size={13} /></button></div>
  </div> : null}</PageState>;
}

const activeArtifactStatuses = new Set(["QUEUED", "RUNNING", "CANCEL_REQUESTED"]);

function useExecutableArtifact(projectId: string) {
  const [summary, setSummary] = useState<ProjectStage3ExecutableArtifact | null>(null);
  const [plan, setPlan] = useState<Stage3ExecutableArtifactPlan | null>(null);
  const [job, setJob] = useState<Stage3ExecutableArtifactJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    try {
      const next = await fetchProjectStage3ExecutableArtifact(projectId, controller.signal);
      if (controller.signal.aborted) return;
      setSummary(next);
      setJob(next.currentJob);
      if (next.currentJob) setPlan(next.currentJob.plan);
      setError(null);
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Executable-artifact authority could not be loaded.");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [projectId]);
  useEffect(() => { void load(); return () => request.current?.abort(); }, [load]);

  const activeJobId = job && activeArtifactStatuses.has(job.status)
    ? job.jobId
    : summary?.currentJob && activeArtifactStatuses.has(summary.currentJob.status)
      ? summary.currentJob.jobId
      : null;
  useEffect(() => {
    if (!activeJobId) return undefined;
    let disposed = false;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const next = await fetchProjectStage3ExecutableArtifactJob(projectId, activeJobId);
        if (disposed) return;
        setJob(next);
        setPlan(next.plan);
        setError(null);
        if (!activeArtifactStatuses.has(next.status)) await load();
      } catch (caught) {
        if (!disposed) setError(caught instanceof Error ? caught.message : "Executable-artifact progress could not be refreshed.");
      } finally {
        polling = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2_500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [activeJobId, load, projectId]);
  return { summary, setSummary, plan, setPlan, job, setJob, loading, error, setError, load };
}

const activeScoringStatuses = new Set(["QUEUED", "RUNNING", "CANCEL_REQUESTED"]);

function useGovernedGameScoring(projectId: string) {
  const [summary, setSummary] = useState<ProjectStage3GameScoring | null>(null);
  const [job, setJob] = useState<Stage3GameScoringJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    try {
      const next = await fetchProjectStage3GameScoring(projectId, controller.signal);
      if (controller.signal.aborted) return;
      setSummary(next);
      setJob(next.currentJob);
      setError(null);
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Governed-game readiness could not be loaded.");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [projectId]);
  useEffect(() => { void load(); return () => request.current?.abort(); }, [load]);
  const activeJobId = job && activeScoringStatuses.has(job.status)
    ? job.jobId
    : summary?.currentJob && activeScoringStatuses.has(summary.currentJob.status)
      ? summary.currentJob.jobId
      : null;
  useEffect(() => {
    if (!activeJobId) return undefined;
    let disposed = false;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const next = await fetchProjectStage3GameScoringJob(projectId, activeJobId);
        if (disposed) return;
        setJob(next);
        setError(null);
        if (!activeScoringStatuses.has(next.status)) await load();
      } catch (caught) {
        if (!disposed) setError(caught instanceof Error ? caught.message : "Governed-game scoring progress could not be refreshed.");
      } finally {
        polling = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2_500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [activeJobId, load, projectId]);
  return { summary, job, setJob, loading, error, setError, load };
}

export function ProjectBoundRegistryHandoff({ projectId, go }: StepProps) {
  const { data, loading, error, setError, load } = useDownstream(projectId);
  const artifactState = useExecutableArtifact(projectId);
  const gameScoringState = useGovernedGameScoring(projectId);
  const missingPrerequisite = useMemo(() => earliestMissingPrerequisite(data, "registry"), [data]);
  const eligible = useMemo(() => (data?.selectionDecisions ?? []).filter((item) =>
    item.decision === "REGISTER_RESEARCH_CHALLENGER"
    && item.authorityStatus === "CURRENT"
    && item.finalistSelectionId === data?.authority.finalistSelectionId
    && (item.selectionId || item.decisionId),
  ), [data]);
  const [selectionId, setSelectionId] = useState("");
  const [nativeWorkers, setNativeWorkers] = useState(4);
  const [saving, setSaving] = useState(false);
  const [artifactAction, setArtifactAction] = useState<"PLAN" | "LAUNCH" | "CANCEL" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    setSelectionId((current) => current && eligible.some((item) => (item.selectionId ?? item.decisionId) === current)
      ? current
      : String(eligible[0]?.selectionId ?? eligible[0]?.decisionId ?? ""));
  }, [eligible]);

  const save = async () => {
    if (!selectionId) return;
    setSaving(true); setError(null); setNotice(null);
    try {
      await registerProjectResearchHandoff(projectId, selectionId);
      setNotice("Immutable research registry handoff created. The model remains a RESEARCH CHALLENGER and is NOT PROMOTED.");
      await Promise.all([load(), artifactState.load()]);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "The research registry handoff failed closed."); }
    finally { setSaving(false); }
  };

  const reviewArtifactPlan = async () => {
    const authoritativeSelection = artifactState.summary?.selection?.selectionDecisionId ?? selectionId;
    if (!authoritativeSelection) return;
    setArtifactAction("PLAN"); artifactState.setError(null); setNotice(null);
    try {
      const next = await planProjectStage3ExecutableArtifact(projectId, { selectionId: authoritativeSelection, nativeWorkers });
      artifactState.setPlan(next);
      artifactState.setJob(null);
      artifactState.setSummary((current) => current ? { ...current, currentJob: null } : current);
      setNotice("The immutable executable-artifact plan is ready for review. No fit has started.");
    } catch (caught) { artifactState.setError(caught instanceof Error ? caught.message : "Executable-artifact planning failed closed."); }
    finally { setArtifactAction(null); }
  };

  const launchArtifactJob = async () => {
    const reviewed = artifactState.plan;
    const authoritativeSelection = artifactState.summary?.selection?.selectionDecisionId ?? selectionId;
    if (!reviewed || !reviewed.executable || !authoritativeSelection) return;
    setArtifactAction("LAUNCH"); artifactState.setError(null); setNotice(null);
    try {
      const next = await enqueueProjectStage3ExecutableArtifact(
        projectId,
        reviewed,
        { selectionId: authoritativeSelection, nativeWorkers: reviewed.execution.nativeWorkers },
      );
      artifactState.setJob(next);
      artifactState.setPlan(next.plan);
      setNotice(`Executable research artifact job ${next.jobId} was queued. Completion will be shown only after persisted verification passes.`);
    } catch (caught) { artifactState.setError(caught instanceof Error ? caught.message : "Executable-artifact launch failed closed."); }
    finally { setArtifactAction(null); }
  };

  const cancelArtifactJob = async () => {
    const current = artifactState.job ?? artifactState.summary?.currentJob;
    if (!current || !activeArtifactStatuses.has(current.status)) return;
    setArtifactAction("CANCEL"); artifactState.setError(null);
    try {
      const next = await cancelUnstartedProjectStage3ExecutableArtifact(projectId, current.jobId);
      artifactState.setJob(next);
      setNotice("Cancel-unstarted was recorded. Completed evidence is retained and active work may finish draining.");
    } catch (caught) { artifactState.setError(caught instanceof Error ? caught.message : "Cancel-unstarted failed closed."); }
    finally { setArtifactAction(null); }
  };

  const artifactJob = artifactState.job ?? artifactState.summary?.currentJob ?? null;
  const persistedArtifact = artifactState.summary?.artifact ?? null;
  const artifactVerificationFailure = persistedArtifact?.status === "EXECUTABLE_RESEARCH_ARTIFACT_VERIFICATION_FAILED"
    ? persistedArtifact.verificationError
    : null;
  const artifact = persistedArtifact?.status === "EXECUTABLE_RESEARCH_ARTIFACT_MATERIALIZED"
    ? persistedArtifact
    : persistedArtifact === null && artifactJob?.status === "COMPLETE"
      ? artifactJob.artifact
      : null;
  const registered = artifactState.summary?.selection != null;
  const artifactRetryable = artifactVerificationFailure != null
    || (artifactJob != null && ["FAILED", "CANCELLED", "INTERRUPTED"].includes(artifactJob.status));
  useEffect(() => {
    if (artifact?.artifactId) void gameScoringState.load();
  }, [artifact?.artifactId, gameScoringState.load]);

  return <PageState loading={loading} error={error} retry={load}>{data ? missingPrerequisite ? <PrerequisiteRedirect prerequisite={missingPrerequisite} onGo={() => go?.(missingPrerequisite.id)} /> : <div className="min-w-0 space-y-4" data-testid="project-bound-registry-handoff">
    <StepHeader icon={<ClipboardList size={14} />} eyebrow="Step 15 · Registry, Artifact & Governed Scoring" title="Materialize a verified research artifact without promotion" description="Bind the immutable research-challenger selection, review its frozen artifact plan, follow persisted job progress, and score only games with complete point-in-time pregame authority. This step never promotes or opens final OOT." data={data} />

    <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><ClipboardList size={15} className="text-cyan-700" />Research registry state</div>
        {data.registryEntries.length ? <div className="mt-3 space-y-2">{data.registryEntries.map((entry, index) => <div key={String(entry.registryEntryId ?? entry.checksum ?? index)} className="rounded-xl border border-emerald-200 bg-emerald-50 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><b className="text-xs text-emerald-950">{String(entry.registryEntryId ?? "Immutable research registry entry")}</b><div className="flex gap-1"><Pill tone="amber" label="RESEARCH CHALLENGER" /><Pill tone="rose" label="NOT PROMOTED" /></div></div><p className="mt-2 truncate font-mono text-[9px] text-emerald-700" title={String(entry.receiptSha256 ?? entry.checksum ?? "")}>{String(entry.receiptSha256 ?? entry.checksum ?? "Checksum bound by registry response")}</p></div>)}</div> : <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs leading-5 text-slate-700">No immutable research entry exists yet. Bind the current <b>REGISTER RESEARCH CHALLENGER</b> selection before planning an artifact.</div>}
        <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4"><Readiness state="AVAILABLE" title="Development OOF" detail="Immutable five-fold aggregate evidence." /><Readiness state={artifact ? "AVAILABLE" : "MISSING"} title="Fitted estimator" detail={artifact ? "Verified and independently reloadable." : "Artifact verification has not completed."} /><Readiness state={artifact ? "AVAILABLE" : "MISSING"} title="Whole-game scoring" detail={artifact ? "Artifact ready; each game still requires pregame authority." : "Blocked until artifact materialization."} /><Readiness state="LOCKED" title="Final OOT" detail="LOCKED · target not accessed or scored." /></div>
      </article>
      <aside className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><FileCheck2 size={15} className="text-cyan-700" />Immutable research handoff</div>
        {!registered ? eligible.length ? <><label className="mt-3 block text-[10px] font-semibold uppercase text-slate-500">Research-challenger selection<select value={selectionId} onChange={(event) => setSelectionId(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal normal-case text-slate-800">{eligible.map((item) => { const id = String(item.selectionId ?? item.decisionId); return <option key={id} value={id}>{id}</option>; })}</select></label><button type="button" disabled={saving || !selectionId} onClick={() => void save()} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">{saving ? <Loader2 size={13} className="animate-spin" /> : <ClipboardList size={13} />}Create immutable research entry</button></> : <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><Lock size={14} className="mr-1 inline" />No compatible research-challenger selection is available. Return to Step 14.</div> : <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900"><CheckCircle2 size={14} className="mr-1 inline" />The exact research selection and registry entry are bound.</div>}
        <div className="mt-4 space-y-2"><StatusLine label="Model status" value="RESEARCH CHALLENGER" /><StatusLine label="Promotion" value="NOT PROMOTED" danger /><StatusLine label="Final OOT" value="LOCKED" danger /></div>
      </aside>
    </section>

    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="stage3-executable-artifact">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Database size={15} className="text-cyan-700" />BUILD EXECUTABLE RESEARCH ARTIFACT</div><p className="mt-1 max-w-3xl text-xs leading-5 text-slate-600">Reproduce five chronological OOF folds, persist their row-level probabilities, fit the final development-only pipeline, reload it in a fresh process, and publish only after checksum and fixture verification.</p></div>{artifactState.loading ? <span className="inline-flex items-center gap-2 text-xs text-slate-500"><Loader2 size={13} className="animate-spin" />Restoring persisted state…</span> : null}</div>
      {artifactState.error ? <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900" role="alert"><b>Artifact workflow held closed:</b> {artifactState.error}<button type="button" onClick={() => void artifactState.load()} className="ml-2 underline">Retry</button></div> : null}
      {artifactVerificationFailure ? <div className="mt-3 rounded-xl border border-rose-300 bg-rose-50 p-3 text-xs text-rose-950" role="alert"><b>{artifactVerificationFailure.code}:</b> {artifactVerificationFailure.message}<p className="mt-1 text-[10px]">The prior job record is retained, but the artifact is not treated as materialized or scoreable.</p></div> : null}
      {!artifact && !artifactJob && !artifactState.plan ? <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]"><div className="rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-xs leading-5 text-cyan-950"><b>Review comes before execution.</b><br />Planning reconciles the current project, Gold/contextual manifests, selection receipt, 234-feature order, five-fold split, frozen XGBoost configuration, zero-OOT guarantee, and no-promotion state. Planning starts zero model fits.</div><div><label className="block text-[10px] font-semibold uppercase text-slate-500">Native workers<select value={nativeWorkers} onChange={(event) => setNativeWorkers(Number(event.target.value))} disabled={!registered} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal normal-case text-slate-800"><option value={1}>1 worker</option><option value={2}>2 workers</option><option value={3}>3 workers</option><option value={4}>4 workers</option></select></label><button type="button" disabled={!registered || artifactAction !== null || artifactState.summary?.gates.artifactPlanReady !== true} onClick={() => void reviewArtifactPlan()} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-cyan-700 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">{artifactAction === "PLAN" ? <Loader2 size={13} className="animate-spin" /> : <FileCheck2 size={13} />}Review artifact build plan</button></div></div> : null}
      {artifactState.plan ? <ArtifactPlanReview plan={artifactState.plan} job={artifactJob} onLaunch={launchArtifactJob} launching={artifactAction === "LAUNCH"} /> : null}
      {artifactJob ? <ArtifactJobProgress job={artifactJob} cancelling={artifactAction === "CANCEL"} onCancel={cancelArtifactJob} /> : null}
      {artifactRetryable ? <button type="button" disabled={artifactAction !== null || artifactState.summary?.gates.artifactPlanReady !== true} onClick={() => void reviewArtifactPlan()} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-cyan-300 bg-white px-3 py-2 text-xs font-semibold text-cyan-950 disabled:cursor-not-allowed disabled:opacity-50">{artifactAction === "PLAN" ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}Review a fresh retry plan</button> : null}
      {artifact ? <ArtifactCompletion artifact={artifact} /> : null}
    </section>

    <GovernedGameScoringPanel projectId={projectId} artifact={artifact} state={gameScoringState} />

    {notice ? <Notice>{notice}</Notice> : null}
    <SafetyStrip />
    <div className="flex flex-wrap items-center justify-between gap-2"><button type="button" onClick={() => go?.("champion")} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-800">Return to development decision</button><p className="inline-flex cursor-default select-none items-center gap-2 text-xs font-semibold text-slate-800" role="status" aria-label="Implementation status"><ShieldCheck size={13} />Status: {artifact ? "verified executable research artifact available" : artifactJob ? human(artifactJob.status) : "artifact not materialized"}</p></div>
  </div> : null}</PageState>;
}

function ArtifactPlanReview({ plan, job, onLaunch, launching }: { plan: Stage3ExecutableArtifactPlan; job: Stage3ExecutableArtifactJob | null; onLaunch: () => Promise<void>; launching: boolean }) {
  const locked = job != null;
  return <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4" data-testid="stage3-artifact-plan-review">
    <div className="flex flex-wrap items-center justify-between gap-2"><b className="text-xs text-slate-950">Exact reviewed plan</b><div className="flex gap-1"><Pill tone="amber" label="RESEARCH CHALLENGER" /><Pill tone="rose" label="NOT PROMOTED" /><Pill tone="rose" label="OOT LOCKED" /></div></div>
    <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4"><PlanFact label="Project" value={`${plan.authority.projectName} · ${plan.projectId}`} /><PlanFact label="Candidate" value={`${human(plan.candidate.modelFamily)} · ${plan.selection.candidateAttemptId}`} /><PlanFact label="Data authority" value={`${plan.authority.goldDatasetId} · ${plan.authority.goldManifestSha}`} /><PlanFact label="Feature contract" value={`${int(plan.candidate.featureCount)} · ${plan.candidate.featureSetChecksum}`} /><PlanFact label="Ordered features SHA" value={plan.candidate.orderedFeaturesSha256} /><PlanFact label="Split" value={`${plan.authority.splitContractId} · ${plan.authority.splitChecksum}`} /><PlanFact label="Registered-fold OOF" value={`${int(plan.workload.oofRows)} rows · ${plan.workload.foldCount} folds`} /><PlanFact label="Final development fit" value={`${int(plan.workload.finalFitRows)} rows through ${plan.authority.developmentEnd}`} /><PlanFact label="Compute" value={`${plan.execution.computeClass} · ${plan.execution.nativeWorkers} native workers · ${plan.workload.modelFits} fits`} /><PlanFact label="Zero-OOT guarantee" value={`Final OOT ${plan.authority.finalOotStart} → ${plan.authority.finalOotEnd} stays LOCKED`} /><PlanFact label="Plan identity" value={`${plan.planId} · ${plan.checksum}`} /><PlanFact label="Contextual manifest" value={plan.authority.contextualManifestSha} /></div>
    <div className="mt-3"><div className="text-[9px] font-semibold uppercase text-slate-500">Governed target order</div><div className="mt-1 flex flex-wrap gap-1">{plan.candidate.targetOrder.map((target, index) => <Pill key={target} tone="slate" label={`${index + 1}. ${target}`} />)}</div></div>
    <div className="mt-3"><div className="text-[9px] font-semibold uppercase text-slate-500">Expected artifacts</div><ul className="mt-1 grid gap-1 text-[10px] text-slate-700 sm:grid-cols-2">{plan.expectedArtifacts.map((item) => <li key={item}>• {item}</li>)}</ul></div>
    {plan.executionBlocker ? <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900"><b>Plan blocked:</b> {plan.executionBlocker}</div> : null}
    {!locked ? <button type="button" disabled={launching || !plan.executable} onClick={() => void onLaunch()} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">{launching ? <Loader2 size={13} className="animate-spin" /> : <ArrowRight size={13} />}Launch exact reviewed artifact job</button> : null}
  </div>;
}

function ArtifactJobProgress({ job, cancelling, onCancel }: { job: Stage3ExecutableArtifactJob; cancelling: boolean; onCancel: () => Promise<void> }) {
  const progress = job.progress;
  const percent = job.plan.workload.oofRows > 0 ? Math.min(100, (progress.oofRowsPersisted / job.plan.workload.oofRows) * 100) : 0;
  const active = activeArtifactStatuses.has(job.status);
  return <div className="mt-4 rounded-xl border border-cyan-200 bg-cyan-50 p-4" data-testid="stage3-artifact-job-progress" role="status">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><b className="text-xs text-cyan-950">Persisted job {job.jobId}</b><p className="mt-1 text-[10px] text-cyan-800">{progress.message}</p></div><Pill tone={job.status === "COMPLETE" ? "emerald" : job.status === "FAILED" || job.status === "INTERRUPTED" ? "rose" : "cyan"} label={job.status} /></div>
    <div className="mt-3 h-2 overflow-hidden rounded-full bg-white"><div className="h-full rounded-full bg-cyan-700 transition-[width]" style={{ width: `${percent}%` }} /></div>
    <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4"><PlanFact label="Current fold" value={progress.currentFold == null ? "Not running" : `${progress.currentFold}/${job.plan.workload.foldCount}`} /><PlanFact label="Fold rows processed" value={int(progress.foldRowsProcessed)} /><PlanFact label="OOF rows persisted" value={`${int(progress.oofRowsPersisted)} / ${int(job.plan.workload.oofRows)}`} /><PlanFact label="Elapsed" value={`${Math.round(progress.elapsedSeconds)} seconds`} /><PlanFact label="Final fit" value={progress.finalFitState} /><PlanFact label="Artifact staging" value={progress.artifactStagingState} /><PlanFact label="Fresh-process reload" value={progress.reloadVerificationState} /><PlanFact label="Latest checkpoint" value={progress.latestCheckpoint ?? "None persisted yet"} /></div>
    {job.error ? <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900"><b>{job.error.code}:</b> {job.error.message}</div> : null}
    {active ? <button type="button" disabled={cancelling || job.status === "CANCEL_REQUESTED"} onClick={() => void onCancel()} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-cyan-300 bg-white px-3 py-2 text-xs font-semibold text-cyan-950 disabled:cursor-not-allowed disabled:opacity-50">{cancelling ? <Loader2 size={13} className="animate-spin" /> : <Ban size={13} />}Cancel unstarted work</button> : null}
  </div>;
}

function ArtifactCompletion({ artifact }: { artifact: Stage3ExecutableArtifact }) {
  return <div className="mt-4 rounded-xl border border-emerald-300 bg-emerald-50 p-4" data-testid="stage3-artifact-completion">
    <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2 text-sm font-semibold text-emerald-950"><CheckCircle2 size={16} />EXECUTABLE RESEARCH ARTIFACT MATERIALIZED</div><div className="flex gap-1"><Pill tone="amber" label="RESEARCH CHALLENGER" /><Pill tone="rose" label="NOT PROMOTED" /><Pill tone="rose" label="OOT LOCKED" /></div></div>
    <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4"><PlanFact label="Artifact ID" value={artifact.artifactId} /><PlanFact label="Manifest SHA" value={artifact.manifestSha256} /><PlanFact label="Model binary SHA" value={artifact.modelSha256} /><PlanFact label="Preprocessing SHA" value={artifact.preprocessingSha256} /><PlanFact label="OOF artifact SHA" value={artifact.oofArtifactSha256} /><PlanFact label="OOF rows" value={int(artifact.oofRows)} /><PlanFact label="Metric reproduction" value={`${artifact.metricReproduction.status} · max Δ ${artifact.metricReproduction.maxAbsoluteDifference}`} /><PlanFact label="Fresh-process reload" value={`${artifact.reloadVerification.status} · ${artifact.reloadVerification.freshProcess ? "verified" : "not verified"}`} /><PlanFact label="Verification fixture" value={`${artifact.verificationFixture.status} · max Δ ${artifact.verificationFixture.maxAbsoluteDifference}`} /><PlanFact label="Final training" value={`${int(artifact.trainingRows)} rows through ${artifact.trainingCutoff}`} /></div>
    <p className="mt-3 text-[10px] leading-4 text-emerald-900">This verified object is research-only. Artifact completion does not imply champion, production, export, deployment, or final-OOT approval.</p>
  </div>;
}

function GovernedGameScoringPanel({
  projectId,
  artifact,
  state,
}: {
  projectId: string;
  artifact: Stage3ExecutableArtifact | null;
  state: ReturnType<typeof useGovernedGameScoring>;
}) {
  const [selectedGameIds, setSelectedGameIds] = useState<Set<string>>(new Set());
  const [draws, setDraws] = useState(10_000);
  const [seed, setSeed] = useState(20260901);
  const [launching, setLaunching] = useState(false);
  const scoreableGames = useMemo(() => (state.summary?.games ?? []).filter((game) => game.scoreable && game.gameId), [state.summary]);
  useEffect(() => {
    setSelectedGameIds((current) => {
      const allowed = new Set(scoreableGames.map((game) => String(game.gameId)));
      const retained = new Set([...current].filter((gameId) => allowed.has(gameId)));
      if (!retained.size && scoreableGames[0]?.gameId) retained.add(scoreableGames[0].gameId);
      return retained;
    });
  }, [scoreableGames]);

  const scoringJob = state.job ?? state.summary?.currentJob ?? null;
  const results = scoringJob?.results.length ? scoringJob.results : state.summary?.results ?? [];
  const artifactMatches = Boolean(artifact
    && state.summary?.authority.artifactId === artifact.artifactId
    && state.summary.authority.artifactManifestSha256 === artifact.manifestSha256);
  const launch = async () => {
    if (!artifact || !artifactMatches || !state.summary?.readiness.ready || !selectedGameIds.size) return;
    setLaunching(true); state.setError(null);
    try {
      const next = await enqueueProjectStage3GameScoring(projectId, {
        artifactId: artifact.artifactId,
        gameIds: [...selectedGameIds],
        draws,
        seed,
      });
      state.setJob(next);
    } catch (caught) {
      state.setError(caught instanceof Error ? caught.message : "Governed-game scoring failed closed before launch.");
    } finally {
      setLaunching(false);
    }
  };
  const toggleGame = (gameId: string) => setSelectedGameIds((current) => {
    const next = new Set(current);
    if (next.has(gameId)) next.delete(gameId); else next.add(gameId);
    return next;
  });

  return <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="stage3-governed-game-scoring">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Orbit size={15} className="text-cyan-700" />SCORE GOVERNED GAMES</div><p className="mt-1 max-w-3xl text-xs leading-5 text-slate-600">Only canonical games with confirmed point-in-time lineups, announced starters, a pre-first-pitch feature cutoff, and a complete 234-feature vector can launch. Missing or ambiguous games fail closed independently.</p></div>{state.loading ? <span className="inline-flex items-center gap-2 text-xs text-slate-500"><Loader2 size={13} className="animate-spin" />Checking provider-free readiness…</span> : null}</div>
    <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4"><Readiness state={artifact ? "AVAILABLE" : "MISSING"} title="Verified artifact" detail={artifact ? artifact.artifactId : "Build and verify the research artifact first."} /><Readiness state={state.summary?.readiness.ready ? "AVAILABLE" : "MISSING"} title="Current game readiness" detail={state.summary?.readiness.ready ? `${scoreableGames.length} scoreable game(s).` : "BLOCKED · no scoreable current game authority."} /><Readiness state={scoreableGames.some((game) => game.lineupEvidence) ? "AVAILABLE" : "MISSING"} title="Lineup evidence" detail={scoreableGames.some((game) => game.lineupEvidence) ? "Confirmed point-in-time authority bound." : "Confirmed point-in-time lineup authority absent."} /><Readiness state={scoreableGames.some((game) => game.starterEvidence) ? "AVAILABLE" : "MISSING"} title="Starter evidence" detail={scoreableGames.some((game) => game.starterEvidence) ? "Announced-starter authority bound." : "Announced-starter authority absent."} /></div>
    {state.error ? <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900" role="alert"><b>Scoring held closed:</b> {state.error}<button type="button" onClick={() => void state.load()} className="ml-2 underline">Retry readiness</button></div> : null}
    {state.summary && !state.summary.readiness.ready ? <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-950" role="status" data-testid="stage3-game-readiness-blocked"><b>Current game readiness: BLOCKED</b>{state.summary.readiness.blockers.map((blocker) => <div key={blocker.code} className="mt-2"><span className="font-mono text-[10px] font-semibold">{blocker.code}</span><br />{blocker.message}</div>)}<p className="mt-2 text-[10px]">No provider was called, no game was fabricated, and no scoring job was created.</p></div> : null}
    {state.summary?.games.length ? <div className="mt-4 space-y-2"><div className="text-[10px] font-semibold uppercase text-slate-500">Game-by-game pregame evidence</div>{state.summary.games.map((game, index) => <GameReadinessRow key={game.gameId ?? `blocked-${index}`} game={game} selected={Boolean(game.gameId && selectedGameIds.has(game.gameId))} onToggle={toggleGame} />)}</div> : <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-700"><b>No governed games are available.</b> Prospective scoring remains empty until Model Studio receives a separately governed pregame inventory. Public reads do not discover schedules or call providers.</div>}
    {scoreableGames.length ? <div className="mt-4 grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-[1fr_1fr_auto]"><label className="text-[10px] font-semibold uppercase text-slate-500">Draws per game<input type="number" min={32} max={1_000_000} value={draws} onChange={(event) => setDraws(Number(event.target.value))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal text-slate-900" /></label><label className="text-[10px] font-semibold uppercase text-slate-500">Fixed seed<input type="number" min={0} value={seed} onChange={(event) => setSeed(Number(event.target.value))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal text-slate-900" /></label><button type="button" disabled={launching || !artifactMatches || state.summary?.readiness.ready !== true || !selectedGameIds.size || !Number.isSafeInteger(draws) || draws < 32 || draws > 1_000_000 || !Number.isSafeInteger(seed) || seed < 0} onClick={() => void launch()} className="self-end rounded-lg bg-slate-950 px-4 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">{launching ? <Loader2 size={13} className="mr-1 inline animate-spin" /> : <Orbit size={13} className="mr-1 inline" />}Score selected governed games</button></div> : null}
    {scoringJob ? <ScoringJobProgress job={scoringJob} /> : null}
    {results.length ? <div className="mt-4 space-y-3" data-testid="stage3-genuine-scoring-results"><div className="text-[10px] font-semibold uppercase text-slate-500">Verified whole-game results</div>{results.map((result) => <GovernedGameResultCard key={result.scoringReceiptSha256} result={result} game={state.summary?.games.find((game) => game.gameId === result.gameId)} />)}</div> : null}
    <div className="mt-4 flex flex-wrap gap-2"><Pill tone="amber" label="RESEARCH CHALLENGER" /><Pill tone="rose" label="NOT PROMOTED" /><Pill tone="rose" label="OOT LOCKED" /><Pill tone="emerald" label="0 PROVIDER CALLS" /></div>
  </section>;
}

function GameReadinessRow({ game, selected, onToggle }: { game: Stage3GameReadiness; selected: boolean; onToggle: (gameId: string) => void }) {
  return <div className={`rounded-xl border p-3 ${game.scoreable ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
    <div className="flex flex-wrap items-start justify-between gap-2"><label className="flex min-w-0 items-start gap-2"><input type="checkbox" checked={selected} disabled={!game.scoreable || !game.gameId} onChange={() => game.gameId && onToggle(game.gameId)} className="mt-0.5" /><span><b className="text-xs text-slate-950">{game.gameId ?? "AMBIGUOUS GAME ID"}</b><span className="mt-1 block text-[10px] text-slate-600">{game.awayTeamId ?? "unknown away team"} @ {game.homeTeamId ?? "unknown home team"} · {game.gameDate ?? "date missing"}</span></span></label><Pill tone={game.scoreable ? "emerald" : "amber"} label={game.status} /></div>
    <div className="mt-2 grid gap-1 text-[10px] text-slate-700 sm:grid-cols-2 lg:grid-cols-4"><span>First pitch <b>{game.scheduledFirstPitch ?? "MISSING"}</b></span><span>Lineup <b>{game.lineupEvidence?.status ?? "MISSING"}</b></span><span>Starters <b>{game.starterEvidence?.status ?? "MISSING"}</b></span><span>Feature cutoff <b>{game.featureCutoff ?? "MISSING"}</b></span></div>
    {game.missingPredictors.length ? <p className="mt-2 text-[10px] text-amber-900"><b>Missing predictors:</b> {game.missingPredictors.join(", ")}</p> : null}
    {game.blockedReasons.map((reason) => <p key={`${reason.code}-${reason.message}`} className="mt-2 text-[10px] text-amber-950"><b>{reason.code}:</b> {reason.message}</p>)}
  </div>;
}

function ScoringJobProgress({ job }: { job: Stage3GameScoringJob }) {
  const percent = job.progress.gamesTotal > 0 ? Math.min(100, (job.progress.gamesCompleted / job.progress.gamesTotal) * 100) : 0;
  return <div className="mt-4 rounded-xl border border-cyan-200 bg-cyan-50 p-4" role="status" data-testid="stage3-scoring-job-progress"><div className="flex flex-wrap items-start justify-between gap-2"><div><b className="text-xs text-cyan-950">Persisted scoring job {job.jobId}</b><p className="mt-1 text-[10px] text-cyan-800">{job.progress.statusMessage}</p></div><Pill tone={job.status === "COMPLETE" ? "emerald" : job.status === "FAILED" ? "rose" : "cyan"} label={job.status} /></div><div className="mt-3 h-2 overflow-hidden rounded-full bg-white"><div className="h-full bg-cyan-700" style={{ width: `${percent}%` }} /></div><div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4"><PlanFact label="Games" value={`${job.progress.gamesCompleted}/${job.progress.gamesTotal}`} /><PlanFact label="Current game" value={job.progress.currentGameId ?? "None"} /><PlanFact label="Draws per game" value={int(job.progress.drawsPerGame)} /><PlanFact label="Latest checkpoint" value={job.progress.latestCheckpoint ?? "None"} /></div>{job.error ? <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900"><b>{job.error.code}:</b> {job.error.message}</div> : null}</div>;
}

function GovernedGameResultCard({ result, game }: { result: Stage3GovernedGameScore; game?: Stage3GameReadiness }) {
  return <article className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><b className="text-sm text-emerald-950">{game ? `${game.awayTeamId} @ ${game.homeTeamId}` : result.gameId}</b><p className="mt-1 text-[10px] text-emerald-800">{result.gameDate} · {result.evidenceStatus} · {result.scoringMode}</p></div><Pill tone="emerald" label="RECONCILED" /></div>
    <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4"><PlanFact label="Expected score" value={`Away ${result.expectedAwayRuns.toFixed(3)} · Home ${result.expectedHomeRuns.toFixed(3)}`} /><PlanFact label="Win probabilities" value={`Away ${(result.awayWinProbability * 100).toFixed(2)}% · Home ${(result.homeWinProbability * 100).toFixed(2)}%`} /><PlanFact label="First five" value={`Away ${result.firstFive.expectedAwayRuns.toFixed(3)} · Home ${result.firstFive.expectedHomeRuns.toFixed(3)} · Tie ${(result.firstFive.tieProbability * 100).toFixed(2)}%`} /><PlanFact label="Extra innings" value={`${(result.extraInningProbability * 100).toFixed(2)}%`} /><PlanFact label="Model used" value={result.foldModelUsed ?? `Final development through ${result.trainedThrough}`} /><PlanFact label="Draws / seed" value={`${int(result.draws)} · ${result.seed}`} /><PlanFact label="Feature cutoff" value={result.featureCutoff} /><PlanFact label="Stability" value={`Home-win spread ${result.stability.maxHomeWinProbabilitySpread.toFixed(5)} · ${result.stability.method}`} /></div>
    <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(260px,.65fr)]"><div className="overflow-auto rounded-lg border border-emerald-200 bg-white"><table className="w-full min-w-[420px] text-left text-[10px]"><thead className="bg-emerald-100 text-emerald-950"><tr><th className="px-3 py-2">Most likely final score</th><th className="px-3 py-2">Draws</th><th className="px-3 py-2">Probability</th></tr></thead><tbody>{result.mostLikelyScores.map((row) => <tr key={`${row.awayRuns}-${row.homeRuns}`}><td className="border-t border-emerald-100 px-3 py-2">Away {row.awayRuns} · Home {row.homeRuns}</td><td className="border-t border-emerald-100 px-3 py-2">{int(row.count)}</td><td className="border-t border-emerald-100 px-3 py-2">{(row.probability * 100).toFixed(2)}%</td></tr>)}</tbody></table></div><div className="space-y-2"><StatusLine label="Joint distribution" value={`${result.jointScoreDistribution.length} cells · NORMALIZED`} /><StatusLine label="Margins / totals" value="RECONCILED" /><StatusLine label="First five" value="RECONCILED" /><StatusLine label="Legal base/out states" value={result.reconciliation.legalBaseOutStates ? "PASS" : "FAIL"} danger={!result.reconciliation.legalBaseOutStates} /><StatusLine label="All draws terminated" value={result.reconciliation.allDrawsTerminated ? "PASS" : "FAIL"} danger={!result.reconciliation.allDrawsTerminated} /></div></div>
    <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4"><PlanFact label="Artifact manifest SHA" value={result.artifactManifestSha256} /><PlanFact label="Model binary SHA" value={result.modelBinarySha256} /><PlanFact label="Feature vector SHA" value={result.featureVectorSha256} /><PlanFact label="Transition SHA" value={result.transitionModelSha256} /><PlanFact label="Lineup authority" value={`${result.lineupAuthority.authorityId} · ${result.lineupAuthority.checksumSha256}`} /><PlanFact label="Starter authority" value={`${result.starterAuthority.authorityId} · ${result.starterAuthority.checksumSha256}`} /><PlanFact label="Scoring receipt SHA" value={result.scoringReceiptSha256} /><PlanFact label="90% total interval" value={`${result.predictionIntervals.totalRuns90.p05}–${result.predictionIntervals.totalRuns90.p95}`} /></div>
    <p className="mt-3 text-[10px] text-emerald-900">No target-game outcome, actual substitution, actual reliever, sportsbook predictor, or external provider call was used.</p>
  </article>;
}

function PlanFact({ label, value }: { label: string; value: string }) { return <div className="min-w-0 rounded-lg border border-slate-200 bg-white p-2"><div className="text-[9px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 break-all text-[10px] font-semibold leading-4 text-slate-900" title={value}>{value}</div></div>; }

function DarkFact({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: "rose" }) { return <div className="min-w-0 bg-slate-950 px-4 py-4"><div className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">{label}</div><div className={`mt-1 truncate text-sm font-semibold ${tone === "rose" ? "text-rose-300" : "text-white"}`}>{value}</div><div className="mt-1 truncate text-[9px] text-slate-400">{detail}</div></div>; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-lg border border-slate-200 bg-slate-50 p-2"><div className="text-[9px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 text-xs font-semibold text-slate-950">{value}</div></div>; }
function Choice({ active, title, detail, onClick }: { active: boolean; title: string; detail: string; onClick: () => void }) { return <button type="button" onClick={onClick} className={`w-full rounded-xl border p-3 text-left ${active ? "border-cyan-500 bg-cyan-50" : "border-slate-200 bg-white hover:border-cyan-300"}`}><div className="flex items-center gap-2 text-xs font-semibold text-slate-950"><span className={`h-3 w-3 rounded-full border-2 ${active ? "border-cyan-700 bg-cyan-600" : "border-slate-300 bg-white"}`} />{title}</div><p className="mt-1 pl-5 text-[10px] leading-4 text-slate-500">{detail}</p></button>; }
function Readiness({ state, title, detail }: { state: "AVAILABLE" | "MISSING" | "LOCKED"; title: string; detail: string }) { const style = state === "AVAILABLE" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : state === "LOCKED" ? "border-rose-200 bg-rose-50 text-rose-900" : "border-amber-200 bg-amber-50 text-amber-900"; return <div className={`rounded-xl border p-3 ${style}`}><div className="text-[9px] font-semibold uppercase tracking-wide">{state}</div><div className="mt-1 text-xs font-semibold">{title}</div><p className="mt-1 text-[10px] leading-4 opacity-90">{detail}</p></div>; }
function UnavailableMetric({ label }: { label: string }) { return <div className="bg-white p-3"><div className="text-[9px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 text-xs font-semibold text-amber-800">NOT EVALUATED</div><div className="mt-1 text-[9px] text-slate-500">No executable authority</div></div>; }
function ComparisonRow({ name, score, detail, status }: { name: string; score: number | null | undefined; detail: string; status: string }) { return <div className="grid grid-cols-[minmax(0,1fr)_repeat(3,minmax(110px,.45fr))] items-center border-t border-slate-100 px-3 py-3 text-[10px]"><b className="truncate pr-2 text-slate-950">{name}</b><span className="font-mono font-semibold">{metric(score)}</span><span className="truncate pr-2" title={detail}>{detail}</span><span className="font-semibold text-slate-600">{status}</span></div>; }
function StatusLine({ label, value, danger }: { label: string; value: string; danger?: boolean }) { return <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[10px]"><span className="text-slate-500">{label}</span><b className={danger ? "text-rose-800" : "text-slate-900"}>{value}</b></div>; }
function Pill({ label, tone }: { label: string; tone: "emerald" | "cyan" | "rose" | "amber" | "slate" }) { const style = { emerald: "border-emerald-200 bg-emerald-50 text-emerald-800", cyan: "border-cyan-200 bg-cyan-50 text-cyan-800", rose: "border-rose-200 bg-rose-50 text-rose-800", amber: "border-amber-200 bg-amber-50 text-amber-900", slate: "border-slate-200 bg-white text-slate-700" }[tone]; return <span className={`inline-flex rounded-full border px-2 py-1 text-[9px] font-semibold ${style}`}>{label}</span>; }
function Notice({ children }: { children: ReactNode }) { return <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs leading-5 text-emerald-900"><CheckCircle2 size={14} className="mr-1 inline" />{children}</section>; }

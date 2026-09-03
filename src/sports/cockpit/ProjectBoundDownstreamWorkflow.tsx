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
  fetchProjectStage3Downstream,
  registerProjectResearchHandoff,
  saveProjectCalibrationDecision,
  saveProjectGameEvaluationDecision,
  saveProjectResearchSelection,
  type ProjectDownstreamDecision,
  type ProjectDownstreamFinalist,
  type ProjectStage3Downstream,
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

export function ProjectBoundRegistryHandoff({ projectId, go }: StepProps) {
  const { data, loading, error, setError, load } = useDownstream(projectId);
  const missingPrerequisite = useMemo(() => earliestMissingPrerequisite(data, "registry"), [data]);
  const eligible = useMemo(() => (data?.selectionDecisions ?? []).filter((item) =>
    item.decision === "REGISTER_RESEARCH_CHALLENGER"
    && item.authorityStatus === "CURRENT"
    && item.finalistSelectionId === data?.authority.finalistSelectionId
    && (item.selectionId || item.decisionId),
  ), [data]);
  const [selectionId, setSelectionId] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => { setSelectionId((current) => current && eligible.some((item) => (item.selectionId ?? item.decisionId) === current) ? current : String(eligible[0]?.selectionId ?? eligible[0]?.decisionId ?? "")); }, [eligible]);
  const save = async () => {
    if (!selectionId) return;
    setSaving(true); setError(null); setNotice(null);
    try {
      await registerProjectResearchHandoff(projectId, selectionId);
      setNotice("Immutable metadata-only research registry handoff created. No model binary was exported or deployed.");
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "The research registry handoff failed closed."); }
    finally { setSaving(false); }
  };
  return <PageState loading={loading} error={error} retry={load}>{data ? missingPrerequisite ? <PrerequisiteRedirect prerequisite={missingPrerequisite} onGo={() => go?.(missingPrerequisite.id)} /> : <div className="min-w-0 space-y-4" data-testid="project-bound-registry-handoff">
    <StepHeader icon={<ClipboardList size={14} />} eyebrow="Step 15 · Registry, Export & Implementation" title="Register evidence without pretending a deployable model exists" description="This bounded handoff can create an immutable research-candidate metadata entry. It cannot export or implement the candidate because the current receipt has no reloadable fitted estimator and has not completed game, final-OOT, or promotion review." data={data} />
    <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><ClipboardList size={15} className="text-cyan-700" />Research registry state</div>{data.registryEntries.length ? <div className="mt-3 space-y-2">{data.registryEntries.map((entry, index) => <div key={String(entry.registryEntryId ?? entry.checksum ?? index)} className="rounded-xl border border-emerald-200 bg-emerald-50 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><b className="text-xs text-emerald-950">{String(entry.registryEntryId ?? "Immutable research registry entry")}</b><div className="flex gap-1"><Pill tone="amber" label={String(entry.modelStatus ?? "RESEARCH_CHALLENGER")} /><Pill tone="rose" label={String(entry.deploymentStatus ?? "NOT_DEPLOYABLE")} /></div></div><p className="mt-2 truncate font-mono text-[9px] text-emerald-700" title={String(entry.receiptSha256 ?? entry.checksum ?? "")}>{String(entry.receiptSha256 ?? entry.checksum ?? "Checksum bound by registry response")}</p></div>)}</div> : <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs leading-5 text-slate-700">No metadata-only research entry has been created yet. First save a <b>REGISTER RESEARCH CHALLENGER</b> decision, then bind that immutable selection below.</div>}
        <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4"><Readiness state="AVAILABLE" title="Development OOF" detail="Immutable aggregate evidence." /><Readiness state="MISSING" title="Fitted estimator" detail="Not persisted in receipt." /><Readiness state="MISSING" title="Game simulation" detail="Explicitly deferred." /><Readiness state="LOCKED" title="Final OOT" detail="Still untouched." /></div>
        <div className="mt-4 rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-xs leading-5 text-cyan-950"><b>Exact next step</b><br />Run a separately governed artifact-producing experiment that persists the fitted estimator and genuine cross-fitted row-level OOF probabilities. Then evaluate recalibration, game simulation with pregame lineup/starter authority, untouched final OOT, and an explicit promotion decision. Until those steps pass, this entry stays research-only.</div>
      </article>
      <aside className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><FileCheck2 size={15} className="text-cyan-700" />Metadata-only handoff</div>{eligible.length ? <><label className="mt-3 block text-[10px] font-semibold uppercase text-slate-500">Research-challenger selection<select value={selectionId} onChange={(event) => setSelectionId(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal normal-case text-slate-800">{eligible.map((item) => { const id = String(item.selectionId ?? item.decisionId); return <option key={id} value={id}>{id}</option>; })}</select></label><button type="button" disabled={saving || !selectionId} onClick={() => void save()} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">{saving ? <Loader2 size={13} className="animate-spin" /> : <ClipboardList size={13} />}Create immutable research entry</button></> : <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"><Lock size={14} className="mr-1 inline" />No compatible research-challenger selection is available. Return to Step 14 and save one, or deliberately keep/defer the decision.</div>}<div className="mt-4 space-y-2"><StatusLine label="Registry classification" value="RESEARCH CHALLENGER" /><StatusLine label="Promotion" value="NOT PROMOTED" danger /><StatusLine label="Deployment" value="NOT DEPLOYABLE" danger /><StatusLine label="Export" value="NOT EXPORTED" danger /><StatusLine label="Final OOT" value="LOCKED" danger /></div></aside>
    </section>
    {notice ? <Notice>{notice}</Notice> : null}
    <SafetyStrip />
    <div className="flex flex-wrap items-center justify-between gap-2"><button type="button" onClick={() => go?.("champion")} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-800">Return to development decision</button><p className="inline-flex cursor-default select-none items-center gap-2 text-xs font-semibold text-rose-800" role="status" aria-label="Implementation status"><Ban size={13} />Status: implementation held closed until a deployable artifact exists</p></div>
  </div> : null}</PageState>;
}

function DarkFact({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: "rose" }) { return <div className="min-w-0 bg-slate-950 px-4 py-4"><div className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">{label}</div><div className={`mt-1 truncate text-sm font-semibold ${tone === "rose" ? "text-rose-300" : "text-white"}`}>{value}</div><div className="mt-1 truncate text-[9px] text-slate-400">{detail}</div></div>; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-lg border border-slate-200 bg-slate-50 p-2"><div className="text-[9px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 text-xs font-semibold text-slate-950">{value}</div></div>; }
function Choice({ active, title, detail, onClick }: { active: boolean; title: string; detail: string; onClick: () => void }) { return <button type="button" onClick={onClick} className={`w-full rounded-xl border p-3 text-left ${active ? "border-cyan-500 bg-cyan-50" : "border-slate-200 bg-white hover:border-cyan-300"}`}><div className="flex items-center gap-2 text-xs font-semibold text-slate-950"><span className={`h-3 w-3 rounded-full border-2 ${active ? "border-cyan-700 bg-cyan-600" : "border-slate-300 bg-white"}`} />{title}</div><p className="mt-1 pl-5 text-[10px] leading-4 text-slate-500">{detail}</p></button>; }
function Readiness({ state, title, detail }: { state: "AVAILABLE" | "MISSING" | "LOCKED"; title: string; detail: string }) { const style = state === "AVAILABLE" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : state === "LOCKED" ? "border-rose-200 bg-rose-50 text-rose-900" : "border-amber-200 bg-amber-50 text-amber-900"; return <div className={`rounded-xl border p-3 ${style}`}><div className="text-[9px] font-semibold uppercase tracking-wide">{state}</div><div className="mt-1 text-xs font-semibold">{title}</div><p className="mt-1 text-[10px] leading-4 opacity-90">{detail}</p></div>; }
function UnavailableMetric({ label }: { label: string }) { return <div className="bg-white p-3"><div className="text-[9px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 text-xs font-semibold text-amber-800">NOT EVALUATED</div><div className="mt-1 text-[9px] text-slate-500">No executable authority</div></div>; }
function ComparisonRow({ name, score, detail, status }: { name: string; score: number | null | undefined; detail: string; status: string }) { return <div className="grid grid-cols-[minmax(0,1fr)_repeat(3,minmax(110px,.45fr))] items-center border-t border-slate-100 px-3 py-3 text-[10px]"><b className="truncate pr-2 text-slate-950">{name}</b><span className="font-mono font-semibold">{metric(score)}</span><span className="truncate pr-2" title={detail}>{detail}</span><span className="font-semibold text-slate-600">{status}</span></div>; }
function StatusLine({ label, value, danger }: { label: string; value: string; danger?: boolean }) { return <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[10px]"><span className="text-slate-500">{label}</span><b className={danger ? "text-rose-800" : "text-slate-900"}>{value}</b></div>; }
function Pill({ label, tone }: { label: string; tone: "emerald" | "cyan" | "rose" | "amber" | "slate" }) { const style = { emerald: "border-emerald-200 bg-emerald-50 text-emerald-800", cyan: "border-cyan-200 bg-cyan-50 text-cyan-800", rose: "border-rose-200 bg-rose-50 text-rose-800", amber: "border-amber-200 bg-amber-50 text-amber-900", slate: "border-slate-200 bg-white text-slate-700" }[tone]; return <span className={`inline-flex rounded-full border px-2 py-1 text-[9px] font-semibold ${style}`}>{label}</span>; }
function Notice({ children }: { children: ReactNode }) { return <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs leading-5 text-emerald-900"><CheckCircle2 size={14} className="mr-1 inline" />{children}</section>; }

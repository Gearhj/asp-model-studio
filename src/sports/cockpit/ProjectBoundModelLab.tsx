import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle, BarChart3, CheckCircle2, ChevronRight, Cpu, FlaskConical,
  Gauge, Layers3, ListChecks, Loader2, Lock, Play, RefreshCw, ShieldCheck,
  SlidersHorizontal, Sparkles, TableProperties, Trash2,
} from "lucide-react";
import {
  enqueueProjectModelDevelopment, fetchProjectModelDevelopmentJob,
  fetchProjectModelDevelopmentJobs, fetchProjectModelLabRuns,
  fetchProjectModelLabSummary, planProjectModelDevelopment,
  type ModelAlgorithm, type ModelDevelopmentJob, type ModelDevelopmentPlan,
  type ModelExperimentDraft, type ModelLabCandidateResult, type ModelLabRun,
  type ProjectModelLabSummary,
} from "./projectModelLabApi";

type LoadState = "loading" | "ready" | "error";
type GridPreset = "COMPACT" | "FULL" | "CUSTOM";
type TuningMode = "FIXED" | "GRID" | "RANDOM";

const int = (value: number) => new Intl.NumberFormat("en-US").format(value);
const decimal = (value: number | null, digits = 6) => value == null ? "—" : value.toFixed(digits);
const duration = (value: number | null) => value == null ? "—" : value < 1_000 ? `${Math.round(value)} ms` : `${(value / 1_000).toFixed(1)} s`;
const short = (value: string) => value.length > 22 ? `${value.slice(0, 18)}…` : value;
const human = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

function gridCount(grid: Record<string, unknown[]>): number {
  const values = Object.values(grid);
  if (!values.length || values.some((items) => !Array.isArray(items) || !items.length)) return 0;
  return values.reduce((total, items) => total * items.length, 1);
}

function parseObject<T extends object>(value: string): T | null {
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as T : null;
  } catch {
    return null;
  }
}

function estimateConfigurations(
  algorithm: ModelAlgorithm | null,
  tuningMode: TuningMode,
  gridPreset: GridPreset,
  customGridText: string,
  randomIterations: number,
): number {
  if (!algorithm) return 0;
  if (tuningMode === "FIXED") return 1;
  const domain = gridPreset === "COMPACT"
    ? algorithm.compactGrid.length
    : gridPreset === "FULL"
      ? gridCount(algorithm.fullGrid)
      : gridCount(parseObject<Record<string, unknown[]>>(customGridText) ?? {});
  return tuningMode === "RANDOM" ? Math.min(Math.max(1, randomIterations), domain) : domain;
}

export function ProjectBoundModelLab({ projectId }: { projectId: string }) {
  const [state, setState] = useState<LoadState>("loading");
  const [summary, setSummary] = useState<ProjectModelLabSummary | null>(null);
  const [runs, setRuns] = useState<ModelLabRun[]>([]);
  const [jobs, setJobs] = useState<ModelDevelopmentJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [featureUniverseId, setFeatureUniverseId] = useState("");
  const [customFeatureText, setCustomFeatureText] = useState("");
  const [eligibilityRationale, setEligibilityRationale] = useState("");
  const [semanticCompatibilityAcknowledged, setSemanticCompatibilityAcknowledged] = useState(false);
  const [foldLocalTreatmentAcknowledged, setFoldLocalTreatmentAcknowledged] = useState(false);
  const [algorithmId, setAlgorithmId] = useState("xgboost");
  const [tuningMode, setTuningMode] = useState<TuningMode>("GRID");
  const [gridPreset, setGridPreset] = useState<GridPreset>("COMPACT");
  const [fixedText, setFixedText] = useState("{}");
  const [customGridText, setCustomGridText] = useState("{}");
  const [randomIterations, setRandomIterations] = useState(20);
  const [queue, setQueue] = useState<ModelExperimentDraft[]>([]);
  const [plan, setPlan] = useState<ModelDevelopmentPlan | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
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
        setFeatureUniverseId(next.featureUniverse.featureSetId);
        const preferred = next.modelCatalog.algorithms.find((item) => item.id === "xgboost" && item.available)
          ?? next.modelCatalog.algorithms.find((item) => item.id === "multinomial_logistic" && item.available)
          ?? next.modelCatalog.algorithms.find((item) => item.available);
        if (preferred) setAlgorithmId(preferred.id);
      }
      const [history, jobLedger] = await Promise.allSettled([
        fetchProjectModelLabRuns(projectId, next, controller.signal),
        fetchProjectModelDevelopmentJobs(projectId, controller.signal),
      ]);
      if (controller.signal.aborted) return;
      setRuns(history.status === "fulfilled" ? history.value : next.historicalEvidence.runs);
      if (jobLedger.status === "fulfilled") {
        setJobs(jobLedger.value);
        const active = jobLedger.value.find((job) => ["QUEUED", "RUNNING"].includes(job.status));
        setActiveJobId(active?.jobId ?? null);
      }
      setState("ready");
    } catch (caught) {
      if (controller.signal.aborted) return;
      setSummary(null);
      setRuns([]);
      setState("error");
      setError(caught instanceof Error ? caught.message : "The project-bound Model Development Laboratory could not be loaded.");
    }
  }, [projectId]);

  useEffect(() => {
    void load();
    return () => request.current?.abort();
  }, [load]);

  useEffect(() => {
    if (!activeJobId) return undefined;
    let disposed = false;
    const poll = async () => {
      try {
        const job = await fetchProjectModelDevelopmentJob(projectId, activeJobId);
        if (disposed) return;
        setJobs((current) => [job, ...current.filter((item) => item.jobId !== job.jobId)]);
        if (!["QUEUED", "RUNNING"].includes(job.status)) {
          setActiveJobId(null);
          if (summary) {
            const history = await fetchProjectModelLabRuns(projectId, summary);
            if (!disposed) setRuns(history);
          }
        }
      } catch (caught) {
        if (!disposed) setActionError(caught instanceof Error ? caught.message : "Job progress could not be refreshed.");
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2_000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [activeJobId, projectId, summary]);

  const algorithm = useMemo(
    () => summary?.modelCatalog.algorithms.find((item) => item.id === algorithmId) ?? null,
    [algorithmId, summary],
  );
  const chosenFeature = useMemo(() => {
    if (!summary) return null;
    if (featureUniverseId === summary.featureUniverse.featureSetId) {
      return { name: summary.featureUniverse.name, count: summary.featureUniverse.featureCount, executable: true };
    }
    if (featureUniverseId === "CUSTOM_SUBSET") {
      const count = customFeatureText.split(",").filter((item) => item.trim()).length;
      return { name: "Custom eligible subset", count, executable: count > 0 };
    }
    const saved = summary.featureSets.find((item) => item.featureSetId === featureUniverseId);
    const reviewedOverride = Boolean(
      saved?.overrideEligible
      && eligibilityRationale.trim().length >= 20
      && semanticCompatibilityAcknowledged
      && foldLocalTreatmentAcknowledged
    );
    return saved ? { name: saved.name, count: saved.featureCount, executable: saved.executable !== false || reviewedOverride } : null;
  }, [customFeatureText, eligibilityRationale, featureUniverseId, foldLocalTreatmentAcknowledged, semanticCompatibilityAcknowledged, summary]);
  const configurationCount = estimateConfigurations(algorithm, tuningMode, gridPreset, customGridText, randomIterations);
  const fitCount = configurationCount * (summary?.split.foldCount ?? 5);
  const selectedSaved = summary?.featureSets.find((item) => item.featureSetId === featureUniverseId) ?? null;
  const currentJob = jobs.find((item) => item.jobId === activeJobId) ?? jobs[0] ?? null;

  useEffect(() => {
    if (!algorithm) return;
    setFixedText(JSON.stringify(algorithm.fixedHyperparameters, null, 2));
    setCustomGridText(JSON.stringify(algorithm.fullGrid, null, 2));
    setTuningMode(algorithm.defaultTuningMode);
    setGridPreset(algorithm.defaultGridPreset);
    setPlan(null);
  }, [algorithm]);

  const draft = (): ModelExperimentDraft | null => {
    if (!algorithm || !summary || !chosenFeature) return null;
    const fixed = parseObject<Record<string, unknown>>(fixedText);
    const custom = parseObject<Record<string, unknown[]>>(customGridText);
    if (tuningMode === "FIXED" && !fixed) {
      setActionError("Fixed hyperparameters must be a valid JSON object.");
      return null;
    }
    if (gridPreset === "CUSTOM" && !custom) {
      setActionError("Custom Grid must be a valid JSON object of parameter arrays.");
      return null;
    }
    return {
      algorithmId: algorithm.id,
      featureUniverseId,
      tuningMode: algorithm.id === "class_frequency_null" ? "FIXED" : tuningMode,
      gridPreset,
      fixedHyperparameters: fixed ?? undefined,
      customGrid: gridPreset === "CUSTOM" ? custom ?? undefined : undefined,
      randomIterations: tuningMode === "RANDOM" ? randomIterations : undefined,
      orderedFeatures: featureUniverseId === "CUSTOM_SUBSET"
        ? customFeatureText.split(",").map((item) => item.trim()).filter(Boolean)
        : undefined,
      eligibilityOverrideRationale: eligibilityRationale || undefined,
      prospectiveSemanticCompatibilityAcknowledged: selectedSaved?.overrideEligible ? semanticCompatibilityAcknowledged : undefined,
      foldLocalTreatmentAcknowledged: selectedSaved?.overrideEligible ? foldLocalTreatmentAcknowledged : undefined,
      seed: 20260901,
    };
  };

  const addToQueue = () => {
    const item = draft();
    if (!item || !chosenFeature?.executable || !algorithm?.available || configurationCount < 1) return;
    const key = JSON.stringify(item);
    if (queue.some((candidate) => JSON.stringify(candidate) === key)) {
      setActionError("That exact model configuration is already in the queue.");
      return;
    }
    setQueue((current) => [...current, item]);
    setPlan(null);
    setAcknowledged(false);
    setActionError(null);
  };

  const reviewPlan = async () => {
    if (!summary || !queue.length || planning) return;
    setPlanning(true);
    setActionError(null);
    try {
      setPlan(await planProjectModelDevelopment(projectId, summary, queue, acknowledged));
    } catch (caught) {
      setPlan(null);
      setActionError(caught instanceof Error ? caught.message : "The queue plan failed closed.");
    } finally {
      setPlanning(false);
    }
  };

  const runQueue = async () => {
    if (!summary || !plan?.executable || launching || activeJobId) return;
    setLaunching(true);
    setActionError(null);
    try {
      const job = await enqueueProjectModelDevelopment(projectId, summary, queue, acknowledged);
      setJobs((current) => [job, ...current.filter((item) => item.jobId !== job.jobId)]);
      setActiveJobId(job.jobId);
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "The project-scoped queue failed to start.");
    } finally {
      setLaunching(false);
    }
  };

  if (state === "loading") return <Loading />;
  if (state === "error" || !summary) return <Failure message={error || "Project authority unavailable."} retry={load} />;

  return (
    <div className="min-w-0 space-y-4" data-testid="stage3-project-bound-model-laboratory">
      <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white shadow-sm" data-testid="model-lab-project-context">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/10 px-4 py-4 sm:px-5">
          <div>
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-300"><FlaskConical size={14} />Stage 3 · Model Development Laboratory</div>
            <h2 className="mt-1 text-xl font-semibold">Build, tune, queue, and compare honest development candidates</h2>
            <p className="mt-1 max-w-4xl text-xs leading-5 text-slate-300">One project-bound workspace for feature authority, algorithms, hyperparameters, exact five-fold workload planning, execution progress, and the development leaderboard. Opening this page performs zero fits.</p>
          </div>
          <StatusBadge ready={summary.readiness.ready} />
        </div>
        <div className="grid gap-px bg-white/10 sm:grid-cols-2 xl:grid-cols-4">
          <DarkFact label="Development" value={`${int(summary.population.developmentRows)} rows`} detail={`${summary.population.startDate} → ${summary.population.endDate}`} />
          <DarkFact label="Default universe" value={`${summary.featureUniverse.featureCount} eligible predictors`} detail={summary.featureUniverse.featureSetId} />
          <DarkFact label="Validation" value={`${summary.split.foldCount} expanding folds`} detail={summary.split.splitContractId} />
          <DarkFact label="Final OOT" value={`${int(summary.population.finalOotRows)} locked`} detail="Targets never materialized or queried" tone="rose" />
        </div>
      </section>

      {!summary.readiness.ready ? <BlockingReasons blockers={summary.readiness.blockers} /> : null}

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(300px,.55fr)]">
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="model-lab-feature-universe">
          <SectionTitle icon={<Layers3 size={16} />} title="1 · Feature universe" description="Full Eligible is the largest governed, point-in-time-valid, forecast-compatible universe—not every physical column." />
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <UniverseButton active={featureUniverseId === summary.featureUniverse.featureSetId} onClick={() => setFeatureUniverseId(summary.featureUniverse.featureSetId)} title="Full Eligible" detail={`${summary.featureUniverse.featureCount} predictors`} status="RECOMMENDED" tone="emerald" />
            <UniverseButton active={featureUniverseId === summary.featureSets[0]?.featureSetId} onClick={() => setFeatureUniverseId(summary.featureSets[0]?.featureSetId ?? "")} title="Core Gold 48" detail="Transparent benchmark" status="BENCHMARK" tone="cyan" />
            <UniverseButton active={featureUniverseId === "CUSTOM_SUBSET"} onClick={() => setFeatureUniverseId("CUSTOM_SUBSET")} title="Custom subset" detail="Eligible predictors only" status="DEVELOPMENT ONLY" tone="slate" />
            <UniverseButton active={Boolean(selectedSaved && selectedSaved.featureSetId !== summary.featureSets[0]?.featureSetId)} onClick={() => setFeatureUniverseId(summary.featureSets.find((item) => item.featureSetId !== summary.featureSets[0]?.featureSetId)?.featureSetId ?? summary.featureSets[0]?.featureSetId ?? "")} title="Saved governed set" detail="Research / ablation preset" status="SECONDARY" tone="amber" />
          </div>
          {featureUniverseId === "CUSTOM_SUBSET" ? <label className="mt-3 block text-xs font-semibold text-slate-700">Ordered eligible feature names, comma separated<textarea value={customFeatureText} onChange={(event) => { setCustomFeatureText(event.target.value); setPlan(null); }} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs" placeholder="context_inning, context_outs_before, ..." /></label> : null}
          <details className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3" data-testid="model-lab-exclusion-inspector">
            <summary className="cursor-pointer text-xs font-semibold text-slate-800">Inspect all {summary.featureUniverse.reconciliation.excludedPredictorCount} exclusions and rule decisions</summary>
            <EligibilitySummary summary={summary} />
          </details>
          <details className="mt-3 rounded-xl border border-slate-200 p-3" data-testid="model-lab-ablation-presets">
            <summary className="cursor-pointer text-xs font-semibold text-slate-800">Ablation / research presets · historical A/B/C evidence preserved</summary>
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              {summary.featureSets.map((item) => { const hardBlocked = item.executionStatus === "NON_EXECUTABLE_CURRENT_AUTHORITY"; return <button key={item.featureSetId} type="button" disabled={hardBlocked} onClick={() => { setFeatureUniverseId(item.featureSetId); setPlan(null); }} className={`rounded-lg border p-3 text-left ${item.executable ? "border-slate-200 bg-white hover:border-cyan-300" : hardBlocked ? "cursor-not-allowed border-rose-200 bg-rose-50" : "border-amber-200 bg-amber-50 hover:border-amber-400"}`}><div className="text-xs font-semibold text-slate-900">{item.name}</div><div className="mt-1 text-[10px] uppercase text-slate-500">{item.featureCount} predictors · {human(item.executionStatus ?? "UNKNOWN")}</div>{item.blockingFeatures?.length ? <p className="mt-2 text-[10px] leading-4 text-rose-700">Blocked: {item.blockingFeatures.map((entry) => entry.name).join(", ")}</p> : null}{item.reviewRequiredFeatures?.length ? <p className="mt-2 text-[10px] leading-4 text-amber-800">Written override required: {item.reviewRequiredFeatures.map((entry) => entry.name).join(", ")}</p> : null}</button>; })}
            </div>
          </details>
          {selectedSaved?.reviewRequiredFeatures?.length ? <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900"><label className="block font-semibold">Prospective semantic-sparse rationale<textarea value={eligibilityRationale} onChange={(event) => { setEligibilityRationale(event.target.value); setPlan(null); }} rows={2} className="mt-2 w-full rounded-md border border-amber-300 bg-white px-2 py-1.5 text-xs text-slate-800" placeholder="Explain why null has a valid prospective meaning and how fold-local treatment preserves it." /></label><label className="mt-2 flex items-start gap-2"><input type="checkbox" checked={semanticCompatibilityAcknowledged} onChange={(event) => { setSemanticCompatibilityAcknowledged(event.target.checked); setPlan(null); }} className="mt-0.5" /><span>I confirm the sparse state has defensible prospective semantics under this run.</span></label><label className="mt-2 flex items-start gap-2"><input type="checkbox" checked={foldLocalTreatmentAcknowledged} onChange={(event) => { setFoldLocalTreatmentAcknowledged(event.target.checked); setPlan(null); }} className="mt-0.5" /><span>I confirm every treatment parameter remains fitted inside its chronological training fold.</span></label></div> : null}
        </section>

        <AuthorityCard title="Scientific authority" icon={<ShieldCheck size={16} />}>
          <AuthorityRows rows={[
            ["Gold", summary.authority.goldDatasetId, summary.authority.goldManifestSha],
            ["Split", `v${summary.split.version} · ${summary.split.foldCount} folds`, summary.split.splitContractId],
            ["Outlier", `v${summary.policies.outlier.version} · adopted`, summary.policies.outlier.policyId],
            ["Missing", `v${summary.policies.missing.version} · adopted`, summary.policies.missing.policyId],
          ]} />
          <div className="mt-3 flex flex-wrap gap-1.5"><Pill label="Fold-local preprocessing" tone="cyan" /><Pill label="Legacy matrix prohibited" tone="rose" /><Pill label="No promotion" tone="slate" /></div>
          <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-[11px] leading-5 text-rose-800"><Lock size={13} className="mr-1 inline" />Final OOT {summary.population.finalOotStartDate} → {summary.population.finalOotEndDate} remains inaccessible to training, tuning, calibration, feature selection, and metrics.</div>
        </AuthorityCard>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="model-lab-model-families">
        <SectionTitle icon={<Gauge size={16} />} title="2 · Algorithm and model family" description="Only supervised eight-class candidates enter this leaderboard. Anomaly / novelty analytics remain a separate research capability." />
        <div className="mt-3 space-y-3">
          {summary.modelCatalog.families.map((family) => {
            const members = family.algorithms.map((id) => summary.modelCatalog.algorithms.find((item) => item.id === id)).filter((item): item is ModelAlgorithm => Boolean(item));
            return <div key={family.id}><div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">{family.label}</div><div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">{members.map((item) => <button key={item.id} type="button" disabled={!item.available} onClick={() => { setAlgorithmId(item.id); setPlan(null); }} className={`rounded-lg border p-3 text-left ${item.id === algorithmId ? "border-cyan-500 bg-cyan-50 ring-1 ring-cyan-100" : item.available ? "border-slate-200 bg-white hover:border-cyan-300" : "cursor-not-allowed border-slate-200 bg-slate-50 opacity-70"}`}><div className="text-xs font-semibold text-slate-900">{item.label}</div><div className="mt-1 text-[10px] uppercase text-slate-500">{item.available ? `${item.computeIntensity} compute` : human(item.status)}</div>{!item.available ? <div className="mt-1 text-[10px] leading-4 text-amber-800">{item.unavailableReason}</div> : null}</button>)}</div></div>;
          })}
        </div>
        <details className="mt-3 rounded-xl border border-violet-200 bg-violet-50 p-3"><summary className="cursor-pointer text-xs font-semibold text-violet-900">Anomaly / Novelty Analytics — not ranked against supervised models</summary><p className="mt-2 text-xs leading-5 text-violet-800">{summary.modelCatalog.anomalyAnalytics.algorithms.join(", ")} are reserved for unusual-observation, OOD, regime, and data-quality research. They are never ranked on eight-class log loss beside XGBoost.</p></details>
      </section>

      {algorithm ? <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="model-lab-inline-tuning">
        <SectionTitle icon={<SlidersHorizontal size={16} />} title="3 · Inline hyperparameter strategy" description={`${algorithm.label} · ${chosenFeature?.name ?? "Choose a feature universe"} · exact registered five-fold development split.`} />
        <div className="mt-3 grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
          <div>
            <div className="flex flex-wrap gap-2" aria-label="Tuning mode">
              {algorithm.supportedTuningModes.map((mode) => <ChoiceButton key={mode} active={tuningMode === mode} onClick={() => { setTuningMode(mode); setPlan(null); }}>{human(mode)}</ChoiceButton>)}
            </div>
            {tuningMode !== "FIXED" ? <div className="mt-3 flex flex-wrap gap-2" aria-label="Grid preset">{(["COMPACT", "FULL", "CUSTOM"] as GridPreset[]).map((preset) => <ChoiceButton key={preset} active={gridPreset === preset} onClick={() => { setGridPreset(preset); setPlan(null); }}>{preset === "COMPACT" ? "Compact Grid" : preset === "FULL" ? "Full Grid" : "Custom Grid"}</ChoiceButton>)}</div> : null}
            {tuningMode === "FIXED" ? <JsonEditor label="Fixed hyperparameters" value={fixedText} onChange={(value) => { setFixedText(value); setPlan(null); }} /> : gridPreset === "CUSTOM" ? <JsonEditor label="Custom parameter grid" value={customGridText} onChange={(value) => { setCustomGridText(value); setPlan(null); }} /> : <GridPreview algorithm={algorithm} preset={gridPreset} />}
            {tuningMode === "RANDOM" ? <label className="mt-3 block max-w-xs text-xs font-semibold text-slate-700">Random configurations<input type="number" min={1} value={randomIterations} onChange={(event) => { setRandomIterations(Number(event.target.value) || 1); setPlan(null); }} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label> : null}
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 text-white" data-testid="model-lab-fit-estimate"><div className="text-[10px] font-semibold uppercase tracking-wide text-cyan-300">Planned workload</div><div className="mt-3 grid grid-cols-[1fr_auto] gap-y-2 text-xs"><span>Configurations</span><b>{int(configurationCount)}</b><span>Registered folds</span><b>× {summary.split.foldCount}</b><span className="border-t border-white/20 pt-2">Total fits</span><b className="border-t border-white/20 pt-2 text-lg text-cyan-200">{int(fitCount)}</b></div><div className={`mt-3 rounded-lg border p-2 text-[10px] leading-4 ${fitCount > summary.modelCatalog.tuning.hardFitLimit ? "border-rose-400/50 bg-rose-400/10 text-rose-200" : fitCount > summary.modelCatalog.tuning.warningFitThreshold ? "border-amber-400/50 bg-amber-400/10 text-amber-200" : "border-emerald-400/40 bg-emerald-400/10 text-emerald-200"}`}>{fitCount > summary.modelCatalog.tuning.hardFitLimit ? `Held closed above ${int(summary.modelCatalog.tuning.hardFitLimit)} fits. Reduce the grid.` : fitCount > summary.modelCatalog.tuning.warningFitThreshold ? "Explicit compute acknowledgement will be required before launch." : "Within the bounded default planning envelope."}</div><div className="mt-2 text-[10px] text-slate-400">Estimator-native workers capped · one project job at a time · seed 20260901</div></div>
        </div>
        <button type="button" onClick={addToQueue} disabled={!algorithm.available || !chosenFeature?.executable || configurationCount < 1} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"><ListChecks size={15} />Add to Experiment Queue</button>
      </section> : null}

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="model-lab-experiment-queue">
        <SectionTitle icon={<TableProperties size={16} />} title="4 · Experiment queue" description="Review every algorithm, universe, tuning strategy, configuration count, and five-fold fit burden before execution." />
        {queue.length ? <div role="region" aria-label="Experiment queue" tabIndex={0} className="mt-3 overflow-x-auto"><table className="w-full min-w-[1240px] text-left text-xs"><caption className="sr-only">Queued development experiments and exact fit counts</caption><thead><tr>{["Algorithm", "Family", "Feature universe", "Tuning", "Configurations", "Folds", "Total fits", "Compute", "Seed", "Metric", "Preprocessing", "Status", ""].map((heading) => <th scope="col" key={heading} className="border-b border-slate-200 px-3 py-2 uppercase text-slate-500">{heading}</th>)}</tr></thead><tbody>{queue.map((item, index) => { const candidate = summary.modelCatalog.algorithms.find((entry) => entry.id === item.algorithmId); const configurations = estimateConfigurations(candidate ?? null, item.tuningMode, item.gridPreset, JSON.stringify(item.customGrid ?? {}), item.randomIterations ?? 20); const universe = item.featureUniverseId === summary.featureUniverse.featureSetId ? summary.featureUniverse.name : item.featureUniverseId === "CUSTOM_SUBSET" ? "Custom subset" : summary.featureSets.find((entry) => entry.featureSetId === item.featureUniverseId)?.name ?? item.featureUniverseId; return <tr key={`${item.algorithmId}-${index}`}><td className="border-b border-slate-100 px-3 py-2 font-semibold text-slate-900">{candidate?.label ?? item.algorithmId}</td><td className="border-b border-slate-100 px-3 py-2">{human(candidate?.family ?? "")}</td><td className="border-b border-slate-100 px-3 py-2">{universe}</td><td className="border-b border-slate-100 px-3 py-2">{human(item.tuningMode)} · {human(item.gridPreset)}</td><td className="border-b border-slate-100 px-3 py-2 tabular-nums">{int(configurations)}</td><td className="border-b border-slate-100 px-3 py-2">5</td><td className="border-b border-slate-100 px-3 py-2 font-semibold tabular-nums">{int(configurations * 5)}</td><td className="border-b border-slate-100 px-3 py-2"><Pill label={`${candidate?.computeIntensity ?? "UNKNOWN"} compute`} tone={candidate?.computeIntensity === "HIGH" ? "amber" : "slate"} /></td><td className="border-b border-slate-100 px-3 py-2">{item.seed}</td><td className="border-b border-slate-100 px-3 py-2">Log loss</td><td className="border-b border-slate-100 px-3 py-2">Fold-local registered contract</td><td className="border-b border-slate-100 px-3 py-2"><Pill label="Queued for review" tone="slate" /></td><td className="border-b border-slate-100 px-3 py-2"><button type="button" aria-label={`Remove ${candidate?.label ?? item.algorithmId}`} onClick={() => { setQueue((current) => current.filter((_, itemIndex) => itemIndex !== index)); setPlan(null); }} className="rounded p-1 text-slate-500 hover:bg-rose-50 hover:text-rose-700"><Trash2 size={14} /></button></td></tr>; })}</tbody></table></div> : <EmptyQueue />}
        <div className="mt-4 flex flex-wrap items-center gap-3"><button type="button" disabled={!queue.length || planning} onClick={() => void reviewPlan()} className="inline-flex items-center gap-2 rounded-lg border border-cyan-700 bg-white px-4 py-2 text-sm font-semibold text-cyan-800 disabled:border-slate-300 disabled:text-slate-400">{planning ? <Loader2 size={14} className="animate-spin" /> : <ListChecks size={14} />}Review Queue Plan</button>{plan ? <span className="text-xs text-slate-600">{int(plan.totalExperiments)} experiments · {int(plan.totalConfigurations)} configurations · <b>{int(plan.totalFits)} five-fold fits</b></span> : null}</div>
        {plan?.requiresAcknowledgement ? <label className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900"><input type="checkbox" checked={acknowledged} onChange={(event) => { setAcknowledged(event.target.checked); setPlan(null); }} className="mt-0.5" /><span><b>Compute acknowledgement required.</b> I reviewed the exact fit count and understand this queue is intentionally bounded and may take substantial time.</span></label> : null}
        {plan ? <div className={`mt-3 rounded-lg border p-3 text-xs ${plan.executable ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-rose-200 bg-rose-50 text-rose-900"}`}><b>{plan.executable ? "Plan verified." : "Plan held closed."}</b> {plan.executionBlocker ?? "Exact project authority, hyperparameters, fold count, preprocessing scope, seed, and zero-OOT contract are bound into the plan identity."}</div> : null}
        <button type="button" onClick={() => void runQueue()} disabled={!plan?.executable || (plan.requiresAcknowledgement && !acknowledged) || launching || Boolean(activeJobId)} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"><Play size={15} />{activeJobId ? "Project Job Already Active" : launching ? "Starting…" : "Run Experiment Queue"}</button>
        {actionError ? <p role="alert" className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900"><b>Held closed.</b> {actionError}</p> : null}
      </section>

      {currentJob ? <JobProgress job={currentJob} /> : null}

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="model-lab-results">
        <SectionTitle icon={<BarChart3 size={16} />} title="Development leaderboard" description="Complete five-fold candidates rank by mean OOF multiclass log loss. Accuracy is diagnostic; the top row is never auto-promoted or called champion." />
        <DevelopmentLeaderboard runs={runs} />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <AuthorityCard title="Interpretability handoff" icon={<Sparkles size={16} />}><ul className="space-y-2 text-xs leading-5 text-slate-700"><li><b>Tree:</b> native gain/importance plus fold stability; permutation importance in Evaluation.</li><li><b>Linear:</b> coefficients and fold coefficient stability.</li><li><b>Neural:</b> permutation importance; SHAP only after a governed dependency exists.</li><li><b>Selection:</b> native tree importance is never the sole authority. RFE/parsimony happens after model evidence exists.</li></ul></AuthorityCard>
        <AuthorityCard title="Workflow handoff" icon={<ChevronRight size={16} />}><ol className="space-y-2 text-xs leading-5 text-slate-700"><li><b>Now:</b> Model Development Laboratory · algorithm, tuning, queue, execution, preliminary leaderboard.</li><li><b>Next:</b> Evaluation · deep candidate inspection.</li><li><b>Later:</b> feature selection/parsimony, calibration, simulation, game-level evaluation, champion/challenger decision, registry/export.</li></ol></AuthorityCard>
      </section>

      <section className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-[11px] text-slate-600" data-testid="model-lab-authority-footer"><div className="flex flex-wrap items-center gap-2"><Pill label="Current Gold unchanged" tone="emerald" /><Pill label="Final OOT unopened" tone="rose" /><Pill label="Split v2 unchanged" tone="cyan" /><Pill label="No model promotion" tone="slate" /><span className="ml-auto max-w-full truncate font-mono" title={summary.featureUniverse.checksum}>Universe {short(summary.featureUniverse.checksum)}</span></div></section>
    </div>
  );
}

function EligibilitySummary({ summary }: { summary: ProjectModelLabSummary }) {
  const counts = summary.featureUniverse.reconciliation;
  return <div className="mt-3"><div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">{[
    ["Eligible", counts.eligiblePredictorCount], ["Source unavailable", counts.sourceUnavailable], ["Missingness", counts.missingness], ["PIT / leakage", counts.pitLeakage], ["Identity", counts.identity], ["Computation", counts.computationFailure], ["Other governance", counts.other],
  ].map(([label, value]) => <div key={String(label)} className="rounded-lg border border-slate-200 bg-white p-2"><div className="text-[9px] uppercase text-slate-500">{label}</div><div className="mt-1 text-lg font-semibold text-slate-900">{value}</div></div>)}</div><div role="region" aria-label="Excluded predictors" tabIndex={0} className="mt-3 max-h-72 overflow-auto"><table className="w-full min-w-[760px] text-left text-[11px]"><caption className="sr-only">Full Eligible exclusion decisions</caption><thead className="sticky top-0 bg-slate-100"><tr>{["Feature", "Category", "Development missing", "Status", "Reason"].map((heading) => <th scope="col" key={heading} className="border-b border-slate-200 px-2 py-2 uppercase text-slate-500">{heading}</th>)}</tr></thead><tbody>{summary.featureUniverse.exclusions.map((item) => <tr key={item.name}><td className="border-b border-slate-100 px-2 py-2 font-mono">{item.name}</td><td className="border-b border-slate-100 px-2 py-2">{human(item.classification)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{item.missingPercentDevelopment.toFixed(2)}%</td><td className="border-b border-slate-100 px-2 py-2">{human(item.status)}</td><td className="border-b border-slate-100 px-2 py-2 text-slate-600">{item.reason}</td></tr>)}</tbody></table></div></div>;
}

function GridPreview({ algorithm, preset }: { algorithm: ModelAlgorithm; preset: GridPreset }) {
  const grid = preset === "COMPACT" ? algorithm.compactGrid : algorithm.fullGrid;
  return <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-semibold text-slate-800">Inspect {preset === "COMPACT" ? "curated compact configurations" : "full Cartesian domain"}</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-[10px] leading-4 text-slate-700">{JSON.stringify(grid, null, 2)}</pre></details>;
}

function JobProgress({ job }: { job: ModelDevelopmentJob }) {
  const progress = job.progress;
  const ratio = progress.totalFits ? Math.min(100, 100 * (progress.completedFits + progress.failedFits) / progress.totalFits) : 0;
  return <section className="rounded-2xl border border-cyan-200 bg-cyan-50/40 p-4 shadow-sm" data-testid="model-lab-job-progress"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Cpu size={16} className="text-cyan-700" />Persisted experiment progress</div><div className="mt-1 font-mono text-[10px] text-slate-500">{job.jobId}</div></div><Pill label={human(job.status)} tone={job.status === "COMPLETE" ? "emerald" : job.status === "FAILED" ? "rose" : "cyan"} /></div><div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200"><div className="h-full bg-cyan-600 transition-all" style={{ width: `${ratio}%` }} /></div><div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4"><ProgressFact label="Current model" value={progress.currentAlgorithm ? human(progress.currentAlgorithm) : "Waiting"} /><ProgressFact label="Configuration" value={progress.currentConfiguration ? `${progress.currentConfiguration} / ${progress.configurationCount ?? "—"}` : "—"} /><ProgressFact label="Hyperparameters" value={progress.currentHyperparameters ? JSON.stringify(progress.currentHyperparameters) : "—"} /><ProgressFact label="Fold" value={progress.currentFold ? `${progress.currentFold} / ${progress.foldCount ?? 5}` : "—"} /><ProgressFact label="Fits" value={`${int(progress.completedFits)} complete · ${int(progress.failedFits)} failed · ${int(progress.totalFits)} total`} /><ProgressFact label="Elapsed" value={`${Math.round(progress.elapsedSeconds ?? 0)} s`} /><ProgressFact label="Estimated remaining" value={progress.estimatedRemainingSeconds == null ? "Estimating" : `${Math.round(progress.estimatedRemainingSeconds)} s`} /><ProgressFact label="Feature universe" value={progress.currentFeatureUniverse ?? "—"} /><ProgressFact label="Evidence" value={job.artifacts.runReceiptSha256 ? `Receipt ${short(job.artifacts.runReceiptSha256)}` : "Pending immutable receipt"} /></div><p className="mt-3 text-xs text-slate-700">{progress.message}</p>{job.error?.message ? <p role="alert" className="mt-2 text-xs text-rose-800">{job.error.code}: {job.error.message}</p> : null}</section>;
}

function DevelopmentLeaderboard({ runs }: { runs: ModelLabRun[] }) {
  const rows = runs.flatMap((run) => run.candidates.map((candidate) => ({ run, candidate })));
  rows.sort((left, right) => {
    if (left.candidate.meanOofLogLoss == null) return 1;
    if (right.candidate.meanOofLogLoss == null) return -1;
    return left.candidate.meanOofLogLoss - right.candidate.meanOofLogLoss;
  });
  if (!rows.length) return <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center"><FlaskConical className="mx-auto text-slate-400" size={24} /><p className="mt-2 text-sm font-semibold text-slate-800">No development evidence yet</p><p className="mt-1 text-xs text-slate-500">Opening this page performed zero fits.</p></div>;
  return <><div className="mt-3 flex flex-wrap gap-2"><Pill label="INITIAL BASELINE / ABLATION EVIDENCE PRESERVED" tone="cyan" /><Pill label={`${runs.length} immutable run receipts`} tone="slate" /><Pill label="Final OOT accessed: NO" tone="rose" /></div><div role="region" aria-label="Development leaderboard" tabIndex={0} className="mt-3 overflow-x-auto"><table className="w-full min-w-[1520px] text-left text-xs"><caption className="sr-only">Development candidates ranked by mean out-of-fold multiclass log loss</caption><thead><tr>{["Rank", "Development status", "Algorithm", "Feature universe", "Hyperparameters", "Folds", "Mean OOF log loss", "Fold σ", "Summed Brier", "ECE", "Macro-F1", "Accuracy diagnostic", "Rare-class stability", "Complexity", "Runtime", "Immutable run / error"].map((heading) => <th scope="col" key={heading} className="border-b border-slate-200 px-3 py-2 uppercase text-slate-500">{heading}</th>)}</tr></thead><tbody>{rows.map(({ run, candidate }, index) => <LeaderboardRow key={`${run.runId}-${candidate.candidateId}`} run={run} candidate={candidate} rank={candidate.meanOofLogLoss == null ? null : index + 1} leading={candidate.meanOofLogLoss != null && index === 0} />)}</tbody></table></div><p className="mt-3 text-[11px] text-slate-500">The first complete row is the <b>Leading Development Candidate</b>, not a champion. Evaluation, feature selection/parsimony, calibration, final-OOT scoring, registry, and promotion remain separate governed decisions.</p></>;
}

function LeaderboardRow({ run, candidate, rank, leading }: { run: ModelLabRun; candidate: ModelLabCandidateResult; rank: number | null; leading: boolean }) {
  return <tr className={leading ? "bg-cyan-50/70" : ""}><td className="border-b border-slate-100 px-3 py-2 font-semibold">{rank ?? "—"}</td><td className="border-b border-slate-100 px-3 py-2">{leading ? <Pill label="Leading Development Candidate" tone="cyan" /> : <Pill label={candidate.status === "FAILED" ? "Failed · preserved" : "Development evidence"} tone={candidate.status === "FAILED" ? "rose" : "slate"} />}</td><td className="border-b border-slate-100 px-3 py-2 font-semibold text-slate-900">{human(candidate.modelFamily)}</td><td className="border-b border-slate-100 px-3 py-2">{candidate.featureSetName || "Feature-independent null"}</td><td className="max-w-72 truncate border-b border-slate-100 px-3 py-2 font-mono text-[10px]" title={JSON.stringify((candidate as ModelLabCandidateResult & { hyperparameters?: unknown }).hyperparameters ?? {})}>{JSON.stringify((candidate as ModelLabCandidateResult & { hyperparameters?: unknown }).hyperparameters ?? {})}</td><td className="border-b border-slate-100 px-3 py-2">{candidate.foldsCompleted} / 5</td><td className="border-b border-slate-100 px-3 py-2 font-mono font-semibold">{decimal(candidate.meanOofLogLoss)}</td><td className="border-b border-slate-100 px-3 py-2 font-mono">{decimal(candidate.foldStability)}</td><td className="border-b border-slate-100 px-3 py-2 font-mono">{decimal(candidate.summedBrier)}</td><td className="border-b border-slate-100 px-3 py-2 font-mono">{decimal(candidate.ece)}</td><td className="border-b border-slate-100 px-3 py-2 font-mono">{decimal(candidate.macroF1)}</td><td className="border-b border-slate-100 px-3 py-2 font-mono">{decimal(candidate.accuracyDiagnostic)}</td><td className="border-b border-slate-100 px-3 py-2">{candidate.rareClassStability ?? "—"}</td><td className="border-b border-slate-100 px-3 py-2">{candidate.modelComplexity ?? "—"}</td><td className="border-b border-slate-100 px-3 py-2">{duration(candidate.runtimeMs)}</td><td className="border-b border-slate-100 px-3 py-2"><div className="font-mono text-[10px]">{short(run.runId)}</div>{candidate.errorReason ? <div className="mt-1 max-w-96 text-[10px] leading-4 text-rose-700">{candidate.errorReason}</div> : null}</td></tr>;
}

function UniverseButton({ active, onClick, title, detail, status, tone }: { active: boolean; onClick: () => void; title: string; detail: string; status: string; tone: "emerald" | "cyan" | "slate" | "amber" }) { return <button type="button" onClick={onClick} className={`rounded-xl border p-3 text-left ${active ? "border-cyan-500 bg-cyan-50 ring-1 ring-cyan-100" : "border-slate-200 bg-white hover:border-cyan-300"}`}><div className="text-sm font-semibold text-slate-950">{title}</div><div className="mt-1 text-xs text-slate-600">{detail}</div><div className="mt-2"><Pill label={status} tone={tone} /></div></button>; }
function ChoiceButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) { return <button type="button" onClick={onClick} className={`rounded-lg border px-3 py-2 text-xs font-semibold ${active ? "border-cyan-600 bg-cyan-50 text-cyan-900" : "border-slate-200 bg-white text-slate-600"}`}>{children}</button>; }
function JsonEditor({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="mt-3 block text-xs font-semibold text-slate-700">{label}<textarea value={value} onChange={(event) => onChange(event.target.value)} rows={8} spellCheck={false} className="mt-1 w-full rounded-lg border border-slate-300 bg-slate-950 px-3 py-2 font-mono text-[11px] leading-5 text-slate-100" /></label>; }
function EmptyQueue() { return <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center"><ListChecks className="mx-auto text-slate-400" size={24} /><p className="mt-2 text-sm font-semibold text-slate-800">No experiments queued</p><p className="mt-1 text-xs text-slate-500">Configure an algorithm above, inspect its exact fit burden, then add it for review. Nothing launches from a checkbox.</p></div>; }
function ProgressFact({ label, value }: { label: string; value: string }) { return <div className="rounded-lg border border-cyan-100 bg-white p-2"><div className="text-[9px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 truncate font-semibold text-slate-900" title={value}>{value}</div></div>; }
function Loading() { return <section className="grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white" role="status" data-testid="model-lab-loading"><div className="text-center"><Loader2 className="mx-auto animate-spin text-cyan-700" size={24} /><p className="mt-2 text-sm font-semibold text-slate-800">Resolving the full project modeling authority…</p><p className="mt-1 text-xs text-slate-500">No model request is issued while the page loads.</p></div></section>; }
function Failure({ message, retry }: { message: string; retry: () => Promise<void> }) { return <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5" role="alert" data-testid="model-lab-error"><div className="flex items-center gap-2 font-semibold text-rose-900"><AlertTriangle size={17} />Model Development Laboratory held closed</div><p className="mt-2 text-sm leading-6 text-rose-800">{message}</p><button type="button" onClick={() => void retry()} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-rose-900 px-3 py-2 text-xs font-semibold text-white"><RefreshCw size={13} />Retry exact authority</button></section>; }
function BlockingReasons({ blockers }: { blockers: string[] }) { return <section className="rounded-2xl border border-rose-200 bg-rose-50 p-4" role="alert"><div className="flex items-center gap-2 text-sm font-semibold text-rose-900"><AlertTriangle size={16} />Execution remains held closed</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-rose-800">{(blockers.length ? blockers : ["The exact project-bound execution contract is incomplete."]).map((item) => <li key={item}>{item}</li>)}</ul></section>; }
function StatusBadge({ ready }: { ready: boolean }) { return <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase ${ready ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200" : "border-rose-400/40 bg-rose-400/10 text-rose-200"}`}>{ready ? <CheckCircle2 size={12} /> : <Lock size={12} />}{ready ? "Ready for model development" : "Held closed"}</span>; }
function DarkFact({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: "rose" }) { return <div className="min-w-0 bg-slate-950 px-4 py-3 sm:px-5"><div className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">{label}</div><div className={`mt-0.5 truncate font-semibold ${tone === "rose" ? "text-rose-300" : "text-white"}`}>{value}</div><div className="mt-0.5 truncate text-[10px] text-slate-400" title={detail}>{detail}</div></div>; }
function AuthorityCard({ title, icon, children }: { title: string; icon: JSX.Element; children: ReactNode }) { return <section className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><h3 className="flex items-center gap-2 text-sm font-semibold text-slate-950">{icon}{title}</h3><div className="mt-3">{children}</div></section>; }
function AuthorityRows({ rows }: { rows: [string, string, string][] }) { return <dl className="space-y-2">{rows.map(([label, value, identity]) => <div key={label} className="grid min-w-0 gap-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 sm:grid-cols-[86px_minmax(0,1fr)]"><dt className="text-[10px] font-semibold uppercase text-slate-500">{label}</dt><dd className="min-w-0"><div className="truncate text-xs font-semibold text-slate-900">{value}</div><div className="truncate font-mono text-[9px] text-slate-500" title={identity}>{identity}</div></dd></div>)}</dl>; }
function SectionTitle({ icon, title, description }: { icon: JSX.Element; title: string; description: string }) { return <div className="flex items-start gap-2"><span className="mt-0.5 text-cyan-700">{icon}</span><div><h3 className="text-sm font-semibold text-slate-950">{title}</h3><p className="mt-0.5 text-xs leading-5 text-slate-500">{description}</p></div></div>; }
function Pill({ label, tone }: { label: string; tone: "emerald" | "cyan" | "rose" | "amber" | "slate" }) { const style = { emerald: "border-emerald-200 bg-emerald-50 text-emerald-800", cyan: "border-cyan-200 bg-cyan-50 text-cyan-800", rose: "border-rose-200 bg-rose-50 text-rose-800", amber: "border-amber-200 bg-amber-50 text-amber-800", slate: "border-slate-200 bg-slate-50 text-slate-700" }[tone]; return <span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold ${style}`}>{label}</span>; }

import { getCachedUserId } from "../../lib/authSession";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Cpu,
  FlaskConical, Layers3, ListChecks, Loader2, Lock, PauseCircle, Play,
  RefreshCw, Save, ShieldCheck, SlidersHorizontal, Sparkles,
} from "lucide-react";
import {
  cancelUnstartedProjectModelDevelopment,
  enqueueProjectModelDevelopment,
  fetchProjectCandidateEvaluation,
  fetchProjectModelDevelopmentJob,
  fetchProjectModelDevelopmentJobs,
  fetchProjectModelLabSummary,
  planProjectModelDevelopment,
  type ModelAlgorithm,
  type ModelDevelopmentJob,
  type ModelDevelopmentPlan,
  type ModelExperimentDraft,
  type ProjectCandidateEvaluation,
  type ProjectModelLabSummary,
} from "./projectModelLabApi";
import { ProjectCandidateComparison } from "./ProjectCandidateComparison";

type LoadState = "loading" | "ready" | "error";
type GridPreset = "COMPACT" | "FULL" | "CUSTOM";
type TuningMode = "FIXED" | "GRID" | "RANDOM";
type WorkerChoice = "AUTO" | 1 | 2;
type ModelConfig = {
  featureUniverseId: string;
  orderedFeaturesText: string;
  tuningMode: TuningMode;
  gridPreset: GridPreset;
  fixedText: string;
  customGridText: string;
  randomIterations: number;
  expanded: boolean;
};

const RECOMMENDED = [
  "class_frequency_null", "multinomial_logistic", "random_forest", "extra_trees",
  "histogram_gradient_boosting", "xgboost", "lightgbm",
];
const LEGACY_RUNTIME_PARAMETER_OWNERS: Record<string, ReadonlySet<string>> = {
  n_jobs: new Set(["random_forest", "extra_trees", "xgboost", "lightgbm", "knn"]),
  thread_count: new Set(["catboost"]),
};
const int = (value: number) => new Intl.NumberFormat("en-US").format(value);
const human = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const duration = (seconds: number | null | undefined) => seconds == null ? "Estimating…" : seconds < 60 ? `${Math.round(seconds)}s` : `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;

function gridCount(grid: Record<string, unknown[]>): number {
  const values = Object.values(grid);
  if (!values.length || values.some((items) => !Array.isArray(items) || !items.length)) return 0;
  return values.reduce((total, items) => total * items.length, 1);
}

function parseObject<T extends object>(value: string): T | null {
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as T : null;
  } catch { return null; }
}

function withoutLegacyRuntimeParameters<T extends Record<string, unknown>>(
  value: T,
  algorithm: ModelAlgorithm,
  grid: boolean,
): T {
  const allowed = new Set(algorithm.allowedHyperparameters);
  return Object.fromEntries(Object.entries(value).filter(([key, entry]) => {
    const legacyOwners = LEGACY_RUNTIME_PARAMETER_OWNERS[key];
    if (allowed.has(key) || !legacyOwners?.has(algorithm.id)) return true;
    // Model-catalog V1 exposed single-worker execution controls as though they
    // were scientific hyperparameters.  V2 owns those values in the runtime
    // admission contract.  Migrate only the exact legacy representation; an
    // unknown key, another spelling, or a scientist-supplied value such as -1
    // remains visible and is rejected by normal plan validation.
    return grid
      ? !(Array.isArray(entry) && entry.length === 1 && entry[0] === 1)
      : entry !== 1;
  })) as T;
}

function migrateLegacyRuntimeJson(
  value: string,
  algorithm: ModelAlgorithm,
  grid: boolean,
): string {
  const parsed = parseObject<Record<string, unknown>>(value);
  if (!parsed) return value;
  const migrated = withoutLegacyRuntimeParameters(parsed, algorithm, grid);
  return Object.keys(migrated).length === Object.keys(parsed).length
    ? value
    : JSON.stringify(migrated, null, 2);
}

function estimateConfigurations(algorithm: ModelAlgorithm, config: ModelConfig): number {
  if (config.tuningMode === "FIXED") return 1;
  const domain = config.gridPreset === "COMPACT" ? algorithm.compactGrid.length
    : config.gridPreset === "FULL" ? gridCount(algorithm.fullGrid)
      : gridCount(parseObject<Record<string, unknown[]>>(config.customGridText) ?? {});
  return config.tuningMode === "RANDOM" ? Math.min(Math.max(1, config.randomIterations), domain) : domain;
}

function defaultConfig(algorithm: ModelAlgorithm, featureUniverseId: string): ModelConfig {
  return {
    featureUniverseId,
    orderedFeaturesText: "",
    tuningMode: "FIXED",
    gridPreset: algorithm.defaultGridPreset,
    fixedText: JSON.stringify(algorithm.fixedHyperparameters, null, 2),
    customGridText: JSON.stringify(algorithm.fullGrid, null, 2),
    randomIterations: 20,
    expanded: false,
  };
}

function completedReceiptSignature(job: ModelDevelopmentJob | null | undefined): string {
  return (job?.progress.completedCandidateReceipts ?? [])
    .map((receipt) => `${receipt.candidateReceiptSha256}:${receipt.status}`)
    .sort()
    .join("|");
}

function computeGuardReason(algorithm: ModelAlgorithm): string | null {
  const reason = algorithm.computeGuard?.reason;
  if (typeof reason === "string" && reason.trim()) return reason;
  if (algorithm.automaticBundleEligible === false) {
    return "Advanced/manual candidate: review its compute guard and feature universe before adding it.";
  }
  return null;
}

function currentFeatureUniverseId(
  saved: unknown,
  summary: ProjectModelLabSummary,
): string {
  const requested = typeof saved === "string" ? saved : "";
  if (requested === "CUSTOM_SUBSET") return requested;
  if (requested === summary.featureUniverse.featureSetId) return requested;
  if (summary.featureSets.some((item) => item.featureSetId === requested)) return requested;
  // A Full Eligible authority is content-addressed.  When its governed
  // transformation contract changes, a locally saved UI selection must follow
  // the new current authority instead of submitting the superseded checksum as
  // though it were still executable.
  return summary.featureUniverse.featureSetId;
}

export function ProjectBoundModelLab({ projectId, go }: { projectId: string; go?: (id: string) => void }) {
  const [state, setState] = useState<LoadState>("loading");
  const [summary, setSummary] = useState<ProjectModelLabSummary | null>(null);
  const [evaluation, setEvaluation] = useState<ProjectCandidateEvaluation | null>(null);
  const [jobs, setJobs] = useState<ModelDevelopmentJob[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [configs, setConfigs] = useState<Record<string, ModelConfig>>({});
  const [commonFeatureUniverse, setCommonFeatureUniverse] = useState("");
  const [commonOrderedFeaturesText, setCommonOrderedFeaturesText] = useState("");
  const [useCommonFeatureUniverse, setUseCommonFeatureUniverse] = useState(true);
  const [batchName, setBatchName] = useState("Stage 3 multi-model development batch");
  const [workers, setWorkers] = useState<WorkerChoice>("AUTO");
  const [plan, setPlan] = useState<ModelDevelopmentPlan | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [cancelRequesting, setCancelRequesting] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [draftSavedAt, setDraftSavedAt] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const completedReceiptsSignature = useRef("");
  const terminalEvaluationJob = useRef<string | null>(null);
  const storageKey = `asp-stage3-multimodel:v3:${getCachedUserId() ?? "unauthenticated"}:${projectId}`;

  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setState("loading"); setError(null);
    try {
      const next = await fetchProjectModelLabSummary(projectId, controller.signal);
      const [evaluationResult, jobResult] = await Promise.allSettled([
        fetchProjectCandidateEvaluation(projectId, controller.signal),
        fetchProjectModelDevelopmentJobs(projectId, controller.signal),
      ]);
      if (controller.signal.aborted) return;
      setSummary(next);
      const loadedEvaluation = evaluationResult.status === "fulfilled" ? evaluationResult.value : null;
      setEvaluation(loadedEvaluation);
      const jobLedger = jobResult.status === "fulfilled" ? jobResult.value : [];
      setJobs(jobLedger);
      const active = jobLedger.find((job) => ["QUEUED", "RUNNING", "CANCEL_REQUESTED"].includes(job.status));
      setActiveJobId(active?.jobId ?? null);
      // Initialize the receipt signature only when Evaluation accounted for
      // every job pointer. If the parallel reads raced, leave it empty so the
      // first poll performs one recovery fetch rather than silently missing a
      // newly completed receipt.
      const jobReceiptCount = active?.progress.completedCandidateReceipts?.length ?? 0;
      const evaluationReceiptCount = (loadedEvaluation?.incrementalCurrentEvidence?.verifiedCandidateReceipts ?? 0)
        + (loadedEvaluation?.incrementalCurrentEvidence?.heldClosedReceipts ?? 0);
      completedReceiptsSignature.current = evaluationReceiptCount >= jobReceiptCount
        ? completedReceiptSignature(active)
        : "";
      terminalEvaluationJob.current = null;
      const available = next.modelCatalog.algorithms.filter((item) => item.available);
      const saved = window.localStorage.getItem(storageKey);
      let parsed: any = null;
      try { parsed = saved ? JSON.parse(saved) : null; if (parsed?.authorityKey !== next.authority.authorityKey || parsed?.featureChecksum !== next.featureUniverse.checksum || parsed?.splitChecksum !== next.split.checksum) parsed = null; } catch { parsed = null; }
      const initialSelected = new Set<string>(
        Array.isArray(parsed?.selected)
          ? parsed.selected.filter((id: string) => available.some((item) => item.id === id))
          : RECOMMENDED.filter((id) => available.some((item) => item.id === id && item.automaticBundleEligible)),
      );
      const universe = currentFeatureUniverseId(parsed?.commonFeatureUniverse, next);
      const nextConfigs = Object.fromEntries(available.map((algorithm) => {
        const baseline = defaultConfig(algorithm, universe);
        const restored = parsed?.configs?.[algorithm.id];
        if (!restored) return [algorithm.id, baseline];
        const restoredFixedText = typeof restored.fixedText === "string" ? restored.fixedText : baseline.fixedText;
        const restoredGridText = typeof restored.customGridText === "string" ? restored.customGridText : baseline.customGridText;
        return [algorithm.id, {
          ...baseline,
          ...restored,
          fixedText: migrateLegacyRuntimeJson(restoredFixedText, algorithm, false),
          customGridText: migrateLegacyRuntimeJson(restoredGridText, algorithm, true),
          featureUniverseId: currentFeatureUniverseId(restored.featureUniverseId, next),
          expanded: false,
        }];
      }));
      setSelected(initialSelected);
      setCommonFeatureUniverse(universe);
      setCommonOrderedFeaturesText(typeof parsed?.commonOrderedFeaturesText === "string" ? parsed.commonOrderedFeaturesText : "");
      setUseCommonFeatureUniverse(parsed?.useCommonFeatureUniverse !== false);
      setBatchName(typeof parsed?.batchName === "string" ? parsed.batchName : "Stage 3 multi-model development batch");
      setWorkers([1, 2].includes(parsed?.workers) ? parsed.workers : "AUTO");
      setConfigs(nextConfigs);
      setState("ready");
    } catch (caught) {
      if (controller.signal.aborted) return;
      setState("error");
      setError(caught instanceof Error ? caught.message : "The exact project-bound Model Laboratory could not be loaded.");
    }
  }, [projectId, storageKey]);

  useEffect(() => { void load(); return () => request.current?.abort(); }, [load]);
  useEffect(() => {
    if (!summary || state !== "ready") return;
    window.localStorage.setItem(storageKey, JSON.stringify({ authorityKey: summary?.authority.authorityKey, featureChecksum: summary?.featureUniverse.checksum, splitChecksum: summary?.split.checksum, selected: [...selected], configs, commonFeatureUniverse, commonOrderedFeaturesText, useCommonFeatureUniverse, batchName, workers }));
  }, [batchName, commonFeatureUniverse, commonOrderedFeaturesText, configs, selected, state, storageKey, summary, useCommonFeatureUniverse, workers]);
  useEffect(() => { setPlan(null); setAcknowledged(false); }, [batchName, commonFeatureUniverse, commonOrderedFeaturesText, configs, selected, useCommonFeatureUniverse, workers]);

  useEffect(() => {
    if (!activeJobId) return undefined;
    let disposed = false;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const job = await fetchProjectModelDevelopmentJob(projectId, activeJobId);
        if (disposed) return;
        setJobs((current) => [job, ...current.filter((item) => item.jobId !== job.jobId)]);
        const nextReceiptSignature = completedReceiptSignature(job);
        const terminal = !["QUEUED", "RUNNING", "CANCEL_REQUESTED"].includes(job.status);
        if (!terminal && nextReceiptSignature !== completedReceiptsSignature.current) {
          const nextEvaluation = await fetchProjectCandidateEvaluation(projectId);
          if (disposed) return;
          setEvaluation(nextEvaluation);
          completedReceiptsSignature.current = nextReceiptSignature;
        }
        if (terminal && terminalEvaluationJob.current !== job.jobId) {
          const nextEvaluation = await fetchProjectCandidateEvaluation(projectId);
          if (disposed) return;
          setEvaluation(nextEvaluation);
          completedReceiptsSignature.current = nextReceiptSignature;
          terminalEvaluationJob.current = job.jobId;
          setActiveJobId(null);
        }
        if (!disposed) setActionError(null);
      } catch (caught) {
        if (!disposed) setActionError(caught instanceof Error ? caught.message : "Batch progress could not be refreshed.");
      } finally {
        polling = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2_000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [activeJobId, projectId]);

  const algorithms = summary?.modelCatalog.algorithms ?? [];
  const selectedAlgorithms = algorithms.filter((algorithm) => selected.has(algorithm.id));
  const configurationCount = selectedAlgorithms.reduce((total, algorithm) => total + estimateConfigurations(algorithm, configs[algorithm.id] ?? defaultConfig(algorithm, commonFeatureUniverse)), 0);
  const fitCount = configurationCount * (summary?.split.foldCount ?? 5);
  const computeClass = selectedAlgorithms.some((item) => item.computeIntensity === "VERY_HIGH") ? "VERY HIGH" : selectedAlgorithms.some((item) => item.computeIntensity === "HIGH") ? "HIGH" : selectedAlgorithms.some((item) => item.computeIntensity === "MEDIUM") ? "MEDIUM" : "LOW";
  const currentJob = jobs.find((job) => job.jobId === activeJobId) ?? jobs[0] ?? null;

  const updateConfig = (algorithmId: string, changes: Partial<ModelConfig>) => setConfigs((current) => ({ ...current, [algorithmId]: { ...current[algorithmId], ...changes } }));
  const selectIds = (ids: string[]) => setSelected((current) => new Set([...current, ...ids.filter((id) => algorithms.some((algorithm) => algorithm.id === id && algorithm.available))]));
  const clearIds = (ids: string[]) => setSelected((current) => { const next = new Set(current); ids.forEach((id) => next.delete(id)); return next; });
  const saveDraft = () => {
    window.localStorage.setItem(storageKey, JSON.stringify({ authorityKey: summary?.authority.authorityKey, featureChecksum: summary?.featureUniverse.checksum, splitChecksum: summary?.split.checksum, selected: [...selected], configs, commonFeatureUniverse, commonOrderedFeaturesText, useCommonFeatureUniverse, batchName, workers }));
    setDraftSavedAt(new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }));
    setActionError(null);
  };

  const experiments = (): ModelExperimentDraft[] | null => {
    if (!summary) return null;
    const output: ModelExperimentDraft[] = [];
    for (const algorithm of selectedAlgorithms) {
      const config = configs[algorithm.id] ?? defaultConfig(algorithm, commonFeatureUniverse);
      const featureUniverseId = useCommonFeatureUniverse ? commonFeatureUniverse : config.featureUniverseId;
      const orderedFeatures = (useCommonFeatureUniverse ? commonOrderedFeaturesText : config.orderedFeaturesText).split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
      const fixedInput = parseObject<Record<string, unknown>>(config.fixedText);
      const customInput = parseObject<Record<string, unknown[]>>(config.customGridText);
      if (config.tuningMode === "FIXED" && !fixedInput) { setActionError(`${algorithm.label}: fixed hyperparameters are not valid JSON.`); return null; }
      if (config.gridPreset === "CUSTOM" && !customInput) { setActionError(`${algorithm.label}: custom grid is not valid JSON.`); return null; }
      if (featureUniverseId === "CUSTOM_SUBSET" && algorithm.id !== "class_frequency_null" && !orderedFeatures.length) { setActionError(`${algorithm.label}: Custom Eligible Subset requires at least one ordered predictor.`); return null; }
      const fixed = fixedInput ? withoutLegacyRuntimeParameters(fixedInput, algorithm, false) : null;
      const custom = customInput ? withoutLegacyRuntimeParameters(customInput, algorithm, true) : null;
      output.push({ algorithmId: algorithm.id, featureUniverseId, orderedFeatures: featureUniverseId === "CUSTOM_SUBSET" ? orderedFeatures : undefined, tuningMode: algorithm.id === "class_frequency_null" ? "FIXED" : config.tuningMode, gridPreset: config.gridPreset, fixedHyperparameters: fixed ?? undefined, customGrid: config.gridPreset === "CUSTOM" ? custom ?? undefined : undefined, randomIterations: config.tuningMode === "RANDOM" ? config.randomIterations : undefined, seed: 20260901 });
    }
    return output;
  };

  const reviewPlan = async () => {
    if (!summary || !selectedAlgorithms.length || planning) return;
    const matrix = experiments(); if (!matrix) return;
    setPlanning(true); setActionError(null);
    try { setPlan(await planProjectModelDevelopment(projectId, summary, matrix, acknowledged, undefined, { parallelWorkers: workers, batchName })); }
    catch (caught) { setPlan(null); setActionError(caught instanceof Error ? caught.message : "The batch plan failed closed."); }
    finally { setPlanning(false); }
  };

  const runBatch = async () => {
    if (!summary || !plan?.executable || launching || activeJobId) return;
    const matrix = experiments(); if (!matrix) return;
    setLaunching(true); setActionError(null);
    try {
      const job = await enqueueProjectModelDevelopment(projectId, summary, matrix, acknowledged, plan, undefined, { parallelWorkers: workers, batchName });
      setJobs((current) => [job, ...current.filter((item) => item.jobId !== job.jobId)]);
      completedReceiptsSignature.current = "";
      terminalEvaluationJob.current = null;
      setActiveJobId(job.jobId);
    } catch (caught) { setActionError(caught instanceof Error ? caught.message : "The project-scoped batch failed to start."); }
    finally { setLaunching(false); }
  };

  const cancelUnstarted = async () => {
    if (!activeJobId || cancelRequesting) return;
    setCancelRequesting(true); setActionError(null);
    try { const job = await cancelUnstartedProjectModelDevelopment(projectId, activeJobId); setJobs((current) => [job, ...current.filter((item) => item.jobId !== job.jobId)]); }
    catch (caught) { setActionError(caught instanceof Error ? caught.message : "The cancel-unstarted request failed closed."); }
    finally { setCancelRequesting(false); }
  };

  if (state === "loading") return <Loading />;
  if (state === "error" || !summary) return <Failure message={error || "Project authority unavailable."} retry={load} />;
  const featureChoices = [{ id: summary.featureUniverse.featureSetId, label: `Full Eligible — ${summary.featureUniverse.featureCount} predictors`, executable: true }, ...summary.featureSets.map((item) => ({ id: item.featureSetId, label: `${item.name} — ${item.featureCount} predictors`, executable: item.executable !== false })), { id: "CUSTOM_SUBSET", label: "Custom Eligible Subset — exact ordered predictors", executable: true }];
  const incrementalEvidence = evaluation?.incrementalCurrentEvidence;

  return <div className="min-w-0 space-y-4" data-testid="stage3-project-bound-model-laboratory">
    <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white"><div className="grid gap-px bg-slate-800 lg:grid-cols-[minmax(0,1.5fr)_repeat(4,minmax(130px,0.6fr))]"><div className="bg-slate-950 p-5"><div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-300"><FlaskConical size={14} /> Step 9 · Model Development Laboratory</div><h2 className="mt-2 text-xl font-semibold">Design one governed multi-model comparison batch</h2><p className="mt-1 text-xs leading-5 text-slate-300">Select algorithms together, configure exact per-model experiments, then explicitly review and launch. Opening this page performs zero fits.</p></div><DarkFact label="Development" value={`${int(summary.population.developmentRows)} rows`} detail={`${summary.population.startDate} → ${summary.population.endDate}`} /><DarkFact label="Feature authority" value={`${summary.featureUniverse.featureCount} eligible`} detail={`${summary.featureUniverse.reconciliation.excludedPredictorCount} governed exclusions`} /><DarkFact label="Selection" value={`${selected.size} algorithms`} detail={`${int(configurationCount)} configurations · ${int(fitCount)} fits`} /><DarkFact label="Final OOT" value={`${int(summary.population.finalOotRows)} locked`} detail="No training, tuning, calibration, or selection access" tone="rose" /></div></section>
    {(useCommonFeatureUniverse ? commonFeatureUniverse === "CUSTOM_SUBSET" : selectedAlgorithms.some((algorithm) => (configs[algorithm.id]?.featureUniverseId ?? commonFeatureUniverse) === "CUSTOM_SUBSET")) ? <section className="rounded-2xl border border-violet-200 bg-violet-50 p-4 shadow-sm" data-testid="custom-eligible-subset-editor"><SectionTitle icon={<ListChecks size={16} />} title="Custom Eligible Subset" description="Enter exact eligible predictor names in modeling order, one per line or comma-separated. The backend rejects duplicates, identifiers, targets, ineligible fields, and empty subsets." />{useCommonFeatureUniverse ? <textarea value={commonOrderedFeaturesText} onChange={(event) => setCommonOrderedFeaturesText(event.target.value)} rows={7} spellCheck={false} className="mt-3 w-full rounded-lg border border-violet-300 bg-white px-3 py-2 font-mono text-[10px] leading-5 text-slate-900" placeholder={summary.featureUniverse.orderedFeatures.slice(0, 5).join("\n")} /> : <div className="mt-3 grid gap-3 lg:grid-cols-2">{selectedAlgorithms.filter((algorithm) => configs[algorithm.id]?.featureUniverseId === "CUSTOM_SUBSET").map((algorithm) => <label key={algorithm.id} className="text-[10px] font-semibold uppercase text-violet-900">{algorithm.label}<textarea value={configs[algorithm.id]?.orderedFeaturesText ?? ""} onChange={(event) => updateConfig(algorithm.id, { orderedFeaturesText: event.target.value })} rows={6} spellCheck={false} className="mt-1 w-full rounded-lg border border-violet-300 bg-white px-3 py-2 font-mono text-[10px] leading-5 normal-case text-slate-900" placeholder="One exact eligible predictor per line" /></label>)}</div>}<p className="mt-2 text-[10px] text-violet-800">This creates a run-scoped content-addressed feature authority. It does not mutate or duplicate a saved governed set.</p></section> : null}
    {!summary.readiness.ready ? <BlockingReasons blockers={summary.readiness.blockers} /> : null}

    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="multi-model-selection"><SectionTitle icon={<Layers3 size={16} />} title="1 · Select multiple algorithms" description="Safe bundles include only automatically eligible models. Advanced/manual algorithms stay visible and require an explicit choice after their compute guard is reviewed." /><div className="mt-3 flex flex-wrap gap-2"><Action onClick={() => selectIds(algorithms.filter((item) => item.available && item.automaticBundleEligible).map((item) => item.id))}>Select all resource-safe models</Action><Action onClick={() => setSelected(new Set())}>Clear all · remove selected experiments</Action><Action onClick={() => selectIds(RECOMMENDED.filter((id) => algorithms.some((item) => item.id === id && item.available && item.automaticBundleEligible)))}>Select recommended baseline bundle</Action><span className="self-center rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-cyan-900">{selected.size} selected · {int(configurationCount)} configs · {int(fitCount)} fits · {computeClass} compute</span></div><div className="mt-4 space-y-4">{summary.modelCatalog.families.map((family) => { const members = family.algorithms.map((id) => algorithms.find((item) => item.id === id)).filter((item): item is ModelAlgorithm => Boolean(item)); const safeIds = members.filter((item) => item.available && item.automaticBundleEligible).map((item) => item.id); const ids = members.map((item) => item.id); return <div key={family.id}><div className="mb-2 flex flex-wrap items-center gap-2"><h3 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">{family.label}</h3><button type="button" onClick={() => selectIds(safeIds)} className="text-[10px] font-semibold text-cyan-700">Select resource-safe family</button><span className="text-slate-300">·</span><button type="button" onClick={() => clearIds(ids)} className="text-[10px] font-semibold text-slate-500">Clear family</button></div><div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">{members.map((algorithm) => { const guard = computeGuardReason(algorithm); return <label key={algorithm.id} className={`relative rounded-xl border p-3 ${!algorithm.available ? "cursor-not-allowed border-slate-200 bg-slate-50 opacity-70" : selected.has(algorithm.id) ? "border-cyan-500 bg-cyan-50 ring-1 ring-cyan-100" : "border-slate-200 bg-white hover:border-cyan-300"}`}><input type="checkbox" disabled={!algorithm.available} checked={selected.has(algorithm.id)} onChange={(event) => setSelected((current) => { const next = new Set(current); if (event.target.checked) next.add(algorithm.id); else next.delete(algorithm.id); return next; })} className="absolute right-3 top-3 h-4 w-4 rounded border-slate-300 text-cyan-700" /><div className="pr-6 text-xs font-semibold text-slate-950">{algorithm.label}</div><div className="mt-1 text-[9px] font-semibold uppercase text-slate-500">{algorithm.computeIntensity} compute · {algorithm.available ? algorithm.automaticBundleEligible ? "resource-safe bundle" : "advanced/manual" : human(algorithm.status)}</div>{algorithm.unavailableReason ? <p className="mt-2 text-[10px] leading-4 text-amber-800">{algorithm.unavailableReason}</p> : guard ? <p className="mt-2 text-[10px] leading-4 text-amber-800">{guard}</p> : null}</label>; })}</div></div>; })}</div></section>

    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="multi-model-feature-universe"><SectionTitle icon={<ShieldCheck size={16} />} title="2 · Common and per-model feature authority" description="Full Eligible is the default. Only explicitly selected algorithm/universe combinations enter the batch; no Cartesian product is inferred." /><label className="mt-3 flex items-center gap-2 text-xs font-semibold text-slate-800"><input type="checkbox" checked={useCommonFeatureUniverse} onChange={(event) => setUseCommonFeatureUniverse(event.target.checked)} /> Use this feature universe for all selected models</label><select value={commonFeatureUniverse} onChange={(event) => setCommonFeatureUniverse(event.target.value)} className="mt-2 w-full max-w-xl rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs">{featureChoices.map((choice) => <option key={choice.id} value={choice.id} disabled={!choice.executable}>{choice.label}{choice.executable ? "" : " — NON-EXECUTABLE"}</option>)}</select><div className="mt-3 flex flex-wrap gap-2"><Pill label="Full Eligible recommended" tone="emerald" /><Pill label="Core Gold 48 benchmark" tone="cyan" /><Pill label="Rest/Travel preserved but held closed" tone="rose" /><Pill label="Unavailable fields never zero-filled" tone="slate" /></div></section>

    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="selected-model-configuration"><SectionTitle icon={<SlidersHorizontal size={16} />} title="3 · Configure selected models" description="One compact card per selected algorithm preserves its own universe, tuning strategy, grid, seed, and five-fold burden." />{!selectedAlgorithms.length ? <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-500">Select one or more available algorithms above. Nothing will launch automatically.</div> : <div className="mt-3 space-y-2">{selectedAlgorithms.map((algorithm) => { const config = configs[algorithm.id] ?? defaultConfig(algorithm, commonFeatureUniverse); const count = estimateConfigurations(algorithm, config); return <div key={algorithm.id} className="rounded-xl border border-slate-200 bg-slate-50"><button type="button" onClick={() => updateConfig(algorithm.id, { expanded: !config.expanded })} className="flex w-full items-center gap-3 p-3 text-left"><span className="text-cyan-700">{config.expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span><span className="min-w-0 flex-1"><b className="block truncate text-xs text-slate-950">{algorithm.label}</b><span className="block truncate text-[10px] text-slate-500">{human(config.tuningMode)} · {human(config.gridPreset)} · {count} configurations · {count * 5} fits · seed 20260901</span></span><Pill label={`${algorithm.computeIntensity} compute`} tone={algorithm.computeIntensity.includes("HIGH") ? "amber" : "slate"} /></button>{config.expanded ? <div className="grid gap-4 border-t border-slate-200 bg-white p-4 lg:grid-cols-[220px_minmax(0,1fr)]"><div className="space-y-3">{!useCommonFeatureUniverse ? <label className="block text-[10px] font-semibold uppercase text-slate-500">Feature universe<select value={config.featureUniverseId} onChange={(event) => updateConfig(algorithm.id, { featureUniverseId: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2 text-xs normal-case text-slate-800">{featureChoices.map((choice) => <option key={choice.id} value={choice.id} disabled={!choice.executable}>{choice.label}</option>)}</select></label> : <div className="rounded-lg border border-cyan-100 bg-cyan-50 p-2 text-[10px] text-cyan-900">Common feature authority applied.</div>}<label className="block text-[10px] font-semibold uppercase text-slate-500">Tuning mode<select value={config.tuningMode} disabled={algorithm.id === "class_frequency_null"} onChange={(event) => updateConfig(algorithm.id, { tuningMode: event.target.value as TuningMode })} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2 text-xs normal-case text-slate-800">{algorithm.supportedTuningModes.map((mode) => <option key={mode}>{mode}</option>)}</select></label>{config.tuningMode !== "FIXED" ? <label className="block text-[10px] font-semibold uppercase text-slate-500">Grid preset<select value={config.gridPreset} onChange={(event) => updateConfig(algorithm.id, { gridPreset: event.target.value as GridPreset })} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2 text-xs normal-case text-slate-800"><option value="COMPACT">Compact Grid</option><option value="FULL">Full Grid</option><option value="CUSTOM">Custom Grid</option></select></label> : null}{config.tuningMode === "RANDOM" ? <label className="block text-[10px] font-semibold uppercase text-slate-500">Random configurations<input type="number" min={1} value={config.randomIterations} onChange={(event) => updateConfig(algorithm.id, { randomIterations: Math.max(1, Number(event.target.value) || 1) })} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2 text-xs normal-case" /></label> : null}</div><label className="block text-[10px] font-semibold uppercase text-slate-500">{config.tuningMode === "FIXED" ? "Fixed hyperparameters" : config.gridPreset === "CUSTOM" ? "Custom parameter grid" : `${config.gridPreset} authoritative preview`}<textarea value={config.tuningMode === "FIXED" ? config.fixedText : config.gridPreset === "CUSTOM" ? config.customGridText : JSON.stringify(config.gridPreset === "COMPACT" ? algorithm.compactGrid : algorithm.fullGrid, null, 2)} readOnly={config.tuningMode !== "FIXED" && config.gridPreset !== "CUSTOM"} onChange={(event) => updateConfig(algorithm.id, config.tuningMode === "FIXED" ? { fixedText: event.target.value } : { customGridText: event.target.value })} rows={8} spellCheck={false} className="mt-1 w-full rounded-lg border border-slate-300 bg-slate-950 px-3 py-2 font-mono text-[10px] leading-5 text-slate-100" /></label></div> : null}</div>; })}</div>}</section>

    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="experiment-batch-plan"><SectionTitle icon={<ListChecks size={16} />} title="4 · Immutable experiment-batch plan" description="The batch binds project, Gold, ordered features, target order, split, treatment policies, exact configurations, environment, seed, creator, zero-OOT status, and a canonical checksum." /><div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_240px]"><div><label className="block text-[10px] font-semibold uppercase text-slate-500">Batch name<input value={batchName} onChange={(event) => setBatchName(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs normal-case text-slate-800" /></label><div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4"><Fact label="Algorithms" value={String(selected.size)} /><Fact label="Configurations" value={int(configurationCount)} /><Fact label="Five-fold fits" value={int(fitCount)} /><Fact label="Compute class" value={computeClass} /></div></div><label className="block rounded-xl border border-slate-800 bg-slate-950 p-3 text-[10px] font-semibold uppercase text-slate-400">Parallel candidate workers<select value={workers} onChange={(event) => setWorkers(event.target.value === "AUTO" ? "AUTO" : Number(event.target.value) as 1 | 2)} className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-xs normal-case text-white"><option value="AUTO">Auto (resource-aware)</option><option value="1">1 worker</option><option value="2">2 workers if safe</option></select><span className="mt-2 block normal-case font-normal leading-4 text-slate-400">High-memory candidates run exclusively. Compatible native-parallel estimators receive a bounded CPU budget without nested oversubscription.</span></label></div><div className="mt-4 flex flex-wrap items-center gap-3"><button type="button" onClick={() => void reviewPlan()} disabled={!selected.size || planning} className="inline-flex items-center gap-2 rounded-lg border border-cyan-700 px-4 py-2 text-sm font-semibold text-cyan-800 disabled:border-slate-300 disabled:text-slate-400">{planning ? <Loader2 size={14} className="animate-spin" /> : <ListChecks size={14} />} Review exact batch plan</button><button type="button" onClick={saveDraft} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700"><Save size={14} />Save Draft Batch</button><button type="button" onClick={() => { setSelected(new Set()); setPlan(null); }} disabled={Boolean(activeJobId)} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 disabled:text-slate-300">Clear draft selections</button>{draftSavedAt ? <span className="text-xs text-emerald-700">Draft saved {draftSavedAt}</span> : null}{plan ? <span className="text-xs text-slate-600"><b>{plan.totalExperiments} models · {plan.totalConfigurations} configurations · {plan.totalFits} five-fold fits</b> · up to {plan.parallelism.effectiveCandidateWorkers} candidate worker(s) planned · up to {plan.parallelism.maximumEstimatorNativeWorkers} native CPU worker(s) · {human(plan.parallelism.schedulingPolicy)}</span> : null}</div>{plan?.requiresAcknowledgement ? <label className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} className="mt-0.5" /><span><b>Compute acknowledgement required.</b> I reviewed the exact workload, worker limit, and five chronological folds.</span></label> : null}{plan ? <div className={`mt-3 rounded-xl border p-3 text-xs ${plan.executable ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-rose-200 bg-rose-50 text-rose-900"}`}><b>{plan.executable ? "Batch plan verified." : "Batch held closed."}</b> {plan.executionBlocker ?? `Plan ${plan.planId} · checksum ${plan.checksum}`}</div> : null}<button type="button" onClick={() => void runBatch()} disabled={!plan?.executable || (plan.requiresAcknowledgement && !acknowledged) || launching || Boolean(activeJobId)} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"><Play size={15} />{activeJobId ? "One project batch is already active" : launching ? "Starting governed batch…" : `Run ${plan?.totalExperiments ?? selected.size} selected models · ${plan?.totalConfigurations ?? configurationCount} configurations · ${plan?.totalFits ?? fitCount} five-fold fits`}</button>{actionError ? <p role="alert" className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900"><b>Held closed.</b> {actionError}</p> : null}</section>
    {currentJob ? <BatchProgress job={currentJob} onCancel={activeJobId ? cancelUnstarted : undefined} cancelRequesting={cancelRequesting} /> : null}
    <section className="rounded-2xl border border-cyan-200 bg-cyan-50 p-4" data-testid="historical-evidence-banner"><div className="flex gap-2 text-sm font-semibold text-cyan-950"><Sparkles size={16} />Evidence loaded without model activity</div><p className="mt-1 text-xs leading-5 text-cyan-900">{evaluation?.historicalEvidence.banner ?? "No experiment was started by opening this page. Verified immutable receipts are shown when available."}</p><div className="mt-2 flex flex-wrap gap-2"><Pill label={`${evaluation?.activity.historicalRunReceipts ?? summary.historicalEvidence.runCount} historical receipts preserved`} tone="cyan" /><Pill label={`${evaluation?.activity.newFitsOnPageLoad ?? 0} fits on page load`} tone="emerald" /><Pill label="Rest/Travel failures retained" tone="rose" /></div></section>
    {evaluation ? <>
      {incrementalEvidence && (incrementalEvidence.candidateGroups.length > 0 || (incrementalEvidence.heldClosedReceipts ?? 0) > 0) ? <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4 shadow-sm" data-testid="incremental-current-evidence"><h3 className="text-sm font-semibold text-amber-950">Completed configurations so far — interim evidence</h3><p className="mt-1 text-xs leading-5 text-amber-900">Each displayed row is backed by a complete immutable candidate receipt, but the batch has not written its terminal receipt. Interim results are not final-ranked and cannot be selected as finalists; ranks may change as other configurations finish.</p><div className="mt-2 flex flex-wrap gap-2"><Pill label={`${incrementalEvidence.verifiedCandidateReceipts ?? incrementalEvidence.candidateGroups.length} verified interim receipt(s)`} tone="amber" />{(incrementalEvidence.heldClosedReceipts ?? 0) > 0 ? <Pill label={`${incrementalEvidence.heldClosedReceipts} receipt(s) held closed`} tone="rose" /> : null}</div>{incrementalEvidence.candidateGroups.length ? <div className="mt-3"><ProjectCandidateComparison groups={incrementalEvidence.candidateGroups} title="Interim complete configurations · not selection eligible" source="ALL" /></div> : null}{incrementalEvidence.diagnostics?.length ? <div role="alert" className="mt-3 rounded-lg border border-rose-200 bg-white p-3 text-xs text-rose-900"><b>Interim receipts held closed.</b><ul className="mt-2 list-disc space-y-1 pl-5">{incrementalEvidence.diagnostics.map((diagnostic, index) => <li key={`${diagnostic.code}-${diagnostic.candidateReceiptSha256 ?? index}`}><span className="font-mono">{diagnostic.code}</span>: {diagnostic.message}</li>)}</ul></div> : null}</section> : null}
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="current-batch-evidence"><h3 className="text-sm font-semibold text-slate-950">A · Terminal current project batch</h3><p className="mt-1 text-xs text-slate-500">Only a terminal batch receipt enters this section; it never overwrites historical receipts.</p>{evaluation.currentBatches.length ? <div className="mt-3"><ProjectCandidateComparison groups={evaluation.currentBatches} title="Terminal current batch · grouped scientific candidates" source="CURRENT_BATCH" /></div> : <p className="mt-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-xs text-slate-600">No terminal current batch is available. Complete configurations from an active batch appear separately as interim evidence; opening this page created zero fits.</p>}</section>
      <details open={!evaluation.currentBatches.length && !evaluation.incrementalCurrentEvidence?.candidateGroups.length} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="historical-baseline-evidence"><summary className="cursor-pointer text-sm font-semibold text-slate-950">B · Historical verified baselines · {evaluation.historicalEvidence.candidates.length} grouped candidates</summary><p className="mt-1 text-xs text-slate-500">Immutable V1 receipts are grouped by scientific fingerprint. Attempt history remains expandable and unchanged.</p><div className="mt-3"><ProjectCandidateComparison groups={evaluation.historicalEvidence.candidates} title="Historical baselines · grouped scientific candidates" source="HISTORICAL_BASELINE" /></div></details>
    </> : <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><b>Grouped Evaluation evidence is temporarily unavailable.</b> Model planning remains usable; reload after the backend is restarted on this build.</section>}
    <section className="grid gap-4 lg:grid-cols-2"><Info title="Safe execution contract"><li>One active batch per project with an interprocess project lock.</li><li>Resource-safe defaults use one fixed configuration per selected algorithm.</li><li>Families are dispatched fairly instead of exhausting adjacent configurations from one family first.</li><li>High-memory candidates run exclusively; compatible estimators receive a bounded native CPU budget.</li><li>Completed candidate receipts appear immediately as interim evidence; only a terminal batch is selection-eligible.</li><li>Cancel affects queued/unstarted work only and never deletes evidence.</li></Info><Info title="Workflow handoff"><li>Terminal completed candidates automatically appear in Candidate Evaluation.</li><li>Evaluation can designate multiple finalists—not a champion.</li><li>Model Refinement receives finalists for leakage-safe parsimony plans.</li><li>Final OOT remains locked until all later modeling decisions are frozen.</li><li className="list-none"><button type="button" onClick={() => go?.("evaluation")} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-cyan-700 px-3 py-2 text-xs font-semibold text-white">Continue to Candidate Evaluation <ChevronRight size={13} /></button></li></Info></section>
  </div>;
}

function BatchProgress({ job, onCancel, cancelRequesting = false }: { job: ModelDevelopmentJob; onCancel?: () => Promise<void>; cancelRequesting?: boolean }) {
  const progress = job.progress;
  const reportedCancelledFits = progress.cancelledFits;
  const cancelledFits = reportedCancelledFits ?? 0;
  const resolvedFits = progress.completedFits + progress.failedFits + cancelledFits;
  const percent = progress.totalFits
    ? Math.min(100, (resolvedFits / progress.totalFits) * 100)
    : 0;
  const cancelling = job.status === "CANCEL_REQUESTED";
  const cancelledTerminal = ["CANCELLED", "CANCELLED_PARTIAL"].includes(job.status);
  const failedTerminal = job.status === "FAILED";
  const interruptedTerminal = job.status === "INTERRUPTED";
  const stoppedTerminal = failedTerminal || interruptedTerminal;
  const completedTerminal = ["COMPLETE", "PARTIAL"].includes(job.status);
  const sectionTone = stoppedTerminal
    ? "border-rose-300 bg-rose-50"
    : cancelling || cancelledTerminal
      ? "border-amber-300 bg-amber-50"
      : "border-cyan-200 bg-cyan-50";
  const ordinaryRemaining = progress.remainingFits
    ?? Math.max(0, progress.totalFits - progress.completedFits - progress.failedFits - cancelledFits);
  const terminalUnfinishedParts = [
    progress.unstartedFits == null ? null : `${progress.unstartedFits} unstarted`,
    progress.unresolvedFits == null ? null : `${progress.unresolvedFits} unresolved`,
    progress.interruptedCandidates == null ? null : `${progress.interruptedCandidates.length} interrupted candidate(s)`,
  ].filter((item): item is string => Boolean(item));
  const terminalUnfinishedValue = terminalUnfinishedParts.length
    ? terminalUnfinishedParts.join(" · ")
    : cancelledTerminal && reportedCancelledFits != null
      ? `${reportedCancelledFits} cancelled before execution`
    : "Not reported";
  const remainingValue = cancelling
    ? `${progress.cancellationPendingFits ?? progress.pendingFits ?? ordinaryRemaining} queued held · ${progress.drainingActiveCandidates ?? progress.activeCandidates?.length ?? 0} active draining`
    : String(ordinaryRemaining);
  const runtimeAdmission = progress.runtimeAdmission;
  const admittedWorkersValue = runtimeAdmission
    ? `${runtimeAdmission.effectiveCandidateWorkers} admitted · up to ${runtimeAdmission.plannedCandidateWorkers} planned`
    : job.status === "QUEUED"
      ? `Up to ${job.plan.parallelism?.effectiveCandidateWorkers ?? 1} planned`
      : "Admission not reported";
  const etaValue = cancelling ? "Waiting for active fits"
    : cancelledTerminal ? "Cancelled"
      : stoppedTerminal ? "Stopped"
        : completedTerminal ? "Complete"
          : progress.estimatedRemainingSeconds == null || (ordinaryRemaining > 0 && progress.estimatedRemainingSeconds <= 0)
            ? "Estimating…"
            : duration(progress.estimatedRemainingSeconds);
  return <section className={`rounded-2xl border p-4 shadow-sm ${sectionTone}`} data-testid="model-development-progress">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Cpu size={16} />{job.plan.batchName ?? "Model development batch"}</div><div className="mt-1 font-mono text-[10px] text-slate-600">{job.jobId} · {job.status}</div></div>{onCancel && ["QUEUED", "RUNNING", "CANCEL_REQUESTED"].includes(job.status) ? <button type="button" onClick={() => void onCancel()} disabled={cancelling || cancelRequesting} className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-semibold text-amber-900 disabled:opacity-60"><PauseCircle size={14} />{cancelling ? "Cancellation recorded · active fits draining" : cancelRequesting ? "Recording cancellation…" : "Cancel unstarted configurations"}</button> : null}</div>
    <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/70"><div className={`h-full ${cancelledTerminal || cancelling ? "bg-amber-500" : stoppedTerminal ? "bg-rose-600" : "bg-cyan-600"}`} style={{ width: `${percent}%` }} /></div>
    <div className="mt-3 grid gap-2 sm:grid-cols-3 lg:grid-cols-8"><Fact label="Completed configs" value={progress.completedConfigurations == null ? "—" : String(progress.completedConfigurations)} /><Fact label="Completed fits" value={`${progress.completedFits}/${progress.totalFits}`} /><Fact label="Failed fits" value={String(progress.failedFits)} /><Fact label="Cancelled fits" value={reportedCancelledFits == null ? "—" : String(reportedCancelledFits)} /><Fact label={cancelling ? "Cancellation state" : stoppedTerminal || cancelledTerminal ? "Unfinished fits" : "Remaining fits"} value={stoppedTerminal || cancelledTerminal ? terminalUnfinishedValue : remainingValue} /><Fact label="Runtime workers" value={admittedWorkersValue} /><Fact label="Elapsed" value={duration(progress.elapsedSeconds)} /><Fact label="ETA" value={etaValue} /></div>
    {runtimeAdmission ? <p className="mt-2 text-[10px] text-slate-600" data-testid="runtime-worker-admission">Runtime admission: {runtimeAdmission.effectiveCandidateWorkers} candidate worker(s) admitted from an upper bound of {runtimeAdmission.plannedCandidateWorkers}; {runtimeAdmission.availableMemoryGiBAtStart == null ? "available memory at start was not reported" : `${runtimeAdmission.availableMemoryGiBAtStart.toFixed(2)} GiB available at start`} · {human(runtimeAdmission.admissionPolicy)}.</p> : null}
    {progress.activeCandidates?.length ? <div className="mt-3 grid gap-2 md:grid-cols-2">{progress.activeCandidates.map((candidate) => <div key={candidate.taskId} className="rounded-lg border border-slate-200 bg-white p-3"><b className="text-xs text-slate-900">{candidate.algorithmLabel}</b><p className="mt-1 text-[10px] text-slate-500">{candidate.featureUniverse} · configuration {candidate.configuration}/{candidate.configurationCount} · fold {candidate.fold}/{candidate.foldCount} · active {duration(candidate.elapsedSeconds)}</p><p className="mt-1 truncate font-mono text-[9px] text-slate-400" title={JSON.stringify(candidate.hyperparameters)}>{JSON.stringify(candidate.hyperparameters)}</p></div>)}</div> : null}
    {stoppedTerminal ? <div role="alert" className="mt-3 rounded-lg border border-rose-300 bg-white p-3 text-xs text-rose-900"><b>{interruptedTerminal ? "Batch was interrupted and is held closed." : "Batch failed before completion."}</b> {job.error?.code ? <span className="font-mono">{job.error.code}: </span> : null}{job.error?.message || (interruptedTerminal ? "The coordinator stopped before a terminal model-development receipt completed." : "The worker stopped without a persisted error message.")}<span className="mt-1 block">Unfinished work: {terminalUnfinishedValue}. Completed immutable candidate receipts remain preserved; unfinished work is not presented as completed model evidence.</span></div> : cancelledTerminal ? <div className="mt-3 rounded-lg border border-amber-300 bg-white p-3 text-xs text-amber-950"><b>{job.status === "CANCELLED_PARTIAL" ? "Batch cancelled after preserving completed evidence." : "Batch cancelled before model evidence completed."}</b><span className="mt-1 block">{progress.cancelledConfigurations == null ? "Cancelled-configuration count unavailable" : `${progress.cancelledConfigurations} configuration(s)`} · {reportedCancelledFits == null ? "cancelled fold-fit count unavailable" : `${reportedCancelledFits} fold fit(s)`}. Unfinished work: {terminalUnfinishedValue}. Completed immutable candidate receipts remain available.</span>{progress.message ? <span className="mt-1 block">{progress.message}</span> : null}</div> : <p className={`mt-3 text-xs ${cancelling ? "text-amber-950" : "text-cyan-900"}`}>{progress.message || (completedTerminal ? "Terminal receipt persisted." : "Progress is awaiting the next worker checkpoint.")}</p>}
    {progress.completedCandidateReceipts?.length ? <p className="mt-2 text-[10px] text-slate-700">{progress.completedCandidateReceipts.length} independent candidate receipt(s) persisted.</p> : null}
  </section>;
}

function Loading() { return <section className="grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white" role="status"><div className="text-center"><Loader2 className="mx-auto animate-spin text-cyan-700" size={24} /><p className="mt-2 text-sm font-semibold text-slate-800">Resolving project model authorities and immutable evidence…</p><p className="mt-1 text-xs text-slate-500">No model request is issued while the page loads.</p></div></section>; }
function Failure({ message, retry }: { message: string; retry: () => Promise<void> }) { return <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5" role="alert"><div className="flex items-center gap-2 font-semibold text-rose-900"><AlertTriangle size={17} />Model Development Laboratory held closed</div><p className="mt-2 text-sm leading-6 text-rose-800">{message}</p><button type="button" onClick={() => void retry()} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-rose-900 px-3 py-2 text-xs font-semibold text-white"><RefreshCw size={13} />Retry exact authority</button></section>; }
function BlockingReasons({ blockers }: { blockers: string[] }) { return <section className="rounded-2xl border border-rose-200 bg-rose-50 p-4" role="alert"><div className="flex items-center gap-2 text-sm font-semibold text-rose-900"><Lock size={16} />Execution remains held closed</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-rose-800">{blockers.map((item) => <li key={item}>{item}</li>)}</ul></section>; }
function SectionTitle({ icon, title, description }: { icon: JSX.Element; title: string; description: string }) { return <div className="flex items-start gap-2"><span className="mt-0.5 text-cyan-700">{icon}</span><div><h3 className="text-sm font-semibold text-slate-950">{title}</h3><p className="mt-0.5 text-xs leading-5 text-slate-500">{description}</p></div></div>; }
function DarkFact({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: "rose" }) { return <div className="min-w-0 bg-slate-950 px-4 py-4"><div className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">{label}</div><div className={`mt-1 truncate text-sm font-semibold ${tone === "rose" ? "text-rose-300" : "text-white"}`}>{value}</div><div className="mt-1 truncate text-[9px] text-slate-400" title={detail}>{detail}</div></div>; }
function Fact({ label, value }: { label: string; value: string }) { return <div className="rounded-lg border border-slate-200 bg-white p-2"><div className="text-[9px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 truncate text-xs font-semibold text-slate-900" title={value}>{value}</div></div>; }
function Action({ onClick, children }: { onClick: () => void; children: ReactNode }) { return <button type="button" onClick={onClick} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:border-cyan-400 hover:text-cyan-800">{children}</button>; }
function Pill({ label, tone }: { label: string; tone: "emerald" | "cyan" | "rose" | "amber" | "slate" }) { const style = { emerald: "border-emerald-200 bg-emerald-50 text-emerald-800", cyan: "border-cyan-200 bg-cyan-50 text-cyan-800", rose: "border-rose-200 bg-rose-50 text-rose-800", amber: "border-amber-200 bg-amber-50 text-amber-900", slate: "border-slate-200 bg-slate-50 text-slate-700" }[tone]; return <span className={`inline-flex rounded-full border px-2 py-1 text-[9px] font-semibold ${style}`}>{label}</span>; }
function Info({ title, children }: { title: string; children: ReactNode }) { return <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><h3 className="flex items-center gap-2 text-sm font-semibold text-slate-950"><CheckCircle2 size={15} className="text-emerald-600" />{title}</h3><ul className="mt-3 space-y-2 text-xs leading-5 text-slate-700">{children}</ul></section>; }

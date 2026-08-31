import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  BarChart3,
  CalendarClock,
  Check,
  CheckCircle2,
  ChevronDown,
  GitBranch,
  History,
  Lock,
  RefreshCw,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Users,
} from "lucide-react";
import type { CurrentGoldReviewState } from "../workflow/currentGoldDataReview";
import { BarChart, Card, LineChart, Pill, Spinner } from "./cockpitUi";
import {
  fetchFeatureSetState,
  fetchSplitContractState,
  fetchSplitStudio,
  generateAutomaticSplit,
  mutateSplitContract,
  validateManualSplit,
  type FeatureSetVersion,
  type SplitContractState,
  type SplitContractVersion,
  type SplitFold,
  type SplitStudioData,
  type StudioAuthority,
} from "./projectFeatureSplitApi";

type Mode = "AUTOMATIC" | "MANUAL";
type WindowPolicy = "EXPANDING" | "ROLLING";
type ManualFold = Pick<SplitFold, "foldNumber" | "trainingStart" | "trainingEnd" | "validationStart" | "validationEnd">;

const fmtInt = (value: number | null | undefined) => value == null ? "—" : value.toLocaleString();
const fmtPct = (value: number | null | undefined) => value == null ? "—" : `${value.toFixed(2)}%`;

function normalizeSplitState(value: any): SplitContractState {
  return value?.contractState ?? value?.state ?? value ?? {
    expectedChecksum: "NO_CURRENT_SPLIT_CONTRACT",
    draft: null,
    registered: null,
    history: [],
  };
}

const foldIdentity = (fold: ManualFold | SplitFold) => ({
  foldNumber: fold.foldNumber,
  trainingStart: fold.trainingStart,
  trainingEnd: fold.trainingEnd,
  validationStart: fold.validationStart,
  validationEnd: fold.validationEnd,
});

function designFingerprint(value: {
  mode: Mode;
  windowPolicy: WindowPolicy;
  foldCount: number;
  embargoDays: number;
  minimumTrainingGames: number;
  minimumValidationGames: number;
  allowGaps: boolean;
  deterministicSeed: number;
  selectedFeatureSetIds: string[];
  folds: (ManualFold | SplitFold)[];
}) {
  return JSON.stringify({
    ...value,
    allowGaps: value.mode === "MANUAL" ? value.allowGaps : false,
    windowPolicy: value.mode === "AUTOMATIC" ? "EXPANDING" : value.windowPolicy,
    selectedFeatureSetIds: value.selectedFeatureSetIds,
    folds: value.folds.map(foldIdentity),
  });
}

function versionDesignFingerprint(value: SplitContractVersion) {
  return designFingerprint({
    mode: value.mode,
    windowPolicy: value.windowPolicy,
    foldCount: value.foldCount,
    embargoDays: value.embargoDays,
    minimumTrainingGames: value.minimumTrainingGames,
    minimumValidationGames: value.minimumValidationGames,
    allowGaps: value.allowGaps,
    deterministicSeed: value.deterministicSeed,
    selectedFeatureSetIds: value.selectedFeatureSetIds,
    folds: value.folds,
  });
}

const versionDraftFingerprint = (value: SplitContractVersion) =>
  JSON.stringify({ design: versionDesignFingerprint(value), notes: value.notes });

export function ProjectBoundSplitBalance({
  state,
  projectId,
  go,
}: {
  state: CurrentGoldReviewState;
  projectId: string;
  go: (id: string) => void;
}) {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [studio, setStudio] = useState<SplitStudioData | null>(null);
  const [authority, setAuthority] = useState<StudioAuthority | null>(null);
  const [mode, setMode] = useState<Mode>("AUTOMATIC");
  const [windowPolicy, setWindowPolicy] = useState<WindowPolicy>("EXPANDING");
  const foldCount = 5;
  const [embargoDays, setEmbargoDays] = useState(0);
  const [minimumTrainingGames, setMinimumTrainingGames] = useState(2_000);
  const [minimumValidationGames, setMinimumValidationGames] = useState(500);
  const [seed, setSeed] = useState(731_026);
  const [allowGaps, setAllowGaps] = useState(false);
  const [manualFolds, setManualFolds] = useState<ManualFold[]>([]);
  const [registeredFeatureSets, setRegisteredFeatureSets] = useState<FeatureSetVersion[]>([]);
  const [selectedFeatureSetIds, setSelectedFeatureSetIds] = useState<string[]>([]);
  const [contractState, setContractState] = useState<SplitContractState>({ expectedChecksum: "NO_CURRENT_SPLIT_CONTRACT", draft: null, registered: null, history: [] });
  const [validatedFingerprint, setValidatedFingerprint] = useState<string | null>(null);
  const [compareLeftId, setCompareLeftId] = useState("");
  const [compareRightId, setCompareRightId] = useState("");
  const [notes, setNotes] = useState("Five expanding, date-atomic validation folds with natural class base rates.");
  const [mutation, setMutation] = useState<{ busy: boolean; message: string | null; error: string | null }>({ busy: false, message: null, error: null });

  const load = useCallback(async (signal?: AbortSignal) => {
    setStatus("loading");
    setError(null);
    try {
      const [splitResponse, featureResponse, contractResponse] = await Promise.all([
        fetchSplitStudio(projectId, signal),
        fetchFeatureSetState(projectId, signal),
        fetchSplitContractState(projectId, signal),
      ]);
      setAuthority(splitResponse.authority);
      const sets = (featureResponse.data as any)?.registered ?? (featureResponse.data as any)?.featureSetState?.registered ?? [];
      const nextContractState = normalizeSplitState(contractResponse.data);
      const restored = nextContractState.draft ?? nextContractState.registered;
      setRegisteredFeatureSets(sets);
      setContractState(nextContractState);
      setCompareLeftId(nextContractState.history[0]?.splitContractId ?? "");
      setCompareRightId(nextContractState.history[1]?.splitContractId ?? "");
      if (restored) {
        const restoredFolds = restored.folds.map(foldIdentity);
        setMode(restored.mode);
        setWindowPolicy(restored.mode === "AUTOMATIC" ? "EXPANDING" : restored.windowPolicy);
        setEmbargoDays(restored.embargoDays);
        setMinimumTrainingGames(restored.minimumTrainingGames);
        setMinimumValidationGames(restored.minimumValidationGames);
        setSeed(restored.deterministicSeed);
        setAllowGaps(restored.allowGaps);
        setSelectedFeatureSetIds(restored.selectedFeatureSetIds);
        setManualFolds(restoredFolds);
        setNotes(restored.notes);
        setStudio({
          ...splitResponse.data,
          folds: restored.folds,
          qualityGates: restored.qualityGates.length ? restored.qualityGates : splitResponse.data.qualityGates,
        });
        setValidatedFingerprint(versionDesignFingerprint(restored));
      } else {
        const recommended = splitResponse.data.recommendedDesign;
        const recommendedFolds = splitResponse.data.folds.map(foldIdentity);
        setMode("AUTOMATIC");
        setWindowPolicy("EXPANDING");
        setEmbargoDays(recommended.embargoDays);
        setMinimumTrainingGames(recommended.minimumTrainingGames);
        setMinimumValidationGames(recommended.minimumValidationGames);
        setSeed(recommended.deterministicSeed || 731_026);
        setAllowGaps(false);
        setSelectedFeatureSetIds(sets.slice(0, 3).map((item: FeatureSetVersion) => item.featureSetId));
        setManualFolds(recommendedFolds);
        setStudio(splitResponse.data);
        setValidatedFingerprint(null);
      }
      setStatus("ready");
    } catch (caught) {
      if (signal?.aborted) return;
      setStatus("error");
      setError(caught instanceof Error ? caught.message : "Split & Balance authority could not be loaded.");
    }
  }, [projectId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const designPayload = useMemo(() => ({
    authorityKey: authority?.authorityKey,
    mode,
    foldCount,
    windowPolicy,
    trainingPolicy: windowPolicy === "ROLLING" ? "ROLLING_WINDOW" : "EXPANDING_WINDOW",
    embargoDays,
    minimumTrainingGames,
    minimumValidationGames,
    groupingUnit: "CANONICAL_GAME",
    dateAtomic: true,
    allowGaps: mode === "MANUAL" ? allowGaps : false,
    deterministicSeed: seed,
    preprocessingScope: "TRAINING_FOLD_ONLY",
    classPolicy: "NATURAL_BASE_RATES",
    selectedFeatureSetIds,
  }), [authority?.authorityKey, mode, foldCount, windowPolicy, embargoDays, minimumTrainingGames, minimumValidationGames, allowGaps, seed, selectedFeatureSetIds]);

  const currentDesignFingerprint = useMemo(() => designFingerprint({
    mode,
    windowPolicy,
    foldCount,
    embargoDays,
    minimumTrainingGames,
    minimumValidationGames,
    allowGaps,
    deterministicSeed: seed,
    selectedFeatureSetIds,
    folds: mode === "MANUAL" ? manualFolds : (studio?.folds ?? []),
  }), [mode, windowPolicy, foldCount, embargoDays, minimumTrainingGames, minimumValidationGames, allowGaps, seed, selectedFeatureSetIds, manualFolds, studio?.folds]);
  const currentDraftFingerprint = useMemo(
    () => JSON.stringify({ design: currentDesignFingerprint, notes }),
    [currentDesignFingerprint, notes],
  );

  const regenerate = async () => {
    if (!authority) return;
    setMutation({ busy: true, message: null, error: null });
    try {
      const response = mode === "AUTOMATIC"
        ? await generateAutomaticSplit(projectId, designPayload)
        : await validateManualSplit(projectId, { ...designPayload, folds: manualFolds });
      setStudio(response.data);
      setManualFolds(response.data.folds.map((fold) => ({ foldNumber: fold.foldNumber, trainingStart: fold.trainingStart, trainingEnd: fold.trainingEnd, validationStart: fold.validationStart, validationEnd: fold.validationEnd })));
      setValidatedFingerprint(designFingerprint({
        mode,
        windowPolicy,
        foldCount,
        embargoDays,
        minimumTrainingGames,
        minimumValidationGames,
        allowGaps,
        deterministicSeed: seed,
        selectedFeatureSetIds,
        folds: response.data.folds,
      }));
      const blocked = response.data.qualityGates.filter((gate) => gate.blocking && !gate.passed);
      setMutation({ busy: false, message: blocked.length ? null : `${mode === "AUTOMATIC" ? "Automatic" : "Manual"} split validated with all registration gates passing.`, error: blocked.length ? blocked.map((gate) => gate.detail).join(" · ") : null });
    } catch (caught) {
      setMutation({ busy: false, message: null, error: caught instanceof Error ? caught.message : "Split validation failed." });
    }
  };

  const saveDraft = async () => {
    if (!authority || !studio) return;
    setMutation({ busy: true, message: null, error: null });
    try {
      const response = await mutateSplitContract(projectId, "draft", {
        ...designPayload,
        expectedChecksum: contractState.expectedChecksum,
        folds: mode === "MANUAL" ? manualFolds : studio.folds,
        notes,
      });
      const nextState = normalizeSplitState(response.data);
      setContractState(nextState);
      if (nextState.draft) {
        setValidatedFingerprint(versionDesignFingerprint(nextState.draft));
        setStudio((current) => current ? {
          ...current,
          folds: nextState.draft?.folds ?? current.folds,
          qualityGates: nextState.draft?.qualityGates.length ? nextState.draft.qualityGates : current.qualityGates,
        } : current);
      }
      const draftBlocked = nextState.draft?.qualityGates.some((gate) => gate.blocking && !gate.passed);
      setMutation({
        busy: false,
        message: draftBlocked
          ? "Immutable draft saved. Registration remains blocked by its stored quality gates."
          : "Immutable split-and-balance draft saved.",
        error: null,
      });
    } catch (caught) {
      setMutation({ busy: false, message: null, error: caught instanceof Error ? caught.message : "Draft save failed." });
    }
  };

  const register = async () => {
    if (!authority || !contractState.draft) return;
    setMutation({ busy: true, message: null, error: null });
    try {
      const response = await mutateSplitContract(projectId, "register", {
        authorityKey: authority.authorityKey,
        expectedChecksum: contractState.draft.checksum,
        contractId: contractState.draft.splitContractId,
      });
      const nextState = normalizeSplitState(response.data);
      setContractState(nextState);
      if (nextState.registered) setValidatedFingerprint(versionDesignFingerprint(nextState.registered));
      setMutation({ busy: false, message: "Split contract registered. Model Laboratory may now consume only these exact identities; no model was fit.", error: null });
    } catch (caught) {
      setMutation({ busy: false, message: null, error: caught instanceof Error ? caught.message : "Split registration failed." });
    }
  };

  if (state.status !== "ready" || !state.review) return <SplitError title="Project-bound authority unavailable" message={state.error || "The accepted Current Gold authority is loading."} />;
  if (status === "loading" && !studio) return <div className="rounded-2xl border border-slate-200 bg-white p-8"><Spinner label="Deriving date-atomic game folds from Current Gold…" /></div>;
  if (status === "error" || !studio || !authority) return <SplitError title="Split & Balance is held closed" message={error || "The project-bound split authority was incomplete."} />;

  const summary = studio.summary;
  const validationStale = validatedFingerprint !== currentDesignFingerprint;
  const draftMatchesVisibleDesign = Boolean(
    contractState.draft
      && versionDraftFingerprint(contractState.draft) === currentDraftFingerprint,
  );
  const draftBlocking = contractState.draft?.qualityGates.filter(
    (gate) => gate.blocking && !gate.passed,
  ) ?? [];
  const registeredFeatureIdentitiesAvailable = Boolean(
    contractState.registered?.selectedFeatureSetIds.length
      && contractState.registered.selectedFeatureSetIds.every((id) =>
        registeredFeatureSets.some((item) => item.featureSetId === id)),
  );
  const unavailableSelectedFeatureIds = selectedFeatureSetIds.filter(
    (id) => !registeredFeatureSets.some((item) => item.featureSetId === id),
  );
  const classNames = studio.targetDistribution.map((item) => item.class);
  const validationCounts = studio.folds.map((fold) => fold.validationGames);
  const trainCounts = studio.folds.map((fold) => fold.trainGames);

  return (
    <div className="min-w-0 space-y-4" data-testid="project-bound-split-balance-studio">
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-950 via-slate-900 to-violet-950 p-5 text-white shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl"><div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-violet-300">Step 08 · Project-bound temporal design</div><h2 className="mt-1 text-2xl font-semibold tracking-tight">Split &amp; Balance</h2><p className="mt-2 text-sm leading-6 text-slate-300">Use five expanding-window folds grouped by canonical game and calendar date; fit all preprocessing inside each training fold; preserve the natural eight-class baseball outcome distribution.</p></div>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3"><DarkMetric label="Development" value={`${fmtInt(summary.developmentRows)} rows`} /><DarkMetric label="Grouping" value="Canonical game" /><DarkMetric label="Final OOT" value={`${fmtInt(summary.finalOotRows)} LOCKED`} /></div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2"><Pill label="Date atomic" tone="cyan" /><Pill label="No random split" tone="rose" /><Pill label="Natural base rates" tone="emerald" /><Pill label="Preprocessing: training fold only" tone="violet" /></div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="Split and Balance summary"><Metric label="Development rows" value={fmtInt(summary.developmentRows)} detail={`${summary.developmentStart} → ${summary.developmentEnd}`} /><Metric label="Development games" value={fmtInt(summary.developmentGames)} detail="Exact canonical identities" tone="cyan" /><Metric label="Distinct dates" value={fmtInt(summary.developmentDates)} detail="Calendar-date atomic" /><Metric label="Folds" value={fmtInt(studio.folds.length)} detail={`${summary.trainingPolicy} windows`} /><Metric label="Final OOT" value={fmtInt(summary.finalOotRows)} detail={`${summary.finalOotStart} → ${summary.finalOotEnd} · LOCKED`} tone="rose" /></section>

      <Card title="Recommended chronological design" icon={CalendarClock} description="The first complete governed season is retained as initial training. Subsequent validation dates are divided into contiguous windows with approximately equal canonical-game counts.">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <TemporalTimeline folds={studio.folds} finalOotStart={summary.finalOotStart} finalOotEnd={summary.finalOotEnd} />
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs leading-5 text-slate-700"><div className="font-semibold text-slate-950">Why this design?</div><ul className="mt-2 space-y-1"><li>• Every game stays intact.</li><li>• Every calendar date stays on one side of a boundary.</li><li>• Training always precedes validation.</li><li>• Validation games appear exactly once.</li><li>• Final-OOT labels are never queried.</li></ul></div>
        </div>
      </Card>

      <Card title="Exact five-fold contract" icon={GitBranch} description="Dates and populations are derived from actual canonical game/date counts, not invented in the frontend.">
        <FoldTable folds={studio.folds} />
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Training growth and validation size" icon={BarChart3} description="Expanding training populations grow monotonically while validation game counts remain approximately balanced."><LineChart categories={studio.folds.map((fold) => `Fold ${fold.foldNumber}`)} series={[{ name: "Training games", data: trainCounts, color: "#0891b2" }, { name: "Validation games", data: validationCounts, color: "#d97706" }]} height={260} xLabel="Chronological fold" yLabel="Canonical games" /></Card>
        <Card title="Overall eight-class balance" icon={Users} description="Natural observed development distribution. No SMOTE, random oversampling, or undersampling."><BarChart categories={classNames} values={studio.targetDistribution.map((item) => item.rows)} height={260} color="#7c3aed" valueFmt={(value) => fmtInt(value)} /></Card>
      </div>

      <Card title="Class balance by fold" icon={BarChart3} description="Training and validation distributions are shown separately. Optional class weighting, if later tested, is learned from each training fold only.">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{studio.folds.map((fold) => <details key={fold.foldNumber} className="rounded-xl border border-slate-200 bg-white" open={fold.foldNumber === 1}><summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs font-semibold text-slate-900">Fold {fold.foldNumber}<span className="ml-auto text-[10px] text-slate-500">{fmtInt(fold.validationRows)} validation PAs</span><ChevronDown size={13} /></summary><div className="border-t border-slate-100 p-3"><table className="w-full text-[10px]"><caption className="sr-only">Fold {fold.foldNumber} training and validation class percentages</caption><thead><tr className="text-slate-500"><th scope="col" className="pb-1 text-left">Class</th><th scope="col" className="pb-1 text-right">Train</th><th scope="col" className="pb-1 text-right">Validation</th></tr></thead><tbody>{classNames.map((name) => { const train = fold.trainingClassDistribution.find((item) => item.class === name); const validation = fold.validationClassDistribution.find((item) => item.class === name); return <tr key={name}><th scope="row" className="border-t border-slate-100 py-1 text-left font-semibold">{name}</th><td className="border-t border-slate-100 py-1 text-right tabular-nums">{fmtPct(train?.percent)}</td><td className="border-t border-slate-100 py-1 text-right tabular-nums">{fmtPct(validation?.percent)}</td></tr>; })}</tbody></table></div></details>)}</div>
        <div className="mt-4 rounded-xl border border-cyan-200 bg-cyan-50 p-3 text-xs leading-5 text-cyan-950"><b>Default:</b> NO RANDOM OVERSAMPLING · NO SMOTE · NO UNDERSAMPLING · RETAIN NATURAL BASE RATES. Later challengers may use fold-local inverse-frequency, bounded effective-number weights, or algorithm-supported focal loss; none is automatically adopted here.</div>
      </Card>

      <Card title="Cold start, missingness, and feature-set coverage" icon={AlertCircle} description="These diagnostics are calculated per fold without deriving preprocessing statistics from validation rows.">
        <div role="region" aria-label="Fold cold start missingness and coverage" tabIndex={0} className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-xs"><caption className="sr-only">Per-fold validation cold-start, missingness, player, feature-set, and preprocessing diagnostics</caption><thead><tr>{["Fold", "Cold start", "Physical missingness", "Batters", "Pitchers", "Selected feature sets", "Preprocessing scope"].map((label) => <th key={label} scope="col" className="border-b border-slate-200 px-2 py-2 uppercase text-slate-500">{label}</th>)}</tr></thead><tbody>{studio.folds.map((fold) => <tr key={fold.foldNumber}><th scope="row" className="border-b border-slate-100 px-2 py-2 text-left font-semibold">{fold.foldNumber}</th><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtPct(fold.coldStartPercent)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtPct(fold.physicalMissingPercent)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(fold.batters)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(fold.pitchers)}</td><td className="border-b border-slate-100 px-2 py-2">{fold.featureSetAvailability.length ? fold.featureSetAvailability.map((item) => `${item.featureSetId}: ${item.available ? "available" : item.reason}`).join(" · ") : "Select registered sets below"}</td><td className="border-b border-slate-100 px-2 py-2 font-semibold text-cyan-800">{fold.preprocessingFitScope}</td></tr>)}</tbody></table></div>
      </Card>

      <Card title="Design controls" icon={SlidersHorizontal} description="Review automatic boundaries or enter an exact manual design. Random K-fold, random stratified, and row-level splits are unavailable because they violate temporal and game identity.">
        <div className="flex flex-wrap items-start gap-3"><ChoiceGroup<Mode> label="Split design mode" options={[{ value: "AUTOMATIC", label: "Recommended automatic" }, { value: "MANUAL", label: "Manual dates" }]} value={mode} onChange={(next) => { setMode(next); if (next === "AUTOMATIC") setWindowPolicy("EXPANDING"); }} /><ChoiceGroup<WindowPolicy> label="Training window policy" options={[{ value: "EXPANDING", label: "Expanding window" }, { value: "ROLLING", label: "Rolling window", disabled: mode === "AUTOMATIC" }]} value={windowPolicy} onChange={setWindowPolicy} /></div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><LockedOption label="Fold count" value="5 (required)" /><NumberInput label="Embargo days" value={embargoDays} min={0} max={30} onChange={setEmbargoDays} /><NumberInput label="Minimum train games" value={minimumTrainingGames} min={1} onChange={setMinimumTrainingGames} /><NumberInput label="Minimum validation games" value={minimumValidationGames} min={1} onChange={setMinimumValidationGames} /><NumberInput label="Deterministic seed" value={seed} min={1} onChange={setSeed} /></div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3"><LockedOption label="Grouping unit" value="CANONICAL_GAME" /><LockedOption label="Date policy" value="DATE_ATOMIC" /><LockedOption label="Preprocessing scope" value="TRAINING_FOLD_ONLY" /></div>
        {mode === "MANUAL" ? <><label className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950"><input type="checkbox" checked={allowGaps} onChange={(event) => setAllowGaps(event.target.checked)} /><span><b>Allow explicit validation gaps</b><br />When off, every governed game date from the first validation date through 2026-08-13 must be assigned exactly once.</span></label><ManualFoldEditor folds={manualFolds} setFolds={setManualFolds} /></> : null}
        {validationStale ? <p role="status" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900"><b>Validation required.</b> Design controls differ from the last server-validated fold contract. Validate before saving or registering.</p> : null}
        <div className="mt-4 flex flex-wrap gap-2"><button type="button" onClick={() => void regenerate()} disabled={mutation.busy} className="rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white disabled:bg-slate-300">{mode === "AUTOMATIC" ? "Regenerate from game counts" : "Validate manual dates"}</button><button type="button" disabled title="Random splits are unavailable for this time-dependent, game-grouped project." className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-xs font-semibold text-rose-500">Random split unavailable</button></div>
      </Card>

      <Card title="Feature-set handoff" icon={ShieldCheck} description="A split contract names exact registered feature-set versions. No unavailable feature may be active.">
        {registeredFeatureSets.length ? <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">{registeredFeatureSets.map((item) => <label key={item.featureSetId} className={`rounded-xl border p-3 ${selectedFeatureSetIds.includes(item.featureSetId) ? "border-cyan-500 bg-cyan-50" : "border-slate-200"}`}><div className="flex items-start gap-2"><input type="checkbox" checked={selectedFeatureSetIds.includes(item.featureSetId)} onChange={() => setSelectedFeatureSetIds((current) => current.includes(item.featureSetId) ? current.filter((id) => id !== item.featureSetId) : [...current, item.featureSetId])} /><div><div className="text-xs font-semibold text-slate-900">{item.name}</div><div className="mt-0.5 text-[10px] text-slate-500">v{item.version} · {item.orderedFeatures.length} features · {item.checksum.slice(0, 12)}…</div></div></div></label>)}</div> : <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Register at least one Feature Engineering candidate before saving a split contract.</div>}
        {unavailableSelectedFeatureIds.length ? <p role="alert" className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-2 text-xs text-rose-900">The restored split references feature-set identities that are no longer registered for this authority: {unavailableSelectedFeatureIds.join(", ")}.</p> : null}
      </Card>

      <Card title="Split quality gates" icon={CheckCircle2} description="Every blocking check must pass before registration. Invalid boundaries are errors, not advisory warnings.">
        <div className="grid gap-2 md:grid-cols-2">{studio.qualityGates.map((gate) => <div key={gate.code} className={`rounded-xl border p-3 ${gate.passed ? "border-emerald-200 bg-emerald-50/50" : "border-rose-200 bg-rose-50"}`}><div className="flex items-center gap-2 text-xs font-semibold text-slate-900">{gate.passed ? <CheckCircle2 size={14} className="text-emerald-600" /> : <AlertCircle size={14} className="text-rose-600" />}{gate.label}<span className="ml-auto text-[9px] uppercase text-slate-500">{gate.blocking ? "blocking" : "informational"}</span></div><p className="mt-1 text-[11px] leading-4 text-slate-600">{gate.detail}</p></div>)}</div>
      </Card>

      <Card title="Immutable split registration" icon={Save} description="Save a draft, review exact folds and gates, then register a versioned contract. Registration does not fit, score, tune, or promote a model.">
        <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Notes<textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900" /></label>
        <div className="mt-3 flex flex-wrap gap-2"><button type="button" disabled={mutation.busy || validationStale || !selectedFeatureSetIds.length || unavailableSelectedFeatureIds.length > 0} onClick={() => void saveDraft()} className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white disabled:bg-slate-300"><Save size={14} /> {contractState.registered && !contractState.draft ? "Save superseding draft" : "Save immutable draft"}</button><button type="button" disabled={mutation.busy || !contractState.draft || validationStale || !draftMatchesVisibleDesign || draftBlocking.length > 0} onClick={() => void register()} className="inline-flex items-center gap-2 rounded-lg bg-cyan-700 px-4 py-2 text-xs font-semibold text-white disabled:bg-slate-300"><CheckCircle2 size={14} /> Register split contract</button><button type="button" onClick={() => void load()} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-4 py-2 text-xs font-semibold text-slate-700"><RefreshCw size={14} /> Reload exact saved design</button></div>
        {contractState.draft && !draftMatchesVisibleDesign ? <p role="alert" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900"><b>Unsaved changes.</b> The visible design does not match the immutable draft. Save a new exact draft before registration.</p> : null}
        {mutation.message ? <p role="status" className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-2 text-xs text-emerald-800">{mutation.message}</p> : null}{mutation.error ? <p role="alert" className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-2 text-xs text-rose-800">{mutation.error}</p> : null}
        <div className="mt-4 grid gap-3 lg:grid-cols-2"><VersionCard label="Current draft" value={contractState.draft} /><VersionCard label="Registered authority" value={contractState.registered} /></div>
        <VersionHistory history={contractState.history} compareLeftId={compareLeftId} compareRightId={compareRightId} setCompareLeftId={setCompareLeftId} setCompareRightId={setCompareRightId} />
      </Card>

      <section className="rounded-2xl border border-slate-200 bg-white p-4" data-testid="split-balance-audit-strip"><div className="flex flex-wrap items-center gap-2 text-xs"><History size={15} className="text-cyan-700" /><b>Workflow handoff</b><Pill label="Gold identity matches" tone="emerald" /><Pill label="Final OOT labels not queried" tone="violet" /><Pill label="Model activity 0" tone="cyan" /><span className="ml-auto max-w-full break-all font-mono text-[10px] text-slate-400">{authority.reviewDigest}</span></div><div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => go("modellab")} disabled={!contractState.registered || !registeredFeatureIdentitiesAvailable} className="inline-flex items-center gap-2 rounded-lg bg-cyan-700 px-4 py-2 text-xs font-semibold text-white disabled:bg-slate-300"><Check size={14} /> Continue to Model Laboratory</button><span className="self-center text-[11px] text-slate-500">Handoff uses only the registered split contract’s {contractState.registered?.selectedFeatureSetIds.length ?? 0} exact feature-set identities. Project champion: <b>None yet</b>. No legacy model is activated by this handoff.</span></div></section>
    </div>
  );
}

function SplitError({ title, message }: { title: string; message: string }) { return <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5" role="alert"><div className="flex items-center gap-2 font-semibold text-rose-900"><Lock size={17} />{title}</div><p className="mt-2 text-sm leading-6 text-rose-800">{message}</p></section>; }
function DarkMetric({ label, value }: { label: string; value: string }) { return <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2"><div className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">{label}</div><div className="mt-0.5 font-semibold text-white">{value}</div></div>; }
function Metric({ label, value, detail, tone = "slate" }: { label: string; value: string; detail: string; tone?: "slate" | "cyan" | "rose" }) { const classes = tone === "cyan" ? "border-cyan-200 bg-cyan-50/40" : tone === "rose" ? "border-rose-200 bg-rose-50/40" : "border-slate-200 bg-white"; return <div className={`rounded-xl border p-3 ${classes}`}><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 text-2xl font-semibold tabular-nums text-slate-950">{value}</div><div className="mt-1 text-[11px] text-slate-500">{detail}</div></div>; }
function LockedOption({ label, value }: { label: string; value: string }) { return <div className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs"><div className="flex items-center gap-1 text-[9px] font-semibold uppercase text-slate-500"><Lock size={10} />{label}</div><div className="mt-1 font-semibold text-slate-900">{value}</div></div>; }
function NumberInput({ label, value, onChange, min, max }: { label: string; value: number; onChange: (value: number) => void; min?: number; max?: number }) { return <label className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}<input type="number" value={value} min={min} max={max} onChange={(event) => onChange(Number(event.target.value))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900" /></label>; }

function ChoiceGroup<T extends string>({ label, options, value, onChange }: {
  label: string;
  options: { value: T; label: string; disabled?: boolean }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return <div><div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div role="group" aria-label={label} className="inline-flex flex-wrap gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1">{options.map((option) => <button type="button" key={option.value} disabled={option.disabled} aria-pressed={value === option.value} onClick={() => onChange(option.value)} className={`rounded-md px-3 py-1.5 text-xs font-semibold ${value === option.value ? "bg-slate-900 text-white" : option.disabled ? "text-slate-300" : "text-slate-600 hover:bg-white"}`}>{option.label}</button>)}</div></div>;
}

function VersionHistory({ history, compareLeftId, compareRightId, setCompareLeftId, setCompareRightId }: {
  history: SplitContractVersion[];
  compareLeftId: string;
  compareRightId: string;
  setCompareLeftId: (value: string) => void;
  setCompareRightId: (value: string) => void;
}) {
  const left = history.find((item) => item.splitContractId === compareLeftId) ?? null;
  const right = history.find((item) => item.splitContractId === compareRightId) ?? null;
  const label = (item: SplitContractVersion) => `v${item.version} · ${item.status} · ${item.checksum.slice(0, 10)}…`;
  const compareRows = left && right ? [
    ["Status", left.status, right.status],
    ["Mode", `${left.mode} / ${left.windowPolicy}`, `${right.mode} / ${right.windowPolicy}`],
    ["Validation span", `${left.folds[0]?.validationStart ?? "—"} → ${left.folds.at(-1)?.validationEnd ?? "—"}`, `${right.folds[0]?.validationStart ?? "—"} → ${right.folds.at(-1)?.validationEnd ?? "—"}`],
    ["Embargo / gaps", `${left.embargoDays} days / ${left.allowGaps ? "allowed" : "prohibited"}`, `${right.embargoDays} days / ${right.allowGaps ? "allowed" : "prohibited"}`],
    ["Feature sets", left.selectedFeatureSetIds.join(", ") || "None", right.selectedFeatureSetIds.join(", ") || "None"],
    ["Checksum", left.checksum, right.checksum],
  ] : [];
  return <section className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3" aria-labelledby="split-version-history-title"><h3 id="split-version-history-title" className="text-xs font-semibold text-slate-950">Immutable split version history</h3>{history.length ? <><div role="region" aria-label="Immutable split versions" tabIndex={0} className="mt-2 overflow-x-auto"><table className="w-full min-w-[680px] text-left text-[11px]"><caption className="sr-only">Immutable split drafts, registrations, and superseded versions</caption><thead><tr>{["Version", "Status", "Mode", "Folds", "Feature sets", "Created", "Checksum"].map((heading) => <th key={heading} scope="col" className="border-b border-slate-200 px-2 py-2 uppercase text-slate-500">{heading}</th>)}</tr></thead><tbody>{history.map((item) => <tr key={item.splitContractId}><th scope="row" className="border-b border-slate-200 px-2 py-2">v{item.version}</th><td className="border-b border-slate-200 px-2 py-2">{item.status}</td><td className="border-b border-slate-200 px-2 py-2">{item.mode} / {item.windowPolicy}</td><td className="border-b border-slate-200 px-2 py-2">{item.foldCount}</td><td className="border-b border-slate-200 px-2 py-2">{item.selectedFeatureSetIds.length}</td><td className="border-b border-slate-200 px-2 py-2">{item.createdAt || "—"}</td><td className="max-w-48 truncate border-b border-slate-200 px-2 py-2 font-mono" title={item.checksum}>{item.checksum}</td></tr>)}</tbody></table></div><div className="mt-3 grid gap-2 sm:grid-cols-2"><label className="text-[10px] font-semibold uppercase text-slate-500">Compare version A<select value={compareLeftId} onChange={(event) => setCompareLeftId(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-xs font-normal text-slate-900"><option value="">Select version</option>{history.map((item) => <option key={item.splitContractId} value={item.splitContractId}>{label(item)}</option>)}</select></label><label className="text-[10px] font-semibold uppercase text-slate-500">Compare version B<select value={compareRightId} onChange={(event) => setCompareRightId(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-xs font-normal text-slate-900"><option value="">Select version</option>{history.map((item) => <option key={item.splitContractId} value={item.splitContractId}>{label(item)}</option>)}</select></label></div>{left && right ? <div role="region" aria-label="Selected split version comparison" tabIndex={0} className="mt-3 overflow-x-auto"><table className="w-full min-w-[620px] text-left text-[11px]"><caption className="sr-only">Comparison of two immutable split contract versions</caption><thead><tr><th scope="col" className="border-b border-slate-200 px-2 py-2">Field</th><th scope="col" className="border-b border-slate-200 px-2 py-2">Version A</th><th scope="col" className="border-b border-slate-200 px-2 py-2">Version B</th></tr></thead><tbody>{compareRows.map(([field, leftValue, rightValue]) => <tr key={field}><th scope="row" className="border-b border-slate-200 px-2 py-2">{field}</th><td className="break-all border-b border-slate-200 px-2 py-2">{leftValue}</td><td className="break-all border-b border-slate-200 px-2 py-2">{rightValue}</td></tr>)}</tbody></table></div> : <p className="mt-2 text-xs text-slate-500">Choose two immutable versions for a direct contract comparison.</p>}</> : <p className="mt-2 text-xs text-slate-500">No immutable split versions have been saved.</p>}</section>;
}

function TemporalTimeline({ folds, finalOotStart, finalOotEnd }: { folds: SplitFold[]; finalOotStart: string; finalOotEnd: string }) {
  return <div role="region" aria-label="Chronological split timeline" tabIndex={0} className="min-w-0 overflow-x-auto pb-2"><div className="flex min-w-[560px] gap-1"><div className="flex-[1.3] rounded-lg bg-slate-700 px-2 py-3 text-center text-[10px] font-semibold text-white"><div>INITIAL TRAINING</div><div className="mt-1 font-normal text-slate-300">{folds[0]?.trainingStart} → {folds[0]?.trainingEnd}</div></div>{folds.map((fold) => <div key={fold.foldNumber} className="flex-1 rounded-lg bg-cyan-600 px-2 py-3 text-center text-[10px] font-semibold text-white"><div>VALIDATION {fold.foldNumber}</div><div className="mt-1 font-normal text-cyan-100">{fold.validationStart}<br />{fold.validationEnd}</div></div>)}<div className="flex-1 rounded-lg bg-rose-600 px-2 py-3 text-center text-[10px] font-semibold text-white"><div>FINAL OOT · LOCKED</div><div className="mt-1 font-normal text-rose-100">{finalOotStart}<br />{finalOotEnd}</div></div></div></div>;
}

function FoldTable({ folds }: { folds: SplitFold[] }) {
  return <div role="region" aria-label="Exact five-fold split contract" tabIndex={0} className="overflow-x-auto"><table className="w-full min-w-[1400px] text-left text-[11px]"><caption className="sr-only">Exact five-fold chronological split dates, populations, diagnostics, and checksums</caption><thead><tr>{["Fold", "Training dates", "Validation dates", "Train rows", "Validation rows", "Train games", "Validation games", "Validation day count", "Batters", "Pitchers", "Cold start", "Missingness", "Preprocessing", "Checksum"].map((label) => <th key={label} scope="col" className="border-b border-slate-200 px-2 py-2 font-semibold uppercase text-slate-500">{label}</th>)}</tr></thead><tbody>{folds.map((fold) => <tr key={fold.foldNumber} className="hover:bg-cyan-50/30"><th scope="row" className="border-b border-slate-100 px-2 py-2 font-semibold">{fold.foldNumber}</th><td className="border-b border-slate-100 px-2 py-2">{fold.trainingStart}<br />{fold.trainingEnd}</td><td className="border-b border-slate-100 px-2 py-2 font-semibold text-cyan-800">{fold.validationStart}<br />{fold.validationEnd}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(fold.trainRows)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(fold.validationRows)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(fold.trainGames)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(fold.validationGames)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(fold.distinctValidationDates)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(fold.batters)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(fold.pitchers)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtPct(fold.coldStartPercent)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtPct(fold.physicalMissingPercent)}</td><td className="border-b border-slate-100 px-2 py-2 text-cyan-800">{fold.preprocessingFitScope}</td><td className="max-w-36 truncate border-b border-slate-100 px-2 py-2 font-mono text-[9px]" title={fold.checksum}>{fold.checksum}</td></tr>)}</tbody></table></div>;
}

function ManualFoldEditor({ folds, setFolds }: { folds: ManualFold[]; setFolds: (folds: ManualFold[]) => void }) {
  const update = (index: number, field: keyof ManualFold, value: string) => setFolds(folds.map((fold, item) => item === index ? { ...fold, [field]: field === "foldNumber" ? Number(value) : value } : fold));
  return <div role="region" aria-label="Manual fold date boundaries" tabIndex={0} className="mt-4 overflow-x-auto rounded-xl border border-amber-200 bg-amber-50/40 p-3"><div className="mb-2 text-xs font-semibold text-amber-950">Manual date design · final OOT dates are rejected</div><table className="w-full min-w-[760px] text-xs"><caption className="sr-only">Editable manual training and validation date boundaries for five folds</caption><thead><tr>{["Fold", "Train start", "Train end", "Validation start", "Validation end"].map((label) => <th key={label} scope="col" className="px-2 py-1 text-left uppercase text-amber-800">{label}</th>)}</tr></thead><tbody>{folds.map((fold, index) => <tr key={fold.foldNumber}><th scope="row" className="px-2 py-1 text-left font-semibold">{fold.foldNumber}</th>{(["trainingStart", "trainingEnd", "validationStart", "validationEnd"] as const).map((field) => <td key={field} className="px-2 py-1"><input aria-label={`Fold ${fold.foldNumber} ${field}`} type="date" min="2023-03-30" max="2026-08-13" value={fold[field]} onInput={(event) => update(index, field, event.currentTarget.value)} onChange={(event) => update(index, field, event.target.value)} className="w-full rounded border border-amber-200 bg-white px-2 py-1" /></td>)}</tr>)}</tbody></table></div>;
}

function VersionCard({ label, value }: { label: string; value: SplitContractState["draft"] | SplitContractState["registered"] }) { return <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div>{value ? <><div className="mt-1 font-semibold text-slate-900">{value.mode} · {value.foldCount} folds · v{value.version}</div><div className="mt-1 break-all font-mono text-[10px] text-slate-500">{value.checksum}</div><div className="mt-2 flex gap-2"><Pill label={value.status} tone={value.status === "REGISTERED" ? "emerald" : "amber"} /><Pill label={`${value.selectedFeatureSetIds.length} feature sets`} tone="cyan" /></div></> : <p className="mt-2 text-xs text-slate-500">None.</p>}</div>; }

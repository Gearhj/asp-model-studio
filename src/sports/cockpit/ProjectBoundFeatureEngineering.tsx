import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowUpDown,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Columns3,
  Copy,
  Eye,
  Filter,
  GitCompareArrows,
  History,
  Layers3,
  Lock,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wand2,
} from "lucide-react";
import type { CurrentGoldReviewState } from "../workflow/currentGoldDataReview";
import { BarChart, Card, Pill, Spinner } from "./cockpitUi";
import { CockpitDrawer } from "./CockpitDrawer";
import {
  fetchFeatureDetail,
  fetchFeatureInventory,
  fetchFeatureSetState,
  fetchFeatureStudioSummary,
  mutateFeatureSet,
  type FeatureFamily,
  type GovernedInteractionAuthority,
  type GovernedInteractionAuthoritySummary,
  type GovernedPreprocessingPriorAuthority,
  type FeatureInventory,
  type FeatureInventoryRow,
  type FeatureSetState,
  type FeatureSetVersion,
  type FeatureStudioSummary,
  type StudioAuthority,
  type TreatmentSpecificationDraftAuthority,
  type TreatmentSpecificationResolution,
} from "./projectFeatureSplitApi";
import {
  governedPriorBucket,
  type GovernedPriorBucket,
} from "./projectTreatmentApi";

type AsyncState<T> = { status: "loading" | "ready" | "error"; data: T | null; error: string | null };

const fmtInt = (value: number | null | undefined) => value == null ? "—" : value.toLocaleString();
const fmtPct = (value: number | null | undefined) => value == null ? "—" : `${value.toFixed(2)}%`;
const human = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const adoptedPolicyLabel = (policy: { policyId: string; version: number }) =>
  policy.policyId && policy.policyId !== "NOT_ADOPTED" && policy.version > 0
    ? `v${policy.version}`
    : "Not adopted";

const priorHierarchy = (authority: GovernedPreprocessingPriorAuthority) =>
  authority.hierarchy.length
    ? authority.hierarchy.map(human).join(" → ").replace(/\bMlb\b/g, "MLB")
    : "Not reported";

const focusedPriorOutputs = (outputs: string[]) => {
  const preferred = outputs.filter((output) =>
    /posterior_mean|effective_n|posterior_reliability|posterior_(?:variance|std)/i.test(
      output,
    ),
  );
  return (preferred.length ? preferred : outputs).slice(0, 5);
};

const PRIOR_BUCKET_PRESENTATION: Record<
  GovernedPriorBucket,
  {
    label: string;
    tone: "emerald" | "cyan" | "slate" | "rose";
    cardClass: string;
    reasonLabel: string;
    reasonClass: string;
  }
> = {
  executable: {
    label: "EXECUTABLE V1",
    tone: "emerald",
    cardClass: "border-emerald-200 bg-emerald-50/50",
    reasonLabel: "",
    reasonClass: "",
  },
  "binding-ready": {
    label: "BINDING READY · WAVE 2",
    tone: "cyan",
    cardClass: "border-cyan-200 bg-cyan-50/50",
    reasonLabel: "WAVE 2 ENGINE REQUIRED:",
    reasonClass: "border-cyan-200 text-cyan-950",
  },
  retired: {
    label: "RETIRED · NONSELECTABLE",
    tone: "slate",
    cardClass: "border-slate-300 bg-slate-100/70",
    reasonLabel: "RETIRED BY SCIENTIFIC DECISION:",
    reasonClass: "border-slate-300 text-slate-800",
  },
  blocked: {
    label: "BLOCKED · MISSING EVIDENCE",
    tone: "rose",
    cardClass: "border-rose-200 bg-rose-50/60",
    reasonLabel: "BLOCKED — MISSING EVIDENCE:",
    reasonClass: "border-rose-300 text-rose-950",
  },
};

function priorPresentation(authority: {
  status?: unknown;
  executable?: unknown;
}) {
  const bucket = governedPriorBucket(authority);
  return { bucket, ...PRIOR_BUCKET_PRESENTATION[bucket] };
}

function priorResolutionReason(
  authority: GovernedPreprocessingPriorAuthority,
  resolution: TreatmentSpecificationResolution | null,
  bucket: GovernedPriorBucket,
): string | null {
  if (bucket === "binding-ready") {
    return resolution?.resolution ?? authority.resolution;
  }
  if (bucket === "retired") {
    return (
      authority.retirementReason ??
      resolution?.retirementReason ??
      resolution?.resolution ??
      null
    );
  }
  if (bucket === "blocked") {
    return (
      authority.blockedReason ??
      resolution?.blockedReason ??
      resolution?.resolution ??
      null
    );
  }
  return null;
}

function priorResolutionCounts(
  authority: GovernedPreprocessingPriorAuthority,
) {
  const derived = {
    executable: 0,
    bindingReady: 0,
    retired: 0,
    blocked: 0,
  };
  authority.bindings.forEach((binding) => {
    const bucket = governedPriorBucket(binding);
    if (bucket === "executable") derived.executable += 1;
    else if (bucket === "binding-ready") derived.bindingReady += 1;
    else if (bucket === "retired") derived.retired += 1;
    else derived.blocked += 1;
  });
  return {
    executable: authority.readyFeatureCount ?? derived.executable,
    bindingReady:
      authority.bindingReadyRequiresWave2EngineFeatureCount ??
      derived.bindingReady,
    retired: authority.retiredFeatureCount ?? derived.retired,
    blocked: authority.blockedFeatureCount ?? derived.blocked,
  };
}

const DEFAULT_QUERY = {
  page: 1,
  pageSize: 25,
  search: "",
  family: "",
  scope: "",
  dataType: "",
  missingness: "",
  outlierPrevalence: "",
  pointInTimeState: "",
  forecastAvailability: "",
  simulationState: "",
  interaction: "",
  status: "",
  sourceAvailability: "",
  governanceStatus: "",
  sortField: "order",
  sortDirection: "asc",
};

type InventoryQuery = typeof DEFAULT_QUERY;

function normalizeFeatureSetState(value: any): FeatureSetState {
  return value?.featureSetState ?? value?.state ?? value ?? {
    expectedChecksum: "NO_CURRENT_FEATURE_SET",
    draft: null,
    registered: [],
    history: [],
  };
}

export function ProjectBoundFeatureEngineering({
  state,
  projectId,
  go,
}: {
  state: CurrentGoldReviewState;
  projectId: string;
  go: (id: string) => void;
}) {
  const [summary, setSummary] = useState<AsyncState<FeatureStudioSummary>>({ status: "loading", data: null, error: null });
  const [authority, setAuthority] = useState<StudioAuthority | null>(null);
  const [inventory, setInventory] = useState<AsyncState<FeatureInventory>>({ status: "loading", data: null, error: null });
  const [featureSets, setFeatureSets] = useState<FeatureSetState>({ expectedChecksum: "NO_CURRENT_FEATURE_SET", draft: null, registered: [], history: [] });
  const [query, setQuery] = useState<InventoryQuery>(DEFAULT_QUERY);
  const [selectedTemplate, setSelectedTemplate] = useState("BASELINE_CORE_48");
  const [draftName, setDraftName] = useState("Baseline Core Gold 48");
  const [notes, setNotes] = useState("Required immutable baseline for chronological comparison.");
  const [defaultTransformation, setDefaultTransformation] = useState("RETAIN_RAW");
  const [transformationOverrides, setTransformationOverrides] = useState<Record<string, string[]>>({});
  const [selectedFeatures, setSelectedFeatures] = useState<string[]>([]);
  const [editorDirty, setEditorDirty] = useState(true);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [detail, setDetail] = useState<FeatureInventoryRow | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const detailButton = useRef<HTMLButtonElement | null>(null);
  const [mutation, setMutation] = useState<{ busy: boolean; error: string | null; message: string | null }>({ busy: false, error: null, message: null });

  const loadSummary = useCallback(async (signal?: AbortSignal) => {
    setSummary((current) => ({ ...current, status: "loading", error: null }));
    try {
      const response = await fetchFeatureStudioSummary(projectId, signal);
      setAuthority(response.authority);
      setSummary({ status: "ready", data: response.data, error: null });
      setFeatureSets(normalizeFeatureSetState(response.data.featureSetState));
    } catch (error) {
      if (signal?.aborted) return;
      setSummary({ status: "error", data: null, error: error instanceof Error ? error.message : "Feature Engineering authority could not be loaded." });
    }
  }, [projectId]);

  const loadInventory = useCallback(async (currentQuery: InventoryQuery, signal?: AbortSignal) => {
    setInventory((current) => ({ ...current, status: "loading", error: null }));
    try {
      const response = await fetchFeatureInventory(projectId, currentQuery, signal);
      setInventory({ status: "ready", data: response.data, error: null });
    } catch (error) {
      if (signal?.aborted) return;
      setInventory({ status: "error", data: null, error: error instanceof Error ? error.message : "Feature inventory could not be loaded." });
    }
  }, [projectId]);

  useEffect(() => {
    const controller = new AbortController();
    void loadSummary(controller.signal);
    return () => controller.abort();
  }, [loadSummary]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void loadInventory(query, controller.signal), 180);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [loadInventory, query]);

  const templates = summary.data?.recommendedSets ?? [];
  const template = templates.find((item) => item.setId === selectedTemplate) ?? templates[0];

  useEffect(() => {
    if (!template) return;
    setSelectedFeatures(template.orderedFeatures);
    setDraftName(template.name);
    setNotes(template.description);
    setTransformationOverrides({});
    setEditorDirty(true);
  }, [template?.setId]);

  const refreshFeatureSets = useCallback(async () => {
    const response = await fetchFeatureSetState(projectId);
    setFeatureSets(normalizeFeatureSetState(response.data));
  }, [projectId]);

  const saveDraft = async () => {
    if (!authority || !template) return;
    setMutation({ busy: true, error: null, message: null });
    try {
      const featureSetKey = template.setId === "CUSTOM"
        ? `CUSTOM.${draftName.trim().toUpperCase().replace(/[^A-Z0-9_.-]+/g, "_").replace(/^_+|_+$/g, "") || "UNTITLED"}`
        : template.setId;
      const priorForKey = featureSets.history.find((item) => item.featureSetKey === featureSetKey);
      const response = await mutateFeatureSet(projectId, "draft", {
        authorityKey: authority.authorityKey,
        expectedChecksum: priorForKey?.checksum ?? "NO_CURRENT_FEATURE_SET",
        recommendedSetId: template.setId,
        featureSetKey,
        name: draftName.trim(),
        description: template.description,
        orderedFeatures: selectedFeatures,
        transformationContracts: { defaultNumeric: defaultTransformation, ...transformationOverrides },
        interactionContracts: template.interactionContracts,
        outlierPolicyId: summary.data?.treatmentPolicies.outlier.policyId,
        missingPolicyId: summary.data?.treatmentPolicies.missing.policyId,
        notes: notes.trim(),
        fittingRule: "FIT_INDEPENDENTLY_WITHIN_EACH_CHRONOLOGICAL_TRAINING_FOLD",
      });
      setFeatureSets(normalizeFeatureSetState(response.data));
      setEditorDirty(false);
      setMutation({ busy: false, error: null, message: "Immutable feature-set draft saved." });
    } catch (error) {
      setMutation({ busy: false, error: error instanceof Error ? error.message : "Draft save failed.", message: null });
    }
  };

  const registerDraft = async () => {
    if (!authority || !featureSets.draft) return;
    setMutation({ busy: true, error: null, message: null });
    try {
      const response = await mutateFeatureSet(projectId, "register", {
        authorityKey: authority.authorityKey,
        expectedChecksum: featureSets.draft.checksum,
        featureSetId: featureSets.draft.featureSetId,
        notes: notes.trim(),
      });
      setFeatureSets(normalizeFeatureSetState(response.data));
      setMutation({ busy: false, error: null, message: "Feature set registered for later Model Laboratory comparison. No model was fit." });
      await loadSummary();
    } catch (error) {
      setMutation({ busy: false, error: error instanceof Error ? error.message : "Registration failed.", message: null });
    }
  };

  const retire = async (item: FeatureSetVersion) => {
    if (!authority) return;
    setMutation({ busy: true, error: null, message: null });
    try {
      const response = await mutateFeatureSet(projectId, "retire", {
        authorityKey: authority.authorityKey,
        expectedChecksum: item.checksum,
        featureSetId: item.featureSetId,
      });
      setFeatureSets(normalizeFeatureSetState(response.data));
      setMutation({ busy: false, error: null, message: `${item.name} retired without deleting its immutable history.` });
    } catch (error) {
      setMutation({ busy: false, error: error instanceof Error ? error.message : "Retirement failed.", message: null });
    }
  };

  const inspect = async (row: FeatureInventoryRow, trigger: HTMLButtonElement) => {
    detailButton.current = trigger;
    setDetail(row);
    setDetailOpen(true);
    try {
      const response = await fetchFeatureDetail(projectId, row.featureName);
      setDetail({ ...row, ...(response.data.feature ?? {}) });
    } catch {
      // The authoritative table row remains an honest limited detail state.
    }
  };

  const families = summary.data?.families ?? [];
  const interactions = summary.data?.interactions ?? [];
  const registered = featureSets.registered ?? [];
  const comparison = registered.filter((item) => compareIds.includes(item.featureSetId));
  const availabilityBySeason = useMemo(() => {
    const rows = summary.data?.visualizations.featureAvailabilityBySeason ?? [];
    const grouped = new Map<number, number[]>();
    rows.forEach((row) => grouped.set(row.season, [...(grouped.get(row.season) ?? []), row.coveragePercent]));
    return [...grouped.entries()].sort(([left], [right]) => left - right).map(([season, values]) => ({
      label: String(season),
      value: values.reduce((total, value) => total + value, 0) / Math.max(1, values.length),
    }));
  }, [summary.data?.visualizations.featureAvailabilityBySeason]);

  if (state.status !== "ready" || !state.review) {
    return <StudioError title="Project-bound authority unavailable" message={state.error || "The accepted Current Gold review is still loading."} />;
  }
  if (summary.status === "loading" && !summary.data) return <StudioLoading label="Loading the project-bound candidate library…" />;
  if (summary.status === "error" || !summary.data || !authority) return <StudioError title="Feature Engineering is held closed" message={summary.error || "The project-bound feature authority was incomplete."} />;
  const s = summary.data.summary;
  const outlierPolicyAdopted =
    adoptedPolicyLabel(summary.data.treatmentPolicies.outlier) !== "Not adopted";
  const missingPolicyAdopted =
    adoptedPolicyLabel(summary.data.treatmentPolicies.missing) !== "Not adopted";
  const treatmentRegistrationReady =
    outlierPolicyAdopted &&
    missingPolicyAdopted &&
    summary.data.treatmentSpecificationDraft === null;

  return (
    <div className="min-w-0 space-y-4" data-testid="project-bound-feature-engineering-studio">
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-950 via-slate-900 to-cyan-950 p-5 text-white shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-cyan-300">Step 06 · Project-bound decision workspace</div>
            <h2 className="mt-1 text-2xl font-semibold tracking-tight">Feature Engineering Studio</h2>
            <p className="mt-2 text-sm leading-6 text-slate-300">Begin with Core Gold 48 as the baseline, then compare bounded feature-family challengers under the same chronological folds.</p>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
            <DarkMetric label="Baseline" value="Core Gold 48" />
            <DarkMetric label="Candidate library" value={`${fmtInt(s.totalCandidateCount)} predictors`} />
            <DarkMetric label="Final OOT" value={`${fmtInt(s.finalOotRows)} LOCKED`} />
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2 text-[11px]">
          <Pill label="No global transformation fit" tone="cyan" />
          <Pill label="No model fit or score" tone="emerald" />
          <Pill label="Development evidence only" tone="violet" />
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-7" aria-label="Feature Engineering decision summary">
        <DecisionMetric label="Core predictors" value={fmtInt(s.coreFeatureCount)} detail="Required immutable order" />
        <DecisionMetric label="Contextual candidates" value={fmtInt(s.contextualFeatureCount)} detail={`${fmtInt(s.eligibleContextualCount)} eligible · ${fmtInt(s.inactiveFeatureCount)} inactive · ${fmtInt(s.unavailableFeatureCount)} unavailable`} tone="cyan" />
        <DecisionMetric label="Feature families" value={fmtInt(s.familyCount)} detail="Chronological ablation candidates" />
        <DecisionMetric label="Interactions" value={fmtInt(s.interactionCount)} detail={`${fmtInt(s.materializedInteractionCount)} materialized · ${fmtInt(s.inactiveInteractionCount)} inactive · ${fmtInt(s.unavailableInteractionCount)} unavailable`} />
        <DecisionMetric label="Outlier policy" value={adoptedPolicyLabel(summary.data.treatmentPolicies.outlier)} detail="Latest adopted immutable project policy" />
        <DecisionMetric label="Missing policy" value={adoptedPolicyLabel(summary.data.treatmentPolicies.missing)} detail="Latest adopted immutable project policy" />
        <DecisionMetric label="Registered sets" value={fmtInt(registered.length)} detail="Candidate contracts, not champions" tone="emerald" />
      </section>

      <details className="rounded-2xl border border-slate-200 bg-white" data-testid="feature-engineering-authority">
        <summary className="cursor-pointer px-4 py-3 text-xs font-semibold text-slate-800">Project-bound authority and locked population</summary>
        <dl className="grid gap-3 border-t border-slate-200 p-4 text-xs sm:grid-cols-2 xl:grid-cols-3">
          <AuthorityFact label="Project" value={projectId} />
          <AuthorityFact label="Registered source" value={`${authority.sourceDatasetId} · ${authority.sourceManifestSha}`} />
          <AuthorityFact label="Current Gold" value={`${authority.goldDatasetId} · ${authority.goldManifestSha} · ${fmtInt(state.review.goldAuthority.rowCount)} rows`} />
          <AuthorityFact label="Contextual authority" value={`${authority.contextualDatasetId} · ${authority.contextualManifestSha}`} />
          <AuthorityFact label="Development population" value={`${fmtInt(state.review.goldAuthority.rowCount - state.review.matrix.finalOot.rows)} rows · ${state.review.matrix.development.startDate} → ${state.review.matrix.development.endDate}`} />
          <AuthorityFact label="Final OOT" value={`${fmtInt(state.review.matrix.finalOot.rows)} rows · ${state.review.matrix.finalOot.startDate} → ${state.review.matrix.finalOot.endDate} · LOCKED`} />
        </dl>
      </details>

      <GovernedPriorSummaryPanel
        authority={summary.data.priorAuthority}
        draft={summary.data.treatmentSpecificationDraft}
      />

      <GovernedInteractionSummaryPanel
        authority={summary.data.interactionAuthority}
        draft={summary.data.treatmentSpecificationDraft}
      />

      <Card title="Recommended experimental plan" icon={Sparkles} description="Ablations isolate whether a contextual family adds stable value. Coverage and descriptive association alone do not prove predictive usefulness.">
        <div className="grid gap-3 lg:grid-cols-3">
          <Recommendation title="Required baseline" items={["BASELINE_CORE_48"]} tone="cyan" />
          <Recommendation title="First challengers" items={["CORE_PLUS_CALENDAR", "CORE_PLUS_REST_TRAVEL", "CORE_PLUS_CIRCADIAN", "CORE_PLUS_CALENDAR_TRAVEL"]} tone="emerald" />
          <Recommendation title="Review before use" items={["CORE_PLUS_DIVISION", "FULL_ELIGIBLE_CONTEXTUAL", "Unavailable source-dependent interactions"]} tone="amber" />
        </div>
      </Card>

      <Card title="Seven declared feature families" icon={Layers3} description="Every family preserves exact order, development coverage, forecast-time status, and explicit exclusions.">
        <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
          {families.map((family) => <FamilyCard key={family.familyId} family={family} selected={template?.setId === family.familyId || family.selected} onSelect={() => {
            const candidate = templates.find((item) => item.setId === family.familyId || item.name.includes(family.familyId.replace(/^[A-G]_?/, "")));
            if (candidate) setSelectedTemplate(candidate.setId);
          }} />)}
        </div>
        <FamilyInventoryTable families={families} />
      </Card>

      <Card title="Candidate feature-set builder" icon={Wand2} description="Create immutable, versioned feature-set contracts for later comparison. Registration performs no fitting and selects no champion.">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.7fr)]">
          <div className="space-y-3">
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Recommended template
              <select aria-label="Recommended feature-set template" value={selectedTemplate} onChange={(event) => setSelectedTemplate(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                {templates.map((item) => <option key={item.setId} value={item.setId}>{item.name} · {item.activeFeatureCount} active</option>)}
              </select>
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Feature-set name<input value={draftName} onChange={(event) => { setDraftName(event.target.value); setEditorDirty(true); }} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900" /></label>
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Default fold-local transformation<select value={defaultTransformation} onChange={(event) => { setDefaultTransformation(event.target.value); setEditorDirty(true); }} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900"><option value="RETAIN_RAW">Retain raw</option><option value="STANDARDIZE">Standardization</option><option value="ROBUST_SCALE">Robust scaling</option><option value="FOLD_LOCAL_QUANTILE">Fold-local quantile</option><option value="NO_TRANSFORMATION">No transformation</option></select></label>
            </div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Scientific notes<textarea value={notes} onChange={(event) => { setNotes(event.target.value); setEditorDirty(true); }} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900" /></label>
            <div className="rounded-xl border border-cyan-200 bg-cyan-50 p-3 text-xs leading-5 text-cyan-950"><ShieldCheck size={14} className="mr-1 inline" /> Every transformation rule states: <b>Fit independently within each chronological training fold.</b> Rules are persisted; transformed Gold rows are not.</div>
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={mutation.busy || !draftName.trim()} onClick={saveDraft} className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white disabled:bg-slate-300"><Save size={14} /> Save immutable draft</button>
              <button type="button" disabled={mutation.busy || !featureSets.draft || editorDirty || !treatmentRegistrationReady} title={!treatmentRegistrationReady ? "Adopt an exact blocker-free combined treatment specification before registration." : editorDirty ? "Save this exact editor state before registration." : undefined} onClick={registerDraft} className="inline-flex items-center gap-2 rounded-lg bg-cyan-700 px-3 py-2 text-xs font-semibold text-white disabled:bg-slate-300"><CheckCircle2 size={14} /> Register candidate set</button>
              <button type="button" onClick={() => { setDraftName(`${draftName} copy`); setEditorDirty(true); setMutation({ busy: false, error: null, message: "Draft duplicated in the editor. Save to create a new immutable version." }); }} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700"><Copy size={14} /> Duplicate</button>
              <button type="button" onClick={() => void refreshFeatureSets()} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700"><RefreshCw size={14} /> Reload</button>
            </div>
            {mutation.message ? <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-2 text-xs text-emerald-800">{mutation.message}</p> : null}
            {mutation.error ? <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-2 text-xs text-rose-800">{mutation.error}</p> : null}
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Current draft preview</div>
            <div className="mt-1 text-lg font-semibold text-slate-900">{draftName || "Unnamed feature set"}</div>
            <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <MiniStat label="Ordered features" value={fmtInt(selectedFeatures.length)} />
              <MiniStat label="Unavailable excluded" value={fmtInt(template?.unavailableExclusions.length ?? 0)} />
              <MiniStat label="Simulation state" value={fmtInt(selectedFeatures.filter((name) => name.startsWith("context_")).length)} />
              <MiniStat label="Interaction rules" value={fmtInt(Object.keys(template?.interactionContracts ?? {}).length)} />
            </dl>
            <div className="mt-3 max-h-40 overflow-auto rounded-lg border border-slate-200 bg-white p-2 font-mono text-[10px] leading-4 text-slate-600">{selectedFeatures.join("\n")}</div>
          </div>
        </div>
      </Card>

      <Card title="Registered candidate sets" icon={GitCompareArrows} description="Registered versions are immutable. Select two or more to compare exact membership, transformations, exclusions, and policy lineage.">
        {registered.length ? <div className="grid gap-3 lg:grid-cols-2">{registered.map((item) => <article key={item.featureSetId} className="rounded-xl border border-slate-200 p-3"><div className="flex items-start gap-2"><label className="mt-1"><input aria-label={`Compare ${item.name}`} type="checkbox" checked={compareIds.includes(item.featureSetId)} onChange={() => setCompareIds((current) => current.includes(item.featureSetId) ? current.filter((id) => id !== item.featureSetId) : [...current, item.featureSetId])} /></label><div className="min-w-0 flex-1"><div className="font-semibold text-slate-900">{item.name}</div><div className="text-[10px] uppercase text-slate-500">v{item.version} · {item.status} · {item.orderedFeatures.length} ordered features</div></div><button type="button" title="Retire registered feature set" onClick={() => void retire(item)} className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600"><Trash2 size={14} /></button></div><div className="mt-2 break-all font-mono text-[10px] text-slate-500">{item.checksum}</div></article>)}</div> : <div className="rounded-xl border border-dashed border-slate-300 p-7 text-center text-sm text-slate-500">No candidate set is registered yet. Save and register Core Gold 48 first.</div>}
        {comparison.length >= 2 ? <div className="mt-4 max-w-full overflow-x-auto"><table className="w-full min-w-[760px] text-left text-xs"><caption className="sr-only">Selected immutable feature-set comparison matrix</caption><thead><tr>{["Set", "Version", "Features", "Unavailable exclusions", "Outlier policy", "Missing policy", "Checksum"].map((label) => <th key={label} scope="col" className="border-b border-slate-200 px-2 py-2 uppercase text-slate-500">{label}</th>)}</tr></thead><tbody>{comparison.map((item) => <tr key={item.featureSetId}><th scope="row" className="border-b border-slate-100 px-2 py-2 text-left font-semibold">{item.name}</th><td className="border-b border-slate-100 px-2 py-2">{item.version}</td><td className="border-b border-slate-100 px-2 py-2">{item.orderedFeatures.length}</td><td className="border-b border-slate-100 px-2 py-2">{item.unavailableExclusions.length}</td><td className="border-b border-slate-100 px-2 py-2 font-mono text-[10px]">{item.outlierPolicyId}</td><td className="border-b border-slate-100 px-2 py-2 font-mono text-[10px]">{item.missingPolicyId}</td><td className="max-w-44 truncate border-b border-slate-100 px-2 py-2 font-mono text-[10px]">{item.checksum}</td></tr>)}</tbody></table></div> : null}
        {featureSets.history.length ? <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50"><summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-800">Immutable version history · {featureSets.history.length} records</summary><div className="max-w-full overflow-x-auto border-t border-slate-200"><table className="w-full min-w-[760px] text-left text-[11px]"><caption className="sr-only">Immutable feature-set version and supersession history</caption><thead><tr>{["Key", "Name", "Version", "State", "Features", "Transform scope", "Checksum"].map((label) => <th key={label} scope="col" className="px-2 py-2 uppercase text-slate-500">{label}</th>)}</tr></thead><tbody>{featureSets.history.map((item) => <tr key={item.featureSetId}><td className="border-t border-slate-200 px-2 py-2 font-mono text-[10px]">{item.featureSetKey}</td><th scope="row" className="border-t border-slate-200 px-2 py-2 text-left font-semibold">{item.name}</th><td className="border-t border-slate-200 px-2 py-2">{item.version}</td><td className="border-t border-slate-200 px-2 py-2">{human(item.status)}</td><td className="border-t border-slate-200 px-2 py-2">{item.orderedFeatures.length}</td><td className="border-t border-slate-200 px-2 py-2">Training fold only</td><td className="max-w-52 truncate border-t border-slate-200 px-2 py-2 font-mono text-[9px]" title={item.checksum}>{item.checksum}</td></tr>)}</tbody></table></div></details> : null}
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Family coverage heatmap" icon={Columns3} description="Development-only availability. High coverage is not evidence of predictive value.">
          <BarChart categories={(summary.data.visualizations.familyCoverage ?? []).map((item) => item.family)} values={(summary.data.visualizations.familyCoverage ?? []).map((item) => item.coveragePercent)} horizontal height={260} valueFmt={(value) => `${value.toFixed(1)}%`} />
        </Card>
        <Card title="Missingness by family" icon={AlertTriangle} description="Physical missingness remains separate from cold start and source-era unavailability.">
          <BarChart categories={(summary.data.visualizations.familyMissingness ?? []).map((item) => item.family)} values={(summary.data.visualizations.familyMissingness ?? []).map((item) => item.missingPercent)} horizontal height={260} color="#d97706" valueFmt={(value) => `${value.toFixed(1)}%`} />
        </Card>
      </div>

      <Card title="Feature construction diagnostics" icon={Columns3} description="Bounded development-only views support construction decisions; they do not choose a winner and never inspect final-OOT outcomes.">
        <div className="grid gap-4 xl:grid-cols-2">
          <section className="rounded-xl border border-slate-200 p-3" aria-label="Feature availability by season">
            <h3 className="text-xs font-semibold text-slate-900">Feature availability by season</h3>
            <p className="mt-1 text-[11px] leading-4 text-slate-500">Mean declared-family coverage from development rows only.</p>
            {availabilityBySeason.length ? <BarChart categories={availabilityBySeason.map((item) => item.label)} values={availabilityBySeason.map((item) => item.value)} height={220} valueFmt={(value) => `${value.toFixed(1)}%`} /> : <DiagnosticEmpty label="NOT_EVALUATED — no season aggregate was published." />}
          </section>
          <section className="rounded-xl border border-slate-200 p-3" aria-label="Fold-safe transformation preview">
            <h3 className="text-xs font-semibold text-slate-900">Fold-safe transformation preview</h3>
            <ol className="mt-3 grid gap-2 text-[11px] leading-4 text-slate-700 sm:grid-cols-3">
              <li className="rounded-lg bg-slate-50 p-2"><b>1 · Select rules</b><br />Raw Gold remains immutable.</li>
              <li className="rounded-lg bg-cyan-50 p-2"><b>2 · Fit in training</b><br />Each fold learns its own parameters.</li>
              <li className="rounded-lg bg-emerald-50 p-2"><b>3 · Apply forward</b><br />Validation receives training-fitted rules only.</li>
            </ol>
            <p className="mt-3 rounded-lg border border-violet-200 bg-violet-50 p-2 text-[11px] text-violet-900">Final OOT stays locked; no transformation statistic is fit here.</p>
          </section>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <DiagnosticState title="Stability through time" state="ON-DEMAND" text="Open a feature drawer for development-only temporal coverage and month/season missingness." />
          <DiagnosticState title="Redundancy clusters" state="ON-DEMAND" text="Only registered development-only redundancy evidence is shown in a feature drawer; absent evidence is labeled NOT_EVALUATED." />
          <DiagnosticState title="Numeric / categorical gallery" state="PROJECT-BOUND" text="Use data-type filters, range/cardinality, and feature details without returning to the global EDA matrix." />
          <DiagnosticState title="Target stratification" state="DESCRIPTIVE ONLY" text="Displayed per feature only when the backend publishes development-only class aggregates." />
        </div>
      </Card>

      <Card title="Project-bound feature inventory" icon={Filter} description="All 254 candidates, with project authority, treatment-policy handoff, forecast availability, and exact exclusions.">
        <FeatureFilters query={query} setQuery={setQuery} families={families} />
        <AdvancedFeatureFilters query={query} setQuery={setQuery} />
        {inventory.status === "loading" && !inventory.data ? <div className="p-6"><Spinner label="Loading development-only feature evidence…" /></div> : null}
        {inventory.status === "error" ? <p role="alert" className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{inventory.error}</p> : null}
        {inventory.data ? <FeatureTable inventory={inventory.data} query={query} setQuery={setQuery} selectedFeatures={selectedFeatures} setSelectedFeatures={(features) => { setSelectedFeatures(features); setEditorDirty(true); }} transformationOverrides={transformationOverrides} setTransformationOverrides={(overrides) => { setTransformationOverrides(overrides); setEditorDirty(true); }} inspect={inspect} /> : null}
      </Card>

      <Card title="Transformation contracts" icon={ShieldCheck} description="Only compatible rules are offered. Identifiers are excluded, categorical values are never mean-imputed, negative-domain features require governed offsets, and global target encoding is unavailable.">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{[
          ["Numeric", "Retain raw · log1p when domain permits · standardization · robust scaling · fold-local quantile/bounded transform"],
          ["Categorical", "Unknown handling · one-hot encoding · no global target encoding"],
          ["Binary / flags", "Binary passthrough · retain missing/insufficient-history indicator"],
          ["Treatment handoff", `Outlier ${adoptedPolicyLabel(summary.data.treatmentPolicies.outlier)} · Missing ${adoptedPolicyLabel(summary.data.treatmentPolicies.missing)}`],
        ].map(([label, text]) => <div key={label} className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="text-xs font-semibold text-slate-900">{label}</div><p className="mt-1 text-[11px] leading-5 text-slate-600">{text}</p></div>)}</div>
      </Card>

      <Card title="Bounded interaction workspace" icon={Layers3} description="All declared interactions remain visible with governed formula, parent-first treatment order, and fail-closed status. Inactive or source-unavailable interactions remain nonselectable.">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {interactions.map((item) => {
            const ready =
              item.executableStatus === "READY_GOVERNED_INTERACTION_V1" ||
              item.status === "MATERIALIZED";
            const parents = item.orderedParents.length
              ? item.orderedParents
              : item.parentVariables;
            return (
              <article
                key={item.name}
                className={`min-w-0 rounded-xl border p-3 ${
                  ready
                    ? "border-emerald-200 bg-emerald-50/40"
                    : "border-amber-200 bg-amber-50/50"
                }`}
                data-testid="feature-studio-governed-interaction"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <code className="min-w-0 break-all text-xs font-semibold text-slate-900">
                    {item.name}
                  </code>
                  <Pill
                    label={item.executableStatus}
                    tone={ready ? "emerald" : "amber"}
                  />
                </div>
                <p className="mt-2 text-[11px] leading-4 text-slate-600">
                  {item.reason || "No additional warning."}
                </p>
                <dl className="mt-2 grid grid-cols-2 gap-2 text-[10px]">
                  <MiniStat label="Coverage" value={fmtPct(item.coveragePercent)} />
                  <MiniStat label="Missing" value={fmtPct(item.missingPercent)} />
                </dl>
                <div className="mt-2 break-words font-mono text-[10px] text-slate-600">
                  <b>Formula {item.formulaVersion || "NOT_REPORTED"}:</b>{" "}
                  {item.formula || "NOT_AVAILABLE"}
                </div>
                <div className="mt-1 break-words font-mono text-[10px] text-slate-500">
                  <b>Ordered parents:</b>{" "}
                  {parents.length ? parents.join(" → ") : "NOT_AVAILABLE"}
                </div>
                <div className="mt-1 text-[10px] text-slate-600">
                  <b>Operation order:</b>{" "}
                  {item.operationOrder.length
                    ? item.operationOrder.join(" → ")
                    : "NOT_REPORTED"}
                </div>
                <div className="mt-1 text-[10px] text-slate-600">
                  PIT {item.pointInTimeStatus || "NOT_EVALUATED"} · Fold-local {item.foldLocal}
                </div>
                <details className="mt-2 rounded border border-white bg-white/70 p-2">
                  <summary className="cursor-pointer text-[9px] font-semibold uppercase text-slate-500">
                    Parent treatment authorities · {item.parentTreatmentAuthorities.length}
                  </summary>
                  <ol className="mt-1 space-y-1 pl-4 text-[9px] leading-4 text-slate-600">
                    {item.parentTreatmentAuthorities.length ? (
                      item.parentTreatmentAuthorities.map((parent, index) => (
                        <li key={`${item.name}:authority:${index}`} className="break-words">
                          {interactionAuthorityValue(parent)}
                        </li>
                      ))
                    ) : (
                      <li>NOT_REPORTED</li>
                    )}
                  </ol>
                </details>
                {item.blockedReason ? (
                  <p className="mt-2 rounded border border-amber-300 bg-white p-2 text-[10px] text-amber-950">
                    <b>BLOCKED:</b> {item.blockedReason}
                  </p>
                ) : null}
                <div className="mt-2 text-[10px] text-slate-600">
                  Selected sets: {item.selectedCandidateSets.length ? item.selectedCandidateSets.join(", ") : "None"}
                </div>
              </article>
            );
          })}
        </div>
      </Card>

      <section className="rounded-2xl border border-slate-200 bg-white p-4" data-testid="feature-engineering-audit-strip">
        <div className="flex flex-wrap items-center gap-2 text-xs"><History size={15} className="text-cyan-700" /><b>Registration and audit</b><Pill label="Current Gold unchanged" tone="emerald" /><Pill label="Final OOT target inaccessible" tone="violet" /><Pill label="Model activity 0" tone="cyan" /><span className="ml-auto max-w-full break-all font-mono text-[10px] text-slate-400">{authority.reviewDigest}</span></div>
        <div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => go("split")} disabled={!registered.length} className="inline-flex items-center gap-2 rounded-lg bg-cyan-700 px-4 py-2 text-xs font-semibold text-white disabled:bg-slate-300"><Check size={14} /> Continue to Split &amp; Balance</button><span className="self-center text-[11px] text-slate-500">Registered candidate sets continue to Split &amp; Balance; Model Laboratory resolves the exact project-bound feature, split, and treatment authorities before enabling execution.</span></div>
      </section>

      <CockpitDrawer open={detailOpen} onClose={() => setDetailOpen(false)} title={detail ? detail.friendlyLabel : "Feature detail"} description={detail?.featureName ?? "Development-only feature evidence"} eyebrow="Project-bound feature review" returnFocusRef={detailButton} widthClassName="max-w-4xl" testId="feature-engineering-detail-drawer">
        {detail ? <FeatureDetail row={detail} /> : <Spinner label="Loading feature details…" />}
      </CockpitDrawer>
    </div>
  );
}

function StudioLoading({ label }: { label: string }) {
  return <div className="rounded-2xl border border-slate-200 bg-white p-8"><Spinner label={label} /></div>;
}

function StudioError({ title, message }: { title: string; message: string }) {
  return <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5" role="alert"><div className="flex items-center gap-2 font-semibold text-rose-900"><Lock size={17} /> {title}</div><p className="mt-2 text-sm leading-6 text-rose-800">{message}</p></section>;
}

function DarkMetric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2"><div className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">{label}</div><div className="mt-0.5 font-semibold text-white">{value}</div></div>;
}

function DecisionMetric({ label, value, detail, tone = "slate" }: { label: string; value: string; detail: string; tone?: "slate" | "cyan" | "emerald" }) {
  const classes = tone === "cyan" ? "border-cyan-200 bg-cyan-50/40" : tone === "emerald" ? "border-emerald-200 bg-emerald-50/40" : "border-slate-200 bg-white";
  return <div className={`rounded-xl border p-3 ${classes}`}><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 text-2xl font-semibold tabular-nums text-slate-950">{value}</div><div className="mt-1 text-[11px] leading-4 text-slate-500">{detail}</div></div>;
}

function Recommendation({ title, items, tone }: { title: string; items: string[]; tone: "cyan" | "emerald" | "amber" }) {
  const classes = tone === "cyan" ? "border-cyan-200 bg-cyan-50" : tone === "emerald" ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50";
  return <div className={`rounded-xl border p-3 ${classes}`}><div className="text-xs font-semibold uppercase tracking-wide text-slate-800">{title}</div><ul className="mt-2 space-y-1 text-xs text-slate-700">{items.map((item) => <li key={item}>• {human(item)}</li>)}</ul></div>;
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-slate-200 bg-white p-2"><dt className="text-[9px] font-semibold uppercase text-slate-400">{label}</dt><dd className="mt-0.5 font-semibold text-slate-900">{value}</dd></div>;
}

function AuthorityFact({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt className="text-[9px] font-semibold uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-1 break-all font-mono text-[10px] leading-4 text-slate-700">{value}</dd></div>;
}

function DiagnosticEmpty({ label }: { label: string }) {
  return <div className="mt-4 rounded-lg border border-dashed border-slate-300 p-6 text-center text-[11px] font-semibold text-slate-500">{label}</div>;
}

function DiagnosticState({ title, state, text }: { title: string; state: string; text: string }) {
  return <section className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-xs font-semibold text-slate-900">{title}</h3><Pill label={state} tone="cyan" /></div><p className="mt-2 text-[11px] leading-5 text-slate-600">{text}</p></section>;
}

function GovernedPriorSummaryPanel({
  authority,
  draft,
}: {
  authority: GovernedPreprocessingPriorAuthority | null;
  draft: TreatmentSpecificationDraftAuthority | null;
}) {
  const priorAuthority = authority ?? draft?.priorAuthority ?? null;
  if (!priorAuthority) return null;
  const counts = priorResolutionCounts(priorAuthority);
  return (
    <section
      className="rounded-2xl border border-violet-200 bg-violet-50/40 p-4"
      data-testid="feature-engineering-governed-prior-authority"
    >
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-violet-800">
            Governed derived preprocessing
          </div>
          <h3 className="mt-1 text-sm font-semibold text-slate-950">
            {priorAuthority.authorityName}
          </h3>
          <p className="mt-1 max-w-4xl text-[11px] leading-5 text-slate-600">
            Read-only visibility into the project-bound prior authority. These
            posterior, effective-sample-size, reliability, and uncertainty
            fields are preprocessing outputs—not separately selectable raw
            predictors. This page does not fit, tune, register, or adopt the
            prior authority.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5 text-[10px] font-semibold">
          <Pill label={`Fold-local ${priorAuthority.foldLocal}`} tone="emerald" />
          <Pill label={`PIT ${priorAuthority.pointInTime}`} tone="emerald" />
          {draft ? <Pill label={draft.status} tone="violet" /> : null}
        </div>
      </div>
      <dl className="mt-3 grid gap-3 text-[11px] sm:grid-cols-2 xl:grid-cols-4">
        <AuthorityFact
          label="Authority ID"
          value={priorAuthority.authorityId}
        />
        <AuthorityFact label="Method" value={priorAuthority.method} />
        <AuthorityFact label="Hierarchy" value={priorHierarchy(priorAuthority)} />
        <AuthorityFact
          label="Feature resolution"
          value={`${fmtInt(counts.executable)} EXECUTABLE V1 · ${fmtInt(counts.bindingReady)} BINDING READY / WAVE 2 · ${fmtInt(counts.retired)} RETIRED · ${fmtInt(counts.blocked)} BLOCKED / MISSING EVIDENCE · ${fmtInt(priorAuthority.featureCount)} governed rows`}
        />
        {draft ? (
          <AuthorityFact
            label="Draft identity"
            value={`${draft.specificationDraftId} · v${draft.specificationVersion ?? "—"}`}
          />
        ) : null}
        {draft ? (
          <AuthorityFact
            label="Manifest checksum"
            value={draft.manifestChecksum}
          />
        ) : null}
        {Object.entries(draft?.executionSummary ?? {})
          .slice(0, 2)
          .map(([label, value]) => (
            <AuthorityFact
              key={label}
              label={`Execution · ${human(label)}`}
              value={
                value && typeof value === "object"
                  ? JSON.stringify(value)
                  : String(value ?? "—")
              }
            />
          ))}
      </dl>
    </section>
  );
}

function interactionAuthorityValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "NOT_REPORTED");
}

function GovernedInteractionBinding({
  binding,
}: {
  binding: GovernedInteractionAuthority;
}) {
  const ready = binding.status === "READY_GOVERNED_INTERACTION_V1";
  return (
    <article
      className={`min-w-0 rounded-xl border p-3 ${
        ready
          ? "border-emerald-200 bg-emerald-50/50"
          : "border-amber-200 bg-amber-50/60"
      }`}
      data-testid={`feature-engineering-governed-interaction-${ready ? "ready" : "blocked"}`}
    >
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <code className="break-all text-[11px] font-semibold text-slate-950">
            {binding.featureName}
          </code>
          <div className="mt-1 break-all text-[9px] text-slate-500">
            Backend {binding.backendFeatureIdentity} · {binding.formulaVersion}
          </div>
        </div>
        <Pill label={binding.status} tone={ready ? "emerald" : "amber"} />
      </div>
      <dl className="mt-3 grid gap-2 text-[10px] leading-4 sm:grid-cols-2">
        <MiniStat label="Exact formula" value={binding.formula} />
        <MiniStat
          label="Ordered parents"
          value={binding.orderedParents.join(" → ") || "NOT_REPORTED"}
        />
        <MiniStat
          label="Operation order"
          value={binding.operationOrder.join(" → ") || "NOT_REPORTED"}
        />
        <MiniStat
          label="Fold-local / PIT"
          value={`Fold-local ${binding.foldLocal} · PIT ${binding.pointInTime}`}
        />
      </dl>
      <details className="mt-2 rounded-lg border border-white bg-white/70 p-2">
        <summary className="cursor-pointer text-[9px] font-semibold uppercase text-slate-600">
          Parent treatment authorities · {binding.parentTreatmentAuthorities.length}
        </summary>
        <ol className="mt-1 space-y-1 pl-4 text-[9px] leading-4 text-slate-700">
          {binding.parentTreatmentAuthorities.length ? (
            binding.parentTreatmentAuthorities.map((parent, index) => (
              <li key={`${binding.featureName}:parent:${index}`} className="break-words">
                {interactionAuthorityValue(parent)}
              </li>
            ))
          ) : (
            <li>NOT_REPORTED</li>
          )}
        </ol>
      </details>
      {!ready && binding.blockedReason ? (
        <p className="mt-2 rounded-lg border border-amber-300 bg-white p-2 text-[10px] leading-4 text-amber-950">
          <b>BLOCKED:</b> {binding.blockedReason}
        </p>
      ) : null}
    </article>
  );
}

function GovernedInteractionSummaryPanel({
  authority,
  draft,
}: {
  authority: GovernedInteractionAuthoritySummary | null;
  draft: TreatmentSpecificationDraftAuthority | null;
}) {
  if (!authority) return null;
  const execution = draft?.executionSummary ?? {};
  const before = Number(
    execution.interactionBlockersBefore ?? authority.featureCount ?? 0,
  );
  const cleared = Number(
    execution.interactionBlockersCleared ?? authority.readyFeatureCount ?? 0,
  );
  const remaining = Number(
    execution.interactionBlockersRemaining ?? authority.blockedFeatureCount ?? 0,
  );
  const semanticRemaining = Number(
    execution.semanticFieldsRemaining ?? execution.semanticReview ?? 0,
  );
  const rivalryHeld = Number(
    execution.rivalryFieldsHeldClosed ?? execution.additionalHeldClosed ?? 0,
  );
  const totalBlockers = Number(execution.blocked ?? 0);
  return (
    <section
      className="rounded-2xl border border-cyan-200 bg-cyan-50/40 p-4"
      data-testid="feature-engineering-governed-interaction-authority"
    >
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-800">
            Governed interaction recomputation
          </div>
          <h3 className="mt-1 text-sm font-semibold text-slate-950">
            {authority.authorityName}
          </h3>
          <p className="mt-1 max-w-4xl text-[11px] leading-5 text-slate-600">
            Exact formulas, ordered parent lineage, parent treatment
            authorities, and parent-first operation order are inspectable as
            read-only preprocessing evidence. This page does not fit, tune,
            register, or adopt this authority.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5 text-[10px] font-semibold">
          <Pill label={`Fold-local ${authority.foldLocal}`} tone="emerald" />
          <Pill label={`PIT ${authority.pointInTime}`} tone="emerald" />
          <Pill label={draft?.status ?? "DRAFT"} tone="violet" />
        </div>
      </div>
      <dl className="mt-3 grid gap-3 text-[11px] sm:grid-cols-2 xl:grid-cols-4">
        <AuthorityFact label="Authority ID" value={authority.authorityId} />
        <AuthorityFact
          label="Authority checksum"
          value={authority.authorityChecksum}
        />
        <AuthorityFact
          label="Interactions before / cleared / remaining"
          value={`${fmtInt(before)} / ${fmtInt(cleared)} / ${fmtInt(remaining)}`}
        />
        <AuthorityFact
          label="Remaining governance"
          value={`${fmtInt(semanticRemaining)} semantic · ${fmtInt(rivalryHeld)} rivalry held · ${fmtInt(totalBlockers)} total blockers`}
        />
      </dl>
      <details open className="mt-3 rounded-lg border border-cyan-100 bg-white/70 p-2">
        <summary className="cursor-pointer text-[10px] font-semibold text-slate-900">
          Exact governed interactions · {authority.bindings.length}
        </summary>
        <div className="mt-2 grid max-h-[36rem] gap-2 overflow-y-auto lg:grid-cols-2">
          {authority.bindings.map((binding) => (
            <GovernedInteractionBinding
              key={binding.featureName}
              binding={binding}
            />
          ))}
        </div>
      </details>
    </section>
  );
}

function FamilyCard({ family, selected, onSelect }: { family: FeatureFamily; selected: boolean; onSelect: () => void }) {
  return <article className={`rounded-xl border p-4 ${selected ? "border-cyan-500 bg-cyan-50/50 ring-1 ring-cyan-200" : "border-slate-200 bg-white"}`}><div className="flex items-start gap-2"><div className="min-w-0 flex-1"><div className="text-[10px] font-semibold uppercase text-cyan-800">{family.familyId}</div><h3 className="mt-0.5 font-semibold text-slate-950">{family.friendlyName}</h3></div><button type="button" onClick={onSelect} aria-pressed={selected} className={`inline-flex h-6 w-6 items-center justify-center rounded border ${selected ? "border-cyan-600 bg-cyan-600 text-white" : "border-slate-300 text-transparent"}`} aria-label={`Select ${family.friendlyName}`}>{selected ? <Check size={14} /> : "·"}</button></div><dl className="mt-3 grid grid-cols-3 gap-1 text-center"><MiniStat label="Ordered" value={fmtInt(family.featureCount)} /><MiniStat label="Eligible" value={fmtInt(family.eligibleFeatureCount)} /><MiniStat label="Inactive" value={fmtInt(family.inactiveFeatureCount + family.unavailableFeatureCount)} /></dl><p className="mt-2 text-[11px] leading-4 text-slate-600">Coverage {fmtPct(family.physicalMissingPercent == null ? null : 100 - family.physicalMissingPercent)} · cold start {fmtPct(family.coldStartExposurePercent)} · {family.interactionCount} interactions</p><p className="mt-1 text-[11px] leading-4 text-slate-600">Forecast {human(family.forecastTimeAvailability)} · {human(family.pointInTimeStatus)} · {family.modelCompatibility.join(", ") || "Compatibility not declared"}</p>{family.excludedFeatures.length ? <details className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-[10px] text-amber-950"><summary className="cursor-pointer font-semibold">{family.excludedFeatures.length} exact exclusion{family.excludedFeatures.length === 1 ? "" : "s"}</summary><ul className="mt-1 space-y-1">{family.excludedFeatures.map((item) => <li key={item.feature}><code>{item.feature}</code> — {item.reason}</li>)}</ul></details> : null}{family.governanceWarnings.length ? <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-[10px] leading-4 text-amber-900">{family.governanceWarnings.join(" · ")}</p> : null}</article>;
}

function FamilyInventoryTable({ families }: { families: FeatureFamily[] }) {
  type SortField = "family" | "featureCount" | "eligibleFeatureCount" | "inactiveFeatureCount" | "sourceUnavailableCount" | "physicalMissingPercent" | "coldStartExposurePercent" | "interactionCount";
  const [sortField, setSortField] = useState<SortField>("family");
  const [sortDirection, setSortDirection] = useState<"ascending" | "descending">("ascending");
  const ordered = [...families].sort((left, right) => {
    const leftValue = sortField === "family" ? left.familyId : (left[sortField] ?? Number.POSITIVE_INFINITY);
    const rightValue = sortField === "family" ? right.familyId : (right[sortField] ?? Number.POSITIVE_INFINITY);
    const result = typeof leftValue === "string" ? leftValue.localeCompare(String(rightValue)) : Number(leftValue) - Number(rightValue);
    return sortDirection === "ascending" ? result : -result;
  });
  const sortable: { field: SortField; label: string }[] = [
    { field: "family", label: "Family" },
    { field: "featureCount", label: "Ordered" },
    { field: "eligibleFeatureCount", label: "Eligible" },
    { field: "inactiveFeatureCount", label: "Inactive" },
    { field: "sourceUnavailableCount", label: "Unavailable" },
    { field: "physicalMissingPercent", label: "Physical missing" },
    { field: "coldStartExposurePercent", label: "Cold start" },
    { field: "interactionCount", label: "Interactions" },
  ];
  const chooseSort = (field: SortField) => { setSortDirection(sortField === field && sortDirection === "ascending" ? "descending" : "ascending"); setSortField(field); };
  return <div className="mt-4 max-w-full overflow-x-auto rounded-xl border border-slate-200"><table className="w-full min-w-[1180px] text-left text-[11px]"><caption className="sr-only">Sortable review table for the seven declared project-bound feature families</caption><thead className="bg-slate-50"><tr>{sortable.map(({ field, label }) => <th key={field} scope="col" aria-sort={sortField === field ? sortDirection : "none"} className="border-b border-slate-200 px-2 py-2 font-semibold uppercase text-slate-500"><button type="button" onClick={() => chooseSort(field)} className="inline-flex items-center gap-1 rounded focus:outline-none focus:ring-2 focus:ring-cyan-500">{label}<ArrowUpDown size={10} /></button></th>)}{["Forecast / PIT", "Model compatibility", "Exact exclusions"].map((label) => <th key={label} scope="col" className="border-b border-slate-200 px-2 py-2 font-semibold uppercase text-slate-500">{label}</th>)}</tr></thead><tbody>{ordered.map((family) => <tr key={family.familyId} className="align-top"><th scope="row" className="border-b border-slate-100 px-2 py-2"><div className="font-mono text-[10px] text-cyan-800">{family.familyId}</div><div className="font-semibold text-slate-900">{family.friendlyName}</div></th><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(family.featureCount)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(family.eligibleFeatureCount)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(family.inactiveFeatureCount)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(family.sourceUnavailableCount)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtPct(family.physicalMissingPercent)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtPct(family.coldStartExposurePercent)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtInt(family.interactionCount)}</td><td className="max-w-56 border-b border-slate-100 px-2 py-2">{human(family.forecastTimeAvailability)}<div className="mt-1 text-slate-500">{human(family.pointInTimeStatus)}</div></td><td className="max-w-52 border-b border-slate-100 px-2 py-2">{family.modelCompatibility.join(", ") || "—"}</td><td className="max-w-72 border-b border-slate-100 px-2 py-2">{family.excludedFeatures.length ? family.excludedFeatures.map((item) => <div key={item.feature}><code>{item.feature}</code>: {item.reason}</div>) : "None"}</td></tr>)}</tbody></table></div>;
}

function FeatureFilters({ query, setQuery, families }: { query: InventoryQuery; setQuery: (query: InventoryQuery) => void; families: FeatureFamily[] }) {
  const patch = (value: Partial<InventoryQuery>) => setQuery({ ...query, ...value, page: value.page ?? 1 });
  return <div className="mb-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-6" data-testid="feature-inventory-filters"><label className="relative xl:col-span-2"><Search size={13} className="absolute left-3 top-2.5 text-slate-400" /><input aria-label="Search feature inventory" value={query.search} onChange={(event) => patch({ search: event.target.value })} placeholder="Search name, definition, or source" className="w-full rounded-lg border border-slate-300 py-2 pl-8 pr-3 text-xs" /></label><select aria-label="Feature family filter" value={query.family} onChange={(event) => patch({ family: event.target.value })} className="rounded-lg border border-slate-300 px-2 py-2 text-xs"><option value="">All families</option>{families.map((item) => <option key={item.familyId} value={item.familyId}>{item.friendlyName}</option>)}</select><select aria-label="Core contextual filter" value={query.scope} onChange={(event) => patch({ scope: event.target.value })} className="rounded-lg border border-slate-300 px-2 py-2 text-xs"><option value="">Core + contextual</option><option value="CORE">Core Gold 48</option><option value="CONTEXTUAL">Contextual</option></select><select aria-label="Feature status filter" value={query.status} onChange={(event) => patch({ status: event.target.value })} className="rounded-lg border border-slate-300 px-2 py-2 text-xs"><option value="">All states</option><option value="ACTIVE">Active</option><option value="INACTIVE">Inactive</option><option value="UNAVAILABLE">Unavailable</option></select><select aria-label="Feature data type filter" value={query.dataType} onChange={(event) => patch({ dataType: event.target.value })} className="rounded-lg border border-slate-300 px-2 py-2 text-xs"><option value="">All data types</option><option value="NUMERIC">Numeric</option><option value="CATEGORICAL">Categorical</option><option value="BINARY">Binary</option></select><select aria-label="Forecast availability filter" value={query.forecastAvailability} onChange={(event) => patch({ forecastAvailability: event.target.value })} className="rounded-lg border border-slate-300 px-2 py-2 text-xs"><option value="">All forecast availability</option><option value="AVAILABLE">Available</option><option value="SIMULATOR_SUPPLIED">Simulator supplied</option><option value="UNAVAILABLE">Unavailable</option></select><select aria-label="Simulation state filter" value={query.simulationState} onChange={(event) => patch({ simulationState: event.target.value })} className="rounded-lg border border-slate-300 px-2 py-2 text-xs"><option value="">Any simulation state</option><option value="YES">Simulation generated</option><option value="NO">Pregame evidence</option></select><select aria-label="Interaction membership filter" value={query.interaction} onChange={(event) => patch({ interaction: event.target.value })} className="rounded-lg border border-slate-300 px-2 py-2 text-xs"><option value="">Any interaction state</option><option value="MEMBER">Interaction member</option><option value="NONE">No interaction</option></select><select aria-label="Source availability filter" value={query.sourceAvailability} onChange={(event) => patch({ sourceAvailability: event.target.value })} className="rounded-lg border border-slate-300 px-2 py-2 text-xs"><option value="">Any source state</option><option value="AVAILABLE">Source available</option><option value="UNAVAILABLE">Source unavailable</option></select><button type="button" onClick={() => setQuery(DEFAULT_QUERY)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700">Reset filters</button></div>;
}

function AdvancedFeatureFilters({ query, setQuery }: { query: InventoryQuery; setQuery: (query: InventoryQuery) => void }) {
  const patch = (value: Partial<InventoryQuery>) => setQuery({ ...query, ...value, page: 1 });
  const className = "rounded-lg border border-slate-300 px-2 py-2 text-xs";
  return <div className="mb-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-label="Advanced feature inventory filters">
    <select aria-label="Missingness filter" value={query.missingness} onChange={(event) => patch({ missingness: event.target.value })} className={className}><option value="">Any missingness</option><option value="COMPLETE">Complete</option><option value="PRESENT">Any physical missingness</option><option value="HIGH">20% or more missing</option></select>
    <select aria-label="Outlier prevalence filter" value={query.outlierPrevalence} onChange={(event) => patch({ outlierPrevalence: event.target.value })} className={className}><option value="">Any outlier evidence</option><option value="NOT_EVALUATED">Not evaluated in inventory</option></select>
    <select aria-label="Point in time state filter" value={query.pointInTimeState} onChange={(event) => patch({ pointInTimeState: event.target.value })} className={className}><option value="">Any point-in-time state</option><option value="PREGAME">Pregame or prior-date evidence</option><option value="SIMULATOR">Simulator supplied</option></select>
    <select aria-label="Governance status filter" value={query.governanceStatus} onChange={(event) => patch({ governanceStatus: event.target.value })} className={className}><option value="">Any governance status</option><option value="ELIGIBLE">Eligible</option><option value="INACTIVE_PENDING_RIVALRY_APPROVAL">Pending rivalry approval</option></select>
  </div>;
}

function GovernedPriorRowSummary({
  resolution,
}: {
  resolution: TreatmentSpecificationResolution | null;
}) {
  const authority = resolution?.priorAuthority;
  if (!authority) return null;
  const outputs = resolution?.derivedPriorOutputs.length
    ? resolution.derivedPriorOutputs
    : authority.derivedOutputs;
  const focused = focusedPriorOutputs(outputs);
  const presentation = priorPresentation(authority);
  const resolutionReason = priorResolutionReason(
    authority,
    resolution,
    presentation.bucket,
  );
  return (
    <div
      className={`mt-2 rounded-lg border p-2 text-[9px] leading-3 ${presentation.cardClass}`}
      data-testid="feature-row-governed-prior-outputs"
      data-prior-bucket={presentation.bucket}
    >
      <div className="flex flex-wrap items-center gap-1">
        <b>Governed prior · {presentation.label}</b>
        <span className="ml-auto">{outputs.length} derived outputs</span>
      </div>
      <div className="mt-1 break-all font-mono text-[8px] text-slate-600">
        {authority.status} · executable {String(authority.executable)} · selectable {String(authority.selectable)}
      </div>
      {focused.length ? (
        <div className="mt-1 break-words font-mono">
          {focused.join(", ")}
          {outputs.length > focused.length ? ` +${outputs.length - focused.length}` : ""}
        </div>
      ) : null}
      {resolutionReason ? (
        <div className={`mt-1 rounded border bg-white p-1 leading-4 ${presentation.reasonClass}`}>
          <b>{presentation.reasonLabel}</b>{" "}
          {resolutionReason}
        </div>
      ) : null}
    </div>
  );
}

function GovernedInteractionRowSummary({
  resolution,
}: {
  resolution: TreatmentSpecificationResolution | null;
}) {
  const authority = resolution?.interactionAuthority;
  if (!authority) return null;
  const ready = authority.status === "READY_GOVERNED_INTERACTION_V1";
  return (
    <div
      className={`mt-2 rounded-lg border p-2 text-[9px] leading-4 ${
        ready
          ? "border-emerald-200 bg-emerald-50 text-emerald-950"
          : "border-amber-200 bg-amber-50 text-amber-950"
      }`}
      data-testid="feature-row-governed-interaction"
    >
      <div className="flex flex-wrap items-center gap-1">
        <b>Governed interaction · {authority.status}</b>
        <span className="ml-auto">Fold-local {authority.foldLocal}</span>
      </div>
      <div className="mt-1 break-words font-mono">
        {authority.formulaVersion}: {authority.formula}
      </div>
      <div className="mt-1 break-words">
        Parents: {authority.orderedParents.join(" → ") || "NOT_REPORTED"}
      </div>
      {!ready && authority.blockedReason ? (
        <div className="mt-1">
          <b>BLOCKED:</b> {authority.blockedReason}
        </div>
      ) : null}
    </div>
  );
}

function FeatureTable({ inventory, query, setQuery, selectedFeatures, setSelectedFeatures, transformationOverrides, setTransformationOverrides, inspect }: { inventory: FeatureInventory; query: InventoryQuery; setQuery: (query: InventoryQuery) => void; selectedFeatures: string[]; setSelectedFeatures: (features: string[]) => void; transformationOverrides: Record<string, string[]>; setTransformationOverrides: (overrides: Record<string, string[]>) => void; inspect: (row: FeatureInventoryRow, trigger: HTMLButtonElement) => void }) {
  const sort = (field: string) => setQuery({ ...query, page: 1, sortField: field, sortDirection: query.sortField === field && query.sortDirection === "asc" ? "desc" : "asc" });
  const pages = Math.max(1, Math.ceil(inventory.total / inventory.pageSize));
  const headers = [["order", "Order"], ["featureName", "Feature"], ["family", "Family"], ["dataType", "Type"], ["developmentCoveragePercent", "Coverage"], ["physicalMissingPercent", "Missing"], ["outlierPrevalencePercent", "Outliers"], ["status", "State"]];
  return <>
    <div className="max-h-[620px] max-w-full overflow-auto rounded-xl border border-slate-200">
      <table className="w-full min-w-[1880px] text-left text-[11px]">
        <caption className="sr-only">All 254 project-bound feature candidates with treatment, point-in-time, availability, and selection evidence</caption>
        <thead className="sticky top-0 z-10 bg-slate-50"><tr>
          <th scope="col" className="border-b border-slate-200 px-2 py-2">Select</th>
          {headers.map(([field, label]) => <th key={field} scope="col" aria-sort={query.sortField === field ? (query.sortDirection === "asc" ? "ascending" : "descending") : "none"} className="border-b border-slate-200 px-2 py-2 font-semibold uppercase text-slate-500"><button type="button" onClick={() => sort(field)} className="inline-flex items-center gap-1 rounded focus:outline-none focus:ring-2 focus:ring-cyan-500">{label}<ArrowUpDown size={10} className={query.sortField === field ? "text-cyan-700" : "text-slate-300"} /></button></th>)}
          <th scope="col" className="border-b border-slate-200 px-2 py-2 uppercase text-slate-500">Definition / lineage / dates</th>
          <th scope="col" className="border-b border-slate-200 px-2 py-2 uppercase text-slate-500">Range / cold start / interactions</th>
          <th scope="col" className="border-b border-slate-200 px-2 py-2 uppercase text-slate-500">Fold-local transformation</th>
          <th scope="col" className="border-b border-slate-200 px-2 py-2 uppercase text-slate-500">Treatment / PIT / governed outputs</th>
          <th scope="col" className="border-b border-slate-200 px-2 py-2 uppercase text-slate-500">Unavailable reason / selected sets</th>
          <th scope="col" className="border-b border-slate-200 px-2 py-2">Details</th>
        </tr></thead>
        <tbody>{inventory.rows.map((row) => {
          const selected = selectedFeatures.includes(row.featureName);
          const visiblySelected =
            row.status === "ACTIVE" && (selected || row.core);
          const currentTransform = transformationOverrides[row.featureName]?.join("|") ?? "";
          const transformOptions = row.eligibleTransformations.filter((item) => item !== "ONE_HOT").map((item) => ({ value: item, label: human(item) }));
          if (row.eligibleTransformations.includes("ONE_HOT") && row.eligibleTransformations.includes("CATEGORICAL_UNKNOWN")) transformOptions.push({ value: "CATEGORICAL_UNKNOWN|ONE_HOT", label: "Unknown handling + one-hot" });
          return <tr key={row.featureName} className="align-top hover:bg-cyan-50/30">
            <td className="border-b border-slate-100 px-2 py-2"><input aria-label={`Select ${row.featureName}`} type="checkbox" disabled={row.status !== "ACTIVE" || row.core} checked={visiblySelected} onChange={() => setSelectedFeatures(selected ? selectedFeatures.filter((name) => name !== row.featureName) : [...selectedFeatures, row.featureName])} /></td>
            <td className="border-b border-slate-100 px-2 py-2 tabular-nums">{row.order}</td>
            <th scope="row" className="border-b border-slate-100 px-2 py-2 text-left"><div className="font-mono font-semibold text-slate-900">{row.featureName}</div><div className="mt-0.5 font-normal text-slate-500">{row.friendlyLabel}</div></th>
            <td className="border-b border-slate-100 px-2 py-2">{row.family}</td>
            <td className="border-b border-slate-100 px-2 py-2">{row.dataType}<div className="text-[9px] uppercase text-slate-400">{row.role}</div></td>
            <td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtPct(row.developmentCoveragePercent)}</td>
            <td className="border-b border-slate-100 px-2 py-2 tabular-nums">{fmtPct(row.physicalMissingPercent)}</td>
            <td className="border-b border-slate-100 px-2 py-2 tabular-nums">{row.outlierPrevalencePercent == null ? "NOT_EVALUATED" : fmtPct(row.outlierPrevalencePercent)}</td>
            <td className="border-b border-slate-100 px-2 py-2"><Pill label={row.status} tone={row.status === "ACTIVE" ? "emerald" : "amber"} /></td>
            <td className="max-w-80 border-b border-slate-100 px-2 py-2 leading-4"><div>{row.definition}</div><div className="mt-1 break-all font-mono text-[9px] text-slate-500">{row.sourceLineage}</div><div className="mt-1 text-slate-500">{row.earliestAvailableDate || "Earliest date not published"} → {row.latestDevelopmentDate}</div></td>
            <td className="max-w-60 border-b border-slate-100 px-2 py-2 leading-4"><div>{row.range || (row.cardinality == null ? "Range/cardinality not published" : `${fmtInt(row.cardinality)} levels`)}</div><div className="mt-1">Cold start: {row.coldStartRelevant ? "Relevant" : "No special flag"}</div><div className="mt-1 text-slate-500">{row.interactionMembership.length ? row.interactionMembership.join(", ") : "No declared interaction"}</div></td>
            <td className="w-56 border-b border-slate-100 px-2 py-2"><select aria-label={`Transformation for ${row.featureName}`} disabled={!selected || row.status !== "ACTIVE"} value={currentTransform} onChange={(event) => { const next = { ...transformationOverrides }; if (!event.target.value) delete next[row.featureName]; else next[row.featureName] = event.target.value.split("|"); setTransformationOverrides(next); }} className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-[10px] disabled:bg-slate-100"><option value="">Governed default</option>{transformOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select><div className="mt-1 text-[9px] leading-3 text-slate-500">Fit independently within each chronological training fold.</div></td>
            <td className="max-w-72 border-b border-slate-100 px-2 py-2 leading-4"><div>{row.missingValueTreatment}</div><div className="text-slate-500">{row.pointInTimeTreatment}</div><div className="text-cyan-800">{row.forecastTimeAvailability}</div>{row.simulationGeneratedState ? <div className="font-semibold text-violet-700">SIMULATION_GENERATED_STATE</div> : null}<GovernedPriorRowSummary resolution={row.treatmentSpecificationResolution} /><GovernedInteractionRowSummary resolution={row.treatmentSpecificationResolution} /></td>
            <td className="max-w-72 border-b border-slate-100 px-2 py-2 text-amber-800"><div>{row.unavailableReason || "—"}</div><div className="mt-1 text-slate-500">{row.selectedCandidateSets.length ? `Sets: ${row.selectedCandidateSets.join(", ")}` : "No registered set membership"}</div></td>
            <td className="border-b border-slate-100 px-2 py-2"><button type="button" onClick={(event) => void inspect(row, event.currentTarget)} className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 font-semibold text-slate-700"><Eye size={11} /> Inspect</button></td>
          </tr>;
        })}</tbody>
      </table>
    </div>
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600"><span>{fmtInt(inventory.total)} candidates · page {inventory.page} of {pages}</span><div className="flex gap-2"><button aria-label="Previous feature inventory page" type="button" disabled={inventory.page <= 1} onClick={() => setQuery({ ...query, page: inventory.page - 1 })} className="rounded border border-slate-300 p-1.5 disabled:opacity-40"><ChevronLeft size={14} /></button><button aria-label="Next feature inventory page" type="button" disabled={inventory.page >= pages} onClick={() => setQuery({ ...query, page: inventory.page + 1 })} className="rounded border border-slate-300 p-1.5 disabled:opacity-40"><ChevronRight size={14} /></button></div></div>
  </>;
}

function GovernedPriorFeatureDetail({
  resolution,
}: {
  resolution: TreatmentSpecificationResolution | null;
}) {
  const authority = resolution?.priorAuthority;
  if (!authority) return null;
  const outputs = resolution?.derivedPriorOutputs.length
    ? resolution.derivedPriorOutputs
    : authority.derivedOutputs;
  const presentation = priorPresentation(authority);
  const resolutionReason = priorResolutionReason(
    authority,
    resolution,
    presentation.bucket,
  );
  return (
    <section
      className={`rounded-xl border p-4 ${presentation.cardClass}`}
      data-testid="feature-detail-governed-prior-outputs"
      data-prior-bucket={presentation.bucket}
    >
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
            Governed preprocessing outputs
          </div>
          <div className="mt-1 break-all font-mono text-xs font-semibold text-slate-950">
            {authority.authorityName} · {authority.authorityId}
          </div>
        </div>
        <Pill
          label={presentation.label}
          tone={presentation.tone}
        />
      </div>
      <dl className="mt-3 grid gap-2 sm:grid-cols-2">
        <MiniStat
          label="Execution / selection"
          value={`${authority.status} · executable ${String(authority.executable)} · selectable ${String(authority.selectable)}`}
        />
        <MiniStat
          label="Method / hierarchy"
          value={`${human(authority.method)} · ${priorHierarchy(authority)}`}
        />
        <MiniStat
          label="Fold-local / point in time"
          value={`Fold-local ${authority.foldLocal} · PIT ${authority.pointInTime}`}
        />
        <MiniStat
          label="Exposure / effective sample size"
          value={`${authority.exposureFeature || "NOT_AVAILABLE"}${authority.exposureDefinition ? ` · ${authority.exposureDefinition}` : ""}`}
        />
        <MiniStat
          label="Reliability / uncertainty"
          value={authority.reliability}
        />
      </dl>
      {outputs.length ? (
        <div className="mt-3">
          <div className="text-[9px] font-semibold uppercase tracking-wide text-slate-500">
            Derived columns carried as one governed preprocessing family
          </div>
          <div className="mt-1 flex max-h-32 flex-wrap gap-1 overflow-y-auto">
            {outputs.map((output) => (
              <code
                key={output}
                className="rounded border border-white bg-white/80 px-1.5 py-1 text-[9px] text-slate-700"
              >
                {output}
              </code>
            ))}
          </div>
        </div>
      ) : null}
      {resolutionReason ? (
        <p className={`mt-3 rounded-lg border bg-white p-2 text-[11px] leading-5 ${presentation.reasonClass}`}>
          <b>{presentation.reasonLabel}</b>{" "}
          {resolutionReason}
        </p>
      ) : null}
    </section>
  );
}

function GovernedInteractionFeatureDetail({
  resolution,
}: {
  resolution: TreatmentSpecificationResolution | null;
}) {
  const authority = resolution?.interactionAuthority;
  if (!authority) return null;
  return (
    <section
      data-testid="feature-detail-governed-interaction"
      className={`rounded-xl border p-4 ${
        authority.status === "READY_GOVERNED_INTERACTION_V1"
          ? "border-emerald-200 bg-emerald-50/50"
          : "border-amber-200 bg-amber-50/60"
      }`}
    >
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
            Governed interaction recomputation
          </div>
          <code className="mt-1 block break-all text-xs font-semibold text-slate-950">
            {authority.featureName} · {authority.backendFeatureIdentity}
          </code>
        </div>
        <Pill
          label={authority.status}
          tone={authority.status === "READY_GOVERNED_INTERACTION_V1" ? "emerald" : "amber"}
        />
      </div>
      <dl className="mt-3 grid gap-2 sm:grid-cols-2">
        <MiniStat
          label="Exact formula / version"
          value={`${authority.formula} · ${authority.formulaVersion}`}
        />
        <MiniStat
          label="Ordered parents"
          value={authority.orderedParents.join(" → ") || "NOT_REPORTED"}
        />
        <MiniStat
          label="Operation order"
          value={authority.operationOrder.join(" → ") || "NOT_REPORTED"}
        />
        <MiniStat
          label="Fold-local / point in time"
          value={`Fold-local ${authority.foldLocal} · PIT ${authority.pointInTime}`}
        />
      </dl>
      <details open className="mt-3 rounded-lg border border-white bg-white/70 p-2">
        <summary className="cursor-pointer text-[10px] font-semibold text-slate-800">
          Parent treatment authorities · {authority.parentTreatmentAuthorities.length}
        </summary>
        <ol className="mt-2 space-y-1 pl-4 text-[10px] leading-4 text-slate-700">
          {authority.parentTreatmentAuthorities.map((parent, index) => (
            <li key={`${authority.featureName}:detail:${index}`} className="break-words">
              {interactionAuthorityValue(parent)}
            </li>
          ))}
        </ol>
      </details>
      {authority.blockedReason ? (
        <p className="mt-3 rounded-lg border border-amber-300 bg-white p-2 text-[11px] leading-5 text-amber-950">
          <b>BLOCKED:</b> {authority.blockedReason}
        </p>
      ) : null}
    </section>
  );
}

function FeatureDetail({ row }: { row: FeatureInventoryRow }) {
  const seasonMissing = row.missingnessBySeason ?? [];
  const monthMissing = row.missingnessByMonth ?? [];
  const targetComparison = row.targetClassComparison ?? [];
  const temporalCoverage = row.temporalCoverage ?? [];
  const redundancy = row.redundancy ?? [];
  return <div className="space-y-4 text-sm">
    <section className="rounded-xl border border-slate-200 p-4">
      <div className="flex flex-wrap gap-2"><Pill label={row.status} tone={row.status === "ACTIVE" ? "emerald" : "amber"} /><Pill label={row.family} tone="cyan" />{row.simulationGeneratedState ? <Pill label="Simulator supplied" tone="violet" /> : <Pill label="Pregame / prior-date" tone="slate" />}</div>
      <p className="mt-3 leading-6 text-slate-700">{row.definition}</p>
      <dl className="mt-3 grid gap-2 sm:grid-cols-2"><MiniStat label="Registered formula / definition" value={row.definition || "NOT_PUBLISHED_SEPARATELY"} /><MiniStat label="Source columns / object / manifest" value={row.sourceLineage || "NOT_PUBLISHED_SEPARATELY"} /><MiniStat label="Development dates" value={`${row.earliestAvailableDate || "NOT_PUBLISHED"} → ${row.latestDevelopmentDate}`} /><MiniStat label="Development coverage" value={fmtPct(row.developmentCoveragePercent)} /><MiniStat label="Point-in-time treatment" value={row.pointInTimeTreatment} /><MiniStat label="Leakage risk" value={row.leakageRisk} /><MiniStat label="Range / cardinality" value={row.range || fmtInt(row.cardinality)} /><MiniStat label="Decision reason" value={row.unavailableReason || (row.status === "ACTIVE" ? "Eligible for bounded chronological comparison; predictive value not established." : "Review required before inclusion.")} /></dl>
      <div className="mt-3 text-xs text-slate-600"><b>Interaction membership:</b> {row.interactionMembership.length ? row.interactionMembership.join(", ") : "None declared"}</div>
    </section>
    <GovernedPriorFeatureDetail
      resolution={row.treatmentSpecificationResolution}
    />
    <GovernedInteractionFeatureDetail
      resolution={row.treatmentSpecificationResolution}
    />
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Missingness by season" description="Development-only; physical missingness is distinct from cold start.">{seasonMissing.length ? <BarChart categories={seasonMissing.map((item) => item.label)} values={seasonMissing.map((item) => item.value)} height={210} color="#d97706" /> : <DiagnosticEmpty label="NOT_EVALUATED — no season profile was published." />}</Card>
      <Card title="Missingness by month" description="Development-only month profile.">{monthMissing.length ? <BarChart categories={monthMissing.map((item) => item.label)} values={monthMissing.map((item) => item.value)} height={210} color="#ea580c" /> : <DiagnosticEmpty label="NOT_EVALUATED — no month profile was published." />}</Card>
      <Card title="Feature stability through time" description="Coverage stability only; no final-OOT outcome evidence.">{temporalCoverage.length ? <BarChart categories={temporalCoverage.map((item) => item.label)} values={temporalCoverage.map((item) => item.value)} height={210} /> : <DiagnosticEmpty label="NOT_EVALUATED — no temporal stability series was published." />}</Card>
      <Card title="Descriptive target comparison" description="Development-only and not a selection decision. It never becomes an automatic selector.">{targetComparison.length ? <BarChart categories={targetComparison.map((item) => item.label)} values={targetComparison.map((item) => item.value)} height={210} /> : <DiagnosticEmpty label="NOT_EVALUATED — no development-only class aggregate was published." />}</Card>
      <Card title="Relationship / redundancy diagnostics" description="Only registered development-only pair evidence is shown.">{redundancy.length ? <BarChart categories={redundancy.map((item) => item.feature)} values={redundancy.map((item) => item.value)} height={210} horizontal /> : <DiagnosticEmpty label="NOT_EVALUATED — no redundancy aggregate was published." />}</Card>
      <Card title="Outlier evidence" description="Uses the adopted project policy; no new thresholds are fit in this drawer.">{row.outlierPrevalencePercent == null ? <DiagnosticEmpty label="NOT_EVALUATED in the bounded inventory." /> : <div className="p-5 text-center"><div className="text-3xl font-semibold tabular-nums text-slate-950">{fmtPct(row.outlierPrevalencePercent)}</div><div className="mt-1 text-xs text-slate-500">development rows flagged under adopted policy</div></div>}</Card>
    </div>
    <section className="rounded-xl border border-cyan-200 bg-cyan-50 p-3 text-xs leading-5 text-cyan-950"><b>Treatment handoff:</b> {row.outlierTreatment} · {row.missingValueTreatment}. Transform candidates: {row.eligibleTransformations.join(", ") || "None"}. Every learned statistic remains training-fold-local.</section>
  </div>;
}

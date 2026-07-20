import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Database,
  GitBranch,
  LoaderCircle,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
} from "lucide-react";
import StepShell from "../components/StepShell";
import {
  AtlasAttentionPanel,
  AtlasDataScopeBadge,
  AtlasExecutionStatus,
  AtlasStatusStrip,
  AtlasWorkflowSection,
  type AtlasWorkflowMetric,
} from "../components/ui/AtlasWorkflow";
import { createEvidence } from "../lib/evidenceGraph";
import {
  getFeatureManifest,
  saveFeatureManifest,
  type FeatureDraft,
  type FeatureManifest,
  type FeatureManifestRow,
} from "../lib/featureManifest";
import {
  featureMetric,
  fetchFullFeatureProfile,
  type FeatureProfileResponse,
  type FeatureProfileRow,
} from "../lib/featureProfiling";
import { loadLocalDataset } from "../lib/localDataset";
import { logDecision } from "../lib/decisionJournal";
import { useWorkflowStore } from "../state/useWorkflowStore";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type BalanceMethod = "none" | "undersample" | "oversample" | "smote";

type Distribution = {
  rows: number;
  valid_rows: number;
  missing_rows: number;
  classes: Record<string, number>;
  event_value?: unknown;
  events: number | null;
  non_events: number | null;
  event_rate: number | null;
};

type SplitStatus = {
  ok: boolean;
  status: "not_created" | "current" | "stale";
  ready?: boolean;
  readiness_reason?: string;
  has_split: boolean;
  split_id?: string | null;
  config_hash?: string | null;
  selected_feature_hash?: string | null;
  split_config_hash?: string | null;
  balancing_config_hash?: string | null;
  created_at?: string | null;
  dataset_version?: string | null;
  target?: string | null;
  event_value?: unknown;
  feature_manifest_version?: string | null;
  selected_features: string[];
  feature_count: number;
  config: Record<string, unknown>;
  distributions: Record<string, Distribution>;
  n_train?: number | null;
  n_test?: number | null;
  original_train_rows?: number | null;
  duration_ms?: number | null;
  execution_ms?: number | null;
};

function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  return fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  }).then(async (response) => {
    const payload = await response.json().catch(() => null);
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.detail ?? payload?.error ?? `ATLAS request failed with HTTP ${response.status}.`);
    }
    return payload as T;
  });
}

function toDraft(row: FeatureManifestRow): FeatureDraft {
  return {
    feature_id: row.feature_id,
    feature_name: row.feature_name,
    display_name: row.display_name,
    origin: row.origin,
    source_features: row.source_features,
    transformation_type: row.transformation_type,
    formula_or_rule: row.formula_or_rule,
    output_datatype: row.output_datatype,
    selected: row.selected,
    exclusion_reason: row.exclusion_reason,
    user_rationale: row.user_rationale,
    config: row.config ?? {},
  };
}

function formatMetric(value: number | null | undefined, digits = 4) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "Not evaluated";
}

function formatPercent(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(3)}%` : "Not available";
}

function statusLabel(status?: SplitStatus["status"]) {
  return status === "current" ? "Current" : status === "stale" ? "Stale" : "Not created";
}

function balanceMethodLabel(method: BalanceMethod) {
  if (method === "undersample") return "Undersample majority";
  if (method === "oversample") return "Oversample minority";
  if (method === "smote") return "SMOTE";
  return "No resampling";
}

function balanceMethodSubtitle(method: BalanceMethod) {
  if (method === "undersample") return "After training-only majority undersampling";
  if (method === "oversample") return "After training-only minority oversampling";
  if (method === "smote") return "After training-only SMOTE synthesis";
  return "No resampling applied";
}

function resolveEventStats(distribution?: Distribution) {
  if (!distribution || typeof distribution.events !== "number" || typeof distribution.non_events !== "number") return null;
  const events = distribution.events;
  const nonEvents = distribution.non_events;
  const rows = events + nonEvents;
  const eventRate = rows > 0 ? events / rows : null;
  const minority = Math.min(events, nonEvents);
  const majority = Math.max(events, nonEvents);
  const minorityLabel = events <= nonEvents ? "Event" : "Non-event";
  return { events, nonEvents, rows, eventRate, minority, majority, minorityLabel };
}

function projectedTrainingDistribution(
  events: number,
  nonEvents: number,
  holdoutSize: number,
  method: BalanceMethod,
  targetShare: number,
) {
  const trainEvents = Math.max(0, Math.round(events * (1 - holdoutSize)));
  const trainNonEvents = Math.max(0, Math.round(nonEvents * (1 - holdoutSize)));
  if (method === "none") {
    const rows = trainEvents + trainNonEvents;
    return { events: trainEvents, nonEvents: trainNonEvents, rows, eventRate: rows ? trainEvents / rows : null, synthetic: 0, removed: 0 };
  }

  const eventIsMinority = trainEvents <= trainNonEvents;
  const minority = eventIsMinority ? trainEvents : trainNonEvents;
  const majority = eventIsMinority ? trainNonEvents : trainEvents;
  if (minority <= 0 || majority <= 0) {
    const rows = trainEvents + trainNonEvents;
    return { events: trainEvents, nonEvents: trainNonEvents, rows, eventRate: rows ? trainEvents / rows : null, synthetic: 0, removed: 0 };
  }

  if (method === "undersample") {
    const desiredMajority = Math.max(1, Math.min(majority, Math.round(minority * (1 - targetShare) / targetShare)));
    const nextEvents = eventIsMinority ? minority : desiredMajority;
    const nextNonEvents = eventIsMinority ? desiredMajority : minority;
    const rows = nextEvents + nextNonEvents;
    return { events: nextEvents, nonEvents: nextNonEvents, rows, eventRate: rows ? nextEvents / rows : null, synthetic: 0, removed: majority - desiredMajority };
  }

  const desiredMinority = Math.max(minority, Math.round(majority * targetShare / (1 - targetShare)));
  const nextEvents = eventIsMinority ? desiredMinority : majority;
  const nextNonEvents = eventIsMinority ? majority : desiredMinority;
  const rows = nextEvents + nextNonEvents;
  return { events: nextEvents, nonEvents: nextNonEvents, rows, eventRate: rows ? nextEvents / rows : null, synthetic: desiredMinority - minority, removed: 0 };
}

function eventCountSeverity(events: number | null | undefined) {
  if (typeof events !== "number") return { tone: "warning" as const, label: "Binary target distribution unavailable" };
  if (events < 30) return { tone: "danger" as const, label: "Critical: fewer than 30 positive events" };
  if (events < 100) return { tone: "warning" as const, label: "High risk: fewer than 100 positive events" };
  if (events < 500) return { tone: "warning" as const, label: "Review: rare-event sample below 500 positives" };
  return { tone: "success" as const, label: "Positive event count is workable" };
}

function splitReadiness(status: SplitStatus | null, dirty: boolean, selectedCount: number, unavailableCount: number) {
  if (dirty) return { ready: false, reason: "Save predictor selections before continuing." };
  if (!selectedCount) return { ready: false, reason: "Select at least one eligible predictor before model training." };
  if (unavailableCount) return { ready: false, reason: "Materialize engineered features before continuing." };
  if (!status) return { ready: false, reason: "Split status is loading." };
  const distributions = status.distributions ?? {};
  const hasOutcomePopulations = !!(distributions.full_dataset && distributions.train_after_balancing && distributions.holdout_untouched);
  const hasUsableSplit = status.has_split === true || !!status.split_id || hasOutcomePopulations;
  if (status.status === "current" && hasUsableSplit && status.ready !== false) {
    return { ready: true, reason: status.readiness_reason || "Ready for next step. Validation split is current." };
  }
  return { ready: false, reason: status.readiness_reason || "Create a governed validation split before continuing." };
}

export default function Step06BalancingSplit() {
  const dataset = loadLocalDataset();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const getNextStepPath = useWorkflowStore((state) => state.getNextStepPath);
  const [manifest, setManifest] = useState<FeatureManifest | null>(null);
  const [profile, setProfile] = useState<FeatureProfileResponse | null>(null);
  const [splitStatus, setSplitStatus] = useState<SplitStatus | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [initialSelection, setInitialSelection] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [selectedOnly, setSelectedOnly] = useState(false);
  const [testSize, setTestSize] = useState(0.2);
  const [randomSeed, setRandomSeed] = useState(42);
  const [balanceMethod, setBalanceMethod] = useState<BalanceMethod>("none");
  const [minorityShare, setMinorityShare] = useState(0.5);
  const [signalThreshold, setSignalThreshold] = useState(0.02);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const problemType = profile?.problemType ?? dataset?.problem_type ?? "classification";
  const isClassification = problemType === "classification";

  async function loadPage() {
    if (!dataset?.target) {
      setError("Return to Data Acquisition and confirm a target before reviewing the final feature set.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const [nextManifest, nextProfile, nextStatus] = await Promise.all([
        getFeatureManifest(),
        fetchFullFeatureProfile(dataset),
        requestJson<SplitStatus>("/balancing_split/status"),
      ]);
      const governed = nextManifest.features
        .filter((row) => row.selected && row.eligibility_status === "eligible")
        .map((row) => row.feature_name);
      setManifest(nextManifest);
      setProfile(nextProfile);
      setSplitStatus(nextStatus);
      setSelected(governed);
      setInitialSelection(governed);
      const config = nextStatus.config ?? {};
      if (typeof config.test_size === "number") setTestSize(config.test_size);
      if (typeof config.random_seed === "number") setRandomSeed(config.random_seed);
      if (config.balance_method === "none" || config.balance_method === "undersample" || config.balance_method === "oversample" || config.balance_method === "smote") setBalanceMethod(config.balance_method);
      if (typeof config.minority_share === "number") setMinorityShare(config.minority_share);
      setDirty(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Final Predictor Review is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadPage();
    // Dataset version is the page-level invalidation key. Selection edits are local until explicitly saved.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset?.dataset_version, dataset?.target]);

  const profileByName = useMemo(
    () => new Map((profile?.features ?? []).map((row) => [row.predictor, row])),
    [profile],
  );
  const eligibleFeatures = useMemo(
    () => (manifest?.features ?? []).filter((row) => row.eligibility_status === "eligible"),
    [manifest],
  );
  const engineeredSelected = useMemo(
    () => eligibleFeatures.filter((row) => row.origin !== "original" && selected.includes(row.feature_name)).length,
    [eligibleFeatures, selected],
  );
  const unavailableSelected = useMemo(
    () => eligibleFeatures.filter((row) => selected.includes(row.feature_name) && row.origin !== "original" && row.materialization_status !== "materialized"),
    [eligibleFeatures, selected],
  );
  const visibleFeatures = useMemo(() => {
    const normalized = search.trim().toLowerCase();
    return eligibleFeatures
      .filter((row) => !selectedOnly || selected.includes(row.feature_name))
      .filter((row) => !normalized || `${row.feature_name} ${row.origin} ${row.source_features.join(" ")}`.toLowerCase().includes(normalized))
      .sort((left, right) => {
        const leftMetric = Math.abs(featureMetric(profileByName.get(left.feature_name) ?? emptyProfile(left.feature_name), problemType) ?? -1);
        const rightMetric = Math.abs(featureMetric(profileByName.get(right.feature_name) ?? emptyProfile(right.feature_name), problemType) ?? -1);
        return rightMetric - leftMetric || left.feature_name.localeCompare(right.feature_name);
      });
  }, [eligibleFeatures, problemType, profileByName, search, selected, selectedOnly]);

  function toggleFeature(name: string, checked: boolean) {
    setSelected((current) => checked ? [...new Set([...current, name])] : current.filter((item) => item !== name));
    setDirty(true);
    setMessage("");
  }

  function applySignalThreshold() {
    const retained = eligibleFeatures
      .filter((feature) => {
        const row = profileByName.get(feature.feature_name);
        const metric = row ? Math.abs(featureMetric(row, problemType) ?? -1) : -1;
        return metric < 0 || metric >= signalThreshold;
      })
      .map((feature) => feature.feature_name);
    setSelected(retained);
    setDirty(true);
    setMessage(`${eligibleFeatures.length - retained.length} predictor(s) below the ${signalThreshold.toFixed(2)} ${isClassification ? "IV" : "absolute correlation"} threshold were deselected. Review and save the feature gate.`);
  }

  async function saveSelection() {
    if (!manifest) return;
    if (!selected.length) {
      setError("Select at least one eligible predictor before model training.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const selectedSet = new Set(selected);
      const updated = manifest.features.map((row) => ({
        ...toDraft(row),
        selected: row.eligibility_status === "eligible" && selectedSet.has(row.feature_name),
        exclusion_reason: row.eligibility_status !== "eligible"
          ? row.exclusion_reason
          : selectedSet.has(row.feature_name) ? "" : "Excluded at Final Predictor Review",
      }));
      const saved = await saveFeatureManifest(updated, manifest.pipeline_steps, manifest.dataset_version);
      setManifest(saved);
      setSelected(saved.features.filter((row) => row.selected && row.eligibility_status === "eligible").map((row) => row.feature_name));
      setDirty(false);
      const status = await requestJson<SplitStatus>("/balancing_split/status");
      setSplitStatus(status);
      setMessage("Final predictor selection saved. Create or rebuild the holdout split to make it current.");
      logDecision({
        workflowStep: "Balance & Split",
        actionType: "feature_inclusion_changed",
        subject: "Final Predictor Review",
        previousValue: initialSelection,
        newValue: selected,
        systemRecommendation: "Use the exact manifest-selected original and engineered predictors for every model.",
        followStatus: "followed",
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ATLAS could not save the final predictor selection.");
    } finally {
      setSaving(false);
    }
  }

  async function createSplit() {
    if (!manifest || dirty) {
      setError("Save the final predictor selection before creating the validation split.");
      return;
    }
    if (unavailableSelected.length) {
      setError("Return to Feature Engineering and materialize: " + unavailableSelected.map((row) => row.feature_name).join(", "));
      return;
    }
    setCreating(true);
    setError("");
    setMessage("");
    try {
      const status = await requestJson<SplitStatus>("/balancing_split/config", {
        method: "POST",
        body: JSON.stringify({
          split_strategy: "holdout",
          test_size: testSize,
          random_seed: randomSeed,
          stratify: isClassification,
          balance_method: isClassification ? balanceMethod : "none",
          minority_share: minorityShare,
          problem_type: problemType,
          event_value: dataset?.event_value,
          selected_features: selected,
          feature_manifest_version: manifest.manifest_version,
          dataset_version: manifest.dataset_version,
        }),
      });
      setSplitStatus(status);
      setManifest((current) => current ? { ...current, split_status: "current" } : current);
      setMessage(`Validation split ${status.split_id} created from the full backend dataset in ${(status.duration_ms ?? 0).toLocaleString()} ms.`);
      logDecision({
        workflowStep: "Balance & Split",
        actionType: "workflow_setting_changed",
        subject: status.split_id ?? "Governed holdout",
        previousValue: null,
        newValue: { testSize, randomSeed, balanceMethod, minorityShare, selectedFeatures: selected },
        systemRecommendation: "Preserve holdout prevalence and apply any resampling to training rows only.",
        followStatus: "followed",
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ATLAS could not create the validation split.");
    } finally {
      setCreating(false);
    }
  }

  async function completeStep() {
    const status = await requestJson<SplitStatus>("/balancing_split/status");
    setSplitStatus(status);
    const latestReadiness = splitReadiness(status, false, selected.length, unavailableSelected.length);
    if (!latestReadiness.ready) {
      throw new Error(latestReadiness.reason);
    }
    await createEvidence({
      projectId,
      projectName,
      evidenceType: "feature_engineering",
      title: "Governed Feature Gate and Validation Split",
      summary: `${status.feature_count} predictors were approved for split ${status.split_id}. Balancing was applied to training rows only.`,
      sourcePage: "Balance & Split",
      sourceRoute: "/step06",
      datasetIds: status.dataset_version ? [status.dataset_version] : [],
      modelIds: [],
      documentIds: [],
      notebookIds: [],
      supportsSections: ["Feature Engineering", "Development Test and OOT Data", "Candidate Models"],
      tags: ["predictive_modeling", "feature_gate", "validation_split"],
      status: "ready",
      importance: "high",
      lineage: { datasetVersion: status.dataset_version, manifestVersion: status.feature_manifest_version, splitId: status.split_id },
      payload: status,
    });
    return true;
  }

  const heroMetrics: AtlasWorkflowMetric[] = [
    { label: "Approved Predictors", value: selected.length.toLocaleString() },
    { label: "Engineered", value: engineeredSelected.toLocaleString(), tone: engineeredSelected ? "info" : "neutral" },
    { label: "Holdout", value: `${Math.round(testSize * 100)}%` },
    { label: "Balancing", value: isClassification ? balanceMethod === "none" ? "None" : "Training only" : "Not applicable" },
    { label: "Split", value: statusLabel(splitStatus?.status), tone: splitStatus?.status === "current" ? "success" : splitStatus?.status === "stale" ? "warning" : "neutral" },
    { label: "Readiness", value: splitStatus?.status === "current" && !dirty ? "Ready" : "Action required", tone: splitStatus?.status === "current" && !dirty ? "success" : "warning" },
  ];

  if (loading) {
    return (
      <StepShell title="Step 6: Balance & Split" subtitle="Establish the authoritative feature gate and governed validation design." variant="preparation" heroMetrics={heroMetrics} nextDisabled>
        <div className="atlas-workflow-section flex min-h-64 items-center justify-center"><LoaderCircle size={30} className="animate-spin text-blue-600" /></div>
      </StepShell>
    );
  }

  const readiness = splitReadiness(splitStatus, dirty, selected.length, unavailableSelected.length);
  const nextReady = readiness.ready;
  const featureSignalMax = Math.max(
    ...eligibleFeatures.map((feature) => {
      const featureProfile = profileByName.get(feature.feature_name);
      return Math.abs(featureProfile ? featureMetric(featureProfile, problemType) ?? 0 : 0);
    }),
    0.0001,
  );
  const fullTargetDistribution = splitStatus?.distributions?.full_dataset;
  const targetStats = resolveEventStats(fullTargetDistribution);
  const eventSeverity = eventCountSeverity(targetStats?.events);
  const balanceProjectionShares = [0.2, 0.3, 0.4, 0.5];
  return (
    <StepShell
      title="Step 6: Balance & Split"
      subtitle="Approve the exact original and engineered predictors, define a reproducible holdout, and verify event coverage before Model Training."
      variant="preparation"
      eyebrow="Predictive Modeling Workflow"
      heroMetrics={heroMetrics}
      nextPath={getNextStepPath("step06")}
      nextDisabled={!nextReady}
      nextDisabledReason={readiness.reason}
      nextLabel="Mark Complete & Next Step"
      nextStatusLine={readiness.reason}
      onNext={completeStep}
    >
      <div className="flex flex-col gap-4">
        <AtlasStatusStrip items={[
          { label: "Manifest loaded", state: manifest ? "complete" : "blocked", detail: manifest?.manifest_version },
          { label: "Predictors approved", state: dirty ? "warning" : selected.length ? "complete" : "blocked", detail: `${selected.length} selected` },
          { label: "Features materialized", state: unavailableSelected.length ? "blocked" : "complete", detail: unavailableSelected.length ? `${unavailableSelected.length} unavailable` : "Contract resolved" },
          { label: "Validation split", state: splitStatus?.status === "current" ? "complete" : splitStatus?.status === "stale" ? "warning" : "pending", detail: statusLabel(splitStatus?.status) },
        ]} />

        {error ? <AtlasAttentionPanel title="Balance & Split requires attention" tone="danger">{error}</AtlasAttentionPanel> : null}
        {message ? <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-950">{message}</div> : null}

        <AtlasWorkflowSection
          eyebrow="Authoritative feature contract"
          title="Final Predictor Review"
          description="This is the final feature gate before training. The table includes source and engineered predictors with backend full-data signal metrics and lineage."
          tone="info"
          className="order-3"
          action={<AtlasDataScopeBadge scope="full_dataset" rows={profile?.registeredRowCount} />}
        >
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="Eligible" value={eligibleFeatures.length} />
            <Metric label="Included for training" value={selected.length} tone="success" />
            <Metric label="Excluded" value={Math.max(0, eligibleFeatures.length - selected.length)} tone={eligibleFeatures.length > selected.length ? "warning" : "neutral"} />
            <Metric label="Engineered selected" value={engineeredSelected} tone={engineeredSelected ? "info" : "neutral"} />
          </div>

          <div className="mt-4 flex flex-col gap-2 xl:flex-row xl:items-end xl:justify-between">
            <div className="flex flex-1 flex-wrap items-end gap-2">
              <label className="min-w-64 flex-1"><span className="atlas-label">Search predictors</span><span className="relative block"><Search size={15} className="pointer-events-none absolute left-3 top-2.5 text-slate-400" /><input className="atlas-input pl-9" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Feature, origin, or source variable" /></span></label>
              <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700"><input type="checkbox" checked={selectedOnly} onChange={(event) => setSelectedOnly(event.target.checked)} />Selected only</label>
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <label><span className="atlas-label">{isClassification ? "Minimum IV" : "Minimum absolute correlation"}</span><input className="atlas-input w-28" type="number" min="0" max={isClassification ? undefined : 1} step="0.01" value={signalThreshold} onChange={(event) => setSignalThreshold(Math.max(0, Number(event.target.value) || 0))} /></label>
              <button type="button" className="atlas-secondary-button" onClick={applySignalThreshold}>Exclude below threshold</button>
              <button type="button" className="atlas-secondary-button" onClick={() => { setSelected(initialSelection); setDirty(true); setMessage("The original Data Acquisition selection was restored for review."); }}><RefreshCw size={15} /> Restore Data Acquisition selection</button>
              <button type="button" className="atlas-primary-button" disabled={saving || !dirty} onClick={() => void saveSelection()}>{saving ? <LoaderCircle size={15} className="animate-spin" /> : <Save size={15} />} Save predictor selections</button>
            </div>
          </div>

          <div className="mt-4 max-h-[540px] overflow-auto rounded-xl border border-slate-200 bg-white shadow-sm">
            <table className="w-full min-w-[720px] table-fixed border-separate border-spacing-0 text-xs">
              <thead className="sticky top-0 z-20 bg-slate-950 text-white shadow-sm"><tr><th className="w-14 border-b border-slate-800 px-3 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200">Use</th><th className="w-[30%] border-b border-slate-800 px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200">Predictor and lineage</th><th className="w-[25%] border-b border-slate-800 px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200">Signal evidence</th><th className="w-[19%] border-b border-slate-800 px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200">Data quality</th><th className="w-[26%] border-b border-slate-800 px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200">Training readiness</th></tr></thead>
              <tbody>
                {visibleFeatures.map((feature) => <FeatureRow key={feature.feature_id} feature={feature} profile={profileByName.get(feature.feature_name)} selected={selected.includes(feature.feature_name)} problemType={problemType} signalMax={featureSignalMax} onToggle={toggleFeature} />)}
                {!visibleFeatures.length ? <tr><td colSpan={5} className="py-10 text-center text-sm text-slate-500">No predictors match the current filters.</td></tr> : null}
              </tbody>
            </table>
          </div>
        </AtlasWorkflowSection>

        <AtlasWorkflowSection
          eyebrow="Validation policy"
          title="Validation Split"
          description="Choose the untouched holdout and any training-only class handling, then create one reproducible split."
          tone="neutral"
          className="order-1"
          action={<AtlasExecutionStatus state={creating ? "running" : splitStatus?.status === "current" ? "complete" : "idle"} label={creating ? "Creating split" : statusLabel(splitStatus?.status)} detail={splitStatus?.split_id ?? undefined} />}
        >
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
            <div className="rounded-xl border border-blue-200 bg-blue-50/60 p-4">
              <div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2"><GitBranch size={17} className="text-blue-700" /><h3 className="text-sm font-semibold text-slate-950">Holdout policy</h3></div><span className="rounded-full border border-blue-200 bg-white px-2.5 py-1 text-[10px] font-semibold uppercase text-blue-800">{isClassification ? "Stratified" : "Reproducible"}</span></div>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label><span className="atlas-label">Holdout size</span><select className="atlas-input mt-1" value={testSize} onChange={(event) => setTestSize(Number(event.target.value))}><option value={0.1}>10%</option><option value={0.2}>20%</option><option value={0.25}>25%</option><option value={0.3}>30%</option><option value={0.4}>40%</option></select><span className="mt-1 block text-xs text-slate-500">Reserved for final, untouched validation.</span></label>
                <label><span className="atlas-label">Random seed</span><input className="atlas-input mt-1" type="number" min="0" value={randomSeed} onChange={(event) => setRandomSeed(Math.max(0, Number(event.target.value) || 0))} /><span className="mt-1 block text-xs text-slate-500">Makes the partition reproducible.</span></label>
              </div>
              <div className="mt-5 overflow-hidden rounded-full border border-blue-200 bg-white">
                <div className="flex h-10 text-xs font-semibold">
                  <div className="flex items-center justify-center bg-blue-700 text-white" style={{ width: `${Math.round((1 - testSize) * 100)}%` }}>Training {Math.round((1 - testSize) * 100)}%</div>
                  <div className="flex items-center justify-center bg-emerald-100 text-emerald-900" style={{ width: `${Math.round(testSize * 100)}%` }}>Holdout {Math.round(testSize * 100)}%</div>
                </div>
              </div>
              <div className="mt-4 grid gap-2 text-xs text-slate-700 sm:grid-cols-3">
                <div className="flex items-center gap-2"><CheckCircle2 size={14} className="shrink-0 text-emerald-600" />Full-data split</div>
                <div className="flex items-center gap-2"><CheckCircle2 size={14} className="shrink-0 text-emerald-600" />Holdout untouched</div>
                <div className="flex items-center gap-2"><CheckCircle2 size={14} className="shrink-0 text-emerald-600" />CV set in training</div>
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="flex items-center gap-2"><ShieldCheck size={17} className="text-blue-700" /><h3 className="text-sm font-semibold text-slate-950">Training population only</h3></div>
              <p className="mt-1 text-xs leading-5 text-slate-500">Optional class balancing is applied after the split and never changes holdout prevalence.</p>
              {isClassification ? <>
                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                  <BalanceMethodCard active={balanceMethod === "none"} title="No resampling" description="Preserve the complete training population. Use with class weights or rare-event metrics downstream." onClick={() => setBalanceMethod("none")} />
                  <BalanceMethodCard active={balanceMethod === "undersample"} title="Undersample majority" description="Reduce majority rows after splitting. Fast and interpretable, but discards non-event information." onClick={() => setBalanceMethod("undersample")} />
                  <BalanceMethodCard active={balanceMethod === "oversample"} title="Oversample minority" description="Duplicate minority rows in training only. Preserves majority data but can overfit repeated events." onClick={() => setBalanceMethod("oversample")} />
                  <BalanceMethodCard active={balanceMethod === "smote"} title="SMOTE" description="Synthesize minority examples from numeric neighbors. Useful for AI/ML challengers, not scorecard audit baselines." onClick={() => setBalanceMethod("smote")} />
                </div>
                {balanceMethod !== "none" ? <label className="mt-4 block"><span className="atlas-label">Target minority share in training</span><select className="atlas-input" value={minorityShare} onChange={(event) => setMinorityShare(Number(event.target.value))}><option value={0.2}>20%</option><option value={0.3}>30%</option><option value={0.4}>40%</option><option value={0.5}>50%</option></select><span className="mt-1 block text-xs text-slate-500">{balanceMethod === "undersample" ? "Majority records are removed only from training." : balanceMethod === "oversample" ? "Minority records are duplicated only in training." : "Synthetic minority records are generated only in training."}</span></label> : null}
              </> : <div className="mt-4 text-sm leading-6 text-slate-600">Class balancing is not applicable to regression. Training and holdout retain their observed target distributions.</div>}
            </div>
          </div>
          {isClassification ? (
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/70 p-4">
              <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-amber-800">Rare-event balance planning</div>
                  <h3 className="mt-1 text-sm font-semibold text-slate-950">Target distribution and training-balance impact</h3>
                  <p className="mt-1 text-xs leading-5 text-slate-600">Use this checkpoint to decide whether class handling is needed before Model Training. Holdout prevalence stays unchanged.</p>
                </div>
                <span className={eventSeverity.tone === "success" ? "rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800" : eventSeverity.tone === "danger" ? "rounded-full border border-red-200 bg-red-50 px-3 py-1 text-xs font-semibold text-red-800" : "rounded-full border border-amber-300 bg-white px-3 py-1 text-xs font-semibold text-amber-900"}>{eventSeverity.label}</span>
              </div>
              {targetStats ? (
                <>
                  <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                    <Metric label="Full rows with target" value={targetStats.rows.toLocaleString()} />
                    <Metric label="Positive events" value={targetStats.events.toLocaleString()} tone={targetStats.events < 100 ? "warning" : "success"} />
                    <Metric label="Non-events" value={targetStats.nonEvents.toLocaleString()} />
                    <Metric label="Observed event rate" value={formatPercent(targetStats.eventRate)} tone={targetStats.eventRate && targetStats.eventRate < 0.01 ? "warning" : "info"} />
                  </div>
                  <div className="mt-4 overflow-auto rounded-lg border border-amber-200 bg-white">
                    <table className="w-full min-w-[760px] text-xs">
                      <thead className="bg-slate-950 text-white">
                        <tr>
                          <th className="px-3 py-2 text-left font-semibold uppercase tracking-wide">Scenario</th>
                          <th className="px-3 py-2 text-right font-semibold uppercase tracking-wide">Training rows</th>
                          <th className="px-3 py-2 text-right font-semibold uppercase tracking-wide">Events</th>
                          <th className="px-3 py-2 text-right font-semibold uppercase tracking-wide">Non-events</th>
                          <th className="px-3 py-2 text-right font-semibold uppercase tracking-wide">Event rate</th>
                          <th className="px-3 py-2 text-right font-semibold uppercase tracking-wide">Synthetic added</th>
                          <th className="px-3 py-2 text-right font-semibold uppercase tracking-wide">Rows removed</th>
                        </tr>
                      </thead>
                      <tbody>
                        <BalanceProjectionRow label="Observed training split" projection={projectedTrainingDistribution(targetStats.events, targetStats.nonEvents, testSize, "none", minorityShare)} />
                        {balanceProjectionShares.map((share) => <BalanceProjectionRow key={share} label={`${balanceMethodLabel(balanceMethod)} at ${Math.round(share * 100)}% minority`} projection={projectedTrainingDistribution(targetStats.events, targetStats.nonEvents, testSize, balanceMethod, share)} active={balanceMethod !== "none" && share === minorityShare} />)}
                      </tbody>
                    </table>
                  </div>
                  <p className="mt-3 text-xs leading-5 text-amber-900">Critical event-count guidance: fewer than 30 positives usually cannot support reliable train/holdout evidence; fewer than 100 positives needs heightened review, rare-event metrics, and careful threshold validation.</p>
                </>
              ) : (
                <AtlasAttentionPanel title="Target distribution is not available yet" tone="warning">Create the validation split once to materialize full target counts. ATLAS will then show the observed event distribution and balancing scenarios.</AtlasAttentionPanel>
              )}
            </div>
          ) : null}
          <div className="mt-4 flex flex-col gap-2 border-t border-slate-200 pt-4 sm:flex-row sm:items-center sm:justify-between"><p className="text-xs text-slate-500">Creating the split persists the feature contract, holdout policy, seed, and training-only balancing decision.</p><button type="button" className="atlas-primary-button min-w-56" disabled={creating || dirty || !selected.length || !!unavailableSelected.length} onClick={() => void createSplit()}>{creating ? <LoaderCircle size={16} className="animate-spin" /> : <Database size={16} />} {splitStatus?.status === "current" ? "Rebuild Validation Split" : "Create Validation Split"}</button></div>
        </AtlasWorkflowSection>

        <AtlasWorkflowSection className="order-2" eyebrow="Validation readiness" title="Split Outcome" description="Counts below are returned by the backend after the full-data split. The holdout is never rebalanced." tone={splitStatus?.status === "current" ? "success" : "warning"}>
          {splitStatus?.status === "current" ? (
            <>
              <div className="grid gap-3 lg:grid-cols-3">
                <DistributionPanel title="Full modeling population" subtitle="Before splitting" distribution={splitStatus.distributions.full_dataset} />
                <DistributionPanel title="Training population" subtitle={balanceMethodSubtitle(balanceMethod)} distribution={splitStatus.distributions.train_after_balancing} before={splitStatus.distributions.train_before_balancing} />
                <DistributionPanel title="Holdout population" subtitle="Untouched validation data" distribution={splitStatus.distributions.holdout_untouched} />
              </div>
              <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
                <Metric label="Split ID" value={splitStatus.split_id ?? "Unavailable"} />
                <Metric label="Train rows" value={(splitStatus.n_train ?? 0).toLocaleString()} />
                <Metric label="Holdout rows" value={(splitStatus.n_test ?? 0).toLocaleString()} />
                <Metric label="Feature count" value={splitStatus.feature_count} />
                <Metric label="Execution" value={`${(splitStatus.execution_ms ?? splitStatus.duration_ms ?? 0).toLocaleString()} ms`} tone="success" />
                <Metric label="Created" value={splitStatus.created_at ? new Date(splitStatus.created_at).toLocaleString() : "Unavailable"} />
              </div>
            </>
          ) : <AtlasAttentionPanel title={splitStatus?.status === "stale" ? "Validation split is stale" : "Validation split has not been created"} tone="warning">Save the final predictor gate, review the split policy, and select Create Validation Split. Model Training is blocked until this status is Current.</AtlasAttentionPanel>}
        </AtlasWorkflowSection>
      </div>
    </StepShell>
  );
}

function FeatureRow({ feature, profile, selected, problemType, signalMax, onToggle }: { feature: FeatureManifestRow; profile?: FeatureProfileRow; selected: boolean; problemType: "classification" | "regression"; signalMax: number; onToggle: (name: string, checked: boolean) => void }) {
  const metric = profile ? featureMetric(profile, problemType) : null;
  const materialized = feature.origin === "original" || feature.materialization_status === "materialized";
  const signalWidth = typeof metric === "number" && Number.isFinite(metric) ? Math.max(3, Math.min(100, (Math.abs(metric) / signalMax) * 100)) : 0;
  const signalLabel = problemType === "classification" ? profile?.ivStrength : profile?.correlationStrength;
  const signalTone = /very strong|strong/i.test(signalLabel ?? "") ? "border-blue-200 bg-blue-50 text-blue-800" : /weak|negligible/i.test(signalLabel ?? "") ? "border-amber-200 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-100 text-slate-700";
  return (
    <tr className={`group ${selected ? "bg-white even:bg-slate-50/70 hover:bg-blue-50/70" : "bg-slate-50/80 opacity-75 hover:opacity-100"}`}>
      <td className="border-b border-slate-100 px-3 py-3 align-middle"><input type="checkbox" checked={selected} disabled={!materialized} aria-label={`Use ${feature.feature_name}`} onChange={(event) => onToggle(feature.feature_name, event.target.checked)} /></td>
      <td className="border-b border-slate-100 px-4 py-3 align-middle"><div className="font-semibold text-slate-950">{feature.feature_name}</div><div className="mt-1 flex flex-wrap items-center gap-1.5"><span className={feature.origin === "original" ? "rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-700" : "rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-800"}>{feature.origin.replace(/_/g, " ")}</span><span className="text-[10px] text-slate-500">{feature.output_datatype}</span></div><div className="mt-2 text-[10px] font-semibold uppercase text-slate-500">Source</div><div className="mt-0.5 break-words font-medium text-slate-700">{feature.source_features.join(", ")}</div>{feature.formula_or_rule && feature.formula_or_rule !== feature.feature_name ? <div className="mt-1 break-words font-mono text-[10px] leading-4 text-slate-500" title={feature.formula_or_rule}>{feature.formula_or_rule}</div> : null}</td>
      <td className="border-b border-slate-100 px-4 py-3 align-middle"><div className="flex items-center justify-between gap-3"><span className="font-mono text-sm font-semibold text-slate-950">{formatMetric(metric)}</span><span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${signalTone}`}>{signalLabel ?? "Not evaluated"}</span></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-blue-600" style={{ width: `${signalWidth}%` }} /></div><div className="mt-1 text-[10px] uppercase text-slate-500">{problemType === "classification" ? "Information value" : "Absolute correlation"}</div></td>
      <td className="border-b border-slate-100 px-4 py-3 align-middle"><div className="grid grid-cols-2 gap-2"><div><div className="text-[10px] uppercase text-slate-500">Missing</div><div className="mt-0.5 font-mono font-semibold text-slate-800">{profile ? `${(profile.missingPercent * 100).toFixed(2)}%` : "N/A"}</div></div><div><div className="text-[10px] uppercase text-slate-500">Distinct</div><div className="mt-0.5 font-mono font-semibold text-slate-800">{profile?.distinctCount?.toLocaleString() ?? "N/A"}</div></div></div></td>
      <td className="border-b border-slate-100 px-4 py-3 align-middle">{materialized ? <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[10px] font-semibold uppercase text-emerald-800"><CheckCircle2 size={13} /> Ready</span> : <span className="inline-flex rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[10px] font-semibold uppercase text-amber-900">Materialization required</span>}<div className="mt-1.5 text-[11px] text-slate-500">{selected ? "Included in training contract" : "Excluded from training contract"}</div></td>
    </tr>
  );
}

function DistributionPanel({ title, subtitle, distribution, before }: { title: string; subtitle: string; distribution?: Distribution; before?: Distribution }) {
  if (!distribution) return <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">{title} is unavailable.</div>;
  const eventRate = distribution.event_rate ?? 0;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-sm font-semibold text-slate-950">{title}</div>
      <div className="mt-1 text-xs text-slate-500">{subtitle}</div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <Metric label="Rows" value={distribution.rows.toLocaleString()} />
        <Metric label="Event rate" value={formatPercent(distribution.event_rate)} tone={distribution.events ? "info" : "warning"} />
        <Metric label="Events" value={distribution.events?.toLocaleString() ?? "N/A"} />
        <Metric label="Non-events" value={distribution.non_events?.toLocaleString() ?? "N/A"} />
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded bg-slate-100"><div className="h-full bg-blue-600" style={{ width: `${Math.max(0.5, Math.min(100, eventRate * 100))}%` }} /></div>
      {before && before.rows !== distribution.rows ? <div className="mt-3 text-xs text-slate-600">Training rows before balancing: <span className="font-semibold">{before.rows.toLocaleString()}</span>. Holdout rows were not changed.</div> : null}
    </div>
  );
}

function BalanceMethodCard({ active, title, description, onClick }: { active: boolean; title: string; description: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`min-h-32 rounded-xl border p-4 text-left transition ${
        active
          ? "border-blue-600 bg-blue-50 shadow-sm ring-1 ring-blue-200"
          : "border-slate-200 bg-white hover:border-blue-200 hover:bg-blue-50/50"
      }`}
    >
      <span className="block text-sm font-semibold text-slate-950">{title}</span>
      <span className="mt-2 block text-xs leading-5 text-slate-600">{description}</span>
      <span className={`mt-4 inline-flex rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase ${
        active ? "border-blue-200 bg-white text-blue-800" : "border-slate-200 bg-slate-50 text-slate-500"
      }`}>
        {active ? "Selected" : "Available"}
      </span>
    </button>
  );
}

function BalanceProjectionRow({
  label,
  projection,
  active = false,
}: {
  label: string;
  projection: { events: number; nonEvents: number; rows: number; eventRate: number | null; synthetic: number; removed: number };
  active?: boolean;
}) {
  return (
    <tr className={active ? "bg-blue-50 font-semibold text-slate-950" : "odd:bg-white even:bg-slate-50/70 text-slate-700"}>
      <td className="border-b border-slate-100 px-3 py-2 font-semibold">{label}</td>
      <td className="border-b border-slate-100 px-3 py-2 text-right font-mono">{projection.rows.toLocaleString()}</td>
      <td className="border-b border-slate-100 px-3 py-2 text-right font-mono">{projection.events.toLocaleString()}</td>
      <td className="border-b border-slate-100 px-3 py-2 text-right font-mono">{projection.nonEvents.toLocaleString()}</td>
      <td className="border-b border-slate-100 px-3 py-2 text-right font-mono">{formatPercent(projection.eventRate)}</td>
      <td className="border-b border-slate-100 px-3 py-2 text-right font-mono">{projection.synthetic.toLocaleString()}</td>
      <td className="border-b border-slate-100 px-3 py-2 text-right font-mono">{projection.removed.toLocaleString()}</td>
    </tr>
  );
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: string | number; tone?: "neutral" | "info" | "success" | "warning" }) {
  const classes = tone === "success" ? "border-emerald-200 bg-emerald-50" : tone === "warning" ? "border-amber-200 bg-amber-50" : tone === "info" ? "border-blue-200 bg-blue-50" : "border-slate-200 bg-slate-50";
  return <div className={`min-w-0 rounded-lg border p-3 ${classes}`}><div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 truncate text-sm font-semibold text-slate-950" title={String(value)}>{value}</div></div>;
}

function emptyProfile(name: string): FeatureProfileRow {
  return { selected: false, predictor: name, role: "feature", datatype: "unknown", iv: null, ivStrength: null, correlationWithTarget: null, correlationStrength: null, associationStatus: "not_evaluated", missingCount: 0, missingPercent: 0, distinctCount: 0, mean: null, standardDeviation: null, minimum: null, firstQuartile: null, median: null, thirdQuartile: null, maximum: null, leakageStatus: "eligible", eligibilityStatus: "eligible", exclusionReason: "" };
}

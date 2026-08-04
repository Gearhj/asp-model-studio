import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  CalendarClock,
  CheckCircle2,
  CircleAlert,
  CircleDot,
  Database,
  GitBranch,
  Layers3,
  LoaderCircle,
  Network,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  TableProperties,
} from "lucide-react";
import StepShell from "../components/StepShell";
import {
  PreparationGovernanceDisclosure,
  PreparationPageIdentity,
} from "../components/preparation/PreparationPageChrome";
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
  assertExactDatasetIdentity,
  buildCanonicalEvidenceEnvelope,
  canonicalDatasetStorageKey,
  requireLocalDatasetCanonicalIdentity,
  type CanonicalDatasetIdentity,
} from "../lib/datasetIdentity";
import {
  getDataset,
  listDatasets,
  type DatasetSummary,
  type DatasetVersionSummary,
} from "../lib/datasetLibrary";
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
import { projectWorkflowRoute } from "../lib/projectScopedRoutes";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type BalanceMethod = "none" | "undersample" | "oversample" | "smote";
type ValidationStrategy =
  | "holdout_current"
  | "separate_test"
  | "separate_test_oot"
  | "cross_validation"
  | "hybrid";
type ExternalValidationMode = "none" | "test" | "oot" | "test_oot";
type FoldMethod =
  | "none"
  | "k_fold"
  | "stratified_k_fold"
  | "repeated_stratified_k_fold"
  | "group_k_fold"
  | "stratified_group_k_fold"
  | "time_series"
  | "nested_cv";
type FoldLocalPreprocessingPolicy =
  | "fit_transform_per_fold"
  | "model_native_per_fold";

type DatasetOption = DatasetSummary & { versions: DatasetVersionSummary[] };

type ValidationDraft = {
  foldMethod: FoldMethod;
  foldCount: number;
  foldRepeats: number;
  innerFoldCount: number;
  foldLocalPreprocessing: FoldLocalPreprocessingPolicy;
  groupField: string;
  timeField: string;
  shuffleFolds: boolean;
  balanceMethod: BalanceMethod;
  minorityShare: number;
  classWeightPolicy: "none" | "balanced";
  externalValidationMode: ExternalValidationMode;
  testDatasetId: string;
  testDatasetVersion: string;
  testTargetField: string;
  ootDatasetId: string;
  ootDatasetVersion: string;
  ootTargetField: string;
  validationRationale?: string;
  designDirty: boolean;
  savedAt: string;
};

const VALIDATION_DRAFT_PREFIX =
  "atlas-validation-design-draft-v2";

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

type DistributionCollection = {
  full_dataset?: Distribution;
  train_before_balancing?: Distribution;
  train_after_balancing?: Distribution;
  holdout_untouched?: Distribution;
  test_untouched?: Distribution;
  oot_untouched?: Distribution;
  cv_folds?: Array<Distribution & { repeat?: number; fold?: number }>;
  [key: string]:
    | Distribution
    | Array<Distribution & { repeat?: number; fold?: number }>
    | undefined;
};

type SplitStatus = {
  ok: boolean;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
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
  distributions: DistributionCollection;
  n_train?: number | null;
  n_test?: number | null;
  original_train_rows?: number | null;
  duration_ms?: number | null;
  execution_ms?: number | null;
  validation_design_id?: string | null;
  validation_design_version?: string | null;
  training_population_id?: string | null;
  holdout_population_id?: string | null;
  test_reference?: Record<string, unknown> | null;
  oot_reference?: Record<string, unknown> | null;
  evaluation_population_role?: string | null;
  validation_design?: {
    project_id?: string;
    dataset_id?: string;
    dataset_version_id?: string;
    dataset_version?: string;
    validation_design_id?: string;
    design_version?: string;
    strategy?: ValidationStrategy;
    approved_by?: { user_id?: string; display_name?: string };
    approved_at?: string;
    status?: string;
    [key: string]: unknown;
  };
  cv_design?: {
    method?: FoldMethod;
    fold_count?: number;
    repeats?: number;
    group_field?: string | null;
    time_field?: string | null;
    shuffle?: boolean;
    tuning_scope?: string;
    approved?: boolean;
  };
  fold_architecture?: {
    enabled?: boolean;
    method?: FoldMethod;
    fold_count?: number;
    repeats?: number;
    fold_size_consistent?: boolean;
    group_field?: string | null;
    time_field?: string | null;
    folds?: Array<{
      sequence: number;
      repeat: number;
      fold: number;
      train_rows: number;
      validation_rows: number;
      validation_distribution?: Distribution;
      validation_groups?: number | null;
    }>;
  };
  compatibility_matrix?: {
    status?: string;
    populations?: Record<
      string,
      {
        status: string;
        checks: Array<{ check: string; status: string; detail: string }>;
      }
    >;
  };
  validation_risks?: Array<{
    risk: string;
    status: "low" | "attention" | "blocking" | "not_applicable";
    detail: string;
  }>;
  completion_gates?: Record<string, boolean>;
  balancing_policy?: Record<string, unknown>;
  analysis_partition?: {
    analysis_partition_id?: string;
    revision?: number;
    project_id?: string;
    dataset_id?: string;
    dataset_version_id?: string;
    target?: string;
    development_partition_id?: string;
    sealed_holdout_partition_id?: string;
    development_share?: number;
    holdout_share?: number;
    random_seed?: number;
    stratification_policy?: string;
    stratification_field?: string;
    status?: string;
    final_holdout_status?: string;
    holdout_isolation_status?: string;
    development_rows?: number;
    development_count?: number;
    holdout_rows?: number;
    holdout_count?: number;
    partition_method?: string;
    created_by?: { user_id?: string; display_name?: string } | string;
    created_at?: string;
    evidence_id?: string;
    evidence_ref?: string;
    evidence_status?: string;
    mdd_status?: string;
    mdd_ref?: string;
    [key: string]: unknown;
  };
  analysis_partition_id?: string | null;
  analysis_partition_revision?: number | null;
  development_partition_id?: string | null;
  sealed_holdout_partition_id?: string | null;
  final_holdout_status?: string | null;
  holdout_isolation_status?: string | null;
  confirmation_actor?: { user_id?: string; display_name?: string };
  confirmation_time?: string;
};

function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  return fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  }).then(async (response) => {
    const payload = await response.json().catch(() => null);
    if (!response.ok || payload?.ok === false) {
      const detail = payload?.detail;
      throw new Error(
        (typeof detail === "string" ? detail : detail?.message) ??
          payload?.message ??
          payload?.error ??
          `ATLAS request failed with HTTP ${response.status}.`,
      );
    }
    return payload as T;
  });
}

function verifySplitStatusIdentity(
  identity: CanonicalDatasetIdentity,
  status: SplitStatus,
  target: string,
  context: string,
) {
  assertExactDatasetIdentity(identity, status, context);
  if (status.validation_design?.validation_design_id) {
    assertExactDatasetIdentity(
      identity,
      status.validation_design,
      `${context} validation design`,
    );
  }
  const partition = status.analysis_partition;
  if (!partition) {
    throw new Error(`${context} is missing the exact sealed Analysis Partition.`);
  }
  assertExactDatasetIdentity(identity, partition, `${context} Analysis Partition`);
  const outerPartitionId = String(status.analysis_partition_id ?? "").trim();
  const nestedPartitionId = String(partition.analysis_partition_id ?? "").trim();
  const outerRevision = Number(status.analysis_partition_revision);
  const nestedRevision = Number(partition.revision);
  if (
    !outerPartitionId ||
    !nestedPartitionId ||
    outerPartitionId !== nestedPartitionId ||
    !Number.isSafeInteger(outerRevision) ||
    outerRevision < 1 ||
    outerRevision !== nestedRevision
  ) {
    throw new Error(`${context} contains a contradictory Analysis Partition ID or revision.`);
  }
  if (String(partition.target ?? "").trim() !== target.trim()) {
    throw new Error(`${context} Analysis Partition is bound to a different governed target.`);
  }
  if (
    String(partition.final_holdout_status ?? "").toLowerCase() !== "sealed" ||
    String(partition.holdout_isolation_status ?? "").toLowerCase() !== "verified"
  ) {
    throw new Error(`${context} does not prove a sealed, isolated final holdout.`);
  }
  const developmentShare = Number(partition.development_share);
  const holdoutShare = Number(partition.holdout_share);
  const randomSeed = Number(partition.random_seed);
  if (
    !Number.isFinite(developmentShare) ||
    !Number.isFinite(holdoutShare) ||
    Math.abs(developmentShare + holdoutShare - 1) > 1e-9 ||
    ![0.1, 0.2, 0.3].some((value) => Math.abs(value - holdoutShare) <= 1e-9) ||
    !Number.isSafeInteger(randomSeed) ||
    randomSeed < 0
  ) {
    throw new Error(`${context} contains an invalid inherited split ratio or random seed.`);
  }
  const stratificationPolicy = String(partition.stratification_policy ?? "");
  const stratificationField = String(partition.stratification_field ?? "");
  if (
    !["target", "none"].includes(stratificationPolicy) ||
    (stratificationPolicy === "target" && stratificationField !== target) ||
    (stratificationPolicy === "none" && stratificationField !== "")
  ) {
    throw new Error(`${context} contains a contradictory inherited stratification contract.`);
  }
  return partition;
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

function formatInteger(value: unknown) {
  const numeric = Number(value);
  return Number.isSafeInteger(numeric) && numeric >= 0
    ? numeric.toLocaleString()
    : "Unavailable";
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

function eventCountSeverity(events: number | null | undefined) {
  if (typeof events !== "number") return { tone: "warning" as const, label: "Target counts pending · retry available" };
  if (events < 30) return { tone: "danger" as const, label: "Critical: fewer than 30 positive events" };
  if (events < 100) return { tone: "warning" as const, label: "High risk: fewer than 100 positive events" };
  if (events < 500) return { tone: "warning" as const, label: "Review: rare-event sample below 500 positives" };
  return { tone: "success" as const, label: "Positive event count is workable" };
}

function loadValidationDraft(
  identity: CanonicalDatasetIdentity,
): ValidationDraft | null {
  try {
    const parsed = JSON.parse(
      localStorage.getItem(
        canonicalDatasetStorageKey(VALIDATION_DRAFT_PREFIX, identity),
      ) || "null",
    );
    return parsed && typeof parsed === "object"
      ? (parsed as ValidationDraft)
      : null;
  } catch {
    return null;
  }
}

function saveValidationDraft(
  identity: CanonicalDatasetIdentity,
  draft: ValidationDraft,
) {
  localStorage.setItem(
    canonicalDatasetStorageKey(VALIDATION_DRAFT_PREFIX, identity),
    JSON.stringify(draft),
  );
}

function projectedDistribution(
  events: number,
  nonEvents: number,
  share: number,
): Distribution {
  const projectedEvents = Math.max(0, Math.round(events * share));
  const projectedNonEvents = Math.max(0, Math.round(nonEvents * share));
  const rows = projectedEvents + projectedNonEvents;
  return {
    rows,
    valid_rows: rows,
    missing_rows: 0,
    classes: {
      event: projectedEvents,
      non_event: projectedNonEvents,
    },
    events: projectedEvents,
    non_events: projectedNonEvents,
    event_rate: rows ? projectedEvents / rows : null,
  };
}

export default function Step06BalancingSplit() {
  const dataset = loadLocalDataset();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const getNextStepPath = useWorkflowStore((state) => state.getNextStepPath);
  let datasetIdentity: CanonicalDatasetIdentity | null = null;
  let datasetIdentityError = "";
  try {
    datasetIdentity = requireLocalDatasetCanonicalIdentity(
      projectId,
      dataset,
      "Training and Validation Design dataset identity",
    );
  } catch (cause) {
    datasetIdentityError =
      cause instanceof Error
        ? cause.message
        : "Training and Validation Design requires an exact registered Dataset Library version.";
  }
  const [manifest, setManifest] = useState<FeatureManifest | null>(null);
  const [profile, setProfile] = useState<FeatureProfileResponse | null>(null);
  const [splitStatus, setSplitStatus] = useState<SplitStatus | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [initialSelection, setInitialSelection] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [selectedOnly, setSelectedOnly] = useState(false);
  const validationStrategy: ValidationStrategy = "hybrid";
  const [externalValidationMode, setExternalValidationMode] =
    useState<ExternalValidationMode>("none");
  const [foldMethod, setFoldMethod] =
    useState<FoldMethod>("stratified_k_fold");
  const [foldCount, setFoldCount] = useState(5);
  const [foldRepeats, setFoldRepeats] = useState(1);
  const [innerFoldCount, setInnerFoldCount] = useState(3);
  const [foldLocalPreprocessing, setFoldLocalPreprocessing] =
    useState<FoldLocalPreprocessingPolicy>("fit_transform_per_fold");
  const [groupField, setGroupField] = useState("");
  const [timeField, setTimeField] = useState("");
  const [shuffleFolds, setShuffleFolds] = useState(true);
  const [balanceMethod, setBalanceMethod] = useState<BalanceMethod>("none");
  const [minorityShare, setMinorityShare] = useState(0.5);
  const [classWeightPolicy, setClassWeightPolicy] = useState<
    "none" | "balanced"
  >("none");
  const [testDatasetId, setTestDatasetId] = useState("");
  const [testDatasetVersion, setTestDatasetVersion] = useState("");
  const [testTargetField, setTestTargetField] = useState("");
  const [ootDatasetId, setOotDatasetId] = useState("");
  const [ootDatasetVersion, setOotDatasetVersion] = useState("");
  const [ootTargetField, setOotTargetField] = useState("");
  const [validationRationale, setValidationRationale] = useState(
    "Cross-validation stays inside the development population; the sealed final holdout remains evaluation-only.",
  );
  const [datasetOptions, setDatasetOptions] = useState<DatasetOption[]>([]);
  const [signalThreshold, setSignalThreshold] = useState(0.02);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [designDirty, setDesignDirty] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [partitionResetImpacts, setPartitionResetImpacts] = useState<string[]>([]);
  const [loadingPartitionImpacts, setLoadingPartitionImpacts] = useState(false);

  const problemType = profile?.problemType ?? dataset?.problem_type ?? "classification";
  const isClassification = problemType === "classification";
  const inheritedPartition = splitStatus?.analysis_partition;
  const testSize = Number(inheritedPartition?.holdout_share);
  const randomSeed = Number(inheritedPartition?.random_seed);
  const inheritedStratify = inheritedPartition?.stratification_policy === "target";

  async function loadPage() {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      setLoading(false);
      return;
    }
    if (!dataset?.target) {
      setError("Return to Data Acquisition and confirm a target before reviewing the final feature set.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const [nextManifest, nextProfile, nextStatus, library] = await Promise.all([
        getFeatureManifest(datasetIdentity),
        fetchFullFeatureProfile(dataset, projectId),
        requestJson<SplitStatus>(
          `/balancing_split/status?${new URLSearchParams({
            project_id: projectId,
            expected_dataset_id: datasetIdentity.dataset_id,
            expected_dataset_version_id: datasetIdentity.dataset_version_id,
          }).toString()}`,
        ),
        listDatasets(),
      ]);
      verifySplitStatusIdentity(
        datasetIdentity,
        nextStatus,
        dataset.target,
        "Validation Design status response",
      );
      const details = await Promise.all(
        library.datasets.map(async (summary) => {
          try {
            return await getDataset(summary.datasetId);
          } catch {
            return { ...summary, versions: [] };
          }
        }),
      );
      const governed = nextManifest.features
        .filter((row) => row.selected && row.eligibility_status === "eligible")
        .map((row) => row.feature_name);
      setManifest(nextManifest);
      setProfile(nextProfile);
      setSplitStatus(nextStatus);
      setDatasetOptions(details);
      setSelected(governed);
      setInitialSelection(governed);
      const config = nextStatus.config ?? {};
      const storedStrategy =
        nextStatus.validation_design?.strategy ??
        (config.split_strategy === "holdout" ? "holdout_current" : config.split_strategy);
      const storedExternalMode = config.external_validation_mode;
      if (
        storedExternalMode === "none" ||
        storedExternalMode === "test" ||
        storedExternalMode === "oot" ||
        storedExternalMode === "test_oot"
      ) {
        setExternalValidationMode(storedExternalMode);
      } else if (storedStrategy === "separate_test_oot") {
        setExternalValidationMode("test_oot");
      } else if (storedStrategy === "separate_test") {
        setExternalValidationMode("test");
      } else {
        setExternalValidationMode("none");
      }
      if (
        config.fold_method === "none" ||
        config.fold_method === "k_fold" ||
        config.fold_method === "stratified_k_fold" ||
        config.fold_method === "repeated_stratified_k_fold" ||
        config.fold_method === "group_k_fold" ||
        config.fold_method === "stratified_group_k_fold" ||
        config.fold_method === "time_series" ||
        config.fold_method === "nested_cv"
      ) setFoldMethod(config.fold_method);
      if (typeof config.fold_count === "number") setFoldCount(config.fold_count);
      if (typeof config.repeats === "number") setFoldRepeats(config.repeats);
      if (typeof config.inner_fold_count === "number") setInnerFoldCount(config.inner_fold_count);
      if (
        config.fold_local_preprocessing === "fit_transform_per_fold" ||
        config.fold_local_preprocessing === "model_native_per_fold"
      ) {
        setFoldLocalPreprocessing(config.fold_local_preprocessing);
      }
      if (typeof config.group_field === "string") setGroupField(config.group_field);
      if (typeof config.time_field === "string") setTimeField(config.time_field);
      if (typeof config.shuffle === "boolean") setShuffleFolds(config.shuffle);
      if (config.balance_method === "none" || config.balance_method === "undersample" || config.balance_method === "oversample" || config.balance_method === "smote") setBalanceMethod(config.balance_method);
      if (typeof config.minority_share === "number") setMinorityShare(config.minority_share);
      if (config.class_weight_policy === "balanced" || config.class_weight_policy === "none") setClassWeightPolicy(config.class_weight_policy);
      if (typeof config.test_dataset_id === "string") setTestDatasetId(config.test_dataset_id);
      if (typeof config.test_dataset_version_id === "string") {
        setTestDatasetVersion(config.test_dataset_version_id);
      }
      if (typeof config.test_target_field === "string") setTestTargetField(config.test_target_field);
      if (typeof config.oot_dataset_id === "string") setOotDatasetId(config.oot_dataset_id);
      if (typeof config.oot_dataset_version_id === "string") {
        setOotDatasetVersion(config.oot_dataset_version_id);
      }
      if (typeof config.oot_target_field === "string") setOotTargetField(config.oot_target_field);
      if (typeof config.approval_note === "string" && config.approval_note.trim()) setValidationRationale(config.approval_note);
      setDirty(false);
      const savedDraft = loadValidationDraft(datasetIdentity);
      if (savedDraft?.designDirty) {
        // The pre-EDA Analysis Partition owns holdout membership. A browser
        // draft may restore CV/balancing choices, never seed or holdout share.
        setFoldMethod(savedDraft.foldMethod);
        setFoldCount(savedDraft.foldCount);
        setFoldRepeats(savedDraft.foldRepeats);
        setInnerFoldCount(savedDraft.innerFoldCount);
        if (
          savedDraft.foldLocalPreprocessing === "fit_transform_per_fold" ||
          savedDraft.foldLocalPreprocessing === "model_native_per_fold"
        ) {
          setFoldLocalPreprocessing(savedDraft.foldLocalPreprocessing);
        }
        setGroupField(savedDraft.groupField);
        setTimeField(savedDraft.timeField);
        setShuffleFolds(savedDraft.shuffleFolds);
        setBalanceMethod(savedDraft.balanceMethod);
        setMinorityShare(savedDraft.minorityShare);
        setClassWeightPolicy(savedDraft.classWeightPolicy);
        setExternalValidationMode(savedDraft.externalValidationMode);
        setTestDatasetId(savedDraft.testDatasetId);
        setTestDatasetVersion(savedDraft.testDatasetVersion);
        setTestTargetField(savedDraft.testTargetField);
        setOotDatasetId(savedDraft.ootDatasetId);
        setOotDatasetVersion(savedDraft.ootDatasetVersion);
        setOotTargetField(savedDraft.ootTargetField);
        if (savedDraft.validationRationale?.trim()) setValidationRationale(savedDraft.validationRationale);
        setDesignDirty(true);
        setMessage(
          `Draft configuration restored from ${new Date(savedDraft.savedAt).toLocaleString()}.`,
        );
      } else {
        setDesignDirty(false);
      }
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
  }, [
    datasetIdentity?.dataset_id,
    datasetIdentity?.dataset_version_id,
    dataset?.target,
  ]);

  useEffect(() => {
    if (loading || !datasetIdentity) return;
    saveValidationDraft(datasetIdentity, {
      foldMethod,
      foldCount,
      foldRepeats,
      innerFoldCount,
      foldLocalPreprocessing,
      groupField,
      timeField,
      shuffleFolds,
      balanceMethod,
      minorityShare,
      classWeightPolicy,
      externalValidationMode,
      testDatasetId,
      testDatasetVersion,
      testTargetField,
      ootDatasetId,
      ootDatasetVersion,
      ootTargetField,
      validationRationale,
      designDirty,
      savedAt: new Date().toISOString(),
    });
  }, [
    balanceMethod,
    classWeightPolicy,
    designDirty,
    externalValidationMode,
    foldCount,
    foldMethod,
    foldRepeats,
    foldLocalPreprocessing,
    groupField,
    innerFoldCount,
    loading,
    minorityShare,
    ootDatasetId,
    ootDatasetVersion,
    ootTargetField,
    shuffleFolds,
    testDatasetId,
    testDatasetVersion,
    testTargetField,
    timeField,
    validationRationale,
    datasetIdentity?.dataset_id,
    datasetIdentity?.dataset_version_id,
  ]);

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
  const cvEnabled = true;
  const holdoutEnabled = true;
  const separateTestEnabled =
    externalValidationMode === "test" ||
    externalValidationMode === "test_oot";
  const ootEnabled =
    externalValidationMode === "oot" ||
    externalValidationMode === "test_oot";
  const selectedTestDataset = datasetOptions.find(
    (item) => item.datasetId === testDatasetId,
  );
  const selectedOotDataset = datasetOptions.find(
    (item) => item.datasetId === ootDatasetId,
  );

  function toggleFeature(name: string, checked: boolean) {
    setSelected((current) => checked ? [...new Set([...current, name])] : current.filter((item) => item !== name));
    setDirty(true);
    setMessage("");
  }

  function markDesignChanged() {
    setDesignDirty(true);
    setMessage("");
  }

  function chooseExternalValidationMode(mode: ExternalValidationMode) {
    setExternalValidationMode(mode);
    if (mode !== "test" && mode !== "test_oot") {
      setTestDatasetId("");
      setTestDatasetVersion("");
      setTestTargetField("");
    }
    if (mode !== "oot" && mode !== "test_oot") {
      setOotDatasetId("");
      setOotDatasetVersion("");
      setOotTargetField("");
    }
    setDesignDirty(true);
    setMessage("");
  }

  // Compatibility-only callback for the retired card-wall markup below the
  // active return. It is intentionally unreachable; the simplified workflow
  // is the only rendered experience.
  function chooseValidationStrategy(_strategy: ValidationStrategy) {
    // No-op. The standard path is always governed holdout plus CV.
  }

  function chooseExternalDataset(role: "test" | "oot", datasetId: string) {
    if (role === "test") {
      setTestDatasetId(datasetId);
      setTestDatasetVersion("");
      setTestTargetField(dataset?.target ?? "");
    } else {
      setOotDatasetId(datasetId);
      setOotDatasetVersion("");
      setOotTargetField(dataset?.target ?? "");
    }
    markDesignChanged();
  }

  async function previewPartitionReset() {
    if (!datasetIdentity) return;
    setLoadingPartitionImpacts(true);
    setError("");
    try {
      const response = await requestJson<{ impacts?: string[] }>(
        `/analysis-partitions/reset-impact?${new URLSearchParams({
          project_id: projectId,
          dataset_id: datasetIdentity.dataset_id,
          dataset_version_id: datasetIdentity.dataset_version_id,
        }).toString()}`,
      );
      setPartitionResetImpacts(response.impacts ?? []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ATLAS could not load the partition reset impact list.");
    } finally {
      setLoadingPartitionImpacts(false);
    }
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
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return;
    }
    if (!dataset?.target) {
      setError("The governed target is unavailable. Reload the exact project dataset identity before saving predictors.");
      return;
    }
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
      const saved = await saveFeatureManifest(
        datasetIdentity,
        updated,
        manifest.pipeline_steps,
      );
      setManifest(saved);
      setSelected(saved.features.filter((row) => row.selected && row.eligibility_status === "eligible").map((row) => row.feature_name));
      setDirty(false);
      const status = await requestJson<SplitStatus>(
        `/balancing_split/status?${new URLSearchParams({
          project_id: projectId,
          expected_dataset_id: datasetIdentity.dataset_id,
          expected_dataset_version_id: datasetIdentity.dataset_version_id,
        }).toString()}`,
      );
      verifySplitStatusIdentity(
        datasetIdentity,
        status,
        dataset.target,
        "Validation Design status response",
      );
      setSplitStatus(status);
      setMessage("Final predictor selection saved. Recreate the Validation Design against the same inherited Analysis Partition; sealed membership remains unchanged.");
      logDecision({
        workflowStep: "Training and Validation Design",
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

  async function createSplit(): Promise<SplitStatus> {
    if (!datasetIdentity) {
      throw new Error(datasetIdentityError);
    }
    if (!manifest || dirty) {
      throw new Error(
        "Save predictor changes before creating the Validation Design.",
      );
    }
    if (!splitStatus || !dataset?.target) {
      throw new Error(
        "Reload the exact sealed Analysis Partition before creating the Validation Design.",
      );
    }
    const exactPartition = verifySplitStatusIdentity(
      datasetIdentity,
      splitStatus,
      dataset.target,
      "Validation Design creation authority",
    );
    if (unavailableSelected.length) {
      throw new Error(
        "Return to Feature Engineering and materialize: " +
          unavailableSelected.map((row) => row.feature_name).join(", "),
      );
    }
    if (
      manifest.confirmation_status !== "confirmed" ||
      manifest.confirmed_manifest_hash !== manifest.manifest_hash
    ) {
      throw new Error(
        "Create and confirm the current feature manifest before defining validation.",
      );
    }
    if (separateTestEnabled && (!testDatasetId || !testDatasetVersion)) {
      throw new Error(
        "Select an immutable TEST version or disable external TEST.",
      );
    }
    if (ootEnabled && (!ootDatasetId || !ootDatasetVersion)) {
      throw new Error(
        "Select an immutable OOT version or disable external OOT.",
      );
    }
    if (cvEnabled && foldMethod === "none") {
      throw new Error("Select a cross-validation method.");
    }
    setCreating(true);
    setError("");
    setMessage("");
    try {
      const status = await requestJson<SplitStatus>("/balancing_split/config", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          analysis_partition_id: exactPartition.analysis_partition_id,
          analysis_partition_revision: exactPartition.revision,
          split_strategy: "hybrid",
          test_size: testSize,
          random_seed: randomSeed,
          stratify: inheritedStratify,
          balance_method: isClassification ? balanceMethod : "none",
          minority_share: minorityShare,
          problem_type: problemType,
          event_value: dataset?.event_value,
          selected_features: selected,
          feature_manifest_version: manifest.manifest_hash,
          dataset_id: datasetIdentity.dataset_id,
          dataset_version_id: datasetIdentity.dataset_version_id,
          dataset_version: datasetIdentity.dataset_version_id,
          development_dataset_id: datasetIdentity.dataset_id,
          development_dataset_version_id:
            datasetIdentity.dataset_version_id,
          external_validation_mode: externalValidationMode,
          test_dataset_id: separateTestEnabled ? testDatasetId : "",
          test_dataset_version_id: separateTestEnabled
            ? testDatasetVersion
            : "",
          test_target_field: testTargetField || dataset?.target || "",
          oot_dataset_id: ootEnabled ? ootDatasetId : "",
          oot_dataset_version_id: ootEnabled ? ootDatasetVersion : "",
          oot_target_field: ootTargetField || dataset?.target || "",
          fold_method: cvEnabled ? foldMethod : "none",
          fold_count: foldCount,
          repeats: foldRepeats,
          inner_fold_count: innerFoldCount,
          fold_local_preprocessing: foldLocalPreprocessing,
          group_field: groupField,
          time_field: timeField,
          shuffle: shuffleFolds,
          tuning_scope:
            foldMethod === "nested_cv"
              ? "nested_inner_folds"
              : cvEnabled
                ? "within_training_population"
                : "none",
          final_holdout_policy: "untouched_until_final_comparison",
          holdout_protection_confirmed: true,
          cv_design_approved: true,
          schema_compatibility_confirmed: false,
          target_mapping_verified: false,
          balancing_scope: "training_population_only",
          class_weight_policy: classWeightPolicy,
          threshold_optimization_policy: "evaluation_only",
          focal_loss_policy: "disabled",
          approval_note:
            validationRationale.trim() ||
            "Cross-validation stays inside the development population; the sealed final holdout remains evaluation-only.",
        }),
      });
      verifySplitStatusIdentity(
        datasetIdentity,
        status,
        dataset.target,
        "Created Validation Design response",
      );
      setSplitStatus(status);
      setDesignDirty(false);
      setManifest((current) => current ? { ...current, split_status: "current" } : current);
      setMessage(
        `Validation Design ${status.validation_design_version} created with split ${status.split_id} in ${(status.duration_ms ?? 0).toLocaleString()} ms.`,
      );
      logDecision({
        workflowStep: "Training and Validation Design",
        actionType: "workflow_setting_changed",
        subject: status.validation_design_id ?? status.split_id ?? "Governed validation design",
        previousValue: null,
        newValue: {
          validationStrategy,
          externalValidationMode,
          analysisPartitionId: exactPartition.analysis_partition_id,
          analysisPartitionRevision: exactPartition.revision,
          analysisPartitionEvidence: exactPartition.evidence_ref,
          foldMethod: cvEnabled ? foldMethod : "none",
          foldCount,
          foldRepeats,
          foldLocalPreprocessing,
          balanceMethod,
          classWeightPolicy,
          selectedFeatures: selected,
        },
        systemRecommendation: "Use hybrid stratified cross-validation inside training plus an untouched final holdout for the current HELOC workflow.",
        followStatus: "followed",
      });
      return status;
    } catch (cause) {
      const failure =
        cause instanceof Error
          ? cause
          : new Error("ATLAS could not create the validation split.");
      setError(failure.message);
      throw failure;
    } finally {
      setCreating(false);
    }
  }

  async function completeStep() {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return false;
    }
    if (splitStatus?.status === "current" && !dirty && !designDirty) {
      return true;
    }
    const status = await createSplit();
    await createEvidence({
      ...buildCanonicalEvidenceEnvelope(datasetIdentity, {
        manifestVersion: status.feature_manifest_version,
        splitId: status.split_id,
        validationDesignId: status.validation_design_id,
        validationDesignVersion: status.validation_design_version,
        trainingPopulationId: status.training_population_id,
        holdoutPopulationId: status.holdout_population_id,
      }),
      projectName,
      evidenceType: "governance",
      title: "Created Validation Design",
      summary: `${status.feature_count} predictors were bound to ${status.validation_design_version} and split ${status.split_id}. Cross-validation, holdout protection, external references, and training-only balancing are governed here.`,
      sourcePage: "Training and Validation Design",
      sourceRoute: "/step06",
      modelIds: [],
      documentIds: [],
      notebookIds: [],
      supportsSections: ["Feature Engineering", "Development Test and OOT Data", "Candidate Models"],
      tags: ["predictive_modeling", "feature_gate", "validation_design", "cross_validation"],
      status: "ready",
      importance: "high",
      payload: status,
    });
    return true;
  }

  const heroMetrics: AtlasWorkflowMetric[] = [
    { label: "Approved Predictors", value: selected.length.toLocaleString() },
    { label: "Engineered", value: engineeredSelected.toLocaleString(), tone: engineeredSelected ? "info" : "neutral" },
    { label: "Strategy", value: validationStrategyLabel(validationStrategy) },
    { label: "CV design", value: cvEnabled ? `${foldCount}-fold` : "Not used" },
    { label: "Holdout", value: holdoutEnabled && Number.isFinite(testSize) ? `${Math.round(testSize * 100)}% · inherited` : separateTestEnabled ? "External TEST" : "Loading" },
    { label: "Balancing", value: isClassification ? balanceMethod === "none" ? "None" : "Training only" : "Not applicable" },
    { label: "Design", value: statusLabel(splitStatus?.status), tone: splitStatus?.status === "current" && !designDirty ? "success" : splitStatus?.status === "stale" || designDirty ? "warning" : "neutral" },
    { label: "Readiness", value: splitStatus?.status === "current" && !dirty && !designDirty ? "Ready" : "Action required", tone: splitStatus?.status === "current" && !dirty && !designDirty ? "success" : "warning" },
  ];

  if (loading) {
    return (
      <StepShell title="Step 6: Training and Validation Design" subtitle="Reference the sealed Analysis Partition and establish the governed development-validation design." variant="preparation" heroMetrics={heroMetrics} nextDisabled>
        <div className="atlas-workflow-section flex min-h-64 items-center justify-center"><LoaderCircle size={30} className="animate-spin text-blue-600" /></div>
      </StepShell>
    );
  }

  const featureSignalMax = Math.max(
    ...eligibleFeatures.map((feature) => {
      const featureProfile = profileByName.get(feature.feature_name);
      return Math.abs(featureProfile ? featureMetric(featureProfile, problemType) ?? 0 : 0);
    }),
    0.0001,
  );
  const developmentTargetDistribution =
    splitStatus?.distributions?.train_before_balancing;
  const targetStats = resolveEventStats(developmentTargetDistribution);
  const eventSeverity = eventCountSeverity(targetStats?.events);
  const balanceProjectionShares = [0.2, 0.3, 0.4, 0.5];
  const manifestCurrent =
    !!manifest &&
    manifest.validation_status === "passed" &&
    manifest.materialization_status === "current" &&
    manifest.materialized_manifest_hash === manifest.manifest_hash &&
    manifest.confirmation_status === "confirmed" &&
    manifest.confirmed_manifest_hash === manifest.manifest_hash;
  const targetContractCurrent =
    !!dataset?.target &&
    !selected.includes(dataset.target) &&
    !(manifest?.predictor_authorization?.target_source_excluded ?? []).some(
      (name) => selected.includes(name),
    );
  const minimumFoldEvents = targetStats
    ? Math.floor(
        targetStats.events / Math.max(2, foldCount),
      )
    : null;
  const minimumFoldNonEvents = targetStats
    ? Math.floor(
        targetStats.nonEvents / Math.max(2, foldCount),
      )
    : null;
  const foldCoverageSufficient =
    typeof minimumFoldEvents === "number" &&
    typeof minimumFoldNonEvents === "number" &&
    minimumFoldEvents > 0 &&
    minimumFoldNonEvents > 0;
  const externalDatasetReady =
    (!separateTestEnabled ||
      (!!testDatasetId && !!testDatasetVersion)) &&
    (!ootEnabled || (!!ootDatasetId && !!ootDatasetVersion));
  const foldConstraintReady =
    foldMethod !== "none" &&
    (!["group_k_fold", "stratified_group_k_fold"].includes(foldMethod) ||
      !!groupField) &&
    (foldMethod !== "time_series" || !!timeField);
  const readinessItems = [
    {
      label: "Canonical dataset identity",
      ready: !!datasetIdentity,
    },
    {
      label: "Feature manifest current",
      ready: manifestCurrent && !dirty,
    },
    {
      label: "Target and target source validated",
      ready: targetContractCurrent,
    },
    {
      label: "Data Acquisition Analysis Partition sealed and current",
      ready:
        Boolean(splitStatus?.analysis_partition_id) &&
        Number(splitStatus?.analysis_partition_revision) > 0 &&
        String(splitStatus?.final_holdout_status ?? splitStatus?.analysis_partition?.final_holdout_status ?? "").toLowerCase() === "sealed",
    },
    {
      label: "Cross-validation selected",
      ready: foldConstraintReady,
    },
    {
      label: "Fold-local preprocessing recorded",
      ready:
        foldLocalPreprocessing === "fit_transform_per_fold" ||
        foldLocalPreprocessing === "model_native_per_fold",
    },
    {
      label: "Fold event counts sufficient",
      ready: !isClassification || foldCoverageSufficient,
    },
    {
      label: "Balancing policy recorded",
      ready:
        !isClassification ||
        (["none", "undersample", "oversample", "smote"] as BalanceMethod[]).includes(balanceMethod),
    },
    ...(externalValidationMode === "none"
      ? []
      : [
          {
            label: "External dataset versions pinned",
            ready: externalDatasetReady,
          },
        ]),
  ];
  const readinessBlockers = [
    !datasetIdentity ? datasetIdentityError : "",
    dirty
      ? "Save predictor changes or restore the current feature manifest."
      : "",
    !manifestCurrent
      ? "Create and confirm the current feature manifest before defining validation."
      : "",
    !splitStatus?.analysis_partition_id
      ? "Return to Data Acquisition and explicitly confirm the Analysis Partition before Validation Design."
      : "",
    unavailableSelected.length
      ? `Materialize ${unavailableSelected.length} engineered predictor${unavailableSelected.length === 1 ? "" : "s"} before validation.`
      : "",
    !selected.length
      ? "Select at least one eligible predictor."
      : "",
    !targetContractCurrent
      ? "Resolve the target or deterministic target-source exclusion before validation."
      : "",
    !developmentTargetDistribution
      ? "The governed development target distribution could not be loaded. Retry the Validation Design status request."
      : "",
    foldMethod === "none" ? "Select a cross-validation method." : "",
    ["group_k_fold", "stratified_group_k_fold"].includes(foldMethod) &&
    !groupField
      ? "Select a governed group field for group cross-validation."
      : "",
    foldMethod === "time_series" && !timeField
      ? "Select a governed time field for time-series cross-validation."
      : "",
    isClassification && !foldCoverageSufficient
      ? `At least one projected fold lacks event coverage. Reduce the number of folds from ${foldCount}.`
      : "",
    !externalDatasetReady
      ? separateTestEnabled && (!testDatasetId || !testDatasetVersion)
        ? "Select an immutable TEST version or disable external TEST."
        : "Select an immutable OOT version or disable external OOT."
      : "",
  ].filter(
    (value): value is string =>
      typeof value === "string" && value.length > 0,
  );
  const nextReady = readinessBlockers.length === 0;
  const readinessReason = nextReady
    ? "Ready. One action will validate, persist, create evidence, update MDD, and continue."
    : readinessBlockers[0];
  const previewDistributions: DistributionCollection =
    splitStatus?.status === "current" && !designDirty
      ? splitStatus.distributions
      : targetStats && developmentTargetDistribution
        ? {
            train_before_balancing: developmentTargetDistribution,
            train_after_balancing: developmentTargetDistribution,
            cv_folds: Array.from({ length: foldCount }, (_, index) => ({
              ...projectedDistribution(
                targetStats.events,
                targetStats.nonEvents,
                1 / Math.max(2, foldCount),
              ),
              repeat: 1,
              fold: index + 1,
            })),
          }
        : {};
  const readiness = { ready: nextReady, reason: readinessReason };
  return (
    <StepShell
      title=""
      hideHeader
      nextPath={getNextStepPath("step06")}
      nextDisabled={!nextReady || creating}
      nextDisabledReason={readinessReason}
      nextLabel={
        creating
          ? "Creating Validation Design..."
          : "Create Validation Design & Continue"
      }
      nextStatusLine={readinessReason}
      nextButtonTestId="create-validation-design-and-continue"
      onNext={completeStep}
      showEmbeddedNext
      nextAlwaysVisible
      nextFooterTestId="balance-split-sticky-footer"
    >
      <div className="prep-premium-page">
        <PreparationPageIdentity
          step="Step 6 of 13"
          title="Training and Validation Design"
          description="Review the inherited sealed Analysis Partition, then configure cross-validation, fold-local preprocessing, balancing, and external validation within development."
          datasetName={
            dataset?.dataset_library?.datasetName ||
            projectName ||
            "Registered dataset"
          }
          datasetVersion={
            datasetIdentity?.dataset_version_id || ""
          }
          target={dataset?.target || ""}
          predictorCount={selected.length}
          predictorManifest={manifest?.manifest_version || "Loading"}
          documentationStatus={
            splitStatus?.status === "current" && !designDirty
              ? "confirmed"
              : splitStatus?.status === "stale"
                ? "stale"
                : "draft"
          }
          decisionState={
            splitStatus?.status === "current" && !designDirty
              ? "Confirmed"
              : designDirty
                ? "Draft saved"
                : "Ready"
          }
          appearance="light"
        />

        <PreparationGovernanceDisclosure
          summary={`${selected.length.toLocaleString()} predictors · ${Math.round(testSize * 100)}% holdout · ${foldCount}-fold CV · ${statusLabel(splitStatus?.status)}`}
        >
          <AtlasStatusStrip
          items={[
            {
              label: "Feature manifest",
              state: manifestCurrent && !dirty ? "complete" : "blocked",
              detail: manifest?.manifest_hash,
            },
            {
              label: "Untouched holdout",
              state: testSize ? "complete" : "blocked",
              detail: `${Math.round(testSize * 100)}%`,
            },
            {
              label: "CV inside training",
              state: foldConstraintReady ? "complete" : "blocked",
              detail: `${foldCount}-fold · ${foldMethod.replace(/_/g, " ")}`,
            },
            {
              label: "Validation Design",
              state:
                splitStatus?.status === "current" && !designDirty
                  ? "complete"
                  : splitStatus?.status === "stale" || designDirty
                    ? "warning"
                    : "pending",
              detail:
                splitStatus?.validation_design_version ??
                statusLabel(splitStatus?.status),
            },
            ]}
          />
        </PreparationGovernanceDisclosure>

        {error ? (
          <AtlasAttentionPanel
            title="Training and Validation Design requires attention"
            tone="danger"
          >
            {error}
          </AtlasAttentionPanel>
        ) : null}
        {message ? (
          <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-950">
            {message}
          </div>
        ) : null}

        <AtlasWorkflowSection
          eyebrow="Recommended standard workflow"
          title="1. Review Inherited Analysis Partition"
          description="Data Acquisition already created the development and sealed final-holdout membership. Review that read-only authority here, then define validation within development."
          tone="info"
          action={
            <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">
              Recommended
            </span>
          }
        >
          <div className="mb-4 rounded-xl border border-blue-200 bg-blue-50/60 p-4" data-testid="immutable-analysis-partition">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <ShieldCheck size={16} className="text-blue-700" />
                  <h3 className="text-sm font-semibold text-slate-950">Data Acquisition Analysis Partition · read-only reference</h3>
                </div>
                <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-600">
                  Validation Design reuses the exact development and sealed final-holdout membership confirmed in Data Acquisition. Only cross-validation inside development and training-only policies can be configured here.
                </p>
              </div>
              <button type="button" className="atlas-secondary-button" disabled={loadingPartitionImpacts} onClick={() => void previewPartitionReset()}>
                {loadingPartitionImpacts ? <LoaderCircle size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                Review exceptional reset impact
              </button>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4" data-testid="analysis-partition-read-only-summary">
              <Metric label="Analysis Partition" value={splitStatus?.analysis_partition_id ?? "Unavailable"} tone={splitStatus?.analysis_partition_id ? "success" : "warning"} />
              <Metric label="Revision" value={splitStatus?.analysis_partition_revision ?? "Unavailable"} />
              <Metric label="Development partition" value={splitStatus?.development_partition_id ?? "Unavailable"} />
              <Metric label="Sealed holdout partition" value={splitStatus?.sealed_holdout_partition_id ?? "Unavailable"} tone={splitStatus?.sealed_holdout_partition_id ? "success" : "warning"} />
              <Metric label="Development rows" value={formatInteger(splitStatus?.analysis_partition?.development_rows ?? splitStatus?.analysis_partition?.development_count)} />
              <Metric label="Final holdout rows" value={formatInteger(splitStatus?.analysis_partition?.holdout_rows ?? splitStatus?.analysis_partition?.holdout_count)} />
              <Metric label="Development / holdout" value={Number.isFinite(testSize) ? `${Math.round((1 - testSize) * 100)}% / ${Math.round(testSize * 100)}%` : "Unavailable"} />
              <Metric label="Partition method" value={splitStatus?.analysis_partition?.partition_method ?? "Unavailable"} />
              <Metric label="Seed" value={Number.isSafeInteger(randomSeed) ? randomSeed : "Unavailable"} />
              <Metric label="Stratification policy" value={splitStatus?.analysis_partition?.stratification_policy ?? "Unavailable"} />
              <Metric label="Stratification field" value={splitStatus?.analysis_partition?.stratification_field ?? "Not applicable"} />
              <Metric label="Seal" value={splitStatus?.analysis_partition?.final_holdout_status ?? splitStatus?.final_holdout_status ?? "Unavailable"} tone={String(splitStatus?.analysis_partition?.final_holdout_status ?? splitStatus?.final_holdout_status).toLowerCase() === "sealed" ? "success" : "warning"} />
              <Metric label="Created by" value={typeof splitStatus?.analysis_partition?.created_by === "string" ? splitStatus.analysis_partition.created_by : splitStatus?.analysis_partition?.created_by?.display_name ?? splitStatus?.analysis_partition?.created_by?.user_id ?? "Unavailable"} />
              <Metric label="Created at" value={splitStatus?.analysis_partition?.created_at ? new Date(splitStatus.analysis_partition.created_at).toLocaleString() : "Unavailable"} />
              <Metric label="Evidence" value={splitStatus?.analysis_partition?.evidence_ref ?? splitStatus?.analysis_partition?.evidence_id ?? splitStatus?.analysis_partition?.evidence_status ?? "Unavailable"} />
              <Metric label="MDD" value={splitStatus?.analysis_partition?.mdd_ref ?? splitStatus?.analysis_partition?.mdd_status ?? "Unavailable"} />
            </div>
            {splitStatus?.analysis_partition?.evidence_ref || splitStatus?.analysis_partition?.evidence_id ? (
              <Link className="atlas-secondary-button mt-3" to={`/model-evidence-center?evidenceId=${encodeURIComponent(String(splitStatus.analysis_partition.evidence_ref ?? splitStatus.analysis_partition.evidence_id))}`}>
                View Partition Evidence
              </Link>
            ) : (
              <span className="mt-3 inline-flex rounded-lg border border-slate-300 bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-500" aria-disabled="true">
                Partition evidence unavailable
              </span>
            )}
            {partitionResetImpacts.length ? (
              <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3" data-testid="analysis-partition-reset-impact">
                <div className="text-xs font-semibold text-amber-950">Reset requires explicit acknowledgement in Data Acquisition and invalidates:</div>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-5 text-amber-900">
                  {partitionResetImpacts.map((impact) => <li key={impact}>{impact.replace(/_/g, " ")}</li>)}
                </ul>
                <Link
                  className="atlas-secondary-button mt-3"
                  to={`${projectWorkflowRoute(projectId, "/step01")}?analysisPartition=reset`}
                >
                  Return to Data Acquisition to reset
                </Link>
              </div>
            ) : null}
          </div>
          <div
            className="grid gap-3 lg:grid-cols-2"
            data-testid="validation-design-summary"
          >
            <DesignStep
              number="1"
              title="Inherited Development / Final Holdout"
              detail={`Data Acquisition assigned ${Math.round((1 - testSize) * 100)}% to development and sealed ${Math.round(testSize * 100)}% for final evaluation. Optional external TEST and OOT populations remain separate.`}
              complete={testSize >= 0.1}
            />
            <DesignStep
              number="2"
              title="Cross-Validation Inside Training"
              detail={`${foldCount}-fold ${foldMethod.replace(/_/g, " ")} estimates stability without exposing the final holdout.`}
              complete={foldConstraintReady}
            />
            <DesignStep
              number="3"
              hidden
              title="Training-only balancing policy"
              detail={
                balanceMethod === "none"
                  ? "No resampling · holdout unchanged"
                  : `${balanceMethodLabel(balanceMethod)} · training only`
              }
              complete={balanceMethod === "none"}
            />
            <DesignStep
              number="4"
              hidden
              title="Create and continue"
              detail="One action persists the Validation Design, exact CV folds, evidence, and MDD handoff without changing partition membership."
              complete={
                splitStatus?.status === "current" && !designDirty
              }
            />
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            <Metric
              label="Full governed rows"
              value={
                profile?.registeredRowCount?.toLocaleString() ??
                "Unavailable"
              }
              tone="info"
            />
            <Metric
              label="Training share"
              value={`${Math.round((1 - testSize) * 100)}%`}
            />
            <Metric
              label="Holdout share"
              value={`${Math.round(testSize * 100)}%`}
              tone="success"
            />
            <Metric label="CV scope" value="Inside training only" />
            <Metric
              label="External validation"
              value={
                externalValidationMode === "none"
                  ? "Optional · not enabled"
                  : externalValidationMode.replace("_", " + ").toUpperCase()
              }
            />
          </div>
        </AtlasWorkflowSection>

        <AtlasWorkflowSection
          eyebrow="Core path"
          title="2. Configure Cross-Validation"
          description="The sealed Analysis Partition is inherited from Data Acquisition. Configure cross-validation within development; draft changes save automatically."
          tone="neutral"
          action={
            <AtlasExecutionStatus
              state={creating ? "running" : designDirty ? "idle" : "complete"}
              label={
                creating
                  ? "Creating design"
                  : designDirty
                    ? "Draft auto-saved"
                    : "Configuration current"
              }
            />
          }
        >
          <div
            className="grid gap-4 lg:grid-cols-3"
            data-testid="holdout-cv-controls"
          >
            <label>
              <span className="atlas-label">Fold method</span>
              <select
                className="atlas-input mt-1"
                value={foldMethod}
                onChange={(event) => {
                  setFoldMethod(event.target.value as FoldMethod);
                  markDesignChanged();
                }}
              >
                {isClassification ? (
                  <option value="stratified_k_fold">
                    Stratified K-fold · recommended
                  </option>
                ) : null}
                <option value="k_fold">K-fold</option>
                {isClassification ? (
                  <option value="repeated_stratified_k_fold">
                    Repeated stratified K-fold
                  </option>
                ) : null}
                <option value="group_k_fold">Group K-fold</option>
                {isClassification ? (
                  <option value="stratified_group_k_fold">
                    Stratified group K-fold
                  </option>
                ) : null}
                <option value="time_series">Time-series split</option>
                <option value="nested_cv">Nested CV · advanced</option>
              </select>
            </label>
            <label>
              <span className="atlas-label">Number of folds</span>
              <select
                className="atlas-input mt-1"
                value={foldCount}
                onChange={(event) => {
                  setFoldCount(Number(event.target.value));
                  markDesignChanged();
                }}
              >
                {[3, 4, 5, 6, 8, 10].map((value) => (
                  <option key={value} value={value}>
                    {value} folds{value === 5 ? " · recommended" : ""}
                  </option>
                ))}
              </select>
            </label>
            {foldMethod === "repeated_stratified_k_fold" ? (
              <label>
                <span className="atlas-label">Number of repeats</span>
                <select
                  className="atlas-input mt-1"
                  value={foldRepeats}
                  onChange={(event) => {
                    setFoldRepeats(Number(event.target.value));
                    markDesignChanged();
                  }}
                >
                  {[2, 3, 5, 10].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {foldMethod === "nested_cv" ? (
              <label>
                <span className="atlas-label">Inner tuning folds</span>
                <select
                  className="atlas-input mt-1"
                  value={innerFoldCount}
                  onChange={(event) => {
                    setInnerFoldCount(Number(event.target.value));
                    markDesignChanged();
                  }}
                >
                  {[2, 3, 4, 5].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {foldMethod === "group_k_fold" ||
            foldMethod === "stratified_group_k_fold" ? (
              <label>
                <span className="atlas-label">Governed group field</span>
                <select
                  className="atlas-input mt-1"
                  value={groupField}
                  onChange={(event) => {
                    setGroupField(event.target.value);
                    markDesignChanged();
                  }}
                >
                  <option value="">Select group field</option>
                  {eligibleFeatures.map((feature) => (
                    <option
                      key={feature.feature_name}
                      value={feature.feature_name}
                    >
                      {feature.feature_name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {foldMethod === "time_series" ? (
              <label>
                <span className="atlas-label">Governed time field</span>
                <select
                  className="atlas-input mt-1"
                  value={timeField}
                  onChange={(event) => {
                    setTimeField(event.target.value);
                    markDesignChanged();
                  }}
                >
                  <option value="">Select time field</option>
                  {eligibleFeatures.map((feature) => (
                    <option
                      key={feature.feature_name}
                      value={feature.feature_name}
                    >
                      {feature.feature_name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <label className="flex items-center gap-2 self-end rounded-lg border border-violet-200 bg-violet-50 px-3 py-2.5 text-xs font-semibold text-slate-700">
              <input
                type="checkbox"
                checked={shuffleFolds}
                disabled={foldMethod === "time_series"}
                onChange={(event) => {
                  setShuffleFolds(event.target.checked);
                  markDesignChanged();
                }}
              />
              Shuffle before folding
            </label>
            <label>
              <span className="atlas-label">Fold-local preprocessing</span>
              <select
                className="atlas-input mt-1"
                data-testid="fold-local-preprocessing"
                value={foldLocalPreprocessing}
                onChange={(event) => {
                  setFoldLocalPreprocessing(
                    event.target.value as FoldLocalPreprocessingPolicy,
                  );
                  markDesignChanged();
                }}
              >
                <option value="fit_transform_per_fold">
                  Fit and transform independently within each fold · recommended
                </option>
                <option value="model_native_per_fold">
                  Model-native preprocessing within each fold
                </option>
              </select>
              <span className="mt-1 block text-xs text-slate-500">
                Preprocessing is fitted on each fold&apos;s training rows only; validation-fold and final-holdout values never influence fitted transforms.
              </span>
            </label>
          </div>
          <label className="mt-4 block" data-testid="validation-design-rationale">
            <span className="atlas-label">Validation design rationale</span>
            <textarea
              className="atlas-input mt-1 min-h-20"
              value={validationRationale}
              onChange={(event) => {
                setValidationRationale(event.target.value);
                markDesignChanged();
              }}
              placeholder="Record why this cross-validation and balancing design is appropriate."
            />
            <span className="mt-1 block text-xs text-slate-500">This rationale documents the configurable development-population design; it cannot alter the sealed final holdout.</span>
          </label>
          <div className="mt-4 grid gap-3 lg:grid-cols-3">
            <ProtectionStatement
              title="CV stays inside training"
              detail="Every tuning and comparison fold is drawn only from the training population."
            />
            <ProtectionStatement
              title="Holdout remains untouched"
              detail="No tuning, resampling, threshold selection, or candidate filtering uses the holdout."
            />
            <ProtectionStatement
              title="Draft auto-save"
              detail="Configuration changes persist locally; the final action creates the governed contract."
            />
          </div>
        </AtlasWorkflowSection>

        <div className="grid gap-3 xl:grid-cols-[minmax(0,1.65fr)_minmax(300px,0.7fr)]">
          <PopulationPartitionVisual
            strategy="hybrid"
            holdoutSize={testSize}
            folds={foldCount}
            randomSeed={randomSeed}
            testLabel={selectedTestDataset?.name}
            ootLabel={selectedOotDataset?.name}
            distributions={previewDistributions}
            hasTest={separateTestEnabled}
            hasOot={ootEnabled}
          />
          <FoldArchitectureVisual
            method={foldMethod}
            foldCount={foldCount}
            architecture={splitStatus?.fold_architecture}
            distributions={previewDistributions}
            dirty={designDirty}
          />
        </div>

        <AtlasWorkflowSection
          eyebrow="Target integrity"
          title="4. Class Preservation Summary"
          description="Development-population and fold counts come from the governed training population. The sealed final holdout is not inspected or used for this design."
          tone={targetStats ? "success" : "warning"}
          action={
            targetStats ? (
              <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">
                Development event rate · {formatPercent(targetStats.eventRate)}
              </span>
            ) : undefined
          }
        >
          {targetStats ? (
            <>
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
                <Metric
                  label="Development rows"
                  value={targetStats.rows.toLocaleString()}
                />
                <Metric
                  label="Events"
                  value={targetStats.events.toLocaleString()}
                  tone="success"
                />
                <Metric
                  label="Non-events"
                  value={targetStats.nonEvents.toLocaleString()}
                />
                <Metric
                  label="Event rate"
                  value={formatPercent(targetStats.eventRate)}
                  tone="info"
                />
                <Metric
                  label="Minimum events per fold"
                  value={minimumFoldEvents?.toLocaleString() ?? "Pending"}
                  tone={foldCoverageSufficient ? "success" : "warning"}
                />
              </div>
              <div className="mt-4">
                <ClassBalancePreservationVisual
                  distributions={previewDistributions}
                />
              </div>
              <p className="mt-3 text-xs leading-5 text-slate-600">
                {eventSeverity.label}. Every projected validation fold contains
                events and non-events based only on development-population
                evidence. No final-holdout target information is used.
              </p>
            </>
          ) : (
            <AtlasAttentionPanel
              title="Target distribution request failed"
              tone="danger"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <span>
                  ATLAS could not load governed development event/non-event
                  counts. Retry before creating the Validation Design.
                </span>
                <button
                  type="button"
                  className="atlas-secondary-button"
                  onClick={() => void loadPage()}
                >
                  <RefreshCw size={15} /> Retry target distribution
                </button>
              </div>
            </AtlasAttentionPanel>
          )}
        </AtlasWorkflowSection>

        <section data-testid="advanced-balancing-settings">
          <AtlasWorkflowSection
            eyebrow="Training population only"
            title="Advanced Balancing Settings"
            description={`Current policy: ${balanceMethodLabel(balanceMethod)}. Balancing can modify only training rows; it never changes the untouched holdout, TEST, or OOT populations.`}
            tone="neutral"
            action={
              <span className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-800">
                Current policy · {balanceMethodLabel(balanceMethod)}
              </span>
            }
          >
            {isClassification ? (
              <>
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                <BalanceMethodCard
                  active={balanceMethod === "none"}
                  title="No resampling"
                  description="Preserve every training row. Preferred for the approximately balanced HELOC target."
                  onClick={() => {
                    setBalanceMethod("none");
                    markDesignChanged();
                  }}
                />
                <BalanceMethodCard
                  active={balanceMethod === "undersample"}
                  title="Undersample majority"
                  description="Applied only to each training fold after the validation fold is isolated."
                  onClick={() => {
                    setBalanceMethod("undersample");
                    markDesignChanged();
                  }}
                />
                <BalanceMethodCard
                  active={balanceMethod === "oversample"}
                  title="Oversample minority"
                  description="Applied only to each training fold; validation and holdout rows remain observed."
                  onClick={() => {
                    setBalanceMethod("oversample");
                    markDesignChanged();
                  }}
                />
                <BalanceMethodCard
                  active={balanceMethod === "smote"}
                  title="SMOTE"
                  description="Training only; synthetic rows never cross fold or holdout boundaries."
                  onClick={() => {
                    setBalanceMethod("smote");
                    markDesignChanged();
                  }}
                />
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <label>
                  <span className="atlas-label">Class weights</span>
                  <select
                    className="atlas-input mt-1"
                    value={classWeightPolicy}
                    onChange={(event) => {
                      setClassWeightPolicy(
                        event.target.value as "none" | "balanced",
                      );
                      markDesignChanged();
                    }}
                  >
                    <option value="none">
                      No class weights · recommended
                    </option>
                    <option value="balanced">
                      Balanced class weights
                    </option>
                  </select>
                </label>
                {balanceMethod !== "none" ? (
                  <label>
                    <span className="atlas-label">
                      Target minority share
                    </span>
                    <select
                      className="atlas-input mt-1"
                      value={minorityShare}
                      onChange={(event) => {
                        setMinorityShare(Number(event.target.value));
                        markDesignChanged();
                      }}
                    >
                      {[0.2, 0.3, 0.4, 0.5].map((value) => (
                        <option key={value} value={value}>
                          {Math.round(value * 100)}%
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">
                  <strong>Later-stage policies:</strong>
                  <br />
                  Threshold optimization: Evaluation only
                  <br />
                  Focal loss: supported models only, currently disabled
                </div>
                </div>
                {balanceMethod !== "none" ? (
                  <AtlasAttentionPanel
                    title="Fold-local resampling selected"
                    tone="info"
                  >
                    ATLAS will apply {balanceMethodLabel(balanceMethod).toLowerCase()} independently within each training fold under the selected fold-local preprocessing policy. Validation folds, the sealed final holdout, TEST, and OOT rows remain unchanged.
                  </AtlasAttentionPanel>
                ) : null}
              </>
            ) : (
              <div className="text-sm leading-6 text-slate-600">
                Class balancing is not applicable to regression. Training and
                validation populations retain their observed distributions.
              </div>
            )}
          </AtlasWorkflowSection>
        </section>

        <section data-testid="advanced-external-validation">
          <AtlasWorkflowSection
            eyebrow="Optional governed validation"
            title="Advanced External Validation Data"
            description="Attach separate TEST or out-of-time datasets when they are part of the validation design. These controls remain visible so the full evaluation architecture can be reviewed before training."
            tone="neutral"
            action={
              <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-semibold uppercase text-slate-600">
                {externalValidationMode === "none"
                  ? "Not enabled"
                  : externalValidationMode.replace("_", " + ")}
              </span>
            }
          >
            <div className="mt-4 border-t border-slate-200 pt-4">
              <p className="text-xs leading-5 text-slate-600">
                External validation datasets are optional. They may also be
                attached later during Scoring and Out-of-Time Validation.
                Supported governed architectures remain Holdout from Current
                Development Dataset, Separate TEST Dataset, Separate TEST and
                OOT Datasets, Cross-Validation Strategy, and Hybrid Holdout plus
                Cross-Validation.
              </p>
              <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {[
                ["none", "No external dataset"],
                ["test", "Use separate TEST dataset"],
                ["oot", "Use OOT dataset"],
                ["test_oot", "Use both TEST and OOT"],
              ].map(([value, label]) => (
                <label
                  key={value}
                  className={`flex items-center gap-2 rounded-lg border p-3 text-xs font-semibold ${
                    externalValidationMode === value
                      ? "border-cyan-400 bg-cyan-50 text-cyan-950"
                      : "border-slate-200 bg-white text-slate-700"
                  }`}
                >
                  <input
                    type="radio"
                    name="external-validation-mode"
                    checked={externalValidationMode === value}
                    onChange={() =>
                      chooseExternalValidationMode(
                        value as ExternalValidationMode,
                      )
                    }
                  />
                  {label}
                </label>
              ))}
              </div>
              {separateTestEnabled || ootEnabled ? (
                <div
                  className="mt-4 grid gap-4 lg:grid-cols-2"
                  data-testid="external-validation-datasets"
                >
                {separateTestEnabled ? (
                  <ExternalDatasetPicker
                    role="TEST"
                    datasets={datasetOptions}
                    datasetId={testDatasetId}
                    versionId={testDatasetVersion}
                    targetField={testTargetField || dataset?.target || ""}
                    onDataset={(value) =>
                      chooseExternalDataset("test", value)
                    }
                    onVersion={(value) => {
                      setTestDatasetVersion(value);
                      markDesignChanged();
                    }}
                    onTarget={(value) => {
                      setTestTargetField(value);
                      markDesignChanged();
                    }}
                  />
                ) : null}
                {ootEnabled ? (
                  <ExternalDatasetPicker
                    role="OOT"
                    datasets={datasetOptions}
                    datasetId={ootDatasetId}
                    versionId={ootDatasetVersion}
                    targetField={ootTargetField || dataset?.target || ""}
                    onDataset={(value) =>
                      chooseExternalDataset("oot", value)
                    }
                    onVersion={(value) => {
                      setOotDatasetVersion(value);
                      markDesignChanged();
                    }}
                    onTarget={(value) => {
                      setOotTargetField(value);
                      markDesignChanged();
                    }}
                  />
                ) : null}
                </div>
              ) : null}
            </div>
          </AtlasWorkflowSection>
        </section>

        <section data-testid="compact-final-predictor-review">
          <AtlasWorkflowSection
            eyebrow="Training input contract"
            title="Final Predictor Review"
            description={`${selected.length} included · ${Math.max(
              0,
              eligibleFeatures.length - selected.length,
            )} excluded · ${engineeredSelected} engineered · manifest ${
              manifestCurrent ? "current" : "requires attention"
            }`}
            tone={manifestCurrent ? "success" : "warning"}
            action={
              <span className="flex flex-wrap items-center justify-end gap-2">
                <Link to={projectWorkflowRoute(projectId, "/step05")} className="atlas-secondary-button">
                  Return to Feature Engineering
                </Link>
                <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[10px] font-semibold text-blue-800">
                  View Full Predictor Contract
                </span>
              </span>
            }
          >
            <div className="mt-4 border-t border-slate-200 pt-4">
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
              <Metric label="Eligible" value={eligibleFeatures.length} />
              <Metric
                label="Included"
                value={selected.length}
                tone="success"
              />
              <Metric
                label="Excluded"
                value={Math.max(
                  0,
                  eligibleFeatures.length - selected.length,
                )}
              />
              <Metric
                label="Engineered"
                value={engineeredSelected}
                tone={engineeredSelected ? "info" : "neutral"}
              />
              <Metric
                label="Target-source fields present"
                value={
                  (manifest?.predictor_authorization
                    ?.target_source_excluded ?? []
                  ).some((name) => selected.includes(name))
                    ? "Review required"
                    : "None"
                }
                tone="success"
              />
              </div>
              <div className="mt-4 flex flex-col gap-2 xl:flex-row xl:items-end xl:justify-between">
              <label className="min-w-64 flex-1">
                <span className="atlas-label">Search predictors</span>
                <span className="relative block">
                  <Search
                    size={15}
                    className="pointer-events-none absolute left-3 top-2.5 text-slate-400"
                  />
                  <input
                    className="atlas-input pl-9"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Feature, origin, or source variable"
                  />
                </span>
              </label>
              <div className="flex flex-wrap items-end gap-2">
                <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700">
                  <input
                    type="checkbox"
                    checked={selectedOnly}
                    onChange={(event) =>
                      setSelectedOnly(event.target.checked)
                    }
                  />
                  Selected only
                </label>
                <button
                  type="button"
                  className="atlas-secondary-button"
                  onClick={() => {
                    setSelected(initialSelection);
                    setDirty(true);
                    setMessage(
                      "The original Data Acquisition selection was restored for review.",
                    );
                  }}
                >
                  <RefreshCw size={15} /> Restore manifest selection
                </button>
                <button
                  type="button"
                  className="atlas-primary-button"
                  disabled={saving || !dirty}
                  onClick={() => void saveSelection()}
                >
                  {saving ? (
                    <LoaderCircle size={15} className="animate-spin" />
                  ) : (
                    <Save size={15} />
                  )}
                  Save predictor changes
                </button>
              </div>
              </div>
              <div className="mt-4 max-h-[460px] overflow-auto rounded-xl border border-slate-200 bg-white shadow-sm">
                <table className="w-full min-w-[720px] table-fixed border-separate border-spacing-0 text-xs">
                <thead className="sticky top-0 z-20 bg-slate-950 text-white shadow-sm">
                  <tr>
                    <th className="w-14 px-3 py-3 text-left">Use</th>
                    <th className="w-[30%] px-4 py-3 text-left">
                      Predictor and lineage
                    </th>
                    <th className="w-[25%] px-4 py-3 text-left">
                      Signal evidence
                    </th>
                    <th className="w-[19%] px-4 py-3 text-left">
                      Data quality
                    </th>
                    <th className="w-[26%] px-4 py-3 text-left">
                      Training readiness
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visibleFeatures.map((feature) => (
                    <FeatureRow
                      key={feature.feature_id}
                      feature={feature}
                      profile={profileByName.get(feature.feature_name)}
                      selected={selected.includes(feature.feature_name)}
                      problemType={problemType}
                      signalMax={featureSignalMax}
                      onToggle={toggleFeature}
                    />
                  ))}
                </tbody>
                </table>
              </div>
            </div>
          </AtlasWorkflowSection>
        </section>

        <AtlasWorkflowSection
          eyebrow="Exact completion path"
          title="Validation Design Readiness"
          description="Only actual blockers appear here. There is no separate save, self-approval, confirmation, and continue sequence."
          tone={nextReady ? "success" : "warning"}
          action={
            <AtlasExecutionStatus
              state={nextReady ? "complete" : "idle"}
              label={nextReady ? "Ready to create" : "Blocked"}
              detail={nextReady ? "Single action" : readinessReason}
            />
          }
        >
          <ValidationReadinessChecklist items={readinessItems} />
          <div
            className={`mt-4 rounded-lg border p-3 text-sm ${
              nextReady
                ? "border-emerald-200 bg-emerald-50 text-emerald-950"
                : "border-amber-200 bg-amber-50 text-amber-950"
            }`}
            data-testid="validation-readiness-blocker"
          >
            <div className="font-semibold">
              {nextReady ? "Ready for the final action" : "Next required action"}
            </div>
            <div className="mt-1">{readinessReason}</div>
          </div>
          <p className="mt-3 text-xs leading-5 text-slate-500">
            Create Validation Design &amp; Continue validates the design,
            persists the exact CV folds and fold-local policies against the inherited
            partition, creates Evidence Center evidence, updates the MDD, and navigates
            to Model Training without changing development or holdout membership.
          </p>
        </AtlasWorkflowSection>

        {splitStatus?.status === "current" && !designDirty ? (
          <AtlasWorkflowSection
            eyebrow="Persisted result"
            title="Successful Validation Design"
            description="Backend-confirmed population IDs, folds, compatibility checks, risks, and completion gates."
            tone="success"
          >
            <div className="grid gap-3 lg:grid-cols-2">
              <DistributionPanel
                title="Development training population"
                subtitle={balanceMethodSubtitle(balanceMethod)}
                distribution={
                  splitStatus.distributions.train_after_balancing
                }
                before={
                  splitStatus.distributions.train_before_balancing
                }
              />
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950">
                <div className="flex items-center gap-2 font-semibold">
                  <ShieldCheck size={16} /> Final holdout remains sealed
                </div>
                <p className="mt-2 text-xs leading-5">
                  This page does not inspect final-holdout target counts or rates.
                  The inherited population is reserved for final evaluation only.
                </p>
              </div>
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              <Metric
                label="Validation Design ID"
                value={
                  splitStatus.validation_design_id ?? "Unavailable"
                }
                tone="success"
              />
              <Metric
                label="Design version"
                value={
                  splitStatus.validation_design_version ?? "Unavailable"
                }
                tone="success"
              />
              <Metric
                label="Split ID"
                value={splitStatus.split_id ?? "Unavailable"}
              />
              <Metric
                label="Training population ID"
                value={
                  splitStatus.training_population_id ?? "Unavailable"
                }
              />
              <Metric
                label="Holdout population ID"
                value={
                  splitStatus.holdout_population_id ?? "Unavailable"
                }
              />
              <Metric
                label="Train rows"
                value={(splitStatus.n_train ?? 0).toLocaleString()}
              />
              <Metric
                label="Holdout rows"
                value={(splitStatus.n_test ?? 0).toLocaleString()}
              />
              <Metric
                label="Execution"
                value={`${(
                  splitStatus.execution_ms ??
                  splitStatus.duration_ms ??
                  0
                ).toLocaleString()} ms`}
                tone="success"
              />
            </div>
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <ValidationRiskSummary
                risks={splitStatus.validation_risks ?? []}
              />
              <ValidationCompletionGates
                gates={splitStatus.completion_gates ?? {}}
              />
            </div>
            {separateTestEnabled || ootEnabled ? (
              <div className="mt-4">
                <DatasetCompatibilityMatrix
                  matrix={splitStatus.compatibility_matrix}
                />
              </div>
            ) : null}
          </AtlasWorkflowSection>
        ) : null}
      </div>
    </StepShell>
  );
}

function validationStrategyLabel(strategy: ValidationStrategy) {
  if (strategy === "holdout_current") return "Current data holdout";
  if (strategy === "separate_test") return "Separate TEST";
  if (strategy === "separate_test_oot") return "TEST + OOT";
  if (strategy === "cross_validation") return "Cross-validation only";
  return "Hybrid holdout + CV";
}

function ValidationStrategyCard({
  strategy,
  selected,
  recommended = false,
  title,
  description,
  onSelect,
}: {
  strategy: ValidationStrategy;
  selected: boolean;
  recommended?: boolean;
  title: string;
  description: string;
  onSelect: (strategy: ValidationStrategy) => void;
}) {
  return (
    <button
      type="button"
      className={`relative min-h-44 rounded-xl border p-4 text-left transition ${
        selected
          ? "border-blue-600 bg-blue-50 shadow-sm ring-1 ring-blue-200"
          : "border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50/40"
      }`}
      onClick={() => onSelect(strategy)}
      aria-pressed={selected}
    >
      {recommended ? (
        <span className="absolute right-3 top-3 rounded-full bg-emerald-100 px-2 py-1 text-[9px] font-bold uppercase tracking-wide text-emerald-800">
          Preferred for HELOC
        </span>
      ) : null}
      <CircleDot size={17} className={selected ? "text-blue-700" : "text-slate-400"} />
      <span className="mt-3 block pr-10 text-sm font-semibold leading-5 text-slate-950">
        {title}
      </span>
      <span className="mt-2 block text-xs leading-5 text-slate-600">{description}</span>
      <span className={`mt-3 inline-flex rounded-full border px-2 py-1 text-[10px] font-bold uppercase ${
        selected
          ? "border-blue-200 bg-white text-blue-800"
          : "border-slate-200 bg-slate-50 text-slate-500"
      }`}>
        {selected ? "Selected" : "Available"}
      </span>
    </button>
  );
}

function ExternalDatasetPicker({
  role,
  datasets,
  datasetId,
  versionId,
  targetField,
  onDataset,
  onVersion,
  onTarget,
}: {
  role: "TEST" | "OOT";
  datasets: DatasetOption[];
  datasetId: string;
  versionId: string;
  targetField: string;
  onDataset: (value: string) => void;
  onVersion: (value: string) => void;
  onTarget: (value: string) => void;
}) {
  const selected = datasets.find((item) => item.datasetId === datasetId);
  return (
    <div className="rounded-lg border border-cyan-200 bg-white p-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
        {role === "OOT" ? <CalendarClock size={15} className="text-cyan-700" /> : <Database size={15} className="text-cyan-700" />}
        {role} dataset contract
      </div>
      <div className="mt-3 space-y-3">
        <label>
          <span className="atlas-label">{role} dataset</span>
          <select className="atlas-input mt-1" value={datasetId} onChange={(event) => onDataset(event.target.value)}>
            <option value="">Select registered dataset</option>
            {datasets.map((item) => <option key={item.datasetId} value={item.datasetId}>{item.name}</option>)}
          </select>
        </label>
        <label>
          <span className="atlas-label">Immutable Dataset Version</span>
          <select className="atlas-input mt-1" value={versionId} onChange={(event) => onVersion(event.target.value)} disabled={!selected}>
            <option value="">Select version</option>
            {(selected?.versions ?? []).map((version) => <option key={version.versionId} value={version.versionId}>{version.versionId} · {version.rowCount.toLocaleString()} rows</option>)}
          </select>
        </label>
        <label>
          <span className="atlas-label">Mapped target field</span>
          <input className="atlas-input mt-1" value={targetField} onChange={(event) => onTarget(event.target.value)} placeholder="Target column in external data" />
        </label>
      </div>
    </div>
  );
}

function PopulationPartitionVisual({
  strategy,
  holdoutSize,
  folds,
  randomSeed,
  testLabel,
  ootLabel,
  distributions,
  hasTest: hasTestOverride,
  hasOot: hasOotOverride,
}: {
  strategy: ValidationStrategy;
  holdoutSize: number;
  folds: number;
  randomSeed: number;
  testLabel?: string;
  ootLabel?: string;
  distributions?: DistributionCollection;
  hasTest?: boolean;
  hasOot?: boolean;
}) {
  const hasHoldout = strategy === "holdout_current" || strategy === "hybrid";
  const hasCv = strategy === "cross_validation" || strategy === "hybrid";
  const hasTest =
    hasTestOverride ??
    (strategy === "separate_test" || strategy === "separate_test_oot");
  const hasOot = hasOotOverride ?? strategy === "separate_test_oot";
  const trainRows =
    distributions?.train_after_balancing?.rows ??
    distributions?.train_before_balancing?.rows;
  const holdoutRows = distributions?.holdout_untouched?.rows;
  const trainingPercent = Math.round((1 - holdoutSize) * 100);
  const holdoutPercent = Math.round(holdoutSize * 100);
  return (
      <section
        className="prep-split-preview"
        data-testid="population-partition-visual"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wide text-blue-700">
              3. Preview of resulting split
            </div>
            <h3 className="mt-1 text-sm font-semibold text-slate-950">
              Training and untouched holdout allocation
            </h3>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Cross-validation rotates only within the blue training
              population. The teal holdout remains sealed for final testing.
            </p>
          </div>
          <span className="prep-state-pill prep-state-pill--success">
            <ShieldCheck size={13} /> Time-ordered split protected
          </span>
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <Metric label="Split method" value="TRAIN / TEST" tone="info" />
          <Metric label="Holdout" value={`${holdoutPercent}%`} />
          <Metric
            label="OOT"
            value={hasOot ? ootLabel ?? "Configured" : "0% · optional"}
          />
          <Metric label="Random seed" value={randomSeed} />
        </div>

        <div className="mt-3 prep-split-preview__bar">
          <div
            className="prep-split-preview__train"
            style={{ width: `${trainingPercent}%` }}
          >
            Training set · {trainingPercent}%
            {trainRows ? ` · ${trainRows.toLocaleString()} rows` : ""}
          </div>
          <div
            className="prep-split-preview__holdout"
            style={{ width: `${holdoutPercent}%` }}
          >
            Test holdout · {holdoutPercent}%
            {holdoutRows ? ` · ${holdoutRows.toLocaleString()} rows` : ""}
          </div>
        </div>
        <div className="mt-1 flex justify-between text-[10px] font-semibold text-slate-500">
          <span>0%</span>
          <span>{trainingPercent}%</span>
          <span>100%</span>
        </div>

        {hasCv ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-violet-200 bg-violet-50/60 px-3 py-2 text-[11px] text-violet-950">
            <Network size={14} className="text-violet-700" />
            <strong>{folds}-fold cross-validation inside training</strong>
            <span className="text-violet-700">
              Rotating validation folds never expose the final holdout.
            </span>
          </div>
        ) : null}
        {hasTest ? (
          <div className="mt-2 text-[10px] text-amber-800">
            Separate TEST: {testLabel ?? "dataset selection required"}
          </div>
        ) : null}
        <div className="mt-2 text-[10px] text-slate-500">
          Development rows shown here are the only target-aware population used
          for cross-validation design.
        </div>
      </section>
  );
  /*
   * Retained as a visual migration reference for the former dark flow
   * diagram. The active experience above uses the compact split-allocation
   * composition from the preparation-page reference.
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-950 p-4 text-white" data-testid="population-partition-visual">
      <div className="flex items-center gap-2"><Boxes size={17} className="text-cyan-300" /><h3 className="text-sm font-semibold">Population Partition Visual</h3></div>
      <p className="mt-1 text-xs leading-5 text-slate-300">The untouched holdout is separated before cross-validation begins inside training.</p>
      <div className="mt-3 grid grid-cols-3 gap-2 text-[10px]">
        <div className="rounded-md border border-blue-400/30 bg-blue-500/10 p-2"><span className="block text-slate-400">Full rows</span><strong>{fullRows?.toLocaleString() ?? "Projected"}</strong></div>
        <div className="rounded-md border border-violet-400/30 bg-violet-500/10 p-2"><span className="block text-slate-400">Training rows</span><strong>{trainRows?.toLocaleString() ?? "Projected"}</strong></div>
        <div className="rounded-md border border-emerald-400/30 bg-emerald-500/10 p-2"><span className="block text-slate-400">Holdout rows</span><strong>{holdoutRows?.toLocaleString() ?? "Projected"}</strong></div>
      </div>
      <div className="mt-4 space-y-2">
        <FlowNode
          tone="blue"
          label="Full governed development population"
          detail={`${fullRows?.toLocaleString() ?? "Projected"} rows · 100% · version pinned`}
        />
        <FlowArrow />
        <div className={`grid gap-3 ${hasHoldout ? "grid-cols-[minmax(0,1fr)_minmax(150px,0.38fr)]" : "grid-cols-1"}`}>
          <div className="space-y-2">
            <FlowNode
              tone="violet"
              label="Training population"
              detail={`${trainRows?.toLocaleString() ?? "Projected"} rows · ${hasHoldout ? `${Math.round((1 - holdoutSize) * 100)}%` : "governed development rows"}`}
            />
            {hasCv ? (
              <div className="rounded-lg border border-cyan-400/50 bg-cyan-500/20 p-3">
                <div className="text-xs font-bold text-cyan-50">
                  ↳ {folds}-fold cross-validation inside training
                </div>
                <div className="mt-2 grid grid-cols-5 gap-1">
                  {Array.from({ length: folds }, (_, index) => (
                    <span
                      key={index}
                      className="rounded border border-cyan-300/30 bg-slate-950/30 px-1 py-1 text-center text-[9px] font-semibold text-cyan-100"
                    >
                      Fold {index + 1}
                    </span>
                  ))}
                </div>
                <div className="mt-2 text-[10px] leading-4 text-slate-300">
                  Rotating validation fold · tuning scope locked to training
                </div>
              </div>
            ) : null}
          </div>
          {hasHoldout ? (
            <div className="space-y-2">
              <FlowNode
                tone="emerald"
                label="Untouched holdout"
                detail={`${holdoutRows?.toLocaleString() ?? "Projected"} rows · ${Math.round(holdoutSize * 100)}% · final use only`}
              />
              <div className="rounded-md border border-emerald-400/30 bg-emerald-500/10 p-2 text-[10px] leading-4 text-emerald-100">
                Never used for tuning, resampling, or candidate filtering.
              </div>
            </div>
          ) : null}
        </div>
        {hasTest ? <><FlowArrow /><FlowNode tone="amber" label="Separate TEST" detail={`${testLabel ?? "Dataset required"} · immutable version`} /></> : null}
        {hasOot ? <><FlowArrow /><FlowNode tone="rose" label="Out-of-time confirmation" detail={`${ootLabel ?? "Dataset required"} · temporal evidence`} /></> : null}
      </div>
    </div>
  );
  */
}

function FlowArrow() {
  return <div className="flex justify-center text-xs text-slate-500">↓</div>;
}

function FoldArchitectureVisual({
  method,
  foldCount,
  architecture,
  distributions,
  dirty,
}: {
  method: FoldMethod;
  foldCount: number;
  architecture?: SplitStatus["fold_architecture"];
  distributions?: DistributionCollection;
  dirty: boolean;
}) {
  if (method === "none") {
    return <div className="rounded-xl border border-slate-200 bg-white p-4"><div className="flex items-center gap-2"><Network size={17} className="text-slate-400" /><h3 className="text-sm font-semibold text-slate-950">Fold Architecture Visual</h3></div><p className="mt-3 text-xs leading-5 text-slate-500">This strategy does not use cross-validation.</p></div>;
  }
  const actual = !dirty ? architecture?.folds ?? [] : [];
  const projected = distributions?.cv_folds ?? [];
  const folds = actual.length
    ? actual.slice(0, Math.max(foldCount, 10))
    : Array.from({ length: foldCount }, (_, index) => ({
        sequence: index + 1,
        repeat: 1,
        fold: index + 1,
        train_rows: 0,
        validation_rows: 0,
        validation_distribution: projected[index],
      }));
  return (
    <div className="rounded-xl border border-violet-200 bg-white p-4" data-testid="fold-architecture-visual">
      <div className="flex items-center justify-between gap-2"><div className="flex items-center gap-2"><Network size={17} className="text-violet-700" /><h3 className="text-sm font-semibold text-slate-950">Fold Architecture Visual</h3></div><span className="text-[10px] font-bold uppercase text-violet-700">{method.replace(/_/g, " ")}</span></div>
      <div className="mt-3 overflow-auto">
        <div className="min-w-[420px] space-y-1.5">
          {folds.map((fold) => {
            const distribution = (
              "validation_distribution" in fold
                ? fold.validation_distribution
                : undefined
            ) as Distribution | undefined;
            return <div key={fold.sequence} className="grid grid-cols-[70px_1fr_92px] items-center gap-2 text-[10px]"><span className="font-bold text-slate-600">Fold {fold.fold}</span><div className="flex h-7 overflow-hidden rounded-md border border-violet-100"><div className="flex flex-1 items-center justify-center bg-violet-100 text-violet-800">Train {fold.train_rows || "projected"}</div><div className="flex w-[22%] items-center justify-center bg-violet-600 text-white">Validate</div></div><span className="text-right text-slate-500">{distribution ? `${distribution.events ?? "?"} E / ${distribution.non_events ?? "?"} N` : "Pending run"}</span></div>;
          })}
        </div>
      </div>
      <div className="mt-3 text-[10px] leading-4 text-slate-500">{architecture?.fold_size_consistent === false ? "Fold sizes differ materially and require review." : "Rotating validation folds preserve consistent sizing; group/time constraints appear when selected."}</div>
    </div>
  );
}

function ClassBalancePreservationVisual({ distributions }: { distributions: DistributionCollection }) {
  const rows: Array<{ label: string; distribution?: Distribution }> = [
    { label: "Development", distribution: distributions.train_before_balancing },
    { label: "Training after policy", distribution: distributions.train_after_balancing },
    ...(distributions.cv_folds ?? []).map((distribution) => ({ label: `Fold ${distribution.fold}`, distribution })),
  ].filter((row) => row.distribution);
  const baseline = distributions.train_before_balancing?.event_rate;
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="class-balance-preservation">
      <div className="flex items-center gap-2"><Layers3 size={17} className="text-blue-700" /><h3 className="text-sm font-semibold text-slate-950">Class-Balance Preservation Visual</h3></div>
      <div className="mt-4 overflow-auto">
        <div className="min-w-[660px] space-y-2">
          <div className="grid grid-cols-[130px_82px_82px_92px_1fr_68px] items-center gap-2 text-[9px] font-bold uppercase tracking-wide text-slate-400">
            <span>Population</span>
            <span className="text-right">Rows</span>
            <span className="text-right">Events</span>
            <span className="text-right">Non-events</span>
            <span>Event-rate comparison</span>
            <span className="text-right">Rate</span>
          </div>
          {rows.map(({ label, distribution }, index) => {
            const rate = distribution?.event_rate;
            const deviation = typeof rate === "number" && typeof baseline === "number" ? Math.abs(rate - baseline) : 0;
            return (
              <div key={`${label}-${index}`} className="grid grid-cols-[130px_82px_82px_92px_1fr_68px] items-center gap-2 text-[10px]">
                <span className="truncate font-semibold text-slate-700">{label}</span>
                <span className="text-right font-medium tabular-nums text-slate-600">{distribution?.rows?.toLocaleString() ?? "—"}</span>
                <span className="text-right font-medium tabular-nums text-slate-600">{distribution?.events?.toLocaleString() ?? "—"}</span>
                <span className="text-right font-medium tabular-nums text-slate-600">{distribution?.non_events?.toLocaleString() ?? "—"}</span>
                <div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className={deviation > 0.05 ? "h-full rounded-full bg-amber-500" : "h-full rounded-full bg-blue-600"} style={{ width: `${Math.max(1, Math.min(100, (rate ?? 0) * 100))}%` }} /></div>
                <span className={deviation > 0.05 ? "text-right font-bold tabular-nums text-amber-700" : "text-right font-medium tabular-nums text-slate-600"}>{formatPercent(rate)}</span>
              </div>
            );
          })}
        </div>
      </div>
      <p className="mt-3 text-[10px] leading-4 text-slate-500">
        Amber marks a material event-rate deviation greater than five percentage points from the governed development population. Final-holdout, TEST, and OOT target distributions are not inspected here.
      </p>
    </div>
  );
}

function DatasetCompatibilityMatrix({ matrix }: { matrix?: SplitStatus["compatibility_matrix"] }) {
  const populations = Object.entries(matrix?.populations ?? {});
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="dataset-compatibility-matrix">
      <div className="flex items-center gap-2"><TableProperties size={17} className="text-cyan-700" /><h3 className="text-sm font-semibold text-slate-950">Dataset Compatibility Matrix</h3></div>
      {!populations.length ? <p className="mt-3 text-xs leading-5 text-slate-500">Not applicable for this strategy. No separate TEST or OOT population is required.</p> : (
        <div className="mt-3 overflow-auto"><table className="atlas-table min-w-[760px]"><thead><tr><th>Population</th><th>Compatibility check</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{populations.flatMap(([population, result]) => result.checks.map((check) => <tr key={`${population}-${check.check}`}><td className="font-semibold">{population}</td><td>{check.check}</td><td><span className={`rounded-full px-2 py-1 text-[10px] font-bold uppercase ${check.status === "passed" ? "bg-emerald-100 text-emerald-800" : check.status === "failed" ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800"}`}>{check.status.replace(/_/g, " ")}</span></td><td className="max-w-xl whitespace-normal text-xs text-slate-600">{check.detail}</td></tr>))}</tbody></table></div>
      )}
    </div>
  );
}

function ValidationRiskSummary({ risks }: { risks: NonNullable<SplitStatus["validation_risks"]> }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="validation-risk-summary">
      <div className="flex items-center gap-2"><CircleAlert size={17} className="text-amber-600" /><h3 className="text-sm font-semibold text-slate-950">Validation Risk Summary</h3></div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {risks.map((risk) => <div key={risk.risk} className={`rounded-lg border p-3 ${risk.status === "blocking" ? "border-rose-200 bg-rose-50" : risk.status === "attention" ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50"}`}><div className="flex items-center justify-between gap-2"><span className="text-xs font-bold text-slate-900">{risk.risk}</span><span className="text-[9px] font-bold uppercase text-slate-500">{risk.status.replace(/_/g, " ")}</span></div><p className="mt-1 text-[10px] leading-4 text-slate-600">{risk.detail}</p></div>)}
        {!risks.length ? <p className="text-xs text-slate-500">Approve the design to calculate validation risks.</p> : null}
      </div>
    </div>
  );
}

function ValidationCompletionGates({ gates }: { gates: Record<string, boolean> }) {
  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4" data-testid="validation-completion-gates">
      <div className="flex items-center gap-2"><ShieldCheck size={17} className="text-emerald-700" /><h3 className="text-sm font-semibold text-slate-950">Training and Validation Design Completion Gates</h3></div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {Object.entries(gates).map(([gate, passed]) => <div key={gate} className="flex items-start gap-2 rounded-lg border border-emerald-100 bg-white p-2.5 text-[10px] leading-4 text-slate-700">{passed ? <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-emerald-600" /> : <CircleAlert size={13} className="mt-0.5 shrink-0 text-rose-600" />}<span className="font-semibold">{gate.replace(/_/g, " ")}</span></div>)}
      </div>
    </div>
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

function DesignStep({
  number,
  title,
  detail,
  complete,
  hidden = false,
}: {
  number: string;
  title: string;
  detail: string;
  complete: boolean;
  hidden?: boolean;
}) {
  if (hidden) return null;
  return (
    <div className={`rounded-xl border p-4 ${complete ? "border-emerald-200 bg-emerald-50/60" : "border-amber-200 bg-amber-50/60"}`}>
      <div className="flex items-start gap-3">
        <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${complete ? "bg-emerald-700 text-white" : "bg-amber-500 text-white"}`}>
          {complete ? <CheckCircle2 size={15} /> : number}
        </span>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-950">{title}</div>
          <p className="mt-1 text-xs leading-5 text-slate-600">{detail}</p>
        </div>
      </div>
    </div>
  );
}

function ProtectionStatement({
  title,
  detail,
}: {
  title: string;
  detail: string;
}) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-blue-100 bg-blue-50/60 p-3">
      <ShieldCheck size={15} className="mt-0.5 shrink-0 text-blue-700" />
      <div>
        <div className="text-xs font-semibold text-slate-900">{title}</div>
        <p className="mt-1 text-[11px] leading-4 text-slate-600">{detail}</p>
      </div>
    </div>
  );
}

function ValidationReadinessChecklist({
  items,
}: {
  items: Array<{ label: string; ready: boolean }>;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3" data-testid="validation-readiness-checklist">
      {items.map((item) => (
        <div
          key={item.label}
          className={`flex items-start gap-2 rounded-lg border p-3 text-xs leading-5 ${item.ready ? "border-emerald-200 bg-emerald-50/60 text-emerald-950" : "border-amber-200 bg-amber-50/60 text-amber-950"}`}
        >
          {item.ready ? (
            <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-emerald-700" />
          ) : (
            <CircleAlert size={14} className="mt-0.5 shrink-0 text-amber-700" />
          )}
          <span className="font-semibold">{item.label}</span>
        </div>
      ))}
    </div>
  );
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: string | number; tone?: "neutral" | "info" | "success" | "warning" }) {
  const classes = tone === "success" ? "border-emerald-200 bg-emerald-50" : tone === "warning" ? "border-amber-200 bg-amber-50" : tone === "info" ? "border-blue-200 bg-blue-50" : "border-slate-200 bg-slate-50";
  return <div className={`min-w-0 rounded-lg border p-3 ${classes}`}><div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 truncate text-sm font-semibold text-slate-950" title={String(value)}>{value}</div></div>;
}

function emptyProfile(name: string): FeatureProfileRow {
  return { selected: false, predictor: name, role: "feature", datatype: "unknown", iv: null, ivStrength: null, correlationWithTarget: null, correlationStrength: null, associationStatus: "not_evaluated", missingCount: 0, missingPercent: 0, distinctCount: 0, mean: null, standardDeviation: null, minimum: null, firstQuartile: null, median: null, thirdQuartile: null, maximum: null, leakageStatus: "eligible", eligibilityStatus: "eligible", exclusionReason: "" };
}

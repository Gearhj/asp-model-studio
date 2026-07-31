import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  Filter,
  Info,
  LoaderCircle,
  Play,
  Search,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import StepShell from "../components/StepShell";
import {
  CarryForwardPanel,
  PreparationGovernanceDisclosure,
  PreparationPageIdentity,
  PreparationQuickSummary,
} from "../components/preparation/PreparationPageChrome";
import {
  AtlasAttentionPanel,
  AtlasDataScopeBadge,
  AtlasExecutionStatus,
  AtlasStatusStrip,
  AtlasWorkflowSection,
} from "../components/ui/AtlasWorkflow";
import { logDecision } from "../lib/decisionJournal";
import { createEvidence } from "../lib/evidenceGraph";
import {
  assertExactDatasetIdentity,
  buildCanonicalEvidenceEnvelope,
  canonicalDatasetStorageKey,
  requireLocalDatasetCanonicalIdentity,
  type CanonicalDatasetIdentity,
} from "../lib/datasetIdentity";
import { loadLocalDataset } from "../lib/localDataset";
import {
  applyOutlierPreviewTreatment,
  buildCommonHistogramPair,
  buildOutlierMethodComparisons,
  outlierBurdenTone,
  type OutlierMethodComparison,
} from "../lib/outlierPremium";
import {
  getEdaCarryForward,
  getPreparationDocumentation,
  saveCarryForwardDisposition,
  type CarryForwardDisposition,
  type PreparationCarryForwardItem,
  type PreparationDocumentationState,
} from "../lib/preparationGovernance";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { safeArray, safeObject } from "../lib/workflowSafety";

type MethodKey =
  | "NONE"
  | "IQR_1_5"
  | "IQR_3_0"
  | "ZSCORE_3"
  | "ZSCORE_4"
  | "PCT_01_99"
  | "PCT_05_95";
type FeatureMethodKey = MethodKey | "USE_GLOBAL";

type MethodResult = {
  method: MethodKey;
  lower_threshold: number;
  upper_threshold: number;
  outlier_count: number;
  outlier_rate: number;
};

type OutlierFeature = {
  feature: string;
  datatype: string;
  nonmissing_count: number;
  ordinary_nonmissing_count: number;
  missing_count: number;
  distinct_count: number;
  mean: number | null;
  standard_deviation: number | null;
  minimum: number | null;
  maximum: number | null;
  special_value_count: number;
  special_value_rate: number;
  special_values: Record<string, number>;
  skewness: number | null;
  signal_metric: number | null;
  association_status: string;
  methods: Record<MethodKey, MethodResult>;
  rendered_sample: number[];
  rendered_sample_count: number;
  quantiles: Record<string, number | null>;
};

type OutlierApplication = {
  applied_at: string;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  dataset_version: string;
  row_count: number;
  global_method: MethodKey;
  config: Record<string, FeatureMethodKey>;
  rationales?: Record<string, string>;
  treatments: Array<{
    feature: string;
    configured_method: FeatureMethodKey;
    applied_method: MethodKey;
    changed_values: number;
    lower_threshold: number;
    upper_threshold: number;
    special_values_preserved?: number;
  }>;
  changed_values: number;
  high_impact_features?: Array<{
    feature: string;
    changed_values: number;
    changed_rate: number;
  }>;
  high_impact_acknowledged?: boolean;
  row_removal_applied?: false;
  state?: "applied";
};

type PredictorAuthorization = {
  authorized_predictors: string[];
  excluded_predictors: Record<string, string>;
  target_source_excluded: string[];
};

type OutlierSummary = {
  ok: boolean;
  scope: "full_dataset";
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  row_count: number;
  dataset_version: string;
  target: string | null;
  problem_type: "classification" | "regression";
  event_value: unknown;
  event_rate: number | null;
  rare_event: boolean;
  predictor_authorization: PredictorAuthorization;
  features: OutlierFeature[];
  application?: OutlierApplication | null;
};

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";
const CONFIG_KEY = "modeling-tool-outlier-methods";
const RATIONALE_KEY = "atlas:outlier-rationales";
const GLOBAL_KEY = "modeling-tool-outlier-global-method";
const PAGE_SIZE = 20;

const METHOD_OPTIONS: Array<{
  key: MethodKey;
  label: string;
  shortLabel: string;
  guidance: string;
}> = [
  {
    key: "NONE",
    label: "None — preserve observed values",
    shortLabel: "None",
    guidance:
      "Use when tail values are plausible business observations or may carry predictive signal.",
  },
  {
    key: "IQR_1_5",
    label: "1.5 IQR capping",
    shortLabel: "1.5 IQR",
    guidance: "A standard robust screen for moderately unusual ordinary values.",
  },
  {
    key: "IQR_3_0",
    label: "3.0 IQR capping",
    shortLabel: "3.0 IQR",
    guidance:
      "A conservative robust screen when extreme values may be meaningful.",
  },
  {
    key: "ZSCORE_3",
    label: "3 standard deviations",
    shortLabel: "Z ±3",
    guidance: "Use for approximately symmetric numeric variables.",
  },
  {
    key: "ZSCORE_4",
    label: "4 standard deviations",
    shortLabel: "Z ±4",
    guidance: "A less aggressive normal-based cap.",
  },
  {
    key: "PCT_01_99",
    label: "Winsorize 0.5% / 99.5%",
    shortLabel: "P0.5–P99.5",
    guidance: "Caps only the most extreme ordinary tails.",
  },
  {
    key: "PCT_05_95",
    label: "Percentile cap 5% / 95%",
    shortLabel: "P5–P95",
    guidance:
      "Aggressive. Use only when tails are documented quality or stability concerns.",
  },
];

function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  return fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  }).then(async (response) => {
    const payload = await response.json().catch(() => null);
    if (!response.ok || payload?.ok === false) {
      throw new Error(
        payload?.detail ??
          payload?.error ??
          `ATLAS request failed with HTTP ${response.status}.`,
      );
    }
    return payload as T;
  });
}

function effectiveMethod(
  configured: FeatureMethodKey | undefined,
  globalMethod: MethodKey,
): MethodKey {
  return !configured || configured === "USE_GLOBAL" ? globalMethod : configured;
}

function normalizedConfig(
  features: OutlierFeature[],
  config: Record<string, FeatureMethodKey>,
) {
  return Object.fromEntries(
    safeArray<OutlierFeature>(features).map((row) => [
      row.feature,
      config[row.feature] ?? "USE_GLOBAL",
    ]),
  );
}

function effectiveConfig(
  features: OutlierFeature[],
  config: Record<string, FeatureMethodKey>,
  globalMethod: MethodKey,
) {
  return Object.fromEntries(
    safeArray<OutlierFeature>(features).map((row) => [
      row.feature,
      effectiveMethod(config[row.feature], globalMethod),
    ]),
  );
}

function isMethodKey(value: unknown): value is MethodKey {
  return METHOD_OPTIONS.some((option) => option.key === value);
}

function migrateStoredConfig(
  features: OutlierFeature[],
  stored: Record<string, FeatureMethodKey>,
  storedGlobal: MethodKey,
  rationales: Record<string, string>,
) {
  const normalized = normalizedConfig(features, stored);
  return Object.fromEntries(
    features.map((row) => {
      const configured = normalized[row.feature];
      const hasOverrideRationale = Boolean(
        String(rationales[row.feature] ?? "").trim(),
      );
      return [
        row.feature,
        configured === storedGlobal && !hasOverrideRationale
          ? ("USE_GLOBAL" as const)
          : configured,
      ];
    }),
  );
}

function configMatchesApplication(
  summary: OutlierSummary | null,
  config: Record<string, FeatureMethodKey>,
  globalMethod: MethodKey,
  rationales: Record<string, string>,
) {
  const application = summary?.application;
  if (!summary || !application || application.global_method !== globalMethod) {
    return false;
  }
  const currentRationales = Object.fromEntries(
    Object.entries(rationales).filter(([, value]) => value.trim()),
  );
  return (
    JSON.stringify(effectiveConfig(summary.features, config, globalMethod)) ===
      JSON.stringify(
        effectiveConfig(
          summary.features,
          application.config,
          application.global_method,
        ),
      ) &&
    JSON.stringify(currentRationales) ===
      JSON.stringify(application.rationales ?? {})
  );
}

function fmt(value: number | null | undefined, digits = 3) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(undefined, {
        maximumFractionDigits: digits,
        minimumFractionDigits: Math.min(digits, 2),
      })
    : "Not evaluated";
}

function pct(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${(value * 100).toFixed(digits)}%`
    : "Not available";
}

function methodLabel(method: MethodKey) {
  return (
    METHOD_OPTIONS.find((option) => option.key === method)?.shortLabel ?? method
  );
}

export default function Step04Outliers() {
  const localDataset = loadLocalDataset();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  let datasetIdentity: CanonicalDatasetIdentity | null = null;
  let datasetIdentityError = "";
  try {
    datasetIdentity = requireLocalDatasetCanonicalIdentity(
      projectId,
      localDataset,
      "Outliers dataset identity",
    );
  } catch (cause) {
    datasetIdentityError =
      cause instanceof Error
        ? cause.message
        : "Outliers requires an exact registered Dataset Library version.";
  }
  const [summary, setSummary] = useState<OutlierSummary | null>(null);
  const [config, setConfig] = useState<Record<string, FeatureMethodKey>>({});
  const [rationales, setRationales] = useState<Record<string, string>>({});
  const [globalMethod, setGlobalMethod] = useState<MethodKey>("IQR_1_5");
  const [settingsHydrated, setSettingsHydrated] = useState(false);
  const [selectedFeature, setSelectedFeature] = useState("");
  const [histogramLimit, setHistogramLimit] = useState(10);
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<"signal" | "outliers" | "name">(
    "outliers",
  );
  const [burdenFilter, setBurdenFilter] = useState<
    "all" | "flagged" | "specials"
  >("all");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [applyFailed, setApplyFailed] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [customLower, setCustomLower] = useState("");
  const [customUpper, setCustomUpper] = useState("");
  const [carryForward, setCarryForward] = useState<
    PreparationCarryForwardItem[]
  >([]);
  const [edaDocumentStatus, setEdaDocumentStatus] = useState("unavailable");
  const [edaManifest, setEdaManifest] = useState("");
  const [preparationDocs, setPreparationDocs] =
    useState<PreparationDocumentationState | null>(null);

  async function loadSummary() {
    setLoading(true);
    setError(datasetIdentityError);
    if (!datasetIdentity) {
      setLoading(false);
      return;
    }
    try {
      const payload = await requestJson<OutlierSummary>("/outliers/summary", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          expected_dataset_id: datasetIdentity.dataset_id,
          expected_dataset_version_id: datasetIdentity.dataset_version_id,
          dataset_version: datasetIdentity.dataset_version_id,
          target: localDataset?.target,
          event_value: localDataset?.event_value,
          problem_type: localDataset?.problem_type,
        }),
      });
      assertExactDatasetIdentity(
        datasetIdentity,
        payload,
        "Outlier summary response",
      );
      if (payload.application) {
        assertExactDatasetIdentity(
          datasetIdentity,
          payload.application,
          "Saved outlier application",
        );
      }
      const features = safeArray<OutlierFeature>(payload.features).map(
        (feature) => ({
          ...feature,
          ordinary_nonmissing_count:
            feature.ordinary_nonmissing_count ?? feature.nonmissing_count,
          distinct_count: feature.distinct_count ?? 0,
          mean: feature.mean ?? null,
          standard_deviation: feature.standard_deviation ?? null,
          minimum: feature.minimum ?? null,
          maximum: feature.maximum ?? null,
          special_value_count: feature.special_value_count ?? 0,
          special_value_rate: feature.special_value_rate ?? 0,
          special_values: safeObject(feature.special_values) as Record<
            string,
            number
          >,
          skewness: feature.skewness ?? null,
          methods: safeObject(feature.methods) as Record<
            MethodKey,
            MethodResult
          >,
          rendered_sample: safeArray<number>(feature.rendered_sample),
          quantiles: safeObject(feature.quantiles) as Record<
            string,
            number | null
          >,
        }),
      );
      const safePayload = {
        ...payload,
        predictor_authorization: payload.predictor_authorization ?? {
          authorized_predictors: features.map((feature) => feature.feature),
          excluded_predictors: {},
          target_source_excluded: [],
        },
        features,
      };
      let stored: Record<string, FeatureMethodKey> = {};
      let storedRationales: Record<string, string> = {};
      let storedGlobal: MethodKey | null = null;
      try {
        const scopedConfig = localStorage.getItem(
          canonicalDatasetStorageKey(CONFIG_KEY, datasetIdentity),
        );
        stored = JSON.parse(scopedConfig || "{}");
        storedRationales = JSON.parse(
          localStorage.getItem(
            canonicalDatasetStorageKey(RATIONALE_KEY, datasetIdentity),
          ) || "{}",
        );
        const candidateGlobal =
          localStorage.getItem(
            canonicalDatasetStorageKey(GLOBAL_KEY, datasetIdentity),
          ) || safePayload.application?.global_method;
        storedGlobal = isMethodKey(candidateGlobal) ? candidateGlobal : null;
      } catch {
        stored = {};
        storedRationales = {};
      }
      const resolvedGlobal = storedGlobal ?? "IQR_1_5";
      const resolvedRationales =
        Object.keys(storedRationales).length
          ? storedRationales
          : safePayload.application?.rationales ?? {};
      const source = Object.keys(stored).length
        ? stored
        : safePayload.application?.config ?? {};
      setSummary(safePayload);
      setGlobalMethod(resolvedGlobal);
      setConfig(
        migrateStoredConfig(
          safePayload.features,
          source,
          resolvedGlobal,
          resolvedRationales,
        ),
      );
      setRationales(resolvedRationales);
      setSettingsHydrated(true);
      setSelectedFeature((current) =>
        current && safePayload.features.some((row) => row.feature === current)
          ? current
          : (safePayload.features[0]?.feature ?? ""),
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Full-data outlier analysis is unavailable.",
      );
    } finally {
      setSettingsHydrated(true);
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadSummary();
    const controller = new AbortController();
    if (datasetIdentity) {
      getEdaCarryForward(datasetIdentity, "outliers", controller.signal)
        .then((context) => {
          setCarryForward(context.items);
          setEdaDocumentStatus(context.documentationStatus);
          setEdaManifest(context.predictorManifestId);
        })
        .catch(() => undefined);
      getPreparationDocumentation(datasetIdentity, controller.signal)
        .then(setPreparationDocs)
        .catch(() => undefined);
    }
    return () => controller.abort();
  }, [
    projectId,
    datasetIdentity?.dataset_id,
    datasetIdentity?.dataset_version_id,
  ]);

  useEffect(() => {
    if (!settingsHydrated || !datasetIdentity) return;
    try {
      localStorage.setItem(
        canonicalDatasetStorageKey(CONFIG_KEY, datasetIdentity),
        JSON.stringify(config),
      );
      localStorage.setItem(
        canonicalDatasetStorageKey(GLOBAL_KEY, datasetIdentity),
        globalMethod,
      );
      localStorage.setItem(
        canonicalDatasetStorageKey(RATIONALE_KEY, datasetIdentity),
        JSON.stringify(rationales),
      );
    } catch {
      setMessage(
        "Selections are retained for this session, but browser persistence is unavailable.",
      );
    }
  }, [
    config,
    datasetIdentity?.dataset_id,
    datasetIdentity?.dataset_version_id,
    globalMethod,
    projectId,
    rationales,
    settingsHydrated,
  ]);

  const applied = configMatchesApplication(
    summary,
    config,
    globalMethod,
    rationales,
  );
  const allRows = safeArray<OutlierFeature>(summary?.features);
  const changedValues = allRows.reduce(
    (sum, row) =>
      sum +
      (row.methods?.[effectiveMethod(config[row.feature], globalMethod)]
        ?.outlier_count ?? 0),
    0,
  );
  const totalOrdinary = allRows.reduce(
    (sum, row) => sum + (row.ordinary_nonmissing_count ?? 0),
    0,
  );
  const highImpactRows = allRows.filter(
    (row) =>
      (row.methods?.[effectiveMethod(config[row.feature], globalMethod)]
        ?.outlier_rate ?? 0) >= 0.1,
  );
  const rows = useMemo(() => {
    const query = search.trim().toLowerCase();
    const filtered = allRows.filter((row) => {
      if (!row.feature.toLowerCase().includes(query)) return false;
      const method =
        row.methods?.[effectiveMethod(config[row.feature], globalMethod)];
      if (burdenFilter === "flagged") return (method?.outlier_count ?? 0) > 0;
      if (burdenFilter === "specials") return row.special_value_count > 0;
      return true;
    });
    return [...filtered].sort((a, b) => {
      if (sortBy === "name") return a.feature.localeCompare(b.feature);
      if (sortBy === "outliers") {
        return (
          (b.methods?.[effectiveMethod(config[b.feature], globalMethod)]
            ?.outlier_rate ?? 0) -
          (a.methods?.[effectiveMethod(config[a.feature], globalMethod)]
            ?.outlier_rate ?? 0)
        );
      }
      return Math.abs(b.signal_metric ?? 0) - Math.abs(a.signal_metric ?? 0);
    });
  }, [allRows, burdenFilter, config, globalMethod, search, sortBy]);
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pagedRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const overrideCount = allRows.filter(
    (row) =>
      !!config[row.feature] && config[row.feature] !== "USE_GLOBAL",
  ).length;
  const signalRankedRows = useMemo(
    () =>
      [...allRows].sort(
        (left, right) =>
          Math.abs(right.signal_metric ?? 0) -
            Math.abs(left.signal_metric ?? 0) ||
          left.feature.localeCompare(right.feature),
      ),
    [allRows],
  );
  const histogramRows = signalRankedRows.slice(
    0,
    Math.min(histogramLimit, signalRankedRows.length),
  );
  const selected =
    allRows.find((row) => row.feature === selectedFeature) ?? allRows[0];
  const selectedMethod = selected
    ? selected.methods?.[effectiveMethod(config[selected.feature], globalMethod)]
    : null;
  const highestBurden = [...allRows].sort((a, b) => {
    const left =
      a.methods?.[effectiveMethod(config[a.feature], globalMethod)]
        ?.outlier_rate ?? 0;
    const right =
      b.methods?.[effectiveMethod(config[b.feature], globalMethod)]
        ?.outlier_rate ?? 0;
    return right - left;
  })[0];
  const maxRate = highestBurden
    ? highestBurden.methods?.[
        effectiveMethod(config[highestBurden.feature], globalMethod)
      ]?.outlier_rate ?? 0
    : 0;
  const documentationStatus = applied
    ? "confirmed"
    : summary?.application
      ? "stale"
      : (preparationDocs?.outliers.status ?? "draft");
  const selectionState = applying
    ? "Applying"
    : applyFailed
      ? "Failed"
      : applied
        ? "Applied"
        : summary?.application
          ? "Stale"
          : changedValues
            ? "Selected"
            : "Suggested";
  const methodComparisons = selected
    ? buildOutlierMethodComparisons(selected.rendered_sample, {
        lower: customLower.trim() ? Number(customLower) : null,
        upper: customUpper.trim() ? Number(customUpper) : null,
      })
    : [];

  function changeFeature(feature: string, method: FeatureMethodKey) {
    logDecision({
      workflowStep: "Outlier Analysis",
      actionType: "outlier_method_selected",
      subject: feature,
      previousValue: config[feature] ?? "USE_GLOBAL",
      newValue: method,
    });
    setConfig((current) => ({ ...current, [feature]: method }));
    setSelectedFeature(feature);
    if (method === "USE_GLOBAL") {
      setRationales((current) => {
        const next = { ...current };
        delete next[feature];
        return next;
      });
    }
    setApplyFailed(false);
    setError("");
    setMessage(
      method === "USE_GLOBAL"
        ? `${feature} now inherits the global default.`
        : `${feature} has a feature-level override. Add rationale before applying.`,
    );
  }

  function changeGlobalMethod(method: MethodKey) {
    logDecision({
      workflowStep: "Outlier Analysis",
      actionType: "outlier_method_selected",
      subject: "All inheriting predictors",
      previousValue: globalMethod,
      newValue: method,
    });
    setGlobalMethod(method);
    setApplyFailed(false);
    setError("");
    setMessage(
      `${methodLabel(method)} is now projected for every predictor without an override. The summary table and cutoff histograms have been updated.`,
    );
  }

  function applyGlobalSelection() {
    setConfig((current) =>
      Object.fromEntries(
        Object.keys(current).map((feature) => [feature, "USE_GLOBAL"]),
      ),
    );
    setRationales({});
    setApplyFailed(false);
    setError("");
    setMessage(
      "All predictors now inherit the global default. The selection remains unmaterialized.",
    );
  }

  function handleCarryForward(
    item: PreparationCarryForwardItem,
    disposition: CarryForwardDisposition,
  ) {
    if (!datasetIdentity) {
      setError(
        datasetIdentityError ||
          "Outlier evidence decisions require an exact registered Dataset Library version.",
      );
      return;
    }
    saveCarryForwardDisposition(
      datasetIdentity,
      "outliers",
      item.findingId,
      disposition,
    );
    setCarryForward((current) =>
      current.map((row) =>
        row.findingId === item.findingId ? { ...row, disposition } : row,
      ),
    );
    setMessage(
      disposition === "accepted"
        ? `${item.title} is accepted as a governed input. No treatment was changed automatically.`
        : `${item.title} remains ${disposition} at the Outliers destination.`,
    );
  }

  async function applyTreatments(): Promise<OutlierApplication | null> {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return null;
    }
    if (!summary) {
      setError(
        "Full-data outlier analysis must load before treatments can be applied.",
      );
      return null;
    }
    const overrideWithoutRationale = summary.features.find(
      (row) =>
        config[row.feature] &&
        config[row.feature] !== "USE_GLOBAL" &&
        !String(rationales[row.feature] ?? "").trim(),
    );
    if (overrideWithoutRationale) {
      setSelectedFeature(overrideWithoutRationale.feature);
      setError(
        `Document why ${overrideWithoutRationale.feature} overrides the global default before applying.`,
      );
      return null;
    }
    setApplying(true);
    setApplyFailed(false);
    setError("");
    try {
      const payload = await requestJson<{
        ok: true;
        scope: "full_dataset";
        project_id: string;
        dataset_id: string;
        dataset_version_id: string;
        dataset_version: string;
        application: OutlierApplication;
        idempotent?: boolean;
      }>("/outliers/apply", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          expected_dataset_id: datasetIdentity.dataset_id,
          expected_dataset_version_id: datasetIdentity.dataset_version_id,
          dataset_version: datasetIdentity.dataset_version_id,
          config: normalizedConfig(summary.features, config),
          global_method: globalMethod,
          target: summary.target,
          event_value: summary.event_value,
          problem_type: summary.problem_type,
          rationales,
          acknowledged_high_impact: highImpactRows.length > 0,
        }),
      });
      assertExactDatasetIdentity(
        datasetIdentity,
        payload,
        "Outlier treatment response",
      );
      assertExactDatasetIdentity(
        datasetIdentity,
        payload.application,
        "Outlier treatment application",
      );
      setSummary((current) =>
        current ? { ...current, application: payload.application } : current,
      );
      setPreparationDocs((current) =>
        current
          ? {
              ...current,
              status: "confirmed",
              outliers: {
                status: "confirmed",
                application: payload.application,
              },
            }
          : current,
      );
      setMessage(
        payload.idempotent
          ? "The current configuration was already applied; no duplicate materialization occurred."
          : `${payload.application.changed_values.toLocaleString()} ordinary values were capped across ${payload.application.treatments.length.toLocaleString()} numeric predictors. Bureau special values were preserved and no rows were removed.`,
      );
      return payload.application;
    } catch (cause) {
      const detail =
        cause instanceof Error
          ? cause.message
          : "Outlier treatments could not be applied.";
      setApplyFailed(true);
      setError(detail);
      return null;
    } finally {
      setApplying(false);
    }
  }

  async function completeStep() {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return false;
    }
    const application =
      applied && summary?.application
        ? summary.application
        : await applyTreatments();
    if (!application) return false;
    await createEvidence({
      ...buildCanonicalEvidenceEnvelope(datasetIdentity, {
        rowCount: application.row_count,
        scope: "full_dataset",
        targetSourceExclusions:
          summary?.predictor_authorization.target_source_excluded ?? [],
      }),
      projectName,
      evidenceType: "outliers",
      title: "Governed Outlier Treatment and Special-Value Separation",
      summary: `${application.changed_values.toLocaleString()} ordinary values were treated across ${application.treatments.length.toLocaleString()} predictors; bureau special values were preserved and no rows were removed.`,
      sourcePage: "Outlier Analysis",
      sourceRoute: "/step03",
      modelIds: [],
      documentIds: [],
      notebookIds: [],
      supportsSections: [
        "Outlier Treatment",
        "Data Quality",
        "Feature Engineering",
      ],
      tags: [
        "predictive_modeling",
        "outliers",
        "special_values",
        "full_dataset",
      ],
      status: "ready",
      importance: "high",
      payload: application,
    });
    return true;
  }

  const datasetName =
    localDataset?.dataset_library?.datasetName ||
    projectName ||
    "Registered dataset";
  const manifestId =
    edaManifest ||
    preparationDocs?.predictor_manifest_id ||
    `authorized:${allRows.length}`;

  return (
    <StepShell
      title=""
      hideHeader
      nextPath="/step04"
      onNext={completeStep}
      nextDisabled={
        loading ||
        !datasetIdentity ||
        !summary ||
        !!error ||
        !allRows.length ||
        applying
      }
      nextDisabledReason={
        error || "Load the governed outlier profile before continuing."
      }
      nextLabel="Confirm Outliers & Continue"
      nextStatusLine={
        applied
          ? "The current full-data treatment is confirmed and ready for Missing Values."
          : "Confirmation applies the selected ordinary-value treatment once; special values and rows remain intact."
      }
      showEmbeddedNext
      nextAlwaysVisible
      nextFooterTestId="outliers-sticky-footer"
    >
      <div className="prep-premium-page space-y-4">
        <PreparationPageIdentity
          step="Step 3 of 13"
          title="Outliers"
          description="Separate ordinary tail behavior from governed bureau special values, compare treatment impact, and materialize only an explicitly confirmed policy."
          datasetName={datasetName}
          datasetVersion={
            datasetIdentity?.dataset_version_id || ""
          }
          target={summary?.target || localDataset?.target || ""}
          predictorCount={allRows.length}
          predictorManifest={manifestId}
          documentationStatus={documentationStatus}
          decisionState={selectionState}
        />

        <PreparationQuickSummary
          metrics={[
            {
              label: "Predictors",
              value: allRows.length.toLocaleString(),
              tone: "info",
            },
            {
              label: "Total flagged",
              value: changedValues.toLocaleString(),
              detail: "ordinary values",
              tone: changedValues ? "warning" : "success",
            },
            {
              label: "Above 10%",
              value: highImpactRows.length.toLocaleString(),
              tone: highImpactRows.length ? "danger" : "success",
            },
            {
              label: "Max rate",
              value: pct(maxRate),
              tone: maxRate >= 0.1 ? "danger" : maxRate ? "warning" : "success",
            },
            {
              label: "Global method",
              value: methodLabel(globalMethod),
            },
            {
              label: "Apply state",
              value: selectionState,
              tone:
                selectionState === "Applied"
                  ? "success"
                  : selectionState === "Failed"
                    ? "danger"
                    : "warning",
            },
            {
              label: "Highest burden",
              value: highestBurden?.feature ?? "None",
              detail: highestBurden ? pct(maxRate) : undefined,
            },
            {
              label: "Documentation",
              value:
                documentationStatus === "confirmed"
                  ? "Confirmed"
                  : documentationStatus === "stale"
                    ? "Stale"
                    : "Draft",
              tone:
                documentationStatus === "confirmed"
                  ? "success"
                  : documentationStatus === "stale"
                    ? "warning"
                    : "neutral",
            },
          ]}
        />

        {loading ? (
          <div className="atlas-workflow-section flex min-h-52 items-center justify-center">
            <LoaderCircle className="animate-spin text-blue-600" size={28} />
          </div>
        ) : null}
        {error ? (
          <AtlasAttentionPanel
            title={
              applyFailed
                ? "Outlier application failed"
                : "Outlier analysis requires attention"
            }
            tone="danger"
          >
            <div className="space-y-3">
              <p>{error}</p>
              {!summary ? (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="atlas-primary-button"
                    onClick={() => void loadSummary()}
                  >
                    Retry analysis
                  </button>
                  <a className="atlas-secondary-button" href="/step01">
                    Go to Data Acquisition
                  </a>
                  <a className="atlas-secondary-button" href="/step02">
                    Go to EDA
                  </a>
                </div>
              ) : null}
            </div>
          </AtlasAttentionPanel>
        ) : null}

        {summary ? (
          <>
            <PreparationGovernanceDisclosure
              summary={`${allRows.length.toLocaleString()} predictors authorized · ${allRows.reduce((sum, row) => sum + row.special_value_count, 0).toLocaleString()} special values preserved · MDD ${documentationStatus}`}
            >
              <AtlasStatusStrip
                items={[
                  {
                    label: "Predictor authorization",
                    state: "complete",
                    detail: `${allRows.length.toLocaleString()} governed predictors`,
                  },
                  {
                    label: "Special-value separation",
                    state: "complete",
                    detail: `${allRows.reduce((sum, row) => sum + row.special_value_count, 0).toLocaleString()} preserved values`,
                  },
                  {
                    label: "Decision",
                    state: applied
                      ? "complete"
                      : applyFailed
                        ? "blocked"
                        : "warning",
                    detail: selectionState,
                  },
                  {
                    label: "MDD link",
                    state:
                      documentationStatus === "confirmed"
                        ? "complete"
                        : documentationStatus === "stale"
                          ? "warning"
                          : "pending",
                    detail: documentationStatus,
                  },
                ]}
              />

              <CarryForwardPanel
                items={carryForward}
                sourceStatus={edaDocumentStatus}
                onDisposition={handleCarryForward}
              />

              {summary.predictor_authorization.target_source_excluded.length ? (
                <div className="flex flex-wrap items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
                  <ShieldCheck size={15} />
                  <strong>Target-source exclusion enforced:</strong>
                  {summary.predictor_authorization.target_source_excluded.join(
                    ", ",
                  )}{" "}
                  cannot enter analysis or treatment.
                </div>
              ) : null}
            </PreparationGovernanceDisclosure>

            {summary.rare_event ? (
              <AtlasAttentionPanel
                title="Rare-event treatment review"
                tone="warning"
              >
                The governed event rate is {pct(summary.event_rate)}. Preserve
                operationally plausible tails unless there is a documented
                quality or stability reason to cap them.
              </AtlasAttentionPanel>
            ) : null}

            <AtlasWorkflowSection
              eyebrow="Primary treatment workspace"
              title="All-Feature Outlier Summary and Treatment Table"
              description="Review every numeric predictor in one scrollable table. Global treatment changes immediately recompute the effective cutoffs, projected range, and flagged population for every inheriting row; explicit feature overrides remain independent."
              tone="info"
              action={
                <AtlasDataScopeBadge
                  scope="full_dataset"
                  rows={summary.row_count}
                />
              }
              id="outlier-feature-summary-table"
            >
              <div className="mb-4 rounded-xl border border-blue-200 bg-blue-50/60 p-4">
                <div className="grid gap-3 lg:grid-cols-[minmax(280px,420px)_auto_minmax(0,1fr)_auto] lg:items-end">
                <label>
                  <span className="atlas-label">Global outlier treatment</span>
                  <select
                    className="atlas-input mt-1"
                    aria-label="Global outlier treatment"
                    value={globalMethod}
                    onChange={(event) =>
                      changeGlobalMethod(event.target.value as MethodKey)
                    }
                    data-testid="outlier-global-treatment"
                  >
                    {METHOD_OPTIONS.map((option) => (
                      <option key={option.key} value={option.key}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <span className="mt-1 block text-xs leading-5 text-slate-600">
                    {
                      METHOD_OPTIONS.find(
                        (option) => option.key === globalMethod,
                      )?.guidance
                    }
                  </span>
                </label>
                <button
                  type="button"
                  className="atlas-primary-button mb-6 whitespace-nowrap"
                  onClick={() => void applyTreatments()}
                  disabled={applying || applied}
                  data-testid="outlier-apply-treatments"
                >
                  {applying ? (
                    <LoaderCircle size={15} className="animate-spin" />
                  ) : applied ? (
                    <CheckCircle2 size={15} />
                  ) : (
                    <Play size={15} />
                  )}
                  {applied ? "Treatments applied" : "Apply treatments"}
                </button>
                <div className="rounded-lg border border-blue-100 bg-white/80 px-3 py-2 text-xs leading-5 text-slate-700">
                  <strong className="text-slate-950">
                    {allRows.length - overrideCount} inheriting
                  </strong>{" "}
                  and{" "}
                  <strong className="text-slate-950">
                    {overrideCount} overridden
                  </strong>{" "}
                  predictors. Changing the global treatment updates inheriting
                  rows immediately; it never clears explicit overrides.
                </div>
                <button
                  type="button"
                  className="atlas-secondary-button"
                  onClick={applyGlobalSelection}
                  disabled={!overrideCount}
                >
                  <SlidersHorizontal size={15} /> Clear all overrides
                </button>
                </div>
                {highImpactRows.length ? (
                  <div
                    className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950"
                    data-testid="outlier-high-impact-inline-notice"
                  >
                    <strong>
                      {highImpactRows.length} predictor
                      {highImpactRows.length === 1 ? "" : "s"} exceed 10%
                      projected change.
                    </strong>{" "}
                    Apply caps ordinary values only; bureau special values and
                    dataset rows are preserved.
                  </div>
                ) : null}
              </div>

              <div className="mb-3 flex flex-wrap items-center gap-2">
                <label className="relative min-w-56 flex-1">
                  <Search
                    size={15}
                    className="pointer-events-none absolute left-3 top-2.5 text-slate-400"
                  />
                  <input
                    className="atlas-input pl-9"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search all predictors"
                    aria-label="Search all outlier predictors"
                  />
                </label>
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-600">
                  <Filter size={15} />
                  <select
                    className="atlas-input min-w-40"
                    value={burdenFilter}
                    aria-label="Filter outlier feature table"
                    onChange={(event) =>
                      setBurdenFilter(
                        event.target.value as typeof burdenFilter,
                      )
                    }
                  >
                    <option value="all">All predictors</option>
                    <option value="flagged">Flagged only</option>
                    <option value="specials">With special values</option>
                  </select>
                </label>
                <select
                  className="atlas-input min-w-44"
                  aria-label="Sort all-feature outlier table"
                  value={sortBy}
                  onChange={(event) =>
                    setSortBy(event.target.value as typeof sortBy)
                  }
                >
                  <option value="outliers">Flagged rate</option>
                  <option value="signal">
                    {summary.problem_type === "classification"
                      ? "Information Value"
                      : "Absolute correlation"}
                  </option>
                  <option value="name">Feature name</option>
                </select>
              </div>

              <OutlierFeatureTable
                rows={rows}
                config={config}
                globalMethod={globalMethod}
                problemType={summary.problem_type}
                selectedFeature={selected?.feature ?? ""}
                applied={applied}
                onSelect={setSelectedFeature}
                onChange={changeFeature}
              />
              <p className="mt-2 text-xs text-slate-500">
                Showing all {rows.length.toLocaleString()} matching predictors
                in the same table. Scroll vertically or horizontally to review
                the full inventory; no predictors are hidden behind pagination.
              </p>

              {selected ? (
                <div className="mt-4 grid gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 lg:grid-cols-[minmax(240px,0.7fr)_minmax(0,1.3fr)] lg:items-start">
                  <div className="text-xs leading-5 text-slate-600">
                    <strong className="block text-sm text-slate-950">
                      {selected.feature}
                    </strong>
                    {config[selected.feature] &&
                    config[selected.feature] !== "USE_GLOBAL"
                      ? `${methodLabel(effectiveMethod(config[selected.feature], globalMethod))} is an explicit override. Document why its tail behavior needs a different policy.`
                      : `${selected.feature} inherits ${methodLabel(globalMethod)}. Choose an override in its table row only when this feature needs a distinct policy.`}
                  </div>
                  <label>
                    <span className="atlas-label">
                      Selected feature override rationale
                    </span>
                    <textarea
                      className="atlas-input mt-1 min-h-20"
                      value={rationales[selected.feature] ?? ""}
                      disabled={
                        !config[selected.feature] ||
                        config[selected.feature] === "USE_GLOBAL"
                      }
                      onChange={(event) => {
                        setRationales((current) => ({
                          ...current,
                          [selected.feature]: event.target.value,
                        }));
                        setError("");
                      }}
                      placeholder={
                        config[selected.feature] === "USE_GLOBAL"
                          ? "No rationale is required while this feature inherits the global treatment."
                          : "Document business meaning, tail plausibility, and why this override is appropriate."
                      }
                    />
                  </label>
                </div>
              ) : null}
            </AtlasWorkflowSection>

            <AtlasWorkflowSection
              eyebrow="Distribution review"
              title={
                summary.problem_type === "classification"
                  ? "Top Predictors by IV · Outlier Cutoff Histograms"
                  : "Top Predictors by Signal · Outlier Cutoff Histograms"
              }
              description="Each bounded rendering sample uses the currently effective treatment and clearly marks the backend-authoritative low and high cutoffs. Ten predictors are shown by default; expand the selector to review more."
              tone="neutral"
              id="outlier-cutoff-histograms"
              action={
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-600">
                  Show histograms
                  <select
                    className="atlas-input min-w-44"
                    aria-label="Number of outlier histograms"
                    value={histogramLimit}
                    onChange={(event) =>
                      setHistogramLimit(Number(event.target.value))
                    }
                    data-testid="outlier-histogram-limit"
                  >
                    <option value={10}>Top 10</option>
                    <option value={20}>Top 20</option>
                    <option value={allRows.length}>All predictors</option>
                  </select>
                </label>
              }
            >
              <CutoffHistogramGallery
                rows={histogramRows}
                config={config}
                globalMethod={globalMethod}
                problemType={summary.problem_type}
                onSelect={setSelectedFeature}
              />
            </AtlasWorkflowSection>

            <details className="rounded-xl border border-slate-200 bg-white p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-950">
                Secondary diagnostics and method comparison
                <span className="ml-2 text-xs font-normal text-slate-500">
                  Burden landscape, selected-feature impact, and pattern map
                </span>
              </summary>
              <div className="mt-4 space-y-4 border-t border-slate-100 pt-4">
            <AtlasWorkflowSection
              eyebrow="Decision workspace"
              title="Outlier Burden Landscape"
              description="Ranked ordinary-value burden, signal, treatment, and special-value context. Select any predictor to coordinate every detail view."
              tone="info"
              action={
                <AtlasDataScopeBadge
                  scope="full_dataset"
                  rows={summary.row_count}
                />
              }
              id="outlier-burden-landscape"
            >
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <label className="relative min-w-56 flex-1">
                  <Search
                    size={15}
                    className="pointer-events-none absolute left-3 top-2.5 text-slate-400"
                  />
                  <input
                    className="atlas-input pl-9"
                    value={search}
                    onChange={(event) => {
                      setSearch(event.target.value);
                      setPage(0);
                    }}
                    placeholder="Search predictors"
                    aria-label="Search outlier predictors"
                  />
                </label>
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-600">
                  <Filter size={15} />
                  <select
                    className="atlas-input min-w-36"
                    value={burdenFilter}
                    onChange={(event) => {
                      setBurdenFilter(
                        event.target.value as typeof burdenFilter,
                      );
                      setPage(0);
                    }}
                  >
                    <option value="all">All predictors</option>
                    <option value="flagged">Flagged only</option>
                    <option value="specials">With special values</option>
                  </select>
                </label>
                <select
                  className="atlas-input min-w-40"
                  aria-label="Sort outlier landscape"
                  value={sortBy}
                  onChange={(event) => {
                    setSortBy(event.target.value as typeof sortBy);
                    setPage(0);
                  }}
                >
                  <option value="outliers">Flagged rate</option>
                  <option value="signal">Signal strength</option>
                  <option value="name">Feature name</option>
                </select>
              </div>
              <BurdenLandscape
                rows={rows}
                config={config}
                globalMethod={globalMethod}
                selectedFeature={selected?.feature ?? ""}
                onSelect={setSelectedFeature}
              />
            </AtlasWorkflowSection>

            {selected && selectedMethod ? (
              <AtlasWorkflowSection
                eyebrow="Selected predictor"
                title={`Treatment Impact Preview · ${selected.feature}`}
                description="Coordinated before/after distributions use one bounded rendered sample and common axes. Full-data counts and thresholds remain backend authoritative."
                tone="neutral"
                action={
                  <AtlasDataScopeBadge
                    scope="rendered_sample"
                    rows={selected.rendered_sample_count}
                  />
                }
                id="treatment-impact-preview"
              >
                <TreatmentImpactPreview
                  feature={selected}
                  method={selectedMethod}
                />
                <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(250px,0.7fr)_minmax(0,1.3fr)]">
                  <label>
                    <span className="atlas-label">
                      Feature-level decision
                    </span>
                    <select
                      className="atlas-input mt-1"
                      value={config[selected.feature] ?? "USE_GLOBAL"}
                      onChange={(event) =>
                        changeFeature(
                          selected.feature,
                          event.target.value as FeatureMethodKey,
                        )
                      }
                    >
                      <option value="USE_GLOBAL">
                        Use global default ({methodLabel(globalMethod)})
                      </option>
                      {METHOD_OPTIONS.map((option) => (
                        <option key={option.key} value={option.key}>
                          Override · {option.label}
                        </option>
                      ))}
                    </select>
                    <span className="mt-1 block text-xs text-slate-500">
                      Global defaults provide consistency. Overrides take
                      precedence and require rationale.
                    </span>
                  </label>
                  <label>
                    <span className="atlas-label">
                      Override rationale
                    </span>
                    <textarea
                      className="atlas-input mt-1 min-h-20"
                      value={rationales[selected.feature] ?? ""}
                      disabled={
                        !config[selected.feature] ||
                        config[selected.feature] === "USE_GLOBAL"
                      }
                      onChange={(event) =>
                        setRationales((current) => ({
                          ...current,
                          [selected.feature]: event.target.value,
                        }))
                      }
                      placeholder={
                        config[selected.feature] === "USE_GLOBAL"
                          ? "Not required while inheriting the global default."
                          : "Document business meaning, tail plausibility, and why this override is appropriate."
                      }
                    />
                  </label>
                </div>
              </AtlasWorkflowSection>
            ) : null}

            {selected ? (
              <AtlasWorkflowSection
                eyebrow="Preview only"
                title="Method Comparison"
                description="Compare nonmutating alternatives for the selected rendered sample. These rows never alter the governed plan or backend frame."
                tone="neutral"
                id="outlier-method-comparison"
              >
                <div className="mb-3 flex flex-wrap items-end gap-3">
                  <label className="w-40">
                    <span className="atlas-label">Custom lower</span>
                    <input
                      className="atlas-input mt-1"
                      inputMode="decimal"
                      value={customLower}
                      onChange={(event) => setCustomLower(event.target.value)}
                      placeholder="Preview only"
                    />
                  </label>
                  <label className="w-40">
                    <span className="atlas-label">Custom upper</span>
                    <input
                      className="atlas-input mt-1"
                      inputMode="decimal"
                      value={customUpper}
                      onChange={(event) => setCustomUpper(event.target.value)}
                      placeholder="Preview only"
                    />
                  </label>
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-xs font-semibold text-blue-800">
                    <Info size={13} /> Preview only — no backend mutation
                  </span>
                </div>
                <MethodComparisonTable rows={methodComparisons} />
              </AtlasWorkflowSection>
            ) : null}

            <AtlasWorkflowSection
              eyebrow="Coordinated diagnostics"
              title="Outlier / Skew / Special-Value Pattern Map"
              description="Ordinary outliers, distribution skew, bureau special values, nulls, signal, and selected treatment remain separate analytical concepts."
              id="outlier-pattern-map"
            >
              <PatternMap
                rows={rows}
                config={config}
                globalMethod={globalMethod}
                selectedFeature={selected?.feature ?? ""}
                applied={applied}
                onSelect={setSelectedFeature}
              />
            </AtlasWorkflowSection>
              </div>
            </details>

            <AtlasWorkflowSection
              eyebrow="Governed policy"
              title="Application Status and Safeguards"
              description="Review the backend application state and the safeguards that remain in force for the selected policy."
              tone="info"
              id="outlier-apply-policy"
            >
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,420px)] lg:items-center">
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">
                  <strong className="text-slate-900">Precedence:</strong>{" "}
                  feature override → global default. Bureau values -7, -8, and
                  -9 remain governed special values and are never ordinary
                  outliers. Row removal is not part of this policy.
                </div>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-slate-200 pt-4">
                <AtlasExecutionStatus
                  state={
                    applying
                      ? "running"
                      : applyFailed
                        ? "failed"
                        : applied
                          ? "complete"
                          : "idle"
                  }
                  label={
                    applying
                      ? "Applying"
                      : applyFailed
                        ? "Failed"
                        : applied
                          ? "Applied"
                          : summary.application
                            ? "Stale"
                            : changedValues
                              ? "Selected"
                              : "Suggested"
                  }
                  detail={
                    summary.application?.applied_at
                      ? `Last backend success ${new Date(summary.application.applied_at).toLocaleString()}`
                      : "No treatment is applied until explicit confirmation succeeds."
                  }
                />
                <span className="text-xs text-slate-500">
                  {changedValues.toLocaleString()} of{" "}
                  {totalOrdinary.toLocaleString()} ordinary predictor values
                  currently flagged.
                </span>
              </div>
            </AtlasWorkflowSection>

            {message ? (
              <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
                {message}
              </div>
            ) : null}

            <details className="atlas-workflow-section" data-prep-anchor>
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
                <span>
                  <span className="block text-sm font-semibold text-slate-950">
                    Detailed Predictor Treatment Inventory
                  </span>
                  <span className="mt-1 block text-xs text-slate-600">
                    Searchable, sortable, paginated full-data counts and
                    explicit per-feature controls.
                  </span>
                </span>
                <CircleDot size={17} className="text-blue-600" />
              </summary>
              <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200">
                <table className="min-w-[1060px] w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-3 py-2">Predictor</th>
                      <th className="px-3 py-2">Ordinary flagged</th>
                      <th className="px-3 py-2">Rate</th>
                      <th className="px-3 py-2">Special values</th>
                      <th className="px-3 py-2">Skew</th>
                      <th className="px-3 py-2">
                        {summary.problem_type === "regression"
                          ? "Correlation"
                          : "IV"}
                      </th>
                      <th className="px-3 py-2">Treatment</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedRows.map((row) => {
                      const method =
                        row.methods?.[
                          effectiveMethod(config[row.feature], globalMethod)
                        ];
                      return (
                        <tr
                          key={row.feature}
                          className={
                            selected?.feature === row.feature
                              ? "border-t border-slate-100 bg-blue-50"
                              : "border-t border-slate-100 hover:bg-slate-50"
                          }
                          onClick={() => setSelectedFeature(row.feature)}
                        >
                          <td className="cursor-pointer px-3 py-2 font-medium text-slate-900">
                            {row.feature}
                          </td>
                          <td className="px-3 py-2 tabular-nums">
                            {method?.outlier_count.toLocaleString() ?? "0"}
                          </td>
                          <td className="px-3 py-2 tabular-nums">
                            {pct(method?.outlier_rate)}
                          </td>
                          <td className="px-3 py-2 tabular-nums">
                            {row.special_value_count.toLocaleString()}
                          </td>
                          <td className="px-3 py-2 tabular-nums">
                            {fmt(row.skewness)}
                          </td>
                          <td className="px-3 py-2 tabular-nums">
                            {fmt(row.signal_metric, 4)}
                          </td>
                          <td
                            className="px-3 py-2"
                            onClick={(event) => event.stopPropagation()}
                          >
                            <select
                              className="atlas-input min-w-52"
                              value={config[row.feature] ?? "USE_GLOBAL"}
                              onChange={(event) =>
                                changeFeature(
                                  row.feature,
                                  event.target.value as FeatureMethodKey,
                                )
                              }
                            >
                              <option value="USE_GLOBAL">
                                Use global · {methodLabel(globalMethod)}
                              </option>
                              {METHOD_OPTIONS.map((option) => (
                                <option key={option.key} value={option.key}>
                                  Override · {option.shortLabel}
                                </option>
                              ))}
                            </select>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <Pagination
                page={page}
                pageCount={pageCount}
                rowCount={rows.length}
                pageSize={PAGE_SIZE}
                onPage={setPage}
              />
            </details>

            <details className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-700">
              <summary className="cursor-pointer font-semibold text-slate-950">
                Treatment guide, scope, and interpretation
              </summary>
              <div className="mt-3 grid gap-3 border-t border-slate-100 pt-3 md:grid-cols-2">
                {METHOD_OPTIONS.map((option) => (
                  <div key={option.key}>
                    <strong>{option.label}</strong>
                    <p className="mt-1 text-xs leading-5 text-slate-600">
                      {option.guidance}
                    </p>
                  </div>
                ))}
                <div className="md:col-span-2 rounded-lg border border-cyan-200 bg-cyan-50 p-3 text-xs leading-5 text-cyan-950">
                  Full-data counts, thresholds, and application are backend
                  authoritative. Histograms and method comparisons use a
                  bounded sample only for rendering. Special bureau values and
                  nulls are separate from ordinary outlier calculations.
                </div>
              </div>
            </details>
          </>
        ) : null}
      </div>
    </StepShell>
  );
}

function projectedRange(row: OutlierFeature, method: MethodResult | undefined) {
  const rawMinimum =
    row.minimum ?? row.methods?.NONE?.lower_threshold ?? null;
  const rawMaximum =
    row.maximum ?? row.methods?.NONE?.upper_threshold ?? null;
  if (
    !method ||
    method.method === "NONE" ||
    rawMinimum === null ||
    rawMaximum === null
  ) {
    return { minimum: rawMinimum, maximum: rawMaximum };
  }
  return {
    minimum: Math.max(rawMinimum, method.lower_threshold),
    maximum: Math.min(rawMaximum, method.upper_threshold),
  };
}

function OutlierFeatureTable({
  rows,
  config,
  globalMethod,
  problemType,
  selectedFeature,
  applied,
  onSelect,
  onChange,
}: {
  rows: OutlierFeature[];
  config: Record<string, FeatureMethodKey>;
  globalMethod: MethodKey;
  problemType: "classification" | "regression";
  selectedFeature: string;
  applied: boolean;
  onSelect: (feature: string) => void;
  onChange: (feature: string, method: FeatureMethodKey) => void;
}) {
  return (
    <div
      className="max-h-[430px] overflow-auto rounded-lg border border-slate-200 bg-white shadow-sm"
      data-testid="outlier-feature-summary-table"
    >
      <table className="w-full min-w-[2220px] text-xs">
        <thead className="sticky top-0 z-20 bg-slate-100 text-left uppercase tracking-wide text-slate-600 shadow-sm">
          <tr>
            <th className="sticky left-0 z-30 min-w-52 bg-slate-100 px-3 py-2">
              Predictor
            </th>
            <th className="sticky left-52 z-30 min-w-32 bg-slate-100 px-3 py-2 text-right">
              Outliers
            </th>
            <th className="px-3 py-2 text-right">Nonmissing</th>
            <th className="px-3 py-2 text-right">Distinct</th>
            <th className="px-3 py-2 text-right">Missing</th>
            <th className="px-3 py-2 text-right">Special</th>
            <th className="px-3 py-2 text-right">Mean</th>
            <th className="px-3 py-2 text-right">Std. dev.</th>
            <th className="px-3 py-2 text-right">Minimum</th>
            <th className="px-3 py-2 text-right">P05</th>
            <th className="px-3 py-2 text-right">Median</th>
            <th className="px-3 py-2 text-right">P95</th>
            <th className="px-3 py-2 text-right">Maximum</th>
            <th className="px-3 py-2 text-right">Skew</th>
            <th className="px-3 py-2 text-right">
              {problemType === "classification" ? "IV" : "Correlation"}
            </th>
            <th className="px-3 py-2">Effective treatment</th>
            <th className="px-3 py-2 text-right">Low cutoff</th>
            <th className="px-3 py-2 text-right">High cutoff</th>
            <th className="px-3 py-2 text-right">Projected range</th>
            <th className="min-w-64 px-3 py-2">Feature override</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const configured = config[row.feature] ?? "USE_GLOBAL";
            const override = configured !== "USE_GLOBAL";
            const method =
              row.methods?.[effectiveMethod(configured, globalMethod)];
            const projection = projectedRange(row, method);
            return (
              <tr
                key={row.feature}
                className={
                  selectedFeature === row.feature
                    ? "cursor-pointer border-t border-blue-100 bg-blue-50/70"
                    : "cursor-pointer border-t border-slate-100 hover:bg-slate-50"
                }
                onClick={() => onSelect(row.feature)}
              >
                <td
                  className={`sticky left-0 z-10 min-w-52 px-3 py-2.5 font-semibold text-slate-950 ${
                    selectedFeature === row.feature
                      ? "bg-blue-50"
                      : "bg-white"
                  }`}
                >
                  {row.feature}
                  <span className="mt-0.5 block text-[10px] font-normal text-slate-500">
                    {row.association_status === "evaluated"
                      ? "Signal evaluated"
                      : row.association_status.replaceAll("_", " ")}
                  </span>
                </td>
                <td
                  className={`sticky left-52 z-10 min-w-32 px-3 py-2.5 text-right tabular-nums ${
                    selectedFeature === row.feature
                      ? "bg-blue-50"
                      : "bg-white"
                  }`}
                  data-testid="outlier-count-cell"
                  data-effective-method={method?.method ?? "UNAVAILABLE"}
                >
                  <span className="block text-sm font-bold text-rose-700">
                    {method?.outlier_count.toLocaleString() ?? "0"}
                  </span>
                  <span className="mt-0.5 block text-[10px] font-medium text-slate-500">
                    {pct(method?.outlier_rate)}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {row.nonmissing_count.toLocaleString()}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {row.distinct_count.toLocaleString()}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {row.missing_count.toLocaleString()}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-violet-700">
                  {row.special_value_count.toLocaleString()}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {fmt(row.mean)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {fmt(row.standard_deviation)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {fmt(row.minimum)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {fmt(row.quantiles?.p05)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {fmt(row.quantiles?.median)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {fmt(row.quantiles?.p95)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {fmt(row.maximum)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {fmt(row.skewness)}
                </td>
                <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-blue-800">
                  {fmt(row.signal_metric, 4)}
                </td>
                <td className="px-3 py-2.5">
                  <span className="font-semibold text-slate-900">
                    {method ? methodLabel(method.method) : "Unavailable"}
                  </span>
                  <span
                    className={`ml-2 rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                      override
                        ? "bg-violet-100 text-violet-800"
                        : "bg-blue-100 text-blue-800"
                    }`}
                  >
                    {override ? "Override" : "Global"}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-rose-700">
                  {fmt(method?.lower_threshold)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-rose-700">
                  {fmt(method?.upper_threshold)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {fmt(projection.minimum)} – {fmt(projection.maximum)}
                </td>
                <td
                  className="px-3 py-2.5"
                  onClick={(event) => event.stopPropagation()}
                >
                  <select
                    className="atlas-input min-w-56"
                    value={configured}
                    aria-label={`Feature override for ${row.feature}`}
                    data-testid="outlier-feature-override"
                    onChange={(event) =>
                      onChange(
                        row.feature,
                        event.target.value as FeatureMethodKey,
                      )
                    }
                  >
                    <option value="USE_GLOBAL">
                      Use global · {methodLabel(globalMethod)}
                    </option>
                    {METHOD_OPTIONS.map((option) => (
                      <option key={option.key} value={option.key}>
                        Override · {option.shortLabel}
                      </option>
                    ))}
                  </select>
                  <span className="mt-1 block text-[10px] text-slate-500">
                    {applied ? "Applied plan" : "Live projection"}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!rows.length ? (
        <div className="p-8 text-center text-sm text-slate-500">
          No predictors match the current search and filter.
        </div>
      ) : null}
    </div>
  );
}

function CutoffHistogramGallery({
  rows,
  config,
  globalMethod,
  problemType,
  onSelect,
}: {
  rows: OutlierFeature[];
  config: Record<string, FeatureMethodKey>;
  globalMethod: MethodKey;
  problemType: "classification" | "regression";
  onSelect: (feature: string) => void;
}) {
  return (
    <div
      className="grid gap-4 xl:grid-cols-2"
      data-testid="outlier-cutoff-histogram-gallery"
    >
      {rows.map((row, index) => {
        const configured = config[row.feature] ?? "USE_GLOBAL";
        const method =
          row.methods?.[effectiveMethod(configured, globalMethod)];
        const sample = safeArray<number>(row.rendered_sample);
        const treatedSample = method
          ? applyOutlierPreviewTreatment(sample, method)
          : sample;
        const histogram = buildCommonHistogramPair(sample, treatedSample);
        const maximumBin = Math.max(
          1,
          ...histogram.before,
          ...histogram.after,
        );
        return (
          <article
            key={row.feature}
            className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm"
          >
            <div className="mb-2 flex items-start justify-between gap-3">
              <button
                type="button"
                className="text-left"
                onClick={() => onSelect(row.feature)}
              >
                <span className="block text-sm font-semibold text-slate-950">
                  {index + 1}. {row.feature}
                </span>
                <span className="mt-0.5 block text-[11px] text-slate-500">
                  {problemType === "classification" ? "IV" : "|Correlation|"}{" "}
                  {fmt(
                    problemType === "classification"
                      ? row.signal_metric
                      : Math.abs(row.signal_metric ?? 0),
                    4,
                  )}{" "}
                  · {row.rendered_sample_count.toLocaleString()} rendered values
                </span>
              </button>
              <span
                className={`rounded-full px-2 py-1 text-[10px] font-bold ${
                  configured === "USE_GLOBAL"
                    ? "bg-blue-100 text-blue-800"
                    : "bg-violet-100 text-violet-800"
                }`}
              >
                {configured === "USE_GLOBAL" ? "Global" : "Override"} ·{" "}
                {method ? methodLabel(method.method) : "Unavailable"}
              </span>
            </div>
            {method && sample.length ? (
              <>
                <div className="grid gap-2 lg:grid-cols-2">
                  <HistogramPanel
                    title="Before capping"
                    bins={histogram.before}
                    maximumBin={maximumBin}
                    color="bg-blue-500"
                    minimum={histogram.minimum}
                    maximum={histogram.maximum}
                    thresholdLow={method.lower_threshold}
                    thresholdHigh={method.upper_threshold}
                    testId="outlier-before-histogram"
                  />
                  <HistogramPanel
                    title="After capping"
                    bins={histogram.after}
                    maximumBin={maximumBin}
                    color="bg-emerald-500"
                    minimum={histogram.minimum}
                    maximum={histogram.maximum}
                    thresholdLow={method.lower_threshold}
                    thresholdHigh={method.upper_threshold}
                    testId="outlier-after-histogram"
                    clipToThresholds
                  />
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                  <div
                    className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-rose-900"
                    data-testid="outlier-low-cutoff"
                  >
                    <span className="block text-[10px] font-bold uppercase tracking-wide">
                      Low cutoff
                    </span>
                    <span className="font-semibold tabular-nums">
                      {fmt(method.lower_threshold)}
                    </span>
                  </div>
                  <div
                    className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-right text-rose-900"
                    data-testid="outlier-high-cutoff"
                  >
                    <span className="block text-[10px] font-bold uppercase tracking-wide">
                      High cutoff
                    </span>
                    <span className="font-semibold tabular-nums">
                      {fmt(method.upper_threshold)}
                    </span>
                  </div>
                </div>
                <p className="mt-2 text-[11px] text-slate-500">
                  {method.outlier_count.toLocaleString()} full-data ordinary
                  values flagged ({pct(method.outlier_rate)}). Governed special
                  values are excluded from these thresholds.
                </p>
              </>
            ) : (
              <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500">
                A numeric rendering sample is unavailable for this predictor.
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}

function BurdenLandscape({
  rows,
  config,
  globalMethod,
  selectedFeature,
  onSelect,
}: {
  rows: OutlierFeature[];
  config: Record<string, FeatureMethodKey>;
  globalMethod: MethodKey;
  selectedFeature: string;
  onSelect: (feature: string) => void;
}) {
  const visible = rows.slice(0, 18);
  const maxRate = Math.max(
    0.001,
    ...visible.map(
      (row) =>
        row.methods?.[effectiveMethod(config[row.feature], globalMethod)]
          ?.outlier_rate ?? 0,
    ),
  );
  return (
    <div
      className="prep-chart-panel"
      data-testid="outlier-burden-landscape"
    >
      <div className="grid grid-cols-[minmax(180px,1fr)_minmax(220px,2fr)_72px_74px_90px] gap-2 border-b border-slate-200 px-2 pb-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">
        <span>Predictor</span>
        <span>Ordinary flagged rate</span>
        <span className="text-right">Count</span>
        <span className="text-right">IV / corr</span>
        <span className="text-right">Treatment</span>
      </div>
      <div className="mt-1 max-h-[430px] overflow-auto">
        {visible.map((row) => {
          const method =
            row.methods?.[effectiveMethod(config[row.feature], globalMethod)];
          const rate = method?.outlier_rate ?? 0;
          const tone = outlierBurdenTone(rate);
          return (
            <button
              key={row.feature}
              type="button"
              className={`grid w-full grid-cols-[minmax(180px,1fr)_minmax(220px,2fr)_72px_74px_90px] items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs ${
                selectedFeature === row.feature
                  ? "bg-blue-50 ring-1 ring-blue-300"
                  : "hover:bg-slate-50"
              }`}
              onClick={() => onSelect(row.feature)}
              title={`${row.feature}: ${pct(rate)} ordinary outliers, ${row.special_value_count} governed special values, signal ${fmt(row.signal_metric, 4)}`}
            >
              <span className="truncate font-semibold text-slate-900">
                {row.feature}
                {row.special_value_count ? (
                  <small className="ml-1 text-violet-600">
                    · {row.special_value_count} special
                  </small>
                ) : null}
              </span>
              <span className="relative h-4 overflow-hidden rounded-full bg-slate-100">
                <span
                  className={`absolute inset-y-0 left-0 rounded-full ${
                    tone === "danger"
                      ? "bg-rose-500"
                      : tone === "warning"
                        ? "bg-amber-400"
                        : tone === "info"
                          ? "bg-blue-500"
                          : "bg-slate-300"
                  }`}
                  style={{ width: `${Math.max(rate ? 2 : 0, (rate / maxRate) * 100)}%` }}
                />
                <span className="absolute inset-0 flex items-center px-2 text-[10px] font-semibold text-slate-800">
                  {pct(rate)}
                </span>
              </span>
              <span className="text-right tabular-nums">
                {method?.outlier_count.toLocaleString() ?? "0"}
              </span>
              <span className="text-right tabular-nums">
                {fmt(row.signal_metric, 3)}
              </span>
              <span className="truncate text-right text-[10px] font-semibold text-blue-700">
                {method ? methodLabel(method.method) : "None"}
              </span>
            </button>
          );
        })}
      </div>
      {rows.length > visible.length ? (
        <p className="mt-2 text-[11px] text-slate-500">
          Showing the first {visible.length} ranked predictors. Use the detailed
          inventory for all {rows.length.toLocaleString()} matching rows.
        </p>
      ) : null}
    </div>
  );
}

function TreatmentImpactPreview({
  feature,
  method,
}: {
  feature: OutlierFeature;
  method: MethodResult;
}) {
  const before = safeArray<number>(feature.rendered_sample);
  const after = applyOutlierPreviewTreatment(before, method);
  const pair = buildCommonHistogramPair(before, after);
  const beforeStats = buildOutlierMethodComparisons(before)[0];
  const afterStats = describePreview(after);
  const maximumBin = Math.max(1, ...pair.before, ...pair.after);
  const changed = after.reduce(
    (sum, value, index) => sum + (value !== before[index] ? 1 : 0),
    0,
  );
  return (
    <div data-testid="outlier-treatment-impact-preview">
      <div className="grid gap-3 lg:grid-cols-2">
        <HistogramPanel
          title="Before treatment"
          bins={pair.before}
          maximumBin={maximumBin}
          color="bg-slate-500"
          minimum={pair.minimum}
          maximum={pair.maximum}
          thresholdLow={method.lower_threshold}
          thresholdHigh={method.upper_threshold}
        />
        <HistogramPanel
          title="After selected treatment"
          bins={pair.after}
          maximumBin={maximumBin}
          color="bg-blue-500"
          minimum={pair.minimum}
          maximum={pair.maximum}
          thresholdLow={method.lower_threshold}
          thresholdHigh={method.upper_threshold}
        />
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
        <ImpactMetric
          label="Original range"
          value={`${fmt(beforeStats?.minimum)} — ${fmt(beforeStats?.maximum)}`}
        />
        <ImpactMetric
          label="Treated range"
          value={`${fmt(afterStats.minimum)} — ${fmt(afterStats.maximum)}`}
        />
        <ImpactMetric
          label="Median / IQR"
          value={`${fmt(afterStats.median)} / ${fmt(afterStats.iqr)}`}
        />
        <ImpactMetric
          label="Full-data flagged"
          value={method.outlier_count.toLocaleString()}
        />
        <ImpactMetric
          label="Rendered changed"
          value={changed.toLocaleString()}
        />
        <ImpactMetric label="Method" value={methodLabel(method.method)} />
      </div>
      <p className="mt-2 text-[11px] text-slate-500">
        Common axis {fmt(pair.minimum)} to {fmt(pair.maximum)} · governed
        thresholds {fmt(method.lower_threshold)} to {fmt(method.upper_threshold)}
        . Optional target-rate comparison is not asserted when the bounded
        renderer does not include target labels.
      </p>
    </div>
  );
}

function HistogramPanel({
  title,
  bins,
  maximumBin,
  color,
  minimum,
  maximum,
  thresholdLow,
  thresholdHigh,
  testId,
  clipToThresholds = false,
}: {
  title: string;
  bins: number[];
  maximumBin: number;
  color: string;
  minimum: number;
  maximum: number;
  thresholdLow: number;
  thresholdHigh: number;
  testId?: string;
  clipToThresholds?: boolean;
}) {
  const span = maximum - minimum || 1;
  const lowPosition = Math.max(
    0,
    Math.min(100, ((thresholdLow - minimum) / span) * 100),
  );
  const highPosition = Math.max(
    0,
    Math.min(100, ((thresholdHigh - minimum) / span) * 100),
  );
  return (
    <div className="prep-chart-panel" data-testid={testId}>
      <div className="prep-chart-title">{title}</div>
      <div className="relative mt-3 h-44 border-b border-slate-300">
        <div
          className="absolute inset-0 flex items-end gap-px"
          style={
            clipToThresholds
              ? {
                  clipPath: `inset(0 ${Math.max(0, 100 - highPosition)}% 0 ${lowPosition}%)`,
                }
              : undefined
          }
          data-testid={
            clipToThresholds ? "outlier-capped-histogram-clip" : undefined
          }
        >
          {bins.map((count, index) => (
            <div
              key={index}
              className={`min-w-0 flex-1 rounded-t-sm ${color}`}
              style={{
                height: `${Math.max(count ? 3 : 0, (count / maximumBin) * 100)}%`,
                opacity: 0.8,
              }}
              title={`${count.toLocaleString()} rendered values`}
            />
          ))}
        </div>
        <span
          className="absolute inset-y-0 border-l border-dashed border-rose-500"
          style={{ left: `${lowPosition}%` }}
          aria-label={`Low cutoff ${fmt(thresholdLow)}`}
          title={`Low cutoff ${fmt(thresholdLow)}`}
          data-testid="outlier-low-cutoff-marker"
        />
        <span
          className="absolute inset-y-0 border-l border-dashed border-rose-500"
          style={{ left: `${highPosition}%` }}
          aria-label={`High cutoff ${fmt(thresholdHigh)}`}
          title={`High cutoff ${fmt(thresholdHigh)}`}
          data-testid="outlier-high-cutoff-marker"
        />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-slate-500">
        <span>{fmt(minimum)}</span>
        <span>Common axis</span>
        <span>{fmt(maximum)}</span>
      </div>
      {clipToThresholds ? (
        <p className="mt-1 text-[10px] leading-4 text-emerald-800">
          Capped tail mass is contained at the governed cutoffs; no treated
          value extends beyond the dashed threshold lines.
        </p>
      ) : null}
    </div>
  );
}

function describePreview(values: number[]) {
  const row = buildOutlierMethodComparisons(values)[0];
  return {
    minimum: row?.minimum ?? null,
    maximum: row?.maximum ?? null,
    median: row?.median ?? null,
    iqr: row?.iqr ?? null,
  };
}

function ImpactMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-1 truncate text-xs font-semibold text-slate-950" title={value}>
        {value}
      </div>
    </div>
  );
}

function MethodComparisonTable({
  rows,
}: {
  rows: OutlierMethodComparison[];
}) {
  return (
    <div
      className="overflow-x-auto rounded-lg border border-slate-200"
      data-testid="outlier-method-comparison"
    >
      <table className="min-w-[980px] w-full text-xs">
        <thead className="bg-slate-50 text-left uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2">Preview method</th>
            <th className="px-3 py-2">Retained rows</th>
            <th className="px-3 py-2">Changed</th>
            <th className="px-3 py-2">Range</th>
            <th className="px-3 py-2">Median / IQR</th>
            <th className="px-3 py-2">Rank order</th>
            <th className="px-3 py-2">Distortion / applicability</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.method}
              className={
                row.applicable
                  ? "border-t border-slate-100"
                  : "border-t border-slate-100 bg-slate-50 text-slate-400"
              }
            >
              <td className="px-3 py-2 font-semibold">{row.method}</td>
              <td className="px-3 py-2 tabular-nums">
                {row.retainedRows.toLocaleString()}
              </td>
              <td className="px-3 py-2 tabular-nums">
                {row.applicable ? row.changedValues.toLocaleString() : "—"}
              </td>
              <td className="px-3 py-2 tabular-nums">
                {row.applicable
                  ? `${fmt(row.minimum)} — ${fmt(row.maximum)}`
                  : "Unavailable"}
              </td>
              <td className="px-3 py-2 tabular-nums">
                {row.applicable
                  ? `${fmt(row.median)} / ${fmt(row.iqr)}`
                  : "Unavailable"}
              </td>
              <td className="px-3 py-2">{row.rankOrder}</td>
              <td className="max-w-sm px-3 py-2 leading-5">
                {row.distortionWarning}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PatternMap({
  rows,
  config,
  globalMethod,
  selectedFeature,
  applied,
  onSelect,
}: {
  rows: OutlierFeature[];
  config: Record<string, FeatureMethodKey>;
  globalMethod: MethodKey;
  selectedFeature: string;
  applied: boolean;
  onSelect: (feature: string) => void;
}) {
  return (
    <div
      className="overflow-x-auto rounded-lg border border-slate-200"
      data-testid="outlier-pattern-map"
    >
      <table className="min-w-[900px] w-full text-xs">
        <thead className="bg-slate-50 text-left uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2">Predictor</th>
            <th className="px-3 py-2">Ordinary outlier</th>
            <th className="px-3 py-2">Skewness</th>
            <th className="px-3 py-2">Bureau special</th>
            <th className="px-3 py-2">Nulls</th>
            <th className="px-3 py-2">IV / corr</th>
            <th className="px-3 py-2">Treatment / state</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 16).map((row) => {
            const method =
              row.methods?.[effectiveMethod(config[row.feature], globalMethod)];
            return (
              <tr
                key={row.feature}
                className={
                  selectedFeature === row.feature
                    ? "cursor-pointer border-t border-slate-100 bg-blue-50"
                    : "cursor-pointer border-t border-slate-100 hover:bg-slate-50"
                }
                onClick={() => onSelect(row.feature)}
              >
                <td className="px-3 py-2 font-semibold text-slate-900">
                  {row.feature}
                </td>
                <HeatCell
                  value={method?.outlier_rate ?? 0}
                  label={pct(method?.outlier_rate)}
                  color="rose"
                />
                <HeatCell
                  value={Math.min(1, Math.abs(row.skewness ?? 0) / 4)}
                  label={fmt(row.skewness)}
                  color="amber"
                />
                <HeatCell
                  value={row.special_value_rate}
                  label={`${row.special_value_count.toLocaleString()} · ${pct(row.special_value_rate)}`}
                  color="violet"
                />
                <HeatCell
                  value={row.missing_count / Math.max(row.nonmissing_count, 1)}
                  label={row.missing_count.toLocaleString()}
                  color="cyan"
                />
                <HeatCell
                  value={Math.min(1, Math.abs(row.signal_metric ?? 0))}
                  label={fmt(row.signal_metric, 4)}
                  color="blue"
                />
                <td className="px-3 py-2">
                  <span className="font-semibold text-slate-800">
                    {method ? methodLabel(method.method) : "None"}
                  </span>
                  <span
                    className={`ml-2 rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                      applied
                        ? "bg-emerald-100 text-emerald-700"
                        : "bg-amber-100 text-amber-700"
                    }`}
                  >
                    {applied ? "Applied" : "Selected"}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function HeatCell({
  value,
  label,
  color,
}: {
  value: number;
  label: string;
  color: "rose" | "amber" | "violet" | "cyan" | "blue";
}) {
  const backgrounds = {
    rose: "rgba(244,63,94,",
    amber: "rgba(245,158,11,",
    violet: "rgba(139,92,246,",
    cyan: "rgba(6,182,212,",
    blue: "rgba(59,130,246,",
  };
  return (
    <td
      className="px-3 py-2 tabular-nums"
      style={{
        backgroundColor: `${backgrounds[color]}${Math.min(0.55, Math.max(0.04, value * 2.5))})`,
      }}
    >
      {label}
    </td>
  );
}

function Pagination({
  page,
  pageCount,
  rowCount,
  pageSize,
  onPage,
}: {
  page: number;
  pageCount: number;
  rowCount: number;
  pageSize: number;
  onPage: (page: number) => void;
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
      <span>
        Showing {rowCount ? page * pageSize + 1 : 0}–
        {Math.min((page + 1) * pageSize, rowCount)} of{" "}
        {rowCount.toLocaleString()}
      </span>
      <div className="flex items-center gap-2">
        <button
          className="atlas-secondary-button"
          type="button"
          disabled={page === 0}
          onClick={() => onPage(Math.max(0, page - 1))}
        >
          Previous
        </button>
        <span>
          Page {page + 1} of {pageCount}
        </span>
        <button
          className="atlas-secondary-button"
          type="button"
          disabled={page >= pageCount - 1}
          onClick={() => onPage(Math.min(pageCount - 1, page + 1))}
        >
          Next
        </button>
      </div>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  Filter,
  Info,
  LoaderCircle,
  Play,
  Search,
  ShieldCheck,
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
import { loadLocalDataset } from "../lib/localDataset";
import {
  getEdaCarryForward,
  getPreparationDocumentation,
  saveCarryForwardDisposition,
  type CarryForwardDisposition,
  type PreparationCarryForwardItem,
  type PreparationDocumentationState,
} from "../lib/preparationGovernance";
import { useWorkflowStore } from "../state/useWorkflowStore";

type MissingStrategy =
  | "None"
  | "Mean"
  | "Median"
  | "Mode"
  | "Constant"
  | "Drop Row";
type MissingConfig = Record<
  string,
  { strategy: MissingStrategy; constantValue?: string }
>;
type ColumnInfo = { name: string; dtype: string; role: "feature" };
type MissingStats = {
  missing: number;
  missingPct: number;
  total: number;
  nonmissing_count: number;
  observed_count: number;
  distinct_count: number;
  mean: number | null;
  mode: string | number | boolean | null;
  standard_deviation: number | null;
  minimum: number | null;
  first_quartile: number | null;
  median: number | null;
  third_quartile: number | null;
  maximum: number | null;
  information_value: number | null;
  correlation_with_target: number | null;
  association_status: string;
  special_value_count: number;
  special_value_rate: number;
  special_values: Record<string, number>;
  distribution: {
    kind: "numeric" | "categorical";
    bins: Array<{
      label: string;
      lower: number | null;
      upper: number | null;
      count: number;
    }>;
    observed_count: number;
    ordinary_numeric_count: number | null;
    missing_count: number;
    special_value_count: number;
    parse_failure_count: number;
    reference_cutoffs: {
      lower: number;
      upper: number;
      method: string;
    } | null;
    cutoff_semantics: string;
  };
  informative: boolean;
  missing_target_metric: number | null;
  present_target_metric: number | null;
  difference: number | null;
  standardized_difference?: number | null;
};
type MissingApplication = {
  applied_at: string;
  dataset_version: string;
  config: MissingConfig;
  config_signature: string;
  source_stage: string;
  rows_before: number;
  rows_after: number;
  missing_before: number;
  missing_after: number;
  dropped_rows: number;
  treatments: Array<{
    feature: string;
    strategy: MissingStrategy;
    filled: number;
    value?: string;
    dropped_rows?: number;
  }>;
};
type MissingValidation = {
  validated_at: string;
  dataset_version: string;
  source_stage: string;
  row_count: number;
  predictor_count: number;
  missing_cells: 0;
  strategy: "None";
  status: "validated_no_treatment_required";
  backend_materialization: false;
  statement: "Validated, no treatment required.";
};
type MissingSummary = {
  ok: boolean;
  scope: "full_dataset";
  rows: number;
  columns: ColumnInfo[];
  stats: Record<string, MissingStats>;
  target: string | null;
  problem_type: "classification" | "regression";
  event_value: unknown;
  event_rate: number | null;
  rare_event: boolean;
  source_stage: string;
  dataset_version: string;
  predictor_authorization: {
    authorized_predictors: string[];
    excluded_predictors: Record<string, string>;
    target_source_excluded: string[];
  };
  application?: MissingApplication | null;
  validation?: MissingValidation | null;
};

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";
const CONFIG_KEY = "modeling-tool-missing-config";
const POLICY_VERSION = 2;
const PAGE_SIZE = 20;
const STRATEGIES: MissingStrategy[] = [
  "None",
  "Mean",
  "Median",
  "Mode",
  "Constant",
  "Drop Row",
];
const STRATEGY_GUIDANCE: Record<MissingStrategy, string> = {
  None: "Recommended when no true nulls exist or when a downstream estimator intentionally preserves missingness.",
  Mean: "Numeric only. Prefer for approximately symmetric variables after sensitivity review.",
  Median: "Numeric only. More robust for skewed ordinary values; bureau specials stay separate.",
  Mode: "Appropriate for categorical or discrete fields when the most common value is substantively defensible.",
  Constant:
    "Uses an explicit governed value. The constant field appears only for this strategy.",
  "Drop Row":
    "High-impact option. Use only after population loss and selection bias are reviewed.",
};

type StoredMissingPolicy = {
  policyVersion: typeof POLICY_VERSION;
  globalStrategy: MissingStrategy;
  globalConstant: string;
  config: MissingConfig;
  overrideFeatures: string[];
};

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

function isNumeric(column: ColumnInfo) {
  return /int|float|double|decimal|number|numeric/i.test(column.dtype);
}

function normalizeConfig(columns: ColumnInfo[], config: MissingConfig) {
  return Object.fromEntries(
    columns.map((column) => [
      column.name,
      config[column.name] ?? { strategy: "None" },
    ]),
  ) as MissingConfig;
}

function compatibleStrategy(
  column: ColumnInfo,
  strategy: MissingStrategy,
): MissingStrategy {
  return !isNumeric(column) && ["Mean", "Median"].includes(strategy)
    ? "Mode"
    : strategy;
}

function migrateLegacyPolicy(
  columns: ColumnInfo[],
  legacyConfig: MissingConfig,
): StoredMissingPolicy {
  const config = normalizeConfig(columns, legacyConfig);
  let globalStrategy: MissingStrategy = "None";
  let globalConstant = "";
  let bestMatchCount = -1;

  for (const candidate of STRATEGIES) {
    let candidateConstant = "";
    if (candidate === "Constant") {
      const counts = new Map<string, number>();
      for (const column of columns) {
        const rule = config[column.name];
        if (rule.strategy !== "Constant") continue;
        const value = String(rule.constantValue ?? "");
        counts.set(value, (counts.get(value) ?? 0) + 1);
      }
      candidateConstant =
        [...counts.entries()].sort(
          ([leftValue, leftCount], [rightValue, rightCount]) =>
            rightCount - leftCount || leftValue.localeCompare(rightValue),
        )[0]?.[0] ?? "";
    }

    const matchCount = columns.filter((column) => {
      const expected = compatibleStrategy(column, candidate);
      const rule = config[column.name];
      if (rule.strategy !== expected) return false;
      return (
        expected !== "Constant" ||
        String(rule.constantValue ?? "") === candidateConstant
      );
    }).length;
    if (matchCount > bestMatchCount) {
      bestMatchCount = matchCount;
      globalStrategy = candidate;
      globalConstant = candidateConstant;
    }
  }

  const overrideFeatures = columns
    .filter((column) => {
      const expected = compatibleStrategy(column, globalStrategy);
      const rule = config[column.name];
      if (rule.strategy !== expected) return true;
      return (
        expected === "Constant" &&
        String(rule.constantValue ?? "") !== globalConstant
      );
    })
    .map((column) => column.name);

  return {
    policyVersion: POLICY_VERSION,
    globalStrategy,
    globalConstant,
    config,
    overrideFeatures,
  };
}

function configMatchesApplication(
  summary: MissingSummary | null,
  config: MissingConfig,
) {
  if (!summary?.application) return false;
  return (
    JSON.stringify(normalizeConfig(summary.columns, config)) ===
    JSON.stringify(normalizeConfig(summary.columns, summary.application.config))
  );
}

function validationMatchesSummary(summary: MissingSummary | null) {
  if (!summary?.validation) return false;
  return (
    summary.validation.dataset_version === summary.dataset_version &&
    summary.validation.source_stage === summary.source_stage &&
    summary.validation.missing_cells === 0
  );
}

function pct(value: number | null | undefined, alreadyPercent = false) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "Not available";
  }
  return `${(alreadyPercent ? value : value * 100).toFixed(2)}%`;
}

function strategyOptions(column: ColumnInfo) {
  return isNumeric(column)
    ? STRATEGIES
    : STRATEGIES.filter((strategy) => !["Mean", "Median"].includes(strategy));
}

export default function Step04MissingValues() {
  const localDataset = loadLocalDataset();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [summary, setSummary] = useState<MissingSummary | null>(null);
  const [config, setConfig] = useState<MissingConfig>({});
  const [globalStrategy, setGlobalStrategy] =
    useState<MissingStrategy>("None");
  const [globalConstant, setGlobalConstant] = useState("");
  const [overrideFeatures, setOverrideFeatures] = useState<Set<string>>(
    () => new Set(),
  );
  const [impactLimit, setImpactLimit] = useState(10);
  const [additionalImpactFeatures, setAdditionalImpactFeatures] = useState<Set<string>>(
    () => new Set(),
  );
  const [settingsHydratedFor, setSettingsHydratedFor] = useState("");
  const hydrationRequest = useRef(0);
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<
    "missing" | "special" | "name" | "informative" | "iv"
  >("missing");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [validationFailed, setValidationFailed] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [carryForward, setCarryForward] = useState<
    PreparationCarryForwardItem[]
  >([]);
  const [edaDocumentStatus, setEdaDocumentStatus] = useState("unavailable");
  const [edaManifest, setEdaManifest] = useState("");
  const [preparationDocs, setPreparationDocs] =
    useState<PreparationDocumentationState | null>(null);

  async function loadSummary() {
    const requestNumber = hydrationRequest.current + 1;
    hydrationRequest.current = requestNumber;
    const requestedProjectId = projectId;
    setSettingsHydratedFor("");
    setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams();
      query.set("project_id", projectId);
      if (
        localDataset?.event_value !== undefined &&
        localDataset?.event_value !== null
      ) {
        query.set("event_value", String(localDataset.event_value));
      }
      if (localDataset?.problem_type) {
        query.set("problem_type", localDataset.problem_type);
      }
      const payload = await requestJson<MissingSummary>(
        `/missing/summary?${query.toString()}`,
      );
      if (requestNumber !== hydrationRequest.current) return;
      const normalizedStats = Object.fromEntries(
        payload.columns.map((column) => {
          const stats = payload.stats[column.name];
          return [
            column.name,
            {
              ...stats,
              special_value_count: stats?.special_value_count ?? 0,
              special_value_rate: stats?.special_value_rate ?? 0,
              special_values: stats?.special_values ?? {},
              nonmissing_count:
                stats?.nonmissing_count ??
                Math.max(0, payload.rows - (stats?.missing ?? 0)),
              observed_count:
                stats?.observed_count ??
                Math.max(
                  0,
                  payload.rows -
                    (stats?.missing ?? 0) -
                    (stats?.special_value_count ?? 0),
                ),
              distinct_count: stats?.distinct_count ?? 0,
              mean: stats?.mean ?? null,
              mode: stats?.mode ?? null,
              standard_deviation: stats?.standard_deviation ?? null,
              minimum: stats?.minimum ?? null,
              first_quartile: stats?.first_quartile ?? null,
              median: stats?.median ?? null,
              third_quartile: stats?.third_quartile ?? null,
              maximum: stats?.maximum ?? null,
              information_value: stats?.information_value ?? null,
              correlation_with_target:
                stats?.correlation_with_target ?? null,
              association_status:
                stats?.association_status ?? "not_evaluated",
              distribution: stats?.distribution ?? {
                kind: isNumeric(column) ? "numeric" : "categorical",
                bins: [],
                observed_count: Math.max(
                  0,
                  payload.rows -
                    (stats?.missing ?? 0) -
                    (stats?.special_value_count ?? 0),
                ),
                ordinary_numeric_count: null,
                missing_count: stats?.missing ?? 0,
                special_value_count: stats?.special_value_count ?? 0,
                parse_failure_count: 0,
                reference_cutoffs: null,
                cutoff_semantics:
                  "Distribution evidence is unavailable until the full-data summary is refreshed.",
              },
            },
          ];
        }),
      );
      const safePayload = {
        ...payload,
        stats: normalizedStats,
        predictor_authorization: payload.predictor_authorization ?? {
          authorized_predictors: payload.columns.map((column) => column.name),
          excluded_predictors: {},
          target_source_excluded: [],
        },
      };
      let storedConfig: MissingConfig = {};
      let storedPolicy: StoredMissingPolicy | null = null;
      try {
        const scopedPolicy =
          localStorage.getItem(`${CONFIG_KEY}:${projectId}`) ??
          localStorage.getItem(CONFIG_KEY);
        const stored = JSON.parse(scopedPolicy || "{}");
        if (
          stored?.policyVersion === POLICY_VERSION &&
          stored?.config &&
          Array.isArray(stored.overrideFeatures)
        ) {
          storedPolicy = stored as StoredMissingPolicy;
          storedConfig = storedPolicy.config;
        } else if (Object.keys(stored).length) {
          storedPolicy = migrateLegacyPolicy(
            safePayload.columns,
            stored as MissingConfig,
          );
          storedConfig = storedPolicy.config;
        }
      } catch {
        storedConfig = {};
      }
      const source = Object.keys(storedConfig).length
        ? storedConfig
        : safePayload.application?.config ?? {};
      setSummary(safePayload);
      setConfig(normalizeConfig(safePayload.columns, source));
      setGlobalStrategy(storedPolicy?.globalStrategy ?? "None");
      setGlobalConstant(storedPolicy?.globalConstant ?? "");
      setOverrideFeatures(
        new Set(
          storedPolicy?.overrideFeatures ??
            safePayload.columns
              .filter(
                (column) =>
                  (source[column.name]?.strategy ?? "None") !== "None",
              )
              .map((column) => column.name),
        ),
      );
      setSettingsHydratedFor(requestedProjectId);
    } catch (cause) {
      if (requestNumber !== hydrationRequest.current) return;
      setError(
        cause instanceof Error
          ? cause.message
          : "Full-data missingness analysis is unavailable.",
      );
    } finally {
      if (requestNumber === hydrationRequest.current) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    void loadSummary();
    const controller = new AbortController();
    getEdaCarryForward(projectId, "missing_values", controller.signal)
      .then((context) => {
        setCarryForward(context.items);
        setEdaDocumentStatus(context.documentationStatus);
        setEdaManifest(context.predictorManifestId);
      })
      .catch(() => undefined);
    getPreparationDocumentation(projectId, controller.signal)
      .then(setPreparationDocs)
      .catch(() => undefined);
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => {
    if (settingsHydratedFor !== projectId) return;
    try {
      const policy: StoredMissingPolicy = {
        policyVersion: POLICY_VERSION,
        globalStrategy,
        globalConstant,
        config,
        overrideFeatures: [...overrideFeatures],
      };
      localStorage.setItem(
        `${CONFIG_KEY}:${projectId}`,
        JSON.stringify(policy),
      );
    } catch {
      setMessage(
        "Selections are retained for this session, but browser persistence is unavailable.",
      );
    }
  }, [
    config,
    globalConstant,
    globalStrategy,
    overrideFeatures,
    projectId,
    settingsHydratedFor,
  ]);

  const totalMissing =
    summary?.columns.reduce(
      (sum, column) => sum + (summary.stats[column.name]?.missing ?? 0),
      0,
    ) ?? 0;
  const totalSpecial =
    summary?.columns.reduce(
      (sum, column) =>
        sum + (summary.stats[column.name]?.special_value_count ?? 0),
      0,
    ) ?? 0;
  const affectedPredictors =
    summary?.columns.filter(
      (column) => (summary.stats[column.name]?.missing ?? 0) > 0,
    ).length ?? 0;
  const specialPredictors =
    summary?.columns.filter(
      (column) =>
        (summary.stats[column.name]?.special_value_count ?? 0) > 0,
    ).length ?? 0;
  const informativeCount =
    summary?.columns.filter(
      (column) => summary.stats[column.name]?.informative,
    ).length ?? 0;
  const validationCurrent = validationMatchesSummary(summary);
  const applied =
    totalMissing === 0
      ? validationCurrent
      : configMatchesApplication(summary, config);
  const rows = useMemo(() => {
    const filtered = (summary?.columns ?? []).filter((column) =>
      column.name.toLowerCase().includes(search.trim().toLowerCase()),
    );
    return [...filtered].sort((a, b) => {
      if (sortBy === "name") return a.name.localeCompare(b.name);
      if (sortBy === "special") {
        return (
          (summary?.stats[b.name]?.special_value_count ?? 0) -
          (summary?.stats[a.name]?.special_value_count ?? 0)
        );
      }
      if (sortBy === "informative") {
        return (
          Number(summary?.stats[b.name]?.informative ?? false) -
            Number(summary?.stats[a.name]?.informative ?? false) ||
          (summary?.stats[b.name]?.missingPct ?? 0) -
            (summary?.stats[a.name]?.missingPct ?? 0)
        );
      }
      if (sortBy === "iv") {
        return (
          (summary?.stats[b.name]?.information_value ?? -1) -
            (summary?.stats[a.name]?.information_value ?? -1) ||
          a.name.localeCompare(b.name)
        );
      }
      return (
        (summary?.stats[b.name]?.missingPct ?? 0) -
        (summary?.stats[a.name]?.missingPct ?? 0)
      );
    });
  }, [search, sortBy, summary]);
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pagedRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const ivRankedColumns = useMemo(
    () =>
      [...(summary?.columns ?? [])].sort(
        (left, right) =>
          (summary?.stats[right.name]?.information_value ?? -1) -
            (summary?.stats[left.name]?.information_value ?? -1) ||
          left.name.localeCompare(right.name),
      ),
    [summary],
  );
  const impactColumns = useMemo(() => {
    const base = ivRankedColumns.slice(0, impactLimit);
    const names = new Set(base.map((column) => column.name));
    for (const column of ivRankedColumns) {
      if (additionalImpactFeatures.has(column.name)) names.add(column.name);
    }
    return ivRankedColumns.filter((column) => names.has(column.name));
  }, [additionalImpactFeatures, impactLimit, ivRankedColumns]);
  const selectedTreatmentCount = summary
    ? summary.columns.filter(
        (column) => (config[column.name]?.strategy ?? "None") !== "None",
      ).length
    : 0;
  const documentationStatus = applied
    ? "confirmed"
    : summary?.application || summary?.validation
      ? "stale"
      : (preparationDocs?.missing_values.status ?? "draft");
  const decisionState = applying
    ? totalMissing
      ? "Applying"
      : "Validating"
    : validationFailed
      ? "Failed"
      : applied
        ? totalMissing
          ? "Applied"
          : "Validated"
        : summary?.application || summary?.validation
          ? "Stale"
          : totalMissing
            ? "Selected"
            : "Recommended: None";

  function updateStrategy(column: string, strategy: MissingStrategy) {
    logDecision({
      workflowStep: "Missing Values",
      actionType: "missing_value_strategy_selected",
      subject: column,
      previousValue: config[column]?.strategy ?? "None",
      newValue: strategy,
    });
    setConfig((current) => ({
      ...current,
      [column]: {
        strategy,
        ...(strategy === "Constant"
          ? { constantValue: current[column]?.constantValue ?? "" }
          : {}),
      },
    }));
    setOverrideFeatures((current) => new Set(current).add(column));
    setValidationFailed(false);
    setMessage(
      "Treatment selection changed. Preview the impact before backend materialization.",
    );
  }

  function useGlobalStrategy(column: ColumnInfo) {
    const compatible =
      !isNumeric(column) && ["Mean", "Median"].includes(globalStrategy)
        ? "Mode"
        : globalStrategy;
    setOverrideFeatures((current) => {
      const next = new Set(current);
      next.delete(column.name);
      return next;
    });
    setConfig((current) => ({
      ...current,
      [column.name]: {
        strategy: compatible,
        ...(compatible === "Constant"
          ? { constantValue: globalConstant }
          : {}),
      },
    }));
    setValidationFailed(false);
    setMessage(
      `${column.name} now inherits the global ${compatible} strategy.`,
    );
  }

  function updateConstant(column: string, constantValue: string) {
    setConfig((current) => ({
      ...current,
      [column]: { strategy: "Constant", constantValue },
    }));
  }

  function buildGlobalConfig(
    strategy: MissingStrategy,
    constantValue: string,
  ) {
    if (!summary) return null;
    return Object.fromEntries(
      summary.columns.map((column) => {
        if (overrideFeatures.has(column.name)) {
          return [
            column.name,
            config[column.name] ?? { strategy: "None" as MissingStrategy },
          ];
        }
        const compatible =
          !isNumeric(column) && ["Mean", "Median"].includes(strategy)
            ? "Mode"
            : strategy;
        return [
          column.name,
          {
            strategy: compatible,
            ...(compatible === "Constant" ? { constantValue } : {}),
          },
        ];
      }),
    ) as MissingConfig;
  }

  function updateGlobalStrategy(strategy: MissingStrategy) {
    setGlobalStrategy(strategy);
    const next = buildGlobalConfig(strategy, globalConstant);
    if (!next) return;
    setConfig(next);
    setValidationFailed(false);
    setMessage(
      strategy === "None"
        ? overrideFeatures.size
          ? `None is selected globally; ${overrideFeatures.size} explicit feature override${overrideFeatures.size === 1 ? "" : "s"} remain in place.`
          : "None is selected globally. No null imputation will be materialized."
        : "Changing the global strategy immediately updates compatible feature-level selections and their projected table states. Explicit feature overrides remain in place; numeric-only choices fall back to Mode for categorical predictors.",
    );
  }

  function updateGlobalConstant(value: string) {
    setGlobalConstant(value);
    if (globalStrategy !== "Constant") return;
    const next = buildGlobalConfig("Constant", value);
    if (next) setConfig(next);
  }

  function handleCarryForward(
    item: PreparationCarryForwardItem,
    disposition: CarryForwardDisposition,
  ) {
    saveCarryForwardDisposition(
      projectId,
      "missing_values",
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
        ? `${item.title} is accepted as a governed input. It does not convert bureau special values into nulls.`
        : `${item.title} remains ${disposition} at the Missing Values destination.`,
    );
  }

  async function validateNoTreatment(): Promise<MissingValidation | null> {
    if (!summary) return null;
    setApplying(true);
    setValidationFailed(false);
    setError("");
    try {
      const payload = await requestJson<{
        ok: true;
        scope: "full_dataset";
        validation: MissingValidation;
      }>("/missing/validate", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          event_value: summary.event_value,
          problem_type: summary.problem_type,
        }),
      });
      setSummary((current) =>
        current
          ? { ...current, validation: payload.validation, application: null }
          : current,
      );
      setPreparationDocs((current) =>
        current
          ? {
              ...current,
              missing_values: {
                status: "confirmed",
                application: null,
                validation: payload.validation,
              },
            }
          : current,
      );
      setMessage(
        "Validated, no treatment required. No backend modeling frame was materialized.",
      );
      return payload.validation;
    } catch (cause) {
      const detail =
        cause instanceof Error
          ? cause.message
          : "Missing-value validation failed.";
      setValidationFailed(true);
      setError(detail);
      return null;
    } finally {
      setApplying(false);
    }
  }

  async function applyTreatments(): Promise<MissingApplication | null> {
    if (!summary) return null;
    if (totalMissing === 0) return null;
    const missingConstant = summary.columns.find(
      (column) =>
        config[column.name]?.strategy === "Constant" &&
        !String(config[column.name]?.constantValue ?? "").trim(),
    );
    if (missingConstant) {
      setError(
        `Enter a constant value for ${missingConstant.name} before applying treatments.`,
      );
      return null;
    }
    const dropRowFeatures = summary.columns.filter(
      (column) => config[column.name]?.strategy === "Drop Row",
    );
    if (
      dropRowFeatures.length &&
      !window.confirm(
        `Drop Row is selected for ${dropRowFeatures.length} predictor${dropRowFeatures.length === 1 ? "" : "s"}. This changes the modeling population and may introduce selection bias. Apply only after reviewing the row-loss preview. Continue?`,
      )
    ) {
      setMessage("Row-removal treatment was not applied.");
      return null;
    }
    setApplying(true);
    setValidationFailed(false);
    setError("");
    try {
      const payload = await requestJson<{
        ok: true;
        scope: "full_dataset";
        application: MissingApplication;
      }>("/missing/apply", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          config: normalizeConfig(summary.columns, config),
          event_value: summary.event_value,
          problem_type: summary.problem_type,
        }),
      });
      setSummary((current) =>
        current
          ? { ...current, application: payload.application, validation: null }
          : current,
      );
      setMessage(
        `Applied ${payload.application.treatments.length.toLocaleString()} governed treatments. True nulls changed from ${payload.application.missing_before.toLocaleString()} to ${payload.application.missing_after.toLocaleString()}; bureau special values remained separate.`,
      );
      return payload.application;
    } catch (cause) {
      const detail =
        cause instanceof Error
          ? cause.message
          : "Missing-value treatments could not be applied.";
      setValidationFailed(true);
      setError(detail);
      return null;
    } finally {
      setApplying(false);
    }
  }

  async function completeStep() {
    if (!summary) return false;
    const decision =
      totalMissing === 0
        ? validationCurrent && summary.validation
          ? summary.validation
          : await validateNoTreatment()
        : configMatchesApplication(summary, config) && summary.application
          ? summary.application
          : await applyTreatments();
    if (!decision) return false;
    const isValidation = "validated_at" in decision;
    await createEvidence({
      projectId,
      projectName,
      evidenceType: "missing_values",
      title: isValidation
        ? "Missing-Value Validation — No Treatment Required"
        : "Governed Missing-Value Treatment",
      summary: isValidation
        ? "No null imputation is required for the current modeling population. Bureau special values remain governed values and are handled separately."
        : `${decision.treatments.length.toLocaleString()} treatments were applied. True nulls changed from ${decision.missing_before.toLocaleString()} to ${decision.missing_after.toLocaleString()}.`,
      sourcePage: "Missing Values",
      sourceRoute: "/step04",
      datasetIds: [decision.dataset_version],
      modelIds: [],
      documentIds: [],
      notebookIds: [],
      supportsSections: [
        "Missing Value Treatment",
        "Data Quality",
        "Feature Engineering",
      ],
      tags: [
        "predictive_modeling",
        "missing_values",
        isValidation ? "validated_no_treatment" : "full_dataset",
        "special_values_separate",
      ],
      status: "ready",
      importance: "high",
      lineage: {
        datasetVersion: decision.dataset_version,
        sourceStage: decision.source_stage,
        scope: "full_dataset",
        backendMaterialization: !isValidation,
      },
      payload: decision,
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
    `authorized:${summary?.columns.length ?? 0}`;

  return (
    <StepShell
      title=""
      hideHeader
      nextPath="/step05"
      onNext={completeStep}
      nextDisabled={loading || !summary || !!error || applying}
      nextDisabledReason={
        error || "Load the governed missingness profile before continuing."
      }
      nextLabel={
        totalMissing === 0
          ? "Validate & Continue"
          : "Confirm Missing Values & Continue"
      }
      nextStatusLine={
        applied
          ? totalMissing === 0
            ? "Validated, no treatment required. Continue to Feature Engineering."
            : "The current treatment is materialized and ready for Feature Engineering."
          : totalMissing === 0
            ? "Validation records a no-treatment decision without backend materialization."
            : "Selected strategies will be materialized only after explicit confirmation."
      }
      showEmbeddedNext
      nextAlwaysVisible
      nextFooterTestId="missing-values-sticky-footer"
    >
      <div className="prep-premium-page space-y-4">
        <PreparationPageIdentity
          step="Step 4 of 13"
          title="Missing Values"
          description="Distinguish true nulls from governed bureau special values, validate the current population, and materialize only a necessary treatment."
          datasetName={datasetName}
          datasetVersion={
            summary?.dataset_version || localDataset?.dataset_version || ""
          }
          target={summary?.target || localDataset?.target || ""}
          predictorCount={summary?.columns.length ?? 0}
          predictorManifest={manifestId}
          documentationStatus={documentationStatus}
          decisionState={decisionState}
        />

        <PreparationQuickSummary
          metrics={[
            {
              label: "Predictors",
              value: (summary?.columns.length ?? 0).toLocaleString(),
              tone: "info",
            },
            {
              label: "True nulls",
              value: totalMissing.toLocaleString(),
              tone: totalMissing ? "warning" : "success",
            },
            {
              label: "Affected",
              value: affectedPredictors.toLocaleString(),
              tone: affectedPredictors ? "warning" : "success",
            },
            {
              label: "Special values",
              value: totalSpecial.toLocaleString(),
              detail: `${specialPredictors} predictors`,
              tone: totalSpecial ? "info" : "neutral",
            },
            {
              label: "Recommendation",
              value: totalMissing ? "Review" : "None",
              tone: totalMissing ? "warning" : "success",
            },
            {
              label: "Global strategy",
              value: globalStrategy,
            },
            {
              label: "Decision state",
              value: decisionState,
              tone: applied
                ? "success"
                : validationFailed
                  ? "danger"
                  : "warning",
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
            <LoaderCircle size={28} className="animate-spin text-blue-600" />
          </div>
        ) : null}
        {error ? (
          <AtlasAttentionPanel
            title="Missing-value decision requires attention"
            tone="danger"
          >
            <div className="space-y-3">
              <p>{error}</p>
              {!summary ? (
                <button
                  type="button"
                  className="atlas-primary-button"
                  onClick={() => void loadSummary()}
                >
                  Retry analysis
                </button>
              ) : null}
            </div>
          </AtlasAttentionPanel>
        ) : null}

        {summary ? (
          <>
            <PreparationGovernanceDisclosure
              summary={`${summary.columns.length.toLocaleString()} predictors authorized · ${totalSpecial.toLocaleString()} special values preserved · MDD ${documentationStatus}`}
            >
              <AtlasStatusStrip
                items={[
                  {
                    label: "Input stage",
                    state: "complete",
                    detail:
                      summary.source_stage === "outlier_treated"
                        ? "Confirmed outlier treatment"
                        : "Registered dataset",
                  },
                  {
                    label: "Null / special separation",
                    state: "complete",
                    detail: `${totalMissing.toLocaleString()} / ${totalSpecial.toLocaleString()}`,
                  },
                  {
                    label: "Decision",
                    state: applied
                      ? "complete"
                      : validationFailed
                        ? "blocked"
                        : "warning",
                    detail: decisionState,
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
                  is unavailable to missingness policy and imputation.
                </div>
              ) : null}
            </PreparationGovernanceDisclosure>

            {totalMissing === 0 ? (
              <section
                className="rounded-lg border border-emerald-200 bg-gradient-to-r from-emerald-50 to-cyan-50 px-3 py-2.5 shadow-sm"
                data-testid="missing-values-zero-state"
              >
                <div className="flex items-start gap-3">
                  <CheckCircle2
                    size={22}
                    className="mt-0.5 shrink-0 text-emerald-700"
                  />
                  <div>
                    <h2 className="text-sm font-semibold text-emerald-950">
                      No null imputation is required for the current modeling
                      population.
                    </h2>
                    <p className="mt-0.5 text-xs text-emerald-900">
                      Bureau special values remain governed values and are
                      handled separately.
                    </p>
                    <p className="mt-1 text-[11px] leading-4 text-emerald-800">
                      Recommended strategy: <strong>None</strong>. Validation
                      records this decision without creating a new backend
                      modeling frame.
                    </p>
                  </div>
                </div>
              </section>
            ) : null}

            {summary.rare_event ? (
              <AtlasAttentionPanel
                title="Rare-event missingness review"
                tone="warning"
              >
                The governed event rate is {pct(summary.event_rate)}.
                Missingness indicators can carry signal, so compare target
                rates before erasing a missing/not-missing distinction.
              </AtlasAttentionPanel>
            ) : null}
            {informativeCount ? (
              <AtlasAttentionPanel
                title="Potentially informative missingness"
                tone="warning"
              >
                {informativeCount.toLocaleString()} predictor
                {informativeCount === 1 ? "" : "s"} show a material target
                difference when missing. Review an explicit indicator or
                governed constant before simple imputation.
              </AtlasAttentionPanel>
            ) : null}

            <AtlasWorkflowSection
              eyebrow="Primary decision workspace"
              title="All-Feature Missing-Value Summary and Treatment"
              description="Every authorized predictor is visible in one scrollable table. Change the global treatment or a feature override and the projected state updates immediately; no treatment is materialized until confirmation."
              tone="info"
              id="missing-feature-table"
              action={
                <AtlasDataScopeBadge scope="full_dataset" rows={summary.rows} />
              }
            >
              <div
                className="mb-4 grid gap-3 rounded-xl border border-blue-200 bg-blue-50/60 p-3 lg:grid-cols-[minmax(230px,300px)_minmax(0,1fr)]"
                data-testid="missing-global-policy"
              >
                <div>
                  <label>
                    <span className="atlas-label">Global treatment</span>
                    <select
                      className="atlas-input mt-1"
                      value={globalStrategy}
                      onChange={(event) =>
                        updateGlobalStrategy(
                          event.target.value as MissingStrategy,
                        )
                      }
                      data-testid="missing-global-strategy"
                    >
                      {STRATEGIES.map((strategy) => (
                        <option key={strategy} value={strategy}>
                          {strategy}
                        </option>
                      ))}
                    </select>
                  </label>
                  {globalStrategy === "Constant" ? (
                    <label className="mt-3 block">
                      <span className="atlas-label">
                        Governed constant value
                      </span>
                      <input
                        className="atlas-input mt-1"
                        value={globalConstant}
                        onChange={(event) =>
                          updateGlobalConstant(event.target.value)
                        }
                        placeholder="Required for Constant"
                      />
                    </label>
                  ) : null}
                </div>
                <div className="text-xs leading-5 text-slate-700">
                  <strong className="text-slate-950">
                    {globalStrategy} guidance:
                  </strong>{" "}
                  {STRATEGY_GUIDANCE[globalStrategy]}
                  <p className="mt-1 text-slate-600">
                    The selector remains interactive when the current dataset
                    has zero nulls so treatment planning can be reviewed. The
                    governed completion still records “no treatment required”
                    unless true nulls are present.
                  </p>
                  {overrideFeatures.size ? (
                    <p className="mt-1 font-semibold text-blue-800">
                      {overrideFeatures.size} feature override
                      {overrideFeatures.size === 1 ? "" : "s"} take precedence
                      over the global treatment.
                    </p>
                  ) : null}
                </div>
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
                  />
                </label>
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-600">
                  <Filter size={15} />
                  <select
                    className="atlas-input min-w-44"
                    value={sortBy}
                    onChange={(event) =>
                      setSortBy(event.target.value as typeof sortBy)
                    }
                  >
                    <option value="missing">Missing rate</option>
                    <option value="iv">Information value</option>
                    <option value="special">Bureau special values</option>
                    <option value="informative">Informative flags</option>
                    <option value="name">Feature name</option>
                  </select>
                </label>
              </div>

              <div className="max-h-[430px] overflow-auto rounded-lg border border-slate-200 bg-white">
                <table
                  className="min-w-[2180px] w-full text-xs"
                  data-testid="missing-all-feature-table"
                >
                  <thead className="sticky top-0 z-10 bg-slate-100 text-left uppercase tracking-wide text-slate-600 shadow-sm">
                    <tr>
                      <th className="sticky left-0 z-20 bg-slate-100 px-3 py-2">
                        Predictor
                      </th>
                      <th className="px-3 py-2 text-right">Missing</th>
                      <th className="px-3 py-2 text-right">Missing rate</th>
                      <th className="min-w-44 px-3 py-2">Imputed value</th>
                      <th className="min-w-64 px-3 py-2">Treatment / override</th>
                      <th className="px-3 py-2 text-right">Nonmissing</th>
                      <th className="px-3 py-2 text-right">IV</th>
                      <th className="px-3 py-2 text-right">Bureau specials</th>
                      <th className="px-3 py-2 text-right">Distinct</th>
                      <th className="px-3 py-2 text-right">Mean</th>
                      <th className="px-3 py-2 text-right">Std dev</th>
                      <th className="px-3 py-2 text-right">Min</th>
                      <th className="px-3 py-2 text-right">Q1</th>
                      <th className="px-3 py-2 text-right">Median</th>
                      <th className="px-3 py-2 text-right">Q3</th>
                      <th className="px-3 py-2 text-right">Max</th>
                      <th className="px-3 py-2">Parameter</th>
                      <th className="px-3 py-2">Projected state</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((column) => {
                      const stats = summary.stats[column.name];
                      const selected = config[column.name] ?? {
                        strategy: "None" as MissingStrategy,
                      };
                      const overridden = overrideFeatures.has(column.name);
                      const compatibleGlobal =
                        !isNumeric(column) &&
                        ["Mean", "Median"].includes(globalStrategy)
                          ? "Mode"
                          : globalStrategy;
                      const projectedValue = projectedImputationValue(
                        stats,
                        selected.strategy,
                        selected.constantValue,
                      );
                      return (
                        <tr
                          key={column.name}
                          className={
                            overridden
                              ? "border-t border-blue-100 bg-blue-50/40"
                              : stats?.informative
                                ? "border-t border-amber-100 bg-amber-50/40"
                                : "border-t border-slate-100 hover:bg-slate-50"
                          }
                        >
                          <td className="sticky left-0 z-[1] bg-inherit px-3 py-2 font-semibold text-slate-950">
                            {column.name}
                            {overridden ? (
                              <span className="ml-2 rounded-full border border-blue-200 bg-blue-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-blue-800">
                                Override
                              </span>
                            ) : null}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            <span className="block text-sm font-bold text-amber-800">
                              {stats?.missing.toLocaleString() ?? "0"}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right font-semibold tabular-nums text-amber-800">
                            {pct(stats?.missingPct, true)}
                          </td>
                          <td
                            className="px-3 py-2"
                            data-testid={`missing-imputed-value-${column.name}`}
                          >
                            <span className="inline-flex rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 font-bold text-blue-900">
                              {projectedValue}
                            </span>
                          </td>
                          <td className="px-3 py-2">
                            <select
                              className="atlas-input min-w-48"
                              value={
                                overridden
                                  ? selected.strategy
                                  : "USE_GLOBAL"
                              }
                              onChange={(event) => {
                                if (event.target.value === "USE_GLOBAL") {
                                  useGlobalStrategy(column);
                                } else {
                                  updateStrategy(
                                    column.name,
                                    event.target.value as MissingStrategy,
                                  );
                                }
                              }}
                              data-testid={`missing-override-${column.name}`}
                            >
                              <option value="USE_GLOBAL">
                                Use global ({compatibleGlobal})
                              </option>
                              {strategyOptions(column).map((strategy) => (
                                <option key={strategy} value={strategy}>
                                  Override: {strategy}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {stats?.nonmissing_count.toLocaleString() ?? "0"}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {formatNumber(stats?.information_value, 4)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-violet-700">
                            {stats?.special_value_count.toLocaleString() ?? "0"}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {stats?.distinct_count.toLocaleString() ?? "0"}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {formatNumber(stats?.mean)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {formatNumber(stats?.standard_deviation)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {formatNumber(stats?.minimum)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {formatNumber(stats?.first_quartile)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {formatNumber(stats?.median)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {formatNumber(stats?.third_quartile)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {formatNumber(stats?.maximum)}
                          </td>
                          <td className="px-3 py-2">
                            {selected.strategy === "Constant" ? (
                              overridden ? (
                                <input
                                  className="atlas-input min-w-36"
                                  value={selected.constantValue ?? ""}
                                  onChange={(event) =>
                                    updateConstant(
                                      column.name,
                                      event.target.value,
                                    )
                                  }
                                  placeholder="Required constant"
                                />
                              ) : (
                                <span className="text-slate-600">
                                  {globalConstant || "Global value required"}
                                </span>
                              )
                            ) : (
                              <span className="text-slate-400">
                                Not applicable
                              </span>
                            )}
                          </td>
                          <td
                            className="px-3 py-2 font-semibold text-slate-700"
                            data-testid={`missing-projection-${column.name}`}
                          >
                            {projectedTreatmentState(
                              stats,
                              selected.strategy,
                              summary.rows,
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-slate-500">
                Showing {rows.length.toLocaleString()} of{" "}
                {summary.columns.length.toLocaleString()} authorized predictors
                in one vertically scrollable table. Bureau specials never
                contribute to the true-null column.
              </p>
            </AtlasWorkflowSection>

            <AtlasWorkflowSection
              eyebrow="Treatment impact"
              title="Missingness and Imputation Map"
              description="Compare each feature's true-null count and rate with the value or row action produced by the current treatment. The readout changes immediately when the global method or a feature override changes."
              tone="neutral"
              id="missing-treatment-impact"
              action={
                <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700">
                  {impactColumns.length} shown
                </span>
              }
            >
              <div className="mb-4 flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                  Ranked display
                  <select
                    className="atlas-input min-w-44"
                    value={impactLimit}
                    onChange={(event) =>
                      setImpactLimit(Number(event.target.value))
                    }
                    data-testid="missing-impact-count"
                  >
                    <option value={10}>Top 10 by IV</option>
                    <option value={20}>Top 20 by IV</option>
                    <option value={summary.columns.length}>
                      All predictors
                    </option>
                  </select>
                </label>
                <details className="relative">
                  <summary className="atlas-secondary-button cursor-pointer list-none">
                    Select additional predictors
                  </summary>
                  <div className="absolute left-0 top-10 z-30 max-h-72 min-w-72 overflow-auto rounded-lg border border-slate-200 bg-white p-2 shadow-xl">
                    {ivRankedColumns.map((column, index) => (
                      <label
                        key={column.name}
                        className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-slate-50"
                      >
                        <input
                          type="checkbox"
                          checked={
                            index < impactLimit ||
                            additionalImpactFeatures.has(column.name)
                          }
                          disabled={index < impactLimit}
                          onChange={(event) =>
                            setAdditionalImpactFeatures((current) => {
                              const next = new Set(current);
                              if (event.target.checked) {
                                next.add(column.name);
                              } else {
                                next.delete(column.name);
                              }
                              return next;
                            })
                          }
                        />
                        <span className="flex-1">{column.name}</span>
                        <span className="tabular-nums text-slate-500">
                          IV{" "}
                          {formatNumber(
                            summary.stats[column.name]?.information_value,
                            4,
                          )}
                        </span>
                      </label>
                    ))}
                  </div>
                </details>
                {summary.problem_type === "regression" ? (
                  <span className="text-xs text-amber-700">
                    IV is not applicable for regression; unavailable rows use
                    stable feature-name ordering.
                  </span>
                ) : null}
              </div>
              <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
                <div className="hidden grid-cols-[minmax(220px,1.2fr)_150px_36px_minmax(230px,1fr)_170px] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-2 text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500 lg:grid">
                  <span>Predictor</span>
                  <span>Missing burden</span>
                  <span aria-hidden="true" />
                  <span>Selected treatment</span>
                  <span>Projected result</span>
                </div>
                {impactColumns.map((column, index) => (
                  <MissingnessTreatmentRow
                    key={column.name}
                    rank={index + 1}
                    column={column}
                    stats={summary.stats[column.name]}
                    strategy={
                      config[column.name]?.strategy ?? ("None" as const)
                    }
                    constantValue={config[column.name]?.constantValue}
                    rowCount={summary.rows}
                  />
                ))}
              </div>
            </AtlasWorkflowSection>

            {totalMissing > 0 && selectedTreatmentCount > 0 ? (
              <AtlasWorkflowSection
                eyebrow="Preview only"
                title="Treatment Impact Preview"
                description="Selected treatment only. Expected fill and row-loss impact from full-data null counts; preview does not materialize a backend frame."
                tone="warning"
                id="missing-impact-preview"
              >
                <MissingImpactPreview
                  columns={summary.columns}
                  stats={summary.stats}
                  config={config}
                  rowCount={summary.rows}
                />
              </AtlasWorkflowSection>
            ) : null}

            {totalMissing > 0 ? (
              <details className="atlas-workflow-section">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
                  <span>
                    <span className="block text-sm font-semibold text-slate-950">
                      Missingness Mechanism Review
                    </span>
                    <span className="mt-1 block text-xs text-slate-600">
                      Conservative diagnostic prompts; ATLAS does not claim
                      MCAR, MAR, or MNAR from this profile alone.
                    </span>
                  </span>
                  <ChevronDown size={17} />
                </summary>
                <div className="mt-4 grid gap-3 border-t border-slate-200 pt-4 md:grid-cols-3">
                  <MechanismCard
                    title="Observed association"
                    detail={`${informativeCount} predictors have a material target difference when missing. This is evidence for review, not proof of a mechanism.`}
                  />
                  <MechanismCard
                    title="Process knowledge"
                    detail="Confirm whether collection rules, application paths, or bureau reporting explain null occurrence."
                  />
                  <MechanismCard
                    title="Validation requirement"
                    detail="Compare treatment choices on held-out data and preserve missingness indicators when they have defensible operational meaning."
                  />
                </div>
              </details>
            ) : null}

            <AtlasWorkflowSection
              eyebrow="Explicit decision"
              title={
                totalMissing === 0
                  ? "Validate No Treatment Required"
                  : "Apply Governed Missing-Value Treatment"
              }
              description={
                totalMissing === 0
                  ? "Records a confirmed no-treatment decision. It does not call the materialization endpoint."
                  : "Runs the selected strategies once against the full backend population after validation."
              }
              tone={totalMissing === 0 ? "success" : "info"}
              id="missing-apply-decision"
            >
              <div className="flex flex-wrap items-center gap-3">
                <AtlasExecutionStatus
                  state={
                    applying
                      ? "running"
                      : validationFailed
                        ? "failed"
                        : applied
                          ? "complete"
                          : "idle"
                  }
                  label={
                    applying
                      ? totalMissing
                        ? "Applying"
                        : "Validating"
                      : validationFailed
                        ? "Failed"
                        : applied
                          ? totalMissing
                            ? "Applied"
                            : "Validated, no treatment required"
                          : totalMissing
                            ? "Selected, not applied"
                            : "Ready to validate"
                  }
                  detail={
                    totalMissing === 0
                      ? "Backend materialization: no"
                      : summary.application?.applied_at
                        ? `Last backend success ${new Date(summary.application.applied_at).toLocaleString()}`
                        : `${selectedTreatmentCount} feature treatment decisions selected`
                  }
                />
                <button
                  type="button"
                  className="atlas-primary-button"
                  onClick={() =>
                    void (totalMissing === 0
                      ? validateNoTreatment()
                      : applyTreatments())
                  }
                  disabled={applying || applied}
                >
                  {applying ? (
                    <LoaderCircle size={15} className="animate-spin" />
                  ) : applied ? (
                    <CheckCircle2 size={15} />
                  ) : (
                    <Play size={15} />
                  )}
                  {applied
                    ? totalMissing
                      ? "Current treatment applied"
                      : "Validation current"
                    : totalMissing
                      ? "Apply treatments"
                      : "Validate no treatment"}
                </button>
                <span className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-800">
                  <Info size={13} />
                  {totalMissing === 0
                    ? "No processed frame will be created"
                    : "Full backend dataset"}
                </span>
              </div>
            </AtlasWorkflowSection>

            {message ? (
              <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
                {message}
              </div>
            ) : null}

            <details
              className="hidden"
              data-testid="missing-values-inventory"
              aria-hidden="true"
            >
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
                <span>
                  <span className="block text-sm font-semibold text-slate-950">
                    Complete Predictor Inventory
                  </span>
                  <span className="mt-1 block text-xs text-slate-600">
                    Expand for searchable full-data counts, target comparison,
                    special-value prevalence, and feature overrides.
                  </span>
                </span>
                <ChevronDown size={17} />
              </summary>
              <div className="mt-4 border-t border-slate-200 pt-4">
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
                    />
                  </label>
                  <label className="flex items-center gap-2 text-xs font-semibold text-slate-600">
                    <Filter size={15} />
                    <select
                      className="atlas-input min-w-40"
                      value={sortBy}
                      onChange={(event) => {
                        setSortBy(event.target.value as typeof sortBy);
                        setPage(0);
                      }}
                    >
                      <option value="missing">Missing rate</option>
                      <option value="special">Special values</option>
                      <option value="informative">Informative flags</option>
                      <option value="name">Feature name</option>
                    </select>
                  </label>
                </div>
                <div className="overflow-x-auto rounded-lg border border-slate-200">
                  <table className="min-w-[1080px] w-full text-xs">
                    <thead className="bg-slate-50 text-left uppercase tracking-wide text-slate-500">
                      <tr>
                        <th className="px-3 py-2">Predictor</th>
                        <th className="px-3 py-2">Type</th>
                        <th className="px-3 py-2">True nulls</th>
                        <th className="px-3 py-2">Null rate</th>
                        <th className="px-3 py-2">Special values</th>
                        <th className="px-3 py-2">Target difference</th>
                        <th className="px-3 py-2">Strategy</th>
                        <th className="px-3 py-2">Parameter</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pagedRows.map((column) => {
                        const stats = summary.stats[column.name];
                        const selected = config[column.name] ?? {
                          strategy: "None" as MissingStrategy,
                        };
                        return (
                          <tr
                            key={column.name}
                            className={
                              stats?.informative
                                ? "border-t border-slate-100 bg-amber-50"
                                : "border-t border-slate-100 hover:bg-slate-50"
                            }
                          >
                            <td className="px-3 py-2 font-semibold text-slate-900">
                              {column.name}
                            </td>
                            <td className="px-3 py-2 text-slate-600">
                              {isNumeric(column) ? "Numeric" : "Categorical"}
                            </td>
                            <td className="px-3 py-2 tabular-nums">
                              {stats?.missing.toLocaleString() ?? "0"}
                            </td>
                            <td className="px-3 py-2 tabular-nums">
                              {pct(stats?.missingPct, true)}
                            </td>
                            <td className="px-3 py-2 tabular-nums">
                              {stats?.special_value_count.toLocaleString() ??
                                "0"}
                            </td>
                            <td
                              className={`px-3 py-2 tabular-nums ${
                                stats?.informative
                                  ? "font-semibold text-amber-800"
                                  : "text-slate-600"
                              }`}
                            >
                              {stats?.difference == null
                                ? "Not evaluated"
                                : summary.problem_type === "classification"
                                  ? `${stats.difference >= 0 ? "+" : ""}${pct(stats.difference)}`
                                  : stats.difference.toFixed(4)}
                              {stats?.informative ? " · review" : ""}
                            </td>
                            <td className="px-3 py-2">
                              <select
                                className="atlas-input min-w-36"
                                value={selected.strategy}
                                onChange={(event) =>
                                  updateStrategy(
                                    column.name,
                                    event.target.value as MissingStrategy,
                                  )
                                }
                              >
                                {strategyOptions(column).map((strategy) => (
                                  <option key={strategy}>{strategy}</option>
                                ))}
                              </select>
                            </td>
                            <td className="px-3 py-2">
                              {selected.strategy === "Constant" ? (
                                <input
                                  className="atlas-input min-w-40"
                                  value={selected.constantValue ?? ""}
                                  onChange={(event) =>
                                    updateConstant(
                                      column.name,
                                      event.target.value,
                                    )
                                  }
                                  placeholder="Required constant"
                                />
                              ) : (
                                <span className="text-slate-400">
                                  Not applicable
                                </span>
                              )}
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
              </div>
            </details>
          </>
        ) : null}
      </div>
    </StepShell>
  );
}

function formatNumber(
  value: number | null | undefined,
  digits = 2,
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "N/A";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function projectedImputationValue(
  stats: MissingStats | undefined,
  strategy: MissingStrategy,
  constantValue?: string,
) {
  if (strategy === "None") return "No imputation";
  if (strategy === "Drop Row") return "Row removed";
  if (strategy === "Constant") {
    return String(constantValue ?? "").trim() || "Value required";
  }
  if (strategy === "Mean") return formatNumber(stats?.mean);
  if (strategy === "Median") return formatNumber(stats?.median);
  const mode = stats?.mode;
  if (mode === null || mode === undefined || mode === "") return "Unavailable";
  return typeof mode === "number" ? formatNumber(mode) : String(mode);
}

function projectedTreatmentState(
  stats: MissingStats | undefined,
  strategy: MissingStrategy,
  rowCount: number,
) {
  const missing = stats?.missing ?? 0;
  if (missing === 0) return "0 nulls · planning only";
  if (strategy === "None") {
    return `${missing.toLocaleString()} null${missing === 1 ? "" : "s"} preserved`;
  }
  if (strategy === "Drop Row") {
    return `${Math.max(0, rowCount - missing).toLocaleString()} rows retained`;
  }
  return `0 nulls projected · ${missing.toLocaleString()} filled`;
}

function MissingnessTreatmentRow({
  rank,
  column,
  stats,
  strategy,
  constantValue,
  rowCount,
}: {
  rank: number;
  column: ColumnInfo;
  stats: MissingStats | undefined;
  strategy: MissingStrategy;
  constantValue?: string;
  rowCount: number;
}) {
  const missingCount = stats?.missing ?? 0;
  const missingRate = Math.max(0, Math.min(100, stats?.missingPct ?? 0));
  const imputedValue = projectedImputationValue(
    stats,
    strategy,
    constantValue,
  );
  return (
    <article
      className="grid gap-3 border-t border-slate-100 px-4 py-3 first:border-t-0 lg:grid-cols-[minmax(220px,1.2fr)_150px_36px_minmax(230px,1fr)_170px] lg:items-center"
      data-testid={`missing-impact-${column.name}`}
    >
      <div className="min-w-0">
        <span className="text-[10px] font-bold uppercase tracking-wide text-slate-400">
          IV rank {rank}
        </span>
        <h3 className="truncate text-sm font-semibold text-slate-950">
          {column.name}
        </h3>
        <span className="text-[11px] text-slate-500">
          {column.dtype} · IV {formatNumber(stats?.information_value, 4)}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <div className="relative h-12 w-12 shrink-0">
          <svg
            className="-rotate-90"
            viewBox="0 0 44 44"
            role="img"
            aria-label={`${formatNumber(missingRate, 2)} percent missing`}
          >
            <circle
              cx="22"
              cy="22"
              r="18"
              pathLength="100"
              fill="none"
              stroke="#e2e8f0"
              strokeWidth="5"
            />
            <circle
              cx="22"
              cy="22"
              r="18"
              pathLength="100"
              fill="none"
              stroke="#f59e0b"
              strokeWidth="5"
              strokeLinecap="round"
              strokeDasharray={`${missingRate} ${100 - missingRate}`}
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-[9px] font-bold tabular-nums text-amber-900">
            {formatNumber(missingRate, missingRate < 1 ? 2 : 1)}%
          </span>
        </div>
        <div>
          <strong className="block text-sm tabular-nums text-slate-950">
            {missingCount.toLocaleString()}
          </strong>
          <span className="text-[11px] text-slate-500">true nulls</span>
        </div>
      </div>
      <div
        className="hidden text-center text-lg font-semibold text-blue-500 lg:block"
        aria-hidden="true"
      >
        →
      </div>
      <div>
        <span className="inline-flex rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-blue-800">
          {strategy}
        </span>
        <div className="mt-1 text-sm font-bold text-slate-950">
          {strategy === "Drop Row" ? "Action" : "Imputed value"}:{" "}
          <span
            className="text-blue-800"
            data-testid={`missing-impact-value-${column.name}`}
          >
            {imputedValue}
          </span>
        </div>
      </div>
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold leading-5 text-slate-700">
        {projectedTreatmentState(stats, strategy, rowCount)}
      </div>
    </article>
  );
}

function MissingDistributionHistogram({
  rank,
  column,
  stats,
  strategy,
  rowCount,
}: {
  rank: number;
  column: ColumnInfo;
  stats: MissingStats | undefined;
  strategy: MissingStrategy;
  rowCount: number;
}) {
  const distribution = stats?.distribution;
  const bins = distribution?.bins ?? [];
  const maximum = Math.max(1, ...bins.map((bin) => bin.count));
  const cutoffs = distribution?.reference_cutoffs;
  const domainLow =
    bins.length && typeof bins[0].lower === "number" ? bins[0].lower : null;
  const domainHigh =
    bins.length && typeof bins[bins.length - 1].upper === "number"
      ? bins[bins.length - 1].upper
      : null;
  const markerPosition = (value: number) => {
    if (
      domainLow === null ||
      domainHigh === null ||
      domainHigh <= domainLow
    ) {
      return null;
    }
    return Math.max(
      0,
      Math.min(100, ((value - domainLow) / (domainHigh - domainLow)) * 100),
    );
  };
  const lowerMarker =
    cutoffs && markerPosition(cutoffs.lower) !== null
      ? markerPosition(cutoffs.lower)
      : null;
  const upperMarker =
    cutoffs && markerPosition(cutoffs.upper) !== null
      ? markerPosition(cutoffs.upper)
      : null;

  return (
    <article
      className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm"
      data-testid={`missing-histogram-${column.name}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
            IV rank {rank}
          </p>
          <h3 className="mt-0.5 text-sm font-semibold text-slate-950">
            {column.name}
          </h3>
        </div>
        <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-800">
          IV {formatNumber(stats?.information_value, 4)}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-2">
          <span className="block text-slate-500">Ordinary observed</span>
          <strong className="tabular-nums text-slate-950">
            {(distribution?.observed_count ?? 0).toLocaleString()}
          </strong>
        </div>
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-2 py-2">
          <span className="block text-amber-700">True nulls</span>
          <strong className="tabular-nums text-amber-950">
            {(distribution?.missing_count ?? 0).toLocaleString()}
          </strong>
        </div>
        <div className="rounded-lg border border-violet-200 bg-violet-50 px-2 py-2">
          <span className="block text-violet-700">Bureau specials</span>
          <strong className="tabular-nums text-violet-950">
            {(distribution?.special_value_count ?? 0).toLocaleString()}
          </strong>
        </div>
      </div>

      <div className="relative mt-3 h-28 rounded-lg border border-slate-200 bg-gradient-to-b from-slate-50 to-white px-2 pb-6 pt-3">
        {bins.length ? (
          <div className="flex h-full items-end gap-1" role="img" aria-label={`${column.name} ordinary-value histogram`}>
            {bins.map((bin, index) => (
              <div
                key={`${bin.label}-${index}`}
                className="group relative flex h-full min-w-0 flex-1 items-end"
                title={`${bin.label}: ${bin.count.toLocaleString()} ordinary observations`}
              >
                <div
                  className="w-full rounded-t bg-gradient-to-t from-blue-700 to-cyan-400 transition-colors group-hover:from-blue-800 group-hover:to-cyan-500"
                  style={{
                    height: `${Math.max(3, (bin.count / maximum) * 100)}%`,
                  }}
                />
              </div>
            ))}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-slate-500">
            No ordinary observed distribution is available.
          </div>
        )}
        {lowerMarker !== null ? (
          <div
            className="absolute bottom-5 top-2 border-l-2 border-dashed border-rose-500"
            style={{ left: `${lowerMarker}%` }}
            title={`Lower ordinary-value reference ${formatNumber(cutoffs?.lower)}`}
            data-testid={`missing-lower-cutoff-${column.name}`}
          />
        ) : null}
        {upperMarker !== null ? (
          <div
            className="absolute bottom-5 top-2 border-l-2 border-dashed border-rose-500"
            style={{ left: `${upperMarker}%` }}
            title={`Upper ordinary-value reference ${formatNumber(cutoffs?.upper)}`}
            data-testid={`missing-upper-cutoff-${column.name}`}
          />
        ) : null}
        <div className="absolute inset-x-2 bottom-1 flex justify-between text-[9px] text-slate-500">
          <span>{bins[0]?.label ?? "No observed bins"}</span>
          <span>{bins[bins.length - 1]?.label ?? ""}</span>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
        <div>
          {cutoffs ? (
            <span className="font-semibold text-rose-700">
              Upstream 1.5-IQR reference: {formatNumber(cutoffs.lower)} to{" "}
              {formatNumber(cutoffs.upper)}
            </span>
          ) : (
            <span className="font-semibold text-slate-600">
              Low/high cutoffs: not applicable
            </span>
          )}
          <p className="mt-0.5 text-[11px] leading-4 text-slate-500">
            {distribution?.cutoff_semantics ??
              "Distribution evidence is unavailable."}
          </p>
        </div>
        <span className="rounded-full border border-blue-200 bg-blue-50 px-2 py-1 font-semibold text-blue-800">
          {strategy}: {projectedTreatmentState(stats, strategy, rowCount)}
        </span>
      </div>
    </article>
  );
}

function MissingnessProfile({
  columns,
  stats,
}: {
  columns: ColumnInfo[];
  stats: Record<string, MissingStats>;
}) {
  const ranked = [...columns]
    .sort(
      (a, b) =>
        (stats[b.name]?.missingPct ?? 0) - (stats[a.name]?.missingPct ?? 0),
    )
    .slice(0, 18);
  const max = Math.max(0.01, ...ranked.map((row) => stats[row.name]?.missingPct ?? 0));
  return (
    <div
      className="prep-chart-panel"
      data-testid="missingness-profile-chart"
    >
      <div className="space-y-1">
        {ranked.map((column) => {
          const row = stats[column.name];
          const rate = row?.missingPct ?? 0;
          return (
            <div
              key={column.name}
              className="grid grid-cols-[minmax(180px,1fr)_minmax(220px,2fr)_74px] items-center gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-slate-50"
              title={`${column.name}: ${row?.missing.toLocaleString() ?? 0} true nulls (${pct(rate, true)})`}
            >
              <span className="truncate font-semibold text-slate-900">
                {column.name}
              </span>
              <span className="relative h-4 overflow-hidden rounded-full bg-slate-100">
                <span
                  className={rate ? "absolute inset-y-0 left-0 rounded-full bg-amber-500" : "absolute inset-y-0 left-0 rounded-full bg-emerald-400"}
                  style={{
                    width: `${rate ? Math.max(2, (rate / max) * 100) : 1.5}%`,
                  }}
                />
              </span>
              <span className="text-right tabular-nums text-slate-700">
                {pct(rate, true)}
              </span>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-[11px] text-slate-500">
        Ranked by true-null rate. Zero-length green markers indicate validated
        absence, not missing chart data.
      </p>
    </div>
  );
}

function MissingSpecialStack({
  columns,
  stats,
}: {
  columns: ColumnInfo[];
  stats: Record<string, MissingStats>;
}) {
  const rows = [...columns]
    .sort(
      (a, b) =>
        (stats[b.name]?.special_value_rate ?? 0) -
          (stats[a.name]?.special_value_rate ?? 0) ||
        (stats[b.name]?.missingPct ?? 0) - (stats[a.name]?.missingPct ?? 0),
    )
    .slice(0, 18);
  return (
    <div
      className="prep-chart-panel"
      data-testid="missing-special-stacked-profile"
    >
      <div className="mb-3 flex flex-wrap gap-3 text-[11px] font-semibold text-slate-600">
        <span className="inline-flex items-center gap-1">
          <i className="h-2.5 w-2.5 rounded-sm bg-amber-500" /> True null
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="h-2.5 w-2.5 rounded-sm bg-violet-500" /> Bureau special
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="h-2.5 w-2.5 rounded-sm bg-slate-200" /> Ordinary observed
        </span>
      </div>
      <div className="space-y-1.5">
        {rows.map((column) => {
          const row = stats[column.name];
          const missingRate = (row?.missingPct ?? 0) / 100;
          const specialRate = row?.special_value_rate ?? 0;
          const observedRate = Math.max(0, 1 - missingRate - specialRate);
          return (
            <div
              key={column.name}
              className="grid grid-cols-[minmax(180px,1fr)_minmax(260px,2fr)_150px] items-center gap-2 text-xs"
            >
              <span className="truncate font-semibold text-slate-900">
                {column.name}
              </span>
              <span className="flex h-4 overflow-hidden rounded-full bg-slate-100">
                <span
                  className="bg-amber-500"
                  style={{ width: `${missingRate * 100}%` }}
                  title={`True null ${pct(missingRate)}`}
                />
                <span
                  className="bg-violet-500"
                  style={{ width: `${specialRate * 100}%` }}
                  title={`Bureau special ${pct(specialRate)}`}
                />
                <span
                  className="bg-slate-200"
                  style={{ width: `${observedRate * 100}%` }}
                  title={`Ordinary observed ${pct(observedRate)}`}
                />
              </span>
              <span className="text-right text-[10px] tabular-nums text-slate-600">
                {row?.missing.toLocaleString() ?? 0} null ·{" "}
                {row?.special_value_count.toLocaleString() ?? 0} special
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MissingImpactPreview({
  columns,
  stats,
  config,
  rowCount,
}: {
  columns: ColumnInfo[];
  stats: Record<string, MissingStats>;
  config: MissingConfig;
  rowCount: number;
}) {
  const selected = columns
    .map((column) => ({
      column,
      strategy: config[column.name]?.strategy ?? "None",
      missing: stats[column.name]?.missing ?? 0,
    }))
    .filter((row) => row.strategy !== "None" && row.missing > 0);
  const cellsFilled = selected
    .filter((row) => row.strategy !== "Drop Row")
    .reduce((sum, row) => sum + row.missing, 0);
  const maximumRowsRemoved = Math.min(
    rowCount,
    selected
      .filter((row) => row.strategy === "Drop Row")
      .reduce((sum, row) => sum + row.missing, 0),
  );
  return (
    <div data-testid="missing-impact-preview">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <ImpactMetric
          label="Selected predictors"
          value={selected.length.toLocaleString()}
        />
        <ImpactMetric label="Cells filled" value={cellsFilled.toLocaleString()} />
        <ImpactMetric
          label="Maximum row loss"
          value={maximumRowsRemoved.toLocaleString()}
          warning={maximumRowsRemoved > 0}
        />
        <ImpactMetric
          label="Minimum retained rows"
          value={Math.max(0, rowCount - maximumRowsRemoved).toLocaleString()}
          warning={maximumRowsRemoved / Math.max(rowCount, 1) >= 0.05}
        />
      </div>
      <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-[620px] w-full text-xs">
          <thead className="bg-slate-50 text-left uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">Predictor</th>
              <th className="px-3 py-2">Strategy</th>
              <th className="px-3 py-2">True nulls affected</th>
              <th className="px-3 py-2">Special values affected</th>
            </tr>
          </thead>
          <tbody>
            {selected.map((row) => (
              <tr key={row.column.name} className="border-t border-slate-100">
                <td className="px-3 py-2 font-semibold">{row.column.name}</td>
                <td className="px-3 py-2">{row.strategy}</td>
                <td className="px-3 py-2 tabular-nums">
                  {row.missing.toLocaleString()}
                </td>
                <td className="px-3 py-2 font-semibold text-emerald-700">
                  0 — preserved separately
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-slate-500">
        Row-loss count is a conservative upper bound because the same row may
        be missing in more than one selected predictor. Backend results remain
        authoritative after apply.
      </p>
    </div>
  );
}

function ImpactMetric({
  label,
  value,
  warning = false,
}: {
  label: string;
  value: string;
  warning?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border px-3 py-2 ${
        warning
          ? "border-amber-200 bg-amber-50"
          : "border-slate-200 bg-slate-50"
      }`}
    >
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-1 text-sm font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function MechanismCard({
  title,
  detail,
}: {
  title: string;
  detail: string;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="text-xs font-semibold text-slate-950">{title}</div>
      <p className="mt-1 text-xs leading-5 text-slate-600">{detail}</p>
    </div>
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

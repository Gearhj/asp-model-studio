import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getJSON, postJSON } from "../../lib/api";
import {
  compactProjectEdaFilters,
  type ProjectEdaAuthority,
  type ProjectEdaFilters,
  type ProjectEdaPopulation,
} from "./projectEdaApi";

export type TreatmentKind = "outliers" | "missing";
export type QueryStatus = "idle" | "loading" | "ready" | "error";

export type OutlierDetectionMethod =
  | "NO_STATISTICAL_DETECTION"
  | "IQR_1_5"
  | "IQR_3_0"
  | "P95_UPPER"
  | "P99_UPPER"
  | "P05_P95"
  | "P01_P99"
  | "DOMAIN_BOUNDS";
export type OutlierTreatmentMethod =
  | "RETAIN"
  | "FLAG_ONLY"
  | "CAP_IQR"
  | "WINSORIZE"
  | "CAP_P95"
  | "CAP_P99"
  | "SET_MISSING"
  | "EXCLUDE_ROW";
export type ImputationMethod =
  | "RETAIN_WITH_INDICATOR"
  | "MEAN"
  | "MEDIAN"
  | "MODE"
  | "CONSTANT"
  | "GOVERNED_PRIOR"
  | "PREDICTED"
  | "UNKNOWN_CATEGORY"
  | "DROP_VARIABLE"
  | "EXCLUDE_ROW";

export type TreatmentAudit = {
  finalOotTargetAccessed: false;
  finalOotUsedForSelection: false;
  legacyGlobalMatrixUsed: false;
  providerCalls: 0;
  sourceOrGoldMutated?: false;
  modelActivity: {
    fits: number;
    scores: number;
    tunes: number;
    calibrations: number;
    selections: number;
    promotions: number;
  };
};

export type TreatmentEnvelope<T> = {
  ok: true;
  authority: ProjectEdaAuthority;
  population: ProjectEdaPopulation;
  audit: TreatmentAudit;
  cacheStatus?: string;
  queryDurationMs?: number;
  data: T;
};

export type TreatmentSpecificationFeature = Record<string, unknown> & {
  featureName?: string;
  feature?: string;
  canonicalDisposition?: string;
  disposition?: string;
  executionStatus?: string;
};

export type TreatmentAdditionalBackendFeature = Record<string, unknown> & {
  featureName: string;
  proposedDisposition: string;
  executableStatus: string;
  executableSelectable: boolean;
  blockedReason: string;
};

export type TreatmentSpecificationData = {
  specification: {
    specificationId: string;
    sourceWorkbookFilename: string;
    sourceWorkbookSha256: string;
    manifestChecksum: string;
    compilerVersion: string;
  };
  reconciliation: {
    workbookFeatureCount: number;
    backendFeatureCount: number;
    exactMatchCount: number;
    unmatchedWorkbookFeatures: string[];
    additionalBackendFeatures: TreatmentAdditionalBackendFeature[];
    status: string;
  };
  dispositionCounts: Record<string, number>;
  executionSummary: Record<string, unknown>;
  exceptions: Array<Record<string, unknown>>;
  features: TreatmentSpecificationFeature[];
  priorPolicies: {
    outlier: Record<string, unknown> | null;
    missing: Record<string, unknown> | null;
  };
  draft: {
    specificationDraftId: string;
    version: number;
    status: "DRAFT";
    outlierPolicyRef: Record<string, unknown> | string;
    missingPolicyRef: Record<string, unknown> | string;
    manifestChecksum: string;
  } | null;
  status: "AVAILABLE" | "DRAFT_CURRENT" | "DRAFT_STALE" | "BLOCKED";
  canCreateDraft: boolean;
  canAdopt: boolean;
  blockers: string[];
};

export function hasCurrentTreatmentSpecificationDraft(
  data: TreatmentSpecificationData | null | undefined,
): boolean {
  return Boolean(
    data?.status === "DRAFT_CURRENT" &&
      data.draft?.status === "DRAFT" &&
      data.draft.manifestChecksum === data.specification.manifestChecksum,
  );
}

export type TreatmentPolicyVersion = {
  policyId?: string | null;
  policyVersion: number;
  status: "DRAFT" | "ADOPTED" | "SUPERSEDED";
  createdAt: string;
  adoptedAt?: string | null;
  user: string;
  checksum: string;
  notes: string;
  globalMethod: string;
  globalTreatment?: string | null;
  variableCount: number;
};

export type TreatmentPolicy<TOverride = Record<string, unknown>> = {
  policyId?: string | null;
  kind: TreatmentKind;
  status: "NO_TREATMENT_ADOPTED" | "DRAFT" | "ADOPTED";
  policyVersion: number | null;
  checksum: string | null;
  globalMethod: string;
  globalTreatment?: string | null;
  overrides: Record<string, TOverride>;
  notes: string;
  versions: TreatmentPolicyVersion[];
  fittingRule: string;
  developmentCutoff: string;
  finalOotIdentity: string;
  coldStartDefault?: string;
  governedPriorAvailable?: boolean;
  governedPriorEligibleVariables?: string[];
};

export type TreatmentFilters = ProjectEdaFilters & {
  families?: string[];
  coreScope?: "CORE" | "CONTEXTUAL" | "";
  dataTypes?: string[];
  severity?: string;
  includeAdvanced?: boolean;
};

export type HistogramBin = {
  binStart: number;
  binEnd: number;
  count: number;
  percent?: number;
  imputedCount?: number;
  affected?: boolean;
};
export type CategoryBin = {
  value: string;
  count: number;
  percent?: number;
  imputedCount?: number;
};
export type DistributionPreview = {
  kind: "CONTINUOUS" | "LOW_CARDINALITY" | "BINARY" | "CATEGORICAL";
  histogram?: HistogramBin[];
  categories?: CategoryBin[];
  density?: { value: number; density: number }[];
  ecdf?: { value: number; cumulativePercent: number }[];
  box?: {
    min: number | null;
    q1: number | null;
    median: number | null;
    q3: number | null;
    max: number | null;
  };
  missingCount: number;
  observedCount: number;
};

export type OutlierOverride = {
  detectionMethod: OutlierDetectionMethod;
  treatment: OutlierTreatmentMethod;
  winsorLowerPercentile?: number;
  winsorUpperPercentile?: number;
  customLowerThreshold?: number | null;
  customUpperThreshold?: number | null;
  included?: boolean;
  notes?: string;
};

export type OutlierSummary = {
  status: "NOT_EVALUATED" | "ANALYZED" | "NO_OUTLIERS";
  eligibleVariables: number | null;
  variablesWithOutliers: number | null;
  totalAffectedRows: number | null;
  affectedGames: number | null;
  affectedBatters: number | null;
  affectedPitchers: number | null;
  activeDetectionMethod: OutlierDetectionMethod | null;
  activeTreatment: OutlierTreatmentMethod | null;
  highestAffectedVariable: string | null;
  highestAffectedCount: number | null;
  highestAffectedPercent: number | null;
  policy: TreatmentPolicy<OutlierOverride>;
};

export type OutlierTableRow = {
  variable: string;
  numberOfOutliers: number | null;
  outlierPercent: number | null;
  lowerTailCount: number | null;
  upperTailCount: number | null;
  dataType: string;
  featureFamily: string;
  core: boolean;
  selectable: boolean;
  eligible: boolean;
  active: boolean;
  developmentNonmissingN: number | null;
  missingN: number | null;
  lowerThreshold: number | null;
  upperThreshold: number | null;
  min: number | null;
  q1: number | null;
  median: number | null;
  q3: number | null;
  max: number | null;
  mean: number | null;
  standardDeviation: number | null;
  selectedDetectionMethod: OutlierDetectionMethod | null;
  selectedTreatment: OutlierTreatmentMethod | null;
  treatmentValueOrBounds: string;
  affectedGames: number | null;
  affectedPlayers: number | null;
  status: string;
  override: boolean;
  eligibleDetectionMethods: OutlierDetectionMethod[];
  eligibleTreatments: OutlierTreatmentMethod[];
  exclusionReason?: string | null;
};

export type OutlierDetail = {
  variable: string;
  dataType: string;
  featureFamily: string;
  detectionMethod: OutlierDetectionMethod;
  treatment: OutlierTreatmentMethod;
  previewLabel: string;
  thresholds: {
    lower: number | null;
    upper: number | null;
    formula: string;
    fittingRule: string;
  };
  before: DistributionPreview;
  after: DistributionPreview;
  sharedAxis: {
    minimum: number | null;
    maximum: number | null;
    binEdges: number[];
  };
  effect: {
    originalCount: number;
    postTreatmentCount: number;
    changedRows: number;
    unchangedRows: number;
    cappedLow: number;
    cappedHigh: number;
    excluded: number;
    setMissing: number;
    original: {
      min: number | null;
      max: number | null;
      mean: number | null;
      median: number | null;
      std: number | null;
    };
    transformed: {
      min: number | null;
      max: number | null;
      mean: number | null;
      median: number | null;
      std: number | null;
    };
    affectedGames: number | null;
    affectedBatters: number | null;
    affectedPitchers: number | null;
    populationLossPercent: number;
    targetCompositionBefore: {
      value: string;
      count: number;
      percent: number;
    }[];
    targetCompositionAfter: { value: string; count: number; percent: number }[];
    formula: string;
  };
};

export type MissingOverride = {
  method: ImputationMethod;
  constantValue?: string | number | null;
  retainIndicator?: boolean;
  coldStartMethod?: string;
  sourceFailureMethod?: string;
  predictorSet?: string[];
  seed?: number;
  notes?: string;
};

export type MissingSummary = {
  status: "NOT_EVALUATED" | "ANALYZED" | "NO_MISSING_VALUES";
  eligiblePredictors: number | null;
  predictorsWithPhysicalMissing: number | null;
  rowsWithPhysicalMissing: number | null;
  macroPredictorCellMissingPercent: number | null;
  largestMissingPercent: number | null;
  largestMissingVariable: string | null;
  coldStartRows: number | null;
  sourceUnavailableRows: number | null;
  computationFailureRows: number | null;
  missingnessIndicatorCount: number | null;
  activeGlobalMethod: string | null;
  policy: TreatmentPolicy<MissingOverride>;
};

export type MissingTableRow = {
  variable: string;
  numberOfMissingValues: number | null;
  missingPercent: number | null;
  developmentN: number | null;
  observedN: number | null;
  dataType: string;
  featureFamily: string;
  core: boolean;
  selectable: boolean;
  eligible: boolean;
  primaryReason: string;
  noPriorHistoryCount: number | null;
  insufficientHistoryCount: number | null;
  sourceUnavailableCount: number | null;
  computationFailureCount: number | null;
  pairedMissingnessIndicator: string | null;
  governedPriorAvailable: boolean;
  governedPriorUnavailableReason: string | null;
  selectedImputationMethod: ImputationMethod | null;
  imputedValueOrPolicy: string;
  descriptivePreviewValue?: string | number | null;
  descriptivePreviewOnly?: boolean;
  previewLabel?: string;
  eligibleMethods: ImputationMethod[];
  ineligibleMethodReasons?: Record<string, string>;
  affectedGames: number | null;
  affectedBatters: number | null;
  affectedPitchers: number | null;
  status: string;
  exclusionReason?: string | null;
  override: boolean;
};

export type PredictedPreview = {
  status: "NOT_RUN" | "COMPLETE" | "FAILED";
  variable: string;
  eligiblePredictors: string[];
  excludedFields: { field: string; reason: string }[];
  design: string;
  missingRowsImputed: number;
  oofCoveragePercent: number;
  estimator: string;
  mae: number | null;
  rmse: number | null;
  accuracy: number | null;
  logLoss: number | null;
  predictedDistribution: HistogramBin[] | CategoryBin[];
  observedDistribution: DistributionPreview;
  imputedDistribution: DistributionPreview;
  after: DistributionPreview;
  sharedAxis: {
    minimum: number | null;
    maximum: number | null;
    binEdges: number[];
  };
  aggregateEffect: {
    observedCount: number;
    imputedCount: number;
    combinedCount: number;
    originalMissingCount: number;
    previewUnfilledMissingCount: number;
    original: {
      mean: number | null;
      median: number | null;
      std: number | null;
    };
    combined: {
      mean: number | null;
      median: number | null;
      std: number | null;
    };
    semantics: string;
  };
  domainBoundViolations: number;
  runtimeSeconds: number;
  seed: number;
  canonicalPredictedPreviewSeed?: number;
  artifactChecksum: string;
};

export type MissingDetail = {
  variable: string;
  dataType: string;
  featureFamily: string;
  method: ImputationMethod;
  fillValue: string | number | null;
  fillPolicy: string;
  before: DistributionPreview;
  after: DistributionPreview;
  sharedAxis: {
    minimum: number | null;
    maximum: number | null;
    binEdges: number[];
  };
  pairedIndicator: string | null;
  canonicalPredictedPreviewSeed?: number;
  governedPriorAvailable: boolean;
  governedPriorUnavailableReason: string | null;
  coldStartHandling: string;
  sourceFailureHandling: string;
  availablePredictors: string[];
  eligiblePredictors: string[];
  excludedPredictorFields: { field: string; reason: string }[];
  predictedPreview: PredictedPreview | null;
  imputedDistribution?: DistributionPreview | null;
  effect: {
    missingCount: number;
    observedCount: number;
    fillCount: number;
    retainedMissingCount: number;
    domainViolations: number;
    affectedGames: number;
    affectedBatters: number;
    affectedPitchers: number;
    original: {
      mean: number | null;
      median: number | null;
      std: number | null;
    };
    transformed: {
      mean: number | null;
      median: number | null;
      std: number | null;
    };
    originalCategories: CategoryBin[];
    transformedCategories: CategoryBin[];
    formula: string;
    fittingRule: string;
  };
};

export type PaginatedTreatmentTable<T> = {
  rows: T[];
  page: number;
  pageSize: number;
  totalRows: number;
  totalPages: number;
  eligibleRows: number;
  excludedRows: number;
  excludedMetadataRows?: number;
  activeSummary?: Omit<OutlierSummary, "policy"> & {
    filtersApplied?: ProjectEdaFilters;
    previewOnly?: boolean;
  };
  activeGlobalMethod?: string;
  canonicalPredictedPreviewSeed?: number;
};

export type TreatmentTableRequest<TOverride> = {
  authorityKey: string;
  filters: TreatmentFilters;
  search: string;
  families: string[];
  coreScope: "CORE" | "CONTEXTUAL" | "";
  dataTypes: string[];
  severity: string;
  includeAdvanced: boolean;
  sort: { field: string; direction: "asc" | "desc" };
  page: number;
  pageSize: number;
  globalMethod: string;
  globalTreatment?: string;
  overrides: Record<string, TOverride>;
  policyVersion: number | null;
};

export async function fetchAllTreatmentRows<T>(
  projectId: string,
  authorityKey: string,
  kind: TreatmentKind,
  request: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T[]> {
  const path = `/projects/${encodeURIComponent(projectId)}/sports/stage3-treatment/${kind}/table`;
  const rows: T[] = [];
  let page = 1;
  let totalPages = 1;
  do {
    const value = await postJSON<TreatmentEnvelope<PaginatedTreatmentTable<T>>>(
      path,
      {
        ...request,
        authorityKey,
        selectedVariables: undefined,
        page,
        pageSize: 100,
        filters: compactProjectEdaFilters(
          (request.filters ?? {}) as ProjectEdaFilters,
        ),
      },
      { signal },
    );
    if (!safeResponse(value, projectId, authorityKey)) {
      throw new Error(
        "Full treatment-table request did not preserve project authority and the final-OOT lock.",
      );
    }
    rows.push(...value.data.rows);
    totalPages = value.data.totalPages;
    page += 1;
  } while (page <= totalPages);
  return rows;
}

type TreatmentQueryState<T> = {
  requestKey: string;
  status: QueryStatus;
  value: TreatmentEnvelope<T> | null;
  error: string | null;
};
const treatmentCache = new Map<string, TreatmentEnvelope<unknown>>();

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined && item !== "")
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}

function responseAuthorityKey(authority: ProjectEdaAuthority): string {
  return [
    authority.sourceManifestSha,
    authority.goldManifestSha,
    authority.contextualManifestSha || "no-context",
    authority.reviewDigest,
  ].join(":");
}

function safeResponse<T>(
  value: TreatmentEnvelope<T>,
  projectId: string,
  authorityKey: string,
): boolean {
  return (
    value.ok &&
    value.authority.projectId === projectId &&
    responseAuthorityKey(value.authority) === authorityKey &&
    value.population.scope === "DEVELOPMENT_ONLY" &&
    value.population.finalOotLocked &&
    !value.audit.finalOotTargetAccessed &&
    !value.audit.finalOotUsedForSelection &&
    !value.audit.legacyGlobalMatrixUsed &&
    value.audit.providerCalls === 0 &&
    Object.values(value.audit.modelActivity).every((count) => count === 0)
  );
}

export function useTreatmentGet<T>(
  projectId: string,
  authorityKey: string,
  kind: TreatmentKind,
  action: "summary" | "policy",
  enabled: boolean,
  refreshKey = 0,
) {
  const path = `/projects/${encodeURIComponent(projectId)}/sports/stage3-treatment/${kind}/${action}`;
  const requestKey = enabled ? `${path}:${authorityKey}:${refreshKey}` : "";
  const [state, setState] = useState<TreatmentQueryState<T>>({
    requestKey,
    status: enabled ? "loading" : "idle",
    value: null,
    error: null,
  });
  const generation = useRef(0);
  const [retryGeneration, setRetryGeneration] = useState(0);
  useEffect(() => {
    if (!enabled) {
      setState({ requestKey: "", status: "idle", value: null, error: null });
      return undefined;
    }
    const controller = new AbortController();
    const current = ++generation.current;
    setState({ requestKey, status: "loading", value: null, error: null });
    void getJSON<TreatmentEnvelope<T>>(path, {
      signal: controller.signal,
      headers: { "X-Stage3-Authority-Key": authorityKey },
    })
      .then((value) => {
        if (controller.signal.aborted || current !== generation.current) return;
        if (!safeResponse(value, projectId, authorityKey))
          throw new Error(
            "Treatment response did not preserve project authority and the final-OOT lock.",
          );
        setState({ requestKey, status: "ready", value, error: null });
      })
      .catch((error) => {
        if (!controller.signal.aborted && current === generation.current)
          setState({
            requestKey,
            status: "error",
            value: null,
            error:
              error instanceof Error
                ? error.message
                : "Treatment authority could not be loaded.",
          });
      });
    return () => controller.abort();
  }, [authorityKey, enabled, path, projectId, requestKey, retryGeneration]);
  return { ...state, retry: () => setRetryGeneration((value) => value + 1) };
}

export function useTreatmentPost<T>(
  projectId: string,
  authorityKey: string,
  kind: TreatmentKind,
  action: "table" | "detail" | "preview",
  request: Record<string, unknown> | null,
) {
  const canonical = useMemo(() => (request ? stable(request) : ""), [request]);
  const path = `/projects/${encodeURIComponent(projectId)}/sports/stage3-treatment/${kind}/${action}`;
  const requestKey = request ? `${path}:${authorityKey}:${canonical}` : "";
  const [state, setState] = useState<TreatmentQueryState<T>>({
    requestKey,
    status: request ? "loading" : "idle",
    value: null,
    error: null,
  });
  const generation = useRef(0);
  const [retryGeneration, setRetryGeneration] = useState(0);
  useEffect(() => {
    if (!request) {
      setState({ requestKey: "", status: "idle", value: null, error: null });
      return undefined;
    }
    const cached = treatmentCache.get(requestKey) as
      TreatmentEnvelope<T> | undefined;
    if (cached && retryGeneration === 0) {
      setState({ requestKey, status: "ready", value: cached, error: null });
      return undefined;
    }
    const controller = new AbortController();
    const current = ++generation.current;
    setState({ requestKey, status: "loading", value: null, error: null });
    void postJSON<TreatmentEnvelope<T>>(
      path,
      {
        ...request,
        authorityKey,
        filters: compactProjectEdaFilters(
          (request.filters ?? {}) as ProjectEdaFilters,
        ),
      },
      { signal: controller.signal },
    )
      .then((value) => {
        if (controller.signal.aborted || current !== generation.current) return;
        if (!safeResponse(value, projectId, authorityKey))
          throw new Error(
            "Treatment preview did not preserve project authority and the final-OOT lock.",
          );
        treatmentCache.set(requestKey, value as TreatmentEnvelope<unknown>);
        setState({ requestKey, status: "ready", value, error: null });
      })
      .catch((error) => {
        if (!controller.signal.aborted && current === generation.current)
          setState({
            requestKey,
            status: "error",
            value: null,
            error:
              error instanceof Error
                ? error.message
                : "Treatment request failed.",
          });
      });
    return () => controller.abort();
  }, [
    action,
    authorityKey,
    canonical,
    kind,
    path,
    projectId,
    requestKey,
    retryGeneration,
  ]);
  return { ...state, retry: () => setRetryGeneration((value) => value + 1) };
}

export function useTreatmentMutation<T>(
  projectId: string,
  authorityKey: string,
  kind: TreatmentKind,
) {
  const [state, setState] = useState<{
    status: QueryStatus;
    value: TreatmentEnvelope<T> | null;
    error: string | null;
  }>({ status: "idle", value: null, error: null });
  const generation = useRef(0);
  const run = useCallback(
    async (
      action: "policy/draft" | "policy/adopt" | "predicted-preview",
      body: Record<string, unknown>,
    ) => {
      const current = ++generation.current;
      setState({ status: "loading", value: null, error: null });
      try {
        const value = await postJSON<TreatmentEnvelope<T>>(
          `/projects/${encodeURIComponent(projectId)}/sports/stage3-treatment/${kind}/${action}`,
          { ...body, authorityKey },
        );
        if (current !== generation.current) return null;
        if (!safeResponse(value, projectId, authorityKey))
          throw new Error(
            "Treatment mutation response failed authority or OOT validation.",
          );
        treatmentCache.clear();
        setState({ status: "ready", value, error: null });
        return value;
      } catch (error) {
        if (current === generation.current)
          setState({
            status: "error",
            value: null,
            error:
              error instanceof Error
                ? error.message
                : "Treatment action failed.",
          });
        return null;
      }
    },
    [authorityKey, kind, projectId],
  );
  const reset = useCallback(() => {
    generation.current += 1;
    setState({ status: "idle", value: null, error: null });
  }, []);
  return { ...state, run, reset };
}

export function useTreatmentSpecification(
  projectId: string,
  authorityKey: string,
  enabled: boolean,
) {
  const [refreshKey, setRefreshKey] = useState(0);
  const [state, setState] = useState<
    TreatmentQueryState<TreatmentSpecificationData>
  >({
    requestKey: "",
    status: enabled ? "loading" : "idle",
    value: null,
    error: null,
  });
  const [draftStatus, setDraftStatus] = useState<QueryStatus>("idle");
  const [draftError, setDraftError] = useState<string | null>(null);
  const [adoptStatus, setAdoptStatus] = useState<QueryStatus>("idle");
  const [adoptError, setAdoptError] = useState<string | null>(null);
  const generation = useRef(0);
  const mutationController = useRef<AbortController | null>(null);
  const path = `/projects/${encodeURIComponent(projectId)}/sports/stage3-treatment/specification`;

  const load = useCallback(async () => {
    if (!enabled) return null;
    const current = ++generation.current;
    const requestKey = `${path}:${authorityKey}:${refreshKey}`;
    setState({ requestKey, status: "loading", value: null, error: null });
    try {
      const value = await getJSON<
        TreatmentEnvelope<TreatmentSpecificationData>
      >(path, { headers: { "X-Stage3-Authority-Key": authorityKey } });
      if (current !== generation.current) return null;
      if (!safeResponse(value, projectId, authorityKey))
        throw new Error(
          "Treatment specification did not preserve project authority and the final-OOT lock.",
        );
      setState({ requestKey, status: "ready", value, error: null });
      return value;
    } catch (error) {
      if (current === generation.current)
        setState({
          requestKey,
          status: "error",
          value: null,
          error:
            error instanceof Error
              ? error.message
              : "Treatment specification could not be loaded.",
        });
      return null;
    }
  }, [authorityKey, enabled, path, projectId, refreshKey]);

  useEffect(() => {
    if (!enabled) {
      generation.current += 1;
      mutationController.current?.abort();
      mutationController.current = null;
      setState({ requestKey: "", status: "idle", value: null, error: null });
      return undefined;
    }
    setDraftStatus("idle");
    setDraftError(null);
    setAdoptStatus("idle");
    setAdoptError(null);
    void load();
    return () => {
      generation.current += 1;
      mutationController.current?.abort();
      mutationController.current = null;
    };
  }, [enabled, load]);

  const createDraft = useCallback(async () => {
    const currentSpecification = state.value?.data;
    if (!currentSpecification?.canCreateDraft) return null;
    mutationController.current?.abort();
    const controller = new AbortController();
    mutationController.current = controller;
    const current = ++generation.current;
    setDraftStatus("loading");
    setDraftError(null);
    try {
      const value = await postJSON<
        TreatmentEnvelope<TreatmentSpecificationData>
      >(`${path}/draft`, {
        authorityKey,
        expectedManifestChecksum:
          currentSpecification.specification.manifestChecksum,
      }, { signal: controller.signal });
      if (controller.signal.aborted || current !== generation.current)
        return null;
      if (!safeResponse(value, projectId, authorityKey))
        throw new Error(
          "Treatment specification draft failed authority or OOT validation.",
        );
      setState({
        requestKey: `${path}:${authorityKey}:draft`,
        status: "ready",
        value,
        error: null,
      });
      setDraftStatus("ready");
      return value;
    } catch (error) {
      if (controller.signal.aborted || current !== generation.current)
        return null;
      setDraftStatus("error");
      setDraftError(
        error instanceof Error
          ? error.message
          : "Combined treatment specification draft could not be created.",
      );
      return null;
    }
  }, [authorityKey, path, projectId, state.value]);

  const adoptSpecification = useCallback(async () => {
    const currentSpecification = state.value?.data;
    const currentDraft = currentSpecification?.draft;
    if (
      !currentSpecification?.canAdopt ||
      !currentDraft ||
      !hasCurrentTreatmentSpecificationDraft(currentSpecification)
    )
      return null;
    mutationController.current?.abort();
    const controller = new AbortController();
    mutationController.current = controller;
    const current = ++generation.current;
    setAdoptStatus("loading");
    setAdoptError(null);
    try {
      const value = await postJSON<
        TreatmentEnvelope<TreatmentSpecificationData>
      >(`${path}/adopt`, {
        authorityKey,
        specificationDraftId:
          currentDraft.specificationDraftId,
        expectedManifestChecksum:
          currentDraft.manifestChecksum,
      }, { signal: controller.signal });
      if (controller.signal.aborted || current !== generation.current)
        return null;
      if (!safeResponse(value, projectId, authorityKey))
        throw new Error(
          "Treatment specification adoption failed authority or OOT validation.",
        );
      setState({
        requestKey: `${path}:${authorityKey}:adopt`,
        status: "ready",
        value,
        error: null,
      });
      setAdoptStatus("ready");
      return value;
    } catch (error) {
      if (controller.signal.aborted || current !== generation.current)
        return null;
      setAdoptStatus("error");
      setAdoptError(
        error instanceof Error
          ? error.message
          : "Combined treatment specification could not be adopted.",
      );
      return null;
    }
  }, [authorityKey, path, projectId, state.value]);

  return {
    ...state,
    draftStatus,
    draftError,
    adoptStatus,
    adoptError,
    retry: () => setRefreshKey((value) => value + 1),
    createDraft,
    adoptSpecification,
  };
}

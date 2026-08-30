import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getJSON, postJSON } from "../../lib/api";

export type ProjectEdaQueryType =
  | "overview"
  | "distribution"
  | "category_counts"
  | "association"
  | "pairwise_sample"
  | "missingness"
  | "outliers"
  | "temporal"
  | "cold_start";

export type ProjectEdaFilters = {
  seasons?: number[];
  startDate?: string;
  endDate?: string;
  months?: number[];
  daysOfWeek?: string[];
  outcomes?: string[];
  batter?: string;
  pitcher?: string;
  battingTeam?: string;
  fieldingTeam?: string;
  homeAway?: string;
  historyStatus?: string;
  missingness?: string;
  simulationState?: {
    field: "context_inning" | "context_top_bottom" | "context_outs_before" | "context_base_mask_before" | "context_batting_score_diff_before";
    value: number;
  };
  minimumSampleSize?: number;
};

export type ProjectEdaVariable = {
  name: string;
  label: string;
  definition: string;
  dataType: string;
  role: string;
  featureFamily: string;
  category: string;
  sourceLineage: string;
  pointInTimeTreatment: string;
  availabilityEra: string;
  missingPercent: number;
  uniqueCount: number | null;
  selectable: boolean;
  core: boolean;
  proxyWarning: string | null;
  /** Optional server-authored rationale. Older metadata falls back to the governed client rationale below. */
  selectionReason?: string | null;
};

export type ProjectEdaVariableSelection = {
  code: "CORE_PREDICTOR" | "CONTEXTUAL_CANDIDATE" | "SIMULATOR_STATE" | "MISSINGNESS_INDICATOR" | "TARGET_STRATIFICATION_ONLY" | "FILTER_OR_LINEAGE_ONLY" | "GOVERNANCE_LOCKED";
  selectable: boolean;
  label: string;
  detail: string;
};

/**
 * Explain why a metadata field can or cannot enter an analytical variable set.
 * This never changes server selectability and never promotes a variable into a
 * model; it only makes the existing governed metadata decision visible.
 */
export function projectEdaVariableSelection(variable: ProjectEdaVariable): ProjectEdaVariableSelection {
  if (variable.selectable) {
    if (variable.role === "SIMULATION_GENERATED_STATE") {
      return {
        code: "SIMULATOR_STATE",
        selectable: true,
        label: "Selectable simulator state",
        detail: variable.selectionReason || "Supplied by the simulator at forecast time; available for descriptive development-only analysis.",
      };
    }
    if (variable.role === "MISSINGNESS_INDICATOR") {
      return {
        code: "MISSINGNESS_INDICATOR",
        selectable: true,
        label: "Selectable missingness indicator",
        detail: variable.selectionReason || "May be explored as an explicit indicator; selection here is not a feature-adoption decision.",
      };
    }
    if (variable.core) {
      return {
        code: "CORE_PREDICTOR",
        selectable: true,
        label: "Selectable Core Gold predictor",
        detail: variable.selectionReason || "Registered Core Gold-48 predictor with reviewed point-in-time treatment.",
      };
    }
    return {
      code: "CONTEXTUAL_CANDIDATE",
      selectable: true,
      label: "Selectable contextual candidate",
      detail: variable.selectionReason || "Registered contextual candidate available for descriptive review; not automatically adopted for modeling.",
    };
  }
  if (variable.role === "TARGET") {
    return {
      code: "TARGET_STRATIFICATION_ONLY",
      selectable: false,
      label: "Target is stratification-only",
      detail: variable.selectionReason || "The governed outcome may be used only through development-safe target controls, never as an input variable.",
    };
  }
  if (["IDENTIFIER", "GROUPING", "TIME", "RESEARCH_ONLY"].includes(variable.role)) {
    return {
      code: "FILTER_OR_LINEAGE_ONLY",
      selectable: false,
      label: "Metadata / filter only",
      detail: variable.selectionReason || "Retained for lineage, grouping, or filtering and hidden from analytical variable choices by default.",
    };
  }
  return {
    code: "GOVERNANCE_LOCKED",
    selectable: false,
    label: "Not selectable",
    detail: variable.selectionReason || variable.proxyWarning || "The registered variable contract does not authorize analytical selection.",
  };
}

export type ProjectEdaFamily = {
  name: string;
  featureCount: number;
  activeCount: number;
  missingPercent: number;
  coveragePercent: number;
  orderedFeatures: string[];
  proxyWarning: string | null;
};

export type ProjectEdaAuthority = {
  projectId: string;
  sourceDatasetId: string;
  sourceManifestSha: string;
  goldDatasetId: string;
  goldManifestSha: string;
  contextualDatasetId: string;
  contextualManifestSha: string;
  reviewDigest: string;
};

export type ProjectEdaPopulation = {
  scope: "DEVELOPMENT_ONLY";
  rows: number;
  finalOotRows: number;
  finalOotLocked: true;
  developmentEndDate: string;
  filtersApplied: Record<string, unknown>;
  rowsRepresented: number;
  aggregation: string;
  sampling: null | { method: string; seed: number; populationSize: number; sampleSize: number };
};

export type ProjectEdaMetadata = {
  schemaVersion: string;
  variables: ProjectEdaVariable[];
  families: ProjectEdaFamily[];
  targetTaxonomy: string[];
  filterOptions: { seasons: number[]; months: number[]; outcomes: string[] };
  queryLimits: { maxVariables: number; maxSampleRows: number; maxBins: number; maxCategories: number };
  notices: string[];
  decisionGuidance: {
    defaultAnalyticalTab: "TARGET_AND_CLASS_BALANCE";
    defaultStabilityVariables: string[];
    defaultStabilityVariableExcluded: "context_inning";
    selectionAuthority: "NONE_DESCRIPTIVE_EDA_ONLY";
  };
};

export type ProjectEdaEnvelope<T> = {
  ok: true;
  authority: ProjectEdaAuthority;
  population: ProjectEdaPopulation;
  audit: {
    finalOotTargetAccessed: boolean;
    finalOotUsedForSelection: boolean;
    legacyGlobalMatrixUsed: boolean;
    providerCalls: number;
    modelActivity: { fits: number; scores: number; tunes: number; calibrations: number; selections: number; promotions: number };
  };
  data: T;
};

export type OverviewData = {
  summary: {
    developmentRows: number;
    games: number;
    batters: number;
    pitchers: number;
    startDate: string;
    endDate: string;
    targetClasses: number;
    coreFeatures: number;
    contextualCandidates: number;
    overallMissingPercent: number;
    coldStartPercent: number;
    rowExclusions: {
      sourceRows: number;
      goldRows: number;
      excludedRows: number;
      bySeason: { season: number; sourceRows: number; goldRows: number; excludedRows: number }[];
      reasonCounts: Record<string, number>;
      reasonStatus: string;
      unsupportedConcentrations: string[];
    };
  };
  targetSummary: {
    dominantClass: { value: string; count: number; percent: number } | null;
    rarestClass: { value: string; count: number; percent: number } | null;
    imbalanceRatio: number | null;
    seasonToSeasonStability: {
      status: string;
      method: string;
      maxClassShareRangePct: number | null;
      mostVariableClass: string | null;
      thresholdsPct?: Record<string, number>;
    };
    minimumRareClassSampleSize: number;
    minimumRareClassSeason: number | null;
    status: string;
    conclusion: string;
    decision: string;
    finalOotTargetsAccessed: false;
  };
  dataQualitySnapshot: {
    overallPhysicalMissingPercent: number;
    coldStartRows: number;
    coldStartPercent: number;
    materialMissingnessThresholdPct: number;
    featuresWithMaterialMissingness: number;
    materialMissingFeatures: { name: string; missingPercent: number }[];
    failureReasonRows: {
      scope: string;
      computationFailureRows: number;
      sourceMissingRows: number;
      sourceNotAvailableForEraRows: number;
      note: string;
    };
    potentialDescriptiveOutliers: {
      scope: string;
      variable: string;
      method: string;
      count: number;
      lowerThreshold: number | null;
      upperThreshold: number | null;
      treatmentApplied: false;
    };
    actions: string[];
    decision: string;
    finalOotTargetsAccessed: false;
  };
  targetDistribution: { value: string; count: number; percent: number }[];
  targetBySeason: { season: number; value: string; count: number; percent: number }[];
  targetByMonth: { period: string; value: string; count: number; percent: number }[];
  targetBySimulationState: { field: string; state: string | number; value: string; count: number; percent: number }[];
  rowsByMonth: { period: string; count: number }[];
  featureFamilyCoverage: { family: string; featureCount: number; coveragePercent: number; missingPercent: number }[];
  historyDepth: { label: string; count: number; percent: number }[];
};

export type DistributionData = {
  variable: string;
  dataType: string;
  statistics: Record<string, number | null>;
  histogram: { binStart: number; binEnd: number; count: number; percent: number }[];
  ecdf: { value: number; cumulativePercent: number }[];
  density: { value: number; density: number }[];
  box: { min: number | null; q1: number | null; median: number | null; q3: number | null; max: number | null; lowerFence: number | null; upperFence: number | null; outlierCount: number };
  stratified: { stratum: string; count: number; mean: number | null; median: number | null; missingPercent: number }[];
};

export type CategoryCountsData = {
  variable: string;
  categories: { value: string; count: number; percent: number; targetComposition: { value: string; count: number; percent: number }[] }[];
  missingCount: number;
  otherCount: number;
};

export type AssociationData = {
  variables: string[];
  methods: string[];
  cells: { x: string; y: string; value: number | null; method: string; rows: number }[];
};

export type PairwiseData = {
  variables: string[];
  populationSize: number;
  sampleSize: number;
  seed: number;
  method: "HASH_SMALLEST_CANONICAL_PA_V1";
  stratifyBy?: "outcome" | null;
  rows: Record<string, string | number | null>[];
};

export type MissingnessData = {
  variables: { name: string; missingCount: number; missingPercent: number; affectedPlayers: number; reasonCounts: Record<string, number> }[];
  coMissingness: { x: string; y: string; count: number; percent: number }[];
  byPeriod: { period: string; variable: string; missingCount: number; missingPercent: number }[];
  reasons: { reason: string; count: number }[];
};

export type OutliersData = {
  variable: string;
  method: string;
  thresholds: { lower: number | null; upper: number | null };
  count: number;
  percent: number;
  extremes: { canonicalPaId: string; gameDate: string; value: number; side: string }[];
};

export type TemporalData = {
  variable: string;
  variables: string[];
  granularity: string;
  series: { period: string; count: number; mean: number | null; median: number | null; missingPercent: number; targetComposition: { value: string; count: number; percent: number }[] }[];
  drift: { period: string; baselinePeriod: string; psi: number | null; ks: number | null; method: string }[];
  seriesByVariable: Record<string, { period: string; count: number; mean: number | null; median: number | null; missingPercent: number; targetComposition: { value: string; count: number; percent: number }[] }[]>;
  driftByVariable: Record<string, { period: string; baselinePeriod: string; psi: number | null; ks: number | null; method: string }[]>;
  stabilityAssessment: {
    overallStatus: string;
    targetMix: { status: string; method: string; maxClassShareRangePct: number | null; mostVariableClass: string | null };
    featureCounts: { scope: string; stable: number; moderateReview: number; highReview: number; sourceEraChange: number };
    selectedVariables: {
      variable: string;
      status: string;
      direction: string;
      magnitude: number | null;
      relativeMagnitudePct: number | null;
      baselinePeriod: string | null;
      latestPeriod: string | null;
      affectedPeriods: string[];
      psiMax: number;
      ksMax: number | null;
      methods: string[];
      coverageShiftPct: number;
      coverageRangePct: number;
      likelyCause: string;
      recommendedNextAction: string;
      decision: string;
    }[];
    coldStartShift: { status: string; baselinePct: number | null; latestPct: number | null; maxRangePct: number; byPeriod: { period: string; coldStartPercent: number }[] };
    sourceEraChanges: unknown[];
    sourceEraEvidenceStatus: string;
    rowVolumeNote: string;
    recommendedNextAction: string;
    thresholds: Record<string, number>;
    decision: string;
    finalOotTargetsAccessed: false;
  };
};

export type ColdStartData = {
  summary: { coldStartRows: number; coldStartPercent: number; affectedGames: number; affectedTeams: number };
  batter: { noPriorRows: number; insufficientRows: number; affectedPlayers: number; affectedGames: number; affectedTeams: number; byPeriod: { period: string; noPriorRows: number; insufficientRows: number }[] };
  pitcher: { noPriorRows: number; insufficientRows: number; affectedPlayers: number; affectedGames: number; affectedTeams: number; byPeriod: { period: string; noPriorRows: number; insufficientRows: number }[] };
  targetComposition: { scope: string; value: string; count: number; percent: number }[];
};

const metadataCache = new Map<string, ProjectEdaEnvelope<ProjectEdaMetadata>>();
const queryCache = new Map<string, ProjectEdaEnvelope<unknown>>();

function responseAuthorityKey(authority: ProjectEdaAuthority): string {
  return [authority.sourceManifestSha, authority.goldManifestSha, authority.contextualManifestSha || "no-context", authority.reviewDigest].join(":");
}

function responseIsSafe<T>(value: ProjectEdaEnvelope<T>): boolean {
  return !value.audit.finalOotTargetAccessed
    && !value.audit.finalOotUsedForSelection
    && !value.audit.legacyGlobalMatrixUsed
    && value.audit.providerCalls === 0
    && Object.values(value.audit.modelActivity).every((count) => count === 0);
}

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined && item !== "" && !(Array.isArray(item) && item.length === 0))
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export function compactProjectEdaFilters(filters: ProjectEdaFilters): ProjectEdaFilters {
  return Object.fromEntries(
    Object.entries(filters).filter(([, value]) => value !== undefined && value !== "" && !(Array.isArray(value) && value.length === 0)),
  ) as ProjectEdaFilters;
}

export function useProjectEdaMetadata(projectId: string, authorityKey: string, enabled: boolean) {
  const [state, setState] = useState<{ status: "idle" | "loading" | "ready" | "error"; value: ProjectEdaEnvelope<ProjectEdaMetadata> | null; error: string | null }>({
    status: enabled ? "loading" : "idle",
    value: null,
    error: null,
  });
  const refresh = useCallback(async (signal?: AbortSignal, bypassCache = false) => {
    if (!enabled || !projectId) return;
    const key = `${projectId}:${authorityKey}`;
    if (!bypassCache && metadataCache.has(key)) {
      setState({ status: "ready", value: metadataCache.get(key)!, error: null });
      return;
    }
    setState((previous) => ({ ...previous, status: "loading", error: null }));
    try {
      const value = await getJSON<ProjectEdaEnvelope<ProjectEdaMetadata>>(
        `/projects/${encodeURIComponent(projectId)}/sports/stage3-eda/metadata`,
        { signal },
      );
      if (signal?.aborted) return;
      if (!value.ok || value.authority.projectId !== projectId || responseAuthorityKey(value.authority) !== authorityKey || value.population.scope !== "DEVELOPMENT_ONLY" || !value.population.finalOotLocked || !responseIsSafe(value)) {
        throw new Error("The project-bound development-only EDA authority was incomplete.");
      }
      metadataCache.set(key, value);
      setState({ status: "ready", value, error: null });
    } catch (error) {
      if (signal?.aborted) return;
      setState({ status: "error", value: null, error: error instanceof Error ? error.message : "EDA metadata could not be loaded." });
    }
  }, [authorityKey, enabled, projectId]);
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);
  return { ...state, refresh: () => refresh(undefined, true) };
}

export type ProjectEdaQuery = {
  queryType: ProjectEdaQueryType;
  filters?: ProjectEdaFilters;
  variables?: string[];
  settings?: Record<string, unknown>;
};

export function useProjectEdaQuery<T>(projectId: string, authorityKey: string, query: ProjectEdaQuery | null) {
  const canonical = useMemo(() => query ? stable({ ...query, filters: compactProjectEdaFilters(query.filters ?? {}) }) : "", [query]);
  const requestKey = query && projectId ? `${projectId}:${authorityKey}:${canonical}` : "";
  const [state, setState] = useState<{ requestKey: string; status: "idle" | "loading" | "ready" | "error"; value: ProjectEdaEnvelope<T> | null; error: string | null }>({ requestKey, status: query ? "loading" : "idle", value: null, error: null });
  const generation = useRef(0);
  useEffect(() => {
    if (!query || !projectId) {
      setState({ requestKey: "", status: "idle", value: null, error: null });
      return undefined;
    }
    const cached = queryCache.get(requestKey) as ProjectEdaEnvelope<T> | undefined;
    if (cached) {
      setState({ requestKey, status: "ready", value: cached, error: null });
      return undefined;
    }
    const controller = new AbortController();
    const requestGeneration = ++generation.current;
    setState({ requestKey, status: "loading", value: null, error: null });
    void postJSON<ProjectEdaEnvelope<T>>(
      `/projects/${encodeURIComponent(projectId)}/sports/stage3-eda/query`,
      { ...query, filters: compactProjectEdaFilters(query.filters ?? {}) },
      { signal: controller.signal },
    ).then((value) => {
      if (controller.signal.aborted || requestGeneration !== generation.current) return;
      if (!value.ok || value.authority.projectId !== projectId || responseAuthorityKey(value.authority) !== authorityKey || value.population.scope !== "DEVELOPMENT_ONLY" || !value.population.finalOotLocked || !responseIsSafe(value)) {
        throw new Error("The analytical response did not preserve the project-bound OOT lock.");
      }
      queryCache.set(requestKey, value as ProjectEdaEnvelope<unknown>);
      setState({ requestKey, status: "ready", value, error: null });
    }).catch((error) => {
      if (controller.signal.aborted || requestGeneration !== generation.current) return;
      setState({ requestKey, status: "error", value: null, error: error instanceof Error ? error.message : "The analytical query failed." });
    });
    return () => controller.abort();
  }, [projectId, authorityKey, canonical, requestKey]); // canonical is the stable query identity; query is deliberately excluded.
  if (state.requestKey !== requestKey) {
    return { requestKey, status: query ? "loading" as const : "idle" as const, value: null, error: null };
  }
  return state;
}

export function downloadAggregatedCsv(filename: string, rows: Record<string, unknown>[]) {
  if (!rows.length) return;
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const cell = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const content = [columns.map(cell).join(","), ...rows.map((row) => columns.map((column) => cell(row[column])).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

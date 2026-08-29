import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../../lib/api";

export type Stage2Check = {
  code: string;
  status: "PASS" | "PASS_WITH_CONDITIONS" | "REVIEW" | "FAIL";
  blocking: boolean;
  detail: string;
};

export type Stage2Column = {
  name: string;
  dtype: string;
  nullable: boolean;
  classification:
    | "IDENTIFIER"
    | "GROUPING"
    | "TIME"
    | "TARGET"
    | "PREGAME_FEATURE"
    | "SIMULATION_GENERATED_STATE"
    | "MISSINGNESS_INDICATOR"
    | "RESEARCH_ONLY"
    | "EXCLUDED";
  predictorOrder: number | null;
};

export type Stage2Missingness = {
  feature: string;
  order: number;
  classification: Stage2Column["classification"];
  missingRows: number;
  overallMissingPct: number;
  developmentMissingPct: number;
  finalOotMissingPct: number;
  indicatorField: string | null;
  indicatorRows: number;
  indicatorPrevalence: number;
  affectedRows: number;
  affectedPlayerCount: number;
  primaryReasonCategory: string | null;
  reasonCounts: { category: string; rows: number }[];
  computationFailureRows: number;
  bySeason: { season: number; missingRows: number; rows: number; missingPct: number }[];
  byMonth: { month: string; missingRows: number; rows: number; missingPct: number }[];
};

export type ContextualFeaturePack = {
  status: string;
  verified: boolean;
  datasetId: string;
  manifestSha256: string;
  sourceGoldManifestSha256: string;
  rowCount: number;
  coreFeatureCount: number;
  addedFeatureCount: number;
  totalFeatureCount: number;
  teamGameRowCount: number;
  rivalryMappingStatus: string;
  features: {
    name: string;
    family: string;
    category: string;
    definition: string;
    sourceLineage: string;
    pointInTimeTreatment: string;
    coverageOverall: number;
    coverageDevelopment: number;
    coverageFinalOot: number;
    proxyWarning: string | null;
    includedByDefault: boolean;
  }[];
  families: {
    name: string;
    featureCount: number;
    orderedFeatures: string[];
    includedByDefault: boolean;
  }[];
  interactions: { name: string; status: string; reason: string }[];
  warnings: string[];
};

export type CurrentGoldDataReview = {
  schemaVersion: string;
  projectId: string;
  sourceAuthority: {
    registrationId: string;
    datasetId: string;
    datasetVersionId: string;
    manifestSha: string;
    activationRevision: number;
    rowCount: number;
    dateCoverage: { earliestDate: string; latestDate: string };
    silverPublicationManifestSha: string;
  };
  goldAuthority: {
    datasetId: string;
    manifestSha: string;
    manifestContract: string;
    manifestVersion: number;
    status: string;
    modelsFitted: number;
    modelPromoted: boolean;
    rowCount: number;
    featureCount: number;
    dateCoverage: { earliestDate: string; latestDate: string };
    rowsBySeason: Record<string, number>;
    sourceSilverManifestSha: string;
    verified: boolean;
  };
  matrix: {
    grain: string;
    totalColumns: number;
    predictorCount: number;
    orderedPredictors: string[];
    seasons: number[];
    development: { startDate: string; endDate: string; rows: number };
    finalOot: { startDate: string; endDate: string; rows: number };
    columns: Stage2Column[];
  };
  targetTaxonomy: {
    column: string;
    classOrder: string[];
    distributions: Record<string, { class: string; rows: number }[]>;
  };
  identity: {
    observedPlayerCount: number;
    matchedExactPlayerCount: number;
    unresolvedPlayerIdentities: number;
    ambiguousPlayerIdentities: number;
    unresolvedGameIdentities: number;
    ambiguousGameIdentities: number;
    duplicateCanonicalPaIdentities: number;
    duplicatePlateAppearanceIdentities: number;
    nullIdentityRows: number;
    paAliasValueDifferences: number;
    gameAliasValueDifferences: number;
  };
  missingness: {
    reasonCategories: string[];
    predictors: Stage2Missingness[];
    note: string;
  };
  contextualFeaturePack?: ContextualFeaturePack;
  pointInTimeReview: Stage2Check;
  leakageGate: Stage2Check;
  modelingTreatment: {
    coldStartRows: string;
    imputation: string;
    missingFlags: string;
    globalImputation: string;
    validationOrOotPreprocessing: string;
    simulationStateForecastRule: string;
  };
  checks: Stage2Check[];
  acceptance: { allowed: boolean; blockers: string[] };
  reviewDigest: string;
  preview: {
    season: number | null;
    sample: string;
    limit: number;
    columns: string[];
    rows: Record<string, unknown>[];
  };
};

export type CurrentGoldReviewState = {
  status: "idle" | "loading" | "ready" | "error";
  review: CurrentGoldDataReview | null;
  error: string | null;
  refresh: () => Promise<void>;
};

export function useProjectCurrentGoldDataReview(projectId: string, enabled = true): CurrentGoldReviewState {
  const [status, setStatus] = useState<CurrentGoldReviewState["status"]>(enabled ? "loading" : "idle");
  const [review, setReview] = useState<CurrentGoldDataReview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!enabled || !projectId) {
      setStatus("idle");
      setReview(null);
      setError(null);
      return;
    }
    setStatus("loading");
    setError(null);
    try {
      const payload = await getJSON<{ ok: boolean; review: CurrentGoldDataReview }>(
        `/projects/${encodeURIComponent(projectId)}/sports/stage2-data-review?limit=25&sample=head`,
        { signal },
      );
      if (signal?.aborted) return;
      if (!payload?.ok || !payload.review || payload.review.projectId !== projectId) {
        throw new Error("The project-scoped Stage 2 review response was incomplete.");
      }
      setReview(payload.review);
      setStatus("ready");
    } catch (caught) {
      if (signal?.aborted) return;
      setReview(null);
      setStatus("error");
      setError(caught instanceof Error ? caught.message : "The current Gold review could not be loaded.");
    }
  }, [enabled, projectId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  return { status, review, error, refresh: async () => load() };
}

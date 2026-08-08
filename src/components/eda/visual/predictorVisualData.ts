import type {
  PredictorAggregate,
  PredictorEventRateBin,
  PredictorSpecialValueAggregate,
  PredictorVisualContract,
  PredictorVisualDatum,
  PredictorVisualProfile,
  PredictorVisualSuiteProps,
} from "./predictorVisualTypes";

export const PREDICTOR_VISUAL_MAX_MARKS = 60;
export const PREDICTOR_GALLERY_MAX = 10;
export const PREDICTOR_MATRIX_MAX_ROWS = 30;

const ALWAYS_EXCLUDED = new Set(["bad_flag", "riskperformance"]);

function normalizedName(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
}

function finite(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function boundedRate(value: unknown): number | null {
  const number = finite(value);
  if (number === null) return null;
  return Math.max(0, Math.min(1, number));
}

function specialFeature(row: PredictorSpecialValueAggregate) {
  return String(row.feature ?? row.variable ?? "").trim();
}

function specialCount(row: PredictorSpecialValueAggregate) {
  const direct = finite(row.special_value_count ?? row.specialValueCount);
  if (direct !== null) return Math.max(0, direct);
  const profileCount = row.special_values?.reduce(
    (sum, item) => sum + Math.max(0, finite(item.count) ?? 0),
    0
  );
  if (profileCount !== undefined) return profileCount;
  const legacy =
    (finite(row.countMinus7) ?? 0) +
    (finite(row.countMinus8) ?? 0) +
    (finite(row.countMinus9) ?? 0);
  return legacy > 0 ? legacy : null;
}

function specialRate(
  row: PredictorSpecialValueAggregate,
  rowCount: number
) {
  const direct = boundedRate(
    row.special_value_rate ??
      row.specialValueRate ??
      row.special_value_frequency
  );
  if (direct !== null) return direct;
  const count = specialCount(row);
  return count !== null && rowCount > 0 ? Math.min(1, count / rowCount) : null;
}

function eventBins(row: PredictorAggregate) {
  const quantiles = Array.isArray(row.event_rate_by_quantile)
    ? row.event_rate_by_quantile
    : [];
  const source: PredictorEventRateBin[] = quantiles.length
    ? quantiles
    : (row.top_levels ?? []).map((item) => ({
        label: String(item.level ?? ""),
        count: finite(item.count) ?? 0,
        event_rate: boundedRate(item.event_rate),
      }));
  return source.slice(0, 20).map((item, index) => ({
    label: String(item.label ?? item.bin ?? `Band ${index + 1}`),
    count: Math.max(0, finite(item.count) ?? 0),
    eventRate: boundedRate(item.event_rate),
  }));
}

function eventSpread(
  bins: Array<{ eventRate: number | null }>
): number | null {
  const rates = bins
    .map((item) => item.eventRate)
    .filter((value): value is number => value !== null);
  return rates.length >= 2 ? Math.max(...rates) - Math.min(...rates) : null;
}

function monotonicityScore(value: unknown) {
  const label = normalizedName(value);
  if (label.includes("increasing")) return 1;
  if (label.includes("decreasing")) return -1;
  return 0;
}

function treatmentLabel(row?: PredictorSpecialValueAggregate) {
  return String(
    row?.treatment_state ??
      row?.recommended_treatment ??
      row?.recommendedTreatment ??
      "Not documented"
  );
}

function validCanonicalContract(
  contract: PredictorVisualContract | null | undefined
) {
  if (!contract) return false;
  const buckets = new Set(contract.non_overlapping_quality_buckets ?? []);
  const scopeIsValid =
    contract.scope === "full_dataset_aggregates" ||
    (contract.scope === "governed_mixed_scope" &&
      contract.descriptive_scope === "full_governed_population" &&
      contract.target_directed_scope === "development_population" &&
      Number(contract.target_directed_rows ?? 0) > 0 &&
      contract.final_holdout_accessed === false);
  return (
    contract.version === "eda-predictor-visual-v1" &&
    contract.request_mode === "single_batched_workspace_request" &&
    scopeIsValid &&
    contract.raw_observations_included === false &&
    contract.server_authorized_predictors_only === true &&
    contract.target_excluded === true &&
    contract.target_source_exclusions_disclosed_at_response_root === true &&
    contract.additional_vif_computation === false &&
    buckets.has("null_missing") &&
    buckets.has("bureau_special_value") &&
    buckets.has("ordinary_outlier")
  );
}

function canonicalEventBins(profile: PredictorVisualProfile) {
  if (
    !["full_dataset_aggregates", "development_population"].includes(
      profile.event_rate_shape?.scope
    ) ||
    profile.event_rate_shape?.raw_observations_included !== false
  ) {
    return [];
  }
  return (profile.event_rate_shape.groups ?? [])
    .slice(0, Math.max(0, profile.event_rate_shape.limit || 0))
    .map((group) => ({
      label: String(group.label ?? ""),
      count: Math.max(0, finite(group.count) ?? 0),
      eventRate: boundedRate(group.event_rate),
    }));
}

function canonicalTreatment(profile: PredictorVisualProfile) {
  const count = Math.max(0, finite(profile.bureau_special?.count) ?? 0);
  if (!count) return "No bureau special values observed";
  return "Review as meaning-bearing coded values; keep separate from null missingness";
}

function canonicalDetails(profile: PredictorVisualProfile) {
  return (profile.bureau_special?.values ?? []).slice(0, 10).map((item) => ({
    value: String(item.value ?? ""),
    definition: String(item.definition ?? "Configured bureau special value"),
    count: Math.max(0, finite(item.count) ?? 0),
    prevalence: boundedRate(item.prevalence),
    eventRate: boundedRate(item.event_rate),
  }));
}

function reviewSignalsFor(row: {
  missingRate: number;
  specialValueRate: number | null;
  outlierRate: number | null;
  skewness: number | null;
  vif: number | null;
  monotonicity: string;
  distinctRatio: number;
  distinctCount: number;
}) {
  const signals: string[] = [];
  if (row.missingRate >= 0.05) signals.push("missingness");
  if (row.specialValueRate !== null && row.specialValueRate > 0) {
    signals.push("bureau special values");
  }
  if (row.outlierRate !== null && row.outlierRate >= 0.03) {
    signals.push("ordinary outlier prevalence");
  }
  if (Math.abs(row.skewness ?? 0) >= 2) signals.push("skewness");
  if (row.vif !== null && row.vif >= 5) signals.push("VIF");
  if (normalizedName(row.monotonicity).includes("non-monotonic")) {
    signals.push("non-monotonic target shape");
  }
  if (row.distinctRatio >= 0.95 && row.distinctCount > 20) {
    signals.push("near-identifier cardinality");
  }
  return signals;
}

function buildCanonicalRows(
  input: PredictorVisualSuiteProps,
  excluded: Set<string>,
  authorized: Set<string>
) {
  if (!validCanonicalContract(input.predictorVisualContract)) return [];
  const governedMixedScope =
    input.predictorVisualContract?.scope === "governed_mixed_scope";
  const vifByFeature = new Map(
    (input.vif ?? []).map((row) => [
      normalizedName(row.feature),
      finite(row.vif ?? row.value),
    ])
  );
  const seen = new Set<string>();
  const result: PredictorVisualDatum[] = [];
  for (const profile of input.predictorVisualProfiles ?? []) {
    const feature = String(profile.feature ?? "").trim();
    const normalizedFeature = normalizedName(feature);
    if (
      !feature ||
      seen.has(normalizedFeature) ||
      !authorized.has(normalizedFeature) ||
      excluded.has(normalizedFeature) ||
      (governedMixedScope
        ? profile.scope !== "governed_mixed_scope" ||
          profile.descriptive_scope !== "full_governed_population" ||
          profile.target_directed_scope !== "development_population" ||
          Number(profile.target_directed_rows ?? 0) <= 0 ||
          profile.event_rate_shape?.scope !== "development_population" ||
          profile.event_rate_shape?.final_holdout_accessed !== false
        : profile.scope !== "full_dataset_aggregates" ||
          profile.event_rate_shape?.scope !== "full_dataset_aggregates") ||
      profile.missing?.semantics !== "null_only" ||
      profile.bureau_special?.missing_values_included !== false
    ) {
      continue;
    }
    if (
      profile.kind === "numeric" &&
      (!profile.ordinary_outlier ||
        profile.ordinary_outlier.semantics !== "regular_numeric_iqr_only" ||
        profile.ordinary_outlier.excludes_nulls !== true ||
        profile.ordinary_outlier.excludes_bureau_special_values !== true)
    ) {
      continue;
    }
    seen.add(normalizedFeature);
    const populationRows = Math.max(
      0,
      finite(profile.population_rows) ?? input.rowCount
    );
    const missingCount = Math.min(
      populationRows,
      Math.max(0, finite(profile.missing.count) ?? 0)
    );
    const specialValueCount = Math.min(
      Math.max(0, populationRows - missingCount),
      Math.max(0, finite(profile.bureau_special.count) ?? 0)
    );
    const inferredOrdinaryDenominator = Math.max(
      0,
      populationRows - missingCount - specialValueCount
    );
    const reportedOrdinaryDenominator = Math.max(
      0,
      finite(profile.ordinary_outlier?.denominator) ??
        inferredOrdinaryDenominator
    );
    if (
      profile.kind === "numeric" &&
      reportedOrdinaryDenominator !== inferredOrdinaryDenominator
    ) {
      continue;
    }
    const ordinaryOutlierDenominator =
      profile.kind === "numeric"
        ? reportedOrdinaryDenominator
        : inferredOrdinaryDenominator;
    const ordinaryOutlierCount =
      profile.kind === "numeric"
        ? Math.min(
            ordinaryOutlierDenominator,
            Math.max(0, finite(profile.ordinary_outlier?.count) ?? 0)
          )
        : 0;
    const ordinaryInlierCount = Math.max(
      0,
      ordinaryOutlierDenominator - ordinaryOutlierCount
    );
    const missingRate =
      boundedRate(profile.missing.rate) ??
      (populationRows > 0 ? missingCount / populationRows : 0);
    const specialValueRate =
      boundedRate(profile.bureau_special.prevalence) ??
      boundedRate(profile.metrics.special_prevalence) ??
      (populationRows > 0 ? specialValueCount / populationRows : 0);
    const outlierRate =
      profile.kind === "numeric"
        ? boundedRate(profile.ordinary_outlier?.rate) ??
          (ordinaryOutlierDenominator > 0
            ? ordinaryOutlierCount / ordinaryOutlierDenominator
            : null)
        : null;
    const ordinaryOutlierPopulationRate =
      populationRows > 0 ? ordinaryOutlierCount / populationRows : null;
    const ordinaryInlierPopulationRate =
      populationRows > 0 ? ordinaryInlierCount / populationRows : null;
    const distinctCount = Math.max(
      0,
      finite(profile.metrics.distinct_count) ?? 0
    );
    const distinctRatio =
      populationRows > 0 ? Math.min(1, distinctCount / populationRows) : 0;
    const bins = canonicalEventBins(profile);
    const iv = finite(profile.metrics.iv);
    const monotonicity = String(
      profile.metrics.monotonicity ?? "Not evaluated"
    );
    const skewness = finite(profile.metrics.skewness);
    const vif =
      vifByFeature.get(normalizedFeature) ?? finite(profile.metrics.vif);
    const base = {
      missingRate,
      specialValueRate,
      outlierRate,
      skewness,
      vif,
      monotonicity,
      distinctRatio,
      distinctCount,
    };
    result.push({
      feature,
      kind: profile.kind,
      count: Math.max(0, populationRows - missingCount),
      missingCount,
      missingRate,
      iv,
      correlation: null,
      signal: Math.abs(iv ?? 0),
      distinctCount,
      distinctRatio,
      outlierRate,
      ordinaryOutlierCount,
      ordinaryOutlierDenominator,
      ordinaryOutlierPopulationRate,
      ordinaryInlierPopulationRate,
      skewness,
      monotonicity,
      monotonicityScore: monotonicityScore(monotonicity),
      eventRateSpread: eventSpread(bins),
      eventRateBins: bins,
      vif,
      specialValueCount,
      specialValueRate,
      specialValueTreatment: canonicalTreatment(profile),
      specialValueDetails: canonicalDetails(profile),
      regularValueRate:
        populationRows > 0
          ? ordinaryOutlierDenominator / populationRows
          : null,
      reviewSignals: reviewSignalsFor(base),
    });
  }
  return result.slice(0, PREDICTOR_VISUAL_MAX_MARKS);
}

export function buildAuthorizedPredictorVisualData(
  input: PredictorVisualSuiteProps
): PredictorVisualDatum[] {
  const excluded = new Set(
    [
      input.target,
      ...(input.targetSourceExcluded ?? []),
      ...ALWAYS_EXCLUDED,
    ].map(normalizedName)
  );
  const authorized = new Set(
    input.authorizedPredictors
      .map((feature) => String(feature).trim())
      .filter((feature) => feature && !excluded.has(normalizedName(feature)))
      .map(normalizedName)
  );
  if (!authorized.size) return [];
  const canonicalRequested =
    input.predictorVisualProfiles !== undefined ||
    input.predictorVisualContract !== undefined;
  if (canonicalRequested) {
    if (
      input.predictorVisualContract?.profile_count !==
      input.predictorVisualProfiles?.length
    ) {
      return [];
    }
    return buildCanonicalRows(input, excluded, authorized);
  }

  const missingByFeature = new Map(
    (input.missingness ?? []).map((row) => [row.feature, row])
  );
  const vifByFeature = new Map(
    (input.vif ?? []).map((row) => [
      row.feature,
      finite(row.vif ?? row.value),
    ])
  );
  const specialByFeature = new Map(
    (input.specialValues ?? [])
      .map((row) => [specialFeature(row), row] as const)
      .filter(([feature]) => feature)
  );
  const seen = new Set<string>();
  const sourceRows = [
    ...(input.numericPredictors ?? []).map(
      (row) => [row, "numeric"] as const
    ),
    ...(input.categoricalPredictors ?? []).map(
      (row) => [row, "categorical"] as const
    ),
  ];

  const result: PredictorVisualDatum[] = [];
  for (const [row, kind] of sourceRows) {
    const feature = String(row.feature ?? "").trim();
    if (
      !feature ||
      seen.has(feature) ||
      !authorized.has(normalizedName(feature)) ||
      excluded.has(normalizedName(feature))
    ) {
      continue;
    }
    seen.add(feature);
    const missing = missingByFeature.get(feature);
    const special = specialByFeature.get(feature);
    const count = Math.max(0, finite(row.count) ?? 0);
    const missingCount = Math.max(
      0,
      finite(missing?.missing_count ?? row.missing_count) ?? 0
    );
    const missingRate =
      boundedRate(missing?.missing_rate ?? row.missing_rate) ??
      (input.rowCount > 0 ? Math.min(1, missingCount / input.rowCount) : 0);
    const iv = finite(row.iv);
    const correlation = finite(row.correlation_with_target);
    const distinctCount = Math.max(
      0,
      finite(row.distinct_count ?? row.cardinality) ?? 0
    );
    const distinctRatio =
      input.rowCount > 0
        ? Math.min(1, distinctCount / input.rowCount)
        : count > 0
          ? Math.min(1, distinctCount / count)
          : 0;
    const outlierRate = boundedRate(row.outlier_rate);
    const bins = eventBins(row);
    const specialValueCount =
      specialCount(special ?? {}) ??
      finite(row.special_value_count);
    const specialValueRate =
      specialRate(special ?? {}, input.rowCount) ??
      boundedRate(
        row.special_value_rate ?? row.special_value_frequency
      );
    const monotonicity = String(row.monotonicity ?? "Not evaluated");
    const skewness = finite(row.skewness);
    const vif = vifByFeature.get(feature) ?? null;
    const reviewSignals = reviewSignalsFor({
      missingRate,
      specialValueRate,
      outlierRate,
      skewness,
      vif,
      monotonicity,
      distinctRatio,
      distinctCount,
    });

    result.push({
      feature,
      kind,
      count,
      missingCount,
      missingRate,
      iv,
      correlation,
      signal: Math.abs(iv ?? correlation ?? 0),
      distinctCount,
      distinctRatio,
      outlierRate,
      ordinaryOutlierCount: null,
      ordinaryOutlierDenominator: null,
      ordinaryOutlierPopulationRate: null,
      ordinaryInlierPopulationRate: null,
      skewness,
      monotonicity,
      monotonicityScore: monotonicityScore(monotonicity),
      eventRateSpread: eventSpread(bins),
      eventRateBins: bins,
      vif,
      specialValueCount:
        specialValueCount === null ? null : Math.max(0, specialValueCount),
      specialValueRate,
      specialValueTreatment:
        special || row.special_value_treatment || row.recommended_treatment
          ? treatmentLabel(special) !== "Not documented"
            ? treatmentLabel(special)
            : String(
                row.special_value_treatment ??
                  row.recommended_treatment ??
                  "Not documented"
              )
          : "Not profiled",
      specialValueDetails: (special?.special_values ?? []).map((item) => ({
        value: String(item.value ?? ""),
        definition: String(item.definition ?? "Configured special value"),
        count: Math.max(0, finite(item.count) ?? 0),
        prevalence: boundedRate(item.frequency),
        eventRate: null,
      })),
      regularValueRate:
        specialValueRate === null
          ? null
          : Math.max(0, 1 - missingRate - specialValueRate),
      reviewSignals,
    });
  }
  return result.slice(0, PREDICTOR_VISUAL_MAX_MARKS);
}

export function metricValue(
  row: PredictorVisualDatum,
  metric: keyof Pick<
    PredictorVisualDatum,
    | "signal"
    | "eventRateSpread"
    | "missingRate"
    | "outlierRate"
    | "distinctRatio"
    | "skewness"
    | "monotonicityScore"
    | "vif"
    | "specialValueRate"
  >
) {
  return finite(row[metric]) ?? 0;
}

export function formatPredictorMetric(
  value: number | null,
  kind: "rate" | "number" | "score" = "number"
) {
  if (value === null || !Number.isFinite(value)) return "Not available";
  if (kind === "rate") {
    return value.toLocaleString(undefined, {
      style: "percent",
      maximumFractionDigits: 2,
    });
  }
  return value.toLocaleString(undefined, {
    maximumFractionDigits: kind === "score" ? 3 : 2,
  });
}

export function predictorCsv(
  rows: PredictorVisualDatum[],
  fields: Array<keyof PredictorVisualDatum>
) {
  const headers: Array<keyof PredictorVisualDatum> = [
    "feature",
    ...fields.filter((field) => field !== "feature"),
  ];
  const escape = (value: unknown) =>
    `"${String(value ?? "").replace(/"/g, '""')}"`;
  return [
    headers.map(escape).join(","),
    ...rows.map((row) =>
      headers
        .map((header) => {
          const value = row[header];
          return escape(Array.isArray(value) ? value.join("; ") : value);
        })
        .join(",")
    ),
  ].join("\n");
}

export function downloadPredictorCsv(filename: string, content: string) {
  if (typeof document === "undefined") return;
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/csv;charset=utf-8" })
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

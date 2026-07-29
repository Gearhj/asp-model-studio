export type PredictorEventRateBin = {
  bin?: string;
  label?: string;
  lower?: number | null;
  upper?: number | null;
  count?: number;
  events?: number;
  event_rate?: number | null;
};

export type PredictorAggregate = {
  feature: string;
  count?: number;
  missing_count?: number;
  missing_rate?: number | null;
  mean?: number | null;
  standard_deviation?: number | null;
  minimum?: number | null;
  q1?: number | null;
  median?: number | null;
  q3?: number | null;
  maximum?: number | null;
  skewness?: number | null;
  kurtosis?: number | null;
  distinct_count?: number;
  cardinality?: number;
  zero_rate?: number | null;
  outlier_rate?: number | null;
  iv?: number | null;
  correlation_with_target?: number | null;
  monotonicity?: string | null;
  event_rate_by_quantile?: PredictorEventRateBin[];
  top_levels?: Array<{
    level?: string;
    count?: number;
    rate?: number | null;
    event_rate?: number | null;
  }>;
  special_value_count?: number | null;
  special_value_rate?: number | null;
  special_value_frequency?: number | null;
  special_value_treatment?: string | null;
  recommended_treatment?: string | null;
};

export type PredictorMissingnessAggregate = {
  feature: string;
  missing_count?: number;
  missing_rate?: number | null;
  present_event_rate?: number | null;
  missing_event_rate?: number | null;
  informative_missingness?: boolean;
};

export type PredictorVifAggregate = {
  feature: string;
  vif?: number | null;
  value?: number | null;
};

export type PredictorSpecialValueAggregate = {
  feature?: string;
  variable?: string;
  special_value_count?: number | null;
  specialValueCount?: number | null;
  special_value_rate?: number | null;
  specialValueRate?: number | null;
  special_value_frequency?: number | null;
  countMinus7?: number | null;
  countMinus8?: number | null;
  countMinus9?: number | null;
  recommended_treatment?: string | null;
  recommendedTreatment?: string | null;
  treatment_state?: string | null;
  special_values?: Array<{
    value?: number;
    count?: number;
    frequency?: number;
    definition?: string;
    recommended_handling?: string;
  }>;
};

export type PredictorVisualProfile = {
  feature: string;
  kind: "numeric" | "categorical";
  scope: "full_dataset_aggregates";
  population_rows: number;
  metrics: {
    iv?: number | null;
    missing_rate?: number | null;
    outlier_count?: number | null;
    outlier_rate?: number | null;
    distinct_count?: number | null;
    skewness?: number | null;
    monotonicity?: string | null;
    vif?: number | null;
    vif_status?: string | null;
    special_prevalence?: number | null;
  };
  ordinary_outlier?: {
    count: number;
    rate?: number | null;
    denominator: number;
    excludes_nulls: true;
    excludes_bureau_special_values: true;
    semantics: "regular_numeric_iqr_only";
  };
  missing: {
    count: number;
    rate?: number | null;
    event_rate?: number | null;
    semantics: "null_only";
  };
  bureau_special: {
    identified?: boolean;
    count: number;
    prevalence?: number | null;
    regular_numeric_count?: number;
    regular_event_rate?: number | null;
    values?: Array<{
      value?: number | string;
      definition?: string;
      count?: number;
      prevalence?: number | null;
      event_rate?: number | null;
    }>;
    identification_basis?: string[];
    missing_values_included: false;
  };
  event_rate_shape: {
    kind: "quantile" | "top_levels";
    scope: "full_dataset_aggregates";
    limit: number;
    groups: Array<{
      label: string;
      count: number;
      population_rate?: number | null;
      event_rate?: number | null;
      minimum?: number | null;
      maximum?: number | null;
      event_count?: number;
    }>;
    returned_groups: number;
    truncated: boolean;
    raw_observations_included: false;
  };
};

export type PredictorVisualContract = {
  version: string;
  request_mode: "single_batched_workspace_request";
  scope: "full_dataset_aggregates";
  profile_count: number;
  event_rate_shape_limit: number;
  raw_observations_included: false;
  server_authorized_predictors_only: true;
  target_excluded: true;
  target_source_exclusions_disclosed_at_response_root: true;
  non_overlapping_quality_buckets: string[];
  additional_vif_computation: false;
  vif_status: string;
  documentation_identity_excludes?: string[];
  profile_duration_ms?: number;
};

/**
 * One already-loaded, server-authorized aggregate bundle feeds every visual.
 * The suite never performs a per-predictor request.
 */
export type PredictorVisualSuiteProps = {
  predictorVisualProfiles?: PredictorVisualProfile[];
  predictorVisualContract?: PredictorVisualContract | null;
  numericPredictors?: PredictorAggregate[];
  categoricalPredictors?: PredictorAggregate[];
  missingness?: PredictorMissingnessAggregate[];
  vif?: PredictorVifAggregate[];
  specialValues?: PredictorSpecialValueAggregate[];
  authorizedPredictors: string[];
  target: string;
  targetSourceExcluded?: string[];
  rowCount: number;
  populationEventRate?: number | null;
  datasetVersion?: string;
  className?: string;
};

export type PredictorVisualDatum = {
  feature: string;
  kind: "numeric" | "categorical";
  count: number;
  missingCount: number;
  missingRate: number;
  iv: number | null;
  correlation: number | null;
  signal: number;
  distinctCount: number;
  distinctRatio: number;
  outlierRate: number | null;
  ordinaryOutlierCount: number | null;
  ordinaryOutlierDenominator: number | null;
  ordinaryOutlierPopulationRate: number | null;
  ordinaryInlierPopulationRate: number | null;
  skewness: number | null;
  monotonicity: string;
  monotonicityScore: number;
  eventRateSpread: number | null;
  eventRateBins: Array<{
    label: string;
    count: number;
    eventRate: number | null;
  }>;
  vif: number | null;
  specialValueCount: number | null;
  specialValueRate: number | null;
  specialValueTreatment: string;
  specialValueDetails: Array<{
    value: string;
    definition: string;
    count: number;
    prevalence: number | null;
    eventRate: number | null;
  }>;
  regularValueRate: number | null;
  reviewSignals: string[];
};

export type PredictorLandscapeMetric =
  | "signal"
  | "eventRateSpread"
  | "missingRate"
  | "outlierRate"
  | "distinctRatio"
  | "skewness"
  | "monotonicityScore"
  | "vif"
  | "specialValueRate";

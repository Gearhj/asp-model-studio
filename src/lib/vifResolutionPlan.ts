export type VifResolutionAction = "retain" | "exclude" | "combine" | "defer";
export type VifResolutionDecision =
  | "accept_complete"
  | "accept_selected"
  | "modify"
  | "reject"
  | "defer"
  | "send_to_feature_engineering";

export type VifPreferenceWeights = {
  signal: number;
  interpretability: number;
  data_quality: number;
  special_value_burden: number;
  production_availability: number;
};

export type VifResolutionInputs = {
  intendedModelFamily:
    | "linear_scorecard"
    | "generalized_linear"
    | "tree_ensemble"
    | "neural_network"
    | "mixed_bench";
  targetVifThreshold: number;
  resolutionObjective:
    | "balanced"
    | "minimize_exclusions"
    | "reduce_max_vif"
    | "preserve_signal"
    | "maximize_interpretability";
  protectedPredictors: string[];
  allowedActions: VifResolutionAction[];
  correlationThreshold: number;
  preferenceWeights: VifPreferenceWeights;
  maximumRemovals: number;
};

export type VifPlanSummary = {
  predictor_count: number;
  maximum_vif: number | null;
  count_above_5: number;
  count_above_10: number;
  vif?: Array<{ feature: string; vif: number | null; status?: string }>;
};

export type VifDelta = {
  feature: string;
  current_vif: number | null;
  proposed_vif: number | null;
  delta: number | null;
  proposed_action: VifResolutionAction;
};

export type VifTie = {
  cluster_id: string;
  features: string[];
  equivalent_maximum_vif: number | null;
  message: string;
  required_tie_breakers: string[];
};

export type VifClusterRecommendation = {
  cluster_id: string;
  features: string[];
  maximum_correlation: number;
  recommended_action: VifResolutionAction;
  proposed_exclusions: string[];
  protected_features: string[];
  tie_case?: VifTie | null;
  rationale: string;
};

export type VifResolutionPlan = {
  ok: boolean;
  plan_id: string;
  plan_hash: string;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  status: string;
  current: VifPlanSummary;
  proposed: VifPlanSummary & {
    illustrative_path: string[];
    target_vif_threshold: number;
    threshold_met: boolean;
  };
  calculation_count: {
    governed_feature_set_calculations: number;
    simulated_complete_vif_recalculations: number;
    total_complete_vif_calculations: number;
    governed_predictor_count: number;
    simulated_proposed_predictor_count: number;
  };
  per_feature_vif_deltas: VifDelta[];
  clusters: VifClusterRecommendation[];
  alternatives: Array<{
    path: string[];
    maximum_vif: number | null;
    count_above_5: number;
    count_above_10: number;
    predictor_count: number;
    score: number;
  }>;
  ties: VifTie[];
  protected_predictors: string[];
  proposed_exclusions: Array<{
    feature: string;
    status: string;
    cluster_id?: string | null;
  }>;
  proposed_combinations: Array<{
    cluster_id: string;
    source_features: string[];
    status: string;
    rationale: string;
  }>;
  remaining_unresolved_clusters: Array<{
    cluster_id: string;
    features: string[];
    reason: string;
  }>;
  retained_profile: Record<string, number | null>;
  model_family: {
    id: string;
    label: string;
    recommended_posture: string;
    implication: string;
  };
  analysis_scope: {
    development_population: string;
    development_rows: number;
    sealed_final_holdout_rows_excluded: number;
    target_informed_evidence: string;
    final_holdout_accessed: boolean;
    final_holdout_used_for_selection: boolean;
  };
  governed_feature_set_changed: false;
  dataset_mutated: false;
  explicit_statement: string;
};

export type VifResolutionDecisionRequest = {
  planId: string;
  action: VifResolutionDecision;
  selectedClusterIds?: string[];
  rationale?: string;
  modifications?: Record<string, unknown>;
};

export const DEFAULT_VIF_RESOLUTION_INPUTS: VifResolutionInputs = {
  intendedModelFamily: "linear_scorecard",
  targetVifThreshold: 10,
  resolutionObjective: "balanced",
  protectedPredictors: [],
  allowedActions: ["retain", "exclude", "combine", "defer"],
  correlationThreshold: 0.85,
  preferenceWeights: {
    signal: 1,
    interpretability: 1,
    data_quality: 1,
    special_value_burden: 1,
    production_availability: 1,
  },
  maximumRemovals: 2,
};

function finite(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function normalizeVifResolutionPlan(value: unknown): VifResolutionPlan {
  if (!value || typeof value !== "object") {
    throw new Error("The backend did not return a VIF resolution plan.");
  }
  const plan = value as VifResolutionPlan;
  if (!plan.ok || !plan.plan_id || !plan.current || !plan.proposed) {
    throw new Error("The backend returned an incomplete VIF resolution plan.");
  }
  if (plan.governed_feature_set_changed !== false || plan.dataset_mutated !== false) {
    throw new Error("The VIF planning endpoint violated its non-mutation contract.");
  }
  return {
    ...plan,
    current: {
      ...plan.current,
      maximum_vif: finite(plan.current.maximum_vif),
    },
    proposed: {
      ...plan.proposed,
      maximum_vif: finite(plan.proposed.maximum_vif),
    },
    per_feature_vif_deltas: Array.isArray(plan.per_feature_vif_deltas)
      ? plan.per_feature_vif_deltas
      : [],
    clusters: Array.isArray(plan.clusters) ? plan.clusters : [],
    alternatives: Array.isArray(plan.alternatives) ? plan.alternatives : [],
    ties: Array.isArray(plan.ties) ? plan.ties : [],
    protected_predictors: Array.isArray(plan.protected_predictors)
      ? plan.protected_predictors
      : [],
    proposed_exclusions: Array.isArray(plan.proposed_exclusions)
      ? plan.proposed_exclusions
      : [],
    proposed_combinations: Array.isArray(plan.proposed_combinations)
      ? plan.proposed_combinations
      : [],
    remaining_unresolved_clusters: Array.isArray(
      plan.remaining_unresolved_clusters,
    )
      ? plan.remaining_unresolved_clusters
      : [],
  };
}

export function vifComparisonChartRows(plan: VifResolutionPlan) {
  return plan.per_feature_vif_deltas
    .filter((row) => row.current_vif !== null || row.proposed_vif !== null)
    .sort(
      (left, right) =>
        (right.current_vif ?? -1) - (left.current_vif ?? -1) ||
        left.feature.localeCompare(right.feature),
    );
}

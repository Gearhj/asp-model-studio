import type { FeatureDraft, FeatureOrigin } from "./featureManifest";

export type RecommendationClass =
  | "deterministic"
  | "statistical"
  | "exploratory";

export type FeatureRecommendation = {
  id: string;
  featureName: string;
  transformationType: FeatureOrigin;
  recommendationClass: RecommendationClass;
  formula: string;
  sourceFeatures: string[];
  rationale: string;
  evidenceMetrics: string[];
  expectedBenefit: string;
  risks: string[];
  leakageAssessment: string;
  interpretability: "high" | "medium" | "low";
  complexity: "low" | "medium" | "high";
  validationRequirement: string;
  outputDatatype: string;
  config: Record<string, unknown>;
  eligible: boolean;
  blockedReason: string;
};

export type FeatureRecommendationInput = {
  availableFeatures: string[];
  excludedFeatures?: Record<string, string>;
  existingFeatureNames?: string[];
  evidenceByFeature?: Record<
    string,
    { iv?: number | null; outlierRate?: number | null; monotonicity?: string | null }
  >;
};

type Candidate = Omit<
  FeatureRecommendation,
  "sourceFeatures" | "formula" | "eligible" | "blockedReason" | "evidenceMetrics"
> & {
  sources: string[];
  formulaFor: (sources: string[]) => string;
};

const CANDIDATES: Candidate[] = [
  {
    id: "non-satisfactory-trade-count",
    featureName: "non_satisfactory_trade_count",
    transformationType: "arithmetic",
    recommendationClass: "deterministic",
    sources: ["NumTotalTrades", "NumSatisfactoryTrades"],
    formulaFor: ([total, satisfactory]) => `${total} - ${satisfactory}`,
    rationale:
      "Makes the complement of satisfactory trade history explicit while preserving an auditable count identity.",
    expectedBenefit:
      "May give linear and scorecard-style models a direct, interpretable burden measure.",
    risks: [
      "Negative results indicate a source-quality or definition mismatch.",
      "The derived count may be redundant with its two inputs.",
    ],
    leakageAssessment:
      "Uses only governed bureau predictors; target and deterministic target source are excluded.",
    interpretability: "high",
    complexity: "low",
    validationRequirement:
      "Confirm the result is nonnegative and reconcile NumTotalTrades >= NumSatisfactoryTrades.",
    outputDatatype: "numeric",
    config: {
      operation: "subtract",
      unit_contract: "count_minus_count",
      preserve_bureau_special_values: true,
    },
  },
  {
    id: "external-risk-band",
    featureName: "external_risk_band",
    transformationType: "numeric_bin",
    recommendationClass: "statistical",
    sources: ["ExternalRiskEstimate"],
    formulaFor: ([risk]) => `quantile_band(${risk}; 20%, 40%, 60%, 80%)`,
    rationale:
      "Creates a coarse risk band for nonlinearity review without claiming an optimized cutoff.",
    expectedBenefit:
      "May make nonlinear response patterns easier to inspect and communicate.",
    risks: [
      "Quantile cut points are dataset-version specific.",
      "Binning can discard within-band variation.",
    ],
    leakageAssessment:
      "Target-free quantiles only; cut points remain versioned to the governed dataset.",
    interpretability: "high",
    complexity: "medium",
    validationRequirement:
      "Review band population, event-rate ordering, special-value handling, and out-of-sample stability.",
    outputDatatype: "categorical",
    config: {
      binning_mode: "quantile",
      quantiles: [0.2, 0.4, 0.6, 0.8],
      labels: ["Very low", "Low", "Mid", "High", "Very high"],
      missing_label: "Special or missing",
      preserve_bureau_special_values: true,
    },
  },
  {
    id: "high-revolving-burden-flag",
    featureName: "high_revolving_burden_flag",
    transformationType: "categorical_rule",
    recommendationClass: "deterministic",
    sources: ["NetFractionRevolvingBurden"],
    formulaFor: ([burden]) => `${burden} > 80`,
    rationale:
      "Expresses a transparent high-utilization review threshold as a binary indicator.",
    expectedBenefit:
      "May expose a threshold effect while remaining easy to challenge and explain.",
    risks: [
      "The 80 threshold is a review starting point, not an optimized cutoff.",
      "Special bureau values must remain separate from ordinary percentages.",
    ],
    leakageAssessment:
      "Uses one governed pre-outcome predictor and no target-derived statistics.",
    interpretability: "high",
    complexity: "low",
    validationRequirement:
      "Confirm the measurement scale, special-value policy, prevalence, and event-rate separation.",
    outputDatatype: "categorical",
    config: {
      rules: [{ op: "greater_than", value: 80, then_label: "High" }],
      else_label: "Not high",
      preserve_bureau_special_values: true,
    },
  },
  {
    id: "average-months-in-file-squared",
    featureName: "average_months_in_file_squared",
    transformationType: "polynomial",
    recommendationClass: "deterministic",
    sources: ["AverageMInFile"],
    formulaFor: ([months]) => `${months} ^ 2`,
    rationale:
      "Provides a simple curvature term for a duration variable without treating duration as a calendar date.",
    expectedBenefit:
      "May help linear models represent smooth nonlinearity in credit-file age.",
    risks: [
      "Squaring magnifies scale and collinearity.",
      "Tree models may not need the extra term.",
    ],
    leakageAssessment:
      "Uses one governed duration predictor; it is explicitly not a date derivation.",
    interpretability: "medium",
    complexity: "low",
    validationRequirement:
      "Center or scale in the training-only pipeline when appropriate and review VIF.",
    outputDatatype: "numeric",
    config: {
      degree: 2,
      semantic_type: "duration_not_date",
      preserve_bureau_special_values: true,
    },
  },
  {
    id: "delinquency-severity-composite",
    featureName: "delinquency_severity_composite",
    transformationType: "arithmetic",
    recommendationClass: "deterministic",
    sources: ["NumTrades60Ever2DerogPubRec", "NumTrades90Ever2DerogPubRec"],
    formulaFor: ([sixty, ninety]) => `${sixty} + ${ninety}`,
    rationale:
      "Combines two same-unit delinquency counts into a conservative severity review measure.",
    expectedBenefit:
      "May reduce fragmentation across closely related delinquency counts.",
    risks: [
      "Simple addition does not establish an optimal severity weighting.",
      "The composite can remain redundant with its source counts.",
    ],
    leakageAssessment:
      "Uses governed historical delinquency predictors only.",
    interpretability: "high",
    complexity: "low",
    validationRequirement:
      "Review component definitions, distribution, VIF, and whether both source counts should remain selected.",
    outputDatatype: "numeric",
    config: {
      operation: "add",
      unit_contract: "count_plus_count",
      preserve_bureau_special_values: true,
    },
  },
  {
    id: "inquiry-window-difference",
    featureName: "inquiry_window_difference",
    transformationType: "arithmetic",
    recommendationClass: "deterministic",
    sources: ["NumInqLast6M", "NumInqLast6Mexcl7days"],
    formulaFor: ([all, excluding]) => `${all} - ${excluding}`,
    rationale:
      "Isolates inquiries attributable to the most recent seven-day window through an auditable identity.",
    expectedBenefit:
      "May distinguish very recent inquiry activity from the broader six-month count.",
    risks: [
      "Negative values indicate inconsistent source definitions or data quality.",
      "The feature may be sparse.",
    ],
    leakageAssessment:
      "Uses governed application-time inquiry counts only.",
    interpretability: "high",
    complexity: "low",
    validationRequirement:
      "Require nonnegative values and reconcile the two inquiry-window definitions.",
    outputDatatype: "numeric",
    config: {
      operation: "subtract",
      unit_contract: "count_minus_count",
      preserve_bureau_special_values: true,
    },
  },
  {
    id: "external-risk-delinquency-interaction",
    featureName: "external_risk_x_never_delinquent",
    transformationType: "interaction",
    recommendationClass: "exploratory",
    sources: ["ExternalRiskEstimate", "PercentTradesNeverDelq"],
    formulaFor: ([risk, neverDelq]) => `${risk} * ${neverDelq}`,
    rationale:
      "Tests whether external risk and clean trade history jointly describe a pattern not captured by either alone.",
    expectedBenefit:
      "Provides an explicit interaction for challenger linear models; no performance gain is assumed.",
    risks: [
      "The product has a less intuitive scale.",
      "It may be highly collinear with its inputs and unnecessary for tree models.",
    ],
    leakageAssessment:
      "Uses two governed pre-outcome predictors; recommendation remains exploratory.",
    interpretability: "medium",
    complexity: "medium",
    validationRequirement:
      "Compare with main-effects-only models, review VIF, and confirm stability on validation data.",
    outputDatatype: "numeric",
    config: {
      interaction_order: 2,
      preserve_bureau_special_values: true,
    },
  },
];

function resolveFeature(available: string[], requested: string) {
  return (
    available.find(
      (name) => name.toLowerCase() === requested.toLowerCase(),
    ) ?? ""
  );
}

function evidenceMetrics(
  sources: string[],
  evidence: FeatureRecommendationInput["evidenceByFeature"],
) {
  const rows: string[] = [];
  sources.forEach((source) => {
    const metric =
      evidence?.[source] ??
      Object.entries(evidence ?? {}).find(
        ([name]) => name.toLowerCase() === source.toLowerCase(),
      )?.[1];
    if (!metric) return;
    if (typeof metric.iv === "number") rows.push(`${source} IV ${metric.iv.toFixed(3)}`);
    if (typeof metric.outlierRate === "number") {
      rows.push(`${source} outlier rate ${(metric.outlierRate * 100).toFixed(2)}%`);
    }
    if (metric.monotonicity) rows.push(`${source} ${metric.monotonicity}`);
  });
  return rows.length ? rows : ["Governed source availability confirmed; validate empirical behavior before acceptance."];
}

export function buildFeatureRecommendations({
  availableFeatures,
  excludedFeatures = {},
  existingFeatureNames = [],
  evidenceByFeature = {},
}: FeatureRecommendationInput): FeatureRecommendation[] {
  const existing = new Set(existingFeatureNames.map((name) => name.toLowerCase()));
  const excluded = new Map(
    Object.entries(excludedFeatures).map(([name, reason]) => [
      name.toLowerCase(),
      reason,
    ]),
  );
  return CANDIDATES.map((candidate) => {
    const resolved = candidate.sources.map((source) =>
      resolveFeature(availableFeatures, source),
    );
    const missing = candidate.sources.filter((_, index) => !resolved[index]);
    const excludedSources = candidate.sources.filter((source) =>
      excluded.has(source.toLowerCase()),
    );
    let blockedReason = "";
    if (existing.has(candidate.featureName.toLowerCase())) {
      blockedReason = "A feature with this name already exists in the governed manifest.";
    } else if (excludedSources.length) {
      blockedReason = excludedSources
        .map((source) => `${source}: ${excluded.get(source.toLowerCase())}`)
        .join("; ");
    } else if (missing.length) {
      blockedReason = `Unavailable governed source${missing.length === 1 ? "" : "s"}: ${missing.join(", ")}.`;
    }
    const sources = resolved.map((source, index) => source || candidate.sources[index]);
    return {
      ...candidate,
      sourceFeatures: sources,
      formula: candidate.formulaFor(sources),
      evidenceMetrics: evidenceMetrics(sources, evidenceByFeature),
      eligible: !blockedReason,
      blockedReason,
    };
  });
}

export function recommendationToFeatureDraft(
  recommendation: FeatureRecommendation,
): FeatureDraft {
  if (!recommendation.eligible) {
    throw new Error(
      recommendation.blockedReason ||
        "This recommendation is not eligible for the governed feature plan.",
    );
  }
  return {
    feature_name: recommendation.featureName,
    display_name: recommendation.featureName,
    origin: recommendation.transformationType,
    source_features: recommendation.sourceFeatures,
    transformation_type: recommendation.transformationType,
    formula_or_rule: recommendation.formula,
    output_datatype: recommendation.outputDatatype,
    selected: true,
    exclusion_reason: "",
    user_rationale: recommendation.rationale,
    config: {
      ...recommendation.config,
      recommendation_id: recommendation.id,
      recommendation_class: recommendation.recommendationClass,
      recommendation_only: false,
      expected_benefit_statement: recommendation.expectedBenefit,
      validation_requirement: recommendation.validationRequirement,
      leakage_assessment: recommendation.leakageAssessment,
    },
  };
}

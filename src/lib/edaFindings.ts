export const EDA_FINDING_CATEGORIES = [
  "Data quality",
  "Target",
  "Predictors",
  "Relationships",
  "Stability",
  "Documentation",
] as const;

export const EDA_FINDING_SEVERITIES = [
  "high",
  "moderate",
  "info",
] as const;

export const EDA_CARRY_FORWARD_DESTINATIONS = [
  "Outliers",
  "Missing Values",
  "Feature Engineering",
  "Balance and Split",
  "Model Training",
  "Documentation",
  "Validation",
] as const;

export const EDA_TRANSFORMATION_OPTIONS = [
  "Log transform",
  "Winsorization",
  "Binning",
  "Special-value separation",
  "Categorical conversion",
  "No transformation",
  "Investigate further",
] as const;

export type EdaFindingCategory = (typeof EDA_FINDING_CATEGORIES)[number];
export type EdaFindingSeverity = (typeof EDA_FINDING_SEVERITIES)[number];
export type EdaCarryForwardDestination =
  (typeof EDA_CARRY_FORWARD_DESTINATIONS)[number];
export type EdaTransformationOption =
  (typeof EDA_TRANSFORMATION_OPTIONS)[number];
export const EDA_FINDING_DISPOSITIONS = [
  "unresolved",
  "accepted",
  "rejected",
  "deferred",
  "documented",
  "no_action_required",
  "not_applicable",
] as const;

export type EdaFindingDisposition =
  (typeof EDA_FINDING_DISPOSITIONS)[number];

export type EdaOverallReviewStatus =
  | "draft"
  | "under_review"
  | "accepted"
  | "accepted_with_conditions"
  | "rejected"
  // Compare-only compatibility value for browser snapshots created before
  // the governed parent-finding contract was introduced.
  | "reviewed";

export type EdaDuplicateResolutionAction =
  | "unresolved"
  | "retain_current_population"
  | "exclude_upstream_and_repartition";

export type EdaFindingDecision = {
  disposition: EdaFindingDisposition;
  rationale: string;
  destination: EdaCarryForwardDestination | "";
  transformation: EdaTransformationOption;
  resolutionAction?: EdaDuplicateResolutionAction;
  updatedAt?: string;
};

export type EdaBulkDispositionAudit = {
  actionId: string;
  family: string;
  parentIds: string[];
  childIds: string[];
  priorStatuses: Record<string, EdaFindingDisposition>;
  newStatus: EdaFindingDisposition;
  rationale: string;
  destination: EdaCarryForwardDestination | "";
  actor: string;
  timestamp: string;
};

export type EdaFindingsReviewState = {
  commentary: string;
  status: EdaOverallReviewStatus;
  savedAt?: string;
  duplicateTreatment?: "review" | "exclude" | "keep";
  duplicateDecisionSavedAt?: string;
  overallConclusion?: string;
  findingDecisions?: Record<string, EdaFindingDecision>;
  parentDecisions?: Record<string, EdaFindingDecision>;
  bulkDispositionAudit?: EdaBulkDispositionAudit[];
  requiredConditions?: string[];
  openNonblockingItems?: string[];
  reviewerDraftGeneratedAt?: string;
  reviewerDraftNonApproving?: true;
};

export type EdaFinding = {
  id: string;
  title: string;
  category: EdaFindingCategory;
  severity: EdaFindingSeverity;
  affectedVariables: string[];
  analyticalBasis: string;
  metricLabel: string;
  metricValue: string;
  recommendedAction: string;
  downstreamDestination: EdaCarryForwardDestination;
  suggestedTransformations: EdaTransformationOption[];
  evidenceReferences: string[];
  documentationImpact: string;
  status: "open";
  importance: number;
  iv?: number | null;
  eventRateShape?: string;
  monotonicity?: string;
  targetSourceStatus?: "excluded" | "not_target_source" | "review";
  leakageEvidence?: string;
};

export type EdaFindingSections = Partial<
  Record<
    | "overview"
    | "target"
    | "predictors"
    | "relationships"
    | "stability"
    | "findings",
    Record<string, any>
  >
>;

const HIGH_IV_REVIEW_THRESHOLD = 0.5;
const MATERIAL_MISSINGNESS_THRESHOLD = 0.1;
const MATERIAL_OUTLIER_THRESHOLD = 0.05;
const MATERIAL_SPECIAL_VALUE_THRESHOLD = 0.05;
const MATERIAL_SKEWNESS_THRESHOLD = 2;
const HIGH_CORRELATION_THRESHOLD = 0.7;
const VIF_REVIEW_THRESHOLD = 5;

function rows(value: unknown): Array<Record<string, any>> {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, any> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => String(item ?? "").trim()).filter(Boolean)
    : [];
}

function finite(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function count(value: unknown): number {
  return Math.max(0, Math.trunc(finite(value) ?? 0));
}

function percent(value: number | null, digits = 1): string {
  if (value === null) return "Not available";
  return `${(value * 100).toLocaleString(undefined, {
    maximumFractionDigits: digits,
  })}%`;
}

function number(value: number | null, digits = 2): string {
  if (value === null) return "Not available";
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function stableId(parts: Array<string | number | null | undefined>): string {
  const source = parts
    .map((part) => String(part ?? "").trim().toLowerCase())
    .join("|");
  let hash = 2166136261;
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `eda-finding-${(hash >>> 0).toString(36)}`;
}

function eventShapeLabel(profile: Record<string, any>): string {
  const shape = profile.event_rate_shape ?? {};
  const groups = rows(shape.groups);
  const rates = groups
    .map((row) => finite(row.event_rate))
    .filter((value): value is number => value !== null);
  if (!rates.length) return "Not available";
  const minimum = Math.min(...rates);
  const maximum = Math.max(...rates);
  return `${groups.length} governed groups; ${percent(minimum)}–${percent(maximum)} event rate`;
}

function severityWeight(severity: EdaFindingSeverity): number {
  return severity === "high" ? 300 : severity === "moderate" ? 200 : 100;
}

function finding(
  input: Omit<EdaFinding, "id" | "status" | "importance"> & {
    identity?: Array<string | number | null | undefined>;
    importance?: number;
  },
): EdaFinding {
  const {
    identity,
    importance,
    ...rest
  } = input;
  return {
    ...rest,
    id: stableId(
      identity ?? [
        rest.category,
        rest.title,
        rest.affectedVariables.join(","),
        rest.metricLabel,
      ],
    ),
    status: "open",
    importance: severityWeight(rest.severity) + (importance ?? 0),
  };
}

function normalizeMonotonicity(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
}

function targetSourceExclusions(sections: EdaFindingSections): string[] {
  const overview = sections.overview ?? {};
  return strings(
    overview.target_source_excluded ??
      overview.predictor_authorization?.target_source_excluded,
  ).sort();
}

function governedPredictorArtifacts(
  sections: EdaFindingSections,
): Record<string, Record<string, any>> {
  const value =
    sections.predictors?.governed_predictor_artifacts ??
    sections.target?.governed_predictor_artifacts ??
    sections.overview?.governed_predictor_artifacts ??
    sections.overview?.governed_analytical_contract?.predictor_artifacts;
  return value && typeof value === "object" && !Array.isArray(value)
    ? value
    : {};
}

function governedTargetArtifact(
  sections: EdaFindingSections,
): Record<string, any> | null {
  const value =
    sections.target?.governed_target_artifact ??
    sections.predictors?.governed_target_artifact ??
    sections.overview?.governed_target_artifact ??
    sections.overview?.governed_analytical_contract?.target_artifact;
  return value && typeof value === "object" && !Array.isArray(value)
    ? value
    : null;
}

function governedRelationshipArtifact(
  sections: EdaFindingSections,
): Record<string, any> | null {
  const value =
    sections.relationships?.governed_relationship_artifact ??
    sections.predictors?.governed_relationship_artifact ??
    sections.overview?.governed_relationship_artifact ??
    sections.overview?.governed_analytical_contract?.relationship_artifact;
  return value && typeof value === "object" && !Array.isArray(value)
    ? value
    : null;
}

function addGovernedDataQualityFindings(
  output: EdaFinding[],
  sections: EdaFindingSections,
) {
  const duplicateRow = rows(sections.findings?.findings).find((row) =>
    String(row.finding ?? "").toLowerCase().includes("duplicate rows"),
  );
  if (!duplicateRow) return;
  const duplicateCount = count(
    duplicateRow.metric_value ??
      String(duplicateRow.finding ?? "").match(/[\d,]+/)?.[0]?.replace(/,/g, ""),
  );
  output.push(
    finding({
      title: "Exact duplicate rows require a governed treatment decision",
      category: "Data quality",
      severity: "high",
      affectedVariables: [],
      analyticalBasis:
        "The development population contains rows that are exact duplicates across the governed analysis frame.",
      metricLabel: "Duplicate rows",
      metricValue: duplicateCount.toLocaleString(),
      recommendedAction:
        "Confirm whether these are ingestion duplicates or valid repeated observations; record exclusion or retention without mutating data from EDA.",
      downstreamDestination: "Feature Engineering",
      suggestedTransformations: ["No transformation", "Investigate further"],
      evidenceReferences: ["findings.findings.exact_duplicate_rows"],
      documentationImpact:
        "The reviewer decision and rationale enter the EDA decision history and downstream queue.",
      importance: Math.min(duplicateCount, 99),
    }),
  );
}

function addGovernedTargetFindings(
  output: EdaFinding[],
  sections: EdaFindingSections,
) {
  const artifact = governedTargetArtifact(sections);
  if (artifact) {
    const targetName = String(artifact.target ?? sections.overview?.target ?? "target");
    const eventRate = finite(artifact.event_rate);
    if (artifact.problem_type === "classification" && eventRate !== null) {
      const rare = eventRate < 0.01;
      const imbalanced = eventRate < 0.1 || eventRate > 0.9;
      output.push(
        finding({
          title: rare
            ? `${targetName} has a rare observed event`
            : imbalanced
              ? `${targetName} has a materially imbalanced class distribution`
              : `${targetName} class balance is measurable`,
          category: "Target",
          severity: rare ? "high" : imbalanced ? "moderate" : "info",
          affectedVariables: [targetName],
          analyticalBasis:
            "Event prevalence is computed only over non-missing target-bearing rows in the governed development population.",
          metricLabel: "Event rate",
          metricValue: `${percent(eventRate)} (${count(
            artifact.event_count,
          ).toLocaleString()} events / ${count(
            artifact.valid_count,
          ).toLocaleString()} target-bearing rows)`,
          recommendedAction: rare
            ? "Use stratified splitting and ranking, lift, calibration, and threshold metrics; do not rely on accuracy alone."
            : "Carry the observed prevalence into split design and model evaluation.",
          downstreamDestination: "Balance and Split",
          suggestedTransformations: ["No transformation"],
          evidenceReferences: ["target.governed_target_artifact.event_rate"],
          documentationImpact:
            "Development class balance and the selected evaluation implications enter the target narrative.",
        }),
      );
    }
    const missingTarget = count(artifact.missing_count);
    if (missingTarget > 0) {
      output.push(
        finding({
          title: "The target contains missing values",
          category: "Target",
          severity: "high",
          affectedVariables: [targetName],
          analyticalBasis:
            "The governed development target artifact contains missing target values.",
          metricLabel: "Missing target values",
          metricValue: missingTarget.toLocaleString(),
          recommendedAction:
            "Resolve the target-quality concern before training and preserve the reviewer rationale in documentation.",
          downstreamDestination: "Validation",
          suggestedTransformations: ["Investigate further"],
          evidenceReferences: ["target.governed_target_artifact.missing_count"],
          documentationImpact:
            "The accepted disposition enters target-quality evidence and validation carry-forward.",
        }),
      );
    }
  }

  const exclusions = targetSourceExclusions(sections);
  if (exclusions.length) {
    output.push(
      finding({
        title: "Deterministic target-source fields remain excluded",
        category: "Target",
        severity: "info",
        affectedVariables: exclusions,
        analyticalBasis:
          "Server predictor authorization identifies deterministic target sources separately from model-eligible predictors.",
        metricLabel: "Excluded target-source fields",
        metricValue: exclusions.join(", "),
        recommendedAction:
          "Retain the governed exclusion. Review evidence if upstream lineage changes; do not reintroduce these fields from EDA.",
        downstreamDestination: "Documentation",
        suggestedTransformations: ["No transformation"],
        evidenceReferences: [
          "overview.predictor_authorization.target_source_excluded",
        ],
        documentationImpact:
          "The exclusion is disclosed in target lineage, predictor authorization, and the approved EDA record.",
        targetSourceStatus: "excluded",
        leakageEvidence:
          "Deterministic source relationship documented by governed target lineage.",
        importance: 20,
      }),
    );
  }
}

function addGovernedPredictorFindings(
  output: EdaFinding[],
  sections: EdaFindingSections,
) {
  const artifacts = governedPredictorArtifacts(sections);
  for (const feature of Object.keys(artifacts).sort()) {
    const artifact = artifacts[feature] ?? {};
    const iv = finite(artifact.iv);
    const monotonicity = String(
      artifact.monotonicity?.valid_value_shape ?? "",
    ).trim();
    const normalizedMonotonicity = normalizeMonotonicity(monotonicity);
    const counts = artifact.value_classification?.development_counts ?? {};
    const developmentRows = Math.max(
      1,
      Object.entries(counts).reduce(
        (total, [key, value]) =>
          key === "ordinary_numeric_outlier" ? total : total + count(value),
        0,
      ),
    );
    const missingRate = count(counts.true_null) / developmentRows;
    const specialGroups = rows(artifact.special_values?.groups);
    const specialRate = specialGroups.reduce(
      (total, group) => total + (finite(group.population_share) ?? 0),
      0,
    );
    const ordinaryBins = rows(artifact.iv_woe?.bins).filter((row) =>
      ["ordinary_valid_range", "ordinary_category"].includes(
        String(row.bin_type ?? ""),
      ),
    );
    const shape = eventShapeLabel({ event_rate_shape: { groups: ordinaryBins } });

    if (iv !== null && iv >= HIGH_IV_REVIEW_THRESHOLD) {
      output.push(
        finding({
          title: `${feature} has unusually high information value`,
          category: "Predictors",
          severity: "high",
          affectedVariables: [feature],
          analyticalBasis:
            "IV is calculated from governed development-population target-event aggregates. A high value is a review signal only and is not proof of leakage.",
          metricLabel: "Information value",
          metricValue: number(iv, 3),
          recommendedAction:
            "Review lineage, availability at decision time, event-rate shape, and target-source status before retaining the predictor.",
          downstreamDestination: "Validation",
          suggestedTransformations: [
            "No transformation",
            "Binning",
            "Investigate further",
          ],
          evidenceReferences: [
            `predictors.governed_predictor_artifacts.${feature}.iv`,
          ],
          documentationImpact:
            "The reviewer disposition, rationale, event-rate shape, and leakage evidence enter predictor findings.",
          iv,
          eventRateShape: shape,
          monotonicity: monotonicity || "Not classified",
          targetSourceStatus: "not_target_source",
          leakageEvidence:
            "No deterministic target-source match. High IV alone does not establish leakage.",
          importance: Math.min(Math.round(iv * 20), 40),
        }),
      );
    }
    if (
      normalizedMonotonicity.includes("non_monotonic") ||
      normalizedMonotonicity.includes("mixed")
    ) {
      output.push(
        finding({
          title: `${feature} has a non-monotonic target shape`,
          category: "Predictors",
          severity: "moderate",
          affectedVariables: [feature],
          analyticalBasis:
            "Governed development-population quantile or level aggregates change direction across the observed event-rate shape.",
          metricLabel: "Monotonicity",
          metricValue: monotonicity,
          recommendedAction:
            "Review whether governed binning improves interpretability without hiding meaningful non-linearity.",
          downstreamDestination: "Feature Engineering",
          suggestedTransformations: [
            "Binning",
            "No transformation",
            "Investigate further",
          ],
          evidenceReferences: [
            `predictors.governed_predictor_artifacts.${feature}.monotonicity.valid_value_shape`,
          ],
          documentationImpact:
            "An accepted recommendation enters the feature-engineering queue as a draft, never an automatic mutation.",
          eventRateShape: shape,
          monotonicity,
        }),
      );
    }
    if (missingRate >= MATERIAL_MISSINGNESS_THRESHOLD) {
      output.push(
        finding({
          title: `${feature} has material missingness`,
          category: "Predictors",
          severity: "moderate",
          affectedVariables: [feature],
          analyticalBasis:
            "Null-only missingness is measured separately from bureau special values in the governed development population.",
          metricLabel: "Missing rate",
          metricValue: percent(missingRate),
          recommendedAction:
            "Compare present and missing event rates, then select an evidence-based treatment on Missing Values.",
          downstreamDestination: "Missing Values",
          suggestedTransformations: [
            "Special-value separation",
            "Investigate further",
            "No transformation",
          ],
          evidenceReferences: [
            `predictors.governed_predictor_artifacts.${feature}.value_classification.development_counts.true_null`,
          ],
          documentationImpact:
            "The accepted recommendation enters the missing-value queue as a draft.",
          importance: Math.min(Math.round(missingRate * 100), 30),
        }),
      );
    }
    if (specialRate >= MATERIAL_SPECIAL_VALUE_THRESHOLD) {
      output.push(
        finding({
          title: `${feature} has material bureau special-value prevalence`,
          category: "Predictors",
          severity: "moderate",
          affectedVariables: [feature],
          analyticalBasis:
            "Recognized bureau special values are counted separately from nulls and ordinary numeric values in the governed development population.",
          metricLabel: "Special-value prevalence",
          metricValue: percent(specialRate),
          recommendedAction:
            "Preserve special values as labeled meaning-bearing categories unless governed evidence supports another treatment.",
          downstreamDestination: "Feature Engineering",
          suggestedTransformations: [
            "Special-value separation",
            "Categorical conversion",
            "No transformation",
          ],
          evidenceReferences: [
            `predictors.governed_predictor_artifacts.${feature}.special_values.groups`,
          ],
          documentationImpact:
            "The accepted semantic treatment enters feature engineering and predictor documentation.",
          importance: Math.min(Math.round(specialRate * 100), 30),
        }),
      );
    }
  }
}

function addGovernedRelationshipFindings(
  output: EdaFinding[],
  sections: EdaFindingSections,
) {
  const artifact = governedRelationshipArtifact(sections);
  if (!artifact) return;
  const correlation = artifact.correlation ?? {};
  const columns = strings(correlation.columns);
  const matrix = Array.isArray(correlation.pearson_matrix)
    ? correlation.pearson_matrix
    : [];
  const pairs: Array<{ featureA: string; featureB: string; value: number }> = [];
  for (let left = 0; left < columns.length; left += 1) {
    for (let right = left + 1; right < columns.length; right += 1) {
      const value = finite(matrix[left]?.[right]);
      if (value !== null && Math.abs(value) >= HIGH_CORRELATION_THRESHOLD) {
        pairs.push({ featureA: columns[left], featureB: columns[right], value });
      }
    }
  }
  pairs.sort(
    (left, right) =>
      Math.abs(right.value) - Math.abs(left.value) ||
      left.featureA.localeCompare(right.featureA) ||
      left.featureB.localeCompare(right.featureB),
  );
  for (const row of pairs.slice(0, 12)) {
    output.push(
      finding({
        title: `${row.featureA} and ${row.featureB} are strongly correlated`,
        category: "Relationships",
        severity: Math.abs(row.value) >= 0.9 ? "high" : "moderate",
        affectedVariables: [row.featureA, row.featureB],
        analyticalBasis:
          "Pairwise Pearson correlation is calculated over governed development-population numeric predictors with pairwise non-missing support.",
        metricLabel: "Correlation",
        metricValue: number(row.value, 3),
        recommendedAction:
          "Inspect overlap, business meaning, and VIF before deciding to retain, drop, or combine either predictor.",
        downstreamDestination: "Feature Engineering",
        suggestedTransformations: ["No transformation", "Investigate further"],
        evidenceReferences: [
          `relationships.governed_relationship_artifact.correlation.${row.featureA}.${row.featureB}`,
        ],
        documentationImpact:
          "The reviewer rationale records any retain, drop, or combine recommendation; no action is automatic.",
        importance: Math.round(Math.abs(row.value) * 25),
      }),
    );
  }
  for (const row of rows(artifact.vif).slice(0, 12)) {
    const feature = String(row.feature ?? "").trim();
    const vif = finite(row.vif);
    if (!feature || (vif !== null && vif < VIF_REVIEW_THRESHOLD)) continue;
    if (vif === null && !row.is_infinite) continue;
    output.push(
      finding({
        title: `${feature} requires multicollinearity review`,
        category: "Relationships",
        severity: row.is_infinite || (vif ?? 0) >= 10 ? "high" : "moderate",
        affectedVariables: [feature],
        analyticalBasis:
          "VIF is computed on the governed development-population complete-case predictor cohort; it is a relationship diagnostic, not an exclusion rule.",
        metricLabel: "VIF",
        metricValue: row.is_infinite ? "Infinite" : number(vif, 2),
        recommendedAction:
          "Review correlated partners and run a non-mutating exclusion scenario before recording a downstream recommendation.",
        downstreamDestination: "Feature Engineering",
        suggestedTransformations: ["No transformation", "Investigate further"],
        evidenceReferences: [
          `relationships.governed_relationship_artifact.vif.${feature}`,
        ],
        documentationImpact:
          "The accepted relationship decision and rationale enter the MDD relationship narrative.",
        importance: Math.min(Math.round(vif ?? 50), 50),
      }),
    );
  }
}

function addDataQualityFindings(
  output: EdaFinding[],
  sections: EdaFindingSections,
) {
  const overview = sections.overview;
  if (!overview) return;
  const headline = overview.headline ?? {};
  const integrity = overview.data_integrity ?? {};
  const duplicateRows = count(
    integrity.duplicate_rows ?? headline.duplicate_rows,
  );
  if (duplicateRows > 0) {
    output.push(
      finding({
        title: "Exact duplicate rows require a governed treatment decision",
        category: "Data quality",
        severity: "high",
        affectedVariables: [],
        analyticalBasis:
          "The full registered population contains rows that are exact duplicates across the governed analysis frame.",
        metricLabel: "Duplicate rows",
        metricValue: duplicateRows.toLocaleString(),
        recommendedAction:
          "Confirm whether these are ingestion duplicates or valid repeated observations; record exclusion or retention without mutating data from EDA.",
        downstreamDestination: "Feature Engineering",
        suggestedTransformations: [
          "No transformation",
          "Investigate further",
        ],
        evidenceReferences: ["overview.data_integrity.duplicate_rows"],
        documentationImpact:
          "The reviewer decision and rationale enter the EDA decision history and downstream queue.",
        importance: Math.min(duplicateRows, 99),
      }),
    );
  }

  const missingCells = count(headline.missing_cells);
  if (missingCells > 0) {
    output.push(
      finding({
        title: "Missing values are present in the modeling population",
        category: "Data quality",
        severity: "moderate",
        affectedVariables: [],
        analyticalBasis:
          "The governed full-population overview reports null cells before any missing-value treatment.",
        metricLabel: "Missing cells",
        metricValue: `${missingCells.toLocaleString()} (${percent(
          finite(headline.missing_cell_rate),
        )})`,
        recommendedAction:
          "Review feature-level prevalence and informative missingness before selecting a treatment on Missing Values.",
        downstreamDestination: "Missing Values",
        suggestedTransformations: [
          "Special-value separation",
          "Investigate further",
          "No transformation",
        ],
        evidenceReferences: ["overview.headline.missing_cells"],
        documentationImpact:
          "The missingness review and any accepted treatment recommendation enter the predictor-quality narrative.",
      }),
    );
  }

  for (const column of strings(integrity.constant_columns)) {
    output.push(
      finding({
        title: `${column} is constant`,
        category: "Data quality",
        severity: "moderate",
        affectedVariables: [column],
        analyticalBasis:
          "The governed overview found no usable variation in this field.",
        metricLabel: "Distinct usable values",
        metricValue: "1 or fewer",
        recommendedAction:
          "Confirm the field has no operational role, then carry a draft exclusion recommendation into feature engineering.",
        downstreamDestination: "Feature Engineering",
        suggestedTransformations: [
          "No transformation",
          "Investigate further",
        ],
        evidenceReferences: [
          `overview.data_integrity.constant_columns.${column}`,
        ],
        documentationImpact:
          "Accepted disposition is recorded as a feature-readiness decision, not an automatic drop.",
      }),
    );
  }

  for (const row of rows(integrity.invalid_numeric_parsing)) {
    const feature = String(row.feature ?? "Field");
    output.push(
      finding({
        title: `${feature} contains values that did not parse numerically`,
        category: "Data quality",
        severity: "moderate",
        affectedVariables: [feature],
        analyticalBasis:
          "The governed parser detected non-null source values that could not be interpreted as numeric.",
        metricLabel: "Unparsed values",
        metricValue: count(row.unparsed_count).toLocaleString(),
        recommendedAction:
          "Review source encoding and decide whether categorical conversion or upstream correction is appropriate.",
        downstreamDestination: "Feature Engineering",
        suggestedTransformations: [
          "Categorical conversion",
          "Investigate further",
        ],
        evidenceReferences: [
          `overview.data_integrity.invalid_numeric_parsing.${feature}`,
        ],
        documentationImpact:
          "The parsing concern and accepted resolution enter the data-quality narrative.",
      }),
    );
  }
}

function addTargetFindings(
  output: EdaFinding[],
  sections: EdaFindingSections,
) {
  const overview = sections.overview ?? {};
  const target = sections.target;
  const profile = target?.profile ?? overview.target_profile;
  const targetName = String(target?.target ?? overview.target ?? "target");
  if (profile) {
    const eventRate = finite(profile.event_rate);
    if (eventRate !== null) {
      const rare = eventRate < 0.01;
      const imbalanced = eventRate < 0.1 || eventRate > 0.9;
      output.push(
        finding({
          title: rare
            ? `${targetName} has a rare observed event`
            : imbalanced
              ? `${targetName} has a materially imbalanced class distribution`
              : `${targetName} class balance is measurable`,
          category: "Target",
          severity: rare ? "high" : imbalanced ? "moderate" : "info",
          affectedVariables: [targetName],
          analyticalBasis:
            "Event prevalence is computed over all non-missing target-bearing rows in the governed population.",
          metricLabel: "Event rate",
          metricValue: `${percent(eventRate)} (${count(
            profile.event_count,
          ).toLocaleString()} events / ${count(
            profile.valid_count,
          ).toLocaleString()} target-bearing rows)`,
          recommendedAction: rare
            ? "Use stratified splitting and ranking, lift, calibration, and threshold metrics; do not rely on accuracy alone."
            : "Carry the observed prevalence into split design and model evaluation.",
          downstreamDestination: "Balance and Split",
          suggestedTransformations: ["No transformation"],
          evidenceReferences: ["target.profile.event_rate"],
          documentationImpact:
            "Class balance and the selected evaluation implications enter the target narrative.",
        }),
      );
    }
  }

  const quality = target?.target_quality;
  if (quality) {
    const checks: Array<{
      count: number;
      title: string;
      metric: string;
      reference: string;
    }> = [
      {
        count: count(quality.missing_target_count),
        title: "The target contains missing values",
        metric: "Missing target values",
        reference: "target.target_quality.missing_target_count",
      },
      {
        count: rows(quality.invalid_target_values).reduce(
          (sum, row) => sum + count(row.count),
          0,
        ),
        title: "The target contains invalid values",
        metric: "Invalid target values",
        reference: "target.target_quality.invalid_target_values",
      },
      {
        count: strings(quality.unexpected_target_values).length,
        title: "The target contains unexpected classes",
        metric: "Unexpected target classes",
        reference: "target.target_quality.unexpected_target_values",
      },
      {
        count: count(quality.duplicate_target_bearing_rows),
        title: "Duplicate records carry observed target values",
        metric: "Duplicate target-bearing rows",
        reference: "target.target_quality.duplicate_target_bearing_rows",
      },
    ];
    for (const check of checks) {
      if (check.count <= 0) continue;
      output.push(
        finding({
          title: check.title,
          category: "Target",
          severity: "high",
          affectedVariables: [targetName],
          analyticalBasis:
            "The target-quality diagnostic evaluated the governed full population without modifying records.",
          metricLabel: check.metric,
          metricValue: check.count.toLocaleString(),
          recommendedAction:
            "Resolve the target-quality concern before training and preserve the reviewer rationale in documentation.",
          downstreamDestination: "Validation",
          suggestedTransformations: ["Investigate further"],
          evidenceReferences: [check.reference],
          documentationImpact:
            "The accepted disposition enters target-quality evidence and validation carry-forward.",
        }),
      );
    }

    const candidateFamilies: Array<{
      key:
        | "target_derived_candidates"
        | "post_outcome_candidates"
        | "perfect_relationship_candidates";
      label: string;
      basis: string;
    }> = [
      {
        key: "target_derived_candidates",
        label: "Target-derived candidate",
        basis:
          "Governed target-quality evidence identifies a field whose lineage or naming suggests derivation from the modeled outcome.",
      },
      {
        key: "post_outcome_candidates",
        label: "Post-outcome candidate",
        basis:
          "Governed target-quality evidence identifies a field that may only be available after the modeled decision point.",
      },
      {
        key: "perfect_relationship_candidates",
        label: "Structural relationship candidate",
        basis:
          "A structural rule—not high IV alone—identified a near-perfect or perfectly separating relationship with the target.",
      },
    ];
    for (const family of candidateFamilies) {
      for (const row of rows(quality[family.key]).slice(0, 20)) {
        const feature = String(
          row.feature ?? row.column ?? row.field ?? "Candidate field",
        );
        const assessment = String(
          row.assessment ?? row.state ?? row.leakage_state ?? "Review recommended",
        );
        output.push(
          finding({
            title: `${feature} requires target leakage review`,
            category: "Target",
            severity:
              normalizeMonotonicity(assessment).includes("likely") ||
              normalizeMonotonicity(assessment).includes("confirmed")
                ? "high"
                : "moderate",
            affectedVariables: [feature],
            analyticalBasis: family.basis,
            metricLabel: family.label,
            metricValue: assessment,
            recommendedAction:
              "Verify source lineage and availability at decision time. Confirmed exclusion requires reviewer evidence; ATLAS does not infer leakage from association strength alone.",
            downstreamDestination: "Validation",
            suggestedTransformations: [
              "No transformation",
              "Investigate further",
            ],
            evidenceReferences: [
              `target.target_quality.${family.key}.${feature}`,
            ],
            documentationImpact:
              "The candidate, evidence, reviewer disposition, and rationale enter target leakage review history.",
            targetSourceStatus: "review",
            leakageEvidence: String(
              row.evidence ??
                row.reason ??
                `${family.label}; reviewer confirmation is required.`,
            ),
          }),
        );
      }
    }
  }

  const exclusions = targetSourceExclusions(sections);
  if (exclusions.length) {
    output.push(
      finding({
        title: "Deterministic target-source fields remain excluded",
        category: "Target",
        severity: "info",
        affectedVariables: exclusions,
        analyticalBasis:
          "Server predictor authorization identifies deterministic target sources separately from model-eligible predictors.",
        metricLabel: "Excluded target-source fields",
        metricValue: exclusions.join(", "),
        recommendedAction:
          "Retain the governed exclusion. Review evidence if upstream lineage changes; do not reintroduce these fields from EDA.",
        downstreamDestination: "Documentation",
        suggestedTransformations: ["No transformation"],
        evidenceReferences: [
          "overview.predictor_authorization.target_source_excluded",
        ],
        documentationImpact:
          "The exclusion is disclosed in target lineage, predictor authorization, and the approved EDA record.",
        targetSourceStatus: "excluded",
        leakageEvidence:
          "Deterministic source relationship documented by governed target lineage.",
        importance: 20,
      }),
    );
  }
}

function addPredictorFindings(
  output: EdaFinding[],
  sections: EdaFindingSections,
) {
  const predictors = sections.predictors;
  if (!predictors) return;
  const excluded = new Set(targetSourceExclusions(sections));
  const targetName = String(
    predictors.target ?? sections.overview?.target ?? sections.target?.target ?? "",
  );
  const profiles = rows(predictors.predictor_visual_profiles);

  for (const profile of profiles) {
    const feature = String(profile.feature ?? "").trim();
    if (!feature || feature === targetName || excluded.has(feature)) continue;
    const metrics = profile.metrics ?? {};
    const iv = finite(metrics.iv ?? profile.iv);
    const missingRate = finite(
      metrics.missing_rate ?? profile.missing?.rate ?? profile.missing_rate,
    );
    const outlierRate = finite(
      metrics.outlier_rate ??
        profile.ordinary_outlier?.rate ??
        profile.ordinary_outlier_rate,
    );
    const specialRate = finite(
      metrics.special_prevalence ?? profile.bureau_special?.prevalence,
    );
    const skewness = finite(metrics.skewness ?? profile.skewness);
    const distinct = finite(
      metrics.distinct_count ?? profile.distinct_count ?? profile.cardinality,
    );
    const monotonicity = String(
      metrics.monotonicity ?? profile.regular_monotonicity ?? "",
    ).trim();
    const normalizedMonotonicity = normalizeMonotonicity(monotonicity);
    const shape = eventShapeLabel(profile);

    if (iv !== null && iv >= HIGH_IV_REVIEW_THRESHOLD) {
      output.push(
        finding({
          title: `${feature} has unusually high information value`,
          category: "Predictors",
          severity: "high",
          affectedVariables: [feature],
          analyticalBasis:
            "IV is calculated from governed target-event aggregates. A high value is a review signal only and is not proof of leakage.",
          metricLabel: "Information value",
          metricValue: number(iv, 3),
          recommendedAction:
            "Review lineage, availability at decision time, event-rate shape, and target-source status before retaining the predictor.",
          downstreamDestination: "Validation",
          suggestedTransformations: [
            "No transformation",
            "Binning",
            "Investigate further",
          ],
          evidenceReferences: [
            `predictors.predictor_visual_profiles.${feature}.metrics.iv`,
          ],
          documentationImpact:
            "The reviewer disposition, rationale, event-rate shape, and leakage evidence enter predictor findings.",
          iv,
          eventRateShape: shape,
          monotonicity: monotonicity || "Not classified",
          targetSourceStatus: "not_target_source",
          leakageEvidence:
            "No deterministic target-source match. High IV alone does not establish leakage.",
          importance: Math.min(Math.round(iv * 20), 40),
        }),
      );
    }

    if (
      normalizedMonotonicity.includes("non_monotonic") ||
      normalizedMonotonicity.includes("mixed")
    ) {
      output.push(
        finding({
          title: `${feature} has a non-monotonic target shape`,
          category: "Predictors",
          severity: "moderate",
          affectedVariables: [feature],
          analyticalBasis:
            "Governed quantile or level aggregates change direction across the observed event-rate shape.",
          metricLabel: "Monotonicity",
          metricValue: monotonicity,
          recommendedAction:
            "Review whether governed binning improves interpretability without hiding meaningful non-linearity.",
          downstreamDestination: "Feature Engineering",
          suggestedTransformations: [
            "Binning",
            "No transformation",
            "Investigate further",
          ],
          evidenceReferences: [
            `predictors.predictor_visual_profiles.${feature}.metrics.monotonicity`,
          ],
          documentationImpact:
            "An accepted recommendation enters the feature-engineering queue as a draft, never an automatic mutation.",
          eventRateShape: shape,
          monotonicity,
        }),
      );
    }

    if (missingRate !== null && missingRate >= MATERIAL_MISSINGNESS_THRESHOLD) {
      output.push(
        finding({
          title: `${feature} has material missingness`,
          category: "Predictors",
          severity: "moderate",
          affectedVariables: [feature],
          analyticalBasis:
            "Null-only missingness is measured separately from bureau special values over the full governed population.",
          metricLabel: "Missing rate",
          metricValue: percent(missingRate),
          recommendedAction:
            "Compare present and missing event rates, then select an evidence-based treatment on Missing Values.",
          downstreamDestination: "Missing Values",
          suggestedTransformations: [
            "Special-value separation",
            "Investigate further",
            "No transformation",
          ],
          evidenceReferences: [
            `predictors.predictor_visual_profiles.${feature}.missing`,
          ],
          documentationImpact:
            "The accepted recommendation enters the missing-value queue as a draft.",
          importance: Math.min(Math.round(missingRate * 100), 30),
        }),
      );
    }

    if (outlierRate !== null && outlierRate >= MATERIAL_OUTLIER_THRESHOLD) {
      output.push(
        finding({
          title: `${feature} has a material ordinary-outlier rate`,
          category: "Predictors",
          severity: "moderate",
          affectedVariables: [feature],
          analyticalBasis:
            "Ordinary IQR outliers exclude nulls and recognized bureau special values.",
          metricLabel: "Ordinary-outlier rate",
          metricValue: percent(outlierRate),
          recommendedAction:
            "Inspect the distribution and business meaning before considering winsorization or another robust treatment.",
          downstreamDestination: "Outliers",
          suggestedTransformations: [
            "Winsorization",
            "No transformation",
            "Investigate further",
          ],
          evidenceReferences: [
            `predictors.predictor_visual_profiles.${feature}.ordinary_outlier`,
          ],
          documentationImpact:
            "Any accepted treatment is carried forward as a draft recommendation; values are not changed here.",
        }),
      );
    }

    if (specialRate !== null && specialRate >= MATERIAL_SPECIAL_VALUE_THRESHOLD) {
      output.push(
        finding({
          title: `${feature} has material bureau special-value prevalence`,
          category: "Predictors",
          severity: "moderate",
          affectedVariables: [feature],
          analyticalBasis:
            "Recognized bureau special values are counted separately from nulls and ordinary numeric outliers.",
          metricLabel: "Special-value prevalence",
          metricValue: percent(specialRate),
          recommendedAction:
            "Preserve special values as labeled meaning-bearing categories unless governed evidence supports another treatment.",
          downstreamDestination: "Feature Engineering",
          suggestedTransformations: [
            "Special-value separation",
            "Categorical conversion",
            "No transformation",
          ],
          evidenceReferences: [
            `predictors.predictor_visual_profiles.${feature}.bureau_special`,
          ],
          documentationImpact:
            "The accepted semantic treatment enters feature engineering and predictor documentation.",
          importance: Math.min(Math.round(specialRate * 100), 30),
        }),
      );
    }

    if (
      skewness !== null &&
      Math.abs(skewness) >= MATERIAL_SKEWNESS_THRESHOLD
    ) {
      output.push(
        finding({
          title: `${feature} is strongly skewed`,
          category: "Predictors",
          severity: "moderate",
          affectedVariables: [feature],
          analyticalBasis:
            "Full-population regular numeric values have material absolute skewness.",
          metricLabel: "Skewness",
          metricValue: number(skewness, 2),
          recommendedAction:
            "Inspect sign, zero values, bureau specials, and model family before selecting a log transform, winsorization, or no treatment.",
          downstreamDestination: "Feature Engineering",
          suggestedTransformations: [
            "Log transform",
            "Winsorization",
            "No transformation",
            "Investigate further",
          ],
          evidenceReferences: [
            `predictors.predictor_visual_profiles.${feature}.metrics.skewness`,
          ],
          documentationImpact:
            "The analyst-confirmed option enters feature engineering as a draft recommendation.",
        }),
      );
    }

    if (distinct !== null && distinct <= 1) {
      output.push(
        finding({
          title: `${feature} has insufficient variance`,
          category: "Predictors",
          severity: "moderate",
          affectedVariables: [feature],
          analyticalBasis:
            "The aggregate predictor profile reports one or fewer distinct non-null values.",
          metricLabel: "Distinct values",
          metricValue: number(distinct, 0),
          recommendedAction:
            "Confirm the field is constant in the governed version before carrying a draft exclusion recommendation forward.",
          downstreamDestination: "Feature Engineering",
          suggestedTransformations: [
            "No transformation",
            "Investigate further",
          ],
          evidenceReferences: [
            `predictors.predictor_visual_profiles.${feature}.metrics.distinct_count`,
          ],
          documentationImpact:
            "The finding records feature readiness without automatically removing the variable.",
        }),
      );
    }

    if (
      String(profile.kind ?? "").toLowerCase() === "categorical" &&
      distinct !== null &&
      distinct > 50
    ) {
      output.push(
        finding({
          title: `${feature} has high categorical cardinality`,
          category: "Predictors",
          severity: "moderate",
          affectedVariables: [feature],
          analyticalBasis:
            "The aggregate categorical profile contains more than 50 distinct non-null levels.",
          metricLabel: "Distinct levels",
          metricValue: number(distinct, 0),
          recommendedAction:
            "Review sparse levels, operational semantics, and encoding strategy before model training.",
          downstreamDestination: "Feature Engineering",
          suggestedTransformations: [
            "Categorical conversion",
            "Binning",
            "No transformation",
            "Investigate further",
          ],
          evidenceReferences: [
            `predictors.predictor_visual_profiles.${feature}.metrics.distinct_count`,
          ],
          documentationImpact:
            "An accepted encoding recommendation enters feature engineering as a draft.",
        }),
      );
    }
  }
}

function addRelationshipFindings(
  output: EdaFinding[],
  sections: EdaFindingSections,
) {
  const relationships = sections.relationships;
  if (!relationships) return;
  for (const row of rows(relationships.strong_pairs).slice(0, 12)) {
    const featureA = String(row.feature_a ?? "").trim();
    const featureB = String(row.feature_b ?? "").trim();
    const correlation = finite(row.correlation);
    if (
      !featureA ||
      !featureB ||
      correlation === null ||
      Math.abs(correlation) < HIGH_CORRELATION_THRESHOLD
    ) {
      continue;
    }
    output.push(
      finding({
        title: `${featureA} and ${featureB} are strongly correlated`,
        category: "Relationships",
        severity: Math.abs(correlation) >= 0.9 ? "high" : "moderate",
        affectedVariables: [featureA, featureB],
        analyticalBasis:
          "Pairwise Pearson correlation is calculated over governed numeric predictors with pairwise non-missing support.",
        metricLabel: "Correlation",
        metricValue: number(correlation, 3),
        recommendedAction:
          "Inspect overlap, business meaning, and VIF before deciding to retain, drop, or combine either predictor.",
        downstreamDestination: "Feature Engineering",
        suggestedTransformations: [
          "No transformation",
          "Investigate further",
        ],
        evidenceReferences: [
          `relationships.strong_pairs.${featureA}.${featureB}`,
        ],
        documentationImpact:
          "The reviewer rationale records any retain, drop, or combine recommendation; no action is automatic.",
        importance: Math.round(Math.abs(correlation) * 25),
      }),
    );
  }

  for (const row of rows(relationships.vif).slice(0, 12)) {
    const feature = String(row.feature ?? "").trim();
    const vif = finite(row.vif);
    if (!feature || (vif !== null && vif < VIF_REVIEW_THRESHOLD)) continue;
    if (vif === null && !row.is_infinite) continue;
    output.push(
      finding({
        title: `${feature} requires multicollinearity review`,
        category: "Relationships",
        severity: row.is_infinite || (vif ?? 0) >= 10 ? "high" : "moderate",
        affectedVariables: [feature],
        analyticalBasis:
          "VIF is computed on the documented bounded complete-case predictor cohort; it is a relationship diagnostic, not an exclusion rule.",
        metricLabel: "VIF",
        metricValue: row.is_infinite ? "Infinite" : number(vif, 2),
        recommendedAction:
          "Review correlated partners and run a non-mutating exclusion scenario before recording a downstream recommendation.",
        downstreamDestination: "Feature Engineering",
        suggestedTransformations: [
          "No transformation",
          "Investigate further",
        ],
        evidenceReferences: [`relationships.vif.${feature}`],
        documentationImpact:
          "The accepted relationship decision and rationale enter the MDD relationship narrative.",
        importance: Math.min(Math.round(vif ?? 50), 50),
      }),
    );
  }
}

function addStabilityFinding(
  output: EdaFinding[],
  sections: EdaFindingSections,
) {
  const stability = sections.stability;
  if (!stability) return;
  const hasTime = rows(stability.time_profile).length > 0;
  const hasSegments = rows(stability.segment_profile).length > 0;
  if (!hasTime && !hasSegments) {
    output.push(
      finding({
        title: "Stability and segment analysis is unavailable for this dataset",
        category: "Stability",
        severity: "info",
        affectedVariables: [],
        analyticalBasis:
          "No governed observation-date or reusable business-segment field was selected or returned. ATLAS did not invent time or segment results.",
        metricLabel: "Available governed analyses",
        metricValue: "0 time / 0 segment",
        recommendedAction:
          "Register an observation date or designate approved cohort, product, channel, or region metadata in a future dataset version.",
        downstreamDestination: "Documentation",
        suggestedTransformations: ["No transformation"],
        evidenceReferences: [
          "stability.time_profile",
          "stability.segment_profile",
        ],
        documentationImpact:
          "The approved EDA record states that stability evidence is unavailable and does not block confirmation.",
      }),
    );
  }
}

function addLegacyWorkspaceFindings(
  output: EdaFinding[],
  sections: EdaFindingSections,
) {
  for (const row of rows(sections.findings?.findings)) {
    const description = String(row.finding ?? "").trim();
    if (!description) continue;
    const normalized = description.toLowerCase();
    if (
      (normalized.includes("duplicate") &&
        output.some((item) => item.title.toLowerCase().includes("duplicate"))) ||
      (normalized.includes("missing") &&
        output.some((item) => item.title.toLowerCase().includes("missing"))) ||
      (normalized.includes("rare") &&
        output.some((item) => item.title.toLowerCase().includes("rare")))
    ) {
      continue;
    }
    const sourceCategory = String(row.category ?? "").toLowerCase();
    const category: EdaFindingCategory = sourceCategory.includes("leak")
      ? "Target"
      : sourceCategory.includes("missing") ||
          sourceCategory.includes("integrity")
        ? "Data quality"
        : "Documentation";
    const severity: EdaFindingSeverity =
      String(row.severity ?? "").toLowerCase() === "warning"
        ? "moderate"
        : "info";
    output.push(
      finding({
        title: String(row.category ?? "Governed EDA finding"),
        category,
        severity,
        affectedVariables: [],
        analyticalBasis:
          "The governed Findings workspace endpoint reported this conclusion from its current aggregate checks.",
        metricLabel: "Finding",
        metricValue: description,
        recommendedAction: String(
          row.recommended_action ?? "Review and document a disposition.",
        ),
        downstreamDestination:
          category === "Target" ? "Validation" : "Documentation",
        suggestedTransformations: [
          "No transformation",
          "Investigate further",
        ],
        evidenceReferences: ["findings.findings"],
        documentationImpact:
          "The reviewer disposition and rationale enter the EDA decision history.",
        identity: [
          "legacy",
          row.category,
          description,
          row.recommended_action,
        ],
      }),
    );
  }
}

export function generateEdaFindings(
  sections: EdaFindingSections,
): EdaFinding[] {
  const output: EdaFinding[] = [];
  const governed =
    Object.keys(governedPredictorArtifacts(sections)).length > 0 ||
    Boolean(governedTargetArtifact(sections)) ||
    Boolean(governedRelationshipArtifact(sections));
  if (governed) {
    // Decision-facing findings must be invariant to sealed-holdout-only
    // changes. Every generated child below is derived from the shared
    // development-population governed artifacts (plus server authorization
    // and the development-scoped Findings endpoint for duplicate rows).
    addGovernedDataQualityFindings(output, sections);
    addGovernedTargetFindings(output, sections);
    addGovernedPredictorFindings(output, sections);
    addGovernedRelationshipFindings(output, sections);
  } else {
    addDataQualityFindings(output, sections);
    addTargetFindings(output, sections);
    addPredictorFindings(output, sections);
    addRelationshipFindings(output, sections);
    addLegacyWorkspaceFindings(output, sections);
  }
  addStabilityFinding(output, sections);
  const byId = new Map<string, EdaFinding>();
  for (const item of output) {
    if (!byId.has(item.id)) byId.set(item.id, item);
  }
  return [...byId.values()].sort(
    (left, right) =>
      right.importance - left.importance ||
      left.title.localeCompare(right.title),
  );
}

export function defaultFindingDecision(
  item: EdaFinding,
): EdaFindingDecision {
  return {
    disposition: "unresolved",
    rationale: "",
    destination: item.downstreamDestination,
    transformation: item.suggestedTransformations[0] ?? "No transformation",
  };
}

export function resolveFindingDecision(
  item: EdaFinding,
  state: EdaFindingsReviewState,
): EdaFindingDecision {
  return state.findingDecisions?.[item.id] ?? defaultFindingDecision(item);
}

export function findingsExecutiveSummary(
  inventory: EdaFinding[],
  state: EdaFindingsReviewState,
) {
  const resolved = inventory.map((item) => ({
    item,
    decision: resolveFindingDecision(item, state),
  }));
  return {
    total: inventory.length,
    blockers: inventory.filter((item) => item.severity === "high").length,
    reviewItems: resolved.filter(
      ({ decision }) => decision.disposition === "unresolved",
    ).length,
    accepted: resolved.filter(
      ({ decision }) => decision.disposition === "accepted",
    ).length,
    rejected: resolved.filter(
      ({ decision }) => decision.disposition === "rejected",
    ).length,
    downstreamActions: resolved.filter(
      ({ decision }) => decision.disposition === "accepted",
    ).length,
  };
}

export function documentedFindingRows(
  sections: EdaFindingSections,
  state: EdaFindingsReviewState,
) {
  const inventory = generateEdaFindings(sections);
  return inventory.map((item) => {
    const explicit = resolveFindingDecision(item, state);
    // The overall reviewer conclusion never disposes analytical evidence.
    // Child findings remain immutable evidence; only an explicit child legacy
    // decision or the governed parent decision can change disposition state.
    const disposition = explicit.disposition;
    return {
      finding_id: item.id,
      title: item.title,
      category: item.category,
      severity: item.severity,
      affected_variables: item.affectedVariables,
      analytical_basis: item.analyticalBasis,
      metric: {
        label: item.metricLabel,
        value: item.metricValue,
      },
      recommended_action: item.recommendedAction,
      downstream_destination: explicit.destination,
      reviewer_disposition: disposition,
      reviewer_rationale: explicit.rationale,
      rationale_status: explicit.rationale.trim()
        ? "documented"
        : disposition === "unresolved"
          ? "not_yet_required"
          : "missing",
      suggested_transformation: explicit.transformation,
      evidence_references: item.evidenceReferences,
      documentation_impact: item.documentationImpact,
      target_source_status: item.targetSourceStatus ?? "review",
      leakage_evidence: item.leakageEvidence ?? null,
      information_value: item.iv ?? null,
      event_rate_shape: item.eventRateShape ?? null,
      monotonicity: item.monotonicity ?? null,
      mutation_applied: false,
      carry_forward_mode:
        disposition === "accepted" ? "draft_recommendation" : "none",
    };
  });
}

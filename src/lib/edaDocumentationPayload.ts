import { stableCodeContextHash } from "./codeContextSafety";
import type {
  EdaDocumentationDecision,
  EdaDocumentationEvidenceReference,
  EdaDocumentationPayload,
  EdaDocumentationRecord,
  EdaDocumentationSections,
} from "./edaDocumentationApi";
import {
  EDA_CARRY_FORWARD_DESTINATIONS,
  EDA_FINDING_DISPOSITIONS,
  EDA_TRANSFORMATION_OPTIONS,
  documentedFindingRows,
  type EdaBulkDispositionAudit,
  type EdaFindingDecision,
  type EdaFindingsReviewState,
  type EdaOverallReviewStatus,
} from "./edaFindings";
import {
  evaluateFindingsCompletionEligibility,
  generateEdaParentFindings,
  summarizeFindingGovernance,
} from "./edaFindingGovernance";

export type EdaDocumentationWorkspaceSection = Record<string, any>;

export type EdaDocumentationFindingsInput = {
  commentary: string;
  status: EdaOverallReviewStatus;
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

export type EdaDocumentationBuildInput = {
  projectId: string;
  datasetId: string;
  datasetVersion: string;
  target: string;
  predictorManifestId: string;
  sections: Partial<
    Record<
      | "overview"
      | "target"
      | "predictors"
      | "relationships"
      | "stability"
      | "findings",
      EdaDocumentationWorkspaceSection
    >
  >;
  findings: EdaDocumentationFindingsInput;
  selectedFeatures: string[];
  controls: {
    histogramBins: number;
    dateField: string;
    segmentField: string;
    pairwiseFeatures: string[];
  };
  evidenceReferences?: EdaDocumentationEvidenceReference[];
};

const STABILITY_NOT_AVAILABLE =
  "This dataset does not contain a governed observation-time or reusable segment field. Stability analysis can be enabled with a documented date, cohort, product, region, channel, or other approved segmentation variable.";

const EDA_GOVERNANCE_CONTRACT_VERSION = "eda-governance-v2";

const REQUIRED_SECTIONS = [
  "overview",
  "target",
  "predictors",
  "relationships",
  "stability",
  "findings",
] as const;

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
    ? value
        .map((item) => String(item ?? "").trim())
        .filter(Boolean)
    : [];
}

function finite(value: unknown): number | null {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

const VOLATILE_ARTIFACT_IDENTITY_FIELDS = new Set([
  "created_at",
  "generated_at",
  "updated_at",
  "started_at",
  "completed_at",
  "duration_ms",
  "elapsed_ms",
  "cache",
  "cache_hit",
  "cache_status",
  "cached_at",
]);

/**
 * Governed artifacts retain their complete server timestamps in the MDD
 * snapshot, but volatile execution metadata must never change the analytical
 * version. Artifact IDs/hashes and analytical content remain hash inputs.
 */
function stableGovernedArtifactIdentity(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(stableGovernedArtifactIdentity);
  }
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(
        ([key]) =>
          !VOLATILE_ARTIFACT_IDENTITY_FIELDS.has(key.trim().toLowerCase()),
      )
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, nested]) => [key, stableGovernedArtifactIdentity(nested)]),
  );
}

function slimGovernedAnalyticalContract(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const {
    target_artifact: _nestedTargetArtifact,
    predictor_artifacts: _nestedPredictorArtifacts,
    relationship_artifact: _nestedRelationshipArtifact,
    ...summary
  } = value as Record<string, unknown>;
  return summary;
}

function oneOf<const T extends readonly string[]>(
  value: unknown,
  allowed: T,
  fallback: T[number],
): T[number] {
  const normalized = String(value ?? "").trim();
  return allowed.includes(normalized as T[number])
    ? (normalized as T[number])
    : fallback;
}

function duplicateTreatmentFromDocumentation(value: unknown) {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (normalized.includes("exclude duplicate")) return "exclude" as const;
  if (normalized.includes("keep duplicate")) return "keep" as const;
  return "review" as const;
}

/**
 * Rehydrate the reviewer workspace from the exact-identity server record.
 * Browser storage is used only when no server draft or approved record exists.
 */
export function hydrateEdaFindingsFromDocumentation(
  source: EdaDocumentationRecord | null | undefined,
  browserDraft: EdaFindingsReviewState,
): EdaFindingsReviewState {
  if (!source) return browserDraft;
  const section = (source.sections?.findings ?? {}) as Record<string, any>;
  const reviewer = (source.reviewer_record ??
    section.reviewer_record ?? {}) as Record<string, any>;
  const parentDecisions: Record<string, EdaFindingDecision> = {};
  for (const row of rows(section.parent_findings)) {
    const parentId = String(row.parent_id ?? "").trim();
    if (!parentId) continue;
    parentDecisions[parentId] = {
      disposition: oneOf(
        row.reviewer_disposition,
        EDA_FINDING_DISPOSITIONS,
        "unresolved",
      ),
      rationale: String(row.reviewer_rationale ?? ""),
      destination: oneOf(
        row.downstream_destination,
        ["", ...EDA_CARRY_FORWARD_DESTINATIONS] as const,
        "",
      ),
      transformation: oneOf(
        row.suggested_transformation,
        EDA_TRANSFORMATION_OPTIONS,
        "No transformation",
      ),
      resolutionAction: oneOf(
        row.resolution_action,
        [
          "unresolved",
          "retain_current_population",
          "exclude_upstream_and_repartition",
        ] as const,
        "unresolved",
      ),
      updatedAt: String(source.updated_at ?? source.confirmed_at ?? "") || undefined,
    };
  }
  const sectionBulk = rows(section.bulk_disposition_audit);
  const topLevelBulk = rows(source.bulk_disposition_actions);
  const bulkRows = sectionBulk.length ? sectionBulk : topLevelBulk;
  const bulkDispositionAudit: EdaBulkDispositionAudit[] = bulkRows
    .map((row) => {
      const priorStatuses = Object.fromEntries(
        Object.entries(
          (row.prior_statuses ?? {}) as Record<string, unknown>,
        ).map(([parentId, disposition]) => [
          parentId,
          oneOf(disposition, EDA_FINDING_DISPOSITIONS, "unresolved"),
        ]),
      );
      return {
        actionId: String(row.action_id ?? "").trim(),
        family: String(row.family ?? "").trim(),
        parentIds: strings(row.parent_ids),
        childIds: strings(row.child_ids),
        priorStatuses,
        newStatus: oneOf(
          row.new_status,
          EDA_FINDING_DISPOSITIONS,
          "unresolved",
        ),
        rationale: String(row.rationale ?? ""),
        destination: oneOf(
          row.destination,
          ["", ...EDA_CARRY_FORWARD_DESTINATIONS] as const,
          "",
        ),
        actor: String(
          row.actor_display_name ?? row.actor ?? row.actor_hint ?? "Authenticated reviewer",
        ),
        timestamp: String(
          row.timestamp ?? row.occurred_at ?? source.updated_at ?? source.confirmed_at ?? "",
        ),
      };
    })
    .filter((audit) => Boolean(audit.actionId && audit.family));
  const duplicateTreatment = duplicateTreatmentFromDocumentation(
    source.duplicate_decision ?? section.duplicate_treatment,
  );
  const reviewerStatus = oneOf(
    reviewer.overall_review_status ?? section.reviewer_status,
    [
      "draft",
      "under_review",
      "accepted",
      "accepted_with_conditions",
      "rejected",
      "reviewed",
    ] as const,
    "draft",
  );
  const generatedDraft = section.reviewer_record?.generated_draft;
  return {
    commentary: String(
      reviewer.reviewer_commentary ?? section.reviewer_commentary ?? "",
    ),
    overallConclusion: String(
      reviewer.overall_conclusion ?? section.overall_conclusion ?? "",
    ),
    status: reviewerStatus,
    savedAt: String(source.updated_at ?? source.confirmed_at ?? "") || undefined,
    duplicateTreatment,
    duplicateDecisionSavedAt:
      duplicateTreatment === "review"
        ? undefined
        : String(source.updated_at ?? source.confirmed_at ?? "") || undefined,
    findingDecisions: {},
    parentDecisions,
    bulkDispositionAudit,
    requiredConditions: strings(reviewer.required_conditions),
    openNonblockingItems: strings(reviewer.open_nonblocking_items),
    reviewerDraftGeneratedAt:
      String(generatedDraft?.generated_at ?? "") || undefined,
    reviewerDraftNonApproving: generatedDraft?.non_approving === true ? true : undefined,
  };
}

function concisePredictor(row: Record<string, any>) {
  return {
    feature: String(row.feature ?? ""),
    count: finite(row.count),
    missing_count: finite(row.missing_count),
    missing_rate: finite(row.missing_rate),
    mean: finite(row.mean),
    standard_deviation: finite(row.standard_deviation),
    minimum: finite(row.minimum),
    q1: finite(row.q1),
    median: finite(row.median),
    q3: finite(row.q3),
    maximum: finite(row.maximum),
    skewness: finite(row.skewness),
    outlier_rate: finite(row.outlier_rate),
    iv: finite(row.iv),
    monotonicity: row.monotonicity ?? null,
  };
}

function duplicateDecision(
  duplicateRows: number,
  resolutionAction: unknown,
) {
  if (duplicateRows <= 0) {
    return "No duplicate rows detected; no duplicate treatment is required.";
  }
  if (
    resolutionAction !== "retain_current_population" &&
    resolutionAction !== "exclude_upstream_and_repartition"
  ) {
    return "pending";
  }
  return resolutionAction === "exclude_upstream_and_repartition"
    ? "Exclude duplicate rows through governed preprocessing before modeling."
    : "Keep duplicate rows as documented repeated observations.";
}

function buildSections(
  input: EdaDocumentationBuildInput,
  selectedPredictors: string[],
): EdaDocumentationSections {
  const overview = input.sections.overview ?? {};
  const target = input.sections.target ?? {};
  const predictors = input.sections.predictors ?? {};
  const relationships = input.sections.relationships ?? {};
  const stability = input.sections.stability ?? {};
  const findings = input.sections.findings ?? {};
  const headline = overview.headline ?? {};
  const integrity = overview.data_integrity ?? {};
  const targetProfile = target.profile ?? overview.target_profile ?? {};
  const numeric = rows(predictors.numeric).filter((row) =>
    selectedPredictors.includes(String(row.feature ?? "")),
  );
  const categorical = rows(predictors.categorical).filter((row) =>
    selectedPredictors.includes(String(row.feature ?? "")),
  );
  const missingness = rows(predictors.missingness)
    .filter((row) => selectedPredictors.includes(String(row.feature ?? "")))
    .map((row) => ({
      feature: String(row.feature ?? ""),
      missing_count: finite(row.missing_count),
      missing_rate: finite(row.missing_rate),
      informative_missingness: Boolean(row.informative_missingness),
    }));
  const targetSourceExclusions = strings(
    overview.target_source_excluded ??
      overview.predictor_authorization?.target_source_excluded,
  );
  const timeFields = strings(
    target.governed_time_fields?.map?.(
      (item: Record<string, unknown>) => item.field,
    ) ?? overview.available_fields?.date_candidates,
  );
  const segmentFields = strings(
    overview.available_fields?.segment_candidates,
  );
  const stabilityAvailable =
    Boolean(stability.date_field || stability.segment_field) ||
    rows(stability.time_profile).length > 0 ||
    rows(stability.segment_profile).length > 0;
  const governedAnalyticalContract = slimGovernedAnalyticalContract(
    overview.governed_analytical_contract ??
    target.governed_analytical_contract ??
    predictors.governed_analytical_contract ??
    relationships.governed_analytical_contract ??
    null,
  );
  const governedPredictorArtifacts =
    predictors.governed_predictor_artifacts ??
    target.governed_predictor_artifacts ??
    overview.governed_predictor_artifacts ??
    null;
  const governedTargetArtifact =
    target.governed_target_artifact ??
    predictors.governed_target_artifact ??
    overview.governed_target_artifact ??
    null;
  const governedRelationshipArtifact =
    relationships.governed_relationship_artifact ??
    predictors.governed_relationship_artifact ??
    overview.governed_relationship_artifact ??
    null;
  const descriptiveScope = String(
    overview.descriptive_scope ??
      governedAnalyticalContract?.descriptive_scope ??
      overview.scope ??
      "unavailable",
  );
  const decisionScope = String(
    governedAnalyticalContract?.analysis_scope ??
      overview.analysis_scope?.mode ??
      overview.scope ??
      "unavailable",
  );
  const documentedFindings = documentedFindingRows(
    input.sections,
    input.findings,
  );
  const parentFindings = generateEdaParentFindings(input.sections);
  const findingsGovernance = summarizeFindingGovernance(
    parentFindings,
    input.findings,
  );
  const governedParentRows = findingsGovernance.parent_findings;
  const duplicateParent = governedParentRows.find(
    (row) => row.family === "exact_duplicate_rows",
  );
  const acceptedFindings = documentedFindings.filter(
    (row) => row.reviewer_disposition === "accepted",
  );
  const rejectedFindings = documentedFindings.filter(
    (row) => row.reviewer_disposition === "rejected",
  );
  const unresolvedFindings = documentedFindings.filter(
    (row) => row.reviewer_disposition === "unresolved",
  );
  const acceptedParentFindings = governedParentRows.filter(
    (row) => row.reviewer_disposition === "accepted",
  );
  const rejectedParentFindings = governedParentRows.filter(
    (row) => row.reviewer_disposition === "rejected",
  );
  const deferredParentFindings = governedParentRows.filter(
    (row) => row.reviewer_disposition === "deferred",
  );

  return {
    overview: {
      analysis_status: input.sections.overview ? "analyzed" : "not_loaded",
      governed_analytical_contract: governedAnalyticalContract,
      population: {
        rows: finite(overview.row_count ?? headline.rows),
        columns: finite(overview.column_count),
        scope: overview.scope ?? "unavailable",
        descriptive_scope: descriptiveScope,
        decision_scope: decisionScope,
        full_population_metrics: [
          "full_dataset",
          "full_dataset_aggregates",
          "full_governed_population",
        ].includes(descriptiveScope),
      },
      predictor_inventory: {
        authorized_predictors: selectedPredictors,
        predictor_count: finite(headline.predictors),
        numeric_predictors: finite(headline.numeric_predictors),
        categorical_predictors: finite(headline.categorical_predictors),
      },
      data_quality: {
        missing_cells: finite(headline.missing_cells),
        missing_cell_rate: finite(headline.missing_cell_rate),
        duplicate_rows: finite(headline.duplicate_rows),
        constant_fields: strings(integrity.constant_columns),
        invalid_numeric_parsing: rows(integrity.invalid_numeric_parsing),
      },
      target_source_exclusions: targetSourceExclusions,
      overall_readiness:
        Number(headline.duplicate_rows ?? 0) > 0 ||
        strings(integrity.constant_columns).length > 0
          ? "review_items_present"
          : "ready_for_reviewer_confirmation",
      governed_dataset: {
        dataset_id: input.datasetId,
        dataset_version_id: input.datasetVersion,
        dataset_version: input.datasetVersion,
      },
    },
    target: {
      analysis_status: input.sections.target ? "analyzed" : "not_loaded",
      governed_target_artifact: governedTargetArtifact,
      target_definition: {
        target: input.target,
        problem_type: target.problem_type ?? overview.problem_type,
        event_value: target.event_value ?? overview.event_value,
        non_event_value: targetProfile.negative_class ?? null,
      },
      governed_lineage:
        target.identity ??
        {
          modeled_target: input.target,
          deterministic_source_fields: targetSourceExclusions,
        },
      class_balance: targetProfile.class_distribution ?? [],
      event_prevalence: {
        event_count: finite(targetProfile.event_count),
        non_event_count: finite(targetProfile.non_event_count),
        event_rate: finite(targetProfile.event_rate),
        rare_event: Boolean(targetProfile.rare_event),
      },
      uncertainty_and_guidance:
        target.full_population_assessment ?? {
          split_sufficiency: targetProfile.split_sufficiency ?? null,
          five_fold_sufficiency: targetProfile.five_fold_sufficiency ?? null,
          recommended_metrics: targetProfile.recommended_metrics ?? [],
        },
      balance_and_confidence: {
        class_balance: targetProfile.class_distribution ?? [],
        full_population_assessment:
          target.full_population_assessment ?? null,
      },
      target_quality: target.target_quality ?? {},
      quality_diagnostic: target.target_quality ?? {},
      predictor_preview: target.predictor_preview ?? null,
      leakage_review: {
        target_source_exclusions: targetSourceExclusions,
        excluded_from_predictors: targetSourceExclusions.every(
          (field) => !selectedPredictors.includes(field),
        ),
      },
    },
    predictors: {
      analysis_status: input.sections.predictors ? "analyzed" : "not_loaded",
      governed_predictor_artifacts: governedPredictorArtifacts,
      selected_predictors: selectedPredictors,
      missingness,
      distribution_summaries: numeric.map(concisePredictor),
      categorical_summaries: categorical.map((row) => ({
        feature: String(row.feature ?? ""),
        count: finite(row.count),
        missing_count: finite(row.missing_count),
        missing_rate: finite(row.missing_rate),
        cardinality: finite(row.cardinality),
        rare_level_count: finite(row.rare_level_count),
        iv: finite(row.iv),
      })),
      information_value: [...numeric, ...categorical].map((row) => ({
        feature: String(row.feature ?? ""),
        iv: finite(row.iv),
      })),
      monotonicity: numeric.map((row) => ({
        feature: String(row.feature ?? ""),
        monotonicity: row.monotonicity ?? null,
      })),
      outliers: numeric.map((row) => ({
        feature: String(row.feature ?? ""),
        outlier_rate: finite(row.outlier_rate),
      })),
      notable_predictor_findings: missingness
        .filter((row) => row.informative_missingness)
        .map((row) => `${row.feature} has informative missingness.`),
    },
    relationships: {
      analysis_status: input.sections.relationships
        ? "analyzed"
        : "not_loaded",
      governed_relationship_artifact: governedRelationshipArtifact,
      correlation_review: {
        variable_count: strings(relationships.correlation_columns).length,
        reviewed_pair: input.controls.pairwiseFeatures,
        bounded_sample_scope: relationships.pairwise_scope ?? "unavailable",
      },
      high_correlation_pairs: rows(relationships.strong_pairs).slice(0, 100),
      vif_review: rows(relationships.vif).slice(0, 100),
      relationship_decisions: [],
      retained_dropped_combined_rationale:
        "No automatic retain, drop, or combine decision is applied by EDA.",
    },
    stability_and_segments: {
      analysis_status: stabilityAvailable ? "analyzed" : "not_available",
      available_time_fields: timeFields,
      available_segment_fields: segmentFields,
      selected_time_field: stability.date_field ?? input.controls.dateField,
      selected_segment_field:
        stability.segment_field ?? input.controls.segmentField,
      time_profile: rows(stability.time_profile),
      segment_profile: rows(stability.segment_profile),
      statement: stabilityAvailable
        ? "Stability or segment analysis is available for the documented governed fields."
        : STABILITY_NOT_AVAILABLE,
      limitation: stabilityAvailable
        ? null
        : {
            limitation_id: "eda-stability-segments-not-applicable",
            status: "not_applicable",
            title: "No governed time or segment fields",
            reason: "no_approved_field_or_comparison_population",
            time_stability_assessed: false,
            segment_comparison_assessed: false,
            drift_assessed: false,
            psi_assessed: false,
            blocks_completion: false,
            configuration_path_preserved: true,
          },
      stability_limitation: stabilityAvailable
        ? null
        : {
            limitation_id: "eda-stability-segments-not-applicable",
            status: "not_applicable",
            assessments_not_performed: [
              "time_stability",
              "segment_comparison",
              "drift",
              "psi",
            ],
            reason: "no_approved_field_or_comparison_population",
            blocks_completion: false,
            configuration_path_preserved: true,
          },
    },
    findings: {
      analysis_status: input.sections.findings ? "analyzed" : "not_loaded",
      duplicate_treatment: duplicateDecision(
        Number(headline.duplicate_rows ?? 0),
        duplicateParent?.resolution_action,
      ),
      reviewer_commentary: input.findings.commentary,
      overall_conclusion: input.findings.overallConclusion ?? "",
      reviewer_status: input.findings.status,
      source_findings: rows(findings.findings),
      approved_findings: acceptedFindings,
      rejected_findings: rejectedFindings,
      unresolved_items: unresolvedFindings,
      parent_findings: governedParentRows,
      finding_groups: findingsGovernance.finding_groups,
      required_parent_finding_count:
        findingsGovernance.required_parent_finding_count,
      unresolved_parent_finding_count:
        findingsGovernance.unresolved_parent_finding_count,
      eligible_parent_finding_count:
        findingsGovernance.eligible_parent_finding_count,
      informational_parent_finding_count:
        findingsGovernance.informational_parent_finding_count,
      child_evidence_count: findingsGovernance.child_evidence_count,
      accepted_parent_findings: acceptedParentFindings,
      rejected_parent_findings: rejectedParentFindings,
      deferred_parent_findings: deferredParentFindings,
      missing_rationales: documentedFindings
        .filter((row) => row.rationale_status === "missing")
        .map((row) => ({
          finding_id: row.finding_id,
          title: row.title,
          reviewer_disposition: row.reviewer_disposition,
        })),
      carry_forward: [...acceptedParentFindings, ...deferredParentFindings]
        .filter((row) => Boolean(row.downstream_destination))
        .map((row) => ({
        parent_id: row.parent_id,
        child_ids: row.child_ids,
        title: row.title,
        destination: row.downstream_destination,
        disposition: row.reviewer_disposition,
        recommendation:
          row.reviewer_disposition === "deferred"
            ? "Retain as a governed deferred recommendation for downstream review."
            : "Retain as a governed draft recommendation for downstream review.",
        suggested_transformation: row.suggested_transformation,
        reviewer_rationale: row.reviewer_rationale,
        status: "draft_recommendation",
        mutation_applied: false,
      })),
      decision_history: governedParentRows
        .filter((row) => row.reviewer_disposition !== "unresolved")
        .map((row) => ({
          parent_id: row.parent_id,
          child_ids: row.child_ids,
          title: row.title,
          disposition: row.reviewer_disposition,
          rationale: row.reviewer_rationale,
          evidence_references: row.evidence_references,
        })),
      bulk_disposition_audit: (input.findings.bulkDispositionAudit ?? []).map(
        (audit) => ({
          action_id: audit.actionId,
          family: audit.family,
          parent_ids: audit.parentIds,
          child_ids: audit.childIds,
          prior_statuses: audit.priorStatuses,
          new_status: audit.newStatus,
          rationale: audit.rationale,
          destination: audit.destination || null,
          mutation_applied: false,
        }),
      ),
      reviewer_record: {
        overall_conclusion: input.findings.overallConclusion ?? "",
        reviewer_commentary: input.findings.commentary,
        eda_status: input.findings.status,
        required_conditions: input.findings.requiredConditions ?? [],
        open_nonblocking_items: input.findings.openNonblockingItems ?? [],
        evidence_references: (input.evidenceReferences ?? []).map(
          (reference) => reference.evidence_id,
        ),
        mdd_reference: null,
        generated_draft: input.findings.reviewerDraftGeneratedAt
          ? {
              generated_at: input.findings.reviewerDraftGeneratedAt,
              non_approving: true,
              edited_by_reviewer: true,
            }
          : null,
        accepted_parent_finding_count: acceptedParentFindings.length,
        rejected_parent_finding_count: rejectedParentFindings.length,
        deferred_parent_finding_count: deferredParentFindings.length,
        unresolved_required_parent_finding_count:
          findingsGovernance.unresolved_parent_finding_count,
      },
      automatic_transformations_applied: false,
      evidence_references: input.evidenceReferences ?? [],
    },
  };
}

export function buildEdaDocumentationPayload(
  input: EdaDocumentationBuildInput,
): EdaDocumentationPayload {
  const overview = input.sections.overview ?? {};
  const authorization = overview.predictor_authorization ?? {};
  const authorized = strings(authorization.authorized_predictors);
  const selected = input.selectedFeatures.filter((feature) =>
    authorized.includes(feature),
  );
  const selectedPredictors = selected.length ? selected : authorized;
  const targetSourceExclusions = strings(
    overview.target_source_excluded ??
      authorization.target_source_excluded,
  );
  const documentationSections = buildSections(input, selectedPredictors);
  const missingSections = REQUIRED_SECTIONS.filter(
    (section) => !input.sections[section],
  );
  const duplicateRows = Number(overview.headline?.duplicate_rows ?? 0);
  const parentFindings = generateEdaParentFindings(input.sections);
  const findingsEligibility = evaluateFindingsCompletionEligibility(
    parentFindings,
    input.findings,
  );
  const duplicateParent = findingsEligibility.governance.parent_findings.find(
    (row) => row.family === "exact_duplicate_rows",
  );
  const duplicateTreatment = duplicateDecision(
    duplicateRows,
    duplicateParent?.resolution_action,
  );
  const blockers = missingSections.map(
    (section) =>
      `${section.replace(/_/g, " ")} analysis has not been loaded and reviewed.`,
  );
  blockers.push(...findingsEligibility.blockers);
  const contentIdentity = {
    project_id: input.projectId,
    dataset_id: input.datasetId,
    dataset_version_id: input.datasetVersion,
    dataset_version: input.datasetVersion,
    target: input.target,
    predictor_manifest_id: input.predictorManifestId,
    controls: {
      ...input.controls,
      pairwiseFeatures: [...input.controls.pairwiseFeatures].sort(),
    },
    findings: {
      commentary: input.findings.commentary,
      overallConclusion: input.findings.overallConclusion ?? "",
      status: input.findings.status,
      findingDecisions: Object.fromEntries(
        Object.entries(input.findings.findingDecisions ?? {})
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([findingId, decision]) => [
            findingId,
            {
              disposition: decision.disposition,
              rationale: decision.rationale,
              destination: decision.destination,
              transformation: decision.transformation,
              resolutionAction: decision.resolutionAction,
            },
          ]),
      ),
      parentDecisions: Object.fromEntries(
        Object.entries(input.findings.parentDecisions ?? {})
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([parentId, decision]) => [
            parentId,
            {
              disposition: decision.disposition,
              rationale: decision.rationale,
              destination: decision.destination,
              transformation: decision.transformation,
            },
          ]),
      ),
      bulkDispositionAudit: input.findings.bulkDispositionAudit ?? [],
      requiredConditions: input.findings.requiredConditions ?? [],
      openNonblockingItems: input.findings.openNonblockingItems ?? [],
    },
    sections: {
      ...documentationSections,
      overview: {
        ...documentationSections.overview,
        governed_analytical_contract: stableGovernedArtifactIdentity(
          documentationSections.overview.governed_analytical_contract,
        ),
      },
      predictors: {
        ...documentationSections.predictors,
        governed_predictor_artifacts: stableGovernedArtifactIdentity(
          documentationSections.predictors.governed_predictor_artifacts,
        ),
      },
      target: {
        ...documentationSections.target,
        governed_target_artifact: stableGovernedArtifactIdentity(
          documentationSections.target.governed_target_artifact,
        ),
      },
      relationships: {
        ...documentationSections.relationships,
        governed_relationship_artifact: stableGovernedArtifactIdentity(
          documentationSections.relationships.governed_relationship_artifact,
        ),
      },
      findings: {
        ...documentationSections.findings,
        evidence_references: [],
      },
    },
  };
  const analysisVersion = `eda-${stableCodeContextHash(
    JSON.stringify(contentIdentity),
  )}`;
  const evidenceReferences = input.evidenceReferences ?? [];
  const decisions: EdaDocumentationDecision[] = [];
  if (input.findings.status !== "draft") {
    decisions.push({
      decision_id: `${analysisVersion}-review`,
      category: "eda_review",
      decision: input.findings.status,
      rationale: input.findings.commentary,
      status: ["accepted", "accepted_with_conditions"].includes(
        input.findings.status,
      )
        ? "approved"
        : "reviewed",
    });
  }
  const findingsGovernance = summarizeFindingGovernance(
    parentFindings,
    input.findings,
  );
  for (const row of findingsGovernance.parent_findings) {
    if (row.reviewer_disposition === "unresolved") continue;
    decisions.push({
      decision_id: `${analysisVersion}-${row.parent_id}`,
      parent_id: row.parent_id,
      child_ids: row.child_ids,
      finding_family: row.family,
      category: `eda_parent_finding:${row.category}`,
      decision: row.reviewer_disposition,
      rationale: row.reviewer_rationale,
      status:
        row.reviewer_disposition === "accepted" ? "approved" : "rejected",
      downstream_destination: row.downstream_destination || undefined,
      suggested_transformation: row.suggested_transformation,
      carry_forward_mode:
        ["accepted", "deferred"].includes(row.reviewer_disposition) &&
        Boolean(row.downstream_destination)
          ? "draft_recommendation"
          : "none",
      mutation_applied: false,
      evidence_references: row.evidence_references,
    });
  }

  return {
    project_id: input.projectId,
    dataset_id: input.datasetId,
    dataset_version_id: input.datasetVersion,
    dataset_version: input.datasetVersion,
    target: input.target,
    predictor_manifest_id: input.predictorManifestId,
    eda_analysis_version: analysisVersion,
    sections: documentationSections,
    evidence_references: evidenceReferences,
    decisions,
    governance_contract_version: EDA_GOVERNANCE_CONTRACT_VERSION,
    reviewer_record: {
      overall_conclusion: input.findings.overallConclusion ?? "",
      reviewer_commentary: input.findings.commentary,
      overall_review_status: input.findings.status,
      required_conditions: input.findings.requiredConditions ?? [],
      open_nonblocking_items: input.findings.openNonblockingItems ?? [],
      evidence_references: evidenceReferences.map(
        (reference) => reference.evidence_id,
      ),
      mdd_reference: null,
      generated_draft_used: Boolean(
        input.findings.reviewerDraftGeneratedAt,
      ),
      generated_draft_non_approving:
        input.findings.reviewerDraftGeneratedAt ? true : null,
    },
    bulk_disposition_actions: (input.findings.bulkDispositionAudit ?? []).map(
      (audit) => ({
        action_id: audit.actionId,
        family: audit.family,
        parent_ids: audit.parentIds,
        child_ids: audit.childIds,
        prior_statuses: audit.priorStatuses,
        new_status: audit.newStatus,
        rationale: audit.rationale,
        destination: audit.destination || null,
        mutation_applied: false as const,
      }),
    ),
    performance_metadata: {
      section_duration_ms: Object.fromEntries(
        Object.entries(input.sections).map(([section, value]) => [
          section,
          finite(value?.duration_ms),
        ]),
      ),
      section_cache_status: Object.fromEntries(
        Object.entries(input.sections).map(([section, value]) => [
          section,
          value?.cache_status ?? "unavailable",
        ]),
      ),
      rendered_sample_limit: 5000,
    },
    completion_contract:
      overview.completion_contract ??
      input.sections.findings?.completion_contract ??
      {},
    duplicate_decision: duplicateTreatment,
    target_source_exclusions: targetSourceExclusions,
    unresolved_blocking_findings: blockers,
    reviewer_status: ["accepted", "accepted_with_conditions"].includes(
      input.findings.status,
    )
      ? "approved"
      : ["reviewed", "under_review", "rejected"].includes(
            input.findings.status,
          )
        ? "reviewed"
        : "pending",
  };
}

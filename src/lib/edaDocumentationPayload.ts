import { stableCodeContextHash } from "./codeContextSafety";
import type {
  EdaDocumentationDecision,
  EdaDocumentationEvidenceReference,
  EdaDocumentationPayload,
  EdaDocumentationSections,
} from "./edaDocumentationApi";
import {
  documentedFindingRows,
  type EdaFindingDecision,
} from "./edaFindings";

export type EdaDocumentationWorkspaceSection = Record<string, any>;

export type EdaDocumentationFindingsInput = {
  commentary: string;
  status: "draft" | "reviewed" | "accepted";
  duplicateTreatment?: "review" | "exclude" | "keep";
  duplicateDecisionSavedAt?: string;
  overallConclusion?: string;
  findingDecisions?: Record<string, EdaFindingDecision>;
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
  findings: EdaDocumentationFindingsInput,
) {
  if (duplicateRows <= 0) {
    return "No duplicate rows detected; no duplicate treatment is required.";
  }
  if (
    !findings.duplicateDecisionSavedAt ||
    findings.duplicateTreatment === "review" ||
    !findings.duplicateTreatment
  ) {
    return "pending";
  }
  return findings.duplicateTreatment === "exclude"
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
  const documentedFindings = documentedFindingRows(
    input.sections,
    input.findings,
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

  return {
    overview: {
      analysis_status: input.sections.overview ? "analyzed" : "not_loaded",
      population: {
        rows: finite(overview.row_count ?? headline.rows),
        columns: finite(overview.column_count),
        scope: overview.scope ?? "unavailable",
        full_population_metrics: overview.scope === "full_dataset",
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
        dataset_version: input.datasetVersion,
      },
    },
    target: {
      analysis_status: input.sections.target ? "analyzed" : "not_loaded",
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
    },
    findings: {
      analysis_status: input.sections.findings ? "analyzed" : "not_loaded",
      duplicate_treatment: duplicateDecision(
        Number(headline.duplicate_rows ?? 0),
        input.findings,
      ),
      reviewer_commentary: input.findings.commentary,
      overall_conclusion: input.findings.overallConclusion ?? "",
      reviewer_status: input.findings.status,
      source_findings: rows(findings.findings),
      approved_findings: acceptedFindings,
      rejected_findings: rejectedFindings,
      unresolved_items: unresolvedFindings,
      missing_rationales: documentedFindings
        .filter((row) => row.rationale_status === "missing")
        .map((row) => ({
          finding_id: row.finding_id,
          title: row.title,
          reviewer_disposition: row.reviewer_disposition,
        })),
      carry_forward: acceptedFindings.map((row) => ({
        finding_id: row.finding_id,
        title: row.title,
        destination: row.downstream_destination,
        recommendation: row.recommended_action,
        suggested_transformation: row.suggested_transformation,
        reviewer_rationale: row.reviewer_rationale,
        status: "draft_recommendation",
        mutation_applied: false,
      })),
      decision_history: documentedFindings
        .filter((row) => row.reviewer_disposition !== "unresolved")
        .map((row) => ({
          finding_id: row.finding_id,
          title: row.title,
          disposition: row.reviewer_disposition,
          rationale: row.reviewer_rationale,
          evidence_references: row.evidence_references,
        })),
      reviewer_record: {
        overall_conclusion: input.findings.overallConclusion ?? "",
        eda_status: input.findings.status,
        accepted_finding_count: acceptedFindings.length,
        rejected_finding_count: rejectedFindings.length,
        unresolved_finding_count: unresolvedFindings.length,
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
  const duplicateTreatment = duplicateDecision(duplicateRows, input.findings);
  const blockers = missingSections.map(
    (section) =>
      `${section.replace(/_/g, " ")} analysis has not been loaded and reviewed.`,
  );
  if (input.findings.status === "draft") {
    blockers.push("Reviewer status remains draft.");
  }
  if (duplicateRows > 0 && duplicateTreatment === "pending") {
    blockers.push("Duplicate-row treatment remains unresolved.");
  }
  const contentIdentity = {
    project_id: input.projectId,
    dataset_id: input.datasetId,
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
      duplicateTreatment: input.findings.duplicateTreatment,
      duplicateDecisionSavedAt: input.findings.duplicateDecisionSavedAt,
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
            },
          ]),
      ),
    },
    sections: {
      ...documentationSections,
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
  if (duplicateRows > 0 && duplicateTreatment !== "pending") {
    decisions.push({
      decision_id: `${analysisVersion}-duplicates`,
      category: "duplicate_rows",
      decision: duplicateTreatment,
      rationale:
        input.findings.duplicateTreatment === "exclude"
          ? "Reviewer selected governed exclusion before downstream modeling."
          : "Reviewer documented duplicate rows as valid repeated observations.",
      status: "approved",
    });
  }
  if (input.findings.status !== "draft") {
    decisions.push({
      decision_id: `${analysisVersion}-review`,
      category: "eda_review",
      decision: input.findings.status,
      rationale: input.findings.commentary,
      status:
        input.findings.status === "accepted" ? "approved" : "reviewed",
    });
  }
  const documentedFindings = documentedFindingRows(
    input.sections,
    input.findings,
  );
  for (const row of documentedFindings) {
    if (row.reviewer_disposition === "unresolved") continue;
    decisions.push({
      decision_id: `${analysisVersion}-${row.finding_id}`,
      finding_id: row.finding_id,
      category: `eda_finding:${row.category}`,
      decision: row.reviewer_disposition,
      rationale: row.reviewer_rationale,
      status:
        row.reviewer_disposition === "accepted" ? "approved" : "rejected",
      downstream_destination: row.downstream_destination,
      suggested_transformation: row.suggested_transformation,
      carry_forward_mode:
        row.reviewer_disposition === "accepted"
          ? "draft_recommendation"
          : "none",
      mutation_applied: false,
      evidence_references: row.evidence_references,
    });
  }

  return {
    project_id: input.projectId,
    dataset_id: input.datasetId,
    dataset_version: input.datasetVersion,
    target: input.target,
    predictor_manifest_id: input.predictorManifestId,
    eda_analysis_version: analysisVersion,
    sections: documentationSections,
    evidence_references: evidenceReferences,
    decisions,
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
    duplicate_decision: duplicateTreatment,
    target_source_exclusions: targetSourceExclusions,
    unresolved_blocking_findings: blockers,
    reviewer_status:
      input.findings.status === "accepted"
        ? "approved"
        : input.findings.status === "reviewed"
          ? "reviewed"
          : "pending",
  };
}

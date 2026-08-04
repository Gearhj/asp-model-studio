import { expect, test, type Page, type Route } from "@playwright/test";

const USER_ID = "predictive-route-matrix-user";
const PROJECT_ID = "predictive-route-matrix-project";
const PROJECT_NAME = "Predictive Route Integrity Matrix";
const DATASET_ID = "ds_predictive_route_matrix";
const DATASET_VERSION_ID = "v_predictive_route_matrix_001";
const TARGET = "bad_flag";
const PARTITION_ID = "analysis-partition-route-matrix-r1";
const DEVELOPMENT_ID = "development-route-matrix-r1";
const MANIFEST_VERSION = "feature-manifest-route-matrix-r1";
const MANIFEST_HASH = "feature-manifest-route-matrix-hash-r1";

const FEATURES = ["ExternalRiskEstimate", "NumTrades60Ever2DerogPubRec"];
const ROWS = Array.from({ length: 24 }, (_, index) => ({
  ExternalRiskEstimate: 42 + index * 2,
  NumTrades60Ever2DerogPubRec: index % 7,
  [TARGET]: index % 3 === 0 ? 1 : 0,
}));

type NetworkAudit = {
  requests: Array<{ method: string; pathname: string; body: string }>;
  serverErrors: Array<{ status: number; url: string }>;
  pageErrors: string[];
  consoleErrors: string[];
};

async function fulfillJson(route: Route, body: Record<string, unknown>, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function canonicalIdentity() {
  return {
    project_id: PROJECT_ID,
    dataset_id: DATASET_ID,
    dataset_version_id: DATASET_VERSION_ID,
    dataset_version: DATASET_VERSION_ID,
  };
}

function projectRecord() {
  return {
    projectId: PROJECT_ID,
    projectName: PROJECT_NAME,
    projectType: "predictive-modeling",
    workflowType: "predictive-modeling",
    ownerUserId: USER_ID,
    status: "active",
    activeSelection: {
      projectId: PROJECT_ID,
      datasetId: DATASET_ID,
      datasetVersionId: DATASET_VERSION_ID,
    },
    metadata: {
      modelId: "model-predictive-route-matrix",
      hasDataset: true,
      projectContextRevision: "1000-route-matrix",
      projectContextSavedAt: "2026-08-03T12:00:00.000Z",
      projectContext: {
        modelId: "model-predictive-route-matrix",
        projectName: PROJECT_NAME,
        modelType: "generic classification",
        modelTypeSelection: "Generic Binary Classification",
        businessObjective: "Validate project-scoped route composition with an isolated development fixture.",
        intendedModelUse: "Verify route integrity without completing governance actions or training a model.",
        targetDefinition: "Predict the isolated fixture event.",
        populationDefinition: "Synthetic development-only records used by browser tests.",
        observationWindow: "All predictors precede the isolated fixture decision point.",
        performanceWindow: "Synthetic outcomes follow the isolated fixture decision point.",
      },
    },
    createdAt: "2026-08-03T11:59:00.000Z",
    updatedAt: "2026-08-03T12:00:00.000Z",
  };
}

function workflowState() {
  const steps = Object.fromEntries(
    Array.from({ length: 14 }, (_, index) => [`step${String(index).padStart(2, "0")}`, index <= 6 ? "complete" : "in_progress"]),
  );
  return {
    projectId: PROJECT_ID,
    currentStepId: "step07",
    updatedAt: "2026-08-03T12:01:00.000Z",
    workflowStatus: {
      workflowId: "predictive-modeling",
      projectType: "predictive-modeling",
      hasDataset: true,
      datasetIdentity: { ...canonicalIdentity(), activation_revision: 1 },
      analysisPartition: {
        analysis_partition_id: PARTITION_ID,
        revision: 1,
        development_partition_id: DEVELOPMENT_ID,
        status: "current",
      },
      steps,
    },
  };
}

function featureRows() {
  return FEATURES.map((feature, index) => ({
    ...canonicalIdentity(),
    feature_id: `feature-route-matrix-${index + 1}`,
    feature_name: feature,
    display_name: feature,
    origin: "original",
    source_features: [feature],
    transformation_type: "identity",
    formula_or_rule: feature,
    output_datatype: "float64",
    creation_status: "available",
    materialization_status: "source",
    pipeline_status: "current",
    eligibility_status: "eligible",
    leakage_status: "eligible",
    selected: true,
    exclusion_reason: "",
    created_at: "2026-08-03T12:00:00.000Z",
    created_by: USER_ID,
    transformation_version: "1",
    profile_scope: "development_population",
    summary_statistics: {
      mean: index ? 2.8 : 65,
      standard_deviation: index ? 1.9 : 14,
      minimum: 0,
      maximum: index ? 6 : 88,
      missing_percent: 0,
      distinct_count: index ? 7 : 24,
      information_value: index ? 0.11 : 0.32,
    },
    config: {},
    user_rationale: "Registered isolated predictor.",
  }));
}

function featureManifest() {
  return {
    ok: true,
    ...canonicalIdentity(),
    manifest_version: MANIFEST_VERSION,
    manifest_hash: MANIFEST_HASH,
    features: featureRows(),
    pipeline_steps: [],
    created_at: "2026-08-03T12:00:00.000Z",
    updated_at: "2026-08-03T12:00:00.000Z",
    validation_status: "passed",
    validated_at: "2026-08-03T12:00:00.000Z",
    materialization_status: "current",
    materialization_hash: MANIFEST_HASH,
    materialized_manifest_hash: MANIFEST_HASH,
    materialized_at: "2026-08-03T12:00:00.000Z",
    confirmation_status: "confirmed",
    confirmed_manifest_hash: MANIFEST_HASH,
    confirmed_at: "2026-08-03T12:00:00.000Z",
    preview_hash: "preview-route-matrix-r1",
    execution_history: [],
    split_status: "current",
    persistence_status: "persisted",
    predictor_authorization: {
      target: TARGET,
      authorized_predictors: FEATURES,
      excluded_predictors: {},
      target_source_excluded: [TARGET],
      selected_predictors: FEATURES,
    },
  };
}

function analysisPartition() {
  return {
    ok: true,
    ...canonicalIdentity(),
    status: "current",
    ready: true,
    analysis_partition_id: PARTITION_ID,
    revision: 1,
    development_partition_id: DEVELOPMENT_ID,
    development_rows: ROWS.length,
    development_share: 0.8,
    holdout_share: 0.2,
    final_holdout_status: "sealed",
    holdout_isolation_status: "verified",
    target: TARGET,
    target_contract_id: "target-contract-route-matrix-r1",
    predictor_authorization_id: "predictor-auth-route-matrix-r1",
    random_seed: 42,
    stratification_policy: "target",
    stratification_field: TARGET,
  };
}

function splitStatus() {
  const baseDistribution = {
    rows: ROWS.length,
    valid_rows: ROWS.length,
    missing_rows: 0,
    classes: { "0": 16, "1": 8 },
    event_value: 1,
    events: 8,
    non_events: 16,
    event_rate: 1 / 3,
  };
  return {
    ok: true,
    ...canonicalIdentity(),
    status: "current",
    ready: true,
    has_split: true,
    split_id: "split-route-matrix-r1",
    target: TARGET,
    selected_features: FEATURES,
    feature_count: FEATURES.length,
    feature_manifest_version: MANIFEST_VERSION,
    config: { random_seed: 42, holdout_size: 0.2 },
    distributions: {
      full_dataset: baseDistribution,
      train_before_balancing: baseDistribution,
      train_after_balancing: baseDistribution,
      holdout_untouched: { ...baseDistribution, rows: 6, valid_rows: 6, events: 2, non_events: 4 },
    },
    n_train: 18,
    n_test: 6,
    validation_design_id: "validation-design-route-matrix-r1",
    validation_design_version: "validation-design-route-matrix-v1",
    training_population_id: DEVELOPMENT_ID,
    evaluation_population_role: "final_holdout_evaluation_only",
    validation_design: {
      ...canonicalIdentity(),
      validation_design_id: "validation-design-route-matrix-r1",
      design_version: "validation-design-route-matrix-v1",
      strategy: "hybrid",
      status: "approved",
    },
    cv_design: {
      method: "stratified_k_fold",
      fold_count: 3,
      repeats: 1,
      shuffle: true,
      approved: true,
      tuning_scope: "development_population_only",
    },
    balancing_policy: { method: "none", class_weight_policy: "none" },
    analysis_partition: analysisPartition(),
    analysis_partition_id: PARTITION_ID,
    analysis_partition_revision: 1,
    development_partition_id: DEVELOPMENT_ID,
    final_holdout_status: "sealed",
    holdout_isolation_status: "verified",
    completion_gates: {
      identity_current: true,
      feature_manifest_current: true,
      analysis_partition_current: true,
      final_holdout_sealed: true,
    },
  };
}

function outlierSummary() {
  const methods = Object.fromEntries(
    ["NONE", "IQR_1_5", "IQR_3_0", "ZSCORE_3", "ZSCORE_4", "PCT_01_99", "PCT_05_95"].map((method) => [method, {
      method,
      lower_threshold: 0,
      upper_threshold: 100,
      outlier_count: 0,
      outlier_rate: 0,
    }]),
  );
  return {
    ok: true,
    ...canonicalIdentity(),
    scope: "full_dataset",
    row_count: ROWS.length,
    target: TARGET,
    problem_type: "classification",
    event_value: 1,
    event_rate: 1 / 3,
    rare_event: false,
    predictor_authorization: {
      authorized_predictors: FEATURES,
      excluded_predictors: {},
      target_source_excluded: [TARGET],
    },
    features: FEATURES.map((feature, index) => ({
      feature,
      datatype: "float64",
      nonmissing_count: ROWS.length,
      ordinary_nonmissing_count: ROWS.length,
      missing_count: 0,
      distinct_count: index ? 7 : 24,
      mean: index ? 2.8 : 65,
      standard_deviation: index ? 1.9 : 14,
      minimum: 0,
      maximum: index ? 6 : 88,
      special_value_count: 0,
      special_value_rate: 0,
      special_values: {},
      skewness: 0.1,
      signal_metric: index ? 0.11 : 0.32,
      association_status: "evaluated",
      methods,
      rendered_sample: ROWS.map((row) => Number(row[feature as keyof typeof row])),
      rendered_sample_count: ROWS.length,
      quantiles: { p05: 1, p25: 2, p50: 3, p75: 4, p95: 5 },
    })),
    application: null,
  };
}

function missingSummary() {
  const stats = Object.fromEntries(FEATURES.map((feature, index) => [feature, {
    missing: 0,
    missingPct: 0,
    total: ROWS.length,
    nonmissing_count: ROWS.length,
    observed_count: ROWS.length,
    distinct_count: index ? 7 : 24,
    mean: index ? 2.8 : 65,
    mode: index ? 0 : 42,
    standard_deviation: index ? 1.9 : 14,
    minimum: 0,
    first_quartile: index ? 1 : 52,
    median: index ? 3 : 65,
    third_quartile: index ? 5 : 77,
    maximum: index ? 6 : 88,
    information_value: index ? 0.11 : 0.32,
    correlation_with_target: 0.1,
    association_status: "evaluated",
    special_value_count: 0,
    special_value_rate: 0,
    special_values: {},
    distribution: {
      kind: "numeric",
      bins: [{ label: "Observed", lower: 0, upper: 100, count: ROWS.length }],
      observed_count: ROWS.length,
      ordinary_numeric_count: ROWS.length,
      missing_count: 0,
      special_value_count: 0,
      parse_failure_count: 0,
      reference_cutoffs: null,
      cutoff_semantics: "Development-population descriptive range.",
    },
    informative: false,
    missing_target_metric: null,
    present_target_metric: null,
    difference: null,
  }]));
  return {
    ok: true,
    ...canonicalIdentity(),
    scope: "full_dataset",
    rows: ROWS.length,
    columns: FEATURES.map((name) => ({ name, dtype: "float64", role: "feature" })),
    stats,
    target: TARGET,
    problem_type: "classification",
    event_value: 1,
    event_rate: 1 / 3,
    rare_event: false,
    source_stage: "registered_dataset",
    predictor_authorization: {
      authorized_predictors: FEATURES,
      excluded_predictors: {},
      target_source_excluded: [TARGET],
    },
    application: null,
    validation: {
      validated_at: "2026-08-03T12:00:00.000Z",
      ...canonicalIdentity(),
      source_stage: "registered_dataset",
      row_count: ROWS.length,
      predictor_count: FEATURES.length,
      missing_cells: 0,
      strategy: "None",
      status: "validated_no_treatment_required",
      backend_materialization: false,
      statement: "Validated, no treatment required.",
    },
  };
}

function edaOverview() {
  return {
    ok: true,
    ...canonicalIdentity(),
    section: "overview",
    scope: "development_population",
    row_count: ROWS.length,
    column_count: FEATURES.length + 1,
    target: TARGET,
    problem_type: "classification",
    event_value: 1,
    duration_ms: 1,
    cache_status: "miss",
    analysis_partition: analysisPartition(),
    final_holdout_accessed: false,
    headline: {
      rows: ROWS.length,
      predictors: FEATURES.length,
      numeric_predictors: FEATURES.length,
      categorical_predictors: 0,
      missing_cells: 0,
      missing_cell_rate: 0,
      duplicate_rows: 0,
    },
    data_integrity: {
      constant_columns: [],
      identifier_candidates: [],
      leakage_candidates: [],
      invalid_numeric_parsing: [],
    },
    target_profile: {
      valid_count: ROWS.length,
      missing_count: 0,
      class_count: 2,
      event_rate: 1 / 3,
      class_distribution: [
        { value: 0, count: 16, rate: 2 / 3 },
        { value: 1, count: 8, rate: 1 / 3 },
      ],
    },
    available_fields: { numeric: FEATURES, categorical: [], date_candidates: [], segment_candidates: [] },
    predictor_authorization: {
      manifest_version: "predictor-auth-route-matrix-r1",
      authorized_predictors: FEATURES,
      target_source_excluded: [TARGET],
    },
    target_source_excluded: [TARGET],
  };
}

async function installMocks(page: Page): Promise<NetworkAudit> {
  const audit: NetworkAudit = { requests: [], serverErrors: [], pageErrors: [], consoleErrors: [] };
  page.on("pageerror", (error) => audit.pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") audit.consoleErrors.push(message.text());
  });
  page.on("response", (response) => {
    if (response.status() >= 500) audit.serverErrors.push({ status: response.status(), url: response.url() });
  });
  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method().toUpperCase();
    const body = request.postData() ?? "";
    audit.requests.push({ method, pathname: url.pathname, body });

    if (url.pathname === "/api/auth/me") {
      await fulfillJson(route, { ok: true, user: { userId: USER_ID, displayName: "Route Matrix User", role: "user", status: "active" } });
      return;
    }
    if (url.pathname === `/api/projects/${PROJECT_ID}` && method === "GET") {
      await fulfillJson(route, { ok: true, project: projectRecord() });
      return;
    }
    if (url.pathname === `/api/projects/${PROJECT_ID}/workflow-state` && method === "GET") {
      await fulfillJson(route, { ok: true, workflowState: workflowState() });
      return;
    }
    if (url.pathname === "/api/data/active-identity" && method === "GET") {
      await fulfillJson(route, {
        ok: true,
        ...canonicalIdentity(),
        activation_revision: 1,
        dataset_version_label: "Predictive route matrix version",
        dataset_source_type: "dataset-library",
        target: TARGET,
      });
      return;
    }
    if (url.pathname === "/api/data/get_sample" && method === "GET") {
      await fulfillJson(route, {
        ok: true,
        ...canonicalIdentity(),
        headers: [...FEATURES, TARGET],
        rows: ROWS,
        target: TARGET,
        selected_columns: FEATURES,
        registered_row_count: ROWS.length,
        row_count: ROWS.length,
      });
      return;
    }
    if (url.pathname === "/api/analysis-partitions/status" && method === "GET") {
      await fulfillJson(route, {
        ok: true,
        ...canonicalIdentity(),
        readiness: "current",
        status: "current",
        code: "analysis_partition_current",
        reused: true,
        analysis_partition: {
          ...analysisPartition(),
          positive_value: 1,
          negative_value: 0,
        },
      });
      return;
    }
    if (url.pathname === "/api/data/quality-profile" && method === "POST") {
      await fulfillJson(route, {
        ok: true,
        ...canonicalIdentity(),
        profileScope: "full_dataset",
        profiledRowCount: ROWS.length,
        registeredRowCount: ROWS.length,
        generatedAt: "2026-08-03T12:00:00.000Z",
        datasetHash: "dataset-route-matrix-hash-r1",
        columnCount: FEATURES.length + 1,
        duplicateRows: 0,
        duplicateIdCandidates: [],
        constantColumns: [],
        nearZeroVarianceColumns: [],
        highCardinalityCategoricalColumns: [],
        unexpectedDatatypeColumns: [],
        potentialLeakageCandidates: [],
        outlierPrevalence: [],
        targetHealth: {
          kind: "classification",
          eventValue: 1,
          eventRate: 1 / 3,
          classDistribution: [
            { value: 0, count: 16, percent: 2 / 3 },
            { value: 1, count: 8, percent: 1 / 3 },
          ],
        },
        dateRanges: [],
        missingness: [...FEATURES, TARGET].map((column) => ({ column, count: 0, percent: 0 })),
        memoryEstimateMb: 0.01,
        warnings: [],
        readinessStatus: "ready",
      });
      return;
    }
    if (url.pathname === "/api/data/feature-profile" && method === "POST") {
      await fulfillJson(route, {
        ok: true,
        ...canonicalIdentity(),
        profileScope: "full_dataset",
        profiledRowCount: ROWS.length,
        registeredRowCount: ROWS.length,
        problemType: "classification",
        target: TARGET,
        eventValue: 1,
        selectedColumns: FEATURES,
        featureManifestVersion: MANIFEST_VERSION,
        features: featureRows().map((row) => ({
          selected: true,
          predictor: row.feature_name,
          role: "predictor",
          datatype: row.output_datatype,
          iv: row.summary_statistics.information_value,
          ivStrength: "medium",
          correlationWithTarget: 0.1,
          correlationStrength: "weak",
          associationStatus: "evaluated",
          missingCount: 0,
          missingPercent: 0,
          distinctCount: row.summary_statistics.distinct_count,
          mean: row.summary_statistics.mean,
          standardDeviation: row.summary_statistics.standard_deviation,
          minimum: row.summary_statistics.minimum,
          firstQuartile: 1,
          median: 2,
          thirdQuartile: 3,
          maximum: row.summary_statistics.maximum,
          leakageStatus: "eligible",
          eligibilityStatus: "eligible",
          exclusionReason: "",
          origin: "original",
          sourceFeatures: [row.feature_name],
          transformationType: "identity",
          formulaOrRule: row.feature_name,
          materializationStatus: "source",
          featureId: row.feature_id,
        })),
      });
      return;
    }
    if (url.pathname === "/api/data/target-profile" && method === "POST") {
      const profileRequest = request.postDataJSON() as { include_iv?: boolean };
      await fulfillJson(route, {
        ok: true,
        analysisScope: {
          mode: "governed_version",
          label: "Development Population",
          projectId: PROJECT_ID,
          datasetId: DATASET_ID,
          datasetVersionId: DATASET_VERSION_ID,
          datasetName: "Predictive route matrix version",
          datasetFingerprint: "dataset-route-matrix-hash-r1",
          artifactChecksum: "artifact-route-matrix-checksum-r1",
          target: TARGET,
          populationRows: ROWS.length,
          exact: true,
          sampled: false,
          immutableVersion: true,
          evidenceEligible: true,
          mddEligible: true,
          decisionReady: true,
          disclosure: "Isolated development-population evidence only.",
          resolvedAt: "2026-08-03T12:00:00.000Z",
        },
        scopeIdentity: `${PROJECT_ID}:${DATASET_ID}:${DATASET_VERSION_ID}:${DEVELOPMENT_ID}`,
        profileScope: "governed_version",
        calculationVersion: "route-matrix-r1",
        generatedAt: "2026-08-03T12:00:00.000Z",
        datasetId: DATASET_ID,
        datasetVersionId: DATASET_VERSION_ID,
        datasetName: "Predictive route matrix version",
        artifactChecksum: "artifact-route-matrix-checksum-r1",
        target: TARGET,
        targetMapping: {
          target: TARGET,
          eventValue: "1",
          nonEventValue: "0",
          eventValueResolution: "configured",
          distinctCount: 2,
          isBinary: true,
          missingTargetCount: 0,
          validTargetCount: ROWS.length,
          eventCount: 8,
          nonEventCount: 16,
          eventRate: 1 / 3,
        },
        quality: {
          populationRows: ROWS.length,
          columnCount: FEATURES.length + 1,
          duplicateRows: 0,
          columnsWithMissingValues: 0,
          missingness: [],
          constantColumns: [],
          nearZeroVarianceColumns: [],
          highCardinalityColumns: [],
          potentialLeakageColumns: [],
          dateFields: [],
          targetMissingCount: 0,
          targetDistinctCount: 2,
          eventCount: 8,
          nonEventCount: 16,
          eventRate: 1 / 3,
        },
        problemType: "classification",
        predictors: FEATURES.map((predictor, index) => ({
          predictor,
          role: "predictor",
          eligible: true,
          exclusionReason: "",
          iv: profileRequest.include_iv === false ? null : index ? 0.11 : 0.32,
          ivStatus: profileRequest.include_iv === false ? "pending" : "available",
          ivStrength: profileRequest.include_iv === false ? null : { key: "medium", label: "Medium" },
          bins: [],
          effectiveBinCount: 0,
        })),
        predictorSummary: {
          total: FEATURES.length,
          evaluated: profileRequest.include_iv === false ? 0 : FEATURES.length,
          unavailable: 0,
          failed: 0,
          leakageReview: 0,
        },
        methodology: { scope: "development_population" },
        artifactResolutions: 1,
        datasetScans: 1,
        cached: false,
      });
      return;
    }
    if (url.pathname === "/api/analytics/target-distribution" && method === "POST") {
      await fulfillJson(route, {
        ok: true,
        supported: true,
        resolution: "exact",
        projectId: PROJECT_ID,
        datasetId: DATASET_ID,
        versionId: DATASET_VERSION_ID,
        target: TARGET,
        classDistribution: [
          { value: 0, count: 16, percent: 2 / 3 },
          { value: 1, count: 8, percent: 1 / 3 },
        ],
        totalRowCount: ROWS.length,
        artifactFormat: "parquet",
        engine: "isolated-fixture",
        cached: false,
        durationMs: 1,
      });
      return;
    }
    if (url.pathname === "/api/data/bureau-detection" && method === "POST") {
      await fulfillJson(route, {
        ok: true,
        ...canonicalIdentity(),
        scope: "full_dataset",
        row_count: ROWS.length,
        target: TARGET,
        event_value: 1,
        detected: false,
        confidence: 0,
        manual_declaration: "auto",
        reasons: [],
        likely_variable_count: 0,
        variables_with_special_values: 0,
        rows_with_special_values: 0,
        variables: [],
        metadata_source: "isolated_fixture",
        reviewed_at: "2026-08-03T12:00:00.000Z",
        activation_revision: 1,
        predictor_authorization_id: "predictor-auth-route-matrix-r1",
        target_contract_id: "target-contract-route-matrix-r1",
        correlation_id: "route-matrix-correlation-r1",
        target_analysis_scope: "development_partition",
        analysis_partition_id: PARTITION_ID,
        development_partition_id: DEVELOPMENT_ID,
        final_holdout_accessed: false,
      });
      return;
    }
    if (url.pathname === "/api/eda/workspace/overview" && method === "POST") {
      await fulfillJson(route, edaOverview());
      return;
    }
    if (url.pathname === `/api/eda/documentation/${PROJECT_ID}` && method === "GET") {
      await fulfillJson(route, {
        ok: true,
        ...canonicalIdentity(),
        status: "draft",
        draft: { status: "draft", findings: [], evidence_references: [] },
        current_approved: null,
        history: [],
        source_lineage: {
          ...canonicalIdentity(),
          target: TARGET,
          predictor_manifest_id: "predictor-auth-route-matrix-r1",
        },
      });
      return;
    }
    if (url.pathname === "/api/eda/documentation/draft" && method === "POST") {
      await fulfillJson(route, {
        ok: true,
        ...canonicalIdentity(),
        status: "draft",
        draft: request.postDataJSON(),
        current_approved: null,
        history: [],
        source_lineage: { ...canonicalIdentity(), target: TARGET, predictor_manifest_id: "predictor-auth-route-matrix-r1" },
      });
      return;
    }
    if (url.pathname === "/api/outliers/summary" && method === "POST") {
      await fulfillJson(route, outlierSummary());
      return;
    }
    if (url.pathname === "/api/missing/summary" && method === "GET") {
      await fulfillJson(route, missingSummary());
      return;
    }
    if (url.pathname === "/api/features/manifest" && method === "GET") {
      await fulfillJson(route, featureManifest());
      return;
    }
    if (url.pathname === "/api/features/profile" && method === "GET") {
      await fulfillJson(route, {
        ok: true,
        ...canonicalIdentity(),
        profileScope: "full_dataset",
        profiledRowCount: ROWS.length,
        registeredRowCount: ROWS.length,
        problemType: "classification",
        target: TARGET,
        eventValue: 1,
        selectedColumns: FEATURES,
        featureManifestVersion: MANIFEST_VERSION,
        features: featureRows().map((row) => ({
          selected: true,
          predictor: row.feature_name,
          role: "predictor",
          datatype: row.output_datatype,
          iv: row.summary_statistics.information_value,
          ivStrength: "medium",
          correlationWithTarget: 0.1,
          correlationStrength: "weak",
          associationStatus: "evaluated",
          missingCount: 0,
          missingPercent: 0,
          distinctCount: row.summary_statistics.distinct_count,
          mean: row.summary_statistics.mean,
          standardDeviation: row.summary_statistics.standard_deviation,
          minimum: row.summary_statistics.minimum,
          firstQuartile: 1,
          median: 2,
          thirdQuartile: 3,
          maximum: row.summary_statistics.maximum,
          leakageStatus: "eligible",
          eligibilityStatus: "eligible",
          exclusionReason: "",
          origin: "original",
          sourceFeatures: [row.feature_name],
          transformationType: "identity",
          formulaOrRule: row.feature_name,
          materializationStatus: "source",
          featureId: row.feature_id,
        })),
      });
      return;
    }
    if (url.pathname === "/api/balancing_split/status" && method === "GET") {
      await fulfillJson(route, splitStatus());
      return;
    }
    if (url.pathname === "/api/models/availability" && method === "GET") {
      await fulfillJson(route, {
        ok: true,
        availability: { logreg: true, dtree: true, rf: true },
        labels: { logreg: "Logistic Regression", dtree: "Decision Tree", rf: "Random Forest" },
      });
      return;
    }
    if (url.pathname === "/api/train/last" && method === "GET") {
      await fulfillJson(route, { ok: true, summary: null });
      return;
    }
    if (url.pathname === "/api/model/train/jobs/active" && method === "GET") {
      await fulfillJson(route, { ok: true, jobs: [] });
      return;
    }
    if (url.pathname === "/api/model/train/selection" && method === "GET") {
      await fulfillJson(route, { ok: true, ...canonicalIdentity(), selection: null, selected_algorithm_ids: [] });
      return;
    }
    if (url.pathname === "/api/preparation/documentation" && method === "GET") {
      await fulfillJson(route, {
        ok: true,
        ...canonicalIdentity(),
        dataset_version: DATASET_VERSION_ID,
        target: TARGET,
        predictor_manifest_id: "predictor-auth-route-matrix-r1",
        documentation_version: "preparation-route-matrix-r1",
        status: "draft",
        predictor_authorization: {
          authorized_predictors: FEATURES,
          excluded_predictors: { [TARGET]: "target" },
          target_source_excluded: [TARGET],
        },
        outliers: { status: "draft", application: null },
        missing_values: { status: "draft", application: null, validation: null },
        feature_engineering: {
          status: "draft",
          manifest_version: MANIFEST_VERSION,
          manifest_hash: "feature-manifest-route-matrix-hash-r1",
          accepted_features: [],
          materialized_features: [],
          pipeline_steps: [],
          split_status: "not_created",
        },
        validation_design: {
          status: "draft",
          validation_design_id: null,
          design_version: null,
          strategy: null,
          completion_gates: {},
        },
        model_training: {
          status: "draft",
          training_job_id: null,
          job_status: null,
          model_portfolio: [],
          ranked_candidates: [],
        },
        governance: {
          backend_enforced: true,
          target_source_excluded: [TARGET],
          automatic_feature_acceptance: false,
          automatic_row_removal: false,
        },
      });
      return;
    }
    if (url.pathname === "/api/notifications/unread-count") {
      await fulfillJson(route, { ok: true, count: 0 });
      return;
    }
    if (url.pathname === "/api/datasets" && method === "GET") {
      await fulfillJson(route, { ok: true, datasets: [], currentUser: { userId: USER_ID } });
      return;
    }
    if (url.pathname.includes("/carry-forward") && method === "GET") {
      await fulfillJson(route, { ok: true, ...canonicalIdentity(), items: [], dispositions: [] });
      return;
    }
    if (url.pathname.includes("/documentation") && method === "GET") {
      await fulfillJson(route, { ok: true, ...canonicalIdentity(), status: "draft", sections: {} });
      return;
    }
    await fulfillJson(route, {
      ok: true,
      ...canonicalIdentity(),
      count: 0,
      items: [],
      rows: [],
      features: [],
      findings: [],
      notifications: [],
    });
  });
  return audit;
}

async function assertRouteIntegrity(
  page: Page,
  step: string,
  expectedLabel: RegExp,
  renderSignal: string,
  audit?: NetworkAudit,
) {
  await expect(page).toHaveURL(new RegExp(`/projects/${PROJECT_ID}/${step}(?:\\?|$)`));
  const breadcrumb = page.getByTestId("atlas-breadcrumb");
  await expect(breadcrumb).toHaveAttribute("data-project-context-status", "ready");
  await expect(breadcrumb).toContainText(PROJECT_NAME);
  await expect(page.locator("#root")).not.toBeEmpty();
  await expect(page.locator("body")).toContainText(expectedLabel);
  await expect(page.locator(renderSignal).first()).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Untitled ATLAS Project");
  await page.waitForTimeout(750);
  if (await page.locator("body").getByText("This workflow route could not be rendered safely", { exact: false }).count()) {
    throw new Error(`Safe route boundary rendered on ${step}. ${JSON.stringify({
      pageErrors: audit?.pageErrors,
      consoleErrors: audit?.consoleErrors,
      requests: audit?.requests.slice(-30),
    })}`);
  }
  await expect(page.locator("body")).not.toContainText("This workflow route could not be rendered safely", { timeout: 1_000 });
  await expect(page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
  await expect(page.getByTestId("project-context-gate")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("Loading project context...");

  const stored = await page.evaluate(({ userId, projectId }) => {
    const raw = sessionStorage.getItem(`atlas:modeling-dataset:${userId}:${projectId}`);
    const workflow = JSON.parse(sessionStorage.getItem("ds-workflow-store") || "null");
    return {
      dataset: raw ? JSON.parse(raw) : null,
      workflowProjectId: workflow?.state?.projectId ?? null,
      workflowIdentity: workflow?.state?.datasetIdentity ?? null,
    };
  }, { userId: USER_ID, projectId: PROJECT_ID });
  expect(stored.workflowProjectId).toBe(PROJECT_ID);
  expect(stored.workflowIdentity).toMatchObject({
    project_id: PROJECT_ID,
    dataset_id: DATASET_ID,
    dataset_version_id: DATASET_VERSION_ID,
  });
  expect(stored.dataset).toMatchObject({
    dataset_id: DATASET_ID,
    dataset_version_id: DATASET_VERSION_ID,
    target: TARGET,
  });
}

test("project-scoped Predictive Modeling route matrix preserves exact identity through Model Training", async ({ page }) => {
  test.setTimeout(180_000);
  const audit = await installMocks(page);
  const routes = [
    ["step00", /Project Setup|Project Context Review/i, '[data-testid="model-identity-card"]'],
    ["step01", /Source and Target/i, '[data-testid="source-command-section"]'],
    ["step02", /Exploratory Data Analysis/i, '[data-testid="eda-overview-launch-surface"]'],
    ["step03", /Outliers/i, '[data-testid="outlier-feature-summary-table"]'],
    ["step04", /Missing Values/i, '[data-testid="missing-values-zero-state"], [data-testid="missing-all-feature-table"]'],
    ["step05", /Feature Engineering/i, '[data-testid="feature-set-review"]'],
    ["step06", /Training and Validation Design|Balance & Split/i, '[data-testid="immutable-analysis-partition"]'],
    ["step07", /Model Training|Training Mission Control/i, '[data-testid="training-mission-control"]'],
  ] as const;

  for (const [step, label, renderSignal] of routes) {
    await page.goto(`/projects/${PROJECT_ID}/${step}?route-matrix=1`);
    await assertRouteIntegrity(page, step, label, renderSignal, audit);
  }

  await page.goBack();
  await assertRouteIntegrity(page, "step06", /Training and Validation Design|Balance & Split/i, '[data-testid="immutable-analysis-partition"]', audit);
  await page.goBack();
  await assertRouteIntegrity(page, "step05", /Feature Engineering/i, '[data-testid="feature-set-review"]', audit);
  await page.goForward();
  await assertRouteIntegrity(page, "step06", /Training and Validation Design|Balance & Split/i, '[data-testid="immutable-analysis-partition"]', audit);
  await page.goForward();
  await assertRouteIntegrity(page, "step07", /Model Training|Training Mission Control/i, '[data-testid="training-mission-control"]', audit);

  expect(audit.pageErrors).toEqual([]);
  expect(audit.serverErrors).toEqual([]);
  expect(
    audit.requests.filter((request) =>
      request.method !== "GET"
      && /\/model\/train|\/train(?:\/|$)|\/balancing_split\/config|\/features\/(?:confirm|materialize)/.test(request.pathname),
    ),
    "The route matrix must not complete governance actions or start training.",
  ).toEqual([]);
  expect(
    audit.requests.filter((request) =>
      /final[-_]?holdout|sealed[-_]?holdout/i.test(`${request.pathname} ${request.body}`),
    ),
    "No request may access final-holdout data during the route matrix.",
  ).toEqual([]);
});

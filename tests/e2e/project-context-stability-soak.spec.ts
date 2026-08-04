import {
  expect,
  test,
  type BrowserContext,
  type Page,
  type Route,
} from "@playwright/test";

const FULL_SOAK = process.env.ATLAS_PROJECT_CONTEXT_SOAK === "1";
const SMOKE_SOAK = process.env.ATLAS_PROJECT_CONTEXT_SOAK_SMOKE === "1";
const DATASET_ID = "ds_project_context_soak_fixture";
const DATASET_VERSION_ID = "v_project_context_soak_fixture_001";
const FEATURES = ["ExternalRiskEstimate", "NumTrades60Ever2DerogPubRec"];
const ROWS = Array.from({ length: 24 }, (_, index) => ({
  ExternalRiskEstimate: 42 + index * 2,
  NumTrades60Ever2DerogPubRec: index % 7,
  bad_flag: index % 3 === 0 ? 1 : 0,
}));
const TRACKED_EVENTS = [
  "atlas-dataset-identity-updated",
  "atlas-project-context-updated",
  "popstate",
  "storage",
] as const;

function integerSetting(name: string, fallback: number, minimum: number) {
  const parsed = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isFinite(parsed) ? Math.max(minimum, parsed) : fallback;
}

const soak = {
  contexts: FULL_SOAK
    ? integerSetting("ATLAS_SOAK_CONTEXTS", 5, 5)
    : integerSetting("ATLAS_SOAK_CONTEXTS", 5, 2),
  domSamples: FULL_SOAK
    ? integerSetting("ATLAS_SOAK_DOM_SAMPLES", 1_000, 1_000)
    : integerSetting("ATLAS_SOAK_DOM_SAMPLES", 20, 1),
  reloads: FULL_SOAK
    ? integerSetting("ATLAS_SOAK_RELOADS", 100, 100)
    : integerSetting("ATLAS_SOAK_RELOADS", 2, 0),
  historyCycles: FULL_SOAK
    ? integerSetting("ATLAS_SOAK_HISTORY_CYCLES", 100, 100)
    : integerSetting("ATLAS_SOAK_HISTORY_CYCLES", 2, 0),
  metadataSaves: FULL_SOAK
    ? integerSetting("ATLAS_SOAK_METADATA_SAVES", 100, 100)
    : integerSetting("ATLAS_SOAK_METADATA_SAVES", 2, 0),
  sampleIntervalMs: FULL_SOAK
    ? integerSetting("ATLAS_SOAK_SAMPLE_INTERVAL_MS", 25, 0)
    : integerSetting("ATLAS_SOAK_SAMPLE_INTERVAL_MS", 0, 0),
  minRuntimeMs: FULL_SOAK
    ? integerSetting("ATLAS_SOAK_MIN_RUNTIME_MS", 30 * 60_000, 30 * 60_000)
    : integerSetting("ATLAS_SOAK_MIN_RUNTIME_MS", 0, 0),
};

type RequestStats = {
  authGets: number;
  projectGets: number;
  projectPuts: number;
  workflowGets: number;
  identityGets: number;
  sampleGets: number;
  overviewPosts: number;
  documentationGets: number;
  documentationDrafts: number;
  otherRequests: Array<{ method: string; pathname: string }>;
};

type SoakProbe = {
  modelMounts: number;
  modelUnmounts: number;
  edaMounts: number;
  edaUnmounts: number;
  safeBoundaryMounts: number;
  hydrationStarts: number;
  hydrationCompletes: number;
  providerStatuses: string[];
  projectContextEvents: number;
  listenerAdds: Record<string, number>;
  listenerRemoves: Record<string, number>;
  listenerActive: Record<string, number>;
};

type IsolatedFixture = {
  context: BrowserContext;
  page: Page;
  projectId: string;
  projectName: string;
  userId: string;
  stats: RequestStats;
  pageErrors: string[];
};

async function fulfillJson(
  route: Route,
  status: number,
  body: Record<string, unknown>,
) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function projectContext(projectId: string, projectName: string) {
  return {
    modelId: `model-${projectId}`,
    projectName,
    modelType: "generic classification",
    modelTypeSelection: "Generic Binary Classification",
    businessObjective: "Exercise a synthetic Project Context stability fixture.",
    intendedModelUse: "Verify lifecycle stability without using a live project.",
    targetDefinition: "Predict the isolated synthetic event.",
    populationDefinition: "Synthetic browser-test records only.",
    observationWindow: "Synthetic observations available before the event.",
    performanceWindow: "Synthetic outcomes observed after the event.",
  };
}

function projectRecord(
  projectId: string,
  projectName: string,
  userId: string,
  metadataContext = projectContext(projectId, projectName),
) {
  return {
    projectId,
    projectName,
    projectType: "predictive-modeling",
    workflowType: "predictive-modeling",
    ownerUserId: userId,
    status: "active",
    activeSelection: {
      projectId,
      datasetId: DATASET_ID,
      datasetVersionId: DATASET_VERSION_ID,
    },
    metadata: {
      modelId: `model-${projectId}`,
      hasDataset: true,
      projectTools: {},
      projectContextRevision: "1000-soak-initial",
      projectContextSavedAt: "2026-08-03T12:00:00.000Z",
      projectContext: metadataContext,
    },
    createdAt: "2026-08-03T12:00:00.000Z",
    updatedAt: "2026-08-03T12:00:00.000Z",
  };
}

function workflowState(projectId: string) {
  return {
    projectId,
    currentStepId: "step02",
    updatedAt: "2026-08-03T12:00:00.000Z",
    workflowStatus: {
      workflowId: "predictive-modeling",
      projectType: "predictive-modeling",
      hasDataset: true,
      datasetIdentity: {
        project_id: projectId,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        activation_revision: 1,
      },
      steps: {
        step00: "complete",
        step01: "complete",
        step02: "in_progress",
      },
    },
  };
}

function overviewPayload(projectId: string) {
  return {
    ok: true,
    project_id: projectId,
    dataset_id: DATASET_ID,
    dataset_version_id: DATASET_VERSION_ID,
    dataset_version: DATASET_VERSION_ID,
    section: "overview",
    scope: "development_population",
    row_count: 100,
    column_count: 2,
    target: "bad_flag",
    problem_type: "classification",
    event_value: 1,
    duration_ms: 1,
    cache_status: "hit",
    headline: {
      rows: 100,
      predictors: 1,
      numeric_predictors: 1,
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
      valid_count: 100,
      missing_count: 0,
      class_count: 2,
      event_rate: 0.5,
      class_distribution: [
        { value: 0, count: 50, rate: 0.5 },
        { value: 1, count: 50, rate: 0.5 },
      ],
    },
    available_fields: {
      numeric: ["ExternalRiskEstimate"],
      categorical: [],
      date_candidates: [],
      segment_candidates: [],
    },
    predictor_authorization: {
      manifest_version: "manifest-project-context-soak",
      authorized_predictors: ["ExternalRiskEstimate"],
      target_source_excluded: [],
    },
    target_source_excluded: [],
  };
}

function analysisPartition(projectId: string) {
  return {
    ok: true,
    project_id: projectId,
    dataset_id: DATASET_ID,
    dataset_version_id: DATASET_VERSION_ID,
    dataset_version: DATASET_VERSION_ID,
    status: "current",
    ready: true,
    analysis_partition_id: `analysis-partition-${projectId}-r1`,
    revision: 1,
    development_partition_id: `development-${projectId}-r1`,
    development_rows: 19,
    development_share: 0.8,
    holdout_share: 0.2,
    final_holdout_status: "sealed",
    holdout_isolation_status: "verified",
    target: "bad_flag",
    target_contract_id: `target-contract-${projectId}-r1`,
    predictor_authorization_id: `predictor-auth-${projectId}-r1`,
    random_seed: 42,
    stratification_policy: "target",
    stratification_field: "bad_flag",
  };
}

function featureProfileRows(projectId: string) {
  return FEATURES.map((predictor, index) => ({
    selected: true,
    predictor,
    role: "predictor",
    datatype: "float64",
    iv: index ? 0.11 : 0.32,
    ivStrength: "medium",
    correlationWithTarget: 0.1,
    correlationStrength: "weak",
    associationStatus: "evaluated",
    missingCount: 0,
    missingPercent: 0,
    distinctCount: index ? 7 : 24,
    mean: index ? 2.8 : 65,
    standardDeviation: index ? 1.9 : 14,
    minimum: 0,
    firstQuartile: 1,
    median: 2,
    thirdQuartile: 3,
    maximum: index ? 6 : 88,
    leakageStatus: "eligible",
    eligibilityStatus: "eligible",
    exclusionReason: "",
    origin: "original",
    sourceFeatures: [predictor],
    transformationType: "identity",
    formulaOrRule: predictor,
    materializationStatus: "source",
    featureId: `feature-${projectId}-${index + 1}`,
  }));
}

async function installProbe(page: Page) {
  await page.addInitScript(({ trackedEvents }) => {
    const probe: SoakProbe = {
      modelMounts: 0,
      modelUnmounts: 0,
      edaMounts: 0,
      edaUnmounts: 0,
      safeBoundaryMounts: 0,
      hydrationStarts: 0,
      hydrationCompletes: 0,
      providerStatuses: [],
      projectContextEvents: 0,
      listenerAdds: {},
      listenerRemoves: {},
      listenerActive: {},
    };
    (window as any).__atlasProjectContextSoak = probe;

    const tracked = new Set<string>(trackedEvents);
    const active = new Map<string, Set<EventListenerOrEventListenerObject>>();
    const originalAdd = window.addEventListener.bind(window);
    const originalRemove = window.removeEventListener.bind(window);
    (window.addEventListener as any) = (
      type: string,
      listener: EventListenerOrEventListenerObject,
      options?: boolean | AddEventListenerOptions,
    ) => {
      if (tracked.has(type) && listener) {
        const listeners = active.get(type) ?? new Set<EventListenerOrEventListenerObject>();
        if (!listeners.has(listener)) {
          listeners.add(listener);
          active.set(type, listeners);
          probe.listenerAdds[type] = (probe.listenerAdds[type] ?? 0) + 1;
          probe.listenerActive[type] = listeners.size;
        }
      }
      return originalAdd(type as keyof WindowEventMap, listener as any, options as any);
    };
    (window.removeEventListener as any) = (
      type: string,
      listener: EventListenerOrEventListenerObject,
      options?: boolean | EventListenerOptions,
    ) => {
      if (tracked.has(type) && listener) {
        const listeners = active.get(type);
        if (listeners?.delete(listener)) {
          probe.listenerRemoves[type] = (probe.listenerRemoves[type] ?? 0) + 1;
          probe.listenerActive[type] = listeners.size;
        }
      }
      return originalRemove(type as keyof WindowEventMap, listener as any, options as any);
    };

    originalAdd("atlas-project-context-updated", () => {
      probe.projectContextEvents += 1;
    });

    let modelPresent = false;
    let edaPresent = false;
    let safeBoundaryPresent = false;
    let lastProviderStatus = "";
    const sample = () => {
      const nextModelPresent = Boolean(
        document.querySelector('[data-testid="model-identity-card"]'),
      );
      if (nextModelPresent && !modelPresent) probe.modelMounts += 1;
      if (!nextModelPresent && modelPresent) probe.modelUnmounts += 1;
      modelPresent = nextModelPresent;

      const nextEdaPresent = Boolean(
        document.querySelector('[data-testid="eda-overview-launch-surface"]'),
      );
      if (nextEdaPresent && !edaPresent) probe.edaMounts += 1;
      if (!nextEdaPresent && edaPresent) probe.edaUnmounts += 1;
      edaPresent = nextEdaPresent;

      const nextSafeBoundaryPresent = Boolean(
        document.querySelector('[data-testid="atlas-safe-error-boundary"]'),
      );
      if (nextSafeBoundaryPresent && !safeBoundaryPresent) {
        probe.safeBoundaryMounts += 1;
      }
      safeBoundaryPresent = nextSafeBoundaryPresent;

      const providerStatus =
        document
          .querySelector('[data-testid="atlas-breadcrumb"]')
          ?.getAttribute("data-project-context-status") ?? "";
      if (providerStatus && providerStatus !== lastProviderStatus) {
        probe.providerStatuses.push(providerStatus);
        if (providerStatus === "resolving") probe.hydrationStarts += 1;
        if (providerStatus === "ready") probe.hydrationCompletes += 1;
        lastProviderStatus = providerStatus;
      }
    };
    const start = () => {
      sample();
      new MutationObserver(sample).observe(document.documentElement, {
        attributes: true,
        childList: true,
        subtree: true,
        attributeFilter: ["data-project-context-status", "data-testid"],
      });
    };
    if (document.documentElement) start();
    else document.addEventListener("DOMContentLoaded", start, { once: true });
  }, { trackedEvents: [...TRACKED_EVENTS] });
}

async function installMocks(
  page: Page,
  projectId: string,
  projectName: string,
  userId: string,
) {
  const stats: RequestStats = {
    authGets: 0,
    projectGets: 0,
    projectPuts: 0,
    workflowGets: 0,
    identityGets: 0,
    sampleGets: 0,
    overviewPosts: 0,
    documentationGets: 0,
    documentationDrafts: 0,
    otherRequests: [],
  };
  let record: Record<string, any> = projectRecord(projectId, projectName, userId);

  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method().toUpperCase();
    const pathname = url.pathname;

    if (pathname === "/api/auth/me" && method === "GET") {
      stats.authGets += 1;
      await fulfillJson(route, 200, {
        ok: true,
        user: {
          userId,
          displayName: `Soak User ${userId}`,
          email: `${userId}@example.test`,
          role: "user",
          status: "active",
        },
      });
      return;
    }

    if (pathname === `/api/projects/${projectId}` && method === "GET") {
      stats.projectGets += 1;
      await fulfillJson(route, 200, { ok: true, project: record });
      return;
    }

    if (pathname === `/api/projects/${projectId}` && method === "PUT") {
      stats.projectPuts += 1;
      const body = request.postDataJSON() as Record<string, any>;
      const metadata = {
        ...(record.metadata as Record<string, unknown>),
        ...(body.metadata ?? {}),
      } as Record<string, any>;
      record = {
        ...record,
        projectName: String(body.projectName ?? record.projectName),
        metadata,
        updatedAt: String(metadata.projectContextSavedAt ?? record.updatedAt),
      };
      await fulfillJson(route, 200, { ok: true, project: record });
      return;
    }

    if (
      pathname === `/api/projects/${projectId}/workflow-state`
      && method === "GET"
    ) {
      stats.workflowGets += 1;
      await fulfillJson(route, 200, {
        ok: true,
        workflowState: workflowState(projectId),
      });
      return;
    }

    if (pathname === "/api/data/active-identity" && method === "GET") {
      stats.identityGets += 1;
      await fulfillJson(route, 200, {
        ok: true,
        project_id: projectId,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        dataset_version_label: "Project Context soak version",
        dataset_source_type: "dataset-library",
        activation_revision: 1,
        target: "bad_flag",
      });
      return;
    }

    if (pathname === "/api/data/get_sample" && method === "GET") {
      stats.sampleGets += 1;
      await fulfillJson(route, 200, {
        ok: true,
        project_id: projectId,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        dataset_version: DATASET_VERSION_ID,
        headers: [...FEATURES, "bad_flag"],
        rows: ROWS,
        target: "bad_flag",
        selected_columns: FEATURES,
        registered_row_count: ROWS.length,
        row_count: ROWS.length,
      });
      return;
    }

    if (pathname === "/api/train/last" && method === "GET") {
      await fulfillJson(route, 200, { ok: true, summary: null });
      return;
    }

    if (pathname === `/api/datasets/${DATASET_ID}` && method === "GET") {
      const version = {
        versionId: DATASET_VERSION_ID,
        createdAt: "2026-08-03T12:00:00.000Z",
        createdBy: userId,
        originalFilename: "project-context-soak.csv",
        hash: "project-context-soak-hash-r1",
        rowCount: ROWS.length,
        columnCount: FEATURES.length + 1,
        warnings: [],
      };
      await fulfillJson(route, 200, {
        ok: true,
        dataset: {
          datasetId: DATASET_ID,
          name: "Project Context soak fixture",
          description: "Isolated browser-test dataset.",
          domain: "testing",
          sourceType: "isolated-fixture",
          ownerUserId: userId,
          createdAt: "2026-08-03T12:00:00.000Z",
          updatedAt: "2026-08-03T12:00:00.000Z",
          archived: false,
          versionCount: 1,
          latestVersion: version,
          versions: [version],
          linkedProjects: [{
            projectId,
            versionId: DATASET_VERSION_ID,
            datasetRole: "modeling",
          }],
        },
      });
      return;
    }

    if (pathname === "/api/analysis-partitions/status" && method === "GET") {
      await fulfillJson(route, 200, {
        ok: true,
        project_id: projectId,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        readiness: "current",
        status: "current",
        code: "analysis_partition_current",
        reused: true,
        analysis_partition: {
          ...analysisPartition(projectId),
          positive_value: 1,
          negative_value: 0,
        },
      });
      return;
    }

    if (pathname === "/api/data/quality-profile" && method === "POST") {
      await fulfillJson(route, 200, {
        ok: true,
        project_id: projectId,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        profileScope: "full_dataset",
        profiledRowCount: ROWS.length,
        registeredRowCount: ROWS.length,
        generatedAt: "2026-08-03T12:00:00.000Z",
        datasetHash: "project-context-soak-hash-r1",
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
        missingness: [...FEATURES, "bad_flag"].map((column) => ({
          column,
          count: 0,
          percent: 0,
        })),
        memoryEstimateMb: 0.01,
        warnings: [],
        readinessStatus: "ready",
      });
      return;
    }

    if (pathname === "/api/data/feature-profile" && method === "POST") {
      await fulfillJson(route, 200, {
        ok: true,
        project_id: projectId,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        profileScope: "full_dataset",
        profiledRowCount: ROWS.length,
        registeredRowCount: ROWS.length,
        problemType: "classification",
        target: "bad_flag",
        eventValue: 1,
        selectedColumns: FEATURES,
        featureManifestVersion: `manifest-${projectId}-r1`,
        features: featureProfileRows(projectId),
      });
      return;
    }

    if (pathname === "/api/data/target-profile" && method === "POST") {
      const profileRequest = request.postDataJSON() as { include_iv?: boolean };
      await fulfillJson(route, 200, {
        ok: true,
        analysisScope: {
          mode: "governed_version",
          label: "Development Population",
          projectId,
          datasetId: DATASET_ID,
          datasetVersionId: DATASET_VERSION_ID,
          datasetName: "Project Context soak version",
          datasetFingerprint: "project-context-soak-hash-r1",
          artifactChecksum: "project-context-soak-checksum-r1",
          target: "bad_flag",
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
        scopeIdentity: `${projectId}:${DATASET_ID}:${DATASET_VERSION_ID}:development-r1`,
        profileScope: "governed_version",
        calculationVersion: "project-context-soak-r1",
        generatedAt: "2026-08-03T12:00:00.000Z",
        datasetId: DATASET_ID,
        datasetVersionId: DATASET_VERSION_ID,
        datasetName: "Project Context soak version",
        artifactChecksum: "project-context-soak-checksum-r1",
        target: "bad_flag",
        targetMapping: {
          target: "bad_flag",
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
          ivStrength: profileRequest.include_iv === false
            ? null
            : { key: "medium", label: "Medium" },
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
        cached: true,
      });
      return;
    }

    if (pathname === "/api/analytics/target-distribution" && method === "POST") {
      await fulfillJson(route, 200, {
        ok: true,
        supported: true,
        resolution: "exact",
        projectId,
        datasetId: DATASET_ID,
        versionId: DATASET_VERSION_ID,
        target: "bad_flag",
        classDistribution: [
          { value: 0, count: 16, percent: 2 / 3 },
          { value: 1, count: 8, percent: 1 / 3 },
        ],
        totalRowCount: ROWS.length,
        artifactFormat: "parquet",
        engine: "isolated-fixture",
        cached: true,
        durationMs: 1,
      });
      return;
    }

    if (pathname === "/api/data/bureau-detection" && method === "POST") {
      await fulfillJson(route, 200, {
        ok: true,
        project_id: projectId,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        scope: "full_dataset",
        row_count: ROWS.length,
        target: "bad_flag",
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
        predictor_authorization_id: `predictor-auth-${projectId}-r1`,
        target_contract_id: `target-contract-${projectId}-r1`,
        correlation_id: `project-context-soak-${projectId}-r1`,
        target_analysis_scope: "development_partition",
        analysis_partition_id: `analysis-partition-${projectId}-r1`,
        development_partition_id: `development-${projectId}-r1`,
        final_holdout_accessed: false,
      });
      return;
    }

    if (
      pathname === `/api/projects/${projectId}/workflow-state`
      && method === "PUT"
    ) {
      await fulfillJson(route, 200, {
        ok: true,
        workflowState: request.postDataJSON() as Record<string, unknown>,
      });
      return;
    }

    if (pathname === "/api/eda/workspace/overview" && method === "POST") {
      stats.overviewPosts += 1;
      await fulfillJson(route, 200, overviewPayload(projectId));
      return;
    }

    if (
      pathname === `/api/eda/documentation/${projectId}`
      && method === "GET"
    ) {
      stats.documentationGets += 1;
      await fulfillJson(route, 200, {
        ok: true,
        project_id: projectId,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        dataset_version: DATASET_VERSION_ID,
        status: "missing",
        draft: null,
        current_approved: null,
        history: [],
        source_lineage: {
          project_id: projectId,
          dataset_id: DATASET_ID,
          dataset_version_id: DATASET_VERSION_ID,
          dataset_version: DATASET_VERSION_ID,
          target: "bad_flag",
          predictor_manifest_id: "manifest-project-context-soak",
        },
      });
      return;
    }

    if (pathname === "/api/eda/documentation/draft" && method === "POST") {
      stats.documentationDrafts += 1;
      const draft = request.postDataJSON() as Record<string, unknown>;
      await fulfillJson(route, 200, {
        ok: true,
        project_id: projectId,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        dataset_version: DATASET_VERSION_ID,
        status: "draft",
        draft,
        current_approved: null,
        history: [],
        source_lineage: {
          project_id: projectId,
          dataset_id: DATASET_ID,
          dataset_version_id: DATASET_VERSION_ID,
          dataset_version: DATASET_VERSION_ID,
          target: "bad_flag",
          predictor_manifest_id: "manifest-project-context-soak",
        },
      });
      return;
    }

    if (pathname === "/api/notifications/unread-count") {
      await fulfillJson(route, 200, { ok: true, count: 0 });
      return;
    }

    stats.otherRequests.push({ method, pathname });
    await fulfillJson(route, 200, {
      ok: true,
      count: 0,
      items: [],
      rows: [],
      headers: [],
      datasets: [],
      versions: [],
      notifications: [],
      findings: [],
      partitions: [],
    });
  });

  return stats;
}

async function readProbe(page: Page) {
  return page.evaluate(
    () => ({ ...(window as any).__atlasProjectContextSoak }) as SoakProbe,
  );
}

async function expectStableProjectContext(page: Page, projectName: string) {
  await expect(page.getByTestId("model-identity-card")).toBeVisible();
  await expect(page.getByTestId("project-context-gate")).toHaveCount(0);
  await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
    "data-project-context-status",
    "ready",
  );
  await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
    "data-breadcrumb",
    new RegExp(projectName),
  );
  await expect(page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
}

async function expectProjectRequestsQuiescent(
  page: Page,
  stats: RequestStats,
  label: string,
) {
  await page.waitForTimeout(500);
  const settled = {
    projectGets: stats.projectGets,
    workflowGets: stats.workflowGets,
    identityGets: stats.identityGets,
  };
  await page.waitForTimeout(500);
  expect(
    {
      projectGets: stats.projectGets,
      workflowGets: stats.workflowGets,
      identityGets: stats.identityGets,
    },
    `${label} continued requesting project or dataset authority after the composition settled.`,
  ).toEqual(settled);
}

async function expectNoSafeBoundary(page: Page, phase: string) {
  const boundary = page.getByTestId("atlas-safe-error-boundary");
  if (await boundary.count()) {
    throw new Error(`${phase} rendered the safe error boundary: ${await boundary.innerText()}`);
  }
}

function activeListeners(probe: SoakProbe) {
  return Object.fromEntries(
    TRACKED_EVENTS.map((eventName) => [
      eventName,
      probe.listenerActive[eventName] ?? 0,
    ]),
  );
}

test.describe("Project Context stability soak", () => {
  test.skip(
    !FULL_SOAK && !SMOKE_SOAK,
    "Set ATLAS_PROJECT_CONTEXT_SOAK=1 for the full soak or ATLAS_PROJECT_CONTEXT_SOAK_SMOKE=1 for a short validation.",
  );

  test("actual composition remains stable under saves, reloads, history, and isolated contexts", async ({
    browser,
  }) => {
    test.setTimeout(soak.minRuntimeMs + 30 * 60_000);
    const startedAt = Date.now();
    const fixtures: IsolatedFixture[] = [];

    try {
      for (let index = 0; index < soak.contexts; index += 1) {
        const projectId = `project-context-soak-${index + 1}`;
        const projectName = `Project Context Soak ${index + 1}`;
        const userId = index % 2 === 0 ? "project-context-soak-user-a" : "project-context-soak-user-b";
        const context = await browser.newContext();
        const page = await context.newPage();
        await installProbe(page);
        const stats = await installMocks(page, projectId, projectName, userId);
        const pageErrors: string[] = [];
        page.on("pageerror", (error) => pageErrors.push(error.message));
        await page.goto(`/projects/${projectId}/step00`);
        await expectStableProjectContext(page, projectName);
        await expectProjectRequestsQuiescent(page, stats, projectId);
        expect(pageErrors, `Unexpected page errors for ${projectId}`).toEqual([]);
        fixtures.push({ context, page, projectId, projectName, userId, stats, pageErrors });
      }

      expect(new Set(fixtures.map(({ userId }) => userId)).size).toBeGreaterThanOrEqual(2);
      expect(new Set(fixtures.map(({ projectId }) => projectId)).size).toBe(soak.contexts);

      const primary = fixtures[0];
      const objective = primary.page.locator(
        'textarea[placeholder^="What decision or business process"]',
      );
      for (let index = 0; index < soak.metadataSaves; index += 1) {
        await objective.fill(`Synthetic governed stability save ${index + 1}.`);
        await expect.poll(
          () => primary.stats.projectPuts,
          { timeout: 15_000 },
        ).toBe(index + 1);
        await expect(primary.page.getByTestId("project-context-save-status")).toHaveAttribute(
          "data-save-status",
          "saved",
        );
      }

      let probe = await readProbe(primary.page);
      expect(probe.projectContextEvents).toBe(soak.metadataSaves);
      expect(probe.hydrationStarts).toBe(1);
      expect(probe.hydrationCompletes).toBe(1);
      expect(probe.safeBoundaryMounts).toBe(0);
      await expectProjectRequestsQuiescent(
        primary.page,
        primary.stats,
        "metadata-save phase",
      );

      for (let index = 0; index < soak.domSamples; index += 1) {
        const sample = await primary.page.evaluate(() => ({
          model: Boolean(document.querySelector('[data-testid="model-identity-card"]')),
          gate: Boolean(document.querySelector('[data-testid="project-context-gate"]')),
          error: Boolean(document.querySelector('[data-testid="atlas-safe-error-boundary"]')),
          status:
            document
              .querySelector('[data-testid="atlas-breadcrumb"]')
              ?.getAttribute("data-project-context-status") ?? "",
        }));
        expect(sample).toEqual({ model: true, gate: false, error: false, status: "ready" });
        if (soak.sampleIntervalMs > 0) {
          await primary.page.waitForTimeout(soak.sampleIntervalMs);
        }
      }

      const projectGetsBeforeReloads = primary.stats.projectGets;
      let previousProjectGets = projectGetsBeforeReloads;
      for (let index = 0; index < soak.reloads; index += 1) {
        await primary.page.reload();
        await expectStableProjectContext(primary.page, primary.projectName);
        await primary.page.waitForTimeout(250);
        const reloadProbe = await readProbe(primary.page);
        expect(reloadProbe.hydrationStarts).toBe(1);
        expect(reloadProbe.hydrationCompletes).toBe(1);
        expect(reloadProbe.modelMounts).toBe(1);
        expect(reloadProbe.modelUnmounts).toBe(0);
        expect(reloadProbe.safeBoundaryMounts).toBe(0);
        const reloadProjectGets = primary.stats.projectGets - previousProjectGets;
        expect(reloadProjectGets).toBeGreaterThanOrEqual(1);
        expect(
          reloadProjectGets,
          `Reload ${index + 1} exceeded the four-request composition hydration ceiling.`,
        ).toBeLessThanOrEqual(4);
        previousProjectGets = primary.stats.projectGets;
      }
      expect(primary.stats.projectGets - projectGetsBeforeReloads).toBeLessThanOrEqual(
        soak.reloads * 4,
      );
      await expectProjectRequestsQuiescent(primary.page, primary.stats, "reload phase");

      await primary.page.getByRole("link", { name: "Data Acquisition", exact: true }).click();
      await expect(primary.page).toHaveURL(new RegExp(`/projects/${primary.projectId}/step01`));
      await primary.page.waitForTimeout(1_000);
      await expectNoSafeBoundary(
        primary.page,
        `Initial Data Acquisition route; requests=${JSON.stringify(primary.stats.otherRequests)}`,
      );
      await expect(primary.page.getByTestId("source-command-section")).toBeVisible();
      await primary.page.getByRole("link", { name: "EDA", exact: true }).click();
      await expect(primary.page).toHaveURL(new RegExp(`/projects/${primary.projectId}/step02`));
      await expect(primary.page.getByTestId("eda-overview-launch-surface")).toBeVisible();
      const listenerBaseline = activeListeners(await readProbe(primary.page));

      for (let index = 0; index < soak.historyCycles; index += 1) {
        await primary.page.goBack();
        await expect(primary.page).toHaveURL(new RegExp(`/projects/${primary.projectId}/step01`));
        await expect(primary.page.getByTestId("source-command-section")).toBeVisible();
        await expectNoSafeBoundary(primary.page, `History cycle ${index + 1} Data Acquisition back`);
        await primary.page.goBack();
        await expect(primary.page).toHaveURL(new RegExp(`/projects/${primary.projectId}/step00`));
        await expect(primary.page.getByTestId("model-identity-card")).toBeVisible();
        await expect(primary.page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
        await primary.page.goForward();
        await expect(primary.page).toHaveURL(new RegExp(`/projects/${primary.projectId}/step01`));
        await expect(primary.page.getByTestId("source-command-section")).toBeVisible();
        await expect(primary.page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
        await primary.page.goForward();
        await expect(primary.page).toHaveURL(new RegExp(`/projects/${primary.projectId}/step02`));
        await expect(primary.page.getByTestId("eda-overview-launch-surface")).toBeVisible();
        await expect(primary.page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
      }

      probe = await readProbe(primary.page);
      expect(
        probe.safeBoundaryMounts,
        `Safe boundary mounted. Page errors: ${JSON.stringify(primary.pageErrors)}`,
      ).toBe(0);
      expect(probe.hydrationStarts).toBe(1);
      expect(probe.hydrationCompletes).toBe(1);
      expect(probe.modelMounts).toBe(probe.modelUnmounts);
      expect(probe.edaMounts).toBe(probe.edaUnmounts + 1);
      expect(activeListeners(probe)).toEqual(listenerBaseline);
      for (const eventName of TRACKED_EVENTS) {
        expect(probe.listenerAdds[eventName] ?? 0).toBeGreaterThanOrEqual(
          probe.listenerRemoves[eventName] ?? 0,
        );
        expect(
          (probe.listenerAdds[eventName] ?? 0) - (probe.listenerRemoves[eventName] ?? 0),
        ).toBe(probe.listenerActive[eventName] ?? 0);
      }

      await expectProjectRequestsQuiescent(primary.page, primary.stats, "history phase");
      expect(primary.pageErrors).toEqual([]);

      const permittedProjectGets =
        (fixtures.length + soak.reloads) * 4
        + 2
        + soak.historyCycles * 8;
      expect(
        fixtures.reduce((total, fixture) => total + fixture.stats.projectGets, 0),
        "Project hydration request count exceeded the reload/save bound.",
      ).toBeLessThanOrEqual(permittedProjectGets);
      expect(primary.stats.workflowGets).toBeLessThanOrEqual(soak.reloads + 2);
      expect(primary.stats.identityGets).toBeLessThanOrEqual(
        soak.reloads * 2 + 3 + soak.historyCycles * 4,
      );
      expect(primary.stats.overviewPosts).toBeLessThanOrEqual(
        (soak.historyCycles + 1) * 2,
      );

      while (Date.now() - startedAt < soak.minRuntimeMs) {
        await primary.page.waitForTimeout(
          Math.min(10_000, soak.minRuntimeMs - (Date.now() - startedAt)),
        );
        await expect(primary.page.getByTestId("eda-overview-launch-surface")).toBeVisible();
        await expect(primary.page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
      }

      const finalCounts = fixtures.map(({ projectId, userId, stats }) => ({
        projectId,
        userId,
        ...stats,
      }));
      test.info().annotations.push({
        type: "soak-summary",
        description: JSON.stringify({
          mode: FULL_SOAK ? "full" : "smoke",
          elapsedMs: Date.now() - startedAt,
          settings: soak,
          requestCounts: finalCounts,
          lifecycle: await readProbe(primary.page),
        }),
      });
    } finally {
      await Promise.all(fixtures.map(({ context }) => context.close()));
    }
  });
});

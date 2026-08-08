import { expect, test, type Page, type Route } from "@playwright/test";
import type { ScoringRunSummary } from "../../src/scoring-runs/scoringRunClient";

const USER_ID = "scoring-reload-user";
const PROJECT_ID = "scoring-reload-project";
const DATASET_ID = "scoring-reload-dataset";
const DATASET_VERSION_ID = "scoring-reload-dataset-version";
const TARGET = "bad_flag";
const MODEL_VERSION_ID = "scoring-reload-model-version";

async function fulfillJson(route: Route, body: Record<string, unknown>, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function completedRun(overrides: Partial<ScoringRunSummary> = {}): ScoringRunSummary {
  return {
    scoringRunId: "scoring-run-exact",
    projectId: PROJECT_ID,
    userId: USER_ID,
    datasetId: DATASET_ID,
    datasetVersionId: DATASET_VERSION_ID,
    datasetIdentity: "Governed development TRAIN split",
    partition: "train",
    modelId: "logreg",
    modelVersion: "training-run-display-version",
    modelVersionId: MODEL_VERSION_ID,
    problemType: "classification",
    target: TARGET,
    status: "completed",
    createdAt: "2026-08-07T12:00:00.000Z",
    completedAt: "2026-08-07T12:00:01.000Z",
    rowCount: 100,
    predictionColumn: "prediction",
    probabilityColumn: "adjusted_score",
    residualColumn: null,
    checksum: "sha256:scoring-output",
    archivedAt: null,
    ...overrides,
  };
}

function finalModelStatus() {
  return {
    ok: true,
    ready: true,
    artifact_present: true,
    stale: false,
    project_id: PROJECT_ID,
    dataset_id: DATASET_ID,
    dataset_version_id: DATASET_VERSION_ID,
    target: TARGET,
    model_version_id: MODEL_VERSION_ID,
    metadata: {
      name: "Exact governed model",
      problem_type: "classification",
      project_id: PROJECT_ID,
      dataset_id: DATASET_ID,
      training_dataset_id: DATASET_ID,
      dataset_version_id: DATASET_VERSION_ID,
      training_dataset_version_id: DATASET_VERSION_ID,
      target: TARGET,
      target_name: TARGET,
      candidate_id: "candidate-exact",
      training_run_id: "training-run-exact",
      feature_manifest_version: "feature-manifest-exact",
      validation_design_id: "validation-design-exact",
      split_id: "split-exact",
      model_id: "model-exact",
      model_version_id: MODEL_VERSION_ID,
      modelVersionId: MODEL_VERSION_ID,
      artifact_verified: true,
      artifact_checksum: "sha256:model-artifact",
      promotion_status: "finalized",
      lineage_status: "verified",
      designation: "champion",
      candidate_decision_id: "candidate-decision-exact",
      evaluation_package_id: "evaluation-package-exact",
      holdout_exposure_id: "holdout-exposure-exact",
      selection_integrity_status: "verified",
      holdout_isolation_status: "verified",
      evaluation_package_integrity_status: "verified",
      promotion_readiness_status: "verified",
      final_holdout_status: "evaluated",
      features: ["feature_a"],
      feature_count: 1,
    },
  };
}

function projectRecord() {
  return {
    projectId: PROJECT_ID,
    projectName: "Scoring Reload Project",
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
      modelId: "model-exact",
      hasDataset: true,
      projectContextRevision: "scoring-reload-r1",
      projectContextSavedAt: "2026-08-07T12:00:00.000Z",
      projectContext: {
        modelId: "model-exact",
        projectName: "Scoring Reload Project",
        modelType: "generic classification",
        modelTypeSelection: "Generic Binary Classification",
        businessObjective: "Verify refresh-durable scoring continuation.",
        intendedModelUse: "Exercise exact governed scoring history.",
        targetDefinition: "Predict the isolated event.",
        populationDefinition: "Synthetic browser-test population.",
        observationWindow: "Predictors precede the outcome.",
        performanceWindow: "Outcomes follow the observation window.",
      },
    },
    createdAt: "2026-08-07T12:00:00.000Z",
    updatedAt: "2026-08-07T12:00:00.000Z",
  };
}

function workflowState() {
  const steps = Object.fromEntries(
    Array.from({ length: 14 }, (_, index) => [
      `step${String(index).padStart(2, "0")}`,
      index <= 9 ? "complete" : "in_progress",
    ]),
  );
  return {
    projectId: PROJECT_ID,
    currentStepId: "step10",
    updatedAt: "2026-08-07T12:00:00.000Z",
    workflowStatus: {
      workflowId: "predictive-modeling",
      projectType: "predictive-modeling",
      hasDataset: true,
      datasetIdentity: {
        project_id: PROJECT_ID,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        activation_revision: 1,
      },
      steps,
    },
  };
}

function reproducibilityContext() {
  return {
    ok: true,
    state: "current",
    project_id: PROJECT_ID,
    context_id: "scoring-reload-context-r1",
    identity: {
      project_id: PROJECT_ID,
      dataset_name: "Scoring reload dataset",
      dataset_id: DATASET_ID,
      dataset_version_id: DATASET_VERSION_ID,
      dataset_version_label: "Scoring reload version",
      source_type: "dataset-library",
      activation_revision: 1,
      governed_population_rows: 100,
      source_columns: 2,
    },
    target_contract: {
      target_contract_id: "target-contract-r1",
      target: TARGET,
      event_value: 1,
      non_event_value: 0,
    },
    predictor_authorization: {
      predictor_authorization_id: "predictor-authorization-r1",
      status: "current",
      authorized_predictors: ["feature_a"],
      selected_predictors: ["feature_a"],
      excluded_fields: { [TARGET]: "target" },
      deterministic_source_exclusions: [],
      target_source_detection_scope: "development_population",
      funnel: {
        source_column_count: 2,
        target_exclusions: [{ field: TARGET, reason: "target" }],
        candidate_predictor_count: 1,
        selected_predictor_count: 1,
        authorized_predictor_count: 1,
        additional_exclusions: {},
        model_ready_status: "not_established_in_data_acquisition",
      },
    },
    analysis_partition: {
      analysis_partition_id: "analysis-partition-r1",
      revision: 1,
      status: "current",
      development_share: 0.8,
      holdout_share: 0.2,
      development_rows: 80,
      sealed_holdout_rows: 20,
      random_seed: 42,
      stratification_policy: "target",
      stratification_field: TARGET,
      final_holdout_status: "sealed",
      holdout_isolation_status: "verified",
    },
    authority: {
      binding: "exact_registered_version",
      fallback_used: false,
      browser_state_authoritative: false,
      row_data_included: false,
      assignments_included: false,
      target_aggregates_included: false,
      final_holdout_access: "protected_metadata_only",
    },
  };
}

async function installMocks(
  page: Page,
  currentRuns: () => ScoringRunSummary[],
  observedFinalStatusQueries: URLSearchParams[],
  observedScoringQueries: URLSearchParams[],
) {
  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/auth/me") {
      await fulfillJson(route, {
        ok: true,
        user: { userId: USER_ID, displayName: "Scoring Reload User", role: "user", status: "active" },
      });
      return;
    }
    if (url.pathname === `/api/projects/${PROJECT_ID}`) {
      await fulfillJson(route, { ok: true, project: projectRecord() });
      return;
    }
    if (url.pathname === `/api/projects/${PROJECT_ID}/workflow-state`) {
      await fulfillJson(route, { ok: true, workflowState: workflowState() });
      return;
    }
    if (url.pathname === "/api/data/active-identity") {
      await fulfillJson(route, {
        ok: true,
        project_id: PROJECT_ID,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        activation_revision: 1,
        dataset_version_label: "Scoring reload version",
        dataset_source_type: "dataset-library",
      });
      return;
    }
    if (url.pathname === "/api/data/get_sample") {
      await fulfillJson(route, {
        ok: true,
        project_id: PROJECT_ID,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        activation_revision: 1,
        source_checksum: "sha256:dataset-source",
        headers: ["feature_a", TARGET],
        rows: [{ feature_a: 1 }, { feature_a: 2 }],
        target: TARGET,
        selected_columns: ["feature_a"],
        target_values_included: false,
        problem_type: "classification",
        registered_row_count: 100,
        row_count: 100,
        scope: {
          analytical_scope: "development_population_predictors_only",
          target_values_included: false,
          population_id: "development-population-r1",
          population_count: 80,
          partition_id: "analysis-partition-r1",
          partition_revision: 1,
          holdout_excluded: true,
        },
      });
      return;
    }
    if (url.pathname === "/api/data/reproducibility-context") {
      await fulfillJson(route, reproducibilityContext());
      return;
    }
    if (url.pathname === "/api/model/final/status") {
      observedFinalStatusQueries.push(url.searchParams);
      await fulfillJson(route, finalModelStatus());
      return;
    }
    if (url.pathname === "/api/scoring-runs") {
      observedScoringQueries.push(url.searchParams);
      const runs = currentRuns();
      await fulfillJson(route, { ok: true, scoringRuns: runs, count: runs.length });
      return;
    }
    if (url.pathname === "/api/train/last") {
      await fulfillJson(route, { ok: true, summary: { problem_type: "classification", ranked: [] } });
      return;
    }
    if (url.pathname === "/api/notifications/unread-count") {
      await fulfillJson(route, { ok: true, count: 0 });
      return;
    }
    await fulfillJson(route, { ok: true, count: 0, items: [], rows: [] });
  });
}

test("Step 10 reload restores only an exact completed durable scoring run", async ({ page }) => {
  test.setTimeout(120_000);
  let runs: ScoringRunSummary[] = [
    completedRun({ scoringRunId: "wrong-model-version", modelVersionId: "other-model-version" }),
    completedRun({ scoringRunId: "failed", status: "failed", checksum: null }),
    completedRun({ scoringRunId: "archived", archivedAt: "2026-08-07T12:05:00.000Z" }),
  ];
  const finalStatusQueries: URLSearchParams[] = [];
  const scoringQueries: URLSearchParams[] = [];
  await installMocks(page, () => runs, finalStatusQueries, scoringQueries);

  const continueButton = page.getByRole("button", {
    name: "Confirm Scoring and Continue to Documentation",
  });
  await page.goto(`/projects/${PROJECT_ID}/step10`);
  await expect(page.getByTestId("final-model-scoring-contract")).toBeVisible();
  await expect(continueButton).toBeDisabled();

  runs = [completedRun()];
  await page.reload();
  await expect(page.getByTestId("final-model-scoring-contract")).toBeVisible();
  await expect(continueButton).toBeEnabled();
  await expect(page.getByText("1 scored output available for documentation and monitoring.")).toBeVisible();

  for (const rejected of [
    completedRun({ scoringRunId: "wrong-dataset-version", datasetVersionId: "other-version" }),
    completedRun({ scoringRunId: "failed-after-reload", status: "failed", checksum: null }),
    completedRun({ scoringRunId: "archived-after-reload", archivedAt: "2026-08-07T12:10:00.000Z" }),
  ]) {
    runs = [rejected];
    await page.reload();
    await expect(page.getByTestId("final-model-scoring-contract")).toBeVisible();
    await expect(continueButton).toBeDisabled();
  }

  expect(finalStatusQueries.length).toBeGreaterThanOrEqual(5);
  for (const query of finalStatusQueries) {
    expect(Object.fromEntries(query.entries())).toMatchObject({
      project_id: PROJECT_ID,
      dataset_id: DATASET_ID,
      dataset_version_id: DATASET_VERSION_ID,
      target: TARGET,
    });
  }
  expect(scoringQueries.some((query) => (
    query.get("projectId") === PROJECT_ID &&
    query.get("datasetId") === DATASET_ID &&
    query.get("datasetVersionId") === DATASET_VERSION_ID &&
    query.get("modelVersionId") === MODEL_VERSION_ID &&
    query.get("target") === TARGET &&
    query.get("status") === "completed" &&
    query.get("includeArchived") === null
  ))).toBe(true);
});

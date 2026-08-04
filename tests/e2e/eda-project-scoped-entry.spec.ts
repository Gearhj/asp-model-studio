import { expect, test, type Page, type Route } from "@playwright/test";

const PROJECT_ID = "eda-scope-regression-project";
const DATASET_ID = "eda-scope-regression-dataset";
const DATASET_VERSION_ID = "eda-scope-regression-version";

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

function overviewPayload(scope = "development_population") {
  return {
    ok: true,
    project_id: PROJECT_ID,
    dataset_id: DATASET_ID,
    dataset_version_id: DATASET_VERSION_ID,
    dataset_version: DATASET_VERSION_ID,
    section: "overview",
    // This is the governed scope returned by the live backend after an
    // Analysis Partition is confirmed. It must remain a supported UI scope.
    scope,
    row_count: 6_275,
    column_count: 24,
    target: "bad_flag",
    problem_type: "classification",
    event_value: 1,
    duration_ms: 1,
    cache_status: "miss",
    headline: {
      rows: 6_275,
      predictors: 23,
      numeric_predictors: 23,
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
      valid_count: 6_275,
      missing_count: 0,
      class_count: 2,
      event_rate: 0.52,
      class_distribution: [
        { value: 0, count: 3_000, rate: 0.4781 },
        { value: 1, count: 3_275, rate: 0.5219 },
      ],
    },
    available_fields: {
      numeric: ["ExternalRiskEstimate"],
      categorical: [],
      date_candidates: [],
      segment_candidates: [],
    },
    predictor_authorization: {
      manifest_version: "predictor-auth-regression",
      authorized_predictors: ["ExternalRiskEstimate"],
      target_source_excluded: [],
    },
    target_source_excluded: [],
  };
}

async function installProjectScopedMocks(
  page: Page,
  scope = "development_population",
) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/auth/me") {
      await fulfillJson(route, 200, {
        ok: true,
        user: {
          userId: "eda-scope-regression-user",
          displayName: "EDA Scope Regression",
          role: "user",
          status: "active",
        },
      });
      return;
    }
    if (url.pathname === `/api/projects/${PROJECT_ID}`) {
      await fulfillJson(route, 200, {
        ok: true,
        project: {
          projectId: PROJECT_ID,
          projectName: "EDA Scope Regression",
          projectType: "predictive-modeling",
          workflowType: "predictive-modeling",
          ownerUserId: "eda-scope-regression-user",
          metadata: {
            modelId: "eda-scope-regression-model",
            projectContextRevision: "eda-scope-regression-revision",
            projectContextSavedAt: "2026-08-02T12:00:00.000Z",
            projectContext: {
              projectName: "EDA Scope Regression",
              modelId: "eda-scope-regression-model",
            },
          },
          createdAt: "2026-08-02T12:00:00.000Z",
          updatedAt: "2026-08-02T12:00:00.000Z",
        },
      });
      return;
    }
    if (url.pathname === `/api/projects/${PROJECT_ID}/workflow-state`) {
      await fulfillJson(route, 200, {
        ok: true,
        workflowState: {
          projectId: PROJECT_ID,
          currentStepId: "step02",
          workflowStatus: {
            workflowId: "predictive-modeling",
            projectType: "predictive-modeling",
            steps: {
              step00: "complete",
              step01: "complete",
              step02: "in_progress",
            },
          },
          updatedAt: "2026-08-02T12:00:00.000Z",
        },
      });
      return;
    }
    if (url.pathname === "/api/data/active-identity") {
      await fulfillJson(route, 200, {
        ok: true,
        project_id: PROJECT_ID,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        dataset_version_label: "HELOC_TRAIN",
        dataset_source_type: "dataset-library",
        activation_revision: 1,
      });
      return;
    }
    if (url.pathname === "/api/data/get_sample") {
      await fulfillJson(route, 200, {
        ok: true,
        headers: ["ExternalRiskEstimate", "bad_flag"],
        rows: [
          { ExternalRiskEstimate: 72, bad_flag: 0 },
          { ExternalRiskEstimate: 48, bad_flag: 1 },
        ],
        target: "bad_flag",
        selected_columns: ["ExternalRiskEstimate"],
        registered_row_count: 6_275,
      });
      return;
    }
    if (url.pathname === "/api/eda/workspace/overview") {
      await fulfillJson(route, 200, overviewPayload(scope));
      return;
    }
    await fulfillJson(route, 404, {
      ok: false,
      detail: "No synthetic response is required for this regression.",
    });
  });
}

test("project-scoped EDA renders the governed development population after Data Acquisition", async ({
  page,
}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await installProjectScopedMocks(page);

  await page.goto(`/projects/${PROJECT_ID}/step02?edaTab=overview`);

  await expect(page.getByTestId("eda-overview-launch-surface")).toBeVisible();
  await expect(page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
  await expect(page.locator(".atlas-data-scope")).toContainText(
    "Development Population",
  );
  await expect(page.locator(".atlas-data-scope")).toHaveAttribute(
    "data-scope-recognized",
    "true",
  );
  expect(pageErrors).toEqual([]);
});

test("an unrecognized backend scope fails closed without crashing the workflow route", async ({
  page,
}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await installProjectScopedMocks(page, "future_governed_scope");

  await page.goto(`/projects/${PROJECT_ID}/step02?edaTab=overview`);

  await expect(page.getByTestId("eda-overview-launch-surface")).toBeVisible();
  await expect(page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);
  await expect(page.locator(".atlas-data-scope")).toContainText(
    "Scope Unavailable",
  );
  await expect(page.locator(".atlas-data-scope")).toHaveAttribute(
    "data-scope-recognized",
    "false",
  );
  expect(pageErrors).toEqual([]);
});

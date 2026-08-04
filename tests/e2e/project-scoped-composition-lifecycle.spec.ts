import { expect, test, type Page, type Route } from "@playwright/test";

const PROJECT_ID = "project-scoped-composition-lifecycle";
const DATASET_ID = "ds_project_scoped_composition";
const DATASET_VERSION_ID = "v_project_scoped_composition_001";

type RequestCounts = {
  auth: number;
  project: number;
  workflow: number;
  identity: number;
  sample: number;
  overview: number;
  documentationRead: number;
  documentationDraft: number;
};

type CompositionProbe = {
  providerStatuses: string[];
  edaMounts: number;
  edaUnmounts: number;
  safeBoundaryMounts: number;
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

async function installCompositionProbe(page: Page) {
  await page.addInitScript(() => {
    const probe: CompositionProbe = {
      providerStatuses: [],
      edaMounts: 0,
      edaUnmounts: 0,
      safeBoundaryMounts: 0,
    };
    (window as any).__atlasProjectScopedCompositionProbe = probe;

    let edaPresent = false;
    let boundaryPresent = false;
    let providerStatus = "";
    const sample = () => {
      const nextEdaPresent = Boolean(
        document.querySelector('[data-testid="eda-overview-launch-surface"]'),
      );
      if (nextEdaPresent && !edaPresent) probe.edaMounts += 1;
      if (!nextEdaPresent && edaPresent) probe.edaUnmounts += 1;
      edaPresent = nextEdaPresent;

      const nextBoundaryPresent = Boolean(
        document.querySelector('[data-testid="atlas-safe-error-boundary"]'),
      );
      if (nextBoundaryPresent && !boundaryPresent) probe.safeBoundaryMounts += 1;
      boundaryPresent = nextBoundaryPresent;

      const status =
        document
          .querySelector('[data-testid="atlas-breadcrumb"]')
          ?.getAttribute("data-project-context-status") ?? "";
      if (status && status !== providerStatus) {
        probe.providerStatuses.push(status);
        providerStatus = status;
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
  });
}

function overviewPayload() {
  return {
    ok: true,
    project_id: PROJECT_ID,
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
    cache_status: "miss",
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
      manifest_version: "manifest-project-scoped-composition",
      authorized_predictors: ["ExternalRiskEstimate"],
      target_source_excluded: [],
    },
    target_source_excluded: [],
  };
}

async function installMocks(page: Page) {
  const counts: RequestCounts = {
    auth: 0,
    project: 0,
    workflow: 0,
    identity: 0,
    sample: 0,
    overview: 0,
    documentationRead: 0,
    documentationDraft: 0,
  };

  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method().toUpperCase();

    if (url.pathname === "/api/auth/me") {
      counts.auth += 1;
      await fulfillJson(route, 200, {
        ok: true,
        user: {
          userId: "project-scoped-composition-user",
          displayName: "Composition Lifecycle User",
          email: "composition@example.test",
          role: "user",
          status: "active",
        },
      });
      return;
    }
    if (url.pathname === `/api/projects/${PROJECT_ID}` && method === "GET") {
      counts.project += 1;
      await fulfillJson(route, 200, {
        ok: true,
        project: {
          projectId: PROJECT_ID,
          projectName: "Project-scoped Composition Fixture",
          projectType: "predictive-modeling",
          workflowType: "predictive-modeling",
          ownerUserId: "project-scoped-composition-user",
          status: "active",
          metadata: {
            modelId: "model-project-scoped-composition",
            projectContextRevision: "1000-project-scoped-composition",
            projectContextSavedAt: "2026-08-03T12:00:00.000Z",
            projectContext: {
              projectName: "Project-scoped Composition Fixture",
              modelId: "model-project-scoped-composition",
            },
          },
          createdAt: "2026-08-03T12:00:00.000Z",
          updatedAt: "2026-08-03T12:00:00.000Z",
        },
      });
      return;
    }
    if (
      url.pathname === `/api/projects/${PROJECT_ID}/workflow-state`
      && method === "GET"
    ) {
      counts.workflow += 1;
      await fulfillJson(route, 200, {
        ok: true,
        workflowState: {
          projectId: PROJECT_ID,
          currentStepId: "step02",
          updatedAt: "2026-08-03T12:00:00.000Z",
          workflowStatus: {
            workflowId: "predictive-modeling",
            projectType: "predictive-modeling",
            hasDataset: true,
            steps: {
              step00: "complete",
              step01: "complete",
              step02: "in_progress",
            },
          },
        },
      });
      return;
    }
    if (url.pathname === "/api/data/active-identity" && method === "GET") {
      counts.identity += 1;
      await fulfillJson(route, 200, {
        ok: true,
        project_id: PROJECT_ID,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        dataset_version_label: "Project-scoped composition version",
        dataset_source_type: "dataset-library",
        activation_revision: 1,
        target: "bad_flag",
      });
      return;
    }
    if (url.pathname === "/api/data/get_sample" && method === "GET") {
      counts.sample += 1;
      await fulfillJson(route, 200, {
        ok: true,
        headers: ["ExternalRiskEstimate", "bad_flag"],
        rows: [
          { ExternalRiskEstimate: 72, bad_flag: 0 },
          { ExternalRiskEstimate: 48, bad_flag: 1 },
        ],
        target: "bad_flag",
        selected_columns: ["ExternalRiskEstimate"],
        registered_row_count: 100,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
      });
      return;
    }
    if (url.pathname === "/api/eda/workspace/overview" && method === "POST") {
      counts.overview += 1;
      await fulfillJson(route, 200, overviewPayload());
      return;
    }
    if (
      url.pathname === `/api/eda/documentation/${PROJECT_ID}`
      && method === "GET"
    ) {
      counts.documentationRead += 1;
      await fulfillJson(route, 200, {
        ok: true,
        project_id: PROJECT_ID,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        dataset_version: DATASET_VERSION_ID,
        status: "missing",
        draft: null,
        current_approved: null,
        history: [],
        source_lineage: {
          project_id: PROJECT_ID,
          dataset_id: DATASET_ID,
          dataset_version_id: DATASET_VERSION_ID,
          dataset_version: DATASET_VERSION_ID,
          target: "bad_flag",
          predictor_manifest_id: "manifest-project-scoped-composition",
        },
      });
      return;
    }
    if (url.pathname === "/api/eda/documentation/draft" && method === "POST") {
      counts.documentationDraft += 1;
      const draft = request.postDataJSON() as Record<string, unknown>;
      await fulfillJson(route, 200, {
        ok: true,
        project_id: PROJECT_ID,
        dataset_id: DATASET_ID,
        dataset_version_id: DATASET_VERSION_ID,
        dataset_version: DATASET_VERSION_ID,
        status: "draft",
        draft,
        current_approved: null,
        history: [],
        source_lineage: {
          project_id: PROJECT_ID,
          dataset_id: DATASET_ID,
          dataset_version_id: DATASET_VERSION_ID,
          dataset_version: DATASET_VERSION_ID,
          target: "bad_flag",
          predictor_manifest_id: "manifest-project-scoped-composition",
        },
      });
      return;
    }
    if (url.pathname === "/api/notifications/unread-count") {
      await fulfillJson(route, 200, { ok: true, count: 0 });
      return;
    }
    await fulfillJson(route, 200, {
      ok: true,
      count: 0,
      items: [],
      rows: [],
      headers: [],
      findings: [],
      notifications: [],
    });
  });
  return counts;
}

test("project-scoped EDA composition hydrates and drafts once without a lifecycle loop", async ({
  page,
}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await installCompositionProbe(page);
  const counts = await installMocks(page);

  await page.goto(`/projects/${PROJECT_ID}/step02?edaTab=overview`);
  await expect(page.getByTestId("eda-overview-launch-surface")).toBeVisible();
  await expect.poll(() => counts.documentationDraft, { timeout: 5_000 }).toBe(1);

  const settledCounts = { ...counts };
  await page.waitForTimeout(2_000);
  const probe = await page.evaluate(
    () => (window as any).__atlasProjectScopedCompositionProbe as CompositionProbe,
  );

  expect(pageErrors).toEqual([]);
  expect(probe).toEqual({
    providerStatuses: ["resolving", "ready"],
    edaMounts: 1,
    edaUnmounts: 0,
    safeBoundaryMounts: 0,
  });
  expect(counts).toEqual(settledCounts);
  expect(counts.workflow).toBe(1);
  expect(counts.identity).toBe(1);
  expect(counts.sample).toBe(1);
  expect(counts.documentationRead).toBe(1);
  expect(counts.documentationDraft).toBe(1);
  expect(
    counts.overview,
    `Actual composition request counts: ${JSON.stringify(counts)}`,
  ).toBe(1);
});

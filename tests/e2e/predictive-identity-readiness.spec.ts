import { expect, test, type Page, type Route } from "@playwright/test";

const PROJECT_ID = "synthetic-identity-project";
const DATASET_ID = "synthetic-dataset";
const DATASET_VERSION_ID = "synthetic-version-001";

async function fulfillJson(route: Route, status: number, body: Record<string, unknown>) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function seedPredictiveProject(page: Page, includeIdentity: boolean) {
  await page.addInitScript(
    ({ projectId, datasetId, datasetVersionId, includeIdentity }) => {
      localStorage.clear();
      sessionStorage.clear();
      const steps = [
        "step00", "step01", "step02", "step03", "step04", "step05", "step06",
        "step07", "step08", "step09", "step10", "step11", "step12", "step13",
      ];
      const state = {
        hasDataset: true,
        datasetIdentity: includeIdentity
          ? {
              project_id: projectId,
              dataset_id: datasetId,
              dataset_version_id: datasetVersionId,
            }
          : null,
        projectId,
        modelId: "synthetic-model",
        projectName: "Synthetic Identity Readiness Project",
        projectType: "predictive-modeling",
        workflowId: "predictive-modeling",
        workflowSteps: steps.map((id, order) => ({
          id,
          label: id === "step07" ? "Model Training" : id,
          route: `/${id}`,
          order,
          status: id === "step07" ? "in_progress" : "complete",
        })),
        currentStepId: "step07",
        steps: Object.fromEntries(steps.map((id) => [id, id === "step07" ? "in_progress" : "complete"])),
        restoreWarnings: [],
      };
      sessionStorage.setItem("ds-workflow-store", JSON.stringify({ state, version: 7 }));
    },
    {
      projectId: PROJECT_ID,
      datasetId: DATASET_ID,
      datasetVersionId: DATASET_VERSION_ID,
      includeIdentity,
    },
  );
}

async function installAuthMock(page: Page) {
  await page.route("**/api/auth/me", (route) => fulfillJson(route, 200, {
    ok: true,
    user: {
      userId: "synthetic-identity-user",
      displayName: "Identity Test User",
      role: "user",
      status: "active",
    },
  }));
}

function authoritativeProject() {
  return {
    projectId: PROJECT_ID,
    projectName: "Synthetic Identity Readiness Project",
    projectType: "predictive-modeling",
    workflowType: "predictive-modeling",
    ownerUserId: "synthetic-identity-user",
    metadata: {
      modelId: "synthetic-model",
      projectContextRevision: "1000-synthetic",
      projectContextSavedAt: "2026-08-02T12:00:00.000Z",
      projectContext: {
        projectName: "Synthetic Identity Readiness Project",
        modelId: "synthetic-model",
      },
    },
    createdAt: "2026-08-02T12:00:00.000Z",
    updatedAt: "2026-08-02T12:00:00.000Z",
  };
}

function authoritativeWorkflowState() {
  return {
    projectId: PROJECT_ID,
    currentStepId: "step07",
    updatedAt: "2026-08-02T12:00:00.000Z",
    workflowStatus: {
      workflowId: "predictive-modeling",
      projectType: "predictive-modeling",
      steps: { step07: "in_progress" },
    },
  };
}

async function fulfillProjectAuthority(route: Route, pathname: string) {
  if (pathname === `/api/projects/${PROJECT_ID}`) {
    await fulfillJson(route, 200, { ok: true, project: authoritativeProject() });
    return true;
  }
  if (pathname === `/api/projects/${PROJECT_ID}/workflow-state`) {
    await fulfillJson(route, 200, { ok: true, workflowState: authoritativeWorkflowState() });
    return true;
  }
  return false;
}

test.describe("Predictive route canonical identity readiness", () => {
  test("keeps the shell visible while exact identity is delayed, then renders Model Training", async ({ page }) => {
    await seedPredictiveProject(page, true);

    let releaseIdentity = () => undefined;
    const identityRelease = new Promise<void>((resolve) => {
      releaseIdentity = resolve;
    });
    let markIdentityRequested = () => undefined;
    const identityRequested = new Promise<void>((resolve) => {
      markIdentityRequested = resolve;
    });
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      if (await fulfillProjectAuthority(route, url.pathname)) return;
      if (url.pathname === "/api/data/active-identity") {
        markIdentityRequested();
        await identityRelease;
        await fulfillJson(route, 200, {
          ok: true,
          project_id: PROJECT_ID,
          dataset_id: DATASET_ID,
          dataset_version_id: DATASET_VERSION_ID,
          dataset_version_label: "Synthetic governed version",
          dataset_source_type: "dataset-library",
        });
        return;
      }
      if (url.pathname === "/api/data/get_sample") {
        await fulfillJson(route, 200, {
          ok: true,
          headers: ["predictor", "target"],
          rows: [{ predictor: 1, target: 0 }, { predictor: 2, target: 1 }],
          target: "target",
          selected_columns: ["predictor"],
        });
        return;
      }
      await fulfillJson(route, 404, { ok: false, detail: "No synthetic downstream artifact" });
    });
    await installAuthMock(page);

    await page.goto(`/projects/${PROJECT_ID}/step07?identity-test=delayed`);
    await identityRequested;
    await expect(page.getByTestId("project-context-gate")).toHaveAttribute(
      "data-project-context-status",
      "resolving",
    );
    await expect(page.locator("body")).toContainText("Loading project context");
    await expect(page.getByRole("button", { name: /Code & Reproducibility/i })).toHaveCount(0);
    await expect(page.locator("#root")).not.toBeEmpty();

    releaseIdentity();
    await expect(page.getByTestId("predictive-identity-gate")).toHaveCount(0);
    const codePanel = page.getByRole("button", { name: /Code & Reproducibility/i });
    await expect(codePanel).toBeVisible();
    await codePanel.click();
    await expect(page.getByTestId("step-python-panel-identity-disabled")).toHaveCount(0);
    await expect(page.getByText("SAS runtime status", { exact: true })).toBeVisible();
    await expect(page.locator("body")).toContainText(/Model Training/i);
    await expect(page.locator("#root")).not.toBeEmpty();
    expect(pageErrors).toEqual([]);
  });

  test("renders a controlled recovery action for a legacy project instead of a blank workspace", async ({ page }) => {
    await seedPredictiveProject(page, false);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      if (await fulfillProjectAuthority(route, url.pathname)) return;
      if (url.pathname === "/api/data/active-identity") {
        await fulfillJson(route, 409, {
          ok: false,
          detail: "No exact registered Dataset Library version is active for this project.",
        });
        return;
      }
      await fulfillJson(route, 404, { ok: false, detail: "No synthetic artifact" });
    });
    await installAuthMock(page);

    await page.goto(`/projects/${PROJECT_ID}/step07?identity-test=legacy`);
    const gate = page.getByTestId("predictive-identity-gate");
    await expect(gate).toHaveAttribute("data-identity-status", "missing");
    await expect(gate).toContainText("Dataset selection required");
    await expect(page.getByTestId("identity-recovery-data-acquisition")).toHaveAttribute(
      "href",
      `/projects/${PROJECT_ID}/step01`,
    );
    await expect(page.locator("#root")).not.toBeEmpty();
    expect(pageErrors).toEqual([]);
  });

  test("contains a late DatasetIdentityError inside the notebook panel and preserves Model Training", async ({ page }) => {
    await seedPredictiveProject(page, true);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      if (await fulfillProjectAuthority(route, url.pathname)) return;
      if (url.pathname === "/api/data/active-identity") {
        await fulfillJson(route, 200, {
          ok: true,
          project_id: PROJECT_ID,
          dataset_id: DATASET_ID,
          dataset_version_id: DATASET_VERSION_ID,
        });
        return;
      }
      if (url.pathname === "/api/data/get_sample") {
        await fulfillJson(route, 200, {
          ok: true,
          headers: ["predictor", "target"],
          rows: [{ predictor: 1, target: 0 }, { predictor: 2, target: 1 }],
          target: "target",
          selected_columns: ["predictor"],
        });
        return;
      }
      await fulfillJson(route, 404, { ok: false, detail: "No synthetic downstream artifact" });
    });
    await installAuthMock(page);

    await page.goto(`/projects/${PROJECT_ID}/step07?identity-test=panel-boundary`);
    await expect(page.getByTestId("predictive-identity-gate")).toHaveCount(0);
    const codePanel = page.getByRole("button", { name: /Code & Reproducibility/i });
    await expect(codePanel).toBeVisible();

    await page.evaluate(({ userId, projectId }) => {
      const key = `atlas:modeling-dataset:${userId}:${projectId}`;
      const raw = sessionStorage.getItem(key);
      if (!raw) throw new Error("Synthetic governed dataset cache was not restored.");
      const dataset = JSON.parse(raw);
      delete dataset.dataset_id;
      if (dataset.dataset_library) delete dataset.dataset_library.datasetId;
      sessionStorage.setItem(key, JSON.stringify(dataset));
    }, { userId: "synthetic-identity-user", projectId: PROJECT_ID });

    await codePanel.click();
    await expect(page.getByTestId("step-python-panel-identity-disabled")).toBeVisible();
    await expect(page.getByText("Governed code export is not available yet.", { exact: true })).toBeVisible();
    await expect(page.locator("body")).toContainText(/Model Training/i);
    await expect(page.locator("#root")).not.toBeEmpty();
    expect(pageErrors).toEqual([]);
  });
});

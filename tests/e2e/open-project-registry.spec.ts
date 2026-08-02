import { expect, test, type Page, type Route } from "@playwright/test";

type MockResponse = {
  status: number;
  body: Record<string, unknown>;
};

type RegistryMockOptions = {
  projects: (attempt: number) => MockResponse | "abort";
  auth?: (attempt: number) => MockResponse;
  failFirstWorkflowState?: boolean;
};

function syntheticProject(index: number, name = `Synthetic Project ${index}`) {
  const timestamp = "2026-07-31T12:00:00.000Z";
  return {
    projectId: `synthetic-project-${index}`,
    projectName: name,
    projectType: "predictive-modeling",
    workflowType: "predictive-modeling",
    status: "active",
    templateId: null,
    metadata: { modelId: `synthetic-model-${index}`, hasDataset: true },
    createdAt: timestamp,
    updatedAt: timestamp,
  };
}

async function fulfillJson(route: Route, response: MockResponse) {
  await route.fulfill({
    status: response.status,
    contentType: "application/json",
    headers: {
      "Access-Control-Allow-Origin": "http://127.0.0.1:5174",
      "Access-Control-Allow-Credentials": "true",
    },
    body: JSON.stringify(response.body),
  });
}

async function installRegistryMocks(page: Page, options: RegistryMockOptions) {
  const stats = {
    authAttempts: 0,
    projectAttempts: 0,
    workflowStateAttempts: 0,
    projectDetailAttempts: 0,
    unhandledApiPaths: [] as string[],
  };

  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (pathname === "/api/auth/me") {
      stats.authAttempts += 1;
      const response = options.auth?.(stats.authAttempts) ?? {
        status: 200,
        body: {
          ok: true,
          user: {
            userId: "synthetic-registry-user",
            displayName: "Registry Test User",
            role: "user",
            status: "active",
          },
        },
      };
      await fulfillJson(route, response);
      return;
    }

    if (pathname === "/api/projects" && request.method() === "GET") {
      stats.projectAttempts += 1;
      const response = options.projects(stats.projectAttempts);
      if (response === "abort") {
        await route.abort("failed");
      } else {
        await fulfillJson(route, response);
      }
      return;
    }

    if (/^\/api\/projects\/[^/]+\/workflow-state$/.test(pathname)) {
      stats.workflowStateAttempts += 1;
      if (options.failFirstWorkflowState && stats.workflowStateAttempts === 1) {
        await fulfillJson(route, { status: 500, body: { ok: false, detail: "Synthetic enrichment failure" } });
      } else {
        await fulfillJson(route, { status: 404, body: { ok: false, detail: "No synthetic workflow state" } });
      }
      return;
    }

    if (/^\/api\/projects\/[^/]+$/.test(pathname)) {
      stats.projectDetailAttempts += 1;
      await fulfillJson(route, { status: 500, body: { ok: false, detail: "Project detail fan-out is forbidden in this test" } });
      return;
    }

    stats.unhandledApiPaths.push(pathname);
    await fulfillJson(route, { status: 200, body: { ok: true, count: 0, notifications: [] } });
  });

  return stats;
}

test.describe("Open Project authoritative registry loading", () => {
  test("renders 132 projects after valid HTTP 200 and isolates optional enrichment failure", async ({ page }) => {
    const projects = Array.from({ length: 132 }, (_, index) => (
      syntheticProject(index + 1, index === 0 ? "Synthetic HELOC Acceptance Project" : undefined)
    ));
    const stats = await installRegistryMocks(page, {
      projects: () => ({ status: 200, body: { ok: true, projects, count: projects.length } }),
      failFirstWorkflowState: true,
    });

    await page.goto("/projects/open?registry-test=success");
    await expect(page.getByTestId("project-registry-status")).toHaveAttribute("data-state", "success");
    await expect(page.getByTestId("project-registry-list")).toBeVisible();
    await expect(page.getByText("Synthetic HELOC Acceptance Project", { exact: true })).toBeVisible();
    await expect(page.getByText(/Backend project registry unavailable/i)).toHaveCount(0);
    expect(stats.projectAttempts).toBeGreaterThanOrEqual(1);
    expect(stats.projectAttempts).toBeLessThanOrEqual(2);
    expect(stats.workflowStateAttempts).toBeGreaterThan(0);
    expect(stats.projectDetailAttempts).toBe(0);

    await page.reload();
    await expect(page.getByTestId("project-registry-status")).toHaveAttribute("data-state", "success");
    await expect(page.getByText("Synthetic HELOC Acceptance Project", { exact: true })).toBeVisible();
    await expect(page.getByText(/Backend project registry unavailable/i)).toHaveCount(0);
  });

  test("renders a valid empty state for an empty HTTP 200 response", async ({ page }) => {
    await installRegistryMocks(page, {
      projects: () => ({ status: 200, body: { ok: true, projects: [], count: 0 } }),
    });
    await page.goto("/projects/open?registry-test=empty");
    await expect(page.getByTestId("project-registry-status")).toHaveAttribute("data-state", "empty");
    await expect(page.getByTestId("project-registry-empty")).toBeVisible();
    await expect(page.getByTestId("project-registry-error")).toHaveCount(0);
  });

  test("identifies malformed HTTP 200 data and a controlled retry recovers", async ({ page }) => {
    let recover = false;
    const stats = await installRegistryMocks(page, {
      projects: () => recover
        ? { status: 200, body: { ok: true, projects: [syntheticProject(1, "Recovered Synthetic Project")], count: 1 } }
        : { status: 200, body: { ok: true, projects: "malformed", count: 1 } },
    });
    await page.goto("/projects/open?registry-test=malformed");
    await expect(page.getByTestId("project-registry-status")).toHaveAttribute("data-state", "error");
    await expect(page.getByTestId("project-registry-error")).toHaveAttribute("data-error-kind", "response");
    await expect(page.getByText(/invalid response|projects array/i)).toBeVisible();
    await expect(page.getByText(/Failed to fetch/i)).toHaveCount(0);

    recover = true;
    await page.getByTestId("project-registry-retry").click();
    await expect(page.getByTestId("project-registry-status")).toHaveAttribute("data-state", "success");
    await expect(page.getByText("Recovered Synthetic Project", { exact: true })).toBeVisible();
    await expect(page.getByTestId("project-registry-error")).toHaveCount(0);
    expect(stats.projectAttempts).toBeGreaterThanOrEqual(2);
  });

  test("HTTP 401 follows the existing sign-in flow", async ({ page }) => {
    await installRegistryMocks(page, {
      auth: (attempt) => attempt === 1
        ? {
          status: 200,
          body: {
            ok: true,
            user: { userId: "expired-user", displayName: "Expired User", role: "user", status: "active" },
          },
        }
        : { status: 401, body: { ok: false, detail: "authentication required" } },
      projects: () => ({ status: 401, body: { ok: false, detail: "authentication required" } }),
    });
    await page.goto("/projects/open?registry-test=401");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "Sign in to ATLAS" })).toBeVisible();
    await expect(page.getByText(/Backend project registry unavailable/i)).toHaveCount(0);
  });

  test("HTTP 403 remains an authorization error in the authenticated shell", async ({ page }) => {
    await installRegistryMocks(page, {
      projects: () => ({ status: 403, body: { ok: false, detail: "permission denied" } }),
    });
    await page.goto("/projects/open?registry-test=403");
    await expect(page.getByTestId("project-registry-status")).toHaveAttribute("data-state", "error");
    await expect(page.getByTestId("project-registry-error")).toHaveAttribute("data-error-kind", "authorization");
    await expect(page.getByText(/do not have permission/i)).toBeVisible();
    await expect(page.getByText(/Backend project registry unavailable/i)).toHaveCount(0);
  });

  test("a genuine network failure renders an error and retry recovers", async ({ page }) => {
    let recover = false;
    const stats = await installRegistryMocks(page, {
      projects: () => recover
        ? { status: 200, body: { ok: true, projects: [syntheticProject(1, "Network Recovery Project")], count: 1 } }
        : "abort",
    });
    await page.goto("/projects/open?registry-test=network");
    await expect(page.getByTestId("project-registry-error")).toHaveAttribute("data-error-kind", "network");
    await expect(page.getByText(/could not reach ATLAS/i)).toBeVisible();

    recover = true;
    await page.getByTestId("project-registry-retry").click();
    await expect(page.getByTestId("project-registry-status")).toHaveAttribute("data-state", "success");
    await expect(page.getByText("Network Recovery Project", { exact: true })).toBeVisible();
    await expect(page.getByTestId("project-registry-error")).toHaveCount(0);
    expect(stats.projectAttempts).toBeGreaterThanOrEqual(2);
  });
});

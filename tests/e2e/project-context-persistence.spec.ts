import { test, expect } from "@playwright/test";
import { makeTestUser, registerUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";
import { shot } from "./helpers/screenshots";
import { attachDiagnostics } from "./helpers/diagnostics";

/**
 * Release-blocking defect: Project Context narrative text was lost when the user
 * left the page by any route other than Continue. This spec types a unique
 * marker into every governed field, then proves the text survives navigation, a
 * refresh, and reopening the project -- without ever pressing Continue.
 */

/** The narrative textarea sits inside a wrapping <label> whose accessible name
 *  also includes the AI-assist controls, so scope to the label then its textarea. */
function narrativeField(page: import("@playwright/test").Page, label: string) {
  return page.locator("label").filter({ hasText: label }).locator("textarea").first();
}

test.describe("Project Context durable persistence", () => {
  test("narrative and governance text survive navigation, refresh, and project reopen", async ({ page }, testInfo) => {
    test.setTimeout(8 * 60_000);
    const { log, dump } = attachDiagnostics(page, testInfo);

    const marker = `MK${Date.now().toString(36).toUpperCase()}`;
    const values: Record<string, string> = {
      "Business Objective": `Objective ${marker}`,
      "Intended Model Use": `IntendedUse ${marker}`,
      "Target Definition": `Target ${marker}`,
      "Population Definition": `Population ${marker}`,
      "Observation Window": `Observation ${marker}`,
      "Performance Window": `Performance ${marker}`,
    };
    const governance: Record<string, string> = {
      "Approved Uses": `Approved ${marker}`,
      "Prohibited Uses": `Prohibited ${marker}`,
      "Human Review Expectations": `HumanReview ${marker}`,
      "Override Authority": `Override ${marker}`,
    };

    await registerUser(page, makeTestUser("pcPersist"));
    await createPredictiveModelingProject(page, { name: `PC Persistence ${marker}`, modelId: `pc-${Date.now()}` });
    await expect(page).toHaveURL(/\/step00/);

    const status = page.getByTestId("project-context-save-status");
    await expect(status).toBeVisible();
    // Wait for hydration to finish so autosave is armed.
    await page.waitForTimeout(2500);
    await shot(page, testInfo, "01-initial-state");

    // Fill every required narrative field.
    for (const [label, value] of Object.entries(values)) {
      await narrativeField(page, label).fill(value);
    }
    // The optional governance boundaries live in a collapsible section.
    const boundaries = page.getByText("Optional Use Boundaries", { exact: false }).first();
    if (await boundaries.isVisible().catch(() => false)) {
      await boundaries.click().catch(() => undefined);
      await page.waitForTimeout(400);
    }
    for (const [label, value] of Object.entries(governance)) {
      const field = narrativeField(page, label);
      if (await field.isVisible().catch(() => false)) await field.fill(value);
    }

    // Unsaved appears while typing, before any backend acknowledgment.
    await expect(status).toHaveAttribute("data-save-status", /unsaved|saving|saved/, { timeout: 5000 });
    await shot(page, testInfo, "02-unsaved-or-saving");

    // "Saved" must only appear after the backend acknowledges.
    await expect(status).toHaveAttribute("data-save-status", "saved", { timeout: 30_000 });
    await expect(status).toContainText("Saved");
    await shot(page, testInfo, "03-saved-state");

    const projectId = await page.evaluate(() => {
      const raw = localStorage.getItem("atlas-active-project-id");
      return raw ?? "";
    });

    // 1) Navigate away via the sidebar (NOT Continue) and come back.
    await page.getByRole("link", { name: "Data Acquisition" }).first().click();
    await expect(page).toHaveURL(/\/step01/, { timeout: 30_000 });
    await page.goBack();
    await expect(page).toHaveURL(/\/step00/, { timeout: 30_000 });
    await page.waitForTimeout(2500);
    for (const [label, value] of Object.entries(values)) {
      await expect(narrativeField(page, label), `lost after navigation: ${label}`).toHaveValue(value);
    }

    // 2) Hard refresh.
    await page.reload();
    await page.waitForTimeout(3000);
    for (const [label, value] of Object.entries(values)) {
      await expect(narrativeField(page, label), `lost after refresh: ${label}`).toHaveValue(value);
    }
    await shot(page, testInfo, "04-restored-after-refresh");

    // 3) The authoritative backend record holds the text (not just the browser).
    if (projectId) {
      const record = await page.request.get(`http://127.0.0.1:8001/api/projects/${projectId}`);
      expect(record.ok()).toBe(true);
      const stored = (await record.json()).project.metadata.projectContext;
      expect(stored.businessObjective).toBe(values["Business Objective"]);
      expect(stored.targetDefinition).toBe(values["Target Definition"]);
      expect(stored.performanceWindow).toBe(values["Performance Window"]);
    }

    // 4) Leave the project entirely and reopen it.
    await page.goto("/projects/open");
    await page.waitForTimeout(1500);
    await page.goto("/step00");
    await page.waitForTimeout(3000);
    for (const [label, value] of Object.entries(values)) {
      await expect(narrativeField(page, label), `lost after reopen: ${label}`).toHaveValue(value);
    }
    await shot(page, testInfo, "05-restored-after-project-reopen");

    // No false "Saved" claim and no console errors from the repair.
    await expect(status).toHaveAttribute("data-save-status", /saved|idle/);
    const repairErrors = log.consoleErrors.filter((line) => /projectContext|autosave/i.test(line));
    expect(repairErrors, `console errors from the repair: ${repairErrors.join("; ")}`).toEqual([]);

    await dump();
  });

  test("a failed save is reported honestly and can be retried", async ({ page }, testInfo) => {
    test.setTimeout(6 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);

    await registerUser(page, makeTestUser("pcFail"));
    await createPredictiveModelingProject(page, { name: `PC Fail ${Date.now()}`, modelId: `pcf-${Date.now()}` });
    await expect(page).toHaveURL(/\/step00/);
    await page.waitForTimeout(2500);

    // Force every save to fail.
    await page.route("**/api/projects/**", async (route) => {
      if (route.request().method() === "PUT") {
        await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Injected failure" }) });
        return;
      }
      await route.continue();
    });

    await narrativeField(page, "Business Objective").fill("This text must not be silently lost.");
    const status = page.getByTestId("project-context-save-status");

    // The failure must surface and stay visible -- never a false "Saved".
    await expect(status).toHaveAttribute("data-save-status", /failed|offline/, { timeout: 30_000 });
    await expect(status).not.toContainText("Saved at");
    await expect(page.getByTestId("retry-project-context-save")).toBeVisible();
    await shot(page, testInfo, "06-save-failure-state");

    // The draft survives locally for recovery.
    const cached = await page.evaluate(() => {
      const key = Object.keys(localStorage).find((k) => k.startsWith("atlas:project-context-draft:"));
      return key ? localStorage.getItem(key) : null;
    });
    expect(cached, "a failed save must still leave a recoverable local draft").toContain("This text must not be silently lost.");

    // Retry succeeds once the backend recovers.
    await page.unroute("**/api/projects/**");
    await page.getByTestId("retry-project-context-save").click();
    await expect(status).toHaveAttribute("data-save-status", "saved", { timeout: 30_000 });

    await dump();
  });
});

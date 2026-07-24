import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { makeTestUser, registerUser, logout, loginUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";
import { fillProjectContextNarrative, CLASSIFICATION_NARRATIVE, REGRESSION_NARRATIVE } from "./helpers/projectContext";
import { goNext } from "./helpers/workflow";
import { shot } from "./helpers/screenshots";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLASS_FILE = "e2e_audit_classification_dev.csv";
const REG_FILE = "e2e_audit_regression_dev.csv";

/**
 * Predictive Modeling Repair Stage 6.2: confirms the browser dataset cache
 * (src/lib/localDataset.ts) is scoped by (user, project) and can never
 * surface one project's -- or one user's -- cached rows/headers/target in
 * another project's Data Acquisition page. Covers same-tab project
 * switching, two-tab independence, and sign-out/cross-user isolation.
 */
test.describe("Browser dataset state: project and user isolation", () => {
  test("same-tab project switching never leaks a stale dataset banner or wrong target", async ({ page }) => {
    test.setTimeout(6 * 60_000);

    const user = makeTestUser("browserState");
    await registerUser(page, user);

    // Project A: classification, upload + select target.
    await createPredictiveModelingProject(page, { name: "Browser State Classification A", modelId: `bsA-${Date.now()}` });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);
    await page.locator('input[type="file"]').setInputFiles(path.join(__dirname, "data", CLASS_FILE));
    await page.waitForTimeout(4000);
    await page.getByLabel("Target Column").selectOption("Class");
    await page.waitForTimeout(1500);
    await expect(page.getByTestId("dataset-persistence-card").getByText("Workspace Upload", { exact: true })).toBeVisible();
    await shot(page, test.info(), "01-project-a-classification-loaded");

    // Project B: fresh regression project, same tab -- must NOT show any trace of A.
    await createPredictiveModelingProject(page, { name: "Browser State Regression B", modelId: `bsB-${Date.now()}` });
    await fillProjectContextNarrative(page, REGRESSION_NARRATIVE);
    await goNext(page, /\/step01/);
    await expect(page.getByText("Restored the cached modeling dataset", { exact: false })).toHaveCount(0);
    await expect(page.getByText(CLASS_FILE, { exact: false })).toHaveCount(0);
    await expect(page.getByTestId("dataset-persistence-card")).toHaveCount(0); // no dataset loaded yet for B
    await shot(page, test.info(), "02-project-b-regression-empty");

    await page.locator('input[type="file"]').setInputFiles(path.join(__dirname, "data", REG_FILE));
    await page.waitForTimeout(4000);
    await page.getByLabel("Target Column").selectOption("MedHouseVal");
    await page.waitForTimeout(1500);
    await expect(page.getByTestId("dataset-persistence-card").getByText("Workspace Upload", { exact: true })).toBeVisible();
    await shot(page, test.info(), "03-project-b-regression-loaded");

    // Switch back to Project A via Open Existing Project, confirm A's own state restores correctly
    // (not B's regression target/headers), and model type/target remain correct.
    await page.goto("/projects/open");
    await page.getByRole("button", { name: "Open Browser State Classification A" }).click();
    await page.waitForURL(/\/step0\d/, { timeout: 20_000 });
    // Navigate to Data Acquisition explicitly since "open project" may land on the last active step.
    await page.goto(page.url().replace(/\/step\d+.*/, "/step01"));
    await expect(page.getByText("MedHouseVal", { exact: true })).toHaveCount(0);
    await expect(page.getByTestId("dataset-persistence-card").getByText("Workspace Upload", { exact: true })).toBeVisible();
    await shot(page, test.info(), "04-project-a-restored-no-regression-leak");
  });

  test("two browser tabs stay independent, and sign-out prevents the next user from reading the prior cache", async ({ page, context }) => {
    test.setTimeout(6 * 60_000);

    const userA = makeTestUser("browserStateTabA");
    await registerUser(page, userA);
    await createPredictiveModelingProject(page, { name: "Browser State Tab A", modelId: `tabA-${Date.now()}` });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);
    await page.locator('input[type="file"]').setInputFiles(path.join(__dirname, "data", CLASS_FILE));
    await page.waitForTimeout(4000);
    await page.getByLabel("Target Column").selectOption("Class");
    await page.waitForTimeout(1500);
    await expect(page.getByTestId("dataset-persistence-card").getByText("Workspace Upload", { exact: true })).toBeVisible();

    // A second tab in the SAME authenticated context opens a second project.
    // sessionStorage is per-tab, so this must be independent even without any
    // explicit clearing logic -- verifying the scoped-key design doesn't rely
    // on tab-count assumptions.
    const secondTab = await context.newPage();
    await secondTab.goto("/dashboard");
    await createPredictiveModelingProject(secondTab, { name: "Browser State Tab B", modelId: `tabB-${Date.now()}` });
    await fillProjectContextNarrative(secondTab, REGRESSION_NARRATIVE);
    await goNext(secondTab, /\/step01/);
    await expect(secondTab.getByText("Restored the cached modeling dataset", { exact: false })).toHaveCount(0);
    await expect(secondTab.getByTestId("dataset-persistence-card")).toHaveCount(0);
    await shot(secondTab, test.info(), "05-tab-b-independent-of-tab-a");
    await secondTab.close();

    // Sign out user A in tab 1, then a different user signs in in the SAME tab.
    // The prior user's cached dataset must be unreadable to the new identity.
    await logout(page);
    const userB = makeTestUser("browserStateUserB");
    await registerUser(page, userB);
    await createPredictiveModelingProject(page, { name: "Browser State User B Project", modelId: `userB-${Date.now()}` });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);
    await expect(page.getByText("Restored the cached modeling dataset", { exact: false })).toHaveCount(0);
    await expect(page.getByTestId("dataset-persistence-card")).toHaveCount(0);
    await shot(page, test.info(), "06-user-b-no-cross-user-cache");
  });
});

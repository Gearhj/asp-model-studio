import { test, expect } from "@playwright/test";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";
import { makeTestUser, registerUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";

// UX-PROJECTCONTEXT-001 + UX-GLOBAL-HTC-001: the Model Identity card now has a
// distinct light-blue treatment, and the global "How to Choose" dropdown-
// explanation popover (previously triggered by focusing/clicking ANY <select>
// on ANY page) is fully removed. This spec proves both, plus the removal's
// reach beyond Project Context: a later Predictive Modeling page with real
// dropdowns, and a non-Predictive-Modeling workflow page.
const CHOOSER_PANEL_TESTID = "atlas-select-decision-support";

test.describe("Model Identity treatment and global How to Choose removal", () => {
  test("Project Context: Model Identity card is visually distinct and Deployment Mode opens no explanation panel", async ({ page }, testInfo) => {
    test.setTimeout(2 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    await registerUser(page, makeTestUser("htcprojectcontext"));
    await createPredictiveModelingProject(page, { name: "Chooser Panel Removal Test", modelId: `htc-${Date.now()}` });

    await expect(page).toHaveURL(/\/step00/);
    const card = page.getByTestId("model-identity-card");
    await expect(card).toBeVisible();

    // Light-blue, stronger-border, dark-navy-heading treatment (not the deep navy
    // page-header treatment) -- verified via computed styles, not just class names.
    const backgroundColor = await card.evaluate((el) => getComputedStyle(el).backgroundColor);
    const borderColor = await card.evaluate((el) => getComputedStyle(el).borderColor);
    const [bgR, bgG, bgB] = backgroundColor.match(/\d+/g)!.map(Number);
    expect(bgR + bgG + bgB, "Model Identity background must be light, not deep navy").toBeGreaterThan(600);
    expect(borderColor, "Model Identity border must be blue-toned, not slate/neutral").toMatch(/rgb\(\d+, \d+, 2\d\d\)/);

    // Must be visually distinct from the neighboring, already-blue-tinted
    // "Decision Foundation" card -- matching class family alone isn't enough.
    const decisionFoundationBg = await page.locator("#business-decision").evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(backgroundColor, "Model Identity background must differ from the neighboring Decision Foundation card's background").not.toBe(decisionFoundationBg);

    await expect(card.getByText("Governed Identity")).toBeVisible();
    await expect(card.getByText("Project Setup", { exact: true })).toBeVisible();

    // All five identity fields remain present with unchanged values/behavior.
    await expect(card.getByLabel("Model ID", { exact: false })).toBeVisible();
    await expect(card.getByLabel("Project Name", { exact: false })).toHaveValue("Chooser Panel Removal Test");
    await expect(card.getByLabel("Project Type", { exact: false })).toHaveValue("Predictive Modeling");
    await expect(card.getByLabel("Model Type", { exact: false })).toBeVisible();
    const deploymentModeSelect = card.getByLabel("Deployment Mode", { exact: false });
    await expect(deploymentModeSelect).toBeVisible();
    await shot(page, testInfo, "01-project-context-model-identity");

    // No chooser panel exists anywhere before interacting with Deployment Mode.
    await expect(page.getByTestId(CHOOSER_PANEL_TESTID)).toHaveCount(0);
    await expect(page.getByText("How to choose", { exact: false })).toHaveCount(0);

    // Opening (focusing/clicking) Deployment Mode's native dropdown must not
    // spawn any explanation panel -- only the browser's native option list.
    await deploymentModeSelect.click();
    await page.waitForTimeout(300);
    await expect(page.getByTestId(CHOOSER_PANEL_TESTID)).toHaveCount(0);
    await expect(page.getByText("How to choose", { exact: false })).toHaveCount(0);
    await expect(page.getByText("Best used when", { exact: false })).toHaveCount(0);
    await shot(page, testInfo, "02-deployment-mode-open-no-panel");

    // Exactly one concise inline helper line remains beneath Deployment Mode.
    await expect(page.getByText("Development is used while the model is being built and evaluated.", { exact: false })).toBeVisible();

    await dump();
  });

  test("A later Predictive Modeling page with real dropdowns renders no chooser panel", async ({ page }, testInfo) => {
    test.setTimeout(2 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    await registerUser(page, makeTestUser("htclaterpm"));
    await createPredictiveModelingProject(page, { name: "Chooser Panel Later PM Page", modelId: `htclater-${Date.now()}` });

    await page.goto("/step06");
    const holdoutSelect = page.getByLabel("Holdout size", { exact: false });
    await expect(holdoutSelect).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId(CHOOSER_PANEL_TESTID)).toHaveCount(0);

    await holdoutSelect.click();
    await page.waitForTimeout(300);
    await expect(page.getByTestId(CHOOSER_PANEL_TESTID)).toHaveCount(0);
    await expect(page.getByText("How to choose", { exact: false })).toHaveCount(0);
    await shot(page, testInfo, "03-later-pm-page-no-chooser-panel");

    await dump();
  });

  test("A non-Predictive-Modeling workflow page renders no chooser panel", async ({ page }, testInfo) => {
    test.setTimeout(2 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    await registerUser(page, makeTestUser("htcoptimization"));

    await page.goto("/projects/new");
    await page.locator("button[aria-pressed]").filter({ hasText: "Optimization" }).first().click();
    const nameInput = page.getByLabel("Project Name", { exact: false });
    await nameInput.fill("Chooser Panel Optimization Test");
    await page.getByRole("button", { name: "Create Optimization Project" }).click();
    await expect(page).toHaveURL(/\/project-overview/, { timeout: 20_000 });

    await page.goto("/workflow/optimization/1");
    const cadenceSelect = page.getByLabel("Decision cadence", { exact: false });
    await expect(cadenceSelect).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId(CHOOSER_PANEL_TESTID)).toHaveCount(0);

    await cadenceSelect.click();
    await page.waitForTimeout(300);
    await expect(page.getByTestId(CHOOSER_PANEL_TESTID)).toHaveCount(0);
    await expect(page.getByText("How to choose", { exact: false })).toHaveCount(0);
    await expect(page.getByText("Best used when", { exact: false })).toHaveCount(0);
    await shot(page, testInfo, "04-optimization-workflow-no-chooser-panel");

    await dump();
  });
});

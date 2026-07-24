import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SEED_PATH = path.join(
  "C:\\Users\\james\\AppData\\Local\\Temp\\claude\\c--Users-james-ds-workflow-starter\\b3701922-26ad-4231-b773-a6d1a9d5ebff\\scratchpad",
  "scoringRun_seed_state.json"
);

async function resumeSession(page: import("@playwright/test").Page, context: import("@playwright/test").BrowserContext, projectId: string, cookieValue: string, projectName: string) {
  await context.addCookies([{ name: "atlas_session", value: cookieValue, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.addInitScript(
    ({ projectId, name }) => {
      const steps = ["dashboard", "step00", "step01", "step01b", "step02", "step03", "step04", "step05", "step06", "step07", "step08", "step09", "step10", "step11", "step12", "step13"];
      const stepStatus = Object.fromEntries(steps.map((id) => [id, "complete"]));
      const workflowSteps = steps.filter((s) => s !== "dashboard").map((id, index) => ({ id, label: id, route: `/${id}`, status: "complete", order: index }));
      const state = { projectId, modelId: name, projectName: name, projectType: "predictive-modeling", workflowId: "predictive-modeling", workflowSteps, currentStepId: "step10", steps: stepStatus, restoreWarnings: [] };
      window.sessionStorage.setItem("ds-workflow-store", JSON.stringify({ state, version: 0 }));
    },
    { projectId, name: projectName }
  );
}

test.describe("Persistent Scoring Runs, Phase 1", () => {
  test("Visual Intelligence Lab loads a durable scoring run from the URL and survives a refresh", async ({ page, context }, testInfo) => {
    test.setTimeout(3 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    const seed = JSON.parse(fs.readFileSync(SEED_PATH, "utf-8"));
    await resumeSession(page, context, seed.project_id, seed.cookies.atlas_session, "VI Lab Scoring Run Seed");

    const testRunId: string = seed.scoring_run_ids.test;
    await page.goto(`/visual-intelligence-lab?scoringRunId=${encodeURIComponent(testRunId)}`);

    // The selector reflects the URL-driven run, not a manual pick.
    await expect(page.getByTestId("vi-scoring-run-badge")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("vi-scoring-run-select")).toHaveValue(testRunId);
    await shot(page, testInfo, "01-vi-lab-scoring-run-selected");

    // Distribution Explorer renders from the durable scoring-run source, not live workspace state.
    await expect(page.getByTestId("distribution-explorer")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("variable-selector")).toBeVisible();
    await expect(page.getByTestId("scoring-run-source-badge").first()).toBeVisible({ timeout: 15_000 });
    await shot(page, testInfo, "02-vi-lab-distribution-scoring-run");

    // Regression Diagnostic Explorer also resolves from the same durable run.
    await page.getByTestId("vi-tab-regression").click();
    await expect(page.getByTestId("regression-diagnostic-explorer")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("scoring-run-source-badge").first()).toBeVisible({ timeout: 15_000 });
    const regressionText = await page.locator('[data-testid="regression-diagnostic-explorer"]').innerText();
    expect(regressionText).toMatch(/RMSE/);
    await shot(page, testInfo, "03-vi-lab-regression-scoring-run");

    // The core durability claim: a hard refresh reloads the SAME run because its id
    // lives in the URL, not in React state -- unlike Step10_Scoring's plain useState.
    // (The active TAB itself is unrelated, ordinary React state -- Playwright must
    // re-select it after reload, same as a real user would see the default tab.)
    await page.reload();
    await expect(page.getByTestId("vi-scoring-run-select")).toHaveValue(testRunId, { timeout: 20_000 });
    await expect(page.getByTestId("distribution-explorer")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("scoring-run-source-badge").first()).toBeVisible({ timeout: 15_000 });
    await shot(page, testInfo, "04-vi-lab-scoring-run-survives-refresh");

    // Switching back to "Live workspace data" clears the URL param and the durable badge.
    await page.getByTestId("vi-scoring-run-select").selectOption("");
    await expect(page.getByTestId("vi-scoring-run-badge")).toHaveCount(0);

    await dump();
  });

  test("Step10 Scoring page's history panel lists durable runs and links into the Visual Intelligence Lab", async ({ page, context }, testInfo) => {
    test.setTimeout(2 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    const seed = JSON.parse(fs.readFileSync(SEED_PATH, "utf-8"));
    await resumeSession(page, context, seed.project_id, seed.cookies.atlas_session, "VI Lab Scoring Run Seed");

    await page.goto("/step10");
    await expect(page.getByTestId("scoring-history-panel")).toBeVisible({ timeout: 20_000 });
    const rows = page.getByTestId("scoring-history-row");
    await expect(rows.first()).toBeVisible();
    expect(await rows.count()).toBeGreaterThanOrEqual(3); // TRAIN + TEST + OOT seeded runs
    await shot(page, testInfo, "05-step10-scoring-history-panel");

    // Reloading the page re-fetches history from the server, not from session state --
    // this is the concrete "refresh must never be the boundary" proof for Step10 itself.
    await page.reload();
    await expect(page.getByTestId("scoring-history-panel")).toBeVisible({ timeout: 20_000 });
    expect(await page.getByTestId("scoring-history-row").count()).toBeGreaterThanOrEqual(3);

    await dump();
  });
});
